# ASAP2-TELEMETRY — durable-наблюдаемость уточнений

Дата: 23.10.2026. Lane: ASAP2-TELEMETRY.

## Проблема (пробел наблюдаемости)

`needs_clarification` / `clarification_target` существовали только в
объекте плана в памяти процесса. Durable `plan_meta` на usage-строках
`step="l1_planner"` (канал ASAP 7 F2, `services/usage_events.py` +
`_attach_l1_plan_meta`) их не содержал → на проде нельзя было посчитать ни
частоту уточнений, ни долю «ложных» (true без предмета / generic-ветка).

## Что добавлено (аддитивно, без новой таблицы/события)

1. `services/usage_events.py:58` — в R17-whitelist `PLAN_META_FIELDS`:
   `"needs_clar"`, `"clar_target_present"` (bool → проходит существующий
   санитайзер через `isinstance(value, bool)`, новых веток фильтра нет).
2. `services/direct_chat_service.py:302-310` — `_clar_target_present(plan)`:
   та же строгая семантика, что в `normalize_l1_plan` (только `str` +
   `strip()`); доступ к атрибуту обёрнут в try → «враждебный» план не
   превращает телеметрию в ошибку.
3. `services/direct_chat_service.py:343-344` — в `_l1_usage_plan_meta`:
   - `needs_clar`: `getattr(p, "needs_clarification", False) is True`
     (строгий boolean, как §3.2/`normalize_l1_plan`; строка `"true"`/`1`/
     `null` → `false`);
   - `clar_target_present`: непустая цель ⇒ `true`.
   Пара `(true,true)` = валидное уточнение; `(true,false)` = generic-ветка.
   Путь записи прежний: один fail-open `UPDATE ... SET plan_meta`
   по `correlation_id` (`_attach_l1_plan_meta`), никаких новых событий.

R17-безопасность: в durable-колонку попадают только два bool. Ни текста
цели, ни пользовательского/промпт-текста; проверено тестом
(подстроки `media_target` в payload нет) и тем, что оба ключа — bool,
а санитайзер отбрасывает неизвестные ключи и свободный текст.

## Тесты

`tests/test_asap2_telemetry_clar.py` (TEST-LIFECYCLE: CONTRACT
owner=ASAP2-TELEMETRY), 9 тестов / 9 passed, 2.9 s:

- `false`-план → `needs_clar=false`, `clar_target_present=false`;
- `true` + цель → `true` + `true` (и текста цели нет в payload);
- `true` + `None`/`""`/`"   "` → `true` + `false`;
- мусорный тип цели (dict) → `true` + `false`; «враждебный» property →
  `false`, остальные оси целы; `None`-план → оба `false` + `fallback`;
- писатель `_attach_l1_plan_meta` fail-open на мусорном плане (не бросает);
- whitelist: флаги проходят, `clarification_target` (свободный текст) —
  отбрасывается;
- end-to-end `handle` (fake LLM/PG): ровно один `UPDATE plan_meta`,
  в JSON пара `(true,true)`, ключи ⊆ `PLAN_META_FIELDS`.

Смежные прогоны (точечно): `tests/test_asap2_clar_contract.py`,
`tests/test_asap7_direct_l1.py`, `tests/test_asap7_direct_settings.py`,
`tests/test_asap8_v6_wc_direct_d03.py` → **97 passed, 2 failed**.
Оба падения — предсуществующие и к этой правке не относятся
(`PRAGMA user_version` == 37 при захардкоженном 35 в тесте v35;
`services/database.py` в диффе отсутствует).

## Измерение на проде (после деплоя)

Статистика появится только для строк, записанных **после** выката
(WAITING_EXTERNAL — деплой не входил в эту полосу):

```sql
-- частота уточнений и доля generic-веток (24ч)
SELECT
  COUNT(*) FILTER (WHERE plan_meta->>'needs_clar' = 'true')            AS clar,
  COUNT(*) FILTER (WHERE plan_meta->>'needs_clar' = 'true'
                     AND plan_meta->>'clar_target_present' = 'false')  AS generic,
  COUNT(*) FILTER (WHERE plan_meta IS NOT NULL)                        AS with_meta
FROM llm_usage_events
WHERE module = 'direct_chat' AND step = 'l1_planner'
  AND ts > now() - interval '24 hours';
```

Старые строки `plan_meta` остаются без новых ключей (честный NULL/пусто),
ретро-пересчёта нет и не требуется.
