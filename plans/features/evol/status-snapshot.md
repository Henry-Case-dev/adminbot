# EVOL — статус по требованиям (снимок 31.10.2026)

Карта: `plans/features/evol/requirements-map.json` (53 обязательных требования: EVOL-001..045 + EVOL-DoD + 4 дельты аддендума 31.10
`EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT`, `EVOL-FACTCHECK-CRITICAL`, `EVOL-GLASS-SEAM` + три поставленных в очередь поручения 31.10
`EVOL-SRC-READER`, `EVOL-COG-MAP`, `ASAP-FC-ADMISSION-01`).
Ветка реализации: `evol/impl`, вершина `18baa36b`. Деплой не выполнялся.

## Как записан статус

Словарь `requirements_gate.py` строгий: `PENDING | BUILDING | REVIEW | VERIFIED | FAILED | BLOCKED_REAL_HUMAN_GATE | READY_FOR_LIVE`.
Поэтому ревью-принятые, но **не задеплоенные** требования держат `status: PENDING` + `review_verdict: "APPROVED"`,
`review_candidate`, `review_scope`, `review_note` и привязку доказательств (`evidence[]`: `ref`, `observation`, `type`,
`artifact_path`, `artifact_branch`, `artifact_sha256`, `candidate_commit`). `VERIFIED` сознательно не выставлен.
Артефакты-отчёты лежат в ветке `evol/impl` (`plans/features/evol/audit/w*.md`) и в `master` ещё не влиты.

## Таблица

| Задача | Backend | UI | Ревью | Деплой |
|---|---|---|---|---|
| EVOL-001 | PASS (`4fcbf684`+`98d16b94`) | PASS (живой рендер Playwright) | APPROVED | не задеплоено |
| EVOL-002 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-003 | PASS (`98d16b94`) | PASS (focus trap в review-fix) | APPROVED | не задеплоено |
| EVOL-004 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-005 | PASS (`98d16b94`) | PASS | APPROVED | не задеплоено |
| EVOL-006 | PASS (`4fcbf684`+`98d16b94`) | n/a (промпт/данные) | APPROVED | не задеплоено |
| EVOL-007 | PASS (`3d52e487`) | n/a (виджет закрыт в 001..005) | APPROVED | не задеплоено |
| EVOL-008 | PASS (`3d52e487`) | n/a | APPROVED | не задеплоено |
| EVOL-009 | PASS (`a02aca0c`) | n/a (данные, не экран) | APPROVED | не задеплоено |
| EVOL-010 | PASS (`0e853f7f`) | n/a | APPROVED | не задеплоено; live-проверка после релиза |
| EVOL-011 | PASS (`dc1fdba6`) | n/a | APPROVED | не задеплоено |
| EVOL-012 | PASS (`44437903`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-013 | PASS (`dc1fdba6`) | n/a | APPROVED | не задеплоено |
| EVOL-014 | PASS (`9eeb3532`+`a02aca0c`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-015 | PASS (`e7443fad`) | n/a | APPROVED | не задеплоено |
| EVOL-016 | PASS (`44437903`+`011fe8ff`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-017 | PASS (`be5ad652`) | PASS (`be5ad652`) | APPROVED | не задеплоено |
| EVOL-018 | PASS (док-контракт `95b8d275`+`c7851980`) | n/a | APPROVED | не задеплоено |
| EVOL-019 | PASS (`4fcbf684`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-020 | PASS (`98d16b94`; F1/F2 в `18baa36b`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-021 | PASS (`4fcbf684`) | **PENDING REVIEW** (`18baa36b`) | backend APPROVED, UI в процессе | не задеплоено |
| EVOL-022 | n/a (фундамент) | PASS (слой токенов, `33a14034`) | APPROVED | не задеплоено |
| EVOL-031 | PASS (`28d55bd1`…`7492d325`) | n/a (UI-карточка удалена) | APPROVED | не задеплоено; live-проверка после релиза |
| EVOL-032 | n/a (фундамент) | PASS (`33a14034`) | APPROVED | не задеплоено |
| EVOL-023..030 | не начато | не начато | — | — |
| EVOL-033 | не начато | не начато — **интеграционный гейт** | — | — |
| EVOL-034..045 | не начато | не начато | — | — |
| EVOL-DoD | не достигнуто (нужен релиз + EVOL-033) | — | — | — |

Итого привязано доказательств: **24 требования** (001..022, 031, 032). Не начато: 23 требования (023..030, 033..045) + DoD.
Дополнительно из аддендума 31.10: 3 требования в работе (`BUILDING`), 1 не начато (`PENDING`) — доказательств пока нет.
Дополнительно из поручений 31.10: 3 требования поставлены в очередь (`PENDING`, доказательств нет) — `EVOL-SRC-READER`, `EVOL-COG-MAP`,
`ASAP-FC-ADMISSION-01`. Итоговый знаменатель обязательных требований: **53**, из них с привязанными доказательствами — 24.

## Аддендум 31.10.2026 — четыре дельты активного эпика (OI-2026-10-31-EVOL-ADDENDUM)

Источник: `plans/current_task.md` строки **911-1155** (социальный контекст §§1-3, видео §4, критический фактчек §5,
стеклянный шов EVOL-032 §6). Разложено в карте: 145 строк (4 `required` + 125 `duplicate` + 16 `context`),
все строки диапазона классифицированы. Новые слайсы добавлены в `slice-graph.json` (волна W5) — это дельты, а не новый эпик.

| Слайс | Что закрывает | Зависит от (уже поставлено) | Статус |
|---|---|---|---|
| `EVOL-SOCIAL-FRAME` | SocialTurnFrameBuilder (0 LLM) из message_identity/quote_resolver/canonical_context → существующие L1/Decision/Writer; 10 сценариев §3 | `EVOL-B-QUOTE`, `EVOL-B-SMARTCACHE`, `EVOL-B-PROMPTREG`, `EVOL-B-PROMPTCONV`, `EVOL-W0-AUDIT` | `BUILDING` (реализация+тесты в рабочей копии, не закоммичено) |
| `EVOL-VIDEO-INTENT` | единый VideoIntent, связка «просьба → отдельный репост», pending TTL, single-flight, summary ≠ download; 8 сценариев §4.5 | `EVOL-B-QUOTE`, `EVOL-W0-AUDIT` | `BUILDING` |
| `EVOL-FACTCHECK-CRITICAL` | отдельная секция «Критический разнос» из того же checked verdict, директива в реестре версий промптов, настройка в модуле «Фактчек», семантический guard; 8 кейсов §5.4 | `EVOL-B-PROMPTREG`, `EVOL-B-PROMPTCONV`, `EVOL-W0-AUDIT` | `BUILDING` (реализация закоммичена `d036707a`, независимого вердикта ревью в карте нет) |
| `EVOL-GLASS-SEAM` | первопричина прямого шва в общем стеклянном слое + before/after в движении (normal/alert, desktop/mobile), внутри приёмки EVOL-032 | `EVOL-UI-HEALTHGLASS` | `PENDING` (не начато) |

Рёбра графа: все четыре добавлены в `EVOL-RELEASE.depends_on`; `EVOL-GLASS-SEAM` дополнительно в `EVOL-UI-FULLDOD.depends_on`
(финальный UI-DoD обязан включать устранение шва). Доказательств (`evidence[]`) у новых требований нет — коммита кандидата ещё нет,
поэтому `BUILDING`/`PENDING`, без `VERIFIED` и без `review_verdict`.
Оговорка по §5.3: UI-часть настройки живёт в `web/app.js` — этот файл остаётся за UI-цепочкой, отдельного параллельного писателя нет
(зафиксировано в `depends_note` узла).

## Поручения 31.10.2026 — SRC/COG и ASAP-FC-ADMISSION (поставлены в очередь, не начаты)

Два отдельных более поздних поручения владельца, не входящих в аддендум 911-1155. Обе записи зарегистрированы в
`plans/progress_scope.json` как `OI-2026-10-31-EVOL-SRC-COG` и `OI-2026-10-31-ASAP-FC-ADMISSION` (обе `reconciled: false` —
глобальный индекс обновляет Orchestrator; здесь только карта/граф/снимок).

| Слайс (req_id) | Строки источника | Что закрывает | Зависит от (уже поставлено) | Волна | Статус |
|---|---|---|---|---|---|
| `EVOL-SRC-READER` | 1158-1235 (§1) | Source Code Reader: discovery → locator → verified fetch → bounded follow-up → Evidence Contract, безопасность (§1.2), поведение при неоднозначности (§1.3), правила доказательности §1.4, 7 конечных сценариев §1.5 | `EVOL-W0-AUDIT`, `EVOL-B-QUOTE`, `EVOL-B-TELEMETRY`, `EVOL-B-PROMPTREG`, `EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT` | W6 | `PENDING` (конец очереди) |
| `EVOL-COG-MAP` | 1238-1348 (§2) | Когнитивная карта вместо «Графа связей»: адаптер данных §2.3, визуальная система §2.4, легенда/LOD §2.4, drilldown к источнику §2.5, паритет старого графа §2.6, mobile-first embedded+fullscreen §2.7, производительность §2.8, проверки §2.9; `/api/memory/graph` и `/api/memory/stats` сохраняются | `EVOL-UI-FULLDOD`, `EVOL-UI-HEALTHGLASS` (EVOL-032), `EVOL-UI-STORIES` (EVOL-021), `EVOL-UI-DESIGN` (EVOL-022), `EVOL-B-EXP`, `EVOL-B-FACTS`, `EVOL-B-MEMCYCLES`, `EVOL-B-TELEMETRY`, `EVOL-SRC-READER` | W7 | `PENDING` (конец очереди) |
| `ASAP-FC-ADMISSION-01` | 1363-1426 (§1-§5) | Механизм допуска фактчека (явное намерение важнее «ерундовости», три различаемых исхода, §2) + cooldown после ложного отказа (§3 этапы A-E), 8 детерминированных сценариев §5 | `EVOL-W0-AUDIT`, `EVOL-FACTCHECK-CRITICAL`, `EVOL-B-QUOTE`, `EVOL-B-PROMPTREG`, `EVOL-SOCIAL-FRAME`, `EVOL-VIDEO-INTENT` | W5-ADMISSION | `QUEUED` → в карте `PENDING` |

Порядок по указанию владельца: **ASAP-FC-ADMISSION-01** берётся сразу после завершения фактических правок фактчека и Reviewer-приёмки
`EVOL-FACTCHECK-CRITICAL` (не параллельно, без повторного большого аудита). **EVOL-SRC-READER** и **EVOL-COG-MAP** — строго в конец
очереди, после текущих UI-волн; оба добавлены в `EVOL-RELEASE.depends_on`, чтобы релиз не опережал поручение. Доказательств у трёх
новых требований нет: `PENDING`, без `VERIFIED` и без `review_verdict`.

Классификация строк 1158-1430: **124** записи (88 `required` + 23 `duplicate` + 13 `context`); непокрытых строк нет.
Прозаические абзацы (1225, 1242/1244/1246/1248, 1302, 1339-1347, 1395/1397/1399/1401/1403, 1360) не входят в построчный инвентарь
гейта, поэтому их обязательства закреплены в `acceptance` соответствующих req и в `reason` ближайших строк — проверять их нужно по
тексту acceptance, а не по числу строк.

## Гейт плана

`py C:\Users\main\.config\opencode\tools\requirements_gate.py check --map plans/features/evol/requirements-map.json --stage plan --repo .`
→ **EXIT 0**, `stage=plan inventory=530 manual=279 scoped=0 errors=0`.
Запускать **из корня основного репозитория** (`C:\Code\Python\adminbot`): `plans/current_task.md` в `.gitignore` и в worktree отсутствует,
иначе гейт даёт `source not present` и лавину ложных «gone or edited».

Состав ошибок сейчас — **0**. Ранее падавшие 124 ошибки `source item not mapped` для строк **1166-1428** закрыты этим проходом:
строки 1158-1430 разложены как `OI-2026-10-31-EVOL-SRC-COG` (SRC/COG) и `OI-2026-10-31-ASAP-FC-ADMISSION`.
Ошибок внутри 911-1155 — **0**; расхождения sha источника — **0**; ошибок графа (циклы/пересечение write_scope/отсутствующие узлы) — **0**.
Прежние 103 ошибки (1 × `authoritative source changed` + 102 × `source item not mapped` в 911-1155) закрыты.

## Что дальше

1. Orchestrator: перенести обновлённую карту в ветку `evol/impl` (в `master` каталог `plans/features/evol/` сейчас **untracked**, правка живёт только в рабочей копии).
2. Orchestrator: выставить `reconciled: true` для `OI-2026-10-31-EVOL-SRC-COG` и `OI-2026-10-31-ASAP-FC-ADMISSION` в `plans/progress_scope.json`
   (карта/граф/снимок уже покрывают оба поручения; строки 1158-1430 классифицированы, гейт плана EXIT 0) и учесть 3 новых требования в знаменателе прогресса.
3. Ревью `18baa36b` → снять `ui_review: pending` у 014/019/020/021 и привязать UI-доказательства.
4. Затем EVOL-033 как интеграционный гейт, после него — релиз и `VERIFIED` (для 010/031 плюс live-проверка на проде).
5. Порядок очереди после текущих волн: `ASAP-FC-ADMISSION-01` (сразу после Reviewer-приёмки `EVOL-FACTCHECK-CRITICAL`) → `EVOL-SRC-READER` (W6) → `EVOL-COG-MAP` (W7) → `EVOL-RELEASE`.
   Параллельно эти три слайса с текущими писателями не запускать: у SRC/COG пересечение по `handlers/**`, `web/**`, у ASAP — по `services/factcheck_*`.

