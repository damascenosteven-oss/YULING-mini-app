"""Phone entry -> relay -> immutable package -> restricted-client boundary."""
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bridge = load("local-bridge")
        self.phone = load("phone-request")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.sha = "a" * 40
        self.commands = []
        self.ssh = []
        self.config = {"state_dir": str(self.state), "host": "115.159.143.24", "ssh_key": "fixture",
                       "known_hosts": "fixture", "trusted_client": "/trusted/ssh-client.py"}
        test = self
        class API:
            def __init__(self, token=None):
                self.deployments = []
                self.states = {}
                self.run = 42
                self.cancelled = False
                self.main_sha = test.sha
            def call(self, route, data=None):
                if route == "/deployments":
                    dep = {**data, "id": len(self.deployments) + 1, "sha": data["ref"],
                           "creator": {"login": "github-actions[bot]"}}
                    self.deployments.append(dep)
                    return dep
                if route.startswith("/deployments?"):
                    return [d for d in self.deployments if "environment=" + d["environment"] + "&" in route]
                if route.startswith("/actions/runs/"):
                    return {"id": self.run, "run_attempt": 1, "event": "workflow_dispatch", "head_branch": "main",
                            "head_sha": test.sha, "status": "completed" if self.cancelled else "in_progress",
                            "path": ".github/workflows/test-site.yml", "actor": {"login": test.bridge.OWNER}}
                if route == "/branches/main": return {"protected": True, "commit": {"sha": self.main_sha}}
                if route.startswith("/commits/"):
                    return {"check_runs": [{"name": n, "head_sha": test.sha, "id": i, "conclusion": "success"}
                                           for i, n in enumerate(test.bridge.CHECKS)]}
                if route.startswith("/deployments/"):
                    identity = int(route.split("/")[2])
                    if data is not None:
                        self.states[identity] = data
                        return {}
                    return [self.states[identity]] if identity in self.states else []
                raise AssertionError(route)
        self.api = API()

    def source(self, state, sha, checkout):
        checkout.mkdir()
        (checkout / "deploy/test").mkdir(parents=True)
        for name, data in (("package.json", "{}"), ("pnpm-lock.yaml", "lockfileVersion: 9.0\n"),
                           ("deploy/test/runtime-lock.json", "{}"), ("deploy/test/ssh-client.py", "# fixture")):
            (checkout / name).write_text(data)
        return Path("/fixture/engine.git")

    def audits(self, output, checkout):
        audit = output / "fresh-audits"
        audit.mkdir(parents=True)
        inputs = {k: hashlib.sha256((checkout / name).read_bytes()).hexdigest() for k, name in zip(
            self.bridge.prepared.INPUTS, ("package.json", "pnpm-lock.yaml", "deploy/test/runtime-lock.json"))}
        for name in ("audit-full.json", "audit-prod.json"):
            (audit / name).write_text(json.dumps({"metadata": {"vulnerabilities": {
                k: 0 for k in ("info", "low", "moderate", "high", "critical")}}}))
        (audit / "audit.json").write_text(json.dumps({**inputs, "audited_at": self.bridge.prepared.now_utc().isoformat()}))

    def execute(self, *args, env=None):
        self.commands.append(tuple(map(str, args)))
        script = str(args[1])
        if script.endswith("build-image.py"):
            output = Path(args[args.index("--output") + 1])
            output.mkdir()
            checkout = Path(script).parents[2]
            self.audits(output, checkout)
            if "--audit-only" in args: return
            (output / "bundle.tar").write_bytes(b"complete verified fixture")
            (output / "bundle.sha256").write_text(hashlib.sha256((output / "bundle.tar").read_bytes()).hexdigest() + "  bundle.tar\n")
            manifest = {"app_sha": self.sha, "engine_sha": self.bridge.ENGINE_SHA,
                        "release": self.sha[:12] + "-42-1", "image_id": "sha256:" + "b" * 64}
            (output / "release.json").write_text(json.dumps(manifest))
            (output / "image.json").write_text("{}")
        elif script.endswith("verify-image.py"):
            output = Path(args[-1])
            (output / "image-memory.txt").write_text("oom 0\n")
            from http_evidence import CASES
            report = {"schema": 1, "app_sha": self.sha, "image_id": "sha256:" + "b" * 64,
                      "checker_sha256": "c" * 64, "fixture_sha256": "d" * 64,
                      "simulated_providers": True, "cloud_calls": 0, "passed": True,
                      "cases": [{"case": c, "passed": True, "step": "complete", "http": 200,
                                 "elapsedMs": 1, "searches": 0, "models": 1, "network": "none",
                                 "resources": {"available": False}} for c in CASES]}
            (output / "outline-entry.json").write_text(json.dumps(report))
            (output / "packaged-candidate").mkdir()
            (output / "packaged-candidate/result.json").write_text("{}")
            m = json.loads((output / "release.json").read_text())
            (output / "verification.json").write_text(json.dumps({"schema": 1, "app_sha": self.sha,
                "engine_sha": self.bridge.ENGINE_SHA, "image_id": m["image_id"], "source_dirty": False,
                "pages": 12, "captures": 2, "differences": 0}))
        elif script.endswith("ssh-client.py"):
            self.ssh.append(args[args.index("--stage") + 1] if "--stage" in args else "rollback")
        else: raise AssertionError(args)

    def request(self, operation):
        env = {"GITHUB_REPOSITORY": "damascenosteven-oss/YULING-mini-app", "GITHUB_ACTOR": self.bridge.OWNER,
               "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": self.sha, "GITHUB_RUN_ID": str(self.api.run),
               "GITHUB_RUN_ATTEMPT": "1", "OPERATION": operation, "GITHUB_TOKEN": "fixture"}
        original = self.api.call
        dispatching = False
        def call(route, data=None):
            nonlocal dispatching
            if route.endswith("/statuses?per_page=1") and data is None:
                identity = int(route.split("/")[2])
                state = self.api.states.get(identity, {})
                if state.get("state") == "pending" and not dispatching:
                    dispatching = True
                    try:
                        self.bridge.poll_once(self.api, self.config, self.state)
                    finally:
                        dispatching = False
            return original(route, data)
        # Dispatch via the actual phone CLI function, then actual relay validation and handler.
        with patch.dict(os.environ, env), patch.object(self.phone, "GitHub", return_value=self.api), \
                patch.object(self.phone.signal, "signal"), patch.object(self.api, "call", side_effect=call):
            self.phone.main()
        self.api.run += 1

    def test_real_phone_prepare_then_publish_without_download_or_build(self):
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), \
                patch.object(self.bridge, "run", side_effect=self.execute), \
                patch.object(self.bridge, "secret", side_effect=AssertionError("prepare must not read SSH secrets")):
            self.request("prepare")
        self.assertEqual(self.ssh, [])
        self.assertEqual(self.api.deployments[0]["environment"], self.bridge.PREPARE_ENVIRONMENT)
        self.assertEqual(self.api.states[1]["state"], "success")
        before = list(self.commands)
        with patch.object(self.bridge, "prepare_sources", side_effect=AssertionError("publish cannot fetch")), \
                patch.object(self.bridge, "run", side_effect=self.execute), \
                patch.object(self.bridge, "secret", return_value="fixture"), \
                patch("urllib.request.urlopen", side_effect=AssertionError("package registries unavailable")):
            self.request("publish")
        self.assertEqual(self.ssh, ["upload", "activate"])
        self.assertEqual(len(self.commands) - len(before), 2)
        self.assertEqual(self.api.states[2]["state"], "success")
        self.assertEqual(self.api.deployments[1]["environment"], self.bridge.ENVIRONMENT)
        self.bridge.handle(self.api, self.api.deployments[1], self.config, self.state)
        self.assertEqual(self.ssh, ["upload", "activate"])

    def test_expired_prepare_refreshes_only_audits_and_keeps_exact_bundle(self):
        now = datetime.now(timezone.utc)
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), \
                patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
            package = self.state / "prepared-releases" / self.sha
            bundle = (package / "bundle.tar").read_bytes()
            self.commands.clear()
            with patch.object(self.bridge.prepared, "now_utc", return_value=now + timedelta(hours=25)):
                self.request("prepare")
            self.assertEqual(len(self.commands), 1)
            self.assertIn("--audit-only", self.commands[0])
            self.assertEqual((package / "bundle.tar").read_bytes(), bundle)
            self.assertEqual(self.ssh, [])

    def test_failed_prepare_reports_failure_and_never_reads_server_credentials(self):
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), \
                patch.object(self.bridge, "run", side_effect=RuntimeError("build fixture failure")), \
                patch.object(self.bridge, "secret", side_effect=AssertionError("no credentials")):
            with self.assertRaises(self.bridge.StepFailure): self.request("prepare")
        self.assertEqual(self.api.states[1]["state"], "failure")
        self.assertFalse((self.state / "prepared-releases" / self.sha).exists())

    def test_http_failure_keeps_stage_before_temporary_cleanup(self):
        def failed(*args, **kwargs):
            if str(args[1]).endswith("verify-image.py"):
                import subprocess
                output = Path(args[args.index("--build-output") + 1])
                (output / "image-check-error.json").write_text(json.dumps({"schema": 1,
                    "stage": "outline_http_entry", "code": "image_check_failed", "exit_code": 1}))
                raise subprocess.CalledProcessError(6, ["private-command"])
            self.execute(*args, **kwargs)
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), \
                patch.object(self.bridge, "run", side_effect=failed):
            with self.assertRaises(self.bridge.StepFailure): self.request("prepare")
        self.assertTrue((self.state / "1-image-check-error.json").exists(), "HTTP failure stage was discarded")
        self.assertEqual(self.ssh, [])

    def test_permission_failure_reaches_phone_and_keeps_safe_diagnostic(self):
        def failed(*args, **kwargs):
            if str(args[1]).endswith("verify-image.py"):
                import subprocess
                output = Path(args[args.index("--build-output") + 1])
                (output / "image-check-error.json").write_text(json.dumps({"schema": 1,
                    "stage": "runtime_permissions", "code": "image_permission_denied", "exit_code": 1}))
                raise subprocess.CalledProcessError(5, ["private-command"])
            self.execute(*args, **kwargs)
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), \
                patch.object(self.bridge, "run", side_effect=failed), \
                patch.object(self.bridge, "secret", side_effect=AssertionError("no credentials")):
            with self.assertRaises(self.bridge.StepFailure) as stopped:
                self.request("prepare")
        self.assertEqual(stopped.exception.code, "image_permission_denied")
        self.assertIn("image_permission_denied", self.api.states[1]["description"])
        diagnostic = json.loads((self.state / "1-image-check-error.json").read_text())
        self.assertEqual(diagnostic["stage"], "runtime_permissions")
        self.assertNotIn("private", json.dumps(diagnostic) + self.api.states[1]["description"])
        self.assertFalse((self.state / "prepared-releases" / self.sha).exists())
        self.assertEqual(self.ssh, [])
        # The next new request succeeds; the failed request remains recorded.
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
        self.assertEqual(self.api.states[2]["state"], "success")

    def test_cancel_after_upload_prevents_activation_and_retains_package(self):
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
        def upload(*args, **kwargs):
            self.execute(*args, **kwargs)
            if self.ssh == ["upload"]: self.api.cancelled = True
        with patch.object(self.bridge, "run", side_effect=upload), patch.object(self.bridge, "secret", return_value="fixture"):
            with self.assertRaises(self.bridge.StepFailure): self.request("publish")
        self.assertEqual(self.ssh, ["upload"])
        self.assertTrue((self.state / "prepared-releases" / self.sha / "bundle.tar").exists())

    def test_legacy_wrong_owner_expiry_and_changed_main_are_rejected(self):
        env = {"GITHUB_REPOSITORY": "damascenosteven-oss/YULING-mini-app", "GITHUB_ACTOR": self.bridge.OWNER,
               "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": self.sha, "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1", "OPERATION": "prepare"}
        dep = self.api.call("/deployments", {"ref": self.sha, "environment": self.bridge.PREPARE_ENVIRONMENT,
            "payload": {**self.phone.identity(env), "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}})
        dep["payload"].pop("sha")
        run = self.api.call("/actions/runs/42")
        branch = self.api.call("/branches/main")
        self.bridge.validate(dep, run, branch, datetime.now(timezone.utc).isoformat())
        dep["payload"]["schema"] = 1
        with self.assertRaises(ValueError): self.bridge.validate(dep, run, branch, datetime.now(timezone.utc).isoformat())
        dep["payload"]["schema"] = 2
        for modified in ({**run, "actor": {"login": "intruder"}}, {**run, "status": "completed"}):
            with self.assertRaises(ValueError): self.bridge.validate(dep, modified, branch, datetime.now(timezone.utc).isoformat())
        with self.assertRaises(ValueError): self.bridge.validate(dep, run, {**branch, "commit": {"sha": "b" * 40}}, datetime.now(timezone.utc).isoformat())

    def test_rollback_never_constructs_a_package(self):
        with patch.object(self.bridge, "run", side_effect=self.execute), patch.object(self.bridge, "secret", return_value="fixture"), \
                patch.object(self.bridge, "prepare_sources", side_effect=AssertionError("rollback cannot fetch")):
            self.request("rollback")
        self.assertEqual(self.ssh, ["rollback"])

    def test_valid_prepare_reuses_package_without_audit_or_source_access(self):
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
        with patch.object(self.bridge, "prepare_sources", side_effect=AssertionError("must reuse")), \
                patch.object(self.bridge, "run", side_effect=AssertionError("must not rebuild/audit")):
            self.request("prepare")
        self.assertEqual(self.api.states[2]["state"], "success")

    def test_main_change_during_preparation_never_accepts_package(self):
        def changed(*args, **kwargs):
            self.execute(*args, **kwargs)
            if str(args[1]).endswith("verify-image.py"): self.api.main_sha = "b" * 40
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=changed):
            with self.assertRaises(self.bridge.StepFailure): self.request("prepare")
        self.assertFalse((self.state / "prepared-releases" / self.sha).exists())
        self.assertEqual(self.ssh, [])

    def test_upload_failure_is_not_retried_or_activated(self):
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
        def failed(*args, **kwargs):
            self.execute(*args, **kwargs)
            raise OSError("fixture interrupted transport")
        with patch.object(self.bridge, "run", side_effect=failed), patch.object(self.bridge, "secret", return_value="fixture"):
            with self.assertRaises(self.bridge.StepFailure): self.request("publish")
        self.assertEqual(self.ssh, ["upload"])
        self.bridge.handle(self.api, self.api.deployments[1], self.config, self.state)
        self.assertEqual(self.ssh, ["upload"])

    def test_missing_or_expired_package_cannot_publish_and_next_request_can_prepare(self):
        with self.assertRaises(self.bridge.StepFailure): self.request("publish")
        self.api.run += 1
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
        with patch.object(self.bridge.prepared, "now_utc", return_value=datetime.now(timezone.utc) + timedelta(hours=25)), \
                patch.object(self.bridge, "run", side_effect=AssertionError("expired package must not upload")):
            with self.assertRaises(self.bridge.StepFailure): self.request("publish")
        self.assertEqual(self.ssh, [])

    def test_damaged_package_reports_inspection_instead_of_reprepare_loop(self):
        with patch.object(self.bridge, "prepare_sources", side_effect=self.source), patch.object(self.bridge, "run", side_effect=self.execute):
            self.request("prepare")
        (self.state / "prepared-releases" / self.sha / "bundle.tar").write_bytes(b"damaged")
        with self.assertRaises(self.bridge.StepFailure): self.request("publish")
        self.assertIn("inspect workstation package", self.api.states[2]["description"])


if __name__ == "__main__": unittest.main()
