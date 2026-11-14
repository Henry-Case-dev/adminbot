# SMART-CORRECTIVE-01 / 2.58.202 — controlled production deploy

Дата: 2026-11-14 (UTC). Финальный прогон: **15:12:57–15:14:52Z**.
Сервер: `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`, user `adminbot`.

Кандидат: **`0beed63df8037002ccfaacef019b8ea948d957f6`**, ветка
`release/smart-corrective-01`, версия **2.58.202**; pre-bump `a476818d`.
Предыдущая production-версия: **`409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9` /
2.58.201** (rollback target). Gate `deploy-corrective-0beed63d.txt`:
`stage=deploy inventory=224 manual=232 scoped=384 errors=0`; plan gate
`errors=0`; integration review `baaae980…` Approved for controlled deployment.

Delta guard-only: `services/prompt_release_policy.py` (+90 строк), guard-tests,
docs, version bump. Factory prompt text/label не менялись. Live-харнессы в
этом прогоне **не запускались** — отдельный follow-up.

## 1. Pre-state

```
UTC                 2026-11-14T15:12:57Z
HEAD                409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9
BRANCH              release/smart-corrective-01
APP_VERSION         2.58.201
UNIT                active, MainPID 819657
ExecMainStart       2026-11-14 13:50:27 UTC
HEALTH_LOCAL        200 {"status":"ok","version":"2.58.201"}
HEALTH_PUBLIC       200 {"status":"ok","version":"2.58.201"}
TRACKED_DIRTY       0; untracked только .cache/
DISK                /dev/vda1 103083636 71261276 26563408 73% /
DB_BYTES            3135078400
BACKUPS_BYTES       33494920885
JOURNAL_USER_RC     0
manifest            409f4e8a / 2.58.201 / previous 0e4a144d / 2.58.200
```

## 2. Fetch / switch

```
git fetch --prune origin release/smart-corrective-01   rc=0
FETCH_HEAD = 0beed63df8037002ccfaacef019b8ea948d957f6
git switch release/smart-corrective-01; git merge --ff-only FETCH_HEAD  rc=0
HEAD        = 0beed63df8037002ccfaacef019b8ea948d957f6
BRANCH      = release/smart-corrective-01
APP_VERSION = 2.58.202
tracked dirty = 0
```

## 3. Backup

```
path        /var/www/admin_bot/backups/pre_deploy_258202_20261114T151257Z.db
size        2 970 902 528 B (2.77 GiB)
integrity   ok
user_version 47
tables      130
```

Новый backup создан через проектную процедуру `VACUUM INTO` по живой
SQLite-БД; integrity/read-back проверены. `backups/` до деплоя уже занимал
33 494 920 885 B (pre-existing, не чистился).

## 4. Manifest (до рестарта)

```json
{"deployed_at":"2026-11-14T15:14:42.974638Z",
 "deployed_sha":"0beed63df8037002ccfaacef019b8ea948d957f6",
 "version":"2.58.202",
 "effect":"deploy",
 "previous_sha":"409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9",
 "previous_version":"2.58.201",
 "release_branch":"release/smart-corrective-01",
 "dirty_tracked":false,
 "schema":1}
```

`tools/release_manifest.py` rc=0; chown `adminbot:adminbot`, chmod 644;
читается сервисным пользователем.

## 5. Restart / health

```
systemctl restart admin_bot   rc=0
health local                 200 {"status":"ok","version":"2.58.202"} (4-й poll)
health public                200 {"status":"ok","version":"2.58.202"} (1-й poll)
unit                         active, MainPID 837957
ExecMainStart                2026-11-14 15:14:44 UTC
```

## 6. Post checks

```
HEAD 0beed63df8037002ccfaacef019b8ea948d957f6
BRANCH release/smart-corrective-01
APP_VERSION 2.58.202
tracked dirty 0
schema user_version 47; pending []; schema_migrations rows 36, max 47; tables 130
identity code verified_deployed; deployed_sha=checkout_sha=0beed63d;
process_started_at 2026-11-14T15:14:44Z; deployed_at 15:14:42.974638Z;
version_provenance runtime=manifest=2.58.202, consistent=true; dirty=false
journal as adminbot: rc=0; 161 строка; tracebacks=0; ERROR=0; CRITICAL=0;
WARNING=1
verify.json: ok=true, failed=[]
```

Единственный WARNING — существующий `services.summary_memory` FTS-only
(`embedding generation not serviceable | index=smart_archive | superseded |
build pending — source empty`); traceback/ERROR нет.

`DISK` после: `/dev/vda1 103083636 74153984 23670700 76% /` (свободно
23 670 700 KB ≈ 22.6 GiB).

## 7. Effective config

- `budgets_enabled=false` глобально и во всех 3 чатах.
- MCA caps: `max_total_calls=0`, `max_metered_calls=0`, `max_same_call=0`,
  `fuse_seconds=0.0`; скрытого enforcement нет.
- Capacity: primary `z-ai/glm-5.3-flash-uncensored` — **1 048 576 / 32 768**,
  `source=provider_catalog`, `confidence=verified`; fallback `deepseek-flash`
  131 072; legacy 1 000 000 `unknown_fallback` (не выдан за verified).
- Schema: 47, pending `[]`, `schema_migrations` 36/47, таблиц 130.

## 8. Settings preservation (guard-aware)

`bot_settings`: **548** строк, digest
`64243e1e0c90355f2da4fb73e3c6f1a1ce5d38a1781222c4a66bc2e4a44c8bae` —
pre/post deploy одинаковый. Защищённые значения не переписаны:

```
flags.budgets_enabled=false                 updated 2026-10-25
flags.factcheck_pipeline_v2=true            updated 2026-10-20
models.llm_model_name=z-ai/glm-5.3-flash-uncensored  updated 2026-11-11
models.llm_base_url=https://nano-gpt.com/api/v1      updated 2026-09-12
prompts.checkup_system_prompt  3 030 chars  sha256 b0c70f974e0e...  unchanged
prompts.factcheck_subject_system_prompt  2 146 chars  sha256 7df7e8752798...  unchanged
```

`chat_profiles`: 3 строки; deploy pre/post digest
`6bddf0617e2f41f1c71c1816eb0512d89353d3195003289b63d6ce157671a14c` — без
изменений. Verifier проверял **prompt_revisions**, а не неизменность
chat-override: manual-ревизия `rev:d31300ef35a0` (12 469 симв.,
sha256 `31d17506…`, `retired=false`) сохранена; factory
`rev:9ed7b22b0d8c` (3 462 симв., sha256 `3140bb36…`) тоже сохранена.

## 9. Reactivation owner checkup revision

После успешного deploy выполнена data-only реактивация сохранённой
manual-ревизии через официальный `prompt_release_policy.activate_revision`
(транзакция + apply-lock; без ручных SQL-записей тела, без удаления/клона,
без изменения factory-ревизии). Подробности — в `prompt-reactivation.md`.

Кратко:

```
chat alias              CHAT_C2
active before           rev:9ed7b22b0d8c (factory, activation 2941)
first activation        rev:d31300ef35a0, kind=manual_rollback,
                        outcome=applied, activation_id=2942
second activation       outcome=skipped_same, applied=false,
                        event id 2943; active revision stayed manual
final active revision   rev:d31300ef35a0 (manual)
manual bytes            12 469 chars, sha256 31d17506… (unchanged)
factory bytes           3 462 chars, sha256 3140bb36… (unchanged)
global prompt           3 030 chars, sha256 b0c70f97… (unchanged)
chat override           present, 12 469 chars, sha256 31d17506…
notification            official pg_notify(chat_params_updated); no Telegram
```

Второй вызов — идемпотентный no-op по телу/указателю active revision
(`skipped_same`), но официальный сервис записывает событие 2943; второго
`applied`-события и повторной записи тела нет. Это ожидаемая семантика
`activate_revision`, а не двойная активация.

## 10. Rollback

Target: **409f4e8a / 2.58.201**, code-only; schema 47, данные не откатываются.
Финальный deploy rollback не требовал (`rollback-result.txt`: not_executed).
Точные команды — в `rollback.md`. Важно: откат кода не отменяет data-only
реактивацию manual-ревизии; prompt journal/chat override остаются.

## 11. Границы / аномалии

- Live-харнессы не запускались; отдельный follow-up.
- Карты требований и `plans/progress_scope.json` не менялись.
- `backups/` pre-existing 33.5 GB; cleanup не выполнялся.
- Единственный WARNING журнала — `summary_memory` FTS-only; не traceback/ERROR.
- Первый verifier 2.58.201 (прошлый релиз) ошибочно считал EVOL-016 cutover
  потерей; в 2.58.202 проверка исправлена на prompt_revisions/manual presence.
  В этом прогоне false rollback не было.
