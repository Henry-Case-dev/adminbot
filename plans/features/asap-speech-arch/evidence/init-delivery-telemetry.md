# Телеметрия доставки инициативы — G1–G7 (аудит `init-delivery-audit`)

LANE_ID: INIT-DELIVERY-TELEMETRY · режим: writer · без сети/прода/DDL.
Основание: `plans/features/asap-speech-arch/evidence/init-delivery-audit/report.md`
(раздел «Пробелы телеметрии», G1–G7). Только технические метаданные (ID/коды/
enum/числа), текста сообщений в payload нет.

## Что теперь записывается

| № | Поле/сигнал | Где физически | Где ставится |
|---|---|---|---|
| G1 | `delivery:chat|reply`, `tgt:<id>`, `tgt_user:<id>`, `addr:<id>`, `corr:<id>`; correlation также в `trace_id` | `mca_events.entity_ids` (JSON-токены) + `trace_id` | `mca_intents.note_decision` |
| G2 | `status = action.delivery_kind` (`reply.text`, `react.react`, `silent.silent`) | `mca_events.status` | `mca_intents.note_decision` / `decision_status` |
| G3 | `reply:<tg_id>`, `delivery:`, `form:`, `mismatch:` + заполненный `config_version` | `initiative_delivery_manifest.entity_ids/config_version` | `mca_intents.note_delivery_manifest` |
| G4 | фактический `parent_message_ref = tg:<id>` | `mca_bot_outputs.parent_message_ref` | ledger-call site инициативы |
| G5 | `target_invalid/missing/no_tg_id/stale/addressee_mismatch/unavailable/gone` | `mca_events.reason_code` | whitelist `mca_events.REASON_CODES` (+7) |
| G6 | correlation Observer-событий | `mca_events.trace_id` | `_insert_event` (fallback при пустом `trace_id`) |
| G7 | фактическая форма `form:chat|reply|react` в существующем событии доставки | `initiative_delivery_manifest.entity_ids` | send-путь и `_execute_initiative_react` |

Новых таблиц/колонок/событий/LLM-вызовов нет. Чтение старых событий
(`status` без `.`, токены без `form/reply`, `config_version` формата
`core=<rev>;...`) сохранено — `initiative_diagnostics` понимает оба формата.

## Пример payload (реальные строки из `mca_events`, текст отсутствует)

```json
{"event_name":"initiative_decided","outcome":"success","chat_id":-1002661910336,
 "stage":"new_message","reason_code":"default","status":"reply.text",
 "trace_id":"bc951871491642d6",
 "entity_ids":["initiative_decision","intent:intent-demo","delivery:reply",
               "tgt:1169990","tgt_user:5885953495","addr:5885953495",
               "corr:bc951871491642d6"]}

{"event_name":"initiative_delivery_manifest","outcome":"success",
 "chat_id":-1002661910336,"stage":"delivery_manifest",
 "reason_code":"initiative_delivered_manifest",
 "config_version":"core.r7.ab12c_style.r2.99aa8_ident.i3.cc1_man.m4.ee33f_c.on",
 "entity_ids":["initiative_delivery","corr:bc951871491642d6","msg:1169991",
               "core:r7.ab12cd34ef56","style:r2.99aa88bb77",
               "identity:i3.cc11dd22","manifest:m4.ee33ff44","composer:on",
               "reply:1169990","delivery:reply","form:reply","mismatch:none"]}
```

Реакция (без текста, тот же слайс): `form:react`, `reply:<tg_id>`, `msg:-`.

## Ключевые технические решения (и почему не иначе)

1. **Новых колонок нет, поэтому метаданные едут существующими полями.**
   `build_event` пропускает только whitelisted поля; `entity_ids` (JSON-токены)
   — уже принятый в проекте транспорт machine-метаданных
   (`note_writer_generated`, `note_delivery_manifest`), `trace_id` — штатная
   колонка correlation (§17.1). DDL в рамке запрещён.
2. **G2: разделитель `.`.** Code-поля валидируются `_IDENT_RE`
   (`[A-Za-z0-9_.:-]`), поэтому `|`/`/` в `status` не доходят до БД; `reply.text`
   проходит, старые значения без `.` читаются как `(action, "")`.
3. **G3: `config_version` был пуст не из-за «сводки», а из-за R17-валидатора**:
   старый формат `core=...;style=...` содержит `=`/`;` и длиннее 64 символов —
   `_safe_value` молча отбрасывал поле (16/16 манифестов в проде пусты).
   Компактный формат `core.<rev8>_style.<rev8>_ident.<rev6>_man.<rev8>_c.<on>`
   укладывается в оба предела; полные ревизии остаются в токенах.
4. **G6: буквальный «`entity_id` в insert-колонки» невозможен без DDL** (колонки
   `entity_id` в `mca_events` нет). Значение не теряется: при пустом `trace_id`
   оно пишется в `trace_id` (корреляционная колонка контракта). Это сознательное
   отступление от буквы пункта в пользу жёсткой рамки «без DDL/новых таблиц».
5. **G7: реакция использует тот же delivery-event** (`form:react`, `msg:-`,
   ревизии пусты) — событие не новое, распределение chat/reply/react считается
   одним запросом по `form:`.
6. **Честный mismatch:** `delivery:reply` + `form:chat` даёт
   `mismatch:<target_*|target_gone|reply_unavailable>`; ledger при этом получает
   `parent_message_ref=NULL` (фактического reply не было).
7. ID проходят общий R17 `sanitize()`; если сконфигурированный секрет случайно
   является подстрокой числа, цифры маскируются (`*`) — это существующее
   поведение всех полей, а не новое.

## Тесты (числа)

* Новый `tests/test_initiative_delivery_telemetry.py` — **11 passed**
  (решение с формой/целями/correlation; react ≠ reply; `target_*` whitelist;
  `form/reply/mismatch`; заполненный `config_version`; `entity_id → trace_id`;
  чтение legacy-событий; реальный send-путь: `tg:…` в ledger, mismatch
  «reply → chat»).
* Обязанный прогон `tests/test_*initiative*` + `test_mca*events*` — **120 passed**.
* Затронутые смежные: `test_asap8_initreply_binding`, `test_mca09_intents_block_c/e`,
  `test_soul1_w5_observer_gates`, пины словаря `test_mca17c_invariants`,
  `test_mca19_block_f`, `test_mca20_integration`, `test_mca20_rework1` —
  **131 passed, 1 pre-existing failure** (`TestValidatorStage.
  test_evidence_injection_stays_data_not_instructions` — воспроизведён на
  чистом `HEAD` в отдельном worktree, к этой правке не относится).
* `test_asap8_v63_w3_analytics_viz`, `test_asap8_v6_c06a_status_ui`,
  `test_p0_initfix_initiative_observer` — **20 passed**.

Пины `len(REASON_CODES) == 302` обновлены до `309` в четырёх файлах
(санкция — G5 этого аудита, +7 `target_*`; комментарии-санкции не переписаны).

## Что останется измерить после деплоя

Один SQL-запрос по новому окну (ничего не досчитывается вручную):

```sql
SELECT json_extract(value, '$')
FROM mca_events, json_each(mca_events.entity_ids)
WHERE event_name = 'initiative_delivery_manifest' AND value LIKE 'form:%';
```

Даёт фактическое распределение `chat|reply|react`; `delivery:%` в
`initiative_decided` — выбранное L1; `mismatch:%` — причины расхождения
(`target_*`/`target_gone`/`reply_unavailable`). До накопления окна ответ
остаётся `NOT_INSTRUMENTED` — теперь измеримым, а не неизвестным.

## Изменённые файлы

`services/mca_intents.py`, `services/mca_events.py`,
`services/direct_chat_service.py`, `services/initiative_diagnostics.py`,
`tests/test_initiative_delivery_telemetry.py` (new), 4 пина словаря причин.
