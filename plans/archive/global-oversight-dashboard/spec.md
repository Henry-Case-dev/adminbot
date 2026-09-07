# Спецификация: Global Oversight Dashboard (F-12)

**Эпик:** раунд 10 (07.09.2026), часть 3.1 (панель глобального админа) «Multi-chat scaling» (research §4 п. 2 «TMA-вкладка Чаты», §8). **Задачи:** T-914…T-924 (база HEAD `fac1b9f`).
**Статус:** спецификация @Architect (T-914) — закрывает Q1–Q5 раздела A `tasks.md`. Источники: F-7 (chat_params/RBAC/ключи-статусы), F-9 (permsoc-гейт), F-10 (gates/опции/worker_budget), F-11 (точка входа «Главная»).

---

## 1. Скоуп и инварианты

1. Просмотр/таргетированное управление — ТОЛЬКО для глобального админа (роль `global_admin`/wildcard); moderator/user/local → 403.
2. Данные — из существующих сервисов (PG-профили, chat_params-cache, feature_gates, worker_budget, chat_keys, SQLite-агрегаты последней активности) — **без новых таблиц** (исключение: никаких новых ДДЛ в этой фиче; F-7/F-10 уже добавили).
3. Kill-switch — **единый слой записи** `chat_params["gates"]`/`["keys"]` (F-7 `set_chat_params`), часть-1 и F-10 — те же руты: параллельных путей не плодим.
4. R17: никаких значений ключей (только `own|global|forbidden|none`-статусы и last4-маску для своей видимости — не отдаём raw).
5. SQLite-схема/инструменты истории — вне скоупа; PG down → карточка ошибки в UI (fail-open, бот не падает).

---

## 2. Q1 — Состав сводки (`ChatSummary`)

```python
@dataclass(frozen=True)
class ChatSummary:
    chat_id: int
    title: str                       # runtime-имя чата (см. §2.1)
    is_active: bool
    gates_opt_in: bool
    heavy: dict[str, bool]           # {'dream':..., 'nostalgia':..., 'lore_auto':...} — effective
    permsoc: bool                    # master permsoc (F-9 §3, effective)
    key_status: str                  # 'own' | 'global' | 'forbidden' | 'none'
    key_last4: str | None            # только для 'own' (маска, R17)
    allow_global: bool
    admins_count: int                # COUNT(chat_admins)
    last_active_ts: datetime | None  # MAX(ts) smart_messages (SQLite, дешёвая агрегация)
    budget: dict | None              # {calls:{used,limit}, tokens:{used,limit}} — day-chat row
```

### 2.1 Источники

- Название чата: кэш-мапа `{chat_id: str}` (TTL 10 мин, ключ-префикс `oversight.chat_title:`), первично — `bot.get_chat(chat_id).title` (асинхронно, в общем кору `build_summary`), фолбэк — «Чат {chat_id}». Кэш наполняется при первой сборке; пустой кэш не блокирует сводку.
- Профили: `PgDatabase`-запросы (`SELECT * FROM chat_profiles` —— `chat_id, is_active, chat_params, gates_opt_in, updated_at`) — кэш 60 с (прецедент ChatLoreCache: per-load + TTL-фолбэк + NOTIFY-инвалидация по `chat_params_updated`/`gates_updated`).
- Гейты: `services/feature_gates.py::gates_enabled` (+`permsoc_enabled` — F-9).
- Ключ-статус: `chat_keys` (exists `keys.llm_api_key` → `own`) + `chat_params["keys"]["allow_global"]` (+`global`, +`forbidden`; иначе `none` — глобальный ключ не задан).
- `admins_count` — `SELECT COUNT(*) FROM chat_admins WHERE chat_id = ?` (один group-by-запрос на все чаты).
- Активность — SQLite `SELECT chat_id, MAX(ts) FROM smart_messages WHERE chat_id IN (...) GROUP BY chat_id` (индекс (chat_id, ts); дешёвая агрегация, кэш 120 с на агрегат).
- `budget` — `worker_budget` (F-10) строка дня `chat:<id>` + лимиты REGISTRY.

### 2.2 Реализация

`services/oversight.py` (НОВЫЙ): `async def build_summary() -> list[ChatSummary]` (без тяжёлых N+1: 3-4 aggregate-запроса; кэш итога 60 с + refresh-инвалидация при любом POST/ключ-политике). Отдельный `get_chat_details(chat_id)` — та же смесь + истории.

---

## 3. Q2 — Kill-switch и «запрет глобального ключа»

### 3.1 Хранение — единое (JSONB-пространства, НЕ колонки)

- **Kill-switch фичи**: `chat_params["gates"][feature] = false` (feature ∈ {dream, nostalgia, lore_auto, permsoc}; 422 иначе) — запись через `set_feature_gate` (F-10 §2) — единый path с локальным управлением (без приоритетного «override-слоя»: приоритет — в §3.2).
- **Запрет глобального ключа**: `chat_params["keys"]["allow_global"] = false` — `(изменено @Architect T-914)`: JSONB-пространство вместо отдельной колонки `chat_profiles.allow_global_key` (простота+версифицируемость с `updated_at`; один write-path, один оптимизм).
- История: той же транзакций `field='gates'`/`field='chat_params'` с `changed_by=telegram_id`; у любой записи — undo-чтение предыдущего значения (тело ответа `{previous: true|false}`).
- NOTIFY: `chat_params_updated` (инвалидация чат-кэшей F-7, gates-кэша F-10).

### 3.2 Приоритет гейтов (✓ окончательная схема, согласована с F-7/F-10/F-9)

```
effective_gate(chat, feature) =
    1. chat_params["gates"][feature]  (если явно задан — его)
    2. hot.get("flags.<feature>_enabled", settings-дефолт)   (глобальный default-слой)
    3. False
```
Kill-switch = записать явно `gates[feature]=false` (приоритет 1 побеждает глобальный default). «Undo» = предыдущее значение (или `jsonb_remove` при отсутствии). Глобальный админ также может выключить всё через глобальные флаги (существующий config-UI) — тогда это приоритет 2 бьёт незаписанные чат-гейты, а явные чат-гейты — нет; документировано в README.

### 3.3 Семантика «запрет» для BYOK/резолва

- `allow_global=false` + собственный ключ чата → bot работает на ключе чата (конфиг не запрещает).
- `allow_global=false` + нет своего ключа → llm_client-резолв возвращает **None** («нет ключа»-путь F-7 §5.2): бот отвечает sandbox-фразой `content.no_key_reply` (или тишина, если настроено), **глобальный ключ НЕ тратится**.
- Глобальные ключи (`keys.llm_api_key`) при `allow_global=true` — под бюджетами F-7 (`limits.chat_global_key_budget_*`) или скип при переполнении (та же sandbox-цепочка).

---

## 4. Q3 — Права/разделение рутов

- Единственный новый гейт в `web/api/deps.py` — добавка `requires_global_admin` (dataclass-check: role_type global_admin или wildcard) — существующие сигнатуры не меняются (F-7-целостность).
- Таблица эндпоинтов (все — 401 без initData; 403 не-глобальный; 404 неизвестный чат):

| Метод | Путь | Тело | Ответ |
|---|---|---|---|
| `GET` | `/api/oversight/summary` | — | `{generated_at, chats: [ChatSummary], global_budget: {...}, errors: [...]}` |
| `GET` | `/api/oversight/chat/{chat_id}` | — | `ChatDetails` (+ admins: F-7 `/api/access`-источник, история 5 записей `chat_lore_history` по chat_id, gate=effective) |
| `POST` | `/api/oversight/chat/{chat_id}/killswitch` | `{feature, enabled, expected_updated_at?}` | 200 `{feature, enabled, previous, updated_at}`; 409 optimistic `{code:'conflict', current_updated_at}`; 422 feature ∉ домена |
| `POST` | `/api/oversight/chat/{chat_id}/global_key` | `{allow: bool, expected_updated_at?}` | 200 `{allow, previous, updated_at}`; 409 как выше |

- Разделение с part-1 `PUT /api/chat/{id}/gates` (F-10): **единая запись** — оба рута пишут в `chat_params["gates"][feature]` через `set_feature_gate`; oversight-рут — wrapper с хвостом 403/global-only+детальной историей. Конфликтов нет (оптимизм + последний пишущий побеждает; «разделение» — только read-витрина и права записи).

## 5. Q4 — Данные-зверная таблица/модалка (UI)

- **Зверю**: `refresh`-кнопка (ручной интервал 60 с — server-кэш уже обновяется; polling НЕ добавляем — десятки чатов, дешёво на запрос). Поиск-фильтр по названию/chat_id (instant, фронт). Сортировка: клик по колонкам (минимал: is_active, opt_in, key_status, admins) — локальная (фронт, без сервера).
- **Модалка деталей** (клик по строке): гейт-значения (3 чипа heavy + permsoc) с кнопками «Переключить удалённо…» (confirm «Фича выключится для чата — продолжить?»), «Запретить глобальный ключ»/«Разрешить» (confirm: «если нет своего ключа — бот перестанет использовать глобальные ключи (или отвечать)»), админов-список (F-7 API), последние 5 событий истории (лента), undo-кнопки после изменения (следующий шаг — значение previous).
- Реализация: `web/api/oversight.py` (НОВЫЙ, include после `api_router` — прецедент web/app.py:96-108), web/app.js методы `loadOversight`, `toggleKillswitch`, `toggleGlobalKey`, `openChatDetails`.

## 6. Q5 — Инвентарь + тест-инварианты

- Точки: `services/oversight.py` (НОВЫЙ), `web/api/oversight.py` (НОВЫЙ), `web/app.js` + `web/index.html` (карточка-вход на Главная / вкладка `oversight` per F-11), `tests/test_oversight.py` (НОВЫЙ).
- Используемые внешние сервисы: `services/chat_params.py` (set/get), `services/feature_gates.py` (гейты), `services/worker_budget.py` (budget day), `services/chat_keys.py` (key status), `services/pg_db.py` (профили), `services/database.py` (SQLite-агрегаты).
- Тест-инварианты:
  1. build_summary: состав полей корректен (мок-данные), кэш-инвалидация после записи, PG down → ошибки-массив + живые данные по остальным источникам.
  2. kill-switch/global_key: запись в chat_params + история + NOTIFY; повторный вызов с тем же значением → 200 без записи/409-протокол; undo → previous.
  3. «forbidden + no own» → llm_client sandbox-путь (мок — NOT вызывается глобальный). Интеграционный кейс F-7 §5.
  4. API-матрица: 401/403 (moderator/user/local), 404, 422, 409; R17-греп (raw-секреты не отдаются).
  5. Фронт-аудит маркеров (summary-методы, killswitch/globalKey, search-поле, модалка).
  6. Полный pytest → 0 failed; `git diff --check`.

## 7. Риски для @Builder

1. **Caches/timestamps**: `expected_updated_at` из модалки — использовать свежий `updated_at` при каждом open-детали (иначе 409-флуд).
2. **Ошибка PG при чтении**: build_summary возвращает `errors:[{source, code}]` и не падает — та же толерантность для SQLite.
3. **Names**: не пересекаться с F-7 `/api/access/chats` (эндпоинт-пути уникальны; список «моих» чатов в selector — НЕ тут).
4. **Лимит истории** (5 записей) — избегать нагрузки чат-истории при каждом refresh.
