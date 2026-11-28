# Release 2.58.265 state (devops)

- started: 2026-11-28
- base: c67683dd6 (2.58.264, product 0118dc081)
- candidate product: 6ab3b718a (branch feat/fct-s4-u2-verdict-2026-11-28, tip 6d911272e)
- canonical planning checkout: C:\Code\Python\adminbot (master) @ 2c1d512c2
- release worktree: ...\WorkspaceData\worktrees\c742e4de9e92c489\fc-trust-01-release-2-58-265-94f0827b8774-eff3b561 (branch release/2.58.265), registered

- PRODUCT: aa7f3f6d8 (3 services + 5 tests byte-identical to 6ab3b718a)
- BUMP: d95ac5ca0 (29 files / 34 occurrences, non_version_changed_pairs=0, CRLF preserved)
- evidence assembly: 55178d5bd (assembly.md sha256 95927ca4…), pushed origin/release/2.58.265
- tests: verdict 24 / core 218 / updated 96 / pins 62 passed; registry 668 OK
- DDL 0, schema 49, routes b8f63355, app.js 3631e82d

- DEPLOYED 2026-11-28T00:03:23Z: prod HEAD 55178d5bd, version 2.58.265, dirty=0,
  unit active/running NRestarts=0 MainPID=1154684 procs=1, chown adminbot 54 paths 644/755, unreadable 0,
  IMPORT_OK 2.58.265, product blobs 8/8 == candidate
- manifest: deployed_sha 55178d5bd, previous c67683dd6/2.58.264, dirty_tracked=false, deployed_at 00:02:23Z
- user_version 49; bot_settings rows 558, prompts 29, maxupd unchanged; routes b8f63355; app.js served == disk
- journal 00:03:23–00:17:49 (14.4 min, 805 lines): ERROR 2 (anticliche pre-existing), Traceback 1
  (initiative_observer LLM timeout, pre-existing class: 11 tracebacks in prior 62-min window),
  KeyError/AttributeError/TypeError 0; execution_status events 0 (no live factcheck turn)
- rollback dry-run rc=0 (to c67683dd6/2.58.264), temp worktree removed, worktrees=1
- disk: cleanup --apply deleted=1 freed 5.9 GiB (db_backup 20261127); 50G used / 44G free (54%)
- deploy doc: deploy-2.58.265.md sha256 82a2c1ff…

- COMPLETE: evidence committed; release branch tip carries assembly + deploy evidence.
