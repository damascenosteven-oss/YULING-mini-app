"""Bounded, allowlisted metadata for disconnected HTTP image checks; never raw output."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

CASES = ('repair', 'invalid', 'timeout', 'upstream', 'json', 'truncated', 'ordinary', 'no-search-key', 'admin',
         'highlight-repair', 'skill-repair', 'skill-invalid', 'json-repair')
STEPS = {'container_start', 'readiness', 'http_client', 'ordinary_login', 'admin_login', 'model_read', 'model_test',
         'model_save', 'outline_generate', 'motion_refresh', 'python_build', 'preview', 'mobile_page', 'persistence',
         'resource_check', 'contract_check', 'complete'}
KINDS = {'assertion', 'timeout', 'process_exit', 'runtime_error', 'resource', 'diagnostic_error'}
STAGES = {'container_start', 'runtime_permissions', 'readiness', 'quick_smoke', 'outline_http_entry',
          'repeatability', 'memory_and_evidence'}
LIMIT = 65536


class EvidenceError(ValueError):
    def __init__(self):
        super().__init__('http_evidence_invalid_or_unavailable')


class FixtureFailure(RuntimeError):
    def __init__(self, detail):
        super().__init__('isolated_http_fixture_failed')
        self.detail = detail


def require(value):
    if not value:
        raise EvidenceError()


def integer(value, maximum=600000):
    require(type(value) is int and 0 <= value <= maximum)


def read_json(file):
    require(file.is_file() and not file.is_symlink() and file.stat().st_size <= LIMIT)
    try:
        return json.loads(file.read_bytes())
    except (ValueError, UnicodeError):
        raise EvidenceError() from None


def atomic_json(file, value):
    data = json.dumps(value, ensure_ascii=True).encode()
    require(len(data) <= LIMIT and not file.is_symlink())
    temporary = file.with_name(file.name + '.' + uuid.uuid4().hex + '.writing')
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, file)
    finally:
        temporary.unlink(missing_ok=True)


def resources(name):
    import subprocess
    result = {'available': False}
    try:
        p = subprocess.run(['docker', 'inspect', name], check=True, capture_output=True, timeout=15)
        state = json.loads(p.stdout)[0]['State']
        result = {'available': True, 'oom': bool(state['OOMKilled']), 'exit_code': int(state['ExitCode'])}
        p = subprocess.run(['docker', 'exec', name, 'sh', '-c',
                            'cat /sys/fs/cgroup/memory.peak /sys/fs/cgroup/memory.events'],
                           check=True, capture_output=True, text=True, timeout=15)
        lines = p.stdout.splitlines()
        result['memory_peak'] = int(lines[0])
        for line in lines[1:]:
            key, value = line.split()
            if key in {'oom', 'oom_kill', 'max'}:
                result['memory_' + key] = int(value)
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        pass  # Only observed counters are reported; missing data is not a zero.
    return result


def failure(error, step):
    import subprocess
    if isinstance(error, FixtureFailure):
        return error.detail
    detail = {'step': step, 'failure': {'kind': 'runtime_error', 'exit_code': None}}
    if isinstance(error, subprocess.TimeoutExpired):
        detail['failure']['kind'] = 'timeout'
    elif isinstance(error, subprocess.CalledProcessError):
        detail['failure'] = {'kind': 'process_exit', 'exit_code': error.returncode}
        try:
            require(isinstance(error.stdout, str) and len(error.stdout.encode()) <= LIMIT)
            data = json.loads(error.stdout)
            require(set(data) == {'fixture_failure', 'step', 'kind', 'http', 'elapsedMs'})
            require(data['fixture_failure'] is True and data['step'] in STEPS and data['kind'] in KINDS)
            integer(data['elapsedMs'])
            require(data['http'] is None or type(data['http']) is int and 100 <= data['http'] <= 599)
            detail.update(step=data['step'], elapsedMs=data['elapsedMs'])
            if data['http'] is not None:
                detail['http'] = data['http']
            detail['failure']['kind'] = data['kind']
        except (ValueError, TypeError, AttributeError):
            pass
    elif isinstance(error, AssertionError):
        detail['failure']['kind'] = 'assertion'
    return detail


def validate_report(data, app_sha, image_id=None):
    require(isinstance(data, dict) and set(data) == {'schema', 'app_sha', 'image_id', 'checker_sha256',
            'fixture_sha256', 'simulated_providers', 'cloud_calls', 'cases', 'passed'})
    require(type(data['schema']) is int and data['schema'] == 1
            and data['app_sha'] == app_sha and re.fullmatch('[0-9a-f]{40}', app_sha))
    require(isinstance(data['image_id'], str) and re.fullmatch('sha256:[0-9a-f]{64}', data['image_id']))
    require(image_id is None or data['image_id'] == image_id)
    for key in ('checker_sha256', 'fixture_sha256'):
        require(isinstance(data[key], str) and re.fullmatch('[0-9a-f]{64}', data[key]))
    require(data['simulated_providers'] is True and type(data['cloud_calls']) is int and data['cloud_calls'] == 0)
    require(type(data['passed']) is bool and isinstance(data['cases'], list) and len(data['cases']) <= len(CASES))
    booleans = {'passed', 'adminVerified', 'built', 'mobile_ui_checked'}
    numbers = {'http': 599, 'pages': 12, 'sources': 100, 'elapsedMs': 600000, 'searches': 0, 'models': 2}
    for index, case in enumerate(data['cases']):
        require(isinstance(case, dict) and {'case', 'step', 'passed'} <= set(case))
        require(set(case) <= {'case', 'step', 'code', 'research', 'network', 'failure', 'resources', 'recreate_resources', 'persistence'} | booleans | set(numbers))
        require(case['case'] == CASES[index] and case['step'] in STEPS)
        for key in booleans & set(case): require(type(case[key]) is bool)
        for key in set(numbers) & set(case): integer(case[key], numbers[key])
        if 'http' in case: require(case['http'] >= 100)
        if case['passed']:
            require({'http', 'elapsedMs', 'searches', 'models', 'network', 'resources'} <= set(case)
                    and case['step'] == 'complete' and 'failure' not in case)
        if 'code' in case: require(case['code'] in (None, 'PPT_OUTLINE_INVALID', 'PPT_MODEL_TIMEOUT', 'PPT_SKILL_UNSUPPORTED'))
        if 'research' in case: require(case['research'] == 'not-required')
        if 'network' in case: require(case['network'] == 'none')
        if 'failure' in case:
            f = case['failure']
            require(isinstance(f, dict) and set(f) == {'kind', 'exit_code'} and f['kind'] in KINDS)
            require(f['exit_code'] is None or type(f['exit_code']) is int and -255 <= f['exit_code'] <= 255)
        for resource_key in ('resources', 'recreate_resources'):
            if resource_key not in case: continue
            r = case[resource_key]
            require(isinstance(r, dict) and set(r) <= {'available', 'oom', 'exit_code', 'memory_peak', 'memory_oom', 'memory_oom_kill', 'memory_max'})
            for key, value in r.items():
                if key in {'available', 'oom'}: require(type(value) is bool)
                else: integer(value, 2**63 - 1)
        if 'persistence' in case:
            p = case['persistence']
            require(set(p) == {'recreated_config_preserved', 'read_only_write_rejected', 'source', 'key_returned'})
            require(p['source'] == 'saved' and all(type(p[k]) is bool for k in set(p) - {'source'}))
    if data['passed']:
        require(len(data['cases']) == len(CASES) and all(c['passed'] and c['step'] == 'complete' for c in data['cases']))
    return data


def checker_digest(folder):
    return hashlib.sha256(b''.join((folder / n).read_bytes() for n in (
        'http_evidence.py', 'outline-entry-checks.py', 'outline-entry-fixture.mjs', 'model-persistence-checks.py',
        'mobile-playback-check.mjs'))).hexdigest()


def retain(output, state, identity, app_sha):
    require(re.fullmatch('[0-9]{1,20}', str(identity)))
    diagnostic = output / 'image-check-error.json'
    stage = None
    if diagnostic.exists():
        data = read_json(diagnostic)
        require(set(data) == {'schema', 'stage', 'code', 'exit_code'} and data['schema'] == 1)
        require(data['stage'] in STAGES and data['code'] in {'image_permission_denied', 'image_check_failed'})
        require(type(data['exit_code']) is int and -255 <= data['exit_code'] <= 255)
        stage = data['stage']
        atomic_json(state / (str(identity) + '-image-check-error.json'), data)
    source = output / 'outline-entry.json'
    if source.exists():
        data = validate_report(read_json(source), app_sha)
        atomic_json(state / (str(identity) + '-outline-entry.json'), data)
    elif stage == 'outline_http_entry':
        raise EvidenceError()
