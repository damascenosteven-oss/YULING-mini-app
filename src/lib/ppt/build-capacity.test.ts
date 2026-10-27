import assert from 'node:assert/strict';
import test from 'node:test';
import { NextRequest } from 'next/server';
import { POST } from '../../app/api/ppt/decks/route';
import { createSessionToken, SESSION_COOKIE } from './auth';
import { createGoldenOutline } from './golden-fixture';

test('real build route admits only one overlapping body read and releases capacity after failure', async () => {
  const savedSecret = process.env.PPT_SESSION_SECRET;
  const savedEngine = process.env.PPT_ENGINE_ROOT;
  process.env.PPT_SESSION_SECRET = 'test-only-concurrent-route-secret';
  // Exercise the real failure/finally path without starting Python or external providers.
  delete process.env.PPT_ENGINE_ROOT;
  try {
    let releaseBody!: () => void;
    const bodyReady = new Promise<void>(resolve => { releaseBody = resolve; });
    const request = (suffix: string) => {
      const value = new NextRequest('https://ppt.example.invalid/api/ppt/decks', {
        method: 'POST',
        headers: { cookie: `${SESSION_COOKIE}=${createSessionToken()}`, 'x-forwarded-for': `capacity-${suffix}` },
      });
      Object.defineProperty(value, 'json', { value: async () => {
        await bodyReady;
        return createGoldenOutline();
      } });
      return value;
    };
    const first = POST(request('first'));
    const second = POST(request('second'));
    releaseBody();
    const results = await Promise.all([first, second]);
    assert.deepEqual(results.map(result => result.status).sort(), [429, 502]);
    const busy = results.find(result => result.status === 429)!;
    assert.deepEqual(await busy.json(), { error: '服务器正在逐页检查其他课件，请稍后重试' });
    // The failed real build must release the slot, not leave all future requests busy.
    assert.equal((await POST(request('after-failure'))).status, 502);
  } finally {
    if (savedSecret === undefined) delete process.env.PPT_SESSION_SECRET;
    else process.env.PPT_SESSION_SECRET = savedSecret;
    if (savedEngine === undefined) delete process.env.PPT_ENGINE_ROOT;
    else process.env.PPT_ENGINE_ROOT = savedEngine;
  }
});
