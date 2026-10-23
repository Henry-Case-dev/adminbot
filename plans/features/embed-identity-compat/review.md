# EMBED-IDENTITY-COMPAT — независимое ревью P0 (LANE REV-EMBED-IDENTITY)

**Кандидат:** `30a2f868aa36348c5c6c99ef2d723bf7a083c124` (+ evidence `02f5473f597d3f733bc35364686e6d9ca5e4cca7`).
HEAD `0e63c117` проверен: `git diff 30a2f868 HEAD -- services/ web/api/ tests/` пуст — код и тесты в объёме лейна на HEAD те же.
**Карта:** `plans/features/embed-identity-compat/requirements-map.json` sha256 `6658f8da77a15389`; `source_sha256` карты совпадает с источником (`429a9868…`). Дизайн `arch-design.md` sha256 `700f68128ff78c73`.
**Режим:** read-only; изменён только этот файл.

## ВЕРДИКТ: `Needs Fixes`

Механика фичи (разделение MSI/PCI, проба на старых векторах, adopt, единый резолвер) реализована корректно и независимо подтверждена. Блокируют: (1) реальный дефект восстановления после рестарта в ветке `incompatible`; (2) приёмочный реестр не привязан к кандидату и не содержит доказательств (review-гейт FAIL); (3) A0-рецепт не проверяет ту ветку, от которой зависит главный результат на проде.

## 1. Главный вопрос: доказывает ли canary совместимость СТАРЫХ векторов?

**Да.** Эталон — только сохранённые строки live-индекса:

* выборка: `graph_facts_vec JOIN graph_facts` / `smart_archive JOIN smart_archive_facts`, eligible по `expires_at`, без `RANDOM` — `services/embedding_control_plane.py:2792-2806`, `_select_sample :2726-2789`;
* тексты — из source-таблицы по id (`:2809-2817`), дедуп по `casefold(strip)`, отсечение `estimate_tokens>2000` (`:2894-2902`);
* новые векторы — **один** батч через serving-путь (`:2905-2915`), без записи в live;
* старый вектор — `SELECT rowid, embedding FROM {live}` float-колонка (`:2820-2831`, `:2922-2933`); `rowid = fact_id` в обеих ветках записи (`services/summary_memory.py:2678-2690`, `services/graphrag_rebuild.py:786-805,1081`);
* поисковая проверка — те же новые векторы как запросы к **старому** индексу `embedding MATCH ? AND k=5` (`:2834-2865`, `:2941-2952`).

Ветки «создать эталон новым провайдером и сравнить с ним же» нет. `embedding_cache` эталоном не служит (в пробе не читается), а типизированный ключ кэша включает полный legacy-fingerprint (`summary_memory.py:454-463,2226-2262`), поэтому старые (Google) векторы под новым fp не подмешиваются. При отсутствии/недостатке старых векторов — `no_old_vectors`/`too_few_vectors` → `insufficient` (`:2886-2889,2936-2937,2957-2959`). Анти-тест `test_antitheorem_new_vs_new_cannot_prove_compatibility` это фиксирует.
Честная формулировка: доказывается совместимость с **содержимым live-таблицы**, а не с «провайдером»; для прода это эквивалентно (запись была закрыта гейтом `_vec_write_allowed`, все 16 003 вектора — старые).

## 2. Блокеры

### B1. `BLOCKER` — пауза «до вердикта» не переживает рестарт: доказанная несовместимость не возобновляет сборку
`services/embedding_control_plane.py:3504-3505` (пауза при insufficient), `:3489-3497` (resume только при incompatible), `:3385-3396` (`_resume_rebuild_under` требует членства в process-set `_PAUSED_BY_COMPAT`), `services/graphrag_rebuild.py:2191-2192` (`_ensure_job` для `paused` → `None`, «явная пауза — не авто-возобновляем»), `:2251-2257` (`pause_rebuild` пишет `reason_code="paused"`, неотличимо от операторской паузы).

Сценарий (воспроизведён на реальной SQLite+sqlite-vec, скрипт `OPENCODE_WORKFLOW_SCRATCH/probe_pause_restart.py`, вывод):
`job=running` → insufficient(`api_unavailable`) → `job=paused` → **рестарт** (`reset_compat_state()`, `_PAUSED_BY_COMPAT=set()`) → incompatible(`low_hit5`) → `job` остаётся `paused`; `maybe_schedule_rebuilds()` → `[]` и на обычном, и на `include_failed=False` тике; `generation_status` при этом показывает `build_in_progress`, `reindex_required=True`, `action=controlled_migration`.
Итог: индекс навсегда FTS-only, панель врёт «сборка идёт», автопродолжения нет (единственный вызов `resume_rebuild` — внутри `_resume_rebuild_under`; API-роута нет). Нарушены source §3 («обеспечить безопасное возобновление после сбоя или рестарта»), DEC-15 и шов сценариев 7/9. Рестарт в окне «insufficient» реален: это первый же деплой/перезапуск при недоступном API.

**Минимальная коррекция:** отличать compat-паузу от операторской (параметр `reason_code="compat_pending"` в `pause_rebuild`), а `_resume_rebuild_under`/ветку incompatible возобновлять при `reason_code='compat_pending'` даже после рестарта (сейчас — только при членстве в `_PAUSED_BY_COMPAT`). Один тест: pause → `reset_compat_state()` (рестарт) → incompatible → job `queued|paused_*`, `maybe_schedule_rebuilds()==[index]`, live-счётчик неизменен.

### B2. `BLOCKER` — приёмочный реестр не связан с кандидатом и пуст по доказательствам
`requirements-map.json`: `candidate_commit=""`, все 43 `items` + 29 `additional_requirements` — `PENDING`, `evidence=[]`.
`py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --map plans/features/embed-identity-compat/requirements-map.json --stage review --slice IDENT-SPLIT --candidate 30a2f868` → `FAIL: candidate mismatch`, 7× `mandatory not ['VERIFIED'] (got PENDING)`, exit 1. Это относится ко всем слайсам.
Дополнительно: `ACC-10` в карте `live_required=false`, хотя план (`plan.md:36`) и source §6.10 требуют **реальную** семантическую выдачу — фикстура на 8-мерных sha-векторах доказывает механизм, но не реальную семантику.
**Минимальная коррекция (PM/Builder, без переписывания кода):** `candidate_commit=30a2f868…`; на каждый `required` — evidence с `artifact_path` (report.md/тест) и статусом; `ACC-10` разделить: механизм — `VERIFIED` (тест), реальная семантика — `READY_FOR_LIVE` (A0 hit5/mean); `ACC-11` — `READY_FOR_LIVE` до пост-деплой проверки; затем перезапустить review-гейт.

### B3. `BLOCKER для деплоя (не код)` — A0-рецепт не проверяет решающую ветку
`evidence/report.md:224-229` предлагает только `ecp.compat_probe(...)`. Проба **не читает реестр** и вернёт `compatible` даже если `resolve_index_compat` на проде даст `incompatible`: `generation_space_identity(row)` требует непустые `model/dims/preprocessing_version` (`:2522-2534`), а расхождение MSI или NULL-`preprocessing_version` в строках от 29.09 даёт `incompatible` → `ensure_current_generation` зарегистрирует target и запустит полную перевекторизацию (`graphrag_rebuild.py:1748-1797`) — ровно то, что запрещено ТЗ. Тогда A0 отчитается «compatible», а деплой перестроит индекс.
**Минимальная коррекция:** A0 на read-only копии прод-БД дополнительно фиксирует `resolve_index_compat(db, 'graph_facts_vec', 'smart_archive').state/reason_code/space/candidate.generation/fingerprint` и колонки строки (`model/dims/preprocessing_version/status`). Ожидаемо: `insufficient(compat_not_proven)`/`compatible`, **не** `incompatible`/`no_generation` по space-mismatch. Если state=`incompatible` — деплой не решает P0; нужно решение по провенансу, а не «перестроим».

## 3. Что проверено и подтверждено (кандидат)

* **IDENT-SPLIT.** MSI без host (`:2495-2519`), PCI отдельно (`:2550-2574`), `profile_identity`→PCI (`:2254-2263`), `classify` + `ADMITTED_COMPATIBLE` (`:2266-2303`). Legacy `embedding_identity_fingerprint`/`_identity_fingerprint`/`_embed_cache_*` в дифф не входят (сверено по `git show`), ключи кэша не менялись.
* **Пороги** (`:2446-2457`): compatible `≥8/0.995/0.990/0.80`, incompatible `dim|0.970|0.940|0.40`, полоса 0.970–0.995 → повтор, api/мало данных → `insufficient`. Для «не смешать пространства» достаточно: другая модель даёт mean≈0.15 (тест/фикстура), min≤0.990 ловит единичный выброс, hit5 проверяет саму выдачу; полоса консервативно уходит в повтор/insufficient. Ложный adopt возможен лишь для near-identical варианта (напр. квантование) и ограничен hit5 + откатом.
* **ADOPTION** (`database.py:6164-6238`): одна `serialized()`-транзакция, проверка чужого ACTIVE и непарсимого `config_revision`, `status='active'`, `activated_at`, `config_revision=adopt1:…`, `fingerprint/provider/endpoint` не перезаписываются, идемпотентность; `supersede_building_generations(keep=fp)`, `cancel_rebuild` после adopt (`ecp:3511-3567`); kill-switch env-only (`:2471-2483`).
* **INTEGRATION.** Один вердикт читают `_index_generation_ok` (`summary_memory.py:1937-1978`), `_vec_write_allowed` (`:2038-2063`), гейт `_register_index_generations` (`:1868-1883`), inline-проба в `initialize()` до backfill/recovery (`:1752-1764`), `ensure_current_generation` (`:1731-1745`), `maybe_schedule_rebuilds` (тик, `:1986-2013`), `generation_status` (`:1830-1886`), панель (`ecp:2057-2090`) и аддитивный `compat` в `GET /api/memory/embeddings` (`web/api/memory_agi.py:540-590`). URL-сравнения в гейтах не осталось (`_index_generation_ok` не сравнивает endpoint).
* **5877810d.** A→B→A и `build_failed` не сломаны: тест переведён на реальную смену модели (`test_graphrag_identity_reindex.py`), `resume_rebuild` TypeError исправлен (`graphrag_rebuild.py:2270`), allowlist tx-supervisor +1 обоснован новым serialized-методом (тест зелёный).
* **ΔDDL=0**, новых таблиц/сервисов/реестров/агентов нет; хардкода под API.NET/Gemini в логике нет (`apinet` встречается только в тестах), провайдер-агностично.
* **Сценарии 1–10 (механизм):** 1,2a,2b,3,4,5,6,7,8,9 — тесты моделируют заявленное на реальной SQLite+sqlite-vec, мок только HTTP-embed: 1 adopt+нет job/поколений, 3 same-name/different-space→`incompatible`+target, 5 API fail→insufficient без изменений реестра/live, 6 flip-back без вызова `embed_fn`, 8 оба `chat_id` и один adopt, 9 running job→`cancelled`+target `superseded`+live неизменен, 10 — search-level KNN (`hit5=1.0`) и контроль «чужое пространство».
* **Прогоны (независимо, этот кандидат/HEAD):** `tests/test_embed_identity_compat.py` — **20 passed**; смежный набор (asap5 identity, asap6 generations, graphrag identity, webapp memory API, tx-supervisor, новый файл) — **107 passed**; полный `pytest -q` — **15277 passed / 39 skipped / 7 failed**. Все 7 — `assert 37 == 35` (`test_t5150_startup_migrations_round1046` ×5, `test_asap7_direct_settings` ×2): v36/v37 введены 17–20.10 (до кандидата), кандидат DDL не меняет → pre-existing. Два «midnight-UTC флейка» из отчёта у меня прошли и standalone (`2 passed`), т.е. классификация правдоподобна; расхождение с отчётом (15274/9) объяснимо этими двумя тестами.

## 4. Неблокирующие замечания (не расширять scope)

1. Полоса-повтор на маленькой БД: при ≤6 строках на чат `order[::stride][:6]` не зависит от offset → повтор берёт те же id → `independent_sample_unavailable` → `insufficient` (безопасно, но adopt не случится и при реально совместимых векторах). Прод (16 003) не затронут.
2. `generation_status`: при невозможности импорта модуля `ecp=None`, а в цикле `ecp.STATE_*` → AttributeError внутри общего try (пустой снимок). Чисто защитная ветка.
3. `compat`-блок панели строится по строкам `task_jobs(kind='graphrag_rebuild')`; если терминальные job'ы когда-либо начнут пруниться, панель потеряет метрики (сейчас планировщик `prune` не вызывает).
4. `plan_embedding_change` остался на legacy-сравнении fingerprint и после adopt вернул бы `REINDEX_REQUIRED`; production-вызовов нет (только экспорт) — если подключат к UI, будет расхождение с единым вердиктом.
5. Startup добавляет один embed-батч (≤12 текстов) до backfill; при недоступном API — штатные таймауты executor'а (задержка старта, не потеря данных).

## 5. Можно ли деплоить

**Сейчас — нет.** После (а) фикса B1 + теста рестарта, (б) обновления карты/гейта B2, (в) A0 с проверкой `resolve_index_compat` (B3) — деплой объединённого поезда допустим; `ACC-11` и реальная семантика `ACC-10` остаются `READY_FOR_LIVE` до пост-деплой проверки (`GET /api/memory/embeddings` → `compat.serviceable=true`, `canary.mean/min/hit5`, `generation.state`, лог `EMBEDDING_COMPAT_ADMITTED`, backfill 4048→0), с откатом «снять допуск» (`status='building'`, `config_revision=NULL`).

**Остаточные риски:** R2 ложный adopt (ограничен порогами/hit5, обратим); провенанс live до A0 не подтверждён (B3); тихая пауза сборки при insufficient (по дизайну, теперь без риска застревания после B1); зависимость панели от job-строк.
