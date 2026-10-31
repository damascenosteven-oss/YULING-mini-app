import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import test from 'node:test';
import { buildDeckHtml } from './builder';
import { createGoldenOutline } from './golden-fixture';
import { browserCandidates } from './platform';
import { DeckQaError, qualityCheckDeck } from './qa';
import { renderDeck, safeJson } from './renderer';
import { normalizeDeckOutline, type DeckOutline } from './schema';

const descriptiveUnit = '报名指数（演示）';
function rankingDeck(unit: string): DeckOutline {
  const deck = createGoldenOutline();
  delete deck.motionPlan;
  const index = deck.slides.findIndex(slide => slide.type === 'ranking');
  deck.slides[index] = {
    id: 'ranking-real-fit', type: 'ranking', variant: 'horizontal-bars', theme: 'blue',
    title: '课程需求热度排名', dataStatus: 'demo', unit,
    story: { question: '哪些课程优先开展？', claim: '数字工具与设备运维课程需求领先', implication: '依据演示数据核对优先级', focusKeys: ['数字工具应用'] },
    entries: ['数字工具应用', '设备运维基础', '数据分析入门', '质量管理实务', '客户沟通技巧', '外贸英语'].map((label, index) => ({ label, value: [92, 85, 78, 64, 58, 45][index], change: 0 })),
  };
  return normalizeDeckOutline(deck);
}
function ready(context: { skip: (reason: string) => void }): boolean {
  const engine = process.env.PPT_ENGINE_ROOT;
  const chrome = browserCandidates().find(candidate => existsSync(candidate));
  if (!engine || !existsSync(engine) || !chrome) { context.skip('Requires real Python engine and Chrome'); return false; }
  process.env.PPT_CHROME_PATH = chrome;
  return true;
}

test('ranking descriptive units remain complete in provenance without crowding inline values', () => {
  const deck = rankingDeck(descriptiveUnit);
  const before = structuredClone(deck);
  const rendered = renderDeck(deck);
  const page = rendered.slides.find(slide => slide.includes('data-chart="ranking"'))!;
  assert.ok(page.includes(`单位：${descriptiveUnit}`));
  assert.equal(page.split(descriptiveUnit).length - 1, 1);
  assert.match(page, /"unit":""/);
  assert.deepEqual(deck, before, 'rendering must preserve original data');
});

test('ranking short symbolic units preserve the existing inline representation', () => {
  for (const unit of ['', '分', '%', '元', '小时']) {
    const rendered = renderDeck(rankingDeck(unit));
    const page = rendered.slides.find(slide => slide.includes('data-chart="ranking"'))!;
    assert.ok(page.includes(`>92${unit}</b>`));
    assert.ok(page.includes(`"unit":"${unit}"`));
  }
});

test('ranking descriptive units preserve zero and signed values at entry-count boundaries', () => {
  for (const unit of ['报名指数（演示）', 'hours/person', '完整单位说明'.repeat(4)]) {
    for (const count of [3, 8]) {
      const deck = rankingDeck(unit);
      const ranking = deck.slides.find(slide => slide.type === 'ranking');
      assert.ok(ranking?.type === 'ranking' && ranking.variant === 'horizontal-bars');
      ranking.entries = Array.from({ length: count }, (_, i) => ({ label: `培训类别${i + 1}`, value: i - 2, change: i - 1 }));
      const before = structuredClone(deck);
      const page = renderDeck(deck).slides.find(slide => slide.includes('data-chart="ranking"'))!;
      assert.ok(page.includes(`单位：${unit}`));
      assert.ok(page.includes('"value":-2') && page.includes('"value":0'));
      assert.ok(page.includes('"unit":""'));
      assert.deepEqual(deck, before);
    }
  }
});

test('browser QA rejects deliberately squeezed ranking titles within otherwise valid cards', async context => {
  if (!ready(context)) return;
  const html = await buildDeckHtml(rankingDeck('分'));
  const broken = Buffer.from(html.toString().replace('</head>', '<style>.ai-podium-card strong{width:18px!important;max-width:18px!important}</style></head>'));
  await assert.rejects(() => qualityCheckDeck(broken), DeckQaError);
});

test('browser QA rejects ranking SVG value text clipped inside an otherwise valid chart', async context => {
  if (!ready(context)) return;
  const html = await buildDeckHtml(rankingDeck('分'));
  let injected = false;
  const broken = html.toString().replace(/(<figure[^>]*data-chart="ranking"[^>]*>\s*<script[^>]*>)([^<]+)(<\/script>)/g, (_match, head: string, json: string, tail: string) => {
    injected = true;
    return head + safeJson({ ...JSON.parse(json), unit: descriptiveUnit }) + tail;
  });
  assert.ok(injected, 'deliberate fault must reach the real chart input');
  await assert.rejects(() => qualityCheckDeck(Buffer.from(broken)), DeckQaError);
});

test('browser QA accepts a complete descriptive-unit ranking without dropping the original data', async context => {
  if (!ready(context)) return;
  const html = await buildDeckHtml(rankingDeck(descriptiveUnit));
  const checked = await qualityCheckDeck(html);
  assert.equal(checked.report.status, 'passed');
  assert.equal(checked.report.pages, 12);
  assert.match(checked.html.toString(), /单位：报名指数（演示）/);
});
