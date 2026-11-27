D1 (VMQ-MEM-07, five-class 2026-11-28): потеря уже принятой period_fill-строки на профильном шаге

Дата: 2026-11-28. Роль: Builder-lane. **Это не вердикт Reviewer и не approval.**

## 0. Идентичность

| Что | Значение |
|---|---|
| База | `1defb4e05fc3ed5cd1566b46af4eac0abd73a814` — выложенный 2.58.259 |
| Ветка / worktree | `fix/vmq-period-fill-loss` / `WorkspaceData/worktrees/.../vmq-onto-01-3689dd92710d-a43b0a38` |
| Кандидат | `c92307c2e308ed610cbc2ccdc985a175d44e619c`, tree `628594770a0b969284770ea093570ebbb7ac8b3d` |
| Tip ветки на момент сдачи | `68b1a9802` — аддитивный evidence-коммит параллельной Builder-lane поверх `c92307c2e`; исходники не менялись |
| Изменённые файлы | `services/direct_chat_service.py` (+11/−2), `tests/test_vmq_mem_slice_d.py` (+67) |
| Хэши кандидата | `direct_chat_service.py` = `389AAE2DE05F7721C7086A436AE1F9EC72A1667E24172BE4C3B40933F0CEFCA8`; `test_vmq_mem_slice_d.py` = `B42048BB560C12EC47CCCF9E27D0EC8113CA5690CFC9015FD162EBCA4F173440` |
| `services/mca_retrieval_context.py` | **не изменён** (0 diff), `reserve_period_append` не тронут |
| Входные данные | синтетическая фикстура в `:memory:` БД; сеть/LLM/embed/rerank — 0 вызовов |

## 1. Причина (точное место)

`services/direct_chat_service.py`, `DirectChatService._rag_append_profile_rows`
(в базе 1defb4e05 строки 18226–18231):

```python
bound = any(row.get("subject_role") or row.get("authored_by_subject")
            for row in profile_rows)
if allow_replace and bound:                      # ← удаление ДО origin-отбора
    rows = [row for row in rows
            if not (isinstance(row, dict) and row.get("period_fill"))]
return self._rag_append_period_rows(rows, profile_rows, limit)   # origin-фильтр ЗДЕСЬ
```

Origin-фильтр живёт ниже, в `_rag_append_period_rows` (строка 18120:
`if _prov.is_self_referential_origin(row.get("origin")): continue`). Поэтому:

1. `bound=True` (профиль вернул субъектные строки) удаляет **все** уже принятые
   `period_fill`-строки, включая единственную старшую;
2. только потом профильные строки проверяются на origin;
3. профиль, целиком состоящий из прошлых ответов бота (`bot_direct_reply`),
   отбрасывается целиком → добавляется 0 строк.

Итог на реальном архиве (evidence `five-class-2026-11-28`, sha `1b2ae3e7…`):
8 base + принятые `[30709 (2026), 5567 (2025)]` → после профильного шага 8 строк,
обе принятые потеряны, `5567` — единственный доставленный факт 2025.

Место продукта: дефект находится **не** в `services/mca_retrieval_context.py`
(этот модуль на данном пути не исполняется; его `select_period_rows`/
`reserve_period_append` корректны и не менялись), а в вызывающем профильном шаге
direct-пути. Поэтому исправление — в `direct_chat_service.py`; иных мест, где
порядок операций можно исправить, в дереве нет (проверено `git grep`).

## 2. Исправление (причина, не симптом)

```python
admissible = [row for row in profile_rows
              if not _prov.is_self_referential_origin(row.get("origin"))]
if allow_replace and bound and admissible:
    rows = [row for row in rows
            if not (isinstance(row, dict) and row.get("period_fill"))]
return self._rag_append_period_rows(rows, admissible, limit)
```

* origin-отбор выполняется **первым**; замена `period_fill` происходит только
  если после него остался хотя бы один допустимый профильный кандидат;
* профиль, состоящий только из выводов бота, больше не уничтожает периодный
  добор: удалять нечем — строки остаются;
* сохранены: `allow_replace` (auto/operative не заменяют), `bound`
  (профиль без субъектной привязки не заменяет), замена только `period_fill`
  (базовый срез не вытесняется), `subject_scope_no_replace` и квоты
  (`_rag_append_period_rows`: `id`-дедуп, бюджет слотов, `len(rows) >= limit`);
* `select_period_rows`/`reserve_period_append` не тронуты → поведение
  VMQ-TIME-01/02 и P-OLDROW-резерва не меняется по построению.

## 3. RED → GREEN (детерминированная фикстура, без сети/LLM)

Новые тесты в `tests/test_vmq_mem_slice_d.py`, класс `TestSubjectHalf`:

* `test_bot_origin_profile_keeps_accepted_old_period_row` — D1-инвариант
  (RED на базе, GREEN на кандидате);
* `test_admissible_profile_replaces_period_row_but_not_base` — дифференциальный
  контроль: тот же профиль с нейтральным `origin` вытесняет только
  `period_fill`, база цела (зелёный и до, и после).

Фикстура = архивный случай: base 8 строк 2026 → принята строка 2025
(`id 5567`, `period_fill=True`) → профильные чтения (`get_user_context_facts`,
`get_subject_profile_facts`) возвращают только `bot_direct_reply` 2026.

| Прогон | Команда | Результат |
|---|---|---|
| RED (код 1defb4e05) | `pytest tests/test_vmq_mem_slice_d.py -k bot_origin_profile` | **1 failed** (`принятая строка старшего периода потеряна`) — `red-base-1defb4e05.txt` |
| GREEN (кандидат) | `pytest tests/test_vmq_mem_slice_d.py -k "bot_origin_profile or admissible_profile"` | **2 passed** — `green-fix-c92307c2e.txt` |

Сквозная продуктовая последовательность `probe_chain.py` (base → принятые
периодные строки → профильный шаг, реальный `DatabaseService`):

| Профиль origin | База 1defb4e05 | Кандидат |
|---|---|---|
| `bot_direct_reply` | `lost=[5567, 30709]`, итог 8 строк | `lost=[]`, итог 10 строк, база цела |
| `chat_history` (контроль) | `lost=[5567, 30709]`, `added=[11, 12]`, итог 10 | **идентично** (замена сохранена) |

Сырые выходы: `probe-base-1defb4e05.txt`, `probe-fix-c92307c2e.txt`.

## 4. Мутации (все три убиваются)

| # | Мутация | Убита |
|---|---|---|
| a | прежний порядок: `bound`-удаление до origin (код базы) | `mutation-a.txt`: `test_bot_origin_profile_keeps_accepted_old_period_row` — 1 failed, 2 passed |
| b | guard снят: профиль вытесняет базовый срез (`rows = []`) | `mutation-b.txt`: 2 failed (включая «базовый срез замещён профилем»), 1 passed |
| c | обнулён резерв старшего периода (`reserve_period_append` → `rows[:budget]`) | `mutation-c.txt`: 9 failed в `test_vmq_oldrow_person_delivery.py` / `test_vmq_mem07_oldrow_reservation.py` |

Мутации применялись к рабочему дереву ветки и снимались `git restore
--source=HEAD`; итоговое дерево = `c92307c2e` (проверено `git status`).

## 5. Регрессия

| Набор | Результат |
|---|---|
| `test_vmq_oldrow_person_delivery.py` (19 тестов) | 19 passed |
| VMQ-наборы (18 модулей: slice_b/c/d, period_intent, retrieval_fixes, rc1–rc7, m1, mem07, oldrow, recent_window, time09, voice) | 317 passed, 1 pre-existing red |
| `test_ur_c_3_real_fts.py` и unified/retrieval (22 модуля: mem_time*, unified*, ur_c*, mca07, memory_unified_retrieval*, speech_p0_rag_diag, graphrag_memory/database) | 737 passed, 3 pre-existing red |
| direct/RAG-сборка (9 модулей: history_isolation, period_vector_leg, p0_memory_relevance r1/r2, p0_embed_empty_input, memory_lookup, history_relevance, budget_global_toggle, history_w4_fixes) | 192 passed, 11 pre-existing red |

Сырые логи: `run-vmq.txt`, `run-unified.txt`, `run-dcs.txt`.

### Предсуществующие red-ы (воспроизведены на чистом 1defb4e05, не вызваны кандидатом)

1. `tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year` — ожидает `len(accepted) <= 2`, получает 4 (устаревшее ожидание «календарной квоты», снятой TIME-03 §4.2).
2. `tests/test_mem_time_l1_scope.py::TestPlanScopeReachesRagBlock::{test_historical_plan_rebuilds_block_with_plan_scope,test_operative_plan_narrows_block,test_t16_research_plan_rebuilds_rag_block}` — заглушка `fake_build()` не принимает `author_uid`.
3. `tests/test_budget_global_toggle_round1024.py::TestMasterPriority::{test_master_off_overrides_context_on,test_master_on_context_off,test_master_on_context_on}`.
4. `tests/test_history_w4_fixes.py::TestComposerOffBannerPlacement::{test_banner_on_conspect_only_in_range_lines_unlabeled,test_inrange_region_covers_all_window_lines,test_verbatim_only_global_gets_no_banner,test_no_sample_parity_no_banner,test_overflow_conspect_remainder_stays_under_banner,test_no_inrange_lines_no_boundary}`, `::TestStandardCeilingBoundaryRecount::{test_partial_trim_boundary_before_first_survivor,test_fully_trimmed_tail_emits_no_boundary}`.

Все 15 совпадают по node id на `1defb4e05` (прогон в worktree `fct-s3-2-58-259`).

## 6. Влияние на VMQ-TIME-01/02 и резерв старшего периода

* `services/mca_retrieval_context.py` не изменён → `select_period_rows`,
  `reserve_period_append`, `period_replace_allowed` работают байт-в-байт как в 2.58.259.
* TIME-01/02-покрытие (`test_vmq_mem_slice_d.py::TestSubjectHalf`,
  `test_mem_time_*`, `test_vmq_time09_turn_coverage.py`) — зелёное.
* P-OLDROW-резерв: `test_vmq_oldrow_person_delivery.py` 19/19, `test_vmq_mem07_oldrow_reservation.py` зелёный; мутация (c) показывает, что защита реально проверяется.
* Направление эффекта: только «больше сохранённых строк» в случае, когда профиль
  после origin-фильтра пуст; в остальных ветках результат идентичен прежнему.

## 7. Ограничения (честно)

1. Проверка на синтетической фикстуре и `:memory:` БД; реальный 4,7-ГБ снимок
   (`b907d4c1…`) в этом прогоне не перечитывался — «до»-состояние взято из
   существующего evidence `five-class-2026-11-28` (sha `1b2ae3e7…`), «после»
   воспроизведено детерминированной последовательностью на продуктовых функциях.
2. Векторная нога не исполнена (нет ключа эмбеддингов); путь — FTS/DB, как и в
   исходном five-class прогоне.
3. Изменение находится в `services/direct_chat_service.py`, хотя в задании
   продуктом назван `services/mca_retrieval_context.py`: в указанном модуле нет
   кода этого пути (проверено `git grep` по 1defb4e05/886d11073/1b7d43333 —
   `_rag_append_profile_rows`/`_rag_append_period_rows` определены только в
   `direct_chat_service.py`). Diff в `direct_chat_service.py` минимален
   (+11/−2 в одной функции) и не затрагивает другие вызовы.
4. Во время работы этот worktree использовался **параллельной Builder-lane** с тем же
   назначением: файл `services/direct_chat_service.py` дважды возвращался к базе
   (mtime 28.11.2026 2:46:08, длина = байтам базы), в `mca_retrieval_context.py`
   появлялась чужая строка `# MUTATION (c)`, а после моего коммита `c92307c2e`
   поверх него лёг аддитивный коммит `68b1a9802` с `builder-verification.md`
   (собственный отчёт второй lane). Собственный фикс от этого не изменился:
   хэш `direct_chat_service.py` = `389AAE…CFCA8` и на момент коммита, и после.
   Мутации двух lane применялись к одному дереву независимо, поэтому мои
   результаты фиксировались сразу после прогона и восстанавливались
   `git restore --source=HEAD`; итоговое дерево чистое (`git status`).
   **Рекомендация Orchestrator'у:** зафенсить дубликат lane; две lane сошлись на
   одном кандидате, конфликтующего кода нет, но параллельные мутации в общем
   worktree — риск ложного evidence.

## 8. Файлы

`index.md`, `red-base-1defb4e05.txt`, `green-fix-c92307c2e.txt`, `mutation-a.txt`,
`mutation-b.txt`, `mutation-c.txt`, `probe_chain.py`, `probe-base-1defb4e05.txt`,
`probe-fix-c92307c2e.txt`, `run-vmq.txt`, `run-unified.txt`, `run-dcs.txt`,
`sha256.txt`.
