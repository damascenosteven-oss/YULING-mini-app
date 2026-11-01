import { createHash } from 'node:crypto';
import { mobilePlaybackCss, mobilePlaybackRuntime, playbackRewrites } from './mobile-playback-lifecycle';
import { mobilePlaybackCss as legacyCss, mobilePlaybackRuntime as legacyRuntime } from './mobile-playback-runtime';

const runtimeHash = '034a4b48d4c2d7c2852f8488232a68fafc2a21f03ba30eb6038277fad7989624';
const boot = 'splitHeadingLines();\n(window.componentBootSteps || []).forEach(step => step());';
const marker = '<!-- yuling-mobile-playback:v2 -->';
const style = `<style data-yuling-mobile="v2">${mobilePlaybackCss}</style>`;
const injected = `${marker}\n${mobilePlaybackRuntime}`;
const digest = (value: string) => createHash('sha256').update(value).digest('hex');

export class PlaybackCompatibilityError extends Error {
  constructor() { super('playback_runtime_unsupported'); this.name = 'PlaybackCompatibilityError'; }
}

/** Adapt only the pinned runtime. Stored COS bytes are never changed. */
function rewrite(html: string, reverse: boolean): string {
  for (const [original, changed] of playbackRewrites) {
    const from = reverse ? changed : original, to = reverse ? original : changed;
    const count = original === 'requestAnimationFrame(tick);' ? 2 : 1;
    if (html.split(from).length !== count + 1) throw new PlaybackCompatibilityError();
    html = html.replaceAll(from, to);
  }
  return html;
}

export function restoreOriginalPlaybackHtml(input: string): string {
  const html = input.replace(/\r\n/g, '\n');
  const marked = html.includes(marker);
  let original = html;
  if (marked) {
    if (html.split(marker).length !== 2 || html.split(injected).length !== 2 || html.split(style).length !== 2) throw new PlaybackCompatibilityError();
    original = rewrite(html.replace(injected, '').replace(style, ''), true);
  } else if (html.includes('<!-- yuling-mobile-playback:v1 -->')) {
    const oldInjection = '<!-- yuling-mobile-playback:v1 -->\n' + legacyRuntime;
    const oldStyle = '<style data-yuling-mobile="v1">' + legacyCss + '</style>';
    if (html.split('<!-- yuling-mobile-playback:v1 -->').length !== 2
      || html.split(oldInjection).length !== 2 || html.split(oldStyle).length !== 2) throw new PlaybackCompatibilityError();
    original = html.replace(oldInjection, '').replace(oldStyle, '');
  } else if (html.includes('data-yuling-mobile=') || html.includes('yuling-mobile-playback:')) {
    throw new PlaybackCompatibilityError();
  }
  if (original.includes('data-yuling-mobile=') || original.includes('yuling-mobile-playback:')) throw new PlaybackCompatibilityError();
  const scripts = [...original.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  if (scripts.length !== 1 || digest(scripts[0][1]) !== runtimeHash || original.split(boot).length !== 2
    || original.split('</head>').length !== 2 || !original.includes('id="stage"') || !original.includes('id="map-grid"')) {
    throw new PlaybackCompatibilityError();
  }
  return original;
}

export function adaptMobilePlayback(input: string): string {
  const original = restoreOriginalPlaybackHtml(input);
  // The marker is a JS comment here so the one verified classic-script scope is preserved.
  return rewrite(original, false).replace('</head>', `${style}</head>`).replace(boot, `${injected}${boot}`);
}
