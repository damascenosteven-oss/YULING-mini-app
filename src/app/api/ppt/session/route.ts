import { NextRequest, NextResponse } from 'next/server';
import {
  createSessionToken,
  DEVICE_COOKIE,
  DEVICE_MAX_AGE_SECONDS,
  deviceIdentity,
  isAuthenticated,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  verifyInvitePassword,
} from '@/lib/ppt/auth';
import { clientAddress, consumeRateLimit } from '@/lib/ppt/rate-limit';
import { sessionRequestSchema } from '@/lib/ppt/schema';

export async function POST(request: NextRequest) {
  const address = clientAddress(request.headers);
  if (!consumeRateLimit(`login:${address}`, 5, 15 * 60 * 1000)) {
    return NextResponse.json({ error: '尝试次数过多，请稍后再试' }, { status: 429 });
  }
  const parsed = sessionRequestSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success || !verifyInvitePassword(parsed.data.password)) {
    return NextResponse.json({ error: '邀请码不正确' }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, createSessionToken(), {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  const device = deviceIdentity(request);
  if (device.cookieValue) response.cookies.set(DEVICE_COOKIE, device.cookieValue, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: DEVICE_MAX_AGE_SECONDS,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(SESSION_COOKIE, '', { httpOnly: true, sameSite: 'lax', secure: process.env.NODE_ENV === 'production', path: '/', maxAge: 0 });
  return response;
}

export function GET(request: NextRequest) {
  const response = NextResponse.json({ authenticated: isAuthenticated(request) });
  const device = deviceIdentity(request);
  if (device.cookieValue) response.cookies.set(DEVICE_COOKIE, device.cookieValue, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: DEVICE_MAX_AGE_SECONDS,
  });
  return response;
}
