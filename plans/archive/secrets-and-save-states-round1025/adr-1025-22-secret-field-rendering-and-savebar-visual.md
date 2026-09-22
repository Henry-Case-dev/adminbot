# ADR-1025-22 — Секрет-поле: маска как display-индикатор (не значение `input`) + визуальный добор SaveBar

- **ID:** ADR-1025-22
- **Статус:** **Accepted** (Step 2 @Architect, 23.09.2026)
- **Фича:** `secrets-and-save-states-round1025` (F9, Эпик 1). **Спека:** `plans/features/secrets-and-save-states-round1025/spec.md`.
- **Контекст:** §50, §51, §69, §78 `plans/current_task.md`. Baseline HEAD `93432c0`, `APP_VERSION` 2.58.15. Зависит от F0 (§52), F4 (§60), F5 (§61).
- **Связанные:** ADR-1025-2 (F0 write-path/state-machine/409), ADR-1025-4 (F0 toasts/SaveBar), ADR-1025-9/-18 (токены/glass/safe-area), ADR-1025-14/-15 (store/workspace), ADR-1025-20 (PERMsoc-гейты), ADR-1016-2 (CSP/zero-build), UPD3/R31 (`SECRET_MASK`/`hasSecretMask`).

## Контекст и проблема
Текущая модель (UPD3/R31, `web/app.js:4748`) **засеивает строку маски `SECRET_MASK` в `keyDrafts`/`blockDrafts`/`blockFieldValue`**, а guard'ы `isSecretMask`/`hasSecretMask` не дают ей сохраниться. Это защищает от порчи ключа, но формально **маска является значением `input`**, что запрещено §50 («Не использовать строку маски как настоящее значение input») и конфликтует с R17. Нужна модель, где маска — **display-индикатор**, а поле ввода всегда пустое, при сохранении guard'ов. Дополнительно §69/§78 требуют добора визуальной части SaveBar (клавиатура, safe-area, последнее поле, одно уведомление) без переписывания движка F0.

## Решения (D1–D7)

### D1 — Маска как display-индикатор; поле ввода пустое (Accepted)
- Вводится helper `secretDisplay(item|key) → {configured, maskText}`: `last4` → `'••••••••'+last4`; configured без last4 → «Ключ установлен»; иначе «Не настроен».
- **Отказ от засева маски в значение:** `_seedSecretMasks` (`app.js:4748`) больше не пишет `SECRET_MASK` в `keyDrafts`; `blockFieldValue` для configured-секрета возвращает `''`. Индикатор несёт признак «настроен».
- **Guard'ы сохраняются** (`SECRET_MASK`, `isSecretMask`, `hasSecretMask`, `SECRET_MASK_HINT`; call-sites `dirtyKeyItems:2800`, `saveKeyItem:7853`, `saveBlock:5964`, `testBlock:5898`, `testField:5930`) — defense-in-depth против вставки/композита/legacy.
- **Альтернативы:** (a) readonly-элемент с маской как `value` — отклонено (значение в DOM/возможно в POST); (b) placeholder вместо индикатора — отклонено (placeholder исчезает при вводе, слабый сигнал «настроен»); (c) сохранить засев — отклонено (§50/R17).
- **Следствия:** untouched → draft пуст → не dirty → секрет прежний; replace → новый ключ → reload → новая маска; маска в API не уходит. Поведение `testBlock`/`saveBlock` сохранено (пустой draft ⇒ `api_key` не шлётся, как и sentinel).

### D2 — Удаление глобального секрета через существующие поверхности (Accepted)
- `isGlobalSecretKey(key) && uiFlag('BYOK_IMAGE_KEY_ENABLED')` → `DELETE /api/config/keys/own/{key}` (существующая глобальная ветка + аудит).
- Иначе → F0 write-path empty-write: `persistItems([{key, value:'', per_chat:false}], {operationId})` (global `POST /api/config`; `CATEGORY_KEYS` global разрешён через `can_view_key_value`, `routes.py:974-977`). Пусто = «не настроен».
- **Отклонено:** новый endpoint (R16); `DELETE /api/config/chat/{key}` (сброс override, не удаление).
- **Следствия:** один write-path (F0), аудит image-ключа сохранён, `BYOK_IMAGE_KEY_ENABLED` уважается.

### D3 — «Ключ установлен» (fallback без last4) (Accepted)
Источник — `configItems[].value={configured,last4}` (global) и `keyStatusOwn` (chat). Без value-возвращающих вызовов (R17). Новых status-API нет.

### D4 — Единый компонент `secret-field` для всех секретов (Accepted)
Один Vue-компонент (регистрация как `sticky-save`/`kv-editor`) заменяет разрозненные шаблоны (`index.html:490-545`, `:700-785`, `:1185-1200`, `:1436-1455`, `:1551-1560`, `:1593-1630`, `:1836-1849`). BYOK — `scope='chat'` с сохранением UX. Классификация 28: 20 `category=keys` (UI) + 8 env-only infra (вне UI, безопасность). **Δ каталога=0** (новых Spec нет).

### D5 — SaveBar: только добор поверх F0 (Accepted)
Движок F0 не переписывается. Добор: клавиатура через `visualViewport` (`_onVV`, `app.js:3074-3082`) → keyboard-offset + `scrollIntoView({block:'nearest'})`; safe-area ровно один раз (§64 D3); `scroll-padding-bottom`/`.sticky-spacer` + `scroll-margin-bottom`; одно уведомление/«Подробнее» reuse. SaveBar остаётся в `footer.modal-actions` вне `.modal-body` (§64).

### D6 — §51: только отображение (Accepted)
Reuse `saveState` (`app.js:2810`) и обработок F0. «Сохранено» — только после подтверждения сервера. Серверная логика 409/412/state-machine — F0, не дублируется.

### D7 — Инварианты, bump, kill-switch (Accepted)
Δ DDL=0, Δ каталога=0, CSP/zero-build, R17-скан. **Bump 2.58.15 → 2.58.16** (web/** → cache-bust). **Kill-switch не вводится:** F9 UI-only, откат `git revert` + cache-bust; прецедент F4/F5 (ADR-1025-14 §D8); новых каталоговых флагов нет.

## AMEND / REUSE-карта
| Ранее | Действие | Причина |
|---|---|---|
| UPD3/R31 — засев `SECRET_MASK` в input | **AMEND (D1)** | маска → display-индикатор; guard'ы сохранены |
| ADR-1025-4 (F0 toasts/SaveBar) | **AMEND (добор, D5)** | клавиатура/последнее поле/safe-area без переписывания движка |
| ADR-1025-2 (F0 write-path/409/state-machine) | **REUSE, без изменений** | F9 — потребитель; empty-write/удаление через `persistItems` |
| ADR-1025-18 D3 (safe-area ровно один раз) | **REUSE** | keyboard-offset не складывается с safe-area |
| ADR-1025-14/-15 (store/workspace) | **REUSE** | секрет-поля в workspace используют компонент, store не меняется |
| ADR-1025-20 (PERMsoc-гейты), ADR-1016-2 (CSP) | **НЕ отменяются** | инварианты |

## Последствия / контракты
- **Затрагиваемые контракты:** `web/app.js` (маска/seed/helpers, `_onVV`), `web/index.html` (шаблоны → `secret-field`), `web/static/app.css` (`.secret-field*`, keyboard-offset), `config/settings.py` (`APP_VERSION`), `README.md`.
- **Сервер:** изменения только если ADR предпишет; по факту — **нет** (D2 reuse существующих endpoint/write-path). `web/api/routes.py` не меняется.
- **Риски:** R17-остаток при неполном переводе шаблонов (Critical) — покрыть все; регресс `testBlock`/`saveBlock` (High) — поведение сохранено; маркер-тесты UPD3/R31 (High) — атомарное обновление; двойной safe-area (High); BYOK (Medium); «28» env-only (Medium).
- **Проверяемость:** маска не в POST/PUT (тело запроса); change/save/delete; keyboard; safe-area; 28/28; Δ DDL/каталога=0; CSP.
