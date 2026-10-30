import { createHash, randomBytes } from 'node:crypto';
import { deckOutlineSchema } from './schema';
import { UnsupportedSkillError, validateSkillDeck } from './skills';
import type { DeckOutline, MotionMode, MotionPersona, MotionPlan, Slide, SlideMotion } from './schema';

export type MotionHistory = Pick<MotionPlan, 'fingerprint' | 'recipe' | 'background' | 'transition' | 'layoutSignature'>;

const RECIPES = {
  business: ['precision-flow', 'editorial-focus'],
  training: ['kinetic-classroom', 'playful-cascade'],
  cinematic: ['cinematic-depth', 'launch-spotlight'],
} as const;

const BACKGROUNDS = {
  business: ['aurora', 'kinetic-grid', 'spotlight'],
  training: ['particles', 'kinetic-grid', 'orbit'],
  cinematic: ['spotlight', 'particles', 'orbit'],
} as const;

const TRANSITIONS = {
  business: ['focus', 'directional', 'wipe'],
  training: ['directional', 'wipe', 'depth'],
  cinematic: ['depth', 'focus', 'wipe'],
} as const;

const ENTRANCES = {
  business: ['fade', 'up', 'left', 'right', 'zoom'],
  training: ['up', 'rise', 'pop', 'flip', 'left', 'right'],
  cinematic: ['blur', 'zoom', 'rise', 'stamp', 'fade'],
} as const;

const EFFECTS: Record<Slide['type'], readonly SlideMotion['effect'][]> = {
  cover: ['hero-focus', 'hero-orbit'],
  bullets: ['card-fan', 'spotlight-scan', 'content-cascade'],
  comparison: ['split-reveal', 'balance-pulse'],
  process: ['flow-packet', 'step-climb'],
  tree: ['branch-grow', 'layer-reveal'],
  venn: ['venn-focus', 'overlap-pulse'],
  closing: ['quote-reveal', 'action-cascade'],
  kpi: ['counter-focus', 'metric-pulse'],
  chart: ['chart-draw', 'data-scan', 'scatter-reveal', 'radar-sweep', 'stacked-grow'],
  funnel: ['funnel-cascade', 'stage-focus'],
  matrix: ['matrix-pop', 'quadrant-scan'],
  ranking: ['ranking-race', 'podium-focus'],
  table: ['table-cascade', 'ledger-scan', 'finance-focus'],
  heatmap: ['heatmap-wave', 'data-scan'],
  methodology: ['method-build', 'content-cascade'],
};

function effectsForSlide(slide: Slide): readonly SlideMotion['effect'][] {
  if (slide.type === 'chart') {
    if (slide.variant === 'scatter') return ['scatter-reveal', 'data-scan'];
    if (slide.variant === 'radar') return ['radar-sweep', 'data-scan'];
    if (slide.variant === 'stacked-bar') return ['stacked-grow', 'data-scan'];
    return ['chart-draw', 'data-scan'];
  }
  if (slide.type === 'heatmap') return ['heatmap-wave', 'data-scan'];
  if (slide.type === 'methodology') return ['method-build', 'content-cascade'];
  return EFFECTS[slide.type];
}

const LAYOUT_VARIANTS = {
  cover: ['cinematic', 'split-hero'],
  bullets: ['feature-list', 'three-cards', 'spotlight'],
  comparison: ['versus', 'two-column'],
  process: ['flow', 'ladder', 'roadmap'],
  tree: ['mind-map', 'layer-stack'],
  closing: ['quote', 'action-card'],
} as const;

function digest(value: string, length: number): string {
  return createHash('sha256').update(value).digest('hex').slice(0, length);
}

function indexFor(seed: string, key: string, length: number): number {
  return Number.parseInt(digest(`${seed}:${key}`, 8), 16) % length;
}

function classifyPersona(deck: DeckOutline, prompt: string): MotionPersona {
  const content = `${prompt} ${deck.title} ${deck.audience} ${deck.goal}`;
  if (/(发布会|产品发布|品牌发布|路演|融资|发布|launch|keynote)/iu.test(content) || deck.design.narrative === 'pitch') return 'cinematic';
  if (/(经营|财务|管理层|董事会|调研|市场报告|季度汇报|年度汇报|商业汇报)/u.test(prompt)) return 'business';
  if (/(培训|课程|教学|课堂|科普|学习|实操|工作坊|训练营)/u.test(content) || deck.design.narrative === 'teach') return 'training';
  return 'business';
}

function resolvedPersona(deck: DeckOutline, prompt: string, mode: MotionMode): MotionPersona {
  if (mode === 'subtle') return 'business';
  if (mode === 'vivid') return classifyPersona(deck, prompt) === 'business' ? 'cinematic' : classifyPersona(deck, prompt);
  return classifyPersona(deck, prompt);
}

function axesDistance(left: MotionHistory, right: MotionHistory): number {
  return Number(left.recipe !== right.recipe)
    + Number(left.background !== right.background)
    + Number(left.transition !== right.transition)
    + Number(left.layoutSignature !== right.layoutSignature);
}

function createSlideMotions(deck: DeckOutline, persona: MotionPersona, recipe: MotionPlan['recipe'], seed: string): SlideMotion[] {
  const entrances = ENTRANCES[persona];
  let previousEntrance: SlideMotion['entrance'] | undefined;
  let entranceRun = 0;
  let previousEffect: SlideMotion['effect'] | undefined;
  return deck.slides.map((slide, index) => {
    let entrance = entrances[indexFor(seed, `${recipe}:entrance:${slide.id}`, entrances.length)] as SlideMotion['entrance'];
    if (entrance === previousEntrance && entranceRun >= 2) {
      entrance = entrances[(entrances.indexOf(entrance as never) + 1) % entrances.length] as SlideMotion['entrance'];
    }
    entranceRun = entrance === previousEntrance ? entranceRun + 1 : 1;
    previousEntrance = entrance;
    const effects = effectsForSlide(slide);
    let effect = effects[indexFor(seed, `${recipe}:effect:${slide.id}`, effects.length)];
    if (effect === previousEffect && effects.length > 1) effect = effects[(effects.indexOf(effect) + 1) % effects.length];
    previousEffect = effect;
    return {
      slideId: slide.id,
      entrance,
      effect,
      stagger: 70 + indexFor(seed, `${recipe}:stagger:${slide.id}`, 12) * 10,
    };
  });
}

function diversifyLayouts(deck: DeckOutline, seed: string): DeckOutline['slides'] {
  return deck.slides.map(slide => {
    if (slide.type === 'cover') return { ...slide, variant: LAYOUT_VARIANTS.cover[indexFor(seed, `${slide.id}:layout`, LAYOUT_VARIANTS.cover.length)] };
    if (slide.type === 'bullets') return { ...slide, variant: LAYOUT_VARIANTS.bullets[indexFor(seed, `${slide.id}:layout`, LAYOUT_VARIANTS.bullets.length)] };
    if (slide.type === 'comparison') return { ...slide, variant: LAYOUT_VARIANTS.comparison[indexFor(seed, `${slide.id}:layout`, LAYOUT_VARIANTS.comparison.length)] };
    if (slide.type === 'process') {
      const choices = slide.steps.length > 4 ? ['flow', 'roadmap'] as const : LAYOUT_VARIANTS.process;
      return { ...slide, variant: choices[indexFor(seed, `${slide.id}:layout`, choices.length)] };
    }
    if (slide.type === 'tree') return { ...slide, variant: LAYOUT_VARIANTS.tree[indexFor(seed, `${slide.id}:layout`, LAYOUT_VARIANTS.tree.length)] };
    if (slide.type === 'closing') return { ...slide, variant: LAYOUT_VARIANTS.closing[indexFor(seed, `${slide.id}:layout`, LAYOUT_VARIANTS.closing.length)] };
    return slide;
  }) as DeckOutline['slides'];
}

function fingerprint(plan: Omit<MotionPlan, 'fingerprint'>): string {
  const sequence = plan.slides.map(slide => `${slide.entrance}.${slide.effect}.${slide.stagger}`).join('|');
  return `v1:${digest(`${plan.persona}|${plan.recipe}|${plan.background}|${plan.transition}|${plan.layoutSignature}|${sequence}`, 16)}`;
}

function compatible(slide: Slide, motion: SlideMotion): boolean {
  return motion.slideId === slide.id && effectsForSlide(slide).includes(motion.effect);
}

export function validateMotionPlan(deck: DeckOutline): MotionPlan | undefined {
  const plan = deck.motionPlan;
  if (!plan) return undefined;
  if (!deck.slides.every((slide, index) => compatible(slide, plan.slides[index]))) throw new Error('Motion plan is incompatible with slide content');
  const { fingerprint: supplied, ...unsigned } = plan;
  if (fingerprint(unsigned) !== supplied) throw new Error('Motion plan fingerprint is invalid');
  return plan;
}

export class MotionResolutionError extends Error {
  override name = 'MotionResolutionError';
}

export function resolveMotionPlan(
  deck: DeckOutline,
  options: { prompt?: string; mode?: MotionMode; recent?: MotionHistory[]; exclude?: string[]; seedBase?: string; preserveLayouts?: boolean } = {},
): DeckOutline {
  // Validate before attempting any layout fallback; never repair illegal input here.
  deckOutlineSchema.parse(deck);
  validateSkillDeck(deck);
  validateMotionPlan(deck);
  const mode = options.mode ?? deck.motionPlan?.mode ?? 'auto';
  const persona = resolvedPersona(deck, options.prompt || '', mode);
  const recent = (options.recent || []).slice(0, 5);
  const excluded = new Set([...(options.exclude || []), ...recent.map(item => item.fingerprint)]);
  const seedBase = options.seedBase || randomBytes(8).toString('hex');
  type Candidate = { plan: MotionPlan; slides: DeckOutline['slides'] };
  let candidateIndex = 0;
  function candidates(preserveLayouts: boolean): Candidate[] {
    const valid: Candidate[] = [];
    for (const recipe of RECIPES[persona]) {
      for (const background of BACKGROUNDS[persona]) {
        for (const transition of TRANSITIONS[persona]) {
          const seed = digest(`${seedBase}:${candidateIndex}:${recipe}:${background}:${transition}`, 16);
          candidateIndex += 1;
          const slides = preserveLayouts ? deck.slides : diversifyLayouts(deck, seed);
          const candidateDeck = { ...deck, slides };
          const layoutSignature = digest(`${deck.skill.id}@${deck.skill.version}|${slides.map(slide => `${slide.type}:${slide.variant}`).join('|')}`, 12);
          const unsigned: Omit<MotionPlan, 'fingerprint'> = {
            version: 1, mode, persona, recipe, seed, background, transition, layoutSignature,
            slides: createSlideMotions(candidateDeck, persona, recipe, seed),
          };
          const plan = { ...unsigned, fingerprint: fingerprint(unsigned) };
          const candidate = { ...candidateDeck, motionPlan: plan };
          if (!deckOutlineSchema.safeParse(candidate).success) continue;
          if (slides.some(slide => slide.type === 'process' && slide.steps.length > 4 && slide.variant === 'ladder')) continue;
          try { validateSkillDeck(candidate); }
          catch (error) {
            if (error instanceof UnsupportedSkillError) continue;
            throw error;
          }
          validateMotionPlan(candidate);
          valid.push({ plan, slides });
        }
      }
    }
    return valid;
  }
  function select(choices: Candidate[]): Candidate | undefined {
    const previous = recent[0];
    const ranked = choices
      .filter(candidate => !excluded.has(candidate.plan.fingerprint))
      .map(candidate => ({
        candidate,
        previousDistance: previous ? axesDistance(candidate.plan, previous) : 4,
        totalDistance: recent.reduce((sum, item) => sum + axesDistance(candidate.plan, item), 0),
        tie: indexFor(seedBase, candidate.plan.fingerprint, 1_000_000),
      }))
      .sort((left, right) => right.previousDistance - left.previousDistance || right.totalDistance - left.totalDistance || right.tie - left.tie);
    return ranked.find(item => item.previousDistance >= 3)?.candidate || ranked[0]?.candidate;
  }
  const selected = select(candidates(Boolean(options.preserveLayouts))) || select(candidates(true));
  if (!selected) throw new MotionResolutionError('No valid motion candidate available');
  return { ...deck, slides: selected.slides, motionPlan: selected.plan };
}

export function ensureMotionPlan(deck: DeckOutline): DeckOutline {
  if (validateMotionPlan(deck)) return deck;
  return resolveMotionPlan(deck, { prompt: `${deck.title} ${deck.goal}`, mode: 'auto', seedBase: digest(deck.title, 16), preserveLayouts: true });
}

export function motionHistory(plan: MotionPlan): MotionHistory {
  return {
    fingerprint: plan.fingerprint,
    recipe: plan.recipe,
    background: plan.background,
    transition: plan.transition,
    layoutSignature: plan.layoutSignature,
  };
}

export function motionProfileLabel(plan: MotionPlan): string {
  const personas: Record<MotionPersona, string> = { business: '商务克制', training: '培训活泼', cinematic: '发布会电影感' };
  const backgrounds: Record<MotionPlan['background'], string> = {
    aurora: '极光', particles: '粒子星场', 'kinetic-grid': '动态网格', spotlight: '聚光舞台', orbit: '轨道光环',
  };
  return `${personas[plan.persona]} · ${backgrounds[plan.background]}`;
}
