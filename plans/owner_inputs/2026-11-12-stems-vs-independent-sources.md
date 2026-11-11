# Owner input — развести `stems_shared` и `independent_sources` (2026-11-12)

- Origin: root chat, 2026-11-12 00:47 (+12:00). Уточнение к `VMQ-NEXT-04` и к исправлению диагностических данных памяти.
- Kind: correction (уточняет семантику уже поставленной работы; не отменяет её).
- Target task: `vmq-onto-01`.

## Verbatim instruction

> Уточнение по `VMQ-NEXT-04` и исправлению диагностических данных памяти.
>
> Не смешивайте два разных понятия:
>
> 1. **`stems_shared`** — количество общих основ слов между запросом и воспоминанием. Это метрика лексической релевантности.
> 2. **`independent_sources`** — независимые первоисточники, подтверждающие конкретное утверждение. Это метрика происхождения и доказательности.
>
> Добавьте `stems_shared` в структурированный результат поиска и диагностическую трассу. Вычисляйте его в существующем механизме `_rag_subject_shared()`, передавайте в JSON/API/отчёт из одного источника данных. Если значение не вычислялось — `null` с причиной, а не фиктивный ноль. Для этого не требуется новая колонка БД.
>
> **Критически важно:** исходное требование о «двух основах» могло относиться именно к основам слов, а не к двум независимым подтверждениям. Восстановите точную семантику из первоначального ТЗ и реализации. Не переопределяйте критерий приёмки задним числом.
>
> Независимость источников проверяйте отдельно, по реальному происхождению записей. Не делайте два подтверждения обязательными для хранения или извлечения любого воспоминания.
>
> Существующие пороги, семантику отбора, эмбеддинги и пользовательские настройки не меняйте в рамках диагностического исправления.
>
> Текущую работу не останавливайте, отдельного согласования не требуется. В отчёте кратко покажите, какой исходный смысл `VMQ-NEXT-04` установлен и откуда теперь берутся обе метрики.

## Established original semantics (verified from the project's own sources)

- `plans/features/vmq-onto-01/evidence/vmq-mem/next-stage-design.md` §2, line 31: «Лексическая строка входит, только если вопрос и текст делят **≥2** разных основы: `_TOKEN_RE` + существующий `stem_word`, длина основы ≥4». Line 40 repeats that the lexical line passing §2 is not sent to the rerank. Line 45 gives the counter-case: the only overlap is the word «сейчас», one stem, so §2 does not admit it.
- Therefore «порог двух основ» in `VMQ-NEXT-04` means **≥2 distinct word stems shared between the question and the row text**, and it is a condition for admission of a LEXICAL FILL row. A row that did not come through the lexical fill is judged by the reranker, so the threshold does not apply to it.
- The map's acceptance sentence for `VMQ-NEXT-04` ("C2 под auto не содержит ни одной строки, не прошедшей порог двух основ") is therefore correctly read as "no row admitted by the lexical fill has fewer than two shared stems" — not "no row in the block has fewer than two shared stems". The wording comes from design §2, not from the owner's source line `MAN-NEXT-04`, whose excerpt is about preserving conflicting versions.
- `independent_sources` is a separate provenance metric over real record origin; it must not be used as the "two foundations" threshold, and two confirmations must not become mandatory for storage or retrieval.
