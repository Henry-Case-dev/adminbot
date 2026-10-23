# INSPECTOR: точный промпт, per-call trace, причины пропуска

> **Rework 2 (после `evidence/inspector-review.md`, Needs Fixes).** Закрыты
> блокеры F1 (fallback: журнал = фактическое HTTP-тело), F2 (иерархия только
> по маскированным текстам; preview тоже с текстом), F3 (`generate_chat` +
> фоновые/воркер/стрим каналы в журнале, явный `trace_coverage`).
> Привязку карты/графа к кандидату делает PM (не входит в этот лейн).

Лейн `SPEECH-INSPECTOR-EXACT`, writer. 24.10.2026, локальное время UTC+12:00.
Прод/SSH/сеть/живые чаты не использовались: транспорт провайдера подменён в
тестах, `Temp`-SQLite вместо PG.

Закрываемые строки карты `asap-speech-arch`: **INS-EXACT**, **INS-TRACE**,
**INS-SKIPREASON** (были `NEEDS_IMPLEMENTATION`), плюс реализационная часть
**INS-HIERARCHY**/**INS-CONFLICT** (оставались `NEEDS_AGENT_CHECK`).

## 1. Что было не так (кандидат `e4ee54f3` / текущий HEAD)

* Inspector отдавал только `system_masked`; «полный итоговый промпт» как режим
  отсутствовал, а `preview` и «фактически отправлено» различались лишь бейджем.
* Не было per-call журнала: `run_id=correlation_id` + версии слоёв, но без
  модели/провайдера и checksum фактического тела запроса.
* `skip_reason` выводился машинным кодом (`samples_absent`) как основной текст.
* У `few_shot`/`channel_output` не было человеческих объяснений.
* Конфликты определялись только в трёх случаях (`core_protected_from_budget`,
  `duplicate_owner_character`, `one_word_not_supported`); устаревшие метки
  `SOUL-*` в payload не обнаруживались, классы не были видны владельцу.

## 2. Что добавлено

### 2.1 Точный payload и per-call trace (INS-EXACT / INS-TRACE)

| Место | Что |
|---|---|
| `services/prompt_composer.py:1017` | `PROVIDER_CALL_MAX=24` — bounded журнал реальных вызовов (in-memory) |
| `services/prompt_composer.py:1913` | `payload_checksum()` — sha256 канонического JSON фактически отправленного тела |
| `services/prompt_composer.py:1953` | `record_provider_call()` — correlation_id, модель, провайдер, модуль/шаг, канал (primary/fallback), статус/ошибка, роли, длины, sha256 каждого сообщения, санитизированный точный текст |
| `services/prompt_composer.py:2049` | `last_provider_call()` / `provider_calls()` — выборка по чату (по хешу, не по сырому ID) |
| `services/prompt_composer.py:2061` | `render_layer_texts()` — точный текст каждого ВКЛЮЧЁННОГО блока (owner-debug, отдельно от телеметрии) |
| `services/llm_client.py:103` | `_record_provider_call()` — единая точка записи; маскирует секреты каноническим `_mask_secrets` ДО записи, fail-open |
| `services/llm_client.py:457/466` | метка провайдера (только хост) и канала (primary/fallback) |

Запись стоит на границе `LLMClient.generate`: **тот же объект payload**, что
уходит в `_post` (после `fallback_payload_adapter`); checksum считается по нему
же. Фиксируются и неудачные попытки (`status=error`), и ответы без валидного
content.

Приватность (R17):

* в журнал не попадают ключи/токены (`_mask_secrets`: Bearer/Basic, `key=…`,
  `"key": "value"`, `sk-…`/`gsk_…` и т.п.);
* `chat_id` хранится только как маска + `chat_sha12`; сырой ID не отдаётся;
* хеши (`payload`, `messages_checksum`, `sha256` сообщений) считаются по
  фактическим байтам и остаются доказательством при усечении длинного текста
  (`_PROVIDER_TEXT_MAX=60000`).

### 2.2 Inspector API

| Место | Что |
|---|---|
| `web/api/speech.py:1812` | `_inspector_exact()` — режим «полный итоговый промпт»: `label` = `last actual request` **или** `preview`, checksum, correlation_id, модель/провайдер/этап, roles, system + user-блоки в порядке запроса |
| `web/api/speech.py:1975` | выбор вызова: сначала по `correlation_id` снимка хода, затем самый свежий вызов этого чата; нет снимка → честный `preview` |
| `web/api/speech.py:1619` | `_inspector_layer_rows()` — `label` слоя и `skip_reason_human`, код остаётся отдельным полем |
| `web/api/speech.py:1637` | `_inspector_hierarchy()` — группы `L2 контракт → Core → Личность → Контекст/план → Выражение/юмор → Примеры → Стиль`, с текстом, источником, редакцией |
| `web/api/speech.py:1706` | `_style_rule_conflicts()` — реальные конфликты типизированных правил формы (chat vs global), одинаковое правило = наследование, не конфликт |
| `web/api/speech.py:1755` | `_inspector_conflicts()` — классы `typography/length/role/budget/chat_global/soul_legacy/profanity_case` со счётом и `coverage_note` |

Классы конфликтов: **типографика** и **длина** — из реальных правил
`style.policy` (`dash`, `trailing_period`, `quotation_marks`, `line_breaks`,
`forbidden_chars`, `one_word`); **роль** — дубликат характера в identity;
**бюджет** — `core_protected_from_budget`; **SOUL-легаси** — фактический поиск
`SOUL-\d+(\.\d+)*` по тексту отрендеренных блоков; **мат/регистр** — честно
`0 найдено` и `coverage_note`: второго источника правил в этой сборке нет,
конфликт не выдумывается.

### 2.3 Человеческие причины пропуска (INS-SKIPREASON)

`services/prompt_composer.py:208` — `SKIP_REASON_LABELS` покрывает весь
закрытый `SKIP_REASONS`; `skip_reason_label()` (стр. 292) отдаёт текст, а
незнакомый код честно помечает как техническую причину. Примеры из источника
§6:

* `samples_absent` / `expression_examples_absent` → «Примеры не выбраны: нет
  подходящих подтверждённых примеров.»
* `channel_output_not_required` → «Отдельный форматный блок этому этапу не
  нужен.»
* `budget_excluded` → «Слой не вошёл в запрос: исчерпан бюджет дополнительных
  блоков (технический лимит модели).»

В UI машинный код живёт только в `title` элемента (всплывающая диагностика).

### 2.4 UI (INS-EXACT/HIERARCHY/CONFLICT, U-04)

| Место | Что |
|---|---|
| `web/index.html:9357` | карточка «Полный итоговый промпт»: бейдж «фактический запрос провайдера»/«превью сборки», checksum, correlation_id/модель/провайдер/этап, system и user-блоки |
| `web/index.html:9405` | «Почему слои не отправлены» — русский текст, код в `title` |
| `web/index.html:9426` | «Иерархия сборки» — группы + клик по блоку раскрывает текст/источник/редакцию |
| `web/index.html:9473` | «Конфликты и дубликаты правил» — классы со счётом и провенансом |
| `web/app.js:21679` | `speechExactLabel`, `speechHierarchyToggle/IsOpen`, `speechInspectorSkipText` (имя не перекрывает существующий `speechSkipReasonText` словаря формы) |
| `web/static/app.css:4744,4782` | раскладка новых рядов и перенос длинного checksum (`overflow-wrap: anywhere`, `word-break: break-all`) |

Ничего из W4/ASAP3 UI не переписано: новые карточки — аддитивные блоки внутри
существующей секции Inspector, полигональный фон/стекло не тронуты.

## 3. Доказательства

### 3.1 Тесты (локально, без сети)

```
py -3 -m pytest tests/test_speech_inspector_exact.py \
  tests/test_soul1_w6_speech_ui.py tests/test_soul1_composer_layers.py \
  tests/test_soul1_core_composer_integration.py \
  tests/test_expression_isolation_followup.py tests/test_soul14_layers_payload.py \
  tests/test_prompt_migrations.py tests/test_soul1_core_version_propagation.py -q
→ 113 passed
py -3 -m pytest tests/test_llm_client.py -q          → 115 passed
py -3 -m pytest tests/test_speech_inspector_exact.py -q → 17 passed
```

`tests/test_speech_inspector_exact.py` (CONTRACT) доказывает:

1. **checksum == фактическое тело**: транспорт перехватывает payload, тест
   независимо считает sha256 канонического JSON и сравнивает с журналом;
   другой payload → другой checksum.
2. **R17**: `sk-live-…` и `Bearer …` в сообщениях не появляются в журнале
   (`***`), сырой `chat_id` не отдаётся, `chat_sha12` стабилен.
3. **exact = last actual request**: `label`, `correlation_id`, checksum, точный
   system (не маска) сверяются с реальным вызовом; без журнала — `preview`.
4. **skip reasons**: каждый пропущенный слой имеет русский текст, отличный от
   кода; `few_shot`/`channel_output` объяснены.
5. **hierarchy**: текст включённого блока равен тексту манифеста; источник и
   редакция непустые; у пропущенного узла — причина.
6. **conflicts**: одинаковое правило chat/global — наследование (0 находок),
   расходящееся — `typography`/`chat_global_rule_override`; `profanity_case`
   честно 0 с `coverage_note`; метка `SOUL-16.5.0` в identity даёт
   `soul_legacy_label_in_payload` с провенансом.

### 3.2 UI-матрица (`tests/ui_inspector_exact_e2e.py`)

Payload строится **настоящим** `_inspector_payload` (temp-SQLite, сид манифеста
`l2_writer` + запись реального provider-вызова), а не руками. Стенд: реальные
`web/index.html` + `web/app.js` + `web/static/app.css`.

```
.venv/Scripts/python.exe tests/ui_inspector_exact_e2e.py
→ [inspector-exact-e2e] checks=142 failures=0
```

Viewports: 320×720, 360×780, 390×844, 430×932, 1280×900, 1440×900, 667×375
(landscape). На каждом проверено: бейдж «фактический запрос провайдера»,
checksum совпадает с sha256 отправленного payload и не выходит за карточку,
system совпадает, `white-space: pre-wrap` + `overflow-wrap: anywhere`,
отсутствие горизонтального скролла страницы и выхода текста за карточку,
русские причины пропусков (код — в `title`), раскрытие блока иерархии с
текстом/источником/редакцией, наличие карточки конфликтов.

Скриншоты: `evidence/inspector/inspector_exact_{320_720,360_780,390_844,
430_932,1280_900,1440_900,667_375}.png` + `inspector_exact_top_{390_844,
1280_900}.png` (верх карточки с checksum). Визуальная проверка реальных
пикселей (Browser Use): длинная русская фраза и URL в system переносятся,
checksum ломается по строкам внутри карточки, шапка/стекло не перекрывают
новые блоки, дублирующих горизонтальных прокруток нет.

### 3.3 Регрессия существующих UI-контуров

```
.venv/Scripts/python.exe tools/ui_w4_ui_e2e.py --no-shots
→ == ИТОГ: failures=0, POST=8, notes=163
.venv/Scripts/python.exe tests/ui_asap3_hint_speech_e2e.py
→ [asap3-hint-e2e] PASS: 10 проверок
node --check web/app.js → 0
```

## 4. Rework 2 — блокеры ревью

### F1 (INS-EXACT, fallback): журнал = фактическое HTTP-тело

Было: запись брала `payload` до подмены `model` в `_post_fallback` и исходные
`messages` (не `payload["messages"]` после адаптера) → при fallback владелец
видел неотправленный текст и checksum ≠ тела.

Стало: точки фактической отправки помечают РОВНО отправленный объект —
`services/llm_client.py`:

* `_post_with_key(..., sent=…)` → `("primary", payload)`;
* `_post_fallback(..., sent=…)` → `("fallback", fallback_payload)` с уже
  подменённым `model`;
* `_fallback_with_retries(..., sent=…)` — сквозная передача;
* `_record_sent_call()` берёт `sent[-1]` (последнее отправленное тело) и
  сообщения ИЗ ЭТОГО тела; `generate`/`generate_chat` пишут из него, включая
  error-ветки (`status=error`) — неудачная primary-попытка не подменяет
  финальный снимок.

Repro (тест `test_fallback_trace_is_the_body_that_went_on_the_wire`): primary
500 → адаптер сокращает user до `Q-cut` → fallback 200. Тест исполняет
РЕАЛЬНЫЙ `_post`/`_post_fallback` (транспорт-двойник фиксирует `json=`):

| | до фикса | после |
|---|---|---|
| `journal.messages[-1]` | `Q` (исходный) | `Q-cut` (как в теле) |
| `journal.model` | `trace-model-1`/старый объект | `trace-fallback-1` |
| `journal.checksum == payload_checksum(http_body)` | **False** | **True** |
| `journal.channel` | `primary` | `fallback` |
| `journal.provider` | `provider.example` | `fallback.example` |

### F2 (INS-PRIVACY): иерархия только по маскированным текстам

Было: `_inspector_hierarchy` получал сырой `render_layer_texts(manifest)`, а
маскированная копия `sent["layer_texts"]` в UI не использовалась → секрет и
длинный ID попадали в JSON/DOM.

Стало: `web/api/speech.py:1961` передаёт в иерархию `{"layers":
sent["layer_texts"]}` (уже `_mask_text`), плюс `_inspector_exact` маскирует
`system`/сообщения на отдаче (checksum и per-message `sha256` по-прежнему
считаются по фактическим байтам). Preview-only тоже получает маскированные
тексты (`_preview_manifest` → `layer_texts`), поэтому клик больше не показывает
«текст недоступен».

Тест `test_inspector_hierarchy_is_masked_but_keeps_provenance`: в JSON нет
`sk-live-…` и полного `123456789012`, есть `***`/`[id]`, при этом слой
`identity` сохраняет `source=global`, непустую `revision` и структуру текста.
E2E дополнительно проверяет DOM: `SECRET`/`LONG_ID` не встречаются на всех
7 viewport'ах (142 проверки, 0 падений).

### F3 (INS-TRACE): покрытие каналов, а не только `generate`

* `generate_chat` (tool-calling Stage-1/tool) — тот же bounded-журнал:
  model из тела, roles, sha256 сообщений, `module/step`, correlation_id,
  маскирование; тест `test_generate_chat_is_traced_with_tools` сверяет
  checksum с телом, где есть `tools`.
* `generate_background` и `generate_worker` (выделенные роли) — пишутся с
  `module=background|worker`, ошибки — `status=error`.
* `stream_chat_completion` — запись при успешном SSE-стриме.
* `composer.trace_coverage()` (`PROVIDER_TRACE_COVERAGE`) отдаётся в API как
  `trace_coverage` и показывается в UI: `generate`, `generate_chat`,
  `generate_background`, `generate_worker`, `stream_chat_completion` —
  «пишется»; `embed` — «НЕ пишется» с причиной (контракт `input/vectors`, без
  messages). Молчаливого отсутствия больше нет.

Тест `test_inspector_declares_trace_coverage` проверяет и покрытые каналы, и
явную причину для `embed`.

## 5. Rework 3 — ревью r2 (4 пункта)

| # | Было | Стало |
|---|---|---|
| 1 R17 | `preview.style.hint_text` и `excluded[].text` отдавались сырыми и рендерились | `_mask_style_view()` (`web/api/speech.py:1202`) маскирует `hint_text`, `hint_block_masked`, `excluded[].text` на границе Inspector (и для preview, и для снимка хода) |
| 2 fallback-error | primary 500 + fallback 500 = 4 HTTP-запроса, но 1 запись в журнале | `_post`/`_post_fallback` пишут КАЖДУЮ попытку; при общем провале `_record_sent_attempts(..., channel="fallback")` фиксирует все fallback-попытки со `status=error` перед `raise`. Журнал: 2 primary + 2 fallback; `last actual request` — последняя fallback-попытка. То же в `generate_chat` (review r3): primary-ветка больше не пишет только последнее тело |
| 3 `generate_chat` empty | 200 + `content:null` → исключение без записи | error-запись (`status=error`, `LLMBadResponseError`) перед `raise` |
| 4 `generate_background` invalid JSON | запись `status=ok` ДО парсинга, затем падение | запись `ok` перенесена после валидации content; все три ветки (invalid JSON / нет choices / пустой content) пишут `status=error` |

Побочно найден и исправлен дефект журнала: ключ записи использовал
`time.time_ns()`, и две одинаковые ретрай-попытки могли перезаписать друг
друга. Ключ теперь — монотонный счётчик (`itertools.count`), поэтому «все
фактические попытки» действительно видны.

Три error-probe (тесты, транспорт-двойник):

* `test_total_fallback_failure_logs_every_attempt` — 4 HTTP-попытки,
  4 записи (2 primary + 2 fallback), все `error`, `last`=fallback,
  `checksum == payload_checksum(http body)`;
* `test_generate_chat_total_failure_logs_every_attempt` — то же для
  tool-calling `generate_chat`: 4 HTTP-попытки → 4 записи (2 primary +
  2 fallback), все `error`, `last`=fallback, checksum по телу;
* `test_generate_chat_empty_content_is_logged_as_error` — 1 запись `error`;
* `test_background_invalid_json_is_not_logged_as_ok` — 1 запись `error`, не `ok`.

R17: `test_inspector_masks_style_hint_text` кладёт секрет и длинный ID в
soft-instruction стиля и проверяет, что их нет в JSON Inspector (`***`/`[id]`
на месте), структура среза сохранена.

## 6. Честные ограничения

* Журнал вызовов — in-memory, bounded (24 записи): после рестарта процесса
  снимка нет, Inspector честно говорит «только превью».
* Trace покрывает `generate`, `generate_chat`, `generate_background`,
  `generate_worker`, успешный `stream_chat_completion`. Ошибки SSE-стрима и
  эмбеддинги в журнал не пишутся — это отражено в `trace_coverage` с причиной.
* Класс «мат/регистр» не имеет второго источника правил в сборке → показывается
  как 0 найденных с явной причиной (не выдумывается).
* `preview`-checksum нельзя сравнивать с `actual`: у превью нет model/
  temperature времени реального вызова; это разные режимы, и оба подписаны.
* Предсуществующий красный тест **не связан с лейном**:
  `tests/test_soul1_composer_parity_off.py::test_p4_l1_planner_system_matches_recorded_dump`
  падает `AttributeError: 'Stub' object has no attribute '_history_partial'`
  и воспроизводится на чистом `HEAD` (worktree без изменений лейна). Причина —
  `services/direct_chat_service.py:4170` использует метод, которого нет в
  стабе теста (появился в `fb8f2ad6`, стаб не обновлён).
