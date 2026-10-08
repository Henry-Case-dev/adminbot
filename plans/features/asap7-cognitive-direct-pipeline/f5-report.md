# F5 — Chat lifecycle fix (ASAP 7, Wave 1)

Дата: 2026-10-09. HEAD `08a8849` (+ незакоммиченные изменения F3/F8-лейнов в общем дереве — не тронуты).
Контракт: architecture.md §4 / §5.1 (SECTION-ACCESS); audit-modules-chat-claims.md P7-C-1/2/6; current_task §7, §17 (C1–C9).

## Изменено (file:line)

1. **`handlers/chat_lifecycle.py`**
   - `:87-100` `on_bot_joined_my` / `:185-196` `on_bot_left_my` — новые хендлы на `my_chat_member`-observer с теми же `ChatMemberUpdatedFilter` (IS_NOT_MEMBER>>IS_MEMBER / обратно); делегируют в общие `_handle_bot_joined`/`_handle_bot_left` (:103, :198) — переиспользуют `upsert_profile_on_join` + `set_active` + `ensure_gates_defaults` (гейт-дефолты только для новых, :123). Существующие `chat_member`-хендлеры сохранены (:77-84, :172+).
   - `:250-269` `on_chat_migrated`: при отсутствии профиля нового id — `upsert_profile_on_join` + `set_active(True)` + gates-дефолты (C9); плюс гигиена `_profile_seen` (old discard / new add).
   - `:277-360` fallback-регистрация: `ChatProfileFallbackMiddleware` (thin, fail-open, handler-цепочку не меняет), `maybe_ensure_group_profile` — только `chat_id<0` из message-like полей Update, только при отсутствии профиля (позитивный кэш `_profile_seen`) + backoff-память `_fallback_last_try` (300 с) — PG не зовётся на каждое сообщение; идемпотентен (ensure+set_active+gates); телеметрия `chat_profile_fallback` success/failed (MCA-17 fail-open); `reset_fallback_memory()` — тест-хук.
2. **`bot.py`** `:135-138` импорт; `:896-902` `dp.update.outer_middleware(chat_profile_fallback_middleware)` — единая точка входа message-роутинга ДО диспетчеризации (проверено: `Dispatcher().update.outer_middleware` существует, aiogram 3.31).
3. **`config/settings.py`** `:586-593` единственный помеченный блок: `CHAT_PROFILE_FALLBACK_ENABLED` ClassVar (env, default ON, Δ каталога = 0).
4. **`web/app.js`** (только SECTION-ACCESS): `:4316-4318` badge «неактивен» для `is_active===false` (не-DМ) в `scopeOptions` (в брифе «activeChatOptions :4242-4265»; реальное имя функции — `scopeOptions`); `:10925-10937` `toggleScope` → `this.loadAccessCtx()` при открытии селектора (re-fetch; fail-safe: loadAccessCtx весь в try/catch, stale-id контракт C8 внутри неё сохранён). Helpers с префиксом F5_ не потребовались.
5. **`web/api/access.py`** — НЕ менялся: `is_active` уже в ответе (`:224`), badge строится клиентом; RBAC `:192-238` не тронут.
6. **`tests/test_asap7_chat_lifecycle.py`** — новый, 22 теста. TEST-LIFECYCLE: REGRESSION owner=ASAP7/F5.

## Проверено (команды → результат)

- `pytest tests/test_asap7_chat_lifecycle.py -x -q` → **22 passed**. C1: my_chat_member-observer имеет join/leave-хендлы (root cause P7-C-1 — observer был пуст), join создаёт активный профиль + gates-дефолты новым; C2: профиль переживает «рестарт», повторный join — без дубля; C3: leave→is_active=false + **на реальном app.js** (node-сниппет scopeOptions): inactive-чат в списке с badge «неактивен», active без badge, ЛС «ЛС»; C4: re-add реактивирует тот же профиль, gates не переписываются; C5: fallback по первому сообщению (ensure+set_active+gates), backoff не даёт повторных store-вызовов, известный профиль не ре-ensure, DM/не-message скип, гейт OFF → no-op, store-ошибка → fail-open + backoff записан, middleware пропускает handler при `_store=None`; C6/C7: локальный админ не видит чужой чат (роль `local_admin`), DM-строка на месте; title-failure → «Чат <id>», чат не скрыт; C8: **на реальном app.js** (node-сниппет loadAccessCtx): stale saved-id удаляется из localStorage, scope → null, app не ломается; C9: migration переносит профиль без дубля, при отсутствии old-профиля — создаёт новый активный, is_active=False при переносе сохраняется (не silent-реактивация).
- `node --check web/app.js` → OK. `node tests/js/routing_test.js` → `JS-UNIT-OK` (exit 0).
- `py_compile bot.py handlers/chat_lifecycle.py config/settings.py tests/...` → OK.
- Связанные существующие тесты точечно: `pytest tests/test_chat_lifecycle.py tests/test_mca03_message_identity_round1027.py tests/test_mca17_perimeter_events.py -q` → **55 passed**; `pytest tests/test_chat_lore_store.py tests/test_access.py tests/test_chat_lore_api.py -q` → **108 passed**.

## Инварианты

- join (любой observer) создаёт профиль + is_active=true → строка попадает в `/api/access/chats` (SELECT по `chat_profiles`, endpoint не менялся — C6/C7 фиксируют его контракт).
- leave → is_active=false, данные сохраняются; UI показывает с badge «неактивен», не скрывает.
- re-add идемпотентен (upsert + set_active(True); gates только для новых).
- fallback при пропущенном join — одно сообщение → один ensure; повторы ≤1/300 с на чат; `CHAT_PROFILE_FALLBACK_ENABLED=false` → байт-в-байт прежний message-роутинг.
- RBAC access.py не ослаблен (тест C6); миграций DDL нет; ручных DB-фиксов нет.

## Известные ограничения / примечания

- Интеграционная цепочка «join → живой PG → HTTP /api/access/chats» в unit-прогоне не собирается (нет PG в тестах) — оба шва покрыты отдельно (хендлер + endpoint); live-проверка — owner-гейт после деплоя (добавить бота в новый чат, открыть селектор).
- В общем рабочем дереве `web/app.js` также содержит незакоммиченные правки F8 (SECTION-COVER-RUNS/…); мой вклад в app.js — ровно 2 хунка SECTION-ACCESS (см. git diff: badge :4316, toggleScope :10925).
- `_profile_seen`/`_fallback_last_try` — in-memory, чистятся при рестарте процесса (fallback после рестарта сработает один раз — ожидаемо).
- При merge с F8/F3 порядок фиксирует архитектура (§5.1); мои хунки изолированы в SECTION-ACCESS.

## Fan-out

Не использовался (LEAF-режим, WRITER_BUDGET=0).
