# P-OLDROW — corrective F1 (Builder, 2026-11-27/28)

Роль: Builder. Предыдущий кандидат: `e1c70d58f926ceb923594ee9bcf551e663ccb964`.
База: `9516c912554bb1062f62a63b6689f418c1cb5425` (2.58.257).
Ревью: `review-r1.md` (NEEDS_FIXES: F1 блокирует, F2 — тест, F3/F4 — backlog).
Контракт: `selector-rootcause-2026-11-27.md`, sha256
`bcce78bb31cec83f703031270af3a52ec2eb30a9a7421e726e45f0297b2e50fc`.

Закрыто: **F1 (OLDROW-R3-BASE-01)** и **F2 (OLDROW-TEST-CAL-01)**.
F3/F4 не трогались (backlog). Деплоя, карт, `progress_scope.json`, настроек
прода и Telegram не было; снимок только `mode=ro&immutable=1` +
`PRAGMA query_only=ON` (sha256 до и после совпал).

## 1. F1 — как именно сохранена база

`subject_scope` имеет `replace_allowed=0`, поэтому периодный вклад больше НЕ
участвует в замещении хвоста базового среза:

```python
# services/direct_chat_service.py, _rag_unified_rows
if subject_scope and not replace_allowed:
    capacity = int(limit) + int(budget)      # budget = period_slots = limit//5
    trial = self._rag_append_period_rows(rows, to_append, capacity, slots=budget)
    base_rows_dropped = 0
    subject_scope_no_replace = 1
else:
    ... прежнее замещение хвоста (historical/plan-сигнал/тонкий/разбор) ...
```

* базовый срез передаётся в добор ЦЕЛИКОМ (`rows`, без `trimmed`) — ни одна
  базовая строка не выбрасывается, порядок первых `base_slots` строк не
  меняется;
* периодный вклад ограничен теми же `limit//5` строками, но занимает
  ДОПОЛНИТЕЛЬНУЮ ёмкость `limit + limit//5`: глобальный `limit`, `per_year`,
  `historical_quota`/`multi_year_quota` не растут;
* ветка `else` (в т.ч. `historical` и plan-сигналы) сохраняет прежнее
  замещение хвоста — это подтверждает неизменный
  `test_vmq_mem_slice_d::test_a1p_historical_vs_auto` (2026:8 + 2024:1 +
  2023:1 при бюджете 2);
* наблюдаемость: `_rag_period_stats`/`_period_trace` получают
  `base_rows_dropped` и `subject_scope_no_replace` (только числа).
  `period_skipped` не менялся — это F4 (backlog), трасса по-прежнему пишет
  `auto_full_slice` при фактически исполненном доборе (честно фиксируем).

**Точное воспроизведение ревью** (`raw/corrective/fixture-f1-ids.json`,
фикстура из 10 базовых `8000..8009`, 3 strict 2026 + 2 soft old, `auto`,
`limit=10`, `period_slots=2`):

| Код | delivered ids | выброшено из базы |
|---|---|---|
| prev `e1c70d58f` | `[8000..8007, 9100, 9201]` | **8008, 8009** |
| fixed | `[8000..8009, 9100, 9201]` | — |

`base_rows_dropped=0`, `subject_scope_no_replace=1`, `breadth_used=2`,
`reserved_old=1`, `replace_allowed=0`.

## 2. F2 — календарно-независимый тест

* `_seed_author_years` сеет три ЗАВЕРШЁННЫХ года относительно
  `datetime.now(UTC).year` (+ одно сообщение текущего года), а не 2023–2025;
* ожидание в `test_subject_window_is_bounded_and_multi_year` сравнивается с
  `_completed_years()`;
* новый `test_subject_window_uses_reader_default_window` проверяет саму
  формулу окна: `_author_window_bounds` == `(start(current-3), end(current-1))`
  из существующего `year_time_bounds`, и что без разрешённого субъекта окна
  нет. Тест не устаревает при смене календаря.

## 3. Тесты

Новый файл `tests/test_vmq_oldrow_person_delivery.py`: **19 тестов** (было 17).

| Прогон | Результат |
|---|---|
| fixed (этот кандидат) | **19 passed** (`raw/corrective/pytest-fixed-new.txt`) |
| prev `e1c70d58f` (F1-дефект, те же тесты) | **2 failed / 17 passed** — оба F1-теста (`pytest-prev-e1c70d58f-new.txt`) |
| base `9516c9125` (те же тесты) | **12 failed / 7 passed** (`pytest-base-9516c9125-new.txt`) |

F1-тесты:
* `test_subject_scope_does_not_drop_base_tail` — новый различающий: полный
  base `8000..8009`, `subject_scope`, `replace_allowed=0`; проверяет, что
  множества базовых id не потеряны, `[8008, 8009]` присутствуют, первые 10
  позиций — ровно `8000..8009`, старый период добавлен,
  `base_rows_dropped=0`, длина ≤ `base + limit//5`;
* обновлённый `test_auto_person_reaches_old_row_without_replacing_base` —
  теперь проверяет ВЕСЬ базовый набор и порядок (`ids[:10] == 8000..8009`),
  `base_rows_dropped=0`, `subject_scope_no_replace=1`, длину `base + 2`, а не
  только `rows[0]` и длину.

Затронутые наборы (11 файлов, `raw/corrective/pytest-fixed-impacted.txt`):
**211 passed / 4 failed**; те же 4 падают на базе с её исходными тестами
(`raw/corrective/pytest-base-9516c9125-impacted.txt`), предсуществующие:

1. `tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year`
2. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_historical_plan_rebuilds_block_with_plan_scope`
3. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_operative_plan_narrows_block`
4. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_t16_research_plan_rebuilds_rag_block`

Дополнительно: `test_direct_chat`, `test_ur_c_3_real_fts`, unified-retrieval,
p0-memory-relevance и vmq-retrieval наборы — **352 passed**.

## 4. Мутации (включая настоящий R1-порог)

`raw/corrective/mutations.json` — 15 вариантов, **15/15 убиты**:

| ID | Мутация | Убивший тест |
|---|---|---|
| M1 | R1 убран целиком | `test_three_strict_plus_two_soft_reserves_exactly_one` |
| M2 | общий порог `PERIOD_SOFT_FALLBACK_MIN_ROWS = 1` | `test_single_weak_row_does_not_assemble_block` |
| **M2-R1** | **настоящий R1-порог `>=2 → >=1` (только R1)** | **`test_single_soft_row_does_not_reserve`** |
| M3 | R1 применён к `operative` | `test_t6_operative_keeps_only_current_year` |
| M3b | R1 применён к `explicit_year` | `test_t5_explicit_year_is_target_filter_not_calendar_quota` |
| M3c | снят фильтр целевого года | `test_2026_rows_do_not_masquerade_as_2023` + `test_t5_...` |
| M4a | резерв добавляется вместо замены слота | `test_three_strict_plus_two_soft_reserves_exactly_one` |
| M4b | `reserve_period_append` игнорирует `reserved_old` | `test_marker_wins_with_mixed_top_years` |
| M5 | безымянные строки атрибутируются субъекту | `test_unattributed_old_row_is_not_attributed` |
| M6a | календарная квота вместо R1 | `test_three_strict...` + `test_t4_yearless_pool...` |
| M6b | годовая квота читателя `limit//5 → limit` | `test_mem_time_profile::test_m1_profile_spans_periods` |
| M7 | субъектный `author_window` для «что сейчас»/`operative` | `test_operative_current_state_has_no_author_window` |
| M8a | снят bound `author_window` | `test_subject_window_is_bounded_and_multi_year` |
| M8b | снят приоритет `author_window` в `_collect_originals` | `test_originals_put_author_window_first` |
| **F1-REVERT** | возвращено замещение хвоста у `subject_scope` | **`test_subject_scope_does_not_drop_base_tail` + `test_auto_person_reaches_...`** |

## 5. Реальный снимок (read-only)

Снимок `predeploy-258257-20261127T072559Z.db`, 6 766 456 832 B, sha256
`450604f133ee790eb989c06d186a5fcc24f2709000a50596a8200e479da9a89e`
(совпал до и после прогона), чат `-1002661910336`. Прогон на трёх версиях
кода: base `9516c9125`, prev `e1c70d58f`, fixed. Raw:
`raw/corrective/snapshot-{base,prev,fixed}.json`, скрипт
`raw/corrective/probe-oldrow-f1-2.58.257.py`.

Как измерен базовый срез: векторной ноги на снимке нет (`memory=None`), поэтому
базовый фактовый канал читается лексически (`_RAG_FACT_CHANNELS` override ТОЛЬКО
в измерительном скрипте, продуктовый код не менялся). В таком режиме
лексические сообщения делят срез с фактами, поэтому базовый фактовый срез на
этом снимке — **5 строк при limit 10**, то есть класс «полный базовый срез»
реальными данными здесь не воспроизводится (честная граница, см. §6).

| Вход | base `9516c9125` | prev `e1c70d58f` | fixed |
|---|---|---|---|
| P1 `auto` | 5 базовых, доставлено 7 (2026), `author_window` нет | 5 базовых сохранены, доставлено 6, 1 периодная строка, `reserved_old=0` | **те же id, что prev**; `base_rows_dropped=0`, `subject_scope_no_replace=1`, `author_window=1` |
| P2 `auto` | 5 базовых, доставлено 7 | 5 сохранены, доставлено 6 | те же id; `base_rows_dropped=0` |
| P3 `auto` | 5 базовых, доставлено 7 | 5 сохранены, доставлено 6 | те же id; `base_rows_dropped=0` |
| A1 `historical` | 5 базовых, доставлено 7, старых 0 | 5 сохранены, доставлено 7, **1 старая (2025)**, `reserved_old=1` | те же id; `reserved_old=1`, `base_rows_dropped=0` |
| «что сейчас» P1 (`auto`, `operative`) | 5 базовых, 5–7 строк, все 2026 | 5 сохранены, все 2026, `author_window=0` | те же id; `author_window=0`, `reserved_old=0`, все 2026 |
| «что сейчас» P1/P2/P3 (периодный вход) | факты 2026:16 / 2024:5+2025:11 / 2026:16 | то же | **то же, что base** (годы совпадают), `author_window=0` |

Ключевые факты:

* `prev == fixed` по доставленным id во ВСЕХ сценариях — F1-исправление меняет
  только полный-базовый крайний случай, на этих данных поведение идентично;
* базовые строки сохранены 5/5 и их порядок не изменён (`base_prefix_preserved
  = true`) во всех версиях и сценариях;
* «что сейчас» по годам не отличается от базы `9516c9125` (P1/P3 — 2026,
  P2 — те же 2024/2025 лексические факты), `author_window=0`, `reserved_old=0`;
* A1 `historical` по-прежнему доставляет старую строку 2025 (`reserved_old=1`),
  как и в ревью.

## 6. Честные ограничения

1. Полный базовый срез (10/10) на снимке не воспроизводится: без embeddings
   фактовый срез лексической ноги ограничен 5 строками (сообщения делят
   `limit`). Класс F1 доказан точной фикстурой ревью (`8008/8009`) и новым
   тестом, а на реальных данных — идентичностью доставленных id у prev/fixed и
   `base_rows_dropped=0`.
2. Живой L1/Writer payload, второй чат и векторная нога не наблюдались —
   границы те же, что в исходном инкременте.
3. `period_skipped="auto_full_slice"` при фактически исполненном доборе —
   **F4, backlog**, в этом corrective не менялся (намеренно).

## 7. F3 — уточнение evidence (по замечанию ревью)

Описание M2 в исходном `index.md` неточно: контрактный M2 сформулирован как
«разрешить R1 без порога `>=2` soft-строк», но тест
`test_single_weak_row_does_not_assemble_block` проверяет **мягкий fallback**
(в нём нет `accepted`, поэтому R1 вообще не исполняется). Мутация общего
порога `PERIOD_SOFT_FALLBACK_MIN_ROWS` валит именно fallback-тест, а не
доказывает R1-порог. Настоящий R1-порог убивается мутацией только R1
(`>=2 → >=1`) и тестом `test_single_soft_row_does_not_reserve` — добавлено в
этот прогон как **M2-R1**. Исходный `index.md` намеренно не редактировался
(его sha256 зафиксирован ревью), уточнение живёт здесь.

## 8. Гигиена и откат

* Изменены только `services/direct_chat_service.py` (+30/−7) и
  `tests/test_vmq_oldrow_person_delivery.py` (+73/−10) относительно
  `e1c70d58f`; `mca_retrieval_context.py` не менялся в этом corrective.
* Копия снимка удалена после прогона; временные скрипты/бэкапы удалены.
* Откат: revert коммита; данных, схемы, настроек и пользовательских выборов
  не касается.

```json
{
  "artifact": "plans/features/vmq-onto-01/evidence/vmq-mem/oldrow-fix-2026-11-27/corrective-f1-2026-11-27.md",
  "artifact_kind": "builder_corrective_f1_f2",
  "role": "Builder",
  "base_commit": "9516c912554bb1062f62a63b6689f418c1cb5425",
  "previous_candidate": "e1c70d58f926ceb923594ee9bcf551e663ccb964",
  "fixed_findings": ["OLDROW-R3-BASE-01 (F1, High)", "OLDROW-TEST-CAL-01 (F2, Low)"],
  "backlog_untouched": ["OLDROW-EVID-M2-01 (F3)", "OLDROW-OBS-01 (F4)"],
  "f1": {
    "mechanism": "subject_scope period contribution uses extra capacity limit + limit//5; base rows passed whole, never trimmed; replacement path unchanged for historical/plan/thin",
    "trace": ["base_rows_dropped", "subject_scope_no_replace"],
    "fixture_prev_ids": [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 9100, 9201],
    "fixture_fixed_ids": [8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009, 9100, 9201],
    "prev_missing_base": [8008, 8009],
    "fixed_missing_base": []
  },
  "f2": {
    "seed_years": "_completed_years() = range(current_year - 3, current_year)",
    "new_test": "test_subject_window_uses_reader_default_window"
  },
  "tests": {
    "new_file_total": 19,
    "fixed": "19 passed",
    "prev_e1c70d58f": "2 failed / 17 passed (both F1)",
    "base_9516c9125": "12 failed / 7 passed",
    "impacted_fixed": "211 passed / 4 failed",
    "preexisting_failures": [
      "tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year",
      "tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_historical_plan_rebuilds_block_with_plan_scope",
      "tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_operative_plan_narrows_block",
      "tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_t16_research_plan_rebuilds_rag_block"
    ],
    "broader": "352 passed"
  },
  "mutations": {"applied": 15, "killed": 15},
  "snapshot": {
    "sha256": "450604f133ee790eb989c06d186a5fcc24f2709000a50596a8200e479da9a89e",
    "bytes": 6766456832,
    "chat_id": -1002661910336,
    "base_rows_on_snapshot": 5,
    "base_slice_full_reproducible": false,
    "prev_vs_fixed_delivered_ids_identical": true,
    "base_rows_preserved": "5/5, prefix order preserved, base_rows_dropped=0",
    "current_state_unchanged_vs_base": true
  },
  "rollback": "revert code only"
}
```
