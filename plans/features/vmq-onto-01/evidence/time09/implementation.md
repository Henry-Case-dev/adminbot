# VMQ-TIME-09 — покрытие памяти по годам ОДНОГО прогона (Status + Аналитика)

Статус: **REVIEW** (кандидат собран и проверен Builder'ом; независимого
review/деплоя не было). Production не менялся, deploy/SSH/БД не трогались.

| Параметр | Значение |
|---|---|
| База | `f68e7631dede326995b985bf8c3849d62def1bcb` (2.58.217, content `b6c9bb0b`, schema 48) |
| Ветка | `fix/vmq-time09` (tip corrective R1 — `ee94ddf9`) |
| Контракт | `plans/features/vmq-onto-01/evidence/time09-ui-brief-2026-11-19.md` |
| Product-коммит | `738bd3a2` (исходный), `ee94ddf9` (corrective R1 по `review-r1.md`) |
| Бампа/манифеста/деплоя | нет |

## 1. Что реализовано

Обе поверхности показывают **один выбранный ход** (не среднее, не «за 24ч»):

- **Status `#/`** — компактная секция внутри существующей карточки
  «Мониторинг интеллекта»: после «Здоровья памяти», до «Инициативы».
  Строки: годы Writer-фактов (чипы), «Исключено» (пять причин), ссылка
  «Подробнее в Аналитике». При отсутствии/усечении — честная подпись.
- **Аналитика → «Память и интеллект»** — карточка после «Цикл памяти (24ч)»
  и до «Embeddings»: Writer-блоки (факты/эпизоды отдельно), список вызовов
  `retrieve()` (3 видимых + остальные в `<details>`), причины исключений,
  `memory_period` раскрытием, «← предыдущий ход» / «следующий →»
  (существующий `turn` 1..8), ⟳.
- Процентов, шкал, донатов/радиалов, KPI-плиток и таблиц нет. Только целые
  счётчики этого прогона; `years` — чипы; причины — подписи + числа.
- 44 px у кнопок ⟳/навигации — inline `min-width/min-height` (app.css
  байт-идентичен, новых CSS-переменных/цветов/радиусов нет).

## 2. Данные и минимальный backend

Канон — per-turn trace, связка по одному `trace_id`:

| Источник | Поля | Изменение |
|---|---|---|
| `direct_turn_selection` | `blocks[].years` (+`years_present`), `memory_period` | API-проекция (схема), producer не менялся |
| `mca07_retrieval` | `usage_json.years`, `excluded`, `period_fill` | `RetrievalRequest.trace_id` + emit |
| `GET /api/direct/turn-diagnostics` | `retrieval[]`, `stages.retrieval`, `selection.*` | аддитивно; новый endpoint НЕ вводился |

Точечные правки producer'а:

- `services/mca_retrieval_context.py` — `RetrievalRequest.trace_id: str | None
  = None`; `trace_id=request.trace_id` в invalid- и основном emit.
  `None` — событие без поля (проверено durable-строкой), отбор/ранжирование/
  бюджеты/лимиты не менялись.
- `services/direct_chat_service.py` — аддитивный проброс `correlation_id`
  через `_rag_retrieve` → `_rag_unified_rows` → `_build_rag_block`
  (включая period-selection emit) и `_build_old_episodes`;
  `_apply_plan_memory_scope[_locked]` получает trace из `_handle_turn`.
  При `trace_id=None` kwarg в `_rag_retrieve` не добавляется — старые
  двойники/тесты с узкой подписью работают прежним путём.

Контракт `retrieval[]` (R17-safe, только коды/числа):

```json
{"ts": 1795..., "outcome": "success|silent", "reason_code": "...|null",
 "policy": "auto|historical|operative", "period": false,
 "years": {"2023": 2}, "years_present": true,
 "excluded": {"policy_operative": 4, "status": 3, "expired": 0,
              "relevance": 1, "budget": 2}, "excluded_present": true}
```

- `years_present`/`excluded_present`: измеренный `{}` ≠ отсутствие данных;
  измеренный пустой `excluded` остаётся `{}` (UI: «исключений не было»),
  при наличии причин — закрытый набор из пяти ключей, отсутствующие = 0.
- `period_selection` в `retrieval[]` не попадает (данные уже в
  `selection.memory_period`; иначе двойной счёт годов).
- Список bounded: отдельный запрос `limit=32`, в ответе ≤6 вызовов,
  сортировка по `ts`; окно 400 строк не расширялось.
- `stages.retrieval` — bool; старые ключи не переименованы.

UI-helper: новый `web/static/status-analytics.js` (UMD, 342 строки) —
`sortedYears`/`yearsText`/`exclusionRows`/`exclusionText`/`writerBlocks`/
`primaryRun`/`latestRun`/`sortRuns`/`view`. Один store/loader
`memoryYearCoverage` на обе поверхности, TTL-кэш 15 с, без фонового опроса;
запрос — ровно один на вход/⟳/смену чата (смена чата отбрасывает чужой
ответ по `seq`, single-flight только для того же ключа). Aggregate
`/api/memory/retrieval-coverage` не вызывается ни разу.

## 3. Изменённые файлы (product)

| Файл | Δ |
|---|---|
| `services/mca_retrieval_context.py` | +9/−1 |
| `services/direct_chat_service.py` | +39/−19 |
| `web/api/routes.py` | +158/−2 |
| `web/app.js` | +189/−0 |
| `web/index.html` | +263/−0 |
| `web/static/status-analytics.js` | +342 (новый) |
| **Итого product** | **+1000/−22** |

Тесты: `tests/js/vmq_time09_year_coverage_ui_test.js` (+264),
`tests/test_vmq_time09_turn_coverage.py` (+605),
`tests/ui_vmq_status_analytics_e2e.py` (+458); атомарно обновлены точные
`stages`-assert'ы в `tests/test_ur_f_inspector_step2.py` (2 строки) и
осознанно переутверждён `ROUTES_SHA256_F11` в
`tests/test_round1025_f8_registry.py` / `tests/test_mca23_planned_vs_actual.py`
(новых endpoint'ов нет; hash
`4faa0a5379a9943d7b0f11403a051777eb779a033c3bc069a1b3300cb7392ee7`).

Байт-идентичны (проверено `git status`): `web/static/app.css`, `web/app.py`,
`handlers/web.py`, `web/api/memory_overview.py`,
`services/memory_diagnostics.py`. DDL/схема не менялись (48), новых флагов,
таблиц, store, endpoint'ов, LLM-вызовов и probe-ов нет.

## 4. Проверки

Полные результаты — `tests-time09.json`, `time09-playwright.json`,
`mutations-time09.json`, RED — `red-base-time09.txt/json`.

| Проверка | Результат |
|---|---|
| RED на базе `f68e7631d` (до кода) | node падает (нет helper), pytest 11 failed/1 passed, Playwright 27 проверок failed |
| node helper | `VMQ-TIME09-UNIT-OK` |
| новый pytest | 13 passed (trace_id, parity, durable-связь, years/memory_period, bounded/сорт/period_selection, cap 8→6, пусто≠неизвестно, R17, 403, truncated) |
| `test_ur_f_inspector_step2.py` | 19 passed |
| affected pytest | 482 passed |
| mandatory 386 | 386 passed |
| JS full | 124 файла, 4 failed — ровно базовые (чистый worktree базы: 123 файла, те же 4); регрессий 0 |
| Playwright 1280/390/320 | 66/66 проверок, `ok=true`; console/pageerror 0; overflow 0; `retrieval-coverage` = 0 вызовов |
| мутации M1–M4 | каждая падает на целевом node-тесте и откатывается |
| M5 (опц.) | падает на целевом pytest (period_selection в `retrieval[]`) |

Визуальные артефакты (temp, не перезаписывают tracked evidence):
`WorkspaceData/temp/intelligence/vmq-time09-<hash>/tmp/time09-shots/` —
`time09_status_1280.png`, `time09_analytics_1280.png`,
`time09_analytics_turn2_1280.png`, `time09_status_after_return_1280.png`,
`time09_unknown_excluded_1280.png`, `time09_zero_writer_1280.png`,
`time09_block_390.png` (390×390), `time09_block_320.png`, плюс полные
390/320. Просмотрены: секция после «Здоровья памяти», карточка между
«Циклом памяти» и «Embeddings», чипы переносятся, 44 px, без обрезки;
F1–F4 закрыты на реальном рендере (ход 2 подписан «ход 2 из 2», возврат в
Статус снова показывает последний ход).

**Browser Use:** blocked — `BU_CDP_URL=http://127.0.0.1:9222` недоступен
(нет выделенного Chrome с `--remote-debugging-port=9222`). Это не отменяет
Playwright-прогон; зафиксировано как ограничение.

## 5. Честные ограничения

1. **Нет реального хода после выката.** Код ещё не задеплоен, поэтому
   «один настоящий ход» с `mca07_retrieval.trace_id` не снимался. После
   деплоя нужен агентский live-чек (не владельца): SQL
   `SELECT ts, trace_id, chat_id, outcome, reason_code, usage_json FROM
   mca_events WHERE trace_id=... ORDER BY ts` и сверка с UI; при отсутствии —
   `delivered_awaiting_evidence`.
2. **Старые ходы.** События до деплоя не имеют `trace_id` у retrieval:
   UI показывает Writer-часть и «событий retrieval с привязкой нет» —
   юнит-покрыто, live не наблюдалось.
3. **`period_selection` не durable.** Producer эмитит outcome `selection`,
   который контракт событий не сохраняет; фильтр в API защитный и проверен
   синтетической строкой слоя, а не «живым» событием. Двойного счёта в
   проде фактически нет, но защита остаётся.
4. **Усечение selection** проверено приведением реальной durable-строки к
   состоянию `truncated=true` (штатный упаковщик на тесте не переполнялся);
   API/UI не подставляют `{}` и говорят «не зафиксировано».
5. **Playwright** использует стабы из реальных payload-схем, не прод-БД;
   TUI/реальный чат остаются post-deploy проверкой.
6. `mca_events` имеет retention — evidence реального хода снимать сразу.
7. Cap `retrieval[]` = 6 (первые по времени); при >6 вызовах самые поздние
   не показываются — для одного хода практически недостижимо, но это
   осознанная граница.

## 6. Вопросы Reviewer'у

1. Достаточно ли `stages.retrieval` + обновлённых точных assert'ов, или
   нужен отдельный тест обратной совместимости старой трассы (сейчас
   проверяется `retrieval: False` в двух существующих тестах)?
2. Приемлем ли осознанный re-pin `ROUTES_SHA256_F11` (без новых endpoint'ов
   и без переиздания `f8_baseline`) по L-F11S-1?
3. Корректен ли выбор «первые ≤6 по времени» вместо «последние 6»?
4. Достаточно ли inline `min-width/min-height: 44px` на четырёх кнопках
   (app.css байт-идентичен) или требуется иной путь без правки CSS?
5. Нужен ли `years_present` у Writer-блока (добавлен сверх минимального
   `years`), чтобы отличать измеренный `{}` от «не зафиксировано»?

## 7. Corrective R1 по независимому ревью (`review-r1.md`, `3507b8f3`)

Вердикт R1 — NEEDS FIXES; все четыре IN_SCOPE дефекта воспроизведены
Reviewer'ом на реальном рендере и исправлены точечно (product-коммит
`ee94ddf9`). RED новых assertions на tip `eefd555c` — до правок:
`red-corrective-time09.txt/json` (node F1; Playwright 11 failed: F1–F4/B6/B7;
pytest 13 passed — cap-тест B1 закрывает пробел, поведение уже было верным).

| # | Исправление | Место |
|---|---|---|
| F1 | `_runView` возвращает `yearsPresent` (и `emptyText`); шаблон больше не печатает «нет данных» рядом с годами | `web/static/status-analytics.js:203-233`; шаблоны `web/index.html:9502/9529` |
| F2 | `excluded_present=false` → «Исключено: нет данных»; `exclusionText` уже отдаёт «нет данных» для пустого измерения | `web/index.html:15615` + `status-analytics.js:exclusionText` |
| F3 | `years_present=true` + `years=null` → «нет фактов»; unknown остаётся «нет данных» | `status-analytics.js:134`, `:218` |
| F4 | вход в Статус сбрасывает `turn=1`; подпись `turnLabel` — «последний ход» только для turn=1, иначе «ход N из M»; `no_selection` — «выбранного хода»; при смене хода старые числа скрываются до ответа | `web/app.js:28941`, `:10275`; `status-analytics.js:238`; `index.html:9447/15588` |
| B1 | новый pytest: 8 вызовов → ровно 6 первых по `ts` | `tests/test_vmq_time09_turn_coverage.py::test_api_retrieval_cap_is_six_first_by_time` |
| B6 | дубль «последний ход» убран из заголовка Status | `web/index.html:15562` |
| B7 | `aria-busy` на контейнерах обеих поверхностей | `web/index.html:9406/15560` |
| B8 | измеренный ноль retrieval показывает `retrieval_empty` | `status-analytics.js:_runView.emptyText`, `index.html:9503/9530` |
| B9 | комментарий re-pin исправлен на 63 уникальных пути | `tests/test_round1025_f8_registry.py` |

Не менялось осознанно: B3 (`latestRun` — обязательный helper брифа §5.1,
UI использует `primaryRun`), B4 (явный `trace_id` — поле store по брифу
§3.1), B5 (маркер «показаны не все» — cap=6 недостижим, расширение scope
не требуется).

После фикса: node OK; pytest **13 passed**; affected **482 passed**;
mandatory **386 passed**; JS full 124/4 = база; Playwright **66/66**
(console 0, overflow 0, aggregate 0), скриншоты включают
`time09_analytics_turn2_1280.png`, `time09_unknown_excluded_1280.png`,
`time09_zero_writer_1280.png`, `time09_status_after_return_1280.png`.
Мутации M6–M9 (каждая — падение целевого node-теста, откат) в
`mutations-time09.json`.
