# ADR-1018-5 — Метафакт-пенализация: канон-миграция `FACT_EXTRACT_PROMPT` + программный хард-лимит importance

- **Статус:** Proposed (**обновлён после human-gate, итерация 2** — 15.09.2026; решения подтверждены «как есть»)
- **Дата:** 2026-09-15
- **Раунд:** 10.18, фича F5 `metafact-penalty-extractor-prompt` (T-1742)
- **База:** HEAD `118a03c`.
- **AMEND:** **ADR-1013-3** (политика правки промпт-канонов) — не supersede, а применение §2 к `FACT_EXTRACT_PROMPT`: модульная константа → PREV-слепок + байт-тесты, `PROMPT_MIGRATIONS` **не трогается**. Дополнительно явно фиксируется, что `FACT_EXTRACT_PROMPT` (memorise) и `EXTRACT_PROMPT`/`prompts.extract_system_prompt` (крон) — **разные** промпты.
- **Связано:** ADR-1018-3 (общий STOP_LIST-модуль `services/graph_stoplist.py`).

## Context

1. **ТЗ §4 неточно трактует механику:** «importance присваивает LLM». В коде `importance` считает `rule_importance(origin, fact)` (`services/database.py:82-113`) при `importance=None`; явный — clamp 1..10 (`:1735-1736`). Значит пенализация — **backend-override**, а не «уговорить LLM».
2. **Промпт-экстрактор — модульная константа**, а не PG-сид: `FACT_EXTRACT_PROMPT` в `services/summary_memory.py:109-118` (канон R46-2 байт-в-байт). Есть **второй**, другой промпт `EXTRACT_PROMPT` (`services/summary_prompts.py:71`, PG `prompts.extract_system_prompt`), используемый кроном `_extract_and_save_graph` (`summary_memory.py:2905`).
3. **Единая точка записи** — `insert_graph_fact` (`services/database.py:1699-1760`), принимает только строку `fact`; `subject`/`object` есть только в `_memorize_facts_inner` (`summary_memory.py:1788-1791`).
4. **Два разных стоп-листа:** §3.1 (centers) = `видеосообщение, голосовое, сообщение, фото, кружочек, ссылка`; §4 (penalty) = `видеосообщение, голосовое, фото, кружочек, ссылка, стикер`.
5. ADR-1013-3 §2 предписывает для модульных канонов PREV+байт-тесты, `PROMPT_MIGRATIONS` — no-op. Это **снимает** формулировку tasks.md «PREV + PROMPT_MIGRATIONS» (для этого канона).

## Decision

### D1. Канон-миграция `FACT_EXTRACT_PROMPT` = PREV + байт-тесты (без PG)
Сохранить прежний текст как `PREV_FACT_EXTRACT_PROMPT` (байт-в-байт), новый `FACT_EXTRACT_PROMPT` — аддитивный абзац «ФОКУС НА СОДЕРЖАНИИ». `PROMPT_MIGRATIONS` **не трогается** (константа не PG-сид). Эталон — `plans/docs/canon/backlog.md`. Промпт `prompts.extract_system_prompt`/`EXTRACT_PROMPT` в этом раунде **не** меняется (см. Open Questions).

### D2. Программный хард-лимит — в единой точке записи
`insert_graph_fact` += опциональные `subject`/`object`; после `imp`:
```python
if is_metafact_stopword(subject) or is_metafact_stopword(object):
    imp = min(imp, METAFACT_PENALTY_IMPORTANCE)  # = 1
```
Вызывающий (`_memorize_facts_inner`) передаёт `subject`/`object`. Прочие пути (без subject/object) в этом раунде не покрываются (осознанное ограничение). Централизация — в `insert_graph_fact`, а не в вызывающих (ТЗ: «middleware перед сохранением»).

### D3. Значение среза — 1 (не 2, не 0) — **подтверждено владельцем (UPD п.4)**
`METAFACT_PENALTY_IMPORTANCE = 1`: гарантированно ниже гейтов Сна (`importance_sum_threshold` 8/12) и внизу RAG-ранга. Факты **сохраняются** (не 0/удаление) — для статистики/шуток.

### D4. Семантика «строго равен» — нормализация
`normalize_token()`: casefold, strip, срез краевой пунктуации, `ё→е`; далее **точное** равенство элементу frozenset. Падежные формы **не** расширяются (риск ложных срезов). Нормализация — общий хелпер в `services/graph_stoplist.py`.

### D5. Два стоп-листа — два frozenset, один модуль
`GRAPH_CENTER_STOPLIST` (F3, содержит `сообщение`, без `стикер`) и `METAFACT_PENALTY_STOPLIST` (F5, содержит `стикер`, без `сообщение`) — **разные** множества в одном `services/graph_stoplist.py`. Дублирования нет; различия явные (комментарий в модуле + тест).

### D6. Фича-флаг НЕ вводится — пенализация безусловна
**Итерация 3 (реализация T-1743…T-1747):** фича-флаг `flags.metafact_penalty_enabled`
**не вводится**. Решение владельца (UPD п.2: «никаких дополнительных фича-флагов
(default OFF)... это должно стать новым стандартом») + прецедент F3
(ADR-1018-3 D7: флаг снят, поведение безусловно). Поэтому Δ каталога от F5 = 0
(`REGISTRY`/`Settings` без изменений; свод — ADR-1018-6 D6). Откат — `git revert`
канон-миграции и среза одним коммитом.

### D7. Evidence: сохранение фактов и не-доминирование (B4-1 — вариант «а»)
**Итерация 4 (после ревью Батча 4, B4-1).** Мета-факты с `importance=1` не
проходят пороги Сна и находятся внизу RAG-сортировки.

Уточнение по итогам ревью: жёсткий срез `importance` в `insert_graph_fact`
сам по себе НЕ влиял на **основной** RAG-путь — `_search_graph_facts`
ранжировал только по `_effective_weight(weight, last_confirmed_at, now)`
(для `chat_history` weight=0.5), а `importance` участвовал лишь в
`search_golden_facts_fts` (SQL-фильтр `importance >= min_importance`).
Таким образом цель §4 «мета-факты не перебьют важные в RAG-выборке» для
основного RAG не достигалась.

**Решение (вариант «а», предпочтительный):** в ранжирование основного RAG
введён **ограниченный множитель важности**
`_importance_factor(importance) = 0.5 + 0.05·imp`, `imp=clamp(1..10)` →
диапазон `[0.55, 1.0]`. Применяется в обеих ветках `_search_graph_facts`:
FTS-фолбек (`w_eff × factor`) и KNN (`cosine × w_eff × factor`);
`f.importance` добавлен в `SELECT` `search_graph_facts_fts` и
`get_graph_fact_records` (аддитивно). Свойства:
- детерминированно: при прочих равных мета-факт (`imp=1`, factor 0.55)
  уступает важному (`imp≥8`, factor `≥0.9`);
- множитель монотонный и ограниченный: равные `importance` не меняют
  относительный порядок по `weight/cosine`; диапазон 1.82× не позволяет
  важности «сломать» базовое взвешивание целиком.
Формулы `weight`/time-decay/`cosine` **не меняются** — importance входит
только множителем. Тесты: `tests/test_metafact_penalty_round1018.py::
TestRagImportanceRanking` (FTS и KNN, контроль «важный не вытеснен»,
границы/монотонность множителя) + `TestSleepGateBehavioral` (реальный гейт
Сна, B4-2).

## Consequences

**Positive**
- Экстрактор меньше плодит формат-мусор (промпт) + жёсткая страховка (import=1).
- Мета-факты остаются в БД, но не засоряют Сон/RAG.
- Дисциплина канона (PREV+байты) сохранена; `PROMPT_MIGRATIONS` нерасширен.
- Стоп-лист переиспользуется F3 (единый источник, нет дрейфа).

**Negative**
- Хард-лимит покрывает только memorise-путь (без subject/object другие пути не затронуты) — потенциальная неполнота.
- Рост объёма `FACT_EXTRACT_PROMPT` — незначительная цена токенов.
- Падежные формы («ссылку», «фотку») не ловятся точным равенством — возможны пропуски.
- Пенализация безусловна (нет runtime-выключателя) — откат только `git revert`; митигируется безвредностью данных (importance=1) и точным равенством стоп-листа.

## Alternatives

- **A1. Править промпт и ожидать, что LLM сама снизит importance.** Отклонено: importance не от LLM; недетерминировано.
- **A2. Добавить `FACT_EXTRACT_PROMPT` в PG-каталог + `PROMPT_MIGRATIONS`.** Отклонено: смена прецедента Q10/ADR-1013-3, лишний Δ, не требуется ТЗ.
- **A3. Срез в вызывающих (`_memorize_facts_inner`).** Отклонено: не централизовано; ТЗ требует «middleware перед сохранением».
- **A4. Значение 0 / удаление факта.** Отклонено: ТЗ требует сохранить (статистика/шутки); 0 нарушил бы clamp 1..10.
- **A5. Расширенный лемматизированный стоп-лист (падежи).** Отклонено в этом раунде: рост ложных срезов; кандидат отдельной задачи.
- **A6. Патчить одновременно `EXTRACT_PROMPT` (крон).** Отложено (Open Question Q2): другой промпт/путь, отдельная канон-миграция.

## References

- `services/summary_memory.py:109-118,134-139,1644-1690,1694-1841,2905`
- `services/database.py:82-113,1699-1760`
- `services/summary_prompts.py:71`; `services/param_catalog.py:373-374`; `services/prompt_migrations.py:20-21,83`
- ADR-1013-3 (`plans/archive/cognition-4d-memory-round1013/adr-1013-3-prompt-canon-policy.md`); ADR-1018-3 (общий `services/graph_stoplist.py`)
- Задачи: T-1742 (ADR/spec), T-1743 (промпт+PREV), T-1744 (хард-лимит), T-1745 (единый стоп-лист), T-1746 (Сон/RAG), T-1747 (тесты), T-1748 (гейты), T-1749 (@Reviewer/@PM).
