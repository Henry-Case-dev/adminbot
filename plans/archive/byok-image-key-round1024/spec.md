# Spec: byok-image-key-round1024 (F11)

> Раунд 10.24 (UPD2 п.9 + UPD3 №6) · P1 · UI/web + backend (routes/chat_keys) · Владелец: F11
> Ступень `web/**`: **4-я** (F3 → F5 → F6 → **F11** → F4 → F10)
> Ступень `web/api/routes.py` + `services/chat_keys.py`: изолирована
> **ADR:** ADR-1024-12 (AMEND ADR-1023-5 §D3)
> **✅ Human Gate №6 — ЗАКРЫТ (UPD3 №6):** сохранение image-ключа через безопасный
> эндпоинт согласовано. **Секреты не цитировать (R17/R18).**

## 1. Цель

Починить сохранение API-ключа генерации изображений в TMA:
1. Новый ключ уходит **отдельным безопасным запросом** на `/api/config/keys/own`,
   а **не** в общий `PUT /api/config` (сейчас даёт 422: «ключ-секрет задаётся через
   /api/config/keys/own» при чат-контексте).
2. Если ключ есть в БД — бэкенд не возвращает его значение в общих настройках;
   фронт показывает заглушку `••••••••••••` / «Ключ установлен».
3. «Режим GET-запроса»: при включении поле ключа **блокируется (disable)** и
   **очищается**; ключ не уходит на сервер.

## 2. Что уже есть (координаты)

| Что | Где |
|---|---|
| Ошибка чат-пути: `CATEGORY_KEYS` → 422 «…BYOK-путь» | `web/api/routes.py:489-493` |
| BYOK-эндпоинты GET/PUT/DELETE `/api/config/keys/own` (требуют `X-Chat-Id`) | `web/api/routes.py:571-665` |
| Whitelist BYOK: `{"keys.llm_api_key"}`; проверки в set/delete | `services/chat_keys.py:20,43-44,85-86,110-111` |
| `IMAGE_API_KEY` — **глобальный** (`keys.image_api_key`, `secret=True`, `per_chat=False`) | `services/param_catalog.py:609-610`; `_KEYS` builder `:1751-1754`; `per_chat` `:118-127` |
| Глобальный путь `_post_config_global` разрешает keys для владельца | `web/api/routes.py:752-793` |
| Frontend провайдер-блок изображений | `web/app.js:539-551` (`image_generation`, `testable:false`) |
| Сохранение блока `saveBlock` (секрет попадает в общий POST) | `web/app.js:3322-3394` |
| `saveKeyItem` (секреты), `_seedSecretMasks`, `hasSecretMask`, `blockFieldValue` | `web/app.js:4441-4473, 2805-2818, 3180-3186` |
| Существующий BYOK-UI для llm-ключа (`saveOwnKey`) | `web/app.js:2121-2154` |
| `image_generation._resolve_str(KEY_API_KEY)` читает **глобальный** кэш | `services/image_generation.py:151-156, 414` |

**Корень конфликта:** `keys.image_api_key` — **глобальный** секрет провайдера.
Общий `POST /api/config` с чат-контекстом отвергает `keys.*` (422), а BYOK-эндпоинт
per-chat не принимает глобальный ключ и требует `X-Chat-Id`. `image_generation`
резолвит ключ только из глобального слоя → per-chat BYOK для картинки backend'ом
не поддерживается.

## 3. Требуемое поведение

### 3.1. Backend: безопасный эндпоинт для глобального секрета (AMEND `chat_keys`)

- В `services/chat_keys.py` ввести отдельный allowlist **глобальных** секретов
  (не per-chat): `GLOBAL_SECRET_KEYS = frozenset({"keys.image_api_key"})` и хелпер
  `is_global_secret(key_name)`.
  - `BYOK_KEYS_WHITELIST` (`{"keys.llm_api_key"}`) — **не менять**: per-chat BYOK
    остаётся только для llm-ключа.
  - Per-chat image-ключ **не** добавляем: нет per-chat резолва в `image_generation`,
    добавили бы «ручку без эффекта» (сознательное решение, см. ADR-1024-12 D2).
- Расширить `/api/config/keys/own`:
  - тело PUT получает **опциональное** `scope: "auto"|"global"|"chat"` (default `auto`);
  - `scope="auto"`: при наличии `X-Chat-Id` → поведение как сейчас (chat BYOK);
    без `X-Chat-Id` → global-секрет (для `is_global_secret`).
  - `scope="global"`: разрешён **только глобальному админу** и **только** для
    `is_global_secret(key_name)`; значение сохраняется в глобальный слой
    (`cache.set(key_name, value, CATEGORY_KEYS)`) — тем же хранилищем, что и текущий
    глобальный путь; наружу возвращается **маска** `{configured,last4}` (R17);
    строка в `chat_keys` **не создаётся**.
  - Не-whitelisted/не-global ключ → 422; нет прав → 403; PG недоступен → 503.
- DELETE для global-секрета — по тому же правилу (`scope`/отсутствие `X-Chat-Id`),
  с записью в audit (`chat_lore_history`/аналог, как у BYOK).
- GET `/api/config/keys/own` для global-секретов: возвращает маску без raw.
- **`GET /api/config` — без изменений:** по-прежнему отдаёт `keys.*` только как
  `{configured,last4}` (никогда raw) — требование UPD2 п.9 соблюдено уже сейчас.

### 3.2. Frontend: маршрутизация секретов

- Отделить «глобальные провайдерские секреты» от per-chat BYOK. Хелпер
  `saveProviderSecret(key, value, {scope})`:
  - `keys.image_api_key` (глобальный провайдерский секрет) → `PUT /api/config/keys/own`
    с телом `{key_name, value, scope:'global'}` и **без** `X-Chat-Id`
    (использовать `global:true` в `api()`);
  - `keys.llm_api_key` в чат-контексте → существующий per-chat BYOK (без изменений);
  - прочие секреты — как сейчас.
- В `saveBlock` **исключить** секреты из общего `POST /api/config`: собирать их
  отдельным списком и отправлять через `saveProviderSecret`. Никакой `keys.*` не
  должен попадать в `items` общего запроса.
- Сохранить guard `hasSecretMask` (маска/композит → no-op, 0 POST).

### 3.3. UI-заглушка и GET-режим

- **Установленный секрет:** `blockFieldValue` уже возвращает `SECRET_MASK`
  (`••••••••••••`) при `{configured:true}`; добавить явный бейдж **«Ключ установлен»**
  рядом с полем. Если `configured:false` — обычный пустой инпут с placeholder.
- **GET-режим** (`models.image_get_mode === true`):
  - поле ключа `disabled`;
  - черновик ключа очищается (`blockDrafts[key]=''`), в отправку не попадает;
  - визуальная подсказка «в GET-режиме ключ не используется» (уже есть `hint`).
  - очистка — **только UI** (никакого автоматического DELETE ключа из БД).
- При выключении GET-режима поле снова редактируемо (значение из БД — маской).

## 4. Изменения по файлам

| Файл | Что |
|---|---|
| `services/chat_keys.py` | `GLOBAL_SECRET_KEYS`, `is_global_secret`; (опц.) helper маски (уже есть). |
| `web/api/routes.py` | `PUT/GET/DELETE /api/config/keys/own`: `scope`, global-ветка, RBAC, маска, audit. |
| `web/app.js` | `saveProviderSecret`; `saveBlock` не отправляет секреты в общий POST; `saveKeyItem` — совместимость; GET-режим disable+clear; бейдж «Ключ установлен»; `uiFlag`. |
| `web/index.html` | Провайдер-блок: бейдж «Ключ установлен», disabled-состояние уже через `dependsOn`. |
| `config/settings.py` + `routes.me` | `BYOK_IMAGE_KEY_ENABLED` (enabler). |
| `tests/**` | §6. |

## 5. Контракты

- **Секрет наружу — ТОЛЬКО** `{configured,last4}` (R17). Raw не отдаётся ни в
  `/api/config`, ни в `keys/own`-ответах.
- **`scope="global"`:** только global admin + только `is_global_secret`; хранит в
  глобальном слое; `X-Chat-Id` отсутствует.
- **BYOK per-chat:** `BYOK_KEYS_WHITELIST = {"keys.llm_api_key"}` не расширяется.
- **`image_generation`:** резолв ключа не меняется — читает глобальный кэш, куда
  пишет global-ветка (`cache.set`) → фича работает без правок сервиса.
- **GET-режим:** ключ не участвует в запросе (строго анонимный GET), UI-очистка
  без DELETE.
- **Fail-open/ошибки:** 422 не-whitelisted, 403 нет прав, 503 PG down.

## 6. Тесты

- **Python (`tests/test_byok_image_key_round1024.py`):**
  - `is_whitelisted("keys.image_api_key") is False` (per-chat BYOK не расширен),
    `is_global_secret("keys.image_api_key") is True`;
  - `PUT /api/config/keys/own` (global admin, no `X-Chat-Id`, `scope:'global'`) →
    200 + маска; значение появилось в глобальном слое (`cache.get`);
  - обычный админ/нет прав → 403; не-global ключ с `scope:'global'` → 422;
  - GET/ответ **никогда** не содержит raw-значения (поиск подстроки значения —
    отсутствует); лог-строки без значения (R17);
  - `GET /api/config` для `keys.image_api_key` → `{configured,last4}`;
  - DELETE global-секрета → удаляет из глобального слоя, audit-запись.
- **JS (`tests/js/round1024_image_key_test.js`):**
  - `saveBlock` для `keys.image_api_key` вызывает `/api/config/keys/own`
    (PUT, `global:true`), а **не** общий `/api/config`;
  - маска/композит → no-op (0 POST);
  - GET-режим: поле `disabled`, draft очищен, ключ не в теле;
  - `node --check web/app.js`.
- **Гейт:** `tests/js/vue_mount_test.js` зелёный.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | Утечка секрета (git/логи/ответы) | Critical | только маска; тест «нет plaintext»; R17 |
| R2 | Расширение BYOK меняет модель прав | High | global-ветка только для global admin + явный allowlist; AMEND ADR |
| R3 | Совместимость с уже сохранённым глобальным ключом | Medium | глобальный слой — то же хранилище; миграции не нужны; тест резолва |
| R4 | UI-очистка в GET-режиме удалит ключ из БД | Medium | очистка только локального draft; без DELETE (явный тест) |
| R5 | Конфликт с F12 (кнопка теста в том же блоке) | Low | ступень §2: F12-UI отдельным шагом после F5 |

## 8. Критерии приёмки

- Новый image-ключ сохраняется **без ошибки** через `/api/config/keys/own`.
- После перезагрузки поле показывает заглушку/«Ключ установлен», ключ есть в БД.
- GET-режим блокирует и очищает поле.
- Секрет **не** появляется в общих настройках, ответах и логах.
- Δ DDL = 0, Δ каталога = 0; pytest/JS-гейт зелёные.

## 9. Флаг и откат

- `BYOK_IMAGE_KEY_ENABLED` (env-only `ClassVar`, **default ON**) через `ui_flags`;
  OFF → `GLOBAL_SECRET_KEYS` пуст (global-ветка отключена), прежнее (сбойное) поведение.
- Откат: флаг OFF / `git revert`. Миграций нет.
