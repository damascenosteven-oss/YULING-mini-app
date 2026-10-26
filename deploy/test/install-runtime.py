"""Install already-hashed official runtime downloads inside the build image."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import zipfile

lock = json.loads(Path("/tmp/runtime-lock.json").read_text(encoding="utf-8"))
root = Path("/tmp/runtime-downloads")
for name, item in lock["downloads"].items():
    with (root / name).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"], name
with tarfile.open(root / "node.tar.xz") as archive:
    archive.extractall("/tmp/node", filter="data")
shutil.copytree(Path("/tmp/node") / ("node-v" + lock["node"] + "-linux-x64"),
                "/usr/local", dirs_exist_ok=True)
with tarfile.open(root / "pnpm.tgz") as archive:
    archive.extractall("/opt/pnpm", filter="data")
os.symlink("/opt/pnpm/package/bin/pnpm.cjs", "/usr/local/bin/pnpm")
with zipfile.ZipFile(root / "chrome.zip") as archive:
    archive.extractall("/opt/chrome")
    for member in archive.infolist():
        target = Path("/opt/chrome") / member.filename
        if target.is_file():
            target.chmod((member.external_attr >> 16) & 0o777 or 0o644)
for name in ("chrome", "chrome_crashpad_handler", "chrome_sandbox"):
    (Path("/opt/chrome/chrome-linux64") / name).chmod(0o755)
