"""Manual-workflow client. Only the deployment SSH credential leaves GitHub."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile


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
        result = subprocess.run(command, stdin=payload, capture_output=True, timeout=960)
    if result.returncode:
        # Receiver errors contain no environment, but do not echo arbitrary SSH banners.
        try:
            detail = json.loads(result.stderr)
            reason = detail.get("error", "Remote operation failed")
        except (ValueError, UnicodeError):
            reason = "SSH/receiver failed; verify host key, connectivity and bootstrap installation"
        raise RuntimeError(reason)
    value = json.loads(result.stdout)
    if not isinstance(value, dict) or value.get("status") == "failed":
        raise RuntimeError("Unexpected receiver response")
    print(json.dumps(value))
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("publish", "rollback", "status"))
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
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
        request(command, {"op": "status"})
        if args.operation == "status":
            return
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
            request(command, {"op": "upload", "release": manifest["release"],
                              "bytes": args.bundle.stat().st_size, "sha256": checksum}, args.bundle)
            request(command, {"op": "deploy", "release": manifest["release"]})
        else:
            request(command, {"op": "rollback"})
        external_port_closed(host)


if __name__ == "__main__":
    main()
