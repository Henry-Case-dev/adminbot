# VMQ-TIME-09 — brief UI-среза «покрытие памяти по годам» (2026-11-19)

Статус: **read-only архитектурная подготовка**. Код, тесты, карта, `progress_scope.json`, `workflow_state.md` не менялись; деплой и SSH не выполнялись. Артефакт создан для Orchestrator/Builder; решение о статусах принимает независимый Reviewer.

## 0. База, метод, что реально проверено

| Параметр | Факт |
|---|---|
| Production (на входе) | `2.58.216` @ `5046090c7c3a9cdc59a37a0082a5effbdda9f1c7`, schema 47 |
| QRNG-поезд | `2.58.217` (кандидат `f68e7631d`, content `b6c9bb0b`) — деплоится; **TIME-09 начинать только от задеплоенного результата**, не от кандидатной ветки |
| Код 2.58.216 | читался через `git show 5046090c7:<path>`; рабочее дерево как «деплой» не использовалось (HEAD планировочной линии отличается) |
| Рендер UI | реальные `web/index.html` + `web/app.js` + `web/static/app.css` 2.58.216 прогнаны Playwright-харнессом на 1440/390/320 (Status) и 1440/390 (Analytics → «Память и интеллект»), плюс Browser Use через отдельный Chrome/CDP 9222 на 1440/390; Playwright console errors 0, горизонтального overflow нет (`scrollWidth == innerWidth` на 390/320) |
| Ограничение | production-БД и SSH в этой задаче не читались; live-числа не заявляются |

Наблюдённые факты рендера:
- Status `#/`: «Мониторинг интеллекта» — одна full-width карточка `.intel-card[data-intel-widget]`; на мобильных (390/320) — переключатель лент с табами 44 px, кнопки ⟳ 44×44; на десктопе табы скрыты, видны все 4 ленты; под лентами «Здоровье памяти» (`data-expired-block`, `data-memory-tech`), затем «Инициатива»; на 390 карточка 1758 px, на 320 — 1929 px, без обрезки/overflow.
- Analytics `#/oversight?tab=memory`: 7 суб-вкладок (desktop 36 px pills, mobile dropdown), карточки full-width: «Истории памяти» (~255 px), «Временной фактчек» (88), «Цикл памяти (24ч)» (88), «Embeddings и векторная память» (92), «Интеллект и Память» (215), «Личность» (93); 1440 — без overflow (1425 ≤ 1440), 390 — без overflow.
- 132–164 px / сетка 4-3-2-1 — правило **каталога модулей** (`design-m3-2026-11-16.md` §4.1/D7), а не этих карточек. Принудительно применять его к Status/Analytics нельзя.

---

## 1. Точная приёмка VMQ-TIME-09 и что требуется доказать

Формулировка карты (row `VMQ-TIME-09`, `acceptance`):

> «Статус» и «Аналитика» показывают по фактическому прогону запроса: (1) покрытие выдачи по годам — сколько фактов каждого года реально дошло до Writer, (2) причины исключения фактов с категориями — квота оперативного набора, статус (archived_fact и др.), давность (полураспад/пол/бонус свежести), релевантность, контекстный бюджет. Все числа вычисляются из реальных долговременных событий/БД этого прогона; при отсутствии данных показывается явный ноль или «нет данных» с причиной, а не декоративное значение. Разбивка воспроизводима из событий и совпадает с трассой блоков (VMQ-TIME-04). Провал: фиктивная или заранее зашитая статистика, проценты без источника, отсутствие разбивки причин исключения либо расхождение с реальными событиями.

Разложение на проверяемые пункты:

1. **Per-run, не aggregate.** UI показывает выбранный ход (`turn`) и его вызовы `retrieve()`; никаких «средних по чату», «за 200 событий» и процентов.
2. **(1) Дошло до Writer.** Для RAG-блока (`kind="rag"`, `rendered=true`) — распределение фактов по годам из `direct_turn_selection.blocks[].years`. Для `rendered=false` — «не дошло» + `skip_reason`, а не нули «покрытия». `episode`-блок показывается отдельно как «строки эпизодов», не смешивается с фактами. `global_tail`/`global_middle` — история чата, не память; в счётчик памяти не входят.
3. **(2) Причины исключения.** Пять категорий из `mca07_retrieval.usage_json.excluded` (`policy_operative`, `status`, `expired`, `relevance`, `budget`), подписи: квота оперативного набора / статус / давность / релевантность / контекстный бюджет. Числа — кандидаты-факты этого вызова, не сообщения и не «доля».
4. **Совпадение с трассой блоков.** Оба числа берутся из одного `trace_id`: `direct_turn_selection` (Writer-блоки) и `mca07_retrieval` (выдача/исключения). Сейчас retrieval-события **не имеют** `trace_id` — это и есть основной backend-пробел (см. §2).
5. **Ноль ≠ неизвестно.** `years={}` у существующего события — измеренный ноль; отсутствие `years`/`blocks`/`truncated` — «нет данных»/«не зафиксировано», не 0.
6. **Нет фиктивных чисел.** В блоке нет `%`, нет доната/радара/прогресс-бара, нет KPI-плиток; только целые счётчики и коды.

Обязательные evidence-артефакты (пути из карты):
- `plans/features/vmq-onto-01/evidence/vmq-mem/time/status-analytics-year-coverage.json` — снимок реального прогона: `trace_id`, `writer_blocks[]` (kind/rendered/skip_reason/years), `retrieval_runs[]` (ts/policy/period/years/excluded), `memory_period`, `ui_text`, `reconciliation[]` «UI-число → путь события», `aggregation: "none"`.
- `plans/features/vmq-onto-01/evidence/vmq-mem/time/status-analytics-year-coverage-ui.md` — скриншоты 1280/390/320 + Browser Use, точный текст блока, таблица сверки, ограничения (truncated/старые ходы).
- Дополнительно к слайсу: `time09-implementation.md` (кандидат, diff, RED/GREEN, мутации), `time09-playwright.json`, `time09-shots/`.

---

## 2. Данные: что уже есть, чего не хватает, минимальный аддитивный backend

### 2.1. Существующие источники (2.58.216)

| Источник | Где | Поля | Годится для TIME-09? |
|---|---|---|---|
| `GET /api/memory/retrieval-coverage` | `web/api/memory_overview.py:250` → `services/memory_diagnostics.py:retrieval_year_coverage` | `available`, `events`, `scanned`, `with_usage`, `last_event_at`, `years` (сумма год→n), `year_count`, `excluded` (сумма 5 категорий), `policy` (счётчики), `available:false` + `empty_reason` (`no_data`/`usage_missing`/`read_failed`) | **нет**: aggregate; игнорирует `chat_id`; суммирует `years` и из `period_selection`-событий (двойной счёт); нет per-run разбивки |
| `GET /api/direct/turn-diagnostics` | `web/api/routes.py:2494` (`chat_id`, `turn=1..8`, `trace_id`, `include_text=0`) | `available`, `turns[]`, `trace_id`, `context/writer/delivery`, `stages{context,writer,delivery,selection,search,tool_phase,style}`, `selection{policy_version,counts,budget,blocks[{kind,role,rendered,skip_reason,source_ids,first_ts,last_ts,tokens}],dropped,self_outputs,truncated}`, `memory_period` *в событии есть, но в ответе отсутствует* | **да, после аддитивной проекции**; RBAC — доступ к чату |
| `direct_turn_selection.usage_json` (durable, `mca_events`) | `services/turn_trace.py:note_selection`/`_selection_payload` | `counts`, `budget`, `blocks[].years` (только для `global_tail`, `global_middle`, `rag`, `episode`; `direct_chat_service._block_years`), `memory_period`, `memory_grounds`, `dropped`, `self_outputs`, `truncated` | **да** — канонический per-turn Writer-снимок |
| `mca07_retrieval.usage_json` (durable) | `services/mca_retrieval_context.py:retrieve` (~3180) | `{policy, years:{YYYY:n}, excluded:{policy_operative,status,expired,relevance,budget}, period_fill:{...}}`; отдельное событие `outcome="selection", reason_code="period_selection"` несёт `{period_trace, years}` | **да, но сейчас без `trace_id`** — нельзя связать с ходом |
| `mca_events` | SQLite/PG | `ts, level, event_name, outcome, trace_id, chat_id, component, stage, reason_code, usage_json, ...` | связь по `trace_id`/`chat_id`/`component="retrieval_context"` |

Точные producer-поля `memory_period` (`services/direct_chat_service.py:_period_trace`, `turn_trace._sel_memory_period`): `policy`, `replace_allowed`, `period_skipped`, `intent{kind,years,source}`, `intent_source`, `pool`, `kept`, `historical_quota`, `multi_year_quota`, `dropped_subject`, `dropped_budget`, `dropped_status`, `dropped_out_of_target_year`, `dropped_unknown_year`, `pool_status{confirmed,archived,other}`, `pool_expired`, `age_policy`, `vector_leg`, `vector_rows`, `vector_unavailable_reason`.

### 2.2. Чего не хватает (ровно три вещи)

1. **`trace_id` у `mca07_retrieval`.** `RetrievalRequest` не имеет поля, `emit_stage_event` не передаёт `trace_id`; событие живёт с `chat_id`, но без хода. Без этого «причины исключения» нельзя честно показать для того же прогона, что и Writer-блоки.
2. **Проекция `blocks[].years` и `memory_period` в API.** Событие их хранит, но `_TURN_BLOCK_SCHEMA` (`routes.py:1825`) и `_TURN_SELECTION_SCHEMA` (`routes.py:1845`) их отбрасывают.
3. **Retrieval-события в ответе диагностики.** `turn-diagnostics` собирает только `_TURN_STAGE_EVENTS` + 4 detail-события; `mca07_retrieval` не приклеивается.

### 2.3. Минимальная аддитивная правка (без новой таблицы/store/pipeline/DDL)

| Файл | Что именно | Оценка |
|---|---|---|
| `services/mca_retrieval_context.py` | `RetrievalRequest.trace_id: str \| None = None`; `trace_id=request.trace_id` в `emit_stage_event("retrieval","invalid",...)` (~2538) и в основном emit (~3180) | +6/−2 |
| `services/direct_chat_service.py` | `_rag_retrieve(..., trace_id=None)` → `RetrievalRequest(trace_id=...)`; `_rag_unified_rows(..., trace_id=None)` → все 3 вызова `_rag_retrieve`; `_build_rag_block(..., trace_id=None)` → `_rag_unified_rows`, `_build_old_episodes`, `emit_stage_event("retrieval","selection",..., trace_id=...)`; `_build_user_content` передаёт `trace_id=correlation_id`; `_apply_plan_memory_scope[_locked](..., trace_id)` из `_handle_turn(correlation_id)`; `_build_old_episodes(..., trace_id=None)` | +16/−8 |
| `web/api/routes.py` | `_TURN_BLOCK_SCHEMA += "years": ("map", 4, "int", 8)`; новый `_TURN_PERIOD_SCHEMA` + `_TURN_SELECTION_SCHEMA["memory_period"]`; новый `_TURN_RETRIEVAL_SCHEMA`/`_turn_retrieval_view`; после выбора `selected_id` — один `mca_events_query(db, trace_id=selected_id, chat_id=chat_id, limit=32)` с фильтром `event_name=="mca07_retrieval"`, без `period_selection`; `view["retrieval"]`, `stages["retrieval"]` | +95/−8 |

Контракт `retrieval[]` (R17-safe, только коды/числа):

```json
{"ts": 1763..., "outcome": "success|silent", "reason_code": "retrieval_empty|...",
 "policy": "auto|historical|operative", "period": false,
 "years": {"2023": 2, "2026": 8}, "years_present": true,
 "excluded": {"policy_operative": 4, "status": 3, "expired": 0,
              "relevance": 1, "budget": 2},
 "excluded_present": true}
```

- `period` = присутствует `usage_json.period_fill` (периодный добор), а не догадка.
- `years_present`/`excluded_present` различают измеренный `{}` и отсутствие поля.
- `excluded` в ответе нормализуется по закрытому набору: все пять ключей присутствуют, отсутствующие в событии = 0 (producer пишет только ненулевые); `excluded_present=false` — события не было, и UI не рисует нули.
- `period_selection`-события **не** попадают в `retrieval[]` (их данные уже в `selection.memory_period`); тест это фиксирует.
- `mca07_retrieval` не является stage-событием: цепочку не создаёт, приклеивается только к выбранному `trace_id`; окно 400 строк не раздувается (отдельный bounded-запрос).
- Никаких изменений `retrieve()`, ранжирования, бюджетов, промптов, лимитов; `trace_id=None` — байт-паритет прежних событий (поле просто не добавляется).

**Почему не `retrieval_year_coverage`:** это aggregate, он не даёт per-run и уже содержит двойной счёт `years` (main + `period_selection`), а `chat_id` игнорируется. Показывать его как «покрытие прогона» нельзя — это прямое нарушение приёмки. Его дефекты фиксируются отдельным non-blocking follow-up (BACKLOG_ONLY), не чинятся в этом UI-срезе, чтобы не расширять scope.

### 2.4. Ограничения источника, которые UI обязан показать

- `turn_trace._PAYLOAD_LIMIT = 1800`: `_selection_payload` сначала режет `memory_grounds`, затем блоки с конца. RAG-блок стоит в начале и обычно выживает, но при `truncated=true` возможны отсутствующие блоки. UI: «детализация усечена», отсутствующий блок — «не зафиксировано», **не 0**.
- Старые ходы (до деплоя) не имеют `trace_id` у retrieval: показывается Writer-часть (если есть) и «событий retrieval с привязкой к ходу нет».
- Если `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` эффективно OFF — событий нет; UI показывает `available:false/reason`, не нули. Проверка effective-state — read-only preflight, не новый флаг.
- Ретенция `mca_events` может удалить старые события; evidence снимать сразу после прогона.

---

## 3. UI-дизайн

### 3.1. Где живёт блок

**Status `#/`** — внутрь существующей карточки `.intel-card[data-intel-widget]` («Мониторинг интеллекта»), после закрывающего `</div>` секции «Здоровье памяти» (нумерация 2.58.216: строки 14985–15032, после деплоя искать по `data-memory-tech` и следующему `data-intents`) и перед `data-intents` («Инициатива»). Тот же паттерн разделителя: `<div class="mt-3 pt-2 border-t border-white/10" data-retrieval-coverage-status>`. Не новая grid-карточка: не ломает 12-колоночную сетку и не отодвигает «Сон/Самодиагностику».

**Analytics `#/oversight?tab=memory`** — новая full-width карточка после «Цикл памяти (24ч)» (перед «Embeddings и векторная память»): `<div class="card p-4 col-span-full mb-3" data-retrieval-coverage-analytics v-if="oversightTab === 'memory'">`. Это та же смысловая линия «цикл памяти → что реально дошло», не новый таб и не новый маршрут.

Один loader/store на обе поверхности: `memoryYearCoverage` (+ `turn`, `trace`, `at`, `seq`, `scope`), чтобы Status и Analytics не показывали разные числа и не делали два запроса.

### 3.2. Состав и иерархия

**Status (компактно, 2–3 строки):**

```
Покрытие памяти по годам                         [⟳]
последний ход · auto · 19.11 14:32 · ход 1a2b3c4d
Дошло до Writer: 2023 — 2 · 2024 — 5 · 2026 — 7
Исключено: квота 4 · статус 3 · давность 0 · релевантность 1 · бюджет 2
Подробнее в Аналитике →
```

- Заголовок `text-xs font-bold`; подпись `text-xs text-gray-500`; ⟳ — существующий `btn-ghost text-xs` (44×44).
- Годы — `badge badge-muted text-[10px]` с `aria-label="2023: 2 факта"`; никаких полос/процентов.
- «Дошло до Writer» — только `kind="rag"` + `rendered=true`. Если RAG-блока нет: «RAG-блок не дошёл до Writer (причина: budget)» или «не зафиксирован (трасса усечена)».
- «Исключено» — основной (первый не-периодный) вызов retrieval этого хода. Если вызовов несколько: «ещё N вызовов — в Аналитике».
- Ссылка — `btn-ghost text-xs` с `@click="openMemoryCoverage()"` (существующий паттерн `openStoriesAnalytics`: `oversightSetTab('memory')` + `navigateTo('#/oversight?tab=memory')`), не новый маршрут.

**Analytics (полный per-run):**

```
Покрытие памяти по годам                         [⟳] [← предыдущий ход]
последний ход · 19.11 14:32 · trace 1a2b3c4d · политика auto

Дошло до Writer
  Факты памяти (RAG)   2023 — 2 · 2024 — 5 · 2026 — 7
  Эпизоды              2023 — 1
  (RAG не дошёл)       причина: budget

Выдано retrieval (этот ход)
  вызов 1 · 14:32:10 · auto · основной
    годы: 2023 — 2 · 2024 — 6 · 2026 — 8
    исключено: квота 4 · статус 3 · давность 0 · релевантность 1 · бюджет 2
  вызов 2 · 14:32:11 · auto · периодный добор
    годы: 2023 — 1
    исключено: квота 1 · статус 0 · давность 0 · релевантность 0 · бюджет 1

▸ Почему старые годы не добавились (period_skipped / пул / отброшено)
▸ Ограничения (один ход, не среднее; старые ходы без trace; truncated)
```

- Компонент — **список строк**, не таблица: у каждого вызова переменное число годовых чипов и 5 причин; таблица на 320 px дала бы горизонтальный скролл. Строки разделяются `border-t border-white/10 pt-2 mt-2`, без вложенного стекла.
- «Периодный добор» — `<details>` (по умолчанию свёрнут): `policy`, `period_skipped` (человеческая подпись кода), `pool → kept`, `dropped_status/expired/budget`, `dropped_out_of_target_year/unknown_year`. Это объяснение ограничения, не второй набор «покрытия».
- Максимум 6 вызовов из API; если больше 3 — первые 3 видны, остальные в `<details>` «ещё N вызовов». Это не aggregate: каждая строка — свой прогон.
- «← предыдущий ход» использует существующий `turn` (1..8), без нового endpoint; «следующий →» появляется при `turn>1`; кнопки 44 px, `disabled` на границах.

### 3.3. Числа, единицы, таймфрейм

- Год — UTC-календарный год времени источника (`_utc_year`/`time.gmtime`), не локальный пояс чата. В подписи: «годы источника (UTC)».
- «Факты» — строки RAG-блока (`graph_facts`), «строки эпизодов» — строки `episode`-блока; не складывать.
- Время — `fmtTs(ts)` существующим форматтером; заголовок хода — `body.ts`/`turns[0].ts`.
- Никаких «за 24ч/7д»: блок про один ход; таймфрейм не предлагается.
- Суммы по годам не выводятся отдельной цифрой; если нужна подпись — «строк: N» только как сумма текущего блока, без процентов и без «покрытие N%».
- Счётчики `excluded` — причины, по которым кандидат не вошёл в выдачу, а не оценка качества ранжирования. `expired` — истёкшая память (давность); полураспад/пол/бонус свежести влияют прежде всего на порядок и не обязаны давать отдельное исключение. Подпись «давность» не превращается в «доля старых фактов».

### 3.4. Состояния (unknown/empty/error/degraded)

| Состояние | Что видно |
|---|---|
| Нет выбранного чата (`activeChatId == null`) | «Выберите чат — покрытие привязано к выбранному чату». Никаких нулей. |
| `available:false`, `reason=no_turn_traces` | «Ходов этого чата ещё нет — покрытие появится после первого ответа». Код причины — в `title`. |
| `selection == null` | «У последнего хода нет снимка памяти (ответ без памяти / трасса неполная)». |
| `selection.truncated == true` | Amber-строка «Детализация блоков усечена — отсутствующие годы не считаются нулём»; показать то, что есть. |
| `blocks` есть, `rag.rendered=false` | «RAG-блок не дошёл: <skip_reason>»; годы не показывать как 0. |
| `retrieval == []` | «Событий retrieval с привязкой к этому ходу нет» (старые ходы). Writer-часть показывается. |
| `years_present=true, years={}` | «0 фактов (выдача пуста, причина: retrieval_empty)» — измеренный ноль. |
| `excluded_present=true, excluded={}` | «Исключений не было» (не пять нулей). Если некоторые категории есть — показать все 5, отсутствующие = 0 (producer пишет только ненулевые; закрытый набор). |
| HTTP 403 | Блок не рендерится (global-admin gate); запроса нет. |
| HTTP 5xx/network | «Не удалось загрузить покрытие: <message>» + ⟳; остальная страница живёт (fail-open). |
| Загрузка | `spinner my-2`, `aria-busy="true"` на блоке. |

### 3.5. Доступность

- Контейнер `role="group" aria-label="Покрытие памяти по годам"`.
- Каждый вызов — `role="group" aria-label="Вызов retrieval: <время>, политика <policy>, <основной|периодный добор>"`.
- Годовой чип: `aria-label="2023: 2 факта"`; причина: `aria-label="Квота оперативного набора: 4"`; полные определения — `title` и строка-легенда.
- ⟳/←/→ — `aria-label`, `title`, `disabled` с понятным состоянием; 44×44.
- Ошибка — `role="alert"`; пустое состояние — обычный текст (не live-region, чтобы не читалось на каждом поллинге).
- Цвет не единственный носитель: числа + подписи; amber/red только как дополнение.
- Никаких `%`, `aria-valuenow` для «покрытия» (нет шкалы).

### 3.6. Мобильные 390/320

- Все ряды `flex flex-wrap gap-1`; годовые чипы переносятся; `min-width:0`.
- 5 причин на 320 — в 1–2 строки, без сокращения подписей до нечитаемых (`квота`, `статус`, `давность`, `релевантность`, `бюджет`).
- Список вызовов — вертикальный; горизонтального скролла нет. `<details>` для периода/ограничений.
- Кнопки 44 px; ссылка «Подробнее» — `btn-ghost` (44 px на тач-ширине).
- Проверка: `document.documentElement.scrollWidth <= window.innerWidth + 1` на 320/390/768/1280/1440 для `#/` и `#/oversight?tab=memory`.

### 3.7. Visual Preservation Map

| BLOCK / route / selector | CURRENT PURPOSE | USER VALUE | ACTION | MUST PRESERVE | ALLOWED CHANGE | DATA / STATE | INTERACTION | RESPONSIVE | WHY |
|---|---|---|---|---|---|---|---|---|---|
| `#/` `.intel-card[data-intel-widget]` | «Мониторинг интеллекта»: 4 ленты + здоровье памяти + инициатива | увидеть, что бот недавно запомнил и как себя чувствует память | **KEEP + ADD** | порядок и состав секций; mobile-табы 44 px и скрытие на десктопе; ленты/скролл; `data-expired-block`/`data-memory-tech`; «Инициатива»; full-width карточка; отсутствие обрезки | новая секция после «Здоровья памяти» с border-top; natural height | `memoryYearCoverage`; `activeChatId`; `isGlobalAdmin` | ⟳; ссылка в Аналитику; без новых табов | карточка растёт вниз; на 320/390 chips переносятся; overflow 0 | это существующая поверхность памяти; отдельная grid-карточка раздробила бы модель и сдвинула «Сон»/«Самодиагностику» |
| `#/` `.cognition-ribbons` + `.intel-tabs` | 4 ленты фактов/убеждений/парадигм/черт; на телефоне — переключатель | быстрый обзор свежих знаний | **KEEP** | 4 ленты, `data-intel-section`, 44 px табы, mobile-видимость одной ленты, скролл | нет | `/api/memory/cognition/status` | switchStatusRibbon | без изменений | не относится к покрытию годов; любое изменение — регресс |
| `#/` «Здоровье памяти» (`data-expired-block`, `data-memory-tech`) | просрочено/не подтверждено/сырьё/диск | честная деградация памяти | **KEEP** | строки, подписи, `mem-kv`, warning диска | нет | `/api/memory/health`, `/api/memory/expired-overview` | ⟳ | без изменений | новый блок дополняет, не заменяет |
| `#/oversight` `data-oversight-tabs` | 7 суб-вкладок Аналитики | навигация по разделам | **KEEP** | 7 табов, 36 px desktop pills, mobile dropdown, `aria-selected`, hash `?tab=` | нет | `oversightTabs` | oversightSetTab | без изменений | новый таб не нужен; блок живёт в «Память и интеллект» |
| `#/oversight` «Истории памяти» | лента эпизодов/историй | что бот помнит ситуационно | **KEEP** | карточка, фильтры, пауза, deep link | нет | `/api/stories/*` | существующие | без изменений | не дублируется |
| `#/oversight` «Временной фактчек» | прогоны проверки дат | видеть фактичность | **KEEP** | таблица/поля, ⟳ | нет | `/api/oversight/temporal/*` | существующие | без изменений | не относится к покрытию |
| `#/oversight` «Цикл памяти (24ч)» | durable-счётчики цикла | понять, жив ли цикл | **KEEP** | заголовок/подпись/узлы/⟳ | нет | `/api/analytics/viz/process-activity` | ⟳ | без изменений | новая карточка ставится сразу после; обе про память |
| `#/oversight` «Embeddings…», «Интеллект и Память», «Личность» | индексы, пульс, черты | диагностика | **KEEP** | порядок, содержимое, ⟳ | только сдвиг вниз из-за вставки | существующие API | существующие | без изменений | вставка не переписывает соседей |
| mobile dropdown `oversight-mobile-dd` | выбор суб-вкладки на <768 | доступ к разделам | **KEEP** | полный список, Esc/outside, focus return | нет | `oversightMobileTabs` | oversightMobilePick | без изменений | новый пункт не добавляется |
| Glass/aurora/polygon/фон | визуальный язык | идентичность | **KEEP** | `data-glass`, blur, токены, анимации | нет | статические модули | — | — | новые тяжёлые стеклянные контейнеры запрещены |

Защищённые токены/классы: `card p-4`, `text-xs font-bold`, `text-xs text-gray-500`, `btn-ghost text-xs`, `badge badge-muted`, `border-white/10`, `spinner`, `text-amber-300`, `text-red-300`; новые CSS-переменные/цвета/радиусы не вводятся. `web/static/app.css` остаётся **байт-идентичным**.

---

## 4. Write scope, сериализация, байт-идентичность

| Файл | Тип | Оценка | Конфликт |
|---|---|---|---|
| `services/mca_retrieval_context.py` | additive trace_id | +6/−2 | нет QRNG; сериализовать с TIME-04, если он пишет этот файл |
| `services/direct_chat_service.py` | additive passthrough | +16/−8 | нет QRNG; сериализовать с TIME-04/voice |
| `web/api/routes.py` | schemas + retrieval view | +95/−8 | **QRNG-файл** (2.58.217 +158); только после деплоя, база — deployed SHA |
| `web/app.js` | store/loader/computed | +140/−2 | **QRNG-файл** (2.58.217 +646); после деплоя |
| `web/index.html` | 2 вставки + script | +110/−0 | **QRNG-файл** (2.58.217 +536); после деплоя |
| `web/static/status-analytics.js` | **новый**, UMD pure helpers | +110 | нет |
| `tests/js/vmq_time09_year_coverage_ui_test.js` | **новый** | +220 | нет |
| `tests/test_vmq_time09_turn_coverage.py` | **новый** pytest | +260 | нет |
| `tests/test_ur_f_inspector_step2.py` | точечно: `stages` + новый ключ | +6/−1 | сериализовать с владельцем инспектора |
| `tests/ui_vmq_status_analytics_e2e.py` | **новый** Playwright | +300 | нет |
| `plans/.../evidence/vmq-mem/time/...` | evidence | +150 | один writer |

Итого ~1 000–1 100 строк, 10–11 файлов. Если Reviewer потребует минимизировать: убрать UI-показ `memory_period` (оставить API) — минус ~60 строк и один блок тестов.

**Должно остаться байт-идентичным:**
- `web/static/app.css`, `web/static/*` (кроме нового файла), `web/app.py`, `handlers/web.py` (план упоминал его; правка **не нужна** — статика уже раздаётся, `__APP_VERSION__` подставляет `web/app.py`).
- Все существующие блоки Status/Analytics (кроме двух вставок), их data-атрибуты, классы, табы, порядок.
- Существующие ключи `turn-diagnostics` и их семантика; `retrieval_year_coverage`/`memory_overview.py` не меняются.
- `APP_VERSION`, `param_catalog`, `module_registry`, `status_service`, `database.py`, `config_cache.py`, `mca_random_source.py` — не трогать (QRNG/релиз).

**Сериализация:** один writer на `routes.py`/`app.js`/`index.html`; backend-файлы можно параллельно с evidence-only работами, но не с TIME-04, если он меняет те же функции. Начинать только после успешного деплоя 2.58.217 и фиксации deployed SHA/content; **не** ветвиться от `f68e7631d`/`b6c9bb0b`.

### 4.1. Совместимость, откат, auth, failure/retry, effective config

- **Совместимость:** все изменения аддитивны. Старые клиенты игнорируют новые ключи; старые ходы без `trace_id` показывают Writer-часть и честную причину отсутствия retrieval-строк. Существующие ключи `turn-diagnostics` не переименовываются и не меняют тип; `stages` получает один новый bool. `retrieval_year_coverage` и его ответ не меняются.
- **Откат:** revert коммита слайса; DDL/schema нет (остаётся 48), сохранённые события с `trace_id` безвредны, настройки пользователей не менялись. UI при отсутствии новых полей обязан показывать «нет данных», а не падать (defensive `view()`).
- **Auth:** обе поверхности global-admin; `turn-diagnostics` дополнительно проверяет доступ к чату. Не-админ не видит блок и не делает запрос; 403 не превращается в «0». Новых прав/ролей нет.
- **Failure/retry:** endpoint при сбое чтения отдаёт `available:false`/`reason` (fail-open), UI — текст причины + ⟳; автоматических retry-циклов/поллеров нет. Один запрос на вход/⟳/смену чата; TTL-кэш в памяти, без фонового опроса.
- **Effective config:** поведение зависит от существующих гейтов контракта событий/телеметрии; проверяется read-only preflight на деплое. UI не читает флаги сам и не включает их; при OFF — честное пустое состояние. Новый флаг не вводится (PET_PROJECT: готовое — включено, без теневого режима).

---

## 5. План проверки, RED и мутации

### 5.1. Node unit (`tests/js/vmq_time09_year_coverage_ui_test.js`)

Загружает `web/static/status-analytics.js` через `require` (UMD, как `execution_graph.js`/`cognitive-map.js`) и проверяет чистую арифметику:
- `sortedYears({"2026":7,"2023":2})` → `[{2023,2},{2026,7}]`; `"0"/"-1"/"abc"/null` отбрасываются.
- `yearsText` → `2023 — 2 · 2026 — 7`; пусто → `нет фактов` (не `0%`).
- `exclusionRows({budget:1,status:3})` → ровно 5 категорий в фиксированном порядке; отсутствующие = 0; `excludedPresent=false` → `null` (нет данных); `view` при `excludedPresent=true` и всех нулях показывает «исключений не было», при частичных — все 5.
- `writerBlocks(blocks)` — только `rag`/`episode`; `rendered=false` не попадает в «дошло», но возвращает `skip_reason`; `kind="global_tail"` не считается памятью.
- `primaryRun(runs)` — первый не-периодный, иначе первый; **не** последний элемент массива.
- `latestRun(runs)` — по максимальному `ts`, не по порядку массива (stale-run тест).
- `view(payload)` — состояния `ready/empty/no_chat/no_selection/truncated/no_retrieval/error`; в `JSON.stringify(view)` нет `pct`/`percent`; ни один текстовый helper не содержит `%`.
- Рендер-маркеры в `web/index.html`: `data-retrieval-coverage-status`, `data-retrieval-coverage-analytics`, `data-rc-run`, `data-rc-writer-block`, `data-rc-exclusions`; в блоке нет `canvas`/`svg` графика и слова `донат`/`radial`.

### 5.2. Pytest (`tests/test_vmq_time09_turn_coverage.py`)

- `RetrievalRequest(trace_id="t1")` → `emit_stage_event` получает `trace_id="t1"`; без trace_id поле не появляется (паритет).
- `_rag_retrieve(..., trace_id="t1")` → событие `mca07_retrieval` с `trace_id="t1"`; `_build_rag_block(..., trace_id="t1")` → period-selection событие тоже с trace.
- `direct_turn_diagnostics` на событии `direct_turn_selection` с `blocks[0].years={2023:2,2026:8}` и `memory_period` → ответ содержит `selection.blocks[0].years` и `selection.memory_period` (поля по схеме, лишние ключи отброшены).
- `mca07_retrieval` main + `period_selection` с тем же `trace_id` → `retrieval` содержит только main; `period_selection` не создаёт строку.
- `years={}`/`excluded={}` → `years_present/excluded_present=true`, нули не выдуманы; отсутствие `usage_json` → строки нет.
- Два retrieval-события в обратном порядке ts → `retrieval` отсортирован по ts; `period` корректен.
- R17: в ответе нет текста сообщения/факта (маркер-строка отсутствует), только коды/числа.
- 403 без доступа к чату; 200 для global admin.
- `stages` теперь содержит `retrieval`; обновить точный assert в `test_ur_f_inspector_step2.py` (атомарно, без ослабления остальных).
- `_TURN_EXCLUSION_KEYS` в routes равен `_RETRIEVAL_EXCLUSION_KEYS` в `memory_diagnostics` (защита от дрейфа).
- Truncated selection: `truncated=true` и отсутствующий rag → API отдаёт без лет, не подставляет `{}`.

### 5.3. Playwright (`tests/ui_vmq_status_analytics_e2e.py`)

Рендерит реальные `web/index.html`+`app.js`+`app.css` задеплоенного 2.58.217 + кандидат, API-стабы из реальных payload-схем (как `tools/ui_asap8_v63_w3_status_e2e.py`):
- 1280/390/320, `#/`: блок есть; текст совпадает со стабом (`2023 — 2`, `квота 4`); `%` нет; `canvas` внутри блока 0; ⟳ 44 px; `scrollWidth<=innerWidth+1`; на 390/320 — 4 таба по 44 px, на 1280 табы скрыты и видны 4 ленты.
- 1280/390/320, `#/oversight` → «Память и интеллект»: карточка между «Цикл памяти» и «Embeddings»; число строк `retrieval` = стабу; 5 подписей; «← предыдущий» работает (turn=2 запрос); нет overflow; нет нового таба/dropdown-опции.
- Пусто (`no_turn_traces`) → текст причины, не нули; ошибка (500) → reason, остальные карточки живы; `truncated=true` → amber-строка.
- Non-admin → блока нет и запроса `/api/direct/turn-diagnostics` нет (счётчик route).
- Сеть: ровно один GET диагностики на вход/⟳; `/api/memory/retrieval-coverage` **не вызывается** (доказательство отказа от aggregate); нет provider-probe/платных вызовов.
- Console/pageerror 0.

### 5.4. Browser Use

Открыть тот же harness-сервер (server-side стабы) на 1440 и 390, снять screenshot, проверить текст/overflow/console. В этой среде Browser Use потребовал отдельный Chrome с `--remote-debugging-port=9222`; если CDP недоступен — зафиксировать **blocked**, не пропускать молча.

### 5.5. RED на задеплоенном base

До кода, на базе deployed 2.58.217:
- node: `Cannot find module .../status-analytics.js` / helper undefined;
- pytest: `selection.blocks[0].years` отсутствует; `memory_period` None; `retrieval` нет;
- Playwright: `[data-retrieval-coverage-status]` не найден.
Сохранить точный вывод в `time09-red-<sha>.txt`.

### 5.6. Дискриминирующие мутации (2–3 обязательны, 4 рекомендованы)

| # | Мутация | Ожидаемый провал |
|---|---|---|
| M1 | в helper добавить `share = count/total*100` и вывести `%` | node `no_percent`; Playwright «нет `%`» |
| M2 | `primaryRun`/`latestRun` брать `runs[0]`/последний элемент вместо max `ts` | node stale-run; Playwright подставляет старый ход как текущий |
| M3 | `writerBlocks` включать `rendered=false` или игнорировать `skip_reason` | node/pytest: пропущенный RAG засчитан как дошедший |
| M4 | `view` при `truncated=true` возвращает `ready` без limitation | node/pytest: отсутствие предупреждения |
| M5 (опц.) | API включает `period_selection` в `retrieval[]` | pytest: лишняя строка/двойной счёт |

Каждая мутация применяется к кандидату (не коммитится), целевой тест падает, мутация откатывается; логи — `red-mutation-*.txt`.

### 5.7. Сверка и evidence

- Один реальный ход (preprod-копия прод-БД или production, если безопасно) через **продуктовый путь**, не ручную вставку событий. LLM-текст не является доказательством; важен `direct_turn_selection`/`mca07_retrieval` с одним `trace_id`.
- SQL read-only: `SELECT ts, trace_id, chat_id, outcome, reason_code, usage_json FROM mca_events WHERE trace_id=... ORDER BY ts`; сравнить с UI.
- В JSON — `aggregation: "none"`, `per_run: true`, `reconciliation[]`; в MD — скриншоты и точный текст.
- Reviewer независимо выбирает свой ход/чат и повторяет сверку; артефакты Builder не единственное доказательство.

---

## 6. Риски, неизвестные, блокеры

1. **Первый ход после деплоя.** Старые ходы не имеют `trace_id` у retrieval; полная приёмка требует хотя бы одного реального хода после выката. Это agent-owned наблюдение, не QA владельца. Если хода нет — `delivered_awaiting_evidence`, строка остаётся REVIEW; не блокировать остальную очередь и не опрашивать вручную.
2. **Усечение selection.** При `truncated=true` RAG-блок может отсутствовать. UI честно показывает «не зафиксировано», но приёмка «покрытие по годам» может быть неполной. Если на первом реальном ходе RAG-блок систематически теряется — отдельный малый corrective: компактное событие `direct_turn_memory_coverage` (только blocks/years/memory_period, ≤1800), без повышения общего cap и без новой таблицы. Это fallback, не входит в текущий scope без решения Reviewer.
3. **Effective gates.** Если контракт событий/телеметрия эффективно OFF, данных нет; UI честно пуст. Проверить effective-state read-only до evidence; не включать флаги самовольно.
4. **QRNG-конфликт.** `routes.py`/`app.js`/`index.html` — файлы 2.58.217; любая правка до деплоя создаёт конфликт и риск потери QRNG/B3. Ждать deployed SHA, не кандидат.
5. **Per-run vs aggregate.** UI сознательно не показывает aggregate. Если владелец/Reviewer захочет тренд по многим прогонам — это отдельная задача с исправлением `retrieval_year_coverage` (chat scope + исключение `period_selection` + per-run rows), не этот срез.
6. **Мобильная длина.** Analytics-карточка с 3 вызовами + details может быть высокой; ограничить первые 3 вызова, остальное — `<details>`; Status — только 2–3 строки. Не превращать в «стену».
7. **`stages` контракт.** Добавление `stages.retrieval` ломает один точный assert в `test_ur_f_inspector_step2.py`; обновить атомарно, не ослабляя другие проверки.
8. **Browser Use.** В этой среде понадобился отдельный Chrome/CDP; если у Builder окружение без CDP — зафиксировать blocked, Playwright-прогон не отменяется.
9. **Наблюдаемость mca-17:** после протяжки `trace_id` события `mca07_retrieval` станут частью trace хода; существующие реестр/проекции (`mca_process_registry`, mca17a) могут показать дополнительную стадию/группировку. Это ожидаемо, но требует targeted-проверки, что их контракты/тесты не меняют смысл; сами реестр/проекции в этом слайсе не переписываются.
10. **Не создавать** новую таблицу, store, очередь, агент, флаг, endpoint, процентную шкалу, донат/радиал, LLM-вызовы, probe-ы, квоты инструкций.

**Блокеры старта:** деплой 2.58.217 и фиксация deployed SHA; независимое решение Reviewer о принятии per-run-подхода и trace-протяжки; отсутствие конфликтующего writer'а на `routes.py`/`app.js`/`index.html`.

---

## 7. Порядок шагов

1. **Preflight:** подтвердить 2.58.217 (health, version, schema 48), записать deployed SHA/content; убедиться, что QRNG-файлы на месте; read-only проверить effective event/telemetry gates.
2. **Worktree** от deployed SHA (не от `f68e7631d`); зафиксировать base; прогнать существующие `test_ur_f_inspector_step2`, `test_mem_time_policy` — зелёные.
3. **RED:** node/pytest/Playwright новые тесты на base → падают; сохранить вывод.
4. **Backend trace_id:** `mca_retrieval_context.py` + `direct_chat_service.py`; unit-тест trace_id и паритет без него; targeted pytest.
5. **API projection:** `routes.py` (years, memory_period, retrieval, stages); обновить `stages` assert; pytest зелёный.
6. **UI helper + вставки:** `status-analytics.js`, `index.html`, `app.js`; node-тесты зелёные.
7. **Playwright 1280/390/320 + Browser Use**; проверить overflow/44px/console/сеть; скриншоты.
8. **Evidence:** один реальный ход, SQL-сверка, JSON/MD; мутации M1–M4 (каждая — падение целевого теста, откат).
9. **Independent review**; затем штатный release/deploy. После деплоя — снять первый реальный ход с тем же `trace_id`; при отсутствии — `delivered_awaiting_evidence`, строка REVIEW, очередь продолжается.

Артефакт: `plans/features/vmq-onto-01/evidence/time09-ui-brief-2026-11-19.md`.
