import { createCipheriv, createDecipheriv, createHash, hkdfSync, randomBytes, randomUUID } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, open, rename, unlink } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { z } from 'zod';
import { checkedModelUrl, modelTransport } from './model-http';

export class ModelSettingsError extends Error {
  constructor(message: string, readonly status = 422, readonly code = 'PPT_MODEL_SETTINGS') { super(message); }
}

export function normalizeBaseUrl(value: string): string {
  const url = checkedModelUrl(value);
  url.pathname = url.pathname.replace(/\/+$/, '').replace(/\/chat\/completions$/, '') || '/';
  return url.toString().replace(/\/$/, '');
}

const configSchema = z.object({
  provider: z.enum(['deepseek', 'openai-compatible']),
  baseUrl: z.string().min(1).max(2048).transform(normalizeBaseUrl),
  model: z.string().trim().min(1).max(200).regex(/^[^\r\n\x00]+$/),
  tokenLimitField: z.enum(['max_tokens', 'max_completion_tokens']),
  apiKey: z.string().max(4096).refine(x => x === x.trim() && !/[\r\n\x00]/u.test(x)),
}).strict().refine(x => x.provider !== 'deepseek' || x.tokenLimitField === 'max_tokens');

export type ModelConfig = z.infer<typeof configSchema>;
export type ModelCandidate = Omit<ModelConfig, 'apiKey'> & { apiKey?: string };
const queues = new Map<string, Promise<unknown>>();

function validated(value: unknown, requireKey = true): ModelConfig {
  try { const config = configSchema.parse(value); if (requireKey && !config.apiKey) throw new Error('key'); return config; }
  catch { throw new ModelSettingsError('模型配置格式不正确，请检查地址、模型名和密钥'); }
}

export class ModelSettingsStore {
  private readonly file: string;
  constructor(private readonly dir: string, private readonly secret: string, private readonly environment: ModelCandidate) {
    if (!isAbsolute(dir)) throw new ModelSettingsError('模型设置目录必须为绝对路径', 503);
    this.file = join(dir, 'settings.json');
  }

  private async directory() {
    const s = await lstat(this.dir);
    if (!s.isDirectory() || s.isSymbolicLink() || (s.mode & 0o077) ||
        (process.getuid && s.uid !== process.getuid())) throw new Error('unsafe directory');
  }

  private key() {
    if (!this.secret) throw new ModelSettingsError('模型设置加密秘密未配置', 503);
    return Buffer.from(hkdfSync('sha256', this.secret, 'yuling-ppt-settings-v1', 'model-api-key', 32));
  }

  async read(): Promise<{ config: ModelConfig; revision: string; source: 'environment' | 'saved' }> {
    try { await this.directory(); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw new ModelSettingsError('模型设置损坏或权限不安全，请联系管理员', 503);
    }
    let handle;
    try { handle = await open(this.file, constants.O_RDONLY | constants.O_NOFOLLOW); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw new ModelSettingsError('模型设置损坏或权限不安全，请联系管理员', 503);
      const config = validated(this.environment, false);
      return { config, source: 'environment', revision: 'environment-' + createHash('sha256').update(JSON.stringify(config)).digest('hex') };
    }
    try {
      const stat = await handle.stat();
      if (!stat.isFile() || stat.size > 65536 || (stat.mode & 0o077) ||
          (process.getuid && stat.uid !== process.getuid())) throw new Error('unsafe settings');
      const envelope = JSON.parse(await handle.readFile('utf8'));
      if (envelope.version !== 1 || typeof envelope.revision !== 'string') throw new Error('version');
      const decipher = createDecipheriv('aes-256-gcm', this.key(), Buffer.from(envelope.iv, 'base64'));
      decipher.setAAD(Buffer.from('v1:' + envelope.revision));
      decipher.setAuthTag(Buffer.from(envelope.tag, 'base64'));
      const payload = JSON.parse(Buffer.concat([decipher.update(Buffer.from(envelope.data, 'base64')), decipher.final()]).toString());
      if (payload?.useEnvironment === true && Object.keys(payload).length === 1) {
        return { config: validated(this.environment, false), revision: envelope.revision, source: 'environment' };
      }
      const config = validated(payload);
      return { config, revision: envelope.revision, source: 'saved' };
    } catch { throw new ModelSettingsError('模型设置损坏或无法解密，请由管理员恢复配置', 503); }
    finally { await handle.close(); }
  }

  async view() {
    const value = await this.read();
    const { apiKey: _key, ...config } = value.config;
    return { ...config, revision: value.revision, source: value.source, apiKeyConfigured: !!value.config.apiKey };
  }

  async candidate(input: unknown): Promise<ModelConfig> {
    if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ModelSettingsError('模型配置格式不正确');
    const value = { ...input } as Record<string, unknown>;
    if (value.apiKey === '' || value.apiKey === undefined) {
      const current = await this.read();
      let same = false;
      try { same = value.provider === current.config.provider && normalizeBaseUrl(String(value.baseUrl)) === current.config.baseUrl; } catch { /* rejected below */ }
      if (!same) throw new ModelSettingsError('更换服务类型或 API 地址时，请重新填写密钥');
      value.apiKey = current.config.apiKey;
    }
    return validated(value);
  }

  private serial<T>(run: () => Promise<T>): Promise<T> {
    const next = (queues.get(this.file) || Promise.resolve()).catch(() => {}).then(run);
    queues.set(this.file, next);
    return next;
  }

  private async persist(config: ModelConfig | { useEnvironment: true }) {
    const next = randomUUID();
    const iv = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', this.key(), iv);
    cipher.setAAD(Buffer.from('v1:' + next));
    const data = Buffer.concat([cipher.update(JSON.stringify(config)), cipher.final()]);
    const value = JSON.stringify({ version: 1, revision: next, iv: iv.toString('base64'), tag: cipher.getAuthTag().toString('base64'), data: data.toString('base64') });
    const temp = join(this.dir, '.settings-' + randomUUID());
    try {
      await this.directory();
      const f = await open(temp, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      try { await f.writeFile(value); await f.sync(); } finally { await f.close(); }
      await rename(temp, this.file);
    } catch { throw new ModelSettingsError('模型设置保存失败，原配置保持不变', 503); }
    finally { await unlink(temp).catch(error => { if (error.code !== 'ENOENT') throw new ModelSettingsError('临时配置清理失败，请联系管理员', 503); }); }
    return this.view();
  }

  async save(input: unknown, revision: string) {
    return this.serial(async () => {
      const current = await this.read();
      if (revision !== current.revision) throw new ModelSettingsError('配置已变化，请刷新后重新保存', 409);
      return this.persist(await this.candidate(input));
    });
  }

  async reset(revision: string) {
    return this.serial(async () => {
      const current = await this.read();
      if (revision !== current.revision) throw new ModelSettingsError('配置已变化，请刷新后重试', 409);
      validated(this.environment, false);
      // Retain only an authenticated fresh revision, never a copy of the environment key.
      return this.persist({ useEnvironment: true });
    });
  }
}

export function modelSettingsStore() {
  return new ModelSettingsStore(process.env.PPT_MODEL_SETTINGS_DIR || '/var/lib/yuling-ppt/model-settings', process.env.PPT_SESSION_SECRET || '', {
    provider: 'deepseek', baseUrl: process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com',
    model: process.env.DEEPSEEK_MODEL || 'deepseek-flash', tokenLimitField: 'max_tokens', apiKey: process.env.DEEPSEEK_API_KEY || '',
  });
}

export async function testModelConnection(config: ModelConfig) {
  const started = performance.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const standard = config.provider === 'deepseek' && new URL(config.baseUrl).origin === 'https://api.deepseek.com' && config.model === 'deepseek-flash';
    const response = await modelTransport.send(config.baseUrl + '/chat/completions', config.apiKey, {
      model: config.model, messages: [{ role: 'user', content: 'Return only this JSON object: {"ok":true}' }],
      response_format: { type: 'json_object' }, stream: false, [config.tokenLimitField]: 128,
      ...(standard ? { thinking: { type: 'disabled' } } : {}),
    }, controller.signal);
    if (!response.ok) throw new ModelSettingsError(response.status === 401 || response.status === 403 ? '模型鉴权失败，请检查密钥' : response.status === 404 ? '接口或模型不存在，请检查地址和模型名' : '模型接口拒绝请求，请检查兼容格式、额度和参数', 502);
    const payload = await response.json();
    const content = payload?.choices?.[0]?.message?.content;
    if (typeof content !== 'string' || JSON.parse(content)?.ok !== true) throw new ModelSettingsError('模型未返回兼容的 JSON 输出', 502);
    return { ok: true, elapsedMs: Math.round(performance.now() - started), model: config.model };
  } catch (error) {
    if (controller.signal.aborted) throw new ModelSettingsError('模型连接测试超时', 504);
    if (error instanceof ModelSettingsError) throw error;
    throw new ModelSettingsError('模型连接失败或未返回兼容的 JSON 输出', 502);
  } finally { clearTimeout(timer); }
}
