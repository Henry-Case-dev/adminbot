# VMQ-MEM-NEXT — два реальных прямых хода на проде (11.11.2026)

Наблюдение read-only, **не приёмка строк**: фиксирует, что именно измерено на живом ходе, а что
осталось ненаблюдаемым. Снято 2026-11-11, серверное UTC `2026-11-11T11:33:47Z`.

## 1. Откуда снято

| Что | Значение |
|---|---|
| Прод | `git_head c087253dd7afdbcfa0c5ee96927324dc349627b2`, ветка `release/2.58.188`, `app_version 2.58.188` |
| Сервис | `MainPID=3982405`, `NRestarts=0`, `ActiveEnterTimestamp=Wed 2026-11-11 09:21:09 UTC` |
| HTTP | `/healthz` 200 `{"status":"ok","version":"2.58.188"}`; `/api/health` 200 `{"status":"ok"}` |
| Способ | **одно** read-only подключение: `sqlite3.connect("file:<prod.db>?mode=ro", uri=True)` — только `SELECT`; `journalctl` read-only |
| Окно | `since_epoch_utc 1794355200` = `2026-11-11T00:00:00Z` |
| `mca_events` всего | `total_rows 264705`, `MAX(rowid) 264706` |
| Ступень памяти | 2.58.187 @ `952b9ebd` (выкачена ~08:24Z). Прод сейчас 2.58.188 @ `c087253d`; `952b9ebd` — её предок, файлы памяти 2.58.188 не менялись |

Ни одной записи в БД, ни одного изменения кода, ни рестарта, ни изменения индекса этим наблюдением
не выполнено.

Сырой вывод пробы: `C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\vmq-onto-01-3689dd92710d\probe-73e424798b\probe.txt`
(одноразовый каталог прогона). Все существенные строки перенесены ниже дословно, поэтому
**каталог прогона можно закрыть** — этот артефакт от него не зависит.

## 2. Тождество и окно (дословно)

```
=== A. identity ===
since_epoch_utc 1794355200 2026-11-11T00:00:00Z
server_utc 2026-11-11T11:33:47Z
git_head c087253dd7afdbcfa0c5ee96927324dc349627b2
git_branch release/2.58.188
app_version 2.58.188
unit MainPID=3982405 | NRestarts=0 | ActiveEnterTimestamp=Wed 2026-11-11 09:21:09 UTC
http/healthz 200 {"status":"ok","version":"2.58.188"}
http/api/health 200 {"status":"ok"}
```

## 3. Два реальных прямых хода (дословно)

```
=== C. direct turns ===
rows_since_window 8
  2026-11-11T11:15:51Z direct_turn_writer chat= -1004482340693 trace= b5353cfe93da452998a4e300b5e08073 success INFO
  2026-11-11T11:15:52Z direct_turn_delivery chat= -1004482340693 trace= b5353cfe93da452998a4e300b5e08073 success INFO
  2026-11-11T11:15:52Z direct_turn_selection chat= -1004482340693 trace= b5353cfe93da452998a4e300b5e08073 success INFO
  2026-11-11T11:15:52Z direct_turn_context chat= -1004482340693 trace= b5353cfe93da452998a4e300b5e08073 success INFO
  2026-11-11T11:17:00Z direct_turn_writer chat= -1004482340693 trace= 602da61219884954a6c5026d6c3789e2 success INFO
  2026-11-11T11:17:00Z direct_turn_delivery chat= -1004482340693 trace= 602da61219884954a6c5026d6c3789e2 success INFO
  2026-11-11T11:17:00Z direct_turn_selection chat= -1004482340693 trace= 602da61219884954a6c5026d6c3789e2 success INFO
  2026-11-11T11:17:00Z direct_turn_context chat= -1004482340693 trace= 602da61219884954a6c5026d6c3789e2 success INFO
```

Все восемь событий `success` / `INFO`. Это **два** хода (по четыре события на ход), оба в чате
`-1004482340693`, оба **после** выкатки ступени памяти. Других прямых ходов с `00:00Z` не было.

## 4. Периодный добор на этих ходах (дословно)

Две строки журнала `direct: rag block` (по одной на ход):

```
2026-11-11T11:15:41+00:00 vps159032-gqg python[3982405]: 2026-11-11 11:15:41,343 - services.direct_chat_service - INFO - direct: rag block | facts=2 | period_kept=0 | period_rejected_subject=0 | period_kept_despite_empty=0 | vector_pool_miss=0 | period_vector_knn=0 | period_vector_leg=n/a | subject_proxy= | chat=-1004482340693
2026-11-11T11:16:50+00:00 vps159032-gqg python[3982405]: 2026-11-11 11:16:50,911 - services.direct_chat_service - INFO - direct: rag block | facts=4 | period_kept=0 | period_rejected_subject=0 | period_kept_despite_empty=0 | vector_pool_miss=1 | period_vector_knn=0 | period_vector_leg=ok | subject_proxy= | chat=-1004482340693
```

durable-событие периодного вызова — единственное в окне:

```
=== D. memory stage: period_fill retrieval rows ===
rows_since_window 1
  2026-11-11T11:16:49Z mca07_retrieval chat= -1004482340693 trace= None success None vector_leg= ok vector_rows= 0 pool_miss= 1 subject_proxy= {}
period_fill_rows_per_trace {None: 1}
--- D1 all-time period_fill rows (last 5) ---
  2026-11-11T11:16:49Z mca07_retrieval chat= -1004482340693 vector_leg= ok vector_rows= 0 pool_miss= 1
```

`D1` — запрос **без** фильтра по времени (`usage_json LIKE '%"period_fill"%'`, последние 5): вернулась
ровно одна строка. То есть `11:16:49Z` — **первая и единственная** строка `period_fill` за всю историю
таблицы, а не «одна из многих в окне».

### 4.1. Ход 1 (`b5353cfe…`, 11:15:38 → 11:15:52)

`period_vector_leg=n/a`, `vector_pool_miss=0`, все периодные счётчики `0`, `facts=2`.
`n/a` — значение по умолчанию: `_rag_period_stats` остаётся пустым, когда добор **не запускался**
(`services/direct_chat_service.py:13714`, печать — `14274`). Значит на этом ходу периодной ноги не
было вообще, и это **нормальный пропуск**, а не деградация: правило `auto` требует
`usable >= max(1, limit // 2)` (`13749–13754`), а в срезе было 2 факта при `limit=8`
(`limits.graph_rag_facts_limit=8`), т.е. `usable < 4` → `return rows` до всякого добора.
Деградацией это не является: лексическая и векторная половины добора на этом ходу просто не
вызывались, ошибок нет.

**Граница честности:** `n/a` доказывает «нога не предпринималась», но не различает ветки
«пропуск по `usable`» и «политика `operative`» — политика хода в строку `direct: rag block` не
печатается. Совпадает с пропуском по `usable` (фактов 2 при пороге 4), `operative`-маркеров нет.

### 4.2. Ход 2 (`602da612…`, 11:16:46 → 11:17:00)

`period_vector_leg=ok`, `vector_pool_miss=1`, `period_vector_knn=0`, `period_kept=0`,
`facts=4`. Векторная нога **запустилась**, вернула 0 строк, и промах записан честно:
`vector_pool_miss = 1 if not rows else 0` (`services/summary_memory.py:6923`) — не «тихий успех».
durable-строка `mca07_retrieval` (`11:16:49Z`, `success`) несёт ровно те же значения
(`vector_leg=ok`, `vector_rows=0`, `pool_miss=1`), т.е. журнал и `usage_json` согласованы.

Одна нога на ход: за окно **одна** строка `period_fill` на **один** ход с периодным добором
(`period_fill_rows_per_trace {None: 1}`), второй ступени/второго operative-прохода нет.
`'period vector leg'` в журнале — `0` (этот маркер пишется только в отказной ветке guard'а).

**Граница честности:** у `mca07_retrieval` `trace_id = None`, поэтому привязка строки к ходу
сделана по времени (11:16:49Z внутри 11:16:46→11:17:00) и чату, а не по трассе. «Ровно одна нога»
следует из количества строк (1) и отсутствия второй, а не из trace-связи.

## 5. Обстановка вокруг (дословно, счётчики)

```
--- G1 pattern counts (window) ---
  'direct: rag block' 2
  'period vector leg' 0
  'rag block absent' 0
  'unified rag retrieval failed' 0
  'rag facts failed' 0
  'ADMITTED_COMPATIBLE' 40
  'not serviceable' 8
  'embedding index serviceable' 40
  'compat_not_proven' 0
  'period_fill' 1
```

Индекс: 40 строк `SmartModule: embedding index serviceable | index=graph_facts_vec | class=ADMITTED_COMPATIBLE`
(включая `11:15:38`, `11:16:46`, `11:16:52`, `11:17:08`, `11:17:10` — то есть и на самих ходах),
**ноль** строк `compat_not_proven` и **ноль** `not serviceable` по `graph_facts_vec`.

Восемь `WARNING` `not serviceable` — все про другой индекс, дословно:

```
2026-11-11T11:11:12+00:00 vps159032-gqg python[3982405]: 2026-11-11 11:11:12,663 - services.summary_memory - WARNING - SmartModule: embedding generation not serviceable | index=smart_archive | status=superseded | gen_fp=2d0efab0e817 new_fp=2d0efab0e817 тАФ FTS-only (A06) | build pending тАФ source empty (nothing to vectorize)
```

(`тАФ` — артефакт кодировки вывода пробы, в журнале там длинное тире; смысл строки — «источник пуст,
векторизовать нечего».) Это ровно тот `smart_archive = source_empty`, который уже разобран в
`../index-compat-diagnosis.md`; к `graph_facts_vec` и к периодной ноге отношения не имеет.

Ошибки памяти в окне:

```
--- G3 generic error counters (no text) ---
  'Traceback' 23
  'CRITICAL' 0
  ' ERROR ' 12
  'database is locked' 23
  'TimeoutError' 0
  'asyncio.Timeout' 0
  'fail-open' 0
  'CancelledError' 0
```

**Граница честности:** специфичные для ступени памяти шаблоны — нулевые
(`unified rag retrieval failed` 0, `rag facts failed` 0, `fail-open` 0, `TimeoutError` 0,
`asyncio.Timeout` 0, `CancelledError` 0, `CRITICAL` 0). Но общие счётчики журнала за сутки
(`Traceback` 23, `'database is locked'` 23, `' ERROR '` 12) **не разобраны** этой пробой:
она их только посчитала, контекст не извлекался. Утверждать «в окне нет ни одной ошибки вообще»
нельзя; утверждается только «нет строк ошибок ступени памяти».

Аномалии (`E`), весь список за окно — одна строка, и она не про память:

```
anomaly_rows 1
  2026-11-11T09:56:17Z WARN style_policy success reason= None chat= -1002661910336 err= 
--- E1 retrieval outcomes since window ---
  success reason= None count= 20 2026-11-11T02:26:05Z -> 2026-11-11T11:17:00Z
  skipped reason= embedding_generation_changed count= 8 2026-11-11T01:02:40Z -> 2026-11-11T11:11:12Z
  success reason= episodes_used count= 4 2026-11-11T03:16:05Z -> 2026-11-11T11:16:52Z
```

Детали `style_policy` этой пробой не сняты: фильтр аномалий брал только не-`INFO` строки и не
раскрывал `error_json` (он пуст). Строка `WARN` уровня `style_policy` — в другом чате; к ступени
памяти она не относится и за её дефект не выдаётся.

## 6. Как это читается по коду `952b9ebd` (проверено `git show`, не по памяти)

| Клауза | Код | Следствие для наблюдения |
|---|---|---|
| `k = 32` | `_RAG_PERIOD_POOL = 32` (`services/direct_chat_service.py:13663`) → передаётся как `limit` (`13789–13791`) → `fetch_k = max(1, limit)` (`services/mca_retrieval_context.py:1498`) → `period_fill_candidates(..., k=fetch_k)` (`1696–1710`) → SQL `embedding MATCH ? AND k = ?` (`services/summary_memory.py:6886–6890`) | `k` — константа кода, протянутая через три звена; **в телеметрию не попадает** |
| `k` не в телеметрии | `period_fill_candidates` пишет `stats["vector_pool"] = k` (`summary_memory.py:6921`), но durable `usage_json.period_fill` собирается только из `vector_leg`, `vector_rows`, `vector_pool_miss`, `subject_proxy` (`mca_retrieval_context.py:1921–1929`); в строке журнала `k` тоже нет (`direct_chat_service.py:14264–14276`) | по одному ходу `k=32` **не проверяемо**; `period_vector_knn` — это число оставленных knn-строк (`13813–13814`), а не `k` |
| `period_vector_leg` | `"ok"` (`summary_memory.py:6919`), `"error"` (`6929`), `"embed_unavailable"` (`6873`), код guard'а (`6864`), `"unsupported_memory"`/`"error"` (`mca_retrieval_context.py:1698–1715`); печать `"n/a"` при пустых статах (`14274`) | `ok` = нога выполнена и вернула результат; `n/a` = нога не предпринималась |
| `vector_pool_miss` | `1 if not rows else 0` (`summary_memory.py:6923`) | `1` при `ok` = честно записанный промах пула, а не успех |
| `subject_proxy` | гистограмма только по строкам с `period_fill=True` (`direct_chat_service.py:3437–3446`); durable-счётчик — по периодным строкам и `period_vector_ids` (`mca_retrieval_context.py:1927`) | пустое `subject_proxy` означает «периодных строк не было», а не «поле сломано» |
| пропуск добора | `usable < max(1, limit//2)` → `return rows` (`13749–13754`) | пропуск на ходу 1 — нормальное поведение правила |
| `period_kept` | считается по фактически показанному `kept ∩ period_keys` (`14192–14199`) | `0` на обоих ходах = в блоке не осталось ни одной периодной строки (согласуется с `period_vector_knn=0`) |

## 7. Что эти два хода доказывают, а что нет (по клаузам приёмки `VMQ-NEXT-01`)

| Клауза приёмки | Состояние | Основание |
|---|---|---|
| Одна периодная нога на ход, и на operative её нет | **частично** | одна строка `period_fill` на один ход с добором (`{None: 1}`), второй ноги нет; operative-хода в окне не было вообще — «ноль на operative» не наблюдалось |
| Векторная нога действительно исполняется | **да** | `period_vector_leg=ok` + `vector_rows=0` в durable-строке и в журнале |
| `period_kept` честный | **да (для этих двух ходов)** | `0` и в журнале, и по коду `14198`; `period_vector_knn=0`, `subject_proxy=` — согласованы |
| `vector_pool_miss` записывается | **да** | `1` при `ok` и `0` строк — ровно ветка `6923` |
| `subject_proxy` для векторной строки (ближайший сосед, не оракул) | **не наблюдалось** | нога вернула 0 строк (`11:16:50` и `11:16:49`), векторных строк не было; на ходу 1 добор не запускался |
| `k = 32` на ходе | **не наблюдаемо** | поле `vector_pool` в телеметрию не пишется (`mrc:1921–1929`) |
| Доставка старой строки в блоке в пределах `k=32` | **не наблюдалось** | обе строки `period_kept=0`; доставки не было ни одной |
| Отклонение при `state != compatible` | **не проверялось** | индекс допущен (`ADMITTED_COMPATIBLE`), отказная ветка не наступала (и `'period vector leg'` = 0) |
| `operative` байт-в-байт, без векторной ноги | **не наблюдалось** | operative-ходов в окне нет |

Вывод: два хода закрывают «нога исполняется, промах записывается, `period_kept` не врёт» и **не**
закрывают `subject_proxy` на реальной векторной строке, `k`, доставку и operative-паритет.

## 8. Честная поправка к прежней формулировке «ходов не было»

Формулировки `release-2.58.187.md` §6 («Турновые события: 0», «Строки `direct: rag block`: 0»,
«реального хода direct-чата в окне не было»), `next_executable.blocked_by` («строк
`period_vector_leg=…` — 0») и `stage_2_58_187_2026_11_11.distinction.per_turn_behaviour`
(«`turn_events=0`, `period_fill_events=0`») были верны **только до 11:15Z** 11.11.2026.

Точный момент, с которого они перестали быть верными:

- `11:15:41Z` — первая строка `direct: rag block` (`period_vector_leg=n/a`);
- `11:16:50Z` — первая строка с `period_vector_leg=ok`;
- `11:16:49Z` — первая и единственная за историю таблицы строка `period_fill` в `usage_json`.

Повторять «ходов не было» или «`period_fill` = 0» после 11:15Z нельзя. Прежние записи не
переписываются задним числом: они остаются верными для своего окна наблюдения (`08:24→09:04Z`,
проба ~11:11Z) и здесь помечены как устаревшие с точным моментом.

## 9. Что осталось непроверенным и не является «задачей владельца»

Всё ниже — внутренние технические наблюдения агентов, не действия владельца:

1. Реальный ход, на котором векторная нога вернёт **хотя бы одну** строку → появится `subject_proxy=knn`.
   Триггер: следующий прямой ход исторического/`auto` вопроса с `usable >= 4`; проверяется той же
   read-only пробой, новых изменений не нужно.
2. `operative`-ход после выкатки (паритет, отсутствие векторной ноги) — наблюдается сам по себе.
3. `k=32` на ходе — не наблюдаемо без аддитивного поля (`vector_pool`) в телеметрии; это вопрос
   следующей утверждённой ступени, а не замера.
4. `knn_ms`/`fts_ms` — таких полей в продукте нет (`git grep` по `952b9ebd`: в `services/` их нет),
   поэтому раздельные тайминги ног — тоже аддитивная телеметрия, а не измерение на копии.
