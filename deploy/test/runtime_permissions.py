"""Credential-free probe executed as the final image's ordinary application user."""

CHECK = r'''
import json, os
from pathlib import Path

root = Path('/opt/yuling')
cache = root / 'app/.next/cache'
if (os.getuid(), os.getgid()) != (10001, 10001):
    raise RuntimeError('runtime_user_mismatch')
def failed(error):
    raise error
files = 0
for directory, dirs, names in os.walk(root, followlinks=False, onerror=failed):
    for path in [Path(directory), *(Path(directory) / n for n in dirs + names)]:
        directory_path = path.is_dir()
        if not os.access(path, os.R_OK | (os.X_OK if directory_path else 0)):
            raise PermissionError('runtime_permission_denied')
        if not path.is_relative_to(cache) and os.access(path, os.W_OK):
            raise PermissionError('runtime_code_writable')
        files += not directory_path
if not files or not cache.is_dir() or not os.access(cache, os.W_OK):
    raise PermissionError('runtime_cache_not_writable')
print(json.dumps({'status': 'passed', 'uid': os.getuid(), 'files': files}))
'''
