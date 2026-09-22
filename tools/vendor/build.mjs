// Builder: локальная сборка vendored-бандлов (ADR-1025-17 D5/D6, T-2818/T-2820).
// npm здесь — ТОЛЬКО инструмент сборки: рантайм проекта остаётся zero-build,
// готовые IIFE отдаются с собственного сервера (CSP script-src 'self', без CDN).
//
// Запуск:  cd tools/vendor && npm ci && npm run build
// Выход:   web/static/vendor/ogl.1.0.11.min.js
//          web/static/vendor/liquidglass.core.0.5.3.min.js
//          web/static/vendor/liquidglass.core.0.5.3.css
import { build } from 'esbuild';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');
const outdir = join(repo, 'web', 'static', 'vendor');
mkdirSync(outdir, { recursive: true });

// Промежуточные entry-файлы (ESM re-export) — генерируются на лету.
const oglEntry = join(here, '.ogl-entry.mjs');
const lgEntry = join(here, '.liquidglass-entry.mjs');
writeFileSync(oglEntry, "export * from 'ogl';\n", 'utf8');
writeFileSync(lgEntry, "export * from '@liquidglassjs/core';\n", 'utf8');

await build({
  entryPoints: [oglEntry],
  bundle: true, format: 'iife', globalName: 'OGL', minify: true,
  legalComments: 'none', outfile: join(outdir, 'ogl.1.0.11.min.js'),
});
await build({
  entryPoints: [lgEntry],
  bundle: true, format: 'iife', globalName: 'LiquidGlass', minify: true,
  legalComments: 'none',
  outfile: join(outdir, 'liquidglass.core.0.5.3.min.js'),
});
await build({
  entryPoints: [join(here, 'node_modules', '@liquidglassjs', 'core', 'src', 'css', 'glass.css')],
  bundle: true, minify: true,
  outfile: join(outdir, 'liquidglass.core.0.5.3.css'),
});

console.log('vendored bundles written to', outdir);
