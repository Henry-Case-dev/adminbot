# Release 2.58.126 — PEMsoc: одна реакция (RELEASE-258126)

**База:** `d3cceb0c` (`origin/task/pemsoc-one-reaction`), код-коммит `97676e34`, от `origin/master` `f0160fd8`.
**Прод до релиза:** 2.58.125 @ `f0e6a0cd`.
**Bump:** 2.58.125 → 2.58.126.
**Откат:** `f0e6a0cd` (2.58.125), ветка `release/fix-2.58.125`.

## Что меняется в поведении

Один фикс: PEMsoc — одна реакция на сообщение/альбом/источник. Код фикса — `97676e34`
(claim across war/slavik/kucha/gif). Speech-контур не тронут: в bump-диффе только версионные пины.

## Bump

| Параметр | Значение |
|---|---|
| Файлов | **31** (proc set идентичен proc-125) |
| Пар пинов | **33** (31 файл + meta HEAD) |
| Non-token deltas | **NONE** — только `2.58.125 → 2.58.126` и meta HEAD `6e9f10a2 → d3cceb0c` |
| APP_VERSION | `2.58.126` |
| F8-meta HEAD | `d3cceb0c` = pre-bump HEAD (совпадает) |
| ΔDDL | **0** (ни schema/migration, ни `user_version` в диффе) |

Файлы: `README.md`, `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`,
4 × `tests/js/round1025_hotfix{7,8,9,10}_*.js`, 24 × `tests/test_*.py` (включая
`test_webapp_round1026_polygon.py` с 2 пинами).

## Guards

| Проверка | Результат |
|---|---|
| bump-verify | files=31, pairs=33, non-token deltas NONE, meta HEAD = pre-bump HEAD, APP_VERSION 2.58.126 |
| F8 `--check` (`tools/gen_param_registry_round1025.py`) | **EXIT 0**, реестр 582 == REGISTRY, карта полна, R17-чисто |
| `py_compile` изменённых (25 `.py`) | rc=0 |
| `pytest test_pemsoc_one_reaction + test_war_alert + test_slavik_handlers + test_slavik_priority -q` | **86 passed** (5.15 s) |
| FACTORY_SET | `47f0d1eb8de4` — без изменений (Core/prompt factory не тронуты) |
| Core rev | 8 (без изменений) |

## Деплой (выполнен)

Сервер: `nik@198.46.175.136`, каталог `/var/www/admin_bot`, unit `admin_bot`.

| Параметр | Значение |
|---|---|
| Deployed commit | `c635bfe9` (сервер сообщает `HEAD=c635bfe9`, `APP_VERSION = "2.58.126"`) |
| `systemctl restart admin_bot` | OK, `sudo -n` (пароль не запрашивался) |
| Состояние unit | `active/running`, MainPID `1139378`, **NRestarts = 0** |
| `/healthz` loopback (`127.0.0.1:8000`) | `{"status":"ok","version":"2.58.126"}` — новая версия отдаётся самим процессом |
| Журнал нового PID (15 мин, 185 строк) | **0** CRITICAL/ERROR/Traceback |
| Окно 60 мин | 0 CRITICAL/ERROR/Traceback, `GIF send failed` **0** |
| FACTORY_SET (на сервере, venv) | `47f0d1eb8de4` — **не изменился** |
| `services.pemsoc_reactions` | импортируется, `claim` присутствует |
| Core rev 8 / adopt | adopt в окне **0** (не повторялся); фабрика/Core не менялись (в диффе нет prompt/файлов фабрики) |
| ΔDDL | **0**: в bump-диффе нет schema-строк; `PRAGMA user_version` на проде = 37 (значение не менялось) |
| Логи `War Alert` / `Slavic` / `GIF` | 8 / 4 / 1 строк, исключений нет (ERR=0) |

Рабочие чаты не задействованы: тестовых сообщений/реакций не отправлялось.

## Откат

- Cold: `git checkout f0e6a0cd` (2.58.125) + `systemctl restart admin_bot`; ветка `release/fix-2.58.125` = `f0e6a0cd`.
- ΔDDL = 0, поэтому откат кода не требует отката схемы. Данных-миграций нет.
- Soft-флага у фикса нет; при инциденте — только cold revert.
