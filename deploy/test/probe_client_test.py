import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('network_probe', Path(__file__).with_name('network-probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeClient(unittest.TestCase):
    def test_failed_samples_are_not_dropped_from_summary(self):
        report = {'samples': []}
        for path, speed in (('ssh', 24000), ('cos_upload', 2e6), ('cos_download', 3e6)):
            for index in range(3):
                report['samples'].append({'path': path, 'status': 'measured', 'sha256_verified': True, 'bytes_per_second': speed})
        probe.summarize(report)
        self.assertTrue(report['recommend_large_test'])
        report['samples'][0]['status'] = 'failed'
        probe.summarize(report)
        self.assertFalse(report['recommend_large_test'])
        self.assertNotIn('ssh', report['speeds_bytes_per_second'])

    def test_unverified_cos_upload_never_qualifies(self):
        report = {'samples': [{'path': 'cos_upload', 'status': 'measured', 'sha256_verified': False,
                              'bytes_per_second': 1e8} for _ in range(3)]}
        probe.summarize(report)
        self.assertEqual(report['speeds_bytes_per_second'], {})

    def test_timeout_recorded_but_auth_and_integrity_stop(self):
        for code in ('probe_timeout', 'probe_idle', 'probe_network', 'probe_auth', 'probe_integrity'):
            report = {'samples': []}
            def fail():
                raise probe.release.ProbeFailure(code)
            if code in probe.NETWORK_CODES:
                probe.measure(report, 'ssh', 1, fail)
            else:
                with self.assertRaises(RuntimeError):
                    probe.measure(report, 'ssh', 1, fail)
            self.assertEqual(report['samples'][0]['code'], code)

    def test_exactly_three_rounds_cleanup_state_and_no_secret_in_reports(self):
        report = {'run': '123-1', 'samples': [], 'outstanding_objects': []}
        state = {'current': None, 'previous': None, 'pending': None}
        def request(command, header, data=b''):
            self.assertIn(header['op'], ('probe_receive', 'probe_download'))
            return {'status': 'measured', 'bytes': 4194304, 'sha256_verified': True, 'client_seconds': 1}
        calls = []
        def cos(method, url, run, data=b''):
            calls.append(method)
            return {'status': 'measured', 'bytes': len(data), 'client_seconds': 1, 'sha256_verified': False}
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'state', return_value=state), \
                patch.object(probe, 'site_health'), patch.object(probe, 'request', side_effect=request), \
                patch.object(probe, 'signed_url', return_value='SECRET-SIGNATURE'), patch.object(probe, 'cos_request', side_effect=cos):
            self.assertEqual(probe.run_probe([], None, report, Path(directory)), 0)
            self.assertEqual(len(report['samples']), 9)
            self.assertEqual(calls, ['PUT', 'DELETE'] * 3)
            self.assertEqual(report['outstanding_objects'], [])
            self.assertNotIn('SECRET-SIGNATURE', (Path(directory)/'result.json').read_text())

    def test_cleanup_failure_and_postcheck_are_visible(self):
        report = {'run': '123-1', 'samples': [], 'outstanding_objects': []}
        def cos(*_):
            raise probe.release.ProbeFailure('probe_auth')
        sample = {'status': 'measured', 'bytes': 4194304, 'sha256_verified': True, 'client_seconds': 1}
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'state', return_value={}), \
                patch.object(probe, 'site_health'), patch.object(probe, 'request', return_value=sample), \
                patch.object(probe, 'signed_url', return_value='SECRET-SIGNATURE'), patch.object(probe, 'cos_request', side_effect=cos):
            self.assertEqual(probe.run_probe([], None, report, Path(directory)), 1)
            self.assertEqual(report['fatal'], 'probe_cleanup')
            self.assertEqual(report['outstanding_objects'], ['transfer-probe/123-1-1.bin'])
            self.assertEqual(report['postcheck'], 'passed')

    def test_actual_client_filters_progress_and_reports_nonzero(self):
        import sys
        command = [sys.executable, '-c', "import sys;sys.stdin.buffer.read();print('SECRET',file=sys.stderr);print('{\"event\":\"progress\",\"phase\":\"probe_receive\",\"received\":1,\"total\":4194304,\"elapsed\":1}',file=sys.stderr);print('{\"status\":\"failed\",\"code\":\"probe_idle\"}',file=sys.stderr);sys.exit(1)"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaisesRegex(RuntimeError, 'probe_idle'):
            probe.request(command, {'op': 'probe_receive'})
        self.assertNotIn('SECRET', output.getvalue())
        self.assertIn('probe_receive', output.getvalue())


if __name__ == '__main__':
    unittest.main()
