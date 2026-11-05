# R-09 live proof — реальный прогон ключевых сценариев коррекции

**Кандидат:** ветка `rlr/live-proof`. Прогон выполнен на коммите
`d484ca692fb04cb533c68ab7bcd6f71cde7ee875` (в нём лежит ровно тот раннер,
которым снят артефакт: `runner_sha256 =
e621bb78b5ce206ed3c66483897f67a61ad451af2e7d710559c948dee41fea28`,
`worktree_dirty = false` — рабочее дерево на старте прогона было чистым).
Продуктовый код не менялся: раннер `tools/rlr_live_proof.py` только вызывает
существующие живые входы и наблюдает трассу.

**Артефакт с числами:** `evidence/r09/r09-live-proof.json` — 112 011 байт,
sha256 `26cfe4d4d3fb4ed0476d9eb2743bbd4c0798a7131347792ac9f62e1b0b98886e`.

> **Ни одно сообщение в Telegram не отправлено.** Транспорт подменён на самом
> последнем шаге (класс `RecordingBot` вместо aiogram `Bot`): вызов
> `bot.send_message` только записывает payload в память процесса. Сетевой
> сессии Telegram, токена бота и HTTP-запроса к Bot API в прогоне нет.
> **Живая доставка в реальный Telegram остаётся непроверенной** (нужен
> реальный чат/клиент).

---

## 0. Что исправлено после замечаний приёмки

| Замечание | Что сделано | Где проверяемо в JSON |
|---|---|---|
| s5: расхождение 417 символов, в JSON попало 200 | `text_diff` больше не обрезает: хранятся **полные** `raw_text`, `sent_text`, `normalized_raw`, `normalized_sent`, полные `removed_span`/`added_span` и **полный список** `diff_ops.ops`; добавлены `hidden_chars` и `truncated`/`truncated_ops` | `scenarios.s5.delivered.text_diff` |
| s3/s7 без `usage`/`model`/`finish_reason`/`http_calls` | `http_calls` пишутся для **всех** сценариев (захват точек отправки включён всегда); у s3 появился `correlation_id` и завершение из фактического объекта Writer'а; у s7 — `model`, `usage_total`, `finish_reasons`, `final_finish_reason`, `correlation_id` | `scenarios.s3.*`, `scenarios.s7.*` |
| Ярлык s5 `forced=128` при фактических 120 | `forced` содержит реально выставленное env-значение, фактический `max_tokens_sent` и `max_tokens` из HTTP-тел | `scenarios.s5.forced` |
| s4: утверждение про 401 не подтверждалось | В запись добавлен `fallback_leg` с **фактическими HTTP-статусами** обеих ног | `scenarios.s4.fallback_leg` → `fallback_statuses: [401, 401]` |
| s6: в отчёте «0 операций», в JSON 6 | Формулировка приведена к факту: 6 записей операций, **все** `changed=false`, ни одна не изменила текст | `scenarios.s6.ops` |

Попутно исправлены два дефекта самого артефакта, найденных при этих правках:

* **Двойной счёт вызовов в фактчеке.** Обёртки над
  `generate`/`generate_with_metadata` считали один вызов дважды (`generate`
  внутри вызывает `generate_with_metadata`). Теперь источник для s7 —
  фактические HTTP-отправки: `llm_calls_total = 2`, а не 4.
* **Терялись события путей без `turn_trace`.** Снимок фильтровался только по
  `trace_id`, поэтому у инициативы находилось 1 событие вместо 10. Теперь
  события собираются тремя фильтрами с дедупликацией, а каждое событие несёт
  `matched_by` (`trace_id` / `chat_id` / `unfiltered`) и в JSON есть сводка
  `events_by_matched_by`.

---

## 1. Предпроверка окружения (без печати секретов)

| Что | Значение |
|---|---|
| `.env` | `C:\Code\Python\adminbot\.env`, читается через `load_dotenv(..., override=False)` |
| Ключи провайдеров | заданы: `LLM_API_KEY` (44 симв.), `LLM_FALLBACK_API_KEY` (35), `EMBEDDING_API_KEY` (51), `TAVILY_API_KEY` (58), `EXA_API_KEY` (36) |
| Chat-провайдер | `nano-gpt.com`, модель `deepseek/deepseek-v4.1-flash` |
| Fallback-провайдер (.env) | `api.deepseek.com`, модель `deepseek-v4-flash` |
| TCP-доступность | `nano-gpt.com:443` — OK, `api.deepseek.com:443` — OK, `apinet.cloud:443` — OK |
| Реальный вызов модели | в каждом сценарии; у каждого вызова в JSON есть `http_status`, `usage`, `finish_reason` |
| Поиск | ключи Tavily/Exa заданы → реальный поиск (использован в s2) |

Вывод: и ключи, и сеть доступны, поэтому прогон **реальный**, а не
контролируемая фикстура. Окружение: Windows, Python 3.12.0, `LLM_TIMEOUT=40`,
`DIRECT_LONGFORM_MAX_OUTPUT_TOKENS=120` (только для s5).

---

## 2. Как снимались данные

Один прогон
`py -3 tools/rlr_live_proof.py --env-file <...>/.env --out evidence/r09 --longform-max-tokens 120`
последовательно выполнил восемь сценариев; каждый — на чистой in-memory БД
(`DatabaseService(":memory:")`) и с чистым in-memory кэшем трасс.

Живые входы:

* **s1, s2, s4, s4b, s5, s6** — настоящий `DirectChatService.handle(bot, msg, user)`;
* **s3** — настоящий `services.direct_chat_service.handle_initiative(...)`
  (`plan_initiative_decision` → `generate_initiative_reply` →
  `_style_initiative_text` → `send_text`);
* **s7** — настоящий `FactCheckService.check_claim(...)` с реальным
  `SearchAggregator`.

Трасса снималась **двумя независимыми каналами** и сверялась:

1. in-memory объект `services/turn_trace.py` (`TurnTrace`) по `correlation_id`;
2. durable события `mca_events`: `emit_mca_event(...)` → `flush_events(db)` →
   `await query_events(db, trace_id=...)` (плюс фильтры `chat_id` и без
   фильтра — БД на сценарий своя).

Плюс третий контроль, независимый от трассы: раннер оборачивает **точки
отправки** `LLMClient._post_with_key` / `_post_fallback` и пишет по каждому
фактическому HTTP-запросу `channel`, `requested_model`, `max_tokens`,
`http_status`, `response_model`, `usage`, `finish_reason`, длительность и тип
ошибки. Обёртка возвращает тот же объект ответа и пробрасывает исходное
исключение — поведение не меняется.

Классификация вызовов LLM (`planning`/`tool`/`final`/`continuation`/
`provider_retry`) берётся из `trace.llm_calls`, который наполняет
`turn_trace.note_llm_call`.

**Сравнение «написано ↔ к отправке»** считается по полным строкам:
`text_diff` содержит оба полных текста, их пунктуационно нормализованные
версии, полный список `diff_ops` (без усечения), а также `punct_only`,
`other_char_delta`, `hidden_chars`, `truncated`. `other_char_delta` — число
различающихся позиций **после** нормализации длинного тире и кавычек-«ёлочек»
(единственная наблюдённая разрешённая операция `owner_style_punctuation`).

Разрешённые операции (`turn_trace.OP_NAMES`, закрытый список из 11 имён):
`l2_scrubber`, `reasoning_marker_strip`, `machine_marker_strip`,
`lore_story_override`, `evidence_egress_guard`, `owner_style_punctuation`,
`rich_render`, `html_escape`, `plain_render`, `egress_sanitize`,
`telegram_chunk`. Любое расхождение `raw_final ≠ delivered`, не объяснённое
одной из них, трасса помечает как `unexplained_text_change`.

---

## 3. Сводка по сценариям

| # | Сценарий | LLM-вызовы | `semantic_rewrite_count` | `finish_reason` | raw (симв./digest) | to-be-sent (симв./digest) | `digest_match` | Причина расхождения |
|---|---|---|---|---|---|---|---|---|
| s1 | Direct без tools | planning 1, final 1 | 0 | `stop` | 180 / `f97142351700d488` | 180 / `9e589e39f9762ded` | false | `owner_style_punctuation` |
| s2 | Direct с веб-поиском | planning 1, tool 1, final 1 | 0 | `stop` | 250 / `047cdb18e59a9c4a` | 250 / `2fac62026baffb91` | false | `owner_style_punctuation` |
| s3 | Initiative reply | planning 1, final 1 | n/a (нет трассы, §5) | `stop` | 24 / `b7be716d149ad018` | 24 / `b7be716d149ad018` | байт-в-байт | — |
| s4 | Fallback, .env-нога | planning 1 | 0 | нет автора | 0 | 38 / `f557ccdb035e25b1` | n/a | нет авторского текста (честный путь отказа) |
| s4b | Fallback, рабочая нога | planning 1, final 1, provider_retry 2 | 0 | `stop` | 71 / `d663c566a003138a` | 71 / `2b82a2cf725afac8` | false | `owner_style_punctuation` |
| s5 | `finish_reason=length` | planning 1, final 1, continuation 2 | 0 | `length` | 728 / `674bde977fc4a9e0` | 728 / `f41c15518c5669a5` | false | `owner_style_punctuation` |
| s6 | Явная переписка + факты | planning 1, final 1 | 0 | `stop` | 86 / `60803f9add9372f4` | 86 / `60803f9add9372f4` | **true** | — |
| s7 | Структурированный фактчек | 2 факт. HTTP-вызова | n/a (иной пайплайн) | `stop`, `stop` | 1 038 симв. / `53826cc52834fe82` | возвращаемый вердикт (доставка не исполнялась) | n/a | — |

Ни в одном сценарии нет `semantic_rewrite_count > 0`, второго `final`-вызова
или операции, меняющей смысл.

---

## 4. Детали по сценариям (наблюдённое)

### s1 — Direct без tools

`correlation_id = 75b4dbe9507f421694ab366fa59e3bff`, 6.5 с.

* L1-план (реальная модель): `action=reply`, `response_act=answer`,
  `execution_mode=none`, `knowledge_origin=conversation_only`,
  `search_intent=not_applicable`, `extent=micro`,
  `preserve_source_facts=false`.
* HTTP: 3 записи — planning `max_tokens=512`, status 200, 2 531 мс; final без
  `max_tokens`, 200, 2 641 мс; третий — фоновый (memorize/rerank вне хода),
  200, 1 640 мс.
* Трасса: `llm_calls = {planning: 1, final: 1}`, `semantic_rewrite_count = 0`,
  `finish_reason = stop`, `attempt=1`, `fallback_used=false`,
  `usage = {prompt 2755, completion 63, total 2818}`,
  `model = deepseek/deepseek-v4.1-flash`, `provider = nano-gpt.com`.
* digest автора (пересчитан раннером) `f97142351700d488` **совпал** с
  `trace.raw_final_digest`; digest отправки `9e589e39f9762ded` совпал с
  `trace.delivered_digest`.
* Операции: `reasoning_marker_strip(false)`, `evidence_egress_guard(false)`,
  **`owner_style_punctuation(true)`**, `plain_render(false)`,
  `egress_sanitize(false)`, `telegram_chunk(false)`.
* Полный дифф: `raw_len = sent_len = 180`, `removed_chars = added_chars = 76`,
  `diff_ops.total_ops = 3`, `hidden_chars = 0`, `punct_only = true`,
  `other_char_delta = 0`. Все три различия — `—` → `-` и `«»` → `"`
  (позиции 59, 127, 134).
* События: 12 (4 по `trace_id`, 8 без фильтра); `direct_turn_writer`,
  `direct_turn_delivery`, `direct_turn_context`, `DIRECT_FRESH_GENERATION` —
  success.

### s2 — Direct с веб-поиском

`correlation_id = fb9ffc8d2a734dfabcbf4730b6b6d5ca`, 8.7 с.

* L1: `execution_mode=simple_tools`, `knowledge_origin=open_world`,
  `search_intent=required`.
* Поиск **реально исполнен**: `tool_rounds=1`, запись инструмента
  `execute_web_search`, `status=ok`, `out_chars=5883`, `truncated=false`.
* `llm_calls = {planning: 1, tool: 1, final: 1}`, `semantic_rewrite_count = 0`,
  `finish_reason = stop`, `usage = {4872, 83, 4955}`.
* digest автора `047cdb18e59a9c4a` = `trace.raw_final_digest`; delivered
  `2fac62026baffb91` = `trace.delivered_digest`.
* Полный дифф: `raw_len = sent_len = 250`, `removed_chars = added_chars = 69`,
  `total_ops = 4`, `hidden_chars = 0`, `punct_only = true`,
  `other_char_delta = 0`; все различия — `—` → `-`.
* События: 15 (6 по `trace_id`, 9 без фильтра), включая
  `reply_search_evidence` (search, success) и `evidence_delivery` (success).
  Есть `capability_check` с `outcome=failed` (см. §6).

### s3 — Initiative reply (реальный `handle_initiative`)

`correlation_id = r09-s3-cfcb83136a41` (передан в `handle_initiative`), 6.2 с,
`initiative_status = {status: sent, delivery_kind: initiative_reply,
action: reply, reason_codes: []}`.

* Фактические HTTP-вызовы (`http_calls`): планирование — status 200,
  `max_tokens=512`, `finish_reason=stop`, 3 172 мс; финальный Writer —
  status 200, `max_tokens=700`, `finish_reason=stop`, 2 577 мс.
* `model = deepseek/deepseek-v4.1-flash`, `provider = nano-gpt.com`,
  `finish_reason = stop`, `max_output_tokens_sent = 700`,
  `usage = {prompt 2636, completion 9, total 2645, cost 6.75e-05 USD}`;
  `completion_source = writer_completion_object` (трассы хода у инициативы нет,
  поэтому завершение берётся из фактического объекта).
* `llm_calls_by_class = {planning: 1, final: 1}`.
* Текст автора: `Привет! Как день прошёл?` (24 симв.) — передан в транспорт
  **байт-в-байт**: `written_equals_sent = true`, `raw_len = sent_len = 24`,
  `punct_only = true`, `other_char_delta = 0`, ни одной записи `note_op`.
* Про `raw_final.digest_agrees = false` у s3: это **не расхождение**, а
  отсутствие второго источника — `digest_trace = null`, потому что
  `handle_initiative` не открывает `turn_trace`. Сравнивать digest раннера
  не с чем; равенство с отправленным текстом проверено напрямую
  (`written_equals_sent = true`, одинаковые digest `b7be716d149ad018`).
* События: 10, `events_by_matched_by = {trace_id: 1, unfiltered: 9}` — то есть
  correlation хода несёт только `initiative_decided`, остальные
  (`initiative_writer_generated`, `speech_extent`, `evidence_egress_check`,
  `initiative_delivery_manifest`, `bot_output_recorded` …) находятся без
  фильтра по трассе. Это и есть причина, по которой снимок собирает события
  тремя фильтрами (§0).

### s4 — Provider fallback, «как в бою» (.env-нога)

`correlation_id = e096595f027f42c7995881c5f464c082`, 12.3 с.

* Принуждение: невалидный primary (`http://127.0.0.1:9/v1`, `max_retries=0`),
  вторая нога — из `.env` (`api.deepseek.com`).
* `fallback_leg`: `primary_attempts = 2`,
  `primary_errors = [LLMTransportError, LLMTransportError]`,
  **`fallback_attempts = 2`, `fallback_statuses = [401, 401]`** — вторая нога
  отвечает 401 (ключ неавторизован на этом хосте). Это факт из JSON, а не
  пересказ лога.
* Итог: автора нет (`raw_len = 0`), доставлен текст существующего пула ошибок
  (`direct_turn_writer: skipped`, `direct_turn_delivery: skipped`,
  `outcome = skipped`, в transport ушло 38 симв.: «мои мозги расплавились от
  твоего бреда»). Это **честный путь отказа**: расхождение
  (`other_char_delta = 38`) не объясняется операцией, потому что авторского
  текста в ходе не было вовсе.
* Механизм fallback при этом реально задействован (две настоящие ноги,
  настоящие HTTP-статусы). Работоспособность второй ноги проверена в s4b,
  потому что 401 — состояние ключа в `.env`, а не дефект кода.

### s4b — Provider fallback с рабочей второй ногой

`correlation_id = 67f3a97a22a241c8a577fac68adcdb45`, 9.7 с.

* Принуждение то же (невалидный primary), вторая нога настроена на рабочий
  провайдер (`LLM_BASE_URL`/`LLM_MODEL_NAME`/`LLM_API_KEY`) — клиент
  конструируется раннером, продуктовые файлы не тронуты.
* `fallback_leg`: `primary_attempts = 3` (все `LLMTransportError`),
  `fallback_statuses = [200, 200, 200]`.
* Трасса: `attempt=2`, `fallback_used=true`, `provider=nano-gpt.com`,
  `llm_calls = {planning: 1, final: 1, provider_retry: 2}`,
  `semantic_rewrite_count = 0`, `finish_reason = stop`,
  `usage = {2727, 23, 2750}`.
* Автор 71 симв. / `d663c566a003138a` = `trace.raw_final_digest`; к отправке
  71 / `2b82a2cf725afac8`; `removed_chars = added_chars = 1`,
  `total_ops = 1` (`—` → `-`), `punct_only = true`, `other_char_delta = 0`.
* Вывод: провайдерский fallback **не создаёт второй авторской генерации** —
  финальный смысловой текст один, ретрай виден отдельным классом
  `provider_retry`.

### s5 — Длинный ответ с `finish_reason=length`

`correlation_id = bcc1122f3cda4e3b887ae56c1d6677dc`, 13.4 с, запрос:
«Напиши развёрнутый рассказ примерно на 90 слов…».

* Принуждение (проверяемо в `forced`):
  `env_DIRECT_LONGFORM_MAX_OUTPUT_TOKENS = 120`,
  **`max_tokens_sent = 120`**,
  `max_tokens_in_http_calls = [512, 120, 120, 120, null]` — потолок реально
  уходит в тело (явная форма «развёрнутый» включает longform-слот, при этом
  семантическое поле L1 остаётся `extent=normal`).
* Первый авторский вызов: `finish_reason = length` (`is_truncated=true`,
  `completion_tokens = 120` — ровно потолок), status 200.
* Продолжение: **`llm_calls.continuation = 2`**, `continuation_calls = 2`,
  `continuation_stop_reason = completed`, событие `llm_continuation`
  (stage `l2_continuation`, outcome success). В HTTP это видно как два
  вызова с `max_tokens=120` и `finish_reason=length`, затем один с
  `finish_reason=stop`.
* Итог: 728 симв., `raw_final_digest = 674bde977fc4a9e0` (совпал с
  `trace.raw_final_digest`). Хвост: `…С тех пор проверяю карманы дважды: один
  раз наяву, второй — на всякий случай, в чате.` — текст заканчивается
  **целым словом и целым предложением**, обрыва нет.
* Полный дифф (без усечения): `raw_len = sent_len = 728`,
  `removed_chars = added_chars = 644`, **`diff_ops.total_ops = 16`**,
  `diff_ops.truncated_ops = false`, `hidden_chars = 0`,
  `punct_only = true`, **`other_char_delta = 0`** — на **полном** тексте
  различаются только 7 длинных тире и 9 кавычек-«ёлочек» (полный список с
  индексами — в `diff_ops.ops`).
* К отправке 728 симв. / `f41c15518c5669a5` = `trace.delivered_digest`,
  доставка `success`.
* Граница контракта: continuation ограничен `MAX_CONTINUATION_CALLS=2`. При
  заведомо недостаточном лимите (прогоны с `max_tokens` 90/200/320/500 на
  более длинных запросах) корректным исходом был **честный отказ**
  `unfinished_answer` (`note_l2_refusal`, `text_source=none`) — обрезанный
  текст в чат не уходил.

### s6 — Явная переписка/перевод с защищаемыми фактами

`correlation_id = ec9a76cc6a804de1899e9a8e9d1113c1`, 5.8 с, запрос:
переписать текст «Вчера в 19:40 … поезд № 42 … 3 500 рублей … в 06:15».

* **Реальная модель сама выставила** `preserve_source_facts = true` в L1-плане
  (поле читается раннером из фактически полученного плана; канон
  `preserve_source_facts` есть в `prompts.direct_l1_planner_system_prompt`).
* `llm_calls = {planning: 1, final: 1}`, `semantic_rewrite_count = 0`,
  `finish_reason = stop`, `usage = {2684, 42, 2726}`.
* Результат: `Вчера в 19:40 я взял билет до Кеми на поезд № 42, отдал
  3 500 рублей и прибыл в 06:15.` — все защищаемые факты (19:40, № 42,
  3 500, 06:15, Кемь) на месте, изложение переписано.
* **Операции: 6 записей** — `reasoning_marker_strip`, `evidence_egress_guard`,
  `owner_style_punctuation`, `plain_render`, `egress_sanitize`,
  `telegram_chunk`, и у всех **`changed = false`**. То есть запись операций
  есть, но ни одна текст не изменила (в прошлой редакции отчёта было неверно
  сказано «0 операций»).
* Проверяемо: `written_equals_sent = true`, `digest_match = true`,
  `raw_len = sent_len = 86`, оба digest `60803f9add9372f4`, `diff_ops` пуст.

### s7 — Структурированный фактчек

20.7 с, `FactCheckService.check_claim` с реальным `SearchAggregator`.

* **2 фактических HTTP-вызова** (`llm_calls_total = 2`): оба status 200,
  `finish_reason = stop`, usage 4 441 и 3 404 токена; суммарно
  `usage_total = {prompt 6556, completion 1289, total 7845}`,
  `model = deepseek/deepseek-v4.1-flash`, `finish_reasons = [stop, stop]`.
  (В прошлой редакции стояло «4 вызова» — это был двойной счёт из-за обёртки
  `generate` → `generate_with_metadata`; исправлено, см. §0.)
* `correlation_id = null` и это зафиксировано полем `correlation_id_note`:
  `check_claim` не принимает `correlation_id` и не открывает `turn_trace`,
  поэтому идентификатора хода у этого пути нет.
* Результат: 1 038 симв. / digest `53826cc52834fe82`. Содержательно проверен
  числовой/датный сдвиг: заявленные «рост 12% за сутки» и «$104 500 сегодня»
  не подтверждены (суточный прирост ≈3%, цена доходила до района $104 000),
  указан источник.
* Путь сохраняет свой узкий контроль данных и **не** переиспользует Direct L2
  (поэтому `semantic_rewrite_count`/`turn_trace` к нему не применимы).
* Событий в `mca_events` этот путь в харнессе не оставил (`events = []`) —
  см. §5.

---

## 5. Что именно утверждается и что нет

Утверждается по этому кандидату и этому прогону:

1. Содержательный ответ Direct получает **ровно один** финальный смысловой
   вызов модели: `llm_calls.final = 1` в s1, s2, s4b, s5, s6; у инициативы —
   `final = 1` по фактическому завершению Writer'а;
   `semantic_rewrite_count = 0` везде, где трасса хода существует.
2. Все различия между текстом автора и текстом, переданным в транспорт,
   объясняются **закрытым списком** разрешённых операций. Единственная
   меняющая операция в прогоне — `owner_style_punctuation`; посимвольная
   проверка на **полных** строках дала `other_char_delta = 0` и
   `hidden_chars = 0` для s1, s2, s4b, s5, s6.
3. `finish_reason=length` приводит к продолжению **того же автора**
   (`continuation=2`, `completed=true`) с целым словом на конце, а при
   невозможности — к честному отказу без обрезка.
4. Провайдерский fallback (s4b) отдаёт текст той же единственной финальной
   стадии; ретрай виден отдельным классом `provider_retry=2`, а не вторым
   `final`. Отказ второй ноги (s4) показывает фактические 401.
5. Явная переписка (s6) реально помечается моделью `preserve_source_facts=true`
   и сохраняет все защищаемые факты; ни одна операция текст не изменила.
6. Инициативный текст (s3) уходит в транспорт байт-в-байт.

Не утверждается:

* **Живая доставка в Telegram не проверена** — транспорт подменён; ни одного
  сетевого вызова Bot API в прогоне не было. Проверено только то, что
  подготовлено к отправке и передано в `bot.send_message`.
* Реальный Telegram-частинг (`telegram_chunk`) записан как операция без
  изменения digest'а, но фактическая нарезка на сообщения >4096 символов в
  этом прогоне не возникала (все ответы короче лимита).
* Инициатива **не имеет `turn_trace`**: `handle_initiative` не вызывает
  `turn_trace.begin`, поэтому для неё нет `direct_turn_writer`/
  `direct_turn_delivery` и `semantic_rewrite_count`, а её события почти не
  несут correlation хода (`events_by_matched_by = {trace_id: 1,
  unfiltered: 9}`). Соответственно у s3 `raw_final.digest_agrees = false` — это
  «нет второго источника» (`digest_trace = null`), а не расхождение текста;
  проверяемая замена — `completion` из фактического объекта
  (`completion_source = writer_completion_object`), `http_calls`, байтовое
  равенство текста и события `initiative_*`.
* Фактчек-путь не оставляет событий в `mca_events` в этом харнессе
  (`events = []` у s7 при 2 фактических HTTP-вызовах и полученном вердикте).

---

## 6. Побочные находки (не блокеры R-09)

| Находка | Класс | Влияние |
|---|---|---|
| `handle_initiative` не вызывает `turn_trace.begin`; correlation хода несут 1 событие из 10 | related-nonblocking | Наблюдаемость инициативы держится на `initiative_*` событиях и фактическом объекте завершения. Если RLR-06 задуман только для Direct — норма; если для всех триггеров — пробел в покрытии |
| `LLM_FALLBACK_API_KEY` из `.env` даёт **401** на `api.deepseek.com` (s4: `fallback_statuses = [401, 401]`) | unrelated/pre-existing (окружение) | Штатный fallback в бою сейчас не спасёт от отказа primary. Не дефект кода; требует внимания владельца/DevOps по ключу |
| В s2 событие `capability_check` с `outcome=failed` | related-nonblocking | На доставку не повлияло: поиск исполнен (`status=ok`, 5 883 симв.), ответ доставлен |
| В s1 и s6 событие `speech_extent` (`direct_pre_send`) с `outcome=failed` | related-nonblocking | Деградации нет: s1 отличается только пунктуацией, s6 ушёл байт-в-байт. «failed» на успешном ходе вводит в заблуждение — стоит разобрать отдельно. Наблюдение плавающее (в части прогонов `success`) |
| Запись инструмента поиска: `out_chars=5883`, но `refs=0` | related-nonblocking | Выдача пришла текстом без структурных ссылок; на R-09 не влияет |
| Длина ответа модели нестабильна (запрос «~90 слов» → 728…2 700 симв.) | context | Влияет только на подбор `max_tokens` для демонстрации continuation |

---

## 7. Воспроизведение

```
py -3 tools/rlr_live_proof.py \
  --env-file C:\Code\Python\adminbot\.env \
  --out plans/features/remove-legacy-rephrasing/evidence/r09 \
  --longform-max-tokens 120 \
  --log-file <run-dir>/live.log
```

Раннер ничего не отправляет в Telegram и не меняет продуктовый код; все
наблюдатели — обёртки над `turn_trace` и точками отправки `LLMClient`.
Отдельные сценарии: `--only s5`, `--only s2,s7`.
В `meta` артефакта фиксируются `commit`, `runner_sha256` и `worktree_dirty`,
поэтому видно, каким именно кодом снят прогон.

**Пересчёт без повторного прогона** (то, что делает приёмка):

```
py -3 tools/rlr_r09_verify.py \
  --out <run-dir>/verify.txt
```

Скрипт читает только JSON и заново считает `other_char_delta`/`punct_only` по
полным текстам, проверяет отсутствие скрытых символов diff'а, полноту
diff-списка s5, соответствие `forced` фактически отправленному `max_tokens`,
обязательные поля s3/s7, равенство счётчика вызовов s7 фактическим HTTP-
отправкам, фактические 401 у s4 и шесть неизменяющих операций у s6.
На этом артефакте: **50/50 PASS**.

**Приватность артефакта.** В JSON лежат полные тексты автора и отправки
(`text_diff.raw_text` / `sent_text`) — это ответы модели, сгенерированные для
самого прогона; пользовательская переписка в артефакт не попадает. Полные
тексты нужны именно для того, чтобы приёмка пересчитала
`other_char_delta`/`punct_only` на всей строке, а не по усечённому фрагменту.
