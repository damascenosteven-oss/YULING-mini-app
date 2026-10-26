import { build } from 'tsup';
import { readFileSync, writeFileSync } from 'node:fs';
import ts from 'typescript';

await build({
  entry: { 'release-smoke': 'scripts/release-smoke.ts' },
  format: ['cjs'],
  platform: 'node',
  target: 'node22',
  outDir: 'dist',
  splitting: false,
  minify: false,
  noExternal: ['pixelmatch', 'pngjs'],
});
writeFileSync('dist/next.config.mjs', ts.transpileModule(readFileSync('next.config.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText);
