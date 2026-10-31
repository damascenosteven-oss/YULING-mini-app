import type { DeckOutline, PresentationSkillId, PublicSkillId, Slide } from './schema';

export type PresentationSkill = {
  id: PublicSkillId;
  version: 1;
  label: string;
  description: string;
  prompt: string;
  defaultNarrative: DeckOutline['design']['narrative'];
  defaultMood: DeckOutline['design']['mood'];
  allowed: ReadonlySet<string>;
};

const common = [
  'cover:cinematic', 'cover:split-hero',
  'bullets:feature-list', 'bullets:three-cards', 'bullets:spotlight',
  'comparison:versus', 'comparison:two-column',
  'process:flow', 'process:ladder', 'process:roadmap',
  'tree:mind-map', 'tree:layer-stack', 'venn:circles',
  'closing:quote', 'closing:action-card',
] as const;
const commercial = [
  'kpi:dashboard', 'chart:bar', 'chart:line', 'chart:donut', 'chart:scatter', 'chart:radar', 'chart:stacked-bar',
  'funnel:conversion', 'matrix:quadrant', 'ranking:horizontal-bars', 'ranking:grouped',
  'heatmap:matrix', 'methodology:score-model',
  'table:data-table', 'table:highlight-table', 'table:financial-return',
] as const;

function allowed(...items: ReadonlyArray<readonly string[]>): ReadonlySet<string> {
  return new Set(items.flat());
}

export const PRESENTATION_SKILLS: Record<PublicSkillId, PresentationSkill> = {
  'executive-briefing': {
    id: 'executive-briefing', version: 1, label: '管理层经营汇报', description: 'KPI、经营趋势、排名、财务与行动决策',
    defaultNarrative: 'report', defaultMood: 'professional', allowed: allowed(common, commercial),
    prompt: '本套是管理层经营汇报。结论先行，数据页必须给出管理含义；优先使用 KPI、趋势、排名、财务和行动项，避免课程化解释。',
  },
  'data-research-report': {
    id: 'data-research-report', version: 1, label: '数据研究报告', description: '行业、市场、政策、品牌心智与 GEO 研究',
    defaultNarrative: 'report', defaultMood: 'professional', allowed: allowed(common, commercial),
    prompt: '本套是正式数据研究报告。需要方法说明、章节节奏、证据图和来源；优先根据关系选择散点、雷达、堆叠、热力、分组排名或高亮表，不堆砌图表。',
  },
  'training-course': {
    id: 'training-course', version: 1, label: '培训课程', description: '学习目标、知识讲解、案例、流程与练习',
    defaultNarrative: 'teach', defaultMood: 'energetic', allowed: allowed(common, commercial),
    prompt: '本套是培训课程。按照目标、概念、方法、案例、练习和行动形成教学节奏；优先使用卡片、流程、树图、对比和少量必要数据。',
  },
  'product-launch': {
    id: 'product-launch', version: 1, label: '产品发布', description: '发布会、路演、产品价值与品牌展示',
    defaultNarrative: 'pitch', defaultMood: 'energetic', allowed: allowed(common, commercial),
    prompt: '本套是产品发布或路演。采用强主视觉、价值主张、能力证明、关键指标、路线图与行动收束；文字更少、更有舞台冲击力。',
  },
  'project-proposal': {
    id: 'project-proposal', version: 1, label: '项目方案', description: '客户提案、投标、实施路径、风险与收益',
    defaultNarrative: 'proposal', defaultMood: 'professional', allowed: allowed(common, commercial),
    prompt: '本套是项目方案。按照问题、目标、解决方案、实施路径、资源投入、风险、收益和下一步形成完整决策链。',
  },
};

export class UnsupportedSkillError extends Error {
  readonly code = 'PPT_SKILL_UNSUPPORTED';
  constructor(message: string, readonly repairConstraint?: string) { super(message); }
}

export function resolveSkill(prompt: string, requested: 'auto' | PublicSkillId): PresentationSkill {
  if (requested !== 'auto') return PRESENTATION_SKILLS[requested];
  if (/(行业|市场|政策|调查|调研|品牌心智|GEO|地区现状|白皮书|研究报告)/iu.test(prompt)) return PRESENTATION_SKILLS['data-research-report'];
  if (/(经营|财务|董事会|复盘|管理层|季度汇报|年度汇报|业务汇报)/u.test(prompt)) return PRESENTATION_SKILLS['executive-briefing'];
  if (/(培训|教学|课程|科普|工作坊|训练营|课堂|学习)/u.test(prompt)) return PRESENTATION_SKILLS['training-course'];
  if (/(发布|路演|融资|品牌展示|产品介绍|launch|keynote)/iu.test(prompt)) return PRESENTATION_SKILLS['product-launch'];
  return PRESENTATION_SKILLS['project-proposal'];
}

function slideKey(slide: Slide): string {
  return `${slide.type}:${slide.variant}`;
}

function isDataSlide(slide: Slide): boolean {
  return ['kpi', 'chart', 'funnel', 'matrix', 'ranking', 'table', 'heatmap', 'methodology'].includes(slide.type);
}

export function skillSlideError(slide: Slide, index: number, skill: PresentationSkill): UnsupportedSkillError | undefined {
  if (!skill.allowed.has(slideKey(slide))) return new UnsupportedSkillError(`第 ${index + 1} 页不属于 ${skill.label} 的受控结构`, `第${index + 1}页 slides.${index}.variant：请选择当前 Skill 允许的 type:variant：${[...skill.allowed].join('|')}`);
  if ((skill.id === 'data-research-report' || skill.id === 'executive-briefing') && isDataSlide(slide) && !('story' in slide && slide.story)) {
    return new UnsupportedSkillError(`第 ${index + 1} 页缺少数据故事`, `第${index + 1}页 slides.${index}.story：必须包含 question、claim、implication 和 focusKeys，说明该页数据的比较问题、结论和行动含义；保留其他合法内容`);
  }
}

export function validateSkillDeck(deck: DeckOutline): DeckOutline {
  if (deck.skill.id === 'legacy-general') return deck;
  const skill = PRESENTATION_SKILLS[deck.skill.id];
  if (!skill || deck.skill.version !== skill.version) throw new UnsupportedSkillError('不支持的 Presentation Skill 或版本');
  const errors = deck.slides.map((slide, index) => skillSlideError(slide, index, skill)).filter(error => error !== undefined);
  if (errors.length) throw new UnsupportedSkillError(errors[0].message, errors.map(error => error.repairConstraint).join('；'));
  return deck;
}

export function skillLabel(id: PresentationSkillId): string {
  return id === 'legacy-general' ? '经典通用' : PRESENTATION_SKILLS[id].label;
}
