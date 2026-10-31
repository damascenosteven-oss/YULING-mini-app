import assert from 'node:assert/strict';
/* global window, document, HTMLCanvasElement, getComputedStyle, show, openMap, closeMap, slides, current, hasHiddenStep, advance, toggleAutoplay, autoplayTimer, PageTransitionEvent */

// Browser-level gestures can navigate the parent instead of firing deck controls.
async function checkSwipes(context, page, frame) {
  const startUrl = page.url();
  const stage = frame.locator('#stage');
  await frame.evaluate(() => show(0, true));
  const box = await stage.boundingBox();
  assert.ok(box && box.width > 0 && box.height > 0);
  const cdp = await context.newCDPSession(page);
  try {
    for (const next of [1, 0]) {
      const left = box.x + box.width * 0.2;
      const right = box.x + box.width * 0.8;
      const start = next ? right : left, end = next ? left : right;
      const points = x => [{ x, y: box.y + box.height / 2, id: 1 }];
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: points(start) });
      for (let i = 1; i <= 3; i++) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(start + (end - start) * i / 3) });
      }
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await page.waitForTimeout(250);
      assert.equal(page.url(), startUrl, 'swiping slides must not navigate the share page');
      assert.equal(await frame.evaluate(() => current), next);
    }
  } finally { await cdp.detach(); }
}

// Shared by the synthetic browser regression and the actual HTTP image entry.
export async function checkMobilePlayback(browser, url, reducedMotion = 'no-preference', requireSteps = true) {
  const context = await browser.newContext({ viewport: { width: 430, height: 932 }, hasTouch: true, isMobile: true, reducedMotion });
  await context.addInitScript(() => {
    const counters = { listeners: 0, particles: 0 };
    window.__playbackTest = counters;
    const add = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function (...args) { counters.listeners++; return add.apply(this, args); };
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args) { if (this.id === 'particles') counters.particles++; return get.apply(this, args); };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  page.on('crash', () => errors.push('crash'));
  try {
    await page.goto(url);
    const frame = await (await page.waitForSelector('iframe')).contentFrame();
    assert.ok(frame);
    await frame.waitForSelector('body[data-yuling-playback="light-v1"].yuling-playback-ready');
    const count = await frame.locator('#stage > .slide').count();
    assert.ok(count >= 6);
    async function sample() {
      return frame.evaluate(() => {
        const actual = [...document.querySelectorAll('#stage > .slide')];
        return {
          active: actual.filter(s => s.classList.contains('active')).length,
          leaving: actual.filter(s => s.classList.contains('leaving')).length,
          drawn: actual.filter(s => getComputedStyle(s).display !== 'none').length,
          hiddenRunning: document.getAnimations().filter(a => {
            const s = a.effect?.target?.closest?.('.slide');
            return s && !s.classList.contains('active') && a.playState === 'running';
          }).length,
          particles: window.__playbackTest.particles,
          listeners: window.__playbackTest.listeners,
          nodes: document.querySelectorAll('*').length,
        };
      });
    }
    async function stable() {
      await page.waitForTimeout(400);
      const s = await sample();
      assert.equal(s.active, 1); assert.equal(s.leaving, 0); assert.equal(s.drawn, 1);
      assert.equal(s.hiddenRunning, 0); assert.equal(s.particles, 0);
      return s;
    }
    await stable();
    if (browser.browserType().name() === 'chromium') await checkSwipes(context, page, frame);
    const pan = await frame.locator('#stage').evaluate(el => getComputedStyle(el).touchAction);
    assert.deepEqual(pan.split(' ').sort(), ['pan-y', 'pinch-zoom'], 'vertical scrolling and pinch zoom must remain available');
    await frame.evaluate(() => { openMap(); closeMap(); });
    assert.equal(await frame.locator('.map-tile').count(), count);
    assert.equal(await frame.locator('.map-mini, .map-screen, #map .slide').count(), 0);
    await frame.evaluate(() => openMap());
    assert.equal(await frame.locator('.map-tile').first().evaluate(el => Number(getComputedStyle(el).opacity)), 1);
    assert.ok((await frame.locator('.map-tile').first().boundingBox()).height >= 44, 'mobile map needs an unscaled touch target');
    assert.ok((await frame.locator('.map-meta span').first().boundingBox()).height >= 14, 'mobile map titles must stay legible');
    await frame.locator('.map-tile').nth(1).click();
    const before = await stable();
    for (let i = 0; i < 100; i++) {
      // WebKit bounds history writes per 10s. Rapid reversal is tested separately.
      await page.waitForTimeout(150);
      await frame.evaluate(index => show(index, true), i % count);
      const s = await sample();
      assert.equal(s.active, 1); assert.ok(s.leaving <= 1); assert.ok(s.drawn <= 2);
      if (i % 10 === 9) {
        await stable();
        await frame.evaluate(() => { openMap(); closeMap(); });
      }
    }
    await frame.evaluate(() => { for (let i = 0; i < 10; i++) show(i % 2); show(0); });
    await page.waitForTimeout(900); // Also catches the obsolete engine 800ms callback.
    assert.equal(await frame.locator('.slide.active.leaving').count(), 0);
    const after = await stable();
    assert.equal(after.nodes, before.nodes); assert.equal(after.listeners, before.listeners);
    assert.deepEqual(errors, []);
    const stepsPresent = await frame.evaluate(() => {
      const index = slides.findIndex(s => s.querySelector('[data-step]'));
      if (index < 0) return false;
      show(index, false);
      if (!hasHiddenStep(slides[current])) throw Error('step reveal missing');
      advance();
      if (!slides[current].querySelector('.step-shown')) throw Error('step reveal failed');
      return true;
    });
    if (requireSteps) assert.equal(stepsPresent, true, 'fixture must exercise step reveal');
    await stable();
    for (let i = 0; i < 5; i++) {
      await page.setViewportSize(i % 2 ? { width: 430, height: 932 } : { width: 932, height: 430 });
      assert.equal(await frame.locator('body').getAttribute('data-yuling-playback'), 'light-v1');
    }
    await frame.evaluate(() => {
      show(0, true); toggleAutoplay();
      for (let i = 0; i < 3; i++) {
        window.dispatchEvent(new PageTransitionEvent('pagehide'));
        if (autoplayTimer !== null) throw Error('background autoplay survived');
        window.dispatchEvent(new PageTransitionEvent('pageshow'));
        if (autoplayTimer === null) throw Error('autoplay did not resume');
      }
    });
    await page.waitForTimeout(9200);
    assert.equal(await frame.evaluate(() => current), 1);
    await frame.evaluate(() => toggleAutoplay());
    await stable();
    for (let i = 0; i < count; i++) {
      await frame.evaluate(index => show(index, true), i);
      await stable();
      assert.equal(await frame.evaluate(() => [...slides[current].querySelectorAll('figure[data-chart] svg')]
        .every(svg => svg.getBoundingClientRect().width > 0 && svg.getBoundingClientRect().height > 0)), true);
      assert.equal(await frame.evaluate(() => [...slides[current].querySelectorAll('[data-a]')]
        .every(el => Number(getComputedStyle(el).opacity) > 0.99)), true);
      assert.equal(await frame.evaluate(() => [...slides[current].querySelectorAll('.ch')]
        .every(el => Number(getComputedStyle(el).opacity) > 0.99)), true, 'chapter title must remain readable');
    }
    assert.deepEqual(errors, []);
    return { pages: count, flips: 100, hiddenRunning: 0, particles: 0, listenersStable: true, stepsPresent, reducedMotion };
  } finally { await context.close(); }
}
