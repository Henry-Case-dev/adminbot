# VMQ-MEM-07 - independent Reviewer harness

Read-only evidence tooling for the Reviewer-owned five-class comparison on the
real archive of chat `-1002661910336` (about 2.07M messages, 2022-2026).
Candidate: `0fce97a14338521a24d94f560e896ebcb19f9492` (production 2.58.219,
schema 48).

This directory does not change `services/`, `handlers/`, `web/`, `config/`,
product tests, maps or statuses. It does not claim VERIFIED and does not
replace the Reviewer verdict.

## Files

- `design.md` - Stage A: own questions, reference protocol, metrics,
  current-state negative, counterexample, acceptance mapping.
- `harness/mem07.py` - the harness.
- `harness/make_fixture.py` - synthetic SQLite fixture.
- `harness/test_mem07_smoke.py` - pytest smoke tests.
- `fixture/` - committed synthetic output (`fixture.json`, summary, hashes);
  never production evidence.

## Exact DevOps command (real snapshot)

Run from the worktree that contains this harness (branch
`vmq/mem07-independent`, product tree equal to candidate `0fce97a14`):

```powershell
& C:\Code\Python\adminbot\.venv\Scripts\python.exe `
  plans\features\vmq-onto-01\evidence\mem07\harness\mem07.py `
  --db C:\Temp\mem07-snapshot.db `
  --chat-id -1002661910336 `
  --out plans\features\vmq-onto-01\evidence\mem07\run-0fce97a14 `
  --code-root .
```

```bash
# POSIX, same .venv (Python 3.12 + sqlite-vec)
.venv/bin/python \
  plans/features/vmq-onto-01/evidence/mem07/harness/mem07.py \
  --db /tmp/mem07-snapshot.db \
  --chat-id -1002661910336 \
  --out plans/features/vmq-onto-01/evidence/mem07/run-0fce97a14 \
  --code-root .
```

Optional: `--builder-matrix <path>` records the Builder matrix path as context
only; it is never used as proof. `--dry-run` prints the resolved configuration.
`--no-network-block` exists only for diagnostics; leave it off.

The harness does not delete the snapshot. DevOps deletes the snapshot, its
`-wal`/`-shm` and helpers after the run, per the production hygiene rule.

## Snapshot recipe (DevOps, read-only)

```python
import sqlite3
src = sqlite3.connect("file:<live.db>?mode=ro", uri=True)
dst = sqlite3.connect("<snapshot.db>")   # must not exist / must be empty
with dst:
    src.backup(dst)
print(dst.execute("PRAGMA quick_check").fetchone()[0])
print(dst.execute("PRAGMA user_version").fetchone()[0])
dst.close(); src.close()
```

Then compute sha256 of `<snapshot.db>`. Check free space (at least 6 GiB is
recommended for a full copy) before creating it. Do not copy a live DB file
with `cp`; use the SQLite backup API from a `mode=ro` source.

The harness re-checks `quick_check`, `user_version`, table counts and the
before/after sha256. It refuses to run on a non-`ok` snapshot, a schema other
than 48, or a product tree that differs from the candidate.

## Outputs

Under `--out`:

- `mem07-independent.json` - compact ids/counts/years/timestamps/hashes,
  questions, policies, four metrics with `num/den/value`, parity, controls,
  assertions;
- `mem07-independent-summary.md` - command, candidate/snapshot, question table,
  class metrics, parity, controls, TIME-07 A/B, assertions, limitations;
- `mem07-independent-hashes.txt` - snapshot before/after, harness files and
  output hashes.

No message/fact text and no personal display names are written. Participants
are `@P1`/`@P2`; only `user_id_sha256`/`name_sha256` and years are recorded.

## Exit codes

- `0` - structural assertions pass;
- `1` - a structural assertion failed;
- `2` - not executed (missing/invalid snapshot, empty reference, unresolved slot);
- `3` - read-only violation (snapshot hash changed);
- `4` - technical failure.

Product quality (coverage/relevance/parity) is reported in the metrics and is
NOT turned into a harness pass/fail; the Reviewer evaluates it separately.

## Local smoke test (synthetic only)

```powershell
& C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest -q `
  plans\features\vmq-onto-01\evidence\mem07\harness\test_mem07_smoke.py
```

The test builds a synthetic fixture in a temp directory, checks the structural
assertions, the four metrics with denominators, current-state negatives, the
changed-position counterexample, the no-text/no-secret guarantee, the
read-only hash and the missing-snapshot `not_executed` path. It never uses
production data.

## Honest limitations

- Snapshot, not the live process; no Telegram turn.
- LLM/embedding are failing stubs; no generated answer text.
- Vector leg is `compat_not_proven` when the embed stub fails; the run measures
  the lexical/structural path and records `vector_leg`.
- Product block builders (`_build_rag_block`, `_build_old_episodes`) and the
  canonical `build_messages` are used; the full L1 composer, system prompt and
  plan context are out of scope.
- Fabricated-link metric covers payload/bundle refs, not prose claims.
- TIME-07 is within-candidate A/B (`auto` vs `auto_plan`), not a cross-release
  baseline; the 2.58.179 baseline is not re-measured here.
- One chat, one run per configuration; no statistical generalization.