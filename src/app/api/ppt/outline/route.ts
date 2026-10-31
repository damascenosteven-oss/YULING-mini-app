import { randomUUID } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { DEVICE_COOKIE, DEVICE_MAX_AGE_SECONDS, deviceIdentity, isAuthenticated } from '@/lib/ppt/auth';
import {
  generateOutline,
  ModelTimeoutError,
  OutlineInvalidError,
  ResearchInsufficientError,
  ResearchUnavailableError,
  UnsafeRequestError,
} from '@/lib/ppt/deepseek';
import { clientAddress, consumeRateLimit } from '@/lib/ppt/rate-limit';
import { outlineRequestSchema } from '@/lib/ppt/schema';
import { MotionResolutionError, resolveMotionPlan, type MotionHistory } from '@/lib/ppt/motion';
import { listDeckHistory } from '@/lib/ppt/storage';
import { UnsupportedSkillError } from '@/lib/ppt/skills';
import { ModelSettingsError } from '@/lib/ppt/model-settings';

export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  if (!isAuthenticated(request)) return NextResponse.json({ error: '请先输入邀请码' }, { status: 401 });
  const address = clientAddress(request.headers);
  if (!consumeRateLimit(`outline:${address}`, 10, 60 * 60 * 1000)) {
    return NextResponse.json({ error: '本小时生成次数已用完' }, { status: 429 });
  }
  const parsed = outlineRequestSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: '需求需为 20–6000 字，页数为 6–12' }, { status: 422 });
  const requestId = randomUUID();
  const device = deviceIdentity(request);
  try {
    const deck = await generateOutline(parsed.data.prompt, parsed.data.pageCount, parsed.data.skillId, failure => {
      const { usage: _usage, ...diagnostic } = failure;
      console.error('ppt_outline_attempt_failed', { requestId, ...diagnostic });
    }, record => console.info('ppt_outline_attempt', JSON.stringify({ requestId, ...record })));
    let recent: MotionHistory[] = [];
    try {
      const history = await listDeckHistory(device.ownerHash);
      recent = history.slice(0, 5).flatMap(item => item.motionDesign ? [item.motionDesign as MotionHistory] : []);
    } catch (historyError) {
      console.error('ppt_motion_history_read_failed', { requestId, error: historyError instanceof Error ? historyError.name : 'UnknownError' });
    }
    const response = NextResponse.json(resolveMotionPlan(deck, { prompt: parsed.data.prompt, mode: parsed.data.motionMode, recent }));
    if (device.cookieValue) response.cookies.set(DEVICE_COOKIE, device.cookieValue, {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: DEVICE_MAX_AGE_SECONDS,
    });
    return response;
  } catch (error) {
    if (error instanceof MotionResolutionError) {
      console.error('ppt_outline_failed', { requestId, step: 'motion_resolve', classification: 'no_valid_candidate' });
      return NextResponse.json({ error: `大纲生成失败，请重试（${requestId.slice(0, 8)}）` }, { status: 502 });
    }
    if (error instanceof ModelSettingsError) return NextResponse.json({ error: error.message, code: error.code }, { status: error.status });
    if (error instanceof UnsafeRequestError) return NextResponse.json({ error: error.message }, { status: 422 });
    if (error instanceof ResearchUnavailableError) return NextResponse.json({ error: error.message, code: error.code }, { status: 503 });
    if (error instanceof ResearchInsufficientError) return NextResponse.json({ error: error.message, code: error.code }, { status: 422 });
    if (error instanceof ModelTimeoutError) return NextResponse.json({ error: 'YuLing AI 响应超时，请稍后重试', code: error.code }, { status: 504 });
    if (error instanceof UnsupportedSkillError) return NextResponse.json({ error: error.message, code: error.code }, { status: 422 });
    if (error instanceof OutlineInvalidError) {
      console.error('ppt_outline_invalid', { requestId, code: error.code, constraint: error.message.slice(0, 1200) });
      return NextResponse.json({ error: `大纲结构未能自动修复，请重试（${requestId.slice(0, 8)}）`, code: error.code }, { status: 502 });
    }
    console.error('ppt_outline_failed', { requestId, step: 'outline_generate', classification: 'generation_failed' });
    return NextResponse.json({ error: `大纲生成失败，请重试（${requestId.slice(0, 8)}）` }, { status: 502 });
  }
}
