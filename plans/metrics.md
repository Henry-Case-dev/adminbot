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
| **10.18** | «Memory-Graph-Sleep-BetterStack bugfixes» — BetterStack US-регион (401) + единый источник настроек воркеров + разблокировка Сна/каскада/бейджей + апгрейд графа (скоринг Σ importance/плотность/физика) + пенализация мета-фактов + Матрица ролей — 7 фич: F1 betterstack-us-region-401, F2 sleep-manual-cascade-badges, F3 graph-density-scoring-stoplist, F4 graph-physics-stabilization, F5 metafact-penalty-extractor-prompt, F6 role-matrix-settings-actualization, F7 settings-worker-sync (T-1703…T-1777, 75 задач) | одна сессия **15.09.2026** (Step 0 → Step 10 @Memory) | **4 (по батчам)** — Б1: 2 (Rejected→Approved), Б2: 3, Б3: 2, Б4: 2 (+фикс-проходы); итог по всем батчам **Approved** | **0 / 0** (открыто) | 0 / **1** / **5** / **5** (итер.1 Батч 1; закрыто 1 High + 6 Medium + низкие по итерациям) | **~7** (включая прерванные сессии) | 6007 → **6139** (**+132**; scan-итерации 6042→6052→6083→6104→6137→6139) | 435 / 406 / 411 → **436 / 406 / 411** (Δ=+1 — только F1 `BETTERSTACK_HOST`; новых фича-флагов НЕТ; GROUPS 90, mapped 88, TAB_RULES 19) | **`16a8c0b`** | ✅ прод `b6c153f..16a8c0b` (fast-forward), `admin_bot` active (PID **2319614**), SQLite v9→**v10** | **200** (+ публичный healthz 200) | **Low 1** (`S10.18-29`) + **Info** (`S10.18-12/-13/-18/-19/-20/-31/-32/-33/-37`) + остаточный **блокер BetterStack 401** (неверный токен, действие владельца) |
| **10.19** | «UPD2+UPD3+UPD4 bugfixes» — бюджеты direct-чата (безлимит + раздел «Бюджеты»), BetterStack ingest-Bearer-контракт, расширение контекста, UI «Статуса», синхронизация медиа/аватаров, здоровье памяти + retention, устойчивость GraphRAG-Memorize — 8 фич: F1 betterstack-ingest-bearer-contract, F2 direct-chat-budget-unlimited, F3 budget-settings-section, F4 direct-context-limit-expansion, F5 status-section-ui-merge, F6 media-files-avatars-sync, F7 memory-retention-health, F8 graphrag-memorize-robustness (T-1778…T-1865, 88 задач) | одна сессия **15–16.09.2026** (Step 0 → Step 10 @Memory) | **5 (по батчам)** — A: F1+F8, B: F2, C: F3, D: F4+F5, E: F6+F7 (после переделки по UPD4); итог по всем батчам **Approved** (отклонений **6**: A-1, B-1, C-1, D-1, E-2) | **0 / 0 / 0** | — (финал по эпику **0 C / 0 H / 0 M**; High `S10.19-13` и Medium `S10.19-14` закрыты @Builder) | **~6** (вкл. переделку по UPD4 и hotfix) | 6139 → **6326** (**+187**; scan-итерации 6164→6195→6232→6262→6323→6326 hotfix) | 436/406/411/90/88/19 → **437/407/412/92/90/20** (Δ санкц. UPD3; +1 ключ `import_history_retention_days`, +2 группы, +1 вкладка `mod_budgets`) | **`c1502b6` + `2416d3e`** (hotfix сида) | ✅ прод `fd6acc7..2416d3e`, `admin_bot` active (MainPID **2476027**), SQLite v10→**v11** (прод `user_version=11`), Post-Deploy Gate **PASS** | **200** | **Low 2** (`S10.19-15`, `S10.19-23`) + **Low 1** (`S10.18-29`) + **Info 16**; UPD2-3 (SSH) — **CANCELLED/RISK-ACCEPTED**; follow-up @DevOps (apply-chat-overrides no-op, retention при живом боте) |
| **10.20** | «Летописец (Lore Compiler) & RAG Refactor» — 9 фич-блоков 0–8: F0 metadata-injection, F1 lore-compiler, F2 rag-chronology-tool-routing, F3 miniapp-ux-refactor, F4 llm-engine-audit (read-only), F5 time-awareness-hallucination-fixes, F6 persona-worker-ui-factcheck, F7 agentic-ai-refactor, F8 help-ui-update (T-1866…T-1931, 66 задач; **8 ADR ADR-1020-1…-8**) | одна сессия **16.09.2026** (Step 0 → Step 10 @Memory; фазы A–H) | **1** (Approved с 1-й итерации) + фикс-проход после Scanner | **0 / 0** | 0 / **1** / **7** / **9** (+5 Info) | **2** (T-1874 partial → фикс; фиксы после Scanner: High `S10.20-1` + 7 Medium + 7 Low) | 6326 → **6546** (**+220**; scan-итерации 6382→6405→6439→6508→6523→6546) | 437/407/412/92/90/20 → **439/409/414/92/90/20** (Δ+2 — `flags.lore_compiler_enabled` default **ON**, `limits.chat_timezone`) | **`995cf83`** + **`741b77c`** (R18-вычистка архива 10.16) | ✅ прод `racknerd-f4e3456` (push origin/master), `systemctl` **active** (MainPID **2668878**, NRestarts=0), SQLite v11→**v12** (`user_version=12`) | active (NRestarts=0) | **Info 5** (`S10.20-18…-22`) + **принято 2** (`S10.20-12` ADR-1020-3, `S10.20-17` вне скоупа) + follow-up **T-1932**; ⏸ human-pending **T-1904/T-1931**; **R17 → Risk Accepted** (`risk-secret-in-git-history` ACCEPTED, без ротации/rewrite; ignore-лист `plans/docs/r18_scanner_ignore.md`); ✅ **UI-rework закрыт** — доработка БЛОК 3 (`round1020-ui-rework`) исправлена, задеплоена и заархивирована 17.09.2026 (см. строку **10.20-UPD3**) |
| **10.20-UPD3** | «UI-rework» — доработка проваленного БЛОК 3 эпика 10.20 (5 дефектов): Liquid Glass, CSS Grid, маска секретов (`SECRET_MASK`+`hasSecretMask`+no-op guard), градиент `#FF8A3D`/`6s`, sticky внутрь скроллера + `.sticky-spacer` (T-1933…T-1942 + T-1936-fix/-fix2; **ADR-1020-9**, D1–D7) | одна сессия **17.09.2026** (Step 0 → Step 10 @Memory) | **2** (1 Needs-fixes → 1 Approved, реальный Chromium) | **0 / 0** | 0 / 0 / **1** / **3** (+3 Info) | **3** (первичный + после Critical Reviewer + после M-1/L-1/L-2 Scanner) | 6546 → **6574** (**+28**; red→green 19 failed/7 passed → 26 passed) | **439/409/414/92/90/20** (Δ=0; SQLite без изменений) | **`ec93c3d`** | ✅ прод `racknerd-f4e3456` (push origin/master), `systemctl` **active** (MainPID **2738993**, NRestarts=0), прод-`/web/static/app.css` подтверждён (`blur(16px)`/`rgba(20,25,30,0.5)`/`#FF8A3D`/`6s`/`sticky-spacer`/`no-store`), SQLite `user_version=12`, каталог-Δ=0 | active (NRestarts=0) | **0** (M-1/L-1/L-2 закрыты T-1936-fix2; 3 Info не блокеры); ⏸ живые WebView + скриншоты §7.5 |
| **10.21** | «System 2 Reasoning & Memory Rebuild» — двухслойная экстракция памяти (Слой А scratchpad + Слой Б синтезатор), строгий grounding фактчекера + CoVe, де-роботизация канонов (Negative Constraints/асимметрия), пороги Парадигм/Deep Sleep + консолидация, ребилд/санитария `manage.py memory`, браузерный UI/UX-аудит — 6 фич: F1 `multilayer-memory-extraction`, F2 `factchecker-grounding-cove`, F3 `de-robotization-negative-constraints`, F4 `paradigm-thresholds-consolidation`, F5 `memory-rebuild-sanitation`, F6 `ui-audit-puppeteer` (T-1943…T-2000 + T-2001…T-2018, **76 задач**; **ADR-1021-1…-6**) | одна сессия **18.09.2026** (Step 0 → Step 10 @Memory; старт 18.09.2026 → деплой 18.09.2026) | **3** (2 итерации `Needs fixes` → **Approved** на 3-й) + фикс-проход после Scanner | **0 / 0 / 0** (re-audit) | 0 / 0 / **2** / **7** (+4 Info; первичный diff-based скан) | **3** (2 фикс-раунда по @Reviewer + 1 пост-скан фикс-раунд) | 6574 → **6779 passed / 0 failed** (**+205**) | 439/409/414/92/90/20 (**Δ=0**; SQLite `user_version=12`, **Δ DDL=0**) | **`29fc638`** (feat: System 2 Reasoning) + **`a923310`** (docs/plans: архивация + Merge §47 + отчёты) | ✅ прод `/var/www/admin_bot` fast-forward `ec93c3d..a923310`, push `21cd54c..a923310`, `systemctl` **active** (PID **3023258**), `/api/health` + `/healthz` = **200**, SQLite `user_version=12`, канон-миграция промптов применилась идемпотентно (8 ключей); `.env.bak.round1021…`; `DREAM_ENABLED=true`/`DEEP_SLEEP_ENABLED=true`/`BELIEF_DECAY_ENABLED=true` | **200** | **Low 3** (`S10.21-8` vec-эмбеддинги парадигм CLI, `N10.21-1` тест-покрытие, `N10.21-2` бинарный `roster_incomplete`) + **Info 4** (`S10.21-10…-13`); ⏸ Telegram **WebView не воспроизводился** (headless ≠ WebView); Telegram **Puppeteer MCP недоступен** → честный fallback Playwright; **R17/R18** — SSH-пароль в истории git (**Risk Accepted**, ротация не делалась) |
| **10.22** | «True System 2 Pipeline & UI Help» (UPD3) — боевой ребилд досье целевого чата (`confirmed-cleanup` + JSONL-архив, окно 180 дней), фикс KV-словаря алиасов, физические двухвызовные пайплайны (фактчек/саммари/direct chat), egress-guard + validator-loop клише, Справка v4, async-пересборка досье (UI) — 8 фич: F1 `urgent-rebuild-dossiers-target-chat`, F2 `urgent-summary-aliases-ui`, F3 `system2-factcheck-two-call`, F4 `system2-summary-two-call`, F5 `system2-direct-chat-two-call`, F6 `telegram-send-regex-guard`, F7 `help-ui-system2`, F8 `dossier-rebuild-async-ui` (T-2019…T-2096, **78 задач**; **ADR-1022-1…-8**) | одна сессия **18–19.09.2026** (Step 0 18.09 → деплой Step 9 19.09) | **3** (2 итерации `Needs fixes` → **Approved** на 3-й) + фикс-проход после Scanner | **0 / 0** (re-audit 0/0/0/0; открыто 1 Info S10.22-4b) | 0 / 0 / **2** / **4** (+3 Info) | **3** (2 фикс-раунда по @Reviewer + 1 пост-скан фикс-раунд) | 6779 → **6962 passed / 0 failed** (**+183**) | 439/409/414/92/90/20 (**Δ=0**; SQLite `user_version=12`, **Δ DDL=0**) | **`2d153b5`** (feat: True System 2 Pipeline) + **`a8a6437`** (docs/plans: архивация 8 фич + Merge §48 + Scanner re-audit) | ✅ прод `/var/www/admin_bot` → **`a8a6437`**, push `acd9311..a8a6437`, `systemctl` **active**, `/api/health` + `/healthz` = **200**, SQLite `user_version=12`, `INFO_CANON_VERSION=4`, env-флаги default ON (`SYSTEM2_*`, `TELEGRAM_SEND_GUARD_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED`); боевой прогон F1 (чат `-1002661910336`): confirmed-факты **451→10**, portraits **0→12**, memes **0→2**, `smart_messages` не тронуты | **200** | **S10.22-4b** (Info: детектор `as_ai` ложно срабатывает при запятой) + **CLI `memory` берёт LLM-ключ из `.env`, а не из PG** (root cause 401 при первом прогоне; follow-up — синхронизация `.env`/ConfigCache) + **vec-слой F8 не восстанавливается** (best-effort) + **stale-lock TTL** 6ч; ⏸ живая приёмка **T-2069** (F6) и **T-2089** (F8) — за владельцем |
| **10.23** | «Adaptive System 2, Token Analytics, Dynamic Anti-Cliche Cache & Image Generation» — adaptive Вербализатор (3 режима), генерация изображений (Pollinations), дашборд токен-аналитики, динамический анти-клише кэш, глубокий контекст фактчека, маркировка сообщения-триггера, обложка+Article для саммари, UI-табы Вербализатора, Справка v5 — 9 фич: F1 `target-message-marking`, F2 `factcheck-deep-context`, F3 `verbalizer-response-modes`, F4 `dynamic-anticliche-cache`, F5 `image-generation-tool`, F6 `summary-cover-rich-article`, F7 `token-analytics-dashboard`, F8 `ui-verbilizer-tabs`, F9 `help-ui-v5` (T-2097…T-2186, **90 задач**; **ADR-1023-1…-9**) | одна сессия **19.09.2026** (Step 0 → Step 10 @Memory) | **21 прогон** — Approved 9/9 (F1=2, F2=3, F3=3, F4=2, F5=2, F6=2, F7=2, F8=2, F9=3) | **0 / 0** (2 Medium закрыты follow-up) | 0 / 0 / **2** / **4** (+4 Info) | **12 циклов** (@Builder) + **1 scanner follow-up** (M1+M2, +6 тестов) | 6962 → **7424 passed / 0 failed** (**+462**) | **REGISTRY 457** (Δ+18: F2+2/F5+5/F6+1/F8+10), Settings 416, GROUPS 96, `_TAB_BY_GROUP` 94; SQLite **v12** (Δ DDL=0; +3 таблицы в PG) | **`8dadbe3`** (feat) + **`4314ea4`** (docs/plans: архивация 9 фич + Merge §49 + Scanner-аудит) | ✅ прод `/var/www/admin_bot` → **`4314ea4`** (push `731a845..4314ea4`), `systemctl` **active**, `/api/health`+`/healthz`=**200**, SQLite `user_version=12` (Δ DDL=0; PG +3 таблицы), `INFO_CANON_VERSION=5`, `GUIDE_CANON_VERSION=2`, `AntiClicheWorker` (`interval_days=7`), venv aiogram ≥3.31; `.env` += `IMAGE_API_KEY`/`IMAGE_BASE_URL` | **200** | **Low 4 (L1–L4)** + **Info 4 (I1–I4)** (см. техдолг 10.23) + ⏸ 5 ручных приёмок владельца (T-2135/T-2146/T-2156/T-2175/T-2182) |
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

## Детали раунда 10.18 (15.09.2026)

- **Эпик:** `Epic round1018 (Memory-Graph-Sleep-BetterStack bugfixes)` / релиз **`release-round1018`** (alias `release-16a8c0b`).
- **Фичи (7, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `betterstack-us-region-401-round1018` — T-1703…T-1711 (9), P0, ADR-1018-1 — US-ingest-host через env `BETTERSTACK_HOST`, token≠public-key (WARNING), Sentry↔BetterStack разведены; **Δ REGISTRY +1**.
  - F2 `sleep-manual-cascade-badges-round1018` — T-1712…T-1726 + T-1767…T-1772 (21), P0, ADR-1018-2 — manual-приоритет без флагов, каскад Сон→Глубокий→Личность, реактивные бейджи, DML порогов; закрывает **S10.17-2**.
  - F3 `graph-density-scoring-stoplist-round1018` — T-1727…T-1735 + T-1773…T-1777 (14), P1, ADR-1018-3 — Σ importance + STOP_LIST + плотность 500–800; **SUPERSEDE ADR-1015-2**; **DDL SQLite v9→v10** (`edges.fact_id`).
  - F4 `graph-physics-stabilization-round1018` — T-1736…T-1741 (6), P1, ADR-1018-4 — iterations=150 + physics off по стабилизации; Δ=0.
  - F5 `metafact-penalty-extractor-prompt-round1018` — T-1742…T-1749 (8), P1, ADR-1018-5 — PREV-слепок канона + хард-лимит importance=1 + RAG-множитель; флаг не вводился, **Δ=0**.
  - F6 `role-matrix-settings-actualization-round1018` — T-1750…T-1757 (8), P2, ADR-1018-6 — nav-разметка/аддитивные `nav*`/parity/подпись PERMsoc; Δ=0.
  - F7 `settings-worker-sync-round1018` — T-1758…T-1766 (9), **P0 (итерация 2)**, ADR-1018-7 — единый источник настроек воркеров (per-chat DB → global DB → env), реактивный планировщик, LISTEN; Δ=0.
- **Ревью/аудит:** @Reviewer — **Approved по всем батчам** (суммарно 4 раунда ревью + фиксы; отклонений: Батч1 — 1, Батч2 — 2, Батч3 — 1, Батч4 — 1). @Scanner — финал **0 Critical / 0 High** открыто; закрыто **1 High** (`S10.18-1` per-chat лимиты Сна) + **6 Medium** (`S10.18-15`, `-21`, `-22`, `-30`, `-35`, `-36`) + множество Low; открыто **1 Low** (`S10.18-29`) + **Info** (`S10.18-12/-13/-18/-19/-20/-31/-32/-33/-37`). @Builder — **~7 циклов реворков** (включая прерванные сессии).
  Отчёты: `plans/reports/round10.18_scanner_audit.md` (§8–§10), `plans/reports/audit_backlog.md`, `plans/reports/global_map.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **§39 «Карта раунда 10.18»** + SUPERSEDE/AMEND-пометки (§22 SUPERSEDE F-10 §5-6 / ADR-1018-2; §26 AMEND RBAC / ADR-1018-6; §3/§36 SUPERSEDE ADR-1015-2 / ADR-1018-3; AMEND F2 10.15 / ADR-1018-4; AMEND ADR-1013-3 / ADR-1018-5; AMEND раунда 4/5 / ADR-1018-1; AMEND F-7 §6 / ADR-1018-7; AMEND ADR-1017-3). **DDL: SQLite v9→v10** (`edges.fact_id` + `idx_edges_fact_id`, идемпотентная/обратимая ALTER-миграция); **новых PG-DDL нет** (F2 — DML порогов Сна). **Новых фича-флагов НЕТ** (manual-приоритет Сна, graph-scoring-v2, metafact-penalty активны безусловно). APP_VERSION **2.57.0 — без бампа**.
- **Архив:** `plans/archive/<feature>/` — **7 папок** (`betterstack-us-region-401`, `settings-worker-sync`, `sleep-manual-cascade-badges`, `graph-density-scoring-stoplist`, `graph-physics-stabilization`, `metafact-penalty-extractor-prompt`, `role-matrix-settings-actualization`; `spec.md` + `tasks.md` + ADR-1018-1…-7); `plans/archive/` — **76 папок**; `plans/features/` — 6 прежних backlog-папок (пустых/осиротевших нет).
- **Проверки:** полный pytest **6139 passed / 0 failed** (scan-итерации 6042→6052→6083→6104→6137→6139); `node --check web/app.js` clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean. Каталог 435/406/411/90/88/19 → **436/406/411/90/88/19** (Δ=+1 — только F1).
- **Деплой:** commit **`16a8c0b`**; push origin/master `118a03c..16a8c0b`; прод `nik@198.46.175.136:/var/www/admin_bot`, fast-forward `b6c153f..16a8c0b`; `.env` += `BETTERSTACK_HOST=s2736363.us-west-2a.betterstackdata.com`; бэкап `.env` и SQLite (`local_database.db.bak.2026-09-15-0744`); `admin_bot` **active (running) PID 2319614**; `/api/health`=**200** (+ публичный healthz 200); миграция v10 применена (`PRAGMA user_version=10`); DML-миграция порогов Сна применена.
- **Остаточно (не блокеры):** ручной live-смоук RAG/графа/бейджей/manual-каскада — за владельцем.
- **⚠️ Остаточный блокер (владелец):** 401 от BetterStack **сохраняется** — причина НЕ хост, а токен: `LOGTAIL_SOURCE_TOKEN` (len 24) побайтово равен public key из `SENTRY_DSN` (хост US подхватился: `[betterstack] attached | host=s2736363.us-west-2a.betterstackdata.com | token_len=24`, WARNING сработал). Требуется подставить реальный Source Token BetterStack в `.env` и рестартовать. Это окончательно снимает противоречие раунда 5 (T-746) в пользу «это не Source Token».

## Техдолг раунда 10.18 (Low 1 + Info, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.18-29` | Low | `run_once(deep=False)` («Сон сейчас») не выставляет `_manual_deep_until` → во время manual-каскада `deep_sleep.manual=False` и `active_until=None` вне окна; TTL маркера (900с) не связан с `_run_lock`/`_deep_lock` |
| `S10.18-12` | Info | `NostalgiaWorker` читает `memory.nostalgia_*` только через `hot.get` (global-only) — перенос на `worker_settings` → backlog **T-1764** |
| `S10.18-13` | Info | Фрагмент SSH-пароля в **отслеживаемом** `plans/archive/security-rotation-finalize-round1016/spec.md:35` — вычистить плейсхолдером + скан `git log -p` (`filter-repo` — по согласованию). Значение НЕ цитировать (R17) |
| `S10.18-18/-19/-20` | Info | `POST ?deep=1` без капа (осознанно); `tokens_today` без фильтра `kind`; `previous` kill-switch = effective (семантика поля) |
| `S10.18-31/-32/-33` | Info | STOP_LIST: дефис/пробел/морфология не ловятся (жёстко по ADR); self-loop ×2; `upsert_edge` при отсутствии узла → факт без ребра |
| `S10.18-37` | Info | RAG-множитель `importance` меняет порядок для всех чатов/фактов — требуется живая проверка RAG-качества (T-1724/T-1749) и фиксация как ожидаемого поведенческого изменения |
| BetterStack 401 | Блокер (владелец) | Неверный `LOGTAIL_SOURCE_TOKEN` (== public key `SENTRY_DSN`), не хост; нужен реальный Source Token + рестарт |
| Закрыто в 10.18 | — | `S10.17-2` (бейджи при `cognition==null`), `S10.18-1` (High), `S10.18-15/-21/-22/-30/-35/-36` (Medium) и низкие итераций 1–3 |

Источник: `plans/reports/round10.18_scanner_audit.md` (§8–§10, сводки §10.4/§10.6), `plans/reports/audit_backlog.md`, `plans/backlog.md` (ИТОГ 10.18); KG `tech-debt-round10.18` + `release-round1018` + `metric-snapshot-round1018-final`.

## Детали раунда 10.19 (15–16.09.2026)

- **Эпик:** `Epic round1019 (UPD2 bugfixes)` / релиз **`release-round1019`** (alias `release-2416d3e`).
- **Фичи (8, все COMPLETED + DEPLOYED + ARCHIVED):**
  - F1 `betterstack-ingest-bearer-contract` — ingest `POST https://{host}` + `Authorization: Bearer`; `_NoRedirectHandler`; WARNING `token==pubkey` снят → debug; `_STATUS_HINTS={401,402,403,406}`; **401 снят** (US × Bearer = 202).
  - F2 `direct-chat-budget-unlimited` — sentinel **−1=безлимит / 0=запрет**; per-chat резолв direct+фон; `budget_snapshot`/`exceeded_metric`; fail-open; дефолты 100/500000 и 60/300000; **SUPERSEDES F-15**.
  - F3 `budget-settings-section` — вкладка `mod_budgets` «Бюджеты», группы `limits_chat_key`/`limits_chat_context`; **UPD4:** «VIP» удалён из кода → универсальный `chat_settings_seed`.
  - F4 `direct-context-limit-expansion` — развязка per-block caps ↔ общий бюджет; дефолты 5000/3000/16000; per-chat −1 → ceiling 32000 (env-only).
  - F5 `status-section-ui-merge` — единый блок «Статус» + компактный поиск по графу; API аддитивен (R16).
  - F6 `media-files-avatars-sync` — локальный fallback медиа/аватаров; honest-диагностика ФС↔БД; `restore_missing_files` убрана (UPD4).
  - F7 `memory-retention-health` — per-chat retention импорта; fail-safe purge + архив; **SQLite v11**; env-only гейты.
  - F8 `graphrag-memorize-robustness` — `parse_fact_list_ex` + bounded recovery-retry + rate-limited WARNING; AMEND F-15 §4.
- **Ревью/аудит:** @Reviewer — **Approved** по батчам A(F1+F8)/B(F2)/C(F3)/D(F4+F5)/E(F6+F7, после UPD4); отклонений **6**. @Scanner — **0 Critical / 0 High / 0 Medium** по всему эпику (High `S10.19-13` и Medium `S10.19-14` закрыты @Builder, независимо верифицированы — §8.5/§9.1); открыто **2 Low** (`S10.19-15`, `S10.19-23`) + **1 Low** из 10.18 (`S10.18-29`) + **16 Info**. @Builder — **~6 rework**. Отчёты: `plans/reports/round10.19_scanner_audit.md`, `plans/reports/global_map.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **818 строк**, **§40–§44** (F2 / F3+F6+F7 / F1+F8 / F4+F5 / итог+SUPERSEDE-карта); **ADR-1019-1…-8** (ADR-1019-8 → Accepted/Implemented). **DDL SQLite v10→v11** (`UNIQUE(chat_id, import_key)`, `import_checkpoints(path, chat_id)`); новых PG-DDL нет. Новых каталоговых флагов нет; env-only retention-тройка + `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000`.
- **Архив:** 8 папок в `plans/archive/<feature>/`; `plans/archive/` — **84 папки**; `plans/features/` — 6 backlog-папок.
- **Проверки:** pytest **6326 passed / 0 failed**; `node --check web/app.js` clean; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` clean.
- **Деплой:** commit **`c1502b6`** + hotfix **`2416d3e`**; push `fd6acc7..2416d3e`; прод `nik@198.46.175.136:/var/www/admin_bot`, `admin_bot` **active (MainPID 2476027)**; `/api/health`=**200**; **SQLite `user_version=11`**.
- **🔴 Post-Deploy Gate (UPD4 п.4) — сработал:** первый деплой → **ABORT** (сид не применялся: `changed_by` str → BIGINT, `asyncpg.DataError`, глотался fail-open; тесты не поймали — мок `set_chat_params`); **hotfix** `changed_by=None` + интеграционный тест без мока (`_StrictPgConn`). **Повторный гейт PASS**: 8 ключей целевого чата `-1002661910336` = `[0,-1,-1,-1,-1,-1,-1,-1]`; идемпотентность (chat_lore_history 39→39), чужие overrides/`meta` сохранены.
- **✅ BetterStack:** 401 снят — probe US × Bearer = **202**; после деплоя `status=401` = 0.
- **Остаточно (не блокеры):** retention авто-purge **OFF** (гейты безопасны); live-проверки у владельца; follow-up @DevOps.

## Техдолг раунда 10.19 (Low 3 + Info, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.19-15` | Low | `services/oversight.py` `_limits_block` вызывает `chat_usage.key_status` дважды на чат (2× `budget_snapshot` + до 2× чтения `chat_profiles`) — перф «Сводки»; фикс ~2 строки |
| `S10.19-23` | Low | `services/memory_maintenance.py` `_flush_and_fsync` — `fsync` файла есть, каталога нет: узкое окно потери имени архива при сбое питания после DELETE; фикс — fsync родительского каталога |
| `S10.18-29` | Low | (унаследовано 10.18/F2) `run_once(deep=False)` не выставляет `_manual_deep_until`; TTL маркера не связан с `_run_lock`/`_deep_lock` |
| Info (16) | Info | `S10.19-3…-6` (reason=not_json, 4xx/3xx без re-buffer, недостижимый верхний except, path-режим пробника), `-9…-12`, `-16…-22` (OFF-тумблер пишет `global_value`, chars-fallback тихий и др.), `-24…-27` (ротация архивов, запись в event loop, флейки-риск) + унаследованные `S10.18-12/-13/-18/-19/-20/-31/-32/-33/-37/-38` (SSH-фрагмент — задача отменена, R17) |
| follow-up @DevOps | Info | `manage.py apply-chat-overrides` — тихий no-op (`pg.init` без connect); `manage.py retention` не работает при живом боте (SQLite write-lock + нет проброса `ChatParamsCache` — нужен снапшот); `restore_missing_files` (F6, UPD4) — при появлении персистентного маппинга `path→file_id`; I-4 chat-scoped vec-индекс |

Источник: `plans/reports/round10.19_scanner_audit.md` (§1–§10, сводки §10.4/§10.5), `plans/backlog.md` (ИТОГ 10.19); KG `tech-debt-round10.19` + `release-round1019` + `metric-snapshot-round1019-final` + `risk-seed-changed-by-type-round1019`.

## Детали раунда 10.20 (16.09.2026)

> **✅ REOPENED → ИСПРАВЛЕНО + ЗАДЕПЛОЕНО + ЗААРХИВИРОВАНО (UI rework) — Шаг 0 @Memory 17.09.2026, закрыто Шаг 10 @Memory 17.09.2026 (UPD3 владельца, 16.09.2026):** фронтенд-блок **БЛОК 3** (`miniapp-ux-refactor-round1020`) провален по визуальной инспекции владельца; @Reviewer — **выговор** за пропуск. Эпик возвращён на доработку: **5 дефектов UI** — (1) нет Liquid Glass → `glassmorphism-contract`; (2) CSS Grid в одну колонку → `css-grid-320`; (3) КРИТИЧНО пустые поля/секреты (two-way binding) → `secret-field-mask`; (4) градиент 5–8s + оранжевый → `gradient-motion-orange`; (5) сломанная sticky-панель «Отмена/Сохранить». Feature — KG `round1020-ui-rework`. Доработка **завершена**: 5/5 дефектов исправлены, @Reviewer Approved (итер. 2), @Scanner 0 C/0 H (M-1/L-1/L-2 закрыты), pytest **6574**, деплой **`ec93c3d`** — см. раздел «Детали раунда 10.20-UPD3».
>
> **✅ R17 — Risk Accepted (владелец, 16.09.2026):** ротация НЕ делается, история git НЕ переписывается; R18 остаётся глобальным правилом; старый файл — в ignore-листе `plans/docs/r18_scanner_ignore.md`; KG `risk-secret-in-git-history` → **ACCEPTED**.

- **Эпик:** `Epic round1020 (Lore Compiler & RAG Refactor)` / 9 фич-блоков 0–8; фазы **A–H**; Human Gate (О1–О7) пройден.
- **Фичи (9 фич-блоков 0–8, все COMPLETED + DEPLOYED + ARCHIVED; папка — одна, `plans/archive/round1020-lore-compiler-rag-refactor/`):**
  - БЛОК 0 `metadata-injection-round1020` — канонические метаданные контекста (`services/canonical_context.py` + `CONTEXT_POINTS` 14 + `context_middleware.truncate_keep_header`).
  - БЛОК 1 `lore-compiler-round1020` — «Летописец» `compile_lore_story` (8-й инструмент), `lore_stories`, HTML-доставка, флаг default ON.
  - БЛОК 2 `rag-chronology-tool-routing-round1020` — ASC-хронология у всех RAG-потребителей (расширение D206), `/summary`-архив, `dig_into_lore` JSON.
  - БЛОК 3 `miniapp-ux-refactor-round1020` — Liquid Glass/Grid/`<sticky-save>`/labels/досье/тикер; меню НЕ менялось.
  - БЛОК 4 `llm-engine-audit-round1020` — read-only аудит (`plans/reports/round1020_llm_engine_audit.md`).
  - БЛОК 5 `time-awareness-hallucination-fixes-round1020` — Time Injection первым user-блоком, `limits.chat_timezone`, анти-галлюцинации.
  - БЛОК 6 `persona-worker-ui-factcheck-round1020` — Full Tool Access фактчекера, закрытие S10.19-15/-23, retention по снапшоту.
  - БЛОК 7 `agentic-ai-refactor-round1020` — `ToolLoopResult` fail-safe, `reasoning`+stripper, Context Middleware, `graph_facts` v12, EN-схемы 8.
  - БЛОК 8 `help-ui-update-round1020` — Справка v3 (`INFO_CANON_VERSION` 2→3), стиль сохранён.
- **Ревью/аудит:** @Reviewer итерация 1 — **Approved** (Critical/High нет; Medium/Low — не блокеры; T-1904/T-1931 ⏸ HUMAN PENDING — код PASSED). @Scanner итерация 1 — **0 Critical / 1 High / 7 Medium / 9 Low / 5 Info** (`S10.20-1` High — конфиг-вкладки мини-аппа потеряли сохранение) → возврат к @Builder; **re-audit §10** — **0 Critical / 0 High / 0 Medium / 0 Low открыто** (High + 7 Medium + 7 Low закрыты; `S10.20-12`/`S10.20-17` приняты обоснованно; 5 Info). @Builder — **2 rework-цикла** (T-1874 partial → фикс точки 2/3/8/13; фиксы после Scanner). Отчёты: `plans/reports/round1020_reviewer.md`, `plans/reports/round1020_scanner_audit.md`, `plans/reports/round1020_llm_engine_audit.md`.
- **Архитектура/БД:** `plans/ARCHITECTURE.md` **§45** (итог/ADR-карта/инварианты) + точечные синки §1/§3/§4/§5/§6/§9/§11/§25; **ADR-1020-1…-8** (все приняты/реализованы). **DDL: SQLite v11 → v12** (`graph_facts.tg_message_id`/`forward_from`, PG — no-op) + аддитивные `lore_stories`/`persona_dossier_overrides` (без бампа `user_version`). Новый каталоговый флаг ровно один — `flags.lore_compiler_enabled` (**default ON**, О3).
- **Архив:** `plans/archive/round1020-lore-compiler-rag-refactor/` — **11 файлов** (`README.md` + `spec.md` + `tasks.md` T-1866…T-1931 + `adr-1020-1…-8`), перенос `git mv` из `plans/features/`; `plans/archive/` — **85 папок**; `plans/features/` — 6 backlog-папок (round1020 отсутствует).
- **Проверки:** pytest **6546 passed / 0 failed** (baseline 6326 → **+220**; траектория 6382→6405→6439→6508→6523→**6546**); `node --check web/app.js` OK; `JS-UNIT-OK`/`VUE-MOUNT-OK`/`round1020_ui_test` OK; `git diff --check` clean; каталог 437/407/412/92/90/20 → **439/409/414/92/90/20** (Δ+2).
- **Деплой:** commit **`995cf83`** (фича) + **`741b77c`** (R18-вычистка кредов из архива 10.16), запушено в origin/master; сервер **`racknerd-f4e3456`** — `systemctl` **active**, MainPID **2668878**, **NRestarts=0**; SQLite **`user_version=12`** (авто-миграция v11→v12 применена). `.env`-правка не требовалась; `media/` не тронуты.
- **Остаточно (не блокеры):** ⏸ **T-1904** (живая UI-приёмка, десктоп/Android/Nekogram) и ⏸ **T-1931** (приёмка Справки) — за владельцем; follow-up **T-1932** (fallback точки 7 `CONTEXT_POINTS` — «голые» строки архива в `query_chat_memory`); живая проверка «Летописца»/меню.

## Техдолг раунда 10.20 (Info 5 + принято 2 + follow-up, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.20-18` | Info | `LLMChatResult.reasoning` — телеметрия без потребителей (ок по ADR-1020-7) |
| `S10.20-19` | Info | `search_messages_fts_count_by_author` группирует по `(author_name, user_id)`, мердж по имени — у вызывающего |
| `S10.20-20` | Info | Диалоги Летописца включают сообщения всех авторов в окне ±30 мин — по спеке |
| `S10.20-21` | Info | Код-константы `_LORE_*` — каталог-Δ=0, изменение = ревизия кода |
| `S10.20-22` | Info | Пути вне реестра `CONTEXT_POINTS` (`_build_batch_text`/стадии отношений) — осознанно «голые» (R42-канон/служебная метка); гэп покрытия, не рантайм-баг |
| `S10.20-12` | Low (принято) | Time Injection первым user-блоком ломает user-префиксный prompt-cache — принятый трейд-офф ADR-1020-3/О2 (system статичен) |
| `S10.20-17` | Low (принято, вне скоупа) | Паритет RBAC `persona_dossier_overrides` moderator'у — новой эскалации нет, фиксируется в матрице ролей отдельно |
| `T-1932` | follow-up | Fallback точки 7 (`vector_search` → `list[str]`): «голые» строки архива в `query_chat_memory` (ADR-1020-1 P6/R26); формат `[ММ.ГГГГ | fact:ID]: текст` |
| **R18-history-risk** | **Risk → ACCEPTED** | R17-инцидент закрыт владельцем (16.09.2026): ротация НЕ делается, история git НЕ переписывается; R18 достаточно. Рабочее дерево и HEAD чисты (`741b77c` → `[REDACTED]`); старый файл — в ignore-листе `plans/docs/r18_scanner_ignore.md`. KG `risk-secret-in-git-history` (ACCEPTED) + SpecDecision `r17-risk-accepted-no-rotation` |
| **round1020-ui-rework** | **✅ ЗАКРЫТ (UI)** | 5 дефектов БЛОК 3: Liquid Glass, CSS Grid, пустые поля/секреты (two-way binding), градиент 5–8s+оранжевый, sticky-панель. Risks `risk-ui-liquid-glass-missing/-grid-single-column/-empty-secret-fields/-gradient-slow-no-orange/-sticky-panel-layout-round1020` — **RESOLVED**; исправлено и задеплоено 17.09.2026 (`ec93c3d`; M-1/L-1/L-2 закрыты T-1936-fix2) |

Источник: `plans/reports/round1020_scanner_audit.md` (§1–§10, сводки §10.1/§10.2/§10.4/§10.5), `plans/reports/round1020_reviewer.md` (§2/§4), `plans/backlog.md` (ИТОГ 10.20), `plans/archive/round1020-lore-compiler-rag-refactor/tasks.md`; KG `tech-debt-round1020` + `metric-snapshot-round1020-final` + `risk-secret-in-git-history`.

## Детали раунда 10.20-UPD3 «UI-rework» (17.09.2026)

Доработка проваленного **БЛОК 3** эпика 10.20 (переоткрыт владельцем по визуальной инспекции; бэкенд 10.20 не переоткрывался). KG — `round1020-ui-rework` (AMENDS `miniapp-ux-refactor-round1020`); ADR-1020-9 (D1–D7); ARCHITECTURE.md **§46** + синк шапки §1.

- **Дефекты (5/5 закрыты), frontend-only — `web/index.html`/`web/app.js`/`web/static/app.css`:** (1) **Liquid Glass** — `--glass-bg rgba(20,25,30,.5)` + `--glass-blur blur(16px)` (+`-webkit-`), стекло на `.card`/`.modal-card`, снят `card-solid` с 5 модалок; (2) **CSS Grid** — `repeat(auto-fit, minmax(320px,1fr))` (4/3/3 трека @1440px, 1 @400px); (3) **маска секретов** — `SECRET_MASK` + `isSecretMask` + **`hasSecretMask`** (композит `маска+ввод`), no-op guard → **0 POST** при чистой маске и композите; `_seedSecretMasks`; `SECRET_MASK_HINT`; (4) **градиент** — `--grad-d:#FF8A3D` + `--grad-speed:6s` (conic-wash, reduced-motion/contrast); (5) **sticky** — перенос внутрь скроллера + `.sticky-spacer` (зазор 0).
- **Процесс:** @Reviewer **2 итерации — 1 Needs-fixes → 1 Approved** (Re-review итерация 2 на реальном Chromium); @Scanner итерация 1 — **0 Critical / 0 High / 1 Medium / 3 Low / 3 Info** → **M-1** (`.sticky-spacer` вместо `padding-bottom`), **L-1** (условный `@focus f.secret`), **L-2** (`SECRET_MASK_HINT`) закрыты финальным фиксом **T-1936-fix2**; @Builder — **3 фикс-цикла** (первичный + после Critical Reviewer + после M-1/L-1/L-2 Scanner). Отчёты: `plans/reports/round1020_ui_rework_reviewer.md`, `plans/reports/round1020_ui_rework_scanner_audit.md`.
- **Тесты:** 6546 → **6574 passed / 0 failed** (**+28**: новые `tests/test_webapp_ui_rework_round1020.py` + `tests/js/round1020_ui_rework_test.js`); **red→green зафиксирован** (19 failed/7 passed → 26 passed); JS-гейты (`node --check web/app.js`, `JS-UNIT-OK`×2, `VUE-MOUNT-OK`, routing) чистые; `git diff --check` clean.
- **Инварианты:** меню-freeze (25 вкладок + 6 `NAV_ITEMS` + 12 карточек модулей); **каталог-Δ=0**; `services/**`, `web/api/**`, `web/app.py`, `bot.py`, БД, `web/static/vendor/**` — Δ=0; `APP_VERSION` без бампа; серверный feature-flag не вводился (откат — `git revert`).
- **Деплой (Step 9 @DevOps):** commit **`ec93c3d`**, запушено в origin/master; сервер **`racknerd-f4e3456`** — `systemctl` **active**, MainPID **2738993**, **NRestarts=0**; прод-`/web/static/app.css` подтверждён (`blur(16px)`, `rgba(20, 25, 30, 0.5)`, `#FF8A3D`, `6s`, `sticky-spacer`, `Cache-Control: no-store`); SQLite **`user_version=12`** (без изменений); каталог-Δ=0.
- **Архив:** спека/`ui-contract.md`/`tasks.md`/ADR — `plans/archive/round1020-ui-rework/` (перенесена `git mv` из `plans/features/`; 4 файла).
- **Остаточно (не блокеры):** ⏸ **живые WebView** (Telegram Android, Nekogram/iOS WKWebView) — фактическое применение `-webkit-backdrop-filter`, поведение `@focus select()`/`:has()`; ⏸ **скриншот-приёмка §7.5** (desktop 1440×900 / Android / Nekogram).
- **R18:** значения секретов не печатались/не цитировались (только маска и фейковые `last4`); R18 в силе, ignore-лист `plans/docs/r18_scanner_ignore.md`. R17 — Risk Accepted (без ротации/rewrite истории).

Источник: `plans/reports/round1020_ui_rework_scanner_audit.md`, `plans/reports/round1020_ui_rework_reviewer.md`, `plans/reports/global_map.md` (Round 10.20 UPD3), `plans/ARCHITECTURE.md` §46; KG `round1020-ui-rework` + `metric-snapshot-round1020-ui-rework-final`.

## Детали раунда 10.21 (18.09.2026)

- **Эпик:** `Epic round1021 (System 2 Reasoning & Memory Rebuild)` / релиз **`release-round1021`** (alias commit **`a923310`**); архитектура — `plans/ARCHITECTURE.md` **§47** (итог/ADR-карта/SUPERSEDE-AMEND-карта). **Длительность:** одна сессия **18.09.2026** (старт Step 0 → деплой Step 9 @DevOps).
- **Фичи (6, все COMPLETED + DEPLOYED + ARCHIVED; папки — `plans/archive/<feature>-round1021/`):**
  - F1 `multilayer-memory-extraction-round1021` — T-1943…T-1952 + T-2001…T-2005/T-2012/T-2013 (17) — двухслойный пайплайн `LoreWorker._classify_dossier` (Слой А Thinker/scratchpad → Python-фильтр + Entity Resolution `_window_names` → Слой Б Synthesizer, per-target портреты/паттерны/мемы, анти-цитатный валидатор >6 слов); портрет — производная `graph_facts.status='dossier_portrait'` (**Δ DDL=0**), kill-switch env-only `MULTILAYER_EXTRACTION_ENABLED` (default **ON**).
  - F2 `factchecker-grounding-cove-round1021` — T-1953…T-1961 + T-2014/T-2015/T-2016 (12) — `services/grounding_validator.py` (`collect_allowed_anchors` только из доверенных источников, `strip_phantom_tags`); CoVe скрытый `<reasoning>`-черновик (+0 LLM); флага нет, Δ=0.
  - F3 `de-robotization-negative-constraints-round1021` — T-1962…T-1970 (9) — `services/prompt_style_blocks.py` (`ANTI_BOT_BLOCK`/`ASYMMETRY_BLOCK`), 8 канонов base+suffix; снята троп-фраза «уже проверял … не повторять дважды»; атомарная канон-миграция ADR-1013-3 (PREV_*_R1021, `PROMPT_MIGRATIONS` + обратный `rollback_prompt_canons`). `ROLLBACK.md` — в архиве.
  - F4 `paradigm-thresholds-consolidation-round1021` — T-1971…T-1979 + T-2009/T-2010/T-2011/T-2017 (13) — READ-ONLY аудит `plans/reports/round1021_paradigm_audit.md` (корень — выключенные `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`, ветвь A), `services/memory_maintenance.consolidate` CLI-only; env-only `DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED` (default **OFF**). `audit.md` — в архиве.
  - F5 `memory-rebuild-sanitation-round1021` — T-1980…T-1989 + T-2006/T-2007/T-2008/T-2018 (14) — `manage.py memory` (rebuild-dossiers/sanitize-beliefs/consolidate/audit); инварианты `imported-history-immutable` + `manual-overrides-immutable`; guard целевого чата `-1002661910336`; allowlist `assert_derived_table`, авто-бэкап + JSONL до DELETE.
  - F6 `ui-audit-puppeteer-round1021` — T-1990…T-2000 (11) — реальный браузерный E2E-аудит; Puppeteer MCP недоступен → Playwright 1.62 + Chromium 151 (`tools/ui_audit_round1021.py` + `UI_AUDIT_REPORT.md`); закрыты F6-01 (High `_syntheticGroup` computed→methods) и F6-02/L-4 (`positionScopePanel`); M-1 sticky 88px → gap 0–0.4px; меню-freeze 25/6/12.
- **Ревью/аудит:** @Reviewer — **2 итерации `Needs fixes` → `Approved` на 3-й**; @Scanner первичный diff-based скан — **0 Critical / 0 High** (2 Medium `S10.21-1/-2` + 7 Low + 4 Info) → **re-audit после пост-скан фиксов — 0 Critical / 0 High / 0 Medium открыто** (S10.21-1/-2 и Low S10.21-3…-7/-9 закрыты); открыто **1 Low** `S10.21-8` (вне скоупа) + **N10.21-1/-2** + **4 Info**. @Builder — **2 фикс-раунда (по @Reviewer) + 1 пост-скан фикс-раунд**. Отчёты: `plans/reports/round1021_scanner_audit.md`, `plans/reports/round1021_paradigm_audit.md`, `UI_AUDIT_REPORT.md`, `plans/reports/global_map.md`.
- **Числа/инварианты:** pytest **6779 passed / 0 failed** (baseline 6574 → **+205**); каталог **439/409/414/92/90/20** (**Δ=0**); **SQLite v12**, **Δ DDL=0**; APP_VERSION **2.57.0** (без бампа); `node --check web/app.js` / `JS-UNIT-OK` / `VUE-MOUNT-OK` чистые; `git diff --check` clean; порядок роутеров `bot.py` не сдвинут; `.env`/`media/` не тронуты (только `.env.example`). `imported-history-immutable`, `manual-overrides-immutable`.
- **Архив (Step 8 @PM):** `plans/archive/<feature>-round1021/` — **6 папок** (`spec.md` + `tasks.md` + `ADR-1021-N`; у F3 — `ROLLBACK.md`, у F4 — `audit.md`), перенос `git mv` из `plans/features/`; `plans/features/` — 6 backlog-папок (round1021 отсутствует); R18-скан папок чист.
- **Деплой (Step 9 @DevOps):** commit **`29fc638`** (feat: System 2 Reasoning) + **`a923310`** (docs/plans: архивация + Merge §47 + отчёты); push `21cd54c..a923310` в origin/master; сервер `/var/www/admin_bot` fast-forward `ec93c3d..a923310`; `systemctl` **active** (PID **3023258**); бэкап `.env.bak.round1021…`; включены `DREAM_ENABLED=true`, `DEEP_SLEEP_ENABLED=true`, `BELIEF_DECAY_ENABLED=true` (ветвь A аудита F4); `/api/health` + `/healthz` = **200**; SQLite `user_version=12`; канон-миграция промптов применилась идемпотентно (8 ключей).
- **`memory consolidate --all`:** no-op (`candidates=0`) — все 52 confirmed-belief принадлежат целевому чату `-1002661910336`, исключённому из `--all` (инвариант guard); таргет не затронут; сырая история не тронута (`smart_messages` +4 = живой трафик).
- **R17/R18:** SSH-креды не цитировались; `plans/current_task.md` (untracked, `.gitignore:70`) не коммитился. R18 в силе (ignore-лист `plans/docs/r18_scanner_ignore.md`); R17 — **Risk Accepted** (SSH-пароль в истории git, ротация не делалась).

## Техдолг раунда 10.21 (Low 3 + Info 4, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.21-8` | Low | Парадигмы CLI-консолидации без vec-эмбеддинга (`services/memory_maintenance.py:785` — `DreamWorker(db, memory=None, llm=None)`): видны FTS-ветке RAG, но не KNN/`vector_search` L3 (косметика RAG-ветки; вне скоупа фиксов) |
| `N10.21-1` | Low | Нет регресс-тестов на фиксы `_chat_roster`/`roster_incomplete`/`belief_source`/`initialize_readonly`/пустой Слой Б (подтверждены ad-hoc пробами @Scanner; будущая регрессия не поймается CI) |
| `N10.21-2` | Low | Бинарный гард `roster_incomplete` по `independent > 0` — остаточный риск Medium `S10.21-2` (теоретический false-positive); страховки авто-бэкап + JSONL + `--dry-run` сохранены |
| `S10.21-10` | Info | Хардкод персонального TG-id `ADMIN_ID` в `tools/ui_audit_round1021.py` |
| `S10.21-11` | Info | `memory audit` на «чужой» БД молча даёт нули (не различает «схема отсутствует»/«пустая память») |
| `S10.21-12` | Info | `_MONTH_RE` извлекает `MM.YYYY` из `DD.MM.YYYY` — нестрогое сопоставление |
| `S10.21-13` | Info | Класс-счётчик `orphan_fact` инкрементируется до перезаписи — косметика отчёта |
| **Наследие** | — | `S10.19-15`/`S10.19-23` (Low 10.19), `S10.18-29` (Low 10.18), 5 Info 10.20 (`S10.20-18…-22`), follow-up **T-1932** (fallback точки 7 `CONTEXT_POINTS`) — не входили в 10.21 |
| **Остаточные приёмки** | — | ⏸ Telegram **WebView не воспроизводился** (headless ≠ WebView) — унаследованное ограничение F6; **IRONY-развязка** — подтвердить в живом прогоне; Puppeteer MCP недоступен → fallback Playwright зафиксирован честно |
| **R17-history-risk** | **Risk → ACCEPTED** | SSH-пароль в истории git — ротация **не делалась**, история не переписывалась; значение не цитировалось (R18) |

Источник: `plans/reports/round1021_scanner_audit.md` (§«Re-audit после пост-скан фиксов»), `plans/reports/round1021_paradigm_audit.md`, `plans/reports/global_map.md` (Round 10.21), `plans/backlog.md` (ИТОГ 10.21), `plans/ARCHITECTURE.md` §47/§25; KG `release-round1021` + `metric-snapshot-round1021-final` + `tech-debt-round10.21`.

## Детали раунда 10.22 (18–19.09.2026)

- **Эпик:** `Epic round1022 (True System 2 Pipeline & UI Help)` / релиз **`release-round1022`** (alias commit **`a8a6437`**); архитектура — `plans/ARCHITECTURE.md` **§48** (итог/ADR-карта/SUPERSEDE-AMEND-карта). **Длительность:** одна сессия **18–19.09.2026** (Step 0 18.09 → деплой Step 9 @DevOps 19.09.2026); UPD3 (Human Gate пройден владельцем, Д-1…Д-11).
- **Фичи (8, все COMPLETED + DEPLOYED + ARCHIVED; папки — `plans/archive/<feature>-round1022/`):**
  - F1 `urgent-rebuild-dossiers-target-chat-round1022` — T-2019…T-2027 + T-2090/T-2091 (11) — примитив `services/memory_rebuild.py::cleanup_confirmed_dossier_facts` (fail-closed `снимок → JSONL-архив → сверка → guard-DELETE`, keyset-пагинация, защита `source_ids` живых beliefs); окно боевого прогона **180 дней** (4320ч), `--target-chat`; кросс-процессный per-chat file-lock (общий с F8); инварианты `imported-history-immutable`/`manual-overrides-immutable`; Δ DDL=0.
  - F2 `urgent-summary-aliases-ui-round1022` — T-2028…T-2034 (7) — `_ensure_keyvalue_object` в `web/api/routes.py` (строка-JSON → объект до 2 уровней, иначе `{}`+WARNING) + фронт `web/app.js` KV-editor `sync()` зеркалит `JSON.parse`; restore из бэкапа запрещён; Δ каталога=0.
  - F3 `system2-factcheck-two-call-round1022` — T-2035…T-2043 + T-2094 (10) — `FactCheckService._check_claim_two_call`: Stage-1 **Аналитик** (JSON, tool-loop ≤4, grounding-якоря, human-time) → Stage-2 **Вербализатор** (только JSON); fallback 10.21; флаг `SYSTEM2_FACTCHECK_ENABLED` (ON).
  - F4 `system2-summary-two-call-round1022` — T-2044…T-2052 + T-2095 (10) — `SummaryGenerator._generate_two_call`: Stage-1 **Редактор** (Markdown-выжимка, отсев архива, единственный потребитель RAG) → Stage-2 **Рассказчик** (plain R11); стриминг/чанки не тронуты; флаг `SYSTEM2_SUMMARY_ENABLED` (ON).
  - F5 `system2-direct-chat-two-call-round1022` — T-2053…T-2061 + T-2096 (10) — `DirectChatService._synthesize_direct_answer`: Stage-1 **Синтезатор тулов** (R17-`redact_secrets(tool_context)` + tool_trace → JSON) → Stage-2 **Вербализатор**; System 2 только при непустом tool_trace (degraded/lore_compiled вне); флаг `SYSTEM2_DIRECT_ENABLED` (ON).
  - F6 `telegram-send-regex-guard-round1022` — T-2062…T-2069 + T-2092/T-2093 (10) — `services/outgoing_guard.py::sanitize_outgoing` (reuse `strip_reasoning_tags` + `\bfact:\d+\b`/`\bmsg:\d+\b`, no-op без паттернов, fail-closed, идемпотентно; клише **не** вырезаются) + chokepoint `services/telegram_send.py`; `services/negative_constraints.py` (`find_forbidden_cliches → codes` + `verbalize_validated(max_retries=2)`); флаги `TELEGRAM_SEND_GUARD_ENABLED`/`SYSTEM2_VALIDATOR_LOOP_ENABLED` (ON).
  - F7 `help-ui-system2-round1022` — T-2070…T-2076 (7) — Справка **v4** (`INFO_CANON_VERSION 3→4`): только h1/h2, команды в `<blockquote>`, удалён п.11 «Безлимиты», добавлен блок «Как бот думает (System 2)»; `PREV_R1022_DEFAULT_INFO_TEXT` в `KNOWN_INFO_SNAPSHOTS`, байт-тест `info_text.md`, идемпотентная PG-миграция `content.info_how_it_works`.
  - F8 `dossier-rebuild-async-ui-round1022` — T-2077…T-2089 (13) — `services/dossier_rebuild_jobs.py` (файловый JSON-job-store без DDL, стартовый user-scoped снапшот/rollback, lock TTL 6ч, `interrupted` при рестарте) + 4 эндпоинта в `web/api/chat_lore.py` + UI-кнопка «Пересобрать досье» (30/90/180/Всё время), прогресс «X/Y чанков», persistence при reopen, отмена-с-откатом; флаг `DOSSIER_REBUILD_UI_ENABLED` (ON, OFF → 404).
- **Ревью/аудит:** @Reviewer — **2 итерации `Needs fixes` → `Approved` на 3-й**; @Scanner первичный diff-based скан — **0 Critical / 0 High** (2 Medium `S10.22-1/-2` + 4 Low + 3 Info) → пост-скан фиксы (@Builder) → **re-audit: 0 Critical / 0 High / 0 Medium / 0 Low открыто** (1 Info **S10.22-4b**). @Builder — **3 фикс-раунда** (2 по @Reviewer + 1 пост-скан). Отчёты: `plans/reports/round1022_scanner_audit.md`, `plans/reports/audit_backlog.md`, `plans/reports/global_map.md` (Round 10.22).
- **Числа/инварианты:** pytest **6962 passed / 0 failed** (baseline 6779 → **+183**); каталог **439/409/414/92/90/20** (**Δ=0**); **SQLite v12**, **Δ DDL=0**; APP_VERSION **2.57.0** (без бампа); JS-гейты (`node --check web/app.js`, `ALIASES-UNIT-OK`, `DOSSIER-REBUILD-UNIT-OK`, help) зелёные; `git diff --check` чист; порядок роутеров `bot.py` не сдвинут (только DI-kwargs); `.env`/`media/` не тронуты (`.env.example` дополнен). Инварианты `imported-history-immutable`, `manual-overrides-immutable`. Канон-миграция ADR-1013-3 атомарна (`PREV_*_R1022` над 8 канонами + `rollback_prompt_canons`).
- **Боевой прогон пересборки досье (F1, чат `-1002661910336`, Step 9 @DevOps):** CLI-отчёт `scanned=451 cleaned_facts=441 protected_belief_sources=10 rebuilt=2 window_hours_used=4320 backup=yes`; confirmed target-факты **451 → 10** (cleaned=441), `dossier_portrait` **0 → 12**, `chat_meme` **0 → 2**; beliefs **71/41** и nodes/edges/overrides — без изменений; `smart_messages` **не удалялись** (+живой трафик). JSONL-архив `memory_generated_confirmed_20260918_144249_877827.jsonl` (441 строка) + авто-бэкап 802 МБ. Старый мусор в portraits/memes = **0**.
- **Архив (Step 8 @PM):** `plans/archive/<feature>-round1022/` — **8 папок** (`spec.md` + `tasks.md` + `ADR-1022-N`), перенос `git mv` из `plans/features/`; карта решений `plans/features/round1022-human-gate-map.md` → `plans/archive/round1022-human-gate-map.md`; `plans/features/` — 6 backlog-папок (round1022 отсутствует); R18-скан папок чист.
- **Деплой (Step 9 @DevOps, 19.09.2026):** commit **`2d153b5`** (feat: True System 2 Pipeline) + **`a8a6437`** (docs/plans: архивация + Merge §48 + Scanner re-audit); push `acd9311..a8a6437`; сервер `/var/www/admin_bot` → **`a8a6437`**; `systemctl` **active**; `/api/health` + `/healthz` = **200**; SQLite `user_version=12`; `INFO_CANON_VERSION=4`; env-флаги default ON (`SYSTEM2_*`, `TELEGRAM_SEND_GUARD_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED`).
- **R17/R18:** SSH-креды не цитировались; `plans/current_task.md` (untracked, `.gitignore:70`) не коммитился. R17 — **Risk Accepted** (SSH-пароль в истории git, ротация не делалась); R18 в силе (ignore-лист `plans/docs/r18_scanner_ignore.md`).

## Техдолг раунда 10.22 (Info 1 + follow-up, открыт)

| ID | Severity | Суть |
|---|---|---|
| `S10.22-4b` | Info | Детектор клише `as_ai` ложно срабатывает при запятой между субъектом и «как» («Он, как искусственный интеллект…» → `['as_ai']`); эффект — редкая лишняя регенерация, не блокер; ремедиация — lookbehind с опциональной запятой |
| CLI LLM-key | follow-up | CLI `manage.py memory` берёт LLM-ключ из `.env`, а не из PG (root cause **401 при первом боевом прогоне**); боевой прогон выполнен с runtime-ключами; нужна синхронизация `.env`/ConfigCache в CLI |
| F8 vec-слой | accepted | Rollback F8 не восстанавливает vec-эмбеддинги (best-effort, embeddings не в снапшоте) — задокументировано |
| F8 stale-lock TTL | accepted | `DOSSIER_REBUILD_LOCK_TTL_SECONDS` (6ч) допускает «stale takeover»; lock не снимается при рестарте; job-store — single-writer in-process |
| R7 ADR-1022-1 | accepted | F1/F8 могут удалить валидные `confirmed`-факты без swap-порядка «извлечь→заменить»; компенсация — авто-бэкап + JSONL-архив + стартовый снапшот F8 |
| **Наследие** | — | S10.21-8 (Low, vec-эмбеддинги парадигм CLI), N10.21-1/-2, 4 Info S10.21-10…-13, 5 Info 10.20, `S10.18-29`, `S10.19-15/-23`, follow-up **T-1932** (fallback точки 7 `CONTEXT_POINTS`) — не входили в 10.22 |

Источник: `plans/reports/round1022_scanner_audit.md`, `plans/reports/audit_backlog.md`, `plans/reports/global_map.md` (Round 10.22), `plans/backlog.md` (ИТОГ 10.22), `plans/ARCHITECTURE.md` §48/§25; KG `release-round1022` + `metric-snapshot-round1022-final` + `tech-debt-round10.22`.

## Детали раунда 10.23 (19.09.2026)

- **Эпик:** `Epic round1023 (Adaptive System 2, Token Analytics, Anti-Cliche Cache & Image Generation)` / релиз **`release-round1023`** (alias commit **`4314ea4`**); архитектура — `plans/ARCHITECTURE.md` **§49** (итог/ADR-карта/SUPERSEDE-AMEND-карта, @Architect Merge). **Длительность:** одна сессия **19.09.2026** (Step 0 → Step 10 @Memory).
- **Статус:** **COMPLETED + DEPLOYED + ARCHIVED** (Step 8 @PM → Step 9 @DevOps → Step 10 @Memory, 19.09.2026).
- **База → финал:** HEAD `731a845` → **`8dadbe3`** (feat/фиксы) → **`4314ea4`** (docs/plans); pytest **6962 → 7424 passed / 0 failed** (**+462**; 1 сторонний `StarletteDeprecationWarning`).
- **Фичи (9, COMPLETED + DEPLOYED + ARCHIVED — папки `plans/archive/<feature>-round1023/`):** F1 `target-message-marking-round1023`, F2 `factcheck-deep-context-round1023`, F3 `verbalizer-response-modes-round1023`, F4 `dynamic-anticliche-cache-round1023`, F5 `image-generation-tool-round1023`, F6 `summary-cover-rich-article-round1023`, F7 `token-analytics-dashboard-round1023`, F8 `ui-verbilizer-tabs-round1023`, F9 `help-ui-v5-round1023` — задачи **T-2097…T-2186** (90), **ADR-1023-1…-9** (Accepted/реализованы).
- **Ревью/аудит:** @Reviewer — **Approved по всем 9 фичам**, всего **21 прогон** (итерации: F1=2, F2=3, F3=3, F4=2, F5=2, F6=2, F7=2, F8=2, F9=3); @Builder — **12 циклов доработок** + **1 scanner follow-up**. @Scanner (независимый re-audit, `plans/reports/round1023_scanner_audit.md`) — **0 Critical / 0 High**; 2 Medium (**M1** correlation-id изображений, **M2** изоляция `response_mode` в Stage-2) **закрыты follow-up-коммитом `8dadbe3`** (`system2_handoff.stage2_payload` + проброс `correlation_id`, +6 регресс-тестов); открыто **4 Low (L1–L4) + 4 Info (I1–I4)** → техдолг 10.23.
- **Числа/инварианты (по @Scanner):** каталог **REGISTRY 457** (Δ+18: F2 +2, F5 +5, F6 +1, F8 +10), Settings **416**, GROUPS **96**, `_TAB_BY_GROUP` **94**; **SQLite `user_version=12` (Δ DDL=0**; новые таблицы только в PG: `anticliche_cache`, `llm_usage_events`, `llm_model_prices`); канон-миграции info **v4→v5** (`INFO_CANON_VERSION=5`), guide **v1→v2** (`GUIDE_CANON_VERSION=2`) идемпотентны; `node --check web/app.js` — OK; порядок роутеров `bot.py` не сдвинут (только DI-kwargs + воркер вне гейта). Инварианты `imported-history-immutable` / `manual-overrides-immutable` — ✅.
- **Флаги (env-only `ClassVar`, default ON):** `SMART_VERBALIZER_MODES_ENABLED` (F3), `DYNAMIC_ANTICLICHE_ENABLED` (F4), `IMAGE_GENERATION_ENABLED` (F5), `SUMMARY_COVER_ARTICLE_ENABLED` (F6), `TOKEN_ANALYTICS_ENABLED` (F7); поэтапная раскатка internal→10%→50%→100% не требуется.
- **Архитектура:** `plans/ARCHITECTURE.md` **§49** (итог/ADR-карта, @Architect Merge).
- **Архив (Step 8 @PM):** `plans/archive/<feature>-round1023/` — **9 папок** (`spec.md` + `tasks.md` + `ADR-1023-N`; 4 трекнутых — `git mv`, 5 untracked — обычный move); `plans/features/round1023-architecture.md` → `plans/archive/round1023-architecture.md`; `plans/features/` — только 6 backlog-папок; R18-скан чист.
- **Деплой (Step 9 @DevOps, 19.09.2026):** commit **`8dadbe3`** (feat/фиксы) + **`4314ea4`** (docs/plans: архивация + Merge §49 + Scanner-аудит); push origin/master **`731a845..4314ea4`**; прод **`/var/www/admin_bot`** — `git pull --ff-only` → HEAD origin/master (**`4314ea4`**); venv aiogram обновлён (≥3.31.0); `.env` — добавлены `IMAGE_API_KEY` (значение не фиксируется, R18) и `IMAGE_BASE_URL=https://gen.pollinations.ai/v1`; `systemctl restart admin_bot` → **active**; `/api/health` = **200**, `/healthz` = **200**; `canon=5 delivered=5`, `guide=2 delivered=2`; воркер `AntiClicheWorker` зарегистрирован (`interval_days=7`); SQLite `user_version=12`; PG-миграции идемпотентны (3 таблицы).
- **Ручные приёмки владельца (⏸ живые, за владельцем):** **T-2135** (F4 — воркер/UI клише), **T-2146** (F5 — генерация изображения), **T-2156** (F6 — Article+обложка), **T-2175** (F8 — UI-табы/монитор), **T-2182** (F9 — Справка v5).
- **R17/R18:** SSH/креды и значение `IMAGE_API_KEY` не цитировались; `plans/current_task.md` (untracked, `.gitignore`) не коммитился; R18 в силе (ignore-лист `plans/docs/r18_scanner_ignore.md`); R17 — **Risk Accepted** (SSH-пароль в истории git, ротация не делалась).

## Техдолг раунда 10.23 (Low 4 + Info 4, открыт)

| ID | Severity | Суть |
|---|---|---|
| `L1` | Low (F5 / ADR-1023-5 OQ-1) | `image_calls` — отдельный счётчик при том же значении лимита, что `llm_calls` → потенциально двойной платный бюджет (подтвердить семантику с владельцем) |
| `L2` | Low (F6) | `_strip_safe_html` применяется и к rich-каналу → затирает инлайновые `<b>/<i>` (применять strip только при канале `plain`) |
| `L3` | Low (F5) | `_download_bytes` качает управляемый провайдером URL без проверки хоста/схемы и без стрим-лимита (риск низкий, URL admin-only) |
| `L4` | Low (F2) | Одноразовая миграция `factcheck_context_messages` шумит WARNING на каждом старте при заданном владельцем `before` (идемпотентна, безвредно) |
| `I1` | Info (F2) | `thread_chain` при `depth=0` возвращает 1 ход (`max(1, depth)`) |
| `I2` | Info (F5) | Устаревший комментарий «7 инструментов» в `services/tool_schemas.py` (фактически 9); doc-only |
| `I3` | Info | Fallback `SYSTEM2_*` может дать 3-й физический LLM-вызов (Stage-2 пустой → одиночный путь); analytics пишет `step=single` |
| `I4` | Info (F5) | `send_photo` не покрыт регэкспом egress-сканера (`test_outgoing_guard_round1022._SEND_RE`) |

Источник: `plans/reports/round1023_scanner_audit.md`, `plans/backlog.md` (ИТОГ 10.23), `plans/ARCHITECTURE.md` §49; KG `release-round1023` + `metric-snapshot-round1023-final` + `tech-debt-round10.23`.
