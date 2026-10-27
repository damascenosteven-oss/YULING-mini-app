import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { access, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium, type Browser, type Page } from 'playwright-core';
import pixelmatch from 'pixelmatch';
import { PNG } from 'pngjs';
import { buildDeckHtml } from '../src/lib/ppt/builder';
import { createGoldenOutline, PPT_GOLDEN_TEMPLATE_VERSION, PPT_GOLDEN_VIEWPORT } from '../src/lib/ppt/golden-fixture';
import { browserCandidates } from '../src/lib/ppt/platform';
import { baselineForCommand, browserArguments, environmentSnapshot, requireEnvironment, reserveCandidateDirectory } from './ppt-golden-lib.mjs';

type Command = 'check' | 'geometry' | 'rebaseline' | 'candidate';
type Rect = { x: number; y: number; width: number; height: number; top: number; right: number; bottom: number; left: number };
type GeometryPage = {
  page: number;
  title: string;
  activeCount: number;
  content: { header: Rect | null; body: Rect | null; nav: Rect; brand: Rect };
  emphasis: Array<{ color: string; fill: string; animation: string; opacity: number }>;
  animated: Array<{ tag: string; entrance: string; transform: string; opacity: number; rect: Rect }>;
  roadmap: Rect[];
};
type Manifest = {
  schemaVersion: 1;
  templateVersion: number;
  createdAt: string;
  platform: string;
  architecture: string;
  chromeVersion: string;
  playwrightVersion: string;
  viewport: typeof PPT_GOLDEN_VIEWPORT;
  pageCount: number;
  pages: Array<{ page: number; file: string; sha256: string; geometry: GeometryPage }>;
  environment: ReturnType<typeof environmentSnapshot>;
  approval: Record<string, unknown>;
};

const ROOT = process.cwd();
const OUTPUT = path.join(ROOT, 'build', 'ppt-golden');
const command = (process.argv[2] || 'check') as Command;

function sha256(buffer: Buffer): string {
  return createHash('sha256').update(buffer).digest('hex');
}

async function exists(file: string): Promise<boolean> {
  try { await access(file); return true; } catch { return false; }
}

function chromePath(): string {
  const found = browserCandidates().find(candidate => existsSync(candidate));
  if (!found) throw new Error('Chrome or Edge was not found. Configure PPT_CHROME_PATH.');
  return found;
}

function playwrightVersion(): string {
  const packageJson = JSON.parse(readFileSync(path.join(ROOT, 'node_modules', 'playwright-core', 'package.json'), 'utf8')) as { version: string };
  return packageJson.version;
}

function overlaps(left: Rect, right: Rect, tolerance = 1): boolean {
  return left.right > right.left + tolerance && right.right > left.left + tolerance
    && left.bottom > right.top + tolerance && right.bottom > left.top + tolerance;
}

async function settle(page: Page, pageIndex: number): Promise<void> {
  await page.evaluate(`(() => {
    if (typeof show !== 'function') throw new Error('presentation runtime did not expose show()');
    show(${pageIndex}, true);
    document.querySelector('.slide.active')?.classList.add('settled');
    document.body.classList.add('is-settled');
    const hint = document.querySelector('#hint');
    if (hint) hint.style.display = 'none';
  })()`);
  if (await page.locator('.slide.active [data-count]').count()) await page.waitForTimeout(2300);
  await page.evaluate(`(async () => {
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    for (const animation of document.getAnimations()) {
      try {
        const timing = animation.effect?.getComputedTiming();
        animation.currentTime = timing && Number.isFinite(timing.endTime) ? Number(timing.endTime) : 0;
        animation.pause();
      } catch { /* decorative node may have detached */ }
    }
    document.querySelectorAll('[data-count]').forEach(element => {
      element.textContent = (element.dataset.count || '') + (element.dataset.suffix || '');
    });
    const particles = document.querySelector('#particles');
    particles?.getContext('2d')?.clearRect(0, 0, particles.width, particles.height);
    const play = document.querySelector('#play');
    if (play) play.textContent = '播放';
    await new Promise(resolve => requestAnimationFrame(resolve));
  })()`);
}

async function inspectGeometry(page: Page, pageNumber: number): Promise<GeometryPage> {
  return page.evaluate(`(() => {
    const currentPage = ${pageNumber};
    const roundRect = element => {
      const rect = element.getBoundingClientRect();
      const value = number => Math.round(number * 100) / 100;
      return { x: value(rect.x), y: value(rect.y), width: value(rect.width), height: value(rect.height), top: value(rect.top), right: value(rect.right), bottom: value(rect.bottom), left: value(rect.left) };
    };
    const active = document.querySelector('.slide.active');
    if (!active) throw new Error('page ' + currentPage + ': no active slide');
    const rectOrNull = selector => {
      const element = active.querySelector(selector);
      return element ? roundRect(element) : null;
    };
    return {
      page: currentPage,
      title: active.getAttribute('data-section') || '',
      activeCount: document.querySelectorAll('.slide.active').length,
      content: {
        header: rectOrNull('.ai-head'), body: rectOrNull('.ai-body'),
        nav: roundRect(document.querySelector('#nav')), brand: roundRect(document.querySelector('#brand')),
      },
      emphasis: [...active.querySelectorAll(':scope.ai-content .grad-text')].map(element => {
        const style = getComputedStyle(element);
        return { color: style.color, fill: style.webkitTextFillColor, animation: style.animationName, opacity: Number(style.opacity) };
      }),
      animated: [...active.querySelectorAll('[data-a]')].map(element => {
        const style = getComputedStyle(element);
        return { tag: element.tagName.toLowerCase(), entrance: element.getAttribute('data-a') || '', transform: style.transform, opacity: Number(style.opacity), rect: roundRect(element) };
      }),
      roadmap: [...active.querySelectorAll('.ai-roadmap article')].map(roundRect),
    };
  })()`) as Promise<GeometryPage>;
}

function geometryProblems(snapshot: GeometryPage): string[] {
  const problems: string[] = [];
  if (snapshot.activeCount !== 1) problems.push(`active slide count is ${snapshot.activeCount}`);
  snapshot.animated.forEach((item, index) => {
    if (!(item.transform === 'none' || item.transform === 'matrix(1, 0, 0, 1, 0, 0)')) problems.push(`[data-a] ${index + 1} retains transform ${item.transform}`);
    if (item.opacity < 0.94) problems.push(`[data-a] ${index + 1} remains transparent (${item.opacity})`);
    if (item.rect.left < -1 || item.rect.top < -1 || item.rect.right > PPT_GOLDEN_VIEWPORT.width + 1 || item.rect.bottom > PPT_GOLDEN_VIEWPORT.height + 1) problems.push(`[data-a] ${index + 1} is outside the stage`);
  });
  snapshot.emphasis.forEach((item, index) => {
    if (item.animation !== 'none') problems.push(`emphasis ${index + 1} has animation ${item.animation}`);
    if (item.fill === 'transparent' || item.color === 'rgba(0, 0, 0, 0)') problems.push(`emphasis ${index + 1} is transparent`);
  });
  const { header, body, nav, brand } = snapshot.content;
  if (header && body && overlaps(header, body)) problems.push('header overlaps body');
  if (body && overlaps(body, nav)) problems.push('body overlaps navigation');
  if (!overlaps(brand, nav, 0)) problems.push('brand is outside navigation');
  if (snapshot.roadmap.length) {
    if (snapshot.roadmap.length !== 4) problems.push(`roadmap card count is ${snapshot.roadmap.length}`);
    snapshot.roadmap.forEach((card, index) => {
      if (card.bottom > nav.top - 1) problems.push(`roadmap card ${index + 1} enters navigation`);
      snapshot.roadmap.slice(index + 1).forEach((other, otherIndex) => {
        if (overlaps(card, other)) problems.push(`roadmap cards ${index + 1} and ${index + otherIndex + 2} overlap`);
      });
    });
  }
  return problems;
}

async function capturePage(browser: Browser, htmlUrl: string, pageIndex: number, destination: string): Promise<GeometryPage> {
  const page = await browser.newPage({ viewport: PPT_GOLDEN_VIEWPORT, deviceScaleFactor: 1, reducedMotion: 'no-preference' });
  try {
    await page.addInitScript({ content: `let __goldenRandomState = 0x6d2b79f5; Math.random = () => { __goldenRandomState = Math.imul(__goldenRandomState ^ __goldenRandomState >>> 15, __goldenRandomState | 1); __goldenRandomState ^= __goldenRandomState + Math.imul(__goldenRandomState ^ __goldenRandomState >>> 7, __goldenRandomState | 61); return ((__goldenRandomState ^ __goldenRandomState >>> 14) >>> 0) / 4294967296; };` });
    await page.goto(htmlUrl, { waitUntil: 'load' });
    await page.waitForSelector('.slide');
    await settle(page, pageIndex);
    const snapshot = await inspectGeometry(page, pageIndex + 1);
    await page.screenshot({ path: destination });
    return snapshot;
  } finally {
    await page.close();
  }
}

export async function captureAll(browser: Browser, htmlPath: string, destination: string): Promise<Array<{ file: string; buffer: Buffer; geometry: GeometryPage }>> {
  await mkdir(destination, { recursive: true });
  const htmlUrl = pathToFileURL(htmlPath).href;
  const captured: Array<{ file: string; buffer: Buffer; geometry: GeometryPage }> = [];
  for (let index = 0; index < createGoldenOutline().slides.length; index += 1) {
    const file = `page-${String(index + 1).padStart(2, '0')}.png`;
    const output = path.join(destination, file);
    const geometry = await capturePage(browser, htmlUrl, index, output);
    const problems = geometryProblems(geometry);
    if (problems.length) throw new Error(`Golden geometry failed on page ${index + 1}: ${problems.join('; ')}`);
    captured.push({ file, buffer: await readFile(output), geometry });
  }
  return captured;
}

export function strictDiff(expectedBuffer: Buffer, actualBuffer: Buffer): { pixels: number; image: PNG } {
  const expected = PNG.sync.read(expectedBuffer);
  const actual = PNG.sync.read(actualBuffer);
  if (expected.width !== actual.width || expected.height !== actual.height) throw new Error('PNG dimensions differ');
  let pixels = 0;
  for (let offset = 0; offset < expected.data.length; offset += 4) {
    if (expected.data[offset] !== actual.data[offset] || expected.data[offset + 1] !== actual.data[offset + 1]
      || expected.data[offset + 2] !== actual.data[offset + 2] || expected.data[offset + 3] !== actual.data[offset + 3]) pixels += 1;
  }
  const diff = new PNG({ width: expected.width, height: expected.height });
  pixelmatch(expected.data, actual.data, diff.data, expected.width, expected.height, { threshold: 0, includeAA: true, alpha: 0.25, diffColor: [255, 0, 0], diffColorAlt: [255, 0, 0] });
  return { pixels, image: diff };
}

function mutateHtml(html: string, mutation: 'rotate' | 'gradient'): string {
  if (mutation === 'rotate') {
    const start = html.indexOf('@keyframes a-stamp');
    const finalStart = html.indexOf('100%', start);
    const finalEnd = html.indexOf('}', finalStart);
    if (start < 0 || finalStart < 0 || finalEnd < 0) throw new Error('stamp final frame not found for mutation');
    const finalFrame = html.slice(finalStart, finalEnd + 1).replace(/transform\s*:\s*none/, 'transform:rotate(-4deg)');
    if (finalFrame === html.slice(finalStart, finalEnd + 1)) throw new Error('stamp final transform not found for mutation');
    return html.slice(0, finalStart) + finalFrame + html.slice(finalEnd + 1);
  }
  const stable = '.slide.ai-content .grad-text{background:none;color:var(--theme-solid);-webkit-text-fill-color:var(--theme-solid);animation:none}';
  if (!html.includes(stable)) throw new Error('stable emphasis rule not found for mutation');
  return html.replace(stable, '.slide.ai-content .grad-text{color:transparent;-webkit-text-fill-color:transparent;animation:gradFlow 1s linear infinite}');
}

async function mutationMustFail(browser: Browser, html: string, mutation: 'rotate' | 'gradient', directory: string): Promise<void> {
  const mutatedPath = path.join(directory, `mutated-${mutation}.html`);
  await writeFile(mutatedPath, mutateHtml(html, mutation));
  try {
    await captureAll(browser, mutatedPath, path.join(directory, `mutated-${mutation}`));
  } catch {
    return;
  }
  throw new Error(`Anti-false-green mutation was not detected: ${mutation}`);
}

async function main(): Promise<void> {
  if (!['check', 'geometry', 'rebaseline', 'candidate'].includes(command)) throw new Error(`Unknown command: ${command}`);
  if (command === 'candidate') {
    const outputIndex = process.argv.indexOf('--output');
    if (outputIndex < 0 || !process.argv[outputIndex + 1]) throw new Error('Candidate requires --output <new directory outside repositories>');
    await captureCandidate(reserveCandidateDirectory(process.argv[outputIndex + 1]));
    return;
  }
  if (command === 'rebaseline' && !process.argv.includes('--approve-current-visual')) throw new Error('Rebaseline requires --approve-current-visual');
  const target = baselineForCommand(command, path.join(ROOT, 'tests', 'ppt-golden', 'baseline'));
  const BASELINE = target?.directory;
  const manifest = target?.manifest as Manifest | undefined;
  const chrome = chromePath();
  if (!await exists(chrome)) throw new Error(`Chrome not found: ${chrome}`);
  await rm(OUTPUT, { recursive: true, force: true });
  await mkdir(OUTPUT, { recursive: true });
  const html = (await buildDeckHtml(createGoldenOutline())).toString('utf8');
  const htmlPath = path.join(OUTPUT, 'golden.html');
  await writeFile(htmlPath, html);
  const args = browserArguments();
  const browser = await chromium.launch({ executablePath: chrome, headless: true, args });
  try {
    const version = browser.version();
    const environment = command === 'geometry' ? undefined : environmentSnapshot(chrome, version, playwrightVersion(), args, PPT_GOLDEN_VIEWPORT);
    if (manifest) requireEnvironment(manifest.environment, environment);
    const captured = await captureAll(browser, htmlPath, path.join(OUTPUT, 'candidate'));
    if (command === 'geometry') {
      console.log(`PPT golden geometry passed: ${captured.length} pages`);
      return;
    }
    if (!manifest || !BASELINE || !environment) throw new Error('Platform baseline environment missing');
    if (command === 'rebaseline') {
      // Geometry may be refreshed only when captures equal the staged approved images.
      const pages: Manifest['pages'] = [];
      for (const item of captured) {
        const approved = manifest.pages.find(page => page.file === item.file);
        if (!approved || approved.sha256 !== sha256(item.buffer)) throw new Error(`Capture differs from approved candidate: ${item.file}`);
        pages.push({ page: item.geometry.page, file: item.file, sha256: sha256(item.buffer), geometry: item.geometry });
      }
      const updated: Manifest = {
        ...manifest,
        schemaVersion: 1, templateVersion: PPT_GOLDEN_TEMPLATE_VERSION, createdAt: new Date().toISOString(),
        platform: process.platform, architecture: process.arch, chromeVersion: version, playwrightVersion: playwrightVersion(),
        viewport: PPT_GOLDEN_VIEWPORT, pageCount: captured.length, pages, environment,
      };
      await writeFile(path.join(BASELINE, 'manifest.json'), `${JSON.stringify(updated, null, 2)}\n`);
      console.log(`PPT approved geometry recorded: ${captured.length} pages; images unchanged`);
      return;
    }
    const runtime = { platform: process.platform, architecture: process.arch, chromeVersion: version, playwrightVersion: playwrightVersion() };
    for (const key of Object.keys(runtime) as Array<keyof typeof runtime>) {
      if (manifest[key] !== runtime[key]) throw new Error(`Golden runtime mismatch for ${key}: expected ${manifest[key]}, got ${runtime[key]}`);
    }
    if (manifest.templateVersion !== PPT_GOLDEN_TEMPLATE_VERSION || manifest.pageCount !== captured.length
      || manifest.viewport.width !== PPT_GOLDEN_VIEWPORT.width || manifest.viewport.height !== PPT_GOLDEN_VIEWPORT.height) throw new Error('Golden manifest does not match the current template contract');
    const failures: Array<{ index: number; pixels: number }> = [];
    for (let index = 0; index < captured.length; index += 1) {
      const expectedMeta = manifest.pages[index];
      const expected = await readFile(path.join(BASELINE, expectedMeta.file));
      if (sha256(expected) !== expectedMeta.sha256) throw new Error(`Golden baseline integrity failed: ${expectedMeta.file}`);
      if (JSON.stringify(expectedMeta.geometry) !== JSON.stringify(captured[index].geometry)) throw new Error(`Golden geometry changed on page ${index + 1}`);
      const result = strictDiff(expected, captured[index].buffer);
      if (result.pixels) {
        await writeFile(path.join(OUTPUT, `diff-${String(index + 1).padStart(2, '0')}.png`), PNG.sync.write(result.image));
        failures.push({ index, pixels: result.pixels });
      }
    }
    if (failures.length) {
      const persistent: typeof failures = [];
      const retryDirectory = path.join(OUTPUT, 'retry');
      await mkdir(retryDirectory, { recursive: true });
      for (const failure of failures) {
        const file = manifest.pages[failure.index].file;
        const destination = path.join(retryDirectory, file);
        const geometry = await capturePage(browser, pathToFileURL(htmlPath).href, failure.index, destination);
        const result = strictDiff(await readFile(path.join(BASELINE, file)), await readFile(destination));
        if (geometryProblems(geometry).length || result.pixels) persistent.push({ index: failure.index, pixels: result.pixels });
      }
      if (persistent.length) throw new Error(`Golden pixel mismatch: ${persistent.map(item => `page ${item.index + 1} (${item.pixels} pixels)`).join(', ')}; see ${OUTPUT}`);
    }
    await mutationMustFail(browser, html, 'rotate', OUTPUT);
    await mutationMustFail(browser, html, 'gradient', OUTPUT);
    console.log(`PPT golden passed: ${captured.length} pages, zero pixel difference, 2 mutations rejected`);
  } finally {
    await browser.close();
  }
}

function sourceRecord(root: string): { commit: string; dirty: boolean } {
  return {
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    dirty: Boolean(execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim()),
  };
}

async function captureCandidate(output: string): Promise<void> {
  const engine = process.env.PPT_ENGINE_ROOT;
  if (!engine) throw new Error('Candidate requires an explicit PPT_ENGINE_ROOT');
  const sources = { app: sourceRecord(ROOT), engine: sourceRecord(engine) };
  const report: Record<string, unknown> = { status: 'incomplete', approved: false, sources, nodeVersion: process.version };
  try {
    if (sources.app.dirty || sources.engine.dirty) throw new Error('Candidate capture requires clean source commits');
    const html = (await buildDeckHtml(createGoldenOutline())).toString('utf8');
    const htmlPath = path.join(output, 'golden.html');
    await writeFile(htmlPath, html);
    const chrome = chromePath();
    const args = browserArguments();
    const runs: Awaited<ReturnType<typeof captureAll>>[] = [];
    let firstEnvironment: ReturnType<typeof environmentSnapshot> | undefined;
    for (const name of ['candidate-a', 'candidate-b']) {
      const browser = await chromium.launch({ executablePath: chrome, headless: true, args });
      try {
        const environment = environmentSnapshot(chrome, browser.version(), playwrightVersion(), args, PPT_GOLDEN_VIEWPORT);
        if (environment.chromeVersion !== '152.0.7977.64' || environment.playwrightVersion !== '1.64.0') throw new Error('Candidate requires Chrome 152.0.7977.64 and Playwright 1.64.0');
        if (firstEnvironment) requireEnvironment(firstEnvironment, environment);
        firstEnvironment = environment;
        const captures = await captureAll(browser, htmlPath, path.join(output, name));
        if (captures.length !== 12) throw new Error('Candidate requires all 12 pages');
        runs.push(captures);
        await writeFile(path.join(output, name, 'capture.json'), JSON.stringify({ environment, pages: captures.map(item => ({ file: item.file, sha256: sha256(item.buffer), geometry: item.geometry })) }, null, 2));
      } finally {
        await browser.close();
      }
    }
    const differences = [];
    for (let index = 0; index < runs[0].length; index += 1) {
      const a = runs[0][index];
      const b = runs[1][index];
      const diff = strictDiff(a.buffer, b.buffer);
      if (diff.pixels || sha256(a.buffer) !== sha256(b.buffer) || JSON.stringify(a.geometry) !== JSON.stringify(b.geometry)) {
        differences.push({ page: index + 1, pixels: diff.pixels });
        await writeFile(path.join(output, `diff-${index + 1}.png`), PNG.sync.write(diff.image));
      }
    }
    report.differences = differences;
    report.environment = firstEnvironment;
    if (differences.length) throw new Error('Independent candidate captures differ; evidence retained');
    if (JSON.stringify(sources) !== JSON.stringify({ app: sourceRecord(ROOT), engine: sourceRecord(engine) })) throw new Error('Source changed during candidate capture');
    report.status = 'repeatable; owner review required';
    console.log('PPT candidate repeatability passed: 12 pages; owner approval still required');
  } catch (error) {
    report.failure = error instanceof Error ? error.message : String(error);
    throw error;
  } finally {
    await writeFile(path.join(output, 'candidate.json'), JSON.stringify(report, null, 2));
  }
}

if (['ppt-golden.ts', 'ppt-golden.js', 'ppt-golden.mjs'].includes(path.basename(process.argv[1] || ''))) {
  main().catch(error => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
