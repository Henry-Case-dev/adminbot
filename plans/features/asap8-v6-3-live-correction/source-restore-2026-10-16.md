# Source-of-truth map for `plans/current_task.md` (owner-managed)

Rechecked 2026-10-16 after the owner's second edit. Recorded by Orchestrator; this file
is agent-owned bookkeeping, it does not modify the owner's file.

| Property | Value |
|---|---|
| `plans/current_task.md` SHA256 | `bd2b08ccc3942dfe387f310f1ef551dfa7a1d052ec61ed80f5d98386ed6d7308` |
| Bytes / lines | 214258 / 758 |
| Block 1 — `# ASAP 8 v6.3 — Live Behavior, полноэкранный Telegram и настоящий Liquid Glass` | lines **1–450**, byte-identical to `plans/features/asap8-v6-3-live-correction/source-lines-37423-EOF.md` (SHA256 `d0b4f611ac5eff7d228a1d2a2d1e283f04b26625f2dac89ab5ad1145f10e686d`) |
| Block 2 — `# SOUL-1 — Unified Character, Adaptive Speech & Humor Learning` | lines **453–758**, byte-identical to `plans/features/soul-1/source-current-task.md` (SHA256 `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B`) |

Order is ASAP first, then SOUL — as the owner intended.

Consequences:

- Both requirement maps keep their source binding; **no map rebuild is needed** and every
  existing evidence/candidate binding stays valid.
- Earlier 37732-line version (which itself was the owner's first restore attempt) held the
  full historical task text plus the v6.3 block at the end. The current version contains
  ONLY the two active epics; the historical text and the 143-line block
  `# ASAP 8 — v6 / corrective delta after F1–F9` are no longer present in the file.
- Those removed pieces are still recoverable verbatim from
  `plans/features/asap8-v6-3-live-correction/current_task.snapshot_2026-10-15.md`
  (SHA256 `91f754e3993477e888e874cd88dcfaf3234d54a92e3409f4d6744150a4ca5c05`).
  Verified explicitly on the owner's request: the v6-delta block is **absent** from the
  current file (0 contiguous matches), present only in that snapshot.

Method: exact contiguous block matching of the whole snapshot against the current file,
plus a structural diff against the previous file version. No heuristic line sampling.
