# AdminBot — Метрики раундов (plans/metrics.md)

Индекс метрик процесса OpenSpec по раундам (epic-level). Источник данных —
`plans/MEMORY.md`, `plans/backlog.md`, `plans/reports/round*`, `plans/ARCHITECTURE.md`,
git-история. Таблица ведётся @Memory на Шаге 10 (финал).

Обозначения: **R-iters** — итерации @Reviewer (Rejected → Approved);
**Scanner C/H** — финальные Critical/High @Scanner; **Rework** — циклы доработок @Builder;
**Тесты** — `база → итог (+Δ)`; **Techdebt** — открытый техдолг финала раунда.

## Сводная таблица по раундам

| Раунд | Эпик / Фичи | Длительность | R-iters | Scanner C/H (финал) | Scanner C/H/M/L (итер. 1) | Rework | Тесты (база → итог, Δ) | Каталог (REGISTRY / Settings / categorized) | Commit | Деплой | Health | Techdebt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **10.13** | Cognition / Sleep / Memory Refactor — 8 фич: F1 4D-память, F2 belief decay+resurrection, F3 глубокий сон+роутер, F4 UI провайдеров, F5 дашборд Cognition+виджет, F6 EKG+фикс логов, F7 справка+README, F8 ирония/досье (T-1417…T-1476, 60 задач) | одна сессия **13.09.2026** (00:52 → 08:50 +1200, ~8 ч) | **2** (1 Rejected → 1 Approved) | **0 / 0** | 0 / **1** / **4** / **9** | **2** (после Reviewer Rejected; после Scanner High) | 5211 → **5392** (**+181**) | 405 / 377 / 381 → **427 / 399 / 403** (GROUPS 90, mapped 88, TAB_RULES 19) | **`8800bba`** | ✅ прод `708f7df..8800bba` (fast-forward), admin_bot active (PID 1629874) | **200** `{"status":"ok"}` | **5 Low** (`S10.13-9`, `-11`, `-13`, `-14`, `-6b`) |
| **10.14** | Самосознание и Личность бота — 8 фич: F1 anti-echo-self-reply, F2 persona-storage-core, F3 persona-ui-tab, F4 persona-traits-ribbon, F5 settings-persistence-audit, F6 help-guide-integration, F7 status-layout-reorder, F8 self-reflection-llm-provider (T-1477…T-1548, 72 задачи) | одна сессия **13.09.2026** (09:01 → 21:13 +1200, ~12 ч) | **2** (1 Rejected → 1 Approved) | **0 / 0** | 0 / 0 / **2** / **5** | **2** (после Reviewer Rejected; после Scanner Mediums) | 5392 → **5589** (**+197**) | 427 / 399 / 403 → **435 / 406 / 411** (GROUPS 90, mapped 88, TAB_RULES 19) | **`eb2a232`** | ✅ прод `8800bba..eb2a232` (fast-forward), admin_bot active (PID **1774527**) | **200** `{"status":"ok"}` | **Low 2** (`R10.14-4`, `R10.14-7`) + **L5** + **Info 2** |
| **10.15** | Багфиксы Графа памяти, Воркера Сна и Ностальгии + Гибридный Tool Calling — 9 фич: F1 graph-sampling-centrality, F2 graph-frontend-physics-search, F3 sleep-unblock-diagnostics, F4 nostalgia-prompt-revamp, F5 status-graph-ui-relocation, F6 command-prefix-persona-routing, F7 guide-rewrite-persona, F8 hybrid-tool-calling, F9 recent-history-tool (T-1549…T-1624, 76 задач) | одна сессия **13–14.09.2026** (798e044 21:24 → d01a539 04:27 +1200, ~7 ч) | **2** (1 Rejected → 1 Approved) | **0 / 0** | 0 / 0 / **3** / **6** | **2** (после Reviewer Rejected; после Scanner Mediums) | 5589 → **5774** (**+185**; итер.1 5761) | 435 / 406 / 411 (Δ=0; GROUPS 90, mapped 88, TAB_RULES 19) | **`d01a539`** | ✅ прод `eb2a232..d01a539` (fast-forward; ручная разблокировка дрейфа `info_text.md`), admin_bot active (PID **1860445**) | **200** | **Low 3** (`R10.15-4`, `-10`, `-11`) + **Info 3** (в т.ч. repo-wide **R17-долг**) |
| **10.16** | «Download-Guide-MobileAudit» — багфиксы скачивания + доставка Гайда + полный аудит 10.13–10.15 + мобильный мини-апп + ротация секрета — 5 фич: F1 download-fix, F2 guide-delivery, F3 audit-recent-epics, F4 miniapp-mobile, F5 security-rotation-finalize (T-1625…T-1665, 41 задача) | одна сессия **14.09.2026** (Step 0 → Step 10 @Memory) | **2** (1 Rejected → 1 Approved) | **0 / 0** | 0 / **1** / **1** / **6** | **2** (после Reviewer Critical; после Scanner High) | 5774 → **5936** (**+162**; итер.1 5910) | 435 / 406 / 411 (Δ=0; GROUPS 90, mapped 88, TAB_RULES 19) | **`eb3fd4a`** | ✅ прод `d01a539..eb3fd4a` (fast-forward), admin_bot active (PID **1976836**) | **200** | **Low 1** (`S10.16-9`) + **WONTFIX 3** (`S10.13-9`, `S10.13-11`, `R10.14-4`) + **R17-долг** `current_task.md` |
| **10.17** | «Mobile-Download-Badges» — мобильный миниапп/DNS-диагностика + tool-download quality + countdown-бейджи Сна + **ОТМЕНА** ротации SSH + warnings-hygiene — 5 фич: F1 miniapp-mobile-dns, F2 tool-download-quality, F3 sleep-badge-countdown, F4 ssh-rotation-cancelled, F5 warnings-hygiene (T-1666…T-1702, 37 задач) | одна сессия **14.09.2026** (Step 0 → Step 10 @Memory) | **2** (1 Rejected → 1 Approved) | **0 / 0** | 0 / 0 / **1** / 2 | **2** (после Reviewer 3 Medium) | 5936 → **6007** (**+71**) | 435 / 406 / 411 (Δ=0; GROUPS 90, mapped 88, TAB_RULES 19) | **`b6c153f`** | ✅ прод `eb3fd4a..b6c153f` (fast-forward), admin_bot active (PID **2016726**) | **200** | **Low 1** (`S10.17-2`) + **Info 3** (`S10.17-4/-5/-6`) + **WONTFIX brotli**; **CANCELLED** ротации SSH |
| **10.18** | «Memory-Graph-Sleep-BetterStack bugfixes» — BetterStack US-регион (401) + разблокировка Сна/каскада/бейджей + апгрейд графа (скоринг/плотность/физика) + пенализация мета-фактов + Матрица ролей + **рассинхрон UI↔воркеры** — 7 фич: F1 betterstack-us-region-401, F2 sleep-manual-cascade-badges, F3 graph-density-scoring-stoplist, F4 graph-physics-stabilization, F5 metafact-penalty-extractor-prompt, F6 role-matrix-settings-actualization, F7 settings-worker-sync (T-1703…T-1777, 75 задач) | _заполнит Step 10_ | _—_ | _—_ | _—_ | _—_ | 6007 → **_итог_** | 435 / 406 / 411 → план **437 / 407** (GROUPS 90, mapped 88, TAB_RULES 19; при отказе от F5-флага 436/406) | _—_ | _—_ | _—_ | **NARROWED** `risk-catalog-delta-drift-round1018` — F3-флаг `graph_scoring_v2_enabled` **снят** (ADR-1018-3 **D7**: флаг не вводится, поведение безусловно; каталог-Δ=0); остаётся пин-тест F6 §6 `436` vs §5 `437` и дрейф backlog/нумерации ADR (закрыть на Merge/Step 10) + запланированные остаточные (см. раздел «Заготовка 10.18») |
| _…_ | — | — | — | — | — | — | — | — | — | — | — | — |

## Детали раунда 10.13 (13.09.2026)

- **Эпик:** `Epic: Cognition-Sleep-Memory Refactor round1013` / милстоун `round1013-epic-cognition`.
- **Фичи (8, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `cognition-4d-memory-round1013` — T-1417…T-1423.
  - F2 `cognition-belief-decay-round1013` — T-1424…T-1433.
  - F3 `cognition-deep-sleep-round1013` — T-1434…T-1442.
  - F4 `cognition-llm-providers-round1013` — T-1443…T-1447.
  - F5 `cognition-dashboard-round1013` — T-1448…T-1458.
  - F6 `cognition-ekg-logs-bugfix-round1013` — T-1459…T-1464.
  - F7 `cognition-user-guide-round1013` — T-1465…T-1467.
  - F8 `cognition-irony-dossier-round1013` — T-1468…T-1476.
- **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (BLOCKER-1 [Critical] T-1439 — роутер
  воркеров не подключён; BLOCKER-2 [High] — ностальгия F5); итерация 2 — **APPROVED**.
  @Scanner итерация 1 — 0 Critical / 1 High (неэкранированный автор RAG) / 4 Medium / 9 Low;
  итерация 2 — **CLEAN 0/0/0** (закрыты High `S10.13-1` и Medium `S10.13-2/-3/-4/-5`),
  остаются **5 Low**. @Builder — **2 цикла реворков**.
  Отчёты: `plans/reports/round10.13_reviewer.md`, `plans/reports/round10.13_scanner_audit.md`.
- **Архитектура:** `plans/ARCHITECTURE.md` **§34** + `ADR-1013-1` (provider keys
  `models.intel_<role>_*` / `keys.intel_<role>_api_key`), `ADR-1013-2` (vis-network
  standalone UMD self-host lazy-load), `ADR-1013-3` (prompt canon policy — модульные
  каноны dream/lore/dossier, `PROMPT_MIGRATIONS` не трогаем).
- **Архив:** `plans/archive/cognition-*-round1013/` — 8 папок (`spec.md` + `tasks.md` +
  3 ADR); `plans/archive/` — **42 папки**; `plans/features/` — 6 активных (F-1…F-6).
- **Проверки:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean. Инварианты: ноль новых PG-DDL, SQLite **v8**, порядок роутеров
  `bot.py` не тронут (только DI-kwargs), R17 чист, F7-гайд без запрещённого жаргона (grep 0),
  новых `v-html`/CDN нет. Флаги default OFF: `flags.belief_decay_enabled`,
  `flags.deep_sleep_enabled`, `flags.irony_filter_enabled`.
- **Деплой:** README + `APP_VERSION` 2.56.0 → **2.57.0**; commit **`8800bba`**;
  push origin/master `ce25dc7..8800bba`; прод `nik@198.46.175.136:/var/www/admin_bot`,
  fast-forward `708f7df..8800bba`, restart active (running) PID **1629874**,
  `/api/health` = **200** `{"status":"ok"}`, рабочее дерево чистое; `.env` не редактировался.
- **Остаточно (не блокеры):** betterstack_handler WARNING 401 (внешний `LOGTAIL_SOURCE_TOKEN`,
  вне раунда); ручной live Android/Telegram QA.

## Техдолг раунда 10.13 (5 Low, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.13-9` | Low | Timeline-лор из in-memory `get_process_accounting().lore_last_inject_at`, а не из `chat_lore_history` |
| `S10.13-11` | Low | LIKE-маркер парадигм матчит только 2 варианта JSON-сериализации `belief_meta` |
| `S10.13-13` | Low | Три дублирующих парсера `belief_meta` (кандидат на DRY-унификацию) |
| `S10.13-14` | Low | Возможны «висячие» рёбра после cap в `graph_snapshot` |
| `S10.13-6b` | Low | Остаточная несогласованность `archived_beliefs` без фильтра парадигм |

Источник: `plans/reports/round10.13_scanner_audit.md` §5; KG `tech-debt-round10.13`.

## Детали раунда 10.14 (13.09.2026)

- **Эпик:** `Epic: Self-Awareness-Persona Refactor round1014` / милстоун `round1014-epic-self-awareness`.
- **Фичи (8, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `anti-echo-self-reply-round1014` — T-1477…T-1486 (origin `bot_self_reply` + SQLite v9 + LLM-экстрактор).
  - F2 `persona-storage-core-round1014` — T-1487…T-1497 (PG `personas`/`persona_traits` + `bot_persona`).
  - F3 `persona-ui-tab-round1014` — T-1498…T-1504 (special-screen `#/ai/persona`).
  - F4 `persona-traits-ribbon-round1014` — T-1505…T-1510 (лента «Эволюция характера» + метрики «Сводки»).
  - F5 `settings-persistence-audit-round1014` — T-1511…T-1525 (write/scope/restart-аудит).
  - F6 `help-guide-integration-round1014` — T-1526…T-1534 (гайд в PG + редактор «Справки»).
  - F7 `status-layout-reorder-round1014` — T-1535…T-1540 (перестановка блоков «Статуса»).
  - F8 `self-reflection-llm-provider-round1014` — T-1541…T-1548 (3-й провайдер `intel_reflection`).
- **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (H1 persona optimistic-409 недостижим — `updated_at`
  не отдавался; H2 RBAC `edit_persona` не выдаётся; H3 per-chat флаги читались только глобально `hot.get`);
  итерация 2 — **APPROVED**. @Scanner итерация 1 — 0 Critical / 0 High / **2 Medium** (R10.14-1 RBAC view/edit
  `edit_persona`; R10.14-2 traits-LLM вне `worker_budget`) / 5 Low; итерация 2 — **CLEAN 0/0/0** (закрыты
  оба Medium), остаются **2 Low** (R10.14-4, R10.14-7) + 2 Info. @Builder — **2 цикла реворков**.
  Отчёты: `plans/reports/round10.14_reviewer.md`, `plans/reports/round10.14_scanner_audit.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **§35 «Карта раунда 10.14»**, **ADR-1014-1** (PG Persona) и
  **ADR-1014-2** (origin `bot_self_reply` + v9 + LLM-экстрактор); SQLite **v8→v9** (rebuild `graph_facts`),
  PG `personas`/`persona_traits`/`persona_state` (идемпотентный DDL) — инварианты «ноль PG-DDL»/«SQLite v8»
  сняты владельцем. Флаги `flags.persona_enabled`/`flags.bot_self_awareness_enabled` = **ON** по умолчанию.
- **Архив:** `plans/archive/*-round1014/` — 8 папок (`spec.md` + `tasks.md` ×8 + ADR-1014-1/2 +
  `settings-persistence-audit-round1014/report.md` + `inventory.tsv`); `plans/archive/` — **50 папок**;
  `plans/features/` — 6 активных (F-1…F-6).
- **Проверки:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean.
- **Деплой:** commit **`eb2a232`**; push origin/master `2edc65b..eb2a232`; прод
  `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `8800bba..eb2a232`; `admin_bot`
  **active (running) PID 1774527**; `/api/health` = **200**, `/api/persona/health` = **401** (не 500);
  `.env` не редактировался (дефолты безопасны, флаги ON в коде). **APP_VERSION 2.57.0 — без бампа**
  (отдельный релиз v2.58.0 не выставлялся).
- **Остаточно (не блокеры):** `betterstack_handler WARNING 401` (внешний `LOGTAIL_SOURCE_TOKEN`,
  pre-existing, вне раунда); ручной live Android/Telegram QA «Личности»/гайда/порядка «Статуса».

## Техдолг раунда 10.14 (Low 2 + L5 + Info 2, открыт)

| ID | Severity | Суть |
|---|---|---|
| `R10.14-4` | Low | `GET /api/persona` отдаёт `dynamic_traits` без фильтра `chat_id` — осознанно по F4 («общий характер бота») |
| `R10.14-7` | Low | warning «closed 12 leaked aiosqlite connection(s)» — pre-existing, не регрессия |
| `L5` | Low | hot-path: на каждый direct-ответ 2 доп. PG-запроса (`resolve_bot_persona`+`get_traits`) + запись `persona_state`, кэша нет (@Reviewer) |
| `I10.14-1` | Info | прямой каскад v7→v9 юнит-тестами не покрыт (безопасен по guard-анализу) |
| `I10.14-2` | Info | FIFO-ротация traits глобальная, не per-chat — соответствует модели «общий характер бота» |

Источник: `plans/reports/round10.14_scanner_audit.md` §5/§6; KG `tech-debt-round10.14`.

## Детали раунда 10.15 (13–14.09.2026)

- **Эпик:** `Epic: Memory-Graph-Sleep-Nostalgia bugfixes round1015` / милстоун `round1015-epic-graph-sleep-nostalgia`; релиз `release-round1015`.
- **Фичи (9, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `graph-sampling-centrality-round1015` — T-1549…T-1557 (Degree Centrality топ-50 + окрестность + очистка сирот).
  - F2 `graph-frontend-physics-search-round1015` — T-1558…T-1565 (barnesHut + «Поиск по графу»).
  - F3 `sleep-unblock-diagnostics-round1015` — T-1566…T-1574 (fallback порогов 2/8 + лог `[Sleep]` WARNING).
  - F4 `nostalgia-prompt-revamp-round1015` — T-1575…T-1583 (окно ±10 + инжект лора/мемов).
  - F5 `status-graph-ui-relocation-round1015` — T-1584…T-1592 (релокация статистики в «Сводку» + оконные бейджи).
  - F6 `command-prefix-persona-routing-round1015` — T-1593…T-1602 (префикс = `active_persona.name`, реестр 17 команд).
  - F7 `guide-rewrite-persona-round1015` — T-1603…T-1609 (канон-гайд + DML-миграция).
  - F8 `hybrid-tool-calling-round1015` — T-1610…T-1618 (7 JSON-Schema инструментов).
  - F9 `recent-history-tool-round1015` — T-1619…T-1624 (`get_recent_history`).
- **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (H1 F5 `enabled=false` не гасил бейдж Сна;
  M1 F6 нет правой границы слова у триггеров; M2 F6 безусловный yield терял сообщение); итерация 2 —
  **APPROVED**. @Scanner итерация 1 — 0 C / 0 H / **3 Medium** (R10.15-1 link-first, R10.15-2
  `get_bot_health` vs `checkup_enabled`, R10.15-3 ложный консьюм обычной речи) / 6 Low; итерация 2 —
  **CLEAN 0/0/0** (закрыты Medium R10.15-1/-2/-3 и Low -5/-6/-7/-8/-9), остаются **3 Low**
  (R10.15-4, -10, -11) + 3 Info. @Builder — **2 цикла реворков**.
  Отчёты: `plans/reports/round10.15_reviewer.md`, `plans/reports/round10.15_scanner_audit.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **§36 «Карта раунда 10.15»**; **ADR-1015-1** (command
  prefix policy), **ADR-1015-2** (graph sampling), **ADR-1015-3** (tool calling). Миграций БД **нет**
  (SQLite **v9**, PG без изменений); единственная миграция — **DML** `info_how_it_works` (F7,
  идемпотентная, guard `PREV_DEFAULT_INFO_TEXT`). Закрыт техдолг **S10.13-14** (висячие рёбра графа, F1).
  APP_VERSION **2.57.0 — без бампа**.
- **Архив:** `plans/archive/*-round1015/` — 9 папок (`spec.md` + `tasks.md` ×9 + ADR-1015-1/2/3);
  `plans/archive/` — **59 папок**; `plans/features/` — 6 активных (F-1…F-6).
- **Проверки:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`;
  `git diff --check` clean. Инварианты: каталог-Δ=0, R16/R17, порядок роутеров `bot.py` не тронут
  (только DI-kwargs), `media/`/`.env` не тронуты, PREV-слепок ностальгии + `PROMPT_MIGRATIONS` не
  тронут, tool-сет = 7.
- **Деплой:** commit **`d01a539`**; push origin/master `798e044..d01a539`; прод
  `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `eb2a232..d01a539` (⚠️ потребовалась ручная
  разблокировка серверного дрейфа `info_text.md`: backup + `git stash` → pull); `admin_bot`
  **active (running) PID 1860445**; `/api/health` = **200**, `/api/memory/graph` = **401**,
  `/api/memory/stats` = **401** (не 500); `.env` не редактировался; миграций БД нет.
- **Остаточно (не блокеры):** ручной live Android/Telegram QA графа/бейджей/гайда/префиксов/tool-сета;
  `betterstack_handler WARNING 401` (внешний `LOGTAIL_SOURCE_TOKEN`, pre-existing, вне раунда).

## Техдолг раунда 10.15 (Low 3 + Info 3, открыт)

| ID | Severity | Суть |
|---|---|---|
| `R10.15-4` | Low | `direct_chat` yield по hot-флагу vs startup-регистрация download-роутера 4e — рантайм-включение `flags.download_enabled` даёт yield без воркера (deferred) |
| `R10.15-10` | Low | link-first привязан к **первому** вхождению имени (`split_prefix_anywhere`) — повторное имя до URL уводит команду в LLM |
| `R10.15-11` | Low | триггер anywhere + **любой** http-URL консьюмит обычную речь (частичный residual R10.15-3) |
| `I10.15-1` | Info | repo-wide R17-долг: `plans/current_task.md:62-65` содержит SSH-доступ и пароль (в `.gitignore`, но уже в истории) — рекомендация сменить/отозвать пароль и очистить историю |
| `I10.15-2` | Info | комментарий-заголовок `services/command_registry.py:11-15` корректно перечисляет снятые алиасы (spec F6-U1) |
| `I10.15-3` | Info | `info_text.md` §5 `Бот, живой?` — границы триггера `живой?` корректны |

Источник: `plans/reports/round10.15_scanner_audit.md` §5; KG `tech-debt-round10.15`.

## Детали раунда 10.16 (14.09.2026)

- **Эпик:** `Epic: Download-Guide-MobileAudit round1016` / релиз **`release-round1016`**.
- **Фичи (5, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `download-fix-round1016` — T-1625…T-1633 (9) — контракт `download(url, quality=None)`, без `"direct"`, reason-коды, R17-логи без URL, bounded probe-fallback.
  - F2 `guide-delivery-round1016` — T-1634…T-1641 (8) — canon_version, force-доставка с бэкапом, PG-only write-path, reset-canon API.
  - F3 `audit-recent-epics-round1016` — T-1642…T-1650 (9) — 7 смоук-наборов; FIX S10.13-6b/-13, R10.15-4/-10/-11; WONTFIX S10.13-9/-11, R10.14-4.
  - F4 `miniapp-mobile-round1016` — T-1651…T-1659 (9) — self-host Vue/Chart.js/Tailwind/Telegram SDK + CSP.
  - F5 `security-rotation-finalize-round1016` — T-1660…T-1665 (6) — git-гигиена, скан секретов, SSH-ключ, README/R17.
- **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (**Critical** F4 — CSP `script-src 'self'` без `'unsafe-eval'` ломал Vue full build; **High** F1 — R17-логи URL/`str(exc)`; **High** F2 — доставка канона не гарантирована; **High** F5 — README-overclaim о ротации SSH); итерация 2 — **APPROVED**. @Scanner итерация 1 — **0 C / 1 H / 1 M / 6 L** (High `S10.16-1` — R17-утечка URL на youtube-пути; Medium `S10.16-2` — force-доставка без бэкапа); итерация 2 — **0 C / 0 H / 0 M** (Low 1 — `S10.16-9`). @Builder — **2 цикла реворков**.
  Отчёты: `plans/reports/round10.16_reviewer.md`, `plans/reports/round10.16_scanner_audit.md`, `plans/reports/round10.16_audit.md`, `plans/reports/round10.16_security_scan.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **§37 «Карта раунда 10.16»**; **ADR-1016-1** (download contract), **ADR-1016-2** (self-host/CSP, финал — вариант A `'unsafe-eval'`), **ADR-1016-3** (guide canon versioning). Миграций БД **нет** (SQLite v9, PG без изменений); единственная миграция — **DML** канона гайда (`canon_version=2`). Каталог-Δ=0.
- **Архив:** `plans/archive/*-round1016/` — **5 папок** (`spec.md` + `tasks.md` ×5 + ADR-1016-1/2/3 + `ssh-rotation-checklist.md`); `plans/archive/` — **64 папки**; `plans/features/` — 6 активных (F-1…F-6).
- **Проверки:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; `git diff --check` clean.
- **Деплой:** commit **`eb3fd4a`**; push origin/master `18a9aa1..eb3fd4a`; прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `d01a539..eb3fd4a`; `admin_bot` **active (running) PID 1976836**; `/api/health`=**200**, `/api/memory/graph`=**401**, `/api/persona/health`=**401** (не 500); **гайд доставлен в PG** (`canon_version=2`, `canon_delivered_version=2`, `canon_drift=False`, `prev_html` сохранён, `html_len==seed_len==4592`); DNS A→198.46.175.136 (AAAA нет), LE notAfter 2026-11-28, `/web/` GET 200 + CSP; Caddy: `encode zstd gzip` включено (backup). APP_VERSION **2.57.0** — без бампа.
- **Остаточно (не блокеры):** HEAD `/web/` = 404 (pre-existing FastAPI/StaticFiles, не регрессия 10.16); 3 caught avatar-traceback (pre-existing `avatars.py`); live-скачивание видео и live Android-проверка — ручные шаги владельцу; SSH-ключ работает (парольный вход сохранён намеренно).

## Техдолг раунда 10.16 (Low 1 + WONTFIX 3 + R17-долг, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.16-9` | Low | Latent hardening: 4 raise-сайта `tools/video_downloader.py:767,772,899,904` интерполируют `{exc}`/тело cobalt-ответа; доступного лог-пути, печатающего сообщение, нет — утечки нет (превентивно) |
| `S10.13-9` | WONTFIX | Timeline-лор из in-memory `get_process_accounting().lore_last_inject_at`, а не из `chat_lore_history` — осознанный источник, сброс рестартом приемлем |
| `S10.13-11` | WONTFIX | LIKE-маркер парадигм матчит только 2 варианта JSON-сериализации `belief_meta` — достижимо лишь ручной/бэкап-правкой, в проде не воспроизводится |
| `R10.14-4` | WONTFIX | `GET /api/persona` отдаёт `dynamic_traits` без фильтра `chat_id` — модель «общий характер бота» по F4 10.14, не утечка |
| R17-долг (repo-wide) | Info | Рабочая копия `plans/current_task.md` содержит SSH-пароль (untracked, `.gitignore:70`; в истории git утечки нет — скан чист); ротация — по желанию владельца. @DevOps-заметки: HEAD-404, brotli-плагин Caddy, live-smoke скачивания |

Источник: `plans/reports/round10.16_scanner_audit.md` §2/§5, `plans/reports/round10.16_audit.md` §3, `plans/reports/round10.16_security_scan.md`; KG `tech-debt-round10.16`.

## Детали раунда 10.17 (14.09.2026)

- **Эпик:** `Epic: Mobile-Download-Badges round1017` / релиз **`release-round1017`** (alias `release-b6c153f`).
- **Фичи (5, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `miniapp-mobile-dns-round1017` — T-1666…T-1674 (9) — top-level DNS-диагностика: HEAD `/web/`, unauth `/healthz` (GET+HEAD, no-store), startup host-лог, no-CDN-гейт (ADR-1017-1).
  - F2 `tool-download-quality-round1017` — T-1675…T-1684 (10) — tool-скачивание спрашивает качество (probe → меню `tdq:` → callback); фикс падения; **SUPERSEDE ADR-1016-1 §2 п.3/§3** (ADR-1017-2).
  - F3 `sleep-badge-countdown-round1017` — T-1685…T-1691 (7) — countdown бейджей Сна «через {остаток}»/«до HH:MM» + glow, эмодзи не тронуты (ADR-1017-3).
  - F4 `ssh-rotation-cancelled-round1017` — T-1692…T-1695 (4) — **docs-only**: ротация SSH **CANCELLED** решением владельца, кода ноль.
  - F5 `warnings-hygiene-round1017` — T-1696…T-1702 (7) — политика логов `web/api/avatars.py` (6 сайтов; транзиенты без трейса/кэша) + brotli **WONTFIX**.
- **Ревью/аудит:** @Reviewer итерация 1 — **Rejected** (3 **Medium** — overclaim ротации в `plans/ARCHITECTURE.md`; транзиенты аватаров на 2 из 6 сайтов `web/api/avatars.py`; дублирование меню качества F2/T-1679); итерация 2 — **APPROVED**. @Scanner итерация 1 — **0 C / 0 H / 1 M / 2 L / 3 Info** (Medium `S10.17-1` docs-only overclaim ротации в архивной спеке 10.16 F5 — закрыт @Architect на Merge; Low `S10.17-2` бейдж при `cognition==null`, `S10.17-3` доки-счётчики — синхронизированы с 6007; Info `S10.17-4/-5/-6`); контракт по **C/H пройден** (финал **0/0**). @Builder — **2 цикла реворков**.
  Отчёты: `plans/reports/round10.17_reviewer.md`, `plans/reports/round10.17_scanner_audit.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **§38 «Карта раунда 10.17»**; **ADR-1017-1** (hostname/DNS), **ADR-1017-2** (tool download quality, **SUPERSEDES ADR-1016-1**), **ADR-1017-3** (sleep badge countdown). Миграций БД **нет** (SQLite v9, PG без изменений); каталог-Δ=0. APP_VERSION **2.57.0 — без бампа**.
- **Архив:** `plans/archive/*-round1017/` — **5 папок** (`spec.md` + `tasks.md` ×5 + ADR-1017-1/2/3); `plans/archive/` — **69 папок**; `plans/features/` — 6 активных (F-1…F-6).
- **Проверки:** `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; `node tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; `git diff --check` clean.
- **Деплой:** commit **`b6c153f`**; push origin/master `772f192..b6c153f`; прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `eb3fd4a..b6c153f`; `admin_bot` **active (running) PID 2016726**, лог без traceback; `/api/health`=**200**, `/healthz` GET+HEAD=**200** (no-store), `HEAD /web/`=**200**, `/api/memory/graph`=**401**, `/api/persona/health`=**401**; DNS A→198.46.175.136 (AAAA пусто, TTL 50), LE notAfter 2026-11-28, Caddy `encode zstd gzip` (gzip подтверждён); миграций/env-правок нет.
- **Остаточно (не блокеры):** ручной Android-смоук мини-аппа — за владельцем (инструкция в отчёте @DevOps); live-скачивание видео — ручной шаг владельцу; ротация SSH — **CANCELLED** владельцем.

## Техдолг раунда 10.17 (Low 1 + Info 3 + WONTFIX, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.17-2` | Low | При `cognition==null` бейджи Сна дают «Сон через —»/«Глубокий сон через —» вместо чистого «—»; §3.4 спеки vs псевдокод §3.2 противоречивы — закреплено тестами, функц. вреда нет |
| `S10.17-4` | Info | Tool-путь скачивания не вызывает `log_download_env_once()` — паритет диагностики с Fast-Track (не блокер) |
| `S10.17-5` | Info | Callback `tdq:` не проверяет hot-флаг `flags.download_enabled` (не блокер) |
| `S10.17-6` | Info | `/healthz` отдаёт `APP_VERSION` — принято F1 §3.1 L8; `query=%r` — pre-existing, вне диффа |
| brotli | WONTFIX | В репо только build-time (субсет шрифта); Caddy требует `xcaddy`/`http.encoders.brotli`; `zstd+gzip` активны (gzip подтверждён) |
| Ротация SSH | CANCELLED | Закрыта **отменой** решением владельца, а не выполнением; не открытый гейт; git-гигиена (`plans/current_task.md` untracked) сохраняется |

Источник: `plans/reports/round10.17_scanner_audit.md`, `plans/reports/round10.17_reviewer.md`; KG `tech-debt-round10.17`.

## Заготовка раунда 10.18 (Step 3 @Memory, 15.09.2026) — заполнит Step 10

> Статус: **ARCHITECTED / SPEC_READY** (Step 2 @Architect + итерация 2 после human-gate);
> Builder не начат. Длительность / R-iters / Scanner / Rework / тесты-Δ / commit / деплой —
> **TBD** (заполняется по факту на Step 10).

- **Эпик:** `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)` — KG + `plans/features/*-round1018/` (7 папок).
- **Фичи (7, 🔵/🟣 SPEC_READY):**
  - F1 `betterstack-us-region-401` — T-1703…T-1711 (9), P0, ADR-1018-1; **Δ REGISTRY +1**.
  - F2 `sleep-manual-cascade-badges` — T-1712…T-1726 + T-1767…T-1772 (21), P0, ADR-1018-2; Δ=0; закрывает **S10.17-2**.
  - F3 `graph-density-scoring-stoplist` — T-1727…T-1735 + T-1773…T-1777 (14), P1, ADR-1018-3; **DDL SQLite v9→v10**.
  - F4 `graph-physics-stabilization` — T-1736…T-1741 (6), P1, ADR-1018-4; Δ=0.
  - F5 `metafact-penalty-extractor-prompt` — T-1742…T-1749 (8), P1, ADR-1018-5; **Δ REGISTRY +1 / Settings +1**.
  - F6 `role-matrix-settings-actualization` — T-1750…T-1757 (8), P2, ADR-1018-6; сводит Δ каталога.
  - F7 `settings-worker-sync` — T-1758…T-1766 (9), **P0 (итерация 2)**, ADR-1018-7; Δ=0.
- **Порядок:** F7 → F2 → F3 → {F4 ∥ F5} → F6 (F1 параллельно; @DevOps `.env` + restart).
- **Baseline:** HEAD `118a03c`, прод `b6c153f` (release-round1017), pytest **6007 / 0**, APP_VERSION **2.57.0**, SQLite v9, каталог 435/406/411/90/88/19.
- **Плановый каталог:** REGISTRY **437** / Settings **407** / categorized **411** (GROUPS 90, mapped 88, TAB_RULES 19); альтернатива 436/406 — решение на Merge.
- **Риск `risk-catalog-delta-drift-round1018` — СУЖЕН (F3-часть снята):** F3-флаг `flags.graph_scoring_v2_enabled` **не вводится** (ADR-1018-3 **D7** — каталог-Δ=0, новая политика активна безусловно, откат = `git revert`); остаются: пин-тест F6 §6 `436` vs свод §5 `437` и дрейф backlog (6 фич / 5 ADR) / нумерации ADR — свести на Merge/Step 10.
- **Планируемые остаточные (заполнить на Step 10):** F1 — CHECKUP-контур/EU, `logtail-python` в requirements; F5 — падежи, крон-промпт, пути без subject/object; F7 — Nostalgia/Lore-рассинхрон, холостой тик; F3 — legacy NULL, `chat_id=None` perf, STOP_LIST-ложносрез.
- **Источник:** `plans/current_task.md` §1–§5 + UPD (109-128); KG `metric-snapshot-round1018-baseline`; `plans/backlog.md` §10.18.
