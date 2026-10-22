# B11-DIAG-FIX — ложный `ok` у FAILED-рана Summary и молчаливый `null` backlog

Лейн: `B11-DIAG-FIX` (writer). Дата: 2026-10-23 06:2x +12:00.
Источник дефекта: `plans/features/_audit-2026-10-23/prod-checks/report.md` §7
(`REQ-B11-E2E` = FAIL), сырые строки — `prod-checks/raw/main3.txt:64-70`
(`summary_runs`, `summary_stages_nonok`).

## 1. Точное место (не там, где предполагалось в брифе)

Бриф указывал `web/api/routes.py (~2156)` и/или `web/api/analytics_viz.py
(~132)`. Это **другие** ветки, к дефекту не относящиеся:

| Файл:строка | Что там реально | Отношение к дефекту |
|---|---|---|
| `web/api/routes.py:2149-2161` | `GET /api/youtube/proxy/health` → `{"status": "never_run"}` | не связано (YouTube-прокси) |
| `web/api/analytics_viz.py:129-167` | `_effective_status()` — коды process-activity (`off/not_instrumented/never_run/error/...`) | не связано (реестр процессов) |
| **`tools/v63_b11_mechanisms_report.py:662-666`** (до фикса) | `diagnose()`: `if status in ("error", "failed")` | **причина ложного `ok`** |
| **`tools/v63_b11_mechanisms_report.py:1163-1169`** (до фикса) | `_summary_section()`: `status = summary_runs.state` | источник значения в верхнем регистре |
| **`tools/v63_b11_mechanisms_report.py:986-987`** (до фикса) | `backlog = db.scalar(spec["backlog_sql"])` → молча `None` | **причина `backlog=null`** |

Почему именно так: `summary_runs.state` пишется только в ВЕРХНЕМ регистре —
`services/summary_run_store.py:58-62`
(`STATE_DONE="DONE"`, `STATE_DEGRADED="DEGRADED"`, `STATE_FAILED="FAILED"`,
`TERMINAL_STATES=(DONE, DEGRADED, FAILED)`; `FAILED` также ставит
`terminal_state_for_run()` и `close_stale_run()`). Сравнение в `diagnose()`
было регистрозависимым и в нижнем регистре, поэтому `FAILED` проваливался в
финальную ветку `ok`. Прод 22.10.2026 16:07Z: `state=FAILED,
publication_status=failed, pipeline_health=degraded` → инструмент показывал
`Summary scheduler — ok` (8 ok / 2 never_run).

`backlog_missing_embedding` считается как `COUNT(graph_facts) -
COUNT(graph_facts_vec)`, а `graph_facts_vec` — **vec0-таблица**
(`services/summary_memory.py:100-104`). Инструмент открывает SQLite в
`mode=ro` и не загружал `sqlite_vec`, поэтому запрос падал
(`no such table: graph_facts_vec`), `ReadOnlyDB.scalar()` возвращал `None`,
и в отчёт уходил `null` без причины. DevOps получал реальные `4162` только
отдельным прогоном с загруженным расширением.

## 2. Что изменено

Файлы: `tools/v63_b11_mechanisms_report.py`,
`tests/test_asap8_v63_b11_report.py` (только эти два; web/services не тронуты —
там дефекта нет, см. §5).

1. **Регистронезависимая классификация исходов** (`diagnose()`,
   `tools/v63_b11_mechanisms_report.py:738-762`). Статус нормализуется
   `casefold()` и сверяется с явными словарями, взятыми из фактических
   писателей:
   * `failed/failure/error/cancelled/canceled/interrupted/crashed/timeout` →
     `attention` (раньше `FAILED`/`CANCELLED` считались успехом);
   * `degraded/partial` → **новый** код `degraded` (резервный контур — не
     зелёное);
   * `done/ok/success/succeeded/completed/published/kept/narrowed/split/
     disputed/replaced/pass/applied` → далее TTL/`ok`;
   * пусто или незнакомое значение → **новый** код `unknown` (не зелёное).
2. **Провал публикации — тоже не зелёное**: `_summary_section()` отдаёт
   `publication_status` в `last_attempt`, `diagnose()` при `failed` → `attention`
   (защита от «state=DONE, но пост не опубликован»).
3. **Явная семантика статуса**: `_self_model_section()` помечает свой
   `last_attempt` как `status_semantics="classification"` — `subject_status`
   (`self/other/ambiguous`, `services/mca_self_model.py:57`) это классификация
   субъекта, а не исход, поэтому словарная проверка к ней не применяется
   (иначе секция стала бы ложным `unknown`).
4. **Backlog честный, а не `null`**: `_backlog_block()`
   (`tools/v63_b11_mechanisms_report.py:1074-1106`) + `ReadOnlyDB.
   scalar_with_error()`/`ensure_vec()` (`:333-380`). Сначала обычный запрос; при ошибке
   read-only коннект идемпотентно догружает `sqlite_vec` (загрузка расширения
   не пишет в БД) и повторяет запрос. Итог в `write_result`:
   `backlog_missing_embedding` (прежний ключ, значение или `null`),
   `backlog_status` = `ok | unknown | not_instrumented`,
   `backlog_reason` = текст реальной ошибки. В человекочитаемый вывод
   добавлена строка `backlog (без эмбеддинга): ... — причина`.
5. Обновлены `not_green_rule` и `_DIAG_RU` (новые коды объяснены словами).
6. **Job-ветка** (догоняющий патч по ревью N1, см. §10): регистронезависимая
   классификация `task_jobs.status` с явными кодами для
   `cancelled/validation_failed/finished` → `attention`, `paused*` →
   `degraded`, незнакомый → `unknown`.

## 3. Наблюдаемое поведение после фикса

Прогон `probe_fixed.py` (реальные прод-значения `state/publication/health`
из `raw/main3.txt`): `probe-fixed-output.json`.

| Вход (последний run) | Было | Стало |
|---|---|---|
| `FAILED` + `publication=failed` + `health=degraded` (прод 22.10) | `ok` | `attention` — «последняя попытка FAILED (run=…, publication=failed, health=degraded)» |
| `DEGRADED` + `published` | `ok` | `degraded` — «резервный контур» |
| `DONE` + `published` + `health=ok` | `ok` | `ok` (контракт не сломан) |
| незнакомое состояние / пустой статус | `ok` | `unknown` (не зелёное) |
| backlog без vec-таблицы | `null` без причины | `null` + `backlog_status=unknown` + `backlog_reason="…no such table: graph_facts_vec"` |
| backlog с vec0 (прод-эквивалент 4162) | `null` | **`1`** (реальное число), `backlog_status=ok` |

## 4. RED → GREEN

**Честная формулировка RED (уточнение по ревью).** На чистом родителе новый
тест-файл вообще не импортируется: `ImportError: cannot import name
'DIAG_DEGRADED'` — новых констант там нет. Поэтому «5 failed / 17 passed на
исходном коде» буквально неверно. Корректно: **RED при откате только логики
(константы `DIAG_DEGRADED`/`DIAG_UNKNOWN` на месте)** —
**5 failed / 17 passed** (`pytest-red-origcode.txt`), падают именно новые
регрессионные тесты (`assert 'ok' == 'attention'`,
`KeyError: 'backlog_status'`). Сам дефект подтверждён отдельно: старый
`diagnose` на `state='FAILED', publication='failed'` возвращает `ok`.

GREEN: `pytest-green.txt` — **24 passed** (`tests/test_asap8_v63_b11_report.py`;
22 после первого патча + 2 на job-ветку, см. §10).
Смежные наборы: `pytest-adjacent.txt` — **103 passed**
(`test_asap8_v63_w3_analytics_viz`, `test_pipeline_analytics_asap4`,
`test_webapp_analytics_api`, `test_memory_health`,
`test_memory_health_round1019`). Итого 127 passed.

Broad-срез `-k "asap8_v63 or analytics or health or pipeline"`
(`pytest-affected.txt`): 466 passed, 1 skipped, **4 failed — не мои**:
`tests/test_summary_generator.py::TestPipeline::*` падают на
`except asyncio.CancelledError` (`TypeError: catching classes that do not
inherit from BaseException`), потому что сам тест подменяет
`services.summary_generator.asyncio` на `MagicMock`
(`tests/test_summary_generator.py:23-26`). Мой дифф не импортируется этим
тестом и не трогает `services/` — дефект тестового харнесса, не регрессия
лейна (incidental, вне scope).

Тест `test_ok_states_fresh_runs` содержал фикстуру `state='COMPLETED'` —
такого состояния генератор никогда не пишет; заменено на реальное `'DONE'`
(иначе тест защищал вымышленный контракт).

## 5. Соседние ветки диагностики (пункт 4 брифа) — рассинхрона регистра нет

Проверено чтением кода, не догадками:

* `web/api/analytics_viz.py:149-167` — сравнивает `mca_events.outcome`;
  писатель `services/mca_events.py:45-52` пишет **нижний** регистр
  (`failed/cancelled/interrupted/skipped/silent/pending_external`) —
  сравнение консистентно. Статусы реестра (`implemented/disabled/not_run/
  not_instrumented`, `services/mca_process_registry.py:32-35`) сверяются
  точно.
* `services/pipeline_analytics.py` — сравнивает `stage_status`/
  `publication_status`/`outcome` (`:569, :1137, :1272-1274, :1518`).
  `publication_status`/`outcome` действительно пишутся в нижнем регистре
  (`published/failed`, `success/failed`). Уточнение по ревью (N2):
  `summary_run_stages.status` **не** чисто нижний — в проде есть
  `LEGACY_FALLBACK` (верхний) и `degraded_map_fallback`; на equality-проверки
  `pipeline_analytics` (`== "failed"`) это не влияет, и B11-инструмент эту
  таблицу не читает вообще.
  `summary_runs.state` (верхний регистр) там не читается.
* `services/summary_run_store.py:436` — `status == "failed"` для статуса
  генератора (`ok/failed`, нижний) — консистентно.
* `web/api/routes.py` и `web/api/analytics_viz.py` из брифа — не связаны
  (см. §1).
* Поиск по репозиторию `== "FAILED"` / `== "DONE"` вне констант
  `summary_run_store`/`cover_style_jobs`: совпадений нет.

Исправлять в соседних ветках нечего; рефакторинг не делался.

## 6. Обратная совместимость формата

Изменения **аддитивные** для JSON/человекочитаемого отчёта:
* новые коды диагноза `degraded` и `unknown` (словарь расширен, старые коды
  и их смысл не менялись);
* новые ключи `write_result.backlog_status`, `write_result.backlog_reason`;
  `backlog_missing_embedding` сохранён;
* `last_attempt.publication_status` (только summary) и
  `last_attempt.status_semantics` (только self_model);
* обновлён текст `not_green_rule`.

Изменения **семантики** (намеренные, это и есть фикс): `FAILED/CANCELLED/
INTERRUPTED` больше не `ok`; `DEGRADED` больше не `ok`; незнакомый статус
больше не `ok`. Единственный потребитель кодов — этот же инструмент и его
тест (`rg` по `producer_off|DIAG_ATTENTION|cursor_stalled` даёт только
`tools/v63_b11_mechanisms_report.py` и `tests/test_asap8_v63_b11_report.py`),
поэтому потребители не ломаются.

## 7. Что осталось / риски

1. **Прод-прогон не выполнен** (SSH/прод запрещены брифу). Проверено
   воспроизведением прод-строк локально на фикстуре + штатным тестом; на
   проде ожидается `Summary scheduler — attention` и `backlog: 4162`.
   Проверить это должен DevOps/Orchestrator read-only прогоном
   `tools/v63_b11_mechanisms_report.py --db local_database.db` после деплоя.
2. `ensure_vec()` грузит расширение только при ошибке запроса — если на проде
   `sqlite_vec` нет в venv инструмента, будет честный `unknown` с причиной
   (не `null`), но без числа.
3. ~~Related-nonblocking: job `cancelled` → `never_run`.~~ **Исправлено
   догоняющим патчем §10** (ревью N1): job-ветка больше не регистрозависима и
   знает реальные статусы.
4. Related-nonblocking: `web/api/analytics_viz.py:_effective_status()`
   неизвестный `outcome` трактует как `working` — не регистровый баг и не
   дефект брифа; не трогал, чтобы не задеть лейн W4-UI.
5. 4 падения `tests/test_summary_generator.py` — pre-existing harness-баг
   (см. §4), не связан с лейном.
6. `local-db-human.txt` — прогон по локальной заглушке БД (12 КБ, без
   `graph_facts`), поэтому прод-форму он не доказывает (ревью N4). Доказательство
   поведения — `probe_fixed.py` с настоящей `vec0` и тесты; реальные 4162 на
   проде остаются за post-deploy прогоном (п.1).

## 8. Артефакты

`probe_fixed.py` (воспроизведение), `probe-fixed-output.json`,
`local-db-human.txt` (реальный прогон инструмента на локальной БД),
`pytest-red-origcode.txt`, `pytest-red-jobbranch.txt`, `pytest-green.txt`,
`pytest-adjacent.txt`, `pytest-affected.txt`.

## 9. Коммит

Один коммит, только файлы лейна (`tools/v63_b11_mechanisms_report.py`,
`tests/test_asap8_v63_b11_report.py`, эта папка evidence): ищется как
`git log -1 --grep "fix(b11): honest diagnoses"`. Точный SHA передан в
handoff лейна (внутрь файла его вписывать нельзя — amend меняет SHA).

## 10. Догоняющий патч: job-ветка `diagnose` (ревью N1)

Тот же класс ложной зелени, отдельная ветка. Было
(`tools/v63_b11_mechanisms_report.py:702-734` в коммите `3334141a`): статус job
сравнивался регистрозависимо и знал только
`queued/running/failed/interrupted/completed`; всё остальное проваливалось в
проверку `last_attempt`, и при старой успешной попытке отчёт показывал `ok`.

Реальные статусы `task_jobs.status` в проде
(`prod-checks/raw/main.txt:176,187,190,201`): `paused_rate_limit`,
`cancelled`, `finished`, `validation_failed`, `completed`, `failed`,
`interrupted`. Семантика `finished` проверена по коду:
`services/embedding_control_plane.py:1665` — это **stale-takeover** lease
(`reason_code='stale_takeover'`), то есть НЕ успешный терминал.

Стало (`:726-773`): статус нормализуется `casefold()`, ветки явные —

| job status | Было (со старой успешной попыткой) | Стало |
|---|---|---|
| `cancelled` / `CANCELLED` | `ok` | **`attention`** — «job CANCELLED — не успешный терминал» |
| `validation_failed` | `ok` | **`attention`** — «не прошло валидацию» (`reason=knn_source_empty`) |
| `finished` | `ok` | **`attention`** — stale-takeover lease, не успех |
| `paused_rate_limit` / `paused_provider` / `paused` | `ok` | **`degraded`** — пауза (авто-resume), не успех |
| `failed` / `interrupted` | `worker_crashed` | без изменений (обратная совместимость) |
| `queued/running/building/checkpoint/validating` | `ok` (только queued/running) | `ok` при свежем heartbeat, `worker_crashed` при протухшем |
| `completed/validated/activated/active` | `ok` | `ok` + прежний `cursor_stalled` |
| незнакомый | `ok` (при наличии попытки) | **`unknown`** (не зелёное) |

RED: `pytest-red-jobbranch.txt` — **2 failed / 22 passed**
(`assert 'ok' == 'attention'` на интеграционном кейсе
«job `cancelled` + старая успешная попытка», и `assert 'ok' ==
'worker_crashed'` для `FAILED` в unit-матрице).
GREEN: `pytest-green.txt` — **24 passed**.

Скоуп: только `tools/v63_b11_mechanisms_report.py`,
`tests/test_asap8_v63_b11_report.py`, этот отчёт; `services/**` и `web/**`
не тронуты (`git show --name-only`).
