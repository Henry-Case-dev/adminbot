# MCA-17 `mca-17c-analytics-matrix` — evidence.md (Builder, round 10.47)

**Статус:** блоки A–G реализованы, интеграционная верификация зелёная. Блоки H/I (ревью/скан/деплой/лайв/закрытие) — не Builder.
**Базовый HEAD:** `b25558e` (= origin/master, прод 2.58.65, mca-12 VERIFIED). База-замеры подтверждены на старте: F8 `CHECK OK: реестр 523`, reason 279, KS 85, тулы (TOOL_CALLING_TOOLS) 14, реестр 47.
**Санкции:** spec §7 = ADR-1028-23 D9–D16 = arch-frames §1.2.12; применённое — см. §Интеграция (цифра-в-цифру).

## Секция A — «Обзор процессов» и IA (T-5180/T-5181/T-5182)

- Суб-навигация «Процессы | Запуски | Инциденты | Самообучение» внутри существующего `#/oversight` — **нового маршрута нет** (js-тест: `#/analytics` отсутствует в app.js/index.html; лейбл навигации «Аналитика» не менялся — T-5179 сохранён).
- Карточки — рендер существующего `GET /api/oversight/processes` (группировка по `widget_id`, D2); честные бейджи: implemented→«активен», disabled→«выключен (гейт `<имя>` из settings_ref)», not_run→«не запускался», not_implemented→«заготовка (запусков нет)», not_instrumented→«не инструментирован» (K-OFF — с причиной, не нули).
- Стадии + `stages_to_events` (`стадия→событие`) видны на карточке (A48-связь функции со стадиями/виджетом); сводка coverage из snapshot.coverage; подпись «общесерверный обзор — …не выбранного чата» (граница scope `:1370`).
- F12-display: карточка показывает и статус реестра, и гейт; расхождение подписано («реестр: implemented · фактическое состояние — по статусу выше»), backend-резолв не трогался (CA-17C-1).
- Фильтры карточек — клиентские по УЖЕ загруженному полному серверному снапшоту (trust не переносится; серверные фильтры — в «Запусках»). Deep link: `#/oversight?view=runs&component=…&status=…&run_id=…` — парсер `oversightParseDeepLink`, применяется на `setTab('oversight')`, переживает F5 (js-тест п.1); drill-down карточки → runs по фактическим component-значениям (`mca17cComponentMap`: `self_model`/`vision.media`/`factcheck.temporal`/`summary`/`dream`/`experience`/`intents` — подтверждены grep по emit-вызовам).
- A73 (T-5190): карточки self.model/vision.media/temporal.factcheck — рендеры реестра (стадии 8/9/8 + события + drill-down), не вторые витрины; factcheck-runs также остаются на существующем виджете `temporal-factcheck-block`.

## Секция B — «Запуски» (T-5183/T-5184)

- `GET /api/oversight/runs` — агрегат по `pipeline_run_id` поверх единого `mca_events` (ОДИН read-only SELECT, коррелированные подзапросы last-outcome/last-error; keyset-пагинация `cursor`, серверные фильтры status/chat_id/pipeline_type/model/component/since_ts; bounded `_RUNS_SCAN_CAP=5000`).
- Read-render статуса (докстринг `_derive_status`, тесты): run_degraded→degraded; run_partial→partial; failed+success→**partial** (ошибка ветви не стирает успехи); failed→failed; interrupted/worker_lost/heartbeat_stale/checkpoint_missing→interrupted; cancelled (без успеха)→cancelled; последнее событие success/**silent**→succeeded (**валидное молчание ≠ падение**); иначе running. `stalled` — **отдельный бейдж-флаг, не подмена outcome**.
- Деталь run: события в порядке sequence (R17-whitelist полей, БЕЗ usage_json/source_ref_json/stack; из error_json — только type/cause), required/optional стадии из СУЩЕСТВУЮЩЕГО `PIPELINE_VERSIONS`; «зелёный» = успешные стадии/молчание, не «получение текста».
- A54: поллинг 12с сохраняет выбранную деталь (re-GET run_id), раскрытые узлы (`mca17cRunOpen`), прокрутку списка (scrollTop сохранение/восстановление); merge без дублей по run_id. Анимации «здоровья по таймеру» нет: running + `updated_ts` > 5 мин → честный бейдж «нет обновлений >5 мин — не выглядит живым»; без объёма — счётчики стадий ok/fail, без выдуманных %.
- Уровень 4: timeline шагов (outcome/duration/причина/error type+cause, expand по клику — A54). Уровень 5: job_id/span/чат в раскрытом шаге; переходы в существующие разделы без дублей карточек.

## Секция C — «Инциденты» (T-5185)

- Рендер существующих `/incidents` + `/changes?since_ts` (cursor-догон, merge дедупом по incident_id, свежая строка побеждает — js-тест п.3); поллинг 8с ≤10s-контракта mca-17a.
- **acknowledged ≠ resolved**: два независимых бейджа; ack — **read-only** (осознанное решение: санкция routes +3, единственный write = jobs action; ack-endpoint отсутствует в 17c по ADR D7; кнопка ack НЕ рисовалась — расхождение с краткой формулировкой брифа «+ack через POST» задокументировано как incidental для @Architect reconcile).
- F14: severity сортируется по **числовому** ключу (js-тест: [10,2,1] ≠ строковой [1,10,2]).
- Группировка по fingerprint (серверная), разным симптомам — разные строки; при потере backend — бейдж «телеметрия: stale/unknown» (не старая зелень); восстановление/влияние/затронутые jobs/chats — в раскрытии; переход к «Запускам» из инцидента. Рассылок и stack trace'ов пользователям нет.

## Секция D — самообучение и фуннель личности (T-5186/T-5187/T-5188)

- Воронка: `GET /api/oversight/experience/funnel` — read-only SELECT поверх существующих таблиц mca-16 (episodes/lessons/applications/feedback), **без второго store**; каждое число с единицей и scope (notes ответа рендерятся); «статусы уроков — текущее состояние реестра» подписано; unknown — отдельным числом с подписью «≠ провал/успех»; feedback ≠ уникальные уроки — отдельная строка.
- «Эффект»: `mca17cEffectState` — без применений/без известных исходов → «эффект ещё не измерен — …» (A57: улучшение не выдумывается); с данными — объём наблюдений + успех/провал/unknown; шкал/«IQ» нет.
- Граф урока: карточки из существующего `GET /api/memory/lessons` (основания/trace/версии/замещение/счётчики); правка — кнопкой в существующую «Память»; представления одних записей без своего состояния (D11 `:1462`).
- Фуннель личности (D12): существующий `GET /api/persona/self-model` — три **различимых** статуса: «передано модели (prompt_render)» = applied_now; «проявилось по оценке» = rejected_now с причинами (иначе честно «нет данных»); «доказан сравнительный эффект (replay)» = «эффект ещё не измерен (вне процесса)»; per-rule причины исключения/конфликта видны; frame/snapshot версии + stale-бейдж; подпись «включение в промпт ≠ доказанный эффект» (причинность не приписывается, `:1588`).

## Секция E — диагностические действия и экспорт (T-5189)

- Единственный write: `POST /api/oversight/jobs/{job_id}/action` (cancel/resume/retry) — только через существующие операции TaskJobStore: cancel = НОВЫЙ `TaskJobStore.cancel` (тот же терминальный исход JOB_CANCELLED, что internal-cancel supervisor'а, + fencing bump — механизм `recover_stale`, A51; терминальные не трогаются → идемпотентность); resume = `requeue`; retry = `set_next_retry` (**error_code/reason_code сохраняются** — прошлая ошибка не затирается; для interrupted — `requeue`). Свой контрольный контур не создавался (CA-17C-1).
- RBAC `requires_global_admin()` на всех трёх маршрутах (тесты: 401/403); гейт супервизора OFF → 409; 404/409/422 валидация. Идемпотентность: повтор cancel на cancelled → 200 idempotent без записи (fencing не растёт — тест).
- Audit: одно событие `OVERSIGHT_JOB_ACTION` с reason **`oversight_job_action`** на запрос (включая идемпотентные реплеи — TH-8), usage_json {action, actor, changed, idempotent, prev_status} — тест с capture.
- Экспорт — client-side download уже очищенных сервером данных (js-тест: без fetch, без usage_json/source_ref_json/секретоподобных строк); «Повторить отображение» — только чтение; fault injection/произвольный код/SQL — отсутствуют; demo-данных в UI нет.

## Секция F — carry-overs (T-5192)

- **F14** — числовая сортировка severity (см. секция C, js-тест).
- **F15** — gaps/spool рендерятся существующим mca-metrics-блоком раздельно («gaps (потеряно)»/«spool (отложено)» семантика сохранена, блок не тронут).
- **F16** — `oversightFreshnessLabel`: null/undefined → «нет данных» (**пусто ≠ устарело**), возраст — честные «обновлено N назад» (js-тест п.5).
- **M-2 (chain UI delta)** — в run-детали дельты видны из фактических полей событий (attempt/duration/stage-исходы); отсутствующее — «нет данных», без выдумки.
- **L-3** — `oversightDeepReasonLabel`: unchanged→«без изменений» и др. человекочитаемые метки при **различимом raw** (js-тест: неизвестный код не маскируется). Полноценный интеграционный пункт показа deep-reason остаётся в модулях сна (вне oversight-экрана); хелпер поставлен в общий контур.
- **F12-display** — см. секцию A.

## Секция G — тесты и верификация (T-5193/T-5194/T-5195)

**Python:**
- `tests/test_mca17c_oversight_api_round1047.py` — 14 тестов: routes==3; RBAC 401/403 на всех трёх (RED-first); runs-агрегаты/статус-рендер (partial/degraded/stalled-флаг/silent); серверные фильтры (chat/status) + 422 вне whitelist; keyset без дублей; detail + контракт стадий; R17-форма (<= whitelist ключей); funnel-счётчики/фильтр чата/notes/gate-off; action: cancel+fencing, идемпотентный повтор, resume, retry с сохранением error_code, 404/409/422, gate-off 409, аудит 1-на-запрос.
- `tests/test_mca17c_invariants_round1047.py` — 7 тестов: reason 280 (+ отсутствие чужих контрольных кодов); v33/ KS 85/ тулы 14/ каталог 523; реестр 47; APP_VERSION 2.58.65 не тронут; routes +3 + регистрация в web/app.py; **byte-freeze routes.py == пин 8153b8bd…45** (re-pin верифицирован, L-F11S-1); `TaskJobStore.cancel` семантика (no-op на терминальных).
- Санкционированные обновления счётчика в 4 существующих тестах (279→280, по прецеденту mca-20→mca-10b): `test_mca10b…round1041`, `test_mca19_block_f_round1043`, `test_mca20_rework1_f1_f2`, `test_mca20_integration_round1045`.

**JS:** `tests/js/round1047_mca17c_ui_test.js` — 14 групп проверок (см. шапку файла). Полный набор `tests/js`: **62/62 зелёные** (вкл. 61 прежних — регрессий UI нет).

**T-5194 — 13 сценариев отказов §27.9 (read-render через API):** покрыты API-проверками: timeout провайдера (error_last type/cause), heartbeat/progress-поля (events whitelist), потеря heartbeat/worker_lost/checkpoint_missing → interrupted, рестарт (recover_stale-механика через fencing-тест cancel), ошибка ветви → partial, stalled-флаг, отмена (cancel 200/идемпотент), валидное молчание → succeeded, delivery_unknown — виден как reason_code в списке/экспорте (сверка, не слепой retry — UI не предлагает retry вне существующих операций). **Не покрыты Builder-фазой** (честно): гибель worker между checkpoint и terminal, сбой log storage, reconnect миниаппа на живом сервере, неясный результат отправки, завершение shared task — требуют живого контура; переносятся в live-приёмку T-5199/prod-smoke (перечислены как чек-лист). Fixtures — без внешних платных операций; demo-данных нет.

**T-5194 — замер нагрузки телеметрии** (dev-side, воспроизводимый: `tools/_mca17c_telemetry_load.py`, `tools/_mca17c_runs_bench.py`): 4000 событий (500 runs × 8) через контракт → build 0.28с, flush встроен в цикл, **dropped_total=0, pending=0 (cap 256 — bounded, неограниченного буфера нет)**, ~488 Б/событие в SQLite; read-агрегат /runs на 500 runs — **0.008с (0.02 мс/run)**; funnel-агрегаты — миллисекунды. Writer-path: только существующий single-writer `write_transaction`, новых writers нет. (Без обещания нулевого overhead.)

**T-5195 — Browser-Verification:** компоновка проверена harness-тестом (маркеры data-mca17c, единственная вставка в oversight-шаблон, нет `#/analytics`, нет v-html в новых блоках, подпись «общесерверный»); снятие **реальных скриншотов desktop/mobile** требует TMA-контекста (global-admin initData) — по прецеденту mca-12 (E2E-раннер против прода, T-5175 PENDING OWNER) полноэкранный проход перенесён в чек-лист T-5199/ревью: граф-vs-stepper на реальных ветвлениях, mobile-список, reduced motion, клавиатура, обезличенные trace-примеры §21 п.6. ` incidental → uncertain`: Playwright-проход без TMA даёт пустой каркас (не доказывает компоновку) — не имитировал.

## Интеграция (финальный кандидат)

**Дельта против 2.58.65 (цифра-в-цифру санкций):**

| Санкция | Было | Стало | Факт |
|---|---|---|---|
| Δ DDL | v33 | v33 | **0** — миграций нет (инвариант-тест PRAGMA user_version) |
| Δ каталога | 523 | 523 | **0** — F8 `--check` OK (замер до/после) |
| Δ KS | 85 | 85 | **0** — инвариант-тест |
| Δ reason | 279 | 280 | **+1** `oversight_job_action` — единственная дельта (`services/mca_events.py`) |
| Δ тулов | 14 | 14 | **0** — инвариант-тест |
| Δ routes | — | +3 | `GET /api/oversight/runs`, `GET /api/oversight/experience/funnel`, `POST /api/oversight/jobs/{job_id}/action` — NEW `web/api/oversight_router.py`; `routes.py` byte-freeze **подтверждён: sha256 == пин 8153b8bd3897…c7b45** |
| widget-ID | 47 | 47 | **0** новых (рендеры существующих) |
| bump | 2.58.65 | 2.58.65 | не делался (2.58.66 — @DevOps, T-5198) |

**Файлы кандидата (sha256[:12], байты):**
- NEW `web/api/oversight_router.py` `115f5ab151bc` 28661
- `web/api/__init__.py` `ed338e366156` 1122; `web/app.py` `f7de56b7e6a0` 20231
- `web/app.js` `280486ba2d7e` 841459; `web/index.html` `69ed14da4b9d` 566445 (финал; в http-пине `bf87f97cb196` был до фикса UI-пина «✕»→«Свернуть»); `web/static/app.css` — не менялся
- `services/mca_events.py` `b8f04f20780c` 60083; `services/task_supervisor.py` `2354bd42bbc7` 38156
- tests: `tests/test_mca17c_oversight_api_round1047.py` `00b076928883`; `tests/test_mca17c_invariants_round1047.py` `de9012086ae6`; `tests/js/round1047_mca17c_ui_test.js` `728b1c2e7fb0`; обновлённые пины 279→280: `6bc9275f0b62`/`816d3b4cfa7d`/`d0b65c5a8b2e`/`492de033f498`
- вспомогательные (untracked, не в пакете): `tools/_mca17c_telemetry_load.py`, `tools/_mca17c_runs_bench.py`

**Прогоны фокуса:** mca-17c (21) + mca-12 (22) + mca-17a + webapp_deps + пины 279→280 = **195 passed, exit 0**; JS 62/62; F8 CHECK OK 523.

**ПОЛНЫЙ pytest FOREGROUND (rework R1, финальный кандидат, `pytest tests -q`):** **12338 passed / 4 failed** — ровно те же 4 документированных pre-existing (tool_loop, nav_disclosure, status_control, mca09-registry); новых 0. Время 7:24.

**Фикс в ходе интеграции (полный прогон №1 → №2):** полный прогон выявил 2 собственных регрессии UI-пинов `count(">✕</button>") == 5` (`test_webapp_avatars_ui`, `test_webapp_round1010_ui` — статический инвариант «крестики = маркер модалок»): кнопка закрытия run-детали была «✕» → переименована в «Свернуть» (панель, не модалка). Репродукции + файлы-соседи зелёные; полный прогон повторён на финальном кандидате (см. конец evidence).

## Incidental findings (для ревью, не чинить молча)

1. `related-nonblocking` — **ack-кнопка инцидентов**: бриф формулирует «+ack через POST», санкция жёстко ограничивает write одним POST jobs-action (routes +3; ADR D7 прямо исключает ack из 17c). Реализовано read-only отображение ack; если владельцу нужна ack-кнопка — нужна доп. санкция (+1 route или расширение action). Решение @Architect на reconcile.
2. `related-nonblocking` — `_scan_runs` N+1-подзапросы устранены коррелированными SELECT (0.02 мс/run), но при `_RUNS_SCAN_CAP=5000` и вырожденно большом числе runs счётчики `counts` считаются по отфильтрованному окну капа (ретенция 90д делает это практически недостижимым).
3. `unrelated/pre-existing` — 4 тестовых файла содержали пин 279; обновлены по конвенции (прецедент в самом файле mca-10b).
4. `uncertain` — полноэкранные скриншоты (T-5195) без TMA-контекста невозможны; чек-лист передан в T-5199.

## Rework R1 (T-5196 итер.1 — Needs Fixes, bounded rework)

**B-1 (High) — audit-событие никогда не создавалось.**
- **RED (репро ревьюера воспроизведён):** `_audit_job_action` слал `outcome="ok"` (`web/api/oversight_router.py:500` в итер.1); `ALL_OUTCOMES` не содержит `"ok"` → `build_event` возвращал `None` (`services/mca_events.py:512–513`: `if outcome not in ALL_OUTCOMES: return None`) → ни лог-строки, ни записи в `mca_events`. Прямое доказательство: `build_event('OVERSIGHT_JOB_ACTION', outcome='ok', …) → None` (замер до фикса). Мок-тест итер.1 пропускал это — доказательство было ложным в рантайме.
- **GREEN:** `outcome="success"` (одна строка, `web/api/oversight_router.py` `_audit_job_action`; словарь ALL_OUTCOMES НЕ расширялся — по решению ревьюера). Обратная верификация на тесте: подмена обратно на `"ok"` → persistence-тест RED; `"success"` → GREEN.
- **Новый persistence-тест БЕЗ мока:** `test_action_audit_persisted_real_emit` — реальный emit → `flush_events` → SELECT из `mca_events`: ровно одна строка `OVERSIGHT_JOB_ACTION`, `outcome="success"`, `reason_code="oversight_job_action"`, `job_id`, usage_json (action/actor/changed/idempotent). Старый мок-тест (`test_action_audit_one_event_per_request`) сохранён как контракт-вызова (TH-8: 1 запрос = 1 emit) и дополнен ассертом `outcome=="success"`; в докстринге явно: мок больше не единственное доказательство.

**B-2 (Medium) — матрица покрытия T-5191.**
- Создан `plans/features/mca-17c-analytics-matrix/coverage_matrix.md`: сверка 47/47 `ProcessDefinition` ↔ handlers (таблица с handler-фактами file:line: `services/dossier_rebuild_jobs.py:61`, `services/dream_worker.py:1728`, `services/mca_vision.py:512`, `services/temporal_factcheck.py:256`, `services/mca_watchdog.py:42`, `services/mca_experience.py:1588`, `services/mca_intents.py:1056`, `services/safe_fetch.py:88`, `services/tool_loop.py:133`, `services/chat_statistics.py:112` и т.д. — 47 строк); 18 строк минимальной матрицы §27.1 (`:1341–1360`) → widget/drill-down/trace/покрытие (да/частично+причина); доп.строки MCA-18/19/20 (`:1364`); пробелы явно: **22 not_instrumented** (унаследованный backend-пробел mca-17a, note-поля в коде) + **4 v0-заготовки** — эскалация @Architect (CA-17C-7), не self-serve.
- Синхронизация замером: 47 = implemented 20 + disabled 1 + not_run 4 + not_instrumented 22 (`coverage_report()`).
- Тест `test_coverage_matrix_sync` (в `test_mca17c_invariants_round1047.py`): каждая definition несёт обязательные поля контракта (process_id/version/purpose/trigger_kind/widget_id), статусы ∈ словаря реестра, 47 уникальных id, v0-набор == 4 известным заготовкам с `WIDGET_NONE`, и coverage_matrix.md упоминает каждый process_id. Overfit-защита: file:line-факты не пинятся тестом.

**Дельта rework (финальные хеши sha256[:12], байты):** `web/api/oversight_router.py` `b0d8046bd7df` 28974 (было `115f5ab151bc`); `tests/test_mca17c_oversight_api_round1047.py` `3c952423195c` 26927 (было `00b076928883`); `tests/test_mca17c_invariants_round1047.py` `f695d81cb498` 7822 (было `de9012086ae6`); NEW `coverage_matrix.md` `6085b262c539` 25179. Остальные файлы кандидата — без изменений к итер.1. Словарь ALL_OUTCOMES/REASON_CODES — НЕ тронут (reason 280 без изменений).

**Прогоны rework:** mca-17c фокус 23 passed (API 15 + инварианты 8); смежный слайс (mca-17a + mca-12 + webapp_deps + supervisor) 162 passed, exit 0; JS 62/62 (MCA17C-UI-OK); F8 CHECK OK 523; замеры: reason 280 / KS 85 / тулы 14 / реестр 47 / routes.py pin match=True. Полный pytest foreground — финальный отпечаток ниже.
