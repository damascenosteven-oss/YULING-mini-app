import { modelTransport } from './model-http';
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatValidationIssues, generateOutline, ModelTimeoutError, OutlineInvalidError,
  type OutlineAttemptFailure,
  type OutlineAttemptRecord,
} from './deepseek';
import { deckOutlineSchema, slideSchema } from './schema';

const prompt = '请介绍团队如何安全使用人工智能提高日常办公效率';
const bullets = { id: 'points', type: 'bullets', variant: 'three-cards', theme: 'blue', title: '团队行动', items: ['建立检查清单', '复核事实来源'] };
const deck = {
  title: '团队办公', audience: '团队成员', goal: '建立可检查的工作流程',
  design: { narrative: 'proposal', mood: 'professional', palette: 'blue', density: 'balanced' },
  slides: [
    { id: 'cover', type: 'cover', variant: 'cinematic', theme: 'blue', title: '团队办公', tagline: '可检查的工作流程' },
    ...Array.from({ length: 4 }, (_, index) => ({ ...bullets, id: `points-${index}`, variant: index % 2 ? 'feature-list' : 'three-cards' })),
    { id: 'closing', type: 'closing', variant: 'action-card', theme: 'blue', title: '下一步', summary: '逐项复核', actions: ['开展小范围试用'] },
  ],
};

function invalidDeck() {
  const value = structuredClone(deck) as unknown as { slides: Array<Record<string, unknown>> };
  value.slides[1].items = [1, 2, 3, 4, 5];
  value.slides[1].subtitle = 'DRAFT_BODY_MUST_NOT_BE_LOGGED';
  return value;
}

function modelResponse(value: unknown, finish = 'stop', status = 200) {
  return new Response(JSON.stringify({
    choices: [{ message: { content: typeof value === 'string' ? value : JSON.stringify({ safe: true, deck: value }) }, finish_reason: finish }],
    usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120, completion_tokens_details: { reasoning_tokens: 0 } },
  }), { status, headers: { 'Content-Type': 'application/json', 'x-request-id': 'fixture-request-1' } });
}

async function scenario(
  responses: Array<() => Response | Promise<Response>>,
  run: (requests: Array<Record<string, unknown>>, searches: () => number) => Promise<void>,
  settings: Record<string, string | undefined> = {},
) {
  const originalFetch = globalThis.fetch;
  const originalTransport = modelTransport.send;
  const names = ['DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL', 'BOCHA_API_KEY'];
  const original = Object.fromEntries(names.map(name => [name, process.env[name]]));
  const requests: Array<Record<string, unknown>> = [];
  let searches = 0;
  process.env.DEEPSEEK_API_KEY = 'FIXTURE_KEY_MUST_NOT_BE_LOGGED';
  process.env.BOCHA_API_KEY = 'FIXTURE_SEARCH_KEY_MUST_NOT_BE_LOGGED';
  delete process.env.DEEPSEEK_BASE_URL;
  delete process.env.DEEPSEEK_MODEL;
  for (const [name, value] of Object.entries(settings)) {
    if (value === undefined) delete process.env[name]; else process.env[name] = value;
  }
  globalThis.fetch = async () => { searches += 1; throw new Error('Search is forbidden in ordinary generation'); };
  modelTransport.send = async (url, _key, body) => {
    assert.ok(url.endsWith('/chat/completions'), 'fixture refuses unexpected network request');
    requests.push(body);
    const response = responses[requests.length - 1];
    assert.ok(response, 'no third model request is permitted');
    return response();
  };
  try { await run(requests, () => searches); }
  finally {
    globalThis.fetch = originalFetch;
    modelTransport.send = originalTransport;
    for (const name of names) {
      if (original[name] === undefined) delete process.env[name]; else process.env[name] = original[name];
    }
  }
}

test('known bullets errors stay on items instead of an unrelated cover union', () => {
  const value = { ...bullets, items: [1, 2, 3, 4, 5] };
  const parsed = slideSchema.safeParse(value);
  assert.equal(parsed.success, false);
  if (parsed.success) return;
  const feedback = formatValidationIssues(parsed.error, value);
  assert.match(feedback, /items\.0/);
  assert.doesNotMatch(feedback, /cover|tagline|cinematic/);
});

test('deck paths identify the actual invalid page and do not echo draft values', () => {
  const value = invalidDeck();
  const parsed = deckOutlineSchema.safeParse(value);
  assert.equal(parsed.success, false);
  if (parsed.success) return;
  const feedback = formatValidationIssues(parsed.error, value);
  assert.match(feedback, /slides\.1\.items/);
  assert.doesNotMatch(feedback, /DRAFT_BODY|tagline/);
});

test('unknown or missing type lists allowed types without guessing a cover', () => {
  for (const type of ['not-a-slide', undefined]) {
    const value = { ...bullets, type };
    const parsed = slideSchema.safeParse(value);
    assert.equal(parsed.success, false);
    if (parsed.success) continue;
    const feedback = formatValidationIssues(parsed.error, value);
    assert.match(feedback, /type/);
    for (const allowed of ['cover', 'bullets', 'chart', 'table', 'closing']) assert.ok(feedback.includes(allowed));
    assert.doesNotMatch(feedback, /tagline/);
  }
});

const table = {
  id: 'table', type: 'table', variant: 'data-table', theme: 'blue', title: '资料表', dataStatus: 'demo',
  takeaway: '此为测试数据', headers: ['项目', '数值'], rows: [{ label: '项目甲', values: [1] }, { label: '项目乙', values: [2] }],
};

test('unknown table variant lists all allowed table variants without changing the data', () => {
  const value = { ...table, variant: 'not-a-table' };
  const before = structuredClone(value);
  const parsed = slideSchema.safeParse(value);
  assert.equal(parsed.success, false);
  if (parsed.success) return;
  const feedback = formatValidationIssues(parsed.error, value);
  for (const variant of ['data-table', 'highlight-table', 'financial-return']) assert.ok(feedback.includes(variant));
  assert.doesNotMatch(feedback, /tagline/);
  assert.deepEqual(value, before);
});

test('each valid table subtype retains its own nested validation contract', () => {
  const cases = [
    { ...table, rows: [{ label: '项目甲', values: [1, 2] }, { label: '项目乙', values: [2] }] },
    { ...table, variant: 'highlight-table', highlights: [{ row: 0, column: 0, tone: 'not-a-tone' }] },
    { ...table, variant: 'financial-return', investment: 10, horizonMonths: 1, currency: 'CNY', items: [{ label: '费用甲', baseline: 1, proposed: 2 }, { label: '费用乙', baseline: 2, proposed: 1 }] },
  ];
  for (const [index, value] of cases.entries()) {
    const parsed = slideSchema.safeParse(value);
    assert.equal(parsed.success, false);
    if (parsed.success) continue;
    const feedback = formatValidationIssues(parsed.error, value);
    assert.match(feedback, [/rows\.0\.values/, /highlights\.0\.tone/, /items\.0\.proposed/][index]);
    assert.doesNotMatch(feedback, /tagline|expected "cover"/);
  }
  assert.equal(slideSchema.safeParse(table).success, true);
  assert.equal(slideSchema.safeParse({ ...table, variant: 'highlight-table' }).success, true);
});

test('official default model uses standard mode in both attempts and repairs the normalized draft', async () => {
  const failures: OutlineAttemptFailure[] = [];
  await scenario([() => modelResponse(invalidDeck()), () => modelResponse(deck)], async requests => {
    const result = await generateOutline(prompt, 6, 'project-proposal', failure => failures.push(failure));
    assert.equal(result.slides.length, 6);
    assert.equal(requests.length, 2);
    for (const request of requests) {
      assert.deepEqual(request.thinking, { type: 'disabled' });
      assert.equal(request.model, 'deepseek-flash');
      assert.equal(request.max_tokens, 8192);
    }
    const system = (requests[0].messages as Array<{ role: string; content: string }>).find(message => message.role === 'system')?.content;
    assert.ok(system);
    for (const [start, end] of [['要点页示例：', '。items'], ['数据表示例：', '。headers']] as const) {
      const example: string | undefined = system.split(start)[1]?.split(end)[0];
      assert.ok(example);
      assert.equal(slideSchema.safeParse(JSON.parse(example)).success, true, 'prompt example must satisfy the real slide schema');
    }
    const second = JSON.stringify(requests[1].messages);
    assert.ok(second.includes('DRAFT_BODY_MUST_NOT_BE_LOGGED'), 'repair must actually receive the previous draft');
    assert.match(second, /slides\.1\.items/);
    const logs = JSON.stringify(failures);
    assert.doesNotMatch(logs, /DRAFT_BODY|FIXTURE_KEY|FIXTURE_SEARCH_KEY/);
    assert.equal(failures[0].category, 'schema');
    assert.equal(failures[0].upstreamStatus, 200);
    assert.equal(failures[0].finishReason, 'stop');
    assert.equal(typeof failures[0].elapsedMs, 'number');
    assert.deepEqual(failures[0].usage, { promptTokens: 100, completionTokens: 20, totalTokens: 120, reasoningTokens: 0 });
  });
});

test('custom endpoint and other model do not receive a new provider parameter', async () => {
  for (const settings of [
    { DEEPSEEK_BASE_URL: 'https://fixture.example/v1' },
    { DEEPSEEK_BASE_URL: 'https://api.deepseek.com.fixture.example' },
    { DEEPSEEK_MODEL: 'other-model' },
  ]) {
    await scenario([() => modelResponse(deck)], async requests => {
      await generateOutline(prompt, 6, 'project-proposal');
      assert.equal('thinking' in requests[0], false);
    }, settings);
  }
});

test('ordinary repair never fetches research even for current-market requests', async () => {
  await scenario([() => modelResponse(invalidDeck()), () => modelResponse(deck)], async (requests, searches) => {
    const result = await generateOutline('调查目前宁波就业市场并形成有公开资料的汇报', 6, 'project-proposal');
    assert.equal(searches(), 0);
    assert.equal(requests.length, 2);
    assert.equal(result.research.status, 'not-required');
  });
});

test('invalid JSON and truncation remain failures after exactly two attempts', async () => {
  for (const response of [() => modelResponse('{not-json'), () => modelResponse(deck, 'length')]) {
    await scenario([response, response], async requests => {
      await assert.rejects(() => generateOutline(prompt, 6, 'project-proposal'), OutlineInvalidError);
      assert.equal(requests.length, 2);
    });
  }
});

test('continuous invalid drafts never escape as successful outlines', async () => {
  await scenario([() => modelResponse(invalidDeck()), () => modelResponse(invalidDeck())], async requests => {
    await assert.rejects(() => generateOutline(prompt, 6, 'project-proposal'), OutlineInvalidError);
    assert.equal(requests.length, 2);
  });
});

test('repair timeout retains timeout classification and safe first-attempt diagnostics', async () => {
  const failures: OutlineAttemptFailure[] = [];
  await scenario([() => modelResponse(invalidDeck()), () => { throw new DOMException('fixture-only-timeout', 'AbortError'); }], async requests => {
    await assert.rejects(() => generateOutline(prompt, 6, 'project-proposal', failure => failures.push(failure)), ModelTimeoutError);
    assert.equal(requests.length, 2);
    assert.deepEqual(failures.map(value => value.category), ['schema', 'timeout']);
    assert.doesNotMatch(JSON.stringify(failures), /DRAFT_BODY|FIXTURE_KEY/);
  });
});

test('upstream HTTP errors retain status without echoing provider bodies', async () => {
  const failures: OutlineAttemptFailure[] = [];
  await scenario([() => new Response('PRIVATE_PROVIDER_BODY', { status: 503 }), () => new Response('PRIVATE_PROVIDER_BODY', { status: 503 })], async requests => {
    await assert.rejects(() => generateOutline(prompt, 6, 'project-proposal', failure => failures.push(failure)));
    assert.equal(requests.length, 2);
    assert.equal(failures[0].upstreamStatus, 503);
    assert.equal(failures[0].category, 'upstream');
    assert.doesNotMatch(JSON.stringify(failures), /PRIVATE_PROVIDER_BODY|FIXTURE_KEY/);
  });
});

const highlight = {
  id: 'table', type: 'table', variant: 'highlight-table', theme: 'blue', title: '比较', dataStatus: 'demo',
  takeaway: '先核对口径', headers: ['项目', '数值'], rows: [{ label: '甲', values: [1] }, { label: '乙', values: [2] }],
  highlights: [{ row: 2, column: 1, tone: 'focus' }],
};

test('highlight feedback identifies page and actual zero-based numeric-cell bounds without changing data', () => {
  const value = structuredClone(deck);
  Object.assign(value.slides[1], highlight);
  const before = JSON.stringify(value);
  const result = deckOutlineSchema.safeParse(value);
  assert.equal(result.success, false);
  if (result.success) return;
  const message = formatValidationIssues(result.error, value);
  assert.match(message, /第2页.*slides\.1\.highlights\.0\.row.*0–1/);
  assert.match(message, /slides\.1\.highlights\.0\.column.*0–0.*标签/);
  assert.equal(JSON.stringify(value), before);
  assert.equal(slideSchema.safeParse({ ...highlight, highlights: [{ row: 1, column: 0, tone: 'focus' }] }).success, true);
  for (const [row, column] of [[0, 0], [1, 0]]) {
    assert.equal(slideSchema.safeParse({ ...highlight, highlights: [{ row, column, tone: 'focus' }] }).success, true);
  }
  for (const [row, column] of [[-1, 0], [0, -1], [0.5, 0], [0, 0.5], [2, 0], [0, 1]]) {
    assert.equal(slideSchema.safeParse({ ...highlight, highlights: [{ row, column, tone: 'focus' }] }).success, false);
  }
});

test('known Skill errors repair with exact field and draft and record each attempt once', async () => {
  const bad = structuredClone(deck);
  Object.assign(bad.slides[1], { ...highlight, highlights: [] });
  const good = structuredClone(bad);
  Object.assign(good.slides[1], { story: { question: '比较什么', claim: '需要核验', implication: '统一口径', focusKeys: ['甲'] } });
  const failures: OutlineAttemptFailure[] = [];
  const events: OutlineAttemptRecord[] = [];
  await scenario([() => modelResponse(bad), () => modelResponse(good)], async requests => {
    const result = await generateOutline(prompt, 6, 'executive-briefing', f => failures.push(f), e => events.push(e));
    assert.equal(result.slides.length, 6);
    assert.equal(failures[0].category, 'skill');
    const repair = (requests[1].messages as Array<{ role: string; content: string }>).find(m => m.role === 'user')!.content;
    assert.match(repair, /slides\.1\.story/);
    assert.match(repair, /上次草稿/);
    assert.deepEqual(events.map(e => [e.attempt, e.outcome, e.stage]), [[1, 'failure', 'skill'], [2, 'success', 'skill']]);
    assert.ok(events.every(e => e.model === 'deepseek-flash' && e.usage?.totalTokens === 120));
  });
});

test('attempt usage preserves provider counters and unknown fields without inventing or double counting', async () => {
  const events: OutlineAttemptRecord[] = [];
  const payload = { choices: [{ message: { content: JSON.stringify({ safe: true, deck }) }, finish_reason: 'stop' }],
    usage: { prompt_tokens: 100, completion_tokens: 20, total_tokens: 120, prompt_cache_hit_tokens: 80, prompt_cache_miss_tokens: 20,
      completion_tokens_details: { reasoning_tokens: 5 }, private_field: 'PRIVATE_USAGE' } };
  await scenario([() => Response.json(payload)], async () => { await generateOutline(prompt, 6, 'project-proposal', undefined, e => events.push(e)); });
  assert.equal(events.length, 1);
  assert.deepEqual(events[0].usage, { promptTokens: 100, completionTokens: 20, totalTokens: 120, cacheHitTokens: 80, cacheMissTokens: 20, reasoningTokens: 5 });
  assert.doesNotMatch(JSON.stringify(events), /PRIVATE_USAGE|FIXTURE_KEY|团队办公/);
  const compatible: OutlineAttemptRecord[] = [];
  await scenario([() => Response.json({ ...payload, usage: { prompt_tokens_details: { cached_tokens: 12 } } })], async () => {
    await generateOutline(prompt, 6, 'project-proposal', undefined, e => compatible.push(e));
  });
  assert.deepEqual(compatible[0].usage, { cacheHitTokens: 12 });
  for (const usage of [undefined, { prompt_tokens: -1, completion_tokens: '20', total_tokens: null }]) {
    const missing: OutlineAttemptRecord[] = [];
    await scenario([() => Response.json({ ...payload, usage })], async () => { await generateOutline(prompt, 6, 'project-proposal', undefined, e => missing.push(e)); });
    assert.equal(missing.length, 1);
    assert.equal(missing[0].usage, undefined);
  }
});

test('invalid JSON has a distinct classification and never fabricates a parsed repair draft', async () => {
  const events: OutlineAttemptRecord[] = [];
  await scenario([() => modelResponse('PRIVATE_BROKEN_JSON'), () => modelResponse(deck)], async requests => {
    await generateOutline(prompt, 6, 'project-proposal', undefined, e => events.push(e));
    assert.deepEqual(events.map(e => e.outcome), ['failure', 'success']);
    assert.equal(events[0].category, 'json');
    assert.equal(events[0].stage, 'json');
    const repair = (requests[1].messages as Array<{ role: string; content: string }>).find(m => m.role === 'user')!.content;
    assert.match(repair, /完整.*JSON/);
    assert.doesNotMatch(repair, /PRIVATE_BROKEN_JSON|上次草稿/);
    assert.doesNotMatch(JSON.stringify(events), /PRIVATE_BROKEN_JSON/);
  });
});

test('unknown local errors are internal and never trigger a fabricated model repair', async () => {
  const events: OutlineAttemptRecord[] = [];
  await scenario([() => modelResponse(deck)], async requests => {
    const original = globalThis.structuredClone;
    globalThis.structuredClone = () => { throw new Error('PRIVATE_INTERNAL_DETAILS'); };
    try { await assert.rejects(() => generateOutline(prompt, 6, 'project-proposal', undefined, e => events.push(e))); }
    finally { globalThis.structuredClone = original; }
    assert.equal(requests.length, 1);
    assert.equal(events.length, 1);
    assert.equal(events[0].category, 'internal');
    assert.equal(events[0].stage, 'normalize');
    assert.doesNotMatch(JSON.stringify(events), /PRIVATE_INTERNAL_DETAILS/);
  });
});
