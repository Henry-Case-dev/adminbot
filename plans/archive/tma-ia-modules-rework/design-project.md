# Архитектурно-дизайн проект: новая IA TMA (Модули 11 + Настройки AI 7) — раунд 10.6

> **Статус:** 🟢 **DESIGN v2** (11.09.2026, Step 2 повторно / @Architect, задача **T-1200**;
> v1 — T-1155; апрув владельца — **T-1156 пройден**). **A1–A9 внесены** — см. §10 «Ревизия v2».
> **Фича:** `plans/features/tma-ia-modules-rework/` (раунд **10.6**).
> **Вход:** `tasks.md` (обратная связь владельца §1, инвентарь §2, вопросы §5),
> `services/param_catalog.py` (фактический дамп REGISTRY 387 / GROUPS 74 / Settings 359),
> `web/app.js` (TABS / NAV_ITEMS / HUBS / ROUTE_*), `web/index.html`
> (navbar / sidebar / `.fullscreen-mode`), архив `plans/archive/tma-relume-redesign/`
> (baseline 10.5), `plans/project.md`, `plans/ARCHITECTURE.md`,
> `plans/reports/round10.5_scanner_audit.md`, `full_audit_results.md`, `global_map.md`,
> `audit_backlog.md`.
> **Язык:** простые русские слова; **код/пути/идентификаторы — английский.**
> **🟢 HARD GATE ПРОЙДЕН 11.09.2026:** владелец утвердил этот документ и `spec.md`
> (T-1156) и дал «proceed». Реализация разрешена. **0 кода** в этом документе.
> **Scanner:** `plans/reports/` перечитан; актуален `round10.5_scanner_audit.md`
> (0 blocker / 0 major, 2 minor + 5 info). Ремедиации R10.5-1/R10.5-2 учтены (§6.5).

---

## 0. Резюме для владельца (TL;DR)

1. **Одна навигация.** Убираем левый **sidebar полностью** (и «гамбургер», и затемняющий
   фон, и все мобильные ветки). Остаётся **только верхний navbar** из **6 пунктов**.
2. **Подписи под иконками.** Каждый пункт navbar становится вертикальным:
   **иконка сверху, маленькая подпись снизу** (10px). Подписи видны **и на мобилке, и на
   десктопе** (сейчас ≤479px они скрывались — это убираем). Длинные названия
   аккуратно переносятся на 2 строки и не разъезжаются.
3. **Скролл в полноэкранном режиме починен.** Контент-колонка получает **собственный
   `overflow-y:auto`**, а не «скроллится сам сайдбар» (сайдбара больше нет).
4. **«Модули» = ровно 11 модулей** (Саммаризация, Прямые ответы, Фактчек, Поиск,
   Транскрипт голосовых и видео, Выжимка видео, Скачивание медиа, Веб-страницы,
   Диагностика, Сон, Ностальгия). У каждого — **тумблер вкл/выкл** и кнопка
   **«Параметры»**, открывающая **окно со всеми параметрами и лимитами** этого модуля.
   Никаких других модулей и карточек.
5. **«Кастомные модули» удаляем** (это была ошибка AI-генерации; B2 остаётся OUT).
6. **«Настройки AI» = 7 подразделов**, «Лимиты» **удаляются** (растворяются по модулям):
   LLM Провайдеры, Промпты, Память (вся память+RAG), Умный кэш, Имена,
   Участники и отношения, Лор чата.
7. **«LLM Провайдеры»** переверстываются: сверху — модель прямых ответов
   (**main → fallback**); **один визуальный блок = base_url + model + api key**;
   добавляется кнопка **«Проверить подключение»** (test connection).
8. **«Функции PERMsoc» очищаются:** 10 случайно заехавших параметров переезжают в модули
   (1 → Скачивание медиа, 6 → Транскрипт, 3 → Выжимка видео). PERMsoc = **только
   захардкоженные простые per-chat функции**.
9. **«Леха» и «Костик» — отдельные пункты** (не одна секция).
10. **Ничего не теряем.** Все 17 прежних вкладок и все фичи (scope-switcher, матрица ролей,
    доступность ключей, гейты, BYOD/BYOK, логи, 409-модалка, аватары) получают новый дом.
    Карта паритета — §6.4.
11. **Каталог v2 (locked):** `+5 master-флагов` **default ON** (честные тумблеры
    Фактчек/Поиск/Выжимка видео/Веб/Диагностика) + RAG-группа `limits_rag` ⟹ **REGISTRY 392 /
    Settings 364 / GROUPS 91 / mapped 89** (Δ GROUPS **74 → 91 = +17**). Детали — §10.
12. **Ноль новых PG-DDL.** Только `param_catalog.py` (+ `config/settings.py` при одобрении
    флагов). SQLite остаётся v8; порядок роутеров `bot.py` не меняется; `media/` не трогаем.

---

## 1. Обратная связь владельца → что меняем (traceability)

| # | Требование владельца | Как закрываем | Раздел |
|---|---|---|---|
| 1 | Два nav-панели — неправильно. Убрать sidebar, оставить только top navbar; добавить маленькие подписи ПОД иконками | §2 — единый navbar, вертикальные пункты, подписи 10px на mobile+desktop; sidebar удалён | §2 |
| 2 | Desktop FULLSCREEN не скроллится | §2.5 — модель скролла: root 100dvh без прокрутки страницы, main-колонка с `overflow-y:auto` | §2.5 |
| 3 | Секции хаотичны; референс не соблюдён; «Кастомные модули» не должно быть | §3 — точное дерево IA; «Кастомные модули» удалены | §3, §7 |
| 4 | «Модули» = ровно 11, у каждого toggle + кнопка окна со всеми параметрами | §3.2/§3.3 — 11 модулей, modal «окно»; карта групп | §3.2–3.3, §4 |
| 5 | «Настройки AI»: убрать «Лимиты»; 7 подразделов: LLM, Промпты, Память(all+RAG), Умный кэш, Имена, Участники и отношения, Лор чата | §3.4 — 7 подразделов; `limits` растворён | §3.4, §4 |
| 6 | LLM Провайдеры: main→fallback сверху; 1 блок = base_url+model+key; test connection | §3.4 A1 + §spec | §3.4 |
| 7 | PERMsoc: убрать 10 миселённых параметров; PERMsoc = простые хардкод-функции | §4.6 — расщепление `limits_media`; карта 10 ключей | §4.6 |
| 8 | Леха и Костик — раздельно | §4.7 — `limits_persons` → `limits_alan` + `limits_kostik`; ID Лехи/Костика по разным карточкам | §4.7 |

---

## 2. Новый навигационный каркас (single top navbar)

### 2.1. Принципы

1. **Одна навигационная поверхность** — верхний navbar (6 пунктов). Никакого sidebar,
   никакого второго меню.
2. **Иконка + подпись под ней** — вертикальная раскладка, подпись **всегда видна**
   (mobile и desktop), мелкий шрифт `--tx-tiny` ≈ `.625rem` (10px), максимум 2 строки.
3. **Единственный источник истины — hash-роут** (как в 10.5): `activeNav` — производное
   от `route`. Навигация только через `navTo()` / `openTab()`.
4. **Вложенность** — через hub-карточки внутри разделов (Модули / AI / Доступы), а не
   через отдельное меню. Глубина > 0 → нативный `BackButton` Telegram (как в 10.5).
5. **Scope-switcher остаётся** в шапке (GLOBAL / ЧАТ / ЛС) — он не nav-пункт (OD7).

### 2.2. Wireframe (desktop ≥992px)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ AdminBot · Панель управления            [аватар ЧАТ ▾] [#id] [👤 me] [ роль] [⛶]│  ← header row 1
├──────────────────────────────────────────────────────────────────────────────┤
│   📊      ℹ️         🧩         🤖          🎭            🛡                     │
│  Статус  Как это    Модули   Настройки   Функции     Доступы                  │  ← header row 2 (navbar)
│          работает             AI         PERMsoc      и Роли                   │
└──────────────────────────────────────────────────────────────────────────────┘
│                                                                                │
│   <main>  контент экрана (собственный скролл в fullscreen)                     │
│                                                                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.3. Wireframe (mobile ≤479px)

```
┌──────────────────────────────────────────────┐
│ AdminBot        [ЧАТ ▾] [me] [⛶]              │  ← header row 1 (компактно)
├──────────────────────────────────────────────┤
│  📊   ℹ️    🧩    🤖    🎭    🛡              │  ← 6 равных колонок
│Статус Как   Моду- Наст- Функ- Доступы        │  ← подписи 10px, перенос ≤2 строк
│       это    ли   рой- ции                    │
│       рабо-       ки AI PERMsoc               │
│       тает                                    │
└──────────────────────────────────────────────┘
│  <main>  контент                              │
└──────────────────────────────────────────────┘
```

### 2.4. Спецификация navbar (для @Builder, без кода)

- **Разметка:** одна `<header>`, две строки:
  - строка 1 — существующая шапка (back-fallback ←, заголовок секции, scope-switcher,
    юзер-чип, кнопка ⛶);
  - строка 2 — `<nav class="navbar-band" aria-label="Основная навигация">` с 6 кнопками.
- **Кнопка navbar** (`.nav-link`) — **вертикальный flex**:
  `flex-direction: column; align-items: center; justify-content: flex-start; gap: 2px;`
  `flex: 1 1 0; min-width: 0;` (на мобилке 6 равных колонок). Иконка `.msr` — 20–22px.
  Подпись — отдельный `<span class="nav-label">`, `font-size: var(--tx-tiny)` (10px),
  `line-height: 1.05; text-align: center; white-space: normal; overflow-wrap: anywhere;`
  до 2 строк. **Убрать** правило `.nav-link > span:not(.msr){display:none}` (сейчас ≤479px).
- **Десктоп (≥992px):** navbar по центру или слева, `gap: .25rem`, пункты `min-width: 72px`,
  подпись в одну строку, если помещается.
- **Мобилка (≤479px):** 6 равных колонок; иконка 20px; подпись 9–10px, до 2 строк;
  допускается `overflow-x:auto` как аварийный фолбэк, но **дизайн-цель — влезать без скролла**
  (6 коротких колонок; «Как это работает»/«Функции PERMsoc»/«Настройки AI»/«Доступы и Роли»
  переносятся на 2 строки).
- **Активный пункт:** `.nav-link.active` (background `--surface-3`, `font-weight:600`,
  иконка `FILL=1`) + `aria-current="page"`; на всех — `title`/`aria-label` с полным
  названием; фокус видимый.
- **Порядок и подписи (ровно как эталон/владелец):**
  1. **Статус** (`#/`, icon `monitoring`)
  2. **Как это работает** (`#/how`, `help`)
  3. **Модули** (`#/modules`, `extension`)
  4. **Настройки AI** (`#/ai`, `smart_toy`)
  5. **Функции PERMsoc** (`#/permsoc`, `admin_panel_settings`)
  6. **Доступы и Роли** (`#/access`, `supervisor_account`)

### 2.5. Удаление sidebar (полный список)

- `web/index.html`: `<aside class="sidebar ...">` (стр. ~538–571), `<div class="sidebar-backdrop">`
  (~572), кнопка `☰` (~578–579), CSS `.sidebar`/`.sidebar-backdrop`/`aside.sidebar`/`md:hidden`
  брейкпоинты (~507–529).
- `web/app.js`: состояние `sidebarOpen` (~457, 1687–1810), сбросы в `openTab/navTo`, любые
  мобильные ветки.
- **Проверить:** не осталось «мёртвых» ссылок/классов `sidebar`, `☰`, `sidebarOpen`,
  `MENU_ORDER`/`MENU_LABELS` (см. §7 T-1157r — `MENU_*` можно удалить, т.к. меню больше нет;
  оставшиеся использования заменить на NAV_ITEMS).

### 2.6. Модель скролла FULLSCREEN (фикс)

**Проблема (baseline 10.5):** `.fullscreen-mode{height:100dvh;overflow:hidden}` на корневом
`min-h-screen flex`; при `overflow:hidden` и без собственного скролла main-колонки страница
не скроллится; на десктопе скроллился **sidebar** (которого теперь нет).

**Решение — единая колонка:**

```
.root (min-h-screen flex flex-col)
  ├─ header.header-sticky           (flex: none; sticky top:0)
  └─ main.scroll-area               (flex: 1 1 auto; min-height: 0)
```

- **Обычный режим:** `body`/страница скроллится как сейчас (header `sticky`).
- **Fullscreen (`.fullscreen-mode` на root):**
  - root: `height:100dvh; overflow:hidden; display:flex; flex-direction:column;`
  - header: `flex:none; position:sticky; top:0;` (остаётся видимым);
  - `main`: `flex:1 1 auto; min-height:0; overflow-y:auto; -webkit-overflow-scrolling:touch;
    overscroll-behavior:contain;`
  - `main` — `padding-bottom: calc(1rem + env(safe-area-inset-bottom, 0px));` (safe-area).
- **Без двойных скроллбаров:** у вложенных скроллеров (`.log-panel`, `.scope-panel`,
  relations/nav-lore, модалки) добавить `overscroll-behavior: contain`, чтобы скролл не
  «протекал» на `main`.
- **Проверка:** desktop fullscreen ⛶ + mobile; длинный экран (Статус/логи/матрица) скроллится
  колесом/свайпом; header не уезжает; на корне ничего не обрезается.

---

## 3. Новая информационная архитектура (дерево экранов)

### 3.1. Верхний navbar — 6 пунктов (не меняется по количеству)

| # | Пункт | Hash | Тип | Что внутри |
|---|-------|------|-----|-----------|
| 1 | Статус | `#/` | контент | Дашборд + доступность ключей (B1) + карточка Oversight |
| 2 | Как это работает | `#/how` | контент | `content.info_how_it_works` (`#/how` — не config) |
| 3 | Модули | `#/modules` | список | **Ровно 11 модулей** (карточки: toggle + «Параметры») |
| 4 | Настройки AI | `#/ai` | hub | **Ровно 7 карточек** → под-экраны |
| 5 | Функции PERMsoc | `#/permsoc` | контент | Только простые per-chat функции (после чистки) |
| 6 | Доступы и Роли | `#/access` | hub | 3 карточки (Матрица ролей / Локальные админы / Администраторы) |

### 3.2. Дерево экранов

```
#/                         Статус (дашборд, ключи, логи, control)
  └─ #/oversight           Oversight (global-only) ★не удалять

#/how                      Как это работает (content_info)

#/modules                  Модули — РОВНО 11 карточек (каждая: toggle + «Параметры»)
  ├─ (модалка) 1  Саммаризация
  ├─ (модалка) 2  Прямые ответы
  ├─ (модалка) 3  Фактчек
  ├─ (модалка) 4  Поиск
  ├─ (модалка) 5  Транскрипт голосовых и видео
  ├─ (модалка) 6  Выжимка видео
  ├─ (модалка) 7  Скачивание медиа
  ├─ (модалка) 8  Веб-страницы
  ├─ (модалка) 9  Диагностика
  ├─ (модалка) 10 Сон
  └─ (модалка) 11 Ностальгия
  ✗ «Кастомные модули» — УДАЛЕНЫ
  ✗ «Модули (вкл/выкл)» — растворены в тумблеры
  ✗ «Реакции и Триггеры» — растворены (см. §5 Q1)

#/ai                       Настройки AI (hub) — РОВНО 7 карточек
  ├─ #/ai/llm              LLM Провайдеры (main→fallback, блоки base_url+model+key, test)
  ├─ #/ai/prompts          Промпты (все prompts_*)
  ├─ #/ai/memory           Память (вся память + RAG)
  ├─ #/ai/smart-cache      Умный кэш
  ├─ #/ai/names            Имена
  ├─ #/ai/relations        Участники и отношения
  ├─ #/ai/lore             Лор чата
  ✗ «Лимиты» (#/ai/limits) — УДАЛЕНЫ
  ✗ «Сон» (#/ai/sleep) / «Ностальгия» (#/ai/nostalgia) — перенесены в #/modules (10/11)

#/permsoc                  Функции PERMsoc (простые per-chat функции)
  Карточки: Леха · Костик · Славик · Оля · Dead page · War-алерты · Common-медиа ·
            Утренняя рассылка · Мимикрия · Словесные реакции · Админ (ID) · Мастер-рубильник

#/access                   Доступы и Роли (hub)
  ├─ #/access/roles        Матрица ролей (все 359 категорийных параметров × read/write)
  ├─ #/access/local        Локальные админы чата
  └─ #/access/admins       Администраторы/роли

#/oversight                Oversight (global admin)
```

### 3.3. Концепт «окно параметров модуля» (module param window)

- На `#/modules` рендерится **список из 11 карточек** (без промежуточного hub→экран).
  Карточка = иконка + название + короткое описание + **тумблер вкл/выкл** + кнопка
  **«Параметры»**.
- Кнопка открывает **модальное окно** (`role="dialog"`, `aria-modal="true"`):
  заголовок модуля + ✕, тело со скроллом (`max-height: ~80dvh; overflow-y:auto`),
  секции групп (generic-рендер, как у config-вкладок), футер «Закрыть».
- **Закрытие:** ✕ / клик по backdrop / Esc / нативная кнопка «назад» / системный back.
  Если окно открыто — back **сначала закрывает окно**, роут не меняется (важно для Android).
- **RBAC:** тумблер и правки внутри окна подчиняются `canEditConfig` (per-chat/global/DM);
  DM — `models.*` read-only (R10.5-2); 409-конфликт и per-chat override работают как сейчас.
- **Принцип «один дом»:** окно модуля показывает **операционные** параметры модуля
  (лимиты/флаги/reactions/content). **Промпты живут только в AI→Промпты, а модели/ключи —
  только в AI→LLM Провайдеры** (без дублирующих редакторов). Внутри окна — компактные
  чипы-ссылки «Промпт модуля → AI→Промпты», «Провайдер/модель → AI→LLM Провайдеры».

### 3.4. «Настройки AI» — 7 подразделов

| Подраздел | Hash | Группы (источник истины) |
|---|---|---|
| LLM Провайдеры | `#/ai/llm` | все `models_*` (8) + все `keys_*` (7) |
| Промпты | `#/ai/prompts` | все `prompts_*` (8) |
| Память (all memory+RAG) | `#/ai/memory` | `limits_memory`, `limits_graph`, `flags_memory`, `memory_infinite`, `reactions_memory` |
| Умный кэш | `#/ai/smart-cache` | `limits_smart_cache`, `flags_smart_cache` |
| Имена | `#/ai/names` | `limits_user_aliases` |
| Участники и отношения | `#/ai/relations` | `limits_relations`, `flags_relations` |
| Лор чата | `#/ai/lore` | `limits_lore`, `flags_lore` |

**LLM Провайдеры (layout v2, A4/A8) — блоки ПО МОДУЛЯМ, каждый = base_url+model+key+«Проверить»:**
```
[2 Прямые ответы]  direct_main              base_url · model · key  [Проверить]
[2 Прямые ответы]  direct_fallback          base_url · model · key  [Проверить]
[5 Транскрипт]     transcribe_groq          base_url · model · key  [Проверить]
[5 Транскрипт]     transcribe_openrouter    base_url · model · key  [Проверить]
[6 Выжимка видео]  video_summary_openrouter base_url · model(+fallback) · key [Проверить]
[общий]            embeddings               model · dim
[общий]            llm_guard                timeouts · retries · circuit breaker
[4 Поиск]          search_keys              tavily key · exa key     [Проверить]
[6 Выжимка видео]  media_share              media_share_secret
```
- Порядок: **сначала прямые ответы (main → fallback)**, затем остальные; блок = один модуль.
- **Один визуальный блок = base_url + model + api key** (сейчас разнесено между
  «Основные модели» / «Ключи» / «Фолбэк»).
- Кнопка **«Проверить подключение»** в КАЖДОМ блоке → `POST /api/llm/test` (A4/D4, §10.4).
- **Убрано (A8):** `keys_youtube` (proxy/cookies) → Модуль 6; `models_checkup`+`keys_betterstack`
  (BetterStack) → Модуль 9 «Диагностика».

### 3.5. «Функции PERMsoc» (после чистки)

- Только **захардкоженные простые per-chat функции**: персоны (Леха, Костик, Славик, Оля),
  dead page, war-алерты, common-медиа, утренняя рассылка, мимикрия, словесные реакции,
  «Админ (ID)», мастер-рубильник PERMsoc.
- **Леха и Костик — отдельные карточки** (§4.7).
- **Убрано:** 10 миселённых параметров (§4.6) → уехали в Модули 5/6/7.
- `flags_media` (Оля/common/mimic) **остаётся в PERMsoc** (это и есть «простые per-chat
  функции») — §5 Q8.

---

## 4. Карта размещения ВСЕХ 387 параметров

### 4.0. Принцип «один дом» (жёстко)

Каждая **группа** (`GroupSpec`) живёт ровно на **одном** экране (инвариант
`_TAB_BY_GROUP`, `test_frontend_tab_mapping`). Поэтому «смешанные» группы расщепляются.
Если ключ надо перенести — он **переезжает из группы в группу** (не дублируется).

### 4.1. База и счётчики

- Фактический дамп (read-only): **REGISTRY 387**, **GROUPS 74**, **Settings 359**.
- Из 387 записей **359 — «категорийные»** (UI-видимые), **28 — infra** (`category=None`,
  `_INFRA` + `_INFRA_ENV_ONLY`) — **в UI не показываются, остаются в `.env`**.
- Групп, реально замапленных на config-вкладки: **72** (2 группы `content_*` никогда не были
  на конфиг-вкладках — `tab=None`).

### 4.2. Rail: 28 infra-параметров (вне IA, без изменений)

`API_TOKEN, DB_PATH, MEDIA_BASE, WEBAPP_URL, COBALT_API_URL, LOCAL_BOT_API_URL,
TELEGRAM_API_FILES_DIR, DOWNLOAD_DIR, INFO_TEXT_FILE, CHECKUP_JOURNALCTL_CMD,
EMBEDDING_FALLBACK_BASE_URL, EMBEDDING_FALLBACK_API_KEY, EMBEDDING_FALLBACK_API_KEY_2,
EMBEDDING_FALLBACK_MODEL, EMBEDDING_FALLBACK_TIMEOUT_SECONDS, EMBEDDING_FALLBACK_MAX_RETRIES`
(16, `_INFRA`) + `POSTGRES_DSN, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_USER, WEB_PORT,
LOG_RING_MAX_ENTRIES, UPTIME_EVENTS_RETENTION_HOURS, SENTRY_DSN, LOGTAIL_SOURCE_TOKEN,
TELEGRAM_API_ID, TELEGRAM_API_HASH, COBALT_HTTP_PROXY` (12, `_INFRA_ENV_ONLY`).
→ **Их «дом» — `.env`/infra, как сейчас. Новой IA не касаются.**

### 4.3. «Модули» — 11 модулей (целевые группы)

| # | Модуль | id | Master toggle | Группы в окне |
|---|--------|----|---------------|---------------|
| 1 | Саммаризация | `mod_summary` | `flags.summary_enabled` | `flags_module_summary`, `flags_summary`, `limits_summary`, `reactions_summary` |
| 2 | Прямые ответы | `mod_direct` | `flags.direct_chat_botword_enabled` | `flags_module_direct`, `flags_chat_behavior`, `limits_chat`, `limits_chat_behavior`, `limits_chat_budgets`, `limits_temperature`, `reactions_chat` |
| 3 | Фактчек | `mod_factcheck` | `flags.factcheck_enabled` ⚠D1 | `flags_module_factcheck`, `limits_factcheck` |
| 4 | Поиск | `mod_search` | `flags.search_enabled` ⚠D1 | `flags_module_search`, `limits_search` |
| 5 | Транскрипт голосовых и видео | `mod_transcribe` | `flags.enable_voice_transcription` | `flags_module_transcribe`, `limits_transcribe` |
| 6 | Выжимка видео | `mod_video_summary` | `flags.video_summary_enabled` ⚠D1 | `flags_module_video_summary`, `limits_video_summary`, `limits_youtube`, `limits_youtube_proxy`, `keys_youtube` (v2/A8), `content_media` |
| 7 | Скачивание медиа | `mod_media_download` | `flags.download_enabled` | `flags_module_media_download`, `limits_media_download` |
| 8 | Веб-страницы | `mod_web` | `flags.webpage_enabled` ⚠D1 | `flags_module_web`, `limits_web` |
| 9 | Диагностика | `mod_checkup` | `flags.checkup_enabled` ⚠D1 | `flags_service` (вкл. checkup-флаг), `flags_throttle`, `limits_checkup`, `limits_service`, `limits_worker`, `models_checkup`, `keys_betterstack` |
| 10 | Сон | `mod_sleep` | `memory.dream_enabled` | `memory_dream` |
| 11 | Ностальгия | `mod_nostalgia` | `memory.nostalgia_enabled` | `memory_nostalgia` |

⚠**D1** — тумблеры модулей без единого существующего флага (см. §5 Q5 и §8).

> **Принцип «один дом» (уточнение):** окна модулей **не дублируют** промпты/модели/ключи.
> Промпты — только AI→Промпты; модели/ключи — только AI→LLM Провайдеры. Модуль показывает
> свои лимиты/флаги/reactions/content + чипы-ссылки на центральные редакторы.

### 4.4. «Настройки AI» — группы (полный список)

- **LLM Провайдеры:** `models_main`, `models_fallback`, `models_embeddings`,
  `models_llm_timeouts`, `models_llm_guard`, `models_extra_providers`,
  `models_video_summary` (7) + `keys_llm`, `keys_groq`, `keys_openrouter`, `keys_search`,
  `keys_media` (5). **Убрано (v2/A8):** `models_checkup`+`keys_betterstack` → Модуль 9;
  `keys_youtube` → Модуль 6.
- **Промпты:** `prompts_factcheck`, `prompts_search`, `prompts_checkup`, `prompts_direct_chat`,
  `prompts_summary`, `prompts_youtube`, `prompts_web`, `prompts_memory` (8).
- **Память:** `limits_memory`, `limits_graph`, **`limits_rag`** (v2/A3), `flags_memory`,
  `memory_infinite`, `reactions_memory` (6).
- **Умный кэш:** `limits_smart_cache`, `flags_smart_cache` (2).
- **Имена:** `limits_user_aliases` (1).
- **Участники и отношения:** `limits_relations`, `flags_relations` (2).
- **Лор чата:** `limits_lore`, `flags_lore` (2).

### 4.5. «Функции PERMsoc» — группы (после чистки)

`reactions_persons` (Славик, Оля), `reactions_alan` (Леха), `reactions_kostik` (Костик),
`reactions_admin`, `reactions_deadpage`, `reactions_slavik`, `reactions_war`,
`reactions_common`, `reactions_goodmorning`, `reactions_mimic`, `reactions_olya`,
`reactions_word_reactions`, `reactions_permsoc` (13 reactions) + `flags_permsoc`,
`flags_media`, `flags_permsoc_behavior` (3 flags) + `limits_alan`, `limits_kostik`,
`limits_media_permsoc`, `limits_mimic`, `limits_deadpage` (5 limits) = **21 группа**.

### 4.6. ⭐ Расщепление `limits_media` (17 → 4) — 10 миселённых ключей

Исходная группа `limits_media` (tab=permsoc, 17 ключей) расщепляется:

| Ключ (pg_key) | Title | Из | Новый дом | Новая группа |
|---|---|---|---|---|
| `limits.olya_cooldown` | Кулдаун Оли, сек | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.gif_interval` | Интервал гифки (сообщений) | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.slavic_photo_interval` | Интервал фото Славика (сообщений) | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.common_cooldown` | Общий кулдаун common-медиа, сек | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.danger_cooldown` | Кулдаун danger-медиа, сек | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.selfdev_cooldown` | Кулдаун selfdev, сек | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.work_cooldown` | Кулдаун work, сек | limits_media | **PERMsoc** | `limits_media_permsoc` |
| `limits.download_cooldown` | Кулдаун скачивания, сек | limits_media | **Модуль 7** | `limits_media_download` |
| `limits.voice_max_duration_seconds` | Макс. длительность войса, сек | limits_media | **Модуль 5** | `limits_transcribe` |
| `limits.video_transcribe_max_size_mb` | Макс. размер видео для расшифровки, МБ | limits_media | **Модуль 5** | `limits_transcribe` |
| `limits.video_transcribe_max_duration_seconds` | Макс. длительность видео для расшифровки, сек | limits_media | **Модуль 5** | `limits_transcribe` |
| `limits.video_stt_timeout_seconds` | Таймаут STT видео, сек | limits_media | **Модуль 5** | `limits_transcribe` |
| `limits.stt_groq_max_upload_mb` | Потолок загрузки Groq STT, МБ | limits_media | **Модуль 5** | `limits_transcribe` |
| `limits.stt_openrouter_max_upload_mb` | Потолок загрузки OpenRouter STT, МБ | limits_media | **Модуль 5** | `limits_transcribe` |
| `limits.video_summary_min_chars` | Мин. символов транскрипта для выжимки | limits_media | **Модуль 6** | `limits_video_summary` |
| `limits.media_share_max_mb` | Потолок публикации видео, МБ | limits_media | **Модуль 6** | `limits_video_summary` |
| `limits.media_share_ttl_seconds` | TTL опубликованного видео, сек | limits_media | **Модуль 6** | `limits_video_summary` |

→ **7 реальных PERMsoc-ключей остаются в PERMsoc**, **10 миселённых уезжают**:
1 → Модуль 7; 6 → Модуль 5; 3 → Модуль 6. Группа `limits_media` → `limits_media_permsoc`
(7), + `limits_transcribe` (6), + `limits_video_summary` (3), + `limits_media_download` (1).
**GROUPS: +3.**

### 4.7. ⭐ Расщепление «Леха и Костик»

Исходная `limits_persons` («Персонажи: Леха и Костик», 4 ключа):

| Ключ | Дом | Новая группа |
|---|---|---|
| `limits.alan_reply_interval` (Интервал ответа Лехи) | **PERMsoc → Леха** | `limits_alan` |
| `limits.alan_greeting_cooldown` (Кулдаун приветствия Лехи) | **PERMsoc → Леха** | `limits_alan` |
| `limits.alan_silence_greeting_hours` (Порог тишины Лехи) | **PERMsoc → Леха** | `limits_alan` |
| `limits.kostik_reply_probability` (Вероятность ответа Костика) | **PERMsoc → Костик** | `limits_kostik` |

Дополнительно ID/юзернейм персон:
- `reactions.alan_user_id`, `reactions.alan_username` переносятся из `reactions_persons`
  в **`reactions_alan`** (там уже `reactions.alan_greeting_dir`).
- `reactions.kostik_user_id` переносится в новую группу **`reactions_kostik`**.
- `reactions_persons` остаётся для `slavik_user_id`, `olya_user_id` (Славик/Оля уже имеют
  свои группы `reactions_slavik`/`reactions_olya` — отдельные, как и требуют).
**GROUPS: +1** (по limits) **+1** (reactions_kostik) = **+2**.

### 4.8. Прочие расщепления/переезды (для «одного дома»)

| Исходная группа | Что происходит | ΔGROUPS |
|---|---|---|
| `limits_youtube_web` (2) | расщепление: `limits_youtube` (YouTube) → Модуль 6; `limits_web` (веб) → Модуль 8 | +1 |
| `limits_cooldowns` (6) | растворение: search→`limits_search`, factcheck→`limits_factcheck`, checkup→`limits_checkup`, youtube→`limits_youtube`, webpage→`limits_web`, info→`limits_service`. Группа удаляется | −1 |
| `flags_modules` (9) | **v2:** расщепление на 7 групп `flags_module_summary`, `flags_module_direct`, `flags_module_transcribe`, `flags_smart_cache`, `flags_throttle`, `flags_module_media_download`, `flags_module_search`; `checkup_memory_metrics_enabled` → **`flags_service`** | +6 |
| `limits_chat_budgets` (11) | **v2/A3:** остаток (10) → Модуль 2; `chat_budget_rag_ratio` → **`limits_rag`** (Память) | +1 |
| `limits_chat` (26) | **v2/A3:** минус `chat_rag_dedup_overlap_ratio` → `limits_rag` | 0 |
| **D1 (A1)** | 5 master-флагов default ON; новые `flags_module_factcheck`/`flags_module_video_summary`/`flags_module_web`; `SEARCH_ENABLED`→`flags_module_search`, `CHECKUP_ENABLED`→`flags_service` | +3 |
| `flags_chat_behavior` (11) | расщепление: остаётся (7, Модуль 2) + `flags_summary` (2, Модуль 1) + `flags_permsoc_behavior` (2, PERMsoc: `alan_replies_enabled`, `dead_page_post_on_join`) | +2 |
| `reactions_summary` (2) | переезд целиком → Модуль 1 | 0 |
| `reactions_chat` (3) | переезд целиком → Модуль 2 | 0 |
| `reactions_memory` (1) | переезд целиком → AI→Память | 0 |
| `reactions_persons`/`reactions_alan`/`reactions_kostik` | см. §4.7 | +1 |
| `limits_persons` | см. §4.7 | +1 |
| `limits_media` | см. §4.6 | +3 |

**Итого ΔGROUPS (v2) = база +13** (`limits_media` +3, `limits_youtube_web` +1, `limits_persons`
+1, `limits_cooldowns` −1, `flags_modules` +6, `flags_chat_behavior` +2, reactions +1)
**+ `limits_rag` (A3) +1 + D1 (A1) +3 = +17.**

### 4.9. Итоговые счётчики каталога (v2, locked)

| Параметр | 10.5 (baseline) | **10.6 v2 (locked)** |
|---|---:|---:|
| **REGISTRY** | 387 | **392** (+5 master-флагов) |
| **Settings** | 359 | **364** (+5) |
| **GROUPS** | 74 | **91** (Δ **+17**) |
| mapped на вкладки | 72 | **89** |
| content-групп (`tab=None`) | 2 | 2 |
| infra (без категории) | 28 | 28 |

> GROUPS-дельта **+17** = базовые расщепления **+13** (`flags_modules`→7 = +6) +
> **`limits_rag` +1** (A3) + **D1 +3** (A1). Санкционировано владельцем; **ноль PG-DDL**.
> *(v1 указывал базовые +14 и flags_modules→8; v2 сводит checkup-флаг в `flags_service`,
> высвобождая слот под `limits_rag` и сохраняя locked 91.)*
>
> **v2-дополнения к §4.10 (полный дом-список новых групп):** `limits_rag` → AI→Память;
> `limits_transcribe`/`limits_video_summary`/`limits_media_download`/`limits_media_permsoc`/
> `limits_youtube`/`limits_web`/`limits_alan`/`limits_kostik`; `reactions_kostik` → PERMsoc;
> `flags_module_summary/direct/transcribe/media_download/search/factcheck/video_summary/web`,
> `flags_smart_cache`, `flags_throttle`, `flags_summary`, `flags_permsoc_behavior` → Модули/PERMsoc
> (детали — `spec.md` §4.2).

### 4.10. Полная таблица «группа → дом» (все 74 текущие группы)

| Группа (10.5) | n | Новый дом (10.6) |
|---|---:|---|
| prompts_factcheck | 1 | AI→Промпты |
| prompts_search | 1 | AI→Промпты |
| prompts_checkup | 1 | AI→Промпты |
| prompts_direct_chat | 1 | AI→Промпты |
| prompts_summary | 1 | AI→Промпты |
| prompts_youtube | 2 | AI→Промпты |
| prompts_web | 1 | AI→Промпты |
| prompts_memory | 2 | AI→Промпты |
| models_main | 2 | AI→LLM Провайдеры |
| models_fallback | 4 | AI→LLM Провайдеры |
| models_embeddings | 4 | AI→LLM Провайдеры |
| models_llm_timeouts | 5 | AI→LLM Провайдеры |
| models_llm_guard | 3 | AI→LLM Провайдеры |
| models_extra_providers | 9 | AI→LLM Провайдеры |
| models_checkup | 3 | **Модуль 9 Диагностика (v2/A8)** |
| models_video_summary | 3 | AI→LLM Провайдеры |
| keys_llm | 2 | AI→LLM Провайдеры |
| keys_groq | 1 | AI→LLM Провайдеры |
| keys_openrouter | 1 | AI→LLM Провайдеры |
| keys_search | 2 | AI→LLM Провайдеры |
| keys_betterstack | 2 | **Модуль 9 Диагностика (v2/A8)** |
| keys_youtube | 4 | **Модуль 6 Выжимка видео (v2/A8: proxy+cookies)** |
| keys_media | 1 | AI→LLM Провайдеры |
| limits_persons | 4 | **расщепление** → limits_alan (Леха) + limits_kostik (Костик) → PERMsoc |
| limits_media | 17 | **расщепление** → limits_media_permsoc (PERMsoc) + limits_transcribe (М5) + limits_video_summary (М6) + limits_media_download (М7) |
| limits_mimic | 4 | PERMsoc |
| limits_deadpage | 3 | PERMsoc |
| limits_cooldowns | 6 | **растворение** → в limits_search/factcheck/checkup/youtube/web/service |
| limits_summary | 11 | Модуль 1 Саммаризация |
| limits_search | 2 | Модуль 4 Поиск (+search_cooldown) |
| limits_factcheck | 2 | Модуль 3 Фактчек (+factcheck_cooldown) |
| limits_checkup | 2 | Модуль 9 Диагностика (+checkup_cooldown) |
| limits_youtube_web | 2 | **расщепление** → limits_youtube (М6) + limits_web (М8) |
| limits_chat | 26→25 | Модуль 2 Прямые ответы (`chat_rag_dedup_overlap_ratio` → `limits_rag`) |
| limits_chat_behavior | 4 | Модуль 2 Прямые ответы |
| limits_chat_budgets | 11→10 | Модуль 2 Прямые ответы (RAG-доля → `limits_rag`, v2/A3) |
| limits_temperature | 4 | Модуль 2 Прямые ответы |
| limits_memory | 14 | AI→Память |
| limits_graph | 29 | AI→Память |
| limits_smart_cache | 2 | AI→Умный кэш |
| limits_service | 1 | Модуль 9 Диагностика (+info_cooldown) |
| limits_user_aliases | 1 | AI→Имена |
| limits_youtube_proxy | 4 | Модуль 6 Выжимка видео |
| limits_lore | 8 | AI→Лор чата |
| limits_relations | 14 | AI→Участники и отношения |
| limits_worker | 7 | Модуль 9 Диагностика (бюджет фоновых воркеров) |
| flags_modules | 9 | **расщепление** → 7 групп (v2); `checkup_memory_metrics_enabled` → `flags_service` |
| flags_media | 7 | PERMsoc |
| flags_memory | 15 | AI→Память |
| flags_chat_behavior | 11 | **расщепление** → flags_chat_behavior (М2, 7) + flags_summary (М1, 2) + flags_permsoc_behavior (PERMsoc, 2) |
| flags_service | 2 | Модуль 9 Диагностика |
| flags_lore | 3 | AI→Лор чата |
| flags_relations | 1 | AI→Участники и отношения |
| flags_permsoc | 3 | PERMsoc |
| reactions_persons | 5 | PERMsoc (Славик, Оля; Леха/Костик → отдельные) |
| reactions_admin | 1 | PERMsoc |
| reactions_deadpage | 4 | PERMsoc |
| reactions_slavik | 3 | PERMsoc |
| reactions_alan | 1 | PERMsoc → **Леха** (вбирает alan_user_id/username) |
| reactions_war | 3 | PERMsoc |
| reactions_common | 2 | PERMsoc |
| reactions_goodmorning | 4 | PERMsoc |
| reactions_mimic | 1 | PERMsoc |
| reactions_olya | 5 | PERMsoc |
| reactions_summary | 2 | Модуль 1 Саммаризация |
| reactions_chat | 3 | Модуль 2 Прямые ответы |
| reactions_memory | 1 | AI→Память |
| reactions_word_reactions | 1 | PERMsoc |
| reactions_permsoc | 2 | PERMsoc |
| content_info | 2 | Спец: `#/how` (`tab=None`, не config) |
| content_media | 2 | Модуль 6 Выжимка видео (спец, `tab=None`) |
| memory_infinite | 1 | AI→Память |
| memory_dream | 14 | **Модуль 10 Сон** |
| memory_nostalgia | 17 | **Модуль 11 Ностальгия** |

---

## 5. Ответы на 10 вопросов PM (рекомендация @Architect)

> Формат: **вопрос → решение → обоснование (с опорой на код)**.

### Q1. «Реакции и Триггеры» (`reactions_admin/summary/chat/memory`) — куда?
**Решение: РАСТВОРИТЬ, отдельного пункта не делать.**
- `reactions_summary` (2) → **Модуль 1** (кому доступно саммари, чаты саммари).
- `reactions_chat` (3) → **Модуль 2** (regex бот-триггера, слова настроения).
- `reactions_memory` (1) → **AI→Память** (папка бэкапов).
- `reactions_admin` (1, Telegram ID админа) → **PERMsoc «Админ (ID)»** (хардкод-функция
  «особые права/реакции»).
**Почему:** navbar = 6 пунктов (владелец не просил 7-й); реакции/триггеры по своей природе
принадлежат фиче (саммари/чат/память), а не отдельной секции; так уходит «хаос секций».

### Q2. «Модули (вкл/выкл)» (`flags_modules`/`flags_service`) — растворяем? Где `flags_service`?
**Решение: ДА, растворить.**
- `flags_modules` → по модулям (см. §4.8): мастера-тумблеры + внутренние флаги модулей.
- `flags_service` (WAL checkpoint, LLM circuit breaker) → **Модуль 9 «Диагностика»**,
  блок «Служебное».
- `THROTTLE_PERSISTENT_ENABLED` → **Модуль 9** (`flags_throttle`) — общий предохранитель
  частоты smart-модулей.
**Почему:** owner: «Модули = ровно 11», значит отдельной вкладки «Модули (вкл/выкл)» быть
не может; каждый рубильник логически принадлежит модулю; служебные — к «Диагностике».

### Q3. RAG-ключи из `limits_chat_budgets` — в «Память» или в «Прямые ответы»?
**✅ РЕШЕНИЕ ВЛАДЕЛЬЦА (11.09.2026, locked): RAG → «Память» (supersedes рекомендацию ниже).**
RAG-доли бюджета (`limits.chat_rag_*`) + все RAG-ключи → `#/ai/memory`; не-RAG остаток
`limits_chat_budgets` остаётся в Модуле 2. Задача — **T-1208**.
**Прежняя рекомендация (superseded): оставить группу целиком в Модуле 2.**
**Почему (прежняя):** это **доли бюджета сборки промпта прямого чата** (`chat_budget_rag_ratio` и т.п.),
а не настройки памяти. Перенос одиночных ключей расщепил бы группу без выгоды и создал бы
два места правки одного бюджета. AI→Память получает `limits_memory`, `limits_graph`,
`flags_memory`, `memory_infinite`, `reactions_memory`. *(Не блокирует; можно пересмотреть.)*

### Q4. «Диагностика» — только чекап или ещё сервер/логи («Статус»)?
**Решение: Модуль 9 = chekup/Betterstack + служебные рубильники/лимиты/воркер-бюджет.
Сервер и логи остаются на `#/` «Статус». Без дублирования.**
- Модуль 9: `limits_checkup`, `limits_service`, `flags_service` (вкл. checkup-флаг),
  `flags_throttle`, `limits_worker`, `models_checkup`, `keys_betterstack`.
- `#/` Статус: метрики сервера, панель логов, control, доступность ключей.
**Почему:** «Диагностика» владельца — это про здоровье бота/чекап; серверная телеметрия уже
имеет полноценный экран «Статус»; дублировать нельзя (чаос).

### Q5. Тумблеры модулей без единого флага (Фактчек, Поиск, Выжимка видео, Веб, Диагностика) — новые флаги?
**Решение (рекомендация): ДОБАВИТЬ 5 новых master-флагов** (bool): `FACTCHECK_ENABLED`,
`SEARCH_ENABLED`, `VIDEO_SUMMARY_ENABLED`, `WEBPAGE_ENABLED`, `CHECKUP_ENABLED`.
→ REGISTRY **387→392**, Settings **359→364**, GROUPS **88→91** (3 новых группы:
`flags_module_factcheck`, `flags_module_video_summary`, `flags_module_web`;
`SEARCH_ENABLED`/`CHECKUP_ENABLED` вливаются в существующие module-flag-группы).
**Почему:** владелец явно требует «on/off toggle» у каждого модуля; честный master-флаг —
единственный чистый источник. Миграция безопасна: новые Settings-поля с дефолтом `True`
(поведение не меняется), ConfigCache засеет их при старте; **PG-DDL нет**.
**Альтернатива (если владелец против роста каталога):** тумблер для этих 5 модулей
показывается **disabled / «всегда вкл»** (или мапится на существующий ключ, напр. Поиск →
`flags.search_rerank_enabled` как «умный поиск», что неточно). Тогда GROUPS **88**,
REGISTRY/Settings без изменений.
👉 **DECISION POINT D1** (§8).

### Q6. «test connection» — новый backend-эндпоинт? Только global admin? Частота? Все провайдеры?
**Решение: да, новый эндпоинт; только global admin; с rate-limit; все настроенные провайдеры
по одному.
- `POST /api/llm/test` (или `POST /api/config/llm/test`) с телом `{provider: "main"|"fallback"|
  "groq"|"openrouter"|"embeddings"|...}`.
- Права: **global admin** (`requires_permission` уровня global; DM/чат-админ → 403).
- Rate-limit: серверный, напр. **не чаще 1 запроса на провайдера в 5–10с** + запрет
  параллельных; UI-кнопка `disabled` во время запроса.
- Ответ: `{ok: bool, http_status: int|null, latency_ms: int, model: str}`.
- **R17:** ключ не возвращается/не логируется; маска `{configured,last4}`; тело ошибки
  провайдера санитизируется (не эхо-ключ).
- Пробуем **по одному** провайдеру (кнопка в каждом блоке), а не «все сразу».
**Почему:** иначе «test connection» небезопасен (R17) и легко превращается в спам-вектор.
👉 **DECISION POINT D4** (§8) — подтвердить scope/права.

### Q7. Леха и Костик раздельно — только они или и Славик/Оля?
**Решение: Леха и Костик — отдельные карточки (требование). Славик и Оля — уже отдельные
(у них свои группы `reactions_slavik`/`reactions_olya`), оставляем.**
- `limits_persons` → `limits_alan` + `limits_kostik` (§4.7).
- `reactions_persons` теряет Леху/Костика; `reactions_alan` вбирает ID/username Лехи;
  новая `reactions_kostik` для ID Костика.
- Итог: **4 персоны = 4 раздельных карточки** в PERMsoc (Леха, Костик, Славик, Оля),
  плюс отдельные Dead page/War/Common/Goodmorning/Mimic/Slovo.

### Q8. `flags_media` — остаётся в PERMsoc или в модули?
**Решение: ОСТАЁТСЯ в PERMsoc.**
**Почему:** `flags_media` (Оля/common-медиа/mimic) — это ровно «захардкоженные простые
per-chat функции» по определению владельца. Ни один из 11 модулей не называется
«медиа-реакции»; раскидывать их по модулям = хаос.

### Q9. Число задач/нумерация — подтвердить T-1155…T-1199 и раунд 10.6?
**Решение: подтверждаю раунд 10.6 и T-1155…T-1199.** Уточнения:
- часть задач получает уточнённые формулировки (§7);
- при одобрении D1 добавить в §C/§D задачи на 5 master-флагов (можно в рамках T-1166);
- T-1178 (test connection backend) остаётся; контракт уточнён в `spec.md`.

### Q10. Судьба hub-экранов 10.5 — сохраняем как способ входа или показываем сразу?
**Решение: гибрид.**
- **«Модули»** — показываем **сразу список 11 модулей** (`#/modules` = рабочий экран,
  без промежуточного hub→карточка→экран; окна — модалки).
- **«Настройки AI»** и **«Доступы и Роли»** — **сохраняем hub-карточки** (7 и 3), т.к. это
  богатые под-экраны.
**Почему:** меньше кликов и ровно соответствует «кнопка открывает окно»; AI-hub сохраняет
наглядную карту 7 подразделов.

---

## 6. Impact analysis (что обязано продолжать работать)

### 6.1. TABS ↔ TAB_RULES (жёсткий инвариант)
- Обновляются **синхронно** до **19 config-вкладок**: 11 модулей (`mod_*`) + 7 AI
  (`llm_providers`, `prompts`, `memory_rag`, `smart_cache`, `people_names`, `relations`,
  `chat_lore`) + `permsoc`.
- Каждая группа — ровно на одной вкладке. Удаляются вкладки: `limits`, `memory_dream`,
  `memory_nostalgia`, `reactions_triggers`, `modules_switches`, `modules_feats`.
- `content_info`/`content_media` остаются `tab=None` (не config), как и в 10.5.

### 6.2. Hash-роутинг
- **Остаются:** `#/`, `#/how`, `#/modules`, `#/ai` (+7), `#/permsoc`, `#/access` (+3),
  `#/oversight`.
- **Удаляются:** `#/ai/limits`, `#/ai/sleep`, `#/ai/nostalgia`, `#/modules/features`,
  `#/modules/switches`, `#/modules/reactions`, `#/modules/custom`.
- **Алиасы (мягкие):** старые ссылки → логичный новый дом:
  `#/ai/limits`→`#/ai`, `#/ai/sleep`→`#/modules`, `#/ai/nostalgia`→`#/modules`,
  `#/modules/*`→`#/modules`. Неизвестный hash → `normalizeRoute` → `#/` (как сейчас).
- Модульные окна — **модалки, не роуты**. `ROUTE_PARENT`/`ROOT_ROUTES` обновляются
  (у `#/modules` больше нет детей).
- `__TMA_DEEPLINK__=false` (OD13) не меняется; back-модель 10.5 сохраняется.

### 6.3. RBAC / `canViewTab`
- Модуль-вкладки и AI-вкладки проверяются `canViewTab` по правам на группы/секции.
- Hub-видимость — через `hubVisible` (хотя бы одна карточка видна).
- **DM:** `#/permsoc` скрыт; `models.*` (`per_chat=False`) — **read-only** (R10.5-2,
  класс R10.3-1, 33 ключа); `keys.*` скрыты.
- UI **не ослабляет** серверные гейты; 403/409/422 ведут себя как сейчас.

### 6.4. Карта паритета (ничего не потеряно)

| Старое (10.5) | Новый дом |
|---|---|
| TABS `status` | `#/` Статус |
| TABS `info` | `#/how` |
| TABS `oversight` | `#/oversight` |
| TABS `llm_providers` | AI→LLM Провайдеры |
| TABS `prompts` | AI→Промпты |
| TABS `limits` | **растворён** по 11 модулям |
| TABS `memory_rag` | AI→Память |
| TABS `memory_dream` | **Модуль 10 Сон** |
| TABS `memory_nostalgia` | **Модуль 11 Ностальгия** |
| TABS `people_names` | AI→Имена |
| TABS `relations` | AI→Участники и отношения |
| TABS `reactions_triggers` | **растворён** (см. Q1) |
| TABS `modules_switches` | **растворён** в тумблеры (см. Q2) |
| TABS `modules_feats` | `#/modules` (список 11) |
| TABS `permsoc` | Функции PERMsoc (очищен) |
| TABS `access` | `#/access` (+3) |
| TABS `chat_lore` | AI→Лор чата |
| Scope-switcher (OD7) | без изменений (шапка) |
| Key-availability (OD8/B1) | без изменений (`#/`) |
| Матрица ролей (OD10) | `#/access/roles` (обновить `TAB_SECTION_ORDER`) |
| Гейты / worker budget | `#/modules` (Модуль 9) + PERMsoc |
| BYOK (`keys/own`) | AI→LLM Провайдеры |
| 409-модалка / per-chat override | все config-экраны/окна |
| Логи/control/аптайм | `#/` |
| Аватары (ленивые) | AI→Участники и отношения |
| Дерево ролей + perm-picker | `#/access/roles` |
| «Кастомные модули» (B2) | **УДАЛЕНО** (out) |

### 6.5. Ремедиации Scanner (обязательны)
- **R10.5-1** (BackButton re-init): вызвать `initBackButton()` в `ready`-хендлере под guard
  `_backOnClickBound` (в навигационном блоке).
- **R10.5-2** (DM `models.*` 422): в DM-ветке `canEditConfig` учитывать `item.per_chat`
  или скрывать/дисейблить `per_chat=False` — включить в блок LLM Провайдеры.
- **R10.5-3** (info): `/api/status/key-history` — открыт авторизованным; если владелец хочет
  ужесточить — обсудить (не в скоупе 10.6).

### 6.6. Тесты и инварианты
- `test_param_catalog`: обновить эталон GROUPS **74→88** (или 91), REGISTRY/Settings.
- `test_frontend_tab_mapping`: TABS↔TAB_RULES на 19 вкладок.
- `test_webapp_nav_disclosure_ui`, `test_webapp_rbac_ui`, `test_webapp_dm_ui`,
  `test_webapp_hubs_matrix_ui`, `test_webapp_parity_smoke`, `tests/js/routing_test.js` —
  под новую IA (sidebar отсутствует, подписи под иконками, 6 пунктов, маршруты).
- `test_progressive_tab_basic_coverage` — basic/advanced не ломается.
- Финальный контур: полный pytest (**baseline 10.5 = 4962 passed / 0 failed**), `node --check`,
  `git diff --check`.

### 6.7. Инварианты «не трогать»
- **Ноль новых PG-DDL**, SQLite v8, порядок роутеров `bot.py`, `media/` — не трогать.
- R17 (секреты только `{configured,last4}`), R16 (ID не имя).
- Эталоны промптов (`plans/docs/canon/`) — байт-в-байт, не менять.

---

## 7. Task list refinements (для `tasks.md`, без кода)

Уточнения к существующим задачам (нумерацию T-1155…T-1199 сохраняем; правки формулировок):

- **T-1155** — принять этот `design-project.md` + `spec.md` как deliverable раунда.
- **T-1157** — добавить удаление `MENU_ORDER`/`MENU_LABELS` и остатков `sidebarOpen`/`☰`.
- **T-1158** — зафиксировать: подписи 10px, вертикальный `.nav-link`, `flex:1` ×6,
  перенос ≤2 строк; **удалить** правило `.nav-link > span:not(.msr){display:none}`.
- **T-1160** — обновить `ROUTE_TO_TAB`/`TAB_TO_ROUTE`/`ROUTE_PARENT`/`ROOT_ROUTES`:
  удалить 7 маршрутов (limits/sleep/nostalgia/modules/*), добавить алиасы, модульные окна —
  не роуты.
- **T-1164** — приложить §4 (карта групп) как обязательный источник; 11 модулей = 11
  config-вкладок `mod_*`.
- **T-1166** — тумблеры: 6 существующих флагов + (при D1) 5 новых; для `per_chat=False`/DM —
  read-only.
- **T-1167** — окно = **модалка** (не роут); back закрывает окно; RBAC/409/per-chat сохранить.
- **T-1168** — Сон/Ностальгия → `#/modules` (М10/М11); удалить `#/ai/sleep`/`#/ai/nostalgia`.
- **T-1169** — удалить `reactions_triggers`/`modules_switches`/`modules_feats`; распределить
  по §4.8/Q1/Q2.
- **T-1171** — `TAB_LIMITS` удалить; `limits_cooldowns` расформировать (§4.8).
- **T-1174** — «Умный кэш» = `limits_smart_cache` + `flags_smart_cache`.
- **T-1179/T-1180** — расщепление: `limits_media`→4, `limits_persons`→2,
  `limits_youtube_web`→2, `flags_modules`→8, `flags_chat_behavior`→3, `limits_cooldowns`→0,
  `reactions_persons`/`reactions_alan`/`reactions_kostik`; GROUPS 74→88.
- **T-1182** — 6 → М5, 3 → М6, 1 → М7.
- **T-1184/T-1185** — Леха/Костик: `limits_alan`+`limits_kostik`, `reactions_kostik`.
- **T-1187** — удалить UI/роут/ROUTE_TO_TAB/REDIRECT «Кастомные модули».
- **Добавить (в рамках T-1166/T-1178):** при D1 — 5 master-флагов + группы; контракт
  `POST /api/llm/test` (§spec).

---

## 8. Decision points владельцу (нужны при апруве T-1156)

| ID | Решение | Рекомендация @Architect | Если «нет» |
|----|---------|------------------------|-----------|
| **D1** | 5 новых master-флагов (Фактчек/Поиск/Выжимка видео/Веб/Диагностика) → REGISTRY 392, Settings 364, GROUPS 91 | **Добавить** (честные тумблеры) | Тумблеры этих 5 модулей — «всегда вкл»/disabled; GROUPS 88 |
| **D2** | Модульные окна = **модалки** (не отдельные роуты); окна без промптов/моделей/ключей (они централизованы) | **Да** | Отдельные экраны + дублирование редакторов (не рекомендую) |
| **D3** | RAG-доли бюджета (`limits_chat_budgets`) остаются в Модуле 2, не в «Памяти» | **Да** | Расщепление группы + два места правки |
| **D4** | Новый эндпоинт `POST /api/llm/test`: только global admin, rate-limit, все провайдеры по одному, R17 | **Да** | Кнопку test connection отложить |
| **D5** | «Диагностика» = чекап/Betterstack + служебное; сервер/логи — на «Статус» | **Да** | Дублирование/хаос |

> **✅ РЕШЕНИЯ ВЛАДЕЛЬЦА (11.09.2026, locked):** **D1=ДА** (+5 master-флагов, **default ON**);
> **D2=ДА** (раздельно: модули ↔ AI-редакторы); **D3=ИЗМЕНЁН → RAG в «Память»** (не Модуль 2);
> **D4=ДА, per-block test**; **D5=сервер/логи на «Статус»** + настройки logs/BetterStack/checkup →
> «Диагностика». Доп.: A6/A7 emoji→icon, A8 proxy/cookies → «Модули», A9 эксклюзивный аккордеон.
> Детали — `tasks.md` §8. Ревизия docs → v2 — **T-1200**.

---

## 9. Вопросы владельцу (новые, сверх §5) — ✅ ЗАКРЫТЫ 11.09.2026

> Все закрыты закреплёнными ответами (см. блок в §8): D2 — раздельно, D4 — per-block,
> D1 — ДА. Открытых вопросов нет.

1. **D2 (уточнение):** окна модулей должны показывать промпт модуля? Мы предлагаем держать
   промпты только в AI→Промпты и давать из окна ссылку-чип. Если хотите промпт прямо в окне —
   скажите, но тогда появится второй редактор того же промпта.
2. **D4 (уточнение):** тестировать только LLM-провайдеров (main/fallback/Groq/OpenRouter/
   embeddings) или также ключи поиска (Exa/Tavily)/Betterstack?
3. **D1:** допустим ли рост каталога +5 записей ради честных тумблеров? (REGISTRY/Settings —
   не PG-DDL, безопасно.)

---

## 10. Ревизия v2 — закреплённые ответы владельца A1–A9 (11.09.2026)

> Источник: `tasks.md` §8.1 (locked). Ниже — точные контракты; `spec.md` v2 — источник истины.

### 10.1. A1 — тумблеры реально работают; 5 master-флагов default ON
- Новые Settings/`_FLAGS` (bool, default `True`): `FACTCHECK_ENABLED`, `SEARCH_ENABLED`,
  `VIDEO_SUMMARY_ENABLED`, `WEBPAGE_ENABLED`, `CHECKUP_ENABLED`.
- Группы: `flags_module_factcheck`, `flags_module_video_summary`, `flags_module_web` (NEW);
  `SEARCH_ENABLED` → `flags_module_search`; `CHECKUP_ENABLED` → `flags_service`.
- **Гейты (код):** `handlers/factcheck.py`, `handlers/search.py`, `handlers/web.py`,
  `handlers/checkup.py` — при OFF `return UNHANDLED`; `handlers/youtube.py` — только summary-ветки
  (transcript продолжает работать). Порядок роутеров `bot.py` не меняется.
- Каталог: REGISTRY **392**, Settings **364**, GROUPS **91** (см. §4.9).

### 10.2. A2 — «один дом»
- Модули показывают только операционные группы (flags/limits/reactions/content) + чипы-ссылки.
- Промпты — только AI→Промпты; модели/ключи — только AI→LLM Провайдеры (исключения — §10.5).

### 10.3. A3/D3 — RAG → «Память» (точный список и «group split»)
Переносим **ровно 2 ключа** (остальные RAG-ключи уже в `flags_memory`/`limits_graph`/
`reactions_memory`):

| pg_key | Settings | Из (было) | Стало |
|---|---|---|---|
| `limits.chat_budget_rag_ratio` | `CHAT_BUDGET_RAG_RATIO` | `limits_chat_budgets` (Модуль 2) | **`limits_rag`** → `memory_rag` |
| `limits.chat_rag_dedup_overlap_ratio` | `CHAT_RAG_DEDUP_OVERLAP_RATIO` | `limits_chat` (Модуль 2) | **`limits_rag`** → `memory_rag` |

**Split:** `limits_chat_budgets` 11→**10** (остаётся в Модуле 2), `limits_chat` 26→**25**,
**NEW `limits_rag`** (2 ключа) в `memory_rag`. GROUPS **+1**.

### 10.4. A4/D4 — provider-блоки ПО МОДУЛЯМ + per-block test
- Блоки в `#/ai/llm` (порядок): `direct_main` → `direct_fallback` → `transcribe_groq` →
  `transcribe_openrouter` → `video_summary_openrouter` → `embeddings` → `llm_guard` →
  `search_keys` → `media_share` (точный состав pg-ключей — `spec.md` §6.2).
- Каждый блок: `base_url` + `model` + `api_key` + кнопка «Проверить». `keys.openrouter_api_key`
  общий для двух блоков (единый pg-ключ, R17-маска).
- `POST /api/llm/test`: global admin; body `{block, base_url, model, api_key}`; 200 `ok:true`
  либо `ok:false`+санитизированный `error`; rate-limit ≥5с; ключ не возвращается/не логируется.

### 10.5. A5/A8 — сервер/логи на «Статус»; proxy/cookies → Модули; diagnostics → «Диагностика»
- `keys_youtube` (proxy url/user/pass + cookies) → **Модуль 6**. `limits_youtube_proxy` — уже там.
- `models_checkup` + `keys_betterstack` (+ `limits_checkup`/`limits_service`/`flags_service`/
  `flags_throttle`/`limits_worker`) → **Модуль 9 «Диагностика»**.
- Метрики сервера, панель логов/control, key-availability → **`#/` «Статус»** (не переносятся).
- «Настройки AI» остаются **7** подразделов («Диагностика» — модуль, не AI-подраздел).

### 10.6. A6/A7 — emoji → Material-иконка
- Использовать существующие `ICONS`/`iconGlyph` (без новых PUA — шрифт-субсет не трогаем).
- `#/how`: `iconGlyph('help')` вместо `ℹ️`. Матрица `#/access/roles`:
  `admin_panel_settings` (заголовок), `restart_alt` (обновить), `manage_accounts` (perm-picker).
- `content.info_how_it_works` (данные) не меняется.

### 10.7. A9 — «Доступы и роли»: эксклюзивный аккордеон
- State `accessOpen ∈ {null,'roles','local','admins'}`; открыт **ровно один**;
  `aria-expanded`/`aria-controls`; роут `#/access/*` синхронизирует единственную открытую секцию.

---

*Design v2 сгенерирован @Architect 11.09.2026 (Step 2, раунд 10.6, задача T-1200). 0 кода.*
*✅ Апрув владельца получен (T-1156); A1–A9 закреплены; готово к @Builder.*
