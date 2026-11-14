# SMART-CORRECTIVE-01 — production reconstruction of two checkup runs, watchdog incidents, provider health

- Дата: 2026-11-14, сервер UTC `06:40:17` (локально `18:40 +12:00`).
- Прод: `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot` (user `adminbot`),
  HEAD `0e4a144db476a1535ae3a2b79a7cce30354ad866`, branch `release/2.58.200`,
  `APP_VERSION=2.58.200`, PID `709883`, старт `2026-11-14T05:18:59Z`, `NRestarts=0`,
  `/healthz` 200 `{"status":"ok","version":"2.58.200"}`.
- Режим: **только чтение**. Ничего не деплоилось, не рестартилось, не менялось;
  Telegram-сообщений не отправлялось; платных LLM-вызовов probe не делал
  (только GET каталога провайдера и чтение уже существующей телеметрии).
- SSH: 1 recon + 1 основной сеанс; все команды ниже выполнены в этом одном
  основном сеансе. Секреты не печатались; chat id заменены на `CHAT_DM8`,
  `CHAT_C1`, `CHAT_C2`; имена участников — `[owner]`.
- Статусы требований и `plans/progress_scope.json` не менялись. Отчёт фиксирует
  только наблюдаемые факты и границы их доказанности; root cause не объявляется
  там, где трасса не сохранила аргументы.

## Итог (кратко)

1. Оба запуска найдены и восстановлены по цепочке
   `smart_messages → mca_bot_outputs → mca_events → journal → llm_usage_events`.
   - Запуск A: `чекап`, 05:47:36 → отчёт 05:48:23, correlation
     `checkup:e37c9a5d4a184d7ba189e0469ed075ba`.
   - Запуск B: reply `зайди в код посмотри что там по watchdog.jobs`,
     05:54:47 → ответ 05:57:33, correlation `0c1bb1ed17574a5c908525d5fe3f805b`.
2. Запуск A технически **не деградировал и не был остановлен лимитом**:
   7 раундов / 8 tool calls, `research_reason=ok`, `research_degraded=false`;
   модель сама завершила цикл после того, как `read_source_code` вернул
   141-строчный файл (по всем признакам — harness-скрипт), а не
   `services/mca_watchdog.py`. Точные arguments этого вызова не сохранились.
3. Запуск B: 4 раунда / 3 успешных+1 неуспешный read; третий read вернул
   329 строк `services/mca_watchdog.py`; финальный writer был обслужен
   **fallback-моделью `deepseek-flash`** после таймаута nano-gpt; ответ 2487
   символов, `tool_reason=finish` (не лимит).
4. Шесть активных `watchdog.jobs` инцидентов — все `ERROR/takeover`,
   `resolved_at=NULL`, `acknowledged_at=NULL`; связанные job-ы **уже
   терминальные**, активных/queued job-ов нет. Это lifecycle-артефакты
   регистрации/повторов, не шесть текущих падений. Самый частый инцидент
   (`asap8b01`) сейчас имеет 73 повтора (в чекапе было 72); 20 job-ов в
   `jobs_json`, все completed; свежий job 06:34:03→06:35:49 был помечен
   stale на 06:35:12 (heartbeat 06:34:04, stale=60 c) и всё равно завершился
   completed — подтверждённый false-takeover.
5. Провайдер сейчас работоспособен: каталог `1048576/32768` verified;
   за 60 минут 39 `LLM request OK`, 1 timeout, 1 fallback OK; последние
   успешные вызовы nano-gpt 06:19:20/06:34:11/06:34:29/06:34:38. Класс
   «HTTP 200, но пустой `message.content`» (06:05, 06:19) сохраняется и
   воспроизводится на semantic-батчах; real-LLM canaries выполнимы, но должны
   допускать этот класс отказа и fallback.

## Part A. Два запуска

### A.1. Общая идентичность (обоих запусков)

| Поле | Значение | Класс |
|---|---|---|
| Release / deployed SHA | `2.58.200` / `0e4a144db476a1535ae3a2b79a7cce30354ad866` | confirmed_production |
| Checkout / branch | тот же SHA / `release/2.58.200`; process PID 709883, start 05:18:59Z | confirmed_production |
| Manifest | schema 1, `deployed_sha=checkout_sha=0e4a144d…`, `previous=d20a7f73…` | confirmed_production (см. 2.58.200 evidence) |
| Chat | `CHAT_DM8` (owner DM) | confirmed_production |
| Message A | `smart_messages.id=2407142`, ts `05:47:36Z`, text `чекап` | confirmed_production |
| Message B | `smart_messages.id=2407145`, ts `05:54:47Z`, `reply_to_id=224`, text `зайди в код посмотри что там по watchdog.jobs` | confirmed_production |
| Route A | command checkup → `handlers/checkup.py::checkup_handler` → `CheckupService.checkup` с tool runtime | from_deployed_code + journal |
| Route B | reply-to-bot → Direct L1 → `mode=adaptive_tool_chain` → tool loop → L2 writer | confirmed_production (`direct_turn_context`) |
| Correlation A | `checkup:e37c9a5d4a184d7ba189e0469ed075ba` | confirmed_production (`mca_bot_outputs`, tool events) |
| Correlation B | `0c1bb1ed17574a5c908525d5fe3f805b` | confirmed_production (`mca_bot_outputs`, trace) |

### A.2. Запуск A — `чекап`

| № | Пункт | Наблюдение | Класс |
|---|---|---|---|
| 1 | identity/process | см. A.1; checkup identity `deployed_sha=checkout_sha=0e4a144db476`, `source_verified=True`, `sources=12/15` | confirmed_production |
| 2 | correlation/route | `checkup:e37c9a5d…`; handler checkup; chat DM8 | confirmed_production |
| 3 | LLM/provider/model | 7 вызовов, все `z-ai/glm-5.3-flash-uncensored` через `nano-gpt.com`; без fallback; steps `stage1` (1) + `tool` (6); usage in 8 258…20 478 / out 173…1 521 | confirmed_production (`llm_usage_events`, journal) |
| 4 | declared tools | ровно `read_source_code`, `inspect_runtime` (capabilities `source_code` + `deep_diagnostics`); подтверждено `research_tools` и планами | confirmed_production |
| 5 | chosen tools/args | последовательность: `inspect_runtime×2` (denied), `inspect_runtime×2` (ok), `read_source_code` locate (ok, 141 строка), `read_source_code` locate (unsupported/parse_error), `read_source_code` discover (ok), `read_source_code` locate (ok, 141 строка). Arguments не сохранены; для denied/failed есть только `args_fingerprint` | sequence confirmed_production; args **unrecoverable** (fingerprints only) |
| 6 | discovery/locate/read/followup | discover: `network_calls=0, repo_present=true`; locate: `verified=true, line_count=141, path_depth=6, ref_kind=branch, http=200, files_read=1`; followup не выполнялся; второй locate: `parse_error`, files_read=0 | confirmed_production |
| 7 | repo/ref/path/symbol/query/lines | repo identity: self Adminbot (`Henry-Case-dev/adminbot`, deployed_sha via checkup ctx — from code); path не записан; единственный 141-строчный не-тестовый Python-файл с 6 каталогами в deployed tree — `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_full/harness_stage_dump.py`; line range `[1,141]`; symbol/query **unrecoverable** | lines/ref_kind confirmed; path **inferred**, args unrecoverable |
| 8 | source provider/reason/local identity | локальный источник; `network_calls=0`, `repo_present=true`, `ref_kind=branch`; GitHub/SafeFetcher не вызывался; local identity — `resolve_self_repo_identity()` (deployed SHA, verified checkout) | provider confirmed_production; identity source from_deployed_code |
| 9 | search results/candidates/order/stop | candidate paths/ranked list не логируются (`files_considered` не в событии); известны `line_count=141`, `path_depth=6`, `files_read=1`; остановка — модель отдала финальный ответ (round 7), не поисковая ошибка | numbers confirmed; candidate list **unrecoverable**; stop confirmed |
| 10 | received fragments/relevance | дважды получен один и тот же 141-строчный файл (8 846 символов, verified); для watchdog-задачи это нерелевантный harness; других фрагментов нет | confirmed_production (размер/строки), relevance — оценка по содержанию |
| 11 | errors/partial/truncation | `truncated=false`, `retrievable_remainder=0`; round 4 `status=unsupported`, `stage=locator`, `reason parse_error`, out 2 812; round 3/6 ok; ошибок чтения БД нет | confirmed_production |
| 12 | fallback attempts | source fallback: **нет** (`network_calls=0`, GitHub не вызывался); LLM fallback: **нет** (все 7 вызовов GLM/nano-gpt) | confirmed_production |
| 13 | effective budget policy | master budgets OFF; `MCA_TOOL_MAX_*=0`; `TOOL_CHAIN_LIMITS_ENABLED=true` (factory), но лимиты 4/2/6/4/360 не применяются: 8 calls / 7 rounds прошли; evidence window 200 000/вызов, `source=window`, `used=5324/141`, без truncation; SourceReader `_MAX_LOCATOR_PATHS=3`, `_MAX_CANDIDATES=3`, `_MAX_REF_CANDIDATES=4` | from_deployed_code + confirmed by run (8 calls > старый 6-call cap) |
| 14 | limits/guards | `diagnostic_policy` разрешил `source_code` (`allowed_project_owner`); первый `inspect_runtime` — `permission_denied` (stages `incidents.active`, `dependencies.providers`), второй — `degraded success`; `diagnostic_output_validated status=clean`; `truncated=false` | confirmed_production |
| 15 | research stop reason | `research_reason=ok`, `research_degraded=false`, `research_rounds=7`, `research_calls=8`; финальный раунд 7 (out 3 066); **не** chain/timeout/budget | confirmed_production |
| 16 | final answer | delivered `checkup_report` output_id 1686, tg 224, 05:48:23, 3 059 chars, sha256_16 `c39e685fcd18715c`; pre-cleanup text не хранится (raw chars 3 066 по `checkup LLM OK`). В тексте: «…снапшот исходников нужный файл отдал только одним харнесс-скриптом деплоя, так что механизм остался непроверенным». | delivered confirmed; pre-cleanup text **unrecoverable** |
| 17 | prompt provenance | `prompt_source=global`, `prompt_hash=ccaf4803efe2ff79`, `prompt_version_used=global:ccaf4803efe2`, `prompt_chars=9 966`; global row `prompts.checkup_system_prompt` 3 030 chars, hash `b0c70f974e0e`, updated 2026-10-31T12:26:32, factory revision `checkup-p0-24-10`; composed system includes owner Core/Expression + addendum (chars 9 966). Chat override в `CHAT_C2` (12 469 chars, manual_edit 06:11:54) — не DM и не участвовал в запуске. | confirmed_production (telemetry); block-level revisions из кода |

**Последовательность A (journal, подтверждено):**

| Время UTC | Раунд | Вызов | Результат |
|---|---|---|---|
| 05:47:45 | 1 | `inspect_runtime` ×2 | denied, out 2 097 / 2 120; `permission_denied` (`incidents.active`, `dependencies.providers`) |
| 05:47:48 | 2 | `inspect_runtime` ×2 | ok, out 4 041 / 6 683 (status degraded) |
| 05:47:54 | 3 | `read_source_code` op=locate | ok, 141 строка, 8 846 chars, verified, local, network 0 |
| 05:47:58 | 4 | `read_source_code` op=locate | unsupported/`parse_error`, 2 812 chars, files_read=0 |
| 05:48:02 | 5 | `read_source_code` op=discover | ok, 2 376 chars, repo_present, network 0 |
| 05:48:04 | 6 | `read_source_code` op=locate | снова 141 строка, 8 846 chars |
| 05:48:23 | 7 | final answer | 3 066 chars pre-cleanup; report sent |

Проверка по коду: `services/mca_watchdog.py` в deployed checkout — **329 строк**
(13 417 символов), поэтому 141-строчный файл не мог быть watchdog-ом. Модель
сама остановилась после получения harness-файла; технической деградации тула
или лимита в трассе нет.

### A.3. Запуск B — reply `зайди в код посмотри что там по watchdog.jobs`

| № | Пункт | Наблюдение | Класс |
|---|---|---|---|
| 1 | identity/process | тот же процесс/релиз, PID 709883, start 05:18:59Z | confirmed_production |
| 2 | correlation/route | `0c1bb1ed17574a5c908525d5fe3f805b`; Direct trigger `reply_to_bot`, source message 225 (reply to bot report 224), L1 → adaptive tool chain → L2 | confirmed_production |
| 3 | LLM/provider/model | L1 planner: 2 вызова GLM/nano-gpt; orchestrator: 4 вызова GLM/nano-gpt; **L2 writer: 1 вызов `deepseek-flash` / `api.deepseek.com`** (fallback после nano-gpt timeout); usage writer in 110 918 / out 1 336; `llm_calls` planning 2, tool 4, final 1, provider_retry 2 | confirmed_production (`llm_usage_events`, journal) |
| 4 | declared tools | L1 capabilities `source_code`, tools `read_source_code`; active_tools 15 (включая `read_source_code`), точный полный список объявленных схем в событии не сохранён | from_deployed_code + journal |
| 5 | chosen tools/args | 4 раунда: read_source_code op=read (ok, 9 files / 3 904 lines, 328 385 chars), read_source_code op=read (error `source_missing`, 2 417 chars, 5 ms), read_source_code op=read (ok, 2 files / 329 lines, 19 050 chars); failed call args fingerprint `cab51a375a18197f`; successful args не сохранены | sequence confirmed; args except fingerprint **unrecoverable** |
| 6 | discovery/locate/read/followup | round 1: discover `network_calls=0`, locator `verified=true, files_read=1, line_count=3904, path_depth=1, ref_kind=branch, http=200`, followup `files_read=9`; round 2: `source_fetch failed source_missing, http=404, network_calls=0`; round 3: locator `line_count=329`, followup `files_read=2` | confirmed_production |
| 7 | repo/ref/path/symbol/query/lines | self repo / deployed ref (from code); path round 3 = `services/mca_watchdog.py` — подтверждён 329 строками, ответом и кодом файла; line range `[1,329]`; round 1 path/query unknown (9 files/3904 lines); symbol/query **unrecoverable** | path/line range confirmed; args unrecoverable |
| 8 | source provider/reason/local identity | локальный источник, `network_calls=0`; GitHub/SafeFetcher не вызывался; local identity — self repo (deployed SHA) через `diagnostic_research`/L1 | provider confirmed; identity from_deployed_code |
| 9 | search results/candidates/order/stop | round 1 candidates/order не логируются; известно 9 files/3904 lines; round 2 `source_missing`; round 3 2 files/329 lines; остановка — `tool_reason=finish`, `finish_reason=adaptive_tool_chain`, 4 раунда | numbers/stop confirmed; candidate list **unrecoverable** |
| 10 | received fragments/relevance | round 1: 9 файлов/3 904 строки/328 385 chars, verified, local; round 3: `services/mca_watchdog.py` 329 строк + 2 файла followup/19 050 chars, verified; ответ использует `_track_incident`, `stale_jobs`, `recover_stale`, `progress_stalled_jobs`, `WATCHDOG_TAKEOVER` — совпадает с кодом | confirmed_production |
| 11 | errors/partial/truncation | round 2: `source_missing`, http 404, network 0, retryable false, 2 417 chars; все ок-вызовы `truncated=false`, `remainder=0`; round 1 evidence window `limit=200000 source=call_budget used=182126/3904`; round 3 `used=13416/329` | confirmed_production |
| 12 | fallback attempts | source fallback: **нет** (round 2 local 404 не переключился на GitHub, network_calls=0); LLM fallback: **да**, финальный writer обслужен `deepseek-flash` после `LLM timeout` nano-gpt (05:57:23) и `LLM fallback OK`; direct-лог `fallback=False` относится к writer-level fallback, не к provider fallback | confirmed_production (source gap observed; LLM fallback) |
| 13 | effective budget policy | master OFF; chain limits 0; `TOOL_CHAIN_LIMITS_ENABLED=true` factory; 4 раунда, 3 tool calls (2 ok + 1 error), 348 060 delivered chars, capacity 3 233 876; evidence window 200k/вызов; SourceReader locator fixed `_MAX_LOCATOR_PATHS=3` | from_deployed_code + confirmed |
| 14 | limits/guards | `tool_phase finish_reason=adaptive_tool_chain`, `tool_degraded=true`, `reason=finish`, `rounds_used=4`; `L1_PLAN` latency 25 639 ms, input 13 235, confidence 0.9; `read_source_code` policy allowed; `diagnostic_output_validated clean`; usage_json 2 000-char cap (observability) | confirmed_production |
| 15 | research stop reason | `tool_reason=finish`; `finish_reason=adaptive_tool_chain`; 4 rounds; **не** chain_call_limit/chain_timeout; финальный writer завершил ответ | confirmed_production |
| 16 | final answer | delivered `direct_reply` output_id 1687, tg 226, 05:57:33, 2 487 chars, sha256_16 `27d77789888b6e08`; raw final digest `5a67ba1d8433ac88` (2 489 chars pre-cleanup), delivered digest `12c2248366a5d6e1`, divergence `owner_style_punctuation`, semantic_rewrite_count=0; pre-cleanup text **unrecoverable** | delivered/digests confirmed; pre-cleanup text unrecoverable |
| 17 | prompt provenance | `direct_turn_context.l1`: model `z-ai/glm-5.3-flash-uncensored`, slot `main`, action reply, response_act research, plan_source repair; `prompt_layers` 05:55:12: core/identity/expression/self_model/lessons/plan/humor/few_shot/style_hint/channel_output stages; writer manifest prefix lists blocks `channel_contract:channel_canon`, `core:core`, `identity:identity`, `self_model_traits` (folded), …; exact revisions/hashes **unrecoverable** — `usage_json` capped at 2 000 chars; style policy revision `g13.548c080d50c8`, source `global` | model/slot confirmed; prompt revisions unrecoverable (cap) |

**Последовательность B (journal/trace):**

| Время UTC | Раунд | Вызов | Результат |
|---|---|---|---|
| 05:55:12 | decision | DECISION_START/COMPLETE | action=silent, reason=recent_reply; позже L1 plan — reply/research |
| 05:55:37 | L1 | L1_PLAN | reply/research/source_code/read_source_code; latency 25 639 ms |
| 05:55:52 | 1 | read_source_code op=read | ok, 9 files/3 904 lines, 328 385 chars, network 0 |
| 05:56:00 | 2 | read_source_code op=read | error `source_missing`, 404, network 0, fp `cab51a375a18197f` |
| 05:56:14 | 3 | read_source_code op=read | ok, 2 files/329 lines, 19 050 chars, `services/mca_watchdog.py` |
| 05:56:23 | 4 | final tool phase | `finish_reason=adaptive_tool_chain`, degraded reason=finish, 348 060 chars |
| 05:57:23 | final | LLM timeout nano-gpt | fallback attempt/OK `deepseek-flash` |
| 05:57:33 | final | L2 writer / send | 2 489→2 487 chars; delivered tg 226 |

### A.4. Сопоставление маршрутов

| Аспект | A: standalone `чекап` | B: reply-driven code read |
|---|---|---|
| System prompt | checkup global prompt 3 030 chars + owner Core/Expression + diagnostic addendum; composed 9 966, hash `ccaf4803efe2` | Direct Core/Expression/composer manifest; exact composed hash not stored (cap); L1 `prompt_layers` includes core/identity/expression |
| Tool runtime | 2 declared tools (`inspect_runtime`, `read_source_code`); tool ctx with self identity | L1 capability `source_code`; `read_source_code`; full active set 15 |
| Tool loop | 7 раундов / 8 calls; 4 read_source attempts; 141-line harness; no fallback, no cap | 4 раунда / 3 calls; first huge 9-file read, one 404, then 329-line watchdog; no source fallback |
| Provider | GLM/nano-gpt all 7 calls; no fallback | GLM/nano-gpt L1/tool; final writer fallback deepseek-flash |
| Stop | `research_reason=ok`, model final | `reason=finish`, model final |
| Result | self-declared unverified; no watchdog code | relevant watchdog analysis, 329 lines |

**Вывод по различию:** оба запуска шли через один и тот же tool-loop/SourceReader
и один и тот же локальный источник; разница в том, какие `read_source_code`
arguments выбрала модель. В A модель получила 141-строчный harness-файл и
остановилась; в B после явного указания владельца получила
`services/mca_watchdog.py` (329 строк). Трасса A не содержит arguments/path,
поэтому утверждать, что причиной был именно SourceReader, нельзя; доказано
только, что технической деградации/лимита в A не было и что fallback на GitHub
не выполнялся. Зафиксированный разрыв: локальный `source_missing` (B round 2)
не переключился на удалённый источник (`network_calls=0`).

## Part B. Шесть `watchdog.jobs` инцидентов

### B.1. Таблица активных инцидентов

Все шесть: `process_id=watchdog.jobs`, `severity=ERROR`, `resolved_at=NULL`,
`acknowledged_at=NULL`, `fallback_used=false`, `first_trace_id=NULL`,
`last_trace_id=NULL`.

| Incident ID | pipeline_type (owner) | stage | repeat | first_ts | last_ts | jobs_json | job statuses | unresolved? |
|---|---|---|---|---|---|---|---|---|
| `inc_330e13ec…f557` | memory | takeover | 3 | 2026-10-02T11:29:30Z | 2026-10-22T00:14:50Z | 1 | 1 cancelled | да |
| `inc_c1633276…3ab3` | vision.media | takeover | 12 | 2026-10-19T09:14:44Z | 2026-11-13T19:38:01Z | 11 | 3 completed, 8 interrupted | да |
| `inc_9b7b2d37…035a` | summary | takeover | 3 | 2026-10-19T13:09:19Z | 2026-11-12T07:26:15Z | 3 | 1 completed, 2 interrupted | да |
| `inc_4627f4bd…7184` | asap8b01 | takeover | **73** | 2026-10-22T06:21:11Z | 2026-11-14T06:35:12Z | 20 (cap) | 20 completed | да |
| `inc_54307e9f…3cdd` | mca16 | takeover | 15 | 2026-11-10T04:08:05Z | 2026-11-14T03:40:52Z | 15 | 15 completed | да |
| `inc_0bf85af4…db95` | qnd.event | takeover | 19 | 2026-11-10T13:27:02Z | 2026-11-14T03:40:52Z | 18 | 18 interrupted | да |

`PRAGMA`/SQL: `SELECT * FROM mca_incidents WHERE resolved_at IS NULL ORDER BY first_ts`. Активных инцидентов других процессов нет; `by_process` содержит только `watchdog.jobs: 6/6`.

### B.2. Job-ы и их фактические состояния

Запрос: `SELECT * FROM task_jobs WHERE job_id IN (…)` по 68 id из `jobs_json`.

| owner/kind | status | n (в связанных job-ах) |
|---|---|---|
| asap8b01 / initiative.observe | completed | 20 (в 73-повторном инциденте) |
| qnd.event / initiative.event | interrupted (`worker_lost`) | 18 |
| mca16 / experience.review | completed | 15 |
| vision.media / vision.media | interrupted / completed | 8 / 3 |
| summary / cover_style | interrupted / completed | 2 / 1 |
| memory / graphrag_rebuild | cancelled | 1 |

- **Ни одного `queued`/`running` job-а нет** (`active_jobs=[]`), queued с deadline — `0`.
- `fencing_token`: у interrupted/восстановленных — 1 (recover_stale bump), у completed vision — 0, у memory cancelled — 13; `generation` везде 0; `attempt` 1 (max 1–4).
- `finished_at` позже `incident.last_ts`:
  - memory: 1/1 (job cancelled 2026-10-23 после последней регистрации 2026-10-22) — **detection artifact**;
  - summary: 1/3 (cov_e423… completed `bad_json` 07:27:35 после last_ts 07:26:15) — detection artifact;
  - asap8b01: 1/20 (job 3550 completed 06:35:49 после last_ts 06:35:12) — **detection artifact**;
  - mca16: 0/15; vision: 0/11; qnd: 0/18 (interrupted, без finished_at).
- `created_before_process_start` (05:18:59Z): 19/20 asap8b01, все 15 mca16, все 11 vision, все 18 qnd, все summary, memory — то есть большинство job-ов относятся к прошлым процессам/рестартам; свежий только job 3550 (создан 06:34:03 после старта).
- **Nonterminal** (нет `finished_at`): vision 8 (interrupted), summary 2 (interrupted), qnd 18 (interrupted); asap8b01/mca16/memory — 0.
- `mca_pipeline_runs` для этих job-ов: **0** строк (`pipeline_run_id` null) — отдельного durable root run нет.

### B.3. «Самый старый / 72 повтора» — отдельно

- В чекапе 05:48 бот видел 72; сейчас `inc_4627f4bd…7184` имеет **73** (последняя
  регистрация 06:35:12Z), поэтому счётчик растёт на новых детекциях.
- **Не самый старый по `first_ts`:** абсолютно старейший активный —
  `inc_330e13ec` (memory, 2026-10-02, 3 повтора); инцидент с 72/73 повторами —
  `inc_4627f4bd` (asap8b01, first 2026-10-22). «Самый старый» в формулировке
  владельца относится к долгоживущему/частому инциденту, а не к минимальной
  дате `first_ts`; отчёт фиксирует оба факта.
- 20 сохранённых job-ов (cap) — все `initiative.observe`/`completed`, созданы
  2026-11-12…14, длительность 1,5–2,8 мин, `heartbeat_at` = момент старта
  (не обновлялся), `finished_at` позже. Свежий job 3550:
  created `06:34:03`, heartbeat `06:34:04`, incident last `06:35:12`,
  finished `06:35:49` → на 06:35:12 heartbeat был 68 с > stale=60 c;
  watchdog сделал takeover (`fencing_token=1`), но job всё равно завершился
  completed. Это **подтверждённый false-takeover**, а не 72 падения.
- `repeat_count=73` при span 33 134 мин (23,0 сут) — это не «раз в минуту»:
  средний интервал ~7,6 ч; `(last-first)/60 ≈ 33 134`, а не 73. Формула
  «(last-first)/60 ≈ repeat_count» для этого инцидента **не выполняется**;
  повторы — отдельные детекции, в том числе несколько за один sweep/несколько
  job-ов с одинаковым fingerprint. 72/73 — число детекций, не падений.
- Заголовок инцидента ссылается на job `13c7347e0a…`, которого уже нет в
  `jobs_json` (cap 20), — история обрезана, но `repeat_count` сохранён.

### B.4. `WATCHDOG_TAKEOVER` и payload

- Всего `mca_events.event_name='WATCHDOG_TAKEOVER'`: **125**; в окне
  05:25–06:50: **1** (`06:35:12Z`, `level=INFO`, `reason=takeover_recovered`,
  `stage=takeover`).
- **Job identifiers в событии отсутствуют**: `entity_ids=NULL`, `usage_json=NULL`,
  `error_json=NULL`; `job_ids` не проходит whitelist события. Связь с job-ом
  восстановлена только по соседнему `INCIDENT`-событию 06:35:12
  (`entity_ids=["inc_4627…"]`, `pipeline_type=asap8b01`) и по времени.
- `INCIDENT` reason при обновлении существующего инцидента всё равно
  `incident_opened` (06:35:12 для уже активного `inc_4627…`) — вводит в
  заблуждение; lifecycle `acknowledged ≠ resolved`, авто-закрытия нет.
- Почему активны: `resolved_at`/`acknowledged_at` NULL, явного `resolve` не
  было; `open_or_update` продлевает `last_ts`/`repeat_count`, но не закрывает
  запись после завершения job. Это lifecycle-дефект наблюдаемости, не текущая
  работа.

### B.5. Effective watchdog limits

| Параметр | Effective | Источник |
|---|---|---|
| `MCA_JOB_STALE_SECONDS` | **60** | default; env отсутствует |
| `MCA_JOB_HEARTBEAT_SECONDS` | **15** | default; env отсутствует |
| `MCA_PROGRESS_STALL_DEFAULT_SECONDS` | **600** | default; env отсутствует |
| `MCA_PROGRESS_STALL_LLM/VIDEO/ARCHIVE_SECONDS` | константы 300 / 1800 / 3600; для owner-ов инцидентов effective **600** (mapping только для `llm`/`video`/`archive`) | default; env отсутствует; `progress_stall_seconds(owner)` = 600 для всех owner-ов инцидентов |
| `limits.vision_job_lease_seconds` | **180** (PG row отсутствует → default) | PG `bot_settings` row absent; `media_readiness.lease_seconds()` |
| `MCA_HEARTBEAT_WATCHDOG_ENABLED` | **true** | default; env отсутствует |
| `MCA_INCIDENTS_ENABLED` | **true** | default; env отсутствует |
| `process_started_at` | **2026-11-14T05:18:59Z** | systemd `ExecMainStartTimestamp` |

### B.6. Текущее воздействие

- Активных/queued job-ов нет; systemd active; `/healthz` 200; пользовательских
  ошибок в текущем окне, связанных с watchdog, нет.
- `mca_media_analyses`: ready 5 361, failed 2 108, unavailable 73, **running 8**
  (старые записи 2026-10-19…2026-11-09, `updated_at=created_at`, без завершения);
  pending 0. По времени/asset provenance они согласуются со старыми
  vision.media interrupted job-ами, но прямая связь job→analysis в событиях не
  сохранена; это застрявшие строки состояния, а не текущая очередь.
  Пользовательское воздействие по доступным данным не подтверждено.
- qnd.event: 18 interrupted `initiative.event` (`max_attempts=1`) — потенциально
  потерянные внутренние события инициативы; повторного запуска нет; внешнего
  пользовательского эффекта в данных нет.
- Остальные инциденты — detection artifacts (job-ы завершились/отменены позже
  последней регистрации).

## Part C. Provider health и effective flags

### C.1. nano-gpt.com

- `resolve_capacity` (каталог, без платного вызова):
  `provider=nanogpt`, `effective_window=1048576`, `max_output_tokens=32768`,
  `source=provider_catalog`, `confidence=verified`, `fallback_used=false`.
- Journal 60 мин (05:40–06:40 UTC): `LLM request OK` **39**, `LLM timeout` **1**,
  `LLM fallback OK` **1**, `LLM request retry` **1**, строк с `empty content` —
  **6** (включая эхо traceback двух semantic-батчей 06:05/06:19).
- Последние успешные nano-gpt вызовы: 06:19:20 (out 8 151), 06:34:11,
  06:34:29, 06:34:38; последний `LLM timeout` — 05:57:23; после него успешные
  вызовы есть. Провайдер сейчас отвечает.
- Класс отказа: HTTP 200, `LLM request OK`, но `choices[0].message.content`
  пустой (`LLMBadResponseError("chat/completions: empty content")`) —
  наблюдался 06:05 и 06:19 на semantic-батчах; в pre-deploy окне тот же класс
  встречался 29 раз. Это не отсутствие сети; real-LLM canaries **выполнимы**,
  но должны допускать этот класс и fallback/retry. Nano-gpt также дал
  `ReadTimeout`/`total_budget_exceeded` в 05:56–05:57; финальный writer ушёл
  на `deepseek-flash` (fallback OK).

### C.2. Effective flags (запрошено отдельно)

| Ключ / параметр | Значение | Источник / класс |
|---|---|---|
| `flags.factcheck_pipeline_v2` (PG) | `true`, updated `2026-10-20T09:44:06.723000+00:00` | confirmed_production (bot_settings) |
| `FACTCHECK_PIPELINE_V2_ENABLED` (env) | **отсутствует** | confirmed_production |
| code default `settings.FACTCHECK_PIPELINE_V2_ENABLED` | `False` | from_deployed_code |
| `pipeline_v2_enabled()` — с read-only PG-шимом | **True** | confirmed resolver precedence (hot PG row → env → False); standalone без кэша даёт False, что подтверждает, что true приходит из PG |
| **Effective FACTCHECK v2** | **ВКЛЮЧЁН (true)** | подтверждено: PG row true, env отсутствует, code default false |
| `flags.checkup_enabled` | `true`, updated `2026-09-10T17:17:07.793360+00:00` | confirmed_production |
| `flags.checkup_memory_metrics_enabled` | `true`, updated `2026-08-29T17:04:33.799627+00:00` | confirmed_production |
| `prompts.checkup_system_prompt` (global row) | present, 3 030 chars, sha256_16 `b0c70f974e0e`, updated `2026-10-31T12:26:32.312537+00:00`, category prompts | confirmed_production; source `global` (activation `deploy_activate` + `legacy_import`, factory revision `checkup-p0-24-10`) |
| Checkup run A composed prompt | `prompt_source=global`, hash `ccaf4803efe2ff79`, version `global:ccaf4803efe2`, chars **9 966** | confirmed_production (`checkup_triggered.source_ref_json`) |
| `CHAT_DM8` checkup override | absent | confirmed_production |
| `CHAT_C2` checkup override | present 12 469 chars, sha256_16 `31d175065461`, `manual_edit` owner 06:11:54Z, revision `rev:d31300ef35a0` | confirmed_production; **не DM и не участвовал в A/B** |
| CheckupService prompt resolver | читает **global** слой (`hot.get('prompts.checkup_system_prompt')`), chat override не читает | from_deployed_code (`services/checkup_service.py:85-95`, `prompt_style_blocks.resolve_prompt_with_source`) |
| Effective checkup prompt (DM, на момент A) | global row (factory content) + owner Core/Expression + diagnostic addendum; composed 9 966 chars, hash `ccaf4803efe2` | confirmed run telemetry |
| Effective checkup prompt row сейчас | global row / factory revision; C2 chat override существует, но checkup-код его не использует | confirmed_production + from_deployed_code |

## Ограничения доказательств (evidence limitations)

1. **Arguments tool-вызовов не хранятся.** Для denied/failed есть только
   `args_fingerprint` (`inspect_runtime`: `f8fd28779c6508a5`, `88f6dd74bf3c427d`;
   `read_source_code` B round 2: `cab51a375a18197f`). Подбор по вероятным
   комбинациям не дал совпадения. Пути/query/symbol/line ranges, выбранные
   моделью, восстановить нельзя.
2. **141-строчный файл A** идентифицирован только по совокупности
   `line_count=141`, `path_depth=6`, deployed tree и тексту ответа модели; в
   трассе пути нет. Единственный не-тестовый 141-строчный Python-файл с 6
   каталогами — `plans/features/asap-speech-arch/evidence/p0-hotfix/probes_full/harness_stage_dump.py`.
   Это **inference**, не literal trace.
3. **`direct_turn_writer.usage_json` обрезан 2 000 символами** хранилищем
   `mca_events`; manifest/request/completion (provider/fallback/finish_reason/
   usage/revisions) в durable-событии не поместились. Модель/fallback
   восстановлены по `llm_usage_events` и journal.
4. **`checkup_triggered.trace_id=NULL`**, хотя tool-события используют
   `checkup:e37c…`; join только через `mca_bot_outputs` и временную корреляцию.
5. **Успешные tool calls не эмитятся в `mca_events`** (только notable
   terminal); последовательность успешных read восстанавливается по journal
   `TOOL_*`/`[tools]`.
6. **`WATCHDOG_TAKEOVER` не сохраняет job_ids** (whitelist события); связь с
   job-ом — по времени и соседнему `INCIDENT`-событию.
7. **Pre-cleanup тексты моделей не хранятся**: есть delivered text, digest,
   chars; raw model output до cleanup — unrecoverable.
8. **`mca_media_analyses.running=8`** — только строки состояния с старыми
   `updated_at`; нет события/потребителя, доказывающего текущую обработку.
9. **Историческая per-sweep картина инцидентов** не хранится отдельно;
   `repeat_count` кумулятивен, `jobs_json` ограничен 20 id.
10. **Checkup prompt text не копировался** в отчёт/raw; только hash/length/source.
11. Все проверки — read-only; никаких выводов о root cause за пределами
    перечисленных фактов не делается. Отсутствие исторической трассы не
    отменяет независимо доказанных дефектов кода.

## Команды и запросы (redacted)

- Identity/service: `git rev-parse HEAD`, `systemctl show admin_bot -p …`,
  `ps -o pid,user,group,etime,args -p 709883`, `curl -sS https://admin-bot.duckdns.org/healthz`.
- Journal: `sudo -u adminbot journalctl -u admin_bot --since "2026-11-14 05:35:00" --until "2026-11-14 06:45:00" --no-pager --output=short-iso` (4 149 строк; выбраны `[checkup]`, `TOOL_*`, `[tools]`, `source_*`, `direct`, `LLM`, `WATCHDOG/INCIDENT/RECOVERY`);
  предыдущий boot `--since 2026-11-13 08:36:00 --until 2026-11-14 05:18:58` (69 339 строк; 1 252 watchdog/takeover строки).
- SQLite (read-only, `mode=ro`, `PRAGMA query_only=1`):
  `SELECT … FROM smart_messages WHERE timestamp BETWEEN … AND (chat_id=? OR instr(text,'чекап')>0 OR instr(text,'зайди в код')>0)`;
  `SELECT … FROM mca_bot_outputs WHERE sent_at BETWEEN … AND chat_id=?`;
  `SELECT … FROM mca_events WHERE ts BETWEEN … AND (chat_id=? OR trace_id IN (…))`;
  `SELECT … FROM mca_incidents WHERE resolved_at IS NULL ORDER BY first_ts`;
  `SELECT * FROM task_jobs WHERE job_id IN (…)`; `SELECT owner,kind,status,count(*) … GROUP BY 1,2,3`;
  `SELECT … FROM task_jobs WHERE status IN ('queued','running')`;
  `SELECT COUNT(*) FROM mca_events WHERE event_name='WATCHDOG_TAKEOVER' AND ts BETWEEN …`;
  `SELECT … FROM mca_media_analyses WHERE status IN ('pending','running')`.
- PostgreSQL (read-only, `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`):
  `bot_settings` (`flags.factcheck_pipeline_v2`, `flags.checkup_*`,
  `prompts.checkup_system_prompt`, `limits.vision_job_lease_seconds`);
  `chat_profiles.chat_params->'overrides'->>'prompts.checkup_system_prompt'`;
  `prompt_activations`/`prompt_revisions` for `checkup.base.system`;
  `llm_usage_events` за окно и по correlation id.
- Code (deployed `0e4a144d`): `services/checkup_service.py`,
  `handlers/checkup.py`, `services/tool_loop.py`, `services/tool_router.py`,
  `services/source_reader.py`, `services/turn_trace.py`, `services/mca_watchdog.py`,
  `services/task_supervisor.py`, `services/mca_incidents.py`,
  `services/mca_gates.py`, `services/factcheck_orchestrator.py`,
  `services/prompt_style_blocks.py`, `services/prompt_registry.py`.

## Housekeeping

- Remote probe и `/tmp` удалены в том же сеансе
  (`probe_removed=yes tmp_removed=yes`); production-tree чистый.
- Durable: этот отчёт + redacted raw `raw/production-runs-and-incidents-2.58.200.txt`.
- Локальный run `WorkspaceData/runs/…/report-b34a6fa199` закрывается
  `run-close` после промоушена; `unit-check` — отдельно.
- `plans/progress_scope.json`, `plans/workflow_state.md` и статусы карты не
  менялись.
