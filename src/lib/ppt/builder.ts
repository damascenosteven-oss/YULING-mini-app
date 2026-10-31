import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import type { DeckOutline } from './schema';
import { renderDeck } from './renderer';
import { ensureMotionPlan } from './motion';
import { pythonCandidates, type PythonCommand } from './platform';
import { adaptMobilePlayback } from './mobile-playback';

function engineRoot(): string {
  const root = process.env.PPT_ENGINE_ROOT;
  if (!root) throw new Error('PPT_ENGINE_ROOT is not configured');
  return path.resolve(root);
}

function runPython(candidate: PythonCommand, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(candidate.command, [...candidate.prefixArgs, ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stderr = '';
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback();
    };
    child.stderr.on('data', chunk => {
      stderr += String(chunk).slice(0, 4000);
    });
    const timer = setTimeout(() => child.kill('SIGKILL'), 20_000);
    child.once('error', error => finish(() => reject(error)));
    child.once('close', code => finish(() => {
      if (code === 0) resolve();
      else reject(new Error(`PPT builder failed (${code ?? 'signal'}): ${stderr.trim()}`));
    }));
  });
}

async function runBuilder(deckDirectory: string, outputPath: string): Promise<void> {
  const root = engineRoot();
  const args = [path.join(root, 'tools/build_deck.py'), '--deck', deckDirectory, '--engine-root', root, '--out', outputPath];
  let lastMissing: NodeJS.ErrnoException | undefined;
  for (const candidate of pythonCandidates()) {
    try {
      await runPython(candidate, args);
      return;
    } catch (error) {
      const systemError = error as NodeJS.ErrnoException;
      if (systemError.code !== 'ENOENT') throw error;
      lastMissing = systemError;
    }
  }
  throw new Error(`No Python interpreter was found. Configure PPT_PYTHON_PATH.${lastMissing ? ` (${lastMissing.code})` : ''}`);
}

export async function buildDeckHtml(outline: DeckOutline): Promise<Buffer> {
  const directory = await mkdtemp(path.join(tmpdir(), 'yuling-ppt-'));
  try {
    const slidesDirectory = path.join(directory, 'slides');
    const stylesDirectory = path.join(directory, 'styles');
    const outputPath = path.join(directory, 'deck.html');
    await Promise.all([mkdir(slidesDirectory), mkdir(stylesDirectory)]);
    const resolved = ensureMotionPlan(outline);
    const rendered = renderDeck(resolved);
    const motion = resolved.motionPlan;
    await Promise.all([
      writeFile(
        path.join(directory, 'deck.json'),
        JSON.stringify({
          title: resolved.title,
          brand: '毓灵 YuLing AI',
          logo: path.resolve(process.cwd(), 'public/yuling-logo.png'),
          style: '苹果风',
          skill: { id: resolved.skill.id, version: resolved.skill.version },
          ...(motion ? { motion: {
            persona: motion.persona,
            recipe: motion.recipe,
            background: motion.background,
            transition: motion.transition,
            fingerprint: motion.fingerprint,
          } } : {}),
          output: outputPath,
        }),
      ),
      writeFile(path.join(stylesDirectory, 'ai-generated.css'), rendered.css),
      ...rendered.slides.map((slide, index) =>
        writeFile(path.join(slidesDirectory, `${String(index + 1).padStart(2, '0')}.html`), slide),
      ),
    ]);
    await runBuilder(directory, outputPath);
    const html = await readFile(outputPath, 'utf8');
    const marked = html.replace(
      '</head>',
      '<meta name="generator" content="YuLing AI PPT"><meta name="ai-generated" content="true"></head>',
    );
    return Buffer.from(adaptMobilePlayback(marked));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}
