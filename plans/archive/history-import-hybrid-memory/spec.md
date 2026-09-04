# Спецификация: импорт истории чатов + бессрочная память (FTS5 + GraphRAG)

- Эпик: планы/features/history-import-hybrid-memory/tasks.md (T-747…T-769, фаза 2; база HEAD afe265a)
- Автор: @Architect (T-747: закрыты Q1–Q9; спецификация создана по решению раунда; дизайн-решения ниже — база для B–G)
- Дата: 05.09.2026
- Research: plans/docs/memory-import-research.md (+ данные аудита Step 0 в разделе A tasks.md)

---

## 1. Обзор

Бот имеет двухслойную память в SQLite: **L1** — `smart_messages` (сырьё всех сообщений) с FTS5-индексом; **L2/L3** — `graph_facts` (факты-триплеты, origin/weight/expires_at) с FTS5 и векторной таблицей `graph_facts_vec` (sqlite-vec, dim 3072, float + int8). Историческая переписка (4 JSON-экспорта Telegram Desktop, ~2.22M записей, ~1.08 ГБ) существует только в файлах `migrate_history/` и в память бота не попадала; цель юзера — «бот должен отвечать, что было N-числа 2024», то есть вся история чата (2022-12 … 2026) должна быть доступна и **полнотекстовому поиску (L1/FTS)**, и **графу фактов с датами (GraphRAG/vec)**.

Эпик решает это гибридным импортом в два этапа:

- **Этап FTS** (выполняется на сервере, $0): потоковый разбор экспортов → INSERT всех содержательных записей в `smart_messages` (с реальными unix-таймстампами) + синхронная запись FTS5-строк. После этапа существующий инструмент `query_chat_memory` и L2-поиск отвечают по всей истории строками `[Имя 2024-05-15]: текст`.
- **Этап Graph** (выполняется локально на ноутбуке юзера, на снапшоте прод-БД): локальная Ollama (`qwen3.5:9b`) пачками по 25 сообщений с датами/авторами извлекает **значимые факты** (новый origin `history_import`, weight 0.3, expires_at NULL — вечно, `message_timestamp` = дата сообщения-источника); факты эмбеддятся API-моделью `gemini-embedding-001` (dim 3072 — бесшовно в существующие vec0-таблицы, float+int8). Результат переносится на прод дельтой.

Параллельно вводится **тумблер `memory.infinite_retention`** (новое UI-настройка, категория `memory`): ON — сырьё и факты памяти не удаляются и не сжимаются по TTL/ретенции (кроме явных команд «забудь»/«/clear»). Тумблер включается **до** FTS-импорта: иначе summary-крон 4×/день начнёт сжимать/удалять импортированное старьё раньше, чем пройдёт Graph-этап.

Размеры контролируются (см. таблицу сценариев §2.3): цель — БД ≤ 6–8 ГБ при 14 ГБ свободного диска на сервере.

---

## 2. Требования

### 2.1 FR

- **FR-1 (FTS-этап).** CLI `python manage.py import_history --mode fts` потоково (ijson) разбирает JSON-экспорты Telegram и наполняет `smart_messages` + `smart_messages_fts` под таргет `chat_id=-1002661910336`. Пиковая RAM — десятки–сотни МБ (файлы 0.15–0.45 ГБ каждый не загружаются в память целиком).
- **FR-2 (Дедуп/идемпотентность).** Повторный запуск и обрыв+`--resume` не создают дублей: дедуп по `import_key = sha256("{timestamp}|{user_id}|{text}")[:32]` + частичный UNIQUE-индекс; пересекающиеся экспорты (31.03–10.08.2025 в `10.08.2025.json` и `2026.json`) разрешаются в пользу **свежего** файла (порядок обработки «свежий первым» + `INSERT OR IGNORE`).
- **FR-3 (Маппинг).** Записи экспорта нормализуются в схему `smart_messages` (author_name/user_id/timestamp/media_type/is_forward/forward_source; `tg_message_id` НЕ пишется — экспортные id отрицательны/коллизятся); служебные (`type != "message"`) и пустые записи без медиа отсеиваются; медиа без подписи сохраняются.
- **FR-4 (Чекпоинты).** Таблица `import_checkpoints(path, processed, total, done, updated_at)` — прогресс FTS-этапа; `--resume` продолжает с перечитыванием файла (дедуп через import_key делает повтор безопасным и быстрым), `--reset` — чистый старт.
- **FR-5 (Graph-этап).** `python manage.py import_history --mode graph` на локальной копии БД: выборка непомеченных сообщений чата (флаг `smart_messages.history_processed`), пачки по 25, LLM-экстракция фактов, запись в `graph_facts` (origin `history_import`, weight 0.3, expires_at NULL, status confirmed, `message_timestamp`) + FTS-строка + vec-строка (`graph_facts_vec`, float+int8, rowid=fact_id). Resume без дублей.
- **FR-6 (Миграция v7).** SQLite-миграция `user_version 6→7`: (а) `graph_facts.message_timestamp INTEGER` (nullable) + origin `'history_import'` в CHECK (rebuild по D201-паттерну, id сохраняются — FTS/vec валидны без пересоздания); backfill `message_timestamp = created_at`; (б) `smart_messages.import_key TEXT` + частичный UNIQUE-индекс; (в) `smart_messages.history_processed INTEGER NOT NULL DEFAULT 0` + частичный индекс; (г) частичный UNIQUE-индекс `graph_facts (chat_id, fact, message_timestamp) WHERE origin='history_import'` — идемпотентность Graph-этапа и переноса дельты на прод.
- **FR-7 (Тумблер).** Параметр `memory.infinite_retention` (bool, дефолт False) в админке (вкладка «Память и RAG», категория `memory`). ON: все TTL/retention-очистки памяти пропускаются, сырьё не сжимается/не удаляется, граф пополняется extract-only веткой; OFF — поведение ровно текущее. Явные «забудь»/«/clear» работают всегда.
- **FR-8 (Даты в RAG).** Рендер даты фактов — `COALESCE(message_timestamp, created_at)` во всех точках GraphRAG-контекста: импортированные факты показываются с датой сообщения-источника (`[2024-05-15] …`), live-факты — как раньше (после backfill они равны).
- **FR-9 (Веса).** `history_import` weight 0.3 (ниже chat_history 0.5) — старое не перебивает новое; time-decay применяется только к ранжированию, expires_at NULL — никогда не протухает.
- **FR-10 (Перенос на прод).** Переносится только дельта импортированных строк (fact → FTS-строка → vec-строка сырьём с remap rowid); live-факты прода не трогаются; повторный перенос идемпотентен.
- **FR-11 (CLI-аудит).** `--dry-run` читает файлы/сырьё без записи и печатает статистику; все режимы пишут человекочитаемые статы (принято/отсеяно/ошибки/скорость/ETA).

### 2.2 NFR

- **NFR-1 (Диск).** Финальный размер БД ≤ 8 ГБ (цель 6–8 ГБ) при ~14 ГБ свободного места на сервере; FTS-этап всех 4 файлов ≈ 0.6–0.8 ГБ; vec-дельта — по таблице сценариев (§2.3). После FTS-этапа: `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM`.
- **NFR-2 (RAM).** Потоковый разбор (ijson, `messages.item`), батч-транзакции по 500, никаких цельных файлов/массивов в памяти; пик — десятки МБ на парсер + страницы SQLite. Проверяется замером на сервере (961 МБ RAM).
- **NFR-3 (Время FTS).** Ожидание: порядка минут–1 часа на 4 файла (после B5-аудита — фактическая скорость); прогресс tqdm.
- **NFR-4 (Время Graph).** Ориентир: ~100k содержательных сообщений ≈ 4–7 ч на qwen3.5:9b (Q4, ~105 t/s); прерывание безопасно (`--resume` по `history_processed`).
- **NFR-5 (Стоимость).** API-эмбеддинги: ~$4–10 на ~300k фактов (~40 токенов/факт); `--embed-mode skip` — $0, факты живут текстом/FTS.
- **NFR-6 (Безопасность).** `migrate_history/` и БД-снапшоты не коммитятся (R17, .gitignore); секреты в логах не печатаются.
- **NFR-7 (Регресс).** OFF-состояние тумблера и live-пути записи фактов — без изменений; полный pytest → 0 failed; миграции идемпотентны (повторный запуск no-op).
- **NFR-8 (Персистентность конфига).** `memory.infinite_retention` читается только через `hot.get("memory.infinite_retention", False)`; без PG фолбэк False.

### 2.3 Таблица сценариев размера БД (база для выбора охвата)

vec0-строка при dim 3072: float = 12 288 Б, int8 = 3 072 Б; «both» = 15 360 Б/факт ≈ 15.6 КБ. Факты ≈ 25% содержательных сообщений (норма по данным Step 0).

| Сценарий | Сообщений (оценочно) | Фактов (density 0.25) | Vec (float+int8) | Vec (float-only) | +FTS/сырьё | Итог БД | Комфорт |
|---|---|---|---|---|---|---|---|
| Live-чат id 2661910336, 2 файла (`--only-live-chat` / `--files 2026.json 10.08.2025.json`) | ~640k | ~160k | 2.5 ГБ | 2.0 ГБ | ~0.5 ГБ | **~3.0 ГБ** | ✅ комфортно |
| Все 4 файла (охват; оценка по плотности 0.25 из планирования) | ~1.1M | ~277k | 4.3 ГБ | 3.4 ГБ | ~0.7 ГБ | **~5.0 ГБ** | ⚠️ в лимите 6–8 ГБ |
| Все 4, `--fact-density 0.15` (**дефолт CLI после B5-аудита**) | ~1.1M | ~166k | 2.5 ГБ | 2.0 ГБ | ~0.7 ГБ | **~3.2 ГБ** | ✅ комфортно |
| Сырые сообщения с vec (не делаем) | 2.2M | — | 34 ГБ | 27 ГБ | — | неприемлемо | ❌ |

Замечания:
- **vec пишется только для фактов**, не для сообщений (иначе 14–18 ГБ — невозможно).
- **int8-only как основной режим отклонён по коду**: KNN-путь бота — грубый поиск по `embedding_i8` **обязательно с реранком по float-колонке** (`_vec_candidates`/`_rerank_by_float`, summary_memory.py:1674-1720), а `_dedup_knn` (1461) читает только float-колонку; строки без float-вектора бот в KNN не видит (тихий фолбек в FTS). Поэтому колонка float **обязательна**.
- **Дефолт `--vec-mode both`** — единственный режим, искомый ботом при любой его конфигурации (VEC_INT8_ENABLED True/False). `float` — резерв для жёсткой экономии диска: ищется только если бот работает в float-режиме (VEC_INT8_ENABLED=False), иначе — FTS-фолбек.
- **Дефолтный охват** = все 4 файла (история одного переезжавшего чата, все экспорты → `-1002661910336`), **рекомендуемый порядок**: сначала live-чат 2 файлами (3.0 ГБ), затем, по желанию юзера, второй заход `--files` для двух старых экспортов (ещё +2.0–2.2 ГБ). `--fact-density` и `--min-fact-chars` — точные регуляторы объёма на втором заходе.

---

## 3. Техдизайн

### 3.1 Архитектура: новые компоненты и схема данных

Новый пакет **`tools/history_import/`** (импортируется без side-эффектов бота):

- `__init__.py`, `parser.py` — потоковый разбор и нормализация записей экспорта;
- `loader.py` — FTS-загрузчик и выборка сырья для Graph-этапа;
- `checkpoints.py` — таблица-прогресс `import_checkpoints`;
- `prompts.py` — канон `HISTORY_EXTRACT_PROMPT` (новый, канон R46-2 не трогаем);
- `llm_worker.py` — Graph-этап: LLM-вызов (Ollama), embed-хелпер, запись фактов/vec;
- `report.py` (опц.) — общий формат стат-отчётов.

Корневой **`manage.py`** (argparse-диспетчер, help на русском): подкоманды `import_history`, общие опции. Только stdout-логи/прогресс — бот не запускается.

Зависимости: `requirements.txt` += `ijson>=3.3`, `tqdm>=4.66` (openai/httpx уже есть; openai-пакет воркеру НЕ обязателен — сырой httpx POST).

**Таргет импорта.** Все 4 экспорта — это один чат, который переезжал между супергруппами; таргет памяти — runtime-супергруппа **`-1002661910336`** (подтверждено фазой 1: чат-лор живёт под этим id). Имя чата в исторических фактах не меняется.

**Маппинг записи экспорта → `smart_messages`** (нормализация `normalize_message(item) -> dict | None`):

| Поле экспорта | Куда | Правило |
|---|---|---|
| `type` | — | `!= "message"` → отсев (service/политика/join и т.п.) |
| `date_unixtime` | `timestamp` | `int(...)`; битое → ошибка+пропуск (счётчик) |
| `from_id` | `user_id` | `user123` → 123; `channel…`/отсутствует → NULL |
| `from` | `author_name` | как есть, `""` при отсутствии |
| `text` | `text` | строка → как есть; список кусков/объектов с `text` → join; отсутствует → NULL; пустая строка → NULL |
| медиа-поля (`photo`,`video`,`animation`,`voice`,`video_note`,`document`,`sticker`,`contact`,`poll`,`game`,`location`) | `media_type` | первое найденное поле; иначе `'text'`. Медиа без подписи — сохранить (text NULL) |
| `reply_to_message_id` | `reply_to_id` | информационно (экспортные id отрицательны — цепочки не резолвим) |
| `forwarded_from`/`forward_from` | `is_forward`, `forward_source` | текст источника как есть, префикс «переслано от» не добавляем |
| — | `import_key` | `sha256(f"{timestamp}|{user_id}|{text}")[:32]` — считается всегда |
| — | `tg_message_id` | **NULL** (отрицательные/коллизии между экспортами) |

Отсев записи целиком: `type != message`; текст пуст И медиа нет. При пустом text и медиа: text NULL (в FTS строка не пишется — условие «text IS NOT NULL AND text != ''», как в `delete_smart_messages_*`/`save_smart_message`).

**Итоговые изменения схемы** (суммарно, детали в §3.4):

- `graph_facts`: + `message_timestamp INTEGER` (nullable); CHECK `origin` += `'history_import'`; + частичный UNIQUE-индекс `idx_graph_facts_history_import ON graph_facts(chat_id, fact, message_timestamp) WHERE origin = 'history_import' AND message_timestamp IS NOT NULL`.
- `smart_messages`: + `import_key TEXT` (nullable; partial UNIQUE `idx_smart_messages_import_key ON smart_messages(import_key) WHERE import_key IS NOT NULL`); + `history_processed INTEGER NOT NULL DEFAULT 0` (+ частичный индекс `idx_smart_messages_history_pending ON smart_messages(chat_id, history_processed) WHERE history_processed = 0`).
- Новая аддитивная таблица `import_checkpoints(path TEXT PRIMARY KEY, processed INTEGER NOT NULL DEFAULT 0, total INTEGER, done INTEGER NOT NULL DEFAULT 0, updated_at INTEGER)` — CREATE IF NOT EXISTS в цепочке `initialize()` (БЕЗ подъёма user_version; прецедент smart_cache R51-5).

### 3.2 CLI-контракт (`manage.py`)

```
python manage.py import_history --mode fts
    [--files FILE... | --all | --only-live-chat]
    [--db PATH] [--target-chat -1002661910336]
    [--batch-size 500] [--resume | --reset] [--dry-run]

python manage.py import_history --mode graph
    [--db PATH] [--chat -1002661910336]
    [--endpoint http://localhost:11434/v1] [--transport openai|ollama]
    [--model qwen3.5:9b] [--batch-size 25]
    [--fact-density 0.15] [--min-fact-chars 12]
    [--vec-mode both|float] [--embed-mode api|skip]
    [--limit N] [--dry-run] [--resume | --reset]
```

- Выбор файлов обязателен для `fts`: явный `--files` (порядок задаёт приоритет дедупа — «свежий первым»: `2026.json → 10.08.2025.json → 10.2024.json → желтая`) или `--all`; `--only-live-chat` — раскрывается в 2 файла экспорт-id 2661910336 (детект по шапке файла, см. §4). Имена файлов с кириллицей передаются явно (glob-сюрпризов нет).
- `--db` — путь к SQLite-БД (дефолт `settings.DB_PATH`). CLI поднимает `DatabaseService.initialize()` (применяет миграции v1–v7); для `--mode fts` требует колонку `import_key` (fail-fast: миграция v7 не влита → понятная ошибка).
- `--resume` — продолжение (fts: перечитать файлы, `INSERT OR IGNORE` дубли сбросит; graph: `WHERE history_processed = 0`); `--reset` — начать заново (fts: сброс чекпоинтов, запись идемпотентна; graph: `UPDATE smart_messages SET history_processed = 0 WHERE chat_id = ? AND import_key IS NOT NULL` — переобработка всех импортированных строк чата; дубли фактов отсекаются UNIQUE-индексом FR-6(г)).
- `--dry-run` — без записи: fts — парсинг + статы (как B5-аудит); graph — подсчёт пачек к обработке и параметров, LLM/embed-вызовы НЕ выполняются.
- `--limit N` (graph) — остановиться после N пачек (пробный прогон/ETA-замер; без лимита — все непомеченные).
- Progress: tqdm на stderr (сообщений/с, фактов/батч, ETA, счётчики ошибок); журнал ошибок — stdout (WARNING на битые записи, ≤ 20 строк, далее счётчик).
- `--transport openai` (дефолт): POST `{endpoint}/chat/completions`; `--transport ollama`: POST `http://{endpoint-host}/api/chat` (см. §3.5, Q5).

### 3.3 FTS-этап (сервер; парсер + загрузчик)

**Парсер (`parser.py`)** — `ijson.items(f, "messages.item")` по каждому файлу (pretty-printed JSON; построчный парсинг исключён). На запись: `normalize_message` (§3.1). Серьёзная структурная ошибка файла (не JSON/обрыв потока) → стоп по файлу с ошибкой и чекпоинтом (повторный `--resume` безопасен); битые/неполные объекты записей — счётчик `errors`, continue. На выходе по файлу: id прочитано / принято / отсеяно с причинами (type!=message, пустой текст, битый timestamp), дубли-кандидаты по import_key, скорость (сообщений/с, МБ/с), пиковый RSS.

**Загрузчик (`loader.py`)** — на том же соединении DatabaseService (миграции уже применены), батчи по `--batch-size` (500), одна транзакция на батч:

1. `INSERT OR IGNORE INTO smart_messages (user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, is_forward, forward_source, import_key, tg_message_id) VALUES (…NULL…)`; `cursor.rowcount == 0` → дубль, FTS-шаг пропускаем (строка и её FTS-запись уже существуют с прошлого прогона — идемпотентность);
2. если вставлено и text непустой: `INSERT INTO smart_messages_fts(rowid, text) VALUES (lastrowid, …)` (внешний content — ручная синхронизация, триггеров нет; паттерн `save_smart_message` database.py:851-881). Дублирование rowid в FTS5 не контролируется самой FTS-таблицей (external content не знает о дублях) — поэтому FTS-запись выполняется ТОЛЬКО при rowcount==1 основного INSERT (см. шаг 1);
3. `import_checkpoints` upsert (processed += n, total = прочитано на текущий момент файла);
4. commit.

После всех файлов: `PRAGMA wal_checkpoint(TRUNCATE)` + `VACUUM` + итоговая статистика (COUNT по chat_id, строк FTS, ошибки, длительность). FTS-этап НЕ трогает graph_facts/vec и НЕ требует v7-колонок graph_facts (только import_key в smart_messages).

**Чекпоинт-философия (Q4):** идемпотентность достигается `import_key` + INSERT OR IGNORE, поэтому «resume после обрыва» = перечитать файл с начала: парсинг быстрый (МБ/с), все дубли отбрасываются индексом за O(1) на строку, запись идёт только для новых. Чекпоинт служит прогрессу/статам и `--reset`, отдельные side-файлы не нужны.

### 3.4 Миграция v7 (`services/database.py`)

Константа `_SCHEMA_VERSION_HISTORY = 7` рядом с :13-18; `_GRAPH_FACT_ORIGINS_SQL` (:26-29) += `'history_import'` (единый источник CHECK); вызов в цепочке `initialize()` после `_migrate_chat_protected_facts_v6` (:222).

`_migrate_history_v7()` — идемпотентная, три независимые части, каждая с guard'ом:

**(а) graph_facts rebuild по паттерну `_migrate_user_memory_v5` (database.py:465-510)** — guard: `sqlite_master` для `graph_facts` не содержит `'history_import'` (тогда же отсутствует колонка `message_timestamp`, т.к. добавляются вместе):
```
ALTER TABLE graph_facts RENAME TO graph_facts_old;
CREATE TABLE graph_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, fact TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT 'chat_history' CHECK (origin IN <_GRAPH_FACT_ORIGINS_SQL>),
  expires_at INTEGER, created_at INTEGER NOT NULL, target_user TEXT,
  weight REAL NOT NULL DEFAULT 0.5, status TEXT NOT NULL DEFAULT 'confirmed',
  last_confirmed_at INTEGER, supersedes INTEGER,
  message_timestamp INTEGER);
INSERT INTO graph_facts (id, chat_id, fact, origin, expires_at, created_at,
  target_user, weight, status, last_confirmed_at, supersedes, message_timestamp)
  SELECT id, chat_id, fact, origin, expires_at, created_at, target_user,
  weight, status, last_confirmed_at, supersedes, NULL FROM graph_facts_old;
DROP TABLE graph_facts_old;
CREATE INDEX IF NOT EXISTS idx_graph_facts_chat_origin …;
CREATE INDEX IF NOT EXISTS idx_graph_facts_target_user …;
```
**FTS5 `graph_facts_fts` НЕ пересоздаётся** — прецедент D201/v4/v5: content-таблица пересоздана с теми же rowid, `content='graph_facts'` резолвится динамически, индекс валиден (проверено в v4/v5 комментариях :422-424/:471-472). Затем:
- `UPDATE graph_facts SET message_timestamp = created_at WHERE message_timestamp IS NULL` (существующие факты: рендер COALESCE не меняет вывода — даты как раньше);
- `CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_facts_history_import ON graph_facts(chat_id, fact, message_timestamp) WHERE origin='history_import' AND message_timestamp IS NOT NULL;`

**(б) smart_messages: import_key + history_processed** — только ALTER-веткой (как tg_message_id :303-311; CREATE TABLE :87-99 НЕ трогаем — существующая схема не меняется):
```
try: ALTER TABLE smart_messages ADD COLUMN import_key TEXT
try: ALTER TABLE smart_messages ADD COLUMN history_processed INTEGER NOT NULL DEFAULT 0
CREATE UNIQUE INDEX IF NOT EXISTS idx_smart_messages_import_key
  ON smart_messages(import_key) WHERE import_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_smart_messages_history_pending
  ON smart_messages(chat_id, history_processed) WHERE history_processed = 0;
```
Порядок ALTER-ов внутри одной миграции; каждый ALTER в try/except OperationalError (уже есть колонка). smart_messages FTS не затрагивается (rebuild самой таблицы не происходит — внешняя FTS остаётся валидной).

**(в)** `PRAGMA user_version = 7`. Повторный запуск — только PRAGMA (guard'ы). `scripts/`-отдельного файла миграции не нужно (паттерн chain в database.py; одноразовые скрипты migrate_*.py — прецедент прошлых раундов, здесь миграция выполняется ботом при старте).

**`insert_graph_fact` расширение (database.py:1193):** параметр `message_timestamp: int | None = None` → колонка в INSERT (NULL для live-вызовов — поведение не меняется, тесты-регресс обязательны). FTS-строка — как сейчас (внутри метода).

### 3.5 Graph-этап (воркер; локально на ноутбуке)

**Выборка сырья.** Пачки: `SELECT … FROM smart_messages WHERE chat_id = ? AND history_processed = 0 AND import_key IS NOT NULL AND text IS NOT NULL AND text != '' ORDER BY timestamp ASC LIMIT 25`. (import_key IS NOT NULL — обрабатываем только импортированную историю; live-строки к воркеру не относятся.) После успешной записи фактов пачки — `UPDATE smart_messages SET history_processed = 1 WHERE id IN (…)` в той же транзакции (resume без потерь/дублей). `--limit N` — стоп после N пачек; `--reset` — обнуление флага по всем импортированным строкам чата (см. §3.2).

**Промпт-канон `HISTORY_EXTRACT_PROMPT` (`prompts.py`, новый).** Системная роль «архивариус»: извлечь **проверяемые значимые факты** о людях/событиях/отношениях/лоре чата (включая устойчивый сленг/«мемы» сообщества, но БЕЗ сиюминутных шуток, оскорблений, эмоций); каждая факт-строка — короткое утверждение в стиле существующих строк graph_facts (реализатор фиксирует выборку 20 живых фактов всех origin из local_database.db как пример в комментарии); даты событий формулируются как в исходных сообщениях («в марте 2025 X сделал Y»); колонка `message_timestamp` = дата **сообщения-источника**, LLM её не выдумывает и не возвращает. Вход (user): пачки `[%Y-%m-%d %H:%M] Имя: текст` (skip пустых; формат как L1-рендер). Выход — строго JSON: `{"facts": [{"fact": "…"}]}`.

**Вызов LLM (Q5, live-проверка @Architect при T-747/F1 на установленной юзером Ollama):**
- По research: Ollama `/v1/chat/completions` **игнорирует** top-level `think` и начиная с определённых версий глушит думание только через OpenAI-стандартное поле **`reasoning_effort`** (`"high"/"medium"/"low"` → думает; **`"none"` → думание ВЫКЛ**); нативный `/api/chat` — через top-level `"think": false`. Версия поддержки зависит от сборки Ollama — фиксируется после live-проверки в константе `THINK_OFF` + комментарии.
- Дефолт: `--transport openai` (эндпоинт юзера `/v1`), в тело запроса кладём **оба** поля `{"think": false, "reasoning_effort": "none"}` (лишние поля Ollama игнорирует; belt-and-suspenders на будущие версии). JSON-режим: `response_format={"type": "json_object"}` (+ формат в промпте).
- Если на установленной Ollama думание не глушится (пустой `content`, ответ в `reasoning_content`, гигантские `usage`): fallback — `--transport ollama` (POST `{host}/api/chat` c `"think": false` + `"format": <schema>`) либо модель без думания `qwen3:14b` (резерв юзера). Способ фиксируется в константе и README.
- retry/backoff по образцу LLMClient (timeout, до 3 попыток, экспонента); битый JSON/мусор → retry → пачка откладывается в список «отложенные» сессии (не теряется), в конце прогона — повторная попытка и счётчик.
- Ограничение выхода: максимум фактов на пачку `max(1, round(batch_size * fact_density))` — **регулятор объёма/скорости** (`--fact-density`, дефолт **0.15**); факт короче `--min-fact-chars` символов (дефолт **12**) отбрасывается (мусор/фрагменты). Дефолты зафиксированы по решению оркестратора после B5-аудита 4 файлов (фактический итог уников — 1 887 027 сообщений); воркер использует те же дефолты (константы `DEFAULT_FACT_DENSITY`/`DEFAULT_MIN_FACT_CHARS` в `llm_worker.py`, `GRAPH_DEFAULT_DENSITY`/`GRAPH_DEFAULT_MIN_CHARS` в `manage.py`).

**Запись факта (пачка за пачкой):**
1. `insert_graph_fact(chat_id=-1002661910336, fact=…, origin="history_import", expires_at=None, target_user=None, weight=0.3, message_timestamp=<…>)`. **message_timestamp:** пачка = 25 сообщений, LLM возвращает только тексты фактов; детерминированное правило — `MAX(timestamp)` сообщений пачки (дата-колонка «не раньше» всей пачки; сдвиг ≤ размера пачки — минуты, для рендера `[%Y-%m-%d]` несущественно). LLM даты НЕ присылает — выдуманные даты исключены.
2. Дубль (та же пачка переобработана после сбоя): `INSERT OR IGNORE`-семантика обеспечивается частичным UNIQUE-индексом FR-6(г) — дубликат молча не вставляется (rowcount 0), ошибкой не считается.
3. Vec (если `--embed-mode api`): embed-хелпер на `LLMClient` (base_url/api_key/embedding_model из `.env` ноутбука — те же, что у бота: `LLM_BASE_URL`, `LLM_API_KEY`, `EMBEDDING_MODEL_NAME=gemini-embedding-001`, `EMBEDDING_DIM=3072`); запись в `graph_facts_vec` **сырым SQL по образцу `_insert_graph_vec_row` (summary_memory.py:995-1011)** — float-колонка всегда, int8 через `vec_quantize_int8(?, 'unit')` при `--vec-mode both`; rowid=fact_id, +fact_id/+chat_id/+origin/+expires_at. Простая сессионная dedup-таблица «text → вектор» (повторный embed того же текста в прогоне — из dict). Embed-фейл → факт остаётся текстом (деградация как боевая, «факт остаётся ТЕКСТОМ»), счётчик `no_vec` в статах; nodes/edges НЕ создаём (прецедент user_memory T-713).
4. `--vec-backfill` (опциональный подрежим того же `--mode graph`): догонка векторов — выборка `graph_facts WHERE origin='history_import' AND id NOT IN (SELECT rowid FROM graph_facts_vec)` → embed + INSERT (закрывает «--embed-mode skip» задним числом).
5. По завершении прогона — отчёт: пачек обработано/отложено/ошибок, фактов, дублей-IGNORE, без vec, ETA, скорость (батч/с).

**Почему не MemoryManager:** воркер — отдельный процесс без бота; MemoryManager тянет крон/сервисы. Переиспользуются только: SQL-образцы записи vec (константа в summary_memory или копия в llm_worker с комментарием-ссылкой), ретраи/формат промпта, формат вектора. Параметры vec0-таблиц (dim) читаем из `sqlite_master` снапшота при старте (самопроверка: фактический dim таблицы == dim эмбеддинга API; расхождение — fail-fast с понятной ошибкой).

### 3.6 Тумблер `memory.infinite_retention` и гейты TTL/retention

**Механика параметра (Q6a).** Новая категория `memory`:
- `config/settings.py`: поле `INFINITE_RETENTION: bool = _env_bool("INFINITE_RETENTION", False)` (в `.env`/`.env.example` не добавляется — значение управляется админкой/PG; поле нужно для сида, экспорта каталога и теста полноты; `env_name` у записи каталога обязан совпадать с именем поля — иначе `scripts/migrate_env_to_pg.py:106` упадёт на `os.environ.get(None)`);
- `services/param_catalog.py`: константа `CATEGORY_MEMORY = "memory"` + в `CATEGORIES` (кортеж :35-43) и docstring; запись в новом списке `_MEMORY` (по образцу `_FLAGS`): `ParamSpec(settings_field="INFINITE_RETENTION", env_name="INFINITE_RETENTION", category="memory", type="bool", pg_id="memory.infinite_retention", title_ru="Бессрочное хранение памяти", group="memory_infinite", description="Отключает сжатие/удаление сырья и TTL-очистки памяти: всё хранится бессрочно (импорт истории)")`; `GroupSpec("memory_infinite", "memory", "Бессрочное хранение", "…", order=1)`;
- `services/pg_db.py`: `SEED_CATEGORIES` (:110-113) += `CATEGORY_MEMORY` → стартовый сид `memory.infinite_retention=false` (ON CONFLICT DO NOTHING; ConfigCache.init самозасевает);
- `web/app.js`: вкладка `memory_rag` sources += `{ category: 'memory', groups: null }` (bool-тумблер рендерится автоматически);
- `web/api/routes.py`: `_category_title` (:533-542) += `"memory": "Память"` (заголовок секции в дереве прав/фолбэке). RBAC: roles-tree строится из REGISTRY — новая секция `memory` появляется автоматически; права задаются только (wildcard) admin — правок permissions не требуется; moderator новые ключи не видит (без прав) — приемлемо (тумблер админский).
- Чтение везде: `hot.get("memory.infinite_retention", False)`.

**Семантика ON (Q6b) — «сырьё и факты памяти не удаляются и не сжимаются».** Итоговый список гейтов (самодокументируется в docstring модуля summary_memory):

| # | Точка (код) | ON | OFF |
|---|---|---|---|
| G1 | `summary_memory.compress_and_purge` (:1887-1935), вызывается из `summary_generator.py:101` (крон 0,6,12,18 и /summary) | extract-only ветка: `_extract_and_save_graph(chat_id, batch)` по пачкам старых сообщений **без** сжатия/удаления и **без** записи smart_archive; **пачки импортированных строк исключаются из extract** (см. ниже) | ровно текущий код (сжатие → smart_archive+extract → DELETE сырья) |
| G2 | `summary_memory._purge_archive` (:2024) | skip (no-op) | как сейчас (retention архивных фактов) |
| G3 | `database.purge_expired_graph_facts` (:1261) — вызывается из compress_and_purge (:1930) и review | `return 0` без SQL | как сейчас |
| G4 | `database.purge_unconfirmed_graph_facts` (:1793) — из review (:294) | `return 0` | как сейчас |
| G5 | `database.trim_compression_log` (:1814) — из review (:296) | `return 0` | как сейчас |
| G6 | `memory_maintenance.review` (:273-300) | фазы expired/unconfirmed/trim скипаются (гейты G3-G5 делают это сами); **merge-фазы (склейка дублей, `_merge_cluster`) работают** — это слияние, не удаление по TTL | как сейчас |
| — | merge-джоб `MemoryMaintenanceService._tick_merge` | не трогаем | — |
| — | Явные команды «забудь» (`forget_direct_facts`/`forget_memory_facts`), `/clear` (`clear_direct_dialogue`), user-forget | **работают всегда** (явное желание юзера; гейтов нет) | — |

Место гейтов G3–G5 — **в начале методов database.py** (единая точка, покрывает всех вызывающих; импорт `from services import hot_config as hot` в database.py циклов не создаёт: hot_config → param_catalog → config.settings; param_catalog не импортирует database.py). `hot.get` при отсутствии кэша возвращает default=False — поведение тестов/деградации не меняется.

**Исключение импортированных строк из extract-only (важно):** при ON extract-only ветка выбирает пачки через новый вариант `get_smart_raw` с фильтром **`AND import_key IS NULL`** — иначе крон начал бы LLM-экстракцию (nodes/edges, триплетный промпт) по миллионам импортированных сообщений параллельно Graph-воркеру (дубли/двойные деньги). Импортированные строки графом пополняются ТОЛЬКО воркером (`history_processed`); сырьё при ON живёт вечно и доступно L1/FTS.

**Деплой-порядок обязателен:** тумблер ON **до** FTS-импорта на проде; OFF — только после завершения Graph-этапа и по явному решению юзера (в отчёте G5 предупреждение: OFF → следующая L3-компрессия начнёт сжимать/удалять сырьё старше 30 дней, включая импортированную историю).

### 3.7 Дата-рендер (COALESCE) и перенос Graph-дельты на прод

**Рендер `[%Y-%m-%d]`.** `_date_prefix`/`build_rag_context` (summary_memory.py:477-514) принимают ts как есть — не меняются. Правятся **источники троек `(origin, fact, ts)`** — везде ts = `COALESCE(message_timestamp, created_at)`:

1. `database.search_graph_facts_fts` (:1220): SELECT += `f.message_timestamp`, `COALESCE(f.message_timestamp, f.created_at) AS rag_ts`;
2. `summary_memory._search_graph_facts` (FTS-ветка :1605-1625): кортеж `(origin, fact, row["rag_ts"])` вместо `row["created_at"]`;
3. `database.get_graph_fact_records` (:1664): SELECT += `message_timestamp` (KNN-путь); `_knn_graph_facts` (:1643-1671): кортеж с `row["message_timestamp"] or row["created_at"]`;
4. `database.get_graph_fact_texts` (:1241): SELECT += `message_timestamp`, кортеж — `message_timestamp or created_at` (единообразие; потребитель сейчас один — будущие/тесты);
5. `get_rag_context(…, sort_by_timestamp=True)` (:1567-1568) сортирует по ts кортежа — автоматически получает дату сообщения (DirectChat-таймлайн истории идёт в хронологическом порядке, а не в порядке импорта);
6. L1-окна/`query_chat_memory` — НЕ трогаем (`smart_messages.timestamp` — уже реальное время).

Критерий: импортированный факт (message_timestamp = дата сообщения 2024-го) рендерится `[2024-…]`, live-факт (message_timestamp == created_at после backfill v7) — ровно как раньше.

**Перенос дельты на прод (Q7).** Graph-воркер работает на снапшоте; прод живёт. Перенос только импортированных строк (после бэкапа прод-БД):
1. `graph_facts` origin='history_import': `INSERT OR IGNORE … SELECT` по колонкам + пересчёт id (вставка по одному: `cursor.lastrowid` → remap); идемпотентность — частичный UNIQUE-индекс FR-6(г) (повторный перенос: IGNORE, id существующей строки из SELECT);
2. FTS-строки пишутся для фактически вставленных (rowid = новый id) — как в insert_graph_fact;
3. vec: для каждого вставленного факта — чтение **блоба** (`embedding`, `embedding_i8`) из локальной `graph_facts_vec` по rowid=факта (float32 dim*4 Б; int8 dim Б; sqlite-vec хранит сырые блобы) → `INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, expires_at, embedding[, embedding_i8])` с блобами как есть (rowid = новый id факта); уже существующий факт (IGNORE) → vec-строку не дублируем;
4. live-факты прода за окно обработки не трогаются; верификация: COUNT(history_import) локально == на проде, KNN-пробник, FTS, рендер `[2024-…]`.

---

## 4. Edge cases

1. **Пересечение экспортов** (`10.08.2025.json` ↔ `2026.json`, период 31.03–10.08.2025): порядок файлов «свежий первым» (задаёт вызывающий/`--all`) + INSERT OR IGNORE по import_key → приоритет `2026.json`. B5-аудит фиксирует фактический % дублей.
2. **Отрицательные/коллизующие экспортные id**: в `tg_message_id` NULL; дедуп только по import_key; reply_to_id — информационный, цепочки не строим.
3. **Пересечение импорт↔живая память бота** (сообщения последних ~30 дней, которые бот уже сохранил сам и ещё не сжал): import_key у live-строк NULL → дубли не отсекаются автоматически; риск низкий (ретенция 30 дней), при фактическом повторе — чистка вручную/вывод в отчёте B5 (не блокер эпика).
4. **Битые записи/структура**: битый `date_unixtime`, неполный объект → счётчик + пропуск (не ронять импорт); структурный обрыв файла → стоп файла с чекпоинтом + `--resume`.
5. **FTS5 и дубли**: FTS5 (external content) сам не знает о дублях rowid и не отклоняет повторную вставку (проверено на SQLite 3.4x: синтаксис OR IGNORE принимается, дубликат rowid молча индексируется повторно) → FTS-запись выполняется только при `rowcount == 1` основного INSERT в smart_messages (см. §3.3);
6. **Обрыв транзакций**: коммит на батч; kill процесса → повтор `--resume` безопасен (дедуп по import_key; graph — по history_processed).
7. **WAL-разрастание на сервере**: регулярные батч-коммиты + финальные `wal_checkpoint(TRUNCATE)`/`VACUUM`; мониторинг размера `-wal` в G3.
8. **Ollama думает (qwen3.5)** — Q5: `think:false` на `/v1` игнорируется старыми сборками (пустой content / ответ в reasoning_content / ×17 токенов); решение: `reasoning_effort="none"` + `think:false` + live-проверка; fallback `--transport ollama` или `qwen3:14b`. Признак проблемы детектится автоматически (пустой content при ненулевом usage) и пишется WARNING с подсказкой флага.
9. **Embed API недоступен/лимиты**: факт сохраняется текстом (FTS/граф живут); счётчик «без vec»; догонка — `--vec-backfill`. Сессионный текст→вектор кэш экономит повторные embed.
10. **Повторный факт из разных пачек/прогонов**: отсекается UNIQUE (chat_id, fact, message_timestamp) для history_import; крос-дубли с live-фактами НЕ чистим (review-склейка на проде покроет, Q9).
11. **Диск сервера**: после заливки 4 файлов (~1.1 ГБ) и FTS-этапа свободно должно оставаться ≥ ~4–5 ГБ (проверка df до старта; таблица §2.3).
12. **RAM сервера (961 МБ)**: ijson-поток + батчи; json.load целого файла запрещён; замер RSS в B5.
13. **Воркер против живой БД**: воркер работает только на снапшоте/копии; запуск воркера против БД живого бота не поддерживается (бот не запускается одновременно с CLI на одной БД — SQLite-локи).
14. **Тумблер OFF после импорта**: деплой-предупреждение (G5); архивация/удаление импортированного сырья по ретенции 30 дней — намеренное поведение OFF.
15. **`message_timestamp` у фактов без привязки к сообщению**: всегда `MAX(timestamp)` пачки-источника (§3.5); LLM даты не присылает — исключает выдуманные даты.

---

## 5. Acceptance criteria (проверяемые)

1. **FTS-импорт идемпотентен**: повторный `--mode fts` на той же БД не меняет `COUNT(*)` smart_messages и строк FTS; `COUNT(import_key непустых) == COUNT(строк)`.
2. **Дедуп пересечения**: при импорте обоих live-файлов сообщения 31.03–10.08.2025 не задваиваются (B5-аудит: % дублей совпадает с ожиданием; победил `2026.json`).
3. **Размеры БД**: итог в пределах таблицы §2.3 (сценарий по выбору юзера; ≤ 6–8 ГБ); после FTS-этапа размер ≈ 0.6–0.8 ГБ + база.
4. **Тумблер ON**: `compress_and_purge`/`review` на БД с истёкшими фактами и старым сырьём НЕ удаляют (счётчики purge 0, сырьё на месте, archive не пополняется, extract-факты появляются); OFF — регресс-тесты текущего поведения зелёные. Явный «забудь» удаляет и при ON.
5. **Даты**: факт истории рендерится в RAG-контексте с `[<дата сообщения>]`; live-факт — без изменений (`COALESCE` после backfill равен created_at). RAG по старому периоду (например «что было 15.05.2024») возвращает факты с датами 2024.
6. **Запись импортированного факта**: origin='history_import', weight=0.3, expires_at NULL, status='confirmed', message_timestamp проставлен; vec-строка (float+int8 при `--vec-mode both`) с rowid=fact_id; KNN-пробник по историческому факту находит его.
7. **Resume**: обрыв fts на середине файла → `--resume` завершает без дублей; обрыв graph-воркера → повторный прогон продолжает с `history_processed=0` и не пишет дублей.
8. **dry-run**: `--mode fts --dry-run` и `--mode graph --dry-run` не пишут ни строки (COUNT/чекпоинты не меняются), печатают статы.
9. **Миграция v7**: на БД с v6-схемой данные сохранены (id/FTS-валидность graph_facts_fts), message_timestamp == created_at для старых строк, повторный запуск no-op, user_version=7, CHECK принимает history_import и отклоняет неизвестные origin, import_key-индекс работает (дубль → IGNORE).
10. **Перенос дельты идемпотентен**: повторный перенос graph-дельты на прод не дублирует ни факты, ни vec-строки.
11. **Каталог/фронт**: REGISTRY содержит `memory.infinite_retention` (category memory, группа memory_infinite), SEED_CATEGORIES включает memory, PG-сид кладёт False, вкладка «Память и RAG» показывает тумблер, roles-tree содержит секцию «Память»; `hot.get("memory.infinite_retention", False)` == False на чистой БД.
12. **Полный pytest → 0 failed**; git diff --check чист; `migrate_history/`, снапшоты и `.env` не коммитятся.

---

## 6. Миграция и докатка (порядок на проде)

1. **Локально**: каркас B1 → parser B2 → loader/checkpoints B3 → тесты B4 → аудит B5 на реальных 4 файлах (dry-run; цифры в G5-отчёт); части C/D/E с тестами; полный pytest 0 failed.
2. **Коммит/пуш** кода (части B–E + tests + plans). На сервере `git pull --ff-only`.
3. **Бэкап** прод-БД (`local_database.db` + `-wal`/`-shm` копией с датой, вне репо).
4. **Мягкий рестарт бота** → journald: миграция v7 (rebuild graph_facts + backfill + индексы import_key/history_processed + user_version=7), старт чистый; проверка FTS-граф-фактов (rowid-валидность), hot-сид `memory.infinite_retention=false` в PG.
5. **Тумблер ON до FTS-импорта** (`memory.infinite_retention = true` через psql/PgDatabase; hot-релоад/рестарт; верификация `hot.get(...)` == true; счётчик L3-компрессии не растёт).
6. **FTS-импорт на сервере**: заливка файлов (rsync ~1.1 ГБ; df-контроль) → `nohup python manage.py import_history --mode fts --all --resume > /var/log/admin_bot/history_import.log 2>&1 &` → мониторинг RAM/WAL/диска → авто VACUUM+checkpoint в конце → верификация (COUNT по chat_id, FTS-пробники по словам/именам разных лет, отсутствие дублей).
7. **Graph-этап (локально, юзер по Приложению A)**: DevOps снимает снапшот прод-БД после FTS-этапа → юзер гоняет `--mode graph` (заходы `--resume`) → возврат снапшота с фактами.
8. **Перенос дельты на прод** (§3.7, FR-10) + верификация AC-5/6/10 + отчёт юзеру G5 (охват/размеры/тумблер-предупреждение/README-раздел G1).
9. **Финальный docs-коммит**: memory-project-overview.md (Step 9), ARCHITECTURE.md при необходимости, планы (spec.md, backlog).

---

## Приложение A: инструкция юзеру (Ollama + запуск Graph-этапа)

**Цель:** превратить импортированную историю (FTS уже на сервере) в «факты с датами» — локально на ноутбуке, БД бота при этом не трогается (работаем на копии).

**1. Установите Ollama** (ollama.com/download). Проверка: `ollama --version`; сервис слушает `http://127.0.0.1:11434` (по умолчанию; менять не нужно).

**2. Скачайте модель:**
```
ollama pull qwen3.5:9b
```
(~6.6 ГБ, Q4_K_M). Проверка: `ollama run qwen3.5:9b "привет"`. Если GPU слабая — резерв `qwen3.5:9b-q8_0`; если модель всё равно «думает» слишком долго в воркере — резерв `qwen3:14b` (без думания).

**3. Получите снапшот БД** у DevOps (файл `local_database.db` после FTS-импорта + `-wal`/`-shm`, ~1–1.5 ГБ) и положите рядом с проектом (например `C:\Code\Python\adminbot\snapshot.db`).

**4. Убедитесь, что `.env` в папке проекта содержит ключи эмбеддингов** (те же, что у бота на сервере):
```
LLM_BASE_URL=…
LLM_API_KEY=…
EMBEDDING_MODEL_NAME=gemini-embedding-001
EMBEDDING_DIM=3072
```
Без них запускайте с `--embed-mode skip` (факты сохранятся текстом+FTS; векторы потом догоняются `--vec-backfill`).

**5. Запуск** (в корне проекта, в активированном venv; команда одинаковая для продолжения после прерывания):
```
python manage.py import_history --mode graph --db snapshot.db --model qwen3.5:9b
```
Опции при необходимости: `--endpoint http://localhost:11434/v1` (дефолт; если Ollama в Docker — другой адрес), `--limit N` (пробный прогон), `--dry-run` (ничего не пишет). Прерывание безопасно: Ctrl+C → повторный запуск продолжает с места (`history_processed`). Лог-статы (пачек/с, фактов на пачку, ETA, счётчик «без vec») пришлите PM/DevOps.

**6. Сколько ждать:** ориентир ~4–7 ч на 100k содержательных сообщений; live-чат (2 файла) ≈ 25–45 ч, все 4 файла ≈ 45–75 ч (можно гонять заходами `--resume`; ноутбук можно использовать параллельно). По завершении верните снапшот DevOps'у для переноса на прод.

**7. Что НЕ делать:** не запускайте бота против `snapshot.db` (это копия для воркера); не удаляйте исходные `migrate_history/*.json` до финального отчёта.
