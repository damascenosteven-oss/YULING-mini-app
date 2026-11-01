// Application-owned task lifecycle. Browser global scheduling APIs stay native.
export const mobilePlaybackRuntime = String.raw`
const playbackTasks = (() => {
  const mobile = matchMedia('(pointer: coarse) and (hover: none)').matches;
  const tasks = new Set();
  const body = document.body;
  let suspended = false;
  let particleId = null;
  let particleDraw = null;
  let pausedAt = 0;
  let pausedTime = 0;
  let mapCovering = false;
  function arm(task) {
    if (suspended || task.cancelled) return;
    task.started = performance.now();
    task.id = task.frame ? requestAnimationFrame(now => fire(task, now)) : setTimeout(() => fire(task), task.remaining);
  }
  function fire(task, now) {
    task.id = null;
    if (task.cancelled || suspended) return;
    if (!task.interval) tasks.delete(task);
    task.callback(task.frame ? now - pausedTime : now);
    if (task.interval && !task.cancelled) { task.remaining = task.interval; arm(task); }
  }
  function make(owner, callback, remaining, frame = false, interval = 0) {
    const task = { owner, callback, remaining, frame, interval, id: null, cancelled: false, started: 0 };
    tasks.add(task); arm(task); return task;
  }
  function cancel(task) {
    if (!task || typeof task !== 'object') { clearTimeout(task); return; }
    task.cancelled = true;
    if (task.frame) cancelAnimationFrame(task.id); else clearTimeout(task.id);
    tasks.delete(task);
  }
  function cancelOwner(owner) {
    for (const task of tasks) if (task.owner === owner) cancel(task);
  }
  function particleVisible() {
    return !suspended && !document.hidden && body.classList.contains('is-night') && !body.classList.contains('is-settled') && !mapCovering;
  }
  function scheduleParticle(callback) {
    if (!mobile) { requestAnimationFrame(callback); return; }
    if (particleId === null && particleVisible()) {
      particleId = requestAnimationFrame(() => { particleId = null; if (particleVisible()) callback(); });
    }
  }
  function syncParticles() {
    if (!mobile) { if (particleDraw) particleDraw(); return; }
    if (!particleVisible()) { cancelAnimationFrame(particleId); particleId = null; }
    else if (particleDraw && particleId === null) scheduleParticle(particleDraw);
  }
  const api = {
    delay: (owner, callback, ms) => mobile ? make(owner, callback, ms) : setTimeout(callback, ms),
    frame: (owner, callback) => mobile ? make(owner, callback, 0, true) : requestAnimationFrame(callback),
    repeat: (callback, ms) => mobile ? make(null, callback, ms, false, ms) : setInterval(callback, ms),
    now: () => performance.now() - (mobile ? pausedTime : 0),
    cancel, scheduleParticle, syncParticles,
    set particleDraw(callback) { particleDraw = callback; },
  };
  if (!mobile) return api;
  body.dataset.yulingPlayback = 'lifecycle-v3';
  let exit = null;
  let exitTimer = null;
  let generation = 0;
  function duration(element) {
    const style = getComputedStyle(element);
    const milliseconds = value => value.trim().endsWith('ms') ? parseFloat(value) : parseFloat(value) * 1000;
    const times = style.transitionDuration.split(',').map(milliseconds);
    const delays = style.transitionDelay.split(',').map(milliseconds);
    return Math.max(0, ...times.map((time, i) => time + delays[i % delays.length]));
  }
  const backgrounds = ['backdrop', 'nightsky'].map(id => ({
    element: document.getElementById(id), released: false, phases: [], clock: 0, display: '', restoring: 0,
  })).filter(item => item.element);
  let backgroundTime = 0;
  let backgroundReference = null;
  let backgroundTimer = null;
  const wipe = document.getElementById('wipe');
  const wipeDisplay = wipe?.style.display || '';
  let wipeTimer = null;
  let wipeGeneration = 0;
  function backgroundAnimations(except) {
    return backgrounds.filter(item => !item.released && item.element !== except)
      .flatMap(item => item.element.getAnimations({ subtree: true }))
      .filter(animation => animation.animationName === 'aurora');
  }
  function setBackgroundReference(except) {
    const animation = backgroundAnimations(except)[0];
    backgroundReference = animation ? { target: animation.effect.target, time: Number(animation.currentTime) } : null;
  }
  function backgroundClock() {
    const animation = backgroundReference && backgroundAnimations()
      .find(animation => animation.effect.target === backgroundReference.target);
    if (animation) {
      const time = Number(animation.currentTime);
      backgroundTime += Math.max(0, time - backgroundReference.time);
      backgroundReference.time = time;
    } else setBackgroundReference();
    // Follow native CSS progress, including settled/background pauses. A wall
    // clock can run ahead of WebKit's delivered animation timeline under load.
    return backgroundTime;
  }
  function desiredBackground() { return slides[current].classList.contains('chapter') ? 'nightsky' : 'backdrop'; }
  function releaseBackground(item) {
    const root = item.element;
    if (item.released || root.id === desiredBackground() || getComputedStyle(root).opacity !== '0') return;
    const children = [...root.querySelectorAll('i')];
    item.clock = backgroundClock();
    item.phases = root.getAnimations({ subtree: true }).filter(a => a.animationName === 'aurora')
      .map(a => ({ index: children.indexOf(a.effect.target), time: Number(a.currentTime) }));
    if (root.contains(backgroundReference?.target)) setBackgroundReference(root);
    item.display = root.style.display;
    root.style.display = 'none';
    item.released = true;
  }
  function restoreBackground(next) {
    const id = next.classList.contains('chapter') ? 'nightsky' : 'backdrop';
    const item = backgrounds.find(item => item.element.id === id);
    if (!item?.released) return;
    // Apply the next tint before allocating the hidden night background again.
    if (id === 'nightsky') tintNightSky(next);
    const elapsed = backgroundClock() - item.clock;
    item.element.style.display = item.display;
    const children = [...item.element.querySelectorAll('i')];
    for (const animation of item.element.getAnimations({ subtree: true })) {
      const phase = item.phases.find(phase => children[phase.index] === animation.effect.target && animation.animationName === 'aurora');
      if (phase) animation.currentTime = phase.time + elapsed;
    }
    item.restoring = generation;
    item.released = false;
  }
  function finishBackgroundRestores(token) {
    for (const item of backgrounds.filter(item => item.restoring === token)) {
      const animations = item.element.getAnimations({ subtree: true }).filter(a => a.animationName === 'aurora');
      const children = [...item.element.querySelectorAll('i')];
      // Revived CSS animations can remain pending until their first WebKit
      // frame. Align after native play readiness, before that frame is painted.
      Promise.all(animations.map(a => a.ready)).then(() => {
        if (token !== generation || item.released || item.element.id !== desiredBackground()) return;
        const elapsed = backgroundClock() - item.clock;
        for (const animation of animations) {
          const phase = item.phases.find(phase => children[phase.index] === animation.effect.target);
          if (phase) animation.currentTime = phase.time + elapsed;
        }
        item.phases = []; item.restoring = 0;
      }, error => { if (error.name !== 'AbortError') throw error; });
    }
  }
  function releaseWipe() {
    if (!wipe || wipe.style.display === 'none') return;
    if (wipe.getAnimations().some(a => a.playState === 'running' || a.playState === 'paused')) return;
    const rect = wipe.getBoundingClientRect(), bounds = stage.getBoundingClientRect();
    const blur = parseFloat(getComputedStyle(wipe).filter.match(/blur\(([\d.]+)px\)/)?.[1] || '0');
    const padding = (blur * 4 + 1) * bounds.width / stage.offsetWidth;
    const outside = rect.right + padding < bounds.left || rect.left - padding > bounds.right
      || rect.bottom + padding < bounds.top || rect.top - padding > bounds.bottom;
    if (getComputedStyle(wipe).opacity !== '0' && !outside) return;
    cancel(wipeTimer); wipeTimer = null;
    wipe.style.display = 'none';
    wipe.classList.remove('run');
  }
  function prepareGlobals(next, previous) {
    backgroundClock();
    restoreBackground(next);
    const target = backgrounds.find(item => item.element.id === (next.classList.contains('chapter') ? 'nightsky' : 'backdrop'));
    if (target?.restoring) target.restoring = generation;
    cancel(backgroundTimer); backgroundTimer = null;
    if (wipe && next !== previous && next.classList.contains('chapter')) {
      cancel(wipeTimer); wipeTimer = null; wipeGeneration++;
      wipe.style.display = wipeDisplay;
    }
  }
  function scheduleGlobals(token) {
    backgroundClock();
    const hidden = backgrounds.filter(item => item.element.id !== desiredBackground());
    for (const item of hidden) releaseBackground(item);
    if (hidden.some(item => !item.released)) {
      backgroundTimer = api.delay(null, () => {
        backgroundTimer = null;
        if (token === generation) for (const item of hidden) releaseBackground(item);
      }, Math.max(0, ...hidden.map(item => duration(item.element))) + 34);
    }
    releaseWipe();
    if (wipe && wipe.style.display !== 'none') {
      const active = wipe.getAnimations().find(a => a.animationName === 'wipe');
      if (active) {
        const version = wipeGeneration;
        cancel(wipeTimer);
        wipeTimer = api.delay(null, () => { wipeTimer = null; if (version === wipeGeneration) releaseWipe(); },
          Math.max(0, active.effect.getComputedTiming().endTime - Number(active.currentTime)) + 34);
      }
    }
  }
  for (const item of backgrounds) item.element.addEventListener('transitionend', event => {
    if (event.target === item.element && event.propertyName === 'opacity') releaseBackground(item);
  });
  wipe?.addEventListener('animationend', event => {
    if (event.target === wipe && event.animationName === 'wipe') releaseWipe();
  });
  function releaseExit() {
    cancel(exitTimer); exitTimer = null;
    if (exit && exit !== slides[current]) {
      cancelLeaving(exit); exit.classList.remove('yuling-exit'); cancelOwner(exit);
      // WebKit can retain animation handles across a rapid display change.
      // Cancel only the now-hidden page, after its original exit transition.
      exit.getAnimations({ subtree: true }).forEach(animation => animation.cancel());
    }
    exit = null;
  }
  const originalShow = show;
  show = (index, revealAll = true) => {
    const token = ++generation;
    releaseExit();
    const previous = slides[current];
    const next = slides[Math.max(0, Math.min(slides.length - 1, index))];
    next.classList.add('yuling-enter');
    void next.offsetWidth; // Establish the original pre-entry transition state.
    cancelOwner(next);
    prepareGlobals(next, previous);
    originalShow(index, revealAll);
    finishBackgroundRestores(token);
    next.classList.remove('yuling-enter');
    body.classList.add('yuling-playback-ready');
    if (previous !== next) {
      cancelLeaving(previous);
      previous.classList.add('leaving', 'yuling-exit');
      exit = previous;
      exitTimer = api.delay(null, () => { if (token === generation) releaseExit(); }, duration(previous));
    }
    syncParticles();
    scheduleGlobals(token);
  };
  const originalSettle = scheduleSettle;
  scheduleSettle = slide => {
    backgroundClock();
    originalSettle(slide);
    backgroundClock();
    const callback = settleTimer.callback;
    settleTimer.callback = () => { backgroundClock(); callback(); backgroundClock(); syncParticles(); };
    syncParticles();
  };
  const originalMini = buildMiniSlide;
  const originalOpen = openMap;
  const originalClose = closeMap;
  const placeholders = new Map();
  let observer = null;
  let mapToken = 0;
  let mapCleanup = null;
  let mapCovered = null;
  api.thumbnailPlaceholder = index => {
    const holder = document.createElement('div'); holder.className = 'map-mini';
    placeholders.set(index, holder); return holder;
  };
  function releaseThumbnails() {
    if (observer) observer.disconnect();
    observer = null;
    for (const holder of placeholders.values()) holder.replaceChildren();
  }
  function mount(index) {
    const holder = placeholders.get(index);
    if (!holder || holder.firstElementChild) return;
    const mini = originalMini(slides[index]);
    holder.append(...mini.childNodes);
    const copy = holder.firstElementChild;
    const pending = [...copy.querySelectorAll('figure.chart')].filter(figure => figure.dataset.chartRendered !== 'true');
    if (!pending.length) return;
    const problems = window.diagramProblems;
    // The pinned renderer queries figure.chart from its root. Restrict that
    // query to pending figures so existing SVG bytes and geometry survive.
    try { renderSlideCharts({ querySelectorAll: () => pending }, index); }
    finally { window.diagramProblems = problems; }
  }
  function updateThumbnails() {
    if (!body.classList.contains('map-open')) return;
    const bounds = mapGrid.getBoundingClientRect();
    for (const [index, holder] of placeholders) {
      const rect = holder.parentElement.getBoundingClientRect();
      if (rect.bottom > bounds.top && rect.top < bounds.bottom && rect.right > bounds.left && rect.left < bounds.right) mount(index);
      else holder.replaceChildren();
    }
    fitMiniSlides();
  }
  openMap = () => {
    const token = ++mapToken;
    cancel(mapCleanup); cancel(mapCovered);
    originalOpen(); updateThumbnails();
    if (observer) observer.disconnect();
    observer = new IntersectionObserver(updateThumbnails, { root: mapGrid });
    for (const holder of placeholders.values()) observer.observe(holder.parentElement);
    mapCovered = api.delay(null, () => { if (token === mapToken) { mapCovering = true; syncParticles(); } }, duration(mapPanel));
  };
  closeMap = () => {
    const token = ++mapToken;
    originalClose(); cancel(mapCleanup); cancel(mapCovered); cancelOwner(mapPanel);
    mapCovering = false;
    mapCleanup = api.delay(null, () => { if (token === mapToken) releaseThumbnails(); }, duration(mapPanel));
    syncParticles();
  };
  let pausedAnimations = [];
  function suspend() {
    if (suspended) return;
    suspended = true;
    pausedAt = performance.now();
    for (const task of tasks) {
      if (task.id === null) continue;
      if (task.frame) cancelAnimationFrame(task.id);
      else { clearTimeout(task.id); task.remaining = Math.max(0, task.remaining - (performance.now() - task.started)); }
      task.id = null;
    }
    pausedAnimations = document.getAnimations().filter(animation => animation.playState === 'running');
    pausedAnimations.forEach(animation => animation.pause());
    syncParticles();
  }
  function resume() {
    if (!suspended || document.hidden) return;
    suspended = false;
    pausedTime += performance.now() - pausedAt;
    for (const task of tasks) arm(task);
    pausedAnimations.forEach(animation => { if (animation.effect?.target?.isConnected) animation.play(); });
    pausedAnimations = [];
    fitStage(); updateThumbnails(); syncParticles();
  }
  document.addEventListener('visibilitychange', () => document.hidden ? suspend() : resume());
  addEventListener('pagehide', suspend);
  addEventListener('pageshow', resume);
  return api;
})();
`;

export const mobilePlaybackCss = String.raw`
body[data-yuling-playback="lifecycle-v3"] #stage { touch-action:pan-y pinch-zoom; }
body[data-yuling-playback="lifecycle-v3"].yuling-playback-ready #stage > .slide:not(.active):not(.yuling-exit):not(.yuling-enter) { display:none!important; }
`;

export const playbackRewrites: ReadonlyArray<readonly [string, string]> = [
  ['clearTimeout(settleTimer);', 'playbackTasks.cancel(settleTimer);'],
  ['settleTimer = setTimeout(() => {', 'settleTimer = playbackTasks.delay(slide, () => {'],
  ['requestAnimationFrame(tick);', 'playbackTasks.frame(slide, tick);'],
  ['const startAt = performance.now() + 500;', 'const startAt = playbackTasks.now() + 500;'],
  ['setTimeout(step, 70);', 'playbackTasks.delay(slide, step, 70);'],
  ['setTimeout(step, 700);', 'playbackTasks.delay(slide, step, 700);'],
  ['clearInterval(autoplayTimer);', 'playbackTasks.cancel(autoplayTimer);'],
  ['autoplayTimer = setInterval(() => {', 'autoplayTimer = playbackTasks.repeat(() => {'],
  ['  requestAnimationFrame(() => {\n    fitMiniSlides();', '  playbackTasks.frame(mapPanel, () => {\n    fitMiniSlides();'],
  ['clearTimeout(dragIdleTimer);', 'playbackTasks.cancel(dragIdleTimer);'],
  ['dragIdleTimer = setTimeout(() =>', 'dragIdleTimer = playbackTasks.delay(null, () =>'],
  ['    requestAnimationFrame(frame);\n    if (!document.body.classList.contains("is-night")', '    playbackTasks.scheduleParticle(frame);\n    if (!document.body.classList.contains("is-night")'],
  ['  frame();\n}\n\n(window.styleBootSteps', '  playbackTasks.particleDraw = frame;\n  playbackTasks.syncParticles();\n}\n\n(window.styleBootSteps'],
  ['screen.appendChild(buildMiniSlide(slide));', 'screen.appendChild(playbackTasks.thumbnailPlaceholder ? playbackTasks.thumbnailPlaceholder(index) : buildMiniSlide(slide));'],
];
