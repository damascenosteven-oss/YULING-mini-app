import { spawn } from 'node:child_process';
import { createServer } from 'node:net';

export function commandForPlatform(command, args, environment = process.env, platform = process.platform) {
  if (platform === 'win32' && command === 'pnpm') {
    if (!environment.npm_execpath) throw new Error('Run this task through pnpm so npm_execpath is available.');
    return [process.execPath, [environment.npm_execpath, ...args]];
  }
  return [command, args];
}

export function runChild(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const [executable, childArgs] = commandForPlatform(command, args, options.env ?? process.env);
    const child = spawn(executable, childArgs, options);
    child.once('error', reject);
    child.once('close', code => resolve(code ?? 1));
  });
}

export function isPortAvailable(port, host = '127.0.0.1') {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.unref();
    probe.once('error', error => {
      if (error.code === 'EADDRINUSE' || error.code === 'EACCES') resolve(false);
      else reject(error);
    });
    probe.listen(port, host, () => probe.close(error => error ? reject(error) : resolve(true)));
  });
}
