# SMART-CORRECTIVE-01 / 2.58.201 — controlled production deploy

Дата: 2026-11-14 (UTC). Финальный прогон: **13:50:23–13:50:32Z**.
Сервер: `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`, user `adminbot`.

Кандидат: **`409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9`**, ветка
`release/smart-corrective-01`, версия **2.58.201**; pre-bump code `051ab76a`.
Предыдущая production-версия: **`0e4a144db476a1535ae3a2b79a7cce30354ad866` / 2.58.200**
(rollback target). Deploy gate: `deploy-corrective-409f4e8a-r2.txt` — `errors=0`;
parent gates SMART/FC — `errors=0`; integration review Approved for controlled
deployment of this exact SHA.

Live-харнессы в этом прогоне **не запускались** — отдельный follow-up.

## 1. Pre-state (финальный прогон)

```
UTC                 2026-11-14T13:50:23Z
HEAD                0e4a144db476a1535ae3a2b79a7cce30354ad866
BRANCH              release/2.58.200
APP_VERSION         2.58.200
UNIT                active, MainPID 817375
ExecMainStart       2026-11-14 13:42:34 UTC
HEALTH_LOCAL        200 {"status":"ok","version":"2.58.200"}
HEALTH_PUBLIC       200 {"status":"ok","version":"2.58.200"}
TRACKED_DIRTY       0
UNTRACKED           только .cache/
DISK                /dev/vda1 103083636 71219292 26605392 73% /
DB_BYTES            3123130368
BACKUPS_BYTES       33494920885
JOURNAL_USER_RC     0
manifest            0e4a144d / 2.58.200 / previous d20a7f73 / release/2.58.200
```

MainPID 817375 — это процесс после первого rollback (см. §8); сам deploy
выполнялся уже поверх этого состояния.

## 2. Fetch и switch

```
git fetch --prune origin release/smart-corrective-01   rc=0
FETCH_HEAD = 409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9
git switch release/smart-corrective-01                  rc=0
HEAD        = 409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9
BRANCH      = release/smart-corrective-01
APP_VERSION = 2.58.201
tracked dirty = 0
```

## 3. Backup

```
path        /var/www/admin_bot/backups/pre_deploy_258201_20261114T133538Z.db
size        2 959 437 824 B (2.76 GiB)
integrity   ok
user_version 47
tables      130
```

Создан через проектную процедуру `VACUUM INTO` по живой SQLite-БД, read-back
проверен `PRAGMA integrity_check`. Backup был получен в первой попытке и
переиспользован после rollback; повторного 3-ГБ копирования не делалось.
`backups/` до деплоя уже занимал 33 494 920 885 B (pre-existing, не чистился).

## 4. Manifest (до рестарта)

```json
{"deployed_at":"2026-11-14T13:50:26.020167Z",
 "deployed_sha":"409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9",
 "version":"2.58.201",
 "effect":"deploy",
 "previous_sha":"0e4a144db476a1535ae3a2b79a7cce30354ad866",
 "previous_version":"2.58.200",
 "release_branch":"release/smart-corrective-01",
 "dirty_tracked":false,
 "schema":1}
```

`tools/release_manifest.py` rc=0; файл chown `adminbot:adminbot`, chmod 644;
читается сервисным пользователем. Все поля сверены с кандидатом.

## 5. Restart и health

```
systemctl restart admin_bot   rc=0
health local                 200 {"status":"ok","version":"2.58.201"} (3-й poll)
health public                200 {"status":"ok","version":"2.58.201"} (1-й poll)
unit                         active, MainPID 819657
ExecMainStart                2026-11-14 13:50:27 UTC
```

Рестарт один; PID сменился с 817375 на 819657. Health 200 на локальном и
публичном `/healthz`, версия 2.58.201.

## 6. Post checks

```
HEAD 409f4e8ae31c9c8fa65ef34bf7c4c3a43c86b8e9
BRANCH release/smart-corrective-01
APP_VERSION 2.58.201
tracked dirty 0
manifest 409f4e8a / 2.58.201 / previous 0e4a144d / 2.58.200 / release_branch
schema user_version 47; pending []; schema_migrations rows 36, max_version 47;
tables 130
identity code verified_deployed; deployed_sha=checkout_sha=409f4e8a;
process_started_at 2026-11-14T13:50:27Z; deployed_at 13:50:26.020167Z;
version_provenance runtime=manifest=2.58.201, consistent=true; dirty=false
journal as adminbot rc=0; 157 строк; tracebacks=0; ERROR=0; CRITICAL=0;
WARNING=1
```

Единственный WARNING — существующий `services.summary_memory`:
`SmartModule: embedding generation not serviceable | index=smart_archive |
status=superseded | ... FTS-only (A06) | build pending — source empty`.
Traceback/ERROR/CRITICAL нет; WARNING не является падением деплоя.

`DISK` после: `/dev/vda1 103083636 71218840 26605844 73% /` (свободно
26 605 844 KB ≈ 25.4 GiB).

## 7. Effective config

- `budgets_enabled=false` глобально и во всех 3 чатах; источник — global/chat
  overrides; `known=true`, `stale=false`.
- MCA caps: `max_total_calls=0`, `max_metered_calls=0`, `max_same_call=0`,
  `fuse_seconds=0.0`; ни один cap не включён. Глобальный
  `limits_enforced=true` при всех нулевых значениях — штатная форма
  «политика не задана».
- Capacity: primary `z-ai/glm-5.3-flash-uncensored` — **1 048 576 / 32 768**,
  `source=provider_catalog`, `confidence=verified`; fallback `deepseek-flash`
  131 072; `legacy=1 000 000 unknown_fallback` (не выдан за verified).
- Schema: `user_version=47`, `pending=[]`, `schema_migrations` 36 строк,
  `max_version=47`, таблиц 130.

## 8. Owner settings / prompt provenance

`bot_settings`: **548** строк, digest
`64243e1e0c90355f2da4fb73e3c6f1a1ce5d38a1781222c4a66bc2e4a44c8bae` —
до/после одинаковый. Защищённые значения не переписаны:

```
flags.budgets_enabled=false                 updated 2026-10-25
flags.factcheck_pipeline_v2=true            updated 2026-10-20
models.llm_model_name=z-ai/glm-5.3-flash-uncensored  updated 2026-11-11
models.llm_base_url=https://nano-gpt.com/api/v1      updated 2026-09-12
prompts.checkup_system_prompt  3 030 chars  sha256 b0c70f974e0e...  updated 2026-10-31
prompts.factcheck_subject_system_prompt  2 146 chars  sha256 7df7e8752798...  updated 2026-11-14
```

`chat_profiles`: **3** строки, digest
`6bddf0617e2f41f1c71c1816eb0512d89353d3195003289b63d6ce157671a14c` —
финальные pre/post одинаковые.

**Сохранённая редакция checkup:** в `prompt_revisions` присутствует
manual-ревизия **`rev:d31300ef35a0`**, `origin=manual`, `scope=chat`,
**12 469 симв.**, sha256
`31d1750654615bf4e69e861ae66f393b31546b34982c7d5613052b67133b3701`,
`retired=false`, `actor_present=true`, `created_at=2026-11-14T06:11:54.954581Z`.
Она не потеряна и не снята с регистрации; при необходимости может быть
активирована через EVOL-017.

Активна factory-ревизия **`rev:9ed7b22b0d8c`**, `origin=factory`,
3 462 симв., sha256
`3140bb36404467973eb4d34afccb5409add55262d251d6d7a60b8df333980052`,
`factory_revision=fac:d263c52f7871`, `release_id=evol-016-cutover`,
activation_id **2941**, `kind=deploy_activate`, `detail_code=factory_activate`,
`outcome=applied`, `created_at=2026-11-14T13:42:28.420641Z`.
Это соответствует решению владельца 29.10.2026 (EVOL-012): новая заводская
ревизия в составе релиза активируется автоматически даже поверх ручной
правки; ручная правка остаётся неизменяемой историей.

Важно: EVOL-016 cutover удаляет активный chat-override
`prompts.checkup_system_prompt` (chat-2: nested overrides 32→31), но **не
удаляет** manual-ревизию. Поэтому первый verifier ошибочно принял изменение
`chat_profiles` за потерю; см. §9.

## 9. Аномалия первого прогона и повторный deploy

Первая попытка (13:42:24–13:42:38Z) подняла 2.58.201, health 200, schema 47,
budgets/caps/capacity/identity — все проверки прошли. Единственный failed
check был `profiles_digest_unchanged`: EVOL-016 cutover изменил chat-2
(override `prompts.checkup_system_prompt` снят, factory revision активирована).
Автоматический verifier счёл это нарушением preservation и откатил **код**
на 0e4a144d / 2.58.200. Ручная ревизия при этом осталась в журнале
(`rev:d31300ef35a0`, 12 469 симв., `retired=false`).

После сверки с owner decision EVOL-012 проверка была исправлена: preservation
теперь проверяет `prompt_revisions` (pre-ревизии сохранены; manual checkup
revision присутствует и не retired), а не неизменность chat-overrides.
Повторный deploy в 13:50 прошёл с `VERIFY_RC=0`; повторного cutover не было
(activation 2941 уже applied; новых изменений prompt/profile нет).

Это была ошибка **DevOps-verifier**, а не дефект продукта; код кандидата не
менялся. Первый rollback — code-only; данные/журнал промптов не откатывались.

## 10. Rollback

Target: **0e4a144d / 2.58.200**, code-only; schema 47, данные не откатываются.
Финальный deploy rollback не требовал (`rollback-result.txt`: not_executed).
Первый rollback выполнен 13:42:32–13:42:38Z: switch rc=0, restart rc=0,
HEAD 0e4a144d, branch release/2.58.200, health 2.58.200. Точные команды — в
`rollback.md`.

## 11. Границы

- Live-харнессы не запускались; они остаются отдельным follow-up.
- Карты требований и `plans/progress_scope.json` не менялись.
- `backups/` — pre-existing 33.5 GB; cleanup не выполнялся (не входит в задачу).
- Единственный WARNING журнала — `summary_memory` FTS-only (см. §6); не
  traceback/ERROR и не повод для rollback.
- AC-15/AC-19 saved-edition: сохранённая manual-ревизия присутствует и не
  retired; активна factory-ревизия по EVOL-012. Это надо учитывать Reviewer/PM
  при приёмке live-строки — не подменять «сохранена» на «активна».
