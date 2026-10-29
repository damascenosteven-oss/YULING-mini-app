"""Create a short-lived GitHub Deployment request and wait for workstation result."""
from datetime import datetime, timedelta, timezone
import json
import os
import re
import signal
import html
import time
import urllib.request

OWNER = "damascenosteven-oss"
REPO = "YULING-mini-app"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
ENVIRONMENT = "ppt-test-local-relay"
PREPARE_ENVIRONMENT = "ppt-test-local-prepare"
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
    if env.get("OPERATION") not in ("prepare", "publish", "rollback"):
        raise ValueError("invalid release operation")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not re.fullmatch(r"[1-9][0-9]{0,19}", env.get(key, "")):
            raise ValueError("invalid workflow run identity")
    return {"schema": 2, "operation": env["OPERATION"],
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


def summary(info, state, description):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    labels = {"prepare": "准备版本", "publish": "发布版本", "rollback": "回滚上一版"}
    next_step = ("准备成功后可运行 main → publish；服务器尚未切换。" if info["operation"] == "prepare"
                 else "发布成功后仍需打开测试站并实际生成普通 PPT 验收。")
    with open(path, "a", encoding="utf-8") as file:
        file.write("## " + labels[info["operation"]] + "\n\n"
                   + "提交：`" + info["sha"] + "`\n\n"
                   + "结果：" + html.escape(state) + "\n\n"
                   + html.escape(description[:400]) + "\n\n" + next_step + "\n")


def run_request():
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
        "ref": info["sha"], "task": "prepare" if info["operation"] == "prepare" else "deploy", "auto_merge": False,
        "required_contexts": [], "environment": PREPARE_ENVIRONMENT if info["operation"] == "prepare" else ENVIRONMENT,
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
    last_phase = None
    while datetime.now(timezone.utc) < expires:
        latest = api.call(f"/deployments/{deployment_id}/statuses?per_page=1")
        if latest:
            state = latest[0].get("state")
            description = latest[0].get("description", "")
            if description != last_phase:
                print("Progress: " + description[:200], flush=True)
                last_phase = description
            if state == "success":
                summary(info, "success", description)
                print("Workstation reported successful " + info["operation"], flush=True)
                return
            if state in ("failure", "error"):
                raise RuntimeError("Workstation reported failure: " + description[:200])
        time.sleep(15)
    api.call(f"/deployments/{deployment_id}/statuses", {
        "state": "failure", "description": "Workstation did not complete before expiry",
        "auto_inactive": False})
    raise RuntimeError("Workstation offline or release exceeded request lifetime")


def main():
    info = identity(os.environ)
    try:
        run_request()
    except (Exception, SystemExit) as error:
        summary(info, "failure", str(error) if isinstance(error, RuntimeError) else "Request stopped; inspect workflow stage")
        raise


if __name__ == "__main__":
    main()
