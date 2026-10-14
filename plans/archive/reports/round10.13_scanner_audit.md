# Round 10.13 — Scanner Audit (независимый аудит diff)

> Аудитор: @Scanner (Step 6, фоновый аудит логических дефектов). Дата: 13.09.2026.
> База: HEAD `ce25dc7`, рабочее дерево (uncommitted) + untracked.
> Объём: 54 изменённых файла + 7 новых модулей/каталогов/тестов (~4375 insertions).
> Метод: diff-based + точечная проверка критичных путей; прогоны validator.
> Зависимость от отчёта @Reviewer отсутствует (аудит независимый).

## 1. Сводка

| Severity | Кол-во |
|---|---|
| Critical | **0** |
| High | **1** |
| Medium | **4** |
| Low | **9** |

Прогоны:
- `.venv/Scripts/python.exe -m pytest -q` → **5383 passed**, 1 warning (60.6 s), exit 0.
- `node --check web/app.js` → clean.
- `node tests/js/routing_test.js` → `JS-UNIT-OK`.
- Каталог-инварианты (рантайм): REGISTRY **427**, Settings **399**, categorized **403** (427−24 `None`),
  GROUPS **90**, `_TAB_BY_GROUP` **88**, TAB_RULES **19** — совпадают с заявленными.

Контрактные инварианты диффа: ноль новых PG-DDL (проверено grep), SQLite v8 не бампнут,
порядок роутеров `bot.py` не тронут (только DI-kwarg `aliases=`), новых `v-html` нет,
секреты в логах/ответах не замечены.

## 2. Findings

| ID | Sev | Файл:строка | Описание | Рекомендация |
|---|---|---|---|---|
| S10.13-1 | **High** | `services/summary_memory.py:721` (+`:748-755`, `:779-800`) | **Неэкранированный автор (`target_user`) в RAG-промпте.** `_fact_prefix` подставляет `name` в `[ММ.ГГГГ \| Автор: {name}]` без `escape_xml_text`. Потребители — `_format_origin_labeled_line` (`origin_labels=True` → `<RAG_Memory>`) и `build_rag_context` (`<context>`), а также `tool_router.dig_into_lore`. `fact` экранируется, `author` — нет. Проверено рантаймом: `_fact_prefix(ts,'a\nb')` и `_format_origin_labeled_line((..., 'Вася</RAG_Memory><evil>'))` возвращают символы как есть (docstring прямо требует «escape_xml_text ОБЯЗАТЕЛЕН»). Риск: поломка XML-структуры промпта и prompt-injection через display-name/извлечённый `target_user`. | Экранировать `name` в `_fact_prefix` (или в `_format_origin_labeled_line`/`build_rag_context`) через `escape_xml_text`; добавить регресс-тест на `<`/`>`/`\n` в `target_user`. |
| S10.13-2 | Medium | `services/dream_worker.py:1130-1145`, `:1232`, `:1314-1318`, `:1347` | **Глубокий сон: cooldown и суточный кап обходятся на не-успешных прогонах.** Маркер `deep_run` пишется только когда `written>0` (`:1232`); cooldown читает `last_deep_run` (`:1136`), а суточный лимит — `count_dream_log(kind='deep_run')>=1` (`:1132-1135`). Если прогон дал `no_anchors/unchanged/duplicate/error`, маркера нет → попытки повторяются каждый тик/after_sleep. При этом `_deep_budget_ok` суммирует только `deep_run` (`:1314-1315`), а токены скипов пишутся как `deep_skip` (`:1347`) и в кап не входят; retry (`:1191`) не перепроверяет бюджет. Итог: dedicated-кап 40000/сутки фактически не работает (ограничивает только общий worker_budget 200 вызовов/сутки). | Писать маркер попытки (`deep_skip`/`last_attempt`) в гейт cooldown; считать кап по `deep_run + deep_skip`, либо логировать `deep_run` с tokens на каждой попытке; перепроверять бюджет перед retry. |
| S10.13-3 | Medium | `services/dream_worker.py:885` | **F2-decay включает F3-парадигмы.** `list_confirmed_beliefs()` = `kind='belief' AND status='confirmed'` без исключения `belief_meta.type='paradigm'`. Парадигмы (weight 0.55) через ~180+90 дней без подкрепления уйдут в `archived_belief` по общей формуле `base−0.1×месяцы<0.3`, т.е. «фоновый исторический слой» F3 со временем распадается; кроме того они попадают в `beliefs_active`/`beliefs`-счётчики (см. S10.13-6). | Исключить парадигмы из `_decay_step` (`belief_meta NOT LIKE '%"type"...%"` или `belief_type != paradigm`) либо задать им отдельный порог/бессмертие; поправить счётчики. |
| S10.13-4 | Medium | `services/dream_worker.py:1003-1008`; `services/memory_health.py:76-78`; `web/api/memory_agi.py:313` | **Воскрешения Сон-Реаниматора не попадают в телеметрию.** Реаниматор логирует `kind='skipped', status='resurrected'` (`:1004-1008`), а `resurrections_total` (API) и строка health считают только `kind='resurrect'` (пишет лишь путь векторного резонанса). Timeline (`_DREAM_TIMELINE`, `memory_agi.py:548`) тоже не знает `skipped` → реаниматор невидим во всех счётчиках, хотя `belief_meta.resurrections` инкрементится. | Считать воскрешения по `belief_meta.resurrections` либо логировать реаниматор отдельным kind/счётчиком; добавить `skipped` в Timeline (с текстом «Реанимация»). |
| S10.13-5 | Medium | `web/app.js:4829`, `:4832` | **F5: ленты «Убеждения»/«Парадигмы» игнорируют выбранный чат.** `loadCognition` строит `q = this._cidQuery(true)` и применяет его к cognition/status, stats, timeline, graph, но запросы `/api/memory/dream/beliefs?kind=belief&limit=30` и `?kind=paradigm` идут без `chat_id`. При выбранном чате виджет показывает глобальные данные, остальные блоки — чатовые. | Добавить `&chat_id=` (аккуратно с `?limit=`-порядком) в оба запроса. |
| S10.13-6 | Low | `services/database.py:3534-3549` | **Счётчики `graph_stats` неточны.** `facts` = `kind='fact'` без `status` (учитывает unconfirmed), `beliefs` = все `kind='belief'` (включая парадигмы и архив), `archived_beliefs` — подмножество `beliefs`. Виджет «Интеллект и Память» и «Модули» показывают пересекающиеся/завышенные числа. | Для `facts` добавить `status='confirmed'`; из `beliefs` исключить `belief_meta.type='paradigm'` (или явно назвать «все kind=belief»). |
| S10.13-7 | Low | `services/dream_worker.py:878-883`, `:1308-1309`, `:1165` | **`or <default>` не даёт задать 0.** `step`, `arch`, `cap`, `top_k`, `max_paradigms` через `float(... or 0.1)`, `int(... or N)` — значение `0`/`0.0` (валидное: отключить кап/декай) подменяется дефолтом. | Использовать `hot.get(..., None)` + явную проверку `is None`. |
| S10.13-8 | Low | `services/dream_worker.py:216-217` | **TZ глубокого сна ≠ спека.** `self._tz_name` = `limits.summary_timezone`; spec F3 §3/§4 предписывает `WORKER_BUDGET_TZ`. Дефолты совпадают, но при независимой настройке окно суточного капа и `deep_sleep_hour` считаются в другом TZ, чем worker_budget. | Взять `settings.WORKER_BUDGET_TZ`/`worker_budget.DAY_TZ` для deep-sleep либо синхронизировать спека↔код. |
| S10.13-9 | Low | `web/api/memory_agi.py:598` | **Timeline: источник лора — in-memory инжект, а не `chat_lore_history`.** Spec F5 §3.5 указывает `chat_lore_history` (обновление лора); реализовано `get_process_accounting().lore_last_inject_at` (сбрасывается рестартом, не per-chat). | Либо привести спеку к реализации (инжект как источник), либо читать `chat_lore_history`. |
| S10.13-10 | Low | `web/app.js:2332-2338`; `services/llm_probe.py` (`probe_openai`) | **Probe не зеркалит runtime-фолбэк F4.** `testBlock` шлёт base/model только из полей блока; `generate_worker` при пустом `model` берёт `_chat_model`, при пустом `base` — main base. Пользователь, задавший только `base_url` выделенной модели, получит ложный `error/not_configured` («Проверить»), хотя рантайм будет работать на основной модели/ключе. | В probe при пустых `model`/`base`/`key` подставлять значения основной модели (как `_saved_api_key` для ключа). |
| S10.13-11 | Low | `services/database.py:2079-2080`, `:2128` | **JSON-маркер парадигм матчится только в двух вариантах сериализации** (`"type":"paradigm"` / `"type": "paradigm"`). Любой иной пробел/перенос (`"type" : "paradigm"`) вне записи `json.dumps` (ручная правка hot/бэкап) сломает фильтры `count_paradigms`/`belief_type`. | Хранить явный `belief_meta.type`-флаг отдельно (напр. `status`) либо нормализовать JSON перед чтением. |
| S10.13-12 | Low | `.env.example:262-278`; `services/lore_prompts.py:60,85`; `services/param_catalog.py` (IRONY_FILTER_ENABLED) | **Доки/описания флагов неточны.** В `.env.example` нет `BELIEF_*` (6 ключей) и `IRONY_FILTER_ENABLED`. Ироническая заметка в `LORE_INIT/MERGE_SYSTEM_PROMPT` добавляется безусловно: при `flags.irony_filter_enabled=OFF` синтез лора всё равно меняется, что противоречит описанию каталога «поведение без изменений». | Добавить ключи в `.env.example`; уточнить описание флага (OFF гейтит классификацию/блоки, но не правку канона лора). |
| S10.13-13 | Low | `services/database.py:1920`; `services/dream_worker.py:_belief_meta`; `services/summary_memory.py:_belief_base_weight` | **Три дублирующих парсера `belief_meta`** (dict/JSON/broken) с почти одинаковой логикой. | Свести к одному хелперу (напр. в `database.py`) и переиспользовать. |
| S10.13-14 | Low | `services/database.py:graph_snapshot` (edges) | **Возможны «висячие» рёбра.** После cap по `max_nodes`/`max_edges` рёбра выбираются по `source_id IN (...) OR target_id IN (...)`; ребро на усечённый/не попавший узел остаётся и отдаётся во фронт (vis-network молча пропускает/варнит). Косметика/шум консоли. | Фильтровать `edges` так, чтобы оба конца входили в отданный `node_ids`. |

## 3. Итог по severity

- **Critical: 0.**
- **High: 1** — S10.13-1 (неэкранированный автор в RAG-промпте).
- **Medium: 4** — S10.13-2, S10.13-3, S10.13-4, S10.13-5.
- **Low: 9** — S10.13-6…S10.13-14.

## 4. Вердикт по контракту

**High открытых: ЕСТЬ (1).** Critical открытых нет.

S10.13-1 — регрессия инварианта экранирования `summary_xml`; High-статус обоснован тем, что
в промпт LLM попадает неэкранированный пользовательско-производный `target_user` внутри
теговых обёрток. Правка локальная (1–3 строки + тест), блокирует прохождение до устранения.

Remediation-порядок для @Builder: S10.13-1 → S10.13-2/-3 → S10.13-4/-5 → Low-пакет.

---

## 5. Повторный аудит (итерация 2)

> Дата: 13.09.2026. База: тот же HEAD `ce25dc7`, рабочее дерево после правок @Builder.
> Метод: повторная проверка кода по file:line + рантайм + полный validator-прогон.

### 5.1 Статус findings

| ID | Sev | Статус | Доказательство |
|---|---|---|---|
| S10.13-1 | High | **closed** | `services/summary_memory.py:723-728` — `escape_xml_text(name)` + схлопывание `\n\t` через `" ".join(...split())`; `_format_origin_labeled_line` (`:767-768`) всё экранирует. Рантайм: `_fact_prefix(ts,'Вася</RAG_Memory><evil>')` → `[...&lt;/RAG_Memory&gt;&lt;evil&gt;] `; `'a\nb\tc'` → `[... a b c]`. Регресс-тест `tests/test_webapp_round1013_ui.py:63-84`. |
| S10.13-2 | Medium | **closed** | `dream_worker.py:1153-1156` — cooldown/суточный лимит читают `count_deep_attempts`/`last_deep_attempt`; `_log_deep_skip:1373-1381` пишет `kind='deep_skip'` на всех не-успешных путях (`:1190,1199,1203,1215,1220,1226,1229,1268`); `_deep_budget_ok:1329-1348` суммирует `deep_run`+`deep_skip` и учитывает `extra_tokens`; retry перепроверяет бюджет `:1213-1216`. БД: `database.py:2088-2117`. Тесты: `tests/test_deep_sleep.py:606-637`. |
| S10.13-3 | Medium | **closed** | `database.py:1932-1954` — `list_confirmed_beliefs` исключает `belief_meta.type='paradigm'` (`IS NULL OR NOT LIKE …`). Тест `tests/test_belief_decay.py:215-228` (400 дней → `checked==0`, `status=confirmed`). |
| S10.13-4 | Medium | **closed** | Реаниматор пишет `kind='resurrect'/status='resurrected'` (`dream_worker.py:1019-1026`), как и векторный резонанс (`summary_memory.py:2337-2338`). Телеметрия: `memory_health.py:80-82`, `web/api/memory_agi.py:313` (`count_dream_log(kind='resurrect')`), Timeline `memory_agi.py:548-553`. Тест `tests/test_belief_decay.py:390-394`. |
| S10.13-5 | Medium | **closed** | `web/app.js:4830-4835` — `var cq = this._cidQuery(false)` добавлен к обоим запросам `/api/memory/dream/beliefs?kind=belief|paradigm&limit=30` (+`&chat_id=`). |
| S10.13-6 | Low | **closed (partial)** | `database.py:3579-3581` `facts` = `status='confirmed'`; `:3584-3589` `beliefs` без парадигм. Остаток: `archived_beliefs` (`:3590-3592`) всё ещё без фильтра парадигм → см. новый S10.13-6b. |
| S10.13-7 | Low | **closed** | `_hot_number` (`dream_worker.py:153-164`) заменяет `or default` во всех чтениях (`:896-901,1006,1161,1185,1235,1338`), `None/''` → default, `0` сохраняется. |
| S10.13-8 | Low | **closed** | `dream_worker.py:232-235` — `_deep_tz_name` из `limits.worker_budget_tz`/`WORKER_BUDGET_TZ`. |
| S10.13-9 | Low | **open** | Timeline-лор по-прежнему из in-memory `get_process_accounting().lore_last_inject_at` (`web/api/memory_agi.py:596-604`), а не `chat_lore_history`. |
| S10.13-10 | Low | **closed** | `services/llm_probe.py:114-140` (`_intel_probe_fallback`) + вызов `:298-300`; тесты `tests/test_deep_sleep.py:640-679`. |
| S10.13-11 | Low | **open** | LIKE-маркер парадигм по-прежнему матчит только 2 варианта сериализации (`database.py:1941-1942,2056-2057,2126,2170-2171,3586-3589`). |
| S10.13-12 | Low | **closed** | `.env.example:265-296` (+`DEEP_SLEEP_*`, `BELIEF_*`, `IRONY_FILTER_ENABLED`); описание флага уточнено (`services/param_catalog.py:808-812`). |
| S10.13-13 | Low | **open** | Три парсера `belief_meta`: `database.py:1919-1930`, `dream_worker.py:857-869`, `summary_memory.py:70` — не сведены. |
| S10.13-14 | Low | **open** | `database.py:3538-3541` — рёбра по `source IN(…) OR target IN(…)` без гарантии обоих концов в `node_ids`. |

### 5.2 Новые находки итерации 2

| ID | Sev | Файл:строка | Описание | Рекомендация |
|---|---|---|---|---|
| S10.13-6b | Low | `services/database.py:3590-3592` | **Остаточная несогласованность `archived_beliefs`.** После фикса S10.13-6 `beliefs` исключает парадигмы, а `archived_beliefs` (`kind='belief' AND status='archived_belief'`) — нет. Для легаси/вручную архивированных парадигм `graph_stats.archived_beliefs` разойдётся с `count_beliefs_by_status`/health (там фильтр есть). | Добавить в `archived_beliefs` те же NOT LIKE-условия, что в `beliefs`. |

### 5.3 Итог по severity (итерация 2)

| Severity | Итерация 1 | Итерация 2 (открытых) |
|---|---|---|
| Critical | 0 | **0** |
| High | 1 | **0** |
| Medium | 4 | **0** |
| Low | 9 | **5** (S10.13-9, -11, -13, -14 + новый S10.13-6b; S10.13-6 закрыт частично) |

Закрыто полностью: S10.13-1 (High), S10.13-2/-3/-4/-5 (Medium), S10.13-7/-8/-10/-12 (Low) = 9 findings.

### 5.4 Validator (итерация 2)

- `.venv/Scripts/python.exe -m pytest -q` → **5392 passed**, 1 warning (StarletteDeprecation), 60.75 s, exit 0 (было 5383; +9 новых тестов).
- `node --check web/app.js` → **clean**.
- `node tests/js/routing_test.js` → **JS-UNIT-OK**.
- `git diff --check` → **OK** (только предупреждения LF→CRLF, не whitespace-ошибки).

### 5.5 Инварианты (итерация 2)

- Ноль новых PG-DDL: grep добавленных строк по `CREATE/ALTER/DROP TABLE|ADD COLUMN|CREATE INDEX` — пусто.
- SQLite v8 не бампнут: `services/database.py:53 _SCHEMA_VERSION_AGI_MEMORY = 8`.
- Порядок роутеров `bot.py` не тронут: diff — только DI-kwarg `aliases=AliasResolver(...)` в `LoreWorker`.
- Каталог: REGISTRY **427**, GROUPS **90**, `_TAB_BY_GROUP` **88**, TAB_RULES **19** (рантайм); Settings **399**/categorized **403** подтверждены проходящими `test_param_catalog.py`/`test_frontend_tab_mapping.py`.
- R17 (секреты не в ответах/логах) — полный прогон тестов зелёный.
- vis-network self-host: `web/static/vendor/vis-network/vis-network.min.js` присутствует.

### 5.6 Вердикт по контракту (итерация 2)

**Critical открытых: НЕТ. High открытых: НЕТ.** Все Medium закрыты. Остаются 5 Low (в т.ч. 1 новый остаточный) — не блокеры. @Builder может переходить к шагу 7.
