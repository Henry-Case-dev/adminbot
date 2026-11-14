# SMART-CORRECTIVE-01 — план корректирующих работ

Дата: 2026-11-14. Автор: PM. Статус: **планирование завершено, реализация не начата, разрешение на implementation не выдано**.

## 1. Источник и идентичность

| Поле | Значение |
|---|---|
| Источник | `plans/owner_inputs/2026-11-14-smart-corrective-01.md` |
| sha256 | `8a0239b3e307f284b5ddc5cc9faf94725e735def03db384aaaabe6e06952ae71` (934 строки) |
| `plans/current_task.md` | **раздел SMART-CORRECTIVE-01 в файле отсутствует** (проверено 2026-11-14: совпадений `SMART-CORRECTIVE`/`watchdog.jobs` нет). Владелец передал задачу в чате; она сохранена как immutable owner input. `current_task.md` не редактировался |
| Родитель | `smart-execution-reliability-01`, production 2.58.200, deployed `0e4a144db476a1535ae3a2b79a7cce30354ad866` |
| Release evidence | `plans/features/smart-execution-reliability-01/release-evidence/2.58.200/` — не переписывается |
| Очередь | `smart-corrective-01`, position 2, P0, `blocked_by: []`, `execution_state: awaiting_pm_mapping`; очередь не переставлялась |
| Карта | `plans/features/smart-corrective-01/requirements-map.json` (strict_evidence, slice-graph) |
| Гейт | `evidence/gate-plan.txt`: `stage=plan inventory=224 manual=232 scoped=0 errors=0` |

## 2. Что уже сделано read-only

- `investigation/watchdog-code-analysis.md` — W-01…W-14 с `file:line`, классификацией, минимальным фиксом и тестом.
- `investigation/watchdog-probe-results.json` — 10 локальных проб (A–K), sha256 `2C18E609…1EFEDE`.
- `investigation/watchdog_probe_semantics.py` — скрипт проб.
- Вывод: **watchdog-часть §9 расследована**; ни один инцидент не объявлен устранённым; production не затрагивался.
- Расследование двух **чекап**-запусков (§2.1, 17 пунктов) ещё не оформлено как отдельный отчёт: есть `production-recon-2026-11-14/checkup-trace.txt` и журнальные артефакты родителя, но они не покрывают все 17 пунктов. Это остаётся обязательным входом S0 до кодирования.

## 3. Архитектурная классификация

**ARCHITECT_REQUIRED.**

Причины (каждая — реальный общий контракт, а не «сложность»):

1. **SourceReader**: новый контракт поиска по содержимому (запрос, классы результатов, порционная выдача, структурированные отказы), которым пользуются чекап, continue, inspect_runtime и будущие потребители. Нельзя зафиксировать PM-ом.
2. **Budget policy**: сквозная передача `chat_id`/`budget_enforced` во вложенные tool calls и границы «единый resolver / без второго механизма».
3. **Completion semantics**: где заканчивается общий tool-loop и начинается проверка достаточности диагностического исследования; запрет второго agentic pipeline.
4. **Limit taxonomy**: семь видов ограничений, приоритет фактов, совместимость `limits.checkup_max_input_symbols`/`checkup_max_symbols`, сохранение настроек.
5. **Prompt delivery**: фактическая цепочка system payload, реестр, addendum, cleanup/Style Policy; запрет второго речевого слоя.
6. **Watchdog lifecycle**: recovery truth, fencing, fingerprint/REASON_CODES, авто-закрытие инцидентов. Есть state/migration-последовательность; нужен утверждённый порядок.

Не требует Architect: локальные правки констант/текста, чистое переименование, исправление одного теста. Но таких обязательных строк в этой карте нет.

Контракт: `plans/features/smart-corrective-01/architecture-plan.md` (ранний черновик Architect, закрепляет deployed-code seams; PM не подменяет его решения). До финализации контракта Builder не начинает кодирование. Read-only S0/S0-PRODDATA могут идти параллельно.

## 4. Объём карты (двухпроходная инвентаризация)

| Метрика | Значение |
|---|---|
| Строк автоинвентаря | 224 |
| Из них `required` | 156 |
| `context` (заголовки, вводные фразы, цитаты, факты) | 58 |
| `duplicate` (поля §9.1, уже входящие в W-12) | 10 |
| Ручных строк | 232 (228 `required` + 4 `context`: W-13, W-14, две вводные) |
| Всего `required` строк | 384 |
| Всего `context` | 62 |
| Уникальных `req_id` | 367 |
| AC-строк | 24 (`AC-01`…`AC-24`) |
| Срезов | 14 |

Гранулярность: каждый подтверждённый дефект/запрет/AC имеет собственную строку; W-строки не дублируют друг друга (см. §7). Родительские требования не копируются: там, где поведение уже описано, corrective-строка формулирует наблюдаемое доказательство и место разрыва.

## 5. Срезы и dependency graph

Архитектурная нумерация принята по `architecture-plan.md`: S5 — watchdog/incidents с под-срезами S5a–S5d. Checkup input переименован в `S3B-INPUT`, чтобы не занимать S5.

```
S0-INVESTIGATE (read-only)
   ├──> S0-PRODDATA (read-only production data, W-12) ──────────────┐
   └──> S1-CONTRACT (Architect freeze)                              │
           ├──> S2-SOURCEREADER ─┐                                  │
           ├──> S3-BUDGET ───────┤                                  │
           └──> S5A-LIFECYCLE ─> S5B-RECOVERY ─> S5C-EVENTS ─> S5D-OBSERVABILITY
                   │                                                  │
                   └──────────────> S5-WATCHDOG (join) ───────────────┤
                                                                       │
        S4-COMPLETION (после S2+S3) ─> S3B-INPUT ─> S6-PROMPT ───────┤
                                                                       v
                                                             S8-REVIEW-RELEASE
```

| Срез | Зависит от | Write scope | Наблюдаемая приёмка |
|---|---|---|---|
| `S0-INVESTIGATE` | — | `investigation/**` | 17 пунктов §2.1 + разделение фактов/выводов/дефектов/гипотез/невосстановимого; watchdog-часть уже закрыта |
| `S0-PRODDATA` | S0 | `investigation/production/**` | Production-данные §4 для шести инцидентов; W-12 = NEEDS_PRODUCTION_DATA до данных; не блокирует W-01…W-11 |
| `S1-CONTRACT` | S0 | `architecture-plan.md` | Заморожены 6 контрактов из §3; у каждого dependent slice есть интерфейс и запреты §10.3 |
| `S2-SOURCEREADER` | S1 | `services/source_reader.py`, source-reader тесты | `watchdog.jobs` находится в `services/mca_watchdog.py`; поиск идёт за top-3; классы результатов различаются |
| `S3-BUDGET` | S1 | `services/tool_router.py`, `services/worker_budget.py`, `services/tool_schemas.py` (scoped: optional `cursor` for `read_source_code`), budget/tool_router тесты | `chat_id`/`budget_enforced` доходят до `SourceReader`; effective policy = резолвер чата; OFF без скрытых потолков; модель может передать continuation `cursor` |
| `S4-COMPLETION` | S1, S2, S3 | `services/tool_loop.py`, `checkup_service.py`, checkup/tool-loop тесты | После нерелевантного первого результата исследование продолжается; иначе — честный partial с причиной |
| `S3B-INPUT` | S4 | `checkup_service.py`, `settings.py`, `services/diagnostic_collector.py` (scoped: `collect_for_checkup` facts budget call-site), checkup-тесты | Факт за 12 000 символов/квотой метрик доходит до payload; facts-блок следует budget/capacity policy; 7 видов ограничений различимы; настройки не перезаписаны |
| `S6-PROMPT` | S3B | `checkup_prompts.py`, `prompt_registry.py`, `checkup_service.py`, тесты промпта | Effective prompt = сохранённая редакция владельца (hash/bytes); addendum согласован; Betterstack удалён только из active |
| `S5A-LIFECYCLE` | S1 | `mca_incidents.py`, `task_supervisor.py`, incident-тесты | Resolved не переоткрывается без evidence; авто-resolve после терминала; fencing; success-событие только при подтверждённом recovery |
| `S5B-RECOVERY` | S1, S5A | `task_supervisor.py`, `mca_watchdog.py`, `mca_gates.py`, recovery-тесты | Bounded requeue/next_retry_at; owner/kind scope; heartbeat/deadline; queued-сироты и progressless-running различимы |
| `S5C-EVENTS` | S1, S5B | `mca_watchdog.py`, `mca_incidents.py`, `mca_events.py`, тест событий | 3 stale → 3 per-job события (не более одного на job) с identity/truthful outcome; идентичный aggregate не повторяется из-за batch/итерации; fingerprint учитывает kind+job_id; старые строки читаемы |
| `S5D-OBSERVABILITY` | S1, S5C | `mca_watchdog.py`, тест observability | Отказ incident service наблюдаем (log+WARN+счётчик), без рекурсии; created/updated/reopened/failed различаются |
| `S5-WATCHDOG` | S5A…S5D | — (join) | Собирает доказательства под-срезов; ничего не пишет |
| `S8-REVIEW-RELEASE` | все, включая S0-PRODDATA | `evidence/**`, `release-evidence/**` | AC-01…AC-24 на одном deployed SHA; identity, config, canary, rollback |

Параллельность по умолчанию: **3 writer-lane** — `S2`, `S3`, `S5A` (непересекающиеся файлы). `S0-PRODDATA` — read-only. `S4` стартует после S2+S3; `S3B`/`S6` сериализованы из-за `checkup_service.py`; `S5B`→`S5C`→`S5D` сериализованы из-за `task_supervisor.py`/`mca_watchdog.py`.

### S3-BUDGET scope expansion (bookkeeping)

`services/tool_schemas.py` добавлен в write-scope `S3-BUDGET` как раскрытое минимальное расширение:

- изменение ровно одно — опциональное строковое свойство `cursor` для `read_source_code` (тот же паттерн, что у `get_recent_history`/`inspect_runtime`); `required` остаётся `["operation"]`, `additionalProperties` — `false`;
- причина: Router уже принимал и передавал continuation cursor, но строгий провайдер не давал модели передать необъявленный аргумент; без этого контракт продолжения S1 был бы мёртвым;
- файл **не принадлежал ни одному срезу графа**; расширение выдано отдельным указанием, ограничено одним свойством и ревьюируется как часть S3-BUDGET, отдельный срез не создаётся;
- evidence: `plans/features/smart-corrective-01/evidence/s3/implementation.md` (ветка `sc/corrective-s3`, code candidate `163b8ddd567ec60ea8cb3274a37b10e9297bddd7`; в текущем checkout master файл может отсутствовать);
- статусы не менялись: S3-строки остаются `PENDING`, расширение не является доказательством приёмки.

### S3B-INPUT scope expansion (bookkeeping)

`services/diagnostic_collector.py` добавлен в write-scope `S3B-INPUT` как раскрытое минимальное расширение:

- изменение ровно одно — call-site `DiagnosticCollector.collect_for_checkup` передаёт `max_chars` из того же budget/capacity-резолвера, что и остальной чек-ап, вместо искусственного `ProbeLimits.max_facts_chars` (default 3000 символов);
- причина: owner §7 требует не терять полезные facts diagnostics collector при сборке payload; `render_facts_text(max_chars=0)` уже документирует «искусственного бюджета нет»;
- `ProbeLimits`, per-probe caps, `max_output_chars` и окно журнала **не изменялись** и остаются safety/physical слоем; второй packing-логики в коллекторе нет;
- файл **не принадлежал ни одному срезу графа**; расширение выдано отдельным указанием, ограничено call-site и ревьюируется как часть S3B-INPUT, отдельный срез не создаётся;
- evidence: `plans/features/smart-corrective-01/evidence/s3b/implementation.md` (ветка `sc/corrective-s3b`, code candidate `1bbe767d3a060e6b8ab56bbd1ccff1b0f4879977`, base `7c1e1afbc3be4098b260a816ff4c6bf5c68d04aa`; в текущем checkout master файл может отсутствовать);
- статусы не менялись: S3B-строки остаются `PENDING`, расширение не является доказательством приёмки.

### Нумерация

Follow-up просил «S5 sub-slices»; Architect в `architecture-plan.md` закрепил S5 = watchdog/incidents и порядок S5a→S5d. В этой карте принято именно это: `S5A-LIFECYCLE`, `S5B-RECOVERY`, `S5C-EVENTS`, `S5D-OBSERVABILITY`, `S5-WATCHDOG`. Прежний `S5-INPUT` переименован в `S3B-INPUT`, чтобы S5 не обозначал два разных контура.

## 6. Watchdog sub-slices: порядок и baseline-тесты

Порядок из `architecture-plan.md` §7.6, подлежит подтверждению Architect при финализации контракта:

1. **S5A-LIFECYCLE** — W-02 (success только при подтверждённом recovery), W-05 (reconciliation, авто-закрытие, запрет молчаливого reopen), W-07 (fencing терминальных записей). **W-05 обязан войти раньше W-11**: старые активные инциденты должны быть сверены с фактическим состоянием job до изменения fingerprint/REASON_CODES; иначе split сделает историю несовместимой.
2. **S5B-RECOVERY** — W-03 (bounded requeue вместо «снятия lease»), W-04 (owner/kind scope), W-06 (heartbeat/deadline), W-08 (progress_at/пороги/overdue), W-09 (queued-сироты/deadline). После lifecycle, чтобы recovery не закреплял ложную связь инцидент→job.
3. **S5C-EVENTS** — W-01 (по одному событию на фактически затронутый job с identity и truthful outcome; одинаковые aggregate events не повторяются из-за размера stale batch; пустой batch — без события), W-11 (fingerprint с kind+job_id, title/job list, история читаема). После lifecycle, чтобы не расколоть историю инцидентов.
4. **S5D-OBSERVABILITY** — W-10 (наблюдаемость отказа incident service без рекурсии, корректные счётчики).
5. **S0-PRODDATA** — W-12 (production-данные §4). Это **вход расследования, не блокер реализации**: S5a–S5d могут стартовать без них, но финальная атрибуция шести инцидентов и закрытие W-12 без данных невозможны.

**Baseline-тесты, которые сейчас фиксируют дефект как ожидаемый** (на release-checkout, не на master):

- `tests/test_smart_exec_learning_incidents.py:100,129-131` — требуют `resolved_at IS NULL` и роста `repeat_count` без закрытия. При исправлении W-05 эти assert-ы должны быть обновлены **вместе с кодом**; иначе зелёный тест будет противоречить AC-23.
- `tests/test_mca17a_observability_core_round1027.py:667-686` (`test_watchdog_takeover_and_recovery`) — проверяет только `interrupted` и отдельный ручной `recover_job`, но не возврат job в работу после sweep. При W-03 обновить/расширить.
- Baseline до изменений: `16 passed` по watchdog/sweep/incident/recover. Это **не доказательство корректности** — тесты закрепляют текущее поведение.

Постоянные регрессии добавляются в существующие файлы (по колонке «Тест» W-таблицы), а не в новый тестовый завод. `watchdog_probe_semantics.py` — PROVISIONAL-проба, не постоянный тест.

## 7. W-строки и отсутствие дублей

- `SC-WD-W01`…`SC-WD-W12` — 12 обязательных строк, у каждой acceptance и `expected_evidence`.
- `SC-WD-W13` — `context` с reason `NOT_A_DEFECT`: requeue/`next_retry_at` работают штатно.
- `SC-WD-W14` — `context` с reason `BACKLOG_ONLY`: prune/sweep noise/глобальный recover; запись `W-14-WATCHDOG-HYGIENE` добавлена в `plans/backlog.md`.
- Поля §9.1 (10 строк) — `duplicate` к `SC-WD-W12`, а не отдельные требования.
- Запреты §9.3 (`SC-WD-NO-01..07`) и разделение направлений (`SC-WD-SEPARATE`, `SC-WD-NOREPLACE`) остаются отдельными обязательными строками.
- `AC-20`…`AC-24` связаны с W-строками: AC-20 → W-02/W-03/W-07; AC-21 → W-01; AC-22 → W-06/W-08/W-09; AC-23 → W-05/W-11/W-12; AC-24 → W-10.

## 8. Обязательный investigation gate (до Builder)

S0 считается завершённым только когда:

1. Для **обоих** чекап-запусков восстановлены 17 пунктов §2.1 или явно отмечено, что именно невосстановимо (без выдумывания traces).
2. Отдельно перечислены: подтверждённые production-факты, выводы из deployed-исходников, воспроизводимые дефекты, гипотезы, невосстановимые данные.
3. Для watchdog: W-01…W-14 уже оформлены; W-12 отмечен `NEEDS_PRODUCTION_DATA` и не выдан за установленную причину.
4. Нет секретов/приватных промптов в журналах; используются существующие события/корреляция, без новой trace-платформы.
5. Если историческая трасса отсутствует, это не блокирует исправление независимо подтверждённых дефектов кода (W-01…W-11), но блокирует заявления о причине конкретного инцидента.

## 9. Evidence plan по стадиям

| Стадия | Что требуется | Куда |
|---|---|---|
| `plan` | Карта + slice graph + этот план + requirement-mapping + queue-overlap + parent-live reconciliation | `plans/features/smart-corrective-01/` |
| `review` | Candidate-bound implementation evidence и независимое ревью по каждому срезу; обновлённые baseline-тесты; negative/failure-сценарии | `evidence/review-*.md`, `evidence/<slice>/` |
| `deploy` | Independent approval каждого обязательного ряда, exact candidate, effective config, rollback | `evidence/gate-deploy.txt` |
| `release` | Deployed SHA = candidate, health, schema, journal, canary results, W-12 data if due | `release-evidence/<version>/` |
| `delivery` | Если останутся только postdeploy-наблюдения (например реальные события recovery), `READY_FOR_LIVE` + approved `postrelease_wait` | `release-evidence/<version>/gate-delivery.txt` |

Никакой ряд не становится VERIFIED этим планом. W-12 может оставаться `NEEDS_PRODUCTION_DATA` до получения данных; это не отменяет реализацию W-01…W-11.

## 10. Feature manifest (компактно)

| Группа требований | Runtime entrypoint | Durable tests | Evidence |
|---|---|---|---|
| `SC-INV-*`, `SC-REP-*`, `SC-WD-W12` | production logs/DB/tool traces (read-only) | — | `investigation/` |
| `SC-SRC-*`, `SC-SEARCH-*` | `services/source_reader.py` | `tests/test_evol_source_reader.py`, `tests/test_smart_c1_source_reader_limits.py`, `tests/test_smart_e_local_first_source.py` | `evidence/s2/` |
| `SC-BUD-*` | `services/tool_router.py`, `services/worker_budget.py`, `services/tool_schemas.py` (optional `cursor` only) | `tests/test_tool_router.py`, `tests/test_budget_unlimited_round1019.py`, `tests/test_tool_schemas.py` | `evidence/s3/` |
| `SC-CMP-*` | `services/tool_loop.py`, `services/checkup_service.py` | `tests/test_checkup_service.py`, `tests/test_checkup_contract.py`, `tests/test_tool_loop.py` | `evidence/s4/` |
| `SC-INP-*` | `services/checkup_service.py`, `services/settings.py`, `services/diagnostic_collector.py` (scoped facts-budget call-site) | `tests/test_checkup_service.py`, `tests/test_smart_corrective_input.py` | `evidence/s5/` |
| `SC-PRM-*` | `services/checkup_prompts.py`, `services/prompt_registry.py`, `services/checkup_service.py` | `tests/test_checkup_prompts.py` | `evidence/s6/` |
| `SC-WD-W02/W05/W07` | `services/mca_incidents.py`, `services/task_supervisor.py` | `tests/test_smart_exec_learning_incidents.py`, `tests/test_smart_corrective_watchdog_lifecycle.py` | `evidence/s5a/` |
| `SC-WD-W03/W04/W06/W08/W09` | `services/task_supervisor.py`, `services/mca_watchdog.py`, `services/mca_gates.py` | `tests/test_mca17a_observability_core_round1027.py`, `tests/test_smart_corrective_watchdog_recovery.py` | `evidence/s5b/` |
| `SC-WD-W01/W11` | `services/mca_watchdog.py`, `services/mca_incidents.py`, `services/mca_events.py` | `tests/test_smart_corrective_watchdog_events.py` | `evidence/s5c/` |
| `SC-WD-W10` | `services/mca_watchdog.py` | `tests/test_smart_corrective_watchdog_observability.py` | `evidence/s5d/` |
| `SC-WD-W12` | production DB/logs (read-only) | — | `investigation/production/` |
| `SC-WD-NO-*`, `SC-WD-SEPARATE`, `SC-WD-NOREPLACE`, `AC-20..24` | review/release gate | — | `evidence/s8/` |

## 11. Сохраняемые контракты и исключения

Не меняются: `prompts.checkup_system_prompt` (сохранённая редакция владельца), Personality Core, Expression, Style Policy, единый речевой слой, триггер «чекап», семантика короткого «фактчек», LLM-определение намерения, память/embedding/БД/граф знаний/квантовый рандом, существующий SourceReader/tool-loop/бюджетный резолвер.

Не создаются: второй SourceReader, второй tool-loop, второй агент, отдельная trace-платформа, новый векторный индекс, второй речевой движок, новые команды/keyword-routing, shadow-режимы/скрытые флаги, миграции БД.

## 12. Риски

| Риск | Уровень | Митигация |
|---|---|---|
| Content search по локальному дереву окажется медленным/дорогим | R2 | порционная выдача + существующие лимиты CPU/памяти; замер на реальном дереве; без нового индекса |
| Изменение completion semantics затронет обычные диалоги | R2 | S4 только после S2/S3; регрессия Direct/фактчек; запрет второго pipeline |
| W-05 меняет lifecycle инцидентов и влияет на аналитику | R2 | W-05 до W-11; сохранение истории; совместимость `mca_events` |
| Recovery-изменения могут дублировать работу | R3 | bounded attempt/max_attempts, fencing, запрет безусловного takeover; W-12 данные |
| Prompt assembly затронет сохранённую редакцию | R1 | hash/bytes проверка; registry; никаких миграций значения |
| Production-данные W-12 недоступны | R1 | W-12 остаётся NEEDS_PRODUCTION_DATA; W-01…W-11 не блокируются |

## 13. Следующее действие

1. Orchestrator: признать карту и план, обновить `coverage_refs` owner input и admission; очередь не переставлять.
2. Architect: подтвердить/финализировать `architecture-plan.md` §7.6, порядок S5A → S5B → S5C → S5D (W-05 до W-11) и интерфейсы S2/S3/S4/S3B/S6.
3. Параллельно read-only: завершить S0 по двум чекап-запускам; собрать S0-PRODDATA production-данные (W-12) — как вход, не блокер.
4. Только после S1 — Builder на S2/S3/S5A (3 writer-lane).
5. Реализация не авторизована этим документом; parent SMART и `progress_scope.json` не изменялись.

## 14. Housekeeping

Рабочий каталог PM: `C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a\artifact-63948e578b`. После promotion документов и гейта run закрывается `run-close --confirmed-idle --confirmed-evidence --apply`; временные скрипты не попадают в репозиторий. Durable артефакты: карта, slice-graph, этот план, requirement-mapping, queue-overlap, parent-live reconciliation, evidence/gate-plan.txt, investigation W-документы.
