# Chat Lore Management — исследование (AdminBot)

**Дата:** 2026-09-05
**Скоуп:** вывести захардкоженный лор чата (`services/chat_lore.py`) в редактируемый раздел Mini App
«Лор чатов» (admin/moderator), мульти-чат, авто-генерация лора, ремаппинг chat_id.
**Стек:** Telegram-бот (Python/aiogram, SQLite-память `protected_facts`/`smart_messages`/`graph_facts`),
PostgreSQL `bot_settings`/`bot_roles`/`bot_admins`, FastAPI `/api/*`, TMA (Vue 3), RBAC v2
(`services/permissions.py`), `ConfigCache`.
**Статус:** исследование; решение по вариантам — за владельцем (чекбоксы ниже).

---

## 1. Текущее состояние — на пальцах

- Лор конференции (чат `-1002661910336`, «джаббер-конфа с нулевых, Пермь») — **константа в коде**:
  `CHAT_LORE_2661910336` + `CHAT_LORE_TARGET_CHAT_ID = -1002661910336` (`services/chat_lore.py:20-31`).
- `ensure_chat_lore(db)` (`services/chat_lore.py:36`) вызывается на старте (`bot.py:196-199`) и
  **идемпотентно** пишет текст в два места SQLite-памяти:
  1. `protected_facts (chat_id, user_name=NULL, fact)` — «чат-уровневый факт»; `get_protected_facts`
     (`services/database.py:1584-1603`) отдаёт его ПЕРВЫМ и всегда в `<protected_facts>` контекста
     direct_chat (`_build_protected_facts`, `direct_chat_service.py:625-641`). Не режется бюджетом, не
     удаляется `/forget`.
  2. `graph_facts (origin='user_memory', expires_at=NULL, weight=1.0)` — вечная строка для RAG/FTS.
- Если админ поправит текст в БД — на следующем старте **хотфикс-`ensure` ничего не делает**
  (проверка по точному тексту, строка есть → skip). Но поменять текст можно только ручным SQL.
- Всё остальное (bot_settings, роли, админы) — в PostgreSQL; редактирование — через Mini App
  (Vue 3 + FastAPI `/api/config`), секции-вкладки, права admin/moderator (RBAC v2:
  `sections`/`params`/`actions`, `wildcard`). Прецедент похожей задачи уже был:
  `plans/features/user-aliases-admin/` (алиасы `limits.summary_aliases` → KV-редактор в «Лимитах и Модулях»).

### Ограничения текущей модели
1. Лор — один, на один чат, зашит в код (нужен редеплой для правки).
2. Нет мульти-тенантности: бот в новом чате не знает, «кто этот чат» и у кого там права.
3. Нет авто-генерации и версий/истории правок.
4. Хрупкий момент: runtime-id супергруппы `-1002661910336` ≠ id экспорта `2661910336` — при
   переезде чата id меняется и текущий инжект просто не сработает на новом id.

---

## 2. Что говорят исследования (2024–2026), вопрос за вопросом

### 2.1 Per-chat память / «server profile / lore»: как делают другие
- **Паттерн «один документ/строку на гильдию/чат»** — доминирующий. У Discord-ботов данные
  естественно партиционированы по guild: `guild_id` — естественный первичный ключ
  (`_id`/PK), конфиг хранится вложенными объектами, обновление — апсерт одной строки
  [guden.tr]. Наш `protected_facts` уже так устроен (UNIQUE по chat_id), но «профиль чата» как
  единая сущность (описание + флаги + владельцы) отсутствует.
- **1:1 «Server → ServerSettings»** (отдельная таблица настроек с внешним ключом на сервер) —
  типовой SQL-вариант [discord-bot-template; Resonance `discord_server_configs`], в том числе с
  `config_metadata JSONB`.
- **Пользовательские боты памяти**: ChatGPT/аналоги хранят «профиль» отдельно от истории и дают
  юзеру смотреть/редактировать его в UI (человек правит сам, модель дополняет). «Server Lore» как
  продуктовое понятие (определи «личность и правила сервера», бот вплетает в каждый ответ) —
  продаёт целый класс Discord-ботов [Contexta]. Вывод: лор — это **контент-сущность,
  управляемая человеком**, а не только технический факт.

### 2.2 Авто-генерация лора (LLM-выжимка) — как делать без деградации
- **Incremental / running summary** (стандарт 2024–2026): не «пересказать всё заново», а
  «обновить существующий саммари дельтой новых сообщений». Элементы: буфер новых сообщений
  (chunk window ~10–20 сообщений / 15–25K токенов), merge-промпт (явные секции + жёсткий
  токен-бюджет + правило «устаревшее перезаписать, противоречия пометить»), периодическая
  «полная пересборка» (full rewrite / deep-clean) против накопленного дрейфа формата
  [agenticskillset; arxiv 2308.15022 — «рекурсивная память»].
- **Фоновая асинхронная конденсация** не ложится на пользовательский путь (MT-OSC, ACL 2026:
  Condenser + «Decider», до −72% токенов, без видимой латентности) [MT-OSC].
- **Российский/репо-прецедент уже есть**: «бегущий конспект» окна чата при заполнении ≥0.8
  от 500 сообщений (`summary_memory.py:935-997`, fire-and-forget `COMPRESS_PROMPT`). Авто-лор —
  тот же механизм, но на уровне «профиль чата».
- **Анти-галлюцинации и анти-деградация** (консолидировано из источников):
  - источник для генерации — только реальные строки памяти (smart_messages окна, protected_facts,
    graph_facts), никакого свободного «вспоминания»;
  - размер ограничен (токен-бюджет в промпте и пост-проверка длины);
  - генерация не должна молча перезаписывать ручной текст: флаг `auto_enabled` OFF после ручной
    правки = «руки человека важнее»;
  - **версионирование**: старое значение уходит в историю (archive), роллбэк возможен;
  - каждый авто-прогон помечается `source='auto'` + `generated_at` + (опц.) диапазон источников,
    админ видит «текст сгенерирован ботом», а не «магия»;
  - метрика деградации: рост размера без роста содержания → периодическая полная пересборка.
- Рекомендуемая модель для нас: **периодическая «выжимка» + merge со старым текстом**, триггер —
  порог новых сообщений (например, ≥N за сутки) или крон раз в сутки в тихом чате, плюс ручная
  кнопка «Сгенерировать сейчас».

### 2.3 Права и мульти-тенантность
- Общий паттерн: **глобальные админы + per-guild (per-chat) модераторы**. Назначения ролей
  скоупированы гильдией: один юзер — админ в чате А и никто в чате Б; проверки на каждый вызов
  [warden permissions; phantom team roles — роли per-guild с `.view`/`.edit` на каждый модуль
  дашборда, union-суммирование, история изменений с before/after].
- Discord: встроенная иерархия (владелец → админ → модератор), у бота поверх — свои «кастомные»
  permission-слои. Telegram-эквивалент «владельца чата» получить можно (getChatMember на момент
  входа / my_chat_member-апдейты), но надёжнее явный список.
- Для нас: RBAC v2 уже гранулярный (`section.*`, `param.*`, `action.*`). Не хватает **измерения
  «chat scope»** — какая роль к какому чату применима. Минимально: новая секция/действие
  (`section.chat_lore` или `action.edit_chat_lore`) + таблица per-chat админов.

### 2.4 Переезд чата / смена chat_id
- **Факт Telegram**: при апгрейде обычной группы в супергруппу (или пересоздании) id меняется,
  старый id «умирает» навсегда. Бот получает service-message с полями `migrate_from_chat_id` /
  `migrate_to_chat_id`; при попытке писать в старый — ошибка с `parameters.migrate_to_chat_id`
  (aiogram: `TelegramMigrateToChat`; PTB: `ChatMigrated`) [PTB PR#1684; conferbot; pcraft; SO].
  Новые id супергрупп ≥ 52 бит и начинаются с `-100` → хранить в 64-бит/BIGINT, не в 32-бит.
- **Best practice переноса данных**:
  1. Ловить миграцию по service-message, хранить пару old→new (таблица `chat_links`);
  2. ленивая нормализация на чтении (если chat_id в таблице есть old — резолвить через chat_links)
     **или** активная миграция (UPDATE всех строк с old на new в одной транзакции);
  3. код, который получает `TelegramMigrateToChat`, обновляет id и повторяет запрос;
  4. в нашем случае данных «на чат» много (`protected_facts`, `smart_messages`, `graph_facts`,
     `bot_replies`, `user_prefs`, настройки) — **перепривязка профиля** должна чинить либо ссылку
     профиля, либо физические id всех таблиц. [conferbot рекомендует: хранить записи «по
     внутреннему id», чтобы миграция была одним UPDATE].
- Вывод: нужна сущность «профиль чата» + ручная кнопка перепривязки в UI (когда авто-ловля
  миграции не сработала: бот не был в чате в момент переезда) и/или авто-обработчик
  service-message.

### 2.5 UI-паттерны раздела
- Карточка/строка чата (id + заголовок + превью лора + бейдж источника: «вручную»/«авто») →
  выбор → редактор.
- Длинный текст: многострочный textarea с счётчиком символов (лимит, например, 2–4 тыс.), в TMA
  это обычный `<textarea>`; кнопки «Сохранить».
- Чекбокс «Автоматически формировать лор» (аналог тумблеров bool в существующих секциях
  настроек). Включение/выключение меняет поведение воркера, а не удаляет текст.
- Поле «Привязанный chat_id» (read-only + кнопка «Перепривязать…» → модалка «было/станет»:
  подтверждение с предупреждением «все данные старого id будут считаться данными нового»).
- Кнопка «Сгенерировать сейчас» (ручной запуск выжимки) — видна при auto ON.
- **История правок/audit**: версии (кто, когда, откуда — рука/бот), просмотр diff между
  версиями, роллбэк. Прецедент интерфейса «последние изменения с before/after» — phantom team
  roles [phantom].
- Подтверждения на деструктив: перепривязка и перезапись ручного текста авто-версией.

### 2.6 Хранение: JSON-ключ на чат vs таблица vs документ-стор
| Подход | Плюсы | Минусы |
|---|---|---|
| **Ключи в `bot_settings`** (`chat_lore.<chat_id>.text` = JSONB, `.auto_enabled` = bool…) | мгновенная интеграция с `/api/config` и TMA-рендером категорий; горячий фикс-механика уже работает | key-value = нет типизации per-chat; история правок = только `updated_at` без `updated_by`; нет «профиля» как единой строки; список чатов = сканирование ключей с префиксом; конкурентная правка длинного текста = lost-update |
| **Реляционная таблица профилей** (`chat_profiles`, chat_id PK) + таблица истории | пер-чат сущность, типы, FK, updated_by/updated_at, версии, дешёвый список чатов; перепривязка = UPDATE одной строки; согласуется с «guild doc»-паттерном | отдельная DDL/миграция; для TMA-UI нужен новый эндпоинт (не через /api/config) |
| **Документ-стор (Mongo и т.п.)** | гибкость схемы | новый инфраструктурный компонент ради одной сущности — оверкилл |

Практика ботов (2024–2026) — реляционная «server settings»-таблица (или 1 JSONB-строка на
guild) + отдельная аудит/история. Для нашего масштаба: **таблица профилей в PG** (там же, где
bot_settings/роли — единый источник конфигурации) с SQLite-памятью как «исполнителем» (лор
физически доставляется в контекст как сегодня).

---

## 3. Целевая модель (общая рамка всех вариантов)

1. **Профиль чата** — единая сущность: `chat_id`, текст лора, флаг `auto_enabled`, источник
   (`manual|auto`), метаданные (кто/когда создал и правил).
2. **Инжект в контекст** остаётся «как сейчас» (чат-уровневые факты первыми в `<protected_facts>`,
   не режутся бюджетом), но текст берётся **из профиля**; `ensure_chat_lore`-хотфикс умирает.
3. **Секция Mini App «Лор чатов»**: список чатов → редактор (textarea + чекбокс auto + поле
   chat_id + «Перепривязать» + «Сгенерировать сейчас» + история версий).
4. **Авто-лор воркер**: периодическая/по-порогу LLM-выжимка из `smart_messages` окна +
   `protected_facts`/`graph_facts`; пишет в историю; перезаписывает текущий текст только при
   `auto_enabled=true`.
5. **Мульти-тенантность**: глобальные admin/moderator (RBAC v2) правят все чаты; **per-chat
   админ-лист** правит только свой чат.
6. **Переезд**: авто-перехват Telegram-миграции + ручная перепривязка в UI (маппинг old→new,
   перенос настроек/профиля).

---

## 4. Варианты архитектуры — выбирает владелец

### [ ] Вариант A — таблица `chat_profiles` в SQLite (минимально, «рядом с памятью»)

Одна новая таблица в SQLite-БД памяти (там же, где `protected_facts`):

```sql
CREATE TABLE chat_profiles (
    chat_id     INTEGER PRIMARY KEY,          -- runtime id (-100…)
    lore_text   TEXT NOT NULL DEFAULT '',
    auto_enabled INTEGER NOT NULL DEFAULT 0,  -- 0 = только ручное
    source      TEXT NOT NULL DEFAULT 'manual', -- manual | auto
    updated_by  INTEGER,                      -- telegram_id (NULL = бот)
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE chat_lore_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    lore_text   TEXT NOT NULL,
    source      TEXT NOT NULL,
    changed_by  INTEGER,
    created_at  REAL NOT NULL
);
```

- **API**: `GET/PUT /api/chat_lore/{chat_id}` (+ `GET .../history`) — пишет в SQLite-файл через
  существующий `DatabaseService`.
- **UI (TMA)**: раздел «Лор чатов», textarea + чекбокс + история.
- **Права**: глобальный RBAC: `action.edit_chat_lore` (или секция `chat_lore`) admin/moderator;
  per-chat списка нет.
- **Миграция с хардкода**: стартовая миграция из константы `CHAT_LORE_2661910336` в
  `chat_profiles`; инжект контекста читает профиль вместо `ensure_chat_lore`; дубль в
  `protected_facts`/`graph_facts` удаляется или помечается (чтобы не было двойного текста).
- **Авто-генерация**: воркер делает merge-выжимку окна `smart_messages` в `lore_text`, при
  `auto_enabled=1`; версия уходит в `chat_lore_history`.
- **Ремаппинг**: `UPDATE chat_profiles SET chat_id=new WHERE chat_id=old` + аналогичные UPDATE
  по связанным SQLite-таблицам (или ленивый резолв через `chat_links`).
- **Риски**: правки через FastAPI → запись в SQLite-файл бота (если web и бот в разных процессах —
  нужен WAL/один писатель); per-chat права и «общий список чатов» придётся дублировать (нет PG);
  история/аудит не в общей конфигурационной картине. Зато ничего не трогает PG-стек.

### [ ] Вариант B — конфиг-ключи в `bot_settings` (per-chat), «по-хотфиксному»

Ключи в PG (категория, например, `chat_lore`):

| key | value (JSONB) | смысл |
|---|---|---|
| `chat_lore.<chat_id>.text` | строка | текст лора |
| `chat_lore.<chat_id>.auto_enabled` | bool | авто-генерация |
| `chat_lore.<chat_id>.source` | `manual\|auto` | происхождение |
| `chat_lore.<chat_id>.lore_links` | `{old_id: …}` | переезд |

- **API/UI**: почти бесплатно — категория `chat_lore` сидится в PG, рендерится в TMA как новая
  секция-вкладка («Лор чатов»), bool → тумблер, текст → textarea; KV-механика уже отлажена
  (`limits.summary_aliases` — прецедент).
- **Права**: RBAC v2 без изменений: секция `chat_lore` в ролях; но per-chat админов всё равно нет.
- **Миграция**: стартовый сид `chat_lore.<-100id>.text` из константы (ON CONFLICT DO NOTHING —
  паттерн сидов pg_db); бот при сборке контекста читает значение через `ConfigCache`.
- **Авто-генерация**: воркер обновляет тот же ключ (версии — нет: только `updated_at`).
- **Ремаппинг**: «перепривязать» = переименовать ключи с old на new (операция неатомарная) +
  поправить физические SQLite-данные чата.
- **Риски**: нет истории версий и `updated_by` (нужно доращивать схему bot_settings); длинный
  текст в KV ломает компактность дашборда; список «всех чатов» ищется LIKE по префиксу;
  конкурентные правки двух админов — lost-update без версий. Быстро, но «на вырост» не тянет.

### [x] Вариант C — гибрид: PG-профиль + авто-лор воркер + chat_links/chat_admins (рекомендуется)

Рекомендую. Три новые таблицы в PG (в `pg_db.py`, идемпотентный DDL как у `bot_settings`):

```sql
CREATE TABLE IF NOT EXISTS chat_profiles (
    chat_id       BIGINT PRIMARY KEY,          -- runtime id, -100… (64-бит!)
    lore_text     TEXT NOT NULL DEFAULT '',
    auto_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    source        TEXT NOT NULL DEFAULT 'auto', -- manual | auto
    updated_by    BIGINT,                      -- telegram_id; NULL = бот-воркер
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chat_profiles_history (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    BIGINT NOT NULL REFERENCES chat_profiles(chat_id) ON DELETE CASCADE,
    lore_text  TEXT NOT NULL,
    source     TEXT NOT NULL,
    changed_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chat_links (        -- переезд/ремаппинг
    old_chat_id BIGINT PRIMARY KEY,
    new_chat_id BIGINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS chat_admins (       -- per-chat права
    telegram_id BIGINT NOT NULL,
    chat_id     BIGINT NOT NULL,
    added_by    BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (telegram_id, chat_id)
);
```

- **API-эндпоинты** (FastAPI, аутентификация TMA как у `/api/config`):
  - `GET /api/chat_lore` — список чатов (id, превью, источник, auto_enabled) — для селектора;
  - `GET /api/chat_lore/{chat_id}` — профиль + привязка (нет записи → дефолт);
  - `PUT /api/chat_lore/{chat_id}` — `{lore_text, auto_enabled}`; ручная правка ставит
    `source='manual'`, `auto_enabled=false` (правило «руки человека важнее»), пишет строку в
    `chat_profiles_history` (changed_by = telegram_id);
  - `POST /api/chat_lore/{chat_id}/generate` — ручной запуск выжимки (или крон);
  - `POST /api/chat_lore/{chat_id}/remap` — `{new_chat_id}`: запись в `chat_links` + опциональная
    активная миграция SQLite-данных чата (protected_facts/smart_messages/graph_facts/bot_replies/
    user_prefs) в одной транзакции, либо ленивый резолв на чтении;
  - `GET /api/chat_lore/{chat_id}/history` — версии (для diff/роллбэка).
- **UI (TMA) «Лор чатов»**: список чатов → карточка профиля: textarea (счётчик символов, лимит
  2–4K), чекбокс «Автоматически формировать лор», бейдж «вручную/авто» + дата генерации, поле
  «Привязанный chat_id» + кнопка «Перепривязать…» (модалка подтверждения: «данные чата будут
  перенесены с id X на id Y»), кнопка «Сгенерировать сейчас», вкладка «История» с diff и
  роллбэком.
- **Права**: глобальные admin/moderator — на всё (секция `chat_lore` в RBAC, сид в роли admin +
  moderator); `chat_admins` — локальные админы чата (правит только профиль СВОЕГО чата);
  правило: `global role grant` ИЛИ `(telegram_id, chat_id) IN chat_admins`. Вариант даунгрейда:
  на этапе 1 локальные списки не вводить (задача мульти-чата с разными админами — отдельной
  доработкой поверх этой же таблицы).
- **Миграция с хардкода** (одноразовый скрипт/сид в on_startup):
  1. `INSERT INTO chat_profiles (chat_id, lore_text, auto_enabled=false, source='manual',
     updated_by=NULL) VALUES (-1002661910336, '<текст константы>', …) ON CONFLICT DO NOTHING`;
  2. удалить/пометить строки `protected_facts`/`graph_facts`, созданные старым `ensure_chat_lore`
     (текст-в-лор теперь живёт в профиле и доставляется иначе — см. п. «Инжект»);
  3. сборка `<protected_facts>` direct_chat: к чат-уровневым фактам спереди добавляется блок
     «лор» из профиля (читается из PG-кэша ConfigCache по chat_id), поведение «всегда виден,
     не режется» сохраняется;
  4. удалить `ensure_chat_lore`/константы (оставить лог-точку на случай не-мигрированных БД).
- **Авто-генерация лора (воркер)**:
  - триггер: крон (например, ночь) + порог «N новых сообщений в smart_messages с last_run» +
    ручная кнопка; fire-and-forget, как существующий конспект окна (`summary_memory.py`);
  - промпт: «у тебя есть прошлый лор + выжимка новых сообщений окна + чат-уровневые факты;
    обнови лор: сохрани постоянное, перезапиши устаревшее, держи ≤ X токенов; формат — связный
    текст 1–3 абзаца» (merge-паттерн из 2.2);
  - запись: предыдущий текст → `chat_profiles_history`, новый текст — в профиль ТОЛЬКО если
    `auto_enabled=true`; `source='auto'`, `changed_by=NULL`;
  - защита: если ручная правка произошла между стартом генерации и записью (updated_at изменился)
    — не перезаписывать (условие optimistic lock по updated_at).
- **Ремаппинг chat_id**: (а) авто — обработчик Telegram-миграции (aiogram: service-сообщение с
  `migrate_to_chat_id`/`migrate_from_chat_id`, исключение `TelegramMigrateToChat`) → запись в
  `chat_links` + перенос профиля и настроек; (б) ручной — кнопка в UI; (в) ленивый резолв:
  все чтения «профиля по chat_id» сначала проверяют `chat_links` (старый id → новый).
- **Риски C**:
  - лор «живёт в PG», а память — в SQLite: нужно аккуратно определить точку инжекта и кэш
    (ConfigCache уже умеет `get`/`set` с asyncio.Lock);
  - два хранилища в одном вопросе — чуть больше движущихся частей, чем A;
  - авто-воркер тратит токены — нужен порог и disable;
  - если PG недоступен в момент инжекта — fail-open (как `ensure_chat_lore` сейчас) + фоллбэк
    на последний известный текст из локального кэша/истории.

---

## 5. Сравнение и рекомендация

| Критерий | A (SQLite-таблица) | B (bot_settings-ключи) | C (PG-гибрид) |
|---|---|---|---|
| Скорость внедрения | средняя | **высокая** | средняя |
| История версий / audit | своя таблица | нет (нужно доращивать) | своя таблица |
| per-chat админы | нет | нет | есть (`chat_admins`) |
| Переезд/ремаппинг | ручной UPDATE | переименование ключей | `chat_links` + авто-ловля |
| Единый конфиг-стек (PG/TMA/RBAC) | нет | да, но KV-мучения | да |
| Риск деградации при мульти-чате | средний | высокий | низкий |

**Рекомендация: вариант C.** Он повторяет «как делают зрелые боты» (server profile в реляционном
хранилище конфигурации + per-guild права + аудит), использует уже готовые RBAC v2, ConfigCache,
сид-механику pg_db и TMA-рендер, и оставляет место под авто-лор-воркер и миграции chat_id.
Если хочется «быстро и руками» уже завтра — вариант B как первый шаг (одна секция в TMA), но с
сознательным долгом: ввести таблицу профилей при появлении второго активного чата. Вариант A —
только если web-процесс и бот гарантированно делят один SQLite-файл без гонок писателей.

---

## 6. Источники (URL)

1. MongoDB-паттерны Discord-ботов: «один документ на guild, guild_id = _id, schema versioning» —
   https://guden.tr/blog/mongodb-patterns-discord-bots
2. Prisma-схема: Server → ServerSettings 1:1, per-guild изоляция —
   https://github.com/Suraj89011/discord-bot-template (commit b18ee10)
3. Supabase-схема Discord-бота: `discord_server_configs` + RLS-изоляция по серверу —
   https://docs.rsnc.network/discord/database-schema
4. Инкрементальные саммари (rolling summary: chunk window, merge prompt, token budget) —
   https://agenticskillset.org/en/topics/incremental-summarization/
5. «Recursively Summarizing Enables Long-Term Dialogue» (рекурсивная память, галлюцинации ~<10%) —
   https://arxiv.org/html/2308.15022v3
6. MT-OSC: фоновая конденсация истории, «Decider» против потери фактов (ACL 2026) —
   https://aclanthology.org/2026.findings-acl.1354.pdf
7. LlamaIndex ChatSummaryMemoryBuffer (summarize то, что не влезло) —
   https://developers.llamaindex.ai/python/examples/memory/chatsummarymemorybuffer/
8. Mem0: memory formation vs summarization, threshold-based triggers, иерархическая память —
   https://mem0.ai/blog/llm-chat-history-summarization-guide-2025
9. Per-guild права: Warden permissions (назначения скоупированы guildId) —
   https://getwarden.dev/plugins/permissions/
10. Phantom Team Roles: роли на дашборд per-guild, `.view/.edit` на модуль, история с before/after —
    https://docs.phantombot.gg/getting-started/team-roles
11. «Server Lore» как продукт (Discord-бот Contexta) — https://contexta-bot-website.vercel.app/
12. Telegram-миграция групп: поля `migrate_to_chat_id`/`migrate_from_chat_id` в Message —
    https://core.telegram.org/bots/api#message
13. Перенос chat_data при миграции (python-telegram-bot) —
    https://github.com/python-telegram-bot/python-telegram-bot/pull/1684
14. Разбор «group upgraded to supergroup»: ловля ошибки, 64-бит id, шаги восстановления —
    https://www.conferbot.com/errors/telegram/400-bad-request-group-chat-was-upgraded-to-a-supergroup-chat
15. Практика супергрупп (Papercraft): миграции меняют chat id —
    https://pcraft.dev/book/supergroups
16. SO: id меняется при конвертации в супергруппу; обработка миграции —
    https://stackoverflow.com/questions/51864930/

**Внутренние привязки (код текущей системы):** `services/chat_lore.py:20-76` (константа + ensure),
`bot.py:196-199` (стартовый вызов), `services/database.py:1549-1603` (protected_facts, чат-уровень
первым), `services/direct_chat_service.py:625-641` (блок `<protected_facts>`), `services/pg_db.py:33-115`
(DDL bot_settings/ролей + сиды), `services/permissions.py` (RBAC v2), `services/param_catalog.py`
(категории/секции), `services/config_cache.py` (get/set + Lock), `web/api/routes.py` + `web/api/deps.py`
(эндпоинты, `requires_permission`), прецедент `plans/features/user-aliases-admin/` (KV-редактор в TMA).
