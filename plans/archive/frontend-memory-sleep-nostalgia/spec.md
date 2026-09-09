# spec.md — frontend-memory-sleep-nostalgia (ТЗ 4 раунда 10.4, фича C)

Задачи: T-1006…T-1017 (tasks.md). Стадия старта — PLANNED → ARCHITECTED (наст. файл).
База: HEAD `1410a68`. Порядок: после D (аккордеоны уже свёрнуты), до E/A/B.

## 1. Контекст и проблема

Вкладка `memory_rag` («Память и RAG») рендерит ВСЕ категории памяти: `limits_memory`+`limits_graph`+`flags_memory`+все 3 группы `memory_*` (infinite/dream/nostalgia, ~30+ ключей) — перегружена. ТЗ 4: «Память и RAG» → **«Память»**; «Сон» (memory_dream) и «Ностальгия» (memory_nostalgia) — в **отдельные** config-вкладки.

## 2. Ключевые решения

| ID | Решение | Обоснование |
|----|---------|-------------|
| **C-1** | Id существующей вкладки **остаётся `memory_rag`** (label меняется на «Память»); новые id — `memory_dream` («Сон») и `memory_nostalgia` («Ностальгия»), menu `ai`. | Смена id `memory_rag`→`memory` затронула бы TABS-зеркало, маркеры, setTab-переходы, canViewTab/RBAC-категории — дифф без выгоды; label — единственное видимое пользователю изменение (ТЗ: «переименовать label-поля/титулы, id менять НЕ обязательно» — tasks.md T-1007). |
| **C-2** | **TAB_RULES** (services/param_catalog.py:1374-1406):<br>— `TAB_MEMORY_RAG` → `(LIMITS, {limits_memory, limits_graph})` + `(FLAGS, {flags_memory})` + `(MEMORY, {memory_infinite})`;<br>— `TAB_MEMORY_DREAM = "memory_dream"` → `(MEMORY, {memory_dream})`;<br>— `TAB_MEMORY_NOSTALGIA = "memory_nostalgia"` → `(MEMORY, {memory_nostalgia})`.<br>`CONFIG_TAB_TITLES` += «Сон»/«Ностальгия», `TAB_MEMORY_RAG` → «Память». | Категория memory покрыта целиком (infinite+dream+nostalgia), каждая группа ровно на одной вкладке — `_TAB_BY_GROUP` :1424-1431 без ValueError; «Сон»/«Ностальгия» — штатные config-вкладки (generic-рендер), как требует ТЗ «отдельные разделы». |
| **C-3** | **Разметка basic/advanced** — ЯВНАЯ (в данных, не в коде): `_ADVANCED_GROUPS` (param_catalog.py:58-61) — убрать `memory_dream`, `memory_nostalgia` (остаётся {limits_memory, limits_graph, flags_memory, memory_infinite}); в `_MEMORY`-записях (list, :1150-1222) задать прогрессивный уровень: **basic** = `memory.dream_enabled`, `memory.nostalgia_enabled`, `memory.nostalgia_layer_a_enabled` (рубильники-гейты воркеров); **advanced** = ВСЕ остальные (окна/пороги/бюджеты/анти-спам) — параметром `progressive_level`. | После фичи D аккордеон свёрнут ВСЕГДА → вкладка целиком-advanced выглядела бы пустой; рубильники остаются базовыми (видимы сразу) — совместимость с ТЗ 5 (tasks.md T-1008 AC-C3: basic-группа ≥1). Явная разметка вместо изменения `resolve_progressive_level`: локальный аддитивный дифф в данных + существующий маркерный резолвер не трогается. |
| **C-4** | Мини-блоки «Синтез (сон)» и «Ностальгия» (ручной запуск/логи, index.html:783-885, только global admin) **переносятся** с `activeTab === 'memory_rag'` (условие :787) на `activeTab === 'memory_dream'` / `'memory_nostalgia'` соответственно — блоки рендерятся под generic-рендером новых вкладок. | «Сон»/«Ностальгия» — отдельные разделы: ручные кнопки/логи должны быть на СВОИХ вкладках, а не на «Памяти»; API/методы (loadDreamBeliefs/runDreamNow/loadDreamLog/loadNostalgiaLog) — без изменений; гейт `isGlobalAdmin` сохраняется. |
| **C-5** | Гейты `chat_params.gates.{dream,nostalgia}` (F-10) и карточки «Тяжёлые фичи» (modules_feats) — **без изменений семантики**; обновляются только переходы: если в modules_feats есть setTab-переходы на `memory_rag` для «Сон»/«Ностальгия» — актуализировать на новые вкладки (маркеры `setTab('memory_dream'|'memory_nostalgia')`, T-1009). | Гейты — runtime-слой (F-10), вкладки — UI-слой; независимы. |
| **C-6** | RBAC/видимость: `tabCategories` новых вкладок = `['memory']` (существующая секция каталога — `known_sections()` **без расширения**); новые гейты-секции НЕ вводятся (known_sections инвариант: категории + access + chat_lore). | Категория memory уже в RBAC (фаза 2, §18 ARCH); секции не плодим (канон R5/§22). |

## 3. Изменяемые файлы

| Файл | Что меняется |
|------|--------------|
| `services/param_catalog.py` | (1) `_ADVANCED_GROUPS` :58-61 — минус 2 группы; (2) `_MEMORY`-records — добавить поле `progressive_level` (расширение кортежа; обработчик len==6 в `_build_registry` :1294-1297 — по образцу `_LIMITS` :1268-1274); (3) `CONFIG_TAB_TITLES` :1362-1369 — «Память» + 2 новые; (4) `TAB_RULES` — 3 записи (T-1006, AC-C1); (5) константы `TAB_MEMORY_DREAM`/`TAB_MEMORY_NOSTALGIA` рядом с :1353-1360. |
| `web/app.js` (TABS :18-72) | Зеркало: `memory_rag` sources → новые наборы; + записи `memory_dream` (🌙) / `memory_nostalgia` (📼), menu 'ai', type 'config'. MENU_ORDER/MENU_LABELS — без изменений. |
| `web/index.html` | Условия мини-блоков :787 (→ `memory_dream`/`memory_nostalgia`); комментарии-титулы. |
| `tests/test_frontend_tab_mapping.py` | composition memory_rag → новый набор; + memory_dream/memory_nostalgia; ALL_TABS/B-1-зеркало. |
| `tests/test_webapp_nav_disclosure_ui.py` | Маркеры label «Память», вкладок «Сон»/«Ностальгия», `_ADVANCED`-наборов. |
| `tests/test_param_catalog.py` | Эталон 383/71/359 — БЕЗ изменений; + тест разметки dream/nostalgia (basic рубильники ≥1) — можно в новый файл (см. D AC-B1-прецедент). |
| Новые тесты | T-1015: `test_progressive_tab_basic_coverage` (общий для раунда, со старта в D) — проверяет ≥1 basic-группу на каждой config-вкладке. |

## 4. Критерии приёмки

| AC | Критерий | Проверка |
|----|----------|----------|
| AC-C1 | `python -c "from services import param_catalog as p; print(p.tab_group_ids('memory_dream'))"` — без ValueError; `tab_group_ids` трёх вкладок ровно целевые; память покрыта целиком без дублей | импорт-тест /T-1006 |
| AC-C2 | Титулы каталога/фронта синхронны: «Память»/«Сон»/«Ностальгия»; маркер-тесты обновлены (T-1007) | test_frontend_tab_mapping + test_webapp_nav_disclosure_ui |
| AC-C3 | У memory_dream ≥1 basic (dream_enabled); у memory_nostalgia ≥1 basic (nostalgia_enabled, layer_a_enabled); `_ADVANCED_GROUPS` — без этих групп | юнит-тест разметки (T-1008) + AC-B1-тест D-фичи |
| AC-C4 | Маркеры `setTab('memory_dream')`/`setTab('memory_nostalgia')` (если переходы были в modules_feats) | test_webapp_nav_disclosure_ui |
| AC-B1 | TABS-зеркало синхронно TAB_RULES (маркеры exact-строк); `node --check` clean | T-1010 |
| AC-B2 | Вкладки открываются (generic-рендер); аккордеон свёрнут по умолчанию (фича D); «(0)» не рендерится; нет TypeError | test + live T-1017 |
| AC-B3 | Категория видимости новых вкладок — `memory`; новые RBAC-секции не введены | `known_sections()` без изменений (тест) |
| AC | Полный pytest 0 failed (baseline 4831 + новые); `node --check`; `git diff --check` | T-1016 |

## 5. Негативные тесты (что НЕ сломать)

- **REGISTRY 383 / 71 группа / Settings 359** — только переносы/разметка; новых ключей/групп НЕТ (эталон test_param_catalog).
- **Гейты F-10**: `gates.dream`/`gates.nostalgia`, opt_in, резолв `gates_enabled` — без дифов (gates API не меняется).
- **Воркеры**: DreamWorker/NostalgiaWorker (уровень поведения) — НЕ меняются (только UI/каталог); `memory_dream_log`/`nostalgia_log` API/минимал-блоки — без изменений.
- **SQLite v8** — без дифов; **промпты/каноны** (в т.ч. R9, PREV_R9, FACT_EXTRACT_PROMPT R46-2) — без дифов.
- **`_TAB_BY_GROUP`** — без ValueError (никакая группа не «в двух вкладках»); «Память» не пустеет: memory_infinite + limits_memory + limits_graph + flags_memory ≥1 basic (маркеры: memory_infinite в _ADVANCED_GROUPS — все advanced?? ПРОВЕРКА: memory_infinite — 1 ключ `memory.infinite_retention` (bool-тумблер!), в _ADVANCED_GROUPS → advanced. Проблема AC-B1: у memory_rag basic-группа должна быть ≥1: limits_memory/limits_graph/flags_memory — имеют basic-ключи? limits_memory содержит… многие с маркерами (ttl/window/retr?), но есть и без маркеров (например, memory_backup_enabled? НЕТ — это флаги). РИСК: вкладка «Память» может получить 0 basic-групп. **Решающий вопрос** — нужно проверить content групп. Если обе limits_memory/limits_graph/flags_memory полностью advanced — нужно переразметить и их (вынести рубильники flags_memory в basic). ТАКОЕ решение: **C-7**: проверить/гарантировать ≥1 basic у каждой вкладки: если в группах памяти нет ни одного basic — переразметить рубильники (напр. `memory.infinite_retention`, `flags.graph_rag_enabled`/`flags.memory_extract_enabled` и т.п. — по факту каталога; выбор — рубильники-вкл/выкл механизмов, НЕ пороги). Точный список — по факту `resolve_progressive_level`-разметки текущего каталога (уровень «проверить на старте фичи; если нужно — точечные `progressive_level='basic'` на флагах-вкл). Это РАСШИРЯЕТ скоуп C минимально (разметка, не каталог). Зафиксировать в AC-C3 как «≥1 basic у КАЖДОЙ из memory_rag/memory_dream/memory_nostalgia». |
- **Маркеры MED-022**: обновляются маркеры только затрагиваемых тестов; `test_webapp_*` (avatars/dm/rbac) без изменений (вкладки памяти не в их скоупе).
- **Роутеры bot.py** — без дифов.

## 6. Границы (вне скоупа)

- Изменение поведения воркеров (окна/бюджеты) — фича G (пер-чат) / вне раунда.
- Перенос «Ностальгия»-блоков куда-либо ещё (кроме двух новых вкладок) — не разрешено.
- Глобальный флаг `flags.summary_enabled`/summary-каскад имён — фича B.
- Новые id вкладок для чего-либо кроме двух — не разрешено.

## 7. Риски и блокеры

| Риск | Митигация |
|------|-----------|
| **Риск C-1 (главный)**: вкладка «Память» (после выноса dream/nostalgia) может не иметь basic-групп (memory_infinite advanced; limits_memory/limits_graph/flags_memory могут быть полностью advanced по маркерам). | C-7: точечная переразметка рубильников-вкл в basic (флаги/выключатели: `memory.infinite_retention`, `flags.graph_rag_enabled`, `flags.memory_commands_user_enabled` и т.п. — по факту; пороги остаются advanced). Проверка: AC-B1-тест (из фичи D) + AC-C3. **Блокер-D**: тест из фичи D «≥1 basic на вкладку» должен быть зелёным в конце C — иначе раунд блокируется на сверке. |
| **Риск C-2**: смена label «Память и RAG» зацепит тексты-маркеры в test_webapp_* (лишние обновления). | grep-маркеры по label обновляются только в test_webapp_nav_disclosure_ui; другие файлы — проверить git grep «Память и RAG» (doc/README — вне скоупа кода; README-актуализация — финальная фаза раунда). |
| **Риск C-3**: DSC «Сон»-миниблок переехал на memory_dream, но гейт `isGlobalAdmin` — у local_admin вкладка с настройками видна, без миниблока — приемлемо (миниблоки административны, как было). | Функционально не меняется; live-проверка T-1017. |
| **Блокер**: нет. | — |

## 8. Зависимости

- До: D (аккордеоны). После: E, A, B, F, H, G.
- Взаимно с A: фича A переносит limits_lore/flags_lore — не пересекается с памятью; фича E перераспределяет models/keys — не пересекается.
- G (per-chat): память-лимиты сохранят hot.get-чтение до G; G использует `get_chat_param` поверх — совместимо (без изменения каталога).
