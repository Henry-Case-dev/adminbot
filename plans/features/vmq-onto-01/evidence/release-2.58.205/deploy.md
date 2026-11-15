# Deploy `2.58.205` (VMQ-ONTO-01 Slice D) — production, 15.11.2026

Статус: **deployed**, факты зафиксированы; VERIFIED не заявляется.

- Кандидат: `release/vmq-slice-d-2.58.205`, tip `bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1`
  (origin совпал: `refs/remotes/origin/release/vmq-slice-d-2.58.205`).
- База/откат: `2b419aa2627f627eb6ea5e2f46b5e01118da2bf0` (`2.58.204`, был deployed).
- Вердикт Reviewer: Approved for deploy на exact tip `bca18c1e`.
- Прод: VPS `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`.
- Окно: `2026-11-15T09:45:12Z` (pre) → `09:47:17Z` (restart) → `09:48Z` (post).
- Runbook: `plans/features/vmq-onto-01/evidence/release-2.58.205/predeploy.md`.

## 1. Predeploy backup (fail-closed)

MySQL-подобных копий нет: SQLite `.backup()` из **read-only** соединения
(`mode=ro`, URI) через `venv/bin/python` (модуль `sqlite3`), на сервере нет
CLI `sqlite3` — единственное отличие от команд в runbook, семантика та же.

| Параметр | Значение |
|---|---|
| Путь | `/var/www/admin_bot/backups/pre_deploy_258205_20261115T094514Z.db` |
| Размер | 3 354 996 736 B (10.5 s) |
| sha256 | `b388f0682cbea5aa2e1f373e186838a81b5560ae0a6f40aa7a91b39c198a02a7` |
| `integrity_check` | `ok` |
| `PRAGMA user_version` | 47 |
| Таблиц | 130 (совпадает с прод-базой) |
| `max(schema_migrations)` | 47 |
| Свободно до / после | 10 638 072 KB → 7 369 352 KB; headroom на копию 7 538 409 472 B |

Источник на момент копии: 3 354 976 256 B + WAL 10 061 072 B.
Гейт свободного места (`free − db ≥ 1 GB`) пройден до старта копии.
Fail-closed не срабатывал: read-back дал `ok`/47/130/47.

## 2. Checkout и deploy-манифест

- `git fetch origin release/vmq-slice-d-2.58.205` → `REMOTE_HEAD=bca18c1e…` (совпал с ожидаемым);
- `git checkout -b release/vmq-slice-d-2.58.205 bca18c1e` (force не использовался);
- `HEAD=bca18c1e`, `branch=release/vmq-slice-d-2.58.205`, tracked-dirty **0**,
  `APP_VERSION="2.58.205"`;
- манифест записан **до** рестарта штатным `tools/release_manifest.py --deployer devops`:

```json
{"deployed_at": "2026-11-15T09:47:15.317949Z", "deployed_sha": "bca18c1e271fdfafa4939b07c88a0d3f2a92b8a1", "deployer": "devops", "dirty_tracked": false, "effect": "deploy", "previous_sha": "2b419aa2627f627eb6ea5e2f46b5e01118da2bf0", "previous_version": "2.58.204", "release_branch": "release/vmq-slice-d-2.58.205", "schema": 1, "version": "2.58.205"}
```

## 3. Postdeploy (agent-run, не владелец)

1. **Health:** local `{"status":"ok","version":"2.58.205"}` (poll OK на 4-й итерации),
   public `https://admin-bot.duckdns.org/healthz` — тот же `2.58.205`; финальный
   публичный чек в конце прогона — `2.58.205`.
2. **Schema:** `PRAGMA user_version=47`, `max(schema_migrations)=47`, таблиц 130;
   journal: `[database] migrations: start | current user_version=47 | pending=[]`.
3. **Identity:** `code=verified_deployed`, `deployed_sha=checkout_sha=bca18c1e…`,
   `dirty=false`, `version_provenance {runtime 2.58.205, manifest 2.58.205, consistent true}`,
   `previous_sha=2b419aa2`, `conflict=[]` (полный файл — `identity.json`).
4. **Unit:** `ActiveState=active`, `NRestarts=0`, `MainPID=1075058`,
   `ExecMainStartTimestamp=Sun 2026-11-15 09:47:17 UTC`.
5. **Journal** с момента рестарта: 159 строк, `Traceback=0`, `ERROR=0`,
   `CRITICAL=0`, `database is locked=0`; WARNING — 1 (известный pre-existing
   `summary_memory: embedding generation not serviceable | status=superseded`,
   тот же класс, что при выкате `2.58.204`).
6. **Settings/profiles** (read-only снапшот существующего harness, pre на
   `2.58.204` коде / post на `2.58.205`):
   - `bot_settings`: 548 строк, digest `e98edf0e…7460` — **совпал**;
     digest без checkup-ключа `fefe4bca…c86d` — совпал;
   - `chat_profiles`: 3, digest `323a6528…0f89` — **совпал**;
   - ручная ревизия промпта: `rev:d31300ef35a0`, `origin=manual`, `scope=chat`,
     `retired=false`; override в профиле чата присутствует,
     `chars=12469`, `sha256=31d1750654615bf4e69e861ae66f393b31546b34982c7d5613052b67133b3701`
     (ожидаемый `31d17506…`); `prompts.global_row` 3500 симв.,
     sha256 `3cef66ec…929d` — pre=post;
   - `prompt_release`: `release=evol-016-cutover | blocks=112 | changed=0 | retired=0`.
7. **L1-наблюдение:** искусственных сообщений не создавалось. После рестарта
   реальных ходов нет: `mca_events` всего 350 559, из них `ts >= 09:47:17Z` — **0**,
   `direct_turn_context` post-restart — **0**. 20 последних (все до рестарта)
   имеют `memory_scope` пустым (поле появилось позже) — срез A1/A1P/P1/P2/P3
   **не снят**, запаркован как postdeploy observation без polling.

## 4. Отклонения и ограничения

- `harness/snapshot.py`, на который ссылается runbook, в дереве Git
  отсутствует; использован существующий проверенный harness из
  `plans/features/vmq-onto-01/evidence/release-2.58.204/harness/`
  (`identity.py` sha256 `a73ec97e…d4b0`, `snapshot.py` sha256 `99721a88…6f63`
  — те же суммы, что в `provenance.json` прошлого выката).
- На сервере нет CLI `sqlite3`; копия/read-back/проверки выполнены модулем
  `sqlite3` из `venv/bin/python` (read-only URI, `PRAGMA query_only=1`).
- Соединений с продом: recon (1) + основной прогон (1) + одна read-only
  передача артефактов harness (`scp`, 1). Параллельных коннектов и ретраев нет.
- Rollback не выполнялся: все обязательные postdeploy-гейты пройдены.
- Схема/DDL: 47 / 0 — миграций не применялось, restore БД не требовался.
- VERIFIED не заявляется: это отчёт о деплое; L1-срез на реальных ходах,
  MEM-04/TIME-01, TIME-02 reply и TIME-07 остаются неподтверждёнными
  (см. финальное одобрение Reviewer и `predeploy.md` §4).

## 5. Откат (если потребуется позже)

`git checkout 2b419aa2` + `systemctl restart admin_bot` (manifest — с
`--effect rollback`), БД не восстанавливать: схема и данные не менялись.
Копия `pre_deploy_258205_20261115T094514Z.db` проверена read-back.
