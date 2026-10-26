"""Build the pinned test image on a workstation/CI, never on the production host."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(target, engine, lock):
    downloads = target / "runtime-downloads"
    downloads.mkdir(parents=True, exist_ok=True)
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
    downloads, engine = prepare(target, args.engine.resolve() if args.engine else None, lock)
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

