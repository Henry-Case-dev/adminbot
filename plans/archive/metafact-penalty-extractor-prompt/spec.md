# Spec F5 — `metafact-penalty-extractor-prompt` (канон-миграция экстрактора + программный хард-лимит importance)

> **Раунд:** 10.18 (Step 2 @Architect, **итерация 2 после human-gate**, 15.09.2026). **Тип:** backend (LLM-экстрактор/канон + `services/database.py`). **Приоритет:** P1.
> **ADR:** `adr-1018-5-metafact-penalty-canon-migration.md` (обязателен).
> **Задачи:** T-1742…T-1749. **Зависит:** F3 (общий STOP_LIST-модуль `services/graph_stoplist.py`). **Baseline:** HEAD `118a03c`; pytest 6007 passed.
> **Источник:** `plans/current_task.md` §4 (строки 77–87) + **UPD п.4** (строка 124).
> **Решение владельца (UPD п.4, «остальные решения — ДА»):** хард-лимит importance для мета-узлов = **1 (не 2)** — подтверждено «как есть»; STOP_LIST-состав, единый модуль и канон-миграция без изменений. Открытые вопросы §9 Q1/Q4/Q5 закрыты этим решением (значение 1, точное равенство, **фича-флаг не вводится** — пенализация безусловна, UPD п.2).

## 1. Контекст и цель

LLM-экстрактор охотно плодит мета-факты вида `[Субъект] → [отправил] → [видеосообщение]` с высокой важностью; RAG/Сон засоряются. Цель: (а) инструкция промпта «фокус на СУТИ/СОДЕРЖАНИИ, не формате»; (б) программный хард-лимит importance для стоп-лист-слов. Мета-факты **сохраняются**, но не проходят гейты Сна и не доминируют в RAG.

## 2. Текущее поведение (сверено с кодом)

- **Канон memorise-экстрактора** = `FACT_EXTRACT_PROMPT` (`services/summary_memory.py:109-118`) — **модульная константа** (не PG). Используется `_extract_facts` (`:1644-1690`) в fire-and-forget ветке `_memorize_facts_inner` (`:1694-1841`).
- Ретрай-промпт `_FACT_RETRY_SYSTEM_PROMPT` (`:134-139`) — тоже модульная константа (F-15).
- **Второй, другой** промпт: `EXTRACT_PROMPT` (`services/summary_prompts.py:71`), PG-ключ `prompts.extract_system_prompt` (`services/param_catalog.py:373-374`, `code_source=services.summary_prompts.EXTRACT_PROMPT`), используется кроном `_extract_and_save_graph` (`services/summary_memory.py:2905`). Он **не входит** в `PROMPT_MIGRATIONS` (`services/prompt_migrations.py:20-21,83`).
- **importance присваивает НЕ LLM**, а `rule_importance(origin, fact)` (`services/database.py:82-113`) при `importance=None`; явный `importance` → clamp 1..10 (`insert_graph_fact:1735-1736`). Значит «пенализация» — backend-override над уже вычисленным значением.
- Единая точка записи факта — `insert_graph_fact` (`services/database.py:1699-1760`), принимает **только** `fact` (строку `"{subject} {predicate} {object}"`), без subject/object.
- `_memorize_facts_inner` имеет `subject`/`obj` раздельно (`services/summary_memory.py:1788-1791`) и вызывает `insert_graph_fact(chat_id, sentence, source_type, expiry, …)` (`:1837-1841`).

## 3. Требуемое поведение

1. **Промпт (memorise-канон `FACT_EXTRACT_PROMPT`):** добавить инструкцию «фокусируйся на СУТИ/СОДЕРЖАНИИ, а не формате; извлекай факт отправки голосового/кружочка ТОЛЬКО при явном обсуждении формата; обычное сообщение — игнорируй формат». Оформить как канон-миграцию (PREV-слепок + байт-тесты).
2. **Хард-лимит:** если нормализованный `subject` **или** `object` факта строго равен слову `METAFACT_PENALTY_STOPLIST` (`видеосообщение, голосовое, фото, кружочек, ссылка, стикер`) → `importance = min(importance, PENALTY)` (значение **1**) независимо от `rule_importance()`/LLM.
3. Хард-лимит применяется **централизованно** в точке записи (не размазан по вызывающим).
4. Мета-факты сохраняются (не удаляются), но не проходят гейты Сна и не доминируют в RAG.
5. STOP_LIST — единый источник с F3 (`services/graph_stoplist.py`), без дублирования.

## 4. Технический дизайн

### 4.1. Канон-миграция (`services/summary_memory.py`)

- Сохранить байт-в-байт прежний текст как `PREV_FACT_EXTRACT_PROMPT`.
- Новый `FACT_EXTRACT_PROMPT` = прежний + аддитивный абзац:
  ```
  ФОКУС НА СОДЕРЖАНИИ:
  - Извлекай СУТЬ и СОДЕРЖАНИЕ сообщений, а не их формат.
  - Факт отправки «голосового», «кружочка», «видеосообщения», «фото», «ссылки»,
    «стикера» извлекай ТОЛЬКО если вокруг формата идёт явное обсуждение
    (например, кто-то ругается на спам голосовыми).
  - Обычное сообщение — игнорируй его формат.
  ```
- По **ADR-1013-3**: `FACT_EXTRACT_PROMPT` — модульная константа, **НЕ** PG-сид → `PROMPT_MIGRATIONS` **не трогается**, миграция = PREV-слепок + байт-тесты. (Промпт `prompts.extract_system_prompt`/`EXTRACT_PROMPT` — отдельный, вне скоупа F5 по умолчанию; см. §9 Q2.)
- Эталон добавить в `plans/docs/canon/backlog.md` (R46-2-раздел) — «эталон = код = тесты».

### 4.2. Программный хард-лимит (`services/database.py::insert_graph_fact`)

- Новые опциональные параметры: `subject: str | None = None, object: str | None = None` (аддитивно, дефолты → прежнее поведение).
- После вычисления `imp`:
  ```python
  from services.graph_stoplist import is_metafact_stopword, METAFACT_PENALTY_IMPORTANCE
  if is_metafact_stopword(subject) or is_metafact_stopword(object):
      imp = min(imp, METAFACT_PENALTY_IMPORTANCE)   # =1
  ```
  `METAFACT_PENALTY_IMPORTANCE = 1` — в `services/graph_stoplist.py`.
- В `_memorize_facts_inner` (`services/summary_memory.py:1837-1841`) передать `subject=subject, object=obj` в `insert_graph_fact`.
- Для путей, передающих только `fact` (крон, direct-reply) — хард-лимит не применяется в этом раунде (флаг/ограничение); либо best-effort: при `subject is None` разобрать первый токен до первого пробела и последний токен (осторожно; рекомендуется **не** делать — см. §9 Q3).
- Фича-флаг **не вводится**: срез применяется **безусловно** (UPD п.2; Δ=0).

### 4.3. Стоп-лист (`services/graph_stoplist.py`, общий с F3)

```python
METAFACT_PENALTY_STOPLIST = frozenset({
    "видеосообщение", "голосовое", "фото", "кружочек", "ссылка", "стикер"})
METAFACT_PENALTY_IMPORTANCE = 1
def normalize_token(value) -> str: ...   # casefold, strip, срез пунктуации, ё→е
def is_metafact_stopword(value) -> bool: ...
```
`GRAPH_CENTER_STOPLIST` (F3) — отдельный frozenset (содержит `сообщение`, не содержит `стикер`). Нормализация: `casefold`, strip, срез `.,!?;:«»"'()` по краям, `ё→е`; **строгое равенство** после нормализации.

### 4.4. Проверка «не проходят гейты Сна / не доминируют в RAG»

- Сон (`dream_worker`) читает кандидатов по `importance`-порогам — мета-факты с `importance=1` не проходят `importance_sum_threshold` (8/12) при типичном кластере.
- RAG-выборка основного пути (`_search_graph_facts`: FTS-фолбек и KNN) ранжируется по `weight`/`cosine` **× ограниченный множитель важности** `_importance_factor(imp) = 0.5 + 0.05·imp ∈ [0.55, 1.0]` (B4-1, вариант «а») — мета-факты (imp=1) внизу, важные (imp≥8) не вытесняются. Формулы `weight`/`cosine`/time-decay не меняются; `importance` добавлена в `SELECT` (`search_graph_facts_fts`, `get_graph_fact_records`). Подтверждено тестами `TestRagImportanceRanking`/`TestSleepGateBehavioral`.

## 5. Изменения схемы / каталога / env

- **DDL:** нет (clamp уже есть).
- **Каталог:** **Δ=0**. Стоп-лист — код-константа; **фича-флаг НЕ вводится** —
  пенализация применяется **безусловно** (решение владельца UPD п.2/п.4: «без
  флагов, базовая логика»; прецедент F3/ADR-1018-3 D7). Итог раунда:
  `REGISTRY 436 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 /
  TAB_RULES 19` (см. ADR-1018-6 D6).
- **env:** не трогать (`.env.example` — без изменений).
- Реализовано: `subject`/`object` — аддитивные параметры `insert_graph_fact`;
  срез централизован; другие пути (без subject/object) не покрыты (D2).

## 6. Влияние на тесты

- `tests/test_summary_memory.py` / новый `tests/test_metafact_penalty_round1018.py`: байт-канон + `PREV_FACT_EXTRACT_PROMPT ==` прежний текст (байт-в-байт); срез для стоп-лист subject/object; обычные факты не затронуты; мета-факты сохраняются.
- `tests/test_database.py`/`test_graphrag_database.py`: `insert_graph_fact(..., subject=…)` срез; без subject/object — прежнее поведение; clamp.
- `tests/test_dream_worker.py`/RAG: мета-факты (importance=1) не проходят гейт/не доминируют (смоук).
- `tests/test_prompt_migrations.py`: `PROMPT_MIGRATIONS` **не** содержит `FACT_EXTRACT_PROMPT` (не PG) и не содержит `prompts.extract_system_prompt` (не трогаем).
- Байт-тесты канона `plans/docs/canon/` — обновить эталон одним коммитом.
- Пин-тесты каталога — при Δ флага (см. §5).
- Полный `pytest` 0 failed; R17-скан; `git diff --check`.

## 7. Rollout / feature-flag / откат

- **Флаг не вводится:** срез применяется **безусловно** (базовая логика, UPD
  п.2; прецедент F3/ADR-1018-3 D7). При `subject`/`object`=None —
  `insert_graph_fact` байт-в-байт прежний.
- Стадии: internal → контроль RAG на одном чате → полный раскат (флага нет).
- Rollback: `git revert` (канон-миграция + срез одним коммитом; данные
  безвредны — мета-факты всего лишь имеют importance 1).

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Конфликт с ADR-1013-3 («канон R46-2 байт-в-байт») | PREV-слепок + байт-тесты + эталон; `PROMPT_MIGRATIONS` не трогаем |
| R2 | ТЗ «importance присваивает LLM» неверна | Хард-лимит как override над `rule_importance()` + clamp (`database.py:1735-1736`) |
| R3 | Разночтение стоп-листов §3.1 (centers) и §4 (penalty) | Разные frozenset в `graph_stoplist.py`; явно в ADR/spec |
| R4 | Срез обнулит полезные наблюдения | «Строго равенство» после нормализации + значение 1 (не 0/удаление); промпт разрешает явное обсуждение |
| R5 | Слом байт-тестов канона | PREV + обновление эталона одним коммитом |
| R6 | `services/database.py` делится с F3 | Согласованное вливание; единый свод тестов |
| R7 | Хард-лимит не покрывает пути без subject/object | Осознанное ограничение (memorise-путь); §9 Q3 |

## 9. Открытые вопросы

**Принято владельцем (UPD п.4, «остальные решения — ДА»; не переоткрывается):**
- **Значение среза = 1** (гарантированно ниже гейтов Сна). Q1 закрыт.
- **Точное равенство после нормализации** (без падежных форм). Q4 закрыт.

Осталось уточнить (@Builder при реализации, не блокирует):
1. **Обновлять ли также `EXTRACT_PROMPT`/`prompts.extract_system_prompt` (крон-экстрактор)?** → **Рекомендация:** в этом раунде **нет** (tasks.md/T-1743 называют `FACT_EXTRACT_PROMPT`); если владелец хочет полное покрытие — отдельная канон-миграция PG-промпта с `PROMPT_MIGRATIONS`-ступенью (без Δ каталога).
2. **Применять ли хард-лимит к путям без subject/object (крон/direct)?** → **Рекомендация:** нет (футуристичный парсинг строки ненадёжен); ограничиться memorise-путём; иначе — отдельная задача.
3. **Флаг `flags.metafact_penalty_enabled`** — **НЕ вводится** (решение владельца UPD п.2: «никаких фича-флагов, базовая логика»; прецедент F3/ADR-1018-3 D7). Δ каталога раунда = 0. Q3 закрыт.
