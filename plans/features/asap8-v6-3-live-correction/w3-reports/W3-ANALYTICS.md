# W3-ANALYTICS — U05 (прогрессивная Аналитика + 7 визуализаций D12) + B08 UI (карточки Stories)

Lane: W3-ANALYTICS · Базовый HEAD: 2d95689 · Коммиты не делались (по брифу).
Дата: 16.10.2026

## 1. U05.1 — прогрессивные Процессы/Запуски

- **По умолчанию**: человеческое имя (словарь `vizProcessNames` для 48
  процессов реестра + fallback — первая фраза `purpose`), **эффективный
  статус** (`работает с результатом` / `ошибка` / `не было условий` /
  `не запускался` / `выключен` + честные служебные `резервный контур`,
  `выполняется сейчас`, `не инструментирован`), «последнее действие:
  <время>» и причина пустоты; счётчик «события 24ч: N · 7д: N».
- **Данные**: СУЩЕСТВУЮЩИЙ `GET /api/oversight/processes` (реестр,
  registry-статус/гейт) + новый read-only `GET
  /api/analytics/viz/process-activity` — последнее событие по заявленным
  `event_names` из durable `mca_events` (ROW_NUMBER-запрос), счётчики
  24ч/7д. Эффективный статус выводится ТОЛЬКО из фактов: нет событий →
  «не запускался» (не зелёный), skip → «не было условий» с кодом,
  failed → «ошибка» + тип ошибки.
- **Developer IDs/stages/event names/настройки/входы-выходы/note** — за
  раскрытием «Детали» (`details[data-viz-details]`, закрыт по умолчанию,
  моноширинный код не доминирует). E2E: `proc_pid_hidden_default`.
- **Запуски**: human-метки типов прогонов (`runTypeLabel`: summary →
  «Сводка», temporal_factcheck → «Временной фактчек», …); mono-ID
  остаётся вторичным.
- Сервис недоступен → честный fallback на registry-статус (не выдумка).

## 2. U05.2 — нет дублей Статус/Аналитика

- Статус (лейн W3-STATUS) оставляет компактные health-карточки Сна /
  Инициативы / Опыта; в Аналитике им не добавлено ни одного дубля.
  Новые виджеты (flow/route) показывают ROUTE-счётчики событий — не
  health-статусы. Углублённая временная трасса — существующие «Запуски»
  (timeline стадий) и «Самообучение» (воронка+уроки+self-model).
- **Новых поллеров нет**: все загрузки ленивые (вход во вкладку / ⟳),
  кэш 60с (`vizActivityAt`/`mca17cActivityAt`/`vizPipelineAt`);
  `/api/analytics/viz/process-activity` — один запрос, общий для
  «Процессов», «Запусков» и flow на «Памяти»; timeline дат фактчека
  переиспользует уже загруженный `temporalRuns` (Δ запросов = 0).

## 3. U05.3 — 7 визуализаций D12 §18I.12 (источник → рендер)

| # | Виджет | Раздел | Источник данных (реальный) | Рендер |
|---|---|---|---|---|
| 1 | Цикл памяти (flow) | Память и интеллект | `viz/process-activity` (24ч-счётчики процессов ingestion/facts/summary/episodes/retrieval/direct/initiative/publish/sleep) + подписи узлов из уже загруженного `/api/memory/stats` | 9 узлов с числами, err-обводка, честный «—»/0; empty-state «событий телеметрии пока нет» |
| 2 | Sankey/маршрут обработки | Запуски | тот же process-activity (Вход=ingestion; ветви: контекст/память, ответы, инициатива, истории, публикации, сон) | Sankey-lite: полосы пропорционально max-ветви; нулевая ветка — без полосы; err-ветка с красным кольцом |
| 3 | Waterfall latency/cost | Модели и расходы | СУЩЕСТВУЮЩИЙ `/api/analytics/pipeline/runs/latest` (nodes.latency_ms, capacity) | Кумулятивные полосы стадий (цвет = state), итог 9с; ёмкость прогона из usage; стоимости по стадиям нет — честная подпись (не распределяем выдуманно) |
| 4 | Heatmap активности | Обзор | новый `GET /api/analytics/viz/activity?days=N` (GROUP BY день×час по `mca_events`, время сервера) | 7/14/30 дн × 24ч, 4 уровня, красная точка ошибок, тултипы; telemetry OFF → причина; пустое окно → «событий не было», нули-от-балды не рисуем |
| 5 | Карта зависимостей модулей | Процессы (раскрытие) | реестр: `inputs`/`outputs` (ребро = артефакт X из outputs заявлен во inputs Y) + эффективные статусы | 4 слоя-колонки (Источники/Память/Интеллект/Выход) + список потоков с образцами артефактов; рёбра только из заявленных данных |
| 6 | Timeline дат источников фактчека | Память и интеллект (внутри «Временной фактчек», раскрытие) | уже загруженный `/api/factcheck/temporal/runs` (original_published_at → repost_received_at → created_at, date_source) | Распределение по date_source (честный «неизвестна») + полосы «+N дн от публикации до проверки»; «даты нет» ≠ 1970 |
| 7 | Status popover overrides чатов | Обзор (таблица чатов) | СУЩЕСТВУЮЩИЙ `/api/config/overrides-map` (D07), фильтр по chat_id | Кнопка-счётчик в колонке «Overrides» → popover с ключ=значение (маски серверные, R17); пусто → «явных переопределений нет» |

Все изображения строятся ТОЛЬКО из подтверждённых данных; unknown/
restricted — честные пустые состояния. IA — progressive details:
виджеты разнесены по существующим суб-вкладкам, один экран не захламлён.

## 4. B08 UI — карточки Stories (модуль «Истории» #/memory/rag)

- **Заголовок/синопсис**: `display_title`/`display_summary` из бэкенда
  B08; `content_status === 'insufficient_sources'` → класс
  `story-card--insufficient` (нейтральная рамка, БЕЗ success-раскраски),
  бейдж «сюжет не восстановлен», текст «Не удалось восстановить сюжет:
  нет источников». Цифровые заглушки не проходят (display-правила
  сервера, f8f9d9a0).
- **Три РАЗНЫЕ даты**: «События: …—…» / «Обнаружена: …» / «Пересобрана:
  …» (`rebuilt_at` отдельно); null → «нет данных», никогда 1970.
- **Участники**: `primary_participants` ≤5 (display_names) + кнопка
  «ещё N» → раскрытие остальных без потери (полный `participants`).
- **Раскрываемая хронология** (`timeline` сервера): дата + факт + refs
  по правам — валидированный t.me/c → clickable ссылка «сообщение N»,
  `url: null` → «в архиве» (ссылка не выдумывается).
- **Нерешённый вопрос**: `open_questions` → отдельный блок (финал не
  выдумывается); `outcome: исход неизвестен` — как есть.
- Таблица: `display_title` + честный бейдж «нет источников» на строке.
- «Хронология эпизодов» свёрнута в «Эпизоды (N)»; claims → «Факты
  сюжета»; developer-IDs — под существующим «Developer details».
- Мобильная карточка: секция ограничена `max-width: 100vw`
  (независимость от широкого grid-трека воркспейса), фильтры сжимаются,
  текст переносится — на 320px читается полностью (скриншот-closeup).

## 5. Изменённые файлы

- `web/api/analytics_viz.py` — NEW: 2 read-only GET (activity heatmap,
  process-activity); global-admin RBAC (прецедент oversight), fail-open,
  R17-safe (тип ошибки, не текст), bounded (дни ≤ 60, IN ≤ 200 имён).
- `web/app.py` — +3 строки: регистрация `analytics_viz_router` (прецедент
  memory_overview).
- `web/app.js` — состояние + методы W3-ANALYTICS (лоадеры с кэшем 60с,
  human-имена/эффективные статусы, heatmap/route/waterfall/deps/
  factdates/ovpop-модели, B08-хелперы карточки); ленивые входы в
  `oversightViewEnter`/`oversightTabEnter`/`oversightRefreshView`;
  honest-fix дубля фразы «запусков не было».
- `web/index.html` — точечные edit-якоря в analytics-секциях (heatmap на
  «Обзоре», редизайн строк «Процессов» + карта зависимостей, маршрут на
  «Запусках», flow + factdates на «Памяти», waterfall на «Моделях»,
  колонка+popover overrides в таблице чатов) и секция историй (таблица +
  карточка B08). Cover-editor/статус-блоки/шапка/модули-настройки не
  тронуты.
- `web/static/app.css` — append-блок `/* ═══ W3-ANALYTICS ═══ */`
  (heatmap/route/flow/waterfall/deps/factdates/ovpop/story-card +
  мобильные 640/380 + landscape ≤480h; prefers-reduced-motion: статично).
- `web/api/` остальные файлы (в т.ч. cover_styles, memory_overview) —
  не тронуты; Chart.js не добавлялся (все viz — CSS/flex, CSP-пин
  соблюдён, ноль новых CDN).

## 6. Тесты

- `tests/js/asap8_v63_w3_analytics_test.js` — NEW, **93 проверки**
  (TEST-LIFECYCLE: CONTRACT owner=REQ-U05/REQ-B08): human-имена,
  эффективные статусы/последнее действие/причины, heatmap-бакеты и
  honest-empty, flow/route-модели с ширинами, waterfall-раскладка,
  deps-рёбра из inputs/outputs, factdates-span, ovpop-фильтр, B08
  карточка (ready/insufficient/даты-null≠1970/участники≤5+ещё N/refs
  url+archive) + разметка/CSS-маркеры.
- `tests/test_asap8_v63_w3_analytics_viz.py` — NEW, **5 тестов** на
  реальном SQLite (aiosqlite in-memory, схема mca_events): 401, бакеты
  день×час + total/errors, telemetry_off → available:false, эффективные
  статусы working/error/no_conditions + счётчики 24ч/7д, R17 (текст
  ошибки не отдаётся), disabled → off. (CONTRACT owner=REQ-U05.)
- `tools/ui_asap8_w3_analytics_e2e.py` — NEW Playwright e2e на
  фикстурных РЕАЛЬНЫХ структурах: **74 проверки, 0 console errors** —
  каждый виджет с данными (не NaN/нули), эффективные статусы, «Детали»
  скрыты по умолчанию, honest empty (telemetry OFF), карточки ready +
  insufficient (refs t.me/c + «в архиве», «ещё 2» → имена, три даты,
  «нет данных» без 1970), мобильные 320/390 + landscape 667×375 без
  переполнения, ширина карточки ≤ вьюпорта.
- Регрессия: tests/js — **84/84 файлов passed**; pytest швов — 62 passed
  (oversight API, memory_overview API, B08 stories 22, B11 17, новые 5).

## 7. Evidence

`plans/features/asap8-v6-3-live-correction/w3-evidence-analytics/` — 21
скриншот: desktop 1440 (Обзор/Процессы+карта зависимостей/Запуски+маршрут/
Память+flow+factdates/Модели+waterfall/карточки ready и insufficient,
closeup-карточки), mobile 320/390 (обзор/процессы/карточка), landscape
667×375, + element-closeup карточки 320/390/landscape. JSON-отчёт прогона:
`$OPENCODE_WORKFLOW_SCRATCH/_ui_w3_analytics_e2e.json`.

Визуальная приёмка по скриншотам (U05.4): дублирующих badge нет;
перекрытий текста графикой нет; чипы не пересекаются; тёмного мелкого
текста на тёмном нет (подписи ≥ rgba(178,192,212,.85)); длинные строки
переносятся (`overflow-wrap`), узкие места — внутренние скролл-контейнеры.
Попутный sweep: Tailwind-классы ширины у legacy-полей не применяются в
этом рендере (поля на всю ширину) — предсуществующее, на мои виджеты не
влияет (для select heatmap задана собственная ширина); grid-трек
воркспейса «Память» растягивается предсуществующим `min-w-max`-блоком
фактчек-настроек (маркер W3-MODULES-UI — НЕ тронут), моя секция историй
защищена `max-width: 100vw`.

## 8. Checklist-гейт (чужие маркеры)

- Маркеры W3-MODULES-UI в CSS (`/* ═══ W3-MODULES-UI ═══ */ …
  /W3-MODULES-UI`) — НЕ изменены (мой блок добавлен строго после).
- Фактчек-настройки (`min-w-max`, блок temporal-настроек) и модульные
  тумблеры (`module-toggle`, `canEditModule`, …) — в моём diff отсутствуют
  (соответствующие `-`-строки в общем рабочем diff — правки параллельного
  лейна в его секциях; мои ханки: oversight-секции, stories-manage,
  analytics-виджеты).
- `web/api/cover_styles.py`, `web/api/memory_overview.py`, статус-блоки,
  шапка (U01/U07), модульные секции — не затронуты.

## 9. Остаточный риск / PENDING-live

- `LIVE_UNVERIFIED`: прод-рендер на РЕАЛЬНОЙ БД (реестр ~48 процессов,
  живые mca_events) и мобильный Telegram WebView — после деплоя волны
  (форма/права/RBAC идентичны существующим маршрутам; данные — те же
  durable-таблицы).
- Эффективный статус процессов зависит от наполненности `mca_events`
  на проде: при_OFF-телеметрии честно показывается «событий нет»
  (fallback на registry-статус), это предусмотренное поведение, не баг.
- V05 (полный release-чеклист, 2 чата + global-переключатели) — вне
  лейна, данные для мобильной части закрыты моими e2e-проверками.

## 10. Отчётные числа

- node --check web/app.js — OK; tests/js — 84/84; новый unit — 93 checks.
- pytest (новые API + швы) — 62 passed.
- Playwright e2e — 74/74 checks, console errors = 0, 21 скриншотов.
