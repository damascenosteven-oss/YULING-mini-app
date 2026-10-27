import { randomUUID } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { DEVICE_COOKIE, DEVICE_MAX_AGE_SECONDS, deviceIdentity, isAuthenticated } from '@/lib/ppt/auth';
import { buildDeckHtml } from '@/lib/ppt/builder';
import { DeckQaError, qualityCheckDeck } from '@/lib/ppt/qa';
import { clientAddress, consumeRateLimit } from '@/lib/ppt/rate-limit';
import { deckOutlineSchema, type DeckOutline } from '@/lib/ppt/schema';
import { allocateShareCode, saveDeck, saveDeckHistory } from '@/lib/ppt/storage';
import { ensureMotionPlan, motionHistory, motionProfileLabel } from '@/lib/ppt/motion';
import { skillLabel, UnsupportedSkillError, validateSkillDeck } from '@/lib/ppt/skills';

export const runtime = 'nodejs';
let activeBuilds = 0;

export async function POST(request: NextRequest) {
  if (!isAuthenticated(request)) return NextResponse.json({ error: '请先输入邀请码' }, { status: 401 });
  if (!consumeRateLimit(`build:${clientAddress(request.headers)}`, 10, 60 * 60 * 1000)) {
    return NextResponse.json({ error: '本小时生成次数已用完' }, { status: 429 });
  }
  if (activeBuilds >= 1) return NextResponse.json({ error: '服务器正在逐页检查其他课件，请稍后重试' }, { status: 429 });
  const parsed = deckOutlineSchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: '大纲结构不完整，请检查各页内容' }, { status: 422 });
  let outline: DeckOutline;
  try {
    outline = ensureMotionPlan(validateSkillDeck(parsed.data));
  } catch (error) {
    if (error instanceof UnsupportedSkillError) return NextResponse.json({ error: error.message, code: error.code }, { status: 422 });
    return NextResponse.json({ error: '动效方案校验失败，请换一套动效后重试' }, { status: 422 });
  }
  // Reading the body yields; another request may have claimed the slot meanwhile.
  if (activeBuilds >= 1) return NextResponse.json({ error: '服务器正在逐页检查其他课件，请稍后重试' }, { status: 429 });
  const requestId = randomUUID();
  const device = deviceIdentity(request);
  activeBuilds += 1;
  try {
    const built = await buildDeckHtml(outline);
    const checked = await qualityCheckDeck(built);
    if (checked.html.byteLength > 20 * 1024 * 1024) throw new Error('Generated deck exceeds 20 MB');
    const code = await allocateShareCode();
    const researchStatus = outline.research.status === 'completed' ? 'completed' : 'not-required';
    const plan = outline.motionPlan;
    if (!plan) throw new Error('Resolved deck is missing motion plan');
    const profile = motionProfileLabel(plan);
    const motionDesign = motionHistory(plan);
    const createdAt = new Date().toISOString();
    const skillName = skillLabel(outline.skill.id);
    const expiresAt = await saveDeck(code, checked.html, outline.title, { ownerHash: device.ownerHash, researchStatus, motionProfile: profile, motionDesign, skillId: outline.skill.id, skillVersion: outline.skill.version, skillLabel: skillName, now: new Date(createdAt).getTime() });
    try {
      await saveDeckHistory(device.ownerHash, { code, title: outline.title, createdAt, expiresAt, researchStatus, motionProfile: profile, motionDesign, skillId: outline.skill.id, skillVersion: outline.skill.version, skillLabel: skillName });
    } catch (historyError) {
      console.error('ppt_history_write_failed', { requestId, error: historyError instanceof Error ? historyError.name : 'UnknownError' });
    }
    const response = NextResponse.json({ code, expiresAt, viewerUrl: `/ppt/view/${code}`, qa: checked.report });
    if (device.cookieValue) response.cookies.set(DEVICE_COOKIE, device.cookieValue, {
      httpOnly: true,
      sameSite: 'lax',
      secure: process.env.NODE_ENV === 'production',
      path: '/',
      maxAge: DEVICE_MAX_AGE_SECONDS,
    });
    return response;
  } catch (error) {
    if (error instanceof UnsupportedSkillError) return NextResponse.json({ error: error.message, code: error.code }, { status: 422 });
    if (error instanceof DeckQaError) {
      const pages = [...new Set(error.issues.filter(issue => issue.page > 0).map(issue => issue.page))];
      console.error('ppt_qa_failed', { requestId, pages, codes: [...new Set(error.issues.map(issue => issue.code))] });
      return NextResponse.json({ error: `第 ${pages.join('、') || '未知'} 页内容过多或布局异常，请精简后重试`, code: 'PPT_LAYOUT_INVALID', pages }, { status: 422 });
    }
    console.error('ppt_build_failed', { requestId, error: error instanceof Error ? error.name : 'UnknownError' });
    return NextResponse.json({ error: `课件生成失败，请重试（${requestId.slice(0, 8)}）` }, { status: 502 });
  } finally {
    activeBuilds -= 1;
  }
}
