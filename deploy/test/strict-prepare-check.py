"""Actual strict-umask prepare handler/build/image/accept path; GitHub is a fixture.

No server credentials or requests. Use a new external directory. Optional cache
seeds contain only verified source/runtime/dependency caches, never credentials.
"""
import argparse
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-state", type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists() or root.is_relative_to(HERE) or os.name != "posix":
        raise RuntimeError("Use a new external Linux evidence directory")
    os.umask(0o077)
    root.mkdir(parents=True)
    state = root / "state"
    state.mkdir()
    caches = state / "source-cache"
    caches.mkdir()
    spec = importlib.util.spec_from_file_location("strict_bridge", HERE / "deploy/test/local-bridge.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    sha = bridge.git_value("-C", HERE, "rev-parse", "HEAD")
    if bridge.git_value("-C", HERE, "status", "--porcelain"):
        raise RuntimeError("Strict check requires a clean committed source")
    run("git", "-C", HERE, "clone", "--bare", "--no-hardlinks", "-q", HERE, caches / "app.git")
    run("git", "-C", caches / "app.git", "remote", "set-url", "origin", bridge.APP_SOURCE)
    if args.seed_state:
        seed = args.seed_state.resolve()
        run("git", "-C", HERE, "clone", "--bare", "--no-hardlinks", "-q",
            seed / "source-cache/engine.git", caches / "engine.git")
        run("git", "-C", caches / "engine.git", "remote", "set-url", "origin", bridge.ENGINE_SOURCE)
        for name in ("runtime-cache", "dependency-cache"):
            shutil.copytree(seed / name, state / name, symlinks=True)
    private = state / "private-proof"
    private.write_text("fixture-only; never copied to image")
    run_id = int(os.environ.get("GITHUB_RUN_ID", str(time.time_ns())))
    dep = {"id": run_id, "sha": sha, "ref": sha, "environment": bridge.PREPARE_ENVIRONMENT,
           "creator": {"login": "github-actions[bot]"}, "payload": {"schema": 2, "operation": "prepare",
           "run_id": run_id, "attempt": 1, "actor": bridge.OWNER,
           "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=110)).isoformat()}}
    class API:
        state = "pending"
        def call(self, route, data=None):
            if data is not None:
                self.state = data["state"]
                return {}
            if route.startswith("/actions/runs/"):
                return {"id": run_id, "run_attempt": 1, "event": "workflow_dispatch", "head_branch": "main",
                        "head_sha": sha, "status": "in_progress", "path": ".github/workflows/test-site.yml",
                        "actor": {"login": bridge.OWNER}}
            if route == "/branches/main": return {"commit": {"sha": sha}, "protected": True}
            if "/check-runs" in route:
                return {"check_runs": [{"id": i, "name": n, "head_sha": sha, "conclusion": "success"}
                                       for i, n in enumerate(bridge.CHECKS)]}
            if "/statuses" in route: return [{"state": self.state}]
            raise AssertionError("Unexpected fixture API route")
    api = API()
    config = {"state_dir": str(state), "host": "115.159.143.24",
              "ssh_key": "forbidden", "known_hosts": "forbidden", "trusted_client": "forbidden"}
    source = bridge.prepare_sources
    checked_modes = []
    def strict_source(*values):
        engine = source(*values)
        file = values[2] / "deploy/test/runtime-lock.json"
        mode = stat.S_IMODE(file.stat().st_mode)
        if mode != 0o600:
            raise AssertionError("Fixture did not reproduce private source permissions")
        checked_modes.append(mode)
        return engine
    execute = bridge.run
    def no_server(*values, **kwargs):
        if any(str(v).endswith("ssh-client.py") for v in values):
            raise AssertionError("Strict prepare attempted a server operation")
        return execute(*values, **kwargs)
    with patch.object(bridge, "prepare_sources", side_effect=strict_source), \
            patch.object(bridge, "run", side_effect=no_server), \
            patch.object(bridge, "secret", side_effect=AssertionError("Prepare read server credentials")):
        bridge.handle(api, dep, config, state)
    package = state / "prepared-releases" / sha
    bridge.prepared.validate(package, sha)
    if api.state != "success" or checked_modes != [0o600] or stat.S_IMODE(private.stat().st_mode) != 0o600:
        raise AssertionError("Strict prepare or private-file protection failed")
    # Prove the final permission gate rejects a deliberate regression in an image.
    info = json.loads((package / "image.json").read_text())
    fault = root / "fault"
    fault.mkdir()
    tag = "yuling-permission-fault:" + str(run_id)
    (fault / "Dockerfile").write_text("FROM " + info["tag"] + "\nUSER 0\n"
        "RUN chmod 000 /opt/yuling/runtime-lock.json\nUSER 10001:10001\n")
    try:
        run("docker", "build", "--pull=false", "-t", tag, fault)
        (fault / "image.json").write_text(json.dumps({**info, "tag": tag}))
        rejected = subprocess.run([sys.executable, str(HERE / "deploy/test/verify-image.py"),
                                  "--build-output", str(fault)], capture_output=True, text=True)
        diagnostic = json.loads((fault / "image-check-error.json").read_text())
        if rejected.returncode != 5 or diagnostic["code"] != "image_permission_denied":
            raise AssertionError("Deliberately unreadable image was not rejected")
        if (fault / "verification.json").exists():
            raise AssertionError("Failed image gained success evidence")
    finally:
        subprocess.run(["docker", "image", "rm", tag], capture_output=True)
    run(sys.executable, HERE / "deploy/test/http-evidence-entry.py",
        "--image-info", package / "image.json", "--output", root / "http-fault")
    (root / "result.json").write_text(json.dumps({"passed": True, "app_sha": sha,
        "github_api_fixture": True, "server_calls": 0, "source_mode": "0600", "umask": "0077",
        "real_prepare_build_verify_accept": True, "permission_fault_rejected": True,
        "package_relative": str(package.relative_to(root))}))
    print("PASS: strict umask real prepare/build/verify/accept; permission fault rejected; no server", flush=True)


if __name__ == "__main__":
    main()
