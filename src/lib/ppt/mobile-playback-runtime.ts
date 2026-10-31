// Application-owned compatibility code, injected before the verified engine boot.
// It shares the classic script scope; the pinned engine itself is not copied here.
export const mobilePlaybackRuntime = String.raw`
(() => {
  if (!matchMedia('(pointer: coarse) and (hover: none)').matches) return;
  const body = document.body;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  body.dataset.yulingPlayback = 'light-v1';
  // The slide stage is scaled from 1920px. Keep the phone map readable outside it.
  body.append(mapPanel, document.getElementById('map-toggle'));
  window.styleBootSteps = (window.styleBootSteps || []).filter(step => step !== startParticles && step !== attachPointerLight);
  window.styleEnterSteps = (window.styleEnterSteps || []).filter(step => step !== runChapterWipe);

  // No counting/typewriter task should survive its slide; show the final value.
  countUp = slide => slide.querySelectorAll('[data-count]').forEach(element => {
    element.textContent = element.dataset.count + (element.dataset.suffix || '');
  });
  typewrite = slide => slide.querySelectorAll('[data-type]').forEach(element => {
    element.textContent = element.dataset.type;
    element.style.whiteSpace = 'pre-line';
  });
  scheduleSettle = slide => {
    clearTimeout(settleTimer);
    slides.forEach(other => other.classList.toggle('settled', other !== slide));
    body.classList.remove('is-settled');
    settleTimer = setTimeout(() => {
      if (slides[current] !== slide) return;
      slide.classList.add('settled');
      body.classList.add('is-settled');
      settleTimer = null;
    }, reduced.matches ? 0 : 350);
  };
  const originalShow = show;
  let exitTimer = null;
  let generation = 0;
  show = (index, revealAll = true) => {
    const token = ++generation;
    clearTimeout(exitTimer);
    slides.forEach(cancelLeaving);
    const previous = slides[current];
    originalShow(index, revealAll);
    const active = slides[current];
    // Components measure the active page in originalShow, before drawing is gated.
    body.classList.add('yuling-playback-ready');
    slides.forEach(slide => {
      cancelLeaving(slide);
      if (slide !== active) slide.classList.add('settled');
    });
    if (previous !== active && !reduced.matches) {
      previous.classList.add('leaving');
      exitTimer = setTimeout(() => {
        if (token !== generation) return;
        if (previous !== slides[current]) previous.classList.remove('leaving');
        exitTimer = null;
      }, 200);
    }
  };

  buildMap = () => {
    if (mapBuilt) return;
    slides.forEach((slide, index) => {
      const tile = document.createElement('button');
      tile.className = 'map-tile';
      const meta = document.createElement('div');
      meta.className = 'map-meta';
      const number = document.createElement('b');
      number.textContent = String(index + 1);
      const title = document.createElement('span');
      title.textContent = slideTitle(slide);
      meta.append(number, title);
      tile.append(meta);
      tile.addEventListener('click', () => { closeMap(); show(index); });
      mapGrid.append(tile);
    });
    mapBuilt = true;
  };

  let suspended = false;
  let resumeAutoplay = false;
  function suspend() {
    if (suspended) return;
    suspended = true;
    resumeAutoplay = Boolean(autoplayTimer);
    if (autoplayTimer) toggleAutoplay();
    clearTimeout(settleTimer);
    clearTimeout(exitTimer);
    ++generation;
    slides.forEach(slide => { cancelLeaving(slide); slide.classList.add('settled'); });
    body.classList.add('is-settled');
  }
  function resume() {
    if (!suspended || document.hidden) return;
    suspended = false;
    fitStage();
    if (resumeAutoplay && !autoplayTimer) toggleAutoplay();
    resumeAutoplay = false;
  }
  document.addEventListener('visibilitychange', () => document.hidden ? suspend() : resume());
  addEventListener('pagehide', suspend);
  addEventListener('pageshow', resume);
})();
`;

export const mobilePlaybackCss = String.raw`
body[data-yuling-playback="light-v1"] *,
body[data-yuling-playback="light-v1"] *::before,
body[data-yuling-playback="light-v1"] *::after { filter:none!important; backdrop-filter:none!important; -webkit-backdrop-filter:none!important; animation:none!important; will-change:auto!important; }
body[data-yuling-playback="light-v1"] #viewport { transition:none; }
body[data-yuling-playback="light-v1"] #backdrop,
body[data-yuling-playback="light-v1"] #nightsky,
body[data-yuling-playback="light-v1"] #particles,
body[data-yuling-playback="light-v1"] #wipe,
body[data-yuling-playback="light-v1"] #motion-field { display:none!important; }
body[data-yuling-playback="light-v1"] .slide { transform:none!important; clip-path:none!important; transition:opacity 200ms ease!important; }
body[data-yuling-playback="light-v1"].yuling-playback-ready .slide:not(.active):not(.leaving) { display:none!important; }
body[data-yuling-playback="light-v1"] .slide.leaving { opacity:0!important; pointer-events:none; }
body[data-yuling-playback="light-v1"] .slide.active { opacity:1!important; visibility:visible!important; }
body[data-yuling-playback="light-v1"] .slide [data-a],
body[data-yuling-playback="light-v1"] .slide .line > span,
body[data-yuling-playback="light-v1"] .slide .ch { opacity:1; transform:none; }
body[data-yuling-playback="light-v1"] .glass,
body[data-yuling-playback="light-v1"] .win.tilt { transform:none!important; }
body[data-yuling-playback="light-v1"] .slide.active [data-a],
body[data-yuling-playback="light-v1"] .slide.active .line > span { animation:yuling-light-enter 300ms ease both!important; animation-delay:0ms!important; }
body[data-yuling-playback="light-v1"] .slide.active [data-step]:not(.step-shown) { visibility:hidden!important; animation:none!important; }
body[data-yuling-playback="light-v1"] .slide.settled [data-a],
body[data-yuling-playback="light-v1"] .slide.settled .line > span { animation:none!important; opacity:1; transform:none; }
body[data-yuling-playback="light-v1"] #map { position:fixed; padding:70px 16px 16px; background:var(--bg); z-index:50; }
body[data-yuling-playback="light-v1"] #map header { padding:0; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
body[data-yuling-playback="light-v1"] #map header h2 { font-size:22px; }
body[data-yuling-playback="light-v1"] #map header span { font-size:12px; }
body[data-yuling-playback="light-v1"] #map-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; padding:4px; align-content:start; }
body[data-yuling-playback="light-v1"] .map-tile { min-height:76px; padding:12px; opacity:1; transform:none; border:1px solid var(--ink-3); border-radius:12px; }
body[data-yuling-playback="light-v1"] .map-tile.is-current { outline:2px solid var(--accent); }
body[data-yuling-playback="light-v1"] .map-meta { margin:0; gap:8px; }
body[data-yuling-playback="light-v1"] .map-meta b { font-size:14px; min-width:20px; }
body[data-yuling-playback="light-v1"] .map-meta span { font-size:15px; }
body[data-yuling-playback="light-v1"] #map-toggle { position:fixed; top:12px; right:12px; z-index:60; font-size:14px; padding:10px 12px; }
@keyframes yuling-light-enter { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }
@media (prefers-reduced-motion:reduce) {
  body[data-yuling-playback="light-v1"] .slide,
  body[data-yuling-playback="light-v1"] .slide * { animation:none!important; transition:none!important; }
}
`;
