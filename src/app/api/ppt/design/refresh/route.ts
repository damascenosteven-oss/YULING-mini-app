import { randomUUID } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { DEVICE_COOKIE, DEVICE_MAX_AGE_SECONDS, deviceIdentity, isAuthenticated } from '@/lib/ppt/auth';
import { resolveMotionPlan, type MotionHistory } from '@/lib/ppt/motion';
import { clientAddress, consumeRateLimit } from '@/lib/ppt/rate-limit';
import { deckOutlineSchema, motionModeSchema } from '@/lib/ppt/schema';
import { listDeckHistory } from '@/lib/ppt/storage';

export const runtime = 'nodejs';

const requestSchema = z.object({ deck: deckOutlineSchema, mode: motionModeSchema });

export async function POST(request: NextRequest) {
  if (!isAuthenticated(request)) return NextResponse.json({ error: '请先输入邀请码' }, { status: 401 });
  if (!consumeRateLimit(`motion-refresh:${clientAddress(request.headers)}`, 30, 60 * 60 * 1000)) {
    return NextResponse.json({ error: '动效切换次数过多，请稍后再试' }, { status: 429 });
  }
  const parsed = requestSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: '课件结构或动效强度不正确' }, { status: 422 });
  const requestId = randomUUID();
  const device = deviceIdentity(request);
  let recent: MotionHistory[] = [];
  try {
    const history = await listDeckHistory(device.ownerHash);
    recent = history.slice(0, 5).flatMap(item => item.motionDesign ? [item.motionDesign as MotionHistory] : []);
  } catch (error) {
    console.error('ppt_motion_history_read_failed', { requestId, error: error instanceof Error ? error.name : 'UnknownError' });
  }
  const resolved = resolveMotionPlan(parsed.data.deck, {
    prompt: `${parsed.data.deck.title} ${parsed.data.deck.goal}`,
    mode: parsed.data.mode,
    recent,
    exclude: parsed.data.deck.motionPlan ? [parsed.data.deck.motionPlan.fingerprint] : [],
  });
  const response = NextResponse.json({ motionPlan: resolved.motionPlan });
  if (device.cookieValue) response.cookies.set(DEVICE_COOKIE, device.cookieValue, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: DEVICE_MAX_AGE_SECONDS,
  });
  return response;
}
