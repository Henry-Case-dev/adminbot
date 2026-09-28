# deployment.md — mca-asap2-summary-pipeline (ASAP-деплой 2.58.33 на прод)

- **Feature-ID:** `mca-asap2-summary-pipeline`
- **Дата деплоя:** 2026-09-28, окно 06:18–07:05 UTC (локально Владивосток ~18:18–19:05, +12)
- **Статус: VERIFIED**
- **Разрешение:** @Reviewer `Approved` (review.md, раунд 2, binding D0A5E27C; оба линза — requirements-лэнс раунда 1 + focused change-audit дельты) + приказ владельца (продолжение прерванной delivery, T-3963: «деплой в прод фиксов по саммари»).

## 1. Связка с ревью (binding)

- **Reviewed-Commit (feat):** `3e8594b` — «fix(round1027): ASAP-2 Summary dual-circuit … (APP_VERSION 2.58.33)»; **docs:** `c0f299c` (plans features + аннотации + README). push выполнен прерванной сессией: origin/master = `c0f299c` (проверено).
- **Scope tracked-diff SHA-256 (канонический 35-файловый список из review.md раунд 2):** `git diff e882d58 3e8594b -- <35 файлов>` → SHA-256 **`D0A5E27CB61D60CA088882D65E5A8EA324EE6CA06FD2B6183C85735399E64918`**, размер **463 919 байт** — побайтово совпал с биндингом раунда 2 (независимый пересчёт DevOps, `git diff --output` raw-байты + Get-FileHash).
- **Состав коммита:** ровно **44 файла** = 35 scope-M + 9 A (untracked-таблица раунда 1); `handlers/summary.py` и `web/index.html` в коммит НЕ вошли (M1/M2 соблюдены). Все 9 untracked-пинов sha256 (summary_l1_repair, hybrid_budget, 6 pytest-файлов, JS-харнесс) пересчитаны на блобах `3e8594b` — **9/9 совпали**.
- **Spec-Hash:** `C30AABC49CC3E996C7CBF072A154FCD7EA7E8C0963974F9ACEE34B30F67C12DC` — не менялся (review раунд 2 ✅). Дрейфа нет.
- **D-3 (долг раунда 2):** плейсхолдеры в `evidence.md` «Прогоны после rework-раунда 1» ОТСУТСТВУЮТ в committed-версии `c0f299c` — фактические счётчики **73 passed / 0 failed** и **1168 passed / 0 failed / 8745 deselected** с отметкой «подтверждено независимым прогоном Reviewer, round2» уже закоммичены. Отдельный docs-коммит `docs(plans): ASAP-2 evidence — rework run counters (D-3)` НЕ потребовался (no-op).

## 2. Прод до деплоя (идемпотентность)

- Прод HEAD **до**: `c0f299c` — pull прерванной сессией уже выполнен, tracked-дерево чистое; НО процесс сервиса был стартован **2026-09-27 08:06:55 UTC** (MainPID 1547594, эпоха ASAP-1) — **старше коммитов фичи** (созданы 2026-09-28 05:38–05:39 UTC) → работающий бот держал в памяти код **2.58.32**. Disk-версия `config/settings.py` = 2.58.33 (свежий python-процесс читал диск).
- **Вывод:** недостающий шаг деплоя — рестарт `admin_bot` (код на диске уже целевой). `git pull --ff-only` не требовался (уже fast-forward до `c0f299c`).
- .env: Δ env=0 — новых ключей не требует (kill-switch'и default ON); SUMMARY_* в .env — только legacy-ключи (TIMEZONE/ALIASES/ADMIN_ONLY/THROTTLE/MAX_CONTEXT_TOKENS), конфликтующих нет. systemd-unit Environment — пусто. PG `limits.max_summary_parts` = **6** (сохранён с ASAP-1).

## 3. Рестарты и старт (сервер `198.46.175.136`, `/var/www/admin_bot`, systemd `admin_bot`)

| Шаг | Результат |
|---|---|
| рестарт #1 (06:19:30 UTC) | rc=0; active через ~3 с (TimeoutStopSec/SIGKILL НЕ сработали — остановка быстрая); MainPID **1808464**, NRestarts=0 |
| старт-лог | `[pg_db] starter bot_settings seeded: 423 (ON CONFLICT DO NOTHING)`, `[config_cache] initialized: settings=442 roles=4 admins=3`, `[prompt_migration] уже новый канон` ×11, **`[prompt_migration] канон обновлён \| key=prompts.summary_l1_clusterizer_system_prompt`** и **`…summary_l2_writer_system_prompt`** — идемпотентная канон-миграция R1027 применилась (кастомы владельца не тронуты), polling/lifespan поднялись |
| новые Traceback/ERROR (окно старта) | **0** |
| health | `GET http://127.0.0.1:8000/api/health` → `{"status":"ok"}` **HTTP 200** |
| рестарт #2 (06:45:47 UTC) | rc=0; active ~3 с; MainPID **1814733** — выполнен после PG-сида (см. §5), health 200 |
| runtime-версия | `venv/bin/python -c "from config.settings import APP_VERSION"` → **2.58.33** (disk); поведенческое подтверждение — §18-события нового пайплайна (L1_PARSE/L1_REPAIR/L1_CORRECTION_RETRY/L1_FALLBACK_PACKAGE) в логе смоука (§6) |

## 4. Проверки post-deploy

| # | Проверка | Факт | Вывод |
|---|---|---|---|
| 1 | Hot-ключи каталога резолвятся (`hot.get`: PG → env → код-дефолт) | `limits.summary_hybrid_target_chars=6500`, `_max_chars=24000`, `_response_mode=serious`, `_context_tokens=30000`, `_context_chars=120000`, `flags.summary_hybrid_l1_repair_enabled=True`, `…_l1_retry_enabled=True`, `flags.summary_legacy_fallback_enabled=True`, `flags.summary_hybrid_l2_enabled=True` (probe на проде, свежий процесс на коде 2.58.33) | ✅ PASS |
| 2 | `limits.max_summary_parts` | PG = **6** (не изменился); в UI LEGACY-секции значение 6, подпись дословная «Не влияет на Hybrid Article» | ✅ PASS |
| 3 | ΔDDL=0 | в 44-файловом коммите нет `services/database.py`/миграций; SQLite `PRAGMA user_version` = 12 (без изменений; никаких migration-строк в стартовом журнале), `[pg_db] DDL ok` — рутинный идемпотентный проход | ✅ PASS |
| 4 | Смоук саммари `-1002661910336` штатным механизмом | §18-цепочка целиком на 2.58.33 (см. §6), публикация состоялась | ✅ PASS |
| 5 | Живой браузер miniapp (prod) | S5 save-reload обеих секций + S6 mobile 390×844 (см. §7) | ✅ PASS |
| 6 | Живой бот после смоука/сидов/рестартов | active, health 200, NRestarts=0; Traceback/ERROR в окне — только известный класс nano-gpt-таймаутов (ReadTimeout/total_budget_exceeded) + fail-soft `graph extract failed — batch kept, pipeline continues`; параллельный крон-саммари 06:28 с `L1_ERROR llm_timeout` — recovery-контракт, не регресс | ✅ PASS |

## 5. Находка деплоя и remediation (PG-only ключи не сидируются)

- **Факт:** 16 новых PG-only ключей каталога (`_SUMMARY_HYBRID_PG_ONLY`; settings_field/code_source = None) пропускаются сидом `pg_db._seed_settings` (ветка `else: continue`), `iter_pg_only()` нигде не используется → строк в `bot_settings` нет → `GET /api/config` (итерация по строкам PG, routes.py:466) их не отдаёт → **workspace-вкладка HYBRID SUMMARY пуста и скрыта** (`workspaceTabHasContent`), в LEGACY-секции видны только старые ключи с строками. Пайплайн НЕ затронут (резолв кодовых дефолтов доказан probe и смоуком: L2_START `response_mode=serious target_chars=6500`).
- **Remediation (data-op уровня деплоя, прецедент ASAP-1 §4):** сид **14 не-секретных ключей** дефолтами каталога `INSERT … ON CONFLICT (key) DO NOTHING` (4 flags=true, 6 limits: 30000/120000/serious/6500/8/24000, 4 models="" — пусто = наследование основной модели по `resolve_l1_slot`, поведение идентично). Секреты `keys.summary_l1/l2_api_key` намеренно НЕ сажаются (правило сида: пусто = наследование ключа основной модели, R17). ΔDDL=0, reviewed-код не менялся.
- После сида — рестарт #2 (внешняя SQL-правка не подхватывается живым ConfigCache) → **вкладка HYBRID SUMMARY появилась**, состав полей полный.
- **Follow-up (вне этой delivery, кандидат в следующий review-раунд):** системный фикс — либо code_source/сид для PG-only записей, либо синтез catalog-only записей в `GET /api/config` (иначе на каждой чистой установке вкладка HYBRID скрыта до первой ручной записи). Не блокёр: значения = кодовые дефолты, пайплайн работает.

## 6. Смоук саммари (штатный механизм, §18-цепочка)

Запуск: one-off раннер на сервере (зеркало wiring'а bot.py on_startup «SmartModule: Summary» БЕЗ polling/scheduler'ов: ConfigCache → DatabaseService → LLMClient → AliasResolver → MemoryManager → SummaryGenerator → `generate_and_send(chat, manual=True)` — вход команды `/summary`). Скрипт `/home/nik/asap2_summary_smoke.py`, лог `/home/nik/asap2_smoke.log`. R17: секреты не печатаются.

`run_id=6746f5194a754145989489e864b71364`, 06:24:49–06:30:48 UTC (duration 359 s):

| Этап | Событие | Факт |
|---|---|---|
| START | `SUMMARY_START` | mode=**hybrid_l2**, manual=True, source_count=333 |
| FILTER | `FILTER_COMPLETE` | messages_before=333 → after=329, restored=29, drop 9.9%, **serialized_chars=0, serialized_tokens=21255** (новые поля ✅) |
| L1 | `L1_START` | messages=329, tokens_est=20943, chunks=1, deepseek-v4.1-flash@nano-gpt, dedicated=False |
| L1 | `L1_PARSE` (новое ✅) | attempt=1, parse_status=ok |
| L1 | `L1_REPAIR` (новое ✅) | deterministic repair: **unknown_ids_removed=7**, topics_removed=1 → topics_after=0 → useless=1 (`no_topics`) |
| L1 | `L1_CORRECTION_RETRY` (новое ✅) | attempt=1/2, reason=`l1_useless_after_repair` (контракт §15) |
| L1 | 2-я попытка → `llm_timeout` → **`L1_FALLBACK_PACKAGE`** (новое ✅) | LEVEL-2 fail-soft: fragments=30, chronology=329 (0 LLM) |
| L2 | `L2_START` | **response_mode=serious, target_chars=6500, target_paragraphs=8** (резолв hot-ключей виден в событии) |
| L2 | `L2_COMPLETE` | chars=2906, paragraphs=8, status=ok, **без `trimmed=`** (trim-костыль удалён) |
| COVER | `COVER_START` → `COVER_COMPLETE` | status=ok (84 s) |
| FORMAT | `FORMAT_START`/`FORMAT_COMPLETE` | channel=rich, paragraphs=8, ok |
| PUBLISH | `PUBLISH_RICH_START` → **`PUBLISH_RICH_COMPLETE`** | sendRichMessage, **message_id=1116138** — публикация состоялась |
| DONE | `SUMMARY_COMPLETE` | status=ok, **fallback=none, publication_status=ok** (новые поля ✅) |

Fail-soft-матрица проверена живьём: L1 деградировал (repair → correction-retry → таймаут) → LEVEL-2 fallback-пакет → L2 → полная статья опубликована через rich. Raw-тексты/секреты в событиях отсутствуют.

## 7. Browser smoke (живой прод, `https://admin-bot.duckdns.org/web/`)

Механизм auth: подписанный TMA initData сгенерирован НА СЕРВЕРЕ (`/home/nik/gen_initdata.py`, HMAC «WebAppData» от `settings.API_TOKEN`; токен не покидал сервер и не попал в evidence), инжект в `sessionStorage['adminbot.initData']` (фолбек app.js вне TG), свежесть ≤24 ч. Сессия: «Никита», роль admin. Playwright MCP, вьюпорты 1440×900 / 390×844.

| Сценарий | Результат |
|---|---|
| S1 | `#/modules/summary`: workspace-вкладки **«HYBRID SUMMARY»** и **«LEGACY SUMMARY FALLBACK»** раздельно, общие параметры вне секций ✅ (скриншоты ниже) |
| S5 (HYBRID) | «Локальный ремонт ответа L1» (`flags.summary_hybrid_l1_repair_enabled`): toggle → **ровно 1 POST `/api/config`** `{"items":[{"key":"flags.summary_hybrid_l1_repair_enabled","value":true}]}` → reload → значение сохранено ✅; режим `limits.summary_hybrid_response_mode`: serious→deep_research → 1 POST → reload → GET отражает deep_research ✅; **возврат serious → 1 POST → reload → serious** (прод в исходном дефолте, PG-проверка: repair=True, l2_enabled=True, mode=serious) |
| S6 (mobile 390×844) | HYBRID и LEGACY секции: `scrollWidth=390=clientWidth` — **0 горизонтального overflow**; тач-цели/описания читаемы ✅ (скриншоты ниже) |
| S7 (гигиена) | console: **0 errors** на всех шагах (warnings — некритичные); секретные значения не рендерятся; секретные слоты `keys.summary_l1/l2_api_key` не сажались (пусто = наследование, правило сида) |

Первичный прогон S5 выявил находку §5 (вкладка HYBRID скрыта из-за отсутствия PG-строк) — устранена сидом на месте, после чего все сценарии зелёные. Примечание: первые попытки программных кликов по тумблеру создали 3 POST-артефакта (чередование false/true/false) — след синтетических DOM-событий аудита, не продукта; финальный чистый прогон показал ровно 1 POST на сохранение, состояние прод-конфига восстановлено в дефолт и сверено по PG.

Скриншоты (untracked-артефакты в `tools/`):
- `tools/asap2_prod_s1_summary_desktop.png` — модуль «Саммаризация», обзор (desktop 1440×900)
- `tools/asap2_prod_s1_hybrid_desktop.png` — секция HYBRID SUMMARY (desktop)
- `tools/asap2_prod_s3_legacy_desktop.png` — секция LEGACY SUMMARY FALLBACK, MAX_SUMMARY_PARTS=6 (desktop)
- `tools/asap2_prod_s6_mobile_hybrid.png` — HYBRID (mobile 390×844)
- `tools/asap2_prod_s6_mobile_legacy.png` — LEGACY (mobile 390×844)

## 8. Откат (готовность)

- **Soft (весь трафик Legacy):** env `SUMMARY_HYBRID_L2_ENABLED=false` + рестарт → байт-в-байт OFF-путь `_run_legacy_pipeline` (верифицировано ревью, тест-пин default ON сохранён).
- **Soft (точечно):** hot-ключи каталога `flags.summary_hybrid_l1_repair_enabled` / `flags.summary_hybrid_l1_retry_enabled` / `flags.summary_legacy_fallback_enabled` → false (UI/POST /api/config, live) или env-слой `SUMMARY_L1_REPAIR_ENABLED`/`SUMMARY_L1_RETRY_ENABLED`/`SUMMARY_LEGACY_FALLBACK_ENABLED=false` + рестарт.
- **Промпты:** ROLLBACK-миграция на `PREV_SUMMARY_*_R1027`-слепки (ADR-1013-3).
- **Cold:** revert `3e8594b` на проде (прод-базис 2.58.32 = `270c277`); **ΔDDL=0 → откат чистый** (user_version не менялся, новых таблиц/колонок нет).
- **Обратимость сида §5:** `DELETE` 14 засеянных строк возвращает состояние «до сидa» (значения равны кодовым дефолтам — поведенческой разницы нет ни в одну сторону).

## 9. Итог

- **Deployed:** prod HEAD `c0f299c` (feat `3e8594b`), APP_VERSION **2.58.33**, MainPID 1814733 (с 06:45:47 UTC), health 200.
- **Статус: VERIFIED** — binding совпал побайтово, §18-цепочка и публикация подтверждены на живом проде, hot-ключи резолвятся, ΔDDL=0, miniapp S5/S6 зелёные после локальной remediation-операции данных (без изменения reviewed-кода).
- **Чужие файлы MCA-волны round1027 не тронуты:** git status до/после — M-список не расширился; сессия добавила только 5 untracked-PNG в `tools/` и этот `deployment.md`.
