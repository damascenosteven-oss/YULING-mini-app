import { accessSync, constants } from 'node:fs';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright-core';
import { browserCandidates } from './platform';

export type DeckQaIssue = {
  page: number;
  code: 'blank' | 'javascript' | 'navigation' | 'overflow' | 'title-wrap' | 'chart' | 'motion';
};

export type DeckQaReport = {
  status: 'passed';
  pages: number;
  compacted: boolean;
  motionStatus: 'passed' | 'not-configured';
  motionProfile: string;
  fingerprint: string;
};

export class DeckQaError extends Error {
  constructor(readonly issues: DeckQaIssue[]) {
    super('Generated deck failed visual QA');
    this.name = 'DeckQaError';
  }
}

function chromePath(): string {
  const found = browserCandidates().find(candidate => {
    try {
      accessSync(candidate, constants.F_OK);
      return true;
    } catch {
      return false;
    }
  });
  if (!found) throw new Error('PPT_CHROME_PATH is not configured and Google Chrome was not found');
  return found;
}

function compactHtml(html: Buffer): Buffer {
  const source = html.toString('utf8');
  return Buffer.from(source.replace(/class="slide ai-generated-slide ai-content(?![^"\n]*\bai-compact\b)/g, 'class="slide ai-generated-slide ai-content ai-compact'));
}

async function inspect(html: Buffer): Promise<{ pages: number; issues: DeckQaIssue[]; motionProfile: string; fingerprint: string }> {
  const directory = await mkdtemp(path.join(tmpdir(), 'yuling-ppt-qa-'));
  const deckPath = path.join(directory, 'deck.html');
  let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
  let timedOut = false;
  const deadline = setTimeout(() => {
    timedOut = true;
    void browser?.close().catch(() => undefined);
  }, 45_000);
  try {
    await writeFile(deckPath, html);
    browser = await chromium.launch({
      executablePath: chromePath(),
      headless: true,
      timeout: 15_000,
      env: {
        ...process.env,
        HOME: directory,
        XDG_CONFIG_HOME: path.join(directory, 'config'),
        XDG_CACHE_HOME: path.join(directory, 'cache'),
      },
      args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-first-run'],
    });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(8_000);
    const javascriptErrors: string[] = [];
    page.on('pageerror', error => javascriptErrors.push(error.name));
    await page.goto(pathToFileURL(deckPath).href, { waitUntil: 'load' });
    await page.evaluate(async () => document.fonts.ready);
    const pages = await page.locator('.slide').count();
    const issues: DeckQaIssue[] = [];
    const motionMetadata = await page.evaluate(() => ({
      profile: [document.body.dataset.motionPersona, document.body.dataset.motionBackground].filter(Boolean).join(':'),
      fingerprint: document.body.dataset.motionFingerprint || '',
    }));

    if (motionMetadata.fingerprint) {
      for (let index = 0; index < pages; index += 1) {
        await page.evaluate(pageIndex => {
          const deckWindow = window as typeof window & { show?: (index: number, revealAll?: boolean) => void };
          deckWindow.show?.(pageIndex, true);
        }, index);
        await page.waitForTimeout(35);
        const motionInvalid = await page.evaluate(pageIndex => {
          const slide = document.querySelectorAll<HTMLElement>('.slide')[pageIndex];
          if (!slide?.dataset.motionEffect || !slide.dataset.motionEntrance) return true;
          const animations = slide.getAnimations({ subtree: true });
          for (const animation of animations) {
            const timing = animation.effect?.getComputedTiming();
            const endTime = Number(timing?.endTime);
            if (Number.isFinite(endTime) && endTime > 0 && endTime <= 10_000) animation.currentTime = endTime;
          }
          const animated = Array.from(slide.querySelectorAll<HTMLElement>('[data-a]'));
          return animated.some(element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            const transform = new DOMMatrixReadOnly(style.transform);
            const hasResidualEntranceTransform = Math.abs(transform.a - 1) > 0.001
              || Math.abs(transform.b) > 0.001
              || Math.abs(transform.c) > 0.001
              || Math.abs(transform.d - 1) > 0.001
              || Math.abs(transform.e) > 0.1
              || Math.abs(transform.f) > 0.1;
            return Number(style.opacity) < 0.94
              || style.visibility === 'hidden'
              || !Number.isFinite(rect.left)
              || !Number.isFinite(rect.top)
              || /NaN|Infinity/.test(style.transform)
              || hasResidualEntranceTransform;
          });
        }, index);
        if (motionInvalid) issues.push({ page: index + 1, code: 'motion' });
      }
      await page.emulateMedia({ reducedMotion: 'reduce' });
      for (let index = 0; index < pages; index += 1) {
        await page.evaluate(pageIndex => {
          const deckWindow = window as typeof window & { show?: (index: number, revealAll?: boolean) => void };
          deckWindow.show?.(pageIndex, true);
        }, index);
        const reducedMotionHidden = await page.evaluate(pageIndex => Array.from(document.querySelectorAll<HTMLElement>('.slide')[pageIndex]?.querySelectorAll<HTMLElement>('[data-a]') || []).some(element => Number(getComputedStyle(element).opacity) < 0.94), index);
        if (reducedMotionHidden) issues.push({ page: index + 1, code: 'motion' });
      }
      await page.emulateMedia({ reducedMotion: 'no-preference' });
    }

    await page.addStyleTag({ content: '*,*::before,*::after{animation:none!important;transition:none!important}.slide{clip-path:none!important}.slide [data-a],.line>span,.chapter h1 .ch{opacity:1!important;transform:none!important;filter:none!important}' });

    for (let index = 0; index < pages; index += 1) {
      await page.evaluate(pageIndex => {
        const deckWindow = window as typeof window & { show?: (index: number, revealAll?: boolean) => void };
        deckWindow.show?.(pageIndex, true);
      }, index);
      await page.waitForTimeout(40);
      const measurements = await page.evaluate(pageIndex => {
        const slides = Array.from(document.querySelectorAll<HTMLElement>('.slide'));
        const slide = slides[pageIndex];
        const nav = document.getElementById('nav');
        const stage = document.getElementById('stage');
        if (!slide || !nav || !stage) return { blank: true, navigation: true, overflow: true, titleWrap: false, chart: true };
        const active = slides.filter(item => item.classList.contains('active'));
        const style = getComputedStyle(slide);
        const visibleText = (slide.innerText || '').replace(/\s+/g, ' ').trim();
        const body = slide.querySelector<HTMLElement>('.ai-body') || slide.querySelector<HTMLElement>('h1');
        const bodyRect = body?.getBoundingClientRect();
        const navRect = nav.getBoundingClientRect();
        const stageRect = stage.getBoundingClientRect();
        const scale = stageRect.width / 1920;
        const tolerance = 3;
        const overflowNodes = Array.from(slide.querySelectorAll<HTMLElement>('*')).filter(element => {
          if (element.closest('#nav') || element.classList.contains('aigc-label')) return false;
          const elementStyle = getComputedStyle(element);
          if (elementStyle.display === 'none' || elementStyle.visibility === 'hidden' || Number(elementStyle.opacity) === 0) return false;
          if (elementStyle.position === 'absolute' || elementStyle.position === 'fixed') return false;
          const rect = element.getBoundingClientRect();
          if (rect.width < 1 || rect.height < 1) return false;
          return rect.left < stageRect.left - tolerance || rect.right > stageRect.right + tolerance || rect.top < stageRect.top - tolerance || rect.bottom > navRect.top - tolerance;
        });
        const diagramTextOverflow = Array.from(slide.querySelectorAll<HTMLElement>('.dg .node .text')).some(text => {
          const node = text.closest<HTMLElement>('.node');
          if (!node) return true;
          const textRect = text.getBoundingClientRect();
          const nodeRect = node.getBoundingClientRect();
          return text.scrollWidth > text.clientWidth + tolerance
            || text.scrollHeight > text.clientHeight + tolerance
            || textRect.left < nodeRect.left - tolerance
            || textRect.right > nodeRect.right + tolerance
            || textRect.top < nodeRect.top - tolerance
            || textRect.bottom > nodeRect.bottom + tolerance;
        });
        const rankingTextOverflow = Array.from(slide.querySelectorAll<HTMLElement>('.ai-podium-card')).some(card => {
          const cardRect = card.getBoundingClientRect();
          return Array.from(card.querySelectorAll<HTMLElement>('span,strong,b,small')).some(text => {
            const rect = text.getBoundingClientRect();
            const fontSize = Number.parseFloat(getComputedStyle(text).fontSize);
            const squeezedTitle = text.tagName === 'STRONG' && (text.textContent || '').trim().length > 2
              && rect.width < fontSize * 2 - tolerance;
            return squeezedTitle || text.scrollWidth > text.clientWidth + tolerance
              || rect.left < cardRect.left - tolerance || rect.right > cardRect.right + tolerance
              || rect.top < cardRect.top - tolerance || rect.bottom > cardRect.bottom + tolerance;
          });
        });
        const heading = slide.querySelector<HTMLElement>('h1,h2');
        const headingStyle = heading ? getComputedStyle(heading) : null;
        const lineHeight = headingStyle ? Number.parseFloat(headingStyle.lineHeight) : 0;
        const headingLines = heading && lineHeight > 0 ? heading.getBoundingClientRect().height / lineHeight : 0;
        const charts = Array.from(slide.querySelectorAll<HTMLElement>('figure.chart'));
        const chartInvalid = charts.some(chart => {
          const rect = chart.getBoundingClientRect();
          const type = chart.dataset.chart;
          const drawn = type === 'kpi' ? chart.querySelector('.kpi-value') : chart.querySelector('svg');
          const svg = drawn instanceof SVGSVGElement ? drawn : null;
          const rankingTextClipped = type === 'ranking' && svg && Array.from(svg.querySelectorAll('text')).some(text => {
            const textRect = text.getBoundingClientRect();
            const svgRect = svg.getBoundingClientRect();
            return textRect.left < svgRect.left - tolerance || textRect.right > svgRect.right + tolerance
              || textRect.top < svgRect.top - tolerance || textRect.bottom > svgRect.bottom + tolerance;
          });
          const content = chart.textContent || '';
          const typeNeedsCategoryColours = type === 'bar' || type === 'donut' || type === 'funnel' || type === 'matrix' || type === 'ranking' || type === 'scatter' || type === 'radar' || type === 'stacked-bar' || type === 'heatmap';
          const colourNodes = typeNeedsCategoryColours
            ? Array.from(chart.querySelectorAll<SVGElement>('.bar,.slice,.funnel-stage,.matrix-point,.ranking-bar,.scatter-point,.radar-series,.stack-segment,.heatmap-cell'))
            : [];
          const colours = new Set(colourNodes.map(node => {
            const nodeStyle = getComputedStyle(node);
            return type === 'donut' || type === 'radar' ? nodeStyle.stroke : nodeStyle.fill;
          }).filter(Boolean));
          let expectedColours = Math.min(3, colourNodes.length);
          if (type === 'bar') {
            try {
              const chartData = JSON.parse(chart.querySelector('script')?.textContent || '{}') as { labels?: unknown[]; series?: unknown[] };
              expectedColours = chartData.series?.length === 1
                ? Math.min(3, chartData.labels?.length || 0)
                : Math.min(3, chartData.series?.length || 0);
            } catch {
              expectedColours = 0;
            }
          }
          if (type === 'scatter') expectedColours = Math.min(3, colourNodes.length);
          if (type === 'heatmap') expectedColours = 1;
          if (type === 'radar' || type === 'stacked-bar') {
            try {
              const chartData = JSON.parse(chart.querySelector('script')?.textContent || '{}') as { series?: unknown[] };
              expectedColours = Math.min(2, chartData.series?.length || 0);
            } catch {
              expectedColours = 0;
            }
          }
          const requiredSelector: Record<string, string> = {
            scatter: '.scatter-point', radar: '.radar-series', 'stacked-bar': '.stack-segment', heatmap: '.heatmap-cell',
          };
          const semanticNodesMissing = Boolean(type && requiredSelector[type] && !chart.querySelector(requiredSelector[type]));
          const colourInvalid = expectedColours > 1 && colours.size < expectedColours;
          const zeroCanvas = svg ? svg.viewBox.baseVal.width < 80 || svg.viewBox.baseVal.height < 80 : false;
          return rect.width < 120 || rect.height < 100 || !drawn || /NaN|Infinity/.test(content) || (drawn instanceof SVGElement && drawn.getBoundingClientRect().width < 80) || zeroCanvas || colourInvalid || semanticNodesMissing || rankingTextClipped;
        });
        const tables = Array.from(slide.querySelectorAll<HTMLTableElement>('table.tbl'));
        const tableInvalid = tables.some(table => table.rows.length < 2 || table.getBoundingClientRect().width < 180 || table.scrollWidth > table.clientWidth + 3);
        const problems = (window as typeof window & { diagramProblems?: Array<{ page?: number }> }).diagramProblems || [];
        return {
          blank: style.visibility !== 'visible' || Number(style.opacity) < 0.95 || visibleText.length < 8 || !bodyRect || bodyRect.width < 40 * scale || bodyRect.height < 20 * scale,
          navigation: active.length !== 1 || active[0] !== slide || slide.classList.contains('leaving'),
          overflow: overflowNodes.length > 0 || diagramTextOverflow || rankingTextOverflow,
          titleWrap: headingLines > 2.35,
          chart: chartInvalid || tableInvalid || problems.some(problem => problem.page === pageIndex + 1),
        };
      }, index);
      if (measurements.blank) issues.push({ page: index + 1, code: 'blank' });
      if (measurements.navigation) issues.push({ page: index + 1, code: 'navigation' });
      if (measurements.overflow) issues.push({ page: index + 1, code: 'overflow' });
      if (measurements.titleWrap) issues.push({ page: index + 1, code: 'title-wrap' });
      if (measurements.chart) issues.push({ page: index + 1, code: 'chart' });
      await page.screenshot({ path: path.join(directory, `p${String(index + 1).padStart(2, '0')}.png`) });
    }

    if (pages > 1) {
      await page.evaluate(iterations => {
        const deckWindow = window as typeof window & { show?: (index: number, revealAll?: boolean) => void };
        for (let count = 0; count < iterations; count += 1) {
          deckWindow.show?.(count % 2, true);
          deckWindow.show?.((count + 1) % 2, true);
        }
      }, 20);
      const rapidNavigationFailed = await page.evaluate(() => {
        const active = Array.from(document.querySelectorAll<HTMLElement>('.slide.active'));
        return active.length !== 1 || active[0].classList.contains('leaving') || Number(getComputedStyle(active[0]).opacity) < 0.95;
      });
      if (rapidNavigationFailed) issues.push({ page: 1, code: 'navigation' });
    }
    if (javascriptErrors.length) issues.push({ page: 0, code: 'javascript' });
    return { pages, issues, motionProfile: motionMetadata.profile, fingerprint: motionMetadata.fingerprint };
  } catch (error: unknown) {
    if (timedOut) throw new Error('PPT visual QA exceeded the 45 second limit');
    throw error;
  } finally {
    clearTimeout(deadline);
    await browser?.close().catch(() => undefined);
    await rm(directory, { recursive: true, force: true });
  }
}

let queue: Promise<void> = Promise.resolve();

async function serial<T>(task: () => Promise<T>): Promise<T> {
  const previous = queue;
  let release: () => void = () => undefined;
  queue = new Promise<void>(resolve => { release = resolve; });
  await previous;
  try {
    return await task();
  } finally {
    release();
  }
}

export async function qualityCheckDeck(html: Buffer): Promise<{ html: Buffer; report: DeckQaReport }> {
  return serial(async () => {
    const first = await inspect(html);
    if (first.issues.length === 0) return { html, report: { status: 'passed', pages: first.pages, compacted: false, motionStatus: first.fingerprint ? 'passed' : 'not-configured', motionProfile: first.motionProfile, fingerprint: first.fingerprint } };
    const retryable = first.issues.every(issue => issue.code === 'overflow' || issue.code === 'title-wrap');
    if (!retryable) throw new DeckQaError(first.issues);
    const compacted = compactHtml(html);
    const second = await inspect(compacted);
    if (second.issues.length) throw new DeckQaError(second.issues);
    return { html: compacted, report: { status: 'passed', pages: second.pages, compacted: true, motionStatus: second.fingerprint ? 'passed' : 'not-configured', motionProfile: second.motionProfile, fingerprint: second.fingerprint } };
  });
}
