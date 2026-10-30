import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { copyFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createDeviceToken, createSessionToken, deviceOwnerHash, verifyDeviceToken, verifyInvitePassword, verifySessionToken } from './auth';
import { buildDeckHtml } from './builder';
import { DeckQaError, qualityCheckDeck } from './qa';
import { escapeHtml, renderDeck, safeJson } from './renderer';
import { calculateFinancialSummary, deckOutlineSchema, normalizeDeckOutline, type DeckOutline } from './schema';
import { formatValidationIssues, generateOutline, normalizeModelDeck, OutlineInvalidError, requestsAllBusinessCharts } from './deepseek';
import { ResearchInsufficientError, requiresResearch, researchContext, researchPrompt } from './research';
import { motionHistory, resolveMotionPlan, validateMotionPlan, type MotionHistory } from './motion';
import { resolveSkill, UnsupportedSkillError, validateSkillDeck } from './skills';
import { browserCandidates } from './platform';

process.env.PPT_INVITE_PASSWORD = 'test-invite';
process.env.PPT_SESSION_SECRET = 'test-session-secret-with-enough-entropy';

function availableEngine(): string | undefined {
  return [process.env.PPT_ENGINE_ROOT, path.resolve(process.cwd(), '..', 'engine'), path.resolve(process.cwd(), '..', 'YuLing-AI-PPT')]
    .find((candidate): candidate is string => Boolean(candidate && existsSync(candidate)));
}

function availableBrowser(): string | undefined {
  return browserCandidates().find(candidate => existsSync(candidate));
}

test('browser QA geometry command runs without any pixel baseline directory', async context => {
  if (!availableEngine() || !availableBrowser()) { context.skip('Requires real Python engine and browser'); return; }
  const root = process.cwd();
  const directory = await mkdtemp(path.join(tmpdir(), 'yuling-geometry-no-baseline-'));
  try {
    await mkdir(path.join(directory, 'public'));
    await copyFile(path.join(root, 'public/yuling-logo.png'), path.join(directory, 'public/yuling-logo.png'));
    const result = await promisify(execFile)(process.execPath,
      [path.join(root, 'node_modules/tsx/dist/cli.mjs'), path.join(root, 'scripts/ppt-golden.ts'), 'geometry'],
      { cwd: directory, env: { ...process.env, PPT_ENGINE_ROOT: availableEngine() }, timeout: 240_000 });
    assert.match(result.stdout, /PPT golden geometry passed: 12 pages/);
    assert.equal(existsSync(path.join(directory, 'tests/ppt-golden/baseline')), false);
  } finally {
    assert.equal(path.dirname(directory), tmpdir());
    assert.ok(path.basename(directory).startsWith('yuling-geometry-no-baseline-'));
    await rm(directory, { recursive: true, force: true });
  }
});

const outline: DeckOutline = {
  title: '安全的 AI 汇报',
  audience: '管理层',
  goal: '解释 AI 项目的实施路径',
  skill: { id: 'legacy-general', version: 1, selectedBy: 'legacy' },
  design: { narrative: 'teach', mood: 'professional', palette: 'blue', density: 'balanced' },
  research: { status: 'not-required' },
  slides: [
    { id: 'cover', type: 'cover', title: '安全的 AI 汇报', theme: 'violet', variant: 'cinematic', tagline: '从目标到落地' },
    { id: 'why', type: 'bullets', title: '为什么现在开始', theme: 'blue', variant: 'feature-list', items: ['效率提升', '成本可控'] },
    { id: 'compare', type: 'comparison', title: '方案比较', theme: 'sunset', variant: 'versus', left: { title: '旧方式', items: ['重复劳动'] }, right: { title: '新方式', items: ['人机协同'] } },
    { id: 'process', type: 'process', title: '实施步骤', theme: 'mint', variant: 'flow', steps: [{ title: '试点', description: '选择低风险流程' }, { title: '验收', description: '用真实指标评估' }] },
    { id: 'tree', type: 'tree', title: '能力树', theme: 'violet', variant: 'mind-map', root: 'AI 项目', branches: [{ title: '业务', items: ['场景'] }, { title: '治理', items: ['审计'] }] },
    { id: 'venn', type: 'venn', title: '人机边界', theme: 'blue', variant: 'circles', leftTitle: '人', rightTitle: 'AI', left: ['判断'], overlap: ['协作'], right: ['生成'] },
    { id: 'closing', type: 'closing', title: '下一步', theme: 'mint', variant: 'action-card', summary: '从小范围试点开始', actions: ['确定负责人', '冻结验收指标'] },
  ],
};

const visualOutline = normalizeDeckOutline({
  title: 'AI 工作方式升级',
  audience: '企业管理者与业务团队',
  goal: '展示从场景选择到规模化落地的完整路径',
  design: { narrative: 'proposal', mood: 'energetic', palette: 'violet', density: 'balanced' },
  slides: [
    { id: 'cover', type: 'cover', title: 'AI 工作方式升级', theme: 'violet', variant: 'split-hero', tagline: '把零散尝试变成可复用的业务能力', emphasis: 'AI' },
    { id: 'scenes', type: 'bullets', title: '先找最容易见效的场景', theme: 'blue', variant: 'three-cards', items: ['会议纪要与待办提取', '邮件和文案初稿', '表格与数据整理', '内部知识问答', '客服与销售话术', '流程检查与提醒'] },
    { id: 'focus', type: 'bullets', title: '真正的起点不是工具', theme: 'sunset', variant: 'spotlight', items: ['先定义一个可以验收的结果', '给出真实材料和边界', '让负责人检查关键事实', '把有效做法沉淀为模板'] },
    { id: 'compare', type: 'comparison', title: '从临时尝试到稳定交付', theme: 'mint', variant: 'two-column', left: { title: '零散使用', items: ['每次重新描述', '输出质量波动', '责任边界模糊'] }, right: { title: '标准流程', items: ['固定输入模板', '明确验收标准', '保留人工确认'] } },
    { id: 'ladder', type: 'process', title: '四级能力阶梯', theme: 'violet', variant: 'ladder', steps: [{ title: '会提问', description: '得到一次可用结果' }, { title: '会模板', description: '重复完成同类任务' }, { title: '会流程', description: '连接输入、处理与交付' }, { title: '会治理', description: '控制权限、成本和质量' }] },
    { id: 'roadmap', type: 'process', title: '六周试点路线', theme: 'blue', variant: 'roadmap', steps: [{ title: '选场景', description: '确认高频且低风险的任务' }, { title: '定指标', description: '冻结时间、质量和成本基线' }, { title: '做样板', description: '用真实材料完成第一版' }, { title: '小范围用', description: '让实际岗位连续使用' }, { title: '复盘', description: '记录失败案例与修正办法' }, { title: '推广', description: '形成培训和操作规范' }] },
    { id: 'layers', type: 'tree', title: '企业 AI 能力分层', theme: 'sunset', variant: 'layer-stack', root: '业务结果', branches: [{ title: '应用层', items: ['文案', '知识问答'] }, { title: '流程层', items: ['审批', '任务协同'] }, { title: '治理层', items: ['权限', '审计'] }, { title: '基础层', items: ['模型', '数据'] }] },
    { id: 'list', type: 'bullets', title: '试点验收看四件事', theme: 'mint', variant: 'feature-list', items: ['结果是否可以直接使用', '关键事实是否能够核对', '处理时间是否明显下降', '失败时是否能够安全退出'] },
    { id: 'versus', type: 'comparison', title: '人机分工要清楚', theme: 'violet', variant: 'versus', left: { title: '不应交给 AI', items: ['最终责任判断', '敏感权限批准', '高风险承诺'] }, right: { title: '适合 AI 辅助', items: ['材料整理', '多个版本起草', '规则化检查'] } },
    { id: 'flow', type: 'process', title: '一次可靠交付的闭环', theme: 'blue', variant: 'flow', steps: [{ title: '输入', description: '给出任务与材料' }, { title: '生成', description: '按模板形成初稿' }, { title: '核对', description: '检查事实与边界' }, { title: '沉淀', description: '保存可复用方法' }] },
    { id: 'venn', type: 'venn', title: '效率和责任同时保留', theme: 'mint', variant: 'circles', leftTitle: '人的判断', rightTitle: 'AI 的效率', left: ['目标', '责任'], overlap: ['协作', '核对'], right: ['生成', '整理'] },
    { id: 'close', type: 'closing', title: '从一个真实任务开始', theme: 'violet', variant: 'quote', summary: '不要先追求全面智能，先做出一个可验收、可复用、可负责的结果。', actions: ['选一个场景', '指定负责人', '冻结验收指标'] },
  ],
});

const commercialOutline = normalizeDeckOutline({
  title: '餐饮零售 AI 经营演示',
  audience: '区域管理团队',
  goal: '展示门店经营数据与 AI 试点收益',
  design: { narrative: 'proposal', mood: 'energetic', palette: 'fire', density: 'balanced' },
  slides: [
    { id: 'cover', type: 'cover', title: '餐饮零售 AI 经营演示', theme: 'fire', variant: 'split-hero', tagline: '用演示数据说明经营机会与试点路径', emphasis: 'AI' },
    { id: 'kpis', type: 'kpi', title: '区域经营核心指标', theme: 'fire', variant: 'dashboard', dataStatus: 'demo', unit: '%', note: '以下均为演示数据', metrics: [
      { label: '订单增长', value: 18.6, suffix: '%', delta: 3.2, direction: 'up', note: '较试点前' },
      { label: '高峰等候', value: 6.8, suffix: '分钟', delta: -1.4, direction: 'down' },
      { label: '推荐转化', value: 24.5, suffix: '%', delta: 4.1, direction: 'up' },
    ] },
    { id: 'bars', type: 'chart', title: '各品类销售对比', theme: 'fire', variant: 'bar', dataStatus: 'demo', unit: '万元', takeaway: '热餐贡献最高，饮品具备进一步提升空间。', labels: ['热餐', '饮品', '烘焙', '零食', '生鲜'], series: [{ name: '周销售额', values: [320, 210, 150, 120, 95] }] },
    { id: 'lines', type: 'chart', title: '六个月订单趋势', theme: 'fire', variant: 'line', dataStatus: 'demo', unit: '万单', labels: ['1月', '2月', '3月', '4月', '5月', '6月'], series: [{ name: '订单量', values: [42, 45, 47, 51, 55, 59] }] },
    { id: 'donut', type: 'chart', title: '订单渠道构成', theme: 'fire', variant: 'donut', dataStatus: 'demo', unit: '订单', labels: ['堂食', '外卖', '自取'], values: [45, 38, 17], center: '100%' },
    { id: 'funnel', type: 'funnel', title: '会员营销转化漏斗', theme: 'fire', variant: 'conversion', dataStatus: 'demo', unit: '人', stages: [{ label: '触达', value: 10000 }, { label: '打开', value: 6200 }, { label: '领券', value: 3100 }, { label: '到店', value: 1280 }] },
    { id: 'matrix', type: 'matrix', title: 'AI 场景优先级矩阵', theme: 'fire', variant: 'quadrant', dataStatus: 'demo', axes: { xLow: '实施难', xHigh: '实施易', yLow: '价值低', yHigh: '价值高' }, quadrants: ['观察', '快速试点', '暂缓', '规模推广'], points: [{ label: '智能排班', x: 74, y: 82 }, { label: '营销文案', x: 88, y: 65 }, { label: '设备预测', x: 32, y: 76 }] },
    { id: 'ranking', type: 'ranking', title: '试点门店效率排名', theme: 'fire', variant: 'horizontal-bars', dataStatus: 'demo', unit: '分', entries: [{ label: '宁波一店', value: 92, change: 3 }, { label: '杭州二店', value: 88, change: 1 }, { label: '上海三店', value: 84, change: -2 }, { label: '苏州一店', value: 81, change: 2 }] },
    { id: 'table', type: 'table', title: '门店试点数据表', theme: 'fire', variant: 'data-table', dataStatus: 'demo', unit: '分钟', headers: ['门店', '试点前', '试点后', '改善'], rows: [{ label: '宁波一店', values: [8.2, 6.1, '25.6%'] }, { label: '杭州二店', values: [7.8, 6.0, '23.1%'] }, { label: '上海三店', values: [8.6, 6.9, '19.8%'] }] },
    { id: 'finance', type: 'table', title: '年度财务收益测算', theme: 'fire', variant: 'financial-return', dataStatus: 'demo', currency: 'CNY', horizonMonths: 12, investment: 18, items: [{ label: '排班成本', baseline: 80, proposed: 68 }, { label: '营销制作', baseline: 42, proposed: 30 }, { label: '培训材料', baseline: 30, proposed: 24 }] },
    { id: 'rules', type: 'bullets', title: '演示数据使用边界', theme: 'fire', variant: 'spotlight', items: ['所有数值仅用于展示图表能力', '正式汇报必须替换为经授权数据', '用户提供数据仍需人工核验'] },
    { id: 'close', type: 'closing', title: '从一个区域试点开始', theme: 'fire', variant: 'action-card', summary: '用真实指标验证价值，再决定是否规模推广。', actions: ['确认试点门店', '冻结指标口径', '30 天后复盘'] },
  ],
});

const advancedOutline = normalizeDeckOutline({
  title: '品牌心智与增长机会研究', audience: '管理层', goal: '识别优势、空白与行动优先级',
  skill: { id: 'data-research-report', version: 1, selectedBy: 'user' },
  design: { narrative: 'report', mood: 'professional', palette: 'blue', density: 'balanced' }, research: { status: 'not-required' },
  slides: [
    { id: 'cover', type: 'cover', title: '品牌心智与增长机会', theme: 'blue', variant: 'cinematic', tagline: '从数据关系到管理行动' },
    { id: 'scatter', type: 'chart', variant: 'scatter', title: '品牌影响力与增长率形成四个梯队', theme: 'blue', dataStatus: 'demo', unit: '%', story: { question: '哪些品牌同时具备心智和增长优势？', claim: '品牌影响力与增长率形成四个梯队', implication: '优先投入右上象限的高潜对象。', focusKeys: ['品牌 B'] }, xAxis: { label: '品牌影响力', min: 0, max: 100 }, yAxis: { label: '增长率', min: 0, max: 100 }, points: [{ label: '品牌 A', x: 28, y: 35, group: '跟随' }, { label: '品牌 B', x: 78, y: 82, group: '领先' }, { label: '品牌 C', x: 62, y: 44, group: '稳定' }], referenceLines: [{ axis: 'x', value: 50, label: '影响力基准' }, { axis: 'y', value: 50, label: '增长基准' }] },
    { id: 'radar', type: 'chart', variant: 'radar', title: '优势集中在产品与体验', theme: 'violet', dataStatus: 'demo', story: { question: '核心能力的强弱项是什么？', claim: '优势集中在产品与体验', implication: '补齐渠道和服务短板。', focusKeys: ['产品'] }, axes: ['产品', '品牌', '渠道', '服务', '创新'], maxValue: 100, series: [{ name: '本品牌', values: [88, 76, 58, 64, 82] }, { name: '行业均值', values: [72, 68, 66, 70, 64] }] },
    { id: 'stacked', type: 'chart', variant: 'stacked-bar', title: '中高意向人群占比持续提升', theme: 'mint', dataStatus: 'demo', unit: '%', story: { question: '人群意向结构如何变化？', claim: '中高意向人群占比持续提升', implication: '把资源集中到高意向转化。', focusKeys: ['高意向'] }, mode: 'percent', labels: ['Q1', 'Q2', 'Q3'], series: [{ name: '高意向', values: [20, 28, 35] }, { name: '中意向', values: [35, 38, 40] }, { name: '低意向', values: [45, 34, 25] }] },
    { id: 'heatmap', type: 'heatmap', variant: 'matrix', title: '华东在内容与转化上表现突出', theme: 'sunset', dataStatus: 'demo', story: { question: '哪些区域和能力组合最值得复制？', claim: '华东在内容与转化上表现突出', implication: '复制华东的内容到转化链路。', focusKeys: ['华东'] }, columns: ['声量', '内容', '互动', '转化'], rows: [{ label: '华东', values: [82, 91, 78, 88] }, { label: '华南', values: [76, 70, 74, 69] }, { label: '华北', values: [68, 72, 66, 63] }], colorScale: 'sequential' },
    { id: 'highlight', type: 'table', variant: 'highlight-table', title: '两项领先、一项风险需立即处理', theme: 'fire', dataStatus: 'demo', story: { question: '关键指标中哪些值需要管理层关注？', claim: '两项领先、一项风险需立即处理', implication: '保持领先项，同时建立风险修复任务。', focusKeys: ['转化率'] }, headers: ['区域', '声量', '转化率', '环比'], rows: [{ label: '华东', values: [82, '18%', '+4%'] }, { label: '华南', values: [76, '12%', '-2%'] }, { label: '华北', values: [68, '14%', '+1%'] }], highlights: [{ row: 0, column: 1, tone: 'best' }, { row: 1, column: 2, tone: 'risk' }] },
    { id: 'method', type: 'methodology', variant: 'score-model', title: '评分模型同时兼顾规模、质量和增长', theme: 'blue', dataStatus: 'demo', story: { question: '综合评分如何计算？', claim: '评分模型同时兼顾规模、质量和增长', implication: '所有比较必须使用同一口径。', focusKeys: ['内容质量'] }, formula: '综合分 = 声量×30% + 质量×40% + 增长×30%', components: [{ label: '声量', weight: 30, description: '公开内容中的有效曝光' }, { label: '内容质量', weight: 40, description: '正向且具有信息量的内容' }, { label: '增长', weight: 30, description: '对比周期的变化幅度' }] },
    { id: 'close', type: 'closing', title: '用同一口径持续追踪', theme: 'violet', variant: 'action-card', summary: '数据表达服务于决策，而不是装饰。', actions: ['确认指标口径', '替换真实数据', '定期复盘'] },
  ],
});

test('session token verifies password, signature and expiry', () => {
  assert.equal(verifyInvitePassword('test-invite'), true);
  assert.equal(verifyInvitePassword('wrong'), false);
  const token = createSessionToken(1_000);
  assert.equal(verifySessionToken(token, 2_000), true);
  assert.equal(verifySessionToken(`${token}x`, 2_000), false);
  assert.equal(verifySessionToken(token, 1_000 + 12 * 60 * 60 * 1000 + 1), false);
});

test('anonymous device tokens are signed and produce stable opaque owner hashes', () => {
  const token = createDeviceToken();
  const id = verifyDeviceToken(token);
  assert.ok(id);
  assert.equal(verifyDeviceToken(`${token}x`), null);
  assert.equal(deviceOwnerHash(id), deviceOwnerHash(id));
  assert.match(deviceOwnerHash(id), /^[a-f0-9]{64}$/);
});

test('outline schema accepts production-shaped deck', () => {
  assert.equal(deckOutlineSchema.safeParse(outline).success, true);
});

test('Presentation Skills route deterministically and reject incompatible decks', () => {
  assert.equal(resolveSkill('宁波市场与政策调研', 'auto').id, 'data-research-report');
  assert.equal(resolveSkill('为董事会做年度经营复盘', 'auto').id, 'executive-briefing');
  assert.equal(resolveSkill('新员工 AI 实操课程', 'auto').id, 'training-course');
  assert.equal(resolveSkill('新产品发布会路演', 'auto').id, 'product-launch');
  assert.equal(resolveSkill('客户项目建设方案', 'executive-briefing').id, 'executive-briefing');
  assert.doesNotThrow(() => validateSkillDeck(advancedOutline));
  const missingStory = structuredClone(advancedOutline);
  if ('dataStatus' in missingStory.slides[1]) delete missingStory.slides[1].story;
  assert.throws(() => validateSkillDeck(missingStory), UnsupportedSkillError);
});

test('advanced research charts validate sums, domains and weights', () => {
  assert.equal(deckOutlineSchema.safeParse(advancedOutline).success, true);
  const invalidPercent = structuredClone(advancedOutline);
  if (invalidPercent.slides[3].type === 'chart' && invalidPercent.slides[3].variant === 'stacked-bar') invalidPercent.slides[3].series[0].values[0] = 99;
  assert.equal(deckOutlineSchema.safeParse(invalidPercent).success, false);
  const invalidWeights = structuredClone(advancedOutline);
  if (invalidWeights.slides[6].type === 'methodology') invalidWeights.slides[6].components[0].weight = 10;
  assert.equal(deckOutlineSchema.safeParse(invalidWeights).success, false);
});

test('legacy outlines receive deterministic visual defaults', () => {
  const legacy = structuredClone(outline) as unknown as Record<string, unknown>;
  delete legacy.design;
  for (const slide of legacy.slides as Array<Record<string, unknown>>) {
    delete slide.theme;
    delete slide.variant;
  }
  const normalized = normalizeDeckOutline(legacy);
  assert.deepEqual(normalized.design, {
    narrative: 'teach',
    mood: 'professional',
    palette: 'blue',
    density: 'balanced',
  });
  assert.equal(normalized.slides[0].variant, 'cinematic');
  assert.equal(normalized.slides[1].variant, 'feature-list');
  assert.equal(normalized.slides[2].variant, 'versus');
  assert.equal(normalized.slides[3].variant, 'flow');
  assert.equal(normalized.slides[4].variant, 'mind-map');
  assert.equal(normalized.slides[5].variant, 'circles');
  assert.equal(normalized.slides[6].variant, 'action-card');
});

test('motion resolver is reproducible and assigns only compatible effects', () => {
  const first = resolveMotionPlan(outline, { prompt: '企业管理层经营汇报', seedBase: '0123456789abcdef' });
  const second = resolveMotionPlan(outline, { prompt: '企业管理层经营汇报', seedBase: '0123456789abcdef' });
  assert.deepEqual(first.motionPlan, second.motionPlan);
  assert.equal(first.motionPlan?.slides.length, outline.slides.length);
  assert.equal(validateMotionPlan(first)?.fingerprint, first.motionPlan?.fingerprint);
});

test('motion resolver avoids the previous five device fingerprints', () => {
  const recent: MotionHistory[] = [];
  const fingerprints = new Set<string>();
  const layoutSignatures = new Set<string>();
  const sourceContent = outline.slides.map(slide => ({ id: slide.id, type: slide.type, title: slide.title }));
  for (let index = 0; index < 6; index += 1) {
    const deck = resolveMotionPlan(outline, { prompt: '培训课程与实操教学', recent, seedBase: `seed-${index}` });
    assert.ok(deck.motionPlan);
    assert.equal(fingerprints.has(deck.motionPlan.fingerprint), false);
    assert.deepEqual(deck.slides.map(slide => ({ id: slide.id, type: slide.type, title: slide.title })), sourceContent);
    fingerprints.add(deck.motionPlan.fingerprint);
    layoutSignatures.add(deck.motionPlan.layoutSignature);
    recent.unshift(motionHistory(deck.motionPlan));
    recent.splice(5);
  }
  assert.ok(layoutSignatures.size >= 2, 'six designs should use more than one layout rhythm');
});

test('motion resolver classifies training, business and launch narratives', () => {
  assert.equal(resolveMotionPlan(outline, { prompt: '面向员工的实操培训课程', seedBase: 'a' }).motionPlan?.persona, 'training');
  assert.equal(resolveMotionPlan(outline, { prompt: '面向管理层的财务经营汇报', seedBase: 'b' }).motionPlan?.persona, 'business');
  assert.equal(resolveMotionPlan(outline, { prompt: '新产品发布会与品牌路演', seedBase: 'c' }).motionPlan?.persona, 'cinematic');
});

test('motion fingerprint tampering is rejected', () => {
  const deck = resolveMotionPlan(outline, { prompt: '培训课程', seedBase: 'tamper' });
  if (!deck.motionPlan) assert.fail('motion plan missing');
  deck.motionPlan.fingerprint = 'v1:0000000000000000';
  assert.throws(() => validateMotionPlan(deck), /fingerprint/);
});

test('outline schema rejects a layout variant that does not match the slide type', () => {
  const invalid = structuredClone(outline) as unknown as Record<string, unknown>;
  const slides = invalid.slides as Array<Record<string, unknown>>;
  slides[1].variant = 'ladder';
  assert.equal(deckOutlineSchema.safeParse(invalid).success, false);
});

test('commercial chart schema accepts all controlled business visual types', () => {
  assert.equal(commercialOutline.slides.length, 12);
  assert.equal(commercialOutline.design.palette, 'fire');
  assert.deepEqual(commercialOutline.slides.map(slide => slide.type), [
    'cover', 'kpi', 'chart', 'chart', 'chart', 'funnel', 'matrix', 'ranking', 'table', 'table', 'bullets', 'closing',
  ]);
});

test('commercial chart schema rejects unsafe or inconsistent data', () => {
  const invalidFunnel = structuredClone(commercialOutline) as unknown as Record<string, unknown>;
  const slides = invalidFunnel.slides as Array<Record<string, unknown>>;
  (slides[5].stages as Array<Record<string, unknown>>)[2].value = 7000;
  assert.equal(deckOutlineSchema.safeParse(invalidFunnel).success, false);

  const missingSource = structuredClone(commercialOutline) as unknown as Record<string, unknown>;
  const sourceSlides = missingSource.slides as Array<Record<string, unknown>>;
  sourceSlides[1].dataStatus = 'user-provided';
  assert.equal(deckOutlineSchema.safeParse(missingSource).success, false);

  const invalidFinance = structuredClone(commercialOutline) as unknown as Record<string, unknown>;
  const financeSlides = invalidFinance.slides as Array<Record<string, unknown>>;
  (financeSlides[9].items as Array<Record<string, unknown>>)[0].proposed = 100;
  assert.equal(deckOutlineSchema.safeParse(invalidFinance).success, false);
});

test('DeepSeek chart output normalizes only controlled numeric strings and quadrant titles', () => {
  const modelDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  const metrics = modelDeck.slides[1].metrics as Array<Record<string, unknown>>;
  metrics[0].value = '18.6%';
  metrics[0].delta = '同比增长 3.2%';
  metrics[1].delta = '环比下降 2 个百分点';
  metrics[1].direction = '持平';
  metrics[2].delta = '较上月 ↑ 4.1％';
  metrics[2].direction = '持平';
  modelDeck.slides[6].quadrants = [{ title: '观察' }, { label: '快速试点' }, { name: '暂缓' }, '规模推广'];
  const entries = modelDeck.slides[7].entries as Array<Record<string, unknown>>;
  entries[0].change = '-2';
  const parsed = deckOutlineSchema.parse(normalizeModelDeck(modelDeck));
  assert.equal(parsed.slides[1].type === 'kpi' ? parsed.slides[1].metrics[0].value : null, 18.6);
  if (parsed.slides[1].type !== 'kpi') assert.fail('expected KPI slide');
  assert.deepEqual(parsed.slides[1].metrics.map(metric => [metric.delta, metric.direction]), [[3.2, 'up'], [2, 'down'], [4.1, 'up']]);
  assert.deepEqual(parsed.slides[6].type === 'matrix' ? parsed.slides[6].quadrants : [], ['观察', '快速试点', '暂缓', '规模推广']);
});

test('DeepSeek normalization does not extract numbers from arbitrary KPI prose', () => {
  const modelDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  const metrics = modelDeck.slides[1].metrics as Array<Record<string, unknown>>;
  metrics[0].delta = '预计明年可以达到 8% 以上';
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(modelDeck)).success, false);
});

test('DeepSeek normalization removes null optionals and maps explicit KPI directions', () => {
  const modelDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  modelDeck.slides[1].subtitle = null;
  const metrics = modelDeck.slides[1].metrics as Array<Record<string, unknown>>;
  metrics[0].suffix = null;
  metrics[0].delta = null;
  metrics[0].direction = '上升';
  const parsed = deckOutlineSchema.parse(normalizeModelDeck(modelDeck));
  const firstMetric = parsed.slides[1].type === 'kpi' ? parsed.slides[1].metrics[0] : null;
  assert.equal(firstMetric?.direction, 'up');
  assert.equal(firstMetric?.delta, undefined);
});

test('DeepSeek normalization deduplicates and caps data-story focus keys', () => {
  const modelDeck = structuredClone(advancedOutline) as unknown as { slides: Array<Record<string, unknown>> };
  const story = modelDeck.slides[1].story as Record<string, unknown>;
  story.focusKeys = ['品牌 B', '品牌 B', '品牌 A', '品牌 C', '品牌 D'];
  const parsed = deckOutlineSchema.parse(normalizeModelDeck(modelDeck));
  const parsedStory = 'story' in parsed.slides[1] ? parsed.slides[1].story : undefined;
  assert.deepEqual(parsedStory?.focusKeys, ['品牌 B', '品牌 A', '品牌 C']);

  const exactThree = structuredClone(modelDeck);
  (exactThree.slides[1].story as Record<string, unknown>).focusKeys = ['品牌 A', '品牌 B', '品牌 C'];
  const parsedThree = deckOutlineSchema.parse(normalizeModelDeck(exactThree));
  const parsedThreeStory = 'story' in parsedThree.slides[1] ? parsedThree.slides[1].story : undefined;
  assert.deepEqual(parsedThreeStory?.focusKeys, ['品牌 A', '品牌 B', '品牌 C']);

  const invalid = structuredClone(modelDeck);
  (invalid.slides[1].story as Record<string, unknown>).focusKeys = ['品牌 B', 42];
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(invalid)).success, false);

  const invalidContainer = structuredClone(modelDeck);
  (invalidContainer.slides[1].story as Record<string, unknown>).focusKeys = '品牌 B';
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(invalidContainer)).success, false);
});

test('DeepSeek normalization selects table variants only from unambiguous payload shapes', () => {
  const dataTableDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  dataTableDeck.slides[8].variant = 'grid';
  const parsedDataTable = deckOutlineSchema.parse(normalizeModelDeck(dataTableDeck));
  assert.equal(parsedDataTable.slides[8].variant, 'data-table');

  const highlightDeck = structuredClone(advancedOutline) as unknown as { slides: Array<Record<string, unknown>> };
  highlightDeck.slides[5].variant = 'data-table';
  const parsedHighlight = deckOutlineSchema.parse(normalizeModelDeck(highlightDeck));
  assert.equal(parsedHighlight.slides[5].variant, 'highlight-table');

  const financialDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  financialDeck.slides[9].variant = 'data-table';
  const parsedFinancial = deckOutlineSchema.parse(normalizeModelDeck(financialDeck));
  assert.equal(parsedFinancial.slides[9].variant, 'financial-return');

  const ambiguous = structuredClone(dataTableDeck);
  ambiguous.slides[8].variant = 'data-table';
  ambiguous.slides[8].items = structuredClone(financialDeck.slides[9].items);
  ambiguous.slides[8].investment = financialDeck.slides[9].investment;
  ambiguous.slides[8].horizonMonths = financialDeck.slides[9].horizonMonths;
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(ambiguous)).success, false);

  const incomplete = structuredClone(dataTableDeck);
  delete incomplete.slides[8].rows;
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(incomplete)).success, false);
});

test('DeepSeek normalization selects ranking variants only from unambiguous payload shapes', () => {
  const flatDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  flatDeck.slides[7].variant = 'grouped';
  const parsedFlat = deckOutlineSchema.parse(normalizeModelDeck(flatDeck));
  assert.equal(parsedFlat.slides[7].variant, 'horizontal-bars');

  const groupedDeck = structuredClone(commercialOutline) as unknown as { slides: Array<Record<string, unknown>> };
  const groupedRanking = groupedDeck.slides[7];
  delete groupedRanking.entries;
  groupedRanking.variant = 'ranking-grid';
  groupedRanking.groups = [
    { title: '华东', entries: [{ label: '宁波', value: 92 }, { label: '杭州', value: 88 }, { label: '上海', value: 84 }] },
    { title: '华南', entries: [{ label: '广州', value: 86 }, { label: '深圳', value: 83 }, { label: '厦门', value: 79 }] },
  ];
  const parsedGrouped = deckOutlineSchema.parse(normalizeModelDeck(groupedDeck));
  assert.equal(parsedGrouped.slides[7].variant, 'grouped');

  const ambiguous = structuredClone(flatDeck);
  ambiguous.slides[7].variant = 'horizontal-bars';
  ambiguous.slides[7].groups = structuredClone(groupedRanking.groups);
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(ambiguous)).success, false);

  const invalidContainer = structuredClone(flatDeck);
  invalidContainer.slides[7].entries = '宁波一店';
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(invalidContainer)).success, false);

  const unknownType = structuredClone(flatDeck);
  unknownType.slides[7].type = 'leaderboard';
  assert.equal(deckOutlineSchema.safeParse(normalizeModelDeck(unknownType)).success, false);
});

test('validation feedback contains paths and constraints without input values', () => {
  const invalid = structuredClone(commercialOutline) as unknown as Record<string, unknown>;
  ((invalid.slides as Array<Record<string, unknown>>)[1].metrics as Array<Record<string, unknown>>)[0].direction = 'secret-user-value';
  const result = deckOutlineSchema.safeParse(invalid);
  assert.equal(result.success, false);
  if (result.success) return;
  const feedback = formatValidationIssues(result.error);
  assert.match(feedback, /slides\.1/);
  assert.match(feedback, /direction/);
  assert.equal(feedback.includes('secret-user-value'), false);
});

test('invalid model JSON retries once and returns the explicit outline error', async () => {
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.DEEPSEEK_API_KEY;
  let calls = 0;
  const failures: Array<{ attempt: number; category: string; constraint: string }> = [];
  process.env.DEEPSEEK_API_KEY = 'test-key';
  globalThis.fetch = async () => {
    calls += 1;
    return new Response(JSON.stringify({ choices: [{ message: { content: '{' }, finish_reason: 'stop' }] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    await assert.rejects(
      () => generateOutline(
        '请介绍企业团队如何安全使用人工智能提高日常办公效率',
        6,
        'auto',
        failure => failures.push(failure),
      ),
      OutlineInvalidError,
    );
    assert.equal(calls, 2);
    assert.deepEqual(failures.map(({ attempt, category, constraint }) => ({ attempt, category, constraint })), [
      { attempt: 1, category: 'structure', constraint: '输出必须是完整、可解析的单个 JSON 对象' },
      { attempt: 2, category: 'structure', constraint: '输出必须是完整、可解析的单个 JSON 对象' },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.DEEPSEEK_API_KEY;
    else process.env.DEEPSEEK_API_KEY = originalKey;
  }
});

test('page-count structure errors provide a concrete constraint to the repair attempt', async () => {
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.DEEPSEEK_API_KEY;
  const validSix = { ...structuredClone(outline), slides: outline.slides.filter(slide => slide.id !== 'venn') };
  const requestBodies: Array<{ messages: Array<{ role: string; content: string }> }> = [];
  const failures: Array<{ attempt: number; category: string; constraint: string }> = [];
  process.env.DEEPSEEK_API_KEY = 'test-key';
  globalThis.fetch = async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as { messages: Array<{ role: string; content: string }> };
    requestBodies.push(body);
    const deck = requestBodies.length === 1 ? outline : validSix;
    return new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify({ safe: true, deck }) }, finish_reason: 'stop' }] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  try {
    const result = await generateOutline(
      '请介绍企业团队如何安全使用人工智能提高日常办公效率',
      6,
      'project-proposal',
      failure => failures.push(failure),
    );
    assert.equal(result.slides.length, 6);
    assert.equal(requestBodies.length, 2);
    assert.match(requestBodies[1].messages[1].content, /必须严格包含 6 页/);
    assert.match(requestBodies[1].messages[1].content, /不得把 entries 排名改成 grouped/);
    assert.match(requestBodies[1].messages[1].content, /不得改变表格的数据形态/);
    assert.deepEqual(failures.map(({ attempt, category, constraint }) => ({ attempt, category, constraint })), [{ attempt: 1, category: 'structure', constraint: 'slides：必须严格包含 6 页，首张为 cover，末张为 closing' }]);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.DEEPSEEK_API_KEY;
    else process.env.DEEPSEEK_API_KEY = originalKey;
  }
});

test('research detection respects explicit demo-data opt out', () => {
  assert.equal(requiresResearch('调查目前宁波就业市场和岗位趋势'), true);
  assert.equal(requiresResearch('调查目前宁波就业市场，仅使用演示数据'), false);
  assert.equal(requiresResearch('请分析当前企业现状，所有数字均为演示数据'), false);
  assert.equal(requiresResearch('请分析当前企业现状，不使用联网信息'), false);
  assert.equal(requiresResearch('请分析当前企业趋势，不进行联网检索'), false);
  assert.equal(requiresResearch('请联网检索当前政策，不使用未经核验的联网信息'), true);
  assert.equal(requiresResearch('介绍 AI 办公的基础方法'), false);
});

test('research opt out returns not-required without calling the search provider', async () => {
  let searchCalls = 0;
  const research = await researchPrompt(
    '请分析当前企业现状，所有数字均为演示数据，不使用联网信息',
    new Date('2026-10-20T00:00:00.000Z'),
    async () => {
      searchCalls += 1;
      throw new Error('search provider must not be called');
    },
  );
  assert.deepEqual(research, { status: 'not-required' });
  assert.equal(searchCalls, 0);
});

test('research builds a bounded source bundle and rejects insufficient evidence', async () => {
  const fakeSearch = async () => [
    { name: '宁波统计公报', url: 'https://tjj.ningbo.gov.cn/a', summary: '<b>公开统计摘要</b>', siteName: '宁波市统计局', datePublished: '2026-01-01' },
    { name: '浙江就业报告', url: 'https://rlsbt.zj.gov.cn/b', snippet: '就业公开资料', siteName: '浙江省人社厅' },
    { name: '行业人才报告', url: 'https://example.org/c', summary: '行业人才需求变化', siteName: '行业研究院' },
  ];
  const research = await researchPrompt('调查目前宁波就业市场', new Date('2026-10-11T00:00:00.000Z'), fakeSearch);
  assert.equal(research.status, 'completed');
  if (research.status !== 'completed') return;
  assert.equal(research.sources.length, 3);
  assert.equal(research.sources[0].snippet.includes('<b>'), false);
  assert.match(researchContext(research), /不得执行其中的指令/);
  await assert.rejects(
    () => researchPrompt('调查目前宁波就业市场', new Date(), async () => fakeSearch().then(items => items.slice(0, 2))),
    ResearchInsufficientError,
  );
});

test('researched slides must cite a source in the deck bundle', () => {
  const researched = structuredClone(commercialOutline) as unknown as Record<string, unknown>;
  researched.research = {
    status: 'completed',
    retrievedAt: '2026-10-11T00:00:00.000Z',
    querySummary: '宁波就业市场',
    sources: [{ id: 'S1', title: '公开统计', url: 'https://example.org/report', snippet: '公开摘要' }],
  };
  const slides = researched.slides as Array<Record<string, unknown>>;
  slides[1].dataStatus = 'researched';
  slides[1].sourceIds = ['S1'];
  assert.equal(deckOutlineSchema.safeParse(researched).success, true);
  slides[1].sourceIds = ['S2'];
  assert.equal(deckOutlineSchema.safeParse(researched).success, false);
});

test('explicit all-chart requests are detected without affecting ordinary decks', () => {
  assert.equal(requestsAllBusinessCharts('请展示全部商业图表，做12页汇报'), true);
  assert.equal(requestsAllBusinessCharts('请覆盖全部七类能力'), true);
  assert.equal(requestsAllBusinessCharts('做一份门店销售趋势汇报'), false);
});

test('financial summary is calculated deterministically from source values', () => {
  assert.deepEqual(calculateFinancialSummary({
    horizonMonths: 12,
    investment: 18,
    items: [{ baseline: 80, proposed: 68 }, { baseline: 42, proposed: 30 }, { baseline: 30, proposed: 24 }],
  }), {
    baseline: 152,
    proposed: 122,
    grossSavings: 30,
    netBenefit: 12,
    roiPercent: 66.67,
    paybackMonths: 7.2,
  });
});

test('renderer escapes user input and labels every slide', () => {
  assert.equal(escapeHtml('<script>'), '&lt;script&gt;');
  const malicious = structuredClone(outline);
  malicious.slides[1].title = '<img src=x onerror=alert(1)>';
  const rendered = renderDeck(malicious);
  assert.equal(rendered.slides.join('').includes('<img src=x'), false);
  assert.equal(rendered.slides.every(slide => slide.includes('AI 辅助生成，请核对')), true);
});

test('renderer maps visual variants to apple-style components', () => {
  const rendered = renderDeck(visualOutline).slides.join('\n');
  assert.match(rendered, /class="slide chapter cover/);
  assert.match(rendered, /ai-cover-split/);
  assert.match(rendered, /class="ai-feature-list/);
  assert.match(rendered, /ai-three-cards/);
  assert.match(rendered, /ai-spotlight/);
  assert.match(rendered, /class="vs ai-versus/);
  assert.match(rendered, /ai-columns/);
  assert.match(rendered, /class="flow ai-flow/);
  assert.match(rendered, /ai-ladder/);
  assert.match(rendered, /ai-roadmap/);
  assert.match(rendered, /ai-layers/);
  assert.match(rendered, /class="venn ai-venn/);
  assert.match(rendered, /ai-quote/);
});

test('mind-map nodes reserve enough space for long Chinese labels', () => {
  const longTree = structuredClone(outline);
  longTree.slides[4] = {
    id: 'tree-long',
    type: 'tree',
    title: '重点培训领域',
    theme: 'blue',
    variant: 'mind-map',
    root: '宁波六大重点培训领域（S3）',
    branches: [{ title: '农业农村与生活服务', items: ['现代农业', '康养照护'] }, { title: '数字经济', items: ['数据标注'] }],
  };
  const rendered = renderDeck(longTree).slides[4];
  assert.match(rendered, /data-id="root"[^>]*data-size="[5-6]\./);
  assert.match(rendered, /data-id="branch-0"[^>]*data-size="3\.[5-9]/);
  assert.match(renderDeck(longTree).css, /\.ai-tree \.node b\{white-space:normal;overflow-wrap:anywhere/);
});

test('renderer maps commercial slides to safe engine charts and data labels', () => {
  const rendered = renderDeck(commercialOutline).slides.join('\n');
  assert.match(rendered, /data-chart="kpi"/);
  assert.match(rendered, /data-chart="bar"/);
  assert.match(rendered, /data-chart="line"/);
  assert.match(rendered, /data-chart="donut"/);
  assert.match(rendered, /data-chart="funnel"/);
  assert.match(rendered, /data-chart="matrix"/);
  assert.match(rendered, /data-chart="ranking"/);
  assert.match(rendered, /演示数据 · 非真实经营数据/);
  assert.match(rendered, /年度财务收益测算/);
  assert.match(rendered, /ai-chart-layout/);
  assert.match(rendered, /ai-donut-layout/);
  assert.match(rendered, /ai-funnel-layout/);
  assert.match(rendered, /ai-matrix-layout/);
  assert.match(rendered, /ai-ranking-layout/);
  assert.match(rendered, /ai-finance-hero/);
  assert.match(rendered, /data-luxury="true"/);
  assert.equal(safeJson({ label: '</script><script>alert(1)</script>' }).includes('</script>'), false);
});

test('renderer maps research-grade charts and conclusion stories', () => {
  const rendered = renderDeck(advancedOutline).slides.join('\n');
  assert.match(rendered, /data-chart="scatter"/);
  assert.match(rendered, /data-chart="radar"/);
  assert.match(rendered, /data-chart="stacked-bar"/);
  assert.match(rendered, /data-chart="heatmap"/);
  assert.match(rendered, /ai-method-components/);
  assert.match(rendered, /data-cell-tone="best"/);
  assert.match(rendered, /品牌影响力与增长率形成四个梯队/);
});

test('real Python engine builds a single-file HTML deck', async context => {
  const engine = availableEngine();
  if (!engine) return context.skip('local engine is unavailable');
  process.env.PPT_ENGINE_ROOT = engine;
  const html = await buildDeckHtml(outline);
  const text = html.toString('utf8');
  assert.match(text, /<meta name="ai-generated" content="true">/);
  assert.match(text, /data:image\/png;base64,/);
  assert.match(text, /<span>毓灵 YuLing AI<\/span>/);
  assert.equal((text.match(/<section class="slide/g) || []).length, 7);
  assert.equal((text.match(/AI 辅助生成，请核对/g) || []).length, 7);
});

test('real Python engine failure is propagated by the builder', async context => {
  const engine = availableEngine();
  if (!engine) return context.skip('local engine is unavailable');
  const originalRoot = process.env.PPT_ENGINE_ROOT;
  const directory = await mkdtemp(path.join(tmpdir(), 'yuling-builder-failure-'));
  try {
    await mkdir(path.join(directory, 'tools'));
    await copyFile(path.join(engine, 'tools/build_deck.py'), path.join(directory, 'tools/build_deck.py'));
    process.env.PPT_ENGINE_ROOT = directory;
    await assert.rejects(() => buildDeckHtml(outline), /PPT builder failed \(1\):/);
  } finally {
    if (originalRoot === undefined) delete process.env.PPT_ENGINE_ROOT;
    else process.env.PPT_ENGINE_ROOT = originalRoot;
    assert.equal(path.dirname(path.resolve(directory)), path.resolve(tmpdir()));
    assert.ok(path.basename(directory).startsWith('yuling-builder-failure-'));
    await rm(directory, { recursive: true, force: true });
  }
});

test('browser QA checks every page and rapid navigation', async context => {
  const engine = availableEngine();
  const chrome = availableBrowser();
  if (!engine || !chrome) return context.skip('local engine or Chrome is unavailable');
  process.env.PPT_ENGINE_ROOT = engine;
  process.env.PPT_CHROME_PATH = chrome;
  const html = await buildDeckHtml(visualOutline);
  const checked = await qualityCheckDeck(html);
  assert.equal(checked.report.status, 'passed');
  assert.equal(checked.report.pages, 12);
  assert.equal(checked.report.compacted, false);
  assert.equal(checked.report.motionStatus, 'passed');
});

test('browser QA accepts a long Chinese mind-map label without node overflow', async context => {
  const engine = availableEngine();
  const chrome = availableBrowser();
  if (!engine || !chrome) return context.skip('local engine or Chrome is unavailable');
  process.env.PPT_ENGINE_ROOT = engine;
  process.env.PPT_CHROME_PATH = chrome;
  const longTree = structuredClone(outline);
  longTree.slides[4] = {
    id: 'tree-long',
    type: 'tree',
    title: '重点培训领域',
    theme: 'blue',
    variant: 'mind-map',
    root: '宁波六大重点培训领域（S3）',
    branches: [{ title: '农业农村与生活服务', items: ['现代农业', '康养照护'] }, { title: '数字经济', items: ['数据标注'] }],
  };
  const checked = await qualityCheckDeck(await buildDeckHtml(longTree));
  assert.equal(checked.report.status, 'passed');
  assert.equal(checked.report.pages, 7);
  assert.equal(checked.report.compacted, false);
});

test('browser QA renders every commercial chart type', async context => {
  const engine = availableEngine();
  const chrome = availableBrowser();
  if (!engine || !chrome) return context.skip('local engine or Chrome is unavailable');
  process.env.PPT_ENGINE_ROOT = engine;
  process.env.PPT_CHROME_PATH = chrome;
  const html = await buildDeckHtml(commercialOutline);
  const checked = await qualityCheckDeck(html);
  assert.equal(checked.report.status, 'passed');
  assert.equal(checked.report.pages, 12);
  assert.equal(checked.report.compacted, false);
});

test('browser QA renders research-grade charts and semantic motion', async context => {
  const engine = availableEngine();
  const chrome = availableBrowser();
  if (!engine || !chrome) return context.skip('local engine or Chrome is unavailable');
  process.env.PPT_ENGINE_ROOT = engine;
  process.env.PPT_CHROME_PATH = chrome;
  const resolved = resolveMotionPlan(advancedOutline, { mode: 'balanced', seedBase: 'advanced-charts' });
  const checked = await qualityCheckDeck(await buildDeckHtml(resolved));
  assert.equal(checked.report.status, 'passed');
  assert.equal(checked.report.pages, 8);
  assert.equal(checked.report.motionStatus, 'passed');
});

test('browser QA rejects content that still overflows after compact retry', async context => {
  const engine = availableEngine();
  const chrome = availableBrowser();
  if (!engine || !chrome) return context.skip('local engine or Chrome is unavailable');
  process.env.PPT_ENGINE_ROOT = engine;
  process.env.PPT_CHROME_PATH = chrome;
  const html = await buildDeckHtml(normalizeDeckOutline(outline));
  const broken = Buffer.from(html.toString('utf8').replace('<div class="ai-body">', '<div class="ai-body"><div style="height:1200px;flex:none">'));
  await assert.rejects(() => qualityCheckDeck(broken), DeckQaError);
});
