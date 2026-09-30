# deployment.md — ASAP-3.2 `asap-32-runtime-reliability-graphrag-provider-discovery` (round1029, ВТОРОЙ цикл — полный релиз D1–D14)

> **Feature-ID:** `asap-32-runtime-reliability-graphrag-provider-discovery`
> **Risk-Level:** R3
> **Deploy:** `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, Ubuntu 24.04, venv `/var/www/admin_bot/venv`; sudoers — точный allowlist: `systemctl {start,stop,restart,status} admin_bot`, `journalctl -u admin_bot`)
> **Дата:** 01.10.2026 (сервер UTC 30.09 22:23–22:50; локальное 01.10 01:23–01:50 MSK)
> **Статус:** **VERIFIED** (деплой + все пост-деплой гейты пройдены; фоновый GraphRAG rebuild — под наблюдением, см. §7; честные границы — §8)

## 0. Binding (re-measure на commit-момент — N-ASAP32-8)

| Параметр | Review Round 2 (гейт) | На момент коммита (DevOps) | Вывод |
|---|---|---|---|
| Reviewed-Commit (HEAD) | `1287130b` | на момент старта цикла `3198cb5` (docs-коммиты цикла 1 поверх; код не менялся) | ✓ |
| Spec-Hash | `E0F752CB…878AA` | `E0F752CB…878AA` — совпадает (spec в архиве не менялся) | ✓ |
| Working-Tree-Hash (гейт) | `0f6e0f5fddc229c6fe626d663fb7e5cf7f16097dca045400deec3a5ae384bfa6` | гейт воспроизведён по существу: **per-file SHA-256 всех 10 релизных untracked-файлов = байт-в-байт манифесту гейта (10/10)**; полный pytest **10319 passed / 2 failed** — точное воспроизведение ревью-чисел (нулевой дрейф кода) | ✓ дрейф только служебный |
| WTH at-commit | — | **`cc525203aa53a2e8e1ce53512b4de8951ba825bb541d556903ba0f073ba6a9f3`** (манифест `plans/reports/asap32_wth_manifest_review.txt`, LF-рецепт Builder; HEAD `0483386`, staged=EMPTY, tracked-modified=4 — только чужие docs, 317 untracked-записей; исключения — сам манифест и этот файл, самореференс) | ✓ зафиксирован |
| ADR-1028-5 | гейт `24FD73A4…6874D` | архив `EE6D4B0F…` — объяснимо: reconcile @Architect (`1eab6d1`) добавил §7/§8 прод-валидации (docs-only, код не тронут; прецедент «approval не инвалидирован» §105) | ✓ |

> Примечание: упомянутый в задании гейт `d0203e00…dc9b` — биндинг предыдущей фичи EXTRA (`extra-cover-style-pipeline`), не ASAP-3.2; гейт ASAP-3.2 round 2 = `0f6e0f5f…4bfa6` (workflow_state/review.md).

## 1. Коммиты (пуш `3198cb5..4cb267a`, ff без force)

1. **FEAT `0483386`** — `feat(round1029): ASAP-3.2 full D1-D14 — GraphRAG shadow rebuild, Media Adapter/Policy, Text Capacity adapters, LLM-driven decision, EXTRA corrective UI (full release)` — **80 файлов, +6905/−643**:
   - **Зона A (GraphRAG):** `services/summary_memory.py` (severity-коалесинг §8/§67, typed rerank-парсер T-4193 + observability, startup-schedule hook); `services/graphrag_rebuild.py` — уже в `5aa4626` (цикл 1); тесты `test_graphrag_rebuild_asap32.py`, `test_rerank_contract_asap32.py`, allowlist-якорь `test_mca01_tx_task_supervisor_round1027.py`;
   - **Зона B (Media):** `services/media_execution.py` (новый, ~700 строк: ImageProviderAdapter/NanoGPT/OpenRouter, MediaExecutionPolicy 4 окна, durable MediaJobState на `task_jobs`, restart recovery, fallback §31, события §35), `image_generation.py`, `image_capabilities.py` (delta — auto-discovery), `cover_style_edit.py`/`cover_style_jobs.py` (stage-aware operation), `bot.py` (bind_db + recover_media_jobs), тесты `test_media_execution_asap32.py` + якоря (`test_unified_image_request_round1026` D5-санкция, `test_extra_cover_style_jobs`, `test_hotfix5…`, `test_capacity_resolver_asap31`, `test_auto_budget_asap31`);
   - **Зона C (Text Capacity):** `services/model_capacity.py` (NanoGPT `provider_catalog` / DeepSeek `verified_registry` / OpenRouter без регрессий, honest unknown), тест `test_capacity_nanogpt_asap32.py`;
   - **Зоны D/E (обязательные зависимости F-файла, часть ревью-кандидата D8/D9/D10):** `summary_generator.py`/`summary_test_run.py` (paged-L2-потребители; ядро зоны D — `summary_semantic_reduction.py`/`summary_fact_package.py` — уже на проде с цикла 1), `llm_client.py`/`tool_loop.py` (`fallback_payload_adapter` §45), `direct_chat_service.py` (содержит И zone-E recompose-вызов, И zone-F decision — файл неделим; без `tool_loop`/`llm_client` прод-инструментальная ветка падала бы TypeError), тесты `test_summary_semantic_reduction_asap32.py`, `test_direct_fallback_recompose_asap32.py`, `test_l2_budget_asap31`, summary-якоря;
   - **Зона F (LLM decision):** `services/direct_llm_react.py` (`<Decision_Task>` контракт, гейт-конъюнкция, kill-switch), `direct_chat_service.py` (demoted-матрица, 🗿 SILENT-ack), тесты `test_direct_llm_decision_asap32.py` + якоря `test_llm_react_asap31`/`test_direct_decision_matrix_asap3` (D11-санкция), `pytest.ini` (маркер asap32), `tests/conftest.py` (autouse-флаги);
   - **Зона H (EXTRA corrective):** `web/api/cover_styles.py` (PgDatabase-контракт, ~18 call sites), `services/pg_db.py` (PG-DDL 51→52, см. §4), `cover_style_registry.py` (connections CRUD, seed-инвариант), `cover_style_pipeline.py`, `bot.py` (seed ensure call-site), `web/index.html`/`web/app.js`/`web/static/app.css` (UI-редизайн §106–§114), `web/api/routes.py` (connections API), `param_catalog.py` (hidden-ключ §102) + F8-артефакты (`param-registry-round1025.*`, `screen-map-round1025.md`, `f8_baseline.json`), тест `test_cover_styles_contract_asap32.py` + якоря зоны H, erratum T-4226d в `plans/archive/extra-cover-style-pipeline-round1029/deployment.md`, `tools/ui_asap32_cover_styles_e2e.py`, README (v2.58.40).
2. **DOCS `4cb267a`** — `docs(round1029): ASAP-3.2 delivery round 2 …` — 5 файлов: `plans/reports/full_audit_results.md` (запись delivery round 2) + `plans/reports/asap32_wth_manifest_review.txt` (манифест at-commit `cc525203`) + 3 UI E2E-скриншота в каталоге фичи.
3. **DEPLOY-DOCS** — этот файл (коммит после верификации).

Чужой WIP не тронут и не закоммичен (§6).

## 2. Локальные гейты перед пушем

| # | Проверка | Результат |
|---|---|---|
| 1 | Полный pytest (`.venv`, чистый `__pycache__`) | **10319 passed / 2 failed** — оба якорные forbidden-paths (чужие); байт-паритет с review Round 2 |
| 2 | Целевой asap32-набор (8 файлов) | **102 passed** |
| 3 | JS (`node --test`, 52 файла) | **52 pass / 0 fail** |
| 4 | F8 `tools/gen_param_registry_round1025.py --check` | **CHECK OK**, реестр 488, Δ каталога = 0 |
| 5 | UI E2E `tools/ui_asap32_cover_styles_e2e.py` | **OK (RC=0)**; скриншоты в каталоге фичи |
| 6 | Свежие импорты новых модулей (`python -B`) | OK |
| 7 | R17-скан (added-строки + 10 новых файлов: sk-/xox/ghp/AKIA/PEM/tg-token/JWT/AIza) | **0 попаданий** |

## 3. Деплой

- Prod HEAD до: `f5054df` (2.58.40 инцидент-фикс). `git pull --ff-only origin master` → **`4cb267a`**. Дельта-скоуп проверен на проде: только ожидаемые префиксы (`services/`, `tests/`, `web/`, `tools/`, `bot.py`, `README.md`, `pytest.ini`, `plans/`).
- Пред-рестарт (прод, `venv/bin/python -B`): импорты `graphrag_rebuild`/`media_execution`/`model_capacity`/`direct_llm_react`/`summary_semantic_reduction`/`summary_memory`/`web.api.cover_styles` — OK; литералы по кодпоинтам — **LITERALS_OK**; `APP_VERSION=2.58.40`.
- **Рестарт:** `sudo -n systemctl restart admin_bot` → **active** (22:23:58 UTC, PID 2580591), SmartModule scheduler started.
- **Δ DDL:** SQLite **`user_version=19`** — Δ=0, бронь v20 `mca-04b` не тронута. PostgreSQL: **+1 таблица `cover_style_connections`** — аддитивный идемпотентный CREATE при старте, санкция ADR-1028-5 D14/§104 (cover_style_* 5→6 таблиц); это ожидаемый DDL полного релиза (в цикле 1 pg_db.py не деплоился — поэтому там Δ=0). Ручных миграций нет.
- **Seeds:** ручных нет. Автоматический идемпотентный seed-инвариант T-4220 сработал штатно: журнал `[cover_styles] seed ensure | profile=medved_press` — no-op (профиль существует, владелец не сброшен).

## 4. Пост-деплой верификация (прод, 22:24–22:50 UTC)

| # | Гейт | Ожидание | Факт |
|---|---|---|---|
| 1 | `GET /healthz` | 200 + `2.58.40` | `{"status":"ok","version":"2.58.40"}` ✓ |
| 2 | `GET /api/health` | 200 | 200 ✓ |
| 3 | Каталог F8 на проде (`--check` read-only) | 488/427/463/105/103/21 | **CHECK OK: реестр 488**, карта полна, идемпотентно ✓ |
| 4 | Kill-switches | COVER_STYLES_ENABLED + COVER_RICH_DEGRADED_ENABLED + DIRECT_LLM_DECISION_ENABLED все ON | **Все ON** (+ MEDIA_EXECUTION_POLICY_ENABLED, GRAPHRAG_SHADOW_REBUILD_ENABLED, SUMMARY_SEMANTIC_REDUCTION_ENABLED — ON) ✓ |
| 5 | GraphRAG shadow rebuild | запускается, НЕ застревает в building | 2 джобы зас schedule'ены на старте (`graph_facts_vec` gen=1, `smart_archive` gen=1, fp `96f80838f683`); shadow-таблица `graph_facts_vec_g1` создана, checkpoint-прогресс **1300→2500** embed-фактов за ~13 мин; при исчерпании лимитов эмбеддинг-провайдера джоба **честно перешла в `failed`** (LLMRateLimitError) — терминальное состояние вместо вечного `building` (старый класс бага устранён); реестр поколений честный (`building`, без фейковой активации §66); FTS serviceable (15013 доков); **возобновление с checkpoint на следующем старте** (§85 background completion) ✓ (наблюдение — §7) |
| 6 | Media Adapter активен (не 90с статик) | policy resolver активен, stage-aware окна | `MEDIA_EXECUTION_POLICY_ENABLED=True`; cold-окна: generate **180s** / edit **240s** (stage-aware §23), connect 15s/read 60s/poll 30s — статические 90s более не предел ✓ |
| 7 | Text Capacity адаптеры | NanoGPT/DeepSeek/OpenRouter работают, honest source | resolver ON; **NanoGPT каталог fetchится живьём** (625 моделей; e2e-доказательство `provider_catalog` + max_output 524288/32768 на моделях из каталога; имена моделей прода отсутствуют в каталоге → честный `registry`/`fallback` 16384 — designed путь §53/§56); **DeepSeek → `verified_registry`**; **OpenRouter → `provider_catalog`** (live) ✓ |
| 8 | LLM-driven decision активен | DIRECT_LLM_DECISION_ENABLED ON + гейт-конъюнкция | flag ON; `llm_decision_enabled(reactions=True)=True`, `(False)=False` — конъюнкция env+per-chat работает ✓ |
| 9 | ladder/parity | набор зелёный на проде | 8 asap32-файлов на прод-venv: **102 passed** ✓ |
| 10 | Error-spike | нет | journal с рестарта: **0** ERROR/CRITICAL/Traceback; WARNING — только 429-ретраи эмбеддингов (темп rebuild) + 1 честный `EMBEDDING_GENERATION_FAILED` (smart_archive); severity-коалесинг §8 работает — спама «not serviceable» нет ✓ |
| 11 | R17-скан | секреты не в логах/отчётах | journal 0 попаданий; скрипты/выводы без секретов; DSN маскирован ✓ |
| 12 | API permission enforcement (T-4222) | unauth → отказ | `/api/cover/styles`, `/api/cover/connections` без авторизации → **401** ✓ |
| 13 | Browser smoke (bounded, SSH-туннель → Playwright) | UI отдаётся, JS живой | bundle 2.58.40, приложение грузится, **0 консольных ошибок приложения** (только favicon 404), корректный guard «Миниапп открыт без Telegram-контекста» ✓ |

## 5. Итоги по зонам на проде

- **A (GraphRAG lifecycle/reranker):** планировщик стартует из `bot.py` (в цикле 1 был dormant); state machine с durable checkpoint; `building` не финализируется фейком; FTS работает во время rebuild; severity-коалесинг подтверждён журналом.
- **B (Media Adapter/Policy):** единая точка исполнения + policy активны (180/240 stage-aware); durable media jobs/recovery в проде dormant до первой image-операции (событий `MEDIA_JOB_*` в окне наблюдения не было — генераций не запускалось, платные вызовы не триггерились).
- **C (Text Capacity):** три адаптера живые, источники честные (см. гейт 7); Analytics получает честный `source`.
- **F (LLM-driven decision):** kill-switch ON, контракт Decision Task в прод-коде; поведенческое live-наблюдение (REACT/SILENT/REPLY в реальном чате) — по мере трафика (безcredential-триггера не форсировалось).
- **H (EXTRA corrective):** PgDatabase-контракт: `/api/cover/*` отвечает 401 unauth (права работают), seeded-профиль в PG цел («Графический роман Медведь Press», seeded_example, enabled, counter_enabled, не удалён); `cover_style_connections` создана (6/6 таблиц); seed-инвариант выполняется идемпотентно; новый UI отдаётся.
- **D/E (зависимости полного релиза):** ядро Summary-редукции уже было на проде с 2.58.40; этим деплоем добавлены paged-L2-потребители и fallback-recompose; крон-саммари 01:00 UTC (следующий после деплоя) — первый на полном коде, наблюдение штатное (см. §7).

## 6. Чужие файлы (подтверждение)

Закоммичено только скоуп ASAP-3.2 (`0483386` — 80 файлов; `4cb267a` — 5 docs-файлов). Проверено `git status` после коммитов — осталось ровно: `plans/docs/mca-round1027-arch-frames.md`, `plans/docs/mca-round1027-plan.md`, `plans/metrics.md`, `plans/workflow_state.md` (модифицированные, чужие), `plans/features/mca-04b-dossier-rebuild/`, `extra_images/`, `.playwright-mcp/`, `node_modules/`, `package.json`, `package-lock.json` (untracked, чужой WIP). `plans/current_task.md` не менялся (R17).

## 7. Watch / фон

- **GraphRAG rebuild:** джобы resumable; при следующем рестарте продолжатся с checkpoint (graph_facts_vec: 2500/15013). Темп ограничен 429 бесплатного тира Gemini (ротация ключей/fallback работает). Активация — автоматически после validation (9 критериев) при завершении; до тех пор прод FTS-serviceable — §85 (background completion, roadmap не блокируется).
- **`smart_archive` rebuild:** `failed/knn_smoke_failed` (processed=0) — вторичный индекс; предполагаемая причина — недостаточно фактов для KNN smoke. Fail-soft designed (FTS serviceable); разбор — в follow-up/backlog, не блокёр.
- **Крон-саммари 01:00 UTC** — первый прогон на полном D1–D14 коде; класс инцидента 2.58.37 уже закрыт и наблюдался в цикле 1.
- **Ручная проверка джоб:** `sudo -n systemctl status admin_bot` / `sudo -n journalctl -u admin_bot` (grep EMBEDDING_GENERATION_*); read-only SQLite: `task_jobs` (kind=graphrag_rebuild).

## 8. Откат

- **Soft (kill-switches, без отката кода):** `DIRECT_LLM_DECISION_ENABLED=false` (алгоритмический decision байт-паритет), `MEDIA_EXECUTION_POLICY_ENABLED=false` (legacy 90/180/240), `GRAPHRAG_SHADOW_REBUILD_ENABLED=false` (rebuild не планируется, FTS продолжает работать), `SUMMARY_SEMANTIC_REDUCTION_ENABLED=false` (каскад байт-в-байт прежний) + рестарт.
- **Cold revert:** `cd /var/www/admin_bot && git checkout 3198cb5 -- . && git reset --hard 3198cb5` → `sudo -n systemctl restart admin_bot` (3198cb5 = состояние перед циклом 2; прод-версия строки останется 2.58.40 — при необходимости доп. отката к 2.58.39 см. deployment.md цикла 1 §8). PG-таблица `cover_style_connections` останется (аддитивная, пустая, безопасна для старого кода). SQLite DDL не менялся — откат кода безопасен.

## 9. Честные границы (не сделано этим деплоем)

- **T-4234 (платная live-generation):** не выполнялась — нет authenticated-триггера из DevOps-сессии; policy/адаптер доказаны резолвером и контракт-тестами на проде. Запуск — штатно владельцем через бота.
- **T-4227 (20-пунктовый authenticated browser acceptance):** требуется реальная Telegram-сессия владельца (miniapp вне Telegram честно гардится); unauth-smoke пройден (гейт 13).
- **T-4235 полная активация vector:** rebuild большой (15013 фактов), идёт в фоне с checkpoint; активация — background completion (санкция §85).
- Поведенческое live-наблюдение Decision Maker и paged-L2 крон-саммари — по мере естественного трафика/расписания.

## 10. Итог

**VERIFIED.** Прод: `4cb267a` (feat `0483386`), версия 2.58.40, health 200, каталог 488/427/463/105/103/21, SQLite DDL Δ=0 (v19), PG +1 аддитивная таблица (D14), kill-switches ON, GraphRAG rebuild запущен с durable checkpoint (не застревает — честные статусы), Media Policy 180/240 stage-aware, capacity-адаптеры с честными источниками, LLM decision ON, ladder/parity 102 passed на проде, ошибок нет, R17 чист, откат готов. Полный D1–D14 задеплоен; фоновые хвосты — §7/§9.
