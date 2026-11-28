# Deploy 2.58.273 — FC-TRUST: S7 acceptance harness + S8 admission fix + U1 year-conflict fix

**Итог: DEPLOYED_AND_VERIFIED.**

- **deployed_sha:** `74ef57ef469220627207603ae133da308f37866f` (ветка `release/2.58.273`, HEAD на сервере = `refs/heads/release/2.58.273`)
- **tree на сервере:** `2d0918e7c13fef5e61ed260355499eecca785f21` — совпадает с собранным деревом
- **предыдущий релиз:** `a2195fe3f9289d75461f27c7278d52779e2b812a` = 2.58.272 (`previous_sha`/`previous_version` в манифесте)
- **версия:** 2.58.273 (три источника)
- **схема:** `user_version=50` до и после — без изменений; DDL 0
- **прод:** `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`, venv `/var/www/admin_bot/venv/bin/python` (3.12.3)
- **окно:** манифест `2026-11-28T10:05:45Z`, restart `10:05:48Z`, active с `10:05:48Z`

Состав кандидатов, bump и локальные проверки — в `assembly.md`. Ключевое:
продуктовое изменение одно (U1/FCT-U1-R1-F1: 4-значная денежная сумма не считается годом),
остальное — тестовые контракты и evidence. `web/api/routes.py`, `web/app.js`,
`web/index.html` после сборки байт-в-байт равны блобам задеплоенного 2.58.272
(sha256 `5c20750a…`, `20e87aa8…`, `b8570e5d…`), то есть route-set и Mini App не менялись.

## 1. fail2ban-дисциплина

HTTP-проверка `/healthz` выполнена **до** любых SSH-подключений (`200`, version 2.58.272).
За весь деплой — **4 коротких SSH-сессии** с интервалом ≥ 60 с: одна основная
(`raw/_deploy.sh`) и три read-only проверки (`raw/_verify.sh`, `raw/_journal-attr.sh`,
`raw/_anticliche-attr.sh`, `raw/_factcheck-activity.sh`). Один логин на сессию,
`-i ~/.ssh/adminbot_vps -o IdentitiesOnly=yes -o BatchMode=yes`, без ретраев и поллеров.

## 2. Идентичность (raw/deploy-run.txt)

```
PRE_HEAD=a2195fe3f… PRE_REF=detached PRE_DIRTY_TRACKED=0 PRE_VER=2.58.272 UNIT=active NRESTS=0
REMOTE_SHA=74ef57ef4…  (abort при несовпадении — не потребовался)
NEW_HEAD=74ef57ef4… NEW_REF=refs/heads/release/2.58.273 NEW_TREE=2d0918e7c…
POST_CHECKOUT_DIRTY_TRACKED=0
MANIFEST={… "deployed_sha": "74ef57ef4…", "previous_sha": "a2195fe3f…", "previous_version": "2.58.272",
          "release_branch": "release/2.58.273", "version": "2.58.273", "dirty_tracked": false}
```

Финальная проверка (`raw/deploy-verify.txt`, `raw/manifest-deployed.txt`):

```
HEAD=74ef57ef4… REF=refs/heads/release/2.58.273 TREE=2d0918e7c… DIRTY_TRACKED=0 WORKTREES=1
MANIFEST_EFFECT=deploy 2.58.273 74ef57ef4
```

## 3. Версия — три источника

```
VER_AST=2.58.273   VER_IMPORT=2.58.273   VER_MANIFEST=2.58.273
```

## 4. Health / unit

```
LOCAL_HEALTHZ_HTTP=200   LOCAL_HEALTHZ={"status":"ok","version":"2.58.273"}
PUBLIC_HEALTHZ_HTTP=200  PUBLIC_HEALTHZ={"status":"ok","version":"2.58.273"}
UNIT=active NRESTS=0 MAINPID=1325247 BOTPROCS=1
PUBLIC_APPJS_HTTP=200 PUBLIC_APPJS_BYTES=2744085   (== собранному app.js)
```

Повторная проверка через ~8 минут после рестарта: те же `200`/`2.58.273`, `NRESTS=0`,
MainPID не менялся — рестарт-петли нет.

## 5. Блобы на сервере (raw/deploy-run.txt)

```
5c20750a…  web/api/routes.py          ROUTES_MATCH=yes
20e87aa8…  web/app.js                 APPJS_MATCH=yes
b8570e5d…  web/index.html
610aa958…  config/settings.py
98c368e1…  services/search_aggregator.py     (== кандидату U1)
5f5d69bd…  services/temporal_factcheck.py    (== кандидату U1)
9929fcdd…  services/prompt_registry.py       (== кандидату U1)
```

## 6. Схема и данные

```
SQLITE_USER_VERSION=50 (PRE)  USER_VERSION_AFTER=50 (POST)  QUICK_CHECK=ok elapsed=333.3s
SETTINGS_ROWS=558 (PRE) == 558 (POST)
SETTINGS_MD5_KV=6f6d6624f5f676a1f26dc4be75128aed (PRE) == (POST)
SETTINGS_MAXUPD=2026-11-27 21:48:55.892740+00:00 (PRE) == (POST)
PROMPTS_KEYS=29 (PRE) == 29 (POST)   PROMPT_KEYS_EMPTY=0
HOT_FLAG=present:true (PRE) == (POST)
```

Сохранённые настройки и чатовые override не тронуты деплоем; новый продуктовый флаг не
вводился, заводское значение готовой функции не менялось.

## 7. Журнал

Окно после рестарта (`systemctl ActiveEnterTimestamp` = `10:05:48Z`, 551 строка):

```
SINCE_TRACEBACK=0 SINCE_SQL_ERR=0 SINCE_402_403=0 J_CRITICAL=0
FACTCHECK_LINES=3 FACTCHECK_ERR=0
```

Причина нулевых/шумовых счётчиков в более широком 2-часовом окне разобрана в
`raw/journal-attribution.txt` и `raw/anticliche-attribution.txt`:

- 3 traceback в 2-часовом окне — **до** рестарта, на старых PID `1267547`/`1294405`
  (2.58.272): `lore_compiler_service.note_compiler_touch()` TypeError в 07:27 и
  `initiative_observer` `[b01] opportunity eval failed` (asyncio.wait_for) в 08:55/09:34/09:44.
  После рестарта — 0.
- `402/403` в широком окне — это фрагменты миллисекунд в таймстампах (`07:19:01,402`) и
  токены (`LLM usage in=402 out=68`), а не HTTP-ответы; после рестарта — 0 совпадений.
- Единственная `ERROR`-строка после рестарта — `component=anticliche step=fetch
  status=error reason=sources_unavailable` (10:10:51). Это штатное поведение модуля без
  настроенных источников: за предыдущие 6 часов до релиза та же строка встречается
  10 раз на 2.58.272 (23:06, 00:08, 01:11, 01:57, 03:05, 04:20, 05:38, 06:14, 06:44, 08:19).
  К изменённым файлам релиза отношения не имеет.

## 8. Диск (P0-PROD-DISK-01)

```
df -h /   99G 51G 44G 54%    (до и после — без изменений)
deploy_backup: count=2 bytes=13583237120 (12.7 GiB)   [(keep=2) соблюдён]
db_backup:     count=1 bytes=5587439616  (5.2 GiB)
total_bytes=19179296958 (17.9 GiB)
manage.py disk audit   → выполнен
manage.py disk cleanup --apply → deleted=0 bytes_freed=0 skipped=0 errors=0
manage.py disk cleanup (dry-run) → candidates=0
TMP_LEFTOVERS=0  WORKTREES=1  PYTEST_PROCS=0
```

Ни одна новая полная копия БД на релиз не создавалась; временные артефакты деплоя
(rollback-worktree `/tmp/wt_rb273_*`, base64-буфер) удалены и проверены. Собственных
production-файлов после работы не оставлено.

## 9. Rollback dry-run (`a2195fe3f`)

```
RB_VERSION=            ← вспомогательный AST-echo упал на BOM (utf-8 без -sig) в моём сниппете;
                          сам dry-run от этого не зависит и завершился успешно
{ "deployed_sha": "a2195fe3f…", "effect": "rollback", "version": "2.58.272", … }
RB_RC=0
RB_WORKTREE_LEFT=0
```

Путь откатa живой: `git checkout -B release/2.58.272 a2195fe3f && systemctl restart admin_bot`
(+ `tools/release_manifest.py --effect rollback`), dry-run возвращает rc 0 и версию 2.58.272.

## 10. Что осталось непроверенным

- Живой сценарий «фактчек по сообщению с денежной суммой» в проде не форсировался: это
  требует реального потока сообщений от пользователя, синтетический трафик в реальные
  чаты недопустим. Ложный year-conflict закрыт детерминированными тестами
  (`test_fc_trust_assertion_kind`, `test_fc_trust_relation_binding`, S7-харнесс) и
  подтверждён тем, что на сервере лежат ровно те блобы `services/temporal_factcheck.py`
  и `services/search_aggregator.py`, которые прошли независимое ревью r2.
- Записи 07:27/08:55/09:34/09:44 (см. §7) — поведение 2.58.272 в других модулях
  (`lore_compiler_service`, `initiative_observer`), вне scope этого релиза; не исправлялись
  и не маскировались.
