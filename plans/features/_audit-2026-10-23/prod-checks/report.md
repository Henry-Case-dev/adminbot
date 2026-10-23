# Прод-проверки строк `READY_FOR_LIVE` (read-only) — 22.10.2026

Лейн: `DEVOPS-PROD-CHECKS`. Задача: только чтение на проде, без деплоя, рестартов и мутаций.
Карты, `workflow_state.md`, `plans/current_task.md` и код не менялись.

## 0. Контекст и метод

| Параметр | Значение |
|---|---|
| Прод | `198.46.175.136`, сервис `admin_bot` — `active`, NRestarts=0 |
| Версия (healthz) | `{"status":"ok","version":"2.58.111"}` |
| HEAD на сервере | `fbf9013d89b03e38473ce6824a460fdbb736fff8` (2.58.111), ветка `master`, worktree dirty=13 (до проверки) |
| Запуск процесса | `2026-10-22 13:14:31Z` (рестарт релизом 2.58.111) |
| Часы | сервер UTC `2026-10-22 16:05–16:16Z`; локальная зона исполнителя — `2026-10-23 04:0x +12:00` (расхождения нет, только смена суток) |
| SSH-коннектов | 4 (recon + 3 пакетных прогона, интервалы ≥45 с, логин один, без sudo-перебора) |
| Запись на проде | нет: SQLite открывался `mode=ro` + `PRAGMA query_only=ON`, PG — только `SELECT`, journalctl/healthz — чтение |

Сырые выгрузки (значения секретов и персональные алиасы вырезаны): `raw/recon.txt`, `raw/main.txt`,
`raw/main2.txt`, `raw/main3.txt`. Скрипты воспроизведения: `probe.py`, `probe2.py`, `probe3.py`.

БД: основное состояние — SQLite `local_database.db` (1.49 ГБ + WAL 4 МБ), настройки/профили — PG `adminbot`.

## 1. Сводная таблица вердиктов

| req_id | Вердикт | Источник (команда) | Выдержка | Причина отказа / комментарий |
|---|---|---|---|---|
| `REQ-B09-BODY` | **NOT_YET_OBSERVED** | `sqlite: SELECT * FROM chat_id_migrations` | `--- b09_chat_id_migrations (n=0) ---`, `b09_migrations_total = (0,)`; таблицы `chat_migration_backup` нет | Реальной миграции чата не было ни разу → пары old→new не существует. Память/конспект при этом на месте по чатам (см. §2) |
| `SOUL-14.2` | **FAIL** (частично) | `sqlite: mca_events WHERE event_name='speech_extent'`; `journalctl -u admin_bot` | 45 событий: compact 27, micro 14, normal 4; `status pass 41 / conflict 4`; `one_word` — **0**; `core_tokens=` — **0 строк/7д** | Распределение extent пишется (PASS), но `one_word`-совпадений нет вовсе (NOT_YET_OBSERVED), «фактическое число injected C» в телеметрии отсутствует (not instrumented), доля фактических/адресных ошибок несчитаема (6 feedback-строк/30д, сигналы `null`/`unknown`) |
| `B10-R06` | **FAIL** | `sqlite+vec0: counts/backlog`; `task_jobs`, `embedding_quota_state` | `graph_facts=20043`, `graph_facts_vec=16003`, `backlog_graph=4162`; generations обе `status=building`, `activated_at=NULL`; quota `primary/fallback_1/fallback_2 = exhausted, next_allowed_at=2026-10-23 00:05Z` | Живого вектора нет: поколения не активированы с 29.09, 4162 факта без эмбеддингов, backfill стоит `paused_rate_limit` с 22.10 00:15Z. Rate-limit/failover-механика работает, но ёмкости групп нет |
| `B10-R10` | **NOT_YET_OBSERVED** (+proxy PASS) | `sqlite: chat_id_migrations`, `mca_events WHERE event_name='mca07_retrieval'` | миграций 0; retrieval 30д: 585 + 72 + 7 + 6 + 1 success по своим chat_id, 1 `retrieval_empty`; чужих chat_id в выдаче не видно | Переноса supergroup не было — проверять «old→new retrieval» не на чем. Изоляция по чатам косвенно подтверждена |
| `B10-R11` | **PASS** (с оговоркой) | `PG llm_usage_events`, `journalctl` (L1_PLAN, TOOL_*) | 408 usage-строк L1/7д (404 прогона, 358 с `plan_meta`), `execution_mode="none"`, `credential_source="global"`; `DIRECT_FRESH_GENERATION 350/7д`; TOOL: start 16 / complete 13 / failed 3 | Режимы, бюджет и инструменты реально наблюдаются. Оговорки: `L1_PLAN` пишется только в журнал/PG `plan_meta` (в `mca_events` 0 строк); запрет «без ключа» подтверждён кодом, живого срабатывания нет (0/30д) |
| `REQ-B11-E2E` | **FAIL** | `tools/v63_b11_mechanisms_report.py --db local_database.db` | `8 ok / 2 never_run`; Summary — «ok» при `status=FAILED, publication=failed, health=degraded` | Инструмент различает `never_run` (graph memory, embeddings — не зелёные), но **красит в ok провалившуюся попытку Summary**: сравнивает `status in ("error","failed")` с `summary_runs.state='FAILED'` (регистр). Плюс фактическая причина graph/embeddings точнее, чем `never_run` — квота |
| `U07-SYM-DESKTOP`, `REQ-U07-3`, `U07.3c` | **NOT_CHECKABLE (owner device)** | — | — | Требуется реальный Telegram Desktop на Windows / Android-клиент. Агентских read-only доказательств не существует; повторная ручная проверка владельцу не навязывается (PET_PROJECT) |

Итог по пунктам: **PASS 1, FAIL 3, NOT_YET_OBSERVED 2, NOT_CHECKABLE 3**.

## 2. REQ-B09-BODY — миграция профилей/ролей Summary и Memory

- `chat_id_migrations`: 0 строк за всё время. Таблицы `chat_migration_backup` в БД нет → ни один перенос не запускался.
- Носители памяти по чатам (SQLite, `GROUP BY chat_id`) — данные не потеряны и не «свалились» в один chat_id:

```
smart_messages: -1002661910336 = 2 032 115 | -1004482340693 = 3 980 | 5885953495 = 191 | ...
graph_facts:    -1002661910336 = 19 110    | -1004482340693 = 666   | 5885953495 = 259 | ...
nodes:          -1002661910336 = 24 642    | -1004482340693 = 845   | ...
edges:          -1002661910336 = 44 040    | -1004482340693 = 599   | ...
chat_running_summary: -1002661910336 = 1 (window_end 2026-09-06 13:00Z, raw_count=500, expires_at 2026-09-06 14:01Z)
```

- PG: `chat_profiles` — 3 чата (`-1002661910336`, `-1004482340693`, `5885953495`), у каждого полный набор секций
  `v/keys/meta/gates/overrides/perm_overrides`; `chat_admins` — только у `-1002661910336` (1); роли (`bot_admins`/`bot_roles`) глобальные, не по чатам.
- `chat_summary_levels` пуста (0 строк), а единственная `chat_running_summary` просрочена (окно до 06.09.2026, `expires_at` там же) — наблюдение для проверки контракта: уровневая/скользящая сводка в БД не обновляется, при этом `summary_runs` публикуются.
- **Вывод:** состояние «память есть, миграции не было» — честный `NOT_YET_OBSERVED`. Проверка переноса возможна только на реальном `migrate_to_chat_id` в Telegram.

## 3. SOUL-14.2 — телеметрия речи

| Метрика строки | Наблюдение | Вердикт |
|---|---|---|
| распределение extent | 45 событий `speech_extent` (21.10 15:11Z – 22.10 15:13Z): compact 27, micro 14, normal 4; `context`: regular 36 / initiative 9 | **PASS** |
| exact `one_word` compliance | `extent='one_word'` — 0 событий за 30 дней; `words` по one_word отсутствует | **NOT_YET_OBSERVED** |
| фактические/адресные ошибки | контур `mca_experience_feedback`: 6 строк/30д (4 `participant_correction` verified, 2 `social_reaction` weak), сигналы `domain=null`(4) и `humor/unknown`(2) | **н/д** (выборка непригодна) |
| повторяемость | 41 из 69 `style_policy`-событий за 30д содержат непустой `repetition` | **PASS** (метрика есть) |
| фактические ошибки доставки | `payload_status="mismatch"` — 11 событий/30д (`quotation_marks.hard.no_graphic`) | наблюдение (реальный дефект стиля, не 14.2) |
| фактическое число injected C | 0 строк `core_tokens=` за 7д; событие `prompt_layers` несёт только `status/reason` (код: `prompt_composer.py:1921-1924`), `core_tokens=` пишется лишь при конфликте бюджета (`:1236`) | **FAIL (not instrumented)** |

Пример payload (без текста ответа): `{"extent": "micro", "status": "pass", "one_word": 0, "one_word_exact": 0, "context": "regular", "words": 12, "reason": "micro_soft_exceeded"}`.
Исходы: `success 41 / failed 4` (`speech_extent`); причины `micro_soft_exceeded 9`, `micro_extent_exceeded 4`.

Честный вывод: extent-часть живой телеметрии работает, но строка требует ещё и one_word-совпадения и injected C — этих данных в проде нет, поэтому `FAIL` (а не «работает»).

## 4. B10-R06 — embeddings quota-groups, backfill/recovery

- Размер индекса и backlog (с загруженным `vec0.so`, readonly):
  `graph_facts = 20 043`, `graph_facts_vec = 16 003` → **backlog = 4 162**; `smart_archive = 0`, `smart_archive_facts` пуста → backlog архива 0.
- Поколения индексов: `smart_archive g1` и `graph_facts_vec g1` — `status=building`, `created_at=2026-09-29 10:39Z`, `activated_at=NULL` → **ни одного активированного live-индекса**.
- Квоты (`embedding_quota_state`): `primary`, `fallback_1`, `fallback_2` — `state=exhausted`, `note="parked kind=spend est=utc_day_end"`, `next_allowed_at=2026-10-23 00:05Z`; `unknown` — `exhausted`, запись от 2026-10-12 00:05Z, `next_allowed_at=2026-10-13 00:05Z` (уже в прошлом, состояние не переоценено).
- Job: `graphrag_rebuild` (`owner=memory`) — `paused_rate_limit`, `reason_code=rate_limit:quota_group`, `updated_at=2026-10-22 00:15:06Z`, payload-курсор `{"last_id": 11953, "processed": 9797}` (отстаёт от 16 003 уже вложенных строк → курсор старого прогона, не «живой прогресс»).
- События: `EMBEDDING_GENERATION_PAUSED` 592 (последнее 22.10 00:15Z), `EMBEDDING_GENERATION_FAILED` 50 (38 `knn_source_empty`, 12 без причины; последнее 06.10 23:28Z).
  `EMBED_API_DEFERRED`: 40 (22.10), 17 (21.10), 50 (20.10), 118 (19.10) и т.д. — факты сохраняются text-only.
- Следствие в рантайме: `SmartModule: embedding generation not serviceable … FTS-only (A06)` каждые ~10 мин; `mca07_retrieval` 30д: **2347 skipped `embedding_generation_changed`** (фоновые тики), при этом пользовательские retrieval на обоих чатах успешны (FTS).
- Rate-limit/failover-поведение само по себе корректно (парковка до конца UTC-суток, перебор primary→fallback_1→fallback_2), но все группы исчерпаны → recovery не идёт 16+ часов.

**Диагноз:** не «producer выключен» и не «worker упал» — вход есть (250 свежих фактов/24ч), воркер жив, но квота провайдера исчерпана; индекс не активирован, backlog растёт. Для строки, требующей работающего live-индекса, это `FAIL`.

## 5. B10-R10 — supergroup, включая память

- `chat_id_migrations` пуста → цепочки `old→new` нет, поэтому резолв канонического chat_id тривиален (сам чат); проверять «старый id отдаёт память нового» не на чем.
- Косвенная проверка изоляции (30д): retrieval идёт строго по chat_id запроса —
  `-1002661910336`: 585 success (+7 `episodes_used`, +6 `exact_match_used`), `-1004482340693`: 72 success, `1313107079`: 1; один `silent/retrieval_empty` (18.10).
- Факты и узлы GraphRAG разложены по чатам (см. §2), строк с чужим `chat_id` в выдаче не обнаружено.
- **Вывод:** сам сценарий переноса supergroup проверить нельзя — `NOT_YET_OBSERVED`; изоляция по чатам — `PASS (proxy)`.

## 6. B10-R11 — Direct L1: auth/budget/execution modes/tools

- Фактические режимы (PG `llm_usage_events`, 7д, `module=direct_chat, step=l1_planner`): 408 вызовов / 404 прогона, 358 с `plan_meta`; 548 739 input + 45 104 output токенов.
  Пример `plan_meta`: `{"tone":"playful","action":"reply","bucket":"medium","extent":"micro","source":"main","inherited":true,"confidence":0.6,"latency_ms":1899,"input_chars":1559,"response_act":"banter","execution_mode":"none","credential_source":"global"}`.
  `execution_mode="none"` в наблюдаемых планах — спец-режимы на обычных репликах не запрашивались; `latency_ms` 1.3–3.3 с.
- Бюджет/ключи: `credential_source="global"`, учёт usage идёт (строки с токенами); маркеры L1 в журнале — 157 строк/7д (включая конфиг-строки), во всех наблюдаемых планах `inherited=True`, `source=main`, `fallback=` пусто; ошибок лестницы (`l1 dedicated/ladder`) — 0.
- Запрет работы без ключа: путь `authorize_l1_call` → `NoApiKeyForChat` → `_sandbox_no_key_reply` (LLM не вызывается, лог «no key — sandbox answer»), `direct_chat_service.py:4244-4247, 4351+`. Живых срабатываний 0/30д (ключ есть) — негативный путь проверен только по коду, не в проде.
- Инструменты: журнал 7д — `TOOL_CALL_START 16`, `TOOL_CALL_COMPLETE 13`, `TOOL_CALL_FAILED 3`; примеры: `recognize_image` (ok, out_chars 56/161), `execute_web_search` (ok, 4053), `get_recent_history` (ok), `fact_check` (`denied`, `no_claim_after_context`). PG: `generate_image` — 106 вызовов/7д.
- Оговорка: `L1_PLAN` через `mca_events` **не пишется** (`emit_l1_plan_event` → `agentic_events`), в таблице 0 строк; табличная агрегация L1 невозможна, только журнал + PG `plan_meta`.

**Вывод: PASS** для «режимы/бюджет/инструменты наблюдаются, работа без ключа заблокирована контрактом», с явной оговоркой про отсутствие живого негативного прогона.

## 7. REQ-B11-E2E — «включено, но не запускалось»

Прогон `tools/v63_b11_mechanisms_report.py` на проде (16:07–16:09Z): `8 ok / 2 never_run`, `not_green_rule` соблюдён для graph memory и embeddings. Уточнения по фактам:

| Механизм | Диагноз инструмента | Фактическая причина по данным |
|---|---|---|
| Graph memory (GraphRAG) | `never_run` | индекс `building`, job `paused_rate_limit` с 22.10 00:15Z, курсор 9797/20043 → не «нет попыток», а **остановка по квоте** |
| Инкрементальный embedding/backfill | `never_run` | то же: квота групп исчерпана до 23.10 00:05Z, `EMBED_API_DEFERRED` ежедневно |
| Summary scheduler | **`ok` — неверно** | последний run `FAILED` (`publication=failed`, `health=degraded`), причина — `CancelledError` при shutdown 13:14:20Z в `_maybe_apply_cover_style`; 21/28 ранов `DEGRADED` с `l2_review_rejected`/`l2_review_unusable` → `LEGACY_FALLBACK` |
| dream / deep sleep / belief revision / paradigms / self-model / experience / initiative | `ok` | подтверждено свежими попытками и записями (напр. initiative: 283 completed/24ч; experience: 36 свежих входов, 1 review) |

Причина ложного зелёного: `diagnose()` сравнивает `status in ("error","failed")`, а `summary_runs.state` — `FAILED` в верхнем регистре (`tools/v63_b11_mechanisms_report.py:662-666, 1163-1169`).
Дополнительно: ось backlog в этом инструменте в проде всегда `null` — процесс не грузит `sqlite_vec`, поэтому `backlog_missing_embedding` не считается (я получил 4162 отдельным прогоном с `vec0.so`).

**Вывод: FAIL** — инструмент, который является доказательной базой строки, выдаёт зелёный статус при провалившейся последней попытке и не измеряет backlog на проде.

## 8. Что осталось непроверяемым (и почему)

1. `REQ-B09-BODY` / `B10-R10` — нужен реальный перенос чата в Telegram (`migrate_to_chat_id`). Пока его не было, доказать old→new перенос невозможно; имитировать миграцию на проде запрещено (мутация).
2. `SOUL-14.2` — `one_word`: нужен реальный запрос, вызывающий extent `one_word` (сейчас 0 за 30 дней); injected C: метрики в коде нет (пишется только конфликт бюджета) → требует изменения кода Builder'ом, не наблюдения.
3. `SOUL-14.2` — доля фактических/адресных ошибок: 6 feedback-строк/30д, сигналы не классифицированы; статистически непригодно.
4. `U07-SYM-DESKTOP`, `REQ-U07-3`, `U07.3c` — Windows Telegram Desktop / реальный клиент: только владелец, и по PET_PROJECT это необязательное наблюдение, а не блокер.
5. `B10-R11` — негативный путь «без ключа» нельзя воспроизвести без изъятия ключа (запрещённая мутация).

## 9. Инциденты и аномалии (вне scope правок, к решению Builder/Reviewer)

| # | Severity | Область | Наблюдение | Риск |
|---|---|---|---|---|
| A1 | **high** | embeddings/память | Все quota-groups `exhausted` до 23.10 00:05Z; live-индекс не активирован с 29.09; backlog 4162; факты пишутся text-only; retrieval FTS-only | Память теряет векторный поиск; разрыв будет расти, пока квота не восстановится |
| A2 | medium | Summary | 28 ранов: DONE 2, DEGRADED 21, FAILED 5; `l2_review_rejected`/`unusable` → legacy-fallback; последний FAILED — из-за shutdown при релизе 13:14:20Z | Конспекты выходят «деградированными» почти всегда; релизный рестарт рвёт публикацию |
| A3 | medium | диагностика B11 | `diagnose()` не распознаёт `FAILED` (регистр) → ложный `ok` у Summary | Доказательная база строки E2E завышает зелёный статус |
| A4 | medium | SQLite/стабильность | 22.10 06:20:30–06:20:33Z серия `database: connection unrecoverable` (aiosqlite `no active connection` + `CancelledError`, `op=save_smart_message_identity`, `b01_observe_checkpoint`), далее новый процесс с 06:21:10Z (PID 434185); `database is locked` — 0 | Потеря части операций записи в окне; причина по логам не установлена (диск/отмена задач?) |
| A5 | low | watchdog | 4 незакрытых инцидента `worker_lost` (summary `cov_2869…`, vision, memory `7ed322…`, asap8b01 `13c734…`), `resolved_at=NULL` | Шум/скрытые зависшие задачи |
| A6 | low | наблюдаемость L1 | `L1_PLAN` только в журнале и PG `plan_meta`; в `mca_events` 0 строк | Нет табличной агрегации L1 (24ч/7д) |
| A7 | low | summary-уровни | `chat_summary_levels` пуста; `chat_running_summary` — 1 строка, окно и `expires_at` от 06.09.2026 (просрочена) | Скользящий/уровневый конспект в БД не обновляется — проверить контракт с `summary_runs` |
| A8 | info | релиз | Прод HEAD `fbf9013d` = 2.58.111; worktree dirty=13 (до проверки) | Не влияет на чтение, но фиксировать при следующем деплое |

## 10. Ограничения честности

- Вердикты `NOT_YET_OBSERVED` и `NOT_CHECKABLE` не являются «зелёными»: строки карт по ним закрывать нельзя без реального события/владельца.
- `FAIL` по `SOUL-14.2`, `B10-R06`, `REQ-B11-E2E` — это наблюдаемое состояние прода на 22.10.2026 16:16Z, а не оценка кода: кодовая часть по этим строкам могла быть корректной, но требуемое живое поведение не подтверждено.
- Секреты и персональные алиасы в выгрузках вырезаны; DSN/ключи не печатались.
