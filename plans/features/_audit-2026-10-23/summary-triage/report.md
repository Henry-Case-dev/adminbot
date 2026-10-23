# SUMMARY-PROD-TRIAGE — почему 21 DEGRADED и 5 FAILED, что закрывает поезд 2.58.112

Дата: 2026-10-23 (локальные часы исполнителя, UTC+12). Лейн: `SUMMARY-PROD-TRIAGE`, режим read-only.
Прод: `198.46.175.136`, версия **2.58.111**, HEAD `fbf9013d89b03e38473ce6824a460fdbb736fff8`, процесс запущен `2026-10-22 13:14:31Z`, NRestarts=0.
SSH-коннектов: **5** (одиночный логин `nik`, интервалы ≥60 с, без sudo-перебора и ретраев). Healthz по HTTP: `{"status":"ok","version":"2.58.111"}` 200.
Мутаций на проде нет: SQLite `mode=ro` + `PRAGMA query_only=ON`, PG — только `SELECT`, journal/healthz — чтение. Скрипты на сервер доставлялись через `bash -s` по stdin (файлов на сервере не создавалось).

## 0. Поправка к вводным данным (сверка часов)

Задача ссылалась на «деплой 2.58.111 (13:14Z 23.10)». Факт по серверу и systemd: релиз 2.58.111 поставлен **22.10.2026 13:14:31Z** (`Stopping` 13:14:20Z → `Started` 13:14:31Z). «23.10» — это локальная дата исполнителя (UTC+12). Дальше все времена — **серверные UTC**.

Второе следствие: между деплоем 2.58.111 и моментом снятия данных (22.10 16:50Z) **нет ни одного завершённого Summary-прогона**. Cron Summary — `0,6,12,18` в `Asia/Yekaterinburg` (+05) = **19:00Z, 01:00Z, 07:00Z, 13:00Z**; следующий тик после деплоя — 19:00Z 22.10, то есть на +2 ч 10 мин позже снятия данных. Поэтому все 28 ранов в выборке — **до 2.58.111**, а «после деплоя» = 0 наблюдений (это не пробел выборки, а реальное окно).

## 1. Что именно в `summary_runs` (окно хранения 7 дней)

`SUMMARY_SOURCE_WINDOW_RETENTION_DAYS=7`; тиков в окне ровно 28 (4/сутки × 7) — **пропущенных тиков нет**, таблица не «потеряла» ни одного прогона. Все 28 ранов — один чат `-1002661910336` (main-чат владельца).

| # | run (8) | старт UTC | state | L2 review | coverage | fallback | publication | health |
|---|---------|-----------|-------|-----------|----------|----------|-------------|--------|
| 1 | d39a961b | 10-15 19:00 | DEGRADED | unusable | 100.0 | legacy | published | degraded |
| 2 | 082217c0 | 10-16 01:00 | DEGRADED | rejected | 100.0 | legacy | published | degraded |
| 3 | 30b3677b | 10-16 07:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 4 | da33f05d | 10-16 13:00 | **FAILED** | — (orphan) | — | — | — | — |
| 5 | 73f16a62 | 10-16 19:00 | DEGRADED | нет (L2 invalid `unknown_field`) | 0.0 | legacy | published | degraded |
| 6 | 689b89ad | 10-17 01:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 7 | 008c3640 | 10-17 07:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 8 | 5187dee4 | 10-17 13:00 | DONE | approved | 0.0 | none | published | ok |
| 9 | 39339fd9 | 10-17 19:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 10 | 64b8a6d4 | 10-18 01:00 | DEGRADED | unusable | 0.0 | legacy | published | degraded |
| 11 | a5df207f | 10-18 07:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 12 | 1a123c63 | 10-18 13:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 13 | c725573d | 10-18 19:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 14 | 9ded95d0 | 10-19 01:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 15 | fd58315d | 10-19 07:00 | DEGRADED | нет (L2 invalid `unknown_field`) | 0.0 | legacy | published | degraded |
| 16 | 9aea8508 | 10-19 13:00 | **FAILED** | degraded (`review_invalid_json`) | 0.0 | none | **failed** | degraded |
| 17 | b61e74b5 | 10-19 19:00 | **FAILED** | approved (11 findings fixed) | 0.0 | none | **failed** | ok |
| 18 | a911221a | 10-20 01:00 | DEGRADED | unusable | 100.0 | legacy | published | degraded |
| 19 | 631535a6 | 10-20 07:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 20 | f071bb38 | 10-20 13:00 | DEGRADED | rejected (l2_calls=2) | 0.0 | legacy | published | degraded |
| 21 | cff5c18e | 10-20 19:00 | **FAILED** | unusable | 0.0 | none | **failed** | degraded |
| 22 | 9455c0a6 | 10-21 01:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 23 | b8edd2db | 10-21 07:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 24 | 6707dc8d | 10-21 13:00 | DONE | approved (first pass) | 0.0 | none | published | ok |
| 25 | 9e865ec2 | 10-21 19:00 | DEGRADED | unusable | 0.0 | legacy | published | degraded |
| 26 | e175025a | 10-22 01:00 | DEGRADED | rejected | 0.0 | legacy | published | degraded |
| 27 | 3e10f7b8 | 10-22 07:00 | DEGRADED | rejected | 100.0 | legacy | published | degraded |
| 28 | 718e9ea6 | 10-22 13:00 | **FAILED** | unusable | 0.0 | none | **failed** | degraded |

### Распределение

| Разрез | Значение |
|---|---|
| state | **DONE 2 / DEGRADED 21 / FAILED 5** |
| publication | published 23, failed 4, нет 1 (orphan) |
| L2 review (25 эпизодов) | approved **3** (12%), rejected **15** (60%), unusable **6** (24%), degraded/reviewer invalid-JSON **1** (4%) |
| review не было (L1/L2 structural invalid) | 2 рана (`73f16a62`, `fd58315d`) → legacy |
| legacy fallback (`final_policy=LEGACY_FALLBACK`) | 21 ран (все DEGRADED) + 2 FAILED-рана успели войти в legacy (`cff5c18e`, `718e9ea6`), но не опубликовали |
| coverage в `SUMMARY_RUN_DONE` (12 дней, 66 событий) | **0.0 — 60**, 100.0 — 6 |
| первый проход ревью | approved 1 из 25 |

## 2. Пять FAILED — разные причины, ни одна не «поездная»

Все пять разобраны по durable-событиям (`mca_events`), `summary_run_stages` и journal-окнам вокруг рана.

| run | причина (факт) | доказательство | закрывает ли 2.58.112 |
|---|---|---|---|
| `da33f05d` 10-16 13:00 | **orphan**: `SUMMARY_RUN_START` в 13:00, дальше ничего; окно/стадии не появились; закрыт startup-recovery `orphan_no_owner` в 16:12Z | `summary_run_stages`: только `stage=run status=failed reason=orphan_no_owner`; `window_from/to=NULL` | **Нет.** Отдельный дефект жизненного цикла рана (создан, но не взят владельцем). С 10-16 не повторялся |
| `9aea8508` 10-19 13:00 | **рестарт сервиса во время рана**: `Stopping admin_bot.service` 13:07:43.864Z; `CancelledError`; публикации не было | journal: `Stopping` → `[shutdown] summary: stopped accepting new work` → `SUMMARY_COMPLETE ... publication_status=-`, в 13:07:44 стек `asyncio.exceptions.CancelledError`; событие `SUMMARY_RUN_DONE status=degraded` | **Исход — нет.** B-1 (#4 фикса) сделает такой терминал честным (`failed/interrupted` вместо «ok»), но публикации не добавит |
| `b61e74b5` 10-19 19:00 | **рестарт сервиса внутри публикации**: движок стоял в `_publish_rich_document_impl` → `generate_image_verbose` (обложка), `Stopping` 19:13:31.488Z | traceback в journal 19:13:31: `summary_generator.py:3128 → :3392 → image_generation.py:1700/1770 wait_for`; `SUMMARY_PUBLISH start` без терминала | **Нет** (то же: честный reason, не публикация) |
| `cff5c18e` 10-20 19:00 | **рестарт сервиса внутри cover-стадии**: `Stopping` 19:09:33.793Z, за 13 мс до `SUMMARY_COMPLETE` | journal 19:09:33: `webapp lifespan finished` → `Scheduler shut down` → `[...] stopped accepting new work` → `SUMMARY_COMPLETE publication_status=-` | **Нет** (то же) |
| `718e9ea6` 10-22 13:00 | **рестарт релизом 2.58.111**: `Stopping` 13:14:20Z, legacy-текст и обложка были готовы, публикация не состоялась | journal: `COVER_COMPLETE status=ok 13:13:45` → `Stopping 13:14:20` → `SUMMARY_COMPLETE 13:14:20`; `SUMMARY_RUN_DONE status=degraded` | **Нет по исходу**; по причине — да: прерванный ран перестанет писаться как `status=ok` |

**Вывод по FAILED:** 4 из 5 — это не дефект Summary-логики, а **деплой/рестарт в середине прогона**; 1 — orphan. Класс «опубликованный ран, отменённый после публикации» (ровно то, что чинит B-1) в окне **не наблюдался ни разу**: у всех FAILED `publication_status` = `failed`/NULL, ни одного `published` + `FAILED`.

Дополнительно видно, что graceful-drain не защищает такие раны: в момент отмены журнал пишет
`[shutdown] summary drain done | in_flight=0 | cancelled=0 | finalized=0` (10-19 13:07:44), хотя ран в этот момент был жив и стоял в cover. То есть учёт in-flight для Summary не видит ран, запущенный из `SummarySchedulerService._tick`.

## 3. Двадцать один DEGRADED — одна причина

У всех 21 `final_policy = LEGACY_FALLBACK` и `pipeline_health = degraded` в `summary_runs`; `health_of()` независимо трактует `fallback=legacy` и `coverage < epsilon` как degraded (`pipeline_analytics.py:1281-1287`). То есть state DEGRADED здесь — **следствие ухода в legacy**, а не следствие coverage.

Раскладка по причине входа в legacy:
- **rejected** (blocking findings остались после 2 ревизий) — 15;
- **unusable** (reviewer verdict `unusable`, прошёл evidence-gate) — 4;
- **structural invalid L2/L1** (`unknown_field`) — 2.

Важный контрпример к версии «всё из-за FactView»: 4 рана (`d39a961b`, `082217c0`, `a911221a`, `3e10f7b8`) шли с **материализованным** пакетом (`L1 degraded_map_fallback` → deterministic package, coverage **100.0**) и всё равно получили rejected/unusable — **0 approvals из 4**. Значит пустой FactView усиливает проблему, но не является её единственной причиной.

## 4. `l2_review_rejected` / `unusable`: что именно отвергается

### 4.1. Что может блокировать (по коду, HEAD)

`services/summary_l2_review.py`:
- серверная таксономия (`:193-216`): блокируют **только 13 hard-кодов** — `unsupported_claim`, `wrong_person_attribution`, `quote_text_not_found`, `quote_speaker_unresolved`, `quote_speaker_mismatch`, `quote_source_ambiguous`, `forward_attribution_error`, `reply_attribution_error`, `unsupported_number`, `timeline_inconsistency`, `contradiction_with_package`, `invented_name`, `factual_overstatement`;
- `duplicate_event` и `major_topic_omitted` — soft, **не могут** выбросить статью в legacy (`:211-216`);
- `severity` модели — advisory, сервер пересчитывает сам (`:225-231`);
- `unusable` принимается только при ≥2 независимых hard-finding (разные коды и разные абзацы) **или** при deterministic-proof `quote_unresolved_blockers` (`:417-431`); иначе даунгрейд в `needs_fixes` (`:1163+`);
- `rejected` = после `MAX_REVISIONS=2` (бюджет 6 LLM-вызовов) blocking не ушли (`:1380`, `:1404`).

То есть **длина/стиль/структура статью в legacy не отправляют by design**. Гипотеза «ревьюер слишком строгий к форме» кодом не поддерживается: блокируют только фактические претензии (цитаты, атрибуция, числа, имена, противоречия).

### 4.2. Что показывают факты

- `first_pass_approved = 0` в 24 из 25 эпизодов (единственное исключение — `6707dc8d`).
- В 15 rejected-ранах `revision_count=2`, и **`revision_fixed=0` во всех 15**: две ревизии не убрали ни одного blocking-finding. При этом механизм работоспособен: `b61e74b5` за одну ревизию закрыл 11 findings и получил approved.
- `unusable` в трёх наблюдаемых случаях (`cff5c18e`, `9e865ec2`, `718e9ea6`) пришёл с `findings_total=0` — вердикт «непригодно» без валидных находок; терминал разрешил deterministic-proof по котировкам (`quote_unresolved_blockers`).
- Детерминированный валидатор writer'а стабильно не подтверждает цитаты: `L2_COMPLETE quotes_verified=0` при `quotes_total=41/6/11` и `quotes_repaired=39/6/10` (`9aea8508`, `b61e74b5`, `cff5c18e`). У `718e9ea6` цитат не было вовсе (`quotes_total=0`), и всё равно `unusable`.
- Пакет, против которого проверяют: `FACT_VIEW_BUILT threads=0 fragments=0 unassigned=0` во всех просмотренных ранах (это тот самый v1/v2-дефект FactView), `L1_COMPLETE facts=0` — во **всех 20** строках L1-завершения за 10-19…10-22. То есть у writer'а нет семантического индекса фактов, а у ревьюера — id-space пакета.

### 4.3. Качество генерации или строгость ревью?

Факты поддерживают **две независимые причины**, и обе — не «строгость формы»:

1. **Пустой пакет/нулевые факты** (дефект FactView + L1 `facts=0`): нечем верифицировать цитаты (`quotes_verified=0`), ревьюер видит фактические претензии без опоры. Это частично закрывается 2.58.112 (v2 anchor-map в FactView) — но только частично, см. п.2.
2. **Качество самой статьи/ревизии**: 4 рана с материализованным пакетом (coverage 100) тоже rejected; 15/15 rejected не улучшились после 2 ревизий. Это уже не про coverage и не про пустой пакет.

Честно: **точный список кодов находок доказать нельзя** — `finding_codes` живут только в `ctx.stage_events` в памяти (`summary_l2_review.py:867-880`, `_record` → `:884`), в БД не пишутся; `summary_run_stages` не имеет колонок под них; `mca_pipeline_runs` для этих ранов пуст (`n=0`); событие `SUMMARY_L2_REVIEW` за всю историю имеет **2 строки** (последняя 10-03), хотя в journal 17 строк `L2_REVIEW`. Текст отклонённого L2-драфта тоже нигде не сохраняется. Поэтому «ревьюер ошибся» доказать нечем — как и «ревьюер прав» по конкретному абзацу.

Ослаблять проверку ради зелёного не предлагаю: единственный корректный шаг — сделать находки durable (код + абзац + evidence-ref, R17-safe) и уже по ним решать, калибровка это или генерация.

## 5. Контекст/модель/обрезка — не причина

- `finish_reason` в журнале за 10-18…10-22: **0 строк**; `truncated=False` во всех `L1_COMPLETE`.
- `L1_CONTEXT_PACK`: `serialized_tokens` 3.5k–82k при `physical_budget=864549`, `overflow=0`, `skipped=0`.
- `L2_COMPLETE`: `tokens_in` 26k–43k, `tokens_out` 2.8k–3.4k, `chars` 3.9k–9.3k при `target_chars=6500` — обрезки нет.
- Все LLM-вызовы этих ранов `success`; таймаутов/5xx в деградации нет. Долгие, но в бюджете: L1 до 311 с, L2 до 225 с.
- Реальная проблема модели/промпта другого рода: `L1_CORRECTION_RETRY reason=bad_schema_version` практически в каждом ране (attempt 1 → attempt 2), плюс 4 рана с L1 map invalid (3 `unknown_field`, 1 `bad_type`) и 2 рана с L2 structural invalid (`unknown_field`). У `718e9ea6` первый ответ L1 — `raw_chars=123774` при `tokens_out=2752` (дегенеративная генерация). Это отдельный дефект стабильности L1-контракта, не «нехватка контекста».

## 6. Coverage=0 / FactView — что реально закрывает 2.58.112

- `FACT_VIEW_BUILT threads=0 fragments=0 unassigned=0` и `coverage=0.0, source_considered=0` — устойчивая сигнатура v1/v2-несовместимости (диагноз `summary-degraded-diag.md` подтверждается новыми ранами 10-20…10-22).
- Влияние на state: **не влияет**. Два рана с `coverage=0.0` и без fallback — `DONE` (`5187dee4`, `6707dc8d`), потому что `pipeline_health` в контексте был `ok`, а coverage в терминал не пересчитывался. Degraded-метка из-за coverage живёт в `pipeline_analytics.health_of` (`:1281-1283`), то есть в аналитике, а не в `summary_runs.state`.
- 2.58.112 (`10f3a2a0` поверх `138330c0`, Approved) закрывает: v2-материализацию FactView, fail-closed `not_built` вместо «ok с пустым пакетом», coverage-гвард, и честный терминал прерванного рана. **Не закрывает**: отвержение ревьюером, legacy-fallback, публикацию, orphan.

Итог по вкладу поезда: **0 из 21 DEGRADED и 0 из 5 FAILED меняют исход**; поезд убирает лживую метрику coverage, «ok при пустом пакете» и «ok при отмене» — это диагностическая ценность, не восстановление публикаций.

## 7. Embeddings — квоты штатные, данные не теряются

- `embedding_quota_state`: `primary`/`fallback_1`/`fallback_2` — `exhausted`, `note=parked kind=spend est=utc_day_end`, `next_allowed_at = 2026-10-23 00:05:00Z` (все три, `updated_at` 22.10 00:15Z); `unknown` — просроченная запись от 10-12 (легаси-группа, не переоценивается).
- Механика восстановления автоматическая и без вмешательства: `control_plane.group_blocked()` fail-open по истечении `next_allowed_at` (`embedding_control_plane.py:717-731`), `_ensure_job` переводит `paused_rate_limit → queued` при истёкшем cooldown (`graphrag_rebuild.py:1747+`), плюс `start_resume_ticker` с периодом `RESUME_TICK_SECONDS=900` (`graphrag_rebuild.py:109,468`). Тикер поднимается при каждом старте процесса — в журнале 18 строк `resume ticker started` с 10-20; отдельного лога на каждый 15-минутный тик нет, поэтому «живость» тикера — вывод из кода + факта, что paused-job ставился именно тикером (`EMBEDDING_GENERATION_PAUSED` 22.10 00:15Z).
- Ожидаемое время: **после 00:05Z 23.10**, повторная постановка job — в течение ≤15 минут очередного тика. Это штатный сценарий, не авария.
- Backlog: `graph_facts=20051`, `graph_facts_vec=16003` → **4048 фактов без векторов** (+8 новых фактов с прошлой проверки, векторов ровно столько же). В аудите 22.10 стояло 4162 при тех же 16003 векторах — разница в знаменателе (там считался eligibility-фильтр `expires_at`), сырая разница сейчас 4048. Факты сохраняются text-only (`EMBED_API_DEFERRED` ежедневно), архив пуст (`smart_archive=0`, `smart_archive_facts=0`).
- Ограничение, которое нельзя не назвать: поколения индексов (`graph_facts_vec g1`, `smart_archive g1`) с 29.09 в статусе `building`, `activated_at=NULL` — **активного live-индекса нет**. Даже когда квота вернётся, retrieval останется FTS до завершения P3-перестройки и активации поколения; 20k фактов за суточную квоту может не перестроиться, и цикл повторится.
- Потери данных нет: 4048 текстовых фактов доступны FTS, причина пропуска — `paused_rate_limit`.

## 8. Что требует кода (гипотезы с file:line)

| # | Область | Гипотеза | Приоритет |
|---|---|---|---|
| C1 | Summary publish | Рестарт сервиса во время рана гарантированно убивает публикацию: drain не видит in-flight ран (`[shutdown] summary drain done | in_flight=0` при живом ране). Кандидаты: `services/summary_scheduler.py:204` (`_tick` владеет раном, но не регистрирует его в drain), `services/summary_generator.py:689/927` | high (4/5 FAILED) |
| C2 | L2 review | Нет durable-следа находок: `summary_l2_review.py:867-880` (`_stage_event` с `finding_codes`) → `_record` только в `ctx.stage_events`; `SUMMARY_L2_REVIEW` почти не эмитится (2 события за всю историю) — сверить вызовы `pipeline_events.l2_review` (`summary_generator.py:2637`) | high (без этого калибровка невозможна) |
| C3 | L2 review | Ревизии не уменьшают blocking (`revision_fixed=0` 15/15, при 1 успешном кейсе). Проверить применение patch и повторный review по `current_doc` (`summary_l2_review.py:1230-1380`), а также `dropped_findings` (0–2 за ран) | high (качество) |
| C4 | FactView | v1/v2 (уже исправлено в `10f3a2a0`, не на проде) — при выкате проверить, что `FACT_VIEW_BUILT threads>0` и `quotes_verified>0` | medium (поезд) |
| C5 | L1 | `facts=0` во всех L1-завершениях + `bad_schema_version` ретрай почти всегда + 4 `unknown_field` — контракт L1-схемы/промпта нестабилен (`services/summary_l1_clusterizer.py`, `summary_l1_semantic_map.py`) | medium |
| C6 | Run lifecycle | Orphan-ран создаётся без окна и переживает владельца (`close_orphan_runs`, `summary_run_store.py:380+`); 1 случай 10-16, не повторялся | low |
| C7 | B11 report | Ложный зелёный `diagnose()` из-за регистра (`tools/v63_b11_mechanisms_report.py:662-666`) — уже в аудите, здесь только подтверждаю фактом `state='FAILED'` | low |

## 9. Что делать дальше

1. **Операционно (DevOps, без кода):** не рестартовать `admin_bot` в окне **0–20 минут после тика Summary** (19:00Z, 01:00Z, 07:00Z, 13:00Z). Все 4 «рестартных» FAILED — на +7…+14 мин; рестарты на +20…+26 мин ран не ломали. Перед рестартом — проверка отсутствия свежего `SUMMARY_RUN_START` без терминала.
2. **Поезд 2.58.112:** выпускать как договорено (он снимает лживые coverage/ok-при-пустом/ok-при-отмене), но **не ждать от него роста публикаций**: 21 DEGRADED и 5 FAILED он не закрывает. После выката первый тик (19:00Z) должен показать `coverage≈100` и `FACT_VIEW_BUILT threads>0` — это и есть проверка поезда.
3. **Отдельная задача Builder+Reviewer (C1–C3):** durable finding-коды, разбор «ревизия не чинит», регистрация рана в drain. Это единственный путь к тому, чтобы 21 DEGRADED перестали быть нормой.
4. **Embeddings:** ничего не делать до 00:05Z 23.10; после — проверить, что `paused_rate_limit → queued`, backlog начал убывать, и что поколение индекса активировалось (`activated_at` не NULL). Если после 00:30Z прогресса нет — это уже дефект resume.

## 10. Честные границы (что по этим данным доказать нельзя)

1. **Коды находок ревьюера** не сохраняются: нельзя назвать, какой именно из 13 hard-кодов сработал. Вывод «блокируют только фактические претензии» — из кода, а не из наблюдённых кодов.
2. **Тексты отклонённых L2-драфтов** не сохраняются → нельзя оценить, права ли претензия по конкретному абзацу. Поэтому «ревьюер слишком строгий» и «writer фактически ошибается» одинаково недоказуемы на текущих данных.
3. **Причинность «пустой пакет → rejected»** не доказана: 4/4 рана с материализованным пакетом тоже rejected. Связь `quotes_verified=0` с пустым пакетом — сильная корреляция, не эксперимент.
4. **2.58.112 на проде не проверен**: на момент снятия данных живёт 2.58.111, следующий прогон — 19:00Z 22.10. Утверждение «после фикса coverage станет 100» опирается на офлайн-replay из evidence фикса, а не на прод.
5. **`next_allowed_at` — обещание провайдера/парковки, а не факт**: что квота реально откроется в 00:05Z, проверить можно только после этого времени.
6. **Наблюдаемость публикации:** у «тихо умерших» ранов есть только `SUMMARY_PUBLISH outcome=start`, без терминального события — публикация не дошла до отправки. Это не потеря события, а отсутствие завершения; но отличить «не начали» от «начали и умерли» можно только по наличию `start`.
7. Персональные данные/секреты не выгружались: chat_id оставлен как есть (это id чата владельца, не персональные данные участников), тексты сообщений/промптов не читались.

## 11. Артефакты и воспроизводимость

| Файл | Что внутри |
|---|---|
| `raw/summary_probe.txt` | полный дамп: 28 ранов, 202 stage-строки, summary-события, квоты, индексы, vec-счётчики, journal-срезы, PG usage |
| `raw/failed_runs_probe.txt` | события 5 FAILED-ранов, `SUMMARY_TEXT_READY`, `SUMMARY_PUBLISH`-контекст |
| `raw/silent_death_probe.txt` | journal-окна 10-19/10-20 (обнаружен `Stopping` + `CancelledError`) |
| `raw/windows_probe.txt` | точные окна b61/cff, список рестартов 10-20…10-22 |
| `raw/b61_window.txt` | подтверждение рестарта 10-19 19:13:31 + traceback отмены в `generate_image_verbose` |
| `probe_summary.py`, `probe2_summary.py`, `probe3_summary.py`, `probe4_summary.py`, `probe5_summary.py` | скрипты чтения (paramiko, stdin-скрипт, scrub секретов) |
| `analyze.py` | локальная агрегация дампа (join runs × stages × run_done) |

Ключевые запросы (все — SELECT/read-only):

```sql
-- runs
SELECT run_id, chat_id, state, publication_status, pipeline_health, created_at, updated_at
FROM summary_runs ORDER BY created_at;

-- стадии по ранам
SELECT s.run_id, s.stage, s.status, s.attempt, s.reason_code, s.started_at, s.finished_at
FROM summary_run_stages s ORDER BY s.run_id, s.id;

-- исход L2 и покрытие (durable-события)
SELECT ts, event_name, status, reason_code, pipeline_run_id, usage_json
FROM mca_events
WHERE event_name IN ('SUMMARY_L2_STAGE','SUMMARY_L2_REVIEW','SUMMARY_LEGACY_FALLBACK')
  AND ts >= :w12d ORDER BY ts;

SELECT ts, status, usage_json FROM mca_events
WHERE event_name='SUMMARY_RUN_DONE' AND ts >= :w12d ORDER BY ts;
```

```bash
# PG (только SELECT): объём вызовов Summary
SELECT step, COUNT(*), SUM(input_tokens), SUM(output_tokens), MAX(output_tokens)
FROM llm_usage_events WHERE module='summary' AND ts >= now() - interval '10 days'
GROUP BY step;

# journal: точная причина FAILED-ранов
journalctl -u admin_bot --since "2026-10-19 19:13:15" --until "2026-10-19 19:14:10" --no-pager -o cat
journalctl -u admin_bot --since "2026-10-20 19:07:30" --until "2026-10-20 19:11:00" --no-pager -o cat
journalctl -u admin_bot --since "2026-10-18" --no-pager -o short-iso | grep -E 'Stopping admin_bot|Started admin_bot'
```

## 12. Итоговая классификация (для карт/приёмки)

| Класс | Кол-во | Вердикт |
|---|---|---|
| DEGRADED = L2 review rejected/unusable → legacy | 19 (15+4) | **Отдельный дефект** (качество L2 / evidence-alignment). Не закрывается 2.58.112 |
| DEGRADED = structural invalid L1/L2 → legacy | 2 | **Отдельный дефект** (стабильность L1-схемы). Не закрывается 2.58.112 |
| FAILED = рестарт сервиса в середине рана | 4 | **Отдельный дефект (C1) + операционное правило по деплою.** 2.58.112 даст только честный `interrupted` |
| FAILED = orphan | 1 | **Отдельный дефект** (жизненный цикл рана), не повторялся |
| coverage=0.0 при пустом FactView | 24 рана | **Исправлено поездом 2.58.112** (метрика + fail-closed пакета) |
| «published-ран, отменённый после публикации» (B-1) | **0** | Наблюдением не подтверждён; фикс остаётся страховкой |
| Embeddings quota / backlog 4048 | 1 класс | **Ожидаемое поведение** (парковка до 00:05Z, авто-resume ≤15 мин, данные целы) |
