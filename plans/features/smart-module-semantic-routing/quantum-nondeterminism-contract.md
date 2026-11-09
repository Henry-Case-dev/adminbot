# Contract — full quantum non-determinism (proactive nostalgia + regular initiative)
**Slice:** smart-module-semantic-routing / QND-NONDET (mandatory corrective; no new epic, no OFF/SHADOW mode)
**Source:** `plans/owner_inputs/2026-11-10-quantum-nondeterminism-correction.md` (binding, "tie-break-only" CANCELLED)
**Depends on:** VMQ-ONTO-01 `Q-01`,`Q-02`,`Q-06`,`Q-07`,`Q-09`,`I-02`,`I-05`  **Supersedes:** `nostalgia-seam-contract.md` §3 only.

## 1. Per-chat stochastic scheduling of the semantic check
Module `services/semantic_schedule.py` (one module, both mechanisms: `MECH_NOSTALGIA="nostalgia"`, `MECH_INITIATIVE="initiative"`).
API: `ensure(db, mechanism, chat_id, *, now=None)`, `due(db, mechanism, chat_id, *, now=None) -> bool`, `claim(db, mechanism, chat_id, *, now, owner) -> bool` (atomic single-row lease),
`draw_next(db, mechanism, chat_id, *, now, source, trigger, reason="") -> dict`, `mark_executed(db, mechanism, chat_id, *, now, trigger, lateness_seconds, missed_count)`,
`request_event(db, chat_id, *, reason, now=None)`, `due_chats(db, mechanism, *, now) -> list[int]`.
Durable record — table `semantic_schedule`, `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47` in `services/database.py`, written through `DatabaseService.write_transaction`:
`PRIMARY KEY (chat_id, mechanism), next_due_ts, last_check_ts, last_draw_ts, lo_seconds, hi_seconds, shape, u, delay_seconds, source, provider, draw_id, fallback_reason, settings_hash, missed_count, scan_requested_at, lease_until, lease_owner`.
Distribution (bounded, adaptive, zero hardcoded numbers): `lo = _param(chat_id,"limits.qnd_<m>_min_seconds",…)`, `hi = limits.qnd_<m>_max_seconds`, `floor = limits.qnd_cadence_floor_seconds`,
`shape = limits.qnd_cadence_shape` (1.0 = uniform). Deterministic adaptive multipliers: `act = clamp(limits.qnd_activity_min_factor, limits.qnd_activity_max_factor,
initiative_observer.recent_message_rate / limits.qnd_activity_target_mps)`; `sil = 1.0` while `now - last_user_ts < limits.qnd_silence_hours*3600` else `limits.qnd_silence_factor`;
`bud = limits.qnd_budget_factor` when remaining `eval_llm_budget_per_day`/`max_replies_per_day`/`worker_budget.get_usage` < 20 % else 1.0; published messages only shrink `lo`
against `min_gap_seconds`/`ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS`, never `hi`. `lo_adj = max(floor, lo*sil*bud/max(1.0,act))`, `hi_adj = max(lo_adj, hi*sil*bud)`.
One draw: `u = DrawResult.value` from `draw_probability(purpose="<m>_schedule", chat_id=chat_id)`; `delay = lo_adj + (hi_adj-lo_adj) * u**shape`; `next_due_ts = now + round(delay)`;
quiet hours shift deterministically to the next allowed local hour (no second draw). Every bound/profile/weight is a `ParamSpec` in `services/param_catalog.py`
(`category=limits`, `group="limits_qnd"`, `pg_id="limits.qnd_*"`) rendered in the existing module tabs `mod_initiative` / `memory_nostalgia`; no new admin page, no `.env`-only numbers.
Restart: an existing row is authoritative (`next_due_ts` never re-derived from wall clock); missing row → one draw at the first heartbeat, `reason="no_state"`.
Missed deadline: at most ONE execution per `(chat, mechanism)` per claim — `lateness = now - next_due_ts`, execute once, then ALWAYS `draw_next` again;
`lateness > limits.qnd_stale_seconds` → do not execute, only re-draw, `quantum_schedule_due{executed=false, reason_code="stale_deadline"}`, `missed_count += 1`.
Never a queue of owed runs, never a catch-up loop, never a batch send.
Concurrency: conditional `UPDATE … SET lease_until=?, lease_owner=? WHERE chat_id=? AND mechanism=? AND lease_until<=?` (rowcount 1 wins, TTL `limits.qnd_lease_seconds`) plus the
existing `NostalgiaWorker._run_lock` and `max_instances=1, coalesce=True` heartbeats; a loser emits `reason_code="lease_held"` and does nothing.
Settings change: `settings_hash = sha256` of the resolved bounds/weights; on mismatch clamp `next_due_ts` into the new `[lo_adj, hi_adj]` measured from `last_check_ts`, if that lands
in the past set `now + lo_adj`, never execute, emit `reason_code="settings_rescaled"`.
Periodic heartbeats remain and only execute due events: `nostalgia_tick` (`NostalgiaWorker.start`, becomes a ≤`limits.qnd_heartbeat_seconds` poller), `initiative_observer_tick`
(`_INITIATIVE_OBSERVER_TICK_SECONDS`, passes only `due_chats`/`scan_requested_at` chats), `intent_heartbeat_tick`, `experience_review_tick`, `db_wal_checkpoint`, `memory_communities_build`.
The PRNG start jitter `random.randint(0, worker_budget.jitter_safe(base_minutes))` in `NostalgiaWorker.start` is REMOVED (pseudo-random cadence).

## 2. Event-driven path — real wakeup, not a scanner
Trigger source (one, existing pipeline point): in `handlers/summary.py`, function `summary_observer`, immediately after the successful
`await message_identity.save_live_message(...)` (line 547 at `1a4a9b1b`), call `semantic_schedule.request_event(db, chat_id=message.chat.id, reason="live_message", now=ingested_at)`;
it sets `scan_requested_at` and `next_due_ts = min(next_due_ts, now)`. Optional second signal at the existing post-turn point `services/turn_trace.py::close()` → `emit_delivery()`
(`EVENT_DELIVERY="direct_turn_delivery"`, called from `services/direct_chat_service.py` `finally: _ttrace.close(correlation_id)`): a listener registered in
`MemoryMaintenanceService.start()` calls `request_event(..., reason="post_turn")`. No polling of message text is added anywhere.
Dispatch is immediate: `request_event` schedules `TaskSupervisor.run(...)` → `initiative_observer.observe_tick(db, …, trigger="event", only_chat=chat_id)`;
`InitiativeObserverRunner.run(job_id, *, only_chat=None)` gains that optional parameter (precedent `NostalgiaWorker.run_once(chat_id=…)`).
Forbidden: a second Observer, a second LLM pipeline, lexical/dictionary/regex triggers, a periodic scanner presented as event reaction.
Bounding (no evaluation storm): per-chat single-flight — if a job for the chat is already `queued|running` the signal is DROPPED (`reason_code="event_dropped_busy"`), not queued;
debounce `limits.qnd_event_debounce_seconds` between event-triggered evaluations; event floor `limits.qnd_event_min_interval_seconds` between paid evaluations (the schedule path keeps
the profile `eval_min_interval_seconds` floor); both consume the same `initiative.eval_llm_budget_per_day` and `MAX_EVALS_PER_PASS`.
Shared, never duplicated: `mca_intents.candidate_from_trigger` → `direct_chat_service.handle_initiative` (Decision/Writer/`mca_intents.SendRecheck`), `publication_coordination` claim,
dedup (`context_hash`/`recent_hashes`, `topic_key`/`max_replies_per_topic`, nostalgia `_told_identities`), send accounting (`sent_stamps`, `nostalgia_log`, `mca_events`).
Live nostalgia = `NostalgiaWorker.recall_in_conversation` → `_delegate_initiative`, identical to the scheduled path.
Provenance: every evaluation carries `trigger="schedule|event"` in `_note_decision`/`_skip_eval` and in the durable event, so a start reason is provable from logs.

## 3. Publication probability replaces the double gate
Factors (server-computed, clamped 0..1, logged as a dict): `r` relevance (`verdict["relevance"]`; nostalgia `_episode_weight`/retrieval score), `s` significance (`verdict["significance"]`;
nostalgia candidate `weight`), `a` activity fit `min(1, rate/limits.qnd_activity_target_mps)`, `t` freshness `1 - min(1, age/limits.qnd_freshness_horizon_seconds)`, `q` memory quality
(top retrieval score / `limits.qnd_memory_quality_reference`; the weight is dropped and the rest renormalised when a candidate has no memory evidence),
`n` recent initiatives `min(1, sent_in_window/max(1,max_replies_per_day))`. `S = (Σ w_i f_i)/(Σ w_i)` with `limits.qnd_w_*`; `p = p_min + (p_max-p_min)*logistic((S-θ)/τ)`,
`θ=limits.qnd_publication_theta`, `τ=limits.qnd_publication_tau`, `p_min/p_max = limits.qnd_<m>_publication_min|max`, clipped. An explicitly set per-chat `initiative.trigger_probability`
is honoured as `p_max` (compat mapping, `migration_class=deprecated_compat`, `hidden=True`); its default 1.0 is no longer a gate.
Draw location: `services/quantum_publication.py::decide(db, *, mechanism, chat_id, factors, candidate_ref, source, trigger, now) -> PublicationDecision`, one
`draw_probability(purpose="<m>_publication")`, publish iff `not deferred and u < p` — this is the publication decision for every positive-enough candidate.
Forbidden: pre-evaluation coin tosses (`initiative_observer.random_trigger` at the eval gate is REMOVED) and any second later SILENT filter — after `decide()` returns publish, no
component may re-run an appropriateness verdict on that candidate.
Ordering is frozen. BEFORE the draw: gates (`feature_gates.gates_enabled`/`gate_blocks_publication`), module/master OFF, rights/ACL, day caps, `min_gap`/anti-flood, topic cap,
dedup/context hash, eval budget, `publication_coordination.precheck`; semantic evaluation also runs before the draw, and `action="silent"` requires
`veto_reason ∈ {no_substance, not_appropriate, unsafe, direct_request, addressed_elsewhere}` → `silence_cause=semantic_none`, NO draw.
AFTER the draw: `publication_coordination.acquire` → Writer → `begin_sending` → SendRecheck (`build_fresh_recheck_context`) → `send_message` → `close(published=True)` → accounting.
SendRecheck is freshness/revalidation only: `proceed|recheck_again(≤1)|recheck_demoted` with `reason_code ∈ {direct_request_seen, message_already_answered, topic_closed, context_conflict}`;
it must not re-decide appropriateness, must not re-draw, must not apply its own probability.
Recorded per decision: `probability=p`, `value=u`, `source=quantum|pseudorandom`, `provider`, `draw_id`, `fallback_reason`, `policy_version`, `hit`, `outcome`,
`silence_cause ∈ semantic_none|limits|dedup|send_recheck|random_miss|random_unavailable|module_off`.

## 4. Single source of randomness (no PRNG mixing)
Only `services/mca_random_source.RandomSourceService` (+ VMQ-ONTO-01 adapters). Purposes added to `SANCTIONED_DRAW_PURPOSES`: `nostalgia_schedule`, `initiative_schedule`,
`nostalgia_publication`, `initiative_publication`; `_direction_pick` keeps `memory_recall`; `initiative_trigger` is retired. One choice = one `DrawResult` from one batch value.
Forbidden inside these paths: `random.Random`, `random.randint/choice`, `numpy.random`, `secrets`, `worker_budget.jitter_safe`. Allowed deterministic transforms only:
`map_value_to_index` (rejection sampling, no modulo bias), `value/value_range` → uniform `[0,1)`, `u**shape`, inverse-CDF weighted pick (one `u`, cumulative weights) — no
pseudo-randomness and no distribution bias added.
Provider policy untouched: `selected_mode`, `resolve_effective`, `fallback_enabled`, `mca_gates.random_source_enabled()`, ANU/LfDR/Lizaonair registry, IBM direct demand-first pool,
timeouts, quota, `AnuClient`. `deferred`/`disabled` → schedule: no execution, retry at the next heartbeat keeping the reason; publication: `outcome=blocked_random_unavailable`,
nothing published. Local PRNG only when `memory.random_fallback_to_pseudorandom=true`, then `source=pseudorandom` + `fallback_reason` recorded and displayed; every draw reaches
`mca_random_draws` + the decision event with its actual source.
No temporary independent QRNG circuit: the cross-epic dependency is explicit — these consumers sit on `VMQ-Q0` (one service, adapters, journal) and `VMQ-Q0-IBM`; a missing provider
yields honest `random_unavailable`, never a local generator. `QND-NONDET` extends `VMQ-Q1` rows `I-02`, `I-05`, `Q-09`.

## 5. Metrics and admin views
Durable events (`emit_mca_event`, component `qnd`): `quantum_schedule_draw{mechanism, chat_id, lo, hi, shape, u, delay_seconds, next_due_ts, source, provider, draw_id,
fallback_reason, settings_hash, trigger}`; `quantum_schedule_due{mechanism, chat_id, planned_at, executed_at, lateness_seconds, missed_count, executed, trigger}`;
`quantum_evaluation{mechanism, chat_id, trigger, candidate_ref, factors, S, budget_left}`; `quantum_publication_decision{mechanism, chat_id, trigger, candidate_ref, factors, S, p, u,
hit, outcome, silence_cause, source, provider, draw_id}`; `quantum_publication_result{mechanism, chat_id, outcome=delivered|dedup|send_recheck|cap, reason_code, latency_ms}`.
Status (`GET /api/status`, existing "Статус" tab — «быстро увидеть, что происходит»), one block per mechanism: last and next semantic check (absolute + countdown), source of the
last draw `quantum|fallback|unavailable`, allowed/deferred/rejected today, deliveries today. Analytics ("Аналитика" — «почему и как менялось»): interval histogram and
per-chat/per-period activity from `quantum_schedule_draw`, planned vs event evaluations, candidate table with `p`/`u`/outcome, silence shares by `silence_cause`, repeats and real
deliveries, quantum/fallback share. Sources — existing routers only: `web/api/initiative_vitality.py::memory_initiative_vitality`,
`web/api/initiative_publications.py::list_publications`, `web/api/memory_agi.py` (`_nostalgia_state`, nostalgia log route), `web/api/analytics_viz.py`;
aggregates reuse `services/initiative_diagnostics.py::collect_window`.
Honesty: `draws_quantum == 0` in the window → «квантовый источник не использовался»/«fallback» and the word «работает» is forbidden; a missing denominator shows «нет данных»,
never a fabricated percentage; no metric exists without its durable event.

## 6. Alignment and mandatory corrective to already-shipped proactive nostalgia
`Q-01/Q-02/Q-06/QM-01` remain the only source, selection/effective/fallback order and provider settings; `Q-07` (n=1 without entropy spend, unbiased mapping) applies to the new draws;
`Q-09` is satisfied by §7's decisive test; dreams/memory integrations stay unchanged.
Corrective to `6674811f`, mandatory in the same release, not deferred: (a) `NostalgiaWorker._direction_pick` stops being an equal-weight band choice (`_DIRECTION_BAND=0.999`, band from
`_EPISODES_MAX-1`) and becomes a weighted quantum choice over ALL eligible candidates with inverse-CDF weights from the existing `0.65*relevance + 0.2*coverage + 0.1*usage`,
recording `info["direction"]{source,draw_id}`; (b) `_candidate_llm_send` replaces the threshold-then-`UNCHANGED` double gate with §3 `decide()` for every candidate passing the LLM
appropriateness veto; (c) `NostalgiaWorker.start` drops the PRNG tick jitter and the semantic cadence moves to §1; (d) `recall_in_conversation` uses the same `decide()` and accounting;
(e) `initiative_observer.random_trigger`/`PURPOSE_INITIATIVE_TRIGGER` at the evaluation gate is removed and `initiative.trigger_probability` becomes the `p_max` compat mapping;
(f) `_next_check_ts` stops promising `last_eval_ts + profile` and reports `semantic_schedule.next_due_ts`.
Preserved: user settings, chat overrides, PET_PROJECT release rule, no OFF/SHADOW, no new agents, no human gate.

## 7. Tests (exact names, controlled RandomSource, no wall-clock races)
`tests/test_qnd_schedule.py::test_per_chat_draws_use_quantum_and_differ_between_chats`;
`::test_long_run_200_cycles_matches_scripted_source_and_has_no_fixed_interval` (exact `next_due_ts`, every delay inside `[lo_adj,hi_adj]`, no two equal consecutive delays);
`::test_restart_keeps_next_due_and_executes_once`; `::test_missed_deadline_executes_once_then_redraws` (one execution, `missed_count=1`);
`::test_stale_deadline_redraws_without_mass_send` (zero sends, `executed=false`); `::test_concurrent_claim_yields_single_execution` (second claim `lease_held`, one send);
`::test_settings_change_clamps_without_execution`; `::test_inactive_chat_intervals_longer_within_bounds`; `::test_two_chats_are_independent` (different `next_due_ts`, no shared tick);
`::test_module_disabled_takes_no_draw_and_publishes_nothing` (zero `draw_probability` calls, zero sends); `::test_provider_failure_is_honest_not_quantum` (`deferred` →
`random_unavailable`, `source != quantum`, nothing published); `::test_no_pseudorandom_in_semantic_paths` (`random`/`numpy.random`/`secrets` patched to raise).
`tests/test_qnd_publication.py::test_same_semantic_situation_different_quantum_values_differ` — decisive: identical factors and gates, `u=0.02` → `outcome=delivered`,
`u=0.98` → `outcome=silent, silence_cause=random_miss`, both from one scripted source sequence, both legal;
`::test_probability_monotone_bounded_and_inside_settings`; `::test_hard_limits_and_dedup_precede_the_draw` (no draw when capped); `::test_sendrecheck_never_redraws_or_redecides`;
`::test_llm_veto_without_veto_reason_is_semantic_parse_error`.
`tests/test_qnd_event_path.py::test_live_message_signal_starts_evaluation_with_trigger_event` (`trigger="event"` in the durable event, same Decision/Writer/SendRecheck);
`::test_event_dropped_when_chat_busy_and_per_chat_debounce`; `::test_event_path_respects_eval_budget_and_floor`;
`::test_event_and_schedule_share_dedup_and_send_accounting` (one delivery, one ledger row).
`tests/test_qnd_metrics.py::test_status_never_reports_working_without_quantum_draws`; `::test_interval_histogram_and_silence_shares_from_events`;
`::test_probability_value_source_outcome_recorded_per_decision`. Long reproducible acceptance runs (`FakeRandomSource` precedent `tests/test_goodmorning.py::FakeRandomSource`,
extended with `draw_probability`): 200 cycles, restart, two chats, inactive chat, module off, provider failure. Evidence → `plans/features/vmq-onto-01/evidence/vmq-q1/`.

## 8. Parallel safety, rollback, risk
`SERIALIZE`: `services/database.py` (v47) → `services/mca_random_source.py` (VMQ-Q0 owns it) → `services/semantic_schedule.py`/`services/quantum_publication.py` →
consumers (`nostalgia_worker.py`, `initiative_observer.py`, `memory_maintenance.py`, `handlers/summary.py`) → UI/API. `READ_ONLY_PARALLEL`: metrics routers, tests.
`BLOCKED_BY:VMQ-Q0` for any purpose addition. Rollback = revert consumers, the additive table stays inert (no down-migration), user settings untouched.
Risk R2: wrong ordering or a surviving double gate is a product-behaviour defect, caught by the §7 decisive test.

QUANTUM NONDETERMINISM CONTRACT FROZEN

Integration points:
1. `services/semantic_schedule.py` + table `semantic_schedule` → `NostalgiaWorker.start/_tick/_run_tick`, `initiative_observer.observe_tick`/`InitiativeObserverRunner._evaluate_phase`, `MemoryMaintenanceService._tick_initiative_observer`, `handlers/summary.py::summary_observer`.
2. `services/quantum_publication.py::decide` → `NostalgiaWorker._candidate_llm_send`, `InitiativeObserverRunner._act_on_opportunity`/`_act_on_memory_recall`.
3. `services/mca_random_source.py` (purposes, journal, trace) + `services/param_catalog.py` and `web/app.js` (`limits.qnd_*` in existing module tabs).
4. `web/api/initiative_vitality.py` + `web/api/initiative_publications.py` + `web/api/memory_agi.py` + `web/api/analytics_viz.py` (Status/Analytics blocks, honesty rules).
