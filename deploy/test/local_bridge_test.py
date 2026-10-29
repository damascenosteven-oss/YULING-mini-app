"""Blocking tests for the phone request and workstation relay contract."""
import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ContractTests(unittest.TestCase):
    def test_request_rejects_wrong_owner_and_expired(self):
        bridge = load("local-bridge")
        request = {"schema": 1, "operation": "publish", "run_id": 42,
                   "attempt": 1, "actor": "damascenosteven-oss",
                   "expires_at": "2026-10-27T17:00:00Z"}
        deployment = {"id": 8, "sha": "a" * 40, "ref": "a" * 40,
                      "environment": "ppt-test-local-relay", "creator": {"login": "github-actions[bot]"},
                      "payload": request}
        run = {"id": 42, "run_attempt": 1, "event": "workflow_dispatch",
               "head_branch": "main", "head_sha": "a" * 40, "status": "in_progress",
               "path": ".github/workflows/test-site.yml", "actor": {"login": "damascenosteven-oss"}}
        branch = {"commit": {"sha": "a" * 40}, "protected": True}
        self.assertEqual(bridge.validate(deployment, run, branch, "2026-10-27T16:00:00Z"), "publish")
        with self.assertRaises(ValueError):
            bridge.validate(deployment, {**run, "actor": {"login": "intruder"}}, branch,
                            "2026-10-27T16:00:00Z")
        with self.assertRaises(ValueError):
            bridge.validate(deployment, run, branch, "2026-10-27T17:00:00Z")

    def test_request_rejects_changed_main_or_cancelled_run(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40, "ref": "a" * 40,
                      "environment": "ppt-test-local-relay", "creator": {"login": "github-actions[bot]"},
                      "payload": {"schema": 1, "operation": "rollback", "run_id": 42,
                                  "attempt": 1, "actor": "damascenosteven-oss",
                                  "expires_at": "2026-10-27T17:00:00Z"}}
        run = {"id": 42, "run_attempt": 1, "event": "workflow_dispatch",
               "head_branch": "main", "head_sha": "a" * 40, "status": "in_progress",
               "path": ".github/workflows/test-site.yml", "actor": {"login": "damascenosteven-oss"}}
        with self.assertRaises(ValueError):
            bridge.validate(deployment, run, {"commit": {"sha": "b" * 40}, "protected": True},
                            "2026-10-27T16:00:00Z")
        with self.assertRaises(ValueError):
            bridge.validate(deployment, {**run, "status": "completed"},
                            {"commit": {"sha": "a" * 40}, "protected": True}, "2026-10-27T16:00:00Z")

    def test_required_checks_bind_to_sha(self):
        bridge = load("local-bridge")
        checks = {"check_runs": [{"name": name, "head_sha": "a" * 40, "conclusion": "success", "id": index}
                                for index, name in enumerate(("app-checks", "release-checks"), 1)]}
        bridge.require_checks(checks, "a" * 40)
        checks["check_runs"][0]["head_sha"] = "b" * 40
        with self.assertRaises(ValueError):
            bridge.require_checks(checks, "a" * 40)
        checks["check_runs"][0]["head_sha"] = "a" * 40
        checks["check_runs"].append({"name": "app-checks", "head_sha": "a" * 40,
                                    "conclusion": "failure", "id": 3})
        with self.assertRaises(ValueError):
            bridge.require_checks(checks, "a" * 40)

    def test_duplicate_request_never_reaches_server_and_failure_is_reported(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40}
        class FakeAPI:
            def __init__(self):
                self.calls = []
            def call(self, route, data=None):
                self.calls.append((route, data))
                return {}
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            with patch.object(bridge, "checked_request", return_value="rollback"), \
                    patch.object(bridge, "build_and_transfer", side_effect=RuntimeError("fixture")) as execute:
                with self.assertRaises(RuntimeError):
                    bridge.handle(api, deployment, {}, state_dir)
                bridge.handle(api, deployment, {}, state_dir)
                self.assertEqual(execute.call_count, 1)
        self.assertEqual([data["state"] for _, data in api.calls],
                         ["in_progress", "failure"])

    def test_publish_rechecks_after_upload_before_activation(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40,
                      "payload": {"run_id": 42, "attempt": 1}}
        config = {"host": "115.159.143.24", "ssh_key": "fixture",
                  "known_hosts": "fixture", "state_dir": "/fixture-state"}
        stages = []
        def fake_run(*args, env=None):
            if len(args) > 1 and str(args[1]).endswith("build-image.py"):
                self.assertIn("--runtime-cache", args)
                self.assertIn("--runtime-offline", args)
                self.assertIn("--dependency-cache", args)
                self.assertIn("--dependency-offline", args)
                output = Path(args[args.index("--output") + 1])
                output.mkdir()
                (output / "bundle.tar").write_bytes(b"verified fixture")
                (output / "bundle.sha256").write_text(
                    hashlib.sha256(b"verified fixture").hexdigest() + "  bundle.tar\n")
            if "--stage" in args:
                stages.append(args[args.index("--stage") + 1])
        def git_output(args, **kwargs):
            return "a" * 40 if args[-1] == "HEAD" else b""
        with patch.object(bridge, "prepare_sources", return_value=Path("/verified/engine.git")), \
                patch.object(bridge, "run", side_effect=fake_run), \
                patch.object(bridge, "checked_request", side_effect=["publish", "publish"]) as checked, \
                patch.object(bridge, "secret", return_value="fixture"), \
                patch.object(bridge.subprocess, "check_output", side_effect=git_output):
            bridge.build_and_transfer(object(), deployment, "publish", config)
        self.assertEqual(stages, ["upload", "activate"])
        self.assertEqual(checked.call_count, 2)

    def test_warm_cache_prepares_dependencies_without_publishing(self):
        bridge = load("local-bridge")
        sha = "a" * 40
        class API:
            def call(self, route):
                if route == "/branches/main":
                    return {"protected": True, "commit": {"sha": sha}}
                if route.startswith("/commits/"):
                    return {"check_runs": []}
                raise AssertionError(route)
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bridge, "require_checks"), \
                patch.object(bridge, "prepare_sources", return_value=Path("/verified/engine.git")), \
                patch.object(bridge, "run", side_effect=lambda *args: calls.append(args)):
            bridge.warm_cache(API(), Path(tmp))
        self.assertEqual(len(calls), 1)
        self.assertIn("--prepare-only", calls[0])
        self.assertIn("--dependency-cache", calls[0])
        self.assertNotIn("--dependency-offline", calls[0])

    def test_rollback_uses_restricted_client_without_build(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40,
                      "payload": {"run_id": 42, "attempt": 1}}
        config = {"host": "115.159.143.24", "ssh_key": "fixture",
                  "known_hosts": "fixture", "trusted_client": "/trusted/ssh-client.py"}
        commands = []
        with patch.object(bridge, "run", side_effect=lambda *args, **kwargs: commands.append(args)), \
                patch.object(bridge, "checked_request", return_value="rollback"), \
                patch.object(bridge, "secret", return_value="fixture"):
            bridge.build_and_transfer(object(), deployment, "rollback", config)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][-1], "rollback")

    def test_bad_bundle_digest_never_uploads(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40,
                      "payload": {"run_id": 42, "attempt": 1}}
        stages = []
        def fake_run(*args, env=None):
            if len(args) > 1 and str(args[1]).endswith("build-image.py"):
                output = Path(args[args.index("--output") + 1])
                output.mkdir()
                (output / "bundle.tar").write_bytes(b"fixture")
                (output / "bundle.sha256").write_text("0" * 64 + "  bundle.tar\n")
            if "--stage" in args:
                stages.append(args[args.index("--stage") + 1])
        def git_output(args, **kwargs):
            return "a" * 40 if args[-1] == "HEAD" else b""
        with patch.object(bridge, "prepare_sources", return_value=Path("/verified/engine.git")), \
                patch.object(bridge, "run", side_effect=fake_run), \
                patch.object(bridge.subprocess, "check_output", side_effect=git_output):
            with self.assertRaises(bridge.StepFailure) as raised:
                bridge.build_and_transfer(object(), deployment, "publish", {"state_dir": "/fixture-state"})
        self.assertEqual(raised.exception.step, "bundle_digest")
        self.assertEqual(stages, [])

    def test_offline_build_failure_never_uploads_or_activates(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40,
                      "payload": {"run_id": 42, "attempt": 1}}
        commands = []
        def fail_build(*args, env=None):
            commands.append(args)
            if str(args[1]).endswith("build-image.py"):
                self.assertIn("--dependency-offline", args)
                raise RuntimeError("simulated missing dependency cache")
            raise AssertionError("A failed build must not start SSH transfer")
        with patch.object(bridge, "prepare_sources", return_value=Path("/verified/engine.git")), \
                patch.object(bridge, "run", side_effect=fail_build):
            with self.assertRaises(bridge.StepFailure) as raised:
                bridge.build_and_transfer(object(), deployment, "publish", {"state_dir": "/fixture-state"})
        self.assertEqual(raised.exception.step, "pinned_image_build")
        self.assertEqual(len(commands), 1)

    def test_upload_failure_never_activates(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40,
                      "payload": {"run_id": 42, "attempt": 1}}
        config = {"host": "115.159.143.24", "ssh_key": "fixture",
                  "known_hosts": "fixture", "state_dir": "/fixture-state"}
        stages = []
        def fake_run(*args, env=None):
            if len(args) > 1 and str(args[1]).endswith("build-image.py"):
                output = Path(args[args.index("--output") + 1])
                output.mkdir()
                (output / "bundle.tar").write_bytes(b"fixture")
                (output / "bundle.sha256").write_text(
                    hashlib.sha256(b"fixture").hexdigest() + "  bundle.tar\n")
            if "--stage" in args:
                stage = args[args.index("--stage") + 1]
                stages.append(stage)
                if stage == "upload":
                    raise OSError("simulated interruption")
        def git_output(args, **kwargs):
            return "a" * 40 if args[-1] == "HEAD" else b""
        with patch.object(bridge, "prepare_sources", return_value=Path("/verified/engine.git")), \
                patch.object(bridge, "run", side_effect=fake_run), \
                patch.object(bridge, "checked_request", return_value="publish"), \
                patch.object(bridge, "secret", return_value="fixture"), \
                patch.object(bridge.subprocess, "check_output", side_effect=git_output):
            with self.assertRaises(bridge.StepFailure) as raised:
                bridge.build_and_transfer(object(), deployment, "publish", config)
        self.assertEqual(raised.exception.step, "restricted_upload")
        self.assertEqual(stages, ["upload"])

    def test_source_failure_never_builds_uploads_or_activates(self):
        bridge = load("local-bridge")
        deployment = {"id": 8, "sha": "a" * 40,
                      "payload": {"run_id": 42, "attempt": 1}}
        commands = []
        with patch.object(bridge, "prepare_sources", side_effect=OSError("source unavailable")), \
                patch.object(bridge, "run", side_effect=lambda *args, **kwargs: commands.append(args)):
            with self.assertRaises(bridge.StepFailure) as raised:
                bridge.build_and_transfer(object(), deployment, "publish", {"state_dir": "/fixture-state"})
        self.assertEqual(raised.exception.step, "checkout")
        self.assertEqual(commands, [])

    def test_relay_continues_after_one_failed_request_without_retrying_it(self):
        bridge = load("local-bridge")
        first = {"id": 101, "sha": "a" * 40, "payload": {"operation": "publish"}}
        second = {"id": 102, "sha": "b" * 40, "payload": {"operation": "publish"}}
        class API:
            def __init__(self):
                self.poll = 0
                self.states = {}
            def call(self, route, data=None):
                if route.startswith("/deployments?"):
                    self.poll += 1
                    return [first] if self.poll == 1 else [first, second]
                if route.endswith("/statuses?per_page=1"):
                    identity = int(route.split("/")[2])
                    return [{"state": self.states.get(identity, "pending")}]
                if route.endswith("/statuses"):
                    identity = int(route.split("/")[2])
                    self.states[identity] = data["state"]
                    return {}
                raise AssertionError(route)
        api = API()
        calls = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bridge, "checked_request", return_value="publish"), \
                patch.object(bridge, "build_and_transfer",
                             side_effect=[bridge.StepFailure("pinned_image_build"), None]) as build:
            def pause(_):
                if api.poll == 2:
                    raise StopIteration
            with patch.object(bridge.time, "sleep", side_effect=pause):
                with self.assertRaises(StopIteration):
                    bridge.poll_continuously(api, {}, Path(tmp))
            calls.extend((build.call_count, api.states[101], api.states[102]))
        self.assertEqual(calls, [2, "failure", "success"])


if __name__ == "__main__":
    unittest.main()
