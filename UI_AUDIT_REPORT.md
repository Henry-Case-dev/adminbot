# UI_AUDIT_REPORT.md — автономный браузерный UI/UX-аудит TMA (раунд 10.21, F6)

> **Дата:** 18.09.2026 · **Агент:** @Builder (Шаг 4, батч D) · **Фича:** `ui-audit-puppeteer-round1021`
> **Baseline:** HEAD `21cd54c` (UI-доработка 10.20-UPD3 `ec93c3d` задеплоена) + рабочее дерево раунда 10.21.
> **Метод:** реальный браузерный рендер (`getComputedStyle`/`getBoundingClientRect`/`input.value`/
> `animationDuration`/console), НЕ grep. Скрипт-харнесс: `tools/ui_audit_round1021.py`;
> сырой вывод: `tools/_ui_audit_raw.json`; скриншоты: `tools/_ui_audit_shots/`.
> **R17/R18:** в отчёте/артефактах — только маска `••••••••••••` и фейковые плейсхолдеры (`sk_FAKE_*`);
> реальные секреты/хост-креды не цитируются.

---

## 1. Окружение и tooling

| Шаг | Инструмент | Результат |
|---|---|---|
| 1 | **Puppeteer MCP** (`puppeteer_navigate`/`puppeteer_screenshot`/`puppeteer_evaluate`) | ❌ **Недоступен.** В сессии зарегистрированы MCP-серверы `exa`/`context7`/`filesystem`/`memory`/`sequential-thinking`/`duckduckgo`; среди доступных tools нет ни одного `puppeteer_*`, а `list_mcp_resources` вернул только ресурсы `exa`. Инструмент вызвать физически невозможно. |
| 2 | **Playwright + Chromium** (fallback) | ✅ **Сработал.** `playwright 1.62.0` (Python API, `.venv`), **Chromium 151.0.7922.34** (`ms-playwright/chromium-1234`, headless). |
| 3 | Честный отказ | не потребовался |

**Живой локальный сервер:** `uvicorn` на `127.0.0.1:8765`, отдаёт **реальный** `web/index.html` +
`web/static/*` (`/static/app.css` — выделенный маршрут с подстановкой `__APP_VERSION__`). `/api/*` —
in-memory стаб `ConfigCache` (фейковый PG): `/api/config` отдаёт **414** catalog-ключей, `keys.*` — плейсхолдеры
`sk_FAKE_*`. Авторизация — `initData`, подписанный фейковым токеном `000000:UI_AUDIT_PLACEHOLDER_TOKEN`
(НЕ реальный секрет). Реальный бэкенд/PG/секреты не использовались.

**Viewport-матрица:** `1440×1000`, `1000×900`, `999×900`, `400×850`, а также **fullscreen** (`100dvh`, ⛶)
для sticky-панели. Эмуляция `prefers-reduced-motion: reduce` и `prefers-contrast: more` (CDP).

---

## 2. Проверенные экраны

| Раздел / экран | Статус рендера | Дефекты |
|---|---|---|
| Статус (`#/`) | ✅ карточек 5, ошибок JS 0 | — |
| Справка (`#/how`) | ✅ | — |
| Модули (`#/modules`) | ✅ 12 карточек, сетка 3 трека | — |
| ИИ (`#/ai`) — hub | ✅ `hub-grid` 3 трека | — |
| ИИ / LLM Провайдеры (`#/ai/llm`) | ✅ `prov-grid` 4 трека, 10 `prov-block`, 15 masked-полей | — |
| ИИ / Промпты (`#/ai/prompts`) | ✅ | — |
| ИИ / Память (`#/ai/memory`) | ✅ рендер; данные памяти — 503 (стаб без PG памяти) | — |
| ИИ / Умный кэш (`#/ai/smart-cache`) | ✅ | — |
| ИИ / Имена (`#/ai/names`) | ✅ | — |
| ИИ / Участники и отношения (`#/ai/relations`) | ✅ | — |
| ИИ / Лор чата (`#/ai/lore`) | ✅ | — |
| ИИ / Личность (`#/ai/persona`) | ✅ рендер; данные — 403 (стаб) | — |
| PERMsoc (`#/permsoc`) | ✅ 65 карточек | — |
| Доступы (`#/access`) + `#/access/admins|roles|local` | ✅ модалки ролей/матрицы/локалов | — |
| Сводка (`#/oversight`) | ✅ рендер; данные — 403 (стаб) | — |
| **Все 12 модалок модулей** («Параметры») | ✅ 12/12 открыты, advanced раскрыты | **F6-01** (mod_video_summary) |
| Шестерёнки «Расширенные настройки» (`.advanced` / module-modal `details`) | ✅ раскрыты и замерены | — |
| Модалки/фолбэки Advanced на LLM-ветке | ✅ `details.advanced` glass = `blur(16px)` | — |

---

## 3. Дефекты

| ID | Severity | Точный селектор / место | Сырой вывод зонда | Фикс | Статус |
|---|---|---|---|---|---|
| **F6-01** | **High** | `web/app.js` → `computed.activeModuleGroups` → `this._syntheticGroup('content','content_media')`; триггер: `#/modules` → карточка `article.module-card[data-mod="mod_video_summary"]` → `button.module-params-btn` («Выжимка видео» → «Параметры») | `pageerror`: `TypeError: this._syntheticGroup is not a function` — `at Proxy.activeModuleGroups (http://127.0.0.1:8765/web/app.js?v=2.57.0:1124:28)`; модалка не строилась, `.modal-close` отсутствовал (таймаут клика) | `_syntheticGroup` **перенесён из `computed` в `methods`** (вызывается с аргументами); регресс-тест `tests/js/round1021_ui_audit_test.js` §7 | ✅ Fixed, проверено рендером (module_5: `passwordFields=4`, маски `••••`, JS-ошибок 0) |
| **F6-02** | **Low** | `web/index.html` → `.scope-wrap` → `.scope-panel.card-solid` (`right: 0` + `min-width: 260px`) | `getBoundingClientRect()` панели на `#/ai/persona` (1440): `x = -45.7`, `right = 214.3` → левый край (аватар/контент) уходил за вьюпорт; на `#/` `x = -5` | Добавлен метод `positionScopePanel()` (`web/app.js`), ослабленный сбросом прошлой коррекции + `:style="scopePanelStyle"` на панели: при левом клипе якорит `left:0` и ограничивает `maxWidth` вьюпортом; при правом — оставляет `right:0` | ✅ Fixed: post-fix `x = 24`, `leftClip=false`, `rightClip=false` (1440 и 400); регресс-тест §8 |

**Других визуальных дефектов не найдено.** Реальный рендер по всем разделам/модалкам не выявил:
- пересечений видимых карточек/панелей вне штатного оверлея модалок (`overlaps = 0` на всех маршрутах);
- горизонтального переполнения (`scrollWidth − clientWidth = 0` для `documentElement` и `.scroll-area`);
- отрицательных margin, кроме служебного Tailwind `sr-only` (`margin: -1px`);
- обрезанных/вылезающих `input.field` (`scrollWidth ≤ clientWidth`).

### Сырые замеры по фокусным зонам ТЗ (реальный Chromium)

**Liquid Glass** (viewport 1440, `getComputedStyle`):
```
.card / .modal-card / .module-card / .hub-card / .prov-block /
details.advanced / .scope-panel / .glass-panel / .oversight-panel
   background-color: rgba(20, 25, 30, 0.5)
   backdrop-filter:  blur(16px) saturate(1.4)     (webkit-дубль есть)
   border-color:     rgba(255, 255, 255, 0.12)
.sticky-save
   background-color: rgba(20, 25, 30, 0.85)       (непрозрачная подложка)
   backdrop-filter:  blur(16px)
```
Фолбэк `@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)))` →
`background-color: var(--glass-bg-strong)` (проверено через CSSOM `document.styleSheets`).

**CSS Grid** (`.prov-grid`, ветка «ИИ»):
```
viewport 1440 → "340px 340px 340px 340px"   (4 трека)
viewport 1000 → "476px 476px"               (2)
viewport  999 → "475.5px 475.5px"           (2)
viewport  400 → "368px"                     (1; @media ≤479px → 1fr)
.module-list 1440 → "356px 356px 356px"     (3)
.hub-grid    1440 → "330.656px 330.672px 330.656px" (3)
```

**Data binding / маски** (`input[type=password].value`):
```
#/ai/llm  (провайдеры)             15 / 15  = "••••••••••••" (len 12, masked)
module_5 «Выжимка видео»            4 /  4  = "••••••••••••"
module_8 «Диагностика» (betterstack)2 /  2  = "••••••••••••"
пусто только при null/{configured:false} (INV-3; JS-кейсы)
```

**Градиент** (`getComputedStyle(documentElement)` / `body::before`):
```
--grad-speed: 6s   (∈ [5,8])     --grad-d: #FF8A3D (оранжевый)
body::before animation: grad-spin, grad-drift | duration 6s, 6s | opacity 0.42
background: conic-gradient(... rgb(102,78,160), rgb(20,203,182), rgb(255,138,61), rgb(141,107,220) ...)
prefers-reduced-motion: reduce → animation-name: none; animation-duration: 0s; opacity 0.35; linear-gradient
prefers-contrast: more         → animation-name: none; opacity 1
```

**Sticky / M-1 (fullscreen ⛶, scroll до низа, скроллер `main.scroll-area`)**:
```
#/ai/prompts  panel.bottom = 1000  scroller.bottom = 1000   gap = 0.0px
#/ai/llm      panel.bottom =  999.6 scroller.bottom = 1000  gap = 0.4px
padding-bottom скролл-контейнера = 0px; .sticky-spacer присутствует
modal_5       panel.bottom =  809   .modal-body.bottom = 809 gap = 0.0px
```
Ранее наблюдавшийся разрыв **88px устранён** (подтверждено независимым замером).

**Инвариант меню:** `navbar .nav-link = 6`, `data.tabs = 25`, `data.modules = 12` — не изменены.

**Панель выбора контекста (L-4, `.scope-panel`)** — `getBoundingClientRect` после фикса:
```
#/ai/persona  1440: x=24.0   right=284.0   leftClip=false  rightClip=false  style "left:0;right:auto;max-width:1408px"
#/            1440: x=65.7   right=325.7   leftClip=false  rightClip=false
#/ai/relations 400: x=113.2  right=373.2   leftClip=false  rightClip=false
```

---

## 4. Консоль

| Тип | Запись | Трактовка |
|---|---|---|
| `pageerror` | `TypeError: this._syntheticGroup is not a function` (при открытии «Выжимка видео») | **Дефект F6-01 — исправлен** |
| `error` ×7 | `Failed to load resource: 503` — `/api/memory/cognition/status`, `/api/memory/graph`, `/api/memory/dream/beliefs`, `/api/memory/dream/log`, `/api/memory/nostalgia/log`, `/api/chat_lore/chats` | Ограничение харнесса: стаб без PG памяти/лора. Не дефект фронта (UI рендерит состояние ошибки). |
| `warning` | `[Telegram.WebApp] BackButton/Header color/… is not supported in version 6.0` | Артефакт headless-окружения вне Telegram (SDK-заглушка 6.0). В реальном WebView версия ≥8.0. |
| JS-ошибки после фикса | **0** | — |
| React-варнинги | нет (приложение на Vue 3) | — |

---

## 5. Скриншоты (маскированные)

`tools/_ui_audit_shots/` (фейковые данные стаба, реальных секретов нет):

| Файл | Экран |
|---|---|
| `route_Модули.png` | «Модули» — сетка 3 трека |
| `route_ИИ-LLM-Провайдеры.png` | «ИИ»: `prov-grid` 4 трека, glass, маски |
| `route_ИИ-Память.png` | «ИИ / Память» (много карточек) |
| `route_Справка.png`, `route_Статус.png`, `route_Сводка.png` | Справка / Статус / Сводка |
| `modal_module_5.png` | Модалка «Выжимка видео» (закрытый F6-01) |
| `llm_advanced_open.png` | «ИИ» — раскрытый блок «Расширенные» |
| `scope_panel_persona.png` | Панель «Выбор контекста» (закрытый F6-02) |
| `sticky-fullscreen-prompts.png` | Fullscreen ⛶, sticky-панель прижата к низу |
| `access_Доступы-Матрица.png` | «Доступы» — матрица ролей |

---

## 6. Закрытые ранее дефекты UPD3 (регресс-чек на реальном рендере)

| Дефект UPD3 | Проверка 10.21 (реальный Chromium) | Статус |
|---|---|---|
| Liquid Glass (`rgba(20,25,30,.5)` + `blur(16px)`) | computed по всем glass-селекторам совпал | ✅ закрыт ранее, подтверждён |
| CSS Grid («ИИ»/«Модули» ≥2 трека) | 4 / 3 трека при 1440, 2 при 999, 1 при 400 | ✅ закрыт ранее, подтверждён |
| Маска секретов `••••••••••••` | все password-поля в 3 ветках (llm/module_5/module_8) замаскированы | ✅ закрыт ранее, подтверждён |
| Градиент 5–8s + оранжевый | `6s`, `#FF8A3D`, conic-gradient с rgb(255,138,61); reduced-motion/contrast глушат | ✅ закрыт ранее, подтверждён |
| **M-1 (sticky 88px, fullscreen config)** | зазор панель↔низ = **0.0–0.4px**, `padding-bottom=0`, `.sticky-spacer` на месте | ✅ закрыт ранее (T-1936-fix2), **подтверждён замером** |
| L-1 `@focus select` на не-секретных | обработчики условны по `f.secret` (3×) | ✅ закрыт ранее |
| L-2 silent-no-op маски | тост «введено в поле маска…» (warn), не «Уже сохранено» | ✅ закрыт ранее |
| L-3 `@supports` padding-bottom | фолбэк без `padding-bottom` | ✅ закрыт ранее |

**Открытые Info (не дефекты, не переоткрываются):** I-1 неиспользуемый в рантайме `isSecretMask`,
I-2 алиас `--surface-glass`, I-3 `data.secretMask` без потребителя.

---

## 7. Ограничения

1. **Telegram WebView (Android/Nekogram/iOS WKWebView) не воспроизводился** — риск R1: headless
   Chromium ≠ реальный WebView (`-webkit-backdrop-filter`, поведение `:has()`/`select()` на тапе,
   `env(safe-area-inset-*)`). Фолбэки `@supports` статически сохранены.
2. `/api/memory/*`, `/api/chat_lore/*` в стабе отдают **503** (нет PG памяти), `/api/oversight/*`,
   `/api/persona`, `/api/roles*` — **403** (стаб-роль не даёт соответствующих прав). Это ограничение
   харнесса, а не дефекты UI; визуальный рендер разделов при этом проверен.
3. Прод-хост `/static/app.css` (доставка) — вне этого аудита (проверяет @DevOps).
4. Скриншоты визуальной приёмки — только desktop 1440 (мобильный WebView недоступен).

---

## 8. Честный статус инструментов

- **Puppeteer MCP — недоступен** в данном окружении (нет зарегистрированных `puppeteer_*` tools);
  попытка использовать его зафиксирована как невозможная, а не «успешная».
- **Визуальный аудит ВЫПОЛНЕН** через fallback **Playwright 1.62 + Chromium 151.0.7922.34**:
  реальный рендер, CSSOM-замеры, значения инпутов, анимации, консоль, скриншоты.
- Все замеры в отчёте получены из фактического рендера и сохранены в `tools/_ui_audit_raw.json`;
  выдуманных результатов/скриншотов нет.

---

## 9. Воспроизведение

```bash
# 1) реальный браузерный аудит (Playwright + Chromium), артефакты:
.venv/Scripts/python.exe tools/ui_audit_round1021.py
#    → tools/_ui_audit_raw.json, tools/_ui_audit_shots/*.png

# 2) регресс-защита (node, без браузера):
node tests/js/round1021_ui_audit_test.js      # → JS-UNIT-OK
node --check web/app.js

# 3) полный pytest
.venv/Scripts/python.exe -m pytest tests/ -q
```
