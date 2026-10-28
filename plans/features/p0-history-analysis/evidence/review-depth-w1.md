# Ревью среза DEPTH (волна 1) — p0-history-analysis

- Вердикт: **Approved** (поведение 8 строк среза). Это не parent DONE.
- Уточнение для оркестратора: `APPROVED_BEHAVIOR / MAP_SYNC_REQUIRED`. Две строки остаются PENDING и не подписаны. Красный метаданный гейт — непривязанная карта, не дефект кода. Builder заново не запускать.
- Кандидат: `9da314e7c28a133a4529c897591ab74e87f0341d` (master, HEAD совпадает).
- Карта: `plans/features/p0-history-analysis/requirements-map.json` (strict_evidence, slice DEPTH, 10 строк).
- Проверено: 2026-10-29 01:53 +12:00. Репозиторий `C:\Code\Python\adminbot`.
- Линзы: родительский Reviewer, без листовых субагентов. Код не менялся.

## Привязка строк

| req_id | статус | доказательство на `9da314e7` |
|---|---|---|
| REQ-HA-DEPTH-PASSTHROUGH | VERIFIED | `dispatch` передаёт depth 200/400/2000/5000 в `get_recent_messages` без уменьшения (`test_dispatch_passes_depth_unchanged`). Явные 9999 тоже доходят (`test_depth_passthrough_no_cap`). |
| REQ-HA-DEPTH-NO-CAP | VERIFIED | `_HISTORY_MAX_DEPTH` удалён. В схеме depth нет `maximum`, minimum=1 сохранён. Поиск по `services/*.py`: единственное упоминание 150 на этом пути — комментарий об удалении. |
| REQ-HA-DEPTH-DEFAULT | VERIFIED | Нет параметра / пустая строка / нечисло → 50. Явные 50 и 2000 не сжимаются до дефолта. 0 и отрицательные → 1, не в 150. |
| REQ-HA-DEPTH-CAPABILITY | VERIFIED | Реальная SQLite: ровно `min(доступно, depth)`. 200 при 120 строках → 120; 5000 при 30 → 30; 610 при 610 → 610. Порядок ASC. |
| REQ-HA-DEPTH-PAGES | VERIFIED | Число чтений от запрошенного размера: 120 при странице 50 → 3; 610 при странице 500 → 2; малый лимит ≤500 → 1 запрос. Keyset `(timestamp, id)`: группы с равным timestamp, разрезанные границей страницы, без дублей и потерь (зонд Reviewer, ниже). |
| REQ-HA-DEPTH-NO-GLOBAL-MAX | VERIFIED | Нового `MAX_TOTAL_MESSAGES` нет. `_RECENT_MESSAGES_PAGE_SIZE = 500` — предел одного чтения, не выборки: depth 5000 не обрезается до 500. 150 не заменено другим общим потолком (H31). |
| REQ-HA-DEPTH-OVERSIZE-GRACE | VERIFIED | `_HISTORY_TOOL_TIMEOUT = 10.0` оборачивает всё чтение, включая страницы. depth=5000 и таймаут 0.05 с → `ОШИБКА get_recent_history: timeout`, не частичная стенограмма. `CancelledError` пробрасывается. Нового потолка нет. |
| REQ-HA-P01-NO-CONSTANT-SWAP | VERIFIED | 150 не заменено на 2000 или иной фиксированный потолок выборки. 500 — только размер страницы БД; запрошенный depth им не подменяется. |
| REQ-HA-PAGES-NOT-FULL | PENDING | Не провал и не снятие. Пользовательские поля продолжения (§4.2, строки 214–223) принадлежат TRUNC-PAGES (`REQ-HA-PAGES-CONTINUATION`, контракт волны 2: `has_next` / cursor / `@@HISTORY_SAMPLE`). DEPTH агрегирует страницы БД в одну выборку и не выдаёт одну страницу чтения за полный ответ. Строка в карте жива, slice всё ещё DEPTH, статус не подделан в VERIFIED. |
| REQ-HA-INCOMPLETENESS-REPORTING | PENDING | Не провал и не снятие. Структурный охват и причина неполноты — волна TRUNC-PAGES (`REQ-HA-CONTRACT-REWORK`, `REQ-HA-PAGES-CONTINUATION`, H14 в контракте). На этом срезе таймаут уже не возвращает первые строки как успех: только строка ошибки. Символьная усечка `_truncate(..., 3500)` не тронута — это ожидаемое промежуточное состояние, не дефект DEPTH. |

Сводка: verified 8 / failed 0 / pending 2 / N/A 0.

## Почему две строки законно ждут TRUNC-PAGES

Они не выпали из учёта: в карте по-прежнему `slice=DEPTH`, `status=PENDING`, evidence пустой. Перенос реализации согласован с границей Architect (`architecture-contract.md`: DEPTH = снятие потолка 150, passthrough, `ORDER BY timestamp, id`, порционные чтения; волна 2 = поля продолжения, честные `has_next`/`incomplete`, снятие символьной обрезки). Дублирующее обязательство уже есть в строках TRUNC-PAGES, поэтому откладывание не прячет требование. Подписывать эти две строки как VERIFIED нельзя.

## Гейт

Команда: `requirements_gate.py check --stage review --slice DEPTH --candidate 9da314e7c28a133a4529c897591ab74e87f0341d`.

Результат: **FAIL, errors=11**, `scoped=10`.

- `candidate mismatch` — в карте `candidate_commit` пустой.
- 10 строк DEPTH: `mandatory not ['VERIFIED'] (got PENDING)`.

Это книжная сверка. Поведение 8 строк доказано на этом коммите; карта ещё не обновлена. PM должен проставить `candidate_commit`, evidence с этим SHA и статус VERIFIED только у восьми строк. Две отложенные оставить PENDING. Не считать красный гейт поводом переписывать код.

## Что проверено заново

Не принимались на веру утверждения Builder.

- Дифф кандидата: `database.py`, `tool_router.py`, `tool_schemas.py`, три тестовых файла. Усечка `_HISTORY_MAX_SYMBOLS = 3500` и вызов `_truncate` не изменены.
- Поиск скрытого общего потолка по `services/`: на пути depth его нет. Кламы 150 в других функциях (участники карты чата, граф, лор) к выборке истории не относятся.
- Вызывающие `get_recent_messages`: поиск (дефолт 6), фактчек (1 и fallback окна ≤500), memory lookup (120), fallback `get_messages_around`. Для лимита ≤500 остаётся один запрос. Набор строк при уникальных timestamp не меняется; при равных timestamp порядок теперь детерминирован `id DESC` — это требуемый tie-break, не регрессия «последних N». Путь B (`query`) не изменён по смыслу: FTS, окно 12 ч, сортировка по timestamp; depth в этом пути в БД не уходит.
- Порядок: `ORDER BY timestamp DESC, id DESC`, возврат ASC. `timestamp INTEGER NOT NULL`, `id INTEGER PRIMARY KEY`.
- Зонд Reviewer на живой in-memory SQLite (не сохранён как тест, исходники не менялись):
  - немонотонные timestamp и группы равного времени, разрезанные страницей 2–3: результат совпал с оракулом `ORDER BY timestamp DESC, id DESC LIMIT`, без дублей, без потерь, чужой чат не протекает;
  - H8: вставка более нового сообщения после первой страницы не сдвигает уже взятую выборку;
  - лог успеха: `fetched` / `count` / `out_chars`, без текста, имени и URL (при том что сам ответ инструмента имя и URL содержит);
  - `CancelledError` не проглатывается.
- Тесты: `pytest tests/test_p0_history_depth_round1029.py tests/test_recent_history_tool_round1015.py tests/test_agentic_ai_round1020.py::TestToolSchemasEnCanon tests/test_mca19_rework_r1_round1044.py -q -o timeout=600` → **59 passed, 0 failed**, 5.20 с. Описание схемы не содержит тем вроде Внуково.
- Внешние API не спорные: веб-поиск не требовался.

## Неблокирующее (один раз, в бэклог, не чинить в этом срезе)

1. `README.md` и `plans/ARCHITECTURE.md` всё ещё описывают `get_recent_history` как «до 150» / `depth` 1..150. На поведение модели это не влияет: схема инструмента уже без maximum. Поправить при ближайшем касании доков.
2. `slice-graph.json` пишет write scope `tests/test_history_depth.py`, фактический файл — `tests/test_p0_history_depth_round1029.py`. На приёмку поведения не влияет.
3. В постоянных тестах нет кейса «равные timestamp через границу страницы». Зонд Reviewer это закрыл; имеет смысл добавить регрессию в следующем касании `database.get_recent_messages`, не блокируя срез.
4. Индекс `idx_smart_messages_chat_ts (chat_id, timestamp)` не включает `id`. Для корректности keyset это не нужно. Имеет смысл смотреть план запроса, только если большие выборки упрутся в таймаут на проде.
5. Лог не помечает, что `_truncate` ещё срезает текст до 3500 символов. Это ожидаемо до TRUNC-PAGES; `out_chars` уже пишется.

## Что сознательно не блокирует

Символьная обрезка `_truncate(..., _HISTORY_MAX_SYMBOLS)` на месте. Директива среза и бриф прямо оставляют её волне TRUNC-PAGES. Пользователь по-прежнему может получить усечённую стенограмму, пока не выйдет следующая волна. Это не повод отклонять снятие потолка 150.

## Следующий шаг

PM: привязать карту к `9da314e7c28a133a4529c897591ab74e87f0341d`, записать evidence восьми VERIFIED строк, две отложенные оставить PENDING. Orchestrator: не открывать цикл Builder по DEPTH. Следующая реализация — TRUNC-PAGES, после этой сверки карты.