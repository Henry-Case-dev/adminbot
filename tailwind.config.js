/**
 * F4 10.16 (ADR-1016-2 §2-3, T-1652/T-1654) — Tailwind: build-time, без CDN.
 *
 * Play CDN (cdn.tailwindcss.com) исключён: это рантайм-JIT, тяжёлый и не для
 * прода. Здесь сканируем реальные исходники и коммитим ПРЕДСОБРАННЫЙ CSS в
 * `web/static/vendor/tailwind.css` (серверу Node не нужен, zero-build).
 *
 * Пересборка после правок вёрстки/классов:
 *   npx --yes tailwindcss@3.4.17 \
 *     -c tailwind.config.js \
 *     -i web/static/tailwind.input.css \
 *     -o web/static/vendor/tailwind.css --minify
 *
 * Динамических Tailwind-утилит, собираемых из JS-строк, в проекте нет:
 * :class-биндинги (`'ekg-' + level`, `'toast-' + kind`, badge-.../avail-...)
 * указывают на КАСТОМНЫЕ классы из web/static/app.css, которые Tailwind не
 * генерирует. Если появится динамическая утилита (напр. `'text-' + x`) —
 * добавить её в safelist и пересобрать (не возвращать CDN).
 */
module.exports = {
  content: ['./web/index.html', './web/app.js'],
  safelist: [],
  theme: {
    extend: {},
  },
};
