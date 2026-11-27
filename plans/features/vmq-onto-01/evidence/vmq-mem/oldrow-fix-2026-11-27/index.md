# P-OLDROW — реализация и доказательства (Builder, 2026-11-27)

Роль: Builder. База: deployed `9516c912554bb1062f62a63b6689f418c1cb5425` (2.58.257).
Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/selector-rootcause-2026-11-27.md`,
sha256 `bcce78bb31cec83f703031270af3a52ec2eb30a9a7421e726e45f0297b2e50fc`
(проверен `Get-FileHash` перед началом).

Ветка: `fix/vmq-oldrow`, worktree
`WorkspaceData/worktrees/c742e4de9e92c489/vmq-oldrow-fix-d6038546e10e-5a0fd4ae`.
Деплоя, рестартов, изменений карт/`progress_scope.json`/настроек прода и
сообщений в Telegram не было. Снимок БД читался только `mode=ro&immutable=1`
+ `PRAGMA query_only=ON`.

## 0. Что изменено

| Точка | Файл | Что сделано |
|---|---|---|
| R1 селектор | `services/mca_retrieval_context.py:1026` (`select_period_rows`) | после строгого отбора и мягкого fallback: одна soft-строка с годом СТРОГО старше минимального принятого ставится в первые `slots` (append при `len(accepted) < slots`, иначе замена `accepted[slots-1]`), помечается `reserved_old=True`; stats `reserved_old`/`reserved_displaced`; при переданных `subject_uids`/`subject_names` — только subject-bound по `subject_ref_id`/`speaker_author_id`/`target_user`; `dropped_subject` уменьшается на добавленную, замена soft-строки уменьшает `soft_fallback`; `historical_quota`/`multi_year_quota` остаются 0; для `none`/`operative`/`explicit_year` ветка не исполняется |
| R1 добор | `services/mca_retrieval_context.py:1310` (`reserve_period_append`) | помеченная строка доезжает и при смешанных годах верхних слотов: занимает последний слот бюджета; если уже в `selected` — срез не меняется; бюджет не растёт |
| R2 author_window | `services/mca_retrieval_context.py` (`retrieve`, канал `author_window`) | разрешён при `author_entity_ids` **или** `subject_entity_ids`; читает `get_author_message_periods` по точному uid (явный автор сильнее субъекта); `author_entity_ids` в запрос не выставляется → FTS-фильтр фактов не меняется |
| R2 окно | `services/mca_retrieval_context.py:737` (`_author_window_bounds`) | без явного года/диапазона при субъекте и `period_intent.wants_year_diverse` — существующее дефолтное окно читателя (три последних завершённых года), без нового списка годов |
| R2 bound/приоритет | `services/mca_retrieval_context.py:810` (`_author_window_bounded`), `services/direct_chat_service.py:17927` (`_collect_originals`) | субъектное окно: `limit // 5` строк на год и столько же всего, распределение по годам по кругу от старшего; в `_collect_originals` сообщения `author_window` идут первыми (стабильная партиция, cap 12 сохранён) |
| R3 intent | `services/mca_retrieval_context.py:609` (`resolve_period_intent`) | аддитивные `subject_present`/`current_state`; разрешённый не-«сейчас» субъект → `multi_year`/`source=subject_scope`; `PERIOD_REPLACE_SOURCES` не расширялся (`period_replace_allowed(..., "auto") is False`) |
| R3 прямой путь | `services/direct_chat_service.py:17404,17542,17671` | субъект разрешён только при имени в вопросе (тот же guard, что у профиля); `breadth_reason="subject_scope"`; тот же периодный `_rag_retrieve` получает `subject_uids`/`subject_names` и канал `author_window`; `select_period_rows` получает субъект; `_period_trace` отдаёт `reserved_old`/`reserved_displaced`/`author_window` (только числа) |

`services/tool_router.py`, схема, миграции, настройки, флаги, словари, второй
retrieval — не менялись.

Diff: `services/mca_retrieval_context.py` +266, `services/direct_chat_service.py`
+80, тесты (см. §4). 5 файлов, +360/−28.

## 1. RED/GREEN на реальном снимке (read-only)

Снимок: `predeploy-258257-20261127T072559Z.db`, 6 766 456 832 B,
sha256 `450604f133ee790eb989c06d186a5fcc24f2709000a50596a8200e479da9a89e`
— скопирован с прода read-only, hash до и после прогона совпал. Чат
`-1002661910336`. Провайдерских вызовов нет, `memory=None` (векторная нога
честно не исполнена — та же граница, что у замера `measure-2026-11-27`).

Entrypoint (как в контракте §5):
`retrieve(period_fill=True, channels=(lexical, vector, author_window),
top_k=32, memory_scope=historical|auto, subject_entity_ids=(uid,),
subject_names=(name,), period_intent=<historical|subject_scope>)` →
`select_period_rows(slots=32//5=2, subject_uids=(uid,), subject_names=(name,))` →
`reserve_period_append(budget=2)`.
Запрос: `что ты знаешь про <name>?` (имя — самый частый `author_name` автора).
Raw: `raw/red-base.json` (база `9516c9125`), `raw/green-candidate.json`
(кандидат); протокол версии кода записан полем `versions` (сигнатуры
`resolve_period_intent`/`select_period_rows` отличаются базой и кандидатом).

### 1.1 До/после по людям

| Автор | Старых сообщений (SQL) | База: `author_window` | База: старых своих сообщений | База: intent (auto) | Кандидат: `author_window` | Кандидат: старых своих сообщений | Кандидат: годы |
|---|---|---|---|---|---|---|---|
| P1 `485008070` | 61 803 | не исполнен (нет поля) | 0 | `none` | исполнен | **6** | 2023:2, 2024:2, 2025:2 |
| P2 `138811255` | 146 755 | не исполнен | 0 | `none` | исполнен | **6** | 2024:3, 2025:3 |
| P3 `1313107079` | 81 180 | не исполнен | 0 | `none` | исполнен | **6** | 2023:2, 2024:2, 2025:2 |

Кандидат: `period_fill.author_window_rows = 6` = `32//5` (≤12 cap), годы
распределены по кругу, каждый год ≤ `limit//5`; контрактные «2/год» — та же
формула при `limit=12` (`12//5=2`), на entrypoint с `top_k=32` она даёт 6 на
три года. `intent` в `auto` = `multi_year/subject_scope`,
`period_replace_allowed(...)` = 0 (право замещать срез не появилось).

Контроль «что сейчас» (`что сейчас происходит?`, те же субъекты,
`auto` и `operative`): `author_window = 0`/`None`, `reserved_old = 0`,
факты только 2026 — и на базе, и на кандидате.

### 1.2 A1 `historical` (выдуманный/исторический вопрос, без субъекта)

| Метрика | База `9516c9125` | Кандидат |
|---|---|---|
| пул | 16 (2026:15, 2025:1) | 16 (2026:15, 2025:1) |
| `kept` | 3 | 3 |
| `accepted` годы | [2026, 2026, 2026] | [2026, **2025**, 2026] |
| `reserved_old` | нет поля (0) | **1** |
| `reserved_displaced` | нет поля (0) | **1** |
| `soft_fallback` | 0 | 0 |
| `dropped_subject` | 13 | 12 (−1 за добавленную) |
| `pool_expired` | 2 | 2 |
| `historical_quota`/`multi_year_quota` | 0/0 | 0/0 |
| доставлено в бюджет 2 | [2026, 2026] | [2026, **2025**] |
| покрытие периодного вклада (`{2022..2026}`) | **0.20** | **0.40** |

A1P `historical` — база и кандидат уже доставляли 2025 строгим путём
(`kept=7`, покрытие 0.40); `reserved_old=0` в обоих — резерв не нужен, это
честный контроль отсутствия лишнего вмешательства.

### 1.3 Побочный эффект, который нужно знать

`author_window` — канал ТОГО ЖЕ `retrieve`: 6 сообщений занимают 6 из 32
слотов пула, поэтому лексическая нога отдаёт меньше строк фактов.
Измерено для P1 (`raw/pool-shape-p1.json`): кандидат `fact_rows=16 → 13`
(уходят 2×2026 и единственная 2025-строка, которая и в базе отбрасывалась
как нерелевантная). Для A1 (нет субъекта, канала нет) пул не меняется
(16). Базовый срез ответа (`_RAG_FACT_CHANNELS`) не затрагивается.

## 2. Тесты

Новый файл `tests/test_vmq_oldrow_person_delivery.py` (17 тестов,
`TEST-LIFECYCLE: CONTRACT owner=VMQ-ONTO-01/vmq-mem P-OLDROW`):

* R1: 3 строгих 2026 + 2 мягких старых, `slots=2` → ровно одна помеченная
  старшая строка в первых слотах, `len(accepted)` не вырос, квоты 0;
* R1 bound: `reserve_period_append` при смешанных годах доставляет
  помеченную, если она уже в бюджете — не трогает, без пометки — прежнее
  правило MEM-07;
* контроль §2: одна мягкая строка блок не собирает;
* M5: безымянная (`unattributed`) старая строка НЕ атрибутируется, а та же
  строка с точным `speaker_author_id` — атрибутируется;
* M3: явный год и `operative` не получают резерв; `none` — не получает;
* R3: `multi_year/subject_scope`, `period_replace_allowed=False`, «что
  сейчас»/`operative` — `none`; end-to-end `auto` + полный срез + субъект:
  `breadth_reason="subject_scope"`, `replace_allowed=0`, старый год
  доставлен, длина среза не выросла, первая базовая строка на месте; без
  разрешённого субъекта `auto` по-прежнему `auto_full_slice` и один вызов;
* R2: субъектное окно ограничено и много-летне (3 года, ≤ `top_k//5`);
  `operative`/«что сейчас» не читает старые сообщения (spy на
  `get_author_message_periods` — 0 вызовов); `_collect_originals` ставит
  `author_window` первыми при 15 лексических кандидатах;
* e2e `historical`: старый subject-bound ряд доезжает до среза как
  `period_fill`, `soft_fallback=0`.

RED/GREEN: `raw/pytest-base-9516c9125-new-tests.txt` —
**10 failed / 7 passed** на базе; `raw/pytest-candidate-new-tests.txt` —
**17 passed** на кандидате. 7 проходящих на базе — контроли («одна слабая
строка», explicit/operative/none, `reserve` без пометки, `auto` без
субъекта, «что сейчас» не платит периодный вызов).

Затронутые наборы (`raw/pytest-candidate-impacted.txt`,
`raw/pytest-base-9516c9125-impacted.txt`): `test_vmq_mem_period_intent`,
`test_vmq_mem07_oldrow_reservation`, `test_vmq_mem_slice_b`,
`test_vmq_mem_slice_c`, `test_vmq_mem_slice_d`, `test_p0_memory_relevance_r1`,
`test_mem_time_profile`, `test_mem_time_policy`, `test_mem_time_asof`,
`test_mem_time_l1_scope`, `test_mem_time_natural_scenarios` —
кандидат: **211 passed, 4 failed**, и те же 4 падают на базе с её исходными
тестами, то есть предсуществующие:

1. `tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year`
   (на базе `len(accepted)=4 > 2`: 4 строгих строки не ограничиваются слотами;
   к R1 отношения не имеет)
2. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_historical_plan_rebuilds_block_with_plan_scope`
3. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_operative_plan_narrows_block`
4. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_t16_research_plan_rebuilds_rag_block`
   (2–4: двойник `fake_build` не принимает существующий `author_uid`)

Обновлены три существующих ожидания — каждое с явной ссылкой на контракт,
без удаления тестов и без ослабления защищаемого инварианта:

* `tests/test_vmq_mem_slice_b.py::test_strict_row_is_not_diluted_by_weak_old_year`:
  строгая 2024 остаётся первой, добавляется ровно одна старшая (2023), строка
  без общей основы не добавляется, квоты 0 (по R1);
* `tests/test_vmq_mem_slice_d.py::test_a1p_historical_vs_auto`: состав
  `2026:8 + 2024:1 + 2023:1` (R1), `reserved_old=1`, `soft_fallback=0`,
  `historical_quota=0`; контроль `auto` не изменён;
* `tests/test_mem_time_policy.py::test_historical_adds_period_channels_and_profile`:
  периодный вызов у субъекта теперь содержит канал `author_window` (R2).

`test_strict_match_is_not_replaced_by_fallback` и
`test_single_weak_row_does_not_assemble_block` остались зелёными.

Дополнительно (затронутые общим изменением `_collect_originals` /
`_rag_unified_rows`): `tests/test_direct_chat.py`,
`tests/test_ur_c_3_real_fts.py` — **171 passed**;
`test_memory_unified_retrieval`, `test_memory_unified_retrieval_06`,
`test_p0_memory_relevance`, `test_p0_memory_relevance_r2`,
`test_vmq_mem_retrieval_fixes`, `test_vmq_mem_rc3_period_slots`,
`test_memory_period_vector_leg`,
`test_mca18_memory_subject_block_b_round1042`, `test_memory_attribution`,
`test_mca07_retrieval_context_round1027` — **245 passed** (предсуществующее
предупреждение `closed N leaked aiosqlite connection(s)` в конце прогона,
к падениям не относится).

## 3. Мутации контракта (M1–M8)

Каждая мутация вносилась в кандидата, прогонялся предназначенный тест,
файл восстанавливался байт-в-байт. Raw: `raw/mutations.json`
(13 вариантов, все убиты).

| ID | Мутация | Убивший тест |
|---|---|---|
| M1 | R1 убран целиком | `test_three_strict_plus_two_soft_reserves_exactly_one` |
| M2 | порог `>=2` soft-строк снят (`PERIOD_SOFT_FALLBACK_MIN_ROWS=1`) | `test_vmq_mem_period_intent::test_single_weak_row_does_not_assemble_block` |
| M3 | R1 применён к `operative` | `test_t6_operative_keeps_only_current_year` |
| M3b | R1 применён к `explicit_year` | `test_t5_explicit_year_is_target_filter_not_calendar_quota` |
| M3c | снят фильтр целевого года явного года | `test_2026_rows_do_not_masquerade_as_2023` + `test_t5_...` |
| M4a | резерв добавляется вместо замены слота (длина растёт) | `test_three_strict_plus_two_soft_reserves_exactly_one` |
| M4b | `reserve_period_append` игнорирует `reserved_old` | `test_marker_wins_with_mixed_top_years` |
| M5 | безымянные строки атрибутируются субъекту | `test_unattributed_old_row_is_not_attributed` |
| M6a | календарная квота `historical_quota` поднята вместо R1 | `test_three_strict...` + `test_t4_yearless_pool_keeps_relevant_year_including_current` |
| M6b | годовая квота читателя `limit//5 → limit` (`database.py`) | `test_mem_time_profile::test_m1_profile_spans_periods` |
| M7 | субъектный `author_window` включён для «что сейчас»/`operative` | `test_operative_current_state_has_no_author_window` |
| M8a | снят bound `author_window` | `test_subject_window_is_bounded_and_multi_year` |
| M8b | снят приоритет `author_window` в `_collect_originals` | `test_originals_put_author_window_first` |

Итог: **13/13 убиты**; M3 покрыт двумя вариантами (operative и
explicit_year), потому что одна ветка не может затронуть оба интента.

## 4. Конфигурация / effective state / откат

* Флагов, настроек, env/per-chat override, схемы и миграций нет. Заводское
  поведение: `historical`/`multi_year` и разрешённый субъект получают
  старший период; `operative`, «что сейчас» и явный год — прежние.
* Замедление: один и тот же периодный вызов (второго retrieval нет); пул 32,
  бюджет `limit//5`.
* Наблюдаемость: `period_fill.author_window/author_window_rows/
  author_window_years`, `_rag_period_stats` и durable `_period_trace`
  получают `reserved_old`, `reserved_displaced`, `author_window`,
  `author_window_rows` — только числа, без текстов/имён.
* Откат: revert коммита; данных, схемы и пользовательских выборов не
  касается.

## 5. Честные ограничения этого прохода

1. Векторная нога не исполнена (`memory=None`): вклад KNN в пул и базовый
   срез не измерялись; R1/R2 работают на лексике и точном uid.
2. Живой L1 `memory_scope`/`response_act` и финальный Writer payload не
   наблюдались: `auto`/`historical` — управляемый вход. Второй чат не
   проверялся (один чат, один снимок).
3. Безымянные `history_import`-факты о третьем лице старших лет остаются
   названным остатком (`person-question-decision.md` §3); правило их не
   атрибутирует.
4. На базе лексический путь уже доставлял отдельные старые ФАКТЫ для
   P2/P3; доказанный дефект этого прохода — 0 собственных старых сообщений
   (`author_window` не исполнялся) и `auto` без периодного вызова; селекторный
   резерв проверен на A1 (`reserved_old=1`, покрытие 0.20 → 0.40) и
   синтетическими тестами.
5. `MEM-04` не переоткрывался; `MEM-07` остаётся `partial` до независимого
   пяти-классового сравнения; `TIME-07` требует перемера на кандидате.

```json
{
  "artifact": "plans/features/vmq-onto-01/evidence/vmq-mem/oldrow-fix-2026-11-27/index.md",
  "artifact_kind": "builder_implementation_and_red_green",
  "created_utc": "2026-11-27",
  "role": "Builder",
  "base_commit": "9516c912554bb1062f62a63b6689f418c1cb5425",
  "base_version": "2.58.257",
  "contract": "plans/features/vmq-onto-01/evidence/vmq-mem/selector-rootcause-2026-11-27.md",
  "contract_sha256": "bcce78bb31cec83f703031270af3a52ec2eb30a9a7421e726e45f0297b2e50fc",
  "branch": "fix/vmq-oldrow",
  "changed": {
    "services/mca_retrieval_context.py": ["resolve_period_intent", "_author_window_bounds", "_author_window_bounded", "_row_year", "_row_subject_bound", "select_period_rows", "reserve_period_append", "retrieve.author_window", "period_usage.author_window"],
    "services/direct_chat_service.py": ["_rag_unified_rows.subject_scope", "_rag_period_stats.reserved_old", "_period_trace", "_collect_originals", "_rag_retrieve.subject_uids"],
    "tests/test_vmq_oldrow_person_delivery.py": "new (17 tests)",
    "tests/test_vmq_mem_slice_b.py": "expectation updated with contract ref",
    "tests/test_vmq_mem_slice_d.py": "expectation updated with contract ref",
    "tests/test_mem_time_policy.py": "expectation updated with contract ref"
  },
  "not_changed": ["services/tool_router.py", "schema/migrations", "settings/flags", "plans/progress_scope.json"],
  "red_green_snapshot": {
    "path": "predeploy-258257-20261127T072559Z.db",
    "bytes": 6766456832,
    "sha256": "450604f133ee790eb989c06d186a5fcc24f2709000a50596a8200e479da9a89e",
    "chat_id": -1002661910336,
    "red_base": {
      "person_old_author_messages": {"P1": 0, "P2": 0, "P3": 0},
      "author_window_executed": false,
      "auto_intent": "none",
      "a1_accepted_years": [2026, 2026, 2026],
      "a1_dropped_subject": 13,
      "a1_pool_expired": 2,
      "a1_reserved_old": 0,
      "a1_coverage": 0.2
    },
    "green_candidate": {
      "person_old_author_messages": {"P1": 6, "P2": 6, "P3": 6},
      "person_years": {"P1": {"2023": 2, "2024": 2, "2025": 2}, "P2": {"2024": 3, "2025": 3}, "P3": {"2023": 2, "2024": 2, "2025": 2}},
      "author_window_rows": 6,
      "author_window_bound": "limit//5 = 32//5 = 6, <= 12 collect cap",
      "auto_intent": "multi_year/subject_scope",
      "period_replace_allowed_auto": false,
      "a1_accepted_years": [2026, 2025, 2026],
      "a1_reserved_old": 1,
      "a1_reserved_displaced": 1,
      "a1_dropped_subject": 12,
      "a1_coverage": 0.4,
      "current_state_control": {"author_window": 0, "reserved_old": 0, "years": [2026]}
    },
    "side_effect": "author_window takes 6 of 32 pool slots: P1 fact_rows 16 -> 13 (2x2026 and the unbound 2025 row that base also dropped); A1 pool unchanged (no subject)."
  },
  "tests": {
    "new_file": "tests/test_vmq_oldrow_person_delivery.py",
    "new_tests_base": "10 failed / 7 passed",
    "new_tests_candidate": "17 passed",
    "impacted_candidate": "211 passed / 4 failed",
    "preexisting_failures": [
      "tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year",
      "tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_historical_plan_rebuilds_block_with_plan_scope",
      "tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_operative_plan_narrows_block",
      "tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::test_t16_research_plan_rebuilds_rag_block"
    ]
  },
  "mutations": {"applied": 13, "killed": 13, "contract_ids": ["M1", "M2", "M3", "M3b", "M3c", "M4a", "M4b", "M5", "M6a", "M6b", "M7", "M8a", "M8b"]},
  "parks": [
    "vector leg not executed (memory=None)",
    "live L1/Writer payload not observed",
    "second chat not tested",
    "unattributed third-person facts remain named residual",
    "MEM-04 not reopened; MEM-07 partial; TIME-07 needs re-measure on candidate"
  ],
  "rollback": "revert code only; no schema/data/settings change"
}
```
