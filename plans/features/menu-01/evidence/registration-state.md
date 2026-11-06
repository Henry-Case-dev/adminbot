# MENU-01 — состояние регистрации Mini App и готовность deep link

Собрано: 2026-11-07 08:46 (+12:00). Режим: только чтение. Никаких сообщений в Telegram,
никаких изменений BotFather, настроек прода, перезапусков. Использованы только
read-only методы Bot API (`getMe`, `getChatMenuButton`) и публичный HTTP (`t.me`, `/healthz`).

## Классификация

**`CONFIRMED_PRESENT`** — Main Mini App бота зарегистрирован, deep link
`https://t.me/<bot>?startapp` резолвится в запуск приложения.

Регистрация **не является** блокером MENU-01 и не требует действий владельца.
Формулировки «не проверено» к факту регистрации не применяются.

## Сырые наблюдения

### 1. Bot API (`getMe`), токен не печатается (только факт наличия, len=46, формат валиден)

```
{"id": 8802473181, "is_bot": true, "first_name": "Базовичок",
 "username": "PERMsoc_bot", "can_join_groups": true,
 "can_read_all_group_messages": true, "supports_inline_queries": true,
 "has_main_web_app": true, ...}
```

`has_main_web_app: true` — официальное поле User из `getMe`:
«Optional. True, if the bot has a main Web App. Returned only in getMe.»
Источник: https://core.telegram.org/bots/api/types/user (проверено 2026-11-07).

### 2. Bot API (`getChatMenuButton`, без параметров → дефолтная кнопка меню)

```
{"ok": true, "result": {"type": "web_app", "text": "Админка",
                        "web_app": {"url": "https://admin-bot.duckdns.org/web/"}}}
```

Кнопка меню — именно `web_app` Mini App (не `default`, не `commands`, не `url`).

### 3. Публичные страницы `t.me` (без логина, обычный GET)

| URL | `<title>` | Кнопка действия | protoUrl |
|---|---|---|---|
| `https://t.me/PERMsoc_bot` | `Telegram: Launch @PERMsoc_bot` | **Start Bot** | `tg://resolve?domain=PERMsoc_bot` |
| `https://t.me/PERMsoc_bot?startapp` | `Telegram: Launch @PERMsoc_bot` | **Open App** | `tg://resolve?domain=PERMsoc_bot&startapp` |

Разница принципиальна и объективна: обычная ссылка отдаёт «Start Bot» +
`tg://resolve` без `startapp`; ссылка с `startapp` отдаёт «Open App» +
`tg://resolve?...&startapp`. Ошибок/«app not found»/404 в разметке нет.
Официальный формат подтверждён документацией:
«A bot's main Mini App can also be opened in the current chat by direct link in the
format `https://t.me/botusername?startapp`» — https://core.telegram.org/bots/webapps
(раздел «Launching the main Mini App», проверено 2026-11-07).

Ограничение этого признака: публичная страница доказывает существование и резолв
ссылки, но не доказывает, что клиент реально открыл приложение и получил `initData`.

### 4. Подтверждение владельца (BotFather)

Сообщение владельца 2026-11-07: Menu Button и Main App — Enabled, оба указывают на
существующий Mini App `https://admin-bot.duckdns.org/web/`, Main App — Fullscreen.
Совпадает с п.2 (`web_app`-кнопка меню ведёт на тот же URL). Direct Link / именованное
приложение не требуется и не запрашивается.

### 5. Прод: что реально работает сейчас

```
GET https://admin-bot.duckdns.org/healthz → 200 {"status":"ok","version":"2.58.161"}
```

Прод-кандидат (из plans/workflow_state.md) — `a563ee31` (release/2.58.161).
Проверено по локальному объекту:

```
git show a563ee31:handlers/menu.py | grep deep_link  → пусто
```

То есть в проде сейчас **старый** group-ветка `/menu` — только текстовая подсказка
«Меню бота доступно в личке…», без URL-кнопки. Кандидат `14400b73` продом **не**
содержится (`git merge-base --is-ancestor 14400b73 a563ee31` → нет).

## Что именно меняет кандидат `14400b73`

Диф к прод-линии (кандидат ответвлён от `8bb2800f`, в `refs/heads` не влит):

* `config/settings.py:190-194` — три новых ключа:
  `MINI_APP_DEEP_LINK_MODE` (str, default `""`),
  `MINI_APP_REGISTRATION_CONFIRMED` (bool через `_env_bool`, default `False`),
  `MINI_APP_SHORT_NAME` (str, default `""`).
* `handlers/menu.py:55-68` — `_group_deep_link()`: ссылка строится только если
  `MINI_APP_REGISTRATION_CONFIRMED` истинно (`:57`); режим `main` → `https://t.me/<bot>?startapp`,
  режим `named` (+ валидный `short_name` по `^[A-Za-z0-9_]{1,64}$`, `:34`) →
  `https://t.me/<bot>/<short_name>`; иначе пустая строка.
* `handlers/menu.py:94-101` — group/supergroup: есть ссылка → URL-кнопка
  «Открыть мини-приложение» (`_GROUP_BUTTON_TEXT`, `:29`); нет → честная подсказка.
* `handlers/menu.py:80-90` — private-ветка не изменена (та же `web_app`-кнопка с `WEBAPP_URL`).

Вывод: **одного деплоя недостаточно**. При пустых/ложных флагах после деплоя в
группах останется честная подсказка (это корректное поведение по MENU-01.7).

## Проверка кандидата (тесты, не моки вместо предмета)

Worktree `menu-01` (`14400b73`, существующий, созданный ранее):

```
handlers.menu.__file__ = ...\menu-01\handlers\menu.py   (deep-link функция есть)
python -m pytest tests/test_menu.py -q  →  18 passed in 3.04s
```

Ключевые проверяемые утверждения (`tests/test_menu.py` в кандидате):

* :88-103 — `main` + confirmed → `url == "https://t.me/Example_bot?startapp"`, `web_app is None`, текст «Открыть мини-приложение»;
* :106-121 — `named` → `https://t.me/Example_bot/memory_map`, домен приложения отсутствует в URL;
* :125-139 — невалидные `mode`/`short_name` → откат на подсказку (нет `reply_markup`);
* :46-62 — без флагов группа получает подсказку без клавиатуры, `@PERMsoc_bot` берётся из `bot.me()`;
* :32-43 — private сохраняет `web_app`-кнопку с `settings.WEBAPP_URL`.

## Server-side `initData`: реальная проверка (file:line)

Ядро — `web/api/deps.py`.

| Требование | Реализация | Файл:строки |
|---|---|---|
| Подпись HMAC-SHA256 по спецификации | `safe_parse_webapp_init_data(token=settings.API_TOKEN, init_data=...)`; `ValueError` → HTTP 401 | `web/api/deps.py:96-103` |
| Сама HMAC-проверка (не заглушка) | aiogram 3.31.0 `check_webapp_signature`: `secret = HMAC(b"WebAppData", token)`, `data_check_string` из отсортированных пар без `hash`, `hmac.compare_digest` | `aiogram/utils/web_app.py` (установленный пакет) |
| Обязательный `hash` | нет `hash` → `False` → 401 | то же + `deps.py:98-103` |
| Пользователь обязателен | `parsed.user is None` → 401 «no user in init data» | `web/api/deps.py:104-109` |
| Свежесть `auth_date` | `age = now - auth_date`; `max_age` из `TMA_AUTH_MAX_AGE`, default 86400; превышение → 401 «init data expired» | `web/api/deps.py:110-120`, `31-49` |
| Кто «я» — только из подписанного `user.id` | роль/права из `parsed.user.id` | `web/api/deps.py:121-134` |
| Привилегии по праву | `requires_permission` → 403 | `web/api/deps.py:182-195` |
| Глобальный админ | `requires_global_admin` → 403 | `web/api/deps.py:198-229` |
| `initDataUnsafe` не авторизует | фронт отправляет только `Telegram.WebApp.initData` в `X-Telegram-Init-Data` | `web/app.js:1858-1866`, `:3` |
| `initDataUnsafe` вообще не используется для прав | единственное упоминание — диагностический флаг `hasInitDataUnsafe` в политике фуллскрина | `web/static/fullscreen-policy.js:381-391` |
| `chat_type` / `chat_instance` не дают прав | в прикладном коде `chat_instance` не читается вообще (grep по `*.py`: только `tools/_build_menu_map.py`, `tools/_bind_menu_rows.py` — плановые скрипты); `chat_type` в ACL не участвует | repo grep 2026-11-07 |
| `chat_instance` ≠ `chat_id` | chat-scope берётся из `chat_admins` по `(user.id, chat_id)`; `chat_id` — только селектор из `X-Chat-Id` | `web/api/access.py:142-162`, `services/roles.py:180-198` |
| URL/payload (`startapp`, `start_param`) не авторизуют | бэкенд не читает `start_param`/`tgWebAppStartParam` (grep пусто); фронт deep-link `start_param` явно выключен | `web/app.js:1853`, grep |
| Транспорт `initData` (header/query/body) — это один и тот же подписанный blob | query/body фолбеки проходят ту же валидацию подписи | `web/api/deps.py:85-97` |

Дополнительно: у всех 208 маршрутов `web/api/*.py` в блоке декоратор+подпись присутствует
auth-dependency (`get_tma_user` / `tma_context` / `requires_permission` /
`requires_global_admin`); маршрутов без неё не найдено (статический скан 2026-11-07).

Остаточный риск, не проверяемый статически: `TMA_AUTH_MAX_AGE=0` отключает проверку
свежести (`tests/test_webapp_deps.py:404-410` это фиксирует). В прод-env значение не читалось
(нет доступа без SSH, а SSH-коннекты ограничены fail2ban-политикой проекта) — дефолт
безопасный (86400). Это пункт деплой-проверки ниже, а не продуктовая правка.

## ACL-матрица: что доказано, что нет

Доказано тестами и кодом (не моками вместо предмета):

| Утверждение | Доказательство |
|---|---|
| Нет `initData` → 401 | `tests/test_webapp_deps.py:133-142` |
| Битая подпись (чужой/неверный токен) → 401 | `tests/test_webapp_deps.py:120-131` |
| Валидная подпись без `user` → 401 | `tests/test_webapp_deps.py:209-228` |
| Просроченный `auth_date` (>24 ч) → 401 | `tests/test_webapp_deps.py:144-156`, `:390-395` |
| Границы свежести (env 10 c, мусор→default, 0→выключено) | `tests/test_webapp_deps.py:397-417` |
| Админ (wildcard) проходит привилегированный маршрут | `tests/test_webapp_deps.py:245-256` |
| Не-админ: разрешённое право — 200, `access` — 403 | `tests/test_webapp_deps.py:258-274` |
| Неизвестный Telegram ID: чтение — 200, привилегированный POST — 403 | `tests/test_webapp_deps.py:276-299` |
| Роль в чате — только из `chat_admins`; `X-Chat-Id` не даёт прав | `web/api/access.py:142-162`, `services/roles.py:180-198` |
| Не-админ с `X-Chat-Id` чужого чата → 403; мусорный → 422 | `tests/test_mca12_stories_round1046.py:601-612` |
| Обычный user с `X-Chat-Id` чата получает restricted-скоуп, админ — chat-скоуп | `tests/test_mca10a_random_source_block_c_round1037.py:552-562` |
| DM-скоуп только при `chat_id == telegram_id` | `services/roles.py:176-179`, `tests/test_dm_access.py:112+` |

Чего в тестах **нет** (честный список пробелов, ничего не добавлялось):

1. Нет теста, который подаёт валидный `initData` с `chat_type=group` + `chat_instance`
   и проверяет, что роль/права совпадают с private-запуском (сейчас это следует
   только из кода: `deps.py:121-134` использует исключительно `parsed.user.id`).
2. Нет теста, что `chat_instance`/`chat_type`/`start_param` в теле запроса не могут
   расширить chat-scope (полностью покрыто косвенно: эти поля нигде не читаются).
3. Нет теста на parity «открытие из группы не расширяет доступ к данным группы»
   именно для TMA-запуска (chat-scope покрыт на уровне API-маршрутов, см. выше).
4. Вся матрица устройств (`MENU-01.9`) — только реальный запуск, тестами не заменяется.

## Чек-лист деплоя (выполняет DevOps; флаги сам не менял)

1. Влить и выкатить кандидата `14400b73` (сейчас он не в прод-линии; прод = `a563ee31`/2.58.161,
   где group-ветка ещё старая). Обычный релиз проекта.
2. В прод-env добавить ровно два значения:
   * `MINI_APP_REGISTRATION_CONFIRMED=true` (`_env_bool` принимает `1/true/yes/on`, регистр не важен);
   * `MINI_APP_DEEP_LINK_MODE=main` (Main App подтверждён; `named` не нужен).
   `MINI_APP_SHORT_NAME` **не задавать** — он относится только к named-режиму.
3. Не задавать `TMA_AUTH_MAX_AGE=0` (иначе отключается проверка свежести `auth_date`).
   Значение по умолчанию (86400) — корректное.
4. После рестарта: `/menu` в группе → URL-кнопка «Открыть мини-приложение» с
   `https://t.me/PERMsoc_bot?startapp`; в личке — прежняя `web_app`-кнопка.
5. Побочный мелкий пробел (несрочно): `.env.example` не документирует три новых ключа —
   стоит добавить при следующей правке окружения.

## Влияние на строки требований

* **MENU-01.4** — регистрация теперь подтверждена объективно (`has_main_web_app: true`,
  `web_app`-кнопка меню на тот же URL, публичный `?startapp`-резолв в «Open App»),
  плюс подтверждение владельца. Регистрационная часть закрыта; клиентский переход и
  получение `initData` относятся к runtime-матрице (MENU-01.9/01.10).
* **MENU-01.9** — статически/тестами доказуемо: подпись, свежесть, `user`, отсутствие
  авторизации по `chat_instance`/`chat_type`/payload, chat-scope через `chat_admins`,
  401/403-поведение. Не доказуемо без реального запуска: Android/Desktop,
  private/group/supergroup, admin/не-admin в реальном клиенте, факт получения `initData`
  клиентом. Эти ячейки остаются `NOT_TESTED`, пока нет наблюдения.
* **MENU-01.10** — не может быть `VERIFIED`: прод пока исполняет старый код, кнопки в
  группе нет, реального `startapp`-запуска с валидным `initData` не наблюдалось.
  После деплоя + флагов нужен один реальный запуск (достаточно любого клиента) с логом
  `[tma-auth] valid=True` и проверкой ACL для не-админа.

## Действия владельца

Не требуются. Регистрация подтверждена, BotFather-настройки трогать не нужно,
Direct Link не нужен. Всё остальное — деплой и проверки на стороне агентов.
