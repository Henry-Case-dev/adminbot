# I2 - ре-ревью кандидата `637c7f31` (SXR-I2-01, F1/F2)

**Решение: `Needs Fixes` (узкий остаток F2 в потребителях).**
Дренаж, F1 и измеренный `lag_seconds` подтверждены; снимок честно отдаёт `None`, но API и diagnostics по-прежнему превращают его в 0, что расходится с требованием "неизвестно -> None, не 0" и с формулировкой "API/снимок/diagnostics согласованы".

## Кандидат

* HEAD: `637c7f31e95f17e9ba46222178288b12547a99b4`
* Код F1/F2: `08838eacd0b7105a772975ee611b76ce0517d351`
* Тесты: `fa1bdb233d87d68a641b8e2d8c0cfd794765bfa1`
* Предыдущий кандидат: `e43fea22`; исходная база: `d20a7f73`.
* Дифф `e43fea22..637c7f31`: 5 файлов, +292/-11: `services/mca_experience_jobs.py` (+84/-11), `services/experience_diagnostics.py` (+3), `web/api/memory_overview.py` (+6), `tests/test_sxr_i2_fresh_stream_drain.py` (+134), addendum в binding (+76). Только заявленные файлы; DDL/миграций/`config/settings.py`/планировщика/каталога параметров нет.
* `git diff --check` НЕ чист: `binding-i2-c5e63d9c.md:235: new blank line at EOF` (docs; поправить в том же проходе).

## Проверено независимо

**F1.** В `_measure_semantic_lag` при непустом `behind` и `measured == 0` результат остаётся `available=False`, выставляются `chats`, `measured_chats=0`, `failed_chats`, `partial=True`; снимок уходит на `lag_source="pending"`. Воспроизведено тестом и отдельным probe: все COUNT падают -> `available=False`, `failed_chats=1`, `partial=True`, `lag_seconds=None`, `lag_seconds_source="unknown"`. Частичный сбой (2 чата, один COUNT падает) -> `available=True`, `measured_chats=1`, `failed_chats=1`, `partial=True`, `lag_rows=2`, `age_seconds=100`. Ложного `cursor_distance` с нулём нет.

**F2.** `_chat_rows_after` одним запросом отдаёт `COUNT(*)` и `MIN(timestamp)`; `age_seconds` считается от самой старой необработанной реплики. Проверено: pending=0, две строки с ts now-3600 и now-60 -> `lag_rows=2`, `lag_seconds>=3590`, `lag_seconds_source="cursor_distance"`. Строки с timestamp=0 -> `lag_rows=2`, `lag_seconds=None`, `lag_seconds_source="unknown"`. Замер недоступен, pending знает возраст -> `lag_seconds=120`, `lag_seconds_source="pending"`. Измеренный ноль: пустая БД, нет `behind` -> `available=True`, `rows=0`, `failed_chats=0`, `partial=False`, `age_seconds=0`, `lag_seconds_source="cursor_distance"` (ноль только как реально измеренный).

**Тесты.** Кандидат: 15 passed; 55 passed (15 + 2 legacy + webapp API); широкий набор 14 файлов: 219 passed + 1 pre-existing (`test_deep_sleep_not_mixed_with_lessons`). RED на `e43fea22` с новыми тестами: 4 failed / 11 passed (ровно F1/F2-тесты). Мутация отключения F1-guard (`if False and behind and measured == 0`): 3 failed / 12 passed; restore -> 15 passed.

**Согласованность потребителей.** Снимок при недоступном замере отдаёт `lag_seconds=None`, `lag_seconds_source="unknown"`. Сквозной probe: `memory_overview._latest_job_async` возвращает `lag_seconds=0`, `lag_seconds_source="unknown"`; `experience_diagnostics._learning_analytics` возвращает `lag_seconds=0`, `lag_seconds_source="unknown"`. То есть значение 0 всё ещё подставляется на границе API/diagnostics, хотя снимок его уже не содержит.

## Findings

**B1 - blocking, F2 downstream.** Неизвестный возраст (`lag_seconds=None`, source `unknown` в снимке) превращается в 0 на выходе API и diagnostics:
* `web/api/memory_overview.py:137` (`_latest_job_async`) и `web/api/memory_overview.py:344-345` (`memory_intel_funnels`): `int(progress.get("lag_seconds") or 0)`;
* `services/experience_diagnostics.py:1332`: `_int(progress.get("lag_seconds"))` (helper `_int` возвращает 0 для `None`).

Repro (временный probe): payload review-job с `semantic_progress = {lag_seconds: None, lag_seconds_source: "unknown", lag_rows: 0, lag_source: "pending"}`; `_latest_job_async` -> `lag_seconds=0, source=unknown`; `_learning_analytics` -> `lag_seconds=0, source=unknown`. Ожидание по требованию: `None` (JSON null) и там. Влияние: owner-facing API/diagnostics всё ещё показывают "0с" при неизвестности; `lag_seconds_source` это частично маскирует, но требование "неизвестно -> None, не 0" и "API/снимок/diagnostics согласованы" не выполнено. Addendum §10.2 сам противоречит себе: "ноль больше не подставляется", затем "потребители `int(x or 0)` сохраняют контракт".

Минимальная правка: в двух местах API и в diagnostics сохранять `None`, когда значение снимка `None` или `lag_seconds_source == "unknown"`; добавить точечные проверки потребителей (webapp API + diagnostics) на `None`; поправить формулировку addendum. Это три однострочные правки плюс тесты.

**B2 - non-blocking, docs.** `git diff --check` не чист: лишняя пустая строка в конце `binding-i2-c5e63d9c.md` (строка 235). Убрать в том же проходе; на код не влияет.

## Ledger (карту не редактировал)

`SXR-I2-01` (10 source-строк L01052, L01065-L01073; `live_required=true`, `live_when=postdeploy`):
* дренаж, честный `lag_rows`, F1, измеренный `lag_seconds`, RED/GREEN и мутация подтверждены;
* REVIEW пока не готов: остаётся B1 (явное требование F2). После правки и точечного прогона потребителей строка может стать REVIEW + READY_FOR_LIVE;
* `VERIFIED`/DONE не ставить; production-дренаж и стоимость `COUNT/MIN` остаются postdeploy.

## Postdeploy (без изменений)

На выкаченном SHA: продвижение курсора на 2M backlog за несколько циклов; `lag_rows` равен COUNT-дистанции (базовая точка 2059418), а не pending; `lag_seconds_source` соответствует источнику; отсутствие роста `database is locked`/нагрузки от `COUNT(*)`+`MIN(timestamp)`; сходимость backlog; событие `experience.fresh_stream_lag`. Rollback: возврат на `d20a7f73` (2.58.199) и рестарт. Effective defaults: batches=12, budget=180, threshold=500, budgets off.

## Housekeeping

Одноразовые worktree `red`/`mut` и probe-файл удалены; `unit-close` для `sxr-i2-review-r2` выполнен (`cleanup_complete=true`, `remaining=[]`). Worktree Builder сохранён. Секреты не печатались, production не затрагивался. Файл ревью новый (untracked); коммит/привязку к карте выполняет PM/Orchestrator.

## Next

Builder: B1 (None в API/diagnostics вместо 0) + B2 (пустая строка EOF), затем повторно прогнать 15/55 и точечные consumer-тесты. Reviewer: фокусное ре-ревью только этих мест. Orchestrator: `SXR-I2-01` пока не включать в REVIEW-поезд; после правки выкат и postdeploy-наблюдение.
