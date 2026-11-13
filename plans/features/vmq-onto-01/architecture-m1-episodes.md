# Архитектурный контракт VMQ-M1 — эпизоды и продольный обзор (M-01..M-03)

Дата: 13.11.2026. Основание: `plans/current_task.md` §14 L9351–L9355 и §4; owner source `plans/owner_inputs/2026-11-09-vmq-onto-01.md` §§4.1–4.5, §5.3–5.8. Код проверен через `git show 23477658:<path>`; production baseline по условию — 2.58.198 @ `23477658`, schema 47. Только чтение кода; production/схема не исследовались этим решением и не изменялись.

## Существенная сверка исходных фактов

В предоставленном Orchestrator факт-пакете указано, что `services/memory_episodes.py` и `services/mca_episodes.py` отсутствуют. Однако прямой `git ls-tree -r --name-only 23477658 services` и `git show 23477658:services/mca_episodes.py` показывают, что **`services/mca_episodes.py` присутствует** и содержит `EpisodeService`, стабильную сегментацию, `segment_key`, хранение `message_keys_json`, временные границы и provenance. На том же срезе есть `services/mca_episode_jobs.py`, `services/episode_diagnostics.py`, `services/memory_contracts.py`, `services/graphrag_provenance.py`; `services/memory_episodes.py` действительно не найден. Это расхождение не препятствует архитектурному решению: не создавать конкурирующий episode engine и не дублировать уже существующую физическую схему. Builder должен сверить точный integration candidate и production schema migration ledger до записи. Если срез Orchestrator имел в виду другую ветку/репозиторий, это расхождение разрешить до начала write.

## Решение и модель данных

**Рекомендация: M1 — расширить/завершить существующий bounded episode pipeline `mca_episodes` и существующий longitudinal/coverage контракт без нового хранилища. Никакая новая DDL/migration для M1 не обоснована текущими фактами.** На 23477658 уже есть episode/story таблицы в schema migrations (v21+), `mca_episodes` содержит episode identity, chat scope, event_start/end, participants, `message_keys_json`, `segment_key`, extraction version/status; `mca_episode_jobs` реализует resumable keyset backfill. Поэтому требование persistent episodes выполнено существующим storage design — новая таблица или повторная миграция создала бы дублирующую истину. Схема production baseline 47 не меняется.

Если проверка целевого кандидата опровергнет наличие/полноту этих таблиц, Builder не вводит миграцию автоматически: остановиться и вернуть точную недостающую персистентную информацию, которую невозможно выразить существующим контрактом, как архитектурное уточнение. Только доказанное отсутствие обязательной durable информации (stable episode/source refs, source revision/fingerprint или per-subject coverage/version) может обосновать **аддитивные nullable/indexed поля/таблицу** через уже используемый migration runner. Никакого destructive rewrite; никакой миграции на основании одной лишь разницы названия `memory_episodes`.

### Episode/period

- Episode — bounded, chat-scoped связный разговорный эпизод, а не произвольная тематическая коллекция и не долговременный факт. Состав источников фиксируется стабильными message refs в текущем `smart_messages`; источники не копируются в новую таблицу. `EpisodeView` следует существующему контракту: стабильный scoped `episode_ref`, `chat_id`, `event_start/end` только из timestamp исходных сообщений, canonical participant IDs, topic refs только если они существуют, ordered source refs, extraction/source fingerprint, derived version и честные quality/completeness flags. Summary/title/claims производные, не доказательство.
- Границы: сортировка `(timestamp, stable message key)`; детерминированная временная близость плюс существующие reply-связи/авторы; reply может связать сообщения лишь в ограниченном horizon. Явная Reply-цепочка может преодолеть обычный gap только в пределах этого horizon. Без reply связь одного общего участника не склеивает разновременные годы. Мягкий gap допустим лишь по текущему сегментатору и не должен объединять параллельные разговоры разных участников; неполные timestamps дают partial/unknown, не выдуманную дату. Стабильная тематическая линия/period grouping — отдельный view поверх нескольких independent episodes; общая тема сама по себе не сливает эпизоды.
- Period — query/coverage bucket по фиксированным календарным границам, выбранным из существующих timestamps (год/интервал), исключительно для отчёта coverage и выбора/сопоставления эпизодов. Это не сущность, не новое событие и не доказательство; год unknown остаётся unknown, timezone/calendar normalization берётся из существующего time contract. Нельзя присваивать событию дату обнаружения или делать вывод о свойствах субъекта из количества сообщений.
- Provenance только через существующие source refs/evidence relations и `graphrag_provenance`/`memory_contracts`. Episode references are lineage, не добавочный supporting root. Quote/forward, bot output, один повторяющийся мем или пересказ не превращаются в независимую подтверждённую опору. Counterexamples и contradictions сохраняются по ссылкам, не сливаются с supporting evidence.
- Subject longitudinal view — вычисляемая/существующая versioned projection в текущих dossier/episode/story механизмах: scoped canonical subject, coverage (earliest/latest, periods present/missing, episode refs), recurrence/temporal change и support/counterexample episode refs. Это обзор evidence и полноты, не биография и не источник фактов. Не дублировать весь текст сообщений/фактов; хранить refs и минимальные derived claims там, где существующий формат уже предусматривает.

## Rebuild, IDs, revisions и инкрементальная обработка

Использовать существующие `mca_episodes` сегментацию и resumable `mca_episode_jobs`/`task_jobs` (если присутствуют на целевом candidate), с keyset cursor по `(timestamp,id)`, bounded batch, single-writer и per-chat coalescing. Обработка новых/изменённых/удалённых источников использует существующие message revisions/source fingerprint и recheck/stale mechanism. Курсор двигается лишь после атомарно зафиксированного результата batch; retry/restart идемпотентен.

Episode ID — текущий стабильный scoped ID, производимый существующим natural key/segment identity; сохранить его при повторной обработке тех же source refs. Если состав источников меняется, не переписывать историю под старой версией как будто ничего не было: сохранять source/extraction revision и инвалидировать/пересобирать производный view; при source deletion/revision исходная связь удалённого/изменённого текста не выдаётся как актуальная. Не менять вручную заданные поля/overrides. Rebuild выполняется выбранными chat/subject/time ranges и bounded job; полный архивный проход не запускается автоматически при старте или deployment. Backfill текущих лет/активных участников может быть отдельной ограниченной resumeable job по исходному контракту, но не должен требовать полной генерации embeddings или LLM на каждое сообщение.

Приём M-03: incremental update по новым source revisions и explicit bounded rebuild должны давать одинаковую projection для одного и того же набора source revisions; повтор job не создаёт дубликаты/переезжающие IDs и не продвигает watermark через незавершённую порцию. Ошибка модели/источника/квоты — `paused`/partial/stale с кодом причины; не объявлять completed/coverage-complete ложно.

## Границы реализации и параллельность

**Предпочтительный Builder write scope:**
- `services/mca_episodes.py` — только необходимое улучшение существующей сегментации/episode lineage/rebuild;
- `services/mca_episode_jobs.py` — если требуется устранить доказанную ошибку курсора/идемпотентности/backfill;
- существующие `services/memory_contracts.py` типы только если для longitudinal view нужен недостающий логический контракт; запрет на параллельный enum/API;
- существующие database/repository files **только** если проверка кандидата доказала отсутствие требуемого persistent поля/индекса; не входит в default scope и подлежит отдельному serialized ownership;
- узкие episode/rebuild tests и, только при необходимости, `plans/features/vmq-onto-01/evidence/vmq-m1/` для candidate-bound доказательств.

Исключить `services/mca_retrieval_context.py`: NEXT-02 final candidate строится в другом worktree и может менять этот общий retrieval файл. M1 не интегрирует новый retrieval механизм и не трогает метрику/порог NEXT-02. M1 должен выдавать episode/source refs через существующий интерфейс; потребление в unified retrieve — M2 после объединения. Если M1-кодовый diff всё-таки требует `mca_retrieval_context.py`, сериализовать строго после завершения и интеграции NEXT-02 candidate; не cherry-pick/перезаписывать параллельные изменения. Тестовые/архитектурные чтения файлов параллельно допустимы.

| Область | Класс |
|---|---|
| `mca_episodes.py` и связанные episode tests | `SERIALIZE` внутри M1, один writer |
| `mca_episode_jobs.py` | `SERIALIZE` с M1 core, если изменяется durable cursor/job contract |
| `services/database.py` / migration ledger | `SERIALIZE`; только при доказанном schema gap |
| `mca_retrieval_context.py` / NEXT-02 worktree | `BLOCKED_BY:NEXT-02 integration` для любых записей; предпочтительно не входит в M1 |
| ONTO-A/B typed meaning | M1 logic `PARALLEL_SAFE`; для semantic topic refs consume only after ONTO contract is available; M1 может хранить/выдавать существующие topic refs без него |
| M2 unified retrieval | M1 output contract prerequisite; M1 не зависит от M2 |

## Инварианты, деградация и откат

1. Строгий `chat_id` scope; участники canonical IDs, но profile одного пользователя автоматически не сливается между чатами.
2. Episode границы подтверждаются Reply/time/participant evidence; тематическое сходство не «склеивает» историю. При недостаточном source или спорных границах — split/uncertain/partial, не ложное объединение.
3. `event_start/end` от source time; `discovered_at` отдельный. Unknown time/outcome/theme остаётся unknown.
4. Существующая memory/retrieval/direct behavior сохраняется: ошибка или отсутствие episode view не блокирует legacy facts, FTS/vector и обычный ответ. Никакого изменения настроек, prompt, порогов/порядка каналов или NEXT-02 metric.
5. Legacy episodes/stories без source refs остаются видимыми только через прежний путь как legacy/weak/partial; не реконструировать отсутствующие связи по одному совпадению текста и не переписывать старые rows. Стабильные старые IDs остаются.
6. Нет embeddings write: episode boundary/coverage/rebuild использует существующие source rows/refs. Запретить новые вызовы embedding provider, upsert vector, generation switch, index rebuild и full message rewrite в M1. Test spy/assertion на provider/vector write API = ноль вызовов для всех M1 jobs.
7. Транзакции короткие и per-batch через существующий single-writer; durable cursor после commit. Failure не стирает active projection/предыдущие истории; stale revisions не показываются как актуальные.
8. Schema rollback: default no schema delta, значит rollback только code/job to prior reviewed commit; episode rows остаются прежними и readable. Если separate approved evidence proves additive DDL necessary, migration must be nullable/additive, idempotent, old-code cold-compatible, backup-verified, and rollback must be forward-compatible (old code ignores fields); do not DROP/DELETE schema or source rows in rollback. DDL не запускать в production в рамках этой архитектурной выдачи.

## Проверки и acceptance M-01..M-03

Builder добавляет/использует meaningful assertions на exact candidate:

- **M-01 — episode boundaries + source verification:** один последовательный Reply thread объединяется при корректном horizon; disconnected соседние сообщения разделяются по gap/parallel participants; reply вне horizon не склеивает; message overlap в batch не дублируется; missing parent/invalid timestamps даёт partial/unknown; другой chat ID никогда не попадает. Выход содержит ordered source message refs, event time и участников из исходных рядов. Evidence: тестовые входы + exact episode IDs/source key lists и сравнение с fixture source rows.
- **M-02 — periods/themes, coverage across years, support/counterexamples:** несколько независимых эпизодов по разным годам остаются отдельными, но входят в общую scoped thematic/subject view только через существующие topic/entity/evidence refs; coverage показывает годы/периоды реально представленные и пропущенные; supporting и counterexample refs отличимы; повтор одного source root/мем не повышает independent evidence; старое событие не получает дату discovery. Evidence: deterministic fixture across years + expected coverage matrix and source-lineage check; никакого synthetic claim о реальном архиве.
- **M-03 — incremental/versioned/rebuildable:** incremental source delta, edit/delete/stale invalidation, retry/restart и повторный rebuild дают ожидаемые stable IDs/revisions; сравнение результатов incremental vs bounded rebuild на одинаковой source snapshot; watermark не перепрыгивает paused batch; persisted manual override не затирается. Evidence: before/after source fingerprints, episode refs/version, idempotency counts, job cursor/status.
- **No mass reembedding:** patch/static call graph + mocked/spy embedding interfaces asserts zero embed/upsert/rebuild calls; schema/migration diff confirms no DDL in default implementation; count/fingerprint invariants on test copy. Никаких live/production probes в рамках Builder acceptance.
- **Provenance/backward compatibility:** настоящие `memory_contracts`/`graphrag_provenance` semantics используются: weak/unknown legacy rows читаемы, но не verified; duplicate/quoted/bot outputs не становятся независимым source; prior retrieval consumer/readers сохраняют прежнюю форму и поведение при отсутствии episodes.
- **Security/performance:** per-chat negative case; SQL/keyset batch bounded, no OFFSET full-archive loops; test budget asserts max batch and finite work per call; logs/events/exception strings exclude message bodies, source text, token/API credentials, and unbounded payloads. Чувствительный source content передаётся только существующим authorized source refs.

| Requirement | После Builder можно поставить `REVIEW`, когда | Остаётся не доказанным этим срезом |
|---|---|---|
| M-01 | candidate-bound boundary/reply/participant/time fixtures, source-ref verification, chat isolation и негативные случаи пройдены; тесты/refs/trace приложены | фактическое поведение retrieval-to-Writer принадлежит M2; естественный production эпизод не нужен для unit proof, если source clause не устанавливает обязательное live событие |
| M-02 | multi-year fixture подтверждает независимость эпизодов, scoped topic/period coverage, genuine gaps, support/counterexamples и отсутствие ложной достоверности | широкое покрытие всего production архива/качество реальных тематических историй не объявлять по фикстуре; живой coverage — future evidence только если исходная строка требует это, internal agent-owned |
| M-03 | candidate-bound idempotent incremental/rebuild/edit/delete/restart tests, revision/watermark proof, no embeddings writes и legacy compatibility | долгосрочная production работа scheduler/естественные изменения после окна не выдумывать; если договор требует наблюдать позднее — оставить точные IDs pending/READY_FOR_LIVE по stage-correct policy |

Builder handoff REVIEW не равен независимому Approved/VERIFIED: Reviewer проверяет точный diff и жизнеспособность assertions, выполняет отдельный falsification case (например, reply вне горизонта либо edit/delete при повторном backfill), после чего evidence связывается с конкретным candidate. Изменение карты требований не входит в архитектурный/Builder write scope по данному заданию.

## Зависимости и рекомендуемый порядок

- M1 **не зависит от M2**: сначала создает/reuses episode and longitudinal source-ref contracts; затем M2 потребляет их через существующий unified retrieval. M1 не реализует второй retrieval и не меняет запрос NEXT-02.
- M1 не должен блокироваться наличием ONTO-A/B. Существующие `memory_contracts.py` и episode table уже несут canonical user/topic/event/fact и source contracts; topic refs optional/unknown до ONTO. Для значения typed relations — reuse existing contract/provenance; если проектная интеграция ONTO ещё не влита, не создавать дубликаты и не делать M1 зависимым от нового semantic module.
- При подтверждённой доступности отдельной writer линии, рекомендуемый порядок: **(0) зафиксировать NEXT-02 candidate без совместных файлов; (1) M1 core на `mca_episodes.py`/`mca_episode_jobs.py` с no-overlap; (2) ONTO-A/B contract can be integrated independently; (3) M2 объединяет episode/semantic refs через единственный retrieve после готовности обязательных inputs; (4) VMQ-MEM/MEM metrics after M2**. Если ONTO-A/B уже принято как общий типовой контракт, M1 использует его, но dependency остаётся API-level, не на физическое завершение O-строк.

Риск R1 (локальный data lifecycle/batch semantics), потенциально R2 только если подтверждённая целевая схема реально не содержит необходимых persistent refs/versions. Внешних источников нет: выводы основаны на repository code и owner spec.

## Точное задание Builder

**Цель:** закрыть M-01..M-03 через существующий `services/mca_episodes.py` episode/story storage и `mca_episode_jobs.py` resumable batch lifecycle; обеспечить bounded conversation segmentation, multi-year scoped episode/subject coverage с provenance refs, устойчивые IDs и инкрементальный rebuild.

**Write scope:** в первую очередь `services/mca_episodes.py`, `services/mca_episode_jobs.py`, их узкие tests. Использовать `services/memory_contracts.py`, `services/graphrag_provenance.py` без переписывания владельцев. `services/database.py`/DDL — только после доказанной отсутствующей обязательной персистентности, с остановкой и точным контрактным обоснованием; не изменять `services/mca_retrieval_context.py` (NEXT-02 параллельная работа).

**Запрещено:** новый episode store/engine, дубль `mca_episodes`, новый агент/LLM или вызов модели на каждое сообщение, embedding/upsert/rebuild/reindex, массовый ingest/rewrite, изменение settings/prompts, semantic keyword hardcode, retrieval/NEXT-02 metric changes, cross-chat merges, UI/production/deploy.

**Тесты/acceptance:** все перечисленные M-01..M-03 boundary/provenance/rebuild/legacy/no-embedding-write/no-secrets/bounded performance checks; existing relevant episode tests; candidate-bound evidence with test command/output, refs/fingerprints, diff/schema audit and explicit candidate. Никакого production action.

**Расхождение для разрешения до Builder write:** факт-пакет Orchestrator об отсутствии `mca_episodes.py` против наблюдаемого `23477658` source tree, где этот файл и persistence/job implementation существуют. Сверить фактическую целевую integration ветку; в случае же расхождения по схеме доказать, что в ней отсутствует, прежде чем предлагать DDL.

ARCH_M1_READY
