# Postdeploy runbook — 2.58.216 (VOICE-TRANSCRIPTION-RECOVERY-01)

**База:** production `f20645f13bbd742aae380596dd9ead52b5888a84` / `2.58.215` (rollback-цель — он же).
**Кандидат:** `release/p0-2.58.216`, content tip `faa2125c79c811d68ac8635be9f7e8532d477f70`, bump `APP_VERSION = 2.58.216`.
**Схема:** v47, MigrationStep 47/47, DDL 0 — миграций нет.
**Запрещено:** выполнять полный `tests/test_webapp_*.py` на сервере; оставлять временные файлы; трогать чужие данные.

## 1. Pre-deploy (30 секунд)

```bash
cd /var/www/admin_bot
git rev-parse HEAD; git status --porcelain | wc -l; grep -m1 '^APP_VERSION' config/settings.py
systemctl is-active admin_bot; systemctl show -p NRestarts admin_bot
curl -s localhost:<порт>/healthz        # фактический адрес сервиса
df -h /var | tail -1                    # свободное место до копии
cat .deploy/release.json 2>/dev/null    # ожидается 2.58.215 / f20645f13
python manage.py disk audit | tail -20
```
Ожидание: HEAD `f20645f13…`, dirty 0, `2.58.215`, unit `active`, health 200,
`release.json.version=2.58.215`.

## 2. Деплой и identity

```bash
cd /var/www/admin_bot
git fetch origin
git checkout release/p0-2.58.216      # или штатная ветка деплоя
git pull --ff-only
NEW_SHA=$(git rev-parse HEAD)
echo "NEW_SHA=$NEW_SHA"
python tools/release_manifest.py      # фактический checkout SHA
systemctl restart admin_bot
```

Проверить **факт**, а не намерение:

| Поле | Ожидание 2.58.216 |
|---|---|
| checkout | `git rev-parse HEAD` = зафиксированный `NEW_SHA`, dirty = 0 |
| product tree | совпадает с content tip `faa2125c7` (docs/evidence-коммиты продукт не меняют) |
| `APP_VERSION` | `2.58.216` |
| `.deploy/release.json` | `version=2.58.216`, `previous_sha=f20645f13…`, `previous_version=2.58.215`, `release_branch=release/p0-2.58.216` |
| health | `/healthz` = 200, JSON `version=2.58.216` |
| unit | `active`, `NRestarts` не растёт |

## 3. Backup и schema

```bash
python manage.py disk audit
python manage.py disk cleanup --apply        # deploy-пул keep=2 (2.58.206)
sqlite3 local_database.db 'PRAGMA user_version;'   # = 47
grep -c '^APP_VERSION' config/settings.py          # = 1
python - <<'PY'
import sqlite3
c = sqlite3.connect('local_database.db')
print(c.execute("select name from sqlite_master where type='table' and name in "
                "('smart_messages','message_revisions','task_jobs','mca_events')").fetchall())
print(c.execute("select count(*) from smart_messages where transcript_status='failed'").fetchone())
PY
```
Ожидание: свежий pre-deploy backup + daily/safety существуют, `user_version=47`,
DDL не выполнялся, таблицы на месте. После деплоя — `disk audit`, free space не
хуже pre-check.

## 4. Effective-конфигурация (что реально включено)

- В журнале старта: `[bot-api] mode=local source=session` (или `source=infra`);
  при расхождении — WARNING `mode mismatch` и явные `session`/`infra`.
  `session=cloud, infra=local` — выравнивать конфигурацию, не «переключать флаг».
- `TELEGRAM_LOCAL` непустой → локальный Bot API; функциональный
  `flags.download_enabled` endpoint **не** выбирает и остаётся отдельным полем.
- `python manage.py`-снимок/страница «Статус»: `local_api` = фактический режим,
  `download_enabled` — отдельное значение (оба должны быть согласованы с
  намерением).
- `flags.enable_voice_transcription` — включён в целевых чатах (effective, с
  учётом CHAT-override).
- Запись в каталог Bot API проверять фактическим `touch`+`rm` от uid 101, а не
  `test -w` (ACL даёт ложный `no`).

## 5. Replay трёх сохранённых объектов (read-only, без отправок)

Использовать существующий `replay_runner.py` из
`plans/features/voice-transcription-recovery-01/evidence/` в изолированном
`/tmp`-checkout задеплоенного кода; production-дерево не менять:

```bash
DIR=$(mktemp -d /tmp/voice-replay.XXXXXX)
git archive --format=tar HEAD | tar -x -C "$DIR"
ln -s /var/www/admin_bot/.env "$DIR/.env"
export TELEGRAM_API_FILES_DIR=/var/www/admin_bot/docker/telegram-bot-api
export DB_PATH=/var/www/admin_bot/local_database.db TMPDIR="$DIR/tmp"
cd "$DIR" && /var/www/admin_bot/venv/bin/python <path>/replay_runner.py
# cleanup: rm -rf "$DIR"; проверить /tmp/voice-replay.* = 0
```

Ожидание (как `replay-run3.json`): 3/3 `ready`, `revision=1`, тексты
**321 / 355 / 10** символов, `transcript_pending` не растёт, `failed` по этим
строкам = 0, повторные проходы — `memorize skipped`, `memory.calls=0`,
отправок в Telegram = 0. `file_unique_id` каждого объекта должен совпасть с
`smart_messages.media_ref` (у video_note `media_ref` пуст).

## 6. Живой входящий voice / video_note (если агент может отправить)

Отправить один voice и один video_note в тестовый чат (не в канал владельца).
Ожидаемые терминальные состояния:

| Сценарий | `transcript_status` | `transcript_reason` | Ответ в чат |
|---|---|---|---|
| успех | `ready` (rev 1) | пусто | обычная реакция/ответ |
| отказ скачивания (локальный 400/нет файла) | `failed` | `download_get_file_local_read_failed` (или `download_<stage>_<class>`) | ровно один нейтральный ответ; **нет** повторного pending |
| пустой облачный файл | `failed` | `download_cloud_download_provider_error` (retryable) | один ответ, без ложного «готово» |
| ASR-сбой | `failed` | `stt_failed` | один ответ, без дубля |
| старый pending (>lease) | `unavailable` (при чтении) | `stale_pending` | «расшифровка недоступна» |

Проверить: в `smart_messages` по новым строкам нет `pending`, revision не
растёт на повторе, `message_revisions`/`mca_source_refs` не получают лишних
строк; Writer-блок `<voice_transcripts>` содержит текст (reply на голосовое).

Диагностика/чекап: при `stale_pending` ожидается degraded с
`reason_code=transcript_stale` и `stale_reason=stale_pending`; свежий `pending`
деградацией **не** считается.

## 7. Rollback

```bash
cd /var/www/admin_bot
git checkout f20645f13bbd742aae380596dd9ead52b5888a84
grep -m1 '^APP_VERSION' config/settings.py   # = 2.58.215
systemctl restart admin_bot
curl -s localhost:<порт>/healthz             # version=2.58.215
sqlite3 local_database.db 'PRAGMA user_version;'   # 47
```
Данные не сбрасываются: транскрипты, revision и журналы остаются; DDL/миграций
нет. После rollback `release.json` описывает последний деплой (2.58.216) —
identity отката подтверждается `git rev-parse HEAD` и `/healthz`, а не этим
файлом. Причина отката — только реальная регрессия; известные F1/F3 (UX) и F2
(наблюдаемость) откат не оправдывают.
