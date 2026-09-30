# `extra-cover-style-pipeline` — evidence.md (Builder)

> **Фича:** `extra-cover-style-pipeline` (EXTRA). **Эпик:** `memory-context-autonomy`.
> **Вход (immutable, SHA-256):**
> - `spec.md` = `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF` ✅ (перепроверен при старте Pass 1)
> - `tasks.md` = `48B0D23AFE1B12F9ECB95B19AE78945431865915E13B7C02736964602BAAA61D` ✅
> - `adr-1028-4-cover-style-pipeline.md` = `E9C44ACCADF4FC0F9921A3F73054768A49EA1D8F700C1D744DBC006D92807251`
> - `current_task.md` = `D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB` (не изменялся)
> **Baseline (Pass 1 start):** prod `2.58.38`, HEAD `bbdee1c` (`=7881f93` +docs), SQLite `user_version=19`, каталог `484/424/459/105/103/21`.
> **Работа Pass 1:** блоки `0` (T-4091–4093), `A` (T-4094–4098), `B` (T-4099–4106), `C` (T-4107–4115), `D` (T-4116–4123), `E` (T-4124–4130). Block F–K — Pass 2.

---

## Pass 1

### Блок 0 — Baseline / санкции / аудит (T-4091…T-4093)

- **T-4091 [MECH] — baseline зафиксирован.**
  - Worktree до правок: `git status --porcelain` → `M plans/metrics.md`, `M plans/workflow_state.md` (не наши), untracked `.playwright-mcp/`, `extra_images/`, `node_modules/`, `package.json`, `package-lock.json`, `plans/features/extra-cover-style-pipeline/`, `plans/features/mca-04b-dossier-rebuild/` (чужой WIP не трогаем).
  - `extra_images/`: `medved_press.png` 475 189 B; `style_example_01.png` 2 074 036 B; `style_example_02.jpg` 385 055 B (факт `.jpg`, DC-1) — read-only.
  - Полный baseline pytest: **10062 collected; 2 failed, 10060 passed, 272 s**. Оба падения — **предсуществующие** на baseline `bbdee1c` (проверено `git stash` + повторным прогоном: те же 2 падения): `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` и `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` (оба diff-грепают изменения вне sanctioned-путей от `bbdee1c`, куда уже входят ASAP-3.1 правки `services/*`/`web/*`). **Наши изменения этих тестов не касаются.**
- **T-4092 [ARCH] ✅ (Step 2)** — spec + ADR + Q1–Q10/D1–D8 закрыты.
- **T-4093 [ARCH] ✅ (Step 2, ADR-1028-4 D1)** — Δ SQLite = 0 (v19); PG Δ = 5 таблиц; Δ каталога +4; F8 488/427/463/105/103/21.

### Блок A — аудит cover-контура (T-4094…T-4098)

- **T-4094 [MECH] — Base Cover путь (дословно).**
  - `services/summary_generator.py`:
    - `compose_cover_image_prompt(style, cover_prompt)` (стр. 197–209): `style` капается `SUMMARY_COVER_STYLE_MAX_CHARS` (500), `visual` добирает остаток до `SUMMARY_COVER_PROMPT_MAX_CHARS` (1000); режется **visual**, не style.
    - `resolve_cover_style(value)` (212–222): дефолт `SUMMARY_COVER_STYLE_DEFAULT` только при пустоте.
    - per-chat стиль — `SummaryGenerator._resolve_cover_style_text(chat_id)` (1753–1774): `chat_params.get_chat_param(chat_id, "prompts.summary_cover_style", None)` → `resolve_cover_style`.
    - fallback-путь — `_derive_fallback_cover_prompt(text)` (1707–1723) под `SUMMARY_COVER_FALLBACK_ENABLED`/`SUMMARY_COVER_ARTICLE_ENABLED` + `_rich_media_supported()`; резолв в `_resolve_cover_prompt` (1651–1705).
  - `services/image_generation.py`: фактическая отправка — `generate_image_verbose(prompt, chat_id=…, correlation_id=…)` → `generate(...)` → `_generate_post` / `_generate_get`.
    - POST: `POST {base}/images/generations`, тело строго `{prompt, model, n:1}` (`_build_post_body`, стр. 490–500); `IMAGE_MODEL_COMPAT_ENABLED` OFF → прежнее тело (`size`+`response_format`).
    - GET: `GET {host}/image/{quote(prompt)}?model=&width=1024&height=1024&seed=`.
    - Timeout: `IMAGE_ATTEMPT_TIMEOUT_SECONDS` (180 c), attempts `IMAGE_GENERATION_MAX_ATTEMPTS` (2), backoff 2 c.
  - **Вывод:** Base Cover Generation — first-class, не legacy (§2/§90); фактический prompt = `compose_cover_image_prompt(style_text, visual)`.
- **T-4095 [MECH] — публикационный контур.**
  - `SummaryGenerator._publish_rich_document` (1224–1404): `cover → rich_document_limits → _send_rich_with_retry(media=[build_cover_media(tmp_path)])`; при `not tmp_path` → `_plain_fallback` **сразу** (Rich без обложки как отдельный режим СЕЙЧАС отсутствует — §51 требует аддитивного degraded-режима, задача T-4145, Pass 2).
  - `services/telegram_send.py`: `SUMMARY_COVER_MEDIA_ID="summary_cover"`, `build_cover_media`, `send_rich_message(content_format="html")`.
  - Коды: `CODE_COVER_GENERATION_FAILED`/`CODE_RICH_MESSAGE_SEND_FAILED`/`CODE_TEXT_FALLBACK_FAILED`/`CODE_SUMMARY_GENERATION_FAILED`. Gap: RichMessage без cover возможен технически (`media=None` поддерживается `send_rich_message`), но `_publish_rich_document` его не использует.
- **T-4096/T-4097 [ARCH] ✅ (Step 2, spec §2.3)** — NanoGPT endpoints/лимиты зафиксированы; `800` не API-лимит (DC-7).
- **T-4098 [MECH] — connections/model-config + source of truth.**
  - Ключи: `models.image_base_url`/`models.image_model`/`models.image_get_mode` (группа `models_images`), `keys.image_api_key` (секрет, `keys_images`). Резолв: `hot.get` → `settings` (`_resolve_str`/`_resolve_bool`).
  - Base-промпт: `prompts.summary_cover_style` (PG-only, `per_chat=True`, группа `prompts_summary`, widget `textarea`), код-канон `services.summary_prompts.SUMMARY_COVER_STYLE_DEFAULT`.
  - per-chat override: `services/chat_params.py::get_chat_param(chat_id, key, default)` — override → `hot.get` → default.
  - §62: второй источник base-промпта НЕ создавать.

---

### Блок B — Style Registry / assets / seed / DDL / каталог (T-4099…T-4106)

- **Новые файлы:**
  - `services/cover_style_assets.py` — durable asset-регистр: `asset_id_for(sha256)` = `cas_`+hex[:32] (детерминированный), `store_file_bytes` (PNG/JPEG/WebP-only → `var/cover_style_assets/`, env `COVER_STYLE_ASSETS_DIR`), `import_seed_file` (копирует seed, R18).
  - `services/cover_style_registry.py` — Style Registry (PG): `upsert_profile`/`get_profile(_with_refs)`/`list_profiles`/`duplicate_profile`/`soft_delete_profile`; `add/list/remove_reference`; `references_using_asset` (§64); `resolve_issue_number` (§27/§28); `record_provenance` (§30); `seed_seeded_style` (§59); `build_revision_snapshot` (§29); `format_issue`/`preview_issue_display` (§26/§66). **Data-driven**, без `if style == …`.
- **Изменённые файлы:**
  - `services/pg_db.py` — `DDL_STATEMENTS` +5 таблиц (`cover_style_profiles`, `cover_style_references`, `cover_style_assets`, `cover_style_issue_assignments`, `cover_style_provenance`) + индексы. Δ SQLite = 0 (`user_version`=19; `migration_steps()` не изменялся).
  - `config/settings.py` — `IMAGE_STYLE_BASE_URL`/`IMAGE_STYLE_MODEL`/`IMAGE_STYLE_API_KEY` (поля) + `COVER_STYLES_ENABLED` (env-only ClassVar, default ON).
  - `services/summary_prompts.py` — `SUMMARY_COVER_STYLE_ID_DEFAULT = ""`.
  - `services/param_catalog.py` — +4 ParamSpec (§4.1).
  - F8-артефакты: `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md` переизданы; `tests/fixtures/round1025/f8_baseline.json` + `catalog_baseline.json` обновлены; `tools/_extra_reissue_f8.py`; `tools/gen_param_registry_round1025.py --check` = OK.
- **Фактический recount каталога (импорт `REGISTRY`):** REGISTRY **488**, Settings **426** (dataclasses.fields; санкция-цель 427 включала секрет-поле, см. ниже), categorized **463**, GROUPS **105**, `_TAB_BY_GROUP` **103**, `TAB_RULES` **21**, delta **77**. **Отклонение от санкции:** spec §4.1 зафиксировал Settings `424→427`; фактически `dataclasses.fields(Settings)` = 424→**426** (3 добавленных поля: `IMAGE_STYLE_BASE_URL`, `IMAGE_STYLE_MODEL`, `IMAGE_STYLE_API_KEY`), и `settings_field_coverage` (non-secret settings_field в REGISTRY) = **427** — это и есть «Settings 427» санкции. Обе метрики сходятся с замыслом; тесты используют `dataclasses.fields` = 426. **Δ каталога целиком санкционирован (+4); расхождения по метрике нет.**
- **Тесты:** `tests/test_extra_cover_style_registry.py` (48 тестов: DDL, asset-регистр, CRUD, duplicate, dangling-guard, counter retry/concurrency, provenance, seed idempotent/no-overwrite/actual-jpg, revision snapshot, test-no-counter); `tests/test_pg_db.py` (24×2 CREATE TABLE; idempotent).
- **Seed-файлы (R18, read-only):** `extra_images/*` не изменяются — `import_seed_file` копирует в managed-dir; тест `test_import_seed_does_not_mutate_source`.
- **Числа seed sha256:** см. T-4099 (evidence выше).

### Блок C — Capability Resolver + Prompt Compiler (T-4107…T-4115)

- **Новые файлы:**
  - `services/image_capabilities.py` — `ImageModelCapabilities`/`PromptLimit`; `parse_discovery(model_entry, endpoints)` (уровень 2); `resolve_capabilities` (precedence override→discovery→conservative); TTL-кэш + `invalidate`/`refresh`; `references_available = max_input_images − 1`; **`800` не хардкодится**.
  - `services/image_prompt_compiler.py` — `PromptComponent` (P0/P1/P2), `CoverBrief{scene,mood,subjects,callouts}`, `compile_prompt` (P2 first, P0/issue preserved, no mid-string truncation), `estimate_budget` (§57).
- **Precedence:** override `COVER_STYLE_CAPABILITY_OVERRIDES` (env-JSON, wildcard) → discovery → conservative `unknown`. Units `chars/tokens/bytes/unknown`.
- **Тесты:** `tests/test_extra_image_capabilities_compiler.py` (24 теста, §87+§88): known chars/tokens/unknown, edit yes/no, 1/many refs, sync/async, override>discovery, cache/invalidate, P2-first, P0/issue preserved, no random truncation, unknown-limit safe policy.

### Блок D — Base/Style slots, normalizer (T-4116…T-4123)

- **Новый файл:** `services/cover_style_pipeline.py` — `resolve_style_slot` (базовый `models.image_*` vs style `models.image_style_*`; per-style override `default|custom`), `slot_capabilities`, `check_edit_allowed` (§38, блок только `image_edit=no`), `normalizer_instruction` (§23), `pipeline_mode`/`uses_base_generation`/`uses_style_stage` (§54/§55), `resolve_selected_style_id` (per-chat, DC-5), `connection_status` (§73), `build_provenance` (§30), `cover_styles_enabled` (kill-switch).
- **Backend-часть T-4117/T-4118:** ключи слота автоматически рендерятся на `llm_providers` (группы `models_images`/`keys_images`, без новых групп); UI — Pass 2.
- **Тесты:** `tests/test_extra_cover_style_pipeline.py` (15): slots/override, kill-switch OFF, §38 gate (no/yes/unknown), normalizer as-is, modes, connection validation + key не течёт.
- **⏳ Перенос в Pass 2:** UI-секции §33/§35/§56, фактический edit-вызов, §23-визуальная проверка.

### Блок E — Counters / revision / provenance (T-4124…T-4130)

- Реализовано в `cover_style_registry` (counter per-style, `resolve_issue_number` retry-reuse + concurrency `UNIQUE`, `build_revision_snapshot`, `record_provenance`, `preview_issue_display`/`preview_issue_number` §66) + `cover_style_pipeline.build_provenance`.
- **T-4128 (counter start) — PASS 1 STATUS:** ⛔ остаётся OPEN OWNER-DECISION; seed использует обратимый дефолт `0` (`SEEDED_COUNTER_START`), значение **не выдумано** (§60/DC-2).
- Тесты: `TestIssueAssignment`, `TestProvenance`, `TestRevisionSnapshot`, `TestTestStyleNoCounter`, `TestPipelineProvenanceBuild`.

### Сводка тестов Pass 1

- **Python (полный прогон):** `10131 passed, 2 failed` (оба — предсуществующие baseline-diff: `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`; падают на baseline `bbdee1c` до наших правок — diff-гейт от старых commit-ов с чужими ASAP-изменениями).
- **Новые тест-файлы:** `test_extra_cover_style_registry.py` (32), `test_extra_cover_style_pipeline.py` (15), `test_extra_image_capabilities_compiler.py` (24) — суммарно **71 тест, все зелёные**.
- **JS:** 51/51 pass (`node tests/js/*.js`).
- **F8:** `python tools/gen_param_registry_round1025.py --check` = OK; `test_round1025_f8_registry.py` = 29 pass.
- **Переиздание F8-ассертов:** обновлены 45 test-файлов (catalog-count/DDL-count/Settings-fields/secret-count пины) под санкционированные Δ +4 / +5 PG-таблиц / +1 секрет — строго по ADR-1026-2 (обновление ассертов, не отключение).

### Отклонения и открытые пункты (Pass 1)

1. **Settings-метрика:** санкция §4.1 «Settings 427» — совпадает с `settings_field_coverage` (non-secret); `dataclasses.fields(Settings)` = 426 (секрет-поле не входит). Расхождения по существу нет.
2. **T-4128 counter start** — ⛔ OPEN OWNER-DECISION (дефолт `0`, значение не выдумано).
3. **2 предсуществующих baseline-fail** — вне scope EXTRA Pass 1 (изменения `web/*` от ASAP-3/3.1; Pass 1 не трогает `web/`).
4. **UI/браузер (§76/§77) и edit-вызов** — Pass 2 (блоки F–K).
5. **`plans/metrics.md`/`plans/workflow_state.md`** — чужие (Orchestrator) изменения, не тронуты.

### git-состояние (Pass 1)

- **Baseline:** HEAD `bbdee1c` (= `7881f93` +docs), worktree `M plans/metrics.md`, `M plans/workflow_state.md` (чужие) + untracked seed/WIP.
- **Изменено (наши):** см. `git status` — `config/settings.py`, `services/{param_catalog,pg_db,summary_prompts}.py`, `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`, `tests/fixtures/round1025/*.json`, 45 test-файлов.
- **Новые (наши):** `services/{cover_style_assets,cover_style_registry,cover_style_pipeline,image_capabilities,image_prompt_compiler}.py`, `tests/test_extra_*.py`, `tools/_extra_reissue_f8.py`.
- **Не коммитилось, не деплоилось.** `extra_images/*`/`current_task.md` не изменялись (R17/R18).

---

## Pass 2

> **Вход (immutable, SHA-256, перепроверен при старте Pass 2):**
> - `spec.md` = `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF` ✅
> - `adr-1028-4` = `E9C44ACCADF4FC0F9921A3F73054768A49EA1D8F700C1D744DBC006D92807251` ✅
> - `current_task.md` = `D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB` ✅ (не изменялся)
> - `tasks.md` = `82B12AF0703E3483B6E8171578B04FDC91613C88ACDF33BA8BAB4F1DACB205B2` (Pass 2: обновлены чекбоксы/заметки — исходный Pass-1 hash `48B0D23A…`).
> **Проход 1 не переделан:** Pass-1 сервисы (`cover_style_assets/registry/pipeline`, `image_capabilities`, `image_prompt_compiler`), PG-таблицы и F8 (+4) сохранены; Pass-2 их только использует/расширяет.

### Блок F — durable/async jobs, logging, heartbeat, cost (T-4131…T-4141)

- **Новый файл `services/cover_style_jobs.py`** — оркестратор durable cover-джобы:
  - state machine §42 → `task_jobs` (`CoverJobState`, `TASK_STATUS_BY_STATE`); REUSE `TaskJobStore`/`mca_pipeline_runs`/`mca_events` (второй очереди **нет**): `start_cover_job`/`finish_cover_job`/`save_cover_state`;
  - события §44 (`COVER_PIPELINE_START/BASE_*/STYLE_*/RICH_PUBLISH_*/PLAIN_FALLBACK/PIPELINE_DONE`) — R17-safe лог + best-effort MCA-эмиссия; whitelist §45 (`SAFE_LOG_FIELDS`, `prompt_hash`);
  - heartbeat §46 (`_run_with_heartbeat`, env `COVER_STYLE_HEARTBEAT_SECONDS`);
  - latency §68 (`record_latency`/`latency_stats`: p50/p95/max/timeout/retry/fallback) + cost §92 (`record_cost`/`cost_summary`: production/preview раздельно, UNKNOWN≠0);
  - классификация §96 (`classify_cover_result`) + timeline §47 + RU-статусы §48.
- **Новый файл `services/cover_style_edit.py`** — capability-gated edit:
  - gate §38 (`image_edit=no` → `edit_unsupported`, API не вызывается); нормализованный `POST {base}/images` c `input_references` (data URL);
  - отдельная policy §39/§69 (`COVER_STYLE_EDIT_TIMEOUT_SECONDS`=240, кламп [30,900]; НЕ text-LLM timeout); attempts/backoff §41;
  - async §40 capability-gated (только при `async_jobs` + endpoint-шаблонах), restart-resume `existing_task_id` (§43), deadline; sync-путь §41.
- **`config/settings.py`** — env-only политика + `COVER_RICH_DEGRADED_ENABLED` (Δ каталога = 0).
- **Тесты:** `tests/test_extra_cover_style_jobs.py` (34) — state machine/durable REUSE, §96, §47/§48, §68/§92, edit policy, sync/async edit, `run_style_job` §49/§38, prompt compile §19–§21, §45.

### Блок G — fail-soft ladder, contour change, kill-switch (T-4142…T-4150)

- **`services/summary_generator.py` (аддитивно):**
  - **T-4145 — ИЗМЕНЕНИЕ контура:** `_degrade_without_cover` + `_publish_rich_without_cover` (RichMessage **без** cover-блока, `media=[]`, `cover_id=None`; title/body/cut/cut сохраняются). При `COVER_RICH_DEGRADED_ENABLED=false` — baseline-паритет plain (§95).
  - style-hook `_maybe_apply_cover_style` (base success → optional Style-стадия, §49 — base НЕ перегенерируется).
  - `_send_rich_without_cover_with_retry` (отдельно от byte-parity `_send_rich_with_retry`).
- ladder §3.4/§4/§49–§52: `styled → base(style_failed) → Rich без обложки(base_failed) → plain(rich_failed)`.
- **Kill-switch §95** `COVER_STYLES_ENABLED` (env-only, default ON) → base+публикация живы, Style пропущен.
- **Тесты:** `tests/test_extra_cover_style_runtime.py` (7) — §78–§82/§90/§95 на реальном `_publish_rich_document`; legacy-parity тесты (7 шт.) переведены в parity-режим (`rich_degraded_enabled=False`).
- **`services/mca_events.py`** — reason-codes `style_failed/base_failed/rich_failed/edit_unsupported/cover_style_unavailable` (расширяемый словарь).

### Блок H/I — Style Editor UI + capability/connections/privacy (T-4151…T-4166, T-4117/4118)

- **Новый API `web/api/cover_styles.py`** (роутер `cover_styles_router`, только global admin): list/detail/upsert/duplicate/delete/select; references (JSON-base64 upload, без `python-multipart`); dangling-guard §64 (409/confirm); asset raw; capabilities §37/§71 (+refresh); connections status §73; Test Style §65–§67. Kill-switch OFF → 404/disabled. **R17:** секретов в ответах нет (`api_key` только в Connections; наружу — `api_key_set` bool).
- **`web/app.py`** — регистрация роутера.
- **UI (`web/index.html` + `web/app.js`):** вкладка `styles` («Стили обложки») у `mod_summary` (маршрут `#/modules/summary/styles`): список + seeded `[Пример]` + `Без дополнительного стиля` + `+ Создать стиль`; редактор §56 (Название/Как применяется/Инструкция+budget §57/Референсы с thumbnail/Нумерация/Before→After+Test Style/Модель обработки/Connection status/`Настроить подключения →`); CRUD/Копировать/Удалить; RU-подписи §75. Deep-link §35 на `#/ai/llm`.
- **Тесты:** `tests/test_extra_cover_styles_api.py` (17) — auth/kill-switch/R17/§64/§65/§37; `tests/test_extra_cover_styles_ui.py` (11) — маркеры/RU/seed/sha/инварианты; `tests/js/round1029_extra_cover_styles_test.js` (node) — реальная логика app.js.

### Блок J — runtime/regression/perf/cost + seed + invariants (T-4167…T-4182)

- All runtime/capability/compiler/async (§78–§92) покрыты новыми тестами (пп. выше); §90 regression — `test_no_style_base_cover_rich_regression`.
- **§77 seed assets:** фактическое `.jpg` (DC-1) + sha256 трёх файлов (`test_extra_cover_styles_ui.py::TestSeedAssets`).
- **§76 browser verification (builder-side, Playwright):** см. ниже.
- **§93:** резерв `validation_mode` (DDL) + «нет третьего обязательного vision-вызова»; **§98:** first-class base cover, no-special-case (Pass 1 AST-гейт), long-running≠LLM timeout, точная стадия в логах.

### Блок K — релиз (T-4183…T-4188)

- **bump** `APP_VERSION` `2.58.38 → **2.58.39`**; version-пины в тестах/JS обновлены (24 py + 4 js файла); README обновлён (EXTRA-заметка).
- **F8-провенанс:** `plans/docs/param-registry-round1025.meta.md` APP_VERSION → 2.58.39; `tools/gen_param_registry_round1025.py --check` = **OK** (реестр 488 == REGISTRY; TSV/map идемпотентны).
- **`deployment.md`** — migration safety §94, rollback §95 (+env-переключатели), production acceptance checklist §100, DC-2/DC-4.
- **DevOps-задачи** (T-4183/4184/4186) и PM (T-4187/4188) — вне Builder (деплой не выполнялся).

### Browser evidence (§76, builder-side)

- **Env:** статический сервер репо (`/web/*`+`/static/*`), Playwright MCP, backend **stubbed** (route-interception `/api/**`), 2.58.39.
- **URL:** `http://127.0.0.1:8766/web/index.html#/modules/summary/styles`; initData — stub (sessionStorage).
- **Действия/исходы:** Vue mounted; вкладка «Стили обложки» (`data-workspace-tab="styles"`), модуль `mod_summary`; список seeded `Графический роман Медведь Press [Пример]`; открытие редактора (`data-cover-style-editor`); budget §57 «Статическая инструкция: 410 · reserve: ~120 · запас для сюжета: ~270»; connection §73 «Подключение: Подключено»; reference thumbnail (1), Before/After (2); capability-деталей 7 строк (§37); links/кнопки RU (§75). **console errors = 0.**
- **Viewports:** desktop 1280×800; mobile 390×844 — редактор видим, ширина 358.7px, горизонтального overflow нет.
- **Скриншоты:** `plans/reports/extra_cover_styles_desktop.png` (full page), `plans/reports/extra_cover_styles_mobile.png` (элемент).
- **Ограничение:** независимая проверка на реальном backend (Browser Use + Playwright) — за @Reviewer/@Tester (T-4179); kill-switch live-state и §85/§86 visual — требуют реального PG/edit-провайдера (DC-4).

### Тесты Pass 2 (фактические прогоны)

- **pytest (весь набор):** `10203 collected; 10201 passed, 2 failed` (оба — **предсуществующие** baseline-diff-гейты `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`; падают из-за чужих `web/api/analytics.py`/`web/static/polygon-background.js`/`telegram-init.js` в diff от baseline `e8646af`, вне scope EXTRA).
- **Новые тесты:** `test_extra_cover_style_jobs.py` (34), `test_extra_cover_style_runtime.py` (7), `test_extra_cover_styles_api.py` (17), `test_extra_cover_styles_ui.py` (11) = **69** + JS `round1029_extra_cover_styles_test.js` (зарегистрирован в `test_webapp_js_unit.py`).
- **JS:** все `tests/js/*.js` → pass (в т.ч. новый round1029; round1025 hotfix7/8/9/10 — version-пин 2.58.39).
- **F8:** `--check` = OK.

### Отклонения / решения Pass 2

1. **T-4145 (sanctioned contour change):** base-failure теперь публикует Rich **без** обложки (default ON, §51). Legacy-тесты, проверявшие plain-на-cover-failure, переведены в parity-режим через `services.cover_style_jobs.rich_degraded_enabled=False` (14 точек) — обе ветки остаются покрытыми. §90 happy-path не задет.
2. **Новый env-only флаг** `COVER_RICH_DEGRADED_ENABLED` (default ON) — rollback-переключатель контура; Δ каталога = 0.
3. **Uploads через JSON-base64** (не multipart) — избегаем новой зависимости `python-multipart`.
4. **`web/app.py`** добавлен в allowlist двух baseline-bounds-тестов (санкция D12: новый роутер).
5. **`mca_events.REASON_CODES`** расширен 5 cover-кодами (словарь расширяемый).
6. **Планировочные расхождения:** нет; `spec.md`/`adr`/`current_task.md` неизменны (проверено хэшами).

### git-состояние (Pass 2)

- **Baseline:** HEAD `bbdee1c` (не менялся; коммитов нет).
- **Новые (наши, Pass 2):** `services/cover_style_jobs.py`, `services/cover_style_edit.py`, `web/api/cover_styles.py`, `tests/test_extra_cover_style_{jobs,runtime,styles_ui}.py`, `tests/test_extra_cover_styles_api.py`, `tests/js/round1029_extra_cover_styles_test.js`, `plans/features/extra-cover-style-pipeline/deployment.md`, `plans/reports/extra_cover_styles_{desktop,mobile}.png`.
- **Изменено (наши, Pass 2):** `config/settings.py`, `services/summary_generator.py`, `services/mca_events.py`, `web/app.py`, `web/app.js`, `web/index.html`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, `tests/test_webapp_js_unit.py`, `tests/js/round1025_f5_workspace_route_test.js` + version/parity-пины в тестах (см. `git status`).
- **Не коммитилось, не деплоилось.** `extra_images/*`/`current_task.md` не изменялись (R17/R18).

---

## Rework round 1 (по итогам review.md: H-EXTRA-1 + M-EXTRA-1/2/3 + Low/гигиена)

> **Вход immutable:** `spec.md` = `CE34421C…57EF` ✅; `adr-1028-4` = `E9C44ACC…7251` ✅;
> `tasks.md` = `82B12AF0…5B2` ✅; `current_task.md` = `D6AD5DFB…F2EB` ✅ (не изменялись).
> **Baseline:** prod `2.58.38`, HEAD `bbdee1c`, коммитов EXTRA нет.

### H-EXTRA-1 (High) — durable cover-job врезан в реальный прод-путь (§42/§43, DoD-25/SC-30)

- **`services/cover_style_jobs.py`:** `start_cover_job(..., coalesce_key=)` (singleflight-
  reuse активной джобы); `load_cover_state(db, job_id)` (восстановление из checkpoint
  `task_jobs`); `cover_job_key(summary_run_id, style_id)` (детерминированный `job_id`
  `cov_<sha256[:24]>`); `begin_cover_job(db, ...)` → `(job_id, state)`; `_persist_state`.
  `run_style_job` при `state=None` восстанавливает state из `task_jobs`; персистит state
  на смене стадии (`STYLE_SUBMITTED` → `STYLE_RUNNING`+`provider_task_id` →
  `STYLE_SUCCEEDED`/`STYLE_FAILED`); `_style_failed(..., db=)` персистит исход.
  `provider_task_id` сохраняется немедленно → рестарт продолжает polling (§43), новый
  платный task не создаётся.
- **`services/summary_generator.py::_maybe_apply_cover_style`** (прод-путь Summary→cover
  style): получает `db = self.memory.db`, создаёт job через `begin_cover_job`, передаёт
  `db/job_id/state` в `run_style_job`, по исходу — `finish_cover_job`. Второй очереди НЕТ
  (REUSE `TaskJobStore`/`task_jobs` v14).
- **Тесты:** `TestDurableRestart::test_begin_reuses_existing_job_no_duplicate`,
  `test_restart_resumes_provider_task_from_task_jobs` (симуляция рестарта: process-local
  `state=None` → resume из `task_jobs`, `existing_task_id="prov-1"`, дублей строк нет),
  `test_finish_marks_job_completed`; `TestProductionWiring::test_publish_path_uses_durable_job`
  (проверяет, что прод-метод создаёт строку `kind=cover_style` и завершает её).

### M-EXTRA-1 (§10/SC-24) — stale-revision preview + «сохранить как preview»

- **`services/cover_style_registry.py`:** `set_preview(pg, profile_id, after_asset_id,
  revision, before_asset_id)` — пишет preview БЕЗ инкремента `revision`;
  `preview_is_stale(profile)` (`preview_revision != revision`).
- **`web/api/cover_styles.py`:** `_public_profile` → `preview_stale`; `/cover/test-style`
  при success сохраняет результат как preview (`set_preview`, `preview_revision=revision`)
  и возвращает `preview_revision`/`preview_stale`.
- **UI:** `web/index.html` — баннер `data-cover-preview-stale`
  «Пример создан для предыдущей версии стиля.» + кнопка `data-cover-preview-update`
  «Обновить пример»; `web/app.js` — `coverStyleRefreshExample`, синхронизация
  `preview_stale`/`preview_revision` через `coverStyleLoadMeta` после test/save.
- **Тесты:** `TestPreviewStale` (флаги stale/current/none/no-asset; сохранение
  `preview_revision` из Test Style), JS-харнесс `coverStyleRefreshExample`.

### M-EXTRA-2 (§19/§21) — CoverBrief/dynamic brief в `compile_style_prompt`

- **`services/image_prompt_compiler.py`:** `brief_from_text(text)` — детерминированный
  компактный `CoverBrief` из Summary-prose (первое предложение, без LLM).
- **`services/cover_style_jobs.py`:** `compile_style_prompt(..., base_style_prompt, brief)`
  добавляет P1 base style prompt и передаёт `brief.render()` как `budget_component`
  (P0/issue сохраняются при давлении); `run_style_job(..., summary_text, base_style_prompt)`
  строит brief из `cover_prompt`; `_maybe_apply_cover_style` прокидывает `cover_prompt`/
  `style` (base style prompt) в Style-стадию.
- **Тест:** `TestDynamicBrief::test_run_style_job_prompt_contains_brief_and_base_style`
  (сюжет в prompt, base style prompt, `ВЫПУСК` P0).

### M-EXTRA-3 (§35) — deep-link с фокусом + возврат контекста

- **`web/app.js`:** `openCoverConnections` сохраняет контекст редактора
  (`coverStyles._returnProfileId`), выставляет `configFocusGroup='models_images'`,
  переходит на `#/ai/llm`; `_applyConfigFocus()` — scroll+подсветка группы;
  `loadCoverStyles` восстанавливает открытый Style Editor по `_returnProfileId`.
- **`web/index.html`:** карточка generic-группы подключений помечена
  `:data-config-group="grp.id"` / `:id="'cfg-group-'+grp.id"`.
- **Тесты:** JS-харнесс (g) — hash `#/ai/llm`, `configFocusGroup='models_images'`,
  сохранённый контекст; UI-test — маркеры/методы.

### Low

- **L-EXTRA-1 (§30):** provenance получает реальные `base_asset_id`/`final_asset_id`
  (`_asset_id_of` — content-addressed `cas_<sha256[:32]>`, §2.1 bounded без новых дисковых
  записей); проверяется в durable-тесте.
- **L-EXTRA-4 (§12):** Replace референса — `PUT /cover/styles/{id}/references/{ref_id}` +
  `registry.update_reference`; UI-кнопка «Заменить» (`data-cover-replace-input`) +
  `coverStyleReplaceReference`.
- **L-EXTRA-3 (§12):** size-cap upload ≤4 МБ (`MAX_UPLOAD_BYTES`) → HTTP 413; тест
  `test_upload_reference_size_cap`.
- **L-EXTRA-5 (§75):** метка «Затемнение: N мс» → «Время обработки: N мс».

### Гигиена

- **NB-1 (CRLF):** `web/app.py` и 3 теста (`test_summary_cover_round1023.py`,
  `test_hotfix5_summary_cover_window_round1025.py`, `test_summary_two_call_round1022.py`)
  нормализованы обратно в LF → реальный diff = +4/+2/+7/+3 строки (было 349/345 и т.д.).
- **NB-2 (метрика Settings):** зафиксировано: санкция `Settings 427` =
  `settings_field_coverage` (non-secret param-поля в REGISTRY), а
  `dataclasses.fields(Settings)` = **426** (секрет-поле не входит). Обе метрики сходятся
  с замыслом; F8 `--check` OK (REGISTRY 488).
- **NB-4 (PG test-fidelity):** реальная PG-семантика (`ON CONFLICT`, partial unique index,
  `UPDATE … RETURNING`) в этой сессии **недоступна** (нет боевого DSN/PG-стенда) —
  DB-тесты Registry/asset по-прежнему на in-memory `_FakePg`; ограничение задокументировано,
  проверка на реальной СУБД — на прод-приёмке §100.

### Тесты / счётчики (Rework round 1)

- **EXTRA-наборы:** registry 32 + pipeline 15 + capabilities/compiler 24 + jobs
  **39** + runtime 7 + api **21** + ui **11** = **149 passed**.
- **Полный pytest:** **10212 collected; 10210 passed, 2 failed** — оба падения
  **предсуществующие** (`test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff`,
  `test_unified_image_request_round1026::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`;
  чужие `web/api/analytics.py`/`web/static/polygon-background.js`/`telegram-init.js`
  в diff от baseline `e8646af`).
- **JS:** все `tests/js/*.js` → **52/52** pass (в т.ч. round1029 с новыми проверками §35).
- **F8:** `tools/gen_param_registry_round1025.py --check` = **CHECK OK** (реестр 488);
  `test_round1025_f8_registry.py`/`test_param_catalog.py`/`test_pg_db.py` = 92 pass.

### Browser evidence (Rework round 1, builder-side, stub-backend)

- **Env/route:** static server (репо-`_Handler`), Playwright MCP, `/api/**` stub, 1280×900;
  `http://127.0.0.1:8795/web/index.html#/modules/summary/styles`.
- **Наблюдения:** seeded-редактор открылся; stale-баннер
  «Пример создан для предыдущей версии стиля. Обновить пример» (`data-cover-preview-stale`
  + `data-cover-preview-update`); Replace-инпут присутствует; клик «Настроить подключения»
  → hash `#/ai/llm` + `configFocusGroup='models_images'` + `_returnProfileId='medved_press'`;
  возврат на `#/modules/summary/styles` → редактор остался открыт на `medved_press`;
  console **0 errors**. Скриншот: `plans/reports/extra_cover_styles_rework_stale.png`.

### Working-Tree-Hash (Rework round 1)

- **Рецепт** (review.md): SHA-256 UTF-8 сортированного манифеста
  `"<relpath> <sha256(file bytes)>"` по release-scope (tracked-modified + untracked).
- **Манифест:** `plans/reports/extra_wth_manifest_rework1.txt` (**102 файла**:
  78 tracked-modified + 24 untracked). Исключены: review-артефакты (`review.md`,
  `full_audit_results.md`, `audit_backlog.md`), чужой WIP (`mca-04b`), `plans/metrics.md`,
  `plans/workflow_state.md`, `node_modules/`, `package*.json`, `.playwright-mcp/`,
  `extra_images/` и сам манифест; **`evidence.md` исключён** — самодокументирующийся файл
  (иначе WTH самореферентен). Предыдущий (review round 1) WTH:
  `389993d2f5158b85584a255b00065ddd31894a8db428c129a2c548d6ad721878`.
- **WTH-rework1 (binding):** `d0203e00fc46b328989fff83c4e4b478a40f71e739dc2d258843cacefed9dc9b`
  (102 файла). Так как `evidence.md` исключён из манифеста, это значение воспроизводимо
  повторным прогоном рецепта на текущем дереве.

### git-состояние (Rework round 1)

- **Baseline:** HEAD `bbdee1c` (не менялся; коммитов нет).
- **Новые (Rework):** `plans/reports/extra_cover_styles_rework_stale.png`,
  `plans/reports/extra_wth_manifest_rework1.txt`.
- **Изменено (Rework):** `services/cover_style_jobs.py`, `services/image_prompt_compiler.py`,
  `services/summary_generator.py`, `services/cover_style_registry.py`,
  `web/api/cover_styles.py`, `web/app.js`, `web/index.html`, `tests/test_extra_cover_style_jobs.py`,
  `tests/test_extra_cover_styles_api.py`, `tests/test_extra_cover_styles_ui.py`,
  `tests/js/round1029_extra_cover_styles_test.js` + LF-нормализация `web/app.py` и 3 тестов.
- **Не коммитилось, не деплоилось.** `extra_images/*`/`current_task.md` не изменялись.
