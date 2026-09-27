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
