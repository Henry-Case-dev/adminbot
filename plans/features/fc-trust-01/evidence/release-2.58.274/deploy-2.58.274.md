# Release 2.58.274 — production deploy (192.255.209.205, `/var/www/admin_bot`)

- **Deployed SHA:** `731a7e51cdb747fb3c0507ec80b885e4217766b0` (branch `release/2.58.274`, tree `16d79f701767a932bf942c1b49a21650915559bd`, version **2.58.274**)
- **Previous production:** `74ef57ef469220627207603ae133da308f37866f` (2.58.273)
- **Rollback target:** `74ef57ef469220627207603ae133da308f37866f`
- **Independent review:** `plans/features/fc-trust-01/evidence/fct-s4-reliability-2026-11-28/review-r1.md` — `APPROVED_FOR_RELEASE_PREPARATION`
- **Candidate:** `feat/fct-s4-reliability-2026-11-28` tip `320517373`, code `dc6703a8f`
- **Deploy moment:** 2026-11-28T10:41:12Z (`.deploy/release.json`), restart 10:41:13Z, settle check 10:52:07Z
- **Raw evidence:** `raw/deploy-run.txt`, `raw/deploy-postcheck.txt`, `raw/_deploy.sh`, `raw/_postcheck.sh`

## Verdict: DEPLOYED_AND_VERIFIED

## 1. Identity on the server

```
PRE_HEAD=74ef57ef469220627207603ae133da308f37866f  PRE_REF=refs/heads/release/2.58.273
PRE_DIRTY_TRACKED=0  PRE_UNIT=active NRESTS=0  PRE_VER=2.58.273
REMOTE_SHA=731a7e51c…  NEW_HEAD=731a7e51c…  NEW_REF=refs/heads/release/2.58.274
NEW_TREE=16d79f701767a932bf942c1b49a21650915559bd  POST_CHECKOUT_DIRTY_TRACKED=0
FINAL: HEAD=731a7e51c… REF=refs/heads/release/2.58.274 TREE=16d79f70… DIRTY_TRACKED=0
```

Fetched and checked out strictly the assembled SHA (refetch of `origin/release/2.58.274`, abort-on-mismatch in the script; no mismatch).

## 2. Artifact identity versus the approved candidate

| file | sha256 on prod | expected (candidate) | match |
|------|----------------|----------------------|-------|
| `handlers/factcheck.py` | `6046df0c2f777446a0d4016608de2c4f19a69cfc04976629fa1f76793ee92a5b` | same | **yes** |
| `services/persistent_throttling.py` | `0a4d0ee071114696dee1ed7ce3f904896b04c046a9fdfa965dd9680d885c6cf2` | same | **yes** |
| `services/smartmodule_throttling.py` | `9021fe9ee546f5ccedbdf8f89fe23b69c7a75912d4afcd400bbb22a5c465dc03` | same | **yes** |
| `tests/test_fc_trust_s4_reliability.py` | `fd9671393a022e4f0a29c6074d315cc0c16209b631b994ec7d22c5e6724dcab7` | same | **yes** |
| `web/api/routes.py` | `5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf` | unchanged vs 2.58.273 | **yes** |
| `web/app.js` | `20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74` | unchanged vs 2.58.273 | **yes** |
| `web/index.html` | `b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907` | unchanged vs 2.58.273 | **yes** |

Routes/Mini App bundle were not touched by this release and are byte-identical to the previously deployed blobs.

## 3. Runtime

```
MANIFEST={"deployed_sha":"731a7e51c…","version":"2.58.274","effect":"deploy","previous_sha":"74ef57ef4…","previous_version":"2.58.273","release_branch":"release/2.58.274","dirty_tracked":false}
VER_AST=2.58.274  VER_IMPORT=2.58.274  VER_MANIFEST=2.58.274
LOCAL_HEALTHZ_HTTP=200  {"status":"ok","version":"2.58.274"}
PUBLIC_HEALTHZ_HTTP=200 {"status":"ok","version":"2.58.274"}
UNIT=active NRESTS=0 MAINPID=1335602 BOTPROCS=1 SINCE=2026-11-28 10:41:14 UTC
SETTLE (10:52:07Z): UNIT=active NRESTS=0 MAINPID=1335602 (unchanged, no restart loop)
SETTLE: local healthz 200 2.58.274, public healthz 200 2.58.274
```

## 4. Data / schema / settings (unchanged)

| item | before | after |
|------|--------|-------|
| `bot_settings` rows | 558 | 558 |
| `SETTINGS_MD5_KV` | `6f6d6624f5f676a1f26dc4be75128aed` | `6f6d6624f5f676a1f26dc4be75128aed` |
| `SETTINGS_MAXUPD` | 2026-11-27 21:48:55.892740+00:00 | identical |
| prompts keys / empty | 29 / 0 | 29 / 0 |
| `flags.factcheck_pipeline_v2` | present:true | present:true |
| SQLite `user_version` | 50 | 50 |
| `PRAGMA quick_check` | — | `ok` (276.7 s, post-check `ok`) |
| `throttle_state` | — | table present (126 rows, `scope,chat_id,user_id,burst_left,last_ts`), readable |

No migration/DDL ran (`git diff 74ef57ef4 HEAD -- services/database.py database migrations` empty).

## 5. Journal after restart

Window 1 (`10:41:13Z` + 5 s, 510 lines) and window 2 (whole 10:41:13 → 10:52:07, 903 lines):

```
J_TRACEBACK=0  J_SQL_ERR=0  J_CRITICAL=0  J_402_403=0
J2_TRACEBACK=0 J2_SQL_ERR=0 J2_CRITICAL=0 J2_402_403=0
```

The only `ERROR` lines are the anticliche wikipedia refresh (`[anticliche] refresh | status=fetch_error`),
which is a pre-existing external-source failure: **23 occurrences in the 2.58.273 window before this deploy**
and 1 after (same scheduled refresh). Not related to this release; no new error classes.

## 6. Disk

```
PRE_DISK  99G total, 51G used, 44G avail (54%)  PRE_AVAIL_KB=45230852
FINAL     99G total, 51G used, 44G avail (54%)
disk audit: top deploy_backup predeploy-258258 (6.8 GB), predeploy-258257 (6.8 GB), db_backup local_database_20261128 (5.6 GB)
disk cleanup --apply: deleted=0 bytes_freed=0 skipped=0 errors=0  (nothing eligible: keep=2 deploy pool already satisfied)
```

No temporary production artifacts were left: `TMP_LEFTOVERS=0`, `/tmp/wt_rb274*` removed by the run, `WORKTREES=1`.

## 7. Rollback readiness

```
git worktree add --detach /tmp/wt_rb274_<pid> 74ef57ef4…   (ok, removed afterwards)
RB_VERSION_AST=2.58.273  RB_BLOB=a99c70c916de15c5326fd1627ed1d654017729be
tools/release_manifest.py --dry-run --effect rollback → effect=rollback version=2.58.273
RB_RC=0
```

Rollback dry-run on `74ef57ef4` exits 0 and resolves version 2.58.273.

## 8. What was NOT verified (honest limits)

- No live Telegram / real provider factcheck request was driven against production in this deploy: the
  throttling single-flight/claim and cancel-refund paths are covered by `tests/test_fc_trust_s4_reliability.py`
  (11 tests) plus the 104/355 passing targeted suites, and by the independent review's RED/GREEN and mutation runs.
  Live factcheck cooldown behaviour was not exercised with real user traffic (no synthetic traffic to real users,
  per project rules).
- `PersistentCooldownTracker.claim` atomicity is single-process only (`REV-FCT-S4-02`); production runs one
  systemd process (`BOTPROCS=1`), so this is not a live exposure.
- Known narrow race `REV-FCT-S4-01` (cancel between delivery and `_settle_cooldown` may refund a used slot)
  remains as documented, non-blocking.

## 9. Deployed-candidate note

Evidence commit for this release sits on top of the deployed SHA; production runs
`731a7e51c…` (code + version bump), and the later evidence-only commit does not change product files.
