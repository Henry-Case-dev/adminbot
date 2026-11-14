# Rollback — SMART-CORRECTIVE-01 / 2.58.202

## Target

- Code: **`409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9`** (2.58.201)
- Version: **2.58.201**
- Schema: **47** (code-only rollback; schema and data are not rolled back)
- Previous manifest before deploy: `409f4e8a / 2.58.201`,
  `previous_sha=0e4a144d…` / 2.58.200

## Exact commands (not executed; final deploy passed)

```bash
cd /var/www/admin_bot

# 1) code back to the exact previous release
git switch --detach 409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9
# optional: create/switch a dedicated branch at this SHA instead of detached HEAD

# 2) honest rollback manifest (version 2.58.201, previous=0beed63d)
venv/bin/python tools/release_manifest.py --effect rollback
chown adminbot:adminbot .deploy/release.json
chmod 644 .deploy/release.json

# 3) restart and health
systemctl restart admin_bot
# poll until 200:
curl -fsS http://127.0.0.1:8000/healthz
# expected: {"status":"ok","version":"2.58.201"}
```

## Final deploy rollback state

```text
status        not_executed
reason        deployment_checks_passed
recorded_utc  2026-11-14T15:14:53Z
```

`verify.json` — `ok=true`, `failed=[]`; deploy health 200 `2.58.202`, schema
47/pending `[]`, budgets OFF, caps 0, capacity 1 048 576/32 768
provider_catalog verified, identity `verified_deployed`, journal 0
traceback/ERROR, settings digest unchanged, manual checkup revision preserved.

## Data / prompt journal note

Rollback is **code-only**: PostgreSQL `prompt_revisions`/`prompt_activations`
and chat settings are not rolled back. The data-only reactivation of
`rev:d31300ef35a0` (manual owner checkup edition) remains active after a code
rollback; the official journal records:
- activation 2942 — `manual_rollback`, `applied`;
- activation 2943 — `manual_rollback`, `skipped_same` (second idempotent call).
The manual revision bytes (12 469 chars, sha256 `31d17506…`) and the global
prompt (3 030 chars, sha256 `b0c70f97…`) are unchanged. A code rollback does
not delete this history or the chat override. If a data rollback is ever
required, it must be a separate authorized operation using the prompt history
service, not a manual SQL body rewrite.
