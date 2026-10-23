# Ревью REV-ASAP2-TELEMETRY — `e3d28812` (durable-флаги уточнений)

- Lane: REV-ASAP2-TELEMETRY, read-only. Время: 2026-10-23 20:19 +12:00.
- Кандидат: `e3d288123d260fb5598a72ee083ebac5afc070a6` (HEAD на момент ревью).
- Diff: 4 файла, +271: `services/usage_events.py` (+2 ключа whitelist),
  `services/direct_chat_service.py` (helper + 2 bool), новый тест (9),
  evidence `telemetry-clar.md`. Поведение Direct не меняется, только payload
  `plan_meta`; схем/миграций/новых событий нет.

## Вердикт: PASS по этой полосе — в поезд можно

### 1. R17 / privacy — ЗАКРЫТО
- В durable-колонку добавлены ровно два boolean: `needs_clar`,
  `clar_target_present` (`direct_chat_service.py:343-344`). Оба проходят
  существующий санитайзер через `isinstance(value, bool)`
  (`usage_events.py:141-142`), новых веток фильтра нет.
- Текста цели в payload нет: единственное чтение `clarification_target` —
  предикат `_clar_target_present` (строка 302-311), наружу отдаётся bool.
  `clarification_target` не входит в `PLAN_META_FIELDS`, поэтому
  `sanitize_plan_meta({"clarification_target": ...})` его отбрасывает.
- Свободный текст под любыми ключами отсекается `_IDENT_VALUE_RE`
  (пробелы/кириллица/длина >64): проверено
  `sanitize_plan_meta({"needs_clar": "какой именно медиафайл нужен?"})` →
  `None`. Реальный payload 297 байт (лимит 2048) — запаса достаточно.
- Логи нового кода текст цели не печатают.
- Nonblocking: санитайзер принимает и token-like строку под этими ключами
  (`{"clar_target_present": "media_target"}` → `{'clar_target_present':
  'media_target'}`), т.к. общего bool-only правила нет. Сегодня такого
  писателя нет и свободный текст всё равно отсекается; для жёсткого
  типового контракта можно добавить bool-only сет (не блокер).

### 2. Семантика — ЗАКРЫТО
- `needs_clar`: `getattr(p, "needs_clarification", False) is True`
  (`direct_chat_service.py:343`). Проверено: `1`, `"false"`, `[True]` →
  `false`; `True` → `true`. Совпадает с `normalize_l1_plan`
  (`direct_l1.py:341`, строгий JSON boolean).
- `clar_target_present`: `isinstance(target, str) and bool(target.strip())`
  (`direct_chat_service.py:302-311`). Проверено: `"  media_target  "` →
  `true`; `None`/`""`/`"   "`/`123`/dict → `false`. Совпадает с
  нормализацией (`direct_l1.py:363-365`) и с фактическим гейтом
  Writer-директивы (`direct_l1.py:915-919`) для планов из нормализации.
- Мусорные структуры запись не ломают: `object()`-план → весь plan_meta
  fail-open drop (исключение не вылетает), «враждебный» property цели →
  `false`, остальные оси целы (тест + код).
- Пара `(true,false)` = уточнение без предмета: generic-директивы нет
  (`direct_l1.py:960-969`) — её и видно отдельно. Пара `(false,true)`
  достижима (нормализация сохраняет target независимо от флага; проверено
  `normalize_l1_plan({"needs_clarification": False,
  "clarification_target": "media_target"})`), метрика её уточнением не
  считает — корректно. В evidence описаны только `(true,true)` и
  `(true,false)`; док-точность, nonblocking.

### 3. Один UPDATE, без новых таблиц/событий — ЗАКРЫТО
- SQL не менялся (`direct_chat_service.py:295-299`), вызов один:
  `_attach_l1_plan_meta` (4346) → `conn.execute` (4376-4380). Новых
  таблиц/колонок/событий/второго апдейта нет; в `usage_events.py` изменён
  только whitelist.
- Гварды прежние: `module='direct_chat' AND step='l1_planner' AND
  plan_meta IS NULL`; на один ответ — максимум один UPDATE-стейтмент
  (e2e-тест подтверждает `len(updates) == 1`).
- Nonblocking (наследие F2, не этой правки): при repair/ladder на один
  ответ бывает несколько usage-строк `l1_planner`, и UPDATE заполняет все —
  доля уточнений в evidence-SQL считается по строкам, а не по ответам. Для
  answer-level метрики добавить `COUNT(DISTINCT correlation_id) FILTER (...)`.

### 4. Fail-open — ЗАКРЫТО
- `_attach_l1_plan_meta` целиком в try/except (`direct_chat_service.py:
  4356-4384`), ошибка только WARNING; расчёт флагов внутри try. Ответ
  Direct не прерывается; `CancelledError` (BaseException) не глотается —
  корректно. Тест `test_attach_is_fail_open_on_junk_plan` зелёный.

### 5. Прогоны (воспроизведено на кандидате)
- `tests/test_asap2_telemetry_clar.py`: **9 passed** (3.14 s).
- `test_asap2_clar_contract` + `test_asap7_direct_l1` +
  `test_asap8_v6_wc_direct_d03`: **70 passed, 0 failed** (3.25 s).
- Набор из evidence (+`test_asap7_direct_settings`): **97 passed,
  2 failed** (4.34 s). Оба падения — `test_migration_v35_idempotent_twice`
  и `test_backup_guard_fires_before_pending_step`, `assert 37 == 35`:
  схема дошла до v37 (SAMPLES-UX, `29b91004`, `services/database.py`), тест
  не обновлён; диф `e3d28812` `database.py` не касается → **pre-existing,
  к правке не относится**.

## Ограничения
- Прод-статистика: `WAITING_EXTERNAL` до деплоя; evidence честно не
  заявляет живых чисел. SQL из evidence валиден по схеме
  (`pg_db.py:311-328`: `ts TIMESTAMPTZ`, `plan_meta JSONB`) и корректно
  читает bool как `'true'`; строки до выката (без новых ключей) занизят
  долю в первые ~24 ч — для честного окна добавить
  `plan_meta ? 'needs_clar'` в фильтр.
- Карта ASAP2 не содержит строки под эту телеметрию, `candidate_commit`
  карты = `e4ee54f3` (не `e3d28812`) → привязку/учёт делает родительский
  PM/Orchestrator; карту в этой полосе не менял.
- UI/визуал не затронут, Playwright/Browser Use не требовались.

## Итог
Код аддитивный, R17 сохранён (в durable-колонку идут только два bool,
свободный текст отбрасывается), семантика совпадает с нормализацией,
запись — прежний единственный fail-open UPDATE. В поезд можно; после
деплоя — снять метрику по evidence-SQL и зафиксировать фактические числа.