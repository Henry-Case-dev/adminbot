# Deploy 2.58.272 — FC-TRUST S6-U3 (API сводки, компактная панель, заводской флаг v2 = ON)

- **Дата деплоя:** 2026-11-28T08:14:34Z (манифест), restart 08:14:41Z.
- **deployed_sha:** `a2195fe3f9289d75461f27c7278d52779e2b812a` (ветка `release/2.58.272`, checkout detached).
- **Предыдущий:** `3a78484b92a6f3ba1273360e4a34de396dcf52f1` = 2.58.271 (манифест зафиксировал
  `previous_sha`/`previous_version`).
- **Схема:** `user_version=50` до и после — не менялась (DDL Δ=0, миграции не запускались).
- **Откат:** code-only к `3a78484b9` (dry-run rc 0, см. §6).
- **Хост:** `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`, venv `/var/www/admin_bot/venv`.

## 0. Дисциплина доступа (fail2ban)

Первый коннект (07:52Z) был отклонён (`Permission denied (publickey,password)`) — ключ не был
указан явно. Дальше: пауза >21 минуты, затем **один** основной прогон (`_deploy.sh`, 08:14–08:21Z)
и три коротких read-only прогона (`_deploy2.sh` 08:36Z — окно журнала, `_deploy3.sh`, `_deploy4.sh`).
Параллельных коннектов нет, перебора логинов/ключей нет, автоповторов после auth-фейла нет.
Рабочий ключ — `~/.ssh/adminbot_vps` (`-o IdentitiesOnly=yes -o BatchMode=yes`).

**Замечание по стримингу:** PowerShell дописывает `\r` к последней строке stdin, поэтому bash
печатает в конце `bash: line N: $'\r': command not found`. Строка стоит **после** `== DONE ==`;
все команды до неё выполнены (подтверждается полным набором секций ниже). На результат деплоя не влияет.

## 1. Identity — три источника версии + манифест

`raw/deploy-identity.txt`:

```
PRE_HEAD=3a78484b92a6f3ba1273360e4a34de396dcf52f1   PRE_REF=detached   PRE_DIRTY_TRACKED=0
REMOTE_SHA=a2195fe3f9289d75461f27c7278d52779e2b812a
NEW_HEAD=a2195fe3f9289d75461f27c7278d52779e2b812a   POST_CHECKOUT_DIRTY_TRACKED=0
VER_AST=2.58.272   VER_IMPORT=2.58.272   VER_MANIFEST=2.58.272
MANIFEST={"deployed_at": "2026-11-28T08:14:34.348403Z", "deployed_sha": "a2195fe3f9...",
          "dirty_tracked": false, "effect": "deploy",
          "previous_sha": "3a78484b92a6f3ba1273360e4a34de396dcf52f1", "previous_version": "2.58.271",
          "schema": 1, "version": "2.58.272"}
UNIT=active NRESTS=0 MAINPID=1294405 BOTPROCS=1 SINCE=Sat 2026-11-28 08:14:41 UTC
HEAD=a2195fe3f9... DIRTY_TRACKED=0 WORKTREES=1
```

SHA деплоя совпал с ожидаемым **до** переключения (`REMOTE_SHA != EXPECT_SHA` → жёсткий abort,
не сработал).

## 2. Файловая идентичность на проде (== сборка == кандидат)

`raw/deploy-file-identity.txt` (sha256 на диске сервера):

```
5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf  web/api/routes.py
20e87aa86fd888114ba706282021a4fcb10331e2672c0aec12d8b61f04b28e74  web/app.js
b8570e5deb8136756dba402719d9530d6e3ff4ed17a45f18ed0d99b001323907  web/index.html
ca3bc66df1c0b0de34f15b450d006c27a452c1e696e744c3801c2e79f44bdd7f  config/settings.py
01bb941b0d5a2b64dedb34f2600baf467ae6255bdd2e3c2a66f3db39e6b03650  services/factcheck_orchestrator.py
4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4  services/factcheck_prompts.py
APPJS_BYTES=2744085
```

Все значения **совпадают** с `assembly.md` §1 (и с reviewed-кандидатом `c3c0e1cb3` / продуктом
`f6cd011e0`); `factcheck_prompts.py` = `4cd1e893…` == база (не менялся).
Публично: `https://admin-bot.duckdns.org/web/app.js` → **200**, `2744085` B (== размер на диске,
== кандидат).

Отдельный прогон `raw/deploy-prod-blobs.txt` подтверждает то же **на самом проде** для полного
набора файлов кандидата (блобы `git rev-parse HEAD:<path>` + sha256 на диске):

```
92bb8a72…  web/api/routes.py                     sha256 5c20750a…  == ожидаемо
8d3c535e…  web/app.js                            sha256 20e87aa8…  == ожидаемо
90499d81…  web/index.html                        sha256 b8570e5d…  == ожидаемо
c40ed631…  config/settings.py                    sha256 ca3bc66d…  == ожидаемо
5f1870e3…  services/factcheck_orchestrator.py    sha256 01bb941b…  == ожидаемо
64bb06c0…  services/factcheck_prompts.py         sha256 4cd1e893…  == база (не менялся)
2a74fbbd…  tests/test_fc_trust_s6_aggregate_api.py sha256 f4ec5b19…  == кандидат
dee8b9dd…  tests/test_mca23_planned_vs_actual.py   sha256 a155eb35…  == кандидат
bc76ccef…  tests/test_round1025_f8_registry.py     sha256 875d861e…  == кандидат + версия
0dc8ac3a…  tests/fixtures/round1025/f8_baseline.json sha256 3e22a537… == кандидат
HEAD=a2195fe3f9…  DIRTY_TRACKED=0
```

## 3. Здоровье, эндпоинт, журнал

`raw/deploy-health.txt`, `raw/deploy-journal.txt`:

```
/healthz локально 127.0.0.1:8000   = 200 {"status":"ok","version":"2.58.272"}
/healthz публично admin-bot.duckdns.org = 200 {"status":"ok","version":"2.58.272"}
unit active, NRestarts=0, MainPID=1294405, процессов bot.py = 1

GET /api/factcheck/temporal/aggregate (без initData):
  {"detail":"missing init data"}  HTTP 401
  BODY_HAS_TRACEBACK=0  BODY_HAS_SECRET_WORD=0  BODY_HAS_PY_PATH=0

journal 08:14:35 → 08:36:23Z (21.8 мин): 2273 строки,
  Traceback=0, SQL-ошибки (OperationalError/database is locked/asyncpg|psycopg)=0,
  HTTP 5xx=0, ERROR-уровень=2:
   2× services.anticliche_worker [pipeline] step=fetch status=error reason=sources_unavailable
      (wikipedia) — известный предсуществующий дефект источника, не связан с релизом
```

## 4. Схема и сохранность настроек

`raw/deploy-db.txt`:

```
SQLITE_USER_VERSION=50 (до) → USER_VERSION_AFTER=50 (после)
QUICK_CHECK=ok (338.5 s, read-only URI)
SETTINGS_ROWS=558  SETTINGS_MAXUPD=2026-11-27 21:48:55.892740+00:00
PROMPTS_KEYS=29
HOT_FLAG=present value='true' category='flags' updated_at=2026-10-20 09:44:06.723000+00:00
```

Строк 558 и `max(updated_at)` `2026-11-27 21:48:55.89274+00` — **те же**, что в evidence
2.58.264/2.58.271 ⇒ ни одна настройка не перезаписана (никакой записи деплой и не выполнял;
строка `flags.factcheck_pipeline_v2` датирована 20.10).

**Честная оговорка по md5.** Исторический литерал `50887d362fe93bf7646beae77cce32c6`
воспроизвести не удалось: в прошлых сессиях он считался ad-hoc-запросом, формат которого не
зафиксирован в репозитории. Проверены шесть вариантов (см. `raw/deploy-db.txt`:
`SETTINGS_MD5_KV=6f6d6624…`, `KCV=544eb26d…`, `all_kv_sorted=4daee310…`, `json_compact=774acc89…`,
`json_default=757617de…`), хелпера `settings md5` в коде нет. Поэтому «настройки прежние»
доказывается не литералом md5, а двумя независимыми инвариантами: **rowcount 558** и
**max(updated_at)**, совпадающими с pre-deploy evidence, плюс нулевая запись в БД за деплой.

## 5. Effective-состояние флага v2

Приоритет (код): hot `flags.factcheck_pipeline_v2` → env `FACTCHECK_PIPELINE_V2_ENABLED` → заводское.

```
FACTORY_LITERAL=True            (AST config/settings.py, класс Settings: _env_bool(..., True))
ENV_UNIT_ROWS=0                 (в unit нет переменной)
ENV_FILE_ROWS=0                 (в .env нет переменной)
HOT_FLAG=present value='true'   (bot_settings, category=flags, updated_at 2026-10-20 — не переписан)
FRESH_EFFECTIVE=True            (свежий импорт: services.factcheck_orchestrator.pipeline_v2_enabled())
```

**Фактический effective-источник — сохранённая hot/PG-строка `flags.factcheck_pipeline_v2 = true`**
(она существовала до релиза и не перезаписывалась), заводское значение тоже `True`, env-переопределения
нет ⇒ флаг **ON**, пользовательский/сохранённый выбор не сброшен. Это соответствует правилу
проекта 09.11.2026 (заводское ON) и не является «теневой» активацией.

## 6. Откат (dry-run)

`raw/deploy-rollback.txt`: временный detached-worktree на `3a78484b9` → `tools/release_manifest.py
--dry-run --effect rollback`:

```
{"deployed_at": "2026-11-28T08:20:31.213654Z", "deployed_sha": "3a78484b92a6f3ba1273360e4a34de396dcf52f1",
 "dirty_tracked": false, "effect": "rollback", "previous_sha": null, "previous_version": null,
 "schema": 1, "version": "2.58.271"}
RB_RC=0   RB_WORKTREE_LEFT=0
```

Точка откатa: **`3a78484b92a6f3ba1273360e4a34de396dcf52f1` (2.58.271)**, code-only
(`git checkout --detach 3a78484b9 && systemctl restart admin_bot`), DDL Δ=0 ⇒ совместимость схемы v50
сохранена. Временный worktree удалён, на проде остался один checkout.

## 7. Диск и retention

`raw/deploy-disk.txt`:

```
df -h / → /dev/vda1 99G, 51G занято, 44G свободно (54%)   (до и после cleanup — без изменений)
disk audit: total 17.9 GiB; deploy_backup 2 (predeploy-258257 6.3 GiB, predeploy-258258 6.4 GiB),
            db_backup 1 (local_database_20261128.db 5.2 GiB), facts_export 1 (8.0 MiB), jsonl/other — мелкие
disk cleanup --apply (deploy pool keep=2): deleted=0 bytes_freed=0 skipped=0 errors=0
```

`keep=2` соблюден: два последних predeploy-дампа сохранены, удалять было нечего. Новых копий БД
этот деплой не создавал (миграций нет).

## 8. Гигиена production и worktree

`raw/deploy-hygiene.txt`:

```
PYTEST_PROCS=0  PPID1_PYTEST=0  TMP_WT=0  WORKTREES=1 (только /var/www/admin_bot)
TMP_AUDIT_COUNT=3 → удалены сторонние старые дампы журнала:
  /tmp/j258193b.txt (11.11, 74.5 KiB), /tmp/j258193.txt (11.11, 25.0 KiB), /tmp/jstart.txt (27.11, 30.0 KiB)
TMP_AFTER=0
```

Своих временных файлов деплой не оставлял (скрипты шли через stdin, без файлов на сервере;
rollback-worktree удалён). Никаких `nohup`/фоновых процессов не запускалось.

Контрольный прогон `raw/deploy-prod-blobs.txt`: `TMP_SCRATCH=0 WORKTREES=1 ORPHANS=0`.

## 9. Что осталось непроверенным (честно)

- **Живой рендер панели в MiniApp** (строка сводки под заголовком карточки «Временной фактчек»)
  не проверялся: страница требует Telegram initData/авторизованную сессию, которой в этом контуре
  нет; реальный admin-запрос к `/api/factcheck/temporal/aggregate` с валидным initData не выполнялся.
  Проверено: endpoint существует, отвечает 401 без initData, тело без секретов; серверный код и бандл
  на проде байт-в-байт совпадают с reviewed-кандидатом (структурная проверка UI — в ревью S6-U3).
- **DDL/миграции:** отсутствуют по конструкции (v50 не менялся); это подтверждено, а не проверено
  «на живых данных».
- Публичный TLS-чек выполнен по SNI-хосту `admin-bot.duckdns.org` (Caddy → 127.0.0.1:8000).

## 10. Соотношение evidence-коммита и deployed SHA

Этот файл и `raw/deploy-*` добавлены **после** деплоя отдельным docs-коммитом. Продуктовые блобы
на HEAD релизной ветки те же, что на проде (`raw/identity-committed.txt`): `routes.py` `92bb8a72…`,
`app.js` `8d3c535e…`, `index.html` `90499d81…`, `factcheck_prompts.py` `64bb06c0…`.
Фактически выложенный и работающий SHA остаётся **`a2195fe3f9289d75461f27c7278d52779e2b812a`**.
