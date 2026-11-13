# I2 - финальное ре-ревью кандидата `9be4227e` (SXR-I2-01, B1/B2)

**Решение: `Approved` для pre-deploy review. `SXR-I2-01` REVIEW + `READY_FOR_LIVE`.**
Блокирующих находок нет. B2 (docs) фактически не закрыт: полный `git diff --check` от базы всё ещё ругается на пустую строку в конце binding; это не влияет на код и приёмку I2.

## Кандидат

* HEAD: `9be4227eb12faa2c59a0a2ca4d1ee7384ec171d6`
* Код: `3a78f961d52abe2a532ba0e9d447d5f589c0f228`
* Тесты: `45bfe2a4` (4 точечные проверки потребителей)
* База: `d20a7f73`; предыдущий кандидат: `637c7f31`.
* Дифф `637c7f31..9be4227e`: 5 файлов, +172/-6: `web/api/memory_overview.py` (+21/-2), `services/experience_diagnostics.py` (+15/-2), `tests/test_sxr_i2_fresh_stream_drain.py` (+47), `tests/test_webapp_memory_overview_api.py` (+43), binding (+52). Только заявленные файлы; DDL/миграций/`config/settings.py`/планировщика/каталога параметров нет.
* `git diff --check` для `637c7f31..9be4227e` чист. Для полного `d20a7f73..9be4227e` остаётся `binding-i2-c5e63d9c.md:285: new blank line at EOF` (B2, docs-only).

## Implementation

`_opt_seconds` в `web/api/memory_overview.py` и `_opt_int` в `services/experience_diagnostics.py` реализуют контракт: `None` остаётся `None`, число приводится к int, нечисловой мусор даёт `None`. Оба места API (`_latest_job_async` и `memory_intel_funnels`) используют `_opt_seconds`; `fresh_lag.lag_seconds` в diagnostics использует `_opt_int`. Измеренный ноль при `cursor_distance` остаётся нулём; отрицательные значения `_opt_seconds` ограничивает нулём (снимок отрицательных не отдаёт). Других потребителей `lag_seconds` по grep нет.

## Test validity

* Кандидат: **17 passed** (контрактный набор), **29 passed** (17 + webapp API), **59 passed** (17 + 2 legacy + webapp API), широкий набор 14 файлов: **219 passed + 1 pre-existing** (`test_deep_sleep_not_mixed_with_lessons`).
* RED на `637c7f31` с новыми тестами: **2 failed / 2 passed** (падают оба сценария unknown, измеренный ноль зелёный).
* Мутация «вернуть None в 0» в обеих helper-функциях: **2 failed / 2 passed**; restore -> **4 passed**.

## Independent challenge

Отдельный probe (временный, удалён):
* снимок при недоступном замере: `lag_seconds=None`, `lag_seconds_source="unknown"`;
* сквозной payload: `_latest_job_async` -> **None**, `memory_intel_funnels` -> **None**, `_learning_analytics` -> **None**;
* измеренный ноль: снимок -> **0**, все три потребителя -> **0**;
* мусор: `_opt_seconds(None/"junk"/[])` -> **None**, `_opt_int(None/"junk"/[])` -> **None**; `0` -> **0**.
Четыре слоя согласованы; ложного нуля при неизвестности нет.

## Ledger (карту не редактировал)

`SXR-I2-01` (10 source-строк L01052, L01065-L01073; `live_required=true`, `live_when=postdeploy`):
* predeploy-часть: дренаж, честный `lag_rows`, F1, измеренный `lag_seconds`, сквозной контракт потребителей - evidence достаточно для **REVIEW**;
* production-дренаж 2M строк и стоимость `COUNT(*)`+`MIN(timestamp)` - **READY_FOR_LIVE**, только после контролируемого выката;
* `VERIFIED`/DONE не ставить.

## Findings

**B2 - non-blocking, docs.** `binding-i2-c5e63d9c.md` заканчивается пустой строкой (285); `git diff --check d20a7f73..9be4227e` даёт `new blank line at EOF`, хотя §11.3 утверждает «чисто». Диапазон `637c7f31..9be4227e` чист, поэтому остаток не виден в проверке только диапазона. Убрать последнюю пустую строку (файл должен заканчиваться одним переводом строки) и поправить строку §11.3; на код/приёмку не влияет.

Блокирующих находок нет. B1 закрыт, F1/F2 подтверждены.

## Postdeploy (live_required)

На выкаченном SHA: продвижение курсора на 2M backlog за несколько циклов; `lag_rows` равен COUNT-дистанции (базовая точка 2059418), а не pending; `lag_seconds_source` соответствует источнику (`cursor_distance`/`pending`/`unknown`); отсутствие роста `database is locked`/нагрузки от `COUNT(*)`+`MIN(timestamp)`; сходимость backlog; событие `experience.fresh_stream_lag`. Rollback: возврат на `d20a7f73` (2.58.199) и рестарт. Effective defaults: batches=12, budget=180, threshold=500, budgets off.

## Housekeeping

Одноразовые worktree `red`/`mut` и probe удалены; `unit-close` для `sxr-i2-review-r3` выполнен (`cleanup_complete=true`, `remaining=[]`). Worktree Builder сохранён. Секреты не печатались, production не затрагивался. Файл ревью новый (untracked); коммит/привязку к карте выполняет PM/Orchestrator.

## Next

Orchestrator: `SXR-I2-01` можно включить в релизный поезд как REVIEW + READY_FOR_LIVE. DevOps: выкат точного SHA и postdeploy-наблюдение. PM: убрать хвостовую пустую строку в binding перед коммитом. Эпик DONE не отмечать.
