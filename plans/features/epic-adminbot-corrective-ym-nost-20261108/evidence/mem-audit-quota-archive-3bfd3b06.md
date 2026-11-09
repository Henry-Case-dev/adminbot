# MEM-AUDIT: квота больше не стирает историю — архивное вытеснение (кандидат 3bfd3b06)

Статус: **кандидат проверен независимым Reviewer (Approved), production runtime НЕ проверен.**
Дата привязки: 2026-11-08.

## 1. Источник требования

| Требование | Источник | Строка |
|---|---|---|
| `MEM-04.6` «Старое, редкое, „забытое“ воспоминание **не стирать** ради квот. Управлять hot-context вероятностью вызова…, оставляя архивный поиск и явное историческое извлечение. Действующие пользовательские delete/forget и security retention policies — исключение, не обходить их.» | `plans/owner_inputs/2026-11-07-epic-memory-cognitive-02.md` | 118 |
| `SRC-0792` (MEM-AUDIT п.3) «Если C подтверждён: дать минимальный защитный фикс в существующем контуре, чтобы **прекратить последующие необратимые удаления**, не ломая явные delete/forget, privacy и дисковую безопасность. Не делать немедленного массового переписывания истории, отката всей БД, рекомпиляции эмбеддингов, второго архива или „восстановления“ без проверенного source provenance.» | `plans/features/epic-adminbot-corrective-ym-nost-20261108/source-2026-11-08.md` | 792 |
| Контекст MEM-AUDIT (п.1–п.5) | там же | 784–796 |

## 2. Дефект (доказательство случая C до фикса)

`plans/features/memory-cognitive-02/audit-a0.md`, строка 35 (sha256 файла
`789bc927c273c1a64d99e5289a73a46b2fc2e024e5e575841d75bcf6a08762c9`):

> `_enforce_user_quota` → `get_quota_victim` → `self.db.delete_graph_fact(victim["id"])` → `log_fact_compression(..., 'quota')`

`DatabaseService.delete_graph_fact` физически удаляет `graph_facts_fts` → `graph_facts_vec` → `graph_facts`
(см. аудит, строка 75 того же файла). То есть вытеснение по квоте было необратимым `DELETE` факта,
FTS- и vec-строк — это случай **C** по классификации MEM-AUDIT, противоречащий `MEM-04.6`/`INV-01`.
Наблюдаемый симптом из отчёта («квота пока удаляет старые факты») подтверждён кодом, а не только формулировкой.

## 3. Замороженный контракт (реализован кандидатом)

1. `DatabaseService.archive_graph_fact_for_quota(fact_id, chat_id, target_user) -> bool`:
   один `write_transaction`, условный `UPDATE graph_facts SET status='archived_fact'
   WHERE id=? AND chat_id=? AND target_user IS ? AND status='confirmed'` (NULL-safe скоуп)
   + **ровно одна** строка `graph_fact_compressions` (`reason='quota'`, `fact_before` = текущий текст,
   `fact_after=NULL`) в той же транзакции.
2. Возврат `True` только на реальном переходе `confirmed → archived_fact`; повторный вызов/чужая область
   (id+chat+user)/отсутствующий факт → `False` **без второго журнала**; сбой журнала → rollback статуса.
3. Ничего не удаляется физически: строка `graph_facts`, FTS-строка, vec-строка и provenance остаются.
4. `get_quota_victim` считает и выбирает **только** `status='confirmed'` (архив не занимает квоту и не выбирается повторно).
5. Обычная выдача (`include_archived=False`) `archived_fact` не видит: FTS-путь `search_graph_facts_fts`
   и KNN/context-путь `_search_graph_facts`/`_knn_graph_facts` используют live-набор
   (`confirmed`, `archived_belief`).
6. Историческое извлечение (`include_archived=True`, напр. `dig_into_lore`) возвращает `archived_fact`
   (тот же id/текст), с архивным пенальти ниже живых; `tool_router.dig_into_lore` помечает «(архивный факт)».
7. Разрушающими остаются только явные delete/forget/privacy/retention (`delete_graph_fact`, `user_forget`);
   `_enforce_user_quota` больше не вызывает `delete_graph_fact`; массового переписывания истории,
   отката БД и рекомпиляции эмбеддингов нет (диff — только quota-путь, чтение, метка и тесты).
8. `count_overdue_facts` не считает `archived_fact` просроченным.

## 4. Кандидат

- Commit: `3bfd3b063b2cb9b26c0191da103319d18d2ffa8d` (ветка `integ/unify-release`), parent `d022d030`.
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\6f4c07e43141f379\hotfix-meme-publication-initia-d78f499866ee-6ef91e44`.
- Изменённые файлы (diff `d022d030..3bfd3b06`, 6 файлов, +361/−38):
  - `services/database.py` — `archive_graph_fact_for_quota`, live-only `get_quota_victim`,
    `search_graph_facts_fts(include_archived)`, `count_overdue_facts`;
  - `services/summary_memory.py` — `_enforce_user_quota` через архивирование,
    `_fact_statuses`/live-набор, KNN+FTS архивный режим, пенальти `archived_fact`;
  - `services/tool_router.py` — метка «(архивный факт)» в `dig_into_lore`;
  - `tests/test_graphrag_database.py` (+148), `tests/test_graphrag_memory.py`, `tests/test_asap8_v63_b03_memory.py` (+51).

## 5. Независимое ревью (три опоры, Approved)

1. **Реализация/контракт:** Reviewer лично инспектировал архивный путь `services/database.py`
   (`archive_graph_fact_for_quota`, журнал, FTS-статусы) и quota-путь `services/summary_memory.py`
   (`_enforce_user_quota`), а не только отчёт Builder.
2. **Валидность тестов:** проверены сами утверждения — DB-уровневый `COUNT(*)` строк журнала
   (не мок), реальный `RAISE(ABORT)`-триггер на журнале для rollback, отдельный тест, доказывающий,
   что явное забывание остаётся физически разрушающим; негативные кейсы (чужой скоуп, отсутствующий факт, повтор).
3. **Независимая попытка опровержения:** Reviewer прогнал 3 focused-теста и собственные сценарии:
   обычный FTS не возвращает `archived_fact`; `include_archived=True` вернул тот же id/текст;
   повторное архивирование → `False` при `COUNT` журнала = 1; индуцированный сбой журнала оставил
   `status='confirmed'` и `COUNT` журнала = 0.

Вердикт: **Approved**, кандидат связан с commit `3bfd3b06`.

## 6. Прогоны тестов (кандидат 3bfd3b06)

```
python -m pytest tests/test_graphrag_database.py tests/test_graphrag_memory.py \
    tests/test_asap8_v63_b03_memory.py -q
249 passed in 23.70s
```

Тот же набор наблюдал Reviewer; повторный прогон PM на кандидате дал тот же результат (249 passed).
Новые тесты контракта: `TestQuotaArchive` — `test_archive_keeps_rows_and_writes_single_journal`,
`test_second_archive_is_false_without_second_journal`, `test_scope_mismatch_changes_nothing`,
`test_missing_fact_is_false_without_journal`, `test_journal_failure_rolls_back_status`,
`test_quota_victim_counts_only_live_confirmed`, `test_archived_fact_invisible_to_ordinary_fts`,
`test_explicit_forget_still_physically_deletes`; в `test_asap8_v63_b03_memory.py` —
`test_archived_fact_hidden_from_knn_unless_archival`.

## 7. Честная граница UNVERIFIED (production/runtime)

Ни один из пунктов ниже этим кандидатом **не** доказан и остаётся `PENDING`/`UNVERIFIED`:

- развёртывание и реальные production-данные: кандидат не задеплоен, фактические `graph_facts`/
  `graph_facts_fts`/`graph_facts_vec` на проде не инспектированы, before/after по реальным записям не снят;
- ретенция **после restart** процесса/сервера (MEM-AUDIT п.4) и поведение фоновых worker/sleep/summary-циклов
  в runtime не проверялись;
- производительность и рост диска от накопления `archived_fact` (квота больше не уменьшает число строк)
  на реальном объёме не измерялись; штатный retention остаётся отдельным механизмом и здесь не перепроверялся;
- полный read-only trace **всех** quota/retention путей (включая не-квотные `invalidate_graph_fact`/TTL,
  retention cleanup, merge/review) и классификация A/B/C/D по ним этим кандидатом не оформлены —
  строки `SRC-0790`/`SRC-0791` остаются `PENDING`;
- формулировка внешнего отчёта и снятие аларма (MEM-AUDIT п.5, `SRC-0794`) — коммуникационное действие,
  в кандидате отсутствует, статус `PENDING`.

## 8. Побочное (pre-existing, не блокирует)

`tests/test_evol014_meme_initiative.py`: 2 падения (`test_fresh_db_migrates_to_v41_with_quota_and_claim_tables`,
`test_v39_db_upgrades_to_v40_without_data_loss`) — тесты ожидают `user_version == 42`, тогда как актуальная
схема = 43 (`entity_resolver`, присутствует уже в base `d022d030`). Файл кандидатом не изменён
(blob `9e562045155e92fce1d7850a2810f2d0ca6d7993` совпадает в base и в кандидате).
Зафиксировано один раз в `plans/backlog.md` как test-maintenance.
