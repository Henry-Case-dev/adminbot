# F9 — `secrets-and-save-states-round1025` — evidence (Step 4 @Builder, 23.09.2026)

> **Spec:** `spec.md` (Step 2). **ADR:** `adr-1025-22-secret-field-rendering-and-savebar-visual.md` (Accepted).
> **Baseline:** HEAD `93432c0`, `APP_VERSION` **2.58.15**, pytest **8403/0**, JS **38**, каталог 459/418/434/98/96/21, Δ DDL=0.
> **Kill-switch не вводится** (UI-only, откат `git revert` + cache-bust, прецедент F4/F5).

## Блоки A–F (реализовано)

| Блок | Задачи | Что сделано |
|---|---|---|
| **A** §50 UI секретов | T-3028…T-3032 | D1: маска — display-индикатор (единый источник `secretDisplayOf` → метод `secretDisplay`; поле ввода пустое (`blockFieldValue` для секрета → `''`), `_seedSecretMasks` не засеивает маску (чистит legacy/композит). Guard'ы `isSecretMask`/`hasSecretMask`/`SECRET_MASK_HINT` сохранены. D2: `deleteKeyItem` (image+BYOK ON → `DELETE /api/config/keys/own/{key}` **с `global:true`**; иначе F0 empty-write `persistItems([{value:''}])`; `DELETE /api/config/chat/{key}` НЕ используется), confirm-гейт. D3: `secretDisplay` → `••••••••last4`/«Ключ установлен»/«Не настроен»; `byokSecret` из `keyStatusOwn`, `last4` больше не раскрывает строку. |
| **A** единый компонент | T-3032 | D4: Vue-компонент `secret-field` (регистрация `app.component`, `template: '#secret-field-tpl'`, zero-build) — 7 шаблонов `index.html` переведены (generic ×3, provider ×3, BYOK `scope='chat'`); мёртвый `keyReveal`/`toggleKeyReveal` удалён. CSS `.secret-field*`. Δ каталога=0. |
| **B** 28 секретов | T-3034/T-3035 | Чек-лист `plans/reports/round1025_f9_secrets_checklist.md`: **20 UI (`category=keys`) + 8 env-only (осознанно вне UI)**; «без экрана»=0. Пробелы закрыты компонентом (все UI-секреты на существующих экранах). |
| **C** SaveBar §69/§78 | T-3037…T-3040 | D5: `_syncKeyboardOffset` (visualViewport → `--kb-offset` = `innerHeight−(vv.height+vv.offsetTop)` + `scrollIntoView({block:'nearest'})`); `_onVV` расширен (+подписка на `visualViewport` scroll); safe-area ровно один раз (`.modal-actions` без env; `.sticky-save` один раз); `scroll-margin-bottom`/`scroll-padding-bottom`/`.sticky-spacer`; SaveBar остаётся в `footer.modal-actions` вне `.modal-body`. Одно уведомление/«Подробнее» — reuse F0 (движок не переписан). |
| **D** §51 состояния/409/412 | T-3043/T-3044 | D6: `stateLabel` дополнен (`loading`/`saved`); `data-save-state`; серверная логика (persistItems/409/state-machine) НЕ дублируется — F0-потребитель. |
| **E** тесты §78 | T-3046…T-3049 | Новые: `tests/js/round1025_f9_secret_field_test.js` (F9-SECRET-OK), `tests/js/round1025_f9_savebar_visual_test.js` (F9-SAVEBAR-OK), `tests/test_webapp_f9_round1025.py` (22 теста), регистрация в `tests/test_webapp_js_unit.py`. |
| **F** маркеры/R17/bump | T-3050/T-3051 | Δ DDL=0, Δ каталога=0 (459/418/98/96/21), CSP/zero-build; bump `APP_VERSION` **2.58.15 → 2.58.16** (`config/settings.py`, `README.md`, `?v=__APP_VERSION__`); R17-скан артефактов чист. |

## Изменённые/новые файлы

**Код/ассеты:** `web/app.js`, `web/index.html`, `web/static/app.css`.
**Bump:** `config/settings.py`, `README.md`.
**Отчёт:** `plans/reports/round1025_f9_secrets_checklist.md`.
**Тесты (новые):** `tests/js/round1025_f9_secret_field_test.js`, `tests/js/round1025_f9_savebar_visual_test.js`, `tests/test_webapp_f9_round1025.py`.
**Тесты (атомарные маркер-правки UPD3/R31 red→green):** `tests/js/round1020_ui_rework_test.js`, `round1020_ui_test.js`, `round1021_ui_audit_test.js`, `round1024_image_key_test.js`, `tests/test_byok_image_key_round1024.py`, `tests/test_webapp_round1011_ui.py`, `tests/test_webapp_round1020_ui.py`, `tests/test_webapp_round108_ui.py`, `tests/test_webapp_ui_rework_round1020.py`, `tests/test_webapp_js_unit.py`; **bump-версии:** hotfix6-10/f6/f7/design_tokens/scope_selector (py+pytest), hotfix7-10 (js). Fixture F8 `tests/fixtures/round1025/f8_baseline.json` **не менялся** — остаётся историческим baseline 2.58.15 (L-F9S-4).
**Планы:** `plans/features/secrets-and-save-states-round1025/tasks.md` (+`spec.md`/ADR — от @Architect).

## Прогоны (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Syntax | `node --check web/app.js` / `telegram-init.js` | OK |
| JS-тесты | `node tests/js/*.js` (все) | **40/40 OK** (38 baseline + 2 новых) |
| F9 pytest | `py -3 -m pytest tests/test_webapp_f9_round1025.py` | **22 passed** |
| Полный pytest | `py -3 -m pytest -q` | **8421 passed / 0 failed** (baseline 8403/0 → +18), `1 skipped`, **5 env-failed** (`rich`/`ImportError` fallback — воспроизводятся без F9, вне диффа) |
| Матрица §71 | `.venv\Scripts\python.exe tools\ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов; `pageerror`=0) |
| Bump-инвариант | grep `2.58.15` в тестах | только исторический fixture F8 (не бампнут сознательно) |
| git | `git diff --check` | exit 0 |
| R17-скан | regex по `git diff` (ключи/токены/DSN/маски) | **0 находок** |

**Live-гейт (реальная TMA/WebView):** PENDING OWNER VERIFICATION — доступа к живому Telegram WebView в этой сессии нет; Playwright-матрица локальная (успешна). Не заявлять пройденной.

## Fix-итерация (Step 5 @Builder, 23.09.2026) — H-F9S-1 + L-F9S-1..4

> Вход: @Reviewer `review.md` (Needs Fixes, 1 High) и @Scanner `round1025_f9_scanner_audit.md` (BLOCKED, H-F9S-1). Правки **не закоммичены**.

| ID | Правка | Файл |
|---|---|---|
| **H-F9S-1** | `deleteKeyItem` image-ветка: `DELETE /api/config/keys/own/{key}` теперь `{ method: 'DELETE', global: true }` (паритет с `saveProviderSecret`; иначе `api()` добавит `X-Chat-Id` → chat-ветка `delete_chat_key` → 422). Прочие ветки проверены: non-image → F0 `persistItems` (`per_chat:false` → global, I-F9S-1), legacy → POST `/api/config` уже с `global:true`. | `web/app.js` (`deleteKeyItem`) |
| **L-F9S-1** | Единый источник маски: компонент `maskText` делегирует в `secretDisplayOf({configured,last4}).maskText` (дубль форматирования устранён); мёртвый `blockSecretText` удалён; 2 теста переведены на `secretDisplay` (assert неизменён). `secretDisplay`/`secretDisplayOf` сохранены (маркер-тесты). | `web/app.js`, `tests/js/round1020_ui_rework_test.js`, `tests/js/round1024_image_key_test.js` |
| **L-F9S-2** | Недостижимый `stateLabel['saved']` удалён (root.saveState не отдаёт `saved`; «Сохранено» — тост F0). Тест обновлён: `saved`/`clean` → `''`, `saving` → «Сохранение…». | `web/app.js`, `tests/js/round1025_f9_savebar_visual_test.js` |
| **L-F9S-3** | Строгий контракт восстановлен: `FIXTURE["app_version"] == "2.58.15"` (исторический F8) **и** `APP_VERSION == "2.58.16"` (без `>=`). | `tests/test_round1025_f8_registry.py` |
| **L-F9S-4** | `f8_baseline.json` убран из списка bump; явно «не менялся — исторический baseline 2.58.15». | `evidence.md` |

### Прогоны после фикса (факт)

| Проверка | Команда | Результат |
|---|---|---|
| Syntax | `node --check web/app.js` | OK |
| JS-тесты | `node tests/js/*.js` (все, 40 файлов) | **40/40 OK** |
| Новый кейс H-F9S-1 | `node tests/js/round1025_f9_secret_field_test.js` | OK; **mutation-check:** со снятым `global:true` assert `calls[0].opts.global===true` падает (red), с фиксом — green |
| F9/F8/регресс pytest | `py -3 -m pytest tests/test_webapp_f9_round1025.py tests/test_round1025_f8_registry.py tests/test_webapp_round1020_ui.py tests/test_webapp_round1011_ui.py tests/test_byok_image_key_round1024.py` | **123 passed** |
| Полный pytest | `py -3 -m pytest -q` | **8421 passed / 5 failed / 1 skipped** (5 — env-only `rich`/`ImportError`: `outgoing_guard_round1022`/`summary_cover_round1023`, вне диффа) |
| `git diff --check` | — | exit 0 |
| R17-скан diff | regex (bot-token/`sk-`/`gsk_`/`ghp_`/Bearer/DSN/PRIVATE KEY/`api_key=`) | **0 находок** |
| Δ DDL=0 | `git diff HEAD -- services/ web/api/ migrations/ alembic/` | пусто |
| Δ каталога=0 | import `services.param_catalog` | **459 / 98 / 96 / 21**; Settings **418** |
| Playwright-матрица | `tools/ui_round1025_matrix.py` | **не запускалась** — `playwright` не установлен в текущей сессии (итер.1: `failures: 0`) |

**Статус фикса:** H-F9S-1 + L-F9S-1..4 — правки внесены; **ждут независимой перепроверки @Reviewer/@Scanner**. Вердикт к деплою не заявляется.


## Непроверенное / ограничения
- 5 env-падений pytest (`services.summary_generator` rich-fallback `ImportError`, `send_rich_message` rich-стаб) — пред-существующие, вне изменённых файлов F9 (services/** не тронут).
- Реальный TMA/WebView keyboard/safe-area — только Playwright-эмуляция (visualViewport отсутствует в Chromium-headless; поведение клавиатуры юнит-верифицируется напрямую на `_syncKeyboardOffset`).
- Δ DDL=0 (схема/миграции не трогались); Δ каталога=0 (`services/param_catalog.py` не изменялся).
