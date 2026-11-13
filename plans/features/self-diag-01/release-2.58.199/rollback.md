# Rollback readiness — 2.58.199

## State

- Deployed: `d20a7f730715ba9e9cba7673c0557794979be339` (2.58.199),
  branch `release/2.58.199`.
- Immediate pre-state: `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198),
  branch `release/2.58.198`.
- Documented rollback target: `25876167` (2.58.197), code-only; schema 47;
  data is not rolled back.
- Data backup retained on the server:
  `backups/pre_deploy_258199_20261113T083507Z.db`
  (`user_version=47`, `integrity_check=ok`, 2,632,986,624 bytes,
  sha256 `6c1a7fac1c984c6b0f00478a9501a5f63ea76caebe7c1255d906aa84afce246b`).
- No rollback was executed; all mandatory live checks passed.

## Fast code revert (previous production)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git switch release/2.58.198        # 23477658, 2.58.198
git pull --ff-only origin release/2.58.198
venv/bin/python tools/release_manifest.py --effect rollback
systemctl restart admin_bot
curl -fsS https://admin-bot.duckdns.org/healthz
```

(Manifest producer records `previous_sha/previous_version` from the current
manifest.)

## Documented rollback target 2.58.197

If 2.58.198 also has to be skipped:

```bash
cd /var/www/admin_bot
git switch release/2.58.198 2>/dev/null || true
git fetch --prune origin 25876167
git checkout 25876167
venv/bin/python tools/release_manifest.py --effect rollback
systemctl restart admin_bot
curl -fsS https://admin-bot.duckdns.org/healthz
```

No schema change or data migration is involved (v47, DDL=0). The pre-deploy
SQLite backup is available if data-level recovery is ever required; it is not
part of a normal code rollback.

## Post-rollback checks

`/healthz` 200 with the target version; unit active; schema 47; journal has no
new traceback; identity record effect `rollback` with `previous_sha` pointing
to `d20a7f73`.
