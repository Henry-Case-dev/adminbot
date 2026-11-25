# P0 GOAL / MEDIA (lane C) — evidence, 2026-11-25

Branch: `fix/p0-goal-media` · Base (deployed 2.58.246): `78abc866cc11ffba2ffaea2558080149859ce6ad`
Requirement rows: `P0I-GOAL-01`, `P0I-GOAL-02` (`plans/features/unified-reply/requirements-map-p0-2026-11-25.json`),
`P0R-MEDIA-01`, `P0R-MEDIA-02` (`plans/features/smart-module-semantic-routing/requirements-map-p0-2026-11-25.json`).
Owner source: `plans/owner_inputs/2026-11-25-p0-intent-memory-answer-quality.md` §2 (sha256 `0d2b3516…`);
acceptance bounds: `plans/owner_inputs/2026-11-25-p0-acceptance-boundaries-amendment.md` (sha256 `02a8e2ce…`).

Scope of this lane: final goal preservation through L1 planning → tool phase → Writer, and media-request
routing (scenario A). Not in scope (other lanes): `_structured_partial`/finalization matrices/hardcoded replies
(`fix/p0-answer-finalization`), memory retrieval/relevance (`fix/p0-memory-relevance`), Летописец delivery gating.

## 1. Established causes on the base (file:line)

### Cause 1 — rule 7 turns "analyse material, then write X" into research instead of X

* `services/chat_prompts.py:1087-1103` (base): active rule 7 says «Просьба разобрать, проанализировать,
  просмотреть, сравнить или обобщить сообщения, переписку, историю, чужие слова… — это разбор материала:
  `response_act=research` при любой манере человека». The rule decides the act from the *object* of analysis
  and never distinguishes the requested product from the preparation for it, so a turn "study old
  congratulations of X and write a new one" is planned as research.
* Consequences downstream are wired to that act, not to the user goal:
  `services/direct_l1.py:3070-3099` (`analysis_directive_needed` → analysis texts for `research`),
  `services/direct_l1.py:675-699` (`plan_response_mode` → `serious`),
  `services/direct_l1.py:582-616` (`to_response_plan` → `task_kind="research"`).
  Verified by code read; no production trace was available for this lane (honest limitation, §5).

### Cause 2 — the plan has no carrier for the final result, so the Writer only sees "research"

* `services/direct_l1.py:493-567` (base): `L1Plan` fields cover action/act/extent/tone/structure/delivery/
  capabilities/claims/axis/memory — there is **no** field for "what the user wants in the end".
* `services/direct_l1.py:3125-3210` (base): `build_l2_plan_block` renders `смысловой акт ответа: research`
  plus tone/mirroring/delivery/rejected note, but nothing about the requested product. The Writer therefore
  receives the intermediate act as the genre, and the material (evidence) as the subject.
* The tool phase keeps the plan object and works on a copy (`services/direct_execution.py:2567-2584`,
  `dataclasses.replace`), so any new plan field survives it — the missing piece was the field itself and its
  rendering in the Writer plan block.

### Cause 3 — media capability/tool semantics invite an operation on any media mention (scenario A)

* The only text L1 gets about media is the capability *name* in `ДОСТУПНЫЕ ВОЗМОЖНОСТИ`
  (`services/direct_l1.py:2558`), and the canon says nothing about materials/operations — so a reply to the
  bot's video with a remark reads as a reason to request `media_download`.
* `services/direct_capabilities.py:37`: `media_download → download_media`;
  `services/direct_execution.py:554-560`: that capability deterministically becomes a `download_media` step
  with empty arguments (the tool then takes the object from the replied message and re-sends it).
* `services/tool_schemas.py:323-330` (base): the tool description literally offered the replied video as a
  source — "Source is a link OR the video from the replied message" — with no boundary between "user asks for
  the file" and "user comments on the video". In the LLM-tool-calling route the same text is the only guidance.
* Fast-Track is not the cause: the command path requires the download trigger at the start of the body
  (`services/video_intent.py:109-110`, `handlers/video_download.py:270`); scenario A's remark has no such
  trigger, so the call could only come from the L1 capability plan or the LLM tool call — both governed by the
  texts above.
* There is no capability for transforming a video at all (`direct_capabilities.py:28-59` has `image_edit`
  for pictures only), so the honest behaviour for "put X into this video" is a conversational answer, not a
  substituted operation.

## 2. What changed (cause-level, minimal)

`services/chat_prompts.py` — one canon revision (P0GM), no second L1/classifier/gate:

* rule 7 rewritten: separates the final result from the material for it ("Разделяй конечный результат и
  материал для него", "Такой ход не становится исследованием"), keeps the material→`research` branch for a
  genuine analysis request, states that when both analysis and a new text are requested both parts must be in
  the answer, and that reproducing someone's manner is style, not biography;
* new optional allowlisted plan field `final_goal` in the same JSON schema + its contract section
  («КОНЕЧНАЯ ЦЕЛЬ ХОДА»): result, not preparation; all results if several; a tool's status/type never changes it;
* new section «МАТЕРИАЛЫ И ДЕЙСТВИЯ С НИМИ»: media in the message/reply is context until the meaning asks for
  an action; capability meaning is decided by the sense of the request; when the requested operation is
  unavailable — answer honestly and do not substitute another available operation; re-sending the same media
  is not fulfilment; do not call a tool for the sake of calling it.
* `PREV_DIRECT_L1_PLANNER_EVR6 = 619290834387` (frozen), active `ce6931304b24`.

`services/direct_l1.py`:

* `L1Plan.final_goal` (optional, `FINAL_GOAL_MAX=200`), normalized in `normalize_l1_plan`
  (whitespace-collapsed, garbage/absent → `""`, plan stays valid, no invented goal);
* `build_l2_plan_block` renders `цель хода: <goal> - ответ даёт именно это; найденный материал и результаты
  шагов служат входом, а не заменой этой цели` only when the goal is non-empty (empty payload unchanged).

`services/tool_schemas.py` — `download_media` description: call only on an explicit request to get/save/send
the file itself; a comment/joke/remark about a video or photo is conversation; never call it just because the
turn replies to media; it cannot transform media (edit_image is for pictures). Schema shape unchanged.

`services/prompt_migrations.py`, `services/prompt_registry.py` — ladder step (`EVR6 → P0GM`) and rollback head
(`P0GM → EVR6`), revision label `l1-planner-final-goal`, seal `ce6931304b24`, factory-set fingerprint
`10efa51a8dae` (owner custom prompts are not touched by the ladder).

No keyword dictionaries, no trigger words, no per-user/per-phrase conditions, no new mandatory LLM call, no new
gate. Finalization/hardcoded partials and lore gating were **not** touched (other lane).

## 3. Tests (RED on base → GREEN on candidate)

New file `tests/test_p0_goal_media_2026_11_25.py` (15 tests). Same file executed on base `78abc866c`:

* base: **9 failed, 6 passed** — RED exactly for the new contract:
  `test_rule7_distinguishes_product_from_material`, `test_final_goal_field_is_in_schema_and_plan_contract`,
  `test_normalize_reads_final_goal_and_never_invents_it`,
  `test_writer_receives_requested_product_with_material_as_input`, `test_goal_survives_tool_phase_into_writer`,
  `test_media_section_states_reply_is_not_an_operation`,
  `test_download_media_description_forbids_reply_comment_invocation`, `test_canon_ladder_has_p0gm_step`,
  `test_canon_has_no_incident_hardcode_or_trigger_lists`.
* candidate: **15 passed**.

Coverage of the required discriminating checks:

| check | test |
|---|---|
| (a) analyse old congratulations of X → new text is the required output | `test_rule7_distinguishes_product_from_material`, `test_writer_receives_requested_product_with_material_as_input` |
| (b) genuine research keeps its format/profiling | `test_genuine_research_keeps_its_contract` (serious mode, analysis+delta directives, lore delivery unchanged) |
| (c) both requested parts present | rule contract `нужны обе части` + Writer gets act + `final_goal` listing both |
| (d) conversational reply to a video → no download/re-send | `test_conversational_reply_to_video_triggers_no_media_operation` (0 steps, router recorded 0 dispatches), `test_download_media_description_forbids_reply_comment_invocation` |
| (e) transformation request → transformation path; honest degradation when unavailable | `test_transform_request_maps_to_the_transform_capability_not_download` (resolves `edit_image`, never `download_media`), `test_unavailable_transform_degrades_honestly_without_substitution` (rejection note names the missing edit capability, never download) |
| (f) unknown/ambiguous intent is not research | `test_unknown_intent_is_not_research_by_default` (act `other` → no analysis/delta directive, mode `casual`, no act/goal line) |

Regression guards that must not break (green on base too): `test_explicit_download_request_still_derives_the_download_step`,
conversation/no-substitution trio, and the positive research profile check.

Affected suites, candidate vs base (same command, same worktree isolation, `-p no:cacheprovider`):

* canon/L1 ladder set (14 files: `test_speech_p0_*`, `test_asap_speech_r3b_canon`, `test_direct_l1_*`,
  `test_asap2_clar_contract`, `test_prompt_migrations`, `test_asap_fc_voice_l1_decision_profile`,
  `test_post_asap5_*`, `test_evol_w17_small_canon_reqs`, `test_evol_evidence_routing`, `test_tool_schemas`):
  candidate **367 passed, 5 failed**; base **352 passed, 5 failed** — the 5 failures are identical on base
  (`test_build_l1_context_bot_replies_caps_and_limit`, `test_34_factory_and_ladder_and_custom_preserved`
  [stale label since 2.58.14x], `test_33_composer_on_off_payload_identical_and_clean` [Chat_Time_Context
  second flake], `test_24_truncated_window_and_branch_are_honest`,
  `test_direct_service_l1_payload_gets_profile_from_turn_frame`).
* tool routing / media / direct set (18 files incl. `test_native_media_tools_round1024`,
  `test_tool_calling_round1015`, `test_tool_loop`, `test_tool_router`, `test_media_download`,
  `test_media_execution_asap32`, `test_mca23_phase2`, `test_direct_chat`): candidate **692 passed, 3 failed**;
  base **692 passed, 3 failed** — identical failures (`test_callback_downloads_chosen_quality`,
  `test_callback_busy_keeps_pending`, `test_import_stays_light_and_has_no_db_dependency`; the last one passes
  alone on both trees — order-dependent, pre-existing).
* prompt audit/registry set (8 files incl. `test_evol018_prompt_audit`, `test_er65_sent_segment_snapshot`,
  `test_ui_verbilizer_tabs_round1023`, `test_soul1_*`): candidate **120 passed, 9 failed**; base **120 passed,
  9 failed** — identical (stale recorded dumps/line pointers on base).
* UR / planning / matrix set on the candidate (`test_ur_turn_engine`, `test_ur26_other_routes_payloads`,
  `test_unified_reply_ur_b_no_topic_veto`, `test_unified_reply_ur_b_review_fixes`,
  `test_mca09_intents_block_a_round1040`, `test_mca09_intents_off_parity_round1040`,
  `test_direct_chat_prompts`): **164 passed, 0 failed**;
  (`test_factcheck_media_2026_10_25`, `test_direct_context_composer_asap3`,
  `test_direct_decision_matrix_asap3`, `test_asap8_v6_wc_direct_matrix`): **138 passed, 0 failed**.
* `tests/test_evol_video_intent.py` does not complete in this environment on **base and candidate alike**
  (`pytest-timeout` is not installed although `pytest.ini` requests it, so a waiting test never times out);
  it was excluded from the runs above after the same stall was reproduced on the base worktree. The file
  covers video trigger regex/services and does not import the L1 canon, so it is outside this change; the
  stalled runs were terminated by hand and no test processes were left behind.

`py_compile` on all changed modules: see §4. `git diff --check`: clean.

## 4. Residuals, limitations, overlap

* No production trace of scenario A/B/C was available to this lane; the causes above are established by code
  (routes to `download_media`, the act→Writer wiring, the missing goal field), not by a live trace. The fix is
  contract-level: model behaviour is probed by tests only at the contract boundary (what the planner is told,
  what the plan normalizes, what the Writer receives, which steps the runtime derives). Live phrasing quality
  is not asserted (acceptance amendment §21-23).
* `final_goal` is optional by design: a turn without a stated goal keeps the previous payload byte-for-byte
  (no synthetic goal, no forced classification).
* Overlap for assembly: this lane edits `services/direct_l1.py` (plan field + `build_l2_plan_block`),
  `services/chat_prompts.py` (L1 canon only), `services/tool_schemas.py` (`download_media` description),
  `services/prompt_migrations.py`, `services/prompt_registry.py` (label/seal/fingerprint) and the canon-pin
  tests listed above. Sibling lanes `fix/p0-answer-finalization` (finalization/hardcoded partials/lore,
  `tool_loop.py`/`direct_chat_service.py`) and `fix/p0-memory-relevance` (retrieval filters) were not touched;
  if either also edits `direct_l1.build_l2_plan_block` or the L1 canon, merge the canon revision as one step
  (the ladder has exactly one active head).
* Behaviour kept intact: genuine research/factcheck/summary/historical story formats, Летописец delivery
  gating (`lore_story_delivery_allowed` unchanged), explicit download requests, Fast-Track command path,
  image generation/edit mapping, evidence policy.

## 5. Files changed

```
services/chat_prompts.py          L1 canon revision P0GM (rule 7, final_goal, media semantics)
services/direct_l1.py             L1Plan.final_goal + normalize + Writer plan line
services/tool_schemas.py          download_media description boundary
services/prompt_migrations.py     ladder step EVR6 → P0GM / rollback head
services/prompt_registry.py       label, seal, factory-set fingerprint
tests/test_p0_goal_media_2026_11_25.py          new contract tests (15)
tests/test_speech_p0_corrective_l1_route.py     canon pins updated to P0GM
tests/test_speech_p0_core_serious.py            active rules P0GM
tests/test_speech_p0_l1_canonical.py            (unchanged; green)
tests/test_asap_speech_r3b_canon.py             canon composition/rollback head
tests/test_direct_l1_corrective_r1.py           canon composition + import
tests/test_direct_l1_l1d_contract.py            canon composition, rollback list, rule 7 text
tests/test_asap_fc_voice_l1_decision_profile.py canon delta/rollback/label
tests/test_post_asap5_w1_writer_core.py         canon composition, sha pins, rollback indices
tests/test_post_asap5_w2_tech_reasoning.py      active rules, canon composition, rollback, label
tests/test_evol_w17_small_canon_reqs.py         canon composition, rollback head, label
tests/test_evol_evidence_routing.py             label, EVR6 pins, rollback head
tests/test_prompt_migrations.py                 rollback target (EVR6), active sha
```
