# Anti-hardcode механический аудит — candidate `76fcb829`

**Назначение.** Фиксирует воспроизводимый механический скан diff'а кандидата как
вспомогательное доказательство инварианта owner input §1/§8.3. Это **не** независимый
аудит Reviewer и не замена ему: решающий аудит фактического production-пути и
собственные unseen-формулировки — в `review-core-76fcb829.md`.

- Candidate: `76fcb82962592a8e099239cd11e6c34ff13cf407`; base: `234776589c934024ed0e8dceba189fb9d70d3215`.
- Проверенная поверхность: `services/ handlers/ bot.py config/ web/` (product-код; тесты и docs исключены из этого скана).
- Инструмент: локальный `git diff -U0 <base> <cand>` + построчный скан добавленных строк; Python 3.12, UTF-8.

## 1. Что искалось

Запрещённые owner input §1.2 механизмы определения намерения по естественному тексту:
регулярки; `startswith`/`endswith`/substring/`in text`; списки ключевых слов, синонимов,
фраз; лексические классификаторы/scoring; словари «фраза → инструмент»; скрытые
fast path / pre-router / fallback router по словам.

## 2. Результат скана

| Проверка | Результат |
|---|---|
| Изменённые product-файлы | 11: `bot.py`, `handlers/checkup.py`, `services/chat_prompts.py`, `services/checkup_prompts.py`, `services/checkup_service.py`, `services/database.py`, `services/direct_capabilities.py`, `services/direct_chat_service.py`, `services/direct_l1.py`, `services/source_reader.py`, `services/tool_router.py` |
| Добавленные строки (`+`, без `+++`) | 670 |
| Новые `import re` / `re.compile` в добавленных строках | **0** |
| Новые присваивания `KEYWORDS|PHRASES|SYNONYMS|_words|TRIGGERS =` | **0** |
| Строки, содержащие `re.`/`regex`/`startswith`/`endswith`/`in text`/`in message`/`in query`/`contains(`/`synonym`/`scoring`/`keyword`/`trigger` | **1** — ложное срабатывание |
| Условия по пользовательскому тексту (`if/elif/while/and/or` + `message|user_text|text|query|question|prompt`) | **1** — та же строка-ложное срабатывание |

Единственное срабатывание:

```python
texts = [text for text in texts if text]
```

Это фильтрация пустых элементов списка (list comprehension), без сопоставления
естественного текста с намерением/инструментом. Других совпадений нет.

## 3. Содержательная проверка маршрута (по коду кандидата)

- `services/direct_l1.py`: `DIAGNOSTIC_TARGETS`/`DIAGNOSTIC_SOURCES` — **закрытые** множества;
  `normalize_diagnostic_research` разбирает только типизированное поле; отсутствие/невалид
  → «не установлено»; `needed` — строгий `True`; неизвестный источник отбрасывается.
  `DIAGNOSTIC_SOURCE_CAPABILITY` сопоставляет **имя источника из решения модели**
  существующей capability (`runtime/journal → deep_diagnostics`, `source_code → source_code`,
  `memory → chat_memory`) и не содержит пользовательских фраз.
- `diagnostic_source_capabilities`: `needed=false`/`None` → `()`; `target in {unknown, other}`
  → инструмент не объявляется; при `needed=true` без источников объявляются оба существующих
  read-only инструмента (объявление, не вызов).
- Контекст отчёта выбирается по структурному признаку `output_kind="checkup_report"`, не по словам.
- Канонический repo origin подставляется сервером только после `target=self`; для внешнего
  объекта — обычный SourceReader-flow.
- Prompt-дополнения (`services/chat_prompts.py`, `services/checkup_prompts.py`) — семантические
  правила (цитата/пересказ, объяснение уже полученных данных, продолжение отчёта, «не читай
  ради счётчика»). Таблиц «фраза → инструмент» нет. Иллюстративные примеры в скобках
  («что значит…», «объясни…») описывают смысловую категорию, а не маршрут; какие-либо
  последствия для выбора инструмента задаёт только типизированное решение модели.

**Гигиена тестовых формулировок (§8.2).** Все 10 формулировок из builder-набора
(включая `neg_external`, `neg_quoted`, `neg_explain_received`) проверены в добавленных
product-строках: **0 вхождений**. Формулировки живут только в тестовых входных данных.

## 4. Границы

- Скан механический: он показывает отсутствие новых лексических механизмов в diff'е, но
  не доказывает семантику — это делает Reviewer по фактическому маршруту
  (`review-core-76fcb829.md`), включая собственные unseen/adversarial формулировки.
- Скан не покрывает исторические (не изменённые) ветки кода; они уже были предметом
  предыдущих приёмок SELF-DIAG-01 (SD1-SEM-*, SD1-AC-05).
- Production-путь и production-модель этим документом не проверялись.
