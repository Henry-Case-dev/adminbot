# ADR-1025-2 — Единая state-machine сохранения, честный 409 и канонический write-path

- **Статус:** **Accepted** (Step 2 @Architect, 20.09.2026)
- **Фича:** F0 `f0-config-bugfixes-round1025` — F0.1 (409/Fallback) + F0.2 (аудит/save-path)
- **Тип:** backend + UI (persistence / optimistic-lock / state-machine)
- **Связано:** `spec.md` §1–§2; `tasks.md` T-2412…T-2426; F9 `secrets-and-save-states-round1025` (читает результат, не переписывает)
- **Задачи:** T-2412…T-2419 (F0.1), T-2420…T-2426 (F0.2)

## Контекст

1. `prompts.verbilizer_default_mode` — `per_chat=True` (`services/param_catalog.py:118-127`, категория `prompts`), хранится в `chat_profiles.chat_params`.
2. Дропдаун Fallback (V2) делает автосейв по `@change` **без await и без in-flight guard**: `web/app.js:4420-4427`, `web/index.html:479-487`.
3. Тот же `v-model` делает элемент `dirty`; SaveBar (`saveModalEdits`, `web/app.js:3164-3197`) шлёт тот же ключ повторно с **тем же** токеном `this.configChatUpdatedAt` (`web/app.js:5032`).
4. Серверный optimistic-лок — по `chat_profiles.updated_at` (`services/chat_params.py:UPDATE_PARAMS_LOCKED_SQL`, `set_chat_params`): второй запрос → 0 строк → `ChatParamsConflict` → **409** (`web/api/routes.py:612-621`).
5. Три противоречивых тоста на одно действие: успех (`web/app.js:5036`), 409 (`:5040-5042`), «Не сохранено» (`:3185-3188`).
6. `updated_at` — на уровне **профиля** (не ключа): конкурентная запись другого ключа даёт **ложный** 409 (T-2413).
7. Глобальный путь `_post_config_global` (`web/api/routes.py:890-931`) — не атомарный, без optimistic-проверки (T-2414).
8. `setActiveChat` обнуляет `configChatUpdatedAt` (`web/app.js:2220`); POST в окне до `loadConfig` уходит с `updated_at=null` → `set_chat_params` идёт по **незаблокированному** SQL (`chat_params.py:UPDATE_PARAMS_SQL`) → перезапись вслепую.

Формулировка §2 ТЗ: *не считать заранее доказанным ни один вариант; не «залечивать» расхождение случайными задержками (§2.2)*.

## Решение

### D1. Единая клиентская state-machine (не набор флагов)
Одно вычисляемое `saveState ∈ {loading, clean, dirty, saving, saved, error, conflict}`; плюс `OperationResult {saved:[], failed:[{key,reason}], state, revalidated}`. Частичный успех — `saved`/`error` **с** раздельными списками; запрещён «success+error» без объяснения частичного результата. При `error`/`conflict` черновик пользователя **не сбрасывается**.

### D2. Одна точка сохранения
Все писатели (`saveConfigItem`/`saveBlock`/`saveKeyItem`/`saveModalEdits`/автосейв `selectPromptMode`/`savePromptFallbackMode`) ходят только через `persistItems(items, {reason})`. Внутри: **guard in-flight по ключу** (двойной тап = один запрос), **scope-split** (chat-пакет одним POST с одним токеном; global-пакет — без X-Chat-Id), агрегация результата.

### D3. Токен: никаких chat-записей с `null`
Для chat-scope `updated_at` обязателен: если `configChatUpdatedAt == null` (сменили scope) — сначала дождаться/выполнить `loadConfig`, затем писать (закрывает слепую запись). Глобальный путь `updated_at=null` допустим (аддитивно для версии), но запись атомарна.

### D4. Честный 409 (сервер)
- **D-409-1 idempotent short-circuit:** при `expected_updated_at != None` и 0 строк UPDATE — прочитать root; если по всем ключам патча серверное значение совпадает с запрошенным → вернуть **200** `{updated:[…], revalidated:true, updated_at}`, не бросать `ChatParamsConflict`.
- **D-409-2 serialize:** мутации профиля сериализуются (in-process `asyncio.Lock` по `chat_id`; PG advisory-lock для multi-worker). Одна операция = одна мутация.
- **D-409-3 global:** глобальный POST валидирует весь пакет до записи и пишет атомарно; optimistic-проверка аддитивна и per-key.
- **D-409-4:** при реальном конфликте — 409 `{code:'conflict', current_updated_at, conflicting:[{key, your_value, server_value}], applied:[]}`.

### D5. 409-recovery на клиенте (§2.3)
Не показывать успех автоматически; сохранить черновик; `GET /api/config`; сравнить `conflicting[]`; если сервер уже содержит запрошенное — «выполнено после проверки» (`revalidated`); иначе показать конфликтующие поля; **без слепой перезаписи** и **без бесконечных retry**.

### D6. Канонический серверный write-path (F0.2)
- chat: `POST /api/config` → атомарный `set_chat_params` (уже так) + D4;
- global: `POST /api/config` → атомарный пакет `ConfigCache` + D4;
- секреты (`keys.*`) — **только** BYOK-эндпоинт `/api/config/keys/own` (не смешивать; §50 — F9);
- аудит (T-2420/T-2421) — инвентарь механизмов + цикл `load→edit→save→re-read→compare` (HTTP 200 не доказательство).

### D7. Устаревшие ответы и scope-изоляция
Каждый запрос несёт `scopeEpoch` (`_scopeGuard`, `web/app.js:4675/4709`); ответ старого scope игнорируется. Локальное не перезаписывается глобальным; «не создавать копию конфигурации под каждый визуальный экземпляр» (T-2423).

## Последствия

**Positive**
- Одно действие → одна мутация → нет ложного 409; Fallback сохраняется, нижняя панель в согласованном состоянии.
- Повторный/идемпотентный 409 при уже применённом значении → «сохранено» без шумного конфликта (T-2415).
- Глобальный путь становится атомарным; убрана слепая null-запись.
- Единый write-path закрывает дрейф источников истины (T-2424) и переносит исправленный механизм в F1.

**Negative**
- Дополнительная server-serialization (lock по `chat_id`) — небольшая латентность на конкурентных записях одного профиля; приемлемо.
- Advisory-lock требует PG-поддержки; при недоступности PG путь и так 503.
- Частичный успех при смешанном chat+global пакете остаётся возможным (2 запроса) — отображается честно, а не маскируется.

## Альтернативы

- **A1. Лечить задержками/повторами** — **отклонено**: запрещено §2.2; дефект вернётся после F1.
- **A2. Optimistic-лок на уровне ключа** — **отложено**: точнее, но требует смены носителя версии (per-key), что расширяет DDL/контракт; для F0 достаточно serialize + idempotent short-circuit + §2.3.
- **A3. Клиентский mutex без серверного** — **отклонено**: две сессии/воркеры остаются незащищёнными.
- **A4. Авто-retry на 409** — **отклонено**: риск бесконечного цикла; восстановление — один раз через перечитывание и сравнение.

## Ссылки

- Спека: `plans/features/f0-config-bugfixes-round1025/spec.md` §1–§2
- Задачи: `tasks.md` T-2412…T-2426
- Код: `services/chat_params.py` (set_chat_params, ChatParamsConflict), `web/api/routes.py:381-626,890-931`, `services/param_catalog.py:118-127,479-482`, `web/app.js:1616-1643,1984-2022,2181-2234,3124-3197,3727-3814,4382-4444,4983-5104`, `web/index.html:469-490`
- Прецеденты optimistic-протокола: `ChatLoreConflict`/`PersonaConflict`, 10.20/10.21/BYOK

## Human Gate

- **Открытые вопросы** (см. spec §10): нужен ли per-key optimistic-лок в этом раунде или достаточно serialize+short-circuit; допустимо ли 409 с `conflicting` для global-пути сразу или аддитивно. Значения (retry одна попытка recovery, без авто-повторов) — техническая настройка @Architect. Прогрессивная раскатка не требуется.
