"""Administrator upgrade uses the receiver's lock and restores exact old bytes."""
import contextlib
import os
if os.name == "posix":
    import fcntl
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from bootstrap_test import bootstrap


@unittest.skipUnless(os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0, "Linux root fixture required")
class Upgrade(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.conf, self.helper = self.base / "root", self.base / "conf", self.base / "installed.py"
        self.root.mkdir(mode=0o700)
        self.conf.mkdir(mode=0o700)
        self.old = b"# known old receiver\n"
        self.helper.write_bytes(self.old)
        self.helper.chmod(0o755)
        self.candidate = b'print(\'{"receiver_version":2,"capabilities":["upload-progress-v1","phased-upload-deadlines-v1"]}\')\n'
        (self.base / "release.py").write_bytes(self.candidate)
        for name, value in (("ROOT", self.root), ("CONF", self.conf), ("HELPER", self.helper),
                            ("__file__", str(self.base / "bootstrap.py"))):
            setting = patch.object(bootstrap, name, value)
            setting.start()
            self.addCleanup(setting.stop)

    def upgrade(self):
        return bootstrap.upgrade_receiver(bootstrap.digest(self.old))

    def test_unknown_old_hash_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "hash"):
            bootstrap.upgrade_receiver("0" * 64)
        self.assertEqual(self.helper.read_bytes(), self.old)

    def test_shared_operation_lock_blocks_upgrade(self):
        with (self.root / "receiver.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "operation"):
                self.upgrade()
        self.assertEqual(self.helper.read_bytes(), self.old)

    def test_success_and_repeat_keep_backup_and_permissions(self):
        self.upgrade()
        backup = self.conf / ("receiver-" + bootstrap.digest(self.old) + ".before")
        self.assertEqual(backup.read_bytes(), self.old)
        self.assertEqual(self.helper.read_bytes(), self.candidate)
        self.assertEqual(self.helper.stat().st_uid, 0)
        self.assertEqual(stat.S_IMODE(self.helper.stat().st_mode), 0o755)
        self.upgrade()
        self.assertEqual(backup.read_bytes(), self.old)

    def test_bad_candidate_keeps_old_program(self):
        (self.base / "release.py").write_bytes(b"not valid python ???")
        with self.assertRaises((RuntimeError, SyntaxError)):
            self.upgrade()
        self.assertEqual(self.helper.read_bytes(), self.old)

    def test_replace_failure_keeps_old_program(self):
        with patch.object(bootstrap.os, "replace", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.upgrade()
        self.assertEqual(self.helper.read_bytes(), self.old)

    def test_installed_verification_failure_restores_old_bytes(self):
        real = bootstrap.verify_receiver
        def verify(path):
            if path == self.helper:
                raise RuntimeError("fixture installed verification failure")
            return real(path)
        with patch.object(bootstrap, "verify_receiver", side_effect=verify):
            with self.assertRaisesRegex(RuntimeError, "restored"):
                self.upgrade()
        self.assertEqual(self.helper.read_bytes(), self.old)


if __name__ == "__main__":
    unittest.main()
