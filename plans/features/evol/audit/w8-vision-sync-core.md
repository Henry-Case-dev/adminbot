> **ASAP-VISION-SYNC-01 / CORE lane (w8)** — реализация общего контракта
> готовности медиа, выходного контракта Vision и watchdog жизненного цикла.
> Worktree: `...\WorkspaceData\worktrees\c742e4de9e92c489\evol-71536a366a11-c63f6f44`
> (branch `evol/impl`, база `432c7593`). Изменения НЕ закоммичены (запрет
> владельца); кандидат = рабочее дерево.

# w8 — Vision sync core: готовность медиа, контракт Vision, watchdog

## 1. Аудит (короткий фактический, по коду HEAD)

### 1.1 Точки входа и media-dependent потребители

| Потребитель | Вход | Как получал медиа ДО | Ждал ли готовность |
|---|---|---|---|
| Direct Chat | `DirectChatService._handle_turn` | только маркеры `[фото tg:<id>]` (`media_marker`, `_render_current_question`, `_resolve_earlier_image_markers`) | **нет** — OCR в payload не попадал вовсе |
| Direct tool-путь | `mca_vision.recognize_target` (tool `recognize_image`) | ready-анализ либо постановка durable-джобы | да, но до 45 с и только в tool-пути |
| FactCheck (handler, `_pipeline_v2_enabled()` OFF) | `handlers/factcheck.py` → `resolve_claim_publication` → `load_claim_media` → `mca_vision.render_media_context_async` | рендер кеша | **нет**: `pending` уходил в «распознавание ещё идёт» уже после ответа |
| FactCheck v2 | `services/factcheck_orchestrator._run_inner` | то же (`resolve_claim_publication`) | нет |
| Общий контекст | `services/chat_context.collect_media_analysis_blocks` / `build_chat_context` | `render_media_context_async` (read-only) | нет (by design) |
| Поиск/инициатива/сводки/память | читают `build_chat_context` / рендер | read-only | нет |

Вывод: единой точки `resolve → reuse/enqueue → await/read → evidence → continue`
не было; общий рендерер умел только читать готовое, а ожидание жило в одном
tool-пути.

### 1.2 Реальная причина `vision_adapt outcome=failed strategy=original reason=fits error=""`

Трассировка (код + телеметрия путей):

1. `analyze_image_bytes` отправлял **жёсткий** `max_tokens=1024` для любого
   изображения и любого маршрута (`services/mca_vision.py:2230` до фикса).
2. Длинный скриншот (длинный OCR/таблица) упирался в предел → провайдер
   возвращал **обрезанный JSON** с `finish_reason="length"`.
3. `finish_reason` **никогда не читался**; `parse_analysis_payload` →
   `json.loads` падал → `status="failed"`, `error_reason="parse_error"`.
4. `_emit_adapt` получал `merged` (не исключение) → `error_class=""` → в лог и
   событие уходило `error=""` (поле заполнялось ТОЛЬКО для исключений).
   `outcome=failed`, `strategy=original`, `reason=fits` — ровно наблюдаемая
   картина: изображение по размеру «влезало», отказ был в **выходном** пределе,
   а не в размере запроса.
5. Дополнительно: `content`/`usage.completion_tokens_details.reasoning_tokens`
   не читались, поэтому «thinking-модель истратила весь бюджет на
   размышление и вернула пустой content» тоже выглядело как `empty_content`
   без объяснения.

То есть `error=""` = «исключения нет, отказ пришёл из разбора ответа модели»,
а сам отказ чаще всего = обрезание по 1024 токенам. Ни одна из веток не была
видна в диагностике.

### 1.3 Вторая независимая причина (подтверждена)

`chat_context` собирается из **готовых** анализов; `pending` рендерится как
строка ожидания. Потребитель, который сформировал payload до готовности,
позже уже не менял ответ: Direct вообще не потреблял OCR (только маркер), а
FactCheck/Writer могли финализировать вывод по «pending-снимку».

### 1.4 Что уже было в durable-фреймворке (watchdog-аудит)

Есть: `task_jobs` (queued/running/…), `heartbeat_at` (lease), `fencing_token`,
`recover_stale` (worker_lost + bump fence), `requeue`, `set_next_retry`,
`deadline_at`/`overdue`, `progress_at`, `checkpoint_ref`, heartbeat-петля на
время обработки (`_job_heartbeat_loop`, 30 с).

Чего не было (реальные дыры):

* `recover_stale` помечал потерянную `running`-задачу `interrupted` и **не
  возвращал её в работу** → актив не распознавался никогда (до backfill);
* `queued`-задача без исполнителя (воркер не поднялся/рестарт) висела вечно;
* analysis-строка, оставленная упавшим воркером в `running`, давала
  потребителю **вечный `pending`** (`asset_vision_outcome` возвращал None);
* не было различия «долгий, но живой внешний вызов» vs «настоящее зависание»;
* не было общего срока жизни операции (только интерактивное ожидание).

## 2. Что сделано (изменённые файлы)

### `services/mca_vision.py` — выходной контракт Vision (§5) + per-asset шов

* **Убран `max_tokens=1024`.** `resolve_output_token_limit(route)`:
  конфигурация `models.vision_max_output_tokens` (каталог/горячая настройка) →
  `Settings.VISION_MAX_OUTPUT_TOKENS` (если появится) → дефолт по классу
  маршрута (4096 для обычной VLM, 16384 для reasoning-класса). Клампы
  `[512, 32768]` — защита от бесконечной генерации, а не «бюджет результата».
* **Reasoning off только по возможностям маршрута.** `resolve_reasoning_mode`
  (`models.vision_reasoning`), параметр `reasoning_effort` отправляется лишь
  когда маршрут его принял; отклонение провайдером запоминается
  (`mark_route_param_rejected`) и не повторяется.
* **Structured output** (`response_format` json_schema) — `on|auto|off`
  (`models.vision_structured_output`); в `auto` отправляется только после
  подтверждённого успеха маршрута (`mark_structured_output_proven`), иначе —
  строгий JSON-парсер как совместимый fallback.
* **Различение причин**: `output_truncated` (finish_reason=length/max_tokens),
  `parse_error`, `empty_content`, `unexpected_format`, плюс классы транспорта
  в `detail` (`http_429`, `http_5xx/provider_error`, `http_4xx/...`,
  `timeout`, `image_rejected`, `model_missing`).
* **Разделены признаки успеха**: `transport_success`, `schema_valid`,
  `analysis_ready` (+ `finish_reason`, `output_tokens`, `reasoning_tokens`,
  `content_present`, `output_limit`, `structured_output`, `reasoning_off_sent`,
  `attempts`, `strategy_changes`, endpoint/model) — в `VisionAnalysis.diagnostics`
  и в событии `vision_adapt` (`error_json.cause`). Пустого `error=""` больше
  нет: причина всегда видна.
* **Bounded-стратегия, без бесконечных retry**: максимум 3 HTTP-вызова на
  анализ. Повтор разрешён только для установленных классов — обрезание вывода
  (увеличение предела, reasoning-off) и отклонённый параметр маршрута
  (повтор без параметра). Детерминированно невалидный запрос не повторяется.
* **Длинный OCR** не режется фиксированным символьным бюджетом: полнота
  обеспечивается пределом вывода + существующей адаптацией изображения
  (segment/merge не тронуты, дефолтом не включены). Физически нераспознанный
  текст так и маркируется.
* Публичные швы для общего контракта: `enqueue_asset_analysis` (single-flight
  по `coalesce_key=vision:asset:<id>`, `deadline_at` = общий срок жизни) и
  `await_asset_ready` (событие **+** перечитывание durable-состояния, bounded).
* `VisionMediaWorker._recover_stale` → единый watchdog (см. ниже).

### `services/media_readiness.py` (новый) — контракт/резолвер/барьер/watchdog

* `MediaReadiness` / `MediaAssetState`: `chat_id`, `target_message_id`,
  `source_message_ids`, `asset_id`, `media_group_id`, `association_kind`
  (`own_caption|own_media|reply|quote|album|explicit_ref|adjacent_before|
  adjacent_after`), `association_status` (`resolved|ambiguous|missing`),
  `analysis_status` (`ready|pending|failed|unavailable|unsupported|disabled|
  missing`), `analysis_revision/model/config_revision`, `ocr_blocks/
  visual_description/uncertainty`, нормализованный `reason_code` (никогда не
  пустой при отказе), `job_ref` (job_id/coalesce_key/stage), `actual_revision`,
  `cache_hit`, `consumer_received`.
  `evidence_block()` — payload потребителя (данные, не инструкции);
  `honest_note()` — короткая оговорка для публичного ответа.
* `resolve_target_media` — приоритет §3: own (подпись/медиа) → reply → quote →
  album → explicit_ref → adjacent_before → adjacent_after; слабые связи не
  угадываются (≥2 равноценных кандидата → `ambiguous`), изоляция чата в SQL.
* `prepare_media_evidence` / `prepare_images_ready` / `prepare_asset` —
  reuse ready → enqueue (single-flight) → bounded await → evidence; false
  dependency (обычный текст рядом с чужим фото) даёт `None` — быстрый путь
  не деградирует.
* Отложенные запросы «просьба → изображение» на durable `task_jobs`
  (`vision.pending_intent`): `register_pending_intent`,
  `link_pending_intent_for_message` (хук приёма медиа),
  `claim_resume_for_turn` (ровно одно потребление, CAS),
  `resume_deferred_requests` (возобновление после рестарта),
  `defer_until_ready` (интерактивный таймаут: pending + durable запрос).
* **Watchdog** (§watchdog): `watchdog_sweep`, `recover_job`,
  `watchdog_diagnostics`, политика из конфигурации
  (`limits.vision_job_lease_seconds`, `…queue_wait_seconds`,
  `…job_lifetime_seconds`, `…job_max_recoveries`, `…backoff_base/max_seconds`,
  `limits.vision_readiness_wait_seconds`, `limits.vision_association_window_seconds`,
  `limits.vision_pending_intent_ttl_seconds`). Никаких разбросанных констант в
  обработчиках.
* `run_admin_check` — сервисная основа кнопки «Проверить»: стадии
  `provider → schema → content → saved → consumer`, `ok` только при
  подтверждении всех; HTTP 200 с пустыми `choices` НЕ «OK».

### `services/chat_context.py`

`format_chat_context`/`collect_media_analysis_blocks` — байт-в-байт прежние.
Добавлены `refresh_media_block` (перечитать ОДИН блок с фактической ревизией)
и `pending_media_targets` (какие медиа окна ещё не готовы) — потребитель
может применить актуальную ревизию и не финализировать вывод по pending.

### `services/direct_chat_service.py`

* Барьер **до захвата per-chat слота** (ожидание Vision не блокирует другие
  сообщения чата и пул): `_prepare_turn_media_evidence` →
  `_insert_media_evidence` (блок `<media_analysis>` перед
  `<Current_Question>`; L1 и Writer видят одну ревизию).
* **Перед финальной сборкой payload** — `_refresh_turn_media_evidence`
  (перечитывание БЕЗ ожидания): если анализ завершился между L1 и Writer,
  Writer получает актуальную ревизию, а не pending-снимок (§4.4, §8.11).
* Интерактивный таймаут → `defer_until_ready` (durable) + честный pending в
  payload (содержимое не выдумывается).
* `_claim_resume_intent`: если это сообщение — поздно пришедшее медиа, ход
  отвечает на исходный вопрос (ровно один раз, durable CAS).
* Все методы fail-open: ошибка → прежний путь.

### `services/factcheck_service.py`

* `load_claim_media` (`media_wait_seconds`) сначала доводит связанные
  изображения до фактического анализа (`media_readiness.prepare_images_ready`,
  reuse durable jobs, без новых LLM-вызовов), затем рендерит уже готовое.
* `ClaimMediaMaterial.image_unchecked` + `unchecked_reason`: терминальный
  отказ Vision → «содержимое картинки НЕ проверено (причина)», честно и без
  дублирования `vision_failed`.
* `ClaimPublication.media_pending` / `media_unchecked` / `media_dependency()` /
  `admission_blocked_by_pending_media()` — единая точка правды для обоих
  маршрутов: pending запрещает `no_claim`.

### `tests/test_evol_vision_sync_core.py` (новый)

Сценарии §8: 1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14 (+терминальная ветка), 15,
16 (+маршрут с отклонённым параметром), 17, 20; watchdog 21–25 + два
дополнительных контракта (невосстановимая причина → терминал; диагностика
стадии/lease). Offline: mocked transport, реальная SQLite-БД, без отправок.

## 3. Что переиспользовано (без дублирования)

`recognize_target`-механика (durable job + событие + честный терминал),
`resolve_ready_for_asset`, `latest_asset_analysis`, `asset_active_job`,
`asset_terminal_job`, `asset_vision_outcome`, `terminal_tool_result`,
`render_media_context_async`, `access_scope_for`, `TaskJobStore` (`enqueue`,
`recover_stale`, `requeue`, `set_next_retry`, `finish` с `fencing_token`),
`mca_events`, `hot_config`, `usage_events`. Второго воркера/БД/таблицы/LLM-агента
нет; `REASON_CODES` (§17.2) не расширялся — точные причины живут в
`VisionAnalysis.error_reason`/`analysis.error_reason`/`error_json.cause`.

## 4. Watchdog — как выполнены требования

* **Наблюдение поверх существующего фреймворка.** Стадии берутся из
  `task_jobs` (`queued|retrying|running|ready|terminal`), lease = `heartbeat_at`
  + `lease_seconds`, прогресс = `progress_at`/`updated_at`, владелец = `owner`,
  дедлайны = `deadline_at`/`next_retry_at`. Отдельного журнала нет.
* **Долгий-но-живой ≠ зависание.** Пока heartbeat свежий и/или не истёк
  stage/queue deadline, job считается `alive` (в сценарии 21 доказано: живая
  задача остаётся `running`, пока рядом осиротевшая уходит в recovery).
  Внутренние progress-события не обязательны: реальный транспортный таймаут
  (60 с) + heartbeat + durable-состояние.
* **Bounded recovery.** Сначала проверяется ФАКТ (готовый результат → job
  закрывается `completed`, без повторного вызова), затем невосстановимые
  причины → сразу терминал, затем попытки (`max_recoveries`) → requeue с
  backoff, иначе терминал с конкретным `reason_code`. `fencing_token + 1`
  перед requeue/терминалом — запись старого владельца становится no-op.
* **Fencing/дубли.** Сценарий 23: старый воркер после рестарта не перезаписал
  новый результат (`store.finish(... fencing_token=old)` → `False`),
  `resolve_ready_for_asset` отдаёт новую ревизию. Один анализ на
  asset+config revision — single-flight `coalesce_key` (сценарий 10).
  Уведомление о готовности (durable intent) и фактическая отправка
  дедуплицируются раздельно: `resume_deferred_requests` + CAS-потребление
  → ровно один логический результат (сценарий 24).
* **Два предела.** Интерактивный (`limits.vision_readiness_wait_seconds`) не
  отменяет Vision — запрос уходит в pending/defer; общий срок жизни операции
  (`limits.vision_job_lifetime_seconds`, ставится `deadline_at` при постановке)
  гарантирует терминальный исход.
* **Диагностика.** `watchdog_diagnostics` (job_id, kind, asset_id, consumer/
  owner, stage, время в стадии, attempt, lease, последний прогресс,
  waiting_consumers, deadline/next_retry) + события только на значимых
  переходах (`stalled`, `recovered`, `vision_readiness`-стадии). Приватных
  текстов/OCR/ключей нет.

## 5. Проверки (все — в этом worktree, `...\.venv\Scripts\python.exe`)

| Прогон | Результат |
|---|---|
| `tests/test_evol_vision_sync_core.py` (24 теста: §8 1–6, 10–17, 20 + 21–25) | **24 passed** |
| `tests/test_evol011_vision_telemetry.py`, `test_evol019_vision_recognition.py`, `test_mca19_block_b_round1043.py` | 60 passed |
| `tests/test_factcheck_media_2026_10_25.py`, `test_factcheck_p0_fc.py`, `test_p0_vision_fix_core.py`, `test_asap5_integration_w3.py` | 237 passed |
| `tests/test_direct_chat.py`, `test_direct_chat_handlers.py`, `test_direct_two_call_round1022.py`, `test_direct_context_scenarios_asap3.py`, `test_direct_decision_matrix_asap3.py` (+ мой файл) | 324 passed |
| `tests/test_mca19_block_c_round1043.py`, `test_mca01_tx_task_supervisor_round1027.py`, `test_asap8_v6_c03a_style_recovery.py`, `test_mca17a_observability_core_round1027.py` | 153 passed, **2 pre-existing failures** (см. ниже) |
| `pytest tests/ -k "factcheck or vision or media or chat_context"` | 1337 passed, 38 skipped; 5 failed + 1 error — все вне моего диффа (ниже) |

Доказательство «до/после» по конкретным дефектам:

* **RED→GREEN, обрезание вывода**: до фикса `finish_reason=length` не читался,
  результат — `failed/parse_error` с `error=""`; тест
  `test_sc14_truncated_json_finish_reason_length` проверяет, что причина =
  `output_truncated`, предел вывода увеличен и ровно один recovery-повтор;
  `test_sc14b…` — что после bounded-восстановления исход честно терминальный.
* **RED→GREEN, «HTTP 200 = OK»**: `test_sc15` — `transport_success=False`,
  `ok=False`, `provider=failed` у админ-проверки.
* **RED→GREEN, thinking + длинный OCR**: `test_sc16` — 9000 символов доходят
  целиком (`len(text) > 5000`), `reasoning_tokens=3000` видны,
  `strategy_changes=["reasoning_budget_raised"]`, `reasoning_effort` не
  отправляется вслепую.
* **RED→GREEN, pending-снимок**: `test_sc11` — после завершения анализа между
  L1 и Writer блок становится `status="ready"` с OCR и ревизией 2.
* **RED→GREEN, вечный pending после падения воркера**: `test_sc21/22/25` —
  watchdog находит осиротевшую задачу, безопасно возвращает в очередь или
  даёт терминал; `await_asset_ready` получает терминальный исход.
* **RED→GREEN, «нечего проверять» при pending OCR**: `test_sc17` —
  `admission_blocked_by_pending_media()=True`, после ready тезис из OCR
  извлекается; `test_sc20/25` — честное разделение текста и непроверенной
  картинки.

### Известные pre-existing failures (не мои)

1. `tests/test_factcheck_post_release_w1.py::TestAggregatorFailureTaxonomy`
   (3 теста): реальный DuckDuckGo отдаёт пустую выдачу → `empty_results` вместо
   `provider_error`; модуль/тест не менялись (сетевой/окруженческий класс).
2. `tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer`:
   пин-аудит `database.py` 207→213 и `prompt_release_policy.py` — файлы не мои.
3. `tests/test_mca17a_observability_core_round1027.py::test_registry_event_names_exist_in_code`:
   `direct.reply` объявляет `mca07_answer_cache` (удалено EVOL-031) — не мой
   дифф.
4. `tests/test_youtube_multimodal_download_round1024.py::TestR17NoSignedUrlInLogs`
   — ошибка сбора в файле параллельной video-лейн (в этом worktree изменены
   `handlers/youtube.py` и `tests/test_evol_video_intent.py`).
5. `tests/test_native_reply_media_context_round1024.py` (3 byte-invariant
   теста) — падают только в общем прогоне `-k` (порядок/глобальное состояние);
   изолированно и вместе с моим файлом — 48/48 passed.

## 6. Точные patch notes для файлов вне моей зоны

1. **`services/factcheck_orchestrator._run_inner` (v2-маршрут, ASAP-FC
   committed)** — несколько строк сразу после `resolve_claim_publication` и
   ДО `fsg.evaluate_with_expansion`:
   ```python
   # ASAP-VISION-SYNC-01 §4: пока анализ изображения не готов, no_claim
   # запрещён (пустая подпись ≠ отсутствие тезиса).
   if publication.admission_blocked_by_pending_media():
       text = _guard_outbound(
           random.choice(FACTCHECK_IMAGE_PENDING_PHRASES),
           where="media_pending", chat_id=req.chat_id)
       await send_chunked_reply(bot, req.chat_id, text,
                                req.target_tg_message_id)
       tf.stage_event("deliver", "skipped",
                      reason_code="temporal_media_pending",
                      chat_id=req.chat_id)
       return _finish(OUTCOME_PENDING, "v2_gate:media_pending")
   ```
   (константа `OUTCOME_PENDING` — существующий «отложенный» исход маршрута
   фактчека; если в файле её нет, использовать существующий
   `OUTCOME_NO_CLAIM`-совместимый «не вердикт» и НЕ выдавать `no_claim`-фразу).
   Причина: обработчик (`handlers/factcheck.py`) уже честно отвечает на
   pending, а v2-ветка при пустой подписи может уйти в `no_claim` до OCR
   (её suitability не получает состояния медиа). Пока патч не применён,
   v2-маршрут (`_pipeline_v2_enabled()`, default OFF) остаётся дефектным
   только для случая «подпись пуста + анализ ещё идёт».
2. **`handlers/factcheck.py::_empty_content_phrase`** — одна ветка:
   `if publication.media_unchecked: return random.choice(FACTCHECK_MEDIA_ERROR_PHRASES)`
   перед проверкой `publication.has_image` (сейчас terminal-failure без текста
   попадёт в `FACTCHECK_IMAGE_NO_CLAIM_PHRASES`, хотя содержимое картинки
   НЕ проверено). Notice с честной формулировкой уже добавляется
   `_with_publication_notice` автоматически.
3. **`config/settings.py` + `services/param_catalog.py` + `web/**`** — сделать
   настройки видимыми/редактируемыми (сейчас код читает их из горячей
   конфигурации и честно падает на дефолт, если ключей нет):
   `models.vision_max_output_tokens` (int, 512…32768, дефолт 4096/16384 по
   классу маршрута), `models.vision_reasoning` (`auto|off`),
   `models.vision_structured_output` (`auto|on|off`),
   `limits.vision_readiness_wait_seconds`, `limits.vision_association_window_seconds`,
   `limits.vision_pending_intent_ttl_seconds`, `limits.vision_job_lease_seconds`,
   `limits.vision_queue_wait_seconds`, `limits.vision_job_lifetime_seconds`,
   `limits.vision_job_max_recoveries`, `limits.vision_job_backoff_base_seconds`,
   `limits.vision_job_backoff_max_seconds`. **Я не добавлял эти поля сам**:
   файлы `config/settings.py`/`services/param_catalog.py` держат пин-тесты
   полноты каталога (465/468, `ROUTES_SHA256_*`), общие для всех лейн — правка
   должна идти одной волной с обновлением пинов.
4. **`web/**` (админка «Модели / Распознавание изображений»)** — кнопка
   «Проверить» должна вызывать `services.media_readiness.run_admin_check(db,
   chat_id=..., transport=None)` и показывать стадии
   `provider/schema/content/saved/consumer` (не только HTTP 200).
5. **`services/factcheck_suitability.py`** — менять не нужно, если применён
   пункт 1: гейт работает по тексту тезиса, а запрет `no_claim` при pending
   обеспечивается до вызова гейта.
6. **`handlers/youtube.py`** — изменений не требуется (видео-лейн не
   используется Vision-контрактом изображений).

## 7. Что НЕ покрыто этой волной (следующая)

Сценарии §8: **7** (обычный текст рядом с чужим фото — логика
`is_media_dependent` есть и не блокирует, но сквозной тест Direct-хода с
реальным фото будет в consumer-волне), **8** (два соседних фото разных
участников → ambiguity: резолвер возвращает `ambiguous`, сквозной тест
потребителя — следующая волна), **9** (альбом: `ASSOC_ALBUM` и сбор всех
элементов реализованы, полная приёмка альбома — следующая волна), **18**
(сводки/истории/факты/инициатива — подключаются тем же
`prepare_media_evidence`; сами обработчики вне моей зоны), **19** cross-chat
(изоляция в SQL есть и проверена в sc4/sc2, отдельный негативный сценарий
«чужой чат как источник» — следующая волна).

Живые проверки в Telegram не выполнялись (запрещено условиями задачи);
все проверки — offline на моках провайдера и реальной SQLite.

## 8. Остаточный риск

* Стоимость ожидания: барьер включается для сообщений с собственным медиа
  (в т.ч. с текстом) — при холодном провайдере ответ задерживается до
  `limits.vision_readiness_wait_seconds` (дефолт 20 с) и затем честно
  говорит о pending. Чат при этом не блокируется (барьер до слота).
* `Recovery` переиспользует попытки задачи; для хронически недоступного
  провайдера терминал наступит после `max_recoveries` (дефолт 3) — дальше
  актив подхватывает существующий backfill.
* v2-маршрут фактчека остаётся с дефектом pending→`no_claim` до применения
  патча из §6.1 (маршрут по умолчанию выключен).

---

## Краткое резюме (RU)

Нашёл две независимые причины «бот не видит скрин». Первая — в Vision-вызове
жёстко стоял `max_tokens=1024`, ответ обрезался, JSON не парсился, а
`finish_reason`/токены/наличие `content` вообще не читались: отсюда
`outcome=failed … error=""`. Теперь предел вывода настраивается (каталог,
дефолт 4096/16384 по классу модели), причины различаются честно
(обрезано/не JSON/пусто/неожиданный формат/лимит/таймаут/отказ провайдера),
structured output и отключение reasoning отправляются только если маршрут их
поддерживает, повторы ограничены установленными классами ошибок. Вторая
причина — потребители отвечали по устаревшему «ещё не распознано». Введён
единый контракт готовности медиа (`services/media_readiness.py`) поверх
существующих реестра активов, durable-задач и рендерера: резолв цели
(подпись/reply/цитата/альбом/соседнее фото с честной неоднозначностью),
переиспользование готового анализа, одна задача на актив, ограниченное
ожидание по событиям и БД, честный pending/terminal с причиной, отложенные
запросы «сейчас скину» с однократным возобновлением. Direct Chat и FactCheck
подключены: Direct теперь получает реальный OCR/описание актуальной ревизии
перед Writer и не удерживает чатовый слот на время ожидания; фактчек сначала
дожидается анализа изображения, при pending не говорит «нечего проверять», а
при терминальном отказе прямо сообщает, что содержимое картинки не проверено.
Сверху — watchdog жизненного цикла поверх существующей durable-очереди:
различает долгий живой вызов и настоящий сбой, безопасно возвращает
осиротевшие задачи (fencing не даёт старому воркеру перезаписать новый
результат), гарантирует терминальный исход при исчерпании попыток и
восстанавливает отложенные запросы после рестарта с ровно одним результатом.
Добавлены 24 offline-теста (сценарии 1–6, 10–17, 20 и watchdog 21–25); все
новые и затронутые наборы зелёные, честно зафиксированы 5+2 падения вне моего
диффа (сетевой поисковый тест, пин-аудиты database/registry и сборка
video-лейн). Сценарии 7, 8, 9, 18, 19 — следующая волна; для v2-маршрута
фактчека и админских настроек приложены точные патч-ноты.

---

# §review-fix — устранение блокеров Reviewer (F1–F5 + неблокирующие)

Кандидат: рабочее дерево на базе `b6403881` (core + wave2 в коммитах, правки
этого раунда НЕ закоммичены — запрет владельца). Изменены только: перечисленные
в задании файлы scope.

## F1 (BLOCKER) — «просьба → фото позже» и resume после рестарта в продукте

Было: `register_pending_intent`/`resume_deferred_requests` вызывались только из
тестов; Direct сохранял pending лишь когда изображение УЖЕ есть
(`readiness.pending`), поэтому «сейчас скину скрин» (цели нет) не создавал
намерение; привязывал намерение только `mca_vision`; TTL-уборки не было;
возобновления по таймауту не было; `_claim_resume_intent` сжигал CAS до хода.

Стало (продуктовый путь, без второго цикла):

1. `DirectChatService._prepare_turn_media_evidence`: если запрос медиа-зависимый,
   а цели нет (`association_status == missing` / нет активов) — durable
   `register_pending_intent` (одна запись на сообщение, TTL из конфигурации).
2. Приём медиа (`mca_vision.register_intake_assets`) связывает намерение
   (`link_pending_intent_for_message`) независимо от авто-очереди и СРАЗУ ставит
   анализ актива (single-flight), т.к. потребитель уже попросил разбор.
3. Единственная точка возобновления — `VisionMediaWorker._maintenance_sweep`
   (`_resume_intents` → `resume_deferred_requests(bot=...)`), плюс новая стадия
   `_expire_intents` (`expire_stale_intents`) для TTL-уборки. Обработчик
   регистрирует потребитель: `media_readiness.set_resume_handler(...)` вызывается
   в `DirectChatService.__init__`; реализация —
   `DirectChatService.resume_deferred_evidence` (ответ РЕПЛАЕМ на исходное
   сообщение через тот же канон-шов `persona_short_reply`/`speech_owner_block`,
   что у Вербализатора Stage-2).
4. Намерение закрывается ТОЛЬКО после успешной доставки: resume-колбэк обязан
   вернуть `True`; `False`/исключение → намерение остаётся (следующий проход),
   дубля ответа нет. Ход Direct больше не потребляет намерение заранее —
   `claim_resume_for_turn(consume=False)` + `complete_resume_intent` после
   `_send_direct_answer` (F1d). Исходный вопрос не теряется при подписи у
   поздно присланного фото: вопрос идёт первым в `query` и отдельным блоком
   `<deferred_request>` в payload.

Доказательства: `test_f1_request_then_photo_resumes_once_via_worker_sweep`
(приём фото → привязка + постановка анализа → sweep доставляет РОВНО один раз,
повторный проход no-op), `test_f1_pending_intent_expires_by_ttl`,
`test_f1_direct_registers_intent_when_no_target`, обновлённый
`test_sc3_request_then_photo_resumes_once` (peek → complete → второй claim None).

## F2 (BLOCKER) — «фото, затем отдельное „фактчек“»; слабые связи учитывают автора/ветку

Было: `resolve_target_media` не принимал автора/ветку; `_adjacent_candidates`
фильтровал только chat+время; `resolve_claim_publication` собирал только цель и
альбом; `_parse_trigger` без reply/forward не давал цели; Direct включал
соседство только при явной ссылке.

Стало:

* `_adjacent_candidates` тянет автора/ветку из `smart_messages`
  (`LEFT JOIN`), `resolve_target_media(author_user_id, author_name,
  branch_message_id)`; `_same_author` (id приоритетнее имени; неизвестная
  личность запроса → прежнее поведение) и `_in_branch`.
* Чужое фото без структурной связи (reply/цитата/альбом) НЕ приписывается:
  возвращается `ambiguous` с `reason_code=ambiguous_target`.
* `resolve_claim_publication(trigger_tg_message_id, requester_user_id,
  requester_name, allow_adjacent=True)`: если у цели нет своих изображений —
  тот же общий резолвер ищет фото рядом; однозначно → ids/подпись фото входят в
  публикацию (`media_linked_adjacent`), неоднозначно → `media_ambiguous`
  (честное уточнение, не «нечего проверять»).
* `handlers/factcheck.py`: `_adjacent_target_or_ambiguous` — команда «фактчек»
  без reply/forward доходит до соседнего фото (адаптер с id/подписью, без
  синтетического `Message` и без выдуманного содержимого); чужое фото/≥2
  кандидата → короткое уточнение (`FACTCHECK_CLARIFY_PHRASES`) в
  `_empty_content_phrase` по `media_ambiguous`.
* Direct: `allow_adjacent` включается для медиа-зависимого текстового запроса
  без своего медиа (с автором и веткой).

Доказательства: `test_f2_foreign_photo_is_ambiguous_not_attributed` (фото А →
«бот, фактчек» от Б → `media_ambiguous`, нотис-уточнение; тот же автор → связь
разрешена и OCR в тезисе), `test_f2_handler_reaches_adjacent_photo`
(обработчик находит фото того же автора; чужое → `(None, True)`).

## F3 — одно окно ожидания на запрос

`prepare_media_evidence` считает ОДИН дедлайн (`budget`) и передаёт каждому
активу остаток (`deadline - now`); `prepare_images_ready` пересчитывает остаток
на каждый актив альбома. Доказательство:
`test_f3_single_wait_window_for_album` — 3 незавершённых актива с `wait=1.0`
завершаются за < 2.2 с (раньше ≈3 с и линейно росло).

## F4 — `auto`-режим structured output реально достижим

Одна пробная отправка `response_format` на маршрут (`_STRUCTURED_TRIED`):
успех → `mark_structured_output_proven` (дальше шлём всегда), отклонение
провайдером → `mark_route_param_rejected` + однократный повтор без параметра и
запоминание. `reset_route_param_memo()` очищает и пробу. Доказательства:
`test_f4_structured_output_auto_trial_and_proof`,
`test_f4_structured_rejection_memoized`.

## F5 — стадия `saved` в админ-проверке честная

`run_admin_check` больше не имитирует сохранение: возвращает `saved="n/a"` +
`saved_note` («проверка не пишет ревизию актива: сохранение подтверждается
round-trip'ом через durable-джобу в UI-лейне»); `ok` требует
provider+schema+content+consumer. Доказательство:
`test_f5_admin_check_reports_saved_honestly`. Патч-нота для UI-лейна обновлена
ниже.

## Неблокирующие

* `queued`-задача без исполнителя теперь доходит до терминала: `attempt`
  инкрементируется и при requeue из watchdog (`_bump_fence_and_requeue`), поэтому
  `max_recoveries` ограничивает и «никто не взял в работу». Доказательство:
  `test_nb_queued_without_executor_terminates`.
* Телеметрический шум: `target_resolved` для «медиа в запросе, цели нет»
  больше не пишет `vision_readiness` на каждый ход. Доказательство:
  `test_nb_no_event_noise_for_missing_media_target`.

## Обновлённые патч-ноты (файлы вне scope этого раунда)

1. `services/factcheck_orchestrator.py` (v2-маршрут): после
   `resolve_claim_publication` добавить
   `if publication.media_ambiguous or publication.admission_blocked_by_pending_media():`
   → существующий `OUTCOME_PENDING` с уточняющей/честной фразой (в wave2 уже
   есть pending-ветка; теперь она должна покрывать и `media_ambiguous`).
2. **UI-лейн, кнопка «Проверить»**: `media_readiness.run_admin_check` —
   сервисная основа; стадия `saved` намеренно `n/a`. Полная проверка
   «сохранено/читается» выполняется round-trip'ом через настоящую durable-джобу
   и настоящий актив (создать актив → дождаться анализа → прочитать
   `resolve_ready_for_asset`), а не записью поддельной ревизии из пробы.
3. `web/**` — вывод стадий `provider/schema/content/consumer` + `saved_note`
   без «зелёного OK» по одному HTTP 200.

## Прогоны этого раунда

| Набор | Результат |
|---|---|
| `tests/test_evol_vision_sync_core.py` (35 тестов: §8 1–6,10–17,20; watchdog 21–25; F1–F5 + неблокирующие) | **35 passed** |
| + `tests/test_evol_vision_sync_wave2.py` | 46 passed |
| + factcheck media/p0/fc-r1 | 154 passed |
| direct: `test_direct_chat`, `..._handlers`, `..._two_call`, `..._context_scenarios`, `..._decision_matrix`, `test_asap7_direct_l1` | 337 passed |
| vision/media ядро: `test_p0_vision_fix_core`, `test_evol011`, `test_evol019`, `test_mca19_block_b/c` (+ wave2 + core) | 260 passed |
| Широкий `-k "vision or media or chat_context or factcheck or direct"` | падения ТОЛЬКО pre-existing (не мой дифф): `test_factcheck_post_release_w1` (2, сетевой DDG), `test_native_reply_media_context_round1024` (3, порядок/глобальное состояние — изолированно green), `test_asap7_direct_settings` migration v35 ожидает схему 35 (сейчас 39), `test_direct_fallback_recompose_asap32` (5; тестовый дубль `fb_retries()` без нового kwarg `sent`) |
