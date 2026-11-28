# Deploy 2.58.271 — FC-TRUST S6-U2 (сводные показатели прогонов, только вычисление)

- **Дата деплоя:** 2026-11-28T06:39:44Z (манифест), restart 06:39:47Z.
- **deployed_sha:** `3a78484b92a6f3ba1273360e4a34de396dcf52f1` (ветка `release/2.58.271`, detached).
- **Продукт (блобы на проде):** `services/temporal_factcheck.py` = `582a2efb48a1…`
  (sha256 `5231d6b8…`, == кандидат `936bc31a7`), `tests/test_fc_trust_s6_aggregates.py` = `6643c50faea1…`
  (sha256 `18774e3c…`). Совпадает с reviewed-кандидатом побайтово.
- **Предыдущий:** `438ad790e` = 2.58.270 (манифест это зафиксировал: `previous_sha`/`previous_version`).
- **Схема:** `user_version=50` — не менялась (DDL Δ=0, миграции не запускались).
- **Откат:** code-only к `438ad790e` (dry-run rc 0, см. §5).

## 1. Identity — три источника версии + схема

`raw/deploy-identity.txt`:

```
head=3a78484b92a6f3ba1273360e4a34de396dcf52f1
dirty_tracked=0
version (config/settings.py, AST) = 2.58.271
version (config/settings.py, import) = 2.58.271
version (.deploy/release.json) = 2.58.271
healthz={"status":"ok","version":"2.58.271"}
routes_sha256=b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
appjs_sha256=3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a
temporal_factcheck_sha256=5231d6b8238f5b173ff1adca16f81d1874b50b244a8da452a6da32254de29f37
factcheck_prompts_sha256=4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4
unit=active restarts=0 mainpid=1267547 bot_procs=1
```

Манифест на проде (`raw/deploy-manifest.txt`):

```json
{"deployed_at": "2026-11-28T06:39:44.516790Z", "deployed_sha": "3a78484b92a6f3ba1273360e4a34de396dcf52f1", "dirty_tracked": false, "effect": "deploy", "previous_sha": "438ad790eb998d1af6d6731be4392ea1d6179b4e", "previous_version": "2.58.270", "schema": 1, "version": "2.58.271"}
```

Права: `chown -R adminbot:adminbot`, umask 022, `644` на продуктовых файлах и `config/settings.py`;
`IMPORT_OK` для `services.temporal_factcheck` (обе функции агрегатов вызываемы).

## 2. Routes и бандл

```
web/api/routes.py sha256 = b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a  == база
/web/app.js (локально, порт 8000): bytes=2739459 sha256=3631e82de2a82b506b63d13914902678e31a28d1aa1abb7d41c79501c4b0282a
публично https://admin-bot.duckdns.org/web/app.js: 200, 2739459 B, sha256 = 3631e82d… (== диск)
```

## 3. База данных и сохранность настроек

`raw/deploy-db.txt`:

```
user_version 50 (не менялась)
quick_check ok (298.4 s, bounded 900 s, read-only URI)
bot_settings rows=558 | md5=50887d362fe93bf7646beae77cce32c6 | maxupd=2026-11-27 21:48:55.89274+00
prompts.* keys = 29
prompt_revisions = 196 (информационно)
```

md5 настроек `50887d36…` совпадает с зафиксированным на релизе 2.58.264 и не изменился
(`maxupd` прежний, 27.11) ⇒ пользовательские настройки не тронуты; число промпт-ключей 29
совпадает с базой. Запись в БД во время деплоя не выполнялась.

## 4. Здоровье и журнал

```
/healthz локально (127.0.0.1:8000) = 200, {"status":"ok","version":"2.58.271"}
/healthz публично (admin-bot.duckdns.org, Caddy → 127.0.0.1:8000) = 200, t=1.13 s
unit active, NRestarts=0, MainPID=1267547, процессов bot.py = 1
journal 06:39:47 → 07:00Z (~20 мин): 716 строк, 0 Traceback, 3 строки уровня ERROR
  - 2× services.anticliche_worker sources_unavailable (wikipedia) — известный предсуществующий дефект источника;
  - 1× services.mca_events INCIDENT (mca16 worker_lost → WATCHDOG_TAKEOVER requeued, attempt=1) — следствие
    штатного graceful restart, задача восстановлена;
  0 HTTP 5xx, 0 ошибок temporal_factcheck/SQL («database is locked» / OperationalError) — 0.
```

`temporal_factcheck` и SQL: в окне нет ни одной ошибки; ошибок новых сигнатур нет.

## 5. Откат (dry-run)

`raw/deploy-rollback.txt`: `git archive 438ad790e` → временное дерево,
`APP_VERSION = 2.58.270`, `import services.temporal_factcheck` OK (агрегатов там нет —
ожидаемо), затем `tools/release_manifest.py --dry-run --effect rollback` в отдельном
detached-worktree на `438ad790e`:

```
deployed_sha=438ad790eb998d1af6d6731be4392ea1d6179b4e  version=2.58.270  effect=rollback  rc=0
```

Временное дерево и worktree удалены (`trap` + `worktree prune`), на проде остался только
основной checkout.

## 6. Диск

`raw/deploy-disk.txt`:

```
df -h / → /dev/vda1 99G, 51G занято, 44G свободно (54%)
disk audit: db_backup 1 (5.2 GiB), deploy_backup 2 (12.7 GiB), facts_export 1 (8.0 MiB),
            jsonl_retention 5 (31.8 KiB), other 7 (201.1 KiB), total 17.9 GiB
disk cleanup --apply (deploy pool keep=2): deleted=0 bytes_freed=0 skipped=0 errors=0
```

Пригодных бэкапов ≥2: `predeploy-258257-…db` (6.4 GiB), `predeploy-258258-…db` (6.4 GiB),
плюс `local_database_20261128.db` (5.3 GiB). Retention сработал по факту (2 в пуле keep),
удалять было нечего.

## 7. Гигиена production

Временные файлы проверок (`/tmp/j*.txt`, `/tmp/appjs271.js`, `/tmp/a271.js`, `/tmp/pubapp.js`,
`/tmp/rollback271`, `/tmp/wt_rb271`) удалены; фоновых процессов и осиротевших unit'ов нет
(`ps` по pytest/rollback — пусто, `git worktree list` — только основной checkout).
Тестовых сообщений в рабочие чаты не отправлялось.

## 8. Соотношение evidence-коммита и deployed SHA

Этот файл и `raw/deploy-*` добавлены **после** деплоя отдельным docs-коммитом
(`git diff --stat 3a78484b9..HEAD` = только `evidence/release-2.58.271/`). Продуктовые блобы
на evidence-HEAD те же, что на проде: `services/temporal_factcheck.py` = `582a2efb48a1…`,
`tests/test_fc_trust_s6_aggregates.py` = `6643c50faea1…`, `web/api/routes.py` = `a851e4f8…`,
`web/app.js` = `2f6d956d…`. Фактически выложенный и работающий SHA остаётся `3a78484b9`.

## 9. Не проверено (честно)

- Реальный прогон сводных показателей на «живых» данных: функции доступны и импортируются на
  проде, но вызов чтения агрегатов не выполнялся (это read-only калькулятор без потребителя в UI/API);
  первый естественный вызов — при следующем обращении к диагностике прогонов.
- Публичный TLS-чек выполнен только с SNI-хостом `admin-bot.duckdns.org` (Caddy); запрос на IP
  без SNI отклоняется на клиенте/сервере — это свойство конфигурации, не регресс релиза.
