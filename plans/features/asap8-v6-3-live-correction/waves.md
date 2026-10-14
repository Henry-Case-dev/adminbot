# waves — план волн ASAP 8 v6.3 Live Correction

- Приоритеты ТЗ: **P0** = B01,B02,B03,B04,B05,B06,B07,B09,B11,B12,U01,U02,U07,U08,V01–V07; **P1** = B08,B10,U03,U04,U05,U06.
- Правило: ≤3 независимых writer-лейнов одновременно; write-scope лейнов внутри волны не пересекаются (файл=owner).
- Общая защита: PRIN-PRESERVE (B12.6) — ни один лейн не делает деструктивных миграций; параллельный CLEAN-1 вне репо-кода не учитывается.

## Wave 0 — сделано (PM-1, read-only + plans)

Карта 222 позиций (gate plan = 0 errors), source-reconciliation, baseline-inventory (пути проверены на f58a644), waves. Gate-барьер: `check --stage plan` exit 0 — выполнен.

## Wave 1 — Backend P0 (3 writer-лейна)

- **Пре-барьер Wave 1 (до старта лейнов, read-only):** REQ-0-1 + REQ-0-BASESHA — владелец **Orchestrator+DevOps**: сбор §0.1 (health, environment-gates, рабочая БД, настройки выбранного чата без секретов, реальные 24/48h данные API/trace/job state/counters/ingest cursor/LLM errors/UI; сверка заявления «26/26» с реальностью) и сверка Git SHA vs deployed SHA через /healthz. Повторная фиксация — в W4-L1 (E2E-VERIFY) перед деплой-вердиктом. Формулировка «отложено на S0» без лейна снята: момент назначен явно.

| Лейн | Требования | Write-scope (файлы) | Зависимости | Критерий готовности |
|---|---|---|---|---|
| W1-L1 CHAT-INTEL | B01 (B01.1–6, REQ-B01-CLARIFY/DOD), B02 (B02.1–5, DOD) | services/direct_chat_service.py, services/memory_maintenance.py, services/mca_experience_jobs.py + миграции таблиц opportunity/intent/experience | нет (от Wave 0) | fixture 100–300 реплик: opportunities+SILENT/REACT/SAY; негативы спама; ≥10 experience-сценариев validated; unit-воронка |
| W1-L2 MEMORY-MIGRATION | B03 (B03.1–5, **B03.4**), B09 (REQ-B09-BODY) | services/summary_memory.py (`_vec_candidates`), services/database.py (purge/retrieval/vec/migration), services/chat_lore.py | нет | scope-до-topK RED/GREEN (displacement), 3500+ факт. задержка, E2E old/new chat retrieval |
| W1-L3 COVER-MODULES | B04 (B04.1–6, DOD), B06 (B06.1–3, DOD), B07 (B07.1–3, BODY) | services/cover_style_jobs.py, services/pg_db.py, services/config_cache.py, services/param_catalog.py, summary-гейты | нет | EDIT-промпт ≤лимита без дублей; preview=production; матрица Summary на реальной генерации; temporal без карточки |

- CAN_PARALLEL_WITH: все три (файлы не пересекаются; БД-миграции согласовать по общему реестру миграций).
- Join barrier: REV-W1 (три среза, `check --stage review --slice …`) → deploy на canary 2.58.79-dev.
- Готовит параллельно read-only: W2-спеки (U01 row-геометрия, FullscreenPolicy-контракт, glass-аудит REQ-U08-1-AUDIT — аудит можно начать сразу, он read-only до CSS).

## Wave 2 — Frontend P0 (3 writer-лейна)

| Лейн | Требования | Write-scope | Зависимости | Критерий |
|---|---|---|---|---|
| W2-L1 SHELL | U01 (+REQ-U01-TESTS), U02, UI-часть B01.4 (per-chat профиль) | app.js::mobileTopnavItems/oversight UI, index.html (mobile-topnav, «Ещё»-popover), app.css header/topnav | W1 не требуется; B01.4 UI — contract с W1-L1 (API-поля) | 320–430+landscape: 4 кнопки целиком, scrollWidth≤viewport, «Ещё»-popover a11y |
| W2-L2 FULLSCREEN | U07 (U07.0–3, HARD), контракты TMA | app.js fullscreen-функции, telegram-init.js, index.html (.header-fs-btn), app.css .fullscreen-mode/.header-compact-v2 | контракт-слот с W2-L1 (fallback в row A) — фиксируется до старта | unit-матрица политик; Windows/Android ручные пробы журналируются; VERIFIED_LIVE — только на реальном клиенте |
| W2-L3 GLASS | U08 (U08.0–5), включая REQ-U08-1-AUDIT/PROBE | app.css glass-токены/.lg-panel*, index.html (#lg-lens, vendor, data-glass-surface), app.js glass-функции | нет жёстких; CSS-конфликты с W2-L1/L2 — владение: glass трогает только `--glass-*`/`.lg-panel*`/data-glass, header-селекторы — W2-L1 | аудит-отчёт до правок; стенд: изгиб линии у края Tier A; два вердикта optical/frost |

- CAN_PARALLEL_WITH: W2-L1 ∥ W2-L2 ∥ W2-L3 при зафиксированном файловом владении app.css (merge-порядок: shell → fullscreen → glass).
- Join barrier: REV-W2 + before/after скриншоты всех ширин (REQ-0-3).

## Wave 3 — P0-хвосты + P1 UI (3 writer-лейна)

| Лейн | Требования | Write-scope | Зависимости | Критерий |
|---|---|---|---|---|
| W3-L1 EDITOR | B05 (B05.1–3, SYM/DOD), U06 (U06.1–3) | app.js coverStyles/polling, index.html cover-editor, app.css .cover-editor-body | контракт B04 из W1-L3 (маршрут preview=production) | Playwright selection 10–15s при polling; RCA-отчёт до фикса; порядок панелей U06 |
| W3-L2 STATUS-ANALYTICS | U03, U04, U05 (incl. U05.3 = 7 виджетов) | app.js status/oversight-блоки, index.html (#status-logs перенос, виджеты), app.css соответствующих секций | данные U05.3 — durable из v6 (есть); сверка с W2-L1 (mobile) | нет дублей сна, фикс 1970, logs только в Статусе, 7 виджетов на реальных данных |
| W3-L3 STORIES+INT-REPORT | B08 (B08.1–4), B11 (SCOPE/CHAIN/E2E) | services/mca_episodes.py, телеметрия-отчёты (read-only запросы + минимальные emitters), plans-отчёт integration-evidence | W1 deploy (реальные прогоны для B11) | 10 эпизодов приёмка; отчёт-цепочка по 10 механизмам; E2E каждому невидимому модулю |

- Join barrier: REV-W3; деплой; начало canary-наблюдения 24–48h для B01/B02 (V01/V02).

## Wave 4 — Close-out (2 writer-лейна + evidence)

| Лейн | Требования | Write-scope | Зависимости | Критерий |
|---|---|---|---|---|
| W4-L1 E2E-VERIFY | V01–V07, REQ-0-3 (ширины/before-after), REQ-EVIDENCE-SELF, повторная фиксация REQ-0-1/REQ-0-BASESHA (§0.1-сбор + SHA-сверка перед деплой-вердиктом) | тесты/фикстуры, скриншоты/видео (маскировка ПДн), ui-acceptance.md, live-canary.md | Waves 1–3 deployed | каждый V — пройден или BLOCKED_ACCESS с точной причиной |
| W4-L2 REL-GATE | B12 (B12.1–6), B10 (R01–R19 + PYTEST), FINAL.1–4, REQ-REL-SHA | validator-скрипт, release-reconciliation.md, review-ledger | W4-L1 частично (данные), waves 1–3 | validator RED при пропусках; f10-расхождение снято; 3 pytest классифицированы; coverage-таблица по всем ID |

- Финальный барьер: `check --stage release --candidate <sha> --deployed-commit <sha>` exit 0 + интеграционный протокол (REQ-0-4). НЕ объявлять COMPLETE при непроверенных Initiative/Experience/Cover/U07/U08/фронте (FINAL.4).

## Блокировки V-сценариев (release blockers)

| V | Блокируется чем | Снимается |
|---|---|---|
| V01 | B01 не готов / нет canary 24–48h | W1-L1 + Wave 4 наблюдение |
| V02 | B02 без ≥10 сценариев / synthetic-счётчики | W1-L1 + W3-L3 evidence |
| V03 | B03.4 displacement не зелёный | W1-L2 |
| V04 | B04 контракт/B05 selection нестабилен | W1-L3 + W3-L1 |
| V05 | U01/U03/U04/U05/B06/B07/B08 любые открыты | W2-L1 + W3-L2 + W3-L3 + B06/B07 (W1-L3) |
| V06 | U07 политика/безопасное окно Windows | W2-L2 + реальные клиентские пробы (не mock-only, U07.3b) |
| V07 | U08 Tier A/B не пройдены на стенде | W2-L3 |

## Риски

1. **app.css — общий файл трёх FE-лейнов** (W2). Смягчение: файловое владение + merge-порядок, запрет на рефакторинг чужих селекторов.
2. **B01.4 UI ↔ W1-L1 API** — контракт полей настроек фиксировать до Wave 2 (Architect при неоднозначности).
3. **U07 Windows VERIFIED_LIVE** требует ручных клиентских проб — планировать ранний ручной тест (U07.3b) сразу после W2-L2, не в Wave 4.
4. **7 виджетов U05.3** — самый объёмный P1; при нехватке данных честный unknown/restricted (ТЗ запрещает демо-картинки).
