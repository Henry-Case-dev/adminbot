# Задачи: urgent-rebuild-dossiers-target-chat-round1022

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 1 @PM (+ Шаг 2b @Architect: T-2090/T-2091) · Тип: data-migration / CLI + ops
> **ТЗ:** `plans/current_task.md`, UPD3 §1 (строки **247–249**) + «Проблема 1» (175–178). Файл untracked, SSH-креды — не цитировать, не коммитить (R17/R18).
> **UPD3-дельта (Step 2b @Architect):** вариант «а», окно **180 дней**, **confirmed-cleanup + JSONL-архив**; spec/ADR-1022-1 Accepted. Детали — `spec.md` §2.5, `ADR-1022-1.md`.
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION 2.57.0; прод `a923310` active.

## Цель
Получить **реальный результат в БД** для целевого чата `-1002661910336`: снять операционные guard'ы, мешающие `manage.py memory rebuild-dossiers` очистить сгенерированный мусор (кроме удаления сырой истории), обеспечить надёжность прогона при блокировке БД и LLM-таймаутах, выдать отчёт counts до/после.

## ТЗ (кратко)
«Жестко запустите пересборку досье именно для чата `-1002661910336`. Снимите любые инварианты и блокировки, которые мешают скрипту очистить сгенерированный мусор (кроме удаления истории сообщений). Нужен реальный результат в базе».

## Решение (Шаг 0)
**Что уже есть:**
- Команда `manage.py memory rebuild-dossiers` — `manage.py:635-719`, подкоманды/парсер `manage.py:944-1020`; движок `services/memory_rebuild.py:400`+.
- Guard целевого чата `_memory_scope` — `manage.py:848-869`: без `--chat <id>` + `--allow-target-chat` целевой чат недоступен; `--all` его исключает.
- Инвариант сырой истории: `RAW_HISTORY_TABLES` + `assert_derived_table` (`services/memory_rebuild.py:55-82`), единая точка удаления `_guarded_delete` (allowlist).
- Авто-бэкап + JSONL-архив + сверка counts (10.21, F5); read-only `memory audit` (`manage.py:893-904`).
- Диагностика прода: `dossier_portrait=0`, `chat_meme=0` для целевого чата → rebuild **ни разу не запускался**.

**Что новое:**
- Операционный обход guard'а для целевого чата (CLI-режим/флаг), но **без снятия** защиты сырой истории.
- Устойчивость к `database is locked` (12 записей в логах прода) и LLM-таймаутам (163): busy_timeout/ретраи/частичная деградация без падения бота.
- Расширенный отчёт counts (before/after, classes, `roster_size`) для оператора.
- **UPD3:** окно по умолчанию **180 дней (4320 ч)**; **confirmed-cleanup** `graph_facts` (точный скоуп — `spec.md` §2.5) с предварительным **JSONL-архивом**; beliefs/nodes/edges/overrides/сырая история — не трогаются.

**Конфликт / инварианты:**
- Формулировка ТЗ «снимите любые инварианты ... кроме удаления истории сообщений» **не снимает** `RAW_HISTORY_TABLES`/`assert_derived_table` — они и есть защита сырой истории, сохраняются неприкосновенно.
- `manual-overrides-immutable`: `persona_dossier_overrides` не перезаписываются; writer пишет только производные `graph_facts`.

## Задачи
- [x] **T-2019** [@Architect] ADR: дизайн снятия операционных guard'ов (какие именно, как), сохранение инварианта сырой истории, режим надёжности при locked/таймаутах, откат. → `ADR-1022-1.md` (Accepted, UPD3).
- [ ] **T-2020** [@Builder] READ-ONLY диагноз прода: counts `dossier_portrait`/`chat_meme` для `-1002661910336`, подтвердить нерабочий путь guard'а (`manage.py:848-869`). → **не выполнено локально:** прод-БД недоступна (локальная пуста); факты диагностики зафиксированы в `spec.md` §0/Step 0. Передать @DevOps для боевого прогона.
- [x] **T-2021** [@Builder] Операционный обход `_memory_scope` (`manage.py:848-869`) для целевого чата; `RAW_HISTORY_TABLES`/`assert_derived_table` остаются нетронутыми. → флаг `--target-chat` (shortcut `--chat <id> --allow-target-chat`); `--all` целевой исключает; инвариант не снят.
- [x] **T-2022** [@Builder] Надёжность при `database is locked`: `busy_timeout` (5с, `database.py:48`) + bounded-ретраи записи (≤3, экспоненциальный бэкофф) в `_guarded_delete`. Snapshot-read оставлен live-WAL (осознанно, без двух хендлов).
- [x] **T-2023** [@Builder] Обработка LLM-таймаутов: bounded-retry Слоя A (уже есть) + `rebuild_error` с частичной деградацией на чат без аборта прогона.
- [x] **T-2024** [@Builder] Отчёт counts before/after: `scanned/reset/reset_portraits/confirmed_candidates/cleaned_facts/protected_belief_sources/rebuilt/skipped/window_hours_used/source_age_days/max_msgs/reasons/backup` (R17-safe).
- [x] **T-2025** [@Builder] Тесты: обход guard'а, JSONL+сверка, неизменность `smart_messages`/FTS, `rebuild_empty`. → `tests/test_memory_dossiers_cleanup_round1022.py`.
- [ ] **T-2026** [@DevOps] Бэкап БД + боевой прогон для `-1002661910336`; post-check неизменности `smart_messages`.
- [ ] **T-2027** [@DevOps] Верификация результата: counts в БД/UI изменились, отчёт оператора.
- [x] **T-2090** [@Builder] **UPD3:** примитив `cleanup_confirmed_dossier_facts(...)` (точный скоуп §2.5): JSONL-архив → сверка (`candidates==archived`) → guarded DELETE; защита `source_ids`/`evidence` beliefs (`protected_belief_sources`); beliefs/nodes/edges/overrides не тронуты; dry-run counts.
- [x] **T-2091** [@Builder] **UPD3:** окно по умолчанию 4320 ч + `effective_window`; тесты: скоуп удаления, beliefs/nodes/edges/`smart_messages`/overrides неизменны; JSONL-архив; `rebuild_empty`/`source_age_days` в отчёте + ненулевой exit.

## Риски
- **R1 (Critical):** снятие guard'а может привести к удалению сырой истории → инвариант `RAW_HISTORY_TABLES`/`assert_derived_table` (`services/memory_rebuild.py:55-82`) и `_guarded_delete` сохраняются; post-check `smart_messages` неизменен (T-2026).
- **R2 (High):** `database is locked` (12 в логах) роняет прогон/бота → busy_timeout + ретраи + прогон на снапшоте/WAL (T-2022).
- **R3 (High):** 163 LLM-таймаута → неполный ребилд или аборт → bounded-ретраи и частичная деградация (T-2023).
- **R4 (High):** боевой прогон без бэкапа → потеря данных → авто-бэкап ДО DELETE обязателен (T-2026); обход guard'а без подтверждённого бэкапа запрещён.
- **R5 (Medium):** over-delete валидных досье (неполный ростер, ср. N10.21-2) → `--dry-run` + вывод `roster_size`/classes до apply.
- **R7 (Critical, принят владельцем UPD3):** confirmed-cleanup удалит валидные подтверждённые факты участников (вариант «а») → предварительный **JSONL-архив** + сверка `candidates==archived` + защита `source_ids` beliefs; beliefs/nodes/edges/overrides/сырая история не трогаются; в F8 — дополнительный rollback-снапшот (T-2090/T-2091).
- **R6 (R17/R18):** SSH-креды в `plans/current_task.md` — не цитировать, не коммитить (untracked).

## Зависимости / ступени вливания
- Внутренних зависимостей нет; **источник задач — P0, стартует первым** в связке `F1 ∥ F2 ∥ F6`.
- Эксклюзивные файлы: `manage.py`, `services/memory_rebuild.py`, `services/database.py` (read-only/режим).
- Канон (`plans/docs/canon/**`, `services/prompt_migrations.py`) — **не трогается**, пересечений нет.
- Ступень: F1 → деплой-прогон (T-2026/T-2027) независимо от System 2.
- Флага нет; снятие guard'а — CLI-параметр. **Δ каталога = 0.**
