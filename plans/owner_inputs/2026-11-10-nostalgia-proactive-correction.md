# Owner correction (2026-11-10): nostalgia is proactive, not only query-driven

Verbatim owner text:

> Корректировка P1 по ностальгии. В отчёте смешаны два разных механизма: исторический поиск по запросу пользователя и самостоятельная ностальгия бота.
>
> Изначальная задумка Nostalgia - бот самостоятельно вспоминает связанные события из прошлого и органично возвращает их в разговор, даже если никто не просил вспомнить прошлое. Кроме того, он может инициировать воспоминание автономно, без текущего разговора.
>
> В актуальном коде `nostalgia_worker.py` уже реализован автономный `nostalgia_tick`, сценарии A/B и делегирование общему Decision/Writer/SendRecheck. Эти механизмы сохранить. Удаление словарного pre-gate не должно отключать инициативную ностальгию или превращать её в функцию, работающую только по запросу.
>
> **Необходимое целевое поведение:**
>
> 1. В живом разговоре модель сама обнаруживает смысловую связь между текущей темой, участниками, событиями и многолетней памятью. Если исторический эпизод действительно уместен, бот может самостоятельно его вспомнить. Никаких обязательных слов-триггеров, словарей тем или регулярных выражений.
> 2. При самостоятельном периодическом запуске ностальгия продолжает исследовать старую историю и выбирать потенциально интересные эпизоды. Не ограничивать её последними сообщениями или событиями ровно годичной давности.
> 3. Если пользователь задаёт обычный вопрос о прошлом, существующий L1 самостоятельно решает, нужен ли исторический поиск. Это отдельный сценарий, не заменяющий инициативную ностальгию.
> 4. Окончательное решение о публикации принимает существующий механизм инициативы с учётом релевантности, контекста, свежести обсуждения, повторов и действующих пользовательских настроек. Не генерировать ностальгию ради заполнения периодического тика.
> 5. Предусмотреть интеграцию с Quantum Navigation из VMQ-ONTO-01. Квантовый источник будет участвовать во взвешенном выборе исторических периодов и эпизодов. Случайность определяет направление исследования, но не достоверность воспоминания и не обязанность его публиковать. Не создавать сейчас второй генератор или независимый пайплайн.
> 6. Переиспользовать существующие NostalgiaWorker, GraphRAG, долговременную память и общий механизм инициативы. Исключить дублирование, не переписывать пользовательские промпты, не отключать новые функции по умолчанию.
>
> Отдельно обратить внимание на `_pick_candidate()` в `nostalgia_worker.py`: текущий приоритет событий примерно годичной давности и «золотых» фактов по словам последних сообщений слишком примитивен для смысловой ностальгии. Не считать наличие этих механизмов реализацией полноценного обнаружения связей.
>
> **Приёмка:** проверить три независимых сценария: бот сам вспомнил уместный исторический эпизод во время живой дискуссии; бот автономно инициировал воспоминание; пользователь спросил о прошлом без специальных ключевых слов и получил релевантный ответ.
>
> Во всех сценариях проверять реальные источники памяти, отсутствие выдуманных связей и повторов. Также проверять, что модель умеет промолчать, когда интересной связи нет.
>
> Эту корректировку учесть в текущем P1 и в архитектурных зависимостях VMQ-ONTO-01. Не создавать новый эпик, отдельный пайплайн, новые словарные триггеры или human gate. Продолжать выполнение workflow.
>
> И ещё принципиальный момент: даже если ностальгия работает по расписанию, это не означает, что она должна ждать ровно следующего тика, чтобы заметить удачную историческую параллель. В перспективе существующий Observer/Decision должен иметь возможность обнаруживать её прямо во время живого обсуждения. Иначе бот будет регулярно вспоминать прошлое, но по-прежнему не научится делать это к месту.

## Binding points

- Two distinct mechanisms must stay distinct: (1) a user's historical question, decided by L1; (2) proactive nostalgia, which the bot initiates on its own.
- Removing the lexical pre-gate must NOT disable proactive nostalgia nor reduce it to a query-only feature.
- In a live conversation the model itself must be able to notice a semantic link between the current topic, participants, events and long-term memory, and recall an episode when it is genuinely relevant — with no word triggers, topic dictionaries or regexes.
- The autonomous periodic pass keeps exploring old history; it must not be limited to the last messages or to events from exactly one year ago.
- Publication is decided by the existing initiative mechanism using relevance, context, discussion freshness, repetition and the user's current settings. Nostalgia must not be generated just to fill a tick.
- `_pick_candidate()`'s current preference for roughly-year-old events and "golden" facts keyed by words of the latest messages is too primitive and is not accepted as semantic link detection.
- Silence is a valid outcome: if no interesting link exists, the bot says nothing.
- Quantum Navigation from VMQ-ONTO-01 will later take part in weighted selection of historical periods and episodes; randomness sets the direction of exploration only, never the truth of a memory nor the obligation to publish. No second generator and no independent pipeline now.
- Reuse NostalgiaWorker, GraphRAG, long-term memory and the shared initiative mechanism; do not rewrite user prompts and do not disable new features by default.
- Acceptance: three independent scenarios (spontaneous in-conversation recall; autonomous initiation; a plain past question without keywords) plus silence when nothing fits; check real memory sources, invented links and repeats.
