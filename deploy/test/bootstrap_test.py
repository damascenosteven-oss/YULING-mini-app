import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("bootstrap", Path(__file__).with_name("bootstrap.py"))
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class DeploymentAccount(unittest.TestCase):
    def test_existing_account_cannot_have_root_or_shared_privileges(self):
        account = SimpleNamespace(pw_uid=998, pw_dir=str(bootstrap.HOME), pw_shell="/bin/sh")
        bootstrap.check_account(account, bootstrap.USER, [])
        for bad, group, extras in ((SimpleNamespace(pw_uid=0, pw_dir=str(bootstrap.HOME), pw_shell="/bin/sh"), bootstrap.USER, []),
                                  (account, "docker", []), (account, bootstrap.USER, ["sudo"])):
            with self.assertRaises(RuntimeError):
                bootstrap.check_account(bad, group, extras)


class CaddyUpdate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Caddyfile"
        self.before = b"existing.example { respond original }\n"
        self.after = self.before + b"test.example { reverse_proxy 172.18.0.1:5000 }\n"
        self.path.write_bytes(self.before)
        self.inode = self.path.stat().st_ino

    def test_success_preserves_file_identity_and_existing_bytes(self):
        observed = []
        bootstrap.replace_in_place(self.path, self.before, self.after, observed.append)
        self.assertEqual(self.path.stat().st_ino, self.inode)
        self.assertEqual(self.path.read_bytes(), self.after)
        self.assertEqual(observed, [self.after])

    def test_reload_failure_restores_original_and_reports_error(self):
        calls = []
        def reload(data):
            calls.append(data)
            if data == self.after:
                raise RuntimeError("reload failed")
        with self.assertRaisesRegex(RuntimeError, "restored"):
            bootstrap.replace_in_place(self.path, self.before, self.after, reload)
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(self.path.stat().st_ino, self.inode)
        self.assertEqual(calls, [self.after, self.before])

    def test_concurrent_owner_edit_is_not_overwritten(self):
        self.path.write_bytes(b"owner edit")
        with self.assertRaises(RuntimeError):
            bootstrap.replace_in_place(self.path, self.before, self.after, lambda _: None)
        self.assertEqual(self.path.read_bytes(), b"owner edit")

    def test_concurrent_edit_during_reload_is_preserved(self):
        def reload(_):
            self.path.write_bytes(b"new owner edit")
            raise RuntimeError("reload failed")
        with self.assertRaisesRegex(RuntimeError, "concurrent"):
            bootstrap.replace_in_place(self.path, self.before, self.after, reload)
        self.assertEqual(self.path.read_bytes(), b"new owner edit")


if __name__ == "__main__":
    unittest.main()
