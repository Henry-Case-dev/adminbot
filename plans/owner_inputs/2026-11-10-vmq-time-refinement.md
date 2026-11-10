# Owner refinement (2026-11-10): VMQ-TIME-01..07 requirements

Verbatim owner text:

> Уточнение требований VMQ-TIME-01…07.
>
> Подтверждена проблема: ограничение 50 активных фактов на участника, вытеснение старого в archived_fact, полураспад 60 дней, бонус свежести и ограниченная выборка профиля совместно препятствуют доступу к многолетней памяти.
>
> Не исправлять проблему механическим повышением лимитов, удалением квот или простым добавлением архивных фактов с неизменным штрафом за возраст.
>
> Квота активных фактов допустима исключительно как ограничение оперативного набора, но не всей доступной истории. Архивные факты должны полноценно участвовать в поиске при соответствующем смысле запроса, даже если пользователь не указал год, период или слово "вспомни". Решение определяет существующий L1 без новых словарных триггеров.
>
> Разделить историческую значимость, фактическую достоверность и актуальность на сегодняшний день. Старый факт не должен получать низкую историческую релевантность исключительно из-за возраста или статуса archived_fact. Архивность по квоте сама по себе не означает ложность, устаревание или неподтверждённость.
>
> Пересмотреть применение GRAPH_TIME_DECAY_HALF_LIFE_DAYS, GRAPH_TIME_DECAY_FLOOR и бонуса свежести в историческом и субъектном retrieval. Для актуальных вопросов сохранить механизм определения действующих сведений, но не подменять его простой сортировкой по дате.
>
> Профиль участника должен уметь строиться из разных периодов его истории, а не только из десяти наиболее свежих фактов. Для исторических вопросов обеспечивать тематическое и временное покрытие, сохраняя реальные источники.
>
> Контекстные бюджеты оставить как техническую защиту производительности, но сделать подбор доказательств адаптивным. Не устанавливать постоянную долю свежих и архивных фактов для всех запросов. Не создавать новую систему памяти, не перестраивать эмбеддинги и не изменять сохранённые пользовательские настройки.
>
> Reviewer должен проверить на реальном архиве 2,07 млн сообщений, что обычные вопросы о людях и событиях без указания года действительно извлекают релевантные сведения из нескольких лет, а вопросы о текущем положении дел не представляют исторические факты как действующие.
>
> В Статусе и Аналитике показывать покрытие выдачи по годам и причины исключения фактов: квота, статус, давность, релевантность, бюджет. Без фиктивной статистики.
>
> Это уточнение к уже зарегистрированному VMQ-TIME-01…07. Не создавать отдельный эпик, новый human gate или многодневный ресерч. Текущие исправления retrieval завершить независимо и продолжить очередь.

## Binding points

- No mechanical fix: raising limits, removing quotas or merely adding archived facts with the same age penalty is forbidden.
- The active-fact quota is an operative working set only, never the boundary of available history. Archived facts must participate fully when the query's meaning calls for it — even with no year, period or "remember" word in the question — and the EXISTING L1 decides, with no new lexical triggers.
- Three properties must be separated: historical significance, factual reliability, and current validity. An old fact must not receive low historical relevance merely because of its age or its `archived_fact` status; being archived by quota does not mean it is false, stale or unconfirmed.
- Revisit `GRAPH_TIME_DECAY_HALF_LIFE_DAYS`, `GRAPH_TIME_DECAY_FLOOR` and the freshness bonus specifically in historical and subject retrieval. For current-state questions keep the mechanism that determines what is in force, but do not replace it with plain date ordering.
- The participant profile must be able to build from several periods of that person's history, not only the ten freshest facts; historical questions need thematic and temporal coverage while keeping real sources.
- Context budgets stay as technical performance protection, but evidence selection must be adaptive; no fixed fresh/archived proportion for all queries. No new memory system, no embedding rebuild, no change to stored user settings.
- Reviewer must verify on the real 2.07M archive that ordinary person and event questions without a year retrieve relevant material from several years, and that current-state questions do not present historical facts as currently valid.
- Status and Analytics must show year coverage of the returned material and the reasons facts were excluded (quota, status, age, relevance, budget), with no fictitious statistics.
- This refines the registered VMQ-TIME-01..07; no new epic, no human gate, no multi-day research. Finish the current retrieval fixes independently and continue the queue.
