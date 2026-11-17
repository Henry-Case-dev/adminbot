# SCH — Scheduler: блокировка event loop и misfire (LVS-SCH-01..05)

- Дата: 2026-11-18
- Слайс: `SCH` эпика `llm-vision-scheduler-p0` (position 1, P0)
- База: deployed `ea9f760f` (2.58.214), ветка `release/mod-acl-w2b3-2.58.214`
- Ветка: `fix/p0-scheduler-loop`, worktree
  `WorkspaceData/worktrees/.../p0-scheduler-loop-0e77d29079bd-f6ad282d`
  (housekeeping `worktree-path` + `register-worktree`, unit `builder-sch`)
- Кандидат: `28c0e7c8`
- Статус: REVIEW (не VERIFIED, не bump, не deploy)
- Требования: LVS-SCH-01, LVS-SCH-02, LVS-SCH-03, LVS-SCH-04, LVS-SCH-05
- Карта `requirements-map.json` и `progress_scope.json` не редактировались.

## 1. Что исправлено

| Блок | Файл:строка (кандидат) | Изменение |
|---|---|---|
| B1 (primary) | `services/slot_claims.py:448`, `:475` | `store.try_claim(...)` → `await asyncio.to_thread(store.try_claim, ...)` в обеих ветках (due → fire, окно прошло → честный skip). Схема, `INSERT OR IGNORE`/CAS, `timeout=5`, `busy_timeout=5000` и возвращаемая семантика не менялись; соединение по-прежнему создаётся внутри вызова — уже в worker-thread. |
| A (lifecycle) | `summary_scheduler.py:69,176`; `goodmorning_scheduler.py:42,116`; `nostalgia_worker.py:160,941`; `uptime_heartbeat.py:30-31,69,74`; `lore_worker.py:267,444`; `dream_worker.py:293,659,670`; `memory_maintenance.py:180-182,366-473`; `memory_backup.py:54,82` | Явный `misfire_grace_time` вместо заводского 1 s APScheduler 3.x. Значения по джобам: 30 / 30 / 30 / 30+300 / 60 / 300+300 / 60+300+3600 / 3600. |
| B2 (backpressure) | `services/summary_scheduler.py:216-258` | Разделены фазы: сначала claim всех due-чатов в `due_chats`, затем `generate_and_send` по списку. Порядок чатов и `chat_timeout` сохранены, новой конкурентности нет. |
| B3 (same class) | `services/publication_coordination.py:782,877,892,911,923,937,952,967` | `precheck/snapshot`, `acquire` (включая manual-retry), `begin_sending`, `release`, `claim_manual_priority`, `release_manual_priority` — sync store-вызовы переведены в `asyncio.to_thread`. CAS/таблица/release-event не менялись. Включено после RED-теста (см. §2). |

Не тронуты: L1/модель/LLM-клиент, Vision, QRNG, UI, `meme_initiative` и
`memory_backup` sync-fallback (B4 — backlog, не доказаны), таблицы/CAS,
порядок роутеров. `vision_media_tick` (30 s) и anticliche (3600 s) уже имели
grace — не менялись (проверяется статическим тестом по всем `add_job`).

## 2. RED на базе `ea9f760f` (измерено)

`tests/test_p0_scheduler_loop.py` на базе (финальная версия тестов): **6
failed / 4 passed**.

| Сценарий | RED-факт на базе |
|---|---|
| B1 claim при чужом write-lock 500 ms | max gap event loop = **546 ms** (тест падал на `gap < 0.1`); в предыдущем прогоне 532 ms; claim завершился только после release |
| B3 publication acquire при том же lock | max gap = **547 ms** |
| B2 claim-first summary | claim второго чата отсутствует, пока идёт первый прогон → `second is not None` падает |
| uptime late run | `job.misfire_grace_time == 1` (заводской) |
| runtime job contract | `summary_job: grace=1, ожидалось 30` |
| static add_job contract | 18 вызовов `add_job` без `misfire_grace_time` |

Четыре теста на базе проходят осознанно: exactly-one claim + CAS (поведение
не должно меняться), «один INSERT на запуск» (heartbeat уже был идемпотентен),
и оба сценария APScheduler misfire — это проверка механизма библиотеки
(grace 1 s → skip, grace 5 s → один запуск), а не дефекта продукта.

## 3. GREEN на кандидате `28c0e7c8`

`tests/test_p0_scheduler_loop.py`: **10 passed**.

Измерено тем же сценарием (lock 500 ms, probe 5 ms):

```text
slot_claim:   gap_ms=16.0  claim_ms=544  action=fire  fired=1
publication:  gap_ms=16.0  claim_ms=540  granted=True
```

Ожидание осталось (≈0.54 s внутри worker-thread, как и требует lock), но loop
свободен: gap 16 ms против 546/547 ms на базе (в предыдущем прогоне 532 ms).

Дополнительные проверки в тестах:

- ровно один claim на слот; второй вызов → `skip_busy`; строка `fired=0`
  перебронируется CAS при смене instant (атомарность сохранена);
- claim-first: пока первый чат «генерируется», строка второго уже `fired=1`,
  `reason_code=''`; после завершения — оба чата по порядку; повторный тик в
  том же due-окне не даёт дублей и не пишет `missed_slot_expired`;
- uptime: ровно 1 INSERT на запуск, два разных запуска → 2 строки; late run в
  пределах явного grace (30 s) → ровно 1 INSERT;
- publication: после освобождения lock бронь выдана, `claimed → sending →
  release` пишет watermark (`last_publish_kind=initiative`), т.е. publish-
  контракт не изменился;
- runtime-контракт: у всех запущенных сервисов (summary, goodmorning,
  nostalgia, lore, dream, memory maintenance, memory backup, uptime) grace
  равен ожидаемому, `coalesce=True`, `max_instances=1`, grace ≤ интервала;
- статический контракт: каждый `add_job` в `services/*.py` объявляет
  `misfire_grace_time` (после фикса — 0 нарушений).

## 4. Мутации (каждая убивает тест)

| Мутация | Результат |
|---|---|
| M1: вернуть sync `store.try_claim` в loop | KILLED — 1 failed |
| M2: вернуть sync `self._store.acquire` в loop | KILLED — 1 failed |
| M3: переплёл claim+generate (старое поведение) | KILLED — 1 failed |
| M4: убрать grace у `summary_job` | KILLED — 2 failed |
| M5: убрать grace у `uptime_heartbeat` | KILLED — 2 failed |

Скрипт мутаций восстанавливал исходное содержимое после каждого прогона.

## 5. Регрессии (затронутый neighbourhood)

Все прогоны: `pytest -q -p no:randomly`, worktree кандидата.

| Батч | Результат |
|---|---|
| `test_p0_scheduler_loop` + `test_summary_scheduler` + `test_ur_c_sched` + `test_uptime_heartbeat` | 43 passed |
| `test_scheduler` + `test_goodmorning` + `test_lore_worker` + dream-батч (7 файлов) | 178 passed |
| nostalgia-батч (10 файлов, включая `test_qnd_schedule`, `test_qnd_publication`) | 167 passed |
| `test_memory_maintenance` + `test_memory_communities_maintenance` + `test_memory_backup` | 37 passed |
| `test_p0_meme_publication_hotfix` + `test_publication_binding_delivery` + `test_qnd_publication` + `test_initiative_publications_api` | 103 passed |
| `test_evol014_meme_initiative` + `test_meme_init_diagnostics` + `test_p0im_s5_meme_marker_interrupt` | 128 passed |
| `test_database` + `test_hot_config` + `test_mca01_tx_task_supervisor_round1027` + 4 migration/schema файла | 188 passed, 1 failed |
| `test_initiative_coordination` | 56 passed, 4 failed |

Итого по neighbourhood: **900 passed**, 5 failed — все 5 **воспроизведены на
базе `ea9f760f`** (отдельный detached worktree, удалён после проверки):

- `test_initiative_coordination`: `test_act_on_opportunity_conflict_defers_to_intent`,
  `test_evaluate_phase_precheck_blocks_before_llm`,
  `test_t1_nostalgia_delegated_refusal_sends_nothing`,
  `test_t5_every_text_send_site_passes_publish_guard` — 4 failed и на базе, и на
  кандидате (базовый прогон с базовым `publication_coordination.py` дал те же
  node id; diff их не вызывает и не лечит);
- `test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer`
  — 1 failed на базе и на кандидате (`meme_initiative.py`,
  `prompt_release_policy.py` — файлы вне diff).

Полный `tests/` — 21 770 тестов, не запускался (вне слайса). «Mandatory 386»
в артефактах карты/плана не зафиксирован как список файлов/узлов, поэтому
вместо реконструкции неизвестного набора выполнен полный затронутый
neighbourhood (900 passed).

## 6. Конфигурация

- Новых флагов/env/hot-ключей нет; значения grace — код-константы рядом с
  каждым планировщиком, поэтому effective-config пользователя не меняется.
- `misfire_grace_time` — целые секунды (APScheduler 3.11.3 отвергает float:
  `misfire_grace_time must be either None or a positive integer`).
- `timeout=5`/`busy_timeout=5000` сохранены: ожидание теперь в worker-thread,
  не в loop.
- Порядок/частота работ не менялись; затронуты только graceful-окна и место
  ожидания.

## 7. Ограничения и честные границы

- `PublicationCoordinator.available()` остаётся sync (`table_present()` —
  чтение `sqlite_master`): это не 5-секундный write-wait, публичный sync-API
  используется и вне async-путей; в B3 не входит.
- `asyncio.to_thread` использует default executor: массовых параллельных
  claim'ов нет (тик summary последовательный, goodmorning последовательный),
  каждая операция короткая; лимит потоков default executor не менялся.
- Grace не восстанавливает пропущенную минуту `uptime_heartbeat` — поздний
  sample пишется, разрыв в истории остаётся честным; это не «разрывов нет».
- Postdeploy-замер lag и отсутствие WARN 09:21-типа — задача DevOps после
  деплоя (не выполнялось).
- Реальный provider/LLM-прогон для этого слайса не требуется (блок был до
  генерации).
- 5 падающих тестов — pre-existing на базе, не кандидаты на исправление в
  этом слайсе.
- Claim-first резервирует слоты всех due-чатов ДО генерации. Если процесс
  упадёт между claim и генерацией позднего чата, его слот останется `fired=1`
  без фактического прогона — та же потеря работы, что раньше записывалась как
  `missed_slot_expired`, но строка уже не покажет пропуск. Durable run-state /
  смена CAS-семантики запрещены scope; postdeploy-проверка должна сверять
  `slot_claims` с `summary_runs`, а не только отсутствие WARN.

## 8. Гигиена

- `git diff --check` чист; EOL/BOM файлов совпадают с базой (после правки
  CRLF-флипа у `summary_scheduler.py`, `uptime_heartbeat.py`,
  `publication_coordination.py` diff снова минимальный).
- Временный detached worktree для base-проверки удалён без force; временные
  скрипты измерений/мутаций лежат вне репозитория.
- Production не затрагивался; артефактов на сервере не создавалось.
