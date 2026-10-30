import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, chmod, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { ModelSettingsStore, normalizeBaseUrl, testModelConnection } from './model-settings';
import { hashAdminPassword, verifyAdminPassword, createAdminToken, verifyAdminToken } from './admin-auth';
import { isPublicAddress, modelTransport } from './model-http';

const input = { provider: 'deepseek' as const, baseUrl: 'https://api.deepseek.com', model: 'deepseek-flash', tokenLimitField: 'max_tokens' as const, apiKey: 'FIXTURE_KEY_NEVER_RETURN' };

test('URL normalization preserves proxy paths and refuses credentials/query/private literals', () => {
  assert.equal(normalizeBaseUrl('https://example.com/proxy/v1/chat/completions/'), 'https://example.com/proxy/v1');
  for (const url of ['http://example.com', 'https://x:y@example.com', 'https://example.com?key=secret', 'https://127.0.0.1', 'https://[::1]', 'https://metadata.google.internal', 'https://localhost']) {
    assert.throws(() => normalizeBaseUrl(url));
  }
});

test('public-address checks include IPv6, mapped IPv4 and reserved ranges', () => {
  for (const ip of ['127.0.0.1', '10.0.0.1', '172.18.0.1', '169.254.169.254', '100.64.0.1', '192.0.2.1', '0.0.0.0', '224.0.0.1', '::', '::1', 'fc00::1', 'fe80::1', '2001:db8::1', '::ffff:127.0.0.1', '64:ff9b::7f00:1']) assert.equal(isPublicAddress(ip), false, ip);
  for (const ip of ['8.8.8.8', '1.1.1.1', '2606:4700:4700::1111']) assert.equal(isPublicAddress(ip), true, ip);
});

test('administrator hashes are separate, tokens expire and password/session changes revoke them', () => {
  const hash = hashAdminPassword('Independent-fixture-password');
  assert.ok(verifyAdminPassword('Independent-fixture-password', hash));
  assert.equal(verifyAdminPassword('ordinary-invite', hash), false);
  assert.equal(verifyAdminPassword('x', 'broken'), false);
  const token = createAdminToken('secret', hash, 'ordinary-session', 1000);
  assert.ok(verifyAdminToken(token, 'secret', hash, 'ordinary-session', 1001));
  assert.equal(verifyAdminToken(token, 'secret', hash, 'other-session', 1001), false);
  assert.equal(verifyAdminToken(token, 'secret', hashAdminPassword('different-password'), 'ordinary-session', 1001), false);
  assert.equal(verifyAdminToken(token, 'secret', hash, 'ordinary-session', 3601001), false);
});

test('encrypted atomic settings survive new store instances; revisions, blank keys and corruption fail closed', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'model-settings-'));
  await chmod(dir, 0o700);
  const env = { ...input, apiKey: 'ENVIRONMENT_FIXTURE_KEY' };
  const store = new ModelSettingsStore(dir, 'fixture-session-secret', env);
  try {
    const initial = await store.view();
    const saved = await store.save(input, initial.revision);
    assert.equal(saved.apiKeyConfigured, true);
    assert.equal(JSON.stringify(saved).includes(input.apiKey), false);
    assert.equal((await readFile(join(dir, 'settings.json'), 'utf8')).includes(input.apiKey), false);
    const reopened = new ModelSettingsStore(dir, 'fixture-session-secret', env);
    assert.deepEqual((await reopened.read()).config, input);
    await assert.rejects(() => new ModelSettingsStore(dir, 'changed-session-secret', env).read(), /损坏/);
    await assert.rejects(() => store.save(input, initial.revision), /已变化/);
    await assert.rejects(() => store.candidate({ ...input, baseUrl: 'https://other.example/v1', apiKey: '' }), /重新填写/);
    assert.equal((await store.candidate({ ...input, model: 'another', apiKey: '' })).apiKey, input.apiKey);
    const competing = await Promise.allSettled([store.save({ ...input, model: 'a' }, saved.revision), reopened.save({ ...input, model: 'b' }, saved.revision)]);
    assert.equal(competing.filter(x => x.status === 'fulfilled').length, 1);
    const current = await store.view();
    await chmod(dir, 0o500);
    if (process.getuid?.() !== 0) await assert.rejects(() => store.save(input, current.revision));
    await chmod(dir, 0o700);
    await writeFile(join(dir, 'settings.json'), '{broken', { mode: 0o600 });
    await assert.rejects(() => store.read(), /损坏/);
    await assert.rejects(() => new ModelSettingsStore(dir, 'changed-session-secret', env).read(), /损坏/);
  } finally { await chmod(dir, 0o700); await rm(dir, { recursive: true, force: true }); }
});

test('empty initial key can be configured without a provider call; no implicit key reuse to other service', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'unconfigured-model-')); await chmod(dir, 0o700);
  try {
    const store = new ModelSettingsStore(dir, 'secret', { ...input, apiKey: '' });
    const initial = await store.view();
    assert.equal(initial.apiKeyConfigured, false);
    const value = await store.save(input, initial.revision);
    assert.ok(value.apiKeyConfigured);
    await assert.rejects(() => store.candidate({ ...input, provider: 'openai-compatible', apiKey: '' }), /重新填写/);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('connection tests use one bounded compatible JSON call and classify failures without response bodies', async () => {
  const original = modelTransport.send;
  const timer = globalThis.setTimeout;
  let calls = 0;
  try {
    for (const field of ['max_tokens', 'max_completion_tokens'] as const) {
      modelTransport.send = async (_url, _key, body) => {
        calls++; assert.equal(body[field], 128); assert.equal('thinking' in body, false);
        return new Response('{"choices":[{"message":{"content":"{\\"ok\\":true}"}}]}');
      };
      assert.equal((await testModelConnection({ ...input, provider: 'openai-compatible', tokenLimitField: field })).ok, true);
    }
    assert.equal(calls, 2);
    for (const status of [401, 403, 404, 429, 503]) {
      modelTransport.send = async () => new Response('PRIVATE_PROVIDER_BODY', { status });
      await assert.rejects(() => testModelConnection(input), error => error instanceof Error && !error.message.includes('PRIVATE_PROVIDER'));
    }
    for (const body of ['{bad', '{}', '{"choices":[{"message":{"content":"not json"}}]}']) {
      modelTransport.send = async () => new Response(body);
      await assert.rejects(() => testModelConnection(input), /JSON/);
    }
    globalThis.setTimeout = ((callback: () => void, ms: number) => { assert.equal(ms, 20_000); return timer(callback, 1); }) as typeof setTimeout;
    modelTransport.send = async (_url, _key, _body, signal) => new Promise((_, reject) => signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true }));
    await assert.rejects(() => testModelConnection(input), /超时/);
  } finally { modelTransport.send = original; globalThis.setTimeout = timer; }
});

test('settings symlinks and unsafe permissions are refused, reset explicitly restores environment', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'model-settings-'));
  await chmod(dir, 0o700);
  const store = new ModelSettingsStore(dir, 'secret', input);
  try {
    const initial = await store.view();
    const saved = await store.save(input, initial.revision);
    const reset = await store.reset(saved.revision);
    assert.equal(reset.source, 'environment');
    await assert.rejects(() => store.save(input, initial.revision), /已变化/, 'reset must not reuse an old environment revision');
    await rm(join(dir, 'settings.json'), { force: true });
    await symlink(join(dir, 'missing'), join(dir, 'settings.json'));
    await assert.rejects(() => store.read());
  } finally { await rm(dir, { recursive: true, force: true }); }
});
