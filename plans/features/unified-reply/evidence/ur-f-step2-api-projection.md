# UR-F шаг 2 — API-проекция durable-событий хода

База: `c9ef6e72` (шаг 1 принят), ветка `ur/f-inspector-step1`.
Контракт: `ur-f-inspector-contract.md` §4–5; данные — `ur-f-step1-delivery-snapshot.md`.
Внешние источники не использовались (внутренняя проекция существующих событий).

## Что изменено

| файл | дельта |
|---|---|
| `web/api/routes.py` | `_turn_chain_view` + проекторы секций + `include_text` в существующем endpoint'е. Δ эндпоинтов = 0. |
| `services/turn_trace.py` | `context_payload()` теперь сериализует уже собранные `clock_timezone`/`clock_as_of_utc`/`clock_config_version`/`clock_timezone_source` (см. «Найденный дефект»). |
| `tests/test_ur_f_inspector_step2.py` | 8 тестов на реальном HTTP + реальных строках SQLite. |

DDL = 0, миграций и backfill нет.

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
  `chat_id`, что в пути, и на границе чтения текста (`_turn_attach_text`);
  без права — 403 (не пустая строка).
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
| `tests/test_ur_f_inspector_step2.py` (новый) | 8 passed |
| `tests/test_ur_f_inspector_step1.py` | 53 passed (ожидалось 53) |
| web/direct/memory API: `test_webapp_api`, `test_webapp_gates_api`, `test_webapp_analytics_api`, `test_webapp_oversight_api`, `test_webapp_memory_overview_api`, `test_chat_lore_api`, `test_direct_chat`, `test_direct_chat_handlers`, `test_direct_chat_prompts`, `test_direct_chat_concurrency` | 512 passed — идентично `92070d0e` (512 passed) |
| `test_ur_ui_effective_config`, `test_mca23_planned_vs_actual`, `test_ur_c_clock`, `test_rlr_observability`, `test_ur_d_writer`, `test_ur_e_speech`, `test_ur_turn_engine` | 103 passed, 1 failed — `test_mca23…::test_routes_pin_untouched` падает ОДИНАКОВО на `92070d0e` (устаревший пин sha256 `routes.py`) |

Собственных регрессий не найдено; семь предсуществующих падений, о которых
сообщал Orchestrator, в перечисленных наборах не воспроизвелись (0 падений на
`92070d0e` для тех же команд) — набор уточняется у Orchestrator.

## Остаётся шагу 3

* Подписи и расшифровка кодов (`required`/`beneficial`, block-kind, ops),
  карточки, сворачивание длинных списков, мобильная верстка — это UI.
* Визуальная приёмка (Playwright + Browser Use) и любые `truncated`-подписи.
