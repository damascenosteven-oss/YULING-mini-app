"""Fault injection inside the disposable SSH fixture, never a production request option."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys

from release_test import bundle

HELPER = "/usr/local/libexec/yuling-ppt-release.py"


def checks(run, host, ssh, client, output):
    original = run("docker", "exec", host, "cat", HELPER)
    # Exercise the reviewed administrator CLI, then the restricted status request.
    legacy = original.replace(b"RECEIVER_VERSION = 2", b"RECEIVER_VERSION = 1")
    assert legacy != original
    run("docker", "exec", "-i", host, "python", "-c",
        "import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())", HELPER,
        input=legacy)
    try:
        client.require_capabilities(client.request(ssh, {"op": "status"}))
    except RuntimeError as error:
        assert "upgrade" in str(error)
    else:
        raise AssertionError("Legacy receiver accepted")
    run("docker", "exec", host, "mkdir", "/tmp/receiver-upgrade")
    for name in ("bootstrap.py", "release.py"):
        run("docker", "cp", Path(__file__).with_name(name), host + ":/tmp/receiver-upgrade/" + name)
    for _ in range(2):
        run("docker", "exec", host, "python", "/tmp/receiver-upgrade/bootstrap.py", "upgrade-receiver",
            "--expected-sha256", hashlib.sha256(legacy).hexdigest())
    assert run("docker", "exec", host, "cat", HELPER) == original
    client.require_capabilities(client.request(ssh, {"op": "status"}))
    print("PASS: real administrator upgrade CLI, repeat and restricted version handshake", flush=True)
    request, data = bundle()
    path = output / "transfer-fixture.tar"
    path.write_bytes(data)
    sender = '''import subprocess,sys,time
p=subprocess.Popen(sys.argv[2:],stdin=subprocess.PIPE)
try:
 p.stdin.write(sys.stdin.buffer.readline());p.stdin.flush()
 delay=float(sys.argv[1])
 while chunk:=sys.stdin.buffer.read(1024):
  time.sleep(delay);p.stdin.write(chunk);p.stdin.flush()
 p.stdin.close();sys.exit(p.wait())
except BrokenPipeError:
 sys.exit(p.wait() or 1)
finally:
 if p.poll() is None:p.kill();p.wait()
'''

    def install(transfer=5, idle=.7, processing=2, slow_normalize=False):
        source = original.decode()
        for old, new in (("TRANSFER_SECONDS = 2700", f"TRANSFER_SECONDS = {transfer}"),
                         ("IDLE_SECONDS = 120", f"IDLE_SECONDS = {idle}"),
                         ("PROCESSING_SECONDS = 900", f"PROCESSING_SECONDS = {processing}"),
                         ("PROGRESS_SECONDS = 10", "PROGRESS_SECONDS = .1"),
                         ("signal.alarm(900)", "signal.alarm(1)")):
            assert source.count(old) == 1, old
            source = source.replace(old, new)
        if slow_normalize:
            needle = 'progress.phase("normalize")'
            assert source.count(needle) == 1
            source = source.replace(needle, needle + "; time.sleep(1)")
        run("docker", "exec", "-i", host, "python", "-c",
            "import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())", HELPER,
            input=source.encode())

    def clean():
        run("docker", "exec", host, "python", "-c",
            "from pathlib import Path;assert not list(Path('/opt/yuling-ppt-test/.incoming').iterdir())")

    def fail(header, code, delay=0):
        with contextlib.redirect_stdout(io.StringIO()) as progress:
            try:
                client.request([sys.executable, "-u", "-c", sender, str(delay), *ssh], header, path)
            except RuntimeError as error:
                assert code in str(error), str(error)
                (output / (code + ".log")).write_text(progress.getvalue() + str(error))
            else:
                raise AssertionError("Injected " + code + " was accepted")
        clean()
        print("PASS: real SSH " + code + " and cleanup", flush=True)

    try:
        install()
        # Lasts longer than the fixture's legacy 1-second request alarm, with steady data.
        with contextlib.redirect_stdout(io.StringIO()) as progress:
            result = client.request([sys.executable, "-u", "-c", sender, ".15", *ssh], request, path)
            assert result["status"] == "stored"
        (output / "slow-transfer.log").write_text(progress.getvalue())
        clean()
        run("docker", "exec", host, "python", "-c",
            "import pathlib,shutil; p=pathlib.Path('/opt/yuling-ppt-test/releases')/" + repr(request["release"]) +
            ";assert p.parent.name=='releases';shutil.rmtree(p)")
        print("PASS: real SSH continuous slow transfer outlives legacy request budget", flush=True)
        install(idle=.3)
        fail(request, "transfer_idle", delay=.6)
        install(transfer=.5)
        fail(request, "transfer_timeout", delay=.15)
        install(processing=.3, slow_normalize=True)
        fail(request, "processing_timeout")
        install()
        fail({**request, "bytes": len(data) + 1}, "receiver_error")
        clean()
    finally:
        run("docker", "exec", "-i", host, "python", "-c",
            "import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(sys.stdin.buffer.read())", HELPER,
            input=original)
    client.require_capabilities(client.request(ssh, {"op": "status"}))
