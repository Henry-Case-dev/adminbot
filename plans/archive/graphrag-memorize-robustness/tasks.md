# Фича F8 — `graphrag-memorize-robustness` (Устойчивость парсинга фактов: не терять факты молча; связь с nano-gpt timeout)

> **Статус: ⏳ PLANNED** (Step 1 @PM, 15.09.2026). Реализация — @Builder (T-1846…T-1851); гейт T-1845 (@Architect) / T-1852 (@Reviewer/@PM).
> **Spec/ADR:** создаёт @Architect — `spec.md` + **ADR-1019-7** (**AMEND F-15 §4** раунда 10.3 `direct-sandbox-budget-investigation`, часть «graphrag memorize JSON list»).
> **Раунд:** 10.19 (UPD2, `plans/current_task.md:130-175`). **Нумерация:** T-1845…T-1852.
> **Тип:** backend (`services/summary_memory.py`, `services/llm_client.py`-таймауты). **Приоритет:** **P1** (память «жрёт мусор и не запоминает»).
> **Зависимости:** **F7** (смежность — диагностика памяти). **Конфликт файлов:** `services/summary_memory.py` (F7 при сжатии/retention).
> **ТЗ:** UPD2 **п.6** (строка 160): «nano-gpt отваливается по таймауту, три ретрая в молоко, фолбэк deepseek-flash; модель отвечает невалидным жидким ответом, graphrag пытается это за Memorize и просто скипает, потому что пришёл не json, а пустой список; два раза подряд; память жрёт мусор и не запоминает нихрена».
> **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/406/411/90/88/19**; SQLite **v10**; APP_VERSION 2.57.0.

## 0. Цель

Сделать извлечение фактов GraphRAG **устойчивым**: невалидный/пустой ответ LLM не должен приводить к **молчаливой потере** фактов; должны работать ретраи/фоллбэк-парсер и **диагностика** (что именно вернула модель). Учесть связь со сбоями nano-gpt по таймауту (три ретрая + фоллбэк на deepseek-flash).

**Требуется (UPD2 п.6, строка 160):**
- При невалидном/пустом ответе — **не терять факты молча**.
- Ретраи/фоллбэк-парсер работают в **обеих** ветках (включая ошибку LLM, а не только «не JSON»).
- Диагностика: видно, что вернула модель (маскированно, R17) и почему факты не записаны.
- Таймауты nano-gpt — принять как внешний фактор; фоллбэк (deepseek-flash) работает; при этом не терять факты.

## 1. Доказательства / карта кода (HEAD `fd6acc7`)

- `services/summary_memory.py:496-539` — `parse_fact_list`: толерантный парсер (code-fence, dict-со-списком); при **не-списке** — WARNING «LLM answer is not a JSON list — skipped» + `_mask_llm_raw(raw)`; капсы.
  - **Нюанс:** валидный **пустой список `[]`** возвращает `[]` **без** WARNING (не отличим от «ничего не нашлось»).
- `services/summary_memory.py:568-639` — `_fallback_parse_facts` (фоллбэк-парсер прозы/буллетов).
- `services/summary_memory.py:1707-1728` — `_extract_facts`: bounded-ретраи **только** для `LLMError` (промпт `FACT_EXTRACT_PROMPT`); при исчерпании — `raise exc`.
- `services/summary_memory.py:1730-1773` — `_memorize_facts_inner`: `parse_fact_list` → `_fallback_parse_facts` → **один** ретрай `_FACT_RETRY_SYSTEM_PROMPT` → снова parse/fallback; при нуле фактов — `logger.info("graphrag memorize: 0 facts")` + return.
- `services/summary_memory.py:1677-1705` — `memorize_facts`: `except LLMError` → WARNING «LLM failed» (**факты теряются**, фоллбэк/ретрай не применяются), `except Exception` → `logger.exception` «unexpected failure».
- **Gap:** если `_extract_facts` исчерпал ретраи и бросил `LLMError` → `memorize_facts` ловит его на верхнем уровне **без** попытки fallback-пути (таймаут nano-gpt = молчаливая потеря фактов).
- Таймауты провайдеров: `services/llm_client.py` (nano-gpt timeout → ретраи → фоллбэк deepseek-flash) — поведение принимается; важно не терять факты **после** успешного фоллбэка.

## 2. Требования

- [x] Невалидный/пустой ответ LLM → факты **не теряются молча**: применяются fallback-парсер и/или ретрай; если восстановить нельзя — явная диагностика (WARNING) с маскированным фрагментом.
- [x] Различать: **валидный пустой список** (`[]` — реально нет фактов) vs **невалидный ответ** (нужен фоллбэк/ретрай).
- [x] Ошибка LLM на первичном `_extract_facts` (таймаут nano-gpt) → попытка fallback/повторного извлечения в fire-and-forget ветке (не только «LLM failed»).
- [x] Диагностика: логи «невалиден/пуст/восстановлено N/потеряно» — R17-safe (маскирование raw через `_mask_llm_raw`), rate-limited.
- [x] Не увеличивать число LLM-вызовов сверх разумного (bounded-ретраи сохранены; +≤1 recovery-retry; бюджеты F2/F3 учитываются).
- [x] Крон-ветка `_extract_and_save_graph` — без ретраев (канон «деградация без потерь» сохранён; добавлено только различение `[]`/невалид в лог).

## 3. Constraints (инварианты раунда)

- **Канон промптов**: `FACT_EXTRACT_PROMPT` (R46-2 + F5-абзац ADR-1018-5) — **байт-в-байт**; правка промпта только через `PROMPT_MIGRATIONS`/PREV-слепок (ADR-1013-3). В этой фиче промпт-канон не менять (только логика парсинга/ретраев).
- **R17:** сырой ответ LLM логировать только маскированно (`_mask_llm_raw`).
- **R16** — аддитивные поля/счётчики.
- **Каталог:** Δ=0 (лимиты ретраев — существующие ключи `limits.graph_memorize_*`).
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** T-1845 (@Architect, ADR-1019-7, AMEND F-15 §4).
- **Смежность:** **F7** (здоровье памяти/`smart_messages`) — свести диагностику и тесты.
- **Порядок:** может идти параллельно F1/F5/F6; с F7 — согласованное вливание `summary_memory.py`.

## 5. Definition of Done

- [x] Невалидный/пустой ответ не приводит к молчаливой потере фактов (есть фоллбэк/ретрай/явная диагностика).
- [x] Таймаут nano-gpt (LLMError) обрабатывается так, что после успешного фолбэка факты **записываются**; при неудаче — диагностика понятна (`facts lost | reason=llm_error`).
- [x] Валидный пустой список отличается от невалидного ответа (`empty_valid` vs `invalid`).
- [x] Диагностика R17-safe; bounded-ретраи не раздувают расход (+≤1 recovery-retry; `[]` — без ретрая).
- [x] Полный `pytest` **0 failed** (6155 passed; **6164** после ревью-фиксов D-06…D-08); каталог Δ=0; `git diff --check` clean.

## 6. Чек-лист задач

- [x] **T-1845 (@Architect, гейт):** `spec.md` + **ADR-1019-7** — политика устойчивости извлечения фактов: различение `[]` vs невалидный ответ, место fallback/ретрая при `LLMError` первичного извлечения, границы ретраев (fire-and-forget vs крон), формат диагностики (счётчики/логи, R17), **AMEND F-15 §4**.
- [x] **T-1846 (@Builder):** `LLMError` первичного `_extract_facts` перехватывается внутри `_memorize_facts_inner` + один recovery-retry (`_safe_retry`) + fallback; верхний `memorize_facts` — только страховка («facts lost after recovery»).
- [x] **T-1847 (@Builder):** `parse_fact_list_ex` → `ok`/`empty_valid`/`invalid`; `parse_fact_list` — совместимая обёртка; `empty_valid` не ретраится (без лишнего расхода).
- [x] **T-1848 (@Builder):** bounded-ретраи сохранены (`limits.graph_memorize_*`); добавлен ровно один recovery-retry; `[]` — без вызова.
- [x] **T-1849 (@Builder):** `_log_memorize_lost` — единый rate-limited (≤60с на chat+source) WARNING со `status`/`reason`/`lost_total`/маскированным raw; восстановление — INFO recovered.
- [x] **T-1850 (@Builder):** тесты — невалидный ответ, `[]`, проза/буллеты, `LLMError` первичного извлечения, восстановление через ретрай, двойной провал = один WARNING, rate-limit, R17-маскирование.
- [x] **T-1851 (@Builder):** гейты — полный `pytest` **6155 passed / 0 failed**; каталог Δ=0; `git diff --check` clean.
- [x] **T-1853 (@Builder, ревью Бата A — D-06…D-08):** D-06 — модульные словари диагностики `_memorize_warn_state`/`_memorize_lost_totals` bounded (`_MEMORIZE_WARN_STATE_MAX=512`, эвикция старейших при вставке); D-07 — сентинел `None` вместо `0.0` («ещё не логировали») → первое событие ВСЕГДА даёт WARNING при любом uptime; D-08 — структурно валидный список без годных фактов (`invalid`) тоже эмитит маскированный WARNING при `warn=True` (в memorize-ветке `warn=False` — без дубля); ADR-1019-7 D1/D4 + spec §4.1/§4.3 синхронизированы. Гейты: pytest **6164 passed / 0 failed**; `git diff --check` clean.
- [ ] **T-1852 (@Reviewer + @PM, гейт):** сверка DoD; проверка «нет молчаливой потери»; согласованность ADR-1019-7 ↔ код; R17-аудит; повторное ревью фиксов D-06…D-08.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **F-15 §4 (10.3)** уже предусмотрел fallback+retry (не JSON) | **AMEND**: расширить на `LLMError`/пустой список; не ломать существующее |
| R2 | Доп. ретраи увеличивают расход/нагрузку | Bounded-ретраи; бюджеты F2/F3; ADR-лимиты |
| R3 | Логирование raw может утечь контент | Только `_mask_llm_raw` (R17); @Reviewer-аудит |
| R4 | Крон-ветка не должна деградировать агрессивно | ADR фиксирует: fire-and-forget vs крон |
| R5 | Правка промпта соблазнительна, но канон запрещён | Промпт не трогать; только парсинг/ретраи |
| R6 | Связь с nano-gpt timeouts — внешняя | Принять фоллбэк (deepseek-flash) как штат; фиксировать в доке |
| R7 | Пересечение с F7 по `summary_memory.py` | Согласованное вливание |

**ADR:** требуется новый **ADR-1019-7** (AMEND F-15 §4 10.3).

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (устойчивость парсинга). Rollback — `git revert`.
- **Progressive delivery:** неприменимо; проверка на реальных логах memorize после деплоя.

## 9. Handoff / деплой

`@Orchestrator` — план F8 готов. Spec/ADR — T-1845 (@Architect). Реализация — T-1846…T-1851 (@Builder). **Деплой (SSH + рестарт + live-проверка логов GraphRAG memorize) — @DevOps. Секреты в репозитории НЕ хранятся.**
