# I2 - независимое ревью кандидата `e43fea22` (SXR-I2-01)

**Решение: `Approved` для pre-deploy review. Эпик не DONE.**
Один низкоприоритетный in-scope остаток (ветка ошибок замера) не блокирует приёмку I2 и не отменяет обязательную postdeploy-проверку.

## Кандидат

* HEAD: `e43fea22fdb93dad6a0277908d917f3430fc2ca1`
* Код: `c5e63d9c37612ac3fe1e20f39f98b763ab43726a`
* Тесты: `21781f8cd4d7bddb389875bec5892e93b869c574`
* База: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199, deployed)
* Ветка `smart/i2-stream`; worktree Builder сохранён.
* Дифф `d20a7f73..e43fea22`: 7 файлов, +1281/-181: `services/mca_experience_jobs.py` (+546/-180), `services/experience_diagnostics.py` (+8), `web/api/memory_overview.py` (+10), 2 legacy-теста (+12), новый `tests/test_sxr_i2_fresh_stream_drain.py` (547), binding evidence (159). DDL/миграций/`config/settings.py`/планировщика/каталога параметров нет. `git diff --check` чистый.

**Stash-происхождение.** Текущие `stash@{0}`/`stash@{1}` к I2 не относятся (другая база/чужой тест); применённый I2-стэш уже удалён, побайтовое сравнение с ним недоступно. Проверено по содержимому коммита: чужих файлов/ханков нет, все изменения соответствуют заявленному механизму.

## Implementation

Проверены: цикл `_semantic_pass` (батч-бюджет 12 + wall-clock 180с, остановки на пустом/отложенном бэклоге, `LLM is None`, `raw is None`, исчерпании бюджета); `_semantic_extract` (замер lag в `finally` до снимка/события); `_checkpoint` после каждого батча + `heartbeat`; `_inherit_cursor`/`semantic_backlog` (наследование `interrupted`, max-merge позиций); `_measure_semantic_lag` (`MAX(id)` + `COUNT(*)` после курсора, не более 16 чатов, `partial`); `semantic_progress_snapshot` (pending отдельно от измеренной дистанции); `_note_fresh_lag` (порог 500 не тронут); `_archive_pass` (блокировка по `lag_actionable_rows`); `_semantic_chat_order` (чаты `behind` участвуют при pending=0); API/снимок. Курсор двигается только через `_book_semantic_window` (`max(current, advanced_to)`), перемотки/массового перепроцессинга нет; ссылок на `budget_gate`/`budgets_enabled` нет.

## Test validity

* Новые 11 тестов прочитаны: проверяют наблюдаемые результаты (курсор, throughput, батчи, lag/pending, событие, crash/resume, изоляцию чатов, границы бюджета), а не имена функций. В `test_run_bounded_by_wall_clock_budget` одна строка-выражение без `assert` (косметика, остальные проверки не ослабляет).
* Кандидат: **11 passed**; те же тесты на базе (код откачен, тесты оставлены): **11 failed**. RED подтверждён.
* `11 новых + 2 legacy + webapp API`: **51 passed**.
* Широкий набор (14 файлов): **219 passed, 1 pre-existing failure**.
* Мутация (удалён per-batch checkpoint+heartbeat в одноразовом worktree): `test_crash_between_batches...` и `test_drain_advances...` дают **2 failed**; restore `git checkout --` даёт **2 passed**.
* Pre-existing: `test_mca16_experience_block_d_round1039.py::test_deep_sleep_not_mixed_with_lessons` падает и на базе (docstring модуля содержит `graph_facts`). BACKLOG_ONLY.
* `test_cfg03_param_audit::test_visible_dead_knobs...` (`flags.dig_pre_gate_enabled`) падает одинаково на базе и на полном checkout кандидата, к I2 не относится; worktree кандидата sparse, поэтому часть `plans/docs` там отсутствует (среда, не коммит). `test_param_catalog.py` зелёный: новые hot-ключи каталог не ломают.

## Independent challenge

* **Production-подобный сценарий** (одноразовый probe, default-бюджеты): 2059 строк, 4 прогона по **600/600/600/259** строк, `lag_rows` **1459, 859, 259, 0**, `lag_source=cursor_distance`, `pending_rows=0`, ровно **42** LLM-батча, ни одна строка не отправлена дважды, курсор на последней строке, следующий тик `not_due`. Потолок 12x50 на одном чате и честный lag подтверждены на масштабе около production, а не только на 125 строках.
* 17 чатов: `chats=17`, `measured_chats=16`, `partial=True`, `rows=32`. Заявленный partial-режим работает.
* API-проекция: `semantic_progress` возвращает `lag_rows=2059418`, `pending_rows=3`, `lag_source=cursor_distance` из checkpoint.
* Ветки ошибок замера (см. F1): при падении `MAX(id)` наблюдено `available=True, chats=0, partial=False`; при падении `COUNT(*)` наблюдено `rows=0, partial=True`. В обоих случаях снимок отдаёт `lag_rows=0` с `lag_source=cursor_distance`; заявленный в binding §2 `available=False` для этих ошибок не срабатывает (достижим только при падении `_semantic_chats_behind` целиком).

## Ledger (карту не редактировал)

`SXR-I2-01` (10 source-строк: L01052, L01065-L01073; `live_required=true`, `live_when=postdeploy`):

* predeploy-часть (причина, дренаж, lag, отсутствие потери/дублей, crash-safe, per-chat изоляция, порог/курсор не тронуты): evidence достаточно для **REVIEW**;
* production-дренаж 2M строк и стоимость `MAX/COUNT`: **READY_FOR_LIVE**, только после контролируемого выката. `VERIFIED`/DONE не ставить.

## Findings

**F1 - low, non-blocking, in-scope остаток.** Ошибка чтения при замере lag даёт ложный ноль без честного fallback. Repro: в `ExperienceReviewRunner` подменить `_chat_max_message_id` на `raise RuntimeError` (или `_chat_rows_after`) и вызвать `_measure_semantic_lag` на payload с курсором 0 и pending=3: получаем `available=True, rows=0/chats=0, partial=False` (для COUNT `partial=True`); снимок отдаёт `lag_rows=0, lag_source=cursor_distance`. Влияние: один 15-минутный цикл может показать "догнали" и не выпустить WARN; данные/курсор не страдают. Минимальная правка: при непустом `behind` и `measured == 0` (или при любом failed COUNT) ставить `available=False`, чтобы снимок честно падал на pending; при желании отдавать `lag_partial` в API. Ответственный Builder, в том же релизном поезде, не блокер I2.

**F2 - note.** `lag_seconds` по-прежнему считается от возраста pending-записей; при заниженном счётчике он может быть 0 при `lag_rows>0`. Владельческое событие использует `lag_rows`, поэтому приёмку не блокирует; учесть позже.

**F3 - note.** Заявление "watchdog 60с не примет живую задачу" верно лишь пока процесс один и APScheduler держит `max_instances=1`: один LLM-вызов имеет таймаут 90с больше 60с stale, heartbeat обновляется только после батча. Дублирующего worker'а не воспроизвёл; при переходе к многопроцессности поднять stale выше таймаута вызова или heartbeat'ить внутри вызова.

**F4 - pre-existing, BACKLOG_ONLY.** `test_deep_sleep_not_mixed_with_lessons` падает на базе (docstring `graph_facts`), кандидат эту строку не добавлял.

**F5 - pre-existing/env.** `test_cfg03_param_audit` падает одинаково на базе и кандидате (`flags.dig_pre_gate_enabled`); sparse-checkout кандидата скрывает `plans/docs`, это не регрессия I2.

## Postdeploy (обязательно, live_required)

Только на выкаченном SHA: фактическое продвижение курсора на 2M backlog за несколько циклов; `lag_rows` равен COUNT-дистанции (базовая точка 2059418), а не pending; отсутствие роста `database is locked`/нагрузки от `MAX(id)`/`COUNT(*)`; сходимость backlog; событие `experience.fresh_stream_lag` с измеренным lag; API-снимок. Rollback: возврат на `d20a7f73` (2.58.199) и рестарт. Проверить effective defaults: batches=12, budget=180, threshold=500, budgets off.

## Housekeeping

Одноразовые worktree (`base-red`, `mut`) и probe-файл удалены, `run-close`/`unit-close` выполнены (`cleanup_complete=true`, `remaining=[]`). Worktree Builder сохранён для DevOps/интеграции. Секреты не печатались, production не затрагивался. Файл этого ревью новый (untracked); коммит/привязку к карте выполняет PM/Orchestrator вместе с REVIEW-строками.

