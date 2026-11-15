# Slice D probe harness (read-only)

Три скрипта, которыми снята матрица `corpus-run-slice-d-2026-11-15.json`
(до — база `2b419aa2`, после — кандидат `ef568e6f`), инвентарь векторной ноги
`vector-leg-inventory-2026-11-15.json` и проба L1 `l1-measure-2026-11-15.json`.
Прогон только читает; копия БД — не живой файл.

```powershell
# 1) копия снапшота прод-БД (sqlite3 .backup с read-only соединения)
# 2) переменные окружения
$env:VMQ_CLONE = "<worktree кандидата или базы>"
$env:VMQ_DB    = "<путь к dbcopy.db>"
$env:PROBE_OUT = "<куда писать JSON>"
python measure.py            # A1/A1P/D/T2/T3 (auto и historical), Old_Episode,
                             # профиль (auto/historical), tool-биография,
                             # product_trace (`_build_rag_block`)
python vector_inventory.py   # TIME-06: таблицы/счётчики/допуск/причина отказа
python l1_measure.py         # L1 memory_scope/response_act на 5 запросах
                             # (в этой среде ключ LLM пуст: LLMTransportError)
```

`measure.py` вызывает реальные швы продукта (`_rag_unified_rows`,
`_build_rag_block`, `_build_old_episodes`, `DatabaseService.get_*`), подменяя
только LLM-клиент (embed/generate → отказ) и кэш настроек (пустой → settings
defaults). `memory_scope` передаётся явно, чтобы измерить обе ветки авторитета;
какой scope выдаёт живой L1 — в этой среде не измерить (см.
`l1-measure-2026-11-15.json`). Наружу пишутся только id/годы/коды
причин/счётчики; тексты фактов и сообщений не сохраняются.

Конфигурация прогона: Python 3.12, `sqlite-vec` загружен, `graph_rag_enabled=true`,
`graph_rag_facts_limit=10`, модель эмбеддингов `gemini-embedding-001` (3072),
векторная нога в обоих вариантах `compat_not_proven` (`vector_rows=0`).
