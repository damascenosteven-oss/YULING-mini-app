"""Manual diagnostics only: fixed samples, endpoint, budgets and no Docker calls."""
import argparse
import base64
import contextlib
from datetime import datetime, timezone, timedelta
import hashlib
import http.client
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import statistics
import sys
import tempfile
import time

import release

spec = importlib.util.spec_from_file_location('ssh_client', Path(__file__).with_name('ssh-client.py'))
ssh_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ssh_client)
BUCKET = 'yuling-ppt-test-1494859304'
REGION = 'ap-shanghai'
CAPABILITY = 'bounded-probe-v1'
CLIENT_SECONDS = 330
PACKAGE_BYTES = 931635200
NETWORK_CODES = {'probe_timeout', 'probe_idle', 'probe_network'}


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def credentials(directory):
    host = os.environ['DEPLOY_HOST']
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}', host), 'invalid_host')
    for name, variable in (('key', 'DEPLOY_SSH_KEY'), ('known', 'SSH_KNOWN_HOSTS')):
        value = os.environ[variable]
        require(value.strip(), 'missing_ssh_credential')
        file = directory / name
        file.write_text(value.rstrip() + '\n', encoding='utf-8')
        file.chmod(0o600)
    return ['ssh', '-F', '/dev/null', '-T', '-p', '22', '-i', str(directory / 'key'),
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + str(directory / 'known'), '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-o', 'Compression=no', 'yuling-ppt-deploy@' + host]


def request(command, header, data=b''):
    with tempfile.TemporaryFile() as payload:
        payload.write(json.dumps(header).encode() + b'\n' + data)
        payload.seek(0)
        start = time.monotonic()
        result = ssh_client.run_request(command, payload, CLIENT_SECONDS)
        result['client_seconds'] = time.monotonic() - start
        if header['op'].startswith('probe_'):
            require(result.get('status') == 'measured' and result.get('probe') == header['probe']
                    and result.get('bytes') == release.PROBE_SIZE and result.get('sha256') == header['sha256']
                    and result.get('cleaned') is True, 'probe_integrity')
            result['sha256_verified'] = True
            result['ssh_setup_seconds_estimate'] = max(0, result['client_seconds'] - result['elapsed'])
        return result


def site_health():
    connection = http.client.HTTPSConnection('zhuwenjie.online', timeout=20)
    try:
        connection.request('GET', '/', headers={'Connection': 'close'})
        require(connection.getresponse().status == 200, 'original_site_unhealthy')
    except OSError:
        raise RuntimeError('original_site_unreachable') from None
    finally:
        connection.close()


def state(command):
    value = request(command, {'op': 'status'})
    require(value.get('receiver_version') == 2 and CAPABILITY in value.get('capabilities', []),
            'receiver_upgrade_required')
    require(value.get('pending') is None, 'pending_release')
    return {key: value[key] for key in ('current', 'previous', 'pending')}


def signer():
    # Imports are isolated to the diagnostic environment, never the app image.
    from qcloud_cos import CosConfig, CosS3Client
    values = [os.environ[name] for name in ('PROBE_COS_SECRET_ID', 'PROBE_COS_SECRET_KEY')]
    require(all(values), 'missing_probe_credential')
    return CosS3Client(CosConfig(Region=REGION, SecretId=values[0], SecretKey=values[1], Scheme='https'))


def signed_url(client, method, probe):
    # No SDK network calls or SDK automatic retries: signing is local.
    url = client.get_presigned_url(Method=method, Bucket=BUCKET,
                                  Key='transfer-probe/' + probe + '.bin', Expired=600)
    release.probe_path(url, probe)
    return url


class CleanupProgress(release.ProbeProgress):
    def check(self):
        if self.clock() - self.start >= 30:
            raise release.ProbeFailure('probe_cleanup', self)
        super().check()

    def arm(self):
        signal.setitimer(signal.ITIMER_REAL, max(.001, min(5, 30 - (self.clock() - self.start))))


def cos_request(method, url, probe, data=b''):
    path = release.probe_path(url, probe)
    progress = CleanupProgress() if method == 'DELETE' else release.ProbeProgress()
    progress.stage = 'probe_cleanup' if method == 'DELETE' else 'probe_upload'
    connection = http.client.HTTPSConnection(release.PROBE_HOST, timeout=release.PROBE_IDLE)
    try:
        with progress:
            connection.connect()
            connected = time.monotonic() - progress.start
            peer = connection.sock.getpeername()[0]
            headers = {'Connection': 'close', 'Content-Length': str(len(data))}
            if method == 'PUT':
                headers['Content-MD5'] = base64.b64encode(hashlib.md5(data).digest()).decode()
            connection.putrequest(method, path)
            for key, value in headers.items():
                connection.putheader(key, value)
            connection.endheaders()
            for offset in range(0, len(data), 65536):
                chunk = data[offset:offset + 65536]
                connection.send(chunk)
                progress.received(len(chunk))
            response = connection.getresponse()
            if response.status in (401, 403):
                raise release.ProbeFailure('probe_auth', progress)
            require(response.status in ((200,) if method == 'PUT' else (200, 204)), 'probe_http')
            if method == 'PUT':
                require(response.getheader('ETag', '').strip('"') == hashlib.md5(data).hexdigest(), 'probe_integrity')
            progress.check()
            return {'status': 'measured', 'bytes': len(data), 'peer': peer,
                    'client_seconds': time.monotonic() - progress.start, 'connect_seconds': connected,
                    'first_byte_seconds': progress.first_byte, 'sha256': hashlib.sha256(data).hexdigest(),
                    'sha256_verified': False, 'md5_verified': method == 'PUT'}
    except (TimeoutError, ConnectionError, http.client.HTTPException):
        raise release.ProbeFailure('probe_network', progress) from None
    except OSError:
        raise release.ProbeFailure('probe_io', progress) from None
    finally:
        connection.close()


def failure_code(error):
    if isinstance(error, release.ProbeFailure):
        return error.detail['code']
    try:
        value = json.loads(str(error))
        return value.get('code', 'probe_protocol') if isinstance(value, dict) else 'probe_protocol'
    except ValueError:
        return str(error) if str(error) in {
            'probe_http', 'probe_integrity', 'probe_boundary', 'probe_pending', 'receiver_upgrade_required',
            'pending_release', 'original_site_unhealthy', 'original_site_unreachable', 'state_changed',
            'cancelled', 'probe_cleanup'} else 'probe_protocol'


def measure(report, path, round_number, function):
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    row = {'path': path, 'round': round_number, 'utc': now.isoformat(),
           'beijing': now.astimezone(timezone(timedelta(hours=8))).isoformat(), 'total': release.PROBE_SIZE}
    report['samples'].append(row)
    try:
        row.update(function())
        row['bytes_per_second'] = row['bytes'] / max(row['client_seconds'], .000001)
    except Exception as error:
        code = failure_code(error)
        row.update(status='failed', code=code, client_seconds=time.monotonic() - start)
        try:
            detail = error.detail if isinstance(error, release.ProbeFailure) else json.loads(str(error))
            if isinstance(detail, dict):
                row.update(ssh_client.progress_fields(detail))
        except ValueError:
            pass
        if code not in NETWORK_CODES:
            raise RuntimeError(code) from None
    return row


def summarize(report):
    report.pop('estimated_direct_seconds', None)
    report.pop('estimated_relay_seconds', None)
    speeds = {}
    for path in ('ssh', 'cos_upload', 'cos_download'):
        rows = [row for row in report['samples'] if row['path'] == path]
        if len(rows) == 3 and all(row.get('status') == 'measured' and row.get('sha256_verified') for row in rows):
            values = [row['bytes_per_second'] for row in rows]
            speeds[path] = {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    report['speeds_bytes_per_second'] = speeds
    report['recommend_large_test'] = False
    if len(speeds) == 3:
        direct = PACKAGE_BYTES / speeds['ssh']['median']
        relay = sum(PACKAGE_BYTES / speeds[path]['median'] for path in ('cos_upload', 'cos_download'))
        report.update(estimated_direct_seconds=direct, estimated_relay_seconds=relay,
                      recommend_large_test=relay <= 1800 and direct >= relay * 4)
    report['limitation'] = 'Small-file screening only; not deployment acceptance or network root-cause proof.'


def save_report(report, directory):
    summarize(report)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = ['# PPT 三段网络测速', '', '仅小文件筛选，不代表大包发布成功或运营商根因确认。', '',
             '| 链路 | 轮次 | 状态 | 平均 KiB/s |', '|---|---:|---|---:|']
    for row in report['samples']:
        lines.append(f"| {row['path']} | {row['round']} | {row.get('code', row.get('status', 'interrupted'))} | {row.get('bytes_per_second', 0)/1024:.2f} |")
    lines += ['', '建议下一轮大文件测试：' + ('是' if report['recommend_large_test'] else '否／证据不足'),
              '已知待清理对象：' + ', '.join(report['outstanding_objects']),
              '结束检查：' + report.get('postcheck', '未执行'),
              '错误代码：' + report.get('fatal', '无')]
    if 'estimated_relay_seconds' in report:
        lines += [f"预计完整包：直传 {report['estimated_direct_seconds']/60:.1f} 分钟，中转两段合计 {report['estimated_relay_seconds']/60:.1f} 分钟。"]
    content = '\n'.join(lines) + '\n'
    (directory / 'summary.md').write_text(content, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as output:
            output.write(content)


def run_probe(command, cos, report, directory):
    before = None
    try:
        before = state(command)
        site_health()
        report['state_before'] = before
        for round_number in range(1, 4):
            probe = report['run'] + '-' + str(round_number)
            data = os.urandom(release.PROBE_SIZE)
            header = {'probe': probe, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            measure(report, 'ssh', round_number, lambda: request(command, {'op': 'probe_receive', **header}, data))
            key = 'transfer-probe/' + probe + '.bin'
            report['outstanding_objects'].append(key)
            save_report(report, directory)  # Breadcrumb survives a hard cancellation.
            try:
                uploaded = measure(report, 'cos_upload', round_number,
                                   lambda: cos_request('PUT', signed_url(cos, 'PUT', probe), probe, data))
                if uploaded['status'] == 'measured':
                    downloaded = measure(report, 'cos_download', round_number, lambda: request(command,
                        {'op': 'probe_download', 'url': signed_url(cos, 'GET', probe), **header}))
                    uploaded['sha256_verified'] = downloaded.get('sha256_verified', False)
                else:
                    report['samples'].append({'path': 'cos_download', 'round': round_number, 'status': 'skipped', 'code': 'upload_failed'})
            finally:
                try:
                    cos_request('DELETE', signed_url(cos, 'DELETE', probe), probe)
                    report['outstanding_objects'].remove(key)
                except Exception:
                    raise RuntimeError('probe_cleanup') from None
            save_report(report, directory)
    except BaseException as error:
        report['fatal'] = failure_code(error)
    finally:
        if before is not None:
            try:
                require(state(command) == before, 'state_changed')
                site_health()
                report['postcheck'] = 'passed'
            except Exception as error:
                report['postcheck'] = failure_code(error)
                report.setdefault('fatal', report['postcheck'])
        save_report(report, directory)
    return 1 if report.get('fatal') or any(row.get('status') != 'measured' for row in report['samples']) else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'main_only')
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    require(re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,2}', run), 'invalid_run')
    sha = os.environ['GITHUB_SHA']
    require(re.fullmatch(r'[0-9a-f]{40}', sha), 'invalid_sha')
    now = datetime.now(timezone.utc)
    report = {'schema': 1, 'app_sha': sha, 'run': run, 'samples': [], 'outstanding_objects': [],
              'python': sys.version.split()[0], 'cos_sdk': importlib.metadata.version('cos-python-sdk-v5'),
              'receiver_capability': CAPABILITY,
              'utc': now.isoformat(), 'beijing': now.astimezone(timezone(timedelta(hours=8))).isoformat()}
    # CI cancellation receives a bounded cleanup opportunity; SIGKILL cannot be guaranteed.
    def interrupted(*_):
        raise RuntimeError('cancelled')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with tempfile.TemporaryDirectory(prefix='ppt-probe-ssh-') as temporary:
        try:
            return run_probe(credentials(Path(temporary)), signer(), report, args.output)
        except BaseException as error:
            report['fatal'] = failure_code(error)
            save_report(report, args.output)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
