# F-14 — Личные сообщения: отдельные настройки (DM-скоуп) (раунд 10.3)

> Пересоздано @Architect 09.09.2026 по KG-канону сущности `feature-dm-user-settings`
> (файл утрачен при реструктуризации 03.09.2026; дизайн ВАРИАНТ A зафиксирован в KG,
> черновые решения сущности `feature-frontend-dm-settings-bugfixes` — НЕ используются).
> Пункт ТЗ владельца 4 (AC-4): «личные сообщения» настраиваются ОТДЕЛЬНО (как чаты) —
> юзер правит параметры/фичи/лимиты/ключи СВОИХ ЛС, наследование от глобальных,
> ЕДИНСТВЕННОЕ исключение — саммари в ЛС по умолчанию OFF.
> База: HEAD `d30b203`, pytest 4760. ⚠️ Код не пишется до spec.md (T-954…T-958).

## 1. Канон модели (вариант A — ПРИНЯТ)

- **DM-скоуп = переиспользование `chat_profiles`/`chat_params` с `chat_id = user.id`**:
  positive chat_id = ЛС (личка с ботом), negative = группы. Коллизий нет (группы <0,
  лички >0; бот-путь direct_chat_service.py:517-521 УЖЕ резолвит `get_chat_param(chat_id=user.id)`).
- `is_dm_scope(chat_id) -> bool = chat_id > 0` — единственный идентификатор;
  helper в `services/chat_params.py` (или `services/roles.py` — рядом с использованием;
  единый модуль — `services/chat_params.py::is_dm_scope`).
- **Ноль DDL**: схема PG не расширяется; `chat_keys`/`chat_usage` уже per-chat_id
  (F-7 §5); `ChatParamsCache` TTL 120с + NOTIFY `chat_params_updated` + 409-оптимизм +
  история `field='chat_params'` — переиспользуются БЕЗ изменений (MED-007/008:
  не инвалидируем, не дублируем).
- **Наследование**: `overrides → hot.get → дефолт` (F-7 резолв, `services/chat_params.py:197-222`)
  работает для DM автоматически: юзер наследует глобальные настройки, кроме явно
  изменённых в своём ЛС-профиле. Единственное исключение — саммари (§4).
- Отдалённый ранее вариант B (отдельная сущность + шим) ОТКЛОНЁН: дублирование
  кэша/истории/прав, риск рассинхрона.

## 2. Права (roles/access — точечные is_dm-ветки)

### 2.1. `services/roles.py`

- `AccessCtx` (frozen dataclass, :80-95): НОВОЕ поле **в конце** списка полей
  `is_dm_owner: bool = False` (дефолт НЕ ломает существующие тесты-конструкторы
  и вызовы, создающие AccessCtx позиционно).
- `access_for` (:126-190): **DM-ветка ДО группового chat_admins-лукапа**:
  если `chat_id is not None and chat_id == telegram_id and is_dm_scope(chat_id)`:
  - `is_dm_owner = True`;
  - `rank = max(rank_global/диз, ROLE_TYPE_RANK[ROLE_LOCAL_ADMIN])` = max(…, 3);
  - `role_chat = None` — НЕ путать с group local_admin (важно: F-11-меню и group-секции
    НЕ открываются; `is_local_admin` остаётся False);
  - `perms_chat = DM_OWNER_PRESET` = `{sections: [prompts, limits, flags, reactions,
    content, memory], actions: []}` — union с глобальным срезом при effective_permissions;
    НЕ включает `chat_lore` (изоляция П.5: лор-API ЛС → 404) и НЕ даёт group-секций;
  - срез вычисляется ЛОКАЛЬНО, БЕЗ обращений к PG → fail-open: PG down → DM-владелец
    работает (локальный срез); остальные сферы — как раньше (глобальный срез + WARNING-фолбэк).
- Существующие `ROLE_TYPE_RANK`/`LOCAL_ADMIN_PRESET`/`MODERATOR_PRESET` — БЕЗ изменений.

### 2.2. `services/access.py` (ТОЛЬКО is_dm-ветки; DEFAULT_MATRIX/effective_matrix/
_normalize_perms/param_permissions — БЕЗ изменений)

- `can_access_chat(ctx, chat_id=None)` — **аддитивный** параметр `chat_id`
  (существующие вызовы без него — прежнее поведение):
  - `chat_id is not None and is_dm_scope(chat_id)` → `return bool(ctx.is_dm_owner)`
    (ТОЛЬКО владелец; **глобальный админ в чужом ЛС → False → 403**);
  - иначе — существующая логика без изменений.
  - Вызывающие с chat_id (routes.py:364; gates.py; chat_lore API) передают `chat_id`,
    где он есть в контексте (аддитивно, без смены сигнатур — MED-019).
- `eligible_type(ctx)`: ветка `ctx.is_dm_owner` → `ROLE_LOCAL_ADMIN` (до алиаса по rank);
  остальное без изменений.
- `can_edit_param(ctx, matrix)`: ветка `is_dm_owner` **ПОСЛЕ** `is_global_admin`
  и **ДО** role_chat-гейта (DM-owner имеет role_chat=None — без ветки вернулось бы
  False всегда): `m = _as_new_matrix(matrix); return eligible_type(ctx) in m.get("edit_roles", [])`.
  Следствия: per_chat-ключи (limits/flags/reactions/content/memory/prompts) —
  edit_roles `[local_admin]` → **True**; keys.* — дефолт-матрица `[]/[]` → **False**
  (ключи — только BYOK-путь `/api/config/keys/own`, R17/S2/S3); models.* — per_chat=False;
  v-формы `[moderator, local_admin]` view → DM-владелец видит (eligible=local_admin ∈ view_roles).
- `can_view_param` — БЕЗ изменений (eligible_type уже вернёт local_admin для DM).

### 2.3. Критерии приёмки (T-954)

- свой id + X-Chat-Id=свой id → is_dm_owner=True, rank=3, role_chat=None, DM-пресет;
- чужой chat_id → is_dm_owner=False; глобальный админ в чужом ЛС → can_access_chat False → 403;
- can_edit_param: per_chat-ключи True для DM-владельца; keys.* → False; prompts → True;
- is_local_admin НЕ выставляется для DM (F-11-меню не открывает group-секции);
- DEFAULT_MATRIX/effective_matrix/_normalize_perms — без дифов;
- fail-open: PG down → DM-владелец работает (локальный срез).

## 3. Профиль ЛС + API-контракты

### 3.1. `services/chat_params.py::ensure_scope_profile(chat_id, *, dm: bool, pg) -> bool`

- INSERT `chat_profiles (chat_id, auto_enabled, is_active, chat_params, gates_opt_in)`
  `VALUES ($1, $2, $3, $4::jsonb, false) ON CONFLICT (chat_id) DO NOTHING`
  (паттерн chat_lore_store.py:44-47), идемпотентен (повтор → no-op → False),
  возвращает True при вставке / False при повторе (или при отсутствии пула).
- DM (`dm=True`): `auto_enabled=false` (LoreWorker не тронет — двойной guard с П.2),
  `is_active=true`, `chat_params=_root_with_meta({})` (v-1-лейаут), `gates_opt_in=false`.
- Ленивый вызов ПЕРЕД ПЕРВОЙ записью в DM-скоупе (иначе `set_chat_params` даст
  мусорный `ChatParamsConflict(chat_id, None)` «профиля нет»): POST /api/config (DM),
  DELETE /api/config/chat/{key} (DM), PUT /api/config/keys/own (DM).
  (Гейты: gates DM PUT → 403 (§3.3), записи в DM нет — ensure не нужен; для групповых
  чатов поведение не меняется.)

### 3.2. Контракты (коды: 200/403/404/409/422; raw-ключи никогда — R17)

| Эндпоинт | DM-поведение |
|---|---|
| `GET /api/access/chats` | фильтр `chat_id > 0` в CHATS_FOR_USER_SQL (П.1) + синтез DM-строки `{chat_id: user.id, title: "Личные сообщения", photo_file_id: null, is_active: true, access: "dm", is_dm: true}` для ЛЮБОГО авторизованного (включая global admin) |
| `GET /api/access/me` | тот же фильтр+синтез (chats-массив с DM-строкой) |
| `GET /api/config` X-Chat-Id=user.id | 200: items per_chat-категорий (chat_source='chat' для override'ов — как у группы), keys.* СКРЫТЫ (матрица []/[] — канон «не global admin»), models.* — read-only глобальная справка (per_chat=False), `ctx.is_dm=true` (добавить в уже существующий ctx-объект :333-337), `updated_at` из профиля |
| `POST /api/config` X-Chat-Id=user.id | `ensure_scope_profile(dm=True)` → `set_chat_params` как есть; models.*/keys.* → 422 (существующий гейт routes.py:380-388); 409-оптимизм как есть; пустые prompts/content → 422 (существующее :400-405) |
| `DELETE /api/config/chat/{key}` | гейт `is_global_admin or is_local_admin or is_dm_owner` = сброс своего override (DM-владелец — только свой ЛС) |
| `GET/PUT/DELETE /api/config/keys/own` | гейт `+ is_dm_owner` (BYOK своего ЛС; chat_keys per-chat без DDL; маска-ответ `{configured, last4}` — R17; GET → ключ НЕ отдаётся, только конфиг-факт) |
| `GET /api/config/keys/status` | `can_access_chat(ctx, chat_id)` (is_dm_owner → 200, `chat_usage.key_status` :128-136); поле `global` (глобальный ключ) — только global admin (S1/S2) |
| `GET /api/chat/{id}/gates` | is_dm_owner → 200 READ (who_can_toggle='global'); PUT → 403 (гейты только global admin — F-10-канон write-path, feature_gates без изменений) |
| `GET /api/workers/budget` | БЕЗ изменений (403 без грантов; DM-грантов в chat_admins НЕ создаём — П.6) |
| `/api/oversight/summary` | БЕЗ DM-строк (П.4) |

### 3.3. Негативные контракты

- глобальный админ в чужом ЛС (X-Chat-Id=чужой положительный): GET /api/config → 403,
  keys/own → 403, gates GET → 403 (can_access_chat False);
- chat_lore-эндпоинты с DM-id → 404 (П.5);
- keys.* в POST /api/config → 422 (существующий канон, НЕ 403 — не ломать);
- raw-ключи в любых ответах/логах — 0 (grep `sk-`/«api_key»-значения в тестах-контрактах).

## 4. Саммари DEFAULT-OFF (единственное исключение из наследования)

### 4.1. `services/chat_params.py`: два новых резолвера

- `get_chat_param_defaulted(chat_id, key, fallback) -> object`:
  override из `chat_params.overrides` (если ключ ЯВНО присутствует — каст по каталогу
  `normalize_value`; мусор → fallback; **без** горячего global-фолбэка `hot.get`) →
  иначе НЕМЕДЛЕННО `fallback` (НЕ hot.get!). Инвариант: `get_chat_param` /
  `get_chat_params_full` / `_resolve_from_root` — БЕЗ изменений (регресс-инвариант).
  Каст — через тот же `normalize_value` (учесть унификацию T-651/652 F-1).
- `chat_summary_enabled(chat_id) -> bool`:
  - `is_dm_scope(chat_id)` → `await get_chat_param_defaulted(chat_id,
    "flags.chat_running_summary_enabled", False)` — override→cast→False;
    **НЕ наследует глобальный ON** (единственное исключение; пустой профиль → False
    даже при глобальном ON);
  - иначе → `hot.get("flags.chat_running_summary_enabled",
    settings.CHAT_RUNNING_SUMMARY_ENABLED)` — байт-в-байт старое поведение.
- НОВЫХ параметров каталога НЕТ: REGISTRY 383 / группы 71 / Settings 359 — без
  изменений (эталон `test_param_catalog`; MED-017).

### 4.2. Точки интеграции (S1-S5)

| Точка | Место | Изменение |
|---|---|---|
| S1 | `summary_memory.py::get_window_messages` :1148-1150 | `hot.get("flags.chat_running_summary_enabled", …)` → `await chat_summary_enabled(chat_id)` (триггер бегущего конспекта; async-функция — вызов допустим) |
| S2 | `direct_chat_service.py::_build_global_context` :1702-1703 | тот же резолвер (L1/L2-инжект конспекта; L2 гейтится ВМЕСТЕ с L1 — только внутри ветки summary_text) |
| S3 | `summary_scheduler.py::_tick` :47-50 | в цикле: `if chat_id > 0: continue` (+ DEBUG/INFO-лог «dm summary skip»; ЛС-рассылки нет; `generate_and_send` НЕ дифится) |
| S4 | manual /summary в ЛС | БЕЗ изменений — работает (явный вызов; гейт S1/S2 применяется при построении окна/конспекта) |
| S5 | `bot.py:613-643` (`flags.summary_enabled`) | **НЕ ТРОГАТЬ** (router-гейт: direct_chat/observer/etc.; правка убьёт весь direct chat) |

- L3/GraphRAG-факты = ПАМЯТЬ, не саммари → НЕ гейтятся (memorize в ЛС работает
  как в группах — факты пишутся).

### 4.3. Матрица `chat_summary_enabled` (тесты T-955)

| Скоуп | Профиль | Глобальный флаг | override | Результат |
|---|---|---|---|---|
| группа (<0) | любой | ON/OFF | — | как было (горячий флаг) |
| ЛС | пустой/нет | ON | нет | **False** |
| ЛС | есть | ON | `true` | True |
| ЛС | есть | OFF | мусор | False (cast-фолбэк — T-651/652 стиль) |
| ЛС | есть | — | `false` | False |

## 5. Изоляция (6 точек)

| Точка | Место | Фильтр |
|---|---|---|
| П.1 | `web/api/access.py` CHATS_FOR_USER_SQL (:46-52) | `WHERE p.chat_id < 0` + синтез DM-строки (см. §3.2; и в /me) |
| П.2 | `services/chat_lore_store.py` (list_active_chats :163-166/`list_active_chat_ids` :170-173/`list_profiles` :341-348) | `WHERE chat_id < 0` (добавляется к SQL-константам) |
| П.3 | LoreWorker | БЕЗ изменений (список уже чист) |
| П.4 | `services/oversight.py` build_summary PROFILE_COLS_SQL (:31-34) | `WHERE p.chat_id < 0` |
| П.5 | `web/api/chat_lore.py` | списки без DM; прямые DM-id → 404 (проверка is_dm_scope(id) → 404) |
| П.6 | `web/api/gates.py` | `_admin_grant_chat_ids` (:121-135) — БЕЗ изменений (DM-грантов в chat_admins не создаём); gates DM READ-only |

## 6. TMA (поверх F-13 AC-1)

### 6.1. Селектор — запись «Личные сообщения»

- DM-строка приходит с сервера (`is_dm: true`) → рендерится в ЕДИНЫЙ селектор F-13
  как обычная опция (`c.title = «Личные сообщения»` — title уже синтезирован сервером);
- при `accessChats.length == 1` (только DM) — селектор виден и авто-выбран
  (существующая логика :637-641: локальный/глобальный без грантов → первый чат);
- `syncActiveChatTitle` — без изменений (title приходит из accessChats).

### 6.2. Помощники фронта

- `isDmCtx(): bool` = `this.activeChatId != null && this.accessChats.some(
  c => c.chat_id === this.activeChatId && c.is_dm)`;
- бейдж в шапке (замена `#{{ activeChatId }}` F-13): `{{ isDmCtx() ? 'ЛС #' + activeChatId : '#' + activeChatId }}`
  (в index.html, в зоне AC-1-бейджа);
- `canViewTab` (app.js:1237-1272): НОВАЯ ветка **до** прав-матріка:
  `if (this.isDmCtx() && tab.type === 'config' && tab.id !== 'permsoc') return true;`
  → открываются: Провайдеры (модели read-only + BYOK-блок), Промпты, Лимиты,
  Память-RAG, Реакции-Триггеры; **permsoc скрыт** (групповые перс-модули);
- локация ветки: после `if (tab.always) return true;` и перед секционным матчингом
  (БЕЗ изменения других веток canViewTab — oversight/modules/chat_lore как есть).

### 6.3. Кнопки/блоки

- BYOK-блок (index.html:737, `isChatContext() && !isGlobalAdmin`) — УЖЕ покрывает
  DM-владельца (isDmCtx ⇒ isChatContext; DM-владелец не глобальный админ) — **без изменений**;
- «↪ глобальное» (resetChatOverride): условие кнопок (index.html:574-576,
  :679-681) `itemOverriddenByChat(item) && isGlobalAdmin` → `… && (isGlobalAdmin || isDmCtx())`;
  метод `resetChatOverride` (app.js:1095) — гейт расширяется тем же условием
  (проверка, что вызов разрешён для DM-владельца);
- badge `item.chat_source === 'chat'` (index.html:569/:675) — переиспользование,
  текст «чат» оставить (не «ЛС» — отсутствие дифов в рендере; решение документально);
- empty-states (index.html:519/:1006, после F-13 AC-1): текст →
  «…выберите чат **или Личные сообщения** в селекторе в шапке».

### 6.4. Критерии (T-958)

- вкладки Провайдеры/Промпты/Лимиты/Память-RAG/Реакции открываются в DM-скоупе
  (manual: выбрать «Личные сообщения» → открыть каждую);
- permsoc скрыт в DM (canViewTab false);
- селектор виден при единственной записи (DM);
- бейдж «ЛС #{id}» в шапке; BYOK-блок виден; «↪ глобальное» работают (сброс
  своего override в своём ЛС);
- `node --check web/app.js` clean.

## 7. Тесты (T-957; MED-019/MED-022)

- Юнит: `tests/test_dm_access.py` (is_dm_owner свой/чужой/глобальный в чужом ЛС 403/
  can_access+chat_id/eligible/can_edit keys→False/fail-open), `test_chat_params.py`
  (+ get_chat_param_defaulted: override→cast→fallback, мусор→fallback, БЕЗ hot-фолбэка;
  ensure_scope_profile DM/группа/повтор; chat_summary_enabled-матрица §4.3; регресс
  кэш/NOTIFY/409 — старые тесты зелёные), `test_summary_memory.py`+`test_direct_chat.py`
  (S1/S2: DM при глобальном ON + пустом профиле — конспект НЕ создаётся/не инжектится;
  override=true — создаётся), `test_summary_scheduler.py` (_tick: положительные id
  исключены; `reactions.summary_target_chat_ids`-источник тоже фильтруется),
  `test_chat_lore_store.py`/`test_lore_worker.py` (положительные id исключены),
  `test_oversight.py`, `test_chat_lore_api.py` (DM → 404);
- API: `test_webapp_api.py` (chats: DM-строка+фильтр; config 200/скрытие keys/
  read-only models/ctx.is_dm/POST ensure_scope_profile/422 keys-models/
  DELETE-сброс/403 чужого), `test_webapp_gates_api.py` (GET 200 read, PUT 403),
  `test_webapp_oversight_api.py` (без DM-строк);
- маркеры: НОВЫЙ `tests/test_webapp_dm_ui.py` (запись в селекторе, isDmCtx правило,
  «ЛС #{», BYOK-блок, empty-state «или Личные сообщения», resetChatOverride для DM);
  `test_webapp_nav_disclosure_ui` (1 селектор — после F-13), `test_webapp_rbac_ui`
  (без изменений);
- эталон каталога: `test_param_catalog` — без изменений (REGISTRY 383/71/359).

## 8. Границы (НЕ трогать — diff-проверка T-961)

- bot.py: порядок роутеров + гейт `flags.summary_enabled` (613-643) — без дифов;
- services/access.py: DEFAULT_MATRIX/effective_matrix/_normalize_perms/param_permissions —
  без изменений; существующие публичные функции chat_params (get_chat_param/
  set_chat_params/кэш TTL 120с/NOTIFY/409) — без изменений; hot_config/ConfigCache —
  без дифов;
- SummaryScheduler служба + generate_and_send — без дифов (фильтр ТОЛЬКО в _tick);
- DM-команды /clear /persona /tone /forget + handlers/direct_chat.py — без дифов;
- services/feature_gates.py + gates-канон (write — только global admin) — без изменений;
- каноны промптов / SQLite-схема / .env — без дифов;
- F-3 scam-followup T-663 (admin_commands.py) — без дифов (остаётся открытой);
- SQL-константы chat_lore_store — только добавка `chat_id < 0`;
- `test_frontend_tab_mapping`/`test_webapp_tma_fixes_ui` — без изменений.

## 9. Конфликты с активными фичами

- **F-1 `post-deploy-admin-minors`**: T-648 (атомарный POST /api/config) — тот же
  routes.py → **F-14 ДО T-648**; T-650 (docstring can_edit_param) — после F-14
  (функция расширяется is_dm-ветками); T-651/652 (унификация кастов) — учесть cast
  `get_chat_param_defaulted` (единый normalize_value-стиль).
- **F-3 `scam-incident-security-followup`**: T-663 (DM-гейты admin_commands.py:40-127) —
  та же DM-плоскость (chat_id>0); исполнять ПОСЛЕ F-14; в F-14 admin_commands.py
  НЕ дифится; T-663 остаётся ОТКРЫТОЙ (отметить в финальной проверке T-961).
- **F-5 `config-read-path-audit`**: новые read-пути (`chat_summary_enabled`,
  `get_chat_param_defaulted`) включить в остаточный аудит (стиль hot.get —
  обязателен; MED-003).
- **F-4 / F-6 / F-2** — пересечений нет.

## 10. Приёмка (метрики)

- полный pytest 0 failed (4760 + ~15-25 новых); `git diff --check` чист;
- `node --check web/app.js` clean;
- ручные (T-964 live): саммари ЛС OFF по умолчанию (даже при глобальном ON),
  юзер правит параметры своего ЛС, наследование от глобальных, ключи своего ЛС (BYOK),
  чужой DM недоступен (403/404), пермсок-вкладка скрыта в DM;
- R17: raw-ключи никогда (grep-проверка `api[_-]?key|token|secret|password`).
