# Ревью F11 `byok-image-key-round1024` — Шаг 5, раунд 10.24

- **Коммит:** `1e93c92` (заявлено pytest 7830)
- **Ревьюер:** @Reviewer
- **Дата:** 20.09.2026
- **Артефакты:** `spec.md`, `ADR-1024-12.md`, `tasks.md`, `plans/current_task.md` UPD2 п.9 + UPD3 п.6, `plans/features/round1024-web-architecture.md` §3
- **Верификация:** `git show 1e93c92 --stat`, `git diff 1e93c92^ 1e93c92`; полный `pytest` на рабочем дереве; `node --check web/app.js`; `tests/js/round1024_image_key_test.js`; `tests/js/vue_mount_test.js`

## Статус

**Changes Requested**

Итог: базовый сценарий владельца (глобальный админ) починен — image-ключ уходит на `/api/config/keys/own` с `scope:'global'`, пишется в тот же глобальный слой, который читает `image_generation`, наружу отдаётся только `{configured,last4}`, whitelist per-chat не расширен, audit маскирован, Δ DDL/Δ каталога = 0, полный pytest 7830 зелёный. Однако есть **разрыв модели прав между UI и новым безопасным эндпоинтом**: фронтовый `canEditConfig` разрешает править `keys.image_api_key` роли с секцией `keys` (не global admin), а `PUT /api/config/keys/own scope=global` такую роль режет 403. Для таких ролей ключ не сохраняется — теперь с 403 вместо прежнего успеха (в глобальном скоупе старый `/api/config` их пропускал через `can_view_key_value`). Плюс kill-switch `BYOK_IMAGE_KEY_ENABLED` не потребляется фронтом (spec §4/arch §3 требуют `uiFlag`), а из тестов spec §6 отсутствуют проверки логов (R17) и reload. Без правок выпускать нельзя — UI обещает возможность, бэкенд её отбирает.

---

## Findings

### [High] Рассинхрон прав: поле ключа активно, но safe-эндпоинт отдаёт 403

- **Файлы:** `web/app.js:4406-4428` (`canEditConfig`, ветка `cat === 'keys'` — `:4424-4425`), `web/index.html:296-302` (`:disabled="!canEditConfig(f.key) ..."`), `web/api/routes.py:690-696` (глобальная ветка: `if not ctx.is_global_admin → 403`).
- **Проблема:** `canEditConfig('keys.image_api_key')` возвращает `true`, если у роли есть `sections: ['keys']` или точный `key.keys.image_api_key`. При этом новая глобальная ветка требует `ctx.is_global_admin` (= `role_type == global_admin` ИЛИ `wildcard`). Для роли с секцией `keys`, но без `wildcard`, поле в карточке «Генерация изображений» остаётся **редактируемым**, пользователь вводит ключ, жмёт «Сохранить» — и получает `403 «только для глобального админа»`.
- **Почему это важно:** это регрессия модели прав. Раньше в глобальном скоупе (без `X-Chat-Id`) image-ключ сохранялся общим путём `_post_config_global` (`web/api/routes.py:886` → `can_view_key_value`), а матчинг `services/permissions.py` правило 3 («секция `keys` покрывает любой `key.*`») такую роль пропускал. Теперь — 403 при активном поле. Хуже того, в `saveBlock` (`web/app.js:3639-3644`) секреты сохраняются **до** остальных полей: 403 по ключу обрывает сохранение всего блока (адрес/модель/GET-режим тоже не уедут). Оператор видит «доступ запрещён» на карточке, которую ему разрешили открыть и править.
- **Required fix:** привести UI в соответствие с бэкендом. Минимально — в `canEditConfig` для полей с `globalSecret` (или конкретно `keys.image_api_key`) возвращать `this.isGlobalAdmin` вместо проверки секции `keys`; в шаблоне поле должно быть `disabled` с подсказкой «только глобальный админ». Альтернатива (если владелец хочет сохранить права секции `keys`) — осознанно выровнять авторизацию эндпоинта на `can_view_key_value(cache, user.id, payload.key_name)` и зафиксировать это AMEND-ом ADR-1024-12 (сейчас там прямо «только global admin»). Добавить тест на роль с `sections:['keys']` без wildcard: ожидаемое поведение (403 + disabled в UI ИЛИ 200) должно быть зафиксировано, а не оставаться неопределённым.

### [Medium] Kill-switch `BYOK_IMAGE_KEY_ENABLED` не потребляется фронтендом

- **Файлы:** `web/app.js:2354-2381` (`saveProviderSecret`/`saveImageKeyItem`), `web/api/routes.py:354-357` (флаг доставляется в `/api/me.ui_flags`), `services/chat_keys.py:56-63` (`is_global_secret` читает флаг).
- **Проблема:** spec §4 явно перечисляет в изменениях `web/app.js` пункт `uiFlag`; arch §3 (ADR-1024-13) шаг 3 требует «`uiFlag(name)` читает `this.me.ui_flags` … применяется в `v-if`/computed», а таблица OFF-поведения (`round1024-web-architecture.md:110`) обещает при OFF «прежнюю маршрутизацию секрета (с ошибкой)». В коммите фронт **нигде не читает** `BYOK_IMAGE_KEY_ENABLED` (grep по `web/` — только бэкенд). При OFF фронт по-прежнему шлёт PUT на safe-эндпоинт, бэкенд отвечает 422 (`workers`), и пользователь получает ошибку на «новом» пути, а не прежнюю маршрутизацию.
- **Почему это важно:** заявленный рубильник не является настоящим kill-switch для UI-части: «откатить» фичу одним env-флагом нельзя, приходится `git revert`. Это ровно тот пункт «долг по флагам», ради которого вводился ADR-1024-13.
- **Required fix:** в `saveProviderSecret`/`saveImageKeyItem` (и в отображении бейджа/маршрутизации) гейтить по `this.uiFlag('BYOK_IMAGE_KEY_ENABLED')`: при OFF — прежний путь (`POST /api/config`), при ON — safe-эндпоинт. Добавить JS-тест с `ui_flags.BYOK_IMAGE_KEY_ENABLED = false`, проверяющий прежний URL.

### [Medium] Не покрыты требуемые spec §6 проверки: логи (R17) и reload

- **Файлы:** `tests/test_byok_image_key_round1024.py` (весь файл), `tests/js/round1024_image_key_test.js` (весь файл).
- **Проблема:** spec §6 для Python-тестов прямо требует «лог-строки без значения (R17)» — ни одного ассерта по логам (`caplog`) нет. Пункт задания «reload» также не покрыт: `test_no_raw_after_save_anywhere` (`:316-326`) делает GET после PUT, но проверяет лишь отсутствие raw, а не `configured:true/last4` (то есть не доказывает, что ключ «не потерялся после перезагрузки»). Бейдж «Ключ установлен» проверяется только как маркер поля `globalSecret:true` (`tests/js/round1024_image_key_test.js:91-92`), но не как факт отрисовки разметки (`web/index.html:303-306`).
- **Почему это важно:** заявленные «тесты маски/логов/reload» — неполные; зелёный прогон не доказывает ни R17 по логам, ни ключевое UX-обещание «после перезагрузки поле показывает заглушку, ключ есть в БД».
- **Required fix:** добавить (а) `caplog`-тест: после PUT/GET/DELETE raw-значение отсутствует во всех записях логов (образец — F12 `test_probe_error_redacts_unprefixed_key`); (б) тест reload: после PUT `GET /api/config` → `items['keys.image_api_key']['value'] == {"configured": True, "last4": ...}`; (в) JS/структурный ассерт на наличие в `index.html` строки «Ключ установлен» для `globalSecret`-поля.

### [Medium] Контракт `saveProviderSecret(key, value, {scope})` не выполнен

- **Файл:** `web/app.js:2354-2366`.
- **Проблема:** spec §3.2 фиксирует сигнатуру `saveProviderSecret(key, value, {scope})` с ветками для `image` (global safe), `llm` в чат-контексте (per-chat BYOK) и прочих. Реализация: `saveProviderSecret: async function (key, value)` — параметр `scope` отсутствует, ветка `keys.llm_api_key → per-chat BYOK` не реализована, `scope:'global'` захардкожен для одного ключа. Сегодня работает, потому что вызывается только из `saveBlock` для провайдерских (глобальных) секретов, а per-chat `llm` идёт через `saveOwnKey`. Но заявленный контракт не выполнен.
- **Почему это важно:** любое будущее обращение к `saveProviderSecret` с per-chat-ключом (например, из карточки «Прямые ответы» в чат-скоупе) молча уйдёт в глобальный слой без `X-Chat-Id`, записав не туда — «ручка без домена».
- **Required fix:** либо реализовать опциональный `opts.scope` и ветку `keys.llm_api_key`→per-chat (как в spec), либо обновить spec/ADR до фактического поведения и назвать функцию честнее (`saveGlobalProviderSecret`), чтобы захардкоженная глобальность была явной.

### [Low] `GLOBAL_SECRET_KEYS` не пуст при OFF (буквально по spec §9)

- **Файл:** `services/chat_keys.py:25,56-63`.
- **Проблема:** spec §9: «OFF → `GLOBAL_SECRET_KEYS` пуст (global-ветка отключена)». Реализовано мягче — frozenset остаётся, гейт через `is_global_secret()`. Все текущие call-site (`routes.py:658-660,695,757`) действительно используют `is_global_secret`, поэтому функционально эквивалентно.
- **Почему это важно:** расхождение спеки и кода, плюс `GLOBAL_SECRET_KEYS` остаётся непустым и его легко использовать напрямую, обойдя рубильник (что и делает `routes.py:659` в списковом включении, фильтруя далее — сейчас безопасно).
- **Required fix:** либо привести spec §9 к фактической реализации (гейт-хелпер), либо в `GET`/ветках использовать исключительно `is_global_secret` (уже так) и добавить комментарий; ideal — сделать allowlist функцией с учётом флага.

### [Low] Placeholder при `configured:false` не «пустой с placeholder»

- **Файл:** `web/app.js:3497-3503` (`blockFieldPlaceholder`).
- **Проблема:** spec §3.3: «Если `configured:false` — обычный пустой инпут с placeholder». Реально `blockFieldPlaceholder` для объекта `{configured:false}` возвращает строку `'не настроен'`, а не `f.label`. Косметика, поведение прежнее.
- **Required fix:** уточнить spec или вернуть `f.label` при `configured:false`.

---

## Контракт

### Чекбоксы по spec §4 / tasks.md

| Пункт | Статус |
|---|---|
| `GLOBAL_SECRET_KEYS={"keys.image_api_key"}`, `is_global_secret` | ✅ `services/chat_keys.py:25,56-63` |
| `BYOK_KEYS_WHITELIST` НЕ расширен | ✅ `services/chat_keys.py:20`; тест `test_per_chat_whitelist_not_expanded` |
| PUT global: `scope`, RBAC global admin (403), 422 не-global, 503 PG down | ✅ `web/api/routes.py:687-709`; тесты `TestGlobalPut` (403/422/503 — 503 покрыт общей проверкой ветки, отдельных нет) |
| Запись в глобальный слой (тот же, что читает `image_generation`) | ✅ `cache.set(..., CATEGORY_KEYS)` → `bot_settings` (`services/config_cache.py:499-521`); тест `test_put_global_scope_saves_to_global_layer_and_masks` |
| GET keys/own (global) — только маска | ✅ `routes.py:653-661`; тест `test_global_get_keys_own_returns_mask_no_raw` |
| DELETE global — сброс слоя + audit | ✅ `routes.py:752-771`; тесты `TestGlobalDelete` |
| `GET /api/config` без изменений (только `{configured,last4}`) | ✅ diff по `get_config` отсутствует; тест `test_get_config_masks_image_key` |
| Frontend: `saveProviderSecret`/`saveImageKeyItem` → safe-эндпоинт `scope:'global'` без `X-Chat-Id` | ✅ `web/app.js:2354-2381`; JS-тест кейсы 1, 5 (⚠️ сигнатура без `scope` — M) |
| Секрет НЕ в общем POST | ✅ `web/app.js:3607-3644`; JS-тест кейс 1 |
| Guard `hasSecretMask` (маска/композит → 0 POST) | ✅ `web/app.js:3616`; JS-тест кейс 2 |
| Бейдж «Ключ установлен» / `••••••••••••` | ✅ `web/index.html:303-306`, `blockFieldValue` `web/app.js:3419-3431` (⚠️ нет ассерта разметки — M) |
| GET-режим: disabled + clear, без DELETE | ✅ `web/app.js:3461-3469`, `web/index.html:302,311-314`; JS-тесты кейсы 3, 4 |
| Reload не теряет ключ | ⚠️ частично (backend PUT→layer есть, GET-маски есть; явного reload-теста нет — M) |
| `uiFlag` в app.js (spec §4) | ❌ **M** — фронт флаг не читает |
| RBAC-паритет UI/бэкенд для поля ключа | ❌ **H** |

### Инварианты

| Инвариант | Статус |
|---|---|
| egress `SEND_POINTS`/`SEND_ALLOWLIST` | ✅ новых send-точек нет |
| `parse_mode=None` plain-каналов | ✅ не затронут |
| `physical-two-call` | ✅ не затронут |
| Δ DDL = 0 | ✅ `services/pg_db.py` в diff нет; audit переиспользует `chat_lore_history` (`field='chat_keys'` есть в CHECK `pg_db.py:204-207`) |
| Δ каталога = 0 | ✅ `services/param_catalog.py` не менялся; флаг env-only `ClassVar` (`config/settings.py:645-646`) |
| R16 (аддитивность) | ✅ `ui_flags` дополнен ключом `BYOK_IMAGE_KEY_ENABLED` |
| R17 (секреты только `{configured,last4}`, не логировать) | ✅ по коду: `mask_key_info`, лог `mode=mask` без значения, audit `'***'`; ⚠️ нет теста логов (M) |
| R18 (секреты не коммитить/цитировать) | ✅ в diff только фейковые значения (`img-secret-value-9999`) |
| F12 probe-save не сломан | ✅ `testBlock`/`probeEndpoint` не менялись; полный pytest зелёный |
| `GLOBAL_AUDIT_CHAT_ID=0` корректен | ✅ `chat_lore_history.chat_id BIGINT NOT NULL` без FK; CHECK `field` включает `chat_keys` |

### Тесты

- Backend: запись/маска/слой/аудит/403/422/GET-маска/DELETE/флаг-OFF — ✅ (`tests/test_byok_image_key_round1024.py`, 19 тестов).
- Backend: raw в логах (R17) — ❌ нет.
- Backend: reload (`configured` после PUT) — ⚠️ частично.
- JS: маршрутизация image → safe-эндпоинт, не в общий POST — ✅ (не тавтологичен: проверяет отсутствие raw и `keys.image_api_key` в теле `/api/config`).
- JS: маска/композит → 0 POST — ✅.
- JS: GET-режим disabled/clear/без DELETE — ✅.
- JS: UI-заглушка как разметка — ❌ только маркер `globalSecret`.
- JS: OFF-флаг — ❌ нет.
- Гейты: `node --check web/app.js` → OK; `round1024_image_key_test.js` → `IMAGE-KEY-OK`; `vue_mount_test.js` → `VUE-MOUNT-OK`.

### Верификация прогона

- Полный `pytest` (`.venv`, `--timeout=120`): **7830 passed, 1 warning** — заявленное число подтверждено (100.96s).
- Целевой модуль: `tests/test_byok_image_key_round1024.py` → 19 passed.
- `git diff --check 1e93c92^ 1e93c92` — чисто; в diff нет `pg_db.py`/`param_catalog.py`/миграций.

---

## Точный список правок (блокеры)

1. **H (рассинхрон прав):** привести `canEditConfig`/шаблон к правилу эндпоинта — поле `keys.image_api_key` редактируемо только при `this.isGlobalAdmin` (или осознанно выровнять авторизацию на `can_view_key_value` + AMEND ADR). Тест на роль с `sections:['keys']` без wildcard.
2. **M (kill-switch):** гейт `saveProviderSecret`/`saveImageKeyItem` по `this.uiFlag('BYOK_IMAGE_KEY_ENABLED')`; JS-тест OFF → прежний путь.
3. **M (тесты spec §6):** `caplog`-ассерт отсутствия raw в логах (PUT/GET/DELETE); reload-тест `configured:true/last4` после PUT; ассерт разметки «Ключ установлен».
4. **M (контракт `saveProviderSecret`):** реализовать `opts.scope`/ветку per-chat `llm` ИЛИ синхронизировать spec/ADR с фактической сигнатурой.
5. **L:** spec §9 vs `GLOBAL_SECRET_KEYS` при OFF; placeholder при `configured:false` — устранить или явно задокументировать.

Низкоприоритетные L — устранить или явно задокументировать до следующего ревью.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — повторный аудит

- **Коммит:** `4542311` (заявлено pytest 7849/0)
- **Учтено:** поверх влит F4 `7eb7c69` (`feat(services,web,tests): … лента досье`) — его правки/тесты F11 **не приписываются**.
- **Ревьюер:** @Reviewer
- **Артефакты:** diff `4542311^..4542311`, файлы F11 на состоянии коммита; независимый JS-харнесс на реальном `web/app.js`.
- **Верификация:** временный `git stash` чужих WIP-правок → полный `pytest` на **чистом** `4542311`; `node --check`; целевой JS-тест; `vue_mount_test.js`. Рабочее дерево восстановлено (stash `pop` не удался из-за CRLF — WIP возвращён через `git checkout stash@{0} -- <8 файлов>` + `git stash drop`; diff вернулся к исходным `8 files, 285+/30-`).

## Статус

**Changes Requested**

Итог: Medium и Low итерации 1 закрыты по существу (kill-switch во фронте, контракт `saveProviderSecret(key,value,{scope})`, caplog/reload/разметка, `global_secret_keys()`, placeholder), R17/R18 чисты, инварианты целы, полный pytest на чистом коммите — **7849 passed, 0 failed** (заявленное подтверждено). Но сам фикс High (паритет прав) **содержит ошибку**: `canEditConfig` вызывает computed-свойство `isGlobalAdmin` как функцию (`this.isGlobalAdmin()`). Для пользователя, у которого `isGlobalAdmin === true`, но `permissions.wildcard` ложно (ветка `role_name === 'admin'`), вызов бросает `TypeError: this.isGlobalAdmin is not a function` **прямо в рендере карточки** (`:disabled`/`v-if`), а JS-тест это маскирует, подменяя `isGlobalAdmin` методом. Плюс паритет остаётся неполным в другую сторону: фронтовый `isGlobalAdmin` (`role_name==='admin' || wildcard`) ≠ бэкендовый `is_global_admin` (`role_type==global_admin || wildcard`). Нужна точечная правка.

## Проверка закрытия findings итерации 1

| Finding | Статус | Доказательство |
|---|---|---|
| H — паритет прав UI↔бэкенд | ❌ **не закрыт** | `canEditConfig` (`web/app.js:4452-4454`) бросает `TypeError` для части админов; тест маскирует (H1 ниже) |
| M2 — kill-switch во фронте | ✅ | `web/app.js:2391-2400` (`uiFlag('BYOK_IMAGE_KEY_ENABLED')`); JS-тест кейс 6 (`round1024_image_key_test.js:265-280`) — OFF → `POST /api/config`, 0 вызовов safe |
| M3 — caplog/reload/разметка | ✅ | `test_logs_never_contain_raw` (caplog, sentinel без узнаваемых префиксов — не тавтологичен), `test_reload_shows_configured_mask` (`{configured:true,last4}`), `TestIndexMarkup` |
| M4 — контракт `saveProviderSecret(key,value,{scope})` | ✅ | `web/app.js:2381-2407`; per-chat `keys.llm_api_key` + `scope:'chat'` → PUT без `global`; JS-тест кейс 7 (`:283-298`) |
| Low 5 — `global_secret_keys()` пуст при OFF | ✅ | `services/chat_keys.py:63-71`; `web/api/routes.py:664` переведён на хелпер; тест `:228` |
| Low 6 — placeholder при `configured:false` | ✅ | `web/app.js:3557-3564` → `f.label` |

Новых утечек R17 не найдено: `routes.py:707-708,769-770` логируют только `key_name/by/removed`, audit (`services/chat_keys.py:168-186`) пишет `'***'`/`''`, ответы — `mask_key_info`. `caplog`-тест осмыслен (sentinel `log-sentinel-raw-987654` не маскируется штатным санитайзером).

## Findings итерации 2

### [High] `canEditConfig` вызывает computed `isGlobalAdmin` как функцию → `TypeError` в рендере

- **Файл:** `web/app.js:4452-4454` (`return !!(this.isGlobalAdmin && this.isGlobalAdmin());`).
- **Контекст:** `isGlobalAdmin` — **computed**, а не метод: `web/app.js:1296-1299` (внутри блока `computed`, рядом `permissions`/`tokenFlowTree`), и во всём коде используется как значение (`web/app.js:4071` `if (this.isGlobalAdmin) return true;`, `:6842`, `:7049` и др.). Значит `this.isGlobalAdmin` — boolean, и `this.isGlobalAdmin()` — вызов boolean.
- **Проблема:** при `p.wildcard === false` (ранний `return true` на `:4445` не срабатывает) и `this.isGlobalAdmin === true` (ветка `role_name === 'admin'`) выполняется `true()` → `TypeError: this.isGlobalAdmin is not a function`. Вызов происходит **во время рендера**: `web/index.html:302` `:disabled="!canEditConfig(f.key) …"` и новый `v-if="f.globalSecret && !canEditConfig(f.key)"` — падение рендера блока «Генерация изображений».
- **Независимое подтверждение:** харнесс, загружающий реальный `web/app.js` и вызывающий `methods.canEditConfig` с `isGlobalAdmin` как boolean (как в рантайме/в остальных JS-тестах):
  - `{sections:['keys']}, isGlobalAdmin=false` → `false` (ок);
  - `{sections:['keys']}, isGlobalAdmin=true` → **`THROWS: TypeError: this.isGlobalAdmin is not a function`**.
  Достижимость: роль `admin` без `wildcard` возможна (снять wildcard у `admin` разрешено, если есть другая wildcard-роль; имя роли правится в UI ролей).
- **Маскировка тестом (тавтологичность):** `tests/js/round1024_image_key_test.js:306` объявляет `isGlobalAdmin() { return isGlobal; }` — **метод**, т.е. тест кодирует несуществующий контракт. Остальные JS-тесты используют `isGlobalAdmin` как **boolean** (`round1020_ui_test.js:152`, `round1023_verbilizer_tabs_test.js:195,232,242`) — новый тест выбивается из модели и потому зелёный при сломанном коде.
- **Required fix:** заменить на `return !!this.isGlobalAdmin;`. Тест переписать на boolean-модель: `editCtx({sections:['keys']}, /*isGlobalAdmin=*/true)` со свойством `isGlobalAdmin: true` (не методом) и ассертом «не бросает, возвращает true/false по правилу». Дополнительно проверить, что `canEditConfig` вызывается без исключений для всех четырёх комбинаций `wildcard × isGlobalAdmin`.

### [Medium] Паритет неполный в обратную сторону: `role_type == global_admin` на фронте не виден

- **Файлы:** `web/app.js:1296-1299` (`isGlobalAdmin` = `role_name==='admin' || permissions.wildcard`) против `services/roles.py:165` (`is_global_admin = role_type==global_admin || perms.wildcard`) и `web/api/routes.py:690-694` (safe-эндпоинт проверяет `access_for().is_global_admin`); `/api/me` (`web/api/routes.py:329-339`) не отдаёт `role_type`/эффективный `is_global_admin`.
- **Проблема:** кастомная роль с `role_type='global_admin'` и без `wildcard`: backend `PUT keys/own scope=global` → **200**, а фронт `isGlobalAdmin === false` → поле `disabled` + подсказка «только глобальный администратор». UI запрещает то, что бэкенд разрешает — тот же класс рассинхрона, что был в итерации 1, только зеркально.
- **Почему это важно:** «паритет» заявлен как закрытие High; фактически сравниваются два разных определения «глобального админа», поэтому одна из сторон всё равно расходится.
- **Required fix:** согласовать источник истины. Предпочтительно — аддитивно (R16) отдать в `/api/me` эффективный `is_global_admin` (из `access_for`) и гейтить поле по нему; либо явно синхронизировать оба определения (`role_type`/`role_name`/`wildcard`) и закрепить тестом на роль `role_type=global_admin` без wildcard.

### [Low] «Разметочные» тесты — только проверка подстрок

- **Файл:** `tests/test_byok_image_key_round1024.py` (`TestIndexMarkup`).
- **Проблема:** проверяется наличие `"Ключ установлен"` и `"f.globalSecret && blockFieldConfigured(f)"` в HTML — не поведение. Для CSP/static-разметки приемлемо, но регресс логики `v-if` не поймает.
- **Required fix:** достаточно как есть; при желании — сверять, что оба бейджа взаимоисключающие (`globalSecret` vs `!globalSecret`).

## Контракт / инварианты

| Пункт | Статус |
|---|---|
| Backend safe-ветка (`scope`, RBAC 403, 422, 503, маска, audit) | ✅ не менялась (кроме `global_secret_keys()`), тесты `TestGlobalPut`/`TestGlobalDelete`/`TestRbacParity` |
| `GET /api/config` без raw; `keys-секция` не видит глобальный ключ | ✅ `web/api/routes.py:425`; тест `test_keys_section_role_sees_no_global_key_in_config` |
| R17 (ответы/логи/аудит без raw) | ✅ `caplog`-тест + код-инспекция |
| R18 (секретов в diff нет) | ✅ только фейковые значения |
| R16 (аддитивность `ui_flags`) | ✅ ключ `BYOK_IMAGE_KEY_ENABLED` (`web/api/routes.py:357`) |
| egress / `parse_mode=None` | ✅ не затронуты |
| Δ DDL = 0 | ✅ `services/pg_db.py` в diff нет (`chat_lore_history.field` уже допускает `chat_keys`) |
| Δ каталога = 0 | ✅ `services/param_catalog.py` в diff нет; флаг env-only `ClassVar` |
| F12 probe-save не сломан | ✅ `testBlock`/`probeEndpoint` не тронуты |
| Паритет прав UI↔бэкенд | ❌ **H1 + M1** |
| Kill-switch (backend + frontend) | ✅ `/api/me` + `uiFlag` + JS-тест OFF |

## Тесты / прогон

- Целевой: `tests/test_byok_image_key_round1024.py` → **26 passed** (было 19; +H-паритет, +caplog, +reload, +2 разметка).
- JS: `round1024_image_key_test.js` → `IMAGE-KEY-OK`; `vue_mount_test.js` → `VUE-MOUNT-OK`; `node --check web/app.js` → OK.
- Полный `pytest` на **чистом** `4542311` (чужие WIP во временном stash): **7849 passed, 0 failed, 1 warning** — заявленное число подтверждено.
- Замечание по грязному дереву: с WIP-правками F4/соседей (не относятся к F11) полный прогон даёт 2 падения порядка (`test_dossier_feed_round1024.py::test_api_nfkc_name_match`, `test_betterstack_handler.py::TestNoRedirect…`), изолированно оба зелёные. К F11 не относится, но дерево перед деплоем должно быть чистым.

## Точный список правок (блокеры итерации 2)

1. **H1:** `web/app.js:4453` — `this.isGlobalAdmin()` → `!!this.isGlobalAdmin` (computed нельзя вызывать). Переписать `tests/js/round1024_image_key_test.js:300-320` на boolean-модель `isGlobalAdmin` и добавить кейс «`wildcard:false, isGlobalAdmin:true` не бросает».
2. **M1:** согласовать определение «глобального админа» фронт↔бэкенд: отдать в `/api/me` эффективный `is_global_admin` (или учесть `role_type`) и гейтить поле по нему; тест на `role_type=global_admin` без wildcard.
3. **L:** при желании — усилить разметочные ассерты (взаимоисключение бейджей).

После правки H1/M1 фича будет готова к `Approved`.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 3 — финальный аудит

- **Коммит:** `59f7900` (заявлено pytest 7857/0)
- **Учтено:** поверх влиты F4-фиксы `e4c4e89`/`fea70ae` — их правки/тесты F11 **не приписываются**.
- **Ревьюер:** @Reviewer
- **Артефакты:** diff `59f7900^..59f7900`; независимый JS-харнесс на реальном `web/app.js` (проверка computed как значения + паритета); полный `pytest`.
- **Верификация:** `git diff --check` чисто; рабочее дерево чистое по tracked-файлам F11 (остаточный WIP — только `plans/backlog.md`, к F11 не относится).

## Статус

**Approved**

H1 (computed как метод → `TypeError` в рендере) и M1 (паритет «глобального админа» UI↔бэкенд) закрыты по существу; тесты переписаны на верную boolean-модель и не тавтологичны; R17/R18 и инварианты целы; полный pytest на коммите — **7857 passed, 0 failed**; `node --check`/JS-гейты зелёные.

## Проверка закрытия findings итерации 2

### H1 — закрыт ✅

- `web/app.js:4467` — вместо `this.isGlobalAdmin()` теперь `return !!this.isGlobalAdminEffective;` (computed как **значение**).
- `web/app.js:1307-1312` — `isGlobalAdminEffective` объявлен в `computed`, фолбэк `!!this.isGlobalAdmin` (тоже значение).
- Независимый харнесс на реальном `web/app.js` (ctx c `isGlobalAdminEffective` как значением, как в рантайме):
  - `{sections:['keys']}, effective=false` → `false`;
  - `{sections:['keys']}, effective=true` (admin без wildcard) → `true`, **без `TypeError`**;
  - `{wildcard:true}, effective=false` → `true` (ранний return).
- Тест `tests/js/round1024_image_key_test.js:300-336` переписан: ctx даёт `isGlobalAdminEffective`/`isGlobalAdmin` **значениями**, добавлен `assert.doesNotThrow` на регресс `admin`/`wildcard:false`. Т.е. тест больше не подменяет computed методом — тавтологичность устранена.

### M1 — закрыт ✅

- `web/api/routes.py:329-345` — `GET /api/me` аддитивно (R16) отдаёт `is_global_admin` из `roles_srv.access_for(user.id, cache=cache)` — **тот же** источник, что RBAC safe-эндпоинта (`routes.py:702`).
- `web/app.js:1307-1313` — `isGlobalAdminEffective` предпочитает серверный флаг, фолбэк — legacy `isGlobalAdmin` (старый сервер/стенд). Проверено харнессом: серверный `false` приоритетнее `role_name='admin'`; custom `role_type=global_admin` → `true`; без поля — legacy.
- Паритет теперь точный: `canEditConfig('keys.image_api_key')` = `!!access_for(...).is_global_admin` = условие эндпоинта.
- Тесты: `test_admin_role_without_wildcard_is_global` (legacy `admin` без wildcard: `/api/me`=true + PUT 200), `test_custom_global_admin_role_allowed` (`role_type=global_admin` без wildcard: `/api/me`=true + PUT 200), `test_keys_editor_me_flag_false` (keys-секция: false). Бэкенд `_role_type_of` (`services/roles.py:72-73`) действительно маппит legacy `admin` → `global_admin`.

Остаточный Low итерации 2 (усиление разметочных ассертов) — не блокирующий, можно отложить.

## Findings итерации 3

Блокирующих нет.

- **[Info]** При первом прогоне полного `pytest` зафиксирован единичный transient-таймаут (`pytest-timeout`), при повторном прогоне — **7857 passed, 0 failed** чисто; к коду F11 не воспроизводится (окружение/заказ тестов). Дерево перед деплоем держать чистым.

## Контракт / инварианты

| Пункт | Статус |
|---|---|
| `canEditConfig` global-секрета = RBAC эндпоинта (паритет) | ✅ `web/app.js:4467` ↔ `web/api/routes.py:702` |
| `/api/me.is_global_admin` (аддитивно, bool, единый источник) | ✅ `web/api/routes.py:345`; тесты API |
| Kill-switch `BYOK_IMAGE_KEY_ENABLED` (backend+frontend) | ✅ без изменений, JS-кейс 6 |
| Safe-эндпоинт: 403/422/503/маска/audit | ✅ тесты `TestGlobalPut`/`TestGlobalDelete`/`TestRbacParity` |
| R17 (ответы/логи/аудит без raw) | ✅ `caplog`-тест + инспекция; `/api/me` — только bool |
| R18 (секретов в diff нет) | ✅ только фейковые значения |
| R16 (аддитивность) | ✅ новое поле `is_global_admin`, ключ `ui_flags` не тронут |
| egress / `parse_mode=None` | ✅ diff не касается |
| Δ DDL = 0 | ✅ `services/pg_db.py` в diff нет |
| Δ каталога = 0 | ✅ `services/param_catalog.py` в diff нет |
| F12 probe-save не сломан | ✅ `testBlock`/`probeEndpoint` не тронуты; полный pytest зелёный |

## Тесты / прогон

- Целевой: `tests/test_byok_image_key_round1024.py` → **29 passed** (было 26; +3 API-паритет).
- JS: `round1024_image_key_test.js` → `IMAGE-KEY-OK` (кейсы 8/9 — computed-as-value + источник истины); `vue_mount_test.js` → `VUE-MOUNT-OK`; `node --check web/app.js` → OK.
- Полный `pytest`: **7857 passed, 0 failed, 1 warning** — заявленное подтверждено.
- `git diff --check 59f7900^ 59f7900` — чисто.

**Вывод:** F11 `byok-image-key-round1024` — **Approved**. Можно двигаться дальше.
