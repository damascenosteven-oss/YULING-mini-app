import { NextRequest } from 'next/server';
import { requireAdmin, requireSameOrigin } from '@/lib/ppt/admin-auth';
import { adminBody, adminError, adminJson } from '@/lib/ppt/admin-response';
import { modelSettingsStore } from '@/lib/ppt/model-settings';

export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try { requireAdmin(request); return adminJson(await modelSettingsStore().view()); }
  catch (error) { return adminError(error); }
}

export async function PUT(request: NextRequest) {
  try {
    requireAdmin(request); requireSameOrigin(request);
    const body = await adminBody(request);
    return adminJson(await modelSettingsStore().save(body.config, String(body.revision || '')));
  } catch (error) { return adminError(error); }
}

export async function DELETE(request: NextRequest) {
  try {
    requireAdmin(request); requireSameOrigin(request);
    const body = await adminBody(request);
    return adminJson(await modelSettingsStore().reset(String(body.revision || '')));
  } catch (error) { return adminError(error); }
}
