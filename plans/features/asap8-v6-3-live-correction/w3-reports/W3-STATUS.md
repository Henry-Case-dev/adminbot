# W3-STATUS — U03 (Статус без дубликатов, фикс 1970, читаемость) + U04 (Логи — только в Статусе) + B03-блок «Просрочено N»

Ленa: W3-STATUS · HEAD на старте `d6366e3` · ветка master · **не коммитила** (по брифу).
Параллельный лейн W3-EDITOR (cover-editor) — зоны разделены, гейт пройден (см. §7).

## 1. Реализации (файл:функция/блок)

### U03.1 — одна каноническая панель «Сон / Глубокий сон»
- `web/index.html` (секция Статуса, карточка `.status-sleep`): заголовок «Сон и активность» →
  канонический **«Сон / Глубокий сон»**; каждая фаза теперь несёт **Стадию / Сейчас /
  Следующий запуск / Последний запуск / Результат**:
  - стадия — `dreamStageLabel()`/`deepStageLabel()` (running+manual → «синтез (ручной
    прогон)», `limit_exhausted`, `enabled=false` → «выключен настройками», иначе
    «ожидание окна/расписания»);
  - результат — `dreamResultLabel()` (фактический дневной бюджет: синтезов/токенов
    today/limit; нет данных → «—», нули не выдумываем) и `deepResultLabel()`
    (последняя попытка deep-sleep-диагностики, D14-лейблы; не было → «ещё не выполнялся»);
  - последний запуск — `statusTsLabel(lastRun, 'ещё не выполнялся')` (см. U03.2).
- **Удалён второй ряд одинаковых sleep-бейджей** из шапки «Мониторинга Интеллекта»
  (2 × `badge-btn` + `scrollToSleepWidget()`); сам блок оставлен для убеждений/парадигм/
  характера (ленты не тронуты). Данные — ОДИН источник: cognition-payload
  (/api/memory/cognition/status + /api/memory/deep-sleep), уже загружен `loadCognition`;
  новых запросов/таймеров нет.

### U03.2 — фикс «22.01.1970» (честные timestamps)
- `web/app.js`: module-функции `_tsNormalizeMs(value)` + `_tsStatusLabel(value, phrase)`
  (не методы — контракты `.call({})` не ломаются) и методы-делегаты
  `normalizeTsMs`/`statusTsLabel`. Правила: null/undefined/''/0/отрицательные/NaN →
  unknown; seconds vs millis — по порядку величины (<1e11 → секунды); всё вне
  [1990-01-01, 2100-01-01) — epoch-заглушка (в т.ч. мусор ~1.8e6 с, дающий
  «22.01.1970») → unknown; числовые строки и ISO — парсятся; старые импорты
  (например 2016) остаются датами.
- `fmtLogTs`/`fmtLogTime`/`fmtTs` переведены на нормализатор; `botLastActivity` —
  «нет данных» вместо фальшивой даты. Статусные поля Сна — `statusTsLabel(...,
  'ещё не выполнялся')`.

### U03.3 — «Мониторинг интеллекта» / «Здоровье памяти»
- «Здоровье памяти» разделено: **смысловые результаты** (`data-expired-block` — блок
  B03 «Просрочено N» + активные/архив убеждений) и **технические счётчики**
  (`data-memory-tech`: не подтверждено, фактов к переизвлечению [бывш. «Просрочено»
  facts_overdue — переименован, чтобы не спорить с TTL-«Просрочено»], сырьё, БД, диск).
- Раскладка — строки «имя → значение» (`.mem-kv__row`), не разноцветные pills одной
  строкой на мобиле.
- Читаемость лент: подложки `.intel-card .ribbon` и `.ribbon-item` (слои КАРТОЧЕК,
  opacity/background) — **CORR-1 соблюдён**: полигональный фон и весь его rendering
  stack не тронуты (гейт-ассерт: блок W3-STATUS в CSS не содержит правил фона).

### U03.4 — воронки «Инициатива» и «Опыт»
- **Инициатива**: `data-initiative-independent` — независимая воронка наблюдателя
  (8 стадий: Наблюдено → Квалифицировано → Возможности → Намерения → Решения →
  Текст → Перепроверка → Отправлено; реакции — подписью, scan/eval-пропуски — в hint/sub).
  Значения — durable-счётчики `task_jobs kind='initiative.observe'` + окна событий
  24ч/7д (mca_events) через **новый GET /api/memory/intel-funnels** (W1 B01 layout).
  Стадия останова — `warn`; liveness-штамп (`_initiative_observer_last_tick`); тиков
  нет → «наблюдение ещё не выполнялось», НЕ «работает». states disabled/restricted →
  воронки нет (честная строка состояния). Причины пустоты — по первой нулевой стадии.
- **Опыт**: `data-experience-windows` — окна 24ч/7д из СУЩЕСТВУЮЩЕЙ read-only воронки
  `/api/oversight/experience/funnel?days=1|7` (mca-17c; Δ endpoint = 0) + последнее
  применение (`intel-funnels.last_application`, ts+исход) + честная причина пустоты
  (B02-счётчики: scanned==0 / кандидатов нет (rejected/duplicates/LLM недоступен) /
  применений за окно не было / kill-switch).
- Пустая панель ≠ «работает»: ни один блок не выводит «работает» по мастер-флагу —
  только по фактическим durable-данным.

### B03 — блок «Просрочено N»
- **Новый GET /api/memory/expired-overview** (`web/api/memory_overview.py`): обёртка
  W1 `MemoryManager.expired_memory_overview(chat_id)` (MemoryManager(db, llm=None),
  кэш per-db); ответ `{available, now_ts, expired_total, expired_searchable,
  needs_recheck, superseded_total, infinite_retention}`; fail-open W1 (error →
  available=false, не 500); 503 при отсутствии БД; RBAC — `_require_global_admin`
  (та же матрица, что /api/memory/health).
- Рендер в «Здоровье памяти»: «Просрочено: N · доступно поиску: X · требует
  перепроверки: Y · вытеснено новыми версиями: Z · режим хранения: бессрочный/обычный»;
  unavailable → «данные недоступны — сервис памяти не ответил».

### U04 — логи только в Статусе
- `web/index.html`: блок `#status-logs` (level-select, чип «Саммари», trace-фильтры,
  копирование, счётчики ERROR/WARN, pagination «показано N из M», экранирование/
  redaction/RBAC — тот же /api/status/logs) **физически перенесён** из шаблона
  Аналитики в конец `.status-grid` Статуса (последняя карточка, `sg-12`); карточка-
  переход `#status-logs-link` («Логи → Аналитика») удалена. В Аналитике блока нет
  (остался только комментарий-указатель). Полоска `.status-counts` («Ошибки/Предупреж-
  дения ↓ к логам») ведёт к блоку в том же разделе.
- `web/app.js`:
  - `{id:'logs'}` удалён из `oversightTabs`; ветка `tab==='logs'` в `oversightSetTab`
    удалена; фильтр в `oversightMobileTabs` упрощён (якоря больше нет);
  - `loadLogs()`/`loadLogCounts()` на входе в Аналитику **убраны**
    (`oversightTabEnter`); ленивый догруз логов перенесён на вход в Статус
    (`setTab('status')`), счётчики — по-прежнему в `loadStatus`;
  - `scrollToLogs()` вне Статуса ведёт на канон **`#/?scroll=logs`**;
  - `_consumeLogsScrollLink(rawHash)` — нормализация канона и легаси
    `#/oversight?scroll=logs|tab=logs` к `#/` (replaceState, F5 не повторяет скролл,
    чужой query-контекст Аналитики не трогается); хуки в `hashchange`-хендлере
    (до applyRoute — без транзитного входа в Аналитику) и на холодном старте;
  - `_scrollToLogsAnchor` — скролл с offset реальной sticky-шапки (измерение высоты
    header), учёт скроллера (mobile `.scroll-area` с его scroll-padding-top), bounded
    settle-доводка (≤5×180мс) против догрузки данных выше блока, вспышка контура
    сохранена.
- `web/static/app.css` — блок `/* ═══ W3-STATUS ═══ */` (после `/W3-EDITOR`): mem-kv,
  подложки лент, funnel-grid, exp-windows, `#status-logs` scroll-margin (+ отмена в
  mobile-скроллере, где работает scroll-padding), тач-цели контролов логов, и
  Visual Neighborhood Sweep: на ≥768 compact-ширины селектора/фильтров логов
  (`.field{width:100%}` перебивал Tailwind w-32/w-40 — растяжка на всю карточку),
  на мобиле полноширинные (тач-дружелюбно).

## 2. Backend-поверхность

- НОВЫЙ `web/api/memory_overview.py` (мой файл-зона; не cover_styles): 2 read-only
  GET, RBAC global-admin, R17-safe (числа/коды, без контента), TTL-кэш воронок 60с
  (паттерн _HEALTH_COUNT_TTL), fail-open per-section.
- `web/app.py`: +3 строки — include `memory_overview_router` рядом с memory_router
  (прецедент stories/oversight17c; routes.py не тронут).
- handlers/services НЕ тронуты (backend W1 готов).

## 3. Checklist-гейт (параллельные лейны)

- W3-EDITOR маркеры на месте: `web/static/app.css` — блок `/* ═══ W3-EDITOR ═══ ... ═══
  /W3-EDITOR ═══ */` (2 маркера, цел), мой блок W3-STATUS добавлен ПОСЛЕ него;
  `w3-evidence-editor/`, `tools/ui_asap8_w3_editor_e2e.py` не тронуты мной.
- Мой diff index.html (по хункам): 5774 (снос логов из Аналитики), 7058–7199 (сон/
  шапка/здоровье), 7336 (воронка инициативы), 7818–7866 (окна опыта + вставка логов).
  Хунки 906–1404 (cover-editor, coverStyles) — лейн W3-EDITOR, мной не писались;
  app.js хунки 11141–11931 (coverStyles) — тоже их зона; пересечений нет.
- `plans/current_task.md`, `plans/workflow_state.md`, `services/*`, `handlers/*` —
  не тронуты (services/disk_retention.py в статусе M — чужая правка, не моя).

## 4. Тесты

Новые (TEST-LIFECYCLE: CONTRACT owner=REQ-U03/U04):
- `tests/js/asap8_v63_w3_status_logs_test.js` — контракт W3-STATUS: одна панель сна
  (стадия/результат/лейблы), U03.2 seconds/millis/None/0/старые импорты/TZ/мусор-1970,
  mem-kv/CORR-1, воронка (фикстура: 8 стадий, значения, liveness, причины пустоты,
  disabled→null), expWindows/причины пустоты, U04 (tabs без logs, логи в Статусе,
  loadLogs убран из oversightTabEnter, нормализация легаси, канон-ссылка).
  **W3-STATUS-UNIT-OK**.
- `tests/test_webapp_memory_overview_api.py` — 7 passed: 401/403, форма
  expired-overview, fail-open (available=false), форма intel-funnels (counters/окна/
  лаг/последнее применение), R17-греп.
- `tools/ui_asap8_v63_w3_status_e2e.py` — Playwright e2e (стабы /api/*, R17):
  **W3-STATUS-E2E-OK**, 26/26 чеков, console без ошибок: одна панель сна, «ещё не
  выполнялся», нет «1970», нет дубля бейджей, раскладка «Просрочено: 3584», воронка
  8 стадий (Наблюдено 420, liveness), окна опыта, логи в status-grid (rows/счётчики/
  фильтры/копирование), в Аналитике нет вкладки и блока логов, легаси-редирект →
  `#/` + tab=status + блок полностью виден, 320/390/1440 без h-overflow.

Обновлённые (контракты перевернуты U04/U03.1 — старые пины защищали отменённое
владельцем решение Wave 2 «логи в Аналитике»):
- `tests/js/asap6_wave2_ux_tabs_test.js` — 7 вкладок без якоря; oversightTabEnter без
  loadLogs; consumer-нормализация; логи в Статусе.
- `tests/js/round1025_f11_status_grid_test.js` — порядок §12 с `card p-4 status-logs`
  последней; блок в Статусе.
- `tests/js/asap8_d1213_save_contract_test.js` — канон «Сон / Глубокий сон», дубль
  бейджей удалён.
- `tests/test_webapp_f11_round1025.py`, `tests/test_webapp_round1014_ui.py`,
  `tests/test_webapp_round1015_ui.py` (mobile order без бейджей),
  `tests/test_webapp_key_availability_ui.py` (граница среза на status-шаблон).

Прогоны (финал):
- все JS-тесты репо: **0 failures** (~85 файлов);
- py: статус/webapp-набор — **551 passed**; v63 backend (b01/b02/b03 + mca17c) —
  **73 passed**; доп. набор — **401 passed**;
- e2e — W3-STATUS-E2E-OK (см. выше).

## 5. Evidence

`plans/features/asap8-v6-3-live-correction/w3-evidence-status/`:
`w3_status_desktop_1440.png`, `w3_status_logs_desktop.png`, `w3_status_mobile_390.png`,
`w3_status_narrow_320.png` (Playwright), `_ui_w3_status.json` (26 чеков, ok=true),
`w3_unit_output.txt` (W3-STATUS-UNIT-OK), `w3_py_suites.txt`, `fingerprint.txt`
(HEAD `d6366e3` + SHA256 первых 16 hex моих файлов).

Дополнительный визуальный осмотр реальным браузером (Browser Use, CDP-эмуляция
390/1036): панель сна, «Здоровье памяти» (раскладка строками), воронка наблюдателя
(8 ячеек, warn на «Текст», liveness), окна опыта 24ч/7д + «последнее применение»,
логи (компактные контролы на desktop, полноширинные на мобиле), легаси-редирект
(hash → `#/`, tab=status, блок виден). Горизонтального переполнения нет; тёмного
мелкого текста на тёмном/просвечивания не выявлено; находка sweep'а (растяжка
`.field` в блоке логов) исправлена в том же_cleanup.

## 6. PENDING-live (postdeploy, вне лейна)

- Живой вид блока «Просрочено N» на прод-данных (ожидаемо N≈3584 по ТЗ) —
  LIVE_UNVERIFIED (нужен прод/препрод с реальной БД памяти).
- Живая частота воронок (initiative.observe/experience.review на проде) —
  LIVE_UNVERIFIED (зависит от реальных durable-джоб).
- Остальное (роутинг, рендер, редирект) покрыто e2e на реальном web/index.html.

## 7. Incidental findings

- `related-nonblocking`: легаси-редирект при уходе из Аналитики проходит транзитный
  reset скролла setTab — закрыто $nextTick-упорядочиванием + settle; если в будущем
  появятся другие reset-очереди — держать их до anchor-скролла.
- `unrelated/pre-existing`: `fmtCountdown` печатает «14 0м» (виден в бейджах сна на
  стабе) — формат countdown без «ч» у часов; вне лейна (F5-канон), на скриншотах не
  мешает чтению.
- `unrelated/pre-existing`: .field{width:100%} перекрывал Tailwind w-* и в СТАРОЙ
  позиции логов (тот же рендер был в Аналитике) — исправлено в рамках переноса
  (Visual Neighborhood Sweep).

## 8. Изменённые/новые файлы (только этот лейн)

- N `web/api/memory_overview.py`
- M `web/app.py` (+3 строки: include роутера)
- M `web/index.html` (status-секции: сон, шапка «Мониторинга», здоровье памяти,
  воронка инициативы, окна опыта, перенос логов)
- M `web/app.js` (форматтеры/лейблы/лоадеры/computed/роутинг U04; хунки 11141–11931 —
  чужие, W3-EDITOR)
- M `web/static/app.css` (append-блок W3-STATUS)
- N `tests/js/asap8_v63_w3_status_logs_test.js`,
  N `tests/test_webapp_memory_overview_api.py`, N `tools/ui_asap8_v63_w3_status_e2e.py`
- M 6 устаревших тестов (см. §4)

Кандидат: рабочий_дерево на HEAD `d6366e3` (не коммитил). SHA256-отпечатки —
`w3-evidence-status/fingerprint.txt`.

@Orchestrator — на строгую независимую ревью.
