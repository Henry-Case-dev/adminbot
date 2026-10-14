# Scanner audit (re-run) — UPD3 hotfix9 `hotfix9-shell-liquidglass-darkaurora-round1025`

- **Дата:** 22.09.2026, Step 6 @Scanner (повторный, после фиксов @Builder).
- **База:** HEAD `b374c0f` (== `origin/master`, тег `pre-round1025-hotfix9`); дерево НЕ закоммичено.
- **Скоуп повторного прогона:** закрытие H-H9S-1, M-H9R-1, L-H9S-1..3 + отсутствие новых Critical/High/Medium.
- **Вердикт: SCANNED — к деплою ГОТОВО.** Critical 0 / High 0 / Medium 0 / Low 0 (открытых) / Info 3.

## Статус прежних находок

| ID | Было | Стало | Доказательство |
|---|---|---|---|
| H-H9S-1 | High | **RESOLVED** | `web/index.html:1920` восстановлен `</div>` закрытия `.modal-body`. HTML-парсер: `footer.modal-actions` — прямой ребёнок `div.modal-card` (сиблинг `.modal-body`) во всех 5 футерах; финальный стек пуст, ошибок 0. Парсер-тест `test_modal_actions_sibling_of_body` — red-on-regression (проверено: при удалении `</div>` ловит вложение, строка 1924). Матрица §12 для модалки модуля ассертит `modalBody.bottom <= modalActions.y+1` и `stickyInActions=true`. |
| M-H9R-1 | Medium | **RESOLVED** | `aurora-flow.js:101–122` + `attach2dFallback():153–167`: при `webglcontextlost` создаётся СВЕЖИЙ canvas (старый владеет WebGL-контекстом и не отдаёт `getContext('2d')`), подменяется в DOM, рисуется кадр. Матрица: `H9_CONTEXT_LOSS_JS` (реальный `WEBGL_lose_context.loseContext()`) → `mode!=webgl`, `sampleCount>0`, `brightness>=3`. |
| L-H9S-1 | Low | **RESOLVED** | `aurora-flow.js:169–184,269–275`: `stop()` → `detachCanvas()` (removeChild + renderer.destroy + сброс mode='none'/'lost'). «Застывший» кадр при `UI_AURORA_FLOW_V2=OFF` не остаётся. |
| L-H9S-2 | Low | **RESOLVED** | `web/app.js:2462–2468`: `shellGraphiteV3 = uiFlag('UI_SHELL_GRAPHITE_V3') && uiFlag('UI_SHELL_V3')` — legacy-рубильник снова действует (алиас), задокументирован в `.env.example`/settings. |
| L-H9S-3 | Low | **RESOLVED** | `web/index.html:3276`: у `.status-block` снят `data-glass="a"` — нет двойной обработки (legacy `::before` + библиотека). |

## Новые находки

**Critical/High/Medium — 0.**

**Info (не блокирует):**
- I-H9S-1: текст лицензий MIT/Unlicense vendored-бандлов не поставлен (только строка в `web/static/vendor/README.md`) — паттерн pre-existing (chart/vue/vis).
- I-H9S-2: `tools/glass_prototype_probe.py` поднимает локальный `127.0.0.1:8792` — dev-инструмент, в рантайм/поставку не входит.
- I-H9S-3: `telegram-init.js:88–101` `scrollActiveModalField()` вызывается на каждый `visualViewport` resize/scroll (при фокусе в `.modal-body`) — минимальный `scrollIntoView({block:'nearest'})`, риск джанка низкий; наблюдать на live-приёмке (T-2832).

## Инварианты (повторно проверено)

| Инвариант | Результат |
|---|---|
| Δ DDL = 0 | OK (миграций/ALTER нет) |
| Δ каталога = 0 | OK — REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21 / Settings 418; 4 флага ∉ `pc.REGISTRY` |
| `APP_VERSION` 2.58.12 | OK (`config/settings.py:1734`, `README.md`, пины) |
| CSP `script-src 'self'`, same-origin | OK — vendored локальные, `src/href="http` в index.html = 0, inline-скриптов нет, `eval(`/`new Function` в новых модулях = 0 |
| `--shell-texture` | 0 в `web/**`; `var(--shell-texture)` = 0 |
| `backdrop-filter:url(` | 0 |
| SHA-256 vendored | OK — 3/3 совпадают с `web/static/vendor/README.md` |
| R17 | OK (секретов/абсолютных путей в новых файлах нет) |
| R18 | OK — тег `pre-round1025-hotfix9` на HEAD, `stash@{0}` на месте |
| Маркер-тесты | не ослаблены; добавлены `test_modal_actions_sibling_of_body`, H9 context-loss/module-modal probes |
| `git diff --check` | exit 0 |

## Прогоны @Scanner (independent)

- `node --check` (app.js / aurora-flow.js / glass.js / telegram-init.js / build.mjs / hotfix9-js) → OK.
- JS-тесты: `HOTFIX9-SHELL-FLEX-GLASS-AURORA-OK`, `HOTFIX7-...-OK`, `HOTFIX8-...-OK`, `JS-UNIT-OK` → все PASS.
- `py -3 -m pytest -q` → **8291 passed / 0 failed** (107.78s).
- Парсер вложенности: текущий — 0 вложенных; искусственно сломанный — ловит (line 1924).
- Каталог напрямую: 459/98/96/21/418, `in_catalog=[]`.
