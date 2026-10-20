# CFG-06 W1 — широкий чат-контекст: что сделано (лейн CFG-06-W0W1)

Дата: 20.10.2026. База: deployed `29cc49ba` (продуктовые файлы байт-идентичны).
КОММИТ НЕ СОЗДАВАЛСЯ (коммитит оркестратор). Состав диффа лейна:

| Файл | Тип | Суть |
|---|---|---|
| `services/factcheck_context.py` | НОВЫЙ | сборщик широкого окна 200–500 (адаптивный бюджет), ConversationContext с якорями, двухуровневый рендер, дедуп, кеш среза, select_verbatim |
| `handlers/factcheck.py` | правка | `_fetch_chat_context`: +kwarg `claim_text`, широкий срез строго за гейтом (default OFF), fail-open в узкое окно; оба call-site (temporal L151+, legacy L449+) передают `claim_text=target_text` |
| `services/smart_cache.py` | правка | slug `factcheck_wide_context` в `_NORMALIZERS` (прецедент `factcheck_temporal`; без слага `build_key` ValueError) |
| `config/settings.py` | правка | `FACTCHECK_WIDE_CONTEXT_ENABLED` (env, default **False**) |
| `tests/test_factcheck_context_cfg06.py` | НОВЫЙ | 11 CONTRACT-тестов (TEST-LIFECYCLE: CONTRACT owner=CFG-06) |

## Контракт флага отката

- Приоритет: hot `flags.factcheck_wide_context` (откат без рестарта, паттерн CFG-01) → env `FACTCHECK_WIDE_CONTEXT_ENABLED` → **False**.
- **OFF (default)** → `_fetch_chat_context` байт-в-байт прежнего пути (тест `test_flag_off_byte_parity_with_old_path`). Прод-контур не меняется до W3.
- **ON** → успешный широкий фид заменяет окно; пустой срез/ошибка → fail-open в узкое окно (прежнее поведение).

## Реализация по пунктам 06I

- 06I.1/06I.5: `ConversationContext`/`ContextMessage` — стабильные опоры message_id/tg_message_id/chat_id/author/timestamp/reply_to/forward в каждой строке; канонический рендер `format_context_item` («нет голого текста»).
- 06I.2: `resolve_window` — per-chat `limits.factcheck_wide_context_messages` (chat_params → hot → 300, потолок 500; 85/15 до/после цели); защитный keep-end-кап 500 с гарантированным якорем.
- 06I.3: два уровня — компакт-хронология (обрезка строк 120 симв., бюджет 8000) + дословные фрагменты выбранных сообщений (600 симв./сообщение, ≤40 сообщений, бюджет 12000); секции маркированы exempt-метками «фон: …» (существующий allowlist `CONTEXT_LABEL_EXEMPT_PREFIXES`, новых структурных тегов не вводили).
- 06I.4: дословный выбор детерминированный: якорь/триггер всегда; прямые ответы на них; лексическая релевантность клейму (≥2 общих токена ≥4 симв. или редкий термин ≥5 симв. с df≤2); замыкание ответов 1 хоп.
- 06I.8: чужие чаты не читаются (все запросы строго chat_id + фильтр в глубину); пустой срез → '' (деградация = прежнее поведение); приватное наружу не уходит (фид едет только в user-content, как и раньше).
- 06I.9: reuse только существующих DB-доступов (`get_messages_around`, `get_recent_messages(1)` для newest-инвалидатора); кеш slug `factcheck_wide_context` с версией `fcx1`/диапазоном окна/newest_id в компонентах ключа, TTL hot `limits.factcheck_wide_context_cache_ttl` (default 120 с); новые сообщения → честный miss.

## Осознанные отклонения от списка скоупа брифа (минимальная проводка)

1. `services/chat_context.py` НЕ тронут — широкому сборщику нечего аддитивно добавлять в узкий модуль (общее — только канон `canonical_context`, который переиспользован напрямую). Правка была бы мёртвым кодом.
2. `services/temporal_factcheck.py` (envelope-поле `context_slice`) НЕ тронут — поле без потребителя (gate W2 ещё не существует) создавало бы лишний шов до фриза схем W3; будет добавлено в W2/W3 при появлении потребителя.

## RED→GREEN и прогон

См. `w1-red-green.txt`: RED = ImportError коллекции без нового модуля; GREEN = 11 passed; затронутые сьюты (factcheck handlers/deep-context/unified-core route-coverage 18 CONTRACT/service) = 130 passed; settings+smart_cache = passed. Известные 2 pre-existing v35 фейла `test_asap7_direct_settings` воспроизведены на чистом HEAD (stash-прогон) — вне диффа.

## Что дальше (W2)

- suitability gate (`services/factcheck_suitability.py`) потребляет `ConversationContext` (Target + контекст, needs_context вместо уверенного отказа);
- ContextualClaimResolution (06I.6) поверх контекста;
- включение флага и расширение окна до прода — этап W3.
