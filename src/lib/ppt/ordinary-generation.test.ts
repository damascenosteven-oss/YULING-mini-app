import { modelTransport } from './model-http';
import assert from 'node:assert/strict';
import test from 'node:test';
import { generateOutline } from './deepseek';

test('current-market requests reach the model without a search key', async () => {
  const before = modelTransport.send;
  const key = process.env.DEEPSEEK_API_KEY;
  const searchKey = process.env.BOCHA_API_KEY;
  process.env.DEEPSEEK_API_KEY = 'FIXTURE_ONLY';
  delete process.env.BOCHA_API_KEY;
  let calls = 0;
  modelTransport.send = async (url) => {
    assert.ok(String(url).endsWith('/chat/completions'));
    calls++;
    return new Response(JSON.stringify({ choices: [{ message: { content: '{' } }] }));
  };
  try {
    await assert.rejects(() => generateOutline('调查目前宁波就业市场，生成带公开来源的十页培训规划汇报', 10), /./);
    assert.equal(calls, 2, 'ordinary generation must not stop at missing search configuration');
  } finally {
    modelTransport.send = before;
    if (key === undefined) delete process.env.DEEPSEEK_API_KEY; else process.env.DEEPSEEK_API_KEY = key;
    if (searchKey === undefined) delete process.env.BOCHA_API_KEY; else process.env.BOCHA_API_KEY = searchKey;
  }
});

test('both generation attempts use the configuration snapshot from request start', async () => {
  const before = modelTransport.send;
  const key = process.env.DEEPSEEK_API_KEY;
  const model = process.env.DEEPSEEK_MODEL;
  process.env.DEEPSEEK_API_KEY = 'START_KEY'; process.env.DEEPSEEK_MODEL = 'start-model';
  let calls = 0;
  const seen: Array<{ apiKey: string; model: unknown }> = [];
  modelTransport.send = async (_url, apiKey, body) => {
    calls++;
    seen.push({ apiKey, model: body.model });
    process.env.DEEPSEEK_API_KEY = 'CHANGED_KEY'; process.env.DEEPSEEK_MODEL = 'changed-model';
    return new Response(JSON.stringify({ choices: [{ message: { content: '{' } }] }));
  };
  try {
    await assert.rejects(() => generateOutline('请介绍团队如何安全使用人工智能提高日常办公效率', 6));
    assert.equal(calls, 2);
    assert.deepEqual(seen, [{ apiKey: 'START_KEY', model: 'start-model' }, { apiKey: 'START_KEY', model: 'start-model' }]);
  }
  finally {
    modelTransport.send = before;
    if (key === undefined) delete process.env.DEEPSEEK_API_KEY; else process.env.DEEPSEEK_API_KEY = key;
    if (model === undefined) delete process.env.DEEPSEEK_MODEL; else process.env.DEEPSEEK_MODEL = model;
  }
});
