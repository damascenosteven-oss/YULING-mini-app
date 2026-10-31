import { createHash } from 'node:crypto';
import { mobilePlaybackCss, mobilePlaybackRuntime } from './mobile-playback-runtime';

const runtimeHash = '034a4b48d4c2d7c2852f8488232a68fafc2a21f03ba30eb6038277fad7989624';
const boot = 'splitHeadingLines();\n(window.componentBootSteps || []).forEach(step => step());';
const marker = '<!-- yuling-mobile-playback:v1 -->';
const style = `<style data-yuling-mobile="v1">${mobilePlaybackCss}</style>`;
const injected = `${marker}\n${mobilePlaybackRuntime}`;
const digest = (value: string) => createHash('sha256').update(value).digest('hex');

export class PlaybackCompatibilityError extends Error {
  constructor() { super('playback_runtime_unsupported'); this.name = 'PlaybackCompatibilityError'; }
}

/** Adapt only the pinned runtime. Stored COS bytes are never changed. */
export function adaptMobilePlayback(input: string): string {
  const html = input.replace(/\r\n/g, '\n');
  const marked = html.includes(marker);
  let original = html;
  if (marked) {
    if (html.split(marker).length !== 2 || html.split(injected).length !== 2 || html.split(style).length !== 2) throw new PlaybackCompatibilityError();
    original = html.replace(injected, '').replace(style, '');
  } else if (html.includes('data-yuling-mobile=') || html.includes('yuling-mobile-playback:')) {
    throw new PlaybackCompatibilityError();
  }
  const scripts = [...original.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  if (scripts.length !== 1 || digest(scripts[0][1]) !== runtimeHash || original.split(boot).length !== 2
    || original.split('</head>').length !== 2 || !original.includes('id="stage"') || !original.includes('id="map-grid"')) {
    throw new PlaybackCompatibilityError();
  }
  if (marked) return html;
  // The marker is a JS comment here so the one verified classic-script scope is preserved.
  return original.replace('</head>', `${style}</head>`).replace(boot, `${injected}${boot}`);
}
