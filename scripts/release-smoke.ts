import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { chromium } from 'playwright-core';
import { buildDeckHtml } from '../src/lib/ppt/builder';
import { createGoldenOutline, PPT_GOLDEN_VIEWPORT } from '../src/lib/ppt/golden-fixture';
import { qualityCheckDeck } from '../src/lib/ppt/qa';
import { captureAll, strictDiff } from './ppt-golden';
import { browserArguments, environmentSnapshot } from './ppt-golden-lib.mjs';

const hash = (data: Buffer) => createHash('sha256').update(data).digest('hex');

async function main() {
  const mode = process.argv[2];
  assert.ok(mode === 'quick' || mode === 'repeat', 'Use quick or repeat');
  const release = JSON.parse(await readFile('/opt/yuling/release.json', 'utf8'));
  const lock = JSON.parse(await readFile('/opt/yuling/runtime-lock.json', 'utf8'));
  assert.equal(process.versions.node, lock.node);
  assert.equal(release.engine_sha, lock.engine_sha);
  const runtimeRequire = createRequire(path.join(process.cwd(), 'package.json'));
  assert.equal(runtimeRequire('playwright-core/package.json').version, lock.playwright);
  const python = process.env.PPT_PYTHON_PATH;
  const chrome = process.env.PPT_CHROME_PATH;
  assert.ok(python && chrome, 'Explicit Python and Chrome paths are required');
  assert.equal(execFileSync(python, ['-c', 'import sys,PIL; print(sys.version.split()[0], PIL.__version__)'],
    { encoding: 'utf8' }).trim(), lock.python + ' ' + lock.pillow);
    const html = await buildDeckHtml(createGoldenOutline());
    const qa = await qualityCheckDeck(html);
    assert.equal(qa.report.pages, 12);
    if (mode === 'quick') {
      console.log(JSON.stringify({ status: 'passed', pages: 12, source: release, externalProvidersTested: false }));
      return;
    }
    const output = process.argv[3];
    assert.ok(output && path.isAbsolute(output), 'Repeat requires a new absolute evidence directory');
    await mkdir(output, { recursive: false });
    const htmlFile = path.join(output, 'golden.html');
    await writeFile(htmlFile, html);
    const captures: Awaited<ReturnType<typeof captureAll>>[] = [];
    const environments = [];
    for (const name of ['candidate-a', 'candidate-b']) {
      const args = browserArguments();
      const browser = await chromium.launch({ executablePath: chrome, headless: true, args });
      try {
        assert.equal(browser.version(), lock.chrome);
        const environment = environmentSnapshot(chrome, browser.version(), lock.playwright, args, PPT_GOLDEN_VIEWPORT);
        environments.push(environment);
        const pages = await captureAll(browser, htmlFile, path.join(output, name));
        assert.equal(pages.length, 12);
        captures.push(pages);
        await writeFile(path.join(output, name, 'capture.json'), JSON.stringify({
          environment, pages: pages.map(page => ({ file: page.file, sha256: hash(page.buffer), geometry: page.geometry })),
        }, null, 2));
      } finally {
        await browser.close();
      }
    }
    assert.deepEqual(environments[0], environments[1]);
    const differences = captures[0].flatMap((first, index) => {
      const second = captures[1][index];
      const pixels = strictDiff(first.buffer, second.buffer).pixels;
      return pixels || hash(first.buffer) !== hash(second.buffer)
        || JSON.stringify(first.geometry) !== JSON.stringify(second.geometry)
        ? [{ page: index + 1, pixels }] : [];
    });
    await writeFile(path.join(output, 'result.json'), JSON.stringify({
      approved: false, source: release, environment: environments[0], pages: 12,
      differences, externalProvidersTested: false,
    }, null, 2));
    assert.equal(differences.length, 0, 'Independent packaged captures differ; evidence retained');
    console.log('Packaged candidate: two independent 12-page captures, zero differences; owner review required');
}

main().catch(error => {
  console.error(error instanceof Error ? error.message : 'Packaged smoke check failed');
  process.exitCode = 1;
});
