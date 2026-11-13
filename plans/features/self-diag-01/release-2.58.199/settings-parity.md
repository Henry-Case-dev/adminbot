# Settings / prompt parity — 2.58.199

Deploy path: `git pull --ff-only` + `tools/release_manifest.py` + `systemctl
restart`. No DDL, no migration, no settings seeding/UPDATE path executed.

## PostgreSQL (read-only inventory after deploy)

| Table | Rows | SHA-256 (16) | max(updated_at) |
|---|---|---|---|
| `bot_settings` (settings + prompt overrides) | 547 | `8a4fed50adfc8908` | **2026-11-11 12:33:23Z** |
| `chat_profiles` (`chat_params`, gates) | 3 | `7daacc2d543876b1` | **2026-11-12 11:04:00Z** |
| `bot_roles` | 4 | `0bcbd0d6f56e07d3` | — |
| `bot_admins` | 3 | `7ad396e507e017ed` | — |
| `chat_admins` | 1 | `ff30a61c99b8c712` | — |

Deploy/manifest time: **2026-11-13 08:36:16Z**. Every `max(updated_at)` is
before the deploy, so the deploy wrote no user settings or prompt overrides.
A full pre-deploy PG hash was not captured; this boundary is stated honestly.
Hashes above are the baseline for the next comparison.

## SQLite (captured before and after in the same deploy run)

| Table | Before | After |
|---|---|---|
| `meme_initiative_attempt` | 27284 rows, `07e595fff82a71cb` | identical |
| `meme_initiative_reservation` | 64 rows, `f5a4892a03e5470e` | identical |

## Prompt registry

Prompt blocks are code-defined (`services/prompt_registry.py`); the bump only
changed `APP_VERSION`. `bot_settings` (prompt overrides) has no write after
deploy. No prompt body was read, printed or sent to any chat during smoke.

## Conclusion

Only the approved code/config delta (train + version pins) reached production.
Existing user/chat settings, prompt overrides, roles and admins were not
overwritten; factory defaults were not reseeded destructively.
