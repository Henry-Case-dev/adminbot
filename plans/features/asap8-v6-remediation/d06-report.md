# D06 — Chat isolation в vector retrieval/dedup (ASAP 8 v6, Wave B, P0)

Lane D06 · HEAD base 6230fde · дата 14.10.2026 · writer-лейн, без коммита.

## Контракт

v6 §C D06 + v5 §9A.3/§9A.5/§18F.4/U13: chat-scope **до** effective nearest/top-K/rank/dedup,
не «глобальный top-K → потом фильтр». Если индекс не умеет фильтр в KNN — proven staged
overfetch (×4-добор + per-chat гарантия + честная деградация). §18F.4: «simple larger global
K is not a complete fix» — поэтому добор стадийный, с телеметрией и различением
«в чате мало фактов» vs «чужие заняли K».

## Root cause (подтверждён кодом, ledger-d)

`chat_id` в vec0-таблицах — auxiliary-колонка (`+chat_id`). sqlite-vec 0.1.9 (версия в
`.venv`, probe-скрипт): фильтр auxiliary-колонки внутри KNN-запроса запрещён —
`OperationalError: An illegal WHERE constraint was provided on a vec0 auxiliary column in a
KNN query`. Отсюда механизм «глобальный KNN → Python-фильтр chat_id»:

1. `_search_archive_knn` — float-путь брал `k = limit` **ровно** → чужие чаты занимали весь
   лимит → false-empty своего чата; int8-путь `k = limit×4` — тот же класс риска.
2. `_dedup_knn` — `k = 3` глобально → 3 чужих кандидата скрывали реальный дубликат своего
   чата (решение add вместо noop/supersede).

## Изменения

Файл: `services/summary_memory.py` (только retrieval/dedup-участки; public-сигнатуры
`vector_search`, `_search_archive_knn`, `_dedup_knn` не менялись — потребители
`summary_generator.py`/`tool_router.py`/`memory_maintenance.py` не затронуты).

- Константы `_KNN_SCOPE_OVERFETCH_MULT=4`, `_KNN_SCOPE_K_CAP=512`, `_DEDUP_KNN_WANT=3`,
  `_DEDUP_KNN_CAP=192` + канон-комментарий стратегии.
- `MemoryManager._staged_knn_scope(run_knn, k_first, k_cap, want, keep)` — стадийный добор:
  k растёт ×4 от k_first (кламп в cap), пока keep-строк < want и индекс не исчерпан; каждая
  попытка — полный top-k скан (надмножество), ответ строится по последней. Телеметрия:
  `attempts, k_last, own, want, overfetch_used (attempts>1), filtered_other_chat, exhausted,
  partial` (`partial` = своего < want при не исчерпанном индексе — чужие заняли K до cap).
- `MemoryManager._log_knn_scope` — R17 (только id/числа): partial → WARNING, добор → INFO,
  здоровый первый-проб не логируется (нет спама hot-path).
- `_search_archive_knn_scoped` (новый, возвращает `(facts, tele)`) + `_search_archive_knn`
  = thin-wrapper (обратная совместимость с существующими тестами/моками). Оба пути:
  int8-KNN (стадийно → реранк float → top-limit) и float-MATCH (стадийно → top-limit);
  фолбэк int8→float сохранён.
- `_dedup_knn` — кандидаты только своего чата (chat_id + TTL-liveness в `keep`), стадийный
  добор до 3 своих живых кандидатов либо исчерпания; семантика 64.1 (без origin/status-
  фильтров, порядок дистанции, колонки row) сохранена.

## Тесты

`tests/test_asap8_v6_d06_isolation.py` — 9 тестов на реальной SQLite+sqlite-vec фикстуре
(`DatabaseService(":memory:")` + `MemoryManager.initialize()`; float/int8 DDL фиксируются
патчем `_probe_vec_int8` до initialize — флаг после не переключается: vec0 int8-колонка
NOT NULL). Фоновые backfill'ы initialize гасятся (детерминизм сидирования). R17: только
синтетические векторы/факты.

`TEST-LIFECYCLE: CONTRACT owner=D06 (v6 remediation §C)`

| Тест | Покрывает |
|---|---|
| float_path_foreign_chat_cannot_displace_own | U13: 6 чужих фактов ближе своих + limit 5 → только свои (RED на старом k=limit); симметрия A↔B; публичный `vector_search` |
| int8_path_foreign_chat_cannot_displace_own | то же через int8-KNN + реранк |
| small_chat_exhausted_is_not_partial | исчерпание индекса — честное «мало фактов», НЕ partial |
| overfetch_cap_marks_partial_not_silent | чужих больше cap: частичный результат (1 из 2) ПОМЕЧЕН (partial=True, WARNING), не пустой молча |
| staged_refill_recovers_own_facts | attempts 8→32: чужие заняли k_first, добор вернул свои; overfetch_used=True |
| foreign_candidates_cannot_hide_own_duplicate | dedup: 3 чужих ближе → старый k=3 возвращал только чужих; теперь свой дубликат |
| no_foreign_leak_when_own_absent | чужие не возвращаются никогда (не-регрессия фильтра) |
| expired_own_excluded_no_foreign_substitute | TTL-liveness: просроченный свой исключён, чужой живой НЕ подставляется |
| decision_foreign_crowd_no_longer_misses_duplicate | интеграция `_dedup_decide`+реальный `_dedup_knn`: толпа чужих → старый код add (дубликат пропущен), теперь noop по своему (cosine 0.96 ≥ HIGH) |

## Acceptance evidence

| Пункт | Статус | Доказательство |
|---|---|---|
| Chat A (X) / Chat B (тот же user, Y): запрос из A → только A-факты при заполненном лимите | PASS | RED: на старом коде 6/9 тестов падают (git stash push -- services/summary_memory.py → 6 failed; pop → restore). GREEN: float+int8 displacement-тесты |
| Dedup: чужой кандидат не блокирует запись факта A; свой дубликат находится | PASS | decision-тест: noop по своему дубликату среди толпы чужих (старый код → add) |
| Overfetch-деградация: чужих больше cap → частичный результат помечен, не пустой молча | PASS | cap=8: facts=[свой], tele.partial=True, WARNING-лог; различение exhausted-vs-partial покрыто |
| Существующие summary_memory/retrieval тесты зелёные | PASS | обновлений существующих тестов НЕ потребовалось (сигнатуры/топология сохранены; `_search_archive_knn` остался seam'ом мока в test_summary_memory.py:253) |
| Команда `pytest tests/test_asap8_v6_d06_isolation.py tests/test_summary_memory*.py -q` | PASS | 88 passed |
| Регрессия вокруг seam'ов | PASS | test_graphrag_memory + test_memory_maintenance + test_summary_generator + test_tool_router + test_dream_worker: 408+135 passed суммарно (273 в одном прогоне с maintenance, 135 consumers) |

Финальный прогон (фикс телеметрии overfetch_used → attempts>1):
`tests/test_asap8_v6_d06_isolation.py tests/test_summary_memory.py tests/test_graphrag_memory.py tests/test_memory_maintenance.py -q` → 273 passed;
`tests/test_summary_generator.py tests/test_tool_router.py tests/test_dream_worker.py -q` → 135 passed.

## Findings (анти-паттерн на других поверхностях — фикс вне этого слайса)

1. **GraphRAG RAG vector retrieval — тот же механизм, ПРИОРИТЕТ**.
   `_vec_candidates` → `_vec_int8_rows`/`_vec_float_rows` → `_filter_vec_rows`
   (services/summary_memory.py ~:4265–4321): глобальный KNN `k=fetch_k×4` (int8) / `×2`
   (float) → Python-фильтр chat_id/origin/TTL. Overfetch есть, но стадийной гарантии/телетерии
   нет — свои факты за пределами глобального K вытесняются. Отдельный slice M: тот же
   `_staged_knn_scope` (helper уже в дереве) + negative-тесты.
2. **Настоящий scope-before-KNN требует DDL-миграции** (вне lane). Probe подтверждил:
   sqlite-vec 0.1.9 **поддерживает** `chat_id INTEGER partition key` в vec0 — тогда
   `WHERE embedding MATCH ? AND k = ? AND chat_id = ?` даёт per-partition top-K (проверено
   на фикстуре). Миграция = DROP/recreate vec-таблиц + backfill (механизм уже есть:
   `_rebuild_vec_tables_if_needed` + backfill'ы). Staged overfetch в этом слайсе —
   сознательный промежуточный контракт без DDL.
3. Чисто (проверено grep'ом, анти-паттерна нет): graph edges SQL (`get_top_edges`,
   `get_top_edges_all`, expansion — `WHERE e.chat_id = ?` до LIMIT); stories
   (`web_stories.py` — chat_id в SQL WHERE); lesson matching (`mca_experience.
   list_scope_candidates` — scope в SQL WHERE); dossier SQL — per-chat схема, чтения
   SQL-скоупнуты (ledger-d это же констатировал).

## Incidental findings

- `EMBEDDING_DIM=3072` (settings) vs фикстурная dim=8 — ожидаемый WARNING тест-среды
  (initialize берёт dim из probe-эмбедда), не дефект.
- vec0 int8-колонка NOT NULL: INSERT без `embedding_i8` на int8-DDL невозможен (float-ветка
  записи/бэкфилла валидна только на float-DDL) — это уже учтено прод-логикой
  (`_rebuild_vec_tables_if_needed`), зафиксировано здесь как документированное ограничение.

## Остаточный риск

- Staged overfetch — не partition: при экстремальном перекосе (сотни чужих фактов ближе
  всех своих и cap=512 достигнут) результат частичный — но ПОМЕЧЕН (WARNING + tele.partial),
  не молчаливый. Устраняется миграцией partition key (finding 2).
- Смешанный partial-результат не дополняется FTS (§18F.4 «text fallback … non-empty but
  incomplete») — текущий контракт слайса: пометка деградации; FTS-merge менял бы семантику
  L3-ответа (потребители C03A-зоны) — вынести в отдельное решение.

## Источники

- sqlite-vec 0.1.9 — probe в venv (`vec_version() = v0.1.9`; auxiliary-WHERE отказ; partition
  key поддержка; k>rows поведение). Скрипты: OPENCODE_WORKFLOW_SCRATCH (d06_vec_probe.py,
  d06_int8_probe*.py) — transient, в репозиторий не попали.
- plans/features/asap8-v6-remediation/ledger-d.md (D06), plans/ASAP8_v6_delta_after_F1-F9.md
  §C D06, plans/current_task.md §9A.3/§9A.5/§18F.4/U13/M11 (read-only).
