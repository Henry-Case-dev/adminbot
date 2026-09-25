# A4 `image-context-memory-round1026` — Evidence (Builder, T-3629..T-3639, T-3644, T-3645)

- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 4 — A4
- **Risk:** **R3** (ADR-1026-19 D10; spec §13)
- **Baseline anchor:** `e8646af` (HEAD == `origin/master`) + UNCOMMITTED epic-release
  tree A2/A3/A5/A6 (untouched/reverted/committed) — feature builds on top.
- **Feature dir:** `plans/features/image-context-memory-round1026/`
- **Spec:** `spec.md` (REQ-A4-01..17 → SC-A4-01..22) · **ADR:** `adr-1026-19-image-context-memory.md` (D1..D12, binding)
- **Release policy:** EPIC_ONLY — deploy **DEFERRED_TO_EPIC**; no commit/tag/bump by Builder.
- **APP_VERSION:** 2.58.30 (unchanged).

## Changed files (A4 contribution only)

Source:
- `services/image_context_memory.py` (**NEW**) — deterministic helper (D1/D2):
  `build_image_memory_context:414`, `_resolve_subject:167`, `_classify_visual:213`,
  `_bounded_slice:273`, `_apply_total_cap:340`, `attach_image_memory:483`,
  `build_reply_note:493`, `log_image_context_build:516`. Reuses A6 sources
  (`db.get_user_context_facts`, `memory.get_rag_facts/search_long_term`,
  `AliasResolver`/`build_alias_resolver`); does NOT import `tool_router`.
- `services/image_generation.py` — `image_context_memory_enabled():213`;
  `ImageRequest.memory_context:271`; 5-part `build_final_prompt:293` +
  `_build_memory_prompt:318` (§37 DATA label); `maybe_handle_keyword:1331`
  (aliases/db/memory + enrichment + reply note); `_enrich_request_with_memory:1386`.
  §104 functions (`generate`/`generate_image(_verbose)`/`extract_prompt`/
  `is_image_keyword`) untouched.
- `services/tool_router.py` — `_image_memory_note:317`; tool entry
  `_generate_image:2292` enriches via helper (`:2339`) and adds `note` on success.
  `_memory_lookup_*` (A6) NOT rewritten.
- `services/direct_chat_service.py:1610-1611` — `_image_pre_gate_block` forwards
  `self.aliases/self.db/self.memory` (only when present → backward compatible).
- `config/settings.py:969-980` — env-only ClassVars `IMAGE_CONTEXT_MEMORY_ENABLED`
  (default ON) + caps (`IMAGE_CONTEXT_FACTS_MAX/FACT_MAX_CHARS/SLICE_MAX/
  SLICE_MAX_CHARS/TOTAL_MAX_CHARS`). Δ каталога = 0 (ClassVar, не поля Settings).

Tests / artifacts:
- `tests/test_image_context_memory_round1026.py` (**NEW**, **34** scenarios).
- `plans/features/image-context-memory-round1026/threat-failure-analysis.md` (**NEW**, R3 artifact, 12 threats).

## T-3629..T-3639 + T-3644/T-3645 — status

- [x] **T-3629 идентификация** — reuse `AliasResolver`; alias-матч по токенам/стемам; first-person + `requester_id`; только по отображаемому имени — не резолвит.
- [x] **T-3630 неоднозначность/смешение** — >1 кандидат → `ambiguous`: 0 фактов, кандидаты только id, нейтральный арт + уточнение.
- [x] **T-3631 визуальные сведения** — лексикон (glasses/beard/hairstyle/clothing/appearance/preferences) + психологический denylist; `dossier_portrait` — только не-визуальный контекст; honest `no_visual_data`.
- [x] **T-3632 ограниченный срез + арт/портрет** — ленивый bounded slice; капы; дисклеймер «арт ≠ портрет»; маркер точного сходства → запрос фото/референса.
- [x] **T-3633 5-частная сборка** — независимые помеченные части; пример «самурай + очки»; лишние биографии не добавляются; `context_required=False` → байт-в-байт A3.
- [x] **T-3634 §37 + R17** — DATA-обёртка; инъекции из памяти остаются данными; ключи не в промпте/логах; R17-safe лог.
- [x] **T-3635 заглушки + оба входа** — `resolved_subjects/context_required/context_sources/memory_context` заполняются; direct и tool → один `run_image_request`; один helper.
- [x] **T-3636 §104-гейт + канон** — `TestBoundsA3` зелёный; канон 12; схема `generate_image` не менялась.
- [x] **T-3637 adversarial-тесты** — 34 сценария (см. ниже).
- [x] **T-3644 R3 `threat-failure-analysis.md`** — 12 threats, threat→mechanism→code→named test.
- [x] **T-3645 OFF-паритет** — `IMAGE_CONTEXT_MEMORY_ENABLED=OFF` → байт-в-байт A3; `UNIFIED_IMAGE_REQUEST_ENABLED=OFF` → legacy, helper не вызывается.
- [x] **T-3638 регресс** — полный pytest **9247/0**; JS 47/47; каталог без изменений; SQLite v12; `git diff --check`=0; APP_VERSION 2.58.30.
- [x] **T-3639 boundary audit** — см. ниже.

## Verification commands + actual results (T-3638/T-3639)

- `pytest -q` (full `.venv`) → **9247 passed / 0 failed** (153.5s). Baseline (A6, Step 0) = **9213/0**; **+34** = `tests/test_image_context_memory_round1026.py` (34). 0 regressions; no existing test files modified — the 3 initially failing legacy fakes were fixed by backward-compatible `getattr` access to optional deps.
- `tests/test_image_context_memory_round1026.py` → **34 passed**.
- A3 gate `tests/test_unified_image_request_round1026.py::TestBoundsA3` → **7 passed** (incl. `test_104_generator_functions_ast_identical`, `test_catalog_counts_unchanged`).
- A3+A6+A4 together → **108 passed**; legacy image/token suites (`test_image_generation_round1023`, `test_token_analytics_round1023`) → green.
- JS: `node tests/js/*.js` → **47/47, 0 failures**.
- Catalog: REGISTRY **470 · Settings 427 · categorized 445 · GROUPS 101 · _TAB_BY_GROUP 99 · TAB_RULES 21** = unchanged ✓.
- SQLite: full suite incl. `tests/test_database.py` (asserts `user_version` = **12**) ✓; Δ DDL = 0.
- `git diff --check` → exit **0** (only LF→CRLF informational warnings).
- `APP_VERSION` → **2.58.30** (unchanged; no bump).

## Boundary audit (T-3639, verified)

- **§104 no-go:** `generate`/`generate_image(_verbose)`/`extract_prompt`/`is_image_keyword` AST-identical to `e8646af` (`TestBoundsA3::test_104_generator_functions_ast_identical`, 7 passed). `generate_and_send` unwrapped by A4 (A5 wrapper intact).
- **A5 outside diff:** `services/worker_budget.py`/`pg_db.py`/`limits.*` not touched by A4 (helper grep: 0 `worker_budget`/DDL markers).
- **A6 not rewritten:** helper imports no `tool_router`; `_memory_lookup_*` untouched; reuses `AliasResolver` + `db.get_user_context_facts` + `memory.get_rag_facts/search_long_term`.
- **Canon 12 / no 13th tool:** `TOOL_CALLING_TOOLS == 12`, tail `get_user_context`; no `request_reference`/`portrait`; `tool_schemas.py` unchanged.
- **Δ каталога = 0 / Δ DDL = 0:** counts above unchanged; no CREATE/ALTER in touched sources; ClassVars outside `Settings` fields (427 unchanged).
- **A4 changed tracked files only:** `config/settings.py`, `services/direct_chat_service.py`, `services/image_generation.py`, `services/tool_router.py` (+ new untracked helper/test/threat file). Nothing from A5/A6/A7/§104.
- **R17/R18:** new log only `[image-ctx] build` (ids/enums/numbers/latency); no names/dossier/facts/prompt/keys. No commits/tags/branches; `current_task.md`/machine block/spec/ADR/backlog/metrics/ARCHITECTURE/MEMORY untouched; existing tags (`pre-round1026-*`) and `stash@{0}` intact.

## New test scenarios (`tests/test_image_context_memory_round1026.py`, 34)

- **Разрешение (B):** alias-match → resolved; same-name → ambiguous (0 фактов, кандидаты id, нет случайного выбора); уточнение; display-name-only не резолвит; first-person + requester_id; нет субъекта → память не читается.
- **Визуальный срез (C):** 6 визуальных категорий; psych-denylist блокирует; `dossier_portrait` только не-визуальный контекст; ленивый slice (spy: quotes не вызываются при наличии фактов); slice через RAG и сообщения; капы (facts ≤8/≤160, slice ≤3/≤200, total ≤1200); hard-клампы 10/5; нерелевантные биографии отбрасываются.
- **Сборка (D):** 5 независимых частей и порядок; не наивная конкатенация; пример «самурай + очки» без мусора; byte-parity A3 при `context_required=False`; дисклеймер в промпте+заметке; маркер точного сходства → фото/референс.
- **§37/adversarial (D):** инъекция остаётся в DATA-блоке, без системной эскалации; секреты `generator_config` не в промпте; R17-лог без имени/факта/dossier-текста/промпта.
- **Интеграция (E):** direct/tool заполняют заглушки и note; маркер `already_handled` → skipped без helper'а/генерации; `context_required` только при субъекте.
- **Флаги/§104 (E/F):** A4 OFF → byte-parity A3; A3 OFF (direct+tool) → legacy без helper'а; kill-switch вне каталога; счётчики каталога; канон 12.

## 14 acceptance invariants — status

1. Никакого полного дампа → **OK** (caps + визуальный фильтр; `test_caps_enforced_no_full_dump`).
2. Только task-relevant → **OK** (`test_non_visual_facts_never_included`).
3. Психология ≠ внешность → **OK** (`test_psych_denylist_blocks_appearance`, dossier non-visual).
4. Нет выдуманных черт лица → **OK** (часть 4 «не досочинять»; `no_visual_data`).
5. Арт ≠ достоверный портрет → **OK** (дисклеймер в промпте+note; фото-ветка).
6. Только существующая идентификация → **OK** (reuse AliasResolver; display-name-only не резолвит).
7. Нет случайного одноимённого → **OK** (`ambiguous`, candidates только id).
8. Неоднозначность → уточнение/отказ → **OK** (нейтральный арт + уточнение).
9. Досье не смешиваются → **OK** (`ambiguous` → 0 фактов, 0 чтений).
10. 5-частная сборка без конкатенации → **OK** (`TestPromptAssembly`).
11. Данные ≠ инструкции (§37) → **OK** (`TestSection37`).
12. Consume A6 без реимплементации → **OK** (helper без `tool_router`; reuse ридеров).
13. §104 no-go + A5 no-go + канон 12 → **OK** (boundary audit; AST-гейт).
14. R17/R18 + EPIC_ONLY → **OK** (лог R17-safe; нет commit/tag/bump; теги/stash целы).

## R17 / R18

- **R17:** единственный новый лог `[image-ctx] build | chat_id | subject_id | resolution | sources | facts | slice | prompt_chars | artistic_only | exact_likeness | empty_reason | latency_ms` — только id/enum/числа/латентность. Никаких имён/текста досье/фактов/сообщений/промпта/ключей.
- **R18:** коммитов/тегов/веток не создавалось; `plans/current_task.md` и машинный блок не изменялись; бэкапы/`stash` целы.

## Epic inputs contributed by this feature (release-candidate)

- Code: `services/image_context_memory.py` (new helper), `services/image_generation.py` (5-part prompt + hook + kill-switch), `services/tool_router.py` (tool-path enrichment + note), `services/direct_chat_service.py` (dep forwarding), `config/settings.py` (env-only switch+caps).
- Tests: `tests/test_image_context_memory_round1026.py` (new, 34).
- R3 artifact: `threat-failure-analysis.md` (12 threats).
- Deploy: **DEFERRED_TO_EPIC** (EPIC_ONLY) — no per-feature deploy/tag/bump; hot rollback `IMAGE_CONTEXT_MEMORY_ENABLED=OFF` / `UNIFIED_IMAGE_REQUEST_ENABLED=OFF`; cold `git revert` → `e8646af`.

## Checks not run / notes

- No network/LLM/provider calls (unit/adversarial only). `dossier_portrait` используется только как не-визуальный контекст; входящее фото — вне scope (§14).
- `artistic_only=not has_visual`: при наличии подтверждённых визуальных фактов дисклеймер не дублируется в note, но часть 4 промпта всё равно помечает вывод как иллюстрацию (инвариант 5).

## Review rework T-3640 (Builder, F1 + F2 + optional N1/N3)

Gate `review-T-3640.md` = **Needs Fixes** (F1 High, F2 Medium). Design unchanged
(spec §3.1 / ADR-1026-19); fixes are behavior-local. Reviewer's review file,
spec, ADR, `current_task.md`, machine block, backlog/metrics/ARCHITECTURE/MEMORY
and durable audit were NOT touched.

### F1 — alias collision no longer leaks a foreign dossier (HIGH)

- **Code:** `services/image_context_memory.py`
  - `_MIN_ALIAS_TOKEN_LEN = 4` + `_ALIAS_STOPLIST` (RU/EN image objects: кот/
    кошка/лис/малыш/ребёнок/медведь + dog/wolf/…): `:91-115`.
  - New `_alias_stems(value)` `:198-214` — eligible normalized alias tokens only:
    raw alias word must be `>= 4` chars (b) and NOT in `_ALIAS_STOPLIST` (c)/(d).
  - `_resolve_subject` `:217-244` now matches via `_alias_stems` `:235-236`.
- **Guard mechanism:** a shared stem with a short generic/image-object word can no
  longer produce a candidate → `resolution=none` → `context_required=False`, no
  `db.get_user_context_facts` read, prompt = `extract_prompt` (A3-parity).
  First-person/requester path (`_has_self_marker`) unchanged.
- **Spec note (honest):** literal "(a) no stemming at all" was NOT applied: spec
  §3.1 mandates casefold + one-step conservative stem for alias matching, and
  removing it would break spec-prescribed declension (e.g. alias «Лёха» ↔
  request «Лёху») and its existing tests. The collision vector is closed by
  min-length + stoplist + image-object classification on the exact normalized
  token (no partial/substring match). Flagged for Reviewer if stricter reading
  of (a) is required.
- **Tests (`tests/test_image_context_memory_round1026.py`):**
  `TestAliasCollisionGuard` `:203` — `test_alias_kot_collision_not_personalized:205`
  (`{"7":"Кот"}` + «нарисуй кота»), `test_alias_lis_collision_not_personalized:213`
  (`{"7":"Лис"}` + «нарисуй лису»), `test_alias_malysh_collision_not_personalized:220`
  (`{"7":"Малыш"}` + «нарисуй малыша»), `test_object_exact_token_not_personalized:227`
  (exact token), `test_short_alias_token_not_personalized:235` (<4),
  `test_real_alias_still_personalizes:243` (positive: «Лёха»/«Лёху» resolves and
  reads facts). Each negative asserts `context_required is False`,
  `resolved_subjects == []`, `context_sources == []`, `db.fact_calls == []`,
  `empty_reason == "unknown_person"` and no fact text ("очки") in the prompt.

### F2 — exact-likeness intent no longer dropped when subject unresolved (MEDIUM)

- **Code:**
  - `services/image_generation.py::_memory_reply_note:1402` — gate changed from
    `context_required` to `context_required OR exact_likeness`.
  - `services/tool_router.py::_image_memory_note:317` — same gate change.
  - Signal source unchanged (`image_context_memory._empty(exact=…)`), note still
    built by `build_reply_note` from flags only (R17: no dossier text).
- **Tests (`tests/test_image_context_memory_round1026.py`):**
  `TestExactLikenessGate` `:648` — `test_exact_likeness_unresolved_note:650`
  (unknown «Лёха» + «точное сходство» → reply has photo/reference request AND
  disclaimer; prompt A3-parity; no facts), `test_exact_likeness_resolved_note_regression:679`
  (resolved subject still notes), `test_unresolved_without_exact_intent_no_note:698`
  (no exact + unresolved → no note; A3-parity), `test_tool_exact_likeness_unresolved_note:719`
  (tool path same). Existing byte-parity test `test_byte_parity_when_context_not_required`
  stays green.

### Optional non-blocking (done, after F1/F2 green)

- **N1:** `TestSection37::test_injection_slice_stays_data:486`,
  `test_injection_dossier_stays_data:499`, `test_injection_preferences_stays_data:511`
  — injection stays inside the labeled DATA block for slice/dossier/preferences.
- **N3:** `TestKillSwitch::test_a4_off_no_memory_reads_at_all:773` — with A4 OFF,
  `db.fact_calls == []` and `memory.calls == []` (explicit spies).

### Rework verification numbers (exact)

- A4 suite: `pytest tests/test_image_context_memory_round1026.py -q` → **48 passed**
  (34 baseline + 10 F1/F2 + 4 N1/N3).
- §104 AST gate: `TestBoundsA3` → **7 passed**.
- A2/A3/A5/A6+A4+legacy image combined → **233 passed** (was 219; +14).
- Full regression: `pytest -q` → **9261 passed / 0 failed** (baseline 9247; +14).
- JS: `node tests/js/*.js` (per-file) → **47 pass / 0 fail**.
- Catalog: REGISTRY **470 · Settings 427 · categorized 445 · GROUPS 101 ·
  _TAB_BY_GROUP 99 · TAB_RULES 21** — unchanged. Canon **12** (tail `get_user_context`).
- `git diff --check` → exit **0** (LF/CRLF informational only). `APP_VERSION` **2.58.30**.
- Changed tracked files by this rework: `services/image_context_memory.py`,
  `services/image_generation.py`, `services/tool_router.py`; test file extended.
  No commit/tag/bump; 88-file epic tree intact.

## Blockers

None (2-attempt rule not triggered). F1/F2 fixes green; optional N1/N3 added.
Ready for independent re-review (T-3640; cycle-2 F1 rework above).

## Cycle 3 (T-3646, D13) — corroboration gate (class-closing identity guard)

Supersedes the cycle-1/2 stoplist-primary guard. Spec §3.1 (rewritten), ADR-1026-19
**D13**, SC-A4-09 (amended), spec §9 (a–i). Spec-Hash now
`63064ccbd5891bde4082d365e7c52def0e0640529a06f3eaa0fe632e33f840c7` (verified
by SHA-256 of `spec.md`). Alias match is now **only a candidate**; `resolved` is
issued exclusively by the corroboration gate.

### Gate implementation (`services/image_context_memory.py`)

- **G0 — eligibility (defense-in-depth):** `_alias_stems:262` keeps
  `_MIN_ALIAS_TOKEN_LEN=4` + `_ALIAS_STOPLIST:92`; `_stem:221`/casefold preserved
  (declension «Лёха»→«Лёху» still works). `_resolve_subject:279` returns
  `resolution="candidate"` + `candidates=[uid,…]` (never `resolved`); first-person
  (`_has_self_marker`) stays id-based `resolved:303`.
- **G1 — person-intent (mandatory, class-closing):** `_has_person_intent:328`;
  closed set `_PERSON_INTENT_TOKENS:124` / `_PERSON_INTENT_STEMS:138` /
  `_PERSON_INTENT_ABOUT:141`; `в образе` phrase. Fail → `_empty("no_person_intent")`
  at `build_image_memory_context:727`; **no roster/fact reads**. Capital letter is
  NOT used (casefold tokens only) → capital alone fails G1.
- **G2 — independent persona corroboration (mandatory; REQ-A4-09):**
  `_persona_names:390` (existing read `db.get_persona_names(chat_id, now)` —
  name+count only, NO fact text) + `_name_in_roster:404`. Corroborated candidates
  filter; 0 → `_empty("unknown_person")`; reader unavailable/`db=None` →
  `unknown_person` (fail-open none, no fact reads); ≥2 → ambiguous (`D5` neutral
  art + clarification, 0 dossier reads); exactly 1 → resolved.
- **G3 — image-object cross-check (defense-in-depth):** `_is_image_object:370` +
  `_candidate_is_image_object:383` over `_IMAGE_OBJECT_LEXICON:173` (derived from
  `_ALIAS_STOPLIST` + `_IMAGE_OBJECT_EXTRA:145`) and `_IMAGE_OBJECT_STEMS:231`,
  plus `_classify_visual` overlap. Applied **after G2** (spec order); firing →
  `none`, `empty_reason="no_person_intent"`.
- **Orchestration:** `_corroborate_subject:420` (G1→G2→G3) returns
  `eligible|no_person_intent|unknown_person`; `build_image_memory_context:700`
  routes `none`/`candidate`/`resolved`; resolved visual slice extracted into
  `_build_resolved_result:654` (single `user_id` isolation, REQ-A4-11 unchanged);
  `_ambiguous_result:691`. First-person path and OFF/parity unchanged.

### Async plumbing (both entries)

No caller changes were required: `image_generation._enrich_request_with_memory`
already passes `chat_id=request.chat_id` + `db` (direct), and
`tool_router._generate_image` already passes `chat_id=ctx.chat_id` + `deps.db`
(tool); `direct_chat_service._image_pre_gate_block` forwards
`self.aliases/self.db/self.memory`. G2's `db.get_persona_names` read therefore
works on both entries through the existing single helper signature (one
implementation, two call sites). No new dependency/env/DDL.

### Tests added (`tests/test_image_context_memory_round1026.py`)

`FakeDb` gained `get_persona_names` + `persona_names` (default `("Лёха",)`, R3:
name+count only, `roster_calls` spy). `_assert_no_personalization` accepts
`unknown_person | no_person_intent` (explicit reason where relevant). New
`TestCorroborationGateD13:294`:
- **(a) 6 cycle-2 repros** `test_cycle2_repros_no_person_intent:296`
  (Тигр/Роза/Панда/Зайка/Ромашка/Лисичка + generic) → `context_required False`,
  `resolved_subjects []`, `no_person_intent`, `fact_calls []`, `roster_calls []`,
  prompt = `extract_prompt`.
- **(b) 3 cycle-1 repros** stay green in `TestAliasCollisionGuard` (Кот/Лис/Малыш
  → `unknown_person` via G0).
- **(c) positives** `test_person_marker_resolves_declension_samurai:313`
  ({"7":"Лёха"} + «Нарисуй Лёху в образе самурая» → resolved, facts read) and
  `test_person_marker_how_looks_resolves:328` («как выглядит Лёха»).
- **(d) short name** `test_short_name_len4_blocks_even_with_marker:340`
  ({"7":"Лёв"} → none even with marker; G0).
- **(e) G1-negative** `test_g1_negative_bare_name_no_reads:350` and
  `test_capitalized_token_alone_not_person_intent:364` → `no_person_intent`, no reads.
- **(f) G2-negative** `test_g2_negative_unknown_person:375` (roster empty;
  roster read, facts NOT) and `test_g2_reader_unavailable_unknown_person:389`
  (no reader → fail-open `unknown_person`).
- **(g) G3** `test_g3_object_token_with_person_marker_blocks:408`
  ({"7":"Тигр"} + «тигра в образе самурая» → none after G2 pass) and
  `test_g3_classify_visual_overlap_blocks:422` ({"7":"Очки"}).
- **(h) stoplist active** as defense-in-depth (cycle-1 tests).
- **(i) class-closure** `test_class_closure_new_noun_bare:438`
  (Барракуда/Гироскутер/Синтезатор — вне любого лексикона + bare request →
  `no_person_intent`).
- **ambiguous via gate** `test_g2_pass_then_two_same_name_ambiguous:450`
  (2 corroborated → ambiguous, candidates `[1,2]`, 0 dossier reads).

### Spec §9 regression list — results

| §9 item | test | result |
|---|---|---|
| (a) 6 cycle-2 repros | `test_cycle2_repros_no_person_intent` (×6) | pass |
| (b) 3 cycle-1 repros | `TestAliasCollisionGuard` (Кот/Лис/Малыш) | pass |
| (c) positive + declension | `test_person_marker_resolves_declension_samurai`, `test_person_marker_how_looks_resolves` | pass |
| (d) short name | `test_short_name_len4_blocks_even_with_marker` | pass |
| (e) G1-negative (+capital) | `test_g1_negative_bare_name_no_reads`, `test_capitalized_token_alone_not_person_intent` | pass |
| (f) G2-negative (+unavailable) | `test_g2_negative_unknown_person`, `test_g2_reader_unavailable_unknown_person` | pass |
| (g) G3 | `test_g3_object_token_with_person_marker_blocks`, `test_g3_classify_visual_overlap_blocks` | pass |
| (h) stoplist defense-in-depth | cycle-1 guard tests | pass |
| (i) class-closure new noun | `test_class_closure_new_noun_bare` (×3) | pass |

### Verification numbers (cycle 3, exact)

- A4 suite `pytest tests/test_image_context_memory_round1026.py -q` → **67 passed**
  (cycle-2: 48; +19).
- §104 AST gate `tests/test_unified_image_request_round1026.py::TestBoundsA3` → **7 passed**.
- Combined A2/A3/A5/A6+A4+legacy image → **252 passed**.
- Full regression `pytest -q` → **9280 passed / 0 failed**, 1 warning (154.10s)
  (cycle-2: 9261; +19).
- JS `node tests/js/*.js` (per-file) → **47 pass / 0 fail**.
- Catalog: REGISTRY **470 · Settings 427 · categorized 445 · GROUPS 101 ·
  _TAB_BY_GROUP 99 · TAB_RULES 21** — unchanged. Canon **12** (tail `get_user_context`;
  no `request_reference`/`portrait`).
- `APP_VERSION` **2.58.30** (no bump); `git diff --check` → exit **0**; no trailing
  whitespace in the two edited/new source files.
- F2/N1/N3 intact: `TestExactLikenessGate` (4), `TestSection37` (6),
  `TestKillSwitch` incl. `test_a4_off_no_memory_reads_at_all` (4) all green.
- `_ALIAS_STOPLIST`/`_MIN_ALIAS_TOKEN_LEN`/`_stem` preserved (G0 defense-in-depth).

### Spec §3.1 interpretation choices (for Reviewer)

1. G1 «как выглядит/выглядел/выглядела» implemented as the stem `выгляд` (covers
   all three forms); «как» is not separately required (the forms are person-only).
   Required positives use `выгляд`/`в образе` and pass.
2. `про <токен>`/`о <токен>`/`об <токен>` implemented as presence of the
   standalone preposition token (`про`/`о`/`об`); not relied on by any required
   test.
3. `лицо/лица` and `образ*` are exact token forms (no loose stems) to avoid
   collisions with «лицензия»/«образец»/«образование».
4. G2 corroboration = casefold-exact match of the alias-derived name against
   `get_persona_names`; candidates are filtered by corroboration, then ≥2 →
   ambiguous, exactly 1 → resolved (aligns with spec «eligible alias-кандидат,
   прошедший G1+G2»). This is the conservative reading (more false-negatives).
5. G2 reader unavailable or `db=None` → `unknown_person` (fail-open none), never
   a personalization; no fact read.
6. First-person + `requester_id` remains id-based `resolved` and bypasses G1/G2
   (spec §3.1 signal 3; subject = requester, no foreign-dossier egress).
7. `no_person_intent` keeps `artistic_only=False` (same neutral A3-parity art as
   other `none` reasons); D5 neutral art means no personalization, prompt =
   `extract_prompt`.
8. F2 regression test updated to carry a person-marker («как выглядит Лёха,
   нужно точное сходство») because bare «нарисуй Лёху, нужно точное сходство» now
   correctly yields `no_person_intent` under D13; the F2 note gate itself is
   unchanged and still emits the photo/reference request for unresolved+exact.

### Cycle-3 status / blockers

- **T-3646 marked [x]** in `tasks.md` (code + tests complete).
- No 2-attempt-rule blocker triggered (gate green on first run after implementation).
- Uncommitted epic tree untouched; no spec/ADR edits (amendment authoritative);
  no commit/tag/bump; R17 (no names/fact text in logs) preserved.
- **Ready for Reviewer cycle 3: yes.** Fresh binding should be computed after this
  build (code + test + evidence changed; spec unchanged at `63064ccb…`).

## Cycle 4 (C3-H1 / C3-M1) — G1 exact closed-set matching

Targeted fix of Reviewer cycle-3 blockers. **Scope:** G1 person-intent only;
G0/G2/G3 logic, order and all other behavior unchanged. No spec/ADR edits
(Spec-Hash still `63064ccbd5891bde4082d365e7c52def0e0640529a06f3eaa0fe632e33f840c7`,
SHA-256 of `spec.md` re-verified). No commit/tag/bump/Scanner.

- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 4, раунд 10.26.
- **Baseline (before edit):** HEAD `e8646af`; A4 suite **67 passed**;
  `APP_VERSION 2.58.30`.
- **Changed files (both untracked, as before):**
  `services/image_context_memory.py`, `tests/test_image_context_memory_round1026.py`.

### Implementation (exact-set matching, no prefix)

- `_PERSON_INTENT_TOKENS:131-144` — unchanged exact-token set (человек/парень/
  друг/…/лицо/образ).
- `_PERSON_INTENT_MARKER_FORMS:148-166` — **new** explicit closed list of marker
  forms (`выглядит/выглядел/выглядела/…`, `портрет/портрета/портрету/…`,
  `внешность/внешности/внешне`, `фото/фотограф/…`, `снимок/снимка/…`, `досье`,
  **`похож/похожа/похожий/похожего/…`** ← C3-M1). Siblings that are *different
  words* (`фотон`, `фотоаппарат`, `фотография`, `фотомодель`, `портретист`,
  `снимать`) are deliberately absent.
- `_PERSON_INTENT_MARKER_STEMS:273-275` — stems derived from the forms
  (`_stem(form)`), compared by **EXACT equality**.
- `_has_person_intent:372-398` — matching is now
  `token in _PERSON_INTENT_TOKENS or _stem(token) in _PERSON_INTENT_MARKER_STEMS`.
  The old `token.startswith(stem)` and the old `_PERSON_INTENT_STEMS` tuple
  (line 138) are **removed**. `в образе` is matched as an exact token bigram
  (`tokens[i]=="в" and tokens[i+1]=="образе"`), not as a substring.
- **Preposition rule (conservative no-leak read):** `про/о/об` satisfies G1
  **only** when the immediately following token is an explicit person reference
  (`_PERSON_ABOUT_OBJECTS:173-177` = person-noun set ∪ self-tokens ∪ person
  pronouns). A bare `про <тема>` / `об <тема>` no longer satisfies G1; the old
  standalone-preposition marker is gone. **Documented ambiguity:** spec §3.1
  lists `про <токен>` without spelling out `<токен>`; a *named* person after a
  preposition (e.g. «про Сергея») is therefore intentionally **not** accepted —
  it is a conservative false-negative that cannot leak. Term of the rule:
  generic topics (`про космос`/`про море`/`об огнях`) and alias-topics cannot
  unlock personalization.

### Necessary complement in G3 (transparent deviation)

G1 exact matching alone leaves the **bare exact-token collisions** «Фото»,
«Снимок», «Досье» resolved, because these words *are* legitimate G1 markers
(spec §3.1) while also naming an image artifact. To satisfy the mandated leak
tests without weakening the markers, `_IMAGE_OBJECT_EXTRA:204-208` gained
`"фото", "снимок", "снимк", "досье"` — the existing G3 image-object
cross-check (data-only; logic/order unchanged; `"портрет"` was already there).
Effect: a bare request whose matched alias token is itself the artifact noun is
blocked by G3 (`no_person_intent`, 0 reads); phrase positives
(«фото Лёхи», «досье Лёхи») are untouched because the matched token is the
subject's name, not the artifact. This is the minimal way to satisfy both
"C3-H1 exact-token leak blocked" and "spec markers still pass"; flagged for
Reviewer as the one non-G1 touch.

### Regression tests added (`tests/test_image_context_memory_round1026.py:471-573`)

New `TestG1ExactMarkerCycle4:500` (+23 tests, A4 suite 67→**90**):

| # | test | coverage | result |
|---|---|---|---|
| 1 | `test_prefix_family_bare_not_personalized` (×8) | e2e: alias `{«7»: word}` + bare «нарисуй <word>» for Фотон/Фото/Фотоаппарат/Фотография/Фотомодель/Снимок/Портретист/Досье → `context_required=False`, `resolved_subjects=[]`, `fact_calls=[]`, A3-parity prompt | pass |
| 2 | `test_preposition_topic_not_personalized` (×3) | Кварк+«про космос», Закат+«про море», Город+«об огнях» → `no_person_intent`, `roster_calls=[]`, `fact_calls=[]` | pass |
| 3 | `test_pohozh_marker_resolves` | C3-M1: «нарисуй похожего на Лёху» → resolved uid=7, facts read | pass |
| 4 | `test_marker_positive_still_resolves` (×9) | «как выглядит», «портрет», «портрета» (declension), «внешность», «лицо», «фото Лёхи», «досье Лёхи», «в образе», «про подругу» → resolved, facts read | pass |
| 5 | `test_exact_marker_units` / `test_preposition_rule_narrow` | unit: фотон/фотоаппарат/фотография/фотомодель/портретист = False; фото/портрет/портрета/снимок/досье/похожего = True; «про космос/море/огнях» = False; «про человека/парня/меня» = True | pass |

### Independent-repro checks (own probe, real `build_image_memory_context`)

- 8 prefix-family leaks: all `context_required=False`, `resolved=[]`,
  `fact_calls=0`, `empty_reason=no_person_intent`. ✔
- 3 preposition leaks: all `False`, `fact_calls=0`, `no_person_intent`. ✔
- positives `выглядит` / `похожего` / `фото Лёхи` / `досье Лёхи` /
  `в образе` / `портрета Лёхи` / `внешность Лёхи`: all resolved uid=7, facts=1. ✔
- prior repros: cycle-1 (Кот/Лис/Малыш), cycle-2 (Тигр/Роза/Панда/Зайка/
  Ромашка/Лисичка), D13 class-closure (Барракуда/Гироскутер/Синтезатор) —
  green in suite. F2/N1/N3 (`TestExactLikenessGate` 4, `TestSection37` 6,
  `TestKillSwitch` 4) green.

### Verification numbers (cycle 4, exact)

| Проверка | Команда | Результат |
|---|---|---|
| A4 suite | `pytest tests/test_image_context_memory_round1026.py -q` | **90 passed** (cycle-3: 67; +23) |
| §104 AST-гейт | `pytest tests/test_unified_image_request_round1026.py::TestBoundsA3 -q` | **7 passed** |
| Полный регресс | `pytest -q` | **9303 passed / 0 failed**, 1 warning (154.20 с) (cycle-3: 9280) |
| JS | `node tests/js/*.js` (per-file) | **PASS=47 / FAIL=0** |
| Каталог | REGISTRY/Settings/categorized/GROUPS/_TAB_BY_GROUP/TAB_RULES | **470 / 427 / 445 / 101 / 99 / 21** (без изменений) |
| Канон | `TOOL_CALLING_TOOLS` | **12**, хвост `get_user_context`, нет `request_reference`/`portrait` |
| Версия | `APP_VERSION` | **2.58.30** (без bump) |
| Пробелы/CRLF | `git diff --check` | exit **0** (только LF→CRLF warning'и) |
| Spec-Hash | SHA-256 `spec.md` | `63064ccb…` — не изменён (spec/ADR не редактировались) |

### Cycle-4 status / blockers

- No 2-attempt-rule blocker triggered (gate green on first run after fix).
- No spec/ADR/backlog/metrics/ARCHITECTURE/MEMORY/current_task/review edits;
  no commit/tag/bump/Scanner; R17 preserved (no names/fact text added to logs).
- **Residual, documented (not blocking):** alias literally named «Фотограф»
  with bare «нарисуй фотографа» is not in the mandated leak set and is not
  added to G3 (profession word, ambiguous); named-person-after-preposition is
  a deliberate conservative false-negative (see above).
- **Ready for Reviewer cycle 4: yes.** Fresh binding should be computed after
  this build (code + test + evidence changed; spec unchanged at `63064ccb…`).
