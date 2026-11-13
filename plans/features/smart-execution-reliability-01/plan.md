# SMART-EXECUTION-RELIABILITY-01 — план, карта требований и граф срезов

- Источник: `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md` (дословная копия
  `plans/current_task.md`, строки 11750–13308, этапы A–M). `current_task.md` не изменялся.
- Карта: `requirements-map.json` (`openworkflow-coverage-v1`, `strict_evidence: true`,
  `slice_graph_path: slice-graph.json`).
- Граф: `slice-graph.json` (`openworkflow-slices-v1`, 13 срезов).
- Статус планирования: карта построена, все требования `PENDING`, реализация не начиналась.
- Gate: `requirements_gate.py check --stage plan` → `stage=plan inventory=509 manual=359 scoped=0 errors=0`.

## 1. Базовая точка и обязательное ограничение

| Параметр | Значение |
|---|---|
| Production | `2.58.199` |
| Deployed commit | `d20a7f730715ba9e9cba7673c0557794979be339` |
| Ветка релиза | `release/2.58.199` |
| Схема БД | 47 |
| Identity | `verified_deployed` |
| Journal | доступ восстановлен (service user в systemd-journal), self-diag corrective выкачен |

Базовая evidence уже собрана DevOps в этой же папке (read-only, 2026-11-14):
`production-recon-2026-11-14.md` и `evidence/production-recon-2026-11-14/*` (identity, effective
configuration по трём чатам, trace чекапа, причина SafeFetch, I2, I4). S0 поэтому не повторяет
recon, а проверяет/нормализует его и закрывает явно отмеченные пробелы (см. §8).

Владелец требует **до любых изменений** подтвердить актуальный deployed SHA и effective
configuration production (SXR-1-02, срез S0). 2.58.199 — отправная точка, а не доказательство
текущего состояния.

### 1.1. Обнаруженное расхождение линий Git (для Orchestrator/DevOps, не исправляется этим планом)

При подготовке карты зафиксировано: локальный `master` (`e439cfd6`) **не является потомком**
deployed-коммита `d20a7f73` (расхождение: 1446 коммитов в одну сторону, 376 — в другую).
На `master` отсутствуют `services/source_reader.py` и `services/deploy_identity.py`, то есть код
SELF-DIAG/deployed-линии. Это означает:

- реализация эпика должна вестись от `release/2.58.199` (deployed-линия), а не от `master`;
- перед стартом Builder нужен явный выбор рабочей ветки/воркtree с подтверждённой базой;
- карта и план не переписывают `progress_scope.json` и не «лечат» расхождение линий; это задача
  Orchestrator (lineage reconciliation), а не PM-маппинга.

DevOps recon 2026-11-14 независимо подтвердил то же расхождение (`377 / 1446`, merge-base
`3193b657`) и зафиксировал, что production дерево чистое, manifest совпадает с HEAD, сервис
здоров. То есть это не артефакт локального checkout, а реальное состояние линий Git.

## 2. Классификация архитектуры

`ARCHITECT_REQUIRED` — но **только как фиксация контракта**, без нового проектирования и без
новых Human Gate (M2: «Architect фиксирует конечный контракт»).

Контракт уже зафиксирован Architect в двух документах этой же папки:

- `architecture-contract-part1.md` — карта ограничителей с точными `file:line`, контракты
  budgets OFF, единого tool-loop, evidence delivery (C) и finalization (G), scopes/acceptance;
  статус `SMART_PART1_READY`.
- `architecture-contract-part2.md` — capacity (D), local-first (E), GitHub/SafeFetcher (F),
  остаток SELF-DIAG (H), локализация I1–I6, границы J/K, L/M; статус `SMART_PART2_READY`.

Триггеры (все закрыты этими документами):
- единый контракт исполнения инструментов across `tool_loop` / `tool_router` / `SourceReader` /
  context composer / evidence window (этапы B–C);
- контракт `model_capacity` для всех LLM-потребителей (этап D, окно vs бюджет);
- контракт двухфазной финализации исследования (этап G);
- контракт deploy identity / manifest и его потребителей (этап H4).

### 2.1. Согласование плана с контрактом Architect

- `direct_execution.py`: часть 1 относит снятие cap (steps/tokens/metered) к этапу B, часть 2
  сериализует файл как S4→S7. Решение PM: **S2 (B) — первый писатель**, S4 (D) — второй
  (capacity-проводка), S7 (G) — третий. Это сохраняет владельца приёмки B и порядок M1 (B до D).
  Следствие: S4 зависит от S2, волны сдвигаются (см. §5).
- C: в write_scope S3 добавлены `services/evidence_bundle.py` и `services/response_extent.py`
  (evidence serialization/composer boundaries из части 1).
- I6: локализация KNN/correction — `services/summary_memory.py` и `services/direct_chat_service.py`
  (часть 2), write_scope S11 приведён к этому.
- H: уже выкаченные в 2.58.199 journal/manifest/identity исправления **не переимплементируются**;
  S8 доказывает только остаток H1–H5.
- A: S1 владеет каноническим predicate (`budget_gate` + settings resolver); каждый потребитель
  (S2, S3, S4, S5) подключает свои внутренние ворота к этому predicate в своём файле. Сквозная
  проверка «ни один env/legacy/внутренний лимит не включает enforcement при OFF» — L1 в S12.

Что переиспользуется без изменений архитектуры: `budget_gate`, существующая иерархия
chat → global → factory, `worker_budget`, общий `tool_loop`, `SourceReader` +
`LocalSnapshotProvider`, `SafeFetcher`, `model_capacity` (legacy + extended resolver),
`checkup_service`/`DiagnosticCollector`/`diagnostic_policy`, `mca_events`/`mca_experience`/
`mca_incidents`, `summary_memory`, `tools/release_manifest.py`.

Владелец прямо запрещает: второй tool-loop, второй SourceReader, нового диагностического агента,
новый LLM-клиент, новую систему бюджетов, новый контекстный resolver, дополнительный индекс кода,
новую БД журналов, новые fallback-хранилища, отдельный тестовый завод, новые стадии согласования
(K2). Эти запреты заведены как обязательные требования SXR-K2-01 и проверяются в S12.

## 3. Инвентаризация требований

| Этап | Требований | ID |
|---|---|---|
| 0. Поручение и результат | 4 | SXR-0-01…04 |
| 1. Production evidence | 2 | SXR-1-01…02 |
| A. Контракт OFF + классификация лимитов | 11 | SXR-A1-01…04, A2-01…04, A3-01…03 |
| B. Общий tool-loop | 11 | SXR-B1-01…06, B2-01…02, B3-01, B4-01…02 |
| C. Лимиты инструментов и evidence | 7 | SXR-C1-01…03, C2-01…02, C3-01…02 |
| D. Контекстное окно модели | 10 | SXR-D1-01…03, D2-01…02, D3-01…02, D4-01, D5-01, D6-01 |
| E. Local-first собственный код | 4 | SXR-E1-01…E4-01 |
| F. GitHub через SafeFetcher | 4 | SXR-F1-01…F4-01 |
| G. Финализация исследования | 5 | SXR-G1-01…G5-01 |
| H. SELF-DIAG | 6 | SXR-H1-01…H5-01 |
| I. Production-дефекты | 13 | SXR-I0-01, I1-01…I2-02, I3-01…I3-02, I4-01…I4-02, I5-01, I6-01…I6-02, I7-01 |
| J. Запрет хардкода намерений | 3 | SXR-J-01…03 |
| K. Права/настройки/scope | 3 | SXR-K1-01…K3-01 |
| L. Приёмка L1–L8 | 8 | SXR-L1-01…L8-01 |
| M. Порядок и DoD | 8 | SXR-M1-01, M2-01…04, M3-01, M4-01…02 |
| **Итого** | **99** | |

Как читать карту:

- 509 извлечённых строк источника классифицированы: 469 `required`, 40 `duplicate`/`context`
  с конкретной причиной (находки «как есть» из §1.2 и сводные инварианты — они ссылаются на
  канонические req_id, а не теряются).
- 359 прозаических обязательств (без bullet-разметки: «не считать master-тумблер доказательством»,
  «при effective OFF…», «Не требовать от владельца…», условия M4 и т.п.) добавлены в
  `additional_requirements` с точной строкой, sha256 строки и префиксом текста — проверяются
  строгим режимом gate.
- Несколько строк могут питать одно требование (это разрешено контрактом карты), но каждое
  требование имеет владельца-срез, наблюдаемую приёмку и live-классификацию.

Сводные инварианты (строки 1555–1566) намеренно помечены `duplicate` с указанием канонических
требований: это итоговая формулировка уже разложенных обязательств, а не новые 12 требований.

## 4. Срезы

| Срез | Этапы | Владелец | Зависит от | Режим | Риск |
|---|---|---|---|---|---|
| S0-BASELINE | 0, 1 | DevOps (read-only) + Architect + PM | — | read-only | R0 |
| S1-BUDGET-MASTER | A | Builder + Reviewer | S0 | writer | R2 |
| S2-TOOL-LOOP | B | Builder + Reviewer | S1 | writer | R2 |
| S3-EVIDENCE | C | Builder + Reviewer | S1, S2 | writer | R2 |
| S4-CAPACITY | D | Builder + Reviewer | S1, S2 | writer | R2 |
| S5-LOCAL-FIRST | E | Builder + Reviewer + DevOps | S3 | writer | R2 |
| S6-GITHUB | F | Builder + DevOps + Reviewer | S5 | writer | R3 |
| S7-FINALIZE | G | Builder + Reviewer | S2, S4 | writer | R2 |
| S8-SELFDIAG | H | Builder + DevOps + Reviewer | S3, S5, S7 | writer | R2 |
| S9-EVENT-PIPELINE | I1, I2, I4 | Builder + Reviewer | S0 | writer | R2 |
| S10-LEARNING-INCIDENTS | I3, I5 | Builder + Reviewer | S0 | writer | R1 |
| S11-MEMORY-CORRECTION | I6, I7 | Builder + Reviewer | S4 | writer | R2 |
| S12-ACCEPT | J, K, L, M | Reviewer + DevOps + Orchestrator | S1…S11 | reviewer + release evidence | R3 |

Точные `write_scope` — в `slice-graph.json`. Ключевые решения:

- **A и B разделены**, потому что контракт OFF (кто включает enforcement) и механика цикла
  (сколько раундов/вызовов) имеют разные наблюдаемые приёмки; при этом B зависит от A, так как
  раунды/вызовы допустимы только как бюджет при effective ON.
- **C после B**: единая политика исполнения (B) фиксируется раньше, чем правятся per-tool caps и
  сериализация результатов; иначе evidence-window настраивается под старую семантику.
- **E после C, F после E**: все три среза пишут `services/source_reader.py`; это осознанный
  последовательный join, а не выдуманная бизнес-зависимость. Диагностика GitHub (F2, read-only)
  может начинаться раньше — как evidence внутри S0.
- **I разделён на три среза**: журнал/поток/коды (общий `mca_events` и event pipeline),
  обучение/инциденты, память/correction frame. Разные модули, разные причины, независимая проверка.
- **J/K/L/M в одном приёмочном срезе**: это вердикт по кандидату и релизу, а не параллельная
  разработка; дробление дало бы несколько «зелёных» вердиктов по константам.

## 5. Волны и параллельность

```
wave0: S0 (read-only baseline+contract) | S9 | S10          — 3 lane (1 read-only)
wave1: S1 (после S0)                                        — + S9/S10 продолжаются
wave2: S2 (единый писатель tool_loop/direct_execution)
wave3: S3 (evidence) | S4 (capacity, после S2)
wave4: S5 (после S3) | S7 (после S2+S4) | S11 (после S4)
wave5: S6 (после S5) | S8 (после S3+S5+S7)
wave6: S12 — независимая приёмка, единый релиз, production smoke
```

Критический путь: S0 → S1 → S2 → S3 → S5 → S6 → S12 (7 шагов). S4 идёт параллельно с S3,
S7/S11 — на следующей волне, S9/S10 — с wave0.

Файлы, которые обязаны сериализоваться (в `slice-graph.json` → `serialized_files`):
`config/settings.py` (S1→S4), `services/tool_loop.py` и `services/tool_result.py` (S2→S7),
`services/tool_router.py` (только S2), `services/direct_execution.py` (S2→S4→S7),
`services/source_reader.py` (S3→S5→S6), `services/evidence_bundle.py` и
`services/response_extent.py` (только S3), `services/direct_chat_service.py` (S4→S11),
`services/summary_memory.py` (только S11), `services/deploy_identity.py` (S5→S8).

Отдельного общего cache/index/telemetry не создаётся; тестовые швы — существующие.

## 6. Модель приёмки и evidence

### 6.1. Что доказывается на каждом этапе

- `plan` — эта карта и граф (пройдено, errors=0).
- `review` — независимый Reviewer на точном кандидате по каждому срезу: реализация, валидность
  тестов (assertions на наблюдаемое поведение), самостоятельная фальсификация исходного дефекта.
- `deploy` — перед выкатом: candidate-bound approvals + implementation evidence по всем
  обязательным строкам объединённого кандидата и подтверждённая dependency closure.
- `release` — после выката: реальные production-наблюдения (L1–L8), deployed SHA.
- Никаких `REVIEW`/`VERIFIED` заранее: все 99 строк `PENDING`.

### 6.2. Post-deploy (агент-исполняемые, не owner)

`live_required=true`, `live_when=postdeploy`: SXR-H3-01, SXR-H4-01, SXR-I1-01, SXR-I2-01,
SXR-K3-01, SXR-L1-01…L8-01 (13 строк). Это проверки, которые физически имеют смысл только на
работающем production: effective-конфигурация, реальный сетевой запрос, реальный журнал,
реальный чекап, реальные записи журнала мемов и курсор потока.

До релиза они остаются `PENDING`; после релиза либо получают production-evidence и становятся
`VERIFIED`, либо остаются честно неподтверждёнными. Это не «ожидание владельца».

### 6.3. Отложенные owner_live_checks

Согласно M4 и правилу проекта «Owner is not mandatory QA»: отложенные owner-наблюдения
регистрируются отдельно, не блокируют DONE и не заявляются выполненными. Обязательная техническая
проверка не может быть превращена в owner-чек. В этой карте **нет** обязательных owner-проверок:
все проверки L1–L8 и I1–I6 выполнимы агентом (есть SSH/HTTP-доступ, БД, журнал, harness).

### 6.4. Evidence (M3)

Для основных сценариев требуется связанный trace: исходный запрос, request/correlation ID,
effective settings, provider/model, context capacity + источник значения, фактическое число
раундов и вызовов, результаты инструментов, причина завершения, фактический финальный payload,
финальный ответ, deployed SHA. Секреты, приватные данные и chain-of-thought не публикуются.

Evidence-артефакты складываются в `plans/features/smart-execution-reliability-01/evidence/<slice>/`
(durable, repo-relative), временные прогоны — только через `workflow_housekeeping.py`.

## 7. Как проверяется каждый этап (кратко)

- **A**: effective OFF на production для чатов из логов + отсутствие обходов master + карта
  лимитов с категориями (искусственный / физический / безопасность / бизнес).
- **B**: контрольный сценарий >4 раундов, >6 вызовов, >2 корректных вызова в одном раунде, при
  этом все вызовы получают результат; metered не блокирует локальные операции.
- **C**: evidence больше прежних лимитов доходит до финального payload; хвост источника не
  потерян; при реальном окне — корректная упаковка без фиктивного «полного прочтения».
- **D**: 8 сценариев ёмкости (GLM 5.3 Flash через NanoGPT, <1M, >1M, неизвестный ID, смена
  основной модели, fallback, недоступный каталог, context exceeded); 1M не выдаётся за
  подтверждённую ёмкость. Recon уже доказал расхождение: чат-путь берёт 16 384
  (`unknown_fallback`), расширенный resolver того же ID даёт 1 048 576 / 32 768
  (`provider_catalog`, verified) — S4 обязан свести все потребители к одному пути, а не
  «убрать warning».
- **E**: реальный read-only запрос по собственному коду; несовпадающий checkout не выдаётся за
  production.
- **F**: реальное сетевое чтение публичного репозитория + отдельный отказ запрещённому адресу
  (SSRF сохранён). Причина уже доказана: единичный снимок DNS `["140.82.114.5"]` против
  фактического peer `140.82.112.6` при ротации A-записей GitHub; S6 исправляет peer
  bookkeeping/transport, не ослабляя anti-rebinding.
- **G**: 7 вариантов исследования/финализации; во всех применимых сохраняются данные, заглушка
  не публикуется.
- **H**: реальный «чекап» + естественное продолжение независимыми формулировками; журнал и
  manifest согласованы; unknown не превращается в ноль.
- **I**: по каждому I1–I6 — причина, участок, исправление, проверка, инварианты.
- **J/K/L/M**: независимые формулировки, отрицательные сценарии безопасности, единый релиз и DoD.

## 8. Риски и внешние неизвестные

1. ~~`EXT-NANOGPT-CATALOG`~~ — **снят recon'ом**: каталог доступен и по точному ID даёт
   1 048 576 / 32 768 (verified). Остаточный риск: точное сопоставление ID/alias и обновление
   кэша после смены модели; выдуманная запись по-прежнему запрещена.
2. ~~`EXT-GITHUB-NET`~~ — **причина доказана** (устаревший единичный DNS-снимок vs фактический
   peer). Остаточный риск: исправление peer bookkeeping не должно ослабить anti-rebinding;
   нужен повторный production-прогон в разное время (интермиттирующий отказ).
3. `EXT-JOURNAL-PERM` — доступ к journald зависит от unit; проверка в окружении процесса
   (recon подтвердил `sudo -u adminbot journalctl` rc=0, InvocationID совпадает).
4. Расхождение Git-линий (см. §1.1) — блокирует старт реализации до выбора базы.
5. `master`-ветка не содержит deployed-кода: любые локальные «уже исправлено» проверки на
   `master` недействительны для приёмки.
6. I1: точное SQLite-исключение не залогировано (код пишет только имя класса); судьба
   конкретных spooled-строк не доказана. S9 обязан сначала добавить структурированную запись
   исключения/operation/table и доказать отсутствие потерь при дренаже.
7. I4: кроме двух кодов владельца в проде видны другие unmapped-маркеры; их producer-строки не
   декодированы — фиксируются как наблюдение, без выдумывания кодов и без «универсального» кода.
8. I2: backlog 2 059 418 строк после курсора при `SEMANTIC_PER_CHAT_MAX=50` и чтении «самых
   старых» строк; исправление не должно быть перемоткой курсора или повышением threshold.

## 9. Предлагаемая запись в progress_scope (выполняет только Orchestrator)

- Раздел `SMART-EXECUTION-RELIABILITY-01` + этапы A–M классифицируются как `mapped` →
  задача `smart-execution-reliability-01`, карта
  `plans/features/smart-execution-reliability-01/requirements-map.json`.
- Готовый машинный delta (точные `id`, `sha256`, `requirement_refs` по 99 req_id) лежит в
  `source-inventory-proposal.json` (14 разделов, посчитан тем же алгоритмом, что и
  `workflow_progress.py`; сверен на существующем разделе WEB-SEARCH-QUALITY-01 — совпадение id и sha).
- `owner_inputs` OI-2026-11-14-SMART-EXEC-RELIABILITY получает `coverage_refs`:
  `{"task_id": "smart-execution-reliability-01", "map": "plans/features/smart-execution-reliability-01/requirements-map.json", "req_ids": [<см. §10>]}`.
- Задача уже стоит в очереди: position 1, P0, `blocked_by: []`, `execution_state: awaiting_architecture`.
  После фиксации контракта Architect — снять `awaiting_architecture` и разрешить wave0 (S0/S9/S10).
- Отдельно: инструмент фиксирует drift раздела `VISION-CONTEXT-UNIFY-01` и два stale owner_inputs
  (`OI-2026-11-12-EXIT-CORRECTIVE-CYCLE`). Они не относятся к этому эпику и не правятся здесь.

## 10. Полный список req_id для coverage_refs

SXR-0-01, SXR-0-02, SXR-0-03, SXR-0-04, SXR-1-01, SXR-1-02,
SXR-A1-01, SXR-A1-02, SXR-A1-03, SXR-A1-04, SXR-A2-01, SXR-A2-02, SXR-A2-03, SXR-A2-04,
SXR-A3-01, SXR-A3-02, SXR-A3-03,
SXR-B1-01, SXR-B1-02, SXR-B1-03, SXR-B1-04, SXR-B1-05, SXR-B1-06, SXR-B2-01, SXR-B2-02,
SXR-B3-01, SXR-B4-01, SXR-B4-02,
SXR-C1-01, SXR-C1-02, SXR-C1-03, SXR-C2-01, SXR-C2-02, SXR-C3-01, SXR-C3-02,
SXR-D1-01, SXR-D1-02, SXR-D1-03, SXR-D2-01, SXR-D2-02, SXR-D3-01, SXR-D3-02, SXR-D4-01,
SXR-D5-01, SXR-D6-01,
SXR-E1-01, SXR-E2-01, SXR-E3-01, SXR-E4-01,
SXR-F1-01, SXR-F2-01, SXR-F3-01, SXR-F4-01,
SXR-G1-01, SXR-G2-01, SXR-G3-01, SXR-G4-01, SXR-G5-01,
SXR-H1-01, SXR-H1-02, SXR-H2-01, SXR-H3-01, SXR-H4-01, SXR-H5-01,
SXR-I0-01, SXR-I1-01, SXR-I1-02, SXR-I2-01, SXR-I2-02, SXR-I3-01, SXR-I3-02, SXR-I4-01,
SXR-I4-02, SXR-I5-01, SXR-I6-01, SXR-I6-02, SXR-I7-01,
SXR-J-01, SXR-J-02, SXR-J-03,
SXR-K1-01, SXR-K2-01, SXR-K3-01,
SXR-L1-01, SXR-L2-01, SXR-L3-01, SXR-L4-01, SXR-L5-01, SXR-L6-01, SXR-L7-01, SXR-L8-01,
SXR-M1-01, SXR-M2-01, SXR-M2-02, SXR-M2-03, SXR-M2-04, SXR-M3-01, SXR-M4-01, SXR-M4-02.
