# EMBED-REBUILD-MECHANISM — почему векторная память жила в FTS-only и что исправлено

Дата: 23.10.2026. Лейн: `EMBED-REBUILD-MECHANISM` (аудит `_audit-2026-10-23`).
Прод `198.46.175.136`, read-only факты — из `../embed-provider/report.md`
(SSH не использовался в этом лейне).

## 1. Наблюдаемый симптом (прод)

* Живой лог процесса: `embedding generation not serviceable | index=graph_facts_vec |
  status=building | gen_fp=96f80838f683 new_fp=2d0efab0e817 — FTS-only (A06)`.
* `_vec_write_allowed()` → False: новые факты пишутся text-only, backfill = 0,
  backlog 4 170, векторный поиск не работает (только FTS5).
* Реестр `mca_embedding_index_generations` — ровно 2 строки, обе `building`,
  `activated_at=NULL`, `fingerprint=96f808…` (Google), созданы 29.09.2026;
  у `graph_facts_vec` `pause_reason=rate_limit:quota_group`, `attempts_total=592`,
  `next_allowed_at` — в будущем.
* Провайдер после смены (apinet) здоров, dim 3072 (совместим), probation-группы
  `apinet_paid`/`google_free_1`/`google_free_2` — healthy.
* `NRestarts=0` — процесс не перезапускался после смены identity.

## 2. Схема текущего пути (как задумано)

```
СОЗДАНИЕ поколения
  MemoryManager.initialize()                     services/summary_memory.py:1640
    └─ _register_index_generations(activate=…)    services/summary_memory.py:1837
         └─ db.ensure_embedding_generation()      services/database.py:5931
              (нет ACTIVE → INSERT status='building'|'active';
               ЕСТЬ ACTIVE → ВОЗВРАТ существующего, даже если fp другой — A06)
  Только два вызова регистрации:
    * startup (initialize)                        summary_memory.py:1748
    * vec-reactivation после embed-фейла          summary_memory.py:2300 (_ensure_vec_retry)
  Больше никто поколений не создаёт (в prod-коде `register_embedding_target_generation`
  и `begin_embedding_migration` не вызывались вообще — только в тестах).

BACKFILL (= fill-missing, НЕ rebuild)
  startup/реактивация → fire_and_forget backfill_archive_vectors /
  backfill_graph_fact_vectors                     summary_memory.py:2397 / 2470
    └─ ГЕЙТ: `_vec_write_allowed(index)`          summary_memory.py:1947
         └─ `_index_generation_ok(index)`         summary_memory.py:1877
              ACTIVE.fp == current → True; иначе (building/старый fp/нет ACTIVE) → False
  Т.е. backfill не является «догоняющим» путём: при расхождении identity он пишет 0.

REBUILD поколения (shadow → validation → activation)
  старт: maybe_schedule_rebuilds()               graphrag_rebuild.py:1751
    * startup: MemoryManager._recover_runtime_jobs  summary_memory.py:2526
    * periodic tick 15 мин: start_resume_ticker/resume_tick_once  graphrag_rebuild.py:464/472
    * post-release после каждой джобы             graphrag_rebuild.py:1381
    условие (до фикса): latest generation.status=='building' AND fingerprint==current
  джоба: run_job                                  graphrag_rebuild.py:1012
    shadow `{live}_g{gen}` (полный re-embed всех eligible, НЕ fill-missing)
      → checkpoint в task_jobs
      → _validate (9 критериев)                   graphrag_rebuild.py:722
      → _activate (DROP live + CREATE + копия из shadow + реестр, ОДНА транзакция)
                                                  graphrag_rebuild.py:952
```

**Вывод по схеме:** единственный путь `building → active` — успешный полный
shadow-rebuild одной джобой. Без него поколение не активируется никогда.

## 3. Причина №1 — смена identity в рантайме не создавала новое поколение

`maybe_schedule_rebuilds` (до фикса) буквально:

```python
gen = await db.get_latest_embedding_generation(index_name)
if gen is None or gen["status"] != "building":
    continue                      # active/failed/superseded — не наш случай
if gen["fingerprint"] != current_fp:
    continue                      # D2: чужой build не оживляем
```

То есть при `gen_fp != current_fp` индекс молча пропускался: старый build не
оживляется (правильно по D2 race-guard), но **новое поколение под новый fp не
создавалось**. Регистрация жила только в `MemoryManager.initialize()` (и
vec-reactivation), а смена провайдера применяется hot-config'ом **без рестарта**
(`POST /api/config`, см. embed-provider §8) → процесса, который бы зарегистрировал
новое поколение, не было (`NRestarts=0`).

Следствие: поколения под текущий fp нет ни в одном состоянии →
`_index_generation_ok` (ACTIVE нет → берётся latest = старое `building`) → False →
`_vec_write_allowed` False → backfill 0 → тихий FTS-only. Единственный
«самолечащий» путь был рестарт процесса (тогда `initialize()` вставил бы новое
`building`-поколение), и это нигде не было видно как обязательное действие.

Проверка «есть ли штатная операторская команда reindex»:
* admin API/CLI отсутствует: `POST|GET /api/memory/embeddings` — только чтение
  (`web/api/memory_agi.py:483`);
* `pause_rebuild/resume_rebuild/cancel_rebuild` (`graphrag_rebuild.py:1824+`)
  реализованы, но не подключены ни к одному роуту;
* ASAP-6 машина миграций `begin_embedding_migration` /
  `run_embedding_migration_chunk` (`embedding_control_plane.py:2571/2810`) есть,
  но **не имеет ни одного прод-вызова** (только тесты) и своего scheduler'а —
  это нерабочий путь;
* знание «нужен reindex» в панели было неверным: `vector_memory_panel`
  сравнивает `profile_identity()` (схема D11, 16 hex) с `fingerprint` реестра
  (sha256, 64 hex) → при наличии ACTIVE всегда `REINDEX_REQUIRED`, а при
  отсутствии ACTIVE (`active_generation=None`) не показывает ничего — ровно наш
  прод-случай (incidental finding, файл принадлежит другому лейну).

## 4. Причина №2 — почему поколения от 29.09 не активировались

Активация требует: полный shadow-скан всех eligible фактов → 9 критериев §6
(`_validate`) → атомарный swap (`_activate`). Джоба 29.09 дошла до
`processed=9797` из 15 819, после чего многократно уходила в
`paused_rate_limit` (`pause_reason=rate_limit:quota_group`, `attempts_total=592`):
провайдерская квота/парковка группы. Ни одного полного прохода → ни одной
валидации → `activated_at` остался NULL. Авто-перехода `building → active` без
полного build нет by design (`_activate` — единственная точка `UPDATE status='active'`).

Дополнительно: после смены identity та же джоба **уже не могла** активироваться —
критерий §6.1 `fingerprint_current` (`graphrag_rebuild.py:730-736`) вернул бы
`failed/fingerprint_changed` (и удалил бы shadow). То есть продолжение старой
джобы бессмысленно: нужна новая генерация под текущий fingerprint.

## 5. Что изменено (минимально, REUSE реестра/job/lease, ΔDDL=0)

| Файл | Изменение |
|---|---|
| `services/graphrag_rebuild.py:1594` | **`ensure_current_generation()`** — единственная точка «догнать identity»: строка текущего fp `building/validated` → цель сборки; `active` → перестройка не нужна; строки нет / она `superseded|failed` → новое `building`-поколение через существующий `db.register_embedding_target_generation` (ACTIVE другого identity не трогается; старые строки/векторы/shadow не удаляются). Пустой источник → поколение не регистрируется (`knn_source_empty` не нужен). Fail-open. |
| `services/graphrag_rebuild.py:1751` | `maybe_schedule_rebuilds`: при `latest` не `building`/чужой fp вызывается `ensure_current_generation` и планирование продолжается уже по новой строке. Поведение D2 сохранено: чужой/терминальный build не оживляется. |
| `services/graphrag_rebuild.py:1677` | **`generation_status()`** — честный R17-safe снимок: `state ∈ {active, build_in_progress, build_failed, identity_changed, no_generation}`, `reindex_required`, `reason_code`, `dim_mismatch`, brief latest/active поколения. |
| `services/graphrag_rebuild.py:1667` | Новое событие `EMBEDDING_GENERATION_REBUILD_REQUIRED` (outcome `skipped`, `reason_code=embedding_generation_changed`, только index/gen/короткие fp) + WARNING-лог. |
| `services/database.py:5993` | `register_embedding_target_generation` стал **идемпотентным по fingerprint** в scope `(namespace, index)`: check+insert под тем же single-writer lock'ом → повторный/параллельный тик не плодит `building`-дубли. |
| `services/summary_memory.py:1913` | Лог `_index_generation_ok` различает «build in progress» и «identity changed — rebuild required» (строка `not serviceable` сохранена — контракт существующих тестов). |
| `web/api/memory_agi.py:536` | Read-API `GET /api/memory/embeddings` получил additive-блок `generation` (состояние индексов) — честный статус без нового роута. UI-потребление — лейн W4-UI. |

Не тронуто: `services/embedding_control_plane.py`, `llm_client.py` (лейн
EMBED-FALLBACK-FIX), `web/**`, direct-chat, `plans/current_task.md`, карты.

## 6. RED → GREEN

RED на pre-fix коде (рабочий diff лейна временно снят, файлы восстановлены из HEAD):

```
.venv/Scripts/python.exe <scratch>/embed-rebuild/red_probe.py
registry before: gen=1 status=building fp=96f80838f683
SmartModule: embedding generation not serviceable | status=building |
  gen_fp=96f80838f683 new_fp=2d0efab0e817 — FTS-only (A06)     <-- прод-строка 1:1
scheduled=[] new_generation=None job=no
_vec_write_allowed=False
FAIL: под текущий fingerprint НЕ появилось поколение (тихий FTS-only)
FAIL: durable-джоба rebuild под текущий fp не создана         EXIT=1

pytest tests/test_graphrag_identity_reindex.py -q  → 10 failed, 1 passed
```

GREEN после фикса (тот же probe):

```
EMBEDDING_GENERATION_REBUILD_REQUIRED | index=graph_facts_vec | gen=2 |
  identity changed → new generation | prev_fp=96f80838f683 | current_fp=2d0efab0e817
scheduled=['graph_facts_vec'] new_generation=2 job=yes
_vec_write_allowed=False        (build ещё не завершён — mixed space запрещён)
EXIT=0
```

`_vec_write_allowed` после активации → True (тест
`test_vec_write_allowed_follows_generation_lifecycle`).

Новые тесты — `tests/test_graphrag_identity_reindex.py` (11 шт.):

1. `test_identity_change_registers_generation_and_job` — смена fp → новое
   поколение + durable-джоба; старое поколение и его shadow не тронуты; identity-поля
   заполнены так, что validation §6.3/§6.4 проходит.
2. `test_identity_change_rebuild_activates_and_keeps_old_data` — полный путь
   build→validate→activate: ACTIVE под новый fp, live=4 вектора, source-факты целы,
   старый shadow цел, `_vec_write_allowed=True`.
3. `test_ensure_current_generation_idempotent` — повторный вызов и двойной
   schedule не плодят поколения/джобы.
4. `test_active_current_identity_needs_no_rebuild` — ACTIVE текущего fp → no-op.
5. `test_active_old_identity_gets_target_generation` — ACTIVE старого identity
   остаётся `active` (A06/§8.4), под новый fp создаётся target; запись в ACTIVE
   запрещена до promotion.
6. `test_vec_write_allowed_follows_generation_lifecycle` — False до, False во
   время, True после перестройки.
7. `test_generation_status_reports_identity_changed` + `..._active_and_build_in_progress`
   + `..._dim_mismatch_flag` — честные состояния.
8. `test_superseded_generation_under_current_fp_registers_new` — терминальная
   строка под текущий fp (A→B→A) → новое поколение, история сохранена.
9. `test_registryless_db_is_fail_open` — БД без реестра: пусто, без исключений.

API-контракт — `tests/test_webapp_memory_overview_api.py::TestEmbeddingsGenerationStatus`
(2 шт.): 401 без initData; `generation` присутствует, существующие ключи не
сломаны, без реестра — честно пусто.

Прогоны (`.venv/Scripts/python.exe -m pytest`, локально, без сети/прода):

| Набор | Результат |
|---|---|
| новый файл + graphrag/embed/memory/mca07/mca01_tx/API (20 файлов, см. ниже) | **678 passed** |
| `tests/test_memory_*.py` (весь glob) | **295 passed** |
| RED (pre-fix) `tests/test_graphrag_identity_reindex.py` | **10 failed, 1 passed** |

Конкретные файлы зелёного прогона: `test_graphrag_identity_reindex`,
`test_graphrag_rebuild_asap32`, `test_asap5_graphrag_recovery`,
`test_asap5_embedding_identity`, `test_asap6_embedding_generations`,
`test_asap8_f8_embeddings`, `test_graphrag_database`, `test_graphrag_memory`,
`test_summary_memory`, `test_asap44_graphrag_batch_breaker`,
`test_embedding_control_plane_asap4`, `test_mca07_retrieval_context_round1027`,
`test_mca01_tx_task_supervisor_round1027`, `test_memory_rebuild_round1021`,
`test_memory_core_round1020`, `test_memory_maintenance`,
`test_memory_lookup_round1026`, `test_soul1_w7_embedding_primary_slot`,
`test_webapp_memory_overview_api`, `test_asap8_v63_b09_migration`.

## 7. Команда для DevOps (что делать после деплоя)

**Отдельная «reindex»-команда не нужна и не создавалась**: путь штатный и
автоматический — на старте процесса `maybe_schedule_rebuilds` (startup-schedule)
и далее тик каждые 15 минут (`start_resume_ticker`) сами регистрируют поколение
под текущий fingerprint и ставят bounded rebuild. Если процесс не перезапускается,
достаточно дождаться тика (≤15 мин).

Порядок:
1. Задеплоить коммит лейна штатным деплоем (рестарт сервиса не обязателен для
   фикса как такого, но при рестарте путь сработает сразу на startup).
2. Ничего больше не запускать: rebuild стартует сам (lease — только одна
   перестройка одновременно, второй индекс ждёт освобождения permit).
3. Наблюдение (read-only):
   * `GET /api/memory/embeddings` → `generation.indexes[]`:
     `state` `build_in_progress` → `active`; `rebuild` (progress/heartbeat),
     `backlog.backlog_graph` (должен падать с 4 170);
   * лог: `EMBEDDING_GENERATION_REBUILD_REQUIRED | ... gen=2`, далее
     `EMBEDDING_GENERATION_BUILD_START/PROGRESS/VALIDATED/ACTIVATED | index=graph_facts_vec | gen=2`.
4. Ожидаемый объём/стоимость (из `../embed-provider/report.md` §4/§7):
   `graph_facts` eligible = **15 819** фактов → **≈316 HTTP-вызовов** при batch 50,
   ≈2.4M входных токенов, одиночный вызов apinet ≈1.9–4.4 с → ориентировочно
   **15–40 минут** при здоровом провайдере (плюс sleep 0.5 с между батчами).
   `smart_archive_facts = 0` → его поколение не регистрируется вовсе (пустой
   источник), дополнительных вызовов нет.
5. Ограничители/остановка (уже существующие, новых нет):
   * `GRAPHRAG_REBUILD_BATCH` (default 50), `GRAPHRAG_REBUILD_SLEEP_SECONDS` (0.5);
   * контроль-плейн: группы квот, AIMD-batch, priority P3, паузы
     `paused_rate_limit/paused_provider` с авто-resume;
   * `EMBED_RETRY_HORIZON_HOURS` (24 ч) → терминальный `failed`;
   * полный стоп: `GRAPHRAG_SHADOW_REBUILD_ENABLED=false` + рестарт (FTS5
     продолжает обслуживать; kill-switch байт-в-байт прежний).
6. Старая paused-джоба (`fp=96f808…`) после фикса не возобновляется (чужой fp),
   остаётся историей в `task_jobs`; её shadow `graph_facts_vec_g1` (9 797 строк)
   не удаляется.

## 8. Риски и что будет со старыми данными

* **Данные не удаляются.** `_activate` заменяет ТОЛЬКО live vec-таблицу
  (пересоздаётся из shadow нового поколения); `graph_facts`/`smart_archive_facts`
  — source of truth, не трогаются (`graphrag_rebuild.py:964-974`). Старое
  поколение остаётся строкой реестра (`building`, с pause-метаданными), старый
  shadow `*_g1` остаётся на диске.
* **Старые векторы в другом пространстве.** Векторы, построенные Google-моделью
  (`96f808…`), несовместимы с apinet-пространством: до активации нового поколения
  запись/чтение KNN закрыты (FTS5 обслуживает), после активации live содержит
  только векторы новой identity — это и есть цель перестройки.
* **Стоимость.** Автоматический старт = ≈316 вызовов/2.4M токенов на полный
  re-embed (см. §7.4). Это ожидаемое следствие смены провайдера; кэш эмбеддингов
  (64.4) переиспользует только совпадающий identity, т.е. на новую identity
  кэш почти не помогает.
* **Идемпотентность/гонки.** Новое поколение регистрируется под single-writer
  lock идемпотентно по fp; параллельный тик/рестарт не плодит дубли. Если
  identity меняется во время build, старая сборка не активируется (критерий §6.1),
  новая будет запланирована следующим тиком.
* **Ложный статус панели (incidental, не в этом лейне):**
  `vector_memory_panel` сравнивает `profile_identity()` (16-hex схема D11) с
  `fingerprint` реестра (sha256 64-hex) → `compat_class` при наличии ACTIVE
  всегда `REINDEX_REQUIRED`. Новый блок `generation` считает состояние по
  правильной схеме (`summary_memory.embedding_identity_fingerprint`), поэтому
  UI должен ориентироваться на него. Файл `embedding_control_plane.py`
  принадлежит лейну EMBED-FALLBACK-FIX — не правил.
* **Fail-open границы:** при БД без реестра/ошибке чтения `generation_status`
  отдаёт пустой снимок, `ensure_current_generation` — None (никаких исключений
  в startup/tick).

## 9. Инструменты/артефакты

* RED-проба: `%OPENCODE_WORKFLOW_SCRATCH%/embed-rebuild/red_probe.py`
  (+ `red_probe_prefix.txt`, `red_pytest_prefix.txt` — вывод pre-fix).
* GREEN: `%OPENCODE_WORKFLOW_SCRATCH%/embed-rebuild/green_final_pytest.txt`
  (678 passed).

## 10. Кандидат и привязка

* База кандидата: `468d1041` (соседний лейн EMBED-FALLBACK-FIX уже влит),
  коммит лейна — следующий `fix(embed): регистрировать поколение индекса …`
  (SHA — в handoff; `git log -1` в рабочем дереве).
* Комбинированный прогон на этом дереве (включая изменённый соседним лейном
  `services/embedding_control_plane.py`): **527 passed** — набор
  `test_graphrag_identity_reindex`, `test_graphrag_rebuild_asap32`,
  `test_asap5_graphrag_recovery`, `test_asap5_embedding_identity`,
  `test_asap6_embedding_generations`, `test_asap8_f8_embeddings`,
  `test_graphrag_database`, `test_embedding_control_plane_asap4`,
  `test_mca07_retrieval_context_round1027`,
  `test_mca01_tx_task_supervisor_round1027`, `test_graphrag_memory`,
  `test_summary_memory`, `test_webapp_memory_overview_api`,
  `test_embed_fallback_slots_routing`.
* sha256 изменённых файлов (кандидат):

```
dee90c3d989d8e21dff930d78c4030f25f258159a9b16a70d41d5797a5b8b81e  services/graphrag_rebuild.py
eaaca84244985e1ae0fc25c1033350a3ef19e0f4fb5b79260284bd25a1c943d7  services/database.py
80349aac7e1afe19b8b53192137e131a88cd0a640fe8ba83092594863ce61df0  services/summary_memory.py
723c7c61a6cc48357f3ced75b306adafe8521c0eeff3efae9e75897cda488440  web/api/memory_agi.py
d8a665ee1d3ffb766dabe642a29ded8058d14c4f9490ded451bc790246527648  tests/test_graphrag_identity_reindex.py
5d550274a46f640f33314c44e07d35953adfac167ead133c9a9feb29e28a0985  tests/test_webapp_memory_overview_api.py
```

