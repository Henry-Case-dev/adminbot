# Задачи: budget-data-repair-round1024

> **Раунд 10.24 (UPD5-critical)** · Приоритет **P0** · Шаг 1 @PM · Тип: ремонт/аудит данных (PG overrides) + разграничение флага
> **ТЗ:** `plans/current_task.md`, **строка 404**: бюджеты целевого чата `-1002661910336` сбросились (были бесконечные лимиты), значения в мини-аппе не применяются. Секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Разведка @Memory: координаты UPD5.
> **Конфликт/AMEND:** **AMEND ADR-1019-8 D4** (сид `chat_settings_seed`, идемпотентность/enforce) — ожидаемо **ADR-1024-23**; разграничение с **`flags.chat_context_budgets_enabled`** (`scripts/backfill_104_chat_flags.py`).
> **Границы:** F20 `budget-overrides-merge-fix-round1024` (**предпосылка:** без фикса merge ремонт снова затрётся); F21 `budget-global-toggle-round1024` (master-тумблер).

## Цель
Восстановить утраченные per-chat значения `overrides` целевого чата и **доказать аудитом**, что они на месте; настроить идемпотентный ремонтный путь; разграничить `flags.chat_context_budgets_enabled` (усечение контекста) с master-тумблером бюджетов (F21).

**Важно:** сначала F20 (иначе любой ремонт снова затирается тем же багом), затем ремонт данных.

## Что уже есть (координаты)
- **Целевые значения (данные оператора, НЕ ветвление):** `config/chat_settings_seed.json:11-20` — 8 ключей, в т.ч. `limits.chat_global_key_budget_requests/tokens = -1`, `limits.worker_daily_llm_calls/tokens_per_chat = -1`, `limits.chat_global_context_max_tokens = -1`, `limits.chat_thread_max_tokens = -1`, `limits.chat_context_budget_tokens = -1` (и `limits.import_history_retention_days = 0`).
- **Идемпотентный сид:** `services/chat_settings_seed.py:145-185` (`apply_chat_settings_seed`, режимы `enforce`/`force`/версия, читает `root.get("overrides")`, merge `current + patch`, пишет `chat_lore_history`).
- **CLI-путь:** `manage.py` — команда `apply-chat-overrides` (`:596-600`, `:829-848`), флаг `--force`.
- **Авто-сид при старте:** `bot.py:1049-1051` (fail-open).
- **История/аудит:** таблица `chat_lore_history` (`field='chat_params'`, `changed_by BIGINT` — `services/pg_db.py:95`).
- **Разграничиваемый флаг:** `flags.chat_context_budgets_enabled` — `services/direct_chat_service.py:1142-1145`; `scripts/backfill_104_chat_flags.py` (ставит `false` целевому чату, только если ключа нет).
- **Читатель значений:** `services/worker_settings.py:123-150` (chat → global → default).

## Задачи
- [x] **T-2369** [@Architect] spec.md + ADR (**ожидаемо ADR-1024-23** / AMEND ADR-1019-8 D4): стратегия ремонта (идемпотентный сид `--force` vs ручная правка после фикса F20); правила `enforce`/`version`/`force` для целевого чата; **JSONL-аудит** по `chat_lore_history field='chat_params'`; **AMEND/разграничение** `flags.chat_context_budgets_enabled` ↔ master-тумблер F21; безопасность (R17/R18 — значения только в данных/на сервере).
- [x] **T-2370** [@Builder] Ремонтный путь: восстановить 8 per-chat значений целевого чата идемпотентно (через `apply-chat-settings-seed`/`apply-chat-overrides --force` или отдельную repair-команду), строго по канону write-path `set_chat_params` (NOTIFY/кэш-инвалидация/история). Повторный прогон — **no-op**; существующий явный выбор админа не перетирается.
- [x] **T-2371** [@Builder] **Аудит/верификация:** скрипт/команда печатает фактические `overrides` целевого чата и сверяет с эталоном `chat_settings_seed.json:11-20`; отдельно собирает JSONL-аудит `chat_lore_history field='chat_params'` (что/когда менялось, `changed_by`) — без секретов (R17). Отчёт — в `plans/metrics.md`/`plans/reports/`.
- [x] **T-2372** [@Builder] Регресс-гарантия против повтора: после ремонта **UI-save не удаляет** восстановленные ключи (тест из F20-b на реальном наборе 8 ключей); сид при рестарте — no-op (петля `save → стирание → рестарт-лечение` разорвана).
- [x] **T-2373** [@Builder] **AMEND/разграничение `flags.chat_context_budgets_enabled`:** зафиксировать семантику рядом с master-тумблером F21; не сломать `scripts/backfill_104_chat_flags.py`; тест на совместное состояние (context-усечение vs лимиты бюджета).
- [ ] **T-2374** [@Reviewer] Ревью: ремонт идемпотентен; аудит воспроизводим; значения не утекли; разграничение флагов документировано; зависимость от F20 подтверждена.
- [ ] **T-2375** [@DevOps] Прод-ремонт + live-аудит: применить ремонт на проде, подтвердить значения и отсутствие заглушки; JSONL-аудит приложен. Отчёт (без секретов).

## Критерии приёмки
- В `overrides` целевого чата восстановлены все per-chat значения из эталона (в т.ч. `-1` = безлимит), подтверждено аудитом.
- Ремонт **идемпотентен** (повторный прогон — no-op), не перетирает существующий явный выбор.
- После ремонта UI-save сохраняет набор (зависит от F20); рестарт-сид — no-op.
- Разграничение `flags.chat_context_budgets_enabled` и master-тумблера зафиксировано и покрыто тестом.
- Полный pytest — 0 failed; `git diff --check` чист.

## Риски
- **R1 (Critical):** ремонт до фикса F20 → данные снова затираются → строгий порядок **F20 → F22**.
- **R2 (High):** `--force` затирает намеренный выбор админа → guard «не перетирать существующее», dry-run.
- **R3 (Medium):** секреты/приватные ключи в JSONL-аудите → R17-редакция.
- **R4 (Medium):** конфликт `scripts/backfill_104_chat_flags.py` и новых repair-команд → один write-path, идемпотентность.
- **R5 (Low):** ошибочная сверка (ключ-значение приведён к чужому типу) → типизация из каталога.

## Зависимости / ступени
- Зависит от: **F20** (обязательно первым). Связано с **F21** (разграничение флага).
- Ступень общих файлов: `config/chat_settings_seed.json` / `services/chat_settings_seed.py` / `manage.py` — **F22**; `scripts/backfill_104_chat_flags.py` — **F22** (AMEND).
- Feature flag: **не требуется** (ops/ремонт данных). Откат — повторный сид/ручная правка + `git revert` кода команд.
- **Δ DDL = 0, Δ каталога = 0.**
