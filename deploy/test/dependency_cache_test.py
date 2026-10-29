"""Offline dependency installation is required for the phone release build."""
from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch


def load_builder():
    source = Path(__file__).with_name("build-image.py")
    spec = importlib.util.spec_from_file_location("build_image", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DependencyInstallContractTests(unittest.TestCase):
    def test_docker_install_uses_frozen_offline_pnpm_and_disables_npx_network(self):
        dockerfile = Path(__file__).with_name("Dockerfile").read_text()
        self.assertIn("pnpm install --offline --frozen-lockfile", dockerfile)
        self.assertIn("npm_config_offline=true", dockerfile)
        self.assertIn("COPY --from=dependency_store", dockerfile)
        self.assertIn("RUN --network=none npm_config_offline=true pnpm install", dockerfile)

    def test_cache_hit_is_offline_and_rejects_corruption(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "private-cache"
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            def populate(stage, _downloads, _lock):
                store = stage / "store"
                store.mkdir()
                (store / "package-index").write_bytes(b"pinned package")
                return builder.dependency_tree_digest(store)
            with patch.object(builder, "populate_dependency_store", side_effect=populate) as fetch:
                with patch.object(builder.platform, "machine", return_value="x86_64"), \
                        patch.object(builder.sys, "platform", "linux"):
                    builder.prepare_dependencies(first, root, {}, cache)
                    builder.prepare_dependencies(second, root, {}, cache, offline=True)
                    self.assertEqual(fetch.call_count, 1)
                    entry = cache / builder.dependency_identity() / "store"
                    (entry / "package-index").write_bytes(b"changed")
                    with self.assertRaisesRegex(RuntimeError, "integrity"):
                        builder.prepare_dependencies(root / "third", root, {}, cache, offline=True)

    def test_missing_or_wrong_lock_cache_is_rejected_offline(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "private-cache"
            with patch.object(builder.platform, "machine", return_value="x86_64"), \
                    patch.object(builder.sys, "platform", "linux"):
                with self.assertRaisesRegex(RuntimeError, "missing"):
                    builder.prepare_dependencies(root, root, {}, cache, offline=True)
                cache.mkdir(exist_ok=True)
                entry = cache / builder.dependency_identity()
                (entry / "store").mkdir(parents=True)
                (entry / "store" / "package-index").write_bytes(b"pinned package")
                (entry / "manifest.json").write_text(json.dumps({
                    "identity": "wrong-lock", "tree_sha256": builder.dependency_tree_digest(entry / "store")}))
                with self.assertRaisesRegex(RuntimeError, "integrity"):
                    builder.prepare_dependencies(root, root, {}, cache, offline=True)

    def test_cache_rejects_symlink_and_concurrent_prefetch(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "private-cache"
            cache.mkdir(mode=0o700)
            with patch.object(builder.platform, "machine", return_value="x86_64"), \
                    patch.object(builder.sys, "platform", "linux"):
                (cache / (builder.dependency_identity() + ".lock")).write_text("busy")
                with self.assertRaisesRegex(RuntimeError, "already in use"):
                    builder.prepare_dependencies(root, root, {}, cache)
                (cache / (builder.dependency_identity() + ".lock")).unlink()
                entry = cache / builder.dependency_identity()
                entry.symlink_to(root, target_is_directory=True)
                with self.assertRaisesRegex(RuntimeError, "Unsafe"):
                    builder.prepare_dependencies(root, root, {}, cache, offline=True)

    def test_fetch_timeout_is_bounded_and_does_not_accept_partial_cache(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "private-cache"
            def timeout(*_args, **_kwargs):
                raise subprocess.TimeoutExpired("pnpm fetch", 300)
            with patch.object(builder.platform, "machine", return_value="x86_64"), \
                    patch.object(builder.sys, "platform", "linux"), \
                    patch.object(builder, "dependency_toolchain", return_value=(root / "node", root / "pnpm")), \
                    patch.object(builder.subprocess, "run", side_effect=timeout) as fetch, \
                    patch.object(builder.time, "sleep") as pause:
                with self.assertRaisesRegex(RuntimeError, "after three attempts"):
                    builder.prepare_dependencies(root, root, {}, cache)
                self.assertEqual(fetch.call_count, 3)
                self.assertEqual([call.kwargs["timeout"] for call in fetch.call_args_list], [300] * 3)
                self.assertEqual([call.args[0] for call in pause.call_args_list], [2, 5])
                self.assertFalse((cache / builder.dependency_identity()).exists())
                self.assertFalse((cache / (builder.dependency_identity() + ".lock")).exists())

    def test_incomplete_store_is_rejected_by_offline_install(self):
        builder = load_builder()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / "private-cache"
            def run(command, **kwargs):
                if "fetch" in command:
                    store = Path(command[command.index("--store-dir") + 1])
                    store.mkdir()
                    (store / "partial-package").write_bytes(b"not enough")
                    return subprocess.CompletedProcess(command, 0)
                if "install" in command:
                    self.assertIn("--offline", command)
                    self.assertEqual(kwargs["env"]["npm_config_offline"], "true")
                    raise subprocess.CalledProcessError(1, command)
                raise AssertionError(command)
            with patch.object(builder.platform, "machine", return_value="x86_64"), \
                    patch.object(builder.sys, "platform", "linux"), \
                    patch.object(builder, "dependency_toolchain", return_value=(root / "node", root / "pnpm")), \
                    patch.object(builder.subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "offline frozen install failed"):
                    builder.prepare_dependencies(root, root, {}, cache)
                self.assertFalse((cache / builder.dependency_identity()).exists())


if __name__ == "__main__":
    unittest.main()
