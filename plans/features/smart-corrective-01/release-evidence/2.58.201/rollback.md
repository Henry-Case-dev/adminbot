# Rollback — SMART-CORRECTIVE-01 / 2.58.201

## Target

- Code: **`0e4a144db476a1535ae3a2b79a7cce30354ad866`** (release/2.58.200)
- Version: **2.58.200**
- Schema: **47** (code-only rollback; schema and data are not rolled back)
- Previous manifest: `deployed_sha=0e4a144d…`, `version=2.58.200`,
  `previous_sha=d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199)

## Exact commands (prepared; not executed for the final successful deploy)

```bash
cd /var/www/admin_bot

# 1) code back to the exact previous release
git switch release/2.58.200
# if the branch is unavailable:
# git switch --detach 0e4a144db476a1535ae3a2b79a7cce30354ad866

# 2) honest rollback manifest (version from checkout, previous=409f4e8a)
venv/bin/python tools/release_manifest.py --effect rollback
chown adminbot:adminbot .deploy/release.json
chmod 644 .deploy/release.json

# 3) restart and health
systemctl restart admin_bot
# poll until 200:
curl -fsS http://127.0.0.1:8000/healthz
# expected: {"status":"ok","version":"2.58.200"}
```

Первый rollback (13:42:32–13:42:38Z) выполнялся эквивалентно, но с
восстановлением точного pre-deploy manifest:

```bash
git switch release/2.58.200
cp <pre-deploy-manifest> .deploy/release.json
chown adminbot:adminbot .deploy/release.json
chmod 644 .deploy/release.json
systemctl restart admin_bot
```

## First rollback result (actually executed)

```text
started_utc   2026-11-14T13:42:32Z
switch_rc     0
restart_rc    0
head          0e4a144db476a1535ae3a2b79a7cce30354ad866
branch        release/2.58.200
health        200 {"status":"ok","version":"2.58.200"}
finished_utc  2026-11-14T13:42:38Z
```

Причина: первый verifier посчитал EVOL-016 cutover (снятие активного
chat-override и активацию factory-ревизии) нарушением preservation. Это была
ошибка verifier; manual-ревизия `rev:d31300ef35a0` (12 469 симв.,
`retired=false`) сохранилась. После исправления проверки (prompt_revisions +
manual revision present/not retired) повторный deploy 2.58.201 прошёл.

## Final deploy rollback state

```text
status        not_executed
reason        deployment_checks_passed
recorded_utc  2026-11-14T13:50:32Z
```

Все mandatory post-checks и `verify.json` (`ok=true`, `failed=[]`) прошли:
HEAD `409f4e8a`, branch `release/smart-corrective-01`, health 200 `2.58.201`,
schema 47/pending `[]`, budgets OFF, caps 0, capacity 1 048 576/32 768
provider_catalog verified, identity `verified_deployed`, journal 0
traceback/ERROR, owner settings digest unchanged, manual checkup revision
preserved/not retired.

## Data / prompt journal note

Rollback is **code-only**. PostgreSQL `prompt_revisions`/`prompt_activations`
and chat settings are not rolled back. After the first code rollback the
EVOL-016 cutover remained in the DB; the final 2.58.201 deployment made the
code and data consistent again. The owner’s saved manual checkup edition
remains in `prompt_revisions` as `rev:d31300ef35a0` (12 469 chars,
sha256 `31d1750654615bf4e69e861ae66f393b31546b34982c7d5613052b67133b3701`,
`retired=false`); the active factory revision is `rev:9ed7b22b0d8c` by owner
decision EVOL-012 (29.10.2026). A future code-only rollback does not delete
this journal history.
