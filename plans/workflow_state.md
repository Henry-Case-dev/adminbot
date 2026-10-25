# Workflow State

Task: P0 speech hotfix + corrective (L1/harness, aliases, old lore) — остановлено владельцем
Task source: root chat 25.10; corrective snapshot `plans/features/asap-speech-arch/source-owner-p0-corrective-2026-10-25.md` (book `67a9c823`; hotfix copy untracked)
Status: paused_by_owner — новых агентов не запускать; продолжить по команде
Primary phase: review
Active feature: asap-speech-arch / P0 corrective
Progress sources: `requirements-map-p0-corrective.json` (95 required, 10 slices, plan gate EXIT 0) + prior P0/speech maps

Production: **2.58.130 @ `534ac7dd`**; healthz/юнит — 200/active, NRestarts 0. Нового деплоя нет.
Code branch: `task/speech-p0-hotfix` @ **`272170e3`** (L1 `47fba465` + lore quarantine `272170e3`); evidence `9ade73bf`.
Prod worktree: `534ac7dd`, 13 untracked leftovers, product diff пуст; deploy только явным SHA, без cleanup/reset.

Active lanes:
- none dispatched after owner stop. Lore lane already finished and committed `272170e3` before stop; alias lane was in-flight with no visible commit. Native cancel API отсутствует; no new work.

Uncommitted / preserved:
- `source-owner-p0-corrective-2026-10-25.md` — untracked in hotfix; source snapshot committed in book `67a9c823`.
- Foreign `stash@{0}` («wip(f1): IA v2 round1025…») untouched; worktree has no foreign paths. Не применять.

Verified / evidence:
- L1 `47fba465`: 261 profile tests, 7 route tests, harness `--self-check` PASS; material/history → research; quick opinion → answer; no hardcoded phrases; research exact analysis 1×. Live L1 not run.
- Lore `272170e3`: 14 new tests + 269/208/290 profile PASS; provenance columns/filters/targeted id=3/4 quarantine; no mass delete. Not independently reviewed.
- R1 `9650e099`: exact analysis/Writer 1× in deep/report; 44 P0 tests; active Core `ead77b2ab509` 3294→1246; current-turn excluded; L2 keep-head+marker; self-echo tentative/out of factual RAG.
- Full L2 matrix `a97ba573`: 8 raw; real L1 A/B = casual/compact; payload 1×/0 and RAG not covered; old tree dirty; not production-equivalent.
- Reviewer: **Needs Fixes** (`d4b3c979`, recheck `e7d67384`); no approval.
- Prod audit `dd10de9d`: 13 untracked backups/test dumps; no product diffs.
- Alias audit `5c2d134b`: uid `42115912` alias = «Макс» (global+chat), display = «Гипербореец»; L1 reply/Observer/background-snapshot defects; exact response `1175361` prompt not traced.
- Old lore audit `b49f309f`: `lore_stories` id=3/4 are bot answers; no provenance; targeted quarantine.

Not closed:
- Alias runtime fix F1-F7 (reply uid, Observer, worker snapshot, alias-map instruction, protected facts, memory_name, diag).
- Live L1/harness + RAG/Memory/FREQUENT real payload.
- Reviewer recheck, map evidence binding, deploy.
- Corrective map rows PENDING; HARNESS map gap noted.
- Progress % not reliable: `current_task.md` absent in code worktrees; root scope stale.

Next on owner command:
1. Inspect branch `272170e3` and alias work; commit only completed slices; no reset.
2. Finish alias/live probes/Reviewer/map, then deploy.

Review: needs_fixes
Deployment: not_deployed (prod 2.58.130)
Human gate: none
Updated: 2026-10-25T16:18+12:00
