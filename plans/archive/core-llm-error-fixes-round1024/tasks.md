# Задачи: core-llm-error-fixes-round1024

> **Раунд 10.24 (UPD2 + UPD3)** · Приоритет **P0** · Шаг 1 @PM (revision UPD3) · Тип: backend/LLM + надёжность
> **ТЗ:** `plans/current_task.md`, UPD2, п.0 (строки 124–153) + **UPD3, п.7 (строка 261)**. Файл untracked; SSH-креды и API-ключи — **не цитировать, не коммитить** (R17/R18). В задачах ниже тексты ошибок и URL даны обезличенно.
> **⚠️ UPD3 №7 — ОТМЕНА п.0b (embeddings):** владелец сам заменит ключ на нативный google-эмбеддинг, чтобы обойти ограничения прокси. Код embeddings (`llm_client.embed`/`_post`/каскад) **НЕ ТРОГАЕМ**; костыли и сокрытие ошибки не нужны. Задачи **T-2191 / T-2192 — CANCELLED BY OWNER**; embed-подпункты T-2193 сняты.
> **Baseline:** HEAD `00eab85`; pytest **7424/0**; SQLite `v12`; каталог REGISTRY **457**; прод `4314ea4`.

## Цель
Устранить **п.0a**: `_extract_and_save_graph` падает с `LLMTimeoutError` (провайдер chat-запросов, 3 попытки, fallback не спасает) — батч сообщений сохраняется, а **граф знания теряется молча**. Требуется: диагностика таймаута, отдельный увеличенный deadline и bounded retry с backoff для канала graph-extract, **логирование** и **устойчивость к таймауту** (батч не теряется, граф не пропадает молча).

**п.0b (embeddings: primary отвечает HTTP 400 «Unknown name `requests`») — ОТМЕНЁН владельцем (UPD3 №7).** Этот код не трогаем, поведение оставляем как есть; вопрос закрыт на стороне владельца (нативный google-эмбеддинг).

## Что уже есть (координаты)
- п.0a: `services/summary_memory.py:3179-3230` (`_compress_purge_extract_only` → `_extract_and_save_graph` → `self.llm.generate`), вызов при таймауте: `services/llm_client.py:753` (`raise LLMTimeoutError`), ретраи `services/llm_client.py:903`.
- п.0b (координаты сохранены справочно, **код не трогаем**): `services/llm_client.py:1130-1187` (`embed`), payload `{"model": …, "input": texts}` на строке `:1145`; фоллбэк-каскад `:1150-1175`. Строки `requests` в репозитории нет — источник несовместимости на стороне прокси-эндпоинта. **Не изменять.**
- Кросс-влияние: телеметрия шагов уже пишет `module/step/input/output/cost_usd` (`web/api/analytics.py:42-124`); логирование payload/ошибок сторонних API — общая фича `logging-infra-round1024`.

## Задачи
- [x] **T-2188** [@Architect] ADR: контракт надёжности **graph-extract** (retry/backoff/deadline, «батч не терять и не терять граф») + явное указание, что тихий пропуск графа недопустим. **Embeddings в объём ADR НЕ входят** (UPD3 №7 — отменено).
- [x] **T-2189** [@Builder] **п.0a:** диагностика — почему fallback не срабатывает на timeout (канал/ключ/дедлайн); добавить в `llm_client.generate`/канал graph-extract отдельный увеличенный deadline и bounded retry с backoff; не менять общий `generate` для остальных потребителей. *(реализовано: `generate_background` + per-call override в `_post`; общий `generate` не изменён)*
- [x] **T-2190** [@Builder] **п.0a:** при исчерпании попыток — **не** молча терять граф: вернуть батч в очередь (не вызывать `mark_smart_messages_processed` на неуспешном батче — сейчас уже так, подтвердить тестом) + ERROR с причиной и `chat_id`; при повторных отказах — счётчик/алерт-лог. *(реализовано: `graph_extract_failed` / `graph_extract_partial` / `graph_extract_dropped` + `graph_extract_dropped_total()`)*
- [ ] ~~**T-2191**~~ [@Builder] **CANCELLED BY OWNER (UPD3 №7)** — provider-aware embed-payload / смена primary embeddings. Код embeddings не трогаем. ID зарезервирован, повторно не использовать.
- [ ] ~~**T-2192**~~ [@Builder] **CANCELLED BY OWNER (UPD3 №7)** — понижение лога embed-primary. Не выполнять.
- [x] **T-2193** [@Builder] Тесты (только graph-extract): timeout graph-extract → батч остаётся необработанным, граф не «теряется молча», повторный крон его подхватывает; ретрай/backoff и отдельный deadline срабатывают. *(embed-подпункты (b)/(c) сняты вместе с п.0b.)* → `TestGraphExtractF1`, `TestPostPerCallOverrideF1`, `TestGenerateBackgroundF1`
- [ ] **T-2194** [@Reviewer] Ревью F1: отсутствие регресса стоимости/латентности, корректность ретраев, R17/R18 (в логах нет секретов); **проверить, что embeddings-код не изменён**.
- [ ] **T-2195** [@DevOps] Деплой + live-проверка: в логах прод нет повторяющегося ERROR таймаута graph-extract; graph-extract успешен или явно повторяется без потери батча; отчёт (без секретов). *(Embeddings-логи вне раунда — не требуется.)*

## Критерии приёмки
- Ни один батч `_extract_and_save_graph` не теряет граф молча: либо запись узлов/связей, либо явный повтор без `mark_processed`.
- Таймаут graph-extract обрабатывается bounded retry + отдельным deadline; при исчерпании — ERROR с причиной и `chat_id`.
- Embeddings-код **не изменён** (п.0b отменён владельцем, UPD3 №7).
- В логах нет секретов; ошибки сторонних API логируются с телом ответа, но без ключей.
- pytest зелёный; существующие тесты аналитики/embedding-каскада не сломаны.

## Риски
- **R1 (High):** увеличение deadline/ретраев повысит латентность фоновых задач → ограниченный bounded retry + отдельный канал.
- **R2 (Medium):** повторная обработка батча при отсутствии идемпотентности upsert → проверить идемпотентность узлов/связей.
- **R3 (Low):** случайное задевание embeddings-кода при правках `llm_client` → ревью-чек «embed-дифф пуст».
- **R4 (R17/R18):** URL/ключи не должны попасть в отчёт и git.

## Зависимости / ступени
- Зависит от: `logging-infra-round1024` (тело ответа провайдера, трассировка) — для диагностики; допустимо стартовать параллельно с минимальным логом.
- Ступень файлов: `services/llm_client.py` — **F1 первый**; `services/summary_memory.py` — **F1** (далее читает F8).
- Feature flag: `GRAPH_EXTRACT_RETRY_ENABLED` (env-only `ClassVar`, **default ON**) — kill-switch для новых ретраев graph-extract. Embeddings-флаг не вводится (отменено).
- Откат: флаг OFF / `git revert`. Δ DDL = 0.
