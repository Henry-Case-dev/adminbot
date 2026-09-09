# Задачи: backend-chat-1002661910336-scaling (ТЗ 8 раунда 10.4)

Раунд 10.4, фича G (T-1045…T-1056). Стадия старта — PLANNED; spec.md @Architect.
ТЗ владельца (п.8): расширить для чата **-1002661910336** лимиты
контекста/саммари/памяти — через per-chat override (per_chat=True) и/или
профиль ЛС (если уместно); **НЕ трогать дефолты глобальных лимитов для других
чатов.**

Отправная точка (рекон tma-structure-10.4 + recon: direct-chat-sandbox-budget,
HEAD 1410a68):
- Per-chat слой: `chat_params` (overrides JSONB) + `hot_chat`-кэш
  (services/chat_params.py:200-346) + `get_chat_param_defaulted(chat_id, key,
  fallback)` (:349-372 — override → каст normalize_value; иначе fallback).
- Кандидаты (ВСЕ — категория limits → per_chat=True; ключи/каталог проверены
  в param_catalog.py:667-812, точные pg-ключи и группы):
  * контекст: `limits.chat_context_budget_tokens` (limits_chat_budgets),
    `limits.chat_global_context_max_tokens` (limits_chat),
    `limits.chat_thread_max_tokens` (limits_chat),
    `limits.chat_global_context_limit` (limits_chat),
    `limits.chat_global_context_max_chars` (limits_chat),
    `limits.chat_level2_max_chars` (limits_chat),
    `limits.chat_map_participants_hours` / `limits.chat_map_participants_cap`
    (limits_chat);
  * саммари: `limits.summary_max_context_tokens` / `limits.summary_max_context_chars`
    (limits_summary), `limits.summary_max_window_messages` (limits_memory),
    `limits.summary_rag_l2_limit` (limits_graph), `limits.summary_compress_batch`
    (limits_summary);
  * память: `limits.full_memory_retention_days` / `limits.archive_memory_retention_days`
    (limits_memory), `limits.graph_rag_facts_limit` /
    `limits.graph_rag_context_max_chars` / `limits.graph_edge_weight_increment`
    (limits_graph).
- ТОЧКИ ЧТЕНИЯ (сейчас hot.get-путь/глобальные):
  * direct_chat_service.py:996-1014 (доли бюджета + гейт), :1498-1522
    (карта участников), :1622 (RAG-контекст), :1684-1880 (контекст/тред),
    :1726 (L2-кап);
  * summary_generator.py:133-169 (L2-RAG-лимит + SUMMARY_MAX_CONTEXT_TOKENS/CHARS);
  * summary_xml.py:63-68 (window_messages/context_chars);
  * summary_memory.py:1283-1290 (окно L1), :1966-2004 (graph_rag_*),
    :2406-2483 (полная ретенция + compress_batch), :2572 (edge weight),
    :2614 (archive retention).
- У чата НЕТ BYOK-ключа (F-15): глобальный ключ 25 req/сутки — расширение окон
  увеличит расход токенов на общем бюджете → в отчёте фичи G и в spec указать
  KPI-наблюдение (F-15 details-снапшот уже логирует used/limit); связать с
  фичей B (флаг бюджетов per-чат — для -1002661910336 ВЫКЛ по ТЗ 3).
- RUNTIME WARNING раунда: SQLite v8 без дифов; каноны промптов без дифов;
  REGISTRY 383/71/359 без изменений; порядок роутеров bot.py без дифов.

## A. Read-слой per-chat [@Architect/@Builder]

- [ ] T-1045 — дизайн резолва: единый хелпер `chat_param(chat_id, key, default)`
  в services/chat_params.py: вариант (а) синхронно-блочный — НЕЛЬЗЯ (вызовы
  async); вариант (б) async `get_chat_param(chat_id, key, default)` —
  override → значение; нет → `hot.get(key, default)` (байт-в-байт старое);
  вариант (в) — overrides вообще пусты (нет профиля чата) → без кода резолва
  (быстрый путь). **AC-G1:** поведение для чатов БЕЗ override совпадает с
  текущим hot.get (тест: значение глобального кэша); для override —
  берётся override; кэш hot_chat (TTL 120с) — как в F-7 (NOTIFY/409-не меняем).
- [ ] T-1046 — контекст (direct_chat): перевести точки :996-1014/:1498-1522/
  :1622/:1684-1880/:1726 на `get_chat_param` (chat_id в скоупе) с фолбэком
  `hot.get(key, settings.X)` — сигнатуры/публичные API без изменений.
  **AC-G2:** юнит-тесты: без override — значения как сейчас (детерм.);
  с override (limits.chat_context_budget_tokens=… увеличенное) — срабатывает;
  сторона других ключей (limits.chat_thread_max_depth и пр.) не смещена
  (точечный дифф — только перечисленные).
- [ ] T-1047 — саммари (summary_generator/summary_xml/summary_memory): перевести
  перечисленные точки на per-chat резолв. **AC-G3:** (1) L1-окно
  (summary_max_window_messages) per-chat; (2) L2-RAG per-chat; (3) ретенция
  (full/archive) per-chat — ВНИМАНИЕ: cleanup-задачи (крон) — chat_id внутри
  контекста цикла (проверить: крон-очередь вызывает per-chat? — если крон
  глобальный, для per-chat ретенции нужен вызов с chat_id из контекста;
  решение @Architect: для per-chat ретенции — резолв в цикле катронов
  по каждому чату; глобальные лимиты крона остаются как есть).
- [ ] T-1048 — безопасность/пределы: override-значения кастуются
  (normalize_value); мусор → fallback (уже в get_chat_param_defaulted —
  переиспользовать). **AC-G4:** тест «мусорный override → fallback»; отсутствие
  NaN/inf (см. T-654 F-1 — учесть: каст float проверить _cast_type_ok).
- [ ] T-1049 — KPI-риски: зафиксировать в spec/summary отчёта влияние на
  глобальный бюджет (25 req/сутки): оценка роста токенов/вызовов и метрика
  наблюдения (F-15 WARNING details уже даёт used/limit — CRITICAL
  наблюдаемость!). **AC-G5:** в spec-раздел «Влияние на глобальный ключ» +
  отчёт фичи: сколько доп. токенов в среднем/запрос ожидается (анализ).

## B. Overrides для -1002661910336 [@Builder]

- [ ] T-1050 — набор значений override: (1) определить целевые значения для
  чата (множители/конкретика — решение @Architect: например контекстная
  база ×1.5-2, саммари ×2, ретенция ×30/×60 с оговоркой диска/RAM прода;
  значения — параметризованы в скрипте, перечислить в AC-таблице);
  (2) записать в `chat_params.overrides` чата -1002661910336 через
  существующий патч-путь (ensure_scope_profile + set_chat_params/патч F-7;
  updated_at/NOTIFY — как в F-7). **AC-G6:** скрипт идемпотентен; значения
  только для этого chat_id; в отчёте — таблица «ключ → значение → обоснование».
- [ ] T-1051 — «профиль ЛС» — если уместно: оценить и зафиксировать, нужен ли
  override для ЛС владельца (по ТЗ «и/или профиль ЛС» — решение: НЕ нужен,
  групп-чат один; DM-скоуп — DEFAULTS не трогаем; если решено — документировать
  в spec). **AC-G7:** явное решение в spec (да/нет + обоснование).
- [ ] T-1052 — деплой-шаг: место в RUNBOOK (@DevOps): PG-путь доступа —
  chat_params обновляются только через put/get API (никаких прямых SQL-update
  в малом, по канону DDL+NOTIFY); скрипт прогоняется на проде (стадия деплоя
  раунда; сид-скрипт vs prod SQL — выбер @DevOps по прецеденту
  backfill_feature_gates). **AC-G8:** в tasks.md/README — инструкция деплоя и
  отката (список ключей+значений; откат = удаление overrides — чисто DELETE
  в JSONB).

## C. Тесты и регресс [@Builder]

- [ ] T-1053 — юнит-тесты chat_params: `get_chat_param` (override/без/мусор/
  каст), новый хелпер; тесты точных точек (direct_chat/summary): значения
  по умолчанию («без override = как раньше» — byte-for-byte зафиксировано).
- [ ] T-1054 — тесты других чатов: значения глобальные взяли хот.кэш — НЕ
  изменены (сравнение до/после), дефолты Settings — не менялись.
- [ ] T-1055 — интеграционные: полный pytest 0 failed (baseline 4831 + новые);
  замер: тесты окон (summary_memory/direct_chat) — без регресса сроков.
- [ ] T-1056 — регресс-режим: `git diff --check` чист; проверка, что
  REGISTRY/SQLite/промпты/роутеры — без дифов; упоминание «эталон 383/71/359».

**Критерии приёмки ТЗ 8 (сводные):**
- У -1002661910336 — расширенные лимиты (override, видимые в TMA как «чат»
  badge + в hot-диагностике); у остальных чатов — УЗЕЛОВЫЕ дефолты не изменились;
- Ноль новых PG-таблиц/DDL; ноль изменений REGISTRY/Settings/SQLite;
- values-таблица в отчёте фичи; риски глобального бюджета (25 req) — описаны
  и связаны с F-15/B-фичением; деплой-инструкция и откат — в RUNBOOK.
