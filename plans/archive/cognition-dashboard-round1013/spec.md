# Spec F5 — `cognition-dashboard-round1013` (дашборд «Осмысление» + виджет «Интеллект и Память»)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; спека Step 2 @Architect, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §5 + §7. Tasks: T-1448…T-1458. Frontend + аддитивные read-API. P1.
> ADR: `adr-1013-2-graph-library.md` (vis-network). Зависимости: API F2 (beliefs/архив) и F3 (парадигмы/deep-sleep).

## 0. Цель

На «Статус» — живой блок «Осмысление»: две вертикальные бегущие строки
(Убеждения/Сон, Парадигмы/Глубокий сон) с opacity-эффектом, бейджи фаз,
интерактивный force-directed граф. Реальная статистика — в «Модули».
В «Сводку» — компактный виджет «Интеллект и Память» (пульс, прогресс-бары, метрики, Timeline).

## 1. Объём

### In scope
- Бэкенд-API (аддитивно): лента beliefs, лента paradigms, статус фаз сна, граф nodes/edges, Timeline, метрики БД, бюджет контекста.
- Блок «Cognition» на «Статус»: 2 бегущие строки (opacity 50→100), бейджи фаз.
- Интерактивный граф (vis-network, ADR-1013-2).
- Перенос статистики графа в «Модули».
- Виджет «Интеллект и Память» в «Сводке» (пульс/бары/метрики/Timeline).

### Out of scope
- Изменение `/api/status` непровместимо (только аддитивные поля).
- Новый каталог-Δ (кроме опц. флага — см. §7).

## 2. Схема данных

Ноль DDL. Источники:
- beliefs/paradigms — `graph_facts` (`kind='belief'`, `belief_meta.type`);
- статус сна — `dream_state`, `memory_dream_log`, флаги `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`;
- граф — SQLite `nodes`/`edges` (GraphRAG);
- Timeline — `memory_dream_log` + `nostalgia_log` + (опц.) `chat_lore_history`;
- бюджет — `worker_budget` (PG) + in-memory last-context accounting.

## 3. API/контракты (аддитивные)

### 3.1. `GET /api/memory/dream/beliefs?chat_id=&limit=&kind=`
Расширение существующего (`web/api/memory_agi.py:212`):
`kind=belief|paradigm|all` (дефолт `all`); поля `_belief_out` + `archived`,
`base_weight`, `type` (`belief`/`paradigm`). `paradigm` — фильтр по
`belief_meta LIKE '%"type":"paradigm"%'`.

### 3.2. `GET /api/memory/cognition/status?chat_id=`
```json
{"dream":{"running":false,"enabled":true,"last_run_at":...,"next_wake_at":...,
          "state":"sleep|synthesizing|limit_exhausted"},
 "deep_sleep":{"running":false,"enabled":false,"last_run_at":...,"next_run_at":...},
 "lore":{"last_inject_at":...},
 "nostalgia":{"mode":"silence|cooldown","silence_left_min":25,"cooldown_left_h":8}}
```
Running определяется in-memory флагом воркера (новый `worker.running` property
или runtime-registry); next_wake — из расписания (окно 4–6 + TZ).

### 3.3. `GET /api/memory/graph?chat_id=&limit=`
```json
{"nodes":[{"id":123,"label":"Толян","group":"user","degree":7}],
 "edges":[{"from":123,"to":456,"label":"друг"}], "truncated":false}
```
Лимиты: `GRAPH_MAX_NODES=120`, `GRAPH_MAX_EDGES=240` (код-константы; аггрегация
по SQLite `nodes`/`edges`, только узлы с degree ≥ 1). R16: `id` — ключ, `label` —
канон-имя/дисплей.

### 3.4. `GET /api/memory/stats?chat_id=`
```json
{"facts":14302,"beliefs":54,"archived_beliefs":3,"protected_facts":12,
 "paradigms":7,"memes":4}
```
Счётчики SQLite (R17-safe). `memes` — из F8 (`status='chat_meme'`), иначе 0.

### 3.5. `GET /api/memory/timeline?chat_id=&limit=20`
Объединённый список последних действий (DESC по ts), элементы:
`{"ts":..., "icon":"🌙|💾|📻|🌌", "text":"Синтезировано убеждение: ..."}`.
Источник: `memory_dream_log` (`distilled`/`deep_run`/`resurrect`),
`nostalgia_log` (sent), `chat_lore_history` (обновление лора). R17: без ключей/эмбеддингов.

### 3.6. Бюджет контекста (F5-Q4 — РЕШЕНО)
Аддитивное поле в `GET /api/status`: `"context":{"used":14500,"limit":24000,"truncated":false}`.
Источник `used` — in-memory last-context accounting (module-level dict в
`direct_chat_service`, обновляется в `_apply_context_budget` после сборки
контекста; хранит только число токенов-оценку и `truncated`-флаг; R17-safe).
Нет данных → `{"used":null,"limit":<cap>}`; фронт показывает «—».
Дневные лимиты воркеров — существующий `GET /api/workers/budget`
(`web/api/gates.py:148`, `worker_budget.get_day_summary`).

## 4. UI/компоненты

### 4.1. Блок «Осмысление» («Статус»)
- Две вертикальные бегущие строки; элементы `position:absolute` + CSS
  `@keyframes` translateY; `opacity` по позиции (центр 1, края 0.5) через
  `mask-image: linear-gradient` ИЛИ per-item класс (JS-юнит проверяет класс).
- Бейджи: `[🌙 Сон активен]` / `[🌌 Глубокий сон активен]` по `cognition/status`.
- Новые элементы вливаются в ленту при polling (без полной перерисовки);
  вне фаз — скролл текущего пула.
- `prefers-reduced-motion: reduce` → статичный список (без анимации).

### 4.2. Граф
- `renderCognitionGraph()` — `new vis.Network(container, {nodes,edges}, options)`.
- drag/zoom включены; `destroy()` до повторного рендера и при уходе с вкладки.
- Ленивая загрузка vis-network (только при открытии «Статус»).
- `prefers-reduced-motion` → `physics: false`.

### 4.3. Виджет «Интеллект и Память» («Сводка», oversight)
- Верх: `[🌙 Сон]` (Спит/Синтезирует/Лимит + next wake), `[💾 Лор]` (последний
  инжект), `[📻 Ностальгия]` (тишина/кулдаун).
- Середина: прогресс-бар бюджета контекста (`used/limit`, красный при
  `truncated||used/limit>0.9`), дневные лимиты воркеров (Сон/Лор из `workers/budget`).
- Низ: метрики БД (факты/убеждения/защищённые) + компактный Timeline.

### 4.4. «Модули» (F5-Q6 — РЕШЕНО)
Переносим **граф-статистику** (число узлов/рёбер/типов) в раздел «Модули»;
сам граф остаётся визуализацией на дашборде. «Сводка» не дублирует «Модули»:
«Сводка» — оперативный виджет, «Модули» — конфигурация/статистика.

### 4.5. Polling (F5-Q3 — РЕШЕНО)
- Интервал 15с, только пока активна вкладка «Статус» и `!document.hidden`
  (TMA свёрнута → пауза; `visibilitychange`).
- Переиспользовать существующий паттерн таймеров (`statusTimer`), обязательно
  `clearInterval` при уходе с вкладки/destroy (R10.11-5).

## 5. Файлы и точки изменения

| Файл | Что |
|---|---|
| `web/api/memory_agi.py` | `beliefs` +kind; новые `cognition/status`, `graph`, `stats`, `timeline` |
| `web/api/routes.py` | `GET /status` + аддитивное `context` |
| `services/status_service.py` | сбор `context` (in-memory accounting) |
| `services/direct_chat_service.py` | запись last-context в accounting |
| `services/database.py` | read-хелперы графа/статистики/timeline |
| `web/app.js` | state/компоненты, `renderCognitionGraph`, polling, виджет |
| `web/index.html` | блок «Осмысление», виджет «Сводка», секция «Модули» |
| `web/static/vendor/vis-network/*` | self-host бандлы (ADR-1013-2) |
| `services/dream_worker.py`/`nostalgia_worker.py` | `running`-флаг для статуса |

## 6. Каталог-Δ

**+0** (все лимиты — код-константы/существующие ключи). Опционально
`flags.cognition_dashboard_enabled` (default ON) — только если Builder
столкнётся с риском; базово **не вводим** (см. tasks.md §8). GROUPS/mapped/TAB_RULES
без изменений.

## 7. Feature flags / progressive delivery

- Feature flag не требуется (UI + аддитивные read-only API; прецедент 10.9–10.12).
- Rollback — атомарный `git revert`.

## 8. План миграций промптов

Не применимо.

## 9. Тест-план

1. API: `beliefs?kind=paradigm` фильтрует; `cognition/status` форма; `graph`
   cap 120/240 и `truncated`; `stats`; `timeline` объединяет и сортирует; `status.context`.
2. R17: ни один ответ не содержит ключей/эмбеддингов/base_url; `graph` — id-ключи.
3. JS-юниты: model лент, opacity-класс, бейдж-состояния, бюджет-класс (`red`),
   Timeline-формат, граф-данные, destroy при переключении.
4. Статик-маркеры: нет `uptimeCanvas`-дубля (F6), есть EKG/граф/виджет-маркеры;
   vis-network self-host + lazy-load.
5. `pytest` 0 failed; `node --check web/app.js` clean; `JS-UNIT-OK`; `git diff --check`.

## 10. Риски

| Риск | Митигация |
|---|---|
| Граф тормозит Android | cap 120/240, Canvas, lazy-load, physics off при reduced-motion/больших N |
| Утечка инстанса vis/таймеров | destroy + clearInterval (R10.11-5/R10.10-3) |
| Бюджет контекста недостоверен | in-memory accounting; `null` → «—», не выдумываем |
| Конфликт с F6 в `index.html`/`app.js` | исполнять F5 и F6 последовательно (tasks §4) |
| Timeline тащит персональное | R17-safe allowlist полей |

## 11. Критерии приёмки

- [ ] «Осмысление»: 2 бегущие строки + opacity, бейджи фаз, вливание новых элементов.
- [ ] Граф рендерится, drag/zoom, не роняет TMA; статистика в «Модулях».
- [ ] Виджет «Сводка»: пульс, прогресс-бары, метрики БД, Timeline — из реальных API.
- [ ] Все данные реальные, без хардкода; R16/R17.
- [ ] `node --check` clean, `JS-UNIT-OK`, `pytest` 0 failed, `git diff --check`.

## 12. Разрешение open questions (F5)

- **F5-Q1** — `vis-network` standalone UMD, self-host, lazy-load (ADR-1013-2).
- **F5-Q2** — источник графа: SQLite `nodes`/`edges`; лимит 120 узлов / 240 рёбер.
- **F5-Q3** — polling 15с, пауза при `document.hidden`/неактивной вкладке.
- **F5-Q4** — бюджет контекста из in-memory accounting `_apply_context_budget` + аддитивное поле `/api/status`.
- **F5-Q5** — Timeline через единый `GET /api/memory/timeline` (агрегатор).
- **F5-Q6** — в «Модули» переносится граф-статистика; «Сводка» — оперативный виджет (не дубль).
