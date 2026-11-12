# D6 — binding evidence: explicit-чекап на общем collector'е, регистрация `prompt_readback`, «Самодиагностика» UI/аналитика

- **Срез:** `self-diag-01` / D6 (checkup integration, registration, UI/analytics).
- **Код-кандидат:** `61e50806bf19d9ffbc9a7f77ba2f2b400b2eb29c` (ветка `self-diag/d6`).
- **База:** `722ccfc522ba00a18dc74881913020151ac250aa` (принятый D4-B).
- **Интеграция:** D3 `278c19e0bbe452a731cb6066102fbe9c47d34bd0` (`self-diag/d3`) и
  D5 `c7b90b2652700dc36a9a7b27b6a8ff17fdad21a1` (`self-diag/d5`); оба merge —
  без конфликтов (`f3621251`, `e3c91f6f`). `inspect_runtime` сохранён 17-й
  записью канона, модули D5 (`services/prompt_readback.py`,
  `handlers/prompt_readback.py`) — без изменений.
- **Worktree:** `WorkspaceData/worktrees/c742e4de9e92c489/self-diag-01-0ccfa8fbf52b-9b4548db`.
- **Docs-коммит:** этот файл (SHA фиксируется в handoff).
- **Статус:** **REVIEW** (решение — за независимым Reviewer). D6/self-diag не
  объявляются DONE; статусы карты Builder не менял.
- **Деплой:** не выполнялся. Прод/master/settings/prompts/VPS/Telegram не
  затрагивались; DDL/миграций/новых сторов/агентов/LLM-вызовов нет.

## 1. Диапазон коммита

D6-дельта поверх объединённой базы (`git diff e3c91f6f 61e50806`):
**22 файла, +1787 / −40**.

| Файл | Что | Строк |
|---|---|---|
| `handlers/checkup.py` | explicit-чекап: факты общего `DiagnosticCollector`, identity-лог, терминальное событие | +212 |
| `services/checkup_service.py` | телеметрия эффективного промпта (source/version/hash) без содержимого | +48 |
| `services/tool_schemas.py` | `prompt_readback` — 18-я запись канона (в хвост), схема из D5 | +21 |
| `services/tool_router.py` | регистрация `prompt_readback`, ack→ToolResult-сигнал, телеметрия входов/отказов | +128 |
| `services/diagnostic_policy.py` | `prompts.tool_names += ("prompt_readback",)` | +6 |
| `web/api/routes.py` | `GET /api/status/self-diagnosis` (существующие источники, TTL 30с) | +338 |
| `web/app.js` | состояние/методы двух блоков UI (существующий `api()`/RBAC) | +242 |
| `web/index.html` | блок «Самодиагностика» на «Статусе» и подраздел в «Доступах» | +290 |
| `tests/test_checkup_contract.py` | **новый** файл, 20 тестов D6 | +382 |
| затронутые канон/DI-тесты | 10 файлов: точные пины 17→18, DI `diagnostics=False`, conscious F8 re-issue | ~+90/−40 |

Полный диф против базы 722ccfc5 — **51 файл, +9864/−91** (включает содержимое
D3+D5, вошедшее merge-коммитами без правок).

### 1.1 Что именно изменено (контракт)

1. **Explicit-чекап** (`handlers/checkup.py`): после `fetcher.fetch()` (те же
   логи/fallback) вызывается `DiagnosticCollector.collect_for_checkup(...)` —
   тот же registry probes и тот же bundle, что у `inspect_runtime` /
   `get_bot_health`. Факты идут ДАННЫМИ перед логами
   (`payload = facts + "\n" + logs`); промпт, ход диалога, кулдаун, реакция,
   busy-фразы и chunked-reply не менялись. Сбой/timeout collector'а — WARNING
   и работа по логам, чекап не выключается. Пишется `[checkup] identity` только
   с машинными полями (runtime/`deployed_sha`/`checkout_sha`/`git_meta`/
   `sources ok/total`), без payloads.
2. **Телеметрия чекапа** (`handlers/checkup.py` + `services/checkup_service.py`):
   одно терминальное событие `checkup_triggered` (существующий `mca_events`) с
   `source_ref_json = {prompt_source, prompt_version_used, prompt_hash,
   bundle_delivered, bundle_status, bundle_truncated, sources, not_checked,
   report_chars, latency_ms, ...}`. Hash считается по ровно тем байтам
   system-промпта, которые ушли в LLM (до подстановки `{max_symbols}`).
   Содержимое промпта/отчёта не пишется.
3. **`prompt_readback`** (три шва): `TOOL_CALLING_TOOLS` (18-я, в хвост),
   `ToolRouter.dispatch` → `handlers.prompt_readback.prompt_readback`
   (D5-сигнатура `(arguments, ctx)`), `diagnostic_policy`
   `prompts.tool_names`. `inspect_runtime` остаётся 17-м. Статус ack честно
   превращается в out-of-band `ToolResult`-сигнал (`denied/unverified` ≠ `ok`);
   тело промпта в контекст модели не попадает.
4. **Телеметрия входов** (существующий `mca_events`, только коды/числа):
   `checkup_triggered`, `get_bot_health_called`, `inspect_runtime_called`
   (был в D3), `read_source_attempted`, `read_source_verified`,
   `code_unavailable`, `prompt_readback_requested/allowed/denied`,
   `diagnostic_output_validated`.
5. **`GET /api/status/self-diagnosis`**: снимок процесса/хоста
   (`status_service._server_metrics`, `deploy_identity` D4, каталог
   `runtime_probes` без исполнения) + аналитика 24ч по `mca_events`
   (`inspect_runtime_called`: calls/partial/p50/p95/by_stage/last_success;
   `checkup_triggered`; счётчики всех входов). RBAC — существующая
   `diagnostic_policy.decide("bot_server_state", "view")`; TTL-кэш 30с.
   Значения без источника — `null` + `measured=false`, не 0.
6. **UI (без новой страницы):**
   - «Статус» → блок `data-self-diagnosis`: runtime/PID/uptime/`deployed_sha`/
     log backend/CPU/RAM/диск/очередь/непроверенные источники/последний
     успешный анализ; кликабельные строки источников с временем, lineage и
     различением «наблюдение/декларация»; аналитика с «—» для неизмеренного.
   - «Доступы» → подраздел `data-self-diag-access`: матрица
     роль×действие по 9 категориям через уже выложенные
     `/api/access/diagnostic_policy*` (PUT/DELETE, global/chat scope),
     объяснение allow/deny (`/explain`), аудит (`/audit`), secret-policy
     (SECRET_VALUE не настраивается). Параллельного ACL/страницы нет.

## 2. Покрытие строк карты (Builder-оценка; статусы ставит Reviewer/PM)

33 строки D6 (26 `items` + 7 `additional_requirements`). «live» — строка
карты помечена `live_required=true`; live-часть этим срезом не выдаётся за
проверенную.

| Строка | Состояние | Доказательство |
|---|---|---|
| `SD1-GRAL-02` | покрыто (unit) | `test_no_second_prompt_or_writer`, sha256 заводского `CHECKUP_SYSTEM_PROMPT`; `services/checkup_prompts.py`/промпты не в диффе |
| `SD1-EVD-02` | покрыто (unit) | `test_uses_shared_collector_and_keeps_report`: explicit → `CheckupService` + действующий промпт; `get_bot_health` использует тот же сервис/collector (D3) |
| `SD1-D6-01` | покрыто (unit) | `test_output_validation_replaces_only_dangerous_fragment` (маскируется только фрагмент, отчёт остаётся); существующий `diagnostic_policy.publish` до отправки + честный отказ вместо «выключить чекап» |
| `SD1-D6-02` | **частично** | Промпт/Writer не менялись (hash-инвариант); «Writer объясняет наблюдения» проверяется только на живых ответах модели — D7/live |
| `SD1-GRAL-06` | **частично** | Инвариант промпта/характера подтверждён байт-равенством; «не выдумывает падение» — поведение LLM, live/D7 |
| `SD1-D6-03` | покрыто (unit), live-часть D7 | `test_no_second_prompt_or_writer` (sha256 `b0c70f97…`), диффа промптов/версий/дедупа нет; реальные ответы — D7 |
| `SD1-D6-04` | **live (D7)** | Характер/живые ответы не проверялись; код промпта байт-идентичен |
| `SD1-GRAL-07` | покрыто (unit) | Ограничения — в backend (`output_projection.sanitize` + `diagnostic_policy.publish`); тест фрагментной замены; стиль речи не менялся |
| `SD1-D6-05` | покрыто (unit) | `test_partial_evidence_is_reported_in_event`: prompt source/version/hash + `bundle_delivered/truncated`, без содержимого; `CheckupService.last_run` |
| `SD1-D6-06` | покрыто (unit) | `tests/test_checkup_handlers.py` (cooldown/reply/fallback/busy/empty/LLM-error зелёные); `test_uses_shared_collector_and_keeps_report` |
| `SD1-D6-07` (стр. 117 и 352) | покрыто (unit) + live D7 | `collect_for_checkup` читает логи (handler), процесс/память/CPU/диски/FD, scheduler, identity+commit metadata, зависимости, конфиг, телеграм-доставку; детерминированный набор из 13 probes; `test_uses_shared_collector_and_keeps_report`/`test_identity_log_is_machine_only` |
| `SD1-D6-08` | покрыто (unit) | Чекап не читает репозиторий целиком: углубление — только через `inspect_runtime`/`read_source_code` по запросу; фиксированный probe-набор; health/версия видны из identity |
| `SD1-D6-09` | покрыто (unit) | `test_collector_failure_does_not_disable_checkup` (честный partial), `test_partial_evidence_is_reported_in_event` (`bundle_truncated`), `not_checked` в bundle |
| `SD1-D6-10` | покрыто (unit) | `test_group_checkup_not_blocked_for_unverifiable_admin`: группа, Telegram не подтверждает роль → `bot_server_state` (PUBLIC_TECH) доступен, чекап идёт; защищённым остаётся только prompt readback (PROMPT_CONTENT) |
| `SD1-D6-11` | покрыто (unit) | `test_checkup_is_not_a_prompt_readback_trigger` («покажи промпт» ≠ триггер; в `handlers/checkup.py` нет `prompt_readback`) + typed-схема D5 |
| `SD1-D6-12` | UI + endpoint (unit), live render — Reviewer/D7 | `/api/status/self-diagnosis` отдаёт status/probe, last observed, runtime/PID/uptime, `deployed_sha`, log backend, code-check state, last successful analysis, summary missing evidence; блок на «Статусе» |
| `SD1-D6-13` | сохранено (unit) | «Основные настройки» — существующий каталог/эффективное состояние (D4-B `flags.self_diag_repo_origin`); D6 не менял `param_catalog`/config UI |
| `SD1-D6-14` | сохранено (unit) | «Промпты» — существующий редактор; промпты не в диффе, sha заводского промпта равен |
| `SD1-D6-15` | сохранено (unit) | «Модели/Лимиты» не менялись; каталог/счётчики F8 `--check` зелёные |
| `SD1-D6-16` | UI реализован, live render — Reviewer/D7 | Блок «Самодиагностика»: снимок, распределение отказов (by_stage), source status, активные job/очередь, CPU/RAM/диск+давление, degraded integrations, source-code correlation, deployed vs upstream, непроверенные источники; строки кликабельны (время/источник/lineage/наблюдение-декларация) |
| `SD1-D2-32` | UI реализован, live render — Reviewer/D7 | Матрица прав по 4 защищённым классам и ролям (verified/unverified показывается в explain), аудит решений без содержимого; backend D2 не менялся |
| `SD1-D6-17` | покрыто (unit) | `test_event_counts_cover_required_names`, `_self_diag_stats`; `secret_value_disclosures.value=0` только при `measured=true`, иначе `null` |
| `SD1-D6-18` | **частично** | p50/p95 probes и полного чекапа + % partial/complete + отказы по stage реализованы (`test_percentiles_partial_and_per_stage`); retry/cache-hits/stale reads в существующих событиях не инструментированы → `measured=false` (не 0) |
| `SD1-D6-19` | **частично** | Инциденты по подсистемам = отказы by_stage; доли observed/hypothesis и false diagnosis в golden eval, «код против неправильного SHA» — не инструментированы: `golden_eval.available=false` (`golden_set_d7`), hypothesis `null`; D7 golden set |
| `SD1-D6-20` | **частично** | Derived-sample с временем/PID/CPU/RAM/диск/очередью (`samples[]`), DB/queue-группы из `mca_events.metrics`; истории роста (DB/WAL/место во времени) нет — стора не вводим, `db_growth/queue_growth.available=false` |
| `SD1-D6-22` | покрыто (unit) | GitHub/сеть не вызываются в чекапе (нет `source_reader` в пути); probes ограничены таймаутами (`ProbeLimits`), сбой → partial; DB-lock через сеть не удерживается (нет сетевых вызовов под локом); partial-ответ честно виден (`degraded`/`not_checked`) |
| `SD1-D6-16` (MAN-D6-16) | см. `SD1-D6-12/16` выше | — |
| `SD1-AMX-01` | UI + существующий ACL (unit), live render — D7 | Подраздел «Самодиагностика» в «Доступах»: 9 категорий × права просмотра/запуска/правки, права наследуются; параллельного ACL нет (`CAPABILITIES` D2) |
| `SD1-AMX-06` | **частично (live)** | Переключатели ролей/категорий, объяснение эффективных прав/наследования и причин allow/deny, сохранение в PG через существующие маршруты; «переживает рестарт» и «применяется к реальным tool calls» — backend D2-тесты + `test_dispatch_is_not_unknown_and_denies_without_identity`, но живая проверка — D7 |
| `SD1-AC-01` | покрыто (unit), live D7 | Handler/cooldown/reply/реакция/busy сохранены (`test_checkup_handlers.py`), факты общего collector — новый тест |
| `SD1-AC-02` | покрыто (unit) + трасса (unit) | `test_uses_shared_collector_and_keeps_report` + `test_identity_log_is_machine_only` + `test_partial_evidence_is_reported_in_event` (в трассе есть identity и bundle-поля) |
| `SD1-AC-09` | покрыто (unit) | sha256 `prompts.checkup_system_prompt` равен заводскому; промпты/ревизии/история не менялись; живые ответы — D7 |
| `SD1-AC-19` | UI реализован, live render — Reviewer/D7 | Статус/аналитика показывают реальное покрытие/отказы; карточки не содержат credential values (payload строится из чисел/кодов; secret policy `SECRET_VALUE` не настраивается) |

**Честно не покрыто этим срезом:** живые ответы Telegram (характер/«writer
explains»), реальные Playwright/Browser Use скриншоты, golden eval и метрики
retry/cache/stale, история роста БД/очереди, реальный VPS-прогон.

## 3. Тесты (реальные прогоны, exact counts)

Новый файл D6:

```text
pytest tests/test_checkup_contract.py -q
20 passed
```

Focused-набор D6 + D3/D4/D5 + затронутые контракты (22 файла):

```text
pytest tests/test_checkup_contract.py tests/test_checkup_handlers.py \
  tests/test_checkup_service.py tests/test_checkup_prompts.py \
  tests/test_checkup_logs_fetcher.py tests/test_p0_checkup_core_contract.py \
  tests/test_prompt_readback.py tests/test_diagnostic_probes.py \
  tests/test_evidence_bundle.py tests/test_diagnostic_policy.py \
  tests/test_tool_schemas.py tests/test_tool_router.py tests/test_tool_loop.py \
  tests/test_tool_calling_round1015.py tests/test_tool_chains_round1026.py \
  tests/test_evol_source_reader.py tests/test_round1025_f8_registry.py \
  tests/test_frontend_tab_mapping.py tests/test_webapp_parity_smoke.py \
  tests/test_addtr_entry_caption.py tests/test_direct_chat_handlers.py \
  tests/test_p0b_current_question_priority.py -q
913 passed
```

D4-B-набор (перенос из его binding, тот же состав) + промпт-контракты:

```text
pytest tests/test_deploy_identity_d4b.py tests/test_deploy_identity.py \
  tests/test_evol_source_reader.py tests/test_param_catalog.py \
  tests/test_round1025_f8_registry.py tests/test_frontend_tab_mapping.py \
  tests/test_webapp_parity_smoke.py tests/test_asap8_v6_d07_overrides.py \
  tests/test_addtr_entry_caption.py tests/test_direct_chat_handlers.py \
  tests/test_p0b_current_question_priority.py tests/test_asap7_cover_preview.py \
  tests/test_mca10b_random_applications_block_d_round1041.py \
  tests/test_prompts_round1024.py tests/test_prompt_baseline.py \
  tests/test_prompt_versioning_enforcement.py -q
661 passed, 1 failed (pre-existing, см. §5)
```

JS/UI-статика (без браузера):

```text
node --check web/app.js                      → exit 0
node tests/js/app_methods_dup_keys_guard_test.js
  → METHODS-DUP-KEYS-OK blocks=9 keys=1554 duplicate-problems=0 behavioral=ok
```

Проверено тестами (что именно утверждается):

- explicit-чекап вызывает ИМЕННО `collect_for_checkup` c `(logs, fallback,
  chat_id, permission-машинные-поля)`; payload = факты + логи; отчёт уходит;
- сбой collector'а → payload = логи, отчёт уходит;
- `checkup_triggered` содержит prompt-метаданные и bundle-флаги, но не текст;
- identity-лог содержит sha, счётчики источников и НЕ содержит секрет из runtime;
- группа с непроверяемым админом не блокирует чекап;
- «чекап» не матчит промпт-запросы; в handler'е нет `prompt_readback`;
- sanitize маскирует только опасный фрагмент, остальной текст сохраняется;
- канон: 18 инструментов, `inspect_runtime` — 17-й, `prompt_readback` — 18-й;
- `prompt_readback` есть в `TOOL_CAPABILITIES["prompts"]` и схеме D5;
- `dispatch("prompt_readback")` — не «неизвестный инструмент»; при
  denied-ack сигнал `denied` + события requested/denied; ack без тела промпта;
- аналитика: p50/p95/partial/by_stage; отсутствие данных → `null`/`measured=false`;
  endpoint отдаёт restricted при отказе политики;
- UI-маркеры/методы присутствуют, новых страниц/агентов нет.

## 4. Влияние на обязательные конфигурации (effective-state)

| Настройка | Default | В тестах | Ожидаемый прод-приоритет |
|---|---|---|---|
| `flags.checkup_enabled` | `CHECKUP_ENABLED=True` | hot-фолбек ON | PG/hot → Settings; OFF скрывает чекап и `get_bot_health` |
| `SELF_DIAG_LOCAL_REPO_ROOT` | `""` | `""` (GitHub-only) | env/unit; задаёт DevOps при активации локального чтения |
| `flags.self_diag_repo_origin` | `Henry-Case-dev/adminbot` | default | PG → default; userinfo вырезается |
| `diagnostic_policy prompts.view` | `local_admin` (user запрещён) | default | PG/global → chat override → class default; owner — неявно |
| `MCA_EVENT_CONTRACT_ENABLED` / `MCA_TELEMETRY_STORE_ENABLED` | `True`/`True` | ON | env-гейты mca_events; при OFF события только логируются |
| `SOURCE_READ_ENABLED` | `True` | ON | env kill-switch `read_source_code` |

Тестовые оверрайды: `setup_checkup(..., diagnostics=False)` в изолированных
тестах (probes не исполняются); `diagnostics=<stub>` в тестах D6. Прод-путь
(`bot.py` → `setup_checkup(..., db)`) идёт без оверрайдов и собирает реальный
`DiagnosticCollector` лениво из существующих db/memory/fetcher/status.

**Чего нельзя доказать локально:** реальные байты промпта в проде (сверяется
hash-инвариантом кода, фактический PG-слой не читался), живая доставка
prompt_readback в Telegram, реальный UI-рендер с TMA-контекстом.

## 5. Найденное попутно (классификация)

- **IN_SCOPE (исправлено):**
  1. Требовался frontend-шов `web/app.js`: данные/методы Vue-приложения живут
     там (index.html — только шаблоны), поэтому UI-блоки D6 невозможно
     реализовать одним `index.html`. Это доказанная связанная причина; файл
     добавлен в изменённый набор D6 (только аддитивные state/methods).
  2. Канон-пины 17 → 18 в 4 тест-файлах и сознательное переутверждение
     `ROUTES_SHA256_F11` + `f8_baseline.routes` (+1 endpoint) — иначе
     существующие guard-тесты запрещают легитимную аддитивную эволюцию.
  3. `_StubCollector`/DI-опция `diagnostics=False` — иначе unit-тесты
     исполняли бы настоящие probes (нестабильность, зависимость от хоста).
- **CRITICAL_OUT_OF_SCOPE:** нет.
- **BACKLOG_ONLY:**
  1. `tests/test_mca10b_random_applications_block_d_round1041.py::test_blockE_f8_check_green_and_baselines`
     падает на базе D4-B `b6d7064c` и на D6 (`assert "643" in stdout`, реестр
     уже 644 после D4-B). Предсуществующая устаревшая пина D4-B, не дефект D6.
  2. В карте требований `SD1-D6-07` присутствует ДВАЖДЫ (source_line 117 и 352)
     при заявленном правиле «req_id уникален» — книжная коллизия PM; Builder
     идентификаторы не менял.
  3. `services/smartmodule_utils.send_chunked_reply` режет только по пробелам
     (из D5-находки) — чекап использует его как раньше, не менялось.
  4. `web/api/speech.py::_chat_overrides` fail-open при недоступном chat-слое
     (из D5-находки) — не затрагивалось.

## 6. Честные границы

1. Деплой/прод/VPS/Telegram не затрагивались; live-чекап, реальная доставка
   `prompt_readback`, реальный `getChatMember` и реальные ответы модели не
   выполнялись.
2. UI: проверены разметка/состояние/методы (статические + JS-guard), но **не**
   Playwright/Browser Use рендер — живая визуальная приёмка остаётся
   Reviewer/D7 (slice-graph `ui_acceptance_condition`).
3. Метрики retry/cache-hits/stale reads, доли hypothesis, golden eval,
   «код против неправильного SHA» и история роста БД/очереди **не
   инструментированы**; аналитика честно отдаёт `null`/`available=false`
   (D7/golden set и отдельные события).
4. `collect_for_checkup` исполняет локальные probes; на Windows-хосте
   `deploy.identity` может честно отдавать `path_denied`/`unknown` (linked
   worktree), что видно как partial, а не как «всё работает».
5. `memory_health.collect_metrics`/`mca_events.metrics` при отсутствии БД дают
   пустые группы — endpoint это показывает, а не подменяет нулями.
6. Полный suite не запускался (не требуется для аддитивного среза); два
   известных pre-existing RED из D3-свидетельства не входят в focused-набор.

## 7. Воспроизведение

```text
git -C <worktree> rev-parse HEAD        # 61e50806bf19d9ffbc9a7f77ba2f2b400b2eb29c
pytest tests/test_checkup_contract.py -q
pytest tests/test_checkup_handlers.py tests/test_checkup_service.py \
       tests/test_checkup_prompts.py tests/test_checkup_logs_fetcher.py \
       tests/test_tool_schemas.py tests/test_tool_router.py \
       tests/test_prompt_readback.py tests/test_diagnostic_probes.py -q
node --check web/app.js
node tests/js/app_methods_dup_keys_guard_test.js
```

## 8. Housekeeping

- Одноразовые probe-скрипты и выводы лежат в `WorkspaceData/runs/…` и после
  переноса доказательств закрыты `run-close` (worktree `self-diag/d6`
  сохраняется для Reviewer).
- Новых сторов/DDL/флагов/агентов/LLM-вызовов нет; `tools/gen_param_registry_round1025.py --check`
  остаётся зелёным (реестр 644).
