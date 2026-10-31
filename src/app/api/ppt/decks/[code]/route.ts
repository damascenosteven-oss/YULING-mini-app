import { NextResponse } from 'next/server';
import { loadDeck } from '@/lib/ppt/storage';
import { adaptMobilePlayback, PlaybackCompatibilityError } from '@/lib/ppt/mobile-playback';

export const runtime = 'nodejs';

export async function GET(_request: Request, context: { params: Promise<{ code: string }> }) {
  const code = (await context.params).code.toUpperCase();
  if (!/^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$/.test(code)) {
    return NextResponse.json({ error: '分享码格式不正确' }, { status: 404 });
  }
  try {
    const deck = await loadDeck(code);
    if (deck.status === 'missing') return NextResponse.json({ error: '未找到课件' }, { status: 404 });
    if (deck.status === 'expired') return NextResponse.json({ error: '课件已过期' }, { status: 410 });
    return new NextResponse(Buffer.from(adaptMobilePlayback(Buffer.from(deck.html).toString('utf8'))), {
      headers: {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'private, no-store',
        'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; font-src data:;",
        'X-Content-Type-Options': 'nosniff',
      },
    });
  } catch (error) {
    if (error instanceof PlaybackCompatibilityError) console.error('ppt_playback_compatibility', { code: 'runtime_unsupported' });
    return NextResponse.json({ error: '读取课件失败' }, { status: 502 });
  }
}
