# HOTFIX7 — review (T-2686, итерация 2) — `hotfix7-shell-glass-heartbeat-round1025`

- **Ревьюер:** @Reviewer, Step 5, 22.09.2026 (итерация 2 после «Changes requested»)
- **Базис:** HEAD `5a5465c` + незакоммиченное рабочее дерево
- **Вердикт итерации 1:** Changes requested (F-1 тег/бэкап; F-2 фолбэк `--shell-h`)
- **Вердикт итерации 2:** **Approved** (блокеров нет; одна Low-запись по содержимому бэкапа)
- **Инструменты субагентов в среде недоступны** — проверка выполнена @Reviewer напрямую, handoff — текстом.

## 1. Статус находок итерации 1

| ID | Было | Статус | Доказательство (факт) |
|---|---|---|---|
| **F-1** | Medium (блокер) | **Закрыто (ядро)** + Low-оговорка | `git rev-parse pre-round1025-hotfix7` → **`5a5465c`**; `git ls-remote --tags origin` → `refs/tags/pre-round1025-hotfix7 5a5465c` (запушен); `var/backups/hotfix7-round1025-20260922-052812/` (6 файлов) + `.env.bak.round1025-hotfix7`; `stash@{0}` на месте; теги `pre-round1025*` (12) не удалены. |
| **F-2** | Medium | **Закрыто** | `app.css:75` — базовое `--shell-h: 100vh;` (валидно всегда); `app.css:99-103` — апгрейд `min(100dvh, var(--tg-viewport-stable-height,100dvh))` строго внутри `@supports (height: 100dvh) and (height: min(100dvh,100dvh))`; висячий `--shell-h:100dvh;` отсутствует (grep). Матрица: `f2ShellH.fallback`=`innerH` (700/800px), `broken`=0px (баг старой цепочки эмулируется), `dvhSupported=true`, `appShellMin`=валидный px. |
| **F-3** | Low | **Закрыто** | `app.js:6693-6698` — HEALTHY-трасса читает `--ok`, фолбэк `#3DD68C` (совпадает с `.hb-healthy { color: var(--ok) }`). |
| **F-4** | Low | **Закрыто** | `app.js:6699-6700` `glowAlpha {healthy .45, warning .60, critical .85, unknown 0}`; `app.js:6762-6766` `glowScale {0.9/1.1/1.5/0}` и `shadowBlur` умножен; `app.js:6814` альфа вспышки по состоянию. |

**Оговорка к F-1 (Low, non-blocking, bounded follow-up):** содержимое файлового бэкапа `hotfix7-round1025-20260922-052812/` — это снимок **рабочего дерева** (итерация 1): в `web__static__app.css` присутствуют `--shell-h`/`--shell-bg`, в `web__app.js` — `_hbEcg`/`_hbDrawPremium`, в `web__index.html` — `shell-layout-v2`; при этом в `HEAD:web/static/app.css` `--shell-h` отсутствует. Т.е. бэкап **не является** pre-hotfix7-baseline, хотя `BASELINE.md` озаглавлен «baseline … перед правками пакета». SHA256 «источник==копия» верен (копия совпадала с источником в момент снятия), но восстановить baseline из бэкапа нельзя — только из тега `pre-round1025-hotfix7` (он корректен и запушен). Рекомендация: либо пересоздать бэкап из `HEAD`, либо уточнить формулировку `BASELINE.md`.

## 2. Воспроизведённые прогоны (итерация 2)

| Проверка | Команда | Результат |
|---|---|---|
| JS-синтаксис | `node --check web/app.js`, `telegram-init.js` | OK |
| Новый JS-регресс | `node tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js` | OK |
| Все JS-тесты | 27 файлов `tests/js/*.js` | 27/27 PASS **0 failures** |
| Полный pytest | `.venv/Scripts/python.exe -m pytest -q` | **8207 passed, 0 failed** |
| Playwright-матрица | `.venv/Scripts/python.exe tools/ui_round1025_matrix.py` | **failures: 0** (10 вьюпортов × normal/fullscreen) |
| `git diff --check` | — | exit 0 |
| Δ каталога | импорт `param_catalog`/`Settings` | **459 / 98 / 96 / 21 / 418**; hotfix7-флагов нет в `REGISTRY` |
| Δ DDL | `git status services/ migrations/` | пусто |

Геометрия shell (raw JSON): fullscreen `appShell.h == innerH` везде, кроме 430×932 → `876 = innerH−56` (симуляция нижнего бара, shell = видимая область) — корректно. `hbVisible=true` во всех режимах; `--shell-bg rgba(33,37,45,.62) ≠ --glass-bg rgba(21,27,42,.5)`; shell-панели `bg ≠` карточным.

## 3. Регрессии/ослабление тестов

- **Тесты не ослаблены — усилены:** `test_single_height_token_chain` теперь запрещает висячий `--shell-h: 100dvh;` и требует `@supports`-гвардию; добавлен `test_glow_state_dependent` (F-4, +1 тест → 8207); в матрицу добавлена проба `f2ShellH`, а `_hotfix7_failures` проверяет `fallback≈innerH`, отсутствие бага, валидный `appShellMin`.
- Legacy-пути: `shell-layout-legacy` / `shell-glass-legacy` / `_hbDrawLegacy` (`UI_HEARTBEAT_PREMIUM=false`) на месте и покрыты; `UI_HEARTBEAT_CANVAS_ENABLED=OFF` → SVG по-прежнему.
- AA не затронута (F-3/F-4 — графика canvas, не текст); палитра §8 и фон §10 не менялись; WebGL/`backdrop-filter:url(`/CDN — 0.
- Новых находок от правок не выявлено.

## 4. На live-гейт (T-2682)

Реальный Telegram WebView: mobile fullscreen — heartbeat виден, header цел, glass качественный, sidebar/topbar серые и отделены, ничего не съезжает; FPS glow/specular (для CRITICAL `shadowBlur` вырос до ×1.5) на слабом устройстве; фактическое поведение старого WKWebView без `dvh` (F-2 закрыт логически и в матрице-эмуляции, но не на живом устройстве).

## 5. Handoff

`RESULT: Approved — hotfix7-shell-glass-heartbeat-round1025 (T-2686, итерация 2). @Orchestrator — F-1/F-2/F-3/F-4 закрыты по факту (тег pre-round1025-hotfix7→5a5465c запушен; @supports-фолбэк --shell-h; единый --ok; лестница glow). Воспроизведено: node --check OK, JS 27/27, pytest 8207/0, matrix 0 FAIL, git diff --check 0, ΔDDL=0, Δкаталога=0 (459/98/96/21/418); тесты усилены. Единственная Low-оговорка: файловый бэкап hotfix7-round1025-20260922-052812 содержит снимок рабочего дерева (итерация 1), а не pre-hotfix7 baseline — hard-rollback обеспечивает корректный тег; рекомендация вынесена как bounded follow-up. Live-гейт T-2682 (реальный Telegram WebView + FPS) остаётся открытым.`
