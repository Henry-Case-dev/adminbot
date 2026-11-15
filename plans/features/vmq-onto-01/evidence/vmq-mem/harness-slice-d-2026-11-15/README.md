# Slice D probe harness (read-only)

Два скрипта, которыми снята матрица `corpus-run-slice-d-2026-11-15.json` и
`vector-leg-inventory-2026-11-15.json`. Прогон только читает; копия БД — не
живой файл.

```powershell
# 1) копия снапшота прод-БД (sqlite3 .backup с read-only соединения)
# 2) переменные окружения
$env:VMQ_CLONE = "<worktree кандидата или базы>"
$env:VMQ_DB    = "<путь к dbcopy.db>"
$env:PROBE_OUT = "<куда писать JSON>"
python measure.py            # классы A1/A1P/D/T2/T3, Old_Episode, профиль, вектор,
                             # D3 tool-биография, D5 product_trace
python probe_current_state.py  # D1: current-state вопросы под auto
python vector_inventory.py   # TIME-06: таблицы/счётчики/допуск/причина отказа
```

`measure.py` вызывает реальные швы продукта (`_rag_unified_rows`,
`_build_old_episodes`, `DatabaseService.get_*`), подменяя только LLM-клиент
(embed/generate → отказ) и кэш настроек (пустой → settings defaults). Наружу
пишутся только id/годы/коды причин/счётчики; тексты фактов и сообщений не
сохраняются.

Конфигурация прогона: Python 3.12, `sqlite-vec` загружен, `graph_rag_enabled=true`,
`graph_rag_facts_limit=10`, модель эмбеддингов `gemini-embedding-001` (3072),
векторная нога в обоих вариантах `compat_not_proven` (`vector_rows=0`).
