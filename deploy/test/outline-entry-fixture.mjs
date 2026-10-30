// Only injected into disconnected test containers; never loaded by production.
import assert from 'node:assert/strict';
import dns from 'node:dns/promises';
import https from 'node:https';
import { PassThrough, Writable } from 'node:stream';
import { scryptSync } from 'node:crypto';
import { syncBuiltinESMExports } from 'node:module';
const scenario = process.env.OUTLINE_FIXTURE_CASE;
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
function stats() { console.error('OUTLINE_FIXTURE ' + JSON.stringify({ scenario, searches: 0, models, connections })); }
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
 const request = new Writable({ write(chunk, _encoding, done) { chunks.push(Buffer.from(chunk)); done(); } });
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
   if (options.method === 'PUT') { objects.set(key, { data: raw, headers: options.headers }); respond(200, '', { etag: '"fixture"' }); }
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
  }
  if (scenario === 'timeout' && models === 2) { options.signal.addEventListener('abort', () => request.destroy(new DOMException('fixture timeout', 'AbortError')), { once: true }); return; }
  if (scenario === 'upstream') { respond(503, 'PRIVATE_PROVIDER_BODY_SENTINEL'); return; }
  const result = structuredClone(deck);
  if (scenario === 'invalid' || (['repair', 'timeout', 'admin'].includes(scenario) && models === 1)) { result.slides[1].items = [1, 2, 3, 4, 5]; result.slides[1].subtitle = marker; }
  respond(200, JSON.stringify({ choices: [{ finish_reason: scenario === 'truncated' ? 'length' : 'stop', message: { content: scenario === 'json' ? '{broken-json' : JSON.stringify({ safe: true, deck: result }) } }], usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 } }), { 'content-type': 'application/json' });
 });
 return request;
};
syncBuiltinESMExports();
