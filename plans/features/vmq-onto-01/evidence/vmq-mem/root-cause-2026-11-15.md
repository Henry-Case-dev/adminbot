# VMQ-MEM / VMQ-MEM-TIME — bounded root-cause diagnosis (2026-11-15)

Статус: read-only диагностика. Код, БД, конфигурация и production не изменялись.
Основание: `measurement-2026-11-15.md`, `run-retrieval-trace.json`,
`formulation-class-matrix.json`, `metrics-comparison.json`,
`year-bias-root-cause.md`, а также текущие исходники `master`.

## 1. Итог

Диагноз: основная проблема — не один endpoint, а последовательное ослабление
материала на общих границах retrieval → нормализация/отбор → projection/tool →
Writer. Многолетний контракт VMQ-MEM/TIME сейчас не выполнен.

Подтверждены как продуктовые дефекты:

* явный вопрос про 2023 год теряет весь 2023-период после отбора по предмету;
* обычный профиль/общий person-path не гарантирует subject-bound material и
  отдаёт свежий общий материал вместо фактов о P1;
* relationships имеет честный `empty_reason=empty`, но действующий consumer не
  предоставляет временной связевой материал вообще;
* событие без года не имеет intent-aware старого периода и остаётся
  2026-доминированным;
* M2 overview вызывается лексическим маркером, а не смысловым классом запроса,
  поэтому точная owner-формулировка не получает overview.

`compat_not_proven` и единичный `EMBED_API_FAILED` в probe-копии — доказательство
деградации именно измерительного запуска, но не доказательство того, что live
индекс production несовместим. В текущем коде это fail-safe состояние
`insufficient/retry_canary`, а ранее зафиксированный live process был
`ADMITTED_COMPATIBLE`. До отдельного live read-only подтверждения это остаётся
unknown и не должно быть превращено в атрибуцию дефекта продакшену.

## 2. Подтверждённые факты и граница артефакта

### Измерение

На свежей read-only копии production DB (2 075 621 сообщений, schema 47,
2022–2026) baseline `c97c06e4` и не выложенный candidate `f7a9c596` дали
идентичные retrieval rows. На вопрос `...в 2023 году` в pool были 13 строк 2023,
но после subject filter принято 0; 15 из 16 period rows были отклонены.
У `A1` точный owner query до Writer дошёл только одной старой строкой 2024,
тогда как lore/Chronicle path для той же темы дал 148 строк 2022–2023 и 6 edges.
В profile reply block 0/10 строк были атрибутированы P1; в graph нет фактов о P1
за 2023–2024 при 44 577 сообщениях P1. `biography` содержит пять лет,
`general` — только 2026. Relationships: 0 edges, `empty_reason=empty`,
fabricated-relations = 0/0 (вакуумная метрика). Event без года остаётся в 2026;
явный `dig(year=2023)` умеет time window, но его snippets не доезжают из-за
budget. M2 overview есть на `история/расскажи... историю`, но не на
`рассказ ... шизах`.

Это не доказывает качество сгенерированного ответа: Writer не запускался,
`Global_Context` и live process не участвовали; candidate не deployed.

### Кодовые контракты

1. Единая точка retrieval — `services/mca_retrieval_context.py:541-713`.
   `retrieve()` сначала строит exact/lexical/vector/episode candidates, применяет
   time/participant filters, dedup, identity prior и top-k. Исторический режим
   включается только при `mode=history` или `is_history_query()`.
2. `is_history_query()` — `mca_retrieval_context.py:416-420`; список маркеров
   `_HISTORY_MARKERS` — `:307-311`: `истори`, `расскажи`, `что было`, `раньше`,
   `хроник`, `летопис` и т.п. Слова `рассказ` и `шизах` сами по себе в список
   не входят. Поэтому M2 trigger — реальный lexical defect, не случайность
   harness.
3. `_build_old_episodes()` в `services/direct_chat_service.py:6643-6781`
   создаёт `RetrievalRequest(mode="history", top_k=8)` (`:6677-6679`), а при
   history sample связывает только фактические границы sample через
   `bind_quantitative_range` (`:6682-6696`). Потребитель допускает в episode
   только `entity_type == "message"` (`:6716-6724`), затем режет результат
   `max_count`/`max_messages` (`:6706-6708`). Это объясняет, почему старые
   episode rows существуют, но 2026 episodes могут заполнить два слота.
4. Векторный leg использует `memory.retrieve_fact_candidates()` в
   `mca_retrieval_context.py:618-628`; ошибка канала намеренно проглатывается
   как деградация. Индексная совместимость разрешается read-only в
   `services/embedding_control_plane.py:3300-3434`: при одинаковом MSI без
   durable admission результат — `state=insufficient`,
   `reason_code=compat_not_proven`, `needs_probe=true`, `action=retry_canary`
   (`:3421-3427`). При валидном admission тот же код возвращает
   `state=compatible`, `class=admitted` (`:3376-3383`). Следовательно, probe
   показал отключённую семантическую leg в копии, но не установил live-state.
5. Профильный tool path — `services/tool_router.py:2187-2208`. `biography`
   читает `db.get_user_context_facts()` (`:2257-2281`), а `general` сначала
   вызывает `memory.get_rag_facts()` и затем `search_long_term()` (`:2313-2367`).
   Это разные источники с разной семантикой: general не является subject-bound
   biography. Reply RAG не получает subject guarantee только от того, что
   вопрос содержит имя; subject candidate должен быть передан в
   `RetrievalRequest.subject_entity_ids` (`mca_retrieval_context.py:328-334`).
6. Relationships — отдельная projection: `tool_router.py:2283-2311`
   вызывает `db.get_persona_card(...).links`, копирует source/target/relation,
   но при пустом списке возвращает `empty_reason="empty"` (`:2306-2309`).
   Временная ось здесь не строится; это не ложная нулевая метрика, а отсутствие
   данных в текущем canonical projection. Следовательно, нельзя лечить это
   route-level подстановкой выдуманных edges.
7. Canonical fact read сохраняет attribution-поля в SQL projection:
   `services/database.py:9900-9925` выбирает `subject_ref_id`,
   `attribution_method`, `speaker_author_id`, `provenance_channel`; schema и
   claim contract запрещают молча считать sender субъектом
   (`services/claim_envelope.py:97-120, 200-216`). Нулевой P1 attribution поэтому
   означает разрыв producer/subject binding или отсутствие подтверждённых facts,
   а не разрешение на fallback `author=P1`.
8. Старый год дополнительно теряется из-за известного quota/status/rank seam:
   `year-bias-root-cause.md:31-45` фиксирует `confirmed`-only read для обычного
   RAG, возрастной вес и вытеснение старых фактов в `archived_fact`; current
   SQL default также ограничивает обычный FTS `status IN ('confirmed')`
   (`database.py:9893-9920`). Это подтверждённая shared MEM/TIME причина
   2026-dominance, но для включения archived facts требуется intent-specific
   policy, не безусловное расширение всех RAG reads.

## 3. Разделение дефектов, артефактов и unknown

### Product defects

* **MEM/TIME period selection:** strict `>=2 common stems` применён к
  period-fill rows без достаточного предметного fallback; при явном годе он
  отбрасывает known-answer rows. Периодный leg должен иметь отдельную
  year/intent-preserving ветку отбора, а не считать слабое lexical overlap
  доказательством нерелевантности.
* **MEM/TIME vector admission:** сам механизм отказа fail-safe корректен, но
  продуктовый acceptance не может считаться выполненным при неактивной leg.
  Исправление должно сначала дать измеряемый live admission/compatible proof;
  если live также `compat_not_proven`, это operational/integration defect
  отдельного embedding slice, а не повод маскировать его лексикой.
* **MEM/TIME subject/profile:** general/reply path не обязан возвращать P1 без
  subject-bound query plan, а текущий confirmed-only/age-biased material не
  покрывает multi-year identity. Нужен canonical subject projection с честной
  attribution и ограниченной multi-year квотой.
* **MEM/TIME relationships:** текущая persona-card projection не является
  временной историей отношений. Пустой результат честен, но он не удовлетворяет
  TIME/MEM contract “как менялись за годы”. Нельзя засчитывать 0/0 fabricated
  metric как успех.
* **TIME event без года:** intent без explicit year должен получать bounded
  multi-year retrieval для повторяющегося E1, с current-state control path,
  иначе свежий rank всегда доминирует.
* **M2/O-04:** overview trigger должен быть нормализован по intent/семантическому
  классу и должен включать owner formulation; расширение одной строкой marker —
  минимально, но надёжнее общий classifier/result flag из retrieval contract.

### Measurement artifacts / limitations

* `compat_not_proven` и `EMBED_API_FAILED` в copy — не live attribution;
  provider identity в старом ad-hoc probe, где `primary` ошибочно заменил
  `apinet_paid`, также не является product defect.
* Candidate `f7a9c596` не deployed; его overview numbers — candidate probe only.
* Один чат, один запрос на класс, один stochastic rerank run; snippets budget
  не позволяет использовать их как доказательство payload-level chronology.
* Копия DB не доказывает live process, hot cache parity или фактический выбор
  инструмента моделью.

### Не доказано / требует отдельной проверки

* Почему именно в probe-копии не был найден durable admission: нужен один
  read-only live check effective generation/admission/space/conn и, если
  разрешено текущим operational policy, один controlled compatibility probe.
* Какие конкретно producer writes создали/не создали P1 subject facts за
  2023–2024; read path дефект подтверждён, producer gap пока hypothesis.
* Достаточность lore/Chronicle path как permanent MEM-04 source: он даёт
  материал, но не заменяет parity обычного retrieval.

## 4. Общий data/control flow и минимальный corrective train

### Slice A — MEM/TIME retrieval period + vector admission

**Владелец/write scope:** `services/mca_retrieval_context.py` и связанные
retrieval tests/evidence; admission state/diagnostic integration только в
существующем `embedding_control_plane.py` contract. Не менять tool_router,
M2 или schema. Shared file `mca_retrieval_context.py` сериализовать: это
общий writer MEM и dependent M2 consumer.

**Изменение:** для explicit year или detected historical intent передавать
структурированный period intent; period pool сначала сохраняет rows внутри
временной цели, затем применяет subject relevance с мягким fallback и
reason-coded drops. Не ослаблять current-state path. Vector leg должна
участвовать только после `compatible`/`admitted`; при insufficient — честный
diagnostic `vector_unavailable`, но acceptance этого slice не проходит без
отдельного доказательства live admission.

**Acceptance:** тот же archived known-answer harness: 2023 rows survive for
explicit 2023 conflict; no 2026 rows masquerade as 2023; no fabricated source;
vector trace contains effective state and reason. Negative: “что сейчас” остаётся
fresh-dominant. Evidence must bind exact candidate and, for live-dependent row,
actual effective generation/admission.

### Slice B — MEM/TIME subject, chronology and relations projection

**Зависимость:** после A; shared read contracts serialize with any other
`mca_retrieval_context.py` writer. Write scope: `services/tool_router.py`,
`services/database.py` read query/projection, and the existing subject/relations
producer only where tracing proves missing canonical data. No new store and no
unconditional archived-fact exposure.

**Изменение:** biography/general/reply must carry resolved subject identity and
  source attribution; use a bounded year-diverse read policy for identity/profile
  questions, preserving `as_of`/status and excluding stale facts from
  current-state intent. For relationships, either consume existing sourced edges
  with timestamps or return an explicit “no temporal projection” diagnostic;
  do not synthesize links. If producer has no attributable P1 facts, retain
  `empty_reason` rather than mapping author to subject.

**Acceptance:** P1 known-answer rows include subject refs and at least 2023/2024
  in profile material; current-state control remains 2026-biased; relationships
  either return sourced year-bearing edges or a non-vacuous unavailable reason;
  invented-relations stays 0 with denominator >0 where edges exist.

### Slice C — M2/O-04 overview trigger and contract propagation

**Dependency:** A’s structured intent/result flag; B not required for lexical
trigger, but release integration follows B so overview cannot conceal bad data.
Write scope: `vmq/m2` M2 files/tests only; no concurrent edits to shared
`mca_retrieval_context.py` without serialized merge. Prefer consuming a
canonical `history_intent`/coverage result over duplicating marker logic.

**Change:** exact owner query and equivalent creative/history formulations must
produce the same bounded overview eligibility; overview is additive and never
claims coverage that retrieval did not deliver.

**Acceptance:** A1 exact query receives overview slots with actual coverage and
limitations; non-history “what is happening now” does not; overview fields are
stable across baseline/candidate except intended additive fields.

## 5. Parallel-safety and release recommendation

* Slice A: `SERIALIZE` on `mca_retrieval_context.py`; read-only corpus analysis
  can run in parallel. Embedding admission check is `READ_ONLY_PARALLEL` until
  any durable state write is required; no state write was authorized here.
* Slice B: `BLOCKED_BY:A` for retrieval contract, then `SERIALIZE` on
  `tool_router.py`/database projection writes. Producer attribution changes and
  read policy must join in one reviewed candidate.
* Slice C: `BLOCKED_BY:A`; M2 branch is otherwise parallel-safe, but integration
  with the shared retrieval contract is serialized.

The proposed `ONTO-A → ONTO-B → M2` train **must be held as a complete VMQ-MEM /
VMQ-TIME release** until A and B are fixed and independently reviewed. M2 may
be developed/tested in isolation, but it must not be presented as completing the
owner’s multi-year memory or 2026-dominance defect: its current overview is
additive metadata over unchanged bad material. A release that leaves explicit
2023 retrieval, subject binding, event-without-year and chronology acceptance
unfixed is not complete. The PET_PROJECT standing rule authorizes release of a
ready feature; it does not authorize weakening failed mandatory acceptance.

## 6. Risks and rollback

* **R0:** period fallback may admit semantically weak rows. Keep explicit
  `drop_reason`, source refs and intent-specific thresholds; rollback is a code
  revert to prior retrieval policy without schema migration.
* **R1:** enabling archived/older profile material can mix stale and current
  facts. Gate by purpose and preserve status/as-of; rollback by disabling the
  new policy, not by deleting data.
* **R2:** vector admission may expose provider/index incompatibility. Fail safe,
  keep lexical result honest, and do not adopt vectors without the existing
  admission proof.
* **R3:** trigger expansion can over-classify ordinary creative prompts. Use
  structured intent plus negative current-state cases; overview remains additive
  and bounded.

## 7. Verdict

`ARCHITECT_ADJUSTMENT_REQUIRED`.

The existing VMQ contracts are adequate for a bounded repair; no new service,
schema or memory store is justified. However, the current implementation cannot
pass MEM-04/TIME-01/TIME-03 and related profile/relations acceptance. Required
next action: Builder/Orchestrator freeze slices A→B→C with the scopes above,
perform the one live read-only compatibility/admission check, then run the same
candidate-bound archived corpus measurement and independent review. Keep the
release train held until mandatory evidence is green.

Housekeeping: no transient workflow runs, screenshots, browser sessions or
temporary files were created by this diagnosis; no cleanup required. The only
new path is this durable diagnosis note.
