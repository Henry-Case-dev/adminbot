# Owner input — дефект доказательной базы: основания в отчёте, но не в JSON (2026-11-12)

- Origin: root chat, 2026-11-12 00:40 (+12:00). Trigger: my report that the per-row `stems_shared` list exists only in the measurement report text and not in the machine-readable dump.
- Kind: correction (a defect inside the current task, explicitly NOT a reason to rebuild memory).
- Target task: `vmq-onto-01` (memory next stage evidence), with effect on any agent-produced evidence artefact.

## Verbatim instruction

> Обнаружен дефект доказательной базы: основания решений присутствуют в текстовом отчёте, но отсутствуют в машиночитаемом JSON.
>
> Найди первопричину в существующем механизме формирования, сериализации и сохранения результатов. Проверь схему JSON, преобразование объектов, запись, повторное чтение, возможные перезаписи и расхождение между worktree.
>
> Требования:
>
> 1. Сведения об основаниях должны сохраняться структурированно, с идентификаторами первичных источников, происхождением и связью с соответствующим воспоминанием/решением.
> 2. Текстовый отчёт и JSON должны формироваться из одних подтверждённых данных. Нельзя допускать, чтобы отчёт содержал доказательства, отсутствующие в сохраняемом состоянии.
> 3. Независимость двух оснований должна проверяться по происхождению источников, а не по количеству фрагментов или текстовых совпадений.
> 4. Исправь уже существующие записи с потерянными основаниями там, где их можно достоверно восстановить. Не придумывай недостающие доказательства и не помечай неподтверждённое как VERIFIED.
> 5. Проверь полный цикл: формирование → запись JSON → повторное чтение → проверка независимости → восстановление после перезапуска.
> 6. Не меняй архитектуру памяти и критерии приёмки без доказанной необходимости. Не создавай параллельное хранилище или новый механизм отчётности.
>
> Это дефект сохранения доказательств в рамках текущей задачи, а не повод переделывать всю память.
>
> После исправления Reviewer должен независимо подтвердить, что фактический JSON содержит необходимые основания и они переживают перезапуск процесса.

## What was found before the fix (my own verification, kept as history)

- `git grep stems_shared c087253d -- services` and the same on master return nothing: the product never writes that key, so the harness line `"stems_shared": row.get("stems_shared")` always stored `null` while the report stated concrete numbers. A silent `.get()` default turned a missing ground into an apparently valid empty value.
- `services/experience_diagnostics.py::_learning_analytics` selects `status, temporal_rank, confirmation_count, origin_kind, last_validated_at` from `mca_lessons` and returns only aggregates, so per-lesson `independent_sources` never reaches that JSON.
- Selection of a period row is grounded by `_rag_subject_shared(query_stems, fact) >= threshold` (services/direct_chat_service.py:3470, used at :13909) - textual stem overlap. The only provenance test nearby is `_prov.is_self_referential_origin(...)` in `_rag_append_period_rows` (:13921). Lexical overlap is relevance, not independence of grounds; the persisted ground record must carry provenance and independence must be computed from it with the existing primitive.
