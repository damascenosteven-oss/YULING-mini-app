"""Persistent settings provisioning and the actual Docker start argument boundary."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from bootstrap_test import bootstrap
from release_test import release, RID


@unittest.skipUnless(os.name == 'posix', 'Linux permissions required')
class ModelSettingsDeployment(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            raise RuntimeError('Use sudo for administrator provisioning tests')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conf = self.root / 'conf'
        self.conf.mkdir(mode=0o700)
        self.settings = self.root / 'model-settings'
        self.env = self.conf / 'app.env'
        self.original = b'DEEPSEEK_API_KEY=fixture-key\nPPT_INVITE_PASSWORD=fixture-invite\nPPT_SESSION_SECRET=fixture-secret\n'
        self.env.write_bytes(self.original); self.env.chmod(0o600)
        for obj, name, value in [(bootstrap, 'ROOT', self.root), (bootstrap, 'CONF', self.conf),
                                 (bootstrap, 'MODEL_SETTINGS_DIR', self.settings),
                                 (release, 'MODEL_SETTINGS_DIR', self.settings)]:
            item = patch.object(obj, name, value, create=True); item.start(); self.addCleanup(item.stop)

    def initialize(self, reset=False):
        with patch.object(bootstrap.sys.stdin, 'isatty', return_value=True), \
             patch.object(bootstrap.getpass, 'getpass', return_value='independent-fixture-password'):
            bootstrap.initialize_model_settings('https://ppt.example', reset_password=reset)

    def test_provision_preserves_old_values_and_hashes_password(self):
        self.initialize()
        value = self.env.read_bytes()
        self.assertTrue(value.startswith(self.original))
        self.assertNotIn(b'independent-fixture-password', value)
        values = dict(line.split('=', 1) for line in value.decode().splitlines())
        version, salt, digest = values['PPT_ADMIN_PASSWORD_HASH'].split(':')
        self.assertEqual(version, 'scrypt-v1')
        self.assertEqual(hashlib.scrypt(b'independent-fixture-password', salt=salt.encode(), n=16384, r=8, p=1, dklen=32).hex(), digest)
        self.assertEqual((self.settings.stat().st_uid, stat.S_IMODE(self.settings.stat().st_mode)), (10001, 0o700))
        self.assertTrue(release.model_settings_ready())
        with self.assertRaisesRegex(RuntimeError, 'already'):
            self.initialize()
        self.assertEqual(self.env.read_bytes(), value)
        self.initialize(reset=True)
        self.assertTrue(self.env.read_bytes().startswith(self.original))
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        backups = list(self.conf.glob('app-model-settings-*.before'))
        self.assertTrue(any(p.read_bytes() == self.original for p in backups))

    def test_invalid_origin_no_interactive_input_or_shared_password_cannot_modify(self):
        with self.assertRaises(RuntimeError):
            bootstrap.initialize_model_settings('http://ppt.example')
        with patch.object(bootstrap.sys.stdin, 'isatty', return_value=False), self.assertRaises(RuntimeError):
            bootstrap.initialize_model_settings('https://ppt.example')
        with patch.object(bootstrap.sys.stdin, 'isatty', return_value=True), patch.object(bootstrap.getpass, 'getpass', return_value='fixture-invite'), self.assertRaises(RuntimeError):
            bootstrap.initialize_model_settings('https://ppt.example')
        self.assertEqual(self.env.read_bytes(), self.original)

    def test_real_start_mount_is_private_writable_only_for_published_container(self):
        self.initialize()
        runtime = release.DockerRuntime({'gateway': '172.18.0.1'})
        calls = []
        runtime.container = lambda name: None
        runtime.image_identity = lambda manifest: 'sha256:' + 'a' * 64
        runtime.settings_required = lambda manifest: True
        runtime.call = lambda *args, **kwargs: calls.append(args) or ''
        for published in (True, False):
            calls.clear()
            runtime.start({'release': RID}, published=published)
            args = calls[0]
            mount = args[args.index('--mount') + 1]
            self.assertIn('src=' + str(self.settings), mount)
            self.assertIn('dst=/var/lib/yuling-ppt/model-settings', mount)
            self.assertEqual(mount.endswith(',readonly'), not published)
        self.settings.chmod(0o755)
        self.assertFalse(release.model_settings_ready())
        with self.assertRaises(release.ReleaseError):
            runtime.start({'release': RID})
