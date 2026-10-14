# ASAP 8 Phase A — Forensic audit: Summary (Symptom 1 + Symptom 2)

Baseline: master `0c4f3a5` (2.58.74). Read-only audit; незакоммиченный шум
(`services/disk_retention.py`, `plans/MEMORY.md`, `plans/runtime_task.md`,
`plans/workflow_state.md` и др. — `git status`: 8 modified, визуальный шум) — не трогал.

---

## 1. Symptom 1 — `invalid_paragraph` топит документ — **CONFIRMED**

### 1.1. Точная арифметика `invalid_paragraph`

`services/summary_l2_writer.py`:
- `PARAGRAPH_MAX = 900` — :78; `MAX_PARAGRAPHS_HARD=498` — :82; `RICH_MAX_CHARS=32000` — :83.
- `_valid_paragraph_text` :790-796 → `None` если: не `str` / пустой после `.strip()` / `len > 900`.
- `_validate` отвергает ВЕСЬ документ (`_reject` → `document=None`) в точках:
  - :934-937 — text=None после `cleanup_llm_text` + `_valid_paragraph_text`
    (пустой абзац; абзац >900 символов; text не-строка → `or ""` → пустой);
  - :940-943 — пустой ПОСЛЕ вырезания сырых ID (`fact:N`/`msg:N`/`[NN.NNNN|`,
    `_strip_raw_ids` :697-708): абзац только из служебных меток → пусто → reject;
  - :1046-1047 — `canonical` пуст (`paragraphs: []` или все отброшены) → тоже
    `REASON_INVALID_PARAGRAPH` (это будущий `document_no_paragraphs`).
- Не-`invalid_paragraph` соседи: не-dict элемент/`emphasis` не-str → `bad_type`
  (:928, :1027-1031); invented evidence → `invalid_evidence` (:950-958);
  `quote_attribution` (:1006-1022); `too_long` >32000 (:1048-1049).

Repro (детерминированный, без LLM): `validate_l2_document({"schema_version":1,
"title":"t","paragraphs":[{"text":"x"*901}]}, package)` → `(None, {reason:
"invalid_paragraph"})`. Один абзац 901 символ (или один пустой среди 10 валидных)
убивает статью целиком → `L2Result.usable=False` → LEVEL-3 Legacy.

### 1.2. (а) Repair/split сегодня — НЕТ
Единственные ремонты внутри `_validate`: снятие кавычек
(`process_paragraph_quotes` :970-1010), вырез raw-ID (:940), канонизация
emphasis (:1032). Split по предложениям / удаление пустого элемента /
пере-подсчёт evidence при split — отсутствуют. `run_l2` :1409-1424 — «ровно
один физический вызов (L2 correction retry не вводится)».

### 1.3. (б) Reason-коды — не granular
`REASON_*` :128-148: один umbrella `invalid_paragraph` на 3 разных дефекта
(1.1). Гранулярность есть только по классам, не по абзацам.

### 1.4. (в) Correction attempt после валидатора — НЕТ
`summary_generator.py:2298-2325`: `not l2_result.usable` → WARN `L2_ERROR` →
немедленно `_legacy_fallback("l2_unusable")`. Попытки исправления нет
(осознанно на момент ADR-1027-10 D3; ТЗ §2.4 теперь требует ONE attempt —
инвариант «ровно 1 вызов L2» придётся менять явно, см. Вопросы).

### 1.5. (г) Telemetry причины — код есть, индексов нет
- WARN: `summary_generator.py:2303-2306` `L2_ERROR | reason=invalid_paragraph`
  (только код).
- Событие: `pipeline_events.py:294-306` `SUMMARY_L2_STAGE`
  `outcome=failed, reason_code, duration_ms, counts={output_count}`.
  `paragraph_index`/`chars` — НЕ пишутся нигде (`_reject` :773-776 пишет только
  status/reason; metrics :739-763 не содержат индекс абзаца).

### 1.6. (г→д) Почему UI говорит «L2 не выполнено» при attempted+invalid
Цепочка: `summary_generator.py:2274-2278` → `_durable_stage_result(ctx, "l2",
"failed", reason)` (исключение только для `l2_review_rejected/_unusable`;
validator-invalid тоже пишется как `failed`) → `pipeline_analytics.py:1291`
`writer = _trace_stage_row(_last_stage("l2"))` → `web/app.js:3529-3534`
`statusRu = { ok:'успешно', failed:'не выполнено', ... }` → рендер
`web/index.html:4688`. Статуса `attempted_invalid` не существует — S4
подтверждён на уровне кода. (Комментарий :2263-2268 показывает, что «не
выполнено» задумывалось только для transport/структурного провала —
validator-invalid туда попадает нечаянно.)

### 1.7. (е) Coverage «0 / 865» — единый скаляр
Строка = `Final text (source)`-ось: `pipeline_analytics.py:844-849`
`out["final"] = {total: usage.source_total, considered:
usage.source_considered, percent: usage.coverage}` из `SUMMARY_RUN_DONE`.
usage_json → `ctx.source_total/considered/coverage`. В Hybrid writer-source ON
ставится 100% (`summary_generator.py:2121-2124`), затем package-coverage
(:2125-2137), затем **Legacy перезаписывает** :1323-1355
(`compute_package_coverage`, `summary_legacy_fullwindow.py:157-202` —
considered = |chronology ∪ fragments ∪ evidence ∪ unassigned| пакета).
Раздельные оси (source/L1/writer/final/overflow) УЖЕ существуют
(`_coverage_breakdown` :724-850, UI `app.js:3444-3516`), но headline-скаляр
`usage.coverage` — один: он же в `health_of` :1197-1205 (coverage<ε →
degraded). «0/865» = considered=0 у финальной оси; точное значение этого run'а
нужен из prod `SUMMARY_RUN_DONE` (live evidence, не архитектура).

---

## 2. Symptom 2 — Summary Test ≠ production — **CONFIRMED**

- Production: `summary_generator.py:1931-1935` `run_l1(..., focus_block=...,
  source_window=source_window)`; окно создаётся в `_establish_source_window`
  :704-750 (`ssw.build_source_window` :723, `summary_source_window.py:156-190`);
  L2: `:2168-2172` `_run_writer_source_stage(..., source_window=...)`
  (source_input + anchor_map + length).
- Dry-run: `summary_test_run.py:557-559` `run_l1(llm, rows, chat_id,
  correlation_id)` — БЕЗ `source_window` и `focus_block`; L2 :630-632/:650-652 —
  БЕЗ `source_input`/`anchor_map`/`length`. Строки берутся из
  `build_test_rows` (`summary_generator.py:2471-2511`) — read-only rows, окна
  не создаёт.
- Anchor-space включается ТОЛЬКО при окне: `summary_l1_clusterizer.py:1737-1742`
  `anchor_map = resolve_anchor_map(source_window, ...)`; `resolve_anchor_map`
  :585-598 → `None` при `source_window is None` (fail-open к raw
  `message_id`-контракту + другой system-промпт :1746-1749).
- Dry-run всё же проходит через capacity-first (`run_l1` :1719-1725 →
  `run_l1_capacity_first` :1626-1632, `_map_mode=semantic_map_enabled()`), но
  `source_window=None` внутри → `anchor_mode=False` → map-v1 ветка :1976-1999.
- `build_summary_execution_input` — НЕ существует (grep по services: 0).
  Нужные входы: rows; immutable source_window (run_id/chat_id/rows);
  anchor map; budget (`resolve_l1_effective_budget`/`resolve_l2_package_budget`);
  focus_block; length (`resolve_hybrid_length`); слоты L1/L2
  (`resolve_l1_slot`/`resolve_l2_slot`).
- Предлагаемая сигнатура и call-sites:
  `build_summary_execution_input(*, chat_id, rows, correlation_id, focus=None,
  trigger_message_id=None) -> ExecutionInput{rows, source_window, anchor_map,
  budget_l1, budget_l2, focus_block, length, slot_l1, slot_l2}`.
  Prod: перед `_run_hybrid_l2` (`summary_generator.py:647-650` + `_establish_…`
  :704); Test: `summary_test_run.py:520-559` (вместо `build_test_rows` +
  голого `run_l1`; окно in-memory с test run_id, 0 durable-записей); replay —
  через `source_window_from_row` (`summary_source_window.py:193-216`).

---

## 3. Unknown refs (L1) — repair ЖИВ, но не для map-v1 (путь dry-run) — **CONFIRMED**

- §95-v2 (threads/facts): `repair_l1` (`summary_l1_repair.py:108-265`) удаляет
  unknown ids (:15-16, :138-222); mass-unknown >50% → `useless` →
  `l1_useless_after_repair`. Вызывается `clusterizer:2029-2047` (между parse и
  validate, kill-switch `flags.summary_hybrid_l1_repair_enabled`).
- v2-anchor: `validate_semantic_map_v2(..., repair=_l1_anchor_repair_enabled())`
  (`clusterizer:1968-1971`) + `repair_l1_anchors` (`summary_l1_repair.py:319+`)
  — локальное удаление битых якорей.
- **map-v1 (anchor_mode=False — именно dry-run): ремонта НЕТ.**
  `validate_semantic_map` (`summary_l1_semantic_map.py:294-428`):
  `_ids_in_space` :314-328 → один unknown id в любом topic/event →
  `REASON_UNKNOWN_MESSAGE_ID` (:371-374, :414-417), fail-closed, ничего не
  удаляется. `unknown_ids` собираются только для correction-блока
  (`clusterizer:1977`, `_collect_map_unknown_ids`).
- Retry: `unknown_message_id` ∈ `RETRYABLE_MAP_REASONS`
  (`semantic_map.py:128-135`) → РОВНО одна correction-попытка
  (`clusterizer:2101-2135`, kill-switch `flags.summary_hybrid_l1_retry_enabled`).
  Если retry снова содержит unknown id → invalid. Итог dry-run:
  `summary_test_run.py:570-585` → `TEST_L1_INVALID · unknown_message_id`
  (~76.7s = LLM-время двух попыток). Prod не падал так, потому что идёт через
  anchors + v2-repair. Итого «deterministic repair жив», но map-v1 — единственный
  контракт без него; ТЗ §3.4 (small trash → remove) для него не выполняется.

---

## 4. S1-S7 → файлы/функции

- **S1** (950 chars → split → Hybrid): `summary_l2_writer.py::_validate`
  (:934-937) / `_valid_paragraph_text` (:790-796); точки вставки repair — до
  `_reject` в цикле канонизации (:925-1047).
- **S2** (empty paragraph → удалить only): тот же цикл; + кейс «пусто после
  ID-strip» (:940-943) и `[]` (:1046-1047).
- **S3** (invented evidence ≠ факт): strict-чек :950-967 (`invalid_evidence`,
  `package_message_id_space` :393-425); anchor-ремонт :1088-1180 + 
  `summary_l2_anchor_repair.repair_l2_evidence` — оставлять fail-closed в
  не-anchor режиме.
- **S4** (attempted_invalid ≠ not_run): `pipeline_events.py:294-306`;
  `summary_generator.py:2274-2278`; `pipeline_analytics.py:1291`;
  `web/app.js:3529-3534` + `index.html:4688`.
- **S5** (parity fingerprint/anchor mode): `summary_test_run.py:557`;
  `summary_generator.py:1931-1935, 704-750`; `summary_l1_clusterizer.py:585-598,
  1737-1742`; регресс — один fixture → одинаковый `messages_json` fingerprint +
  `anchor_mode`.
- **S6** (small unknown refs → remove): `summary_l1_semantic_map.py:314-328,
  371-374, 414-417` (сегодня fail-closed) — добавить v1-remover по образцу
  `summary_l1_repair.py`.
- **S7** (map unusable → ровно 1 retry → fail-closed): `clusterizer:2101-2135`;
  счётчики `unknown_refs_count/removed_unknown_refs/map_useful_after_repair/
  retry_used/anchor_mode/source_window_present` сейчас частично в
  `RepairReport.as_log_fields` (`summary_l1_repair.py:83-86`) — в events не идут.

## 5. Лог-гигиена §26 (Summary)

Summary WARN-ы — transition-based, не «на каждый повтор»: `L2_ERROR` один на
run (`summary_generator.py:2303-2306`), `L1_CORRECTION_RETRY` один
(`clusterizer:2108-2112`), `SUMMARY_TEST_*` один на failure
(`summary_test_run.py:525-527, 698-701`). Нарушений repeat-WARN не найдено.
Разрыв с §26 другой: «L2 invalid → WARN с granular code» — сегодня код
umbrella (`invalid_paragraph`) без paragraph_index/chars.

---

## Вопросы для Architect (только развилки)

1. **Порядок L2-repair**: granular-детект + split/remove внутри цикла
   канонизации `_validate` (один проход, точные reason+index) или
   pre-validate pass над raw-документом с последующим revalidate? Влияет на
   метрики/`quote_repair`-пайплайн.
2. **ONE L2 correction attempt (§2.4) vs инвариант «ровно 1 вызов L2»**
   (`summary_l2_writer.py:11-14, 1424`): какой контракт менять явно, как
   считать `calls_so_far`/бюджет ≤5 генераций.
3. **build_summary_execution_input**: владелец (метод generator vs новый
   модуль); достаточно ли in-memory окна для dry-run (fingerprint/checksum
   строится от run_id — окно без durable-строки валидно?).
4. **Granular reason-коды**: §28.1 запрещает «только переименовать» —
   сохранить `invalid_paragraph` как umbrella + аддитивные
   `paragraph_*`-коды/поля (paragraph_index/chars в metrics+events) или полная
   замена набора?
5. **Coverage UI (§2.5)**: оси уже есть в `coverage_breakdown` — задача только
   починить headline-скаляр (финальная ось, Legacy overwrite
   `summary_generator.py:1323-1355`) или добавить явную строку «L2 accepted
   coverage»?
