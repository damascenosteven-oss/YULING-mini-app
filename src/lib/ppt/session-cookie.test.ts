import assert from 'node:assert/strict';
import test from 'node:test';
import { NextRequest } from 'next/server';
import { DELETE, GET, POST } from '../../app/api/ppt/session/route';

for (const mode of ['production', 'development']) {
  test(`real session routes protect cookies in ${mode}`, async () => {
    const environment = process.env as Record<string, string | undefined>;
    const saved = {
      NODE_ENV: environment.NODE_ENV,
      PPT_INVITE_PASSWORD: environment.PPT_INVITE_PASSWORD,
      PPT_SESSION_SECRET: environment.PPT_SESSION_SECRET,
    };
    Object.assign(environment, {
      NODE_ENV: mode,
      PPT_INVITE_PASSWORD: 'test-only-invite',
      PPT_SESSION_SECRET: 'test-only-session-secret-not-a-real-credential',
    });
    try {
      const login = await POST(new NextRequest('https://ppt.example.invalid/api/ppt/session', {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-forwarded-for': mode },
        body: JSON.stringify({ password: 'test-only-invite' }),
      }));
      assert.equal(login.status, 200);
      const identity = GET(new NextRequest('https://ppt.example.invalid/api/ppt/session'));
      const logout = await DELETE();
      for (const [label, response, count] of [
        ['login', login, 2], ['identity', identity, 1], ['logout', logout, 2],
      ] as const) {
        const cookies = response.headers.getSetCookie();
        assert.equal(cookies.length, count, label);
        for (const cookie of cookies) {
          assert.match(cookie, /; HttpOnly/i, label);
          assert.match(cookie, cookie.startsWith('yuling_ppt_admin=') ? /; SameSite=strict/i : /; SameSite=lax/i, label);
          assert.equal(/; Secure(?:;|$)/i.test(cookie), mode === 'production', label);
        }
      }
      assert.match(logout.headers.getSetCookie()[0], /Max-Age=0/i);
      assert.ok(logout.headers.getSetCookie().some(value => value.startsWith('yuling_ppt_admin=') && value.includes('Max-Age=0')));
    } finally {
      for (const [name, value] of Object.entries(saved)) {
        if (value === undefined) delete environment[name];
        else environment[name] = value;
      }
    }
  });
}
