# REVIEW — EMBED-REBUILD-MECHANISM (d3ba845b)

Лейн: **REV-EMBED-REBUILD** (аудит 23.10.2026). Режим: read-only; единственная запись — этот файл.
Дата: 2026-10-23 (локально UTC+12). SSH/прод не использовались (запрещено лейном).

Кандидат: **`d3ba845b4c644f602fdeaab6513aba185003bbd5`**
База: `468d1041904d024d7cffb07b92fb3d417765294d` (соседний EMBED-FALLBACK-FIX уже в базе).
Привязка: 7 файлов скоупа не менялись между `d3ba845b` и текущим master `b1525b60` (`git diff d3ba845b b1525b60 -- <7 файлов>` пусто; `b1525b60` — несвязанный summary-L2-коммит); sha256 четырёх кодовых файлов совпадают с `report.md` §10 (dee90c3d…, eaaca842…, 80349aac…, 723c7c61…). Прогоны ниже сделаны **в чистом worktree** `rev-embed-rebuild-cand` = `d3ba845b`, не в грязном master.

## Вердикт

**Needs Fixes.** В поезд **2.58.113 — пока нельзя**; после двух точечных исправлений (B1, B2) и повторной проверки — можно.

Главный прод-сценарий (hot-смена identity без рестарта: Google → apinet, реестр с чужим `building`) **работает**: новое поколение регистрируется, durable-джоба создаётся, `_activate` заменяет только live-векторы, статус `identity_changed` виден в API. Но механизм не доведён в двух реальных состояниях: (B1) повторная смена identity на fingerprint, у которого уже есть *завершённая* rebuild-джоба (A→B→A), навсегда оставляет индекс в тихом FTS-only; (B2) после терминального провала сборки честный статус врёт «build_in_progress» вместо «build_failed» (ветка `build_failed` недостижима).

## Acceptance ledger (по пунктам лейна)

| # | Пункт | Статус | Доказательство |
|---|---|---|---|
| 1a | `active` под текущий fp → no-op | **VERIFIED** | `graphrag_rebuild.py:1629-1630`; тест `test_active_current_identity_needs_no_rebuild` |
| 1b | Нет строки/терминальная строка → новое `building`, старые строки/векторы не трогаются | **VERIFIED** | `graphrag_rebuild.py:1631-1675`, `database.py:6018-6045`; тесты 1, 5, 8 |
| 1c | Пустой источник не регистрируется | **VERIFIED** | `graphrag_rebuild.py:1634-1638`; независимый probe: `empty-src scheduled=[] generations=1` (только старое поколение) |
| 1d | Идемпотентность повторного/параллельного тика | **VERIFIED** | `database.py:6018-6028` (check+insert под `serialized`), `task_jobs` unique partial; probe: 2 параллельных `maybe_schedule_rebuilds` → 1 новое поколение, 1 джоба |
| 1e | Новое поколение под fp, у которого уже есть терминальная джоба, **реально планируется** | **FAILED — B1** | `graphrag_rebuild.py:1973-1974`; probe A→B→A: `scheduled=[]`, джоба `activated`, `write_allowed=False` |
| 2 | Нет потери данных; ΔDDL=0; source/FTS не трогаются | **VERIFIED** | `_activate` не менялся (`graphrag_rebuild.py:962-1007`): DROP/CREATE только live + копия из shadow; source/FTS не в DDL; старые поколение/shadow целы (тест 2); в диффе нет `CREATE/ALTER/DROP` |
| 3 | Безопасность автостарта: lease, kill-switch, троттлинг, горизонт, нет retry-storm | **VERIFIED** (с эксплуатационной оговоркой §8) | `graphrag_rebuild.py:1117-1143` (lease), `:1774-1775`/`:480-481` (kill-switch `GRAPHRAG_SHADOW_REBUILD_ENABLED`), `:156-162`, `:226-234`, `:1808-1812` (tick `include_failed=False` не переоткрывает failed) |
| 4 | Честный статус: `active/build_in_progress/build_failed/identity_changed/no_generation` | **FAILED — B2** | `graphrag_rebuild.py:1706-1715`; `_handle_build_failure` (`:1447-1466`, `:1581-1589`) не пишет статус в реестр; probe: джоба `failed`, API отдаёт `build_in_progress` |
| 5 | Скоуп: 7 файлов, нет env/DDL/зависимостей/секретов, чужие подсистемы целы | **VERIFIED** | `git show --name-status d3ba845b`: ровно 7 файлов (код/тесты/report.md); скан добавленных строк: 0 `AIza|sk-|api_key|password|secret|environ|getenv|CREATE TABLE|ALTER TABLE`; `embedding_control_plane.py`/`llm_client.py` не менялись |
| 6 | Независимый RED/GREEN | **VERIFIED** | Числа §3 ниже |
| 7 | Incidental `compat_class` (16-hex vs 64-hex) | **VERIFIED как pre-existing, nonblocking** | `embedding_control_plane.py:2072-2080`, `:2246-2261`, `:2285-2288`; UI обязан смотреть на `generation` |
| 8 | Влияние автостарта на поезд 2.58.112/113, порядок | **VERIFIED (анализ)** | §8 ниже |

## Blocking findings

### B1 — Новое поколение под уже завершённый fingerprint не получает джобу (тихий FTS-only)

- **Требование:** «догнать identity» при любой смене fingerprint; терминальная строка под текущий fp → новое поколение **и перестройка** (docstring `ensure_current_generation` `graphrag_rebuild.py:1606-1614`; `report.md` §8: «новая будет запланирована следующим тиком»; тест 8 заявляет A→B→A).
- **Место:** `graphrag_rebuild.py:1973-1974` (`_ensure_job`: `activated`/`cancelled` → `return None`) + `:1795-1804` (после `ensure_current_generation` вызывается `_ensure_job`, результат `None` → `continue`) + `:602-613` (`_find_active_job` возвращает старую джобу по coalesce-key `graphrag_rebuild:{index}:{fp}`).
- **Сценарий (воспроизведён):** A собран и активирован (`task_jobs.status=activated`, payload generation=1) → identity B собран/активирован (A → `superseded`) → identity снова A. Тик регистрирует gen=3 `building` под A (`registry: gen1 superseded A, gen2 active B, gen3 building A`), но `_ensure_job` находит старую `activated`-джобу A и возвращает `None`; новая джоба не создаётся. Итог: `scheduled=[]`, `job=('activated', …)`, `_vec_write_allowed=False`, `generation_status=build_in_progress` — навсегда (рестарт не помогает: startup-путь либо пропускает уже существующую `building`-строку, либо упирается в ту же activated-джобу).
- **Влияние:** семантический поиск и запись векторов снова тихо деградируют в FTS-only — ровно тот класс дефекта, который лейн должен устранить. Сценарий реален: владелец переключает embedding-провайдера (в проекте уже есть `.env.bak.nanogpt*`), а после успешной сборки A возврат на A блокируется навсегда. Панель при этом показывает «идёт перестройка», хотя ничего не идёт. Сужение скоупа до одного прод-сценария (Google→apinet, старая джоба `paused`) дефект не отменяет: тест 8 и docstring уже обещают A→B→A; либо чинить, либо явно убрать это обещание и тест из отчёта.
- **Минимальная коррекция:** в `_ensure_job` при `activated`/`cancelled` (и при `failed`, если `include_failed=True`) и **целевой generation > generation из payload** — CAS-перевести джобу в `queued`, обновить payload (`generation`, `fingerprint`) и **сбросить checkpoint** (`store.save_checkpoint(job_id, cursor_token=json.dumps({"last_id": 0, "processed": 0}), processed=0, ...)`), иначе resume старого shadow. Альтернатива — coalesce-key с generation; тогда согласованно поправить `_find_active_job`/pause/resume. `run_job` уже умеет стартовать с `queued` (`:1065-1110`), менять state machine не нужно.
- **Минимальная перепроверка:** один regression-тест «build A → build B → снова A» через `maybe_schedule_rebuilds` + `run_job` (не только `ensure_current_generation`): ожидается новая джоба под A, `activated`, `_vec_write_allowed=True`, старые shadow/source целы. Мой probe: `%OPENCODE_WORKFLOW_SCRATCH%\rev-embed-rebuild\probe_flipback.py`.

### B2 — `build_failed` недостижим: после терминального провала статус навсегда «build_in_progress»

- **Требование:** `generation_status()` честно различает `build_failed` (лейн п.4; docstring `graphrag_rebuild.py:1680-1686`); лог `_index_generation_ok` различает «сборка идёт» и «identity сменилась» (`summary_memory.py:1913-1921`).
- **Место:** `graphrag_rebuild.py:1447-1466`, `:1581-1589` (терминальные ветки `_handle_build_failure`), `:1272-1288` (validation-failed) обновляют только `task_jobs`, но не `mca_embedding_index_generations`; `_registry_pause` (`:356-374`) пишет только pause-колонки. `generation_status` (`:1708-1713`) видит реестровую строку `building` → `build_in_progress`; ветка `build_failed` (`:1712-1713`) не получает ни одного продюсера (grep: `set_embedding_generation_status(..., "failed")` нигде не вызывается; миграционная машина пишет только `building_target/catching_up/ready`).
- **Сценарий (воспроизведён):** `_embed` бросает детерминированную ошибку → джоба `failed`/`ValueError`, реестр остаётся `building`; `generation_status` → `state=build_in_progress`, `_index_generation_ok` → hint «build in progress»; тик `include_failed=False` ничего не переоткрывает (`scheduled=[]`), реестр/джобы не меняются (`generations=1`, `jobs=[('failed','ValueError')]`).
- **Влияние:** после реального терминального провала (auth_invalid, validation_failed, исчерпан 24-часовой горизонт) владелец в панели видит бесконечную «перестройку» без прогресса; API в том же ответе отдаёт `rebuild` со статусом `failed` — противоречие. Это прямо противоречит цели «честный статус».
- **Минимальная коррекция:** в `generation_status` (и в hint `_index_generation_ok`) учитывать последнюю durable-джобу для `(index, latest.fp)`: `failed`/`validation_failed` → `build_failed`; отсутствие джобы при `building`-строке → не `build_in_progress` (например, `identity_changed`/`no_job`). Альтернатива — писать `failed` в реестр терминально и не регистрировать новое поколение на тике, пока джоба терминальна (`include_failed=False`); тогда нужен и B1-фикс, иначе новый `building` останется без джобы.
- **Минимальная перепроверка:** probe с `_embed`-ошибкой: `generation_status.state == "build_failed"`, нет роста поколений на следующем тике; плюс `test_generation_status_build_failed`. Мой probe: `%OPENCODE_WORKFLOW_SCRATCH%\rev-embed-rebuild\probe_failstatus.py`.

## Nonblocking / incidental

1. **`validated` в `TARGET_GENERATION_STATUSES` не планируется.** `graphrag_rebuild.py:90` включает `validated`, `ensure_current_generation` его возвращает, но `maybe_schedule_rebuilds:1803` продолжает только для `building`. Строка `validated` (теоретически возможна при сбое между CAS validate и `_activate`) будет вечно висеть без джобы. В прод-пути graphrag статус `validated` в реестр не пишется — сегодня недостижимо; либо планировать `validated`, либо убрать из target-set. Nonblocking.
2. **Пустой `smart_archive` = `no_generation` + `reindex_required=true`.** `generation_status` не знает про пустой источник (`:1700-1729`), поэтому на проде (0 фактов) панель будет вечно предлагать reindex пустого индекса. Добавить `source_empty` (REUSE `_source_empty`) или не показывать warning в UI. Nonblocking.
3. **Миграционные статусы в `generation_status`.** `building_target/catching_up/ready` попадают в `build_failed` (`:1713`), хотя это in-progress/ready. Машина миграций ASAP-6 в проде не используется — nonblocking, но при её включении статус будет ложным.
4. **Incidental п.7 — `vector_memory_panel`/`compat_class`.** `profile_identity()` возвращает 16-hex D11-отпечаток (`embedding_control_plane.py:2246-2261`), а `active.fingerprint` — 64-hex sha256 (`summary_memory.py:432-451`); `classify_identity_compatibility` при несовпадении всегда даёт `REINDEX_REQUIRED` (`:2285-2288`). При наличии ACTIVE панель всегда показывает ложный REINDEX_REQUIRED; при отсутствии ACTIVE (`active_generation=None`) не показывает ничего (`:2067-2082`). **Новый путь не задет**: `_vec_write_allowed`/`_index_generation_ok` и `generation_status` считают fingerprint одной схемой. Классификация: pre-existing, **nonblocking для этого кандидата**; файл принадлежит другому лейну. Условие для W4-UI: рендерить `generation`, а не `vector_memory.indexes[].compat_class`, пока ложный REINDEX не исправлен.
5. **Двойной `scheduled` при параллельных тиках.** Оба вызова `maybe_schedule_rebuilds` возвращают `["graph_facts_vec"]` и оба делают `fire_and_forget(run_job)`; джоба одна (unique partial по coalesce-key), `run_job` CAS не даёт двум сборкам стартовать. Косметика/лишний вызов, не storm; pre-existing concurrency, этим диффом не ухудшена.

## Независимые числа (чистый worktree `d3ba845b`)

| Набор | Результат |
|---|---|
| `tests/test_graphrag_identity_reindex.py` + `tests/test_webapp_memory_overview_api.py` | **20 passed** (11 новых + 9 тестов API-файла, включая 2 новых) |
| 20-файловый graphrag/embed/memory/API набор из `report.md` §6 | **678 passed** (61.56 s; повтор с `--timeout=120` после одного инфраструктурного timeout в первом прогоне — тот же результат) |
| `tests/test_memory_*.py` (11 файлов) | **295 passed** (16.93 s) |
| RED: новый файл на `468d1041` (копия теста в одноразовый worktree) | **10 failed, 1 passed** (совпадает с отчётом) |
| RED: `test_webapp_memory_overview_api.py` (новая версия) на `468d1041` | **1 failed, 8 passed** (падает только новый `test_generation_block_present_and_fail_open`) |
| Мои probes (GREEN-код, sqlite-vec, tmp DB) | flip-back: `scheduled=[] / job=activated / build_in_progress / write_allowed=False`; fail-status: `failed / build_in_progress`; empty-source: `scheduled=[] / generations=1`; parallel: `1 gen / 1 job` |

Замечание: первый прогон 20-файлового набора в чистом worktree один раз прервался pytest-timeout (тот же класс, что описан в соседнем review EMBED-FALLBACK); последовательный повтор — 678 passed. К диффу не отношу; но перед релизом набор надо гонять последовательно, без параллельных тяжёлых прогонов.

## Ответы на вопросы лейна 7–8

**7.** Подтверждено: incidental не блокирует новый путь; `generation` использует правильную схему (`summary_memory.embedding_identity_fingerprint`), `compat_class` остаётся ложным при ACTIVE. UI — только `generation` + `rebuild`; `compat_class` не рендерить до фикса владельцем `embedding_control_plane.py`.

**8. Порядок деплоя/перестройки.**
- Сначала **зафиксировать финальный embedding identity** (provider/model/base_url/dim). Любая смена identity после старта сборки = aborted validation + повторный полный re-embed (~316 платных вызовов).
- Деплой: 2.58.112 (fallback) → 2.58.113 (этот фикс + W4-UI) в одном окне; рестарт сервиса — штатный. **Перестройка стартует сама** на startup/тике ≤15 мин; отдельная команда не нужна.
- Важно: рестарт **любой** версии, включая 2.58.112, уже запускает pre-existing startup-путь (`_register_index_generations` + `maybe_schedule_rebuilds`), поэтому 316 вызовов могут начаться ещё на 2.58.112; 2.58.113 затем продолжит с checkpoint (durable; после рестарта возможна пауза до ближайшего тика ≤15 мин, пока heartbeat старого процесса не станет stale), без дубля стоимости.
- Ожидаемо: `graph_facts` eligible = 15 819 → ≈316 HTTP-вызовов, ~2.4M токенов, 15–40 мин; `smart_archive_facts=0` → поколение не регистрируется, вызовов нет; lease — одна перестройка, второй индекс ждёт.
- Наблюдение: `GET /api/memory/embeddings` → `generation.indexes[].state: build_in_progress → active`, `rebuild` progress, `backlog.backlog_graph` падает с 4 170; логи `EMBEDDING_GENERATION_REBUILD_REQUIRED → BUILD_START/PROGRESS/VALIDATED/ACTIVATED`.
- Стоп: `GRAPHRAG_SHADOW_REBUILD_ENABLED=false` + рестарт (FTS5 продолжает работать). Горизонт пауз 24 ч → terminal failed; после B2-фикса это будет видно как `build_failed`.
- Откат: откат только кода после успешной активации безопасен (ACTIVE совпадает с identity, старый код продолжает отдавать векторы). Откат **конфига** при новом коде запустит ещё один полный re-embed; откат кода+конфига вернёт прежний тихий FTS-only. Решение об откате — по факту ошибок провайдера/квоты, без отдельного согласования (PET_PROJECT).

## Что не проверялось

- Прод/live-поведение (SSH запрещён лейном): факты `report.md` §1 (2 строки `building` от 29.09, backlog 4 170, apinet healthy) взяты из аудита, не перепроверены. Реальная активация поколения на проде — post-deploy (`READY_FOR_LIVE` после фиксов), не доказана этим ревью.
- UI/Playwright/Browser Use: визуальных изменений нет (только additive JSON-поле); потребление — лейн W4-UI.
- Внешняя эквивалентность apinet/Google — вне лейна (см. review EMBED-FALLBACK, `EXTERNAL_UNVERIFIED`).

## Следующее действие

Builder: исправить B1 и B2 (локально, без новой архитектуры/DDL/env), добавить два regression-теста (A→B→A через `maybe_schedule_rebuilds`+`run_job`; terminal failure → `build_failed`), прогнать новый файл + 20-файловый набор + `test_memory_*.py`, приложить probe-вывод. Reviewer: перепроверить оба probe и полный путь, затем — `Approved for controlled deployment` для 2.58.113 (родитель не DONE до post-deploy активации на проде).
