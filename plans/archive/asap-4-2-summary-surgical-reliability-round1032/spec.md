# ASAP 4.2 — spec.md (lean design, @Architect T-4801, 04.10.2026)

**Feature ID:** `asap-4-2-summary-surgical-reliability`
**Mode:** design (lean — только реальные design-точки; не новый слой архитектуры)
**Источник (авторитет, не менять):** `plans/current_task.md:23847–25458` (§0–§60, DoD 50).
**PM-пакет:** `requirements-map.md` (R8-A…R8-Q, AM-1…AM-5), `tasks.md` (T-4800…T-4840), `reuse-inventory.md`.
**Связано:** ADR-1028-10 (D-решения + AMEND-register); AMEND/SUPERSEDE к ADR-1028-8 (D2/D3), ADR-1028-4 (D2/D4/D5), ADR-1028-5 (media adapter, паттерн-донор).

**Risk-Level: R3** — меняется моделе-обращённый контракт ссылок (L1/L2 anchors, schema bump), реальный provider edit-route и production acceptance-gate. R3 оправдан; **не** повышать до R4: всё env-kill-switch'ится, OFF = бит-в-бит 2.58.47, DDL = 0. Что может поднять риск: если live-дискавери покажет, что anchors требуют durable-хранения или смены носителя L1 (тогда DDL ≠ 0 → пересмотр).

**Browser-Verification: REQUIRED** — D6 меняет user-visible mobile/desktop layout, navigation, interactive state и test-style flow. Требуется Playwright (default) с геометрическими проверками; Browser Use дополнительно только для реального Telegram WebView/визуального приёма (см. §8).

---

## 0. Scope / excluded

**В scope (хирургически, в порядке владельца):** anchors + L1/L2 repair; Writer→Reviewer targeted revision; prompt-audit; capacity/reserve; streaming liveness; retry single-owner; реальный NanoGPT edit contract; dynamic image prompt-limit + P0–P3 compiler; Medved Press profile/seeds/RBAC; MiniApp layout/UX; targeted→integration→REAL canary→full suite; deploy→REAL prod acceptance.

**Исключено (не трогать, 25383–25393):** immutable `SummarySourceWindow` (только чтение), RichMessage renderer, Base Cover generation, unrelated GraphRAG, MCA features, message history, unrelated modules. Новый Summary-контур не строится — правим существующие модули (`reuse-inventory.md` §1–§2).

**Запрещённый anti-pattern (§0):** тяжёлый design → десятки волн → тысячи mock-тестов. Здесь: точечные правки → targeted → integration → REAL canary → ОДИН full suite → browser → deploy → REAL prod acceptance.

---

## 1. D1 — SourceAnchorMap (self-validating anchors; AM-1)

**Проблема (§2, BL-1/2):** LLM обязана перепечатывать длинные TG `message_id`; один `unknown_message_id` валит весь L1 (`summary_l1_contract.py:414/445/471`, `invalid_result`), L2 — весь document (`summary_l2_writer.py:134/938`).

**Формат (код создаёт, LLM видит только anchors):** `m` + 4-char base36 ordinal (0-padded, `0-9A-Z`) + `-` + 2-char base36 checksum, напр. `m00BD-K7`.
- **ordinal** — 0-based индекс сообщения в immutable `SummarySourceWindow.messages` (порядок детерминирован; окно write-once, DDL v24).
- **checksum** — `base36(sha256(run_fingerprint + ":" + real_message_id + ":" + ordinal)[:8] % 36²)`; `run_fingerprint` = короткий хэш `(run_id, chat_id, window_from, window_to)`.
- `real_message_id` = TG `message_id`; если отсутствует — stable `db_id` окна (обратный перевод честно возвращает то, что есть).

**Инварианты (§2, R8-A-002):**
1. mapping создаёт только код; LLM anchors не изобретает;
2. immutable на время run (frozen, строится один раз из immutable окна);
3. биекция: один anchor ↔ ровно один source message;
4. checksum валидируется кодом: parse → ordinal → реальный id из окна → пересчёт checksum → сравнение;
5. битый anchor не может тихо стать другим валидным source (checksum + ordinal не совпадут при опечатке);
6. после validation код переводит anchors обратно в реальные IDs для materialize/публикации;
7. mapping не попадает в публичный текст (R17; anchors допустимы только во внутренних LLM-промптах).

**Collision handling:** ordinal уникален ⇒ полные строки anchors уникальны. Build **asserts** `len(anchor→msg)==len(messages)` и отсутствие дублей; при нарушении — fail-open на repair-путь (anchor считается unknown). Типовая опечатка модели (`m0012→m0021`) не проходит checksum → unknown → local repair, silent alias невозможен.

**AM-1 (L1-карта v1→v2):** v1 (`summary_l1_semantic_map.py`, `MAP_SCHEMA_VERSION=1`) использует `message_ids` (raw TG). v2: `topics/events/relationships` несут `source_anchors[]` вместо `message_ids`; `unassigned_message_ids` → `unassigned_anchors[]` (**optional** — canonical считает код); `schema_version=2`. IdSpace → AnchorSpace. OFF-kill-switch → v1 байт-в-бит.

**`unassigned` вычисляет код (§3, R8-A-003):** `mentioned = union(valid anchors in topics/events/relationships)`; `unassigned = source_anchors − mentioned`. LLM-значение игнорируется; поле optional/не source-of-truth.

**L1 repair вместо invalidate (§4–§6, R8-B):** flow `parse → normalize → validate syntax/checksum → remove invalid anchors локально → recompute unassigned → drop только пустой dependent topic/event → semantic validity → repaired map`. Fatal только если после repair не осталось полезной структуры. Correction retry — только `invalid_json` / structural schema failure / пустой output, с конкретной validator reason; 1–2 broken anchor retry НЕ вызывают. L1 остаётся компактной картой (anchors/participants/hint, без full text/timestamps/author/chronology — materialize из SourceWindow). Расширяет существующий `summary_l1_repair.py` (deterministic, pure) на anchor-space; membership-расширение и useless-verdict Q3 сохраняются.

**L2 evidence repair (§7, R8-C):** paragraph несёт `source_anchors`; normalize → remove invalid → **paragraph остаётся** → Reviewer checks unsupported/misattributed. Paragraph без evidence после repair = reviewer signal, НЕ `document=None`→Legacy. `document=None` только при неремонтируемой структуре.

**Writer→Reviewer targeted revision + Full SourceWindow (§8–§9, R8-D):** `ReviewResult`: `paragraph_id`, `reason ∈ {wrong_speaker, bad_quote, bad_number_date, unsupported, lost_reply, no_evidence, mixed_people}`, `source_anchors[]`, `repair_instruction`. Writer на revision получает ТОЛЬКО paragraph + source excerpts + проблему; bounded (существующий ×2 patch-контракт), без whole-article regen. Reviewer видит оригинальный SourceWindow (source of truth); semantic map/fact package — подсказки. Prompt-audit (§10, R8-E): убрать противоречие «сырой истории нет» vs «вот полное окно — истина»; старые FactPackage-only формулировки удалить одним коммитом (канон+код+тесты).

---

## 2. D2 — Реальный NanoGPT edit contract (AM-3)

**Проблема (§18–§20, BL-4):** прод `nano-gpt.com / qwen-image-3-pro` → HTTP 400. Текущий код `cover_style_edit.py:38` постит `{base_url}/images` + `input_references` (data URL строки). Mock закрепляет invented-контракт.

**Верифицировано внешним источником (docs.nano-gpt.com, 04.10.2026 — authoritative):**
- Dedicated Image API: `POST /api/v1/images` (JSON-only). `input_references` — **массив** строк (URL/data-URL) **или** объектов `{type:"image_url", image_url:{url}}`. Нельзя смешивать с legacy-алиасами (`imageDataUrl`, `imageDataUrls`, `image_url`, `images`) → `conflicting_image_inputs`. Поля: `model` (required), `prompt`, `n`, `resolution`, `aspect_ratio`, `quality`, `output_format`, `seed`. `stream:true` не поддерживается (`unsupported_stream`).
- OpenAI-compatible Image Edits: `POST /api/v1/images/edit` и `POST /api/v1/images/edits` (алиасы). Multipart: `prompt` + `image`/`image[]` (+`mask`,`model`,`size`,`n`). JSON: `prompt` + `imageDataUrl` (single) / `imageDataUrls` (array) (+`maskDataUrl`). Auth: `Authorization: Bearer` **или** `x-api-key`.
- Response (обе ветки): OpenAI-совместимый `{created, data:[{url|b64_json}], cost, paymentSource, remainingBalance}`.
- Errors: `missing_image_input`, `image_input_too_large`, `invalid_multipart_body`, `rate_limit_exceeded`, `missing_model`, `invalid_content_type`, `invalid_input_references`, `conflicting_image_inputs`, `unsupported_stream`, `unsupported_provider_options`.
- Discovery: `GET /api/v1/images/models` + `GET /api/v1/images/models/{modelId}/endpoints` (dedicated) и `GET /api/v1/image-models?detailed=true` (legacy list).

**Design:**
- `ImageProviderAdapter` (существует, `media_execution.py:308`) получает provider-specific маршруты: `submit_generation / submit_edit / get_status / get_result`; generic-route не форсится.
- `NanoGPTImageAdapter.submit_edit` выбирает реальный маршрут по discovered endpoint-metadata модели: **Image API** (`input_references`) ИЛИ **Image Edits** (`imageDataUrl(s)`/multipart). Не изобретать; при отсутствии подтверждения → честный `route_unverified` → fail-soft Base Cover.
- References: base cover — 1-й input, style references — далее; соблюдать `input_reference_constraints.max_items` и `max_bytes` из endpoints.
- Auth: `Authorization: Bearer` (JSON), `x-api-key`/`Bearer` (multipart). Response/error extraction — tolerant к `url|b64_json` и к documented error codes.
- **HTTP 400 body не терять (§29, R8-I-004):** логировать `status, provider reason_code, sanitized message, request_id, route, model`; НЕ логировать key/full prompt/data-URL/reference bytes. Основной UI — человекочитаемо («Стиль не применён: провайдер отклонил запрос.»); machine reason — Developer details (§47).
- Generic adapter — только при реально совпадающем контракте.

**PO-1 (live, не code):** подтвердить для `qwen-image-3-pro` фактический route (Image API vs Image Edits) и точную field-mapping через live endpoints-metadata; выполнить REAL canary T-4831 с ключом владельца. Док-контракт уже зафиксирован — PO-1 сузился до model→route mapping + canary, не до «discover contract с нуля».

---

## 3. D3 — Dynamic image prompt-limit + P0–P3 compiler (AM-4)

**Проблема (§21–§26, BL-5):** `ImageModelCapabilities.prompt_limit` фактически не заполняется (`image_capabilities.py:174 parse_discovery` не парсит лимит) → `compile_prompt` идёт в unknown-ветку (`image_prompt_compiler.py:157`). Нельзя hardcode `800` и `prompt[:N]`.

**Precedence (§22, R8-J-002):** 1) explicit developer override → 2) live provider metadata → 3) live route metadata → 4) verified adapter/docs registry → 5) cached runtime-discovered → 6) unknown.
- Расширить `parse_discovery`: извлекать prompt-limit из model/endpoint metadata при наличии поля; иначе честный unknown.
- Machine-readable 400 (`prompt max N chars` / `maximum prompt length is N`) → extract N → cache per `provider+base_url+model+route` → recompile → **ONE retry**.
- Смена provider/model/base_url инвалидирует (не протекает `800`).
- Per-route: лимит резолвится по `provider+base_url+model+operation/route`, не глобально.

**Compiler P0–P3 (§24–§27, R8-J-004/006):** расширить `image_prompt_compiler.py` с 3 до 4 уровней: **P0** обязательная механика edit, **P1** сущность стиля/бренд, **P2** ключевые детали Summary, **P3** декоративные hints. Порядок сокращения: сначала P3, затем P2 → short semantic brief; **P0+P1 абсолютный приоритет**, никогда не режутся строковыми ножницами. Если P0+P1 не помещаются: validated compact semantic profile, иначе `prompt_limit_exceeded` → Base Cover публикуется + понятная причина в MiniApp.

**Сохранение смысла (§25, R8-J-005):** оригинальный style prompt хранится целиком в БД; compiled runtime prompt — отдельный derivative; Inspector показывает `Original N chars / Resolved limit M / Compiled K chars`.

**Medved Press compact profile (§27, R8-K-001):** ядро сохраняется — edit готовой Base Cover; сохранить сцену/персонажей/композицию; modern Russian graphic novel/comic; `PERMsoc` главный title; branding `Медведь Press`; issue number; 2–3 comic plaques/callouts; logo reference как branding; не плодить дубли; русский текст; печатная comic-композиция. Формулировку ужимать можно, смысл — нельзя.

---

## 4. D4 — Capacity resolver live-precedence + capability-aware reserve

**Проблема (§11–§13, BL-6):** stale family registry может занижать live capability; output reserve — один `4000`.

**Precedence (owner §12, AMEND ADR-1028-8 D2):** 1) explicit developer override → 2) verified live provider/model metadata → 3) verified route metadata → 4) fresh provider cache → 5) internal registry fallback → 6) conservative unknown.
- **Важно:** ADR-1028-8 D2 (ASAP 4.1) переместил override на уровень 4. Owner 4.2 §12 требует override на уровне 1 → **AMEND ADR-1028-8 D2**. Текущий `model_capacity.py:_resolve_uncached` (runtime→catalog→registry→override→fallback) должен стать override→live model metadata→live route metadata→fresh cache→registry→unknown.
- `WHOLE_WINDOW` если модель вмещает serialized source, иначе `CAPACITY_OVERFLOW` с coverage 100%; без 50000/N-messages/«важные» как normal flow.
- Cache key: `provider + base_url + model + route/capability fingerprint`; смена любого компонента инвалидирует; runtime 400/context-length → переоценка в рамках run (существующий `invalidate_runtime_capacity`).

**Output reserve capability-aware (§13, R8-F-004):** учитывать `effective_context`, `max_output` (из live catalog — сейчас парсится и отбрасывается, `model_capacity.py:548`), `target_output`, `safety_margin`. Не один вечный `4000`; fallback — существующий `output_reserve_tokens` (ratio floor 1024) только при unknown max_output.

**Streaming liveness (AM-2, §14–§16):** для OpenAI-compatible text route (`POST /chat/completions`, реальный маршрут `llm_client`) сначала проверять поддержку `stream=true`. Если да: submit stream → приём SSE/events → `last_activity_at` → assemble. Пока stream жив — запрос жив. Async jobs → poll реального endpoint; opaque sync → adaptive watchdog. Не пинговать несуществующий endpoint. Hard deadline — только safety fuse (`SUMMARY_LLM_HARD_DEADLINE_SECONDS`), НЕ primary health metric.
- Текущее состояние: `declare_execution_capabilities` всегда `streaming=False` (`summary_llm_supervisor.py:108`), Mode B — «контрактный слот» OFF. ASAP 4.2 активирует Mode B для верифицированного OpenAI-compatible chat-route; флаги `SUMMARY_LLM_STREAMING_MODE_ENABLED` / `SUMMARY_LLM_ASYNC_MODE_ENABLED` остаются (AMEND ADR-1028-8 D5.4: «слоты» → подтверждённый маршрут).

**Retry multiplication (§17, R8-H):** один `LLMExecutionSupervisor` владеет lifecycle (primary → optional transport retry → fallback provider/model → optional fallback transport retry → final failure); stage не запускает свои ×3; Inspector показывает реальное число network attempts (≤4 HTTP).

---

## 5. D5 — MiniApp layout/UX contract (§31–§47, BL-9)

**D5.1 `.more-sheet` root cause (R8-M-001, DoD 33/34/48):** закрытая шторка остаётся fixed-слоем (z-index 50) и лишь уезжает `transform: translateY(110%)` (`web/index.html:5477`, `app.css:2333-2356`) — часть торчит и перекрывает SaveBar. **Контракт closed-state:** при `moreOpen=false` шторка либо отсутствует в DOM (`v-if`+transition, как backdrop `index.html:5475`), либо computed hidden/non-interactive; visible intersection с viewport = **0 px**; не перехватывает pointer/touch; не создаёт stacking overlay. **НЕ лечить** высотой `.bottom-nav`, размером кнопок, safe-area, `sticky-save bottom:+N`, padding, z-index SaveBar. Проверка — геометрическая (`getBoundingClientRect`/hit-test), не только скриншот.

**D5.2 SaveBar contract (R8-M-002):** после фикса отдельно на mobile portrait / Telegram WebView / desktop narrow / wide — доступен, не перекрывает поля, без пустой полосы, нормальная z-index, content доскролливается до последнего поля. Не смешивать с D5.1.

**D5.3 Quick Access (R8-M-003):** удалить панель «Быстрое управление» (`index.html:2373`) полностью; один список/сетка module cards (название/человеческое описание/status/toggle/избранное/Настроить); не заменять дублем.

**D5.4 Style cards/editor (R8-M-004):** в списке — компактные before/after mini-images (не full-size); arrow — `MaterialSymbolsRounded[FILL,GRAD,opsz,wght]`, не текстовый `→`; before/after **снаружи** editor dialog; в editor preview компактный (разумные max-width/height), desktop/mobile адаптивны; giant image wall удалён.

**D5.5 Test-style UX (R8-K-006, DoD 26–29):** «Протестировать стиль» НЕ открывает File Explorer (wiring bug); запускает тестовый pipeline: safe test brief → реальная Base Cover через configured provider/model → реальная Style Edit → две реальные картинки → Base→Styled. **Не** тратит production issue counter (существующий `preview_issue_number`/`MODE_PREVIEW`), **не** публикует RichMessage. Preview обновляется и **сохраняется** (существующие `cover_style_profiles.preview_before_asset_id/preview_after_asset_id/preview_revision`, `cover_style_registry.set_preview`). Fail → последний успех не уничтожать + понятная ошибка; если успеха не было — seeded placeholders.

**D5.6 Seeds end-to-end (R8-K-003/004/005):** `medved_press.png` — реальный durable reference по цепочке `cover_style_references(medved_press)` → `cover_style_assets` (filename/sha256/disk_path) → asset-serving API (те же bytes); если корректно — не трогать, зафиксировать evidence; stale — чинить конкретный defect, без дубля. `style_example_01.png` (Before) / `style_example_02.jpg` (After) — seeded placeholders (`cover_style_registry.SEED_FILES`). UI различает `Пример` / `Последний тест`; placeholder не выдаётся за real test.

**D5.7 Reference UI + RBAC (R8-K-007/008, DoD 23/30/31/45):** миниатюра/название/role description/заменить-удалить при правах; upload отделён от test-style; `medved_press.png` связан с реальным `asset_id`; сквозная трассируемость. Medved Press — полноценный style entity (тот же contract/editor/seed/issue numbering/refs/connection override), не hardcoded if/else; seeded редактирует только admin (backend RBAC + API + UI + `Доступы/Права`, не только disabled button); non-admin видит/выбирает по правам, но не меняет canonical definition/refs/issue/provider; custom styles — общая permission model.

**D5.8 Human naming (R8-M-005):** русский нейминг + краткое описание; developer key вторично; machine reason — в Developer details; основной UI: «Стиль не применён: провайдер отклонил запрос.».

---

## 6. DDL delta / kill-switches / rollback

**DDL delta = 0.** Anchors и `unassigned` вычисляются из immutable `SummarySourceWindow`; L1-map v2 и L2 evidence живут в существующих run-stage артефактах (`summary_runs`/`summary_run_stages`, v24). Preview persistence использует существующие `cover_style_profiles.preview_*` (PG). Ни одной новой таблицы/колонки. Если live-дискавери выявит необходимость durable-хранения anchors — вернуться к Architect (риск ↑).

**Kill-switches (env-only, default ON, OFF = бит-в-бит 2.58.47; parity-тест каждой зоны):**
| Зона | Флаг |
|---|---|
| anchors + L1 map v2 + code-unassigned | `SUMMARY_SOURCE_ANCHORS_ENABLED` |
| L1 anchor repair policy | `SUMMARY_L1_ANCHOR_REPAIR_ENABLED` |
| L2 evidence repair | `SUMMARY_L2_EVIDENCE_REPAIR_ENABLED` |
| L2 targeted revision | `SUMMARY_L2_TARGETED_REVISION_ENABLED` |
| capacity live-precedence | `SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED` |
| capability-aware reserve | `SUMMARY_OUTPUT_RESERVE_CAPABILITY_ENABLED` |
| streaming Mode B | `SUMMARY_LLM_STREAMING_MODE_ENABLED` (existing; OFF-слот → подтверждённый route) |
| NanoGPT provider routes | `COVER_STYLE_PROVIDER_ROUTES_ENABLED` |
| dynamic prompt-limit | `IMAGE_PROMPT_LIMIT_DYNAMIC_ENABLED` |
| P0–P3 semantic compression | `IMAGE_PROMPT_SEMANTIC_COMPRESSION_ENABLED` |
| retry single-owner | `SUMMARY_LLM_SUPERVISOR_ENABLED` (existing) |

UI (D5.1–D5.8) не имеет env-kill-switch: rollback — revert статики + cache-bust `APP_VERSION`/`?v=`.

**Rollback:** hot — перечисленные env-флаги `false` + рестарт (OFF = 2.58.47); cold — revert feat-коммита (DDL = 0, миграций нет); restore не требуется (нет DDL). Provider routes: при красном canary — `COVER_STYLE_PROVIDER_ROUTES_ENABLED=false` → прежний (fail-soft Base Cover) путь.

---

## 7. Acceptance scenarios (compact; полные — tasks.md)

1. **Anchors:** fixture с 1 битым anchor → L1 usable/repaired, valid структура сохранена; «1 битый → entire INVALID» невозможно; checksum-mismatch rejected; silent alias невозможен; reverse-mapping → real id; unassigned пересчитан кодом; mapping не в публичном тексте (R17).
2. **L1 correction:** broken-anchor-only → НЕ retry; invalid_json/schema/empty → retry с reason.
3. **L2:** 1 битый evidence → документ публикуем, абзац сохранён + reviewer signal; `document=None` только при неремонтируемом; targeted revision правит один абзац (bounded), whole-article regen не вызывается; §47 wrong-speaker ловится из оригинала.
4. **Capacity:** live metadata сильнее stale registry; смена provider/model/base_url → re-resolve; WHOLE_WINDOW/overflow 100%; разный reserve из capability.
5. **Streaming:** real canary `stream=true` → SSE activity → `last_activity` → финал; живой длинный запрос не убит wall-clock; зависший → cancel/fallback.
6. **NanoGPT edit:** adapter/unit под верифицированный контракт (обе ветки); HTTP 400 diagnostics без секретов; REAL canary → HTTP 2xx + реальный image; mock не засчитывается.
7. **Prompt-limit:** precedence; 400-extract → cache → ровно 1 retry; `800` не управляет лимитом; P0/P1 не режутся; непомещаемый P0+P1 → `prompt_limit_exceeded` + Base Cover; оригинал цел; Inspector 3 числа.
8. **Medved/seeds/RBAC:** seed→list→preview→test→update на реальных `extra_images`; `medved_press.png` e2e (bytes/sha256, без дубля); placeholders seeded; provenance-метки; seeded editable только admin; non-admin не меняет canonical.
9. **MiniApp (Browser):** closed `.more-sheet` visible intersection = 0 / SaveBar видим/кликабелен / bottom-nav нормального размера; open работает; Quick Access отсутствует в DOM; style list compact; arrow — Material icon; before/after до editor; test-style не открывает file picker, не тратит counter, previews persist; human naming.
10. **Integration:** synthetic SourceWindow 1000+ с 1 bad L1 anchor + 1 bad L2 evidence → **Hybrid survives, Legacy not used**.
11. **Prod acceptance №1–№5** (§53–§57): большой Summary HYBRID без Legacy; Medved Press Style Edit HTTP 2xx + styled cover; Test Style e2e; UI (closed more-sheet 0px); смена provider → re-resolve, `800` не протекает. Archive запрещён до live-приёмок (§58).

**Browser-verification contract (D5):** entry points — MiniApp `/` (Modules, Cover Styles list, Style Editor, sticky-save страницы). Prerequisite state — seeded `extra_images` (medved_press.png + placeholders), desktop 1280×800 и mobile 390×844, Telegram-WebView-эмуляция через существующий shell (`isMobileShell`). Auth — существующая сессия MiniApp (не изобретать credentials). Interactions/состояния: open/close «Ещё» (после transition), scroll до SaveBar, открыть Medved Press, запустить «Протестировать стиль», reopen. Observable outcomes — геометрия (`getBoundingClientRect`/hit-test) для D5.1; DOM-отсутствие Quick Access; compact-размеры before/after; Material-icon arrow; отсутствие file-picker и расхода counter; persistence preview. Console/network — фиксировать только ошибки JS и факт вызова edit/generate endpoints. Structured browser checks — D5.1/D5.2/D5.3/D5.5; visual screenshot — D5.4/D5.6/D5.8 (компактность/иконка/нейминг). Playwright MCP — default; Browser Use — дополнительно для реального Telegram WebView/визуального приёма.

---

## 8. PO-1 split — что реально требует live-дискавери

**Можно сделать по коду (без PO-1):**
- SourceAnchorMap + L1 map v2 + code-unassigned + L1/L2 repair (D1) — чистая логика, код+unit.
- P0–P3 compiler, original/compiled split, no `[:N]`, `prompt_limit_exceeded` (D3, кроме фактического значения лимита).
- Capacity live-precedence (reorder) + capability-aware reserve + cache key (D4).
- Streaming Mode B для OpenAI-compatible `/chat/completions` (реальный маршрут уже используется `llm_client`) — D4.
- Retry single-owner verification (D4).
- MiniApp D5.1–D5.8 (root-cause layout, Quick Access, compact cards, test-style wiring, seeds/provenance/RBAC, naming).
- NanoGPT adapter **скелет + route-resolution по discovered endpoint-metadata + tolerant response/error + sanitized 400** — контракт обеих веток уже верифицирован по docs (D2).

**Требует PO-1 (live/owner):**
- Подтверждение фактического route для `qwen-image-3-pro` (Image API `input_references` vs Image Edits `imageDataUrl(s)`/multipart) через live `GET /api/v1/images/models/{model}/endpoints`; возможен ключ/доступ владельца.
- REAL text canary (stream) и REAL NanoGPT edit canary (T-4830/T-4831) с production-ключом.
- Фактическое наличие prompt-limit поля в live metadata либо получение N из machine-readable 400 (D3).
- Prod acceptance №1–№5 (T-4835–T-4839), prod-URL/сессия (PO-2), production-run (PO-3), подтверждение «test не публикует/не тратит counter» (PO-4), решение по stale seeded asset (PO-5).

> Если live-дискавери покажет, что prompt-limit не экспонируется ни metadata, ни 400 — лимит остаётся `unknown`, и P0+P1-ветка работает по `unknown`-policy (включаем всё, без ложных чисел), а не через hardcode.

---

## 9. Матрица spec → tasks (T-4800…T-4840)

| Spec-точка | R8 | Задачи |
|---|---|---|
| D1 anchors + SourceAnchorMap + reverse/R17 | A-001/002/004 | T-4802 |
| D1 code-unassigned | A-003 | T-4803 |
| D1 L1 repair + correction policy + compact map | B-001/002/003 | T-4804 |
| D1 L2 evidence repair | C-001 | T-4805 |
| D1 Reviewer verdict + targeted revision + Full SourceWindow | D-001/002/003 | T-4806 |
| D1 prompt-audit | E-001 | T-4807 |
| D4 capacity precedence + cache key + WHOLE_WINDOW | F-001/002/003 | T-4808 |
| D4 capability-aware reserve | F-004 | T-4809 |
| D4 streaming liveness + fuse (AM-2) | G-001/002/003 | T-4810 |
| D4 retry single-owner | H-001 | T-4811 |
| D2 NanoGPT real contract + adapter routes (AM-3) | I-001/002/003 | T-4812 |
| D2 HTTP 400 diagnostics | I-004 | T-4813 |
| D3 dynamic prompt-limit + cache (AM-4) | J-001/002/003 | T-4814 |
| D3 P0–P3 compiler + overflow reason | J-004/006 | T-4815 |
| D3 original/compiled + Inspector numbers | J-005 | T-4816 |
| D3 Medved Press compact profile | K-001 | T-4817 |
| D5.6 seeds e2e + provenance | K-003/004/005 | T-4818 |
| D5.5 test-style real semantics | K-006 | T-4819 |
| D5.7 reference UI + traceability | K-007 | T-4820 |
| D5.7 style entity + RBAC | K-008 | T-4821 |
| D5 cover fail-soft regression | K-002 | T-4822 |
| D5.1 more-sheet root cause | M-001 | T-4823 |
| D5.2 SaveBar contract | M-002 | T-4824 |
| D5.3 Quick Access removal | M-003 | T-4825 |
| D5.4 compact cards/editor + arrow | M-004 | T-4826 |
| D5.8 human naming | M-005 | T-4827 |
| targeted tests | N-001 | T-4828 |
| local integration | N-002 | T-4829 |
| REAL text canary | N-003 | T-4830 |
| REAL NanoGPT canary | N-004 | T-4831 |
| one full suite | N-005 | T-4832 |
| browser acceptance | O-001 | T-4833 |
| deploy | P-001 | T-4834 |
| prod acceptance №1–№5 | P-002…P-006 | T-4835–T-4839 |
| archive gate + MCA return | Q-001 | T-4840 |

**Coverage:** каждая spec-точка (D1–D5 + seeds/RBAC + retry) маппится на ≥1 задачу; каждая задача T-4802…T-4839 маппится на spec-точку; T-4800/T-4801 — planning/design; T-4840 — gate. Orphan-задач нет.

---

## 10. Design-консистент-гейт (для PM/Orchestrator)

- Все принятые R8-требования → поведение spec + задача/верификация (§9). ✔
- Каждая задача Step 1 → принятый scope. ✔
- Exclusions/risk/DDL/kill-switches/rollback согласованы: DDL = 0, env-only флаги, OFF=2.58.47, R3. ✔
- Открытых ARCHITECT_DECISION_REQUIRED нет: owner-директивы разрешают спорные точки (override-level 1, anchors вместо raw ids, реальный provider contract). Единственный live-блокер — PO-1 (model→route + canary), не user-tradeoff.

**Spec-hash:** вычисляется при передаче в Orchestrator (SHA-256 файла spec.md на момент design-freeze).
