# UR-F INSPECTOR — релиз 2.58.185 (инспектор хода, шаги 1–3)

Срез инспектора хода выпущен отдельным релизом. Дата: 11.11.2026.

## Идентичность

- **Версия:** `2.58.185`
- **Релизный SHA:** `40d529540ea480e9b188694213bbfb76e471276a` (ветка `release/2.58.185`, запушена в origin)
- **Одобренный кандидат:** `dbf89a96` на `ur/f-inspector-step1` (база `92070d0e`), шаги 1 `c9ef6e72`, 2 `d8270517`, 3 `dbf89a96`
- **Цель порта:** `77a63bc5` (2.58.184)
- **Откат:** `release/2.58.184` = `77a63bc5`; схема не менялась (v47), восстановление БД не требуется

## Метод порта

Ветка `release/2.58.185` создана от `77a63bc5`; срез влит merge-коммитом `fda548a2`
(merge-base `ur/f-inspector-step1` × `release/2.58.185` = `92070d0e`, то есть вносится
ровно дельта среза). Три конфликта — все аддитивные склейки:

| файл | что объединено |
|---|---|
| `services/direct_execution.py` | `published_at_status`/`source_dates` (UR-SRC-DATE) + `source_links` (UR-20.7) |
| `services/direct_chat_service.py` | `memory_scope`/`out_rag_ctx` (VMQ-MEM-TIME) + `correlation_id`/`out_prepared` (UR-F шаг 1) в сигнатурах `_build_user_content`/`_build_rag_block` и в обоих вызовах |
| `tests/test_unified_reply_ur_b_search_first.py` | набор ключей трассы — объединение, ассерты обеих сторон сохранены |

Смысловых развилок не было: обе стороны добавляли независимые поля.

## Дельта к 77a63bc5 (64 файла)

Продуктовые (12): `services/direct_chat_service.py`, `services/direct_execution.py`,
`services/llm_client.py`, `services/style_policy.py`, `services/thread_chain.py`,
`services/tool_loop.py`, `services/turn_trace.py`, `web/api/routes.py`, `web/app.js`,
`web/index.html`, `web/static/app.css`, `config/settings.py` (только `APP_VERSION`).

Тесты (35): новые `tests/test_ur_f_inspector_step1.py` (53), `step2` (19),
`step3_ui` (32), `tests/js/ur_f_inspector_step3_test.js`; правки ассертов в
`test_direct_fallback_recompose_asap32.py`, `test_unified_reply_ur_b_search_first.py`,
`test_webapp_js_unit.py`, `test_auto_budget_asap31.py`; 24 python-пина версии и
4 JS-пина (держались на 2.58.168 и были красными уже на 77a63bc5).

Прочее (16): 14 файлов evidence среза, `tools/ui_urf_visual_e2e.py`,
`plans/docs/param-registry-round1025.meta.md`.

**Не тронуты относительно 77a63bc5 (блобы совпадают):** `services/permissions.py`
`e20d46eb`, `web/api/avatars.py` `3b8be940`, `web/api/deps.py` `509b387d`,
`services/text_morphology.py` `69775156`, `services/summary_memory.py` `717236b5`,
`services/mca_retrieval_context.py` `259bc0b4`.

**Схема:** `services/database.py` и `services/pg_db.py` не менялись; `user_version` = 47
на проде до и после; DDL = 0.

## Проверки до выката (на точном дереве)

| набор | результат |
|---|---|
| `test_ur_f_inspector_step1.py` | 53 passed |
| `test_ur_f_inspector_step2.py` | 19 passed |
| `test_ur_f_inspector_step3_ui.py` | 32 passed |
| web-наборы (63 файла `test_webapp_*`) | 1466 passed / 15 failed — все 15 красные и на 77a63bc5 |
| direct-наборы (17 файлов) | 563 passed / 5 failed — те же 5 красные на 77a63bc5 |
| memory-наборы + ADR-1019 guard | 633 passed, 0 failed |
| полный прогон | 19854 passed; 106 отказов, все воспроизводятся на 77a63bc5 |

Классификация отказов сделана прогоном того же набора файлов на неизменённом
`77a63bc5`: новых отказов — ноль. Пре-существующие классы (не связаны со срезом):
устаревшие пины версии в 4 старых JS-тестах, README без `v<APP_VERSION>`,
5 тестов `test_direct_fallback_recompose_asap32` (двойник без `sent=`),
навигационные снапшоты admin-UI, evidence-даты визуальных тестов.

## Живые наблюдения на проде (read-only, реальные данные)

- `/healthz` публично: `{"status":"ok","version":"2.58.185"}`; локально на хосте то же;
  `systemctl is-active admin_bot` = active; `ActiveEnterTimestamp` 05:27:10 UTC.
- Сервер сообщает HEAD `40d52954…`, ветка `release/2.58.185`, рабочее дерево без
  изменённых отслеживаемых файлов (только `?? .cache/`).
- Журнал с момента рестарта: 0 `Traceback`, 0 записей уровня err, 0 WARNING.
- ADR-1019 guard на развёрнутом дереве: `stem_word("колбасный")` = `колбасн` (и в
  `text_morphology`, и в `search_aggregator`), `term_key("колбасный")` = `колбас`,
  `stem_word("нового")` = `новог`, `stem_word("я")` = `я`,
  `services/summary_memory.py` не импортирует `services.search_aggregator` → green.
- `GET /api/direct/turn-diagnostics` без initData → **401**.
- Подписанная сессия без прав на чат → **403** и для обычного вызова, и для
  `include_text=1` (`{"detail":"нет доступа к чату"}`), текст не отдаётся.
- Владельческая подписанная сессия, чат `-1004482340693` → **200**, `available: true`,
  `turns` = 3. В ответе присутствуют новые разделы: `stages` (7 булевых флагов:
  context/delivery/search/selection/style/tool_phase/writer), `source`
  (`author_id`, `message_id`, без текста), `search` (9 полей, включая
  `evidence_class` и `required`), `clock` с ключом `stages`, `selection`, `style`.
- Старый (до релизный) ход: `available: true`, при этом `selection`, `style`,
  `clock.stages` = **null**, `stages`/`source`/`search` присутствуют — ровно
  заявленный контракт «старый ход отдаёт null-секции, но доступен».
- `include_text=1` с правами владельца → **200**, в `source` появляются `text`
  (280 символов) и `truncated`; без `include_text` ключа `text` в ответе нет.

## Осталось непроверенным (зависит от реального события)

Последний реальный direct-ход в durable-логе — `2026-11-10T21:52:45Z`, то есть за
~7.5 часов до выката; после рестарта новых ходов не было (0 строк
`direct_turn_selection`, 0 новых `direct_turn_context`). Поэтому два пункта
приёмки честно остаются открытыми до первого живого хода:

1. durable-событие `direct_turn_selection` с `chat_id` и `trace_id` (пишется только
   в реальном ходе);
2. заполненные реальными значениями `selection`/`style`/`clock.stages` на этом ходе.

Триггер: первый обычный ход в любом из чатов; проверка read-only, повторяется тем же
скриптом. Сообщения в боевые чаты для получения события не отправлялись.

## Отклонения от «только срез»

Две точечные правки, поведение продукта не меняют:

1. `web/app.js` — комментарий инспектора больше не называет backend-модуль
   `direct_chat_service` (дифф-гард F5 round1025 `test_no_backend_files_in_scope`
   был красным из-за текста комментария).
2. `tests/test_auto_budget_asap31.py` — двойник fallback-адаптера разворачивает
   `(body, prepared)` так же, как `LLMClient`. На одобренном кандидате `dbf89a96`
   этот тест **красный** (шаг 1 изменил контракт адаптера, двойник не обновили);
   дефект кандидата, а не порта. Требует внимания Reviewer/Builder.

## Побочные находки (вне среза)

- `tests/test_webapp_evol_w10_sections.py::test_live_render_sections_e2e` при каждом
  прогоне **перезаписывает отслеживаемые** файлы `plans/features/evol/audit/evidence/*`
  (даты/скриншоты на текущую дату). Файлы восстановлены из HEAD и в релиз не попали;
  тест стоит перенаправить в WorkspaceData.
- 4 старых JS-пина версии держались на `2.58.168` — в этом релизе приведены к
  актуальной версии вместе с остальными пинами.
