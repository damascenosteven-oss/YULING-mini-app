"""Build the pinned test image on a workstation/CI, never on the production host."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sha_file_is_regular(path):
    return not path.is_symlink() and path.is_file() and stat.S_ISREG(path.stat().st_mode)


def fetch_runtime(item, temporary, name):
    started = time.monotonic()
    progressed = started
    with urllib.request.urlopen(item["url"], timeout=120) as source, temporary.open("xb") as dest:
        while True:
            data = source.read(64 * 1024)
            now = time.monotonic()
            if now - started > 600:
                raise TimeoutError("Runtime download deadline exceeded: " + name)
            if now - progressed > 120:
                raise TimeoutError("Runtime download stalled: " + name)
            if not data:
                break
            dest.write(data)
            progressed = now
    if sha(temporary) != item["sha256"]:
        raise RuntimeError("Runtime download checksum failed: " + name)


def prepare_downloads(target, lock, runtime_cache=None, offline=False, seed_dir=None):
    downloads = target / "runtime-downloads"
    if downloads.is_symlink():
        raise RuntimeError("Unsafe runtime output directory")
    downloads.mkdir(parents=True, exist_ok=True)
    if offline and runtime_cache is None:
        raise RuntimeError("Offline runtime build requires a cache")
    if seed_dir is not None:
        seed_dir = Path(seed_dir)
        if offline or runtime_cache is None or seed_dir.is_symlink():
            raise RuntimeError("Runtime seed requires a warm cache")
        seed_dir = seed_dir.resolve()
        if seed_dir.is_relative_to(HERE) or not seed_dir.is_dir():
            raise RuntimeError("Runtime seed must be an external directory")
    if runtime_cache is not None:
        runtime_cache = Path(runtime_cache)
        if runtime_cache.is_symlink():
            raise RuntimeError("Runtime cache must be outside the repository")
        runtime_cache = runtime_cache.resolve()
        if runtime_cache.is_relative_to(HERE):
            raise RuntimeError("Runtime cache must be outside the repository")
        runtime_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and runtime_cache.stat().st_mode & 0o077:
            raise RuntimeError("Runtime cache directory must have mode 0700")
        lock_file = runtime_cache / ".lock"
        try:
            descriptor = os.open(lock_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise RuntimeError("Runtime cache is already in use") from error
        os.close(descriptor)
        try:
            for name, item in lock["downloads"].items():
                if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
                    raise RuntimeError("Invalid runtime filename")
                expected = item["sha256"]
                if not re.fullmatch(r"[0-9a-f]{64}", expected):
                    raise RuntimeError("Invalid runtime checksum")
                cached = runtime_cache / (name + "-" + expected)
                if cached.exists() or cached.is_symlink():
                    if not sha_file_is_regular(cached) or sha(cached) != expected:
                        raise RuntimeError("Cached runtime checksum failed: " + name)
                elif offline:
                    raise RuntimeError("Pinned runtime cache missing: " + name)
                else:
                    temporary = cached.with_name(cached.name + ".partial")
                    if temporary.exists() or temporary.is_symlink():
                        raise RuntimeError("Incomplete runtime download present: " + name)
                    if seed_dir is not None:
                        seed_file = seed_dir / name
                        if not sha_file_is_regular(seed_file) or sha(seed_file) != expected:
                            raise RuntimeError("Runtime seed checksum failed: " + name)
                        try:
                            with seed_file.open("rb") as source, temporary.open("xb") as dest:
                                shutil.copyfileobj(source, dest)
                            if sha(temporary) != expected:
                                raise RuntimeError("Runtime seed checksum changed: " + name)
                            os.replace(temporary, cached)
                        finally:
                            temporary.unlink(missing_ok=True)
                    else:
                        for attempt in range(3):
                            try:
                                fetch_runtime(item, temporary, name)
                                os.replace(temporary, cached)
                                break
                            except (OSError, urllib.error.URLError, RuntimeError):
                                temporary.unlink(missing_ok=True)
                                if attempt == 2:
                                    raise RuntimeError("Runtime download failed after three attempts: " + name) from None
                                time.sleep((2, 5)[attempt])
                output_file = downloads / name
                if output_file.is_symlink():
                    raise RuntimeError("Unsafe runtime output file")
                shutil.copyfile(cached, output_file)
                if sha(output_file) != expected:
                    raise RuntimeError("Runtime output checksum failed: " + name)
        finally:
            lock_file.unlink()
        return downloads
    for name, item in lock["downloads"].items():
        file = downloads / name
        if not file.exists():
            temporary = file.with_suffix(file.suffix + ".partial")
            try:
                with urllib.request.urlopen(item["url"], timeout=120) as source, temporary.open("wb") as dest:
                    shutil.copyfileobj(source, dest)
                if sha(temporary) != item["sha256"]:
                    raise RuntimeError("Runtime download checksum failed: " + name)
                os.replace(temporary, file)
            finally:
                temporary.unlink(missing_ok=True)
        if sha(file) != item["sha256"]:
            raise RuntimeError("Cached runtime checksum failed: " + name)
    return downloads


def prepare(target, engine, lock, runtime_cache=None, offline=False, seed_dir=None):
    downloads = prepare_downloads(target, lock, runtime_cache, offline, seed_dir)
    if engine is None:
        engine = target / "engine-git"
        if not engine.exists():
            run("git", "clone", "--filter=blob:none", "--no-checkout",
                "https://github.com/YuLing-Ai-Tech/yuling-ai-ppt.git", engine)
        run("git", "-C", engine, "fetch", "origin", lock["engine_sha"])
    if output("git", "-C", engine, "rev-parse", lock["engine_sha"] + "^{commit}") != lock["engine_sha"]:
        raise RuntimeError("Engine source mismatch")
    archive = target / "engine.tar"
    run("git", "-C", engine, "archive", "--format=tar", "-o", archive, lock["engine_sha"])
    extracted = target / "engine"
    if extracted.exists():
        if not extracted.resolve().is_relative_to(target.resolve()):
            raise RuntimeError("Unsafe engine context")
        shutil.rmtree(extracted)
    extracted.mkdir()
    with tarfile.open(archive) as stream:
        stream.extractall(extracted, filter="data")
    return downloads, extracted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "0"))
    parser.add_argument("--attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--runtime-cache", type=Path)
    parser.add_argument("--runtime-offline", action="store_true")
    parser.add_argument("--runtime-seed-dir", type=Path)
    args = parser.parse_args()
    target = args.output.resolve()
    if target.is_relative_to(HERE):
        raise RuntimeError("Build evidence must be outside the application repository")
    target.mkdir(parents=True, exist_ok=True)
    lock = json.loads((HERE / "deploy/test/runtime-lock.json").read_text())
    app_sha = output("git", "-C", HERE, "rev-parse", "HEAD")
    dirty = output("git", "-C", HERE, "status", "--porcelain")
    if dirty and not args.development:
        raise RuntimeError("Release builds require a clean committed checkout")
    if not re.fullmatch(r"[0-9]{1,20}", args.run_id) or not re.fullmatch(r"[0-9]{1,3}", args.attempt):
        raise RuntimeError("Invalid workflow identity")
    release = app_sha[:12] + "-" + args.run_id + "-" + args.attempt
    tag = "yuling-ppt-test:" + release
    downloads, engine = prepare(target, args.engine.resolve() if args.engine else None, lock,
                                args.runtime_cache, args.runtime_offline, args.runtime_seed_dir)
    if args.prepare_only:
        print("Pinned runtime and engine contexts verified")
        return
    run("docker", "build", "--pull=false", "--build-context", "engine=" + str(engine),
        "--build-context", "runtime_downloads=" + str(downloads), "--build-arg", "APP_SHA=" + app_sha,
        "--build-arg", "SOURCE_DIRTY=" + ("true" if dirty or args.development else "false"),
        "-f", HERE / "deploy/test/Dockerfile", "-t", tag, HERE)
    image_id = output("docker", "image", "inspect", "--format", "{{.Id}}", tag)
    (target / "image.json").write_text(json.dumps({"tag": tag, "image_id": image_id,
        "app_sha": app_sha, "release": release, "development": args.development}, indent=2))
    if args.development:
        print("Development image built; no publishable bundle created")
        return
    image = target / "image.tar.gz"
    with image.open("wb") as file, gzip.GzipFile(fileobj=file, mode="wb", mtime=0) as compressed:
        process = subprocess.Popen(["docker", "image", "save", tag], stdout=subprocess.PIPE)
        try:
            shutil.copyfileobj(process.stdout, compressed, 1024 * 1024)
        finally:
            process.stdout.close()
        if process.wait() != 0:
            raise RuntimeError("Docker image export failed")
    # The portable identity is the configuration digest, not the store-specific
    # Docker inspect Id (which can be an OCI index with the containerd store).
    with tarfile.open(image, "r:gz") as archive:
        entries = json.load(archive.extractfile("manifest.json"))
        if len(entries) != 1 or entries[0]["RepoTags"] != [tag]:
            raise RuntimeError("Export must contain exactly the selected image")
        member = archive.getmember(entries[0]["Config"])
        if member.size > 524288 or not member.isfile():
            raise RuntimeError("Invalid exported image configuration")
        with archive.extractfile(member) as config:
            image_id = "sha256:" + hashlib.file_digest(config, "sha256").hexdigest()
    manifest = {"schema": 1, "application": "yuling-ppt-test", "release": release,
                "app_sha": app_sha, "engine_sha": lock["engine_sha"],
                "image_id": image_id, "image_tag": tag, "image_sha256": sha(image)}
    (target / "release.json").write_text(json.dumps(manifest, indent=2))
    bundle = target / "bundle.tar"
    with tarfile.open(bundle, "w") as archive:
        archive.add(target / "release.json", arcname="release.json")
        archive.add(image, arcname="image.tar.gz")
    (target / "bundle.sha256").write_text(sha(bundle) + "  bundle.tar\n")
    print("Bundle created for " + release)


if __name__ == "__main__":
    main()
