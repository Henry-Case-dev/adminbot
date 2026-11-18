# Postdeploy runbook — 2.58.217 (QRNG-RECOVERY-01)

**Кандидат:** `release/qrng-2.58.217`, content tip `b6c9bb0bdec0f26ee72a3b7ab54c0a19f26610a0`, `APP_VERSION = 2.58.217`.
**Статус:** REVIEW; runbook выполняется только после независимого одобрения и штатного деплоя. В этой сборке production не затрагивался.

## 0. Перед деплоем

- Убедиться, что ветка/кандидат одобрены; деплой — штатный (`git pull --ff-only` + `systemctl restart admin_bot`), без force.
- SSH: один recon-коннект с коротким таймаутом; при закрытом порте — пауза ≥22 мин (fail2ban), не долбить. HTTP-проверки (`443`, `/healthz`) от бана не зависят.
- Снять deploy-бэкап существующим механизмом (deploy_backup keep=2) до миграции. Свободное место проверить заранее; полные копии БД не накапливать.

## 1. После рестарта — базовое

1. `GET https://<prod>/healthz` → 200; версия/identity.
2. `git rev-parse HEAD` в production checkout = фактический deployed SHA; `git status --porcelain` пуст (dirty=false).
3. Схема: `PRAGMA user_version` = **48**; в `PRAGMA table_info(mca_random_batches)` есть nullable `config_fingerprint TEXT` и `external_ref TEXT`.
4. `python manage.py disk audit` (read-only) + `python manage.py disk cleanup` (dry-run; `--apply` по штатной политике keep=2). Свободное место в норме.
5. Журнал: нет ошибок миграции/старта; строка `migration v48: random_batches.config_fingerprint added` (или no-op на уже мигрированной БД) и `migrations: complete | user_version=48`.
6. Production-настройки/ключи не сброшены: существующие значения чатов/глобала на месте (только заводской PRNG-дефолт для новых установок — false; сохранённое `true` не перезаписывается).

## 2. Read-only проверки QRNG (без платных IBM jobs)

Выполнять только чтением API/БД/страницы; никаких POST, кроме явно указанного безопасного draft-check, и никаких IBM job.

1. **Реестр провайдеров — ровно 3 id:** `ibm_quantum`, `anu`, `lfdr`; Lizaonair отсутствует. В `/api/status.random.providers` — три записи, без четвёртой.
2. **Селектор:** `random.primary_provider` = `ibm_quantum` по умолчанию (или сохранённое владельцем значение), `random.fallback_enabled` = true по умолчанию, `random.fallback_order` = `["anu","lfdr"]` (или сохранённый порядок). Эффективный порядок начинается с primary; per-chat запись этих ключей → 422.
3. **Резерв и provenance:** `random.provider_reserve`/`reserve_remaining` считают только партии действующего fingerprint (+NULL-легаси); партии другого ключа видны как quarantined и не расходуются. `last_batch.config_matches` — boolean, `config_fingerprint`/`key_fingerprint` наружу **не** отдаются.
4. **Draft-check `deposited=false`:** при ручной проверке чернового ключа (если владелец её инициирует) ответ содержит `deposited=false`, число строк `mca_random_batches` не растёт; квота провайдера при этом расходуется. Ключ не эхо-ится; в evidence — только last4/prefix.
5. **LfDR live GET:** один публичный GET `https://lfdr.de/qrng_api/qrng` (без ключа) → 2xx и hex-тело; никаких повторов при ошибке, зафиксировать статус/длину без значений. Если сеть production закрыта — честно `not_checked`, не выдавать за успех.
6. **IBM paid jobs = 0:** по журналу/учётным данным провайдера нет созданных jobs; IBM в UI — «не настроен»/`external_wait`, не зелёный. Проверить отсутствие записей job-id/`external_ref` IBM за окно наблюдения.
7. **UI:** страница «Модули → Случайность» показывает ровно 3 провайдера, селектор, эффективное состояние (`Сейчас используется`), резерв, статус, ключи, диагностику; draft-подсказка прямо говорит, что проверка тратит квоту провайдера и **не** зачисляется в рабочий резерв. На `#/ai/llm` нет `keys.random_*`; «Время ответа и защита» — последняя группа, 180/360 на месте. 390/320 — одна колонка, без горизонтального скролла.
8. **Журнал:** нет `config_fingerprint`/ключей в логах; ошибки провайдеров классифицированы, без сырых тел; cooldown ручных проверок работает (повторное нажатие в окне не делает квотный запрос).

## 3. Откат

См. `rollback.json`: code rollback на `5046090c7` (2.58.216), рестарт, проверка identity/health. Схема может остаться 48: две nullable-колонки инертны, старый код их не читает, runner не падает. Данные не откатываются. Полный DROP COLUMN — только по отдельному решению, не в штатном откате.

## 4. Evidence после деплоя

- Зафиксировать deployed SHA, версию, schema=48, результат health/identity/disk.
- Приложить компактные результаты read-only проверок (числа/коды/булевы, без значений ключей и сырых тел).
- Не оставлять на production временные файлы, копии БД, скриншоты и исследовательские артефакты; удалить свои временные файлы после проверки.
