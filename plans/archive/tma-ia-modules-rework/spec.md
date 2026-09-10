# Spec: TMA IA rework — единый navbar, Модули (11), Настройки AI (7), PERMsoc (чистый)

> **Статус:** 🟢 **SPEC v2** (11.09.2026, Step 2 повторно / @Architect, задача **T-1200**).
> **Фича:** `plans/features/tma-ia-modules-rework/` (раунд **10.6**).
> **Компаньон:** `design-project.md` **v2** (обоснования, wireframes, карта всех параметров,
> ответы, §10 «Ревизия v2 — A1–A9»).
> **🟢 HARD GATE (T-1156) ПРОЙДЕН**; ответы владельца **A1–A9** закреплены и внесены в v2.
> **0 кода** здесь — только контракты, таблицы, AC.
> **v1 → v2 внесено:** A1 (честные тумблеры + 5 master-флагов ON), A2 («один дом»),
> A3 (RAG → «Память», группа `limits_rag`), A4 (блоки провайдеров ПО МОДУЛЯМ + per-block test),
> A5/A8 (сервер/логи на «Статус»; proxy/cookies → «Модули»; logs/BetterStack/checkup → «Диагностика»),
> A6/A7 (emoji → Material-иконка), A9 (эксклюзивный аккордеон «Доступы и роли»).
> **Каталог (locked):** REGISTRY **392** / GROUPS **91** / Settings **364** / mapped **89**.

---

## 1. Scope

Раздел «Настройки/IA» мини-аппа TMA: навигация, разделы, раскладка параметров каталога.
**В скоупе:**
- `web/index.html`, `web/app.js` — nav shell, 11 модулей + модалки, 7 подразделов AI,
  блоки провайдеров, proxy/cookies/diagnostics релокация, emoji→icon, аккордеон «Доступы»;
- `services/param_catalog.py` — расщепления групп, новая `limits_rag`, 5 master-флагов,
  `TAB_RULES`/`CONFIG_TAB_TITLES`/`_TAB_BY_GROUP` (91 группа, 89 mapped);
- `config/settings.py` — 5 новых master-флагов (bool, default `True`);
- `handlers/factcheck.py`, `handlers/search.py`, `handlers/youtube.py`, `handlers/web.py`,
  `handlers/checkup.py` — **новые runtime-гейты** 5 master-флагов (A1: тумблеры реальны),
  без смены порядка роутеров `bot.py`;
- `web/api/*` — **только новый** `POST /api/llm/test` (D4/A4);
- `tests/*` — маркеры/инварианты.

**Вне скоупа:** смена порядка роутеров `bot.py`, DDL, движок бота, промпт-эталоны, `media/`.

---

## 2. Контракт навигационного каркаса

### 2.1. DOM-структура (контракт)
```
<div id="app">
  <div class="app-shell" :class="{ 'fullscreen-mode': isFullscreen }">
     <header class="main-header header-sticky">
        row1: [← fallback] [текущий заголовок] [scope-switcher] [me-чип] [⛶]
        row2: <nav class="navbar-band" aria-label="Основная навигация">
                <button class="nav-link" v-for="n in navItems"
                        :class="{active: activeNav===n.id}"
                        :aria-current="activeNav===n.id ? 'page' : null"
                        :title="n.label" @click="navTo(n.route)">
                   <span class="msr nav-icon">{{ iconGlyph(n.icon) }}</span>
                   <span class="nav-label">{{ n.label }}</span>
                </button>
              </nav>
     </header>
     <main class="scroll-area"> ... контент ... </main>
  </div>
</div>
```
- `navItems` = `NAV_ITEMS` (6 пунктов). **Без** `☰`, **без** `<aside class="sidebar">`.
- `activeNav` — производное от `route` (как в 10.5).

### 2.2. CSS-контракт navbar
- `.navbar-band`: `display:flex; align-items:stretch; gap:.25rem; width:100%; overflow-x:auto;`
- `.nav-link`: `display:flex; flex-direction:column; align-items:center; justify-content:flex-start;
  gap:2px; flex:1 1 0; min-width:0; padding:.3rem .25rem; white-space:normal;`
- `.nav-icon` (`.msr`): `font-size:20px; line-height:1;`
- `.nav-label`: `font-size:var(--tx-tiny)` (≈10px); `line-height:1.05; text-align:center;
  overflow-wrap:anywhere;` (максимум 2 строки).
- `.nav-link.active`: фон `--surface-3`, `font-weight:600`, иконка `FILL=1`.
- **УДАЛИТЬ** правило `@media (max-width:479px){ .nav-link > span:not(.msr){display:none} }`.
- Breakpoints: desktop ≥992px (пункты `min-width:72px`, подпись в 1–2 строки),
  mobile ≤479px (6 равных колонок; аварийный `overflow-x:auto` допустим).

### 2.3. Модель скролла (контракт)
- `.app-shell`: `display:flex; flex-direction:column; min-height:100vh;`
- `header.header-sticky`: `position:sticky; top:0; z-index:40; flex:none;`
- `.scroll-area` (main): `flex:1 1 auto; min-height:0; padding:1rem;`
- `.fullscreen-mode`:
  - `.app-shell.fullscreen-mode { height:100dvh; overflow:hidden; }`
  - `.fullscreen-mode .scroll-area { overflow-y:auto; -webkit-overflow-scrolling:touch;
    overscroll-behavior:contain; padding-bottom:calc(1rem + env(safe-area-inset-bottom,0px)); }`
- Вложенные скроллеры (`.log-panel`, `.scope-panel`, relations/lore, **модалки модулей**):
  `overscroll-behavior:contain;` (нет скролл-чейнинга/двойных барров).
- **AC:** desktop fullscreen ⛶ прокручивает длинный экран; header остаётся; нет обрезки.

### 2.4. Удаление sidebar (обязательный список)
- `index.html`: `<aside class="sidebar ...">`, `.sidebar-backdrop`, кнопка `☰`, CSS
  `.sidebar/.sidebar-backdrop/aside.sidebar` и `md:hidden`-ветки.
- `app.js`: `sidebarOpen`, его сбросы, мобильные ветки; `MENU_ORDER`/`MENU_LABELS` (мёртвые
  после удаления меню — удалить; тесты обновить); мёртвый `setMenu` (R10.5-6).
- **AC:** grep `sidebar|☰|sidebarOpen|MENU_ORDER` в `web/` — пусто.

---

## 3. Маршруты (hash)

### 3.1. Целевые роуты
| Hash | Экран | Тип |
|---|---|---|
| `#/` | Статус (сервер, логи/control-панель, key-availability, карточка Oversight) | контент |
| `#/oversight` | Oversight | контент (global) |
| `#/how` | Как это работает | контент |
| `#/modules` | Модули (11 карточек) | список |
| `#/ai` | Настройки AI (hub 7) | hub |
| `#/ai/llm` | LLM Провайдеры | config |
| `#/ai/prompts` | Промпты | config |
| `#/ai/memory` | Память | config |
| `#/ai/smart-cache` | Умный кэш | config |
| `#/ai/names` | Имена | config |
| `#/ai/relations` | Участники и отношения | config/custom |
| `#/ai/lore` | Лор чата | config/custom |
| `#/permsoc` | Функции PERMsoc | config |
| `#/access` | Доступы и Роли (hub 3) | hub |
| `#/access/roles` | Матрица ролей (эксклюзивный аккордеон) | контент |
| `#/access/local` | Локальные админы (тот же аккордеон) | контент |
| `#/access/admins` | Администраторы (тот же аккордеон) | контент |

### 3.2. Удаляемые роуты + алиасы
| Удаляем | Куда ведём (алиас) |
|---|---|
| `#/ai/limits` | `#/ai` |
| `#/ai/sleep` | `#/modules` |
| `#/ai/nostalgia` | `#/modules` |
| `#/modules/features` | `#/modules` |
| `#/modules/switches` | `#/modules` |
| `#/modules/reactions` | `#/modules` |
| `#/modules/custom` | `#/modules` (UI «Кастомные модули» удалён) |

- `ROUTE_TO_TAB`, `TAB_TO_ROUTE`, `ROUTE_PARENT`, `ROOT_ROUTES` обновить; `#/modules` —
  только корневой (без детей). Неизвестный hash → `normalizeRoute` → `#/` (как сейчас).
- **Модульные окна — модалки, не роуты.** При открытом окне back (нативный или in-app)
  **закрывает окно** (роут не меняется). Контракт закрытия — §12.
- `#/access/roles|local|admins` — **не разворачивают несколько секций**: роут задаёт
  единственную открытую секцию аккордеона (§14).

---

## 4. TABS ↔ TAB_RULES (контракт, **19 config-вкладок**)

### 4.1. Новые id вкладок
`mod_summary, mod_direct, mod_factcheck, mod_search, mod_transcribe, mod_video_summary,
mod_media_download, mod_web, mod_checkup, mod_sleep, mod_nostalgia,
llm_providers, prompts, memory_rag, smart_cache, people_names, relations, chat_lore, permsoc`.

`CONFIG_TAB_TITLES`: `mod_summary`="Саммаризация", `mod_direct`="Прямые ответы",
`mod_factcheck`="Фактчек", `mod_search`="Поиск", `mod_transcribe`="Транскрипт голосовых и видео",
`mod_video_summary`="Выжимка видео", `mod_media_download`="Скачивание медиа",
`mod_web`="Веб-страницы", `mod_checkup`="Диагностика", `mod_sleep`="Сон",
`mod_nostalgia`="Ностальгия", `llm_providers`="LLM Провайдеры", `prompts`="Промпты",
`memory_rag`="Память", `smart_cache`="Умный кэш", `people_names`="Имена",
`relations`="Участники и отношения", `chat_lore`="Лор чата", `permsoc`="Функции PERMsoc".
**Удаляются как config-вкладки:** `limits`, `memory_dream`, `memory_nostalgia`,
`reactions_triggers`, `modules_switches`, `modules_feats`.

### 4.2. TAB_RULES: группа → вкладка (источник истины)
```
mod_summary:        flags:[flags_module_summary, flags_summary]
                    limits:[limits_summary]  reactions:[reactions_summary]
mod_direct:         flags:[flags_module_direct, flags_chat_behavior]
                    limits:[limits_chat, limits_chat_behavior, limits_chat_budgets, limits_temperature]
                    reactions:[reactions_chat]
mod_factcheck:      flags:[flags_module_factcheck]  limits:[limits_factcheck]
mod_search:         flags:[flags_module_search]     limits:[limits_search]
mod_transcribe:     flags:[flags_module_transcribe] limits:[limits_transcribe]
mod_video_summary:  flags:[flags_module_video_summary]
                    limits:[limits_video_summary, limits_youtube, limits_youtube_proxy]
                    keys:[keys_youtube]           content:[content_media]
mod_media_download: flags:[flags_module_media_download] limits:[limits_media_download]
mod_web:            flags:[flags_module_web]        limits:[limits_web]
mod_checkup:        flags:[flags_service, flags_throttle]
                    limits:[limits_checkup, limits_service, limits_worker]
                    models:[models_checkup]         keys:[keys_betterstack]
mod_sleep:          memory:[memory_dream]
mod_nostalgia:      memory:[memory_nostalgia]
llm_providers:      models:[models_main, models_fallback, models_embeddings,
                            models_llm_timeouts, models_llm_guard,
                            models_extra_providers, models_video_summary]
                    keys:[keys_llm, keys_groq, keys_openrouter, keys_search, keys_media]
prompts:            prompts: all
memory_rag:         limits:[limits_memory, limits_graph, limits_rag]
                    flags:[flags_memory]  memory:[memory_infinite]  reactions:[reactions_memory]
smart_cache:        limits:[limits_smart_cache] flags:[flags_smart_cache]
people_names:       limits:[limits_user_aliases]
relations:          limits:[limits_relations] flags:[flags_relations]
chat_lore:          limits:[limits_lore] flags:[flags_lore]
permsoc:            reactions:[reactions_persons, reactions_admin, reactions_deadpage,
                               reactions_slavik, reactions_alan, reactions_kostik,
                               reactions_war, reactions_common, reactions_goodmorning,
                               reactions_mimic, reactions_olya, reactions_word_reactions,
                               reactions_permsoc]
                    flags:[flags_permsoc, flags_media, flags_permsoc_behavior]
                    limits:[limits_alan, limits_kostik, limits_media_permsoc,
                            limits_mimic, limits_deadpage]
```
- `content_info` → `tab=None` (спец, `#/how`); `content_media` → `tab=None` (спец, окно
  Модуля 6) — **как в 10.5** (content не на config-вкладках).
- `_TAB_BY_GROUP` строится без `ValueError` (нет дублей); **ровно 19 вкладок**.
- **Каждая группа — ровно на одной вкладке.** Счётчики: GROUPS **91**, mapped **89**,
  content `tab=None` **2**, infra **28**, REGISTRY **392**, Settings **364**.
- `TABS` (фронт) зеркалит то же (см. §4.4). `llm_providers.sections` — 9 блоков (§6.2).

### 4.3. `TAB_SECTION_ORDER` (матрица ролей)
Новый порядок (19): 11 `mod_*` → `llm_providers` → `prompts` → `memory_rag` → `smart_cache` →
`people_names` → `relations` → `chat_lore` → `permsoc`.

### 4.4. Фронтовый `TABS` (зеркало) — новые/удаляемые записи
- Добавить 11 записей `mod_*` (`type:'config'`, `menu:'modules'`, `sources` = §4.2,
  `icon` → Material-имя в `TAB_ICON`), 1 запись `smart_cache` (menu `'ai'`).
- Обновить `memory_rag` (добавить `limits_rag`), `llm_providers` (убрать `models_checkup`,
  `keys_betterstack`, `keys_youtube`; `sections` → 9 блоков §6.2).
- Удалить записи `limits`, `memory_dream`, `memory_nostalgia`, `reactions_triggers`,
  `modules_switches`, `modules_feats` (последняя заменяется списком 11 модулей, `type:'modules'`).
- `chat_lore`/`relations` остаются кастомными типами (config-часть через `groupedForTab`).
- `TAB_ICON`: добавить Material-имена для всех `mod_*`/`smart_cache`; `TAB_SECTION_ORDER` — §4.3.

---

## 5. Модули (11) — контракт

| # | Название | id | Master toggle (pg_key → группа) | Группы окна |
|----|----------|----|-------------------------------|-------------|
| 1 | Саммаризация | `mod_summary` | `flags.summary_enabled` (`flags_module_summary`) | flags_module_summary, flags_summary, limits_summary, reactions_summary |
| 2 | Прямые ответы | `mod_direct` | `flags.direct_chat_botword_enabled` (`flags_module_direct`) | flags_module_direct, flags_chat_behavior, limits_chat, limits_chat_behavior, limits_chat_budgets, limits_temperature, reactions_chat |
| 3 | Фактчек | `mod_factcheck` | `flags.factcheck_enabled` ⭐NEW (`flags_module_factcheck`) | flags_module_factcheck, limits_factcheck |
| 4 | Поиск | `mod_search` | `flags.search_enabled` ⭐NEW (`flags_module_search`) | flags_module_search, limits_search |
| 5 | Транскрипт голосовых и видео | `mod_transcribe` | `flags.enable_voice_transcription` (`flags_module_transcribe`) | flags_module_transcribe, limits_transcribe |
| 6 | Выжимка видео | `mod_video_summary` | `flags.video_summary_enabled` ⭐NEW (`flags_module_video_summary`) | flags_module_video_summary, limits_video_summary, limits_youtube, limits_youtube_proxy, **keys_youtube**, content_media (спец) |
| 7 | Скачивание медиа | `mod_media_download` | `flags.download_enabled` (`flags_module_media_download`) | flags_module_media_download, limits_media_download |
| 8 | Веб-страницы | `mod_web` | `flags.webpage_enabled` ⭐NEW (`flags_module_web`) | flags_module_web, limits_web |
| 9 | Диагностика | `mod_checkup` | `flags.checkup_enabled` ⭐NEW (`flags_service`) | flags_service, flags_throttle, limits_checkup, limits_service, limits_worker, **models_checkup**, **keys_betterstack** |
| 10 | Сон | `mod_sleep` | `memory.dream_enabled` (`memory_dream`) | memory_dream |
| 11 | Ностальгия | `mod_nostalgia` | `memory.nostalgia_enabled` (`memory_nostalgia`) | memory_nostalgia |

⭐NEW — 5 master-флагов (A1), default `True`, реально гейтят выполнение (§5.3).

### 5.1. DOM/CSS контракт карточки модуля
```
<div class="module-list" role="list">
  <article class="module-card" v-for="m in modules" role="listitem" :data-mod="m.id">
    <span class="msr module-icon" aria-hidden="true">{{ iconGlyph(m.icon) }}</span>
    <div class="module-meta">
      <div class="module-title">{{ m.title }}</div>
      <div class="module-sub">{{ m.subtitle }}</div>
    </div>
    <label class="module-toggle">
      <input type="checkbox" class="sr-only peer" :checked="m.enabled"
             :disabled="!canEditConfig(m.toggleKey)"
             @change="toggleModule(m, $event.target.checked)">
      <span class="module-track" aria-hidden="true"></span>
      <span class="sr-only">Включить модуль {{ m.title }}</span>
    </label>
    <button class="btn-ghost module-params-btn" @click="openModule(m)">Параметры</button>
  </article>
</div>
```
- `.module-list { display:grid; gap:.75rem; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }`
- `.module-card { display:flex; align-items:center; gap:.75rem; ... }`
- `.module-toggle .module-track` — визуальный тумблер (существующий паттерн gate-toggle).
- Тумблер показывает состояние master-флага; disabled при `!canEditConfig(toggleKey)` (DM: `models.*`/`keys.*` read-only).

### 5.2. DOM/CSS контракт окна параметров (модалка)
```
<div class="modal-backdrop" @click.self="closeModule()">
  <div class="modal-card card-solid" role="dialog" aria-modal="true"
       :aria-labelledby="'mod-title-' + openModuleId">
    <header class="modal-head">
      <span class="msr">{{ iconGlyph(openModuleIcon) }}</span>
      <h2 class="modal-title" :id="'mod-title-' + openModuleId">{{ openModuleTitle }}</h2>
      <button class="modal-close" @click="closeModule()" aria-label="Закрыть">✕</button>
    </header>
    <div class="modal-body">   <!-- generic-рендер групп модуля (§4.2) -->
      ... groupedForTab(moduleTabId) ...
    </div>
    <footer class="modal-footer">
      <button class="btn-ghost" @click="closeModule()">Закрыть</button>
    </footer>
  </div>
</div>
```
- `.modal-body { max-height:80dvh; overflow-y:auto; overscroll-behavior:contain; }`
- **Закрытие:** ✕ / backdrop / Esc / нативный back / системный back. При открытом окне
  back **сначала закрывает окно**, роут не меняется (важно для Android). Реализация:
  перехват в `goBack()` и `BackButton.onClick` при `openModuleId != null`.
- **RBAC:** правки внутри окна подчиняются `canEditConfig`; DM — `models.*`/`keys.*`
  read-only (R10.5-2); 409-конфликт/per-chat override — как сейчас.
- **Один дом (A2/D2):** окно показывает **только операционные** группы модуля. Промпты —
  только AI→Промпты; модели/ключи — только AI→LLM Провайдеры, **кроме** `keys_youtube`
  (A8, живёт в Модуле 6) и `models_checkup`/`keys_betterstack` (A5/A8, живут в Модуле 9).
  Внутри окна — чипы-ссылки «Промпт модуля → AI→Промпты», «Провайдер/модель → AI→LLM».

### 5.3. Честные гейты 5 master-флагов (A1) — точки чтения
Все — через `hot.get("<pg_key>", settings.<FIELD>)` в начале соответствующего пути;
выключено → прежний `return UNHANDLED` / пропуск (порядок роутеров `bot.py` не меняется):

| Флаг (pg_key / Settings) | Гейт-точка | Поведение OFF |
|---|---|---|
| `flags.factcheck_enabled` / `FACTCHECK_ENABLED` | `handlers/factcheck.py` (entry) | `return UNHANDLED` (как выключенный модуль) |
| `flags.search_enabled` / `SEARCH_ENABLED` | `handlers/search.py` (entry) | `return UNHANDLED` |
| `flags.video_summary_enabled` / `VIDEO_SUMMARY_ENABLED` | `handlers/youtube.py` — ветки **summary** (YouTube+media), НЕ transcript | summary-пути → `UNHANDLED`; «транскрипт» работает |
| `flags.webpage_enabled` / `WEBPAGE_ENABLED` | `handlers/web.py` (entry) | `return UNHANDLED` |
| `flags.checkup_enabled` / `CHECKUP_ENABLED` | `handlers/checkup.py` (entry, оба хендлера) | `return UNHANDLED` |

- Существующие мастер-тумблеры (1/2/5/7/10/11) — без изменений семантики.
- **AC:** при OFF модуль не отвечает, при ON поведение байт-в-байт прежнее.

---

## 6. Настройки AI (7) — контракт

- `#/ai` hub: **ровно 7** карточек (LLM Провайдеры, Промпты, Память, Умный кэш, Имена,
  Участники и отношения, Лор чата). «Лимиты»/«Сон»/«Ностальгия»/«Диагностика» — **не** в AI.
- Группы — §4.2.

### 6.1. RAG → «Память» (A3/D3) — точный список и расщепление
Переносятся **ровно 2 ключа** (все остальные RAG-ключи уже в памяти):

| pg_key | Settings | Title RU | Из группы (было) | Вкладка была | В группу (стало) |
|---|---|---|---|---|---|
| `limits.chat_budget_rag_ratio` | `CHAT_BUDGET_RAG_RATIO` | Доля бюджета: RAG | `limits_chat_budgets` (Модуль 2) | `mod_direct` | **`limits_rag`** → `memory_rag` |
| `limits.chat_rag_dedup_overlap_ratio` | `CHAT_RAG_DEDUP_OVERLAP_RATIO` | Порог дедупа RAG ↔ фон, доля | `limits_chat` (Модуль 2) | `mod_direct` | **`limits_rag`** → `memory_rag` |

**«Resulting group split»:**
- `limits_chat_budgets` (11 → **10**): остаются `flags.chat_context_budgets_enabled` +
  9 limits (`chat_context_budget_tokens`, `chat_budget_map/global/thread/target/anchors/
  branch/response/reserve_ratio`). Вкладка `mod_direct` (Модуль 2).
- `limits_chat` (26 → **25**): минус `chat_rag_dedup_overlap_ratio`.
- **NEW GroupSpec `limits_rag`** (category `limits`, title_ru «Память: RAG-бюджет и дедуп»,
  2 ключа) → вкладка `memory_rag`. **GROUPS +1** (74→…→91, §8).

Уже в памяти (не переносим): `flags.graph_rag_enabled`, `flags.chat_rag_rerank_enabled`,
`flags.graph_mmr_enabled` (`flags_memory`); `limits.summary_rag_l2_limit`,
`limits.summary_rag_l3_limit`, `limits.graph_rag_facts_limit`,
`limits.graph_rag_context_max_chars` (`limits_graph`); `reactions.memory_backup_dir`
(`reactions_memory`).

### 6.2. «LLM Провайдеры» — блоки ПО МОДУЛЯМ (A4/D4)
Каждый блок = **`base_url` + `model` + `api key`** + кнопка **«Проверить»**. Порядок витрины —
как в таблице; при равном модуле **main перед fallback**.

| # | block id | Модуль(и) | base_url (pg) | model (pg) | api key (pg) |
|---|---|---|---|---|---|
| 1 | `direct_main` | 2 Прямые ответы (+1,3,4,8,10,11 — общий LLM) | `models.llm_base_url` | `models.llm_model_name` | `keys.llm_api_key` |
| 2 | `direct_fallback` | 2 Прямые ответы (фолбэк) | `models.llm_fallback_base_url` | `models.llm_fallback_model` | `keys.llm_fallback_api_key` |
| 3 | `transcribe_groq` | 5 Транскрипт | `models.groq_base_url` | `models.groq_transcribe_model` | `keys.groq_api_key` |
| 4 | `transcribe_openrouter` | 5 Транскрипт (фолбэк STT) | `models.openrouter_base_url` | `models.openrouter_transcribe_model` | `keys.openrouter_api_key` |
| 5 | `video_summary_openrouter` | 6 Выжимка видео | `models.openrouter_base_url` | `models.video_primary_model` (+`models.video_fallback_model`) | `keys.openrouter_api_key` |
| 6 | `embeddings` | 3 Фактчек, 4 Поиск, Память | — | `models.embedding_model_name`, `models.embedding_dim` | — |
| 7 | `llm_guard` | общий | — | `models_llm_timeouts` + `models_llm_guard` | — |
| 8 | `search_keys` | 4 Поиск | — | — | `keys.tavily_api_key`, `keys.exa_api_key` |
| 9 | `media_share` | 6 Выжимка видео (`/media/`) | — | — | `keys.media_share_secret` |

- **Убрано из LLM Провайдеров (A8):** `keys_youtube` (proxy URL/user/pass + cookies) →
  Модуль 6; `models_checkup` + `keys_betterstack` → Модуль 9 «Диагностика».
- Где два блока делят один ключ (`transcribe_openrouter` и `video_summary_openrouter` →
  `keys.openrouter_api_key`) — это **один pg-ключ**, редактируемый в любом из блоков
  (единый источник истины; сохранение обновляет значение для обоих). R17-маска
  `{configured,last4}`; ключ в ответах теста не возвращается.

DOM/CSS:
```
<section class="prov-block" v-for="b in providerBlocks" :data-block="b.id">
  <header class="prov-head">
     <span class="prov-title">{{ b.title }}</span>
     <span class="prov-modules">{{ b.moduleLabels.join(' · ') }}</span>
  </header>
  <div class="prov-row" v-for="f in b.fields">
     <label class="prov-label">{{ f.label }}</label>
     <input class="field prov-input" :type="f.secret ? 'text' : 'text'"
            v-model="b.draft[f.key]" :placeholder="f.placeholder"
            :disabled="!canEditConfig(f.key)">
  </div>
  <button class="btn-accent prov-test-btn" :disabled="b.testing"
          @click="testBlock(b)">Проверить</button>
  <span class="prov-test-status" :class="b.result.ok ? 'is-ok' : 'is-err'"
        v-if="b.result">{{ b.result.text }}</span>
</section>
```
- `.prov-block { border:var(--card-border); border-radius:var(--radius-lg); padding:.75rem; }`
- `.prov-test-btn:disabled { opacity:.5; cursor:not-allowed; }`
- `.prov-test-status.is-ok { color:#4ade80; } .is-err { color:#f87171; }`

### 6.3. `POST /api/llm/test` (D4/A4) — контракт backend
```
POST /api/llm/test
auth:  requires_permission(global admin)            → иначе 403
body:  {
         "block": "direct_main"|"direct_fallback"|"transcribe_groq"|
                  "transcribe_openrouter"|"video_summary_openrouter"|
                  "embeddings"|"search_keys"|"checkup_betterstack",
         "base_url": "<строка из блока>",
         "model":    "<строка из блока>",
         "api_key":  "<строка из блока>"
       }
resp:  200 { "ok": true,  "http_status": 200, "latency_ms": int, "model": str }
       200 { "ok": false, "http_status": int|null, "latency_ms": int, "model": str,
             "error": "<санитизированное сообщение провайдера>" }
```
- Тест использует **предоставленные** `base_url`/`model`/`api_key` (можно до сохранения).
- Rate-limit: ≥5с на (user, block); параллельный повтор того же блока → `429`.
- **R17:** `api_key` не возвращается/не логируется; тело ошибки санитизируется (без эха ключа).
- `checkup_betterstack` — probe SQL API BetterStack (host/table/user/password), не LLM.
- UI-кнопка `disabled` во время запроса (анти-спам).

---

## 7. Функции PERMsoc — контракт

- Только простые per-chat функции; группы — §4.2 `permsoc` (16 reactions + 3 flags + 5 limits).
- **Леха** = `reactions_alan` (ID/username/greeting_dir) + `limits_alan`.
- **Костик** = `reactions_kostik` (ID) + `limits_kostik`.
- Славик (`reactions_slavik`), Оля (`reactions_olya`) — отдельные (уже).
- `flags_media` — остаётся в PERMsoc.
- 10 миселённых ключей удалены из PERMsoc (см. §8, → Модули 5/6/7).

---

## 8. Изменения `services/param_catalog.py` (без миграций)

1. **Расщепления/переносы групп (0 новых PG-ключей, меняется только `group`):**
   - `limits_media` (17) → `limits_media_permsoc` (7, PERMsoc) + `limits_transcribe` (6, М5)
     + `limits_video_summary` (3, М6) + `limits_media_download` (1, М7). **Δ +3**
   - `limits_persons` (4) → `limits_alan` (3) + `limits_kostik` (1). **Δ +1**
   - `limits_youtube_web` (2) → `limits_youtube` (1, М6) + `limits_web` (1, М8). **Δ +1**
   - `limits_cooldowns` (6) → растворена (search/factcheck/checkup/youtube/web/service). **Δ −1**
   - `flags_modules` (9) → **7 групп**: `flags_module_summary`, `flags_module_direct`,
     `flags_module_transcribe`, `flags_smart_cache`, `flags_throttle`,
     `flags_module_media_download` (download+ytdlp), `flags_module_search`;
     `checkup_memory_metrics_enabled` → **`flags_service`**. **Δ +6**
   - `flags_chat_behavior` (11) → `flags_chat_behavior` (7, М2) + `flags_summary` (2, М1)
     + `flags_permsoc_behavior` (2, PERMsoc). **Δ +2**
   - `reactions_persons` (5) → `reactions_persons` (Славик+Оля) + `reactions_alan` (+ID/username)
     + **`reactions_kostik`** (NEW). **Δ +1**
   - **A3:** `limits_chat_budgets` (11) → `limits_chat_budgets` (10, М2) + **`limits_rag`** (1)
     → `memory_rag`; `limits_chat` (26) → 25 (минус `chat_rag_dedup_overlap_ratio` → `limits_rag`).
     **Δ +1**
2. **Новые master-флаги (A1, default `True`):** `FACTCHECK_ENABLED`, `SEARCH_ENABLED`,
   `VIDEO_SUMMARY_ENABLED`, `WEBPAGE_ENABLED`, `CHECKUP_ENABLED` (`config/settings.py`:
   `_env_bool(..., True)`; `_FLAGS` в `param_catalog.py`; группы — §4.2).
   Новые группы: `flags_module_factcheck`, `flags_module_video_summary`, `flags_module_web`.
   `SEARCH_ENABLED` → `flags_module_search`; `CHECKUP_ENABLED` → `flags_service`. **Δ +3**
3. **`GROUPS`/`TAB_RULES`/`CONFIG_TAB_TITLES`** — по §4 (добавить `TAB_MOD_*`, `TAB_SMART_CACHE`;
   `limits_rag`; удалить `TAB_LIMITS`/`TAB_REACTIONS_TRIGGERS`/`TAB_MODULES_SWITCHES`).
4. **Все `order`** внутри категорий пересчитать под новый порядок (уникальность).
5. **PG-ключи не меняются** (переносится только `group`); значения не мигрируются.
6. **Без DDL:** изменения — только в Python-метаданных (`param_catalog.py`, `settings.py`).

### 8.1. Итоговые счётчики каталога (locked)
| Параметр | 10.5 (baseline) | 10.6 (v2, locked) |
|---|---:|---:|
| REGISTRY | 387 | **392** (+5 master-флагов) |
| Settings | 359 | **364** (+5) |
| GROUPS | 74 | **91** (Δ **+17**) |
| mapped на вкладки | 72 | **89** |
| content `tab=None` | 2 | 2 |
| infra | 28 | 28 |

**GROUPS-дельта: базовые расщепления +13** (limits +4: media+3/ytweb+1/persons+1/cooldowns−1;
flags +8: modules→7 = +6, chat_behavior +2; reactions +1) **+ A3 `limits_rag` +1 + D1 +3 = +17.**
**Ноль PG-DDL.** (v1 указывал flags_modules→8 и базу +14; v2 сводит checkup-флаг в `flags_service`
— это освобождает слот под `limits_rag` и сохраняет locked **91**.)

---

## 9. RBAC / DM / scope / key-availability / матрица (не деградировать)

- `canViewTab`: 11 модулей + 7 AI + permsoc; `hubVisible` для `#/ai`/`#/access`.
- **DM:** `#/permsoc` скрыт; `models.*`/`keys.*` read-only (R10.5-2/класс R10.3-1 — сохранить
  DM-ветку `canEditConfig` с `item.per_chat`); недоступные вкладки не показываются.
- Scope-switcher: без изменений; смена скоупа перезагружает окно/экран. (R10.4-2 — relations
  reload — учесть при рефакторинге вкладок.)
- Key-availability: без изменений (`#/`).
- Матрица ролей: `param_permissions_list` без изменений (обходит REGISTRY);
  `TAB_SECTION_ORDER` обновлён (§4.3) — все **359** категорийных покрыты; 19 секций.
- R10.5-1 (BackButton re-init на `ready`) — **сохранить** (уже в коде: `initBackButton()` под
  guard `_boundBackApi`).
- 409-конфликт/per-chat override/per_chat-False — на всех config-экранах и в окнах модулей.

---

## 10. Emoji → Material-иконка (A6/A7)

- Использовать **существующие** `ICONS`/`iconGlyph`; **новых PUA-кодпоинтов не добавлять**
  (шрифт-субсет не пересобирать).
- **A6 «Как это работает» (`#/how`):** заголовок карточки — `<span class="msr">{{ iconGlyph('help') }}</span>
  Как это работает` (emoji `ℹ️` убрать из разметки). Контент `content.info_how_it_works`
  (данные из `info_text.md`) **не менять**.
- **A7 Матрица ролей (`#/access/roles`):** заголовок — `iconGlyph('admin_panel_settings')`
  (вместо 🔐); кнопка обновления — `iconGlyph('restart_alt')` (вместо ⟳); perm-picker —
  `iconGlyph('manage_accounts')` (вместо ⚙). Emoji/glyph-символы в разметке матрицы не рендерить.
- **AC:** маркер-тест «нет emoji в `#/how` и в матрице»; остальные emoji в удаляемых
  `modules_feats`-карточках исчезают вместе с разделом.

---

## 11. Модули: `keys_youtube` (proxy+cookies) в Модуль 6, diagnostics в Модуль 9 (A5/A8)

| Что | Откуда | Куда | Примечание |
|---|---|---|---|
| `keys_youtube` (proxy url/user/pass + cookies file, secret) | AI→LLM Провайдеры | **Модуль 6** (`mod_video_summary`) | R17-маска `{configured,last4}`; редактируемо |
| `limits_youtube_proxy` (domain/port/locations/retries) | Модуль 6 (уже) | Модуль 6 | без изменений |
| `models_checkup` (Betterstack SQL host/table/query) | AI→LLM Провайдеры | **Модуль 9** (`mod_checkup`) | настройки диагностики |
| `keys_betterstack` (SQL user/password, secret) | AI→LLM Провайдеры | **Модуль 9** | R17 |
| `limits_checkup`, `limits_service`, `limits_worker`, `flags_service`, `flags_throttle` | Модуль 9 (уже) | Модуль 9 | без изменений |
| Сервер, метрики, панель логов, control, key-availability | `#/` | **`#/` Статус** | **просмотр** не переносится |

- «Настройки логов» в каталоге — это `models_checkup` + `keys_betterstack` +
  `limits_checkup` (+ `limits_worker`/`flags_service`/`flags_throttle`). Инфра-лог-ключи
  (`LOG_RING_MAX_ENTRIES`, `SENTRY_DSN`, `LOGTAIL_SOURCE_TOKEN`) остаются infra (`tab=None`).
- **AC:** `models_checkup`/`keys_betterstack`/`keys_youtube` больше не в `llm_providers`;
  панель логов/сервера — на `#/`.

---

## 12. «Доступы и Роли» — эксклюзивный аккордеон (A9)

- State: `accessOpen` ∈ `{null,'roles','local','admins'}`. **Открыт ровно один**.
- DOM/CSS:
```
<div class="acc" role="tablist" aria-label="Доступы и роли">
  <button class="acc-head" role="tab" :aria-expanded="accessOpen==='roles'"
          aria-controls="acc-roles" @click="setAccess('roles')">Матрица ролей</button>
  <section class="acc-panel" id="acc-roles" role="tabpanel"
           v-show="accessOpen==='roles'"> ...матрица... </section>
  <!-- аналогично 'local' (Локальные админы) и 'admins' (Администраторы) -->
</div>
```
- `setAccess(id)`: toggle — `accessOpen = (accessOpen===id) ? null : id`.
- Роут `#/access/roles|local|admins` → синхронизирует `accessOpen`; при входе открыт ровно
  один. `#/access` (hub) показывает карточки (без открытых панелей).
- `aria-expanded` на заголовке; панель только одна `v-show`; нет одновременного показа
  `sec-roles`/`sec-local`/`sec-admins`.
- **AC:** маркер-тест «одна открытая секция»; `aria-expanded` корректен; deep-link открывает одну.

---

## 13. Acceptance Criteria (AC)

1. Sidebar удалён; в `web/` нет `sidebar|☰|sidebarOpen|MENU_ORDER`.
2. Navbar: 6 пунктов, иконка + подпись ПОД иконкой; видны на 360px и desktop; ≤2 строки.
3. Desktop fullscreen ⛶: длинный экран прокручивается; header виден; нет двойных скроллбаров.
4. `#/modules` = ровно 11 модулей (порядок §5); у каждого toggle + «Параметры»; окно содержит
   только группы модуля; «Кастомные модули» отсутствуют.
5. Тумблеры 5 новых модулей реально гейтят (§5.3): OFF → `UNHANDLED`/пропуск, ON → прежнее.
6. `#/ai` = ровно 7 подразделов; «Лимиты»/«Сон»/«Ностальгия»/«Диагностика» в AI отсутствуют.
7. LLM Провайдеры: 9 блоков (§6.2) ПО МОДУЛЯМ; main перед fallback; блок = base_url+model+key;
   **у каждого блока** кнопка «Проверить» (`POST /api/llm/test`); ключ не утекает (R17).
8. RAG: `limits_rag` в `memory_rag`; `limits_chat_budgets` (10) и `limits_chat` (25) без RAG-ключей.
9. PERMsoc не содержит 10 миселённых ключей; они в Модулях 5/6/7; Леха и Костик — раздельно.
10. `models_checkup`/`keys_betterstack`/`keys_youtube` не в `llm_providers`; proxy/cookies — М6;
    diagnostics-настройки — М9; панель сервера/логов — `#/` Статус.
11. A6/A7: нет emoji в `#/how` и в матрице (Material-иконки).
12. A9: «Доступы и Роли» — эксклюзивный аккордеон (одна открытая секция, `aria-expanded`).
13. `test_param_catalog`: GROUPS **91**; REGISTRY **392**; Settings **364**; mapped **89**.
14. `test_frontend_tab_mapping`: TABS↔TAB_RULES синхронны, **19** config-вкладок, каждая группа
    ровно на одной.
15. RBAC/DM/409/scope/key-availability/матрица не деградировали.
16. Полный pytest 0 регрессий; `node --check web/app.js`; `git diff --check` чисто.
17. Ноль новых PG-DDL; SQLite v8; `bot.py` порядок роутеров не тронут; `media/` не тронут.

---

## 14. Test plan

- Обновить: `test_param_catalog` (392/91/364/mapped 89), `test_frontend_tab_mapping` (19),
  `test_progressive_tab_basic_coverage`, `test_webapp_nav_disclosure_ui`, `test_webapp_rbac_ui`,
  `test_webapp_dm_ui`, `test_webapp_hubs_matrix_ui`, `test_webapp_parity_smoke`,
  `tests/js/routing_test.js`.
- Новые маркеры/проверки:
  - нет `sidebar`/`☰`/`sidebarOpen`/`MENU_ORDER`; `.nav-label` есть; нет правила скрытия ≤479px;
  - `.scroll-area`/`.fullscreen-mode` contain overflow;
  - 11 модулей ровно, «Кастомные модули» нет; 5 master-флагов default `True` и гейтят;
  - 7 AI-подразделов; `limits_rag` в `memory_rag`; RAG-ключи не в `mod_direct`;
  - 9 provider-блоков, каждый с test-кнопкой; `keys_youtube`/`models_checkup`/`keys_betterstack`
    не в `llm_providers`;
  - нет emoji в `#/how` и матрице; аккордеон «одна открытая»;
  - Леха/Костик — разные группы; 10 миселённых в М5/М6/М7.
- `POST /api/llm/test`: 403 не-админу; 200 ok/err; rate-limit; ключ не эхо.
- Финальный контур: `pytest -q` (baseline 10.5 = 4962 passed), `node --check`, `git diff --check`.

---

## 15. Инварианты и non-goals

- Ноль новых PG-DDL; SQLite v8; `bot.py` порядок роутеров; `media/` не трогать.
- R17 (секреты `{configured,last4}`), R16 (ID не имя), промпт-эталоны байт-в-байт.
- Zero-build (Vue3 global), hash-роутер, `__TMA_BACK__=true`, `__TMA_DEEPLINK__=false`.
- Не делать: bundler/vue-router; CRUD кастомных модулей (B2 OUT); новых PUA-иконок.

---

## 16. Закреплённые ответы владельца (A1–A9) — источник истины

| # | Решение (locked) | Отражено |
|---|---|---|
| A1 | Тумблеры модулей реально работают; Фактчек/Поиск/Выжимка видео/Веб/Диагностика **default ON**; +5 master-флагов | §5, §5.3, §8.2; 392/91/364 |
| A2 | Модули отдельно; редакторы промптов/моделей/ключей — в «Настройки AI» | §5.2, §6.2 |
| A3 | RAG-доли + все RAG-ключи → «Память» | §6.1 (2 ключа, `limits_rag`) |
| A4 | LLM Провайдеры — блоки ПО МОДУЛЯМ; base_url+model+key; main→fallback; per-block test | §6.2, §6.3 |
| A5 | Сервер/логи — на «Статус»; logs/BetterStack/checkup CONFIG → «Диагностика» | §11 |
| A6 | «Как это работает» — emoji → Material-иконка | §10 |
| A7 | Матрица ролей — emoji → Material-иконка | §10 |
| A8 | Proxy+cookies → «Модули»; logs/BetterStack/checkup → «Диагностика» | §11 |
| A9 | «Доступы и роли» — эксклюзивный аккордеон | §12 |

**Решения D1–D5:** D1=ДА (5 флагов ON) · D2=ДА (один дом) · D3=ИЗМЕНЁН → RAG в «Память» ·
D4=ДА (per-block test) · D5=сервер/логи «Статус», настройки → «Диагностика». Открытых вопросов нет.

---

*Spec v2 — @Architect, 11.09.2026 (T-1200). 0 кода. Готов к @Builder.*
