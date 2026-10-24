# ARCH-QUOTA-AUDIT — сквозной аудит квот инструкций LLM (ADDENDUM #3)

Лейн: `ARCH-QUOTA-AUDIT` (read-only, без прода). Источник: `source-addendum3-2026-10-24.md` §1–§6.
Метод: статический разбор всех реально используемых путей `источник инструкции → builder → wrapper → payload`
по 457 `.py` (`services/**`, `bot.py`, `web/**`, `config/**`, `SmartModule/**`, `tools/**`) + адресное чтение
30 файлов. Критерий A/B/C — §2.5 источника. Runtime-payload дампы **не** снимались (см. §7).

## 1. Карта путей (реальные entry points к LLM)

| # | Путь | Источник инструкций | Builder | Wrapper | Квоты на пути |
|---|------|--------------------|---------|---------|----------------|
| 1 | Новая речь, Direct L2-writer | Core (`character.core`), Expression, Style Policy, ResponsePlan | `prompt_composer.compose_prompt` | `llm.generate` | **A1–A4, A6** |
| 2 | Direct L1 planner / ReAct / tool-loop | `direct_l1`, `tool_schemas` | `direct_execution`, `tool_loop` | `llm.generate`/`generate_chat` | B (output/loop) |
| 3 | Direct synth/fallback | база канала + plan | `prompt_style_blocks.compose_verbalizer_system` | `llm.generate` | нет |
| 4 | Factcheck stage-2 (вербализатор) | `factcheck_prompts` + Core+Expression (`speech_owner_block`) | `compose_verbalizer_system` | `llm.generate` | нет (`{max_symbols}` = вывод, B) |
| 5 | Factcheck claim/tool-loop, temporal | `factcheck_orchestrator/planner/prompts` | там же | `llm.generate` | нет |
| 6 | Checkup | `checkup_prompts` + Core/Expression/Style | `checkup_service` | `llm.generate` + `apply_style_policy` | нет |
| 7 | Summary L1 clusterizer | `summary_prompts` + `summary_l1_*` | `summary_l1_clusterizer` | `llm.generate` | B (окно/`max_symbols`) |
| 8 | Summary L2 writer/review/repair + legacy fullwindow + supervisor | `summary_prompts`, `summary_l2_*` | там же | `llm.generate` | B (данные), C6 |
| 9 | Memory / GraphRAG / memory_maintenance | `summary_memory`, `mca_retrieval_context` | там же | `llm.generate` | B (выборка/ранжирование) |
| 10 | Experience / self-reflection | `mca_experience_jobs`, `self_reflection` | там же | `llm.generate` | нет |
| 11 | Sleep / Deep Sleep | `dream_prompts` | `dream_worker` | `llm.generate` | B (учёт денег, `max_facts`) |
| 12 | Досье / портреты | `dossier_prompts` | `dossier_rebuild_jobs` | `llm.generate` | C2 |
| 13 | Initiative / Observer / диагностика | `initiative_observer`, plan | там же | `llm.generate` | B (output 700) |
| 14 | Lore compiler/worker, Nostalgia, Anticliche | `lore_prompts`, `nostalgia_prompts` | `*_worker/service` | `llm.generate` | C5, B |
| 15 | Episodes / Exploration / Humor craft+feedback | `mca_episode_prompts`, `mca_humor_*` | там же | `llm.generate` | B (выборка) |
| 16 | Search / Web / YouTube summarizers | `search_prompts`, `web_prompts`, `youtube_prompts` | там же | `llm.generate` | нет (`{max_symbols}` = вывод) |
| 17 | Image/vision prompt compiler, `tools/history_import` | свои шаблоны | там же | `llm.generate`/image API | B (не инструкции речи) |

Вывод: самостоятельный бюджет инструкций существует **только** в пути №1 (Composer) и в его поставщиках
(Core/Expression examples/Style hint). Остальные пути инструкции не режут — режут данные, вывод или считают окно.

## 2. Инвентаризация ограничений

### A — удалить (искусственная квота инструкций при достаточном окне)

| ID | file:line | Что именно ограничивает | Доказательство |
|----|-----------|------------------------|----------------|
| A1 | `services/mca_gates.py:2473-2495` (+ витрина `web/api/speech.py:1081,1181-1186,2258`) | `composer_additive_budget_tokens()`: синтетический бюджет «добавки» слоёв, дефолт **1200**; `<=0` возвращает `0`, а не `None` | ключа нет в `config/settings.py` и `param_catalog.py` — только `getattr`+env; докстринг обещает «<=0 → без лимита», код возвращает `0`; бюджет виден в Inspector/Core-API, т.е. это настройка, которую владелец требует убрать |
| A2 | `services/prompt_composer.py:1242,1574,1612,1641,1680` | `budget is not None and consumed+cost > budget` вытесняет `humor_craft`, `expression_examples`, `few_shot`, `style_policy_hint` | функция возвращает `int` → `is not None` **всегда** истинно; при `0` вытесняется всё аддитивное |
| A3 | `services/prompt_composer.py:1680-1685` | `style_policy_hint → skip_reason="budget_excluded"` (прод-симптом §2.7) | hint — слой №10, последний в бюджете: 1200 «съедают» Core+Expression+examples |
| A4 | `services/prompt_registry.py:1209-1214` (+ вызовы `prompt_composer.py:807-809,942`) | **редакция Personality Core**: `detail_level=full` принудительно → `compact`, причина `context_budget`, если full > 1200 ток. | квота Core тем же аддитивным бюджетом; выбор владельца молча подменяется |
| A5 | `services/mca_expression.py:181-185,518-542,596-599` | few-shot Expression: `MAX_ITEMS=4`, `MAX_CHARS=700`, `MAX_TOKENS=140`; не влезло → `skip_reason="budget_excluded"`, блок исчезает целиком | это авторские примеры речи, а не данные; при `140` ток. блок часто пуст |
| A6 | `services/prompt_composer.py:1330,1523` | сравнение с бюджетом для Core/Expression (спасает только запись `ConflictRecord`, расход всё равно считается) | после A1–A2 сравнение теряет смысл и должно уйти вместе с бюджетом |

### B — сохранить (техническое/функциональное/fallback/деньги)

`token_counter.truncate_to_tokens`/`keep_head` (общий инструмент, применяется к данным); `context_middleware.py:53-89`
(история чата, header-safe); `summary_hybrid_budget.py:87-117` (**вычитает system из бюджета данных** — образец
правильного поведения); `summary_l1_clusterizer.py:1556-1583` + `model_capacity.py` (реальное окно/`max_output`);
`llm_client` (`max_tokens`, таймауты, retry, `budget`=время, `_BODY_MAX_CHARS`, `_AUTH_BODY_MAX_CHARS` — маскировка);
`worker_budget.py` (деньги/вызовы); `{max_symbols}` в factcheck/checkup/summary/search/web (объём **ответа**);
`_DIG_RESULT_MAX_CHARS=3600`; `CHAT_CURRENT_QUESTION_MAX_CHARS`; `relations/lore/graph_rag_*_max_chars` (выборка
данных); `dream_prompts` `max_facts/max_beliefs`; `prompt_factory.py:254` (история); `initiative` `max_tokens=700`.

### C — проверить, не удалять

| ID | file:line | Почему C |
|----|-----------|----------|
| C1 | `direct_chat_service.py:7826-7833` | `chat_style_anchor_max_chars` режет **примеры стиля** по символам — влияет на подражание, но это образцы, не директивы |
| C2 | `direct_chat_service.py:448,8153-8172` | `_PERSONA_DOSSIER_MAX_CHARS=1200` — досье в промпте: данные или инструкция? |
| C3 | `direct_chat_service.py:7979-7992` | `_MEMORY_FACT_MAX_CHARS=500` — факт памяти |
| C4 | `style_policy.py:931-939,1038` + `prompt_style_blocks.py:659-668` | `hint_limits.max_chars/max_items` режут **инструкции Style Policy** (`user_limit`); сейчас дефолт `0`=off и это видимый выбор владельца, а не скрытый |
| C5 | `lore_prompts.py:153-207` | `<chat_lore>` обрезается с маркером `…[обрезано]` — данные чата, но влияет на стиль |
| C6 | `summary_l2_anchor_repair.py:246`, `summary_l2_review.py:390` | `instruction[:500]` — проверить, что это телеметрия, а не payload модели |

## 3. Composer — дизайн (заморозка)

1. **Удалить** `COMPOSER_LAYER_BUDGET_TOKENS` полностью: `mca_gates.composer_additive_budget_tokens()`,
   env-ветку, `getattr(settings, …)`, витрину `web/api/speech.py:_composer_budget` + все её вызовы, ключ
   каталога/UI (если появится), миграции, восстанавливающие значение. Тесты, пиннящие квоту
   (`test_asap3_acceptance.py:268`, `test_add_exp_expression.py:416,972`, `test_soul1_core_*`) перевести на
   новый контракт: они защищают отменённую владельцем квоту, а не требование.
2. `compose_prompt`: убрать `budget`/`consumed` и все `budget_excluded`-ветки (A2/A3/A6). Порядок слоёв,
   `_append`/`_joined`, `traces`, `ConflictRecord`, `estimate_tokens` (для `tokens_total`) — **сохранить**.
   `skip_reason` остаются только смысловые: `profile:*`, `*_disabled`, `*_absent`, `not_owner_approved`.
3. `prompt_registry.core_selection`: удалить параметр `budget_tokens` и причину `context_budget`;
   `detail_level` — единственный источник выбора; `full_text_missing`/`compact_text_missing` остаются fallback.
4. Реальное окно не трогать: `model_capacity`, `CHAT_CONTEXT_BUDGET_TOKENS`, summary hybrid budget,
   `llm_client.max_tokens`. Переполнение — честная деградация/ошибка, **не** молчаливое вытеснение инструкций.
5. Семантика `0` vs `None` исчезает вместе с функцией — третьего состояния не вводить.
6. Inspector: причины `budget_excluded` у core/expression/humor/examples/hint больше не существуют; показывать
   фактические (`style_policy_absent`, `core_disabled`, `profile:*`). «Бюджеты» (модуль чата) не затрагивать.

## 4. Кавычки — дизайн

Сейчас: `style_policy._apply_quotation_marks` (`1681-1766`) — семантика (ирония, многословность →
`quotes_require_rephrase`, `risk=irony_may_be_lost`), пресет `no_quotes` (`193-205`), hint `HINT_QUOTES_HARD/SOFT`
(`prompt_style_blocks.py:449-453`), kind в `RULE_ORDER`/`_TYPOGRAPHY_KINDS` (`web/api/speech.py:1684`).

Целевое: **два детерминированных режима** в существующем `kind="quotation_marks"`, поле `params.mode`:
`replace` (заводской ON: `«`→`"`, `»`→`"`, содержимое не меняется) и `strip` (заводской OFF: удалить `«`, `»`, `"`
в обычном тексте, содержимое остаётся). Взаимоисключение — в нормализации (`normalize`/`resolve`): активен ровно
один режим, `strip` перекрывает `replace`; оба OFF допустимы. Защищённые сегменты — существующие `Span`-виды
(`SPAN_KINDS`, `style_policy.py:90`): `url/code/json/verbatim_quote/telegram_entity` не трогаются; апостроф `'`
в новых режимах **не** обрабатывается вовсе. Удалить ветки иронии/многословности/unpaired-конфликтов и
`risk=irony_may_be_lost`; `_protected_machine_quotes` оставить как защиту. `no_quotes` → alias режима `strip`
(миграция `presets_applied`), отдельного правила-конкурента не остаётся. Hint: `replace` — без инструкции Writer
(детерминированно), `strip` — одна строка «без кавычек». UI: два чекбокса в существующей секции Style Policy,
глобально + per-chat override тем же merge; миграция сохраняет явные выборы владельца.

## 5. FREQUENT — вывод

Кодом подтверждено: инструкция **доставляется** и не режется — `<Expression_Settings>` (~85–96.3% сборки) плюс
повтор в самом конце system (`prompt_composer.py:1712-1719`, `mca_expression.render_expression_final_contract`),
постпроцессора вставки/удаления мата нет (`mca_expression.py:14` EXP-INSTR.NOPOST; `direct_chat_service.py:1656-1687`
только считает). Значит «не доставлено» — исключено; «урезано квотой» — тоже, кроме **A5** (few-shot режима часто
пуст из-за 140 ток./700 симв. — а примеры сильнее директивы). Остаются: (1) выравнивание конкретной модели/провайдера,
(2) конкуренция Core/функциональных промптов, (3) директива без демонстрации. Минимум: снять A5, добавить
owner-approved FREQUENT-примеры, прогнать офлайн OFF/OCCASIONAL/FREQUENT на боевой модели. Если модель систематически
игнорирует — честно зафиксировать как ограничение модели (замена модели — решение владельца, не агента). Механику
вставки, проценты и рандом не вводить.

## 6. План и параллельность

1. **QUOTES** (`style_policy.py`, `prompt_style_blocks.py`, `web/api/speech.py`, `web/app.js`, миграции) ∥
2. **COMPOSER-QUOTA** (`mca_gates.py`, `prompt_composer.py`, `prompt_registry.py`, `config_migrations.py`, `param_catalog.py`, тесты) ∥
3. **AUDIT-фиксы** по C1–C6 (после решения по каждой) → 4. **FACTCHECK/SUMMARY/прочие** — регрессия payload (A нет) →
5. **ACCEPT**: payload по группам, офлайн-пробы речи, Inspector, сохранность после рестарта.
Не трогать: fallback/retry, `model_capacity`/реальное окно, модуль «Бюджеты», функциональные лимиты объёма.
Риск R2: снятие квот увеличивает payload → на слабых моделях возможен реальный overflow; закрывать
`model_capacity` и честной ошибкой, а не новым лимитом. Конфликт файлов: `web/app.js` (asap3-corrective).

## 7. Покрытие и непроверенное

Покрыто: 17 групп путей (таблица §1), все `services/**` через адресный поиск по `budget|truncate|slice|max_chars|
max_tokens|estimate_tokens|budget_excluded`, чтение Composer/Registry/Expression/Style/token_counter/summary/checkup/
factcheck/lore/dream. **Не проверено runtime**: фактические payload по 17 путям, поведение после рестарта,
провайдерские различия моделей; C2/C4/C6 требуют подтверждения назначения. Прод/SSH не использовались.
Утверждать «полную очистку проекта» до runtime-подтверждения нельзя.
