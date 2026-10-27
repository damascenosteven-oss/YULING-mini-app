"""Create a short-lived GitHub Deployment request and wait for workstation result."""
from datetime import datetime, timedelta, timezone
import json
import os
import re
import signal
import time
import urllib.request

OWNER = "damascenosteven-oss"
REPO = "YULING-mini-app"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
ENVIRONMENT = "ppt-test-local-relay"
deployment_id = None
api = None


def identity(env):
    if env.get("GITHUB_REPOSITORY") != f"{OWNER}/{REPO}" or env.get("GITHUB_ACTOR") != OWNER:
        raise ValueError("only the repository owner may request test releases")
    if env.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("test releases require main")
    sha = env.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid main commit")
    if env.get("OPERATION") not in ("publish", "rollback"):
        raise ValueError("invalid release operation")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not re.fullmatch(r"[1-9][0-9]{0,19}", env.get(key, "")):
            raise ValueError("invalid workflow run identity")
    return {"schema": 1, "operation": env["OPERATION"],
            "run_id": int(env["GITHUB_RUN_ID"]),
            "attempt": int(env["GITHUB_RUN_ATTEMPT"]),
            "actor": env["GITHUB_ACTOR"], "sha": sha}


class GitHub:
    def __init__(self, token):
        self.token = token

    def call(self, route, data=None):
        req = urllib.request.Request(
            BASE + route, data=None if data is None else json.dumps(data).encode(),
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "yuling-phone-release-request",
                     "Content-Type": "application/json"},
            method="POST" if data is not None else "GET")
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)


def fail_on_signal(signum, frame):
    if api is not None and deployment_id is not None:
        try:
            api.call(f"/deployments/{deployment_id}/statuses",
                     {"state": "failure", "description": "Phone workflow cancelled",
                      "auto_inactive": False})
        except Exception:
            pass
    raise SystemExit(128 + signum)


def main():
    global deployment_id, api
    info = identity(os.environ)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("missing workflow token")
    api = GitHub(token)
    expires = datetime.now(timezone.utc) + timedelta(minutes=110)
    payload = {key: value for key, value in info.items() if key != "sha"}
    payload["expires_at"] = expires.isoformat().replace("+00:00", "Z")
    deployment = api.call("/deployments", {
        "ref": info["sha"], "task": "deploy", "auto_merge": False,
        "required_contexts": [], "environment": ENVIRONMENT,
        "transient_environment": True, "production_environment": False,
        "description": "Owner-triggered workstation test release request",
        "payload": payload})
    deployment_id = deployment["id"]
    if deployment.get("sha") != info["sha"]:
        raise ValueError("GitHub returned a different deployment commit")
    api.call(f"/deployments/{deployment_id}/statuses", {
        "state": "pending", "description": "Waiting for trusted workstation",
        "auto_inactive": False})
    signal.signal(signal.SIGTERM, fail_on_signal)
    signal.signal(signal.SIGINT, fail_on_signal)
    print("Request created: deployment", deployment_id, "commit", info["sha"], flush=True)
    while datetime.now(timezone.utc) < expires:
        latest = api.call(f"/deployments/{deployment_id}/statuses?per_page=1")
        if latest:
            state = latest[0].get("state")
            if state == "success":
                print("Workstation reported successful server operation", flush=True)
                return
            if state in ("failure", "error"):
                raise RuntimeError("Workstation reported failure; inspect local relay log")
        time.sleep(15)
    api.call(f"/deployments/{deployment_id}/statuses", {
        "state": "failure", "description": "Workstation did not complete before expiry",
        "auto_inactive": False})
    raise RuntimeError("Workstation offline or release exceeded request lifetime")


if __name__ == "__main__":
    main()
