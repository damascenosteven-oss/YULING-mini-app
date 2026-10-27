"""Bounded diagnostic requests never enter the release transaction."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_test import release


class ProbeBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.controller = release.Controller(self.root, {})
        self.data = b'x' * (4 * 1024**2)
        self.header = {'op': 'probe_receive', 'probe': '123-1-1', 'bytes': len(self.data),
                       'sha256': hashlib.sha256(self.data).hexdigest()}

    def request(self, header=None, data=None):
        with contextlib.redirect_stderr(io.StringIO()):
            return release.dispatch(self.controller, io.BytesIO(
                json.dumps(header or self.header).encode() + b'\n' +
                (self.data if data is None else data)))

    def test_exact_data_is_verified_without_release_state(self):
        with patch.object(release.DockerRuntime, 'call', side_effect=AssertionError('Docker used')):
            result = self.request()
        self.assertEqual(result['sha256'], self.header['sha256'])
        self.assertEqual(result['bytes'], len(self.data))
        self.assertEqual(result['status'], 'measured')
        self.assertTrue(result['cleaned'])
        self.assertFalse((self.root / 'state.json').exists())
        self.assertEqual(list(self.controller.incoming.iterdir()), [])
        self.assertEqual(list(self.controller.releases.iterdir()), [])

    def test_truncation_extra_data_and_checksum_are_fatal_and_cleaned(self):
        for data in (self.data[:-1], self.data + b'x', b'y' * len(self.data)):
            with self.subTest(length=len(data)), self.assertRaises(release.ReleaseError):
                self.request(data=data)
            self.assertEqual(list(self.controller.incoming.iterdir()), [])

    def test_bounds_cannot_be_changed_by_request(self):
        for changes in ({'bytes': 1}, {'bytes': True}, {'seconds': 999},
                        {'probe': '../escape'}, {'probe': '123-1-4'}, {'sha256': 'bad'}):
            with self.subTest(changes=changes), self.assertRaises(release.ReleaseError):
                self.request({**self.header, **changes})

    def test_pending_release_blocks_probe(self):
        self.controller.save_state({'current': None, 'previous': None, 'pending': 'a'*12+'-1-1'})
        with self.assertRaises(release.ReleaseError):
            self.request()

    def test_url_bound_to_exact_host_and_run_object(self):
        valid = 'https://yuling-ppt-test-1494859304.cos.ap-shanghai.myqcloud.com/transfer-probe/123-1-1.bin?q-signature=abc'
        self.assertEqual(release.probe_path(valid, '123-1-1'), valid.split('.com', 1)[1])
        for bad in (valid.replace('https:', 'http:'), valid.replace('.com/', '.com:443/'),
                    valid.replace('.com/', '.com.evil/'), valid.replace('123-1-1.bin', '../app.env'),
                    valid.replace('123-1-1.bin', '124-1-1.bin'), valid+'#secret',
                    valid.replace('https://', 'https://user@'), valid.replace('transfer-probe/', '%74ransfer-probe/')):
            with self.subTest(url=bad), self.assertRaises(release.ReleaseError):
                release.probe_path(bad, '123-1-1')

    def test_fixed_deadlines_are_independent_of_upload_budget(self):
        now = [0.0]
        p = release.ProbeProgress(clock=lambda: now[0])
        now[0] = 60
        with self.assertRaises(release.ProbeFailure) as error:
            p.check()
        self.assertEqual(error.exception.detail['code'], 'probe_idle')
        p.last_data = 299
        now[0] = 300
        with self.assertRaises(release.ProbeFailure) as error:
            p.check()
        self.assertEqual(error.exception.detail['code'], 'probe_timeout')

    def test_download_uses_tls_exact_object_and_checks_content(self):
        from unittest.mock import Mock
        response = io.BytesIO(self.data)
        response.status = 200
        response.getheader = lambda name: str(len(self.data)) if name == 'Content-Length' else None
        connection = Mock()
        connection.getresponse.return_value = response
        connection.sock.getpeername.return_value = ('169.254.1.2', 443)
        header = {**self.header, 'op': 'probe_download', 'url': 'https://' + release.PROBE_HOST + '/transfer-probe/123-1-1.bin?signature=SECRET'}
        with patch.object(release.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('169.254.1.2', 443))]), \
                patch.object(release.http.client, 'HTTPSConnection', return_value=connection):
            result = self.request(header, b'')
        self.assertEqual(result['peer'], '169.254.1.2')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(connection.request.call_count, 1)

    def test_redirect_and_auth_fail_without_following_or_leaking_url(self):
        from unittest.mock import Mock
        for status in (301, 302, 307, 401, 403, 404):
            connection = Mock()
            connection.sock.getpeername.return_value = ('169.254.1.2', 443)
            connection.getresponse.return_value.status = status
            header = {**self.header, 'op': 'probe_download', 'url': 'https://' + release.PROBE_HOST + '/transfer-probe/123-1-1.bin?signature=SECRET'}
            with patch.object(release.socket, 'getaddrinfo', return_value=[]), \
                    patch.object(release.http.client, 'HTTPSConnection', return_value=connection), \
                    self.assertRaises(release.ProbeFailure) as error:
                self.request(header, b'')
            self.assertNotIn('SECRET', str(error.exception))
            self.assertEqual(error.exception.detail['code'], 'probe_auth' if status in (401, 403) else 'probe_http')
            self.assertEqual(connection.request.call_count, 1)
            self.assertEqual(list(self.controller.incoming.iterdir()), [])

    def test_cleanup_failure_is_fatal(self):
        with patch.object(release.shutil, 'rmtree', side_effect=OSError('SECRET')):
            with self.assertRaisesRegex(release.ProbeFailure, 'probe_cleanup'):
                self.request()

    @unittest.skipUnless(hasattr(release.signal, 'setitimer'), 'Linux timer boundary')
    def test_download_body_eof_is_inside_deadline(self):
        class StalledBody:
            def read(self, _):
                self_test.assertGreater(release.signal.getitimer(release.signal.ITIMER_REAL)[0], 0)
                raise release.ProbeFailure('probe_idle')
        self_test = self
        header = {**self.header, 'op': 'probe_download', 'url': 'https://' + release.PROBE_HOST + '/transfer-probe/123-1-1.bin?signature=fixture'}
        with self.assertRaisesRegex(release.ProbeFailure, 'probe_idle'):
            release.probe_request(self.controller, header, StalledBody())
        self.assertEqual(list(self.controller.incoming.iterdir()), [])

    def test_termination_is_handled_and_signal_handler_restored(self):
        import subprocess
        import sys
        code = '''import signal,release
old=signal.getsignal(signal.SIGTERM)
try:
 with release.ProbeProgress():signal.raise_signal(signal.SIGTERM)
except release.ProbeFailure as e:
 assert e.detail['code']=='probe_cancelled'
else:raise AssertionError('termination swallowed')
assert signal.getsignal(signal.SIGTERM)==old
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).parent, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))


if __name__ == '__main__':
    unittest.main()
