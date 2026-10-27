"""Owner-operated workstation relay for manually requested test deployments.

Run in Ubuntu WSL with Docker Desktop integration. Credentials live in files
outside the checkout. This process never registers as a public Actions runner.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

OWNER = "damascenosteven-oss"
REPO = "YULING-mini-app"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
ENVIRONMENT = "ppt-test-local-relay"
# engineering-guard is a PR-only check enforced by branch protection. The
# merged main SHA has its own app and release checks but no PR check run.
CHECKS = {"app-checks", "release-checks"}
SHA = re.compile(r"[0-9a-f]{40}\Z")


class StepFailure(RuntimeError):
    def __init__(self, step):
        self.step = step
        super().__init__("local release failed at " + step)


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def validate(deployment, run, branch, now):
    payload = deployment.get("payload")
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("unsupported request")
    if deployment.get("environment") != ENVIRONMENT or deployment.get("creator", {}).get("login") != "github-actions[bot]":
        raise ValueError("untrusted request origin")
    sha = deployment.get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or deployment.get("ref") != sha:
        raise ValueError("invalid commit binding")
    if payload.get("operation") not in ("publish", "rollback"):
        raise ValueError("invalid operation")
    if type(payload.get("run_id")) is not int or type(payload.get("attempt")) is not int:
        raise ValueError("invalid workflow identity")
    if payload["run_id"] != run.get("id") or payload["attempt"] != run.get("run_attempt"):
        raise ValueError("workflow identity mismatch")
    if payload.get("actor") != OWNER or run.get("actor", {}).get("login") != OWNER:
        raise ValueError("unapproved actor")
    if (run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main" or
            run.get("head_sha") != sha or run.get("status") != "in_progress" or
            run.get("path") != ".github/workflows/test-site.yml"):
        raise ValueError("workflow is cancelled, stale or unrelated")
    if branch.get("commit", {}).get("sha") != sha or branch.get("protected") is not True:
        raise ValueError("main changed since request")
    try:
        expires = timestamp(payload["expires_at"])
        current = timestamp(now)
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("invalid expiry") from error
    if current >= expires or (expires - current).total_seconds() > 7200:
        raise ValueError("request expired or excessive lifetime")
    return payload["operation"]


def require_checks(response, sha):
    runs = response.get("check_runs", [])
    for name in CHECKS:
        matches = [run for run in runs if run.get("name") == name and run.get("head_sha") == sha]
        newest = max(matches, key=lambda run: run.get("id", 0), default=None)
        if newest is None or newest.get("conclusion") != "success":
            raise ValueError("required check missing or failed: " + name)


class GitHub:
    def __init__(self, token):
        self.token = token

    def call(self, route, data=None):
        if not route.startswith("/"):
            raise ValueError("invalid API route")
        request = urllib.request.Request(
            BASE + route,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "yuling-local-release-bridge",
                     "Content-Type": "application/json"},
            method="POST" if data is not None else "GET")
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)


def checked_request(api, deployment):
    payload = deployment["payload"]
    run = api.call(f"/actions/runs/{payload['run_id']}")
    branch = api.call("/branches/main")
    operation = validate(deployment, run, branch, datetime.now(timezone.utc).isoformat())
    checks = api.call(f"/commits/{deployment['sha']}/check-runs?per_page=100")
    require_checks(checks, deployment["sha"])
    statuses = api.call(f"/deployments/{deployment['id']}/statuses?per_page=2")
    if not statuses or statuses[0].get("state") not in ("pending", "in_progress"):
        raise ValueError("request already completed or missing pending state")
    return operation


def status(api, deployment_id, state, description):
    # Fixed descriptions only. Never put server responses or secrets on GitHub.
    if state not in ("in_progress", "success", "failure"):
        raise ValueError("invalid result")
    api.call(f"/deployments/{deployment_id}/statuses",
             {"state": state, "description": description[:140], "auto_inactive": False})


def run(*command, env=None):
    subprocess.run([str(arg) for arg in command], check=True, env=env)


def build_and_transfer(api, deployment, operation, config):
    sha = deployment["sha"]
    step = "checkout"
    try:
        with tempfile.TemporaryDirectory(prefix="yuling-local-release-") as directory:
            root = Path(directory)
            checkout = root / "app"
            bundle_dir = root / "output"
            if operation == "publish":
                run("git", "clone", "--filter=blob:none", "--no-checkout",
                    f"https://github.com/{OWNER}/{REPO}.git", checkout)
                run("git", "-C", checkout, "fetch", "origin", sha)
                run("git", "-C", checkout, "checkout", "--detach", sha)
                actual = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
                if actual != sha or subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain"]).strip():
                    raise ValueError("checkout is not the approved clean commit")
                clean_env = {key: value for key, value in os.environ.items()
                             if key not in ("GH_DEPLOY_TOKEN", "DEPLOY_SSH_KEY", "SSH_KNOWN_HOSTS")}
                clean_env.update({"GITHUB_SHA": sha, "GITHUB_REF": "refs/heads/main",
                                  "GITHUB_RUN_ID": str(deployment["payload"]["run_id"]),
                                  "GITHUB_RUN_ATTEMPT": str(deployment["payload"]["attempt"])})
                step = "pinned_image_build"
                run(sys.executable, checkout / "deploy/test/build-image.py", "--output", bundle_dir, env=clean_env)
                step = "image_visual_checks"
                run(sys.executable, checkout / "deploy/test/verify-image.py", "--build-output", bundle_dir, env=clean_env)
                step = "bundle_digest"
                bundle = bundle_dir / "bundle.tar"
                expected = (bundle_dir / "bundle.sha256").read_text().split()[0]
                with bundle.open("rb") as source:
                    actual = hashlib.file_digest(source, "sha256").hexdigest()
                if actual != expected:
                    raise ValueError("verified bundle checksum changed")
            step = "request_recheck"
            if checked_request(api, deployment) != operation:
                raise ValueError("request changed before server operation")
            deploy_env = {key: value for key, value in os.environ.items()
                          if key != "GH_DEPLOY_TOKEN"}
            deploy_env.update({"GITHUB_SHA": sha, "GITHUB_REF": "refs/heads/main",
                               "DEPLOY_HOST": config["host"],
                               "DEPLOY_SSH_KEY": secret(Path(config["ssh_key"])),
                               "SSH_KNOWN_HOSTS": secret(Path(config["known_hosts"]))})
            client = checkout / "deploy/test/ssh-client.py" if operation == "publish" else Path(config["trusted_client"])
            if operation == "publish":
                step = "restricted_upload"
                run(sys.executable, client, "publish", "--bundle", bundle, "--stage", "upload", env=deploy_env)
                step = "post_upload_recheck"
                checked_request(api, deployment)
                step = "server_activation"
                run(sys.executable, client, "publish", "--bundle", bundle, "--stage", "activate", env=deploy_env)
            else:
                step = "restricted_rollback"
                run(sys.executable, client, "rollback", env=deploy_env)
    except Exception as error:
        raise StepFailure(step) from error


def secret(path):
    path = path.resolve()
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("credential file must exist with mode 0600: " + path.name)
    value = path.read_text().strip()
    if not value:
        raise ValueError("empty credential file: " + path.name)
    return value


def handle(api, deployment, config, state_dir):
    identity = deployment["id"]
    record = state_dir / str(identity)
    try:
        with record.open("x") as stream:
            stream.write(str(deployment["sha"]) + "\n")
    except FileExistsError:
        return
    try:
        operation = checked_request(api, deployment)
        status(api, identity, "in_progress", "Local workstation accepted request")
        build_and_transfer(api, deployment, operation, config)
        status(api, identity, "success", "Restricted server operation completed")
        print(f"Request {identity}: {operation} completed", flush=True)
    except Exception as error:
        # Do not publish exception text; it can contain subprocess or credential detail.
        try:
            status(api, identity, "failure", "Local release stopped; inspect workstation log")
        except Exception:
            pass
        print(f"Request {identity}: failed at {getattr(error, 'step', 'request_validation')}", flush=True)
        raise


def poll_once(api, config, state_dir):
    deployments = api.call("/deployments?environment=" + ENVIRONMENT + "&per_page=30")
    for deployment in reversed(deployments):
        if not isinstance(deployment.get("payload"), dict):
            continue
        statuses = api.call(f"/deployments/{deployment['id']}/statuses?per_page=1")
        if statuses and statuses[0].get("state") == "pending":
            handle(api, deployment, config, state_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config_path = args.config.resolve()
    if config_path.stat().st_mode & 0o077:
        raise ValueError("configuration must have mode 0600")
    config = json.loads(config_path.read_text())
    for field in ("token_file", "ssh_key", "known_hosts", "host", "trusted_client", "state_dir"):
        if not config.get(field):
            raise ValueError("missing local configuration: " + field)
    if config["host"] != "115.159.143.24":
        raise ValueError("unexpected release host")
    state_dir = Path(config["state_dir"]).resolve()
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state_dir.stat().st_mode & 0o077:
        raise ValueError("state directory must have mode 0700")
    api = GitHub(secret(Path(config["token_file"])))
    while True:
        try:
            poll_once(api, config, state_dir)
        except (urllib.error.URLError, OSError, ValueError) as error:
            print("Relay stopped this poll: " + type(error).__name__, flush=True)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
