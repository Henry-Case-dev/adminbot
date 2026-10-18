# P0-Vision (VISION-FIX-CORE) — design-note: D9 (тик воркера) и флаг включения, 2026-10-19

## 1. D9 — выбранный вариант: claim + фоновые задачи (не «последовательно без пропусков»)

**Факт (recon)**: `_tick_body` обрабатывал до 6 джоб ПОСЛЕДОВАТЕЛЬНО при
таймауте vision-вызова 60 с и интервале тика 5 с; APScheduler `max_instances=1`
писал `skipped: maximum number of running instances reached (1)` — прод: 487
пропусков за 36 ч.

**Решение** (рекон, уточнение 4 — «claim+обработка с корректным параллелизмом
(семафор) ЛИБО последовательно, но без пропуска тиков»; выбран первый):

- тик только делает `recover_stale` → `_expire_deferred` → выбор due-джоб
  (manual > auto, FIFO) → **claim** (`mark_running`, атомарный
  `UPDATE … WHERE status='queued'`) → `asyncio.create_task` на каждую;
- фактическая обработка идёт фоном под семафором `ANALYSIS_CONCURRENCY=2`;
  слотов ровно `2 − inflight`, поэтому claim ограничен конкуренцией
  (третья джоба ждёт следующий тик, очередь не теряется);
- тик возвращается за миллисекунды независимо от длительности вызовов —
  APScheduler-пропуски исчезают; лок `_tick_lock` остаётся только страховкой
  от наложения БД-фаз (наблюдаемо: debug-лог, не тихий skip);
- **heartbeat**: на время обработки отдельная задача пишет `store.heartbeat`
  (пол 1 с, `_heartbeat_seconds`) — `recover_stale(stale_after_seconds=120)` не
  помечает ещё работающую джобу потерянной при долгом вызове (download до
  ~20 МБ + vision до 60 с); fencing_token берётся из свежей строки после
  `mark_running`;
- **shutdown**: планировщик гасится, `drain(timeout=5 s)` ждёт фон, остаток
  отменяется (джобы остаются `running` ≤ heartbeat-окна и будут честно
  восстановлены `recover_stale` при следующем старте — поведение прежнего
  контракта с `worker_lost`);
- backfill (K3) — отдельная фоновая задача при пустой live-очереди и нулевом
  inflight (раньше он выполнялся синхронно внутри тика и мог его растянуть);
  heartbeat пишется и для архивной джобы (`backfill_sweep`, интервал 30 с) —
  долгая загрузка/вызов не выглядит «потерянным владельцем»;
- сбой фоновой задачи виден (WARNING в `_on_task_done`, только класс ошибки —
  R17), а не «Task exception was never retrieved».

**Наблюдаемость**: `meta`-поведение не расширялось; тесты фиксируют
«тик быстрый», «нет дубля», «слоты», «heartbeat живой». Прод-наблюдение
postdeploy: отсутствие `skipped: maximum number of running instances`
в журнале + прогресс очереди.

**Остаточный риск**: при очень долгой обработке (> 120 с без heartbeat —
heartbeat поднят, поэтому окно фактически расширено) или при аварийном
завершении процесса джоба вернётся в работу через `recover_stale`
(дубль-защита: CAS-finish анализа + singleflight-гранула; результат не
дублируется, но возможен повторный vision-вызов при потере процесса —
прежнее поведение).

## 2. Флаг `flags.vision_enabled` — механика включения (уточнение 2)

Цепочка гейтов (существующая, не менялась):

1. **K1 `MCA_VISION_ENABLED`** (env, default ON) — мастер-рубильник
   (`mca_gates.vision_enabled`): OFF → воркер не стартует, ничего не пишется;
2. **глобальный `flags.vision_enabled`** в `bot_settings` — тумблер владельца
   (каталог `flags_module_vision`, карточка модуля «Распознавание изображений»
   в UI → `toggleKey:'flags.vision_enabled'`); отсутствие строки → Settings-дефолт
   `VISION_ENABLED` (env, default **False**);
3. **per-chat override** (`chat_profiles.chat_params.overrides["flags.vision_enabled"]`,
   `flags.*` — per_chat) — резолв `resolve_requested`: override чата → глобал →
   дефолт. Прод-факт: глобально False; включение возможно и точечно (override
   чата), и штатно глобально — код/каталог ничего не блокируют;
4. **effective-состояние** = requested ON **И** capability-чек `ok`
   (`resolve_effective_state`) — производный рендер, не отдельный ключ.

Проверки в срезе: после сброса кеша и с фиксом D1/D2/D8 задания доходят до
реального вызова (при провайдере, отвечающем ok), а не умирают
`capability_check_pending`; включение флага (global или per-chat) — штатная
операция без новых ключей. **Что должен сделать владелец после деплоя**:
включить тумблер модуля (глобально) либо per-chat override; первая джоба
запустит пробу сама (D8).

## 3. Прочие решения P0 в этом срезе (для ревью)

- **D1**: канонический ключ `models.vision_api_base_url`; legacy
  `models.vision_base_url` — алиас совместимости с логом-подсказкой (значение
  не логируется). Прод-выборка recon показала, что legacy-строки в PG нет —
  алиас оставлен только как страховка от старых сохранений.
- **D2**: `api_key_for(route)` — единственный резолвер ключа; отдельный
  endpoint без своего ключа → `vision_key_missing` (не «основной ключ на
  чужой endpoint»); зеркало в `cover_style_jobs._default_scene_verifier`
  (now: `api_type_supported` → `api_key_for` → `chat_completions_url`).
- **D3**: изображения пробы генерируются кодом (zlib/struct PNG, RGB,
  512×512 и 640×512, непрозрачные, детерминированные; ленивый кеш).
  Прозрачная PNG 1×1 (`_NEUTRAL_PNG`) больше не отправляется (оставлена
  только как reference для теста).
- **D5**: словарь reason-кодов НЕ расширялся (269); различия — `detail`
  (R17-safe класс) + `visible_reason` (единая функция отображения).
- **D13**: SUPPORTED_API_TYPES = ("openai_compatible",); иной тип →
  `api_type_unsupported` без отправки payload (задел под адаптеры).
- **routes (item 9)**: ответ `POST /api/vision/test` дополнен `visible_reason`,
  `provider`, `api_type`, `source`; `GET /api/vision/state` (`runtime_snapshot`)
  — `base_url`, `api_type`, `provider`, `detail`. Пересечения с CFG-02B в
  `web/api/routes.py` нет (CFG-02B правит `web/app.js`,
  `services/param_catalog.py`, `services/persistent_throttling.py` и др.; в
  момент среза `web/api/routes.py` не был изменён параллельным лейном).
  Хэш-пин F11 переутверждён осознанно (Δ routes = 0).

## 4. Остатки/риски

- UI-фаза (D10–D12: вызов `visionStateLine`, русские формулировки в форме,
  компактность/переполнение) — отдельный срез после CFG-02B; витрина данных
  для неё уже отдаётся API.
- Живая проба против реального OpenRouter/NanoGPT в этом срезе не делалась
  (нет доступа к ключам владельца в песочнице; честно — postdeploy).
- `probe_connection` в проде ограничен кнопкой (rate-limit 10 с/пользователь)
  и авто-путём (кеш/TTL + singleflight); при постоянно падающем провайдере
  частота авто-проб ≤ 1 на transient-TTL (default 90 с) на конфигурацию.
- Политика retry заданий НЕ менялась: при transient-недоступности провайдера
  задание по-прежнему завершается честным `failed vision_unavailable`
  (терминально, как и раньше); самовосстановление обеспечивают: короткий TTL
  вердикта → следующая проба/задание, backfill-свип (активы без готового
  анализа перебираются заново) и повторная отправка медиа. Изменение
  job-политики в этот срез не входило.
- `image_capabilities.invalidate()` напрямую не вызывается: это кеш
  image-моделей обложек (другой контур). Семантика инвалидации для вердиктов
  vision воспроизведена на месте: ключ кеша включает `config_revision`
  (с хэшем значения ключа), успешная проба перезаписывает transient, есть
  `reset_capability_cache()`. Переиспользованы примитивы
  `extract_provider_error` + `_sanitize_error_text` (R17-разбор тела ошибки).
- Incidental (вне среза): `tests/test_mca01_tx_task_supervisor_round1027.py::
  test_write_points_go_through_single_writer` падает и на чистом HEAD
  (`services/database.py` = 201 `commit`-вызов при allow-map 198) — не
  относится к правкам Vision; передано как pre-existing.
- Лейн CFG-02B правит `web/app.js` и не трогает `web/api/routes.py`
  (на момент среза файл был незакоммиченно чист) — пересечения нет.
