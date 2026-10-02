# deployment.md — post-asap4-corrective-pass (prod 2.58.46)

Feature: `post-asap4-corrective-pass` · Risk R3 · **Статус: VERIFIED**
Дата: 02.10.2026 (UTC) · Исполнитель: @DevOps

## 1. Binding и авторизация

- Review: **Approved for delivery** (round 2 re-gate T-4504), release-blocking: 0.
- Reviewed-Commit: `34ba7d886d6e99a44bc803a91fa197a3030b6e36` (HEAD на момент ревью) — совпал с локальным HEAD до коммитов.
- **WTH re-measure (до release-prep):** `4ccd48bf163e54512cca72a817b2cd62b66c7298e38ef6ef5be01c1331ed2195` — воспроизведён **байт-в-байт** по 15 файлам манифеста review (формула: SHA-256 от конкатенации `"путь хеш\n"`, UTF-8, backslash-пути).
- Spec: spec.md отсутствует намеренно (corrective pass, указание владельца); контракт — `design-fix.md` SHA-256 `7e53d8046194a52f23fb39051aafcbab15c9ba1fc8716f855a95baa5fd44bc67` — сверён, MATCH. (Поле `spec_hash` в workflow-state несёт маркер предыдущей фичи `ab9dec9451cdd6a0` = spec AB9DEC94 asap-4 — реликвия оркестратора, к биндингу pass'а отношения не имеет; авторитетен review.md.)
- Drift при коммите: **ровно 1 манифест-файл** (`config\settings.py` — version-pin hunk release-prep), WTH после bump `bdde9f95f1c5e5818ba3d05f057903589ab84b9eb7068df70c72bf49e78ed838`; остальные 14 файлов манифеста байт-в-байт (конвенция release-prep предыдущих раундов).

## 2. Release prep

- APP_VERSION `2.58.45 → 2.58.46` (`config/settings.py`, версия-цепочка комментария) + README.md (заголовок «Версия»).
- Свип version-пинов: 23 py-теста (`assert APP_VERSION == "2.58.45"` → `"2.58.46"`) + 4 js-теста (regex `2\.58\.45` → `2\.58\.46`) + F8-meta переиздана генератором (`python tools/gen_param_registry_round1025.py`; `--check` EXIT=0, реестр 488, Δ каталога=0; в meta обновились только APP_VERSION + HEAD). Исторические паритет-ссылки «бит-в-бит 2.58.45» в services/тестах pass'а не тронуты (так и задумано).
- Полный pytest **после свипа**: **10838 passed / 2 failed** (337s, detached-джоба) — оба failed = known pre-existing round1026 `forbidden_paths_out_of_diff`/`_vs_baseline` (те же 2, что в review-прогоне; вне скоупа). py_compile settings.py OK. R17-скан диффа и журнала: 0 секретов.

## 3. Коммиты и деплой

- FEAT: `ddc24ff` — `fix(round1030): corrective pass — embedding quota kind-aware parking + resume backoff + disk retention policy (APP_VERSION 2.58.46)` (36 файлов: services/embedding_control_plane.py, services/graphrag_rebuild.py, config/settings.py, tools/disk_retention.py, docs/deploy-disk-retention-t4506.md, тесты 2 файлов + свип пинов + F8-meta + README).
- DOCS: `fe6b5db` — RCA/design-fix/disk-audit/tasks/evidence/review + full_audit_results + ADR-1028-7 AMEND + request archive (10 файлов).
- Push: `34ba7d8..fe6b5db → origin/master` (github Henry-Case-dev/adminbot).
- Прод: `git pull --ff-only` на `/var/www/admin_bot` → HEAD `fe6b5db`; `tools/disk_retention.py` на проде SHA-256 `400f365d2ff6bd60c4716638cf0cd8343f307681124b60af41ba5ce3ba1f047d` — байт-в-байт из манифеста review.
- Рестарт: `sudo systemctl restart admin_bot` (NOPASSWD-правило) → **active (running) с 13:36:04 UTC, PID 3051854**.
- **ΔDDL = 0: `PRAGMA user_version` = 23 ДО и ПОСЛЕ** (проверено read-only). PG no-op.

## 4. T-4507 — retention install + первая чистка (до рестарта)

Установка: systemd-юниты недоступны — sudoers NOPASSWD покрывает только `systemctl {start,stop,restart,status} admin_bot` + `journalctl -u admin_bot` (проверено `sudo -n -l`); `sudo -n systemctl daemon-reload`/`tee /etc/systemd/system/...` требуют пароль → использована **санкционированная доком §3 альтернатива: cron от nik** (без sudo):

```
30 6 * * 1 cd /var/www/admin_bot && venv/bin/python tools/disk_retention.py >> /home/nik/adminbot-disk-retention.log 2>&1
```

(crontab до установки — пуст; лог в /home/nik — /var/log недоступен nik на запись. systemctl list-timers неприменим — см. §6.)

Первая чистка (dry-run → сверка с disk-audit §9 → `--apply`, построчный лог `/tmp/disk-retention-apply.log`):

- План dry-run = 5 кандидатов / 1.5 GiB — каждый путь ∈ whitelist-классам §9:
  - `local_database.db.bak.2026-09-15-0744` (+ `-shm` 32 KiB, `-wal` 0 B) — app_adhoc_db_baks >14д (724.4 MiB);
  - `/home/nik/backups/pre_mca_v19_20260929_052904.db` — db_anchor_backups, keep-2 (811.3 MiB);
  - `proxy.log.5` — rotated_logs >14д (10 MiB) — **unlink-failed: владелец headroom:headroom, у nik нет прав** (честное исключение; автоматика будет честно репортить ERROR по этому пути до смены владельца/прав — не критично).
- Отклонения от аудита §9 (объяснимы): `/tmp/pytest-of-nik` — candidates=0 (вычищен после аудита 02.10); `proxy.log.1–4` моложе 14д — вне плана, как и предписывал аудит; apt-классы (~0.30G) — не исполнены (требуют root, вне NOPASSWD); `migrate_history` (1.1G) — **исключён инструментом** (`owner_confirm_required`), решение владельца pending.
- **df ДО:** 18G used / 4.4G free (81%). **df ПОСЛЕ:** 16.5G used / 5.8–5.9G free (74%). **Освобождено: 1.5 GiB.**
- Защитный чеклист (R5-B-003) — всё на месте:
  - рабочая `local_database.db` (1.3G, живая запись) + WAL/shm;
  - `pre_migration_20261002_101544.db` (1.2G, root-owned);
  - якорь `pre_v21` = `/home/nik/backups_adminbot/local_database_20261001-080155_pre_v21.db` (1.2G);
  - суточный бэкап `/var/www/admin_bot/backups/local_database_20261002.db` (1.2G, v22, smart_messages=1 989 935 — read-back ok);
  - `media/` (96M), `.env` (600), `migrate_history/` (1.1G — не тронут).

## 5. T-4509 — прод-приёмка (факты)

1. **Health**: `GET :8000/healthz` → HTTP 200 `{"status":"ok","version":"2.58.46"}`; `user_version=23` (read-only SQLite); каталог не менялся (F8 CHECK OK 488, Δ=0).
2. **GraphRAG после рестарта** (journalctl + read-only SQLite):
   - `13:36:27 EMBEDDING_GENERATION_BUILD_START | index=graph_facts_vec | gen=1 | resumed=True` — **resume той же generation 1, НЕ пересоздана** (mca_embedding_index_generations: generation_id=2, generation=1, created_at 1790678362 — без изменений);
   - джоба `graph_facts_vec` — `paused_rate_limit`, checkpoint цел: `last_id=7640 / processed=6427` (вырос с 7608/~6395 на момент ревью — прогресс сохранён);
   - `13:36:27 embed rate limit | group=unknown | kind=spend | retry_after=None | cooldown_s=37712 | parked=1 | 429_last_10m=1` — **парковка сработала: горизонт до конца суток UTC + margin 300s** (next_allowed_at=1790985900 = (int(now)//86400+1)*86400+300), **счётчик 429 одинарный** (дедуп D4; до фикса задваивался → «59»);
   - в `task_jobs.result_ref` персистентный стрик: `quota_exhaust_streak=1, quota_kind_last=spend` (D2, переживает рестарт);
   - стартовая диагностика D3: `embedding pool rotation=none | group=unknown | keys=3 | hint=EMBEDDING_QUOTA_GROUP_LABELS` (WARN ≤1 — ровно 1 при старте);
   - **окно наблюдения 13:36:27 → 13:47+ (>10 мин): 0 повторных embed-запросов к охлаждённой группе** (было: 298 BUILD_START/4ч, ре-хит ~20с) — финальный скан в §7.
3. **Панель `/api/memory/embeddings`**: неавторизованный доступ → **401** (R17 admin-gate ✓). Поля панели верифицированы по источникам данных: `parked kind=spend est=utc_day_end` — в `embedding_quota_state.note` (SQLite, read-only); `rotation:none` + hint-лейбл — в стартовом WARN пула; `429_last_10m=1` — в rate-limit WARN. Аутентифицированный просмотр панели — за владельцем (прецедент T-4447–4449).
4. **Resume-after-reset — механика верифицирована, NATURAL RESUME pending**: провайдерский reset spend-класса ожидается к концу UTC-суток (~23:55 UTC 02.10); парковка НЕ ждёт его в окне приёмки — `resume произойдёт при next_allowed_at` подтверждён механически: гейты §68 удерживают paused с checkpoint, `next_allowed_at=1790985900` в обеих таблицах (job + generation), auto-resume по сроку — существующий контур (asap-4 VERIFIED 2.58.45). **Выход из FTS-only: PENDING NATURAL RESUME** — подтверждение по факту resume (checkpoint продолжит расти с 7640/6427; активация generation → векторный контур/KNN).
5. **Retention-расписание**: cron-запись установлена (еженедельно, пн 06:30 UTC); первый прогон — ручной `--apply` по процедуре §4 (до/после/освобождено — §4); еженедельные прогоны — dry-run-отчёты в `/home/nik/adminbot-disk-retention.log`.
6. **Ошибки/секреты**: 0 `ERROR|CRITICAL|Traceback` в журнале с момента рестарта (161 строка, скан); R17-скан журнала — 0 хитов; в логах только group-id/счётчики/alias — без ключей.
7. **Kill-switches**: `EMBED_QUOTA_KIND_PARKING_ENABLED`, `EMBED_RESUME_BACKOFF_ENABLED` — кодовые дефолты ON, env-оверрайдов на проде НЕТ (grep имён по `.env` — 0 вхождений; значения не читались). Предыдущие 11 флагов asap-4 без изменений (Δenv=0).

## 6. Ограничения (честно)

- systemd timer/logrotate НЕ установлены: sudoers NOPASSWD не покрывает `daemon-reload`/запись юнитов/logrotate.d — использован cron-вариант дока §3 (функциональный эквивалент расписания; `systemctl list-timers` неприменим, расписание верифицируется `crontab -l`). Если владельцу нужен systemd-вариант — команды §3 дока исполняются под root за 2 минуты.
- `proxy.log.2–5` (порция ~40M) не удаляются: моложе 14д (правило) + владелец `headroom` (unlink-failed на proxy.log.5). Досчитаются автоматически после 14д при доступности на unlink; иначе — разовая ручная guarded-команда под root.
- apt-позиции аудита (~0.30G) не исполнены (требуют root) — осознанно, вне автоматики.
- Аутентифицированный просмотр панели embeddings — за владельцем (R17; у DevOps-сессии нет admin-креденшелов, и они не запрашивались).

## 7. Финальный скан окна наблюдения (10+ мин)

Заполняется по факту финального скана — см. evidence.md секцию T-4509.

## 8. Rollback

- Soft: `EMBED_QUOTA_KIND_PARKING_ENABLED=0` + `EMBED_RESUME_BACKOFF_ENABLED=0` + рестарт (OFF = бит-в-бит 2.58.45 — парковка/бэкофф выключаются, прежний кулдаун ~20с); retention: `ADMINBOT_DISK_RETENTION_ENABLED=0` (no-op) либо снятие cron-строки.
- Cold: `git revert` до `34ba7d8`/`b5eaecd`; БД не требует отката (ΔDDL=0, v23 остаётся — старый код её читает).
- Restore-якоря неприкосновенны: pre_v21, pre_migration_20261002, суточный бэкап (§4).
