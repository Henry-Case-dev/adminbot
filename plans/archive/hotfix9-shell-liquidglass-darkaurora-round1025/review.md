# Review (итерация 2) — HOTFIX9 `hotfix9-shell-liquidglass-darkaurora-round1025` (T-2835, @Reviewer)

- **Feature-ID:** `hotfix9-shell-liquidglass-darkaurora-round1025`
- **Status: Approved** — блокеров нет; итерация 1 (High H-H9S-1, Medium M-H9R-1, Low×5) закрыта по факту, новых проблем не выявлено.
- **База:** рабочий каталог поверх HEAD `b374c0f`; тег `pre-round1025-hotfix9` → `b374c0f`, `stash@{0}` на месте, `plans/current_task.md` untracked (R18).

## Чек-лист итерации 1 → статус
| Находка | Статус | Независимое доказательство |
|---|---|---|
| **H-H9S-1** футер модалки модуля внутри `.modal-body` | **Закрыто** | HTML-парсер: у `footer.modal-actions` предки `…modal-backdrop > modal-card` (без `modal-body`), вложенных футеров 0; счётчик div сбалансирован (`web/index.html:1919–1930`). Матрица (модалка модуля `mod_sleep`): `modalBody.bottom 675 < modalActions.y 683` (390), `785<793` (768), `673<681` (1280), `stickyInActions=true` |
| **M-H9R-1** context-loss fallback не срабатывал | **Закрыто** | Мой Playwright-репро `WEBGL_lose_context`: `mode()='canvas2d'`, яркость 58.8→55.3 (кадр есть). Матрица: `mode=canvas2d, sampleCount=64, brightness=46/50` на 390/1280; ассерты `mode!='webgl'`, `sampleCount>0`, `brightness≥3` |
| **L-H9S-1** `stop()` не убирал canvas | **Закрыто** | `aurora-flow.js:269–275` → `detachCanvas()` (removeChild + destroy + сброс состояния) |
| **L-H9S-2** мёртвый `UI_SHELL_V3` | **Закрыто** | `app.js:2462`: `shellGraphiteV3 = uiFlag('UI_SHELL_GRAPHITE_V3') && uiFlag('UI_SHELL_V3')` |
| **L-H9S-3** двойное стекло `.status-block` | **Закрыто** | `web/index.html:3276` — `class="card p-4 status-block"` без `data-glass="a"`; остаются 1934/3464 (tier-A жив) |
| Нет `scrollIntoView({block:'nearest'})` | **Закрыто** | `telegram-init.js:89–106` — только для `input/textarea/select` внутри `.modal-body` |
| Гейт стекла не проверял `scale` | **Закрыто** | `glass_prototype_probe.py` ассертит `feDisplacementMap` + `scale>0`; факт `displacementScale=14.56` |
| Маркер-тесты | **Усилены, не ослаблены** | `tests/test_webapp_hotfix9_round1025.py::test_modal_actions_sibling_of_body` — парсер предков, `assert parser.actions` (не вакуум); я воспроизвёл red: удаление `</div>` на строке 1920 → `nested=[1925]` ⇒ тест падает |

## Воспроизведённые цифры (мои прогоны, не со слов @Builder)
- `node --check`: `app.js`, `telegram-init.js`, `aurora-flow.js`, `glass.js`, оба vendored-бандла, `build.mjs` — OK; `git diff --check` — OK (только CRLF).
- `pytest -q` → **8291 passed / 0 failed** (106.6 с); `tests/test_webapp_hotfix9_round1025.py` → 18 passed (+1 новый).
- `tools/ui_round1025_matrix.py` → **failures: 0** (10 вьюпортов × 5 режимов).
- `tools/glass_prototype_probe.py` → `mounted=true`, `hasDisplacement=true`, `displacementScale=14.56`, `diffGlass=15.97`, `diffHole=63.817`, `failures: 0`.
- Δ DDL=0 (нет миграций в `git status`); Δ каталога=0 (459/98/96/21/418, `in_catalog=[]`).
- CSP без изменений (`script-src 'self' 'unsafe-eval'`, без CDN/инлайна); `backdrop-filter:url(` в авторском CSS = 0; `--shell-texture` только в doc-комментариях; `background-image: var(--shell-specular), …` на shell = 0.
- Vendored SHA-256 3/3 совпадают с `web/static/vendor/README.md`; версии `ogl 1.0.11` / `@liquidglassjs/core 0.5.3` зафиксированы; `.gitignore` покрывает `tools/vendor/node_modules/` и артефакты probe.
- Логика F0/F9 не тронута: `git diff web/app.js` — 8 ханков (флаги/scrollTop/_hbResize/aurora/glass), без `persistItems`/`saveModalEdits`/store.

## Новые находки
Блокирующих нет. Незакрытый ограниченный техдолг (не мешает приёмке):
- [Info] `preserveDrawingBuffer:true` у фонового рендерера (нужен для `sample()`) — цена по перфу в проде.
- [Info] `_panel_contrast_failures` матрицы по-прежнему моделирует shell-панели через `--glass-bg`; фактический графит `.94` даёт AA ≈7.3:1 (лучше), т.е. тест-сталness, не дефект.
- [Info] `--shell-texture` встречается в 2 комментариях `app.css` (кода нет).

## Requirement/evidence coverage
§4/§5/§6 геометрия и модалки — OK (matrix + parser); §7/§8 текстура/графит/AA — OK; §9 стекло (точечно, same-origin, CSP, `scale>0`) — OK; §10 фон (движение/пауза/DPR/reduced-motion/context-loss) — OK; §11 сердцебиение — только `_hbResize`, дизайн не тронут; инварианты R17/R18 — OK.

## Unavailable checks
Живой Telegram WebView (реальные insets/клавиатура, FPS стекла/фона, WebKit `feDisplacementMap`) — **PENDING OWNER VERIFICATION** (не пройдено; не блокирует продолжение F6 по §15).

**RESULT: Approved @Orchestrator, evidence: `plans/features/hotfix9-shell-liquidglass-darkaurora-round1025/review.md`. Живой WebView — PENDING OWNER VERIFICATION. Следующий шаг — @Scanner (T-2836) → @DevOps деплой (T-2837).**
