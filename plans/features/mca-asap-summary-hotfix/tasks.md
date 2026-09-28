# mca-asap-summary-hotfix — tasks.md (ASAP, round1027, MCA round 10.27)

Приоритет владельца: «Саммари нужно срочно починить и сделать деплой на прод. Затем продолжать выполнение задач.» (ASAP-блок current_task.md, прод-инцидент 27.09 03:17).

## Диагноз (см. evidence.md)
- Публикацию саммари сорвала L2-жёсткая отбраковка по **мягкому** капу абзацев (`limits.max_summary_parts`, settings-дефолт 1 от Epic 24 v2.22.0) — S5-round1026 переиспользовал легаси-ключ как кап абзацев статьи. Документ §99илей, но >captions → `too_many_paragraphs` → L2_ERROR → «не публикуем» → публикация отменялась ЦЕЛИКОМ. Файл mca-волной не менялся (гипотеза mca-07-регресса («полный payload-бюджет уменьшил доступный user-контекст L2ОО») не подтверждается кодом: `summary_l2_writer.py`/`summary_generator.py`/`summary_fact_package.py` вне mca-диффа).
- Graph-ветка безопасна: `GraphExtractionError` ловится в `_compress_purge_extract_only` (except Exception → break, batch kept, pipeline continues) — mca-дифф в регионе (3574–3770) — только serialized()-обёртки транзакций (MCA-01), логика защиты не менялась.

## Задачи
- [x] T-3918 Диагноз: прод-цепочка (graph L3-фон по LLMTimeoutError НЕ влияет на публикацию; публикация сорвана L2 too_many_paragraphs), роль mca-07 — не подтверждена (сводка в evidence.md).
- [x] T-3919 Фикс №1: env-only kill-switch `SUMMARY_L2_TRIM_ENABLED` (ClassVar, default ON, Δ каталога=0) в config/settings.py.
- [x] T-3920 Фикс №1: `run_l2` — детерминированная обрезка до мягкого капа (первые N абзацев) c R17-safe маркером `trimmed_for_publication` (-L2_COMPLETE `trimmed=1` + WARN-строка; пар метрики paragraphs_before/kept/dropped); жёсткие лимиты §99 (498 абзацев) остаются fail-closed.
- [x] T-3921 Фикс №1: _trim_document_for_publication (детерминированная обрезка, RICH_MAX_CHARS-бюджет после капа).
- [x] T-3922 Фикс №2 (верификаition): тест-покрытие Graph-ветки — LLMTimeoutError всех чанков → GraphExtractionError пойман в _compress_purge_extract_only, батч НЕ помечен, compress_and_purge завершается штатно (публикация не срывается графом).
- [x] T-3923 Тесты: обновить test_too_many_paragraphs (S5) — при SUMMAR_L2_TRIM_ENABLED default → status=ok; при OFF → прежний too_many_paragraphs (байт-в-байт).
- [x] T-3924 Точечные тесты hotfix (новый файл tests/test_summary_asap_hotfix_round1027.py): (а) L2 LLMTimeoutError → status=error (независимо от trim), граф-fire-сценарии, публикация (б) cap=1 → publish (обрезка до 1 абзаца).
- [x] T-3925 Полный pytest .venv (9839 passed, 0 failed, ~211s; baseline round1026 9828 → delta +11) + JS vm-харнесс (48/48 файлов, exit 0; baseline 48/48).
- [x] T-3926 APP_VERSION bump 2.58.31 → 2.58.32 + README «Версия» синхронно.
- [x] T-3927 evidence.md: deployment-заметки для @DevOps (env-флаг, hot-ключ прод-БД проверка, рекомендации).

## ASAP-2: L1-ретрай (пост-деплой 2.58.32, второй пункт ASAP)

> **PM-аннотация (28.09, сверка с `plans/current_task.md` 1884–2768):** нижеследующие
> T-3928…T-3934 — **unreviewed local partial**: код лежит в рабочем дереве
> (`services/summary_l1_clusterizer.py`, `config/settings.py`, untracked
> `tests/test_summary_asap2_l1_retry_round1027.py`), НЕ закоммичен, НЕ ревьюен,
> НЕ задеплоен; прод = 2.58.32. Reviewer `Approved` (`review.md`, коммит `270c277`)
> относится ТОЛЬКО к T-3918…T-3927 (L2-trim hotfix). Поэтому флаги `[x]` с
> T-3928…T-3934 **сняты** (реализация ≠ приёмка).
>
> Более того, эта partial-реализация (same-prompt retry, список `_RETRYABLE_REASONS`
> с `message_in_multiple_threads`/`unknown_message_id`) **SUPERSEDED требованием
> владельца ASAP-2 §15/§16** (`current_task.md:2487`/`2533`): retry — только
> **correction retry ПОСЛЕ deterministic repair**; many-to-many членство больше
> НЕ error (§5, `current_task.md:2128`) и unknown id чинится локально (§6,
> `current_task.md:2157`). Partial не удаляется — он **перерабатывается** в новой
> фиче: `plans/features/mca-asap2-summary-pipeline/tasks.md` → **T-3947**
> (+ контракты T-3944/T-3945, тесты T-3947/T-3958). История и текст задач ниже
> сохранены как есть; диагноз в `evidence.md` §8–§14 остаётся валидным.

Прод-факты: 2 свежих прогона пали РАНЬШЕ L2 — `L1_COMPLETE status=invalid |
invalid_reason=invalid_json` (07:30) и `invalid_reason=message_in_multiple_threads`
(08:23) → `L2_SKIPPED l1_not_usable` → `SUMMARY_COMPLETE degraded`. За 30 дней:
17 SUMMARY, 16 degraded, L2_COMPLETE всего 2. Причина: L1 single-shot — один
невалидный ответ модели → сразу invalid_result без повторной попытки.

- [ ] T-3928 ⟦PARTIAL · UNREVIEWED · SUPERSEDED → mca-asap2-summary-pipeline T-3947⟧
      Механика ретрая в `run_l1`: ровно одна повторная LLM-попытка
      (макс. 2 вызова) при невалидном ОТВЕТЕ модели; триггеры — классы
      валидации `_RETRYABLE_REASONS` (invalid_json, bad_type, unknown_field,
      invalid_fact, unknown_message_id, message_in_multiple_threads); НЕ
      ретраятся LLMError/LLMTimeoutError (error_result как раньше) и
      too_many_threads/too_many_facts/too_many_facts_total (жёсткие лимиты,
      экономия токенов); обе попытки — тот же parse_l1_response/validate_l1_response
      (hard-контракт §95 не ослаблен); обе невалидны → прежний invalid с
      reason ВТОРОЙ попытки.
- [ ] T-3929 ⟦PARTIAL · UNREVIEWED · SUPERSEDED → mca-asap2-summary-pipeline T-3947/T-3948⟧
      Kill-switch env-only `SUMMARY_L1_RETRY_ENABLED` (ClassVar,
      default ON, Δ каталога=0; OFF → точный прежний single-shot байт-в-байт).
- [ ] T-3930 ⟦PARTIAL · UNREVIEWED · SUPERSEDED → mca-asap2-summary-pipeline T-3947/T-3956⟧
      Логи R17-safe: WARN `L1 retry | run_id | chat_id | attempt=1/2 |
      reason=<первой попытки>`; L1_COMPLETE — аддитивное поле `attempts=%d`
      (1/2), фактический статус последней попытки.
- [ ] T-3931 ⟦PARTIAL · UNREVIEWED · SUPERSEDED → mca-asap2-summary-pipeline T-3947/T-3958⟧
      Тесты: новый tests/test_summary_asap2_l1_retry_round1027.py
      (12 тестов: ретрай invalid_json → ok/attempts=2; ретрай
      message_in_multiple_threads → ok; обе невалидны → прежний invalid (reason
      второй); ровно один ретрай без лавины; too_many_facts → single-shot;
      kill-switch OFF ×2 (invalid single-shot / ok без ретрая); LLMError и
      LLMTimeoutError → без ретрая; первая ok → attempts=1; Δ каталога=0).
      Обновлены под новую семантику: test_summary_test_run.py
      (invalid L1 → 2×L1, L2 не вызывается) и test_summary_deploy_round1026.py
      scenario_07 (2×L1, 0 публикаций, fail-closed сохранён).
- [ ] T-3932 ⟦PARTIAL · UNREVIEWED — баунд-гейты переиспользуемы, статус переживёт переработку T-3947⟧
      Баунд-гейты: summary_l1_clusterizer.py санкционирован в
      test_tool_coordinator_round1026 (summary_changed) и исключён из запрета
      test_summary_deploy_round1026 (NOTE ASAP-2, прецедент NOTE-исключений).
- [ ] T-3933 ⟦PARTIAL · UNREVIEWED · SUPERSEDED — итоговый APP_VERSION назначит релиз ASAP-2 (mca-asap2-summary-pipeline T-3962); локальный пин 2.58.33 в дереве ≠ прод⟧
      APP_VERSION 2.58.32 → 2.58.33 + README + param-registry.meta +
      версия-пины (27 py-файлов + 4 JS-харнесса, механика 270c277).
- [ ] T-3934 ⟦PARTIAL · UNREVIEWED · SUPERSEDED — прогон относится к нелокальной partial-ветке; финальные полные прогоны — mca-asap2-summary-pipeline T-3961⟧
      Полный pytest 9851 passed / 0 failed (9839 baseline → +12) +
      JS vm-харнесс 48/48 exit 0 + git diff --check CLEAN + R17-скан CLEAN.

