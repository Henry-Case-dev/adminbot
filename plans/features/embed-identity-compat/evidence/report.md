# EMBED-IDENTITY-COMPAT — отчёт реализации (P0, 23.10.2026)

**Лейн:** `EMBED-IDENTITY-IMPL` (Builder). **Слайсы:** IDENT-SPLIT, CANARY,
DECISION, INTEGRATION, GOV, ACCEPT — один serialized-лейн (общий
`services/embedding_control_plane.py`).
**ΔDDL = 0.** Новых таблиц, сервисов, реестров моделей и агентов нет.

**Кандидат:** `30a2f868aa36348c5c6c99ef2d723bf7a083c124` (код+тесты).
Evidence-файлы (`report.md`, `gov-report.md`, `probe_fixture.json`) добавляются
отдельным docs-коммитом поверх него; тестовое дерево полного прогона совпадает
с кодом кандидата.

---

## 1. Как определяется совместимость

Совместимость векторов решается **только** Model Space Identity (MSI).
Смена API-шлюза меняет Provider Connection Identity (PCI) — это провенанс и
инвалидация допуска, но не «другое пространство».

| | MSI (`model_space_identity`) | PCI (`connection_identity`) |
|---|---|---|
| Входит | `model`, `revision`, фактическая `dims`, `task_mode`, `normalization`, `preprocessing_version`, материальные параметры генерации | `provider_family`, `endpoint_host`, `endpoint_path`, `credential_alias`, `quota_group` |
| Не входит | host/URL/ключ/квота/маршрут | модель, размерность, параметры, нормализация |
| Смысл | **единственный критерий совместимости** | провенанс, диагностика, инвалидация допуска |
| Формат | `sha256[:16]` канон-JSON **без host** | `sha256[:16]` канон-JSON |
| Потребители | `resolve_index_compat`, `generation_space_identity` | допуск (`conn16`), панель |

Важно: `profile_identity()` переопределён как **PCI** (это была одна из двух
расходящихся формул — 16-hex PCI против 64-hex fingerprint в панели, из-за
чего панель показывала ложный `REINDEX_REQUIRED`). Совместимость пространства
считается через `profile_space_identity`/`model_space_identity`.

`summary_memory.embedding_identity_fingerprint()` (64-hex, включает host) и
`_identity_fingerprint()` **не изменены байт-в-байт** — это legacy-полная
идентичность, fingerprint реестра (провенанс) и ключ `embedding_cache`.
`_embed_cache_*` не тронуты, старые строки живут до TTL.

### Проба (`compat_probe`) — доказательство на СТАРЫХ векторах

1. **Источник эталонов** — `graph_facts_vec JOIN graph_facts` (для
   `smart_archive` — `smart_archive JOIN smart_archive_facts`), только
   eligible-строки (`expires_at`). `embedding_cache` эталоном **не является**:
   после смены identity там лежат векторы нового же провайдера (new-vs-new —
   запрещено ТЗ §2).
2. **Выборка детерминированная** (без `RANDOM`): по каждому `chat_id` каждая
   `ceil(n/6)`-я строка, ≤6 на чат, ≤12 всего (min 8); приоритет бакетам длин
   (`<200`, `200–1999`, `≥2000`); только `estimate_tokens(text) ≤ 2000`; дубли
   по `casefold(strip)` схлопываются.
3. **Новые векторы** — те же тексты через штатный serving-путь (`_embed`,
   приоритет P2), **один батч**. Эталоны новым провайдером не создаются.
4. **Косинус** считается по float-колонке `embedding` (не `embedding_i8`)
   существующим `graphrag_rebuild._read_vector`.
5. **Проверка поиска (обязательна):** те же новые векторы как запросы к
   **старому** индексу `SELECT rowid, fact_id FROM graph_facts_vec WHERE
   embedding MATCH ? AND k = 5`; `hit5` = доля запросов, чей `fact_id` в top-5.
   Это отсекает «совпали размерности, но выдача чужая».
6. **Пороги (frozen в коде, не hot-config):**
   * compatible: `checked ≥ 8`, dims совпали, `mean ≥ 0.995`, `min ≥ 0.990`,
     `hit5 ≥ 0.80`;
   * incompatible: dim mismatch, либо `mean < 0.970`, либо `min < 0.940`,
     либо `hit5 < 0.40`;
   * иначе insufficient (`weak_numeric|low_hit5|too_few_vectors|
     api_unavailable|no_old_vectors|provenance_unknown`);
   * полоса `0.970 ≤ mean < 0.995` → **один независимый повтор** на другой
     фазе выборки; compatible — только если подтверждающий прогон compatible.
     Метрики допуска берутся из подтверждающего прогона, слабая полоса
     сохраняется в `canary.band` (не «лучший из двух»).
7. **Недоступность API / мало данных → insufficient, никогда incompatible.**
   Индекс, факты, кэш и старые поколения не меняются; поиск — FTS.

### Одно решение читают все точки

`resolve_index_compat(db, index, current_fp, current_dims)` (read-only, без
сети) возвращает `{state, reason_code, serviceable, space, conn, admission,
canary, source_empty, needs_probe, class, action}`. `state ∈ compatible |
insufficient | incompatible | source_empty | no_generation`.

Потребители: `summary_memory._index_generation_ok`, гейт
`_register_index_generations`, `graphrag_rebuild.ensure_current_generation`,
`maybe_schedule_rebuilds`, `generation_status`, `ecp.vector_memory_panel`,
`GET /api/memory/embeddings` (аддитивный блок `compat`).

## 2. Почему adopt / rebuild / ничего

| Исход | Действие | Что происходит с данными |
|---|---|---|
| **compatible** | `adopt_embedding_generation()` — одна `serialized()`-транзакция: `status='active'`, `activated_at`, `config_revision=adopt1:<space16>:<conn16>:<checked>:<mean>:<min>:<hit5>:<at>`; затем `cancel_rebuild` + `supersede_building_generations(keep=adopted)` | индекс/векторы/факты целы; `fingerprint/provider/endpoint` **не перезаписываются** (провенанс); rebuild не стартует; backfill добирает недостающие векторы в ту же таблицу |
| **insufficient** | ничего не активируем и не регистрируем; запущенная сборка под новый fp ставится на паузу (обратимо); `action=retry_canary|need_old_vectors` | индекс/факты/кэш/старые `building`-строки сохранены; FTS; понятная диагностика (`generation.state=compat_insufficient`, `serviceable=false`, `reindex_required=false`) |
| **incompatible** | существующий контролируемый путь: target-generation (`building`) → shadow `{live}_g{gen}` → `_validate` → атомарная `_activate`; пауза снимается; переэмбеддиваются только `graph_facts.fact` | live не смешивается; старый ACTIVE сервит до promotion; source-факты и shadow не удаляются |
| **source_empty** | ничего (перестраивать нечего) | — |

Вердикт durable в `config_revision` ACTIVE-строки (без новой таблицы).
Инвалидация: допуск валиден только при `space16==space_now` и
`conn16==conn_now`; мусорный/чужой `config_revision` → отказ adopt
(fail-closed). Негативные вердикты не персистятся — перепроверяются раз за
старт/тик (1 батч, cooldown 15 мин).

Kill-switch: **`EMBED_COMPAT_ADOPTION_ENABLED`** (env-only, default ON).
`OFF` = прежнее поведение (любой другой fingerprint → rebuild), проба не
запускается.

## 3. Что изменено

| Файл | Изменение |
|---|---|
| `services/embedding_control_plane.py` | MSI/PCI (`model_space_identity`, `generation_space_identity`, `connection_identity`, `profile_space_identity`), `profile_identity`→PCI, `classify_identity_compatibility` (+`ADMITTED_COMPATIBLE`), `format/parse_admission`, `compat_probe`, `resolve_index_compat`, `ensure_index_compat`, поля `compat` в `vector_memory_panel` |
| `services/summary_memory.py` | `_index_generation_ok` читает единый вердикт; гейт в `_register_index_generations`; inline-проба в `initialize()` после регистрации поколений и **до** recovery/backfill; skip фоновой drift-canary, пока вердикт не получен; честный hint лога |
| `services/graphrag_rebuild.py` | `ensure_current_generation`/`maybe_schedule_rebuilds` не запускают rebuild до вердикта (тик перепроверяет insufficient одним батчем); `generation_status` различает `active` / `compat_insufficient` / `build_*` / `identity_changed` + `serviceable/action/compat`; исправлен pre-existing `TypeError` в `resume_rebuild` (`tuple | frozenset`) — без него «resume после incompatible» не работал |
| `services/database.py` | +`adopt_embedding_generation` (одна транзакция, без DDL) |
| `web/api/memory_agi.py` | аддитивный блок `compat` в `GET /api/memory/embeddings` (без нового роута) |
| тесты | новый `tests/test_embed_identity_compat.py`; правки `test_asap5_embedding_identity`, `test_graphrag_identity_reindex` (смена шлюза больше не rebuild; A→B→A — реальная смена модели); `test_mca01_tx_task_supervisor_round1027` (allowlist +1 commit нового serialized-метода) |

**Не трогали:** `embedding_identity_fingerprint`, `_identity_fingerprint`,
`_embed_cache_*`, DDL/схему/версии, строки `embedding_cache`,
`_validate`/`_activate`, lease/pauses/kill-switch, `web/index.html`,
`web/app.js`, `web/static/**`, `services/direct_l1.py`,
`direct_chat_service.py`, `chat_prompts.py`, `summary_l2_review.py`,
`pipeline_events.py`, `plans/current_task.md`, requirements-map,
`plans/progress_scope.json`, прод/SSH/живые чаты.

## 4. Проверки (кандидат)

Команда: `.venv\Scripts\python.exe -m pytest tests/test_embed_identity_compat.py -q`

```
20 passed
```

Смежные наборы (embed/graphrag/memory/API/registry-write):

```
tests/test_embed_identity_compat.py (20)
tests/test_asap5_embedding_identity.py
tests/test_asap6_embedding_generations.py
tests/test_graphrag_identity_reindex.py
tests/test_webapp_memory_overview_api.py
tests/test_mca01_tx_task_supervisor_round1027.py .... 107 passed
```

Полный прогон `pytest -q` запускался на том же исходном коде; 20-й тест
(`new_write_after_adopt`) и усиленная проверка сценария 8 добавлены после
старта прогона и проверены отдельно (20 passed; набор выше — 107 passed).

Расширенный смежный набор (control plane asap4, recovery, rebuild, graphrag
database/memory, summary_memory, F8 embeddings, fallback-слоты, primary-slot,
batch-breaker, tx-supervisor): **451 passed, 1 failed**.
Единственное падение — `test_asap5_graphrag_recovery.py::test_future_resume_tick_after_cooldown_restart_survives`
— **pre-existing** (воспроизведено на чистом HEAD-worktree без изменений
лейна; порядко-зависимое состояние process-level AIMD-контроллера:
`_batch` остаётся 50 → 429 не наступает).

Полный прогон `pytest -q`: **15274 passed, 39 skipped, 9 failed** (750 s).
Разбор всех 9 падений:
* **7 — pre-existing** (воспроизведены на чистом HEAD-worktree без изменений
  лейна): `test_t5150_startup_migrations_round1046` (5) и
  `test_asap7_direct_settings` (2) ждут `user_version=35`, а в БД уже
  v36/v37;
* **2 — midnight-UTC флейки** (не связаны с эмбеддингами; проходят
  standalone вне границы суток): `test_embedding_control_plane_asap4.py::
  test_parking_spend_until_utc_day_end` (`_utc_day_end()` пересчитан после
  полуночи UTC) и `test_asap8_initreply_binding.py::
  test_nostalgia_without_writer_sends_without_reply` (time/random-зависимый
  nostalgia-тест; в предыдущем прогоне падал другой тест того же файла).
  Оба файла после прогона: `69 passed` и `14 passed` соответственно.
* Ни одного падения в embed/graphrag/memory/API-скоупе лейна.

### Метрики пробы на фикстуре (не прод)

`plans/features/embed-identity-compat/evidence/probe_fixture.json`
(20 фактов, 2 чата, детерминированные векторы; мок — только HTTP-embed):

| Сценарий | verdict | checked | mean | min | hit5 | runs |
|---|---|---|---|---|---|---|
| те же векторы, новый шлюз | compatible | 12 | 1.0 | 1.0 | 1.0 | 1 |
| полоса: первый прогон 0.99 | compatible | 12 | 1.0 | 1.0 | 1.0 | 2 (band mean 0.99) |
| то же имя модели, другое пространство | incompatible | 12 | 0.151 | -0.217 | 0.25 | 1 |
| API недоступен | insufficient | 0 | — | — | — | 1 |

После всех проб: live-строк 20, source-строк 20, поколений 1 (`building`) —
проба ничего не удаляет и не активирует.

## 5. Сценарии приёмки

| # | Сценарий источника | Статус | Тест |
|---|---|---|---|
| 1 | одна модель, одинаковые векторы, разные провайдеры → перестройка не запускается | **PASS** (fixture) | `test_scenario_01_gateway_swap_adopts_existing_index` |
| 2 | малая численная погрешность | **PASS** (fixture) | `test_scenario_02a_band_requires_repeat_then_compatible`, `test_scenario_02b_band_repeat_not_compatible_is_insufficient` |
| 3 | одинаковое имя модели, разные фактические векторы → несовместимость | **PASS** (fixture) | `test_scenario_03_same_name_different_space_is_incompatible` |
| 4 | разные модели/размерности — индексы не смешиваются | **PASS** (fixture) | `test_scenario_04_dimension_mismatch_never_mixes` |
| 5 | недоступность API — данные не теряются, автоматики нет | **PASS** (fixture) | `test_scenario_05_api_unavailable_is_insufficient_keeps_data` |
| 6 | возврат к предыдущему провайдеру — старый индекс переиспользуется | **PASS** (fixture) | `test_scenario_06_flip_back_reuses_confirmed_index` |
| 7 | рестарт — результат сохраняется, повторной перестройки нет | **PASS** (fixture) | `test_scenario_07_restart_reads_durable_admission` |
| 8 | два чата — нет дублей и нарушения изоляции | **PASS** (fixture) | `test_scenario_08_two_chats_single_adopt_no_isolation_break` |
| 9 | уже запущенный rebuild — безопасная отмена после adopt | **PASS** (fixture) | `test_scenario_09_running_rebuild_cancelled_by_adopt` |
| 10 | поиск по старым фактам новым API — реальная выдача | **PASS** (fixture, search-level `hit5`) | `test_scenario_10_search_new_api_finds_old_facts` |

ACC-11 «после смены провайдера память работает без полной перевекторизации»
— **NOT_TESTED на проде** (требует деплоя и A0-probe; это шаг DevOps).
ACC-12 — **PASS** (fixture): adopt не запускает rebuild/re-extraction,
`maybe_schedule_rebuilds()==[]`, live/source счётчики не меняются.
ACC-13 (отчёт «как определена совместимость и почему») — **PASS**: этот файл.
ACC-14 (не объявлять совместимость без измерения) — **PASS**:
`test_antitheorem_new_vs_new_cannot_prove_compatibility` — эталоны только из
`embedding_cache` (new-vs-new) НЕ дают compatible; `no_old_vectors`.
ACC-15/16/17 (доп. лейн): гейт регистрации + inline-проба; панель и
`generation_status` читают один вердикт; insufficient ставит сборку на паузу.
DEC-05: `test_new_write_after_adopt_is_searchable` — новая запись после adopt
попадает в тот же индекс и находится KNN.

## 6. GOV-аудит

* GOV-01/GOV-06: новых сервисов, таблиц, реестров моделей, агентов нет; ΔDDL=0.
* GOV-02: нет хардкода под API.NET/Gemini; провайдер-агностично (host/family
  только в PCI, совместимость — измерение).
* GOV-03: совпадение имени модели не даёт compatible (тест 3).
* GOV-04: `embedding_identity_fingerprint`/`_identity_fingerprint` не
  переписаны; защиты (`_validate`/`_activate`, lease, pauses, kill-switch) не
  отключены; массового «всё совместимо» нет.
* GOV-05: adopt не удаляет векторы/факты/поколения; тесты сверяют счётчики.

## 7. Что осталось для прода (A0) и риски

1. **A0-probe (read-only, до деплоя):** прогнать `compat_probe` на 12 реальных
   прод-фактах через apinet и зафиксировать `mean/min/hit5` + `checked`.
   Точка входа (не меняет БД: только чтение индекса + один embed-батч):
   `ecp.compat_probe(db, "graph_facts_vec", embed_fn=<serving embed>)`.
   Пороги frozen; если вердикт insufficient — деплой не включает adopt, поиск
   остаётся FTS (ожидаемое состояние, не регресс).
2. **После деплоя:** `GET /api/memory/embeddings` →
   `compat.serviceable=true`, `compat.canary.{mean,min,hit5}`,
   `generation.state`; лог `EMBEDDING_COMPAT_ADMITTED`; backfill 4 048 → 0;
   `_vec_write_allowed=True`. Если вердикт insufficient/incompatible — панель
   покажет причину и `action`.
3. **Риск R2 (ложный adopt):** сдерживание — `min` чувствителен к загрязнённой
   таблице, purity-by-write-gate, KNN-hit5; откат — снять допуск
   (`status='building'`, `config_revision=NULL`) → FTS-only, векторы целы.
4. **Риск тайминга старта:** inline-проба добавляет один embed-батч (≤12
   текстов) к `initialize()` до backfill/recovery. API недоступен → быстрый
   insufficient (штатные таймауты executor'а).
5. **Совместимость с `5877810d`:** A→B→A (реальная смена модели) и честный
   `build_failed` сохранены (тесты обновлены под новую семантику: смена только
   шлюза больше не rebuild).
