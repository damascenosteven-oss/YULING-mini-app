// Only injected into disconnected test containers; never loaded by production.
/* global playbackFixtureRewrites */
import assert from 'node:assert/strict';
import dns from 'node:dns/promises';
import https from 'node:https';
import { PassThrough, Writable } from 'node:stream';
import crypto, { scryptSync } from 'node:crypto';
import { syncBuiltinESMExports } from 'node:module';
const scenario = process.env.OUTLINE_FIXTURE_CASE;
// Only the synchronous 8-byte motion seed is fixed. Auth, IVs and UUIDs stay native.
const nativeRandomBytes = crypto.randomBytes;
if (scenario === 'admin') crypto.randomBytes = function (size, callback) {
 if (size === 8 && !callback) return Buffer.from('0000000000000001', 'hex');
 return nativeRandomBytes.call(this, size, callback);
};
const marker = 'PRIVATE_DRAFT_BODY_SENTINEL';
const originalFetch = globalThis.fetch;
let models = 0;
let connections = 0;
const objects = new Map();
const salt = '0'.repeat(32);
process.env.PPT_ADMIN_PASSWORD_HASH = 'scrypt-v1:' + salt + ':' + scryptSync('fixture-admin-independent-password', salt, 32).toString('hex');
const deck = {
 title: '培训规划', audience: '测试人员', goal: '验证普通生成完整入口',
 design: { narrative: 'proposal', mood: 'professional', palette: 'blue', density: 'balanced' },
 slides: [
  { id: 'cover', type: 'cover', variant: 'cinematic', theme: 'blue', title: '培训规划', tagline: '隔离模型样本' },
  ...Array.from({ length: 8 }, (_, i) => ({ id: `points-${i}`, type: 'bullets', variant: i % 2 ? 'feature-list' : 'three-cards', theme: 'blue', title: '规划行动', items: ['核对需求并明确目标', '安排实践并逐项复核'] })),
  { id: 'closing', type: 'closing', variant: 'action-card', theme: 'blue', title: '下一步', summary: '内容仍需人工核验', actions: ['人工复核并试用'] },
 ],
};
// The real acceptance failure used a descriptive unit on a ranking page.
// Exercise the same renderer -> Python -> QA -> COS path without cloud calls.
if (scenario === 'admin') deck.slides[7] = {
 id: 'ranking-unit-fit', type: 'ranking', variant: 'horizontal-bars', theme: 'blue',
 title: '课程需求热度排名', dataStatus: 'demo', unit: '报名指数（演示）',
 takeaway: '数字工具与设备运维课程需求领先',
 story: { question: '如何安排课程？', claim: '数字工具与设备运维课程需求领先', implication: '仅为演示，实际需核验', focusKeys: ['数字工具应用'] },
 entries: ['数字工具应用', '设备运维基础', '数据分析入门', '质量管理实务', '客户沟通技巧', '外贸英语'].map((label, i) => ({ label, value: [92, 85, 78, 64, 58, 45][i], change: 0 })),
};
function stats() { console.error('OUTLINE_FIXTURE ' + JSON.stringify({ scenario, searches: 0, models, connections })); }
const highlightPage = {
 id: 'highlight-bounds', type: 'table', variant: 'highlight-table', theme: 'blue', title: '项目比较',
 dataStatus: 'demo', takeaway: '先核对实际口径', headers: ['项目', '数值'],
 rows: [{ label: '项目甲', values: [1] }, { label: '项目乙', values: [2] }],
 highlights: [{ row: 1, column: 0, tone: 'focus' }],
 story: { question: '如何比较', claim: '先核验口径', implication: '复核后再决策', focusKeys: ['项目甲'] },
 subtitle: marker,
};
globalThis.fetch = async (input, init) => {
 const url = String(input instanceof Request ? input.url : input);
 assert.ok(url.startsWith('http://127.0.0.1:') || url.startsWith('http://localhost:'), 'no external fetch');
 return originalFetch(input, init);
};
dns.lookup = async (host, options) => {
 assert.ok(['api.deepseek.com', 'fixture-model.example'].includes(host));
 return options?.all ? [{ address: '8.8.8.8', family: 4 }] : { address: '8.8.8.8', family: 4 };
};
https.request = function (input, options, callback) {
 let url;
 if (input instanceof URL) url = input;
 else { callback = options; options = input; url = new URL('https://' + (options.hostname || options.host) + (options.path || '/')); }
 const isModel = ['api.deepseek.com', 'fixture-model.example'].includes(url.hostname);
 const isStorage = url.hostname === 'fixture-bucket.cos.ap-shanghai.myqcloud.com';
 assert.ok(isModel || isStorage, 'no other native HTTPS destination');
 const chunks = [];
 const request = new Writable({ autoDestroy: false, write(chunk, _encoding, done) { chunks.push(Buffer.from(chunk)); done(); } });
 request.setTimeout = () => request;
 request.flushHeaders = () => {};
 request.abort = () => request.destroy(new Error('fixture aborted'));
 const respond = (statusCode, data, headers = {}) => {
  const response = Object.assign(new PassThrough(), { statusCode, headers, rawHeaders: [], statusMessage: statusCode === 200 ? 'OK' : 'Not Found' });
  callback(response); response.end(data);
 };
 request.on('finish', () => {
  const raw = Buffer.concat(chunks);
  if (isStorage) {
   const key = decodeURIComponent(url.pathname);
   if (options.method === 'PUT') {
    let data = raw;
    if (key.endsWith('.html')) {
     // Simulate an existing COS work: the writer must adapt new output, while
     // the real GET route must adapt the unmodified pinned engine runtime too.
     const html = raw.toString();
     assert.equal(html.split('<!-- yuling-mobile-playback:v2 -->').length, 2);
     let old = html.replace(/<style data-yuling-mobile="v2">[\s\S]*?<\/style>/, '')
      .replace(/<!-- yuling-mobile-playback:v2 -->[\s\S]*?(?=splitHeadingLines\(\);)/, '');
     for(const [original, changed] of playbackFixtureRewrites) old=old.split(changed).join(original);
     assert.equal(old.includes('yuling-mobile-playback:v2'), false);
     data = Buffer.from(old);
    }
    objects.set(key, { data, headers: { ...options.headers, 'content-length': String(data.length) } });
    respond(200, '', { etag: '"fixture"' });
   }
   else if (url.searchParams.has('list-type')) respond(200, '<ListBucketResult><IsTruncated>false</IsTruncated><KeyCount>0</KeyCount></ListBucketResult>', { 'content-type': 'application/xml' });
   else if (objects.has(key)) { const stored = objects.get(key); respond(200, options.method === 'HEAD' ? '' : stored.data, stored.headers); }
   else respond(404, '<Error><Code>NoSuchKey</Code></Error>', { 'content-type': 'application/xml' });
   return;
  }
  assert.ok(['/chat/completions', '/v1/chat/completions'].includes(url.pathname));
  const body = JSON.parse(raw.toString());
  if (body.messages[0].content === 'Return only this JSON object: {"ok":true}') { connections++; stats(); respond(200, JSON.stringify({ choices: [{ message: { content: '{"ok":true}' } }] })); return; }
  models++; stats(); assert.ok(models <= 2);
  if (scenario === 'admin') { assert.equal(body.model, 'fixture-compatible'); assert.equal(body.max_completion_tokens, 8192); assert.equal('thinking' in body, false); }
  else { assert.equal(body.model, 'deepseek-flash'); assert.equal(body.max_tokens, 8192); assert.deepEqual(body.thinking, { type: 'disabled' }); }
  if (models === 2 && ['repair', 'invalid', 'timeout', 'admin'].includes(scenario)) {
   const repair = body.messages.find(m => m.role === 'user').content;
   assert.ok(repair.includes(marker) && repair.includes('slides.1.items')); assert.ok(!repair.includes('slides.1.tagline'));
   if (scenario === 'admin') assert.ok(repair.includes('slides.8.totalRow') && repair.includes('slides.2.story'));
  }
  if (models === 2 && ['highlight-repair', 'skill-repair', 'skill-invalid', 'json-repair'].includes(scenario)) {
   const repair = body.messages.find(m => m.role === 'user').content;
   if (scenario === 'json-repair') { assert.ok(repair.includes('完整、可解析')); assert.ok(!repair.includes('上次草稿')); }
   else {
    assert.ok(repair.includes(marker) && repair.includes('上次草稿'));
    if (scenario === 'highlight-repair') assert.ok(repair.includes('第8页') && repair.includes('slides.7.highlights.0.row') && repair.includes('0–1') && repair.includes('0–0'));
    else assert.ok(repair.includes('slides.7.story') && repair.includes('focusKeys'));
   }
  }
  if (scenario === 'timeout' && models === 2) { options.signal.addEventListener('abort', () => request.destroy(new DOMException('fixture timeout', 'AbortError')), { once: true }); return; }
  if (scenario === 'upstream') { respond(503, 'PRIVATE_PROVIDER_BODY_SENTINEL'); return; }
  const result = structuredClone(deck);
  if (scenario === 'admin') {
   result.slides[2] = { ...structuredClone(highlightPage), id: 'story-required' };
   result.slides[8] = { ...structuredClone(highlightPage), id: 'summary-required', totalRow: 1 };
   if (models === 1) {
    delete result.slides[2].story;
    result.slides[8].totalRow = { label: '合计', values: [3] };
   }
  }
  if (['highlight-repair', 'skill-repair', 'skill-invalid'].includes(scenario)) {
   result.slides[7] = structuredClone(highlightPage);
   if (scenario === 'highlight-repair' && models === 1) result.slides[7].highlights = [{ row: 2, column: 1, tone: 'focus' }];
   if (scenario === 'skill-invalid' || scenario === 'skill-repair' && models === 1) delete result.slides[7].story;
  }
  if (scenario === 'invalid' || (['repair', 'timeout', 'admin'].includes(scenario) && models === 1)) { result.slides[1].items = [1, 2, 3, 4, 5]; result.slides[1].subtitle = marker; }
  respond(200, JSON.stringify({ choices: [{ finish_reason: scenario === 'truncated' ? 'length' : 'stop', message: { content: scenario === 'json' || scenario === 'json-repair' && models === 1 ? '{broken-json' : JSON.stringify({ safe: true, deck: result }) } }], usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150, prompt_cache_hit_tokens: 80, prompt_cache_miss_tokens: 20, completion_tokens_details: { reasoning_tokens: 5 } } }), { 'content-type': 'application/json' });
 });
 return request;
};
syncBuiltinESMExports();
