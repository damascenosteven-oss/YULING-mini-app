'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ModelConfig } from '@/lib/ppt/model-settings';

type View = Omit<ModelConfig, 'apiKey'> & { revision: string; source: 'environment' | 'saved'; apiKeyConfigured: boolean };
type Form = ModelConfig;
const initial: Form = { provider: 'deepseek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-flash', apiKey: '', tokenLimitField: 'max_tokens' };
const base = '/api/ppt/admin';

async function api(path: string, method = 'GET', body?: unknown) {
  const response = await fetch(base + path, { method, cache: 'no-store', credentials: 'same-origin',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.error === 'string' ? value.error : '请求失败');
  return value;
}

export default function ModelSettings() {
  const [authenticated, setAuthenticated] = useState(false);
  const [configured, setConfigured] = useState(true);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState('');
  const [view, setView] = useState<View | null>(null);
  const [form, setForm] = useState<Form>(initial);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  function display(value: View) {
    setView(value);
    setForm({ provider: value.provider, baseUrl: value.baseUrl, model: value.model, tokenLimitField: value.tokenLimitField, apiKey: '' });
  }

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const status = await api('/session');
        if (!active) return;
        setConfigured(status.configured);
        setAuthenticated(status.authenticated);
        if (status.authenticated) {
          const value = await api('/model-settings');
          if (active) display(value);
        }
      } catch (failure) { if (active) setError(failure instanceof Error ? failure.message : '读取设置失败'); }
      finally { if (active) setChecking(false); }
    })();
    return () => { active = false; };
  }, []);

  async function login() {
    setBusy('login'); setError('');
    try {
      await api('/session', 'POST', { password });
      setPassword(''); setAuthenticated(true);
      display(await api('/model-settings'));
    } catch (failure) { setError(failure instanceof Error ? failure.message : '验证失败'); }
    finally { setPassword(''); setBusy(''); }
  }

  async function operate(action: 'save' | 'test' | 'reset') {
    if (action === 'reset' && !window.confirm('恢复服务器环境变量中的默认模型配置？当前网页保存的配置将移除。')) return;
    setBusy(action); setError(''); setNotice('');
    try {
      if (action === 'test') {
        const result = await api('/model-settings/test', 'POST', { config: form });
        setNotice(`连接及 JSON 输出测试通过，耗时 ${result.elapsedMs} 毫秒。尚未保存，也未生成 PPT。`);
      } else {
        const result = await api('/model-settings', action === 'save' ? 'PUT' : 'DELETE',
          { ...(action === 'save' ? { config: form } : {}), revision: view?.revision });
        display(result);
        setNotice(action === 'save' ? '已保存，新生成请求立即使用此配置。' : '已恢复服务器默认配置。');
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : '操作失败'); }
    finally { setBusy(''); }
  }

  return <main className="mx-auto min-h-screen w-full max-w-lg space-y-4 px-4 py-6">
    <div className="flex items-center justify-between gap-3"><h1 className="text-xl font-extrabold">模型设置</h1><Link className="text-sm text-[var(--brand-600)] underline" href="/ppt">返回工作台</Link></div>
    <p className="text-sm text-[var(--muted-clr)]">管理员配置，全站共用。普通生成无需另外配置搜索 API。</p>
    {checking ? <p>正在检查登录状态…</p> : !authenticated ? <Card>
      <CardHeader><CardTitle>验证管理员身份</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">请先在工作台使用邀请码登录，再输入独立管理员密码。邀请码不能用于管理模型。</p>
        {!configured && <p className="text-sm text-amber-700">管理员密码尚未初始化，请联系服务器管理员完成初始化。</p>}
        <form onSubmit={event => { event.preventDefault(); void login(); }} className="space-y-3">
          <Label htmlFor="admin-password">管理员密码</Label><Input id="admin-password" type="password" autoComplete="current-password" maxLength={200} value={password} onChange={event => setPassword(event.target.value)} />
          <Button className="w-full" disabled={!!busy || !password || !configured} type="submit">{busy ? '正在验证…' : '进入设置'}</Button>
        </form>
      </CardContent>
    </Card> : <Card>
      <CardHeader><CardTitle>当前模型</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {view && <p className="text-xs text-[var(--muted-clr)]">来源：{view.source === 'saved' ? '管理员保存' : '服务器默认'} · 密钥{view.apiKeyConfigured ? '已配置' : '未配置'}</p>}
        <div className="space-y-2"><Label htmlFor="provider">服务类型</Label><select id="provider" className="h-10 w-full rounded-md border bg-white px-3 text-sm" value={form.provider} onChange={event => {
          const provider = event.target.value as Form['provider'];
          setForm(provider === 'deepseek' ? { ...initial } : { ...form, provider, apiKey: '' });
        }}><option value="deepseek">DeepSeek</option><option value="openai-compatible">OpenAI 兼容</option></select></div>
        <div className="space-y-2"><Label htmlFor="api-base">API Base URL</Label><Input id="api-base" type="url" autoComplete="off" value={form.baseUrl} onChange={event => setForm({ ...form, baseUrl: event.target.value })} placeholder="https://服务地址/v1" /><p className="text-xs text-[var(--muted-clr)]">仅支持公网 HTTPS；保留服务商要求的 /v1 或代理路径，无需开放服务器端口。</p></div>
        <div className="space-y-2"><Label htmlFor="model-name">模型名</Label><Input id="model-name" autoComplete="off" value={form.model} onChange={event => setForm({ ...form, model: event.target.value })} placeholder="填写服务商提供的模型名" /></div>
        <div className="space-y-2"><Label htmlFor="model-key">API Key</Label><Input id="model-key" type="password" autoComplete="new-password" maxLength={4096} value={form.apiKey} onChange={event => setForm({ ...form, apiKey: event.target.value })} placeholder={view?.apiKeyConfigured ? '已配置；地址不变时留空保留' : '填写 API Key'} /><p className="text-xs text-[var(--muted-clr)]">密钥不回显。更换服务类型或地址时必须重新填写。</p></div>
        <details className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer">高级兼容设置</summary><div className="mt-3 space-y-2"><Label htmlFor="token-field">输出长度参数</Label><select id="token-field" className="h-10 w-full rounded-md border bg-white px-2" disabled={form.provider === 'deepseek'} value={form.tokenLimitField} onChange={event => setForm({ ...form, tokenLimitField: event.target.value as Form['tokenLimitField'] })}><option value="max_tokens">max_tokens（DeepSeek 及多数兼容接口）</option><option value="max_completion_tokens">max_completion_tokens（按服务商文档选择）</option></select><p className="text-xs text-[var(--muted-clr)]">服务需支持 Chat Completions、Bearer 鉴权及 JSON 输出。</p></div></details>
        <p className="text-xs text-[var(--muted-clr)]">测试连接会产生一次小型模型请求，可能收费；测试不保存。保存不会调用模型。测试通过不代表完整 PPT 生成通过。</p>
        <div className="flex gap-2"><Button className="flex-1" variant="outline" disabled={!!busy} onClick={() => void operate('test')}>{busy === 'test' ? '测试中…' : '测试连接'}</Button><Button className="flex-1" disabled={!!busy || !view} onClick={() => void operate('save')}>{busy === 'save' ? '保存中…' : '保存配置'}</Button></div>
        <div className="flex flex-wrap justify-between gap-3"><Button size="sm" variant="ghost" disabled={!!busy || !view} onClick={() => void operate('reset')}>恢复服务器默认</Button><Button size="sm" variant="ghost" disabled={!!busy} onClick={() => {
          void api('/session', 'DELETE').then(() => { setAuthenticated(false); setForm(initial); setView(null); setNotice(''); }).catch(failure => setError(failure instanceof Error ? failure.message : '退出失败'));
        }}>退出管理</Button></div>
      </CardContent>
    </Card>}
    {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p>}
  </main>;
}
