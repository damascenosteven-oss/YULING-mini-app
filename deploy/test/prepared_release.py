"""Immutable workstation release packages. No network or Docker side effects."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import uuid

from release_audit import check_report

ENGINE_SHA = "be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192"
TTL = timedelta(hours=24)
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
INPUTS = ("package_sha256", "lock_sha256", "runtime_sha256")
REQUIRED = {"bundle.tar", "bundle.sha256", "release.json", "ssh-client.py", "inputs.json", "verification.json"}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def now_utc():
    return datetime.now(timezone.utc)


def timestamp(value):
    require(isinstance(value, str), "invalid_audit_time")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(date.tzinfo is not None, "invalid_audit_time")
    return date


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular(path):
    return not path.is_symlink() and path.is_file() and stat.S_ISREG(path.stat().st_mode)


def safe_tree(directory):
    require(directory.exists() or directory.is_symlink(), "prepare_required_missing_package")
    require(not directory.is_symlink() and directory.is_dir(), "unsafe_package_directory")
    for path in directory.rglob("*"):
        require(not path.is_symlink() and (path.is_dir() or regular(path)), "unsafe_package_file")


def read_json(path):
    require(regular(path), "prepared_evidence_missing")
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        raise ValueError("invalid_package_json") from None
    require(isinstance(data, dict), "invalid_package_json")
    return data


def root_directory(state):
    state = Path(state)
    require(not state.is_symlink(), "unsafe_prepared_state")
    state = state.resolve()
    require(not state.is_relative_to(Path(__file__).resolve().parents[2]), "prepared_state_must_be_external")
    root = state / "prepared-releases"
    require(not root.is_symlink(), "unsafe_prepared_root")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(os.name != "posix" or root.stat().st_mode & 0o077 == 0, "prepared_root_permissions")
    return root


@contextmanager
def locked(root):
    lock = root / ".operation.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("prepared_package_busy") from None
    os.close(descriptor)
    try:
        yield
    finally:
        lock.unlink()


def evidence(directory, sha, generation, now, fresh):
    require(SHA.fullmatch(sha) is not None, "invalid_package_source")
    manifest = read_json(directory / "release.json")
    require(manifest.get("app_sha") == sha and manifest.get("engine_sha") == ENGINE_SHA,
            "prepared_source_mismatch")
    require(str(manifest.get("release", "")).startswith(sha[:12] + "-"), "prepared_release_mismatch")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", str(manifest.get("image_id", ""))) is not None,
            "prepared_image_mismatch")
    verification = read_json(directory / "verification.json")
    expected = {"schema": 1, "app_sha": sha, "engine_sha": ENGINE_SHA, "image_id": manifest["image_id"],
                "source_dirty": False, "pages": 12, "captures": 2, "differences": 0}
    require(verification == expected and type(verification.get("source_dirty")) is bool
            and all(type(verification.get(k)) is int for k in ("schema", "pages", "captures", "differences")),
            "prepared_verification_mismatch")
    inputs = read_json(directory / "inputs.json")
    require(set(inputs) == set(INPUTS) and all(isinstance(v, str) and DIGEST.fullmatch(v) for v in inputs.values()),
            "prepared_inputs_invalid")
    require(isinstance(generation, str) and re.fullmatch(r"[a-z0-9-]+", generation) is not None,
            "prepared_audit_path_invalid")
    audits = directory / "audits" / generation
    metadata = read_json(audits / "audit.json")
    require(all(metadata.get(k) == inputs[k] for k in INPUTS), "prepared_audit_source_mismatch")
    date = timestamp(metadata.get("audited_at"))
    require(date <= now, "prepared_audit_future")
    if fresh:
        require(now < date + TTL, "prepare_required_audit_expired")
    for name in ("audit-full.json", "audit-prod.json"):
        check_report(read_json(audits / name))
    checksum = (directory / "bundle.sha256").read_text().split()
    require(len(checksum) == 2 and checksum[1] == "bundle.tar" and checksum[0] == digest(directory / "bundle.tar"),
            "prepared_bundle_checksum")
    return {"manifest": manifest, "inputs": inputs, "expires_at": (date + TTL).isoformat()}


def validate(directory, sha, *, now=None, fresh=True):
    now = now or now_utc()
    safe_tree(directory)
    receipt = read_json(directory / "receipt.json")
    require(type(receipt.get("schema")) is int and receipt["schema"] == 1 and receipt.get("app_sha") == sha,
            "prepared_receipt_mismatch")
    files = receipt.get("files")
    require(isinstance(files, dict) and REQUIRED.issubset(files), "prepared_receipt_incomplete")
    generation = receipt.get("audit_generation")
    audit_files = {f"audits/{generation}/{name}" for name in ("audit.json", "audit-full.json", "audit-prod.json")}
    require(audit_files.issubset(files), "prepared_audit_not_bound")
    for name, checksum in files.items():
        path = PurePosixPath(name)
        require(not path.is_absolute() and ".." not in path.parts and str(path) == name and "\\" not in name,
                "unsafe_receipt_path")
        file = directory / name
        require(isinstance(checksum, str) and DIGEST.fullmatch(checksum) is not None
                and regular(file) and digest(file) == checksum, "prepared_file_integrity")
    return evidence(directory, sha, generation, now, fresh)


def seal(directory, sha, generation, *, now=None):
    safe_tree(directory)
    result = evidence(directory, sha, generation, now or now_utc(), True)
    files = {p.relative_to(directory).as_posix(): digest(p) for p in directory.rglob("*")
             if regular(p) and p.name not in ("receipt.json", ".receipt.tmp")}
    require(REQUIRED.issubset(files), "prepared_receipt_incomplete")
    receipt = {"schema": 1, "app_sha": sha, "audit_generation": generation, "files": files}
    temporary = directory / ".receipt.tmp"
    require(not temporary.exists() and not temporary.is_symlink(), "incomplete_package_receipt")
    with temporary.open("x") as file:
        json.dump(receipt, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, directory / "receipt.json")
    return result


def refresh(directory, audits, sha, *, now=None):
    # A fresh audit must never bless damaged existing package bytes or evidence.
    validate(directory, sha, now=now, fresh=False)
    safe_tree(audits)
    generation = uuid.uuid4().hex
    target = directory / "audits" / generation
    try:
        shutil.copytree(audits, target)
        return seal(directory, sha, generation, now=now)
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise


def accept(root, build, checkout, sha):
    import tempfile
    stage = Path(tempfile.mkdtemp(prefix=".partial-", dir=root))
    try:
        for name in ("bundle.tar", "bundle.sha256", "release.json", "image.json", "verification.json", "image-memory.txt"):
            require(regular(build / name), "prepared_build_evidence_missing")
            shutil.copyfile(build / name, stage / name)
        safe_tree(build / "packaged-candidate")
        safe_tree(build / "fresh-audits")
        shutil.copytree(build / "packaged-candidate", stage / "packaged-candidate")
        shutil.copyfile(checkout / "deploy/test/ssh-client.py", stage / "ssh-client.py")
        inputs = {key: digest(checkout / name) for key, name in zip(INPUTS,
                  ("package.json", "pnpm-lock.yaml", "deploy/test/runtime-lock.json"))}
        (stage / "inputs.json").write_text(json.dumps(inputs))
        audits = stage / "audits" / "initial"
        audits.mkdir(parents=True)
        for name in ("audit.json", "audit-full.json", "audit-prod.json"):
            shutil.copyfile(build / "fresh-audits" / name, audits / name)
        result = seal(stage, sha, "initial")
        require(not (root / sha).exists() and not (root / sha).is_symlink(), "prepared_destination_exists")
        os.replace(stage, root / sha)
        return result
    finally:
        if stage.exists(): shutil.rmtree(stage)


def retain_two(root, current):
    # Called only under the operation lock. No Docker/cache/worktree cleanup.
    candidates = []
    for path in root.iterdir():
        if path.name == current or not SHA.fullmatch(path.name):
            continue
        try:
            validate(path, path.name, fresh=False)
        except (ValueError, OSError):
            print("Retention skipped an unverified package directory", flush=True)
            continue
        candidates.append(path)
    candidates.sort(key=lambda p: (p / "receipt.json").stat().st_mtime_ns, reverse=True)
    for path in candidates[1:]:
        require(path.parent == root and not path.is_symlink(), "unsafe_retention_path")
        shutil.rmtree(path)
