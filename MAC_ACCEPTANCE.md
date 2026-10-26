# Mac M5 owner handoff — Issue #1

Status: **Issue #7 Mac repeatability retest pending; no Mac visual target approved or adopted**.
The owner reported partial native M5 checks at the preceding SHA; developer-side
evidence for this follow-up is Windows only. See Issue #7 for the owner report.
Windows/WSL2 tests of routing and error handling do not establish Mac acceptance.
Run this procedure on native Apple Silicon, outside Rosetta, using synthetic data.

## Exact candidate sources and tools

- Engine code: `be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192` (PR #5).
- Application code: `005c7726de9af287f6059b239ea2cb06bb2a64ff` (PR #6).
- Python 3.12, uv **0.13.4**, Pillow **13.0.0**, Python Playwright **1.60.0**, pytest **9.1.1**.
- Native Node **22.23.3**, pnpm **9.0.0**, application playwright-core **1.64.0**.
- Chrome for Testing **152.0.7977.64**, mac-arm64; viewport **1920×1080**.
- Engine launch arguments: `--disable-gpu --force-color-profile=srgb --disable-lcd-text --disable-partial-raster`.
- Application Mac arguments: `--no-sandbox --disable-dev-shm-usage --font-render-hinting=none --disable-gpu`.

The two SHAs above are the local regression pair. Later report-only commits must
be identified separately. If source changes, record the new pair and repeat the
affected checks. The formal application engine lock is deliberately unchanged
until the engine's final approved merge SHA is available.

## Prepare an independent workspace

Use a new terminal with native Python 3.12 and Node/pnpm versions above available.
The following commands use Bash; execute them in one Bash session. Do not use an
existing output directory. No command changes system fonts or replaces a browser.

```bash
set -euo pipefail
test "$(uname -m)" = arm64
python3.12 -c 'import platform,sys; assert platform.machine() == "arm64"; assert sys.version_info[:2] == (3, 12)'
test "$(node -p 'process.arch')" = arm64
test "$(node --version)" = v22.23.3
test "$(pnpm --version)" = 9.0.0
export WORK="$(mktemp -d "$HOME/ppt-issue1-mac.XXXXXX")"
export TOOLS="$WORK/tools" EVIDENCE="$WORK/evidence"
mkdir "$TOOLS" "$EVIDENCE"
git clone https://github.com/YuLing-Ai-Tech/yuling-ai-ppt.git "$WORK/yuling-ai-ppt"
git clone https://github.com/YuLing-Ai-Tech/mini-app.git "$WORK/mini-app"
git -C "$WORK/yuling-ai-ppt" switch --detach be73ccd4e811bd877fb2635fd7dfc3ca3ad8e192
git -C "$WORK/mini-app" switch --detach 005c7726de9af287f6059b239ea2cb06bb2a64ff
git -C "$WORK/yuling-ai-ppt" rev-parse HEAD
git -C "$WORK/mini-app" rev-parse HEAD
test -z "$(git -C "$WORK/yuling-ai-ppt" status --porcelain)"
test -z "$(git -C "$WORK/mini-app" status --porcelain)"
```

Read each clone's AGENTS.md/SECURITY.md before continuing. Record any rule change.
The detached checkouts here are owner-operated read-only validation clones, not
development worktrees. Do not edit or commit from them.

### Bootstrap the fixed uv without using an older uv

Official PyPI metadata: <https://pypi.org/pypi/uv/0.13.4/json>.
The wheel URL and SHA below were checked against that metadata on 2026-10-21;
native execution remains to be verified by the owner. Python's standard library
extracts just the uv executable; it does not install bootstrap pip dependencies.

```bash
curl --fail --location --proto '=https' \
  'https://files.pythonhosted.org/packages/26/44/5a8733dd1b2e8d6f9cffd1ff6428a3e11dcc7e146a7657e32cfb8d9fb4a4/uv-0.13.4-py3-none-macosx_11_0_arm64.whl' \
  --output "$TOOLS/uv.whl"
python3.12 - <<'PY'
import hashlib, os, pathlib, zipfile
root = pathlib.Path(os.environ['TOOLS'])
wheel = root / 'uv.whl'
assert hashlib.sha256(wheel.read_bytes()).hexdigest() == '95f4eb2b991b53b50ec2b18ab612fca8ba1e7a75a47af0331fb8bcd21da3eb03'
with zipfile.ZipFile(wheel) as archive:
    matches = [name for name in archive.namelist() if name.endswith('/scripts/uv')]
    assert len(matches) == 1, 'Unexpected official wheel layout; stop'
    executable = root / 'uv'
    executable.write_bytes(archive.read(matches[0]))
    executable.chmod(0o700)
print(hashlib.sha256(executable.read_bytes()).hexdigest())
PY
test "$("$TOOLS/uv" --version | cut -d ' ' -f 2)" = 0.13.4
export PATH="$TOOLS:$PATH" UV_CACHE_DIR="$TOOLS/cache"
uv venv --python 3.12 "$TOOLS/builder"
uv pip install --python "$TOOLS/builder/bin/python" Pillow==13.0.0
uv venv --python 3.12 "$TOOLS/tests"
uv pip install --python "$TOOLS/tests/bin/python" -r "$WORK/yuling-ai-ppt/requirements-test.txt"
uv venv --python 3.12 "$TOOLS/audit"
uv pip install --python "$TOOLS/audit/bin/python" pip-audit==2.10.1 uv==0.13.4
export PPT_ENGINE_ROOT="$WORK/yuling-ai-ppt"
export PPT_PYTHON_PATH="$TOOLS/builder/bin/python"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 NEXT_TELEMETRY_DISABLED=1
```

### Official browser and native environment

Verified official version metadata (mac-arm64 entry):
<https://googlechromelabs.github.io/chrome-for-testing/152.0.7977.64.json>.
The archive source was reachable; no Mac runtime result is claimed here.
Keep TLS and macOS platform security enabled. If native launch is blocked, record
the error and resolve through the owner's normal installation process.

```bash
curl --fail --location --proto '=https' \
  'https://storage.googleapis.com/chrome-for-testing-public/152.0.7977.64/mac-arm64/chrome-mac-arm64.zip' \
  --output "$TOOLS/chrome.zip"
ditto -x -k "$TOOLS/chrome.zip" "$TOOLS/chrome"
export PPT_CHROME_PATH="$TOOLS/chrome/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
test -f "$PPT_CHROME_PATH"
sw_vers > "$EVIDENCE/macos.txt"
uname -a >> "$EVIDENCE/macos.txt"
file "$PPT_CHROME_PATH" > "$EVIDENCE/browser-architecture.txt"
"$PPT_CHROME_PATH" --version > "$EVIDENCE/browser-version.txt"
shasum -a 256 "$TOOLS/uv.whl" "$TOOLS/uv" "$TOOLS/chrome.zip" "$PPT_CHROME_PATH" > "$EVIDENCE/tool-hashes.txt"
/usr/sbin/system_profiler -json SPFontsDataType > "$EVIDENCE/fonts-private.json"
```

Keep raw font paths and system inventory local. Candidate manifests record an
aggregate fingerprint of **registered font files**, including extra libraries.
Missing/unreadable font paths or an unsupported profiler schema are blocking;
do not replace the inventory with a smaller default-directory scan.

## Security gate first

```bash
for target in builder tests audit; do
  site="$TOOLS/$target/lib/python3.12/site-packages"
  test -d "$site"
  "$TOOLS/audit/bin/python" -m pip_audit --path "$site" --format json \
    > "$EVIDENCE/audit-$target.json"
  "$TOOLS/$target/bin/python" -c 'import sys, importlib.metadata as m; print(sys.executable); print(sorted((d.metadata["Name"], d.version) for d in m.distributions()))' \
    > "$EVIDENCE/runtime-$target.txt"
done
cd "$WORK/mini-app"
pnpm install --frozen-lockfile 2>&1 | tee "$EVIDENCE/install.log"
pnpm audit --json > "$EVIDENCE/audit-app-all.json"
pnpm audit --prod --json > "$EVIDENCE/audit-app-production.json"
cd "$WORK/yuling-ai-ppt"
uv run --no-project --python 3.12 --with playwright==1.60.0 --with pillow==13.0.0 --with pytest==9.1.1 python - <<'PY'
import importlib.metadata as md, json, os, pathlib, subprocess, sys
out = pathlib.Path(os.environ['EVIDENCE'])
packages = [(d.metadata['Name'], d.version, str(d.locate_file(''))) for d in md.distributions()]
(out / 'ci-runtime-private.json').write_text(json.dumps({'python': sys.executable, 'packages': packages}, indent=2))
command = [os.environ['TOOLS'] + '/audit/bin/python', '-m', 'pip_audit', '--format', 'json']
for directory in sorted({row[2] for row in packages}):
    command.extend(['--path', directory])
with (out / 'audit-ci.json').open('x') as stream:
    result = subprocess.run(command, stdout=stream)
assert result.returncode == 0, 'CI overlay audit failed'
data = json.loads((out / 'audit-ci.json').read_text())
assert all(not item.get('vulns') and not item.get('skip_reason') for item in data['dependencies'])
PY
```

Every audit must exit 0 with no findings and no skipped dependency. Network or
database errors block acceptance. The final command audits the actual `uv run`
overlay used by ci.sh, separately from the builder and standalone test environment.

## Phase 1: run, measure and collect candidates

```bash
cd "$WORK/yuling-ai-ppt"
export PYTEST_ADDOPTS="--basetemp=$EVIDENCE/fast-tmp"
./tools/ci.sh --fast 2>&1 | tee "$EVIDENCE/engine-fast.log"
unset PYTEST_ADDOPTS
"$TOOLS/tests/bin/python" tools/check_line_limits.py
"$TOOLS/tests/bin/python" tools/regress.py candidate --suite 图元样板 --work "$EVIDENCE/engine-candidate" \
  2>&1 | tee "$EVIDENCE/engine-candidate.log"
cd "$WORK/mini-app"
pnpm validate 2>&1 | tee "$EVIDENCE/validate.log"
pnpm test:portable 2>&1 | tee "$EVIDENCE/portable.log"
pnpm test:ppt 2>&1 | tee "$EVIDENCE/integration.log"
pnpm test:ppt:golden:geometry 2>&1 | tee "$EVIDENCE/geometry.log"
for attempt in 1 2; do
  pnpm exec tsx scripts/ppt-golden.ts candidate --output "$EVIDENCE/app-candidate-$attempt" \
    2>&1 | tee "$EVIDENCE/app-candidate-$attempt.log"
done
pnpm build 2>&1 | tee "$EVIDENCE/build.log"
```

Expect 9 engine pages and two complete app candidate commands. Each app command
captures all 12 pages twice in independent browser launches. Require
zero repeat differences, and all geometry checks passing. Candidate capture
does not approve or adopt any PNG. It refuses existing/in-repository output,
dirty sources, incorrect browser/Playwright, incomplete fonts and inconsistent
captures; failed evidence remains available. Never choose one successful repeat
and discard a differing capture.

Run these full/formal commands separately and retain their exit codes even in
phase 1:

```bash
cd "$WORK/yuling-ai-ppt"
"$TOOLS/tests/bin/python" -m pytest tests -q --basetemp="$EVIDENCE/full-tmp" --junitxml="$EVIDENCE/full.xml"
"$TOOLS/tests/bin/python" tools/regress.py engine --suite 图元样板 --work "$EVIDENCE/engine-formal"
cd "$WORK/mini-app"
pnpm test:ppt:golden
```

**Before Mac adoption, formal pixel checks must fail with “Mac visual baseline
not established”; the full engine suite cannot be counted as passing.** Other
failures must be diagnosed separately. Do not skip the failing tests or use
Windows/Linux PNGs. Cross-repository tests exercise real Chinese/long-content
DeckOutline → Python → HTML → browser QA and real Python failure propagation.
The new Python image tests cover RGB/RGBA, resizing, lossless QR and corrupt input.

## Phase 2: owner approval and final acceptance

Owner reviews all 9+12 Mac candidate-a pages, repeat comparison, geometry and
environment evidence. Record a GitHub approval explicitly naming both source
SHAs, candidate/manifest hashes, date and scope. Only then prepare a separate
reviewed adoption change for `platforms/darwin-arm64` with the original PNG bytes.
Do not run automatic rebaseline or change existing platform images.

After adoption, use the newly recorded exact pair and fresh evidence directories;
rerun every command above. Require complete engine suite **zero failed/errors/
skipped**, nine-page zero pixel difference, repeatability and color mutation only
on pages 4/5; application integration, 12-page geometry/pixels, rotation/gradient
rejection, validation/build and all audits pass. Use collected counts rather than
assuming prior counts. Record command, exit code, source/tool hashes and log SHA256.

Mac acceptance, remote CI, Architect/owner approval and final engine-lock pairing
remain mandatory. Engine merges first by owner approval; then update the app lock
to its actual merge SHA, rerun the pair and review the app PR. No merge/deployment
authorization is implied by this handoff.
