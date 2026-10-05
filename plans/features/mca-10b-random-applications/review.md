# MCA-10b `mca-10b-random-applications` — review.md (@Reviewer, gate T-5063, 06.10.2026)

## Вердикт: **Approved** (финал; история: Needs Fixes → Approved после rework F-1/F-2 — см. Addendum в конце документа)

Один ограниченный rework: пост-селекшен-обработка в `after_sleep_direction` — честность исхода
+ закрытие trace-run + обработка зависших queued exploration-job (F-1/F-2 ниже, одна зона,
`services/mca_exploration.py` + `services/dream_worker.py`, ~30-50 строк + 1-2 фикстуры).
Остальная дельта (контракт/purposes/DDL v30/каталог F8/UI-блок/kill-switch) соответствует
санкциям и приёмкам и утверждается в составе текущего состояния — после фикса F-1/F-2
перепроверяется только затронутый район (блоки A–D 10b + 2 репро ниже).

## Биндинг

- HEAD: `897ce4fbe49370369c49fa614590ea608b3c12bd` (uncommitted working tree, без stage).
- Манифест: `plans/reports/mca10b_wth_manifest_review.txt` — 82 файла,
  **WORKTREE_SHA256: `ac9a499af959a31446807c023f2c7c14b073f6a91016354553ed40e6c7b06cc0`**
  (пересчитан и сверен в конце ревью — совпадает).
- Исключения из манифеста (по рецепту): `plans/workflow_state.md` (process journal,
  Orchestrator), `plans/docs/mca-round1027-arch-frames.md` (foreign WIP),
  `plans/verification_cache.json`, `node_modules/*`, `.playwright-mcp/*`, `package.json`,
  `package-lock.json`, `tools/_ui_asap43_*` (мусор/foreign WIP), сам файл манифеста.
- `plans/current_task.md` — НЕ изменён (git status чист по файлу). Другие feature-папки не тронуты.

## Блокирующие находки

### F-1 (Medium-High, блокирует) — нечестный исход события + незакрытый trace-run при пустом результате selection
- **Где:** `services/mca_exploration.py:606-626` (`after_sleep_direction`, хвост после
  `spec.select_and_enqueue`).
- **Что:** `select_and_enqueue` возвращает `{"status": "not_run", "reason": ...}`
  (`range_occupied`, `no_periods`, `fully_covered`, `no_beliefs`, `no_context_episode`,
  `no_eligible_alternative`) или `deferred` (draw провайдера недоступен) — но направление
  безусловно эмитит `random_uses_background` c `outcome=success`,
  `reason_code=exploration_accepted` и `merged.status="enqueued"`, хотя job не создан.
  При этом `trace_finish` в этой ветке НЕ вызывается — run `mca_pipeline_runs`
  остаётся `running` (временно виден как `stalled` по heartbeat, финального исхода нет).
- **Воспроизведено** (мои репро, см. «Что я запускал» п.9): selection вернул
  `not_run/range_occupied` → событие `outcome='success' / 'exploration_accepted'`,
  entity.status='not_run'; список событий — `PIPELINE_START` + 2×`random_uses_background`,
  БЕЗ finish.
- **Нарушает:** spec §11 («честный итог», честный `not_run`), §14.5 (п. «Проверка результата»:
  по trace виден полный переход), §14.11 (не имитировать события) — витрина маппит
  `success` → «выполнено», владелец видит ложное «выполнено/принято» при пустом исходе.
  Усугубляется F-2: при зависшем job чатвидит «accepted» вечно.
- **Исправление (bounded):** ветвление по `(outcome or {}).get("status")`:
  `selected` (+job_id) → текущий путь; `not_run`/`deferred` → `outcome=skipped|silent`
  с фактическим reason (`exploration_not_used`/`exploration_deferred`), `status` не
  переписывать на `enqueued`, вызвать `trace_finish` с честным итогом.
- **Наименьшая перепроверка:** блоки A–D 10b + репро F-1.

### F-2 (Medium, блокирует; compounding к F-1) — зависший queued exploration-job навсегда блокирует archive_sample чата
- **Где:** `services/mca_exploration.py:868-873` (`_uncovered_range`, busy-check) +
  `services/dream_worker.py:1516-1530` (execute-шаг), `services/task_supervisor.py:547-569`
  (`recover_stale` — только `running`).
- **Что:** окно между `store.enqueue(...)` (job = `queued`) и `mark_running` в
  `execute_*_job`: крэш/рестарт/транзиентная ошибка до `mark_running` оставляет
  `queued`-job навсегда — `recover_stale` чистит только `running`, `prune` сохраняет
  queued/running, повторного исполнителя queued `exploration.*` нет (hook запускает
  исполнение только сразу после постановки). Busy-check `_uncovered_range`
  (`coalesce_key LIKE 'exploration:<chat_id>:%' AND status IN ('queued','running')`)
  матчит осиротевший job → возвращает `None` → `range_occupied` → archive_sample
  для этого чата не выполняется НИКОГДА (belief_review/association не затронуты).
  Рестарт не дублирует job (требование выполнено), но требует восстановления живости.
- **Воспроизведено** (репро F-2): chat7 без job → диапазон (1,3); после постановки
  queued-`exploration.archive_sample` (чужой/старый run) → `_uncovered_range` = None;
  chat8 в той же БД → нормальный диапазон.
- **Исправление (bounded):** в `_maybe_random_uses_after_sleep` (или в начале
  `after_sleep_direction`) — разбор exploration.* job'ов прошлых незавершённых прогонов:
  завершить их честным терминальным статусом (`failed`/reason `exploration_deferred`)
  либо исполнить; либо сузить busy-check до job'ов актуального прогона. Плюс фикстура:
  «осиротевший queued exploration-job прошлого прогона → следующий выбор диапазона
  работает».
- **Наименьшая перепроверка:** репро F-2 + блоки B/D 10b.

## Неосновные (non-blocking) находки / notes

- **N-1 (related-nonblocking, Medium):** `select_memory_recall_candidates`
  (порог допуска по версии ранжирования, канонический dedup, предпочтение давних),
  `delivery_pending`-подавление и `is_repeated_phrase` реализованы и покрыты фикстурами
  (блоки B/C), но в живом разговорном пути НЕ вызываются — живой draw `memory_recall`
  работает по story-кандидатам, уже присутствующим в пуле mca-09, а штамп
  `last_used_in_chat_at` (корректно — после фактической отправки) и
  `delivery_unknown` в `handle_initiative` подключены. Discovered-лимит задокументирован
  Builder'ом («известный предел part-1»); приёмки A30 — фикстурные, исполнены. → backlog:
  подключить селектор к живому пути или явно зафиксировать演进 в следующих срезах.
- **N-2 (unrelated/pre-existing, доказано на чистом HEAD через worktree):**
  1) `test_webapp_status_control.py::test_status_public_for_all_roles` — падает на HEAD
  (пин top-level `set(body)` без `experience`/`intents`; 10b добавляет `random.uses.*`
  ВНУТРИ блока `random`, пин не затрагивает);
  2) 4 × `test_webapp_js_unit` hotfix7–10 — падают на HEAD: `tests/js/round1025_hotfix{7,8,9,10}_*.js`
  пиннят `APP_VERSION = "2.58.59"` (`tests/js/round1025_hotfix7_...js:311` и соседи)
  против фактического 2.58.60;
  3) pollution `test_mca09_intents_block_e::test_registry_process_intent_initiative`
  после mca-17a — воспроизводится на чистом HEAD (1 failed при совместном прогоне).
  → классификация: acceptable-with-note / backlog @Orchestrator, вне среза 10b.
- **N-3 (info):** предупреждение «closed 7 leaked aiosqlite connection(s)» в блоках 10b —
  тестовое окружение, не прод-путь; не блокер.
- **N-4 (info):** spec §11 ссылается «§27.1 :1355» строку матрицы виджетов — в
  `plans/ARCHITECTURE.md` строки «Случайность и её применения» нет; контрактная половина
  (process `random.uses` с `widget_id` в реестре) присутствует, рендер — зона mca-17c
  (как и заявлено). Несоответствие номера строки/ссылки — на @Architect при merge §121.

## Ответы на контрольные точки (1-16)

1. **R5 контракт** — ✅. `ExplorationRequest/ExplorationResult` (`mca_exploration.py:116-163`),
   lifecycle-константы; purposes ровно +5 в ЕДИНСТВЕННУЮ карту 10a
   (`mca_random_source.EXPLORATION_PROBABILITY_KEYS`, верифицировано импортом — 7 purpose,
   2 существующих probability-ключа); `ui_replay` — read-only маркер (`choose()` отвергает
   неизвестный purpose; фикстура `test_ui_replay_creates_no_draw`); source of draw один
   (`RandomSourceService`, `get_source`), второго сервиса/координатора/таблицы Request/Result нет.
2. **R5 one-choice** — ✅. `choose_conversation_alternative` — одна probability-проверка
   (фикстура `test_one_check_one_draw_A29`), memory-история → один дополнительный РАВНОМЕРНЫЙ
   `memory_recall`-draw (выборка, не вторая проверка); пустой пул → `no_eligible_alternative`
   без draw; LLM ради альтернатив не вызывается (пул = готовые кандидаты + статические формы);
   интеграция в `handle_initiative` через контракт mca-09 `decide_initiative(random_choice=…)`
   (сигнатура mca-09 не менялась — проверено `mca_intents.py:342`).
3. **R5 background** — ✅ с F-1/F-2. Hook только после обычного пакета сна (`tick`/`run_once`);
   максимум 1 job; уникальный coalesce-ключ `(chat, run, type)`; lifecycle-события; без
   рекурсии; FIFO основного прохода by construction (отдельный kind `exploration.*`,
   основной worker ходит только `episodes.backfill` — `mca_episode_jobs.py:40`); рестарт
   не повторяет. Дефекты хвоста — F-1/F-2.
4. **R6 memory_recall** — ✅ механизм, ⚠️ живой wiring (N-1). `retrieve()` строго;
   релевантность → разнообразие (`no_relevant_memory` до ротации давности); порог =
   `RANKING_ADMIT_SHARE` по версии ранжирования, неизвестная версия → fail-closed
   `insufficient_evidence`; dedup по canonical ID (redirect-резолв);
   `last_retrieved_at` ≠ `last_used_in_chat_at` (v30; штамп только после `sent`,
   `direct_chat_service.py:6455-6465`); `delivery_unknown` отдельный код; прямой запрос —
   обычный поиск (exploration только в инициативном пути).
5. **R7 archive_sample** — ✅ механика выбора с F-2. Существующий resumable worker, coverage
   map (`mca_archive_coverage`, merge-MAX upsert), нижняя группа → равномерный draw периода →
   непроверенный диапазон по стабильным ID; random OFFSET отсутствует; гейт «всё покрыто» ДО
   draw (THR-13); основной cursor не двигается (фикстура cursor-untouched); пустой результат
   отмечает диапазон (R7c — на исполнении, `merge_coverage`); платежи/занятые диапазоны
   исключаются — но см. F-2.
6. **R8 belief_review** — ✅. Изменённые источники — существующая RevisionQueue (вне random);
   выбор: старшая группа `last_reviewed_at` (NULLS FIRST), ожидающие и `protected_facts`
   исключены, ядро личности структурно вне выборки (derived graph_facts); исходы
   kept/narrowed/split/disputed (+ replaced только через существующий supersede-путь);
   отсутствие контрпримера не повышает confidence (weight/счётчики не трогаются);
   `material_refs_hash` → `kept` + `belief_review_unchanged` (durable v30).
7. **R9 associations** — ✅. Конечный набор (cap ≤ 8), сторона B строго `retrieve()`,
   разные canonical ID (redirect), topic-overlap, обе стороны резолвятся; LLM-классификация
   (не random), LinkType + basis + версии сторон; v30 `mca_associations`
   candidate/accepted/rejected/stale; rejected = кэш попытки по версиям; stale по редакции
   версии; не склеивает истории (EpisodeService-правила единственные), в досье/убеждения не
   попадает; accepted — кандидат координатору, прямой отправки нет; атрибуция v22 не тронута
   (файлы mca-22 вне дельты).
8. **R10 conversation_variant** — ✅. Формы на этапе Decision (`build_conversation_form_candidates`
   в `handle_initiative`, только при allowed); выбор в общей процедуре §3 (одна проверка);
   verbalizer/вербализация — контракт mca-09 (`selected_candidate.communicative_intent` +
   цель/длина/предмет на объекте формы; глубокой Stage-2 интеграции нет — disclosed предел
   среза, зона mca-09 не тронута сверх sanctioned point); раскрытие: форма в событии (enum) +
   `candidate_actions` с причинами; в чат без меток (в текст ничего не добавляется).
9. **R11 visualization** — ✅. Живая лента внутри СУЩЕСТВУЮЩЕЙ карточки `data-random-source`
   (`web/index.html:5344+` внутри template блока; второго виджета/маршрута нет); бэкенд —
   read-only проекция `mca_events` (`random_uses*`), bounded 20, event-key cursor, chat scope
   (restricted для чужих), ANU/PRNG по фактическому `actual_source`, отклонённые показаны
   отклонёнными; никаких QRNG/LLM на открытии/повторе (фикстуры + whitelist-проекция);
   пауза/reduced-motion/текстовая альтернатива/сохранение скролла — в app.js; master/`ui_visualization`
   OFF → `enabled:false`, статичный блок 10a остаётся. Персональные детали/ключи/сырой контекст
   в проекции отсутствуют (scalar-whitelist.details).
10. **Observability** — ✅ с F-1. Процесс `random.uses` v1 + стадии lifecycle в реестре
    (`PipelineVersion` + `ProcessDefinition`, `_GATE_RESOLVERS` подключён); reason-кодов
    ровно +10, единый словарь 247 (проверено); trace `mca_pipeline_runs` сквозной
    (с оговоркой F-1b о незакрытом run в одной ветке); OFF → честный `not_run`/`disabled`
    (виден в моей проверке master-OFF); строка матрицы — контрактом реестра (рендер mca-17c).
11. **Catalog/F8** — ✅. REGISTRY 510 (+6 `memory.random_uses_*`, группа `memory_random`),
    GROUPS 108, TABS 106, TAB_RULES 21, categorized 485, memory.random_uses_* = 6, секреты 32
    (0), Settings 441 (0), Δ routes = 0 (web/api/routes.py не менялся, sha256 файла
    `efcbc457…8dea90f2` — совпадает с заявленным `ROUTES_SHA256_F11`); F8 `--check` EXIT=0
    («CHECK OK: реестр 510 == REGISTRY…»); meta: delta 411→510 = 99; тул переиздания
    (`tools/_mca10b_reissue_f8.py`) парсит счётчики из вывода генератора (errata-урок 10a
    соблюдён).
12. **Δ DDL v30** — ✅. `MigrationStep(30, "random_uses")` + `_migrate_random_uses_v30`:
    ALTER `mca_episodes` (+2 колонки + индекс `idx_mca_episodes_last_used`), CREATE
    `mca_associations` (3 индекса) / `mca_archive_coverage` (PK = санкционированный idx) /
    `mca_belief_reviews` (+idx); guard-семантика (ALTER под `PRAGMA table_info`, CREATE под
    `sqlite_master`); идемпотентно (фикстуры fresh/idempotent + v29→v30 симуляция с backup
    read-back user_version=29); census-allowlist mca-01: 171→176 commit-сайтов (обосновано,
    L-MCA14-3); PG no-op (SQLite-only контур).
13. **OFF parity (re-check сам)** — ✅. Master OFF: мой независимый прогон —
    `choose_conversation_alternative` → `(None, disabled)` без draw (source не вызван),
    `after_sleep_direction` → `{"status":"disabled"}`, `random_uses_snapshot` →
    `{enabled:false, events:[]}`, 0 событий, 0 trace-стартов — бит-в-бит 2.58.60;
    per-use OFF (master ON): draw нет, ровно одно честное `disabled`-событие (+ закономерный
    PIPELINE_START от живого trace при master ON — не шум); trace_start после master-гейта
    (incidental Builder-1 закрыт и виден по коду `mca_exploration.py:341-346`).
14. **Pre-existing reds** — все три класса воспроизведены на чистом HEAD `897ce4f` через
    worktree (см. N-2) и НЕ являются дельтой 10b: классификация acceptable-with-note /
    backlog @Orchestrator. Дельта их не ухудшает (пин status-теста не затрагивается).
15. **R17** — ✅. События — только ID/коды/enum/числа (entity `_short`, whitelist-проекция);
    ключи ANU/секретов в снапшоте/событиях нет конструктивно; basis ассоциации — только в
    v30-таблице, в события не идёт; промпт классификации (light summaries) — внутренний LLM-вызов,
    не журнал; grep по emits — без сырых текстов; `plans/current_task.md` не тронут.
16. **Перепроверки выполнены** — см. «Что я запускал»; RED-чек на worktree HEAD подтверждён
    (сборка новых тестов падает: модуля нет), зависимые пины обновлены в дельте и зелёные.

## Что я запускал (точные счётчики; `.venv\Scripts\python.exe -m pytest … -q`)

1. 10b блоки A+B+C+D: **55 passed** (17/13/16/9).
2. 10a блоки A,B,D,E: **56 passed**; блок C: **22 passed** (Σ 10a = 78 — совпадает с клеймом).
3. mca-09 blocks A+B + off_parity: **33 passed**.
4. `test_round1025_f8_registry + test_param_catalog + test_frontend_tab_mapping +
   test_budget_guardrails_round1024 + summary_l1 TestCanon`: **134 passed**.
5. mca-06 sleep DE + mca-17a observability: **109 passed**.
6. webapp_status_control + webapp_parity_smoke: **28 passed, 1 failed** (pre-existing, N-2).
7. F8 `--check`: **EXIT=0 (510)**.
8. RED-чек (worktree `897ce4f`): 4 новых тест-файла — **collection error** (нет
   `services/mca_exploration.py`); pre-existing: status_roles **1 failed**; hotfix7-10
   js_unit **4 failed**; mca-09↔17a pollution **1 failed** — все на чистом HEAD.
9. Мои репро (временные тесты, удалены после прохождения): F-1 подтверждён
   (success/accepted при not_run + нет finish), F-2 подтверждён (orphan queued job →
   `uncovered_range=None`, контрольный чат — норм). Master/per-use OFF — мои тесты:
   **2 прогн. (master OFF ✓, per-use OFF ✓)**.
10. Структурные проверки импортом (single run): REASON_CODES 247 (+10 subset), KILL_SWITCHES
    73, REGISTRY 510 / GROUPS 108 / TABS 106 / RULES 21 / categorized 485 / secrets 32 /
    Settings 441; purposes карта = ровно +5; routes sha `efcbc457…dea90f2`.

Перепроверка master-ключа (п.13) выполнена мной отдельно, не через Builder-фикстуры.

## Остаточные notes

- Live T-5065 (реальный чат: применения/визуализация на проде) — **[PENDING OWNER]**,
  post-deploy; до live приёмку применений на проде не заявлять (spec §13.7).
- UI-ревью: A35-фикстуры (python) + код-ревью app.js/index.html; Playwright-vs-real-TMA -
  в зоне live-гейта T-5065 (post-deploy), не блокирует код-гейт.
- Deploy: per spec §13.6 — CA-11 bump 2.58.60→2.58.61, мягкий откат `MCA_RANDOM_USES_ENABLED=false`.
- N-1: подключение селектора memory_recall к живому пути — кандидат в задачи следующего
  среза (не блокер текущего гейта: приёмки A30 фикстурные, исполнены; предел disclosed).
- Повторный пересчёт манифеста после ревью совпал: `ac9a499a…` — ревью привязано одному
  состоянию дерева.

---

## Addendum: F-1/F-2 resolved — rework recheck (@Reviewer, 06.10.2026)

**Итог расширения вердикта: `Needs Fixes` → `Approved`** (финальный вердикт документа).

### Изменение (scope-контроль)
Манифест дельты поверх биндинга итерации 1 сверлён хэш-в-хэш: изменились РОВНО 4 файла —
`services/mca_exploration.py` (F-1 ветвление по статусу selection + `close_stale_queued_explorations`),
`services/dream_worker.py` (вызов cleanup до direction, fail-open), `tests/…block_c…` (+4 фикстуры:
`test_F1_selection_not_run_honest_outcome`, `test_F1_selection_deferred_honest_outcome`,
`test_F2_stale_queued_job_released`, `test_F2_hook_closes_stale_before_direction`),
`plans/features/mca-10b-random-applications/evidence.md` (rework-заметки). Посторонних правок нет;
все прочие файлы биндинга итерации 1 — байт-в-байт.

### Проверка фиксов
- **F-1 (код + мои независимые репро):** `selected` → `success/exploration_accepted` +
  `trace_finish(succeeded)` + `enqueued` (happy path не регрессировал); `not_run` →
  `skipped/exploration_not_used` + `trace_finish(succeeded)`, статус результата остаётся
  `not_run` (без перезаписи в `enqueued`), причина (`range_occupied` и др.) сохранена в entity —
  витрина покажет «пропущено»; `deferred` → `skipped/exploration_deferred` +
  `trace_finish(partial)`. Run закрывается на каждом пути (проверено подменой
  `trace_finish`/`finish_run`).
- **F-2 (код + мои независимые репро):** `close_stale_queued_explorations` (bounded: порог
  3600 с, cap 8/прогон; только `status='queued'`; `instr(coalesce_key, ':<current_run>:') = 0`
  — только прошлые прогоны) закрывает зависший job честно: `cancelled` +
  `reason=exploration_deferred` + lifecycle-событие. Зависший queued-объект старого прогона
  освобождает busy-check: `_uncovered_range` вернул `(1, 3)` после очистки (до очистки — `None`).
  Job текущего прогона не тронут (остался `queued`). Cleanup вызывается в hook до
  direction, fail-open (`dream_worker`).
- F-1/F-2 закрыты в заявленном rework-объёме; N-1 (живой wiring memory_recall-селектора) и
  pre-existing reds (N-2) остаются вне среза — в backlog @Orchestrator, вердикт не меняют.

### Прогоны (точные счётчики; `.venv\Scripts\python.exe -m pytest … -q`)
- 10b блоки A–D: **59 passed** (55 → 59, +4 фикстуры rework).
- `block_c -k "F1 or F2"`: **4 passed**.
- Мои независимые репро-фикстуры (временные, удалены после): **4 passed**
  (not_run честно / deferred честно / happy path intact / stale job released).
- Изменённый сосед: `test_dream_worker.py` + `test_mca06…DE`: **64 passed**.
- F8 `--check` после rework: **CHECK OK, EXIT=0 (510)** (каталог не менялся).
- Остальные наборы (10a/09/13/17a, webapp guards) не перезапускались: файлы вне rework-объёма
  байт-в-байт к итерации 1 — кэш PASS ревью действителен.

### Биндинг финала
- Без изменений HEAD: `897ce4fbe49370369c49fa614590ea608b3c12bd`.
- Манифест (обновлён в `plans/reports/mca10b_wth_manifest_review.txt`, ITER2, 82 файла):
  **WORKTREE_SHA256_ITER2 = `48e0c9792f7aca32c046c56628bda9eaf4ef9886dc891cee8a4dbd886bb4d385`**;
  исключения — как в итерации 1 + `review.md` (артефакт ревьюера, вне кандидата).
- Сравнение состояний: итерация 1 `ac9a499a…` → итерация 2 `48e0c979…`; дельта — ровно
  rework (4 файла), ничего больше.

### Остались вне гейта (без изменений)
- Random N-1 (wiring memory_recall-селектора в живой путь), N-2 pre-existing reds
  (status-pin, 4 hotfix-JS харнесса 2.58.59, mca-09↔17a pollution), N-3/N-4 — backlog
  @Orchestrator; блокирующими не являются.
- Live T-5065 (применения/визуализация в реальном чате) — **[PENDING OWNER]**, post-deploy;
  деплой per spec §13.6 (bump 2.58.61, soft-rollback `MCA_RANDOM_USES_ENABLED=false`).

