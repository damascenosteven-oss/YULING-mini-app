"""Issue 12: budgets, cleanup and actual client subprocess boundary."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from release_test import release, bundle

spec = importlib.util.spec_from_file_location("transfer_client", Path(__file__).with_name("ssh-client.py"))
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class TransferBudget(unittest.TestCase):
    def progress(self):
        self.now = 0.0
        return release.UploadProgress(100, clock=lambda: self.now)

    def test_continuous_slow_transfer_has_its_own_total_budget(self):
        p = self.progress()
        for t in range(100, 2700, 100):
            self.now = t
            p.check()
            p.received(1)
        self.now = 2700
        with self.assertRaisesRegex(release.ReleaseError, "transfer_timeout"):
            p.check()

    def test_idle_budget_is_not_reset_by_progress_logging(self):
        p = self.progress()
        self.now = 119
        p.check()
        p.emit()
        self.now = 120
        with self.assertRaisesRegex(release.ReleaseError, "transfer_idle"):
            p.check()

    def test_processing_has_one_budget_across_phase_changes(self):
        p = self.progress()
        self.now = 2000
        p.received(100)
        p.phase("archive")
        self.now = 2800
        p.phase("normalize")
        p.check()
        self.now = 2900
        with self.assertRaisesRegex(release.ReleaseError, "processing_timeout"):
            p.check()

    def test_timeout_cleans_staging_without_docker_call(self):
        request, data = bundle()
        class Broken(io.BytesIO):
            def read1(self, _):
                raise release.ReleaseError("transfer_idle")
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            c = release.Controller(Path(tmp), {}, lambda *a: calls.append(a))
            with self.assertRaisesRegex(release.ReleaseError, "transfer_idle"):
                c.upload(request, Broken(data))
            self.assertEqual(list(c.incoming.iterdir()), [])
            self.assertEqual(list(c.releases.iterdir()), [])
            self.assertEqual(calls, [])

    def test_request_cannot_override_production_budget(self):
        request, data = bundle()
        request["timeout"] = 999999
        with tempfile.TemporaryDirectory() as tmp:
            c = release.Controller(Path(tmp), {}, None)
            with self.assertRaisesRegex(release.ReleaseError, "fields"):
                c.upload(request, io.BytesIO(data))


class ClientProcess(unittest.TestCase):
    def test_progress_is_printed_before_remote_process_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "progress-seen"
            class Output(io.StringIO):
                def write(self, value):
                    if "receive" in value:
                        marker.touch()
                    return super().write(value)
            code = '''import sys,json,time,pathlib
sys.stdin.buffer.read()
print(json.dumps({"event":"progress","phase":"receive","received":1,"total":2,"elapsed":1}),file=sys.stderr,flush=True)
p=pathlib.Path(sys.argv[1]); end=time.monotonic()+3
while not p.exists() and time.monotonic()<end: time.sleep(.02)
if not p.exists(): sys.exit(3)
print('{"status":"stored"}',flush=True)
'''
            with contextlib.redirect_stdout(Output()):
                self.assertEqual(client.request([sys.executable, "-u", "-c", code, str(marker)], {"op":"status"})["status"], "stored")

    def test_progress_followed_by_error_preserves_failure(self):
        code = '''import sys,json
sys.stdin.buffer.read()
print(json.dumps({"event":"progress","phase":"receive","received":1,"total":2,"elapsed":120}),file=sys.stderr)
print(json.dumps({"status":"failed","code":"transfer_idle","phase":"receive","received":1,"total":2,"elapsed":120}),file=sys.stderr)
sys.exit(1)
'''
        with self.assertRaisesRegex(RuntimeError, "transfer_idle"):
            client.request([sys.executable, "-c", code], {"op":"status"})

    def test_old_receiver_is_rejected_before_upload(self):
        with self.assertRaisesRegex(RuntimeError, "upgrade"):
            client.require_capabilities({"current": None})

    def test_malformed_capabilities_fail_with_upgrade_guidance(self):
        for capabilities in (None, 42, "upload-progress-v1", ["upload-progress-v1"]):
            with self.assertRaisesRegex(RuntimeError, "upgrade"):
                client.require_capabilities({"receiver_version": 2, "capabilities": capabilities})

    def test_deadline_kills_child_and_reaps_it(self):
        with patch.object(client, "CONTROL_TIMEOUT", .1):
            with self.assertRaisesRegex(RuntimeError, "client_timeout") as raised:
                client.request([sys.executable,"-c","import time; time.sleep(5)"], {"op":"status"})
            self.assertIn("awaiting_receiver", str(raised.exception))
            self.assertIn('"received": null', str(raised.exception))

    def test_unknown_stderr_is_never_echoed(self):
        code = "import sys; sys.stdin.buffer.read(); print('SECRET-example',file=sys.stderr); sys.exit(1)"
        with self.assertRaises(RuntimeError) as result:
            client.request([sys.executable,"-c",code], {"op":"status"})
        self.assertNotIn("SECRET-example", str(result.exception))


class WorkflowBinding(unittest.TestCase):
    def test_download_is_bound_to_successful_build_id(self):
        content = (Path(__file__).resolve().parents[2] / ".github/workflows/test-site.yml").read_text(encoding="utf-8")
        self.assertIn("artifact-ids: ${{ needs.build.outputs.artifact_id }}", content)
        self.assertIn("artifact_id: ${{ steps.release_artifact.outputs.artifact-id }}", content)
        self.assertIn("timeout-minutes: 90", content)
        self.assertIn("Verify build artifact reference", content)


if __name__ == "__main__":
    unittest.main()
