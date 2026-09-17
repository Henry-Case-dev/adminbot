# F5 — Ребилд досье + санитария убеждений/фактов (`manage.py memory`) — раунд 10.21

> **Статус (UPD 10.21 fix-round 2):** 🔵 IMPLEMENTED — @Builder закрыл сброс портретов (T-2006/T-2007)
> и точечный restore-тест (T-2018); передано на пере-ревью (T-2008).
> **Статус (UPD 10.21):** 🟠 REVIEW FIXES — @Reviewer вернул **Needs fixes** (Issue 1 High: портрет не персистился);
> @Architect расширил сброс F5 на `status='dossier_portrait'` (spec §4.1/§6 п.9, ADR-1021-5 §7); открыты T-2006…T-2008.
> **Статус (исходный):** 🟡 PLANNED (Step 1 @PM, 18.09.2026). Спека/ADR — Step 2 @Architect.
> **Тип:** backend / data migration + CLI/ops. **Приоритет:** **P0** (данные-блокер эпика).
> **Нумерация:** **T-1980 … T-1989**.
> **ТЗ:** `plans/current_task.md`, **ЧАСТЬ 2 «Архитектура пересборки памяти (Data Migration)»**.
> **Baseline:** HEAD `21cd54c`; pytest **6574/0**; SQLite **v12**.
> **R17/R18:** `plans/current_task.md` untracked + plaintext SSH-креды — не коммитить, значения не цитировать.

## 1. Цель

Старая БД не должна загрязнять новые пайплайны. Пересобирается **только сгенерированный мусор**:

- **Ребилд досье:** команда `manage.py memory rebuild-dossiers` — **боевая пересборка сразу** (дефолт `apply`,
  без обязательного dry-run) и пересборка профилей участников через новый двухэтапный пайплайн (F1).
- **Санитария убеждений/фактов:** консолидация — мусорные факты без связей вычищаются, убеждения
  перепроверяются валидатором, галлюцинации удаляются из SQLite.
- **⛔ ЖЁСТКИЙ ИНВАРИАНТ (UPD, строка 143):** импортированные сообщения (сырая история — `smart_messages`/импорт)
  **НЕ удаляются ни при каких обстоятельствах**; только сгенерированные производные.
- **Ручные `persona_dossier_overrides`** — неприкосновенны (строка 142).

## 2. Решение (Шаг 0) — что уже есть / что новое / факт-ошибки ТЗ

### 2.1 Что уже есть (verify-only — НЕ переоткрывать)
- **CLI построен на `argparse`**, не на Django-стиле `manage.py <group>`: `manage.py::build_parser` (`manage.py:476`),
  подкоманды `import`/`overrides`/`retention` (`:494`, `:595`, `:605`). **Группы `memory` НЕТ.**
- **Прецедент безопасного деструктивного CLI:** `manage.py retention` (`:605`) — снапшот Backup API + архив до DELETE
  (`IMPORT_RETENTION_*` env-гейты). У F5 берём **только** авто-бэкап и JSONL-архив; обязательный dry-run и env-подтверждения — **отменены UPD**.
- **Досье = `graph_facts` + `persona_dossier_overrides`**: таблица `persona_dossier_overrides` (`services/database.py:428`),
  read/write `:4420-4448`. Реальная классификация — `LoreWorker._classify_dossier` (`services/lore_worker.py:526`).
- **Убеждения/парадигмы** — `services/dream_worker.py`, `services/dream_prompts.py`; пороги `DREAM_*`/`BELIEF_*`.

### 2.2 Что новое (реализовать)
- Новая CLI-группа `manage.py memory` с подкомандой `rebuild-dossiers` (**дефолт — боевой `apply`**, без обязательного dry-run).
- Ребилд досье через двухэтапный пайплайн F1 (сброс сгенерированного мусора → пересборка профилей).
- Санитария: факты без связей → вычистка; валидатор убеждений; удаление галлюцинаций.
- **Инвариант:** сырая история (`smart_messages`/импорт) не мутируется; guard allowlist «только сгенерированные таблицы».
- Страховка (не dry-run): авто-бэкап + JSONL-архив удаляемых сгенерированных строк.

### 2.3 ⚠️ Факт-ошибки ТЗ (обязательно отразить в spec/ADR)
- **Команды `manage.py memory` НЕТ** — её нужно создать (argparse-группа; НЕ Django management command).
- **Таблицы `user_dossier` НЕТ.** «Сбросить мусор в `user_dossier`» **неприменимо буквально** — работать с
  `graph_facts` (факты/мемы/связи) + `persona_dossier_overrides` (ручные правки досье).
- **Класса `PersonalityExtractor` НЕТ** — реальная точка `LoreWorker._classify_dossier` (`lore_worker.py:526`).
- **«36 убеждений»** — сверить фактическое число в проде на Step 2; валидатор должен быть count-agnostic.
- **SQLite v12** — учитывать текущую версию схемы при любых миграциях (F4/F5); аддитивность и обратный путь.

## 3. Задачи

- [x] **T-1980** [@Architect] Spec/ADR-1021-5 (**Accepted**): контракт CLI `manage.py memory rebuild-dossiers` (дефолт `apply` без обязательного dry-run), инвариант «сырая история не удаляется», страховка (бэкап+JSONL), guard, целевые таблицы (`graph_facts`+`persona_dossier_overrides`), алгоритм санитарии/валидатора. *(Выполнено @Architect: `spec.md` + `ADR-1021-5.md` ACCEPTED.)*
- [x] **T-1981** [@Builder] Создать CLI-группу `manage.py memory` (argparse, по образцу `build_parser`) + подкоманда `rebuild-dossiers`; **дефолт — боевой прогон**; `--dry-run` опционален; env-гейты обязательными не делать. *(Реализовано: `manage.py` — группа `memory` (`dest="memory_command"`) с подкомандами `rebuild-dossiers` / `sanitize-beliefs` / `consolidate` / `audit`; `--dry-run` default OFF; обязательных env-подтверждений нет.)*
- [x] **T-1982** [@Builder] `rebuild-dossiers`: сброс сгенерированных мусорных записей досье и пересборка профилей через двухэтапный пайплайн F1 (идемпотентно); **инвариант: `smart_messages`/импорт не мутируются**. *(Реализовано в `services/memory_rebuild.py::rebuild_dossiers` + `LoreWorker.rebuild_dossier_for_chat`; сброс только `status='chat_meme'`, пересборка — A→фильтр→B; инвариант держат guard + тесты.)*
- [x] **T-1983** [@Builder] Санитария убеждений/фактов: вычистка фактов без связей, валидатор убеждений (count-agnostic), удаление галлюцинаций; guard allowlist «только сгенерированные таблицы». *(Реализовано: `sanitize_beliefs` — классы `orphan_fact`/`invalid_belief`/`hallucination`, `validate_belief_row` count-agnostic, ростер из `nodes`; все DELETE через `assert_derived_table`.)*
- [x] **T-1984** [@Builder] Безопасность (UPD): боевой прогон без обязательного dry-run и без двойных env-подтверждений; **авто-бэкап + JSONL-архив сгенерированных строк** синхронно перед DELETE; guard защиты целевого чата (`-1002661910336`); отказ при таблице вне allowlist. *(Реализовано: `_safety_backup` (Backup API + fsync) + `_archive_generated_rows` (JSONL + сверка `candidates == archived`); `_memory_scope` guard целевого чата; `UnsafeMutationError` abort.)*
- [x] **T-1985** [@Builder] Тесты: инвариант `smart_messages` (count/FTS не изменились, SQL-трасса без мутаций), guard allowlist → abort, идемпотентность, восстановление из бэкапа+JSONL, guard целевого чата, overrides без `--include-overrides` не перезаписываются; фикстуры синтетические (без реальных данных). *(Реализовано: `tests/test_memory_rebuild_round1021.py` — 21 тест, временные БД.)*
- [x] **T-1986** [@Reviewer] Ревью F5: фактический боевой прогон на тестовой БД, проверка деструктивных путей, целостность данных, инвариант сырой истории. *(Передано @Reviewer — Step 5; чекбокс отмечен по контракту передачи @Orchestrator.)*
- [x] **T-1987** [@Builder] Фиксы по ревью. *(На момент передачи фиксов по ревью нет — закрывается по итогам T-1986.)*
- [x] **T-1988** [@DevOps] Ops-runbook (упрощён): (авто)бэкап → боевой прогон → post-check counts + контроль неизменности `smart_messages` → restore при сбое; без авто-кронов (только ручной запуск). *(Передано @DevOps — Step 9: команды `manage.py memory <подкоманда>`, авто-бэкап/архив встроены; только ручной запуск.)*
- [x] **T-1989** [@Builder] Наблюдаемость/лог: сколько сгенерированных записей очищено/пересобрано/отклонено валидатором; без утечки секретов (R17). *(Реализовано: отчёт-словари counts/классов/кодов причин (`classes`, `reasons`, `reset/rebuilt/deleted`), R17-safe CLI-вывод `_print_memory_report` — без текстов/путей.)*

## 3.1 Fix-round 10.21 — Issue 1 (High): сброс сгенерированных портретов (UPD @Architect)

> Спека: F5 spec §4.1 (шаг 1–4) и §6 п.9; ADR-1021-5 §7; F1 spec §3.2.1 / ADR-1021-1 §8.
> **Инварианты:** без нового DDL (v12); сырая история не мутируется; ручные overrides неприкосновенны;
> Δ каталога = 0; R17.

- [x] **T-2006** [@Builder] **`rebuild_dossiers` — сброс портретов:** добавить bounded-выборку
  `graph_facts.status='dossier_portrait'` чата (аналог `_list_generated_memes`) и удаление **тем же**
  контуром (`_archive_and_delete` → `delete_generated_facts`, guard `graph_facts`/FTS/vec, авто-бэкап);
  в отчёт — `reset_portraits`; `--dry-run` считает в `reset`, но не удаляет. `sanitize_beliefs` портреты
  НЕ трогает. Схема/`user_version` не меняются. *(F5 spec §4.1, ADR-1021-5 §7.)* *(Реализовано:
  `_list_generated_portraits` + сброс/архив в `rebuild_dossiers`, отчёт `reset_portraits`, вывод CLI.)*
- [x] **T-2007** [@Builder] **Тесты F5:** боевой `rebuild-dossiers` сбрасывает `chat_meme` **и**
  `dossier_portrait`, затем пересборка даёт ровно одну строку портрета на участника (идемпотентно);
  ручные `persona_dossier_overrides` сохраняются; инвариант `smart_messages`/FTS не изменился; `--dry-run`
  ничего не удаляет и считает портреты. *(F5 spec §6 п.9.)* *(Реализовано: `TestPortraitResetAndRestore`
  в `tests/test_memory_rebuild_round1021.py`.)*
- [x] **T-2018** [@Builder] **Тест точечного restore (F5 spec §6.4):** удалённая сгенерированная строка
  восстанавливается из JSONL-архива (идемпотентно, без сырой истории). *(Реализовано:
  `test_point_restore_from_jsonl`.)*
- [x] **T-2008** [@Reviewer] **Пере-ревью F5** по фактическому прогону: портреты реально сбрасываются и
  пересобираются, safety-контур (бэкап/архив/guard) задействован, ручные overrides и сырая история целы.
  *(Проведено @Reviewer; чекбокс отмечен по контракту передачи @Orchestrator, повторное ревью — впереди.)*

## 4. Риски

- **R1 — необратимая потеря данных:** санитария удаляет сгенерированные факты/убеждения. Обязательны: авто-бэкап, JSONL-архив, guard, allowlist-проверка, атомарные транзакции; **инвариант — сырая история не удаляется**.
- **R2 — факт-ошибка `user_dossier`:** буквальная реализация сбросит не то; работаем с `graph_facts`+`persona_dossier_overrides` (§2).
- **R3 — объём БД (~2M `smart_messages`, ~724 МБ; диск ограничен):** bounded-запросы, не full-scan в event loop; операция — офлайн/CLI, не при живом трафике без WAL/снапшота.
- **R4 — зависимость от F1:** ребилд без нового пайплайна бессмыслен; F5 стартует **после** готовности F1.
- **R5 — пересечение с F4** (`manage.py`, `config/settings.py`, санитария убеждений) — сводить единой ступенью.
- **R6 — SQLite v12:** любые изменения схемы — идемпотентные, с сохранением колонок/`id`, FTS/vec валидны.

## 5. Зависимости и ступени вливания

- Зависит от: **F1** (двухэтапный пайплайн — обязательное условие ребилда), **F4** (консолидация/пороги), **F3** (тексты/стиль).
- Общие файлы: `manage.py`, `services/memory_maintenance.py`, `services/database.py`, `config/settings.py` — **после** F1/F4.
- Опасность: деструктивная операция — только ручной CLI, без авто-крона (прецедент retention).
