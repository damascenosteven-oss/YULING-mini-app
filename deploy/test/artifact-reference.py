"""Fail before download when the successful build did not supply one artifact ID."""
import os
import re

identity = os.environ.get("BUILD_ARTIFACT_ID", "")
if not re.fullmatch(r"[1-9][0-9]{0,19}", identity):
    raise SystemExit("Missing or invalid build artifact ID; run a new build, never select latest")
print("artifact_id=" + identity)
