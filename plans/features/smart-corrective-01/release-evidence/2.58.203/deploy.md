# SMART-CORRECTIVE-01 / 2.58.203 — controlled production deploy

Дата: 2026-11-14 (UTC). Прогон: **18:55:01–19:08:51Z**.
Сервер: `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`, user `adminbot`.

Кандидат: **`c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5`**, ветка
`release/smart-corrective-01`, версия **2.58.203** (train tip, delta-ревью
`Approved for controlled deployment`, artifact sha `11a12ab5…`).
Предыдущая production-версия: **`0beed63df8037002ccfaacef019b8ea948d957f6` /
2.58.202** (rollback target).
Gate: `stage=deploy inventory=224 manual=232 scoped=384 errors=0`
(`evidence/gates/deploy-corrective-c97c06e4.txt`); plan gate `errors=0`;
parent deploy gates `errors=0`.

Delta против предыдущего релиза — runtime 5 файлов (метка чек-апа,
FC-анкер, APP_VERSION), остальное тесты/evidence; DDL нет, схема v47.
Live-харнессы: см. `fc-canary.md`, `prompt-release.md`, `watchdog.md`.

## 1. Pre-state

```
UTC                 2026-11-14T18:55:01Z
HEAD                0beed63df8037002ccfaacef019b8ea948d957f6
BRANCH              release/smart-corrective-01
APP_VERSION         2.58.202
UNIT                active, MainPID 837957, start 2026-11-14 15:14:44 UTC
TRACKED_DIRTY       0; untracked только .cache/
HEALTH_LOCAL        200 {"status":"ok","version":"2.58.202"}
HEALTH_PUBLIC       200 {"status":"ok","version":"2.58.202"}
DISK                /dev/vda1 103083636 74231616 23593068 76% /
DB_BYTES            3173666816
BACKUPS_BYTES       36465823413
manifest            0beed63d / 2.58.202 / previous 409f4e8a / 2.58.201
```

Preflight в рабочем дереве кандидата: `git status` clean на `c97c06e4`
(единственный untracked файл — чужой черновик ревью), manifest dry-run:
`version=2.58.203, deployed_sha=c97c06e4, dirty_tracked=false,
release_branch=release/smart-corrective-01`.

## 2. Backup

```
path        /var/www/admin_bot/backups/pre_deploy_258203_20261114T185501Z.db
size        3 007 090 688 B
integrity   ok
user_version 47
tables      130
```

Создан через `VACUUM INTO` по живой SQLite-БД, затем read-back
`PRAGMA integrity_check`/`user_version`. `backups/` до деплоя уже занимал
36 465 823 413 B (pre-existing, не чистился).

## 3. Fetch / fast-forward

```
git fetch --prune origin release/smart-corrective-01   rc=0
FETCH_HEAD   c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
git switch release/smart-corrective-01                 rc=0
git merge --ff-only FETCH_HEAD                         rc=0
0beed63d..c97c06e4  Fast-forward, 45 files, +2024/-65
HEAD        c97c06e4
APP_VERSION 2.58.203
tracked dirty 0
```

## 4. Manifest (до рестарта)

```json
{"deployed_at": "2026-11-14T18:56:47.914303Z",
 "deployed_sha": "c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5",
 "version": "2.58.203",
 "effect": "deploy",
 "previous_sha": "0beed63df8037002ccfaacef019b8ea948d957f6",
 "previous_version": "2.58.202",
 "release_branch": "release/smart-corrective-01",
 "dirty_tracked": false,
 "schema": 1}
```

`venv/bin/python tools/release_manifest.py` rc=0; chown `adminbot:adminbot`,
chmod 644.

## 5. Restart / health

```
systemctl restart admin_bot   rc=0
poll 1                      пусто (процесс стартует)
poll 2                      200 {"status":"ok","version":"2.58.203"}
health public               200 {"status":"ok","version":"2.58.203"}
unit                        active, MainPID 887397, NRestarts 0,
                            ExecMainStatus 0, start 2026-11-14 18:56:49 UTC
```

## 6. Post checks (verifier v2)

`raw/verify203.json`: **ok=true, 33 проверки, failed=[]**. Покрыто: версия/SHA/
ветка/чистота checkout, health local+public, схема 47/130 таблиц/migrations
36→47, неизменность настроек кроме ожидаемой строки, промпт-журнал
(manual 12 469/31d17506; новая factory-ревизия global 3 462/3140bb36;
активации 2944/2945), budgets OFF, caps 0, capacity, profiles digest.

Verifier v1 дал 3 «падения», все — дефекты самой проверки, не продукта
(код кандидата не менялся):
1) строки `prompts.*` в `bot_settings` хранятся как JSON-текст, поэтому
   длина/хеш raw-текста ≠ длине/хешу тела промпта;
2) у чатов CHAT_C1/CHAT_C2 есть явный `flags.budgets_enabled=false`
   chat-override (как и на 2.58.202), поэтому утверждение «override нет»
   было неверным.
Verifier v2 читает идентичность тела из журнала ревизий и из
бот-подобного резолвера (`raw/prov203.json`), бюджеты проверяет по
значениям, а не по отсутствию override.

## 7. Identity

`raw/identity203.json`, штатный `services.deploy_identity.collect_identity`
с `process_started_at` из unit (как это делает сервис):

```
code                     verified_deployed
deployed_sha / checkout_sha  c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5
dirty                    false
version_provenance       runtime=2.58.203, manifest=2.58.203, consistent=true
previous                 0beed63d / 2.58.202
upstream_head            refs/remotes/origin/release/smart-corrective-01
                         c97c06e4, observed 18:56:47.797016Z
sources                  release_manifest, git_head, git_cli,
                         runtime_app_version, process_start
conflict                 []
```

Замечание: вызов без `process_started_at` честно отдаёт
`local_unverified/no_process_start` — так же ведёт себя и харнесс
(`identity_code=local_unverified` в JSON канареек), это контекст вызова, а
не состояние прода.

## 8. Effective config

См. `effective-config.txt`. Кратко: схема 47 (DDL=0), таблиц 130; бюджеты
OFF глобально и во всех 3 чатах; MCA caps 0 / fuse 0; capacity
1 048 576 / 32 768, `provider_catalog`, `verified`; единственное изменённое
значение в `bot_settings` — `prompts.checkup_system_prompt`
(3 030/b0c70f97 → 3 462/3140bb36, без Betterstack/401); digest остальных
548 строк и digest `chat_profiles` не изменились.

## 9. Prompt release / owner edition

См. `prompt-release.md` и `provenance.txt`: глобальный слой активировал
новую factory-ревизию `rev:a2a369bba312` (`fac:93c42f967ef8`), а
сохранённая владельцем редакция `rev:d31300ef35a0` осталась активной
(активация 2945 `factory_superseded_manual`, `skipped_same`), байты и
chat-override не тронуты.

## 10. Journal

`journal-summary.txt` (окно до 19:08:51Z): 1401 строк, 0 traceback,
0 CRITICAL, 2 ERROR и 11 WARNING. Оба ERROR — существующий периодический сбой
`anticliche` (wikipedia `sources_unavailable`), он же встречается 6 раз в
6 часах ДО релиза; WARNING — пропуски тиков APScheduler, 2 retry LLM по
ReadTimeout и известное FTS-предупреждение `summary_memory`.
Строк `persisted speech value withheld` — 0.

Расширенное окно 19:09–19:20:41Z (тот же процесс): добавились 2 ERROR
`services.llm_client` (ReadTimeout/total_budget_exceeded к nano-gpt.com),
4 ERROR `services.summary_memory` как следствие того же таймаута
(`graph_extract_failed`, «batch kept, pipeline continues») и 1 ERROR
`services.mca_events` — инцидент реального takeover (см. §11). Traceback 0,
CRITICAL 0. Класс `llm_client` встречался и до релиза (12 раз за 6 часов).

## 11. Watchdog / инциденты

Подробно — `watchdog.md`. Кратко: после релиза 22 свипа (18:56:52–19:17:02Z),
все `success`; один **реальный** takeover в 19:14:01Z (job `1e900f46…`,
experience.review, `worker_lost` → `takeover_recovered`,
discovered/attempted/recovered=1, failed=0) и связанный с ним инцидент
`inc_583cdba5…` (ERROR; на 19:18:03Z ещё открыт, в последнем свипе задача уже
в `normal_wait`). Тот же fingerprint срабатывал до релиза (16:34:42Z,
17:22:04Z, оба раза восстановление и закрытие), поэтому это существующий
повторяющийся класс, а не регрессия релиза; ложных takeover нет.
Исторические инциденты (15, из них 3 открытых) сохранены.

## 12. Rollback

Target: **0beed63d / 2.58.202**, code-only; схема 47 и данные не
откатываются. Финальный deploy rollback не требовал; точные команды — в
`rollback.md`.

## 13. Границы

- Требования в карте **не помечены** VERIFIED: связывание наблюдений — за PM.
- Пин канарейки `original_production_scenario --max-provider-calls 20`
  оказался недостаточным после FC-анкера (прогон A упал в
  `provider_cap_reached`, это не продуктовый вердикт); чистый вердикт
  получен свежим прогоном с cap 40 — см. `fc-canary.md` §4. Это вопрос
  конфигурации измерения, его должен подтвердить Reviewer/PM.
- Инцидент `inc_583cdba5…` (experience.review worker_lost) остаётся
  открытым на момент последнего наблюдения; класс повторяющийся и
  фиксировался до релиза. Наблюдение — агентское, через штатную телеметрию.
- `backups/` pre-existing 36.5 GB, cleanup не выполнялся.
- Live-сообщений в чаты владельца не отправлялось (харнесс использует
  stub-бота и синтетический чат; `outbound_delivered_to_telegram=0`).
