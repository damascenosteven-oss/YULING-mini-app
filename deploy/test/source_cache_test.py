"""Verified, fixed-origin source cache used by the workstation relay."""
import importlib.util
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


def load_bridge():
    path = Path(__file__).with_name("local-bridge.py")
    spec = importlib.util.spec_from_file_location("local_bridge_cache_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args):
    return subprocess.check_output(["git", *map(str, args)], text=True,
                                   stderr=subprocess.DEVNULL).strip()


class SourceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        subprocess.run(["git", "init", "-q", str(self.source)], check=True)
        git("-C", self.source, "config", "user.name", "Test")
        git("-C", self.source, "config", "user.email", "test@example.invalid")
        (self.source / "file.txt").write_text("one")
        git("-C", self.source, "add", ".")
        git("-C", self.source, "commit", "-qm", "one")
        self.sha = git("-C", self.source, "rev-parse", "HEAD")
        self.url = self.source.as_uri()
        self.cache = self.root / "state" / "source-cache" / "app.git"
        self.bridge = load_bridge()

    def test_first_fill_hit_and_new_commit(self):
        self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        self.assertEqual(git("-C", self.cache, "rev-parse", self.sha + "^{commit}"), self.sha)
        with patch.object(self.bridge, "fetch_source", side_effect=AssertionError("unexpected fetch")):
            self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        (self.source / "file.txt").write_text("two")
        git("-C", self.source, "commit", "-qam", "two")
        newer = git("-C", self.source, "rev-parse", "HEAD")
        self.bridge.ensure_cached_source(self.cache, self.url, newer)
        self.assertEqual(git("-C", self.cache, "rev-parse", newer + "^{commit}"), newer)

    def test_wrong_origin_and_corrupt_object_fail_closed(self):
        self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        git("-C", self.cache, "remote", "set-url", "origin", "https://example.invalid/other.git")
        with self.assertRaises(ValueError):
            self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        git("-C", self.cache, "remote", "set-url", "origin", self.url)
        object_file = self.cache / "objects" / self.sha[:2] / self.sha[2:]
        object_file.chmod(0o600)
        object_file.write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            self.bridge.ensure_cached_source(self.cache, self.url, self.sha)

    def test_two_transient_failures_then_success_and_three_failures(self):
        original = self.bridge.fetch_source
        attempts = []
        def flaky(cache, sha):
            attempts.append(sha)
            if len(attempts) <= 2:
                raise subprocess.TimeoutExpired("git fetch", 90)
            return original(cache, sha)
        with patch.object(self.bridge, "fetch_source", side_effect=flaky), \
                patch.object(self.bridge.time, "sleep") as sleep:
            self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        self.assertEqual(len(attempts), 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list if call.args[0] in (2, 5)], [2, 5])
        with patch.object(self.bridge, "fetch_source", side_effect=OSError("TLS")) as fetch, \
                patch.object(self.bridge.time, "sleep"):
            with self.assertRaises(OSError):
                self.bridge.ensure_cached_source(self.root / "other.git", self.url, self.sha)
        self.assertEqual(fetch.call_count, 3)
        self.assertFalse((self.root / "other.git").exists())
        self.assertEqual(list(self.root.glob("source-*")), [])

    def test_fetch_has_a_ninety_second_limit(self):
        with patch.object(self.bridge.subprocess, "run") as execute:
            self.bridge.fetch_source(self.cache, self.sha)
        self.assertEqual(execute.call_args.kwargs["timeout"], 90)

    def test_missing_commit_never_substitutes_old_one(self):
        self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        with patch.object(self.bridge, "fetch_source", side_effect=OSError("network")), \
                patch.object(self.bridge.time, "sleep"):
            with self.assertRaises(OSError):
                self.bridge.ensure_cached_source(self.cache, self.url, "f" * 40)

    def test_request_to_verified_cache_build_upload_and_status(self):
        engine = self.root / "engine"
        subprocess.run(["git", "init", "-q", str(engine)], check=True)
        git("-C", engine, "config", "user.name", "Test")
        git("-C", engine, "config", "user.email", "test@example.invalid")
        (engine / "engine.txt").write_text("fixed engine")
        git("-C", engine, "add", ".")
        git("-C", engine, "commit", "-qm", "engine")
        engine_sha = git("-C", engine, "rev-parse", "HEAD")
        (self.source / "deploy" / "test").mkdir(parents=True)
        (self.source / "deploy" / "test" / "runtime-lock.json").write_text(
            json.dumps({"engine_sha": engine_sha}))
        git("-C", self.source, "add", ".")
        git("-C", self.source, "commit", "-qm", "lock")
        sha = git("-C", self.source, "rev-parse", "HEAD")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        deployment = {"id": 99, "sha": sha, "ref": sha,
                      "environment": self.bridge.ENVIRONMENT,
                      "creator": {"login": "github-actions[bot]"},
                      "payload": {"schema": 1, "operation": "publish", "run_id": 42,
                                  "attempt": 1, "actor": self.bridge.OWNER,
                                  "expires_at": expiry}}
        class API:
            def __init__(self):
                self.states = ["pending"]
            def call(self, route, data=None):
                if data is not None:
                    self.states.insert(0, data["state"])
                    return {}
                if route.startswith("/actions/runs/"):
                    return {"id": 42, "run_attempt": 1, "event": "workflow_dispatch",
                            "head_branch": "main", "head_sha": sha, "status": "in_progress",
                            "path": ".github/workflows/test-site.yml",
                            "actor": {"login": "damascenosteven-oss"}}
                if route == "/branches/main":
                    return {"commit": {"sha": sha}, "protected": True}
                if "/check-runs" in route:
                    return {"check_runs": [{"name": name, "head_sha": sha,
                                            "conclusion": "success", "id": number}
                                           for number, name in enumerate(("app-checks", "release-checks"), 1)]}
                if "/statuses" in route:
                    return [{"state": self.states[0]}]
                raise AssertionError(route)
        api = API()
        stages = []
        def fake_run(*args, env=None):
            if str(args[1]).endswith("build-image.py"):
                self.assertEqual(args[args.index("--engine") + 1].name, "engine.git")
                output = Path(args[args.index("--output") + 1])
                output.mkdir()
                data = b"verified bundle"
                (output / "bundle.tar").write_bytes(data)
                (output / "bundle.sha256").write_text(hashlib.sha256(data).hexdigest())
            if "--stage" in args:
                stages.append(args[args.index("--stage") + 1])
        config = {"state_dir": str(self.root / "state"), "host": "115.159.143.24",
                  "ssh_key": "fixture", "known_hosts": "fixture"}
        (self.root / "state").mkdir()
        with patch.object(self.bridge, "APP_SOURCE", self.url), \
                patch.object(self.bridge, "ENGINE_SOURCE", engine.as_uri()), \
                patch.object(self.bridge, "ENGINE_SHA", engine_sha), \
                patch.object(self.bridge, "run", side_effect=fake_run), \
                patch.object(self.bridge, "secret", return_value="fixture"):
            self.bridge.handle(api, deployment, config, self.root / "state")
        self.assertEqual(stages, ["upload", "activate"])
        self.assertEqual(api.states[:3], ["success", "in_progress", "pending"])

    def test_warm_entry_only_checks_main_and_prepares_sources(self):
        sha = "a" * 40
        class API:
            def call(self, route):
                if route == "/branches/main":
                    return {"protected": True, "commit": {"sha": sha}}
                if route.startswith("/commits/"):
                    return {"check_runs": [{"name": name, "head_sha": sha,
                                            "conclusion": "success", "id": number}
                                           for number, name in enumerate(("app-checks", "release-checks"), 1)]}
                raise AssertionError(route)
        with patch.object(self.bridge, "prepare_sources", return_value=self.cache) as prepare, \
                patch.object(self.bridge, "run", side_effect=AssertionError("server or build called")):
            self.bridge.warm_cache(API(), self.root)
        self.assertEqual(prepare.call_args.args[:2], (self.root, sha))


if __name__ == "__main__":
    unittest.main()
