# MAC-AVATAR-01 — живая проверка на выкаченном SHA

Релиз **2.58.181**, выкаченный коммит **`92070d0eda83674fd386324d55ba12a28b5e3837`**
(ветка `release/2.58.181`), база прод-линии **`721bab10`** (2.58.180), схема БД **47**
(без шага миграции). Проверено 10.11.2026, сервер `vps159032-gqg`, сервис `admin_bot`
active с 10:10:25 UTC.

## Что вошло в выкат (байт-идентично одобренному)

| Коммит | Роль |
|---|---|
| `a2721908` | правило доступа `/api/avatar` (403 до Bot API) |
| `c2255690` | `Cache-Control: private` + `Vary: X-Telegram-Init-Data` |
| `fc641f6c` | только тесты |
| `30cd8564` | MAC-DEF-01 (`user_has_permission`) |

Черри-пик на `721bab10` прошёл без конфликтов. Дельта против базы — 32 файла:
продуктовые только `web/api/avatars.py`, `web/api/deps.py`; плюс
`config/settings.py` (версия), `plans/docs/param-registry-round1025.meta.md`,
28 тестовых файлов. `services/permissions.py` байт-идентичен
(`e20d46ebf1591bfa4f1c9df622d6babcb33d7ccb`).

## Живые наблюдения (реальные значения)

Авторизованные запросы — **на уровне владельца** (role `admin`,
`role_type=global_admin`). Подписанный `initData` собран на самом сервере из
`API_TOKEN` по HMAC-схеме Telegram (`WebAppData` → `auth_date`/`user`/`hash`);
токен не покидал сервер, чужая личность не подделывалась, использован только
собственный owner-профиль.

| # | Запрос | Результат |
|---|---|---|
| 1 | `GET /api/avatar/user/<чужой id>` с owner-initData | **200**, 8 673 байта, `Cache-Control: private, max-age=86400`, `Vary: X-Telegram-Init-Data` |
| 2 | То же через публичный HTTPS (Caddy) | **200**, 8 673 байта, заголовки сохранены (`via: 1.1 Caddy`) |
| 3 | `GET /api/avatar/chat/-1002661910336` с owner-initData | **200**, 83 144 байта, те же заголовки |
| 4 | `GET /api/avatar/user/<id>` **без** initData | **401** |
| 5 | `GET /api/admins` **без** initData | **401** |

Строка журнала статуса запроса зафиксирована:

```
[api-status] method=GET path=/api/admins status=401 user=- reason=missing_init_data
```

То есть неаутентифицированный запрос действительно записывается middleware
`web/request_status.py` (одна строка на non-2xx под `/api/*`).

## Отказы и здоровье

* `permission_denied` за 25 минут после рестарта: **0** — новых ложных 403 на
  затронутых путях нет.
* Уровень `ERROR/CRITICAL`: **0**.
* `/healthz` → `{"status":"ok","version":"2.58.181"}`.
* Два `sqlite3.OperationalError: database is locked` в 10:09:52 и 10:09:57 —
  от **старого** процесса (`pid 3640633`) во время снятия 2-ГБ снапшота БД,
  до рестарта; после рестарта (`pid 3691656`) не повторялись. Это артефакт
  операции снапшота, а не дефект кода.

## Чего не проверял live

* Отказ `403` для **постороннего** Mini App-пользователя на проде: в проекте
  реальных посторонних аккаунтов нет (3 записи в `bot_admins`: 2 × moderator,
  1 × admin/global_admin). Само правило 403 до Bot API и «прогретый кэш не
  отдаёт чужое» доказано Reviewer'ом на базе и кандидате тестами
  `tests/test_avatar_access_scope.py` (см. `mac-avatar-01-review.md`).
* Fail-closed без lore/PG на проде не воспроизводим без выключения источника —
  покрыто тестами кандидата.

## Откат

`cd /var/www/admin_bot && git checkout release/2.58.180 && systemctl restart admin_bot`
(тот же коммит `721bab10`). Схема не менялась (47), поэтому откат БД не требуется;
снапшот `predeploy-258181.db` (2 091 036 672 байта, `PRAGMA quick_check=ok`,
`user_version=47`) снят до рестарта на случай неожиданностей.
