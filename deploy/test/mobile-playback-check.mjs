import assert from 'node:assert/strict';
/* global window, document, HTMLCanvasElement, getComputedStyle, requestAnimationFrame, show, openMap, closeMap, slides, current, hasHiddenStep, advance, toggleAutoplay, autoplayTimer, PageTransitionEvent, countUp, typewrite */

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
    const counters = { listeners: 0, particles: 0, particleFrames: 0, frames: 0, pendingFrames: 0, observers: 0 };
    window.__playbackTest = counters;
    const frame = window.requestAnimationFrame;
    const cancelFrame = window.cancelAnimationFrame;
    const pendingFrames = new Set();
    window.requestAnimationFrame = callback => {
      counters.frames++;
      const id = frame.call(window, time => {
        pendingFrames.delete(id); counters.pendingFrames = pendingFrames.size;
        callback(time);
      });
      pendingFrames.add(id); counters.pendingFrames = pendingFrames.size;
      return id;
    };
    window.cancelAnimationFrame = id => {
      pendingFrames.delete(id); counters.pendingFrames = pendingFrames.size;
      cancelFrame.call(window, id);
    };
    const add = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function (...args) { counters.listeners++; return add.apply(this, args); };
    const OriginalObserver = window.IntersectionObserver;
    window.IntersectionObserver = class extends OriginalObserver {
      constructor(...args) { super(...args); this.counted = true; counters.observers++; }
      disconnect() {
        if (this.counted) { counters.observers--; this.counted = false; }
        super.disconnect();
      }
    };
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (...args) {
      const context = get.apply(this, args);
      if (this.id === 'particles') {
        counters.particles++;
        const clear = context.clearRect;
        context.clearRect = function (...values) { counters.particleFrames++; return clear.apply(this, values); };
      }
      return context;
    };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  page.on('crash', () => errors.push('crash'));
  try {
    await page.goto(url);
    const frame = await (await page.waitForSelector('iframe')).contentFrame();
    assert.ok(frame);
    await frame.waitForSelector('body[data-yuling-playback="lifecycle-v2"].yuling-playback-ready');
    const count = await frame.locator('#stage > .slide').count();
    assert.ok(count >= 6);
    async function sample() {
      return frame.evaluate(() => {
        const actual = [...document.querySelectorAll('#stage > .slide')];
        return {
          page: current,
          active: actual.filter(s => s.classList.contains('active')).length,
          leaving: actual.filter(s => s.classList.contains('yuling-exit')).length,
          drawn: actual.filter(s => getComputedStyle(s).display !== 'none').length,
          hiddenRunning: document.getAnimations().filter(a => {
            const s = a.effect?.target?.closest?.('.slide');
            return s && !s.classList.contains('active') && a.playState === 'running';
          }).length,
          particles: window.__playbackTest.particles,
          listeners: window.__playbackTest.listeners,
          nodes: document.querySelectorAll('*').length,
          observers: window.__playbackTest.observers,
        };
      });
    }
    async function stable() {
      await frame.waitForFunction(() => !document.querySelector('#stage > .yuling-exit'));
      await page.waitForTimeout(60);
      const s = await sample();
      assert.equal(s.active, 1); assert.equal(s.leaving, 0); assert.equal(s.drawn, 1);
      assert.equal(s.hiddenRunning, 0); assert.equal(s.particles, 1, 'original particle renderer must still initialize once');
      assert.equal(s.observers, 0, 'closed map must release its intersection observer');
      return s;
    }
    await stable();
    if (browser.browserType().name() === 'chromium') await checkSwipes(context, page, frame);
    const pan = await frame.locator('#stage').evaluate(el => getComputedStyle(el).touchAction);
    assert.deepEqual(pan.split(' ').sort(), ['pan-y', 'pinch-zoom'], 'vertical scrolling and pinch zoom must remain available');
    await frame.evaluate(() => openMap());
    await frame.waitForFunction(() => Number(getComputedStyle(document.getElementById('map')).opacity) > 0.99);
    assert.equal(await frame.locator('.map-tile').count(), count);
    assert.equal(await frame.locator('.map-screen').count(), count);
    assert.ok(await frame.locator('#map .slide').count() > 0, 'original full thumbnails must be present');
    // The engine positions the selected tile on its next frame, including
    // reduced-motion mode where the CSS fade completes immediately.
    await frame.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await frame.evaluate(() => {
      const grid = document.getElementById('map-grid');
      grid.style.flex = 'none'; grid.style.height = '70px';
    });
    await frame.waitForFunction(() => document.getElementById('map-grid').clientHeight === 70);
    await frame.evaluate(() => { const grid = document.getElementById('map-grid'); grid.scrollTop = grid.lastElementChild.offsetTop; });
    await frame.waitForFunction(() => document.querySelector('.map-tile:last-child .slide'));
    await frame.waitForFunction(() => !document.querySelector('.map-tile:first-child .slide'));
    assert.ok(await frame.locator('#map .slide').count() < count, 'offscreen full thumbnail copies must be released');
    await frame.evaluate(() => {
      const grid = document.getElementById('map-grid');
      grid.style.removeProperty('flex'); grid.style.removeProperty('height'); grid.scrollTop = 0;
    });
    await frame.waitForFunction(() => document.querySelector('.map-tile:first-child .slide'));
    await frame.locator('.map-tile').nth(1).click();
    await frame.waitForFunction(() => current === 1);
    await frame.waitForFunction(() => document.querySelectorAll('#map .slide').length === 0);
    // The engine defers SVG creation until a chart has a visible size.
    // Visit every page once, then compare completed laps at the same cover.
    for (let i = 1; i <= count; i++) {
      await frame.evaluate(index => show(index, true), i % count);
      assert.ok(await frame.evaluate(() => [...slides[current].querySelectorAll('figure.chart')]
        .every(figure => figure.dataset.chartRendered === 'true' && figure.clientWidth > 0 && figure.clientHeight > 0)),
      'visible chart must finish drawing before measuring retained resources');
    }
    const before = await stable();
    assert.equal(before.page, 0);
    function checkResourceCounts(measured) {
      assert.equal(measured.page, before.page, 'compare at the same visible page');
      assert.equal(measured.nodes, before.nodes, 'DOM count changed after a completed lap');
      assert.equal(measured.listeners, before.listeners, 'listener count changed after a completed lap');
    }
    async function checkThumbnailCharts() {
      assert.equal(await frame.evaluate(() => slides.every((slide, index) => {
        const copy = document.querySelectorAll('.map-tile')[index]?.querySelector('.slide');
        if (!copy) return true;
        return [...slide.querySelectorAll('figure.chart')].every((figure, chart) => {
          const source = figure.querySelector('svg');
          return !source || source.outerHTML === copy.querySelectorAll('figure.chart')[chart]?.querySelector('svg')?.outerHTML;
        });
      })), true, 'already rendered chart thumbnails must preserve the original SVG');
    }
    for (let i = 1; i <= 100; i++) {
      // WebKit bounds history writes per 10s. Rapid reversal is tested separately.
      await page.waitForTimeout(150);
      await frame.evaluate(index => show(index, true), i % count);
      const s = await sample();
      assert.equal(s.active, 1); assert.ok(s.leaving <= 1); assert.ok(s.drawn <= 2);
      if (i % count === 0) {
        checkResourceCounts(await stable());
        await frame.evaluate(() => openMap());
        await checkThumbnailCharts();
        await frame.evaluate(() => closeMap());
        await frame.waitForFunction(() => document.querySelectorAll('#map .slide').length === 0);
      }
    }
    await frame.evaluate(() => { for (let i = 0; i < 10; i++) show(i % 2); show(0); });
    await page.waitForTimeout(900); // Also catches the obsolete engine 800ms callback.
    assert.equal(await frame.locator('.slide.active.leaving').count(), 0);
    const after = await stable();
    checkResourceCounts(after);
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
      assert.equal(await frame.locator('body').getAttribute('data-yuling-playback'), 'lifecycle-v2');
    }
    await frame.evaluate(() => {
      show(0, true); toggleAutoplay();
      for (let i = 0; i < 3; i++) {
        window.dispatchEvent(new PageTransitionEvent('pagehide'));
        if (autoplayTimer.id !== null) throw Error('background autoplay survived');
        window.dispatchEvent(new PageTransitionEvent('pageshow'));
        if (autoplayTimer.id === null) throw Error('autoplay did not resume');
      }
    });
    await page.waitForTimeout(9200);
    assert.equal(await frame.evaluate(() => current), 1);
    await frame.evaluate(() => toggleAutoplay());
    await stable();
    await frame.evaluate(() => {
      const count = document.createElement('span');
      count.id = 'test-count'; count.dataset.count = '1000'; count.textContent = '0';
      const type = document.createElement('span');
      type.id = 'test-type'; type.dataset.type = 'The original typing animation must resume from its current position.';
      slides[current].append(count, type);
      countUp(slides[current]); typewrite(slides[current]);
    });
    await page.waitForTimeout(850);
    const progress = await frame.evaluate(() => {
      window.dispatchEvent(new PageTransitionEvent('pagehide'));
      return { count: document.getElementById('test-count').textContent, type: document.getElementById('test-type').textContent };
    });
    await page.waitForTimeout(400);
    assert.deepEqual(await frame.evaluate(() => ({
      count: document.getElementById('test-count').textContent, type: document.getElementById('test-type').textContent,
    })), progress, 'background must pause original count and typing progress');
    await frame.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow')));
    await page.waitForTimeout(100);
    const resumed = await frame.evaluate(() => ({
      count: Number(document.getElementById('test-count').textContent), type: document.getElementById('test-type').textContent,
    }));
    assert.ok(resumed.count > Number(progress.count) && resumed.count < 1000, 'original counter resumes without jumping to its end');
    assert.ok(resumed.type.length >= progress.type.length && resumed.type.length < 60);
    await frame.evaluate(() => { document.getElementById('test-count').remove(); document.getElementById('test-type').remove(); });
    const chapter = await frame.evaluate(() => slides.findIndex(s => s.classList.contains('chapter')));
    assert.ok(chapter >= 0, 'fixture must exercise the original particle scene');
    await frame.evaluate(i => show(i, true), chapter);
    await stable();
    const visibleParticleFrames = await frame.evaluate(() => window.__playbackTest.particleFrames);
    if (reducedMotion !== 'reduce') {
      await frame.waitForFunction(before => window.__playbackTest.particleFrames > before, visibleParticleFrames, { timeout: 3000 });
    }
    const ordinary = await frame.evaluate(() => slides.findIndex(s => !s.classList.contains('chapter')));
    await frame.evaluate(i => show(i, true), ordinary);
    await stable();
    const particleFrames = await frame.evaluate(() => window.__playbackTest.particleFrames);
    const frameRequests = await frame.evaluate(() => window.__playbackTest.frames);
    await page.waitForTimeout(160);
    assert.equal(await frame.evaluate(() => window.__playbackTest.particleFrames), particleFrames, 'invisible particle canvas must stop drawing');
    assert.equal(await frame.evaluate(() => window.__playbackTest.frames), frameRequests, 'hidden particles must stop scheduling idle animation frames');
    assert.equal(await frame.evaluate(() => window.__playbackTest.pendingFrames), 0, 'hidden playback must not retain a pending animation frame');
    for (let i = 0; i < count; i++) {
      await frame.evaluate(index => show(index, true), i);
      await stable();
      await frame.waitForFunction(() => [...slides[current].querySelectorAll('[data-a], .ch')]
        .every(el => Number(getComputedStyle(el).opacity) > 0.99));
      assert.equal(await frame.evaluate(() => [...slides[current].querySelectorAll('figure[data-chart] svg')]
        .every(svg => svg.getBoundingClientRect().width > 0 && svg.getBoundingClientRect().height > 0)), true);
      assert.equal(await frame.evaluate(() => [...slides[current].querySelectorAll('[data-a]')]
        .every(el => Number(getComputedStyle(el).opacity) > 0.99)), true);
      assert.equal(await frame.evaluate(() => [...slides[current].querySelectorAll('.ch')]
        .every(el => Number(getComputedStyle(el).opacity) > 0.99)), true, 'chapter title must remain readable');
    }
    assert.deepEqual(errors, []);
    return { pages: count, flips: 100, hiddenRunning: 0, particleRendererPresent: true, thumbnailsPresent: true, listenersStable: true, stepsPresent, reducedMotion };
  } finally { await context.close(); }
}
