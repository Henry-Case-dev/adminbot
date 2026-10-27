# ASAP5 W2 — IMAGE-ADMIN: возможности, edit-route, противоречия, админка (§18–§22)

Слайсы: `ASAP5-IMAGE-GEN` + `ASAP5-ADMIN` (строки карты REQ-GEN-CAPABILITIES /
REQ-GEN-CONTRADICTION / REQ-GEN-EDIT-ROUTE / REQ-GEN-CONTEXT / REQ-ADMIN-TYPES /
REQ-ADMIN-DIAG). Ветка `task/asap5-image-admin`, база `release/p0-2026-10-26`
@ `ad239f73`. Кандидат: commit `49408a1881d3372ec59a9ebbc53008ba3958997f`
(85 файлов: +2102/−316). Границы лейна соблюдены: без нового пайплайна/
провайдера/второго LLM-вызова; без instruction-квот и нового шаблонирования.

## 1. §19 (CONTRADICTION, был FAILED) — установленная корневая причина и фикс

**Путь воспроизведения (L1 → Capability Registry → ToolRouter → Media
Execution → ToolResult → Writer):**

1. Транзиентный сбой провайдера (timeout/5xx/429) фиксируется
   `capability_registry.record_outcome(ok=False, code=…)` и держит статус
   `temporarily_unavailable` в окне `OUTCOME_COOLDOWN_SECONDS = 120 c`.
2. В следующем ходе `_l1_capability_consistency` резолвит
   `image_generation` → not-available → инжектит Writer'у
   `<capability_notice>` с инструкцией «не обещай выполнение … объясни отказ».
3. Инструмент `generate_image` при этом ОСТАЁТСЯ анонсирован (анонс гейтится
   только флагом модуля) — Writer вызывает его в tool-раунде; провайдер за
   это время восстановился → генерация и отправка УСПЕШНЫ.
4. Финальный ответ Writer собирает при противоречивых входах: устаревшая
   инструкция «объясни отказ» + ToolResult «успешно отправлено». Наблюдаемый
   production-исход — текст «не умею рисовать» при фактически отправленном
   изображении; в следующем ходе отрицание повторяется (своего фото в
   текстовой истории Writer'а нет — прежний дизайн observer, W1 §7.1).

Это одновременно три причины из списка §19 источника: **устаревшая информация
в контексте + игнорирование ToolResult + противоречащие инструкции
функциональных компонентов**.

**Фикс (по причине, не формулировкой):**

* `services/tool_loop.py`: `_sync_claim_with_outcome` /
  `_strip_stale_capability_notices` — после фактического УСПЕХА
  media-инструмента (`generate_image`/`edit_image`, JSON `"status":
  "success"` / `delivery="sent"`) устаревшие `<capability_notice>` этой
  capability выветриваются из модельного контекста (в deepcopy цикла;
  оригинальные messages не мутируются). Неуспех — пометка сохраняется
  (она была правдой на момент планирования). Синхронизация вставлена в ОБА
  пути исполнения: плановый (round=0) и модельные раунды.
* `services/capability_registry.notice_block`: добавлена оговорка
  «пометка отражает состояние на момент планирования; если действие
  фактически выполнилось и результат отправлен — описывай фактический
  результат, а не отказ; недоступность одной операции не означает
  недоступности остальных» — defense-in-depth.

**Тесты (`tests/test_asap5_image_admin.py`):**
`test_generation_success_strips_stale_inability_claim` — RED→GREEN дефекта:
fake-LLM вызывает generate_image (успех) при stale-notice в контексте;
на кандидате финальный payload БЕЗ capability_notice, на базе `ad239f73`
пометка остаётся. `test_failed_generation_keeps_notice_honestly` — неуспех
честно сохраняет пометку. Юнит: strip только своей capability; не-успех не
синхронизирует.

## 2. §18 (CAPABILITIES) — раздельные честные состояния

* `services/capability_registry.py`: НОВАЯ capability **`image_edit`**
  (`_build_image_edit`) из ТЕХ ЖЕ реальных источников: модуль (per-chat
  `resolve_module_enabled`), ключ/модель (hot→chat_params), квота
  (`_image_quota`), наблюдаемые исходы (`record_outcome`/"image_edit"),
  плюс provider edit-capability из СУЩЕСТВУЮЩЕЙ цепочки
  `image_capabilities.resolve_capabilities(provider, base_url, model,
  operation=OPERATION_EDIT)` БЕЗ сети (discovery остаётся у вызывающего
  контура): `yes`→ready, `no`→unsupported (`edit_unsupported`/
  `model_cannot_edit`), `unknown`→**not_configured**
  (`edit_capability_unknown` — поддержка НЕ выдумывается; реестровый
  `STATUS_UNKNOWN` зарезервирован под «capability не в реестре»).
  `image_edit` добавлен в `_DEFAULT_VIEW_IDS` (UI/L1-данные).
* `services/direct_capabilities.py`: `CAPABILITY_TOOLS["image_edit"] =
  ("edit_image",)`, человеческий лейбл «редактирование картинок»;
  `services/response_extent.py`: `CAPABILITY_TOOLS["image_edit"]`.
* `services/tool_schemas.py`: `edit_image` анонсируется тем же флагом
  модуля изображений, что и generate_image (выключенный модуль убирает
  оба; раздельность состояний — работа capability-реестра, не гейта анонса).
* Тесты: ready-from-real-sources; **edit unsupported при generate ready**
  («недоступность одной операции не означает недоступности остальных»);
  unknown→not_configured; module off→disabled; capability_view содержит
  обе; notice-формулировка не подменяет фактический результат.

## 3. §20 (EDIT-ROUTE) — существующий submit_edit подключён к Direct Chat

* **Канон 14→15**: `TOOL_EDIT_IMAGE` (`edit_image`) в КОНЕЦ
  `TOOL_CALLING_TOOLS`; первые 14 имён байт-в-байт (прецедент каждого
  добавления, счётчики/комментарии канона обновлены).
* **Router**: `tool_router._edit_image` — единственный исполнитель
  `media_execution.detect_adapter(base_url).submit_edit(...)` →
  существующий `cover_style_edit.edit_image` (capability-gated, штатные
  окна политики `OPERATION_EDIT`, fallback/retry сохранены). Второй
  редактор/набор провайдеров не созданы.
* **Операция через Capability Registry**: `image_edit` unsupported → честный
  `edit_unsupported` (спекулятивная генерация «вместо edit» запрещена);
  не-ready → честный отказ с реальным reason_code.
* **Исходник**: `target{chat_id,message_id}` из аргументов (другой чат
  запрещён) → reply-цель хода; активы — канонический реестр
  `mca_media_assets` (kinds photo/document/sticker/video_preview/
  animation_preview — доступ к предыдущему результату генерации сохранён:
  бот-медиа регистрируется observer'ом, шов W1 §7.1); скачивание
  существующим `mca_vision.download_telegram_file`; временный файл
  удаляется во всех ветках.
* **Честность**: без исходника → `no_source_image` (генерация «вместо» НЕ
  вызывается; тест ассертит, что submit_edit не зовётся); ошибка
  исполнителя (`submit_edit ok=False`, напр. timeout) → error JSON с
  реальной причиной, отправки НЕТ, `record_outcome(ok=False)`; success →
  существующая доставка `telegram_send.send_photo` (reply на запрос) +
  `record_outcome(ok=True)` + `ctx.image_request_handled=True` (повтор в
  том же ходе не создаёт дубликат).
* **Intent (§20/§21)**: `direct_capabilities.detect_action_intent` —
  аддитивный `INTENT_EDIT_IMAGE` (`edit_actionable`): edit-глаголы
  («измен/редактир/поменя/поправ/исправ/перекрас…»)+объект, либо
  удаление/добавление с локативом («на картинке/с фото…»). Правила W10
  сохранены: negation/forwarded/self/reported гасят и edit;
  create-глаголы сильнее edit («перерисуй мем» — по-прежнему CREATE,
  регресс-тесты W10 зелёные); `edit_actionable` НЕ открывает пре-гейт
  генерации (veto проверен runtime-чеком) — «новая независимая генерация
  не выдаётся за изменение оригинала».

## 4. §21 (CONTEXT) — существующие контекст и журнал операций

* Уточняющий вопрос clarify (`_image_capability_gate`, ambiguous) НЕ
  повторяется ход за ходом: TTL-кеш `_CLARIFY_TS` (600 c, bounded 512
  чатов, прецедент module-level кешей реестра); после TTL вопрос снова
  возможен (не «заглушен навсегда»); при недавнем clarify ход идёт обычным
  путём (Writer решает сам).
* Edit-результат связан с исходным запросом: reply_to + `source{chat_id,
  message_id}` в JSON-результате инструмента; `<image_result>` + postgen-
  блок генерации — без изменений (факт отправки).
* Честные коды вместо искусственной неоднозначности: `no_source_image`/
  `edit_unsupported`/`route_unverified`/`no_input_images` добавлены в
  `_FAILURE_CODE_BY_REASON` (управляемые Factory Default-тексты, без
  нового шаблонирования и без instruction-квот).

## 5. §22 (ADMIN TYPES) — «Типы медиа» в существующем Vision-разделе

* `services/param_catalog.py`: группа **`flags_vision_media_types`**
  («Типы медиа») на СУЩЕСТВУЮЩЕЙ вкладке `mod_vision` (TAB_RULES in-place;
  отдельного GIF-модуля/панели стикеров/второго Vision-раздела нет) + 5
  тумблеров §22 (фото и изображения-документы / статические стикеры / GIF
  и анимации / анимированные и видеостикеры / превью видео и
  видеосообщений). `per_chat` = True (настройки отдельных чатов),
  pg_id `flags.vision_media_*`.
* `config/settings.py`: `VISION_MEDIA_*` — заводские значения ВКЛЮЧЕНЫ
  (default True).
* `services/mca_vision.py`: `media_type_for_asset` (kind/variant → тип,
  матрица §22) + `resolve_media_type_enabled` (env→hot→per-chat, та же
  иерархия, что `resolve_requested`; hot-reload штатный). Гейт в
  `enqueue_intake_jobs` ПО типу: выключенный тип → джобы авто-разбора нет
  (событие `vision_type_disabled`), канонический реестр активов НЕ сужен;
  главный тумблер Vision (K1+K2+requested) сохраняет приоритет; ручной/
  tool-разбор не сужен.
* `web/app.js`: вкладка mod_vision — sources + группа «Типы медиа»
  (рендер существующим generic-каталогом; UI-текст).

## 6. §22 (ADMIN DIAG) — диагностика из существующих записей

* `runtime_snapshot` (GET `/api/vision/state`) дополнен: `media_types`
  (effective-тумблеры §22 с человеческими лейблами),
  `types_need_transform` (gif_animations/animated_stickers/video_previews
  — анализ по кадру-обложке, честная маркировка W1), `queue.failed`
  (существующие durable-строки `task_jobs` kind vision.*),
  `last_error` (reason_code+время последней failed-строки; R17 — только
  коды/время).
* `web/app.js`: `visionStateLine` (очередь + «с ошибкой: N»),
  `visionStateFacts` (Типы медиа, Требуют преобразования — N, Последняя
  ошибка). Отдельного хранилища статистики нет; интерфейс не перегружен
  техдетaлями форматов/кодеков.

## 7. Согласованность каталога (F8-переиздание по прецеденту MCA-20)

`tools/_asap5_w2_reissue_f8.py`: регенерация TSV/meta/screen-map
(`gen_param_registry_round1025.run_emit()`), fixtures
`f8_baseline.json`/`catalog_baseline.json` (counts REGISTRY 587 / GROUPS
121 / _TAB_BY_GROUP 119 / delta 176, sha256 param_catalog.py, note в
superseded_by), перенос guard-счётчиков в тестах (582→587, 461→466,
557→562, 120→121, 118→119, flags 102→107, канон 14→15, tails).
`ROUTES_SHA256_F11` не тронут (routes.py не менялся). Пин sha256
param_catalog в `test_round1025_f8_registry` переутверждён осознанно по
дельте (L-F11S-1). Проверка генератора: `CHECK OK: реестр 587 == REGISTRY,
карта полна, R17-чисто, TSV/map идемпотентны`.

## 8. Прогоны

* **RED (честность):** на базе `ad239f73` 27/29 новых тестов
  `test_asap5_image_admin.py` падают (2 «граничных» — фиксируют прежнее
  поведение).
* **PASS (кандидат `49408a18`):**
  - новый файл: **29 passed**;
  - focused-контуры: capability/tool_schemas (223), tool_loop/router/image
    (177), vision core + block_c + addtr-entry + factcheck-media (193),
    cfg02a/chains/coordinator/mca11/native/transcribe/addtr-tools/
    perimeter + block_a + rework_r1 (282), f8/audit/inventory/block_d/f/g/
    memory_lookup/webapp_api (134), catalog parity (85), ctx-memory (90),
    mca20+mca17c (36), tool_calling+download_quality (51) — все зелёные;
  - **полный набор на кандидате: 15982 passed, 40 failed; из них 38 —
    побитовый пре-существующий список базы ad239f73 (другие слайсы/env:
    playwright-отсутствие ×8+, aiogram без InputRichMessageMedia,
    Speech_Base-порядок UNIFIED-CORE в summary/verbilizer/composer,
    фейки llm_client `sent`-kwarg), +2 флайка нагрузки полного прогона
    (`test_asap8_initreply_binding` / `test_p0_init_arch_fix_observer`
    — initiative/observer-тайминги; в изоляции оба passed, файлы лейном
    не тронуты; на базовом прогоне те же тесты прошли в составе набора)**
    — 0 отказов, относимых на дельту лейна. Сравнение списков:
    `asap5_w2_base_run.txt` / `asap5_w2_final_run3.txt` (scratch).
* `compileall services tests` — OK.

## 9. Границы честного (не закрыто лейном — заявлений нет)

1. Live Telegram/provider-прогон edit-пути — вне границ лейна (без
   прод/SSH/Telegram); контракт доказан harness-тестами на реальном
   адаптере + честных отказах.
2. Полное редактирование видео/анимаций (не превью-обложка) — не существует
   в системе и не заявляется (граница W1 сохранена).
3. Скоуп-замечание для Reviewer/PM: `slice-graph.json` перечисляет для
   IMAGE-GEN/ADMIN более узкие write_scope, чем потребовал связный
   маршрут (tool_schemas/tool_loop/direct_chat_service/response_extent/
   mca_vision/param_catalog + ревизия пинов 65 тест-файлов). Все
   изменения перечислены здесь; параллельных писателей в этих файлах на
   момент лейна не было (worktree изолирован от `release/p0-2026-10-26`).
4. `meta.md` HEAD-штамп = база `ad239f73` (момент генерации F8 до
   коммита кандидата) — см. superseded_by-note в f8_baseline.json.

## 10. Команда воспроизведения

```
py -3 -m pytest tests/test_asap5_image_admin.py -q
py -3 -m pytest tests -q --tb=no -p no:cacheprovider -rf
```
