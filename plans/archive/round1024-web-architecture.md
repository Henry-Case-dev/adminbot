# Round 10.24 — сквозной архитектурный слой (Step 2 @Architect, часть 2/2: UI & Web)

> **Эпик:** «Disaster Recovery: UI & Backend Bloat». Часть 1 (backend-core) —
> `plans/features/round1024-architecture.md`. Этот файл — **её продолжение** для
> web-слоя; контракты/инварианты Части 1 действуют здесь без изменений.
> **Источники:** `plans/current_task.md` UPD2 (стр. 159–237) + **UPD3 (стр. 239–272)**
> — untracked, в git НЕ коммитить, секреты/креды в задачах и отчётах НЕ цитировать
> (R17/R18); `tasks.md` 6 фич-папок; часть 1 `round1024-architecture.md` §8.
> **Baseline:** HEAD `00eab85`; pytest **7424/0**; SQLite `v12`; APP_VERSION 2.57.0.
> **Статус:** часть 2 из 2 — **F3, F4, F5, F6, F10, F11** (UI/web).
> **ADR части 2:** ADR-1024-7 (F3), ADR-1024-8 (F4), ADR-1024-9 (F5),
> ADR-1024-10 (F6), ADR-1024-11 (F10), ADR-1024-12 (F11). Сквозной enabler
> доставки флагов — §3 (ADR-1024-13, ниже).

---

## 0. Что уже есть (не переизобретаем)

Web-слой — Vue 3.5.42 (полная сборка, **self-host**, runtime-компилятор in-DOM),
zero-build, CSP `script-src 'self'`, никаких внешних CDN. Общие файлы этого слоя:

| Файл | Роль |
|---|---|
| `web/index.html` | In-DOM шаблоны (в т.ч. `#kv-editor-tpl`) + крупные секции вкладок |
| `web/app.js` | Корневое приложение (`TABS`, `MODULES`, `PROVIDER_BLOCKS`, computed/methods) |
| `web/static/app.css` | Стили/анимации (в т.ч. `dossier-ticker`, `details.advanced`) |
| `web/api/*.py` | Read/write API (analytics, oversight, routes, chat_lore) |
| `services/param_catalog.py` | Единый реестр параметров/групп → вкладки (`TAB_RULES`) |

Реальность, важная для планирования: **UI-флаги предыдущих раундов (10.22/10.23)
не были реализованы** (`PROMPTS_UI_V2_ENABLED`/`TOKEN_FLOW_NODEFLOW_ENABLED` и
подобных в коде нет). Их «флаг» = атомарность коммита + `git revert`. В раунде
10.24 мы вводим **единый настоящий kill-switch** (§3), чтобы OFF возвращал
прежнее поведение байт-в-байт.

---

## 1. Обзор 6 web-фич

| # | Фича | Файлы (владелец) | Δ каталога | Δ DDL | Флаг (default ON) |
|---|---|---|---|---|---|
| **F3** | `token-metrics-nodeflow-round1024` | `web/index.html`, `web/app.js`, `web/static/app.css` | 0 | 0 | `TOKEN_FLOW_NODEFLOW_ENABLED` |
| **F4** | `dossier-live-feed-round1024` | `web/**` + `web/api/oversight.py` + `services/database.py` | 0 | 0 | `DOSSIER_LIVE_FEED_ENABLED` |
| **F5** | `image-module-toggle-round1024` | `services/param_catalog.py` + `web/**` | **+1 вкладка** (0 групп/ключей) | 0 | `IMAGE_MODULE_CARD_ENABLED` |
| **F6** | `prompts-refactor-accordion-modes-round1024` | `services/param_catalog.py`, `services/prompt_style_blocks.py`, `web/**` | 0 (ключ сохраняется) | 0 | `PROMPTS_UI_V2_ENABLED` |
| **F10** | `aliases-render-real-fix-round1024` | `web/**` | 0 | 0 | `ALIASES_KEYSVALUE_RENDER_ENABLED` |
| **F11** | `byok-image-key-round1024` | `web/**`, `web/api/routes.py`, `services/chat_keys.py` | 0 | 0 | `BYOK_IMAGE_KEY_ENABLED` |

**Итоговые счётчики** (после Part 1 F7 **и** Part 2 F5):

| Метрика | Baseline | После раунда |
|---|---|---|
| `REGISTRY` | 457 | **458** (F7: +1) |
| `GROUPS` / mapped | 96 / 94 | **97 / 95** (F7: +1) |
| `_TAB_BY_GROUP` | 94 | **95** (F7: +1) |
| Конфиг-вкладок (`TAB_RULES`/`TAB_NAV`/`CONFIG_TAB_TITLES`) | 20 | **21** (F5: +`mod_images`) |
| Витрина `MODULES` (JS) | 12 | **13** (F5: +«Генерация изображений») |
| SQLite `user_version` | 12 | **12** |

F5 добавляет **вкладку**, но **не добавляет группу** (`flags_module_images` уже
существует и лишь меняет владельца-вкладку). F6 вообще не меняет каталог (ключ
`prompts.verbilizer_default_mode` сохраняется). Новых SQLite-таблиц/колонок нет;
PG не трогаем.

---

## 2. Ступени вливания общих файлов (строго)

| Файл | Ступень (порядок вливания фич) | Правило |
|---|---|---|
| `web/index.html` + `web/app.js` | **F3 → F5 → F6 → F11 → F4 → F10** | фича читает результат предыдущей и не переписывает её блоки |
| `web/static/app.css` | F3 → F4 (F4 — владелец `.dossier-ticker*`); F6 не трогает CSS `details.advanced` сверх необходимого | не удалять существующие классы |
| `services/param_catalog.py` | **F7 (Part 1, влит) → F5 → F6** | F5 переносит `flags_module_images`; F6 не меняет реестр |
| `web/api/routes.py` | **F11** (изолировано; F12 Part 1 — выше этажом) | `me.ui_flags` добавляет F3 (enabler) |
| `web/api/oversight.py` + `services/database.py` | **F4** (изолировано) | read-only резолв `user_id` |
| `services/chat_keys.py` | **F11** (изолировано) | global-secret allowlist |
| `services/prompt_style_blocks.py` | **F6** | только дефолт `casual` + fallback-контракт |

**Вне частей 2:** UI-кнопка «Проверить подключение» (владелец **F12**, Part 1,
эндпоинт `POST /api/images/test`) встраивается в web-очередь **после F5** (та же
карточка провайдера изображений). @Orchestrator ставит её отдельным шагом, чтобы
не конфликтовать с F11 (общий файл `web/app.js`).

---

## 3. Сквозной enabler: доставка UI-флагов (ADR-1024-13)

**Проблема:** UI-фича живёт в `app.js`, а env-флаги — в Python. Inline `<script>`
запрещён CSP-инвариантом (`script-src 'self'`; проверяется `tests/js/vue_mount_test.js`).

**Решение (минимальное, CSP-safe):**
1. `config/settings.py` — env-only `ClassVar[...] = bool(os.getenv(...))` с дефолтом
   **ON** (OFF возвращает прежнее поведение). В `param_catalog` НЕ добавляем (Δ=0).
2. `web/api/routes.py::me` — аддитивно (R16) возвращает `ui_flags: {name: bool}`.
3. `web/app.js` — корневой метод `uiFlag(name)` читает `this.me.ui_flags` (до загрузки
   `/api/me` — безопасный дефолт `true`), применяется в `v-if`/computed.
4. Нет inline-скриптов, нет meta-инъекций, нет изменений `_render_index`.

**Инварианты:** R16 (поле аддитивно), R17 (наружу только булевы, без значений),
CSP не нарушается. Флаги — исключительно kill-switch; штатный дефолт = новое
поведение (как требует Часть 1 §4.10).

| Флаг | Фича | Default | OFF-поведение |
|---|---|---|---|
| `TOKEN_FLOW_NODEFLOW_ENABLED` | F3 | True | плоские бейджи 10.23 (байт-в-байт) |
| `DOSSIER_LIVE_FEED_ENABLED` | F4 | True | горизонтальный тикер 42s, строки некликабельны |
| `IMAGE_MODULE_CARD_ENABLED` | F5 | True | карточка/вкладка скрыта, тумблер остаётся в «Прямых ответах» |
| `PROMPTS_UI_V2_ENABLED` | F6 | True | аккордеоны + отдельная карточка режимов |
| `ALIASES_KEYSVALUE_RENDER_ENABLED` | F10 | True | прежний (сломанный) KV-watcher |
| `BYOK_IMAGE_KEY_ENABLED` | F11 | True | прежняя маршрутизация секрета (с ошибкой) |

> Тест-контракт enabler: `test_webapp_*` проверяет наличие `ui_flags` в `/api/me`,
> отсутствие inline-скриптов, и что frontend читает `this.me.ui_flags`.

---

## 4. Инварианты раунда (web-срез; нарушать нельзя)

1. **CSP/zero-build:** только self-host; никаких CDN/библиотек графов/чартов;
   `tests/js/vue_mount_test.js` и запрет inline-скриптов остаются зелёными.
2. **`tma-menu-freeze`** — единственное санкционированное исключение: новый пункт
   «Генерация изображений» в «Модулях» (UPD3 №1). Прочие пункты/порядок меню не двигать.
3. **egress-реестр** — web-слой ничего не отправляет в Telegram; новых send-точек нет.
4. **`parse_mode=None`** — web-слой не касается текстовой доставки.
5. **R16/R17/R18** — API только аддитивно; наружу секреты только `{configured,last4}`;
   ID/имена в отчётах обезличивать; секреты `current_task.md` не цитировать.
6. **`physical-two-call-pipeline`** — телеметрия F3 только читает; счётчик вызовов не меняется.
7. **`imported-history-immutable` / `manual-overrides-immutable`** — F4 read-only
   (`graph_facts` SELECT), F10 read-only диагностика, F11 не трогает персоны/досье.
8. **Δ DDL = 0** — SQLite `v12`, новых PG-таблиц нет.
9. **Порядок роутеров `bot.py`** не сдвигается (web-слой его не импортирует).
10. **Совместимость по умолчанию** — все флаги default ON = новое поведение; OFF = байт-в-байт.

---

## 5. AMEND / RE-OPEN карта (часть 2)

| Решение | Действие | Причина (UPD2/UPD3) |
|---|---|---|
| ADR-1023-7 (UI-объём «Token Metrics») | **AMEND → ADR-1024-7** | UPD2 п.1: плоские бейджи ≠ дашборд; нужен visual Node Flow + русский нейминг |
| 10.20 T-1897 / ADR-1022-8 (горизонтальная лента 42s) | **AMEND → ADR-1024-8** | UPD2 п.2: нечитаемо; вертикально/медленнее + клик → Досье (UPD3 №9) |
| ADR-1023-5 §D5 (карточка изображений внутри «Прямого чата») | **AMEND → ADR-1024-9** | UPD2 п.3 + UPD3 №1: отдельный пункт «Модулей», default ON, menu-freeze снят для пункта |
| ADR-1023-8 (аккордеоны + отдельная карточка режимов; дефолт `serious`) | **AMEND → ADR-1024-10** | UPD2 п.4 + UPD3 №2: убрать аккордеоны; дропдаун НЕ удалять → «Резервный режим (Fallback)», дефолт `casual`; табы внутрь карточек |
| 10.22 F2 «Починили рендер JSON-словаря» | **RE-OPEN → ADR-1024-11** | UPD2 п.8: **ложный отчёт**; нужен реальный binding + живое доказательство из БД |
| ADR-1023-5 §D3 (image-ключ как глобальный секрет через общий PUT) | **AMEND → ADR-1024-12** | UPD2 п.9 + UPD3 №6: сохранение только через безопасный `/api/config/keys/own`, заглушка/GET-режим |
| ADR-1024-13 (§3, доставка флагов) | **новый** | UI-флаги ранее объявлялись, но не были реализованы — нужен настоящий kill-switch |

---

## 6. Human Gate: статус (UPD3, web-срез)

**Закрыто владельцем:** карточка изображений — отдельный пункт (№1); дропдаун —
fallback-предохранитель, дефолт `casual`, не влияет на штатный выбор (№2); клик по
факту ленты → переход на чат + модалка «Досье» (№9); BYOK image-ключа — через
безопасный эндпоинт (№6). **Остаточных вопросов нет.**

---

## 7. Риски web-среза (сводно)

| Риск | Уровень | Митигация |
|---|---|---|
| CSP/zero-build нарушен тяжёлой библиотекой графов | High | ADR-1024-7: только CSS Grid/Flexbox; гейт `vue_mount_test.js` |
| Рассинхрон пин-тестов каталога/меню | High | F5: обновить `test_frontend_tab_mapping`, `test_round106_ia_smoke`, `test_webapp_round1020_ui`, `tests/js/round1020_ui_rework_test.js` **одним коммитом** |
| F10 повторяет «ложное закрытие» | High | ADR-1024-11: обязательный live-диагностический шаг + render-тест; без доказательства не закрывать |
| F4 GLOBAL-лента ↔ per-chat досье | High | ADR-1024-8 D4: сначала `setActiveChat`, затем `openDossier`; иначе no-op + toast |
| F11 утечка секрета | Critical | ADR-1024-12: только safe-эндпоинт, маска, тест «нет plaintext» в ответах/логах |
| Порядок web-ступени нарушен | Medium | §2 + атомарные коммиты по фиче |

---

## 8. Ссылки

- Часть 1: `plans/features/round1024-architecture.md`
- Спеки+ADR: `plans/features/<feature>-round1024/spec.md` + `ADR-1024-*.md`
- Архив-образцы: `plans/archive/round1023-architecture.md`,
  `plans/archive/image-generation-tool-round1023/ADR-1023-5.md`,
  `plans/archive/summary-cover-rich-article-round1023/ADR-1023-6.md`
- Веб-ресёрч фронта: Vue `watch`/shallowReactive props
  (https://vuejs.org/guide/essentials/watchers,
  https://github.com/vuejs/core/issues/9965), вертикальный CSS-marquee
  (https://codefronts.com/motion/css-infinite-marquee/vertical-marquee-agency-services/)
