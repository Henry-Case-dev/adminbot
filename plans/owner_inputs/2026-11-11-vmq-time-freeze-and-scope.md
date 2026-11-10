# Owner input — 2026-11-11: freeze VMQ-TIME, independent evaluation, no per-test patching

- Origin: root chat message, 2026-11-11 (local time 00:2x UTC+12), following the inspector/memory review reports.
- Kind: amendment (scope and process correction), not a new epic.
- Affected tasks: `vmq-onto-01` (VMQ-MEM-TIME slice), `unified-reply` (UR-F inspector slice and UR-07.3 source dates as independent works).
- Note: the owner's previous decision "release 2.58.180 is finished" is restated; VMQ-TIME must not be mixed with the released VMQ-MEM 2.58.180, with the inspector or with web-search defects.

## Verbatim text

Текущие работы по памяти и поиску начинают расползаться в серию локальных исправлений под конкретные тестовые примеры.

Релиз VMQ-MEM 2.58.180 уже завершён. Не смешивать его с VMQ-TIME, инспектором хода и дефектами веб-поиска.

По VMQ-TIME зафиксировать текущий кандидат и провести независимую проверку на разнообразных реальных исторических вопросах, включая события, не использованные при разработке и настройке. Не ограничиваться примером с колбасой 2023 года.

Проверить, не приводит ли защита исторических записей от фильтра релевантности к попаданию нерелевантного материала в контекст. Временное разнообразие не должно подменять смысловую релевантность.

Отдельно пересмотреть введённую обработку словоформ через таблицы окончаний. Не закреплять её как универсальное решение смыслового поиска и не наращивать новые словари, исключения и ручные правила под неудачные запросы.

Утверждение "семантический поиск по старым периодам технически невозможен" слишком сильное. Architect должен проверить доступные варианты в существующей архитектуре, включая комбинированное извлечение и проверку временных метаданных. Без перестройки эмбеддингов, нового конвейера и многочасового исследования.

Не добавлять новые исправления после каждого единичного неудачного теста. Reviewer должен оценить системный результат на независимом наборе примеров и определить, является ли обнаруженная проблема блокирующей для данного слайса или относится к следующему утверждённому этапу памяти.

Если блокирующих дефектов нет — завершить текущий кандидат, оформить SHA, выполнить штатную интеграцию и двигаться дальше. Новые проблемы фиксировать в существующих задачах, а не бесконечно расширять текущую.

Инспектор хода и даты веб-источников вести как независимые работы со своими критериями DONE. Не ждать завершения всех смежных исследований ради закрытия одного исправления.

Никаких новых human gate, проверок за владельцем или дополнительных агентов. Кратко отчитайся о статусе каждого активного задания, его SHA, доказательствах и конкретных оставшихся блокерах. Продолжай workflow.

## Constraints implied for execution

1. VMQ-TIME candidate is frozen at the reviewed SHA; no further feature additions to this slice.
2. Independent evaluation must use a diverse set of real historical questions, including events never used while developing or tuning.
3. Temporal diversity must not replace semantic relevance: injected historical rows must be judged relevant, not merely different in year.
4. Suffix-table stemming is provisional recall support, not a universal semantic solution; no new dictionaries, exception lists or hand rules for individual failing queries.
5. The claim "semantic search over old periods is technically impossible" must be re-examined against existing architecture (combined retrieval, timestamp metadata checks) without embedding rebuild, new pipeline or long research.
6. No new fix per single failing example; Reviewer decides blocking-for-slice versus next approved memory stage.
7. Inspector and web-source dates are separate works with their own DONE criteria and must not wait for each other.
8. No new human gates, owner checks or additional agents.
