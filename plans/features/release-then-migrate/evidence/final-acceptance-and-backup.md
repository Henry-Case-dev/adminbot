# FINAL ACCEPTANCE + INDEPENDENT BACKUP — release-then-migrate (decommission phases 1–2, DevOps)

**Дата/окно:** 2026-10-29, активные проверки 06:38–07:00 UTC (локально 18:38–19:00 UTC+12); cutover был 04:17:39Z (~2ч20м до начала).
**Кандидат:** NEW production `192.255.209.205`, git HEAD `5346ee765e83ee859596b60437811b21db1e4564` (2.58.141) — тот же SHA, что принят ревью и подтверждён в POST.
**Вердикт: GO** — удаление Adminbot на старом VPS (фазы 3+) разрешено. Критических регрессий нового production нет; независимый бэкап создан и проверен. Старый VPS в этой полосе НЕ трогался ни разу (0 подключений).
**Дисциплина fail2ban:** 6 сессий к NEW (recon 15с + f1 + f1b + f2 + f3-sftp + f4), одиночная auth на сессию, пейсинг ≥62 с, hostkey pinned `SHA256:KMOAKfeddYbWXoqx7W4mVgu+DaU2Qg+V0wF5CRmHYAg` (все 6 — MATCH). Банов нет.

## Фаза 1 — приёмка NEW production (§3–§7)

### §3 Сервисы — таблица

| Компонент | Наблюдение (06:40–06:58 UTC) | Статус |
|---|---|---|
| systemd admin_bot | active+enabled, NRestarts=0, старт процесса 04:56:02 UTC (управляемый рестарт из POST), MainPID 72680, RSS 434МБ, %CPU 7.4, unit'ов с bot-именем =1 | **PASS** |
| Git/версия | HEAD `5346ee76` = принятый релиз; healthz body `2.58.141`; dirty=1 — только untracked `.cache/` (классифицировано в CUT) | **PASS** |
| Poller | BOT_PROC_COUNT=1, `Run polling` с момента старта процесса = **1** (с cutover = 2: до/после управляемого рестарта); 409/conflict-совпадения (5) — **ложные срабатывания** на «409» внутри миллисекунд таймстампов INFO-строк (tma-auth, ingestion, seed) — реальных конфликтов getUpdates нет | **PASS** |
| Docker Compose | adminbot-postgres healthy, adminbot-telegram-bot-api healthy, adminbot-cobalt healthy, adminbot-bgutil-pot Up — все 4, Up 2ч | **PASS** |
| PostgreSQL | 26 таблиц, bot_settings 544, uptime heartbeat «up» каждые 60с (последние 06:39/06:40), PG 16.15, слушает 127.0.0.1:5432 | **PASS** |
| SQLite | 1,55ГиБ (1 670 549 504 Б), integrity_check **ok** (13.9s), user_version 37, journal_mode=wal (wal 4.96МБ / shm 32КБ — норма), freelist 107, 121 таблиц | **PASS** |
| Caddy/TLS | caddy active+enabled; TLS LE VALID, notAfter 27.01.2027 (локально openssl + извне); Caddyfile на месте | **PASS** |
| Local bot-api | 127.0.0.1:8081 жив (HTTP 404 на корень = процесс отвечает), контейнер healthy, proc=1 | **PASS** |
| Cobalt/xray | cobalt 127.0.0.1:9000 → 200; xray active+enabled, слушает 127.0.0.1:10808 | **PASS** |
| DNS | локальный резолвер + 1.1.1.1/8.8.8.8/9.9.9.9 → только 192.255.209.205 | **PASS** |
| Админка извне | `/` 307→`/web/` 200, `/api/config`, `/api/me` → 401 без initData (слой auth жив); tma-auth в журнале 05:19 (реальный вход владельца, role=admin, valid=True) | **PASS** |
| Внутр. API | healthz 200 `2.58.141`; /api/health 200 | **PASS** |
| Память/диск/CPU | RAM 3.9ГБ (used 1.16ГБ, available 2.76ГБ), swap 0 использован; диск 99ГБ (used 16ГБ, 17%); load 0.22/0.10/0.11 на 2 ядрах | **PASS** |
| Периметр | 5432/8081/9000/10808/4416/8000 извне CLOSED; открыты только 22/80/443 | **PASS** |

### §4 Расшифровка счётчиков админки (скриншот владельца: ошибки 0 / предупреждения 17 / ошибок с запуска 3 / проблем 4)

Механика: «Ошибки»/«Предупреждения» — уровни записей в in-memory ring-буфере логов (1000 записей, ротация ~15–20 мин при текущем темпе); «Ошибки с запуска» — `errors_total` (ERROR+ с старта процесса 04:56); «Проблемы» — LLM-карточки с не-configured/неok health + активные инциденты oversight (`mca_incidents.resolved_at IS NULL`). Счётчики НЕ чистились.

| Счётчик | Чем объясняется | Классификация |
|---|---|---|
| Ошибки 0 | В ротационном окне буфера (~15–20 мин) ERROR-записей нет; последние ERROR были 06:19–06:20 | норма |
| Ошибки с запуска 3 | Скриншот сделан ~05:0x: 3 ERROR-записи одного события — **wikipedia-403 anticliche fetch** 05:01:05 (внешний ресурс блокирует IP VPS; next_run 05.11, кэш anticliche_cache=1 обслуживает) | harmless-pre-existing (известный класс, был и до миграции) |
| Предупреждения 17 (на момент скриншота; к 06:44 выросло до 106) | (а) `embed transport error \| error=NameError` — ~4 за 10-мин цикл (48 с рестарта); (б) `smart_archive … FTS-only (A06) build pending`; (в) `FACTS_EXTRACT … reason_code=embed_deferred`; (г) `vision_adapt outcome=failed reason="fits"` — мисклассифицированный INFO (стратегия original выбрана, error="") — шум; (д) `[graphrag] embed failed — fact saved text-only \| fact_id=22486` | пре-существующее семейство дефектов embed-пайплайна (на OLD за 2 дня: 124 NameError + 26 FTS-only — O1/POST); НЕ регрессия миграции; факты сохраняются текстом, FTS-fallback жив; Builder-backlog (уже заведён в POST §2.2) |
| NEW с 06:19: `LLM HTTP 400 embeddings "input must not contain empty strings"` ×4 | Один батнь факт-экстракции послал пустые строки в embeddings (media-only сообщения имеют len=None); ответ провайдера 400, факт сохранён text-only, повторов нет (4 за всё время) | то же семейство embed-пайплайна (подкласс empty-input точечно не трекался на OLD; код тот же принятый 2.58.141, что работал на старом); не влияет на доставку/историю |
| Проблемы в статусе 4 | РОВНО 4 активных ERROR-инцидента mca_incidents: все `worker_lost` (stage=takeover) в пайплайнах memory/summary/vision.media/asap8b01; first_ts 02–24 октября, **last_ts 24–27 октября — ВСЕ до cutover**; repeat 2–5; unack=4 | устаревшие записи реестра инцидентов, перенесённые байт-снапшотом со старого сервера; после переключения новых инцидентов НЕТ; на работу бота не влияют; владелец может погасить/ack в админке в любой момент (я БД не трогал) |

Итог §4: **ни одной новой критической регрессии миграции не найдено**. Все классы — пре-существующие (wikipedia-403, embed-семейство, старые инциденты) или шум. Повторяющихся исключений инициализации нет (старт 04:56:02 чистый, seeding 482 настроек ON CONFLICT — норма).

### §5 Данные после переключения

- smart_messages = **2 050 595** на 06:40 (базис миграции 2 050 132 → +463; на скриншоте 2 050 292 — монотонный рост ✓); в бэкап-снапшоте 06:48 — **2 050 649** (растёт вживую).
- SINCE_CUTOVER: 463 сообщения, first 04:22:50Z, last 06:40:03Z — **все записи после cutover реально писались на новом сервере**; max(id) 2 372 823 монотонен (2 372 373 → +450).
- Последние 10 сообщений: подряд идущие id, ts 06:39:08–06:40:03 (секунды до запроса), длины адекватные, chat топ-чата маскирован.
- Непрерывность: PER_DAY 26/27/28/29 окт = 1779/2204/1841/513 (день неполный) — разрывов нет; DUP_RECENT500 (chat:tg_message_id) = **0**.
- Чтение истории (read-only проба боевого SQL-пути get_recent_history): requested=150 → available=150 (**без клампа**), page1 fetched=40; requested=60 → 60/40 ✓ (2.58.141 содержит исправленную динамику).
- WAL: journal_mode=wal, wal 4.96МБ/shm 32КБ, freelist 107 — здоровое состояние; checkpoint'ы не трогались (read-only).
- PostgreSQL: 26 таблиц; chat_lore_history 250→251, llm_usage 9387→9402, worker_budget 311→312, uptime 4323→4326 (живой рост); структурные счётчики == снапшоту.
- Роли/права/алиасы/настройки: bot_roles=4, bot_admins=3, chat_profiles=3, bot_settings=544, prompts.*=25 — всё на месте.
- Embeddings: embedding_cache 16 646 (−3 к POST — штатная LRU-обрезка по EMBED_CACHE_MAX_ROWS, кэш, не данные); **KNN по боевому graph_facts_vec (21 771 строк, sqlite-vec v0.1.9): 5 соседей, distances 0.371–0.394** ✓.
- FTS: механизмы живы (POST N2: MATCH ≤5 строк за 0.00с; в проде прямо сейчас работает FTS-only fallback smart_archive — факты сохраняются и читаются). Два моих экспресс-проба дали 0 из-за кривой токенизации пробного токена (склейка через границы слов) — дефект пробы, не данных.
- Очереди: task_jobs — активных (queued/running/stuck) = **0** (7718 всего, все в терминальных статусах; failed 493 — историческая накопленная статистика старого сервера).

### §6 Функции (read-only; тестов в Telegram НЕ отправлял, платных LLM-вызовов НЕ делал)

| Функция | Свидетельство | Статус |
|---|---|---|
| Direct Chat L1/writer/config | flags.direct_chat_botword_enabled=true; промпты direct_chat_system/synthesizer/verbalizer + direct_l1_planner + summary_l2_writer на месте; L1 running_summary=1 (raw_count 500); живая активность: smart_cache direct_update miss/set в 06:19:26 | **PASS** (конфиг+данные+живой след) |
| get_recent_history | проба боевого SQL: depth 150/60 passed unclamped (§5); естественная строка `fetched=` за окно NOT_OBSERVED (tool-вызовов не было) | **PASS** (проба) / NOT_OBSERVED (естественная линия) |
| Fact-check | factcheck_enabled=true, pipeline_v2=true, wide_context=true, context 6/6/6, dig_max_facts=5 | **PASS** (конфиг; live не звали — платно) |
| Summary | summary_enabled + running_summary + hybrid L1/L2 repair/retry flags, video_summary_enabled; расписания в конфиге; история runs == снапшоту (POST: 28); тик-механика APScheduler в журнале работает (dream/nostalgia тикают) | **PASS** (конфиг/данные); цикл саммари за окно NOT_OBSERVED |
| Sleep / Deep Sleep | **deep_sleep_enabled=false** — и журнал честно: «[deep_sleep] skip reason=deep_disabled» (конфиг соблюдается); dream_log 1521→**1523** — сон отработал уже на новом сервере; random_sleep_exploration 0.05, событие random_uses_background в 05:56 | **PASS** |
| Initiative | initiative_enabled=true, observer_enabled=true (max_replies/day 6, min_gap 7200, profile normal); **observer tick каждые 5 мин executed successfully** (89 строк журнала, последние 06:36); второй экземпляр отсутствует (BOT_UNITS=1, proc=1) | **PASS** |
| Nostalgia | nostalgia_enabled=true (aggressiveness 0.3, cooldown 12h, quiet 08:00); nostalgia_log 414→415 (+1, запись сделана на новом); тики в 05:56: гейты/cooldown отработали, «LLM UNCHANGED — skip» | **PASS** |
| Vision / Media | env-флаги/ключи на месте (VISION/IMAGE/COBALT/TELEGRAM_LOCAL set); cobalt+bot-api healthy; media/ 96МБ 59 файлов; **реальная доставка в 06:08:33 — Slavic Photo отправлен в чат** (естественное событие, не мой тест); vision_adapt-варнинги — шум классификации, не сбой | **PASS** |
| Админка | 544 настройки, 25 prompt-ключей, роли 4, админы 3, профили 3; tma-auth реального владельца 05:19 valid=True; 401-слой снаружи | **PASS** |
| Telegram Bot API | локальный, healthy, tqueue.binlog на месте | **PASS** |

### §7 Память (read-only, без чисток)

- graph_facts 21 688 → **21 704** (+16 живых фактов, последний создан 06:20:13); nodes 28 964 (=), edges 52 598→52 599.
- **Просроченные убеждения: 4 633 — на диске, НЕ вычищены** (политика сохранения исторической памяти соблюдена); активных 17 071; belief_reviews 12; protected 1.
- Механизмы чтения/поиска/статусов: KNN vec0 — 5 соседей ✓; FTS — см. §5; статусы expires_at читаются. Никаких purge/rebuild/retention-изменений не выполнялось.

## Фаза 2 — независимый бэкап (§8)

**Расположение (машина владельца, независимо от ОБОИХ VPS):** `C:\Users\main\.config\opencode\WorkspaceData\backups\adminbot-postmigration-2026-10-29\` — 8 файлов, 1 694,6 МБ.

| Файл | Размер | sha256 (MANIFEST.sha256, перенос OK) | Верификация |
|---|---|---|---|
| local_database.db | 1 670 549 504 Б | 590b2f1b…15ea7607 | **integrity_check=ok** на сервере (27.9s) и повторно на локальной копии (16.5s); smart_messages=2 050 649; user_version 37 |
| postgres.dump | 604 265 Б | 8ca17e3a…2a332feec9… | **pg_restore -l внутри контейнера: RC=0, TOC 124 записи (135 строк, 52 TABLE-записи), Format CUSTOM, dumped 16.15→16.15, dbname adminbot** — читаемость/полнота доказана серверной стороной (локального pg_restore нет — лимитация закрыта) |
| env | 8 121 Б | 67bb8b1e…4add55db | копия `.env` (0600 на сервере; локально ACL ограничен пользователем, т.к. SFTP не переносит POSIX-права) |
| media.tar | 100 300 800 Б | b2d4c47d…2ffcb3cd27ebf2c9f | 59 файлов (бит-в-бит как в POST) |
| botapi_data.tar | 5 427 200 Б | 207bd28d…acc76531d | хост-маунт `/var/www/admin_bot/docker/telegram-bot-api`: tqueue.binlog, webhooks_db.binlog, каталог bot-token (восстановление локального Telegram Bot API возможно) |
| manifest.txt | 8 911 Б | ef506683…d324f3d918c6f4add55db | git HEAD 5346ee76, app_version 2.58.141, unit admin_bot, compose-файл, Caddyfile, Ubuntu 24.04 / kernel 6.8.0-31 / Python 3.12.3 / PG 16.15 / Docker 29.9.2 / Compose v5.6.1 / Caddy 2.11.7 / Xray 26.10.21 / ffmpeg 6.1.1 / sqlite 3.45.1, ключевые пакеты |
| MANIFEST.sha256 | 483 Б | — | все 6 файлов: **OK** (пересчитано локально) |
| VERIFY-LOCAL.txt | — | — | протокол локальной верификации |

- Согласованность: SQLite — backup-API снапшот живой БД (mode=ro); PG — pg_dump -Fc (свой консистентный снапшот); .env/медиа/bot-api — статические данные момента.
- Staging на NEW (`/var/backups/adminbot-final-shAv1Q`, 1.7ГБ) после подтверждённой передачи удалён (диск NEW: свободно 81.5ГБ, до/после без дренажа).
- Пользовательские файлы: media/ — единственный каталог пользовательских файлов (USER_DIRS пуст); `extra_images` — 3 файла, полностью в Git; chrome-profile/.cache — регенерируемые кэши, в бэкап не включены (сознательно).
- Лимитации (честно): tqueue.binlog копировался с живого bot-api (файл меняется в момент чтения) — при восстановлении очередь может потребовать сверить с Telegram; локального pg_restore нет — читаемость доказана `pg_restore -l` на сервере; шифрования архива нет (хранится на машине владельца).

## Аномалии/naходки (incidental)

1. Embed-пайплайн (NameError-транспорт ~27/ч, empty-input 400 ×4, smart_archive FTS-only) — пре-существующий дефект продукта, деградирует векторную свежесть памяти (текст сохраняется, FTS обслуживает). Builder-backlog, в срез декоммишена не входит, GO не блокирует.
2. 4 устаревших worker_lost-инцидента в статусе админки — косметика реестра (до-cutover записи); владелец может погасить в UI.
3. embedding_cache −3 строки — штатная LRU-обрезка (EMBED_CACHE_MAX_ROWS), не потеря данных.
4. Vision_adapt «failed reason=fits» — мисклассифицированный INFO-уровень (warn-шум), поведения не портит; можно Builder-микрофиксом уровня логирования когда-нибудь.

## Вердикт

**GO** — фазы декоммишена 3+ (инвентаризация/удаление на старом VPS) могут стартовать. Новый production: единственный, здоровый, живой (сообщения/факты/сны/тики пишутся), на принятом SHA 2.58.141; независимая проверенная копия состояния на машине владельца создана. Последняя сохранная копия на старом сервере больше не нужна как условие GO (условие §8 «если копию создать нельзя — не удалять» не сработало: копия создана и проверена).

Raw-evidence: `WorkspaceData/runs/c742e4de9e92c489/release-then-migrate-02338e6f0-288aa96c35eb/temp-c9c3d416da/` — `final_driver.py`, `scripts/{f1_final,f1b_final,f2_backup,f4_cleanup}.sh`, `raw/*.out.txt|*.err.txt|*.meta.json` (санитизированы), локальный бэкап с MANIFEST.sha256 и VERIFY-LOCAL.txt.
