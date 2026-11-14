# SMART-CORRECTIVE-01 — пересечения с очередью эпиков

Дата: 2026-11-14. Источник очереди: `plans/progress_scope.json` (актуальный рабочий файл, не master-копия). Позиция corrective: **2**, priority **P0**, `blocked_by: []`, `execution_state: awaiting_pm_mapping`.

Этот документ **не запускает** перечисленные эпики, **не меняет** их статусы, содержание и порядок. Он фиксирует: что corrective обязан починить сейчас в существующем контуре, а что остаётся будущей функциональностью.

## 1. Очередь на момент планирования (релевантный срез)

| Поз. | ID | P | Статус / состояние | Пересечение с corrective |
|---:|---|---|---|---|
| 1 | `smart-execution-reliability-01` | P0 | acceptance_in_progress; 2.58.200, 162/186 mandatory VERIFIED, 24 live | Родитель. Corrective продолжает его контур; его evidence не переписывается |
| 2 | `smart-corrective-01` | P0 | awaiting_pm_mapping (эта карта) | Текущая задача |
| 3 | `p0-init-meme-ux-diag` | P0 | VERIFIED / completed | Нет |
| 4 | `self-diag-01` | P0 | queued; corrective 13.11, core/identity Approved | Прямое: журнал, identity, prompt delivery, incident lifecycle, observability |
| 5 | `vmq-onto-01` | P0 | queued; два approved кандидата ждут release handoff | Нет (память/QRNG не трогаем) |
| 6 | `mod-acl-ux-01` | P0 | queued | Нет |
| 7 | `fc-trust-01` | P0 | awaiting_dependency (`vmq-onto-01`, `self-diag-01`) | Косвенное: общий tool-loop/factcheck-контур, но эпик не запускается |
| 8 | `web-search-quality-01` | P0 | awaiting_dependency (`fc-trust-01`) | Косвенное: поиск по внешним источникам ≠ поиск по коду; не поглощается |
| 9 | `pvr-fc-corrective-01` | P1 | awaiting_dependency (`unified-reply`) | Косвенное: общий фактчек-путь |
| 10 | `behavior-gates-simplification-01` | P1 | awaiting_dependency | Нет |
| 11 | `soul-1` | P1 | release_pending | Косвенное: Core/Expression/Style Policy — только сохранение контракта |
| 12–16 | `asap8-v6.3`, `add-exp`, `p0-nostalgia-rework`, `p0-admin-cache-toggle-save`, `release-then-migrate` | P1 | paused/release_pending | Нет |
| 17–20 | `asap5-multimodal`, `meme-pipeline-refactor-01`, `evol`, `reply-context-integrity-rci` | P2/P3 | paused/amendment | Косвенное: общий tool-loop и контекст, но corrective их не заменяет |
| 21 | `epic-memory-cognitive-02` | P2 | paused_with_progress | Прямое ограничение: память/embedding/БД не менять |
| 22 | `smart-module-semantic-routing-p0` | P2 | paused_with_progress | Прямое: семантика намерения, запрет keyword-routing |
| 23 | `factcheck-clean-publication` | P2 | paused_with_branch | Косвенное: style/publication guard |
| 24 | `EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108` | P2 | awaiting_architecture | Нет |
| 30 | `remove-legacy-rephrasing-01` | P3 | paused_with_progress | Прямое ограничение: не добавлять второй речевой слой/перефразирование |
| 32 | `asap-speech-arch` | P3 | paused_with_progress | Прямое ограничение: единая архитектура речи |
| 35 | `p0-factcheck-speech` | P3 | paused_with_progress | Косвенное: голос/фактчек не трогаем |
| 36 | `p0-factcheck-media` | P3 | queued | Косвенное: медиа-контекст не трогаем |
| 40 | `evol-reply-context-integrity-01` | P2 | paused_with_branch | Косвенное: reply-контекст сохраняется |
| 41 | `vision-context-unify-01` | P3 | queued | Нет |
| 42 | `unified-reply` | P0 | queued; inspector step 3 | Косвенное: общий tool-loop; не пересекаться писателями |

Полный список — в `plans/progress_scope.json`; срез выше покрывает все направления, названные владельцем в §10.2, и ближайшие общие контуры.

## 2. Что чинится сейчас, в существующем контуре

1. **SourceReader**: fallback на всех этапах, поиск по содержимому, классы результатов, порционная выдача, отсутствие top-N-потолка. Это общий дефект существующего инструмента, поэтому чинится сейчас, а не в будущем поисковом эпике.
2. **ToolRouter / budget policy**: передача `chat_id` и `budget_enforced` во вложенный `SourceReader`; один действующий resolver; OFF-семантика. Это общий контракт SMART, а не функциональность будущего эпика.
3. **Tool-loop / CheckupService**: различение «модель остановилась» и «существенное исследование завершено», частичный результат с причиной. Общий механизм не должен деградировать обычные диалоги.
4. **Checkup input**: таксономия ограничений, приоритет существенных фактов, сохранение настроек.
5. **Checkup prompt**: фактическая доставка сохранённой редакции, согласование addendum, удаление устаревшего Betterstack из активного контура.
6. **Watchdog A–F**: корректность recovery-событий, queued/running-зависания, lifecycle инцидентов. Это не будущая функциональность, а исправление уже случившихся production-инцидентов.

## 3. Что остаётся будущим эпикам (corrective не реализует)

| Направление | Что НЕ делает corrective | Почему |
|---|---|---|
| `fc-trust-01` | Не меняет доверие к фактчеку, не вводит новые правила доверия/ранжирования утверждений | Отдельный эпик, ожидает `vmq-onto-01` + `self-diag-01` |
| `web-search-quality-01` | Не строит новый поисковый каскад, не меняет провайдеров веб-поиска, не вводит качество внешних результатов | Отдельный эпик, ожидает `fc-trust-01` |
| `vision-context-unify-01` | Не унифицирует vision/контекст | Отдельный эпик, не начат |
| `epic-memory-cognitive-02`, `vmq-onto-01` | Не меняет память, embedding pipeline, KNN, граф знаний, квантовый рандом | Явный запрет §10.3 |
| `asap-speech-arch`, `remove-legacy-rephrasing-01`, `p0-factcheck-speech` | Не создаёт вторую Personality Core/Expression, не добавляет перефразирование, не меняет речевые настройки | Сохраняется действующая архитектура речи |
| `unified-reply`, `evol-reply-context-integrity-01`, `pvr-fc-corrective-01`, `factcheck-clean-publication` | Не переписывает reply-контекст, публикацию и фактчек-контракты | Только регрессионная проверка затронутых путей |
| `mod-acl-ux-01`, `menu-01` | Не меняет ACL/UI | Нет пересечения |
| `smart-module-semantic-routing-p0` | Не добавляет новых команд/триггеров/keyword-routing | Сохраняется LLM-определение намерения |

## 4. Совместное использование файлов и писатели

| Файл | Кто пишет в corrective | Конфликтующие активные задачи | Решение |
|---|---|---|---|
| `services/source_reader.py` | S2 | Нет активного писателя в очереди | Один writer S2 |
| `services/tool_router.py` | S3 | `unified-reply`/`smart-module-semantic-routing-p0` могут касаться router в будущем | S3 только после S1; не параллелить с их активными lane |
| `services/tool_loop.py` | S4 | `unified-reply` (tool-loop) | S4 не стартует, пока unified-reply имеет живого writer-а на этом файле |
| `services/checkup_service.py` | S4, затем S5, затем S6 | `self-diag-01` (checkup) | Сериализовано зависимостями; при активном self-diag lane — координация через Orchestrator |
| `services/mca_watchdog.py`, `mca_incidents.py`, `task_supervisor.py` | S7 | Нет активного писателя | Один writer S7 |
| `services/checkup_prompts.py`, `prompt_registry.py` | S6 | `epic-prompt-versioning-ux-01` (VERIFIED), speech epics | S6 не меняет сохранённые значения; только active factory/addendum |

Правило: пересечение писателей — временное scheduling-ограничение, а не бизнес-зависимость. Оно не блокирует независимые S2/S3/S7.

## 5. Влияние на очередь

- Новых эпиков не создаётся; `smart-corrective-01` уже стоит позицией 2.
- Позиции и приоритеты остальных задач не меняются.
- `blocked_by` corrective остаётся `[]`: Architect contract — внутренний срез задачи, а не внешняя зависимость; он не блокирует постановку, но блокирует implementation slices.
- Единственное реальное ограничение: пока corrective не завершён, `smart-execution-reliability-01` не может закрыть live-строки, которые зависят от исправленного поведения (см. `parent-live-rows-reconciliation.md`).
