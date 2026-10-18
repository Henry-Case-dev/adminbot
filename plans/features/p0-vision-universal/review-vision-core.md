# REVIEW-VISION-CORE — независимое ревью сервисного фикса Vision (P0, VISION-FIX-CORE)

| Поле | Значение |
|---|---|
| Кандидат | uncommitted поверх `f9283b3d` (база сборки `dea5f84a`; чужие docs-коммиты HEAD не пересекаются): `services/mca_vision.py` `493c1651f749`, `services/cover_style_jobs.py` `b732f298f5db`, `web/api/routes.py` `21f72a8ebb4e`, новый `tests/test_p0_vision_fix_core.py` `1852e3240b9d` — sha256_12 все совпали |
| Вердикт | **Approved** — все D-контракты (ARCH/PROBE/PIPE) подтверждены кодом и моими прогонами; живая половина — postdeploy (RFL); UI D10–D12 — отдельный срез |

## 1. D1 — канонический ключ + legacy-алиас
`_vision_base_url()`: приоритет `models.vision_api_base_url` (канонический) → `models.vision_base_url` (legacy-алиас, при использовании — INFO-лог без значения) → `VISION_API_BASE_URL` (env); значение в логи не попадает (R17). Регресс-тесты перепрогоняны: `test_d1_saved_endpoint_reaches_request` (сохранённый адрес реально уходит в запрос), canonical-priority, alias-fallback ✓.

## 2. D2 — ключи строго по профилю
`api_key_for(route)` — единственный резолвер: dedicated-endpoint без своего ключа → `''` → честный `vision_key_missing` (основной ключ на чужой endpoint НЕ отправляется — тест это фиксирует по URL запроса); маршрут на основном endpoint — основной ключ; зеркало `cover_style_jobs._default_scene_verifier` (api_type_supported → api_key_for → chat_completions_url) ✓, тест `test_d2_scene_verifier_mirror_key_missing` зелёный.

## 3. D3 — валидная проба
`_build_probe_png`: детерминированный **непрозрачный RGB PNG** (color type 2), 512×512 и 640×512, ленивый кеш; прозрачная 1×1 (`_NEUTRAL_PNG`) больше не отправляется (осталась reference для теста). Тесты (валидность/размер/непрозрачность + payload содержит большое изображение) ✓.

## 4. D4/D5 — матрица классов
`mock-matrix-2026-10-19.md` (HTTP-матрица + 4xx-семантика + конфиг-отказы) сверена с кодом и тестами: 400 с валидным текстом → `unavailable/image_rejected` (НЕ no_vision), только явный модальный отказ («does not support image input», «No endpoints … image input») → `no_vision`; `model_not_found ≠ modality`; «доступность ≠ мультимодальность» (ok только при 2xx+choices); пустой 2xx (`choices` без content) → ok; словарь reason-кодов 269 не расширялся — различия в `detail` + `visible_reason` ✓.

## 5. D6/D7 — TTL и инвалидация
Transient (`access_error/rate_limited/unavailable/pending`) — TTL `MCA_VISION_TRANSIENT_TTL_SECONDS` (90 с), permanent (`ok/no_vision`) — часы; успешная проба перезаписывает transient; `_capability_key` включает `config_revision` = hash(значение ключа+endpoint+модель+тип) — тест «revision hash без ключевого материала» ✓; ротационные тесты (значение ключа / основного ключа / endpoint / типа) перепрогоняны ✓; `reset_capability_cache()` bounded (локи+кеш) ✓.

## 6. D8 — авто-проба (singleflight)
`ensure_capability()`: свежий кеш уважается, иначе одна проба на конфигурацию (`_probe_lock`), остальные получают её результат; подключена в `process_asset_job` и tool-путь; «job failed с честной причиной вместо `capability_check_pending`» — тест ✓ (`test_d8_auto_probe_failure_reports_honest_reason`).

## 7. D9 — claim + фон (оценка отказа от последовательной схемы)
`_tick_body`: `recover_stale(120s)` → `_expire_deferred` → slots = `ANALYSIS_CONCURRENCY(2) − inflight` → `mark_running` (атомарный CAS только из `queued`) → `create_task`; `_job_heartbeat_loop` (пол 1 с, fencing из свежей строки); `drain(timeout)` bounded, `shutdown` = scheduler off → drain 5 с → cancel; `_on_task_done` — WARNING только класса ошибки (R17). **Оценка:** отказ от «последовательной» схемы обоснован (recon: 487 APScheduler-пропусков за 36 ч); потерь/дублей нет — claim-CAS исключает двойной захват, повторный vision-вызов возможен только при потере процесса (прежнее поведение `worker_lost`/`recover_stale`), результат не дублируется (CAS-finish). Тесты D9 (быстрый тик / нет дубля-потерь / слоты / heartbeat) ✓.

## 8. D13/D14 — типы и URL
`SUPPORTED_API_TYPES = ("openai_compatible",)`: иной тип → `api_type_unsupported` **без отправки payload** (тест по отсутствию запроса) ✓; `normalize_base_url`/`chat_completions_url` — единственная сборка, матрица форм (host, host/, /v1, /api/v1, полный путь) перепрогоняна, двойного `/chat/completions` нет (в т.ч. полный путь в base) ✓.

## 9. Routes и пины
`POST /api/vision/test` дополнен аддитивно: `visible_reason`, `provider`, `api_type`, `source`; `GET /api/vision/state` (`resolve_effective_state`) отдаёт `base_url/api_type/provider/detail/config_revision` — тесты обоих путей ✓. `web/api/routes.py` дифф = +12/−3 (докстринг+поля), **пересечений с CFG-02B нет** (CFG-02B правил `web/api/gates.py`/`app.js`/`index.html`; `routes.py` не входил — сверено по file-list коммита `7e5edd75`); **F11 re-pin осознан**: `ROUTES_SHA256_F11` в тесте == sha256 текущего `routes.py` (`21f72a8ebb4e…`) ✓.

## 10. Флаг
`resolve_requested` = env-мастер (`mca_gates.vision_enabled`) AND hot/каталог-тумблер (`flags.vision_enabled`, per-chat override через `chat_params`); `resolve_effective_state` = requested AND capability `ok` (сеть не вызывается; неизвестное → `capability_check_pending`). Дизайн-нота §2 совпадает с кодом ✓.

## 11. Числа (мои прогоны) и атрибуция свипа
* `tests/test_p0_vision_fix_core.py` → **47 passed** ✓; mca19 A–G + rework + scene delivery → **129 passed** (116 + 13) ✓; routes-пины (`f8_registry` + `mca23`) → **53 passed** ✓; RED (лог) 32F/14P/2E — причины совпадают с D-контрактами ✓.
* **Атрибуция свипа (спот, мой):** factory-fingerprint-кластер (4 теста: `soul1_core_registry_api` ×2, `soul1_registry_completeness`, `soul1_w4_humor_craft`) — на **чистом HEAD-воркtree** 46 passed, в основном дереве 4 failed → дрейф от **чужих uncommitted** factory-текстов (`handlers/direct_chat.py`, `services/direct_chat_service.py`, `services/initiative_*` — все `M`, подтверждено статусом) ✓; `break-all`-кейс — на чистом HEAD 17 passed, в дереве 1 failed (`test_logs_block_layout_mono`) из-за комментария `break-all` в **чужом uncommitted** `web/static/app.css` ✓. Прочие классы (t5150/asap7-v35, mca01 single-writer, outgoing_guard ImportError, summary-моки) — известные pre-existing (сверено ранее: asap7/t5150/mca01 красные и на чистом HEAD).

## Леджер-решения

* **Код-контракты — закрываемо сейчас** (evidence: 47 + 129 + 53 + матрица + design-note + фиксация свапа): `P0V-ARCH-BASEURL/SPLIT/KEYS/ADAPTER/NOFAULT`, `P0V-PROBE-IMG/SPLIT/CLASSIFY/400/CACHE/INVALID/SECRETS/REAL`, `P0V-UNIV-NOHARDCODE`, `P0V-PIPE-BEYOND`; у live-строк ARCH/PIPE — код-половина закрыта.
* **Live (postdeploy, RFL):** `P0V-ARCH-ENDPOINTS/SWITCH` (реальный провайдер), `P0V-PIPE-E2E/FALLBACK/WORKER/CONTEXT` (journal без `skipped: maximum number of running instances`, прогресс очереди, реальное распознавание в контексте); ключей владельца в песочнице нет — честно postdeploy; включает DevOps/Orchestrator (владелец: тумблер модуля/override, первая джоба сама пробует, D8).
* **UI D10–D12** — отдельный срез (данные API уже отдаются) — вне этого ревью.
* **NF-1** (до биндинга/релиза): F11 re-pin (`ROUTES_SHA256_F11`) и общий фикстур-пин-комплект (`f8_baseline.json`/`test_round1025_f8_registry.py`/`test_mca23`) — сейчас uncommitted вместе с чужими лейнами; закоммитить вместе с парой после приземления ENTRY/INIT-ARCH.
* **NF-2**: после коммитов ENTRY/INIT-ARCH переутвердить `FACTORY_SET_SHA256_12` (сейчас 4 чужих factory-теста красные из-за их uncommitted текстов — к VISION-FIX-CORE не относится).
* **NF-3** (рутина биндинга): `candidate` + evidence на 21 строку ARCH/PROBE/PIPE; live-строки → RFL по конвенции.

## Итог

Сервисный слой Vision закрыт в объёме P0: маршрут/ключи строго по профилю, валидная детерминированная проба, честная классификация (400≠no_vision, доступность≠мультимодальность), TTL/инвалидация по конфигурации, авто-проба с singleflight, неблокирующий тик с claim+CAS и heartbeat, универсальные URL/типы без хардкода; витринные поля для UI-фазы отдаются. Все заявленные числа воспроизведены, чужие падения атрибутированы спотом. **Approved** (живая половина — postdeploy; NF-1/NF-2 — до релиза).
