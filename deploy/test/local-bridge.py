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
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import prepared_release as prepared

OWNER = "damascenosteven-oss"
REPO = "YULING-mini-app"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
ENVIRONMENT = "ppt-test-local-relay"
PREPARE_ENVIRONMENT = "ppt-test-local-prepare"
# engineering-guard is a PR-only check enforced by branch protection. The
# merged main SHA has its own app and release checks but no PR check run.
CHECKS = {"app-checks", "release-checks"}
SHA = re.compile(r"[0-9a-f]{40}\Z")
APP_SOURCE = f"https://github.com/{OWNER}/{REPO}.git"
ENGINE_SOURCE = "https://github.com/YuLing-Ai-Tech/yuling-ai-ppt.git"
ENGINE_SHA = "be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192"


class StepFailure(RuntimeError):
    def __init__(self, step, code="operation_failed"):
        self.step = step
        self.code = code
        super().__init__("local release failed at " + step)


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def validate(deployment, run, branch, now):
    payload = deployment.get("payload")
    if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload["schema"] != 2:
        raise ValueError("unsupported request")
    environment = PREPARE_ENVIRONMENT if payload.get("operation") == "prepare" else ENVIRONMENT
    if deployment.get("environment") != environment or deployment.get("creator", {}).get("login") != "github-actions[bot]":
        raise ValueError("untrusted request origin")
    sha = deployment.get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or deployment.get("ref") != sha:
        raise ValueError("invalid commit binding")
    if payload.get("operation") not in ("prepare", "publish", "rollback"):
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


def git_value(*args):
    return subprocess.check_output(["git", *map(str, args)], text=True,
                                   stderr=subprocess.DEVNULL).strip()


def fetch_source(cache, sha):
    subprocess.run(["git", "-C", str(cache), "fetch", "--no-tags", "origin", sha],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                   timeout=90)


def verify_source(cache, source, sha):
    if cache.is_symlink() or not cache.is_dir():
        raise ValueError("source cache is not a regular repository")
    try:
        if (git_value("-C", cache, "rev-parse", "--is-bare-repository") != "true" or
                git_value("-C", cache, "remote", "get-url", "origin") != source):
            raise ValueError("source cache origin or shape mismatch")
    except subprocess.CalledProcessError as error:
        raise ValueError("source cache metadata invalid") from error
    for setting in ("remote.origin.promisor", "extensions.partialClone"):
        if subprocess.run(["git", "-C", str(cache), "config", "--get", setting],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise ValueError("partial source cache is not accepted")
    try:
        subprocess.run(["git", "-C", str(cache), "fsck", "--full", "--no-reflogs"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError("source cache object integrity failed") from error
    try:
        present = git_value("-C", cache, "rev-parse", "--verify", sha + "^{commit}") == sha
    except subprocess.CalledProcessError:
        return False
    if not present:
        return False
    try:
        subprocess.run(["git", "-C", str(cache), "fsck", "--full", "--no-reflogs", sha],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=90)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError("requested source commit is incomplete") from error
    return True


def ensure_cached_source(cache, source, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("invalid source commit")
    cache.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if cache.parent.is_symlink() or (os.name == "posix" and cache.parent.stat().st_mode & 0o077):
        raise ValueError("source cache directory must have mode 0700")
    lock = cache.with_name(cache.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ValueError("source cache is already in use") from error
    os.close(descriptor)
    temporary = None
    try:
        if cache.exists() or cache.is_symlink():
            if verify_source(cache, source, sha):
                subprocess.run(["git", "-C", str(cache), "update-ref", "refs/heads/pinned", sha], check=True)
                print("Verified source cache hit: " + cache.name, flush=True)
                return cache
            target = cache
        else:
            temporary = Path(tempfile.mkdtemp(prefix="source-", dir=cache.parent))
            subprocess.run(["git", "init", "--bare", "-q", str(temporary)], check=True)
            subprocess.run(["git", "-C", str(temporary), "remote", "add", "origin", source], check=True)
            target = temporary
        for attempt in range(3):
            try:
                print(f"Source fetch {cache.name}: attempt {attempt + 1}/3", flush=True)
                fetch_source(target, sha)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
                print(f"Source fetch {cache.name}: {type(error).__name__}", flush=True)
                if attempt == 2:
                    raise
                time.sleep((2, 5)[attempt])
        if not verify_source(target, source, sha):
            raise ValueError("fetched source commit is missing or damaged")
        subprocess.run(["git", "-C", str(target), "update-ref", "refs/heads/pinned", sha], check=True)
        if temporary is not None:
            os.replace(temporary, cache)
            temporary = None
        return cache
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
        lock.unlink()


def prepare_sources(state_dir, sha, checkout):
    caches = state_dir / "source-cache"
    app = ensure_cached_source(caches / "app.git", APP_SOURCE, sha)
    subprocess.run(["git", "clone", "--no-local", "--no-checkout", "-q",
                    str(app), str(checkout)], check=True, timeout=90)
    subprocess.run(["git", "-C", str(checkout), "checkout", "--detach", "-q", sha],
                   check=True, timeout=90)
    if (git_value("-C", checkout, "rev-parse", "HEAD") != sha or
            git_value("-C", checkout, "status", "--porcelain")):
        raise ValueError("checkout is not the approved clean commit")
    lock = json.loads((checkout / "deploy/test/runtime-lock.json").read_text())
    engine_sha = lock["engine_sha"]
    if engine_sha != ENGINE_SHA:
        raise ValueError("engine lock differs from approved fixed commit")
    engine = ensure_cached_source(caches / "engine.git", ENGINE_SOURCE, engine_sha)
    return engine


def warm_cache(api, state_dir, seed_dir=None):
    branch = api.call("/branches/main")
    sha = branch.get("commit", {}).get("sha")
    if branch.get("protected") is not True or not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("protected main is unavailable")
    require_checks(api.call(f"/commits/{sha}/check-runs?per_page=100"), sha)
    with tempfile.TemporaryDirectory(prefix="yuling-source-warm-") as directory:
        checkout = Path(directory) / "app"
        engine = prepare_sources(state_dir, sha, checkout)
        command = [sys.executable, checkout / "deploy/test/build-image.py", "--output", Path(directory) / "output",
                   "--engine", engine, "--runtime-cache", state_dir / "runtime-cache",
                   "--dependency-cache", state_dir / "dependency-cache", "--prepare-only"]
        if seed_dir is not None:
            command.extend(("--runtime-seed-dir", seed_dir))
        run(*command)
    print("Verified source, pinned runtime and dependency caches ready for main " + sha, flush=True)


def prepare_package(api, deployment, config, root, phase):
    sha = deployment["sha"]
    package = root / sha
    if package.exists() or package.is_symlink():
        info = prepared.validate(package, sha, fresh=False)
        if prepared.now_utc() < prepared.timestamp(info["expires_at"]):
            return prepared.validate(package, sha)
    else:
        info = None
    with tempfile.TemporaryDirectory(prefix="yuling-prepare-") as directory:
        checkout = Path(directory) / "app"
        output = Path(directory) / "output"
        phase("source_preparation")
        engine = prepare_sources(Path(config["state_dir"]), sha, checkout)
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("GH_DEPLOY_TOKEN", "DEPLOY_SSH_KEY", "SSH_KNOWN_HOSTS")}
        environment.update({"GITHUB_SHA": sha, "GITHUB_REF": "refs/heads/main",
                            "GITHUB_RUN_ID": str(deployment["payload"]["run_id"]),
                            "GITHUB_RUN_ATTEMPT": str(deployment["payload"]["attempt"])})
        command = [sys.executable, checkout / "deploy/test/build-image.py", "--output", output,
                   "--runtime-cache", Path(config["state_dir"]) / "runtime-cache"]
        if info is not None:
            phase("audit_refresh")
            run(*command, "--audit-only", "--runtime-offline", env=environment)
            if checked_request(api, deployment) != "prepare":
                raise ValueError("request changed during audit refresh")
            return prepared.refresh(package, output / "fresh-audits", sha)
        phase("package_build_and_audits")
        run(*command, "--engine", engine, "--dependency-cache",
            Path(config["state_dir"]) / "dependency-cache", env=environment)
        phase("image_visual_checks")
        try:
            run(sys.executable, checkout / "deploy/test/verify-image.py", "--build-output", output, env=environment)
        except subprocess.CalledProcessError:
            diagnostic = output / "image-check-error.json"
            if diagnostic.is_file() and not diagnostic.is_symlink() and diagnostic.stat().st_size <= 1024:
                data = json.loads(diagnostic.read_text())
                stages = {"container_start", "runtime_permissions", "readiness", "quick_smoke",
                          "repeatability", "memory_and_evidence"}
                if (set(data) == {"schema", "stage", "code", "exit_code"} and data["schema"] == 1
                        and data["stage"] in stages and type(data["exit_code"]) is int
                        and data["code"] in {"image_permission_denied", "image_check_failed"}):
                    record = Path(config["state_dir"]) / (str(deployment["id"]) + "-image-check-error.json")
                    with record.open("x") as stream:
                        json.dump(data, stream)
                    record.chmod(0o600)
            raise
        if checked_request(api, deployment) != "prepare":
            raise ValueError("request changed during preparation")
        result = prepared.accept(root, output, checkout, sha)
        prepared.retain_two(root, sha)
        return result


def build_and_transfer(api, deployment, operation, config):
    sha = deployment["sha"]
    step = "prepared_package" if operation == "publish" else "preparation" if operation == "prepare" else "request_recheck"
    def phase(value):
        nonlocal step
        step = value
        print(f"Request {deployment['id']}: phase {value}", flush=True)
        status(api, deployment["id"], "in_progress", operation + ": " + value)
    try:
        root = prepared.root_directory(config["state_dir"])
        with prepared.locked(root):
            if operation == "prepare":
                result = prepare_package(api, deployment, config, root, phase)
                if checked_request(api, deployment) != operation:
                    raise ValueError("preparation request changed")
                return result
            if operation == "publish":
                package = root / sha
                prepared.validate(package, sha)
                bundle = package / "bundle.tar"
                client = package / "ssh-client.py"
            else:
                client = Path(config["trusted_client"])
            phase("request_recheck")
            if checked_request(api, deployment) != operation:
                raise ValueError("request changed before server operation")
            deploy_env = {key: value for key, value in os.environ.items() if key != "GH_DEPLOY_TOKEN"}
            deploy_env.update({"GITHUB_SHA": sha, "GITHUB_REF": "refs/heads/main", "DEPLOY_HOST": config["host"],
                               "DEPLOY_SSH_KEY": secret(Path(config["ssh_key"])),
                               "SSH_KNOWN_HOSTS": secret(Path(config["known_hosts"]))})
            if operation == "publish":
                phase("restricted_upload")
                run(sys.executable, client, "publish", "--bundle", bundle, "--stage", "upload", env=deploy_env)
                phase("post_upload_recheck")
                if checked_request(api, deployment) != operation:
                    raise ValueError("request changed after upload")
                prepared.validate(package, sha)  # Includes freshness at activation, not just upload start.
                phase("server_activation")
                run(sys.executable, client, "publish", "--bundle", bundle, "--stage", "activate", env=deploy_env)
            else:
                phase("restricted_rollback")
                run(sys.executable, client, "rollback", env=deploy_env)
    except Exception as error:
        if isinstance(error, subprocess.CalledProcessError) and error.returncode == 4 and step == "package_build_and_audits":
            step = "dependency_audit"
        if isinstance(error, subprocess.CalledProcessError) and step == "image_visual_checks":
            if error.returncode in (5, 6):
                raise StepFailure(step, "image_permission_denied" if error.returncode == 5 else "image_check_failed") from error
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r"[a-z_]{1,80}", str(error)) else "operation_failed"
        raise StepFailure(step, code) from error


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
        result = build_and_transfer(api, deployment, operation, config)
        message = ("Prepared " + deployment["sha"][:12] + "; audits until " + result["expires_at"]
                   if operation == "prepare" else "Restricted server operation completed")
        status(api, identity, "success", message)
        print(f"Request {identity}: {operation} completed", flush=True)
    except Exception as error:
        # Do not publish exception text; it can contain subprocess or credential detail.
        try:
            step = getattr(error, "step", "request_validation")
            code = getattr(error, "code", "operation_failed")
            hint = ("; run prepare" if code.startswith("prepare_required_") else "; inspect workstation package") if step == "prepared_package" else "; inspect workstation log"
            status(api, identity, "failure", "Stopped at " + step + ": " + code
                   + hint)
        except Exception:
            print("Failed to report request status; request stays recorded", flush=True)
        print(f"Request {identity}: failed at {getattr(error, 'step', 'request_validation')}", flush=True)
        raise


def poll_once(api, config, state_dir):
    deployments = []
    for environment in (ENVIRONMENT, PREPARE_ENVIRONMENT):
        deployments.extend(api.call("/deployments?environment=" + environment + "&per_page=30"))
    for deployment in sorted({d["id"]: d for d in deployments}.values(), key=lambda d: d["id"]):
        if not isinstance(deployment.get("payload"), dict):
            continue
        statuses = api.call(f"/deployments/{deployment['id']}/statuses?per_page=1")
        if statuses and statuses[0].get("state") == "pending":
            handle(api, deployment, config, state_dir)


def poll_continuously(api, config, state_dir, once=False):
    while True:
        try:
            poll_once(api, config, state_dir)
        except StepFailure as error:
            print("Request failed at " + error.step + "; relay remains available", flush=True)
            if once:
                raise
        except (urllib.error.URLError, OSError, ValueError) as error:
            print("Relay stopped this poll: " + type(error).__name__, flush=True)
            if once:
                raise
        if once:
            return
        time.sleep(15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--warm-cache", action="store_true")
    parser.add_argument("--runtime-seed-dir", type=Path)
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
    if args.warm_cache:
        warm_cache(api, state_dir, args.runtime_seed_dir)
        return
    if args.runtime_seed_dir is not None:
        raise ValueError("Runtime seed is only accepted with --warm-cache")
    poll_continuously(api, config, state_dir, args.once)


if __name__ == "__main__":
    main()
