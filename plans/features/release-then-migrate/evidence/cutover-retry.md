# CUTOVER RETRY — SUCCESS — release-then-migrate (slice CUT шаги 6–8 + VERIFY, DevOps)

**Дата окна:** 2026-10-29, подготовка 03:44Z, простое окно **04:06:18Z → 04:17:39Z (гэп 11 мин 21 с)**, верификация до 04:22Z (UTC; оба сервера Etc/UTC). **Исполнитель:** DevOps (subagent CUT-retry).
**MIGRATION_SOURCE_SHA:** `5346ee765e83ee859596b60437811b21db1e4564` (2.58.141) — подтверждён на OLD (O1) и на NEW (N1/N5).
**Итог:** **CUT SUCCESS + VERIFY PASS.** Владелец передал токен DuckDNS в приватный `deploy_commands.txt` → блокер прошлого окна (WAITING_EXTERNAL) устранён до начала простоя. Новый VPS — единственный работающий production; старый остановлен (disabled) и сохранён как fallback. Тестовые сообщения в рабочие чаты не отправлялись.
**План отката:** `evidence/rollback-plan.md` (не понадобился; DuckDNS-откат теперь доступен и по API — токен проверен no-op-пробой ДО остановки старого бота).

## 0. Журнал SSH-сеансов (fail2ban-дисциплина: паузы ≥62 c/хост, single auth, без ретраев/параллели)

| # | Время UTC | Хост | Содержание | Результат |
|---|---|---|---|---|
| pre | 04:04:56 | локально | healthz OLD 200 `2.58.141`; DNS(1.1.1.1)→198.46.175.136; DuckDNS **no-op** update (ip=старый) → `OK` | PREFLIGHT_OK |
| O1 | 04:05:15 | OLD nik@ | recon: HEAD==SHA, unit active, 4 контейнера Up, env sha == SYNC, db stat | OK |
| N1 | 04:05:33 | NEW root@ | preflight: unit inactive+disabled, 0 procs; **очищены остатки `/tmp/oc_cut_*.sh` (0 слева)**; cron-аномалия классифицирована; staging на месте; authkeys=1 (владелец) | OK |
| O2 | 04:06:18 | OLD | **WINDOW_START**: stop admin_bot+bot-api; **держатели SQLite поименованы**; финальные снапшоты; keygen | OK |
| N2a | 04:08:01 | NEW | установка временного ключа cut (authkey_lines=2) | OK |
| O2b | 04:09:09 | OLD | пуш OLD→NEW: db+dump+tar+env одним rsync; REMOTE sha **4/4 == LOCAL**; media/extra/chrome/dossier/info дельты (media: 0 файлов изменений) | OK |
| N2 | 04:11:15 | NEW | sha 4/4 MATCH → integrity ok (staging) → placement по точному `DB_PATH` → PG restore `--clean --if-exists` **rc=0, 0 err** → 26/26 counts == OLD → DSN OK → ENV_BYTES_MATCH → ownership | OK |
| O3 | 04:11:49 | OLD | **logOut** на старом bot-api: HTTP 200 `{"ok":true}`; пост-logout дельта (3 файла) → push (remote==local); **stop старого стека**: unit inactive+**disabled**, caddy/xray inactive, 4 контейнера exited, 0 procs; intact-check; staging-копии удалены | OK |
| dns | 04:12:3x | локально | DuckDNS update → 192.255.209.205 → `OK`; **резолв 1.1.1.1/8.8.8.8/9.9.9.9 → новый IP через 4 с** | OK |
| N3 | 04:12:55 | NEW | применение пост-logout набора (rsync --delete из sha-верифиц. тара) → compose up → bot-api **healthy** → **getMe 200 `{"ok":true}`** (токен привязан к NEW) → xray active → caddy active → **TLS-сертификат выпущен ~04:13:45** (handshake 502=TLS OK, приложение ещё не поднято) | OK |
| N4 | 04:17:33 | NEW | `enable --now admin_bot` → **healthz_try1=200 в 04:17:39Z** → NRestarts=0, 1 proc, journal 0 errors, polling запущен | **GAP END** |
| N5 | 04:18:36 | NEW | полный VERIFY (§2) + revoke временного ключа (authkey_lines=1, ключ владельца на месте) + очистка stale-копий staging (освобождено 1,669,840,896 B) | OK |
| N6 | 04:21:31 | NEW | media-пробы прицельно + path-независимый digest bot-api | OK |
| O4 | 04:22:07 | OLD | финальный fallback-state + относительный digest старого store + статус stray-probe | OK |

- OLD: 5 коннектов (лимит ~5–6 соблюдён), NEW: 7 (не ограничен fail2ban, пейсинг тот же); pushes OLD→NEW — исходящие с OLD по временному ключу (TOFU fingerprint `SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` == эталон).
- Окно и откат: откат НЕ потребовался. В каждый момент ≤1 бот: OLD остановлен 04:06:18–04:22 (и далее выключен), NEW единственный активный с 04:17:39.

## 1. Шаги 6–8 (§6 owner-input)

| Шаг | Результат | Evidence |
|---|---|---|
| 6 единственный admin_bot + logOut | OLD остановлен ДО старта NEW; logOut 200/`ok:true`; **tqueue.binlog пережил logOut (17 408 B)** — очередь обновлений сохранена; getMe на NEW = 200/`ok:true` (привязка токена); двойной обработки нет (0×409/conflict в журнале) | O3/N3/N4 |
| 7 DNS/reverse proxy | A-запись admin-bot.duckdns.org → 192.255.209.205 (API, verdict OK); резолв у трёх резолверов за 4 с; Caddy active, **ACME-сертификат выпущен** (LE, handshake OK); домен https 200; служебные порты не открыты: ufw только 22/80/443, 5432/8000/8081/9000/10808 — только loopback (bgutil 4416 host-net прикрыт ufw — шейп старого сервера) | dns/N3/N5/ext |
| 8 старт + приёмка | первый рабочий healthz **04:17:39Z** локально и по домену; NRestarts=0; 4 контейнера healthy; PG+SQLite с реальными данными; админка 200/307→`/web/`; journal 0 fatals; **гэп 11 мин 21 с** (§6.1 POST-приёмка — отдельный slice POST по карте) | N4/ext |

## 2. VERIFY (9 строк) — против ФИНАЛЬНОГО снапшота этого окна (O2 04:06–04:11)

| Строка | Числа | Статус |
|---|---|---|
| VERIFY-SQLITE | integrity_check=ok; **76/76 таблиц**; 75 equal + 1 GROW (`mca_events` 136964→136967 — естественная активность после старта); **0 shrink**; user_version 37; smart_messages **2 050 132** (граница max_rowid 2 372 360 == снапшоту, MONOTONIC_OK); graph_facts 21 688, nodes 28 964, edges 52 598, embedding_cache 16 649, mca_episodes 23, mca_experience_episodes 449, memory_dream_log 1 521, nostalgia_log 414, task_jobs 7 650, message_source_records 66 834, summary_runs 28 — всё == снапшоту | **PASS** |
| VERIFY-PG | восстановлен из финального дампа (sha `9d3482ad…`, restore rc=0/0 err); **26 таблиц: 25 equal + uptime_events 4296→4297 (heartbeat)**, 0 shrink/missing; bot_settings 544, chat_profiles 3, personas 2, persona_traits 50, lore 250, cover_* всё на месте; DSN-коннект реальным паролем OK (server_version_num 160015) | **PASS** |
| VERIFY-FILES | .env sha `67bb8b1e…` == OLD == SYNC (байт-в-байт); media **59 файлов, tree digest `d25b19c1…` old==new**; info_text sha == SYNC `c8866df2…`; cookies присутствуют; extra_images 3; dossier_jobs 6; пустых замен нет | **PASS** |
| VERIFY-GIT | HEAD NEW == `5346ee76…` == принятый production; `.env` NOT_TRACKED_OK; `deploy_commands.txt` ABSENT_OK; dirty=1 — только `?? .cache/` (untracked pip-кэш, не данные) | **PASS** |
| VERIFY-ROUTES | настройки те же (env байт-в-байт; WEBAPP_URL/MEDIA_PUBLIC_BASE_URL = https://admin-bot.duckdns.org в журнале старта); домен/TLS работают: **внешне (реальный DNS) healthz 200 `2.58.141`, admin UI 200 (307→/web/)**; volumes подключены (PG volume, bot-api bind, media-дерево) | **PASS** |
| VERIFY-SINGLE | OLD: unit inactive+**disabled**, 4 контейнера exited, 0 procs; NEW: ровно **1** bot.py, 1 bot-api; cron_admin_hits=0; systemd timers=0; 409/conflict=0 | **PASS** |
| VERIFY-ACCESS | bot_admins=3, bot_roles=4, chat_admins=1, param_permissions=1 — восстановлены из финального дампа; GraphRAG/embeddings без перестройки: mca_embedding_index_generations=3 (без изменений), embedding_cache 16 649 == снапшоту | **PASS** |
| VERIFY-OLDVPS | intact+stopped fallback (проверено O4 04:22:07Z): db stat **не менялся** (1 669 840 896 B / mtime 1793244883), env sha, HEAD, media 59, backups/ на месте, staging-копии удалены (оригиналы целы) | **PASS** |
| VERIFY-SNAPSHOT-BASIS | все сравнения — против финального снапшота ЭТОГО окна (O2), не дефолтов; снапшот снят backup API с остановленных писателей | **PASS** |

**bot-api final set old==new:** logOut очистил кэш медиа-файлов (435→3), сохранив `tqueue.binlog` 17 408 B, `webhooks_db.binlog`, `.gitkeep`; пост-logout набор передан таром (sha `01408ff6…` remote==local), применён `rsync --delete` → состав NEW == OLD **3/3 файла (имена+размеры)**; затем daemon NEW создал `td.binlog` (18 536→18 600 B — живая сессия после claim). Дайджест первого сравнения «не совпал» — артефакт метода (абсолютные префиксы путей), заменён на path-независимое сравнение; контент-доказательство — sha-цепочка тара.
**Медиа-route:** прицельный проб: единственный файл в корне media — `srv_cookies.txt` (cookies) → **404 — корректно** (не должен отдаваться наружу); публичная раздача реальных media-URL по конкретному item — **NOT_OBSERVED** в этом окне (нет естественного события; проверка → slice POST §7.1 точка 6; файлы бит-в-бит на месте).

## 3. Естественные наблюдения (без тестовых сообщений)

Polling запущен (`Run polling for bot …` в журнале); mca_events +3, uptime_events +1 (heartbeat 60 с), td.binlog растёт — бот жив и тикает штатно. Сканирующий трафик интернета уже приходит на новый Caddy (HEAD `/.env*` → 502/404, без раскрытий). Тестовые сообщения в рабочие чаты не отправлялись.

## 4. Аномалии — все разрешены/классифицированы

1. **db_holders=3 (прошлое окно) — РАЗГАДАНО:** 3 дескриптора = ОДИН процесс `venv/bin/python /tmp/probe_258140.py` (pid 800296), державший db+wal+shm. Это **устаревший probe-скрипт от релиз-проверки 2.58.140** (создан Oct 28 08:52), не входящий в unit — пережил `systemctl stop`. Снапшот консистентен (backup API). Probe **до сих пор работает на OLD** (проверено O4) — на замороженном fallback безопасен; решение об остановке — владельцу/PM (incidental, вне среза).
2. **`/tmp/oc_cut_*.sh` на NEW — очищены** (N1: 0 слева; скрипты этого окна самоудаляются в finally; строка в O4 — собственный скрипт текущего сеанса до его удаления).
3. **10-минутные root-сеансы на NEW (00:35/00:45Z) — КЛАССИФИЦИРОВАНЫ:** `/etc/cron.d/sysstat` (`5-55/10 * * * *` debian-sa1) — штатный сборщик статистики Ubuntu, к боту отношения не имеет.
4. **logOut wiping:** поведение локального bot-api задокументировано (кэш медиа удаляется, очередь/сессия-state сохраняется/пересоздаётся) — штатная семантика процедуры переключения, потери очереди нет.
5. **`?? .cache/`** в git NEW — untracked pip-кэш после старта, не данные (можно добавить в .gitignore позже, вне среза).

## 5. Секрет-гигиена

Все raw-логи санитизированы драйвером ДО записи: bot-token (вкл. имя каталога store → `<BOTID>`/REDACTED), DSN, DuckDNS token, пароли (литералы из deploy_commands.txt). Токен DuckDNS проверялся no-op-запросом (ip=текущий) ДО простоя; update-запрос G — из памяти драйвера, в печать не попал. Контрольный скан sanitized-логов: 0 остатков. Временный ключ миграции: создан на OLD, отозван на NEW (N5: authkey_lines=1, ключ владельца на месте), staging OLD удалён (O3).

## 6. Raw-evidence

`WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0d2c/temp-71fbb8076a/`: `cut2_driver.py` (pacing ≥62 c, парсинг креденшелов только в память, санитизация), `scripts/*.sh` (o1_recon2, n1_preflight2, o2_stop_snap2, n2a_install_key2, o2b_push2, n2_load2, o3_logout2, n3_start2, n4_start_bot2, n5_verify2, n6_final, o4_oldfinal), `raw/*.out.txt|*.meta.json` (все сеансы), `expected_final.json` (значения финального снапшота).

**Итог:** шаги 6–8 выполнены, все 9 строк VERIFY — PASS против финального снапшота; новый VPS — единственный production (SHA `5346ee76…`, 2.58.141), гэп 11 мин 21 с, данные без потерь, старый сервер — остановленный fallback. Готово к PM-байнду строк CUT-STEP6/7/8 + VERIFY; расширенная приёмка §7.1 — slice POST (по карте).
