import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { execFileSync } from 'node:child_process';

function resolveSourceRevision(): string {
  const supplied = process.env.VITE_GIT_SHA ?? process.env.GITHUB_SHA;
  if (supplied && /^[0-9a-f]{7,64}$/i.test(supplied)) return supplied.toLowerCase();
  try {
    const revision = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
    const changes = execFileSync('git', ['status', '--porcelain'], { encoding: 'utf8' }).trim();
    return `${revision}${changes ? '+dirty' : ''}`;
  } catch {
    return 'unversioned-local-source';
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __RIPPLE_SOURCE_REVISION__: JSON.stringify(resolveSourceRevision()),
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
});
