import assert from 'node:assert/strict';
import { createServer } from 'node:net';
import test from 'node:test';
import { commandForPlatform, isPortAvailable, runChild } from './task-runner-lib.mjs';

test('Windows pnpm uses its Node entrypoint without shell parsing', () => {
  const entrypoint = 'C:\\Tools with spaces\\pnpm.cjs';
  const args = ['exec', 'tool', 'value & literal'];
  assert.deepEqual(commandForPlatform('pnpm', args, { npm_execpath: entrypoint }, 'win32'),
    [process.execPath, [entrypoint, ...args]]);
  assert.deepEqual(commandForPlatform('node', args, {}, 'win32'), ['node', args]);
  assert.deepEqual(commandForPlatform('pnpm', args, {}, 'darwin'), ['pnpm', args]);
  assert.throws(() => commandForPlatform('pnpm', args, {}, 'win32'), /Run this task through pnpm/);
});

test('task runner starts the real pnpm CLI', async () => {
  assert.equal(await runChild('pnpm', ['--version'], { stdio: 'ignore' }), 0);
});

test('port check detects an occupied port without terminating its owner', async () => {
  const server = createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  assert.equal(await isPortAvailable(address.port), false);
  assert.equal(server.listening, true);
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
});

test('child execution preserves non-zero exit codes', async () => {
  const code = await runChild(process.execPath, ['-e', 'process.exit(7)'], { stdio: 'ignore' });
  assert.equal(code, 7);
});
