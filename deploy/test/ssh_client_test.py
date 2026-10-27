"""Client failure propagation and accidental public-port protection."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location("client", Path(__file__).with_name("ssh-client.py"))
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ClientBoundary(unittest.TestCase):
    def test_receiver_failure_is_not_reported_as_success(self):
        result = subprocess.CompletedProcess([], 1, b"", b'{"status":"failed","error":"prior state restored"}')
        with patch.object(client.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "restored"):
                client.request(["ssh"], {"op": "rollback"})

    def test_ssh_failure_does_not_echo_banner_or_secret(self):
        result = subprocess.CompletedProcess([], 255, b"", b"untrusted banner")
        with patch.object(client.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "SSH/receiver") as raised:
                client.request(["ssh"], {"op": "status"})
            self.assertNotIn("untrusted", str(raised.exception))

    def test_request_stream_contains_exact_header_and_binary(self):
        def fake_run(command, **kwargs):
            self.assertEqual(kwargs["stdin"].read(), b'{"op": "status"}\n')
            return subprocess.CompletedProcess([], 0, b'{"current":null}', b"")
        with patch.object(client.subprocess, "run", side_effect=fake_run), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(client.request(["ssh"], {"op": "status"}), {"current": None})

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


if __name__ == "__main__":
    unittest.main()
