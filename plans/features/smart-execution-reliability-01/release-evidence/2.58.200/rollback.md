# Rollback readiness — 2.58.200

## State

- Deployed: `0e4a144db476a1535ae3a2b79a7cce30354ad866` (2.58.200),
  branch `release/2.58.200`; manifest `effect=deploy`,
  `previous_sha=d20a7f730715ba9e9cba7673c0557794979be339`,
  `previous_version=2.58.199`.
- Rollback target: `d20a7f73` (2.58.199) on `release/2.58.199` — the exact
  pre-deploy production commit; code-only, schema stays 47, data is not rolled back.
- Pre-deploy data copy retained on the server:
  `backups/pre_deploy_258200_20261114T051849Z.db` (3,015,938,048 bytes,
  `user_version=47` before copy). Data-level recovery only if ever required;
  not part of a normal code rollback.
- No rollback was executed; all immediate post-deploy checks passed.

## Fast code revert (previous production, ~1 session)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git switch release/2.58.199        # d20a7f73, 2.58.199
git merge --ff-only origin/release/2.58.199
venv/bin/python tools/release_manifest.py --effect rollback
systemctl restart admin_bot
curl -fsS https://admin-bot.duckdns.org/healthz   # expect version 2.58.199
```

The manifest producer records `previous_sha/previous_version` from the current
manifest, so the rollback is traceable (`previous_sha=0e4a144d…`).

## Post-rollback checks

`/healthz` 200 with `2.58.199`; unit active; `user_version=47`;
`sudo -u adminbot journalctl -u admin_bot` readable; no new traceback;
`.deploy/release.json` `effect=rollback`.

## Notes

- 2.58.200 introduces no flag that must be switched off for a code rollback:
  the reverted code simply ignores the new factory prompt row
  (`prompts.factcheck_subject_system_prompt`), which is harmless and reused if
  the release is re-applied. Owner settings are never reset by the rollback.
- Deploy-fail2ban discipline used: 1 short recon session + 1 main session +
  2 short read-only checks, single connections, no retries.
