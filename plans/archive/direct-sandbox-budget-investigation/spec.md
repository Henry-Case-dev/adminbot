# F-15 — Расследование и фиксы: sandbox reason=budget + graphrag memorize JSON (раунд 10.3)

> Создано @Architect 09.09.2026 (новая фича — КГ-канона spec нет; рекон-гипотезы
> @PM — в разделе «Рекон-база» tasks.md). Пункты ТЗ владельца 5 и 7 (два
> бэкенд-расследования). Base: HEAD `d30b203`, pytest 4760, прод PID 454654.
> ⚠️ Прод-диагностика (T-965/T-966) — ДО кода: сначала факты (root cause), потом фикс.

## 1. Контекст и канон

### Задача 5 — WARNING `[direct] no key — sandbox answer | chat=-1002661910336 | reason=budget`

- Код-путь: `direct_chat_service.py:543-553` ловит `NoApiKeyForChat` (llm_client.py:122)
  из `chat_with_tools`/`llm.generate`; исключение бросает `_resolve_api_key_and_source`
  (llm_client.py:317-356): (1) свой ключ `chat_keys` → source 'chat'; (2)
  `chat_params.keys.allow_global=false` → reason 'forbidden'; (3) `chat_usage.budget_exceeded`
  → reason 'budget' (llm_client.py:347-348); (4) иначе глобальный ключ + `_record_global_usage`
  на КОНЦЕ вызова (:374-391).
- `budget_exceeded` (chat_usage.py:100-113): лимиты `limits.chat_global_key_budget_requests`
  (дефолт 25) / `limits.chat_global_key_budget_tokens` (дефолт 100000); ЛЮБОЙ лимит ≤ 0 =
  ЗАПРЕТ (True); used из PG `chat_usage` (PK chat_id, day, metric); день =
  WORKER_BUDGET_TZ Asia/Yekaterinburg (chat_usage.py:25, :44-50); счётчик растёт на
  КОНЦЕ каждого LLM-вызова с source='global' (1 вызов + estimate len/4, :116-125).
- Fail-open: PG down/разусередину → `used_today` возвращает {} → NOT exceeded (бот жив).
- Прямые тесты: `tests/test_chat_keys.py:157-183` ('forbidden'/'budget').
- Гипотезы (проверить в T-965): (а) лимиты ужаты hot-конфигом; (б) счёт за день по
  ВСЕМ пайплайнам чата; (в) чат использует глобальный ключ без своего и allow_global=true;
  (г) смена дня/TZ (в БД проверить фактическое значение day); (д) оценка len/4 грубая —
  частые вызовы упираются в токен-лимит раньше ожидаемого.

### Задача 7 — WARNING `graphrag memorize: LLM answer is not a JSON list — skipped`

- `summary_memory.py:380-418 parse_fact_list(raw)`: candidates = [raw] + [unwrapped
  code-fence]; json.loads; dict → первое list-значение; НЕ-список → WARNING «not a
  JSON list» (:408) + [] (тихо, без содержимого raw); per-item `_validate_fact`
  (:421-444: subject/predicate/object — str, _normalize_name, капсы, subject != object,
  context cap).
- Вызов из memorize-хука: `direct_chat_service.py:581-584 fire_and_forget(
  self._memorize_direct_reply(...))` → `_memorize_facts_inner` (summary_memory.py:1448-1459:
  `raw = await self._extract_facts(tail)` → `parse_fact_list(raw)` → пусто → INFO,
  return) — фоновая ветка, юзеру не падает (fire-and-forget :447-459).
- Гипотезы (проверить в T-966): (а) модель ответила прозой/буллетами (промпт-дрейф/
  фоллбэк-провайдер); (б) пустой/короткий ответ; (в) массив строк или объект без
  list-значения; (г) ёлочки/длинные тире (канон-запрет раунда 5) ломают JSON.
- Сейчас raw НЕ логируется → невозможно диагностировать; тесты фиксируют WARNING:
  `tests/test_graphrag_memory.py:604,621` (substring «not a JSON list»).

## 2. Прод-диагностика (ДО фикса; T-965/T-966 — @DevOps/@Builder; результаты — в tasks.md)

### 2.1. T-965 — задача 5: собрать факты

SQL (значения ключей/секретов НЕ копировать — R17; только last4/факты наличия):

```sql
SELECT * FROM chat_usage WHERE chat_id = -1002661910336 ORDER BY day DESC;
SELECT key, value FROM bot_settings
  WHERE key IN ('limits.chat_global_key_budget_requests',
                'limits.chat_global_key_budget_tokens');
SELECT chat_id, key_name, key_hint FROM chat_keys WHERE chat_id = -1002661910336;
SELECT chat_id, chat_params->'keys' AS keys FROM chat_profiles WHERE chat_id = -1002661910336;
```

Плюс:
- `journalctl -u admin_bot --since "2026-09-09 00:00" | grep -i "no key"` — точное время WARNING;
- `GET /api/config/keys/status` (F-7 §6; chat_usage.key_status :128-136) — счётчик глазами;
- `uptime_events` — рестарты вокруг WARNING;
- сопоставить: если между WARNING и следующим ответом «минуту спустя» произошла смена
  дня (TZ Екб) или рестарт — зафиксировать.

**Вывод:** доказанный root cause (по какой из гипотез а–д) + объяснение, почему
«минуту спустя бот отвечал».

### 2.2. T-966 — задача 7: статистика

- `journalctl -u admin_bot --since "2026-09-09 00:00" | grep -i "graphrag"` — сколько
  WARNING «not a JSON list» за 24/48ч, из какого пайплайна (лог-источник: direct/поиск/
  видео/веб/крон compress-purge — источники `memorize_facts` вызовов);
- raw-ответ модели НЕ реконструируем (не логировался) — ставим постоянный лог в фиксе;
- **Вывод:** паттерн ответа (проза/пусто/массив строк/объект) ИЛИ вердикт
  «промпт-дрейф, нужен постоянный лог raw».

## 3. Фикс-дизайн задачи 5 (по итогам T-965; диагностика — обязательный минимум, смягчение — по канону)

### 3.1. Диагностические логи бюджет-пути (обязательно; HIGH-004 частично)

- `NoApiKeyForChat` (llm_client.py:122-132): аддитивный kwarg
  `details: dict | None = None` (дефолт None — существующие конструкторы/тесты
  `test_chat_keys.py:157-183` не ломаются; в `__init__` после `reason`).
- В `_resolve_api_key_and_source`: в ветке budget (:347-348), ДО `raise`, собрать
  снапшот (без секретов — R17: requests/tokens/day НЕ секреты):
  ```
  details = {
    "resolve_path": "budget",
    "day": str(chat_usage.today()),
    "used_calls": int(used.get(METRIC_CALLS, 0)),
    "limit_calls": chat_usage-лимит запросов (через существующий хелпер _budget_limit_requests),
    "used_tokens": int(used.get(METRIC_TOKENS, 0)),
    "limit_tokens": chat_usage-лимит токенов,
    "allow_global": bool(root.get("keys", {}).get("allow_global", True)),
  }
  ```
  (для ветки forbidden — `{"resolve_path": "forbidden", "allow_global": False}`).
- `direct_chat_service.py:547-549`: WARNING → `"[direct] no key — sandbox answer | chat=%s | reason=%s | details=%s"` —
  `details` = repr(details) (одна строка, без traceback; exc_info НЕ нужен).
- Убедиться: grep-проверка, что в логах нет значений ключей (R17); README-пометка
  о приблизительности счётчика (существует) — не трогается.

### 3.2. Смягчение — BYOK-фоллбэк (канон порядка)

Строгий порядок резолва (без нарушения R17/S1-S3-фиксов раунда 10):
**свой → глобал-бюджет → свой-фоллбэк → sandbox**.

- В `_resolve_api_key_and_source`, ветка budget: ПЕРЕД `raise NoApiKeyForChat("budget")` —
  **повторная** проверка `chat_keys.get_chat_key(self._pg(), chat_id, "keys.llm_api_key")`
  (дешёвый re-read: покрывает гонку/персист, когда ключ добавлен между шагом 1 и 3;
  гипотеза (в)); найдено → `return own, "chat"` (бюджет НЕ тратится);
  нет → `raise NoApiKeyForChat(chat_id, "budget", details=details)`.
- Шаги 1/2/4 — БЕЗ изменений; fail-open (PG/кэш недоступен → global) — БЕЗ изменений.
- Если T-965 покажет «лимиты ужаты» — операционная правка лимитов в TMA (hot config),
  код не меняется; если «счёт накоплен» — тот же вывод (лимит по дефолту 25/100k —
  поведение НЕ меняется).
- Рассматривалось, отклонено: ретрай/повторная попытка использования глобального ключа
  после budget (обход бюджета — запрещён семантикой F-7); ESM-подсказка в логе —
  не вводится (лог уже несёт used/limit; наглядность — в TMA); отчёт юзеру —
  вне скоупа (нет канала в этой фиче).

### 3.3. Критерии приёмки (T-969)

- WARNING «[direct] no key — sandbox answer» теперь содержит reason + details
  (used/limit/day/resolve_path) без секретов (grep: «api key value»-паттернов нет);
- unit-тест: бюджет-исчерпан + при этом есть свой ключ → «повторное» чтение нашло
  ключ → source 'chat' (ответ НЕ sandbox);
- unit-тест: бюджет-исчерпан и ключа нет → NoApiKeyForChat('budget', details…) —
  `details["used_calls"]`/`details["limit_calls"]` актуальны;
- sandbox — только после всех фоллбэков (порядок строго);
- поведение при дефолтных лимитах (25/100k) не изменилось (существующие тесты
  `test_chat_keys.py` — зелёные);
- fail-open при PG down — как раньше (глобальный ключ, бот жив).

## 4. Фикс-дизайн задачи 7 (по итогам T-966)

### 4.1. Не тихий WARNING: лог raw-фрагмента (обязательно; R17)

- В `parse_fact_list` ветка :408: WARNING → `"graphrag memorize: LLM answer is not a
  JSON list — skipped | raw=%s"` с `_mask_llm_raw(raw)`:
  - `_mask_llm_raw(raw)` — новый маленький хелпер в summary_memory.py: `str(raw)[:500]`
    + маска известных секрет-паттернов (`sk-…`, `Bearer …`, `ghp_…`, `api_key=[^&\s]+`,
    длинные hex-последовательности ≥ 40 симв.); на выходе — компактная строка
    (repr-обрезка, пробелы схлопнуты);
  - цифры-идентификаторы НЕ маскируются (uid/chat_id в фактах — не секреты; маска
    цифр уничтожила бы диагностику);
  - НЕ логировать полный чат-диалог: только ответ модели (raw — выход LLM-экстрактора);
  - не обязателен вызов log_ring.sanitize вручную (логгер-уровень уже маскирует в
    BetterStackHandler; journald получает готовый текст).
- Фраза «not a JSON list» СОХРАНЯЕТСЯ (тесты :604, :621 — substring-совместимы).
- Инфо-лог :1456-1458 («0 facts») — оставить (не дублирует WARNING).

### 4.2. Fallback-парсер (толерантность к прозе/буллетам)

- Новая чистая функция `_fallback_parse_facts(raw: str) -> list[dict]` (summary_memory.py)
  рядом с `parse_fact_list`:
  1) **массив в тексте**: поиск подстрок `[`…`]` (рекурсивно/итеративно с расширением
     границы, bounded ≤ 20 попыток), `json.loads` пробует расширяющиеся кандидаты до
     успеха (первый валидный массив);
  2) **построчные тройки**: для каждой строки, отделённой `\n`/`;`:
     - `split` по `;` или `,` → ровно 3 части → strip кавычек/пробелов → dict
       `{subject, predicate, object}`;
     - либо регекс-паттерн `“…”…“…”…“…”`-транскрипта (ёлочки «» И обычные кавычки
       " ' — толерантность к канон-запрету гипотезы (г)); упрощённая форма:
       построчные пары `subject — predicate — object` (тире — отдельный пункт, НЕ путать
       с `→`);
  3) каждый кандидат → `_validate_fact` (уже фильтрует мусор: капсы/длины/context cap);
  4) результат → до `limits.graph_extract_max_triplets` (как :416); НИКОГДА не бросает.
- Порядок в `_memorize_facts_inner`: `facts = parse_fact_list(raw)`; если пусто —
  `facts = _fallback_parse_facts(raw)`.

### 4.3. 1 ретрай с жёстким промптом (только fire-and-forget ветка)

- В `_memorize_facts_inner` ПОСЛЕ fallback-парсера, при пустом результате: ОДИН
  дополнительный LLM-вызов `self.llm.generate([{"role":"system","content":
  _FACT_RETRY_SYSTEM_PROMPT}, {"role":"user","content": tail}])`:
  - `_FACT_RETRY_SYSTEM_PROMPT` — КОД-константа в summary_memory.py (НЕ канон, НЕ PG,
    НЕ REGISTRY — прецедент Q10 dream/nostalgia-промптов; каноны `plans/docs/canon/`
    и `prompts.extract_system_prompt` НЕ изменяются);
  - содержание (утверждает @Architect): «Верни СТРОГО один JSON-массив объектов
    {"subject": …, "predicate": …, "object": …}. Никакого текста, пояснений, списков,
    кавычек-елочек и длинных тире. Нечего запомнить — верни []» (короткий, жёсткий,
    без формата маркдауна);
  - результат второго вызова → `parse_fact_list` → fallback-парсер; всё пусто →
    WARNING с raw-фрагментом первого ответа + `[retry] second attempt also failed`
    (инфо/дебаг), `[]`;
  - retry обрабатывает только LLMError как и `_extract_facts` (bounded 1; исключение →
    WARNING-лог как сейчас, факты не пишутся);
- НЕ ретраится: `_extract_and_save_graph` (крон compress/purge, :2246/:2325) —
    остаётся прежним (ретрай только в memorize-ветке; канон «деградация без потерь —
    ретрай только в fire-and-forget-ветке, НЕ в основном ответе бота»);
- `memorize_facts`-контракт (R46-2, FACT_EXTRACT_PROMPT :83 байт-в-байт) — БЕЗ изменений.

### 4.4. Критерии приёмки (T-970)

- WARNING «not a JSON list» — больше НЕ тихий: содержит raw-фрагмент (test: caplog —
  фрагмент есть, секрет-паттерн замаскирован);
- проза/буллеты/«массив строк»/объект-со-списком/«строка с [] внутри» → fallback-парсер
  извлекает факты (тест на каждую форму);
- пустой результат → 1 ретрай: mock LLM «мусор → корректный JSON» → факты записаны
  (тест); «мусор → мусор» → WARNING + [] (тест), фактов 0;
- ответ бота НЕ затронут (memorize — fire-and-forget; generate_and_send без дифов);
- `parse_fact_list` НЕ бросает (существующие тесты :596-624 зелёные);
- каноны промптов/доков — без дифов (grep `docs/canon`-файлов).

## 5. Тесты (T-971)

- `test_graphrag_memory.py` (+): parse_fact_list — проза/буллеты/одиночная строка/
  кривой JSON/массив строк/объект-со-списком/кривой элемент/ёлочки-и-тире;
  `_fallback_parse_facts` — все формы; ретрай-паттерн (mock LLM: мусор → корректный
  JSON; мусор → мусор); секрет-маска raw-фрагмента; WARNING-содержание;
- `test_chat_keys.py` / `test_llm_client.py` (+): `_resolve_api_key_and_source`
  (бюджет-исчерпан + свой ключ (повторное чтение) → source 'chat'; бюджет + нет ключа →
  NoApiKeyForChat('budget') с details; details без секретов);
- `test_direct_chat.py` (+): WARNING «no key — sandbox answer» содержит details
  (капкап-проверка форматной строки; ручная проверка mask);
- маркер-тесты: если старые фиксируют старый формат WARNING (текст) — обновить
  (substring «no key — sandbox answer» сохраняется; добавление деталей — поддержка);
- полный pytest 0 failed (4760 + ~8-15 новых); `git diff --check` чист.

## 6. Границы (НЕ трогать)

- Порядок роутеров bot.py + гейт `flags.summary_enabled` (613-643) — без дифов;
- Сигнатуры публичных функций (llm_client/direct_chat_service/summary_memory) —
  только аддитивные/точечные (NoApiKeyForChat.details — kwarg с дефолтом; новые
  хелперы — приватные; MED-015: монолит НЕ рефакторим);
- Каноны промптов (plans/docs/canon/) и `prompts.extract_system_prompt` — НЕ меняются
  (ретрай — код-уровень `_FACT_RETRY_SYSTEM_PROMPT`, одобрен @Architect в §4.3);
- SQLite-схема — без миграций; `hot.get`-путь — без изменений интерфейса;
- R17: реальные ключи/токены — никогда в логи/планы/commit (grep `api[_-]?key|token|
  secret|password` перед коммитом);
- F-5 config-read-path-audit: новые hot.get-чтения (если появятся) — в стиле каталога;
  включить в остаточный аудит (MED-003);
- лимиты `limits.chat_global_key_budget_*` — дефолты 25/100k НЕ меняются (операционная
  правка на проде — через TMA/hot config, не код);
- scanner: HIGH-004 — в этой фиче только диагностика конкретного budget-пути и
  raw-memorize (полный LLM request/response-лог — вне 10.3, кандидат в следующий раунд).

## 7. Финальная фаза (T-972/T-973 — по схеме T-941…T-944, после T-971)

- T-972: полный pytest (≤300с) 0 failed; README — ироничный абзац (бюджет/песочница,
  «бот взял себя в руки» — прецедент хотфикса 10.1) + счётчик тестов; коммит master
  (русский conventional; grep секретов R17; `git diff --check`);
- T-973: деплой (ssh nik@198.46.175.136, fail2ban maxretry=3; пароль — интерактивно/
  sshpass, в планы не писать R17), `git pull --ff-only`, `systemctl restart admin_bot`,
  status active, journal чист; live: ответ бота в -1002661910336 без «no key»-WARNING
  при живом балансе; `GET /api/config/keys/status` показывает счётчик; массовых
  «graphrag»-WARNING нет (сверка с T-966-статистикой).

## 8. Что требует проверки на проде (для задачи 5 — сводка)

1. Фактические `limits.chat_global_key_budget_requests/tokens` в bot_settings (ужаты ли);
2. `chat_usage` за 09.09.2026 и соседние дни (used_calls/used_tokens/day;
   совпадение day с TZ Екб; собирается ли счёт по всем пайплайнам чата);
3. Наличие собственного ключа у -1002661910336 (chat_keys — факт, last4);
4. `chat_params.keys.allow_global` этого чата;
5. журнал: точное время WARNING, рестарты (uptime_events), смена дня между WARNING
   и следующим ответом («минуту спустя») — объяснение;
6. `GET /api/config/keys/status` на проде (счётчик vs лимиты — в TMA «Доступы и Роли»).
