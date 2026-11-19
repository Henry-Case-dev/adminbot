# VMQ-MEM-07 - independent Reviewer harness (reissue)

Read-only evidence tooling for the Reviewer-owned five-class comparison on the
real archive of chat `-1002661910336` (about 2.07M messages, 2022-2026).
Candidate: `0fce97a14338521a24d94f560e896ebcb19f9492` (production 2.58.219,
schema 48).

This directory does not change `services/`, `handlers/`, `web/`, `config/`,
product tests, maps or statuses. It does not claim VERIFIED and does not replace
the Reviewer verdict.

## Files

- `design.md` - Stage A design plus Stage C reissue corrections.
- `harness/mem07.py` - the harness.
- `harness/make_fixture.py` - synthetic SQLite fixture.
- `harness/measure_effective_config.py` - read-only settings/PG hot-config probe.
- `harness/test_mem07_smoke.py` - pytest smoke tests.
- `fixture/` - committed synthetic output; never production evidence.
- `mem07-analysis.md` - run-0 analysis (run-0 is invalid; kept for history).
- `run-0fce97a14/` - run-0 artifacts (invalid for acceptance; privacy redacted).

## Exact DevOps command (preferred: production env, no --effective-config)

The harness must record the actual production effective values. Do not write a
hand-made `{"graph_rag_enabled": true, "graph_rag_facts_limit": 10}` file.

Prepare a worktree that contains this branch and the product tree at
`0fce97a14`, then run it with the production environment and venv:

```bash
# once, on the production host
git -C /var/www/admin_bot worktree add /tmp/vmq-mem07-reissue vmq/mem07-independent

cd /tmp/vmq-mem07-reissue
# Load the production env into the process (do not print it):
set -a; . /var/www/admin_bot/.env; set +a

/var/www/admin_bot/.venv/bin/python   plans/features/vmq-onto-01/evidence/mem07/harness/mem07.py   --db /tmp/mem07-snapshot-fresh.db   --chat-id -1002661910336   --out plans/features/vmq-onto-01/evidence/mem07/run-0fce97a14-reissue   --code-root .
```

The harness then:

- imports the real `config.settings.settings` instance and records
  `settings_instance`;
- runs a **SELECT-only** query against `bot_settings` for
  `flags.graph_rag_enabled` and `limits.graph_rag_facts_limit` when
  `POSTGRES_DSN` is present, and records `db_hot_config`, per-key `sources`,
  `pg_status` and `hot_config_measured`;
- computes `effective` from DB hot values where present, otherwise from the
  settings instance;
- records the measurement command, tool sha256, a provenance sha256 and the
  exact source per key.

If the measured effective value is false/0, the harness stops with
`not_executed: graph_rag_disabled`. It does not override to true. If the PG query
fails (as opposed to `POSTGRES_DSN` being absent), the provenance is not
production-ready and the harness stops with
`not_executed: effective_config_provenance_production_not_ready`.

Working directory matters: `config.settings` loads `.env` from the process cwd
(unless `ADMINBOT_SKIP_DOTENV=1`). Run from the prepared worktree with the
production env loaded, or use the measured-file path below.

### Alternative: measured file from a temp worktree

If the harness must run from a worktree without the production env, generate the
provenance file from the production environment first:

```bash
cd /tmp/vmq-mem07-reissue
set -a; . /var/www/admin_bot/.env; set +a
/var/www/admin_bot/.venv/bin/python   plans/features/vmq-onto-01/evidence/mem07/harness/measure_effective_config.py   --out /tmp/mem07-effective.json
sha256sum /tmp/mem07-effective.json
```

Then run the harness with `--effective-config /tmp/mem07-effective.json`.
The file is accepted only if it was produced by `measure_effective_config.py`
(schema, tool sha256, read-only flag, command, settings instance, DB hot values,
sources, effective values). The harness records the file sha256 and provenance.
A hand-written file is rejected with
`not_executed: effective_config_provenance_*`. `--settings-only` files are for
fixture tests only and are rejected for a real run.

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
recommended for a full copy) before creating it. Do not copy a live DB file with
`cp`; use the SQLite backup API from a `mode=ro` source.

The harness re-checks `quick_check`, `user_version`, table counts and the
before/after sha256. It refuses to run on a non-`ok` snapshot, a schema other
than 48, a product tree that differs from the candidate, or an effective
GraphRAG config that is false/zero.

## Outputs

Under `--out`:

- `mem07-independent.json` - compact ids/counts/years/timestamps/hashes,
  questions, config, diagnostics, policies, exact + semantic metrics, parity,
  Old_Episode probes, builder comparison, controls, assertions;
- `mem07-independent-summary.md` - command, candidate/snapshot, question table,
  class metrics, parity, controls, Old_Episode, builder table, assertions;
- `mem07-independent-hashes.txt` - snapshot before/after, harness files and
  output hashes.

No message/fact text and no personal display names are written. Participants are
`@P1`/`@P2`; only `user_id_sha256`/`name_sha256`, years and counts are recorded.
`MEM07-PRIVACY` fails if a known display name appears anywhere in the output.

## Key assertions

- `MEM07-CONFIG` - actual settings instance/effective config: GraphRAG true,
  limit > 0, unified path for every matrix question.
- `MEM07-TRACE` - `_rag_unified_rows` returned non-None and period policy is
  present; no legacy fallback.
- `MEM07-DIAGNOSTICS` - bounded histogram and `log_sha256`; no unexpected
  errors/tracebacks.
- `MEM07-PRIVACY` - no personal display-name values.
- `MEM07-METRICS` - exact coverage/chrono plus `semantic.old_coverage` and
  `chrono_period` with explicit denominators.
- `MEM07-OLDEP-2023/2024` - explicit-year Old_Episode non-empty, spans and
  resolved source refs, no year leak.
- `MEM07-CONTROLS` - N1/N2 historical negative has old rows and labels; X1
  historical delivers old+new facts and labels the old one.
- `MEM07-BUILDER-DIFF` - numeric Builder discrepancy table with sources.

## Exit codes

- `0` - structural assertions pass;
- `1` - an assertion failed;
- `2` - not executed (missing/invalid snapshot, GraphRAG disabled, empty
  reference, unresolved slot);
- `3` - read-only violation (snapshot hash changed);
- `4` - technical failure.

Product quality is reported in metrics; it is not turned into a harness pass/fail.
The Reviewer evaluates it separately.

## Local smoke test (synthetic only)

```powershell
& C:\Code\Python\adminbot\.venv\Scripts\python.exe -m pytest -q `
  plans\features\vmq-onto-01\evidence\mem07\harness\test_mem07_smoke.py
```

The smoke test builds a synthetic fixture in a temp directory and checks config
assertion/gate, unified path, privacy scan, diagnostics histogram, semantic
metrics, Old_Episode 2023/2024, non-trivial controls, builder table, no-text/no-secret,
read-only hash and missing-snapshot `not_executed`. It never uses production data.

## Honest limitations

- Snapshot, not the live process; no Telegram turn.
- LLM/embedding are failing stubs; no generated answer text.
- Vector leg is `compat_not_proven`/`embed_unavailable` when the embed stub fails;
  the run measures the lexical/structural path and records it.
- Product block builders (`_build_rag_block`, `_build_old_episodes`) and the
  canonical `build_messages` are used; the full L1 composer, system prompt and
  plan context are out of scope.
- Fabricated-link metric covers payload/bundle refs, not prose claims.
- TIME-07 remains within-candidate A/B (`auto` vs `auto_plan`); no 2.58.179
  baseline is re-measured by this harness.
- One chat, one run per configuration; no statistical generalization.