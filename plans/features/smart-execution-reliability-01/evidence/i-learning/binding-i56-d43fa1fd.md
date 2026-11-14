# Binding — I5/I6/I7 (S10-LEARNING-INCIDENTS остаток, S11-MEMORY-CORRECTION)

Эпик `SMART-EXECUTION-RELIABILITY-01`; срезы `S10-LEARNING-INCIDENTS`
(остаток I5) и `S11-MEMORY-CORRECTION` (I6/I7). База —
`d20a7f730715ba9e9cba7673c0557794979be339` (production 2.58.199).
Ветка `smart/i56-memory-learning`, worktree
`WorkspaceData/worktrees/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b-6fe59a2f`.
Деплой не выполнялся, production не изменялся, DDL/миграций нет.

* CODE_SHA: **`d43fa1fd17aebd03f94654b0476483c2c68f5e8c`**
  (`services/summary_memory.py`, `services/direct_chat_service.py`).
* TEST_SHA: **`58a8f859c39526137f97d4956f327690ba1ea1be`**
  (`tests/test_smart_exec_memory_scope.py`,
  `tests/test_smart_exec_learning_incidents.py`,
  `tests/test_asap8_v6_d06_isolation.py`).
* Требования: `SXR-I5-01`, `SXR-I6-01`, `SXR-I6-02`, `SXR-I7-01`
  (`live_required=false`, `live_when=preprod`).

## 1. SXR-I6-01 — структурная изоляция KNN по chat scope

### 1.1. Воспроизведение прод-симптома

Прод-лог владельца: `graphRAG int8: chat-scope KNN partial`, `own=3/16`,
`own=5/30`, `k_last=512`, `filtered_other_chat=509`. Причина в коде:
`_staged_knn_scope` делал **глобальный** KNN и фильтровал `chat_id` в
Python; при перекосе корпуса чужие чаты занимали все k до cap=512, свой чат
получал partial (`services/summary_memory.py`, историческая ветка; лог
`_log_knn_scope`).

Воспроизведено на **реальной** локальной prod-like БД
`local_database_2026-09-04_history.db` (10 619 vec-строк, dim 3072, один
доминирующий чат): глобальный KNN `k=512` для чата `5885953495` дал
`own=9/10` (partial), для чата `1313107079` — `own=0/10` (partial) — ровно
класс прод-лога (`probe-real-knn-bench.txt`).

### 1.2. Проверка возможностей sqlite-vec 0.1.9 (deployed-линия D06)

* auxiliary `+chat_id` в WHERE KNN — `OperationalError: illegal WHERE
  constraint ... auxiliary column` (как и в D06);
* `partition key` поддерживается, **но** требует DROP/recreate vec-таблиц и
  backfill — это DDL-миграция, запрещённая границами среза;
* `rowid IN (SELECT id FROM <источник> WHERE chat_id = ?)` **работает**
  внутри KNN (float и int8), без DDL, переиндексации и новых таблиц; rowid
  vec-строки == `id` факта по инварианту INSERT
  (`_insert_graph_vec_row` / `_save_archive_embedding`).

Probe: `probe-knn-rowid-2026-11-14.txt`, `probe_vec0_rowid.py`,
`probe_vec0_partition.py`.

### 1.3. Исправление

`services/summary_memory.py`:

* новый helper `_chat_scope_rowid_clause(source_table)` — SQL-фрагмент
  `AND rowid IN (SELECT id FROM ... WHERE chat_id = ?)`;
* применён в трёх KNN-путях: `_search_archive_knn_scoped`
  (`smart_archive_facts`, float+int8), `_vec_candidates`
  (`graph_facts`, float+int8), `_dedup_knn` (`graph_facts`);
* `_staged_knn_scope` больше не используется для вытеснения чужими чатами:
  rowid-scope стоит **до** top-K; staged добор оставлен только для
  post-KNN фильтров своего чата (TTL/origin) — cap `_KNN_SCOPE_K_CAP=512` и
  множитель `×4` **не менялись**;
* телеметрия: `tele["scope"]="rowid"`, `filtered_other_chat` теперь 0;
  partial WARNING переформулирован (недобор своего чата, а не «чужие
  заполнили K»).

Инварианты: существующие эмбеддинги/corpus не тронуты; полного
переиндексации нет; искусственных квот по годам нет; retrieval-семантика
FTS/ранжирования не менялась.

### 1.4. Производительность (реальная локальная БД, 10.6k×3072)

`probe-real-knn-bench.txt` (лучшее из 3):

| Запрос | Время |
|---|---|
| глобальный KNN `k=512` | ~103.6 ms |
| scoped малый чат `k=20` | ~77.0 ms |
| scoped большой чат `k=20` | ~98.8 ms |
| scoped большой чат `k=40` | ~96.4 ms |

Структурный scope не медленнее прежнего overfetch и снимает starvation.

### 1.5. Пересечение с VMQ/ONTO и memory-эпиками

Структурного chat-scope исправления в VMQ-эпике нет. VMQ подтвердил лишь
SQL-возможность «KNN-подзапрос + JOIN по rowid с фильтром источника» для
периодной ноги (`plans/features/vmq-onto-01/evidence/vmq-mem/old-period-semantic-recheck.md`,
`vmq-onto-01/requirements-map.json:10712-10791`) и явно оставил chat-scope
следующей ступени памяти. D06-отчёт называет тот же остаток и partition-key
DDL как отдельную опцию (`plans/features/asap8-v6-remediation/d06-report.md:93-98,113-120`).
Наше исправление — не дубль VMQ, а закрытие остатка D06 без DDL; связь
зафиксирована здесь.

## 2. SXR-I6-02 — обрезка correction claim до 800

Причина: `_CORRECTION_OWN_TEXT_CAP = 800` в
`services/direct_chat_service.py` (константа «паритет с Current_Question»);
`_build_correction_frame` безусловно резал `claim_text`/`quote_text` и
логировал `direct: correction frame {claim|quote} truncated | chars=2981 -> 800`.

Исправление: константа и срез удалены; в `_render_correction_frame`
передаётся **полный** текст утверждения и цитаты (XML-эскейп сохранён).
Никакого нового символьного cap нет: упаковка по реальному контекстному
окну остаётся в существующем composer. Тесты:
`test_long_own_claim_is_not_truncated` (2981 символов, хвост за 800-м
присутствует, warning отсутствует), `test_long_quote_is_not_truncated`.
Прод-лог `chars=2981 -> 800` после выката исчезает (строка удалена).

## 3. SXR-I7-01 — `style_policy success` с удалением точки

Проверено как **штатное** поведение, без изменений кода/настроек:
`trailing_period.hard.strip` — правило активной речевой настройки
(`services/style_policy.py`, `PRESET no_trailing_period`); успешный проход
даёт `STATUS_REPAIRED`, `style_event_payload → status="success"`,
`repaired=1`. Политика речи, кавычки, мат, пользовательские настройки не
менялись (`services/style_policy.py` и speech-настройки вне diff).

Тест `test_trailing_period_removal_is_success_not_defect`: текст теряет
только конечную точку, событие success, `repaired=1`, записей
настроек/политики нет.

## 4. SXR-I5-01 — причины инцидентов `asap8b01`/`qnd.event`

Полный разбор: `evidence/i-learning/incidents-asap8b01-qnd-event-2026-11-14.md`.

Кратко: оба owner'а — job'ы инициативы (`initiative.observe` = `asap8b01`,
`initiative.event` = `qnd.event`); инциденты — законный watchdog-takeover
(`worker_lost`, stage=takeover, ERROR) прерванных рестартом 2.58.192
(2026-11-11T19:05:11Z) пайплайнов (`p0-init-meme-ux-diag/release-258192/...`).
Detector не ошибся; severity не занижена; инциденты не закрываются
(`acknowledged ≠ resolved`). Уже отражено в эпиках `p0-init-meme-ux-diag`,
`release-then-migrate` (stale-строки до cutover), `samples-ux`/
`p0-vision-universal` (тот же restart-artifact паттерн).

Подтверждённый смежный дефект (вне write scope): heartbeat инициативных
job'ов обновляется один раз на старте (`services/initiative_observer.py:1958-1965`,
`services/task_supervisor.py:459-483`) при пороге stale 60 c
(`services/mca_gates.py:1351-1353`) → возможно ложное `worker_lost` даже без
рестарта; исправление — в `TaskSupervisor`/`initiative_observer`
(периодический heartbeat, shutdown-маркировка). Передать в существующую
задачу `SELF-DIAG-01` (этап H консолидирован в этот эпик) / линию MCA
observability `mca-17a`; PM — в `plans/backlog.md`. BACKLOG_ONLY также:
повторный update незакрытого инцидента эмитит `incident_opened`
(отдельного `incident_updated` в реестре нет) — наблюдение, не блокер.

## 5. RED → GREEN и mutation-proof

| Прогон | База `d20a7f73` | Кандидат |
|---|---|---|
| `pytest tests/test_smart_exec_memory_scope.py` (I6/I7, 8 тестов) | **7 failed, 1 passed** (зелёный — I7-верификация, её и не меняли) | **8 passed** |
| `pytest tests/test_smart_exec_memory_scope.py tests/test_asap8_v6_d06_isolation.py tests/test_smart_exec_learning_incidents.py` | — | **19 passed** |
| Регрессия: correction/summary/graphrag/migration/mod-acl/style/mca17a/mca17c/maintenance | — | **479 passed, 1 warning** |
| Mutation A: `_chat_scope_rowid_clause → "AND 1 = 1"` | — | **5 failed** (все ChatScope-тесты) |
| Mutation B: вернуть `[:800]` в correction frame | — | **2 failed** (оба long-text теста) |
| Mutation C (I5): severity принудительно `WARN` в `open_or_update` | — | **1 failed, 1 passed** |

RED-лог: `evidence/i-memory/red-base-d20a7f73.txt`; mutation-логи рядом.
Pre-existing (не связаны с кандидатом, воспроизводятся на базе):
`tests/test_summary_generator.py::TestEpic60RunningSummary::test_below_ratio_no_trigger`
и `...test_expired_summary_stays_then_retriggers_on_new_messages`
(идентично 2 failed на базе в изоляции). `test_dream_worker` в большом
батче — order-флак: в изоляции и в сокращённом наборе passes; к диффу не
относится.

## 6. Файлы и границы

Изменены: `services/summary_memory.py` (+KNN scope), два новых теста,
`services/direct_chat_service.py` (снятие cap).

**Расширение write scope (осознанное, минимальное):**
`tests/test_asap8_v6_d06_isolation.py` не входит в исходный список, но три
его теста кодировали ровно тот промежуточный staged-overfetch контракт
(`partial`/`filtered_other_chat`), который владелец заменил структурной
изоляцией (SXR-I6-01). Без правки suite красный; изменены только
утверждения о механизме (scope/telemetry), U13-инварианты и негативные
случаи сохранены. Прочие файлы не трогались; схемы/миграции/каталог
настроек/фичефлаги — без изменений.

## 7. Effective configuration

* KNN-путь: `flags.vec_int8_enabled` / `settings.VEC_INT8_ENABLED` и
  per-chat `flags.memory_search_enabled` (`mca_gates.memory_search_enabled`)
  не менялись; тесты покрывают float **и** int8 ветки (форсированный probe
  в MemoryManager, как в D06). Отдельного нового флага нет.
* Style policy: `SPEECH_STYLE_POLICY_ENABLED` (env) +
  `flags.speech_style_policy_enabled`; тест I7 включает её штатно; выкат не
  требуется, поведение не менялось.
* Incidents/watchdog: `MCA_INCIDENTS_ENABLED`, `MCA_HEARTBEAT_WATCHDOG_ENABLED`
  env-only default ON; тесты на default; прод 2.58.192 фактически эмитил
  INCIDENT ⇒ effective ON. Значения `MCA_JOB_STALE_SECONDS` в прод-окружении
  не снимались (recon их не фиксировал) — для I5 это не требуется, но
  отмечено в §4.

## 8. Остаточное (postdeploy / preprod, не блокирует REVIEW)

1. Подтвердить на deployed-окружении версию sqlite-vec (локально и в
   D06-линии — 0.1.9; `requirements.txt` допускает `>=0.1.2`). При
   отсутствии `rowid IN` внешние обработчики деградируют в FTS
   (`vector search failed — FTS5 fallback`); это надо увидеть в логах, а не
   предполагать.
2. После первого выката: в логах L3/RAG не должно быть
   `chat-scope KNN partial ... filtered_other_chat>0` из-за чужих чатов;
   строки overfetch/partial содержат `scope=rowid`. Проверить реальный
   retrieval малого чата (свои факты, не partial) и латентность на прод-БД.
3. I5: после выката рестарт снова даст ожидаемые ERROR `worker_lost`
   takeover-инциденты (детектор не менялся). Существующие строки
   `asap8b01`/`qnd.event` остаются незакрытыми до `resolve` с evidence —
   искусственно не закрывать.
4. F-I5-1 (heartbeat длинных job'ов) и duplicate `incident_opened` — вне
   кандидата (см. §4), переданы PM/Orchestrator.

## 9. Housekeeping

Пробные прогоны и mutation-копии: `WorkspaceData/runs/74a29db0597e9311/.../probe-3f984fefaf/`
(`red-base-d20a7f73.txt`, mutation-логи, probe-скрипты); durable-копии
перенесены в `evidence/i-memory/` и `evidence/i-learning/`, run-каталог
закрывается после сдачи. Production не использовался (ни SSH, ни записи).
