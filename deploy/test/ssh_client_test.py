"""Client failure propagation and accidental public-port protection."""
import importlib.util
import io
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location("client", Path(__file__).with_name("ssh-client.py"))
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ClientBoundary(unittest.TestCase):
    def test_receiver_failure_is_not_reported_as_success(self):
        code = "import sys; sys.stdin.buffer.read(); print('{\"status\":\"failed\",\"code\":\"prior_state_restored\"}',file=sys.stderr); sys.exit(1)"
        with self.assertRaisesRegex(RuntimeError, "restored"):
            client.request([sys.executable, "-c", code], {"op": "rollback"})

    def test_ssh_failure_does_not_echo_banner_or_secret(self):
        code = "import sys; sys.stdin.buffer.read(); print('untrusted banner',file=sys.stderr); sys.exit(255)"
        with self.assertRaisesRegex(RuntimeError, "SSH/receiver") as raised:
            client.request([sys.executable, "-c", code], {"op": "status"})
        self.assertNotIn("untrusted", str(raised.exception))

    def test_request_stream_contains_exact_header_and_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "bundle"
            bundle.write_bytes(bytes(range(256)))
            code = "import sys,json; assert sys.stdin.buffer.read()==b'{\"op\": \"upload\"}\\n'+bytes(range(256)); print('{\"status\":\"stored\"}')"
            with patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(client.request([sys.executable, "-c", code], {"op": "upload"}, bundle), {"status": "stored"})

    def test_public_port_reachable_is_rejected(self):
        connection = Mock()
        with patch.object(client.socket, "create_connection", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "publicly reachable"):
                client.external_port_closed("example.invalid")
        connection.close.assert_called_once()

    def test_unknown_connectivity_error_is_not_a_pass(self):
        with patch.object(client.socket, "create_connection", side_effect=OSError("unknown")):
            with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
                client.external_port_closed("example.invalid")

    def test_closed_port_is_accepted(self):
        for error in (ConnectionRefusedError(), TimeoutError()):
            with patch.object(client.socket, "create_connection", side_effect=error):
                client.external_port_closed("example.invalid")

    def test_upload_and_activation_are_separate_restricted_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bundle.tar"
            bundle.write_bytes(b"fixture")
            (root / "release.json").write_text(json.dumps({
                "app_sha": "a" * 40, "release": "a" * 12 + "-42-1"}))
            (root / "bundle.sha256").write_text(hashlib.sha256(b"fixture").hexdigest() + "  bundle.tar\n")
            env = {"GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "a" * 40,
                   "DEPLOY_HOST": "example.invalid", "DEPLOY_SSH_KEY": "fixture",
                   "SSH_KNOWN_HOSTS": "fixture"}
            for stage, expected in (("upload", ["status", "upload"]),
                                    ("activate", ["status", "deploy"])):
                operations = []
                def fake_request(command, header, bundle=None):
                    operations.append(header["op"])
                    return {"receiver_version": 2, "capabilities": [
                        "upload-progress-v1", "phased-upload-deadlines-v1"]}
                with patch.dict(os.environ, env), patch.object(sys, "argv", [
                        "ssh-client.py", "publish", "--bundle", str(bundle), "--stage", stage]), \
                        patch.object(client, "request", side_effect=fake_request), \
                        patch.object(client, "external_port_closed"):
                    client.main()
                self.assertEqual(operations, expected)


if __name__ == "__main__":
    unittest.main()
