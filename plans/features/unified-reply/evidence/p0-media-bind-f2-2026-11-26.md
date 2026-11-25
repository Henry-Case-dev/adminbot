# P0 — MEDIA BINDING F2: одна привязка на медиа-сообщение и авторство медиа

Date: 2026-11-26. Lane: `P0-MEDIA-F2` (owner input `plans/owner_inputs/2026-11-26-p0-direct-trigger-l1-media.md`, §4; diagnosis `plans/features/unified-reply/evidence/p0-media-binding-diagnosis-2026-11-26.md`, C2).
Base: deployed `f2cb38c8412506261504b4000f7a7a53be143851` (2.58.247).
Worktree: `WorkspaceData/worktrees/c742e4de9e92c489/p0-media-bind-f2-79fe0e3242f9-ad61648f`, branch `fix/p0-media-bind-f2`.
Scope held: `services/direct_chat_service.py` and `handlers/direct_chat.py` untouched (F1 lane owns them).

## 1. Cause (confirmed in source, reproduced locally)

`media_readiness.link_pending_intent_for_message` (base `:980-1049`) linked the newest unlinked intent of the **chat** only:

- no message identity — the only guard was "media newer than the request" (`:1004-1005`), so one media message could serve several pending intents;
- no author check — a photo by another participant was linked to the asking user's intent, contradicting the existing "foreign photo is not attributed" rule (`:615-620`, `_same_author`).

The media intake seam calls the function **twice** for the same photo: `mca_vision.register_intake_assets` (`:2151-2161`) and then `mca_vision.enqueue_intake_jobs` (`:3510-3522`), both driven by `handlers/summary.py:613-617`. Each call linked one intent and broke, so one photo linked two intents and the worker sweep delivered two answers describing the same image.

## 2. Fix (minimal, cause-level)

`services/media_readiness.py`:

- new helper `_linked_tg_message_id(job)` — the `tg_message_id` already bound to an intent payload;
- new helper `_intent_author_conflict(payload, author_user_id)` — deliberate mismatch only when the numeric `user_id` is known on **both** sides (same semantics as `_same_author`); unknown media author or legacy intent without `user_id` keeps the previous structural decision (link proceeds, subject to the older-than-media rule);
- `link_pending_intent_for_message(..., author_user_id: int | None = None)`:
  1. first pass expires stale intents and returns `None` if **any** active intent is already linked to this `tg_message_id` — the first intake call wins, the second is a no-op;
  2. second pass links at most one candidate and skips intents whose payload `user_id` differs from the media author.

`services/mca_vision.py` (both intake call sites) pass the message author:
`register_intake_assets` — `int(message.from_user.id)`; `enqueue_intake_jobs` — the already-computed `user_id`.

No TTLs, cooldowns, rate limits, new stores, LLM checks or new behaviour gates. Vision asset keying, Direct window rendering, `_render_current_question`, `_resolve_earlier_image_markers` and the reply anchor are untouched.

Side effect kept without new code: a bot-generated image is registered through `handlers/summary.py:451-454` with `from_user.id = bot id`, so it no longer satisfies a participant's pending request.

## 3. Deterministic proof

New file `tests/test_p0_media_bind_f2.py` (6 tests, no network, Vision transport not called; analysis recorded ready as after a worker run).

RED on base `f2cb38c84` (service files reverted to base, test file unchanged), `5 failed, 1 passed`:

```
test_f2_one_photo_two_intents_links_once_and_resumes_once   AssertionError: одно фото связало 2 намерения  (link: 9001+9002 -> tg=9500)
test_f2_link_is_idempotent_per_media_message                second call returned a link to the OTHER intent (trigger 9102, tg 9150)
test_f2_foreign_author_photo_does_not_link_asker_intent     intent 9201 (user 4242) linked to photo 9250 by user 777
test_f2_unknown_author_keeps_structural_link                TypeError: unexpected keyword argument 'author_user_id' (API-shape guard, behaviour kept)
test_f2_bot_generated_image_does_not_satisfy_pending_request bot photo 9550 closed intent 9501
test_f2_own_author_photo_links_normally                      PASSED on base (unchanged product scenario, positive control)
```

GREEN on the candidate: `6 passed in 4.48s` (same file, fix applied).

Assertions are behavioural: exactly one linked intent and exactly one sweep delivery for one photo (`-- resume handler calls == 1`, second sweep pass is a no-op); the second intake call returns `None` and the payload keeps the first call's `asset_ids`; foreign author yields no link at both the intake seam and the direct call; own author keeps `trigger`/`asset_ids`; unknown author still links; a bot image leaves the intent unlinked while the following participant photo links it.

Adjacent suites (all with the fix; failures proven identical on base):

| Suite set | Result |
|---|---|
| `test_evol_vision_sync_core`, `..._wave2`, `test_p0_vision_fix_core`, `test_rc_target_media_evidence`, `test_p0_vision_download_transport`, `test_evol011_vision_telemetry`, `test_evol019_vision_recognition`, `test_vision_adapt` | 239 passed, 38 skipped |
| `test_mca19_block_a…g`, `test_mca19_rework_r1`, `test_mca17_perimeter_events`, `test_mca20_rework1_f1_f2` | 155 passed, 2 failed — identical on base (`test_js_mirrors_mod_vision`: missing `toggleKey: 'flags.vision_enabled'` in the TMA bundle; `test_evidence_injection_stays_data_not_instructions`: `&lt;/evidence&gt;` absent) |
| `test_asap5_*`, `test_asap7_module_completeness`, `test_asap8_v6_p1_d11_registry`, `test_caps_tool_results`, `test_evol_reply_context_consumers`, `test_evol013_reason_quality`, `test_factcheck_*`, `test_mca01_*`, `test_mca10b_*`, `test_memory_attribution`, `test_p1_semantic_routing_demotions`, `test_addtr_postgen`, `test_postgen_diag`, `test_smart_corrective_*`, `test_evol019_ui` | 562 passed, 1 skipped, 10 failed — identical on base (8 × `TestNostalgiaProvenance`, `test_env_off_beats_product_toggle`, `test_write_points_go_through_single_writer`) |

`py_compile` on the two services and the new test: exit 0. `git diff --check`: exit 0.

The pre-existing reds are unrelated to this lane (front-end toggle mirror, validator evidence encoding, nostalgia/integration and writer-architecture contracts) and are not touched here.

## 4. Residuals / not verified

- Production trace (which photo, how many tracks, per-chat flags) still not read; the mechanism, not the exact incident sequence, is fixed.
- If the sweep consumed the first intent in the sub-second gap between the two intake calls, a second intent could theoretically be linked to the same photo. Requires a ready analysis and a delivery inside that gap (Vision latency makes it practically unreachable); symbols to fix it would be a new store, which the corrective forbids.
- Unknown authoring on either side keeps the previous structural behaviour by design (`_intent_author_conflict` docstring); a bot image is blocked through author mismatch, not through a bot-identity rule.
- F1 (audio/voice/non-image "own media" classification, `services/direct_chat_service.py`) belongs to the parallel lane and is not part of this evidence.
