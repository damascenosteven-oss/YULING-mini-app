import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, statSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import path from 'node:path';
import { isDeepStrictEqual } from 'node:util';

export function platformKey(platform = process.platform, architecture = process.arch) {
  if (platform === 'darwin' && architecture === 'arm64') return 'darwin-arm64';
  if (!['win32', 'linux'].includes(platform) || architecture !== 'x64') {
    throw new Error(`Unsupported visual platform: ${platform}/${architecture}`);
  }
  return `${platform}-${architecture}`;
}

export function baselineDirectory(root, platform = process.platform, architecture = process.arch) {
  return path.join(root, 'platforms', platformKey(platform, architecture));
}

export function loadBaselineManifest(directory) {
  const file = path.join(directory, 'manifest.json');
  if (!existsSync(file)) {
    if (path.basename(directory) === 'darwin-arm64') throw new Error('Mac visual baseline not established; capture candidates and obtain owner approval');
    throw new Error('Platform Golden manifest missing; stage approved candidate images first');
  }
  return JSON.parse(readFileSync(file, 'utf8'));
}

export function browserArguments(platform = process.platform) {
  platformKey(platform, platform === 'darwin' ? 'arm64' : 'x64');
  const args = ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'];
  return platform === 'win32' || platform === 'darwin' ? [...args, '--disable-gpu'] : args;
}

export function fontInventoryFingerprint(root, platform = process.platform) {
  platformKey(platform, 'x64');
  if (!existsSync(root) || !statSync(root).isDirectory()) throw new Error('Visual font directory missing');
  const entries = new Map();
  function visit(directory) {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      const full = path.join(directory, item.name);
      if (item.isDirectory()) {
        if (platform === 'linux') visit(full);
      } else if (statSync(full).isFile()
        && (platform !== 'win32' || ['.ttf', '.ttc', '.otf'].includes(path.extname(item.name).toLowerCase()))) {
        const relative = path.relative(root, full).split(path.sep).join('/');
        entries.set(relative, createHash('sha256').update(readFileSync(full)).digest('hex'));
      }
    }
  }
  visit(root);
  if (!entries.size) throw new Error('Visual font inventory is empty');
  const names = [...entries.keys()].sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
  return createHash('sha256').update(names.map(name => `${name}\0${entries.get(name)}\n`).join('')).digest('hex');
}

export function environmentSnapshot(browserPath, chromeVersion, playwrightVersion, args, viewport) {
  platformKey();
  const fonts = process.platform === 'win32' ? path.join(process.env.WINDIR || 'C:/Windows', 'Fonts') : '/usr/share/fonts';
  const snapshot = {
    platform: process.platform, architecture: process.arch, chromeVersion, playwrightVersion,
    browserSha256: createHash('sha256').update(readFileSync(browserPath)).digest('hex'),
    fontInventorySha256: process.platform === 'darwin'
      ? macFontFingerprint(JSON.parse(execFileSync('/usr/sbin/system_profiler', ['-json', 'SPFontsDataType'], { timeout: 60000, maxBuffer: 32 * 1024 * 1024, encoding: 'utf8' })))
      : fontInventoryFingerprint(fonts), browserArgs: args, viewport,
  };
  if (process.platform === 'darwin') {
    snapshot.macOS = execFileSync('/usr/bin/sw_vers', { timeout: 15000, encoding: 'utf8' }).trim();
    snapshot.fontInventoryMethod = 'system_profiler-SPFontsDataType-path-v1';
  }
  return snapshot;
}

export function macFontFingerprint(inventory) {
  const records = inventory?.SPFontsDataType;
  if (!Array.isArray(records) || !records.length) throw new Error('Mac font inventory is empty or unsupported');
  const entries = new Map();
  for (const record of records) {
    if (typeof record?.path !== 'string' || !path.isAbsolute(record.path)) throw new Error('Mac font inventory has a missing file path');
    const file = realpathSync(record.path);
    const relative = path.relative(homedir(), file);
    const name = (!relative.startsWith('..') && !path.isAbsolute(relative) ? `user/${relative}` : `root/${file.replace(/^\/+/, '')}`).split(path.sep).join('/');
    entries.set(name, createHash('sha256').update(readFileSync(file)).digest('hex'));
  }
  const names = [...entries.keys()].sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
  return createHash('sha256').update(names.map(name => `${name}\0${entries.get(name)}\n`).join('')).digest('hex');
}

export function baselineForCommand(command, root, platform = process.platform, architecture = process.arch) {
  platformKey(platform, architecture);
  if (command === 'geometry' || command === 'candidate') return null;
  if (!['check', 'rebaseline'].includes(command)) throw new Error(`Unknown command: ${command}`);
  const directory = baselineDirectory(root, platform, architecture);
  const manifest = loadBaselineManifest(directory);
  verifyBaselineImages(directory, manifest.pages);
  return { directory, manifest };
}

export function reserveCandidateDirectory(output) {
  let directory = path.resolve(output);
  const pending = [];
  while (!existsSync(directory)) {
    pending.unshift(path.basename(directory));
    directory = path.dirname(directory);
  }
  const resolved = path.join(realpathSync(directory), ...pending);
  if (existsSync(resolved)) throw new Error('Candidate output already exists; choose a new evidence directory');
  for (let parent = resolved; ; parent = path.dirname(parent)) {
    if (existsSync(path.join(parent, '.git'))) throw new Error('Candidate output must be outside Git repositories');
    if (parent === path.dirname(parent)) break;
  }
  mkdirSync(path.dirname(resolved), { recursive: true });
  mkdirSync(resolved);
  return resolved;
}

export function requireEnvironment(expected, actual) {
  if (!expected || typeof expected !== 'object') throw new Error('Platform baseline environment missing');
  for (const [key, value] of Object.entries(actual)) {
    if (!(key in expected) || !isDeepStrictEqual(expected[key], value)) {
      throw new Error(`Visual environment mismatch: ${key}; restore the approved environment`);
    }
  }
}

export function verifyBaselineImages(directory, pages) {
  if (!Array.isArray(pages) || !pages.length) throw new Error('Golden page list missing');
  for (const page of pages) {
    if (typeof page.file !== 'string' || path.basename(page.file) !== page.file || !page.file.endsWith('.png')) {
      throw new Error('Invalid Golden image filename');
    }
    const file = path.join(directory, page.file);
    if (!existsSync(file) || createHash('sha256').update(readFileSync(file)).digest('hex') !== page.sha256) {
      throw new Error(`Golden baseline integrity failed: ${page.file}`);
    }
  }
}
