# Scanner-аудит ПАКЕТА round10.25 (финал F2 + hotfix5 + F3), повторный (Step 6, 22.09.2026)

- **Диапазон:** `f2328fb..HEAD` (HEAD `3caddeb`), т.е. весь недеплоенный пакет из трёх единиц работы,
  деплоящийся ОДНИМ пакетом.
- **Финальные коммиты (код):** F2 → `d2df8ca` (ревью-фиксы `0f227a5`, `d2df8ca`; база `e895726`);
  hotfix5 → `412f844` (ревью-фиксы `cbaec05`, `412f844`; база `b3fb6a5`);
  F3 → `4f31197` (ревью-фиксы `fb49f29`, `4f31197`; база `76a6c40`).
- **Почему повторный:** базовые отчёты писались на базах и НЕ покрывали правки ревью — блокирующее расхождение.
- **Метод:** diff-based аудит именно ревью-фикс-коммитов + полные файлы финального состояния; целевые тесты; проверка
  арифметики и текста без доверия сообщениям коммитов.
- **Дерево:** чистое (`git status -s` пуст), `stash@{0}` (F1-WIP) цел, трекаемых `*.zip` нет.

## Вердикт: к деплою — ДА

**Critical 0 / High 0.** Все ранее найденные Medium (F2 M-1/-2/-3, hotfix5 M-1, F3 M-1) — либо закрыты,
либо (M-2/M-3) не блокируют деплой. Новых Critical/High ревью-фиксы не внесли. Блокеров возврата @Builder нет.

## Таблица находок (финальное состояние)

| Severity | Кол-во | Позиции |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium | 1 | **M10.25F2-3** (цена преломления не измерена; A не ограничен одним узлом) — остаточный, не блокер |
| Low | 5 | L10.25F2-1 (sticky-header alpha без blur), L10.25F2-2 (тавтологичный `assert "240" in APP_JS`), L10.25F2-4 (README «Тестов: 5936»), **NEW-L1** (iOS Edge `EdgiOS` не покрыт WebKit-gate), **NEW-L2** (ResizeObserver не вешается на стартовые allow-узлы до следующего reconcile) |
| Info | 4 | I-1 (matrix «0» не воспроизведён — нет playwright), I-2 (5 падений pytest — env aiogram, вне пакета), I-3 (`_onResize` без троттлинга), I-4 (downgraded-A сохраняет `inset 0 -1px 0`) |

## Статус ранее найденных Medium (проверка по факту)

### F2 M-1 — «min-240 необратим/не покрывает route-узлы» → **ЗАКРЫТ**
- Доказательство: `web/app.js:8122-8141` `reconcileLiquidGlass` больше НЕ переписывает opt-in `data-glass`, а
  ставит/снимает `data-glass-downgraded` (`setAttribute`/`removeAttribute`); CSS
  `app.css:978-981 [data-glass="a"][data-glass-downgraded="1"]{backdrop-filter:blur(...)}` — понижение визуально
  эквивалентно B и снимается при росте → A↔B обратимо.
- Транзитивность: watch `activeTab` → `$nextTick(_lgSchedule)` (`app.js:2041-2044`), `_initLiquidGlassObserver`
  (`MutationObserver` на `#app`, childList/subtree/attributeFilter) + `ResizeObserver` на allow-узлы, `_onResize`
  вызывает reconcile (`app.js:2086-2088`). Узлы Сводки/графика появляются в DOM позже — observer ловит.

### F2 M-2 — «WebKit: потеря blur на уровне A» → **ЧАСТИЧНО ЗАКРЫТ (остаток — Low, не блокер)**
- Доказательство: `app.js:8004-8014` добавлен UA-gate:
  `if (ua && /AppleWebKit/i.test(ua) && !/Chrome|Chromium|Edg|OPR/i.test(ua)) return false;` — общий
  WKWebView (iOS Safari, CriOS, FxiOS, OPiOS) уводится на уровень B.
- **Остаток (NEW-L1):** UA iOS Edge = `EdgiOS/…` содержит подстроку `Edg` → исключается из негативного
  фильтра и НЕ гейтится. Воспроизведено прогоном regex: `iOS Edge => gate=false` (т.е. уровень A не отключён),
  тогда как iOS Safari/Chrome/Opera → `gate=true` (B). На WKWebView `CSS.supports('backdrop-filter','url(...)')`
  возвращает true (посылка Reviewer), поэтому на iOS Edge blur может быть потерян. Ниша узкая, поведенческий
  риск — читаемость, не данные → Low. Требует проверки на устройстве (в CI/локально не воспроизводимо).

### F2 M-3 — «цена преломления не измерена / A не ограничен» → **ЧАСТИЧНО ЗАКРЫТ (остаточный Medium)**
- Часть (а) «240px-отсечка реально не работала из-за M-1» — **закрыта**: матрица теперь проверяет min-сторону
  каждого allow-элемента с преломлением (`tools/ui_round1025_matrix.py:...` в `_f2_failures`: `active` → `minSide < 240`
  → failure), плюс `TestMatrixF2Probe.test_catches_small_displaced_element` в python-тесте.
- Часть (б) «цена `feTurbulence/feGaussianBlur/feDisplacementMap` не измерена; A не ограничен одним узлом» —
  **ОТКРЫТА**: бюджета FPS кадров в матрицу не добавлено, `data-glass="a"` по-прежнему на 3 узлах
  (`web/index.html:1420`, `2762`, `2930`). Смягчено документацией (ADR-1025-9 D2 — признано приближением) и
  троттлингом observer ≥250 мс (D-2). Не блокер (фон, desktop Chromium), но остаётся Medium.

### hotfix5 M-1 — «ретрай ×2 умножается на внутренний 429/503 → до 4 вызовов/~4×окна» → **ЗАКРЫТ**
- Доказательство: `generate_image_verbose` вызывает `generate(..., retry=False)` (`image_generation.py:897-901`),
  `retry=False` пробрасывается в `_generate_post`/`_generate_get`/`_download_bytes` → `_request_with_retry(..., max_retries=0)`
  (`image_generation.py:460`, `limit = _RETRY_MAX if max_retries is None else max(0,int(max_retries))`, цикл `attempt < 0` не идёт).
  Внутренний HTTP-повтор на период обложки отключён → на попытку ≤ 2 сетевых вызова, повторами владеет только внешний цикл.
- Селективность: `is_transient_reason` (`image_generation.py`) — повтор только `timeout`/`network`/`unreachable`/`429/502/503/504`;
  детерминированные (`unauthorized`/`bad_request`/`bad_json`/`too_large`/…) → `break` после 1-й попытки (`:918-919`).
- Дедлайн попытки: `asyncio.wait_for(generate(...), timeout=окно)` (`:897-901`) — POST+скачивание ограничены одним окном,
  поэтому worst-case = `attempts × окно + backoff` (2×180+2 = 362 c), как и заявлено в `settings.py`/`.env.example`.
- `asyncio.CancelledError` (BaseException) не глотается `except Exception` → отмена/cleanup корректны.
- Поведенческий тест подтверждает: `test_timeout_first_attempt_then_success_rich` (ровно 2 попытки, `retry is False`),
  `test_deterministic_failure_single_attempt` (1 попытка), `test_attempt_bounded_by_window_deadline` (обе «зависшие»
  попытки уложились в дедлайн). Прогнаны локально — зелёные.

### F3 M-F3-1 — «guard несохранённых правок не видит `blockDrafts`» → **ЗАКРЫТ**
- Доказательство: `web/app.js:2481-2516` `hasUnsavedEdits` теперь проверяет `blockDrafts` (любой ключ = правка;
  `blockDrafts` заполняется ТОЛЬКО на взаимодействие — `index.html:335/391/785 @input`, `setBlockBool:4094-4100`),
  а также `ownKeyDraft`, `personaDraft` (сравнение с baseline `personaMeta.values`) и `dossierDraft`
  (сравнение с `dossierData.manual_traits`, включая очистку до `''`). `setActiveChat` (`:2521-2532`) вызывает guard
  ДО сброса (`this.blockDrafts = {}` идёт на `:2572` только после подтверждения). JS-тест
  `tests/js/round1025_scope_selector_test.js` проверяет поведенчески (`blockDrafts`/`ownKeyDraft`/`persona`/`dossier` → confirm).

## Новые/остаточные Low и Info (финальное состояние)

- **[L10.25F2-1] `web/static/app.css:745-749`** — `header.header-sticky{background:var(--glass-bg-strong)}` (alpha 0.85)
  без blur; контент при скролле просвечивает, против комментария. Остаётся открытым (ревью-фиксы не трогали
  токен шапки). Не блокер.

- **[L10.25F2-2] `tests/test_webapp_design_tokens_round1025.py:343`** — `assert "240" in APP_JS` тавтологичен
  (в `app.js` много «240»). Частично закрыт: добавлены реальные проверки
  (`test_downgrade_reversible_and_transitive`, `test_webkit_ua_gate`) и `TestMatrixF2Probe`
  (`test_catches_small_displaced_element` → ждёт failure по «240»). Остаётся тавтологичная строка.

- **[L10.25F2-4] `README.md:5`** — «Тестов: 5936» устарело (фактически pytest 8146 passed).
  Ревью-фиксы README не трогали → открыт.

- **[NEW-L1] iOS Edge (`EdgiOS`) не покрыт WebKit-gate** — см. F2 M-2, воспроизведено regex-прогоном.

- **[NEW-L2] `web/app.js:8163-8181`** — `_initLiquidGlassObserver()` вызывается ПОСЛЕ стартового
  `reconcileLiquidGlass()` (`mounted` `:2111-2112`), поэтому `_lgResizeObserver` создаётся уже после обхода
  стартовых узлов и не подписывается на них до следующего reconcile (resize/мутация). Влияние ограничено:
  реверсия A↔B при ресайзе окна работает (листенер `resize`), изменение размера узла без ресайза/мутации — редкий
  случай. Не блокер.

- **[I-3] `web/app.js:2086-2088`** — `_onResize` вызывает `reconcileLiquidGlass()` напрямую, без троттлинга
  (в отличие от `_lgSchedule`). На потоке resize-событий — повторные `querySelectorAll`, но bounded и дёшево.

- **[I-4] `web/static/app.css:965-981`** — у пониженного A (`data-glass-downgraded`) остаётся лишняя тень
  `inset 0 -1px 0 var(--glass-highlight-soft)` от уровня A (правило понижения переопределяет только
  `backdrop-filter`, не `box-shadow`) → микро-расхождение с уровнем B. Косметика.

- **[Info] i-1** Матрица `tools/ui_round1025_matrix.py` (10 вьюпортов, chat-scope, local_admin 320/360/390,
  red-proof) — **не воспроизведена**: `playwright` в окружении отсутствует (`ModuleNotFoundError`).
  Заявления коммитов «matrix 0» / «red-proof 10 FAIL» принимаются на доверии, не подтверждены.
  Структурно F3-проверки присутствуют (`scrollWidth>innerWidth+1`, вариант local_admin, кнопка возврата).

- **[Info] i-2** Локальный полный `pytest`: **8146 passed / 5 failed / 1 skipped** (118.16 s). 5 падений —
  окружение `aiogram 3.29.1` без `InputRichMessageMedia` (`services/telegram_send.py:177`), в файлах
  `tests/test_outgoing_guard_round1022.py`, `tests/test_summary_cover_round1023.py`, которые пакет НЕ трогал
  (`git diff --name-only` пуст) → **не регрессия**. Целевые тесты пакета: **152 passed** (hotfix5 + image_generation_1023
  + webapp_dm_ui + scope_selector + design_tokens).

## Свежая проверка Critical/High (финальное состояние)

- **CSP/zero-build:** новых внешних ссылок/data-URI/WebGL/библиотек нет; `#lg-displace` — inline SVG, один id;
  `feDisplacementMap` применён через `backdrop-filter` (фон), текст внутри `[data-glass="a"]` не искажается.
- **RBAC/DELETE override:** серверный гейт `web/api/routes.py:868-876` (группа: `is_global_admin or is_local_admin`;
  DM: только `is_dm_owner`). JS-guard `resetChatOverride` приведён к паритету
  `!(isGlobalAdmin || isDmCtx() || isLocalAdminCtx())` (`app.js:3333`) и кнопка показывается тем же условием
  (`index.html`, 8 мест). Эскалации нет; снятие override — `overrides.pop(key)` + merge `meta`, не factory-reset.
- **Секреты/R17 (hotfix5):** WARNING-логи несут только `reason`/`reason_class`/`provider`(host)/`chat_id`/`latency_ms`;
  `redact_url`+`redact_key` на месте; новых источников данных нет. Секретов в диффе нет (скан-проба пуста).
- **Гонки/stale scope (F3):** `scopeEpoch++` + `_scopeGuard` не тронуты ревью-фиксами; правки ревью только
  расширяют guard черновиков. Остаточное F0-окно (`persistItems` снимает epoch после await) — follow-up F0, не этот пакет.
- **Контраст/читаемость:** D-1 подтверждён численно: `--text-3 #A2B0C6` vs худший фон стекла `rgb(27,62,69)` = **5.25:1**
  (было 4.50), `--err-text #FCA5A5` = **6.07:1** (было 4.17) — совпадает с заявлением коммита. Tailwind-утилиты
  перекрыты в `app.css:473-476`, `app.css` грузится после `tailwind.css` (`index.html:21,24`).
- **Δ DDL=0, Δ каталога=0:** `git diff --name-only f2328fb..HEAD -- migrate_history/* *.sql docker/* services/param_catalog.py` пуст;
  `test_new_keys_not_in_param_catalog` подтверждает env-only ключи.
- **Обязательные инварианты:** `git diff --check f2328fb..HEAD` — чисто; `stash@{0}` цел; zip в git нет.

## Регрессии

**Не обнаружено.** Пакет не касается `handlers/**`, `bot.py`, `database/**`, `media_download`, F0-слоя,
Эпик 2. Полный pytest зелёный, кроме 5 предсуществующих env-падений (вне пакета). JS-юниты: **25/25 OK**
(`node --check web/app.js` OK, `SCOPE-SELECTOR-OK`, `JS-UNIT-OK`). F1 shell/safe-area, П0-fix, hotfix-медиа,
hotfix3, hotfix4 — не задеты (файлы вне диффа).

## Цифры (факт, воспроизведено)

- `py -m pytest -q` → **8146 passed / 5 failed / 1 skipped** (5 — env aiogram `InputRichMessageMedia`).
- Целевые: `py -m pytest <5 файлов> -q` → **152 passed**.
- `npm`-независимые JS: все `tests/js/*.js` → **25/25 OK**.
- Контраст-арифметика пересчитана (WCAG relative luminance) — совпала с заявлением.
- Regex-проба WebKit-gate — iOS Edge не гейтится (NEW-L1).
- Матрица Playwright — **не подтверждена** (нет playwright).

*Отчёт-спутник: базовые — `round1025_f2_scanner_audit.md`, `round1025_hotfix5_scanner_audit.md`,
`round1025_f3_scanner_audit.md`.*
