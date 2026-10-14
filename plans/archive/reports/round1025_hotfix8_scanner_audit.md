# round1025 HOTFIX8 — Scanner-аудит `hotfix8-shell-glass-aurora-round1025`

**Дата:** 2026-09-22 · **Итерация:** Step 6 UPD2 (T-2784) · **Статус:** `SCANNED`
**Режим:** focused diff-based audit рабочего дерева относительно HEAD `a1e6db3` (`pre-round1025-hotfix8`).
**Контекст:** UPD2 стр. 6156–6496; `spec.md`, `adr-1025-16`, `evidence.md`, `deployment.md`, `tasks.md`; отчёты `round1025_hotfix8_contrast.md`, `round1025_hotfix8_ui_report.md`.

> Правки не закоммичены. Bump `2.58.10 → 2.58.11` (T-2786) — Block G, намеренно ещё не сделан.

---

## Вердикт

**К автоматизированному деплою — ДА (блокеров нет).**
Critical 0 / High 0 / Medium 0 / Low 3 / Info 3. Единственный обязательный оставшийся гейт — **live-проверка реального Telegram WebView (T-2776, владелец)**, заложенная самим ADR (FPS blob, safe-area, нативные кнопки) — не является новым блокером Scanner.

| Severity | Кол-во | Блокирует релиз |
|---|---|:--:|
| Critical | 0 | — |
| High | 0 | — |
| Medium (блокирующий) | 0 | — |
| Medium (perf, non-blocking, покрыт T-2776) | 0 | — |
| Low | 3 | нет |
| Info | 3 | нет |

---

## Независимо воспроизведённые доказательства

| Проверка | Команда | Результат |
|---|---|---|
| Синтаксис JS | `node --check web/app.js` + `telegram-init.js` | OK |
| JS-маркер HOTFIX8 | `node tests/js/round1025_hotfix8_shell_aurora_test.js` | `HOTFIX8-SHELL-AURORA-OK` |
| Регресс hotfix6/7 | `node tests/js/round1025_hotfix6_…` / `hotfix7_…` | OK / OK |
| Целевой pytest | `pytest tests/test_webapp_hotfix8_… tests/test_webapp_hotfix6_… tests/test_webapp_ui_rework_round1020.py` | **78 passed** |
| Δ DDL | diff не касается `services/**` БД | **0** |
| Δ каталога | REGISTRY 459 / GROUPS 98 / `_TAB_BY_GROUP` 96 / TAB_RULES 21 / Settings 418 | **0** |
| Playwright-матрица | `tools/_ui_round1025_raw.json` → `failures` | **0**, `shellA=False`, `sidebarW=216`, `headerCardGap=16`, `auroraBlobs=5`, `auroraAnim=aurora-blob-1` |
| CSP/zero-build | grep `backdrop-filter:url(`, WebGL, CDN/`data:image` | 0 |
| Гигиена | `git diff --check`; индекс на `.env`/`current_task`/zip/PNG | чисто (0) |
| R18 | тег `pre-round1025-hotfix8` → `a1e6db3`; `.env.bak.round1025-hotfix8`; `stash@{0}` | целы |

Новые токены подтверждены на живом DOM матрицы: mobile-панели `background-color: rgba(24, 28, 38, 0.78)`, desktop `rgba(24, 28, 38, 0.72)`, `border rgba(255,255,255,0.08)`, `backdrop-filter: blur(18px) saturate(1.15)`, `shellLensPaint.content='none'` (цветной линзы A на shell нет).

---

## Находки

### Low

**[L-H8S-1] Перф-риск aurora (paint-heavy), open — покрыт live-гейтом T-2776.**
`web/static/app.css:210-255`. 5 элементов `.aurora-blob` 52vmax с `filter: blur(64px)` и постоянным `will-change: transform` анимируют `transform` **и `border-radius`** (paint-свойство → непрерывная ре-растеризация blur); `body::before/after` (fixed, full-viewport) анимируют `background-position` (не композитится). Митигации есть: `html.lg-bg-paused` (hidden) и `prefers-reduced-motion`. FPS headless не измеряется — ADR/evidence сами выносят это в live-гейт T-2776. Действие: подтвердить FPS/батарею на low-end WebView в T-2776; при провале — перевести blob-слой в статичный/урезать blur. Блокером не считаю (нет замеров, дизайн-требование «фон живой»).

**[L-H8S-2] Тест-покрытие: mobile `.78` не ассертится, отсутствие панели = pass, open.**
`tools/ui_round1025_matrix.py:623` (`shellBg = tok('--shell-bg')` читает токен с `:root` → всегда `.72`; mobile `.78` приходит только из computed панелей и не проверяется `_hotfix8_failures`); `_hotfix8_failures` считает `glass=None` (панель отсутствует) валидным; `tests/test_webapp_hotfix6_round1025.py:73` — проверка drawer подстрокой «где угодно». Не слабее прежнего, но: рекомендую ассертить computed mobile-bg `.78` и `data-glass="shell"` именно у существующей панели.

**[L-H8S-3] AA-расчёт worst-case по одному blob, open.**
`plans/reports/round1025_hotfix8_contrast.md`: композит считается по одной (самой светлой) teal-фазе; перекрытие нескольких blob и слой `body::after` (opacity .9) теоретически могут поднять яркость выше расчётной. Запас велик (минимум **7.33:1** при пороге 4.5:1), практического риска нет. Действие: пере-проверить AA на реальном фоне в T-2776.

### Info

- **[I-H8S-1]** `APP_VERSION = "2.58.10"` (`config/settings.py:1715`) — bump `2.58.11` (T-2786) ожидаемо в Block G; тесты намеренно фиксируют 2.58.10. Не дефект.
- **[I-H8S-2]** F2-чекер ослаблен намеренно: `_f2_failures` больше не требует `grad-spin` (достаточно любой живой анимации), убран `body::before opacity>0.32`; инвариант «фон не static» сохранён новым `test_f2_checker_rejects_static_background`. Соответствует ADR-1025-16 D3.
- **[I-H8S-3]** `header.header-sticky { border-top/right/left: 0 }` — shorthand сбрасывает `border-*-color` в `currentColor` (проба показывает `rgb(244,247,251)`), но ширина 0, визуально ничего; видимая нижняя рамка — `rgba(255,255,255,.08)`. Действий не требует.

---

## Инварианты (все подтверждены)

| Инвариант | Статус | Доказательство |
|---|:--:|---|
| Δ DDL = 0 | PASS | diff не трогает `services/**`/БД; SQLite v12 |
| Δ каталога = 0 | PASS | 459/98/96/21/418; `param_catalog.py` не в diff; флаги `UI_SHELL_V3`/`UI_AURORA_BG_ENABLED` отсутствуют в `REGISTRY` |
| env-only флаги | PASS | `ClassVar` default ON + `/api/me.ui_flags` (bool) + `.env.example` (комментарии) |
| `APP_VERSION` | PASS (2.58.10) | bump в Block G (T-2786) — зафиксировано, не дефект |
| CSP/zero-build | PASS | нет CDN/inline/WebGL/`data:image`/новых библиотек; `backdrop-filter:url(` = 0; `filter:url(#lg-lens)` — только форграунд-слой существующего стекла |
| XSS/injection | PASS | новых `innerHTML`/`v-html`/`insertAdjacentHTML` нет; `_syncBgLayer` только `classList.toggle` по bool |
| Утечки rAF/observer/анимаций | PASS | новых rAF/observer нет; `onVisibilityChange`/`lg-bg-paused` — единый обработчик; reduced-motion гасит |
| Атомарность маркер-тестов | PASS | новые JS+Python маркер-гейты падают до HOTFIX8; static-фон → FAIL |
| Карточные `--glass-*`/палитра §8 | PASS | `--glass-bg rgba(21,27,42,.5)`/`.85` не тронуты; shell ≠ card computed |
| IA F1 / маршруты | PASS | не в diff; тесты IA зелёные |
| F5 §61 workspace / F4 store §37–§42 / F0 `persistItems` / F3 guard | PASS | не в diff |
| `computeBottomOffset` / hotfix4 / fullscreen-sync ADR-1024-24 | PASS | не в diff; `--tg-viewport-bottom-offset` сохранён |
| Deny-list tier C | PASS | `[data-glass="c"]` не тронут |
| R17 (секреты) | PASS | в diff только комментарии/bool; `.env` не в индексе |
| R18 (тег/бэкап/stash) | PASS | `pre-round1025-hotfix8`→`a1e6db3`; `.env.bak.round1025-hotfix8`; `stash@{0}` цел |
| Логика shell ≠ карточки, фон анимирован, legacy OFF, пауза/reduced-motion | PASS | raw.json: `shellBg≠glassBg`, `auroraAnim` активен, `bg-wash-legacy`-ветка и `lg-bg-paused` в CSS/JS |

---

## Изменённые файлы (разово, относительно `a1e6db3`)

`web/static/app.css` (+shell §4, aurora, радиусы, sidebar 216, `.scope-trigger` 16, `.shell-v3-off`), `web/index.html` (`data-glass="shell"` ×5 + `.aurora-bg`), `web/app.js` (computed `shellV3`/`auroraBgEnabled`, `_syncBgLayer`), `config/settings.py` (2 `ClassVar`), `web/api/routes.py` (доставка в `ui_flags`), `.env.example` (док), `tools/ui_round1025_matrix.py` + 4 тест-файла (обновление маркеров), новые `tests/js/round1025_hotfix8_shell_aurora_test.js`, `tests/test_webapp_hotfix8_round1025.py`, отчёты/фича-доки.

---

RESULT: SCANNED @Orchestrator — `hotfix8-shell-glass-aurora-round1025`, diff `a1e6db3..worktree`, блокеров нет (Critical/High/Medium=0; Low 3 / Info 3 — owner T-2776 live-gate + follow-up). Δ DDL=0, Δ каталога=0 (459/98/96/21/418), CSP/zero-build, R17/R18 чисто, pytest 78 passed (target) / JS-маркеры OK / matrix failures 0. Отчёт: `plans/reports/round1025_hotfix8_scanner_audit.md`.
