"""Final-image errors retain fixed diagnostics, never captured process secrets."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ImageDiagnostics(unittest.TestCase):
    def test_permission_failure_is_classified_without_process_output(self):
        spec = importlib.util.spec_from_file_location("verify_image", Path(__file__).with_name("verify-image.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.json").write_text(json.dumps({"tag": "fixture", "app_sha": "a" * 40}))
            def execute(*args):
                if "quick" in args:
                    raise subprocess.CalledProcessError(1, ["secret-command"],
                        output="secret-output", stderr="EACCES: permission denied secret-token")
                return ""
            out, err = io.StringIO(), io.StringIO()
            with patch.object(module, "run", side_effect=execute), patch.object(module.subprocess, "run"), \
                    patch.object(sys, "argv", ["verify-image.py", "--build-output", directory]), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as stopped:
                    module.main()
            self.assertEqual(stopped.exception.code, 5)
            diagnostic = json.loads((root / "image-check-error.json").read_text())
            self.assertEqual(diagnostic, {"schema": 1, "stage": "quick_smoke",
                                         "code": "image_permission_denied", "exit_code": 1})
            self.assertNotIn("secret", out.getvalue() + err.getvalue() + json.dumps(diagnostic))
            self.assertFalse((root / "verification.json").exists())


if __name__ == "__main__":
    unittest.main()
