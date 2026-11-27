# D1 — потеря уже принятой периодной строки при профиле из ответов бота (Builder, 2026-11-28)

Роль: Builder. Кандидат: `c92307c2e308ed610cbc2ccdc985a175d44e619c`,
tree `628594770a0b969284770ea093570ebbb7ac8b3d`, база
`1defb4e05fc3ed5cd1566b46af4eac0abd73a814` (2.58.259).
Ветка: `fix/vmq-period-fill-loss`.

## 1. Причина и точное место

`services/direct_chat_service.py:18226-18241`
(`DirectChatService._rag_append_profile_rows`).

При `bound=True` (в профиле есть subject-строки) блок удалял ВСЕ строки с
`period_fill=True` из уже собранного среза, и только затем
`_rag_append_period_rows` отбрасывал профильные строки по
`provenance.is_self_referential_origin`. Профиль, состоящий целиком из
`bot_direct_reply` (`get_user_context_facts` + `get_subject_profile_facts`),
после origin-фильтра даёт ноль допустимых строк — но принятая периодным
селектором строка (в пятиклассовом прогоне единственная строка 2025, id 5567)
к этому моменту уже уничтожена. Результат: `+0` вместо `+2`, факт 2025 года
потерян.

Исправление: origin-отбор выполняется ДО удаления (вычисляется `admissible`),
и `period_fill`-строки замещаются только если после origin-фильтра остался
хотя бы один допустимый профильный кандидат. `allow_replace`/`bound`
сохраняют прежнее значение; `base_rows_dropped=0` и
`subject_scope_no_replace=1` не затрагиваются (удаляются только
`period_fill`-строки, базовый срез не режется).

Файл `services/mca_retrieval_context.py` НЕ изменялся: наблюдаемая потеря
происходит на шаге профильного добора, уже после `select_period_rows`;
селектор, `reserve_period_append` и его резерв старшего периода не тронуты.

## 2. Тесты (обязательная пара)

`tests/test_vmq_mem_slice_d.py::TestSubjectHalf`

* `test_bot_origin_profile_keeps_accepted_old_period_row` — профильные чтения
  вернули только `bot_direct_reply`; принятая старшая периодная строка
  остаётся, новых строк не появляется, базовый срез не замещён
  (`out[:len(base)] == base`), ни одна `bot_direct_reply`-строка не доставлена.
* `test_admissible_profile_replaces_period_row_but_not_base` —
  дифференциальный контроль: тот же профиль с нейтральным origin вытесняет
  именно `period_fill`-строку, добирает материал и не трогает базу.

## 3. RED / GREEN (один и тот же запуск, только исходник)

```
py -3.12 -m pytest tests/test_vmq_mem_slice_d.py \
  -k "bot_origin_profile or admissible_profile or subject_material_replaces_generic" -q
```

* база `1defb4e05` (исходник откатан): 1 failed, 2 passed —
  `test_bot_origin_profile_keeps_accepted_old_period_row`,
  `AssertionError: принятая строка старшего периода потеряна` (строка 5567
  отсутствует в выдаче). Дифференциальный контроль на базе зелёный — тест
  падает по причине дефекта, а не из-за фикстуры.
* кандидат `c92307c2e`: 3 passed.

## 4. Мутации

| № | Мутация | Результат |
|---|---|---|
| a | прежний порядок: удалять `period_fill` при `allow_replace and bound`, добавлять `profile_rows` | FAILED `test_bot_origin_profile_keeps_accepted_old_period_row` — «принятая строка старшего периода потеряна»; 1 failed, 2 passed |
| b | убрать guard `allow_replace` (`if bound and admissible:`) | FAILED `test_subject_material_replaces_generic_period_row` на `assert generic in out2` (auto не вправе замещать period-строку); 1 failed, 2 passed |
| c | обнулить резерв старшего периода (`reserve_period_append` → ранний `return rows[:budget]`) | 9 failed, 21 passed: `test_vmq_oldrow_person_delivery.py::{TestAppendHonoursReservation::test_marker_wins_with_mixed_top_years, TestAppendHonoursReservation::test_no_marker_keeps_previous_behaviour, TestSubjectScopeIntent::test_auto_person_reaches_old_row_without_replacing_base, TestSubjectScopeIntent::test_subject_scope_does_not_drop_base_tail, TestHistoricalPersonDeliversOldRow::test_historical_person_gets_old_row_in_block}, test_vmq_mem07_oldrow_reservation.py::{TestA1HistoricalOldPeriodKept::test_a1_historical_covers_old_period, TestA1PHistoricalOldPeriodKept::test_a1p_historical_covers_old_period, TestReservationBounded::test_never_exceeds_budget_and_keeps_rank, TestReservationBounded::test_multiple_old_periods_take_one_slot}` |

После каждой мутации исходник восстановлен байт-в-байт
(`Get-FileHash` совпадает с кандидатом); `git diff HEAD` пуст.

## 5. Прогоны (кандидат `c92307c2e`)

Полный набор: все 18 `tests/test_vmq_*.py` + `test_ur_c_3_real_fts.py`,
`test_ur_c_3_live_proof.py`, `test_memory_unified_retrieval.py`,
`test_memory_unified_retrieval_06.py`,
`test_mca07_retrieval_context_round1027.py`,
`test_unified_reply_ur_b_no_topic_veto.py`,
`test_unified_reply_ur_b_review_fixes.py`,
`test_unified_reply_ur_b_search_first.py`, `test_unified_core_route_coverage.py`,
`test_ur_context_selection.py`, `test_ur_17_historical_dialog.py`:

* кандидат: **653 passed, 1 failed** (75.4 s);
* база `1defb4e05` (тот же набор, откачен только `direct_chat_service.py`):
  **652 passed, 2 failed** (65.8 s).

Разница — ровно новый тест D1. Других изменений в множестве падений нет.

Точечно на кандидате:
`tests/test_vmq_oldrow_person_delivery.py` — 19 passed;
`tests/test_vmq_mem_slice_d.py` — 43 passed (включая VMQ-TIME-01/02);
`tests/test_ur_c_3_real_fts.py` — 10 passed;
`test_vmq_mem07_oldrow_reservation.py` + `test_vmq_mem_period_intent.py` +
`test_vmq_mem_retrieval_fixes.py` — 126 passed в общем прогоне.

Влияние на VMQ-TIME-01/02: не ухудшилось — соответствующие тесты Slice D
зелёные на кандидате, поведение профиля при `allow_replace=False`
(свободные слоты) и guard `subject_scope` не менялись.

## 6. Предсуществующий red (сверен с базой)

`tests/test_vmq_mem_slice_b.py::TestHistoricalMeaningSelection::test_quota_is_bounded_by_slots_and_never_adds_current_year`
— падает ОДИНАКОВО на базе `1defb4e05` и на кандидате:
`AssertionError: assert 4 <= 2` (строка 152). Тест последний раз менялся
15.11.2026 (Slice B) и утверждает предел `len(accepted) <= slots` для строк,
прошедших строгий лексический порог; более поздние TIME-03 §3.3/P-OLDROW R1
трактуют `slots` как ресурсный предел вызывающего, а не потолок
`accepted`. К D1 не относится, кандидатом не затронут; вынесен в отчёт как
BACKLOG_ONLY, не исправлялся.

## 7. Ограничения и наблюдение о параллельной работе

* Дефект воспроизведён детерминированно на фикстуре (без сети/LLM/прод-данных);
  живой пятиклассовый прогон не повторялся.
* Во время верификации в этом же worktree другой процесс зафиксировал
  `c92307c2e` (тот же diff, `12 insertions(+), 2 deletions(-)`) и начал писать
  `run-vmq.txt`. Содержимое HEAD сверено с проверенным файлом:
  `Get-FileHash services/direct_chat_service.py` =
  `389AAE2DE05F7721C7086A436AE1F9EC72A1667E24172BE4C3B40933F0CEFCA8`,
  совпадает с проверенным состоянием. Настоящий отчёт относится именно к этому
  содержимому; чужие файлы evidence не перезаписывались.

sha256 затронутых файлов на кандидате:
`services/direct_chat_service.py` = `389AAE2DE05F7721C7086A436AE1F9EC72A1667E24172BE4C3B40933F0CEFCA8`;
`tests/test_vmq_mem_slice_d.py` = `B42048BB560C12EC47CCCF9E27D0EC8113CA5690CFC9015FD162EBCA4F173440`.
