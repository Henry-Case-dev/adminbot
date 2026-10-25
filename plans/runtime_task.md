# Runtime Task — P0 speech corrective (root chat 25.10.2026)

Status: **paused_by_owner** (16:18 +12). No new agent dispatch; resume only by owner command.

## Source
- Corrective prompt: root chat 25.10.2026.
- Verbatim snapshot: `plans/features/asap-speech-arch/source-owner-p0-corrective-2026-10-25.md`
  (book commit `67a9c823`; copy in `adminbot-wt-speech-p0` is untracked).
- Prior P0 source: `source-owner-p0-hotfix-chained-2026-10-25.md`.

## Code / production
- Branch `task/speech-p0-hotfix` @ **`272170e3`**:
  - `47fba465` — L1 semantic routing (material/history → research; quick opinion → answer; depth ≠ length; no hardcoded phrases) + same-commit harness.
  - `272170e3` — old-lore provenance/quarantine (nullable columns, baseline/facade predicate, graph self-origin filter, targeted id=3/4, no mass delete). Not independently reviewed.
  - `9ade73bf` — L1 evidence; `5c2d134b` alias audit; `dd10de9d` prod audit; `b49f309f` old-lore audit.
- Prod: **2.58.130 @ `534ac7dd`**, unit active, NRestarts 0. **No deploy.**
- Prod worktree: 13 untracked leftovers, `git diff` empty; deploy by explicit SHA, no reset/cleanup.

## Unfinished
1. Alias runtime fix F1-F7: L1 reply uid/alias, Observer, worker `bind_turn_aliases`, alias-map instruction, protected facts by `subject_ref_id`, `memory_name`, diag. Audit `5c2d134b`.
2. Live L1 probe + same-commit harness with real RAG/Memory/Core/Expression/FREQUENT; full probe `a97ba573` was not production-equivalent.
3. Reviewer recheck; map evidence binding; corrective map 95 required PENDING; HARNESS map gap.
4. Deploy after Reviewer, version/health/errors.

## Known live findings
- Active Core `ead77b2ab509`, 3294 chars (owner_edit rev8); P0 filter → 1246.
- Alias uid `42115912`: effective alias «Макс»; Telegram display «Гипербореец»; `author_name` historical; exact response `1175361` prompt not traced.
- `lore_stories` id=3/4 are bot answers; targeted quarantine committed but not applied/verified on prod DB.
- Foreign `stash@{0}` must not be applied; worktree has no foreign paths.

## Resume
On owner command: inspect branch/worktree, finish alias/live probes, Reviewer recheck, bind map, deploy. Do not reset/delete production or foreign stash.
