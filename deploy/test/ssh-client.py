"""Manual-workflow client. Only the deployment SSH credential leaves GitHub."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import queue
import time

CONTROL_TIMEOUT = 960
UPLOAD_TIMEOUT = 3900
PHASES = {"receive", "archive", "image", "normalize", "stored", "probe_receive", "probe_download", "probe_upload"}
ERROR_CODES = {"transfer_idle", "transfer_timeout", "processing_timeout",
               "receiver_error", "prior_state_restored", "probe_timeout", "probe_idle", "probe_network",
               "probe_auth", "probe_http", "probe_integrity", "probe_io", "probe_cleanup", "probe_boundary", "probe_pending", "probe_cancelled"}


def require_capabilities(value, settings=False):
    if (value.get("receiver_version") != 2 or not isinstance(value.get("capabilities"), list) or
            not {"upload-progress-v1", "phased-upload-deadlines-v1"}.issubset(
                value.get("capabilities", []))):
        raise RuntimeError("Receiver upgrade required before publish")
    if settings and ("admin-model-settings-v1" not in value.get("capabilities", []) or not value.get("model_settings_ready")):
        raise RuntimeError("Receiver upgrade and administrator model-settings initialization required before upload")


def progress_fields(value):
    if value.get("phase") not in PHASES:
        return {}
    fields = {key: value.get(key) for key in ("received", "total", "elapsed")}
    if not all(type(n) in (int, float) and 0 <= n <= 2 * 1024**3 and math.isfinite(n) for n in fields.values()):
        return {}
    if fields["received"] > fields["total"] or fields["total"] > 2 * 1024**3:
        return {}
    return {"phase": value["phase"], **fields}


def read_pipe(stream, channel, events, stopped):
    try:
        while line := stream.readline(65537):
            while not stopped.is_set():
                try:
                    events.put((channel, line), timeout=.1)
                    break
                except queue.Full:
                    continue
            if stopped.is_set():
                return
    finally:
        stream.close()
        while not stopped.is_set():
            try:
                events.put((channel, None), timeout=.1)
                break
            except queue.Full:
                continue


def run_request(command, payload, timeout):
    events, stopped = queue.Queue(maxsize=32), threading.Event()
    process = subprocess.Popen(command, stdin=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    readers = [threading.Thread(target=read_pipe, args=(stream, name, events, stopped), daemon=True)
               for stream, name in ((process.stdout, "out"), (process.stderr, "err"))]
    for reader in readers:
        reader.start()
    end = time.monotonic() + timeout
    output, closed, failure = bytearray(), set(), None
    latest = {"phase": "awaiting_receiver", "received": None, "total": None}
    try:
        while len(closed) < 2 or process.poll() is None:
            if time.monotonic() >= end:
                raise RuntimeError("client_timeout " + json.dumps(latest))
            try:
                channel, line = events.get(timeout=min(.1, max(.001, end - time.monotonic())))
            except queue.Empty:
                continue
            if line is None:
                closed.add(channel)
                continue
            if len(line) > 65536:
                raise RuntimeError("Receiver response exceeds limit")
            if channel == "out":
                output.extend(line)
                if len(output) > 65536:
                    raise RuntimeError("Receiver response exceeds limit")
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(value, dict):
                continue
            fields = progress_fields(value)
            if fields and value.get("event") == "progress":
                latest = fields
                print(json.dumps({"event": "progress", **fields}), flush=True)
            if value.get("status") == "failed" and value.get("code") in ERROR_CODES:
                failure = {"code": value["code"], **fields}
        if process.wait() != 0:
            raise RuntimeError(json.dumps(failure) if failure else
                               "SSH/receiver failed; verify connectivity and receiver installation")
        if failure:
            raise RuntimeError(json.dumps(failure))
        try:
            value = json.loads(output)
        except (ValueError, UnicodeError) as error:
            raise RuntimeError("Unexpected receiver response") from error
        if not isinstance(value, dict) or value.get("status") == "failed":
            raise RuntimeError("Unexpected receiver response")
        print(json.dumps(value), flush=True)
        return value
    finally:
        stopped.set()
        if process.poll() is None:
            process.kill()
        process.wait()
        for reader in readers:
            reader.join(timeout=2)


def external_port_closed(host):
    try:
        connection = socket.create_connection((host, 5000), timeout=5)
    except (TimeoutError, ConnectionRefusedError):
        return
    except OSError as error:
        raise RuntimeError("Cannot verify external port; inspect connectivity before release") from error
    else:
        connection.close()
        raise RuntimeError("Port 5000 is publicly reachable; stop and inspect the binding/firewall")


def request(command, header, bundle=None):
    with tempfile.TemporaryFile() as payload:
        payload.write(json.dumps(header).encode() + b"\n")
        if bundle:
            with bundle.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    payload.write(chunk)
        payload.seek(0)
        return run_request(command, payload, UPLOAD_TIMEOUT if header.get("op") == "upload" else CONTROL_TIMEOUT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("publish", "rollback", "status"))
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--stage", choices=("all", "upload", "activate"), default="all")
    args = parser.parse_args()
    if args.operation != "publish" and args.stage != "all":
        raise RuntimeError("Staged operations are only available for publish")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RuntimeError("Manual releases accept main only")
    host = os.environ["DEPLOY_HOST"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}", host):
        raise RuntimeError("Invalid deployment host")
    with tempfile.TemporaryDirectory(prefix="ppt-ssh-") as directory:
        root = Path(directory)
        key, known = root / "key", root / "known_hosts"
        for path, variable in ((key, "DEPLOY_SSH_KEY"), (known, "SSH_KNOWN_HOSTS")):
            value = os.environ[variable]
            if not value.strip():
                raise RuntimeError("Missing deployment credential: " + variable)
            path.write_text(value.rstrip() + "\n", encoding="utf-8")
            path.chmod(0o600)
        command = ["ssh", "-F", "/dev/null", "-T", "-p", "22", "-i", str(key),
                   "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                   "-o", "UserKnownHostsFile=" + str(known), "-o", "GlobalKnownHostsFile=/dev/null",
                   "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                   "yuling-ppt-deploy@" + host]
        status = request(command, {"op": "status"})
        if args.operation == "status":
            return
        require_capabilities(status, settings=args.operation == "publish")
        external_port_closed(host)
        if args.operation == "publish":
            if args.bundle is None:
                raise RuntimeError("Publish requires a verified release bundle")
            manifest = json.loads(args.bundle.with_name("release.json").read_text())
            if manifest["app_sha"] != os.environ["GITHUB_SHA"]:
                raise RuntimeError("Bundle differs from the selected main commit")
            with args.bundle.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            expected = args.bundle.with_name("bundle.sha256").read_text().split()[0]
            if checksum != expected:
                raise RuntimeError("Release bundle checksum mismatch")
            if args.stage in ("all", "upload"):
                request(command, {"op": "upload", "release": manifest["release"],
                                  "bytes": args.bundle.stat().st_size, "sha256": checksum}, args.bundle)
            if args.stage in ("all", "activate"):
                request(command, {"op": "deploy", "release": manifest["release"]})
        else:
            request(command, {"op": "rollback"})
        external_port_closed(host)


if __name__ == "__main__":
    main()
