# EVOL-014 — бэкенд инициативных мемов

Кандидат: worktree `evol/impl`, HEAD `be5ad652` (коммит не создавался).
Новый модуль и правки ниже — незакоммиченный diff этой полосы.

Живых отправок в Telegram нет. Заводское состояние функции — **выключено**.

## Архитектура

Мем — capability внутри существующего прохода `initiative.observe`, не отдельный cron и не замена текстовой инициативы.

- Точка вызова: `InitiativeObserverRunner._meme_phase` после scan/evaluate/diagnose. Ошибка мема не валит job текстовой инициативы.
- Выключение мемов (`flags.meme_initiative_enabled`, дефолт OFF) не трогает `INITIATIVE_OUTPUT_KINDS = ("initiative_reply",)`.
- Выключение Initiative (`observer_enabled()` ложен → `run()` выходит раньше фазы; плюс проверка внутри `consider_chat`) останавливает мемы.
- Свой вид выхода: `meme_initiative`. В общие счётчики реплик не входит.
- Контекст — один `chat_id`. SQL окна: `WHERE chat_id = ?`. Размер окна — настройка, дефолт 500, не кап.
- Выжимка — один вызов суммаризатора. Тяжёлый summary/writer-каскад не используется.
- Потолок длины считается до вызова и передаётся как `target_chars`. Источник: `explicit_override` | `admin_setting` | `model_capability` (минимум из заданных). Если выжимка длиннее цели — отказ `summary_failed/exceeded_precomputed_limit`, без среза.
- Image-конфиг не дублируется: те же ключи и `resolve_module_enabled` из `image_generation`. Причины: `image_module_off`, `image_provider_not_configured`, `image_provider_unhealthy`.
- Случайность: `mca_random_source.PURPOSE_MEME_TRIGGER` (`meme_trigger`) в `SANCTIONED_DRAW_PURPOSES`. Это не exploration-выбор и не новый probability-ключ (`choose()` по-прежнему отвергает purpose вне карты 10b). Недоступный draw и PRNG-подмена контура (`fallback_reason`) пишутся как `random_unavailable`. Локального `random` нет.
- Публикация: генерация может состояться, отправка — только если publish/recheck-гейт разрешил и есть sender. Гейт по умолчанию — `build_fresh_recheck_context` + `SendRecheck`. Сбой гейта блокирует отправку (`recheck_unavailable`), а не шлёт молча. Хук шлёт через `telegram_send.send_photo` только при привязанном bot и открытом гейте.

## Квота

Свой журнал, не `image_calls` и не `image_reservation`.

- Дефолт 3 на чат за календарные сутки в TZ чата. Нет настроенной зоны → UTC, `timezone_source=utc_fallback`.
- `0` запрещает генерацию и не равен тумблеру.
- Слот бронируется `BEGIN IMMEDIATE` **до** вызова провайдера. Считаются `reserved` / `provider_called` / `provider_failed`. Выжимка и сама публикация слот не добавляют. Неуспешный вызов провайдера слот занимает. Если вызов достоверно не начался (`called=False`) — слот снимается (`released`).
- Тот же `job_id` — replay без второго списания. Повторный платный вызов уже завершённого job не делается.
- Два чата — независимые счётчики. Смена лимита в середине дня не обнуляет расход; лимит ниже расхода блокирует новые слоты.
- Новый `day_bucket` начинает счёт заново. Рестарт читает тот же файл.
- Параллельные worker'ы не превышают кап (проверено: 8 потоков, лимит 3, прошло ровно 3; второй чат в том же прогоне держит свои 3).
- Каскад «несколько мемов сразу»: свежая чужая бронь `reserved` моложе 900 с блокирует новую попытку (`in_flight`), не забирая второй слот. Протухшая бронь каскад уже не держит, но в квоте остаётся.
- Cooldown конфигурируемый (дефолт 6 ч), не магический кап.

## Схема v40 — заметка интеграции

> **Обновлено (см. §integration в конце файла):** шаг v40 уже в раннере —
> `services/database.py`, `MigrationStep(40, "meme_quota_journal_v40")`,
> `_migrate_meme_quota_v40()`; он применяет `SCHEMA_DDL_SQLITE` из этого
> модуля. Текст ниже — исходное состояние полосы и оставлен для истории.

`pg_db.py` не менялся и не меняется: журнала квоты в PostgreSQL нет.

Следующий шаг схемы — **v40**, аддитивно, без сброса:

- таблицы `meme_initiative_reservation` и `meme_initiative_attempt`;
- DDL: `services/meme_initiative.py` → `SCHEMA_DDL_SQLITE` и `SCHEMA_DDL_POSTGRES`;
- шаг миграции должен вызвать этот DDL (`CREATE TABLE IF NOT EXISTS`), не копировать вторую версию;
- пока таблицы нет, `open_ledger()` возвращает None, попытка завершается `schema_absent`, провайдер не вызывается. Горячий путь таблицу сам не создаёт.

## Промпты

Зарегистрированы через `declare_prompt` + печать, без отдельного хранилища:

| block_id | константа | метка | печать |
|---|---|---|---|
| `initiative.meme.image` | `MEME_IMAGE_PROMPT` | `meme-image-evol014` | `f81fe7e4b505` |
| `initiative.meme.summary` | `MEME_SUMMARY_SYSTEM_PROMPT` | `meme-summary-evol014` | `8b0906ccbdaa` |

Заводской image-текст дословно: `Создай мем с шрифтом импакт:`
Формула: `{префикс} {выжимка}`.

`FACTORY_SET_SHA256_12`: `c1535d3d4252` → `03776db327b4`.
Чтение — `prompt_factory.meme_prompt_view` → `effective_prompt`. Ручной override помечается `differs_from_factory`. Каталожный `prompts.*` ключ не добавлялся: без записи в каталоге он уронил бы полноту реестра, а каталог этой полосе не принадлежит. UI-полоса может передать override тем же вызовом.

Пины отпечатка в `tests/test_p0_prompts_core.py` и `tests/test_expression_isolation_followup.py` сдвинуты вместе с новой заводской парой. Это не смена чужих канонов.

## Матрица проверок

`pytest tests/test_evol014_meme_initiative.py tests/test_evol018_prompt_audit.py` — 39 passed
(вместе с пинами отпечатка; фактический сбор — 29 + 10. Раньше здесь стояло «41
passed» — завышение на 2, исправлено в §review-fix). `compileall services` — без
ошибок. Сеть и Telegram не использовались.

| Приёмка | Доказательство |
|---|---|
| 1. Отдельный подсервис; мем OFF не глушит текст; Initiative OFF глушит мемы | `test_default_off_and_text_initiative_untouched`, `test_initiative_off_stops_memes` |
| 2. Санкционированный RNG; недоступность не маскируется | `test_purpose_is_sanctioned_extension_not_exploration`, `test_random_unavailable_is_recorded_not_masked`, `test_random_miss_is_logged` |
| 3. Один чат, окно настраивается | `test_window_is_configurable_and_chats_do_not_mix` |
| 4. Лимит до выжимки, без скрытого среза | `test_length_limit_is_applied_before_summarizer`, `test_overlong_summary_is_not_truncated`, `test_length_source_is_explicit` |
| 5. Дословный префикс, реестр, отличие ручной редакции | `test_factory_prompt_is_exact_literal_and_registered`, `test_manual_prefix_is_used_and_marked`, `test_evol018_prompt_audit` |
| 6. Неготовый image — конкретная причина, без провайдера | `test_image_dependency_reason_blocks_before_provider` |
| 7. Отдельные стадии, не смешаны с репликами | `test_analytics_are_separate_from_initiative` |
| 8. Гейт блокирует отправку, причина записана, генерация могла быть | `test_publish_gate_blocks_delivery_and_records_reason`, `test_sender_not_bound_does_not_send` |
| 9. Desktop/mobile/reduced-motion | не эта полоса (`web/**` не трогался). Бэкенд отдаёт effective state, источник лимита, окно, квоту и skip-причины для UI |
| 10. Дефолт 3, `0` глушит генерацию, исчерпание до провайдера | `test_quota_default_three_zero_disables_and_midday_limit`, `test_zero_and_exhausted_quota_skip_before_provider` |
| 11. Атомарность: два чата, конкуренция, retry, день/TZ, смена лимита | `test_concurrent_workers_cannot_exceed_cap`, `test_retry_same_job_does_not_double_count`, `test_day_boundary_and_timezone_label`, `test_new_day_bucket_resets_spent_slots`, `test_failed_provider_call_consumes_slot` |

Дополнительно: `schema_absent` без авто-CREATE; cooldown; in-flight; рестарт журнала на том же файле.

## Подтверждение

- Дефолт мемов **OFF**.
- Тесты не шлют в Telegram и не ходят в сеть.
- Пока нет таблицы v40, функция честно недоступна (`schema_absent`) и провайдера не вызывает.

## Остаточный риск

- Прод не начнёт генерировать, пока шаг v40 не создаст таблицы. Это намеренно, не скрытый fallback.
- Атомарность доказана на SQLite (`BEGIN IMMEDIATE`). PostgreSQL-DDL лежит рядом и на живом PG этой полосой не гонялся.
- Каталожный ключ и экран настроек — следующая UI-полоса. Бэкенд уже принимает override префикса через реестр.
- При включённом флаге, открытом гейте и привязанном bot хук наблюдателя может отправить фото. Пока флаг OFF, этого не происходит.

## §review-fix — мост к реальному конвейеру

Ревью вскрыло: фаза мемов не была подключена к настоящему конвейеру и не могла
сработать ни в одном чате.

### Что было сломано

1. **Несовпадение контракта.** `_meme_phase` передавал `llm=self._llm`, а у
   `consider_chat` не было такого параметра. Каждый проход по каждому чату падал
   на `TypeError` ещё до первой проверки, ошибку глотал `except` внутри
   `on_initiative_cycle`, строка попытки не писалась, счётчики оставались
   нулевыми, а аналитика показывала ложный `summary_failed`.
   RED (старый модуль, новый тест):
   `TypeError: consider_chat() got an unexpected keyword argument 'llm'`;
   попытка записывалась как `failed` с `reason=summary_failed`.
2. **Суммаризатор не был подключён.** `_default_summarize(None, …)` вызывался с
   жёстким `None`, а `_default_summarize` всегда бросал
   `RuntimeError('summarizer_unavailable')`. Даже без TypeError живой путь
   гарантированно заканчивался `summary_failed`, лёгкого контура не существовало.

### Что исправлено

- `consider_chat(..., llm=None, ...)` — единый контракт: настоящий LLM-клиент
  проходит от `_meme_phase` до выжимки.
- `_default_summarize(llm, rows, target, system_prompt, *, chat_id, model)` —
  реальный лёгкий вызов существующего клиента:
  `generate(messages, temperature=0.2, chat_id=…, module='initiative',
  step='meme_summary', correlation_id=…)`, один вызов на окно, без heavy
  summary-pipeline. Тяжёлого planner→writer→reviewer нет.
- Потолок длины по-прежнему считается ДО выжимки и уходит суммаризатору как
  `target_chars` в payload («уложись в N»), постфактум-обрезки нет; превышение →
  отказ `summary_failed / exceeded_precomputed_limit`.
- `cycle_exception` — отдельная причина: ошибка моста больше не выдаётся за
  провал выжимки, пишется строкой журнала (`considered` + `failed`) и видна в
  `skip_reasons`; при сбое всей фазы в payload пишется
  `meme.reason=cycle_exception` с классом ошибки.
- Детали ошибок выжимки больше не безликие: `exception:<КлассОшибки>`.
- `slot_released` — повтор job, чья бронь уже снята (`released`), не выдаётся за
  «суточную квоту»; квота при этом не считается исчерпанной.
- Проверка «генерация в этом чате уже идёт» перенесена ДО платной выжимки:
  свежая чужая бронь больше не съедает LLM-вызов впустую (порядок проверок — до
  дорогих вызовов).
- Причина блокировки публикации честная: гейт открыт, но отправителя нет →
  `publish_blocked / publisher_not_bound` (раньше в detail попадало `ok`).

Модель выжимки: отдельного клиента под неё не создаётся, поэтому
`initiative.meme_summarizer_model` не подменяет модель потихоньку — при отличии
от фактической модели общего клиента пишется INFO, значение остаётся видимым в
настройках. Это ограничение зафиксировано, а не замаскировано.

### Проверки после правки

`pytest tests/test_evol014_meme_initiative.py tests/test_evol018_prompt_audit.py -q`
— **44 passed** (было 39, из них 5 новых). Смежные полосы инициативы:
`test_asap8_f6_initiative`, `test_asap8_v63_b01_initiative_observer`,
`test_p0_initfix_initiative_observer`, `test_initiative_delivery_telemetry`,
`test_p0_prompts_core`, `test_expression_isolation_followup` — 115 passed.
`compileall` — без ошибок. Сеть и Telegram не использовались.

| Что именно проверено | Тест |
|---|---|
| Фаза мемов реально доходит до генерации без заглушки `on_initiative_cycle` (стадии `considered/eligible/summary/image_generation`, нет `summary_failed` и `cycle_exception`) | `test_meme_phase_runs_real_pipeline_and_journals_stages` |
| Ошибка моста записывается как `cycle_exception`, а не `summary_failed` | `test_meme_phase_bridge_exception_is_cycle_exception` |
| Лёгкая выжимка совпадает с контрактом НАСТОЯЩЕГО `LLMClient.generate` (система+payload, `target_chars`, один вызов, транспорт подменён) | `test_default_summarizer_matches_real_client_contract` |
| Повтор снятой брони → `slot_released`, не `daily_quota_reached` | `test_retry_of_released_slot_is_not_daily_quota` |
| Guard «уже идёт» отсекает попытку до платной выжимки | `test_in_flight_check_precedes_paid_summary` |

### Остаточный риск после правки

- Прод по-прежнему не начнёт генерировать, пока шаг v40 не создаст таблицы, а
  `flags.meme_initiative_enabled` выключен с завода. Живой LLM-вызов в тестах не
  делался: проверен контракт клиента, а не реальный провайдер.
- Модель выжимки задаётся общим клиентом (см. выше) — не скрытая подмена, а
  явное ограничение текущего пути.

## §integration — шаг схемы v40 зарегистрирован (находка DevOps закрыта)

Находка: `services/database.py` шага v40 не знал. Заметка «Схема v40» выше
описывала интеграцию как задачу «следующей полосы», но в раннере её не было:
на проде `PRAGMA user_version` доходил до 39, таблиц журнала квоты не
существовало, `open_ledger()` каждый проход возвращал `None`, и каждая попытка
честно, но навсегда завершалась `schema_absent`. Провайдер не вызывался —
мемы не могли сгенерироваться ни в одном чате.

### Что изменено

- `services/database.py`: `_SCHEMA_VERSION_MEME_QUOTA = 40`,
  `MigrationStep(40, "meme_quota_journal_v40")` сразу после v39 и
  `DatabaseService._migrate_meme_quota_v40()`. Шаг аддитивный: применяет
  `meme_initiative.SCHEMA_DDL_SQLITE` (`CREATE TABLE/INDEX IF NOT EXISTS`) —
  второй копии DDL в `database.py` нет, владелец схемы остаётся один;
  `PRAGMA user_version = 40` — внутри шага, запись в `schema_migrations` —
  раннером (`INSERT OR REPLACE`, одна строка на версию). Повтор и рестарт —
  no-op, существующие строки не UPDATE/DELETE-ятся.
- `services/meme_initiative.py`: `SCHEMA_MIGRATION_STEP_NAME` (одно имя шага
  для книги схемы, заметки и тестов); `schema_integration_note()` переписана —
  шаг зарегистрирован, поэтому `schema_absent` теперь означает «миграция не
  применилась на этой БД», а не штатный режим работы.
- `services/pg_db.py`: **не менялся, намеренно.** Журнал квоты — SQLite-файл
  рядом с сообщениями (`SqliteQuotaLedger` открывает его по пути БД), PG-журнала
  нет. Регистрация PG-таблиц создала бы пустые таблицы, которые никто не читает,
  и выдавала бы несуществующую поддержку PostgreSQL. `SCHEMA_DDL_POSTGRES`
  остался справочной формой контракта и помечен в коде как незарегистрированный.
- Горячий путь по-прежнему не создаёт схему сам: `open_ledger()` только
  проверяет наличие таблицы. После миграции feature-detect — это штатный путь.

### Проверки

- `tests/test_evol014_meme_initiative.py` — **39 passed** (было 34, +5):
  регистрация шага и владение DDL, свежая БД 0→40 с таблицами/индексами,
  апгрейд v39→40 без потери данных (строка сообщения и checksum книги v39
  совпадают), публикация мема на РЕАЛЬНОЙ БД (окно читается из `smart_messages`,
  бронь и стадии лежат в настоящих таблицах, кап и replay держатся на файле),
  рестарт — no-op с сохранённым расходом квоты.
- `tests/test_evol016_prompt_journal_v39.py` — **6 passed**. Пины
  `user_version` пересчитаны честно: свежая БД и рестарт теперь 40 (последняя
  версия схемы), проверка книги v39 и её единственной строки сохранена.
- Смежные пины схемы — **446 passed** одним прогоном:
  `test_mca05_episodes_stories_round1027`, все `test_mca19_block_*` +
  `test_mca19_rework_r1`, `test_mca14_schema_additive_round1027`,
  `test_database`, `test_hot_migration`, `test_evol015_quote_pipeline`,
  `test_samples_acceptance`, `test_samples_categories`,
  `test_samples_factory_persist`.
- Застаревшие пины «последней версии схемы» там, где файл и так краснел:
  `tests/test_t5150_startup_migrations_round1046.py` (`user_version = 35`,
  `pending=[33, 34, 35]`, **7 passed**) и
  `tests/test_asap7_direct_settings.py` (`== 35` в трёх местах, **20 passed**).
  Оба файла не про мемы: они пинили номер версии числом эпохи и краснели
  ещё с v36. Значения выводятся из раннера (`_LATEST_VERSION`,
  `_PENDING_FROM_32`, `_frontier()`), проверяемое поведение (guard→DDL→book,
  retry, лог-след, идемпотентность v35) не ослаблено: неизвестный/пропавший
  шаг по-прежнему ломает прогон.

TEST-LIFECYCLE: CONTRACT owner=EVOL-014 (§integration, шаг схемы v40).

### Что проверить после деплоя

- `PRAGMA user_version` на прод-БД = 40 и в `sqlite_master` есть обе таблицы
  журнала; в логе — `migration v40 applied in ... | meme_quota_journal_v40`.
- `GET /api/initiative/meme-settings` отдаёт `schema_present: true`
  (до этого был `false`); квота дня считается по реальной таблице.
- Генерация по-прежнему требует `flags.meme_initiative_enabled` (заводской
  OFF) — версия схемы сама мемы не включает.


### Замечено попутно (не моя полоса, не блокирует)

`tests/test_samples_fewshot.py::test_section2_texts_are_byte_exact` и
`::test_rendered_layer_uses_section2_texts` красные на этом кандидате:
коммит `0866264c` (speech-p0-a1, «точные тексты §2») поменял тексты в
`services/mca_expression.py` и обновил пины в других файлах, но локальные
константы `EPISODIC/FREQUENT_TEXT` в этом тесте не тронул. К схеме v40 и
мемам отношения не имеет — оставлено владельцу той полосы.

### Остаточный риск после интеграции

- PostgreSQL-журнала квоты нет и не появилось: на PG-контуре функция остаётся
  недоступной (`schema_absent`). Это ограничение, а не скрытый fallback.
- Атомарность по-прежнему доказана на SQLite (`BEGIN IMMEDIATE`); прод-БД
  получает таблицы миграцией при старте, живой прогон квоты на прод-данных —
  задача деплоя, а не этой правки.

## Для владельца

Инициативные мемы сделаны как отдельный режим внутри обычной инициативы, по умолчанию выключенный. Бот не рисует мем, если выключена сама инициатива, нет генерации картинок, кончилась суточная норма (с завода 3 на чат) или квантовый жребий недоступен — и не подменяет это тихим случайным числом. Заводская фраза картинки ровно «Создай мем с шрифтом импакт:». В чаты из этих проверок ничего не отправлялось. Раньше здесь было сказано, что ждём «ещё шаг базы v40 и экран настроек»; теперь таблицы журнала квоты создаются миграцией v40 при штатном старте, и функция перестаёт молчать по причине «нет схемы». Экран настроек в вебе уже есть.

После доработки по ревью мемы действительно подключены к обычному проходу инициативы: выжимка собирается тем же llm-клиентом, что и остальные лёгкие вызовы, а любая поломка самого моста пишется отдельной причиной, а не выдаётся за «не собралась выжимка». Живой генерации в проверках не было.

