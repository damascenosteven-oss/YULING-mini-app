import { NextRequest, NextResponse } from 'next/server';
import { ModelSettingsError } from './model-settings';
import { ModelConnectionError } from './model-http';

export function adminJson(value: unknown, status = 200) {
  return NextResponse.json(value, { status, headers: { 'Cache-Control': 'no-store' } });
}

export function adminError(error: unknown) {
  if (error instanceof ModelSettingsError) return adminJson({ error: error.message, code: error.code }, error.status);
  if (error instanceof ModelConnectionError) return adminJson({ error: error.message, code: error.code }, 422);
  return adminJson({ error: '管理操作失败，请联系管理员检查服务器配置', code: 'PPT_ADMIN_ERROR' }, 503);
}

export async function adminBody(request: NextRequest): Promise<Record<string, unknown>> {
  const text = await request.text();
  if (Buffer.byteLength(text) > 16 * 1024) throw new ModelSettingsError('配置请求过大');
  try {
    const value = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('object');
    return value;
  } catch { throw new ModelSettingsError('配置请求格式不正确'); }
}
