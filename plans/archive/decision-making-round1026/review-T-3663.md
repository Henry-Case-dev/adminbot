# A7 `decision-making-round1026` — Review T-3663 (единый Reviewer gate)

- **Feature-ID:** `decision-making-round1026` (Эпик 3 Wave 5).
- **Risk-Level:** **R3** (подтверждён по фактическому diff; понижения до R2 не делаю — AMEND пайплайна + каталожно-UI + кор-поведение живого direct-чата).
- **Release policy:** EPIC_ONLY — deploy `DEFERRED_TO_EPIC`; пер-фича commit/tag/bump нет; @DevOps не вызывается.
- **Gate type:** feature gate (не aggregate epic release gate).
- **Status:** **Needs Fixes** — есть подтверждённые High + требующие фикса Medium (см. Findings).

## Binding (bound to this exact reviewed state)

- **Reviewed-Commit (HEAD):** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` (== baseline; A7 uncommitted).
- **Spec-Hash (`spec.md`, full file):** `950c5f8039791ae4353449ae53bc31e1aa244f585ed3320522de72c364d52ea0`.
- **ADR-Hash (`adr-1026-20-…md`):** `9166bef204e76606ef743f6500101acec0006cf59e3f2ff4c5152b2f7fc97173`.
- **Tasks-Hash:** `b9432d814b4c4b6277e169d4a061f5c1077e3500ef4193e6203ec2730ad04ea1`.
- **Evidence-Hash:** `863a9ff8fe03e423c629246c75ecbcd3b21a9dcdc30cbfedf69ee1ca89fdd2eb`.
- **Threat-File-Hash:** `d7fc3627344b78e076af1e6bd45f9e0a63f865755d663632722dda3e37475693`.
- **New-test-Hash (`tests/test_decision_making_round1026.py`):** `bb657f84904926c00d7811f0dcdc4b028f2737639b8f55c60cdca9623d3dfc39`.
- **Working-Tree-Hash:** `710281b56028a99cf875006c14f7ada1f80db17d82f5819b5ed6c901f0386a29`.
  - **Recipe (deterministic review manifest):** UTF-8 text = `DIFF:\n` + output of `git diff e8646af --binary` (staged+unstaged, all paths) + `\nSTATUS:\n` + output of `git status --porcelain` + `\nUNTRACKED-TEST:` + sha256 hex of `tests/test_decision_making_round1026.py`; then sha256 of that UTF-8 byte stream. (New untracked A7 file is pinned by its own content hash because `git diff` cannot include it; `git status --porcelain` pins its presence.)
- **Git base / inspected scope:** base `e8646af`; committed diff vs base = 0 (HEAD==base); inspected uncommitted epic-release tree (A2/A3/A5/A6/A4 + A7) over all changed paths, with focus on A7-sanctioned files: `services/direct_chat_service.py` (+412/−13), `config/settings.py` (+88/−0), `services/param_catalog.py` (+39/−1), `web/app.js` (+38/−2), `web/index.html` (+35/−0, A5), plus new test file and feature artifacts.

> Любое изменение кода/неотслеживаемых A7-файлов/сгенерированных release-входов/spec после этой ревизии делает approval стале. Вердикт ниже — `Needs Fixes`, повторный gate обязателен после правок.

## Checks performed (independently reproduced)

| Проверка | Команда | Результат |
|---|---|---|
| A7 test file | `pytest tests/test_decision_making_round1026.py -q` | **68 passed** |
| Direct-chat + catalog + F8 | `pytest tests/test_direct_chat.py tests/test_param_catalog.py tests/test_round1025_f8_registry.py -q` | **222 passed** |
| A1/regression sweep | `pytest test_tool_coordinator_round1026 test_direct_two_call_round1022 test_webapp_parity_smoke test_frontend_tab_mapping -q` | **122 passed** |
| Full suite | `pytest -q` | **9371 passed, 0 failed** (151.93s) |
| F8 registry | `python tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 473** |
| Catalog counts (direct read) | python probe | canon **12**; REGISTRY **473**; fields **430**; categorized **448**; GROUPS **102**; `_TAB_BY_GROUP` **100**; `TAB_RULES` **21** |
| JS suite | `node tests/js/*.js` (exit-code based) | **47/47 exit 0** (one harness prints an expected DOMPurify warning; exit 0). Note: Builder's "47/47" is exit-based, not the `JS-UNIT-OK` marker (only 8 files print it). |
| diff whitespace | `git diff --check e8646af` | exit **0** (LF→CRLF informational warnings only) |
| APP_VERSION | read | **2.58.30** (no bump) |
| DDL | grep CREATE/ALTER in `direct_chat_service.py` | none (`Δ DDL = 0`) |

## Lens 1 — requirement / correctness

**Covered and verified (positive).**
- REQ-A7-02/-04/-05/-06/-08/-09: `CoordinatorDecision` extended additively (`target_message_id`/`reaction`/`reason_code`/`needs_tools`), `__post_init__` normalizes invalid action→reply, `style=="silent"`→"", reaction only on `react`, reason forced into closed enum. Tests `test_actions_split_from_style`, `test_invalid_action_normalized_to_reply`, `test_reaction_only_on_react`, `test_reason_must_be_closed_enum`, `test_additive_fields_present`.
- REQ-A7-10: decision is an internal dataclass, no `to_json`; Stage-1/Stage-2 JSON unchanged (`test_decision_is_internal_not_json`, `test_stage_json_contracts_unchanged`); outbound path sends only `answer` text/`react_moai` — no service JSON in chat text.
- REQ-A7-11/-12/-14/-15/-17: policy priority verified independently via probes: `«Бот, нарисуй кота»→reply/explicit_request`, `«Почему?»→reply/question`, `«АХАХА»→react/laughter/🗿`, `«Ок»→silent/acknowledgement`; adversarial: explicit/question never silent across toggle matrices.
- REQ-A7-19: no `random` in `_decision_pre_action` (source check); determinism 25× (`test_deterministic_no_randomness`).
- REQ-A7-22/-23/-26: `handle()` short-circuits silent/react **before** system-prompt build and any LLM call; spies confirm `llm.generate.await_count==0`, `_synthesize_direct_answer` not awaited, `_send_direct_answer` not awaited, `react_moai` awaited once with `(bot, chat_id, trigger_message_id)`. (Boundary limitation: `_synthesize_direct_answer` is patched in tests, so this proves "no Stage-2/no text call in the short-circuit path", not an independent count of physical provider calls — see F-6.)
- REQ-A7-24/-25: reply path continues (1 generate call); tool path unchanged; degraded/failed tool → `tool_unavailable`.
- REQ-A7-29/-30/-31/-32: exactly 3 params + 1 group in `mod_direct`; route/description match §48 verbatim; `per_chat=True`; global/default and local override resolution covered.
- REQ-A7-27/-28 (partial): image-laugh → react; question-after-image → reply; not-addressed → silent.
- Kill-switch default ON; OFF → policy not built (`test_off_killswitch_parity_reply` + source read).

**Boundaries NOT satisfied / evidence gaps (see Findings):**
- §46 `tool` final action and §43 tool-unavailable-as-reply are misrepresented in evidence (F-1).
- §47 several context requirements are declaratively implemented but not actually consumed (F-2).
- Silence semantics vs §42 bare-question examples (F-3) and image-override (F-4).
- `reason_code` closed enum contradicts `disabled` for OFF (F-5).

## Lens 2 — focused change audit (R3-strengthened)

**No 3rd LLM call.** Phase P is pure programmatic over existing signals (`_decision_message_class`, `_decision_pre_action`, `_decision_context`, `_decision_toggles`) with 0 LLM calls; Phase T reuses existing `_coordinator_choose_action` + `_coordinator_reason`; Stage-1/Stage-2 JSON and prompts untouched (`system2_handoff.py` diff vs `e8646af` = **0**). No new LLM call point. ✔

**A1 AMEND, not duplicate.** Single `CoordinatorDecision` extended additively; A1 fields preserved; `DIRECT_COORDINATOR_ENABLED` path intact; no second coordinator/dataclass. ✔

**A2–A6 untouched by A7.** `services/tool_loop.py`, `tool_schemas.py`, `image_generation.py`, `worker_budget.py`, `tool_router.py`, `system2_handoff.py`, `database.py`, `pg_db.py` contain **no A7/CHAT_DECISION/1026-20 markers** (grep); their diffs are A2/A3/A5/A6 epic-release work. Canon = **12**. ✔

**§41/A8 boundary.** `set_message_reaction` absent from `direct_chat_service.py`; reaction executed via reused `smartmodule_utils.react_moai` (fail-silently, WARNING only). `smartmodule_utils.py` diff = **0**. ✔

**Catalog delta.** A7 exactly +3 params +1 group: `CHAT_DECISION_*` ×3 in `_FLAGS` + `GroupSpec("flags_decision_making", …)` + membership in `TAB_MOD_DIRECT` (`flags_chat_behavior`+`flags_decision_making`). F8 reissued (baseline JSON, TSV, screen-map). Other catalog changes (`IMAGE_DAILY_LIMIT`, `limits_images`, `mod_images` tab) are **A5**, part of the expected epic-release tree, not A7 scope creep. Final sanctioned counts match exactly. ✔

**UI scope.** `web/app.js` A7 change limited to `mod_direct` sources +`flags_decision_making`; the rest of app.js/index.html delta is A5 image-limits. ✔

**R17 logs.** `_log_decision_short_circuit` / `_log_coordinator_decision(with_decision_fields=True)` emit only chat id, action, reason enum, target id, needs_tools, reaction, tool names. No message text. The two `query` occurrences in `direct_chat_service.py` are the Stage-1 synth user prompt (1529) and memory-fact write (2137) — pre-existing, not A7 decision logs. ✔

**Threat file adequacy (F-7).** Format is correct (`threat→mechanism→code→test` table) and covers all R3-core classes named in spec §13 (false silence, false reply/extra call, Verbalizer waste, JSON/private leak, randomness, passive regression, context misread, wrong reaction target, kill-switch, settings/catalog regression, double silence, A8 boundary) — but see F-7 for inaccuracies.

## Findings

### High

**F-1 (High) — Evidence (`evidence.md` / `threat-failure-analysis.md` / `tasks.md` T-3649) misrepresents §46-tool and §43 tool-unavailable as a completed done-state; no test drives `handle()` through the tool path.**
- Location: `services/direct_chat_service.py:1377-1442` (handle tool/degraded/empty branches), `:730-760` `build_coordinator_decision`/`_coordinator_reason`, `evidence.md:55-64`, `threat-failure-analysis.md` threats #2/#3/#10.
- Requirement: spec §3.4 / §46 REQ-A7-25 («tool → выполнить инструменты, затем определить **итоговое** действие»); §43 REQ-A7-16 / §5 invariant 6 («недоступный инструмент → корректное сообщение об ошибке ожидающему результат»); §13 R3-trigger «отсутствие ложного молчания».
- Reproduction/observation: On a pure-tool hop with **no LLM call** (deterministic pre-gates dig/image fired — handled inside Phase P, fine), the final action is correct. But for a **degraded/failed tool outcome the final action is `tool` or `reply`, never `silent`** — an error is always reported as text (existing Stage-2/degraded path or the final `except`). Yet `threat-failure-analysis.md` threat #2 claims `handle():1221–1252` is the mechanism for "silent/react короткое замыкание до LLM" and threat #10 cites `_coordinator_reason`/`build_coordinator_decision` as the mechanism. Those functions **build/log a reason, they do not branch `handle()`**; the only runtime branching is `if pre_action == ACTION_SILENT/REACT` at `:1240–1251`. So the threat table's "code" pointers for tool/unavailable outcomes are inferential, not runtime enforcement.
- Additional confirmation: the only end-to-end order tests (`TestHandleOrder`) use `«Ок»`/`«АХАХА»`/`«Почему?»` — they **never pass a mocked `tool_router`/`ToolLoopResult`** through `handle()`. The tool/unavailable behavior is covered only at the pure-function level (`TestPhaseT`), and `evidence.md:72-80`/`threat-failure-analysis.md` present it as runtime-enforced. `evidence.md` also writes `await_count==2 сохранён` as evidence while `tests/test_decision_making_round1026.py` contains no `await_count==2` assertion (that lives only in the A1 file).
- Impact (R3): a reviewer/release reader is led to believe the §46-tool final hop and §43 error-as-reply are end-to-end proven when they are not; if a future edit to the reply/degraded branches silently changed the final action, no A7 test would catch it. This is an unmet acceptance-evidence requirement, not merely a doc nit.
- Corrective action: (a) fix the threat table so each row points at the **actual** runtime mechanism (the `pre_action` branch for silent/react; the reply/degraded/except path for tool failures) and stop citing `_coordinator_reason` as the mechanism; (b) add a real `handle()` test with a mocked `tool_router` returning a degraded/failed `ToolLoopResult` asserting text reply (not silence) and one asserting a successful tool hop proceeds to Stage-2; (c) remove/adjust the `await_count==2` claim in `evidence.md` or add the assertion.
- Verification method: new `TestHandleOrder` cases pass; threat table code-pointers resolve to the cited line; `evidence.md` no longer states an assertion absent from the test file.

**F-2 (High) — §47 context fields (`reply_to_is_article`, `expects_tool_result`, `is_private`, `bot_replied_recently` from actual bot-reply history) are computed but never consumed by the policy; §47 REQ-A7-27 partially unmet.**
- Location: `services/direct_chat_service.py:1046-1078` (`_decision_context`), `:789-...` (`_decision_pre_action` — no reads of `is_private`/`reply_to_is_article`/`expects_tool_result`), `:1058` (`bot_replied_recently=reply_to_bot` — aliased, not read from `bot_replies`).
- Requirement: spec §3.5 / §47 REQ-A7-27 («…была ли это статья; ожидается ли результат инструмента») and §5 invariant 10; ADR D8 lists image/article/expects-tool as context sources.
- Reproduction: source inspection — `_decision_pre_action` reads only `expects_tool_result` (which is hard-coded `False` at `:1067`), `bot_replied_recently` (aliased to `reply_to_bot`), and `has_question`; `is_private` and `reply_to_is_article` are dead. `expects_tool_result` is the priority-(4) branch but is never `True`, because the function is called only pre-LLM.
- Impact: two of §47's six signals do not influence any decision; article replies and "waiting for tool result" cases fall through to `default` reply. Behavior is fail-safe (reply), but the acceptance-driving §47 capability is only partly delivered while `evidence.md:132`/invariant 10 assert it "OK".
- Corrective action: either consume the fields (e.g. article/private cases influence reason/target) or explicitly document in `evidence.md`/`threat-failure-analysis.md` that they are reserved for A8/A9 and not acceptance-relevant; and make `test_addressed_other_replies`/`test_expects_tool_result_replies` reflect the real source of `expects_tool_result` rather than a value the runtime never sets.
- Verification method: a test showing article/private/expects-tool inputs change (or provably do not need to change) the outcome, plus truthful evidence text.

### Medium

**F-3 (Medium, requirement-blocking) — A short message that is only punctuation (`«?»`, `«???»`, `«?!»`, `«...»`) is classified `emoji_only` and (with default toggles) produces `react`/silent, not a reply, contradicting §42's spirit and REQ-A7-12/-15.**
- Location: `services/direct_chat_service.py:766-786` (`_decision_message_class`: `_EMOJI_ONLY_RE` matches before the `?` check), `:214-224` (local `pre.txt` branch).
- Observation (independently reproduced): `_decision_message_class("?") == emoji_only`; `_decision_pre_action(message_class="?", addressed=True, toggles=all True) → ("react", "emoji_reaction", "🗿", 1)`.
- Requirement/impact: §42 names «Почему?» as the counterexample to a hard short-rule; a bare «?» is short but is a request for content. Here it is treated as an emoji reaction. Cost class = "false silence/extra reaction dropping a real task" (R3 primary failure cost). This is a boundary case not covered by the current tests (they only test `«Почему?»`, not bare `«?»`).
- Corrective action: order the `?`/question check before `_EMOJI_ONLY_RE`, and/or exclude question-punctuation from emoji-only; add a regression test for `«?»`/`«???»` → `reply`/`question`.
- Verification method: new test asserts `«?» → ACTION_REPLY`.

**F-4 (Medium, requirement-blocking) — `IMAGE_REACTIONS_ENABLED` OFF is bypassed when `REACTIONS_ENABLED` is ON for a laugh on the bot's own image.**
- Location: `services/direct_chat_service.py:249-264` (`_decision_pre_action` branch 5/6).
- Observation: `if reply_to_bot and reply_to_is_image: if toggles.image_reactions: react ... return reply` (correct for image OFF). But if `image_reactions=False` **and** `reactions=True`, the code returns `reply` — correctly honoring IMAGE OFF. However for the **laughter** path the first matching branch already returned; when `image_reactions=False` the function returns early `reply`, so off works — **but when `reply_to_is_image=False` and `reply_to_bot=True`** the laugh uses the generic `reactions` toggle. The concrete bypass is the inverse: with `image_reactions=False, reactions=True, reply_to_bot=True, reply_to_is_image=True` the branch returns `reply` (OK); but the test `test_image_reactions_off_replies_not_react` only checks that one combination. Verified by code read, not by probe (needs an image context mock). Under §48, disabling "Реакции на короткие ответы к собственным изображениям" must stop reactions specifically for own images regardless of the generic toggle. Code appears to honor it (early reply), so downgrade this to **Low** pending an explicit probe — see F-4b below.

**(F-4 re-scoped to Low):** no confirmed bypass found by code read; retain only as "add an explicit probe & test" debt. → registered under Non-blocking debt.

**F-5 (Medium, requirement-blocking) — `reason_code` closed-enum contract is contradicted by the `disabled` code: the kill-switch OFF path never emits `disabled`, and `REASON_DISABLED` is unreferenced outside the enum.**
- Location: `services/direct_chat_service.py:492` (`REASON_DISABLED`), `:1230` (OFF → policy not built, `pre_reason` stays `REASON_DEFAULT`), `:714-727` (`_coordinator_reason` never returns `disabled`), `spec.md:159` (priority row 0: OFF → reason `disabled`).
- Observation: `REASON_DISABLED` has no producer; when `DIRECT_DECISION_MAKING_ENABLED=false`, `pre_reason=REASON_DEFAULT` and the coordinator log (with OFF `with_decision_fields=False`) omits reason entirely. The spec's priority table promises `disabled`.
- Impact: diagnostic contract inconsistency; a log reader cannot distinguish "policy disabled" from "default". Not a runtime-safety defect (OFF behaves as A1 baseline).
- Corrective action: either emit `disabled` when OFF (pre_reason=REASON_DISABLED, without building policy) or remove `disabled` from the enum/spec and document that OFF changes no fields. Must keep `spec`/enum consistent.
- Verification method: test asserting the OFF log/reason, or a spec/enum edit reconciling the two.

### Low

- **F-6 (Low) — "no 3rd LLM call" proven at mock boundary, not by physical call count in a real pipeline.** Builder's `await_count==2` claim is not present in this feature's test file. The design is verifiably 0 additional call sites, so this is a verification-depth gap, not a defect. Recommend an integration-style assertion (or link A1's test) in the R3 evidence.
- **F-7 (Low) — `threat-failure-analysis.md` has one factual inconsistency:** header says tests are in `tests/test_decision_making_round1026.py` "unless noted", reserve tests include `TestPolicy::test_policy_has_no_random` (exists) but the table also claims `TestHandleOrder::test_silent_*` proves 0 LLM while the test patches `_synthesize_direct_answer`; and threat #3 claims `await_count == 0` `llm.generate` — true for silent/react, but threat #1 "expects_tool_result" branch is unreachable (see F-2). Fix the table so each claim is reproducible.
- **F-8 (Low) — `evidence.md` says the R3 artifact "10 threats" while the file has 14 rows;** and `evidence.md:78` also has a typo `санction` in a *different* file (`test_tool_coordinator_round1026.py`, A5 note). Counting/style only; align the number.
- **F-9 (Low) — boundary test `test_forbidden_paths_out_of_diff` in `tests/test_tool_coordinator_round1026.py` now only inspects `tests/test_decision_making_round1026.py`?** No — it inspects `tests/`… Verified it inspects the A1/A5/A3 diff names and has been weakened (removed `image_generation.py`/`param_catalog.py` from forbidden, allowed `web/app.js`) for A3/A5 sanctions. This is *outside A7* but it means the repo's cross-feature boundary guard no longer forbids `param_catalog.py`; A7's own catalog delta is nonetheless exactly sanctioned (verified). Register so the epic release gate re-checks the aggregate.

### Non-blocking debt

- **D-1:** Add explicit probe/test for `IMAGE_REACTIONS_ENABLED=false ∧ REACTIONS_ENABLED=true ∧ own-image` to prove no bypass (F-4 re-scope).
- **D-2:** A1 `test_forbidden_paths_out_of_diff` has been relaxed for A3/A5 (see F-9); include in aggregate epic review.
- **D-3:** `plans/features/decision-making-round1026/` is **untracked**; if the feature folder is not staged/archived before the aggregate release, the binding manifest cannot see it via git. Pin by content hash (done here) and ensure archive step includes it.

## Counterexamples checked

| # | Counterexample | Result |
|---|---|---|
| 1 | Bare `«?»` (short question) | **Fails → react** (F-3) |
| 2 | `«???»`, `«?!»`, `«...»` | **Fails → emoji_only** (F-3) |
| 3 | `«Почему?»` | OK → reply/question |
| 4 | `«Бот, нарисуй кота»` | OK → reply/explicit_request |
| 5 | `«АХАХА»` on own image | OK → react/image_reaction |
| 6 | Not addressed by other user | OK → silent/not_addressed |
| 7 | `«Ок»` default toggles | OK → silent/acknowledgement |
| 8 | Toggles: ignore OFF + reactions ON for `«Ок»` | OK → react |
| 9 | Tool failed / degraded | OK at pure-function level; **no end-to-end test** (F-1) |
| 10 | OFF kill-switch for `«Ок»` | OK → reply path, no policy (F-5 reason wording) |
| 11 | Throttle/cooldown before Phase P | OK → no `[decision]` log (coexistence, no double silence) |
| 12 | `_decision_pre_action(..., toggles=None)` | OK → reply/error (fail-safe, never false silence) |
| 13 | Context error | OK → `DecisionContext(addressed=True)` → reply |
| 14 | R17 leak via log | OK → no message text in decision logs |
| 15 | Catalog creep | OK → exactly sanctioned counts; other delta = A5 |

## Unavailable checks

- No live/LLM/provider or real-Telegram calls (unit + adversarial only) — offline environment; the physical 2-call invariant is not directly measurable here.
- No Context7/Exa/documentary verification required: A7 introduces **no new third-party dependency, no migration, no external API contract** (canon unchanged; no new tool; prompts untouched), so the documentary-verification trigger does not apply for this diff.
- Owner-gate A3 `PENDING OWNER VERIFICATION` remains external; A7 does not close it (as specced).

## Summary

Architecture, boundaries, no-3rd-call, A1-AMEND, A8-boundary, catalog delta (+3/+1), R17-safe logs, tests (68 + full 9371/0), JS 47/47, F8 CHECK OK, diff-check 0, canon 12, Δ DDL 0, APP_VERSION — all independently reproduced and consistent. The decisive issues are (1) an **unproven/misrepresented** §46-tool + §43 tool-unavailable runtime path with no `handle()` test, and (2) a **partially implemented** §47 context whose acceptance is asserted but whose fields are dead. These, plus bare-question misclassification and the OFF `disabled` reason contradiction, keep this at **Needs Fixes**. After corrections, re-run this gate against a fresh `Working-Tree-Hash` — the current approval binding is stale by definition.

---

# Cycle 2 — повторный focused-review после rework Builder (T-3663)

- **Status cycle 2: `Approved`.**
- **Gate type:** feature gate (не aggregate epic release gate).
- **Смысл решения:** A7 (обе линзы) прошёл для включения в pending epic-кандидат; готов к reconcile/archive.
  **Deployment — `DEFERRED_TO_EPIC`** (агрегатное epic-решение и деплой — на границе эпика; по этому gate @DevOps не вызывается).
- **Охват cycle 2:** проверка закрытия F-1/F-2 High, F-3/F-5 Medium, Low F-4/F-6/F-7/F-8/F-9 + повторные регрессионные прогоны. Полный требования-ориентированный аудит cycle 1 сохранён выше без изменений.

## Binding (cycle 2, свежий — bound to this exact reviewed state)

- **Reviewed-Commit (HEAD):** `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` (== baseline; A7 uncommitted).
- **Spec-Hash:** `950c5f8039791ae4353449ae53bc31e1aa244f585ed3320522de72c364d52ea0` — **не изменён** (spec.md не редактировался).
- **ADR-Hash:** `9166bef204e76606ef743f6500101acec0006cf59e3f2ff4c5152b2f7fc97173` — не изменён.
- **Tasks-Hash:** `b9432d814b4c4b6277e169d4a061f5c1077e3500ef4193e6203ec2730ad04ea1` — не изменён (tasks.md не редактировался).
- **Evidence-Hash:** `194e246b6fabb8888cf4260c4727eef97e176e4ea79905a5b3a71901efda2ee2` (изменён rework-секцией).
- **Threat-File-Hash:** `c52209f16c95b8cd406abbfabfcc3abcafe3594abcae1f609e3794af6b17eee0` (переписан F-1/F-7).
- **New-test-Hash (`tests/test_decision_making_round1026.py`):** `ee15c6577efb88f55b6779938c01ed55ac5f181314bec7450e55d191ac383c43` (совпадает с заявленным Builder).
- **Working-Tree-Hash:** `4b3df1402375e2287e67ec25a2d0c3e0f61662b5f6afeec43d9509f2ed8cccf4`.
  - **Recipe (идентичен cycle 1):** UTF-8 text = `DIFF:\n` + output `git diff e8646af --binary` (staged+unstaged) + `\nSTATUS:\n` + output `git status --porcelain` + `\nUNTRACKED-TEST:` + sha256- hex of `tests/test_decision_making_round1026.py`; затем sha256 этого потока. Feature-папка untracked, её содержимое пиннится отдельными хешами выше (Spec/ADR/Tasks/Evidence/Threat), presence — через `git status --porcelain` (D-3).

> Любое изменение кода/untracked A7-файлов/spec/ADR/tasks после этой ревизии делает cycle-2 approval стале.

## F-1 (High) — §46-tool / §43 tool-unavailable end-to-end + `await_count` — ЗАКРЫТ

**Ранее:** tool/unavailable-путь не прогонялся через `handle()`; `await_count==2` заявлен в evidence без ассерта в A7-файле.

**Проверено независимо (сам запускал; не вакуумно):**
- `TestHandleOrder::test_tool_path_runs_tools_then_final_action` — реальный `chat_with_tools` (не monkeypatch) + `_CaptureRouter`; инструмент реально диспатчится: `tool_loop.py:422 → router.dispatch`; ассерты `router.calls == [("execute_web_search", {"query":"новости"}, chat_id)]`, `chat_with_tools`-раунды `chat_calls==2`, лог `action=tool` / `reason=tool_result` / `tool_calls=("execute_web_search",)`, Stage-1+Stage-2 `generate_calls==2`, `_send_direct_answer` awaited once с `"итоговый текст"`, react — не вызван. Ветка реально «исполняет инструмент → затем итоговое действие» (§46 REQ-A7-25).
- `TestHandleOrder::test_tool_degraded_sends_reply_not_silence` — фейк `chat_with_tools` возвращает **настоящую деградацию** `ToolLoopResult(degraded=True, tool ok=False)`, а не «тихо успешный» фейк; итог: `reason=tool_unavailable`, `_send_direct_answer` вызван (текст), `react` — нет, `generate.await_count==0`. Это корректная симуляция отказа (§43 REQ-A7-16), не «зелёная пустышка».
- `TestHandleOrder::test_await_count_two_on_tool_path` — реальный счётчик `svc.llm.generate.await_count == 2` (Stage-1+Stage-2).
- `TestHandleOrder::test_await_count_zero_on_silent_path` — реальный счётчик `== 0`, `_synthesize_direct_answer` не awaited, `react` не awaited.
- Мой повторный прогон 20 целевых rework-тестов (tool/degraded/await/off/knot/context/private/image) → **20 passed**.

**Документация:** `evidence.md:59,113-116` теперь ссылается на фактические A7-тесты (`test_await_count_two_on_tool_path`), а не на несуществующий ассерт; `threat-failure-analysis.md` переведён с `_coordinator_reason` (только причина) на фактические runtime-ветки `handle()` (`:1258–1286`, `:1411–1528`). Заявление «await_count==2 сохранён» приведено в соответствие.

**Вывод:** High F-1 закрыт. Требование «end-to-end tool-путь + недоступность инструмента → не молчание» доказано тестом и воспроизведено мной.

## F-2 (High) — §47-поля реально вычисляются и читаются — ЗАКРЫТ

**Ранее:** `reply_to_is_article`/`is_private`/`expects_tool_result` вычислялись, но не читались; `expects_tool_result` был жёстко `False`.

**Независимые входы (мой probe, не тесты Builder), каждый меняет решение:**
- `_decision_message_class`/`_decision_pre_action`:
  - `expects_tool_result=True` + «Ок» → `reply`/`tool_result` (вместо `silent`/`acknowledgement`).
  - `reply_to_bot=True, reply_to_is_article=True` + «АХАХА» → `reply`/`tool_result` (вместо `react`/`image_reaction`).
  - `addressed=False, is_private=True` + «просто фраза» → `reply` (вместо `silent`/`not_addressed`).
- `_decision_context` (реальный код, `TestDecisionContextFields`): статья (`web_page`) → `reply_to_is_article=True` и `expects_tool_result=True`; документ (`document`) → `expects_tool_result=True`, `reply_to_is_image=False`; фото → `reply_to_is_image=True`, `expects_tool_result=False`; группа + reply не-боту → `addressed=False`; ЛС → `addressed=True`. → **все три поля реально вычисляются и потребляются** (`_decision_pre_action:801` ветка 4 / ветка 8).

**Оценка эвристики `expects_tool_result` (статья или не-фото медиа в ответе на бота) — matches §47 intent, но шире буквального «изображение/статья»:**
- Конкретный case (мой probe): `video`/`sticker`/`voice` от бота + «АХАХА» → `expects_tool_result=True` → `reply`/`tool_result`, тогда как для `photo` → `react`/`image_reaction`, для текста → `react`/`laughter`. Т.е. реакция «АХАХА» на **не-фото** медиа бота подавляется в пользу текстового ответа.
- Направление — **fail-safe** (лишний ответ, не ложное молчание), и spec §3.5(6) прямо разрешает pre-LLM-эвристику по «replied-сообщению бота-результата». §28-пример про «изображение» (photo) обработан корректно. Классифицирую как **ограниченный Low** (R-2 ниже), не как нарушение REQ.
- `bot_replied_recently` оставлен алиасом `reply_to_bot` и **задокументирован** как осознанное ограничение (`evidence.md:212-213`, residual `threat-failure-analysis.md:45-47`) — это ровно тот путь закрытия F-2, который был предписан в cycle 1 («consume … или явно задокументировать»).

**Вывод:** High F-2 закрыт; остаточная грубость эвристики — Low.

## F-3 (Medium) — короткая вопросительная пунктуация → reply — ЗАКРЫТ

Мой probe `_decision_message_class` + `_decision_pre_action`:
- `?`, `???`, `?!`, `?!?!?`, `??????????` → `question` → `reply`/`question`; `...` → `other` → `reply`/`default` (fail-safe, не реакция). Порядок: `_QUESTION_PUNCT_RE` проверяется до `_EMOJI_ONLY_RE`; `_ELLIPSIS_ONLY_RE` выводит `...` из emoji-класса. `test_bare_question_punctuation_replies`, `TestMessageClass` — зелёные. F-3 закрыт.

## F-5 (Medium) — OFF kill-switch → reason `disabled` — ЗАКРЫТ (с прозрачной оговоркой)

- Код: `handle():1262` `pre_reason = REASON_DEFAULT if decision_on else REASON_DISABLED`; далее `build_coordinator_decision(..., pre_reason=...)` → `_coordinator_reason` возвращает `"disabled"` (action=reply, без tools). `TestHandleOrder::test_off_killswitch_reason_disabled` — зелёный (reason_code=`disabled` на объекте решения).
- Мой независимый запуск `handle()` при OFF (перехват реального лога): `[coordinator] decision | chat=… | intent=chat | addressee=author | memory=0 | tools=- | eval=none | action=reply` — **байт-в-байт A1-формат** (без полей reason/target/needs_tools/reaction), т.к. `_log_coordinator_decision(with_decision_fields=decision_on=False)`.
- **Оговорка (не блокирует):** `disabled` присутствует на внутреннем объекте решения, но **не печатается** в OFF-строке лога — это осознанный компромисс ради сохранения A1-формата байт-в-байт (ровно один из вариантов, предписанных cycle-1 corrective action: «pre_reason=REASON_DISABLED, without building policy»). Контракт spec/enum согласован; ON-строка `[decision] … reason=<код>` работает (`reason=acknowledgement` проверено).

## Threat-файл (F-7) — adequacy для R3

- Формат `threat → mechanism → code → test` сохранён; **ровно 15 строк** (1–15) — счётчик `evidence.md` синхронизирован (было «10»). Покрыты все R3-классы spec §13: ложное молчание, ложный ответ/лишний вызов, Вербализатор, JSON/приватная утечка, случайность, пассивность, контекст §47, неверная цель реакции, недоступный инструмент/реакция, kill-switch, каталог/F8, R17, двойное молчание, граница A8.
- Spot-check code-указателей: **row 2** (`handle():1258–1286`; silent `:1274–1277`, react `:1279–1286`) — соответствует фактическим ветвям; **row 12** (`_log_coordinator_decision:872`, `_log_decision_short_circuit:909`) — точны; **row 11** (`settings.py:1407–1412`, `param_catalog.py:359`) — точны; **row 10** (`:1411` degraded-log, `:1445` Stage-2 skip, `:1460`/`:1481` финал, `:1505`/`:1519` ошибки) — соответствует runtime.
- **Найденная неточность (Low, R-1):** row 15 указывает `handle():1377–1380` как «empty→🗿», но реальная ветка — `except LLMBadResponseError` `:1402–1410` (react_moai `:1409`). Строки 1377–1380 — аргументы вызова `chat_with_tools`. Остальные указатели row 15 (`:1505–1517`, `:1519–1528`) корректны.
- **Adequacy для R3: adequate** (набор угроз полон, механизмы и тесты в целом воспроизводимы; одна Low-неточность указателя).

## Low spot-check (F-4/F-6/F-8/F-9)

- **F-4 (→Low):** probe-тесты `test_image_emoji_off_replies`, `test_image_reaction_ignores_generic_reactions_off` осмысленны (проверяют IMAGE-тумблер независимо от generic REACTIONS); bypass не найден. Закрыто как Low-долг.
- **F-6:** proof усилен реальными `await_count`-ассертами (2 на tool, 0 на silent) — счётчики фактически сравниваются, не декларация.
- **F-8:** счётчик 10→15 исправлен; main-секция `evidence.md` и threat-файл согласованы.
- **F-9:** deferral-rationale приемлем: `test_forbidden_paths_out_of_diff` намеренно расширен под санкционированные A3/A5-diff (повторное сужение сломало бы зелёные A3/A5); A7-дельта каталога независимо пиннится `TestBounds::test_counts_sanctioned` + F8 `--check` (473). Остаётся **aggregate-gate item** (Reviewer D-2), не пер-фича blocker.

## Повторные регрессионные прогоны (independently reproduced)

| Проверка | Команда | Результат |
|---|---|---|
| A7 suite | `pytest tests/test_decision_making_round1026.py -q` | **89 passed** |
| Direct-chat + catalog + F8 | `pytest tests/test_direct_chat.py tests/test_param_catalog.py tests/test_round1025_f8_registry.py -q` | **222 passed** |
| Direct-chat изолированно | `pytest tests/test_direct_chat.py -q` | **159 passed** |
| A7 + A1 coordinator | `pytest tests/test_decision_making_round1026.py tests/test_tool_coordinator_round1026.py -q` | **145 passed** |
| Full suite | `pytest -q` | **9392 passed, 0 failed** (151.99s) |
| F8 registry | `python tools/gen_param_registry_round1025.py --check` | **CHECK OK: реестр 473** |
| Catalog counts | probe | REGISTRY **473** · fields **430** · categorized **448** · GROUPS **102** · `_TAB_BY_GROUP` **100** · `TAB_RULES` **21** · canon **12** |
| JS suite | `node tests/js/*.js` (exit-code) | **47/47, exit 0** |
| diff whitespace | `git diff --check e8646af` | exit **0** (LF→CRLF informational) |
| APP_VERSION | read | **2.58.30** (без bump) |
| Δ DDL | source read | `test_no_ddl` зелёный; CREATE/ALTER в `direct_chat_service.py` отсутствуют |

**Регрессий нет.** Подтверждено: нет 3-го LLM-вызова (`await_count` 2/0), A1 — AMEND (единственный `CoordinatorDecision:591`; `system2_handoff.py` и `smartmodule_utils.py` diff vs base = **0**), реакция — reuse `react_moai` (`set_message_reaction` отсутствует; `test_no_set_message_reaction_direct_call` зелёный), R17-safe логи (`test_logs_r17_safe`), двойного молчания нет (`test_throttle_runs_before_decision` — throttle до Phase P).

## Scope (подтверждение)

A7-маркеры (`CHAT_DECISION|1026-20|DIRECT_DECISION_MAKING|decision_making_enabled|_decision_pre_action`) присутствуют только в санкционированных файлах: `services/direct_chat_service.py`, `config/settings.py`, `services/param_catalog.py`; UI — `web/app.js` (`flags_decision_making`); тесты/фикстуры A7 + feature-папка. Прочие изменённые файлы — эпик-дерево A2/A3/A5/A6 (не A7). Новых модулей решений нет (`services/*decision*` отсутствуют). Ничего вне санкционированного контура rework не затронул.

## Остаточный долг (Low, non-blocking — для aggregate-gate/следующих волн)

- **R-1 (Low):** `threat-failure-analysis.md` row 15 — устаревший code-указатель `:1377–1380` вместо фактического `:1402–1410` (empty→🗿). Исправить при следующем касании артефакта.
- **R-2 (Low):** pre-LLM-эвристика `expects_tool_result` шире §47: `video/sticker/voice` от бота + «АХАХА» → `reply` вместо `react` (fail-safe, задокументировано). При желании сузить до `article/document/video`.
- **R-3 (Low):** `bot_replied_recently = reply_to_bot` грубо: ответ на сообщение бота «other»-классом (напр. «продолжай») → `silent`/`recent_reply`, в т.ч. в ЛС. Класс разрешён spec §45 (row 9), задокументировано; более тонкая детекция «продолжение не нужно» — A8/A9.
- **D-2/F-9:** расширенный A1 `test_forbidden_paths_out_of_diff` — перепроверить на aggregate epic gate.
- **D-3:** feature-папка untracked — включить в archive-манифест (пиннится хешами).

## Итог cycle 2

Все cycle-1 блокеры (F-1/F-2 High, F-3/F-5 Medium) подтверждённо закрыты; Low F-4/F-6/F-8 закрыты, F-7 в целом закрыт (одна Low-неточность), F-9 — aggregate-gate item. Регрессий нет (9392/0, JS 47/47, F8 OK, канон 12, Δ DDL 0, версия и санкционированные счётчики каталога). Остаточные замечания — Low и не нарушают ни одно принятое требование.

**Status: `Approved` — feature gate пройден, A7 готов к reconcile/archive и включению в pending epic-кандидат. Deployment — `DEFERRED_TO_EPIC`.** Approval связан с Reviewed-Commit `e8646af…`, Working-Tree-Hash `4b3df140…` и Spec-Hash `950c5f80…`; любое последующее изменение кода/untracked A7-файлов/spec делает его стале.
