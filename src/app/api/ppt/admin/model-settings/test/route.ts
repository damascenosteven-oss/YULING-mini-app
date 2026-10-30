import { NextRequest } from 'next/server';
import { requireAdmin, requireSameOrigin } from '@/lib/ppt/admin-auth';
import { adminBody, adminError, adminJson } from '@/lib/ppt/admin-response';
import { ModelSettingsError, modelSettingsStore, testModelConnection } from '@/lib/ppt/model-settings';
import { consumeRateLimit } from '@/lib/ppt/rate-limit';

export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    requireAdmin(request); requireSameOrigin(request);
    if (!consumeRateLimit('admin-model-test', 3, 60_000)) throw new ModelSettingsError('连接测试过于频繁，请稍后再试', 429);
    const body = await adminBody(request);
    return adminJson(await testModelConnection(await modelSettingsStore().candidate(body.config)));
  } catch (error) { return adminError(error); }
}
