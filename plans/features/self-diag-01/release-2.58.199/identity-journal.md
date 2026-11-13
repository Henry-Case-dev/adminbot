# Identity and journal — 2.58.199

## Deploy identity (authoritative `collect_identity`, running pid 454989)

```json
{
  "checkout_sha": "d20a7f730715ba9e9cba7673c0557794979be339",
  "code": "verified_deployed",
  "conflict": [],
  "deployed_at": "2026-11-13T08:36:16.759775Z",
  "deployed_sha": "d20a7f730715ba9e9cba7673c0557794979be339",
  "dirty": false,
  "local_source_verification": "verified_deployed",
  "process_started_at": "2026-11-13T08:36:17.830000Z",
  "reason": "",
  "sources": ["release_manifest", "git_head", "git_cli",
              "runtime_app_version", "process_start"],
  "version_provenance": {
    "consistent": true,
    "manifest": "2.58.199",
    "runtime": "2.58.199"
  }
}
```

`deployed_sha == checkout_sha == release SHA`; process start is after manifest
write (08:36:17.830Z > 08:36:16.759775Z). No mismatch/dirty/version conflict.

The API snapshot exposes `runtime.deployed_sha` and `runtime.checkout_sha`
(both `d20a7f73`) and `runtime.app_version=2.58.199`. The `deploy.identity`
entry in the API `sources` list is `not_checked` because that list reports the
last observed `inspect_runtime_called` event, not an execution of the probe;
the authoritative identity record above is the direct collector result.

## Journal

- `sudo -u adminbot journalctl -u admin_bot -n 50 --no-pager` → **rc=0**
  (service user `adminbot`), current invocation pid 454989, started
  08:36:18 UTC.
- After restart: `Traceback` 0, `attempt LOST` 0 in 15 minutes.
- Before restart (prior hour): 1 `Traceback` (pre-existing history), 0 `attempt
  LOST`.
- Startup shows the existing workers/schedulers and `Bot started, listening for
  messages...`; no restart traceback, no migration/prompt-migration failure.
- Full sanitized excerpt: `final-run.txt` (chat IDs redacted), plus
  `main-run.txt` and `control-run.txt`.
