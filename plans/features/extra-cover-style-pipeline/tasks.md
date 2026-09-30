# `extra-cover-style-pipeline` — tasks.md (Step 1 @PM)

> **Фича:** `extra-cover-style-pipeline` (feature prefix `EXTRA`).
> **Эпик:** `memory-context-autonomy` (round 10.27+); очередь владельца: ASAP-3.1 ✅ → **EXTRA** → обязательный прод-деплой EXTRA → MCA-tasks.
> **Источник ТЗ:** `plans/current_task.md`, строки **9923–12024** — блок `# EXTRA — Modular Cover Styles / Branded Cover Pipeline` (§1–§102, ~2100 строк). Прочитан полностью (3 приёма Read). Файл **НЕ изменялся** (R17/R18): sha256 `D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB` (= `D6AD5DFB…F2EB`).
> **Baseline (Step 0, данность для планирования):** прод `2.58.38` (HEAD `7881f93`, `bbdee1c` — docs-архив ASAP-3.1); SQLite DDL **v19**; каталог **484/424/459/105/103/21** (подтверждён импортом `services.param_catalog.REGISTRY` = 484); генерация обложек **РАБОТАЕТ** (ASAP-2 / ASAP-2.1: cover на fallback-пути, prompt-ключ `prompts.summary_cover_style`, per-chat override через `SummaryGenerator._resolve_cover_style_text`, round1025-hotfix4).
> **Seed-ассеты уже в дереве (untracked, владельческие, read-only):** `extra_images/medved_press.png` (475 189 B), `extra_images/style_example_01.png` (2 074 036 B), `extra_images/style_example_02.jpg` (385 055 B). **Фактическое имя seed-файла — `style_example_02.jpg`** (DC-1; spec §3.6/§14 зафиксировал `.jpg`) — seed/acceptance используют литерал `.jpg` (T-4099/T-4106/T-4180).
> **Инварианты:** не переписывать работающую генерацию (ASAP-2.1 §34); R17 (секреты только маскированно/Connections); **Standard Base Cover Generation — first-class модуль, НЕ legacy** (§2, §98); Δ каталога / Δ DDL — только по санкции @Architect; атомарность «эталон+код+тесты»; `plans/current_task.md` и `extra_images/*` не трогать байт-в-байт (R17/R18).
> **Санкции @Architect (spec §13 / ADR-1028-4):** Δ DDL SQLite = **0** (`user_version` остаётся **19**; `mca-04b` сохраняет **v20**; **AMEND ADR-1027-9 D13 НЕ требуется**; `plans/docs/mca-round1027-arch-frames.md` **не правится**); Δ PG DDL **≠0** — **5 таблиц** (`cover_style_profiles`/`cover_style_references`/`cover_style_assets`/`cover_style_issue_assignments`/`cover_style_provenance`) + индексы, идемпотентно через `services/pg_db.py::DDL_STATEMENTS` (прецедент A5 `image_reservation`); Δ каталога **+4** ParamSpec (3 connection + 1 per-chat selection) → F8 **484/424/459/105/103/21 → 488/427/463/105/103/21** (атомарное переиздание, ADR-1026-2); kill-switch **`COVER_STYLES_ENABLED`** (env-only, default **ON**); durable jobs/telemetry — **REUSE** `task_jobs`/`mca_pipeline_runs`/`mca_events` (**второй очереди нет**); bump `2.58.38` → **`2.58.39`**.
> **Только планирование:** код/коммиты в этом шаге не создаются.
> **Risk:** **R3** (spec §12; подтверждён @Architect: обязательный прод-деплой, PG-DDL, аддитивное изменение публикационного пути Summary (degraded Rich-without-cover), внешняя image-edit зависимость, кросс-фичевая DDL-развилка).
> **Deploy:** **обязательный прод-деплой** после @Reviewer Approved и приёмки §100; bump `2.58.38` → `2.58.39`; rollback §95.

---

## Ревизия PM — consistency-gate (DC-1…DC-7 + санкции Step 2)

> **Дата:** Step 2.5 @PM (domain-consistency gate). **Вход (полные Get-FileHash):** `spec.md` = `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF`; `adr-1028-4-cover-style-pipeline.md` = `E9C44ACCADF4FC0F9921A3F73054768A49EA1D8F700C1D744DBC006D92807251`; `current_task.md` = `D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB` (**не изменялся**). **`extra_images/*` не трогать** (R18).
> **Вердикт:** **PLANNING_CONSISTENT** (handoff ниже).
> **Устранённые расхождения (spec §14):**
> - **DC-1** — seed-имя: факт **`style_example_02.jpg`** (не `.png`) → T-4099/T-4106/T-4180.
> - **DC-2/D8** — `counter start` — **открытое решение владельца**, значение НЕ выдумывать → T-4128 (owner-input required before production seed) + безопасный обратимый дефолт в деплое → T-4186.
> - **DC-3** — T-4145 = **ИЗМЕНЕНИЕ публикационного контура** (аддитивный degraded-режим «Rich без картинки»), а не «проверить».
> - **DC-4** — текущий code-default provider **не** умеет cover-edit → для реального стиля нужен **edit-capable provider** в Connections; предпосылка отражена в T-4163…T-4166 и T-4186 (base публикуется корректно и без него).
> - **DC-5** — реестр **глобальный**, **ВЫБОР стиля — per-chat** (`prompts.summary_cover_style_id`) → T-4100/T-4117/T-4151/T-4160.
> - **DC-6** — «существующего media/assets storage» в коде **нет** → spec вводит **новый durable asset-регистр** (PG-метаданные + файлы на диске) → T-4100/T-4101.
> - **DC-7** — `800` — **не** API-лимит (не хардкодить) → T-4097/T-4107/T-4154.

---

## Блок 0 — Baseline, spec/ADR, санкции (T-4091…T-4093)

- [x] **T-4091 [@Memory/@Orchestrator — подтверждение Step 0]** — **Цель:** зафиксировать baseline EXTRA (прод `2.58.38`, HEAD `7881f93`, SQLite v19, каталог 484/424/459/105/103/21, pytest/JS последнего verified, sha256 `current_task.md` = `D6AD5DFB…F2EB`, `extra_images/*` untracked/read-only) и точку отката. **Приёмка:** baseline согласован, вход §1–§102 доступен, `current_task.md`/`extra_images` не изменены (§94, §95). **Тег:** [MECH]. **Риск:** Low (процесс). **✅ Pass 1:** baseline зафиксирован в `evidence.md` (pytest 10062 collected / 2 предсуществующих fail; seed sha256; вход не изменён).
- [x] **T-4092 [@Architect — `spec.md` + ADR + ответы §97] — ✅ RESOLVED Step 2.** **Артефакты:** `spec.md` (sha256 `CE34421C…57EF`) + `adr-1028-4-cover-style-pipeline.md` (sha256 `E9C44ACC…7251`); Q1–Q10 §97 отвечены (spec §11.1), производные D1–D8 (spec §11.2). **Приёмка:** ✅ каждый §1–§102 имеет задачу/SC; границы §102 не сужены; REUSE зафиксирован (§4.3). **Тег:** [ARCH]. **Риск:** High. **Зависимости:** T-4091.
- [x] **T-4093 [@Architect — санкция Δ DDL + коллизия версий] — ✅ RESOLVED Step 2 (ADR-1028-4 D1/D5/D11).** **Решение — вариант (b):** Style Registry/references/assets/issue-assignment/revision/provenance живут в **PostgreSQL** (идемпотентный `DDL_STATEMENTS`: 5 таблиц + индексы); **Δ DDL SQLite = 0** (`user_version` остаётся **19**); `mca-04b` сохраняет **v20**; **AMEND ADR-1027-9 D13 НЕ требуется**; `plans/docs/mca-round1027-arch-frames.md` **не правится**. Δ каталога = **+4**. **Приёмка:** ✅ решение зафиксировано (spec §4/§13, ADR-1028-4 D1). **Тег:** [ARCH]. **Риск:** High. **Зависимости:** T-4092. См. раздел «DDL-оценка».

---

## Блок A — Аудит текущего cover-контура + Standard Base Cover (§1–§4, §15, §61–§62, §90, §97 Q1/Q2/Q10) (T-4094…T-4098)

- [x] **T-4094 [@Scanner/@Memory — аудит Base Cover Generation]** — **Цель:** дословно зафиксировать текущий путь базовой обложки: `services/summary_generator.py` (композиция cover-prompt: `_resolve_cover_style_text`/`resolve_cover_style`, капы `SUMMARY_COVER_STYLE_MAX_CHARS`=500 / `SUMMARY_COVER_PROMPT_MAX_CHARS`=1000, `_derive_fallback_cover_prompt`), `services/image_generation.py` (`generate_image`/`generate_image_verbose`, `IMAGE_MODEL_COMPAT_ENABLED`, `IMAGE_MODEL`), реальный отправляемый prompt. **Приёмка:** named файл/функция/строка + фактический prompt-контракт; подтверждение «Base Cover Generation — first-class, не legacy» (§2, §90, §97/Q1). **Тег:** [MECH]. **Риск:** Low. **✅ Pass 1:** аудит в `evidence.md` (файлы/функции/строки; prompt = `compose_cover_image_prompt(style, visual)` → `POST /images/generations` `{prompt,model,n:1}`).
- [x] **T-4095 [@Scanner/@Memory — аудит публикационного контура]** — **Цель:** зафиксировать лестницу публикации по факту: `summary_generator` → `services/telegram_send.py` (`send_rich_message`/`build_cover_media`/`SUMMARY_COVER_MEDIA_ID`) → plain `sendMessage`; возможен ли RichMessage **без** cover-блока; существующие коды (`SUMMARY_GENERATION_FAILED`/`COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED`). **Приёмка:** карта ladder §4/§51/§52 + gap-анализ «Rich без картинки» (§51, §97/Q10). **Тег:** [MECH]. **Риск:** Low. **✅ Pass 1:** аудит в `evidence.md`; gap подтверждён — `_publish_rich_document` при `not tmp_path` уходит в plain сразу, degraded Rich-without-cover отсутствует (T-4145, Pass 2).
- [x] **T-4096 [@Architect — реальные NanoGPT endpoints/contract] — ✅ RESOLVED Step 2 (spec §2.3).** **Результат:** generation `POST {base}/images/generations`; discovery `GET /api/v1/image-models?detailed=true` + `GET /api/v1/images/models/{model}/endpoints`; edit `POST /api/v1/images/edits` (multipart `image[]`) / нормализованный `POST /api/v1/images` (`input_references`); image-маршруты **non-streaming/synchronous** (`async_jobs=false` для известных). **Приёмка:** ✅ Q2 §97; endpoint'ы подтверждены по API-докам, не по Studio UI. **Тег:** [ARCH]. **Риск:** High. **Зависимости:** T-4094.
- [x] **T-4097 [@Architect — реальные лимиты Qwen Image 3 / Pro через API] — ✅ RESOLVED Step 2 (spec §2.3/§11.1 Q3; DC-7).** **Результат:** Qwen Image — edit, **≤3 reference/edit images**, до 4 выходов, route max 30 MB, `size=auto`; **char-limit промпта API не публикует** → `prompt_limit.source ∈ {internal_config, unknown}`, unit `chars|tokens|bytes|unknown`. **DC-7: `800` — НЕ API-лимит и в код не переносится.** **Приёмка:** ✅ Q3 §97. При смене провайдера — перепроверить discovery. **Тег:** [ARCH]. **Риск:** High. **Зависимости:** T-4096.
- [x] **T-4098 [@Scanner/@Memory — аудит connections/model-config + source of truth базового промпта]** — **Цель:** карта существующей конфигурации подключений/моделей (`IMAGE_BASE_URL`/`IMAGE_MODEL`/ключи, PG-only `models.*`), prompt-ключа `prompts.summary_cover_style` (PG-only, editable) и per-chat override. **Приёмка:** §62 (no duplicate source of truth), §31–§36, §61, Q5/Q9 — точки REUSE зафиксированы. **Тег:** [MECH]. **Риск:** Medium (риск ввести второй источник промпта). **✅ Pass 1:** аудит в `evidence.md` (ключи/группы/hot→settings/`chat_params.get_chat_param`).

---

## Блок B — `extra_images`, Style Registry, seed, DDL (§5–§9, §59, §94) (T-4099…T-4106)

- [x] **T-4099 [@PM/@Scanner — inventory seed-ассетов]** — **Цель:** зафиксировать точный состав `extra_images/`; seed импортируется по **фактическим** именам: `medved_press.png` (475 189 B), `style_example_01.png` (2 074 036 B), **`style_example_02.jpg`** (385 055 B). **DC-1 (решено):** §7/§9/§59/§77 называют `style_example_02.png` — литерал расходится с фактом; spec §3.6/§14 зафиксировал `.jpg`. **Не генерировать замены** (§7). **Приёмка:** список файлов+размеры+sha256; seed/acceptance используют **`.jpg`**. **Тег:** [MECH]. **Риск:** Low. **✅ Pass 1:** sha256 — `medved_press.png` `BE0A700BA8D3AF64358EEE6697AEFF11BCE8765E6FC8D9730E3569DF74AA15DB`, `style_example_01.png` `88A3D6BF5852A65C7167253C5DC730F50F9884AF4C7C8A5E397448F84B161006`, `style_example_02.jpg` `B3C337A68197B5974E93CAAA75C45D2CBB78955436838868ABE01CED4E88878E`.
- [x] **T-4100 [@Architect — дизайн хранилища Style Registry] — ✅ RESOLVED Step 2 (spec §4.2 / ADR-1028-4 D1/D5/D6).** **Решение:** Style Registry в **PostgreSQL** (5 таблиц: `cover_style_profiles`/`cover_style_references`/`cover_style_assets`/`cover_style_issue_assignments`/`cover_style_provenance`; идемпотентно через `DDL_STATEMENTS`; **Δ SQLite = 0**). **Реестр — ГЛОБАЛЬНЫЙ** (профили общие), **ВЫБОР стиля — per-chat** (`prompts.summary_cover_style_id`; DC-5). Поля §6/§11/§12/§26/§29 покрыты; data-driven, **без** `if style == "medved_press"` (§6). **Тег:** [ARCH]. **Риск:** High.
- [x] **T-4101 [@Architect — asset-регистр + импорт `extra_images/*`] — ✅ RESOLVED Step 2 (spec §3.6/§4.2 / ADR-1028-4 D6; DC-6).** **DC-6 (решено):** «существующего durable media/assets storage» в коде **нет** (есть лишь TTL-шаринг `media_share` + audit), поэтому spec вводит **НОВЫЙ durable asset-регистр**: PG `cover_style_assets` (stable `asset_id` = `sha256→id`, метаданные) + файлы на диске `var/cover_style_assets/` (env `COVER_STYLE_ASSETS_DIR`). Импорт seed идемпотентен (`ON CONFLICT DO NOTHING`), seed-файлы **копируются**, `extra_images/*` не мутируются (R18); Style Profile хранит `asset_id`, не blob/URL (§8/§12). **Тег:** [ARCH]. **Риск:** Medium. **Зависимости:** T-4100.
- [x] **T-4102 [@Builder — реализация seeded Style Profile `Графический роман Медведь Press`]** — **Цель:** создать Style Profile с `origin=seeded_example`, `pipeline_mode=generate_then_edit`, seeded edit-prompt (normalize/ensure/replace, §24), numbering enabled, format `ВЫПУСК {counter}`, reference `medved_press.png`, previews before/after. **Приёмка:** §6, §59; полностью редактируем/переименовываем/duplicate; **runtime не содержит special-case по имени стиля**. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4100, T-4101, T-4093. **✅ Pass 1:** `services/cover_style_registry.py::seed_seeded_style` + `SEEDED_INSTRUCTION`; тесты `test_extra_cover_style_registry.py` (no-special-case AST-гейт).
- [x] **T-4103 [@Builder — идемпотентность сида]** — **Цель:** seed не повторяется при каждом startup/migration. **Приёмка:** §59 (idempotent), повторный прогон — no-op; существующий ручной стиль не перезатирается. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4102. **✅ Pass 1:** `seed_seeded_style` короткое замыкание при существующем профиле; тесты `test_seed_idempotent`, `test_seed_does_not_overwrite_manual`.
- [x] **T-4104 [@Builder — PG-DDL init (Δ SQLite = 0)]** — **Цель:** добавить **5 таблиц + индексы** в `services/pg_db.py::DDL_STATEMENTS` (аддитивно/идемпотентно, `CREATE TABLE IF NOT EXISTS`; прецедент A5 `image_reservation`). **SQLite-миграция `mca-14` НЕ добавляется:** `user_version` остаётся **19** (санкция T-4093); self-guard в реестре `mca-14` не требуется. **Приёмка:** повторный старт — no-op; `PRAGMA user_version` = **19**; старые ID/таблицы/FTS/vec сохранены; Style-таблицы аддитивны (откат base-cover не требуется). **Тег:** [MECH]. **Риск:** High (схема). **Зависимости:** T-4093. **✅ Pass 1:** 5 таблиц + индексы в `DDL_STATEMENTS`; `test_pg_db.py` 24×2, `test_extra_cover_style_registry.py::TestDdl`; Δ SQLite = 0 (нет `migration_steps` v20, `user_version`=19).
- [x] **T-4105 [@Builder — Δ каталога + переиздание F8 (санкция)]** — **Цель:** добавить **+4 ParamSpec** (санкция spec §4.1/§13): `models.image_style_base_url`, `models.image_style_model` (группа `models_images`), `keys.image_style_api_key` (secret, `keys_images`), `prompts.summary_cover_style_id` (PG-only, `per_chat=True`, группа `prompts_summary` (пустое значение = `Без дополнительного стиля`). Новую GROUP **не** создавать (рекомендация spec §4.1). **Приёмка:** F8 переиздан **атомарно** по ADR-1026-2 (repin sha256 `param_catalog.py`+`pg_db.py`, regenerate TSV/meta/ScreenMap/widget-map, recount): **484/424/459/105/103/21 → 488/427/463/105/103/21** (delta 73→77; GROUPS/TAB_BY_GROUP/TAB_RULES — без роста; правило `mod_summary` — IN-PLACE при необходимости), обновлены `tests/fixtures/round1025/f8_baseline.json` + ассерты. **Числа перепроверить фактическим импортом `REGISTRY` на момент Build** (процедура recount ADR-1026-2; санкция фиксирует цель 488/427/463). **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4093. **✅ Pass 1:** фактический recount = **488/427/463/105/103/21** (delta 77); `< 4` ключа добавлены; F8-артефакты переизданы (`tools/gen_param_registry_round1025.py`, `--check` OK), фикстуры/ассерты обновлены (`tools/_extra_reissue_f8.py`).
- [x] **T-4106 [@Builder — preview placeholders §9→§10]** — **Цель:** подключить `style_example_01.png` (Before) и **`style_example_02.jpg`** (After; DC-1 — фактический файл `.jpg`) как дефолтную пару seeded стиля, заменяемую реальным preview (§9, §10). **Приёмка:** §9, §77 (браузерная приёмка seed-ассетов; имя — **`.jpg`**). **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4101, T-4102. **✅ Pass 1:** `SEED_FILES`/`seed_seeded_style` пишут `preview_before_asset_id`/`preview_after_asset_id` из фактических файлов; `preview_revision=None` (нет preview → placeholders); тест `test_seed_uses_actual_jpg`. Браузерная приёмка §77 — Pass 2 (T-4180).

---

## Блок C — Image Model Capability Resolver + Prompt Compiler + CoverBrief (§13–§21, §53, §57–§58, §71) (T-4107…T-4115)

- [x] **T-4107 [@Builder — структура `ImageModelCapabilities` + Resolver]** — **Цель:** реализовать resolver `provider+base_url+model → ImageModelCapabilities` с полями §14 (`text_to_image`, `image_edit`, `prompt_limit{value,unit,source}`, `max_input_images`, `max_input_bytes`, `supported_sizes`, `prompt_expansion`, `async_jobs`) — **без** hardcoded limits: `800` — **НЕ** API-лимит и в код не переносится (§15/DC-7; источник — capability resolver/`internal_config`|`unknown`). **Приёмка:** §14; значения берутся из источника (вход T-4096/T-4097). **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4096, T-4097. **✅ Pass 1:** `services/image_capabilities.py` (`ImageModelCapabilities`, `PromptLimit`, `parse_discovery`); тесты §87; AST-гейт «нет 800».
- [x] **T-4108 [@Builder — capability precedence]** — **Цель:** порядок резолва 1) explicit developer override → 2) runtime/provider API metadata → 3) provider-specific model catalog → 4) verified internal registry → 5) `unknown`/conservative fallback; override — аварийный escape hatch. **Приёмка:** §16. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4107. **✅ Pass 1:** `resolve_capabilities` (env-JSON `COVER_STYLE_CAPABILITY_OVERRIDES` уровень 1 → discovery уровень 2 → conservative уровень 5); тест `test_override_precedes_discovery`.
- [x] **T-4109 [@Builder — capability cache]** — **Цель:** кэш по `provider+base_url+model`; инвалидация при смене connection/model, reload config, explicit refresh, TTL; при смене Style model — инвалидация (§17, §71). **Приёмка:** §17, §71; нет запроса provider metadata на каждую обложку. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4107. **✅ Pass 1:** `_CACHE` + TTL (`COVER_STYLE_CAPABILITY_TTL_SECONDS`) + `invalidate`/`refresh`; тесты `test_cache_*`.
- [x] **T-4110 [@Builder — prompt limit unit]** — **Цель:** поддержка `chars`/`tokens`/`bytes`/`unknown`; при tokens — подходящий estimator/tokenizer без грубого перевода в chars. **Приёмка:** §18. **Тег:** [MECH]. **Риск:** Medium. **✅ Pass 1:** `UNIT_*` + `image_prompt_compiler._units_of` (tokens-estimator); тест `test_tokens_unit_uses_estimator`.
- [x] **T-4111 [@Architect — capability sources для локальных/неизвестных провайдеров] — ✅ RESOLVED Step 2 (spec §3.7/D2).** **Решение:** precedence §16 — runtime discovery (уровень 2) как primary; для провайдеров без публичных metadata — **developer override** (уровень 1, env-JSON/CSV по `provider+base_url+model`, аварийный escape-hatch, **не** UI-настройка) либо verified internal registry (уровень 4); иначе conservative `unknown` (`image_edit=unknown`, `max_input_images=0`), сохранение профиля не запрещается (§58). **Тег:** [ARCH]. **Риск:** High. **Зависимости:** T-4107, T-4108. **✅ Pass 1 (реализовано):** уровень 1 (`COVER_STYLE_CAPABILITY_OVERRIDES`) + уровень 2 (`parse_discovery`) + уровень 5 (`conservative_unknown`); тесты `TestCapabilities`.
- [x] **T-4112 [@Builder — Priority-aware Prompt Compiler]** — **Цель:** compiler собирает prompt из компонент §19 (base style prompt, dynamic brief, style instructions, runtime issue number, reference descriptions, mandatory invariants, provider constraints); приоритеты P0 (runtime invariants — не обрезать случайным `text[:N]`), P1, P2; при pressure **сначала сокращается P2** (§20). **Приёмка:** §19, §20; P0/номер выпуска сохраняются при любом давлении. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4107. **✅ Pass 1:** `services/image_prompt_compiler.py::compile_prompt`; тесты §88.
- [x] **T-4113 [@Builder — CoverBrief]** — **Цель:** формализовать компактное представление сюжета (`scene`/`mood`/`subjects`/`callouts`) вместо полной Summary-prose; compiler сам решает объём под capability; Summary-пайплайн не знает конкретные limits image-provider (§21). **Приёмка:** §21. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4112. **✅ Pass 1:** `CoverBrief` (`render(max_chars)`); тесты §88.
- [x] **T-4114 [@Builder — estimator бюджета для UI]** — **Цель:** расчёт «статическая инструкция / runtime+номер+reference reserve / запас для сюжета» для индикатора §57. **Приёмка:** §57; при неизвестном лимите — без ложных чисел. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4112, T-4110. **✅ Pass 1:** `estimate_budget`; тесты `test_estimate_*`.
- [x] **T-4115 [@Builder — unknown-limit policy + prompt expansion + save-инвариант]** — **Цель:** при неизвестном лимите профиль всё равно сохраняется, compiler использует безопасную policy, при API validation error логируется capability mismatch (§58); prompt expansion: разрешён для Base Creative, для Style Edit по умолчанию выключен/строгий режим, как model-policy, не universal hardcode (§53). **Приёмка:** §53, §58. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4112. **✅ Pass 1:** unknown-limit ветка компилятора (`limit=None` → безопасная policy, без ложных чисел); `prompt_expansion` в capabilities; тест `test_unknown_limit_safe_policy`.

---

## Блок D — Base/Style pipeline, слоты/connections, normalizer (§22–§24, §31–§35, §71–§73) (T-4116…T-4123)

- [x] **T-4116 [@Architect — раздельные Connections + Model Slots + per-style override] — ✅ RESOLVED Step 2 (spec §3.9/§4.1 / ADR-1028-4 D3).** **Решение:** `Connection` (base URL/key/provider) + `Image Model Slot` (`connection_id`+`model_id`) + `Style Profile`; слоты `Base Cover Generation` (существующие `models.image_*`) и `Cover Style Processing` (новые `models.image_style_*` + `keys.image_style_api_key`); глобальный default Style Processing + per-style override (`default`/`custom`); API key **не** в Style Profile (§31–§36). **DC-5:** реестр глобальный, **выбор стиля — per-chat** (§4.1). **Тег:** [ARCH]. **Риск:** High. **Зависимости:** T-4092, T-4098.
- [x] **T-4117 [@Builder — Connections UI «Обработка стилей обложки»]** — **Цель:** секция в центральном экране connections + маппинг на существующий settings/model-механизм. **Приёмка:** §33, §72; Base URL/API Key/Model настраиваются через Connections. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4116. **⏳ Pass 1 (backend готов):** ключи `models.image_style_base_url`/`models.image_style_model` (гр. `models_images`) + `keys.image_style_api_key` (гр. `keys_images`) автоматически рендерятся на вкладке `llm_providers` (без новых групп); `cover_style_pipeline.resolve_style_slot`; **UI-секция §33/§72** — Pass 2 (блок H).
- [x] **T-4118 [@Builder — deep-link Connections → Style Editor + возврат]** — **Цель:** кнопка `Настроить подключения →` (ИИ → Подключения, фокус на «Обработка стилей обложки») + сохранение контекста редактирования при возврате. **Приёмка:** §35, Q9. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4117. **⏳ Pass 1 (backend готов):** `connection_status`; **UI deep-link §35** — Pass 2 (блок H).
- [x] **T-4119 [@Builder — semantics normalizer]** — **Цель:** Style Edit как нормализатор (ensure/replace, без дублей и без тупого overlay): не добавлять второй PERMsoc, заменять/исправлять issue-badge, заменять чужой publisher-logo на reference, сохранять удачные callouts/композицию (§23). **Приёмка:** §23; приемлемость — визуальные runtime-тесты §85/§86. **Тег:** [MECH]. **Риск:** High (качество результата). **✅ Pass 1:** `cover_style_pipeline.normalizer_instruction` (инструкция как есть, без special-case); seeded prompt §24 в registry; визуальные тесты §85/§86 — Pass 2 (T-4173).
- [x] **T-4120 [@Builder — seeded edit prompt]** — **Цель:** заполнить seeded prompt, реализующий normalize/ensure/replace; recurring identity: `PERMsoc`, brand/reference `Медведь Press`, issue number, graphic-novel характер; композиция не фиксируется жёстко (§24). **Приёмка:** §24. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4102, T-4119. **✅ Pass 1:** `cover_style_registry.SEEDED_INSTRUCTION`; тест `test_seed_instruction_semantics`.
- [x] **T-4121 [@Builder — сохранять creative base]** — **Цель:** Style layer не стирает творческую работу base (выноски/облака/плашки/comic layout/captions) без необходимости (§22). **Приёмка:** §22. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4119. **✅ Pass 1:** seeded prompt §24 требует «сохрани удачные contextual callouts, композицию и сцену насколько возможно»; фактическая проверка — Pass 2 (§85/§86).
- [x] **T-4122 [@Builder — model switch]** — **Цель:** при смене Style Processing model — инвалидация кэша capability, пересчёт references в UI, пересчёт бюджета Compiler, новая job на новой модели; старые активные jobs — по своему snapshot (§71, §29). **Приёмка:** §71. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4109, T-4130. **✅ Pass 1:** `resolve_capabilities(refresh=True)`/`invalidate`; `references_available` пересчитывается; `build_revision_snapshot` фиксирует активный job; тест `test_cache_ttl_and_invalidate`.
- [x] **T-4123 [@Builder — connection validation]** — **Цель:** Test connection / Fetch models+capabilities / понятный status / last successful check; без обязательной реальной генерации при наличии дешёвого metadata endpoint (§73). **Приёмка:** §73. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4116. **✅ Pass 1:** `cover_style_pipeline.connection_status` (без реальной генерации); тесты `TestConnectionValidation`; UI — Pass 2.

---

## Блок E — Counters, revisions, provenance (§25–§30, §60, §66) (T-4124…T-4130)

- [x] **T-4124 [@Builder — нумерация принадлежит Style Profile]** — **Цель:** issue counter — per-style, не глобальный; поддержка форматов вида `ВЫПУСК {counter}` / `№ {counter}` / `ГЛАВА {counter}` / disabled (§25). **Приёмка:** §25. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4100. **✅ Pass 1:** `cover_style_profiles.counter_value/counter_format` per-profile; `format_issue`; тест `test_format_issue_uses_profile_format`.
- [x] **T-4125 [@Builder — counter config]** — **Цель:** поля `enabled` / next-current value / format string; слово `ВЫПУСК` не hardcode в runtime (§26). **Приёмка:** §26. **Тег:** [MECH]. **Риск:** Low. **✅ Pass 1:** `counter_enabled`/`counter_value`/`counter_format` в PG-схеме/сиде; `format_issue` берёт слово из шаблона.
- [x] **T-4126 [@Builder — pin номера к Summary run]** — **Цель:** при первом назначении `summary_run_id + style_id → assigned issue`; повторная генерация/rety того же Summary использует тот же номер (`44 → retry → 44`) (§27). **Приёмка:** §27; runtime-test §83. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4124. **✅ Pass 1:** `resolve_issue_number` (retry-reuse); тест `test_retry_reuse_same_number`; runtime §83 — Pass 2 (T-4172).
- [x] **T-4127 [@Builder — транзакционность/idempotency назначения]** — **Цель:** два параллельных Summary с одним style не получают одинаковый номер; свойства: уникальность внутри style, retry reuse, reproducibility (не gapless ценой хрупкости) (§28). **Приёмка:** §28; runtime-test §84. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4126. **✅ Pass 1:** атомарный `UPDATE ... RETURNING` + `INSERT ... ON CONFLICT DO NOTHING` + `UNIQUE(profile_id, issue_number)`; тест `test_concurrent_runs_get_different_numbers`; runtime §84 — Pass 2 (T-4172).
- [ ] **T-4128 [@Architect/владелец — начальное значение seeded counter] — ⛔ OPEN OWNER-DECISION (D8/§60).** **Цель:** подтвердить start value для seeded `Графический роман Медведь Press`. **Правило:** значение **НЕ выдумывать** (не выводить из `43/44` тестовой картинки). Варианты (spec §15): (a) `0`/`1`; (b) явное число владельца (напр. продолжить с `47`); (c) не задавать (configurable, пусто до ручного ввода). **Пометка: owner-input required before production seed.** **Приёмка:** §60; решение владельца зафиксировано до production seed; допускается безопасный обратимый дефолт (`0`/configurable) — см. T-4186. **Тег:** [ARCH]. **Риск:** Medium (product decision; не блокирует код/деплой). **Зависимости:** T-4092. **⏳ Pass 1:** seeded counter использует обратимый дефолт `0` (`SEEDED_COUNTER_START`); значение **не выдумано**, решение владельца — pending.
- [x] **T-4129 [@Builder — style revision snapshot]** — **Цель:** при старте Style Job зафиксировать style_id/revision/resolved instructions/reference asset IDs+versions/issue number/connection+model/capability snapshot; изменение профиля во время генерации не влияет на текущий job (§29). **Приёмка:** §29. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4100. **✅ Pass 1:** `cover_style_registry.build_revision_snapshot`; тест `test_snapshot_isolated_from_later_change`.
- [x] **T-4130 [@Builder — provenance артефакта + test-no-counter]** — **Цель:** хранить metadata итоговой картинки (§30: run_id/base_asset_id/final_asset_id/style_id/revision/issue/provider/model/connection_id/reference_asset_ids/timestamps/job id/status-fallback mode); Test Style **не** расходует production counter (§66). **Приёмка:** §30, §66. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4104, T-4128. **✅ Pass 1:** PG `cover_style_provenance` + `record_provenance` + `cover_style_pipeline.build_provenance`; `preview_issue_display`/`preview_issue_number` (§66); тесты `TestTestStyleNoCounter`, `TestPipelineProvenanceBuild`.

---

## Блок F — Long-running/async/durable jobs, recovery, logging, heartbeat, cost (§39–§48, §68–§70, §92) (T-4131…T-4141)

- [x] **T-4131 [@Builder — отдельная image execution policy]** — **Цель:** generation ~≥1 мин, edit ~≥2 мин; короткий общий LLM timeout **не** единственная граница; отдельная policy для image gen/edit (не `LLM timeout = 120`) (§39, §69). **Приёмка:** §39, §69. **Тег:** [MECH]. **Риск:** High (иначе обложки падают по таймауту).
- [x] **T-4132 [@Builder — async provider jobs]** — **Цель:** если provider поддерживает `submit → task_id → status/poll` — использовать async workflow, polling interval provider-aware (не hardcode без contract) (§40). **Приёмка:** §40; тест §89. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4096, T-4131.
- [x] **T-4133 [@Builder — synchronous-only путь]** — **Цель:** отдельный image timeout, локальный job state, heartbeat, retry policy с учётом стоимости повторной генерации (§41). **Приёмка:** §41. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4131.
- [x] **T-4134 [@Builder — Durable Media Job (REUSE)]** — **Цель:** REUSE существующей durable-инфраструктуры MCA: `task_jobs` (v14) через `TaskSupervisor`/`TaskJobStore` + `mca_pipeline_runs` (v19) через `mca_trace.start_run`/`finish_run` + `mca_events` (v15) — **второй очереди/второго стора НЕТ** (§42/Q6; ADR-1028-4 D8). State machine `CREATED → BASE_* → STYLE_* → PUBLISH_RICH/PLAIN → DONE/FAILED` → маппинг на `task_jobs.status/reason_code/checkpoint_ref`; provider `task_id` (если async) — в `payload`. **Приёмка:** §42; REUSE зафиксирован в ADR (§4.3). **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4092, T-4093.
- [x] **T-4135 [@Builder — crash/restart recovery]** — **Цель:** job state не теряется; async `provider task_id` сохраняется; после restart polling продолжается; **не** создавать новый платный task, если старый жив (§43). **Приёмка:** §43; тест §89 (restart resume). **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4134.
- [x] **T-4136 [@Builder — stage logging]** — **Цель:** события `COVER_PIPELINE_START` / `COVER_BASE_*` / `COVER_STYLE_*` / `COVER_RICH_PUBLISH_*` / `COVER_PLAIN_FALLBACK` / `COVER_PIPELINE_DONE` (§44). **Приёмка:** §44; логи позволяют увидеть точную упавшую стадию (§98). **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4134.
- [x] **T-4137 [@Builder — safe log fields]** — **Цель:** логировать run_id/job_id/style_id/revision/issue/connection/provider/model/prompt length/prompt hash/reference count/duration/provider task id/status/fallback path; **не** логировать API key, полный prompt, raw Summary, приватные image URLs с секретами (§45, R17). **Приёмка:** §45. **Тег:** [MECH]. **Риск:** High (R17). **Зависимости:** T-4136.
- [x] **T-4138 [@Builder — heartbeat]** — **Цель:** heartbeat при долгом gen/edit с разумным интервалом (`elapsed`, `provider_status`), без спама (§46). **Приёмка:** §46. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4133.
- [x] **T-4139 [@Builder — Analytics timeline + user-facing статусы]** — **Цель:** timeline по Summary run (текст/base/style/Rich + fallback-строки) §47; пользователю — русские статусы (`Обработка стилем не завершилась вовремя. Использована базовая обложка.`), машинный reason — только в техдеталях §48. **Приёмка:** §47, §48, §75. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4136.
- [x] **T-4140 [@Builder — observed latency]** — **Цель:** сбор по model/stage p50/p95/max/timeout count/retry count/provider fallback (§68). **Приёмка:** §68. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4136.
- [x] **T-4141 [@Builder — provider fallback + cost observability]** — **Цель:** не вводить сложный image-provider fallback в первой версии, но архитектурно оставить `primary→fallback image model` и интегрироваться с существующим механизмом, если есть (§70); раздельно логировать/агрегировать base generation / style edit / preview cost, не смешивать preview с production без маркировки (§92). **Приёмка:** §70, §92. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4134.

---

## Блок G — Fallback ladder, pipeline modes, Rich/plain, migration, kill-switch (§4, §49–§55, §94–§96) (T-4142…T-4150)

- [x] **T-4142 [@Builder — fallback ladder]** — **Цель:** финальная лестница `styled → base → RichMessage without cover → sendMessage`; ошибка оформления **никогда** не уничтожает готовый текст (§4, §96). **Приёмка:** §4, §96; runtime-tests §78–§82. **Тег:** [MECH]. **Риск:** Critical (публикация). **Зависимости:** T-4095, T-4136.
- [x] **T-4143 [@Builder — style fallback не перегенерирует base]** — **Цель:** при падении Style stage использовать сохранённую base cover, не вызывать Base Generation повторно (§49). **Приёмка:** §49; test §80 (`no second base generation`). **Тег:** [MECH]. **Риск:** High (стоимость). **Зависимости:** T-4142.
- [x] **T-4144 [@Builder — base fail]** — **Цель:** при неисправности base generation Style stage не запускается → `RichMessage without cover`; отсутствие обложки не отменяет статью (§50). **Приёмка:** §50; test §81. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4142.
- [x] **T-4145 [@Builder — ИЗМЕНЕНИЕ контура публикации: Rich без картинки (degraded)] — DC-3.** **Цель:** **аддитивно изменить** `SummaryGenerator._publish_rich_document` (`services/summary_generator.py`), добавив **штатный degraded-режим** RichMessage **без** cover-блока (media=[]), с сохранением title/body/formatting/cut/details/finale. Сейчас при `not tmp_path` контур сразу уходит в plain (§2.2 spec) — это **ИЗМЕНЕНИЕ публикационного пути**, а не «проверить существующую возможность». Второй publication pipeline **не** создаётся (§52/Q10). **Приёмка:** §51; Q10; runtime-test §81. **Тег:** [MECH]. **Риск:** High (публикация). **Зависимости:** T-4095.
- [x] **T-4146 [@Builder — plain sendMessage последний рубеж]** — **Цель:** переход к обычному `sendMessage` только при провале RichMessage; существующий Summary-fallback contract сохранён, тело статьи не теряется (§52). **Приёмка:** §52; test §82. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4142.
- [x] **T-4147 [@Builder — Style Pipeline Modes]** — **Цель:** минимум `generate_only` / `generate_then_edit` / `edit_only`; seeded `Медведь Press = generate_then_edit`; custom style может использовать другие режимы, если продуктово поддержано (§54). **Приёмка:** §54. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4100.
- [x] **T-4148 [@Builder — «Без дополнительного стиля»]** — **Цель:** explicit selection (не Style Profile): работает Base Generation, Style stage полностью пропущена, никаких branding/counter/reference constraints (§55). **Приёмка:** §55; test §78. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4142.
- [x] **T-4149 [@Builder — migration safety]** — **Цель:** existing config без выбора Style → автоматически `Без дополнительного стиля`; старое поведение default-compatible; добавление Registry/assets/issue-state не ломает существующие Summary (§94). **Приёмка:** §94; migration smoke T-4183. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4104.
- [x] **T-4150 [@Builder — kill-switch `COVER_STYLES_ENABLED`]** — **Цель:** env-only `ClassVar` kill-switch **`COVER_STYLES_ENABLED`**, default **ON** (санкция D6/D11; Δ каталога для kill-switch = 0): OFF → Base Cover Generation и публикация продолжают работать (parity baseline), Style stage полностью пропущена, Style UI disabled/скрыт; миграционного rollback base-cover не требуется (§95). **Приёмка:** §95; rollback-drill T-4184. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4093.

---

## Блок H — Style Editor UI, CRUD, preview/references, budget (§5, §9–§13, §56–§57, §63–§65, §67, §75) (T-4151…T-4162)

- [x] **T-4151 [@Builder — список стилей]** — **Цель:** UI-список: `Без дополнительного стиля` + seeded `Графический роман Медведь Press [Пример]` + пользовательские + `+ Создать стиль`; badge `Пример` только по `origin=seeded_example`. **DC-5:** список — **глобальный** (профили общие для всех чатов), но **выбранный стиль — per-chat** (`prompts.summary_cover_style_id`); UI отражает текущий per-chat выбор. **Приёмка:** §5, §6. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4100, T-4102.
- [x] **T-4152 [@Builder — Style Editor: структура]** — **Цель:** экран §56: Название / Как применяется / Инструкция стиля (textarea) / Референсы / Нумерация (toggle+next+format) / Как работает стиль (Before→After) / Модель обработки (default/custom) / Connection status / кнопка `Настроить подключения →`. **Приёмка:** §56. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4117.
- [x] **T-4153 [@Builder — reference upload UX]** — **Цель:** upload / drag&drop / PNG-JPEG-WebP validation / размер / progress / thumbnail / filename-label / Replace / Remove / понятная ошибка; Style Profile хранит `asset_id` (§12). **Приёмка:** §12; §98 (thumbnail/upload работают). **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4101.
- [x] **T-4154 [@Builder — динамический лимит references]** — **Цель:** `model max input images − base cover input = available references`, пересчёт при смене модели; **без** hardcode `max=2/3` (§13). **Приёмка:** §13, §37. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4107, T-4116.
- [x] **T-4155 [@Builder — references как универсальная сущность]** — **Цель:** reference = logo/персонаж/композиция/рамка/постер/цвет/вёрстка/прочее; prompt объясняет роль каждого; metadata label/description/ordering; **нет** hardcode роли `logo` на уровне системы (§11). **Приёмка:** §11. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4153.
- [x] **T-4156 [@Builder — Before/After preview + test + stale revision]** — **Цель:** блок `Как работает этот стиль` (base/example → styled/example) + `Протестировать стиль`; сохранение результата как preview; при изменении prompt/reference — `Пример создан для предыдущей версии стиля` + `Обновить пример` (§10). **Приёмка:** §10. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4106, T-4129.
- [x] **T-4157 [@Builder — Custom Style CRUD]** — **Цель:** Create / Read / Update / **Duplicate** / Delete / enable-disable; Duplicate особенно для копии seeded стиля. **Приёмка:** §63, §5. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4100, T-4151.
- [x] **T-4158 [@Builder — защита Style при delete asset]** — **Цель:** при удалении используемого reference asset — запрет с понятным сообщением либо удаление link после подтверждения; **никаких** broken dangling `asset_id` (§64). **Приёмка:** §64. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4101, T-4153.
- [x] **T-4159 [@Builder — Test Style standalone + preview logging]** — **Цель:** `Протестировать стиль` запускает только Style Edit job на выбранной/загруженной base image, без создания Summary (§65); логирование с `mode=preview`, не смешивая со статистикой production cover (§67). **Приёмка:** §65, §67. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4134, T-4130.
- [x] **T-4160 [@Builder — раздельность base prompt и style prompt]** — **Цель:** текущий пользовательский prompt базовой обложки остаётся и относится к Base Cover Generation; Style prompt — отдельное поле; UI явно объясняет разницу; **не** одна giant textarea; **не** второй независимый источник базового промпта (§61, §62). **DC-5:** **выбор Style Profile — per-chat** (`prompts.summary_cover_style_id`, пустое = `Без дополнительного стиля`), отдельно от base-промпта (`prompts.summary_cover_style`). **Приёмка:** §61, §62. **Тег:** [MECH]. **Риск:** High (source of truth). **Зависимости:** T-4098.
- [x] **T-4161 [@Builder — human-readable RU UI]** — **Цель:** все названия по-русски и понятны без знания архитектуры (`Базовая генерация обложки`, `Обработка стилем`, `Референсы`, `Нумерация выпуска`, `Модель обработки`, `Настроить подключения`, `Использована базовая обложка`); технические имена (`image_style_slot`, `capability_source`, `provider_task_id`) — только в раскрываемых техдеталях (§75). **Приёмка:** §75. **Тег:** [MECH]. **Риск:** Low.
- [x] **T-4162 [@Builder — budget indicator в редакторе]** — **Цель:** при известной capability — «Инструкция стиля: N / Динамический лимит модели: M» и/или compiler estimate (статика / reserve / запас сюжета); при неизвестном лимите — «Провайдер не публикует точный лимит инструкции», без ложного числа (§57). **Приёмка:** §57, §58. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4114.

---

## Блок I — Capability/Connections UI + privacy (§36–§38, §74) (T-4163…T-4166)

- [x] **T-4163 [@Builder — model capability UI]** — **Цель:** при выборе Style Processing model авто-показать: Image Edit да/нет, Text-to-Image да/нет, кол-во input images, остаток references (с учётом base cover), известный prompt limit + единицу, supported size/resolution, sync/async (если известно), source capability; без требования ручного знания (§37). **DC-4 (предпосылка):** текущий code-default provider (Pollinations/flux) **не** умеет image-edit → для реального Style Edit нужен **edit-capable provider** (напр. NanoGPT Qwen Image) в Connections; для модели без `image_edit` UI/валидация заблокируют запуск (T-4164), a base публикуется корректно. **Приёмка:** §37. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4107, T-4116.
- [x] **T-4164 [@Builder — модель без image_edit]** — **Цель:** при выборе модели без edit — понятная ошибка `Эта модель не умеет редактировать готовые изображения и не подходит для Cover Style Processing.`; заведомо неправильный API call не запускается (§38). **DC-4:** без edit-capable provider в Connections Style stage не выполняется, но публикуется base (деградация по contract §4); не блокирует base-путь. **Приёмка:** §38. **Тег:** [MECH]. **Риск:** Medium. **Зависимости:** T-4107.
- [x] **T-4165 [@Builder — секреты только в Connections]** — **Цель:** API key не показывается в Style Profile, не копируется в style JSON, не попадает в logs, хранится существующим безопасным способом; Style UI показывает только `Подключено` / `API ключ не настроен` (§36, R17). **Приёмка:** §36, §72, R17. **Тег:** [MECH]. **Риск:** High (R17). **Зависимости:** T-4117.
- [x] **T-4166 [@Builder — API key privacy]** — **Цель:** frontend никогда не получает полный сохранённый API key после initial save; masked `•••••••• configured` + возможность заменить (§74). **Приёмка:** §74. **Тег:** [MECH]. **Риск:** High (R17).

---

## Блок J — Тесты §78–§92 + regression + browser + invariants (T-4167…T-4182)

- [x] **T-4167 [@Tester — §78 runtime: no style]** — style `Без дополнительного стиля`: base cover generated; style stage skipped; RichMessage uses base cover. **Приёмка:** §78. **Тег:** [MECH]. **Риск:** Medium.
- [x] **T-4168 [@Tester — §79 runtime: style success]** — base generated; style получает base+references; style succeeds; styled cover published. **Приёмка:** §79. **Тег:** [MECH]. **Риск:** Medium.
- [x] **T-4169 [@Tester — §80 runtime: style failure]** — base generated; style failed; **no second base generation**; base cover published; Summary successful. **Приёмка:** §80. **Тег:** [MECH]. **Риск:** High.
- [x] **T-4170 [@Tester — §81 runtime: base failure]** — no style call; RichMessage without cover; при успехе Rich → Summary successful. **Приёмка:** §81. **Тег:** [MECH]. **Риск:** High.
- [x] **T-4171 [@Tester — §82 runtime: Rich failure]** — ordinary sendMessage fallback; тело статьи сохранено. **Приёмка:** §82. **Тег:** [MECH]. **Риск:** High.
- [x] **T-4172 [@Tester — §83/§84: retry reuse + concurrency]** — §83: first `44`, timeout, retry → `44`; §84: два независимых Summary на одном стиле → разные номера. **Приёмка:** §83, §84. **Тег:** [MECH]. **Риск:** High.
- [ ] **T-4173 [@Tester — §85/§86: foreign logo + existing PERMsoc/issue]** — §85: base содержит чужой publisher/logo, стиль `Медведь Press` → replace/normalize, не дубль (**обязательна визуальная верификация**); §86: base уже содержит PERMsoc + issue badge → нет второго PERMsoc/badge, номер нормализован к assigned runtime. **Приёмка:** §85, §86. **Тег:** [MECH]. **Риск:** High (визуальное качество). **⏳ Pass 2 (blocked-by DC-4):** семантика ensure/replace зафиксирована в seeded prompt (`SEEDED_INSTRUCTION`, §24) и P0-инвариантах компилятора; фактическая **визуальная** проверка требует edit-capable provider (DC-4) — не выполнена локально, вынесена в прод-приёмку §100.
- [x] **T-4174 [@Tester — §87 capability tests]** — fixtures: known chars limit / known tokens limit / unknown limit / edit supported / edit unsupported / 1 reference / many references / async / sync; корректное поведение frontend и runtime. **Приёмка:** §87. **Тег:** [MECH]. **Риск:** Medium.
- [x] **T-4175 [@Tester — §88 prompt compiler tests]** — everything fits / P2 removed first / P0 preserved / runtime number preserved / **no random mid-string truncation of mandatory instruction** / unknown limit / provider rejects oversized prompt. **Приёмка:** §88. **Тег:** [MECH]. **Риск:** High.
- [x] **T-4176 [@Tester — §89 async job tests]** — если provider async: submit / persist task_id / poll RUNNING / success / timeout-deadline / **restart resume**. **Приёмка:** §89. **Тег:** [MECH]. **Риск:** High.
- [x] **T-4177 [@Tester — §90 standard base cover regression (КРИТИЧНО)]** — после внедрения Style Engine обычная Base Cover Generation без Style даёт **тот же функциональный результат**, что до EXTRA; happy path не ухудшен. **Приёмка:** §90, §98. **Тег:** [MECH]. **Риск:** Critical (регрессия работающей функции).
- [x] **T-4178 [@Tester — §91 performance + §92 cost]** — не блокировать event loop долгим synchronous image request, использовать существующие async/network abstractions (§91); cost/usage раздельно base/style/preview, preview маркирован (§92). **Приёмка:** §91, §92. **Тег:** [MECH]. **Риск:** Medium.
- [ ] **T-4179 [@Reviewer/@Tester — §76 browser verification]** — **обязательны Browser Use + Playwright**; проверить: список Styles / seeded example / Create / Duplicate / Edit / reference upload / thumbnail / replace-remove / before-after preview / test style / numbering UI / model selection / connections redirect / return to editor / capability update после смены модели / **mobile** / **desktop**. **Приёмка:** §76, §98. **Тег:** [MECH]. **Риск:** High (UI-e2e). **⏳ Pass 2 (builder-side):** Playwright smoke (stubbed backend, 2.58.39): маршрут `#/modules/summary/styles`, seeded `[Пример]`, открытие редактора, budget §57, connection §73, reference thumbnail, Before/After, capability §37, mobile 390px без overflow, 0 console-errors; скриншоты `plans/reports/extra_cover_styles_{desktop,mobile}.png`. **Независимая** проверка (Browser Use + Playwright, реальный backend) — за @Reviewer/@Tester.
- [x] **T-4180 [@Tester — §77 seed assets verification]** — seeded `Графический роман Медведь Press` сразу показывает `medved_press.png` как reference thumbnail, `style_example_01.png` слева в Before, **`style_example_02.jpg`** справа в After (DC-1 — фактический `.jpg`) — до первой собственной preview generation. **Приёмка:** §77, §99.9-.7. **Тег:** [MECH]. **Риск:** Medium.
- [x] **T-4181 [@Architect/@Builder — §93 future extension reservation]** — архитектурно оставить место под `validation_mode = off|basic|strict` (будущая vision-проверка issue/PERMsoc/branding/duplicates); **не** добавлять третий mandatory LLM/image call сейчас. **Приёмка:** §93, §102. **Тег:** [ARCH]. **Риск:** Low.
- [ ] **T-4182 [@Reviewer — §98 invariants + §99 DoD coverage]** — пройти чек-лист §98 (**21 инвариант**; источник `current_task.md` строки 11855–11880) и подтвердить покрытие всех **35** пунктов DoD §99 (`current_task.md` строки 11883–11921; mapping — ниже). **Приёмка:** §98, §99; каждый инвариант имеет evidence. **Тег:** [MECH]. **Риск:** High (gate).

---

## Блок K — Релиз: migration safety, rollback, prod acceptance, bump, deploy, отчёт, архив (§94–§101) (T-4183…T-4188)

- [ ] **T-4183 [@Builder/@DevOps — migration smoke + идемпотентность]** — **Цель:** прогнать идемпотентный **PG-DDL init** (5 таблиц) на копии/эталоне; повторный старт — no-op; **SQLite `PRAGMA user_version` остаётся 19** (Δ = 0; в EXTRA никакого v20+ нет); существующие Summary/данные не затронуты; `extra_images` импортированы один раз. **Приёмка:** §94; Δ DDL = санкция (SQLite **0** / PG **5 таблиц**). **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4104.
- [ ] **T-4184 [@DevOps — rollback drill]** — **Цель:** проверить kill-switch **`COVER_STYLES_ENABLED=false`** (env-only, default ON; Base Cover + публикация продолжают работать, Style UI disabled) и cold `git revert` (PG-таблицы аддитивны, SQLite Δ = 0); откат base-cover функциональности не требуется. **Приёмка:** §95. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4150.
- [ ] **T-4185 [@Reviewer — единый Reviewer gate + подготовка §100]** — **Цель:** обе линзы ревью, Approved; инвентарь приёмки для прод-деплоя (no-style / Medved Press / style failure / base failure / rich failure / UI / logs). **Приёмка:** §98, §100. **Тег:** [MECH]. **Риск:** High. **Зависимости:** T-4167…T-4182.
- [ ] **T-4186 [@DevOps — bump `2.58.38` → `2.58.39` + ОБЯЗАТЕЛЬНЫЙ прод-деплой + приёмка §100]** — **Цель:** bump `APP_VERSION`; прод-деплой; проверить на production реальными Summary: no-style (base+Rich, без деградации), Medved Press (base→style→reference→issue→styled→Rich), style failure → base published, base failure → Rich без изображения, rich failure → обычный sendMessage; UI (seeded/thumbnails/references/create/duplicate/edit/counter/preview/connection redirect/mobile); логи понятны для одной успешной и одной degraded публикации. **DC-2 (безопасный дефолт):** для seeded counter — **обратимый configurable дефолт (`0`, допускается пустое)**; **значение НЕ выдумывать**, фиксируется владельцем до production seed (T-4128); пометка владельцу в отчёте/чеке. **DC-4 (предпосылка):** реальный Style Edit требует **edit-capable provider** в Connections; **base публикуется корректно и без него** (style stage — §38-деградация) — не блокер деплоя, зафиксировать в §101-отчёте. **Приёмка:** §100, §95; health 200, `database is locked`=0, version `2.58.39`. **Тег:** [MECH]. **Риск:** Critical (публикация в прод). **Зависимости:** T-4185.
- [ ] **T-4187 [@PM/@DevOps — финальный отчёт владельцу §101]** — **Цель:** человекочитаемый отчёт (без только SHA/manifest): как устроена базовая обложка; как работает optional Style; какие connections/models; какие capabilities определились; какой issue counter у seeded style; fallback ladder; сколько заняли base/edit; как создать свой стиль; какие ограничения image-модели реально обнаружены через API; что осталось future work. **DC-4 (§101, обязательно):** отметить, что реальный Style Edit требует **edit-capable provider** в Connections (текущий code-default — Pollinations/flux — edit не умеет; base при этом публикуется корректно). **DC-2:** зафиксировать фактическое начальное значение seeded counter (или пометку «owner-input required before production seed»). **Приёмка:** §101. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4186.
- [ ] **T-4188 [@PM — архивация фичи]** — **Цель:** после `delivery → reconcile → archive` переместить **полную** папку `plans/features/extra-cover-style-pipeline/` в `plans/archive/extra-cover-style-pipeline-round1029/` (или по дате раунда), сохранив стабильные ID и разрешив относительные ссылки. **Предусловия:** unified @Reviewer Approved с binding commit/tree; нет release-blocking находок; deploy `VERIFIED`; reconciliation @Architect завершён; evidence/review/deploy ссылки резолвятся. **DC-2:** подтвердить, что начальное значение seeded counter зафиксировано владельцем (**owner-input required before production seed**) либо осознанно принят обратимый дефолт `0`; иначе — не архивировать с открытым D8. **Приёмка:** §99; затем — чекпоинт `archive → select_next`. **Тег:** [MECH]. **Риск:** Low. **Зависимости:** T-4186.

---

## Трассировка §1–§102 → задачи → тесты

| § (источник в `current_task.md`) | Тема | Задачи | Тесты/приёмка |
|---|---|---|---|
| §1 | главный принцип (независимые стадии) | 0, G (T-4142) | §78–§82 |
| §2 | Base Cover Generation ≠ Legacy | A (T-4094), G, J | §90, §98 |
| §3 | Cover Style — optional post-processor | D, G (T-4142/4147) | §78–§79 |
| §4 | fail-soft publication ladder | G (T-4142…T-4146) | §78–§82, §96 |
| §5 | Style Registry / список стилей | B (T-4100), H (T-4151) | §76, §100/UI |
| §6 | Медведь Press — обычный seeded стиль | B (T-4102/4103) | §98 (no special-case) |
| §7 | папка `extra_images/` | B (T-4099/4101) | §77 |
| §8 | `medved_press.png` reference | B (T-4101/4106) | §77, §98 |
| §9 | preview placeholders | B (T-4106) | §77 |
| §10 | replaceable preview / stale revision | H (T-4156) | §76, §100/UI |
| §11 | references — универсальны | H (T-4155) | §76 |
| §12 | reference upload UX | H (T-4153) | §76, §98 |
| §13 | динамический лимит references | C (T-4107) + H (T-4154) | §87 |
| §14 | ImageModelCapabilityResolver | C (T-4107) | §87 |
| §15 | не предполагать Qwen=800 | A (T-4096/4097), C | §87, §99.20-.21 |
| §16 | capability precedence | C (T-4108/4111) | §87 |
| §17 | capability cache | C (T-4109) | §87 |
| §18 | prompt limit unit | C (T-4110) | §87 |
| §19 | Image Prompt Compiler | C (T-4112) | §88 |
| §20 | priority-aware (P0/P1/P2) | C (T-4112) | §88 |
| §21 | CoverBrief | C (T-4113) | §88 |
| §22 | creative base generation | D (T-4121) | §79, §85 |
| §23 | Style Edit = normalizer | D (T-4119) | §85, §86 |
| §24 | seeded prompt | D (T-4120) | §85, §86 |
| §25 | нумерация принадлежит style | E (T-4124) | §83, §84 |
| §26 | counter config | E (T-4125) | §76, §99.12 |
| §27 | номер закреплён за run | E (T-4126) | §83 |
| §28 | counter concurrency | E (T-4127) | §84 |
| §29 | style revision snapshot | E (T-4129), D (T-4122) | §71-тесты, §76 |
| §30 | cover artifact provenance | E (T-4130) | §92, §96 |
| §31–§35 | separate connections / slots / override / deep-link | D (T-4116…T-4118) | §76, §100/UI |
| §36 | secrets только в Connections | I (T-4165) | §98, R17 |
| §37 | model capability UI | I (T-4163) | §76, §87 |
| §38 | модель без edit | I (T-4164) | §87 |
| §39–§41 | long-running / async / sync | F (T-4131…T-4133) | §89, §91 |
| §42 | durable media job | F (T-4134) | §89 |
| §43 | crash/restart recovery | F (T-4135) | §89 (restart resume) |
| §44 | logging стадий | F (T-4136) | §98 (точная стадия) |
| §45 | safe log fields | F (T-4137) | R17, §98 |
| §46 | heartbeat | F (T-4138) | §89 |
| §47 | analytics timeline | F (T-4139) | §99.35 |
| §48 | RU user-facing статусы | F (T-4139), H (T-4161) | §75 |
| §49 | style fallback без regen base | G (T-4143) | §80 |
| §50 | base generation fail | G (T-4144) | §81 |
| §51 | RichMessage without image (DC-3 — изменение контура) | G (T-4145) | §81 |
| §52 | plain sendMessage | G (T-4146) | §82 |
| §53 | prompt expansion policy | C (T-4115) | §88 |
| §54 | pipeline modes | G (T-4147) | §78–§79 |
| §55 | «Без дополнительного стиля» | G (T-4148) | §78 |
| §56 | Style Editor структура | H (T-4152) | §76, §100/UI |
| §57 | budget indicator | C (T-4114) + H (T-4162) | §76 |
| §58 | нельзя запретить save при unknown limit | C (T-4115) | §88 |
| §59 | seed init / idempotent | B (T-4102/4103) | §77, §99.3 |
| §60 | counter initial value | E (T-4128) | owner-decision D8 (не блокирует) |
| §61 | existing cover prompt UI | H (T-4160) | §76 |
| §62 | no duplicate source of truth | H (T-4160), A (T-4098) | §98 |
| §63 | custom CRUD | H (T-4157) | §76, §100/UI |
| §64 | не потерять Style при delete asset | H (T-4158) | §76 |
| §65 | Test Style без Summary | H (T-4159) | §99.30 |
| §66 | Test Style не увеличивает counter | E (T-4130) + H (T-4159) | §99.31 |
| §67 | Test Style logging mode=preview | H (T-4159) | §92 |
| §68 | observed latency | F (T-4140) | §99.35 |
| §69 | timeout ≠ LLM | F (T-4131) | §91, §98 |
| §70 | provider fallback | F (T-4141) | §99.24 |
| §71 | model switch | D (T-4122) | §76 (capability update) |
| §72 | Base URL/Key/Model settings | D (T-4117), I (T-4165) | §99.16-.18 |
| §73 | connection validation | D (T-4123) | §76 |
| §74 | API key privacy | I (T-4166) | R17, §98 |
| §75 | human-readable UI | H (T-4161), F (T-4139) | §76 |
| §76 | browser verification | J (T-4179) | browser-use+Playwright |
| §77 | seed assets verification | J (T-4180) | §77 |
| §78–§92 | runtime/capability/compiler/async/regression/perf/cost тесты | J (T-4167…T-4178) | §78–§92 |
| §93 | future extension validation | J (T-4181) | — |
| §94 | migration safety | B (T-4104), G (T-4149), K (T-4183) | migration smoke |
| §95 | rollback | G (T-4150), K (T-4184) | rollback drill |
| §96 | analytics/logs fallback ladder | G (T-4142), F (T-4139) | §96 |
| §97 | Architect questions Q1–Q10 | 0 (T-4092), A, C, D | — |
| §98 | Reviewer invariants | J (T-4182), K (T-4185) | чек-лист |
| §99 | Definition of Done | K (T-4188), J (T-4180/4182) | mapping ниже |
| §100 | production acceptance | K (T-4186) | прод-приёмка |
| §101 | финальный отчёт владельцу | K (T-4187) | отчёт |
| §102 | non-goals | границы scope | — |

**Осиротевших требований нет:** каждая секция §1–§102 замаплена на ≥1 задачу. **Задач без обоснования нет:** каждая задача ссылается на § или на процесс (baseline/release/archive).

---

## DoD §99 — mapping (35 пунктов)

| §99 | Пункт | Задачи |
|---|---|---|
| 1 | Style Registry | T-4100, T-4151 |
| 2 | «Без стиля» = current Base behavior | T-4148, T-4167 |
| 3 | Медведь Press seeded editable | T-4102, T-4103 |
| 4 | Нет `if medved_press` | T-4102 |
| 5 | `medved_press.png` импортирован | T-4101, T-4106 |
| 6 | `style_example_01.png` Before | T-4106, T-4180 |
| 7 | `style_example_02.jpg` After (DC-1) | T-4106, T-4180 |
| 8 | References загружаются через Miniapp | T-4153 |
| 9 | References thumbnail | T-4153, T-4180 |
| 10 | Reference limits от модели | T-4154 |
| 11 | Counter принадлежит Style | T-4124 |
| 12 | Counter format configurable | T-4125 |
| 13 | Retry сохраняет номер | T-4126, T-4172 |
| 14 | Concurrent assignment безопасен | T-4127, T-4172 |
| 15 | Base и Style модели раздельно | T-4116 |
| 16 | Style Processing Base URL/Key/Model | T-4117 |
| 17 | API key не внутри Style | T-4165 |
| 18 | Кнопка `Настроить подключения →` | T-4118 |
| 19 | ImageModelCapabilityResolver | T-4107 |
| 20 | Prompt limit не hardcoded 800 | T-4107, T-4110 |
| 21 | Реальный NanoGPT contract исследован | T-4096, T-4097 |
| 22 | Prompt compiler учитывает capabilities | T-4112 |
| 23 | Long-running отдельная policy | T-4131 |
| 24 | Async polling если поддерживается | T-4132, T-4133, T-4176 |
| 25 | Durable state переживает restart | T-4134, T-4135, T-4176 |
| 26 | Каждая стадия логируется | T-4136 |
| 27 | Style failure → base cover | T-4143, T-4169 |
| 28 | Base failure → Rich без cover | T-4144, T-4170 |
| 29 | Rich failure → sendMessage | T-4146, T-4171 |
| 30 | Preview/test независим от Summary | T-4159 |
| 31 | Preview не тратит counter | T-4130, T-4159 |
| 32 | Before/After UX работает | T-4156, T-4179 |
| 33 | Base-cover regression проходит | T-4177 |
| 34 | Browser desktop/mobile verified | T-4179 |
| 35 | Analytics/logging показывают timing/fallback | T-4139, T-4140 |

---

## Reviewer invariants §98 — mapping

| §98 инвариант | Задача |
|---|---|
| Base Cover first-class, не legacy | T-4094, T-4148 |
| No-style path работает как раньше | T-4167, T-4177 |
| Style layer optional | T-4142, T-4150 |
| Медведь Press — seeded normal Style | T-4102 |
| Runtime без special-case по имени | T-4102 |
| Seed reference из `extra_images/medved_press.png` | T-4101, T-4106 |
| Before/After placeholders (DC-1: `style_example_02.jpg`) | T-4106, T-4180 |
| References thumbnail/upload | T-4153, T-4179 |
| Issue counter принадлежит style | T-4124 |
| Retry reuse issue number | T-4126 |
| Style failure → base cover | T-4143 |
| Base failure → Rich without cover | T-4144 |
| Rich failure → sendMessage | T-4146 |
| Limits не hardcoded глобально | T-4107, T-4110 |
| Capability resolver model/provider-aware | T-4107, T-4108 |
| Base и Style — разные models/providers | T-4116 |
| API key только в Connections | T-4165 |
| Кнопка Connections работает | T-4118 |
| Long-running ≠ text LLM timeout | T-4131 |
| Logs видно точную стадию | T-4136 |
| Browser desktop/mobile verified | T-4179 |

---

## DDL-оценка — ✅ RESOLVED Step 2 (историческая оценка PM сохранена ниже)

> **✅ ФИНАЛЬНОЕ РЕШЕНИЕ @Architect (spec §4/§13, ADR-1028-4 D1):** выбран вариант **(b)** — **Δ DDL SQLite = 0** (`user_version` остаётся **19**); Style Registry/references/assets/issue-assignment/revision/provenance — в **PostgreSQL**, идемпотентные `DDL_STATEMENTS` (**5 таблиц + индексы**; прецедент A5 `image_reservation`); **Δ PG DDL ≠ 0**; `mca-04b` сохраняет **v20**; **AMEND ADR-1027-9 D13 и правка `mca-round1027-arch-frames.md` НЕ требуются**; Δ каталога **+4** → F8 **488/427/463/105/103/21**; kill-switch `COVER_STYLES_ENABLED` env-only default ON. Инвариант: `extra_images/*` не мутируются (копируются в `var/cover_style_assets/`).

**Вопрос владельца: нужна ли новая таблица / версия (v20?) для §7 `extra_images`?**

- **§7 сам по себе таблицу НЕ требует.** `extra_images/` — это **папка входных seed-ассетов** (§7: «Не генерировать вместо них новые изображения при миграции»). Ассеты импортируются в **существующее** media/assets storage (§8), а Style Profile хранит `asset_id`, а не blob (§12). Отдельная таблица под файлы не нужна.
- **Потребность в durable-хранилище возникает из других секций:** §5 Style Registry (профили с CRUD, references, revision), §26 counter config, §27–§28 issue assignment (`summary_run_id + style_id → issue`, транзакционно/идемпотентно), §29 revision snapshot, §30 provenance. Это **не** §7.
- **Оценка @PM (не решение):**
  - `task_jobs`/durable job (§42–§43) — **REUSE** (v14/v19), Δ DDL = 0.
  - Cover provenance (§30) — вероятно REUSE существующих asset-метаданных/provenance (`mca-04a`), Δ DDL = 0 — за @Architect.
  - **Style Registry + issue assignment** — наиболее вероятные кандидаты на новое хранилище. Если оно **PG** (`CREATE TABLE IF NOT EXISTS` идемпотентно) — **SQLite `user_version` не поднимается**, коллизии с `mca-04b` **нет**. Если оно **SQLite** — нужен новый шаг `user_version` → **v20**.

**Коллизия версий (флаг @Architect, обязателен к разрешению до Build):**

- Прод SQLite сейчас — **v19**. Следующая свободная — **v20**.
- `plans/features/mca-04b-dossier-rebuild/spec.md` §5.1 / `adr-1027-9-...md` **D13** уже **санкционировали v20** для `mca-04b` (`mca_dossier_generations`, `mca_dossier_staging_items`, `graph_facts.dossier_generation_id`) и объявили **v21** свободной.
- **Однако `mca-04b` не построен и не задеплоен** (spec/ADR готовы, шаг Builder — впереди; деплой — `DEFERRED_TO_RELEASE`). Очередь владельца ставит **EXTRA до MCA-tasks**, значит на реальной прод-цепочке первым v20 может занять **EXTRA**.
- **Варианты (выбор — @Architect, T-4093):**
  - **(a)** EXTRA берёт **v20**, `mca-04b` переносит бронь на **v21** → требуется **AMEND ADR-1027-9 D13** + правка брони в рамке `plans/docs/mca-round1027-arch-frames.md` §1.2.4.
  - **(b)** Style Registry живёт в **PG**, issue assignment — REUSE существующего SQLite-состояния → **Δ DDL (SQLite) = 0 для EXTRA**, `mca-04b` сохраняет v20 без AMEND.
  - **(c)** Смешанный: Registry в PG, но issue assignment требует SQLite → EXTRA берёт v20, `mca-04b` → v21 (вариант (a)).
- **Вывод:** новая таблица **вероятна**, но **не доказана**; **если** реализуется на SQLite — нужен **v20** и **однозначное разрешение конфликта с `mca-04b`** (иначе два шага с одним `user_version`). Это **санкция @Architect** (T-4093); @PM архитектурных решений не принимает.

**Отдельно (не DDL):** §94 допускает, что существующий config без выбора Style автоматически становится `Без дополнительного стиля`; §95 требует kill-switch `cover_styles_enabled` — предпочтительно env-only (тогда Δ каталога = 0, но финально — @Architect).

---

## [ARCH]-зависимости — ✅ закрыты Step 2 (spec/ADR); открыт только D8-counter

> **Статус:** все пункты ниже разрешены `spec.md` + ADR-1028-4 (см. «Ревизия PM» выше и spec §11.2 D1–D8), кроме: **T-4128** — ⛔ OPEN OWNER-DECISION (counter start; не блокирует код/деплой), **T-4181** — build-time резерв (§93). Исторический список сохранён ниже.

1. **T-4092** — `spec.md` + ADR + ответы Q1–Q10 §97 и производные.
2. **T-4093** — санкция Δ DDL (v20/v21/0) + **разрешение коллизии с `mca-04b`** (AMEND ADR-1027-9 D13 / ребронь рамки §1.2.4).
3. **T-4096/T-4097** — реальные NanoGPT endpoints + лимиты Qwen Image 3 / Pro через API (§15, Q2/Q3).
4. **T-4100/T-4101** — выбор хранилища Style Registry (PG/SQLite/file) + REUSE asset storage (§8, Q8).
5. **T-4111** — capability sources для локальных/неизвестных провайдеров + developer override (§16 п.3–5).
6. **T-4116** — раздельные Connections/Model Slots + per-style override (Q5).
7. **T-4128** — начальное значение seeded counter `Медведь Press` (§60; product decision владельца).
8. **T-4181** — резерв под `validation_mode` (§93).
9. Классификация REUSE: `task_jobs`/`TaskSupervisor`/`mca_pipeline_runs` для durable cover pipeline (§42, Q6); существующие Summary-fallbacks для публикации (§52, Q10); Connections redirect (§35, Q9).

---

## Вопросы @Architect — ✅ отвечены Step 2 (spec §11); ниже — исторический список

> **Статус:** Q1–Q10 §97 и производные D1–D8 отвечены в `spec.md` (§11.1/§11.2) и ADR-1028-4; **D8** остаётся ⛔ owner-decision (T-4128). Список оставлен дословно для трассировки.

**Обязательные из §97 (дословно):**

- **Q1** — Как сейчас реально устроен Base Cover Generation и какой exact prompt отправляется image provider?
- **Q2** — Какие реальные NanoGPT endpoints используются сейчас?
- **Q3** — Каковы реальные API limits Qwen Image 3 / Qwen Image 3 Pro через используемый NanoGPT API, а не только Studio UI?
- **Q4** — Есть ли у provider async image jobs/status API для используемого endpoint?
- **Q5** — Как интегрировать ImageModelCapabilityResolver с существующей model/provider config architecture?
- **Q6** — Как использовать существующий `task_jobs` для durable cover pipeline?
- **Q7** — Как хранить Style Profiles и issue assignment без special-case `Медведь Press`?
- **Q8** — Как импортировать `extra_images/*` в существующее asset storage idempotently?
- **Q9** — Как устроить Connections redirect и возврат обратно в Style Editor?
- **Q10** — Какие existing Summary fallbacks нужно переиспользовать, чтобы не создать второй publication pipeline?

**Производные (добавлены @PM):**

- **D1 (DDL-конфликт)** — Δ DDL SQLite EXTRA: 0 / v20 / v21? Если v20 — кто берёт первым с учётом очереди «EXTRA до MCA-tasks»? Требуется ли **AMEND ADR-1027-9 D13** и ребронь `mca-04b` на v21? (T-4093)
- **D2 (capability sources)** — Для провайдеров без публичных metadata (локальные/self-hosted) какой источник истины (verified registry / provider catalog / override)? Как оформляется developer override (T-4111)?
- **D3 (размеры/лимиты prompt)** — Точные значения `prompt_limit{value,unit,source}` и `max_input_images` для фактически используемых моделей; как хранятся `supported_sizes`; нужен ли tokenizer для tokens-limit (§18)?
- **D4 (async-провайдеры)** — Состав провайдеров с async `submit/task_id/poll`, источник polling interval (§40), deadline-семантика; как мапится на `mca-17a` lifecycle (v19).
- **D5 (хранилище Style Registry)** — PG vs SQLite vs файловый store; где живёт issue assignment и revision snapshot; REUSE или новая таблица (T-4100).
- **D6 (kill-switch / Δ каталога)** — `cover_styles_enabled` env-only (Δ каталога=0) или каталогизируемый ключ? Нужны ли per-style/toggle ключи в `param_catalog` (T-4105, T-4150)?
- **D7 (расхождение seed-имени)** — §7/§9/§59/§77 называют `style_example_02.png`, фактический файл — `style_example_02.jpg`; подтвердить, что seed берёт фактическое имя (T-4099).
- **D8 (начальное значение counter)** — подтвердить start value seeded стиля (владелец), не угадывать по `43/44` (§60, T-4128).

---

## Non-goals первой версии (§102)

Не делать сейчас: полноценный графический редактор; canvas manual positioning; ручную расстановку каждого logo; pixel-perfect brand validation; обязательный третий vision QA-call; сложный marketplace Styles; multi-user permissions внутри одного Style Profile; arbitrary workflow scripting. Главная задача — устойчивый, расширяемый, data-driven Cover Style pipeline поверх уже хорошей Base Cover Generation (§102).

---

## Handoff (Step 2.5 @PM — consistency-gate)

- **Путь:** `plans/features/extra-cover-style-pipeline/tasks.md`
- **Состав:** **T-4091…T-4188 (98 задач)**, блоки **0, A–K**; теги `[ARCH]`/`[MECH]`; каждая — цель, приёмка со ссылкой §, риск, зависимости.
- **Трассировка:** §1–§102 → задачи → тесты (таблица выше); **DoD §99 (35 пунктов)** и **Reviewer invariants §98** — замаплены; тесты **§78–§92 — все в блоке J** (T-4167…T-4178).
- **✅ ВЕРДИКТ: PLANNING_CONSISTENT** — requirement map ↔ spec ↔ tasks согласованы по scope/exclusions, risk (**R3**), acceptance evidence, dependencies, deploy applicability и rollback.
- **Санкции (spec §13 / ADR-1028-4):** Δ SQLite **0** (v19; `mca-04b` v20 — AMEND не требуется); Δ PG **≠0** (5 таблиц + индексы, идемпотентно); Δ каталога **+4** → F8 **488/427/463/105/103/21** (атомарное переиздание); kill-switch **`COVER_STYLES_ENABLED`** env-only default ON; deploy bump **2.58.38 → 2.58.39**; REUSE `task_jobs`/`mca_pipeline_runs`/`mca_events` (второй очереди нет).
- **Открытые вопросы:** **D8 (counter start) — ⛔ owner-decision, НЕ блокирующий** (T-4128; в деплое — обратимый configurable дефолт `0`, пометка владельцу); **DC-4** — продуктовая предпосылка edit-capable provider (не блокирует код/деплой; base публикуется корректно). **Блокирующих вопросов нет.**
- **Хэши входа (полные Get-FileHash):** spec `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF`; ADR-1028-4 `E9C44ACCADF4FC0F9921A3F73054768A49EA1D8F700C1D744DBC006D92807251`; `current_task.md` `D6AD5DFB338A1FD6441E5013FA3D856A487F1796EE3D39FA963C02AF9DCAF2EB` (**не изменялся**). **`extra_images/*` не тронуты** (untracked/read-only; R18).
- **Следующий шаг:** @Orchestrator — чекпоинт planning → Build; **@Builder (Step 3)** по `tasks.md` (старт с блоков 0/A/B, вход — Step 2 spec/ADR).
