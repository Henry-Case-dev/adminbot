# RW-D4-BOTH-WRITE-FAIL — CORRECTION: удержание на процесс, а не на экземпляр

**Эпик:** `P0-INIT-MEME-UX-DIAG`. **Строка:** `P0IM-ID-FINISH` / `P0IM-ID-CONC`, инвариант D
(`architecture-identity.md` §1).
**Кандидат кода:** `926b093a160454b72fc519b0c27ef438e27a0ee6`, ветка `fix/p0im-final-train`.
**База:** production `6c11fc08` (2.58.194). **Предыдущий кандидат:** `f984f06a`
(его привязка — `binding-f984f06a.md`, ею закрывается только полоса экранных пробелов).
**Проверял:** Architect (нашёл окно) → Builder (воспроизвёл, исправил, прогнал).

Файл `../S5M-MEME-DURABILITY/binding-16cdb3b8.md` содержал неверное утверждение
«окно закрывается переносом при следующей записи в этом процессе». В его начале
добавлена пометка CORRECTION; сам файл сохранён.

## 1. Что именно было неверно (file:line)

`_unpersisted` жил на **экземпляре** `SqliteQuotaLedger` (`services/meme_initiative.py`,
`__init__`). Production НЕ переиспользует журнал: `open_ledger` (`:374`) создаёт новый
объект при каждом вызове и кэша не имеет. Вызовы на каждом проходе:

| файл:строка | контекст |
|---|---|
| `services/initiative_observer.py:2029` | `ledger=meme.open_ledger(self._db)` — боевой цикл мемов |
| `services/initiative_observer.py:2090` | `_meme_claim_store` — второй объект в ТОМ ЖЕ проходе |
| `handlers/meme_command.py:264` | ручной `/meme` |
| `web/api/initiative_publications.py:381` | витрина «Публикации» |
| `web/api/routes.py:6257` | админский маршрут |
| `services/initiative_diagnostics.py:600`, `:2976` | отчёты и диагностика |

(В задании Architect указаны `initiative_publications.py:301` и
`initiative_diagnostics.py:2900` — в текущем дереве это другие строки тех же файлов;
сами вызовы `open_ledger` находятся на `:381` и `:2976`. Существо дефекта не меняется.)

Следствие: после отказа ЖУРНАЛА и СПУЛА удержанную строку мог перенести только следующий
`record_attempt` того же объекта. Следующий проход начинал с пустым списком, и даже после
восстановления обоих носителей строка не попадала ни в журнал, ни в спул. Единственным
следом оставалась ERROR-строка. Инвариант D требует «удерживается процессом и переносится
в первый освободившийся носитель», а принятым остаточным окном является только смерть
процесса при мёртвых носителях.

## 2. Наблюдаемое до/после (реальная SQLite, подмена обоих носителей)

Проба `repro` (A удерживает при мёртвых носителях → носители живы → B = новый
`SqliteQuotaLedger` того же файла делает одну запись):

| величина | `f984f06a` (до) | `926b093a` (после) |
|---|---|---|
| A удержал | `['held-by-A']` | `['held-by-A']` |
| спул-файл | нет | нет |
| журнал для читателя до переноса | `[]` | `[]` |
| B видит удержание до своей записи | `[]` | `['held-by-A']` |
| журнал после записи B | `['written-by-B']` | `['held-by-A', 'written-by-B']` |
| строка A дошла до журнала | **нет** | **да** |
| удержание после переноса | `['held-by-A']` (у A навсегда) | `[]` |

## 3. Что изменено (минимально)

`services/meme_initiative.py` (+83/−36):

- `_UNPERSISTED_BY_PATH: dict[str, list[dict]]` (`:1072`) — реестр на ПРОЦЕСС, ключ —
  `_unpersisted_key(path)` = `os.path.abspath` (`:1077`), один `threading.Lock` (`:1074`).
- `held_unpersisted(path)` (`:1085`) — копия списка для тестов/наблюдаемости (не даёт
  менять реестр в обход замка).
- `_hold_unpersisted` (`:1381`): под замком — дедуп по `attempt_id`, добавление, вытеснение
  за `ATTEMPT_UNPERSISTED_MAX = 200` (`:1059`); лог пишется ПОСЛЕ замка и целиком:
  `json.dumps(_spool_payload(row))`, `attempt_id` без усечения (`_log_held_row`, `:1412`).
- `_retry_unpersisted` (`:1425`): под замком — снимок не более `ATTEMPT_SPOOL_BATCH` строк
  этого пути; далее на строку одна попытка `_insert_attempt`, при отказе одна попытка
  `_spool_attempt`; строка снимается только после успешной записи; пустой путь удаляется из
  реестра. Никогда не бросает; дисковый ввод-вывод вне замка.
- `record_attempt` (`:1342`) — вызовы в прежнем порядке: `_flush_pending_attempts()` →
  `_retry_unpersisted()` → попытки журнала → спул → удержание.
- `attempts()` не тронут (перенос только на записи), схема/спул-формат/читатели/группировка/
  `_PROCESS_ATTEMPTS` не менялись.

`tests/test_evol014_meme_initiative.py` (+2 теста): прямые обращения к
`self._unpersisted` переведены на `meme.held_unpersisted(path)` — проверка стала строже
(смотрит общий реестр пути, а не поле объекта), ослаблений нет; тест потолка 200 теперь
держит строки ДВУМЯ экземплярами одного файла.

## 4. Матрица сценариев

| сценарий | `f984f06a` | `926b093a` | тест |
|---|---|---|---|
| оба носителя живы | строка в журнале, удержания нет | так же | `test_both_carriers_ok_puts_the_row_in_the_journal_only` |
| журнал мёртв, спул жив | строка в спуле, удержания нет | так же | `test_journal_failure_keeps_the_row_in_the_spool_without_holding` |
| оба мёртвы, потом живы, ТОТ ЖЕ объект | перенос при следующей записи | так же | `test_both_carriers_fail_hold_the_row_then_flush_it_exactly_once` |
| оба мёртвы, потом живы, **НОВЫЙ объект того же файла** | **строка не доезжает никогда** | перенос при следующей записи нового объекта, ровно один раз | `test_held_row_survives_a_new_ledger_instance_on_same_path` |
| читатель, пока строка удержана | предыдущая попытка, подделки нет | так же | `test_held_row_is_not_fabricated_into_the_read_model` |
| ERROR при удержании | полный JSON, id без усечения | так же | `test_both_carriers_fail_log_the_full_row_without_truncation` |
| потолок 200, вытеснение | полная ERROR-запись старейшей | так же, потолок ОБЩИЙ на путь (проверено на двух экземплярах) | `test_unpersisted_cap_logs_the_oldest_in_full` |
| два экземпляра в двух потоках | н/д (реестры разные) | 10 удержаний → 10 строк, перенос без потерь и дублей | `test_two_ledgers_in_two_threads_hold_and_flush_without_loss` |
| повторная запись того же `attempt_id` | no-op (ID2) | так же | те же два теста переноса |

Конкурентный тест прогнан 5 раз подряд: `2 passed` каждый раз (3.17–3.25 с), флака нет.

## 5. Прогоны (cwd = worktree кандидата)

| команда | результат |
|---|---|
| `pytest tests/test_evol014_meme_initiative.py` | **58 passed** |
| `pytest tests/test_initiative_publications_api.py tests/test_meme_init_diagnostics.py` | **78 passed** |
| `pytest tests/test_evol014_ui.py` | **17 passed** |
| `node tests/js/initiative_ui_rework_test.js` | `INITIATIVE-UI-OK` |
| `node tests/js/meme_ui_fields_test.js` | `MEME-UI-FIELDS-OK` |
| 15-файловая серия мемов/инициативы/публикаций/диагностики | **364 passed, 4 failed** |
| `tests/ui_initiative_rework_e2e.py` | **failures=2** (те же предсуществующие) |
| `tests/ui_meme_ui_fields_e2e.py` | **failures=0** |

Серия: +2 к прошлому прогону (362→364) — ровно новые тесты; имена и состав четырёх падений
те же, что на базе `6c11fc08`: `test_act_on_opportunity_conflict_defers_to_intent`,
`test_evaluate_phase_precheck_blocks_before_llm`,
`test_t1_nostalgia_delegated_refusal_sends_nothing`,
`test_t5_every_text_send_site_passes_publish_guard` (последний падает на уже существующем
неохранённом вызове `tools/rlr_live_proof.py:580`). Оба e2e-падения — те же две строки
«после снятия override источник не "Исходный из кода"», воспроизводятся на базе.

## 6. Мутации (каждая проверена прогоном, файл восстановлен побайтово)

| # | мутация | красные тесты |
|---|---|---|
| D0 | ключ реестра = `id(self)` (список на экземпляре — прежний дефект) | `test_held_row_survives_a_new_ledger_instance_on_same_path` |
| D1 | убран `self._retry_unpersisted()` из `record_attempt` | `test_both_carriers_fail_hold_the_row_then_flush_it_exactly_once`, `test_held_row_is_not_fabricated_into_the_read_model`, `test_held_row_survives_a_new_ledger_instance_on_same_path` |
| D2 | ERROR снова без `row=` (усечённый id) | `test_both_carriers_fail_log_the_full_row_without_truncation`, `test_unpersisted_cap_logs_the_oldest_in_full` |
| D3 | вытеснение за потолком без записи в лог | `test_unpersisted_cap_logs_the_oldest_in_full` |
| P1 | `isStale: false` в `web/app.js` | JS-набор падает (`AssertionError`) |
| P2 | `generated` = «все рассмотренные» | `test_generated_is_not_considered_and_not_published` |
| P3 | `duration_ms = 0` у шага | `test_step_carries_duration_or_reason_and_recorded_request_id` |
| P4 | `stale → no_data` | `test_stale_snapshot_is_not_no_data_and_needs_a_recorded_window` |

Выживших мутаций нет. D0 — это и есть форма прежнего дефекта: тест на новом экземпляре
красный ровно так же, как падала проба до правки.

## 7. Честные пределы

- **Остаточное окно (принято решением, не блокирует):** если процесс умрёт, пока оба
  носителя мёртвы, единственный след — полная ERROR-строка. Если носители восстановятся, но
  в этом процессе больше НЕ БУДЕТ ни одной записи попытки, перенос не произойдёт до смерти
  процесса — это и есть «переносится в первый освободившийся носитель при следующей записи»,
  а не обещание фонового таймера.
- Реестр — на процесс: поддержано предусловие ID5 (один процесс-писатель). Между процессами
  удержание не разделяется; второй процесс с тем же файлом журнала контрактом не разрешён.
- Ключ реестра — `abspath` строки пути, которую дал `sqlite_path_of`. Если один и тот же файл
  открыть в одном процессе РАЗНЫМИ путями (симлинк, регистр, относительный путь), это будут
  разные ключи. Production всегда берёт путь из `sqlite_path_of(db)`, поэтому окно не
  наблюдалось; регистро/симлинк-нормализация не добавлялась (это уже не минимальная правка).
- Живой прод не проверялся: кандидат не выложен. Сценарии воспроизведены на реальной SQLite с
  подменой носителей, а не физическим отказом диска.
- `attempts()` по-прежнему не переносит (так и записано в решении): пока переноса не было,
  витрина показывает предыдущую попытку — принятое остаточное окно, а не выдача за правду.

## 8. Конфигурация

Новых флагов, настроек и дефолтов нет; схема, формат спула и промпты не менялись. Поведение
не зависит от конфигурации: удержание/перенос — внутренний путь записи журнала.
