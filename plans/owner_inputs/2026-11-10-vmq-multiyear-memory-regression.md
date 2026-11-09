# Owner amendment (2026-11-10): real-world multi-year memory regression for VMQ-ONTO-01

Verbatim owner text:

> Дополнение к VMQ-ONTO-01: реальный регрессионный сценарий многолетней памяти.
>
> В чате с историей около 2,07 млн сообщений бот на запрос "напиши юмористический рассказ об основных шизах конфы" формирует довольно связный рассказ, включающий текущие и более старые события. Однако при обычных вопросах о многолетней истории участников память часто выдаёт случайные факты без связной реконструкции.
>
> Не считать успешную творческую генерацию доказательством качественного retrieval.
>
> Включить в приёмку VMQ-ONTO-01 сравнительные проверки одних и тех же исторических данных при разных формулировках: юмористический рассказ, обычный пересказ истории, характеристика участника, восстановление конкретного конфликта, изменение отношений или взглядов за годы.
>
> Проверять, какие эпизоды действительно извлекались из долговременной памяти, из каких периодов, с какими источниками и связями. Сравнить фактическое покрытие, хронологическую точность, релевантность и количество выдуманных связей.
>
> Важнейшее требование: обычный фактический вопрос должен получать не менее качественную доказательную основу, чем творческий рассказ. Различаться должны форма и стиль ответа, а не способность находить историю.
>
> Использовать существующие GraphRAG, эпизоды, тематические линии и ONTO-01. Не добавлять отдельный summary-пайплайн, словарные триггеры или новую систему памяти.
>
> Architect должен проверить именно end-to-end retrieval до Writer, Reviewer — независимо сравнить результаты на реальной истории.
>
> Встроить это в существующую приёмку VMQ-ONTO-01, без нового эпика, длительного ресерча и human gate.

## Binding points

- A successful creative answer is NOT evidence of retrieval quality and must never be accepted as such.
- Acceptance must compare the SAME historical data across at least five formulation classes: humorous story, plain retelling, participant profile, reconstruction of a specific conflict, and how relations or views changed over years.
- For each run, record which episodes were actually retrieved, from which periods, with which sources and relations; compare coverage, chronological accuracy, relevance and the number of invented links.
- Governing criterion: a plain factual question must receive an evidence base no worse than a creative story. Only form and style may differ, never the ability to find the history.
- Reuse the existing GraphRAG, episodes, thematic lines and ONTO-01. No separate summary pipeline, no dictionary triggers, no second memory system.
- Architect verifies the end-to-end retrieval path up to the Writer; Reviewer independently compares results on the real 2.07M-message history.
- This is an addition to the existing VMQ-ONTO-01 acceptance, not a new epic: no long research phase and no human gate.
