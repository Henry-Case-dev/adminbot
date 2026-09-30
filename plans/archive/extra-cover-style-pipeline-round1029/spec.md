# `extra-cover-style-pipeline` — spec.md (Step 2 @Architect)

> **Фича:** `extra-cover-style-pipeline` (prefix `EXTRA`). **Эпик:** `memory-context-autonomy` (round 10.27+).
> **Очередь владельца:** ASAP-3.1 ✅ → **EXTRA** → обязательный прод-деплой EXTRA → MCA-tasks.
> **Источник ТЗ:** `plans/current_task.md` строки **9923–12024** (§1–§102), файл immutable. **План PM:** `plans/features/extra-cover-style-pipeline/tasks.md` (T-4091…T-4188).
> **ADR:** `plans/features/extra-cover-style-pipeline/adr-1028-4-cover-style-pipeline.md` (следующий свободный после ADR-1028-3).
> **Статус:** `Proposed` (Accepted — по Merge @Architect в `plans/ARCHITECTURE.md`).
> **Risk-Level:** **R3** (см. §12). **Deploy:** обязательный прод-деплой (§100), bump `2.58.38 → 2.58.39`; rollback §95.
> **Инварианты:** Standard Base Cover Generation — first-class модуль, **НЕ legacy** (§2, §90, §98); R17 (секреты только в Connections, маска); R18 (`current_task.md`/`extra_images/*` байт-в-байт); атомарность «эталон+код+тесты»; Δ DDL/Δ каталога — только по санкции ниже.

---

## 1. Scope / Excluded scope

### 1.1. Scope (in)

1. **Standard Base Cover Generation** сохранён как основной модуль; no-style путь не деградирует (§2, §3, §55, §90).
2. **Optional Cover Style** — постпроцессор поверх готовой base cover: `Base Cover → Style Edit → pub` (§3, §54).
3. **Style Registry** (data-driven CRUD-список профилей) + **seeded** `Графический роман Медведь Press` (`origin=seeded_example`, без special-case по имени) (§5, §6, §59, §63).
4. **Asset storage** для reference/seed/preview: stable `asset_id`, thumbnail, upload PNG/JPEG/WebP, replace/remove, dangling-protection (§8, §12, §64).
5. **Image Model Capability Resolver** (precedence/cache/units) + **Image Prompt Compiler** (priority-aware P0/P1/P2) + **CoverBrief** (§13–§21, §53, §57–§58, §71).
6. **Раздельные model slots/connections** `Base Cover Generation` / `Cover Style Processing`; per-style override; секреты только в Connections; deep-link §35 (§31–§38, §72–§74).
7. **Counters / revisions / provenance** per-style, транзакционно, retry-reuse (§25–§30, §60, §66).
8. **Durable job** REUSE существующей инфраструктуры MCA (`task_jobs` / TaskSupervisor / `mca_pipeline_runs` / `mca_events`), crash-recovery, safe-log, heartbeat, cost (§39–§48, §68–§70, §91–§92, §96).
9. **Fail-soft publication ladder** `styled → base → RichMessage-without-cover → sendMessage` (§4, §49–§52, §96).
10. **Style Editor UI + Miniapp CRUD/preview/references/counter/budget**; capability/connections UI; human-readable RU (§10–§13, §56–§57, §63–§67, §74–§77).
11. **Migration safety / kill-switch / rollback** (§94, §95), **observability** (§96), производственный отчёт (§101).

### 1.2. Excluded (non-goals §102)

Полноценный графический редактор; canvas manual positioning; ручная расстановка каждого logo; pixel-perfect brand validation; **обязательный третий vision QA-вызов**; сложный marketplace стилей; multi-user permissions внутри Style Profile; arbitrary workflow scripting. **Резерв** (архитектурное место, без реализации): `validation_mode = off|basic|strict` (§93).

---

## 2. Grounded facts (по коду и факт-контракту; каждый `[ARCH]`-вопрос опирается на эти факты)

### 2.1. Текущий Base Cover Generation (Q1)

- Композиция промпта — `services/summary_generator.py`:
  - `compose_cover_image_prompt(style, cover_prompt)` (строки ~197–209): `style` сохраняется приоритетно до `SUMMARY_COVER_STYLE_MAX_CHARS` (deflt **500**), `visual` добирает остаток до `SUMMARY_COVER_PROMPT_MAX_CHARS` (deflt **1000**); при переполнении режется **visual**, не style.
  - per-chat «Стиль обложки» — `SummaryGenerator._resolve_cover_style_text(chat_id)` (строки ~1753–1774): `chat_params.get_chat_param(chat_id, "prompts.summary_cover_style", None)` → `hot.get` → `resolve_cover_style` (дефолт `SUMMARY_COVER_STYLE_DEFAULT = "photorealistic, cinematic light"`, `services/summary_prompts.py:221`).
  - fallback-путь при пустом visual-промпте — `_derive_fallback_cover_prompt(text)` (детерминированно, 0 LLM; строки ~1707–1723) под kill-switch `SUMMARY_COVER_FALLBACK_ENABLED` (env-only, ON) + `SUMMARY_COVER_ARTICLE_ENABLED` (env-only, ON) + rich-support guard `_rich_media_supported()`.
  - Фактически отправляемый prompt = `compose_cover_image_prompt(style, visual)`; генерация — `generate_image_verbose(prompt, chat_id=…)` в `_publish_rich_document` (строки ~1247–1304).
- Генерация — `services/image_generation.py`: `generate_image_verbose` → `generate` → `_generate_post`/`_generate_get`.
  - **POST (default):** `POST {base_url}/images/generations`, headers `Content-Type: application/json` (+`Authorization: Bearer <key>` если ключ), тело **строго** `{prompt, model, n:1}` (`_build_post_body`; `size`/`quality`/`response_format` НЕ отправляются сознательно, ADR-1024-4 D1). Ответ: `data[0].url` (скачиваем) или `data[0].b64_json`.
  - **GET:** `GET {host}/image/{quote(prompt)}?model=&width=1024&height=1024&seed=` (анонимный, без ключа).
  - Асинхронных image jobs/status НЕТ ни в интеграции, ни в текущем контракте провайдера (см. §2.3).
- Временный файл: `_write_temp_image` (tmp, вызывающий удаляет) — байты **не персистятся**; `final_asset_id`/`base_asset_id` в текущем коде отсутствуют.

### 2.2. Текущий публикационный контур (Q10)

- Единое ядро богатой доставки — `SummaryGenerator._publish_rich_document` (строки ~1224–1400): порядок `cover → rich_document_limits → _send_rich_with_retry(media=[build_cover_media(tmp_path)])`.
- При отсутствии/ошибке обложки — `_plain_fallback(...)` (строки ~1837+): даунгрейд rich→plain. **Rich без обложки как отдельный режим сейчас НЕ поддержан** (при `not tmp_path` сразу plain; §51/§81 требуют обратного).
- Коды: `CODE_SUMMARY_GENERATION_FAILED` / `CODE_COVER_GENERATION_FAILED` / `CODE_RICH_MESSAGE_SEND_FAILED` / `CODE_TEXT_FALLBACK_FAILED`; события S7 `COVER_START/COMPLETE/ERROR`, `SUMMARY_*`, `FORMAT_*`, `PUBLISH_RICH_*`.
- `services/telegram_send.py`: `SUMMARY_COVER_MEDIA_ID="summary_cover"`, `build_cover_media`, `send_rich_message(content_format="html")`.
- Медиа: durable asset-регистра с stable `asset_id` **нет**. Есть `services/media_share.py` (uuid-файл + HMAC-URL, TTL — транзиентный шаринг), `media_integrity.py` (аудит файлов), `media_download.py` (Telegram `file_id`). Это НЕ «media/assets storage» из §8 — см. ADR D6.
- Durable jobs (LIVE на проде 2.58.38, MCA wave): `task_jobs` (SQLite **v14**), `TaskSupervisor`/`TaskJobStore` (`services/task_supervisor.py`: `enqueue/heartbeat/finish/recover_stale/checkpoint/progress/requeue/next_retry`), `mca_events` (v15), `mca_pipeline_runs` + `mca_incidents` (v19; `services/mca_trace.py::start_run/finish_run/heartbeat`), `services/mca_process_registry.py` (code-declared).

### 2.3. Фактический image-API контракт (Q2/Q3/Q4) — верифицировано по документации провайдера

Код-дефолт провайдера — **Pollinations** (`IMAGE_BASE_URL=https://gen.pollinations.ai/v1`, `IMAGE_MODEL=flux`, POST), **заменяем через PG/catalog** (`models.image_base_url`/`models.image_model`/`models.image_get_mode`/`keys.image_api_key` — группа `models_images`/`keys_images`). Owner §15 требует изучить реальный API, не только Studio UI. Проверено (docs.nano-gpt.com, 2026):

- **Discovery (runtime metadata) — источник истины capability:**
  - `GET /api/v1/image-models?detailed=true` → per-model: `architecture.input_modalities`, `capabilities.image_generation/image_to_image/inpainting`, `supported_parameters.resolutions/max_images/rendering_speed/fixed_image_count`, `pricing` (USD per image).
  - `GET /api/v1/images/models/{model}/endpoints` → `input_reference_constraints.max_items`, `route` (`min_width/min_height/max_bytes/formats`), `supports_streaming`, `pricing`.
  - **Прямая инструкция провайдера: «Do not hardcode image model capability tables in your client»** — совпадает с §14/§15 владельца.
- **Generation (существующий путь совместим):** `POST /api/v1/images/generations` (OpenAI-compatible; `prompt`, `model`, `n`, `size`, `response_format`). Legacy img2img-поля: `imageDataUrl`/`imageDataUrls`/`maskDataUrl` (base64 data URL; direct URL не поддерживается; upload ≤4 MB).
- **Edit (для Style Processing):** `POST /api/v1/images/edits` (и alias `/images/edit`) — OpenAI-compatible, `multipart/form-data`: `prompt` (required), `image` **или** `image[]` (multi-image), `mask` (opt), `model` (opt). Нормализованный маршрут `POST /api/v1/images` принимает `input_references` (URL/data-url/typed), `n`; нельзя смешивать `input_references` с legacy-алиасами (`conflicting_image_inputs`).
- **Qwen Image (nano-gpt.com/models/image/qwen-image):** «precise image editing… multi-image editing», **Images Per Run: up to 4**, **up to 3 reference/edit images**, **route max 30 MB**, `size=auto` (match input image for edits). → пример владельца «Qwen поддерживает 3 изображения» **подтверждён**: `max_input_images=3`, `image_edit=true`.
- **Async (Q4):** документированные image-маршруты **non-streaming / synchronous** — клиент ждёт завершённый результат; async `submit→task_id→status/poll` в image-контракте **не публикуется**. → `async_jobs=false` для известных маршрутов; §40 polling реализуется capability-gated (если провider/connection сообщит async — REUSE durable job + provider task_id).
- **Prompt limit (Q3):** провайдер **не публикует** char/token-limit промпта. → `prompt_limit = {value: <из внутренней конфигурации>, unit: "chars", source: "internal_config"}` либо `unknown`; **`800` в код не переносится** (§15).

### 2.4. Каталог/конфиг (Q5/Q9)

- Изображения в каталоге: группа `models_images` (`IMAGE_BASE_URL`/`IMAGE_MODEL`/`IMAGE_GET_MODE`), `keys_images` (`IMAGE_API_KEY`, секрет); вкладка `mod_images` (`TAB_MOD_IMAGES`), nav `NAV_MODULES`.
- Приоритет model-конфига по каталогу (прецедент ASP-2 `models_summary_hybrid`): per-chat override → `hot.get` → Settings/env.
- FB8 baseline (подтверждено импортом `services.param_catalog.REGISTRY`): **REGISTRY 484 / Settings 424 / categorized 459 / GROUPS 105 / _TAB_BY_GROUP 103 / TAB_RULES 21** (`tests/fixtures/round1025/f8_baseline.json`).
- Реестр SQLite-миграций (mca-14): `services/database.py::migration_steps()` → v1…v19; прод `PRAGMA user_version=19`. Бронь `mca-04b` = **v20** (`plans/docs/mca-round1027-arch-frames.md` §1.2.5; ADR-1027-9 D13). PG DDL — `services/pg_db.py::DDL_STATEMENTS` (идемпотентный `CREATE TABLE IF NOT EXISTS` при старте; **не** поднимает `user_version`); прецедент PG-only таблицы — `image_reservation` (A5, round1026).

---

## 3. Контракты (observable behavior + failure semantics)

### 3.1. Standard Base Cover (first-class, §2/§90) — REQ-EXTRA-01

- **Preconditions:** Summary text ready; chat имеет доступный image-provider.
- **Behavior:** при выборе `Без дополнительного стиля` (дефолт для существующих config) выполняется **ровно текущий** путь: `compose_cover_image_prompt(resolve_cover_style_text(chat_id), visual_prompt)` → `generate_image_verbose` → rich-доставка с cover.
- **Invariant:** результат функционально идентичен до-EXTRA (regression §90). Base-промпт остаётся `prompts.summary_cover_style` (§62, no duplicate source of truth) — никакой второй копии/второго ключа.
- **Failure:** как сейчас — `COVER_GENERATION_FAILED` → §3.4 ladder.

### 3.2. Cover Style — optional post-processor (§3/§54/§55) — REQ-EXTRA-02

- **Modes** (§54): `generate_only` | `generate_then_edit` | `edit_only`. Seeded `Медведь Press` = `generate_then_edit`. `Без дополнительного стиля` = НЕ профиль, а explicit selection → Base Generation без style-stage.
- **Style stage input:** готовая base cover (temp из job) + references профиля (ordered) + compiled prompt (issue number, инструкции, reference descriptions, P0-invariants).
- **Precondition capability:** выбранная `Cover Style Processing` модель **обязана** поддерживать `image_edit`; иначе §38-ошибка, API-call **не** запускается.
- **Style stage НЕ заменяет** Base Generation и **не перегенерирует** base при падении (§49).

### 3.3. Style Edit = normalizer, не overlay (§23/§24) — REQ-EXTRA-03

- Семантика seeded prompt: ensure/replace/normalize — не добавлять второй `PERMsoc`; править/заменять существующий issue-badge; заменять чужой publisher-logo на reference `Медведь Press`; не дублировать `Медведь Press`; сохранять композицию/сцену и удачные callouts (§22/§85/§86).
- **Composition не фиксируется** жёстко; identity recurring: `PERMsoc`, brand/reference, issue number, graphic-novel характер.

### 3.4. Fail-soft publication ladder (§4/§49–§52/§96) — REQ-EXTRA-04

```
styled cover      (style SUCCEEDED)
   ↓ style FAILED → base cover (НЕ перегенерировать base, §49)
   ↓ base FAILED  → RichMessage WITHOUT cover (degraded mode, §51)
   ↓ rich FAILED  → ordinary sendMessage (существующий Summary fallback, §52)
```
- Ошибка оформления **никогда** не уничтожает готовый текст (§4).
- `RichMessage without cover` — **новый штатный degraded-режим существующего форматтера** (media=[]), не второй пайплайн (§51/§81).
- Классификация cover-result для логов/§96: `styled` | `base(reason=style_failed)` | `none(reason=base_failed)` | `publication=plain_send_message(reason=rich_failed)`.

### 3.5. Style Registry (§5/§6/§26/§29/§59/§63) — REQ-EXTRA-05

- Список: `Без дополнительного стиля` + seeded `Графический роман Медведь Press [Пример]` + custom + `+ Создать стиль`; badge `Пример` только по `origin=seeded_example`.
- Поля профиля: `name`, `pipeline_mode`, `instruction` (style prompt), `references=[{asset_id,label,description,ordering}]`, `counter{enabled,value,format}`, `preview{before_asset_id,after_asset_id,revision}`, `model{use_default|connection_id+model_id}`, `revision`, `enabled`, `origin`, timestamps.
- CRUD: Create/Read/Update/**Duplicate**/Delete/enable-disable. Runtime **data-driven**: `if style == "medved_press"` запрещён (§6/§98).
- Seed **идемпотентен**: повторный прогон — no-op; ручной стиль не перезатирается (§59).

### 3.6. Asset storage & seed import (§8/§9/§12/§64/§77) — REQ-EXTRA-06

- **Asset Registry:** stable `asset_id` (детерминированный для seed: `sha256 → id`), метаданные (filename/mime/size/sha256/origin/timestamps), **файлы на durable диске** вне git (managed dir `var/cover_style_assets/`, env `COVER_STYLE_ASSETS_DIR`). Style Profile хранит `asset_id`, **не** blob/URL (§12).
- **Seed import:** `extra_images/medved_press.png` → reference asset; `style_example_01.png` → preview-before; фактический файл `style_example_02.**jpg**` → preview-after (см. DC-1). **Не генерировать замены** (§7).
- **Upload:** PNG/JPEG/WebP validation, size cap, progress, thumbnail, filename/label, Replace/Remove, понятная ошибка.
- **Dangling-protection (§64):** delete используемого reference — запрет с сообщением либо удаление link после подтверждения; broken `asset_id` не остаётся.

### 3.7. Image Model Capability Resolver (§13–§18/§37/§38/§53/§71) — REQ-EXTRA-07

- `ImageModelCapabilities`: `text_to_image`, `image_edit`, `prompt_limit{value,unit∈{chars,tokens,bytes,unknown},source}`, `max_input_images`, `max_input_bytes`, `supported_sizes[]`, `prompt_expansion`, `async_jobs`.
- **Precedence (§16):** 1) explicit developer override (аварийный escape-hatch, env/config, **не** обычная настройка) → 2) runtime/provider API metadata (**`GET /api/v1/image-models?detailed=true` + `/images/models/{model}/endpoints`**) → 3) provider-specific model catalog → 4) verified internal capability registry → 5) `unknown`/conservative fallback (`image_edit=unknown`, `max_input_images=0`).
- **Cache (§17):** по `provider+base_url+model`; invalidate при смене connection/model, reload config, explicit refresh, TTL. Не дёргать metadata на каждую обложку.
- **Units (§18):** `tokens` — подходящий estimator/tokenizer, без грубого перевода в chars.
- **References UI (§13):** `model.max_input_images − 1 (base cover) = available references`; пересчёт при смене модели.
- **§38:** модель без `image_edit` → `Эта модель не умеет редактировать готовые изображения и не подходит для Cover Style Processing.`; API не вызывается.
- **§53:** `prompt_expansion` разрешён для Base Creative, для Style Edit — по умолчанию выключен/строгий (model-policy, не universal hardcode).
- **§71 model switch:** инвалидация cache, пересчёт references/budget, новая job на новой модели; активные jobs — по своему snapshot.
- **Локальные/неизвестные провайдеры (T-4111):** при отсутствии discovery-endpoint источник истины — developer override (уровень 1) или verified internal registry (уровень 4); иначе conservative `unknown` (level 5), сохранение профиля не запрещается (§58).

### 3.8. Image Prompt Compiler + CoverBrief (§19–§21/§53/§57/§58/§88) — REQ-EXTRA-08

- Компоненты (§19): base style prompt, dynamic cover brief, style instructions, runtime issue number, reference descriptions, mandatory invariants (P0), provider/model constraints.
- **Priority-aware (§20):** P0 (runtime invariants; не обрезать случайным `text[:N]`) > P1 (композиция/callouts/сюжет) > P2 (stylistic hints). При pressure **сначала сокращается P2**; P0 и issue number сохраняются всегда.
- **CoverBrief (§21):** `{scene, mood, subjects[], callouts[]}` — компактный сюжет вместо полной Summary-prose; compiler сам решает объём под capability; Summary-pipeline не знает prompt-limits image-provider.
- **Budget indicator (§57):** статика / runtime+number+reference reserve / запас сюжета; при `unknown` — «Провайдер не публикует точный лимит инструкции» без ложного числа.
- **§58:** unknown-limit не запрещает сохранение профиля; при API validation error логируется capability mismatch; registry обновляется отдельно.

### 3.9. Connections / Model Slots / secrets (§31–§36/§72–§74) — REQ-EXTRA-09

- Разделены: **Connection** (base URL/key/provider), **Image Model Slot** (`connection_id`+`model_id`), **Style Profile** (что делать с изображением). Слоты: `Base Cover Generation` (существующие `models/image_*`) и `Cover Style Processing` (новые ключи, §4.1).
- Глобальный default Style Processing + per-style override (`Использовать default` / `Выбрать другую`).
- **Secrets только в Connections** (§36/R17): API key не в Style Profile/JSON/logs; UI показывает `Подключено` / `API ключ не настроен`; после сохранения фронт получает только маску `•••••••• configured` + Replace (§74).
- **§35 deep-link:** кнопка `Настроить подключения →` → экран `ИИ → Подключения` с фокусом на `Обработка стилей обложки`; возврат сохраняет контекст редактора.
- **§73 validation:** Test connection / Fetch models+capabilities / status / last successful check; без обязательной реальной генерации, если есть metadata endpoint (у NanoGPT есть).

### 3.10. Counters/Revision/Provenance (§25–§30/§60/§66) — REQ-EXTRA-10

- Counter — **per-style** (не глобальный); config `enabled`/value/format (`ВЫПУСК {counter}`); слово `ВЫПУСК` не хардкодится в runtime.
- **Pin номера к run:** первый assign `(summary_run_id, style_id) → issue`; retry/regen того же Summary → тот же номер (`44→retry→44`).
- **Concurrency (§28):** две параллельные публикации одного style → разные номера; свойства: уникальность внутри style, retry-reuse, reproducibility (не gapless ценой хрупкости). Assignment транзакционный/idempotent.
- **Revision snapshot (§29):** на старте job фиксируются `style_id/revision/resolved instructions/reference asset IDs+versions/issue number/connection+model/capability snapshot`; изменение профиля во время генерации не влияет на текущий job.
- **Provenance (§30):** metadata итоговой картинки (`summary_run_id/base_asset_id/final_asset_id/style_id/style_revision/issue_number/provider/model/connection_id/reference_asset_ids/timestamps/job_id/status-fallback mode`).
- **Test Style (§66):** не расходует production counter (preview `ВЫПУСК 00` либо текущий номер без commit); counter меняется только в реальном production assignment.

### 3.11. Durable job / recovery / logging / heartbeat / cost (§39–§48/§68–§70/§91–§92) — REQ-EXTRA-11

- **Отдельная image execution policy (§39/§41/§69):** gen ~≥1 мин, edit ~≥2 мин; **НЕ** общий text-LLM timeout. Сейчас `IMAGE_ATTEMPT_TIMEOUT_SECONDS=180` (кламп 600), `IMAGE_GENERATION_MAX_ATTEMPTS=2` (кламп 5), backoff 2 c. Style-stage — собственное окно (env-only), синхронный путь §41.
- **Async provider jobs (§40):** if provider supports `submit→task_id→status/poll` — использовать; polling interval provider-aware (не хардкод). **Текущий image-контракт — synchronous** → `async_jobs=false`, реализуется §41-путь; async-путь capability-gated, provider task_id сохраняется в job payload.
- **REUSE durable job (§42/Q6):** `task_jobs` (v14) через `TaskSupervisor`/`TaskJobStore` + `mca_pipeline_runs` (v19) через `mca_trace.start_run`/`finish_run` + `mca_events` (v15). **Второй очереди/второго стора нет.**
  - State machine: `CREATED → BASE_SUBMITTED/RUNNING/SUCCEEDED/FAILED → STYLE_SUBMITTED/RUNNING/SUCCEEDED/FAILED → PUBLISH_RICH/PLAIN → DONE/FAILED` (маппинг на `task_jobs.status/reason_code/checkpoint_ref`).
- **Crash/restart (§43):** state не теряется; `provider task_id` сохраняется (если async); после restart polling продолжается; новый платный task **не** создаётся, если старый жив.
- **Stage logging (§44):** `COVER_PIPELINE_START/BASE_*/STYLE_*/RICH_PUBLISH_*/PLAIN_FALLBACK/PIPELINE_DONE`.
- **Safe log fields (§45/R17):** можно run/job/style/revision/issue/connection/provider/model/prompt length+hash/reference count/duration/provider task id/status/fallback; **нельзя** API key/полный prompt/raw Summary/приватные URL с секретами.
- **Heartbeat (§46):** при долгом gen/edit — `COVER_STYLE_RUNNING elapsed=…s provider_status=…`, без спама.
- **Analytics timeline (§47):** текст/base/style/Rich + fallback-строки; RU-статусы (§48/§75), machine reason — только в техдеталях.
- **Cost (§92):** base/style/preview cost логируются/агрегируются раздельно; preview маркируется `mode=preview` (§67). Discovery `pricing` — источник оценки.
- **§91:** не блокировать event loop долгим sync-запросом (существующие async/network abstractions).

### 3.12. UI (§10/§56/§76/§77) — REQ-EXTRA-12

- **Style Editor (§56):** Название / Как применяется / Инструкция стиля (textarea + budget) / Референсы (thumbnail cards) / Нумерация (toggle+next+format) / Как работает стиль (Before→After) / Модель обработки (default/custom) / Connection status + `Настроить подключения →`.
- **Preview (§10):** `Протестировать стиль` применяет профиль к base image; сохранение результата как preview; при изменении prompt/reference старой revision → `Пример создан для предыдущей версии стиля` + `Обновить пример`.
- **Test Style (§65/§67):** отдельный Style Edit job, без Summary, `mode=preview`.
- **RU UI (§75):** `Базовая генерация обложки`, `Обработка стилем`, `Референсы`, `Нумерация выпуска`, `Модель обработки`, `Настроить подключения`, `Использована базовая обложка`; tech-имена — только в раскрываемых техдеталях.

### 3.13. Kill-switch / migration / rollback (§94/§95) — REQ-EXTRA-13

- **Kill-switch `COVER_STYLES_ENABLED`** — env-only `ClassVar`, default **ON**. OFF: Base Cover + публикация работают, Style UI disabled/скрыт, миграционного rollback base-cover не требуется, Style stage полностью пропущена (parity baseline).
- **Migr. safety (§94):** config без выбора Style → автоматически `Без дополнительного стиля`; добавление Registry/assets/issue-state не ломает существующие Summary.
- **Rollback (§95):** hot — `COVER_STYLES_ENABLED=false`; cold — `git revert` (PG-таблицы аддитивны; откат base-cover не требуется).

---

## 4. Data contracts / DDL

### 4.1. Δ каталога (санкция @Architect) — +4 ParamSpec

| # | pg_key | Settings field | Тип | Группа | Назначение |
|---|---|---|---|---|---|
| 1 | `models.image_style_base_url` | `IMAGE_STYLE_BASE_URL` | str | `models_images` | Base URL «Обработка стилей обложки» |
| 2 | `models.image_style_model` | `IMAGE_STYLE_MODEL` | str | `models_images` | Модель «Обработка стилей обложки» |
| 3 | `keys.image_style_api_key` | `IMAGE_STYLE_API_KEY` (secret) | str | `keys_images` | Ключ (маска; только Connections) |
| 4 | `prompts.summary_cover_style_id` | — (PG-only, `per_chat=True`) | str | `prompts_summary` | Per-chat выбор Style Profile (`""`=`Без дополнительного стиля`) |

- **F8-переиздание ОБЯЗАТЕЛЬНО** (ADR-1026-2): repin `sha256(param_catalog.py, pg_db.py)`, regenerate TSV/meta/ScreenMap/widget-map, recount/delta, обновить `tests/fixtures/round1025/f8_baseline.json` + ассерты. Обновление тестов — **не отключение**.
- **Точные F8-числа (от 484/424/459/105/103/21):** REGISTRY `484→488`; Settings `424→427` (три env-поля, п.1–3); categorized `459→463` (все 4 имеют group); GROUPS `105` **без изменений**; `_TAB_BY_GROUP` `103` **без изменений**; `TAB_RULES` `21` **без изменений** (при необходимости правило `mod_summary` правится IN-PLACE; прецедент ASP-2); `delta 73→77`. **Итог: 488 / 427 / 463 / 105 / 103 / 21.**
  - Если реализация не даст env-поле п.4 (PG-only) — Settings остаётся `427` (совпадает).
  - Если п.4 размещается в новой группе — GROUPS `105→106`; **рекомендация: не создавать новую группу** (использовать `prompts_summary`).

### 4.2. Δ DDL SQLite = **0** (РЕШЕНИЕ D1 — вариант (b)); Δ PG-DDL ≠ 0

**SQLite: Δ = 0.** Style Registry / assets / counters / issue-assignment / revision / provenance — в **PostgreSQL**, а не SQLite. Обоснование в ADR-1028-4 D1. `mca-04b` сохраняет бронь **v20**; `plans/docs/mca-round1027-arch-frames.md` §1.2.5 и ADR-1027-9 D13 **не править**; `mca-round1027-arch-frames.md` §1.2.4 — без изменений.

**PG-DDL (идемпотентно, через `services/pg_db.py::DDL_STATEMENTS`; `user_version` не поднимается; прецедент A5 `image_reservation`):**

```sql
-- cover_style_profiles (Style Registry)
CREATE TABLE IF NOT EXISTS cover_style_profiles (
  profile_id      TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  origin          TEXT NOT NULL DEFAULT 'custom',   -- seeded_example|custom
  pipeline_mode   TEXT NOT NULL DEFAULT 'generate_then_edit', -- generate_only|generate_then_edit|edit_only
  instruction     TEXT NOT NULL DEFAULT '',
  counter_enabled BOOLEAN NOT NULL DEFAULT false,
  counter_value   BIGINT  NOT NULL DEFAULT 0,
  counter_format  TEXT    NOT NULL DEFAULT 'ВЫПУСК {counter}',
  model_mode      TEXT    NOT NULL DEFAULT 'default',   -- default|custom
  connection_id   TEXT,
  model_id        TEXT,
  preview_before_asset_id TEXT,
  preview_after_asset_id  TEXT,
  preview_revision        INTEGER,
  revision        INTEGER NOT NULL DEFAULT 1,
  enabled         BOOLEAN NOT NULL DEFAULT true,
  is_deleted      BOOLEAN NOT NULL DEFAULT false,
  validation_mode TEXT NOT NULL DEFAULT 'off',          -- резерв §93
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cover_style_profiles_active
  ON cover_style_profiles (enabled, is_deleted);

-- cover_style_references (ordered reference assets; §11)
CREATE TABLE IF NOT EXISTS cover_style_references (
  ref_id      TEXT PRIMARY KEY,
  profile_id  TEXT NOT NULL REFERENCES cover_style_profiles(profile_id) ON DELETE CASCADE,
  asset_id    TEXT NOT NULL,
  label       TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  ordering    INTEGER NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cover_style_refs_profile
  ON cover_style_references (profile_id, ordering);

-- cover_style_assets (stable asset_id → durable file; §8/§12)
CREATE TABLE IF NOT EXISTS cover_style_assets (
  asset_id    TEXT PRIMARY KEY,
  scope       TEXT NOT NULL DEFAULT 'global',     -- global|chat:<id>
  filename    TEXT NOT NULL,
  mime        TEXT NOT NULL,
  size_bytes  BIGINT NOT NULL,
  sha256      TEXT NOT NULL,
  origin      TEXT NOT NULL DEFAULT 'upload',     -- seed|upload|generated_preview
  disk_path   TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cover_style_assets_sha
  ON cover_style_assets (sha256, scope) WHERE deleted_at IS NULL;

-- cover_style_issue_assignments (§27/§28 — pin номера к run)
CREATE TABLE IF NOT EXISTS cover_style_issue_assignments (
  profile_id     TEXT NOT NULL,
  summary_run_id TEXT NOT NULL,
  issue_number   BIGINT NOT NULL,
  assigned_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (profile_id, summary_run_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cover_style_issue_unique
  ON cover_style_issue_assignments (profile_id, issue_number);

-- cover_style_provenance (§30)
CREATE TABLE IF NOT EXISTS cover_style_provenance (
  provenance_id     TEXT PRIMARY KEY,
  summary_run_id    TEXT,
  job_id            TEXT,
  style_id          TEXT,
  style_revision    INTEGER,
  issue_number      BIGINT,
  base_asset_id     TEXT,
  final_asset_id    TEXT,
  provider          TEXT,
  model             TEXT,
  connection_id     TEXT,
  reference_asset_ids JSONB,
  status            TEXT NOT NULL,   -- staged|styled|base|none
  fallback_mode     TEXT,            -- ''|style_failed|base_failed
  mode              TEXT NOT NULL DEFAULT 'production', -- production|preview
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cover_style_prov_run ON cover_style_provenance (summary_run_id);
```

- **Counter allocator (транзакционно, §28):** `SELECT ... FOR UPDATE` по профилю (или `UPDATE cover_style_profiles SET counter_value=counter_value+1 ... RETURNING counter_value`) + `INSERT ... ON CONFLICT (profile_id, summary_run_id) DO NOTHING`; если assignment уже есть — вернуть существующий номер (retry-reuse). Уникальность `(profile_id, issue_number)`.
- **Файлы:** `var/cover_style_assets/<asset_id>` (managed, env `COVER_STYLE_ASSETS_DIR`); fsync при записи; seed-файлы **копируются**, `extra_images/*` не изменяются/не удаляются (R18). Хранение самого изображения — не PG; PG хранит метаданные (§12).

### 4.3. REUSE (Δ DDL = 0)

- Durable jobs — `task_jobs`(v14)/`TaskSupervisor`; pipeline-runs/telemetry — `mca_pipeline_runs`(v19)/`mca_events`(v15); процессы — code-declared `mca_process_registry`.
- Публикация — существующие `_publish_rich_document`/`_plain_fallback`/`telegram_send`, коды `*_FAILED`.
- Base-промпт — существующий `prompts.summary_cover_style`.

---

## 5. Requirement traceability (REQ → § → SC)

| REQ | § | SC |
|---|---|---|
| REQ-EXTRA-01 Standard Base Cover first-class | §2/§3/§55/§90 | SC-01, SC-02, SC-27 |
| REQ-EXTRA-02 Optional Cover Style / modes | §3/§54/§55 | SC-02, SC-03 |
| REQ-EXTRA-03 Normalizer semantics | §22–§24 | SC-19, SC-20 |
| REQ-EXTRA-04 Fail-soft ladder | §4/§49–§52/§96 | SC-04…SC-08, SC-28 |
| REQ-EXTRA-05 Style Registry + seed | §5/§6/§59/§63 | SC-09, SC-13, SC-14, SC-23 |
| REQ-EXTRA-06 Asset registry/import/upload | §8/§9/§12/§64/§77 | SC-10, SC-11, SC-24 |
| REQ-EXTRA-07 Capability Resolver | §13–§18/§37/§38/§53/§71 | SC-15, SC-16, SC-26 |
| REQ-EXTRA-08 Prompt Compiler + CoverBrief | §19–§21/§57/§58 | SC-17, SC-18, SC-25 |
| REQ-EXTRA-09 Connections/slots/secrets/deep-link | §31–§36/§72–§74 | SC-12, SC-21, SC-22 |
| REQ-EXTRA-10 Counters/revision/provenance | §25–§30/§60/§66 | SC-13, SC-14 |
| REQ-EXTRA-11 Durable jobs/recovery/log/heartbeat/cost | §39–§48/§68–§70/§91–§92 | SC-05, SC-29, SC-30 |
| REQ-EXTRA-12 UI (editor/preview/test) | §10/§56/§65–§67/§75/§76 | SC-23, SC-24 |
| REQ-EXTRA-13 Kill-switch/migration/rollback | §94/§95 | SC-31, SC-32 |

Каждый §1–§102 имеет ≥1 задачу (см. `tasks.md` trace-таблицу) и ≥1 SC; осиротевших нет.

---

## 6. Security / privacy (R17)

- API key — только `keys.*` (Connections), маска `{configured,last4}`; нет в Style Profile/JSON/логах/фронте после сохранения (§36/§74).
- Логи — только whitelisted поля (§45): нет полного prompt/raw Summary/приватных URL с токенами.
- Upload — только PNG/JPEG/WebP; лимит размера; sanitized filename; assets вне git; nothing user-supplied исполняется.
- Capability discovery идёт на тот же connection (base_url/key), без утечки ключа в query.

---

## 7. Acceptance scenarios

| SC | Проверка | § |
|---|---|---|
| SC-01 | `Без стиля`: base generated, style skipped, Rich с base (§78) | §78 |
| SC-02 | style success: base→style(base+refs)→styled published (§79) | §79 |
| SC-03 | pipeline modes: seeded=`generate_then_edit`; explicit `Без стиля` (§54/§55) | §54/§55 |
| SC-04 | style failure → base published, **no second base gen** (§80) | §80 |
| SC-05 | base failure → no style call; Rich without cover; Summary successful (§81) | §81 |
| SC-06 | rich failure → ordinary sendMessage; body preserved (§82) | §82 |
| SC-07 | `RichMessage without cover` как штатный degraded-режим (§51) | §51 |
| SC-08 | §96 classification в логах (styled/base/none/plain_send_message) | §96 |
| SC-09 | Regression: Standard base cover до/после идентичен (§90) | §90 |
| SC-10 | seed reference = `medved_press.png`; preview before=`style_example_01.png`, after=`style_example_02.jpg` (§77) | §77 |
| SC-11 | asset upload PNG/JPEG/WebP, thumbnail, Replace/Remove, dangling-guard (§12/§64) | §12/§64 |
| SC-12 | Connections: Base URL/Key/Model style slot; скрытый ключ; deep-link + возврат (§35/§72/§74) | §35 |
| SC-13 | counter per-style; format configurable; retry reuse `44→44` (§25–§27/§83) | §83 |
| SC-14 | concurrent assignment → разные номера; test-preview не тратит counter (§28/§66/§84) | §84 |
| SC-15 | capability fixtures: known chars/known tokens/unknown/edit yes/no/1/many refs/async/sync (§87) | §87 |
| SC-16 | model без `image_edit` → §38-ошибка, нет API-вызова | §38 |
| SC-17 | compiler: всё влезает / P2 сокращён первым / P0 сохранён / number сохранён / нет random mid-string truncation / unknown limit / provider reject oversize (§88) | §88 |
| SC-18 | CoverBrief компактнее prose; Summary-pipeline не знает limits (§21) | §21 |
| SC-19 | foreign logo → replace/normalize, не дубль; visual verification (§85) | §85 |
| SC-20 | existing PERMsoc/issue → нет второго PERMsoc/badge; номер нормализован (§86) | §86 |
| SC-21 | secrets: key не в style JSON/logs; фронт получает маску (§36/§74) | §36 |
| SC-22 | capability UI показывает edit/limits/sizes/sync/async/source (§37) | §37 |
| SC-23 | Style Editor структура §56 + CRUD + Duplicate (§5/§56/§63) | §56 |
| SC-24 | Before/After preview, stale-revision, Test Style standalone (§10/§65/§67) | §10 |
| SC-25 | budget indicator; unknown-limit не блокирует save (§57/§58) | §57/§58 |
| SC-26 | model switch: cache invalidated, references/budget пересчитаны (§71) | §71 |
| SC-27 | `Base Cover ≠ Legacy` naming/Runtime без special-case (§2/§6/§98) | §2/§6 |
| SC-28 | ошибка оформления не уничтожает текст (§4) | §4 |
| SC-29 | long-running image policy ≠ text LLM timeout (§39/§41/§69/§91) | §39 |
| SC-30 | durable job переживает restart; async task_id сохранён (§42/§43/§89) | §89 |
| SC-31 | migration safety: existing config → `Без стиля`; Summary не ломается (§94) | §94 |
| SC-32 | kill-switch OFF: Base + публикация живы, Style UI disabled (§95) | §95 |

**Production acceptance §100:** no-style (base+Rich, без деградации) / Medved Press (base→style→reference→issue→styled→Rich) / style failure → base / base failure → Rich без изображения / rich failure → sendMessage / UI / логи. **DoD §99 (35 пунктов)** замаплен в `tasks.md`.

---

## 8. Browser-Verification contract

**`Browser-Verification: REQUIRED`** — фича меняет user-visible Miniapp UI (Style Editor, списки, upload, preview, capability/connections).

- **Entry points:** TMA `https://admin-bot.duckdns.org/web/` → раздел Summary/Обложка; маршруты (hash) новых экранов Style Registry/Editor; deep-link `ИИ → Подключения` (фокус `Обработка стилей обложки`).
- **Prerequisites:** прод-подобная среда или локальный harness; существующий Telegram TMA envelope (`get_tma_user`, RBAC как у config-роутов); PG с seed-стилем; `extra_images/*` импортированы.
- **Viewports:** mobile (TMA ≤ 430px) + desktop.
- **Interactions/outcomes:** список Styles / seeded `[Пример]` / Create / Duplicate / Edit / reference upload / thumbnail / Replace / Remove / Before→After preview / Test Style (mode=preview) / numbering UI / model selection / capability update после смены модели / connections redirect + return / RU-подписи (§75) / dangling-guard (§64).
- **Structured (Playwright, required):** DOM/a11y — список, CRUD, upload flow, redirect, capability-пересчёт, disabled-state при kill-switch; console/network — отсутствие ошибок и утечки ключа в ответах.
- **Визуальные скриншоты (Browser Use required для materially visual):** корректность Before→After, thumbnail/логотип, общая верстка mobile/desktop.
- **Default:** Playwright MCP. **Browser Use дополнительно** — для реального визуального сравнения и persistent-Chrome (TMA).
- Никаких изобретённых тест-креденшелов: используется существующий TMA-envelope проекта.

---

## 9. Dependencies

- **Внешняя:** image provider с discovery-endpoint (`GET /api/v1/image-models?detailed=true`) и edit-route (`/images/edits` или `/api/v1/images` c `input_references`); рекомендуется NanoGPT Qwen Image (edit, ≤3 refs, 30 MB). Совместимость — capability-gated, конкретный provider выбирает владелец в Connections.
- **Внутренние (REUSE):** `summary_generator`, `image_generation`, `telegram_send`, `chat_params`, `hot_config`, `param_catalog`, `pg_db`, `task_supervisor`, `mca_trace`, `mca_events`, `media_share`-паттерны (HMAC-URL для превью-отдачи).
- **Блокеров нет.** Требуется product-decision владельца по начальному counter (D8).

---

## 10. Test / deploy / rollback strategy

- **Unit/runtime:** §78–§92 → `tasks.md` блок J; особо критичный regression §90/SC-09.
- **Capability/compiler fixtures:** §87/§88 (chars/tokens/unknown/edit/sync/async/P0/P2).
- **Browser:** Playwright + Browser Use (§8 выше).
- **Migration smoke:** PG-DDL идемпотентна (повторный старт — no-op); SQLite Δ=0 → `PRAGMA user_version` остаётся 19.
- **F8:** переиздание по процедуре ADR-1026-2 (repin sha256 + recount + update fixture/ассертов).
- **Deploy:** bump `2.58.38 → 2.58.39`; обязательный прод-деплой; health 200, `database is locked`=0, version 2.58.39.
- **Rollback:** hot `COVER_STYLES_ENABLED=false`; cold `git revert` (PG-таблицы аддитивны); cold DDL-откат не требуется; base-cover функциональность не откатывается.

---

## 11. Answer map

### 11.1. §97 Q1–Q10

- **Q1 (Base Cover + exact prompt):** §2.1 spec; `compose_cover_image_prompt(style_text, visual_prompt)` → отправляется в `generate_image_verbose`; style = per-chat `prompts.summary_cover_style` (дефолт `photorealistic, cinematic light`), visual = из Stage-1 (`draft.cover_prompt`) либо детерминированный fallback; капы 500/1000 chars. Base = first-class, не legacy.
- **Q2 (NanoGPT endpoints):** §2.3 spec — generation `POST {base}/images/generations` (код); discovery `GET /api/v1/image-models?detailed=true` + `GET /api/v1/images/models/{model}/endpoints`; edit `POST /api/v1/images/edits`/`/images/edit` (multipart `image[]`) и нормализованный `POST /api/v1/images` (`input_references`). Код-дефолт провайдера — Pollinations; реальный прод-provider — через `models.image_base_url`.
- **Q3 (реальные лимиты Qwen 3/Pro):** §2.3 — discovery отдаёт `max_images`, `input_reference_constraints.max_items`, `route.max_bytes`; для Qwen Image: до 4 выходов, **до 3 reference/edit images**, route max 30 MB, `size=auto`. **Char-limit промпта API не публикует** → `prompt_limit.source=internal_config|unknown`, `800` в код не переносится. Capability читать из `image-models` at runtime (провайдер сам запрещает хардкод).
- **Q4 (async jobs/status):** image-маршруты non-streaming/synchronous; async `submit/status/poll` **не публикуется** → `async_jobs=false`; §40 реализуется capability-gated, §41 sync-путь с отдельным timeout.
- **Q5 (интеграция Resolver с config):** §3.7/§2.4 — резолв connection из `hot.get`/per-chat cascade по `models.image_style_*`/`keys.image_style_api_key`; base slot — существующие `models.image_*`; cache по provider+base_url+model.
- **Q6 (task_jobs для durable pipeline):** §3.11/§4.3 — REUSE `TaskSupervisor`/`TaskJobStore`(v14) + `mca_trace.start_run`/`mca_pipeline_runs`(v19) + `mca_events`(v15); state machine → task_jobs.status/reason_code/checkpoint_ref; provider task_id в payload.
- **Q7 (хранение без special-case):** §4.2 — PG `cover_style_profiles` (data-driven), `cover_style_issue_assignments` (PK profile+run); seeded row — обычная строка с `origin=seeded_example`; runtime без `if style=="medved_press"`.
- **Q8 (импорт extra_images):** §3.6 — sha256 → детерминированный `asset_id`, `INSERT ... ON CONFLICT DO NOTHING`, файл копируется в `var/cover_style_assets/`; повтор — no-op; `extra_images/*` не мутируются.
- **Q9 (Connections redirect/возврат):** §3.9 — deep-link на существующий экран `llm_providers` с фокусом на группу `models_images`/`Обработка стилей обложки`; сохранение контекста редактора через hash/state.
- **Q10 (existing fallbacks):** §3.4/§2.2 — REUSE `_publish_rich_document`/`_plain_fallback`/`_send_rich_with_retry`/`_send_text_with_retry` и коды `*_FAILED`; **добавить** degraded-режим Rich-without-cover; второй publication pipeline не создаётся.

### 11.2. Derived D1–D8

- **D1 (DDL-конфликт) — РЕШЕНИЕ: вариант (b).** Δ DDL SQLite **= 0**; Style Registry/counters/issues/revision/provenance — в **PG** (идемпотентный `DDL_STATEMENTS`, прецедент A5 `image_reservation`). `mca-04b` сохраняет **v20**; **AMEND ADR-1027-9 D13 НЕ требуется**; правка `mca-round1027-arch-frames.md` §1.2.4/§1.2.5 **НЕ требуется**. Обоснование — ADR-1028-4 D1.
- **D2 (capability sources):** §3.7 — runtime discovery endpoint (уровень 2) как primary; developer override (уровень 1, env, аварийный) для локальных/self-hosted; если discovery недоступен — verified registry (уровень 4) или conservative `unknown` (уровень 5). Оформление override — env-JSON/CSV по `provider+base_url+model` (не UI-настройка).
- **D3 (размеры/лимиты prompt):** `prompt_limit.source=provider_or_registry|internal_config|unknown`; для текущего API — `internal_config` (500/1000) / `unknown`; unit support `chars/tokens/bytes/unknown`; `supported_sizes` — из discovery `resolutions`; **tokenizer нужен только** когда `unit=tokens` (иначе — явный отказ от грубого пересчёта).
- **D4 (async-провайдеры):** текущий image-контракт **sync**; для async — mapping на `task_jobs`(v14)/`mca_pipeline_runs`(v19) lifecycle + provider `task_id` в payload; deadline/polling — provider-aware; `mca-17a` lifecycle REUSE.
- **D5 (хранилище Registry):** **PG** (см. D1) + durable файлы для asset-байтов; issue assignment/revision/provenance — PG.
- **D6 (kill-switch / Δ каталога):** kill-switch **env-only** `COVER_STYLES_ENABLED` (Δ=0 для kill-switch); connection-slot ключи и per-chat selection — **+4** (см. §4.1, санкция). Отдельные per-style toggle-ключи в каталоге **не** вводятся (per-style `enabled` — поле Registry).
- **D7 (seed-имя):** seed импортируется по **фактическим** именам: `medved_press.png`, `style_example_01.png`, `style_example_02.**jpg**`. Литерал `.png` в §7/§9/§59/§77 — расхождение; см. DC-1.
- **D8 (counter init):** **OWNER-DECISION** (см. §13 DC-2) — не выдумывать; зафиксировать явное значение либо configurable initial до production seed.

---

## 12. Risk

**Risk-Level: R3.** Обоснование: обязательный прод-деплой; PG-DDL; изменение публикационного пути Summary (degraded Rich-without-cover); новые внешние зависимости (image-edit API); кросс-фичевая DDL-развилка.

- **Что повысит риск:** если потребуется SQLite-миграция (тогда снова коллизия v20 с mca-04b); если async-провайдер потребует изменения `task_jobs`-схемы; если изменится hot-path base cover без parity-тестов; если Style Edit станет mandatory.
- **Что понизит:** доказанная parity no-style (§90), capability-gated edit (модель без edit просто не вызывает API), Δ SQLite=0, env kill-switch.

---

## 13. Sanctions (итог для @Orchestrator/@PM)

| Область | Санкция |
|---|---|
| **SQLite Δ DDL** | **0** (`user_version` остаётся **19**); `mca-04b` сохраняет **v20** |
| **PG Δ DDL** | **≠ 0** — 5 таблиц (`cover_style_profiles`, `cover_style_references`, `cover_style_assets`, `cover_style_issue_assignments`, `cover_style_provenance`) + индексы, идемпотентно через `DDL_STATEMENTS` (прецедент A5) |
| **Δ каталога** | **+4** ParamSpec (3 connection + 1 per-chat selection); GROUPS/TAB_BY_GROUP/TAB_RULES — без роста |
| **F8 числа** | от **484/424/459/105/103/21** → **488/427/463/105/103/21** (delta 73→77) + переиздание артефактов |
| **AMEND ADR-1027-9 D13** | **НЕ требуется** |
| **`mca-round1027-arch-frames.md`** | **НЕ правится** |
| **Kill-switch** | `COVER_STYLES_ENABLED` (env-only, default ON) |
| **Deploy** | обязательный прод-деплой; bump `2.58.38 → 2.58.39` |

---

## 14. Deviations / items для @PM (consistency gate)

- **DC-1 (seed-имя, D7).** §7/§9/§59/§77 называют `style_example_02.png`; фактический файл — **`style_example_02.jpg`** (385 055 B). **Требуется правка формулировок в `tasks.md`** (T-4099/T-4106/T-4180): seed и browser-acceptance используют фактическое имя. Spec зафиксировал `.jpg`.
- **DC-2 (counter init, D8).** Начальное значение seeded counter — **решение владельца**; не выводить из `43/44`. До seed: configurable initial (default `0` или явное). **OPEN OWNER-DECISION** — см. §15.
- **DC-3 (`RichMessage without cover`).** Требуется **аддитивное** изменение `_publish_rich_document` (пропуск `media`/cover-блока) под gate; это задача **T-4145** — уточнить, что она меняет контур публикации (не только «проверить»).
- **DC-4 (стиль-провайдер).** Текущий код-дефолт (Pollinations/flux) **не** умеет image-edit; для реального Style Edit владельцу нужен edit-capable provider (напр. NanoGPT Qwen Image) в Connections. Без него Style stage даёт §38-ошибку и публикуется base. **Продуктовый факт** — вынести в отчёт §101; не блокирует код.
- **DC-5 (per-chat selection).** Реестр — глобальный; **выбор стиля** — per-chat (`prompts.summary_cover_style_id`). Если PM предполагал global selection — уточнить (влияет на Δ каталога и UI).
- **DC-6 (asset storage).** §8 говорит «существующее media/assets storage» — такого durable asset-регистра в коде **нет** (есть `media_share` TTL-шаринг). Spec вводит новый durable asset-регистр (PG-метаданные + файлы на диске). Формулировку §8 в tasks.md уточнить.
- **DC-7 (Qwen limits).** Подтверждено: edit, ≤3 reference images, 30 MB route. `800 chars` — **не** API-limit; из каталога не исходит. Задачи T-4096/T-4097 закрыты фактами §2.3 (при смене провайдера — перепроверить discovery).

---

## 15. Вопросы владельцу (owner-decision)

- **ARCHITECT_DECISION_REQUIRED EXTRA-D8-counter-start.** Начальное значение issue-counter для seeded `Графический роман Медведь Press`: (a) `0`/`1` (следующий выпуск — `ВЫПУСК 1`/`ВЫПУСК 01`); (b) явное число от владельца (напр. продолжить с `47`); (c) не задавать (configurable, остаётся пустым до ручного ввода). Влияет только на первый выпуск; не блокирует код/деплой (задаётся до production seed). — Отдельного блокирующего дизайн-решения нет; остальные развилки разрешены кодом/факт-контрактом.

---

## 16. Handoff

- **Артефакты:** этот `spec.md` + `adr-1028-4-cover-style-pipeline.md`.
- **Следующий шаг:** @Orchestrator → домен-консистентность @PM (учесть DC-1…DC-7 + D8) → Step 3 @Builder.
- **Никаких изменений кода/схем в этой фазе.**
