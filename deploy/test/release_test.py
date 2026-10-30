"""Real bundle-validation boundary tests; fixtures contain no real secrets."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("release", Path(__file__).with_name("release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
APP = "a" * 40
ENGINE = "be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192"
RID = APP[:12] + "-123-1"


def tar_bytes(files):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def bundle(dirty="false", **overrides):
    config = json.dumps({
        "config": {
            "User": "10001:10001",
            "Labels": {
                "org.opencontainers.image.revision": APP,
                "dev.yuling.engine.revision": ENGINE,
                "dev.yuling.application": "yuling-ppt-test",
                "dev.yuling.source.dirty": dirty,
            },
            "Env": ["NODE_ENV=production"],
        },
        "rootfs": {"type": "layers", "diff_ids": []},
    }, sort_keys=True).encode()
    digest = hashlib.sha256(config).hexdigest()
    tag = "yuling-ppt-test:" + RID
    image_manifest = [{"Config": "config.json", "RepoTags": [tag], "Layers": []}]
    image = gzip.compress(tar_bytes({
        "config.json": config,
        "manifest.json": json.dumps(image_manifest).encode(),
    }))
    manifest = {
        "schema": 1, "application": "yuling-ppt-test", "release": RID,
        "app_sha": APP, "engine_sha": ENGINE, "image_id": "sha256:" + digest,
        "image_tag": tag, "image_sha256": hashlib.sha256(image).hexdigest(),
    }
    manifest.update(overrides)
    data = tar_bytes({"release.json": json.dumps(manifest).encode(), "image.tar.gz": image})
    request = {"op": "upload", "release": RID, "bytes": len(data),
               "sha256": hashlib.sha256(data).hexdigest()}
    return request, data


class BundleBoundary(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.calls = []
        self.controller = release.Controller(
            Path(self.directory.name),
            {"gateway": "172.18.0.1", "caddy_network": "test-edge", "caddy_container": "test-caddy"},
            docker=lambda *args: self.calls.append(args) or "",
        )

    def reject(self, request, data):
        with self.assertRaises(release.ReleaseError):
            self.controller.upload(request, io.BytesIO(data))
        self.assertEqual(self.calls, [], "Rejected uploads must not call Docker")

    def test_wrong_transport_hash_is_rejected(self):
        request, data = bundle()
        request["sha256"] = "0" * 64
        self.reject(request, data)

    def test_path_traversal_is_rejected(self):
        data = tar_bytes({"../escape": b"bad"})
        request = {"op": "upload", "release": RID, "bytes": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()}
        self.reject(request, data)
        self.assertFalse((Path(self.directory.name).parent / "escape").exists())

    def test_wrong_engine_pair_is_rejected(self):
        self.reject(*bundle(engine_sha="b" * 40))

    def test_mismatched_source_version_is_rejected(self):
        self.reject(*bundle(app_sha="b" * 40))

    def test_unrelated_image_tag_is_rejected(self):
        self.reject(*bundle(image_tag="unrelated:production"))

    def test_truncated_input_is_rejected(self):
        request, data = bundle()
        self.reject(request, data[:100])

    def test_valid_bundle_and_identical_retry(self):
        request, data = bundle()
        first = self.controller.upload(request, io.BytesIO(data))
        self.assertFalse(first["idempotent"])
        second = self.controller.upload(request, io.BytesIO(data))
        self.assertTrue(second["idempotent"])
        self.assertEqual(self.calls, [])
        image = Path(self.directory.name) / "releases" / RID / "image.tar"
        with tarfile.open(image) as archive:
            self.assertEqual(archive.getnames(), ["config.json", "manifest.json"])

    def test_dirty_development_image_rejected(self):
        self.reject(*bundle(dirty="true"))

    def test_directory_entries_count_toward_archive_limit(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            for index in range(4097):
                item = tarfile.TarInfo("folder-" + str(index))
                item.type = tarfile.DIRTYPE
                archive.addfile(item)
        stream.seek(0)
        with tarfile.open(fileobj=stream) as archive:
            with self.assertRaises(release.ReleaseError):
                release.members(archive, 1024)


class RuntimeContract(unittest.TestCase):
    def test_real_start_arguments_keep_trial_limits_and_private_binding(self):
        runtime = release.DockerRuntime({"gateway": "172.18.0.1"})
        calls = []
        runtime.container = lambda name: None
        runtime.call = lambda *args, **kwargs: calls.append(args) or ""
        runtime.image_identity = lambda manifest: "sha256:" + "a" * 64
        runtime.settings_required = lambda manifest: False
        runtime.start({"release": RID, "image_id": "sha256:" + "a" * 64})
        args = calls[0]
        for flag, expected in (("--memory", "1024m"), ("--memory-swap", "1024m"),
                               ("--cpus", "1"), ("--publish", "172.18.0.1:5000:5000"),
                               ("--user", "10001:10001")):
            self.assertEqual(args[args.index(flag) + 1], expected)
        self.assertNotIn("--privileged", args)
        self.assertEqual(calls[1][:3], ("exec", release.APPLICATION, "node"))

    def test_loaded_image_checked_by_configuration_and_layer_content(self):
        expected = {"config": {"User": "10001:10001"}, "architecture": "amd64", "os": "linux",
                    "rootfs": {"diff_ids": ["sha256:" + "a" * 64]}}
        actual = {"Id": "sha256:" + "b" * 64, "Config": expected["config"].copy(),
                  "Architecture": "amd64", "Os": "linux", "RootFS": {"Layers": expected["rootfs"]["diff_ids"][:]}}
        data = json.dumps(expected).encode()
        self.assertEqual(release.loaded_identity(actual, data), actual["Id"])
        for field, value in (("Config", {"User": "0"}), ("RootFS", {"Layers": []}), ("Architecture", "arm64")):
            broken = {**actual, field: value}
            with self.assertRaises(release.ReleaseError):
                release.loaded_identity(broken, data)

    def test_classic_docker_default_fields_do_not_change_content_identity(self):
        expected = {"config": {"User": "10001:10001"}, "architecture": "amd64", "os": "linux",
                    "rootfs": {"diff_ids": ["sha256:" + "a" * 64]}}
        data = json.dumps(expected).encode()
        actual = {"Id": "sha256:" + hashlib.sha256(data).hexdigest(),
                  "Config": {**expected["config"], "Hostname": "", "Tty": False, "OnBuild": None},
                  "Architecture": "amd64", "Os": "linux", "RootFS": {"Layers": expected["rootfs"]["diff_ids"][:]}}
        self.assertEqual(release.loaded_identity(actual, data), actual["Id"])
        for field, value in (("Id", "sha256:" + "b" * 64), ("RootFS", {"Layers": []}),
                             ("Architecture", "arm64"), ("Os", "windows")):
            with self.subTest(field=field), self.assertRaises(release.ReleaseError):
                release.loaded_identity({**actual, field: value}, data)
        changed = {**expected, "config": {"User": "0"}}
        with self.assertRaises(release.ReleaseError):
            release.loaded_identity(actual, json.dumps(changed).encode())


class FakeRuntime:
    def __init__(self):
        self.running = None
        self.fail = None
        self.capacity_error = False
        self.calls = []

    def preflight(self):
        self.calls.append("preflight")

    def load(self, directory, manifest):
        self.calls.append("load:" + manifest["release"])

    def capacity(self):
        self.calls.append("capacity")
        if self.capacity_error:
            raise release.ReleaseError("Insufficient available memory")

    def stop(self):
        self.calls.append("stop")
        self.running = None

    def start(self, manifest, published=True):
        self.calls.append(("start:" if published else "candidate:") + manifest["release"])
        self.running = manifest["release"]
        if self.fail == manifest["release"]:
            raise release.ReleaseError("Container readiness failed")

    def remove_candidate(self):
        self.calls.append("remove-candidate")


class ReleaseTransactions(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = FakeRuntime()
        self.controller = release.Controller(Path(self.directory.name), {}, docker=self.runtime)
        self.old = "a" * 12 + "-1-1"
        self.new = "b" * 12 + "-2-1"
        self.old_manifest = {"release": self.old}
        self.new_manifest = {"release": self.new}
        # Archive validation has separate real-byte tests. Here the actual transaction
        # and protocol run with a deterministic host instead of touching the workstation.
        self.controller.stored = lambda rid: {"release": rid}
        release.write_json(self.controller.root / "state.json",
                           {"current": self.old, "previous": None, "pending": None})
        self.runtime.running = self.old

    def invoke(self, request):
        return release.dispatch(self.controller, io.BytesIO(json.dumps(request).encode() + b"\n"))

    def test_start_failure_restores_old_and_propagates_failure(self):
        self.runtime.fail = self.new
        with self.assertRaisesRegex(release.ReleaseError, "restored"):
            self.invoke({"op": "deploy", "release": self.new})
        self.assertEqual(self.runtime.running, self.old)
        state = release.read_json(self.controller.root / "state.json")
        self.assertEqual(state["current"], self.old)
        self.assertIsNone(state["pending"])

    def test_capacity_failure_restores_old(self):
        self.runtime.capacity_error = True
        with self.assertRaisesRegex(release.ReleaseError, "memory"):
            self.invoke({"op": "deploy", "release": self.new})
        self.assertEqual(self.runtime.running, self.old)

    def test_publish_then_real_rollback_entry_restores_previous(self):
        self.invoke({"op": "deploy", "release": self.new})
        self.assertEqual(self.runtime.running, self.new)
        self.invoke({"op": "rollback"})
        self.assertEqual(self.runtime.running, self.old)
        state = release.read_json(self.controller.root / "state.json")
        self.assertEqual(state["current"], self.old)
        self.assertEqual(state["previous"], self.new)

    def test_interrupted_transaction_is_recovered_before_next_operation(self):
        release.write_json(self.controller.root / "state.json",
                           {"current": self.old, "previous": None, "pending": self.new})
        self.runtime.running = self.new
        self.invoke({"op": "deploy", "release": self.old})
        self.assertEqual(self.runtime.running, self.old)
        self.assertIn("start:" + self.old, self.runtime.calls)

    def test_first_failed_publish_leaves_no_current_container(self):
        release.write_json(self.controller.root / "state.json",
                           {"current": None, "previous": None, "pending": None})
        self.runtime.running = None
        self.runtime.fail = self.new
        with self.assertRaises(release.ReleaseError):
            self.invoke({"op": "deploy", "release": self.new})
        self.assertIsNone(self.runtime.running)

    def test_protocol_rejects_unknown_operation_without_docker(self):
        with self.assertRaisesRegex(release.ReleaseError, "operation"):
            self.invoke({"op": "shell", "command": "id"})
        self.assertEqual(self.runtime.calls, [])

    def test_protocol_rejects_trailing_data(self):
        with self.assertRaises(release.ReleaseError):
            release.dispatch(self.controller, io.BytesIO(b'{"op":"rollback"}\nextra'))
        self.assertEqual(self.runtime.calls, [])

    def test_status_reports_pending_without_mutation(self):
        release.write_json(self.controller.root / "state.json",
                           {"current": self.old, "previous": None, "pending": self.new})
        result = self.invoke({"op": "status"})
        self.assertEqual(result["pending"], self.new)
        self.assertEqual(self.runtime.calls, [])


if __name__ == "__main__":
    unittest.main()
