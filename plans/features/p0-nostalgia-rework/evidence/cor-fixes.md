# COR-FIXES (PA5-COR-FIX) — COR-01/02/03: root causes, fixes, verification

Lane: PA5-COR-FIX, ветка `task/pa5-cor`, база `release/p0-2026-10-26` @ `563aac43`
(docs over deployed 2.58.137 line `8adf5fa4`). Коммит кандидата: code+tests+evidence —
см. `candidate_commit` в requirements-map.json (rows COR-01/02/03); биндинг карты —
следующий коммит той же ветки (цепочка, конвенция w1→w2→bind).

Запреты соблюдены: без новых подсистем/провайдеров/LLM-вызовов, без квот,
без словниковых хардкодов (COR-02 — суть фикса), без изменений канона/промптов
(каталог-Δ = 0; ladder не требуется).

## COR-01 — Image Edit: единая конфигурация / формат исходника

Root cause (два дефекта одного пути `_edit_image`):

1. **Конфиг-расщепление.** Проверка способности
   (`capability_registry._build_image_edit`) резолвила model/key через
   per-chat-цепочку `_chat_value` (override чата → hot → default), а base_url —
   глобально; исполнитель (`tool_router._edit_image`) резолвил ВСЁ trio
   глобально через `image_generation._resolve_str` (hot → env). Чат с
   per-chat override провайдера проверялся по одному провайдеру, исполнялся
   другим (модель/ключ/base_url от глобального слоя).
2. **Потеря формата исходника.** Скачанный исходник
   (`mca_vision.download_telegram_file` → `DownloadedImage.mime` — сниффер)
   писался во временный файл БЕЗУСЛОВНО с суффиксом `.png`
   (tool_router.py:3620 базовая линия); MIME edit-запроса выводился из
   суффикса (`cover_style_edit._mime_for`) → JPEG/WebP-исходник
   декларировался провайдеру как image/png.

Fix (минимальный, у владельцев компонентов):

* `services/capability_registry.py`: константа `IMAGE_BASE_URL_KEY`
  (= `models.image_base_url`) + включение в `_TOKEN_KEYS` (когерентность кеша);
  публичный `chat_value()` — ТОТ ЖЕ резолв (`_chat_value`), без новой
  конфиг-системы; `_build_image_edit` теперь резолвит base_url той же
  per-chat-цепочкой, а ярлык провайдера для `resolve_capabilities` берётся из
  РЕЗОЛВНУТОГО base_url (`ig._provider_from_url`) — проверенная способность
  принадлежит провайдеру исполнения.
* `services/tool_router.py`: `_edit_image` резолвит base_url/model/api_key
  через `capability_registry.chat_value(ctx.chat_id, …)` — одна цепочка у
  проверки и исполнения; временный исходник пишется с суффиксом по
  сниффер-MIME (`_EDIT_SOURCE_SUFFIX_BY_MIME`: png/jpg/gif/webp; неизвестный
  mime → консервативный прежний `.png`).

Tests (`tests/test_asap5_image_admin.py`):

* `test_edit_image_source_format_preserved` — JPEG→.jpg, WebP→.webp,
  PNG без изменений; data-URL payload'а edit-запроса несёт фактический MIME
  (`data:image/jpeg` / `data:image/webp` / `data:image/png`).
* `test_edit_image_uses_chat_provider_config` — per-chat override
  base_url/model/key идёт И в capability-проверку (`resolve_capabilities`
  получает provider=host чата, base_url/model чата), И в `submit_edit`
  (adapter base_url, model, api_key) — один effective-набор.
* Регресс неизменён: dispatch/no_source/unsupported/failure тесты зелёные.

Multi-provider приёмка «≥2 чата с разными настройками провайдеров»:
конфиг-сторона корректности доказана тестом на per-chat override
(разные значения у чата против глобального слоя). Live-проба двух реальных
чатов с разными внешними провайдерами — **needs-real-env** (внешние
провайдеры, вне sandbox-компетенции лейна); честно отмечена в map-note.

## COR-02 — Image Intent: семантическое определение редактирования

Root cause: детерминированный пре-гейт классифицировал edit-интент по
словникам основ `_EDIT_VERB`/`_EDIT_REMOVE`/`_EDIT_LOCATIVE_RE`
(direct_capabilities.py:263-271 базовой линии, использовались в
`detect_action_intent`), при том что семантический L1-путь уже существует
(`_l1_capability_consistency`: `plan.capabilities_needed` → честная проверка
image_edit). Владелец запретил словниковые хардкоды; расширение словников
под очередные фразы запрещено ТЗ.

Fix (семантический путь — авторитет):

* `services/direct_capabilities.py`: словники/regex удалены, словесная
  edit-ветка (бывший шаг 3.5) удалена; `detect_action_intent` больше НЕ
  возвращает INTENT_EDIT_IMAGE и не ветоирует по словам — edit/generate
  решение за L1-планом (структурные поля). Create-детекция (W10-контракт,
  другие словники) не тронута — вне скоупа COR-02.
* `services/direct_chat_service.py`: edit-ветка `_image_capability_gate`
  удалена (плана на стадии пре-гейта нет → default non-edit handling без
  edit-специфичных действий; честность edit-capability обеспечивает
  `_l1_capability_consistency` по плану: unavailable → denied + правдивая
  пометка Writer'у, генерация не подменяется).
* Structural guard: routing-fix в `_l1_capability_consistency` получил
  условие `"image_edit" not in requested` — детерминированный create-интент
  (need+объект, напр. «можешь изменить мем») НЕ подменяет генерацией план,
  выбравший edit («создание не путается с редактированием»; «генерация не
  выполняется вместо редактирования»).
* Структурный контракт сохранён: INTENT_EDIT_IMAGE / REASON_EDIT_REQUEST /
  `edit_actionable` / `intent_blockers(edit)` остались для plan/структурных
  intent-источников.

Tests:

* `test_edit_intent_not_word_derived` — ни словниковые, ни естественные
  формулировки (вкл. фразы БЕЗ словарных основ) не дают INTENT_EDIT_IMAGE от
  детектора.
* `test_edit_phrasing_does_not_misroute_into_create` — edit-фраза без
  create-поручений не actionable (fast-path генерации не стреляет).
* `test_word_intent_create_does_not_override_plan_edit` — план с edit +
  create-интект + доступная генерация → routing-fix НЕ стреляет, edit-пометка
  честная (guard против подмены).
* `test_plan_edit_unavailable_denied_and_notice` — план edit + инструмент
  недоступен → denied + notice, fired=False (генерация вместо edit нет).
* `test_plan_edit_available_no_denial_no_generation_force` — план edit +
  инструмент готов → без отказов и без принудительной генерации.
* `test_negated_create_still_suppressed`, `test_create_regressions_stay_create`,
  `test_intent_blockers_cover_edit_capability_status` — регрессы W10 живы.
* Прежние словниковые edit-тесты заменены (контракт изменился намеренно).

## COR-03 — Tool Loop: структурированный результат исполнения

Root cause: `_sync_claim_with_outcome` определяла успех подстрочным поиском
`'"status": "success"'` / `'delivery="sent"'` в тексте вывода
(tool_loop.py:143-146 базовой линии), при том что структурный envelope
`ToolLoopResult.tool_results` (статусы классификации
`tool_result.classify_output`) уже существует и пишется рядом.

Fix: сигнатура `_sync_claim_with_outcome(payload_messages, tool_name, info)` —
успех = структурный статус классификации `info["status"] == STATUS_OK`
(тот же `info` идёт в envelope `tool_results`); `delivery_unknown`/empty/
error/битый info → консервативно 0 (notice остаётся). Оба call-site
(plan-шаг §19 и round-loop) передают структуру. Substring-совпадение в тексте
ошибки больше не трактуется как успех; синхронизация Capability Registry и
Writer сохранена (`record_outcome`/`notice_block` пути не тронуты).

Tests:

* `test_sync_claim_structured_contract` — error/None/текст/пустой dict/
  delivery_unknown/empty → 0; чужой тул → 0; структурный ok → strip.
* `test_sync_claim_structured_success_strips_and_ignores_substring_trick` —
  подстрока `"status": "success"` внутри СТРУКТУРНОЙ ошибки успехом не
  считается.
* `test_substring_success_inside_error_keeps_notice` — тот же трюк сквозь
  полный `chat_with_tools` (router-вывод) — notice остаётся.
* `test_generation_success_strips_stale_inability_claim`,
  `test_failed_generation_keeps_notice_honestly` — прежние end-to-end
  контракты зелёные (успех выветривает, отказ остаётся).

## Верификация (кандидат против базы `563aac43`)

Мандатные сьюты (image/edit/tool-loop/vision + factcheck-регрессия + asap5):

| Батч | Результат |
|---|---|
| test_asap5_image_admin.py (обновлён) | 36 passed |
| asap42 + soul1_intent + addtr + post_asap5_w2 | 176 passed |
| test_asap5_integration_w3.py | 66 passed |
| tool_loop/router/mca11/chains/tool_calling | 192 passed, 1 pre-existing fail |
| vision (mca19b/postgen/vision_adapt/p0_vision/soul1_reg/edit_contract/direct_chat) | 441 passed, 4 pre-existing fails |
| factcheck_media_2026_10_25 + asap7_direct + nostalgia + delta_routing | 225 passed, 2 pre-existing fails |
| cover/media/unified_image | 283 passed, 6 pre-existing + 1 flaky node |
| mca23/direct_l1/scene_delivery/concurrency/nostalgia_ab | 122 passed |
| coordinator/agentic/mca19_rework/byok/cfg02c | 207 passed, 2 pre-existing fails |

Итого: **0 новых сбоев** — каждое падение кандидата воспроизведено на чистой
базе `563aac43` (stash-прогоны), это pre-existing расхождения release-линии
(catalog-count 588≠587 в тесте master-линии; env-зависимые PIL/ffmpeg/retry
тесты; миграционные тесты asap7_direct_settings; AST-freeze унифицированного
запроса) либо флак node-spawn (js-unit, в изоляции проходит).
Иные W2/asap5-сьюты зелёные — поведение W2 не регрессировало.

Incidental findings: `unrelated/pre-existing` — перечисленные расхождения
release-ветки с master-линейными freeze-тестами (catalog counts / AST baseline /
kill-switch legacy) зафиксированы для Orchestrator; в скоуп лейна не входят.
