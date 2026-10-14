# Раунд 10.4 — отчёт ревью-фиксов (T-вёрстка: fix-раунд после Needs Fixes)

> @Builder, после вердикта @Reviewer «Needs Fixes» (критично: select-виджет
> B, кросс-чатовая запись F; средние: advanced-аккордеон F, автозагрузка F,
> 3 «мёртвых» override G; minor: тексты A, ограничение B-13).
> Все исправления: `web/api/routes.py`, `web/app.js`, `web/index.html`,
> `services/direct_chat_service.py`, `services/param_catalog.py`,
> `services/user_relations.py`, `tests/*` (см. ниже).

## 1. Реестр read-путей (AC-B4, для F-5-аудита)

| Файл:место | Ключ | Тип чтения | Введено |
|---|---|---|---|
| `direct_chat_service.py` саller `_apply_context_budget` | `flags.chat_context_budgets_enabled` | `get_chat_param` (async) | B-2 |
| `direct_chat_service.py` саller `_apply_context_budget` | `limits.chat_context_budget_tokens` | `get_chat_param` (async, ревью-фикс) | G |
| `direct_chat_service.py` `_active_participants` | `limits.chat_map_participants_hours/cap` | `get_chat_param` | G |
| `direct_chat_service.py` `_build_global_context` | `limits.chat_global_context_limit/max_tokens/max_chars`, `limits.chat_level2_max_chars` | `get_chat_param` | G |
| `direct_chat_service.py` `_collect_thread_chain` | `limits.chat_thread_max_depth` | `get_chat_param` | G |
| `direct_chat_service.py` `_thread_limit` (новий хелпер) | `limits.chat_thread_max_tokens/max_chars` | `get_chat_param` (ревью-фикс) | G |
| `summary_generator.py` | `limits.summary_rag_l2_limit`, `limits.summary_max_context_tokens/chars` | `get_chat_param` | G |
| `summary_memory.py` `get_window_messages` | `limits.summary_max_window_messages` | `get_chat_param` | G |
| `summary_memory.py` `get_rag_context` | `limits.graph_rag_facts_limit/context_max_chars` | `get_chat_param` | G |
| `summary_memory.py` `compress_and_purge`/`_compress_purge_extract_only`/`_purge_archive` | `full/archive_memory_retention_days`, `summary_compress_batch` | `get_chat_param` (chat_id в скоупе цикла — G-4) | G |
| `summary_memory.py` memorize | `limits.graph_edge_weight_increment` | `get_chat_param` (значение НЕ менялось) | G |
| `summary_memory.py` | `flags.chat_running_summary_enabled` (через `chat_summary_enabled`) | per-chat (F-14) | F-14 |
| `web/api/chat_lore.py` list_relations | `limits.summary_aliases` | `build_alias_resolver(chat_id)` | B-13 |
| `scripts/backfill_104_*.py` | per-chat overrides | `set_chat_params` (write) | B-4/G-5 |

## 2. G-отчёт (AC-G5/G6, KPI, деплой/откат)

- **KPI-влияние (25 req/сутки, глобальный ключ)**: ×1.5–×2-контекст
  увеличивает токены на запрос; пер-чат флаг `flags.chat_context_budgets_enabled=false`
  (backfill_104_chat_flags) выключает партишинг → контекст без обрезок
  (осознанный выбор владельца; восстановление — 1 клик: удалить override).
  Наблюдаемость: F-15 details (used/limit/day) + worker_budget; при исчерпании
  25 req/сутки — sandbox R16 (то, что и было до фичи).
- **Решение G-6 (ЛС)**: override для ЛС-профиля владельца НЕ создаётся
  (у -1002661910336 один групп-чат; ЛС-настройки — механика F-14).
- **Деплой/откат**:
  - Применить: `python scripts/backfill_104_chat_flags.py` затем
    `python scripts/backfill_104_overrides.py` (оба идемпотентны; `--dry-run`
    для предпросмотра); после — `systemctl restart admin_bot` (не требуется
    для кэша 120с, но желательно для чистоты журнала).
  - Откат: удалить overrides чата -1002661910336 (одна команда в TMA/
    psql: `UPDATE chat_profiles SET chat_params = chat_params #- '{overrides}' WHERE chat_id = -1002661910336;`
    — канон JSONB; или штатный UI «↪ глобальное» по ключу).
- **Ремедиация G item 5**: 3 «мёртвых» override ПЕРЕВЕДЕНЫ на per-chat чтение
  (budget-база через параметр `budget_tokens` в `_apply_context_budget`;
  `limits.chat_level2_max_chars` — `_cp_g` в `_build_global_context`;
  thread-токены/чары — новый async-хелпер `_thread_limit(chat_id)` +
  параметр `thread_limit` у `_render_thread`) — таблица значений бэкфила
  соответствует фактическому поведению.

## 3. H-рекон (кейс → причина → фикс, AC-N1/N2)

| Кейс (участник без имени) | Причина | Фикс |
|---|---|---|
| Вне окна 30д/top-200 nickname и вне топ-50 username | username-обогащение только топ-50 (`_RELATIONS_ENRICH_TOP`) | **H-2**: username — ВСЕМ строкам (Semaphore(5), кэш 1ч, fail-open None) |
| Nickname есть, но username пуст | каскад останавливается на nickname | каскад без изменений (alias → nickname → username → '') |
| Alias-путь пустой | глобальные алиасы не учитывают per-chat | **B-13/H**: `build_alias_resolver(chat_id)` (override → глобальные) |
| `_display_name` → str(uid) | дефект исключён в 10.2 (owner-реквизит :220-221) | H-4: отчёт — дефектов НЕТ; R16-страховка остаётся |

## 4. Документированные отклонения (финальный перечень)

1. **B-13 points 2-4**: per-chat алиасы НЕ доходят до инжекта
   `<user_relations>` (RelationsService/`_display_name` используют глобальные
   алиасы из bot.py:322; точка 1 — TMA-каскад list_relations — работает
   per-chat). Зафиксировано комментарием в `user_relations.py`.
2. **G-4-граница**: `summary_xml.py`-рендер и `_participant_roster` (витрина
   карты) остаются глобальными (синхронные функции без chat_id в скоупе;
   риск «ретенция/окно не расширяются в этих путях» — KPI-наблюдение).
   R10.4-7: граница сканер-доработки — direct RAG-cap / get_rag_facts:
   per-chat для `get_rag_context` (graphrag) переведено; пайплайн
   direct-контекста с собственным лимитом RAG-фактов читает глобальные
   значения (hot.get) — вне per-chat-таблицы G (кандидат F-5-аудита).
3. **B-1-исключение инварианта префикса** групп каталога:
   `flags.chat_context_budgets_enabled` в группе `limits_chat_budgets`
   (рендер-блок «Прямой чат: бюджеты токенов»; категория/per_chat не менялись).
4. **D-AC-B1** был красным между D и C (ожидаемо; финально зелёный).

## 5. Ревью-фиксы: статус по пунктам

| # | Пункт | Статус |
|---|-------|--------|
| 1 | select-сериализация GET + тесты (200/422/маркер) | ✅ |
| 2 | кросс-чатовая запись F (onLoreTab-приоритет + сброс профиля в setTab) | ✅ |
| 3 | advanced-аккордеон «Настройки отношений» (D-канон) | ✅ |
| 4 | автозагрузка участников при setTab('relations') | ✅ |
| 5 | 3 «мёртвых» override → per-chat чтение (предпочтительный вариант) | ✅ |
| 6 | тексты «Модули и Фичи»/«Память и RAG» в пользовательских описаниях | ✅ |
| 7 | B-13 points 2-4 — зафиксировано (не реализуется в раунде) | ✅ |
| 8 | этот отчёт | ✅ |
