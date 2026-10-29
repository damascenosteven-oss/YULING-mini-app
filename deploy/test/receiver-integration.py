"""Actual SSH -> forced command -> receiver -> Docker transaction test, local/CI only.

Uses a disposable receiver container, never SSHes to a user-supplied host. Refuses
to start if the Docker engine already contains PPT deployment resources.
"""
import argparse
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import os
import sys
from unittest.mock import patch
from types import SimpleNamespace

HERE = Path(__file__).resolve().parents[2]
APP = "yuling-ppt-test"
ENGINE = "be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192"
NODE = "node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1"


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, **kwargs).stdout


def sha(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fixture(root, letter, failed=False):
    source = letter * 40
    rid = source[:12] + "-998-1"
    tag = APP + ":" + rid
    directory = root / letter
    directory.mkdir()
    server = "process.exit(1);" if failed else """require('http').createServer((q,r)=>{
if(q.url==='/api/health')r.end('ok');
else if(q.url.startsWith('/_next/static/'))r.end('fixture');
else r.end('<script src="/_next/static/fixture.js"></script>');
}).listen(5000,'0.0.0.0');"""
    (directory / "server.js").write_text(server)
    (directory / "release-smoke.js").write_text("console.log('transaction fixture only');")
    (directory / "Dockerfile").write_text(f'''FROM {NODE}
LABEL dev.yuling.application="{APP}" org.opencontainers.image.revision="{source}" dev.yuling.engine.revision="{ENGINE}" dev.yuling.source.dirty="false"
WORKDIR /fixture
COPY server.js dist/server.js
COPY release-smoke.js dist/release-smoke.js
USER 10001:10001
CMD ["node","dist/server.js"]
''')
    run("docker", "build", "--pull=false", "-t", tag, directory)
    image = directory / "image.tar.gz"
    with image.open("wb") as file, gzip.GzipFile(fileobj=file, mode="wb", mtime=0) as compressed:
        process = subprocess.Popen(["docker", "image", "save", tag], stdout=subprocess.PIPE)
        shutil.copyfileobj(process.stdout, compressed)
        process.stdout.close()
        if process.wait():
            raise RuntimeError("Fixture export failed")
    with tarfile.open(image) as archive:
        entry = json.load(archive.extractfile("manifest.json"))[0]
        identity = "sha256:" + hashlib.sha256(archive.extractfile(entry["Config"]).read()).hexdigest()
    manifest = {"schema": 1, "application": APP, "release": rid, "app_sha": source,
                "engine_sha": ENGINE, "image_id": identity, "image_tag": tag, "image_sha256": sha(image)}
    (directory / "release.json").write_text(json.dumps(manifest))
    bundle = directory / "bundle.tar"
    with tarfile.open(bundle, "w") as archive:
        archive.add(image, arcname="image.tar.gz")
        archive.add(directory / "release.json", arcname="release.json")
    return rid, tag, bundle


def prepared_entry(output, bundle, ssh, client, key, known):
    """Transaction fixture only: real relay handler -> real client CLI -> real SSH."""
    import prepared_release as prepared
    spec = importlib.util.spec_from_file_location("prepared_bridge_entry", HERE / "deploy/test/local-bridge.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    manifest = json.loads(bundle.with_name("release.json").read_text())
    source = manifest["app_sha"]
    state = output / "prepared-entry-state"
    state.mkdir(mode=0o700)
    package = prepared.root_directory(state) / source
    package.mkdir()
    shutil.copyfile(bundle, package / "bundle.tar")
    shutil.copyfile(bundle.with_name("release.json"), package / "release.json")
    (package / "bundle.sha256").write_text(sha(bundle) + "  bundle.tar\n")
    shutil.copyfile(HERE / "deploy/test/ssh-client.py", package / "ssh-client.py")
    inputs = {k: "d" * 64 for k in prepared.INPUTS}
    (package / "inputs.json").write_text(json.dumps(inputs))
    (package / "verification.json").write_text(json.dumps({"schema": 1, "app_sha": source,
        "engine_sha": ENGINE, "image_id": manifest["image_id"], "source_dirty": False,
        "pages": 12, "captures": 2, "differences": 0}))
    audits = package / "audits/fixture"
    audits.mkdir(parents=True)
    (audits / "audit.json").write_text(json.dumps({**inputs, "audited_at": datetime.now(timezone.utc).isoformat()}))
    for name in ("audit-full.json", "audit-prod.json"):
        (audits / name).write_text(json.dumps({"metadata": {"vulnerabilities": {
            k: 0 for k in ("info", "low", "moderate", "high", "critical")}}}))
    prepared.seal(package, source, "fixture")
    dep = {"id": 99, "sha": source, "ref": source, "environment": bridge.ENVIRONMENT,
           "creator": {"login": "github-actions[bot]"}, "payload": {"schema": 2, "operation": "publish",
           "run_id": 42, "attempt": 1, "actor": bridge.OWNER,
           "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}}
    class API:
        def __init__(self): self.state = "pending"
        def call(self, route, data=None):
            if data is not None: self.state = data["state"]; return {}
            if route.startswith("/actions/runs/"):
                return {"id": 42, "run_attempt": 1, "event": "workflow_dispatch", "head_branch": "main",
                        "head_sha": source, "status": "in_progress", "path": ".github/workflows/test-site.yml",
                        "actor": {"login": bridge.OWNER}}
            if route == "/branches/main": return {"commit": {"sha": source}, "protected": True}
            if "/check-runs" in route:
                return {"check_runs": [{"name": n, "head_sha": source, "conclusion": "success", "id": i}
                                       for i, n in enumerate(bridge.CHECKS)]}
            if "/statuses" in route: return [{"state": self.state}]
            raise AssertionError(route)
    api = API()
    actual_request = client.request
    def execute(*args, env=None):
        assert str(args[1]).endswith("ssh-client.py"), "publish attempted preparation"
        # Only the credential-free fixture address/port is substituted here.
        with patch.dict(os.environ, env), patch.object(sys, "argv", list(map(str, args[1:]))), \
                patch.object(client, "request", side_effect=lambda command, header, data=None: actual_request(ssh, header, data)), \
                patch.object(client, "external_port_closed"):
            client.main()
    known.chmod(0o600)
    config = {"state_dir": str(state), "host": "127.0.0.1", "ssh_key": str(key), "known_hosts": str(known)}
    with patch.object(bridge, "run", side_effect=execute), \
            patch.object(bridge, "prepare_sources", side_effect=AssertionError("publish attempted source retrieval")):
        bridge.handle(api, dep, config, state)
    assert api.state == "success"
    assert client.request(ssh, {"op": "status"})["current"] == manifest["release"]
    (output / "prepared-entry.json").write_text(json.dumps({"passed": True,
        "fixture_evidence_only": True, "entry": "schema2 relay -> package -> client CLI -> restricted SSH -> Docker"}))
    print("PASS: prepared package real relay/client SSH entry; no build, registry or audit at publish", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output.is_relative_to(HERE):
        raise RuntimeError("Use a new external evidence directory")
    for name in (APP, APP + "-check"):
        if run("docker", "container", "ls", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}").strip():
            raise RuntimeError("Existing PPT container; use a separate test Docker engine")
    if APP in run("docker", "network", "ls", "--format", "{{.Name}}", text=True).splitlines():
        raise RuntimeError("Existing PPT network; use a separate test Docker engine")
    output.mkdir()
    prefix = "yuling-receiver-test-" + uuid.uuid4().hex[:8]
    host, edge, network = prefix + "-host", prefix + "-edge", prefix + "-network"
    host_image = "yuling-issue8-receiver-fixture:local"
    tags = []
    fixture_ids = set()
    spec = importlib.util.spec_from_file_location("client", HERE / "deploy/test/ssh-client.py")
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    # Capture full structured failures only in this credential-free fixture.
    # Production client logs remain restricted to codes and progress fields.
    failures = []
    def record_failure(data, *args, **kwargs):
        value = json.loads(data, *args, **kwargs)
        if isinstance(value, dict) and value.get("status") == "failed":
            failures.append(value)
        return value
    client.json = SimpleNamespace(loads=record_failure, dumps=json.dumps)
    try:
        run("docker", "build", "--pull=false", "-f", HERE / "deploy/test/receiver-fixture.Dockerfile",
            "-t", host_image, HERE)
        run("docker", "network", "create", "--label", "dev.yuling.integration=" + prefix, network)
        run("docker", "run", "-d", "--name", edge, "--network", network, NODE,
            "node", "-e", "setInterval(()=>{},10000)")
        gateway = json.loads(run("docker", "network", "inspect", network))[0]["IPAM"]["Config"][0]["Gateway"]
        run("docker", "run", "-d", "--name", host, "--publish", "127.0.0.1::22",
            "--mount", "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock", host_image)
        port = run("docker", "port", host, "22/tcp", text=True).strip().rsplit(":", 1)[1]
        with tempfile.TemporaryDirectory(prefix="yuling-fixture-ssh-") as credentials:
            key = Path(credentials) / "key"
            run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key)
            config = {"gateway": gateway, "caddy_network": network, "caddy_container": edge}
            setup = """import pathlib,json,os,sys
c=json.loads(sys.stdin.read()); root=pathlib.Path('/etc/yuling-ppt-test')
for name,data in [('config.json',json.dumps(c['config'])),('app.env','')]:
 p=root/name;p.write_text(data);p.chmod(0o600)
p=pathlib.Path('/home/yuling-ppt-deploy/.ssh');p.mkdir();p.chmod(0o755)
f=p/'authorized_keys';f.write_text('restrict,command="sudo -n /usr/bin/python3 -I /usr/local/libexec/yuling-ppt-release.py" '+c['key'].strip()+'\\n');f.chmod(0o644)
"""
            run("docker", "exec", "-i", host, "python", "-c", setup,
                input=json.dumps({"config": config, "key": key.with_suffix(".pub").read_text()}).encode())
            host_key = run("docker", "exec", host, "cat", "/etc/ssh/ssh_host_ed25519_key.pub", text=True).strip()
            known = Path(credentials) / "known_hosts"
            known.write_text("[127.0.0.1]:" + port + " " + host_key + "\n")
            ssh = ["ssh", "-F", "none", "-T", "-p", port, "-i", str(key), "-o", "BatchMode=yes",
                   "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
                   "-o", "UserKnownHostsFile=" + str(known), "yuling-ppt-deploy@127.0.0.1"]
            # A changed host key must fail before any receiver operation.
            correct = known.read_text()
            known.write_text("[127.0.0.1]:" + port + " " + key.with_suffix(".pub").read_text())
            try:
                client.request(ssh, {"op": "status"})
            except RuntimeError:
                print("PASS: mismatched host key rejected", flush=True)
            else:
                raise AssertionError("Mismatched host key was accepted")
            known.write_text(correct)
            assert client.request(ssh, {"op": "status"})["current"] is None
            transfer_spec = importlib.util.spec_from_file_location("transfer_entry", HERE / "deploy/test/transfer-entry-checks.py")
            transfer = importlib.util.module_from_spec(transfer_spec)
            transfer_spec.loader.exec_module(transfer)
            transfer.checks(run, host, ssh, client, output)
            probe_spec = importlib.util.spec_from_file_location("probe_entry", HERE / "deploy/test/probe-entry-checks.py")
            probe = importlib.util.module_from_spec(probe_spec)
            probe_spec.loader.exec_module(probe)
            probe.checks(run, host, ssh, output)
            for index, letter in enumerate(("a", "b", "c")):
                rid, tag, bundle = fixture(output, letter, failed=letter == "c")
                tags.append(tag)
                fixture_ids.add(rid)
                header = {"op": "upload", "release": rid, "bytes": bundle.stat().st_size, "sha256": sha(bundle)}
                bad = {**header, "sha256": "0" * 64}
                try:
                    client.request(ssh, bad, bundle)
                except RuntimeError:
                    print("PASS: corrupt upload rejected", flush=True)
                else:
                    raise AssertionError("Corrupt upload accepted")
                if index == 0:
                    prepared_entry(output, bundle, ssh, client, key, known)
                else:
                    client.request(ssh, header, bundle)
                if index == 1:
                    assert client.request(ssh, {"op": "deploy", "release": rid})["current"] == rid
                elif index == 2:
                    try:
                        client.request(ssh, {"op": "deploy", "release": rid})
                    except RuntimeError as error:
                        assert "restored" in str(error), str(error)
                    else:
                        raise AssertionError("Broken candidate was accepted")
                    assert client.request(ssh, {"op": "status"})["current"] == "b" * 12 + "-998-1"
            result = client.request(ssh, {"op": "rollback"})
            assert result["current"] == "a" * 12 + "-998-1"
            # Supplying an arbitrary remote command cannot escape the forced receiver.
            assert client.request(ssh + ["touch /tmp/ssh-command-escaped"], {"op": "status"})["current"] == result["current"]
            run("docker", "exec", host, "test", "!", "-e", "/tmp/ssh-command-escaped")
            (output / "result.json").write_text(json.dumps({"passed": True, "entry": "SSH forced command -> receiver -> Docker",
                "app_fixture_only": True, "real_server_tested": False, "rollback": result}, indent=2))
            print("PASS: actual SSH upload, publish, failed-start recovery, rollback and forced-command restriction", flush=True)
    except Exception:
        (output / "fixture-receiver-errors.json").write_text(json.dumps(failures, indent=2))
        # The fixture contains no real credentials. Preserve failure diagnostics
        # before cleanup; production receiver intentionally suppresses Docker stderr.
        diagnostics = subprocess.run(["docker", "exec", host, "cat", "/tmp/docker-fixture-errors"], capture_output=True)
        (output / "fixture-docker-errors.log").write_bytes(diagnostics.stdout)
        for name in (APP, APP + "-check"):
            inspected = subprocess.run(["docker", "container", "inspect", name], capture_output=True)
            if inspected.returncode == 0:
                item = json.loads(inspected.stdout)[0]
                (output / (name + "-state.json")).write_text(json.dumps(item["State"], indent=2))
        raise
    finally:
        for name in (APP + "-check", APP):
            values = run("docker", "container", "ls", "-a", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}", text=True).splitlines()
            for identity in values:
                labels = json.loads(run("docker", "inspect", identity))[0]["Config"]["Labels"]
                if labels.get("dev.yuling.release") in fixture_ids:
                    run("docker", "rm", "-f", identity)
        for name in (host, edge):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        for name in (APP, network):
            subprocess.run(["docker", "network", "rm", name], capture_output=True)
        for tag in tags:
            subprocess.run(["docker", "image", "rm", tag], capture_output=True)


if __name__ == "__main__":
    main()
