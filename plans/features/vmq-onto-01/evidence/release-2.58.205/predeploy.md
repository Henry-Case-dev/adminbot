# Predeploy runbook — `2.58.205` (Slice D)

Кандидат: `release/vmq-slice-d-2.58.205`. База/откат: `2b419aa2` (`2.58.204`).
Схема: **47**, DDL **0**, миграций нет. Production-путь: `/var/www/admin_bot`;
SQLite: `/var/www/admin_bot/local_database.db`; каталог копий:
`/var/www/admin_bot/backups/` (не чистится).

## 1. Predeploy backup (до checkout/рестарта)

Существующая практика проекта — SQLite `.backup()` из **read-only** соединения
(`mode=ro`) с обязательным read-back копии. Один основной прогон, без
поллеров (fail2ban-дисциплина AGENTS.md).

```bash
cd /var/www/admin_bot
TS=$(date -u +%Y%m%dT%H%M%SZ)
DB=/var/www/admin_bot/local_database.db
BK=/var/www/admin_bot/backups/pre_deploy_258205_${TS}.db
df -k /var/www/admin_bot | tail -1          # свободное место
stat -c '%s %n' "$DB"                       # размер БД (+ -wal, если есть)
sqlite3 "file:${DB}?mode=ro" ".backup '${BK}'"
ls -l "$BK"
sha256sum "$BK"
sqlite3 "file:${BK}?mode=ro" \
  "PRAGMA integrity_check; PRAGMA user_version; SELECT count(*) FROM sqlite_master WHERE type='table';"
```

Ожидаемо: `integrity_check = ok`, `user_version = 47`, число таблиц совпадает
с прод-базой (прецедент `2.58.204`: 130), `sha256` записан в deploy-отчёт,
свободного места не меньше размера БД с запасом (прецедент: 43 GB свободно
при БД 3.29 GB).

**Fail-closed:** если `integrity_check != ok`, `user_version != 47` или копия
не читается — деплой не начинать; разбираться с копией, а не «повторить
рестарт». Имя копии: `pre_deploy_258205_<UTC>.db`.

## 2. Rollback

Цель: `2b419aa2` / `2.58.204` (deployed), schema **47**, DDL 0, данные не
меняются; restore БД не требуется (все изменения Slice D — чтения).

```bash
cd /var/www/admin_bot
git fetch origin
git checkout 2b419aa2
git rev-parse HEAD                    # 2b419aa2
systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz   # 200, version 2.58.204
```

Если обнаружено повреждение данных (не ожидается при DDL=0) — restore из
`/var/www/admin_bot/backups/pre_deploy_258205_<UTC>.db` по штатной процедуре
остановки unit'а; копия уже проверена read-back.

## 3. Postdeploy checklist (агенты, не владелец)

1. **Health:** `curl -fsS http://127.0.0.1:8000/healthz` → HTTP 200,
   `{"status":"ok","version":"2.58.205"}`; публичный `/healthz` — тот же
   version.
2. **Schema:** `PRAGMA user_version = 47`;
   `SELECT max(version) FROM schema_migrations` = 47; в journal строка
   старта `[database] migrations: start | current user_version=47 |
   pending=[]` (pending пуст, новых `migration v… applied` нет).
3. **Identity:** запустить deployed `identity.py` (существующий harness) →
   `code = verified_deployed`, `deployed_sha` = tip релиза,
   `version = 2.58.205`; `dirty = false`.
4. **Unit:** `systemctl show admin_bot -p NRestarts --value` = 0 (или без
   прироста после рестарта), `ActiveState=active`.
5. **Journal:** с момента рестарта — 0 `ERROR`/`CRITICAL`/`Traceback`;
   известные pre-existing WARNING (embedding 429/rotation) не считать
   регрессией, но перечислить.
6. **Settings/profiles:** снять pre/post snapshot существующим
   `harness/snapshot.py` (read-only): `bot_settings` count+digest и
   `chat_profiles` count+digest должны совпасть; ручная ревизия промпта
   сохранена (`rev:d31300ef35a0`, `sha256 ≈ 31d17506…`, `retired=false`,
   `origin=manual`), иначе — стоп и разбор.
7. **L1-наблюдение (после реальных ходов, один плановый read — без busy
   polling):** в durable-событии `mca_events` (`event_name =
   'direct_turn_context'`, `usage_json.l1`) посмотреть `memory_scope` и
   `response_act` для пяти формулировок: A1, A1P, P1, P2, P3. Пример
   read-only запроса:

```bash
sqlite3 "file:/var/www/admin_bot/local_database.db?mode=ro" \
 "SELECT ts, json_extract(usage_json,'$.l1.memory_scope'),
         json_extract(usage_json,'$.l1.response_act')
  FROM mca_events
  WHERE event_name='direct_turn_context'
  ORDER BY id DESC LIMIT 20;"
```

   Зафиксировать фактические значения. Если A1P исторический по смыслу, а L1
   выдаёт `memory_scope=auto` — это **L1/prompt finding** (дефект формулировки
   решения), а не повод вернуть словарь в retrieval; записать отдельной
   находкой. Дополнительно тот же ход виден в journal:
   `direct: rag block | memory_policy=… | replace_allowed=… |
   period_skipped=… | intent_source=…`.
8. **No owner QA:** все проверки выше выполняют агенты; владельцу не
   назначаются unit/integration/UI-прогоны.

## 4. Ограничения

- Это predeploy-план; сам деплой и живые прогоны — отдельный шаг DevOps после
  подтверждения вердикта на точный tip.
- `memory_scope` до первого реального хода после выката неизвестен
  (локальный LLM-ключ отсутствует, durable L1-плана в копии БД нет).
- Векторная нога `compat_not_proven`; TIME-07 — синтетический набор, не
  человеческая разметка. VERIFIED не заявляется.
