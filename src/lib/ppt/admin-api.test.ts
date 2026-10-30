import assert from 'node:assert/strict';
import { mkdtemp, chmod, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { NextRequest } from 'next/server';
import { createSessionToken, SESSION_COOKIE } from './auth';
import { ADMIN_COOKIE, hashAdminPassword } from './admin-auth';
import { GET as getSession, POST as login, DELETE as logout } from '../../app/api/ppt/admin/session/route';
import { GET as getSettings, PUT as saveSettings, DELETE as resetSettings } from '../../app/api/ppt/admin/model-settings/route';
import { POST as connectionTest } from '../../app/api/ppt/admin/model-settings/test/route';
import { modelTransport } from './model-http';

test('actual admin API separates invitation/admin, origin, cookie, settings and test-only calls', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'admin-api-')); await chmod(dir, 0o700);
  const names = ['PPT_SESSION_SECRET', 'PPT_ADMIN_PASSWORD_HASH', 'PPT_PUBLIC_ORIGIN', 'PPT_MODEL_SETTINGS_DIR', 'DEEPSEEK_API_KEY', 'NODE_ENV'];
  const before = Object.fromEntries(names.map(n => [n, process.env[n]]));
  Object.assign(process.env, { PPT_SESSION_SECRET: 'FIXTURE_SESSION', PPT_ADMIN_PASSWORD_HASH: hashAdminPassword('independent-fixture-password'), PPT_PUBLIC_ORIGIN: 'https://ppt.example', PPT_MODEL_SETTINGS_DIR: dir, DEEPSEEK_API_KEY: 'FIXTURE_KEY_NO_RESPONSE', NODE_ENV: 'production' });
  const ordinary = `${SESSION_COOKIE}=${createSessionToken()}`;
  let calls = 0;
  const original = modelTransport.send;
  modelTransport.send = async (_url, _key, body) => {
    calls++;
    assert.equal(body.max_completion_tokens, 128);
    assert.equal('thinking' in body, false);
    return new Response(JSON.stringify({ choices: [{ message: { content: '{"ok":true}' } }] }));
  };
  function request(method: string, body?: unknown, cookie = ordinary, origin = 'https://ppt.example') {
    return new NextRequest('https://ppt.example/api/ppt/admin/model-settings', { method, headers: { Cookie: cookie, Origin: origin, 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  }
  try {
    assert.equal((await getSettings(request('GET', undefined, ''))).status, 401);
    assert.equal((await getSettings(request('GET'))).status, 403);
    assert.equal((await login(request('POST', { password: 'ordinary-invite' }))).status, 401);
    assert.equal((await login(request('POST', { password: 'independent-fixture-password' }, ordinary, 'https://evil.example'))).status, 403);
    const response = await login(request('POST', { password: 'independent-fixture-password' }));
    assert.equal(response.status, 200);
    const set = response.headers.get('set-cookie') || '';
    for (const attribute of ['HttpOnly', 'Secure', 'SameSite=strict', 'Max-Age=3600']) assert.ok(set.includes(attribute), attribute);
    assert.ok(set.startsWith(ADMIN_COOKIE + '='));
    const adminCookie = ordinary + '; ' + set.split(';')[0];
    assert.equal((await getSession(request('GET', undefined, adminCookie))).status, 200);
    const viewResponse = await getSettings(request('GET', undefined, adminCookie));
    assert.equal(viewResponse.headers.get('cache-control'), 'no-store');
    const view = await viewResponse.json();
    assert.equal(JSON.stringify(view).includes('FIXTURE_KEY'), false);
    const config = { provider: 'openai-compatible', baseUrl: 'https://provider.example/v1', model: 'fixture-model', apiKey: 'FIXTURE_NEW_SECRET', tokenLimitField: 'max_completion_tokens' };
    assert.equal((await saveSettings(request('PUT', { revision: view.revision, config }, ordinary))).status, 403);
    assert.equal((await saveSettings(request('PUT', { revision: view.revision, config }, adminCookie, 'https://evil.example'))).status, 403);
    const tested = await connectionTest(request('POST', { config }, adminCookie));
    assert.equal(tested.status, 200);
    assert.equal(calls, 1);
    assert.equal((await (await getSettings(request('GET', undefined, adminCookie))).json()).revision, view.revision, 'test must not save');
    const saved = await saveSettings(request('PUT', { revision: view.revision, config }, adminCookie));
    assert.equal(saved.status, 200);
    const newView = await saved.json();
    assert.equal(calls, 1, 'save must not call provider');
    assert.equal(JSON.stringify(newView).includes('FIXTURE_NEW_SECRET'), false);
    assert.equal((await saveSettings(request('PUT', { revision: view.revision, config }, adminCookie))).status, 409);
    const reset = await resetSettings(request('DELETE', { revision: newView.revision }, adminCookie));
    assert.equal(reset.status, 200);
    assert.equal((await reset.json()).source, 'environment');
    const end = logout(request('DELETE', undefined, adminCookie));
    assert.ok(end.headers.get('set-cookie')?.includes('Max-Age=0'));
  } finally {
    modelTransport.send = original;
    for (const n of names) { if (before[n] === undefined) delete process.env[n]; else process.env[n] = before[n]; }
    await rm(dir, { recursive: true, force: true });
  }
});
