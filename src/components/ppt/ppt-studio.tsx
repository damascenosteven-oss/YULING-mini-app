'use client';

import { useEffect, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowUp, Copy, History, LogOut, Presentation, RefreshCw, Sparkles, Trash2 } from 'lucide-react';
import Link from 'next/link';
import Logo from '@/components/logo';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { DeckOutline, MotionMode, MotionPlan, PublicSkillId, Slide, SlideTheme } from '@/lib/ppt/schema';
import { PRESENTATION_SKILLS, skillLabel } from '@/lib/ppt/skills';

type JsonResponse = Record<string, unknown>;
type HistoryItem = {
  code: string;
  title: string;
  createdAt: string;
  expiresAt: string;
  researchStatus: 'not-required' | 'completed';
  motionProfile?: string;
  skillLabel?: string;
};

type SkillChoice = 'auto' | PublicSkillId;
const skillChoices: Array<{ id: SkillChoice; label: string; description: string }> = [
  { id: 'auto', label: '自动选择', description: 'YuLing AI 根据需求判断' },
  ...Object.values(PRESENTATION_SKILLS).map(skill => ({ id: skill.id, label: skill.label, description: skill.description })),
];

const motionModeOptions: Array<{ value: MotionMode; label: string }> = [
  { value: 'auto', label: '自动判断' },
  { value: 'subtle', label: '商务克制' },
  { value: 'balanced', label: '标准动效' },
  { value: 'vivid', label: '绚丽动效' },
];

function motionPlanLabel(plan: MotionPlan | undefined): string {
  if (!plan) return '等待自动编排';
  const personas = { business: '商务克制', training: '培训活泼', cinematic: '发布会电影感' } as const;
  const backgrounds = { aurora: '极光', particles: '粒子星场', 'kinetic-grid': '动态网格', spotlight: '聚光舞台', orbit: '轨道光环' } as const;
  return `${personas[plan.persona]} · ${backgrounds[plan.background]}`;
}

async function requestJson(url: string, init?: RequestInit): Promise<JsonResponse> {
  const response = await fetch(url, init);
  const body: unknown = await response.json().catch(() => ({}));
  const result = body && typeof body === 'object' ? (body as JsonResponse) : {};
  if (!response.ok) throw new Error(typeof result.error === 'string' ? result.error : '请求失败');
  return result;
}

const lines = (value: string) => value.split('\n').map(item => item.trim()).filter(Boolean);

const variantOptions: Record<Slide['type'], Array<{ value: string; label: string }>> = {
  cover: [{ value: 'cinematic', label: '电影感封面' }, { value: 'split-hero', label: '分栏主视觉' }],
  bullets: [{ value: 'feature-list', label: '重点清单' }, { value: 'three-cards', label: '三卡布局' }, { value: 'spotlight', label: '核心观点' }],
  comparison: [{ value: 'versus', label: '正反对比' }, { value: 'two-column', label: '左右对照' }],
  process: [{ value: 'flow', label: '流程图' }, { value: 'ladder', label: '阶梯图' }, { value: 'roadmap', label: '路线图' }],
  tree: [{ value: 'mind-map', label: '思维导图' }, { value: 'layer-stack', label: '分层结构' }],
  venn: [{ value: 'circles', label: '两圈交集' }],
  closing: [{ value: 'action-card', label: '行动清单' }, { value: 'quote', label: '金句收束' }],
  kpi: [{ value: 'dashboard', label: 'KPI 仪表盘' }],
  chart: [{ value: 'bar', label: '柱状对比' }, { value: 'line', label: '折线趋势' }, { value: 'donut', label: '环形占比' }, { value: 'scatter', label: '散点与基准线' }, { value: 'radar', label: '雷达能力图' }, { value: 'stacked-bar', label: '堆叠构成' }],
  funnel: [{ value: 'conversion', label: '转化漏斗' }],
  matrix: [{ value: 'quadrant', label: '2×2 商业矩阵' }],
  ranking: [{ value: 'horizontal-bars', label: '门店/区域排名' }, { value: 'grouped', label: '多分组排名' }],
  table: [{ value: 'data-table', label: '数据表格' }, { value: 'highlight-table', label: '条件高亮表' }, { value: 'financial-return', label: '财务收益' }],
  heatmap: [{ value: 'matrix', label: '热力矩阵' }],
  methodology: [{ value: 'score-model', label: '指标与权重' }],
};

const themeOptions: Array<{ value: SlideTheme; label: string }> = [
  { value: 'blue', label: '科技蓝' },
  { value: 'violet', label: '紫粉' },
  { value: 'sunset', label: '日落橙' },
  { value: 'mint', label: '薄荷绿' },
  { value: 'fire', label: '餐饮零售红' },
];

type DataSlide = Extract<Slide, { type: 'kpi' | 'chart' | 'funnel' | 'matrix' | 'ranking' | 'table' | 'heatmap' | 'methodology' }>;
const numberValue = (value: string) => Number.isFinite(Number(value)) ? Number(value) : 0;
const numberLines = (value: string) => value.split(/[，,\n]/).map(item => numberValue(item.trim()));

function DataMetaEditor({ slide, onChange }: { slide: DataSlide; onChange: (slide: DataSlide) => void }) {
  return <div className="space-y-2 rounded-xl bg-slate-50 p-3">
    <div className="grid grid-cols-2 gap-2">
      <Select value={slide.dataStatus} onValueChange={value => onChange({ ...slide, dataStatus: value as DataSlide['dataStatus'] } as DataSlide)}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="demo">演示数据</SelectItem><SelectItem value="user-provided">用户提供</SelectItem><SelectItem value="researched" disabled={slide.dataStatus !== 'researched'}>联网调研</SelectItem></SelectContent></Select>
      <Input value={slide.unit || ''} onChange={event => onChange({ ...slide, unit: event.target.value } as DataSlide)} placeholder="单位，如 万元" />
    </div>
    <Input value={slide.source || ''} onChange={event => onChange({ ...slide, source: event.target.value } as DataSlide)} placeholder={slide.dataStatus === 'user-provided' ? '数据来源（必填）' : '来源（可选）'} />
    <Input value={slide.note || ''} onChange={event => onChange({ ...slide, note: event.target.value } as DataSlide)} placeholder="数据口径或备注" />
    {slide.story && <div className="space-y-2 rounded-lg border border-blue-100 bg-white p-2"><Input value={slide.story.question} onChange={event => onChange({ ...slide, story: { ...slide.story!, question: event.target.value } } as DataSlide)} placeholder="这页回答的问题" /><Textarea value={slide.story.claim} onChange={event => onChange({ ...slide, story: { ...slide.story!, claim: event.target.value } } as DataSlide)} rows={2} placeholder="数据结论标题" /><Textarea value={slide.story.implication} onChange={event => onChange({ ...slide, story: { ...slide.story!, implication: event.target.value } } as DataSlide)} rows={2} placeholder="管理含义或行动建议" /><Input value={slide.story.focusKeys.join('、')} onChange={event => onChange({ ...slide, story: { ...slide.story!, focusKeys: event.target.value.split(/[、,，]/).map(item => item.trim()).filter(Boolean).slice(0, 3) } } as DataSlide)} placeholder="重点对象，最多3个" /></div>}
    {slide.dataStatus === 'researched' && <p className="text-[11px] text-[var(--muted-clr)]">引用来源：{slide.sourceIds?.join('、') || '未绑定'}</p>}
  </div>;
}

function SlideEditor({ slide, index, count, onChange, onMove, onDelete }: {
  slide: Slide;
  index: number;
  count: number;
  onChange: (slide: Slide) => void;
  onMove: (direction: -1 | 1) => void;
  onDelete: () => void;
}) {
  const common = (patch: Partial<Slide>) => onChange({ ...slide, ...patch } as Slide);
  const changeVariant = (variant: string) => {
    const dataDefaults = 'dataStatus' in slide ? {
      dataStatus: slide.dataStatus, source: slide.source, unit: slide.unit, note: slide.note,
      sourceIds: slide.sourceIds, story: slide.story,
    } : {};
    const chartLabels = slide.type === 'chart' && 'labels' in slide ? slide.labels : ['A', 'B', 'C', 'D'];
    const chartValues = slide.type === 'chart' && 'values' in slide
      ? slide.values
      : slide.type === 'chart' && 'series' in slide ? slide.series[0]?.values || chartLabels.map(() => 0) : chartLabels.map(() => 0);
    if (slide.type === 'chart' && variant === 'donut') {
      onChange({ ...slide, ...dataDefaults, variant: 'donut', labels: chartLabels.slice(0, 6), values: chartValues.slice(0, 6), center: '100%' } as Slide);
      return;
    }
    if (slide.type === 'chart' && (variant === 'bar' || variant === 'line' || variant === 'stacked-bar')) {
      const labels = chartLabels.slice(0, 8);
      const values = chartValues.slice(0, labels.length);
      const series = variant === 'stacked-bar'
        ? [{ name: '组成 A', values: values.map(value => Math.max(0, value)) }, { name: '组成 B', values: values.map(() => 0) }]
        : [{ name: '数据', values }];
      onChange({ ...slide, ...dataDefaults, variant, labels, series, ...(variant === 'stacked-bar' ? { mode: 'absolute' as const } : {}) } as Slide);
      return;
    }
    if (slide.type === 'chart' && variant === 'scatter') {
      onChange({ ...slide, ...dataDefaults, variant: 'scatter', xAxis: { label: 'X 轴', min: 0, max: 100 }, yAxis: { label: 'Y 轴', min: 0, max: 100 }, points: [{ label: '对象 A', x: 25, y: 35 }, { label: '对象 B', x: 55, y: 70 }, { label: '对象 C', x: 80, y: 45 }], referenceLines: [] } as Slide);
      return;
    }
    if (slide.type === 'chart' && variant === 'radar') {
      onChange({ ...slide, ...dataDefaults, variant: 'radar', axes: ['效率', '质量', '成本', '体验'], maxValue: 100, series: [{ name: '本期', values: [70, 75, 65, 80] }] } as Slide);
      return;
    }
    if (slide.type === 'table' && variant === 'financial-return') {
      onChange({ ...slide, variant: 'financial-return', currency: 'CNY', horizonMonths: 12, investment: 1, items: [{ label: '项目一', baseline: 0, proposed: 0 }, { label: '项目二', baseline: 0, proposed: 0 }] });
      return;
    }
    if (slide.type === 'table' && variant === 'data-table') {
      onChange({ ...slide, variant: 'data-table', headers: ['项目', '数值'], rows: [{ label: '项目一', values: ['0'] }, { label: '项目二', values: ['0'] }] });
      return;
    }
    if (slide.type === 'table' && variant === 'highlight-table') {
      onChange({ ...slide, variant: 'highlight-table', headers: ['项目', '数值'], rows: [{ label: '项目一', values: ['0'] }, { label: '项目二', values: ['0'] }], highlights: [] } as Slide);
      return;
    }
    if (slide.type === 'ranking' && variant === 'horizontal-bars') {
      onChange({ ...slide, variant: 'horizontal-bars', entries: [{ label: '项目 A', value: 80 }, { label: '项目 B', value: 70 }, { label: '项目 C', value: 60 }] } as Slide);
      return;
    }
    if (slide.type === 'ranking' && variant === 'grouped') {
      onChange({ ...slide, variant: 'grouped', groups: [{ title: '分组 A', entries: [{ label: 'A1', value: 80 }, { label: 'A2', value: 70 }, { label: 'A3', value: 60 }] }, { title: '分组 B', entries: [{ label: 'B1', value: 78 }, { label: 'B2', value: 68 }, { label: 'B3', value: 58 }] }] } as Slide);
      return;
    }
    common({ variant } as Partial<Slide>);
  };
  return (
    <Card className="border-[var(--line-clr)] shadow-none">
      <CardHeader className="space-y-3 pb-3">
        <div className="flex items-center justify-between">
          <span className="rounded-full bg-[var(--brand-50)] px-2.5 py-1 text-[11px] font-bold text-[var(--brand-600)]">{index + 1} · {slide.type}</span>
          <div className="flex gap-1">
            <Button size="icon-sm" variant="ghost" disabled={index === 0} onClick={() => onMove(-1)} aria-label="上移"><ArrowUp /></Button>
            <Button size="icon-sm" variant="ghost" disabled={index === count - 1} onClick={() => onMove(1)} aria-label="下移"><ArrowDown /></Button>
            <Button size="icon-sm" variant="ghost" disabled={count <= 6} onClick={onDelete} aria-label="删除"><Trash2 /></Button>
          </div>
        </div>
        <Input value={slide.title} onChange={event => common({ title: event.target.value })} aria-label="页面标题" />
        <Input value={slide.subtitle || ''} onChange={event => common({ subtitle: event.target.value })} placeholder="副标题（可选）" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1.5"><Label className="text-xs">页面版式</Label><Select value={slide.variant} onValueChange={changeVariant}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{variantOptions[slide.type].map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>
          <div className="space-y-1.5"><Label className="text-xs">色彩主题</Label><Select value={slide.theme} onValueChange={value => common({ theme: value as SlideTheme })}><SelectTrigger className="w-full"><SelectValue /></SelectTrigger><SelectContent>{themeOptions.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>
        </div>
        {slide.type === 'cover' && <Textarea value={slide.tagline} onChange={event => onChange({ ...slide, tagline: event.target.value })} />}
        {slide.type === 'bullets' && <Textarea value={slide.items.join('\n')} onChange={event => onChange({ ...slide, items: lines(event.target.value) })} rows={5} />}
        {slide.type === 'comparison' && (
          <div className="grid grid-cols-2 gap-2">
            <div><Input value={slide.left.title} onChange={event => onChange({ ...slide, left: { ...slide.left, title: event.target.value } })} /><Textarea className="mt-2" value={slide.left.items.join('\n')} onChange={event => onChange({ ...slide, left: { ...slide.left, items: lines(event.target.value) } })} /></div>
            <div><Input value={slide.right.title} onChange={event => onChange({ ...slide, right: { ...slide.right, title: event.target.value } })} /><Textarea className="mt-2" value={slide.right.items.join('\n')} onChange={event => onChange({ ...slide, right: { ...slide.right, items: lines(event.target.value) } })} /></div>
          </div>
        )}
        {slide.type === 'process' && slide.steps.map((step, stepIndex) => (
          <div className="grid grid-cols-[1fr_1.5fr] gap-2" key={stepIndex}>
            <Input value={step.title} onChange={event => onChange({ ...slide, steps: slide.steps.map((item, i) => i === stepIndex ? { ...item, title: event.target.value } : item) })} />
            <Input value={step.description} onChange={event => onChange({ ...slide, steps: slide.steps.map((item, i) => i === stepIndex ? { ...item, description: event.target.value } : item) })} />
          </div>
        ))}
        {slide.type === 'tree' && (
          <div className="space-y-2">
            <Input value={slide.root} onChange={event => onChange({ ...slide, root: event.target.value })} placeholder="中心主题" />
            {slide.branches.map((branch, branchIndex) => (
              <div className="grid grid-cols-[1fr_1.5fr] gap-2" key={branchIndex}>
                <Input value={branch.title} onChange={event => onChange({ ...slide, branches: slide.branches.map((item, i) => i === branchIndex ? { ...item, title: event.target.value } : item) })} />
                <Textarea value={branch.items.join('\n')} onChange={event => onChange({ ...slide, branches: slide.branches.map((item, i) => i === branchIndex ? { ...item, items: lines(event.target.value) } : item) })} rows={2} />
              </div>
            ))}
          </div>
        )}
        {slide.type === 'venn' && (
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2"><Input value={slide.leftTitle} onChange={event => onChange({ ...slide, leftTitle: event.target.value })} /><Input value={slide.rightTitle} onChange={event => onChange({ ...slide, rightTitle: event.target.value })} /></div>
            <Textarea value={slide.left.join('\n')} onChange={event => onChange({ ...slide, left: lines(event.target.value) })} placeholder="左侧特征，每行一项" />
            <Textarea value={slide.overlap.join('\n')} onChange={event => onChange({ ...slide, overlap: lines(event.target.value) })} placeholder="共同特征，每行一项" />
            <Textarea value={slide.right.join('\n')} onChange={event => onChange({ ...slide, right: lines(event.target.value) })} placeholder="右侧特征，每行一项" />
          </div>
        )}
        {slide.type === 'closing' && <><Textarea value={slide.summary} onChange={event => onChange({ ...slide, summary: event.target.value })} /><Textarea value={slide.actions.join('\n')} onChange={event => onChange({ ...slide, actions: lines(event.target.value) })} /></>}
        {'dataStatus' in slide && <DataMetaEditor slide={slide} onChange={updated => onChange(updated)} />}
        {slide.type === 'kpi' && <div className="space-y-2">{slide.metrics.map((metric, metricIndex) => <div className="grid grid-cols-[1.2fr_.8fr_.7fr_auto] gap-2" key={metricIndex}>
          <Input value={metric.label} onChange={event => onChange({ ...slide, metrics: slide.metrics.map((item, i) => i === metricIndex ? { ...item, label: event.target.value } : item) })} placeholder="指标" />
          <Input type="number" value={metric.value} onChange={event => onChange({ ...slide, metrics: slide.metrics.map((item, i) => i === metricIndex ? { ...item, value: numberValue(event.target.value) } : item) })} placeholder="数值" />
          <Input value={metric.suffix || ''} onChange={event => onChange({ ...slide, metrics: slide.metrics.map((item, i) => i === metricIndex ? { ...item, suffix: event.target.value } : item) })} placeholder="单位" />
          <Button size="icon-sm" variant="ghost" disabled={slide.metrics.length <= 2} onClick={() => onChange({ ...slide, metrics: slide.metrics.filter((_, i) => i !== metricIndex) })}><Trash2 /></Button>
        </div>)}<Button size="sm" variant="outline" disabled={slide.metrics.length >= 4} onClick={() => onChange({ ...slide, metrics: [...slide.metrics, { label: '新指标', value: 0, direction: 'flat' }] })}>增加指标</Button></div>}
        {slide.type === 'chart' && (slide.variant === 'bar' || slide.variant === 'line' || slide.variant === 'stacked-bar') && <div className="space-y-2">
          {slide.variant === 'stacked-bar' && <Select value={slide.mode} onValueChange={value => onChange({ ...slide, mode: value as 'absolute' | 'percent' })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="absolute">绝对值堆叠</SelectItem><SelectItem value="percent">100% 占比</SelectItem></SelectContent></Select>}
          <Textarea value={slide.labels.join('\n')} onChange={event => onChange({ ...slide, labels: lines(event.target.value) })} rows={3} placeholder="类目，每行一项" />
          {slide.series.map((series, seriesIndex) => <div className="grid grid-cols-[1fr_1.5fr_auto] gap-2" key={seriesIndex}><Input value={series.name} onChange={event => onChange({ ...slide, series: slide.series.map((item, i) => i === seriesIndex ? { ...item, name: event.target.value } : item) })} placeholder="系列名" /><Input value={series.values.join(',')} onChange={event => onChange({ ...slide, series: slide.series.map((item, i) => i === seriesIndex ? { ...item, values: numberLines(event.target.value) } : item) })} placeholder="逗号分隔数值" /><Button size="icon-sm" variant="ghost" disabled={slide.series.length <= 1} onClick={() => onChange({ ...slide, series: slide.series.filter((_, i) => i !== seriesIndex) })}><Trash2 /></Button></div>)}
          <Button size="sm" variant="outline" disabled={slide.series.length >= (slide.variant === 'stacked-bar' ? 5 : 3)} onClick={() => onChange({ ...slide, series: [...slide.series, { name: '新系列', values: slide.labels.map(() => 0) }] })}>增加系列</Button>
        </div>}
        {slide.type === 'chart' && slide.variant === 'donut' && <div className="space-y-2">{slide.labels.map((label, itemIndex) => <div className="grid grid-cols-[1fr_1fr_auto] gap-2" key={itemIndex}><Input value={label} onChange={event => onChange({ ...slide, labels: slide.labels.map((item, i) => i === itemIndex ? event.target.value : item) })} /><Input type="number" value={slide.values[itemIndex]} onChange={event => onChange({ ...slide, values: slide.values.map((item, i) => i === itemIndex ? numberValue(event.target.value) : item) })} /><Button size="icon-sm" variant="ghost" disabled={slide.labels.length <= 2} onClick={() => onChange({ ...slide, labels: slide.labels.filter((_, i) => i !== itemIndex), values: slide.values.filter((_, i) => i !== itemIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.labels.length >= 6} onClick={() => onChange({ ...slide, labels: [...slide.labels, '新分组'], values: [...slide.values, 0] })}>增加分组</Button></div>}
        {slide.type === 'chart' && slide.variant === 'scatter' && <div className="space-y-2"><div className="grid grid-cols-2 gap-2"><Input value={slide.xAxis.label} onChange={event => onChange({ ...slide, xAxis: { ...slide.xAxis, label: event.target.value } })} placeholder="X 轴" /><Input value={slide.yAxis.label} onChange={event => onChange({ ...slide, yAxis: { ...slide.yAxis, label: event.target.value } })} placeholder="Y 轴" /></div>{slide.points.map((point, pointIndex) => <div className="grid grid-cols-[1.3fr_.7fr_.7fr_auto] gap-2" key={pointIndex}><Input value={point.label} onChange={event => onChange({ ...slide, points: slide.points.map((item, i) => i === pointIndex ? { ...item, label: event.target.value } : item) })} /><Input type="number" value={point.x} onChange={event => onChange({ ...slide, points: slide.points.map((item, i) => i === pointIndex ? { ...item, x: numberValue(event.target.value) } : item) })} /><Input type="number" value={point.y} onChange={event => onChange({ ...slide, points: slide.points.map((item, i) => i === pointIndex ? { ...item, y: numberValue(event.target.value) } : item) })} /><Button size="icon-sm" variant="ghost" disabled={slide.points.length <= 3} onClick={() => onChange({ ...slide, points: slide.points.filter((_, i) => i !== pointIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.points.length >= 20} onClick={() => onChange({ ...slide, points: [...slide.points, { label: '新对象', x: 50, y: 50 }] })}>增加点位</Button></div>}
        {slide.type === 'chart' && slide.variant === 'radar' && <div className="space-y-2"><Input value={slide.axes.join('、')} onChange={event => onChange({ ...slide, axes: event.target.value.split(/[、,，]/).map(item => item.trim()).filter(Boolean).slice(0, 8) })} placeholder="维度，用顿号分隔" /><Input type="number" value={slide.maxValue} onChange={event => onChange({ ...slide, maxValue: numberValue(event.target.value) })} placeholder="统一最大值" />{slide.series.map((series, seriesIndex) => <div className="grid grid-cols-[1fr_1.5fr_auto] gap-2" key={seriesIndex}><Input value={series.name} onChange={event => onChange({ ...slide, series: slide.series.map((item, i) => i === seriesIndex ? { ...item, name: event.target.value } : item) })} /><Input value={series.values.join(',')} onChange={event => onChange({ ...slide, series: slide.series.map((item, i) => i === seriesIndex ? { ...item, values: numberLines(event.target.value) } : item) })} /><Button size="icon-sm" variant="ghost" disabled={slide.series.length <= 1} onClick={() => onChange({ ...slide, series: slide.series.filter((_, i) => i !== seriesIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.series.length >= 2} onClick={() => onChange({ ...slide, series: [...slide.series, { name: '新系列', values: slide.axes.map(() => 0) }] })}>增加系列</Button></div>}
        {slide.type === 'funnel' && <div className="space-y-2">{slide.stages.map((stage, stageIndex) => <div className="grid grid-cols-[1fr_1fr_auto] gap-2" key={stageIndex}><Input value={stage.label} onChange={event => onChange({ ...slide, stages: slide.stages.map((item, i) => i === stageIndex ? { ...item, label: event.target.value } : item) })} /><Input type="number" value={stage.value} onChange={event => onChange({ ...slide, stages: slide.stages.map((item, i) => i === stageIndex ? { ...item, value: numberValue(event.target.value) } : item) })} /><Button size="icon-sm" variant="ghost" disabled={slide.stages.length <= 3} onClick={() => onChange({ ...slide, stages: slide.stages.filter((_, i) => i !== stageIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.stages.length >= 6} onClick={() => onChange({ ...slide, stages: [...slide.stages, { label: '新阶段', value: 0 }] })}>增加阶段</Button></div>}
        {slide.type === 'matrix' && <div className="space-y-2"><div className="grid grid-cols-2 gap-2"><Input value={slide.axes.xLow} onChange={event => onChange({ ...slide, axes: { ...slide.axes, xLow: event.target.value } })} placeholder="横轴低" /><Input value={slide.axes.xHigh} onChange={event => onChange({ ...slide, axes: { ...slide.axes, xHigh: event.target.value } })} placeholder="横轴高" /><Input value={slide.axes.yLow} onChange={event => onChange({ ...slide, axes: { ...slide.axes, yLow: event.target.value } })} placeholder="纵轴低" /><Input value={slide.axes.yHigh} onChange={event => onChange({ ...slide, axes: { ...slide.axes, yHigh: event.target.value } })} placeholder="纵轴高" /></div><Textarea value={slide.quadrants.join('\n')} onChange={event => { const values = lines(event.target.value); if (values.length <= 4) onChange({ ...slide, quadrants: values }); }} rows={4} placeholder="四象限标题，每行一个" />{slide.points.map((point, pointIndex) => <div className="grid grid-cols-[1.2fr_.7fr_.7fr_auto] gap-2" key={pointIndex}><Input value={point.label} onChange={event => onChange({ ...slide, points: slide.points.map((item, i) => i === pointIndex ? { ...item, label: event.target.value } : item) })} /><Input type="number" min="0" max="100" value={point.x} onChange={event => onChange({ ...slide, points: slide.points.map((item, i) => i === pointIndex ? { ...item, x: numberValue(event.target.value) } : item) })} /><Input type="number" min="0" max="100" value={point.y} onChange={event => onChange({ ...slide, points: slide.points.map((item, i) => i === pointIndex ? { ...item, y: numberValue(event.target.value) } : item) })} /><Button size="icon-sm" variant="ghost" disabled={slide.points.length <= 2} onClick={() => onChange({ ...slide, points: slide.points.filter((_, i) => i !== pointIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.points.length >= 8} onClick={() => onChange({ ...slide, points: [...slide.points, { label: '新场景', x: 50, y: 50 }] })}>增加坐标点</Button></div>}
        {slide.type === 'ranking' && slide.variant === 'horizontal-bars' && <div className="space-y-2">{slide.entries.map((entry, entryIndex) => <div className="grid grid-cols-[1.2fr_.8fr_.8fr_auto] gap-2" key={entryIndex}><Input value={entry.label} onChange={event => onChange({ ...slide, entries: slide.entries.map((item, i) => i === entryIndex ? { ...item, label: event.target.value } : item) })} /><Input type="number" value={entry.value} onChange={event => onChange({ ...slide, entries: slide.entries.map((item, i) => i === entryIndex ? { ...item, value: numberValue(event.target.value) } : item) })} /><Input type="number" value={entry.change || 0} onChange={event => onChange({ ...slide, entries: slide.entries.map((item, i) => i === entryIndex ? { ...item, change: numberValue(event.target.value) } : item) })} placeholder="变化" /><Button size="icon-sm" variant="ghost" disabled={slide.entries.length <= 3} onClick={() => onChange({ ...slide, entries: slide.entries.filter((_, i) => i !== entryIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.entries.length >= 8} onClick={() => onChange({ ...slide, entries: [...slide.entries, { label: '新门店', value: 0 }] })}>增加排名项</Button></div>}
        {slide.type === 'ranking' && slide.variant === 'grouped' && <div className="space-y-3">{slide.groups.map((group, groupIndex) => <div className="space-y-2 rounded-lg border p-2" key={groupIndex}><Input value={group.title} onChange={event => onChange({ ...slide, groups: slide.groups.map((item, i) => i === groupIndex ? { ...item, title: event.target.value } : item) })} />{group.entries.map((entry, entryIndex) => <div className="grid grid-cols-[1.4fr_.8fr] gap-2" key={entryIndex}><Input value={entry.label} onChange={event => onChange({ ...slide, groups: slide.groups.map((item, i) => i === groupIndex ? { ...item, entries: item.entries.map((candidate, j) => j === entryIndex ? { ...candidate, label: event.target.value } : candidate) } : item) })} /><Input type="number" value={entry.value} onChange={event => onChange({ ...slide, groups: slide.groups.map((item, i) => i === groupIndex ? { ...item, entries: item.entries.map((candidate, j) => j === entryIndex ? { ...candidate, value: numberValue(event.target.value) } : candidate) } : item) })} /></div>)}</div>)}</div>}
        {slide.type === 'table' && slide.variant === 'data-table' && <div className="space-y-2"><Textarea value={slide.headers.join('\n')} onChange={event => onChange({ ...slide, headers: lines(event.target.value) })} rows={3} placeholder="表头，每行一列" />{slide.rows.map((row, rowIndex) => <div className="grid grid-cols-[1fr_1.6fr_auto] gap-2" key={rowIndex}><Input value={row.label} onChange={event => onChange({ ...slide, rows: slide.rows.map((item, i) => i === rowIndex ? { ...item, label: event.target.value } : item) })} /><Input value={row.values.join(',')} onChange={event => onChange({ ...slide, rows: slide.rows.map((item, i) => i === rowIndex ? { ...item, values: event.target.value.split(',').map(item => item.trim()) } : item) })} placeholder="其余列，逗号分隔" /><Button size="icon-sm" variant="ghost" disabled={slide.rows.length <= 2} onClick={() => onChange({ ...slide, rows: slide.rows.filter((_, i) => i !== rowIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.rows.length >= 8} onClick={() => onChange({ ...slide, rows: [...slide.rows, { label: '新行', values: slide.headers.slice(1).map(() => '0') }] })}>增加行</Button></div>}
        {slide.type === 'table' && slide.variant === 'financial-return' && <div className="space-y-2"><div className="grid grid-cols-3 gap-2"><Select value={slide.currency} onValueChange={value => onChange({ ...slide, currency: value as 'CNY' | 'USD' })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="CNY">人民币</SelectItem><SelectItem value="USD">美元</SelectItem></SelectContent></Select><Input type="number" value={slide.horizonMonths} onChange={event => onChange({ ...slide, horizonMonths: numberValue(event.target.value) })} placeholder="周期（月）" /><Input type="number" value={slide.investment} onChange={event => onChange({ ...slide, investment: numberValue(event.target.value) })} placeholder="一次性投入" /></div>{slide.items.map((item, itemIndex) => <div className="grid grid-cols-[1.2fr_.8fr_.8fr_auto] gap-2" key={itemIndex}><Input value={item.label} onChange={event => onChange({ ...slide, items: slide.items.map((entry, i) => i === itemIndex ? { ...entry, label: event.target.value } : entry) })} /><Input type="number" value={item.baseline} onChange={event => onChange({ ...slide, items: slide.items.map((entry, i) => i === itemIndex ? { ...entry, baseline: numberValue(event.target.value) } : entry) })} placeholder="基准" /><Input type="number" value={item.proposed} onChange={event => onChange({ ...slide, items: slide.items.map((entry, i) => i === itemIndex ? { ...entry, proposed: numberValue(event.target.value) } : entry) })} placeholder="方案后" /><Button size="icon-sm" variant="ghost" disabled={slide.items.length <= 2} onClick={() => onChange({ ...slide, items: slide.items.filter((_, i) => i !== itemIndex) })}><Trash2 /></Button></div>)}<Button size="sm" variant="outline" disabled={slide.items.length >= 6} onClick={() => onChange({ ...slide, items: [...slide.items, { label: '新项目', baseline: 0, proposed: 0 }] })}>增加成本项</Button></div>}
        {slide.type === 'table' && slide.variant === 'highlight-table' && <div className="space-y-2"><Textarea value={slide.headers.join('\n')} onChange={event => onChange({ ...slide, headers: lines(event.target.value) })} rows={3} placeholder="表头，每行一列" />{slide.rows.map((row, rowIndex) => <div className="grid grid-cols-[1fr_1.6fr] gap-2" key={rowIndex}><Input value={row.label} onChange={event => onChange({ ...slide, rows: slide.rows.map((item, i) => i === rowIndex ? { ...item, label: event.target.value } : item) })} /><Input value={row.values.join(',')} onChange={event => onChange({ ...slide, rows: slide.rows.map((item, i) => i === rowIndex ? { ...item, values: event.target.value.split(',').map(value => value.trim()) } : item) })} /></div>)}<Input value={slide.highlights.map(item => `${item.row + 1}:${item.column + 1}:${item.tone}`).join(',')} onChange={event => { const highlights = event.target.value.split(',').map(item => item.trim().split(':')).filter(parts => parts.length === 3).map(parts => ({ row: Math.max(0, numberValue(parts[0]) - 1), column: Math.max(0, numberValue(parts[1]) - 1), tone: (['best', 'risk', 'focus'].includes(parts[2]) ? parts[2] : 'focus') as 'best' | 'risk' | 'focus' })).slice(0, 12); onChange({ ...slide, highlights }); }} placeholder="高亮：行:列:best/risk/focus" /></div>}
        {slide.type === 'heatmap' && <div className="space-y-2"><Textarea value={slide.columns.join('\n')} onChange={event => onChange({ ...slide, columns: lines(event.target.value) })} rows={3} placeholder="列标题" />{slide.rows.map((row, rowIndex) => <div className="grid grid-cols-[1fr_1.6fr] gap-2" key={rowIndex}><Input value={row.label} onChange={event => onChange({ ...slide, rows: slide.rows.map((item, i) => i === rowIndex ? { ...item, label: event.target.value } : item) })} /><Input value={row.values.join(',')} onChange={event => onChange({ ...slide, rows: slide.rows.map((item, i) => i === rowIndex ? { ...item, values: numberLines(event.target.value) } : item) })} /></div>)}</div>}
        {slide.type === 'methodology' && <div className="space-y-2"><Textarea value={slide.formula} onChange={event => onChange({ ...slide, formula: event.target.value })} rows={2} placeholder="计算说明" />{slide.components.map((component, componentIndex) => <div className="grid grid-cols-[1fr_.6fr_1.4fr] gap-2" key={componentIndex}><Input value={component.label} onChange={event => onChange({ ...slide, components: slide.components.map((item, i) => i === componentIndex ? { ...item, label: event.target.value } : item) })} /><Input type="number" value={component.weight} onChange={event => onChange({ ...slide, components: slide.components.map((item, i) => i === componentIndex ? { ...item, weight: numberValue(event.target.value) } : item) })} /><Input value={component.description} onChange={event => onChange({ ...slide, components: slide.components.map((item, i) => i === componentIndex ? { ...item, description: event.target.value } : item) })} /></div>)}</div>}
      </CardContent>
    </Card>
  );
}

export default function PptStudio() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [password, setPassword] = useState('');
  const [prompt, setPrompt] = useState('');
  const [pageCount, setPageCount] = useState(8);
  const [skillId, setSkillId] = useState<SkillChoice>('auto');
  const [motionMode, setMotionMode] = useState<MotionMode>('auto');
  const [outline, setOutline] = useState<DeckOutline | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<{ code: string; viewerUrl: string; expiresAt: string; qaPages: number } | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [importCode, setImportCode] = useState('');
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    fetch('/api/ppt/session').then(response => response.json()).then(data => setAuthenticated(Boolean(data.authenticated))).catch(() => setAuthenticated(false));
  }, []);

  const loadHistory = async () => {
    try {
      const data = await requestJson('/api/ppt/history');
      setHistory(Array.isArray(data.items) ? data.items as HistoryItem[] : []);
      setHistoryError('');
    } catch (reason) {
      setHistoryError(reason instanceof Error ? reason.message : '最近生成暂时无法读取');
    }
  };

  useEffect(() => {
    if (authenticated) void loadHistory();
  }, [authenticated]);

  const importHistory = async () => {
    const code = importCode.toUpperCase().replace(/[^23456789ABCDEFGHJKLMNPQRSTUVWXYZ]/g, '').slice(0, 8);
    if (code.length !== 8) return;
    setImporting(true); setHistoryError('');
    try {
      await requestJson('/api/ppt/history', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
      setImportCode('');
      await loadHistory();
    } catch (reason) { setHistoryError(reason instanceof Error ? reason.message : '找回作品失败'); }
    finally { setImporting(false); }
  };

  const login = async () => {
    setBusy(true); setError('');
    try {
      await requestJson('/api/ppt/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
      setAuthenticated(true); setPassword('');
    } catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败'); }
    finally { setBusy(false); }
  };

  const generate = async () => {
    setBusy(true); setError(''); setResult(null);
    try {
      const data = await requestJson('/api/ppt/outline', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, pageCount, motionMode, skillId }) });
      setOutline(data as DeckOutline);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '生成失败'); }
    finally { setBusy(false); }
  };

  const refreshMotion = async (mode: MotionMode = motionMode) => {
    if (!outline) return;
    setBusy(true); setError('');
    try {
      const data = await requestJson('/api/ppt/design/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ deck: outline, mode }) });
      if (!data.motionPlan || typeof data.motionPlan !== 'object') throw new Error('动效方案返回不完整');
      setMotionMode(mode);
      setOutline({ ...outline, motionPlan: data.motionPlan as MotionPlan });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '更换动效失败'); }
    finally { setBusy(false); }
  };

  const build = async () => {
    if (!outline) return;
    setBusy(true); setError('');
    try {
      const data = await requestJson('/api/ppt/decks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(outline) });
      const qa = data.qa && typeof data.qa === 'object' ? data.qa as JsonResponse : {};
      setResult({ code: String(data.code), viewerUrl: String(data.viewerUrl), expiresAt: String(data.expiresAt), qaPages: Number(qa.pages) || outline.slides.length });
      await loadHistory();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '生成课件失败'); }
    finally { setBusy(false); }
  };

  if (authenticated === null) return <div className="grid min-h-[100dvh] place-items-center text-sm text-[var(--muted-clr)]">正在检查访问权限…</div>;
  if (!authenticated) return (
    <main className="min-h-[100dvh] px-[18px] py-8">
      <Link href="/" className="mb-8 inline-flex items-center gap-1 text-sm text-[var(--muted-clr)]"><ArrowLeft className="size-4" />返回首页</Link>
      <Card className="border-[var(--line-clr)]">
        <CardHeader><div className="mb-3 grid size-12 place-items-center rounded-2xl mp-brand-gradient text-white"><Presentation /></div><CardTitle>AI PPT 内测</CardTitle><p className="text-sm leading-relaxed text-[var(--muted-clr)]">输入邀请码后，用一句话生成可在电脑放映的 HTML PPT。</p></CardHeader>
        <CardContent className="space-y-4"><div className="space-y-2"><Label>统一邀请码</Label><Input type="password" value={password} onChange={event => setPassword(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void login(); }} /></div>{error && <p className="text-sm text-red-600">{error}</p>}<Button className="w-full mp-brand-gradient" disabled={busy || !password} onClick={() => void login()}>{busy ? '验证中…' : '进入生成器'}</Button></CardContent>
      </Card>
      <p className="mt-4 rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">当前为 HTTP 内测，请勿输入敏感、个人隐私或保密信息。</p>
    </main>
  );

  return (
    <main className="min-h-[100dvh] px-[14px] pb-10 pt-5">
      <header className="mb-5 flex items-center justify-between"><div><div className="flex items-center gap-2 whitespace-nowrap"><Logo size={24} /><span className="text-sm font-extrabold">毓灵 YuLing AI</span><span className="h-4 w-px bg-[var(--line-clr)]" /><span className="text-lg font-extrabold">AI PPT</span></div><p className="mt-1 text-xs text-[var(--muted-clr)]">需求 → 大纲 → HTML 放映</p></div><Button variant="ghost" size="sm" onClick={() => { void fetch('/api/ppt/session', { method: 'DELETE' }).then(() => setAuthenticated(false)); }}><LogOut />退出</Button></header>
      <div className="mb-3 flex justify-end"><Link className="text-sm text-[var(--brand-600)] underline" href="/ppt/settings">模型设置</Link></div>
      <div className="mb-4 rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">内测环境，请勿输入敏感或保密信息。本次未联网，内容和数据需人工核验。</div>
      {!outline ? <div className="space-y-4">
        <Card className="border-[var(--line-clr)] shadow-none"><CardHeader className="pb-3"><div className="flex items-center justify-between"><CardTitle className="flex items-center gap-2 text-base"><History className="size-4 text-[var(--brand-500)]" />最近生成</CardTitle><span className="text-[11px] text-[var(--muted-clr)]">近 7 天</span></div></CardHeader><CardContent className="space-y-3">
          {history.length === 0 ? <p className="text-xs text-[var(--muted-clr)]">当前浏览器还没有保存的作品。</p> : history.map(item => <div key={item.code} className="rounded-xl border border-[var(--line-clr)] bg-white/70 p-3"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-bold">{item.title}</p><p className="mt-1 text-[11px] text-[var(--muted-clr)]">{new Date(item.createdAt).toLocaleString('zh-CN')} · {item.skillLabel || '经典通用'} · {item.researchStatus === 'completed' ? '联网调研' : '普通生成'}{item.motionProfile ? ` · ${item.motionProfile}` : ''}</p></div><span className="shrink-0 font-mono text-xs font-bold">{item.code}</span></div><div className="mt-2 flex gap-2"><Button asChild size="sm" variant="outline" className="flex-1"><Link href={`/ppt/view/${item.code}`}>打开</Link></Button><Button size="icon-sm" variant="ghost" aria-label="复制分享码" onClick={() => void navigator.clipboard.writeText(item.code)}><Copy /></Button></div></div>)}
          <div className="flex gap-2"><Input value={importCode} onChange={event => setImportCode(event.target.value.toUpperCase().replace(/[^23456789ABCDEFGHJKLMNPQRSTUVWXYZ]/g, '').slice(0, 8))} onKeyDown={event => { if (event.key === 'Enter') void importHistory(); }} placeholder="输入分享码找回作品" className="font-mono uppercase" /><Button variant="outline" disabled={importing || importCode.length !== 8} onClick={() => void importHistory()}>{importing ? '找回中…' : '找回'}</Button></div>
          {historyError && <p className="text-xs text-red-600">{historyError}</p>}
        </CardContent></Card>
        <Card className="border-[var(--line-clr)] shadow-none"><CardHeader><CardTitle className="text-base">描述你想讲什么</CardTitle></CardHeader><CardContent className="space-y-4"><Textarea value={prompt} onChange={event => setPrompt(event.target.value)} rows={9} placeholder="例如：调查目前宁波就业市场，生成一份带公开来源的 10 页培训规划汇报。" /><div className="space-y-2"><Label>Presentation Skill</Label><div className="grid grid-cols-2 gap-2">{skillChoices.map(choice => <button type="button" key={choice.id} onClick={() => setSkillId(choice.id)} className={`rounded-xl border p-3 text-left transition ${skillId === choice.id ? 'border-[var(--brand-500)] bg-[var(--brand-50)]' : 'border-[var(--line-clr)] bg-white'}`}><span className="block text-xs font-extrabold">{choice.label}</span><span className="mt-1 block text-[10px] leading-relaxed text-[var(--muted-clr)]">{choice.description}</span></button>)}</div></div><div className="space-y-2"><Label>页数：{pageCount}</Label><input className="w-full accent-[var(--brand-500)]" type="range" min="6" max="12" value={pageCount} onChange={event => setPageCount(Number(event.target.value))} /></div><div className="space-y-2"><Label>动效强度</Label><Select value={motionMode} onValueChange={value => setMotionMode(value as MotionMode)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{motionModeOptions.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>{error && <p className="text-sm text-red-600">{error}</p>}<Button className="w-full mp-brand-gradient" disabled={busy || prompt.trim().length < 20} onClick={() => void generate()}>{busy ? 'YuLing AI 正在生成大纲…' : '生成大纲'}</Button></CardContent></Card>
      </div> : (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3"><div className="min-w-0"><h1 className="truncate font-extrabold">{outline.title}</h1><p className="text-xs text-[var(--muted-clr)]">{skillLabel(outline.skill.id)} v{outline.skill.version} · {outline.skill.selectedBy === 'user' ? '手动选择' : outline.skill.selectedBy === 'auto' ? '自动识别' : '经典兼容'}</p></div><Button variant="outline" size="sm" onClick={() => { setSkillId(outline.skill.id === 'legacy-general' ? 'auto' : outline.skill.id); setOutline(null); setResult(null); }}>更换 Skill</Button></div>
          {outline.research.status === 'completed' && <Card className="border-blue-200 bg-blue-50/70 shadow-none"><CardContent className="pt-4"><p className="text-xs font-bold text-blue-800">已检索 {outline.research.sources.length} 个公开来源 · 数据仍需人工核验</p><div className="mt-2 max-h-28 space-y-1 overflow-y-auto">{outline.research.sources.map(source => <p key={source.id} className="truncate text-[11px] text-blue-700">[{source.id}] {source.title}{source.publisher ? ` · ${source.publisher}` : ''}</p>)}</div></CardContent></Card>}
          <Card className="border-violet-200 bg-gradient-to-br from-violet-50 to-blue-50 shadow-none"><CardContent className="flex items-center justify-between gap-3 pt-4"><div className="min-w-0"><p className="flex items-center gap-1.5 text-xs font-bold text-violet-800"><Sparkles className="size-4" />动态设计</p><p className="mt-1 truncate text-sm font-extrabold">{motionPlanLabel(outline.motionPlan)}</p><p className="mt-1 text-[11px] text-[var(--muted-clr)]">整套保持统一，自动避开当前设备最近 5 套组合</p></div><div className="flex shrink-0 flex-col gap-2"><Select value={motionMode} onValueChange={value => void refreshMotion(value as MotionMode)}><SelectTrigger className="w-28"><SelectValue /></SelectTrigger><SelectContent>{motionModeOptions.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select><Button size="sm" variant="outline" disabled={busy} onClick={() => void refreshMotion()}><RefreshCw />换一套动效</Button></div></CardContent></Card>
          {outline.slides.map((slide, index) => <SlideEditor key={slide.id} slide={slide} index={index} count={outline.slides.length} onChange={updated => setOutline({ ...outline, slides: outline.slides.map((item, i) => i === index ? updated : item) })} onMove={direction => { const next = [...outline.slides]; const target = index + direction; [next[index], next[target]] = [next[target], next[index]]; setOutline({ ...outline, slides: next }); }} onDelete={() => setOutline({ ...outline, slides: outline.slides.filter((_, i) => i !== index) })} />)}
          {error && <p className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          {result && <Card className="border-emerald-200 bg-emerald-50"><CardContent className="pt-5 text-center"><p className="text-xs font-semibold text-emerald-700">已完成 {result.qaPages} 页逐页检查</p><p className="mt-1 text-xs text-emerald-700">分享码（7 天有效）</p><p className="my-2 font-mono text-3xl font-black tracking-[0.2em] text-emerald-900">{result.code}</p><Link className="text-sm font-bold text-[var(--brand-600)] underline" href={result.viewerUrl}>打开电脑放映页</Link></CardContent></Card>}
          <Button className="sticky bottom-4 w-full py-6 shadow-xl mp-brand-gradient" disabled={busy} onClick={() => void build()}>{busy ? '正在生成并逐页检查…' : '生成 HTML PPT'}</Button>
        </div>
      )}
    </main>
  );
}
