# Задачи: tma-ia-modules-rework (Раунд 10.6)

> **✅ СТАТУС: ЗАВЕРШЕНО И ЗААРХИВИРОВАНО (11.09.2026, @PM Step 8 Archive Phase).**
> Фича перенесена из `plans/features/tma-ia-modules-rework/` в
> **`plans/archive/tma-ia-modules-rework/`** (плоский kebab-case, как существующие архивы).
> Итог: полный pytest — **5027 passed / 0 failed**; @Reviewer — **APPROVED WITH MINOR ISSUES**
> (все минорные закрыты до Merge); @Scanner — **0 blocker / 0 major**
> (`plans/reports/round10.6_scanner_audit.md`; worthwhile-миноры закрыты); @Architect —
> архитектура влита в `plans/ARCHITECTURE.md` (§27 и связанные §2/§6/§9/§25).
> Каталог-инвариант: **REGISTRY 392 / GROUPS 91 / Settings 364** (mapped 89; Δ GROUPS 74→91 = +17).
> Артефакты сохранены: `design-project.md`, `spec.md`, `tasks.md`.
> **Остаётся пост-архивная фаза @DevOps (секция §K):** T-1196 (commit+push в `master`),
> T-1197 (деплой на прод), T-1199 (memory-sync docs-коммит). Ниже — исторический документ
> планирования; оставшиеся `[ ]` относятся только к этим пост-архивным задачам @DevOps.
> **FEATURE:** `plans/archive/tma-ia-modules-rework/` (kebab-case).
> **РАУНД:** **10.6** (follow-up после 10.5 `tma-relume-redesign`,
> архив `plans/archive/tma-relume-redesign/`, задеплоен 10.09.2026).
> **НУМЕРАЦИЯ ЗАДАЧ:** **T-1155…T-1223** (T-1155…T-1199 — исходный план;
> T-1200…T-1212 — по закреплённым ответам владельца; T-1213…T-1218 — review-fix @Reviewer;
> T-1219…T-1221 — approve-minors; T-1222…T-1223 — Scanner-миноры).
> **🟢 HARD GATE (T-1156) ПРОЙДЕН 11.09.2026;** реализация @Builder завершена, открытых вопросов нет (см. §8).
> **@PM не пишет код** — только план и артефакты.

---

## 0. Контекст и вход

**Вход:** обратная связь владельца после деплоя раунда 10.5 (Relume-редизайн TMA).

**Референс/канон раунда 10.5:** `plans/archive/tma-relume-redesign/` (spec v3,
design-project v5, tasks.md). Навигация 10.5: sidebar + top navbar (6 пунктов) +
hub-экраны + hash-роутинг. Каталог параметров: **REGISTRY 387 / GROUPS 74 /
Settings 359** (инвариант, проверен `test_param_catalog`).
**ЦЕЛЬ 10.6 (закреплено владельцем 11.09.2026): REGISTRY 392 / GROUPS 91 / Settings 364
(D1=YES, +5 master-флагов default ON).**

**Свежие аудиты @Scanner (обязательно учесть):**
- `plans/reports/round10.5_scanner_audit.md` (10.09.2026): **0 blocker / 0 major**;
  minor **R10.5-1** (BackButton не переинициализируется после позднего Telegram-`ready`)
  и **R10.5-2** (DM: `models.*` с `per_chat=False` редактируемы во фронте → сервер 422;
  класс R10.3-1, 33 ключа `models.*`); info R10.5-3…R10.5-7.
- `plans/reports/audit_backlog.md`: вся поверхность 10.5 просканирована.
- **Перепроверка 11.09.2026 (Step 1, повторно):** в `plans/reports/` **новых отчётов после
  `round10.5_scanner_audit.md` нет**; единственные открытые ремедиации — R10.5-1 (T-1160a)
  и R10.5-2 (DM `models.*` read-only, T-1175/T-1176/T-1207) — включены в план.

**Учитываем в плане:**
- R10.5-1 → включить точечную ремедиацию в навигационный блок (T-1160a).
- R10.5-2 → в разделе LLM Провайдеры сохранить read-only-семантику DM для `models.*`
  (не показывать/дисейблить `per_chat=False` в ЛС), чтобы не повторять 422.

---

## 1. Обратная связь владельца (captured EXACTLY, дословно)

1. **TWO nav panels is wrong.** Remove the SIDEBAR entirely; keep navigation ONLY via
   the TOP navbar; the top navbar currently has icons without labels → ADD small labels
   UNDER the icons, small font, fitting both mobile and desktop.
2. **Desktop FULLSCREEN has no scrolling** → must be fixed.
3. **Sections are chaotic**; the reference structure was not followed. **"Кастомные
   модули" must NOT be implemented (AI hallucination).**
   **REQUIRED IA:**
   - **"Модули"** section = **EXACTLY these 11 modules**, each with: **on/off toggle** +
     a **button opening a window with ALL params/limits of that module**:
     1 Саммаризация, 2 Прямые ответы, 3 Фактчек, 4 Поиск, 5 Транскрипт голосовых и
     видео, 6 Выжимка видео, 7 Скачивание медиа, 8 Веб-страницы, 9 Диагностика,
     10 Сон, 11 Ностальгия.
   - **"Настройки AI":** REMOVE **"Лимиты"** (limits move into Модули). Contains:
     LLM Провайдеры, Промпты, **Память (all memory+RAG)**, **Умный кэш**, Имена,
     Участники и отношения, Лор чата.
   - **"LLM Провайдеры"** layout: all models/providers/base_url; at the TOP the
     direct-answers model (main then fallback); **ONE visual block = base_url + model +
     api key**; ADD a **"test connection"** button.
   - **"Функции PERMsoc":** REMOVE misfiled params (Кулдаун скачивания, длительность
     видео для расшифровки, длительность войса, размер видео для расшифровки, символов
     транскрипта для выжимки, Потолок загрузки Groq, Потолок загрузки OpenRouter,
     Потолок публикации видео, TTL опубликованного видео, Таймаут STT видео) →
     redistribute into the correct Модули. **PERMsoc = hardcoded simple per-chat
     functions only.**
   - **Characters:** **"Леха" and "Костик" must be SEPARATE items**, not one section.

**Пример текущего перехода владельца (baseline 10.5):** 5 меню-секций
`MENU_ORDER = ['home','chat_profile','modules','ai','access']`, sidebar `<aside
class="sidebar">` + top navbar `NAV_ITEMS` (6 пунктов), вкладки `TABS`.

---

## 2. Инвентаризация групп параметров (light inventory, для @Architect — БЕЗ кода)

> Источник: `services/param_catalog.py` (GROUPS, TAB_RULES, `_MODELS_PG_ONLY`),
> `web/app.js` (TABS/sources), `web/index.html`. READ-ONLY-разведка @PM.

### 2.1. Инвариант каталога
- База 10.5: **REGISTRY 387 / GROUPS 74 / Settings 359** (проверено `test_param_catalog`).
- **Цель 10.6 (закреплено владельцем 11.09.2026): REGISTRY 392 / GROUPS 91 / Settings 364**
  (Δ GROUPS **74→91 = +17**; D1=YES, +5 master-флагов **default ON**).
- Групп по категориям: **prompts 8, models 8, keys 7, limits 23, flags 8,
  reactions 15, content 2, memory 3** = 74.
- `TAB_RULES` ↔ TABS обязаны оставаться синхронными (`test_frontend_tab_mapping`).

### 2.2. Маппинг «11 модулей → кандидатные группы/ключи» (для уточнения @Architect)

| # | Модуль | Кандидатные группы/ключи (текущее состояние) |
|---|--------|----------------------------------------------|
| 1 | Саммаризация | `prompts_summary`; `limits_summary`; флаги `SUMMARY_ENABLED` (`flags_modules`), `SUMMARY_STREAMING_ENABLED` (`flags_chat_behavior`); `reactions_summary` (доступ) |
| 2 | Прямые ответы | `prompts_direct_chat`; `limits_chat`, `limits_chat_behavior`, `limits_chat_budgets`, `limits_temperature`; `flags_chat_behavior`; `DIRECT_CHAT_BOTWORD_ENABLED` (`flags_modules`) |
| 3 | Фактчек | `prompts_factcheck`; `limits_factcheck`; кулдаун фактчека в `limits_cooldowns` |
| 4 | Поиск | `prompts_search`; `limits_search`; кулдаун поиска в `limits_cooldowns`; `keys_search`; `SEARCH_RERANK_ENABLED` (`flags_modules`) |
| 5 | Транскрипт голосовых и видео | `ENABLE_VOICE_TRANSCRIPTION` (`flags_modules`); `keys_groq`, `keys_openrouter`; `models_extra_providers`; **+6 ключей из `limits_media`** (см. §2.3) |
| 6 | Выжимка видео | `prompts_youtube`; `models_video_summary`; `keys_media`; `content_media`; `limits_youtube_web`; **+3 ключа из `limits_media`** (см. §2.3) |
| 7 | Скачивание медиа | `DOWNLOAD_ENABLED`, `YTDLP_FOR_YOUTUBE` (`flags_modules`); **+1 ключ из `limits_media`** (см. §2.3) |
| 8 | Веб-страницы | `prompts_web`; `limits_youtube_web`; web-runtime-флаги (уточнить) |
| 9 | Диагностика | `prompts_checkup`; `limits_checkup`; `models_checkup`; `keys_betterstack`; `limits_service` (уточнить границу со «Статусом») |
| 10 | Сон | `memory_dream` (переносится из «Настройки AI») |
| 11 | Ностальгия | `memory_nostalgia` (переносится из «Настройки AI») |

### 2.3. Миселённые параметры PERMsoc → redistribution (все сейчас в `limits_media`)

| Ключ | Title (RU) | Текущая группа | Целевой модуль |
|------|-----------|----------------|----------------|
| `DOWNLOAD_COOLDOWN` | Кулдаун скачивания, сек | `limits_media` | **7 Скачивание медиа** |
| `VOICE_MAX_DURATION_SECONDS` | Макс. длительность войса, сек | `limits_media` | **5 Транскрипт** |
| `VIDEO_TRANSCRIBE_MAX_SIZE_MB` | Макс. размер видео для расшифровки, МБ | `limits_media` | **5 Транскрипт** |
| `VIDEO_TRANSCRIBE_MAX_DURATION_SECONDS` | Макс. длительность видео для расшифровки, сек | `limits_media` | **5 Транскрипт** |
| `VIDEO_STT_TIMEOUT_SECONDS` | Таймаут STT видео, сек | `limits_media` | **5 Транскрипт** |
| `STT_GROQ_MAX_UPLOAD_MB` | Потолок загрузки Groq STT, МБ | `limits_media` | **5 Транскрипт** |
| `STT_OPENROUTER_MAX_UPLOAD_MB` | Потолок загрузки OpenRouter STT, МБ | `limits_media` | **5 Транскрипт** |
| `VIDEO_SUMMARY_MIN_CHARS` | Мин. символов транскрипта для выжимки | `limits_media` | **6 Выжимка видео** |
| `MEDIA_SHARE_MAX_MB` | Потолок публикации видео, МБ | `limits_media` | **6 Выжимка видео** |
| `MEDIA_SHARE_TTL_SECONDS` | TTL опубликованного видео, сек | `limits_media` | **6 Выжимка видео** |

> ⚠️ **Ключевая находка:** группа **`limits_media` смешанная**. Кроме 10 переносимых
> ключей в ней остаются **настоящие PERMsoc-параметры**: `GIF_INTERVAL`,
> `SLAVIC_PHOTO_INTERVAL`, `COMMON_COOLDOWN`, `DANGER_COOLDOWN`, `SELFDEV_COOLDOWN`,
> `WORK_COOLDOWN`, `OLYA_COOLDOWN`. Значит, redistribution требует **расщепления
> `limits_media` на 2+ группы** (изменение каталога), а не только правки `TAB_RULES`.
> Решение о схеме расщепления — **за @Architect** (T-1179).
>
> `flags_media` (Оля/common-медиа/mimic) — **НЕ входит** в список из 10, но требует
> решения о месте (PERMsoc vs Модули) — см. открытые вопросы Q9.

### 2.4. «Настройки AI» — новая карта подразделов (кандидат)

| Подраздел | Текущие группы |
|-----------|----------------|
| **LLM Провайдеры** | `models_main`, `models_fallback`, `models_embeddings`, `models_llm_timeouts`, `models_llm_guard`, `models_extra_providers`, `models_video_summary`, `models_checkup` + `keys_llm`, `keys_groq`, `keys_openrouter`, `keys_search`, `keys_betterstack`, `keys_youtube`, `keys_media` (переупаковать в блоки «base_url + model + api key», см. §2.5) |
| **Промпты** | все `prompts_*` (8 групп) |
| **Память (all memory+RAG)** | `limits_memory`, `limits_graph`, `flags_memory`, `memory_infinite` (+ уточнить RAG-ключи внутри `limits_chat_budgets`) |
| **Умный кэш** | `limits_smart_cache` + `SMART_CACHE_ENABLED` (`flags_modules`) |
| **Имена** | `limits_user_aliases` |
| **Участники и отношения** | `limits_relations`, `flags_relations` |
| **Лор чата** | `limits_lore`, `flags_lore` |

**Удаляется из «Настройки AI»:** `TAB_LIMITS` («Лимиты») — растворяется по модулям;
«Сон»/«Ностальгия» — переносятся в «Модули» (#10/#11).

### 2.5. «LLM Провайдеры» — целевая раскладка (layout)
- Сверху — модель прямых ответов: **main → fallback** (порядок).
- **Один визуальный блок = `base_url` + `model` + `api key`** (сейчас разнесено
  между секциями «Основные модели»/«Ключи»/«Фолбэк»).
- Кнопка **«test connection»** (нужен backend-эндпоинт — см. T-1180).
- DM-семантика: `models.*` с `per_chat=False` — **read-only/скрыто** в ЛС (R10.5-2,
  класс R10.3-1).

### 2.6. Current nav baseline (что ломаем/убираем)
- Sidebar: `web/index.html` `<aside class="sidebar ...">` (стр. ~538-571) +
  `sidebar-backdrop` + кнопка `☰` + `sidebarOpen` (app.js).
- Top navbar: `NAV_ITEMS` (`web/app.js` ~211-220) — 6 пунктов; на ≤479px
  `.nav-link > span:not(.msr){display:none}` (только иконки) в `web/index.html` ~265.
- Fullscreen: `.fullscreen-mode { height:100dvh; overflow:hidden; }` (`web/index.html`
  ~496-499) — при `overflow:hidden` и без собственного скролла main-колонки
  **десктопный fullscreen не скроллится** (сейчас скроллится сам sidebar).
- «Кастомные модули»: hub-карточка `#/modules/custom` (read-only, `anchor:true`) в
  `web/app.js` ~238-241 + `ROUTE_TO_TAB`/`ROUTE_PARENT`.

---

## 3. План задач (checkboxes для @Builder/@Architect/@DevOps)

> Легенда: `[ ]` — не сделано; `[x]` — сделано; `⏸` — ждёт человека (не закрывать).
> Исполнители: **@Architect** — дизайн/spec (`spec.md`); **@Builder** — код;
> **@DevOps** — деплой; независимая верификация — **@Scanner**/@Reviewer.

### §0 — Envelope & HARD GATE (pre-implementation, 0 кода)

- [x] **T-1155 — @Architect: `spec.md` + дизайн новой IA (deliverable раунда 10.6).**
  ✅ **ВЫПОЛНЕНО 11.09.2026** (`spec.md` v1, `design-project.md` v1). Ревизия → v2 — **T-1200**.
  Вход: этот `tasks.md`, обратная связь владельца §1, инвентарь §2, архив 10.5.
  Обязательно: (а) **parity-map без потери функций** (все текущие экраны/фичи аппа
  учтены); (б) карта `TABS`/`TAB_RULES`/GROUPS после расщепления `limits_media`;
  (в) спецификация 11 модулей (toggle + окно параметров); (г) спецификация
  «Настройки AI» 7 подразделов; (д) LLM Провайдеры «base_url+model+key» + test
  connection; (е) схема навигации без sidebar (top navbar + подписи под иконками);
  (ж) модель скролла fullscreen; (з) ответы на открытые вопросы §5.
  **Без реализации.**
- [x] **T-1156 — ✅ @PM + ВЛАДЕЛЕЦ: HARD GATE — ПРОЙДЕН 11.09.2026.**
  Владелец **утвердил** дизайн/IA и дал явное **«proceed»**; все ответы закреплены в §8.
  Реализация (`@Builder`) **РАЗБЛОКИРОВАНА**. Не переоткрывать.

### §A — Навигация: убрать sidebar, оставить только top navbar с подписями

- [x] **T-1157 — @Builder: удалить SIDEBAR полностью.**
  `web/index.html`: `<aside class="sidebar ...">`, `sidebar-backdrop`, кнопка `☰`,
  CSS `.sidebar`/`.sidebar-backdrop`/`aside.sidebar`, `safe-area`-правило sidebar.
  `web/app.js`: состояние `sidebarOpen`, `openTab/navTo` его сброс, мобильные ветки.
  Убедиться, что не осталось «мёртвых» ссылок/брейкпоинтов `md:hidden`.
- [x] **T-1158 — @Builder: top navbar — иконка + МАЛЕНЬКАЯ ПОДПИСЬ ПОД иконкой.**
  Вертикальная раскладка `.nav-link` (icon сверху, label снизу), мелкий шрифт
  (`--tx-tiny`, напр. .75rem), корректно на **mobile и desktop**.
  Убрать правило `.nav-link > span:not(.msr){display:none}` (сейчас на ≤479px прячет
  подписи) и заменить на адаптивный размер подписи. Подписи должны помещаться
  без переполнения на 6 пунктах (`Статус`, `Как это работает`, `Модули`,
  `Настройки AI`, `Функции PERMsoc`, `Доступы и Роли`).
- [x] **T-1159 — @Builder: a11y/active-state navbar.**
  `aria-current`для активного пункта, `aria-label`/`title`, клавиатурная
  доступность; активный пункт — по route (`activeNav`).
- [x] **T-1160 — @Builder: hash-роутинг под новую навигацию.**
  Убедиться, что все 6 top-level маршрутов (`#/`, `#/how`, `#/modules`, `#/ai`,
  `#/permsoc`, `#/access`) доступны из навбара, `ROUTE_TO_TAB`/`ROUTE_PARENT`
  не ссылаются на удалённые sidebar-экраны; deep-link OFF (OD13) сохраняется.
- [x] **T-1160a — @Builder: ремедиация R10.5-1 (BackButton re-init).**
  Вызвать `initBackButton()` в `ready`-хендлере под guard повторной регистрации
  (`_backOnClickBound`), чтобы нативная кнопка «назад» работала при позднем
  Telegram-контексте (находка `round10.5_scanner_audit.md`).

### §B — Desktop FULLSCREEN: скроллинг

- [x] **T-1161 — @Architect: спека модели скролла (в составе T-1155).**
  Корень `100dvh` без скролла страницы; **main-контент-колонка — собственный
  `overflow-y:auto`** (`min-h-0`); sticky-navbar остаётся; safe-area insets.
- [x] **T-1162 — @Builder: фикс fullscreen-скролла.**
  Переработать `.fullscreen-mode` (`web/index.html`): 100dvh, но контент-скролл
  там, где он реально нужен; проверить desktop (fullscreen ⛶) и mobile.
  После удаления sidebar (T-1157) — скролл не должен зависеть от sidebar.
- [x] **T-1163 — @Builder: не сломать существующие вложенные скроллы.**
  Проверить панели логов, scope-dropdown, relations/nav-lore, модалки —
  они не должны получить двойной скроллбар/обрезку.

### §C — «Модули»: ровно 11 модулей (toggle + окно параметров)

- [x] **T-1164 — @Architect: спека 11-модульной IA + точная карта параметров**
  (в составе T-1155). Использовать §2.2; зафиксировать, какие группы/ключи входят
  в окно каждого модуля, и что делать с `Реакции и Триггеры`/`Модули (вкл/выкл)`
  (Q1/Q2).
- [x] **T-1165 — @Builder: построить раздел «Модули» = ровно 11 модулей.**
  Порядок строго: 1 Саммаризация, 2 Прямые ответы, 3 Фактчек, 4 Поиск,
  5 Транскрипт голосовых и видео, 6 Выжимка видео, 7 Скачивание медиа,
  8 Веб-страницы, 9 Диагностика, 10 Сон, 11 Ностальгия.
  Никаких других модулей/карточек.
- [x] **T-1166 — @Builder: on/off toggle у каждого модуля.**
  Тумблер прокидывается в существующий флаг/гейт там, где он есть; для модулей без
  единого флага (Q5) — согласованное решение из T-1155 (не выдумывать).
  Учесть RBAC (`canEditConfig`/DM) и per-chat/gate-семантику.
- [x] **T-1167 — @Builder: кнопка «Параметры» → окно со ВСЕМИ параметрами модуля.**
  Модалка/отдельный экран (по спеке), generic-рендер групп/ключей из карты
  T-1164; сохранение через существующий config-контракт (per-chat override, 409).
- [x] **T-1168 — @Builder: перенести «Сон» и «Ностальгия» из «Настройки AI» в «Модули».**
  `memory_dream` → модуль 10, `memory_nostalgia` → модуль 11; удалить их вкладки
  из AI-хаба; обновить `TABS`/маршруты/`TAB_SECTION_ORDER`.
- [x] **T-1169 — @Builder: деактивировать/переразметить старые вкладки секции «Модули».**
  `modules_feats`, `modules_switches`, `reactions_triggers` — по решению T-1164
  (растворить/перевести в окна модулей), убрать дубли из `TABS`/`.sources`.

### §D — «Настройки AI»: 7 подразделов, без «Лимитов»

- [x] **T-1170 — @Architect: спека AI-хаба (7 подразделов)** (в составе T-1155).
  Строго: LLM Провайдеры, Промпты, Память (all memory+RAG), Умный кэш, Имена,
  Участники и отношения, Лор чата. «Лимиты» — удалить.
- [x] **T-1171 — @Builder: удалить раздел «Лимиты» из «Настройки AI».**
  `TAB_LIMITS` и его карточка/маршрут `#/ai/limits` убираются; параметры
  распределяются по модулям (см. §C/§2.2). Не оставлять висячих маршрутов.
- [x] **T-1172 — @Builder: собрать 7 подразделов AI.**
  Обновить `HUBS['#/ai']`, `TABS.menu='ai'`, `TAB_RULES`/`CONFIG_TAB_TITLES`
  синхронно (инвариант `test_frontend_tab_mapping`).
- [x] **T-1173 — @Builder: «Память (all memory+RAG)».**
  Включить `limits_memory`, `limits_graph`, `flags_memory`, `memory_infinite`
  (+ RAG-ключи из `limits_chat_budgets` — по решению Q3).
- [x] **T-1174 — @Builder: «Умный кэш» — отдельный подраздел.**
  `limits_smart_cache` + `SMART_CACHE_ENABLED` (перенос из `flags_modules`).

### §E — «LLM Провайдеры»: блоки base_url+model+key + test connection

- [x] **T-1175 — @Architect: спека раскладки LLM-провайдеров** (в составе T-1155).
  Сверху — модель прямых ответов (main → fallback); **1 блок = base_url + model +
  api key**; кнопка test connection; DM `per_chat=False` → read-only (R10.5-2).
- [x] **T-1176 — @Builder: переверстать LLM Провайдеры в единые блоки.**
  `models_main`+`keys_llm` (main), `models_fallback`+`LLM_FALLBACK_API_KEY` (fallback),
  затем остальные провайдеры/модели/base_url; секции в `TABS.sources/sections` и
  `TAB_RULES` синхронны.
- [x] **T-1177 — @Builder: кнопка «test connection» во фронте.**
  Вызов нового эндпоинта (T-1178), индикация успех/ошибка, маскировка ключа (R17),
  запрет на спам (disabled во время запроса).
- [x] **T-1178 — @Architect → @Builder: backend-эндпоинт test connection.**
  Спека контракта (@Architect), реализация (@Builder): безопасный probe провайдера
  без утечки ключа (R17), permission — global admin (уточнить Q6), rate-limit.
  Если можно обойтись существующим API — зафиксировать это в T-1155.

### §F — «Функции PERMsoc»: чистка и redistribution 10 параметров

- [x] **T-1179 — @Architect: план расщепления `limits_media` + маппинг 10 ключей**
  (в составе T-1155, §2.3). Определить новые группы (напр. `limits_transcribe_video`,
  `limits_video_summary_media`, `limits_media_download` или иные), сохранив
  инвариант «каждая группа ровно на одной вкладке».
- [x] **T-1180 — @Builder: реализовать расщепление групп в `services/param_catalog.py`.**
  Перенести 10 ключей в новые/целевые группы; обновить `GROUPS`, `TAB_RULES`,
  `CONFIG_TAB_TITLES`, TABS-зеркало; сохранить REGISTRY-счётчики/инвариант
  (пересчитать и задокументировать новое число групп — согласованное изменение).
- [x] **T-1181 — @Builder: убрать 10 параметров из вкладки «Функции PERMsoc».**
  PERMsoc = только захардкоженные простые per-chat функции
  (`reactions_*` персон/каналов + `flags_permsoc` + genuinely-PERMsoc `limits_*`).
- [x] **T-1182 — @Builder: разместить 10 параметров в окнах модулей.**
  Модуль 5 — 6 ключей; модуль 6 — 3 ключа; модуль 7 — 1 ключ (см. §2.3).
- [x] **T-1183 — @Builder: определить место `flags_media`** по решению Q9
  (остаётся в PERMsoc или переносится в модули Транскрипт/Медиа).

### §G — Персонажи: Леха и Костик — РАЗДЕЛЬНО

- [x] **T-1184 — @Architect: спека разделения** (в составе T-1155).
  Сейчас `limits_persons` ("Персонажи: Леха и Костик") и `reactions_persons` (IDs
  Леха/Костик/Славик/Оля) — общие. Спроектировать отдельные items для **Леха** и
  **Костик** (отдельные карточки/группы в PERMsoc), без слияния в одну секцию.
- [x] **T-1185 — @Builder: реализовать разделение Леха/Костик.**
  Обновить `GROUPS`/`TAB_RULES`/TABS; проверить, что реакционные группы
  (`reactions_alan`=Леха и новая для Костика) не конфликтуют и не дублируются.
- [x] **T-1186 — @Builder: не сломать ID-соответствие персон.**
  R16 (ID не имя): значения персон/ID не менять; меняется только группировка UI.

### §H — Удалить «Кастомные модули»

- [x] **T-1187 — @Builder: удалить UI «Кастомные модули».**
  Hub-карточка `Кастомные модули` (`web/app.js`, `route:'#/modules/custom'`,
  `anchor:true`), `ROUTE_TO_TAB['#/modules/custom']`, `ROUTE_PARENT`, любые
  подписи/ссылки. B2 остаётся OUT (OD9 раунда 10.5). Никакого CRUD.

### §I — Проверка отсутствия функциональных потерь (parity)

- [x] **T-1188 — @Builder: parity-матрица «каждый параметр применяется и персистится».**
  Round-trip 1:1 по всем записям, затронутым переносом (10 миселённых + группы
  AI/Модули/PERMsoc); ни один параметр не потерян из UI и не осиротел.
- [x] **T-1189 — @Builder: инвариант каталога + RBAC без ослабления.**
  `canViewTab`/`canEditConfig`/DM-ветки — источник истины; UI не ослабляет серверные
  гейты; 409-конфликты работают.

### §J — Тесты / QA

- [x] **T-1190 — @Builder: обновить маркер-тесты IA.**
  `test_frontend_tab_mapping`, `test_param_catalog`, `test_webapp_nav_disclosure_ui`,
  `test_webapp_rbac_ui`, `test_webapp_dm_ui`, `test_webapp_hubs_matrix_ui`,
  `test_webapp_parity_smoke` и др. — под новую IA/карту.
- [x] **T-1191 — @Builder: JS-тесты (node) на новую навигацию.**
  Sidebar отсутствует; подписи под иконками присутствуют; 6 top-level пунктов;
  роутинг/active-state. Расширить `tests/js/*` + `node --check web/app.js`.
- [x] **T-1192 — @Builder: тест скролла fullscreen (где возможно).**
  Регресс-проверка, что fullscreen содержит собственный скролл-контейнер
  (маркер/CSS-тест).
- [x] **T-1193 — @Builder: полный pytest + `node --check` + `git diff --check`.**
  Baseline 10.5 = **4962 passed / 0 failed**; цель — 0 регрессий.
- [x] **T-1194 — ✅ @Scanner: независимый аудит раунда 10.6** → отчёт
  `plans/reports/round10.6_scanner_audit.md`: **0 blocker / 0 major** (3 minor + 3 info;
  worthwhile-миноры закрыты — T-1222/T-1223).
- [x] **T-1195 — ✅ @Reviewer: ревью раунда** — **APPROVED WITH MINOR ISSUES**
  (все минорные закрыты до Merge: T-1213…T-1221).

### §K — Завершение (после GO владельца)

- [ ] **T-1196 — @DevOps: русский conventional-commit + push в `master`.**
  Эталон+код+тесты одним атомарным коммитом; скан секретов; без `.env`/`var/`/`media/`.
- [ ] **T-1197 — @DevOps: деплой на прод (systemd `admin_bot`).**
  ssh → `git pull --ff-only` → `.env` при необходимости → `systemctl restart admin_bot`
  → `systemctl status` → live-smoke (Telegram desktop/Android WebView).
- [x] **T-1198 — ✅ @PM: Archive Phase (Step 8) — `plans/features/tma-ia-modules-rework/`
  → `plans/archive/tma-ia-modules-rework/`** — выполнено 11.09.2026 (packaging-коммит — @DevOps, T-1196).
- [ ] **T-1199 — @DevOps/@Memory: memory-sync docs-коммитом.**

---

## 4. DoD (Definition of Done) раунда 10.6

| # | Критерий | Задачи |
|---|----------|--------|
| a | Sidebar удалён; навигация — только top navbar; подписи под иконками (mobile+desktop) | T-1157…T-1160 |
| b | Desktop fullscreen скроллится | T-1161…T-1163 |
| c | «Модули» = ровно 11 модулей; toggle + окно со всеми параметрами | T-1164…T-1169 |
| d | «Настройки AI» = 7 подразделов; «Лимиты» удалены | T-1170…T-1174 |
| e | LLM Провайдеры: блоки base_url+model+key **по модулям** (main→fallback), **per-block test** | T-1175…T-1178, T-1207, T-1210 |
| f | 10 миселённых параметров перенесены в модули; PERMsoc простой | T-1179…T-1183 |
| g | Леха и Костик — раздельно | T-1184…T-1186 |
| h | «Кастомные модули» отсутствуют | T-1187 |
| i | Ноль функциональных потерь (parity) | T-1188…T-1189 |
| j | Тесты: 0 регрессий, `node --check`, `git diff --check` | T-1190…T-1193 |
| k | @Scanner 0 blocker/major; @Reviewer approve | T-1194…T-1195 |
| l | Commit+push+deploy+live-smoke; README | T-1196…T-1199 |
| m | **HARD GATE: дизайн утверждён владельцем ДО кода — ✅ ПРОЙДЕН 11.09.2026** | T-1156 |
| n | Каталог **392 / 91 / 364 / mapped 89** (Δ GROUPS 74→91 = +17: база +13, `limits_rag` +1, D1 +3); 5 master-флагов **default ON** | T-1200, T-1201, T-1208, T-1211 |
| o | Модули и AI-редакторы раздельны («один дом»); RAG → «Память» | T-1208, T-1209 |
| p | emoji→icon в «Как это работает» и матрице; эксклюзивный аккордеон «Доступы и роли» | T-1202, T-1203, T-1206 |
| q | Proxy/cookies → Модули; logs/BetterStack/checkup → Диагностика (сервер/логи на «Статус») | T-1204, T-1205 |

---

## 5. Открытые вопросы к владельцу — ✅ ВСЕ ЗАКРЫТЫ 11.09.2026 (см. §8)

> Ниже — исторический список вопросов; ответы владельца закреплены в §8. **Открытых нет.**

1. **«Реакции и Триггеры»** (`reactions_admin/summary/chat/memory`) — куда?
   Свернуть в «Функции PERMsoc», оставить отдельным пунктом навбара, или иное?
2. **«Модули (вкл/выкл)»** (`flags_modules`/`flags_service`) — растворяем в тумблеры
   11 модулей? Где живут служебные `flags_service`?
3. **«Память (all memory+RAG)»** — включать ли RAG-ключи из `limits_chat_budgets`
   (`limits.chat_rag_*`) в подраздел «Память», или они остаются в модуле
   «Прямые ответы»?
4. **«Диагностика»** — это только chekup-модуль, или также сервер/логи (страница
   «Статус»)? Не дублировать «Статус».
5. **Тумблеры модулей без единого флага** (Фактчек, Поиск, Веб-страницы,
   Диагностика) — добавляем новые master-флаги (одобрение на +N записей каталога)
   или выводим из существующих ключей?
6. **«test connection»** — новый backend-эндпоинт? Только global admin?
   Ограничение частоты? Тестировать все провайдеры или только main/fallback?
7. **Леха и Костик раздельно** — отдельные группы каталога + отдельные карточки
   только для этих двух, или аналогично разнести и остальных персон (Славик/Оля)?
8. **`flags_media`** — остаётся в PERMsoc или переносится в модули?
9. **Число задач/нумерация** — подтвердить T-1155…T-1199 и раунд **10.6**.
10. **Судьба hub-экранов 10.5** — hub-карточки «Модули»/«Настройки AI» сохраняем
    как способ входа, или сразу показываем раздел без промежуточного экрана?

---

## 6. Замечания @PM

- **Никакого кода** в этом раунде со стороны @PM; реализация — только через
  `@Architect` (spec/дизайн) и `@Builder` (код) после гейта T-1156.
- **Не ломать инварианты** 10.5: REGISTRY/GROUPS/Settings, `TABS`↔`TAB_RULES`,
  hash-роутинг, RBAC/DM, R16/R17, zero-build.
- Расщепление `limits_media` меняет счётчик GROUPS — это **осознанное согласованное
  изменение каталога**, должно быть явно отражено в спеке T-1155 и тестах.
- Раунд 10.5 уже занял номера T-1149…T-1154 (деплой-секция H) — поэтому 10.6
  начинается с **T-1155**.

---

## 7. Уточнения @Architect (Step 2, 11.09.2026) — источник: `spec.md` + `design-project.md`

> **Статус:** 🟢 спецификации **v2 готовы** (T-1155 → v1, **T-1200 → v2**; A1–A9 внесены).
> Нумерация T-1155…T-1212 сохраняется. Ниже — уточнения формулировок задач под
> утверждённую архитектуру. **0 кода.**

- **T-1155 — ✅ ВЫПОЛНЕНО @Architect (v1).** Написаны `spec.md` + `design-project.md`
  (Nav shell, IA-дерево, карта всех 387 параметров, ответы на §5, impact, AC).
- **T-1200 — ✅ ВЫПОЛНЕНО @Architect (v2).** `spec.md` v2 + `design-project.md` v2:
  A1–A9 (5 флагов ON + реальные гейты; «один дом»; RAG→«Память» с `limits_rag`;
  provider-блоки по модулям + per-block test; proxy/cookies → Модули; diagnostics → М9;
  emoji→icon ×2; эксклюзивный аккордеон). Каталог **392 / 91 / 364 / mapped 89**.
- **T-1157** — дополнительно удалить `MENU_ORDER`/`MENU_LABELS` (мёртвые после удаления
  menu) и все остатки `sidebarOpen`/`☰`.
- **T-1158** — зафиксировать: `.nav-link` вертикальный, `.nav-label` 10px, `flex:1` ×6,
  перенос ≤2 строк; **удалить** `.nav-link > span:not(.msr){display:none}`.
- **T-1160** — `ROUTE_TO_TAB`/`TAB_TO_ROUTE`/`ROUTE_PARENT`/`ROOT_ROUTES`: удалить 7 роутов
  (`#/ai/limits`, `#/ai/sleep`, `#/ai/nostalgia`, `#/modules/features|switches|reactions|custom`),
  добавить алиасы в `#/ai`/`#/modules`; модульные окна — **не роуты** (модалки).
- **T-1161/T-1162/T-1163** — модель скролла: `.app-shell` flex-col; `.scroll-area`
  (`flex:1;min-height:0`) + `.fullscreen-mode .scroll-area{overflow-y:auto}`; вложенные
  скроллеры `overscroll-behavior:contain`.
- **T-1164** — окна модулей строятся по группам из `spec.md` §4.2; 11 config-вкладок `mod_*`.
- **T-1166** — тумблеры: 6 существующих флагов + (при D1) 5 новых; DM/`per_chat=False` read-only.
- **T-1167** — окно = модалка; back закрывает окно; RBAC/409/per-chat сохранить; **не**
  дублировать prompts/models/keys (чипы-ссылки).
- **T-1169** — удалить `reactions_triggers`/`modules_switches`/`modules_feats`; распределить
  по `design-project.md` Q1/Q2 + §4.8.
- **T-1171** — `TAB_LIMITS` удалить; `limits_cooldowns` расформировать (§4.8).
- **T-1174** — «Умный кэш» = `limits_smart_cache` + `flags_smart_cache`.
- **T-1179/T-1180** — расщепления (v2): `limits_media`→4, `limits_persons`→2,
  `limits_youtube_web`→2, `flags_modules`→**7** (checkup-флаг → `flags_service`),
  `flags_chat_behavior`→3, `limits_cooldowns`→0, `reactions_persons`/`reactions_alan`/
  `reactions_kostik`; **A3:** `limits_chat_budgets`→+`limits_rag` (RAG→«Память»);
  **GROUPS 74→88** (база+RAG), с D1 → **91**. Детали — `spec.md` §6.1/§8, `design-project.md` §10.
- **T-1182** — 6 → Модуль 5, 3 → Модуль 6, 1 → Модуль 7.
- **T-1184/T-1185** — Леха/Костик: `limits_alan` + `limits_kostik`, `reactions_kostik`.
- **T-1187** — удалить UI/роут/`ROUTE_TO_TAB` «Кастомные модули».
- **T-1178** — контракт `POST /api/llm/test` (global admin, rate-limit, R17) — см. `spec.md` §6.
- **D1 ОДОБРЕН владельцем (11.09.2026):** 5 master-флагов (**default ON**) + 3 группы →
  REGISTRY **392** / Settings **364** / GROUPS **91** (Δ GROUPS **74→91 = +17**).
  Детали и новые задачи — §8.

### ✅ РЕШЕНИЯ ВЛАДЕЛЬЦА (T-1156 ПРОЙДЕН 11.09.2026) — см. §8
D1 = **ДА** (5 master-флагов default ON; 392/91/364) · D2 = **ДА — раздельно** ·
D3 = **RAG → «Память»** · D4 = **per-block test** · D5 = **Статус держит сервер/логи**.

---

## 8. ЗАКРЕПЛЁННЫЕ ОТВЕТЫ ВЛАДЕЛЬЦА (Step 1, Round 10.6, 11.09.2026) — 🟢 ГЕЙТ ОТКРЫТ

> Источник: прямое сообщение владельца (locked, дословные решения). **T-1156 пройден.**
> Ниже — единая запись решений и дельта задач (T-1200…T-1212). **@PM не пишет код.**

### 8.1. Дословные решения владельца (locked)

| # | Решение владельца (locked) | Влияние |
|---|---|---|
| A1 | Тумблеры модулей ДОЛЖНЫ реально работать; **Фактчек, Поиск, Выжимка видео, Веб-страницы, Диагностика — default ON**; добавить **5 master-флагов** | Каталог: **REGISTRY 392 / GROUPS 91 / Settings 364**; D1=YES |
| A2 | Модули — отдельно в «Модули»; редакторы промптов/моделей/ключей — отдельно в «Настройки AI» | D2=YES («один дом», без дублей) |
| A3 | Доли RAG-бюджета И всё, что относится к RAG → подраздел **«Память»** «Настроек AI» | D3=**ИЗМЕНЁН** (было: оставить в Модуле 2) → `limits_chat_budgets` расщепить, RAG → `memory_rag` |
| A4 | LLM Провайдеры: **отдельные визуальные блоки ПО КАЖДОМУ МОДУЛЮ** (прямые ответы, транскрипция, …); каждый блок = `base_url` + `model` + `api key`; сначала main, потом fallback; **у КАЖДОГО блока — кнопка test** (ввести key/model/url → тестовый запрос → ошибка (плохой key/model) или 200) | Расширяет T-1175…T-1178; D4=YES (per-block) |
| A5 | Сервер и логи остаются на **«Статус»** | D5=YES (view-only); см. A8 |
| A6 | «Как это работает» — emoji → **иконка (Material Symbols)** | Новая задача T-1202 |
| A7 | Матрица ролей — emoji → **иконка (Material Symbols)** | Новая задача T-1203 |
| A8 | Настройки **прокси + cookies** → вынести из «Провайдеров» в «Модули»; настройки **логов + BetterStack + checkup** → подраздел «Диагностика» | T-1204/T-1205; уточняет D5/A5 (view — Статус, settings — Диагностика) |
| A9 | «Доступы и роли» — **эксклюзивный аккордеон**: открытие одного подраздела показывает ТОЛЬКО его | T-1206 |

### 8.2. Резолюция прежних D1–D5

| ID | Вопрос | РЕШЕНИЕ владельца (locked) |
|----|--------|----------------------------|
| **D1** | 5 master-флагов? | ✅ **ДА.** `FACTCHECK_ENABLED`, `SEARCH_ENABLED`, `VIDEO_SUMMARY_ENABLED`, `WEBPAGE_ENABLED`, `CHECKUP_ENABLED`; **default `True` (ON)**. REGISTRY **392**, Settings **364**, GROUPS **91** (+3 группы). |
| **D2** | Окна-модалки без промптов/моделей/ключей? | ✅ **ДА — раздельно.** Модули (операционные параметры+тумблеры) → «Модули»; редакторы промптов/моделей/ключей → только «Настройки AI». |
| **D3** | RAG-доли бюджета — в Модуле 2 или «Память»? | ✅ **«Память».** Все RAG-ключи (включая доли бюджета из `limits_chat_budgets`) → `#/ai/memory`; не-RAG остаток `limits_chat_budgets` остаётся в Модуле 2. |
| **D4** | test connection: эндпоинт/права/охват? | ✅ **ДА, per-block.** `POST /api/llm/test`; global admin; rate-limit; R17; **каждый визуальный блок** (по модулю) тестирует свои `key/model/base_url` → ошибка или 200. |
| **D5** | «Диагностика» vs «Статус» (сервер/логи)? | ✅ **Сервер и логи — на «Статус»** (просмотр); **настройки** логов/BetterStack/checkup → подраздел «Диагностика» (Модуль 9 / AI→Диагностика). |

### 8.3. Обновление счётчиков каталога (locked)

| Параметр | 10.5 (baseline) | 10.6 целевое |
|---|---:|---:|
| REGISTRY | 387 | **392** (+5 master-флагов) |
| Settings | 359 | **364** (+5) |
| GROUPS | 74 | **91** (Δ **+17**) |
| mapped на вкладки | 72 | **89** |
| content (`tab=None`) | 2 | 2 |
| infra | 28 | 28 |

> GROUPS-дельта (v2): базовые расщепления **+13** (74→87) + A3 `limits_rag` **+1** (87→88)
> + D1 **+3** (88→91) = **+17**. `flags_modules`→**7** групп (checkup-флаг → `flags_service`),
> что высвобождает слот под `limits_rag`. Санкционировано владельцем. **Ноль PG-DDL.**

### 8.4. Дельта задач (добавлено/уточнено; T-1200…T-1212)

- [x] **T-1200 — ✅ @Architect: ревизия `spec.md`/`design-project.md` → v2 (11.09.2026, 0 кода).**
  Внесены A1–A9: A1 (5 master-флагов default ON + реальные гейты; 392/91/364/mapped 89),
  A2 («один дом»), A3 (RAG→«Память»: 2 ключа → `limits_rag`; `limits_chat_budgets` 11→10,
  `limits_chat` 26→25), A4 (9 provider-блоков по модулям + `POST /api/llm/test`), A5/A8
  (`keys_youtube`→М6; `models_checkup`/`keys_betterstack`→М9; сервер/логи — «Статус»), A6/A7
  (emoji→Material-иконка в `#/how` и матрице), A9 (эксклюзивный аккордеон).
  Обновлены `spec.md` §1–§16 и `design-project.md` §3.4/§4/§10. **Готово к @Builder.**
- [x] **T-1201 — @Builder: 5 master-флагов default ON (D1/A1).**
  `FACTCHECK_ENABLED`/`SEARCH_ENABLED`/`VIDEO_SUMMARY_ENABLED`/`WEBPAGE_ENABLED`/`CHECKUP_ENABLED`
  (Settings + `_FLAGS`, default `True`), группы `flags_module_factcheck`/`flags_module_video_summary`/
  `flags_module_web` (+ существующие module-flag-группы для search/checkup). Регистр 392/91/364.
  Тумблеры **реально гейтят выполнение** (не только UI). (Расширяет T-1166/T-1172.)
- [x] **T-1202 — @Builder: emoji → иконка в «Как это работает» (`#/how`) (A6).**
  Заменить emoji-глифы на Material Symbols (тот же `ICONS`/`iconGlyph`); нет emoji в рендере;
  `content_info` не менять (контент — данные), менять только разметку/иконки.
- [x] **T-1203 — @Builder: emoji → иконка в матрице ролей (`#/access/roles`) (A7).**
  Секции/карточки матрицы — Material Symbols; маркер-тест «нет emoji» в матрице.
- [x] **T-1204 — @Builder: вынести настройки прокси + cookies из «LLM Провайдеры» в «Модули» (A8).**
  Определить целевой модуль(и) (Транскрипт/Выжимка/Скачивание — по спеке T-1200);
  `keys_youtube`/`limits_youtube_proxy`/cookies-ключи — новый дом; убрать из LLM Провайдеров.
- [x] **T-1205 — @Builder: настройки логов + BetterStack + checkup → подраздел «Диагностика» (A8/D5).**
  Просмотр сервера/логов остаётся на `#/` «Статус» (A5); в «Диагностику» уходят **настройки**
  (`limits_checkup`, `keys_betterstack`, log-settings). Без дублирования.
- [x] **T-1206 — @Builder: «Доступы и роли» — эксклюзивный аккордеон (A9).**
  Открытие одного подраздела (Матрица/Локальные админы/Администраторы) закрывает остальные;
  один открытый за раз (state + `aria-expanded`). Маркер-тест.
- [x] **T-1207 — @Builder: LLM Провайдеры — блоки ПО МОДУЛЯМ с per-block test (A4).**
  Каждый блок (прямые ответы, транскрипция, выжимка видео, checkup, embeddings, fallback и т.д.)
  = `base_url` + `model` + `api key` + кнопка «Проверить»; main перед fallback; ключ не утекает (R17).
  (Расширяет T-1176/T-1177.)
- [x] **T-1208 — @Builder: RAG-доли и все RAG-ключи → AI→Память (D3/A3).**
  Расщепить `limits_chat_budgets` (11→10): `limits.chat_budget_rag_ratio` → **NEW `limits_rag`**
  (`memory_rag`); `limits.chat_rag_dedup_overlap_ratio` из `limits_chat` (26→25) → `limits_rag`;
  не-RAG остаток — Модуль 2. Обновить `GROUPS`/`TAB_RULES`; GROUPS 74→91. (Уточняет T-1173;
  точный список — `spec.md` §6.1, `design-project.md` §10.3.)
- [x] **T-1209 — @Builder: enforce «один дом» (D2).**
  Модули не рендерят редакторы промптов/моделей/ключей (только чипы-ссылки); редакторы — в
  «Настройки AI». Никаких дублирующих input'ов. Маркер-тест.
- [x] **T-1210 — @Builder: контракт test-endpoint под per-block произвольные key/model/base_url (D4).**
  `POST /api/llm/test` принимает выбранный блок (не только имя провайдера); используется
  предоставленный key/model/base_url; возвращает ошибку (невалидный key/model) или 200;
  rate-limit + global admin + R17. (Расширяет T-1178.)
- [x] **T-1211 — @Builder: обновить каталог-инвариант и тесты под 392/91/364 (Δ GROUPS +17).**
  `test_param_catalog`, `test_frontend_tab_mapping`, parity-тесты; mapped 89.
- [x] **T-1212 — @Builder: маркер-тесты на новые пункты.**
  Нет emoji в `#/how` и матрице; proxy/cookies не в LLM Провайдерах; diagnostics-настройки;
  аккордеон; реальные гейты 5 флагов; per-block test.

### 8.4.1. Review-fix после ревью @Reviewer (T-1213…T-1218, 11.09.2026) — ВЫПОЛНЕНО

- [x] **T-1213 — @Builder: BLOCKER-1 — пункт navbar «Модули».**
  `navItems`: `modules` гейтится своим tab (`canView('modules')`), hubVisible — только
  `ai`/`access`. JS-тест: navItems = ровно 6 id (вкл. `modules`) для wildcard и негатив.
- [x] **T-1214 — @Builder: MAJOR-1 — 3 из 9 «Проверить» не работали.**
  `services/llm_probe.py`: ветка `search_keys` ДО проверки base_url (base не нужен);
  `embeddings`/`llm_guard` помечены `testable:false` (кнопки нет); llm_guard убран из
  KNOWN_BLOCKS и не шлёт timeout/retries как `model`. Плюс SSRF-минимум (https).
  Тесты probe на каждый блок + endpoint-параметризация.
- [x] **T-1215 — @Builder: MAJOR-2 — панели Сон/Ностальгия были мёртвым кодом.**
  Перенесены в `modal-body` и рендерятся по `activeModule.id`; данные грузит
  `_ensureModuleData` при открытии окна; мёртвые `activeTab === 'mod_*'` убраны.
  JS-тест: открытие окна Сон вызывает `loadDreamBeliefs`.
- [x] **T-1216 — @Builder: MODERATE-1 — черновики блоков терялись.**
  Добавлена кнопка «Сохранить» блока (`saveBlock` → `POST /api/config`, 409-протокол,
  секреты — только при новом вводе); duplicate-editors остаются как полный фолбэк.
- [x] **T-1217 — @Builder: MODERATE-2 + MINOR-1.**
  Глобальный `keydown`-Esc закрывает модалку; `ROUTE_ALIAS` нормализует legacy-hash
  (`#/ai/limits`→`#/ai`, `#/ai/sleep|nostalgia`→`#/modules`) через `history.replaceState`.
- [x] **T-1218 — @Builder: MINOR-2 + INFO.**
  Документирован `checkup_betterstack` (best-effort probe, без UI-кнопки); TTL-очистка
  `_LLM_TEST_LAST`; `content_media` рендерится в окне Модуля 6; async-гейт-тесты
  (flag OFF → UNHANDLED) для 5 модулей.

### 8.4.2. Review-approve minors @Reviewer (T-1219…T-1221, 11.09.2026) — ВЫПОЛНЕНО
- [x] **T-1219 — @Builder: MINOR-1 (security) — SSRF-префикс.**
  `_safe_base` через `urllib.parse.urlsplit`: https всегда; http — только при
  `hostname ∈ {localhost,127.0.0.1,::1}`; `http://localhost.evil.com` и
  `http://127.0.0.1.evil.com` отклоняются. Тесты на обход + точный loopback.
- [x] **T-1220 — @Builder: MINOR-2 (UX) — search_keys проверял один ключ.**
  Отдельные таргеты `search_keys:tavily`/`search_keys:exa` (per-field кнопки
  `testField`, `data-block`), `_probe_search(provider=...)`. Тесты probe + endpoint.
- [x] **T-1221 — @Builder: MINOR-3 (UX) — saveBlock не мог очистить поле.**
  `draft == null` = «не трогать», `draft === ''` = очистить (шлём `''`). JS-тест:
  очистка отправляется, без правок POST не идёт.

### 8.4.3. Scanner-миноры раунда 10.6 (T-1222…T-1223, 11.09.2026) — ВЫПОЛНЕНО
- [x] **T-1222 — @Builder: R10.6-3 (security/R17) — 422 эхоил `api_key`.**
  `web/app.py`: app-wide `RequestValidationError`-хендлер отдаёт только
  `loc`/`msg`/`type` (без `input`/`ctx`), тело запроса не логируется. Тесты:
  malformed `/api/llm/test` с `api_key` → 422 без ключа; generic-422 санитизирован.
- [x] **T-1223 — @Builder: R10.6-1 (UX) — дубли редакторов в LLM Провайдерах.**
  `groupedForTab` на вкладке `llm_providers` исключает ключи, покрытые
  provider-блоками (`providerCoveredKeys`, 21 из 37; остальные 16 — generic).
  JS-тест: покрытый ключ скрыт, не-блоковый показан, модульные вкладки не фильтруются.

### 8.5. Открытые вопросы
**НЕТ.** Все вопросы §5 `tasks.md`, §9 `design-project.md` и decision points D1–D5 — **ЗАКРЫТЫ**
ответами владельца 11.09.2026. Гейт T-1156 пройден; реализация разрешена.
