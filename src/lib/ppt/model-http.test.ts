import assert from 'node:assert/strict';
import dns from 'node:dns/promises';
import https from 'node:https';
import type { IncomingMessage } from 'node:http';
import { PassThrough, Writable } from 'node:stream';
import test from 'node:test';
import { modelTransport, resolveModelTarget } from './model-http';

test('mixed public/private DNS is refused before connection', async () => {
  await assert.rejects(() => resolveModelTarget('provider.example', async () => [{ address: '8.8.8.8', family: 4 }, { address: '127.0.0.1', family: 4 }]));
});

test('real transport pins DNS, preserves TLS, refuses redirect and bounds response', async () => {
  const originalLookup = dns.lookup;
  const originalRequest = https.request;
  let lookups = 0;
  let requests = 0;
  let mode = 'success';
  dns.lookup = (async () => { lookups++; return [{ address: lookups === 1 ? '8.8.8.8' : '169.254.169.254', family: 4 }]; }) as unknown as typeof dns.lookup;
  https.request = ((_url: URL, options: https.RequestOptions, callback: (response: IncomingMessage) => void) => {
    requests++;
    assert.equal(options.rejectUnauthorized, undefined, 'native TLS validation remains enabled');
    assert.equal(options.agent, false);
    assert.equal(options.family, 4, 'disable automatic family re-resolution and pin lookup shape');
    assert.equal(options.headers && (options.headers as Record<string, unknown>).Authorization, 'Bearer FIXTURE');
    const request = new Writable({ write(_chunk, _encoding, done) { done(); } });
    let pinned = false;
    options.lookup?.('provider.example', {}, (error, address) => { assert.equal(error, null); assert.equal(address, '8.8.8.8'); pinned = true; });
    assert.ok(pinned, 'validated lookup must actually be used');
    request.on('finish', () => {
      const response = Object.assign(new PassThrough(), { statusCode: mode === 'redirect' ? 302 : mode === 'empty' ? 204 : 200 });
      callback(response as unknown as IncomingMessage);
      response.end(mode === 'oversized' ? Buffer.alloc(2 * 1024 * 1024 + 1) : '{"ok":true}');
    });
    return request;
  }) as unknown as typeof https.request;
  try {
    const response = await modelTransport.send('https://provider.example/v1/chat/completions', 'FIXTURE', {}, new AbortController().signal);
    assert.equal(response.status, 200); assert.deepEqual(await response.json(), { ok: true });
    assert.equal(lookups, 1);
    // New DNS lookup sees the changed private address and prevents another request.
    await assert.rejects(() => modelTransport.send('https://provider.example/v1/chat/completions', 'FIXTURE', {}, new AbortController().signal));
    assert.equal(requests, 1);
    for (const next of ['redirect', 'oversized']) {
      lookups = 0; mode = next;
      await assert.rejects(() => modelTransport.send('https://provider.example/v1/chat/completions', 'FIXTURE', {}, new AbortController().signal));
    }
    assert.equal(requests, 3, 'redirect is never followed');
    lookups = 0; mode = 'empty';
    assert.equal((await modelTransport.send('https://provider.example/v1/chat/completions', 'FIXTURE', {}, new AbortController().signal)).status, 204);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(() => modelTransport.send('https://provider.example/v1/chat/completions', 'FIXTURE', {}, controller.signal), { name: 'AbortError' });
  } finally { dns.lookup = originalLookup; https.request = originalRequest; }
});
