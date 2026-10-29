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

    def test_real_cached_checkout_and_fixed_engine(self):
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
        checkout = self.root / "checkout"
        with patch.object(self.bridge, "APP_SOURCE", self.url),                 patch.object(self.bridge, "ENGINE_SOURCE", engine.as_uri()),                 patch.object(self.bridge, "ENGINE_SHA", engine_sha):
            actual_engine = self.bridge.prepare_sources(self.root / "state", sha, checkout)
        self.assertEqual(git("-C", checkout, "rev-parse", "HEAD"), sha)
        self.assertEqual(git("-C", checkout, "status", "--porcelain"), "")
        self.assertEqual(git("-C", actual_engine, "rev-parse", "refs/heads/pinned"), engine_sha)

    def test_cache_hit_repins_objects_before_nonlocal_clone(self):
        self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        git("-C", self.cache, "update-ref", "-d", "refs/heads/pinned")
        with patch.object(self.bridge, "fetch_source", side_effect=AssertionError("must use verified object")):
            self.bridge.ensure_cached_source(self.cache, self.url, self.sha)
        clone = self.root / "repinned-clone"
        git("clone", "--no-local", "--no-checkout", str(self.cache), str(clone))
        git("-C", clone, "checkout", "--detach", self.sha)
        self.assertEqual(git("-C", clone, "rev-parse", "HEAD"), self.sha)

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
        commands = []
        with patch.object(self.bridge, "prepare_sources", return_value=self.cache) as prepare, \
                patch.object(self.bridge, "run", side_effect=lambda *args, **kwargs: commands.append(args)):
            self.bridge.warm_cache(API(), self.root)
        self.assertEqual(prepare.call_args.args[:2], (self.root, sha))
        self.assertEqual(len(commands), 1)
        self.assertIn("--prepare-only", commands[0])
        self.assertIn("--runtime-cache", commands[0])
        self.assertNotIn("--runtime-offline", commands[0])


if __name__ == "__main__":
    unittest.main()
