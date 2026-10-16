# SOUL-1 — Source Snapshot Manifest

| Field | Value |
|---|---|
| Feature | `soul-1` (epic SOUL-01 … SOUL-19) |
| Authoritative source (agent-immutable copy) | `plans/features/soul-1/source-current-task.md` |
| Live user-owned original | `plans/current_task.md` (git-ignored, agents must never write it) |
| SHA256 | `8C42DDFABCE635FE4E1F24F9522FF8642F3BD3049FAC05C77CA162687051196B` |
| Bytes | 103476 |
| Snapshot taken | 2026-10-16 |
| Task origin | root user prompt («прочитай current_task.md и приступай к выполнению») |

Purpose: freeze the exact SOUL-1 requirement text so that requirement-map entries,
review findings and release evidence can be bound to one immutable, hash-verified
source version. Any later owner amendment of `plans/current_task.md` must be
re-snapshotted deliberately (new SHA, map revised, coverage re-confirmed) — never
silently ignored.

Note: the epic text has been amended by the owner — see the amendment section below.

## Amendment (owner's mandatory architectural clarification) — 2026-10-16

| Field | Value |
|---|---|
| Added to `plans/current_task.md` | section `# SOUL-1 — Обязательное архитектурное уточнение: Personality Core, управляемые промпты и реальные возможности бота`, lines 761–899 |
| Agent-immutable copy | `plans/features/soul-1/source-architectural-clarification.md` |
| SHA256 | `338fd9c6bd323a7ea8ad80577c2e9d8b45a714d30bdd4fc9147af75931a4a35c` |
| Bytes / lines | 31378 / 139 |
| Whole owner file after the addition | SHA256 `A256B865C2EF7F734B1FFAA1E3AD37D2CC5DDC6B1A8ED5CE2CB5DEBDF54CA18A`, 899 lines, 245638 bytes |

Why a second snapshot instead of extending the first: the original map binds its items to
line numbers/hashes of the first snapshot (`source-current-task.md`, SHA 8C42DDFA…).
Rewriting that file would invalidate every `source_id`; instead the amendment gets its own
source + coverage map (`requirements-map-amendment.json`) and both maps are gated at release.

Owner-stated precedence: the clarification **overrides conflicting older wording**,
explicitly including SOUL-03/SOUL-04 passages about preserving legacy speech customs.
Concrete policy change: old speech canons and legacy speech custom prompts must NOT remain an
active layer in runtime; they are removed with a plain emergency backup first, and no special
UI migration is built for them. Core becomes mandatory for all author-voice public texts
(Direct, Initiative, public Factcheck, public Summary, dreams/sleep/nostalgia/lore/stories,
tool answers, public failure messages) and prohibited for machine stages.
