import dns from 'node:dns/promises';
import https from 'node:https';
import { isIP } from 'node:net';

export class ModelConnectionError extends Error {
  readonly code = 'PPT_MODEL_CONNECTION';
}

export function isPublicAddress(ip: string): boolean {
  if (isIP(ip) === 4) {
    const [a, b, c] = ip.split('.').map(Number);
    return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && (b === 168 || b === 0 || (b === 88 && c === 99))) ||
      (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) ||
      (a === 203 && b === 0 && c === 113));
  }
  if (isIP(ip) !== 6 || ip.includes('%')) return false;
  const [left, right] = ip.toLowerCase().split('::');
  const head = left ? left.split(':') : [];
  const tail = right ? right.split(':') : [];
  const words = [...head, ...Array(8 - head.length - tail.length).fill('0'), ...tail].map(x => Number.parseInt(x, 16));
  // Only ordinary global unicast: exclude translation, mapped, tunnel and documentation ranges.
  return words[0] >= 0x2000 && words[0] <= 0x3fff &&
    !(words[0] === 0x2001 && (words[1] < 0x0200 || words[1] === 0x0db8)) &&
    words[0] !== 0x2002 && !(words[0] === 0x3fff && words[1] < 0x1000);
}

export function checkedModelUrl(value: string): URL {
  let url: URL;
  try { url = new URL(value); } catch { throw new ModelConnectionError('API 地址格式不正确'); }
  const host = url.hostname.replace(/^\[|\]$/g, '').toLowerCase().replace(/\.$/, '');
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash ||
      /[\u0000-\u0020\\]/u.test(value) || !host || host === 'localhost' ||
      /\.(localhost|local|localdomain|internal)$/u.test(host) ||
      (isIP(host) !== 0 && !isPublicAddress(host))) {
    throw new ModelConnectionError('仅允许不含凭据或查询参数的公网 HTTPS API 地址');
  }
  return url;
}

type Address = { address: string; family: number };
export async function resolveModelTarget(host: string, lookup: (host: string) => Promise<Address[]> = name => dns.lookup(name, { all: true, verbatim: true })) {
  const plain = host.replace(/^\[|\]$/g, '');
  const addresses = isIP(plain) ? [{ address: plain, family: isIP(plain) }] : await lookup(plain);
  if (!addresses.length || addresses.some(x => !isPublicAddress(x.address))) {
    throw new ModelConnectionError('模型接口不能连接内网、保留或云元数据地址');
  }
  return addresses[0];
}

async function postModelJson(endpoint: string, key: string, body: Record<string, unknown>, signal: AbortSignal): Promise<Response> {
  const url = checkedModelUrl(endpoint);
  signal.throwIfAborted();
  let onAbort: () => void = () => {};
  const aborted = new Promise<never>((_, reject) => {
    onAbort = () => reject(new DOMException('Model request aborted', 'AbortError'));
    signal.addEventListener('abort', onAbort, { once: true });
  });
  let target: Address;
  try { target = await Promise.race([resolveModelTarget(url.hostname), aborted]); }
  catch (error) {
    if (signal.aborted) throw new DOMException('Model request aborted', 'AbortError');
    if (error instanceof ModelConnectionError) throw error;
    throw new ModelConnectionError('模型接口域名解析失败');
  } finally { signal.removeEventListener('abort', onAbort); }
  signal.throwIfAborted();
  const data = JSON.stringify(body);
  if (Buffer.byteLength(data) > 128 * 1024) throw new ModelConnectionError('模型请求过大');
  return new Promise<Response>((resolve, reject) => {
    const request = https.request(url, {
      method: 'POST', agent: false, signal, family: target.family,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}`, 'Content-Length': Buffer.byteLength(data) },
      // Pin the validated address; retain the original hostname for certificate/SNI verification.
      lookup: (_host, _options, callback) => callback(null, target.address, target.family),
    }, response => {
      const chunks: Buffer[] = [];
      let bytes = 0;
      if ((response.statusCode || 0) >= 300 && (response.statusCode || 0) < 400) {
        reject(new ModelConnectionError('模型接口重定向已拒绝，请填写最终 API 地址'));
        response.destroy();
        return;
      }
      response.on('data', (chunk: Buffer) => {
        bytes += chunk.length;
        if (bytes > 2 * 1024 * 1024) request.destroy(new ModelConnectionError('模型响应过大'));
        else chunks.push(chunk);
      });
      response.on('error', () => reject(signal.aborted ? new DOMException('Model request aborted', 'AbortError') : new ModelConnectionError('模型响应连接中断')));
      response.on('end', () => {
        try {
          const status = response.statusCode || 502;
          resolve(new Response([204, 205].includes(status) ? null : Buffer.concat(chunks).toString('utf8'), { status }));
        } catch { reject(new ModelConnectionError('模型返回了不兼容的 HTTP 响应')); }
      });
    });
    request.on('error', error => reject(signal.aborted ? new DOMException('Model request aborted', 'AbortError') :
      error instanceof ModelConnectionError ? error : new ModelConnectionError('模型接口连接失败，请检查地址、网络或证书')));
    request.end(data);
  });
}

// The same production transport is used by generation and connection tests.
// Tests replace this in process memory; there is no environment or request bypass.
export const modelTransport = { send: postModelJson };
