# VMQ-MEM-06 G2 read-only harness (candidate `0fce97a14`)

Evidence tooling for `plans/features/vmq-onto-01/evidence/acceptance-closeout-2026-11-19/architect-mem06-decision.md` §5.
It is **not** product code and does not change `services/`, `handlers/`, `web/` or `config/`.

## What it reuses

* `plans/features/vmq-onto-01/evidence/vmq-mem/harness-slice-d-2026-11-15/measure.py`
  (method-level A1/A1P/D/T2/T3, Old_Episode, people probes);
* the real product seams:
  `DirectChatService._rag_unified_rows`, `_build_rag_block`,
  `_build_old_episodes`, `_build_evidence_bundle`,
  `mca_retrieval_context.retrieve`, `DatabaseService.lore_*`,
  `LoreCompilerService._graph_facts` / `_dialog_pairs`;
* G2-only additions: Lore material probe (no `llm.generate`),
  `MEM06-THEMATIC` (`mode="thematic"`), G1 hints-not-in-payload,
  G4 episode-refs/source-id, chat-scope.

No second retrieval/store/pipeline is created. LLM and embedding clients are
failing stubs; the snapshot is opened with SQLite `mode=ro`
(`DatabaseService.initialize_readonly`). The harness never writes to the
snapshot; it records sha256 before/after.

## Exact DevOps command (real snapshot)

```powershell
# Windows: run from the worktree that contains this harness
# (branch `vmq/g2-mem06`). Its product tree must equal candidate
# 0fce97a14; the harness checks `product_diff_clean` and records
# `code_root_head` (the harness commit, not the product candidate).
# Use the repository .venv (Python 3.12 + sqlite-vec); a bare `py`/`python`
# may resolve to another interpreter and then §5.1 is not met.
& C:\Code\Python\adminbot\.venv\Scripts\python.exe `
  plans\features\vmq-onto-01\evidence\vmq-mem\harness-deployed-0fce97a14\measure_g2.py `
  --db <snapshot.db> `
  --chat-id -1002661910336 `
  --out <evidence-output-dir> `
  --code-root <worktree-with-harness>
```

```bash
# POSIX, same .venv (Python 3.12 + sqlite-vec) and harness worktree
.venv/bin/python \
  plans/features/vmq-onto-01/evidence/vmq-mem/harness-deployed-0fce97a14/measure_g2.py \
  --db <snapshot.db> \
  --chat-id -1002661910336 \
  --out <evidence-output-dir> \
  --code-root <worktree-with-harness>
```

Optional: `--other-chat <id>` for the scope probe; by default the harness
discovers another chat from the snapshot. `--dry-run` prints resolved
configuration only. `--fixture` builds a synthetic SQLite fixture and runs on
it (never production evidence).

The snapshot itself is created by DevOps per §5.1 (`sqlite3.Connection.backup`
from a source opened `mode=ro`, then `PRAGMA quick_check`, `user_version`,
sha256). Do **not** copy a live DB file. Check free space (≥6 GiB) before the
copy. Delete the snapshot, its `-wal`/`-shm` and helpers after the run; the
harness does not delete the `--db` file.

Snapshot recipe (DevOps, not run by the harness):

```python
import sqlite3
src = sqlite3.connect("file:<live.db>?mode=ro", uri=True)
dst = sqlite3.connect("<snapshot.db>")          # must not exist / must be empty
with dst:
    src.backup(dst)
print(dst.execute("PRAGMA quick_check").fetchone()[0])
print(dst.execute("PRAGMA user_version").fetchone()[0])
dst.close(); src.close()
```

Then record `sha256` of `<snapshot.db>`. The harness re-checks `quick_check`,
`user_version`, table counts and the before/after sha256 and refuses to run on
a non-`ok` snapshot (publishes `not_executed`).

The harness records `python_version`, `sqlite_vec_version`,
`sqlite_vec_loaded`, `sqlite_vec_off_reason`, `vec_ok` and the effective
`MCA_*` gates. In the contract environment Python is 3.12, the extension is
loaded, and the failing embed stub makes `sqlite_vec_off_reason=embed`
(expected); `off_reason=extension` means §5.1 is **not** met. The harness
loads sqlite-vec through the product `MemoryManager.initialize()`, disables
vector backfills, and opens the snapshot strictly `mode=ro`.

## Outputs

Under `--out`:

* `g2-mem06.json` — compact ids/counts/years/timestamps/hashes, all
  `MEM06-*` assertions;
* `g2-mem06-summary.md` — command, candidate/snapshot SHA, chat, topics,
  tables, per-assertion `pass|fail|not_executed`, limitations;
* `g2-mem06-hashes.txt` — snapshot/harness sha256.

No message/fact text is written; Lore topics are queries and are recorded as
required by §5.3.

Exit codes: `0` all pass; `1` any fail; `2` any not_executed; `3` read-only
violation; `4` technical failure.

## Local smoke test (synthetic only)

```powershell
& C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest -q `
  plans\features\vmq-onto-01\evidence\vmq-mem\harness-deployed-0fce97a14\test_g2_harness_smoke.py
```

The test builds a synthetic fixture in a temp directory, runs the harness
against it, validates the output schema/assertion ids/no-text guarantee, all
19 assertions (including the Writer record, Lore, P1-P3 and Old_Episode
paths), the Python/sqlite-vec environment record, and the `not_executed`
publication path for a missing snapshot. A separate unit check pins the
`MEM06-OLDP` tail/ref-skip explanation so a correct empty result is not
reported as a failure.

## Status

`VMQ-MEM-06` stays **PENDING** until the real G2 run is published and
independently reviewed. This harness does not merge, deploy or edit maps.
