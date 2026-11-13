# VMQ-M1 — инженерия: эпизоды/периоды (M-01..M-03)

Кандидат: `80726249b2e67aff53f803d5434e712d9aa09f7e` (ветка `vmq/m1`).
База: производственный `234776589c934024ed0e8dceba189fb9d70d3215`
(2.58.198, schema 47). Worktree:
`<GLOBAL_CONFIG>/WorkspaceData/worktrees/c742e4de9e92c489/vmq-onto-01-3689dd92710d-4b445a11`.
Контракт: `plans/features/vmq-onto-01/architecture-m1-episodes.md`
(docs-коммит `e92080e9`, на base-линии появляется вместе с интеграцией
docs; код-кандидат от него не зависит).
Owner source: `plans/owner_inputs/2026-11-09-vmq-onto-01.md` §§4.1–4.5,
§5.3–5.8 (через контракт).

Статус: `REVIEW` (Builder). Это не независимое approval и не DONE —
вердикт за Reviewer. Production не затрагивался, деплой не выполнялся.

## 1. Сверка фактов Orchestrator (обязательна до записи)

Проверено на `23477658` (`git ls-tree -r --name-only`, `git show`):

* `services/mca_episodes.py` — **есть** (2567 строк, `EpisodeService`,
  детерминированная сегментация, `segment_key`, `message_keys_json`,
  provenance, события). Не пересоздавался.
* `services/mca_episode_jobs.py` — **есть** (resumable `task_jobs`
  backfill, keyset, paused/cancelled/failed, recheck-очередь).
* `services/memory_contracts.py` — **есть**; в M1 **не изменялся**
  (нужного недостающего логического контракта не возникло; параллельный
  episode-API не создавался).
* `services/graphrag_provenance.py`, `services/provenance.py` — **есть**;
  provenance эпизодов/историй идёт через них (`record_episode_provenance`,
  `record_story_provenance` не переписаны).
* `services/memory_episodes.py` — **отсутствует**; новый модуль не
  создавался: контракт требует расширять существующий pipeline, а не
  второй episode engine.
* `services/episode_diagnostics.py` — **есть**, не изменялся (витрина
  mca-12 остаётся владельцем своей read-проекции).
* `services/mca_retrieval_context.py` — **не изменялся** (NEXT-02).

Расхождение факт-пакета Orchestrator («mca_episodes отсутствует»)
опровергнуто; блокировки записи нет.

## 2. Что изменено (Δ DDL = 0)

Только два сервиса + один новый test-файл; `git diff --name-only
23477658..80726249`:

```
services/mca_episode_jobs.py
services/mca_episodes.py
tests/test_vmq_m1_episode_contract.py
```

### M-01 — границы, source refs, качество

`services/mca_episodes.py`, блок «VMQ-M1: episode/period view contract»:

* `EpisodeView` (frozen dataclass) + `episode_view_from_row`,
  `get_episode_view`, `list_episode_views`:
  * `source_refs` — ordered (хронология сегмента), `event_start/end` —
    только из timestamps источников, `discovered_at` — отдельно;
  * `participants` — canonical `smart_messages.user_id` строк;
  * `source_fingerprint` = `sha256(ordered refs + MCA-03
    current_revision)`; отсутствующая ревизия → `?` (не 0);
  * `source_integrity` = `ok|partial|missing|unknown` по реальному
    наличию refs в строгом chat scope (удалённый источник не «актуален»);
  * `stale` = `recheck_pending` или partial/missing;
  * `projection_complete` — агрегат честных флагов (не «истина» о
    событии); `topic_refs` пусты до контракта ONTO (не выдумываются);
  * строгий chat scope: карточка чужого чата → `None`.
* Источник ревизий — `_source_states` (1–2 bounded SELECT на окно
  `EPISODE_SOURCE_MAX=500`, chunk 400).

### M-02 — периоды/coverage/опоры

`LongitudinalView` + `subject_longitudinal_view`:

* календарные bucket'ы по годам через существующий time-контракт
  `services/chat_clock.resolve_chat_timezone` (IANA чата; fallback UTC
  помечен `timezone_source`);
* `coverage`: `present_periods`, `missing_periods` (пропуск = нет
  эпизодов, не «нет событий»), `unknown_time_episode_refs`,
  `coverage["complete"]=False` + `complete_reason` до подтверждённых
  границ архива;
* `support_source_refs` — независимые корни: одна опора на различную
  формулировку; повтор мема/тот же root не повышает;
  `independent_support_count`, `repeated_claims`, `claims_without_refs`;
* `counterexample_pairs` — пары из существующего
  `detect_contradictions`, отдельно от support (не сливаются);
* `stale_episode_refs`, `legacy_unlinked_episode_refs` (legacy без refs
  видны, но не verified), `notes` с явными оговорками;
* subject filter — canonical participant ID; нет эпизодов → honest
  `empty` + `no_episodes_for_subject`.
* `period_year` — год мгновения в поясе чата; `None` для ts ≤ 0.

### M-03 — incremental/rebuild/watermark/override

`services/mca_episode_jobs.py`:

* `EpisodesBackfillRunner.rebuild_range(chat_id, since_ts, until_ts,
  max_messages, max_batches=20)`: explicit bounded rebuild keyset-порциями
  `(timestamp,id)` через тот же `process_batch`, верхняя граница
  `until_ts`, конечная работа (`REBUILD_RANGE_MAX_BATCHES`,
  `REBUILD_RECHECK_MAX`), `complete/reason/processed/episodes_created`,
  ошибка не двигает курсор через незавершённую порцию;
* backfill `run()`: **watermark не продвигается**, если порция вернула
  `errors>0` — `paused/model_unavailable`, счётчики фиксируются только
  для завершённых порций (RED-дефект D1);
* `process_rechecks` после успешных recheck пересобирает проекцию
  историй (bounded, no-op при отсутствии изменений, override не
  затирается).

`services/mca_episodes.py`:

* `_find_overlap_duplicate` — окно поиска по событийному диапазону
  (`EpisodeRepository.list_episodes_in_range`, LIMIT 300) вместо
  «последних 500 по updated_at»: повторный rebuild старого архива не
  создаёт дубль при >500 эпизодов чата (RED-дефект D3);
* `reextract_episode`: `extraction_version` = `<base>+recheck` без
  накопления суффиксов (D2); окно события пересчитывается из текущих
  timestamps источников (`COALESCE`, unknown не стирает известную дату);
  `discovered_at`/`episode_id`/`segment_key` не меняются;
* R17: `emit_story_event.summary` для story-событий — кодовая метка
  `episodes=<n>`, а не текст/производная выжимка источников; тип
  исключения LLM-провайдера логируется без тела (`reextract`).

## 3. RED → GREEN (реальные дефекты, не «зелёные отчёты»)

Один и тот же скрипт-репродукция (временный run-каталог
`WorkspaceData/runs/...`, закрыт после переноса результатов; durable-
эквиваленты — названные ниже тесты) запускался на базовом срезе
`23477658` и на кандидате; используются только публичные API.

| Дефект | База `23477658` | Кандидат `80726249` |
|---|---|---|
| D1 watermark через незавершённую порцию | FAIL: `status=paused, cursor_id=4, cursor_ts=1623780000` | PASS: `cursor_id=2, cursor_ts=1623765600` |
| D2 revision растёт при повторах recheck | FAIL: `['episodes_extract-1+recheck', 'episodes_extract-1+recheck+recheck']` | PASS: `['episodes_extract-1+recheck', 'episodes_extract-1+recheck']` |
| D3 дубль при rebuild старого архива (>500 эпизодов) | FAIL: `real_episodes=2` | PASS: `real_episodes=1` |

Долговременные регрессии — в `tests/test_vmq_m1_episode_contract.py`
(`test_watermark_does_not_jump_over_failed_portion`,
`test_edit_recheck_revision_is_stable`,
`test_old_archive_rebuild_dedups_beyond_500_episodes`).

## 4. Тесты (точные команды и счётчики)

Интерпретатор: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`
(pytest 9.1.1, `pytest.ini`: per-test timeout 60 c). Все БД — temp/
`:memory:`, production не использовался.

| Команда | Результат |
|---|---|
| `pytest tests/test_vmq_m1_episode_contract.py -q` | **32 passed** (7.0 c) |
| `pytest tests/test_mca05_episodes_stories_round1027.py tests/test_evol021_episode_semantics.py tests/test_asap8_f7_stories.py tests/test_asap8_v63_b08_stories.py tests/test_mca12_stories_round1046.py tests/test_vmq_m1_episode_contract.py -q` | **159 passed** |
| `pytest tests/test_memory_contracts.py tests/test_graphrag_memory.py tests/test_mca17_sleep_memory_workers_round1050.py tests/test_memory_health.py -q` | **295 passed** |
| `pytest tests/test_mca01_tx_task_supervisor... tests/test_mca10b_*a/b/c... tests/test_memory_communities_migration.py tests/test_asap8_v63_b09_migration.py -q` | 110 passed, **1 failed — предсуществующий** (см. §6) |
| `pytest tests/test_nostalgia_history_rework.py tests/test_nostalgia_proactive_recall.py tests/test_p0_old_lore_quarantine.py tests/test_vmq_mem_retrieval_fixes.py tests/test_history_retention_toggle.py tests/test_asap7_module_completeness.py -q` | **101 passed** |

Что именно утверждают новые тесты (не тавтологии — проверяются
наблюдаемые значения строк/refs/курсора):

* M-01: reply-цепочка внутри горизонта → 1 эпизод, точный ordered
  `source_refs`, event start/end, участники; gap > 30 мин → 2; reply вне
  горизонта → 2; параллельные участники → 2; повтор окна → тот же
  episode_id/fingerprint, count=1; ts=0 → `event_period_known=False`,
  `coverage` без периода; два чата с одним tg id → разные refs/карточки,
  чужая карточка `None`; битый reply-parent без времени не склеивает.
* M-02: 2021+2023 → 2 независимых эпизода, present `2021/2023`, missing
  `2022`, `complete=False`; повтор того же текста → 1 независимая опора,
  `repeated_claims=1`; «встретились/не встречались в парке» →
  `counterexample_pairs` с refs обоих эпизодов; старое событие 2022 не
  получает период 2026; subject filter изолирован, отсутствующий subject
  → honest empty.
* M-03: incremental vs rebuild_range на одинаковом наборе источников →
  равные projection (refs/event/participants/fingerprint/content);
  повторный rebuild → 0 новых эпизодов, те же IDs; >500 эпизодов →
  дубль не создан; две recheck-правки → revision стабильна, text
  обновлён, discovered_at/segment_key прежние; правка timestamp →
  окно события следует за источником; DELETE источника → partial/missing,
  stale, `projection_complete=False`; ошибка модели → paused, курсор на
  конце успешной порции, повтор без дублей (4 эпизода = 4
  distinct segment_key); ручной override истории переживает rebuild.
* Безопасность/границы: spy на `LLMClient.embed/embed_once`,
  `EmbeddingExecutor.embed`, `EmbeddingProviderAdapter.embed_batch` →
  0 вызовов, `embedding_cache` пуст; static-проверка модулей на
  embed/DDL-паттерны; `PRAGMA user_version` не меняется; secret-строка
  не попадает в логи `services.*` (включая exception провайдера);
  гейт OFF → `enabled=False`, 0 эпизодов, legacy-фасад работает;
  ошибка чтения view → `()`/`unavailable`; legacy `lore_stories` строка
  не переписывается (полное равенство row до/после); `limit=10000` →
  ≤ `EPISODE_VIEW_LIMIT_MAX`; `rebuild_range` с `max_batches=1` →
  processed=2, `complete=False`, `batch_cap_reached`.

## 5. Нет mass-reembedding и нет DDL

* Код-кандидат не содержит вызовов embedding/векторов: статическая
  проверка `embed(`, `embed_once(`, `embed_batch(`, `embedding_cache`,
  `upsert_vector`, `embedding_control_plane` в обоих модулях — пусто.
* Runtime-spy на четырёх уровнях провайдера → 0 вызовов на всех M1
  путях (process_batch, views, rebuild_range, process_rechecks).
* DDL: `git diff --name-only` не содержит `services/database.py`/
  migrations; в модулях нет `CREATE/ALTER/DROP TABLE|INDEX`;
  `PRAGMA user_version` до/после прогонов одинаков.
* Provenance — существующие `provenance`/`mca_source_refs`/
  `mca_evidence_links` (функции не переписаны); цитаты/бот-вывод не
  становятся независимым источником (existing validator).

## 6. Предсуществующий сбой (BACKLOG_ONLY)

`tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer`
падает **и на базе** `23477658` (проверено в отдельном worktree:

```
Differing items:
 {'summary_memory.py': 15} != {'summary_memory.py': 13}
 {'memory_maintenance.py': 3} != {'memory_maintenance.py': 1}
 {'database.py': 230} != {'database.py': 207}
 Left contains 1 more item: {'prompt_release_policy.py': 1}
FAILED tests/test_mca01_...::test_write_points_go_through_single_writer
```

Скан-паритет устарел относительно текущего кода (baseline не обновлён).
M1 не добавлял write-points в `database.py`/чужие модули; дефект
независимый, не блокирует M-01..M-03. Запись в общий backlog — за PM
(в write scope Builder не входит).

## 7. Effective configuration

* `MCA_EPISODES_ENABLED`, `MCA_EPISODES_BACKFILL_ENABLED`,
  `MCA_EPISODES_CONTINUATION_ENABLED`,
  `MCA_EPISODES_COMPILER_FACADE_ENABLED` — заводское ON (`mca_gates`);
  в тестах **не** переопределялись, кроме одного watermark-теста, где
  continuation/direct-priority выключены test-only (детерминизм
  LLM-скрипта; проверяется durable cursor, не эти ветки).
* `MCA_EPISODES_BATCH_MAX_MESSAGES` — default 500 (наблюдаемое значение в
  тестах), `rebuild_range` не может превысить gate.
* Часовой пояс coverage — из `chat_clock` (per-chat → global → factory →
  UTC); в тестах годы выбраны вне границ года, результат стабилен.
* Production precedence не менялась; секретов в артефактах нет.

## 8. Честные границы (что этим срезом НЕ доказано)

1. Паритет incremental/rebuild доказан для **одинакового окна порций**
   (batch-boundary — свойство существующего стримингового сегментатора;
   перенос сегмента через границу порции не склеивается, но и не
   дублируется — overlap-дедуп). Массовый архив/фактическое качество
   реальных эпизодов фикстурой не доказывается.
2. `coverage["complete"]` всегда `False`: границы архива не доказаны,
   «полный охват» не заявляется.
3. `topic_refs` пусты: семантические темы — ONTO-A/B, не M1.
4. Subject в longitudinal view — canonical participant ID
   (`smart_messages.user_id`); сущностный subject-резолвер — вне M1.
5. Все проверки — unit/integration на temp-БД; живого production-эпизода
   не требуется по контракту (M-01/M-03), живой архив не наблюдался.
6. `EpisodeView`/`LongitudinalView` пока не потребляются retrieval'ом:
   M2 подключает их через существующий интерфейс; M1 не менял
   `mca_retrieval_context.py` (NEXT-02 параллельная работа).
7. Изменение event-текста story-событий (`episodes=<n>` вместо выжимки)
   меняет поле `text` ленты `web_stories._feed_item` для **новых**
   событий; заголовок/display_summary карточки не меняются (читаются из
   строки истории). Это осознанное R17-следствие.
8. `rebuild_range` ограничен chat + временным диапазоном; отдельного
   subject-scoped rebuild нет (subject view — read-only производная).
   Полный архивный проход автоматически не запускается.

## 9. Follow-up seam для M2

* `list_episode_views` / `get_episode_view` / `subject_longitudinal_view`
  — read-контракт (refs, fingerprint, coverage, support/counterexample).
* `EpisodeRepository.list_episodes_in_range` — bounded time-range выборка.
* Потребление в unified retrieve — M2, через существующий
  `services/mca_retrieval_context.py` (файл M1 не трогал).

## 10. Housekeeping

Временные RED/GREEN-пробы и smoke — в `WorkspaceData/runs/` (вне
репозитория) и закрыты после переноса результатов в этот файл; durable-
эквиваленты — `tests/test_vmq_m1_episode_contract.py`. Отдельный
detached worktree базы
(`.../worktrees/c742e4de9e92c489/vmq-onto-01-3689dd92710d-aed758df`)
использовался только для сравнения и удалён после проверки. В репозиторий
добавлены только кандидатский код/тест и evidence-файлы.
