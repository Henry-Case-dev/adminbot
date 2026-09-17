# F4 — Аудит порогов Парадигм / Deep Sleep + Memory Consolidation — раунд 10.21

> **Статус (UPD 10.21 fix-round 2):** 🔵 IMPLEMENTED — @Reviewer Issue 2 (High) закрыт: `consolidate` получил
> авто-бэкап ДО первой записи + JSONL-архив записываемых парадигм (T-2009/T-2010); fix-round 2 — страховка
> **fail-closed** без `db_path` (T-2017). Передано @Reviewer.
> **Статус (исходный):** 🟡 PLANNED (Step 1 @PM, 18.09.2026). Спека/ADR — Step 2 @Architect.
> **Тип:** backend / cognition (мета-слой памяти). **Приоритет:** **P1**.
> **Нумерация:** **T-1971 … T-1979**.
> **ТЗ:** `plans/current_task.md`, **ЧАСТЬ 1 → Шаг 4 «Починка порогов Парадигм»**.
> **Baseline:** HEAD `21cd54c`; pytest **6574/0**; SQLite **v12**.
> **R17/R18:** `plans/current_task.md` untracked + plaintext SSH-креды — не коммитить, значения не цитировать.

## 1. Цель

«Мёртвые Парадигмы»: мета-слой памяти (Deep Sleep) всё ещё пуст. Требуется:

- Аудит триггеров Парадигм / Deep Sleep.
- Скрипт переоценки (**Memory Consolidation**): сжатие мусорных убеждений в Парадигмы **или** принудительное
  снижение порога глубокого сна (threshold).

## 2. Решение (Шаг 0) — что уже есть / что новое

### 2.1 Что уже есть (verify-only — НЕ переоткрывать)
- **Deep Sleep реализован** (раунд 10.13, F3 `cognition-deep-sleep`): поля `config/settings.py:1180-1195`
  — `DEEP_SLEEP_ENABLED` (default **False**), `DEEP_SLEEP_TRIGGER` (`after_sleep`/`fixed`),
  `DEEP_SLEEP_HOUR`, `DEEP_SLEEP_TOP_K=20`, `DEEP_SLEEP_MAX_PARADIGMS=3`, `DEEP_SLEEP_TOKENS_PER_DAY=40000`.
- **Пороги сна ослаблены в 10.18** (F2 sleep-manual-cascade): `DREAM_*` дефолты `2/10/2/8/10/60/300000`
  (`config/settings.py:1144-1161`); PG-миграция `migrate_dream_thresholds`.
- **Belief decay/resurrect** (10.13, F2): `BELIEF_*` (`config/settings.py:1170-1178`), `BELIEF_DECAY_ENABLED` default False.
- **Парадигмы** как сущность уже присутствуют в каталоге/`param_catalog.py` (`DEEP_SLEEP_MAX_PARADIGMS` → `limits.deep_sleep_max_paradigms_per_run`, `param_catalog.py:1750-1753`).
- **Диагностика здоровья памяти:** `services/memory_health.py::collect_metrics` — можно расширить наблюдаемостью по парадигмам.

### 2.2 Что новое (реализовать)
- READ-ONLY аудит: почему прогонов Deep Sleep/парадигм нет (флаги OFF? нет кандидатов? пороги недостижимы?).
- Скрипт **Memory Consolidation** (переоценка/сжатие убеждений в Парадигмы), идемпотентный, CLI-only из F5.
- Решение по порогам: **принудительное снижение threshold разрешено** (Д11=да) **или** принудительный триггер —
  конкретика по результатам аудита.

### 2.3 ⚠️ Уточнения/факт-ошибки ТЗ
- ТЗ формулирует «добавьте скрипт переоценки» — в проекте **нет** `manage.py memory` (см. F5); CLI-группа создаётся в F5, сюда встраивается консолидация.
- «Парадигмы» — терминология мета-слоя; сверить с реальными таблицами/полями `graph_facts`/убеждениями на Step 2 (таблицы `user_dossier`/`paradigms` в ТЗ могут не совпадать с кодом).

## 3. Задачи

- [x] **T-1971** [@Architect] Spec/ADR-1021-4: аудит-методика, алгоритм Memory Consolidation, решение по порогам (снижение vs принудительный триггер), контракт с CLI F5. *(Выполнено @Architect: `spec.md` + `ADR-1021-4.md` ACCEPTED.)*
- [x] **T-1972** [@Builder] READ-ONLY аудит триггеров Deep Sleep/Парадигм (флаги, пороги, кандидаты, фактическое число прогонов) → раздел отчёта `plans/reports/round1021_paradigm_audit.md`. *(Выполнено: `collect_paradigm_audit` в `services/memory_maintenance.py`; отчёт `plans/features/paradigm-thresholds-consolidation-round1021/audit.md` + копия `plans/reports/round1021_paradigm_audit.md`. Результат: **ветка A, break_point=flags_off** — DREAM_ENABLED/DEEP_SLEEP_ENABLED/BELIEF_DECAY_ENABLED=False; `memory_dream_log`/`dream_state`/парадигм нет; пороги ни при чём. Мутаций при аудите нет.)*
- [x] **T-1973** [@Builder] Скрипт Memory Consolidation: сжатие мусорных убеждений в Парадигмы (идемпотентно, дефолт — боевой прогон `apply`; опциональный `--dry-run`; авто-бэкап + JSONL-архив). *(Реализовано: `consolidate(...)` в `services/memory_maintenance.py` — bounded-выборка `belief_meta.type='belief'`, ранжирование по опорам, запись через `DreamWorker._write_paradigm` + дедуп `_paradigm_dedup_keys`/`_deep_dedup_key`; CLI-only `manage.py memory consolidate`; повторный прогон → 0 записей.)*
- [x] **T-1974** [@Builder] Правка порогов/триггеров по решению T-1971 (понижение `DEEP_SLEEP_*`/`BELIEF_*` — **в т.ч. принудительное снижение, Д11=да, значения из отчёта аудита** — или force-триггер) + PG-миграция дефолтов. *(Ветка A: пороги не меняем. Механизм принудительного снижения реализован как идемпотентная обратимая PG/DML-миграция `migrate_deep_sleep_thresholds` (`services/config_migrations.py`; `memory.deep_sleep_min_interval_hours` 20→6), по умолчанию выключен env-only `DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED=False`, Δ каталога = 0; активируется при ветке B/C.)*
- [x] **T-1975** [@Builder] Тесты: консолидация идемпотентна, apply-дефолт соответствует решению, опциональный dry-run — no-op, пороги (в т.ч. принудительное снижение) применяются, нет регрессий cognition. *(Реализовано: `tests/test_memory_consolidation_round1021.py` — 19 тестов; F5-инварианты — `tests/test_memory_rebuild_round1021.py`.)*
- [x] **T-1976** [@Reviewer] Ревью F4 (по фактическим прогонам/метрикам, не по grep). *(Передано @Reviewer — Step 5; чекбокс отмечен по контракту передачи @Orchestrator.)*
- [x] **T-1977** [@Builder] Фиксы по ревью. *(На момент передачи фиксов по ревью нет — закрывается по итогам T-1976.)*
- [x] **T-1978** [@Builder] Наблюдаемость: метрики «парадигм за прогон», причины пропуска (расширение `memory_health`/логов). *(Реализовано в `services/memory_health.py::collect_metrics`: `paradigms_total`, `paradigms_last_run`, `dream_runs_7d`, R17-safe reason-коды `deep_skip`.)*
- [x] **T-1979** [@Builder] Активация: **без флага** (`flags.memory_consolidation_enabled` не вводится); раскатки 10/50/100% нет; консолидация CLI-only, авто-крона нет; **Δ каталога = 0**. *(Подтверждено: флаг не введён; `consolidate` вызывается только из `manage.py memory consolidate`; крон/HTTP-триггеров нет; новые записи каталога отсутствуют.)*

## 3.1 Fix-round 10.21 — Issue 2 (High): страховка консолидации

> Спека: F4 spec §3.2 (R1); прецедент F5 (`_safety_backup`/`_archive_generated_rows`).
> **Инварианты:** без нового DDL (v12); капы `TOP_K`/`MAX_PARADIGMS`/`TOKENS_PER_DAY` не снимаются;
> R17 — без текстов в логах; Δ каталога = 0.

- [x] **T-2009** [@Builder] `consolidate()` принимает `db_path`/`backup_dir`; при `dry_run=False` и `db_path`
  вызывает авто-бэкап ДО первой записи и JSONL-архив ЗАПИСЫВАЕМЫХ парадигм (сверка
  `candidates == archived` → иначе запись отменяется). Прокинуто из `manage.py memory consolidate`.
  *(Реализовано: `memory_maintenance.consolidate` + ленивый импорт F5-хелперов; CLI прокидывает
  `db_path`/`backup_dir`; при отсутствии `db_path` — fail-closed, см. T-2017.)*
- [x] **T-2010** [@Builder] Тесты страховки: «бэкап создан до write» (порядок backup→archive→write),
  «архив содержит записанные строки», `archive_mismatch` → запись отменена, `dry_run` без бэкапа/архива.
  *(Реализовано: `TestConsolidateSafety` в `tests/test_memory_consolidation_round1021.py`.)*
- [x] **T-2011** [@Builder] **Descope-нота Issue 7 (Low):** `DreamWorker` — ВНЕ периметра F1 (двухслойность
  убеждений/парадигм меняет семантику F4 и пересекается с F5); формулировка зафиксирована @Architect в
  F1 spec §4.1 и T-1949. Отдельная задача на распространение фильтра на убеждения — только по решению владельца.
  *(Зафиксировано; код `DreamWorker` не трогается.)*
- [x] **T-2017** [@Builder] **Fix-round 2 (Medium): страховка fail-closed.** Боевой прогон `consolidate`
  без `db_path` раньше писал reason `backup_unavailable` и **продолжал запись**; теперь — выход до первой
  записи (F5-семантика). Явный opt-in `allow_no_backup=True` (в прод-коде не выставляется) сохраняет
  прежнее поведение. *(Реализовано: `memory_maintenance.consolidate`; тесты `TestConsolidate`
  `test_no_db_path_is_fail_closed` / `test_allow_no_backup_explicit_opt_in`, 4 базовых теста переведены на
  `db_path`.)*

## 4. Риски

- **R1 — деструктивность консолидации:** сжатие убеждений/парадигм может уничтожить данные; страховка — авто-бэкап + JSONL-архив изменённых сгенерированных строк + guard (по образцу `retention`, `services/memory_maintenance.py:389-425`); `--dry-run` опционален.
- **R2 — стоимость RAG «по всей базе»:** Deep Sleep ограничен `TOP_K`/`MAX_PARADIGMS`/`TOKENS_PER_DAY` — не снимать капы.
- **R3 — БД большая (~2M строк `smart_messages`, БД ~724 МБ / диск ~8 из 23 ГБ по данным 10.19):** аудит/консолидация только bounded-запросами, не full-scan в event loop.
- **R4 — пересечение с F5** (`manage.py memory` + санитария убеждений) и с F1/F3 (качество убеждений на входе). Ступени — §5.
- **R5 — миграция дефолтов PG** (`DREAM_*`/`DEEP_SLEEP_*`/`BELIEF_*`): идемпотентность и обратный путь.

## 5. Зависимости и ступени вливания

- Зависит от: **F1** (качество фактов/убеждений на входе), **F5** (CLI-группа `manage.py memory`).
- Общие файлы: `config/settings.py`, `services/param_catalog.py`, `services/config_migrations.py`, `manage.py`, `services/dream_worker.py` — сводить после F1/F3, вместе с F5.
- Даёт: операционный инструмент для санитарии (F5).
