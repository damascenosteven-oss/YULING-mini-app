"""Real restricted SSH and local TLS COS simulator; no cloud or user server access."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import time

HELPER = '/usr/local/libexec/yuling-ppt-release.py'
HOST = 'yuling-ppt-test-1494859304.cos.ap-shanghai.myqcloud.com'


def checks(run, host, ssh, output):
    spec = importlib.util.spec_from_file_location('probe_client_entry', Path(__file__).with_name('network-probe.py'))
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    original = run('docker', 'exec', host, 'cat', HELPER)
    header = {'op': 'probe_receive', 'probe': '123-1-1', 'bytes': 4194304,
              'sha256': hashlib.sha256(b'x' * 4194304).hexdigest()}
    def write(path, data):
        run('docker', 'exec', '-i', host, 'python', '-c',
            'import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())', path, input=data)
    def clean():
        run('docker', 'exec', host, 'python', '-c',
            "from pathlib import Path;assert not list(Path('/opt/yuling-ppt-test/.incoming').iterdir());assert not Path('/opt/yuling-ppt-test/state.json').exists()")
    def fail(request, data=b'', code=None, command=None):
        try:
            client.request(command or ssh, request, data)
        except RuntimeError as error:
            if code:
                assert code in str(error), str(error)
        else:
            raise AssertionError('Probe fault accepted')
        clean()
    before = client.state(ssh)
    assert client.request(ssh, header, b'x' * 4194304)['cleaned']
    fail(header, b'x' * 4194303, 'probe_integrity')
    fail(header, b'x' * 4194305, 'probe_integrity')
    fail({**header, 'sha256': '0'*64}, b'x' * 4194304, 'probe_integrity')
    fail({**header, 'seconds': 999}, code='receiver_error')
    # Timers are shortened in this disposable helper only, never via a request.
    slow = 'import subprocess,sys,time;p=subprocess.Popen(sys.argv[1:],stdin=subprocess.PIPE);p.stdin.write(sys.stdin.buffer.readline());p.stdin.flush();time.sleep(2);p.stdin.close();sys.exit(p.wait())'
    try:
        for needle, replacement, code in (
                (b'PROBE_IDLE = 60', b'PROBE_IDLE = .2', 'probe_idle'),
                (b'PROBE_SECONDS = 300', b'PROBE_SECONDS = .2', 'probe_timeout')):
            assert original.count(needle) == 1
            write(HELPER, original.replace(needle, replacement))
            fail(header, command=[sys.executable, '-c', slow, *ssh], code=code)
    finally:
        write(HELPER, original)
    # Advisory lock must reject a real forced-command request.
    holder = subprocess.Popen(['docker', 'exec', host, 'python', '-c',
        "import fcntl,time;f=open('/opt/yuling-ppt-test/receiver.lock','a');fcntl.flock(f,fcntl.LOCK_EX);print('locked',flush=True);time.sleep(3)"], stdout=subprocess.PIPE)
    try:
        assert holder.stdout.readline().strip() == b'locked'
        fail(header, code='receiver_error')
    finally:
        holder.wait(timeout=10)
        holder.stdout.close()
    # Local HTTPS fixture: exact hostname and TLS verification remain enabled.
    run('docker', 'exec', host, 'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
        '-keyout', '/tmp/probe-key.pem', '-out', '/usr/local/share/ca-certificates/probe.crt',
        '-days', '1', '-subj', '/CN=' + HOST, '-addext', 'subjectAltName=DNS:' + HOST)
    run('docker', 'exec', host, 'update-ca-certificates')
    run('docker', 'exec', host, 'python', '-c',
        "from pathlib import Path;p=Path('/etc/hosts');p.write_text(p.read_text()+'\\n127.0.0.1 " + HOST + "\\n')")
    server = '''import ssl,http.server,pathlib,hashlib,base64
class Handler(http.server.BaseHTTPRequestHandler):
 def do_PUT(self):
  data=self.rfile.read(int(self.headers['Content-Length']))
  assert len(data)==4194304
  assert self.headers['Content-MD5']==base64.b64encode(hashlib.md5(data).digest()).decode()
  pathlib.Path('/tmp/probe-put').write_bytes(data)
  self.send_response(200);self.send_header('ETag','"'+hashlib.md5(data).hexdigest()+'"');self.send_header('Content-Length','0');self.end_headers()
 def do_DELETE(self):
  pathlib.Path('/tmp/probe-put').unlink(missing_ok=True)
  self.send_response(204);self.end_headers()
 def do_GET(self):
  mode=pathlib.Path('/tmp/probe-mode').read_text()
  data=b'x'*4194304
  if mode=='bad':data=b'y'*4194304
  status=int(mode) if mode.isdigit() else 200
  self.send_response(status);self.send_header('Content-Length',str(len(data)));self.end_headers()
  if status==200:self.wfile.write(data)
 def log_message(self,*args):pass
s=http.server.HTTPServer(('127.0.0.1',443),Handler)
c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);c.load_cert_chain('/usr/local/share/ca-certificates/probe.crt','/tmp/probe-key.pem')
s.socket=c.wrap_socket(s.socket,server_side=True);pathlib.Path('/tmp/probe-ready').touch();s.serve_forever()
'''
    write('/tmp/probe-http.py', server.encode())
    write('/tmp/probe-mode', b'good')
    run('docker', 'exec', '-d', host, 'python', '/tmp/probe-http.py')
    for _ in range(30):
        if subprocess.run(['docker', 'exec', host, 'test', '-e', '/tmp/probe-ready']).returncode == 0:
            break
        time.sleep(.1)
    else:
        raise AssertionError('TLS fixture unavailable')
    download = {**header, 'op': 'probe_download', 'url': 'https://' + HOST + '/transfer-probe/123-1-1.bin?signature=fixture-only'}
    measured = client.request(ssh, download)
    assert measured['peer'] == '127.0.0.1' and measured['sha256_verified']
    run('docker', 'exec', host, 'mkdir', '/tmp/probe-scripts')
    for name in ('network-probe.py', 'ssh-client.py', 'release.py'):
        run('docker', 'cp', Path(__file__).with_name(name), host + ':/tmp/probe-scripts/' + name)
    upload_test = '''import importlib.util,sys
sys.path.insert(0,'/tmp/probe-scripts')
s=importlib.util.spec_from_file_location('p','/tmp/probe-scripts/network-probe.py');p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
url='https://'+p.release.PROBE_HOST+'/transfer-probe/123-1-1.bin?signature=local-fixture'
r=p.cos_request('PUT',url,'123-1-1',b'x'*4194304)
assert r['md5_verified'] and r['bytes']==4194304 and r['peer']=='127.0.0.1'
p.cos_request('DELETE',url,'123-1-1')
from pathlib import Path
assert not Path('/tmp/probe-put').exists()
'''
    run('docker', 'exec', host, 'python', '-c', upload_test)
    for mode, code in (('302', 'probe_http'), ('403', 'probe_auth'), ('bad', 'probe_integrity')):
        write('/tmp/probe-mode', mode.encode())
        fail(download, code=code)
    fail({**download, 'url': 'https://example.invalid/'}, code='receiver_error')
    assert client.state(ssh) == before
    clean()
    (output / 'probe-entry.json').write_text(json.dumps({'passed': True,
        'entry': 'client -> restricted SSH -> receiver -> local TLS COS simulator',
        'cloud_tested': False, 'production_server_tested': False, 'release_state_unchanged': True}, indent=2))
    print('PASS: bounded probes, real SSH deadlines/lock/cleanup and local TLS download; not cloud measurement', flush=True)
