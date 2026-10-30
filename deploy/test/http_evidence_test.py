"""Evidence validation and the real relay preparation failure boundary."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import http_evidence as evidence
import local_bridge_test as bridge_tests


def report(passed=False):
    return {'schema': 1, 'app_sha': 'a' * 40, 'image_id': 'sha256:' + 'b' * 64,
            'checker_sha256': 'c' * 64, 'fixture_sha256': 'd' * 64,
            'simulated_providers': True, 'cloud_calls': 0, 'passed': passed,
            'cases': ([{'case': c, 'step': 'complete', 'passed': True, 'http': 200,
                        'elapsedMs': 1, 'searches': 0, 'models': 1, 'network': 'none',
                        'resources': {'available': False}} for c in evidence.CASES] if passed else
                      [{'case': 'repair', 'step': 'ordinary_login', 'passed': False, 'http': 500,
                        'failure': {'kind': 'assertion', 'exit_code': 1}, 'resources': {'available': False}}])}


class Evidence(unittest.TestCase):
    def test_allowlist_rejects_sensitive_unknown_and_wrong_identity(self):
        for mutate in (lambda d: d.update(password='PRIVATE_SECRET'),
                       lambda d: d['cases'][0].update(step='PRIVATE_PROMPT'),
                       lambda d: d['cases'][0].update(failure={'kind': 'PRIVATE_BODY', 'exit_code': 1}),
                       lambda d: d.update(app_sha='e' * 40),
                       lambda d: d.update(cloud_calls=1)):
            d = report(); mutate(d)
            with self.assertRaises(evidence.EvidenceError): evidence.validate_report(d, 'a' * 40)
        self.assertEqual(evidence.validate_report(report(), 'a' * 40), report())
        with self.assertRaises(evidence.EvidenceError):
            evidence.validate_report(report(), 'a' * 40, 'sha256:' + 'e' * 64)

    def test_partial_success_is_not_a_complete_report(self):
        d = report(); d['passed'] = True
        with self.assertRaises(evidence.EvidenceError): evidence.validate_report(d, 'a' * 40)
        self.assertTrue(evidence.validate_report(report(True), 'a' * 40)['passed'])
        incomplete = report(True); del incomplete['cases'][0]['http']
        with self.assertRaises(evidence.EvidenceError): evidence.validate_report(incomplete, 'a' * 40)

    def test_missing_bad_oversized_and_symlinked_reports_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'report.json'
            with self.assertRaises(evidence.EvidenceError): evidence.read_json(p)
            for data in (b'{broken', b'x' * (evidence.LIMIT + 1)):
                p.write_bytes(data)
                with self.assertRaises(evidence.EvidenceError): evidence.read_json(p)
            p.unlink(); target = Path(folder) / 'target'; target.write_text('{}')
            p.symlink_to(target)
            with self.assertRaises(evidence.EvidenceError): evidence.read_json(p)

    def test_child_output_is_never_transcribed(self):
        error = subprocess.CalledProcessError(1, ['PRIVATE_COMMAND'], output='PRIVATE_MODEL_BODY', stderr='PRIVATE_KEY')
        self.assertNotIn('PRIVATE', json.dumps(evidence.failure(error, 'outline_generate')))
        payload = {'fixture_failure': True, 'step': 'mobile_page', 'kind': 'timeout', 'http': 200, 'elapsedMs': 30}
        error.stdout = json.dumps(payload)
        self.assertEqual(evidence.failure(error, 'readiness')['step'], 'mobile_page')
        payload['prompt'] = 'PRIVATE_PROMPT'; error.stdout = json.dumps(payload)
        self.assertEqual(evidence.failure(error, 'readiness')['step'], 'readiness')

    def test_ci_retains_only_safe_http_reports_on_both_paths(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/release-checks.yml').read_text()
        for suffix in ('state/*-outline-entry.json', 'http-fault/state/*-outline-entry.json'):
            self.assertIn('/release-check/' + suffix, workflow)
        self.assertIn('if: always()', workflow)
        self.assertNotIn('*-failure.log', workflow)

    def test_child_report_write_failure_does_not_delete_its_only_fixture(self):
        import importlib.util
        import sys
        file = Path(__file__).with_name('outline-entry-checks.py')
        spec = importlib.util.spec_from_file_location('http_child_write_fault', file)
        child = importlib.util.module_from_spec(spec); spec.loader.exec_module(child)
        def execute(*args, **kwargs):
            if args[:3] == ('docker', 'image', 'inspect'):
                return json.dumps([{'Id': 'sha256:' + 'b' * 64, 'Config': {'Labels': {
                    'org.opencontainers.image.revision': 'a' * 40}}}])
            if args[:2] == ('docker', 'exec'):
                raise subprocess.CalledProcessError(1, ['fixture'])
            return ''
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(sys, 'argv', ['fixture', '--image', 'fixture', '--output', folder + '/report.json']), \
                patch.object(child, 'run', side_effect=execute), \
                patch.object(child, 'resources', return_value={'available': False}), \
                patch.object(child, 'atomic_json', side_effect=OSError('PRIVATE_DISK_ERROR')), \
                patch.object(child.subprocess, 'run') as cleanup:
            with self.assertRaises((OSError, SystemExit)): child.main()
            self.assertFalse(cleanup.called, 'Only isolated fixture was deleted after evidence write failure')

    def test_persistence_save_failure_reports_retained_fixture_without_raw_error(self):
        import contextlib
        import io
        child = bridge_tests.load('model-persistence-checks')
        stderr = io.StringIO()
        payload = {'recreated_config_preserved': True, 'read_only_write_rejected': True,
                   'source': 'saved', 'key_returned': False}
        def execute(args, **kwargs):
            value = ''
            if args[:2] == ['docker', 'exec']: value = json.dumps(payload)
            if args[:2] == ['docker', 'inspect']:
                value = json.dumps([{'Mounts': [{'Destination': '/var/lib/yuling-ppt/model-settings', 'RW': False}],
                                     'State': {'OOMKilled': False}}])
            return subprocess.CompletedProcess(args, 0, stdout=value)
        with patch.object(child.subprocess, 'run', side_effect=execute) as calls, \
                patch.object(child, 'resources', return_value={'available': False}), \
                contextlib.redirect_stderr(stderr):
            with self.assertRaises(evidence.FixtureFailure):
                child.check('fixture', Path('/fixture.mjs'), 'fixture-volume',
                            record=lambda _: (_ for _ in ()).throw(OSError('PRIVATE_DISK_ERROR')))
        saved = json.loads(stderr.getvalue())
        self.assertEqual(saved['event'], 'diagnostic_save_failed')
        self.assertTrue(saved['retained_container'].startswith('yuling-settings-recreate-'))
        self.assertNotIn('PRIVATE', stderr.getvalue())
        self.assertFalse(any(c.args[0][:2] == ['docker', 'rm'] for c in calls.call_args_list))


class Retention(unittest.TestCase):
    setUp = bridge_tests.ContractTests.setUp
    source = bridge_tests.ContractTests.source
    execute = bridge_tests.ContractTests.execute
    audits = bridge_tests.ContractTests.audits
    request = bridge_tests.ContractTests.request

    def failed(self, *args, **kwargs):
        if not str(args[1]).endswith('verify-image.py'):
            return self.execute(*args, **kwargs)
        output = Path(args[args.index('--build-output') + 1]); self.output = output
        (output / 'image-check-error.json').write_text(json.dumps({'schema': 1, 'stage': 'outline_http_entry',
            'code': 'image_check_failed', 'exit_code': 1}))
        (output / 'outline-entry.json').write_text(json.dumps(report()))
        raise subprocess.CalledProcessError(6, ['PRIVATE_COMMAND'], stderr='PRIVATE_KEY')

    def test_detailed_http_failure_reaches_state_and_cleans_only_after_save(self):
        with patch.object(self.bridge, 'prepare_sources', side_effect=self.source), patch.object(self.bridge, 'run', side_effect=self.failed):
            with self.assertRaises(self.bridge.StepFailure): self.request('prepare')
        d = json.loads((self.state / '1-outline-entry.json').read_text())
        self.assertEqual(d['cases'][0]['step'], 'ordinary_login')
        self.assertEqual(d['cases'][0]['http'], 500)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.state / 'prepared-releases' / self.sha).exists())
        self.assertEqual(self.ssh, [])

    def test_save_failure_retains_isolated_source_and_never_seals_or_uploads(self):
        with patch.object(self.bridge, 'prepare_sources', side_effect=self.source), patch.object(self.bridge, 'run', side_effect=self.failed), \
                patch.object(self.bridge.http_evidence, 'atomic_json', side_effect=OSError('PRIVATE_ERROR')):
            with self.assertRaises(self.bridge.StepFailure): self.request('prepare')
        self.assertTrue(self.output.is_dir())
        self.assertTrue((self.output / 'outline-entry.json').is_file())
        self.assertFalse((self.state / 'prepared-releases' / self.sha).exists())
        self.assertEqual(self.ssh, [])
        import shutil
        shutil.rmtree(self.output.parent)  # Test-owned retained fixture, after assertions.

    def test_missing_or_invalid_success_report_never_accepts_package(self):
        import shutil
        for content in (None, '{broken', 'x' * (evidence.LIMIT + 1),
                        json.dumps({**report(True), 'api_key': 'PRIVATE_KEY'})):
            with self.subTest(content_type=type(content).__name__):
                self.setUp()
                def invalid(*args, **kwargs):
                    value = self.execute(*args, **kwargs)
                    if str(args[1]).endswith('verify-image.py'):
                        self.output = Path(args[-1])
                        file = self.output / 'outline-entry.json'
                        if content is None: file.unlink()
                        else: file.write_text(content)
                    return value
                with patch.object(self.bridge, 'prepare_sources', side_effect=self.source), \
                        patch.object(self.bridge, 'run', side_effect=invalid):
                    with self.assertRaises(self.bridge.StepFailure): self.request('prepare')
                self.assertTrue(self.output.exists())
                self.assertEqual(self.ssh, [])
                self.assertFalse((self.state / 'prepared-releases' / self.sha).exists())
                shutil.rmtree(self.output.parent)


if __name__ == '__main__': unittest.main()
