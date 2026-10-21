# REV-MINILENS — mini-lens fullscreen binding (leaf review)

Candidate: 6c1dea40 (fix) on ceb3e437, prep note 7e42c7ee; worktree HEAD=7e42c7ee, web-файлы чистые.
Base lens: REV-W2-N1 (has_mini_lens=false @31c16555); contract U08.4d/U08.5.1.

## Воспроизведено (все на байтах кандидата)
- `node tests/js/asap8_u084d_mini_lens_binding_test.js` → MINI-LENS-BINDING-OK (разметка: класс на единственном узле ⛶, ровно 1 экземпляр lg-mini-lens в index.html; @click=toggleFullscreen → policy.request/exit; v-if/aria-pressed сохранены; швы стекла _lgGlassSelector+SURFACE_SELECTOR; круг+rim; 44×44; hover/active без background, brightness есть).
- `node --check web/app.js` → OK.
- `node tests/js/asap8_w2_fullscreen_policy_test.js` → FS-POLICY-OK (28 проверок; обновлённый pin «материал только из .lg-mini-lens» зелёный).
- `node tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js` → HOTFIX6-OK (pin класса обновлен когерентно).
- glass_probe_test.js / glass_refraction_test.js / round1025_design_tokens_test.js → OK.

## Аудит диффа
- Ровно 6 файлов, все по существу; web/static/fullscreen-policy.js НЕ менялся; app.js — только комментарий.
- .header-fs-btn: фон/рамка/border-radius/color сняты, остались геометрия+filter-переход; hover/active = filter:brightness(1.12/.92). Прочие правила кнопки в CSS: два header-context (order/геометрия), focus-visible (outline) — фон нигде не рисуется.
- Материал .lg-mini-lens: border-radius:50%, rim (::after + --lg-rim + ring-mask), блик (radial 30% 22% + inset highlight), frost — контракт U08.4d соблюдён.

## Честность карты
- U08.4d/U08.5.1 = PENDING в requirements-map.json (VERIFIED только после deployed live check, live_required preprod) — корректно.
- prep-rfl-binding.md:60 — «FIX APPLIED @6c1dea40, PENDING DEPLOY» присутствует.

## Примечания (non-blocking)
- Pin-regex W2-теста сужен `[^{,]*` (исключает selector-списки с запятой после .header-fs-btn из backdrop/background-проверки). Таких правил в CSS нет; основное правило прямо покрыто binding-тестом. Фоновая заметка, фиксации не требует.

## Вердикт
APPROVED (leaf): фикс корректен, минимален, тесты реально защищают контракт; готов к релизному поезду 2.58.105. U08.4d/U08.5.1 → VERIFIED только после deployed live check.
