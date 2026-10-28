"""Pinned runtime cache contract for the workstation release path."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


def load_builder():
    path = Path(__file__).with_name("build-image.py")
    spec = importlib.util.spec_from_file_location("runtime_cache_builder_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "state" / "runtime-cache"
        self.output = self.root / "output"
        self.data = b"verified runtime fixture"
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.lock = {"downloads": {"node.tar.xz": {
            "url": "https://example.invalid/node.tar.xz", "sha256": self.digest}}}
        self.builder = load_builder()

    def entry(self):
        return self.cache / ("node.tar.xz-" + self.digest)

    def test_warm_then_offline_hit_never_fetches_and_copies_isolated_output(self):
        with patch.object(self.builder.urllib.request, "urlopen", return_value=io.BytesIO(self.data)) as fetch:
            self.builder.prepare_downloads(self.output, self.lock, self.cache)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.entry().read_bytes(), self.data)
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            other = self.root / "other-output"
            downloads = self.builder.prepare_downloads(other, self.lock, self.cache, offline=True)
        self.assertEqual((downloads / "node.tar.xz").read_bytes(), self.data)
        self.assertNotEqual(downloads / "node.tar.xz", self.entry())

    def test_verified_existing_archive_can_seed_cache_without_network(self):
        seed = self.root / "existing-downloads"
        seed.mkdir()
        (seed / "node.tar.xz").write_bytes(self.data)
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            self.builder.prepare_downloads(self.output, self.lock, self.cache, seed_dir=seed)
        self.assertEqual(self.entry().read_bytes(), self.data)
        (seed / "node.tar.xz").write_bytes(b"wrong")
        self.cache.joinpath(self.entry().name).unlink()
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            with self.assertRaisesRegex(RuntimeError, "seed checksum"):
                self.builder.prepare_downloads(self.root / "second", self.lock, self.cache, seed_dir=seed)
        self.assertFalse(self.entry().exists())

    def test_offline_miss_and_corrupt_existing_cache_fail_without_network(self):
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache, offline=True)
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.entry().write_bytes(b"wrong")  # Deliberate bad cache mutation.
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache, offline=True)
        self.assertFalse((self.output / "runtime-downloads" / "node.tar.xz").exists())

    def test_truncated_attempt_is_removed_before_retry(self):
        with patch.object(self.builder.urllib.request, "urlopen",
                          side_effect=[io.BytesIO(b"truncated"), io.BytesIO(self.data)]) as fetch, \
                patch.object(self.builder.time, "sleep") as sleep:
            self.builder.prepare_downloads(self.output, self.lock, self.cache)
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(2)
        self.assertEqual(self.entry().read_bytes(), self.data)
        self.assertEqual(list(self.cache.glob("*.partial")), [])

    def test_three_network_failures_leave_no_cache_entry(self):
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=TimeoutError("fixture")) as fetch, \
                patch.object(self.builder.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "three attempts"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual([item.args[0] for item in sleep.call_args_list], [2, 5])
        self.assertFalse(self.entry().exists())
        self.assertEqual(list(self.cache.glob("*.partial")), [])

    def test_busy_cache_lock_fails_closed_without_download(self):
        self.cache.mkdir(mode=0o700, parents=True)
        (self.cache / ".lock").write_text("busy")
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            with self.assertRaisesRegex(RuntimeError, "in use"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache)

    def test_second_warm_process_cannot_use_cache_during_first_download(self):
        entered = threading.Event()
        release = threading.Event()
        failures = []

        def blocked_fetch(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test wait exceeded")
            return io.BytesIO(self.data)

        def first_warm():
            try:
                self.builder.prepare_downloads(self.output, self.lock, self.cache)
            except Exception as error:
                failures.append(error)

        with patch.object(self.builder.urllib.request, "urlopen", side_effect=blocked_fetch) as fetch:
            worker = threading.Thread(target=first_warm)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaisesRegex(RuntimeError, "in use"):
                    self.builder.prepare_downloads(self.root / "other", self.lock, self.cache)
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.entry().read_bytes(), self.data)

    def test_corruption_while_copying_to_output_is_rejected(self):
        self.cache.mkdir(mode=0o700, parents=True)
        self.entry().write_bytes(self.data)
        original = self.builder.shutil.copyfile

        def corrupt_copy(source, destination):
            result = original(source, destination)
            Path(destination).write_bytes(b"changed during copy")
            return result

        with patch.object(self.builder.shutil, "copyfile", side_effect=corrupt_copy):
            with self.assertRaisesRegex(RuntimeError, "output checksum"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache, offline=True)

    def test_read_deadline_rejects_slow_attempt_and_cleans_partial(self):
        class Slow(io.BytesIO):
            def read(self, size=-1):
                return b"slow"
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=lambda *args, **kwargs: Slow()), \
                patch.object(self.builder.time, "monotonic", side_effect=[0, 0, 601] * 3), \
                patch.object(self.builder.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "three attempts"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache)
        self.assertFalse(self.entry().exists())
        self.assertEqual(list(self.cache.glob("*.partial")), [])

    def test_symlink_cache_entry_is_rejected_without_fetch(self):
        self.cache.mkdir(mode=0o700, parents=True)
        try:
            self.entry().symlink_to(self.root / "elsewhere")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                self.builder.prepare_downloads(self.output, self.lock, self.cache, offline=True)


if __name__ == "__main__":
    unittest.main()
