# Owner correction (2026-11-10): full quantum non-determinism for nostalgia and initiative

Verbatim owner text:

> **Корректировка проактивной ностальгии и инициативы — полноценная квантовая недетерминистика.**
>
> В текущем отчёте указано: "Квантовая точка — только тай-брейк внутри равных весов". Это НЕ соответствует требованиям владельца. Ограничение QRNG до разрешения ничьих отменить.
>
> Изначальная задумка Quantum RandomSource — сделать поведение бота реально недетерминированным. Случайность должна влиять на то, когда бот обращает внимание на определённые события, какие области памяти исследует, когда решает вмешаться в разговор и с какой вероятностью публикует подготовленное сообщение.
>
> **1. Недетерминированное расписание**
>
> Пересмотреть текущие `nostalgia_worker.py`, `initiative_observer.py`, `memory_maintenance.py` и существующие планировщики.
>
> Для ностальгии и обычной инициативы реализовать случайный выбор момента следующей смысловой проверки через единый Quantum RandomSource. Не ограничиваться случайным jitter при старте фиксированного IntervalTrigger.
>
> После очередного цикла выбирать новое случайное время следующей проверки. Использовать ограниченное адаптивное распределение, учитывающее настройки частоты, активность чата, периоды молчания, доступные бюджеты и антифлуд.
>
> Настройки границ и профилей частоты должны быть редактируемыми через существующую админку. Не зашивать произвольные фиксированные интервалы и вероятности в код.
>
> Следующее запланированное время сохранять в durable-состоянии по каждому чату, переживать рестарты, корректно обрабатывать пропущенные сроки, конкурентные запуски и изменение настроек. Не допускать накопления просроченных заданий с последующей массовой отправкой.
>
> Технические heartbeat и обслуживание очередей можно оставить периодическими. Они лишь исполняют наступившие события, но не определяют фиксированную периодичность смысловых решений.
>
> **2. Событийная инициатива без ожидания таймера**
>
> Сохранить способность существующего Observer обнаруживать интересные ситуации непосредственно во время живой беседы.
>
> Если возникает содержательный повод — неожиданная связь с прошлым, развитие конфликта, интересная ассоциация, удачная возможность пошутить или вмешаться, — бот может сразу оценить возможность инициативы или ностальгии, не ожидая следующего случайного планового тика.
>
> Не создавать для этого второй Observer, отдельный LLM-пайплайн или словарные триггеры.
>
> Плановый квантовый механизм и событийный Observer должны пользоваться общими Decision/Writer/SendRecheck, дедупликацией и учётом отправок.
>
> **3. QRNG влияет на публикацию**
>
> После смысловой оценки кандидата рассчитывать вероятность публикации с учётом релевантности, значимости, активности разговора, свежести и качества памяти, недавних инициатив, настроек частоты и других существующих факторов.
>
> Решение о публикации должно действительно использовать случайное значение Quantum RandomSource. Это отдельная значимая область применения, а не tie-break.
>
> Не вводить двойную систему независимых запретов, при которой LLM сначала почти всегда выбирает SILENT, а QRNG вызывается только для редких уже одобренных сообщений. Пересмотреть контракт принятия решения так, чтобы вероятностный механизм реально влиял на частоту и спонтанность поведения.
>
> При этом не превращать случайность в безусловный приказ публиковать мусор. LLM отвечает за содержание, фактическую уместность и смысловые основания. Жёсткие лимиты, права, отключение модуля, дедупликация и SendRecheck остаются обязательными.
>
> Для умеренно подходящих кандидатов допускается вероятностная спонтанная публикация; при отсутствии содержательного повода допустимо молчание.
>
> **4. Общий источник без псевдослучайного подмешивания**
>
> Использовать только существующий RandomSource и его расширение из VMQ-ONTO-01.
>
> Квантовые значения должны применяться для:
> - Выбора следующего момента проверки.
> - Выбора направления исследования памяти.
> - Взвешенного выбора кандидатов.
> - Вероятностного решения о публикации.
> - Дополнительных ситуаций инициативы, предусмотренных существующими контрактами.
>
> Не создавать новый генератор, не смешивать квантовые и псевдослучайные значения внутри одного выбора. Детерминированное преобразование равномерных квантовых битов в длительности, индексы и вероятностные исходы допустимо, если оно не добавляет псевдослучайности и не вносит смещения распределения.
>
> Соблюдать существующую политику провайдеров, пулов, IBM direct-generation, сроков ожидания и fallback. Фактический источник каждого решения должен быть известен из журнала.
>
> До готовности соответствующих контрактов VMQ-ONTO-01 не создавать временный независимый QRNG-контур. Установить явную зависимость между эпиками.
>
> **5. Метрики и админка**
>
> В Статусе и Аналитике добавить понятную визуализацию фактической недетерминистики отдельно для ностальгии и обычной инициативы:
>
> - Время последнего и следующего запланированного смыслового события.
> - Источник случайности и факт использования quantum/fallback.
> - Распределение интервалов между проверками.
> - Количество плановых и событийных оценок.
> - Кандидаты, вероятности публикации и результаты случайных решений.
> - Сколько публикаций разрешено QRNG, сколько отложено или отклонено.
> - Доля молчаний по отсутствию повода, лимитам, семантике и случайному исходу.
> - Повторы, фактические доставки, активность по чатам и временным периодам.
>
> Не использовать фиктивные метрики. Каждая статистика должна происходить из реальных решений и durable events. Не отображать статус "работает", если QRNG фактически не использовался.
>
> **6. Область действия и приёмка**
>
> Распространить механизм как минимум на проактивную ностальгию и обычную инициативу, не ограничиваясь мем-инициативой. Сохранить уже запланированные интеграции QRNG со снами и памятью.
>
> Проверить реальные различия во времени и частоте событий на длительных воспроизводимых тестах с управляемыми значениями RandomSource, в том числе после рестарта, на двух чатах, при неактивном чате, при отключении отдельного модуля и при отказе квантового провайдера.
>
> Проверить, что при одинаковой семантической ситуации разные допустимые квантовые значения способны дать разные решения о публикации. В противном случае требование не выполнено.
>
> Architect должен согласовать этот контракт с VMQ-ONTO-01 и текущими исправлениями P1, передать его Builder как обязательное требование. Reviewer обязан проверить, что случайность не декоративна и не ограничена выбором при равных весах.
>
> Не создавать отдельный эпик, новые агенты, OFF/SHADOW-режимы или human gate. Сохранить пользовательские настройки и существующую архитектуру. Если это требует изменений уже выполненной проактивной ностальгии — оформить их как обязательную корректировку, а не отложить на неопределённый срок.
>
> После интеграции продолжить текущий workflow.
>
> Я бы предусмотрел независимое случайное расписание по каждому чату, а не один глобальный квантовый тик. Иначе оба чата будут постоянно оцениваться одновременно, что само по себе выглядит искусственно.
>
> А для живого разговора важнее всего сочетание двух механизмов: случайной возможности вмешаться и модельного обнаружения действительно интересного момента. Именно это даст боту поведение, похожее на живого участника, который иногда молчит, иногда внезапно вспоминает старую историю, а иногда сам решает встрять в обсуждение — без команды пользователя.

## Binding points

- The tie-break-only role for QRNG is CANCELLED. Quantum values must govern: the next check moment, the direction of memory exploration, weighted candidate choice, the publication probability, and other initiative situations already covered by existing contracts.
- Per-chat independent random scheduling, not one global tick: after each cycle a new next-check time is drawn from an adaptive bounded distribution that accounts for frequency settings, chat activity, silence, budgets and anti-flood. Bounds and frequency profiles are editable in the existing admin, not hardcoded. The next time is durable per chat, survives restarts, handles missed deadlines and concurrent runs, and never accumulates overdue work into a mass send.
- Technical heartbeats and queue maintenance may stay periodic; they only execute due events and must not define the semantic cadence.
- The existing Observer keeps detecting interesting situations during a live conversation and may evaluate initiative or nostalgia immediately, without waiting for the tick. No second Observer, no separate LLM pipeline, no lexical triggers; both paths share Decision/Writer/SendRecheck, dedup and send accounting.
- Publication must use a real random value: a probability derived from relevance, significance, conversation activity, freshness, memory quality, recent initiatives and frequency settings. The double-gate pattern (LLM nearly always SILENT, QRNG only for rare approved items) is rejected. The LLM remains responsible for content and appropriateness; hard limits, rights, module-off, dedup and SendRecheck stay mandatory. Moderate candidates may be published spontaneously; with no substantive reason silence is fine.
- Only the existing RandomSource and its VMQ-ONTO-01 extension. No new generator, no mixing quantum and pseudo-random values inside one choice. Deterministic transforms of uniform quantum bits into durations, indices and outcomes are allowed if they add no pseudo-randomness and no distribution bias. Provider policy, pools, IBM direct generation, timeouts and fallback are respected, and the actual source of each decision is recorded in the log. No temporary independent QRNG circuit while VMQ contracts are pending; the cross-epic dependency is explicit.
- Status and Analytics must show real non-determinism per mechanism (last/next planned event, source and quantum/fallback usage, interval distribution, planned versus event-driven evaluations, candidates with probabilities and outcomes, allowed versus deferred/rejected, silence shares by cause, repeats, deliveries, per-chat activity). No fictitious metrics; never show "working" when QRNG was not actually used.
- Scope covers at least proactive nostalgia and regular initiative, not just meme initiative; existing QRNG integrations with dreams and memory are preserved.
- Acceptance: long reproducible runs with controlled RandomSource values, including restart, two chats, inactive chat, module disabled and quantum provider failure; and the same semantic situation must be able to produce different publication decisions under different allowed quantum values, otherwise the requirement is unmet.
- Architect aligns this with VMQ-ONTO-01 and the P1 fixes and hands it to Builder as a mandatory requirement; Reviewer must verify the randomness is neither decorative nor confined to ties.
- No new epic, agents, OFF/SHADOW modes or human gate; keep user settings and the existing architecture.
