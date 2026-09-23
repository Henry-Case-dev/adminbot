# Vendored client bundles (same-origin, CSP `script-src 'self'`)

Round 10.25 / hotfix9 (`hotfix9-shell-liquidglass-darkaurora-round1025`,
ADR-1025-17 D5/D6). These files are **built locally** with `esbuild` and served
from our own server — no CDN, no inline script. npm is a build tool only; the
application stays zero-build at runtime.

## Files

| File | Package | Version | License | SHA-256 |
|---|---|---|---|---|
| `ogl.1.0.11.min.js` | [`ogl`](https://github.com/oframe/ogl) | `1.0.11` | Unlicense | `E40E6275EB2A3511239209BE96EF41BBC559F82F21BBF388C34EC89B4F04477B` |
| `liquidglass.core.0.5.3.min.js` | [`@liquidglassjs/core`](https://github.com/Amir-Abushanab/liquid-glass-js) | `0.5.3` | MIT | `77E8A873FB779AD435058406EB3B15CB5AB30E39B1E98061C24B01898A4B1B1A` |
| `liquidglass.core.0.5.3.css` | `@liquidglassjs/core` (`.ps-glass*` chrome) | `0.5.3` | MIT | `E42DAC700A9E50ECF193B74D626DB4A4BEC57C93F8DEB0B9A5CA5B69618BC431` |
| `delaunator.5.0.0.min.js` | [`delaunator`](https://github.com/mapbox/delaunator) | `5.0.0` | ISC | `7707D7FE750559D4D31DBDEBEA5E41024487520BC1CC9967AC9795B4A682C1BE` |

Both bundles are IIFE with global names `OGL` and `LiquidGlass`.
`delaunator.5.0.0.min.js` is an IIFE that assigns the `Delaunator` **class
itself** to the global (so `typeof Delaunator.from === 'function'`); the
transitive `robust-predicates` dependency is bundled in. License: **ISC**
(`delaunator` 5.0.0, © Vladimir Agafonkin).

## Build

```sh
cd tools/vendor
npm ci
npm run build   # -> ../../web/static/vendor/{ogl,liquidglass}.*
```

`tools/vendor/package.json` + `package-lock.json` pin the exact versions.
`tools/vendor/node_modules/` is not committed (see root `.gitignore`).

## Notes

- `@liquidglassjs/core` renders refraction with an SVG `feDisplacementMap` over
  **live DOM**, so it does not depend on `backdrop-filter: url()` (which the
  project forbids in first-party CSS). If the renderer cannot be mounted the
  integration honestly degrades to a frosted-glass fallback.
- `ogl` is used **only** by the single background canvas (`Dark Aurora Flow`).
  No WebGL scene is created per card.
- `delaunator` (round 10.26, ADR-1026-3 D3) is used **only** by the single
  Polygon background canvas (`polygon-background.js`) for Delaunay
  triangulation of the node cloud. It is loaded before `polygon-background.js`
  and `app.js`; no CDN is used at runtime.
