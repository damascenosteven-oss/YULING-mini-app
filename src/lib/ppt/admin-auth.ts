import { createHmac, randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import type { NextRequest } from 'next/server';
import { SESSION_COOKIE, isAuthenticated } from './auth';
import { ModelSettingsError } from './model-settings';

export const ADMIN_COOKIE = 'yuling_ppt_admin';
export const ADMIN_MAX_AGE = 3600;

export function hashAdminPassword(password: string): string {
  const salt = randomBytes(16).toString('hex');
  return 'scrypt-v1:' + salt + ':' + scryptSync(password, salt, 32, { N: 16384, r: 8, p: 1 }).toString('hex');
}

export function verifyAdminPassword(password: string, hash: string): boolean {
  if (!/^scrypt-v1:[a-f0-9]{32}:[a-f0-9]{64}$/u.test(hash)) return false;
  const [, salt, expected] = hash.split(':');
  return timingSafeEqual(scryptSync(password, salt, 32, { N: 16384, r: 8, p: 1 }), Buffer.from(expected, 'hex'));
}

function sign(secret: string, hash: string, session: string, expires: string): string {
  return createHmac('sha256', secret).update(`ppt-admin-v1:${hash}:${session}:${expires}`).digest('base64url');
}

export function createAdminToken(secret: string, hash: string, session: string, now = Date.now()): string {
  const expires = String(now + ADMIN_MAX_AGE * 1000);
  return expires + '.' + sign(secret, hash, session, expires);
}

export function verifyAdminToken(token: string | undefined, secret: string, hash: string, session: string, now = Date.now()): boolean {
  if (!token || !secret || !hash || !session) return false;
  const [expires, signature, extra] = token.split('.');
  if (extra || !/^\d+$/u.test(expires) || Number(expires) <= now || Number(expires) > now + ADMIN_MAX_AGE * 1000) return false;
  const expected = Buffer.from(sign(secret, hash, session, expires));
  const supplied = Buffer.from(signature || '');
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

export function isAdmin(request: NextRequest): boolean {
  return isAuthenticated(request) && verifyAdminToken(request.cookies.get(ADMIN_COOKIE)?.value,
    process.env.PPT_SESSION_SECRET || '', process.env.PPT_ADMIN_PASSWORD_HASH || '', request.cookies.get(SESSION_COOKIE)?.value || '');
}

export function requireOrdinaryLogin(request: NextRequest) {
  if (!isAuthenticated(request)) throw new ModelSettingsError('请先使用邀请码登录', 401);
}

export function requireAdmin(request: NextRequest) {
  requireOrdinaryLogin(request);
  if (!isAdmin(request)) throw new ModelSettingsError('请先验证管理员密码', 403);
}

export function requireSameOrigin(request: NextRequest) {
  const expected = process.env.PPT_PUBLIC_ORIGIN || (process.env.NODE_ENV !== 'production' ? request.nextUrl.origin : '');
  if (!expected) throw new ModelSettingsError('管理员站点 Origin 尚未初始化', 503);
  if (request.headers.get('origin') !== expected) throw new ModelSettingsError('管理操作必须来自本站', 403);
}
