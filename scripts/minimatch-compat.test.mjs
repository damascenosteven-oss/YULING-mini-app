import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { ESLint } from 'eslint';
import importPlugin from 'eslint-plugin-import-x';

test('patched import rules preserve glob restrictions and cycle detection', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'yuling-import-compat-'));
  try {
    await writeFile(path.join(root, 'package.json'), JSON.stringify({ name: 'fixture-project', type: 'module' }));
    await writeFile(path.join(root, 'entry.js'), '');
    const dependency = path.join(root, 'node_modules/fixture-pkg');
    await mkdir(dependency, { recursive: true });
    await writeFile(path.join(dependency, 'package.json'), JSON.stringify({ name: 'fixture-pkg', main: 'index.js' }));
    for (const name of ['index.js', 'internal.js', 'allowed.js']) {
      await writeFile(path.join(dependency, name), 'export default 1;\n');
    }
    const lint = async (options, source = "import value from 'fixture-pkg/internal.js';") => {
      const eslint = new ESLint({ cwd: root, overrideConfigFile: true, overrideConfig: [{
        plugins: { 'import-x': importPlugin },
        rules: { 'import-x/no-internal-modules': ['error', options] },
      }] });
      const [result] = await eslint.lintText(source, { filePath: path.join(root, 'entry.js') });
      assert.equal(result.fatalErrorCount, 0);
      return result.messages.filter(message => message.ruleId === 'import-x/no-internal-modules').length;
    };
    assert.equal(await lint({ forbid: ['fixture-pkg/**'] }), 1);
    assert.equal(await lint({ forbid: ['fixture-pkg/{internal,other}.js'] }), 1);
    assert.equal(await lint({ forbid: ['!**/allowed.js'] }), 1);
    assert.equal(await lint({ forbid: ['!**/allowed.js'] }, "import value from 'fixture-pkg/allowed.js';"), 0);
    assert.equal(await lint({ forbid: ['#comment', ''] }), 0);
    assert.equal(await lint({ allow: ['fixture-pkg/**'] }), 0);
    assert.equal(await lint({ allow: ['other/**', '#comment', ''] }), 1);

    await writeFile(path.join(root, 'a.js'), "import { b } from './b.js'; export const a = () => b;\n");
    await writeFile(path.join(root, 'b.js'), "import { a } from './a.js'; export const b = () => a;\n");
    const cycles = new ESLint({ cwd: root, overrideConfigFile: true, overrideConfig: [{
      plugins: { 'import-x': importPlugin }, rules: { 'import-x/no-cycle': 'error' },
    }] });
    const results = await cycles.lintFiles(['a.js', 'b.js']);
    assert.ok(results.some(result => result.messages.some(message => message.ruleId === 'import-x/no-cycle')));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
