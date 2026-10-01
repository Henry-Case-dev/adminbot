# `mca-04b-dossier-rebuild` — анализ угроз и отказов (threat & failure analysis)

> **Статус:** ✅ оформлен (M-MCA04B-2, review round 1, 01.10.2026). Артефакт обязателен при Risk **R3** (spec §7, tasks.md «Risk — заявка R3»).
> **Основа:** substantive-анализ Reviewer (`review.md`, раздел «Threat/failure analysis (R3)») + спека §3.2/§3.3 + фактическая реализация (включая реворк H-1/H-2 round 1).
> **R17/R18:** секреты и сырой пользовательский контекст отсутствуют — только компоненты, коды, состояния, единицы счётчиков.

## 1. Метод и границы

Метод: анализ границ доверия → активов → сценариев угроз/отказов → контрмер с указанием проверяемого evidence. Анализ покрывает **изменённую поверхность** фичи (10 прод-файлов + реворк round 1: `lore_worker.py`, `dossier_rebuild_jobs.py`, `database.py` v20-API, `chat_lore.py`, гейты, `loader.py`, `mca_events.py`, `mca_process_registry.py`); неизменённые подсистемы (transport, TMA-авторизация, PG) — вне периметра, их гарантии наследуются.

## 2. Границы доверия и точки входа

| Граница | Вход | Авторизация | Комментарий |
|---|---|---|---|
| TMA → API | `web/api/chat_lore.py::start_dossier_rebuild`, resume, cancel, `job_view` | `_require_chat` (членство в чате) + `_is_global_admin` (admin-only мутации, политика §104/§135) — **не менялись** (review L2: doc-формулировка spec §5.3 уточняется @Architect, ослабления нет) | UI не ходит в БД напрямую (GEN-R21) |
| LLM-провайдер | `_layer_a_call`/`_layer_b_call` (роль background) | существующий клиент/маршрутизация | LLM вне транзакций записи (MCA14-R3); ответ — недоверенные данные: `parse_layer_a/b` + `filter_layer_a_candidates` + row-bound + SourceRef-маппинг до записи |
| Диск | `jobs_dir`/`archive_dir` (backlog-артефакты, snapshot, job-store, backup) | локальный процесс | R17: артефакты — счётчики/курсоры/коды; содержимое кандидатов — только в staging `payload_json` (производные, без сырых сообщений) |
| БД (SQLite single-writer) | `write_transaction`/`serialized` | — | миграция v20 аддитивна; PG no-op (GEN-R4) |

## 3. Активы и неприемлемые события

1. **Память о людях** (`graph_facts`, досье, портреты) — потеря/подмена/загрязнение субъекта недопустимы.
2. **Честность статусов заданий** — ложный «успех» эксплуатируется пользователем как достоверность досье.
3. **Доступность direct-flow** — фоновая пересборка не должна блокировать ответы.
4. **Секреты/сырой контекст** — не попадают в логи/события/job-view.

## 4. Сценарии угроз и отказов → контрмеры

### 4.1. Класс «нечестная финализация» (главный класс, ради которого фича создавалась)

| # | Сценарий | До фикса (проба Reviewer) | Контрмера (round 1) | Evidence |
|---|---|---|---|---|
| T-1 | Модель недоступна весь проход → «успешная» пересборка с 0 извлечений | проба B: `completed`, errors=3, reason=None | движок: `extracted==0 ∧ model_errors>0` → `model_unavailable` (≠ completed); раннер → `paused`, `reason_code=model_unavailable` (retryable, спека §3.2 «paused/failed по retryability»), курсор сохранён для resume | `test_model_unavailable_whole_pass_is_failed_not_completed` |
| T-2 | Бюджет кончился на финальном синтезе → completed без портрета | проба C: `completed`, portraits=0 | Layer B budget → `budget_exhausted` + `failed_stage="synthesize"`; кандидаты персистятся (T-4) → resume повторяет синтез по полному набору; в direct-режиме (набор не восстановим) → честный терминальный `failed` | `test_budget_exhausted_at_synthesis_not_completed`, `test_direct_mode_layer_b_budget_is_failed_not_silent` |
| T-3 | Parse error ≠ модель — неотличимы, маскировка под сбой модели | один `parse_error` на всё | `_layer_a_call`: `ValueError` (невалидный JSON после retry) → `parse_error`; прочие исключения транспорта → `model_unavailable`; раздельные счётчики `parse_errors`/`model_errors` | `test_zero_extract_with_parse_errors_not_completed` |
| T-4 | Пауза по бюджету + resume теряют кандидатов до курсора (дефолтная collect-конфигурация) → неполное досье «успешно» | проба A: r1 candidates=1, r2 candidates=0, активировано только r2 | раннер персистит кандидатов прерванного прогона в staging **до** паузы (building-поколение job'а); при resume кандидаты сеются в движок (`resume_candidates`) — Layer B видит оба сегмента; финализация переиспользует то же поколение (дедуп по `(kind, text, target)` + `_restored`) и активирует **оба** сегмента одним атомарным шагом | `test_pause_stages_candidates_then_resume_activates_both_segments`, `test_resume_engine_receives_seeded_candidates` |
| T-5 | Сбой персистентации кандидатов до паузы → молчаливая paused с потерей сегмента | (новая ветка, появилась вместе с T-4) | если кандидаты есть, а staging не создан → job `failed`, `error_code=pending_staging_failed`, `reason_code=dossier_pending_staging_failed` (пауза запрещена: она молча теряла бы данные) | `test_pending_staging_failure_is_failed_not_silent_pause` |
| T-6 | Бюджет исчерпан на batch → частичный синтез + done (baseline-дефект §8.3.1) | baseline `run_dossier_rebuild` ставил `done`+`processed=total` | безусловно: budget → `budget_exhausted` без синтеза → `paused`, percent честный; `processed` не подменяется | `test_a89_budget_exhaustion_no_partial_synthesis`, `test_budget_exhaustion_paused_never_completed` |
| T-7 | Отмена/рестарт → ложный completed | — | кооперативная отмена → `cancelled`/`interrupted`; reconcile рестарта `paused→interrupted` с сохранением курсора; перепроверка cancel между последним batch и finalize | `test_cancel_raises_and_writes_nothing`, `test_restart_marks_paused_interrupted` |

Инвариант 2 (спека §3.3: «budget exhaustion, недоступность модели, parse error, отмена, рестарт никогда не дают completed») закрыт для всех воспроизводимых путей; нулевой результат при **полном корректном** проходе (0 ошибок) остаётся валидным `completed` (инвариант 14 — `test_empty_range_completed_zero_valid`).

### 4.2. Отказы данных и реклассификация

- **Потеря накопленного при активации:** staging-only построение; активация — одна короткая `write_transaction` (apply staged → prev `active→superseded` → `building→active`); строки superseded-поколения не удаляются; сбой активации → `failed` без деструкции (`test_activation_failure_is_failed_not_destroying`). Backup **до** активации (`memory_backup.migration_backup` → `backup_ref`; при reuse-поколении backup_ref обновляется свежим).
- **Авто-очистка confirmed:** отсутствует в full-контракте (D7; cleanup только в legacy-раннере при master OFF — паритет baseline). Ручные правки/overrides не затрагиваются (`test_activation_keeps_confirmed_and_overrides`).
- **Загрязнение субъектов:** локальные evidence-номера → постоянные SourceRef сразу после чанка (каждый чанк — свой `window_rows`); невалидный кандидат отбрасывается с `evidence_invalid`; N-1 name-резолв ограничен ростером scope; self_report/third_party по автору evidence-строки.
- **Дубли при повторе/resume:** дедуп записей (`person_fact_exists`), keyset-курсор без OFFSET, идемпотентная повторная активация (no-op на active), дедуп staged-элементов по ключу — перезапуск не удваивает связи (инвариант 4).
- **История портрета:** `upsert_generated_dossier` не стирает долгосрочную картину (`previous_text` + bounded `portrait_history`, contract_version 2).

### 4.3. Конкуренция и ресурсы

- Single-writer SQLite: записи активации/staging/job-store — короткие транзакции; LLM — вне транзакций; кросс-процессный chat-lock (1 активный LLM batch на чат).
- Потоковый keyset-проход (порции ≤ `MCA_DOSSIER_BATCH_MAX_MESSAGES`=500, деление на чанки) — архив не грузится в RAM и не отправляется одним промптом; OOM-профиль ограничен порцией.
- Кандидаты — отфильтрованное подмножество; backlog-артефакты — по batch на диск (fsync, tmp→replace).
- Отказ LLM не создаёт лавины: fail-open по чанку + честная остановка прохода (T-1/T-3), повтор — управляемый resume.
- M-2 (loader): полный стриминговый SHA-256 файла импорта порциями 1 MiB — память не зависит от размера файла; устранена коллизия «голова 256 KiB + size» (тихая потеря source records при регенерации крупного файла).

### 4.4. Наблюдаемость и R17

- `start`+терминальный `outcome` (`dossier_rebuild`), каскад (`dossier_cascade`); reason_code из словаря mca-13 (round 1: `model_unavailable`, `parse_error`, `dossier_pending_staging_failed` добавлены явно).
- job-view — R17-safe: числа/коды/`snapshot_ref`-basename; `target_name` и тексты фактов не отдаются; span-поля mca-17a через `ALLOWED_FIELDS`.
- Секреты не журналируются ни на одном пути (проверено Reviewer, п. «Focused audit»).

## 5. Откат

- **Hot:** `MCA_DOSSIER_REBUILD_ENABLED=false` → legacy-раннер (паритет baseline; под-гейты инертны). Состояния paused/failed нового контракта не мешают legacy-пути.
- **Cold:** `git revert` → базовый коммит Build (`4cb267a`); v20 аддитивна — старый код новые объекты не читает.
- **Точечный откат досье:** `backup_ref` (backup до активации) + повторная активация предыдущего поколения; restore БД — аварийный сценарий (R18).
- **Последствия round 1 для отката:** building-поколение с staged-кандидатами при hot-откате остаётся инертной строкой v20 (legacy не читает); при cold-откате — безвредные данные в аддитивных таблицах.

## 6. Остаточные риски (после round 1, все — non-blocking)

| ID | Риск | Оценка | Компенсация |
|---|---|---|---|
| R-a | Модель «мигает» (часть чанков ок, часть model_unavailable) при extracted>0 → `completed` с ошибками в счётчиках | Low | ошибки видимы (`errors`/`model_errors`/`rejected_by_reason`); consecutive-failure порог сознательно не введён (Builder-решение по review: «на усмотрение»); прод-мониторинг — mca-17a |
| R-b | Orphan building-поколения при терминальном failed (кандидаты не активируются) | Low | строки инертны до активации; следующая успешная пересборка создаёт новое поколение; ручная реактивация возможна API-уровнем |
| R-c | direct-режим (staging OFF): пауза extraction → портрет resume-сегмента без сегмента до курсора | Low | OFF — явный kill-switch (паритет baseline); H-1 требование покрывает дефолтную collect-конфигурацию; портрет — инкрементальное обновление (история сохраняется) |
| R-d | `percent=100` при paused, если весь диапазон просмотрен, но синтез не выполнен | Info | status/reason_code/`stage=synthesize` — честный сигнал; percent отражает просмотр, неуспех — статус |
| R-e | L1–L8 из review round 1 (dead knob, doc L2, tasks-hash repin, история портрета 4×400, каскад парадигм через Dream и пр.) | Low | перечислены в review.md «Non-blocking debt»; не эксплуатируют класс «нечестная финализация» |

## 7. Вывод

Архитектурная изоляция активации от hot-path доказана; бюджет/модель/parse/отмена/рестарт больше ни на одном воспроизводимом пути не дают ложного успеха; resume не теряет извлечённое (дефолтная конфигурация). Понижение R3 не инициируется: пересборка остаётся операцией, способной менять память субъектов, — компенсирующие контролы (staging/атомарная активация/backup/честная финализация/kill-switch) сохраняются обязательными.

**Binding:** файл действителен для состояния worktree на 01.10.2026 после реворка round 1 (см. `evidence.md` §8, WTH round 1). Изменение контрактов финализации/активации требует пересогласования этого анализа.
