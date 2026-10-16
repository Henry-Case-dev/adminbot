# INC-SUMMARY-01-FIX — границы pre-generation цепочки Summary (код)

Дата: 17.10.2026. Lane: INC-FIX (writer: summary/memory path). Деплоя/SSH/коммитов нет.
Вход: `incident-summary-01-code-analysis.md` (§6 п.1-7, §7 тест-матрица).
Прод-форензика (`incident-summary-01-prod-forensics.md`) появилась во время работы и учтена — см. §1b
(она уточняет механику инцидента: SIGKILL-фантом, а не живое зависание).

## 1. Причина (подтверждена по коду, без изменений в диагнозе)

До первого LLM-вызова было ТРИ шага без верхней границы времени:
пермит-ожидание (`summary_generator.py:539` — `acquire()` без таймаута), обслуживание памяти
(`:611` — дедлайна нет нигде в файле; `summary_memory.py:4956-4991` `while True` без капа и без
общего бюджета) и ожидание single-writer lock при записях окна. Терминал пишется только в
`finally` → висевший ран оставался `RUNNING` со `stages 0/0`, а тик крона
(`max_instances=1`, последовательный обход) держал остальные чаты и последующие тики.

## 1b. Уточнение по прод-форензике (файл появился во время работы; учтено)

`incident-summary-01-prod-forensics.md` (lane INC-SUMMARY-01, read-only прод) уточняет механику
инцидента 17.10 01:00:06:

* Прогон **не висел**: процесс SIGKILL-нут рестартом деплоя через 62 с после старта
  (13:00:06 UTC start → 13:00:08 SIGTERM → 13:01:08 SIGKILL). «48+ мин running» — **фантом UI**
  из-за отсутствия терминала (SIGKILL не исполняет `finally`) и отсутствия финализатора/вотчдога
  для `summary_runs`.
* **Подтверждено**: прогон шёл именно в `compress_and_purge` → `_compress_purge_extract_only`
  (`memory.infinite_retention=true`), и эта петля — **единственное**, что удерживало процесс в
  drain-окне до SIGKILL; общего дедлайна у петли нет (подтверждает §1).
* Бэклог extract-only на проде: «созревших» (старше 30 дней) live-строк — **758** при
  `limits.summary_compress_batch=50` → ~16 батчей × ~20 с ≈ 5 мин на прогон (не часы).

Что это значит для этой полосы (честно):

1. Делегированная задача — «ограничить pre-generation цепочку, чтобы обслуживание памяти никогда
   не могло подвесить публикацию» — выполнена как **защитная граница** класса причин
   (неограниченные ожидания перед публикацией), а НЕ как устранение конкретного прод-триггера
   (SIGKILL деплоя). Формулировка «зависший ран» в тестах означает «неограниченное ожидание»,
   а не воспроизведение прод-таймлайна.
2. Побочный полезный эффект для того же фантома: orphan-строка прод-типа (`CREATED`, без окна,
   без живого владельца, старше `SUMMARY_STALE_RUN_SECONDS`) теперь закрывается корректным
   терминалом `FAILED`/`stale_no_window` при следующем прогоне этого чата (раньше она
   «резюмилась» тем же run_id) — т.е. фантом исчезает честным терминалом.
3. **Вне scope этой полосы** (форензика адресует это parent-лейну, не мне): финализатор орфанов
   на старте процесса / терминал при SIGTERM / релизный гейт «не рестартовать во время Summary-тика» /
   грациозный stop. Мой фикс НЕ закрывает фантом, если для этого чата больше не будет ни одного
   прогона (нет стартового финализатора) — это остаточный незакрытый пункт, вынесен в §7.
4. Границы лимитов калиброваны под реальный прод-бэклог: кап 20 батчей × 50 строк = 1000
   сообщений/прогон > 758 «созревших»; бюджет 600 с > ~320 с фактических. Т.е. на проде границы
   не тормозят штатное обогащение графа, а срабатывают только на аномалии/большом бэклоге.

## 2. Что реализовано (file:line)

| # | Изменение | Где |
|---|---|---|
| 1 | Кооперативный бюджет + кап батчей + no-progress guard в extract-only; причина остановки в логе (R17-числа) | `services/summary_memory.py:4956-5043` |
| 2 | Hard-fuse (`asyncio.timeout`) вокруг `compress_and_purge` + локальный `except TimeoutError` ДО общего обработчика → fail-soft skip, stage `run_memory_maintenance`/`skipped`/`deadline_exceeded` | `services/summary_generator.py:686-712` |
| 3 | Bounded пермит: `try_acquire(timeout=SUMMARY_PERMIT_WAIT_SECONDS)`; таймаут → `SUMMARY_PERMIT_WAIT` (outcome=timeout) + busy-UX (manual) + выход БЕЗ run-row | `services/summary_generator.py:543-570` |
| 4 | Наблюдаемость: stage-строки `run_permit` / `run_memory_maintenance` / `run_source_window` со `started_at` + `duration_ms` в `SOURCE_WINDOW`-событии | `summary_generator.py:674-682, 702-712, 716-762, 955-972`; `services/pipeline_events.py:144-153` |
| 5 | Устаревший ран без окна и без живого владельца → FAILED/`stale_no_window` + НОВЫЙ run_id; ран с окном — resume как раньше | `summary_generator.py:596-620`, `services/summary_run_store.py:263-295` |
| 6 | Отменобезопасность записи графа: rollback и на `BaseException` | `services/summary_memory.py:5125` |
| 7 | Kill-switch `SUMMARY_PREGEN_BOUNDS_ENABLED` + env-оси лимитов | `services/mca_gates.py:554-640` |
| 8 | Тик: per-chat try/except + last-resort потолок времени на чат | `services/summary_scheduler.py:131-183` |

Реестр живых владельцев run_id (`_LIVE_RUN_IDS`, `summary_generator.py:449, 668, 862`) — чтобы
закрытие устаревшего рана не задевало ран, который прямо сейчас пишет своё окно (пул даёт до N
слотов на чат).

## 3. Kill-switch: решение и обоснование

`SUMMARY_PREGEN_BOUNDS_ENABLED` — **default ON**.

* Инцидент — прод-зависание: при OFF по умолчанию прод остался бы незащищённым до ручной
  правки env + рестарта, т.е. класс инцидента жил бы дальше.
* ON-путь fail-soft: обслуживание памяти лишь откладывается (данные/TTL/окно не меняются),
  публикация выходит вовремя с записанной причиной; ON не ослабляет ни один гейт.
* OFF = документированный паритет baseline (см. текст паритета в реестре) для аварийного отката.

Регистрация: словарь `INCIDENT_GATES` (`mca_gates.py:554`) той же формы, что `KILL_SWITCHES` /
`W2_GATES` (имя → (default, OFF-паритет)), + accessor `summary_pregen_bounds_enabled()`.
В `KILL_SWITCHES` **намеренно не добавлен**: тот словарь 1:1 связан с
`module_registry.MODULE_ENV_GATES` тестами M2 (`test_asap7_module_registry`,
`test_asap7_module_completeness`, `test_asap8_v6_p1_d11_registry`), а `services/module_registry.py`
вне write-scope полосы — ровно тот же прецедент, что у `W2_GATES` (комментарий в файле).

Env-оси (резолв per-call, fail-safe default): `SUMMARY_PERMIT_WAIT_SECONDS`=300,
`SUMMARY_MEMORY_MAINT_DEADLINE_SECONDS`=600, `SUMMARY_MEMORY_MAINT_HARD_SECONDS`=900,
`SUMMARY_MEMORY_MAINT_MAX_BATCHES`=20, `SUMMARY_STALE_RUN_SECONDS`=900,
`SUMMARY_TICK_CHAT_TIMEOUT_SECONDS`=3600 (≤0 → без потолка).

**Если бы kill-switch был OFF по умолчанию**: прод защищала бы только ручная установка env
(рестарт обязателен) — то есть ничто; поэтому OFF выбран как аварийный откат, а не как дефолт.

## 4. Демонстрации (исполнено)

Файл-доказательство: `evidence/incident-summary-01/_fix_demos_and_new_tests.txt` (полный вывод
`pytest -v --log-cli-level=WARNING`), RED/GREEN — `_fix_red_rollback.txt`.

1. **Зависшее обслуживание памяти больше не блокирует публикацию** (bounded skip + записанная причина):
   `SUMMARY_MEMORY_MAINT | outcome=skipped | reason=deadline_exceeded | budget_s=1.0` →
   публикация состоялась (`bot.send_message` ровно 1), ран `DONE`, stage
   `run_memory_maintenance`=`skipped`/`deadline_exceeded`, пермит освобождён, терминал записан.
   Обратная сторона (RED-эквивалент причины): при OFF публикация ЖДЁТ память (≥1.4 с из 1.5 с),
   при ON — < 2 с на 30-секундном зависании (`test_red_off_path_publication_waits_for_memory`).
2. **Зависший чат не останавливает тик**: тик с чатом, чьё обслуживание памяти висит 30 с,
   обрабатывает ОБА чата (`{BUSY_CHAT, FREE_CHAT}` опубликованы), тик завершается < 10 с;
   плюс last-resort потолок: `chat run deadline exceeded — tick continues | chat_id=-1`,
   исключение чата `-2` не срывает чат `-3` (`calls == [-1,-2,-3]`).
3. **Дубля публикации нет**:
   * рестарт без окна → старый ран `FAILED`/`stale_no_window` (публикация не трогается),
     новый ран — свой run_id, ровно 1 отправка;
   * рестарт с окном → resume ТОГО ЖЕ run_id, в БД ровно один ран, ровно 1 отправка;
   * конкурентный/занятый слот + таймаут пермита → `SUMMARY_PERMIT_WAIT | outcome=timeout`,
     run-row НЕ создаётся (`runs == []`), тик продолжает следующий чат;
   * большая очередь GraphRAG: обработано ровно 15 из 30 (кап 3×batch 5), остаток 15 остаётся
     `history_processed=0` (не удалён, не помечен), публикация идёт, следующий прогон догоняет до 0.
4. **No-progress guard**: та же пачка дважды → стоп `reason=no_progress_same_batch` без повторной
   экстракции (пачка экстрактится ровно один раз).
5. **RED→GREEN (отменобезопасность)**: с прежним `except Exception` отмена внутри транзакции
   оставляет `in_transaction=True` (тест падал), после фикса — `False`.

## 5. Тесты

Новый файл `tests/test_summary_inc01_pregen_bounds.py` — **13 passed** (`pytestmark = asap41`,
чтобы durable-контур был в прод-дефолтах; иначе session-fixture глушит `SUMMARY_RUN_DURABLE_ENABLED`).
`TEST-LIFECYCLE: REGRESSION owner=INC-SUMMARY-01/<case>` — в шапке файла и в docstring каждого теста.

Существующие suites (регресс-поверхность §8 + гейт-реестр): **674 passed** — `test_summary_generator`,
`test_summary_scheduler`, `test_summary_concurrency`, `test_summary_memory`,
`test_memory_retention_round1019`, `test_history_retention_toggle`,
`test_summary_asap_hotfix_round1027`, `test_summary_run_store_asap41`, `test_graphrag_memory`,
`test_asap8_v63_b06_summary_scope`, `test_summary_legacy_source_window_asap41`,
`test_summary_asap2_observability_round1027`, `test_summary_inspector_zone_g_asap41`,
`test_summary_supervisor_asap41`, `test_asap7_module_registry`, `test_asap7_module_completeness`,
`test_asap8_v6_p1_d11_registry`, `test_asap8_v6_wa2_mca_gates_hours`, `test_soul1_flags_composition`,
`test_summary_source_window_asap41`, `test_mca17_summary_instrumentation`, `test_pipeline_analytics_asap4`.
Широкий прогон `-k "summary or graphrag or mca_gates or module_registry"` — **2021 passed**.

## 6. Что сознательно НЕ менялось

* Удаление/TTL памяти, cutoff/окно ретенции, `history_processed`-семантика (кап лишь уменьшает
  объём за прогон; остаток докатывается следующим — данные не теряются).
* Окно 6 ч, каденс крона, `max_instances/coalesce`, гейт публикации/идемпотентность
  (`publication_status` у закрытого устаревшего рана НЕ трогается), `_publication_gate` не изменён.
* Слепой перепубликации/нового publish-API нет; второй живой run_id под то же окно не создаётся.
* `services/smartmodule_concurrency.py` — правок НЕ потребовалось: существующий
  `try_acquire(timeout=…)` уже возвращает `None` на таймауте и корректно снимает `pending`.
* SOUL-1 файлы и флаги не тронуты; `config/settings.py` не тронут (env-оси резолвятся в `mca_gates`
  per-call — поведение идентично env-only ClassVar, регистрация в settings остаётся за владельцем файла).

## 7. Отклонения от write-scope / риски

1. **`services/pipeline_events.py`** (не в списке WRITE_SCOPE, но требуется п.4 задания —
   `duration_ms` в SOURCE_WINDOW): добавлен **аддитивный** keyword `duration_ms=None` в
   `source_window(...)`; при `None` payload байт-в-бит прежний. Одна строка + docstring.
2. **Имена stage-строк** — `run_permit`/`run_memory_maintenance`/`run_source_window` (семейство `run`):
   существующий фильтр карточек `pipeline_analytics._liveness_cards` показывает только семейства
   l1/l2/review/writer/legacy/run, поэтому имена без префикса `run` были бы durable-записью,
   но НЕ видны в Analytics (а правки `pipeline_analytics.py` вне scope). Видимость подтверждена
   тестом через `pipeline_analytics.collect_run(...)["liveness"]`.
3. Новая user-visible фраза `_UX_BUSY_TIMEOUT` («саммари занято, попробуй позже») — только manual,
   честный исход вместо бесконечного молчания; крон молчит как раньше.
4. Остаточный риск: last-resort потолок чата в тике (default 3600 с) отменяет прогон, если
   неизвестное место зависания съест час; терминал пишется `finally`-ом, но отмена в момент
   «отправлено, ещё не записано» теоретически может дать повтор окна следующим прогоном
   (тот же класс, что и любой сбой процесса после отправки; reconcile-лестница и движущееся
   6-часовое окно ограничивают эффект). Первичные границы (пермит/память) этот сценарий не создают.
5. Не покрыто тестом (вне контракта полосы): отказ провайдера с «медленным, но живым» темпом
   на реальном прод-провайдере — проверяется следующим плановым прогоном после деплоя.
6. **Не закрыто этой полосой (фантом из прод-форензики)**: стартового финализатора орфан-ранов нет;
   если для чата с orphan-строкой больше не будет ни одного прогона, строка останется нетерминальной
   (TTL-purge чистит только терминальные). Нужен отдельный пункт parent-лейна: финализатор на старте
   процесса / терминал при SIGTERM (по прецеденту `mca_watchdog`, который репает только `task_jobs`).
7. Хронический неграциозный stop (SIGKILL через 60 с на всех рестартах с 12.10, прод-форензика §«Механика
   рестарта») — причина класса «обрыв прогона без терминала»; вне этой полосы. Мой фикс лишь сокращает
   время пребывания в петле памяти (кап/бюджет), т.е. уменьшает окно, в котором рестарт застаёт прогон
   внутри обслуживания памяти.

## 8. Проверка перед деплоем (для Reviewer/DevOps)

0. **Внимание: ожидаемая сигнатура на проде изменится.** Прод-форензика прогнозировала
   само-лечение orphan-строки `da33f05…` через `SUMMARY_RESUME` тем же run_id + терминал DONE.
   С этим фиксом (bounds ON) следующий прогон этого чата вместо resume закроет orphan
   (`SUMMARY_STALE_RUN_CLOSED | reason=stale_no_window`) и создаст НОВЫЙ run_id — фантом исчезает
   так же, но лог/ID другие. Это осознанное следствие делегированного п.5 (без второго живого
   run'а под ту же запись), а не регресс.
1. Прогнать `tests/test_summary_inc01_pregen_bounds.py` + список §5 (674 passed) на текущем кандидате.
2. После деплоя — следующий плановый прогон: ожидаемы stage-строки `run_permit`/
   `run_memory_maintenance`/`run_source_window`, терминал `DONE/DEGRADED`, при большой очереди —
   лог `extract-only bounded | reason=batch_cap_reached|deadline_exceeded`.
3. Аварийный откат: `SUMMARY_PREGEN_BOUNDS_ENABLED=0` + рестарт (прежний контур байт-в-бит).
4. Join barrier «причина устранена» **не может быть закрыт одним этим фиксом**: конкретный
   прод-триггер (SIGKILL деплоя без терминала + отсутствие финализатора `summary_runs`) остаётся —
   нужен отдельный пункт parent-лейна (§7 п.6-7).
