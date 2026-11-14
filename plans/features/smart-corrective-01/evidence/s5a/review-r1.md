Needs Fixes - F-S5A-01 
 
BLOCKER F-S5A-01: delivery_unknown loses durable reason during takeover and recover_job resumes queued.  
Reproduction scratch SQLite: takeover no_change/reconcile_required, then recover_job resumed=True and final queued/recovery_from_checkpoint.  
Focused tests: lifecycle and incident 26 passed; observability/task-supervisor 102 passed, 1 deselected.  
Verdict Needs Fixes. Candidate 6714dd1c. 
 
Re-review r2 (F-S5A-01 fix)  
Candidate 8a64c7af39e804d069775f2f8b4265ab01bcca5e; evidence 1267ab9e845c7408d47ece32a61d2137443f5149.  
Exact sequence PASS: takeover returned no_change/reconcile_required; row interrupted, reason_code and error_code delivery_unknown, next_retry_at None; recover_job returned resumed False/status reconcile_required; final row stayed interrupted; no recovery_from_checkpoint event.  
Tests: 27 passed for S5A plus incidents; baseline observability/task-supervisor 102 passed, 1 deselected.  
Mutation: copied worktree to disposable run, changed guard to if False; focused regression failed with resumed versus reconcile_required. Guard is therefore meaningful.  
Updated not-retried test asserts marker preservation; no weakening. No DDL or new flags/settings in fix diff.  
Resume paths inspected: mca_watchdog.recover_job; media_readiness recover_job; cover recovery; vision watchdog recover_stale; meme interrupted; mca_trace retry/resume; set_next_retry. The generic mca_watchdog path is guarded by reason/error marker.  
Remaining blocker: media_readiness.py:1695-1748 has an independent recovery path that accepts a caller-supplied reason and calls requeue without checking durable delivery_unknown. mca_trace.py:511-535 checks reason_code only, not error_code, so an error_code-only delivery_unknown row could bypass retry/resume. These are IN_SCOPE blockers for the broader controlled scope unless proven unreachable for affected jobs.  
Ledger: SC-WD-W03 remains UNVERIFIED/Needs Fixes for broader bypasses; F-S5A-01 generic watchdog path fixed, but S5A not Approved.  
Verdict: Needs Fixes.
 
Re-review r3 (F-S5A-02/03 fix)  
Candidate 3ff04f3f6c4476851174e67f1e163db7504a1c9; evidence e360738b.  
F-S5A-02 FIXED: exact generic and media sequences on scratch SQLite preserve interrupted row, delivery_unknown marker, next_retry_at=None; generic recover_job and media caller-supplied worker_lost return reconcile_required/none without requeue.  
F-S5A-03 FIXED: mca_trace retry and resume with reason-only, error-only, and both markers return reconcile_required; no state change. Primitives mark_running, finish queued/running, requeue, set_next_retry refuse both marker fields through SQL WHERE.  
Observed exact generic output: takeover no_change/reconcile_required; recover resumed=False/status=reconcile_required; final interrupted/delivery_unknown, no retry and no recovery event. Media suite: 284 passed, 1 warning.  
Mutation: disposable mca_trace guard removed; focused control retry/resume regression failed with ('both','retry') noop instead of reconcile_required. Guard-sensitive.  
Regression: combined S5A/incidents/observability/task-supervisor 133 passed, 1 deselected.  
Audit: task_supervisor primitives and recover_stale; mca_watchdog recover_job; media_readiness recover_job/_bump_fence_and_requeue; mca_trace control retry/resume; cover_style recovery; mca_vision watchdog; meme interrupted; all state-changing calls use TaskJobStore guards. Raw writers only assign delivery marker or terminal outcomes; no unguarded resume path found. recover_stale preserves reason_code; error-only marker remains in error_code and SQL guards block re-arm.  
No DDL, flags, or settings changes in fix diff. No remaining S5A blocker found in reviewed scope.  
Ledger: SC-WD-W03 remains UNVERIFIED in map; behavior is independently supported by this re-review but map was not edited and no requirement is marked VERIFIED.  
Verdict: Approved for implemented S5A controlled scope; F-S5A-02/03 fixed. Not production acceptance; no production access. 
