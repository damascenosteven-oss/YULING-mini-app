import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import test from 'node:test';
import { resolveMotionPlan, validateMotionPlan, motionHistory } from './motion';
import { deckOutlineSchema, type DeckOutline, type MotionMode } from './schema';
import { PRESENTATION_SKILLS, validateSkillDeck } from './skills';

function fixture(pages = 10): DeckOutline {
  return deckOutlineSchema.parse({
    title: '培训规划', audience: '测试人员', goal: '验证普通生成完整入口',
    skill: { id: 'data-research-report', version: 1, selectedBy: 'auto' },
    design: { narrative: 'proposal', mood: 'professional', palette: 'blue', density: 'balanced' },
    slides: [
      { id: 'cover', type: 'cover', variant: 'cinematic', theme: 'blue', title: '培训规划', tagline: '隔离模型样本' },
      ...Array.from({ length: pages - 2 }, (_, i) => ({ id: `points-${i}`, type: 'bullets', variant: i % 2 ? 'feature-list' : 'three-cards', theme: 'blue', title: '规划行动', items: ['核对需求并明确目标', '安排实践并逐项复核'] })),
      { id: 'closing', type: 'closing', variant: 'action-card', theme: 'blue', title: '下一步', summary: '内容仍需人工核验', actions: ['人工复核并试用'] },
    ],
  });
}
const prompt = '调查目前宁波就业市场，形成公开来源的十页培训汇报';
function valid(deck: DeckOutline) {
  assert.ok(deckOutlineSchema.safeParse(deck).success, 'randomization broke the outline structure');
  validateSkillDeck(deck);
  const plan = validateMotionPlan(deck);
  assert.ok(plan);
  const signature = createHash('sha256').update(`${deck.skill.id}@${deck.skill.version}|${deck.slides.map(s => `${s.type}:${s.variant}`).join('|')}`).digest('hex').slice(0, 12);
  assert.equal(plan.layoutSignature, signature, 'motion signature must describe actual pages');
}
function content(deck: DeckOutline) { return deck.slides.map(({ variant: _variant, ...slide }) => slide); }

test('known seed and 100 hex seeds across four modes preserve legal content', () => {
  const deck = fixture();
  const before = structuredClone(deck);
  valid(resolveMotionPlan(deck, { prompt, seedBase: '0000000000000001' }));
  for (const mode of ['auto', 'subtle', 'balanced', 'vivid'] as MotionMode[]) {
    for (let i = 0; i < 100; i++) {
      const next = resolveMotionPlan(deck, { prompt, mode, seedBase: i.toString(16).padStart(16, '0') });
      valid(next); assert.deepEqual(content(next), content(deck));
      assert.deepEqual(next.skill, deck.skill); assert.deepEqual(next.research, deck.research);
    }
  }
  assert.deepEqual(deck, before);
});

test('six/twelve pages and all skills retain process/tree/data compatibility', () => {
  for (const pages of [6, 12]) for (const id of [...Object.keys(PRESENTATION_SKILLS), 'legacy-general'] as DeckOutline['skill']['id'][]) {
    const deck = fixture(pages);
    deck.skill = { id, version: 1, selectedBy: id === 'legacy-general' ? 'legacy' : 'user' };
    deck.slides[1] = { id: 'process', type: 'process', title: '实施步骤', theme: 'mint', variant: 'flow', steps: Array.from({ length: 6 }, (_, i) => ({ title: `步骤${i + 1}`, description: '核对目标并验收' })) };
    deck.slides[2] = { id: 'tree', type: 'tree', title: '能力树', theme: 'blue', variant: 'mind-map', root: '目标', branches: [{ title: '业务', items: ['场景'] }, { title: '治理', items: ['审计'] }] };
    deck.slides[3] = { id: 'chart', type: 'chart', variant: 'bar', title: '演示对比', theme: 'blue', dataStatus: 'demo', labels: ['甲', '乙'], series: [{ name: '演示', values: [2, 3] }], story: { question: '哪里有差异？', claim: '乙较高', implication: '需人工复核', focusKeys: ['乙'] } };
    for (let i = 0; i < 12; i++) {
      const next = resolveMotionPlan(deck, { seedBase: `mixed-${i}` }); valid(next);
      assert.notEqual(next.slides[1].variant, 'ladder'); assert.deepEqual(content(next), content(deck));
    }
  }
});

test('hard exclusions exhaust both bounded rounds and preserve original-layout fallback', () => {
  const deck = fixture(); const excluded: string[] = []; let fallback = false; let ended = false;
  for (let i = 0; i <= 36; i++) {
    try {
      const next = resolveMotionPlan(deck, { seedBase: '0000000000000001', prompt, exclude: excluded });
      valid(next); assert.ok(!excluded.includes(next.motionPlan!.fingerprint));
      fallback ||= next.slides.every((s, j) => s.variant === deck.slides[j].variant);
      excluded.push(next.motionPlan!.fingerprint);
    } catch (error) {
      if (!(error instanceof Error) || error.message !== 'No valid motion candidate available') throw error;
      ended = true; break;
    }
  }
  assert.ok(fallback, 'must try original legal layouts'); assert.ok(ended, 'must fail after bounded candidates');
  assert.throws(() => resolveMotionPlan(deck, { seedBase: '0000000000000001', prompt, exclude: excluded }), /No valid motion candidate/);
});

test('refresh preserves pages, matches layout signature and excludes current/recent', () => {
  const first = resolveMotionPlan(fixture(), { seedBase: 'first' });
  const next = resolveMotionPlan(first, { seedBase: 'next', preserveLayouts: true, recent: [motionHistory(first.motionPlan!)], exclude: [first.motionPlan!.fingerprint] });
  valid(next); assert.deepEqual(next.slides, first.slides); assert.notEqual(next.motionPlan!.fingerprint, first.motionPlan!.fingerprint);
});

test('invalid inputs never enter fallback; unexpected validation errors propagate', () => {
  const invalid = fixture(); invalid.slides[2] = { ...invalid.slides[1], id: 'duplicate-layout-2' }; invalid.slides[3] = { ...invalid.slides[1], id: 'duplicate-layout-3' };
  assert.throws(() => resolveMotionPlan(invalid));
  const allowed = PRESENTATION_SKILLS['data-research-report'].allowed;
  const original = allowed.has; let calls = 0;
  allowed.has = function (value) { if (++calls > 10) throw new Error('unexpected-validator-fault'); return original.call(this, value); };
  try { assert.throws(() => resolveMotionPlan(fixture()), /unexpected-validator-fault/); }
  finally { allowed.has = original; }
});
