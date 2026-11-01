import assert from 'node:assert/strict';
import test from 'node:test';
import { buildDeckHtml } from './builder';
import { createGoldenOutline } from './golden-fixture';
import { adaptMobilePlayback, restoreOriginalPlaybackHtml, PlaybackCompatibilityError } from './mobile-playback';
import { createServer } from 'node:http';
import { chromium } from 'playwright-core';
import { checkMobilePlayback, checkInvisibleGlobals, checkCounterPause } from '../../../deploy/test/mobile-playback-check.mjs';
import legacy from './fixtures/mobile-playback-v1.json';
import { mobilePlaybackCss as v2Css, mobilePlaybackRuntime as v2Runtime, playbackRewrites as v2Rewrites } from './mobile-playback-v2';

test('mobile adapter rejects unknown, duplicate and forged runtimes', () => {
  for (const html of ['', '<html><head></head><script>unknown()</script></html>', '<!-- yuling-mobile-playback:v1 -->', '<style data-yuling-mobile="v1"></style>']) {
    assert.throws(() => adaptMobilePlayback(html), PlaybackCompatibilityError);
  }
});

test('browser QA transparent global backgrounds and completed sweep release with original phase', async () => {
  const html = (await buildDeckHtml(createGoldenOutline())).toString();
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    if (req.url === '/deck') {
      res.setHeader('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:");
      res.end(html);
    } else res.end('<meta name="viewport" content="width=device-width,initial-scale=1"><iframe style="position:fixed;inset:0;width:100%;height:100%;border:0" sandbox="allow-scripts allow-downloads" src="/deck"></iframe>');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const browser = await chromium.launch({ executablePath: process.env.PPT_CHROME_PATH, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] });
  try {
    const context = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 3, hasTouch: true, isMobile: true });
    const page = await context.newPage(); await page.goto(`http://127.0.0.1:${address.port}`);
    const frame = await (await page.waitForSelector('iframe')).contentFrame(); assert.ok(frame);
    await frame.waitForSelector('.slide.active');
    await checkInvisibleGlobals(frame);
    await context.close();
  } finally { await browser.close(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('browser QA mobile playback lifecycle through sandboxed share iframe', async () => {
  const html = await buildDeckHtml(createGoldenOutline());
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    if (req.url === '/deck') {
      res.setHeader('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:");
      // A frame can boot before its charts have measurable geometry. Exercise
      // the engine's real lazy SVG drawing when a chart first becomes visible.
      const deferredCharts = '<style>body[data-yuling-playback]:not(.yuling-playback-ready) figure.chart{display:none!important}</style>';
      res.end(adaptMobilePlayback(html.toString()).replace('</head>', deferredCharts + '</head>'));
    } else res.end('<meta name="viewport" content="width=device-width,initial-scale=1"><iframe style="position:fixed;inset:0;width:100%;height:100%;border:0" sandbox="allow-scripts allow-downloads" src="/deck"></iframe>');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const browser = await chromium.launch({ executablePath: process.env.PPT_CHROME_PATH, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] });
  try {
    await checkMobilePlayback(browser, `http://127.0.0.1:${address.port}`);
    await checkMobilePlayback(browser, `http://127.0.0.1:${address.port}`, 'reduce');
    await checkMobilePlayback(browser, `http://127.0.0.1:${address.port}`, 'no-preference', true, 1);
  } finally { await browser.close(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('browser QA global resource assertions reject retained layers and reset phases', async () => {
  const original = (await buildDeckHtml(createGoldenOutline())).toString();
  let html = original;
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(req.url === '/deck' ? html : '<iframe sandbox="allow-scripts" src="/deck"></iframe>');
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  const browser = await chromium.launch({ executablePath: process.env.PPT_CHROME_PATH, args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'] });
  try {
    for (const [from, to, reason] of [
      ["root.style.display = 'none';", "root.style.display = '';", /fully transparent background/],
      ["wipe.style.display = 'none';", "wipe.style.display = '';", /finished offscreen sweep/],
      ['animation.currentTime = phase.time + elapsed;', 'animation.currentTime = 0;', /preserve its original phase/],
      ["if (item.released || root.id === desiredBackground() || getComputedStyle(root).opacity !== '0') return;",
        'if (item.released) return;', /visible original background must remain|stale release must not hide/],
    ] as const) {
      const locations = from === 'animation.currentTime = phase.time + elapsed;' ? 2 : 1;
      assert.equal(original.split(from).length, locations + 1, 'deliberate fault must affect exactly the expected source locations');
      html = original.replaceAll(from, to);
      const context = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 3, hasTouch: true, isMobile: true });
      try {
        const page = await context.newPage(); await page.goto(`http://127.0.0.1:${address.port}`);
        const frame = await (await page.waitForSelector('iframe')).contentFrame(); assert.ok(frame);
        await frame.waitForSelector('.slide.active');
        await assert.rejects(checkInvisibleGlobals(frame), reason);
      } finally { await context.close(); }
    }
    const clock = 'task.callback(task.frame ? now - pausedTime : now);';
    assert.equal(original.split(clock).length, 2);
    html = original.replace(clock, 'task.callback(now);');
    const context = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 3, hasTouch: true, isMobile: true });
    try {
      const page = await context.newPage(); await page.goto(`http://127.0.0.1:${address.port}`);
      const frame = await (await page.waitForSelector('iframe')).contentFrame(); assert.ok(frame);
      await frame.waitForSelector('.slide.active');
      await assert.rejects(checkCounterPause(frame), /counter resumes without jumping/);
    } finally { await context.close(); }
  } finally { await browser.close(); await new Promise<void>(resolve => server.close(() => resolve())); }
});

test('real Python engine mobile adapter covers new and existing decks exactly once', async () => {
  const html = (await buildDeckHtml(createGoldenOutline())).toString();
  assert.ok(html.includes('<!-- yuling-mobile-playback:v3 -->'), 'new builds must retain original visuals with lifecycle v3');
  assert.equal(adaptMobilePlayback(html), html);
  assert.throws(() => adaptMobilePlayback(html + '<!-- yuling-mobile-playback:v3 -->'), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html + '<!-- yuling-mobile-playback:v2 -->'), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html + '<!-- yuling-mobile-playback:v1 -->'), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html.replace('const SETTLE_MS = 7000;', 'const SETTLE_MS = 7001;')), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html.replace('const token = ++generation;', 'const token = 0;')), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(html.replace('</head>', '</head></head>')), PlaybackCompatibilityError);
});

test('real Python engine restores known v1 work and upgrades without duplicate compatibility code', async () => {
  const html = (await buildDeckHtml(createGoldenOutline())).toString();
  const raw = restoreOriginalPlaybackHtml(html);
  const old = raw.replace('</head>', '<style data-yuling-mobile="v1">' + legacy.mobilePlaybackCss + '</style></head>')
    .replace('splitHeadingLines();', '<!-- yuling-mobile-playback:v1 -->\n' + legacy.mobilePlaybackRuntime + 'splitHeadingLines();');
  const upgraded = adaptMobilePlayback(old);
  assert.equal(upgraded, html, 'known v1 and fresh original content must produce identical v3 playback');
  assert.ok(upgraded.includes('<!-- yuling-mobile-playback:v3 -->'));
  assert.equal(upgraded.includes('light-v1'), false);
  assert.equal(adaptMobilePlayback(upgraded), upgraded);
});

test('real Python engine upgrades only exact known v2 content and rejects damaged compatibility', async () => {
  const html = (await buildDeckHtml(createGoldenOutline())).toString();
  const raw = restoreOriginalPlaybackHtml(html);
  let old = raw;
  for (const [original, changed] of v2Rewrites) old = old.replaceAll(original, changed);
  old = old.replace('</head>', '<style data-yuling-mobile="v2">' + v2Css + '</style></head>')
    .replace('splitHeadingLines();', '<!-- yuling-mobile-playback:v2 -->\n' + v2Runtime + 'splitHeadingLines();');
  assert.equal(restoreOriginalPlaybackHtml(old), raw);
  assert.equal(adaptMobilePlayback(old), html);
  assert.equal(adaptMobilePlayback(adaptMobilePlayback(old)), html);
  assert.throws(() => adaptMobilePlayback(old.replace('const token = ++generation;', 'const token = 0;')), PlaybackCompatibilityError);
  assert.throws(() => adaptMobilePlayback(old + '<!-- yuling-mobile-playback:v2 -->'), PlaybackCompatibilityError);
});
