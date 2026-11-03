# AC-DATA — single-flight публикации `refresh` (T-SRC-CONCURRENCY, Builder)

- Кандидат-основа: `5e6fe90264e1859993d42d4ed7bb1342b47ac907` (ветка `feat/ac-data-sources`,
  база `a9f326f8`); блокер из `reports/w-ac-data-review.md` (Re-review 2, раздел
  «T-SRC-CONCURRENCY — подтверждён FAILED»).
- Требование: `plans/owner_inputs/2026-11-02-anticliche-memory-admin-ux-spec.md`, §2.2
  проверка 20 — «Одновременно cron+manual не создают две конкурентные публикации/дубль
  правил»; строка карты `T-SRC-CONCURRENCY`, `slice=AC-DATA`.
- Правка: `services/anticliche_worker.py` + набор AC-DATA + этот отчёт. Новых таблиц,
  второго транспорта, новых agentic-типов событий, изменений DDL/read API и `plans/`
  (кроме отчёта) нет. `apply_manual` (PUT) не тронут — см. «Что осталось».

## Выбранный guard — честный `busy` (не ожидание)

В `refresh` добавлен один `asyncio.Lock` (`_run_lock`, создаётся в `__init__`) — ровно
паттерн `dream_worker._run_lock`/`nostalgia_worker._run_lock`: идущий прогон → второй
вызов **не ждёт**, а сразу возвращает `{"status": "busy", "count": 0,
"published": False, source, version, rules}` с РЕАЛЬНЫМ действующим банком (`**bank`,
формула вынесена в `_bank_from_stored` — один источник истины для гейтов и для `busy`).

Почему отказ, а не ожидание:

1. Это буквально существующий паттерн проекта (`dream_worker.run_once` →
   `already_running`, `nostalgia_worker._tick/run_once`), а не новый механизм.
2. Ручной HTTP-запрос админки не висит минутами за сетевым+LLM циклом (в прогоне до
   `rounds_limit × источники` вызовов модели и HTTP-проверок).
3. Повторное нажатие кнопки не превращается в N последовательных полных прогонов
   (двойной/десятикратный расход модели) — бюджет провайдера не тратится на дубли.

Почему это не «тихая потеря результата»: второй вызов ничего не публикует и говорит об
этом явно; результат отдаёт тот прогон, который реально выполняется. Проверка
`locked()` и захват идут **без `await` между ними** — в одном event-loop это атомарно,
окна «проверил → потерял» нет (комментарий в коде).

Что именно сериализуется: `_refresh_impl` читает `stored` уже под замком, поэтому
публикация (`anticliche_cache.write_patterns` — полная перезапись списка, version+1)
не может наложиться на публикацию: в любой момент активен ровно один прогон.

Сопутствующее (чтобы `busy` не выглядел сбоем): статус добавлен в `_ANTICLICHE_TERMINAL`
(`skipped` + существующий код словаря §17.2 `queue_coalesced`, прецедент
`mca_vision`/`task_supervisor`), в `_refresh_level` (INFO) и в skip-логику `tick`
(`status=skip, reason=busy`). MCA-событие `anticliche_run` для отказа не эмитится —
как в `dream_worker`/`nostalgia_worker`, где отказ возвращается до старта прогона;
наблюдаемость даёт `trace_step` + лог эндпоинта.

## Тест и инвариант

`tests/test_anticliche_sources_ac_data.py::TestRefreshSingleFlight` — два одновременных
`refresh(force=True)` на одном воркере; прогон №1 удерживается внутри LLM
(`_GatedLlm`), вызов №2 приходит ровно в этот момент (реальная гонка: кнопка «обновить»
во время недельного тика). Транспорт `_ChangingTransport` отдаёт РАЗНЫЙ текст на каждую
проверку — без этого вторая попытка получила бы `unchanged` от уже записанного
состояния источника и гонка не воспроизводилась бы (проверено: с одинаковым телом
мутация оставалась зелёной).

Утверждается:

- (б) ни одно правило не потеряно: в банке и старое правило, и добытое прогоном №1;
  дублей нет; `store.cache_row["version"] == 10` — ровно ОДНА публикация;
  `llm.calls == 1` и `transport.calls == 1` — второй вызов не ходил ни в источники,
  ни в модель;
- (а) второй вызов — `status="busy"`, `version=9, rules=1` (реальный банк до
  публикации, не нули), `count=0`, `published=False`;
- замок освобождается: `worker.running is False` и следующий `refresh` не отказывает.

`TestRefreshEndpointBusy` — та же гарантия на админской поверхности: при занятом замке
`POST /api/anticliche/refresh` отдаёт 200 `{"status":"busy","version":9,"rules":1,
"count":0,"published":false}`, банк не тронут.

## Мутация (снят guard → RED)

Мутация `refresh` без замка (`return await self._refresh_cycle(...)`) — то есть ровно
код ревью-кандидата `5e6fe902`:

| Проверка | Результат |
| --- | --- |
| `TestRefreshSingleFlight` | **RED**: `assert 11 == 10` — две публикации (v10 и v11), `llm.calls == 2`; далее краснеют `busy` (`status='ok'`) и `transport.calls` |
| пробник «два одновременных force-прогона, пустой банк, медленная модель» | **воспроизводит находку ревьюера дословно**: `run1: ok count=1 version=1`, `run2: ok count=1 version=2`, итог `version=2`, в банке `['правило второго прогона']`, **потеряно `['правило первого прогона']`**, вызовов модели 2 |
| тот же пробник на исправленном коде | `run1: ok count=1 version=1`, `run2: busy count=0 version=0 rules=0 published=False`, итог `version=1`, правило первого прогона на месте, вызовов модели 1 |

Откат мутации проверен: `git diff --numstat` после отката снова `73/8`
(`services/anticliche_worker.py`), набор — `141/0`; рабочее дерево содержит только
правку этой задачи.

## Прогоны (03.11.2026, ветка `feat/ac-data-sources`)

- `pytest tests/test_anticliche_sources_ac_data.py -q` — **68 passed** (было 66; +2 новых).
- Затронутые 12 файлов (`test_anticliche_*` x5, `test_pg_db`, `test_round1025_f8_registry`,
  `test_external_log_round1024`, `test_budget_*_round1024` x4) — **363 passed, 0 failed**
  (было 361; +2 новых теста).
- Контракт событий/воркеров (`test_agentic_events_round1026`, `test_mca13_event_contract_round1027`,
  `test_mca17a_observability_core_round1027`, `test_mca17_sleep_memory_workers_round1050`,
  AC-DATA) — **259 passed, 1 failed**: `test_mca17a_observability_core_round1027.py::
  test_registry_event_names_exist_in_code` (`direct.reply: {'mca07_answer_cache'}`) —
  предсуществующее падение, воспроизведено ревьюером на базе `4e470cf7`, к AC-DATA и к
  этой правке отношения не имеет (файл `services/direct_chat_service.py` вне диффа).

## Что осталось (не расширял пакет)

- **N11.** `apply_manual` (PUT `/api/anticliche`) остаётся вне замка: ручная правка —
  это осознанная полная замена списка, но PUT во время идущего прогона может быть
  перекрыт его публикацией (та же природа «полная перезапись списка»). Замок на PUT
  задержал бы админскую правку на минуты; решение (ждать/отказывать/не трогать) —
  предмет AC-API, здесь не реализовано.
- **N12.** Legacy-блок `web/app.js:20970-20981` показывает тост «Список анти-клише
  обновлён» независимо от `status` ответа, поэтому `busy` (как ранее `disabled`/
  `fetch_error`) будет объявлен успехом; список перечитывается из `/api/anticliche` и
  показывает реальное состояние. Это долг AC-UI (там же, где `partial_success`/
  `unchanged` выводятся сырым кодом) — UI в AC-DATA не входит.
- **N13.** Замок процессный (`asyncio.Lock`): тик и ручной запуск в этом проекте живут
  в одном процессе (`bot.py` создаёт воркер, API читает `get_runtime_worker()`). При
  выносе HTTP-API в отдельный процесс понадобится `pg_try_advisory_lock` — отдельное
  решение Architect, не эта правка.
