# W3 — EVOL-007/008/009: виджет фактов и диагностика памяти

Lane: Builder, worktree `evol/impl`, 30.10.2026.
Источник: `plans/current_task.md` EVOL-007 (~L107–111), EVOL-008 (~L113–117), EVOL-009 (~L119–121).
Аудит линий: `plans/features/evol/audit/base-revalidation.md` (виджет `database.py` dossier_feed, случайная выборка без `created_at`).

Схема не менялась (`user_version` остаётся 39). Второй телеметрический стор не создавался. Расписание не менялось, прогоны не запускались. FTS/vector-поиск не трогался. `summary_prompts.py` / реестр промптов не трогались.

## EVOL-006 — отложено

Ревизия промпта экстракции (разовый запрос vs долговременный факт) требует bump фабрики в `prompt_registry.py`. Этот файл в этой волне принадлежит другой полосе. Текст фабрики в `summary_prompts.py` не менялся.

## EVOL-007 — что было сломано и что отдаёт бэкенд

Подтверждённый дефект: `dossier_feed` брал случайную выборку из пула `limit*20` и возвращал только `chat_id/name/fact`. Даты в ответе были невозможны.

Исправление в `services/database.py::dossier_feed` (население то же: confirmed, непустой fact, живой TTL, `target_user` задан):

* порядок `created_at DESC, id DESC` — новые записи первыми, без `RANDOM()`;
* в строке реальные поля: `created_at`, `message_timestamp`, `last_confirmed_at`, `kind`, `id`;
* даты не подменяются: нет `message_timestamp` — в ответе `null`, а не копия `created_at`.

Конверт виджета — `services.memory_diagnostics.new_facts_widget`:

* scope `chat:<id>` или явно `global` (два чата в запросе одного чата не смешиваются);
* `last_successful_extract_at` — последний успешный проход `FACTS_EXTRACT` (`outcome=success` или `skipped/no_new_contribution`) из `mca_events`;
* пустое состояние из данных, не из пустого списка само по себе: `empty` / `disabled` / `no_new_results` / `load_failed` / `not_yet_run`;
* если факты уже есть, а последний проход честно ничего нового не нашёл — факты остаются, `freshness=no_new_results` и дата прохода рядом;
* выключенный `flags.graph_rag_enabled` не прячет уже записанные факты (`updates_disabled=true`);
* сбой чтения не подменяется пустой лентой и не выдумывает факты (`load_failed`).

Отдельной колонки `extracted_at` в `graph_facts` нет. В конверте `extracted_at` равен `created_at` и помечен источником `graph_facts.created_at`. Это время записи экстракции, не дата события.

Шов для следующей UI-полосы: `web/api/oversight.py::dossier_feed` по-прежнему собирает свой словарь (`chat_id/name/excerpt/user_id/user_name`) и даты отбрасывает. Этот файл здесь не трогался. Порядок строк HTTP уже станет «новые первыми», потому что роут идёт по результату `dossier_feed`, но даты на экране появятся только когда UI-полоса прокинет поля или вызовет `new_facts_widget`.

## EVOL-008 — расписание и честный статус (прогоны не запускались)

Функция: `memory_cycle_status`. Состояние стадии: `disabled` (флаг выключен) / `never_run` (флаг включён, строк прогона нет) / `ran` (есть успех или ошибка). История не стирается при `disabled`: `last_success_at` / `last_error_*` заполняются, если строки есть.

Проверено по коду, не по живому продакшену (эта полоса без сети и без SSH):

| Стадия | Планировщик | Гейт | Дефолт env | Откуда дата последнего прогона |
|---|---|---|---|---|
| Экстракция фактов | Не отдельный крон. Живые хуки (`memorize_facts`) + крон сводки `hour=0,6,12,18` в `limits.summary_timezone` (дефолт `Asia/Yekaterinburg`), `summary_scheduler.py:140-141` | `flags.graph_rag_enabled` (в `memorize_facts` читается глобальный hot, не per-chat) | `GRAPH_RAG_ENABLED=true` | `mca_events` `FACTS_EXTRACT` |
| Sleep | Джоб `dream_tick` регистрируется всегда, `IntervalTrigger` `memory.dream_tick_minutes` (дефолт 60). Дистилляция в окне `[4, 6)` local | `memory.dream_enabled` (chat → global → env) | `DREAM_ENABLED=false` | `memory_dream_log` `kind=run/distilled status=ok`; ошибка — `kind=error`. Класса исключения в журнале нет |
| Deep Sleep | Джоб `deep_sleep_tick` на том же интервале. `after_sleep` (дефолт) после обычного сна; `fixed` — в `memory.deep_sleep_hour` (дефолт 7, TZ бюджета). Cooldown 20 ч (`_DEEP_SLEEP_MIN_INTERVAL_HOURS`) | `flags.deep_sleep_enabled`. Обычный сон этот флаг не включает | `DEEP_SLEEP_ENABLED=false` | успех `kind=deep_run status=ok`; сбой записи — `kind=deep_skip status=error` (класса исключения нет) |
| Личность | Отдельного джоба нет. Шаг `_run_persona_traits_step` внутри глубокого сна | `flags.persona_enabled` | `PERSONA_ENABLED=true` | `memory_dream_log kind=deep_traits status=done`; ошибка — `status=error` или `mca_events persona_traits outcome=failed` (класс — из `error_json.type`, если событие новее журнала) |

Наблюдение владельца («в другом чате пулы пусты, Deep Sleep выключен глобально») с кодом сходится: дефолт глубокого сна — выключен, джоб при этом зарегистрирован и на каждом тике сам решает не работать. Включённая личность при выключенном Deep Sleep — это `never_run` + `not_invoked_because=deep_sleep_disabled`, а не «личность выключена» и не повод форсировать прогон.

Per-chat override читается, только если вызывающий передал `flags` (тесты и будущий UI) или прогрет кэш `chat_params`. Без кэша источник помечается честно (`error` / `hot_fallback`), значение не выдаётся за прочитанный override чата. Живые timestamps двух продо-чатов эта полоса не снимала: нет доступа к продо-БД, выдумывать их нельзя. Функция вернёт их, когда её вызовут на этой БД.

## EVOL-009 — диагностика (данные, не экран)

Функция: `memory_health_diagnostics`. Поля из существующих таблиц:

* последний успешный extract / sleep / deep sleep / personality;
* `last_new_fact_at` = `MAX(created_at)` живых confirmed-фактов с `target_user`;
* счётчики: пропуски `FACTS_EXTRACT` по `reason_code`, пропуски сна по `kind:status`, число `unconfirmed` фактов;
* FTS vs vector: таблица `graph_facts_fts` / `graph_facts_vec` + внедряемая проверка runtime (`vector_runtime` / `vector_probe`);
* backlog индексации — число живых `graph_facts` без строки в `graph_facts_vec`. Если vec-таблицы нет, backlog = `null` и причина `vec_table_absent`, не ноль;
* последняя ошибка: более позднее из `mca_events.outcome=failed` (класс из `error_json.type`) и `memory_dream_log` со `status/kind=error`.

Инвариант: `embeddings_working` истинен только при режиме `vector` (таблица vec есть и runtime-проверка сказала да). Режим `fts_only` никогда не помечается как работающие embeddings, даже если заглушка runtime вернула true, а таблицы vec нет.

Фиктивный «показатель качества» не считается.

## Проверки

* `tests/test_evol007_new_facts_widget.py` — даты, порядок, изоляция чатов, пять пустых состояний, отказ чтения без выдуманных фактов.
* `tests/test_evol009_memory_diagnostics.py` — disabled vs never-run, ошибка/успех по чатам, FTS-only не равен vector-ok, backlog.
* Рядом: `tests/test_evol015_quote_pipeline.py`, `tests/test_webapp_round1020_ui.py::TestDossierBackend::test_dossier_feed_scope`.
* `compileall services`.

Сети, Telegram и полного набора тестов не было.

## §review-fix (EVOL-009, по вердикту Reviewer)

Блокер: у диагностики не было числа кандидатов. `mca_events.usage_json` не читался, а `unconfirmed_facts` кандидатами не является (это состояние фактов, а не результаты прохода).

Что сделано в `services/memory_diagnostics.py`:

* `_extract_usage(db, chat_id)` — чтение терминалов `FACTS_EXTRACT` (`outcome != 'start'`) в scope. `last_terminal` = последний проход: `at`, `outcome`, `reason_code`, `stage`, `pass_outcome` (это `usage_json.outcome`, т.е. настоящий исход прохода), `candidates` = `saved+skipped+deduped+superseded`, плюс сами `saved/skipped/deduped/superseded` и `text_only` по отдельности. `total` — сумма по проходам scope с явными `terminal_passes` / `passes_with_usage` / `passes_without_usage` / `covers_all_passes`; суммы считаются только по проходам с `usage_json`, поэтому частичное покрытие не выдаётся за полное. Старое событие без `usage_json` → `None` (неизвестно), никогда `0`. Поле отдано в `memory_health_diagnostics` как `extract_usage`; `counts.extract_skipped_by_reason` сохранён.
* `last_extract` виджета (EVOL-007) и диагностики теперь несёт те же счётчики и `pass_outcome`, `stage`.
* `_SUCCESS_OUTCOMES` больше не мёртвый: это исходы прохода из `summary_memory.outcome_map` (`success`/`all_duplicates`/`partial`/`text_only_vector_deferred`), их использует `_pass_ok`.
* `empty_state_reason` называет реальный исход последнего прохода: `empty:skipped:validation_failed`, `empty:failed:writer_failed`; для честного «новых нет» — `no_new_results:skipped:no_new_contribution`. Голого `empty` при сбое больше нет.
* `freshness`: `has_items` только при успешном проходе. Провал → `extract_failed`, пропуск по другой причине → `extract_skipped`, события недоступны или прохода нет → `unknown`.
* `schedule_view()`: у `deep_sleep` свой часовой пояс — `limits.worker_budget_tz` (`WORKER_BUDGET_TZ`), ровно как в `dream_worker._deep_tz_name` (`dream_worker.py:542-547`), где считаются его сутки/час. У `extract`/`sleep` остаётся `limits.summary_timezone` (крон сводки и окно дистилляции). В каждой секции добавлен `timezone_key`, чтобы соответствие было проверяемым.

Проверки (`tests/test_evol009_memory_diagnostics.py`, фикстуры без сети):

* агрегация из реальных строк `mca_events` (`_extract_pass` пишет `usage_json` так же, как `summary_memory.py:3759-3761` и `:3394-3416`), плюс `unconfirmed_facts` отдельно от кандидатов;
* старое событие без `usage_json` → `candidates/saved/text_only = None`, `covers_all_passes=False`; смешанная история — сумма только по покрытым проходам;
* проход с `write_failed` и `validation_failed` → `candidates=3`, `saved=0` (кандидаты не пропадают из-за нулевой записи);
* `empty_state_reason` и `freshness` по каждому исходу последнего прохода;
* `deep_sleep.timezone` = `WORKER_BUDGET_TZ`, `sleep`/`extract` = `SUMMARY_TIMEZONE`.

Прогон: `pytest tests/test_evol009_memory_diagnostics.py tests/test_evol007_new_facts_widget.py -q` — 18 passed. Коммитов нет, правки в рабочем дереве `evol/impl` (33a14034).

Уточнение к строке 83 по второму вердикту Reviewer: `candidates = saved+skipped+deduped`, `superseded` НЕ суммируется — писатель делает `superseded += 1` в той же итерации до `saved += 1` (`summary_memory.py:3682-3695`), т.е. замещённые старые факты входят в уже посчитанный `saved` (иначе двойной счёт: было `8`, стало `7`). `superseded` остаётся отдельным полем `last_terminal`/`total`, добавлено явное утверждение в тесте, что он не входит в `candidates`.
`deep_sleep.timezone` при пустом `WORKER_BUDGET_TZ` теперь `UTC` (`str(deep_tz or "UTC")`), как `dream_worker._deep_tz_name`, а не `SUMMARY_TIMEZONE`; добавлен тест на пустой `limits.worker_budget_tz`. Прогон: `pytest tests/test_evol009_memory_diagnostics.py tests/test_evol007_new_facts_widget.py -q` — 19 passed.
