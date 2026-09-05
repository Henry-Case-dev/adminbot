# Спецификация: Chat Lore Management v2.0 — PG-профили чатов + авто-лор-воркер + TMA «Лор чатов»

**Эпик:** раунд 7 (05.09.2026), T-770…T-788 (база HEAD `3bf9e75`).
**Статус:** спецификация @Architect (T-770) — закрывает открытые вопросы Q1–Q9 PM-раздела A
(`tasks.md`) и является источником дизайн-решений для задач B–I. Является зеркалом раздела A
(не дублирует его тексты, а уточняет/фиксирует решения); **все «изменено @Architect T-770»**
перечислены в §3.1 «Расхождения с PM-разделом A» и в §4 (Q1–Q9).
**Документы-источники:** `plans/features/chat-lore-management-v2/tasks.md` (раздел A + T-770),
`plans/docs/chat-lore-management-research.md` (вариант C, выбран `[x]`).

---

## 1. Обзор

### 1.1 Проблема

Лор конференции `-1002661910336` захардкожен в коде (`services/chat_lore.py:25-33`,
`CHAT_LORE_2661910336`, инжект через `ensure_chat_lore` в `bot.py:196-199` в два места SQLite:
`protected_facts` chat-level `user_name IS NULL` + `graph_facts origin='user_memory'`). Правка
текста = редеплой; нет мульти-чатности, нет авто-генерации, нет аудита правок, нет переживания
переезда чата (смены `chat_id`).

### 1.2 Цель (по research §5, вариант C)

Вывести лор в управляемую сущность: **PG-профиль чата** (ручной + авто-лор независимо),
**фоновый авто-воркер** (LLM-выжимка из окна `smart_messages`, merge со старым лором),
**раздел TMA «Лор чатов»** (редактор + история + per-chat админы), **переживание переезда**
(`chat_links` + ленивый резолв + авто-обработчик `migrate_to_chat_id`), **инжект в контекст
direct_chat** из PG с дедупом против SQLite-легаси.

### 1.3 Ключевые свойства системы (инварианты дизайна)

1. **Manual и auto-лор НЕЗАВИСИМЫ** (ТЗ владельца): ручная правка пишет только `manual_lore`,
   авто-генерация — только `auto_lore`; ручная правка не выключает авто-генерацию (отключается
   только тумблером `auto_enabled` профиля). В инжект попадают оба поля.
2. **Легаси SQLite не трогаем** (RUNTIME WARNING): старые строки (`protected_facts`/
   `graph_facts` от раунда 5) не удаляем и не мигрируем; дедуп текста — ТОЛЬКО на чтении/инжекте
   (Q1). SQLite-схемы, `manage.py`, `tools/history_import/`, файлы `local_database_*.db*` — вне
   скоупа. Весь новый код: PG (DDL + сервисы), FastAPI, TMA-фронт, новые aiogram-хендлеры,
   воркер, `direct_chat_service` (только чтение-инжект). SQLite-ЧТЕНИЕ разрешено
   (`get_protected_facts`, окно `smart_messages` для воркера).
3. **Fail-open везде**: PG недоступен/ошибка → пустой лор-блок, старое SQLite-поведение,
   бот жив. Ошибки — `logger.warning`, без спама (дедуп-счётчик раз в N попыток).
4. **Атомарность**: изменение строки профиля + запись истории + `pg_notify` — одна явная
   транзакция (`async with conn.transaction()`), сбой → полный откат.
5. **Инжект лора не режется контекст-бюджетом** (protected-семантика), защита от раздувания —
   только cap ДО инжекта (§3.9, Q1).

### 1.4 Код-привязки (проверены при планировании)

- `services/pg_db.py:33-70` — `DDL_STATEMENTS` (идемпотентный `CREATE TABLE/INDEX IF NOT EXISTS`,
  новый блок — дополнением в конец кортежа); `:110-115` — `SEED_CATEGORIES`
  (limits/flags уже есть — не меняем); `:219-276` — `init()` = DDL + сиды; сид значений
  `bot_settings` читает `getattr(settings, spec.settings_field)` → **для новых REGISTRY-записей
  обязательны парные поля Settings** (§3.11).
- `services/config_cache.py:86+` — `ConfigCache`: `pg` (`:112`), `init()` (`:125`, внутри
  `pg.init()`), `get/upsert/close`; шарится между ботом и FastAPI (`web/app.py:89`,
  `bot.py:601-605`).
- `web/api/deps.py:80-195` — `get_tma_user`, `requires_permission`, `tma_context`;
  `routes.py:60` — `api_router`; включение `web/app.py:96`. Правила матчинга RBAC —
  `services/permissions.py:110-142`; секции/дерево — `param_catalog.known_sections()`
  (`:1072-1074`, `set(CATEGORIES) | {"access"}`); единственный вызов — `routes.py:379`
  (валидация ролей).
- `web/app.js` — `TABS` (`:18-47`), `api()` (`:264`), `hasPerm` (`:342`, зеркало
  `permissions.py`), `canViewTab` (`:369`), `setTab` (`:308`); шаблоны — `web/index.html`
  (`v-else-if activeTab === …`, конфиг-вкладки — generic-блок `:320-420`).
- `services/direct_chat_service.py` — `_build_user_content` (`:402-441`), `_apply_context_budget`
  (`:445-517`), `_build_protected_facts` (`:625-641`), persona-ветка `build_persona_card`
  (`:765-795`, читает `db.get_protected_facts(..., include_chat_level=True)` напрямую `:778`);
  `services/database.py:1584-1603` — `get_protected_facts` (чат-уровневые первыми);
  `services/database.py:1045-1056` — `get_smart_window(chat_id, since_ts, limit)`
  (SQLite-чтение окна); `services/summary_xml.escape_xml_text` (экранирование в блоках).
- Планировщик-прецедент: `services/memory_maintenance.py:40-92` (`AsyncIOScheduler(tz=…)`,
  `IntervalTrigger` + `max_instances=1, coalesce=True`, hot-гейты; DI/старт `bot.py:403-416`,
  стоп в `on_shutdown` `:564+`).
- chat_member-прецедент: `handlers/slava_presence.py:24-67` (`ChatMemberUpdatedFilter(
  IS_NOT_MEMBER >> IS_MEMBER)` и обратно, `UNHANDLED` для чужих, модульный `setup_presence`);
  инклуд-зона `bot.py:483` (новые инклуды — ТОЛЬКО добавками, порядок существующих не менять).
- Легаси-лор: `services/chat_lore.py` (константа `:25-33`; `CHAT_LORE_TARGET_CHAT_ID=-1002661910336`
  `:21`). Константа нужна воркеру/инжекту для дедуп-исключения (§3.9/§3.5).
- Фильтр «не бот» прецедент: `handlers/summary.py:166` (`_bot_id`, DI через `setup_summary`).
- Тесты: `tests/test_config_cache.py:78+` (`_FakePg`/`_FakePool`), `tests/test_webapp_*.py`,
  `tests/test_chat_lore.py`, `tests/test_direct_chat.py`, `tests/test_frontend_tab_mapping.py`
  (конфиг-группы каждой вкладки; новые группы limits/flags попадут на вкладку «Лимиты»
  автоматически — см. §3.11, тест `test_limits_tab_excludes_memory_groups` не ломается).

---

## 2. Требования

### 2.1 Функциональные требования (FR)

- **FR-1 (профили).** Каждый чат (по `chat_id`, включая отрицательные id супергрупп ≤ −100…) имеет
  PG-профиль: `manual_lore`, `auto_lore`, `auto_enabled`, `auto_period_hours`, `auto_window_hours`,
  `is_active`, `last_auto_at`, `updated_at`. Профиль создаётся: (а) lifecycle-событием входа бота в
  чат (FR-6), (б) сид-скриптом (FR-10), (в) лениво — по умолчанию нет (404 в API).
- **FR-2 (ручная правка).** Админ/модератор/чат-админ меняет `manual_lore` (≤ 4000 символов,
  optimistic lock по `updated_at` → 409 при конфликте); записывается история
  (`field='manual'`, `changed_by=telegram_id`). Ручная правка НЕ трогает `auto_lore` и
  НЕ выключает `auto_enabled`.
- **FR-3 (авто-генерация).** Фоновый цикл (каждые `limits.lore_tick_minutes`, по умолчанию 30 мин)
  обходит `is_active AND auto_enabled`-профили; прогон чата — когда: глобальный флаг
  `flags.lore_auto_enabled` включён; период с последнего успешного авто-прогона
  (`last_auto_at`, см. §3.5) ≥ `auto_period_hours`; в окне `auto_window_hours` ≥
  `limits.lore_min_messages` «осмысленных» сообщений (§3.5, Q5). LLM merge/init по канону
  `services/lore_prompts.py` (§3.6). Результат пишется в `auto_lore` (история `field='auto'`,
  `changed_by NULL`) или пропускается (UNCHANGED — метка `last_auto_at` без истории). Любые
  ошибки — fail-open WARNING, профиль не трогается.
- **FR-4 (ручная генерация).** `POST /{chat_id}/generate` («Сгенерировать сейчас») вызывает тот же
  `LoreWorker.generate_for_chat(manual=True)`: обходит период/окно/флаги, но ТРЕБУЕТ
  `auto_enabled=true` профиля (иначе 409 с detail). Работает без ожидания периода.
- **FR-5 (инжект).** В контекст direct_chat (и карточку `/persona`) добавляется блок
  `<chat_lore>` (manual + auto, разделитель `---`) сразу ПОСЛЕ `<protected_facts>`, если:
  `flags.lore_inject_enabled` включён, для `chat_id` есть PG-профиль (резолв `chat_links`),
  профиль `is_active` и хотя бы одно из полей непусто. Cap блока — `limits.lore_inject_max_chars`
  (§3.9). При активном PG-лоре SQLite chat-level факты (весь `user_name IS NULL` канал легаси-лора)
  из `<protected_facts>` исключаются; иначе — ровно старое поведение.
- **FR-6 (lifecycle).** События `my_chat_member` только про самого бота
  (`new/old_chat_member.user.id == bot.id`): бот стал участником/админом → `ensure_profile` +
  `is_active=true`; бот удалён/вышел → `is_active=false` (тексты и настройки не трогаются).
  События других юзеров — `UNHANDLED`.
- **FR-7 (переезд чата).** Message-хендлер `migrate_to_chat_id`: `chat_links.add_link(old, new)` +
  `migrate_profile(old, new)` (merge-семантика Q9) + история `field='remap'` + NOTIFY.
  Ручной remap: `POST /{chat_id}/remap`. Все чтения профиля (инжект, API, воркер) идут через
  `resolve_chat_id` (глубина ≤ 5, защита от циклов).
- **FR-8 (RBAC).** Новая секция `chat_lore` (§3.8): глобальный admin — все чаты и все операции;
  moderator/custom-роль с `section.chat_lore` — доступ к чатам из `chat_admins`; per-chat admin
  (строка `chat_admins` без глобальной роли) — свой чат. Remap и CRUD `chat_admins` — только
  глобальный admin. Требования: «Сгенерировать/Очистить/remap/история» — по этой матрице.
- **FR-9 (API + история + фронт).** Эндпоинты §3.8; история-аудит (§3.3, Q7); раздел TMA
  «Лор чатов» (§3.10) с 409-обработкой optimistic-lock.
- **FR-10 (сид легаси-лора).** `scripts/seed_chat_lore.py` — идемпотентный перенос константы
  `CHAT_LORE_2661910336` в `manual_lore` профиля `-1002661910336` (`ON CONFLICT DO NOTHING`,
  непустой существующий manual не затирать). Без side-эффектов на SQLite (§3.12).

### 2.2 НФР

- **NFR-1.** Полный `pytest` перед коммитом → 0 failed; `git diff --check` чист; секреты не
  логировать (R17); `.db-wal/.db-shm` в коммиты не попадают.
- **NFR-2.** Fail-open (см. §1.3-3); старт бота не роняется ошибками PG-слоя лора.
- **NFR-3.** Идемпотентность: повторный `pg.init()` (DDL) и повторный сид — no-op.
- **NFR-4.** Инжект-путь не делает лишних PG-запросов на каждое сообщение: чтение через
  RAM-кэш (Q2), NOTIFY-инвалидация, TTL-фолбэк.
- **NFR-5.** Авто-воркер не тратит токены вхолостую: гейты периода/флага/порога + cooldown +
  advisory-лок (§3.5, Q3/Q4); UNCHANGED не пишет историю.
- **NFR-6.** Новых зависимостей нет (asyncpg/apscheduler/FastAPI/aiogram уже в проекте).

---

## 3. Техдизайн

### 3.1 Расхождения с PM-разделом A (решения @Architect T-770; применяются к задачам B–I)

| № | Пункт PM-раздела A | Решение @Architect (эта спецификация) |
|---|---|---|
| D1 | `chat_profiles` «строго по ТЗ, без лишних колонок» | + колонка `last_auto_at TIMESTAMPTZ NULL` (Q3; обоснование §3.5) |
| D2 | История: `field IN ('manual_lore','auto_lore','settings','remap')`, settings — JSON-строка | `field IN ('manual','auto','auto_enabled','auto_period_hours','auto_window_hours','remap','chat_admin')` (Q7): настройки пишутся ПО-ПОЛЕВОЙ записью; `is_active` в историю НЕ пишется |
| D3 | Cap инжекта «общий ≤ 2000 символов (диапазон 1500–2500 фиксирует @Architect)» | `limits.lore_inject_max_chars = 3000` (Q1) |
| D4 | REGISTRY: 5 записей (в т.ч. `limits.lore_max_tokens`) | Полный список §3.11: `limits.lore_max_tokens` УБРАН (бюджет выражается в словах — `limits.lore_max_words`), добавлены `lore_min_message_chars/lore_window_max_messages/lore_window_max_chars/lore_max_words/lore_inject_max_chars/lore_tick_minutes` + `flags.lore_worker_enabled` (**правит T-776/C2, T-785/H3.1, T-786/README-списки**) |
| D5 | Remap: «new занят → WARNING/409, не затирать» | Merge-семантика Q9: профиль переносится и объединяется, API возвращает 200 (**правит T-779/E1, T-783/H1 «remap 409»**) |
| D6 | Кэш TTL-фолбэк 60 с | TTL-фолбэк **120 с** (Q2) |
| D7 | Кэш «в store или отдельный файл — Q2» | Отдельный `services/lore_cache.py` (Q2) |
| D8 | RBAC: moderator-section видит ВСЕ чаты; admins-CRUD — «глобальные admin/moderator-section» | Безопаснее (Q6): moderator/custom с `section.chat_lore` видит ТОЛЬКО чаты из `chat_admins`; POST/DELETE `chat_admins` и remap — только глобальный admin; DELETE `chat_admins` НЕ доступен moderator-section |
| D9 | «Сгенерировать сейчас … вызов generate_for_chat(manual=True)» | Синхронный вызов в обработчике (ответ после завершения LLM-прогона) |
| D10 | Изменяющие операции над профилем принимают «ожидаемый updated_at» | `updated_at` (обязательный) передаётся ТЕЛОМ JSON (`body.updated_at`), не If-Match-заголовком (Q8) |

### 3.2 Схема PostgreSQL (задачи B1)

Четыре НОВЫЕ таблицы — дополнением в `DDL_STATEMENTS` (`services/pg_db.py:33-70`), идемпотентно,
в едином стиле существующих (без FK между новыми таблицами). Для существующих БД миграция = сам
`CREATE TABLE IF NOT EXISTS` при очередном `init()` — никаких ALTER/rebuild существующих таблиц.

```sql
CREATE TABLE IF NOT EXISTS chat_profiles (
    chat_id           BIGINT PRIMARY KEY,             -- runtime id (-100…, 64-бит)
    manual_lore       TEXT NOT NULL DEFAULT '',       -- ручной лор (админ)
    auto_lore         TEXT NOT NULL DEFAULT '',       -- авто-лор (воркер)
    auto_enabled      BOOLEAN NOT NULL DEFAULT TRUE,  -- тумблер авто-генерации чата
    auto_period_hours INTEGER NOT NULL DEFAULT 24,    -- период авто-прогонов
    auto_window_hours INTEGER NOT NULL DEFAULT 24,    -- окно истории для генерации
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,  -- бот в чате (lifecycle)
    last_auto_at      TIMESTAMPTZ,                    -- успешный авто-прогон (NULL = ещё нет)
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()  -- optimistic-метка (любое изменение)
);

CREATE TABLE IF NOT EXISTS chat_lore_history (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    BIGINT NOT NULL,
    field      TEXT NOT NULL CHECK (field IN
               ('manual','auto','auto_enabled','auto_period_hours',
                'auto_window_hours','remap','chat_admin')),
    changed_by BIGINT,                                -- NULL = бот/воркер (AI)
    old_value  TEXT NOT NULL DEFAULT '',
    new_value  TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_lore_history_chat_ts
    ON chat_lore_history (chat_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_links (
    old_chat_id BIGINT PRIMARY KEY,
    new_chat_id BIGINT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_admins (
    chat_id     BIGINT NOT NULL,
    telegram_id BIGINT NOT NULL,
    added_by    BIGINT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, telegram_id)
);
```

Замечания:

- **`last_auto_at`** — расширение схемы юзера, допустимое ТЗ (Q3): `updated_at` меняется на любые
  правки (включая manual) и НЕ может служить маркером «последней генерации»; `MAX(created_at)`
  из истории по `field='auto'` — тоже не годится: clear_auto пишет историю с тем же field, а
  UNCHANGED-прогоны истории не оставляют. `last_auto_at` выставляется ТОЛЬКО воркером
  (успешный прогон: смена текста ИЛИ UNCHANGED) и ручной генерацией; сбрасывается в NULL при
  `clear_auto` (чтобы следующий прогон не ждал период) — и никогда не трогается ручными
  правками `manual_lore`.
- `updated_at` обновляется `now()` на каждое изменение строки профиля (оптимистик-метка,
  включая служебные апсерты воркера и `is_active` — единая «активность профиля»).
- `chat_links` PK по `old_chat_id` — каждая «умершая» ссылка уникальна; повторный переезд того же
  старого id (upsert) перезаписывает `new_chat_id` на актуальный (§3.4/Q9).
- Индексов на `chat_profiles` сверх PK не нужно (выборки по PK и полный скан для
  `list_active_chats`).

### 3.3 `services/chat_lore_store.py` — транзакционный слой (B2)

`ChatLoreStore(pg: PgDatabase)` — тонкий слой над пулом; **транзакционная единица**:
`async with conn.transaction()`: (1) мутирующий SQL по профилю; (2) при контентном изменении —
`INSERT INTO chat_lore_history`; (3) `SELECT pg_notify('lore_updated', $1)` (payload —
`str(chat_id)`), при remap — два события (old и new). Сбой в любой точке → откат целиком
(ни апдейта, ни истории, ни NOTIFY).

Тип данных профиля — `@dataclass(frozen=True) LoreProfile` (в `services/lore_cache.py`, см. §3.4)
с полями: `chat_id, manual_lore, auto_lore, auto_enabled, auto_period_hours, auto_window_hours,
is_active, last_auto_at: str|None, updated_at: str` (ISO-8601 UTC) + `is_ai`-производные не нужны.

**Методы (обязательный контракт):**

- `get_profile(chat_id) -> LoreProfile | None` — с `resolve_chat_id` внутри (запрос по
  актуальному id).
- `list_profiles() -> list[LoreProfile]`; `list_active_chats() -> list[int]` —
  `WHERE is_active AND auto_enabled` (список chat_id для цикла воркера).
- `ensure_profile(chat_id) -> LoreProfile` — `INSERT ... ON CONFLICT (chat_id) DO NOTHING`,
  затем SELECT. Дефолты из схемы (auto_enabled=TRUE, периоды 24, is_active=TRUE, лоры пусты).
- `set_manual(chat_id, text, changed_by, expected_updated_at=None) -> LoreProfile` — UPDATE
  `manual_lore, updated_at=now()` с условием оптимистик-метки
  (`WHERE chat_id=$1 AND updated_at=$2::timestamptz`); 0 строк → `ChatLoreConflict(
  chat_id, current_updated_at)` (в транзакции читаем актуальный `updated_at` для исключения);
  история `field='manual'` old/new; NOTIFY. НЕ трогает `auto_lore/last_auto_at/auto_enabled`.
- `set_auto(chat_id, text) -> LoreProfile` — вызов воркера при изменении текста: UPDATE
  `auto_lore, last_auto_at=now(), updated_at=now()`; история `field='auto'`, `changed_by NULL`;
  NOTIFY. Без optimistic-метки (воркер — свой гейт, §3.5).
- `mark_auto_done(chat_id) -> None` — UNCHANGED-путь: UPDATE `last_auto_at=now(),
  updated_at=now()`; **истории нет** (контент не менялся); NOTIFY. (Период обязан «сброситься»
  и при UNCHANGED, иначе активный чат гонял бы LLM каждый тик — §3.5.)
- `clear_auto(chat_id, changed_by) -> LoreProfile` — UPDATE `auto_lore='', last_auto_at=NULL,
  updated_at=now()`; история `field='auto'` old=предыдущий текст, new=''; NOTIFY.
- `update_settings(chat_id, *, auto_enabled=None, auto_period_hours=None, auto_window_hours=None,
  changed_by, expected_updated_at=None) -> LoreProfile` — частичное обновление только переданных
  полей; **история пишется отдельной строкой на каждое реально изменённое поле**
  (`field='auto_enabled'|'auto_period_hours'|'auto_window_hours'`, old/new — строки значений);
  если ни одно поле не изменилось — UPDATE не выполняется и истории нет; optimistic-метка →
  `ChatLoreConflict`.
- `set_active(chat_id, is_active) -> None` — lifecycle-апсерт (без истории, без
  optimistic-метки), NOTIFY (is_active влияет на гейт инжекта).
- `migrate_profile(old_chat_id, new_chat_id) -> dict` — перенос/merge по Q9 (§4): возвращает
  `{"moved": bool, "merged": bool}`; пишет историю `field='remap'`
  (old_value=str(old), new_value=str(new)); NOTIFY old+new; переносит `chat_admins`.
- `chat_admins`: `list_chat_admins(chat_id)`, `add_chat_admin(chat_id, telegram_id, added_by)`
  (`INSERT ... ON CONFLICT DO NOTHING`, история `field='chat_admin'`, new_value=str(telegram_id)),
  `remove_chat_admin(chat_id, telegram_id)` (DELETE + история `field='chat_admin'`,
  old_value=str(telegram_id)); `is_chat_admin(telegram_id, chat_id) -> bool` (для RBAC, §3.8).
- `chat_links`: `add_link(old, new)` (INSERT `ON CONFLICT (old_chat_id) DO UPDATE SET
  new_chat_id=EXCLUDED.new_chat_id`), `resolve_chat_id(chat_id) -> int` (жадно: пока есть ссылка —
  идти по цепочке; **глубина ≤ 5 и защита от циклов** (множество посещённых) → при превышении
  вернуть исходный id), `list_chat_history(chat_id, limit=100)` — timeline DESC.
- `history(chat_id, limit) -> list[dict]` — строки истории (created_at ISO, field, changed_by,
  old_value, new_value).

Исключение: `class ChatLoreConflict(Exception)` — `chat_id`, `current_updated_at`.

Реализация NOTIFY-эмита: внутри той же транзакции `await conn.execute("SELECT pg_notify(
'lore_updated', $1)", str(chat_id))` — доставка после COMMIT (документированное поведение
asyncpg/PostgreSQL). На INSERT history отдельный pg_notify не нужен: любая запись истории в этой
архитектуре сопровождается апдейтом профиля; одиночная история не инвалидирует профиль.

### 3.4 `services/lore_cache.py` + `services/lore_notify.py` (B3/B4, Q2/Q4)

**`ChatLoreCache`** — в ОТДЕЛЬНОМ модуле (`services/lore_cache.py`; решение Q2): хранилище — RAM
`dict[chat_id, _Entry(profile: LoreProfile, loaded_mono: float)]`; инстанс один на процесс,
создаётся в `bot.py` on_startup и шарится между инжектом direct_chat, API-роутами и воркером.

Контракт:

- `get(chat_id) -> LoreProfile | None` — load-on-demand: miss → `store.get_profile(chat_id)`
  (резолв chat_id внутри store). Исключение/`None` → наружу None, в кэш НЕ кладётся (следующий
  вызов попробует снова); fail-open: PG down — пусто, SQLite-fallback (легаси-путь инжекта)
  работает.
- **Инвалидация:** (1) NOTIFY `lore_updated` → `invalidate(chat_id)` — удаление ключа; (2) TTL-
  фолбэк: при `get`, если `loaded_mono` старше 120 секунд — перечитать (NOTIFY может потеряться).
- Гонки: `asyncio.Lock` на мутации внутренних dict + coalescing параллельных miss'ов на один
  chat_id (inflight-таск/фьюча: второй `get` того же id не делает второй SELECT).
- `invalidate_all()` (на `reload`/служебные нужды — опционально).
- `resolve_chat_id` отдельно НЕ кэшируется (база: запрос в store; цепочки короткие, а кэш ссылок
  потребовал бы инвалидации при `add_link`).

**`LoreNotifyService`** — LISTEN-подписка (B3): отдельное asyncpg-соединение (не из пула;
реквизиты из конфига `PgDatabase`, init-колбэк регистрирует json-кодеки, прецедент
`_init_connection` pg_db.py:178), `add_listener('lore_updated', cb)`; `cb(pg_conn, pid,
channel, payload)` → `asyncio.create_task(cache.invalidate(int(payload)))` — никогда не роняет
задачу слушателя (try/except WARNING).

Lifecycle: `start()` — попытка connect+listen; при недоступности PG → `logger.warning` +
фоновый retry-цикл: повторная попытка каждые **60 с** (fail-open, бот жив). Обрыв соединения в
процессе работы → WARNING + переподключение (retry каждые 60 с). `stop()` — close соединения и
отмена задачи. Интеграция: создание/`start()` в `bot.py` после `cache.init()`/on_startup
(рядом с uptime-сервисами, порядок существующих не трогать); `stop()` — в shutdown-секции
(прецедент `on_shutdown` bot.py:564+).

### 3.5 `services/lore_worker.py` — воркер (C1/C2; Q3/Q4/Q5)

**Класс `LoreWorker(store: ChatLoreStore, cache: ChatLoreCache, db: DatabaseService,
llm: LLMClient, bot_id: int | None = None)`.**

**Цикл (C2):** `start()`/`stop()` — `AsyncIOScheduler(timezone=hot.get("limits.summary_timezone",
settings.SUMMARY_TIMEZONE))`, джоб `lore_worker_tick`: `IntervalTrigger(minutes=hot.get(
"limits.lore_tick_minutes", settings.LORE_TICK_MINUTES), timezone=…)`,
`max_instances=1, coalesce=True`. Джоб добавляется и планировщик стартует только при
`hot.get("flags.lore_worker_enabled", settings.LORE_WORKER_ENABLED)`. Тик: `store.list_active_chats()`
→ последовательно `generate_for_chat(chat_id)` (каждый в своём try — ошибка чата не роняет тик,
WARNING). Несуществующий/недоступный PG → WARNING, следующий тик.

**`generate_for_chat(chat_id, *, manual=False) -> dict{status, reason}`** — шаги:

1. **Advisory-лок** (анти-гонка тик vs «Сгенерировать сейчас» vs повторные вызовы): на
   ОТДЕЛЬНОМ соединении на время всего прогона —
   `conn = await pg.connect(..., init=_init_connection)` (прямое соединение по DSN, НЕ из пула —
   LLM-вызов занимает минуты, пул min1/max10 занимать нельзя); `SELECT pg_try_advisory_lock(
   <bigint key = chat_id>)` → false → WARNING «другой прогон уже идёт» + skip; unlock +
   close — в `finally`. PG недоступен на этом шаге → WARNING + skip (fail-open).
2. **Условия прогона** (для `manual=True` — только пп. а/б; для авто — все):
   (а) профиль существует (резолв chat_id) и `is_active`; отсутствует → WARNING+skip;
   (б) `auto_enabled` (профиль) — иначе skip (авто-тик НЕ тратит токены; «Сгенерировать сейчас»
   при выключенном — отсекается уже на уровне API 409);
   (в) авто: `hot.get("flags.lore_auto_enabled", settings.LORE_AUTO_ENABLED)` — иначе skip;
   (г) авто: период — `last_auto_at IS NULL OR last_auto_at + make_interval(hours =>
   auto_period_hours) <= now()` (колонка, см. D1/Q3);
   (д) авто+manual: **cooldown** — in-memory `dict[chat_id, mono_time завершения прогона]`;
   с момента последнего ЗАВЕРШЁННОГО прогона прошло < `hot.get(
   "limits.lore_generate_cooldown", settings.LORE_GENERATE_COOLDOWN)` секунд → skip. Ручной
   generate cooldown ИГНОРИРУЕТ (Q4: рука человека — исключение); слой памяти сбрасывается
   рестартом процесса.
3. **Окно сообщений** (SQLite-ЧТЕНИЕ через `db`; актуальный chat_id после резолва):
   `since_ts = now - auto_window_hours*3600`. SQL-фильтр «осмысленности» (Q5):
   `text IS NOT NULL AND length(trim(text)) >= limits.lore_min_message_chars (20)
    AND substr(trim(text), 1, 1) <> '/' AND (user_id IS NULL OR user_id <> $bot_id)`
   — команды `/…` исключаются, медиа-без-текста (NULL/короткие плейсхолдеры) исключаются
   правилом длины, бот-строки исключаются по user_id (прецедент summary.py:166), импортированные
   строки (`user_id IS NULL` — история без автора) ВКЛЮЧАЮТСЯ (Q5). Порядок:
   (1) `SELECT COUNT(*)` по фильтру ≥ `hot.get("limits.lore_min_messages", settings.LORE_MIN_MESSAGES)`
   → нет → WARNING+skip (порог не набран);
   (2) выборка строк по фильтру `ORDER BY timestamp DESC LIMIT hot.get("limits.
   lore_window_max_messages", settings.LORE_WINDOW_MAX_MESSAGES)` → reverse (ASC).
   Выполняется прямым `db.db.execute` (read-only) — сигнатуры `services/database.py` НЕ меняются
   (RUNTIME WARNING: только чтение).
4. **Сборка merge-контекста** (формат §3.6): текущий `auto_lore` (если пуст — INIT-режим) +
   строки окна `[%Y-%m-%d %H:%M] author_name: text` (author_name пуст → `user_id` строкой)
   + чат-уровневые protected-факты (`user_name IS NULL`, выборка через `db.db`, ИСКЛЮЧАЯ
   легаси-константу `CHAT_LORE_2661910336` — она же в manual после сида). Бюджет окна:
   строки собираются от свежих к старым, пока суммарно ≤ `hot.get("limits.lore_window_max_chars",
   settings.LORE_WINDOW_MAX_CHARS)` (свежий конец сохраняется — прецедент «режется с конца»).
5. **LLM-вызов (Q4):** единый клиент `LLMClient.generate(messages, temperature=None)` —
   `[{"role": "system", "content": <SYSTEM_PROMPT>}, {"role": "user", "content": <контекст>}]`.
   Таймауты/ретраи/фолбэк — ВНУТРИ llm_client (существующие `models.llm_*`, total-budget,
   каскад ключей) — новых таймаутов НЕ вводим. `limits.lore_max_words` подставляется в текст
   промпта при сборке (число из `hot.get`). Ошибка LLM → WARNING+skip (профиль не тронут).
6. **Запись результата:**
   - ответ после `strip()` равен ровно `UNCHANGED` (регистронезависимо) → `mark_auto_done`
     (метка периода без истории);
   - иначе текст нормализуется (strip, схлопывание пустых строк до абзацев) и если он НЕ равен
     текущему `auto_lore` → `set_auto` (история `field='auto'`, `changed_by NULL`, NOTIFY);
     равен → `mark_auto_done`;
   - возврат `{"status": "ok", "changed": bool}`; skip-пути возвращают `{"status": "skipped",
     "reason": ...}`; исключения → WARNING + `{"status": "failed"}`.

### 3.6 `services/lore_prompts.py` — канон промптов и форматов (C1)

Новый файл. Верх файла — две КАНОН-константы (правки — только через PR, как все каноны); ниже —
чистые функции форматирования (не канон): `format_lore_block(manual, auto, cap_chars)`,
`truncate_with_marker(text, limit)`, `is_unchanged_response(text)`, `normalize_lore(text)`.
Переменная `{max_words}` подставляется из горячего ключа при каждом вызове.

**`LORE_MERGE_SYSTEM_PROMPT`** (точный текст канона, русский; без кавычек-ёлочек и длинных тире):

```
Ты архивариус чата. У тебя есть текущий лор чата, новые сообщения за последнее время
и защищённые факты о чате.

Обнови лор: сохрани всё постоянное (история чата, ключевые люди и их статусы, мемы,
устоявшийся вайб), перепиши устаревшее, разреши противоречия. Игнорируй микро-события:
разовые шутки, бытовые реплики, то, что не имеет значения для новичка.

Верни связный текст на русском, 1-3 абзаца, максимум {max_words} слов, в стиле сообщений
этого чата. Не используй кавычки-ёлочки и длинные тире.

Если за окно не случилось ничего глобального и лор обновлять не нужно, верни ровно
строку: UNCHANGED
```

**`LORE_INIT_SYSTEM_PROMPT`** (когда `auto_lore` пуст — первичная генерация из окна):

```
Ты архивариус чата. По сообщениям чата за последнее время составь лор чата: кто эти
люди, чем живёт чат, ключевые мемы, истории, статусы, вайб.

Верни связный текст на русском, 1-3 абзаца, максимум {max_words} слов, в стиле сообщений
этого чата. Не используй кавычки-ёлочки и длинные тире.

Если в окне нет ничего глобального, верни ровно строку: UNCHANGED
```

**Формат user-контента** (merge-режим):

```
Текущий авто-лор чата:
{auto_lore | «(нет)»}

Новые сообщения чата (окно):
[2026-09-05 14:03] Саша: ну что, кто завтра идёт?
[2026-09-05 18:41] Ксюша: ахахах, вспомнили
...

Защищённые факты о чате:
- факт (без legacy-константы CHAT_LORE_2661910336)
```

INIT-режим — без секции «Текущий авто-лор», остальное то же.

**Инжект-блок** (Q1; используется direct_chat и persona-карточкой):

```
<chat_lore>
{manual_lore}
---
{auto_lore}
</chat_lore>
```

- Оба поля пусты → блока нет (пустой блок не рендерится, H2).
- `---` ставится ТОЛЬКО когда непусты оба поля.
- Содержимое экранируется `escape_xml_text` (как protected-факты).
- Cap: суммарно ≤ `limits.lore_inject_max_chars` (3000). Урезается в первую очередь `auto_lore`
  (по границе абзаца, затем предложения), при необходимости — `manual_lore`; при обрезке в конец
  добавляется маркер `\n…[обрезано]`.

### 3.7 `handlers/chat_lifecycle.py` — lifecycle (D1/D2)

Новый модуль, роутер `chat_lifecycle_router`, DI — модульный `setup_chat_lifecycle(store)`
(прецедент `setup_presence`); регистрация в `bot.py` — ДОБАВОЧНЫЙ инклуд рядом с
`slava_presence_router` (зона ~:483, порядок существующих не менять). Требование Group Privacy:
chat_member-хендлеры приходят только по апдейтам с правами — узкий фильтр по боту обязателен.

1. `chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> IS_MEMBER))` —
   если `new_chat_member.user.id != bot.id` → `UNHANDLED`; иначе `ensure_profile(chat_id)` +
   `set_active(chat_id, True)` (существующие тексты/настройки не трогаются).
2. `chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_MEMBER >> IS_NOT_MEMBER))` —
   если `old_chat_member.user.id != bot.id` → `UNHANDLED`; иначе `set_active(chat_id, False)`.
3. `message(F.migrate_to_chat_id)` (aiogram 3: `old = message.chat.id`, `new =
   message.migrate_to_chat_id`; service-message, хендлер узкий — не конфликтует с широкой
   direct-chat зоной): `store.add_link(old, new)` → `store.migrate_profile(old, new)` (Q9-merge,
   WARNING при отсутствии профиля old — no-op) → NOTIFY внутри store. НЕ читает/пишет ничего в
   direct_chat-кэши (ленивый резолв делает остальное).

Точное место инклуда — «добавкой в существующую зону рядом с ~:483», мигрировать-хендлер должен
стоять ДО широких message-роутеров (aiogram порядок регистрации).

### 3.8 RBAC и API (E1; Q6/Q8)

**Секция.** `known_sections()` (`param_catalog.py:1072`) → `return set(CATEGORIES) | {
"access", "chat_lore"}`. Дефолты moderator/ролей НЕ расширяются: `chat_lore` выдаётся глобальным
админом через roles-UI. Валидация ролей (`routes.py:379`) подхватит секцию автоматически.

**Матрица доступа (Q6 — решение @Architect):**

| Роль | Какие чаты | Что может |
|---|---|---|
| Глобальный admin (роль `admin`/wildcard/`settings.ADMIN_USER_ID`) | все | всё: просмотр/правка/генерация/remap/история/CRUD `chat_admins` |
| moderator/custom-роль с `section.chat_lore` | ТОЛЬКО чаты со строкой `(telegram_id, chat_id)` в `chat_admins` | просмотр/правка/генерация/очистка/настройки/история; НЕ remap; НЕ POST/DELETE `chat_admins` |
| обычный юзер со строкой `chat_admins` | свой чат | то же, что moderator-section (для своего чата) |
| остальные | — | 403 |

Вкладка «Лор чатов» видна: admin (wildcard), moderator/custom с секцией, а также юзерам со
строками `chat_admins` (фронт: `canViewTab` для типа `chat_lore` = `hasPerm('section.chat_lore')
|| wildcard || (probe-список непуст)`, см. §3.10). Moderator с секцией, но без строк → вкладка
видна, список пуст («Нет чатов с доступом»).

**API-модуль `web/api/chat_lore.py`** — `APIRouter`, все эндпоинты под `Depends(get_tma_user)`;
включение — `web/app.py:96` рядом с `api_router` (`app.include_router(chat_lore_router,
prefix="/api")`). Кастомная проверка чата: `can_access_chat(cache, store, telegram_id, chat_id)`
по матрице (админ → да; иначе `perms.sections` содержит `chat_lore` И строка `chat_admins`, либо
строка chat_admins у любого юзера; иначе 403). DI: `store`/`cache`/`worker` читаются из
`request.app.state` (фабрика `create_app` расширяется: `app.state.chat_lore_store/cache/worker` —
заполняются в `bot.py` до `create_app`). `chat_id` в URL — int64 (отрицательные допустимы).

Коды ошибок по конвенции 84.5: 401 (нет initData) / 403 (нет права) / 404 (профиль не
существует у доступного чата) / 409 (конфликт optimistic-метки или недопустимое состояние) /
422 (валидация). 

| Метод | Путь | Тело/параметры | Ответ | Комментарий |
|---|---|---|---|---|
| GET | `/chat_lore/chats` | — | `[{chat_id, manual_preview, auto_preview, has_manual, has_auto, auto_enabled, is_active, updated_at}]` | admin/moderator-section-право → все профили; юзер → JOIN `chat_admins` (только свои); превью ~80 симв.; неактивные включены с пометкой `is_active=false` (решение: не скрывать, диагностика) |
| GET | `/chat_lore/{chat_id}` | — | profile (полный объект, поля §3.2) | резолв chat_id; 403/404 по матрице |
| PUT | `/chat_lore/{chat_id}` | `{manual_lore: str, updated_at: str}` | 200 profile | `manual_lore` ≤ 4000 симв. → 422; история `field='manual'`, changed_by=telegram_id; Q8: `updated_at` — ОБЯЗАТЕЛЕН в теле (ISO-8601), при рассинхроне — 409 `{"detail": {"code":"conflict", "current_updated_at": …}}` |
| POST | `/chat_lore/{chat_id}/generate` | — | 200 `{status:"ok", changed: bool}` | auto_enabled=false профиля → 409 detail `auto_disabled`; синхронный `generate_for_chat(manual=True)` |
| POST | `/chat_lore/{chat_id}/clear_auto` | — | 200 profile | история `field='auto'` old=текст/new='', changed_by=telegram_id; `last_auto_at=NULL` |
| PUT | `/chat_lore/{chat_id}/settings` | `{auto_enabled?, auto_period_hours?, auto_window_hours?, updated_at}` | 200 profile | период/окно 1..720 → 422; 409 optimistic; по-полевая история §3.3 |
| POST | `/chat_lore/{chat_id}/remap` | `{new_chat_id: int}` | 200 profile-нового чата | только глобальный admin (иначе 403); merge Q9; 404 — профиля нет |
| GET | `/chat_lore/{chat_id}/history` | `?limit=100` | `[{created_at, field, changed_by, is_ai, old_value, new_value}]` | DESC; is_ai = changed_by IS NULL |
| GET | `/chat_lore/admins?chat_id=` | — | `[telegram_id]` | для своего/доступного чата |
| POST | `/chat_lore/admins` | `{chat_id, telegram_id}` | 200 | ТОЛЬКО глобальный admin; история `field='chat_admin'` |
| DELETE | `/chat_lore/admins?chat_id=&telegram_id=` | — | 200 | ТОЛЬКО глобальный admin; история `field='chat_admin'` |

### 3.9 Инжект в direct_chat (F1; Q1)

**Точки сборки контекста** (полный список — проверен по коду):

1. `_build_user_content` (direct_chat_service.py:402-441) → вызов `_build_protected_facts`
   (:421, блок `("protected", …)`) — основной путь каждого ответа.
2. `build_persona_card` (:765-795) — карточка `/persona` (читает protected напрямую, :778).
3. Промпт/суммари-пути, фактчек, поиск — чат-лор НЕ инжектится (не меняем: только direct).

**Новый приватный хелпер direct_chat_service** `async _chat_lore_state(chat_id) -> tuple[bool,
str]` (возвращает `(pg_lore_active, block)`, где block — строка `<chat_lore>…</chat_lore>` или
`""`):

1. `hot.get("flags.lore_inject_enabled", settings.LORE_INJECT_ENABLED)` == False → `(False, "")`
   (ровно старое поведение).
2. `cache.get(chat_id)` (инъекция `ChatLoreCache` в `DirectChatService` — новый опциональный
   конструктор-параметр `chat_lore_cache=None`; `None` → выключено → старое поведение; тесты и
   другие вызовы без изменений). Исключение/PG-down → WARNING с дедуп-счётчиком (не спамить,
   раз в 50 попыток) → `(False, "")`.
3. Профиля нет ИЛИ `not is_active` ИЛИ оба поля пусты → `(False, "")`.
4. Иначе → блок по §3.6 (cap `limits.lore_inject_max_chars`), `(True, block)`.

**Изменения `_build_protected_facts`** (:625-641): добавить параметр
`include_chat_level: bool = True` (дефолт сохраняет поведение). В `_build_user_content` порядок
(Q1, финальная механика дедупа):

- до сборки protected: `lore_active, lore_block = await self._chat_lore_state(chat_id)`;
- `_build_protected_facts(chat_id, target_name, include_chat_level=not lore_active)` —
  при активном PG-лоре SQLite-канал chat-level (`user_name IS NULL`) целиком исключается из
  protected-блока (это и есть канал легаси-лора — текст константы или иные chat-level факты
  раунда 5; user-level protected-факты не затрагиваются);
- если `lore_block` непуст — сразу ПОСЛЕ protected в `blocks` добавляется
  `("lore", lore_block)`.

**Бюджет** `_apply_context_budget` (:445-517) НЕ трогается: kind `"lore"` не входит в `limits`
и не входит в порядок урезания → блок не режется, а итоговый `[texts[kind] for kind, _ in
blocks if texts[kind]]` сохраняет позицию после protected. Защита от раздувания — только cap до
инжекта (§3.6). Регресс-инварианты: профиль есть/лоры пусты → блока нет и `include_chat_level`
остаётся True (старое поведение); `flags.lore_inject_enabled=false` → старое поведение целиком;
профиля нет → старое поведение (SQLite-константа на месте, дублей нет).

**Persona-карточка**: при `lore_active` — `get_protected_facts(..., include_chat_level=False)` и
текст PG-лора добавляется первой «строкой» списка (многострочный текст одним элементом;
счётчик «знаю о тебе: N фактов» считает лор как +1 — формат VERBATIM сохраняется, как в раунде
5, когда на этом месте были легаси-чат-факты). При неактивном PG-лоре — как сейчас.

### 3.10 Фронт TMA (E2)

**`web/app.js`:**

- `TABS` += `{ id: 'chat_lore', icon: '📜', label: 'Лор чатов', type: 'chat_lore' }`
  (не `config`-тип — свой рендер; `tabCategories` вернёт пусто → штатный `canViewTab` не
  сработает, добавляется ветка в `canViewTab`: `tab.type === 'chat_lore'` → `wildcard || section
  'chat_lore' || this.chatLoreChats.length > 0`).
- При первом показе вкладки (ветка в `setTab`): `loadChats()`; для юзеров без секции —
  «probe»: вызов `api('/api/chat_lore/chats')`, 403 → вкладка остаётся скрытой (пустой список
  НЕ показываем).
- Методы: `loadChats`, `loadProfile(chatId)`, `saveManual` (409-обработка → модалка «Профиль
  изменён — перезагрузить?» → повторный `loadProfile`), `saveSettings` (та же 409-обработка),
  `generateNow`, `clearAuto` (confirm), `remapChat(newId)` (модалка-подтверждение «данные
  профиля будут перенесены»), `loadHistory`, `loadChatAdmins/addChatAdmin/removeChatAdmin`
  (только глобальный admin). Переиспользуются `api()` (:264), тосты/модалки прецедентов
  user-aliases-admin/memory_rag. 401 → редирект-сообщение; 404 → «профиль не найден».
- Данные: `chatLoreChats`, `chatLoreProfile`, `chatLoreHistory`, флаги `chatLoreSaving`,
  `isGlobalAdmin` (для кнопок remap/admins).
- `isGlobalAdmin = me.role_name === 'admin' || permissions.wildcard`.

**`web/index.html`** — ветка `v-else-if="activeTab === 'chat_lore'"`:

- layout «селектор чатов (слева) + карточка»: список `chat_id` + превью + бейджи источников
  (`manual`/`auto`/оба), пометка неактивного чата;
- блок Manual: `<textarea>` (лимит 4000, счётчик символов) + «Сохранить» (409-модалка);
- блок Auto: read-only текст с бейджем «авто» + «обновлено: {updated_at}»; тумблер
  `auto_enabled`; инпуты `auto_period_hours`/`auto_window_hours` (1..720) + «Сохранить
  настройки» (409-обработка); кнопки: «Сгенерировать сейчас» (видна при `auto_enabled`),
  «Очистить авто-лор» (confirm);
- «Перепривязать chat_id…» (только глобальный admin): модалка (старый id read-only, поле
  нового id, предупреждение «данные профиля будут перенесены»);
- «История»: модалка-timeline DESC: дата; кто — «бот/ИИ» при `changed_by IS NULL`, иначе
  `telegram_id` (имена через UserService НЕ подтягиваем — решение Q7: без доп. сервиса);
  бейдж-перевод field (`manual` → «ручной лор», `auto` → «авто-лор», `auto_enabled` →
  «автогенерация», `auto_period_hours` → «период», `auto_window_hours` → «окно», `remap` →
  «переезд», `chat_admin` → «админ чата»); old/new блоками, каждый обрезан фронтом до ~300
  символов, «было → стало»; для больших текстов — построчная подсветка добавленных/удалённых
  строк БЕЗ библиотек (простейший split-построчный diff: строки, есть только в new — зелёным,
  только в old — красным);
- блок «Админы чата» (глобальный admin): список telegram_id + добавить (input id)/удалить.

**Аудит-тест фронта** `tests/test_frontend_tab_mapping.py`: тесты конфиг-вкладок НЕ ломаются
(chat_lore — не config-группа). По образцу H3.2 добавляются ассерты на: TABS-запись (id/label/
type), ветку `activeTab === 'chat_lore'` в index.html, наличие ключевых методов app.js
(`loadChats/loadProfile/saveManual/saveSettings/generateNow/clearAuto/remap/loadHistory`),
маркер-строку 409-обработки в `saveManual`.

### 3.11 Параметры REGISTRY и settings-поля (C2; «Settings-поля парно»)

Новые группы (в `GROUPS`, приложением в конец списков; перенумерация order не требуется):

```python
GroupSpec("limits_lore", "limits", "Лор чатов",
          "Авто-лор: пороги окна, генерация, инжект в контекст.", 21),
GroupSpec("flags_lore",  "flags",  "Лор чатов",
          "Рубильники лора чатов: воркер, авто-генерация, инжект.", 6),
```

Группы попадают на конфиг-вкладку «Лимиты и Модули» (TAB_LIMITS rules используют `except` —
новые группы включаются автоматически, тест `test_limits_tab_excludes_memory_groups` остаётся
зелёным; app.js-зеркало TAB_LIMITS не меняется).

Записи `REGISTRY` (туплы `_FLAGS`/`_LIMITS`; категории limits/flags — существующие,
`SEED_CATEGORIES` не меняется). Для каждой — парное поле `Settings` в `config/settings.py`
(дефолты сидятся в bot_settings при init; .env.example не меняем — I1: новых документированных
env нет; `_env_*`-чтение дефолтами не ломает):

| pg_key | Settings-поле | type | default | title_ru / смысл |
|---|---|---|---|---|
| `flags.lore_worker_enabled` | `LORE_WORKER_ENABLED` | bool | True | «Лор чатов: фоновый воркер» — планирует тик-цикл |
| `flags.lore_auto_enabled` | `LORE_AUTO_ENABLED` | bool | True | «Лор чатов: авто-генерация» — авто-прогоны разрешены (manual может игнорировать) |
| `flags.lore_inject_enabled` | `LORE_INJECT_ENABLED` | bool | True | «Лор чатов: инжект в контекст» — off = старое поведение |
| `limits.lore_min_messages` | `LORE_MIN_MESSAGES` | int | 15 | Порог «осмысленных» сообщений в окне для авто-прогона |
| `limits.lore_min_message_chars` | `LORE_MIN_MESSAGE_CHARS` | int | 20 | Мин. длина «осмысленного» сообщения |
| `limits.lore_window_max_messages` | `LORE_WINDOW_MAX_MESSAGES` | int | 300 | Потолок строк окна для LLM |
| `limits.lore_window_max_chars` | `LORE_WINDOW_MAX_CHARS` | int | 20000 | Потолок символов окна |
| `limits.lore_max_words` | `LORE_MAX_WORDS` | int | 150 | Бюджет авто-лора в словах (подставляется в промпт) |
| `limits.lore_inject_max_chars` | `LORE_INJECT_MAX_CHARS` | int | 3000 | Cap блока лора в контексте |
| `limits.lore_tick_minutes` | `LORE_TICK_MINUTES` | int | 30 | Период тик-цикла воркера (мин) |
| `limits.lore_generate_cooldown` | `LORE_GENERATE_COOLDOWN` | int | 60 | Мин. пауза между прогонами одного чата (manual игнорирует) |

Чтение везде — `hot.get(key, settings.<FIELD>)` (прецедент T-755). `limits.lore_max_tokens`
из PM-раздела A НЕ вводится (D4; бюджет выражается словами — см. §3.1). Группы-рендер:
`flags_lore`/`limits_lore`.

### 3.12 Сид легаси-лора (G1)

`scripts/seed_chat_lore.py` — автономный скрипт (НЕ manage.py; runtime-warning):
подключение к PG (конфиг как у PgDatabase — env `POSTGRES_DSN`), идемпотентный сид:

```sql
INSERT INTO chat_profiles (chat_id, manual_lore, auto_enabled, is_active)
VALUES (-1002661910336, $текст_константы_CHAT_LORE_2661910336, TRUE, TRUE)
ON CONFLICT (chat_id) DO NOTHING
```

Отчёт в stdout (`inserted/skipped/existing-manual-not-empty`); явное правило: строка уже есть и
`manual_lore` непустой → НЕ затирать (ручные правки приоритетнее). Текст — из
`services.chat_lore.CHAT_LORE_2661910336` (дословно). Без side-эффектов на SQLite; NOTIFY после
INSERT не требуется (кэш пуст до старта бота; инвалидация не нужна). Запуск — шаг @DevOps при
деплое (I2).

---

## 4. Edge cases и закрытие Q1–Q9 (сводно)

| Q | Решение (эта спецификация) | Где |
|---|---|---|
| **Q1 Инжект/дубли** | Отдельный блок `<chat_lore>` СРАЗУ ПОСЛЕ `<protected_facts>` (не внутри); формат §3.6; не режется бюджетом; cap `limits.lore_inject_max_chars=3000` с маркером `…[обрезано]` (режется auto первым). Дедуп с легаси: **(1)** PG-профиль есть и (manual или auto непуст) → инжектим PG-лор, а SQLite chat-level факты (`user_name IS NULL` канал — весь легаси-лор) из `<protected_facts>` исключаются (`include_chat_level=False`); **(2)** иначе → ровно старое поведение (SQLite chat-level показываются). Легаси-строки SQLite НЕ удаляются и НЕ мигрируются (RUNTIME WARNING); дубль невозможен даже сразу после сида (сид кладёт тот же текст в manual → канал chat-level исключён). При профиле «есть, но пуст» — тоже старое поведение (fallback, контент не теряется). | §3.6, §3.9 |
| **Q2 Кэш** | RAM `dict[chat_id → LoreProfile+ts]`, load-on-demand через store; инвалидация: NOTIFY `lore_updated(chat_id)` → удалить ключ; TTL-фолбэк 120 с (потеря NOTIFY); asyncio-защита (Lock + coalescing miss'ов); PG down → пусто/None (fail-open, SQLite-fallback жив); отдельный модуль `services/lore_cache.py`; `resolve_chat_id` не кэшируется. | §3.4 |
| **Q3 Период/окно** | Колонка `last_auto_at TIMESTAMPTZ NULL` добавлена в `chat_profiles` (расширение схемы юзера — допустимо ТЗ). Ставится воркером при успешном прогоне (смена текста ИЛИ UNCHANGED) и ручной генерацией; NULL после `clear_auto`; manual-правки её НЕ трогают. Условие авто: `auto_enabled AND is_active AND flags.lore_auto_enabled AND (last_auto_at IS NULL OR last_auto_at + auto_period_hours ≤ now()) AND count(осмысленных в окне auto_window_hours) ≥ lore_min_messages`. Тик — настройка `limits.lore_tick_minutes=30` (не жёстко), флаг `flags.lore_worker_enabled`. | §3.2, §3.5 |
| **Q4 LLM-вызов** | `llm_client.generate` (chat), temperature None; единый клиент; таймауты/ретраи/фолбэк — существующие внутри клиента (новых нет). Окно: `db` (SQLite-чтение) `get_smart_window`-эквивалент по актуальному (резолвнутому) chat_id; лимиты `lore_window_max_messages=300`/`lore_window_max_chars=20000`, свежий конец сохраняется. Строки `[YYYY-MM-DD HH:MM] Имя: текст`. Advisory-лок — отдельное соединение (не из пула) на время прогона, `pg_try_advisory_lock`, unlock в finally. Cooldown `lore_generate_cooldown=60` — in-memory, manual игнорирует. LISTEN-реконнект: WARNING + retry 60 с. | §3.5 |
| **Q5 Осмысленность** | `text` непуст после trim; `len ≥ lore_min_message_chars` (20); НЕ начинается с `/`; `user_id` ≠ bot_id; media-без-текста и короткие плейсхолдеры отсекаются правилом длины; пересланные с подписью ≥ 20 — считаются; импортированные (`user_id NULL`) — считаются. SQL-фильтр §3.5.3. | §3.5 |
| **Q6 RBAC** | `known_sections() += 'chat_lore'`; moderator/custom-роль с секцией НЕ получает «все чаты» — только свои `chat_admins`; глобальный admin — все; per-chat admin — свой чат; remap + POST/DELETE `chat_admins` — ТОЛЬКО глобальный admin; фронт-зеркало по матрице §3.8 (hasPerm + probe-список чатов). | §3.8, §3.10 |
| **Q7 История** | Схема по Q7 (field-энум `manual|auto|auto_enabled|auto_period_hours|auto_window_hours|remap|chat_admin`, `changed_by NULL` = бот/AI); настройки — по-полевые строки (не JSON); `clear_auto` → `field='auto'` (old=текст, new=''); `set_active`/lifecycle — историю НЕ пишет; UI: timeline «когда, кто, поле, было→стало», old/new обрезаются до ~300 символов фронтом, простейший построчный diff (добавлено/удалено цветом), имена НЕ подтягиваются (бот/NULL → «бот», иначе telegram_id). | §3.2, §3.3, §3.10 |
| **Q8 If-match** | Передача ожидаемого `updated_at` ТЕЛОМ JSON (обязательное поле `updated_at` в PUT manual и PUT settings) — единообразно; If-Match-заголовок НЕ вводим. Сервер: `WHERE chat_id=? AND updated_at=$expected::timestamptz` → 0 rows → `ChatLoreConflict` → 409 `{"detail":{"code":"conflict","current_updated_at": …}}`. Фронт: при 409 — диалог «Профиль изменён — перезагрузить?» → loadProfile. | §3.3, §3.8 |
| **Q9 Remap/merge** | `POST /{chat_id}/remap {new_chat_id}` (и migrate-хендлер) — общий `migrate_profile(old, new)` в ОДНОЙ транзакции: (1) upsert `chat_links(old→new)` (актуализация цепи); (2) профиль old (после резолва old через links) — если профиля new нет: `UPDATE chat_profiles SET chat_id=new WHERE chat_id=old` (чистый перенос); если new занят — MERGE: `manual_lore = old.manual_lore если непуст, иначе new.manual_lore` (старый приоритетнее), `auto_lore = new.auto_lore или old.auto_lore` (при переезде авто не теряем до следующей генерации; воркер всё равно пересоберёт), `last_auto_at = max(old, new)` (период от последнего успешного прогона), `auto_enabled = old.auto_enabled OR new.auto_enabled`, `is_active = old.is_active OR new.is_active`, периоды/прочие скаляры — от old при наличии, иначе new; старый профиль — DELETE (физический перенос; история `field='remap'` old=new-строки); (3) `chat_admins`: чистый перенос — `UPDATE chat_admins SET chat_id=new WHERE chat_id=old`; merge — `INSERT … SELECT new … ON CONFLICT DO NOTHING` + DELETE строк old; (4) NOTIFY old+new; (5) 404 — профиля old нет. 409 на занятый new НЕ возвращаем (D5). | §3.3, §3.7 |

Прочие edge cases:

- **Гонка период/окно**: последний шаг `generate_for_chat` может обнаружить, что `last_auto_at`
  уже обновился (параллельный ручной прогон) — защита: advisory-лок (serialize) + перепроверка
  `updated_at`/`last_auto_at` профиля внутри транзакции записи (WHERE-условие) → 0 строк =
  конкурентный прогон уже записал — не пишем повторно.
- **Смена auto_window_hours/периода на лету** — валидация диапазона 1..720 (422) на API;
  воркер читает актуальные значения профиля каждый прогон.
- **UNCHANGED и ручная правка**: если между выборкой контекста и записью юзер изменил manual —
  auto-запись всё равно легальна (поля независимы, D-инвариант №1); optimistic-метка воркером
  не используется.
- **resolve-цепочки**: `resolve_chat_id` возвращает исходный id при глубине > 5 или цикле
  (безопасный возврат; WARNING раз в N).
- **NOTIFY до LISTEN** (бот писал, а подписки нет): TTL 120 с лечит.
- **Двойной инклуд роутера lifecycle при Group Privacy**: чужие события → `UNHANDLED`.
- **Повторный remap на тот же old**: upsert `chat_links` актуализирует; история — ещё одна
  запись `remap` (аудит переездов).
- **Профиль несуществующего чата в списке воркера**: `generate_for_chat` → профиль есть, но
  сообщений нет/период не прошёл → skip WARNING; без LLM-вызова.
- **Кавычки/тире в тексте лора от LLM**: промпт запрещает; пост-нормализация НЕ исправляет
  (лор — контент, не канон-текст).

---

## 5. Acceptance criteria (проверяемое)

Нумерованные критерии готовности (AC) — каждый проверяется тестом из §6 или live-шагом I2:

1. **AC-1 Инжект manual+auto**: при PG-профиле с непустыми полями контекст direct_chat содержит
   `<chat_lore>` сразу после `<protected_facts>`, оба текста на месте, разделитель `---`;
   при активном PG-лоре legacy-константа и прочие SQLite chat-level факты в `<protected_facts>`
   ОТСУТСТВУЮТ (нет дубля); у юзера без профиля — старое поведение (константа на месте).
2. **AC-2 Порог и флаги воркера**: `auto_enabled=false` на профиле ИЛИ `flags.lore_auto_enabled
   =false` → авто-прогон чата не вызывает LLM (мок не вызван); `flags.lore_worker_enabled=false`
   → тик-джоб не зарегистрирован; период не прошёл (свежий `last_auto_at`) → skip; окно
   < `lore_min_messages` → skip с WARNING.
3. **AC-3 UNCHANGED**: LLM-ответ «UNCHANGED» → `auto_lore` не меняется, история НЕ пишется,
   `last_auto_at` обновляется (следующий прогон — только через период); ответ, идентичный
   текущему авто-лору, — то же самое.
4. **AC-4 Запись генерации**: изменённый ответ → `auto_lore` обновлён + история
   `field='auto'`, `changed_by NULL`, NOTIFY; manual при этом не затронут.
5. **AC-5 409/optimistic**: PUT manual/settings со старым `updated_at` → 409 с
   `current_updated_at`; актуальная метка → 200 + история `field='manual'`,
   `changed_by=telegram_id`.
6. **AC-6 NOTIFY-инвалидация**: юнит с фейковым listener: `pg_notify` после апдейта →
   ключ кэша удалён; следующий `get` — свежие данные; payload == `str(chat_id)`.
7. **AC-7 Remap**: `migrate_profile` переносит профиль на новый id (данные/настройки
   сохранены), пишет `chat_links(old→new)`, переносит `chat_admins`, пишет историю
   `remap`; повторный migrate на занятый new → merge без потери непустого manual; старый
   профиль удалён; NOTIFY old+new; чтения по старому id резолвятся на новый.
8. **AC-8 Lifecycle**: my_chat_member бота вход → профиль создан `is_active=true` (тексты
   пусты/дефолты), выход/kick → `is_active=false`; события ДРУГИХ юзеров профиль не трогают.
9. **AC-9 Права**: аноним 401; «не-участник» 403; глобальный admin — все чаты/операции;
   moderator с секцией — только свои `chat_admins`-чаты; chat-admin — свой чат 200/чужой 403;
   remap и POST/DELETE admins для moderator-section и chat-admin — 403; GET /chats фильтрует
   по роли.
10. **AC-10 «Сгенерировать сейчас»**: кнопка видна и API доступен ТОЛЬКО при
    `auto_enabled=true` (иначе 409 `auto_disabled` на API, кнопки нет на фронте); manual-прогон
    работает вне периода.
11. **AC-11 Лимиты/cap**: инжект-блок ≤ `lore_inject_max_chars` (3000), auto режется первым,
    маркер `…[обрезано]` присутствует; ручная правка > 4000 символов → 422; period/window вне
    1..720 → 422.
12. **AC-12 Фронт**: вкладка «Лор чатов» с правильной видимостью по ролям; методы app.js
    (loadChats/loadProfile/saveManual/saveSettings/generateNow/clearAuto/remap/loadHistory)
    присутствуют; 409-обработка saveManual вызывает перезагрузку профиля; timeline-история
    показывает field/old/new/changed_by.
13. **AC-13 REGISTRY/сид**: записи §3.11 корректны (категория/группа/тип/дефолт), hot.get с
    фолбэком работает без PG; `known_sections()` содержит `chat_lore`; moderator-дефолт не
    расширен; повторный прогон сида — no-op; непустой manual не затирается; текст сида ==
    `CHAT_LORE_2661910336`.
14. **AC-14 Регресс**: `tests/test_direct_chat.py`, `tests/test_chat_lore.py`,
    `tests/test_database.py`, `tests/test_frontend_tab_mapping.py` — без изменений сигнатур и
    зелёные; полный pytest → 0 failed; `git diff --check` чист.

---

## 6. Тесты, миграция и докатка

### 6.1 Тесты поимённо (H1–H3 + регрессы)

Новые файлы по конвенции `test_chat_lore_*.py`/`test_lore_*.py`:

- **`tests/test_chat_lore_store.py`** (H1.1/H1.2): повторный `init()` идемпотентен; 4 таблицы с
  ожидаемой схемой (PK/CHECK/индексы/дефолты, включая `last_auto_at`); store: get/list/ensure,
  атомарность транзакции «профиль+история+NOTIFY» (сбой на середине → полный откат), история с
  правильными field/old/new/changed_by (по-полевые settings, `clear_auto`→auto,
  chat_admin add/remove), `update_settings` без изменений — ни истории, ни NOTIFY; optimistic →
  `ChatLoreConflict(current_updated_at)`; NOTIFY-эмит (payload=str(chat_id), на UPDATE и remap —
  old+new); `mark_auto_done` без истории; chat_links add/resolve (цепочка old→new→newest, циклы/
  глубина>5 → исходный id); chat_admins CRUD; migrate_profile: чистый перенос + merge + admins
  + история remap.
- **`tests/test_chat_lore_api.py`** (H1.3): матрица доступов (401/403/200 по ролям §3.8, включая
  «moderator-section не видит чужие чаты», remap/POST-DELETE admins только глобальный admin);
  GET /chats фильтр по роли; PUT manual 200/409/422; generate: `auto_enabled=false` → 409
  `auto_disabled`, авто-прогон не вызван (мок воркера); clear_auto (old=текст/new='');
  remap 200 (перенос) — 409 НЕ тестируется (D5-замена: merge); history-формат; admins.
- **`tests/test_lore_worker.py`** (H2.1): SQLite-tmp + мок-стор/мок-llm: `auto_enabled=false` →
  skip; свежий `last_auto_at` (период не прошёл) → skip; `flags.lore_auto_enabled=false` →
  skip; cooldown → skip (manual игнорирует); осмысленных < `lore_min_messages` → skip; фильтр
  осмысленности (команды/короткие/медиа-плейсхолдеры исключены, импорт-строки включены);
  ≥ порога → merge-контекст по формату §3.6 (есть auto_lore + строки окна + chat-факты без
  legacy-константы) → мок-ответ пишет auto_lore + историю NULL + NOTIFY; UNCHANGED → только
  `mark_auto_done` без истории; ответ == старому → `mark_auto_done`; advisory-лок занят → skip;
  исключение генерации → fail-open (профиль не тронут); `manual=True` вне периода работает.
- **`tests/test_chat_lifecycle.py`** (H2.2): мок aiogram-событий — MEMBER бота → профиль
  `is_active=true` (дефолты), KICKED → false; чужие события → профиль не тронут; migrate →
  links + перенос + история remap; migrate на занятый new → merge (без затирания непустого
  manual).
- **`tests/test_direct_chat.py`** (дополнения, H2.3): инжект-блок при профиле (manual+auto, cap:
  длинный auto урезан по границе, manual цел); профиль есть/лоры пусты → блока нет + легаси
  chat-level на месте; профиля нет → старое поведение; PG-ошибка/кэш-None → fail-open;
  `flags.lore_inject_enabled=false` → старое поведение; активный PG-лор → легаси-константа НЕ
  дублируется; persona-карточка — PG-лор первой строкой вместо легаси-фактов.
- **`tests/test_chat_lore_registry.py`** (по образцу H3.1): REGISTRY-записи §3.11
  (категория/группа/тип/дефолты), фолбэк `hot.get(key, settings.<FIELD>)` без PG; новые группы
  `limits_lore`/`flags_lore` на вкладке TAB_LIMITS; `known_sections()` содержит `chat_lore`;
  moderator-дефолт без секции.
- **`tests/test_frontend_tab_mapping.py`** (расширение H3.2): TABS chat_lore, ветка index.html,
  методы app.js, 409-маркер saveManual.
- **`tests/test_seed_chat_lore.py`** (по образцу H3.3): 2 прогона на мок-PG — 1 вставка, повтор
  no-op; существующий непустой manual не затирается; текст сида == константе.

Регрессы (без изменений сигнатур): `test_chat_lore.py`, `test_database.py`, существующие
`test_webapp_*`, `test_config_cache.py` (`_FakePg`/`_FakePool` прецеденты переиспользуются/при
необходимости расширяются).

### 6.2 Миграция и докатка (порядок на проде)

**Порядок (по задачам I1→I2):**

1. **Код**: коммит (код + тесты + `plans/features/chat-lore-management-v2/` +
   `plans/backlog.md`); полный pytest → 0 failed; `git diff --check` чист; grep-проверка секретов.
2. **README** (I1): раздел «Лор чатов (v2.0)»: архитектура (PG-таблицы, NOTIFY, кэш, воркер),
   сид-команда `python scripts/seed_chat_lore.py`, краткий API-список, права (секция `chat_lore`
   в roles-UI + per-chat admin через раздел), параметры (тумблеры `flags.lore_*`, лимиты
   `limits.lore_*`), правило инжекта (PG-профиль приоритетнее SQLite-легаси; флаг off возвращает
   старое поведение). `.env.example` — без изменений.
3. **Бэкап перед деплоем**: SQLite-БД (как в прецедентах) + `pg_dump` bot_settings-схемы
   (новые таблицы создадутся при init; бэкап — для отката).
4. **Сервер**: `git pull --ff-only`; мягкий рестарт бота → journald: init-DDL новых таблиц
   (4 шт. + индексы), LISTEN-подключение `lore_updated`, старт воркера, ошибок нет.
5. **Сид** `python scripts/seed_chat_lore.py` (чат `-1002661910336`) — после рестарта, до
   live-проверок.
6. **Live-верификация (I2)**: профиль в `GET /chats`; ручная правка в TMA (вкладка видна,
   сохранение, 409-сценарий двумя вкладками); история-запись; блок лора в direct-контексте БЕЗ
   дубля с SQLite-фактом; «Сгенерировать сейчас» (лог воркера); тумблеры off/on
   (`lore_inject_enabled`/`lore_auto_enabled`/`lore_worker_enabled`).
7. **Архив/отчёт (I3)**: аппрув @Reviewer; перенос папки фичи в `plans/archive/`;
   `plans/backlog.md`; отчёт юзеру (что сделано, где UI, как выдать роль/добавить админа чата,
   настройки-ключи, что НЕ тронуто — SQLite-легаси и history-воркер, RUNTIME WARNING).
   Не-технические указания в README-раздел попадают от @DevOps.

**Откат**: PG-слой лора не влияет на SQLite-легаси (инжект при отсутствии профиля/выключенном
флаге = старое поведение); откат деплоя = откат коммита + рестарт. Таблицы при откате можно
оставить (CREATE IF NOT EXISTS идемпотентен, данные безвредны) либо удалить вручную.

### 6.3 Остаточные риски / открытые вопросы (минимум)

Официальных открытых вопросов нет (Q1–Q9 закрыты в §4). Некритичные пункты на инженерное
усмотрение при реализации (не архитектурные): точная строка-место инклуда
`chat_lifecycle_router` в `bot.py` (~:483, добавкой); иконка вкладки (📜 или аналог);
детали Vue-шаблонов модалок; порядок полей в профайл-объекте API.

**Риск-флаг (обязателен к прочтению DevOps/Reviewer):** решение D4/D5/D8 меняет формулировки
задач T-776 (REGISTRY-список), T-779/T-783 (remap без 409), T-785/H3 (списки тестов) и T-786
(README-список параметров) — при планировании/ревью эти задачи должны читаться вместе с §3.1.
