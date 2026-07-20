import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';

if (process.platform === 'win32') {
  execFileSync(
    'powershell.exe',
    [
      '-NoProfile',
      '-NonInteractive',
      '-Command',
      "New-Item -ItemType Directory -Force -Path 'dist/assets' | Out-Null",
    ],
    { stdio: 'inherit' },
  );
} else {
  mkdirSync('dist/assets', { recursive: true });
}
