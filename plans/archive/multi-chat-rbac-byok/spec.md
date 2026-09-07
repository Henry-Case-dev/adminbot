# Спецификация: Multi-chat — Granular RBAC + chat_params-слой + BYOK (F-7)

**Эпик:** раунд 10 (07.09.2026), часть 1 «Multi-chat scaling» (вариант A, research `plans/docs/multi-chat-scaling-research.md`, §4 пункт 3/6/7). **Задачи:** T-843…T-869 (база HEAD `fac1b9f`).
**Статус:** спецификация @Architect (T-843) — закрывает открытые вопросы Q1–Q9 раздела A `tasks.md`; источник дизайна для задач B–H и для связанных фич raundа (`permsoc-module-isolation` T-878, `feature-gates-worker-budget` T-890, `tma-ia-progressive-disclosure` T-903, `global-oversight-dashboard` T-914).
**Документы-источники:** `plans/docs/multi-chat-scaling-research.md`; `plans/features/multi-chat-rbac-byok/tasks.md` (раздел A + T-843); спецификация — НЕ дублирует тексты задач, а фиксирует решения.

---

## 1. Скоуп и инварианты

### 1.1 Что входит

(1) Роли Global Admin / Local Admin / Moderator / User (+ Custom через `bot_roles`), (2) per-param права `param_permissions` (view/edit min-role + hidden_from_local), (3) слой overrides `chat_profiles.chat_params` + резолв `hot_chat` (chat_params → bot_settings → дефолт), (4) BYOK: `chat_keys` + per-chat бюджет глобального ключа `chat_usage`, (5) API-модуль `/api/access/*`, расширение `/api/config` (X-Chat-Id), (6) TMA-витрина: контекст-селектор, роль-пикер, BYOK-поля, карточки «Доступы и Роли» — **только частично** (полная навигация/прогрессивное раскрытие — F-11).

### 1.2 Инварианты (нарушения — STOP для @Builder)

1. **R17**: сырые ключи никогда не логируются и никогда не отдаются по API (только маски `{configured, last4}` / `{key_name, configured, last4}`).
2. **Локальный админ НЕ видит глобальный ключ ни в каком виде**: поля keys-секции в TMA для него визуально пустые; `{configured,last4}` глобального ключа ему не показывается; только его собственные `chat_keys` (маска).
3. **`chat_params`** содержит ТОЛЬКО ключи с `per_chat=True` (Q5) и никогда `keys.*`-секреты (BYOK — только таблица `chat_keys`).
4. **Fail-open на PG**: PG недоступен → `hot_chat` возвращает глобал/дефолт, PermsocGate/гейты — безопасный дефолт; бот жив.
5. **Существующие сигнатуры `web/api/deps.py` (`get_tma_user`, `requires_permission`, `can_edit_param`, `can_view_key_value`) НЕ меняются**; новые сущности — отдельный модуль `services/access.py` + новые `web/api/access.py`.
6. **Порядок роутеров `bot.py` (slava_presence → … → vasya) не изменяется**; новые регистрации — только добавками.
7. **SQLite-схема/память/`tools/history_import` — вне скоупа** (RUNTIME WARNING, Epic 86 frozen).
8. **`hot_config.hot.get` и `ConfigCache` не изменяются** — per-chat слой живёт в `services/chat_params.py` параллельно.

---

## 2. Q1 — Модель ролей

**Решение: `bot_roles.role_type TEXT` (аддитивная колонка) + иерархия `ROLE_RANK` в НОВОМ `services/roles.py`.** Обоснование: role_type — семантический маркер (4 встроенные роли = 4 уже существующих+1 строчки в `bot_roles`), permission-пресеты без колонки недолговечны (Custom-роли будут отличаться); `permissions.py` НЕ расширяем (остаётся чистым матчером 84.14.2), иначе есть риск регресса `validate_permissions`/`guard_last_wildcard`.

### 2.1 ДДЛ (идемпотентно, в `DDL_STATEMENTS` `services/pg_db.py`)

```sql
ALTER TABLE bot_roles ADD COLUMN IF NOT EXISTS role_type TEXT;  -- NULL=custom
ALTER TABLE chat_admins ADD COLUMN IF NOT EXISTS role_name TEXT NOT NULL DEFAULT 'local_admin';
```

- `role_type` значения: `'global_admin' | 'local_admin' | 'moderator' | 'user' | NULL(custom)`.
- Сиды `DEFAULT_ROLES` (ON CONFLICT DO NOTHING; существующие `admin/moderator/user` **не перезаписываются** — добавляются только `role_type` через отдельный `UPDATE bot_roles SET role_type=$1, is_custom=false WHERE role_name=$2 AND role_type IS NULL`):
  - `admin` → `global_admin` (permissions `{wildcard}` — без изменений);
  - `moderator` → `moderator` (сид-сет `sections:[limits] + actions:control.*` — **НЕ расширять**);
  - `user` → `user` (пустые);
  - НОВАЯ строка `local_admin` → `role_type='local_admin'`, `is_custom=false`, permissions-пресет:
    ```json
    {"sections": ["limits", "flags", "reactions", "content", "chat_lore"], "actions": []}
    ```
    (без `wildcard`, без `keys`, без `prompts` как секции — промпты доступны через per-chat override «Использовать мой», см. §5; без `models` — маршрутизация глобальная).
- `chat_admins.role_name` — роль per-chat-гранта; домен значений `{'local_admin','moderator'}` (валидация на API: иначе 422). Существующие строки (лорадмины раунда 7) получают `'local_admin'` — они автоматически становятся локальными админами чатов (намерение, не ломает их доступ к лору).

### 2.2 `services/roles.py` (НОВЫЙ)

```python
ROLE_TYPE_RANK = {"global_admin": 4, "local_admin": 3, "moderator": 2, "user": 1}

def role_type(role_name, perms) -> str            # из role_type колонки; None → custom
def rank_of_type(role_type) -> int                 # custom → 4 если wildcard,
                                                   #          2 если permissions имеет ненулевые группы,
                                                   #          1 иначе
LOCAL_ADMIN_PRESET: dict[str, object]              # см. 2.1 (секции)
MODERATOR_PRESET: dict[str, object]                # существующий сид moderator
@dataclass AccessCtx: {role_global: str, role_chat: str|None, perms_global: Permissions,
                       perms_chat: Permissions, is_global_admin: bool,
                       is_local_admin: bool, rank: int}
async def access_for(telegram_id, chat_id=None) -> AccessCtx
def effective_permissions(ctx) -> Permissions      # union perms_global ∪ perms_chat (для chat-скоупа)
```

### 2.3 Семантика `access_for` (Q3-ядро)

| Игрок | role_global | роль в чате | Права |
|---|---|---|---|
| Global Admin (`role_type='global_admin'` или `wildcard`) | global_admin | — | **всё**, все чаты (`is_global_admin=True`) |
| Строка `chat_admins(chat_id, 'local_admin')` | их глобальная роль или `user` | local_admin | пресет local_admin **в ЭТОМ чате**: редактирование `chat_params` (ключи `per_chat=True`), per-chat gates (тяжёлые, см. F-10), лор/relations/админы лора-чата; ГЛОБАЛЬНЫЙ config-путь (POST /api/config без X-Chat-Id) — **НЕ расширяется** (проверяется по глобальным правам) |
| Строка `chat_admins(chat_id, 'moderator')` | их роль | moderator (chat-scoped) | пресет moderator **в ЭТОМ чате** (limits-секция scope-чата: read chat_params, edit только через min-role, см. §3) |
| Глобальный `moderator` (bot_roles) | moderator | — | глобальный — **без изменений сегодняшней семантики** (секция limits + control.*); в per-chat-контексте — только чтение |
| `user` / никто | user | — | read-only: «Статус», «Как это работает» (меню — F-11) |
| Custom (role_type NULL) | custom | — | rank по 2.2; права — по их permissions (существующий матчинг) |

- `is_local_admin = (role_chat == 'local_admin')`. `rank` (для min-ролей §3) = `rank_of_type` от **наибольшего** из: role_global, role_chat.
- access_for без `chat_id` → только глобальный срез (для глобальных API-путей пользователей, селектор чатов и т.п.).
- **Никаких пер-чат прав пользователей, кроме двух грантов `chat_admins`** — новых таблиц/ролей на юзера не вводим.

---

## 3. Q2 — `param_permissions`: отдельная таблица

**Решение: НОВАЯ таблица `param_permissions (key TEXT PRIMARY KEY, value JSONB NOT NULL DEFAULT '{}')`** (паттерн `bot_settings`: key→JSONB). Обоснование: (а) это НЕ runtime-конфиг, а авторизационные метаданные — не должны попадать в `ConfigCache`/`GET /api/config`/дерево ролей; (б) bulk-чтение для роль-пикера одним запросом; (в) `botsettings`-контракт «значения» не смешивается с «правилами».

```json
{"view_min_role": "user", "edit_min_role": "moderator", "hidden_from_local": false}
```

### 3.1 Эффективная матрица (код-дефолты + БД-перекрытия)

Строки в таблице **НЕ сидятся** (`(изменено @Architect T-843)`: 372 строки устареют при росте каталога; вместо них — DEFAULT_MATRIX в коде `services/access.py`, а БД-строки — только точечные override'ы глобального админа). `GET /api/access/param_permissions` отдаёт **эффективный** вид (дефолт ⊕ перекрытие).

| Категория | view_min_role | edit_min_role | hidden_from_local |
|---|---|---|---|
| `keys.*` | global_admin | global_admin | **True** |
| `prompts.*` | user | local_admin | False (значение «as-is») |
| `limits.*, flags.*, reactions.*, content.*, memory.*` | user | moderator | False |
| `models.*` | user | moderator | False |

- Оверрайды (только global admin, `PUT /api/access/param_permissions/{key}`) валидируются: роль ∈ домен ROLE_TYPES, view_rank ≤ edit_rank не обязателен, но view_min_role можно выставить выше edit — тогда ключ read-view-for-all выше editing — допустимо, валидация только на домен и 422 на мусор.
- `hidden_from_local=true` → локальный админ **не видит** ключ (в GET/POST /api/config с X-Chat-Id ключ исключается полностью).
- Проверки рендера в TMA: `canViewTab` (существующий permission-матчинг) НЕ меняется; per-param фильтр видимости — НОВЫЙ `can_view_param(ctx, key)`/`can_edit_param(ctx, key)` из `services/access.py` (не путать с одноимёнными функциями `web/api/deps.py` — те без изменений).

---

## 4. Q4/Q5 — `chat_profiles.chat_params`: layout, версионирование, whitelist

### 4.1 ДДЛ

```sql
ALTER TABLE chat_profiles ADD COLUMN IF NOT EXISTS chat_params JSONB NOT NULL DEFAULT '{}'::jsonb;
-- Расширение CHECK-констрейнта история-полей (существующий констрейнт — по умолчанию
-- называется chat_lore_history_field_check; оператор идемпотентен):
ALTER TABLE chat_lore_history DROP CONSTRAINT IF EXISTS chat_lore_history_field_check;
ALTER TABLE chat_lore_history ADD CONSTRAINT chat_lore_history_field_check
    CHECK (field IN ('manual','auto','auto_enabled','auto_period_hours','auto_window_hours',
                     'remap','chat_admin','chat_params','chat_keys','gates'));
```

### 4.2 Layout (версионирование — «версия корневая, per-key версий НЕТ»)

```json
{
  "v": 1,
  "overrides": { "<pg_key>": <значение> },          // per_chat=True ключи (вкл. prompts.*)
  "gates":     { "dream": false, "nostalgia": false, "lore_auto": false,
                 "permsoc": false },                 // booleans; по умолчанию отсутствуют
  "keys":      { "allow_global": true },             // false = запрет глобального ключа (F-12)
  "perm_overrides": { "<pg_key>": {"view_min_role": "...","edit_min_role": "...",
                                   "hidden_from_local": bool} },
  "meta": { "updated_by": <telegram_id>, "note": "" }
}
```

- `overrides` — единый namespace для ВСЕХ категорий-параметров (без под-неймспейсов params/prompts: dotted-ключи уже уникальны).
- `keys` — только МЕТА (режим/запрет); секреты — в `chat_keys` (§5).
- `hidden_from_local` — нет в chat_params: скрытие глобально (таблица `param_permissions`); чат-уровень не нужен (Q7).
- `perm_overrides` — чат-скоуп min-ролей, пишутся только глобальным админом (через маленький `POST /api/access/chats/{chat_id}/param_permissions/{key}` — добавка к E1; не дублировать в таблицу).

### 4.3 Запись/чтение (Q4)

- **Optimistic-конфликт — один на профиль**: `set_chat_params(chat_id, patch: dict, *, changed_by, expected_updated_at=None)`:
  1. транзакция: `UPDATE chat_profiles SET chat_params = jsonb_set(...), updated_at = now() WHERE chat_id=$1 AND updated_at = $expected`;
  2. 0 строк → `ChatParamsConflict(chat_id, current_updated_at)` → **409** `{code: "conflict", current_updated_at}` (прецедент ChatLoreConflict, T-772);
  3. в той же транзакции запись истории `field='chat_params'` (old_value=JSON-прежний, new_value=JSON-новый, changed_by) + `pg_notify('chat_params_updated', chat_id)`.
- **Атомарность**: массив правок (GET/POST /api/config с X-Chat-Id, F-1-прецедент) — все записи в ОДНУ операцию `set_chat_params` с **полной** валидацией до записи (тип по ParamSpec, per_chat=True, права, домены); частичный успех исключён.
- **Устаревший ключ** (ключ пропал из REGISTRY): фильтр на чтении (неизвестные каталогу ключи в overrides — игнорируются, отдаются глобал/дефолт); **авто-purge НЕТ**; список «осиротевших» ключей виден только глобальному админу (oversight-модалка, F-12), сброс — `DELETE /api/config/chat/{key}` (F5, 404 если нет).
- **Кэш**: `ChatParamsCache` (паттерн ChatLoreCache, T-774): per-chat load-on-demand, TTL 120 с, NOTIFY-инвалидация on `chat_params_updated`, fail-open `{}`. Sync-читалки hot-путей НЕ используется (см. 4.5).
- **День** обновления `updated_at` используется и F-10 (gates) с тем же `expected_updated_at`-механизмом — единый конфликт-протокол.

### 4.4 Whitelist `per_chat` (Q5)

- `ParamSpec.per_chat: bool = False` (новое поле с дефолтом False).
- Правило заполнения: `per_chat = (category in {prompts, limits, flags, reactions, content, memory}) and (secret == False)`. `models.*` и `keys.*` — **строго глобальные** (маршрутизация/секреты; BYOK даёт пер-чат только ключ, не модель).
- Валидация: `POST /api/config` с X-Chat-Id для ключа с `per_chat=False` → **422** (`"ключ нельзя переносить на уровень чата"`).
- `GET /api/config/params-meta` (новый) — отдаёт `{pg_key: {per_chat, progressive_level, group, title, type, secret_mask}}` консолидированно для TMA (без значений секретов; полезен F-11).

### 4.5 Точки `hot_chat` (Q5/Q9-список — все sites)

`services/chat_params.py`:
```python
async def get_chat_param(chat_id, key, default=None):  # chat_params.overrides (cast!!) → hot.get → default
def get_chat_param_sync(...)  # только для внутренних проверок флагов (см. F-9 — допускается sync-путь
                              # через pre-await кэша; БЕЗ обращений к ConfigCache)
```
Вызовы (аудит T-847; добавлять только после явного согласования в задачe):
- `services/direct_chat_service.py` — тон/персона/стиль (`prompts.direct_chat_system_prompt`, `limits.*`-тонкость);
- воркеры (`services/dream_worker.py`, `services/nostalgia_worker.py`, `services/lore_worker.py`) — чтение их per-chat лимитов (демон: `limited по Q5` — лимиты из group `limits_memory`/`limits_graph` и `limits.nostalgia_*`/`limits.dream_*` — через hot_chat);
- `services/permsoc.py` (F-9) — `flags.permsoc_enabled`, под-флаги (olya/mimic/alan);
- `services/features_gate.py` (F-10) — gates;
- хендлеры реакций/персон — тоны `reactions.*` (slavik/kostik/alan/olya) — через hot_chat где есть chat_id;
- **НЕ трогаем**: `ConfigCache`-горячий путь, `hot.get` внутри `llm_client` (глобальный слой), импорт-time hot.get паттерны (F-5-прецедент — отложенный доступ).

---

## 5. Q6 — BYOK (`chat_keys` + бюджет)

### 5.1 Хранение

```sql
CREATE TABLE IF NOT EXISTS chat_keys (
    chat_id     BIGINT NOT NULL,
    key_name    TEXT NOT NULL,
    key_value   TEXT NOT NULL,
    key_hint    TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, key_name)
);
```

- Whitelist `key_name`: **`['keys.llm_api_key']`** (fallback-ключ и embed-ключи — строго глобальные: fallback это админ-инструмент, embed — .env-инфраструктура; `(изменено @Architect T-843)`, E4-список уточнить: `keys.llm_api_key` только). 422 для прочих.
- Аудит записи/удаления — `chat_lore_history field='chat_keys'`, changed_by. Удаление ключа — намеренно без мягкой пометки (insert-or-replace).
- Секрет `chat_keys` **не попадает** в `chat_params` и в общие конфиг-дампы.

### 5.2 Резолв в `services/llm_client.py` (D2)

```python
# публичный async-метод хек: async def _resolve_api_key(chat_id):
# 1) chat_keys[chat_id]['keys.llm_api_key'] → источник 'chat' (свой ключ, бюджет не тратится)
# 2) elif not chat_params['keys']['allow_global'] (default True) → None (источник 'forbidden')
# 3) elif budget_exceeded(chat_id) → None (источник 'budget')
# 4) else глобальный hot.get("keys.llm_api_key", settings.LLM_API_KEY) + recount (источник 'global')
```

- Точки входа (главный interactive-путь `direct_chat_service` → `llm_client`): добавляется `chat_id=None: int|None` в публичные async-методы (в первую очередь generation/chat), внутри — предварительный `await _resolve_api_key(chat_id)`, затем существующий `_get_client(key)` (пересоздание клиента при смене ключа — уже есть, `_client_key`); `_current_api_key()` остаётся для «глобальных» вызовов (embed/vision/video — НЕ в скоупе BYOK; они глобальные всегда).
- **Bуget flag**: `_mask_secret` контракт расширяется новой маской `mask_chat_key_info` → `{"key_name","configured","last4"}`. Глобальный админ в GET /api/config видит по-прежнему `{configured,last4}` глобального ключа (без изменений); **локальный — НИЧЕГО из статусов глобального** (для него легальная видимость = его собственные chat_keys).
- **Расходы**: `chat_usage (chat_id BIGINT, day DATE, metric TEXT, used BIGINT, PRIMARY KEY(chat_id,day,metric))`; metric ∈ `{'llm_calls','llm_tokens'}`; счётчик — в PG, на КОНЦЕ LLM-вызова (1 вызов + фактические токены ответа; приблизительность фиксируется в README), пред-проверка «used > limit → не тратить». REGISTRY: `limits.chat_global_key_budget_tokens` (int, дефолт 100000), `limits.chat_global_key_budget_requests` (int, дефолт 25). Лимит **0** = глобальный ключ этому чату запрещён.
- Превышение/`forbidden` → **сансдбокс**: бот отвечает фиксированной фразой (REGISTRY `content.no_key_reply`, дефолт: «Сейчас я не могу отвечать: у чата нет своего ключа, а глобальный недоступен или исчерпан. Настройка: ключ чата (для локального админа) или лимиты.»), WARNING-лог с chat_id (без значений), LLM не вызывается. Тишины нет.

---

## 6. API-контракты (E1–E4)

Все — под `Depends(get_tma_user)`; 401 без initData; 403 нет права.

| Метод, путь | Права | Тело/ответ |
|---|---|---|
| `GET /api/access/me` | любая роль | `{role_global, role_chat, is_global_admin, is_local_admin, chats: [{chat_id, role}]}` (список доступных чатов — по грантам/`can_access_chat` для local/moderator; для global admin — полный список активных профилей) |
| `GET /api/access/chats` | любая роль | `[{chat_id, title, is_active, access: 'global_admin'\|'local_admin'\|'moderator'\|'user'}]` — join chat_admins; для TMA-селектора |
| `POST /api/access/chats/{chat_id}/admins` | **только global admin** | `{telegram_id, role_name}` ∈ {local_admin, moderator} → chat_admins upsert (ON CONFLICT) + история `field='chat_admin'`; 404 нет профиля; 422 домен |
| `DELETE /api/access/chats/{chat_id}/admins/{telegram_id}` | только global admin | `{removed: true}` |
| `GET /api/access/param_permissions` | только global admin | эффективная матрица `[key → {view_min_role, edit_min_role, hidden_from_local, default: bool}]` |
| `PUT /api/access/param_permissions/{key}` | только global admin | `{view_min_role, edit_min_role, hidden_from_local}`; 422 невалидная роль/мусор; запись в таблицу (INSERT ON CONFLICT) + NOTIFY `param_permissions_updated` |
| `GET /api/config` (X-Chat-Id) | роль имеет доступ к чату, иначе 403 «нет доступа к чату» | значение = chat_params → глобал → дефолт; фильтр: `can_view_param` (hidden_from_local и keys-правила); для secret-ключей — только `{configured,last4}` своего |
| `POST /api/config` (X-Chat-Id) | local admin/moderator (по chat-правам) для per-параметра; global admin — всё | запись в chat_params (для `per_chat=True`); `keys.*` → **403/422** (идет в chat_keys, не сюда; jsonb-маска); 409 optimistic; 422 каст-ошибка; атомарная |
| `DELETE /api/config/chat/{key}` (X-Chat-Id) | global admin / local admin чата | сброс override на глобальный (`jsonb_remove('overrides', key)`), 404 если нет |
| `GET /api/config/params-meta` | любая роль | мета-каталог (per_chat, progressive_level, group, title, type) — без значений |
| `GET /api/config/keys/own` | local admin чата / global admin | `[{key_name, configured, last4}]` |
| `PUT /api/config/keys/own` | локальный админ чата / global admin | `{key_name, value}` → chat_keys; ответ `{key_name, configured, last4}` |
| `DELETE /api/config/keys/own/{key_name}` | локальный админ чата / global admin | `{removed}` |
| `GET /api/config/keys/status` | роль имеет доступ к чату | `{own: {key_name: {configured, last4}}, allow_global, budgets: {tokens: {used, limit}, requests: {used, limit}}}` — статусы для TMA; глобальный ключ в поле `global` только для global admin |

Замечание: `X-Chat-Id` — прозрачный заголовок; отсутствует → ровно старое поведение (глобальный конфиг). Все маски — единый `_mask_secret`/`mask_chat_key_info`.

---

## 7. TMA-витрина (F1–F5; навигация — F-11)

- **`activeChatId`** (persist `localStorage['adminbot.active_chat_id']`), `api()` добавляет `X-Chat-Id` при установленном чате; NULL → старый вид.
- **Роль-пикер**: для global admin, gear-кнопка ВОЗЛЕ КАЖДОГО параметра в generic-рендере → модалка `view_min_role`/`edit_min_role`/`hidden_from_local` → `PUT /api/access/param_permissions/{key}`; бейдж «скрыт» у параметров (для non-global пикер не рендерится).
- **BYOK-UI**: для local admin — поля keys-секции ПУСТЫЕ, placeholder «Ваш ключ чата…», кнопка «Использовать мой» (PUT /api/config/keys/own), строка «используется ключ чата» / «используется глобальный ключ (бюджет N/M)» (GET /api/config/keys/status). Для global admin — прежний вид (configured/last4).
- **«Доступы и Роли»-карточки** (F4): локальные админы чата (список + POST/DELETE), «Мой доступ» (GET /api/access/me), инфа-карточка «Промпты — базовые; Использовать мой — в чат».
- **Бейджи «переопределено чатом»** (F5) + «Сбросить на глобальное» (DELETE /api/config/chat/{key}) — для per_chat=True; 409 optimistic; 404/403-обработка.

---

## 8. Тест-инварианты (G1–G5)

1. Двойной `init()` — no-op; `ADD COLUMN IF NOT EXISTS` на «чистой» и «уже существующей» БД; CHECK-констрейнт истории — при повторном init без ошибок.
2. `access_for`-матрица §2.3 (global/local/moderator/user; не-член → пусто для чата).
3. `chat_params`: каст-ошибка 422, optimistic 409 с current_updated_at, NOTIFY-эмит, кэш-инвалидация, fail-open (PG down → глобал/дефолт).
4. BYOK: chat_keys CRUD, маска ответов (никогда raw), резолв своего ключа приоритетом к глобальному, бюджет-исчерпание → sandbox-ответ, fallback — только глобальный путь.
5. R17-греп: `chat_keys`/`chat_params` raw не логируются и не отдаются.
6. API-матрица: 401/403/404/422/409; для локального админа GET /api/config X-Chat-Id чужого чата → 403; POST атомарен (частичный успех исключён).
7. Фронт-аудит (маркер-строки в app.js/index.html): `X-Chat-Id` в `api()`, роль-пикер-элементы, BYOK-пустые поля/статус, access-карточки; тесты сохраняют `test_frontend_tab_mapping.py`-инвентарь актуальным.
8. Полный pytest → 0 failed; `git diff --check` чист; RUNTIME WARNING соблюдён (SQLite/`bot.py`-порядок/`MEMORY.md` untracked — не в коммит).

---

## 9. Инвентарь (Q9 — ответы/справка для Builder)

- **`hot.get` в direct_chat/воркерах**: `services/direct_chat_service.py` (промпт/тон `prompts.direct_chat_*`, лимиты cooldown/суммари), `services/dream_worker.py` (limits.dream_* / flags.dream_enabled), `services/nostalgia_worker.py` (limits.nostalgia_* / flags.nostalgia_enabled), `services/lore_worker.py` (auto_period/auto_enabled — из PG-профиля; флаги), `services/summary_aliases.py` (limits.summary_aliases). Полный grep-сверок — в задаче T-847 (создать свежий список на CHANGES по каждому файлу, не доверяя этому списку на 100%).
- **`_current_api_key`-вызовы**: `services/llm_client.py` (:291, :296 fallback), `services/video_cascade_client.py` (:104) — видео остаётся глобальным.
- **Известные секции** (`known_sections()`): CATEGORIES (prompts/models/keys/limits/flags/reactions/content/memory) ∪ {access, chat_lore}.
- **TABS** (`web/app.js` :18-47): llm_providers/prompts/limits/memory_rag/reactions_triggers/access/chat_lore/status/info.
- **POST /api/config** — `web/api/routes.py:235-283` (существующий путь глобального редактирования; НЕ меняется для no-X-Chat-Id).
- **Moderator-сид**: `pg_db.py` DEFAULT_ROLES — НЕ расширять.
- **RUNTIME WARNING**: SQLite-схема, `tools/history_import`, `manage.py`, `plans/MEMORY.md` (untracked — НЕ коммитить), порядок роутеров bot.py, `plans/ARCHITECTURE.md` (ПОСЛЕ фич — см. H-секции).

## 10. Риски для @Builder

1. **CHECK-констрейнт `chat_lore_history.field`** — DROP/ADD в DDL: если PK/имя отличается — идемпотентность проверяетсядвойным init; писать в DDL_STATEMENTS в ОДНОЙ связке DROP+ADD.
2. **Двойной канал записи gates** (F-10 пишет в те же `chat_params.gates`): синхронизация optimistic-токена — обе фичи обязаны использовать `expected_updated_at`, но F-8/F-10 выходят в один деплой раунда — согласовать до кода.
3. **`_resolve_api_key` async-инъекция в llm_client**: НЕ менять сигнатуры sync-методов — только добавить chat_id в публичные async-точки и передавать resolved key в `_get_client` (иначе регресс эмбеддинг-каскада).
4. **Local admin самозаписывание прав**: проверки `can_edit_param` в контексте чата не деградируют до проверок глобальных прав (union только для чат-путей).
5. **Бюджет/токены округление**: `chat_usage` — приблизительный (обрать estimate на концах), README-пометка; НЕ делать строгий метринг в этой части.
