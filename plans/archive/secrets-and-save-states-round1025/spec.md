# F9 — `secrets-and-save-states-round1025` — SPEC (Step 2 @Architect, 23.09.2026)

> **ТЗ:** `plans/current_task.md` §50, §51, §69, §78 (файл не трогать/не коммитить). **Тип:** UI-слой секретов + визуальная часть Sticky SaveBar.
> **Зависит от:** F0 ✅, F4 ✅, F5 ✅ (ARCHIVED). **Baseline:** HEAD `93432c0`, `APP_VERSION` **2.58.15**, pytest 8403/0, JS 38, каталог 459/418/434/98/96/21, Δ DDL=0.
> **Границы:** persistence / 409 / 412 / state-machine / merge / версия — **F0 (§52), НЕ дублируем**; F9 читает `persistItems` (`web/app.js:7571-7737`), `notify`/`toast` (:7518/:3385), `saveState` (:2810). **ADR:** `adr-1025-22-secret-field-rendering-and-savebar-visual.md` (Accepted).
> **Инварианты:** **Δ DDL=0**, **Δ каталога=0** (28 секретов — UI, не новые Spec), CSP/zero-build (ADR-1016-2/1024-13), **R17** (raw секрет и строка маски — не в значение input / браузер / POST / лог / отчёт; наружу только `{configured,last4}`), **R18**.

## 1. Scope

**В scope:** единый рендер секрет-поля (§50) с маской как **display-индикатором**, а не значением `input`; отдельные действия «Заменить»/«Удалить» для глобальных секретов; прогон всех секретов каталога; визуальный добор Sticky SaveBar (§69/§78: клавиатура, safe-area, последнее поле, одно уведомление/«Подробнее»); UI-отображение состояний `saveState` (§51) и понятных сообщений 409/412; тесты §78; инварианты/маркеры/bump.

**Вне scope (F0 §52):** серверный persistence, контракт 409/412, единая state-machine, безопасное слияние, контроль версии. F9 — **потребитель**, не дублирует. **Вне scope:** реальная TMA/WebView-приёмка (live-гейт владельца, post-deploy — PENDING, не заявлять пройденной).

## 2. Трассируемость REQ → §ТЗ → ADR

| REQ | §ТЗ | Решение ADR-1025-22 |
|---|---|---|
| REQ-F9-01/02/03 (маска/last4/«Ключ установлен», маска ≠ value) | §50, R17 | D1, D3 |
| REQ-F9-04 (замена/удаление — отдельные; пусто не удаляет) | §50 | D2, D4 |
| REQ-F9-05 (сохранение несекретных не трогает секрет) | §50 | D1 |
| REQ-F9-06 (все 28) | §50 | D4 |
| REQ-F9-07/08 (409/412 UI, состояния, «Сохранено» после сервера) | §51, §69 | D6 |
| REQ-F9-09/10 (SaveBar: safe area/клавиатура/последнее поле/одно уведомление) | §69 | D5 |
| REQ-F9-11 (тесты §78) | §78 | D7 |

## 3. Поведение и контракты

### 3.1. Рендер секрет-поля (D1/D3)
- **Display ≠ value.** Для каждого секрет-поля: отдельный display-индикатор `secretDisplay(item|key)` → `{configured, maskText}`:
  - `last4` непустой → `'••••••••' + last4` (например `••••••••a7F2`);
  - `configured` без `last4` → **«Ключ установлен»** (fallback, D3);
  - иначе → «Не настроен».
- **Поле ввода всегда пустое** для configured-секрета: `keyDrafts[item.key]`/`blockDrafts[f.key]`/`blockFieldValue(f)` **не засеиваются** маской (отказ от `_seedSecretMasks`-засева; `web/app.js:4748`). Placeholder: `«Новый ключ (заменить)…»` / `«Ключ…»`.
- **Guard'ы сохраняются без изменений** (defense-in-depth, R17): `SECRET_MASK`/`isSecretMask`/`hasSecretMask` (:17-30), `SECRET_MASK_HINT`, call-sites `dirtyKeyItems:2800`, `saveKeyItem:7853`, `saveBlock:5964`, `testBlock:5898`, `testField:5930`. Предикат `hasSecretMask` защищает от вставки/композита даже при новой модели.
- **Источник статуса:** `configItems[].value={configured,last4}` (global) и `keyStatusOwn` (chat BYOK). Значение-возвращающих путей не вызываем (R17).

### 3.2. Жизненный цикл секрета
| Сценарий | Поведение |
|---|---|
| Не трогали | draft пуст → `dirtyKeyItems` не включает → **не перезаписывается**; старый секрет прежний |
| Заменили (ввели новый) | draft = реальный ключ → `saveKeyItem`/`saveProviderSecret` (safe-path) → после ответа сервера reload → **новая маска** |
| Пустое новое поле | `saveKeyItem` guard `!value` → не сохраняется/не удаляет; «Введите новый ключ» |
| Вставили строку маски | `hasSecretMask` → отказ + `SECRET_MASK_HINT`; в API не уходит |
| Удаление | отдельное подтверждаемое действие (D2) |
| Сохранение несекретных | секрет вне `dirtyItems` (category=keys/secret) → прежний |

### 3.3. Удаление глобального секрета (D2)
Без нового endpoint (R16):
- `isGlobalSecretKey(key) && uiFlag('BYOK_IMAGE_KEY_ENABLED')` → существующий `DELETE /api/config/keys/own/{key}` (глобальная ветка, аудит `record_global_secret_audit`).
- Иначе → F0 write-path empty-write: `persistItems([{key, value:'', per_chat:false}], {operationId})` → global `POST /api/config` (сервер допускает `CATEGORY_KEYS` global через `can_view_key_value`, `routes.py:974-977`). Пустая строка = «не настроен» (`_mask_secret` → `{configured:false}`).
- **Не использовать** `DELETE /api/config/chat/{key}` (это сброс override, не удаление секрета).
- UI: «Удалить» — отдельная кнопка с `window.confirm` (паритет BYOK `deleteOwnKey:3761`); «Заменить» = ввод + SaveBar.

### 3.4. Единый компонент для 28 секретов (D4)
- Vue-компонент `secret-field` (регистрация как `sticky-save`/`kv-editor`), props: `title/techKey/description/configured/last4/draftKey/scope/disabled`, emits/callbacks `replace/delete`. Рендер: заголовок → тех.ключ → описание → индикатор маски → пустой password-инпут + reveal → «Заменить»/«Удалить».
- Перевод разрозненных шаблонов `web/index.html`: generic-секции (`:1436-1455`, `:1551-1560`, `:1836-1849`), provider-блоки (`:490-545`, `:700-785`, `:1185-1200`), BYOK (`:1593-1630`). BYOK — `scope='chat'` (сохранить `ownKeyDraft`, «Использовать мой», `keyStatusOwn`, статус «использовать глобальный»).
- **Классификация 28** (проверено): 20 `category=keys` (группы `keys_llm/search/groq/openrouter/betterstack/youtube/media/images`, включая `IMAGE_API_KEY`→`keys.image_api_key`) — UI-редактируемые; 8 env-only infra (`API_TOKEN`, `POSTGRES_DSN`, `POSTGRES_PASSWORD`, `SENTRY_DSN`, `LOGTAIL_SOURCE_TOKEN`, `TELEGRAM_API_ID/HASH`, `COBALT_HTTP_PROXY`, `category=None`) — **осознанно вне UI** (безопасность). Чек-лист (T-3034) отмечает их «env-only (вне UI)», **не** «без экрана».
- CSS: `.secret-field`, `.secret-field__mask`, `.secret-field__actions` в `web/static/app.css`; существующие `.field`/badge. Zero-build, без библиотек.

### 3.5. SaveBar §69/§78 — только добор (D5)
Движок F0 (`persistItems`/`notify`/`toast`/`saveState`/`sticky-save:11226-11277`) **не переписывается**:
- **Клавиатура:** расширить `_onVV` (`app.js:3074-3082`; сейчас только фон/сердцебиение): при изменении `visualViewport` и фокусе внутри `.modal-body`/scroll-area — CSS-переменная offset клавиатуры (`innerHeight - (vv.height + vv.offsetTop)`) на `.modal-actions`/`.sticky-save` + `scrollIntoView({block:'nearest'})` для фокус-поля. **Safe-area ровно один раз** (§64 D3): `max(env(safe-area-inset-bottom), var(--tg-*))` + отдельный keyboard-offset; без двойного вычета.
- **Последнее поле:** сохранить `scroll-padding-bottom`/`.sticky-spacer` (`app.css:1585,1606-1618`); добавить `scroll-margin-bottom` полям; проверка высот 600–700 CSS px.
- **Одно уведомление + «Подробнее»:** reuse F0 (`notify` дедуп по `operationId`, очередь ≤3; длинная ошибка → `.toast-more`/«Подробнее», `index.html:4515`). F9 проверяет отсутствие дублей в секрет-потоках (silent-пути).
- **§64-граница:** SaveBar остаётся в `footer.modal-actions` **вне** `.modal-body` (`position:static` в footer, `app.css:1559-1597`) — не переносить внутрь.

### 3.6. Состояния и 409/412 (D6)
- Reuse computed `saveState` (`app.js:2810`: `loading|saving|error|conflict|dirty|clean`) и обработки F0. F9 — только отображение (`data-save-state`, `stateLabel`, per-field `stickyFailedKeys`), без серверной логики.
- «Сохранено» — **только после подтверждения сервера** (F0 baseline сдвигается лишь при полном успехе). При 409/412 — понятный текст, без «успеха» и без молчаливой перезаписи.

## 4. Нефункциональные / инварианты (D7)
- **Δ DDL=0**, **Δ каталога=0** (`services/param_catalog.py` не трогается; новых ParamSpec/групп нет), **CSP/zero-build** (нет новых библиотек/CDN/inline/WebGL), **R17**-скан артефактов, **R18**.
- **Bump `APP_VERSION` 2.58.15 → 2.58.16** (`config/settings.py:1748`) + `README.md` + cache-bust `?v=__APP_VERSION__` (меняются `web/**`).
- **Kill-switch: не нужен.** F9 UI-only, обратим `git revert` + cache-bust; прецедент F4/F5 (ADR-1025-14 §D8); новых каталоговых флагов нет. Существующий `BYOK_IMAGE_KEY_ENABLED` уважается (D2).

## 5. Приёмка (сценарии)
1. Configured-секрет → виден индикатор `••••••••last4` или «Ключ установлен»; **value `input` пуст**; маска отсутствует в POST/PUT (проверка тела запроса).
2. Ввод нового ключа → сохранение → новая маска. Пустое поле → старый секрет цел. Вставка маски → отказ, в API не уходит.
3. «Удалить» → confirm → секрет «не настроен» (D2-путь по типу ключа).
4. SaveBar: клавиатура не перекрывает поле/SaveBar; последнее поле докатывается и нажимаемо; safe-area один раз; одно уведомление; длинная ошибка за «Подробнее».
5. Состояния `saveState` отображаются; «Сохранено» — после сервера; 409/412 — понятный текст.
6. 28/28 секретов: чек-лист «параметр → экран → поведение»; 20 UI + 8 env-only (вне UI, осознанно); «без экрана»=0 в смысле отсутствующих UI-полей.

## 6. Тесты / деплой / откат
- **Тесты (§78):** маска не уходит в API; смена/сохранение/удаление; клавиатура (`visualViewport`); safe area; 28/28; Δ DDL=0/Δ каталога=0; CSP.
- **Атомарно** обновить маркер-тесты UPD3/R31, если они ассерят засев маски в `keyDrafts` (red→green, без тихого ослабления).
- **Деплой:** bump, рестарт, `?v=`, `/api/health`, `database is locked`=0. **Live-гейт (реальная TMA/WebView)** — PENDING OWNER VERIFICATION, если доступа нет (не заявлять пройденным).
- **Откат:** `git revert` + cache-bust; точка `pre-round1025-f9` (T-3024).

## 7. Риски
- **Critical (R17):** остаточный засев маски в input/POST при неполном переводе шаблонов → покрыть все 9 шаблонов, сохранить guard'ы, R17-скан.
- **High:** регресс `testBlock`/`saveBlock` «Проверить без ввода» при смене `blockFieldValue` → поведение сохранено (пустой draft → api_key не шлётся); тест.
- **High:** маркер-тесты UPD3/R31, ассертящие seeded mask → атомарное обновление.
- **High:** двойной вычет safe-area (§64) при keyboard-логике → единый источник.
- **Medium:** регресс BYOK при конвертации → `scope='chat'`-паритет + тест.
- **Medium:** неоднозначность «28» (8 env-only) → классификация в чек-листе, подтверждение @Reviewer/@Scanner.
