import { NextRequest } from 'next/server';
import { SESSION_COOKIE } from '@/lib/ppt/auth';
import { ADMIN_COOKIE, ADMIN_MAX_AGE, createAdminToken, isAdmin, requireOrdinaryLogin, requireSameOrigin, verifyAdminPassword } from '@/lib/ppt/admin-auth';
import { adminBody, adminError, adminJson } from '@/lib/ppt/admin-response';
import { clientAddress, consumeRateLimit } from '@/lib/ppt/rate-limit';
import { ModelSettingsError } from '@/lib/ppt/model-settings';

export const runtime = 'nodejs';

export function GET(request: NextRequest) {
  try {
    requireOrdinaryLogin(request);
    return adminJson({ authenticated: isAdmin(request), configured: !!process.env.PPT_ADMIN_PASSWORD_HASH });
  } catch (error) { return adminError(error); }
}

export async function POST(request: NextRequest) {
  try {
    requireOrdinaryLogin(request);
    requireSameOrigin(request);
    if (!consumeRateLimit('admin-login:' + clientAddress(request.headers), 5, 15 * 60 * 1000)) throw new ModelSettingsError('管理员尝试次数过多，请稍后再试', 429);
    const hash = process.env.PPT_ADMIN_PASSWORD_HASH || '';
    if (!hash) throw new ModelSettingsError('管理员密码尚未初始化，请在服务器运行管理员初始化工具', 503);
    const body = await adminBody(request);
    if (typeof body.password !== 'string' || body.password.length > 200 || !verifyAdminPassword(body.password, hash)) throw new ModelSettingsError('管理员密码不正确', 401);
    const response = adminJson({ ok: true });
    response.cookies.set(ADMIN_COOKIE, createAdminToken(process.env.PPT_SESSION_SECRET || '', hash, request.cookies.get(SESSION_COOKIE)?.value || ''), {
      httpOnly: true, sameSite: 'strict', secure: process.env.NODE_ENV === 'production', path: '/api/ppt/admin', maxAge: ADMIN_MAX_AGE,
    });
    return response;
  } catch (error) { return adminError(error); }
}

export function DELETE(request: NextRequest) {
  try {
    requireOrdinaryLogin(request);
    requireSameOrigin(request);
    const response = adminJson({ ok: true });
    response.cookies.set(ADMIN_COOKIE, '', { httpOnly: true, sameSite: 'strict', secure: process.env.NODE_ENV === 'production', path: '/api/ppt/admin', maxAge: 0 });
    return response;
  } catch (error) { return adminError(error); }
}
