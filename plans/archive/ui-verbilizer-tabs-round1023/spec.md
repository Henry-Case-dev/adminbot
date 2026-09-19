# spec.md — F8 `ui-verbilizer-tabs-round1023`

> **Раунд 10.23** · Приоритет **P1** · Шаг 2 @Architect · Тип: каталог + UI (`web/**`) + API
> **ADR:** `ADR-1023-8.md` (**Accepted**). **Задачи:** `tasks.md` (T-2167…T-2175).
> **ТЗ:** `plans/current_task.md`, «Рефакторинг UI и Аналитика (Мини-апп) → 2. Управление Промптами (System 2 & Cliches)» (untracked; секреты не цитировать — R17/R18).
> **Сквозной слой:** `plans/features/round1023-architecture.md` §3.4, §5.
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**.
> **Зависит от:** F3 (режимы/`MODE_*_BLOCK`), F4 (кэш клише + API мониторинга), F5 (ступень `web/**` + группа изображений + ступень каталога).

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Каталог: группы prompts (8) | `services/param_catalog.py:139-156` (`prompts_factcheck`…`prompts_memory`) |
| Реестр промпт-ключей (10) | `services/param_catalog.py:369-400` (`_PROMPTS`) |
| Категорийная привязка к вкладке «Промпты» | `TAB_RULES` (`:1909-1982`, `(TAB_PROMPTS, ((CATEGORY_PROMPTS, None),))`), `_TAB_BY_GROUP` (`:2024`) |
| Сид промптов из код-канона | `services/pg_db.py:389-500` (`resolve_code_source` + идемпотентный сид) |
| Рантайм-чтение промптов | `summary_generator.py:211` (`hot.get("prompts.summary_system_prompt", …)`), `factcheck_service.py:82`, `direct_chat_service.py:681-682` |
| Канон-миграции промптов | `services/prompt_migrations.py:82-146` (`PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS`) |
| UI-таб «Промпты» (generic-рендер) | `web/app.js:49-52` (`TABS.prompts`, sources `{category:'prompts', groups:null}`) |
| UI: generic-группы вкладки | `web/index.html:424-499` (`currentTabGroups`, `basicItems`/`advancedItems`) |
| UI: карточки модулей (список) | `web/index.html:713-740` (витрина 11 модулей, toggle/«Параметры») |
| API конфига | `web/api/routes.py` (`GET /api/config`, save), `services/access.py`, `param_permissions` |
| Кэш клише (F4) | F4 API: GET списка/метаданных, POST форс-обновления, PUT ручного редактирования (T-2132) |
| Freeze-меню | `tests/test_webapp_hubs_matrix_ui.py` (`NAV_ITEMS`), `tests/test_frontend_tab_mapping.py` (20 вкладок), `tests/test_param_catalog.py` (группы/вкладки) |

### 0.1. Ключевые конфликты и их решение

1. **Stage-1/Stage-2 промптов в каталоге нет.** Рантайм Stage-1/Stage-2 (F3) читает **код-константы** (`SUMMARY_EDITOR_SYSTEM_PROMPT`, `SUMMARY_NARRATOR_SYSTEM_PROMPT`, аналоги), а не PG-ключи. Чтобы карточки «Синтезатор/Вербализатор» были **рабочими**, F8 обязан (а) добавить PG-ключи, (б) **прочитать их в рантайме** (`hot.get(...)`, additive). Это кросс-фичевый контракт с F3/F6 (см. §4.2 и ADR).
2. **Не у всех модулей есть Stage-1.** Реальный двухстадийный конвейер (F3) — у **Фактчек / Прямой чат / Саммари**; Поиск/YouTube/Веб — одностадийные (только `SYSTEM_PROMPT`). Фальшивых Stage-1 ключей не вводим: у этих карточек рендерится **только** секция «Вербализатор (Характер)» с пометкой «модуль одностадийный».
3. **Freeze-меню.** Структура меню (`NAV_ITEMS`, число вкладок = 20, карточки модулей-витрины) **не меняется**. Меняется только внутренний рендер вкладки «Промпты».
4. **Кэш клише.** Блок мониторинга — **читатель** API F4; F8 не владеет логикой воркера и не превращает список в scrubber.

## 1. Цель

Разделить карточки модулей на **«Синтезатор (Логика)»** и **«Вербализатор (Характер)»**, добавить UI-селектор режимов Вербализатора (Tabs: `Casual` | `Serious` | `Deep Research`) и блок мониторинга `dynamic_cliche_list` (дата обновления, форсированное обновление, ручное редактирование). Структура меню не меняется.

## 2. Требуемое поведение

1. Вкладка «Промпты»: внутри каждой карточки модуля — две секции: **Синтезатор (Логика)** (Stage-1) и **Вербализатор (Характер)** (Stage-2). Для одностадийных модулей — только Вербализатор + пометка.
2. Селектор режимов: Tabs `Casual`/`Serious`/`Deep Research` — переключают редактируемый режимный блок и задают режим по умолчанию.
3. Блок `dynamic_cliche_list`: дата обновления, кнопка «Обновить сейчас» (POST force), ручное редактирование (PUT), fail-open при недоступности API.
4. Редактирование Stage-1/Stage-2 промптов **реально влияет** на ответы (рантайм читает новые PG-ключи), `basic≥1` на вкладку «Промпты».
5. Freeze: `NAV_ITEMS`, 20 вкладок, карточки модулей-витрины — без изменений.

## 3. Каталог: точная Δ (T-2168)

### 3.1. Новая группа

`GroupSpec("prompts_verbilizer", "prompts", "Вербализатор: режимы", "Режимы подачи ответа: Casual / Serious / Deep Research.", 9)` → **GROUPS 92 → 93**. Привязка к вкладке — автоматическая (категорийное правило `TAB_PROMPTS`), **TAB_RULES Δ = 0**.

### 3.2. Новые ключи (категория `prompts`, PG-only, сид из `code_source`)

| pg_key | title (ru) | group | code_source | stage |
|---|---|---|---|---|
| `prompts.factcheck_analyst_system_prompt` | Синтезатор фактчека (Логика) | `prompts_factcheck` | `services.factcheck_prompts.FACTCHECK_ANALYST_SYSTEM_PROMPT` | synthesizer |
| `prompts.summary_editor_system_prompt` | Синтезатор саммари (Редактор) | `prompts_summary` | `services.summary_prompts.SUMMARY_EDITOR_SYSTEM_PROMPT` | synthesizer |
| `prompts.direct_chat_synthesizer_system_prompt` | Синтезатор прямого чата (Логика) | `prompts_direct_chat` | `services.chat_prompts.DIRECT_SYNTHESIZER_SYSTEM_PROMPT` | synthesizer |
| `prompts.factcheck_verbalizer_system_prompt` | Вербализатор фактчека (Характер) | `prompts_factcheck` | `services.factcheck_prompts.FACTCHECK_VERBALIZER_SYSTEM_PROMPT` | verbalizer |
| `prompts.summary_narrator_system_prompt` | Вербализатор саммари (Рассказчик) | `prompts_summary` | `services.summary_prompts.SUMMARY_NARRATOR_SYSTEM_PROMPT` | verbalizer |
| `prompts.direct_chat_verbalizer_system_prompt` | Вербализатор прямого чата (Характер) | `prompts_direct_chat` | `services.chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT` | verbalizer |
| `prompts.verbilizer_mode_casual` | Режим Casual | `prompts_verbilizer` | `services.prompt_style_blocks.MODE_CASUAL_BLOCK` | mode |
| `prompts.verbilizer_mode_serious` | Режим Serious | `prompts_verbilizer` | `services.prompt_style_blocks.MODE_SERIOUS_BLOCK` | mode |
| `prompts.verbilizer_mode_deep_research` | Режим Deep Research | `prompts_verbilizer` | `services.prompt_style_blocks.MODE_DEEP_RESEARCH_BLOCK` | mode |
| `prompts.verbilizer_default_mode` | Режим по умолчанию | `prompts_verbilizer` | (select) | mode |

- **Δ prompts-ключей = +10** (10 → 20); все — уровень **advanced** (длинные каноны). `basic≥1` на вкладке сохраняется за существующими ключами.
- `prompts.verbilizer_default_mode` — `widget=select`, `select_options=("casual","serious","deep_research")`, дефолт `serious` (fail-safe F3).
- Одностадийные модули (Поиск/YouTube/Веб): существующие `prompts.search/youtube/youtube_video/webpage_system_prompt` получают `stage="verbalizer"`; Stage-1 не вводится.

### 3.3. Разметка секций (stage)

Добавляется **аддитивное** поле `stage: str | None` в `ParamSpec` и `add(...)` (значения `"synthesizer"`/`"verbalizer"`/`"mode"`; `None` — прочее) и отдаётся в `/api/config` как есть. UI группирует элементы внутри карточки по `stage`. **GROUPS/TAB_RULES не меняются** от этого поля.

### 3.4. Блок мониторинга клише

- **Review iter1 (Low, решено): ключ `content.dynamic_cliche_list` НЕ регистрируется в каталоге.** F4 хранит список в PG-таблице `anticliche_cache` (не `bot_settings`); `GET /api/config` и `params-meta` hidden-ключи не отдают, а UI-блок работает через `/api/anticliche` — registry-ключ был бы «мёртвой ручкой» в матрице прав (никто не читает/пишет). Итоговый Δ F8 — **REGISTRY +10** (только prompts).
- **Координация:** владелец данных/логики обновления — F4; F8 отвечает только за UI-блок и вызовы API F4.

### 3.5. Итоговый Δ каталога F8 (после review iter1)

| Метрика | Было | Стало |
|---|---|---|
| REGISTRY | 447 | **457** |
| settings-поля | 416 | 416 |
| categorized | 422 | **432** |
| GROUPS | 95 | **96** |
| TABS | 20 | 20 |

Точные значения зафиксированы пин-тестами в коммите F8. Ключ клише не регистрируется (см. §3.4, review iter1).

## 4. Архитектура и контракты

### 4.1. Рантайм-чтение Stage-1/Stage-2 (T-2172, кросс-фичевый контракт)

- `summary_generator._generate_two_call`: Stage-1 `hot.get("prompts.summary_editor_system_prompt", SUMMARY_EDITOR_SYSTEM_PROMPT)`; Stage-2 base `hot.get("prompts.summary_narrator_system_prompt", SUMMARY_NARRATOR_SYSTEM_PROMPT)` (далее `{max_symbols}` через `.replace`).
- `factcheck_service._check_claim_two_call`: аналогично (`…_analyst_system_prompt` / `…_verbalizer_system_prompt`).
- `direct_chat_service` (System 2): аналогично (`…_synthesizer_system_prompt` / `…_verbalizer_system_prompt`).
- Режимные блоки: выбор `MODE_*_BLOCK` берёт `hot.get("prompts.verbilizer_mode_<mode>", MODE_<MODE>_BLOCK)`; fallback режима — `hot.get("prompts.verbilizer_default_mode", "serious")`.
- **Инвариант:** это **аддитивные** `hot.get`-чтения; поведение при пустых PG-значениях/отсутствии ключей — прежнее (код-константа). Число LLM-вызовов не меняется.
- **Порядок/владение:** F8 вливается после F6 (ступени каталога F2→F5→F8), поэтому правки сервисов F3/F6 не конфликтуют (последовательная ступень, не параллель). Если владелец хочет сохранить строгую эксклюзивность — читатели добавляются в коммите F8 и подтверждаются ревью (см. ADR §Human Gate).

### 4.2. API (T-2172)

- **Δ = 0 новых эндпоинтов**: сохранение новых ключей идёт через существующий generic `POST /api/config`; блок клише — через API F4 (T-2132).
- Если F4-эндпоинты названы иначе/нужен агрегат — F8 использует имя из F4 (`GET/POST/PUT /api/cliches*`); при необходимости тонкий прокси-роут в `web/api/routes.py` (те же RBAC/`param_permissions`).

### 4.3. UI (T-2169…T-2171)

- `web/app.js`: в `TABS.prompts` sources остаются `{category:'prompts', groups:null}`; добавить клиентскую группировку по `stage` и рендер секций «Синтезатор (Логика)» / «Вербализатор (Характер)».
- `web/index.html`: в блоке generic-групп вкладки «Промпты» — рендер под-заголовков секций и спец-блока «Режимы Вербализатора» (Tabs) для группы `prompts_verbilizer`; спец-блок мониторинга клише (дата/force/PUT) с `v-if` по доступности F4-API (fail-open: API недоступен → блок скрыт, вкладка работает).
- Витрина модулей (`index.html:713-740`, `NAV_ITEMS`) — **не трогается** (freeze).
- `basic≥1` на вкладке «Промпты» гарантируется существующими basic-ключами; новые ключи advanced, чтобы не раздувать basic.

## 5. План тестирования (T-2173/T-2174)

1. Каталог: REGISTRY/GROUPS/`prompts`-count обновлены **осознанно**; `prompts_verbilizer` привязана к `TAB_PROMPTS`; каждый промпт-ключ имеет группу/описание; уникальность pg_key.
2. Рантайм: `hot.get`-чтение Stage-1/Stage-2/режимов (mock cache) → выбран PG-промпт; при отсутствии — код-константа; число LLM-вызовов не изменилось.
3. UI: `stage`-группировка; секции Синтезатор/Вербализатор; Tabs режимов; блок клише (дата/force/PUT) с fail-open; `basic≥1` на вкладке.
4. Freeze: 20 вкладок, `NAV_ITEMS`, карточки модулей (парность бэк↔фронт); `test_frontend_tab_mapping.py`, `test_webapp_*`, JS-гейты (`node --check web/app.js`).
5. RBAC: `param_permissions`/`canEditConfig` на новых ключах; секреты (ключ F5) не логируются (R17).
6. Полный pytest — 0 failed.

## 6. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Δ каталога ломает `test_param_catalog` (эталон) | осознанный Δ + обновление пинов одним коммитом |
| R2 | High | структурные изменения UI нарушают freeze-меню | freeze-тесты; витрина/`NAV_ITEMS` не трогаются |
| R3 | Medium | карточки пустые при разделении (basic=0) | generic-рендер `basic≥1`; новые ключи advanced |
| R4 | Medium | Stage-1/2 ключи в UI, но рантайм их не читает (мёртвые поля) | кросс-фичевый контракт §4.1 + тест чтения |
| R5 | Medium | рассинхрон с F4-API (гонки) | единый источник истины (F4), идемпотентные вызовы, fail-open |
| R6 | R17/R18 | промпты/ключи утекают в UI/лог | RBAC, без логирования значений |

## 7. Критерии приёмки

- Карточки разделены на Синтезатор/Вербализатор; селектор режимов работает; рантайм читает новые ключи.
- Блок `dynamic_cliche_list`: дата, форс-обновление, ручное редактирование (через F4-API).
- Структура меню не изменена (freeze), `basic≥1` на вкладку.
- Δ каталога зафиксирована; полный pytest — 0 failed.

## 8. Feature flag / раскатка / откат

- Отдельного серверного флага нет: UI-раздел доступен по существующему RBAC/`param_permissions`; чтение Stage-1/2 ключей — fail-safe к код-константам. Откат — `git revert` (PG-значения новых ключей безвредны; код-константы остаются источником при отсутствии ключей).
- Δ каталога — осознанный (новые ключи/группа), фиксируется в spec.

## 9. Зависимости / ступени

- **Зависит от F3** (режимы/`MODE_*_BLOCK`), **F4** (кэш клише + API), **F5** (ступень `web/**` + группа изображений + ступень каталога).
- Общие: `services/param_catalog.py` — ступень F2 → F5 → **F8**; `web/index.html`/`web/app.js` — ступень F5 → F7 → **F8** → F9.
- Кросс-фичевые `hot.get`-чтения §4.1 — в коммите F8 (после F6, без параллельного конфликта).

## 10. Открытые вопросы (Human Gate)

1. Подтвердить, что Stage-1/2 промпты становятся **PG-редактируемыми** (рантайм-чтения §4.1) — это расширяет эксклюзив F3/F6.
2. Подтвердить правило одностадийных модулей (Поиск/YouTube/Веб: только «Вербализатор», без фейкового Синтезатора).
3. Подтвердить, что «Режимы Вербализатора» — общий блок (группа `prompts_verbilizer`), а не per-module.
4. ~~Подтвердить владельца hidden-ключа `content.dynamic_cliche_list` (F4).~~ — **ЗАКРЫТО (review iter1):** ключ в каталоге не регистрируется; владелец данных — F4 (PG-таблица `anticliche_cache`), UI — через `/api/anticliche`.

## 11. Задачи

См. `tasks.md` (T-2167…T-2175). **T-2167** — этот spec + `ADR-1023-8.md` (выполнено).
