# Deploy checklist — 2.58.240 (UR-C-CLOCK) — для DevOps

Ассемблирование: `plans/features/unified-reply/evidence/release-2.58.240/assembly.md`.
Версия: **2.58.240**. Deploy на момент этой записи **не выполнялся** (Builder
не имел SSH/deploy-мандата). Все шаги ниже — шаг DevOps.

## 0. Что деплоится

| Поле | Значение |
|---|---|
| Branch | `release/unified-reply-ur-c-clock-2.58.240` |
| **Deploy SHA (content RC)** | **`f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9`** |
| Rollback SHA | `6123a1469bbfe1019d0a1ecdb65c383988444655` (2.58.239) |
| Review | `review-2026-11-25.md` r2 = APPROVED_FOR_RELEASE_PREPARATION |
| DDL / schema | DDL 0; SQLite schema 48; PG DDL 0 |
| Флаги / UI | новых флагов 0; `web/*` не изменён |

Evidence-коммит (этот) содержит только docs и не меняет код; деплоить нужно
именно `f7e20e15d`. Если checkout идёт по ветке, после `git pull --ff-only`
выполнить `git checkout f7e20e15d` (detached) и зафиксировать HEAD в manifest.

## 1. Predeploy (без изменений в проде)

1. Один recon-коннект (~15 с таймаут), один основной прогон; fail2ban:
   без повторов и параллельных логинов.
2. Свободное место: `df -h /` и `python manage.py disk audit` (read-only).
   Текущую версию/HEAD зафиксировать: `git -C /var/www/admin_bot rev-parse HEAD`
   (ожидается `6123a1469…`).
3. Predeploy backup штатным механизмом, **keep=2** (текущий rollback +
   предыдущий), после бэкапа — проверить размер и целостность (sha256/размер),
   не оставлять копий сверх keep.
4. Проверить, что на сервере нет незакоммиченных правок:
   `git -C /var/www/admin_bot status --porcelain` (пусто/только `.deploy`).

## 2. Deploy

```bash
cd /var/www/admin_bot
git fetch origin --tags
git checkout release/unified-reply-ur-c-clock-2.58.240   # или origin/…
git pull --ff-only
git rev-parse HEAD                                        # должен быть f7e20e15d… (или evidence-tip с тем же кодом)
python tools/release_manifest.py --deployer devops-2.58.240
sudo systemctl restart admin_bot
```

Если деплоится release-tip с evidence-коммитом — обязательно проверить, что
`git diff f7e20e15d..HEAD` не содержит `services/`, `handlers/`, `config/`,
`web/`, `tests/` (только `plans/`), и записать фактический HEAD в manifest.

## 3. Postdeploy — обязательные проверки

| Проверка | Команда/критерий |
|---|---|
| Health | `curl -fsS https://<host>/healthz` → 200 |
| Версия | `/api/status` → `version = "2.58.240"`; UI/лог не обязательны |
| Identity | `.deploy/release.json` существует, `deployed_sha` = фактический HEAD, `version = 2.58.240`, `previous_sha = 6123a1469…`, `previous_version = 2.58.239`, `dirty_tracked = false` |
| Service | `systemctl show admin_bot -p NRestarts -p ActiveState`; ActiveState=active, NRestarts без роста после старта |
| Schema | `PRAGMA user_version` = 48; PostgreSQL DDL 0 (миграций нет) |
| Логи | `journalctl -u admin_bot --since "-10min" -p warning` — без новых `Traceback`, `chat_clock`-ошибок, `KeyError: window_local`; нет `web_error` из-за новых payload-полей |
| Настройки | существующие per-chat/global override не сброшены (в частности `limits.chat_timezone`, `limits.summary_timezone`, `SUMMARY_TIMEZONE`, `GOODMORNING_TZ`) |
| Диск | `python manage.py disk audit` и `python manage.py disk cleanup --apply` (deploy-пул keep=2); свободное место после деплоя |
| Мусор | удалить собственные временные файлы деплоя; production не свалка |

## 4. Postdeploy-наблюдение (агентское, не owner-QA)

1. **D5 наблюдаемость.** В логах присутствуют записи часов с
   `module/step/chat_id/timezone/as_of_utc/config_version/clock_included` для
   summary supervisor (sync/stream/dedicated) и youtube; для tool-пути YouTube
   `clock_included=false` (seal не протекает).
2. **D4 user-facing.** В фактических запросах поиска/веба/YouTube ровно один
   блок `<Chat_Time_Context>` (по логам/диагностике, без чтения приватного
   текста в evidence — только счётчики/поля).
3. **Context-diagnostics.** На `CONTEXT_CAPACITY`/fallback: `[CAPACITY]` не
   появляется при достаточном окне; sealed-блок либо целиком, либо снят
   (`fallback_clock_dropped`).
4. **`URC-CLOCK-N2` (важно для прода).** Передача `chat_id` в `llm.generate`
   включает per-chat BYOK/budget-резолв: при настроенном BYOK или исчерпанном
   per-chat бюджете поиск/веб/YouTube/сводка могут вернуть `NoApiKeyForChat`
   вместо global-ключа. Проверить effective config (allow_global/BYOK/бюджеты
   затронутых чатов) и первый реальный прогон этих маршрутов. Дефолтная
   конфигурация (без BYOK, allow_global=true, бюджет не исчерпан) — поведение
   прежнее.
5. **`URC-CLOCK-R2-A`.** Для чата с legacy/`GOODMORNING_TZ` поясом суточный
   image-лимит сбрасывается по тому же поясу, что и локальные сутки ответов
   (контрактная цель R1): сверить `image_day`/`image_next_reset` в
   диагностике для такого чата.

## 5. Rollback (при регрессии)

```bash
cd /var/www/admin_bot
git checkout 6123a1469bbfe1019d0a1ecdb65c383988444655
python tools/release_manifest.py --effect rollback --deployer devops-2.58.240
sudo systemctl restart admin_bot
```

- Code-only; DDL/миграций/флагов/данных нет, откат данных не требуется.
- После rollback: `/healthz` 200, `/api/status` version `2.58.239`,
  manifest `effect=rollback`, `deployed_sha=6123a1469…`.
- Учесть fail2ban-политику: один rollback-прогон, без быстрых повторных
  подключений.

## 6. Что НЕ обязан делать deploy

- Owner QA/наблюдение — запрещено как гейт; проверки §3–§4 выполняют агенты.
- Пересборка тестов/ревью на сервере не требуется; RC уже проверен локально
  (§5 в `assembly.md`).
