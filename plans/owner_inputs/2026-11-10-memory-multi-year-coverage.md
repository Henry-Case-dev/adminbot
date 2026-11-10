# Owner requirement (2026-11-10): the memory block must use the whole multi-year history

Verbatim owner text:

> Уточни по коду, почему блок памяти при обычных вопросах отдаёт преимущественно 2026 год. Требуется проверить весь путь извлечения исторического контекста: источники, временные фильтры, ранжирование, профили участников и сборку контекста LLM.
>
> Бот должен уметь использовать всю доступную многолетнюю историю чата, а не только последние месяцы. Старые сообщения должны извлекаться по смысловой релевантности, без искусственного приоритета свежих данных там, где вопрос касается истории или человека.
>
> Проверь на реальных обезличенных данных вопросы о событиях и участниках за разные годы. Покажи, на каком конкретно этапе теряется историческая информация.
>
> Не создавай новую систему памяти без необходимости и не перестраивай существующие эмбеддинги. Сначала установи первопричину и проверь, можно ли исправить действующий механизм. Если это не входит в текущий P0, зарегистрируй как отдельный обязательный дефект с точными зависимостями, не прерывая текущую работу.
>
> И ключевой момент: даже если вопрос не содержит года, бот должен уметь найти сведения о человеке из 2023-го или 2024-го, если они действительно релевантны. Иначе это не полноценная долговременная память, а поиск по сравнительно свежему контексту.

## Binding points

- Establish the root cause by code across the entire retrieval path: sources, time filters, ranking, participant profiles and LLM context assembly.
- The bot must be able to use the whole multi-year history, not the last months; old messages are retrieved by semantic relevance without an artificial recency preference where the question concerns history or a person.
- Verify on real anonymised data with questions about events and participants from different years, and show the exact stage where historical information is lost.
- Do not build a new memory system without need and do not rebuild existing embeddings; fix the current mechanism if possible after the root cause is established.
- If this is outside the current P0, register it as a separate mandatory defect with exact dependencies, without interrupting current work.
- Decisive: a question WITHOUT a year must still surface 2023 or 2024 information about a person when it is genuinely relevant; otherwise the feature is not long-term memory.
