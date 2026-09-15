# Spec F8 — `graphrag-memorize-robustness` (Устойчивость извлечения фактов: не терять молча; `[]` ≠ невалидный ответ; связь с nano-gpt timeout)

> **Раунд:** 10.19 (Step 2 @Architect, 15.09.2026). **Тип:** backend (`services/summary_memory.py`). **Приоритет:** **P1**.
> **ADR:** `adr-1019-7-memorize-robustness.md` (**AMEND F-15 §4** раунда 10.3).
> **Задачи:** T-1845…T-1852. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/90/406/411/88/19**.
> **Источник:** `plans/current_task.md` UPD2 п.6 (строка 160): «nano-gpt отваливается по таймауту, три ретрая в молоко, фолбэк deepseek-flash; модель отвечает невалидным жидким ответом, graphrag скипает, потому что пришёл не json, а пустой список; два раза подряд; память жрёт мусор и не запоминает».
> **Смежность:** F7 (`summary_memory.py` — согласованное вливание). **Конфликт файлов:** `services/summary_memory.py` (F7 при retention).

## 1. Контекст и цель

F-15 (§4, 10.3) уже добавила: тихий WARNING → с маскированным raw, `_fallback_parse_facts` (проза/буллеты), 1 ретрай жёстким промптом. Но остались дыры:

1. **Валидный пустой список `[]` неотличим от «ничего не нашлось»** — `parse_fact_list` возвращает `[]` **без WARNING**; отладка невозможна.
2. **`LLMError` первичной экстракции теряет факты молча:** `_extract_facts` при исчерпании bounded-ретраев `raise exc`; `memorize_facts` ловит его на верхнем уровне (`:1694-1700`) и **не применяет** ни fallback-парсер, ни retry-промпт. Таймаут nano-gpt → `WARNING "LLM failed"` → фактов нет.
3. Диагностика не различает «невалидно / пусто / восстановлено N / потеряно»; логи могут дублироваться (WARNING в `parse_fact_list` + WARNING в `_memorize_facts_inner`).

**Цель:** не терять факты молча; различать `[]` vs невалидный ответ; применять fallback/ретрай в **обеих** ветках (включая `LLMError`); дать понятную не-спамящую диагностику.

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `services/summary_memory.py:496-539` — `parse_fact_list(raw)`: code-fence/объект-со-списком; **не-список** → WARNING «not a JSON list — skipped | raw=…» + `[]`; валидный `[]` → `[]` **без логов**.
- `services/summary_memory.py:568-639` — `_fallback_parse_facts(raw)`: JSON-массив в тексте, построчные тройки (csv/ёлочки/тире); никогда не бросает.
- `services/summary_memory.py:1707-1728` — `_extract_facts`: bounded-ретраи **только** `LLMError` (`limits.graph_memorize_max_batch_retries`, default 2 → 3 попытки); при исчерпании — `raise exc`.
- `services/summary_memory.py:1730-1773` — `_memorize_facts_inner`: `parse_fact_list` → `_fallback_parse_facts` → **один** ретрай `_FACT_RETRY_SYSTEM_PROMPT` → снова parse/fallback; при нуле — `logger.info("graphrag memorize: 0 facts")` + return.
- `services/summary_memory.py:1677-1705` — `memorize_facts`: `except LLMError` → WARNING «LLM failed» (**потеря без fallback**); `except Exception` → `logger.exception`.
- `services/summary_memory.py:2945-2964` — крон `_extract_and_save_graph` (свой `EXTRACT_PROMPT`/`parse_triplets`) — **не** часть memorize-ветки.
- Таймауты провайдеров — `services/llm_client.py` (nano-gpt timeout → ретраи → фоллбэк deepseek-flash). Внешний фактор; важно не терять факты **после** успешного фолбэка.

## 3. Требуемое поведение

1. **Невалидный ответ** → применяются fallback-парсер и/или ретрай; **потеря фактов молча невозможна** — при неудаче явный WARNING с маскированным фрагментом и причиной.
2. **Валидный `[]`** (реально нет фактов) отличается от **невалидного** ответа (статус `empty_valid` vs `invalid`) — в логах/счётчиках, без лишних LLM-вызовов.
3. **`LLMError` первичной экстракции** (таймаут nano-gpt): делается **одна** попытка восстановления (retry-промпт) + fallback-парсер по доступному тексту; если восстановить нельзя — явная диагностика «потеряно» (не `LLM failed` без деталей).
4. **Не спамить:** не более одного WARNING на событие memorize (дедуп существующих двух WARNING); при повторяющихся сбоях — rate-limit (≤1/60с на chat+source) + агрегированные счётчики.
5. Крон-ветка `_extract_and_save_graph` **не ретраится агрессивно** (канон «деградация без потерь» сохраняется); получает только различение `[]` vs невалидный (диагностика).
6. Промпт-канон `FACT_EXTRACT_PROMPT` **не меняется** (байт-в-байт; F5 раунда 10.18).
7. Число LLM-вызовов не растёт сверх разумного (bounded); расход учитывается бюджетами F2/F3.
8. R17: сырой ответ LLM — только через `_mask_llm_raw`.

## 4. Технический дизайн

### 4.1. Различение статуса парсинга (`parse_fact_list_ex`)

```python
# services/summary_memory.py
PARSE_OK = "ok"            # есть факты
PARSE_EMPTY_VALID = "empty_valid"   # валидный [] — реально нет фактов
PARSE_INVALID = "invalid"  # не-список/кривой JSON/объект без списка
                           # ИЛИ валидный список без годных фактов (D-08)

def parse_fact_list_ex(raw, *, warn=True) -> tuple[list[dict], str]:
    """Толерантный парсер + статус. НИКОГДА не бросает. WARNING только
    для статуса invalid (оба подслучая — D-08) при warn=True (маскированный
    raw, R17); empty_valid → debug."""
def parse_fact_list(raw) -> list[dict]:     # совместимость API/тестов
    return parse_fact_list_ex(raw)[0]
```
- Поведение `parse_fact_list` сохраняется **байт-в-байт** по результату (тесты `test_graphrag_memory.py` — зелёные); добавляется только статус.
- **D-08 (ревью Батча A):** структурно валидный список с нулём годных фактов — тоже `invalid`, и при `warn=True` даёт WARNING (не тихий); в memorize-ветке `warn=False` (единый WARNING даёт `_log_memorize_lost`).

### 4.2. `_memorize_facts_inner` — не терять при `LLMError` первичной экстракции

Текущая структура: `raw = await self._extract_facts(tail)` (**может бросить**). Новая:
```python
raw, status = None, PARSE_INVALID
facts: list[dict] = []
try:
    raw = await self._extract_facts(tail)
except LLMError as exc:
    # промежуточный сигнал — debug; ЕДИНЫЙ WARNING на событие даёт
    # _log_memorize_lost (ADR-1019-7 D4 — не спамим)
    logger.debug("graphrag memorize: primary extract LLMError — trying "
                 "recovery | chat_id=%s | source=%s | error=%s",
                 chat_id, source_type, exc)
if raw is not None:
    facts, status = parse_fact_list_ex(raw)
    if not facts and status != PARSE_EMPTY_VALID:
        facts = _fallback_parse_facts(raw)
        status = PARSE_OK if facts else PARSE_INVALID
# ОДНА попытка восстановления: либо primary был invalid/empty → как F-15 §4.3,
# либо primary бросил LLMError → тот же retry-путь
if not facts and status != PARSE_EMPTY_VALID:
    retry_raw = await self._safe_retry(tail, chat_id, source_type)   # LLMError → None
    if retry_raw:
        facts, r_status = parse_fact_list_ex(retry_raw)
        if not facts:
            facts = _fallback_parse_facts(retry_raw)
    if facts:
        logger.info("graphrag memorize: recovered %d facts | …", len(facts))
    else:
        _log_memorize_lost(chat_id, source_type, status, raw)   # single WARNING, rate-limited
if not facts:
    if status == PARSE_EMPTY_VALID:
        logger.debug("graphrag memorize: empty valid list (no facts) | …")
    return
```
- `_safe_retry` — обёртка над одним вызовом `_FACT_RETRY_SYSTEM_PROMPT` с `except LLMError → None`.
- **Единый WARNING** на событие (`_log_memorize_lost`), rate-limited ≤1/60с на `(chat_id, source)`; повторные — `debug` со счётчиком. Убирает дубль «parse WARNING + retry WARNING».
- `memorize_facts` верхний уровень: `except LLMError` **становится fallback-веткой** (не «глушилкой»); сообщение — «lost after recovery» с причиной; при этом `_memorize_facts_inner` уже обработал восстановление, поэтому верхний хендлер — только страховка (unexpected).

### 4.3. Rate-gate и счётчики (не спамить)

```python
# module-level (D-06: bounded; D-07: None = «ещё не логировали»)
_MEMORIZE_WARN_STATE_MAX = 512
_memorize_warn_state: dict[tuple[int, str], float | None] = {}
_memorize_lost_totals: dict[tuple[int, str], int] = {}

def _log_memorize_lost(chat_id, source_type, status, raw) -> None:
    """WARNING ≤1/60с на (chat,source); статус/reason + маскированный raw;
    первое событие ВСЕГДА логируется (сентинел None, а не 0.0)."""
```
- **D-06/D-07 (ревью Батча A):** словари диагностики — bounded (эвикция старейших при вставке, `_MEMORIZE_WARN_STATE_MAX`), иначе рост по `(chat_id, source_type)` на весь срок процесса; «ещё не логировали» — `None` (не `0.0`), поэтому при uptime < 60 с первый WARNING не подавляется.
- Логируемые поля: `chat_id`, `source`, `status` (`invalid`), `reason` (`empty|not_json|llm_error`), `recovered=0`, `raw=_mask_llm_raw(raw)`.
- Прометей-подобных метрик нет — счётчики живут в логах (R17); при необходимости — аддитивно в health (F7).

### 4.4. Крон-ветка (не агрессивно)

`_extract_and_save_graph` (`:2945-2964`): `parse_triplets(raw)` — добавить различение «пусто валидно» vs «невалидно» в **лог** (info/debug), **без** дополнительных LLM-вызовов и **без** retry (канон F-15 §4.3 сохраняется). `EXTRACT_PROMPT` не трогаем.

## 5. Изменения схемы / каталога / env

- Схема: нет. **Каталог: Δ=0** (лимиты ретраев — существующие `limits.graph_memorize_*`). env: нет. Промпт-канон: не меняется.

## 6. Влияние на тесты

- `tests/test_graphrag_memory.py` (+):
  - `parse_fact_list_ex`: `"[]"` → `([], 'empty_valid')` **без WARNING**; `"мусор"`/`{…}` → `([], 'invalid')` + WARNING (substring «not a JSON list» сохранён); валидный список → `('ok')`;
  - `parse_fact_list` — регресс байт-в-байт по результату;
  - `_extract_facts` бросает `LLMError` → `_memorize_facts_inner` делает retry-промпт (mock LLM: ошибка → корректный JSON) → факты **записаны**; mock «ошибка → ошибка» → **один** WARNING «lost» + `[]` (не два);
  - rate-limit: два сбоя подряд → один WARNING + `debug`/счётчик;
  - `[]` от primary → **нет** retry-LLM-вызова (нет лишнего расхода) и нет WARNING;
  - **D-08 (ревью Батча A):** структурно валидный список без годных фактов → `invalid` + WARNING при `warn=True`; при `warn=False` — тихо (единый WARNING даёт `_log_memorize_lost`);
  - **D-06/D-07 (ревью Батча A):** словари диагностики bounded (`_MEMORIZE_WARN_STATE_MAX`); первое событие даёт WARNING даже при `monotonic()≈0.5` (uptime < 60 с);
  - R17: секрет-паттерн в raw замаскирован.
- `tests/test_direct_chat.py`: ответ бота не затронут (memorize — fire-and-forget).
- Полный `pytest` 0 failed; `git diff --check`; grep-проверка неизменности `plans/docs/canon/`.

## 7. Rollout / feature-flag / откат

- Feature flag не вводится (устойчивость парсинга). Rollback — `git revert`.
- Progressive delivery неприменимо; проверка на реальных логах memorize после деплоя (рост `recovered`, снижение `lost`).

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | **F-15 §4 (10.3)** уже предусмотрел fallback+retry | **AMEND** ADR-1019-7: расширяем на `LLMError` и `[]`; существующее не ломаем |
| R2 | Доп. вызовы увеличивают расход | Bounded (≤1 retry); нет лишнего вызова при `empty_valid`; бюджеты F2/F3 |
| R3 | Логирование raw может утечь контент | Только `_mask_llm_raw` (R17); аудит @Reviewer |
| R4 | Крон-ветка деградирует агрессивно | Явно: крон **без** retry (канон сохранён) |
| R5 | Соблазн правки промпта | Канон `FACT_EXTRACT_PROMPT` не трогать (байт-тесты) |
| R6 | nano-gpt timeouts — внешний фактор | Принимаем фолбэк deepseek-flash как штат; важно не терять после фолбэка |
| R7 | Пересечение с F7 по `summary_memory.py` | Согласованное вливание (F7 — retention, F8 — memorize) |
| R8 | Rate-limit «спрячет» реальную деградацию | Агрегированный счётчик в логе; `INFO` при восстановлении |

## 9. Открытые вопросы (рекомендации)

1. **Бюджет восстановления:** рекомендация — **не более 1** дополнительного LLM-вызова на memorize-событие (как F-15 §4.3), включая ветку `LLMError`.
2. **Rate-limit WARNING:** рекомендация — **60 с** на `(chat_id, source)` + агрегированный счётчик потерь.
3. **`[]` при primary:** рекомендация — **не** делать retry (валидный пустой ответ — не ошибка), только `debug`.
4. **Хранить ли счётчики recover/lost в health:** рекомендация — **фаза 2**, если F7 вводит health-расширение; в F8 достаточно логов.
