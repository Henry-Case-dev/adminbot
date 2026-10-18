# INC-SUMMARY-01-CODE — блокирующая цепочка pre-generation Summary + минимальный фикс

Дата: 17.10.2026. Lane: INC-SUMMARY-01-CODE (read-only анализ кода; правок/деплоя нет).
Вход: `plans/workflow_state.md:11` (гипотеза владельца), инцидент 17.10 01:00:06 (run RUNNING 48+ мин, stages 0/0, только start-event).
Прод-логи в этом lane недоступны: всё ниже — из кода с точками `file:line`; сверку с фактом делает lane INC-SUMMARY-01 (prod forensics), см. §8.

## 1. Цепочка крон → первый LLM-вызов (что чем ограничено)

| Шаг | Код | Ограничение сегодня | При сбое |
|---|---|---|---|
| Тик крона 0/6/12/18 (Asia/Yekaterinburg) | `services/summary_scheduler.py:113-122` | `max_instances=1`, `coalesce=True`, `misfire_grace_time` НЕ задан → дефолт APScheduler 3.11.3 = **1 с** (проверено в `.venv` `schedulers/base.py`: `_job_defaults["misfire_grace_time"]=asint(...,1)`) | наложение → лог `skipped: maximum number of running instances reached`, прогон НЕ ставится в очередь |
| Обход чатов (последовательно, `await` на чат) | `summary_scheduler.py:129-157` | **нет** per-chat timeout, **нет** try/except вокруг `generate_and_send` (157) | исключение/зависание чата A → чаты B..N не обработаны; следующий тик через 6 ч (или пропущен) |
| Резолвер включённости | `summary_generator.py:519` → `chat_params.get_chat_param` (`services/chat_params.py:344-351`, кэш) | не блокирует (кэш) | — |
| Пермит пула чата | `summary_generator.py:531` `try_acquire(timeout=0.0)` → **`539 await self._pool.acquire(chat_id)`** | **НЕТ таймаута** (ждать сколько нужно) | занято → ждём бесконечно; при этом `finally: permit.release()` (543) держит слот на весь run |
| Пул | `services/smartmodule_concurrency.py:90-94` | N на чат = `SMARTMODULE_CONCURRENCY_PER_CHAT` дефолт **3** (`config/settings.py:2578-2579`); пул ОБЩИЙ с youtube/web/search/factcheck/checkup/direct_chat | зависший run держит 1 из 3 слотов чата |
| Поиск прерванного run (resume) | `summary_generator.py:556-571` → `database.py:4989-5006` | «активный» = **любой** не-терминальный, самый свежий по `created_at`; фильтра устаревания **нет** | застрявший CREATED-ран вечно считается «активным» |
| `SUMMARY_RUN_START` (mca_events) | `summary_generator.py:597-602` → `services/pipeline_events.py:137-141` | fail-open (`except Exception: pass`) | отсутствие события не диагностируется |
| Durable run-row CREATED | `summary_generator.py:607` → `summary_run_store.py:139-146`, `database.py:4878-4899` | INSERT OR IGNORE | fail-open → run без durable строки |
| **Память: `compress_and_purge`** | **`summary_generator.py:611`** | **НЕТ дедлайна**: в `summary_generator.py` вообще нет `asyncio.timeout`/`wait_for` (grep: только `time.monotonic` 3717/3736/3748) | см. §2 — блокировка неограниченной длительности |
| Чтение окна | `summary_generator.py:634` → `summary_memory.py:2562-2598` → `database.py:7349-7360` | один SQL, `LIMIT` 500 (`settings.py:1869`), окно 6 ч (`settings.py:494`); ожидание single-writer lock — без таймаута | при исключении → ветка `_SQLITE_ERRORS` (706) |
| Snapshot окна + SOURCE_READY | `summary_generator.py:667` → `747-799`; `summary_source_window` write-once; `set_state(SOURCE_READY)` (790-794) | fail-open | snapshot не записан → resume деградирует к перечитке |
| Первый LLM-вызов (hybrid/legacy) | `summary_generator.py:679-700` | **есть** hard fuse: `summary_llm_supervisor.py:753-758` `asyncio.timeout(fuse)`, fuse=3600 с, clamp [600,7200] (`settings.py:1090-1091`) — но это per-call, не на run | LLMError → терминал FAILED |

Итог: до первого LLM-вызова **три** шага без верхней границы по времени — пермит-ожидание (`539`), обслуживание памяти (`611`), и неявное ожидание single-writer lock на записях окна. Первая durable stage-строка появляется только глубоко в пайплайне (`summary_generator.py:1655/1998/2052/...`), поэтому у застрявшего рана в `summary_run_stages` **0 строк** — это и есть наблюдаемые «stages 0/0».

## 2. `_compress_purge_extract_only`: структура и деградация embeddings

- Вход: `summary_memory.py:4802-4846`. Сначала шаг импорт-retention (4821-4843) — env-гейт `IMPORT_RETENTION_ENABLED` (дефолт OFF) + dry-run гейт `auto_purge_dry_run` (`memory_maintenance.py:935`), т.е. на прод-дефолте это подсчёт, а не удаление. Далее `hot.get("memory.infinite_retention", settings.INFINITE_RETENTION)` (4844) → **`_compress_purge_extract_only`** (4845-4846).
- Тело: `summary_memory.py:4910-4996`. `cutoff = now − FULL_MEMORY_RETENTION_DAYS(30)` (4937-4941), `batch_size = limits.summary_compress_batch` дефолт **100** (`settings.py:1874`), флаг графа (4946; дефолт ON `settings.py:1983`).
- Цикл: `while True` (4956) → `db.get_smart_raw(..., exclude_imported=True, exclude_processed=True)` (4957-4959; `database.py:7362-7383`, partial-index `idx_smart_messages_history_pending` `database.py:6571-6573`) → `_extract_and_save_graph` (4964) → маркер `mark_smart_messages_processed` (4988) → выход **только** если пачка короче batch (4990-4991).
- **Спин невозможен, но и верхней границы нет**: исключение → `break` (4974-4985, батч сохраняется), `GraphExtractDropped` → маркер+continue (4965-4973), успех → маркер (4988). Прогресс монотонный (маркеры), но число итераций = backlog/100 **без капа** и без общего дедлайна → длительность = f(размер очереди × латентность провайдера).
- Стоимость батча: `_extract_and_save_graph` (5085-5217): хвост 8000 симв. (5105; `_GRAPH_EXTRACT_MAX_CHARS` 753), чанки ≤3 × 4000 (`5125`, `796-801`, `settings.py:1998-2001`), на чанк `llm.generate_background(deadline=120 с, max_attempts=2)` (5137-5145; `settings.py:2003-2006`) — каждый `_post` жёстко ограничен `asyncio.timeout(call_budget)` (`llm_client.py:798`, budget=deadline `1353`). Потолок батча ≈ **3×120 = 360 с**; при «здоровом, но медленном» провайдере батчи идут по 100-360 с. 48+ мин ≈ 8 батчей по полному таймауту или 50-140 батчей по 20-60 с (backlog ≈ 5-14 тыс. live-строк старше 30 дней). После 3 подряд полных фейлов батч явно отбрасывается (5194-5208).
- Локи/транзакции: `_write_graph_triplets` (5034-5083) пишет под общим single-writer `db.serialized()` (5045) в одной транзакции BEGIN..COMMIT (5046-5076) — **сеть внутри лока не держится**; но `except Exception` (5077) не ловит `CancelledError`/`BaseException` → отмена внутри блока оставляет открытую транзакцию на общем соединении. `mark_smart_messages_processed` (`database.py:7848-7865`) пишет **без** single-writer лока (прямой execute+commit).
- Второй (не-infinite) контур: цикл 4857-4893 — прогресс зависит от фактического `delete_smart_messages_by_ids` (4890, вне try); guard'а «пачка не изменилась» нет (кандидат на спин при молчаливом no-op DELETE — проверить в логах, §8).
- **Embeddings/деградированный вектор — НЕ причина**: ветка extract-only не вызывает `_embed`/vec вообще (4910-4996); при `_vec_available=False` в non-infinite ветке embedding-запись просто пропускается (4881). Контрол-плейн при `max_wait_s=None` на «припаркованной» группе падает **сразу** (`embedding_control_plane.py:870-884`; `summary_memory.py:2035` вызывает `execute_embed` без `max_wait_s`) → деградация даёт быстрый fail-soft FTS, а не ожидание. Роль вектора: только обеднение RAG-обогащения, не блокировка.

## 3. Почему не появился терминальный статус

- Терминал пишется **только** в `finally` (`summary_generator.py:715-745`): `finish_run` (719), `summary_done_from_ctx` → `SUMMARY_RUN_DONE` (737), `_durable_run_finish` → терминальное состояние + stage `run` (743, реализация 855-878). Пока задача висит на `await compress_and_purge` (611), `finally` не исполняется — **исключения/сглатывания нет, задача жива и заблокирована**; UI при этом честно выводит «в работе» из START-без-DONE (`services/pipeline_analytics.py:1731-1732`), а счётчики стадий — из пустого `summary_run_stages` (`pipeline_analytics.py:1745-1753`; `web/app.js:3719-3727`).
- Все терминальные записи **fail-open** (`except Exception: pass` 718-745; `_durable_run_finish` 877-878) — сбой БД/эмиссии оставляет ран нетерминальным молча.
- Watchdog'а для `summary_runs` **нет**: `mca_watchdog` реапает только `task_jobs` (`services/mca_watchdog.py:59-71,111-117`), а summary-run сознательно НЕ `mca_pipeline_runs` (`summary_run_store.py:6-9`); startup-recovery нет (`bot.py:467-474` — только создание и старт планировщика). Устаревание не помечается никем.
- После рестарта: следующий прогон находит ту же строку как «активную» (`database.py:4989`) → resume с тем же `run_id` (`summary_generator.py:563-569`) → окно из durable snapshot (`620-625` → `summary_legacy_fullwindow.py:103-113`); если snapshot'а нет (ран не дошёл до `_establish_source_window` — как при зависании на 611) → `resumed=False`, свежая перечитка (`631-634`). Потери данных нет, но ран-ID и «running»-бейдж тянутся дальше.

## 4. Планировщик/конкурентность (последствия зависшего рана)

- `max_instances=1` + `coalesce=True` → пока тик не завершился, следующее срабатывание **пропускается** (лог APScheduler), а `misfire_grace_time=1 с` означает: если loop был занят >1 с в момент срабатывания, прогон вообще теряется как misfire.
- Тик последовательный (`summary_scheduler.py:131-157`): один зависший чат останавливает обработку остальных чатов и все последующие тики (до 6 ч × N).
- Пермит пула держится весь ран (543) → зависший run занимает слот чата; при N=3 manual `/summary` того же чата обычно ещё проходит (свободные слоты есть) — это и есть аварийный путь восстановления (§6).
- Локи БД: `get_smart_window`/`store_source_window` идут через single-writer (`database.py:2380-2413`), ожидание лока — **без таймаута**; при чужой долгой транзакции шаг окна может ждать неограниченно (второй кандидат в причину инцидента, §8).

## 5. Идемпотентность и безопасный повтор окна

- Двойная публикация **одного run_id** невозможна: `_publication_gate` (`summary_generator.py:880-949`, вызовы 2739/3283/3614) фиксирует `publication_status='publishing'` ДО отправки (`summary_run_store.py:202-227`), `published` не перезаписывается (`database.py:4938-4973`), при `publishing` — reconcile по ledger (`database.py:5008-5023`) и по content-hash текста (928-948) → `skip` либо честный retry.
- Риск дубля существует только между **разными** run_id одного чата (content-hash барьер работает лишь в ветке `publishing`): поэтому фикс не должен создавать второй живой run_id, пока владелец первого жив.
- Восстановление «пропущенного» окна — только существующим контрактом: окно = `now − SUMMARY_WINDOW_HOURS(6 ч)` (`summary_memory.py:2568-2576`; `settings.py:494`), поэтому пропуск восстанавливается **пока сообщения внутри 6-часового горизонта**: следующий крон или manual `/summary` (тот же `generate_and_send`, `handlers/summary.py:599-601`). Фактически для инцидента: manual `/summary` в ~01:48 взял бы свободный слот (N=3), прошёл resume того же run_id, опубликовал окно 00:00-01:00, а зависший ран позже был бы отсечён гейтом (`published` → skip). После ухода горизонта период в саммари уже не вернуть без изменения окна — новую «перепубликацию» не вводим.

## 6. Минимальный фикс (дизайн; кода не трогаем)

1. **Бюджет памяти кооперативно** в `_compress_purge_extract_only` (`summary_memory.py:4956`): `deadline = monotonic() + MEMORY_MAINT_DEADLINE_S` (env/hot, дефолт ~600 с) + кап `GRAPH_EXTRACT_MAX_BATCHES_PER_RUN` (дефолт ~20) + guard «та же пачка дважды → break» + INFO-событие с counts (processed/остаток/elapsed). Маркеры `history_processed` и данные НЕ меняются → докатка следующим прогоном.
2. **Жёсткий предохранитель** вокруг шага в `summary_generator._run` (`611`): `async with asyncio.timeout(MEMORY_MAINT_HARD_S)` + **явный** `except TimeoutError` ДО общего `except Exception` (710) → fail-soft skip: WARNING + durable stage `memory_maintenance` `status=skipped`, `reason_code=deadline_exceeded` (`record_stage` уже умеет reason_code/started_at — ΔDDL=0) → продолжить чтение окна. (Важно: `asyncio.TimeoutError is TimeoutError` в 3.12, это `OSError`, но не `_SQLITE_ERRORS` (137) — без явного catch ран пометится FAILED.)
3. **Ограничить ожидание пермита** (`539`): `try_acquire(chat_id, timeout=PERMIT_WAIT_S)`; таймаут → событие/лог `SUMMARY_PERMIT_WAIT` (waited_ms, outcome=timeout) + busy-UX (manual) + выход **без** создания run-row; в `_tick` — переход к следующему чату (тик не виснет).
4. **Наблюдаемость pre-gen стадий**: писать stage-строки `permit`/`memory_maintenance`/`source` со `started_at` (уже поддерживается) → вместо 0/0 видно текущую стадию; добавить `duration_ms` в `pipeline_events.source_window` (транспорт уже принимает duration_ms, `pipeline_events.py:100-113`).
5. **Закрытие устаревших ранов (рестарт без дубля публикации)**: в начале `_run` — если `prior` нетерминален, старше `STALE_RUN_S`, **без** durable окна и **без живого владельца в процессе** (in-memory набор активных run_id) → `FAILED` c reason `stale_no_window` + **новый** run_id; если окно есть — resume как сегодня (snapshot = контракт). `publication_status` не трогаем (остаётся pending), повторной отправки нет.
6. **Отменобезопасность** (нужна для п.2): `_write_graph_triplets` — rollback и на `BaseException` (`summary_memory.py:5077`), чтобы отмена не оставляла открытую транзакцию на общем соединении.
7. **Kill-switch** `SUMMARY_PREGEN_BOUNDS_ENABLED` (дефолт ON; OFF → прежнее поведение бит-в-бит) + значения всех лимитов через env/hot.
8. **НЕ меняем**: удаление/TTL памяти, данные графа/архива, окно (6 ч), каденс крона, гейт публикации, семантику `history_processed`, «слепую» перепубликацию и любой новый publish-API.

## 7. Тест-матрица (seams)

| Тест | Seam | Ожидание |
|---|---|---|
| Большая очередь GraphRAG | реальный `DatabaseService` + seed > batch×cap live-строк старше cutoff; fake `llm.generate_background` с задержкой (`tests/test_graphrag_memory.py`, `tests/test_summary_memory.py`) | цикл выходит по бюджету/капу; обработано ≤ капа; остаток `history_processed=0`; публикация идёт |
| LLM недоступен | `generate_background` → `LLMTimeoutError` на все чанки (ср. `tests/test_summary_asap_hotfix_round1027.py:185`) | батч сохранён, пайплайн продолжается, стадия/reason записаны |
| Долгая память | FakeMemory `compress_and_purge` спит > hard cap (`tests/test_summary_generator.py:59`) | публикация состоялась; stage=skipped/deadline_exceeded; ран не FAILED; пермит освобождён; терминал записан |
| Рестарт | pre-seed нетерминального рана: (a) без окна, (b) с окном (`tests/test_asap8_v63_b06_summary_scope.py`, `summary_source_window`) | (a) закрыт FAILED + новый run_id; (b) resume того же run_id по snapshot; ровно одна отправка |
| Конкурентные раны | два `generate_and_send` одного чата + permit-timeout | одна публикация на run_id (mark_publishing), при таймауте пермита — чистый skip без run-row |
| Крон | `_tick` с «висящим» чатом (`tests/test_summary_scheduler.py`) | остальные чаты обработаны, тик завершается |
| No-progress guard | DB-двойник: `get_smart_raw` отдаёт ту же пачку, маркер no-op | break + WARNING, без спина |

## 8. Риск/регресс, честный режим отказа, уточнения к гипотезе

- Ничто не зависит от завершения обслуживания памяти **до** публикации: окно — последние 6 ч, cutoff ретенции — 30 дней (пересечения нет), а extract-only ничего не удаляет (4913-4914). Единственный эффект ограничения — отставание граф/архив-обогащения.
- Честный режим отказа для пользователя: **сводка выходит вовремя, обслуживание памяти отложено с записанной причиной** (не «сводка отложена на неопределённое время» и не тихий пропуск); отставание видно по счётчику очереди (нужна метрика backlog) и решается бюджетом/каденсом, но НЕ автоудалением.
- Регресс-поверхность: OFF-ветка `INFINITE_RETENTION` не меняется; suites — `test_graphrag_memory`, `test_summary_memory`, `test_memory_retention_round1019`, `test_history_retention_toggle`, `test_summary_concurrency`, `test_summary_generator`, `test_summary_scheduler`, `test_asap8_v63_b06_summary_scope`, `test_summary_asap_hotfix_round1027`.
- Уточнения к гипотезе владельца: (a) «нет границы» — верно для **общего** времени цикла (4956-4991), но батч ограничен 3×120 с (`llm_client.py:798`), при мёртвом LLM цикл **прерывается** (4974-4985), «отравленный» батч отбрасывается через 3 фейла (5194-5208) — спина нет; проблема = медленный/частично-падающий провайдер × большая очередь; (b) «unlimited memory» важен только как источник очереди (live-строки старше 30 дней, 4957-4959); (c) деградированный вектор **не каузален** (§2) — он даёт быстрый fail-soft FTS.
- Что подтвердить/опровергнуть логами (lane INC-SUMMARY-01): наличие `graph extract`/`LLM background OK | purpose=graph_extract` после 01:00:06 и отсутствие `extract-only N messages kept`; альтернативы — ожидание single-writer lock на окне (§1/§4) или зависание main-generate; проверить, был ли рестарт процесса между 01:00 и 01:48 (тогда нетерминальная строка + resume — ожидаемы по §3).

Next: Builder-фиксу — реализовать §6 п.1-7 + тесты §7; Reviewer'у — подтвердить, что причина (неограниченный pre-generation) устранена, а не только замаскирована; после деплоя — следующий плановый прогон, публикация и терминальный статус (вне этого lane).
