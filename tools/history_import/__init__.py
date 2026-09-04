"""Фаза 2 (эпик импорта истории, T-748) — пакет `tools/history_import/`.

Импортируется БЕЗ side-эффектов бота (никакого bot.py/памяти; stdlib +
ijson/tqdm/httpx/aiosqlite; сервисы бота подключаются точечно: config.settings
и services.database.DatabaseService — только Graph-воркером). Компоненты:

* parser.py      — потоковый разбор JSON-экспортов Telegram Desktop (ijson,
                   `messages.item`) + нормализация записи → smart_messages
                   (T-749);
* loader.py      — FTS-загрузчик: INSERT smart_messages + синхронная запись
                   smart_messages_fts по батчам, чекпоинты, VACUUM (T-750);
* checkpoints.py — аддитивная таблица import_checkpoints (прогресс `--resume`);
* prompts.py     — (часть B, T-762) канон HISTORY_EXTRACT_PROMPT +
                   JSON Schema ответа Graph-этапа + формат пачки;
* llm_worker.py  — (часть B, T-761..T-763) Graph-воркер: клиент локальной
                   Ollama (openai/ollama transport, think off), embed-клиент
                   (API), запись graph_facts (origin history_import) + FTS +
                   vec float+int8, --vec-backfill.
"""
