# UR-F шаг 2 — API-проекция durable-событий хода

База: `c9ef6e72` (шаг 1 принят), ветка `ur/f-inspector-step1`.
Контракт: `ur-f-inspector-contract.md` §4–5; данные — `ur-f-step1-delivery-snapshot.md`.
Внешние источники не использовались (внутренняя проекция существующих событий).

## Что изменено

| файл | дельта |
|---|---|
| `web/api/routes.py` | `_turn_chain_view` + проекторы секций + `include_text` в существующем endpoint'е. Δ эндпоинтов = 0. Схемная allowlist-проекция ВСЕХ секций, включая вложенные (см. «Схема ответа»). |
| `services/turn_trace.py` | `context_payload()` теперь сериализует уже собранные `clock_timezone`/`clock_as_of_utc`/`clock_config_version`/`clock_timezone_source` (см. «Найденный дефект»). |
| `tests/test_ur_f_inspector_step2.py` | 15 тестов на реальном HTTP + реальных строках SQLite. |

DDL = 0, миграций и backfill нет.

## Схема ответа: единственный путь значения (корень, не поле)

Значения в ответ идут ТОЛЬКО через `_turn_project(spec, value)`: объявленный
ключ + объявленный тип, иначе `null`/отсутствие. Никакой вложенный объект не
копируется «как есть» — это и был корень утечек: плоская allowlist не видела
`context.l1`, `tools[]`, `coverage`, `llm_calls`, `manifest`, `request`,
`completion`, `ops[]`, `delivery`.

Спецификации: `int | bool | url | (code,N) | (text,N) | (id) | (ids,N) |
(codes,N) | (ints,N) | (dict,S) | (list,S,N) | (map,keyN,S,N) | status_counts`.

| секция | объявленные вложенные ключи |
|---|---|
| `context` | `l1{action,response_act,structure,plan_source,execution_mode,override,model,fallback}`, `tools[]{tool,round,status,error,out_chars,truncated,attempt,refs}`, `coverage{sources,delivered,capacity_chars,delivered_chars,limits,required_claims,evidence_class,required}`, `llm_calls` (код→int), `clock{...}` |
| `writer` | `manifest{manifest_id,writer,profile,composer,context_representation,tokens_total,blocks[]{block,rendered,skip},revisions}`, `request{provider,model,fallback_model,max_output_tokens}`, `completion{finish_reason,finish_reason_raw,metadata_available,completed,is_truncated,attempt,fallback_used,provider,model,usage{prompt_tokens,completion_tokens,total_tokens},max_output_tokens_sent,chars,raw_final_digest,continuation_calls,continuation_stop_reason,text_source,refused,refused_reason,checks{form_guard,protected_facts_mismatch,needs_clarification,numeric_mismatch,cliche_observed,format_observed}}` |
| `delivery` | `ops[]{op,digest,chars,changed,chunks}`, `delivery{outcome,channel,reason,chat_id,tg_message_ids,idempotency_key}`, `raw_final_digest`, `delivered_digest`, `digest_match`, `divergence_reason` |
| `selection` | `counts{3}`, `budget{9}`, `blocks[]{kind,role,rendered,skip_reason,source_ids,first_ts,last_ts,tokens}`, `dropped[]{reason_code,kind,count}`, `self_outputs[]{source_id,tg_message_id,ts}` |
| `search` | `decision,called,status,skip_reason,evidence_class,required,source_count,source_ids[],links[]{source_id,source_url,source_title,published_at}` |
| `style` | `revision,source,applied,counts{только STATUSES},rules[]{rule_id,kind,status,reason,source}` |
| `source`/`clock` | 7 и 5 объявленных ключей (§4) |

Последний рубеж — `_turn_json_safe(out)` на границе ответа: non-finite float →
`null`, значения не из JSON-примитивов/контейнеров отбрасываются, глубина
ограничена. Даже непредусмотренное поле не может уронить страницу.

## Allowlist проекции

Любое поле ответа — только объявленный ключ объявленного типа. Свободная
строка из события не проходит нигде, кроме двух текстовых полей контракта.

| группа | правило |
|---|---|
| коды/enum (`slot`, `window_source`, `policy_mode`, `status`, `decision`, `skip_reason`, `kind`, `role`, `reason`, `revision`, `timezone`, `as_of_utc`, `config_version`, …) | `^[A-Za-z0-9_.:/+@()\-]{1,96}$`, обрезка до объявленной длины; иначе поля нет |
| стабильные id (`source_ids[]`, `blocks[].source_ids[]`, `self_outputs[].source_id`, `links[].source_id`) | объявленный namespace (`msg,tg,row,fact,episode,summary,web,src,source,bot_output,bot_output_tg`) + хвост `[A-Za-z0-9_.-]{1,48}`; два сегмента — только `summary:<chat>:<level>`. `web:javascript:alert` и чужие namespace не проходят |
| числа (включая вложенные `coverage.*`, `tools[].refs`, `completion.attempt`, `manifest.tokens_total`, `ops[].chars`, `usage.*`) | только конечное число в `|x| ≤ 2^53`; `NaN`/`Infinity`/`1e400`/string → `null` — **никогда 0** |
| bool (`stages.*`, `blocks[].rendered`, `search.called/required`, `style.applied`, `digest_match`, `completion.*`, `tools[].truncated`) | только настоящий `bool`, иначе `null` |
| URL (`links[].source_url`) | только `^https?://\S{4,300}$` и НИ ОДНОГО символа `[\x00-\x1f\x7f-\x9f]` (C0/DEL/C1); иначе ссылка целиком не выводится |
| свободный текст (`source.author_alias`, `review_to_alias`, `links[].source_title`) | ≤48/≤120, управляющие символы C0/DEL/C1 и переводы строк сняты |
| статусы правил `style.rules[].status` | только из `style_policy.STATUSES`; правило с необъявленным статусом НЕ выводится (раньше печатался сам код) |
| бюджеты/счётчики | **только** объявленные ключи: `slot,window,window_source,output_reserve,available,budget,policy_mode,payload_tokens,fallback_window` и `available_messages,included_messages,window_messages`; `style.counts` — только статусы закрытого набора `style_policy.STATUSES` |
| `detail`, `repetition`, `content`, `quote_text`, `snippet`, `notes`, произвольные `secret`/`note` | не входят ни в одну секцию (проверяется тестом и мутацией) |

## Повторная находка: вложенные секции (закрыта корнем)

До правки `_turn_chain_view` копировал `l1`, `tools[]`, `coverage`, `llm_calls`,
`manifest`, `request`, `completion`, `ops[]`, `delivery` как сырые объекты —
плоская allowlist их не видела. Проба на одном payload (`e173a02d` → fix):

```
BEFORE context.l1 = {"action":"reply","secret":"RVSECRET_7c1e",
                     "note":"RVNOTE_chat_field","text":"RVTEXT_chat_excerpt",
                     "snippet":"RVSNIPPET_9aa1","inner":{"text":…}}
       coverage  = {"sources":2,"snippet":"RVSNIPPET_9aa1","text":…}
       tools[0]  = {…,"detail":"RVTEXT_chat_excerpt","snippet":"RVSNIPPET_9aa1"}
       llm_calls = {"planning":1,"note":{"text":…}}
       manifest  = {"tokens_total":NaN,"blocks":[{"text":…}],…}
       completion= {"attempt":NaN,"usage":{"prompt_tokens":NaN,"text":…}}
       ops[0]    = {"chars":NaN,"content":"RVTEXT_chat_excerpt"}
       tool_rounds = NaN, semantic_rewrite_count = 0 (из Infinity!)
       strict json.dumps(..., allow_nan=False) → ERROR Out of range float
AFTER context.l1 = {"action":"reply"}
      coverage   = {"sources":2}
      tools[0]   = {"tool":"web_search","status":"success","refs":2}
      llm_calls  = {"planning":1}
      manifest   = {"writer":"l2_writer","tokens_total":null,
                    "blocks":[{"block":"l1:context","rendered":true,"skip":null}]}
      completion = {"finish_reason":"stop","attempt":null,
                    "usage":{"prompt_tokens":null,"completion_tokens":5}}
      ops[0]     = {"op":"l2_scrubber","changed":false,"chars":null}
      tool_rounds = null, semantic_rewrite_count = null
      маркеров в ответе: нет; strict json.dumps → OK
```

## Дефект 1 — утечка в обычном ответе (исправлен)

`_turn_plain_map` копировал ЛЮБУЮ строку из события, а ссылки не проверялись.
До/после на одном и том же загрязнённом payload (проба вне репозитория):

```
BEFORE budget  = {..., "secret": "SECRET_BUDGET_LEAK_9f3a",
                       "note": "текст чата в служебном поле"}
       counts  = {..., "snippet": "SECRET_BUDGET_LEAK_9f3a", "text": "текст чата …"}
       source_ids = ["msg:1", "текст чата в служебном поле"]
       links   = [{"source_url": "javascript:alert(1)"},
                  {"source_url": "текст чата в служебном поле"}]
       style.counts = {"pass": 0, "repaired": 1, "text": "текст чата …"}
AFTER  budget  = {slot, window, window_source, output_reserve, available,
                  budget, policy_mode, payload_tokens, fallback_window}
       counts  = {available_messages, included_messages, window_messages}
       source_ids = ["msg:1"]
       links   = [{"source_id": "web:ok",
                   "source_url": "https://example.test/ok",
                   "source_title": "Нормальный заголовок",
                   "published_at": "2026-11-01"}]
       style.counts = {"pass": 0, "repaired": 1}
```

## Дефект 2 — 500 на `NaN`/`Infinity` (исправлен)
`_turn_int` делал `int(value)`: `NaN`/`Infinity` давали
`ValueError: cannot convert float NaN to integer`, и вся страница хода падала
(500). Теперь число принимается только конечное и в диапазоне; иначе — `null`
для объявленного поля (не 0). Проба «до» на том же payload:
`RAISED ValueError: cannot convert float NaN to integer`; «после»:
`counts.available_messages = null`, `window_messages = 7`, `budget.window = null`,
`blocks[0].tokens = null`, `first_ts/last_ts = null`.

Повторная находка (ВЛОЖЕННЫЕ объекты) закрыта корнем: `l1`/`tools[]`/
`coverage`/`manifest`/`completion`/`ops[]` раньше копировались как объекты,
поэтому `NaN` внутри них валил сериализацию (`Out of range float values are
not JSON compliant`) уже ПОСЛЕ per-row `try/except`. Теперь такие значения
приходят из схемы как `null`, а на границе ответа стоит `_turn_json_safe`.
Дополнительно убраны `or 0`-коэрции: `tool_rounds`/`semantic_rewrite_count`
при невалидном числе → `null`, а не ложный 0; каждая строка цепочки
обрабатывается в `try/except` (сбой одного ряда = «нет данных» этого ряда).


## Якорь и join

* Якорь цепочки — прежние `_TURN_STAGE_EVENTS` (`direct_turn_context`,
  `direct_turn_writer`, `direct_turn_delivery`): только они создают «ход».
* `_TURN_DETAIL_EVENTS` = `direct_turn_selection`, `reply_search_evidence`,
  `tool_phase`, `style_policy` — их строки приклеиваются к УЖЕ существующей
  цепочке по `trace_id`; деталь без якоря не создаёт ход (`trace_not_found`).
* Join строго `chat_id + trace_id`: выборка ограничена `chat_id` в SQL и каждый
  ряд дополнительно проверяется (`rows[].chat_id == chat_id`). Деталь другого
  чата с тем же `trace_id` не приклеивается и не смешивает ходы.

## Форма ответа (аддитивно к `context/writer/delivery`)

```
stages{context,writer,delivery,selection,search,tool_phase,style}   # bool
source{message_id,author_id,author_alias,message_ts,
       reply_to_id,reply_to_author_id,reply_to_alias}
clock{timezone,as_of_utc,timezone_source,config_version,stages[]}
selection{policy_version,counts,budget,blocks[],dropped[],self_outputs[]}
search{decision,called,status,skip_reason,evidence_class,required,
       source_count,source_ids[],links[]}
style{revision,source,applied,counts,rules[]}
```

* `context.clock` — тот же объект с добавленным `stages` (обратная совместимость).
* `selection` дополнительно отдаёт `dropped_total`/`truncated`, когда они есть
  в событии: срез виден как срез.
* `selection.blocks[].role` — ПРИОРИТЕТ ВЫТЕСНЕНИЯ (`p0`…`p3`), а не авторская
  роль участника (подпись в шаге 3 обязана это учитывать).
* `selection.budget.fallback_window: null` = «fallback-окна не было» (факт);
  отсутствующий ключ = «неизвестно».
* `search.links[]` — сохранённые ключи события: `source_id`, `source_url`,
  `source_title`, `published_at`.
* `search` = `null`, когда нет фактов поиска (`reply_search_evidence`); один
  `tool_phase` без них даёт `stages.tool_phase = true` и `search = null`
  («решение о поиске не зафиксировано», R3).

## Старые трассы

Только три якорных события → `selection/search/style = null`, `stages.* = false`,
`available: true` не меняется; `source.*` = `null` по полям; `clock.stages = null`
(«неизвестно», не `[]`: пустой список означал бы «часы не подавались»).
Битый/усечённый `usage_json`/`source_ref_json` → `{}` (нет данных), без 500 и без
подставленных нулей.

## Дедупликация положительных событий

* Повторный снимок выбора: берётся последний по `(ts, id)`; одинаковые id внутри
  блока и в `search.source_ids` рендерятся один раз.
* Повторный поиск: скаляры — из последнего события хода, `source_ids`/`links`
  объединяются без повторов (ключ ссылки — `(source_id, source_url)`).
* Повторные `style_policy`: правила объединяются с дедупом `(rule_id, status)`.
* `self_outputs` — дедуп `(source_id, tg_message_id)`; `dropped` — дедуп
  `(reason_code, kind)`.

## `include_text` (по умолчанию 0)

* Предикат `access_srv.can_access_chat(ctx, chat_id)` проверяется на ТОМ ЖЕ
  `chat_id`, что в пути, и **на границе чтения текста** (`_turn_attach_text`);
  без права — 403 (не пустая строка). Предикат на границе перепроверяется
  реально (права могли измениться между чтением трассы и текстом) — это
  покрыто HTTP-тестом с подменой предиката «первый вызов да, второй нет».
* Источники текста — существующие хранилища: `get_smart_message_by_tg_id`,
  `get_messages_around(before=0, after=0)` (берётся ТОЛЬКО строка нужного
  `tg_message_id`+`chat_id`, т.к. метод откатывается к «последним сообщениям»),
  `get_bot_output_by_tg`. Каждое чтение ограничено `chat_id`, каждая строка
  проверяется на этот чат.
* Текст ≤600 символов + `truncated`; не логируется и не кэшируется; в
  `mca_events` не пишется.
* Добавляются `source.text`, `source.reply_parent{message_id,text,truncated}`,
  `self_outputs[].text`.

## Найденный дефект (исправлен попутно, минимально)

Шаг 1 (`note_clock`) принимал и хранил структурированные часы, но
`TurnTrace.context_payload()` их не сериализовал — Inspector читал пустые строки
(`clock_timezone`/`clock_as_of_utc`/`clock_config_version`/`clock_timezone_source`
отсутствовали в событии). Без этой правки секция `clock{...}` пуста по
построению, т.е. требование §4 невыполнимо. Правка аддитивная (4 ключа при
наличии значения), поведение остальных потребителей не меняется.

## Проверки

| набор | результат |
|---|---|
| `tests/test_ur_f_inspector_step2.py` (новый) | 17 passed |
| `tests/test_ur_f_inspector_step1.py` | 53 passed (ожидалось 53) |
| web/direct/memory API: `test_webapp_api`, `test_webapp_gates_api`, `test_webapp_analytics_api`, `test_webapp_oversight_api`, `test_webapp_memory_overview_api`, `test_chat_lore_api`, `test_direct_chat`, `test_direct_chat_handlers`, `test_direct_chat_prompts`, `test_direct_chat_concurrency` | 512 passed — идентично `92070d0e` (512 passed) |
| `test_ur_ui_effective_config` + `test_ur_c_clock` + `test_rlr_observability` + `test_ur_d_writer` + `test_ur_e_speech` + `test_ur_turn_engine` | 78 passed |
| общий прогон кандидата (18 файлов, включая step-1/step-2) | 685 passed, 0 failed |
| `test_mca23_planned_vs_actual` | 23 passed + 1 failed (`test_routes_pin_untouched`) — падает ОДИНАКОВО на `92070d0e` (устаревший пин sha256 `routes.py`) |

Мутации (каждая отдельно, файл восстановлен побайтово по sha256):

| мутация | красный тест |
|---|---|
| снят предикат на границе чтения текста (`_turn_attach_text`) | `test_permission_predicates_are_enforced_on_http` (`200 != 403`) |
| снят предикат страницы (`direct_turn_diagnostics`) | тот же тест (`200 != 403`) |
| отключена проверка URL ссылки | `test_polluted_durable_json_never_leaks_into_default_response` |
| убрана проверка конечности числа в `_turn_int` | `test_nan_and_infinity_numbers_are_unknown_not_500` |
| снят allowlist статусов `style.counts` | `test_polluted_durable_json_never_leaks_into_default_response` |
| **вложенный raw-copy** (`out[key] = value.get(key)` в словаре схемы) | `test_nested_sections_are_allowlisted_and_json_safe` + тест загрязнённого payload |
| **убрана проверка конечности** (повтор на новом кандидате) | `test_nan_and_infinity_numbers_are_unknown_not_500` |

Финальный пропуск `_turn_json_safe` мутацией не ловится: схема уже отдаёт
`null` вместо non-finite, поэтому страж стоит на непредусмотренный случай. Он
покрыт прямым тестом `test_json_safe_boundary_replaces_non_finite_and_drops_unknown`.

Собственных регрессий не найдено; семь предсуществующих падений, о которых
сообщал Orchestrator, в перечисленных наборах не воспроизвелись (0 падений на
`92070d0e` для тех же команд) — набор уточняется у Orchestrator.

## Остаётся шагу 3

* Подписи и расшифровка кодов (`required`/`beneficial`, block-kind, ops),
  карточки, сворачивание длинных списков, мобильная верстка — это UI.
* Визуальная приёмка (Playwright + Browser Use) и любые `truncated`-подписи.
