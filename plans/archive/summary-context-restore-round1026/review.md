# review.md — S2 `summary-context-restore-round1026` (T-3245, @Reviewer)

- **Diff base:** `7895e77` (Step 4 @Builder, рабочее дерево, без коммита/деплоя).
- **Вердикт:** **Approved** (блокеров нет; live-приёмка Telegram — PENDING OWNER VERIFICATION).

## Возможности: как это работает

- **Что сделано.** Новый чистый модуль `services/summary_context_restore.py` достраивает контекст
  вокруг сохранённых S1 сообщений: reply-родители транзитивно (пример §90 `100→101→102`), проход
  сквозь бот-ответы, ограниченные соседи с каждой стороны, единая ASC-хронология `(timestamp,id)`,
  дедуп по `id`, жёсткий cap 50 и общий токенный/символьный бюджет. Врезка в
  `SummaryGenerator._apply_filter` строго между S1-фильтром и `summary_xml.build`; XML отдаётся
  `RestoreResult.kept`. Родители **вне окна** добываются async-адаптером через переиспользование
  `services/thread_chain.collect_thread_chain` (вторая цепочка не создаётся, `thread_chain.py` не изменён).
- **Почему безопасно.** Входные `kept`/`dropped` не мутируются, `kept` не удаляется никогда; любое
  усечение → `status=truncated` + `skipped_ids` + лог; ошибка → fail-open на S1-выходе; тумблер OFF →
  S2 не вызывается, поведение S1 байт-в-байт. 0 новых LLM-вызовов (2-вызовность сохранена).

## Checks performed

| Проверка | Как проверял | Результат |
|---|---|---|
| Полный pytest (.venv, Python 3.12.0) | `py -3 -m pytest -q` | **8569 passed, 1 warning, 0 failed** (baseline 8525 + 44) |
| Новые тесты S2 | оба файла отдельно | **44 passed** (34 unit + 10 integration) |
| JS-тесты | все 43 файла `node tests/js/*.js` | **43/43 OK** |
| `git diff --check` | от `7895e77` | exit 0 |
| Δ DDL | diff по `services/database.py`/миграциям | **пусто → 0** |
| Δ каталога | `test_round1025_f8_registry.py` (29 passed) + прямой подсчёт | REGISTRY 467 / GROUPS 100 / TAB_BY_GROUP 98 / TAB_RULES 21 — **Δ 0** |
| Публикация/XML/промпты вне diff | `git diff --name-only 7895e77` по `summary_xml.py`, `summary_prompts.py`, `image_generation.py`, `telegram_send.py`, `media_send.py`, `summary_filter.py`, `thread_chain.py`, `param_catalog.py`, `web/` | **пусто** |
| Версии | `settings.py` vs `README.md` | `APP_VERSION 2.58.21`, README v2.58.21 — синхронно |
| R17/R18 | тег/бэкап/stash | `pre-round1026-s2` = `8aa7b2b9` → commit `7895e77`, запушен в origin; бэкап на месте; `stash@{0}` не тронут |

## Requirement / evidence coverage

| REQ | Где подтверждено | Статус |
|---|---|---|
| §90 родители 100→101→102, вне окна, сквозь бота, ID не подменены | core `_walk_parents`; тесты `chain_100_101_102`, `parent_outside_window_via_extra_parents`, `pass_through_bot_row`, `ids_and_reply_preserved` | ✅ |
| §90 соседи с каждой стороны, хронология, дедуп | `_collect_neighbors`, финальная ASC+дедуп; `neighbors_n_both_sides`, `asc_order_and_parent_not_duplicated`, `double_run_is_identical` | ✅ |
| §91 тред/всплеск/параллельные/медиа/подписи/бот | `short_thread_fully_restored`, `burst_only_nearest`, `parallel_threads_not_merged`, `media_parent_without_text`, `previous_summary_bot_not_restored` | ✅ |
| §92 `build_l1_payload` только реальные поля, `mentions` не выдуман | `field_mapping`, `mentions_not_invented`, `authors_not_substituted`, `missing_fields_not_fabricated` | ✅ |
| §89/§93 cap 50, бюджет, «не резать молча», `kept` не удаляется | `cap_50_with_200_candidates`, `budget_truncates_additions_not_kept`, `tiny_budget_keeps_all_kept`, `char_budget_exact_fit_and_plus_one` | ✅ |
| §107/§114 дефолт ON, OFF hot, fail-open, master-тумблер как у S1 | `test_off_gate_keeps_s1_output`, `test_off_gate_no_db_touch`, `test_restore_error_falls_back_to_s1`, `test_chat_a_restores_chat_b_not` | ✅ |
| §108/§109 `restored_count`, логи `RESTORE_*` без секретов | `test_apply_filter_restored_count_matches_effective`, `test_logs_have_run_id_without_content` | ✅ |
| ровно 2 LLM-вызова | `test_exactly_two_llm_calls_with_restore` (await_count == 2) | ✅ |
| блок H NOT_APPLICABLE | Δ каталога=0 подтверждён инструментально | ✅ |

## Blocking findings

**Нет.**

## Non-blocking debt

- **[Low] Реальный проход по reply-цепочке в проде зависит от наполнения `bot_replies`.** Адаптер
  `_collect_extra_parents` ищет недостающие ходы через канонический `collect_thread_chain`, который
  резолвит бот-ход/родителя через БД `bot_replies`/`bot_reply_parents`; в тесте подана заглушка
  `FakeDb.get_bot_reply → None` (чистый обход по `smart_messages`). Сам обход переиспользован корректно,
  поэтому это фактор среды, а не дефект S2. Рекомендация: подтвердить на живом контуре в рамках
  §107/§114 (PENDING OWNER VERIFICATION).
- **[Low] Адаптер на «открытом» якоре не находит родителя, если строки-родителя нет в
  `smart_messages`.** Тогда родитель остаётся не восстановленным (fail-open, без потери `kept`).
  Ограничение наследовано от существующего хранилища; соответствует ADR-1026-4 D1.
- **[Low] `RESTORE_CHAIN_CALLS_MAX=50`** ограничивает число БД-обходов на прогон; при числе «открытых»
  якорей > 50 часть цепочек не догрузится (ядро по окну отработает). Осознанная защита от деградации,
  задокументирована в коде.

## Unavailable checks

- **Live-проверка Telegram** (прод-поведение, наполнение `bot_replies`, served `?v=2.58.21`) —
  **PENDING OWNER VERIFICATION** (§17: workflow не останавливать).
- **Deploy** (T-3250 @DevOps) не выполнялся — вне области ревью.

## Handoff

`RESULT: Approved — @Orchestrator. S2 summary-context-restore-round1026 прошла независимое QA
(8569/0 pytest, 43/43 JS, ΔDDL=0, Δкаталога=0, XML/промпты/публикация вне diff, RESTORE_* R17/R18,
0 новых LLM-вызовов). Единственный открытый пункт — live-приёмка Telegram (PENDING OWNER VERIFICATION).
Далее по задачам: T-3246 @Scanner → T-3247 rework (если findings), T-3248 @Architect, T-3250 @DevOps.`
