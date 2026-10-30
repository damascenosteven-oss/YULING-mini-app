// Only mounted into network-disabled test containers. Never used by releases.
import assert from 'node:assert/strict';

const scenario = process.env.OUTLINE_FIXTURE_CASE;
assert.ok(['repair', 'invalid', 'timeout', 'upstream', 'json', 'truncated', 'search', 'insufficient'].includes(scenario));
const originalFetch = globalThis.fetch;
let searches = 0;
let models = 0;
const marker = 'PRIVATE_DRAFT_BODY_SENTINEL';
const deck = {
  title: '资料汇报', audience: '测试人员', goal: '验证受控入口',
  design: { narrative: 'report', mood: 'professional', palette: 'blue', density: 'balanced' },
  slides: [
    { id: 'cover', type: 'cover', variant: 'cinematic', theme: 'blue', title: '资料汇报', tagline: '隔离服务样本' },
    ...Array.from({ length: 8 }, (_, index) => ({
      id: `points-${index}`, type: 'bullets', variant: index % 2 ? 'feature-list' : 'three-cards', theme: 'blue',
      title: '核对资料', items: ['核对公开来源', '制定培训安排'], sourceIds: ['S1'],
    })),
    { id: 'closing', type: 'closing', variant: 'action-card', theme: 'blue', title: '下一步', summary: '保持来源可核验', actions: ['人工复核资料'] },
  ],
};

function stats() {
  console.error('OUTLINE_FIXTURE ' + JSON.stringify({ scenario, searches, models }));
}

globalThis.fetch = async function (input, init) {
  const url = String(input instanceof Request ? input.url : input);
  if (url.startsWith('http://127.0.0.1:')) return originalFetch(input, init);
  if (url === 'https://api.bochaai.com/v1/web-search') {
    searches += 1;
    stats();
    if (scenario === 'search') return new Response('{}', { status: 503 });
    return new Response(JSON.stringify({ data: { webPages: { value: Array.from({ length: scenario === 'insufficient' ? 2 : 3 }, (_, index) => ({
      name: `隔离资料 ${index}`, url: `https://fixture.gov.cn/source-${index}`, snippet: '仅验证接口结构的模拟来源。', siteName: '模拟统计机构',
    })) } } }));
  }
  assert.equal(url, 'https://api.deepseek.com/chat/completions', 'no unapproved network in HTTP fixture');
  models += 1;
  stats();
  assert.ok(models <= 2);
  const body = JSON.parse(String(init?.body));
  assert.deepEqual(body.thinking, { type: 'disabled' });
  assert.equal(body.model, 'deepseek-flash');
  assert.equal(body.max_tokens, 8192);
  if (models === 2 && ['repair', 'invalid', 'timeout'].includes(scenario)) {
    const repair = body.messages.find(message => message.role === 'user').content;
    assert.ok(repair.includes(marker), 'previous draft missing from real repair entry');
    assert.ok(repair.includes('slides.1.items'), 'repair feedback uses the wrong union');
    assert.ok(!repair.includes('slides.1.tagline'), 'repair must not ask for an unrelated cover');
  }
  if (scenario === 'timeout' && models === 2) {
    return new Promise((_, reject) => {
      if (init.signal.aborted) reject(new DOMException('fixture timeout', 'AbortError'));
      else init.signal.addEventListener('abort', () => reject(new DOMException('fixture timeout', 'AbortError')), { once: true });
    });
  }
  if (scenario === 'upstream') return new Response('PRIVATE_PROVIDER_BODY_SENTINEL', { status: 503 });
  const result = structuredClone(deck);
  if (scenario === 'invalid' || (['repair', 'timeout'].includes(scenario) && models === 1)) {
    result.slides[1].items = [1, 2, 3, 4, 5];
    result.slides[1].subtitle = marker;
  }
  return new Response(JSON.stringify({
    choices: [{ finish_reason: scenario === 'truncated' ? 'length' : 'stop', message: {
      content: scenario === 'json' ? '{broken-json' : JSON.stringify({ safe: true, deck: result }),
    } }],
    usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150, completion_tokens_details: { reasoning_tokens: 0 } },
  }), { headers: { 'Content-Type': 'application/json' } });
};
