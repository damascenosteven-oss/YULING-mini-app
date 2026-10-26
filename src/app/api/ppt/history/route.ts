import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import {
  DEVICE_COOKIE,
  DEVICE_MAX_AGE_SECONDS,
  deviceIdentity,
  isAuthenticated,
} from '@/lib/ppt/auth';
import { clientAddress, consumeRateLimit } from '@/lib/ppt/rate-limit';
import { importDeckHistory, listDeckHistory } from '@/lib/ppt/storage';

export const runtime = 'nodejs';

const importSchema = z.object({ code: z.string().trim().toUpperCase().regex(/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/) });

function attachDeviceCookie(response: NextResponse, cookieValue?: string): NextResponse {
  if (cookieValue) response.cookies.set(DEVICE_COOKIE, cookieValue, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: DEVICE_MAX_AGE_SECONDS,
  });
  return response;
}

export async function GET(request: NextRequest) {
  if (!isAuthenticated(request)) return NextResponse.json({ error: '请先输入邀请码' }, { status: 401 });
  const device = deviceIdentity(request);
  try {
    const items = await listDeckHistory(device.ownerHash);
    return attachDeviceCookie(NextResponse.json({ items }), device.cookieValue);
  } catch {
    return NextResponse.json({ error: '最近生成暂时无法读取' }, { status: 502 });
  }
}

export async function POST(request: NextRequest) {
  if (!isAuthenticated(request)) return NextResponse.json({ error: '请先输入邀请码' }, { status: 401 });
  if (!consumeRateLimit(`history-import:${clientAddress(request.headers)}`, 20, 60 * 60 * 1000)) {
    return NextResponse.json({ error: '找回尝试过多，请稍后再试' }, { status: 429 });
  }
  const parsed = importSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: '分享码格式不正确' }, { status: 422 });
  const device = deviceIdentity(request);
  try {
    const item = await importDeckHistory(device.ownerHash, parsed.data.code);
    if (!item) return NextResponse.json({ error: '分享码不存在或课件已过期' }, { status: 404 });
    return attachDeviceCookie(NextResponse.json({ item }), device.cookieValue);
  } catch {
    return NextResponse.json({ error: '找回作品失败，请稍后重试' }, { status: 502 });
  }
}
