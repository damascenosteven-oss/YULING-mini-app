"""Run-attempt changes must never synthesize a different artifact reference."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ArtifactReference(unittest.TestCase):
    def check(self, identity, attempt):
        return subprocess.run([sys.executable, str(Path(__file__).with_name("artifact-reference.py"))],
                              env={**os.environ, "BUILD_ARTIFACT_ID": identity, "GITHUB_RUN_ATTEMPT": str(attempt)},
                              capture_output=True)

    def test_initial_and_release_only_retry_keep_build_identity(self):
        for attempt in (1, 2, 5):
            result = self.check("12706655039", attempt)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), b"artifact_id=12706655039")

    def test_full_rerun_uses_new_build_identity(self):
        self.assertEqual(self.check("12706655040", 2).stdout.strip(), b"artifact_id=12706655040")

    def test_missing_or_invalid_reference_fails_without_fallback(self):
        for value in ("", "0", "latest", "1,2", " 12", "1\n"):
            self.assertNotEqual(self.check(value, 2).returncode, 0)


if __name__ == "__main__":
    unittest.main()
