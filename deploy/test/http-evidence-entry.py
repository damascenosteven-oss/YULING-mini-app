"""Real HTTP child -> image checker -> relay -> CI artifact failure evidence.

Uses an already built image and a deliberately broken COPY of the disconnected
fixture. GitHub/source/build are fixtures; Docker HTTP, verification and relay
failure handling are real. No server credentials, upload or activation.
"""
import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from http_evidence import read_json, validate_report

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image-info', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise RuntimeError('Use a new external evidence directory')
    root.mkdir(parents=True)
    state = root / 'state'
    state.mkdir()
    info = read_json(args.image_info)
    sha = info['app_sha']
    spec = importlib.util.spec_from_file_location('http_fault_bridge', HERE / 'local-bridge.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    deployment = {'id': 1, 'sha': sha, 'ref': sha, 'environment': bridge.PREPARE_ENVIRONMENT,
        'creator': {'login': 'github-actions[bot]'}, 'payload': {'schema': 2, 'operation': 'prepare',
        'run_id': 1, 'attempt': 1, 'actor': bridge.OWNER,
        'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}}

    class API:
        states = ['pending']

        def call(self, route, data=None):
            if data is not None:
                self.states.append(data['state'])
                return {}
            if route == '/branches/main':
                return {'protected': True, 'commit': {'sha': sha}}
            if '/check-runs' in route:
                return {'check_runs': [{'name': n, 'head_sha': sha, 'id': i, 'conclusion': 'success'}
                                      for i, n in enumerate(bridge.CHECKS)]}
            if route.startswith('/actions/runs/'):
                return {'id': 1, 'run_attempt': 1, 'event': 'workflow_dispatch', 'head_branch': 'main',
                        'head_sha': sha, 'status': 'in_progress', 'path': '.github/workflows/test-site.yml',
                        'actor': {'login': bridge.OWNER}}
            if '/statuses' in route:
                return [{'state': self.states[-1]}] if self.states else []
            raise AssertionError('Unexpected fixture API route')

    observed = {}

    def source(_state, _sha, checkout):
        target = checkout / 'deploy/test'
        target.mkdir(parents=True)
        runtime = checkout / 'src/lib/ppt/mobile-playback-lifecycle.ts'
        runtime.parent.mkdir(parents=True)
        shutil.copyfile(HERE.parents[1] / 'src/lib/ppt/mobile-playback-lifecycle.ts', runtime)
        for file in HERE.glob('*'):
            if file.is_file():
                shutil.copyfile(file, target / file.name)
        fixture = target / 'outline-entry-fixture.mjs'
        text = fixture.read_text()
        marker = 'return originalFetch(input, init);'
        if text.count(marker) != 1:
            raise AssertionError('Deliberate fault no longer matches fixture')
        fixture.write_text(text.replace(marker,
            "if(url.endsWith('/api/ppt/session'))return new Response('{}',{status:500});\n " + marker))
        observed['checkout'] = checkout
        return Path('/unused-fixture-engine')

    def execute(*values, **kwargs):
        if str(values[1]).endswith('build-image.py'):
            output = Path(values[values.index('--output') + 1])
            output.mkdir()
            shutil.copyfile(args.image_info, output / 'image.json')
            observed['output'] = output
            return
        if not str(values[1]).endswith('verify-image.py'):
            raise AssertionError('Failure attempted upload or another unexpected operation')
        return subprocess.run([str(v) for v in values], check=True, capture_output=True, text=True, **kwargs)

    api = API()
    with patch.object(bridge, 'prepare_sources', side_effect=source), \
            patch.object(bridge, 'run', side_effect=execute), \
            patch.object(bridge, 'secret', side_effect=AssertionError('Failure read server credentials')):
        try:
            bridge.handle(api, deployment, {'state_dir': str(state)}, state)
        except bridge.StepFailure as error:
            if error.code != 'image_check_failed':
                raise
        else:
            raise AssertionError('Deliberately broken HTTP route was accepted')
    report = validate_report(read_json(state / '1-outline-entry.json'), sha)
    case = report['cases'][0]
    stage = read_json(state / '1-image-check-error.json')
    if (report['passed'] or case['step'] != 'ordinary_login' or case['http'] != 500
            or case['failure']['exit_code'] != 1 or stage['stage'] != 'outline_http_entry'
            or stage['exit_code'] != 1 or api.states[-1] != 'failure'
            or observed['checkout'].exists() or (state / 'prepared-releases' / sha).exists()):
        raise AssertionError('Failure evidence or cleanup/acceptance boundary lost')
    (root / 'result.json').write_text(json.dumps({'passed': True, 'app_sha': sha,
        'real_http_child_and_image_checker': True, 'real_relay_failure': True,
        'github_source_build_fixtures': True, 'server_calls': 0, 'cloud_calls': 0,
        'deliberate_http_500_rejected': True, 'diagnostics_retained_before_cleanup': True}))
    print('PASS: deliberate HTTP 500 -> real child/checker/relay -> bounded CI evidence; no server')


if __name__ == '__main__':
    main()
