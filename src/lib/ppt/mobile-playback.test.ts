import assert from 'node:assert/strict';
import test from 'node:test';
import { buildDeckHtml } from './builder';
import { createGoldenOutline } from './golden-fixture';
import { adaptMobilePlayback, PlaybackCompatibilityError } from './mobile-playback';
import { createServer } from 'node:http';
import { chromium } from 'playwright-core';
import { checkMobilePlayback } from '../../../deploy/test/mobile-playback-check.mjs';

test('mobile adapter rejects unknown, duplicate and forged runtimes', () => {
  for (const html of ['', '<html><head></head><script>unknown()</script></html>', '<!-- yuling-mobile-playback:v1 -->', '<style data-yuling-mobile="v1"></style>']) {
    assert.throws(() => adaptMobilePlayback(html), PlaybackCompatibilityError);
  }
});

test('browser QA mobile playback lifecycle through sandboxed share iframe', async () => {
  const html = await buildDeckHtml(createGoldenOutline());
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    if (req.url === '/deck') {
      res.setHeader('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:");
      res.end(adaptMobilePlayback(html.toString()));
    } else res.end('<meta name="viewport" content="width=device-width,initial-scale=1"><iframe style="position:fixed;inset:0;width:100%;height:100%;border:0" sandbox="allow-scripts allow-downloads" src="/deck"></iframe>');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const browser = await chromium.launch({ executablePath: process.env.PPT_CHROME_PATH, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] });
  try {
    await checkMobilePlayback(browser, `http://127.0.0.1:${address.port}`);
    await checkMobilePlayback(browser, `http://127.0.0.1:${address.port}`, 'reduce');
  } finally { await browser.close(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('real Python engine mobile adapter covers new and existing decks exactly once', async () => {
  const html = (await buildDeckHtml(createGoldenOutline())).toString();
  assert.ok(html.includes('<!-- yuling-mobile-playback:v1 -->'), 'new builds must use shared adapter');
  assert.equal(adaptMobilePlayback(html), html);
  assert.throws(() => adaptMobilePlayback(html + '<!-- yuling-mobile-playback:v1 -->'), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html.replace('const SETTLE_MS = 7000;', 'const SETTLE_MS = 7001;')), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html.replace('const token = ++generation;', 'const token = 0;')), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html.replace('</head>', '</head></head>')), PlaybackCompatibilityError);
});
