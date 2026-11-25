# P0 DIRECT-TRIGGER / L1 AUTONOMY — lane 1 evidence (2026-11-26)

- Contract: `plans/owner_inputs/2026-11-26-p0-direct-trigger-l1-media.md`
  (sha256 `528eac7f41c79373676df80f4b4dc32ddf7d4fb9d3ccf3debe9b2f731a2275b2`),
  sections 1–3 and 5. Section 4 (media binding) is a separate lane, not touched here.
- Boundaries: `plans/owner_inputs/2026-11-25-p0-acceptance-boundaries-amendment.md`,
  `AGENTS.md` "BOUNDED ACCEPTANCE AND LONG-TERM PRODUCT QUALITY".
- Base (deployed): `f2cb38c8412506261504b4000f7a7a53be143851` (2.58.247).
- Candidate branch: `fix/p0-trigger-force`, commit
  `4e5374536e45bcf97e9aa8544d68493fa2cbe6e0`.
- Worktree: `WorkspaceData/worktrees/c742e4de9e92c489/p0-trigger-force-a624ec521cbe-dcce6c61`
  (registered unit `P0-TRIGGER-FORCE`).
- Builder session: `ses_ded186f3cffehgIXVIBT37AqK6`.

## 1. Established mechanisms on the deployed code

Handler `handlers/direct_chat.py`:

- `_effective_text()` (L181) combined `message.text`/`caption` without provenance.
- `_is_direct_trigger_unscoped()` (L270) applied `_BOTWORD_RE.search(text)` to the
  same unprovenanced text; `_BOTWORD_RE` (L105) is the configurable
  `reactions.chat_botword_pattern` family; mention/persona/reply branches adjacent.
- `_forward_source_of()` lived only in the service and was used by
  `_image_capability_gate()` / facts, not by trigger detection.

Service `services/direct_chat_service.py`:

- `_message_user_text()` (L1294) — own second text/caption combiner.
- `_BOTWORD_RE = re.compile(r"(?i)\bбот\w*")` (L1593) — a second, divergent regex.
- `_resolve_direct_trigger()` (L1697) returned `(trigger_type, force_reply_required)`;
  keyword/persona/mention → `TRIGGER_FORCE_KEYWORD, True` (L1710).
- `handle()`/`_handle_turn()` pre-set `pre_action = ACTION_REPLY` for force
  (L6158–6167), passed `FORCE_LINE` to L1 (L9088), then overrode the model:
  `if _force_required and _l1_action != "reply": l1_plan.action = "reply"`
  (L6625–6630). `DeliveryPolicy(force_reply=force_required, direct_request=...)`
  (L9041).
- Silent ack `_execute_silent_ack()` (L5568) gated on `reply_bot` only, so a
  keyword-addressed silent never reached the existing 🗿 mechanism.
- `_decision_addressed()` (L5433) and `_f6_chat_facts()` (L20411) re-scanned the
  full text with the service regex.

## 2. What was removed / kept

Removed (obsolete forced-text mechanisms, not re-added under another name):

- `force_reply_required` (trigger matrix result, `DecisionContext` field,
  `DIRECT_TRIGGER`/`DECISION_COMPLETE` telemetry fields).
- `TRIGGER_FORCE_KEYWORD` (`"force_keyword"`); keyword trigger is now
  `TRIGGER_KEYWORD = "keyword"`.
- `FORCE_LINE` ("прямое обращение к боту: текстовый ответ обязателен") and its
  injection into L1 conditions.
- Pre-set `pre_action = ACTION_REPLY` / `REASON_FORCE_DIRECT` branch and the
  `direct_force_reply_total` increment on keyword ("force_direct" stays in the
  reason vocabulary as historical telemetry only).
- Post-L1 override `l1_plan.action = "reply"` for keyword triggers.
- Service-local regex `\bбот\w*` and service-side re-classification of the same
  text.
- `DeliveryPolicy(force_reply=...)` / `direct_request=...` set from the keyword.

Kept: the configurable word family (`CHAT_BOTWORD_PATTERN`), persona-name /
mention / reply priorities, functional commands and memory-command parsing,
`DecisionContext`/telemetry shapes, the decision matrix for explicit requests,
L1 `react`/`silent` allowed sets, `silent` demotion for explicit requests/questions,
initiative/Observer paths, full forwarded/quoted material in `query`/context
(`_message_user_text` unchanged for semantic paths), 🗿 kill-switches.

`_plan_direct_l1(force_required=...)` keeps a keyword-only compatibility parameter
(default `False`, ignored) so existing direct callers/tests do not break; it no
longer affects the delivery policy or the L1 prompt.

## 3. Provenance rule (computed once)

`services/command_prefix.py` is the single owner of the word family and of the
trigger vocabulary (`TRIGGER_KEYWORD/MENTION/PERSONA_NAME/REPLY_TO_BOT/FREE_WILL`,
`is_genuine_address`). `own_message_text(message)`:

1. message has `forward_origin` → "" (whole text/caption is forwarded material;
   a hidden origin `MessageOriginHiddenUser` is still a forward — detection does
   not depend on the source name);
2. message sender `is_bot is True` → "";
3. otherwise `text` or `caption` of the same event, with
   `blockquote`/`expandable_blockquote` entity spans (UTF-16 offsets) removed —
   quoted fragments are not the participant's own words. Native `Message.quote`
   is not part of `text` in Bot API, so it never reaches the command word;
4. reply linkage is not provenance: a participant replying to a forwarded
   message with their own words is handled by the normal trigger path.

`handlers.direct_chat._direct_trigger_type(message, own_text)` computes the type
once (reply → mention → own @username → persona name → keyword, preserving the
existing order and the alan/kostik keyword exclusion) and the handler passes
`trigger_type` into `DirectChatService.handle`. The service uses it as-is; only
direct callers/tests without `trigger_type` fall back to the same
`command_prefix` helpers (no divergent regex).

## 4. L1 autonomy and execution

- Reply → normal L1 pipeline (tools/L2/Writer) unchanged.
- Silent after a genuine address (keyword/mention/name/reply-to-bot) → existing
  `_execute_silent_ack` → 🗿 via `react_moai`, no text; env/per-chat gates kept.
- No genuine address (`free_will`, initiative) → no 🗿.
- Other allowed reactions (`react`) execute as chosen; explicit requests/questions
  keep the existing "silence is not an answer" demotion.
- Broken/empty/provider-failed L1 on a genuine address → existing deterministic
  fallback, and a fallback `silent` is turned into a text reply (recovery is not
  reported as a deliberate silence).

## 5. Tests (deterministic, no mass LLM runs)

New: `tests/test_p0_trigger_force_l1.py` (20 tests; real aiogram `Message`/
`MessageOrigin*`/`MessageEntity` objects for provenance; injected L1 plans for
action execution).

| Scenario | Fix (GREEN) | Base `f2cb38c84` (RED/GREEN) |
|---|---|---|
| own text keyword/mention starts contour | pass | RED (no `trigger_type` handoff; behavior green) |
| forwarded text / hidden origin / forwarded caption keyword | pass | RED (base triggers) |
| third-party bot text | pass | RED (base triggers) |
| keyword inside quote block | pass | RED (base triggers) |
| own text outside quote triggers | pass | RED (handoff kw) |
| reply to forwarded with own words | pass | RED (handoff kw; behavior green) |
| reply to bot still triggers | pass | RED (handoff kw; behavior green) |
| L1 `reply` executes | pass | pass (old force replied too) |
| L1 `silent` → 🗿, no text | pass | RED (base overrides to reply) |
| L1 `react` executes chosen reaction | pass | RED (base overrides to reply) |
| no genuine address + L1 silent → no 🗿 | pass | pass (preserved) |
| silent-ack conjunction unit | pass | RED (old `reply_bot` API) |
| L1 outage genuine address → reply | pass | pass (old force replied too) |
| L1 outage, matrix would be silent, genuine address → reply | pass | pass (old force replied too) |
| concrete user task executes | pass | pass |

Commands (worktree root, `PYTHONPATH=<worktree>`, `-p no:cacheprovider`):

- fix: `python -m pytest tests/test_p0_trigger_force_l1.py -q` → **20 passed**.
- base: same file copied into the release worktree, run, then removed →
  **14 failed, 6 passed** (the six passes are the preserved behaviors above).

Affected legacy suites (fix run):

`test_direct_chat, test_direct_chat_handlers, test_addtr_entry_caption,
test_epic72_gates, test_command_registry_round1015, test_asap8_f5_module_truth,
test_asap8_v63_b07_temporal_factcheck, test_p0b_current_question_priority,
test_smoke_round1016_fixes, test_smoke_round1016_nostalgia_persona,
test_direct_decision_matrix_asap3, test_asap7_direct_l1,
test_direct_context_composer_asap3, test_direct_l1_corrective_r1,
test_asap2_telemetry_clar, test_asap2_clar_contract, test_agentic_events_round1026,
test_asap7_direct_settings, test_asap8_f6_initiative, test_asap8_v6_wc_direct_d03,
test_asap8_v6_wc_direct_matrix, test_auto_budget_asap31, test_ur_turn_engine,
test_ur_c_clock, test_ur_b_live_wiring, test_selfdiag_corrective_research,
test_soul1_composer_parity_off, test_soul1_machine_profile_no_core,
test_ui_verbilizer_tabs_round1023, test_asap_fc_voice_l1_decision_profile,
test_asap3_identity_aliases`
→ 1027 passed, 13 failed (flaky environmental subset varies 13–16 between runs).

Pre-existing failures proven identical on the base worktree:

- 7-file comparison batch (selfdiag, soul1 x2, ui-verbilizer, asap_fc_voice,
  direct_l1_corrective, asap2_clar_contract): fix **15 failed / 108 passed**,
  base **15 failed / 108 passed**, same list.
- `test_auto_budget_asap31::TestFallbackRecompose::test_no_fallback_model_no_adapter`
  fails on base and fix.
- `test_direct_l1_corrective_r1::test_build_l1_context_bot_replies_caps_and_limit`
  fails on base and fix (the other, `test_autonomous_line...`, was updated to the
  new contract: `FORCE_LINE` must not exist).

Legacy-contract tests updated (old forced-reply expectations replaced by the new
contract, not weakened): `test_direct_decision_matrix_asap3` (matrix returns a
single type; keyword goes through the decision matrix; no force counter/fields),
`test_asap7_direct_l1` (keyword + L1 silent → 🗿, no override),
`test_direct_context_composer_asap3` (no force field), `test_direct_l1_corrective_r1`
(no `FORCE_LINE`), `test_ur_turn_engine` (`DeliveryPolicy.force_reply=False`),
`test_direct_chat` (two cooldown/limit tests now use a non-keyword question so
they keep measuring limits rather than the removed force).

Checks: `git diff --check` clean; `python -m py_compile` clean for all changed
modules and tests.

## 6. Configuration

- No new flags/env vars; `CHAT_BOTWORD_PATTERN` / hot `reactions.chat_botword_pattern`
  and `DIRECT_SILENT_ACK_ENABLED` / `flags.chat_silent_ack_enabled` unchanged.
- Tests ran with `pytestmark = [system2, asap3]` for the new file so prod defaults
  (silent ack ON) apply, matching the existing ASAP harness; no factory defaults
  changed.
- Python `C:\Users\main\AppData\Local\Python\bin\python.exe`; `PYTHONPATH` = worktree.

## 7. Residuals / honest limitations

- Section 4 (media binding / wrong reply target / image-instead-of-audio) is not
  addressed in this lane; no claim about its root cause is made here.
- `_PEER_PREFIX_RE`/`_strip_direct_prefix` (address-prefix stripping for
  `<Current_Question>` and memory commands) still uses its hardcoded family; it is
  a stripping helper, not a trigger, and was left untouched to avoid changing
  memory-command parsing.
- Direct service callers outside the handler (diagnostic tools / evidence scripts)
  call `handle()` without `trigger_type`; they get the keyword/persona/mention
  fallback without message provenance. Production entry is the handler.
- Per Bot API, "forward with comment" arrives as a separate comment message
  (own message, no `forward_origin`) linked by reply, so own comments still work;
  a single message carrying `forward_origin` is treated wholly as forwarded
  material by design.
- Pre-existing environmental failures listed in §5 are unrelated to this lane and
  were not fixed here.
