# Мультимодальная видео-выжимка + Tool Calling + фиксы реакций + UX/UI админки

Эпик 04.09.2026, 4 части. Ссылки: `plans/features/multimodal-summarization-tools-reactions-ui/tasks.md` (T1–T34), живой план `plans/docs/memory-project-overview.md:38-45`.

## 1. Обзор (Overview)

Эпик закрывает 4 независимые линии развития бота и его админки:

1. **Каскадная мультимодальная видео-выжимка (Part 1).** Раньше «перескажи видос» (YouTube) работал только по субтитрам (текст), а видео без субтитров не пересказывалось. Теперь бот сначала пытается «посмотреть само видео» мультимодальной моделью через OpenRouter (`video_url` в content): L1 — `models.video_primary_model` (дефолт `minimax/minimax-m3:free`), L2 — `models.video_fallback_model` (дефолт `google/gemma-4-31b-it:free`), L3 — прежняя логика субтитров. Любой сбой L1/L2 молча уводит на следующий уровень; юзер никогда не видит ошибок промежуточных уровней.
2. **Tool Calling (Part 2).** Главный диалоговый подсервис (`direct_chat`) получает два инструмента — `execute_web_search` (каскад Tavily→Exa→DDG через существующий `SearchAggregator`) и `query_chat_memory` (опрос истории чата/фактов через `MemoryManager`). Модель сама решает, когда их вызвать; цикл `tool_calls` → исполнение → `role:"tool"` повторяется с жёстким лимитом итераций; при недоступности tool-режима провайдера — бесшовный откат на обычный ответ. Ручные триггеры «найди/загугли» не меняются.
3. **Фиксы реакций (Part 3).** Тумблеры-гейты (default `false`) для «Вася ↔ АДМИН», «куча → ДАЛБАЕБ», мимикрии в common и мимикрии на Леху (бывшего Alan); строгий гейт медиа `slavic_chlen.mp4` по `reactions.slavik_user_id`; переименование «Alan/Алан» → «Леха» в отображаемых текстах UI/параметров (ключи БД/env-имена и код-идентификаторы не трогаются).
4. **UX/UI админки (Part 4).** Реорганизация вкладок («LLM Провайдеры», «Промпты», «Лимиты», «Память и RAG», «Реакции и Триггеры», «Доступы», «Статус»), консолидация разрозненных настроек памяти, Key-Value-редактор для `limits.summary_aliases`, устранение дублирования и остаточного нейминга Alan.

Сценарии пользователя (коротко):

- Юзер кидает YT-ссылку + «че за видос»: бот смотрит ролик сам (L1); если модель недоступна — запасная (L2); если нет — старые субтитры (L3). При любых сбоях промежуточных уровней — тишина на уровне, итог либо выжимка, либо привычные фразы ошибок (как сегодня).
- Владелец в админке включает «Мимикрия включена» и «Мимикрия Лехи» → бот передразнивает Леху. Включает «Словесные реакции» → оживают «Вася→АДМИН» и «куча→ДАЛБАЕБ». Гифка Славика уходит строго Славику и только по его ID.
- Владeлец в админке правит алиасы людей парами «ID → имя» в Key-Value-редакторе вместо ручного JSON.
- В прямом чате модель сама решает: «загуглить» (инструмент веб-поиска) или «вспомнить из памяти» (инструмент памяти), когда ответ требует внешних/исторических данных.

## 2. Требования (Requirements)

### Функциональные

**Часть 1 — видео-каскад**

- FR-1. Новые настройки `models.video_primary_model` (default `minimax/minimax-m3:free`) и `models.video_fallback_model` (default `google/gemma-4-31b-it:free`) читаются через `hot.get` (фолбек — поля `Settings`), редактируются в админке без рестарта.
- FR-2. Пересказ YouTube-видео пробует мультимодальный путь ДО субтитров: L1 (primary) → L2 (fallback) → L3 (старая логика: субтитры + текст через основной LLM).
- FR-3. Запрос в OpenRouter по спецификации `video_url`: `content = [{"type":"text","text":...},{"type":"video_url","video_url":{"url": <полный YT URL>}}]`; модели L1/L2 задаются ключами FR-1; ключ доступа — `keys.openrouter_api_key` (пусто → мультимодальный путь полностью пропущен, WARNING, сразу L3 — прецедент D104).
- FR-4. Graceful degradation: L1 упал → L2 (WARNING-лог); L1 и L2 упали → L3 без каких-либо сообщений юзеру об уровнях; исключения уровней наружу не пробрасываются.
- FR-5. Успешный результат любой ступени — обычный текст выжимки (тот же стиль, cleanup, `{max_symbols}`), кэшируется в smart_cache как раньше (кэш — только успешный результат, ключ по `video_id`); `_memorize_youtube` — только на пути субтитров (L3), как сегодня.
- FR-6. Классификация сбоя уровня: HTTP 400/401/402/403/404/415/422/429/5xx, транспортная ошибка, таймаут уровня, пустой ответ (`content` пуст/`None`) — всё это «уровень упал». Ретрай уровня — 1 повтор только на транзиентное (429/5xx/транспорт, backoff 2с).
- FR-7. «Неподдерживаемый формат видео» отдельно не классифицируется: любой не-2xx (в т.ч. 400/415 «не могу скачать/распарсить видео») — обычный сбой уровня → следующий уровень.
- FR-8. Точки интеграции: только YouTube-ссылки (`handlers/youtube.py` → сервис выжимки). Видео-файлы, присланные в чат без ссылки, НЕ получают каскада (нет публичного URL для OpenRouter и нет потока субтитров) — текущее поведение без изменений; кружки/голосовые обслуживаются VoiceTranscriber (другая модальность, не трогаем).
- FR-9. Логи: INFO на успех ступени (ступень/модель/латенси/чаты), WARNING на сбой ступени, ERROR — только по существующим путям финального провала (R41-5 стиль `[youtube]/[video cascade]`); R17 — тело ответа провайдера не логируется.

**Часть 2 — Tool Calling**

- FR-10. `LLMClient` умеет отправлять `tools`/`tool_choice` в payload `/chat/completions` без изменения контракта {model, messages, temperature} для существующих вызовов (существующий `generate()` не меняет поведение — 0 регрессий).
- FR-11. Инструмент `execute_web_search` (аргумент `query`): исполняется поверх `SearchAggregator` (Tavily→Exa→DDG); `AllSearchEnginesFailedException` и любые сбои → структурированный текст-результат инструмента (НЕ исключение наружу); результат режется до лимита символов.
- FR-12. Инструмент `query_chat_memory` (аргументы `query`, `time_range` enum `last_day|last_week|last_month|all`): опрос истории чата/фактов через `MemoryManager` (`get_window_messages`/`search_long_term`/`vector_search`/`get_rag_context`); результат возвращается модели сообщением `role:"tool"`.
- FR-13. Цикл обработки `tool_calls`: ответ LLM с `tool_calls` → исполнение → сообщения `role:"tool"` с `tool_call_id` → повторный вызов; жёсткий лимит раундов (не более 4 вызовов LLM суммарно); финальный ответ — обычный текст.
- FR-14. Ошибка инструмента не роняет диалог: результат ошибки уходит модели как `role:"tool"` текст «ОШИБКА: …»; если после исчерпания лимита финального текста нет — поведение пустого ответа (молчание + 🗿, существующий путь direct_chat).
- FR-15. Если провайдер не поддерживает tools (детерминированный не-2xx на первом вызове с tools) — один повтор БЕЗ tools и обычный ответ (graceful degradation, юзеру — без ошибок).
- FR-16. Ручные триггеры поиска/исследования (`handlers/search.py`, `handlers/web.py`) не меняются — только регресс-проверка.
- FR-17. Инструменты включаются в минимальный набор диалоговых подсервисов: **только `direct_chat`** (см. 3.3, обоснование). Остальные подсервисы smartmodule не меняют поведение (0 регрессий).

**Часть 3 — реакции**

- FR-18. Тумблеры `reactions.vasya_enabled`, `reactions.kucha_enabled`, `flags.mimic_enabled`, `reactions.alan_mimic_enabled` — default `false`; регистрируются в param_catalog REGISTRY и сидятся в PG (автоматически через `_seed_settings`); чтение — `hot.get` в горячем пути (переключение в админке без рестарта).
- FR-19. Выключенный тумблер → реакция молчит без ошибок и без сообщений; роутеры/фильтры остаются зарегистрированными (паттерн `work_handler`: гейт первой строкой + `return UNHANDLED`); порядок регистрации роутеров в `bot.py` НЕ меняется.
- FR-20. `flags.mimic_enabled` — глобальный рубильник мимикрии common: не влияет на славячий mimic внутри `handlers/slavik.py` (управляется `limits.slavik_mimic_min_words`/`limits.slavik_mimic_cooldown`, как сейчас).
- FR-21. `reactions.alan_mimic_enabled` — дополнительное разрешение мимикрии именно на Леху/Алана (id из `reactions.alan_user_id`): для Лехи нужны ОБА флага (`flags.mimic_enabled` И `reactions.alan_mimic_enabled`); для остальных жертв из `reactions.mimic_victim_user_ids` достаточно `flags.mimic_enabled`.
- FR-22. Медиа-реакция `slavic_chlen.mp4` уходит строго пользователю с id `reactions.slavik_user_id`: гейт в `MessageCounterMiddleware` до инкремента/отправки; для остальных пользователей счётчик не тикает и гифка не шлётся; data-флаг `slavik_gif_sent` — только при фактической отправке Славику.
- FR-23. Переименование Alan/Алан → Леха во ВСЕХ отображаемых текстах: title_ru/description групп и параметров, группы-заголовки, README, `.env.example`-комментарии, остаточный «Alan» в web/. Код-идентификаторы (`ALAN_USER_ID`, `handlers/alan.py`, `services/database.py` ключи `alan_last_msg:*`, pg-ключи `reactions.alan_*`) НЕ переименовываются (совместимость).

**Часть 4 — UX/UI**

- FR-24. Вкладки админки: «LLM Провайдеры» (models+keys), «Промпты», «Лимиты», «Память и RAG», «Реакции и Триггеры», «Доступы», «Статус»; «Как это работает» остаётся (always-вкладка).
- FR-25. Каждый параметр виден ровно на одной вкладке (никаких дублей); группы каталога — «атом» отображения, одна группа — одна вкладка (кроме правил FR-26).
- FR-26. «Память и RAG» собирает: группы `flags_memory`, `limits_memory`, `limits_graph` целиком + параметры L1/RAG-окон, перемещённые между группами: `SUMMARY_WINDOW_HOURS`, `SUMMARY_MAX_WINDOW_MESSAGES` → группа `limits_memory`; `SUMMARY_RAG_L2_LIMIT`, `SUMMARY_RAG_L3_LIMIT` → группа `limits_graph` (pg-ключи не меняются — только `group` в каталоге).
- FR-27. «Реакции и Триггеры» показывает категорию `reactions` (все группы, включая новые «Словесные реакции») + флаг-группу `flags_media` (медиа/Оля/common/mimic-рубильники).
- FR-28. Key-Value-редактор для `limits.summary_aliases` (признак `widget: 'keyvalue'` в каталоге и в GET /api/config): пары «ID → имя», добавление/удаление строк, валидация пустых/дублей, сборка JSON-объекта при сохранении через существующий POST /api/config (updated_by фиксируется штатно).
- FR-29. Фронт не дублирует серверные названия вкладок/категорий; RBAC-дерево ролей (`/roles/tree`, секции-категории) не переименовывается (иначе ломаются права).

### Нефункциональные

- NFR-1. Пользователь не видит промежуточных ошибок каскадов (видео L1/L2, tool-режим) — только итоговый результат или существующие финальные фразы/молчание.
- NFR-2. Совместимость: pg-ключи и env-имена существующих параметров не меняются; добавление полей `Settings` всегда парой с записями REGISTRY (юнит-тест полноты покрытия `test_param_catalog.py` обязан остаться зелёным).
- NFR-3. Все новые тумблеры выключены по умолчанию (безопасный деплой: прод-поведение реакций меняется только явным включением).
- NFR-4. Порядок регистрации роутеров `bot.py` (340–447) не меняется; приоритеты медиа-реакций (dead page > service > GIF > photo > mimic > «пошёл нахуй» и т.д.) не ломаются тумблерами.
- NFR-5. Полный pytest — 0 failed; `git diff --check` чист (правило `plans/project.md`).
- NFR-6. Секреты (OpenRouter-ключ и др.) не логируются (R17); новые значения в БД — не секреты.

## 3. Технический дизайн

### 3.1 Настройки (param_catalog + Settings + сид)

#### Новые поля `config/settings.py` (dataclass `Settings`)

Блоки: LLM-модели (для `VIDEO_*`, рядом с `LLM_MODEL_NAME`/блоком OpenRouter у `ENABLE_VOICE_TRANSCRIPTION`), флаги/реакции — в существующих смысловых блоках:

```python
# ── Видео-выжимка (каскад OpenRouter video_url) ──
VIDEO_PRIMARY_MODEL: str = _env_str("VIDEO_PRIMARY_MODEL", "minimax/minimax-m3:free")
VIDEO_FALLBACK_MODEL: str = _env_str("VIDEO_FALLBACK_MODEL", "google/gemma-4-31b-it:free")
# Таймаут ОДНОГО мультимодального запроса видео (скачивание ролика + инференс
# free-моделью заметно дольше обычного чата; прецедент LLM_FALLBACK_TIMEOUT_SECONDS).
VIDEO_TIMEOUT_SECONDS: float = _env_float_min("VIDEO_TIMEOUT_SECONDS", 120.0, 5.0)
# ── Реакции-тумблеры ──
VASYA_ENABLED: bool = _env_bool("VASYA_ENABLED", False)
KUCHA_ENABLED: bool = _env_bool("KUCHA_ENABLED", False)
MIMIC_ENABLED: bool = _env_bool("MIMIC_ENABLED", False)
ALAN_MIMIC_ENABLED: bool = _env_bool("ALAN_MIMIC_ENABLED", False)
```

> Примечание: `VIDEO_TIMEOUT_SECONDS` — седьмой ключ сверх списка задач T3–T5; без него L1 гарантированно умирал бы по общему `models.openrouter_timeout` (15с — это таймаут транскриба голоса). Если PM отклонит — Builder убирает ключ и использует `hot.get("models.video_timeout_seconds", settings.LLM_FALLBACK_TIMEOUT_SECONDS)`-эквивалент, но дефолт в коде тогда должен быть ≥90с.

#### Новые записи `services/param_catalog.py`

В `_MODELS` (формат строк: `field, title, type, group, desc`):

| settings_field | pg_key | type | env_name | group | title_ru / description |
|---|---|---|---|---|---|
| `VIDEO_PRIMARY_MODEL` | `models.video_primary_model` | str | VIDEO_PRIMARY_MODEL | `models_video_summary` | «Первичная видео-модель (OpenRouter)» / «Модель, которая первой пробует „посмотреть” само видео через OpenRouter. Если упала — пробуется запасная, затем субтитры.» |
| `VIDEO_FALLBACK_MODEL` | `models.video_fallback_model` | str | VIDEO_FALLBACK_MODEL | `models_video_summary` | «Запасная видео-модель (OpenRouter)» / «Используется, когда первичная видео-модель недоступна. Упала — бот пересказывает по субтитрам.» |
| `VIDEO_TIMEOUT_SECONDS` | `models.video_timeout_seconds` | float | VIDEO_TIMEOUT_SECONDS | `models_video_summary` | «Таймаут видео-запроса, сек» / «Сколько ждать ответ мультимодальной модели на видео. Больше — реже сбои, но дольше тишина.» |

В `_FLAGS` (формат: `field, title, group, desc`):

| settings_field | pg_key | type | env_name | group | title_ru / description |
|---|---|---|---|---|---|
| `MIMIC_ENABLED` | `flags.mimic_enabled` | bool | MIMIC_ENABLED | `flags_media` | «Мимикрия включена» / «Главный рубильник передразниваний common (список „жертв” — в „Реакции и Триггеры” → „Мимикрия”). Выключено — бот никого не передразнивает (кроме мимикрии Славика — она на своём переключателе).» |

> Обоснование группы: `flags.mimic_forwards_enabled` уже живёт в `flags_media`; вкладка «Реакции и Триггеры» показывает `flags_media` целиком — рубильник мимикрии окажется рядом со списком жертв и лимитами-соседями.

В `_REACTIONS` (формат: `field, title, type, group, desc`):

| settings_field | pg_key | type | env_name | group | title_ru / description |
|---|---|---|---|---|---|
| `VASYA_ENABLED` | `reactions.vasya_enabled` | bool | VASYA_ENABLED | `reactions_word_reactions` | «Реакция „Вася → АДМИН”» / «Кто-то написал „Вася” — бот отвечает „АДМИН”; кто-то написал „админ” — бот отвечает „ВАСЯ”. Выключено — реакция молчит.» |
| `KUCHA_ENABLED` | `reactions.kucha_enabled` | bool | KUCHA_ENABLED | `reactions_word_reactions` | «Реакция „куча → ДАЛБАЕБ”» / «Кто-то написал „куча” — бот отвечает „ДАЛБАЕБ”. Выключено — реакции нет (гифка Славика работает независимо).» |
| `ALAN_MIMIC_ENABLED` | `reactions.alan_mimic_enabled` | bool | ALAN_MIMIC_ENABLED | `reactions_mimic` | «Мимикрия Лехи» / «Передразнивать сообщения Лехи (нужно также включить общий рубильник „Мимикрия включена”). Других „жертв” из списка этот тумблер не касается.» |

Новые `GroupSpec` в `GROUPS`:

```python
GroupSpec("models_video_summary", "models", "Видео-выжимка (OpenRouter)",
          "Модели, которые смотрят видео сами, и таймаут выжимки.", 8),
GroupSpec("reactions_word_reactions", "reactions", "Словесные реакции",
          "Тумблеры текстовых реакций: „Вася ↔ АДМИН” и „куча → ДАЛБАЕБ”.", 13),
```

Счётчик групп меняется 59 → 61; `_REACTIONS` остаётся отсортированной по группам внутри списка (рекомендуется вставить записи рядом с семантическими соседями; порядок записей в исходнике не влияет на PG).

Новый PG-only промпт-канон для видеорежима (в `_PROMPTS`, формат `pg_id, title_ru, code_source, group, description`):

```python
("prompts.youtube_video_system_prompt", "Системный промпт пересказа видео (мультимодально)",
 "services.youtube_prompts.YOUTUBE_VIDEO_SYSTEM_PROMPT", "prompts_youtube",
 "Инструкция нейросети при пересказе видео, когда модель смотрит само видео (без субтитров)."),
```

И в `services/youtube_prompts.py` — код-канон `YOUTUBE_VIDEO_SYSTEM_PROMPT`: копия `YOUTUBE_SYSTEM_PROMPT`, в которой строка «…по предоставленной текстовой расшифровке (субтитрам)» заменена на «…по самому видео (ты видишь кадры и слышишь звук)». Остальное байт-в-байт. Зачем отдельный промпт: существующий прямо требует «текстовую расшифровку» — для видеорежима это противоречие; промпт обязан остаться редактируемым (PG-only сид по `code_source`, hot.get-чтение).

#### Механика сида

- Отдельные ручные сид-строки НЕ нужны: `services/pg_db.py:_seed_settings` (251–274) итерирует `REGISTRY` и вставляет записи категорий из `SEED_CATEGORIES` (`models/limits/flags/reactions` — все входят, 110–113) через `INSERT … ON CONFLICT (key) DO NOTHING`. Новые записи попадут в PG при ближайшем старте (или через ConfigCache-самозасев). `prompts.youtube_video_system_prompt` — сид по `code_source` тем же механизмом.
- Ключ `keys.openrouter_api_key` уже существует и сидится как «не секрет» пустым (пусто = уровень выключен, прецедент voice-каскада).
- ВАЖНО для теста полноты `test_param_catalog.py::test_every_settings_field_covered`/`test_settings_field_count`: каждый новый env-ключ Settings обязан иметь запись REGISTRY и наоборот (пары таблиц выше — 1:1); `test_group_ids_all_valid...`/`test_groups_cover_all_categories_and_count_59` → обновить ожидания (61 группа, counts по категориям: models 8, reactions 13).

#### Переименование Alan → Леха (только отображаемые тексты, `services/param_catalog.py`)

Точный список строк для правки (группы и параметры; код-поля не трогаем):

| Строка | Было | Стало |
|---|---|---|
| 136 (GroupSpec `limits_persons`) | «Персонажи: Алан и Костик» | «Персонажи: Леха и Костик» |
| 137 | «…ответов Алана и Костика, приветствия Алана.» | «…ответов Лехи и Костика, приветствия Лехи.» |
| 189 (GroupSpec `reactions_persons`) | «Telegram ID Алана, Костика, Славика, Оли и админа.» | «Telegram ID Лехи, Костика, Славика, Оли и админа.» |
| 194 (GroupSpec `reactions_alan`) | title «Алан», desc «Папка видео-приветствий.» | title «Леха», desc «Папка видео-приветствий.» |
| 455–456 (`ALAN_REPLIES_ENABLED`) | «Reply-блок Алана» / «Алан отвечает…» | «Reply-блок Лехи» / «Леха отвечает…» |
| 466–467 (`ALAN_REPLY_INTERVAL`) | «Интервал ответа Алана…» / «…Алан отвечает…» | «Интервал ответа Лехи…» / «…Леха отвечает…» |
| 478–481 (`ALAN_GREETING_COOLDOWN`, `ALAN_SILENCE_GREETING_HOURS`) | «приветствия Алана…» / «Алан поприветствовал…» | «приветствия Лехи…» / «Леха поприветствовал…» |
| 692–693 (`SUMMARY_ALIASES`) | пример `{"138811255": "Алан"}` | пример `{"138811255": "Леха"}` |
| 715–716 (`ALAN_USER_ID`) | «Telegram ID Алана» | «Telegram ID Лехи» |
| 727–728 (`ALAN_USERNAME`) | «Юзернейм Алана» | «Юзернейм Лехи» |
| 729–730 (`ALAN_GREETING_DIR`) | «Папка приветствий Алана» | «Папка приветствий Лехи» |

Группа `reactions_alan` (id) и все pg-ключи/env-имена/код-идентификаторы НЕ меняются. Правки в README (строки 65–69, 351, 377–386, 597, 610, 661–662), `.env.example` (комментарии 13–19, 42–48), прочие «Alan/Алан» в web/ (фронт после рефакторинга 3.5 таких строк не содержит; grep-аудит перед коммитом). Комментарии в `config/settings.py` (152–196) и `services/database.py` (`alan_activity`, 475–493) можно привести к «Леха» — они не являются код-идентификаторами; строго не трогаем имена переменных/ключей/комментарии в `handlers/alan*.py` (код-канон).

#### Новое поле `widget` в каталоге

`ParamSpec` получает необязательное поле `widget: str = ""` (dataclass, frozen — значение задаётся в конструкторе). Значения: `""` (дефолт) | `"keyvalue"` (JSON-объект «ключ→значение», рендер KV-редактором). Проставляется в записи `SUMMARY_ALIASES` (строковый кортеж `_LIMITS` расширяется до 6 элементов с widget-флагом, либо после сборки — точечная замена объекта). GET /api/config отдаёт `"widget": spec.widget` в items (см. 3.5).

### 3.2 Часть 1 — видео-каскад (`video_url`)

#### Размещение

- **Новый файл `services/video_cascade_client.py`** — мультимодальный клиент OpenRouter на видео (по образцу `SmartModule/transcriber/openrouter_transcriber.py`: `AsyncOpenAI`, `base_url="https://openrouter.ai/api/v1"`, ключ — горячая точка `keys.openrouter_api_key` с фолбеком на settings, ленивая пересборка клиента при смене ключа, R17-логика).
- **Расширение `services/youtube_summarizer_service.py`** — метод-оркестратор каскада в существующем сервисе (НЕ новый сервис): конвейер один, DI/тесты/хендлер меняются минимально.
- **`handlers/youtube.py`** — единственная точка интеграции: `youtube_handler` вызывает `summarize_cascade` вместо `summarize`. Кэш, «печатает…», троттлинг, фразы и обработка исключений хендлера не меняются.
- `bot.py` (on_startup, YouTube-блок): `YoutubeSummarizerService(engine, llm, memory=memory, video_client=OpenRouterVideoClient())`; `video_client=None` (или недоступен ключ) = ровно старое поведение.

#### Сигнатуры

```python
class VideoLevelError(Exception):
    """Один уровень каскада упал (обёртка: HTTP-статус/класс исключения).
    reason: str — 'status=429' | 'timeout' | 'transport: ReadTimeout' | 'empty content' ..."""

class OpenRouterVideoClient:
    name = "openrouter_video"
    def __init__(self) -> None: ...                    # дефолты из settings
    @property
    def available(self) -> bool: ...                   # hot keys.openrouter_api_key непуст
    async def summarize(self, *, model: str, video_url: str,
                        system_prompt: str, user_text: str,
                        timeout: float) -> str:        # -> текст; пусто -> VideoLevelError('empty content')
```

```python
class YoutubeSummarizerService:
    def __init__(self, engine, llm, memory=None,
                 video_client: OpenRouterVideoClient | None = None) -> None: ...

    async def summarize_cascade(self, video_id: str,
                                on_retry: Callable[[int, int], Awaitable[None]] | None = None,
                                chat_id: int | None = None,
                                rag_query: str | None = None) -> str:
        """L1 (primary) → L2 (fallback) → L3 (субтитры). Всегда возвращает текст."""
```

#### Payload (спека OpenRouter)

```
POST https://openrouter.ai/api/v1/chat/completions
messages = [
  {"role": "system", "content": hot.get("prompts.youtube_video_system_prompt",
                                        YOUTUBE_VIDEO_SYSTEM_PROMPT).replace("{max_symbols}", str(max_symbols))},
  {"role": "user", "content": [
      {"type": "text", "text": f"{rag}\n\n<video_id>{video_id}</video_id>\n\nСмотри видео и сделай выжимку по правилам."},
      {"type": "video_url", "video_url": {"url": f"https://www.youtube.com/watch?v={video_id}"}},
  ]},
]
```

`rag` — префикс из `memory.get_rag_context(chat_id, rag_query)` (как в L3-пути, 55.5). Видео передаётся URL-ом canonical-формы (`watch?v=`); OpenRouter скачивает ролик сам. Канальный URL юзера не нужен и не хранится.

#### Псевдокод каскада (внутри `summarize_cascade`)

```
max_symbols = hot.get("limits.youtube_max_symbols", settings.YOUTUBE_MAX_SYMBOLS)
timeout    = hot.get("models.video_timeout_seconds", settings.VIDEO_TIMEOUT_SECONDS)

if video_client is None or not video_client.available:
    logger.warning("[video cascade] disabled (no openrouter key) — subtitles path | video_id=%r", video_id)
    return await summarize(video_id, on_retry=on_retry, chat_id=chat_id, rag_query=rag_query)   # L3

rag = await _build_rag(...)                                   # best-effort, fail-open
for level, key in (("L1", "models.video_primary_model"), ("L2", "models.video_fallback_model")):
    model = hot.get(key, settings.VIDEO_PRIMARY_MODEL if level=="L1" else settings.VIDEO_FALLBACK_MODEL)
    if not model:                                            # пусто = ступень отключена
        logger.warning("[video cascade] %s skipped (empty model)", level); continue
    started = time.monotonic()
    try:
        raw = await asyncio.wait_for(
            video_client.summarize(model=model, video_url=canonical_url(video_id),
                                   system_prompt=video_system, user_text=user, timeout=timeout),
            timeout=timeout)
    except VideoLevelError as exc:
        logger.warning("[video cascade] %s failed → next | model=%s video_id=%r | reason=%s",
                       level, model, video_id, exc)          # WARNING, юзеру НЕ показываем
        continue
    except asyncio.TimeoutError:
        logger.warning("[video cascade] %s timeout (%.0fs) → next | model=%s video_id=%r",
                       level, timeout, model, video_id); continue
    text = cleanup_llm_text(raw)
    if not text.strip():
        logger.warning("[video cascade] %s empty answer → next | model=%s video_id=%r", ...)
        continue
    logger.info("[video cascade] OK | level=%s model=%s video_id=%r out_chars=%d latency_ms=%.0f",  # R41-5
                level, model, video_id, len(text), (time.monotonic()-started)*1000)
    return text                                             # успех L1/L2 — кэшируется хендлером

logger.warning("[video cascade] L1+L2 unavailable → subtitles (L3) | video_id=%r", video_id)
return await summarize(video_id, on_retry=on_retry, chat_id=chat_id, rag_query=rag_query)        # L3: существующий код
```

Клиент-уровень (`OpenRouterVideoClient.summarize`): 1 стартовая попытка + 1 повтор только на транзиентное (429/5xx/`httpx.TransportError`, backoff 2с); 400/401/402/403/404/415/422 и прочие не-2xx — мгновенный `VideoLevelError(f"status={code}")`; `choices[0].message.content` пуст/`None` — `VideoLevelError("empty content")`; `httpx`/OpenAI-SDK исключения — `VideoLevelError(type(exc).__name__)`. Тело ответа НЕ логируется (R17). Итоговый критерий «уровень упал» (общий список): HTTP 400, 401, 402, 403, 404, 415, 422, 429, 5xx, транспорт, таймаут `wait_for`, пустой/`None` content — любой из них.

#### Интеграция в хендлер

`handlers/youtube.py:143`: `text_out = await _service.summarize_cascade(video_id, on_retry=..., chat_id=..., rag_query=text)` — замена одного вызова; try/except хендлера (LLMBadResponseError → молчание+🗿; YouTubeTranscriptUnavailable → фразы 5.6; LLMError → фразы 5.5) остаётся и теперь покрывает только финальный провал ВСЕГО каскада (L3). Исключения L1/L2 в хендлер не приходят (логика выше).

#### Видео-файлы из чата — решение

НЕ обрабатываем: (а) у файла из Telegram нет публичного URL — OpenRouter не скачает; (б) потока субтитров нет — L3 бессмыслен; (в) подъём файла на временный хостинг/локальный Bot API — новая инфраструктура и безопасность-риск вне эпика. Текущее поведение (каскад не запускается; при триггере без URL — `_parse` возвращает `None`, пропагация) сохраняется. Voice-каскад Groq→OpenRouter (video_note/кружки) — отдельная модальность, не пересекается.

### 3.3 Часть 2 — Tool Calling

#### JSON Schema инструментов (новый модуль `services/tool_schemas.py`)

```python
TOOL_EXECUTE_WEB_SEARCH = {
    "type": "function",
    "function": {
        "name": "execute_web_search",
        "description": "Поиск в интернете (каскад Tavily→Exa→DuckDuckGo). "
                       "Вызывай, когда ответу нужны свежие/внешние факты, которых нет в контексте.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Поисковый запрос (короткий, по-русски или по-английски)."}
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

TOOL_QUERY_CHAT_MEMORY = {
    "type": "function",
    "function": {
        "name": "query_chat_memory",
        "description": "Поиск по памяти бота: истории этого чата и долгосрочным фактам. "
                       "Вызывай, когда спрашивают «что я говорил/что было раньше/помнишь ли».",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "О чём вспомнить."},
                "time_range": {
                    "type": "string",
                    "enum": ["last_day", "last_week", "last_month", "all"],
                    "description": "Окно времени: last_day/last_week/last_month/all.",
                    "default": "all",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

TOOL_CALLING_TOOLS: list[dict] = [TOOL_EXECUTE_WEB_SEARCH, TOOL_QUERY_CHAT_MEMORY]
```

#### Расширение `services/llm_client.py`

Без изменения существующей сигнатуры `generate()`:

```python
@dataclass(frozen=True)
class LLMToolCall:
    id: str            # tool_call_id для role:"tool"
    name: str
    arguments: str     # JSON-строка аргументов (парсит исполнитель)

@dataclass(frozen=True)
class LLMChatResult:
    content: str | None        # текст финального ответа (None при tool_calls)
    tool_calls: list[LLMToolCall] | None
    finish_reason: str | None

async def generate_chat(self, messages, *, temperature: float | None = None,
                        tools: list[dict] | None = None,
                        tool_choice: str | dict = "auto") -> LLMChatResult: ...
```

Внутренности: `payload = {"model": ..., "messages": messages}`; `temperature` — как сейчас (None → не добавлять); `tools`/`tool_choice` добавляются в payload только когда `tools` передан. Ретраи/фоллбэк `_post`/`_fallback_with_retries` переиспользуются как есть (payload — сквозной). Парсинг: `choices[0].message.content` (может быть `None`) + `choices[0].message.tool_calls` (список `{id, type, function:{name, arguments}}`) + `choices[0].finish_reason`. Легаси `generate()` остаётся нетронутым (парсит только content; пустой content без tool_calls → `LLMBadResponseError` как раньше). ВАЖНО: НЕ менять `{model, messages, temperature}`-контракт — `tools` уходят только новым методом.

#### Исполнение инструментов (новый `services/tool_router.py`)

```python
class ToolDeps:                       # контейнер зависимостей (инжектится из bot.py)
    search: SearchAggregator
    memory: MemoryManager
    aliases: AliasResolver | None = None

class ToolContext:
    chat_id: int
    query: str                        # исходное сообщение юзера (fallback для пустых аргументов)

class ToolRouter:
    def __init__(self, deps: ToolDeps) -> None: ...
    async def dispatch(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        """Всегда возвращает строку результата (в т.ч. 'ОШИБКА: …') — НЕ бросает."""
```

- `execute_web_search(query)`: `text = await deps.search.search(query, max_symbols=4000)`; успех → `"Результаты поиска по запросу «{q}»:\n{text}"`; `AllSearchEnginesFailedException`/любая ошибка/пусто → `"ОШИБКА execute_web_search: поиск недоступен ({reason})"` (результат ошибки тоже уходит модели как `role:"tool"` — модель решает, что делать). Один вызов на `tool_call`. Исполнение — под `asyncio.wait_for(..., timeout=25)` (сумма таймаутов каскада поиска + запас).
- `query_chat_memory(query, time_range="all")`: `since = 0 if all else now - {24h|168h|720h}`; набор результатов:
  1. `rows = await deps.memory.search_long_term(chat_id, keywords(query), limit=40)` (FTS по L1-сообщениям) с пост-фильтром `timestamp >= since`;
  2. если пусто и `time_range in (last_month, all)` — `facts = await deps.memory.vector_search(chat_id, query, limit=15)` (факты архива/графа);
  3. если всё ещё пусто — `rag = await deps.memory.get_rag_context(chat_id, query)`.
  Рендер: строки `[имя/дата]: текст` через `deps.aliases.resolve` (если есть), общий лимит 3500 символов. Пусто → `"По запросу «{q}» в памяти ничего не найдено."` (важный честный ответ — модель не выдумывает). Все сбои БД/вектора — fail-open в текст ошибки (см. выше).
- Безопасность/ограничения: фиксированный реестр имён (неизвестное имя → `"ОШИБКА: неизвестный инструмент {name}"`, никогда не исполняется произвольный код); аргументы валидируются по схеме (кривой JSON/тип → текст ошибки); результат режется (4000/3500 симв.); нет параллельного исполнения (последовательно, по одному `tool_call` за раунд); общий бюджет раундов — в цикле ниже.

#### Цикл обработки `tool_calls` (новый `services/tool_loop.py`)

```python
TOOL_MAX_ROUNDS = 4      # 1 стартовый вызов + до 3 раундов инструментов

async def chat_with_tools(llm, messages: list[dict], *,
                          tools: list[dict], router: ToolRouter, ctx: ToolContext,
                          temperature: float | None = None) -> str:
    """→ финальный текст. При невозможности tool-режима — обычный ответ без tools."""
```

```
payload_messages = deepcopy(messages)
last_error = None
for round_index in range(TOOL_MAX_ROUNDS):
    try:
        result = await llm.generate_chat(payload_messages, temperature=temperature,
                                         tools=tools, tool_choice="auto")
    except LLMError as exc:                    # провайдер не умеет tools (400 и т.п.)
        if round_index == 0:
            logger.warning("[tools] provider rejected tools — plain answer | error=%s", exc)
            return await llm.generate(messages, temperature=temperature)   # degrade: 1 обычный вызов
        raise
    if not result.tool_calls:
        text = (result.content or "").strip()
        if text:
            return text
        raise LLMBadResponseError("tool loop: empty final answer")   # путь молчания+🗿 direct_chat
    if len(result.tool_calls) > 2:             # защита от спама вызовов одним ходом
        result.tool_calls = result.tool_calls[:2]
    payload_messages.append({"role": "assistant",
                             "content": result.content or None,
                             "tool_calls": [tc.as_openai_dict() for tc in result.tool_calls]})
    for tc in result.tool_calls:
        try:
            arguments = json.loads(tc.arguments) if (tc.arguments or "").strip() else {}
            if not isinstance(arguments, dict):
                raise ValueError("arguments not object")
            output = await router.dispatch(tc.name, arguments, ctx)
        except Exception as exc:               # инструмент упал — модель видит текст ошибки
            logger.warning("[tools] exec failed | tool=%s | error=%s", tc.name, exc)
            output = f"ОШИБКА {tc.name}: {type(exc).__name__}"
        payload_messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": output})
# лимит раундов исчерпан
logger.warning("[tools] round limit reached | rounds=%d", TOOL_MAX_ROUNDS)
raise LLMBadResponseError("tool loop: no final answer within round limit")
```

Случай «финальный ответ снова `tool_calls`» покрыт самим циклом (пока есть `tool_calls` — продолжаем; лимит раундов режет). Логи — `[tools]`-префикс, WARNING на деградацию/лимит, INFO на каждый раунд (tool/раунд/символов).

#### Куда встроен цикл: минимальный набор подсервисов

Решение по списку подсервисов smartmodule:

| Подсервис | Tools в этом эпике | Обоснование |
|---|---|---|
| `direct_chat` (`services/direct_chat_service.py`, `handle()`) | ✅ `[execute_web_search, query_chat_memory]` | Единственный свободно-генеративный диалог: контекст уже включает RAG, но модель не может «добрать» внешнее/глубокое-историческое. Инструменты дают максимум пользы здесь. |
| search / factcheck | ❌ | Детерминированный поиск/контекст уже выполнен ДО LLM (SearchService/FactCheckService) — tools привели бы к двойному поиску, расходам и нестабильности ответов. |
| summary / youtube / web / checkup | ❌ | Железные XML-пайплайны с фиксированным контентом (транскрипт/страница/логи); агентность не нужна. |
| voice / video | ❌ | Не LLM-чат. |

Механика включения — по месту вызова, не в промптах: `DirectChatService` получает `tools=None` по умолчанию (тесты/DI не ломаются) и `tool_router: ToolRouter | None`; в `handle()` участок `raw = await self.llm.generate(payload, temperature=...)` заменяется на `raw = await chat_with_tools(self.llm, payload, tools=TOOL_CALLING_TOOLS, router=self._tool_router, ctx=ToolContext(chat_id, query), temperature=temperature)` при настроенном роутере; иначе — старый вызов (ровно текущее поведение). Расширение на другие подсервисы в будущем — одна строка (инструменты декларативны, цикл общий).

Остальные части `handle()` (CB, throttle, замок, memorize, дедуп, фразы ошибок) не меняются; `LLMBadResponseError`/`LLMError` из цикла обрабатываются существующими except-ветками. Системные промпты НЕ правятся (код-каноны R50-4 и др., золотые тесты): модель узнаёт об инструментах из их описаний («Вызывай, когда…»), инициатива — за моделью.

`bot.py` (on_startup, direct_chat-блок): собрать `_tool_router = ToolRouter(ToolDeps(search=_search_aggregator, memory=memory, aliases=aliases))` и передать в `DirectChatService(..., tool_router=_tool_router)`.

### 3.4 Часть 3 — реакции

Общий принцип гейтов (прецедент `handlers/common.py::work_handler`): роутер/фильтр остаются зарегистрированными; внутри хендлера первой строкой `hot.get("…", settings.…)`; выключено → `logger.info` + `return UNHANDLED` (пропагация вниз по порядку регистрации не ломается — для последних роутеров это «тишина»). Порядок регистрации в `bot.py` (340–447) НЕ меняется ни для одного роутера.

#### 3.4.1 Вася ↔ АДМИН — `reactions.vasya_enabled`

Файлы: `handlers/vasya.py` (оба хендлера), фолбек `settings.VASYA_ENABLED`; импорт `settings` добавить в модуль. Гейт первой строкой в обоих:

```python
# handlers/vasya.py
if not hot.get("reactions.vasya_enabled", settings.VASYA_ENABLED):
    logger.info("vasya: disabled (reactions.vasya_enabled=False) | user=%s", ...)
    return UNHANDLED
```

Фильтры `filters/vasya_name.py`/`filters/admin_word.py` не меняются (они лишь определяют «кто сработал»). «Отдельный сервис-флаг» здесь означает именно флаг-гейт в каталоге (новые `services/reaction_*.py` не нужны — хендлеры тривиальны, 17 строк, вынос в сервис добавил бы слой без логики). Вася-роутер — последний (позиция 6); при выключенном флаге сообщения «просто не получают ответа», ошибок нет.

#### 3.4.2 Куча → ДАЛБАЕБ — `reactions.kucha_enabled`

Файл: `handlers/slavik.py::kucha_handler` (149–156). Гейт ДО `message.reply`, data-флаг миддлвари сохраняется:

```python
async def kucha_handler(message, data=None):
    if (data or {}).get("slavik_gif_sent"):
        return UNHANDLED
    if not hot.get("reactions.kucha_enabled", settings.KUCHA_ENABLED):
        logger.info("kucha: disabled | chat=%s", message.chat.id)
        return UNHANDLED            # пропагация: славячий юзер уйдёт в catch-all
    await message.reply("ДАЛБАЕБ")
```

Важно: `kucha_handler` матчит ЛЮБОГО юзера (фильтр без UserIdFilter) — так было и остаётся; выключенный тумблер возвращает управление дальше (для Славика — catch-all, т.е. mimic/«пошёл нахуй»; для остальных — тишина). Гифка Славика (middleware) от тумблера не зависит и продолжает работать.

#### 3.4.3 Мимикрия common — `flags.mimic_enabled` (глобально) + `reactions.alan_mimic_enabled` (Леха)

Файл: `handlers/common.py::mimic_handler` (228–269). Гейты — после существующей проверки `_VICTIM_IDS` (список пуст → disabled-возврат как сейчас), ДО проверок репоста/relay:

```python
user_id = message.from_user.id if message.from_user else 0
if not hot.get("flags.mimic_enabled", settings.MIMIC_ENABLED):
    logger.debug("mimic: disabled (flags.mimic_enabled=False) | user=%s", user_id)
    return UNHANDLED
alan_user_id = hot.get("reactions.alan_user_id", settings.ALAN_USER_ID)
if user_id == alan_user_id and not hot.get("reactions.alan_mimic_enabled",
                                           settings.ALAN_MIMIC_ENABLED):
    logger.debug("mimic: alan-mimic disabled | user=%s", user_id)
    return UNHANDLED
```

Семантика (проверено против кода):
- `_VICTIM_IDS`/`_MIMIC_USER_IDS` парсятся на импорт модуля из `reactions.mimic_victim_user_ids` — фильтр статический; новые гейты — горячие, поверх фильтра. Дефолт списка — `"138811255"` (Леха) — не меняем.
- Для Лехи mimic срабатывает только при `flags.mimic_enabled=True` И `reactions.alan_mimic_enabled=True` (в т.ч. когда он единственный в списке).
- Для других жертв списка достаточно `flags.mimic_enabled` (`reactions.alan_mimic_enabled` их не касается).
- Славячий mimic внутри `handlers/slavik.py` (Branch 2, `_slavik_mimic_should_trigger`, `limits.slavik_mimic_min_words`/`limits.slavik_mimic_cooldown`, свой `_slavik_mimic_last_sent`) — отдельный механизм, `flags.mimic_enabled` его НЕ трогает (в коде slavik.py флаг не читается; ничего не добавляем). Выключение славячьего mimic — по-прежнему `slavik_mimic_min_words < 0`.
- Репост-гейт `flags.mimic_forwards_enabled` (D52) остаётся как есть и работает внутри включённой мимикрии.

#### 3.4.4 Медиа `slavic_chlen.mp4` — строгий гейт `reactions.slavik_user_id`

Файл: `services/message_counter.py` (`MessageCounterMiddleware`). Проверка по коду: гейта в middleware НЕТ (счётчик инкрементируется для любого юзера, чьё сообщение дошло до slavik_router, гифка может уйти не-Славику — дефект). Фикс в `__call__`:

```python
user_id = event.from_user.id
slavik_id = hot.get("reactions.slavik_user_id", settings.SLAVIK_USER_ID)
if user_id != slavik_id:
    # slavic_chlen.mp4 — строго Славику: чужой счёт не тикает, гифка не шлётся
    return await handler(event, data)      # (data без "slavik_gif_sent": флаг ставится только Славику)
```

Место: сразу после ветки service-сообщений (join/leave), до `increment_and_get_count`. Следствия: существующие тесты `tests/test_message_counter.py` зелёные (их user_id = 479167456 = дефолт славик); поведение для Славика не меняется; для остальных — больше никакого счётчика/гифки (чинит потенциальную «гифку не-Славику»). Конфликтов с другими медиа-реакциями нет: middleware стоит на `slavik_router` (позиция 5), а dead page / war / common / olya / kostik / goodmorning регистрируются РАНЬШЕ и съедают свои сообщения до него; data-флаг `slavik_gif_sent` сохраняет приоритет «одно действие на сообщение» (T-410) внутри роутера Славика; `kucha_handler`/catch-all — ниже по цепочке и реагируют на флаг. Тумблеры vasya/kucha гейтят только свои тексты и не влияют на приоритеты роутеров (см. 4).

#### 3.4.5 Прочее

`handlers/admin_commands.py` (ветки /alangreet и т.п.), `services/database.py` (`alan_activity`) и README — только тексты «Alan/Алан» → «Леха» (см. 3.1). Ключи `reactions.alan_user_id`/`reactions.alan_mimic_enabled` вместе дают ID Лехи: гейт 3.4.3 читает `reactions.alan_user_id` (hot) — жёстких констант 138811255 в новом коде нет.

### 3.5 Часть 4 — UX/UI админки

#### 3.5.1 Целевая структура вкладок и маппинг

Фронт (`web/app.js::TABS` + `web/index.html`) — источник витрин; серверные категории (RBAC/roles tree) не переименовываются.

| Текущая вкладка (TABS) | Новая вкладка | Категория(и) | Какие группы param_catalog |
|---|---|---|---|
| «Модели и Провайдеры» (models) | **«LLM Провайдеры»** | models, keys | models: все 8 (включая новую `models_video_summary`); keys: все 6 |
| «API Ключи» (keys) | ↑ (та же вкладка) | ↑ | ↑ |
| «Промпты» (prompts) | **«Промпты»** | prompts | все 8 (включая `prompts_youtube` + новый сид-промпт видеорежима) |
| «Лимиты и Модули» (limits) | **«Лимиты»** | limits, flags | limits: все, кроме `limits_memory`, `limits_graph` (после переноса окон/RAG-параметров группы `limits_summary`/`limits_graph` автоматически облегчены); flags: `flags_modules`, `flags_chat_behavior`, `flags_service` |
| — (нет) | **«Память и RAG»** | limits, flags | `limits_memory`, `limits_graph` (limits) + `flags_memory` (flags) |
| — (нет) | **«Реакции и Триггеры»** | reactions, flags | reactions: все 13 групп (включая новые `reactions_word_reactions`; `reactions_mimic` с `alan_mimic_enabled`, `reactions_slavik` и т.д.); flags: `flags_media` (медиа/Оля/common/mimic-рубильники) |
| «Управление доступом» | **«Доступы»** | access | — |
| «Статус» | **«Статус»** | — | — |
| «Как это работает» | остаётся (always) | — | — |

Перенос «в бэке»: (а) GET /api/config уже отдаёт `items` с `category/group/order` и `groups[]` — перекладывать нечего; (б) релокация параметров L1/RAG-окон — правка поля `group` в записях каталога (FR-26): `SUMMARY_WINDOW_HOURS`, `SUMMARY_MAX_WINDOW_MESSAGES` → `limits_memory`; `SUMMARY_RAG_L2_LIMIT`, `SUMMARY_RAG_L3_LIMIT` → `limits_graph` (строки `_LIMITS`). PG-ключи и значения не затрагиваются; группы-«доноры» остаются непустыми. (в) Новое поле `widget` в items (FR-28).

Механика фронта (устранение дублирования шаблонов):

1. `TABS` — новая декларативная форма: каждый таб несёт `sources: [{category, groups: [...] | null}]` (`null` = вся категория) и `type: 'config'|'access'|'status'|'info'`. Старые 5 конфиг-шаблонов `index.html` (prompts/models/keys/limits+flags) схлопываются в ОДИН generic-шаблон `config-tab` (v-for по `groupedForSources(tab)`), который рендерит карточки по `item.type`/`item.widget`.
2. `groupedForSources(tab)` — аналог `groupedByCategory`, но фильтрует по спискам групп источников и собирает «витрины» (карточка-группа с title/description как сегодня). Каждый item попадает ровно в один источник (группа принадлежит одной вкладке — см. таблицу; assert-проверка в тестах).
3. Типы контролов внутри карточки: `bool` → тумблер (как в limits сейчас); `str`/`int`/`float` → input (`inputType`); `json` с `widget==='keyvalue'` → KV-редактор; `json` без widget → textarea с JSON (как сейчас); prompts-тип `str` с большой длиной — textarea (эвристика по `key`-префиксу `prompts.` или по длине description; фиксируем: категория `prompts` и `content` всегда textarea).
4. `canViewTab(tab)` — расширяется на новые `sources`: видимость, если есть section-право на ЛЮБУЮ категорию источника либо param-право на любой ключ вида `<cat>.` (существующая логика по `tab.categories` заменяется на уникальные категории источников; для «Память и RAG» = limits+flags, «Реакции и Триггеры» = reactions+flags). Ограничение прежнее: проверка на уровне категории (не группы) — пустых вкладок не возникает, т.к. GET /api/config отдаёт значения всем ролям (править могут только с правами).
5. Пустые состояния и поиск — как сегодня (пер-таб `configSearch`).

#### 3.5.2 KeyValueEditor для `limits.summary_aliases`

Серверный признак: `ParamSpec.widget` (3.1) → GET /api/config: `"widget": spec.widget or ""` у item. Фронт: `loadConfig` НЕ строкифайт `json`-значения с `widget==='keyvalue'` (остаются объектом); остальные json — как сейчас (stringify). Текстовое JSON-поле для `summary_aliases` убирается.

Компонент (inline `app.component('kv-editor', …)` в `web/app.js`, шаблон в `index.html`; Vue 3 global build с template compiler):

- **Props:** `item` (объект конфиг-item: `{key,title,description,value: dict, widget}`), `canEdit` (bool).
- **State (локальный):** `pairs: [{id, name}]`, `draftDirty` — инициализация на `created`/watch `item.value`: `Object.entries(value||{}) → pairs` (порядок объекта сохраняется; для объекта-значения из `hot`/PG порядок вставки — как в JSON).
- **Render:** строка-карточка на пару: input «Telegram ID» (`pairs[i].id`, placeholder «Например 138811255»), input «Имя» (`pairs[i].name`, placeholder «Например Леха»), иконка-кнопка корзины (🗑/✕) удаляет пару. Кнопка «+ Добавить имя» добавляет пустую пару `{id:'', name:''}` в конец.
- **Валидация при сохранении:** пустой `id` ИЛИ пустое `name` на любой строке → toast «Заполните ID и имя в каждой строке» (кнопка Сохранить disabled при любой пустой строке, чтобы не накапливать); дубли `id` → toast «Дублируется Telegram ID: X». Порядок строк = порядок в объекте.
- **Сборка и сохранение:** `obj = {}; pairs.forEach(p => obj[p.id] = p.name)` → `POST /api/config` `{items:[{key: item.key, value: obj}]}` (существующий `saveConfigItem`-механизм; серверный `_coerce_value` для `json` принимает dict; `updated_by` фиксируется штатно в ConfigCache.set). После успеха — toast и перезагрузка `loadConfig()` (как `saveKeyItem`).
- Ограничение: до ~200 строк (мягкий лимит на фронте — предупреждение) — защита от вырожденных словарей.

#### 3.5.3 Нейминг «Леха» во фронте/параметрах

После рефакторинга шаблонов фронт не содержит собственных названий параметров (всё с сервера — title/description из каталога, правки 3.1). Остаточные строки во `web/index.html`/`app.js`: grep-аудит `Alan|Алан` перед коммитом (по дизайну их нет: заголовки-группы и карточки приходят из каталога). README/.env.example — см. 3.1.

#### 3.5.4 Масштабируемость (динамический список провайдеров)

Что уже есть: параметры провайдеров — обычные записи каталога (адреса/модели/ключи/таймауты редактируются в «LLM Провайдеры» без рестарта, hot-read); новые модели видео — те же записи. Что добавить не требуется в этом эпике (вне скоупа, roadmap): динамический «список провайдеров» как сущность (несколько конфигураций LLM с выбором активной), панель «быстрый тест модели», авто-обнаружение моделей OpenRouter. Вкладки/карточки уже рендерятся из каталога, поэтому добавление нового параметра провайдера = одна запись REGISTRY без правок фронта (свойство, проверяемое тестом-аудитом «нет дублей и все группы на своих вкладках»).

## 4. Пограничные случаи и решения (Edge cases)

- **Порядок роутеров (CRITICAL, bot.py 340–447) не меняется.** Dead page (4), war_alert (4b), common (4c), olya (4d), kostik (2), goodmorning (scheduler) перехватывают свои сообщения ДО slavik (5) и vasya (6). Тумблеры только «выключают текст» внутри уже сработавшего хендлера → приоритеты не смещаются.
- **Vasya против более ранних роутеров:** сообщение «вася» от Славика и сегодня уходит в slavik-цепочку раньше vasya_router («пошёл нахуй» и т.п.) — поведение не меняется; включённый `reactions.vasya_enabled` этого не ломает. «куча админ» в одном сообщении: при включённых обоих тумблерах сработает kucha (роутер 5 раньше 6) — «ДАЛБАЕБ»; документируем как существующий порядок приоритетов, НЕ чиним (не регрессия).
- **Kucha при выключенном флаге:** гифка Славика (middleware) продолжает работать (интервал — `limits.gif_interval`, путь `reactions.gif_path`); славячий catch-all не затронут; не-славик с «кучей» — тишина. Включение kucha + славик: «ДАЛБАЕБ» приоритетнее catch-all (как сегодня).
- **Mimic дефолты:** с деплоем `flags.mimic_enabled=False` (дефолт) мимикрия common выключается даже для Лехи (дефолт жертвы) — намеренно; включение — два тумблера в админке. Мимикрия Славика не зависит от новых флагов (см. 3.4.3). `MIMIC_FORWARDS_ENABLED`-гейт остаётся внутренним.
- **slavic_chlen.mp4 и «одно действие»:** гейт по `reactions.slavik_user_id` в middleware не создаёт конфликтов с danger/otboy/olya-медиа (другие роутеры раньше) и с catch-all (data-флаг). У Славика поведение byte-в-byte прежнее (интервал-счётчик по его сообщениям, гифка на N-е).
- **Выключенный PG / деградация:** `hot.get` без кэша возвращает settings-дефолт → все новые тумблеры `False`, видео-каскад с моделями-дефолтами, но без `keys.openrouter_api_key` (пусто в .env → уровень пропущен). Админка без PG: POST /api/config честно 503 (R6) — фронт показывает toast, KV-редактор ничего не «теряет» (правка только по кнопке Сохранить).
- **Новые ключи в чужом окружении:** сид ON CONFLICT DO NOTHING не перезаписывает значения, выставленные вручную в PG ранее (для новых ключей значений нет — вставятся дефолты Settings на старте; если владелец успел включить тумблер до рестарта — сид не тронет).
- **Совместимость env/PG:** не меняем имена `ALAN_*`-env и `reactions.alan_*`-ключей; переименование — только `title_ru`/description/группы/README. Код-идентификаторы (`ALAN_USER_ID`, методы `alan_*` в database.py) не трогаем.
- **«Вася» при выключенном флаге:** молчание — без сообщений об ошибке; UNHANDLED-пропагация после роутера 6 никуда не ведёт (последний роутер) — равнозначно тишине.
- **Видео-каскад и возрастные/гео-ограничения YouTube:** OpenRouter не скачает → 4xx → L2 → L3 (субтитры через прокси, существующие ретраи движка); юзер видит только привычные финальные фразы. Каскад не «залипает»: суммарный худший случай L1+L2 ≤ 2×`models.video_timeout_seconds` (дефолт 120с), затем L3 с его собственными ретраями.
- **Кэш умного кэша:** первый успешный результат (любой ступени) фиксирует ответ по `video_id`; повторные запросы — из кэша (мультимодальная попытка не повторяется) — прежнее поведение, ок.
- **Tool-цикл и CB:** `direct_chat`'s Circuit Breaker не знает о раундах — счёт сбоев по-прежнему на `llm.generate`-уровне? НЕТ: в цикле вызовы идут через `generate_chat`; сбой любого раунда → `LLMError` наружу → существующая except-ветка `handle()` классифицирует по классу (LLMTimeout/Server/Transport → CB.on_failure; 4xx-детерминированный не тикает, кроме HALF_OPEN — как сейчас). Успех финального раунда сбрасывает CB (on_success в handle после отправки — без изменений).
- **Ошибки инструментов и лимит раундов** не порождают сообщений юзеру сверх существующих путей direct_chat (фразы R13/молчание+🗿 — см. FR-14).
- **Роли/модераторы и новые вкладки:** видимость по категориям источников; карточки видны всем, кнопки — по `canEditConfig` (без изменений правовой модели). Вкладка «Память и RAG» у роли только с `limits`-правами может быть видна, но пуста по группам — нет: значения отдаются всем, поэтому вкладка непуста; редактирование ограничено правами.
- **`test_param_catalog` / полнота каталога:** новые поля Settings обязаны иметь записи REGISTRY (иначе красный тест полноты) — таблицы 3.1 дают 1:1.
- **Прод-деплой тумблеров:** после деплоя (дефолты false) «Вася/куча/mimic» молчат до включения владельцем в «Реакции и Триггеры». Это ожидаемое изменение (задачи T18–T21); порядок включения не важен (гейты независимы).

## 5. Критерии приёмки (Acceptance criteria)

**Часть 1 (видео-каскад)**
- AC-1.1. REGISTRY содержит `models.video_primary_model`, `models.video_fallback_model`, `models.video_timeout_seconds` (type/group/дефолты по 3.1); `test_param_catalog` зелёный; сид-записи появились в PG (ON CONFLICT DO NOTHING) без ручных строк.
- AC-1.2. С unit-тестами: primary OK (текст вернулся, хендлер отправил, кэш записан); primary fail → fallback OK; оба fail → субтитры (L3) вызваны и юзеру НЕ показана ошибка уровней; пустой ответ L1+L2 → L3; пустой ответ всех → молчание+🗿; отсутствие `keys.openrouter_api_key` → сразу L3 (WARNING), `video_client=None` → ровно старое поведение.
- AC-1.3. Payload мультимодального вызова соответствует спеке OpenRouter: `content` = `[{type:'text'}, {type:'video_url', video_url:{url: 'https://www.youtube.com/watch?v=<id>'}}]`, model из ключа уровня.
- AC-1.4. Ретрай уровня — только транзиентное (429/5xx/транспорт, ≤1 повтор); 400/401/402/403/404/415/422/пусто/таймаут → следующий уровень без ретрая.
- AC-1.5. «перескажи видос» в живом чате: L1 или L2 или L3 дают выжимку; сбой всех — существующие фразы; промежуточных сообщений об ошибках нет (живая проверка T34).

**Часть 2 (Tool Calling)**
- AC-2.1. `generate()` не меняет поведение (payload {model,messages[,temperature]} без tools) — существующие тесты LLMClient зелёные; `generate_chat` с tools кладёт `tools`/`tool_choice` в payload и парсит `content`+`tool_calls`.
- AC-2.2. Round-trip мок-тест: модель вернула tool_calls → исполнены инструменты (по одному, последовательно) → сообщения `role:"tool"` с корректными `tool_call_id` → финальный текст; порядок сообщений в повторном запросе валиден.
- AC-2.3. Лимит: цикл не превышает 4 вызовов LLM; после лимита без финального текста → `LLMBadResponseError` (молчание+🗿), без исключений наружу.
- AC-2.4. Сбой инструмента → `role:"tool"` с текстом «ОШИБКА …», диалог продолжается; `AllSearchEnginesFailedException` → структурированный результат инструмента.
- AC-2.5. Провайдер без поддержки tools (детерминированный не-2xx на 1-м вызове) → один повтор БЕЗ tools → обычный ответ (юзер не видит ошибки).
- AC-2.6. Только direct_chat получил инструменты; search/factcheck/summary/youtube/web/checkup — нулевой диф поведения (регресс-тесты зелёные); ручные триггеры поиска работают как раньше.
- AC-2.7. Дженерик: инструменты описаны в `tool_schemas.py` точно по 3.3 (имена/схемы/`time_range` enum); исполнение — только через реестр `ToolRouter.dispatch` (без произвольного кода).

**Часть 3 (реакции)**
- AC-3.1. Все 4 тумблера: в REGISTRY+Settings с дефолтом `False`, видны в админке, переключение в PG меняет поведение бота БЕЗ рестарта (hot.get).
- AC-3.2. Vasya: выключен — «вася»/«админ» молчат (нет reply, нет ошибок); включен — ровно прежние «АДМИН»/«ВАСЯ».
- AC-3.3. Kucha: выключен — «куча» от любого юзера без «ДАЛБАЕБ», гифка Славика продолжает работать; включен — прежнее поведение (с уважением data-флага гифки).
- AC-3.4. Mimic: `flags.mimic_enabled=false` → common-mimic молчит (в т.ч. Леха); славячий mimic в slavik.py работает без изменений (минимальная длина/кулдаун); `flags.mimic_enabled=true` + жертва ≠ Леха → мимикрируется без `alan_mimic_enabled`; жертва = Леха → нужны оба флага.
- AC-3.5. MessageCounterMiddleware: не-Славик не инкрементит счётчик и не получает гифку; Славик — как раньше; файл `media/slavik/slavic_chlen.mp4` — только при интервале `limits.gif_interval` и пути `reactions.gif_path`.
- AC-3.6. Переименование: grep-аудит «Alan|Алан» по UI-текстам (param_catalog/web/README/.env.example) пуст или осознан (код/ключи/env-имена не тронуты — диф-проверка).
- AC-3.7. Порядок регистрации роутеров bot.py не изменён (диф); полный pytest — 0 failed.

**Часть 4 (UX/UI)**
- AC-4.1. Вкладки по таблице 3.5.1: 7 именованных + «Как это работает»; каждый параметр ровно на одной вкладке (тест-аудит маппинга групп → вкладок, без дублей).
- AC-4.2. «Память и RAG» показывает limits_memory/limits_graph/flags_memory + перемещённые окно/RAG-параметры; «Реакции и Триггеры» показывает reactions + flags_media; пустых вкладок нет.
- AC-4.3. `limits.summary_aliases` рендерится KV-редактором (пары, «Добавить имя», удаление-иконка, валидация пустых/дублей), сохраняется в PG объектом JSON через POST /api/config, `updated_by` фиксируется; у других json-полей — прежние контролы.
- AC-4.4. Ручная проверка (T30): все вкладки грузятся с существующими ролями; тумблеры bool на «Реакции и Триггеры»/«Лимиты» работают; поиск по вкладке работает.
- AC-4.5. RBAC не сломан: `/api/roles`/tree секции и права не переименовывались; тесты webapp API зелёные.
- AC-4.6. Ни одного «Alan/Алан» в отображаемых строках интерфейса (title/description/группы → «Леха»).

**Сквозные**
- AC-5.1. Полный pytest: 0 failed; `git diff --check` чист; conventional commit на русском.
- AC-5.2. README и .env.example обновлены (видео-модели/таймаут, тумблеры, вкладки, KV-редактор, «Леха»).
- AC-5.3. Деплой по T33 (git pull --ff-only + systemd restart) без ручных миграций (сид автоматический).

## 6. План миграции/докатки

### Тесты (создать/править)

Создать:
- `tests/test_video_cascade.py` — клиент+каскад: L1 OK; L1 fail→L2 OK; оба fail→L3 (мок движка/LLM); пустой ответ→L3; все пусто→`LLMBadResponseError`; отсутствие ключа→сразу L3; payload-форма (video_url); ретрай-политика; рендер `hot.get`-чтения ключей (прецедент `tests/test_message_counter.py`).
- `tests/test_tool_schemas.py` — схемы валидны (JSON Schema-прогон, enum time_range, required).
- `tests/test_tool_router.py` — dispatch web_search (мок SearchAggregator, включая `AllSearchEnginesFailedException`), query_chat_memory (мок MemoryManager: FTS/vector/RAG-ветки, time_range-фильтр), неизвестный инструмент, кривые аргументы.
- `tests/test_tool_loop.py` — round-trip моков `generate_chat` (tool_calls→tool→text; порядок сообщений; лимит 4; ошибка инструмента в `role:"tool"`; деградация без tools при LLMError на 1-м раунде; пустой финал → `LLMBadResponseError`).
- `tests/test_reaction_flags.py` — дефолты false у 4 тумблеров (REGISTRY+Settings), поведение гейтов с `hot.get`-моками (vasya/kucha/mimic/alan-mimic), славячий mimic не тронут.
- `tests/test_frontend_tab_mapping.py` (или в `test_param_catalog.py`) — аудит: каждая группа ровно одной вкладке, каждый параметр в одной группе, counts (61 группа; models 8, reactions 13).

Править:
- `tests/test_param_catalog.py` — counts групп/категорий (59→61), новые записи (полнота покрытия уже проверяет 1:1), при необходимости порядок/секции.
- `tests/test_vasya.py` — хендлеры под гейтом: включить флаг (patch `handlers.vasya.settings`/hot) для проверки прежнего поведения + кейсы выключенного.
- `tests/test_slavik_handlers.py` / `tests/test_edge_cases.py` / `tests/test_filters.py` — kucha под `reactions.kucha_enabled` (включить в тестах, добавить кейс выключенного).
- `tests/test_common.py` — mimic-хендлер: default false (обновить сетапы), alan-гейт, славячий mimic-регресс.
- `tests/test_message_counter.py` — кейс «не-Славик: нет инкремента/гифки» + сохранение существующих.
- `tests/test_youtube_handlers.py`/`test_youtube_summarizer_service.py` — вызов `summarize_cascade` (defaults: без video_client — старое поведение; с client-моком — каскад).
- `tests/test_llm_client.py` — `generate_chat`: payload tools/tool_choice, парсинг tool_calls/None-content, легаси `generate` без изменений.
- `tests/test_direct_chat_service.py`/хендлер-тесты direct_chat — tool_router=None (старое поведение) и включённый роутер (мок).
- `tests/test_webapp_api.py` — item.widget в GET /api/config; регресс POST (в т.ч. json-dict `summary_aliases`).
- `tests/test_settings_helpers.py` (если считает дефолты) и любые тесты, завязанные на дефолт-состояние реакций (прогон выявит).

### Документация
- README: блок «Видео-выжимка (каскад OpenRouter video_url)», «Tool Calling в прямом чате», таблицы env: `VIDEO_PRIMARY_MODEL/VIDEO_FALLBACK_MODEL/VIDEO_TIMEOUT_SECONDS/VASYA_ENABLED/KUCHA_ENABLED/MIMIC_ENABLED/ALAN_MIMIC_ENABLED`; описание вкладок админки и KV-редактора; секции «Алан» → «Леха»; замечание о дефолтах false.
- `.env.example`: те же новые переменные с комментариями (без значений секретов).
- `plans/docs/memory-project-overview.md` (T2): статусы частей по мере выполнения.
- `plans/backlog.md` при необходимости.

### Каскад развёртывания
1. Коммиты по частям (1→4), каждый с локальным зелёным прогоном затронутых тестов; перед коммитом — полный pytest (0 failed).
2. Деплой на прод (T33, DevOps): `git pull --ff-only` + `systemctl restart admin_bot` на 198.46.175.136 (`/var/www/admin_bot`); сид новых ключей произойдёт автоматически при старте.
3. Включение фич владельцем через админку (тумблеры false по умолчанию — поведение реакций не меняется до явного включения).
4. Живая верификация (T34, ждёт человека): видео-каскад (L1/L2/L3 и молчание при сбоях), тумблеры реакций, mimic Лехи, KV-редактор и вкладки.

## Открытые вопросы (для @Builder/@PM/владельца)

1. Реальная поддержка `video_url` моделями `minimax/minimax-m3:free` и `google/gemma-4-31b-it:free` на OpenRouter (проверяется живым тестом T34; модели конфигурируемы ключами — код не зависит). Если fallback-модель понимает только кадры (`image_url`) — выносим в отдельную задачу.
2. `VIDEO_TIMEOUT_SECONDS` — 7-й ключ сверх списка T3–T5 (обоснование в 3.1). Если PM против — убрать, дефолт уровня взять из существующего ключа таймаута.
3. Группа `flags.mimic_enabled` = `flags_media` (вкладка «Реакции и Триггеры»). Альтернатива — `flags_modules` (вкладка «Лимиты»): решение влияет только на каталог-строку.
4. Релокация 4 параметров окон/RAG между группами (FR-26) — моя интерпретация T26 («связанные лимиты окон/RAG»). Если имелись в виду группы `limits_summary`/`limits_search` целиком — меняется только декларация вкладки (одна строка), каталог не трогаем.
5. Tool Calling включён только для `direct_chat` (FR-17). Если PM требует «все подсервисы» буквально — добавление инструментов в search/factcheck обсуждаемо, но несёт риск двойного поиска и регрессий фразовых контрактов.
6. Переименование «Леха» затрагивает отображаемые тексты и комментарии; код-идентификаторы не переименовываются — подтвердить, что этого достаточно для владельца.
