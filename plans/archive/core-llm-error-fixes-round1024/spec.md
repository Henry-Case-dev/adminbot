# spec.md — F1 `core-llm-error-fixes-round1024` (п.0a: устойчивость graph-extract)

> Раунд 10.24, Часть 1 (backend-core) · Приоритет **P0** · ADR: **ADR-1024-6**
> ТЗ: `plans/current_task.md` UPD2 п.0a (стр. 125–143), UPD3 п.7. Секреты/URL не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; pytest 7424/0; SQLite v12.
> **Область:** только п.0a. **п.0b (embeddings `requests`) ОТМЕНЁН владельцем — код не трогать.**

## 1. Цель

Устранить потерю графа при `LLMTimeoutError` в `_extract_and_save_graph`: сделать фоновый graph-extract устойчивым (чанкование промпта, отдельный дедлайн/бюджет, bounded retry) и **никогда не терять граф молча** — либо запись узлов/связей, либо явный повтор/отброс с метрикой и логом.

## 2. Что уже есть (координаты)

- Вход: `services/summary_memory.py:3171-3198` (`_compress_purge_extract_only`: `while True` → `get_smart_raw(exclude_processed=True)` → `_extract_and_save_graph` → `mark_smart_messages_processed`; на исключении — `logger.exception` + `break`, mark НЕ ставится).
- Мяса: `services/summary_memory.py:3211-3268` (`_extract_and_save_graph`; `tail = text[-_GRAPH_EXTRACT_MAX_CHARS:]`, `:3223`; `_GRAPH_EXTRACT_MAX_CHARS = 8000`, `:462`).
- Общий вызов: `services/llm_client.py:871-938` (`generate`), `_post` `:618-760` (`asyncio.timeout(self._budget)`; `_budget = hot.get("models.llm_total_budget", settings.LLM_TOTAL_BUDGET)` `:304`; `LLMTimeoutError` `:752-755`).
- Идемпотентность: `services/database.py:2490-2541` (`upsert_edge` наращивает `MIN(weight+inc, cap)`).
- Наблюдаемость: F2 `services/external_log.py` (ADR-1024-1).

## 3. Требуемое поведение

1. Фоновый graph-extract идёт **отдельным каналом** с дедлайном `GRAPH_EXTRACT_TIMEOUT_SECONDS` (120с) и ≤ `GRAPH_EXTRACT_MAX_ATTEMPTS` (2) попытками; общий `generate` не меняется.
2. Хвост батча ≤ 8000 символов режется на окна ≤ `GRAPH_EXTRACT_CHUNK_CHARS` (4000), не более `GRAPH_EXTRACT_MAX_CHUNKS` (3).
3. Запись в БД ровно один раз на батч (extract-then-write): нет инфляции весов при повторе.
4. Исходы: **all-ok** → запись+mark; **partial** → запись успешных + mark + `WARNING event=graph_extract_partial`; **none-ok** → без записи/mark + `ERROR event=graph_extract_failed`; после `GRAPH_EXTRACT_MAX_BATCH_FAILURES` (3) подряд → mark + `ERROR event=graph_extract_dropped` + счётчик.
5. `GRAPH_EXTRACT_RETRY_ENABLED=False` → прежнее одиночное поведение (kill-switch).
6. Лог: причина, число чанков ok/failed, `chat_id`; без секретов/URL с ключами.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/llm_client.py` | `generate_background(messages, *, purpose, deadline, max_attempts)`; в `_post(..., budget=None, max_retries=None)` — опциональные per-call override (None = текущее поведение) |
| `services/summary_memory.py` | Переписать `_extract_and_save_graph` на фазы extract→write с чанкованием; счётчик `_graph_batch_failures`/`_GRAPH_DROPPED_TOTAL` + `graph_extract_dropped_total()`; лог через F2-helper |
| `config/settings.py` | env-only `ClassVar`: см. §7 |

## 5. Контракты

### 5.1. `generate_background`

```python
async def generate_background(self, messages: list[dict], *, purpose: str,
                              deadline: float, max_attempts: int) -> str
```
- Разрешает глобальный ключ; при исчерпании — бросает `LLMError`-подкласс (caller решает).
- `deadline`/`max_attempts` передаются как per-call override в `_post` (не меняют `self._budget`/`self._max_retries` для других).
- Не пишет в analytics как System-2 шаг (фоновый вызов вне `physical-two-call`).

### 5.2. Алгоритм `_extract_and_save_graph` (псевдо)

```
if not GRAPH_EXTRACT_RETRY_ENABLED:
    <старый одиночный путь generate()>            # kill-switch
tail = text[-_GRAPH_EXTRACT_MAX_CHARS:]
chunks = [tail[i:i+CHUNK] for i in range(0, min(len(tail), CHUNK*MAX_CHUNKS), CHUNK)]
triplets, ok, failed = [], 0, 0
for ch in chunks:
    try:
        raw = await llm.generate_background(..., deadline=T, max_attempts=N)
        triplets += parse_triplets(raw); ok += 1
    except LLMError as e:
        failed += 1; trace_step(component="graph", step="chunk", status="error", reason=type(e).__name__)
if not triplets:
    failures += 1
    if failures >= MAX_BATCH_FAILURES:
        log_dropped(component="graph", reason="timeout/exhausted", ...); return  # caller добавит mark
    raise GraphExtractError(...)                   # caller оставит батч
write triplets (upsert_node/upsert_edge)
if failed: trace_step(status="partial", extra={chunks_ok, chunks_failed})
failures = 0
```
> `mark_smart_messages_processed` ставит caller после успешного возврата; для `none-ok + drop` — caller должен поставить mark (флаг возврата/исключение `GraphExtractDropped`). Точную форму (возврат-признак vs исключение) фиксирует @Builder в рамках контракта «ровно один mark на батч».

### 5.3. Идемпотентность

Запись только после успешного извлечения всех решаемых чанков (или явного partial/drop); повторный прогон не переписывает один и тот же батч → нет роста весов.

## 6. Тесты

- (a) timeout всех чанков → батч не обработан, граф не потерян молча, повторный крон подхватывает (сообщение есть); лог `graph_extract_failed`.
- (b) partial: 1 чанк ok, 1 failed → записан граф успешного чанка + `graph_extract_partial` + mark.
- (c) 3 полных фейла подряд → `graph_extract_dropped` + mark + счётчик инкрементирован.
- (d) `GRAPH_EXTRACT_RETRY_ENABLED=False` → одиночный вызов, старое поведение.
- (e) `_post` без override — байт-в-байт прежнее поведение (бюджет/ретраи не смещены).
- (f) нет дублей весов при повторном прогоне одного батча.

## 7. Флаги

- `GRAPH_EXTRACT_RETRY_ENABLED` (env-only `ClassVar`, default **ON**) — kill-switch.
- `GRAPH_EXTRACT_CHUNK_CHARS` (4000), `GRAPH_EXTRACT_MAX_CHUNKS` (3), `GRAPH_EXTRACT_TIMEOUT_SECONDS` (120.0), `GRAPH_EXTRACT_MAX_ATTEMPTS` (2), `GRAPH_EXTRACT_MAX_BATCH_FAILURES` (3) — env-only `ClassVar`, вне каталога.

## 8. Риски

- **R1 (High):** рост латентности фона → bounded-retry + отдельный канал, только graph-extract.
- **R2 (Medium):** инфляция весов при повторе → extract-then-write + mark ровно один раз.
- **R3 (Medium):** отброс батча теряет граф → событие `graph_extract_dropped` + метрика (не молча), порог 3.
- **R4 (R17/R18):** URL/ключи не в логах/отчёте → helper F2.

## 9. Критерии приёмки

- Ни один батч не теряет граф молча: либо запись, либо явный повтор без `mark_processed`, либо явный `graph_extract_dropped` с логом и счётчиком.
- При промпте ≤ 4000 символов фоновый вызов укладывается в дедлайн (наблюдаемо в логах).
- Общий `generate` не изменён (регресс-тесты direct/factcheck/summary зелёные).
- В логах нет секретов.

## 10. Откат / Δ

- Откат: `GRAPH_EXTRACT_RETRY_ENABLED=False` / `git revert`.
- Δ DDL = 0; Δ каталога = 0; канон-миграций нет. SQLite остаётся v12.

## 11. Артефакты-ссылки

- ADR: `ADR-1024-6.md`; карта: `round1024-architecture.md` §3.1, §3.4, §5.
- **Отменённые задачи:** T-2191, T-2192 (embeddings) — не выполнять.
