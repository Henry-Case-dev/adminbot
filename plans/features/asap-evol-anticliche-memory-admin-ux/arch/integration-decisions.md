# ASAP-EVOL-ANTICLICHE-MEMORY-ADMIN-UX — решения интеграции

Источник: `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md` (FINAL v8, §1–§17), прочитан целиком.
База: ветка `evol/impl`, HEAD `361c9022`. Код проверен на этом дереве; файлы COG-MAP S2 не затрагиваются.
Характер документа: только решения по существующему коду. Реализацию выполняет Builder, проверяет Reviewer.

## 0. Фактическая карта хранилищ (одна истина каждая)

| Что | Где физически | Кто читает |
|---|---|---|
| PG-конфиг, hot-ключи | `bot_settings` (`services/pg_db.py:34-40`) | `hot_config` |
| Per-chat overrides/gates/keys | `chat_params` (JSONB, `pg_db.py:140-157`, API `services/chat_params.py:407`) | runtime, UI |
| Банк клише | PG `anticliche_cache` singleton (`pg_db.py:286-303`; чтение/запись `services/anticliche_cache.py:59-80,169-201`) | `get_rules()` memo (`:125-142`) |
| Событийный журнал | SQLite `mca_events` + `mca_event_aggregates` (`services/database.py:242-283`; запись `services/mca_events.py:701-770`; чтение `:853-902`) | админка, телеметрия |
| Свои отправленные ответы | SQLite `mca_bot_outputs` (`database.py:881-905`; writer `services/bot_output_ledger.py:80+`) | память/цитаты |
| Сырые сообщения/граф | SQLite `smart_messages`, `nodes` (`database.py:2226-2270`) | `summary_memory` |
| Versioned prompt registry | `bot_settings` `prompts.*` + код-константы (`services/prompt_registry.py:1072,2200`) | сборка промптов |
| Речевой system | `services/prompt_composer.py:_compose` (`:1514-2008`), единая точка `compose_speech_system` (`:965`) | все публичные Writer'ы |
| Логи процесса | stdout → journald (`bot.py:160-207`) + кольцо `services/log_ring.py:115-198` | `/api/status/logs` |

Вывод: достраивать нечего заново — не хватает ровно двух PG-хранилищ (см. §1).

## 1. Модель данных AntiCliche на существующем хранилище

**Вердикт: 2 новые PG-таблицы + 1 расширение JSONB. Девять логических сущностей — это карта на существующие журналы, а не девять таблиц.**

| Логическая сущность | Физически | Комментарий |
|---|---|---|
| `Source` | код-реестр `services/anticliche_sources.py` (стабильные id) + `anticliche_source_state.enabled` | конфиг в коде, включённость в PG |
| `SourceCheck` (последняя) | `anticliche_source_state`: `last_check_at, last_status, last_http, revision, etag, docs_fetched, docs_parsed, last_success_fetch_at, last_success_analysis_at, next_attempt_at, last_error_code` | история — событием |
| `SourceCheck` (история), `DocumentProcessing`, `ModelAnalysis`, `AuditEvent` | `mca_events` (`component='anticliche'`, `trace_id=run_id`) | уже так пишет воркер: `anticliche_worker.py:485-498` |
| `RefreshRun` | `trace_id` + события start/terminal; сводка стадий — события того же `trace_id` | одна пара start/terminal на цикл |
| `ClicheCandidate` (staging) | `anticliche_snapshot.rules` JSONB строки со `status='candidate'` в единственной mutable строке `status='draft'` | без третьей таблицы |
| `RuleFamily`, `OwnerLiteral`, `bank_only` | те же строки `rules` с полями `strategy, family_id, scope, route, exceptions, priority, enabled, evidence, approved_by, approved_at` | одна каталог-структура |
| `PublishedSnapshot` | `anticliche_snapshot` (PK `version`; `state` + `compiler_version` + `checksum` + `source_revisions` + `parent_version` + `publisher` + `published_at` + `effective_rule_count` + неизменяемый `rules`) | immutable опубликованные строки |
| `PromptCompileTrace` | манифест/trace композера (`prompt_composer.py:2146-2175`, bounded) + агрегированное `mca_events` событие применения/сбоя | не по событию на токен |

Дополнительно: `anticliche_cache.patterns` остаётся **материализованным снимком активной версии** (обратная совместимость `get_rules()`); в каждый элемент добавляются `status/strategy/family_id/scope/evidence` — аддитивно в JSONB, без DDL.

**Атомарная публикация и LKG.** Публикация = одна PG-транзакция: `INSERT anticliche_snapshot(state='published')` + upsert `anticliche_cache` (version = версия snapshot) → затем инвалидация memo. Сбой транзакции → не изменено ничего, активная версия и owner-literal остаются. Чтение после рестарта: `bot.py:1365-1370` уже греет memo из PG. Компилятор при недоступном/битом snapshot использует `anticliche_cache` (предыдущая версия) и `status='lkg'`; пустой набор отдаётся **только** когда в PG действительно нет опубликованной версии — «нет правил» отличается от «не загрузилось» явным статус-кодом, не пустым массивом.

**Отклонено:** (а) девять таблиц по одной сущности; (б) складывать staging в `bot_settings` (каталог-hot — не для рабочего состояния и запрещённых аудитом ключей); (в) переиспользовать `patterns` как версионный журнал (singleton теряет историю/откат).

**Приёмка:** откат восстанавливает пару «правила + наблюдение» атомарно; после рестарта активна последняя опубликованная версия; сбой источника/модели не меняет `version` и не даёт ложный `0`.

## 2. Путь компиляции промпта: одна точка вставки, одна трасса

**Вердикт: новый слой `anticliche_hint` в `_compose`, между слоем 10 (`style_policy_hint`) и слоем 11 (`channel_output`). Второго сборщика нет.**

- Вход плана: аддитивное поле `PromptPlan.anticliche: AnticlicheRef | None` (`prompt_composer.py:536-574`); резолв — из in-process снимка активной версии (как `_cached_rules`), 0 сетевых вызовов, 0 LLM.
- Единственный производитель текста: `services/anticliche_compile.py::compile_hint(profile, scope, mode, snapshot) -> HintResult(text, selected_ids, skipped[(id, reason)], hash, version)`. Runtime-композер и preview-API вызывают **одну и ту же** функцию; preview передаёт зафиксированный fixture метаданных, не подделывая Observer/L1.
- Место после `style_policy_hint` и до `channel_output`: блок — стилевое уточнение того же класса, а формат/доставка остаются последним жёстким ограничением. Хвостовой expression-контракт (`:1999-2006`) не трогается.
- Трасса слоя: `LayerTrace(layer='anticliche_hint', block_id='style.anticliche.hints', owner='anticliche', source='snapshot:vN', revision=effective_hash, chars, rendered, skip_reason)`; `versions['anticliche_snapshot']=v`; skip-причины закрытым набором (`anticliche_off`, `anticliche_no_snapshot`, `anticliche_no_relevant_hints`), чтобы «0 подсказок» не выглядел сбоем.
- Текст блока — код-константа, объявленная в реестре через `declare_prompt` (`prompt_registry.py:1072`), иначе падает аудит необъявленных промпт-констант (`:594-622`). В блок не попадают Markdown источников, URL и regex.
- Гарантия «нет второго компилятора/валидатора»: `speech_owner_block` (`:884-934`) и `compose_verbalizer_system` (`prompt_style_blocks.py:544-596`) AntiCliche не импортируют; тест-страж по импортам этих путей.

**Отклонено:** (а) вставлять блок через `character_block`/`style_directives` вербализатора (двойная инъекция на фактчеке, который уже идёт через `compose_speech_system`); (б) отдельный фактчек-композер; (в) preview, собранный иначе, чем runtime.

**Приёмка:** текст preview байт-в-байт равен фактическому блоку в манифесте при одинаковых profile/scope/mode/version; при OFF/без версии — 1 слой с причиной и байт-паритет остальных слоёв.

## 3. Отсечение AntiCliche-стимула к перегенерации

**Вердикт: в `verbalize_validated` (`services/negative_constraints.py:651-932`) коды стиля перестают быть условием повтора; независимые гарды сохраняются как есть.**

Точки:
- Первый проход: `codes` вычисляются, но возврат происходит при отсутствии form/numeric/metatext причин (`:828-831` — оставить, стиль из условия убрать).
- Ветка `else: retry_system = CLICHE_RETRY_SYSTEM_PROMPT` (`:870-871`) удаляется; цикл исполняется **только** для `metatext` / `form` / `numeric`. Константа и её регистрация (`prompt_registry.py:1419`) остаются как исторический материал, но перестают быть достижимыми.
- Наборы правил разделяются в одном месте (`:490-511`): `STYLE_SIGNALS = {as_ai, classic_genre, summing_up, in_conclusion, hope_helped, mirror_no_you, you_asked_before}` → только наблюдение; `FORMAT_GUARDS = {plain_no_tables, bullet_list}` → отдельная причина `format_retry` и отдельный зарегистрированный промпт формы, из того же bounded-бюджета.
- `as_ai` остаётся наблюдением: запрет «отсылки к тому, что ты ИИ» уже действует **до** генерации (`prompt_style_blocks.py:32-47`, пункт 1) и на выходе остаётся `sanitize_outgoing`; переносить его в metatext-гард нельзя — это и был бы скрытый повтор под другим именем.
- Статистика: `stats['hits']` остаётся, добавляется `stats['anti_cliche_retries']` (всегда 0) и `stats['cliche_observed']`. Запрещено писать клише-находку в `form_guard_rejected`, `metatext_*`, `format` — коды не переиспользуются.
- Вызывающие (`direct_chat_service.py:7101-7109,7321`, `factcheck_service.py:1638-1643,2348-2351`, `summary_generator.py:4248-4251`) не меняют контракт: они по-прежнему передают `enabled_rules`/`dynamic_rules`, но стилевые коды больше не влияют на число генераций.

**Отклонено:** (а) оставить ≤1 стилевой повтор «для мягкости»; (б) вырезать фразу из готового текста; (в) переименовать стилевой отказ в `format`/`metatext`.

**Приёмка:** текст с любым стилевым попаданием (hardcoded, dynamic, pinned, множество) → ровно один `generate_call`; независимые numeric/form/metatext/format проверки дают прежнее поведение; тест «нет пути, собирающего retry-сообщение с `CLICHE_RETRY_SYSTEM_PROMPT`».

## 4. Память: понимание и исправление собственного высказывания бота

**Вердикт: детерминированный резолв референта по существующим цепочкам и ролям. Нового движка, судьи и бюджета нет.**

Опоры (все уже есть):
- Триггер хода и reply-цель: `ToolContext` (`tool_router.py:1205-1274`: `query`, `reply_to_message_id`, `reply_source_message_id/text`, `correlation_id`).
- Свои прошлые ответы с `tg_message_id` и `sent_at`: `mca_bot_outputs` (`database.py:881-905`); reply-граф: `smart_messages.reply_to_id/tg_message_id` (`:2226-2237`), роли `message_identity.ROLE_*` (`message_identity.py:82-85`).
- Типизированная доказательная база: `EvidenceBundle` (`mca_retrieval_context.py:198-239`: `author/reply_addressee/quoted_speaker/subjects/structured/contradictions`) и `RetrievalCandidate` (`:337-366`: `subject_entity_id`, `speaker_entity_id`, `attribution_method`, `origin_type`, `verification`, `contradiction_status`, `provenance_backed`).
- Свой вывод ≠ факт о человеке: `provenance.is_self_referential_origin` (`provenance.py:263`), уже фильтруется в direct-RAG (`direct_chat_service.py:11188-11189`).
- Статистика отдельно: `MetricResult`/`NumericClaim` (`chat_statistics.py:157-198`) + numeric-гард.

Контракт (без литеральных имён):
1. **Резолв референта.** Вопрос о имени/кличке/«этот твой X» разрешается в порядке: (а) сообщение, на которое отвечает пользователь, если это ряд `mca_bot_outputs` → референт введён самим ботом; (б) иначе — непосредственно предшествующий ответ бота в этой ветке (соседство хода, не top-N); (в) иначе — резолв по участникам чата существующим AliasResolver. Токен считается «названным ботом», если он присутствует в тексте собственного предшествующего ответа и **не** имеет подтверждённой личности. Никаких списков имён, regex и id чатов.
2. **Идентичность.** В `_memory_lookup_resolve` (`tool_router.py:3413-3448`) третья ветка с голым именем перестаёт возвращать `resolution='resolved'` (`:3447`): `verified_id` (есть Telegram id), `name_only_unverified`, `ambiguous`, `unresolved`. Форма payload совместима, поля аддитивны. Отождествление только по id; одноимённые не сливаются.
3. **Смысловая релевантность.** `_memory_lookup_general` (`:3612-3666`) строит запрос из текущего вопроса (`ctx.query`, тема/reply), а не только из имени; при `purpose='general'` тематические термины идут вместе с именем. Тема не выводится — при отсутствии сигнала остаётся unknown.
4. **Сериализация.** `str(fact)` в vector-фолбэке (`:1656-1659`) заменяется разбором структуры: в модельно-видимый текст идёт только текстовое поле факта, метаданные (`chat_id/method/coverage/source_ref/confidence/rank`) остаются в конверте (`services/tool_result.py:484-596`). Неизвестная форма → `memory_tool_payload_invalid`, без repr в промпт.
5. **Статистика только по намерению.** `_query_chat_memory` включает stats-режим лишь при явном `stats`-аргументе (`:1566-1573`) — оставить; вопрос о человеке не запускает счётчики, а числа выдаются только как `MetricResult` с областью/методом/единицей.
6. **Память в речи.** Writer получает типизированную опору (`EvidenceBundle`), а не список фрагментов; «внутреннее доказательство vs естественная реплика» — правка существующей инструкции `style.bot_knowledge` (`prompt_style_blocks.py:187-190`) новой ревизией реестра, без второго источника инструкций. Явный вопрос об источнике — источник и дата показываются; непрошенный дамп и `chat_id` — нет.

**Негативный тест «транслит/имя» (структурно эквивалентный, без реальных имён):** параметризация ≥5 вымышленными именами/алиасами/парафразами; проверяются: (а) ответ на «кто такой X» после собственного введения X не приписывает биографию/профессию/религию и либо уточняет, либо признаёт своё употребление; (б) reply на своё сообщение и follow-up без reply дают один и тот же вывод; (в) имя есть в исторических текстах, но не участник — нет слияния, при прямом историческом вопросе факт доступен; (г) два одинаковых имени — `ambiguous`; (д) имя в цитате другого человека — `quoted_speaker`, не self-report; (е) свежий и устаревший противоречащий факты датируются; (ж) связанный кандидат с меньшим score не вытесняется (`apply_identity_prior`, `:368-397`); (з) обычный дружеский callback остаётся возможен; (и) явная просьба об источнике даёт `SourceRef`+дату; (к) явная статистика работает, биографический вопрос не содержит служебных полей и широких чисел. Проверки — на детерминированном слое (что попало в контекст/конверт) плюс голден-набор (`scripts/run_golden_questions.py`).

**Отклонено:** per-turn LLM-судья, «топ-1 вместо top-k», regex/список имён, отдельный `MemoryJudge`/второй retrieval, глобальное выключение памяти.

## 5. Наблюдаемость: логи с начала запуска и честная история AntiCliche

**Вердикт: историю логов даёт journald через существующий адаптер; кольцо остаётся live-tail; счётчики определяются по тому же источнику и той же эпохе.**

- Источник: stdout процесса уже пишется в journald и уже санитизируется на консольном обработчике (`bot.py:160-165`, `SecretMaskFilter`). Чтение — существующий `services/system_logs_fetcher.py` (каскад SQL API → `journalctl`, `:1-90`), но в режиме страниц, а не «последние 200 строк».
- Эпоха запуска: `_SYSTEMD_INVOCATION_ID` (реальный id инвокации) как `run_epoch_id`; `Доступно с` = самая ранняя доступная запись эпохи; `Покрытие: полное|частичное` и явный разрыв текстом. `errors_since_start` и фильтр `ERROR/CRITICAL` считаются по одной и той же эпохе и одному источнику.
- Пагинация: курсор `__CURSOR`/`__REALTIME_TIMESTAMP`, порядок новые→старые, «Загрузить ещё» без дублей и потери позиции. Размер страницы — транспорт, не лимит истории.
- Если journald недоступен (не-systemd окружение): `history_source='ring'`, `Покрытие: частичное`, честная нижняя граница; запрещено выдавать кольцо за полную историю или повышать `LOG_RING_MAX_ENTRIES` как «исправление» (`log_ring.py:118-127`).
- RBAC/санитайзинг: общий журнал эпохи — только глобальному админу (в системных строках есть идентификаторы других чатов); остальным — scoped-вид с `restricted: true`. На чтении повторно применяется `log_ring.sanitize` (`:65-84`); заголовки/env/ключи не отдаются.
- AntiCliche-история — не из кольца: вкладка «Журнал» и вкладка «Анализ» читают `mca_events` (`query_events` по `component='anticliche'`/`trace_id`, `mca_events.py:853-902`). Реальная доступность источника, реальные вызовы модели, кандидаты и опубликованные правила — из этих событий + `anticliche_snapshot`, а не из `last_status`.
- Точный AntiCliche-блок, реально отданный Writer, берётся из манифеста/trace (`prompt_composer.py:2146-2175`) и при необходимости восстанавливается из неизменяемого snapshot; если точное восстановление недоказуемо — «Точный текст недоступен; доступны IDs и hash».

**Отклонено:** второй логгер, дублирование всего потока в новую таблицу, `maxlen=10000`, «Ошибки 42» при трёх WARN на экране.

**Приёмка:** после заполнения кольца самая ранняя запись эпохи достижима; `errors_since_start == count(ERROR+CRITICAL)` по доступной истории; две последовательные выгрузки без дублей; поиск по `trace_id`; отсутствие секретов; честный `Нет данных` вместо нуля.

## 6. UI-контракт: AntiCliche, состояния, селектор чата, модули, мемы

**Вердикт: расширяем существующие компоненты; новых дизайн-примитивов нет.**

- AntiCliche = подраздел «Речь и характер»: карточка в витрине (`web/api/speech.py:2448-2519` секции + `app.js:24189-24215` группы) и раздел `speechSection='anticliche'` с шестью вкладками. Один `ctl-toggle` (`index.html:1544-1551`), сохранение — существующий config-путь с optimistic 409 (`routes.py:1254-1350`), значение — резолвер вида `mca_gates._module_catalog_flag` (env AND catalog). При OFF: компилятор даёт пустой hint, авто-опрос источников приостановлен, банк/версии/логи сохранены.
- Честное здоровье: четыре независимые оси в API — `reachability` (последняя проверка источника), `content` (скачано/разобрано), `analysis` (последний завершённый `ModelAnalysis`), `runtime` (активная версия + компилятор). Четыре KPI строятся из них; один зелёный бейдж на всё запрещён. `Активная версия vN` и время публикации — из snapshot, при отсутствии «Не опубликована».
- Экран загрузки: `boot-splash` (`index.html:101-112`) снимается по **терминальному** состоянию (`ready|empty|error`) с `data-boot-state`; скелетоны исчезают в любом терминальном состоянии; кнопка «Повторить»; никаких `setTimeout`. Ошибка одного раздела не держит оболочку.
- Селектор чата: на телефоне `_ctlScopePlacement` (`app.js:2417`) больше не превращает панель в нижний лист по умолчанию — приоритет `below` от триггера с собственным скроллом и `maxHeight`; лист — только когда места под триггером меньше трёх строк и над ним тоже нет места, с сохранением видимости триггера. Координаты пересчитываются на scroll/resize/`viewportChanged` (`positionScopePanel`, `:19781-19866`); тот же overlay-ранг, второй поповер не создаётся.
- Модули: сохраняются `module-toggle.is-readonly`, `.module-global-hint`, `.module-global-btn` (`app.js:16073-16105`). Для `runtime_gate=='per_chat'` (`module_registry.py:45,161`) добавляется трёхсостояние «Наследовать/Включить/Выключить» с записью в существующее пространство `chat_params.gates` (`chat_params.py:114,407`), сброс = удаление ключа; сервер отдаёт `global/chat_override/effective/source/editable_here/scope_type/reason`. Для `runtime_gate=='global'` переключатель виден, но read-only, плюс «Настроить глобально» и честный RBAC-вид.
- Мем-инициатива: `GET/POST /api/initiative/meme-settings` принимают `chat_id=None` (Глобально); полезная нагрузка берётся существующим `meme_initiative.load_settings(None)` (фолбэк на hot уже реализован, `meme_initiative.py:308-358`), запись в Глобальном идёт в те же hot-ключи `initiative.meme_*`, чатовые сохранения остаются дельтой (`web/index.html:1611-1650`, `app.js:10985-11034`). Квоты в Глобальном — «не измерялось: считается по чату», не ноль.
- Состояния (`loading/empty-never-run/empty-no-new/partial/network-error/model-error/source-blocked/stale-cache/off/running/forbidden/conflict/rollback`) реализуются на существующих токенах `badge`, `ctl-*`, `w-spinner`; статус всегда текст+иконка+цвет.

**Отклонено:** новая страница верхнего уровня, второй редактор списка клише в «Библиотеке промптов» (старый блок `data-block="anticliche-monitor"`, `index.html:3963-4020`, заменяется одной ссылкой), отдельный селектор модели внутри AntiCliche (карточка в «Моделях и подключениях» — единственная точка), фиктивные проценты загрузки.

**Приёмка:** 1536×960 и 390×844 без горизонтального переполнения; OFF/ON меняет реальный runtime; `docs_fetched=5, analyzed=2` показаны в своих полях; reload во время run восстанавливает состояние по `run_id`; GLOBAL-мемы наследуются чатом и сбрасываются.

## 7. Бюджеты, лимиты и таймауты: что остаётся, что запрещено

| Константа | Вердикт | Обоснование |
|---|---|---|
| `anticliche_cache.max_patterns()` 200/1000 (`anticliche_cache.py:30-52`) | оставить как **вместимость банка** | не применяется к отбору подсказок в промпт |
| `max_patterns_per_run()` 40, `max_rounds()` 3 (`anticliche_worker.py:57-78`) | оставить | выходной лимит модели и учёт бюджета провайдера |
| `MAX_SOURCE_CHARS` 60000 (`anticliche_worker.py:50`) | оставить | граница входного материала источника |
| `REFRESH_DAYS=7` (`:51`) | оставить | каденция; ручной запуск её не ждёт |
| `_MAX_RETRIES_HARD_CAP=2` (`negative_constraints.py:35`) | оставить, но стиль исключён из условий | бюджет теперь только form/numeric/metatext/format |
| `_MEMORY_LOOKUP_RESULT_MAX_CHARS` (`tool_router.py:3324-3335`) | оставить как транспорт с `truncated: true` | не правило отбора фактов |
| `LOG_RING_MAX_ENTRIES` 1000 (`log_ring.py:122`) | не менять | кольцо — live-tail, историю даёт journald |
| `limit ≤ 1000` в `/api/status/logs` (`routes.py:1983`) | переопределить как размер страницы | не глубина истории |
| `MANIFEST_CACHE_MAX` (`prompt_composer.py:2146-2175`) | оставить | bounded-хранение трасс без роста памяти |

**Явно запрещено вводить:** квоту токенов/символов на AntiCliche-подсказки; «не более N семейств» как жёсткий потолок выбора; `max_memory_facts`; TTL/таймаут на retrieval памяти; вайп кэша по времени; «20-минутный watchdog». Ограничения выбора подсказок задаются доказанным качеством/латентностью и видны в UI как «исключено, причина», а не молчаливое усечение.

**Приёмка:** `grep` по новым изменениям не находит новых констант-квот для памяти/AntiCliche; `0 релевантных подсказок` — валидный результат, не ошибка; при нехватке места под pinned в UI перечислены исключённые owner-literal с причиной.

## 8. Риски, параллельность, что дальше

- Наивысший риск: **§3 (отсечение повтора)** — единственное место, где ошибка меняет уже доставляемый текст; проверять до остального.
- Второй риск: **§1 атомарность публикации** (несовместимая пара snapshot/cache при сбое PG).
- Третий риск: **§4 идентичность** (пересечение с существующими identity-prior и self-referential фильтрами).
- Параллельность: §1–§3 один писатель (`services/anticliche_*`, `negative_constraints.py`, `prompt_composer.py`); §4 другой писатель (`tool_router.py`, `mca_retrieval_context.py`, `direct_chat_service.py`); §5 третий (`system_logs_fetcher.py`, `routes.py`, `status_service.py`); §6 после серверных контрактов (`web/api/speech.py`, `web/app.js`, `index.html`). Общие файлы `routes.py`/`index.html` — сериализовать.
- Владельцу решать нечего: все развилки — инженерные и закрыты этим документом.
