# F9 `secrets-and-save-states-round1025` — Scanner-аудит (Шаг 6, T-3055)

- **Дата:** 23.09.2026. **База:** HEAD `93432c0` (тег `pre-round1025-f9`), правки **НЕ закоммичены** — focused diff-based аудит рабочего дерева (32 M + 9 ??).
- **Вход:** `plans/current_task.md` §50/§51/§69/§78 (не трогался), `spec.md`, `adr-1025-22`, `evidence.md`, `review.md`, `round1025_f9_secrets_checklist.md`.
- **Вердикт (итер.2, финал): К ДЕПЛОЮ — ДА.** Critical 0 / High 0 / Medium 0 / Low 0 / Info 1. Все findings итер.1 (H-F9S-1 + L-F9S-1..4) **закрыты** и воспроизведены. Обязательных возвратов @Builder нет. Live-гейт TMA/WebView — PENDING OWNER.

## Таблица severity

| ID | Sev | Статус | Локация | Суть |
|---|---|---|---|---|
| H-F9S-1 | High | **RESOLVED** | `web/app.js:7978-7986` | image-ветка `deleteKeyItem` → `DELETE … {global:true}` (chat-scope не задействуется) |
| L-F9S-1 | Low | **RESOLVED** | `web/app.js:11464-11468` | единый источник маски: `maskText` → `secretDisplayOf`; мёртвый `blockSecretText` удалён |
| L-F9S-2 | Low | **RESOLVED** | `web/app.js:11398-11404` | недостижимая ветка `stateLabel['saved']` убрана; тест ждёт `''` |
| L-F9S-3 | Low | **RESOLVED** | `tests/test_round1025_f8_registry.py:102-107` | строгий контракт версии восстановлен (`APP_VERSION == "2.58.16"`) |
| L-F9S-4 | Low | **RESOLVED** | `evidence.md:25,53` | `f8_baseline.json` убран из списка bump, помечен историческим |
| I-F9S-1 | Info | — | `web/app.js:5935-5936` | осиротевший комментарий от удалённого `blockSecretText` (косметика) |
| I-F9S-2 | Info | PENDING OWNER | — | живой TMA/WebView keyboard/safe-area — вне headless |

## H-F9S-1 — закрытие (доказательство)

1. **Код:** `web/app.js:7978-7986` — image-ветка теперь `await this.api('/api/config/keys/own/' + encodeURIComponent(key), { method: 'DELETE', global: true });`. `api()` (`:3295`) при `options.global === true` **не** подставляет `X-Chat-Id` → сервер идёт в **глобальную** ветку `routes.py:814-833` (`is_global_secret` + `record_global_secret_audit`), chat-ветка `routes.py:834-847`/`delete_chat_key` не задействуется даже при выбранном чате.
2. **Паритет:** совпадает с существующим save-путём `saveProviderSecret` (`:3864`, `global:true`) и ADR-1025-22 D2.
3. **Регресс-гейт (новый):** `tests/js/round1025_f9_secret_field_test.js:236-239` — `assert.strictEqual(calls[0].opts.global, true, '… иначе chat-scope → 422')`. Прогон `node …` → `F9-SECRET-OK`.
4. **Прочие ветки проверены:** non-image → F0 empty-write через `persistItems` (`per_chat=false` → `global:true`, `app.js:7728`; тест `:197-218`); BYOK OFF → empty-write (тест `:242-257`); confirm=false → без запросов (тест `:259-271`); legacy-контекст → `POST /api/config {global:true}`; `DELETE /api/config/chat/{key}` не используется (статик-ассерт `test_webapp_f9_round1025.py:88`).

## L-F9S-1..4 — закрытие (доказательство)

- **L-F9S-1:** `secret-field.maskText` (`app.js:11464-11468`) делегирует в `secretDisplayOf({configured,last4}).maskText` — дубль форматирования устранён; `blockSecretText` удалён (ссылок в `web/`/`tests/` нет); 2 теста переведены на `secretDisplay` с неизменным assert. `secretDisplay`/`secretDisplayOf` сохранены (маркер-тесты).
- **L-F9S-2:** `stateLabel` (`app.js:11398-11404`) больше не содержит `saved`; тест `round1025_f9_savebar_visual_test.js:184-185` ждёт `''`. «Сохранено» по-прежнему доставляет тост F0 после подтверждения сервера.
- **L-F9S-3:** `test_round1025_f8_registry.py:106-107` — `FIXTURE["app_version"] == "2.58.15"` **и** `APP_VERSION == "2.58.16"` (строго, без `>=`). `2.58.15` в `tests/` остался только в историческом fixture.
- **L-F9S-4:** `evidence.md:25` — fixture явно «не менялся — исторический baseline 2.58.15 (L-F9S-4)»; `:53` — строка о закрытии.

## Проверенные инварианты ✔

- **R17:** сырых секретов нет в DOM/POST/логах/артефактах/тестах (regex-скан по диффу и новым файлам — 0). Поле ввода секрета **всегда пусто** (`_seedSecretMasks` только чистит legacy/композит; `blockFieldValue` секрет → `''`; шаблон `:value="draft"`). Guard'ы целы: `hasSecretMask` в `dirtyKeyItems`, `saveKeyItem`, `saveBlock`, `testBlock`, `testField`. Маска в API не уходит (JS-тест: 0 запросов).
- **R18:** тег `pre-round1025-f9` ✅, `.env.bak.round1025-f9` ✅, `stash@{0}` ✅.
- **Δ DDL=0:** `git diff HEAD -- services/ web/api/ migrations/ alembic/` пусто; новый endpoint не создан.
- **Δ каталога=0:** 459/98/96/21/418; `param_catalog.py` не тронут.
- **CSP/zero-build:** `secret-field` — x-template, без CDN/inline/`eval`.
- **`APP_VERSION` 2.58.16** синхронен (settings + README); `?v=__APP_VERSION__` сохранён.
- **XSS:** только `{{ }}`/`:attr`, без `v-html`/`innerHTML`.
- **Совместимость:** F0-движок не переписан (`persistItems`×1, `notify`×1); §52–§67/F1/F4/F5/F6/F7/F8/BYOK не сломаны (backend вне диффа); маркер-тесты не ослаблены (L-F9S-3 восстановлен).
- **Логика:** не трогали → не перезаписывается; заменили → новая маска; вставка маски → отказ; удаление — отдельная кнопка + `window.confirm`, не при пустом поле; safe-area ровно один раз.
- **Гигиена:** `git diff --check`=0; в индексе нет `.env`/`current_task.md`/zip/скриншотов/`tools/_ui_*`/`var/backups`.

## Прогоны @Scanner (независимо, итер.2)

- `node --check web/app.js` → exit 0.
- `tests/js/*.js` → **40/40 OK** (`F9-SECRET-OK`, `F9-SAVEBAR-OK`).
- `py -3 -m pytest -q` → **8421 passed / 0 failed / 1 skipped**, 5 env-failed (`rich`-fallback в `test_outgoing_guard_round1022`/`test_summary_cover_round1023`, `services/**` вне диффа — пред-существующие, не регресс F9).
- Каталог `459 98 96 21 418`; `git diff --check`=0; R17-regex 0.

## Handoff

**RESULT: SCANNED @Orchestrator** — Critical 0 / High 0 / Medium 0 / Low 0 / Info 2 (I-F9S-1 косметика, I-F9S-2 live-гейт PENDING OWNER). Блокеров нет; H-F9S-1 + L-F9S-1..4 закрыты с доказательствами. Дальше — штатный merge/деплой-цикл; live-гейт владельца (реальная TMA/WebView) не заявляется пройденным.
