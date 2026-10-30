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

`database.py` / `pg_db.py` **не менялись**. v39 занят журналом промптов.

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

`pytest tests/test_evol014_meme_initiative.py tests/test_evol018_prompt_audit.py` — 41 passed (вместе с пинами отпечатка). `compileall services` — без ошибок. Сеть и Telegram не использовались.

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

## Для владельца

Инициативные мемы сделаны как отдельный режим внутри обычной инициативы, по умолчанию выключенный. Бот не рисует мем, если выключена сама инициатива, нет генерации картинок, кончилась суточная норма (с завода 3 на чат) или квантовый жребий недоступен — и не подменяет это тихим случайным числом. Заводская фраза картинки ровно «Создай мем с шрифтом импакт:». В чаты из этих проверок ничего не отправлялось. Чтобы функция заработала на сервере, нужен ещё шаг базы v40 и экран настроек; до этого она честно молчит.
