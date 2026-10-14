# Scanner-аудит: hotfix4-cover-nav-shell-round1025

- **Дата:** 21.09.2026, Step 6 @Scanner
- **Диапазон:** `git diff 5f624cd..HEAD` (HEAD `f458b8c`), фича `hotfix4-cover-nav-shell-round1025`
- **Область:** `services/summary_generator.py`, `services/summary_prompts.py`, `services/prompt_migrations.py`,
  `plans/docs/canon/**`, `web/app.js` (bottom-nav/More), `web/static/app.css`, `web/static/telegram-init.js`,
  `web/index.html`, `tools/ui_round1025_matrix.py`, `config/settings.py`, новые тесты.

## Итог

**Critical 0 / High 0 / Medium 1 / Low 5.** Блокеров нет → **к деплою — да.**

## Medium

- **[M10.25H4-1] Тест-тавтология offset (тест-качество).** `tests/js/round1025_hotfix4_shell_test.js:47-53` —
  локальная копия формулы `offset(layoutH, stableH)` + подстроковые проверки `window.innerHeight`/`viewportStableHeight`.
  Если поменять арифметику в `telegram-init.js`, оставив имена, JS-тесты пройдут. Матрица тоже не запускает JS-формулу
  (она выставляет `--tg-viewport-bottom-offset` напрямую). Сценарий: регресс клампа «залипает» до прод-визуала.
  **Фикс:** поднять `telegram-init.js` в jsdom-стенде с подставным `window.Telegram.WebApp` и проверять фактическое
  значение `--tg-viewport-bottom-offset` для stable = отсутствует / 0 / больше / меньше `innerHeight`.

## Low

- **[L10.25H4-1] Нет guard `stableH > 0`.** `web/static/telegram-init.js:54-56`. Если клиент отдаёт
  `viewportStableHeight` = 0/отрицательный (свёрнутое окно / устаревшее событие; геттер SDK = `raw - bottomBarHeight`),
  `offset` клампится в `layoutH` → `.bottom-nav` получает `bottom: <весь экран>` и уезжает за экран до следующего события.
  **Фикс:** `if (typeof stableH === 'number' && stableH > 0 && layoutH > 0)`.

- **[L10.25H4-2] CSS-фолбэк на `100dvh`.** `web/static/app.css:1350-1352`. `dvh` не поддерживают старые iOS WebKit
  (<15.4) и Chromium <108: при невыставленной `--tg-viewport-bottom-offset` (страница открыта вне Telegram, но shell
  рендерится) объявление `bottom` невалидно → `bottom: auto`. В Telegram переменную всегда ставит JS, поэтому ущерб узкий.
  **Фикс:** добавить `bottom: 0;` отдельной строкой перед `bottom: var(...)` как последний резерв.

- **[L10.25H4-3] `has_heading` ловит подстроки.** `services/summary_generator.py:149-150` — токены `"perm"`/`"title"`
  дают ложные срабатывания (например, «permanent», «entitled»). Маркер только для наблюдаемости, но может ввести в
  заблуждение при разборе именно этого P0. **Фикс:** границы слов (`\bpermsoc\b`, `\bheading\b`, `\btitle\b`, «заголов»).

- **[L10.25H4-4] `viewport-fit=cover` не гейтится `IA_V2_ENABLED`.** `web/index.html:5-7`. Мета глобальна, поэтому при
  `IA_V2_ENABLED=false` на iOS layout тоже растягивается под home-indicator, а legacy-shell не имеет нижней
  safe-area-компенсации (`.bottom-nav`/`.more-sheet` — только ON). Минорный визуал. **Фикс:** либо подтвердить OFF-скоуп
  в ADR, либо добавить нижний safe-area-паддинг в legacy-контейнер.

- **[L10.25H4-5] Связность тестов.** `tests/test_hotfix4_cover_nav_shell_round1025.py` импортирует приватные
  хелперы (`_Recorder`, `_env`, `_generator`) из `tests/test_hotfix3_summary_fallback_round1025.py`: рефакторинг
  hotfix3-тестов ломает hotfix4-гейт. **Фикс:** вынести общие фикстуры в `tests/conftest.py` или локальный helper-модуль.

## Верифицировано чисто

- **Стиль обложки (A):** `compose_cover_image_prompt` не изменён — порядок `style → visual` и капы (стиль 500, всего 1000)
  сохранены; `resolve_cover_style` применяет стиль владельца как есть, код-дефолт — только при `None`/пробелах.
- **R17/безопасность:** новые логи (`summary_generator.py:806-813`, `:728-730`, `:753-755`) несут только длины и
  булевы маркеры; текст стиля/промпта не утекает (тест `test_configured_style_reaches_compose_and_log` это фиксирует).
  В диффе нет секретов; CSP — без inline-скриптов/обработчиков и `eval` (проверено JS-тестами).
- **Целостность миграций канона:** `PREV_SUMMARY_EDITOR_R1025_HOTFIX4` побайтово совпал с прод-каноном до правки
  (загрузка блоба `5f624cd:services/summary_prompts.py`) → ступень миграции/откат корректны.
- **Навигация (C):** `navItems` (`app.js:1310-1322`) всегда отдаёт `status`+`how` (public) → они всегда первые два у всех
  ролей; `bottomNavItems` ≤4 (status, how, modules|ai, more); `Ещё` — только при `hiddenCount>0`; `mobileMoreItems`
  исключает inline-раздел и public → нет дубля «Справки», все непубличные разделы достижимы.
- **OFF-режим:** `NAV_ITEMS` (legacy) не тронут, bottom-nav рендерится только при `iaV2` — false-путь не задет.
- **Матрица реально проверяет вертикаль:** во время аудита временно навязал `.bottom-nav { bottom: 0 !important; }` →
  матрица дала **56 failures** (панель уезжала под видимую область); после восстановления — **0 failures**.

## Прогоны (факт)

- `python -m pytest -q` → **8065 passed, 1 warning** (Starlette deprecation), 106.91 s.
- JS: `round1025_hotfix4_shell_test.js`, `round1025_ia_routing_test.js`, `round1025_shell_breakpoints_test.js`,
  `routing_test.js` → `JS-UNIT-OK`; все JS-тесты через `tests/test_webapp_js_unit.py` — зелёные.
- `tools/ui_round1025_matrix.py` → **failures: 0**; mobile (320/360/390/430) `bottomNav=True(4)`; sidebar/drawer/nav взаимоисключающи.
- `git diff --check` = 0; `node --check web/app.js` и `web/static/telegram-init.js` = 0.

## Инварианты

- Δ DDL = 0 (файлы схемы/миграций БД не тронуты; `prompt_migrations.py` — канон промптов, не DDL).
- Δ каталога = 0 (`services/param_catalog.py` не менялся; метаданные ключа `prompts.summary_cover_style` уже существовали).
- `stash@{0}` (`wip(f1): IA v2…`) цел.
- Секретов в диффе нет; корневые `*.zip` — git-ignored артефакты сборки, не в индексе.

## Вердикт

**К деплою — да.** Critical/High отсутствуют; Medium — тест-качество (не блокирует). Low можно закрыть follow-up'ом.
