# Задачи: direct-sandbox-budget-investigation (F-15)

> Раунд 10.3, пункты 5 и 7 ТЗ владельца — ДВА бэкенд-расследования +
> возможные фиксы:
> - **Задача 5**: WARNING `services.direct_chat_service "[direct] no key — sandbox
>   answer | chat=-1002661910336 | reason=budget"` ПОЯВИЛСЯ ВНЕЗАПНО при наличии
>   ключа и баланса — минуту спустя бот отвечал.
> - **Задача 7**: WARNING `services.summary_memory "graphrag memorize: LLM answer
>   is not a JSON list — skipped"` — расследовать и пофиксить.
> База: HEAD `d30b203` (раунд 10.2, задеплоен), pytest 4760, прод PID 454654.
> Спецификация: `spec.md` — создаёт **@Architect** на следующем шаге (новая
> фича — КГ-канона spec нет; реконы-гипотезы @PM ниже в разделе «Рекон-база»).
> ⚠️ Прод-диагностика (T-965/T-966) — ДО проектирования фикса: сначала факты
> (root cause), потом код. Задачи T-967/T-968 — по итогам диагностики.
> Нумерация продолжает T-964 (раунд 10.3, F-13 T-925…T-944 + F-14 T-945…T-964).

## Рекон-база (@PM, гипотезы из KG сущностей `recon: direct-chat-sandbox-budget` + `recon: graphrag-memorize-json-list`)

### Задача 5 — sandbox reason=budget

- Код-путь: `direct_chat_service.py:543-553` ловит `NoApiKeyForChat`
  (llm_client.py:122) из `chat_with_tools`/`llm.generate`; исключение бросает
  `_resolve_api_key_and_source` (llm_client.py:317-356): 1) свой ключ `chat_keys`
  → source 'chat'; 2) `chat_params.keys.allow_global=false` → reason 'forbidden';
  3) `chat_usage.budget_exceeded` → reason 'budget' (llm_client.py:347-348);
  4) иначе глобальный ключ + `_record_global_usage` на КОНЦЕ вызова.
- `budget_exceeded` (chat_usage.py:100-113): лимиты
  `limits.chat_global_key_budget_requests` (дефолт 25) /
  `limits.chat_global_key_budget_tokens` (дефолт 100000); ЛЮБОЙ лимит <= 0 = ЗАПРЕТ
  (True); used из PG `chat_usage` (PK chat_id, day, metric); день =
  WORKER_BUDGET_TZ `Asia/Yekaterinburg` (chat_usage.py:25); счётчик растёт на
  КОНЦЕ каждого LLM-вызова с source='global' (1 вызов + токены len/4 — оценка).
- Гипотезы (проверить в T-965): (а) лимиты на проде ужаты через hot config
  (bot_settings); (б) chat_usage накопил счёт за день по ВСЕМ пайплайнам чата
  (не только direct) — сумма за день; (в) чат -1002661910336 использует
  глобальный ключ без своего (chat_keys пуст) и allow_global=true;
  (г) смена day/TZ — нет, день в БД (проверить фактическое значение day);
  (д) оценка токенов len/4 грубая — частые вызовы упираются в token-лимит
  раньше ожидаемого (25 вызовов/день выглядит «внезапно»).
- Fail-open: PG down/разусередину → `used_today` возвращает {} → NOT exceeded
  (бот жив). Прямые unit-тесты: tests/test_chat_keys.py:158-183 ('forbidden'/'budget').
- Прод-диагностика: `SELECT * FROM chat_usage WHERE chat_id = -1002661910336
  ORDER BY day DESC; SELECT key, value FROM bot_settings WHERE key IN
  ('limits.chat_global_key_budget_requests','limits.chat_global_key_budget_tokens');`
  + `GET /api/config/keys/status` (F-7 §6, key_status chat_usage.py:128-136).
- В TMA счётчик ВИДЕН на вкладке «Доступы и Роли»/BYOK-блок (key_status
  calls/tokens used/limit); изменение лимитов — через hot config (REGISTRY
  limits_worker/chat_global_key_budget_*).

### Задача 7 — graphrag memorize JSON list

- Код: `summary_memory.py:380-418` `parse_fact_list(raw)`: candidates = [raw] +
  [unwrapped code-fence]; json.loads; dict → берётся первое list-значение;
  не-список → WARNING «graphrag memorize: LLM answer is not a JSON list — skipped»
  (:408) + [] (ТИХО, без содержимого raw); per-item `_validate_fact`
  (subject/predicate/object — str, _normalize_name, капсы, subject != object,
  context cap).
- Вызывается из memorize-хука: `direct_chat_service.py:581-584`
  `fire_and_forget(self._memorize_direct_reply(...))` → parse_fact_list на
  LLM-ответ (факты из ответа бота). Это фоновый fire-and-forget
  (summary_memory.py:447-458) — ошибка только в логах, юзеру не падает.
- Гипотезы (проверить в T-966): (а) модель (deepseek-v4-flash через apinet,
  каскад) ответила прозой/буллетами вместо JSON-массива (промпт-дрейф/
  сменившийся fallback-провайдер); (б) ответ «ничего важного»/пусто/простая
  строка — json.loads падает; (в) вернулся массив строк или объект без
  list-значения; (г) ответ с ёлочками/длинными тире (канон-запрет раунда 5)
  или невалидной запятой — JSON ломается.
- Диагностика: сейчас raw НЕ логируется → нельзя понять, что вернула модель.
- Тесты фиксируют warning: tests/test_graphrag_memory.py:604,621.

## Прод-диагностика (ДО фикса; выполняется с доступом к прод-БД — @DevOps/@Builder с прозрачным логом; результаты фиксируются в этом файле)

- [ ] **T-965** — задача 5: собрать факты. SQL по `chat_usage` (все строки за
  09.09.2026 + соседние дни, chat_id=-1002661910336: used_requests/used_tokens/
  day/metric), `bot_settings` (лимиты + `keys.llm_api_key`-маск-факты:
  last4/source — РЕАЛЬНЫЕ значения НЕ копировать в планы, R17), `chat_keys`
  (есть ли свой ключ у чата — только факт наличия, last4), `chat_profiles`.
  chat_params.keys.allow_global. Проверка гипотез (а)–(д): точный день/лимит/
  счётчик/провайдер; сопоставить с журналом рестартов (uptime_events) и
  временем WARNING (journal: `journalctl -u admin_bot --since
  "2026-09-09 00:00" | grep -i "no key"`). Вывод: **доказанный root cause** +
  описание, почему «минуту спустя бот отвечал» (сброс дня? перезапуск? лимит
  уже превышен на ТОТ момент и снят?).
- [ ] **T-966** — задача 7: если возможно, извлечь raw-ответ модели по известному
  времени WARNING: `journalctl -u admin_bot --since "2026-09-09 00:00" | grep -i
  "graphrag"`; временный точечный лог-брейкпоинт НЕ ставим до spec — вместо
  этого статистика: сколько WARNING «not a JSON list» за 24/48ч, из какого
  пайплайна (лого-источник = direct chat/memorize/video/…) — анализ
  BetterStack/journal; вывод: **доказанный паттерн ответа модели** (проза/пусто/
  массив строк/объект) или вывод «промпт-дрейф, нужен постоянный лог raw».

## Спецификация (@Architect — по фактам T-965/T-966; варианты фиксов ниже)

- [ ] **T-967** — spec задачи 5: по root cause. Кандидаты: (1) ДИАГНОСТИЧЕСКИЕ
  логи — в WARNING «no key — sandbox» добавить used/limit/источник лимита
  (chat_usage + resolve path: свой ключ / allow_global / budget_exceeded);
  при budget_exceeded — лог `used_requests/total_requests, used_tokens/total_tokens,
  day` (БЕЗ секретов, R17; токены/запросы — не секрет); (2) СМЯГЧЕНИЕ: если у
  чата есть СВОЙ ключ (chat_keys) — при исчерпании глобального бюджет-лимита
  пробовать свой ключ (фоллбэк BYOK вместо sandbox), только потом sandbox
  (порядок строго: свой → глобал-бюджет → свой-фоллбэк → sandbox, не нарушать
  R17/S1-S3-фиксы раунда 10); (3) ESM-дистайл: если лимит 0 — WARNING-подсказка
  «установите лимит или добавьте свой ключ» одна в N+1; (4) отчёт юзеру с
  рекомендуемым значением лимита (если root cause — «мало лимита»).
  ВЫБОР фикса — по фактам T-965 (если диагностика покажет «самому лимиту
  иск}: 0 → фоллбэк-ключ обязателен, иначе тумблер юзера).
- [ ] **T-968** — spec задачи 7: (1) лог raw-ответа: WARNING + `repr(raw[:500])`
  (обрезка + маскировка ролей/повторяющихся секретов — R17; текст чата —
  осторожно: НЕ логировать полный чат-диалог, только фрагмент сырого ответа
  модели); (2) fallback-парсер: regex-построчный `"subject"…"predicate"…
  "object"` (или split по ';') до перехода в WARNING + [] — толерантность к
  прозе/буллетам; (3) 1 ретрай с ЖЁСТКИМ промптом (канон R46-2/46-4 — вернуть
  только JSON-массив) при пустом результате; деградация без потерь
  (ретрай только в fire-and-forget-ветке, НЕ в основном ответе бота).

## Реализация (@Builder — после spec.md)

- [ ] **T-969** — задача 5 фикс (по T-967): диагностический лог budget-пути
  (used/limit/источник/day в WARNING «no key») + выбранное смягчение
  (BYOK-фоллбэк и/или повтор-логика). ↓ критерии: WARNING «[direct] no key —
  sandbox answer» теперь содержит used/limit/reason-детали (запросы/токены/день)
  без секретов (grep-проверка: no api key value в логах, R17); при наличии
  chat_keys-ключа и исчерпанном глобальном бюджете — ответ отправлен СВОИМ
  ключом (unit-тест `_resolve_api_key_and_source`); sandbox — только после всех
  фоллбэков; поведение при лимитах по умолчанию (25/100k) не изменилось.
- [ ] **T-970** — задача 7 фикс (по T-968): лог raw + fallback-парсер + 1 ретрай;
  ↓ критерии: WARNING «not a JSON list» — больше НЕ тихий (raw-фрагмент в логе,
  R17); проза/буллеты/вариант «массив строк» → факты извлечены fallback-парсером
  (тест); пустой результат → 1 повтор с жёстким промптом (тест: при повторном
  корректном JSON — факты записаны; при повторном мусоре — WARNING + []).
- [ ] **T-971** — тесты: unit — parse_fact_list (проза/буллеты/одиночная строка/
  кривой JSON/массив строк/объект-со-списком/кривой элемент), fallback-парсер,
  ретрай-паттерн (mock LLM: мусор → корректный JSON), `_resolve_api_key_and_source`
  (бюджет-исчерпан + свой ключ → source 'chat'), бюджет-лог (mask-проверка);
  маркер-тесты (WARNING-текст нового формата — если старые фиксируют старый,
  обновить); ↓ критерии: полный pytest 0 failed (4760 + ~8-15 новых);
  `git diff --check` чист.

## Финальная фаза F-15 (своя, по схеме T-941…T-944; исполняется ПОСЛЕ T-971)

- [ ] **T-972** — регресс + README: полный pytest (≤300с, .venv) 0 failed; README —
  ироничный абзац (бюджет/песочница и «бот взял себя в руки»), счётчик тестов;
  коммит master русский conventional + grep секретов (R17) + `git diff --check`.
- [ ] **T-973** — деплой + live-верификация: ssh nik@198.46.175.136 (осторожно
  fail2ban maxretry=3; пароль интерактивно/sshpass — в планы НЕ писать R17),
  `git pull --ff-only`, `systemctl restart admin_bot`, status active, journal чист;
  live-проверки: нормальный ответ бота в -1002661910336 (нет «no key» WARNING
  при живом балансе), `GET /api/config/keys/status` показывает счётчик;
  WARNING «graphrag» при нормальной работе — нет массовых повторов (обновление
  статистики из T-966).

## Границы (НЕ трогать)

- Порядок роутеров bot.py + гейт `flags.summary_enabled` (613-643) — без дифов;
- Сигнатуры публичных функций (llm_client/direct_chat_service/summary_memory) —
  только аддитивные/точечные правки (MED-015: монолит НЕ рефакторим);
- Каноны промптов (plans/docs/canon/) — НЕ меняются (ретрай — код-уровень,
  жёсткий промпт-костыль — только при явном одобрении @Architect в spec);
- SQLite-схема — без миграций; `hot.get`-путь — без изменений интерфейса;
- R17: реальные ключи/токены — никогда в логи/планы/commit (grep-проверка
  `api[_-]?key|token|secret|password` перед коммитом);
- F-5 config-read-path-audit: новые hot.get-чтения (если появляются) — в стиле
  каталога; включить в остаточный аудит F-5.

## Scanner-аудит (plans/reports/full_audit_results.md) — релевантные находки

- **HIGH-004** (LLM request/response-логирование) — частично в T-969 (диагностика
  конкретного budget-пути); полный request/response-лог — вне 10.3.
- **MED-015** (direct_chat_service 800+ строк) — точечные правки только.
- **MED-016** (rule_importance magic numbers) — вне скоупа.
- **MED-003** (settings vs hot.get) — учесть стиль в новых чтениях (F-5).
