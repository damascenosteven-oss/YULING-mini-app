import { calculateFinancialSummary, normalizeDeckOutline, type DeckOutline, type Slide } from './schema';
import { ensureMotionPlan } from './motion';

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, character => {
    const entities: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return entities[character];
  });
}

export function safeJson(value: unknown): string {
  return JSON.stringify(value)
    .replaceAll('&', '\\u0026')
    .replaceAll('<', '\\u003c')
    .replaceAll('>', '\\u003e')
    .replaceAll('\u2028', '\\u2028')
    .replaceAll('\u2029', '\\u2029');
}

const list = (items: string[], className = 'ai-list') =>
  `<ul class="${className}">${items.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;

const iconPaths = [
  '<path d="M12 2l2.3 5.7L20 10l-5.7 2.3L12 18l-2.3-5.7L4 10l5.7-2.3L12 2Z"/><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/>',
  '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M22 12h-3M12 22v-3M2 12h3"/>',
  '<path d="M12 3 4 7v5c0 5 3.4 8 8 9 4.6-1 8-4 8-9V7l-8-4Z"/><path d="m9 12 2 2 4-5"/>',
  '<path d="m13 2-9 12h7l-1 8 9-12h-7l1-8Z"/>',
];

function safeIcon(index: number): string {
  return `<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${iconPaths[index % iconPaths.length]}</svg>`;
}

function highlightedTitle(title: string, emphasis?: string): string {
  if (!emphasis) return escapeHtml(title);
  const position = title.indexOf(emphasis);
  if (position < 0) return escapeHtml(title);
  return `${escapeHtml(title.slice(0, position))}<span class="grad-text">${escapeHtml(emphasis)}</span>${escapeHtml(title.slice(position + emphasis.length))}`;
}

function takeaway(slide: Slide): string {
  return slide.takeaway ? `<div class="callout ai-takeaway"><b>关键结论</b>：${escapeHtml(slide.takeaway)}</div>` : '';
}

function contentFrame(slide: Slide, index: number, body: string, className = '', includeTakeaway = true): string {
  const story = 'story' in slide ? slide.story : undefined;
  const eyebrow = story ? slide.title : slide.eyebrow || `AI PPT · ${String(index + 1).padStart(2, '0')}`;
  const visibleTitle = story?.claim || slide.title;
  return `<section class="slide ai-generated-slide ai-content${className ? ` ${className}` : ''}" data-section="${escapeHtml(slide.title)}" data-theme="${slide.theme}" data-variant="${slide.variant}" data-aigc="true"${className.includes('ai-luxury') ? ' data-luxury="true"' : ''}>
  <header class="ai-head"><div class="eyebrow" data-a="fade">${escapeHtml(eyebrow)}</div><h2>${story ? escapeHtml(visibleTitle) : highlightedTitle(visibleTitle, slide.emphasis)}</h2>${slide.subtitle ? `<p class="ai-subtitle" data-a="up">${escapeHtml(slide.subtitle)}</p>` : ''}</header>
  <div class="ai-body">${body}${includeTakeaway ? takeaway(slide) : ''}</div>
  <div class="aigc-label">AI 辅助生成，请核对</div>
</section>`;
}

type DataSlide = Extract<Slide, { type: 'kpi' | 'chart' | 'funnel' | 'matrix' | 'ranking' | 'table' | 'heatmap' | 'methodology' }>;

function chartFigure(type: string, data: unknown, className = ''): string {
  return `<figure class="chart ${className}" data-chart="${escapeHtml(type)}"><script type="application/json">${safeJson(data)}</script></figure>`;
}

function dataProvenance(slide: DataSlide): string {
  const status = slide.dataStatus === 'user-provided'
    ? '用户提供 · 未核验'
    : slide.dataStatus === 'researched'
      ? '联网调研数据 · 请核验'
      : '演示数据 · 非真实经营数据';
  const details = [slide.unit ? `单位：${slide.unit}` : '', slide.source ? `来源：${slide.source}` : '', slide.note || ''].filter(Boolean);
  return `<div class="ai-data-meta"><strong>${escapeHtml(status)}</strong>${details.map(item => `<span>${escapeHtml(item)}</span>`).join('')}</div>`;
}

function dataFrame(slide: DataSlide, index: number, body: string): string {
  return contentFrame(slide, index, `<div class="ai-data-stage">${body}</div>${dataProvenance(slide)}`, `ai-luxury ai-luxury-${slide.variant}`, false);
}

function storyCopy(slide: DataSlide, fallback: string): string {
  return slide.story?.implication || slide.takeaway || fallback;
}

function displayNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value);
}

function insightPanel(label: string, value: string, copy: string): string {
  return `<aside class="ai-insight-panel" data-a="right"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><p>${escapeHtml(copy)}</p><i></i></aside>`;
}

function kpi(slide: Extract<Slide, { type: 'kpi' }>, index: number): string {
  const cards = slide.metrics.map((metric, metricIndex) => {
    const ratio = metric.suffix === '%' && metric.value >= 0 && metric.value <= 100 ? metric.value / 100 : undefined;
    const trend = metric.delta === undefined ? '' : `<div class="ai-kpi-trend ${metric.direction}">${metric.direction === 'up' ? '↑' : metric.direction === 'down' ? '↓' : '→'} ${escapeHtml(String(Math.abs(metric.delta)))}${escapeHtml(metric.suffix || slide.unit || '')}</div>`;
    return `<article class="ai-kpi-card tone-${(metricIndex % 4) + 1}${metricIndex === 0 ? ' is-primary' : ''}" data-a="rise" style="--d:${metricIndex + 1}">${chartFigure('kpi', { value: metric.value, suffix: metric.suffix || slide.unit || '', label: metric.label, ratio }, 'ai-kpi-chart')}${trend}${metric.note ? `<p>${escapeHtml(metric.note)}</p>` : ''}</article>`;
  }).join('');
  return dataFrame(slide, index, `<div class="ai-kpi-grid count-${slide.metrics.length}">${cards}</div>`);
}

function chart(slide: Extract<Slide, { type: 'chart' }>, index: number): string {
  const data = slide.variant === 'donut'
    ? { labels: slide.labels, values: slide.values, center: slide.center }
    : slide.variant === 'scatter'
      ? { xAxis: slide.xAxis, yAxis: slide.yAxis, points: slide.points, referenceLines: slide.referenceLines, quadrants: slide.quadrants }
      : slide.variant === 'radar'
        ? { axes: slide.axes, maxValue: slide.maxValue, series: slide.series }
        : { labels: slide.labels, series: slide.series, mode: slide.variant === 'stacked-bar' ? slide.mode : undefined };
  if (slide.variant === 'donut') {
    const total = slide.values.reduce((sum, value) => sum + value, 0);
    const largestIndex = slide.values.indexOf(Math.max(...slide.values));
    const largestShare = total ? Math.round(slide.values[largestIndex] / total * 100) : 0;
    const legend = slide.labels.map((label, itemIndex) => `<div class="ai-share-item" data-tone="${(itemIndex % 8) + 1}"><i></i><span>${escapeHtml(label)}</span><b>${total ? Math.round(slide.values[itemIndex] / total * 100) : 0}%</b></div>`).join('');
    const copy = storyCopy(slide, `${slide.labels[largestIndex]}是当前最大构成，需要持续关注贡献变化。`);
    return dataFrame(slide, index, `<div class="ai-donut-layout"><div class="ai-chart-glass">${chartFigure('donut', data, 'ai-primary-chart')}</div><aside class="ai-share-panel" data-a="right"><span>构成洞察</span><strong>${escapeHtml(slide.labels[largestIndex])} · ${largestShare}%</strong><div>${legend}</div><p>${escapeHtml(copy)}</p></aside></div>`);
  }
  if (slide.variant === 'scatter') {
    const focus = slide.story?.focusKeys[0] || slide.points[0].label;
    return dataFrame(slide, index, `<div class="ai-chart-layout"><div class="ai-chart-glass">${chartFigure('scatter', data, 'ai-primary-chart')}</div>${insightPanel('重点对象', focus, storyCopy(slide, '结合基准线识别高潜对象与偏离项。'))}</div>`);
  }
  if (slide.variant === 'radar') {
    return dataFrame(slide, index, `<div class="ai-chart-layout"><div class="ai-chart-glass">${chartFigure('radar', data, 'ai-primary-chart')}</div>${insightPanel('能力画像', slide.series[0].name, storyCopy(slide, '聚焦优势维度，同时补齐最明显短板。'))}</div>`);
  }
  if (slide.variant === 'stacked-bar') {
    return dataFrame(slide, index, `<div class="ai-chart-layout"><div class="ai-chart-glass">${chartFigure('stacked-bar', data, 'ai-primary-chart')}</div>${insightPanel('结构变化', slide.mode === 'percent' ? '100% 构成' : `${slide.labels.length} 个类目`, storyCopy(slide, '比较各类目的组成差异与重点变化。'))}</div>`);
  }
  const latestSeries = slide.series[slide.series.length - 1];
  const allPoints = latestSeries.values.map((value, pointIndex) => ({ value, label: slide.labels[pointIndex] }));
  const peak = allPoints.reduce((best, point) => point.value > best.value ? point : best, allPoints[0]);
  const first = latestSeries.values[0];
  const last = latestSeries.values[latestSeries.values.length - 1];
  const insightValue = slide.variant === 'line'
    ? `${last >= first ? '+' : ''}${displayNumber(last - first)}${slide.unit || ''}`
    : `${displayNumber(peak.value)}${slide.unit || ''}`;
  const insightLabel = slide.variant === 'line' ? '区间变化' : '峰值品类';
  const fallback = slide.variant === 'line'
    ? `${slide.labels[0]}至${slide.labels[slide.labels.length - 1]}整体${last >= first ? '上升' : '下降'}。`
    : `${peak.label}在当前对比中表现最高。`;
  return dataFrame(slide, index, `<div class="ai-chart-layout"><div class="ai-chart-glass">${chartFigure(slide.variant, data, 'ai-primary-chart')}</div>${insightPanel(insightLabel, slide.variant === 'bar' ? `${peak.label} · ${insightValue}` : insightValue, storyCopy(slide, fallback))}</div>`);
}

function funnel(slide: Extract<Slide, { type: 'funnel' }>, index: number): string {
  const first = slide.stages[0].value || 1;
  const final = slide.stages[slide.stages.length - 1];
  const conversion = Math.round(final.value / first * 1000) / 10;
  return dataFrame(slide, index, `<div class="ai-funnel-layout"><div class="ai-chart-glass">${chartFigure('funnel', { stages: slide.stages, unit: slide.unit }, 'ai-primary-chart')}</div>${insightPanel('全链路转化', `${conversion}%`, slide.takeaway || `${first.toLocaleString('zh-CN')} 个触达最终形成 ${final.value.toLocaleString('zh-CN')} 个${final.label}。`)}</div>`);
}

function matrix(slide: Extract<Slide, { type: 'matrix' }>, index: number): string {
  const priority = slide.points.reduce((best, point) => point.x + point.y > best.x + best.y ? point : best, slide.points[0]);
  return dataFrame(slide, index, `<div class="ai-matrix-layout"><div class="ai-chart-glass">${chartFigure('matrix', { axes: slide.axes, quadrants: slide.quadrants, points: slide.points }, 'ai-primary-chart')}</div>${insightPanel('优先机会', priority.label, slide.takeaway || '优先验证高价值、易实施的右上象限场景。')}</div>`);
}

function ranking(slide: Extract<Slide, { type: 'ranking' }>, index: number): string {
  if (slide.variant === 'grouped') {
    const groups = slide.groups.map((group, groupIndex) => `<article class="ai-ranking-group" data-a="rise" style="--d:${groupIndex + 1}"><h3>${escapeHtml(group.title)}</h3>${group.entries.slice().sort((a, b) => b.value - a.value).map((entry, entryIndex) => `<div><b>${entryIndex + 1}</b><span>${escapeHtml(entry.label)}</span><i style="--w:${Math.max(8, Math.min(100, Math.abs(entry.value)))}%"></i><strong>${displayNumber(entry.value)}${escapeHtml(slide.unit || '')}</strong></div>`).join('')}</article>`).join('');
    return dataFrame(slide, index, `<div class="ai-ranking-groups">${groups}</div>`);
  }
  // Descriptive units already appear in provenance; repeating them squeezes labels.
  const inlineUnit = (slide.unit?.length ?? 0) <= 2 ? slide.unit : '';
  const sorted = [...slide.entries].sort((left, right) => right.value - left.value);
  const podium = sorted.slice(0, 3).map((entry, entryIndex) => `<article class="ai-podium-card rank-${entryIndex + 1}" data-a="rise" style="--d:${entryIndex + 1}"><span>TOP ${entryIndex + 1}</span><strong>${escapeHtml(entry.label)}</strong><b>${displayNumber(entry.value)}${escapeHtml(inlineUnit || '')}</b>${entry.change === undefined ? '' : `<small class="${entry.change < 0 ? 'down' : 'up'}">${entry.change >= 0 ? '↑' : '↓'} ${displayNumber(Math.abs(entry.change))}</small>`}</article>`).join('');
  return dataFrame(slide, index, `<div class="ai-ranking-layout"><div class="ai-podium">${podium}</div><div class="ai-chart-glass">${chartFigure('ranking', { entries: slide.entries, unit: inlineUnit }, 'ai-primary-chart')}</div></div>`);
}

function dataTable(slide: Extract<Slide, { type: 'table'; variant: 'data-table' }>, index: number): string {
  const table = `<div class="ai-table-layout"><aside class="ai-table-summary" data-a="left"><span>数据范围</span><strong>${slide.rows.length} × ${slide.headers.length}</strong><p>${escapeHtml(slide.takeaway || '横向比较关键指标，定位值得复制与优先改善的对象。')}</p></aside><div class="ai-table-wrap ai-table-luxury"><table class="tbl"><thead><tr>${slide.headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${slide.rows.map((row, rowIndex) => `<tr data-tone="${(rowIndex % 8) + 1}"><th><i></i>${escapeHtml(row.label)}</th>${row.values.map((value, valueIndex) => `<td${valueIndex === row.values.length - 1 ? ' class="is-key"' : ''}>${escapeHtml(String(value))}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
  return dataFrame(slide, index, table);
}

function highlightTable(slide: Extract<Slide, { type: 'table'; variant: 'highlight-table' }>, index: number): string {
  const tones = new Map(slide.highlights.map(item => [`${item.row}:${item.column}`, item.tone]));
  const rows = slide.rows.map((row, rowIndex) => `<tr${slide.totalRow === rowIndex ? ' class="ai-total"' : ''}><th>${escapeHtml(row.label)}</th>${row.values.map((value, columnIndex) => `<td data-cell-tone="${tones.get(`${rowIndex}:${columnIndex}`) || 'none'}">${escapeHtml(String(value))}</td>`).join('')}</tr>`).join('');
  return dataFrame(slide, index, `<div class="ai-table-layout"><aside class="ai-table-summary"><span>核心判断</span><strong>${escapeHtml(slide.story?.focusKeys[0] || '重点单元格')}</strong><p>${escapeHtml(storyCopy(slide, '比较关键指标，识别领先项与风险项。'))}</p></aside><div class="ai-table-wrap ai-table-luxury"><table class="tbl"><thead><tr>${slide.headers.map(header => `<th>${escapeHtml(header)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></div>`);
}

function financialTable(slide: Extract<Slide, { type: 'table'; variant: 'financial-return' }>, index: number): string {
  const summary = calculateFinancialSummary(slide);
  const currency = slide.unit || (slide.currency === 'CNY' ? '元' : '美元');
  const cards = [
    ['净收益', summary.netBenefit, currency],
    ['回收期', summary.paybackMonths, '个月'],
  ].map(([label, value, suffix], cardIndex) => `<article class="ai-finance-kpi" data-a="rise" style="--d:${cardIndex + 2}"><span>${escapeHtml(String(label))}</span><strong>${escapeHtml(String(value))}<small>${escapeHtml(String(suffix))}</small></strong></article>`).join('');
  const rows = slide.items.map(item => `<tr><th>${escapeHtml(item.label)}</th><td>${item.baseline}</td><td>${item.proposed}</td><td>${Math.round((item.baseline - item.proposed) * 100) / 100}</td></tr>`).join('');
  const body = `<div class="ai-finance-layout"><div class="ai-finance-hero" data-a="left"><span>预计 ROI</span><strong>${summary.roiPercent}<small>%</small></strong><p>${escapeHtml(slide.takeaway || `预计 ${summary.paybackMonths} 个月收回一次性投入。`)}</p><div class="ai-finance-grid">${cards}</div></div><div class="ai-table-wrap ai-table-luxury"><table class="tbl"><thead><tr><th>项目</th><th>基准</th><th>方案后</th><th>年度节省</th></tr></thead><tbody>${rows}<tr class="ai-total"><th>合计</th><td>${summary.baseline}</td><td>${summary.proposed}</td><td>${Math.round((summary.baseline - summary.proposed) * 100) / 100}</td></tr></tbody></table></div></div>`;
  return dataFrame(slide, index, body);
}

function table(slide: Extract<Slide, { type: 'table' }>, index: number): string {
  if (slide.variant === 'data-table') return dataTable(slide, index);
  if (slide.variant === 'highlight-table') return highlightTable(slide, index);
  return financialTable(slide, index);
}

function heatmap(slide: Extract<Slide, { type: 'heatmap' }>, index: number): string {
  return dataFrame(slide, index, `<div class="ai-chart-layout"><div class="ai-chart-glass">${chartFigure('heatmap', { columns: slide.columns, rows: slide.rows, colorScale: slide.colorScale, midpoint: slide.midpoint }, 'ai-primary-chart')}</div>${insightPanel('交叉洞察', slide.story?.focusKeys[0] || '高值区域', storyCopy(slide, '通过色阶定位集中优势、空白与异常区域。'))}</div>`);
}

function methodology(slide: Extract<Slide, { type: 'methodology' }>, index: number): string {
  const components = slide.components.map((component, componentIndex) => `<article data-a="rise" style="--d:${componentIndex + 1}"><i>${component.weight}%</i><div><h3>${escapeHtml(component.label)}</h3><p>${escapeHtml(component.description)}</p></div></article>`).join('');
  return dataFrame(slide, index, `<div class="ai-method-layout"><div class="ai-method-formula"><span>评分模型</span><strong>${escapeHtml(slide.formula)}</strong><p>${escapeHtml(storyCopy(slide, '统一口径后再比较不同对象。'))}</p></div><div class="ai-method-components">${components}</div></div>`);
}

function cover(slide: Extract<Slide, { type: 'cover' }>): string {
  if (slide.variant === 'split-hero') {
    return `<section class="slide chapter cover ai-generated-slide ai-cover-split" data-section="${escapeHtml(slide.title)}" data-theme="${slide.theme}" data-variant="${slide.variant}" data-aigc="true" data-luxury="true"><div class="split"><div class="stack"><div class="eyebrow" data-a="fade">${escapeHtml(slide.eyebrow || '毓灵 YuLing AI · PRESENTATION')}</div><h1 data-split>${highlightedTitle(slide.title, slide.emphasis)}</h1><p class="lead" data-a="up" style="--d:7">${escapeHtml(slide.tagline)}</p></div><div class="ai-hero-orbit" data-a="rise" style="--d:4"><i></i><i></i><i></i><strong>AI</strong></div></div><div class="aigc-label">AI 辅助生成，请核对</div></section>`;
  }
  return `<section class="slide chapter cover ai-generated-slide ai-cover" data-section="${escapeHtml(slide.title)}" data-theme="${slide.theme}" data-variant="${slide.variant}" data-aigc="true" data-luxury="true"><div class="eyebrow" data-a="fade">${escapeHtml(slide.eyebrow || '毓灵 YuLing AI · PRESENTATION')}</div><h1 data-split>${highlightedTitle(slide.title, slide.emphasis)}</h1><p class="lead" data-a="up" style="--d:8">${escapeHtml(slide.tagline)}</p><div class="meta" data-a="up" style="--d:10"><span>结构化表达</span><span>16:9 放映</span><span>AI 辅助生成</span></div><div class="orb"><i></i><i></i><i></i><em></em></div><div class="aigc-label">AI 辅助生成，请核对</div></section>`;
}

function bullets(slide: Extract<Slide, { type: 'bullets' }>, index: number): string {
  if (slide.variant === 'three-cards') {
    const groupSize = Math.ceil(slide.items.length / 3);
    const groups = [0, 1, 2].map(groupIndex => slide.items.slice(groupIndex * groupSize, (groupIndex + 1) * groupSize));
    const cards = groups.filter(group => group.length).map((group, groupIndex) => `<article class="glass bar shine" data-a="rise" style="--d:${groupIndex + 2}"><div class="icon">${safeIcon(groupIndex)}</div><h3>${escapeHtml(group[0])}</h3>${group.length > 1 ? list(group.slice(1), 'ai-card-list') : '<p>聚焦这一关键动作，形成可复用结果。</p>'}</article>`).join('');
    return contentFrame(slide, index, `<div class="grid3 ai-three-cards">${cards}</div>`);
  }
  if (slide.variant === 'spotlight') {
    const [first, ...rest] = slide.items;
    return contentFrame(slide, index, `<div class="split even ai-spotlight"><div class="ai-spotlight-main" data-a="rise"><span>核心观点</span><strong>${escapeHtml(first)}</strong></div><div class="stack">${rest.map((item, itemIndex) => `<div class="ai-mini-point" data-a="up" style="--d:${itemIndex + 2}"><i>${String(itemIndex + 1).padStart(2, '0')}</i><p>${escapeHtml(item)}</p></div>`).join('')}</div></div>`);
  }
  return contentFrame(slide, index, `<div class="ai-feature-list">${slide.items.map((item, itemIndex) => `<article data-a="up" style="--d:${itemIndex + 2}"><div class="icon">${safeIcon(itemIndex)}</div><span>${String(itemIndex + 1).padStart(2, '0')}</span><p>${escapeHtml(item)}</p></article>`).join('')}</div>`);
}

function comparison(slide: Extract<Slide, { type: 'comparison' }>, index: number): string {
  if (slide.variant === 'two-column') return contentFrame(slide, index, `<div class="grid2 ai-columns"><article class="glass" data-a="left"><span class="ai-side-label">A</span><h3>${escapeHtml(slide.left.title)}</h3>${list(slide.left.items)}</article><article class="glass" data-a="right"><span class="ai-side-label">B</span><h3>${escapeHtml(slide.right.title)}</h3>${list(slide.right.items)}</article></div>`);
  return contentFrame(slide, index, `<div class="vs ai-versus"><div class="bad-side" data-a="left"><b>${escapeHtml(slide.left.title)}</b>${list(slide.left.items)}</div><div class="good-side" data-a="right"><b>${escapeHtml(slide.right.title)}</b>${list(slide.right.items)}</div></div>`);
}

function process(slide: Extract<Slide, { type: 'process' }>, index: number): string {
  if (slide.variant === 'ladder' && slide.steps.length <= 4) return contentFrame(slide, index, `<div class="ladder ai-ladder">${slide.steps.map((step, stepIndex) => `<div class="step" data-a="rise" style="--d:${stepIndex + 1};height:${46 + stepIndex * 15}%"><em>${String(stepIndex + 1).padStart(2, '0')}</em><b>${escapeHtml(step.title)}</b><span>${escapeHtml(step.description)}</span></div>`).join('')}</div>`);
  if (slide.variant === 'roadmap' || slide.steps.length > 4) return contentFrame(slide, index, `<div class="ai-roadmap">${slide.steps.map((step, stepIndex) => `<article data-a="up" style="--d:${stepIndex + 1}"><i>${stepIndex + 1}</i><div><h3>${escapeHtml(step.title)}</h3><p>${escapeHtml(step.description)}</p></div></article>`).join('')}</div>`);
  return contentFrame(slide, index, `<div class="flow ai-flow">${slide.steps.map((step, stepIndex) => `${stepIndex ? '<i class="arrow"></i>' : ''}<div class="node${stepIndex === slide.steps.length - 1 ? ' hot' : ''}" data-a="up" style="--d:${stepIndex + 1}">${escapeHtml(step.title)}<small>${escapeHtml(step.description)}</small></div>`).join('')}</div>`);
}

function treeNodeSize(text: string, depth: 0 | 1 | 2): string {
  const visualLength = Array.from(text).reduce((total, character) =>
    total + (/^[\u0000-\u00ff]$/.test(character) ? 0.55 : 1), 0);
  const baseWidth = depth === 0 ? 4.2 : 3.2;
  const threshold = depth === 0 ? 9 : 6;
  const maxWidth = depth === 0 ? 6.2 : 4.6;
  const width = Math.min(maxWidth, baseWidth + Math.max(0, visualLength - threshold) * 0.22);
  const height = visualLength > (depth === 0 ? 20 : 14) ? 1.45 : 1.2;
  return `${width.toFixed(2)} ${height.toFixed(2)}`;
}

function tree(slide: Extract<Slide, { type: 'tree' }>, index: number): string {
  if (slide.variant === 'layer-stack') return contentFrame(slide, index, `<div class="ai-layer-root">${escapeHtml(slide.root)}</div><div class="layers ai-layers">${slide.branches.map((branch, branchIndex) => `<div class="layer" data-a="up" style="--d:${branchIndex + 1};--c1:var(--cat-${(branchIndex % 4) + 1});--c2:var(--cat-${((branchIndex + 5) % 8) + 1})"><b>${escapeHtml(branch.title)}</b><span>${escapeHtml(branch.items.join(' · '))}</span></div>`).join('')}</div>`);
  const nodes = [`<div class="node" data-depth="0" data-id="root" data-shape="pill" data-size="${treeNodeSize(slide.root, 0)}" data-tone="1"><b>${escapeHtml(slide.root)}</b></div>`];
  slide.branches.forEach((branch, branchIndex) => {
    const branchId = `branch-${branchIndex}`;
    nodes.push(`<div class="node" data-depth="1" data-id="${branchId}" data-parent="root" data-size="${treeNodeSize(branch.title, 1)}" data-tone="${(branchIndex % 5) + 1}" data-step="${branchIndex + 1}"><b>${escapeHtml(branch.title)}</b></div>`);
    branch.items.forEach((item, itemIndex) => nodes.push(`<div class="node" data-depth="2" data-id="${branchId}-${itemIndex}" data-parent="${branchId}" data-size="${treeNodeSize(item, 2)}" data-tone="${(branchIndex % 5) + 1}" data-step="${branchIndex + 1}"><b>${escapeHtml(item)}</b></div>`));
  });
  return contentFrame(slide, index, `<div class="dg ai-tree" data-grid="26 12" data-tree="mind" data-node="3.2 1.1" data-gap="1.2 0.4">${nodes.join('')}</div>`);
}

function venn(slide: Extract<Slide, { type: 'venn' }>, index: number): string {
  return contentFrame(slide, index, `<div class="venn ai-venn" data-sets="2"><div class="set"><b>${escapeHtml(slide.leftTitle)}</b></div><div class="set"><b>${escapeHtml(slide.rightTitle)}</b></div><div class="region" data-region="a">${escapeHtml(slide.left.join(' · '))}</div><div class="region" data-region="ab" data-step="1">${escapeHtml(slide.overlap.join(' · '))}</div><div class="region" data-region="b">${escapeHtml(slide.right.join(' · '))}</div></div>`);
}

function closing(slide: Extract<Slide, { type: 'closing' }>, index: number): string {
  const body = slide.variant === 'quote'
    ? `<blockquote class="quote ai-quote" data-a="blur">“${escapeHtml(slide.summary)}”</blockquote><div class="meta ai-action-chips">${slide.actions.map(action => `<span>${escapeHtml(action)}</span>`).join('')}</div>`
    : `<div class="split even ai-action-card"><div class="ai-action-summary" data-a="rise"><span>下一步</span><strong>${escapeHtml(slide.summary)}</strong></div><div class="stack">${slide.actions.map((action, actionIndex) => `<div class="callout" data-a="up" style="--d:${actionIndex + 2}"><b>${String(actionIndex + 1).padStart(2, '0')}</b> ${escapeHtml(action)}</div>`).join('')}</div></div>`;
  return `<section class="slide chapter ai-generated-slide ai-cinematic-close" data-section="${escapeHtml(slide.title)}" data-theme="${slide.theme}" data-variant="${slide.variant}" data-aigc="true" data-luxury="true"><header class="ai-head"><div class="eyebrow" data-a="fade">AI PPT · ${String(index + 1).padStart(2, '0')}</div><h2>${highlightedTitle(slide.title, slide.emphasis)}</h2></header><div class="ai-body">${body}</div><div class="aigc-label">AI 辅助生成，请核对</div></section>`;
}

function renderSlide(slide: Slide, index: number): string {
  switch (slide.type) {
    case 'cover': return cover(slide);
    case 'bullets': return bullets(slide, index);
    case 'comparison': return comparison(slide, index);
    case 'process': return process(slide, index);
    case 'tree': return tree(slide, index);
    case 'venn': return venn(slide, index);
    case 'closing': return closing(slide, index);
    case 'kpi': return kpi(slide, index);
    case 'chart': return chart(slide, index);
    case 'funnel': return funnel(slide, index);
    case 'matrix': return matrix(slide, index);
    case 'ranking': return ranking(slide, index);
    case 'table': return table(slide, index);
    case 'heatmap': return heatmap(slide, index);
    case 'methodology': return methodology(slide, index);
  }
}

function slideSourceFooter(outline: DeckOutline, slide: Slide): string {
  if (outline.research.status !== 'completed' || !slide.sourceIds?.length) return '';
  const byId = new Map(outline.research.sources.map(source => [source.id, source]));
  const labels = slide.sourceIds.flatMap(id => {
    const source = byId.get(id);
    return source ? [`[${source.id}] ${source.publisher || source.title}${source.publishedAt ? ` · ${source.publishedAt}` : ''}`] : [];
  });
  return labels.length ? `<div class="ai-source-footer">来源：${labels.map(escapeHtml).join('　')}</div>` : '';
}

function sourceAppendix(outline: DeckOutline): string {
  if (outline.research.status !== 'completed') return '';
  const rows = outline.research.sources.map(source => `<span data-source-id="${escapeHtml(source.id)}" data-source-url="${escapeHtml(source.url)}"><b>[${escapeHtml(source.id)}]</b> ${escapeHtml(source.title)}${source.publisher ? ` · ${escapeHtml(source.publisher)}` : ''}</span>`).join('');
  return `<aside class="ai-source-appendix"><strong>资料来源 · 检索于 ${escapeHtml(outline.research.retrievedAt.slice(0, 10))}</strong><div>${rows}</div></aside>`;
}

export function renderDeck(input: DeckOutline): { slides: string[]; css: string } {
  const outline = ensureMotionPlan(normalizeDeckOutline(input));
  const lastIndex = outline.slides.length - 1;
  const slides = outline.slides.map((slide, index) => {
    const additions = `${slideSourceFooter(outline, slide)}${index === lastIndex ? sourceAppendix(outline) : ''}`;
    const motion = outline.motionPlan?.slides[index];
    const rendered = additions ? renderSlide(slide, index).replace('</section>', `${additions}</section>`) : renderSlide(slide, index);
    if (!motion) return rendered;
    const withMotion = rendered.replace(
      /<section class="([^"]*\bslide\b[^"]*)"/,
      `<section class="$1" data-motion-effect="${motion.effect}" data-motion-entrance="${motion.entrance}" style="--motion-stagger:${motion.stagger}ms"`,
    );
    return withMotion.replace(/data-a="(?:fade|up|rise|blur|zoom|flip|pop|stamp)"/g, `data-a="${motion.entrance}"`);
  });
  const css = `
.slide.ai-generated-slide{position:absolute}.slide.ai-content{justify-content:flex-start;padding:58px 112px 132px}.ai-head{flex:none}.ai-head .eyebrow{font-size:20px;margin-bottom:12px}.ai-head h2{font-size:54px;line-height:1.12;margin:0;max-width:1500px}.ai-subtitle{font-size:24px;color:var(--ink-2);margin:12px 0 0;line-height:1.45;max-width:1320px}.ai-body{display:flex;flex:1;min-height:0;flex-direction:column;justify-content:center;padding-top:28px}.aigc-label{position:absolute;right:48px;bottom:116px;z-index:19;font-size:13px;letter-spacing:.08em;color:rgba(60,68,90,.58)}.chapter .aigc-label{color:rgba(220,225,240,.55)}
.slide.ai-content .grad-text{background:none;color:var(--theme-solid);-webkit-text-fill-color:var(--theme-solid);animation:none}
.ai-cover h1,.ai-cover-split h1{font-size:86px;max-width:1300px}.ai-cover .lead,.ai-cover-split .lead{font-size:29px}.ai-cover .meta span{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.12);padding:10px 18px;border-radius:999px}.ai-cover-split .split{width:100%;grid-template-columns:1.1fr .9fr}.ai-hero-orbit{width:460px;height:460px;position:relative;margin:auto;display:grid;place-items:center}.ai-hero-orbit i{position:absolute;border:2px solid rgba(255,255,255,.18);border-radius:50%;inset:0}.ai-hero-orbit i:nth-child(2){inset:54px;border-color:var(--theme-solid)}.ai-hero-orbit i:nth-child(3){inset:110px;border-style:dashed}.ai-hero-orbit strong{font-size:118px;background:var(--theme);-webkit-background-clip:text;background-clip:text;color:transparent}
.ai-list{display:grid;gap:14px;margin:0;padding-left:26px;font-size:23px;line-height:1.42}.ai-list li::marker{color:var(--theme-solid)}.ai-feature-list{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}.ai-feature-list article{display:grid;grid-template-columns:58px 42px 1fr;align-items:center;gap:16px;padding:20px 24px;border-radius:22px;background:var(--panel-bg);box-shadow:var(--shadow);border:1px solid var(--line)}.ai-feature-list .icon{width:52px;height:52px;border-radius:16px;margin:0;padding:13px}.ai-feature-list .icon svg,.ai-three-cards .icon svg{width:100%;height:100%}.ai-feature-list article>span{font-size:17px;font-weight:800;color:var(--theme-solid)}.ai-feature-list p{font-size:23px;line-height:1.4;margin:0}.ai-three-cards{align-items:stretch}.ai-three-cards article{min-height:330px}.ai-three-cards .icon{padding:18px}.ai-card-list{padding-left:20px;font-size:20px;line-height:1.45;display:grid;gap:9px}.ai-spotlight-main,.ai-action-summary{min-height:360px;border-radius:32px;background:var(--theme);color:white;padding:42px;display:flex;flex-direction:column;justify-content:space-between;box-shadow:0 28px 70px -25px var(--theme-solid)}.ai-spotlight-main span,.ai-action-summary span{font-size:18px;font-weight:800;letter-spacing:.12em}.ai-spotlight-main strong,.ai-action-summary strong{font-size:42px;line-height:1.28}.ai-mini-point{display:grid;grid-template-columns:48px 1fr;gap:15px;align-items:start;padding:17px 20px;border-bottom:1px solid var(--line)}.ai-mini-point i{font-style:normal;color:var(--theme-solid);font-weight:800}.ai-mini-point p{font-size:22px;line-height:1.42;margin:0}
.ai-columns{align-items:stretch}.ai-columns article{padding:32px;position:relative}.ai-columns h3{font-size:31px;margin:0 0 22px}.ai-side-label{position:absolute;right:28px;top:24px;font-size:52px;font-weight:900;color:var(--accent-soft)}.ai-versus{align-items:stretch}.ai-versus>div{min-height:330px}.ai-versus b{font-size:28px}.ai-versus .ai-list{font-size:22px}
.ai-flow{align-items:stretch;justify-content:center}.ai-flow .node{min-width:0;flex:1;padding:24px 18px;font-size:25px;display:flex;flex-direction:column;justify-content:center}.ai-flow .node small{font-size:17px;line-height:1.4}.ai-flow .arrow{flex:0 0 34px}.ai-ladder{height:410px}.ai-ladder .step{min-height:190px}.ai-roadmap{display:grid;grid-template-columns:repeat(2,1fr);gap:16px 28px}.ai-roadmap article{display:grid;grid-template-columns:62px 1fr;gap:18px;align-items:center;padding:18px 22px;border-radius:22px;background:var(--panel-bg);border:1px solid var(--line);box-shadow:var(--shadow)}.ai-roadmap i{display:grid;place-items:center;width:52px;height:52px;border-radius:50%;font-style:normal;font-weight:800;background:var(--theme);color:white}.ai-roadmap h3{font-size:25px;margin:0 0 5px}.ai-roadmap p{font-size:17px;line-height:1.4;color:var(--ink-2);margin:0}
.ai-tree{height:500px}.ai-tree .node .text{box-sizing:border-box;width:100%;min-width:0;max-width:100%;padding:0 12px}.ai-tree .node b{white-space:normal;overflow-wrap:anywhere;line-height:1.18}.ai-layers{max-width:1450px;margin:16px auto 0;width:100%}.ai-layers .layer{padding:18px 30px}.ai-layers .layer b{font-size:27px}.ai-layers .layer span{font-size:21px}.ai-layer-root{align-self:center;padding:9px 22px;border-radius:999px;background:var(--accent-soft);font-size:19px;font-weight:800;color:var(--theme-solid)}.ai-venn{height:500px;flex:none}.ai-venn .region{max-width:240px;line-height:1.4}
.ai-quote{font-size:54px;max-width:1400px}.ai-action-chips{margin-top:36px;display:flex;gap:16px;flex-wrap:wrap}.ai-action-chips span{padding:12px 20px;border-radius:999px;background:var(--surface);box-shadow:var(--shadow);font-size:19px;color:var(--ink)}.ai-action-card .stack{gap:14px}.ai-action-card .callout{padding:18px 24px;font-size:21px}.ai-takeaway{margin-top:20px;padding:14px 22px;font-size:18px;box-shadow:none}
.ai-data-stage{flex:1;min-height:0;display:flex;flex-direction:column}.ai-data-meta{display:flex;align-items:center;gap:14px;min-height:30px;margin-top:12px;font-size:14px;color:var(--ink-2)}.ai-data-meta strong{color:var(--theme-solid);background:var(--accent-soft);padding:6px 11px;border-radius:999px}.ai-data-meta span{padding-left:14px;border-left:1px solid var(--line)}.ai-primary-chart{width:100%;min-height:390px;border-radius:28px;background:var(--panel-bg);border:1px solid var(--line);box-shadow:var(--shadow);padding:22px}.ai-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;flex:1;align-items:stretch}.ai-kpi-grid.count-2{grid-template-columns:repeat(2,1fr)}.ai-kpi-grid.count-3{grid-template-columns:repeat(3,1fr)}.ai-kpi-grid.count-4 .kpi-value{font-size:82px}.ai-kpi-card{position:relative;min-height:350px;border-radius:28px;background:var(--panel-bg);border:1px solid var(--line);box-shadow:var(--shadow);padding:18px;display:flex;flex-direction:column}.ai-kpi-chart{min-height:250px}.ai-kpi-trend{position:absolute;top:20px;right:20px;padding:6px 10px;border-radius:999px;background:var(--accent-soft);font-size:15px;font-weight:800;color:var(--theme-solid)}.ai-kpi-trend.down{color:#0f8b6d}.ai-kpi-card p{margin:0;text-align:center;color:var(--ink-2);font-size:16px}.ai-table-wrap{overflow:hidden;border-radius:24px;border:1px solid var(--line);box-shadow:var(--shadow);background:var(--panel-bg)}.ai-table-wrap .tbl{width:100%;font-size:20px}.ai-table-wrap .tbl th,.ai-table-wrap .tbl td{padding:15px 20px}.ai-table-wrap .tbl thead th{background:var(--accent-soft);color:var(--theme-solid)}.ai-table-wrap .tbl tbody th{text-align:left}.ai-finance-layout{display:grid;grid-template-columns:.85fr 1.15fr;gap:24px;align-items:stretch}.ai-finance-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.ai-finance-kpi{border-radius:24px;background:var(--panel-bg);border:1px solid var(--line);box-shadow:var(--shadow);padding:24px;display:flex;flex-direction:column;justify-content:space-between}.ai-finance-kpi span{font-size:18px;color:var(--ink-2);font-weight:700}.ai-finance-kpi strong{font-size:42px;color:var(--ink);line-height:1}.ai-finance-kpi small{font-size:17px;margin-left:5px;color:var(--theme-solid)}.ai-total{font-weight:800;background:var(--accent-soft)}
.ai-luxury::before{content:"";position:absolute;inset:0 0 104px;pointer-events:none;background:radial-gradient(circle at 12% 16%,color-mix(in srgb,var(--cat-6) 14%,transparent),transparent 28%),radial-gradient(circle at 84% 24%,color-mix(in srgb,var(--cat-2) 14%,transparent),transparent 30%),radial-gradient(circle at 70% 88%,color-mix(in srgb,var(--cat-7) 11%,transparent),transparent 30%)}.ai-luxury .ai-head,.ai-luxury .ai-body,.ai-luxury .aigc-label{position:relative;z-index:1}.ai-luxury .ai-head h2{letter-spacing:-.035em}.ai-luxury .ai-head h2::after{content:"";display:block;width:86px;height:7px;margin-top:18px;border-radius:99px;background:var(--theme);box-shadow:0 8px 28px color-mix(in srgb,var(--theme-solid) 34%,transparent)}
.ai-luxury [data-tone="1"]{--tone:var(--cat-1)}.ai-luxury [data-tone="2"]{--tone:var(--cat-2)}.ai-luxury [data-tone="3"]{--tone:var(--cat-3)}.ai-luxury [data-tone="4"]{--tone:var(--cat-4)}.ai-luxury [data-tone="5"]{--tone:var(--cat-5)}.ai-luxury [data-tone="6"]{--tone:var(--cat-6)}.ai-luxury [data-tone="7"]{--tone:var(--cat-7)}.ai-luxury [data-tone="8"]{--tone:var(--cat-8)}
.ai-chart-layout,.ai-donut-layout,.ai-funnel-layout,.ai-matrix-layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:24px;height:430px;min-height:0}.ai-donut-layout{grid-template-columns:minmax(0,1.3fr) minmax(320px,.7fr)}.ai-chart-glass{position:relative;min-width:0;min-height:0;border-radius:32px;background:linear-gradient(145deg,rgba(255,255,255,.92),rgba(255,255,255,.62));border:1px solid rgba(255,255,255,.9);box-shadow:0 26px 70px rgba(29,29,31,.11),inset 0 1px 0 #fff;overflow:hidden}.ai-chart-glass::before{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(120deg,color-mix(in srgb,var(--cat-6) 7%,transparent),transparent 42%,color-mix(in srgb,var(--cat-2) 7%,transparent))}.ai-chart-glass .ai-primary-chart{height:100%;min-height:0;border:0;box-shadow:none;background:transparent;border-radius:0;padding:24px;position:relative;z-index:1}
.ai-insight-panel,.ai-share-panel,.ai-table-summary{position:relative;overflow:hidden;border-radius:32px;padding:34px;color:#fff;background:linear-gradient(145deg,#171826,#282a3d);box-shadow:0 30px 72px rgba(20,22,38,.26);display:flex;flex-direction:column}.ai-insight-panel::before,.ai-share-panel::before,.ai-table-summary::before{content:"";position:absolute;width:260px;height:260px;border-radius:50%;right:-100px;top:-120px;background:var(--theme);filter:blur(22px);opacity:.65}.ai-insight-panel span,.ai-share-panel>span,.ai-table-summary span{position:relative;font-size:16px;font-weight:800;letter-spacing:.14em;color:rgba(255,255,255,.62)}.ai-insight-panel strong,.ai-share-panel>strong,.ai-table-summary strong{position:relative;font-size:38px;line-height:1.16;margin:24px 0 18px}.ai-insight-panel p,.ai-share-panel>p,.ai-table-summary p{position:relative;margin:auto 0 0;font-size:19px;line-height:1.55;color:rgba(255,255,255,.78)}.ai-insight-panel>i{position:relative;width:54px;height:7px;border-radius:99px;background:var(--theme);margin-top:24px}
.ai-share-panel{padding:28px}.ai-share-panel>strong{font-size:32px;margin:16px 0}.ai-share-panel>div{display:grid;gap:8px;position:relative}.ai-share-item{display:grid!important;grid-template-columns:12px 1fr auto;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.08)}.ai-share-item i{width:10px;height:10px;border-radius:50%;background:var(--tone)}.ai-share-item span,.ai-share-item b{font-size:16px}.ai-share-panel>p{font-size:16px;margin-top:15px}
.ai-kpi-grid.count-3{grid-template-columns:1.18fr 1fr 1fr}.ai-kpi-card{overflow:hidden;background:linear-gradient(150deg,rgba(255,255,255,.96),rgba(255,255,255,.68));border-color:rgba(255,255,255,.92);box-shadow:0 24px 60px rgba(29,29,31,.12)}.ai-kpi-card::before{content:"";position:absolute;inset:0 0 auto;height:8px;background:var(--theme)}.ai-kpi-card.tone-1::before{background:var(--cat-1)}.ai-kpi-card.tone-2::before{background:var(--cat-5)}.ai-kpi-card.tone-3::before{background:var(--cat-6)}.ai-kpi-card.tone-4::before{background:var(--cat-7)}.ai-kpi-card.is-primary{background:linear-gradient(145deg,#171826,#2c2944);color:#fff;position:relative;top:-10px}.ai-kpi-card.is-primary .kpi-value{color:#fff}.ai-kpi-card.is-primary .kpi-label,.ai-kpi-card.is-primary p{color:rgba(255,255,255,.68)}.ai-kpi-card.is-primary .ring-track{stroke:rgba(255,255,255,.12)}
.ai-ranking-layout{display:grid;grid-template-columns:350px minmax(0,1fr);gap:24px;height:430px}.ai-podium{display:grid;gap:12px}.ai-podium-card{position:relative;border-radius:22px;padding:18px 22px;background:linear-gradient(145deg,rgba(255,255,255,.95),rgba(255,255,255,.66));border:1px solid rgba(255,255,255,.9);box-shadow:var(--shadow);display:grid;grid-template-columns:72px 1fr auto;align-items:center;gap:10px}.ai-podium-card span{font-size:14px;font-weight:900;color:var(--theme-solid)}.ai-podium-card strong{font-size:21px}.ai-podium-card b{font-size:24px}.ai-podium-card small{grid-column:3;font-size:14px;text-align:right}.ai-podium-card small.up{color:#0f8b6d}.ai-podium-card small.down{color:#d92d20}.ai-podium-card.rank-1{background:linear-gradient(135deg,#171826,#342b46);color:#fff;outline:3px solid rgba(255,214,10,.2)}.ai-podium-card.rank-1 span{color:#FFD60A}
.ai-table-layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:24px;height:430px}.ai-table-luxury{background:rgba(255,255,255,.74);border-color:rgba(255,255,255,.9);box-shadow:0 24px 70px rgba(29,29,31,.12)}.ai-table-luxury .tbl tbody tr:nth-child(even){background:rgba(255,255,255,.52)}.ai-table-luxury .tbl tbody th i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:12px;background:var(--tone)}.ai-table-luxury .tbl .is-key{font-weight:900;color:var(--theme-solid)}
.ai-table-luxury td[data-cell-tone="best"]{background:rgba(18,215,179,.18);color:#08745f;font-weight:900}.ai-table-luxury td[data-cell-tone="risk"]{background:rgba(255,59,48,.14);color:#b42318;font-weight:900}.ai-table-luxury td[data-cell-tone="focus"]{background:rgba(79,107,255,.15);color:#304dcc;font-weight:900}
.ai-ranking-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;height:430px}.ai-ranking-group{padding:22px;border-radius:26px;background:rgba(255,255,255,.78);border:1px solid rgba(255,255,255,.9);box-shadow:var(--shadow)}.ai-ranking-group h3{font-size:23px;margin:0 0 14px}.ai-ranking-group>div{display:grid;grid-template-columns:28px 130px 1fr 88px;align-items:center;gap:10px;margin:9px 0}.ai-ranking-group>div b{color:var(--theme-solid)}.ai-ranking-group>div span{font-size:16px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ai-ranking-group>div i{height:10px;width:var(--w);border-radius:99px;background:var(--theme)}.ai-ranking-group>div strong{text-align:right;font-size:16px}
.ai-method-layout{display:grid;grid-template-columns:.78fr 1.22fr;gap:24px;height:430px}.ai-method-formula{border-radius:32px;padding:36px;background:linear-gradient(145deg,#151625,#312b48);color:#fff;display:flex;flex-direction:column;box-shadow:0 30px 72px rgba(20,22,38,.25)}.ai-method-formula span{font-size:16px;letter-spacing:.15em;color:rgba(255,255,255,.62)}.ai-method-formula strong{font-size:34px;line-height:1.35;margin:auto 0;background:var(--theme);-webkit-background-clip:text;background-clip:text;color:transparent}.ai-method-formula p{font-size:17px;color:rgba(255,255,255,.72);line-height:1.5}.ai-method-components{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.ai-method-components article{display:grid;grid-template-columns:64px 1fr;gap:14px;align-items:center;padding:18px;border-radius:22px;background:rgba(255,255,255,.78);border:1px solid rgba(255,255,255,.9);box-shadow:var(--shadow)}.ai-method-components i{display:grid;place-items:center;width:58px;height:58px;border-radius:18px;background:var(--theme);color:#fff;font-style:normal;font-weight:900}.ai-method-components h3{font-size:21px;margin:0 0 5px}.ai-method-components p{font-size:14px;line-height:1.35;color:var(--ink-2);margin:0}
.ai-finance-layout{grid-template-columns:.72fr 1.28fr;height:430px}.ai-finance-hero{border-radius:32px;padding:32px;color:#fff;background:linear-gradient(145deg,#141522,#31283e);box-shadow:0 30px 76px rgba(20,22,38,.28);display:flex;flex-direction:column}.ai-finance-hero>span{font-size:16px;font-weight:800;letter-spacing:.14em;color:rgba(255,255,255,.64)}.ai-finance-hero>strong{font-size:82px;line-height:1;margin:20px 0 12px;background:var(--theme);-webkit-background-clip:text;background-clip:text;color:transparent}.ai-finance-hero>strong small{font-size:28px}.ai-finance-hero>p{font-size:17px;color:rgba(255,255,255,.72);line-height:1.45}.ai-finance-grid{margin-top:auto}.ai-finance-kpi{padding:16px;background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.12);box-shadow:none}.ai-finance-kpi span{font-size:14px;color:rgba(255,255,255,.6)}.ai-finance-kpi strong{font-size:28px;color:#fff}.ai-finance-kpi small{font-size:13px;color:rgba(255,255,255,.7)}
.ai-cinematic-close{justify-content:flex-start;padding:74px 112px 132px;background:radial-gradient(circle at 78% 28%,color-mix(in srgb,var(--theme-solid) 38%,transparent),transparent 34%),radial-gradient(circle at 18% 86%,rgba(0,113,227,.28),transparent 34%),#080912;color:#fff}.ai-cinematic-close .ai-head h2{font-size:58px;margin:0}.ai-cinematic-close .ai-body{display:flex;flex:1;flex-direction:column;justify-content:center;padding-top:30px}.ai-cinematic-close .ai-action-summary{background:var(--theme);box-shadow:0 30px 80px color-mix(in srgb,var(--theme-solid) 35%,transparent)}.ai-cinematic-close .callout,.ai-cinematic-close .ai-action-chips span{background:rgba(255,255,255,.08);color:#fff;border:1px solid rgba(255,255,255,.12);box-shadow:none}.ai-cinematic-close .ai-quote{color:#fff}
.slide.ai-compact.ai-content{padding-top:46px}.slide.ai-compact .ai-head h2{font-size:48px}.slide.ai-compact .ai-body{padding-top:18px}.slide.ai-compact .ai-list,.slide.ai-compact .ai-feature-list p{font-size:20px}.slide.ai-compact .ai-feature-list article{padding:15px 20px}.slide.ai-compact .ai-roadmap article{padding:13px 18px}.slide.ai-compact .ai-roadmap p{font-size:15px}.slide.ai-compact .ai-three-cards article{min-height:290px;padding:27px}.slide.ai-compact .ai-tree,.slide.ai-compact .ai-venn{height:455px}
.slide.ai-compact .ai-primary-chart{min-height:350px}.slide.ai-compact .ai-kpi-card{min-height:320px}.slide.ai-compact .ai-table-wrap .tbl{font-size:17px}.slide.ai-compact .ai-table-wrap .tbl th,.slide.ai-compact .ai-table-wrap .tbl td{padding:11px 15px}
.ai-source-footer{position:absolute;left:112px;right:330px;bottom:116px;z-index:19;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px;color:rgba(60,68,90,.62)}.chapter .ai-source-footer{color:rgba(220,225,240,.62)}
.ai-source-appendix{position:absolute;left:112px;right:112px;bottom:116px;z-index:20;padding:12px 16px;border-radius:16px;background:rgba(8,9,18,.82);border:1px solid rgba(255,255,255,.12);backdrop-filter:blur(18px);color:rgba(255,255,255,.78)}.ai-source-appendix>strong{display:block;margin-bottom:7px;font-size:12px;letter-spacing:.08em}.ai-source-appendix>div{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3px 18px}.ai-source-appendix span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px}.ai-source-appendix b{color:#fff}
`;
  return { slides, css };
}
