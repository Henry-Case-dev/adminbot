# R-09 live proof — реальный прогон ключевых сценариев коррекции

**Кандидат:** ветка `rlr/live-proof`, коммит `71c3d95ad0c6d268b1a1dfdc13e2665033f2b670`
(`HEAD` = merge RLR-06). Продуктовый код в этом прогоне **не менялся**: раннер
`tools/rlr_live_proof.py` только вызывает существующие живые входы и наблюдает
трассу.

**Артефакт с числами:** `evidence/r09/r09-live-proof.json` (60 165 байт,
sha256 `23114ab39dfd4ed2552aacde97fb62f97f8f4468a704e078689b92c912b7454b`).

> **Ни одно сообщение в Telegram не отправлено.** Транспорт подменён на самом
> последнем шаге (класс `RecordingBot` вместо aiogram `Bot`): вызов
> `bot.send_message` только записывает payload в память процесса. Сетевой
> сессии Telegram, токена бота и HTTP-запроса к Bot API в прогоне нет.
> **Живая доставка в реальный Telegram остаётся непроверенной** (нужен
> реальный чат/клиент).

---

## 1. Предпроверка окружения (без печати секретов)

| Что | Значение |
|---|---|
| `.env` | `C:\Code\Python\adminbot\.env`, читается через `load_dotenv(..., override=False)` |
| Ключи провайдеров | заданы: `LLM_API_KEY` (44 симв.), `LLM_FALLBACK_API_KEY` (35), `EMBEDDING_API_KEY` (51), `TAVILY_API_KEY` (58), `EXA_API_KEY` (36) |
| Chat-провайдер | `nano-gpt.com`, модель `deepseek/deepseek-v4.1-flash` |
| Fallback-провайдер (.env) | `api.deepseek.com`, модель `deepseek-v4-flash` |
| TCP-доступность | `nano-gpt.com:443` — OK, `api.deepseek.com:443` — OK, `apinet.cloud:443` — OK |
| Реальный вызов модели | выполнен в каждом сценарии; ответы HTTP 200 с usage |
| Поиск | ключи Tavily/Exa заданы → реальный поиск возможен (использован в s2) |

Вывод предпроверки: и ключи, и сеть доступны, поэтому прогон **реальный**, а не
контролируемая фикстура. Фикстуры-двойники (R-09.1 «дополненный controlled
fixtures для отказов при недоступности провайдера») не понадобились.

Окружение прогона: Windows, Python 3.12.0, `LLM_TIMEOUT=40`,
`DIRECT_LONGFORM_MAX_OUTPUT_TOKENS=120` (только для s5, см. ниже).

---

## 2. Как снимались данные

Один прогон `py -3 tools/rlr_live_proof.py --env-file <...>/.env --out evidence/r09 --longform-max-tokens 120`
последовательно выполнил восемь сценариев; каждый — на чистой in-memory БД
(`DatabaseService(":memory:")`), с чистым in-memory кэшем трасс.

Живые входы:

* **s1, s2, s4, s4b, s5, s6** — настоящий `DirectChatService.handle(bot, msg, user)`;
* **s3** — настоящий `services.direct_chat_service.handle_initiative(...)`
  (решение по кандидату → `plan_initiative_decision` → `generate_initiative_reply`
  → `_style_initiative_text` → `send_text`);
* **s7** — настоящий `FactCheckService.check_claim(...)` с реальным
  `SearchAggregator`.

Трасса снималась **двумя независимыми каналами** и сверялась:

1. in-memory объект `services/turn_trace.py` (`TurnTrace`) по `correlation_id`;
2. durable события `mca_events`: `emit_mca_event(...)` → `flush_events(db)` →
   `await query_events(db, trace_id=...)` (in-memory SQLite, схема v15).

Плюс третий, независимый от трассы контроль: раннер сам оборачивал **точки
отправки** `LLMClient._post_with_key` / `_post_fallback` и записывал фактические
HTTP-вызовы провайдера (канал, `max_tokens`, длительность, ошибка), а также сам
считал `blake2s-8` digest'ы по реальному тексту автора и по реально
переданному в транспорт тексту. Классификация вызовов LLM
(`planning`/`tool`/`final`/`continuation`/`provider_retry`) берётся из
`trace.llm_calls`, который наполняет `turn_trace.note_llm_call`.

Разрешённые операции (`turn_trace.OP_NAMES`, закрытый список из 11 имён):
`l2_scrubber`, `reasoning_marker_strip`, `machine_marker_strip`,
`lore_story_override`, `evidence_egress_guard`, `owner_style_punctuation`,
`rich_render`, `html_escape`, `plain_render`, `egress_sanitize`,
`telegram_chunk`. Любое расхождение `raw_final ≠ delivered`, не объяснённое
одной из них, трасса помечает как `unexplained_text_change`.

---

## 3. Сводка по сценариям

| # | Сценарий | Запущен | LLM-вызовы | `semantic_rewrite_count` | `finish_reason` | raw (симв./digest) | to-be-sent (симв./digest) | `digest_match` | Причина расхождения |
|---|---|---|---|---|---|---|---|---|---|
| s1 | Direct без tools | да | planning 1, final 1 | 0 | `stop` | 219 / `3f1eefebb9a0c4b0` | 219 / `83c849fd5f3d865b` | false | `owner_style_punctuation` |
| s2 | Direct с веб-поиском | да | planning 1, tool 1, final 1 | 0 | `stop` | 204 / `068366f6ae123155` | 204 / `41ef59b50663222f` | false | `owner_style_punctuation` |
| s3 | Initiative reply | да | planning 1, final 1 | n/a (нет трассы, §5) | n/a | 16 / `28fa4e152571b267` | 16 / `28fa4e152571b267` | равно байт-в-байт | — |
| s4 | Fallback при невалидном primary (.env-нога) | да | planning 1 | 0 | нет автора | 0 | 38 / `f557ccdb035e25b1` | n/a | нет авторского текста (честный путь ошибки) |
| s4b | Fallback при невалидном primary (рабочая нога) | да | planning 1, final 1, provider_retry 2 | 0 | `stop` | 78 / `ec6b1a3d29c0b44c` | 78 / `6b8e09c56ff6c74c` | false | `owner_style_punctuation` |
| s5 | Длинный ответ, `finish_reason=length` | да | planning 1, final 1, continuation 1 | 0 | `length` | 585 / `3446ef574b158718` | 585 / `9121a0555f2146f0` | false | `owner_style_punctuation` |
| s6 | Явная переписка с защищаемыми фактами | да | planning 1, final 1 | 0 | `stop` | 103 / `b4f00c5f0bde22ea` | 103 / `b4f00c5f0bde22ea` | **true** | — |
| s7 | Структурированный фактчек | да | 4 вызова (свой пайплайн) | n/a (иной пайплайн) | n/a | 633 симв. / `3d7e5cce8567d2a1` | возвращаемый вердикт (доставка не исполнялась) | n/a | — |

Ни в одном сценарии не появилось `semantic_rewrite_count > 0`, второго
`final`-вызова или операции, меняющей смысл.

---

## 4. Детали по сценариям (наблюдённое)

### s1 — Direct без tools

`correlation_id = 90b994cba71e49548edf2c316d00cd67`, 6.0 с.

* L1-план (реальная модель): `action=reply`, `response_act=answer`,
  `execution_mode=none`, `knowledge_origin=conversation_only`,
  `search_intent=not_applicable`, `extent=compact`.
* Фактические HTTP-вызовы: `planning` (`max_tokens=512`, 2 657 мс),
  `final` (`max_tokens` не отправлялся, 2 030 мс), третий вызов — фоновый
  (memorize/rerank, 1 000 мс, вне хода).
* Трасса: `llm_calls = {planning: 1, final: 1}`, `semantic_rewrite_count = 0`,
  `finish_reason = stop`, `attempt=1`, `fallback_used=false`,
  `usage.completion_tokens=73`.
* digest автора (пересчитан раннером) `3f1eefebb9a0c4b0` **совпал** с
  `trace.raw_final_digest`.
* Операции: `reasoning_marker_strip(false)`, `evidence_egress_guard(false)`,
  **`owner_style_punctuation(true)`**, `plain_render(false)`,
  `egress_sanitize(false)`, `telegram_chunk(false)`.
* Сравнение «написано ↔ к отправке»: `punct_only = true`,
  `other_char_delta = 0` — единственное отличие внутри 160-символьного
  участка это длинное тире вместо дефиса; после нормализации строки
  совпадают посимвольно. Пример: автор `…в такую рань — вот это…` →
  к отправке `…в такую рань - вот это…`.
* Доставка: `outcome=success`, 1 сообщение, digest доставки в трассе совпал с
  пересчитанным раннером.

### s2 — Direct с веб-поиском

`correlation_id = cb2868292e1545cd811dd336f901c410`, 7.2 с.

* L1: `execution_mode=simple_tools`, `knowledge_origin=open_world`,
  `search_intent=required`.
* Поиск **реально исполнен**: `tool_rounds=1`, запись инструмента
  `execute_web_search`, `status=ok`, `out_chars=6857`, `truncated=false`.
* `llm_calls = {planning: 1, tool: 1, final: 1}`, `semantic_rewrite_count = 0`,
  `finish_reason=stop`.
* digest автора `068366f6ae123155` = `trace.raw_final_digest`; delivered
  `41ef59b50663222f`.
* Операции те же 6; меняет только `owner_style_punctuation(true)`
  (`punct_only=true`, `other_char_delta=0`).
* События: `reply_search_evidence` (search, success), `direct_turn_context`,
  `direct_turn_writer`, `direct_turn_delivery` — все success.
  Дополнительно присутствует событие `capability_check` c `outcome=failed`
  (см. §6, побочная находка, на доставку не влияет).

### s3 — Initiative reply (реальный `handle_initiative`)

4.3 с, `initiative_status = {status: sent, delivery_kind: initiative_reply,
action: reply, reason_codes: []}`.

* L1-решение инициировано кандидатом `trigger:intent_due:2934a3a63b0d0be0`;
  Writer — существующий Direct L2 (`generate_initiative_reply`), затем
  `_style_initiative_text`.
* Фактические вызовы модели: `planning` (`max_tokens=512`) и `final`
  (`max_tokens=700`).
* Текст автора: `Как день прошёл?` (16 симв.) — передан в транспорт
  **байт-в-байт** (`written_equals_sent = true`, `punct_only = true`,
  `other_char_delta = 0`, ни одной записи `note_op`).
* События инициативы: `initiative_decided`, `initiative_writer_generated`,
  `speech_extent`, `evidence_egress_check`, `evidence_policy_decided`,
  `initiative_delivery_manifest`, `bot_output_recorded` — все success.

### s4 — Provider fallback, «как в бою» (.env-нога)

`correlation_id = c37694947d294740aa01084125de94c0`, 12.4 с.

* Принуждение: в клиенте задан невалидный primary (`http://127.0.0.1:9/v1`,
  `max_retries=0`), вторая нога — из `.env` (`api.deepseek.com`).
* Фактический трейс: `primary → LLMTransportError` (2 218 мс), затем
  `fallback` (1 265 мс) — и **ногá fallback вернула `status=401`**
  (ключ `LLM_FALLBACK_API_KEY` неавторизован на этом хосте). Вторая пара
  вызовов повторила то же для L2.
* Итог: автора нет (`raw_final` пуст), доставлен текст существующего пула
  ошибок (`direct_turn_writer: skipped`, `delivery: skipped`,
  `outcome=skipped`). Это **честный путь отказа**, а не переписывание:
  расхождение не объясняется операцией, потому что объяснять нечего —
  авторского текста в ходе не было.
* Механизм fallback при этом реально задействован (две настоящие ноги,
  `LLM fallback attempt` в логе). Успешность самой второй ноги проверена
  отдельно в s4b, потому что 401 — состояние ключа в `.env`, а не дефект кода.

### s4b — Provider fallback с рабочей второй ногой

`correlation_id = 73439e4053c84b9a9b76ca5634f8e870`, 9.6 с.

* Принуждение то же (невалидный primary), но вторая нога настроена на рабочий
  провайдер (`LLM_BASE_URL` / `LLM_MODEL_NAME` / `LLM_API_KEY`) — клиент
  конструируется раннером, продуктовые файлы не тронуты.
* Фактические вызовы: `primary → LLMTransportError` (2 188 мс) →
  `fallback` 3 952 мс (успех), и то же для финальной стадии
  (2 031 мс / 1 391 мс), плюс фоновый вызов (889 мс).
* Трасса: `attempt=2`, `fallback_used=true`, `provider=nano-gpt.com`,
  `llm_calls = {planning: 1, final: 1, provider_retry: 2}`,
  `semantic_rewrite_count = 0`, `finish_reason = stop`.
* Автор `78 симв.` digest `ec6b1a3d29c0b44c` = `trace.raw_final_digest`;
  к отправке `6b8e09c56ff6c74c`; `punct_only=true`, `other_char_delta=0`
  (единственное отличие — `—` → `-`).
* Вывод: **провайдерский fallback не создаёт второй авторской генерации** —
  финальный смысловой текст один, ретрай виден отдельным классом
  `provider_retry`.

### s5 — Длинный ответ с `finish_reason=length`

`correlation_id = 29a60c49a75c41569d7f957153299854`, 8.0 с, запрос:
«Напиши развёрнутый рассказ примерно на 90 слов…».

* Принуждение: `DIRECT_LONGFORM_MAX_OUTPUT_TOKENS=120` → явная форма
  пользователя («развёрнутый») через `explicit_form_override` даёт effective
  longform, и в тело запроса реально уходит `max_tokens=120`
  (`completion.max_output_tokens_sent=120`).
* Первый авторский вызов: `finish_reason = length` (`is_truncated=true`,
  `completion_tokens=120` — ровно потолок).
* Продолжение: **`llm_calls.continuation = 1`**, `continuation_calls=1`,
  `continuation_stop_reason = completed`, `completed = true`; событие
  `llm_continuation` (stage `l2_continuation`, outcome success).
* Итог: 585 символов, `raw_final_digest = 3446ef574b158718` (совпал с
  пересчитанным раннером). Хвост: `…Вася, кстати, до сих пор уверен, что это
  он их тогда нашёл.` — текст заканчивается **целым словом и целым
  предложением**, обрыва нет.
* К отправке 585 символов, digest `9121a0555f2146f0`, `punct_only=true`,
  `other_char_delta=0`. Кавычки `«привет»` → `"привет"`, `—` → `-`; ни одного
  изменённого слова.
* Важное наблюдение по границам: continuation ограничен
  `MAX_CONTINUATION_CALLS=2`. При заведомо недостаточном лимите (прогоны с
  `max_tokens=90`, `200`, `320`, `500` на более длинных запросах) корректным
  исходом был **честный отказ** `unfinished_answer` (`note_l2_refusal`,
  `text_source=none`) — обрезанный текст в чат не уходил. То есть
  «недописанный ответ» не маскируется под готовый и не обрезается по слову.

### s6 — Явная переписка/перевод с защищаемыми фактами

`correlation_id = d31796cf5ee84eae864c13c1dd2a6221`, 4.0 с, запрос: переписать
текст «Вчера в 19:40 … поезд № 42 … 3 500 рублей … в 06:15».

* **Реальная модель сама выставила** `preserve_source_facts = true` в L1-плане
  (поле читается раннером из фактически полученного плана; канон
  `preserve_source_facts` присутствует в `prompts.direct_l1_planner_system_prompt`,
  ревизия `fac:2354a5cc57c4(l1-planner-source-facts)`).
* Узкий контракт трансформации применён: `_explicit_transform_contract` +
  `protected_facts_mismatch` — в `completion.checks` неисправностей нет.
* Результат: `Вчера в 19:40 я взял билет на поезд № 42 до станции Кемь,
  заплатив 3 500 рублей, и прибыл туда в 06:15.` — **все** защищаемые факты
  (19:40, № 42, 3 500, 06:15, Кемь) на месте, порядок изложения переписан.
* `llm_calls = {planning: 1, final: 1}`, `semantic_rewrite_count = 0`,
  `finish_reason = stop`.
* Показательно: здесь `digest_match = true`, `written_equals_sent = true`,
  `punct_only = true` — **ни одной операции вообще** (`note_op` не вызывался:
  `owner_style_punctuation(false)`), текст ушёл байт-в-байт.
* Пары «черновик tool-final → JSON → Verbalizer» в ходе не возникло: одна
  финальная авторская генерация.

### s7 — Структурированный фактчек

10.4–16.2 с за прогон, `FactCheckService.check_claim` с реальным `SearchAggregator`.

* `llm_calls_total = 4` (свой двухступенчатый пайплайн фактчека: аналитик →
  вербализатор), `result_chars = 633`, digest результата
  `3d7e5cce8567d2a1`.
* Содержательно проверен числовой/датный сдвиг: заявленное «рост 12% и
  $104 500 сегодня» отклонено, текущие котировки из выдачи ($77 000–$81 500)
  отделены от майского максимума $104 500. Хвост вердикта: `…Ниже — только
  результат структурной проверки.`
* Путь сохраняет свой узкий контроль данных и **не** переиспользует Direct L2
  (поэтому `semantic_rewrite_count`/`turn_trace` к нему не применимы).
* Наблюдение: запрос `mca_events.query_events(db, chat_id=...)` после прогона
  не вернул событий фактчека, хотя вердикт получен — фактчек-путь эмитит свою
  телеметрию иначе, чем `direct_turn_*`. Для R-09 это не блокер (требование
  про трассу одного хода относится к Direct/инициативе), но при желании
  наблюдаемости фактчека это отдельная задача.

---

## 5. Что именно утверждается и что нет

Утверждается по этому кандидату и этому прогону:

1. Содержательный ответ Direct получает **ровно один** финальный смысловой
   вызов модели: `llm_calls.final = 1` во всех сценариях s1, s2, s4b, s5, s6;
   `semantic_rewrite_count = 0` везде, где трасса хода существует.
2. Все различия между текстом автора и текстом, переданным в транспорт,
   объясняются **закрытым списком** разрешённых операций. Единственная
   меняющая операция в прогоне — `owner_style_punctuation`; посимвольная
   проверка (`punct_only`) дала `other_char_delta = 0` для s1, s2, s4b, s5,
   s6, то есть после нормализации длинного тире и кавычек-«ёлочек» строки
   совпадают полностью.
3. `finish_reason=length` приводит к продолжению **того же автора**
   (`continuation=1`, `completed=true`) с целым словом на конце, а при
   невозможности — к честному отказу без обрезка.
4. Провайдерский fallback (s4b) отдаёт текст той же единственной финальной
   стадии; ретрай виден отдельным классом `provider_retry=2`, а не вторым
   `final`.
5. Явная переписка (s6) реально помечается моделью `preserve_source_facts=true`
   и сохраняет все защищаемые факты без единой доставочной операции.
6. Инициативный текст (s3) уходит в транспорт байт-в-байт.

Не утверждается:

* **Живая доставка в Telegram не проверена** — транспорт подменён; ни одного
  сетевого вызова Bot API в прогоне не было. Проверено только то, что
  подготовлено к отправке и передано в `bot.send_message`.
* Реальный Telegram-частинг (`telegram_chunk`) записан как операция без
  изменения digest'а, но фактическая нарезка на сообщения >4096 символов в
  этом прогоне не возникала (все ответы короче лимита).
* Инициатива не имеет `turn_trace` (см. §6): для неё нет ни
  `direct_turn_writer`/`direct_turn_delivery`, ни `semantic_rewrite_count`.
  Её наблюдаемость в этом прогоне — существующие события `initiative_*` плюс
  независимый захват текста автора и текста к отправке.
* Фактчек-путь не оставляет событий в `mca_events` в этом харнессе.

---

## 6. Побочные находки (не блокеры R-09)

| Находка | Класс | Влияние |
|---|---|---|
| `handle_initiative` не вызывает `turn_trace.begin` → у инициативы нет трассы хода; `note_l2_*` для неё раннее завершение | related-nonblocking | Наблюдаемость инициативы остаётся на `initiative_*` событиях. Если RLR-06 задуман только для Direct — это норма; если для всех триггеров — дырка в покрытии |
| `LLM_FALLBACK_API_KEY` из `.env` даёт `401` на `api.deepseek.com` | unrelated/pre-existing (окружение) | Штатный fallback в бою сейчас не спасёт от отказа primary. Не дефект кода; требует внимания владельца/DevOps по ключу |
| В s2 событие `capability_check` с `outcome=failed` | related-nonblocking | На доставку не повлияло: поиск исполнен, ответ доставлен. Стоит отдельного разбора телеметрии |
| Запись инструмента поиска: `out_chars=6857`, но `refs=0` | related-nonblocking | Выдача пришла текстом без структурных ссылок; на R-09 не влияет |
| Длина ответа модели сильно нестабильна (90 слов → 585…2696 символов) | context | Влияет только на подбор `max_tokens` для демонстрации continuation |

---

## 7. Воспроизведение

```
# 1) предпроверка (ключи/сеть), без печати секретов — см. §1
# 2) прогон
py -3 tools/rlr_live_proof.py \
  --env-file C:\Code\Python\adminbot\.env \
  --out plans/features/remove-legacy-rephrasing/evidence/r09 \
  --longform-max-tokens 120 \
  --log-file <run-dir>/live.log
```

Раннер ничего не отправляет в Telegram и не меняет продуктовый код; все
наблюдатели — обёртки над `turn_trace` и точками отправки `LLMClient`.
Тексты чата в артефакт не пишутся целиком: только digest'ы, длины, короткие
фрагменты (≤300 символов) и результат посимвольной проверки.

Сценарии можно запускать по отдельности: `--only s5`, `--only s2,s7`.
