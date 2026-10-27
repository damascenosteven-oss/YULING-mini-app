"""Restricted, root-owned receiver for the PPT test site. Python standard library only."""
import gzip
import hashlib
import io
import json
import os
import ipaddress
import signal
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

ENGINE = "be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192"
APPLICATION = "yuling-ppt-test"
ROOT = Path("/opt/yuling-ppt-test")
CONFIG = Path("/etc/yuling-ppt-test/config.json")
ENV_FILE = Path("/etc/yuling-ppt-test/app.env")
MAX_UPLOAD = 2 * 1024**3
MAX_IMAGE = 4 * 1024**3
MIN_DISK = 8 * 1024**3
RID = re.compile(r"[0-9a-f]{12}-[0-9]{1,20}-[0-9]{1,3}")


class ReleaseError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def valid_release(value):
    require(isinstance(value, str) and RID.fullmatch(value), "Invalid release identifier")
    return value


def digest_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    require(path.stat().st_size <= 65536, "Oversized JSON metadata")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    temporary = path.with_name(path.name + ".new")
    require(not temporary.is_symlink(), "Unsafe metadata path")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)


def members(archive, maximum):
    result = {}
    size = 0
    for index, item in enumerate(archive):
        require(index < 4096, "Archive exceeds entry count limit")
        name = PurePosixPath(item.name)
        require(not name.is_absolute() and ".." not in name.parts and "\\" not in item.name,
                "Unsafe archive path")
        require(item.isfile() or item.isdir(), "Archive links and special files are forbidden")
        require(not item.sparse, "Sparse archive entries are forbidden")
        if item.isdir():
            continue
        require(item.name not in result, "Duplicate archive entry")
        size += item.size
        require(size <= maximum and len(result) < 4096, "Archive exceeds limits")
        result[item.name] = item
    return result


def tar_json(archive, item, maximum=65536):
    require(item.size <= maximum, "Oversized archive metadata")
    with archive.extractfile(item) as stream:
        return json.load(stream)


def normalize_image(source, destination, manifest):
    """Load only a normalized one-image Docker archive, never an arbitrary OCI index."""
    with tarfile.open(source, "r:*") as archive:
        files = members(archive, MAX_IMAGE)
        require("manifest.json" in files, "Docker image manifest missing")
        images = tar_json(archive, files["manifest.json"])
        require(isinstance(images, list) and len(images) == 1, "Exactly one image is required")
        image = images[0]
        require(isinstance(image, dict), "Malformed image manifest")
        require(image.get("RepoTags") == [manifest["image_tag"]], "Image tag mismatch")
        config_name = image.get("Config")
        require(config_name in files, "Image configuration missing")
        require(files[config_name].size <= 524288, "Image configuration too large")
        with archive.extractfile(files[config_name]) as stream:
            config_bytes = stream.read()
        require("sha256:" + hashlib.sha256(config_bytes).hexdigest() == manifest["image_id"],
                "Image identity mismatch")
        configuration = json.loads(config_bytes)
        settings = configuration.get("config", {})
        require(settings.get("User") == "10001:10001", "Image must use the unprivileged runtime user")
        labels = settings.get("Labels", {})
        require(labels.get("org.opencontainers.image.revision") == manifest["app_sha"]
                and labels.get("dev.yuling.engine.revision") == ENGINE
                and labels.get("dev.yuling.application") == APPLICATION, "Image source labels mismatch")
        require(labels.get("dev.yuling.source.dirty") == "false", "Development image is not publishable")
        forbidden = {"DEEPSEEK_API_KEY", "COS_SECRET_ID", "COS_SECRET_KEY",
                     "PPT_SESSION_SECRET", "PPT_INVITE_PASSWORD", "BOCHA_API_KEY"}
        require(not any(value.split("=", 1)[0] in forbidden for value in settings.get("Env", [])),
                "Image must not contain credential environment variables")
        layers = image.get("Layers")
        ids = configuration.get("rootfs", {}).get("diff_ids")
        require(isinstance(layers, list) and isinstance(ids, list) and len(layers) == len(ids),
                "Image layers mismatch")
        normalized = {"Config": "config.json", "RepoTags": [manifest["image_tag"]], "Layers": []}
        total = 0
        with tarfile.open(destination, "w") as output:
            info = tarfile.TarInfo("config.json")
            info.size = len(config_bytes)
            output.addfile(info, io.BytesIO(config_bytes))
            for index, (name, expected) in enumerate(zip(layers, ids)):
                require(name in files and isinstance(expected, str)
                        and re.fullmatch(r"sha256:[0-9a-f]{64}", expected), "Invalid image layer")
                layer_file = destination.with_name("normalizing-layer.tar")
                try:
                    with archive.extractfile(files[name]) as raw:
                        magic = raw.read(2)
                        raw.seek(0)
                        data = gzip.GzipFile(fileobj=raw) if magic == b"\x1f\x8b" else raw
                        hasher = hashlib.sha256()
                        with layer_file.open("wb") as target:
                            while chunk := data.read(1024 * 1024):
                                total += len(chunk)
                                require(total <= MAX_IMAGE, "Expanded image exceeds limit")
                                hasher.update(chunk)
                                target.write(chunk)
                    require("sha256:" + hasher.hexdigest() == expected, "Image layer digest mismatch")
                    output_name = f"layer-{index}.tar"
                    normalized["Layers"].append(output_name)
                    info = tarfile.TarInfo(output_name)
                    info.size = layer_file.stat().st_size
                    with layer_file.open("rb") as layer:
                        output.addfile(info, layer)
                finally:
                    layer_file.unlink(missing_ok=True)
            data = json.dumps([normalized]).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            output.addfile(info, io.BytesIO(data))


def validate_manifest(manifest, release):
    required = {"schema", "application", "release", "app_sha", "engine_sha",
                "image_id", "image_tag", "image_sha256"}
    require(isinstance(manifest, dict) and set(manifest) == required, "Invalid release manifest fields")
    require(type(manifest["schema"]) is int and manifest["schema"] == 1, "Unknown manifest schema")
    require(manifest["application"] == APPLICATION and manifest["release"] == release,
            "Application or release mismatch")
    require(isinstance(manifest["app_sha"], str) and re.fullmatch(r"[0-9a-f]{40}", manifest["app_sha"])
            and release.startswith(manifest["app_sha"][:12] + "-"), "Application source mismatch")
    require(manifest["engine_sha"] == ENGINE, "Unapproved test engine pairing")
    require(manifest["image_tag"] == APPLICATION + ":" + release, "Unrelated image tag")
    require(isinstance(manifest["image_id"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["image_id"]), "Invalid image identity")
    require(isinstance(manifest["image_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", manifest["image_sha256"]), "Invalid image checksum")


def loaded_identity(actual, config_bytes):
    # The classic store's Id binds the exact configuration bytes, even when
    # older inspect APIs add empty default fields. Containerd can expose an
    # index Id instead; in that case still require exact configuration equality.
    expected = json.loads(config_bytes)
    config_id = "sha256:" + hashlib.sha256(config_bytes).hexdigest()
    require((actual.get("Id") == config_id or actual.get("Config") == expected.get("config"))
            and actual.get("RootFS", {}).get("Layers", []) == expected.get("rootfs", {}).get("diff_ids")
            and actual.get("Architecture") == expected.get("architecture")
            and actual.get("Os") == expected.get("os") == "linux"
            and re.fullmatch(r"sha256:[0-9a-f]{64}", actual.get("Id", "")),
            "Loaded image content mismatch")
    return actual["Id"]


class DockerRuntime:
    def __init__(self, config):
        self.config = config

    def call(self, *args, timeout=180):
        try:
            result = subprocess.run(["/usr/bin/docker", *map(str, args)], check=True,
                                    capture_output=True, text=True, timeout=timeout)
            return result.stdout
        except (OSError, subprocess.SubprocessError) as error:
            # Never echo Docker's raw error: it can include runtime configuration.
            raise ReleaseError("Docker operation failed: " + " ".join(map(str, args[:2]))) from error

    def container(self, name):
        identity = self.call("container", "ls", "-a", "--filter", "name=^/" + name + "$",
                             "--format", "{{.ID}}").strip()
        if not identity:
            return None
        value = json.loads(self.call("container", "inspect", identity))[0]
        require(value.get("Config", {}).get("Labels", {}).get("dev.yuling.application") == APPLICATION,
                "Refusing to modify a container owned by another application")
        return value

    def preflight(self):
        gateway = ipaddress.ip_address(self.config["gateway"])
        allowed = [ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
        require(gateway.version == 4 and any(gateway in network for network in allowed),
                "Binding must be a private IPv4 Docker gateway")
        for key in ("caddy_network", "caddy_container"):
            require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", self.config[key]),
                    "Invalid Caddy resource identifier")
        network = json.loads(self.call("network", "inspect", self.config["caddy_network"]))[0]
        require(network["Driver"] == "bridge"
                and any(item.get("Gateway") == str(gateway) for item in network["IPAM"]["Config"]),
                "Caddy network gateway changed; owner must inspect configuration")
        caddy = json.loads(self.call("container", "inspect", self.config["caddy_container"]))[0]
        require(caddy["State"]["Running"] and self.config["caddy_network"]
                in caddy["NetworkSettings"]["Networks"], "Caddy container/network unavailable")
        for name in (APPLICATION, APPLICATION + "-check"):
            self.container(name)
        names = self.call("network", "ls", "--format", "{{.Name}}").splitlines()
        if APPLICATION not in names:
            self.call("network", "create", "--label", "dev.yuling.application=" + APPLICATION, APPLICATION)
        own = json.loads(self.call("network", "inspect", APPLICATION))[0]
        require(own.get("Labels", {}).get("dev.yuling.application") == APPLICATION
                and own["Driver"] == "bridge", "Refusing unrelated application network")

    def load(self, directory, manifest):
        self.call("image", "load", "--input", directory / "image.tar", timeout=300)
        self.image_identity(manifest)

    def image_identity(self, manifest):
        directory = ROOT / "releases" / valid_release(manifest["release"])
        with tarfile.open(directory / "image.tar") as archive:
            config = archive.getmember("config.json")
            require(config.size <= 524288 and config.isfile(), "Invalid stored image configuration")
            with archive.extractfile(config) as source:
                data = source.read()
        require("sha256:" + hashlib.sha256(data).hexdigest() == manifest["image_id"],
                "Stored configuration identity mismatch")
        image = json.loads(self.call("image", "inspect", manifest["image_tag"]))[0]
        return loaded_identity(image, data)

    def capacity(self):
        match = re.search(r"^MemAvailable:\s+(\d+)\s+kB$", Path("/proc/meminfo").read_text(), re.M)
        require(match and int(match[1]) >= 768 * 1024, "Insufficient available memory; minimum 768 MiB")
        require(shutil.disk_usage(ROOT).free >= MIN_DISK, "Insufficient disk; minimum 8 GiB")

    def remove(self, name):
        if self.container(name) is not None:
            self.call("container", "stop", "--time", "20", name)
            self.call("container", "rm", name)

    def stop(self):
        self.remove(APPLICATION)

    def remove_candidate(self):
        self.remove(APPLICATION + "-check")

    def start(self, manifest, published=True):
        name = APPLICATION if published else APPLICATION + "-check"
        require(self.container(name) is None, "Application container name is already in use")
        args = ["run", "-d", "--name", name, "--label", "dev.yuling.application=" + APPLICATION,
                "--label", "dev.yuling.release=" + manifest["release"],
                "--network", APPLICATION, "--cpus", "1", "--memory", "1024m", "--memory-swap", "1024m",
                "--pids-limit", "256", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "10001:10001", "--env-file", str(ENV_FILE),
                "-e", "NODE_ENV=production", "-e", "PPT_HOST=0.0.0.0", "-e", "PORT=5000",
                "-e", "PPT_ENGINE_ROOT=/opt/yuling/engine", "-e", "PPT_PYTHON_PATH=/usr/local/bin/python",
                "-e", "PPT_CHROME_PATH=/opt/chrome/chrome-linux64/chrome",
                "--log-driver", "json-file", "--log-opt", "max-size=5m", "--log-opt", "max-file=2"]
        if published:
            args += ["--publish", self.config["gateway"] + ":5000:5000", "--restart", "unless-stopped"]
        args += [self.image_identity(manifest)]
        self.call(*args)
        self.readiness(name)
        if not published:
            self.call("exec", name, "node", "dist/release-smoke.js", "quick", timeout=120)

    def readiness(self, name):
        probe = """(async()=>{
const base='http://127.0.0.1:5000';
let ready=false;
for(let i=0;i<30;i++){try{const r=await fetch(base+'/api/health',{signal:AbortSignal.timeout(2000)});
if(r.ok){ready=true;break;}}catch{} await new Promise(r=>setTimeout(r,1000));}
if(!ready)throw Error('health');
const page=await fetch(base+'/ppt');if(!page.ok)throw Error('page');
const html=await page.text();const asset=html.match(/(?:src|href)="(\\/_next\\/static\\/[^"]+)"/);
if(!asset)throw Error('asset missing');
const r=await fetch(base+asset[1]);if(!r.ok||(await r.arrayBuffer()).byteLength===0)throw Error('asset');
})().catch(()=>process.exit(1));"""
        self.call("exec", name, "node", "-e", probe, timeout=90)

    def delete_image(self, manifest):
        self.image_identity(manifest)
        self.call("image", "rm", manifest["image_tag"])


class Controller:
    def __init__(self, root, config, docker=None):
        self.root = root
        self.config = config
        self.docker = docker
        self.releases = root / "releases"
        self.incoming = root / ".incoming"
        for directory in (root, self.releases, self.incoming):
            require(not directory.is_symlink(), "Symlinked release directory")
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def upload(self, request, stream):
        require(set(request) == {"op", "release", "bytes", "sha256"}, "Invalid upload request fields")
        release = valid_release(request["release"])
        size = request["bytes"]
        expected = request["sha256"]
        require(type(size) is int and 0 < size <= MAX_UPLOAD, "Invalid upload size")
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                "Invalid upload checksum")
        require(shutil.disk_usage(self.root).free >= MIN_DISK + size, "Insufficient upload disk space")
        temporary = Path(tempfile.mkdtemp(prefix="upload-", dir=self.incoming))
        try:
            payload = temporary / "bundle.tar"
            with payload.open("wb") as target:
                remaining = size
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    require(chunk, "Truncated upload")
                    target.write(chunk)
                    remaining -= len(chunk)
            require(not stream.read(1), "Unexpected trailing upload data")
            require(digest_file(payload) == expected, "Upload checksum mismatch")
            destination = self.releases / release
            require(not destination.is_symlink(), "Unsafe release destination")
            if destination.exists():
                require(read_json(destination / "receipt.json")["sha256"] == expected,
                        "Release already exists with different content")
                return {"status": "stored", "release": release, "idempotent": True}
            with tarfile.open(payload, "r:") as archive:
                files = members(archive, MAX_UPLOAD)
                require(set(files) == {"release.json", "image.tar.gz"}, "Unexpected bundle members")
                manifest = tar_json(archive, files["release.json"])
                validate_manifest(manifest, release)
                compressed = temporary / "image.tar.gz"
                with archive.extractfile(files["image.tar.gz"]) as source, compressed.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
            require(digest_file(compressed) == manifest["image_sha256"], "Image archive checksum mismatch")
            normalize_image(compressed, temporary / "image.tar", manifest)
            payload.unlink()
            compressed.unlink()
            write_json(temporary / "release.json", manifest)
            write_json(temporary / "receipt.json", {"sha256": expected, "bytes": size,
                       "normalized_sha256": digest_file(temporary / "image.tar")})
            os.rename(temporary, destination)
            return {"status": "stored", "release": release, "idempotent": False}
        except (tarfile.TarError, EOFError, OSError, ValueError, KeyError, TypeError) as error:
            raise ReleaseError("Malformed or unreadable release bundle") from error
        finally:
            if temporary.exists():
                require(temporary.resolve().is_relative_to(self.incoming.resolve()),
                        "Refusing cleanup outside upload staging")
                shutil.rmtree(temporary)


    def stored(self, release):
        valid_release(release)
        directory = self.releases / release
        require(directory.is_dir() and not directory.is_symlink(), "Release is not uploaded")
        manifest = read_json(directory / "release.json")
        validate_manifest(manifest, release)
        receipt = read_json(directory / "receipt.json")
        require(digest_file(directory / "image.tar") == receipt["normalized_sha256"],
                "Stored image checksum mismatch")
        return manifest

    def state(self):
        file = self.root / "state.json"
        value = read_json(file) if file.exists() else {"current": None, "previous": None, "pending": None}
        require(isinstance(value, dict) and set(value) == {"current", "previous", "pending"},
                "Invalid release state; owner recovery required")
        for rid in value.values():
            if rid is not None:
                valid_release(rid)
        return value

    def save_state(self, state):
        write_json(self.root / "state.json", state)

    def recover(self, state):
        self.docker.remove_candidate()
        self.docker.stop()
        if state["current"]:
            self.docker.start(self.stored(state["current"]))
        state["pending"] = None
        self.save_state(state)

    def install(self, release):
        valid_release(release)
        self.docker.preflight()
        state = self.state()
        if state["pending"]:
            self.recover(state)
        if state["current"] == release:
            return {"status": "unchanged", **state}
        manifest = self.stored(release)
        require(shutil.disk_usage(self.root).free >= MIN_DISK, "Insufficient disk before image load")
        self.docker.load(self.releases / release, manifest)
        state["pending"] = release
        self.save_state(state)
        try:
            self.docker.stop()
            self.docker.capacity()
            self.docker.remove_candidate()
            self.docker.start(manifest, published=False)
            self.docker.remove_candidate()
            self.docker.start(manifest)
        except Exception as error:
            try:
                self.recover(state)
            except Exception as recovery_error:
                raise ReleaseError("Publish failed AND recovery failed; pending state retained; owner intervention required") from recovery_error
            raise ReleaseError("Publish failed; prior state restored: " + str(error)) from error
        state = {"current": release, "previous": state["current"], "pending": None}
        self.save_state(state)
        return {"status": "published", **state}

    def rollback(self):
        state = self.state()
        if state["pending"]:
            self.docker.preflight()
            self.recover(state)
        require(state["previous"], "No previous successful release is available")
        return self.install(state["previous"])

    def cleanup(self):
        """Only our superseded archives/images; no global Docker prune."""
        state = self.state()
        require(not state["pending"], "Cannot clean an incomplete transaction")
        keep = {state["current"], state["previous"]}
        retained = []
        for directory in self.releases.iterdir():
            if directory.name in keep:
                continue
            require(not directory.is_symlink() and directory.is_dir()
                    and RID.fullmatch(directory.name), "Unexpected release directory; refusing cleanup")
            try:
                self.docker.delete_image(read_json(directory / "release.json"))
            except ReleaseError:
                retained.append(directory.name)
                continue
            require(directory.resolve().parent == self.releases.resolve(), "Unsafe cleanup target")
            shutil.rmtree(directory)
        return retained


def dispatch(controller, stream):
    line = stream.readline(4097)
    require(len(line) <= 4096 and line.endswith(b"\n"), "Invalid request header")
    try:
        request = json.loads(line)
    except (ValueError, UnicodeError) as error:
        raise ReleaseError("Invalid request JSON") from error
    require(isinstance(request, dict), "Request must be an object")
    operation = request.get("op")
    if operation == "upload":
        return controller.upload(request, stream)
    require(not stream.read(1), "Unexpected trailing request data")
    if operation == "status":
        require(set(request) == {"op"}, "Invalid status fields")
        return controller.state()
    if operation == "deploy":
        require(set(request) == {"op", "release"}, "Invalid deploy fields")
        return controller.install(request["release"])
    if operation == "rollback":
        require(set(request) == {"op"}, "Invalid rollback fields")
        return controller.rollback()
    raise ReleaseError("Unknown operation; only upload, deploy, status and rollback are supported")


def secure_file(path):
    require(path.is_file() and not path.is_symlink(), "Required configuration file is missing")
    info = path.stat()
    require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600,
            "Configuration must be root-owned with mode 0600")


def main():
    require(os.geteuid() == 0 and len(sys.argv) == 1, "Use the installed restricted receiver")
    import fcntl
    secure_file(CONFIG)
    secure_file(ENV_FILE)
    require(ROOT.is_dir() and not ROOT.is_symlink() and ROOT.stat().st_uid == 0
            and not ROOT.stat().st_mode & 0o022, "Unsafe application directory")
    config = read_json(CONFIG)
    require(set(config) == {"gateway", "caddy_network", "caddy_container"}, "Invalid host configuration")
    controller = Controller(ROOT, config, DockerRuntime(config))
    with (ROOT / "receiver.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ReleaseError("Another PPT operation is running; retry after it completes") from error
        # Whole request deadline; normal subprocess timeouts are shorter and recover first.
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(ReleaseError("Receiver deadline exceeded")))
        signal.alarm(900)
        result = dispatch(controller, sys.stdin.buffer)
        if result.get("status") == "published":
            result["retained_for_owner_review"] = controller.cleanup()
        print(json.dumps(result))
        signal.alarm(0)


if __name__ == "__main__":
    try:
        main()
    except (ReleaseError, OSError, ValueError, KeyError, TypeError) as error:
        # Request/host errors are useful; avoid dumping tracebacks or environment data.
        print(json.dumps({"status": "failed", "error": str(error) if isinstance(error, ReleaseError)
                          else "Invalid host state; owner inspection required"}), file=sys.stderr)
        sys.exit(1)
