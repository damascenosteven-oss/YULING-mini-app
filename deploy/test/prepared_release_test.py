"""Source-bound preparation and immutable publication contract."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from local_bridge_test import load


class PreparedTests(unittest.TestCase):
    def setUp(self):
        self.m = load("prepared_release")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sha = "a" * 40
        self.now = datetime(2026, 10, 29, 4, tzinfo=timezone.utc)

    def package(self):
        p = self.root / "package"
        p.mkdir()
        manifest = {"app_sha": self.sha, "engine_sha": self.m.ENGINE_SHA,
                    "release": self.sha[:12] + "-42-1", "image_id": "sha256:" + "b" * 64}
        (p / "bundle.tar").write_bytes(b"immutable fixture package")
        (p / "bundle.sha256").write_text(hashlib.sha256((p / "bundle.tar").read_bytes()).hexdigest() + "  bundle.tar\n")
        (p / "release.json").write_text(json.dumps(manifest))
        (p / "ssh-client.py").write_text("# verified client fixture\n")
        inputs = {"package_sha256": "c" * 64, "lock_sha256": "d" * 64,
                  "runtime_sha256": "e" * 64}
        (p / "inputs.json").write_text(json.dumps(inputs))
        (p / "verification.json").write_text(json.dumps({"schema": 1, "app_sha": self.sha,
            "engine_sha": self.m.ENGINE_SHA, "image_id": manifest["image_id"],
            "source_dirty": False, "pages": 12, "captures": 2, "differences": 0}))
        audit = p / "audits" / "initial"
        audit.mkdir(parents=True)
        for name in ("audit-full.json", "audit-prod.json"):
            (audit / name).write_text(json.dumps({"metadata": {"vulnerabilities": {
                k: 0 for k in ("info", "low", "moderate", "high", "critical")}}}))
        (audit / "audit.json").write_text(json.dumps({**inputs, "audited_at": self.now.isoformat()}))
        self.m.seal(p, self.sha, "initial", now=self.now)
        return p

    def test_valid_expired_future_and_wrong_source(self):
        p = self.package()
        self.m.validate(p, self.sha, now=self.now)
        for sha, now in (("b" * 40, self.now), (self.sha, self.now + timedelta(hours=24)),
                         (self.sha, self.now - timedelta(seconds=1))):
            with self.subTest(sha=sha, now=now), self.assertRaises(ValueError):
                self.m.validate(p, sha, now=now)

    def test_corruption_missing_receipt_and_symlink_are_rejected(self):
        p = self.package()
        (p / "bundle.tar").write_bytes(b"corrupt")
        with self.assertRaises(ValueError): self.m.validate(p, self.sha, now=self.now)
        with self.assertRaises(ValueError): self.m.refresh(p, p / "audits/initial", self.sha, now=self.now)
        (p / "receipt.json").unlink()
        with self.assertRaisesRegex(ValueError, "prepared_evidence_missing"):
            self.m.validate(p, self.sha, now=self.now)

    def test_lock_refuses_concurrent_operations(self):
        with self.m.locked(self.root):
            with self.assertRaises(ValueError):
                with self.m.locked(self.root): pass

    def test_receipt_cannot_hide_missing_or_invalid_audit(self):
        p = self.package()
        audit = p / "audits/initial/audit-full.json"
        audit.write_text("{}")
        with self.assertRaises(ValueError): self.m.seal(p, self.sha, "initial", now=self.now)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink boundary exercised in Linux CI")
    def test_symlink_and_receipt_path_escape_are_rejected(self):
        p = self.package()
        outside = self.root / "outside"
        outside.write_bytes(b"not package content")
        (p / "external").symlink_to(outside)
        with self.assertRaises(ValueError): self.m.validate(p, self.sha, now=self.now)
        (p / "external").unlink()
        receipt = json.loads((p / "receipt.json").read_text())
        receipt["files"]["../outside"] = hashlib.sha256(outside.read_bytes()).hexdigest()
        (p / "receipt.json").write_text(json.dumps(receipt))
        with self.assertRaises(ValueError): self.m.validate(p, self.sha, now=self.now)

    def test_failed_refresh_keeps_previous_acceptance_record(self):
        p = self.package()
        previous = (p / "receipt.json").read_bytes()
        bad = self.root / "bad-audits"
        bad.mkdir()
        (bad / "audit.json").write_text("{}")
        with self.assertRaises(ValueError): self.m.refresh(p, bad, self.sha, now=self.now)
        self.assertEqual((p / "receipt.json").read_bytes(), previous)
        self.m.validate(p, self.sha, now=self.now)

    def test_retention_keeps_two_verified_packages_and_unrelated_data(self):
        import shutil
        original = self.package()
        for number, sha in enumerate(("a" * 40, "b" * 40, "c" * 40)):
            target = self.root / sha
            shutil.copytree(original, target)
            # A distinct valid source binding, including the verification record.
            for name in ("release.json", "verification.json"):
                x = json.loads((target / name).read_text());x["app_sha"] = sha
                if name == "release.json": x["release"] = sha[:12] + "-42-1"
                (target / name).write_text(json.dumps(x))
            self.m.seal(target, sha, "initial", now=self.now)
            os.utime(target / "receipt.json", (number + 1, number + 1))
        (self.root / "unrelated").mkdir()
        with patch.object(self.m, "now_utc", return_value=self.now): self.m.retain_two(self.root, "c" * 40)
        self.assertFalse((self.root / ("a" * 40)).exists())
        self.assertTrue((self.root / ("b" * 40)).exists())
        self.assertTrue((self.root / ("c" * 40)).exists())
        self.assertTrue((self.root / "unrelated").exists())

    def test_refresh_preserves_bundle_and_verification(self):
        p = self.package()
        before = {name: (p / name).read_bytes() for name in ("bundle.tar", "verification.json")}
        fresh = self.root / "new-audits"
        fresh.mkdir()
        for name in ("audit-full.json", "audit-prod.json", "audit.json"):
            (fresh / name).write_bytes((p / "audits/initial" / name).read_bytes())
        x = json.loads((fresh / "audit.json").read_text())
        x["audited_at"] = (self.now + timedelta(hours=25)).isoformat()
        (fresh / "audit.json").write_text(json.dumps(x))
        self.m.refresh(p, fresh, self.sha, now=self.now + timedelta(hours=25))
        self.m.validate(p, self.sha, now=self.now + timedelta(hours=26))
        for name, data in before.items(): self.assertEqual((p / name).read_bytes(), data)

    def test_publish_missing_package_never_builds_or_uploads(self):
        bridge = load("local-bridge")
        dep = {"sha": self.sha, "id": 1, "payload": {"run_id": 42, "attempt": 1}}
        with patch.object(bridge, "prepare_sources", side_effect=AssertionError("must not fetch")), \
                patch.object(bridge, "run", side_effect=AssertionError("must not build or upload")):
            with self.assertRaises(bridge.StepFailure) as error:
                bridge.build_and_transfer(object(), dep, "publish", {"state_dir": str(self.root)})
        self.assertEqual(error.exception.step, "prepared_package")


if __name__ == "__main__": unittest.main()
