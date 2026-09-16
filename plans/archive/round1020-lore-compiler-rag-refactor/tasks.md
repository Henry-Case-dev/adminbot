# Эпик round1020 — «Летописец» (Lore Compiler) + глубокий рефакторинг RAG-архитектуры + UX/UI мини-аппа + Agentic AI + Справка UI

> **Статус: ✅ COMPLETED + DEPLOYED + ЗААРХИВИРОВАН** (16.09.2026). Фазы **A–H** выполнены; @Reviewer — **Approved**;
> @Scanner (re-audit) — **0 Critical / 0 High / 0 Medium / 0 Low** (открыто 5 Info); pytest **6546 passed / 0 failed**;
> деплой — коммит **`995cf83`** (фича) + **`741b77c`** (R18-вычистка кредов из архива 10.16), запушено; на сервере
> `systemctl` **active**, MainPID **2668878**, SQLite **`user_version=12`**. Архитектура смержена — `plans/ARCHITECTURE.md` **§45**.
> Папка фичи перенесена `plans/features/round1020-lore-compiler-rag-refactor/` → **`plans/archive/round1020-lore-compiler-rag-refactor/`** (@PM Step 8).
> **Human Gate пройден**, решения **О1–О7** зафиксированы (см. §Решения). Спеки/ADR — @Architect (Step 2): **ADR-1020-1…-8 DONE**.
> ⏸ **Открыто (human-pending, не блокер):** **T-1904** (живая UI-приёмка), **T-1931** (приёмка Справки). Follow-up: **T-1932** (fallback точки 7, R26).
> **Тип:** backend (память/RAG/тулы/промпты/LLM-движок) + frontend (TMA) + ops/CLI. **Приоритет:** Фаза A ✅ (гейт пройден) → **P0** (B, C) → **P1** (D, E, G) → **P2** (H).
> **Фазы:** **A** (read-only аудит ✅) → **B** (ядро памяти) → **C** («Летописец») → **D** (UX/UI) → **E** (фактчекер + техдолг) → **G** (Agentic AI, БЛОК 7) → **H** (Справка UI, БЛОК 8) → **F** (верификация/SPEC_READY/деплой/архив).
> **Нумерация:** продолжает T-1865 (10.19) → **T-1866 … T-1931 (66 задач)**.
> **ТЗ:** `plans/current_task.md` — БЛОК 0 (стр. 7–11), БЛОК 1 (14–45), БЛОК 2 (48–76), БЛОК 3 (88–140),
> БЛОК 4 (144–177), БЛОК 5 (181–211), БЛОК 6 (225–254), **UPD-раздел: ответы О1–О7 (278–291)**, **БЛОК 7 Agentic AI (293–319)**, **БЛОК 8 Справка UI (323–331)**.
> **Файл ТЗ — untracked + содержит plaintext-секрет (SSH): НЕ коммитить, значение не цитировать (R17, решение О6).**
> **Baseline:** HEAD `2f3e1f0` (docs-финал 10.19); pytest **6326 passed / 0 failed**; каталог **437/407/412/92/90/20**; SQLite **v11**; APP_VERSION 2.57.0.
> **Step 0 @Memory:** `plans/reports/global_map.md` + `plans/reports/round10.19_scanner_audit.md` (§10.4/§10.5) + `plans/MEMORY.md`.
> **Step 2 @Architect (вход):** `spec.md`, `adr-1020-1…-6`, отчёт Фазы A `plans/reports/round1020_llm_engine_audit.md`.

## Решения Human Gate (О1–О7) — зафиксировано 16.09.2026

| # | Решение владельца | Влияние на план |
|---|---|---|
| **О1** | **БЛОК 5.5 / 6.1 = verify-only.** Заново не пишем, ADR-1018-2 не переоткрываем. Ручной DeepDream привязать к кнопке **нового UI** и подтвердить, что работает. | T-1883, T-1906 — verify-only (2 задачи); UI-привязка проверяется после Фазы D (T-1904). |
| **О2** | **Time Injection — первым USER-блоком.** System-промпт **статичен**, **Prompt Caching НЕ ломать.** Вариант А. | T-1879 (инъекция в `payload_builder.py::build_messages`), ADR-1020-3 §Вариант А. |
| **О3** | **`compile_lore_story` — простой Feature Flag ВКЛ/ВЫКЛ, ДЕФОЛТ ON глобально.** Никакой поэтапной раскатки 10/50/100 %. | T-1887 (`flags.lore_compiler_enabled` default **true**), §8 переписан; откат — toggle OFF / `git revert`. |
| **О4** | **Новый ключ `limits.chat_timezone`.** Расписания сна/бэкапа не смешивать с временем диалогов. | T-1879; Δ каталога +1 ключ (не реюз `limits.summary_timezone`); фолбэк на него. |
| **О5** | **Глобальный `parse_mode = None` сохраняем.** Для историй Летописца **локально `parse_mode=HTML`** + **HTML-теги** в промпте (не Markdown). UI подтверждён полностью, структуру меню не менять. | T-1890/T-1891/T-1892 (HTML вместо markdown), ADR-1020-6 → HTML; Фаза D без изменений объёма. |
| **О6** | **Политика безопасности:** `plans/current_task.md` остаётся **untracked**, пароль в git **не коммитить**. | §3 (R17), §9. |
| **О7** | **Хранение историй:** аддитивная таблица **`lore_stories` без бампа `user_version`**. | T-1891, ADR-1020-4 (прецедент `smart_cache`/`bot_reply_parents`). |

## 0. Цель

Закрыть «слепые» места памяти бота, поднять LLM-движок до агентной архитектуры и дать пользователю новые продуктовые фичи:

1. **Аудит прежде ремонта (Фаза A — ✅ DONE).** Read-only инвентаризация LLM-движка (tool recursion, scratchpad/reasoning,
   сборка контекста, intent routing) — **до** проектирования блоков 1/2, чтобы не строить костыли поверх старого фундамента (ТЗ, стр. 78–80).
   Отчёт выдан текстом + сохранён в `plans/reports/round1020_llm_engine_audit.md`; **Human Gate A пройден (T-1871)**.
2. **Ядро памяти (Фаза B).** Тотальная инъекция метаданных во все промпты/тулы/воркеры (БЛОК 0); жёсткий роутинг тулов,
   фикс хронологии (ASC), рефакторинг `/summary` и `dig_into_lore` (БЛОК 2); Time Injection (первым user-блоком) + «Часовой пояс чата»,
   анти-галлюцинации + group-by-authors, persona fallback, фикс виджетов «Сводки» для безлимита `-1` (БЛОК 5).
3. **Новая фича «Летописец» (Фаза C).** Изолированный tool `compile_lore_story(topic)` — граф 1–2 уровня + хронология
   + storytelling-промпт (**HTML**) + механизм диффов/UPD (БЛОК 1). 7 → **8** инструментов; флаг **default ON**.
4. **UX/UI мини-аппа (Фаза D).** Критические баги binding/routing, досье участников, тикер досье, Liquid Glass,
   CSS Grid, sticky save-панель, human-readable labels, рестайлинг аккордеона Advanced (БЛОК 3). **МЕНЮ НЕ МЕНЯТЬ.**
5. **Фактчекер + техдолг (Фаза E).** Full Tool Access фактчекера + функциональный промпт (БЛОК 6.2/6.3); техдолг
   S10.19-15 / S10.19-23 / CLI retention (БЛОК 6.4).
6. **Agentic AI (Фаза G, БЛОК 7).** Tool recursion fail-safe + graceful degradation; парсинг `reasoning_content` + stripper
   reasoning-тегов + снятие канона «1-2 предложения» для `compile_lore_story`/`factcheck` (P0); единый Context Middleware
   (приоритет метаданных над бюджет-капом) + расширение `graph_facts` (`tg_message_id`, `forward_from`); EN-перевод
   всех `description` тулов + строгая типизация параметров.
7. **Справка UI (Фаза H, БЛОК 8).** Актуализация текстов раздела «Справка» (Летописец, Фактчек, безлимиты) с сохранением
   дерзкого ироничного стиля; удаление неактуальных механик.
8. **Верификация (Фаза F).** SPEC_READY-демонстрация логики владельцу **до деплоя** (прямое требование ТЗ, стр. 76); ревью, аудит, деплой, архив.

## 1. Контекст, доказательства и исторические конфликты (@Memory Step 0 + @Architect Step 2)

- **БЛОК 5.5 ⚠️ и БЛОК 6.1 🔴 — УЖЕ РЕАЛИЗОВАНЫ в раунде 10.18** (`plans/archive/sleep-manual-cascade-badges/`, **ADR-1018-2**,
  коммит `16a8c0b`, тесты `tests/test_sleep_manual_cascade_round1018.py`; API `POST /api/memory/dream/run`).
  Manual-прогон **безусловно** обходит gate/budget/window; диагностика пропусков Личности (в т.ч. `persona_disabled`)
  логируется (T-1717). → **verify-only** (решение О1); повторную реализацию НЕ планировать (T-1883, T-1906).
- **Имя тула:** в ТЗ `dig_into_lor` (опечатка), в коде — **`dig_into_lore`** (`services/tool_schemas.py:72`,
  реализация `services/tool_router.py::_dig_into_lore:413`). В задачах — только корректное имя.
- **Хроно-сортировка ASC уже есть для DirectChat** (`services/summary_memory.py:2316-2368`, канон **D206**,
  `sort_by_timestamp=True` c Epic 50/58.8). → БЛОК 2.6 = **расширение скоупа на остальных RAG-потребителей (аддитивно)**,
  не новая система; хелпер `order_rag_facts_asc`.
- **Аккордеон Advanced уже есть** (раунды 10.4 D + 10.11 F-11: `progressive_level`, `<details class="advanced">`).
  → БЛОК 3.8 = **рестайлинг** (сейчас нативный HTML-спойлер), не создание.
- **Tool recursion уже есть** (`services/tool_loop.py::chat_with_tools`, `TOOL_MAX_ROUNDS = 4` = 1 стартовый + до 3 раундов).
  → БЛОК 4 = read-only ОПИСАНИЕ (Фаза A, готова). **БЛОК 7.1 = НОВЫЙ скоуп** — fail-safe/degradation поверх существующего цикла.
- **Reasoning/scratchpad в движке ОТСУТСТВУЕТ** (аудит Q2): `llm_client.generate_chat` читает только `content`
  (`services/llm_client.py:1005-1032`); reasoning-теги уедут пользователю (`direct_chat_service.py:656` — только `str(raw).strip()`).
  → БЛОК 7.2 = новый рабочий пакет (T-1920…T-1922).
- **Контекст собирается монолитно** (`services/payload_builder.py:12-23` — 1 system + 1 user; `_apply_context_budget` режет по символам/токенам).
  → БЛОК 7.3 = единый Context Middleware + приоритет метаданных (T-1923/T-1924).
- **`graph_facts` не имеет `tg_message_id`/`forward_from`** (`services/database.py:286-296`); forward-атрибуты есть у
  `smart_messages` (`:209-221`). → БЛОК 7.3 требует расширения схемы + миграции pg+sqlite (T-1924).
- **`compile_lore_story` НЕ существует** — реально новая фича; текущих инструментов **7**
  (`execute_web_search`, `query_chat_memory`, `dig_into_lore`, `summarize_video`, `download_media`, `get_bot_health`, `get_recent_history`)
  → станет **8**. `description` всех схем — на русском (`tool_schemas.py`), шапка файла требует ревизии канона 3.3.
- **`factcheck_service.py` тулов не имеет** — посылка ТЗ (БЛОК 6.2) верна.
- **Справка (БЛОК 8) — код-канон `services/info_service.py::DEFAULT_INFO_TEXT`** (+ байт-зеркало `info_text.md`,
  `INFO_CANON_VERSION`, `KNOWN_INFO_SNAPSHOTS`), гайд — `plans/docs/intelligence_user_guide.md`; рендер — `web/index.html:2564-2630`.
  Любая правка = бамп версии + слепок (правило `info_service.py:142-144`).
- **Техдолг БЛОК 6.4 подтверждён:** **S10.19-15** (двойной `chat_usage.key_status` в «Сводке»,
  `services/oversight.py:203-216`), **S10.19-23** (fsync есть у файла, нет у каталога,
  `services/memory_maintenance.py:389-425`), **CLI `manage.py retention`** (dry-run default; работа при живом боте → WAL/снапшот).
  Источник: `plans/reports/round10.19_scanner_audit.md` §10.4/§10.5, `plans/reports/global_map.md`.
- **S10.18-29 (Low, наследство 10.18):** `run_once(deep=False)` не выставлял `_manual_deep_until` — по факту **закрыт**
  фикс-проходом 10.18 (§14 задачи F2); при работе по БЛОКУ 5.5/6.1 — перепроверить, не переоткрывать вслепую.

## 2. Требования (сводно по фазам)

**Фаза A (read-only, БЛОК 4) — ✅ DONE:**
- [x] По каждому из 4 вопросов — «Текущее состояние (файл + функция)» и «Узкие места (Blockers)».
- [x] Отчёт **текстом** пользователю + файл `plans/reports/round1020_llm_engine_audit.md`.
- [x] **Никаких** коммитов/правок кода/файлов — только чтение и отчёт.

**Фаза B (БЛОК 0, 2, 5):**
- [ ] Единый канонический формат метаданных `[Дата Время | Автор | ID | Переслано: откуда]: Текст` — **в смысле критерия «метаданные фактически присутствуют»** (ADR-1020-1 ред. 3: ярус A — канонический префикс там, где нет временного маркера; ярус B — эквивалентная явная сериализация, напр. XML-атрибуты `<chat_history>`); остаток фазы B — точки **2/3/8/13** (T-1874).
- [ ] Жёсткие `description` инструментов в JSON Schema (роутинг `dig_into_lore` ↔ `compile_lore_story`).
- [ ] Пересортировка Top-K RAG по `created_at`/`timestamp` **ASC** перед инжектом (расширение D206 на все потребители).
- [ ] `/summary`: контрастная маркировка архива (согласно БЛОК 0) + правило саммаризатора «архив ≠ свежее».
- [ ] `dig_into_lore`: сырые релевантные факты + промпт против сухой статистики.
- [ ] **Time Injection — первым USER-блоком** (О2), system-промпт статичен, Prompt Caching не ломать; глобальная чат-настройка **«Часовой пояс чата»** — новый ключ `limits.chat_timezone` (О4).
- [ ] Анти-галлюцинации: `{"total_mentions", "mentions_by_authors", "snippets"}` + Anti-Hallucination Guard.
- [ ] Persona fallback («изящный слив» в спорах) — без выдумывания цифр.
- [ ] «Сводка»: реактивность виджетов «Бюджет контекста»/«Дневной фон» при `-1` → «Безлимит (∞)».
- [ ] (verify-only) БЛОК 5.5 — подтвердить, что пайплайн DeepDream/PersonalityExtractor не падает и логирует причины пропуска (О1).

**Фаза C (БЛОК 1):**
- [ ] Tool `compile_lore_story(topic)`: граф (узел + связи 1–2 уровня + привязанные Убеждения) + хронология (earliest/latest + 2–3 диалога максимальной плотности, ASC) → JSON `{graph_facts, chronological_dialogs}`.
- [ ] Storytelling-промпт (структура «завязка → развитие → статус-кво», постирония, имена, цитаты, **HTML-теги** — О5).
- [ ] Механика повторных запросов: база + блок **UPD (Свежак)**; хранилище `lore_stories` аддитивно, **без бампа `user_version`** (О7).
- [ ] Флаг `flags.lore_compiler_enabled` — **default ON** глобально, простой тумблер ВКЛ/ВЫКЛ (О3); доставка истории — локальный `parse_mode=HTML` (О5).

**Фаза D (БЛОК 3):**
- [ ] Глобально: binding/routing фиксы, Liquid Glass, CSS Grid, sticky save, human-readable labels, рестайлинг Advanced-аккордеона.
- [ ] Новое: досье участников с ручным редактированием; тикер досье в «Сводке».
- [ ] **Структура меню/навигация/основные разделы НЕ меняются.**

**Фаза E (БЛОК 6):**
- [x] (verify-only) БЛОК 6.1 — ручной триггер DeepDream уже есть; подтвердить UI-доступность кнопки (О1).
- [x] Full Tool Access фактчекера (`dig_into_lore`, `compile_lore_story`, веб-поиск) + метаданные БЛОК 0.
- [x] Функциональные инструкции промпта фактчекера (умный выбор инструментов; использование меток даты/автора). Tone of voice — не переписывать.
- [x] Техдолг: S10.19-15, S10.19-23, CLI retention.

**Фаза G (БЛОК 7, Agentic AI):**
- [x] 7.1 Tool Recursion **fail-safe**: graceful degradation при исчерпании раундов/ошибке на раунде > 0 (частичный ответ или саркастичная заглушка, НЕ тишина) + логирование потерянных раундов (`services/tool_loop.py`).
- [x] 7.2 Scratchpad/Reasoning: парсинг `reasoning_content` (`services/llm_client.py`); stripper reasoning-тегов перед отправкой в Telegram; **P0** — локальное снятие канона «1-2 предложения» для `compile_lore_story`/`factcheck` (канон-миграция).
- [x] 7.3 Context Assembly: единый **Context Middleware**; метаданные (дата/время/автор) приоритетнее бюджет-капа (обрезаем контент, сохраняем заголовок); расширение `graph_facts` (`tg_message_id`, `forward_from`) + миграция sqlite (**PG — no-op**).
- [x] 7.4 Schemas & Routing: все `description` JSON-схем тулов — **на английском** + строгая типизация параметров (`additionalProperties: false`, `required`, `enum`).

**Фаза H (БЛОК 8, Справка UI):**
- [ ] Актуализация текстов «Справка»/«Гайд»: убрать неактуальные механики, описать **Летописца**, обновлённый **Фактчек**, объяснить **безлимиты** (`-1` → «Безлимит (∞)», retention `0` → «Вечно»).
- [ ] **Сохранить дерзкий ироничный стиль**, не превращать в корпоративный мануал.

**Фаза F:** SPEC_READY владельцу → ревью → аудит → деплой → архив.

## 3. Constraints (инварианты)

- **R17:** логи/отчёты/спеки — без секретов и текстов; `plans/current_task.md` **untracked**, содержит plaintext SSH-секрет —
  **не коммитить, не копировать значение** ни в backlog, ни в задачи, ни в spec/ADR/KG (решение О6).
- **R16:** id — ключ, не имя (контракты API аддитивны).
- **Меню мини-аппа НЕ менять** (глобальное правило БЛОК 3, стр. 92): правки только внутри существующих вкладок/модалок.
- **Порядок роутеров `bot.py` не менять** (только DI-kwargs); `media/` и `.env` **не трогать**.
- **Prompt Caching (О2):** system-промпт **статичен между запросами**; Time Injection — **первым user-блоком**; динамика — только в user-контенте.
- **`parse_mode` (О5):** глобально `None`; локально `HTML` **только** для режима Летописца (`ctx.lore_compiled`); истории — с HTML-тегами, не Markdown.
- **Флаг `flags.lore_compiler_enabled` — default ON** (О3); никакой поэтапной раскатки; откат — toggle OFF/`git revert`.
- **Каноны промптов** живут ТОЛЬКО в `plans/docs/canon/`; правка эталона = код + эталон + тесты **одним атомарным коммитом**
  (ADR-1013-3; `PROMPT_MIGRATIONS`). Правки промптов в фазах B/C/E/G/H — все канон-миграции.
- **DDL:** разрешён (project.md §«Политика DDL»). Заявлены: **`lore_stories`** — аддитивно, **без** бампа `user_version` (О7);
  **расширение `graph_facts`** (`tg_message_id`, `forward_from`) — миграция **pg+sqlite**, идемпотентно + обратный путь (решение по `user_version` — за @Architect, ADR-1020-7).
- **Каталог параметров:** правки = **санкционированный Δ** с точным числом (эталон `tests/test_param_catalog.py`).
  Ожидаемый Δ = **+2 ключа** (`flags.lore_compiler_enabled`, `limits.chat_timezone`) + N текстов.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check`;
  русские conventional commits.
- **Таймауты shell-команд** — по project.md (pytest ≤ 300с с `--timeout=120`).
- `⏸` = ждёт человека (не закрывать без вердикта владельца).

## 4. Зависимости / порядок

- **Фаза A закрыта** (гейт T-1871 пройден) → **Step 4 @Builder разрешён**.
- **Фаза B блокирует Фазу C** (роутинг 2.5 ссылается на описание C; метаданные нужны всем).
- **Фаза C блокирует Фазу E** (фактчекер получает `compile_lore_story`) и **Фазу G.2c** (снятие канона для `compile_lore_story`).
- **Фаза E блокирует Фазу G.2c** (снятие канона для `factcheck`) и **Фазу H** (тексты Справки описывают Фактчек).
- **Фаза B блокирует Фазу G.3** (Context Middleware строится поверх канонического форматтера §2.2).
- **Фаза D** от A/B не зависит (только UI), но **О1-проверка UI-кнопки** manual DeepDream (T-1906) — после T-1904.
- **Порядок:** **A ✅ → {B ∥ D} → C → E → {G ∥ H} → F** (фазы G и H могут идти параллельно после E; внутри G — 7.1 ∥ 7.2a-b ∥ 7.4, затем 7.2c, 7.3).
- **Пересечения файлов (сводить ступенями):**
  - B/C/E/G.4 делят `services/tool_schemas.py` → вливать **B → C → E → G.4** (T-1875 → T-1887 → T-1907 → T-1925).
  - C/G.1 делят `services/tool_loop.py` (C — только сигнал режима; G.1 — fail-safe) → вливать **C → G.1** (T-1887 → T-1919).
  - B/G.3 делят `services/canonical_context.py` + `direct_chat_service.py` (`_apply_context_budget`) → вливать **B → G.3**.
  - C/E/G.2c/H делят канон `chat_prompts.py`/`factcheck_prompts.py`/`lore_prompts.py` + `prompt_migrations.py` → **все канон-миграции атомарно, ступенями C → E → G.2c; H — только тексты справки (`info_service.py`), канон промптов не трогает**.
  - B/D/E/G.3 делят `services/param_catalog.py` (каталог-Δ) и `web/*` → свести Δ каталога единым гейтом (T-1885/T-1904/T-1927).
  - D/H делят `web/*` → вливать **D → H** (H правит контент/рендер Справки; D — общие стили).
  - G.3/H делят `services/info_service.py`? — нет; H трогает `info_service.py` + `info_text.md` + `plans/docs/intelligence_user_guide.md`.
- **Вверх:** отчёт Фазы A → spec/ADR Step 2 (`plans/ARCHITECTURE.md` Merge — Step 7).

## 5. Definition of Done (эпик)

- [ ] Отчёт-аудит (Фаза A) выдан текстом + сохранён; **Human Gate A пройден**, решения О1–О7 зафиксированы в §Решения.
- [ ] Метаданные БЛОК 0 применяются во всех путях контекста (тесты на формат + отсутствие «голого» текста); метаданные не режутся бюджет-капом.
- [ ] Роутинг тулов однозначен (все `description` EN, строгая типизация); хронология ASC во всех RAG-потребителях; `/summary` разделяет архив и свежее; `dig_into_lore` не отделывается счётчиками.
- [ ] Time Injection (первым user-блоком) + «Часовой пояс чата» (`limits.chat_timezone`) работают; prompt-cache не сломан; анти-галлюцинации подтверждены тестом `mentions_by_authors`; `-1` → «Безлимит (∞)».
- [ ] `compile_lore_story` реализован, зарегистрирован (**8** инструментов), выдаёт storytelling-историю с UPD-блоком при повторном запросе; доставка локально `parse_mode=HTML`; флаг **default ON**, тумблер OFF → тул недоступен.
- [ ] `lore_stories` — аддитивна, **без бампа `user_version`**.
- [ ] Agentic AI: лимит раундов/ошибка late-round → **не тишина** (graceful degradation + логирование); `reasoning_content` парсится, reasoning-теги вырезаются; канон «1-2 предложения» снят локально для `compile_lore_story`/`factcheck`; `graph_facts` расширен (`tg_message_id`, `forward_from`) с миграцией pg+sqlite.
- [ ] UI: критические баги закрыты, досье/тикер работают, стиль Liquid Glass/Grid/sticky/labels/аккордеон применены; меню НЕ изменено.
- [ ] Фактчекер видит локальные тулы; промпт функционален (tone of voice сохранён); техдолг S10.19-15/S10.19-23/CLI retention закрыт.
- [ ] Справка (БЛОК 8) актуализирована (Летописец/Фактчек/безлимиты), стиль сохранён, `INFO_CANON_VERSION` бампнут + слепок.
- [ ] **SPEC_READY показан владельцу ДО деплоя** (логика/пайплайны/флаги/Δ каталога).
- [ ] Полный `pytest` **0 failed**; JS-гейты чистые; каталог-Δ санкционирован; R17-скан чист; `git diff --check` clean.
- [ ] Верификация живая: человек прошёл UI-сценарии, проверил «Летописца», кнопку manual DeepDream (О1) и Справку; @DevOps-деплой по протоколу (пароль в репо НЕ хранится).

## 6. Чек-лист задач

### Фаза A — READ-ONLY аудит LLM-движка (БЛОК 4) — ✅ DONE

- [x] **T-1866 (@Architect):** аудит **Tool Recursion** — `services/tool_loop.py::chat_with_tools` (`TOOL_MAX_ROUNDS=4`); вывод: рекурсия **есть**, multi-turn. ✅
- [x] **T-1867 (@Architect):** аудит **Scratchpad / Reasoning** — `content`-only, теги не вырезаются, доставка plain-text. ✅
- [x] **T-1868 (@Architect):** аудит **Scaffolding & Context Assembly** — монолит `payload_builder` + ≥10 точек подачи контекста. ✅
- [x] **T-1869 (@Architect):** аудит **Agentic Factorization** — один универсальный промпт + rule-based Fast-Track. ✅
- [x] **T-1870 (@Architect):** сводный отчёт `plans/reports/round1020_llm_engine_audit.md` + текстовая выжимка. ✅
- [x] **T-1871 (@PM + @Reviewer, гейт) — Human Gate A:** ✅ **пройден** (О1–О7, 16.09.2026). Фаза A **закрыта**.

### Фаза B — Ядро памяти: метаданные, роутинг, хронология, анти-галлюцинации (БЛОК 0 + 2 + 5)

- [x] **T-1872 (@Architect, гейт):** `spec.md` + **ADR-1020-1** (контракт метаданных, БЛОК 0), **ADR-1020-2** (роутинг тулов + ASC-хронология + `/summary` + `dig_into_lore`), **ADR-1020-3** (Time Injection **Вариант А** + `limits.chat_timezone` + анти-галлюцинации + persona fallback). SUPERSEDE/AMEND: **D206/Epic 50-58.8** (расширение ASC), канон **R11**, `F-15` §4 (`dig_into_lore`). **Статус: DONE (Step 2, ADR-1020-1…-3 созданы).**
- [x] **T-1873 (@Builder):** БЛОК 0 — модуль `services/canonical_context.py::format_context_item` (kind `msg`/`fact`/`archive`) + инвентаризация **14 точек** подачи контекста (§2.3 спеки) с перечнем применения (Сон, Саммари, тулы, базовый промпт, воркеры). **DONE:** модуль + `CONTEXT_POINTS` (14) + `resolve_item_id` + `format_chat_time`; тесты `tests/test_memory_core_round1020.py::TestFormatContextItem`.
- [x] **T-1874 (@Builder):** БЛОК 0 — закрыть подачу «голого» текста по критерию **«метаданные фактически присутствуют»** (ADR-1020-1 ред. 3, §«Разрешение конфликта T-1874»; spec §2.2/§2.3). **Конфликт разрешён @Architect:** из 14 точек **остаток фазы B — только точки 2, 3, 8, 13**.
  - **ПРИМЕНИТЬ формат (ярус A, точки 2/3/8/13):** (2) `<Global_Context>` verbatim-хвост — `direct_chat_service._build_global_context:2082-2106` → `format_context_item(ts=row["timestamp"], author=_speaker_tag(...), item_id=resolve_item_id(tg_message_id=row["tg_message_id"], message_id=row["id"]), forward_source=row["forward_source"] if is_forward else None, kind="msg")`; (3) thread/branch — `_collect_thread_chain`/`_chain_line`/`_render_thread`/`_render_branch`: расширить внутренний кортеж цепочки метаданными user-хода (`timestamp`, `tg_message_id`/`id`, `is_forward`, `forward_source`); **бот-ход**: ts **опускается** (`bot_replies` времени сообщения не хранит, `last_used_at` — время доступа; выдумывать = нарушение R16), ID = `tg:<current_id>`, автор = `_resolve_bot_name()`; (8) `get_recent_history` → `_history_lines:928-944`; (13) фактчек `<chat_context>` → `services/chat_context.py:32`.
  - **ПОДТВЕРДИТЬ эквивалент (не трогать код):** 1 `<chat_history>` (XML-атрибуты — байт-инвариант), 4/5/14 (`[ММ.ГГГГ | Автор: X]` — ts+author; `fact:ID`/forward → фаза G/T-1924), 7 основная ветка, 10, 11, 12; 6/9 уже каноничны.
  - **Сопутствующие фиксы (обязательны):** `strip_context_header(line)` (новый хелпер) → применить в `direct_chat_service._line_markers:287-300` (первое `:` уедет в заголовок `msg:<id>` → сломает E1 keep-importance) и в `summary_memory._fact_tokens:1007-1010` (F2-дедуп ↔ заголовок); служебные метки `<Global_Context>` (`«фон: …»`/`«широкий фон: …»`) и `_SELF_ECHO_INSTRUCTION` — allowlist, не форматировать.
  - **Сознательное обновление снапшотов (атомарно с кодом, `fake_time`):** точки 2/3 — `tests/test_direct_chat.py`, `tests/test_direct_chat_prompts.py`, `tests/test_context_limits_round1019.py`, `tests/test_budget_unlimited_round1019.py`; точки 8/13 — соответствующие тесты `tool_router`/`chat_context`/фактчека (точный перечень фиксирует @Builder по факту `pytest -q`). **Всё остальное расхождение — сигнал регрессии, а не «обновить снапшот».**
  - **Вне скоупа (PENDING, Р6 ADR):** fallback-ветка точки 7 (`vector_search` → `list[str]`, общий контракт с `summary_generator`) — follow-up-задача, предлагается @PM **T-1932** (`[ММ.ГГГГ | fact:ID]: текст`, без смены текущего контракта); ID/forward фактов — фаза G/T-1924.
  - **Файлы:** `services/direct_chat_service.py`, `services/tool_router.py`, `services/chat_context.py`, `services/canonical_context.py` (или `context_middleware.py` — хелпер), `services/summary_memory.py` (`_fact_tokens`), + тесты.
  - **DoD (дословно):** *все 14 точек подачи контекста проходят инвентаризационный тест «нет голого текста», генерируемый из `CONTEXT_POINTS` (per-point pattern: `canonical` / `xml_attrs` / `bracket_header` / `label_exempt`) — т.е. в каждом промпте нет строк-элементов данных без временного маркера (при наличии ts в источнике) и без автора (при наличии автора); точки 2/3/8/13 рендерятся каноническим `format_context_item`; поля, отсутствующие в источнике, опущены (R16), выдуманных ID/имён нет; `_line_markers` (E1) и `_fact_tokens` (F2) работают через `strip_context_header`; тесты R42/R46/D206 зелёные; замер `facts=%d | chars=%d` до/после зафиксирован.*
  - **DONE (ред. 3):** закрыты **точки 2/3/8/13** каноническим `format_context_item` (ярус A): `_build_global_context._context_row_line` (ts/автор/ID/forward из `get_smart_window`-строк), `_ChainItem` + `_chain_line` (user — всё из `smart_messages`; бот — **ts опущен**, ID `tg:<current_id>`, R16), `tool_router._history_lines`, `chat_context.format_chat_context`. Сопутствующие фиксы (R23): новый `canonical_context.strip_context_header` применён в `direct_chat_service._line_markers` (E1) и `summary_memory._fact_tokens` (F2); служебные метки (`«фон: …»`/`«широкий фон: …»`/`_SELF_ECHO_INSTRUCTION`) — allowlist `CONTEXT_LABEL_EXEMPT_PREFIXES`/`is_label_exempt`, не форматируются. Реестр `CONTEXT_POINTS` расширен `representation` + per-point `pattern`; инвентарный тест «нет голого текста» **генерируется из реестра** (`tests/test_memory_core_round1020.py::test_no_bare_text_generated_from_registry`, 14 параметров) + `test_registry_samples_cover_all_points`. Осознанно обновлены снапшоты `test_direct_chat.py`/`test_epic65.py`/`test_recent_history_tool_round1015.py`. **Замер:** TOTAL facts=80→80, chars=3800→6492 (точка 2: 990→1694; 3: 990→1610; 8: 890→1594; 13: 930→1594). **Тесты:** целевой набор 409 passed; полный `pytest tests/` **6382 passed** (R42/R46/D206 зелёные). Скоуп: fallback точки 7 и ID/forward фактов (G/T-1924) НЕ трогались.
- [x] **T-1875 (@Builder):** БЛОК 2.5 — роутинг-`description` в JSON Schema для **пары** `dig_into_lore` ↔ `compile_lore_story` (**EN**, дословно по ТЗ; `services/tool_schemas.py`); `tool_calling`-снапшот + тест роутинга (фразы → ожидаемый тул). **Зависит:** T-1873. **Ступень:** `tool_schemas.py` вливается до T-1925. **DONE (dig_into_lore EN; парная `compile_lore_story` — Фаза C/T-1887); снапшот-тест обновлён осознанно.**
- [x] **T-1876 (@Builder):** БЛОК 2.6 — хелпер `order_rag_facts_asc(facts)` + ASC перед рендером во **всех** потребителях `build_rag_context`/`get_rag_context` (`search_service.py:78`, `factcheck_service.py:60`, `summary_generator.py:162`, `tool_router.py:392`, `web/youtube_summarizer_service.py`); **direct-путь** — ASC после дедупа/реранка, перед `_build_rag_block`. **DoD:** состав top-K не изменился (снапшот), D206-тесты зелёные. **DONE:** все потребители через `sort_by_timestamp=True`; direct-путь — `order_rag_facts_asc(kept)`. **Ред. 3: без изменений** (ASC/D206 — байт-инвариант, разрешение конфликта T-1874 его не трогает; норматива «форматировать факты» в B нет — только G/T-1924).
- [x] **T-1877 (@Builder):** БЛОК 2.7 — `/summary`: маркировка архива `format_context_item(kind="archive")` в `_compose_user_content` + правило канона `SYSTEM_PROMPT` «архив = лор/флешбэк, КАТЕГОРИЧЕСКИ не свежее» (**канон: код + `plans/docs/canon/` + `prompt_migrations.py` + слепок `PREV_SUMMARY_*` — одним коммитом**). **Зависит:** T-1873. **DONE:** `PREV_R2020_SUMMARY_SYSTEM_PROMPT` + ступень миграции + `backlog.md`.
- [x] **T-1878 (@Builder):** БЛОК 2.8 — `dig_into_lore` (`services/tool_router.py::_dig_into_lore`): JSON-контракт `{total_mentions, mentions_by_authors, first_seen, last_seen, snippets, facts}`; `snippets` непусты при попаданиях; новый `db.search_messages_fts_count_by_author` (GROUP BY author, R16-резолв имени). Промпт тула — «раскрой суть: что, кто, последствия» (**канон**). **DoD:** осознанная правка снапшот-тестов plain→JSON (точное число фиксирует @Builder). **DONE:** +db-метод с `by_author`; канон-блок АНТИ-ГАЛЛЮЦИНАЦИИ (T-1880) покрывает «что/кто/последствия»; обновлено 8 снапшот-тестов `tests/test_tool_router.py` (plain→JSON).
- [x] **T-1879 (@Builder):** БЛОК 5.1 — **О2/О4**: Time Injection `[Текущее время в чате: DD.MM.YYYY, HH:MM, День недели]` **первым USER-блоком** в `services/payload_builder.py::build_messages` (system статичен — Prompt Caching не ломать) + новый ключ **`limits.chat_timezone`** (per-chat select, человеческие названия, фолбэк на `limits.summary_timezone`, который **не трогаем**) + селектор «Часовой пояс чата» в существующем разделе «Поведение»/«Прямые ответы» (`mod_direct`; меню не менять). **Файлы:** `payload_builder.py`, `services/param_catalog.py`, `broadcast/prompts`-каскад, `web/app.js`. **DoD:** тест «строка времени в первом user-блоке, system-байты неизменны». **DONE:** `build_messages(time_line=…)` + `_chat_time_line` в direct + `CHAT_TIMEZONE` (select, group `limits_chat_behavior`).
- [x] **T-1880 (@Builder):** БЛОК 5.2 — анти-галлюцинации: group-by-authors (T-1878) + **Anti-Hallucination Guard** в каноне `CHAT_SYSTEM_PROMPT`: «Цифры — только из JSON; разделяй, сколько писал собеседник, а сколько другие; не выдумывать» (**канон-миграция**). **DONE:** блок `АНТИ-ГАЛЛЮЦИНАЦИИ:` + слепок `PREV_CHAT_R2020_SYSTEM_PROMPT` + ступень миграции + `architecture.md`.
- [x] **T-1881 (@Builder):** БЛОК 5.3 — **Persona fallback** («изящный слив»): абзац канона `CHAT_SYSTEM_PROMPT` — при поимке на нестыковке без подтверждения в памяти не выдумывать цифры, признать косяк саркастично/токсично, остаться в фактах. **Тон не переписывать** (**канон**). **DONE:** блок `ЕСЛИ ПОЙМАЛИ НА НЕСТЫКОВКЕ:`.
- [x] **T-1882 (@Builder):** БЛОК 5.4 — фикс «Сводки»: реактивность виджетов «Бюджет контекста»/«Дневной фон» по `chat_id` (обязательное перечитывание `chat_params` при смене чата); при `-1` → **«Безлимит (∞)»** (backend `services/oversight.py` + `web/app.js`). Один запрос при переключении (связано со S10.19-15). **DONE:** `_limits_block` — ОДИН `key_status`/чат (S10.19-15); `status_service.build_snapshot` — per-chat резолв (unlimited → «Безлимит (∞)»); `setActiveChat` → `loadStatus`+`loadOversight` один раз; тест `seen == [-100]` обновлён.
- [x] **T-1883 (@Builder) — ⚠️ VERIFY-ONLY (О1):** БЛОК 5.5 — подтвердить, что DeepDreamWorker/PersonalityExtractor не падают и логируют причину пропуска (сделано в 10.18/ADR-1018-2, T-1717); при пробеле — только диагностические логи. **Повторную реализацию НЕ создавать, ADR не переоткрывать.** **VERIFIED:** `[persona_traits] skip | reason=persona_disabled` (`dream_worker.py:1637`) + `[deep_sleep] skip | reason=…` + `[dream] WARNING skip: gate/budget`; тесты `test_sleep_manual_cascade_round1018.py`, `test_dream_persona_traits.py` — зелёные. Кода не меняли.
- [x] **T-1884 (@Builder):** тесты B — формат `format_context_item` (все kind, R16-опускание пустых полей), «нет голого текста» (14 точек), ASC-порядок у всех потребителей, маркировка архива, `dig_into_lore` (сырые факты + `mentions_by_authors`), Time Injection в первом user-блоке + `limits.chat_timezone`, `-1` → «Безлимит (∞)», один `chat_params`-запрос. **DONE:** `tests/test_memory_core_round1020.py` (27 тестов) + обновлённые снапшоты. **DELTA (ред. 3, ADR-1020-1):** пункт «инвентарный тест „нет голого текста“» **переоформлен** — тест **генерируется из реестра** `CONTEXT_POINTS.representation` (`canonical`/`xml_attrs`/`bracket_header`/`label_exempt`) и **приходит вместе с T-1874** (в T-1884 проверялся только `len(CONTEXT_POINTS) == 14`); критерий — §2.2 спеки (метаданные фактически присутствуют в любой явной форме), а не «каждая строка начинается с `[`».
- [x] **T-1885 (@Reviewer + @PM, гейт):** ревью B — DoD, R16-аддитивность, канон-атомарность, каталог-Δ (+1 ключ tz), R17, prompt-cache. **PASSED (Step 5 @Reviewer, `plans/reports/round1020_reviewer.md`):** 14 точек + инвентарный тест, header-safe усечение, Time Injection первым user-блоком (system статичен), `limits.chat_timezone` +1; 0 Critical/High.

### Фаза C — Новая фича «Летописец» (БЛОК 1)

- [x] **T-1886 (@Architect, гейт):** `spec.md` + **ADR-1020-4** (контракт `compile_lore_story(topic)`, пайплайн граф+хронология, storytelling-промпт, диффы/UPD, `lore_stories`, флаг) + **ADR-1020-6** (доставка: локальный `parse_mode=HTML`, снятие канона 1-2 предложений). **Решения О3/О5/О7 зафиксировать.** Зависимость: гейт T-1885. **Статус: DONE (Step 2, ADR-1020-4/6 созданы).**
- [x] **T-1887 (@Builder):** регистрация 8-го инструмента: JSON Schema в `services/tool_schemas.py`, dispatch в `services/tool_router.py`, доступ из DirectChat (`services/direct_chat_service.py`), сигнал режима из `services/tool_loop.py` (без правок цикла), флаг **`flags.lore_compiler_enabled` (default ON — О3)**. **DoD:** снапшот 8 инструментов; OFF → тул недоступен.
  - **DONE:** `TOOL_COMPILE_LORE_STORY` (EN-description дословно по ТЗ, `topic` required, `additionalProperties:false`) + `active_tools()` (ON → 8, OFF → 7 прежних имён, снапшот не мутируется); dispatch `_compile_lore_story` + `ToolContext.lore_compiled` (сигнал режима; сам цикл `chat_with_tools` не менялся — только docstring); `ToolDeps.llm` (DI из `bot.py`); флаг `flags.lore_compiler_enabled` (settings default **True** + запись каталога `flags_module_direct`, О3); DirectChat резолвит флаг per-chat → отдаёт 8/7 схем. **Тесты:** снапшот 8, OFF→7, description-роутинг (`test_tool_schemas.py::TestToolSchemas`, `tests/test_lore_compiler_round1020.py::TestCompileLoreStoryTool`).
- [x] **T-1888 (@Builder):** Шаг А — `db.lore_graph_slice(chat_id, topic, depth=2)`: узел топика + связи 1–2 уровня (взаимодействия + привязанные Убеждения) → `graph_facts` (ASC, детерминизм, `format_context_item(kind="fact")`). **Файлы:** `services/database.py`, `services/lore_compiler_service.py` (новый).
  - **DONE:** `DatabaseService.lore_graph_slice` — casefold-матч узла топика (`nodes`, скан по id, детерминизм) → BFS рёбер в ОБЕ стороны (`edges`: relation_type/weight/`fact_id`-provenance ADR-1018-3 D1) → факты/Убеждения `graph_facts` по `edge.fact_id`; ASC по `(rag_ts, id)`. Рендер канонический (`format_context_item(kind="fact")` + `resolve_item_id` + stale-суффикс) — в `LoreCompilerService._graph_facts`; рёбра без факта — честной строкой связи. Ошибки → пустой срез + WARNING.
- [x] **T-1889 (@Builder):** Шаг Б — `db.lore_dense_dialogs(...)`: `earliest`/`latest` упоминаний топика + 2–3 диалога максимальной плотности (окна, топ-3 бакета, полный текст окна) **строго ASC** → `chronological_dialogs` (`format_context_item(kind="msg")`). **DoD:** тест порядка ASC + честный пустой случай.
  - **DONE:** `DatabaseService.lore_dense_dialogs(chat_id, match_query, max_dialogs=3, window_minutes=30, since_ts=0)` — точный COUNT + `earliest`/`latest`, жадное бакетирование FTS-совпадений, топ-3 бакета по плотности (тай-брейк — раннее окно), ПОЛНЫЙ текст окна строго ASC (`timestamp, id`, включая не-совпавшие соседние сообщения); `since_ts` — UPD-окно. Честный пустой случай (`total=0`, пустые dialogs). Рендер — `format_context_item(kind="msg")`. **Тесты:** `tests/test_lore_compiler_round1020.py::TestLoreDenseDialogs` (ASC, полный текст окна, since_ts, пусто).
- [x] **T-1890 (@Builder):** storytelling-промпт `LORE_STORY_SYSTEM_PROMPT` + UPD-инструкция: структура «завязка → развитие → статус-кво», постирония/сленг, имена участников, смешные цитаты, **HTML-теги вместо Markdown (О5)**, «мало фактов — сымпровизируй, но не ври про ключевые действия». **Канон: код + `plans/docs/canon/` + тесты одним коммитом.**
  - **DONE:** канон `LORE_STORY_SYSTEM_PROMPT` в `services/lore_prompts.py` (дословная структура ТЗ, HTML `<b>/<i>`, запрет Markdown, UPD-ветка «база → `<b>UPD (Свежак):</b>`) + `build_lore_story_user` (статистика/факты ASC/хронология ASC; при UPD — «Известная база» + «Свежак»); эталон в `plans/docs/canon/architecture.md` (байт-в-байт тест). `PROMPT_MIGRATIONS` НЕ трогаем — канон-константа без PG-сида (прямой прецедент `LORE_MERGE`/`LORE_INIT`, ADR-1013-3).
- [x] **T-1891 (@Builder):** механика UPD/диффов: аддитивная таблица **`lore_stories`** через `CREATE TABLE IF NOT EXISTS` **без бампа `user_version` (О7)** + read/write-методы `Database`; hit по `(chat_id, topic_key)` → `is_update=true` + `previous_story_at`, дотягивание только новых сообщений (`ts > last_ts`); ошибки → WARNING + деградация без UPD. **Зависит:** T-1886.
  - **DONE:** `lore_stories` (`UNIQUE(chat_id, topic_key)`, `topic_key=normalize_text`) в `_SCHEMA_SQL` аддитивно, **без бампа `user_version`** (тест `PRAGMA user_version == 11`); `get_lore_story`/`upsert_lore_story` (UPSERT); `LoreCompilerService.compile` при hit → `is_update=true` + `previous_story_at` + `since_ts=last_ts` (`ts > last_ts`); ошибки чтения/записи → WARNING, деградация без UPD (NFR-4); UPD без нового материала — отдаём сохранённую базу без повторного LLM-вызова.
- [x] **T-1892 (@Builder):** доставка истории: при `ctx.lore_compiled` — `send_chunked_reply(..., parse_mode=HTML)` (`services/smartmodule_utils.py`), глобальный `parse_mode=None` **не менять (О5)**, экранирование текста и фолбэк при ошибке парсинга. + тесты C: сборка JSON (граф+хронология), ASC, UPD-ветка, флаг default ON / toggle OFF, `description`-роутинг; JS/полный `pytest` без регрессий.
  - **DONE:** `DirectChatService._send_direct_answer` — при `ctx.lore_compiled` ЛОКАЛЬНО `parse_mode="HTML"` с экранированием по whitelist-тегов (`smartmodule_utils.escape_lore_html`), при `TelegramBadRequest` фолбэк plain с ИСХОДНЫМ текстом; обычный путь байт-в-байт `parse_mode=None` (О5). Сборка JSON/ASC/UPD/флаг/роутинг/доставка — `tests/test_lore_compiler_round1020.py` (29 тестов). JS-гейты чистые, полный `pytest tests/` — **6439 passed / 0 failed**.
- [x] **T-1893 (@Reviewer + @PM, гейт):** ревью C — DoD фичи, роутинг, канон, R16/R17, каталог-Δ (+1 ключ флага = default ON), отсутствие бампа `user_version`. **PASSED (Step 5 @Reviewer):** 8 тулов, `lore_stories` без бампа `user_version`, UPD-механика, локальный `parse_mode=HTML`+фолбэк, `LORE_STORY_SYSTEM_PROMPT` байт-синхронен с canon; 0 Critical/High.

### Фаза D — Рефакторинг UX/UI мини-аппа (БЛОК 3) — МЕНЮ НЕ МЕНЯТЬ

- [x] **T-1894 (@Architect, гейт):** UI-спека + UI-документ: дизайн-токены Liquid Glass (`--glass-*`), sticky save-контракт, сетка, human-readable labels, рестайлинг Advanced-аккордеона; **явный запрет изменения структуры меню/навигации** (стр. 92). **Статус: DONE (Step 2).**
- [x] **T-1895 (@Builder):** 3.1 критич. баги. **DONE:**
  - **(а) binding:** generic-инпуты — `v-model="item.value"` (значение из БД всегда в поле), секреты — маска `configured ••••last4`; пусто только при реальном `null` (R16). `blockFieldValue`/`blockFieldPlaceholder` покрыты JS-тестом `tests/js/round1020_ui_test.js` T-1895a.
  - **(б) роутинг «Выжимка видео»:** root cause — карточка модуля видна по широкому предикату вкладки «Модули», а старый гейт `canViewTab(m.tab)` требовал секцию config-вкладки (flags/limits/keys) → у ролей без этих секций модалка молча не открывалась. Фикс: гейт по `canViewTab('modules')`, запись per-item `canEditConfig` (read-only открытие без RBAC-регресса).
  - **(в) тумблер `relations_enabled`:** root cause — `:checked` (не v-model) + busy-блокировка: Vue возвращал visual в исходное состояние до ответа, при 409 стейт «залипал». Фикс: оптимистичное обновление стейта до PUT + откат + штатный 409-путь (окно конкурентности).
- [x] **T-1896 (@Builder):** 3.2 — раздел «Участники и отношения»: кнопка «Досье» у каждого участника + модалка с авто-досье (PersonalityExtractor, `db.get_persona_card`) и ручной правкой. Аддитивные API `GET/PUT /api/chat_lore/{id}/dossier/{user_id}` (R16: `user_id` — ключ) + аддитивная таблица `persona_dossier_overrides` (`CREATE TABLE IF NOT EXISTS`, без бампа `user_version`). Существующий persona-экран не дублируется.
- [x] **T-1897 (@Builder):** 3.3 — «Сводка»: виджет-тикер «Живая лента досье» (GLOBAL → случайные досье всех чатов; конкретный чат → только его участники). Источник — `GET /api/oversight/dossier_feed` (`graph_facts`, без новых таблиц); реактивность — один запрос на смену чата + polling 45с; CSS-анимация без сторонних библиотек (CSP), `prefers-reduced-motion`.
- [x] **T-1898 (@Builder):** 3.4 — Liquid Glass глобально: токены `--glass-bg`/`--glass-blur: blur(12px)`/`--glass-border`; применены к панели «Сводка», hub-grid («ИИ»), список/карточки «Модулей» и всем `.modal-card`; `@media (prefers-reduced-motion)` + `@supports not` фолбэк.
- [x] **T-1899 (@Builder):** 3.5 — CSS Grid: `.module-list`/`.hub-grid` на `repeat(auto-fit, minmax(300px, 1fr))` + строгая центровка (`justify-content: center`, `margin-inline: auto`).
- [x] **T-1900 (@Builder):** 3.6 — убит антипаттерн «Кнопка Сохранить везде»: удалены индивидуальные кнопки в generic-конфиге и модалке модуля; внедрён компонент `<sticky-save>` («Отмена» / «Сохранить изменения», dirty-tracking через `configSnapshot`); тумблеры/select — мгновенный auto-save. Тест «тумблер ON + sticky-панель не перезатирает» (`tests/js/round1020_ui_test.js` T-1900).
- [x] **T-1901 (@Builder):** 3.7 — human-readable labels/descriptions: убраны «Кап», «Temperature:», «L1/L2», «Слой А/В» (примеры ТЗ: `LLM_RETRY_BACKOFF_CAP` → «Макс. пауза между попытками (сек)», `CHAT_TEMPERATURE_CHATTY` → «Креативность (Болтливый режим)»). Санкционированный каталог-Δ **только по текстам**: REGISTRY=**438**, GROUPS=**92** — не выросли.
- [x] **T-1902 (@Builder):** 3.8 — рестайлинг существующего Advanced-аккордеона (`<details class="advanced">`): glassmorphism-полоса, chevron (`::before`) + шестерёнка (`advanced-gear`), плавная CSS-анимация, семантический блок «Расширенные системные». Состав групп НЕ менялся.
- [x] **T-1903 (@Builder):** JS-гейты + тесты D. **DONE:** `node --check web/app.js` OK; `tests/js/routing_test.js` → `JS-UNIT-OK`; `tests/js/vue_mount_test.js` → `VUE-MOUNT-OK`; новый `tests/js/round1020_ui_test.js` → `JS-UNIT-OK` (binding/роутинг/тумблер/тикер/sticky); `tests/test_webapp_round1020_ui.py` (23 теста) — включая **снимок навигации** (состав/порядок 25 вкладок + navbar 6 пунктов + 12 карточек модулей НЕ изменены). Полный `pytest tests/` — **6405 passed**. Осознанно обновлены счётчики модальных ✕ (4→5 из-за новой модалки досье) в `test_webapp_round1010_ui.py`/`test_webapp_avatars_ui.py`.
- [ ] **T-1904 (@Reviewer + @PM, гейт) + ⏸ живая верификация:** приёмка UI-сценариев человеком (десктоп/Android/Nekogram); подтверждение «меню не изменено»; **проверка кнопки «Форсировать глубокий сон» в новом UI (О1/T-1906)**.

### Фаза E — Фактчекер + техдолг (БЛОК 6)

- [x] **T-1905 (@Architect, гейт):** `spec.md` + **ADR-1020-5** — Full Tool Access фактчекера (реюз `chat_with_tools`/tool_router, DI-kwargs), функциональный блок промпта (канон), применение БЛОК 0 к пайплайну фактчека; дом техдолга 6.4. **Статус: DONE (Step 2, ADR-1020-5 создан).** Зависит от C (T-1893).
- [x] **T-1906 (@Builder) — 🔴 VERIFY-ONLY (О1):** БЛОК 6.1 — ручной триггер «Форсировать глубокий сон» **уже реализован** (10.18: API `POST /api/memory/dream/run`, ADR-1018-2, тесты `tests/test_sleep_manual_cascade_round1018.py`); обход лимитов/порогов + сброс счётчиков сырья. **Подтвердить работоспособность и UI-доступность кнопки после Фазы D (T-1904). НЕ переписывать.** **VERIFIED (кода не меняли):** `POST /api/memory/dream/run` (+алиас `/api/memory/dream`, `web/api/memory_agi.py:340/362`); кнопка в новом UI — вкладка «Мониторинг Интеллекта» → «Синтез (сон)» → «Запустить синтез сейчас» (`web/index.html:862`, `web/app.js:5423 runDreamNow` → POST + optimistic-бейдж/polling); тесты `test_sleep_manual_cascade_round1018.py` и `test_webapp_agi_ui.py`/`tests/js/routing_test.js` — зелёные. UI-доступность после Фазы D подтверждена.
- [x] **T-1907 (@Builder):** БЛОК 6.2 — прокиннуть в роутер фактчекера инструменты обычного диалога (`dig_into_lore`, `compile_lore_story`, веб-поиск); гарантировать БЛОК 0 (`[Дата Время | Автор | Переслано: откуда]: Текст`) в контексте фактчека; бюджеты/лимиты раундов те же (4) + замер стоимости. **DONE:** `FactCheckService.__init__` += аддитивный `tool_router` (DI из `bot.py`; `setup_factcheck` перенесён ПОСЛЕ сборки `_tool_router` — порядок роутеров не менялся); при роутере+`chat_id` вердикт считается `chat_with_tools` с tool-сетом `factcheck_tools()` (`dig_into_lore`+`compile_lore_story`+`execute_web_search`; О3 OFF убирает `compile_lore_story`); без роутера/`chat_id` — ровно прежний `llm.generate` (R16). Лимит раундов — общий `TOOL_MAX_ROUNDS=4`. Метаданные БЛОК 0: `<chat_context>` уже канонический (`chat_context.format_chat_context`, точка 13) — подтверждено тестом сквозного проброса в messages. **Замер стоимости:** direct-ответ = 1 LLM-вызов (было 1); +1 вызов на каждый tool-раунд; потолок 4 (как в обычном диалоге).
- [x] **T-1908 (@Builder):** БЛОК 6.3 — функциональные инструкции промпта фактчекера: (а) мировые факты/наука/новости → веб-поиск; (б) спор о том, кто что сказал в чате → **обязательно** локальные тулы; (в) использовать метки `[Дата Время | Автор | Переслано]` для аргументации точной датой/временем. **Tone of voice сохранить; ненормативную лексику не переписывать** (стр. 217–219 ТЗ). Канон-миграция атомарно. **DONE (атомарно):** в `FACTCHECK_SYSTEM_PROMPT` добавлен блок «ВЫБОР ИСТОЧНИКА (ФУНКЦИОНАЛЬНО, ОБЯЗАТЕЛЬНО)» (веб vs локальные тулы + метки `[Дата Время | Автор | Переслано: откуда]`), тон/мат не тронуты; слепок `PREV_FACTCHECK_R2020_SYSTEM_PROMPT` + ступень в `PROMPT_MIGRATIONS`; эталон `plans/docs/canon/architecture.md` (Section 72) обновлён синхронно. Снятие канона «1-2 предложения» — Фаза G/T-1922 (НЕ здесь).
- [x] **T-1909 (@Builder):** техдолг **S10.19-15** — `services/oversight.py::_limits_block` вызывает `chat_usage.key_status` **дважды на чат**; свести к одному `budget_snapshot`/`key_status` на чат (обе метрики из результата); обновить `test_direct_contour_reads_key_status` (ассерт «ровно 1 вызов»). **VERIFIED (закрыто Фазой B/T-1882, кода не меняли):** `_limits_block` читает `key_status` один раз (`oversight.py:212`), `calls`+`tokens` — из одного результата; тест `test_direct_contour_reads_key_status` уже содержит ассерт `seen == [-100]` («РОВНО один раз на чат») — зелёный.
- [x] **T-1910 (@Builder):** техдолг — (а) CLI `manage.py retention`: не падать при живом боте (read-only WAL / временный снапшот; dry-run default сохранить; R17 — без путей/секретов в выводе); (б) **S10.19-23** — fsync **каталога** архива после `fsync(file)` (`services/memory_maintenance.py:389-425`; POSIX `os.open(dir, O_RDONLY)`+`os.fsync` в том же `to_thread`; на Windows — no-op с честным логом). **DONE:** (а) dry-run работает по ВРЕМЕННОМУ СНАПШОТУ (`manage._make_db_snapshot` — sqlite backup API, живой бот не блокируется) + `DatabaseService.initialize_existing()` (WAL/busy_timeout, БЕЗ DDL/миграций) для `--apply`; dry-run дефолт сохранён; вывод без путей (`archive=yes/no`). (б) `_fsync_directory()` + `_flush_fsync_and_dir()` — fsync каталога в том же `to_thread` после fsync файла (POSIX), Windows — no-op с честным логом.
- [x] **T-1911 (@Builder):** тесты E — доступность тулов фактчекеру, метаданные в фактчеке, промпт-миграция, `key_status` вызван 1×, retention при живом боте (WAL), fsync каталога (best-effort), стоимость factcheck-цикла. **DONE:** `tests/test_factcheck_tools_round1020.py` (25 тестов: tool-сет/флаг, dispatch через `chat_with_tools`, метаданные `<chat_context>`→messages, замер стоимости 1↔2 вызова, канон+миграция, retention при живом WAL-соединении + `--apply` без DDL, fsync каталога).
- [x] **T-1912 (@Reviewer + @PM, гейт):** ревью E — DoD, канон, R17 (в т.ч. секреты в отчётах/логах retention). **PASSED (Step 5 @Reviewer):** DI-аддитивность фактчека, S10.19-15 (`key_status` 1×/чат), S10.19-23 (fsync каталога, Windows no-op), retention по снапшоту без путей/секретов; 0 Critical/High.

### Фаза G — Agentic AI (БЛОК 7)

- [x] **T-1918 (@Architect, гейт):** `spec.md` §БЛОК 7 + **ADR-1020-7 (Agentic AI)** — дизайн: (1) fail-safe/degradation политика tool-цикла; (2) контракт `reasoning_content` + stripper-стадия + стратегия снятия канона 1-2 предложения; (3) Context Middleware + приоритет метаданных + **схема `graph_facts` (`tg_message_id`, `forward_from`) и миграция pg+sqlite** (решение по `user_version`); (4) EN-канон схем тулов + типизация/форсирование `tool_choice`. **Файлы:** `spec.md`, `adr-1020-7-agentic-ai.md` (имя — по @Architect; при расщеплении — ADR-1020-7…-9). **Зависит:** T-1885 (B), T-1893 (C), T-1912 (E). **Гейт для всего блока G.** **DONE (Step 2, ADR-1020-7 создан); Human Gate пройден.**
- [x] **T-1919 (@Builder) — 7.1 Tool Recursion Fail-Safe:** в `services/tool_loop.py` — **graceful degradation** при исчерпании `TOOL_MAX_ROUNDS` и при `LLMError` на раунде > 0: вернуть частичный ответ (то, что модель успела надумать) или саркастичную заглушку — **НЕ тишину**; вынести degraded-ответ в `direct_chat_service` (фолбэк вместо 🗿). **Логирование потерянных раундов:** `round=`, `tool=`, `lost_rounds=`, причина, цепочка тулов. **DoD:** тесты «лимит исчерпан → ответ, не исключение», «ошибка late-round → ответ»; `TOOL_MAX_ROUNDS` не меняется. **Зависит:** T-1918, T-1887 (C, тот же файл — вливать после C). **DONE:** `ToolLoopResult(str)` + `TOOL_LOOP_FALLBACK_PHRASE` + `tool_trace` + лог `[tools] degraded | reason | rounds_used | lost_rounds | tools | partial_chars` (R17); провайдер-reject round==0/`NoApiKeyForChat`/пустой финал — контракт сохранён. Осознанно обновлены 3 теста (round-limit → degraded).
- [x] **T-1920 (@Builder) — 7.2a Парсинг `reasoning_content`:** в `services/llm_client.py::generate_chat` читать `reasoning_content`/`reasoning`/`thinking`; не бросать `LLMBadResponseError`, если `content` пуст, но есть reasoning (возвращать в `LLMChatResult` отдельным полем, в `content` не помешивать). **DoD:** тест «reasoning-модель (пустой `content` + `reasoning_content`) → результат, не молчание»; обратная совместимость `content`-only. **Зависит:** T-1918. **DONE:** аддитивное `LLMChatResult.reasoning` (default None), guard ослаблен, WARNING `reasoning_chars=N` (черновик не логируется/не отправляется).
- [x] **T-1921 (@Builder) — 7.2b Stripper reasoning-тегов:** единая стадия пост-обработки ответа перед отправкой в Telegram (chokepoint `direct_chat_service.py:656`): вырезать теги-черновик (`<thought>…</thought>`/`<analysis>…</analysis>`/`…` — **точный список фиксирует ADR-1020-7**), не отправлять пользователю. Применить ко всем 4 путям вывода (direct/factcheck/summary/tool) — по решению ADR. **Файлы:** `services/direct_chat_service.py` + новый модуль-стриппер (имя — по @Architect), `services/factcheck_service.py`. **DoD:** тесты «теги вырезаны», «легитимный текст с `<` не съеден», «регистронезависимо/многострочно». **DONE:** новый `services/reply_postprocess.py::strip_reasoning_tags` (5 тегов, defensive к незакрытым, no-op без тегов); применён в direct (chokepoint), tool_loop (финал+деградация), `cleanup_llm_text` (factcheck/summary).
- [x] **T-1922 (@Builder) — 7.2c (P0) Локальное снятие канона «1-2 предложения»** для `compile_lore_story` и `factcheck`: в каноне `CHAT_SYSTEM_PROMPT`/`FACTCHECK_SYSTEM_PROMPT` + `services/prompt_migrations.py` — исключение по режиму (летописец: длинный HTML-storytelling; фактчек: развёрнутый вердикт), общий ответ остаётся коротким. **Канон-миграция атомарно** (код + `plans/docs/canon/` + слепки + тесты). **DoD:** тест «general-ответ по-прежнему 1-2 предложения», «lore/factcheck — без обрезки». **Зависит:** T-1918, T-1890 (C), T-1908 (E) — канон-ступени **C → E → G.2c**. **DONE (без правки `CHAT_SYSTEM_PROMPT` — приоритет ADR-1020-7 §2):** изоляция `LORE_STORY_SYSTEM_PROMPT` (её нет) + `FACTCHECK_SYSTEM_PROMPT` (полный вердикт уже есть, E/T-1908) + детерминированная доставка готового текста истории (`ToolContext.lore_story` → DirectChat при `ctx.lore_compiled`).
- [x] **T-1923 (@Builder) — 7.3a Единый Context Middleware:** единая точка инъекции метаданных (развитие `services/canonical_context.py`) + **приоритет метаданных над бюджет-капом**: в `services/direct_chat_service.py::_apply_context_budget` при обрезке сохранять заголовок `[Дата Время | Автор | ID | Переслано]`, обрезать только `text`. **Учесть ред. 3 (ADR-1020-1):** строки `<Global_Context>`/thread/branch после T-1874 **уже несут** канонический заголовок → `truncate_keep_header` обязан понимать форму `[header]: body` и для kinds `global`/`thread` (не только `rag`); `strip_context_header` переиспользуется, а не дублируется. **DoD:** тест «при жёстком капе строка начинается с `[`, заголовок цел» (в т.ч. для `global`/`thread`); замер `facts=%d | chars=%d` до/после. **Зависит:** T-1873/T-1874 (B). **DONE:** новый `services/context_middleware.py` (`context_item`/`metadata_header`/`truncate_keep_header`, реюз `split_context_header`/`strip_context_header`); `_truncate_block` переиспользует header-safe усечение; sentinel/неприкосновенные kinds не тронуты. Замер в тесте (6 фактов: chars 3.3k→~200 при капе 200, заголовок первой строки цел).
- [x] **T-1924 (@Builder) — 7.3b Расширение `graph_facts`:** добавить `tg_message_id`, `forward_from` в схему (`services/database.py:286-296`) + **миграция sqlite** (идемпотентная, обратимая; аддитивный ALTER; **PG — no-op**: таблицы `graph_facts` в PG нет, phantom-таблицу не создавать); заполнение при записи фактов (provenance), чтение в `format_context_item` (ID-политика §2.2). **Часть ред. 3 (ADR-1020-1 Р4):** довести до канона строки **фактов** — точки 4/5/10/14 (`_fact_prefix`/`_format_origin_labeled_line`/`build_rag_context` legacy/dream) получают `fact:ID` → `tg:<tg_message_id>` + `Переслано:` при непустом `forward_from`; для этого 4-кортеж `_search_graph_facts` расширяется provenance-полями (3/4-кортежи остаются валидными — R16-аддитивно); **XML-структура legacy `<context>/<user_gossip>/<bot_knowledge>` и D206-порядок — байт-инвариант** (R42/R46 зелёные). **DoD:** миграция идемпотентна/обратима, старые строки `NULL`-толерантны, тест sqlite (PG no-op); факт с `tg_message_id` → `tg:`, без него → `fact:`; тесты R42/R46/D206 зелёные. **Зависит:** T-1923. **DONE:** `_SCHEMA_VERSION_GRAPH_FACTS_V12=12` + `_migrate_graph_facts_metadata_v12` (guard `PRAGMA table_info`, FTS не пересоздаётся, новых индексов нет, PG no-op); `insert_graph_fact`/`memorize_facts` += `tg_message_id`/`forward_from`; поиск отдаёт 6-кортеж; рендер — `tg:`/`fact:` + `Переслано:`. Точка 10 (dream) не трогалась — у неё нет provenance (opt-in, R16).
- [x] **T-1925 (@Builder) — 7.4 Schemas & Routing:** перевести **все** `description` JSON-схем тулов (`services/tool_schemas.py`) на **английский** (не только пару из T-1875 — ещё 6 инструментов) + **строгая типизация**: `additionalProperties: false`, `required`, `enum` где применимо; политика форсирования `tool_choice` (per-intent) — по ADR-1020-7. **Канон-ревизия 3.3.** **DoD:** снапшот 8 схем EN; тест типизации; роутинг-тесты не деградировали. **Зависит:** T-1875 (B), T-1887 (C) — ступень **B → C → E → G.4**. **DONE:** 8/8 `description` + все параметры EN (без кириллицы); имена/порядок/`required`/`enum` не тронуты; `summarize_video.mode` += `description`; `tool_choice` НЕ форсируется; шапка файла + `plans/docs/canon/architecture.md` (Section TOOL_SCHEMAS).
- [x] **T-1926 (@Builder):** тесты G — fail-safe/degradation (лимит + late-round), логирование потерянных раундов, `reasoning_content`, stripper (позитив/негатив/мультистрочность), снятие канона (general vs lore/factcheck), middleware/приоритет заголовков, миграция `graph_facts` (pg+sqlite, идемпотентность/откат), EN-схемы + типизация. Полный `pytest` без регрессий. **DONE:** `tests/test_agentic_ai_round1020.py` (44 теста). Полный `pytest tests/` — **6508 passed / 0 failed**.
- [x] **T-1927 (@Reviewer + @PM, гейт):** ревью G — DoD, канон-атомарность (7.2c), миграционная матрица (`graph_facts`, `user_version`), R16/R17, каталог-Δ не вырос. **PASSED (Step 5 @Reviewer):** `ToolLoopResult` fail-safe, `reasoning` аддитивно + stripper 5 тегов, middleware header-safe, v11→v12 идемпотентно + PG no-op, EN 8/8; каталог 439/92/20 = санкц. Δ+2; 0 Critical/High.

### Фаза H — Справка UI (БЛОК 8)

- [x] **T-1928 (@Architect, гейт):** spec §БЛОК 8 + (при необходимости) UI-документ/ADR-1020-8: где живут тексты справки (`services/info_service.py::DEFAULT_INFO_TEXT`, зеркало `info_text.md`, гайд `plans/docs/intelligence_user_guide.md`, рендер `web/index.html:2564-2630`), контракт актуализации (бамп `INFO_CANON_VERSION` + `KNOWN_INFO_SNAPSHOTS`), инвариант «стиль сохраняется, меню не меняется». **Зависит:** T-1893 (C), T-1912 (E). **Гейт для H.** **Статус: DONE (Step 2, `adr-1020-8-help-ui-update.md` создан, spec §19 ред. 2).**
- [x] **T-1929 (@Builder):** обновить тексты раздела «Справка»/«Гайд»: удалить неактуальные механики; добавить описание **Летописца** (`compile_lore_story`, формат HTML-истории, UPD/Свежак); обновить **Фактчек** (доступ к локальным тулам, умный выбор источника); объяснить **безлимиты** (`-1` → «Безлимит (∞)», retention `0` → «Импорт: Вечно», per-chat override). **Критично: сохранить дерзкий ироничный стиль** (без корпоративного мануала). **Файлы:** `services/info_service.py` (канон + `INFO_CANON_VERSION` bump + слепок), `info_text.md`, `plans/docs/intelligence_user_guide.md`; `web/index.html`/`web/app.js` — только при необходимости рендера/верстки. **DoD:** байт-тест `DEFAULT_INFO_TEXT ↔ info_text.md`; идемпотентная миграция знает прежний слепок. **DONE:** канон v3 (**11 секций**: актуализирован §1 «Фактчек» — локальные тулы + умный выбор источника веб/база чата + развёрнутый вердикт; новый §3 «Летописец» — как просить, HTML-история с именами/цитатами, повтор → блок **UPD (Свежак)**, флаг ON by default; новый §11 «Безлимиты» — `-1` → «Безлимит (∞)», `0` → «Импорт: Вечно», per-chat override «ближе к чату», «Модули → Бюджеты»; в §10 добавлен «Часовой пояс чата»); удалена устаревшая механика web-only-фактчека («поднимет поисковики»). Tone of voice сохранён (мат не переписан, `<h1>`/`<h2>`, разговорные конструкции). `INFO_CANON_VERSION` **2 → 3**, `KNOWN_INFO_SNAPSHOTS` += `PREV_R2020_DEFAULT_INFO_TEXT` (v2); гайд — новый §10 «Лимиты и безлимиты» + Летописец в §6 + словарик. `web/*` **не трогались**.
- [x] **T-1930 (@Builder):** тесты H — канон-версия/слепок, байт-зеркало, наличие блоков «Летописец»/«Фактчек»/«Безлимит», отсутствие удалённых механик; JS-гейты (`node --check`, `JS-UNIT-OK`, `VUE-MOUNT-OK`); снимок навигации (меню не менялось). **DONE:** новый `tests/test_help_ui_round1020.py` (15 тестов: v3/слепки, байт-зеркало, содержательные блоки, absence retired, tone, миграция v2→v3 идемпотентна, снимок навигации 25 вкладок + структура вкладки «Справка»); осознанно обновлены счётчики канона (`test_info_service`, `test_guide_round1015`, `test_info_handlers`) и маркеры `canon_delivered_version` (`test_config_cache`, `test_hotfix_jsonb_types`, `test_webapp_api` — берут `INFO_CANON_VERSION`), `test_help_guide_round1014` (новые секции гайда / `## 11. Словарик`). JS-гейты чистые. Полный `pytest tests/` — **6523 passed / 0 failed**.
- [ ] **T-1931 (@Reviewer + @PM, гейт) + ⏸:** приёмка Справки владельцем (стиль/актуальность); сверка текстов с фактическим поведением T-1929/T-1904.

### Фаза F — Верификация, SPEC_READY, деплой, архив (финал, охватывает фазы B–H)

> **Внимание:** нумерация T-1913…T-1917 **меньше** номеров фаз G/H, но физически Фаза F — **последняя** (финальные гейты).

- [x] **T-1913 (@Architect + @PM) — SPEC_READY ✅ (требование ТЗ, стр. 76):** логика всех изменений (пайплайны фаз B/C/E/G/H, флаги — включая default ON, Δ каталога +2 ключа, миграции, порядок доставки) **предъявлена владельцу до деплоя**; получено явное **«go»** → деплой одобрен (считаем закрытым фактом получения «go» на деплой). **DONE.**
- [x] **T-1914 (@Reviewer):** сквозное ревью эпика (DoD §5, R16/R17, канон-атомарность, отсутствие регрессий); полный `pytest` + JS-гейты. **APPROVED** (`plans/reports/round1020_reviewer.md`); pytest **6546 passed / 0 failed**; JS-гейты чистые; `git diff --check` clean.
- [x] **T-1915 (@Scanner):** аудит эпика → отчёт `plans/reports/round1020_scanner_audit.md`. **RE-AUDIT: 0 Critical / 0 High / 0 Medium / 0 Low** (открыто только **5 Info**, не блокеры); все S10.20-* (1 High + 7 Medium + 9 Low) закрыты/верифицированы (§6a). **DONE.**
- [x] **T-1916 (@DevOps, гейт):** деплой выполнен — коммит **`995cf83`** (фича) + **`741b77c`** (R18-вычистка кредов из архива 10.16), запушено; на сервере `systemctl` **active**, MainPID **2668878**, SQLite **`user_version=12`**; живая проверка «Летописца»/Справки/UI — ⏸ human-pending (T-1904/T-1931). **Пароль сервера в репозитории НЕ хранится (R17, О6).** **DONE.**
- [x] **T-1917 (@PM, Step 8):** архивация выполнена — папка фичи перенесена `plans/features/round1020-lore-compiler-rag-refactor/` → **`plans/archive/round1020-lore-compiler-rag-refactor/`**; синхронизированы `plans/backlog.md` и `tasks.md`/`README.md` (все файлы + ADR-1020-1…-8 сохранены). R18-скан папки фичи — **чисто** (секретов нет). Передача **@Memory (Step 10)** — синхронизация `plans/MEMORY.md`/`plans/metrics.md`. **DONE (Step 8).**
- ⏸ **ОТКРЫТО (human-pending, НЕ блокирует архив/деплой):** **T-1904** (живая UI-приёмка человеком: десктоп/Android/Nekogram, «меню не изменено», кнопка manual DeepDream О1) и **T-1931** (приёмка Справки владельцем). Follow-up: **T-1932** (fallback точки 7, R26 — `[ММ.ГГГГ | fact:ID]: текст`, без смены текущего контракта).

## 6a. Фиксы после @Scanner S10.20-* (Step 6→4, 16.09.2026)

Источник: `plans/reports/round1020_scanner_audit.md` (1 High + 7 Medium + 9 Low).

| Finding | Sev | Статус | Как закрыто |
|---|---|---|---|
| **S10.20-1** | High | ✅ | `web/index.html`: `<sticky-save class="col-span-full">` добавлен в конец ветки `currentTabIsConfig` (точечные кнопки удалены диффом) — сохранение textarea/input/JSON/промптов и key-drafts снова работает. Тесты проверяют панель В КАЖДОЙ ветке (config / modules / access), а не «где-нибудь». |
| S10.20-2 | Medium | ✅ | `services/tool_router.py::resolve_lore_compiler_flag` (per-chat override → hot → канон) — используется и в `_compile_lore_story`, и в `factcheck_service` (раньше только глобальный `hot.get`). |
| S10.20-3 | Medium | ✅ | `_dig_json_payload`: усечение секций `snippets`/`facts` + `"truncated": true` ДО `json.dumps` — JSON всегда валиден (кап `dig_max_symbols` больше не рвёт скобки). |
| S10.20-4 | Medium | ✅ | `ToolContext.lore_verbatim_instruction` (фактчек → `False`: без «верни ДОСЛОВНО»); `smartmodule_utils.strip_lore_html` срезает whitelist-теги в plain-выдаче фактчека. |
| S10.20-5 | Medium | ✅ | `last_ts` = max ts фактически включённых `dialog_lines` (`_trim_pairs` отдаёт ts), а не глобальные `dense.latest`/`stats.last_seen` — сообщения не выпадают из UPD. |
| S10.20-6 | Medium | ✅ | `saveConfigItem`/`saveKeyItem` возвращают bool; `saveModalEdits` НЕ снапшотит baseline при ошибках, собирает `stickyFailed`, панель подсвечивает провалы (не «благословляет»). |
| S10.20-7 | Medium | ✅ | `status_service`: per-chat cap (≠ глобального) приоритетнее acct-лимита; добавлено поле `context.source` (`chat`/`account`/`global`). |
| S10.20-8 / M1 | Medium | ✅ | `_trim`: заголовок неприкосновенен — `split_context_header` отделяет header, усекается только body (иначе строка отбрасывается). |
| Reviewer M2 | Medium | ✅ (док) | `database.lore_graph_slice` докстринг явно фиксирует кап `_LORE_NODE_SCAN_LIMIT=2000` (детерминированный скан узлов по id). |
| Reviewer M3 | Medium | ✅ | `database.dossier_feed`: случайная выборка из свежего пула `limit*20` (PK DESC), а не `ORDER BY RANDOM()` по полному скану; докстринг «fail-open» приведён к коду. |
| S10.20-9 | Low | ✅ | Паттерны `direct_rag`/`legacy_rag` в `canonical_context` расширены под 6-кортеж (`fact:ID`/`Переслано:`); сэмплы реестра обновлены (новый `_sample_video_web`). |
| S10.20-10 | Low | ✅ | Длинная (>4096 экранированных) история доставляется plain без тегов — чанкинг не рвёт тег и не дублирует текст. |
| S10.20-11 | Low | ✅ (коммент) | `escape_lore_html` документировано: при переносе историй в TMA обязателен sanitize. |
| S10.20-13 | Low | ✅ | `initialize_existing`: `Path.exists()` + проверка наличия таблиц → понятная ошибка вместо «deleted=0» по пустой схеме. |
| S10.20-14 | Low | ✅ | `LoreCompilerService._date` считает дату в tz чата (`limits.chat_timezone`, фолбэк `limits.summary_timezone`) — согласовано с диалогом. |
| S10.20-15 | Low | ✅ | `_empty_dense()` отдаёт свежий список на вызов (убрана общая мутабельная ловушка). |
| S10.20-16 | Low | ✅ | Докстринг `dossier_feed` приведён к фактическому поведению. |
| S10.20-12 | Low | ⛔ | Принято ADR-1020-3 (Time Injection / prompt-cache) — не трогаем. |
| S10.20-17 | Low | ⛔ | Паритет RBAC `persona_dossier_overrides` — вне скоупа. |

**Проверка (16.09.2026):** полный `pytest tests/ -q --timeout=300` — **6546 passed, 0 failed** (baseline 6523; +23 новых теста).
JS-гейты: `node --check web/app.js` OK; `routing_test` → `JS-UNIT-OK`; `vue_mount_test` → `VUE-MOUNT-OK`; `round1020_ui_test` → `JS-UNIT-OK`; `git diff --check` clean.
Новые/обновлённые тесты: `tests/test_scanner_fixes_round1020.py` (S10.20-2/-3/-4/-5/-8/-13/-15), `tests/test_webapp_round1020_ui.py` + `tests/js/round1020_ui_test.js` (панель в каждой ветке, S10.20-6), `tests/test_status_service.py` (S10.20-7), `tests/test_factcheck_tools_round1020.py` (S10.20-2/-4), `tests/test_lore_compiler_round1020.py` (S10.20-10), `tests/test_memory_core_round1020.py` (S10.20-9).
**Гейты T-1904/T-1931** — по-прежнему ⏸ HUMAN PENDING; код-часть UI-фазы (sticky-save) переоткрыта сканером и закрыта S10.20-1.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **Дубли 10.18** (БЛОК 5.5 и 6.1): повторная реализация сломает ADR-1018-2/тесты `test_sleep_manual_cascade_round1018.py` | Помечены **verify-only** (T-1883, T-1906); решение **О1** закреплено; UI-привязка проверяется на T-1904 |
| R2 | **7→8 инструментов** меняет роутинг и может ломать существующие вызовы/тесты | ADR-1020-4 + жёсткие EN-`description` (T-1875/T-1925) + роутинг-тесты + флаг default ON с toggle |
| R3 | **Коллизия имён** `dig_into_lor` (ТЗ) vs `dig_into_lore` (код) | Используется только `dig_into_lore`; ошибка зафиксирована в spec/задачах |
| R4 | **ASC-хронология** конфликтует с семантическим порядком RAG как «фичей» для части потребителей | Аддитивное расширение D206; ASC меняет только порядок внутри контекста, не состав top-K (T-1876) |
| R5 | **Канон промптов** — правка эталона ломает байт-в-байт тесты 10.13 | Канон-миграция атомарно (код+`plans/docs/canon/`+тесты); ADR-1013-3; ступени C → E → G.2c |
| R6 | **Delta каталога** от tz-настройки/флага/лейблов расходится между фазами B/C/D/G | Единый гейт сведения Δ каталога (+2 ключа + N текстов); точное число в spec |
| R7 | **Time Injection** может ухудшить кэш-хиты промпта/стоимость токенов | **О2: инъекция первым user-блоком**, system статичен; тест «system-байты неизменны» (T-1879/T-1884) |
| R8 | **UI-рефакторинг сломает навигацию** (владелец прямо предупредил) | «Меню не менять» — констрейнт §3 + тест/снимок навигации (T-1903/T-1904) |
| R9 | **sticky-save** может конфликтовать с auto-save тумблеров/конкурентностью (409) | UI-спека T-1894: контракт тумблеров vs кнопки + тесты (T-1900) |
| R10 | **Фактчекер + тон**: правка промпта ≠ переписывание токсичности (политика) | Правятся только функциональные инструкции; tone of voice/мат — как есть (T-1908) |
| R11 | **`current_task.md` с plaintext-секретом** может утечь в коммит/спеки | Файл untracked + в `.gitignore`; значение не копировать (R17, **О6**) |
| R12 | **Audit-before-design** проигнорирован → костыли | Фаза A выполнена; Human Gate A пройден (T-1871) |
| R13 | **CLI retention** при живом боте (WAL/lock) — риск порчи данных | Снапшот/read-only WAL + dry-run default; тесты T-1911 |
| R14 | **`/summary` архивные факты** уже подмешиваются осознанно — легко сломать «фичу» | Правило промпта сохраняет подмешивание, меняет подачу (флешбэк) |
| **R15** | **Stripper reasoning-тегов** может съесть легитимный текст (`<`, `a < b`) или не поймать вложенность | Точный список тегов/границ — в ADR-1020-7; тесты позитив/негатив/мультистрочность (T-1921/T-1926) |
| **R16** | **EN-перевод всех `description`** меняет роутинг/может спровоцировать рост вызовов тулов | Снапшот 8 схем + роутинг-тесты (T-1925/T-1926); ступенчато B → C → E → G.4 |
| **R17** | **`graph_facts` DDL** (pg+sqlite) — риск миграционной матрицы/`user_version` | Аддитивный ALTER, идемпотентно/обратимо; решение по `user_version` — ADR-1020-7 (T-1924); старые строки `NULL`-толерантны |
| **R18** | **Приоритет метаданных над бюджет-капом** увеличит контекст (заголовки не режутся) | Обрезать только `text`; замер `facts=%d | chars=%d` до/после (T-1923/T-1926) |
| **R19** | **Снятие канона «1-2 предложения»** может «протечь» в general-ответ и раздуть все ответы | Исключение строго по режиму (`ctx.lore_compiled` / factcheck), тест «general остаётся коротким» (T-1922/T-1926) |
| **R20** | **Справка (H)** может разойтись с фактическим поведением/флагами | Сверка текстов с T-1929/T-1904 на гейте T-1931; `INFO_CANON_VERSION` + слепок |
| **R21** | **Локальный `parse_mode=HTML`** (О5) — невалидная разметка модели/падение отправки | Промпт на HTML-теги (T-1890); экранирование + фолбэк при ошибке парсинга (T-1892); глобальный `None` сохранён |
| **R22** | **`metadata-migration-regressions`** (БЛОК 0): «применить формат во всех 14 точках» противоречило байт-инварианту → T-1874 PARTIAL | **Разрешено ред. 3:** двухъярусный критерий (ADR-1020-1 §«Разрешение конфликта T-1874») — ярус A там, где нет временного маркера (точки **2/3/8/13**), ярус B — эквивалентная явная сериализация (1/4/5/7/10/11/12/14); `CONTEXT_POINTS.representation` + инвентарный тест из реестра (T-1874) |
| **R23** | **`global-context-header-coupling`** (БЛОК 0): заголовок `[…]` в строках `<Global_Context>`/thread ломает `text.find(":")` → регресс E1 keep-importance и F2-дедупа | Обязательные фиксы `_line_markers` (`direct_chat_service:287-300`) и `_fact_tokens` (`summary_memory:1007-1010`) через `strip_context_header`; служебные метки — allowlist; тесты E1/F2 (T-1874) |
| **R24** | **`snapshot-churn-context-metadata`** (БЛОК 0): «обновить снапшоты» может замаскировать настоящую регрессию | Осознанно обновляются **только** снапшоты точек 2/3/8/13 (список — ADR-1020-1 Р4, `fake_time`); `<chat_history>`/legacy-RAG-структура/D206 — не трогать; прочие расхождения = сигнал регрессии |
| **R25** | **`fact-id-enrichment-deferral`** (БЛОК 0): `fact:ID`/forward для фактов (4/5/10/14) физически невозможны до v12 → соблазн имитировать | В B статус «эквивалент (ts+author)»; наполнение — **G/T-1924**; тест «нет выдуманных ID» (R16) |
| **R26** | **Fallback точки 7** (`vector_search` → `list[str]`): «голые» строки архива остаются в `query_chat_memory` | Документированный **PENDING** (ADR-1020-1 Р6); смена общего контракта с `summary_generator` — вне T-1874; follow-up-задача (предлагается @PM **T-1932**) |

**ADR-кандидаты (Step 2):** ADR-1020-1 (метаданные; **ред. 3 — разрешение конфликта T-1874**), ADR-1020-2 (роутинг/хронология/summary/dig), ADR-1020-3 (Time Injection + tz + анти-галлюцинации + persona fallback), ADR-1020-4 (`compile_lore_story` + UPD-хранилище), ADR-1020-5 (фактчекер + техдолг), ADR-1020-6 (формат доставки историй), **ADR-1020-7 (Agentic AI, БЛОК 7)** — in-flight, **ADR-1020-8 (Справка UI, БЛОК 8)** — при необходимости.

## 8. Feature flags / progressive delivery

- **Фича C — простой Feature Flag (решение О3).** Ключ каталога: **`flags.lore_compiler_enabled`** (bool, категория `flags`, **Δ каталога +1**).
  - **ДЕФОЛТ = ON глобально** для всех чатов. **Поэтапная раскатка 10/50/100 % ОТМЕНЕНА.**
  - Тумблер ВКЛ/ВЫКЛ в админке; **OFF** → тул `compile_lore_story` недоступен, остальные 7 работают (без редеплоя).
  - **Откат:** toggle OFF или `git revert` (безусловные фазы — `git revert`).
- **Фаза B/D/E/G/H — безусловные** (правило раунда): откат — `git revert`. Отдельных флагов не вводить.
  - Исключение — **`limits.chat_timezone`** и labels: это **данные/тексты**, не флаги (решение О4).
  - **`parse_mode`:** глобально `None` (не флаг); локально `HTML` — режим Летописца (`ctx.lore_compiled`), решение О5.
- **Порядок доставки:** A ✅ → {B ∥ D} → C → E → {G ∥ H} → F (SPEC_READY → деплой).

## 9. Handoff / деплой

`@Orchestrator` — эпик **round1020 ЗАВЕРШЁН**: реализация фаз **A–H** выполнена, @Reviewer **Approved**, @Scanner re-audit
**0 Critical/High/Medium/Low**, pytest **6546 passed / 0 failed**, архитектура смержена (`plans/ARCHITECTURE.md` **§45**).
**Деплой (Step 9) выполнен:** коммит **`995cf83`** (+ R18-fix **`741b77c`**), запушено; на сервере `systemctl` active,
MainPID **2668878**, SQLite **`user_version=12`**.
**Архив (Step 8, @PM) выполнен:** папка фичи — **`plans/archive/round1020-lore-compiler-rag-refactor/`** (`spec.md`, `tasks.md`,
`README.md`, `adr-1020-1…-8` сохранены); R18-скан — чисто.
**Передача @Memory (Step 10):** синхронизация `plans/MEMORY.md` + `plans/metrics.md`; финальные числа — pytest **6546/0**,
каталог **439/409/414/92/90/20**, **SQLite v12**, 8-й инструмент `compile_lore_story` (флаг `flags.lore_compiler_enabled` default ON).
**⏸ Открыто (human-pending):** T-1904 (живая UI-приёмка), T-1931 (приёмка Справки); follow-up **T-1932** (fallback точки 7, R26).
**Безопасность:** пароль сервера в репозитории НЕ хранится, `plans/current_task.md` — untracked (О6/R17).
