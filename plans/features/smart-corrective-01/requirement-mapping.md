# SMART-CORRECTIVE-01 — сопоставление требований с SMART и SELF-DIAG

Дата: 2026-11-14. Автор: PM. Статус: планирование, реализации нет.

Источник: `plans/owner_inputs/2026-11-14-smart-corrective-01.md` (sha256 `8A0239B3…52AE71`, 934 строки).
Карта: `plans/features/smart-corrective-01/requirements-map.json`.
Родительские карты: `plans/features/smart-execution-reliability-01/requirements-map.json`, `requirements-map-fc-amendment.json`, `plans/features/self-diag-01/requirements-map.json`.

Правило этого документа: **не переписывать и не ослаблять прежние доказательства**. Если production-поведение противоречит уже VERIFIED строке, это фиксируется как дефект и повод перепроверить достаточность прежнего доказательства, но статус родительской строки здесь не меняется.

## 1. Сводка классификации

| Класс | Что это значит | Направления |
|---|---|---|
| **Регрессия** | Требование уже было сформулировано и даже помечено VERIFIED, но deployed-код/поведение ему не соответствует | 4 |
| **Недореализованное требование** | Общий контракт существует, но конкретный потребитель/ветка его не применяет | 5 |
| **Новое уточнение** | Прежние требования не покрывали наблюдаемое поведение или необходимый контракт | 5 направлений + W-01…W-11 |
| **Полностью новое** | Дефект не описан ни в SMART, ни в SELF-DIAG | 1 (watchdog A–F) |
| **Плановое/процессное** | Очередь, артефакты, порядок работ | 2 |

Ключевой вывод: это **не новый SMART-эпик**. Четыре подтверждённых дефекта — прямые противоречия уже принятым требованиям (`SXR-C1-01`, `SXR-E4-01`, `SXR-A3-01`, `SXR-C3-02`). Ещё пять — недореализация общего контракта у конкретного потребителя. Watchdog A–F — единственное направление, которого раньше не было в требованиях; внутри него W-01…W-11 — new clarification, W-12 — investigation, W-13 — не дефект, W-14 — backlog.

## 2. По пунктам corrective

### 2.1. Чекап не довёл самостоятельное исследование до результата (§1, §6)

| Поле | Содержание |
|---|---|
| Наблюдение | 14.11.2026 «чекап» обнаружил шесть активных `watchdog.jobs` ERROR-инцидентов, но завершился без анализа реализации; второй запрос владельца дал содержательный разбор `services/mca_watchdog.py`. |
| Существующие требования | `SXR-H1-01` (чекап автоматически исследует собственную реализацию при необходимости анализа кода), `SXR-B4-01` (шесть условий завершения tool-loop), `SXR-G4-01` (деградировавшее завершение даёт содержательный ответ по доступным данным), `SD1-COR-03` (стандартный чекап исполняет существующий tool-loop, модель сама решает, что читать), `SD1-EVD-01`. |
| Классификация | **Недореализованное требование**: tool-loop завершается корректно, но `CheckupService` принимает `str(loop_result)` как достаточный результат и не различает «модель остановилась» и «исследование существенной проблемы завершено». |
| Что перепроверить | `SXR-H1-01`, `SXR-B4-01`, `SXR-G4-01`, `SD1-COR-03`, `SD1-EVD-01`; evidence `evidence/h/pytest-checkup.txt`, `evidence/h/binding-h-d238f808.md`, `evidence/accept-final/binding-s12-final-b204c66c.md`; production-факт 14.11.2026. |
| Дополнительная приёмка | `AC-01`…`AC-04`, `SC-CMP-TOOLOOP`, `SC-CMP-NOTPROOF`, `SC-CMP-SERVICE`, `SC-CMP-EARLY`, `SC-CMP-DONE-01..04`, `SC-CMP-PARTIAL`, `SC-CMP-CONT-01..06`, `SC-CMP-EXEC`, `SC-CMP-NOREGRESS`, `SC-CMP-NOLOOP`, `SC-CMP-BALANCE`, `SC-REP-ESSENCE`, `SC-REP-CAUSE`, `SC-REP-NOFOLLOWUP`. |
| Где новое | Требование к **состоянию исследования** («существенная проблема → исследование не завершено, пока не выполнено одно из четырёх условий») и запрет принимать первый текстовый вывод после нерелевантного результата. В SMART это было общим свойством tool-loop, но не проверялось на потребителе-чекапе. |

### 2.2. Разрыв fallback в `_locate_in_tree()` (§3.1)

| Поле | Содержание |
|---|---|
| Наблюдение | В 2.58.200 `_maybe_switch_to_remote()` есть, но `_locate_in_tree()` при `tree_unavailable`, `no_path_match` и ряде отказов возвращает `not_found` локального провайдера, не переключаясь на GitHub. |
| Существующие требования | `SXR-E4-01` (порядок источников: локальный → иной локальный snapshot → GitHub по deployed ref → честный partial), `SXR-F4-01` (live-сценарии GitHub), `SD1-D4-07` (чтение собственного кода от локальной копии, затем commit-pinned GitHub), `SD1-AC-03` (source_reader реально читает файл/строки, неуспех обозначается), `SXR-E3-01`. |
| Классификация | **Регрессия** против `SXR-E4-01` и `SD1-D4-07`: наличие переключения в `_fetch_one()` не означает его наличия во всём маршруте. |
| Что перепроверить | `SXR-E4-01`, `SXR-E3-01`, `SD1-D4-07`, `SD1-AC-03`, `SXR-F4-01`; review `evidence/review-e-18fa4d59.md`, `evidence/review-i1-76d60678.md`, `evidence/review-s12-*`; production-факт «файл отдал только харнесс-скрипт деплоя». |
| Дополнительная приёмка | `AC-05`…`AC-08`, `SC-SRC-FIND-01..03`, `SC-SRC-PATH`, `SC-SRC-FB-01..06`, `SC-SRC-FB-NOTFOUND/NOPOINTLESS/NOBYPASS`, `SC-SRC-CLASS-01..06`, `SC-SRC-CLASS-RESULT`, `SC-SRC-GEN-ROUTES/CONSUMERS/NOSECOND/NOCYCLE/EXISTING`, `SC-REP-GH-UNCONF`. |
| Где новое | Требование покрыть fallback-ом **каждый** этап `repo identity → source selection → discovery → locator → verified read → continuation`, а не отдельные ветки; явная таксономия «достоверное отсутствие / неуспешный поиск / неполный результат / недоступность источника / нет прав / ограничение провайдера». |

### 2.3. Локатор ищет по именам, а не по содержимому; top-3 — потолок (§4)

| Поле | Содержание |
|---|---|
| Наблюдение | `_MAX_LOCATOR_PATHS = 3`; `_locate_in_tree()` перебирает `ranked[:3]`; `rank_paths()` опирается на имена/пути/язык. `watchdog.jobs` находится внутри `services/mca_watchdog.py`, но не является именем файла. |
| Существующие требования | `SXR-C1-01` (потолки SourceReader 6/2/16 и defaults 3/1/8 не ограничивают чтение при OFF), `SXR-A2-01` (искусственные потолки при OFF не применяются), `SXR-C2-01` (аналогичные потолки инструментов), `SXR-C3-01` (7 шагов прохождения результата), `SD1-D4-01` (`read_source_code` развивается, а не заменяется). |
| Классификация | **Регрессия** против `SXR-C1-01`/`SXR-A2-01`: фиксированный срез сохраняется независимо от `budgets OFF`. Плюс **новое уточнение**: прежние требования не описывали поиск по содержимому и классы найденных материалов. |
| Что перепроверить | `SXR-C1-01`, `SXR-A2-01`, `SXR-C2-01`, `SXR-C3-01`, `SD1-D4-01`; evidence `evidence/s3`/`binding-*` и `evidence/review-*`, focused-тест `tests/test_smart_c1_source_reader_limits.py`; live-строки `SXR-L1-01`, `SXR-L2-01`. |
| Дополнительная приёмка | `AC-02`, `AC-03`, `AC-09`, `AC-12`, `SC-SEARCH-FIND-01..03`, `SC-SEARCH-FIND-CAP`, `SC-SEARCH-CONTENT`, `SC-SEARCH-CAP-01..07`, `SC-SEARCH-TOOL`, `SC-SEARCH-MODEL`, `SC-SEARCH-ACTUAL`, `SC-SEARCH-NOMAP`, `SC-SEARCH-NOHARDCODE`, `SC-SEARCH-KIND-01..08`, `SC-SEARCH-NOEXCLUDE`, `SC-SEARCH-VERIFY`, `SC-SEARCH-REFINE`, `SC-SEARCH-PAGE`, `SC-SEARCH-REMOVE-TOP3`, `SC-SEARCH-NONEWTOP`, `SC-SEARCH-CHUNK`, `SC-SEARCH-NOINDEX`. |
| Где новое | Универсальный поиск по содержимому доступной ревизии (точные вхождения, символы, event/process/error ids, config keys, traceback, импорты) с проверкой вхождений и идентичностью источника; классы «реализация / вызывающий код / тест / документация / план / миграция / скрипт деплоя / упоминание»; запрет заменять top-3 на другую константу. |

### 2.4. Effective budget policy не доходит до вложенного SourceReader (§5.1)

| Поле | Содержание |
|---|---|
| Наблюдение | `SourceReader.run()` принимает `chat_id` и `budget_enforced`; `ToolRouter._read_source_code()` в 2.58.200 не передаёт их, поэтому вложенный SourceReader определяет политику без контекста чата. |
| Существующие требования | `SXR-A3-01` (пройден фактический путь enforcement), `SXR-D4-01` (один resolver для всех LLM-вызовов), `SXR-A1-01` (при OFF контекст/инструменты/evidence не ограничиваются), `SXR-B2-01` (единая политика для Direct, L1, последовательных раундов, checkup, inspect_runtime, SourceReader…). |
| Классификация | **Регрессия** против `SXR-A3-01`/`SXR-B2-01`: путь enforcement проверялся, но вложенная передача контекста в `reader.run()` выпала. |
| Что перепроверить | `SXR-A1-01`, `SXR-A3-01`, `SXR-B2-01`, `SXR-D4-01`; evidence `evidence/binding-*`, `evidence/review-*`, `tests/test_budget_unlimited_round1019.py`, `tests/test_tool_router.py`; live-строка `SXR-L1-01`. |
| Дополнительная приёмка | `AC-11`, `AC-12`, `SC-BUD-FIND-01..03`, `SC-BUD-FIX`, `SC-BUD-RESOLVER`, `SC-BUD-NOSECOND`, `SC-BUD-SCOPE-01..06`, `SC-BUD-CONTEXT`, `SC-BUD-NOCROSS`, `SC-BUD-NOIMPLICIT`, `SC-BUD-RELATED`, `SC-BUD-OFF-01..06`, `SC-BUD-NOTINF`, `SC-BUD-SAFETY`, `SC-BUD-GUARD`, `SC-BUD-PROGRESS`, `SC-BUD-PARTIAL`, `SC-SEARCH-OFF`. |
| Где новое | Явное требование: при известной области исполнения отсутствие `chat_id` не подменяется безусловным ON/OFF; политика вложенного инструмента соответствует контексту задачи; технический предохранитель не маскируется под бюджет. |

### 2.5. Вход чекапа теряет факты (§7)

| Поле | Содержание |
|---|---|
| Наблюдение | `limits.checkup_max_input_symbols`, фиксированная обрезка memory metrics (2 000), обрезка текста по символам (12 000), отдельная настройка объёма ответа. Метрики идут первыми, логи режутся до остатка; хвост отбрасывается без учёта содержания. |
| Существующие требования | `SXR-C3-02` (устранены искусственные потери в символьных caps, включая `max_input_symbols`/`max_symbols`), `SXR-D5-01` (при OFF доступно полное окно без скрытых секционных caps), `SXR-H1-01`, `SXR-C2-01`. |
| Классификация | **Регрессия** против `SXR-C3-02`/`SXR-D5-01`: общий контракт сформулирован, но `checkup_service.py` продолжает применять старую семантику. Плюс **новое уточнение**: таксономия семи видов ограничений и приоритет фактов при физической нехватке места. |
| Что перепроверить | `SXR-C3-02`, `SXR-D5-01`, `SXR-H1-01`; evidence `evidence/caps/*`, `evidence/fc-resources/*`, `tests/test_checkup_service.py`; live-строка `SXR-L2-01`. |
| Дополнительная приёмка | `AC-14`, `SC-INP-FIND-01..04`, `SC-INP-CHECK`, `SC-INP-NOLOSS`, `SC-INP-TAX-01..07`, `SC-INP-REPORT`, `SC-INP-LOGWINDOW`, `SC-INP-CHUNKLOSS`, `SC-INP-FIX`, `SC-INP-OFF`, `SC-INP-CAPACITY`, `SC-INP-PRIORITY`, `SC-INP-TAIL`, `SC-INP-NOCONST`, `SC-INP-NOFULL`, `SC-INP-SETTINGS`, `SC-INP-NORESET`. |
| Где новое | Разделение «окно наблюдения журналов / полнота данных / ёмкость модели / операторский бюджет / размер порции / объём отчёта / ограничение канала»; запрет отбрасывать хвост без анализа содержания; сохранение семантики настроек владельца. |

### 2.6. Промпт чекапа: доставка, жанр, устаревшие инструкции (§8)

| Поле | Содержание |
|---|---|
| Наблюдение | Владелец вручную заменил `prompts.checkup_system_prompt`; нужно установить, что применяется именно его редакция, а не заводская/реестровая/обрезанная. В active-контуре есть `CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM`; требуется согласовать его с новым поведением инструментов. |
| Существующие требования | `SD1-D6-03` (промпт сохраняется байт-в-байт), `SD1-D6-04` (жанр подтверждается живыми ответами), `SD1-D6-05` (телеметрия `prompt_version_used/hash`), `SD1-AC-09` (effective bytes/hash до/после релиза), `SD1-EVD-02`, `SD1-D6-17/18`, `SXR-K3-01` (сохранённые промпты не перезаписаны). |
| Классификация | **Новое уточнение** к частично покрытому контракту: прежние требования гарантировали сохранность и телеметрию, но не проверяли фактическую доставку на маршруте чекапа и согласованность addendum с новым поведением инструментов. |
| Что перепроверить | `SD1-D6-03`, `SD1-D6-04`, `SD1-D6-05`, `SD1-AC-09`, `SD1-EVD-02`, `SXR-K3-01`; `services/checkup_service.py` (сборка system), `services/checkup_prompts.py`, `prompt_registry.py`; телеметрия production-чекапа 14.11.2026 (если сохранилась). |
| Дополнительная приёмка | `AC-15`…`AC-19`, `SC-PRM-OWNER`, `SC-PRM-GENRE`, `SC-PRM-PRESERVE`, `SC-PRM-SCOPE`, `SC-PRM-NOTHIRD`, `SC-PRM-VERSION`, `SC-PRM-CHECK-01..12`, `SC-PRM-TELEMETRY`, `SC-PRM-NOTPROOF`, `SC-PRM-LAYER-01..04`, `SC-PRM-NOCORE2/NOMATRIX/NOEXPR2/NOFLATTEN`, `SC-PRM-MATSET/NOWORDS/NOSUPPRESS`, `SC-PRM-SEM-01..07`, `SC-PRM-CLEANLOG/BOTH/NOACTIVEFALSE/NOSOFT/NOINVENT`, `SC-PRM-STALE-01..04`, `SC-PRM-ADD-CHECK`, `SC-PRM-ADD-01..05`, `SC-PRM-ADD-NODUP/NOEXTRA`. |
| Где новое | Проверка **фактической доставки** (резолв глобальных/чатовых значений, provenance, реестр, подстановка, порядок блоков, effective Core/Expression в ЛС, payload, tool-loop/fallback-запросы, обрезка инструкций, cleanup/Style Policy/publication guard) и требование согласовать addendum с новым поведением; удаление устаревшего Betterstack только из активного контура без переписывания истории. |

### 2.7. Watchdog A–F (§9) — полностью новое направление, W-01…W-14

Read-only расследование `investigation/watchdog-code-analysis.md` + `watchdog-probe-results.json` превратило §9 в конкретные находки. W-ids — метки расследования, не текст владельца; каждая строка привязана к §9.2 A–F и AC-20…AC-24.

| W | Находка | Владельческий якорь | Существующие требования | Классификация | Карта |
|---|---|---|---|---|---|
| W-01 | takeover эмитится в цикле, `job_ids` молча отбрасывается `build_event`, per-job доказательств нет | §9.2 C (633/637), AC-21 | `SXR-M3-01` (trace), `SXR-I4-01` (реестр событий), `SD1-D6-17` (аналитика) — частично | **new clarification** (контракт события/доказательств не был описан) | `SC-WD-W01` |
| W-02 | `takeover_recovered` уходит после неудачного `recover_stale` или без store | §9.2 D (643/647/649), AC-20 | `SXR-G4-01` (честность деградации), `SXR-M3-01` — частично | **new clarification** (recovery truth) | `SC-WD-W02` |
| W-03 | `recover_stale` только снимает lease, не возвращает job в работу | §9.2 D (645), AC-20/22 | `SXR-B4-01` (завершение), `SXR-I5-01` — не покрывает | **new clarification** (recovery semantics) | `SC-WD-W03` |
| W-04 | vision-watchdog глобально забирает чужие running-job и молча terminated | §9.2 A (611/613), AC-22 | `SXR-I2-01`, `SXR-I5-01` — частично (event pipeline) | **new clarification** (owner/kind scope) | `SC-WD-W04` |
| W-05 | resolved-инцидент молча переоткрывается; `resolve()` без production-вызова; нет связи с job | §9.2 F (661–665), AC-23 | `SD1-D3-02` (состояния), `SXR-I5-01`, `SXR-M3-01` — частично | **new clarification** (incident lifecycle) | `SC-WD-W05` |
| W-06 | часть durable-running job не обновляет heartbeat; stale 60 с ложно срабатывает | §9.2 A/B (611/623), AC-22 | нет прямого | **new clarification** (heartbeat contract) | `SC-WD-W06` |
| W-07 | терминальные записи без `fencing_token` воскрешают задачу после takeover | §9.2 F (665), AC-20/22 | `SXR-I5-01`, `SD1-D3-02` — частично | **new clarification** (fencing) | `SC-WD-W07` |
| W-08 | `progress_at` не ставится в `mark_running`; пороги только для llm/video/archive; heartbeat-only job невидим | §9.2 B (621–629), AC-22 | нет прямого | **new clarification** (progress contract) | `SC-WD-W08` |
| W-09 | queued-сироты без claimer/deadline не видны; `next_retry_at` нужно отличать | §9.2 A (613–617), AC-22 | нет прямого | **new clarification** (queued policy) | `SC-WD-W09` |
| W-10 | `_track_incident` глотает ошибки; счётчик считает update как new | §9.2 E (653–657), AC-24 | `SXR-G5-01` (structured errors), `SD1-D6-17` — частично | **new clarification** (observability without recursion) | `SC-WD-W10` |
| W-11 | fingerprint без `kind`, title от первого job, `jobs_json` ≤20 | §9.2 F (661/663), AC-23 | `SD1-D6-17`, `SXR-M3-01` — частично | **new clarification** (identity/fingerprint) | `SC-WD-W11` |
| W-12 | причина каждого из шести инцидентов требует production-данных §4 | §9.1 (582), AC-23 | нет прямого | **required investigation / NEEDS_PRODUCTION_DATA** | `SC-WD-W12` |
| W-13 | проверенный requeue/`next_retry_at` — не дефект | §9.2 A (617) | — | **NOT_A_DEFECT** | context с reason |
| W-14 | `TaskJobStore.prune`, шум `WATCHDOG_SWEEP`, глобальный recover каждые 5 с | §9.2 A/F | — | **BACKLOG_ONLY** | context с reason + `plans/backlog.md` |

**Порядок, который подтвердит Architect:** W-05 (lifecycle/reconciliation, включая авто-закрытие по фактическому состоянию job) должен войти **раньше** W-11 (fingerprint/REASON_CODES). Иначе старые активные инциденты останутся без миграционной сверки, а новый fingerprint split сделает их несовместимыми с историей. W-02/W-05/W-07 идут в S5a, W-01/W-11 — в S5c после lifecycle, W-03/W-04/W-06/W-08/W-09 — в S5b, W-10 — в S5d. Architect предложил имена `S5-W01_EVENT_IDENTITY`…; PM привязал те же смыслы к стабильным `SC-WD-W01`…`SC-WD-W12` (suggestions only, PM owns map IDs).

**Что это меняет в прежней оценке:** watchdog остаётся единственным полностью новым направлением, но теперь это не «A–F вообще», а 12 обязательных W-строк с file:line, acceptance и expected evidence. `W-13` не является дефектом и не должен попасть в реализацию; `W-14` не входит в приёмку и лежит в backlog.

### 2.8. Пересечения, очередь и сохраняемые контракты (§10)

| Поле | Содержание |
|---|---|
| Наблюдение | Нужно открыть актуальные источники планирования, проверить свежесть и commit identity, сопоставить с будущими эпиками, не запуская их и не переставляя очередь. |
| Существующие требования | `SXR-0-01`…`SXR-0-04` (один эпик, без конкурирующих), `SXR-M1-01`/`M2-01` (порядок и контракт), `SXR-K2-01` (без вторых механизмов), `SD1-SEM-01/03` (без keyword-routing), `SD1-GRAL-02` (без второго промпта/Writer). |
| Классификация | **Плановое/процессное**; новых инженерных требований нет, но corrective обязан иметь собственный queue-overlap и contract freeze. |
| Что перепроверить | `SXR-0-01..04`, `SXR-K2-01`, `SD1-SEM-01/03`, `SD1-GRAL-02`; `plans/progress_scope.json`, `plans/current_task.md`, `plans/workflow_state.md`, карты fc-trust/web-search/memory/vmq/speech. |
| Дополнительная приёмка | `SC-OVL-*`, `SC-OVL-FC-SEM`, `SC-OVL-FC-CONTEXT`, `SC-OVL-FC-NOCLARIFY`, `SC-OVL-NOCMD/TRIGGER/NOKEYWORD/NOMEM`, `SC-OVL-DEPTH`, `SC-ACC-REG-01/02/SCOPE`. |
| Где новое | Анализ пересечений с очередью и правило «общий дефект чинится сейчас, будущая функциональность не реализуется досрочно». |

### 2.9. Реализация, ревью, деплой и артефакты (§12–§13)

| Поле | Содержание |
|---|---|
| Существующие требования | Действующий workflow проекта, `SXR-M4-01` (эпик закрывается после ревью/релиза/smoke), `SXR-M2-02/03/04` (роли Builder/Reviewer/Orchestrator), правила PET_PROJECT и stage-correct acceptance. |
| Классификация | **Плановое/процессное**, без нового продуктового контракта. |
| Что перепроверить | `SXR-M2-02..04`, `SXR-M4-01`, release-evidence 2.58.200 (identity, health, effective config, rollback). |
| Дополнительная приёмка | `SC-IMPL-*`, `SC-ART-01..11`, `SC-ART-NOTDONE`, `SC-ACC-MAIN`, `SC-ACC-METHOD`, `SC-COR-DELIVERY`, `SC-COR-NOTVERIFIED`, `SC-COR-STAGES`. |

## 3. Что это меняет в родительских картах

1. **Статусы не меняются.** Ни одна родительская строка не переводится в FAILED/PENDING этой картой. Противоречие фиксируется как новое corrective-требование и как вопрос к Reviewer: достаточно ли было прежнее evidence.
2. **Прежние доказательства не переписываются.** Release-evidence 2.58.200, review-артефакты и bindings остаются как есть. Исправленный релиз получит собственные candidate-bound артефакты.
3. **24 live-строки родителя** разбираются отдельно в `parent-live-rows-reconciliation.md`; часть из них придётся перепроверить на corrective-релизе, часть можно закрывать на 2.58.200.
4. **Новые требования не дублируют родительские.** Там, где поведение уже описано, corrective-строка формулирует наблюдаемое производственное доказательство и место разрыва, а не копирует текст SMART.

## 4. Итог для Orchestrator

- Уже покрыто SMART/SELF-DIAG: порядок источников, local-first identity, GitHub fallback, единый resolver, OFF-семантика, сохранность промпта, отсутствие второго SourceReader/tool-loop/промпта, запрет keyword-routing.
- Требует перепроверки и, вероятно, признания недостаточным прежнего evidence: `SXR-C1-01`, `SXR-E4-01`, `SXR-A3-01`, `SXR-C3-02`, `SXR-B4-01`, `SXR-H1-01`, `SD1-D4-07`, `SD1-AC-03`, `SD1-D6-03/04/05`.
- Реально новое: content-search и классы результатов; сквозная передача policy во вложенный инструмент; состояние завершённости исследования у чекапа; таксономия входных ограничений; проверка фактической доставки промпта и addendum; **watchdog W-01…W-12**.
- W-13 (`requeue`/`next_retry_at`) — **не дефект**, в реализацию не входит. W-14 (prune/sweep noise/глобальный recover) — **BACKLOG_ONLY**, запись в `plans/backlog.md`, вне приёмки.
- Порядок watchdog: W-05 lifecycle/reconciliation **до** W-11 fingerprint/REASON_CODES; W-01/W-02/W-10 (события) до W-05; W-03/W-04/W-06/W-08/W-09 (recovery) после lifecycle.
