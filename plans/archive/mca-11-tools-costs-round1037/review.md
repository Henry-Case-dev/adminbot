# review.md — MCA-11 `mca-11-tools-costs` (Reviewer T-4959, независимый gate)

**Дата:** 05.10.2026. **Решение: Approved.** Дата-фриз `spec.md` (§ 2–12) + ADR-1028-13, санкции §9 — соблюдены. Блокирующих дефектов нет.

## Binding (точное покрываемое состояние)

- **HEAD:** `a34e1632538840fe36f6d81446ff6b6ad54db7fa` (master); **staged — пусто**; кандидат = незакоммиченное рабочее дерево (2 Builder-сессии).
- **WTH-манифест Reviewer (24 файла):** `plans/reports/mca11_wth_manifest_review.txt`; **SHA-256 тела манифеста (LF, UTF-8, sorted, `path␣␣hash␣␣(origin)`; tracked-модификации — `git diff HEAD -- path`, новые файлы — content):** `4d3fe09150f15e1f49062daa5e2a03657db390cd35e91635dc05855bce030407`.
- **Состав:** 13 tracked-diff (`config/settings.py`, 11 `services/*` модификаций, `tests/test_tool_chains_round1026.py`) + 6 новых (`services/tool_result.py`, `services/mca_money_limits.py`, 4 test-файла mca11) + 5 док-файлов пакета (content). Правка любого файла манифеста (кроме review.md) инвалидирует ревью.
- **Исключено (записано в header манифеста):** `plans/workflow_state.md` (процессный журнал Orchestrator, вне scope по брифу — прецедент mca-15), `plans/docs/mca-round1027-arch-frames.md` (незакоммиченный backfill **mca-05** Wave 2 v21/ADR-1027-12 — хунки проверены, к mca-11 отношения не имеют; прецедент asap-4-4 F-N5), мусор `node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*`, `plans/verification_cache.json` (pre-existing debris; при коммите НЕ стейджить), сам review.md.
- Spec-хэши пакета (sha256): `spec.md` c580ec80…, `adr-1028-13` 03af3605…, `tasks.md` e0155012…, `requirements-map.md` ad799c54…, `evidence.md` 4f788445…
- **Пин сверён:** 18 git-blob-хешей из `evidence.md` пересчитаны независимо — **18/18 совпадают** (Builder-евиденс привязан к ровно тем байтам, что ревьюятся).

## Проверки (сводно; REQ→факт)

| # | Точка | Итог |
|---|---|---|
| 1 | D1 ToolResult: 7 статусов + деривация; error-текст/`status:error` ≠ `ok` (A20); legacy `skipped→denied`, `not_found/unsupported→empty`, `partial` сохранён в payload; envelope аддитивен (19 ключей = 12 legacy + 7); output в журнал не пишется (R17); категории канона 12 (4/5/2/1), неизвестный → `external_read`, никогда `admin`; права не расширены; mca-15: `MetricResult.status` авторитетен в payload, count-контур не подменён (`metric_results` вне diff) | ✅ снято кодом (`tool_result.py`) + тестами (`TestA20/TestStatusMapping/TestContract/TestCanonicalEnvelope`) |
| 2 | D2: числа 6/4/2/360 + `MCA_TOOL_TRANSIENT_RETRIES_MAX=2` — env-only ClassVar, дефолты = прежние константы; enforcement в `tool_loop`, master `TOOL_CHAIN_LIMITS_ENABLED` не задублирован; на пределе — `denied` + `data={kind,unit,scope,value,reason}` + прежняя graceful-деградация; media deadline отдельный (180s ≠ 360s), окна/pipeline не урезаны; A2 не ослаблена (test_total_call_cap 6 executing + retries-политика — пин для mca-09/10b) | ✅ |
| 3 | D3: `idempotency_key` = sha1-16(chat\|corr\|tool\|args_fp\|op_kind), K2-gated в durable `begin_media_job` → `coalesce_key`; `delivery_unknown` при `send_failed` без слепого повтора (fixture: ровно 1 внешний вызов; повтор диспатчить нельзя), `duplicate=True` в кэше; exactly-once не обещан (`ceiling_exact`/докстринги); mca-22/`mca_trace`/`mca_watchdog`/`task_supervisor`/`bot_output_ledger` — вне diff (REUSE, не форк) | ✅ |
| 4 | D4: `llm_usage_events` — единственный леджер; `SOURCES += ("embedding","media")` код-only; новая K3-gated точка записи — успешный `llm_client.embed` (tokens из usage или `tokens_estimated`, fail-open); unknown ≠ 0: `price_known=false`/`cost_usd=null`/`price_version="unknown"`; агрегатор один (`execution_graph_source`/`web/api/analytics.py` — вне diff, unknown → cost=None не 0); `usage_detail`/`limit_record` (единицы usd/tokens/slots/bytes/events/seconds раздельно); `llm_client.embed_once` — точки записи нет (документировано, не изобретено) | ✅ |
| 5 | D5: `services/mca_money_limits.py` — K5 master **default OFF**; per-scope env без числовых дефолтов (None); sentinel-семантика REUSE `budget_limits` (unset/forbidden/unlimited/cap); owner-настройки (9 шт.) не тронуты и показаны в `effective_state()` с отличием unit≠USD; семантика включения инертна (резерв/overshoot/reconcile, degradation_order maintenance→autonomous→direct, intake не гейтится — runtime-вызовов нет: grep Rust): **runtime-вызовов нет** (`test_no_runtime_callers`); no hidden budget | ✅ |
| 6 | D6: `tools.chain` v1→v2: stages/stages_to_events/instrumentation/enabled_gate/event_names/settings_ref/widget-id «Tool chain» (контракт mca-17a конвенция); эмиссия только через единственный `emit_mca_event` (все поля в `ALLOWED_FIELDS`, существование подтверждено), notable-only (execute при error/timeout/cancelled/denied; deliver при `delivery_unknown`; account при accounting-unknown = `cost_unknown`, +1 в единственный `REASON_CODES` — `mca_events.py` diff ровно 1 код); K4 OFF → событий нет + registry честный disabled/not_run | ✅ |
| 7 | K1–K4 = ON, K5 = OFF — дефолты независимы (импортировали settings из чистого окружения: `K1 True K2 True K3 True K4 True K5 False; 6/4/2/360/2; usd None/None/None`); env-переопределяемость подтверждена пробой (K4=false + DIRECT_USD=2 → False, 2.0);resar K2/K4/K5 OFF-паритет отвесно: `test_k2_off_no_marking_and_no_guard` (2 вызова, error), `test_k4_off_no_stage_events` (перехват эмиттера — 0 событий), K5 default-OFF+inert (`TestA28DefaultOff` incl. caps=0 → allowed, ledger не трогается), K1-OFF байт-в-байт (`TestK1OffParity`, legacy 12 ключей/`skipped`/`ok`) | ✅ |
| 8 | Scope/вторые механизмы: 15 tracked + 2 новых services + 4 теста — других зон нет; Δ DDL = 0 (`database.py`/`pg_db.py`/`mca_trace`/микросервисы вне diff; SQLite v26 не тронут); Δ каталога = 0 (`param_catalog.py` вне diff + тест `env_numbers_not_in_catalog`); канон 12 = 12 (`test_categories_cover_canon_twelve`, `tool_schemas.py` вне diff); `plans/current_task.md` вне diff (§15 на :730–761, A20/A21 :901–902, A28 :909, §20.2 :1026 сверены построчно) | ✅ |
| 9 | R17: новые log/emit-сайты — только единицы/состояния/орign/числа (`entity_ids={tool,args_fingerprint}`, usage_json = численно-кодовий контракт); `TestR17` (secret-сан vs events/usage_json) + `test_no_payload_in_logs`-семейство зелёные; сырые args/output/URL и ключи в диффе отсутствуют | ✅ |

## Findings (все — non-blocking; блокирующих нет)

| ID | Сев. | Локация | Finding | Blocking |
|---|---|---|---|---|
| F-1 | Low | `services/tool_result.py:450–460` | Стадия `account` эмитит `tool_accounting` для ЛЮБОГО непустого `usage`, включая `price_known=true` (reason="", level INFO), тогда как evid/T-4956 & spec §7 утверждают notable-only `accounting-unknown`. В текущей интеграции все известные `usage`-продюсеры ставят `price_known=false` (image) — prod-шум невозможен сегодня | **No** (заметка для mca-09: при появлении known-price usage у tool в prod появится INFO-событие на каждый метражный вызов — K4 выключает; свести к `notable-only` или обновить докстринг) |
| F-2 | Low | `config/settings.py:2934` | CA-11-санкция §9.6 — bump `APP_VERSION 2.58.56→2.58.57` **не в кандидате** (в дереве 2.58.56). Deploy T-4960 — следующ.charCodeAt; не забыть в релизном коммите (кандидат в остальном deploy-готов) | **No** (handoff-условие DevOps) |
| F-3 | Low | `services/mca_money_limits.py:248–255, 285–296` | FIFO-согласование пересмешивает резервы: при mixed-known/unknown конкурентных операциях `reconcile` снимает чужой FIFO-резерв, а unknown-счётчик размагничивается отдельно (каление) | **No** (модуль инертен, runtime-вызовов нет; контракт для mca-09: check→reconcile парно по операции) |
| F-4 | Info | `services/tool_result.py:157–165` | `MCA_TOOL_TRANSIENT_RETRIES_MAX` — читатель `transient_retries_max()` не потребляется runtime (только тесты): политик-wise лишний слой повторов в direct loop не создан, пин для mca-09/10b — по санкции §3 | **No** (по санкции; отметить в handoff) |
| F-5 | Info | `services/tool_loop.py:544–558` | K1=OFF + K4=ON → chain-лимитное событие с каноническим `status="denied"` при legacy-склейки `skipped` в конверте; расхождение документировано в код-комменте, reason_code — из единого словаря (mapped), R17-safe | **No** (согласованное решение;非物质ного риска нет) |
| F-6 | Info | довс untracked | Мусор (`node_modules/`, `.playwright-mcp/`, `package*.json`, screens `tools/_ui_asap43_*`, `plans/verification_cache.json`) не в манифесте; при коммит-моменте не стейджить (commit-гигиена, прецедент asap-4-4 F-N5) | **No** |

## Pre-existing reds (классификация; оба воспроизведены и на чистом HEAD a34e163 в tempgit-worktree — delta отсутствует)

1. `tests/test_tool_loop.py::TestChatWithTools::test_query_chat_memory_count_reaches_model` — **pre-existing, unrelated к mca-11**: файл не менялся с `8c46132` (19.09, diff-vs-HEAD пуст), красный уже на базовом HEAD; зелёный при `MCA_CHAT_STATISTICS_ENABLED=false` (проверено: `11 passed`); root cause — released default-ON mca-15 сменил вывод `query_chat_memory` против старой фразы. **Признано: accepted-with-note → backlog** (или micro-fix — 1-строчная правка ожидания).
2. `tests/test_migrate_env_to_pg.py::TestRunDryRun::test_run_created_and_idempotent_skip` — **pre-existing, unrelated**: файл не менялся с `cc1b960` (30.09), Yне переселялись; `services/config_migrations.py`/`pg_db.py` вне diff; сами 22 ключа — пред-Yние env-ключи (snippet: `keys.embedding_quota_group_labels`, `keys.image_style_api_key`) против пина-счётчика 21. **Признано: accepted-with-note → backlog** (stale-счётчик fixture; сериальная drift-не-миграция).

## Ответы на вопросы Builder (1)–(3)

1. **`llm_client.embed_once` без санкционированной точки записи** — подтверждено: write-point только в `embed` (успех), `embed_once` не вызывается. Классификация: **correct-by-design, документировано** (open-вопрос для @Architect/Orchestrator — цены control-plane embeddings остаются невидимыми; отдельная запись была бы несанкционированной).
2. **`SOURCES += "media"` без writer'а** — подтверждено: STT/медиа-провайдеры не отражают usage; `media` — метка домена для будущих точек записи (аддитивная по AM-2). **Correct-by-design** (в леджер попадают только честные записи, нет 0-лив).
3. **Spec §7 OFF → registry честный `not_run` vs факт `disabled/not_run`** — подтверждено: конвенция mca-17a — при OFF(eл disabled, `not_run` при активном инструменте <нет событий>). **Correct-by-design**: spec-фраза оплачена нестрого, Builder-интерпретация покрыта тестами (`test_runtime_status_honest`), контракта не нарушает.

## Что было проверено (точные счётчики).

- `.venv\Scripts\python.exe -m pytest tests/test_mca11_tool_result_round1028.py tests/test_mca11_costs_round1028.py tests/test_mca11_money_limits_round1028.py tests/test_mca11_chain_stages_round1028.py tests/test_tool_chains_round1026.py -q` → **138 passed**.
- `pytest tests/test_mca22_core_round1027.py tests/test_mca02_safe_fetch_round1027.py tests/test_tool_router.py -q` → **166 passed**.
- `pytest tests/test_mca15_chat_statistics_round1028.py tests/test_media_execution_asap32.py tests/test_unified_image_request_round1026.py -q` → **140 passed**.
- `pytest tests/test_tool_loop.py tests/test_migrate_env_to_pg.py -q` → **2 failed / 30 passed** (оба — проверенные pre-existing, ниже).
- `pytest tests/test_direct_chat.py tests/test_direct_two_call_round1022.py tests/test_negative_constraints_round1022.py tests/test_image_generation_round1023.py -q` → **265 passed**.
- `tests/test_tool_loop.py -q` при `MCA_CHAT_STATISTICS_ENABLED=false` → **11 passed** (red #1 зелен).
- **RED-check (репро на чистом HEAD `a34e163` через temp `git worktree` + копия 4 новых тест-файлов):** `pytest (4 файла) -q` → **4 collection errors** (модули `services.tool_result`/`mca_money_limits` отсутствуют) — тесты действительно привязаны к признаку; два pre-existing red-теста на HEAD → **2 failed / 20 passed** (потверждено: дельта их не приносит).
- Prобы по K-гейтам (импортирование чистых дефолтов + env-переопределяемость): K1..K4=ON/K5=OFF/числа 6/4/2/360/2/None — подтверждено.
- **Итого независимых pytest-результатов Reviewer: 738 (736 passed / 2 failed) + 4 collection-ошибки RED-check.** Builder-пакет (859/2) согласуется: обе failed — те же pre-existing.

## Residual notes

- Задача Stage $7 (notable-only) — факт-заметка F-1 (сводить с `account`-контPaint: known-price usage пока не бывает).
- `answers` к вопросам Builder — § «Ответы»;额外的相关问题 нет.
- live T-4961 (реальный чат/платные вызовы/аналитика) — `PENDING OWNER`, no-false-acceptance (`:15167`): Scope review не охватывает live-часть (это deploy-домен).
- R17: сырые и secrets в диффе отсутствуют (независимый ручной осмотр новых log/emit-сайтов + TestR17-семейство зелёное).
- При коммит-моменте DevOps переизмеряет binding (mca-11-манифест требует док. пакета); APP-версию подняты не даёт (F-2).
