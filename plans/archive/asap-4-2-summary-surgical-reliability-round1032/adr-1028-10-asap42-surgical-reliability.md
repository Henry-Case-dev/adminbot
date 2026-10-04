# ADR-1028-10 — ASAP 4.2: Surgical Summary Reliability, Real Provider E2E & MiniApp UX Repair

> **Фича:** `asap-4-2-summary-surgical-reliability` (ASAP 4.2, corrective pass после ASAP 4.1).
> **Задача-инициатор:** T-4801 [@Architect]; потребители — Builder/Reviewer/DevOps (tasks.md T-4802…T-4840).
> **Статус:** Accepted (04.10.2026, design; ратифицирован merge + прод-валидацией VERIFIED 2.58.48 — см. «Прод-валидация и история» ниже).
> **Контекст:** прод 2.58.47 (SQLite v24). Источник — `plans/current_task.md:23847–25458` (§0–§60, DoD 50); прод-инцидент §1 (L1/L2 FAILED → Legacy; `COVER_STYLE_FAILED HTTP 400 nano-gpt.com/qwen-image-3-pro`).
> **PM-пакет:** requirements-map (R8-A…R8-Q, AM-1…AM-5), tasks.md (T-4800…T-4840), reuse-inventory.md.
> **Связь:** AMEND → ADR-1028-8 (D2 capacity precedence, D3 L1 map, D5.4 streaming slots); REPLACE → ADR-1028-4 (D2 image capability precedence completion, D4 edit route, D5 compiler P0–P3); EXTENSION → ADR-1028-8 (D8 Inspector fields), ADR-1028-5 (media adapter pattern-donor, контур не дублируется); не трогает → ADR-1028-6/-7/-9, MCA features, RichMessage renderer, Base Cover generation, GraphRAG, history.

---

## Supersede / Amend register (AM-1…AM-5, статусы)

| # | Старое решение | Новый статус | Директива владельца | Где |
|---|---|---|---|---|
| AM-1 | ASAP 4.1 `summary_l1_semantic_map` v1: `message_ids` (raw TG) в topics/events/relationships; `unassigned_message_ids` приходит от LLM | **AMENDED → v2:** `source_anchors[]` вместо `message_ids`; `unassigned_anchors[]` optional, canonical считает код; `schema_version=2`. Kill-switch OFF → v1 байт-в-бит | 23952–24018 | D1, spec §1 |
| AM-2 | ASAP 4.1: Mode A/B — «контрактные слоты default OFF», live-верификация PENDING OWNER; `declare_execution_capabilities` всегда `streaming=False` | **AMENDED → активирован Mode B** для подтверждённого OpenAI-compatible `/chat/completions` (`stream=true`); Mode A остаётся слотом (только при реальном job/status API); флаги `SUMMARY_LLM_STREAMING_MODE_ENABLED`/`_ASYNC_MODE_ENABLED` сохранены | 24273–24313 | D5, spec §4 |
| AM-3 | `cover_style_edit.py` использует `POST {base_url}/images` + `input_references` (data-URL строки); mock закрепляет этот контракт | **AMENDED/REPLACED → provider-specific routes.** Верифицировано по docs.nano-gpt.com: Image API `POST /api/v1/images` (`input_references`: строки **или** `image_url`-объекты) **и** OpenAI-compatible `POST /api/v1/images/edit( s)` (`imageDataUrl(s)`/multipart `image[]`). Маршрут выбирается по discovered endpoint-metadata модели; mock не является доказательством | 24334–24379, 24540–24557 | D2, spec §2 |
| AM-4 | `image_capabilities.py` декларирует precedence, но `prompt_limit` фактически не заполняется (`parse_discovery` не парсит лимит) → compiler в unknown-ветке | **AMENDED/COMPLETED:** реальное заполнение prompt_limit по precedence override→live model→live route→verified registry→cached runtime→unknown; machine-readable 400 → extract N → cache → recompile → ONE retry; per provider+model+route; `800` не глобальный hardcode | 24383–24440, 24444–24496 | D3, spec §3 |
| AM-5 | ASAP 4.1 Inspectors/events (T-4621–4624) — база root-cause visibility | **EXTENDED (additive):** anchors generated/repaired/dropped, correction retry, invalid refs repaired, revision count, provider error sanitized, original/compiled prompt chars, resolved limit + source, published cover styled/base/none. R17-safe | 24561–24599 | D6 (spec §5) |

**SUPERSEDE-процедура:** owner-директивы в §0–§60 прямые («не считать правильным», «убрать», «реальный contract»); формальные записи — этот register. Старые каноны помечаются amended этим ADR; второй противоречащий канон не создаётся.

---

## D1. SourceAnchorMap — self-validating anchors вместо raw message_id (AM-1)

**Решение.** LLM-обращённый reference-контракт = короткие self-validating anchors, создаваемые только кодом поверх immutable `SummarySourceWindow`.
- Формат: `m` + 4-char base36 ordinal (0-padded) + `-` + 2-char base36 checksum (`m00BD-K7`).
- ordinal — 0-based индекс в `SummarySourceWindow.messages`; checksum = `base36(sha256(run_fingerprint + ":" + real_message_id + ":" + ordinal)[:8] % 36²)`; `run_fingerprint` = hash `(run_id, chat_id, window_from, window_to)`.
- Инварианты: код создаёт; immutable per run; биекция 1↔1; checksum валидируется; битый anchor не становится другим валидным; обратный перевод anchor→real id; mapping не в публичном тексте (R17).
- Collision: ordinal уникален ⇒ полные строки уникальны; build asserts уникальность; опечатка модели не проходит checksum → unknown → local repair.

**L1 map v2 (AM-1):** `schema_version=2`; topics/events/relationships несут `source_anchors[]`; `unassigned_anchors[]` optional; `mentioned = union(valid anchors)`; `unassigned = source_anchors − mentioned` (код). L1 repair flow: parse→normalize→validate→remove invalid→recompute unassigned→drop пустые dependent→semantic validity→repaired map; fatal только при отсутствии полезной структуры; correction retry только для invalid_json/schema/empty. L2 evidence — тоже anchors; repair не убивает document; paragraph без evidence = reviewer signal. Расширяет существующий `summary_l1_repair.py` (pure/deterministic) на anchor-space, сохраняя membership-расширение и useless-verdict Q3.

**Альтернативы (отклонены):** наивная плотная шкала `m000001…` (owner запретил — silent alias); raw TG ids как контракт (BL-2); durable-хранение map (избыточно — map детерминированно строится из immutable окна; DDL=0). **Kill-switch:** `SUMMARY_SOURCE_ANCHORS_ENABLED` (+ `SUMMARY_L1_ANCHOR_REPAIR_ENABLED`, `SUMMARY_L2_EVIDENCE_REPAIR_ENABLED`, `SUMMARY_L2_TARGETED_REVISION_ENABLED`). **Consequences:** L1/L2 больше не валятся из-за одной битой ссылки; схема L1 bump v1→v2; raw id остаётся только внутри кода/derived views.

## D2. NanoGPT real provider contract — provider-specific routes (AM-3)

**Решение.** `ImageProviderAdapter` владеет provider-specific маршрутами (`submit_generation/submit_edit/get_status/get_result`). `NanoGPTImageAdapter.submit_edit` резолвит реальный маршрут по discovered endpoint-metadata модели (`GET /api/v1/images/models/{model}/endpoints` / legacy `image-models`): либо normalized Image API `POST /api/v1/images` с `input_references` (массив строк/data-URL **или** `{type:"image_url", image_url:{url}}`; нельзя смешивать с legacy-алиасами), либо OpenAI-compatible Image Edits `POST /api/v1/images/edit`/`/images/edits` с `imageDataUrl`/`imageDataUrls` (JSON) или multipart `image`/`image[]`. Auth `Authorization: Bearer` или `x-api-key`. Response `{data:[{url|b64_json}]}`; error codes `missing_image_input`/`image_input_too_large`/`invalid_input_references`/`conflicting_image_inputs`/`rate_limit_exceeded` и др. HTTP 400 body сохраняется sanitized (status/reason_code/message/request_id/route/model; без key/prompt/bytes). Generic adapter — только при реально совпадающем контракте; invented route запрещён.

**Альтернативы (отклонены):** оставить `{base_url}/images`+`input_references` как единственный путь (BL-4, HTTP 400); hardcode NanoGPT/Qwen. **Kill-switch:** `COVER_STYLE_PROVIDER_ROUTES_ENABLED`. **PO-1:** live-подтверждение route для `qwen-image-3-pro` + REAL canary (T-4831); контракт обеих веток уже верифицирован по docs, PO-1 сужен до model→route mapping + canary. **Consequences:** реальный edit работает или честный `route_unverified` → fail-soft Base Cover; provider 400 диагностируем.

## D3. Dynamic image prompt-limit + P0–P3 compiler (AM-4)

**Решение.** `ImageModelCapabilities.prompt_limit` реально заполняется по precedence: override → live provider metadata → live route metadata → verified adapter/docs registry → cached runtime-discovered → unknown. Machine-readable 400 (`prompt max N chars`) → extract N → cache per `provider+base_url+model+route` → recompile → **ONE retry**. Смена provider/model/base_url инвалидирует. Compiler расширяется до 4 уровней **P0** (механика edit) / **P1** (стиль-бренд) / **P2** (детали Summary) / **P3** (декор): сокращение P3→P2→semantic brief; P0+P1 абсолютный приоритет, никогда `[:N]`; если P0+P1 не помещаются → validated compact semantic profile, иначе `prompt_limit_exceeded` + Base Cover + понятная причина. Оригинальный style prompt хранится целиком в БД; compiled — derivative; Inspector `Original N / Resolved limit M / Compiled K`. Medved Press compact profile сохраняет ядро (сцена/персонажи/композиция, `PERMsoc`, branding, issue, 2–3 callouts, logo reference, русский текст).

**Альтернативы (отклонены):** глобальный hardcode `800` (owner запретил); `prompt[:N]` (запрещён); 3-уровневый compiler (owner требует P0–P3). **Kill-switch:** `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED`, `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED`. **Consequences:** лимит честный per-route; смысл стиля не теряется; `prompt_limit_exceeded` — first-class reason.

## D4. Capacity live-precedence + capability-aware reserve + streaming liveness (AM-2)

**Решение.**
1. Precedence capacity (owner §12): **explicit developer override → verified live provider/model metadata → verified route metadata → fresh provider cache → internal registry → conservative unknown.** Это **AMEND ADR-1028-8 D2** (там override был перемещён на уровень 4). Текущий `_resolve_uncached` (runtime→catalog→registry→override→fallback) переупорядочивается.
2. Cache key `provider+base_url+model+route/capability fingerprint`; смена инвалидирует; runtime 400/context-length → переоценка (существующий `invalidate_runtime_capacity`).
3. Output reserve capability-aware: `effective_context`, `max_output` (из live catalog — сейчас отбрасывается), `target_output`, `safety_margin`; существующий ratio-floor — только fallback при unknown.
4. Streaming liveness (AM-2): OpenAI-compatible `/chat/completions` с `stream=true` → приём SSE/events → `last_activity_at` → assemble; async jobs → poll реального endpoint; opaque sync → adaptive watchdog; hard deadline — только safety fuse, не health metric.
5. Retry single-owner: один `LLMExecutionSupervisor`, ≤4 HTTP на логический вызов, без stage-×3.

**Альтернативы (отклонены):** оставить override на уровне 4 (owner §12 явно требует уровень 1); fixed timeout как health-метрика (запрещено); выдуманный status/ping endpoint (запрещено). **Kill-switch:** `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED`, `SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED`, `SUMMARY_LLM_STREAMING_MODE_ENABLED`, `SUMMARY_LLM_SUPERVISOR_ENABLED`. **Consequences:** stale registry не занижает live capability; длинный живой запрос не убивается по wall-clock; reserve честный.

## D5. MiniApp layout/UX contract (more-sheet, test-style, seeds)

**Решение.** (1) `.more-sheet`: closed-state contract — unmount (`v-if`+transition) либо computed hidden/non-interactive; visible intersection = 0 px; не перехватывает pointer/touch; не лечится `.bottom-nav`/safe-area/`sticky-save bottom:+N`/padding/z-index. (2) SaveBar — отдельная layout-verification на 4 viewport. (3) Quick Access panel удаляется полностью. (4) Style cards — компактные before/after mini-images, arrow `MaterialSymbolsRounded`, preview снаружи editor, editor compact. (5) Test-style — не открывает File Explorer; реальный base+styled; не тратит counter; не публикует RichMessage; preview persist (`cover_style_profiles.preview_*`); fail → last success + понятная ошибка. (6) Seeds e2e (`medved_press.png` durable reference; `style_example_01/02` placeholders; provenance `Пример`/`Последний тест`). (7) Reference UI + RBAC (seeded Medved Press editable только admin, backend+API+UI). (8) Human naming.

**Альтернативы (отклонены):** пиксельные nudges (`translateY(115%)`, `bottom:+N`) — owner запретил; cosmetic fix; frontend-only RBAC (disabled button) — запрещено. **Kill-switch:** UI не имеет env-флага; rollback — revert статики + cache-bust. **Consequences:** root cause (dormant overlay) устранён; UX-регрессии закрыты контрактом, а не косметикой.

## D6. Inspector / observability (AM-5, additive)

Раздельно: L1 (input mode, source count, anchors generated/repaired/dropped, correction retry, map final status); L2 (paragraph count, evidence refs, invalid refs repaired, review issues, revision count, final status); Style (provider, model, adapter/route, original/compiled prompt chars, resolved prompt limit + source, references count, HTTP status, sanitized provider error, published cover styled/base/none). R17-safe (числа/коды; без ключей/промптов/байтов). Аддитивное расширение существующих Inspectors/events, не новый продукт.

---

## Sanctions (сводка)

| Решение | SQLite DDL | PostgreSQL | Kill-switches (env-only, default ON) |
|---|---|---|---|
| D1 anchors + L1 map v2 + L2 repair | 0 | no-op | `SUMMARY_SOURCE_ANCHORS_ENABLED`, `SUMMARY_L1_ANCHOR_REPAIR_ENABLED`, `SUMMARY_L2_EVIDENCE_REPAIR_ENABLED`, `SUMMARY_L2_TARGETED_REVISION_ENABLED` |
| D2 provider routes | 0 | no-op | `COVER_STYLE_PROVIDER_ROUTES_ENABLED` |
| D3 prompt-limit/compiler | 0 | no-op | `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED`, `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED` |
| D4 capacity/reserve/streaming | 0 | no-op | `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED`, `SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED`, `SUMMARY_LLM_STREAMING_MODE_ENABLED`, `SUMMARY_LLM_SUPERVISOR_ENABLED` |
| D5 MiniApp | 0 | no-op | UI — revert статики + cache-bust |

**OFF = бит-в-бит 2.58.47** (parity-тест каждой зоны). **DDL delta = 0**; preview persistence использует существующие `cover_style_profiles.preview_*`. Rollback: hot (флаги false + рестарт) / cold (revert feat-коммита, миграций нет). R17-скан обязателен перед релизом.

## Consequences для Builder/Reviewer/DevOps

- **Builder:** контракты spec §1–§5; DDL = 0; флаги §6; порядок owner (fix→targeted→integration→REAL canary→full suite). Mock не доказывает provider E2E (AM-3).
- **Reviewer:** линзы «механизм против заглушки»; no invented provider route/status API; OFF-паритет всех флагов; геометрическая (не только скриншот) проверка `.more-sheet`; AM-1…AM-5 выполнены по этому ADR; R17.
- **DevOps:** deploy после browser acceptance; DDL-миграций нет; prod acceptance §53–§57; archive запрещён до live-приёмок (§58); PO-1…PO-5 PENDING OWNER.

## История статуса

1. **04.10.2026 — Proposed (design):** D1–D6 утверждены как design-точки; AMEND-register AM-1…AM-5 зафиксирован; консистент-гейт с PM пройден (spec §9–§10); Risk R3; DDL = 0. Внешне верифицирован NanoGPT edit-контракт (docs.nano-gpt.com, 04.10.2026). Прод-валидация pending (delivery → canary → deploy → prod acceptance).

## Прод-валидация и история

2. **Round-2 review gate:** минификс [M-ASAP42-1] (guard `_assert_can_edit_seeded` в `cover_test_style` + allowlist-композиция гейт-тестов) — **Approved for deploy** (2026-10-04; release-blocking: 0; дельта-фингерпринт кодовой дельты `67a4245a…`, Spec-Hash прежний `2300990f…`; Round-1 WTH `5658e414…`).
3. **REAL canary (Step 4, T-4830/T-4831) — PASS 2/2** (mock не использовался; прод-сервис не тронут — только исходящие HTTP). Детали — `canary-evidence.md` (VERIFIED):
   - **(a) TEXT:** реальный `POST …/chat/completions` `stream=true` → **HTTP 200** `text/event-stream`, 8 SSE-событий + `[DONE]`, `assembled_len>0`, `on_activity`=15 (3.1 s) — упражнена реальная реализация SSE (T-4810).
   - **(b) NanoGPT Style Edit:** endpoint-discovery `GET …/images/models/qwen-image-3-pro/endpoints` → 200 → route **`image_api`** (`POST /api/v1/images` + `input_references`) → **HTTP 200**, **реальный image** 1 471 019 B (55.2 s, 0 ретраев) → **PO-1 (route) закрыт**; сценарий `route_unverified` не актуален.
4. **Deploy — VERIFIED 2.58.48 (04.10.2026):** прод ff `05a210c..b4dcb34` (feat `1da44b5` 99 файлов, docs `b4dcb34`; prod-HEAD/deploy-doc `8b96319`); рестарт 02:34:38 UTC (PID 3484893, NRestarts=0), health 200 `2.58.48`. Факты — `deployment.md` (VERIFIED):
   - **DDL=0** — `user_version` 24→24 (read-only PRAGMA до/после); anchors живут в immutable `summary_source_windows` + run-stage артефактах; PG no-op.
   - **Kill-switches — дефолт-паспорт:** 0 env-оверарайдов / 0 systemd Environment; **4 anchor-флага ON** (`SUMMARY_SOURCE_ANCHORS_ENABLED`, `SUMMARY_L1_ANCHOR_REPAIR_ENABLED`, `SUMMARY_L2_EVIDENCE_REPAIR_ENABLED`, `SUMMARY_L2_TARGETED_REVISION_ENABLED`), **5 «42»-свитчей ON** (`SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED`, `SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED`, `COVER_STYLE_PROVIDER_ROUTES_ENABLED`, `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED`, `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED`); **Mode A/B OFF** (`SUMMARY_LLM_ASYNC_MODE_ENABLED`/`_STREAMING_MODE_ENABLED`), **async batch OFF** (`EMBED_ASYNC_BATCH_ENABLED`) — контрактные слоты.
   - **RBAC-гейты (unauth):** `/api/analytics/pipeline/inspector` (+`?mode=structured`/`runs/abc`), `/api/memory/embeddings` → **401**; `POST /api/cover/test-style` → **401** (`missing init data`; test-style не публичный).
   - **Ladder/parity на прод-venv: 177 passed / 0 failed** (11 файлов asap41+asap42). **F8: CHECK OK реестр 488, EXIT=0** (Δ каталога = 0). **Посторонние ошибки: 0** (`ERROR|CRITICAL|Traceback` = 0; единственный WARNING — известный asap-4 GraphRAG embed-spend-parking, вне скоупа). **R17-скан: 0 хитов**.
   - **Ключи через ConfigCache:** живое доказательство — embedding HTTP 200 (`gemini-embedding-001`) при фиктивном env `LLM_API_KEY=401` → ключи резолвятся из каталога (ConfigCache), не из сырого env.
   - **Browser smoke (prod, unauth):** desktop 1280×800 + mobile 390×844 — closed `.more-sheet`/`.more-backdrop` **отсутствуют в DOM** (unmount; intersection 0 px, band hit-test 0 перехватов), **Modules Quick Access отсутствует**; **0 JS-ошибок**.
   - **Deploy-фактор:** первичный прямой SSH-22 таймаутил (транзиентный flap сетевого окна), порт восстановился спустя минуты; повторные пробы альтернативных портов закрыты; финальное соединение удачно — на результат не повлияло.
5. **PO-2…PO-5 — PENDING OWNER** (no-false-acceptance): реальный 1480-Summary run (Hybrid выживает / Legacy NOT used), живой Medved Press styled cover, Test Style не публичный/без расхода счётчика, stale sha `style_example_01/02` + аутентифицированный обзор. Архив фичи до live-приёмок запрещён.
