# A8 `telegram-reactions-round1026` — спецификация (Step 2 @Architect, T-3669)

- **Epic-ID:** Эпик 3 «Agentic Intelligence» (Wave 5 — продолжение; **Wave 6 не изобретается**, C-4 подтверждён). **Feature-ID:** `telegram-reactions-round1026`. **Раунд:** 10.26.
- **Тип** (`backlog:310`): backend/Telegram API — **механика исполнения реакции** (§41) поверх контракта A7: официальный `setMessageReaction`, проверка доступности в чате, детерминированная разрешённая альтернатива/отказ, реакция на **правильное** сообщение, «ошибка реакции ≠ длинный текст», контекстный (не фиксированный) выбор эмодзи из **стандартного набора**. **P0.**
- **ТЗ-источник (IMMUTABLE, `plans/current_task.md`, только чтение — R17/R18):** **§41 «РЕАКЦИИ TELEGRAM»** (`:5384–5409`; содержательные `:5388–5408`), **§44-механика «КОГДА СТАВИТЬ РЕАКЦИЮ»** (`:5494–5501`: «Не использовать одинаковую реакцию в любой ситуации», «Не использовать случайность как основной механизм принятия решений», «Реакция должна соответствовать контексту и характеру бота»). **Правила §44 (`:5480–5498`) = scope A7** — A8 их **не переопределяет**. **Приёмка:** §52 п.21 «Недоступную реакцию Telegram.» (`:5795`), §53 «реакция ставится не на то сообщение» (`:5844`), §53 «бот продолжает отвечать длинным текстом на каждое "АХАХА"» (`:5839–5840`), §54 п.9 «Результаты тестирования реакций и молчания.» (`:5885`). **Кросс-приёмка:** §52 п.16/17/20/22 (`:5785/5787/5793/5797`) — A7-поведение, подпёртое механикой A8; §54 п.8 (`:5884`) — контракт A7 (граница).
- **Связанные документы:** `tasks.md` (13 REQ-A8-01…-13 verbatim-traced, 12 инвариантов, блоки 0/A–L, U1–U12, §44-атрибуция C-1 «правила=A7 / механика=A8»); **ADR-1026-21** (`adr-1026-21-reaction-mechanics.md`, D1–D14, Status **Proposed → Accepted по merge**, ожидаемый раздел `plans/ARCHITECTURE.md` **§90**).
- **Зависит от:** **A7** ✅ (Merge §89, ADR-1026-20 D1/D5): поставляет решение `action=react` + `target_message_id` + `reaction` + `reason_code`; точка reuse `react_moai`; **разрыв T-3678** — `pre_reaction`/`pre_reason` не доходят до исполнителя. **A1** ✅ (`CoordinatorDecision` — не дублировать). **A0** ✅ (durable-аудит, EV-26/EV-32). Owner-gate прод-проб A3 `PENDING OWNER VERIFICATION` — внешний (A8 не закрывает).
- **Baseline (Step 0 @Memory, 25.09.2026; в Step 2 не перемеряется):** HEAD **`e8646af`** + **UNCOMMITTED epic-release рабочее дерево A2–A7** — не трогать/не коммитить. `APP_VERSION` **2.58.30**; канон инструментов **12**; **Δ DDL = 0** (SQLite **v12**); **Δ каталога = 0** (счётчики после A7: `REGISTRY 473` / Settings `430` / categorized `448` / `GROUPS 102` / `_TAB_BY_GROUP 100` / `TAB_RULES 21`). Baseline-анкер **`e8646af`**; hot-откат = env-only kill-switch OFF; холодный = `git revert`/анкер; теги/бэкапы/`stash` не удаляются (R18).
- **Release policy:** **EPIC_ONLY.** A8 не деплоится после approval; входит в **pending epic-release Эпика 3** (`included in pending epic release`; пер-фича деплоя/тега/bump нет; агрегатный bump **2.58.30 → 2.58.31** — на границе эпика). **@DevOps на пер-фича деплой не вызывается.**
- **Risk-Level: R2** (финальный, обоснование — §13). **Статус:** Proposed.

## 1. Область и исключения

**Входит (что делает A8):**
- **Исполнитель реакции = единственный официальный путь** `Bot.set_message_reaction` (§41 `:5388–5390`; REQ-A8-01): расширение существующего примитива `services/smartmodule_utils.py::react_moai` (`:93–107`) — **один** и тот же вызов, без обходных путей. (§3.1)
- **Проверка доступности в конкретном чате** (§41 `:5392–5393`; REQ-A8-02): доступность разрешается **авторитетно результатом доставки** (`REACTION_INVALID` → детерминированная альтернатива/отказ); бот **никогда не предполагает**, что эмодзи разрешён. (§3.2)
- **Запрет произвольного эмодзи** (§41 `:5395–5396`; REQ-A8-03): только **стандартный набор** Telegram (для ботов без custom/premium/paid), **одна** реакция на сообщение; выбор — из малого курируемого набора. (U8; §3.3)
- **Разрешённая альтернатива или отказ** (§41 `:5398–5400`; REQ-A8-04/-09/-11): недоступная выбранная реакция → **детерминированная** альтернатива из набора; если все недоступны → **тихий отказ** (без текста, без случайности). (§3.2/§3.3)
- **Правильная цель** (§41 `:5405–5408`; REQ-A8-06/-07/-12): реакция ставится на `target_message_id` (trigger-сообщение); `reply_to_id`/ID предыдущего сообщения бота **не** используются как цель; media-group → серверное поведение Telegram (первое неудалённое сообщение группы). (§3.4)
- **Ошибка реакции ≠ текст** (§41 `:5402–5403`; REQ-A8-05): любая ошибка реакции → fail-silently; **никакого** автоматического текстового ответа. (§3.5)
- **Контекстный (не фиксированный) выбор эмодзи** (§44-механика; REQ-A8-08/-10): детерминированная карта `reason_code → эмодзи` из стандартного набора; `CoordinatorDecision.reaction` несёт контекстный эмодзи; фиксированная 🗿 — только дефолт/fallback. (§3.3)
- **Закрытая таксономия ошибок** (REQ-A8-05): `ok` / `unavailable` / `forbidden` / `message_gone` / `service` / `rate_limited` / `unknown`; логи — R17-safe (id/enum/эмодзи/reason/код ошибки). (§3.5)
- **Kill-switch** `REACTION_MECHANICS_ENABLED` (env-only, default ON; OFF → legacy-поведение: фиксированная 🗿, одиночная попытка, best-effort). (U10; §3.6)
- **Закрытие разрыва T-3678:** `pre_reaction`/`pre_reason` из решения A7 передаются в исполнитель в точке `direct_chat_service.py:1279–1285`. (§3.7)

**Не входит (границы, категорически):**
- **правила §44 `:5480–5498`** — **scope A7** (когда/какую) — **не переопределяются** (C-1; потребляем только `action=react`/`reason_code`/`target_message_id`/`reaction`).
- **A7-политика** `_decision_pre_action` (классы/приоритеты/`action`) — не меняется; A8 меняет только **значение эмодзи** для уже выбранной ветки `react` (механика, прямо делегированная A7→A8 в ADR-1026-20 D5).
- **A9** (§49/§51 — события `REACTION_SENT`/`MESSAGE_IGNORED`, ExecutionGraph, Mini App) — **вне scope**; `MessageReactionUpdated`/`MessageReactionCountUpdated` **не подписываются и не обрабатываются** (события — A9).
- **A10** (§52–§54) — агрегатный acceptance-gate эпика — вне A8 (ориентиры §52.21/§53.5844/§54.9 учтены как REQ-A8-11/-12/-13).
- **A1** `CoordinatorDecision` — **не дублировать** (используем его поля `reaction`/`reason_code`/`target_message_id` как есть).
- **A2/A3/A4/A5/A6** — не переписываются; `tool_loop`/envelope/`ImageRequest`/`image_context_memory`/`get_user_context` — вне diff.
- **Новый инструмент/LLM-вызов** — канон **12** без изменений; A8 не добавляет LLM-вызовов и не трогает JSON-схемы инструментов.
- **Новый каталог/группы/вкладки/DDL/хранилище** — запрещены (Δ каталога = 0, Δ DDL = 0).
- **Прочие `react_moai`-сайты** (`handlers/youtube.py:800/815/1300`, `handlers/web.py:203`, `handlers/search.py:172`, `handlers/factcheck.py:305`, `handlers/checkup.py:148`, safety-net `direct_chat_service.py:1409/1475`) — **вне scope** (U11): их вызовы остаются байт-в-байт legacy (фиксированная 🗿, одиночная попытка).
- **§104 `generate_image`** — no-go; правки `plans/current_task.md`/машинного блока/`tasks.md`/`backlog`/`metrics`/`ARCHITECTURE`/`MEMORY`/durable-аудита — не в этом шаге. **@Scanner отсутствует** (единый Reviewer gate). **@DevOps не вызывается.**

## 2. Трассируемость REQ → SC

> Каждый REQ-A8-01…-13 привязан к ≥1 SC; каждый SC восходит к ≥1 REQ. **Orphan-REQ и orphan-SC нет (13 REQ → 15 SC: 13 специфичных + 2 кросс-скоупных).** Колонки SC/ADR в `tasks.md` заполняются @PM на сверке T-3670; формулировки — здесь. Полная детализация — §3/§6/§7/§9.

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC | ADR |
|---|---|---|---|---|---|
| REQ-A8-01 | §41 «Использовать официальный Bot API: setMessageReaction.» (`:5388–5390`) | B | T-3671 | SC-A8-01 | D1 |
| REQ-A8-02 | §41 «Проверять, разрешена ли реакция в конкретном чате.» (`:5392–5393`) | C | T-3673, T-3677 | SC-A8-02 | D2 |
| REQ-A8-03 | §41 «Не считать, что бот может отправить любой произвольный эмодзи.» (`:5395–5396`) | C, D | T-3673, T-3674 | SC-A8-03 | D8 |
| REQ-A8-04 | §41 «Если выбранная реакция недоступна, использовать разрешённую альтернативу или отказаться от реакции.» (`:5398–5400`) | C | T-3673 | SC-A8-04 | D2, D3 |
| REQ-A8-05 | §41 «Не превращать ошибку реакции автоматически в длинный текстовый ответ.» (`:5402–5403`) | F | T-3676 | SC-A8-05 | D5 |
| REQ-A8-06 | §41 «Реакцию ставить на правильное сообщение.» (`:5405`) | E | T-3675 | SC-A8-06 | D4 |
| REQ-A8-07 | §41 «Не путать reply_to_id, message_id и ID предыдущего сообщения бота.» (`:5407–5408`) | E | T-3675 | SC-A8-07 | D4 |
| REQ-A8-08 | §44-мех «Не использовать одинаковую реакцию в любой ситуации.» (`:5494–5495`) — на стороне A8 = **не хардкодить одну реакцию, поддерживать выбранную A7** (C-1) | D | T-3674 | SC-A8-08 | D1 |
| REQ-A8-09 | §44-мех «Не использовать случайность как основной механизм принятия решений.» (`:5497–5498`) — на стороне A8 = **детерминированный** выбор альтернативы/отказа (C-1) | C, D | T-3673, T-3674 | SC-A8-09 | D3 |
| REQ-A8-10 | §44-мех «Реакция должна соответствовать контексту и характеру бота.» (`:5500–5501`) — на стороне A8 = **корректная доставка** контекстно-выбранной A7 реакции (C-1) | D, H | T-3674, T-3678 | SC-A8-10 | D1, D13 |
| REQ-A8-11 | §52 п.21 «Недоступную реакцию Telegram.» (`:5795`) | C, I | T-3673, T-3679 | SC-A8-11 | D2, D5 |
| REQ-A8-12 | §53 «реакция ставится не на то сообщение» (`:5844`) | E, I | T-3675, T-3679 | SC-A8-12 | D4 |
| REQ-A8-13 | §54 п.9 «Результаты тестирования реакций и молчания.» (`:5885`) | I, J | T-3679, T-3680 | SC-A8-13 | D12 |

**Кросс-скоуповые примечания:** §44-**правила** `:5480–5498` — **A7** (REQ-A7-17/-18/-19), не REQ A8; §54 п.8 «JSON Schema нового Decision Making» `:5884` — **A7**-контракт, поле `reaction` — граница (потребитель A8, не REQ); §41 `setMessageReaction` **не вызывается** из A7 (инвариант границы; вызов только в `react_moai`); §49/§51 (события/ExecutionGraph) — **A9**; §52 п.16/17/20/22 — A7-поведение, подпёртое механикой A8. **`SC-A8-14/-15` — кросс-скоупные агрегаторы; orphan-SC нет.**

### 2.1. Определения SC (наблюдаемо/тестируемо)

| SC | Формулировка | Восходит к REQ |
|---|---|---|
| SC-A8-01 | Реакция исполняется **исключительно** `Bot.set_message_reaction`; в коде — один call-site (примитив `react_moai`); spy фиксирует метод; обходных путей (`raw`-HTTP, aiogram-shortcut `Message.react`) нет. | REQ-A8-01 |
| SC-A8-02 | Доступность реакции в конкретном чате разрешается **авторитетно**: недоступность (`REACTION_INVALID`) детектируется и обрабатывается (альтернатива/отказ); реакция не считается доставленной без учёта разрешения чата; не делается предположение «любой эмодзи разрешён». | REQ-A8-02 |
| SC-A8-03 | В `set_message_reaction` передаётся ровно один `ReactionTypeEmoji` из **курируемого стандартного набора**; custom/premium/paid (`ReactionTypeCustomEmoji`/`ReactionTypePaid`) не используются; списки >1 не формируются. Проверяется конструкцией + тестом. | REQ-A8-03 |
| SC-A8-04 | Недоступная выбранная реакция → детерминированная разрешённая **альтернатива** из набора; если все кандидаты недоступны → **тихий отказ** (0 реакций, 0 текста). | REQ-A8-04 |
| SC-A8-05 | Любой отказной путь реакции (недоступна/запрещено/удалено/служебное/429/неизвестно) → **0 исходящих текстовых сообщений**; `_send_direct_answer`/`send_message` не вызываются; ошибка отражается только R17-safe логом. | REQ-A8-05 |
| SC-A8-06 | Реакция ставится на `target_message_id` = id **trigger-сообщения пользователя**; executor получает и пересылает его без подмены. | REQ-A8-06 |
| SC-A8-07 | `reply_to_id` и id предыдущего сообщения бота **никогда** не используются как цель реакции; в reply-ситуации реакция уходит на trigger, не на replied-сообщение. | REQ-A8-07 |
| SC-A8-08 | Исполнитель **не хардкодит** одну реакцию: разные контексты (`reason_code`) → разные эмодзи (😂/👍/🔥); фиксированная 🗿 — только дефолт/fallback; при OFF — legacy 🗿. | REQ-A8-08 |
| SC-A8-09 | Детерминизм: одинаковый вход (тот же `reason_code`/контекст) → одинаковый эмодзи при повторном прогоне; альтернативный порядок фиксирован; `random` не используется. | REQ-A8-09 |
| SC-A8-10 | Контекстно-выбранная реакция (`CoordinatorDecision.reaction`) **реально доставляется**: эмодзи, выбранный A7-решением, равен эмодзи, переданному в `set_message_reaction` (T-3678 закрыт). | REQ-A8-10 |
| SC-A8-11 | Сценарий §52.21 (недоступная реакция Telegram) воспроизводится тестом: альтернатива принята **или** тихий отказ; текста нет. | REQ-A8-11 |
| SC-A8-12 | Сценарий §53.5844 (реакция не на то сообщение) воспроизводится тестом: цель = trigger; в reply-/media-group-ситуации подмены нет. | REQ-A8-12 |
| SC-A8-13 | Артефакт §54.9 «Результаты тестирования реакций и молчания» предоставляется (evidence: прогон тестов реакций/молчания + R17-логи). | REQ-A8-13 |
| SC-A8-14 | **Кросс-скоуп:** OFF-паритет (kill-switch OFF → фиксированная 🗿, одиночная попытка, best-effort, без текста) + полный регресс (существующие тесты `react_moai`/direct/инструменты зелёные) + доказанное «0 текста на ошибку». | REQ-A8-01, REQ-A8-05, REQ-A8-08 |
| SC-A8-15 | **Кросс-скоуп:** границы соблюдены — A7-правила §44 не переопределены, `action`/`reason_code` семантика не изменена; A9-события/ExecutionGraph вне diff; канон **12**; Δ DDL=0; Δ каталога=0; промпты/JSON-схемы вне diff. | REQ-A8-08, REQ-A8-10, REQ-A8-13 |

## 3. Наблюдаемое поведение и отказные сценарии (по кластерам REQ)

### 3.1. Единственный официальный путь исполнения (REQ-A8-01; блок B; U8)
- **Примитив:** `services/smartmodule_utils.py::react_moai` — **единственный** вызов `bot.set_message_reaction`. A8 расширяет его аддитивно; второй исполнитель/HTTP-обход/shortcut `Message.react` **не вводится**. `direct_chat_service.py` (и все хендлеры) продолжают звать `react_moai`.
- **Сигнатура (аддитивная, обратносовместимая):**
  `async def react_moai(bot, chat_id, message_id, *, reaction=None, reason_code=None) -> str`.
  Позиционные 3 аргумента сохранены → legacy-сайты (`youtube/web/search/factcheck/checkup`, safety-net `:1409/1475`) не меняются. Возвращает R17-safe код исхода (старые вызовы игнорируют возврат).
- **OFF-parity:** при `reaction=None` или kill-switch OFF поведение байт-в-байт прежнее: одиночная best-effort попытка 🗿, `WARNING` при ошибке, без raise.

### 3.2. Доступность + альтернатива/отказ (REQ-A8-02/-04/-11; блок C; U2/U3)
- **Решение U2:** **реактивная** авторитетная проверка — попытка → классификация → детерминированная альтернатива/отказ. **Проактивный `getChat.available_reactions` в A8 не используется** (обоснование — ADR D2: лишний сетевой вызов на hot-path, race/stale-кэш, `available_reactions` отсутствует ≠ гарантия приёма; сервер — источник истины). Опциональный warm-кэш `available_reactions` — **вне scope** (genuine unknown для PM).
- **Кандидаты (детерминированно):** `primary = reaction`, если `reaction ∈ STANDARD_REACTION_EMOJIS`, иначе `REACTION_DEFAULT` (🗿). `candidates = (primary,) + (первые (MAX_REACTION_ATTEMPTS-1) альтернативы из REACTION_FALLBACK_ORDER, исключая primary)`. `MAX_REACTION_ATTEMPTS = 2`.
- **Только `unavailable` — retryable:** при `REACTION_INVALID` пробуется следующий кандидат; любая иная классификация (forbidden/gone/service/rate_limited/unknown) → останов и тихий отказ (альтернативы не помогут).
- **Если все кандидаты недоступны** → `REACTION_UNAVAILABLE`, **0 реакций, 0 текста** (тихий отказ, §41 «или отказаться»).
- **Детерминизм:** фиксированный порядок; `random` не используется (REQ-A8-09).

### 3.3. Источник эмодзи + стандартный набор (REQ-A8-03/-08/-09/-10; блоки C/D; U1/U8)
- **Решение U1:** детерминированная карта `reason_code → эмодзи` (механика, делегированная A7→A8 в ADR-1026-20 D5). `_decision_pre_action` возвращает контекстный эмодзи вместо константы 🗿 на всех четырёх `react`-ветках (`direct_chat_service.py:832/839/847/859`); `REACTION_MOAI` остаётся дефолтом/fallback.
- **Курируемый стандартный набор (U8):** `REACTION_DEFAULT="🗿"`, `REACTION_LAUGH="😂"`, `REACTION_APPROVE="👍"`, `REACTION_FIRE="🔥"`; `STANDARD_REACTION_EMOJIS` — замыкание этих четырёх. Все входят в стандартный reaction-набор Telegram; custom/premium/paid не используются.
- **Карта:**

| `reason_code` (A7) | Контекст (A7) | Эмодзи |
|---|---|---|
| `image_reaction` | смех/эмоция на **своё изображение** бота | 😂 |
| `laughter` | смех без контекста изображения | 😂 |
| `emoji_reaction` | одиночный эмодзи в ответ (в т.ч. на изображение) | 👍 |
| `emotion` | одобрение/подтверждение, когда `ignore_trivial` OFF | 🔥 |
| любой иной / `None` / неизвестный | fallback | 🗿 (`REACTION_DEFAULT`) |

- **`REACTION_FALLBACK_ORDER = (😂, 👍, 🔥, 🗿)`** — детерминированный порядок альтернатив.
- **«Не одна и та же всегда» (REQ-A8-08):** три различимых контекста → три различимых эмодзи; 🗿 — только дефолт/fallback; при OFF — legacy 🗿.
- **«Соответствие контексту/характеру» (REQ-A8-10):** выбранный эмодзи совпадает с контекстным классом; доставка не «теряет» выбор A7 (T-3678).
- **Одна реакция на сообщение:** всегда список из одного `ReactionTypeEmoji` (non-premium bot, `TOO_MANY_REACTIONS` не провоцируется).
- **Kill-switch-gate выбора:** `_reaction_for_reason` возвращает `REACTION_MOAI` при `REACTION_MECHANICS_ENABLED=false` — чтобы OFF-логи и OFF-поведение совпадали.

### 3.4. Правильная цель + media-group (REQ-A8-06/-07/-12; блок E; U4)
- **Цель = trigger:** `react_moai(bot, chat_id, target_message_id, ...)`, где `target_message_id = message.message_id` (уже так в A7: `_decision_pre_action(target_message_id=getattr(message, "message_id", None))`). Никогда не `reply_to_id` и не id предыдущего сообщения бота.
- **media-group:** **серверное** поведение Telegram (verbatim Bot API: «If the message belongs to a media group, the reaction is set to the first non-deleted message in the group instead») — специальный код **не нужен**; A8 передаёт trigger-id, Telegram применяет к первому неудалённому сообщению группы. Тест фиксирует, что переданный `message_id` не подменяется при `media_group_id`.
- **reply-ситуация:** `reply_to_message` **не** становится целью; тест с reply.
- **Служебные сообщения:** часть служебных типов не реактируема (Bot API) → классифицируется `service` → тихий отказ (без текста).

### 3.5. Таксономия ошибок + no-text fallback + rate limits (REQ-A8-05/-11; блок F/G; U5/U6)
- **Закрытый словарь исходов (R17-safe):** `REACTION_OK`, `REACTION_UNAVAILABLE`, `REACTION_FORBIDDEN`, `REACTION_MESSAGE_GONE`, `REACTION_SERVICE`, `REACTION_RATE_LIMITED`, `REACTION_UNKNOWN`.
- **Классификация** по `TelegramBadRequest.message` (lowercase-подстроки): `REACTION_INVALID`→unavailable; `not enough rights`/`CHAT_WRITE_FORBIDDEN`/`CHAT_ADMIN_REQUIRED`/`bot was blocked`→forbidden; `message to react not found`/`message not found`/`MESSAGE_ID_INVALID`→message_gone; `can't react to this message type`→service; иначе `unknown`. `TelegramRetryAfter`→`rate_limited`. Прочий `Exception`→`unknown`.
- **U6 (rate limits):** на `TelegramRetryAfter` **повтор не выполняется** (реакция не критична; `asyncio.sleep(retry_after)` блокировал бы handler; очередь/состояние = новый риск). Классифицируется `rate_limited`, тихий отказ.
- **no-text:** ни один исход не порождает `send_message`/`_send_direct_answer` (REQ-A8-05; §53 `:5839–5840`).
- **Логи (R17):** только `chat_id`/`message_id`/`outcome-enum`/`reason_code`/эмодзи/краткий код ошибки; **никогда** текст сообщений/имена/ключи/промпты. Существующая строка `"SmartModule: moai reaction failed"` **сохраняется** (аддитивные поля) — регресс-совместимость тестов.

### 3.6. Kill-switch (U10; блок J)
- `REACTION_MECHANICS_ENABLED` — env-only `ClassVar` (`config/settings.py`, паттерн `DIRECT_DECISION_MAKING_ENABLED:560`), default **ON**, резолв per-call, никогда не бросает, Δ каталога не растёт.
- **OFF → legacy-поведение:** одиночная попытка фиксированной 🗿, best-effort, без контекстного выбора и fallback; контекстный выбор в `_decision_pre_action` также возвращается к 🗿 (лог совпадает с реально отправленным эмодзи). Это hot-откат к pre-A8.
- **ON:** контекстный выбор + детерминированный fallback + таксономия.

### 3.7. Разрыв T-3678 — доставка `reaction` из A7 (REQ-A8-10; блок H; C-1)
- В точке `direct_chat_service.py:1279–1285` ветка `pre_action == ACTION_REACT`:
  `await react_moai(bot, chat_id, pre_target, reaction=pre_reaction, reason_code=pre_reason)`.
- `pre_reaction`/`pre_reason` уже вычисляются A7 и передаются в `build_coordinator_decision` (`:1430`); `CoordinatorDecision.reaction` уже несёт `pre_reaction` при `action=react`. **Контракт A1 не дублируется**, A7-политика не меняется — меняется только **значение** эмодзи (механика).
- `reason_code` в чат не выводится.

### 3.8. Прочие `react_moai`-сайты (U11; блок B/T-3672)
- **Решение U11:** **direct-only по поведению.** Новые возможности активируются только когда A7-ветка передаёт `reaction`; прочие сайты (`youtube:800/815/1300`, `web:203`, `search:172`, `factcheck:305`, `checkup:148`, safety-net `direct_chat_service:1409/1475`) зовут 3-аргументную форму → legacy 🗿 одиночная попытка, байт-в-байт. Их миграция на контекстный эмодзи — **вне scope** (нет `reason_code`-контекста; смена поведения расширила бы blast radius без продуктовой ценности).

### 3.9. Отказные/негативные сценарии (что считается НЕ выполнением)
- Текстовый ответ на ошибку реакции → не принято (§41; REQ-A8-05).
- Произвольный/custom/paid эмодзи; >1 реакции на сообщение → не принято (§41; REQ-A8-03).
- Случайный выбор эмодзи/альтернативы → не принято (§44; REQ-A8-09).
- Реакция на `reply_to_id`/предыдущее сообщение бота вместо trigger → не принято (§41; REQ-A8-07).
- Фиксированная 🗿 как **единственный** путь при ON → не принято (REQ-A8-08).
- Второй механизм/вызов `setMessageReaction` вне примитива → не принято (REQ-A8-01).
- Переопределение A7-правил `_decision_pre_action` (§44) → не принято (C-1).
- A9-события/ExecutionGraph/`MessageReactionUpdated` в diff → не принято (инвариант 10).
- Новый инструмент/LLM-вызов; Δ DDL≠0; Δ каталога≠0; §104 → не принято.
- Секреты/приватный контент в логах (R17) → не принято.
- Регресс legacy-сайтов / OFF-паритета → не принято (SC-A8-14).

## 4. Решения по открытым вопросам U1–U12 (полные формулировки — ADR-1026-21)

| U | Вопрос | Решение A8 | ADR |
|---|---|---|---|
| **U1** | Источник эмодзи | **Детерминированная карта `reason_code → эмодзи`** из курируемого стандартного набора; `_decision_pre_action` отдаёт контекстный эмодзи; 🗿 — дефолт/fallback; A7-политика (когда) не меняется. | D1 |
| **U2** | Проверка доступности | **Реактивная (try-and-fallback)**, `getChat.available_reactions` не используется (стоимость/race; сервер — истина); warm-кэш вне scope. | D2 |
| **U3** | Альтернатива/отказ | **Детерминированный** порядок `REACTION_FALLBACK_ORDER`, ≤2 попытки; все недоступны → тихий отказ; без рандома. | D3 |
| **U4** | Цель + media-group | Цель = trigger `message.message_id`; media-group — серверное «первое неудалённое» (код не нужен); `reply_to_id`/prev-bot не используются; тесты. | D4 |
| **U5** | Таксономия ошибок | Закрытый enum 7 исходов; только `unavailable` retryable; все fail-silently; логи R17-safe. | D5 |
| **U6** | Rate limits/`RetryAfter` | **Без повтора**; классификация `rate_limited`; тихий отказ. | D6 |
| **U7** | Права/типы чатов | Реактивно: private/group/channel различаются доступностью; `can_react_to_messages` (Bot API 10.0, на `ChatPermissions`/`ChatMemberRestricted`) проактивно не читается; ошибки классифицируются; при отсутствии прав → отказ. | D7 |
| **U8** | Набор эмодзи | Только **стандартный набор** (без custom/premium/paid), одна реакция; курируемый набор {🗿,😂,👍,🔥}. | D8 |
| **U9** | Настройки/каталог | **Δ каталога = 0**; A8 переиспользует A7-тумблеры `CHAT_DECISION_REACTIONS_ENABLED`/`CHAT_DECISION_IMAGE_REACTIONS_ENABLED` (гейт `react`-действия); F8 не переиздаётся. | D9 |
| **U10** | Kill-switch | `REACTION_MECHANICS_ENABLED` (env-only, default ON); OFF → legacy 🗿 одиночная попытка. | D10 |
| **U11** | Scope | **direct-only по поведению**; общий примитив апгрейдится обратносовместимо; прочие сайты не мигрируются. | D11 |
| **U12** | Финальный Risk | **R2**; escalation-триггеры — §13; R3-артефакт не требуется. | D12 |

## 5. Приёмочные инварианты A8 (12) → SC

> Нарушение = НЕ принято. Все 12 из `tasks.md` сохранены без потерь; привязка — к SC из §2.

1. **Только официальный `setMessageReaction`.** *(REQ-A8-01; SC-A8-01)*
2. **Проверка доступности в чате:** учёт «разрешена ли выбранная реакция» при постановке. *(REQ-A8-02; SC-A8-02)*
3. **Запрет произвольного эмодзи:** только стандартный набор (без custom/premium), одна реакция. *(REQ-A8-03; SC-A8-03)*
4. **Недоступно → альтернатива/отказ:** детерминированно, без текста-компенсации. *(REQ-A8-04/-09; SC-A8-04/-09)*
5. **Ошибка реакции ≠ длинный текст:** 0 текстовых ответов на ошибку. *(REQ-A8-05; SC-A8-05)*
6. **Правильная цель:** trigger/`target_message_id`; `reply_to_id`≠`message_id`≠prev-bot; media-group → первое неудалённое. *(REQ-A8-06/-07; SC-A8-06/-07)*
7. **Не одна и та же реакция всегда (механика):** исполнитель не хардкодит 🗿; контекстный выбор доставляется; 🗿 — дефолт/fallback. *(REQ-A8-08; SC-A8-08)*
8. **Соответствие контексту/характеру (механика):** контекстный выбор реально доставляется. *(REQ-A8-10; SC-A8-10)*
9. **Правила §44 не переопределяются:** A7 владеет «когда/какую»; A8 потребляет `action=react` и не вводит второй набор правил. *(REQ-A8-08/-10 + C-1; SC-A8-15)*
10. **Без A9-событий:** `REACTION_SENT`/`MESSAGE_IGNORED`, ExecutionGraph, Mini App — вне scope. *(SC-A8-15)*
11. **Без нового инструмента/LLM-вызова:** канон 12; JSON-схемы не меняются; `CoordinatorDecision` не дублируется. *(SC-A8-01/-15)*
12. **R17-логи + EPIC_ONLY:** логи — только id/enum/reason/эмодзи/код ошибки; deploy `DEFERRED_TO_EPIC`; Δ DDL=0; Δ каталога=0. *(REQ-A8-13; SC-A8-13/-15)*

## 6. Feature contract

**Preconditions:**
- A7 `DIRECT_DECISION_MAKING_ENABLED` ON и соответствующий тумблер (`CHAT_DECISION_REACTIONS_ENABLED`/`CHAT_DECISION_IMAGE_REACTIONS_ENABLED`) ON — тогда A7 выбирает `action=react`.
- `REACTION_MECHANICS_ENABLED` (A8, env-only) ON для новых возможностей; OFF → legacy.
- `bot`/`message_id` доступны; `bot.set_message_reaction` — единственный канал.
- Канон `TOOL_CALLING_TOOLS == 12`; `json`-схемы инструментов не меняются; Δ DDL=0.

**Invariants:** §5 (12). Дополнительно: 0 текстовых отправок на любом отказе реакции; выбор эмодзи детерминирован (без `random`); прочие `react_moai`-сайты без изменений поведения.

**Inputs/Outputs:**
- **Вход:** `bot`, `chat_id`, `message_id` (trigger), `reaction` (контекстный эмодзи из A7; `None` у legacy-сайтов), `reason_code` (R17-safe; для логов), kill-switch.
- **Выход:** один исход реакции (`REACTION_OK`/классифицированный отказ) + R17-safe лог; при успехе — одна реакция на trigger; при отказе — ничего (0 текста). **Второго канала/события нет.**
- **Контракты:** `react_moai` — аддитивное расширение (позиционные 3 аргумента совместимы); `CoordinatorDecision` (A1) — reuse полей `reaction`/`reason_code`/`target_message_id`, не дублируется; `_decision_pre_action` — то же возвращаемое 4-кортежное представление, меняется только значение эмодзи.

**Failure semantics (fail-safe):**
- Любая ошибка реакции → тихий отказ (`*`-код), никогда не текст/не raise.
- Неизвестная ошибка → `unknown` (безопасная остановка).
- Rate-limit → `rate_limited`, без повтора.
- Kill-switch OFF → legacy 🗿.
- `message_id is None` → no-op (как сегодня).

**Compatibility:** legacy-вызовы `react_moai(bot, chat_id, msg)` — без изменений; safety-net `:1409/1475` — legacy; direct-путь при OFF/тумблерах-OFF — без изменений; OFF-паритет.

**Observability (R17):** только `chat_id`/`message_id`/enum-исход/`reason_code`/эмодзи/код ошибки; без текстов/имён/ключей/промптов. Система событий/ExecutionGraph не создаётся (граница A9).

**Acceptance evidence:** тесты §9 (`tests/test_telegram_reactions_round1026.py`); обновление `tests/test_smartmodule_utils.py` (аддитивные кейсы); evidence §54.9; diff-аудит границ (Δ DDL=0, Δ каталога=0, канон 12, A7-правила/A9/§104 вне diff).

**Release-order constraints:** A8 — после A7; до A9. Внутри эпик-релиза A8 reuse (не меняет) контракты A1/A2/A3/A4/A5/A6/A7.

**Rollback boundary:** hot — `REACTION_MECHANICS_ENABLED=false` (legacy 🗿) и/или OFF соответствующего A7-тумблера; cold — `git revert` к **`e8646af`** + агрегатный анкер Эпика 3; DDL-откат не нужен (Δ DDL=0).

**Ownership верификации:** @Builder (T-3671…T-3682) → **единый @Reviewer gate** (T-3683) → @Architect merge **§90** + ADR-1026-21 Accepted (T-3684) → @PM архивация → **T-3685 = `DEFERRED_TO_EPIC`** → T-3686 handoff → A9. **@Scanner отсутствует. Owner-gate A3 — внешний.**

**Epic-release contribution:** A8 добавляет в pending epic-release Эпика 3 **механику исполнения реакции** (`setMessageReaction`: доступность/детерминированная альтернатива/отказ, корректная цель, контекстный стандартный эмодзи, no-text on error, таксономия) поверх контракта A7; агрегируется в манифест на границе эпика; пер-фича деплоя нет.

## 7. Дизайн / технические решения

### 7.1. Дом и состав (D1/D2/D11)
- **Примитив-исполнитель** — `services/smartmodule_utils.py`: аддитивный апгрейд `react_moai` (`:93–107`):
  - новые константы: `REACTION_DEFAULT="🗿"`, `REACTION_LAUGH="😂"`, `REACTION_APPROVE="👍"`, `REACTION_FIRE="🔥"`, `STANDARD_REACTION_EMOJIS`, `REACTION_FALLBACK_ORDER`, `MAX_REACTION_ATTEMPTS=2`, `REACTION_*`-коды исходов, маркеры классификации;
  - новый `def reaction_mechanics_enabled() -> bool` (env-only, default ON, никогда не бросает);
  - новые приватные функции: `_classify_reaction_error(exc)`, `_reaction_candidates(primary)` (детерминированное расширение);
  - `react_moai(..., *, reaction=None, reason_code=None) -> str` — новая механика при `reaction is not None and reaction_mechanics_enabled()`, иначе legacy.
- **Точка выбора** — `services/direct_chat_service.py` (дом reason-кодов): карта `_REACTION_BY_REASON` (reason→эмодзи), `def _reaction_for_reason(reason) -> str` (гейт kill-switch), замена возврата `REACTION_MOAI` на `_reaction_for_reason(...)` в 4 `react`-ветках `_decision_pre_action`; интеграция в `:1284`.
- **Почему не новый модуль и не новый исполнитель:** §41 требует официальный `setMessageReaction`; `react_moai` — единственный существующий call-site; второй исполнитель = дублирование/дрейф. Контекстное разнообразие — механика доставки (D5 A7→A8).

### 7.2. Псевдокод исполнителя
```
if bot is None or message_id is None: return REACTION_UNKNOWN
legacy = (reaction is None) or (not reaction_mechanics_enabled())
if legacy:
    candidates = (REACTION_DEFAULT,)          # точное pre-A8 поведение
else:
    primary = reaction if reaction in STANDARD_REACTION_EMOJIS else REACTION_DEFAULT
    alts = [e for e in REACTION_FALLBACK_ORDER if e != primary][:MAX_REACTION_ATTEMPTS-1]
    candidates = tuple([primary] + alts)
for i, emoji in enumerate(candidates):
    try:
        await bot.set_message_reaction(chat_id, message_id,
                                       reaction=[types.ReactionTypeEmoji(emoji=emoji)],
                                       is_big=False)
        return REACTION_OK
    except TelegramRetryAfter:
        return REACTION_RATE_LIMITED
    except TelegramBadRequest as exc:
        code = _classify_reaction_error(exc)
        if code == REACTION_UNAVAILABLE and i + 1 < len(candidates):
            continue
        return code
    except Exception:
        return REACTION_UNKNOWN
return REACTION_UNAVAILABLE
```
- Логи: на успех — `INFO` (`chat/msg/emoji/reason`); на отказ — `WARNING` с сохранением подстроки `"SmartModule: moai reaction failed"` + аддитивные `code=`/`reason=` (регресс-совместимость `test_smartmodule_utils`). Никогда не бросает.

### 7.3. Точки кода (ориентиры baseline)
- `services/smartmodule_utils.py:93–107` — `react_moai` + новые константы/функции.
- `services/direct_chat_service.py:801–869` — `_decision_pre_action` (замена `REACTION_MOAI` на `_reaction_for_reason(reason)`; классы/приоритеты/`action` **не меняются**).
- `services/direct_chat_service.py:1279–1285` — интеграция `reaction=pre_reaction, reason_code=pre_reason`.
- `config/settings.py:552–561` — `REACTION_MECHANICS_ENABLED: ClassVar[bool]` рядом с `DIRECT_*`.
- `services/direct_chat_service.py:132–138` — импорт новых имён из `smartmodule_utils`.

## 8. DDL / миграции / каталог — вердикт

- **Δ DDL = 0.** Новых таблиц/колонок/индексов/PG нет; SQLite остаётся **v12**.
- **Δ каталога = 0 (U9, D9).** Новых параметров/групп/вкладок **нет**; F8 **не переиздаётся**. Гейт `react`-действия — существующие A7-тумблеры. Счётчики остаются после-A7:

| Счётчик | Baseline (после A7) | Целевое | Δ |
|---|---|---|---|
| `REGISTRY` | 473 | 473 | 0 |
| Settings fields | 430 | 430* | 0 |
| categorized | 448 | 448 | 0 |
| `GROUPS` | 102 | 102 | 0 |
| `_TAB_BY_GROUP` | 100 | 100 | 0 |
| `TAB_RULES` | 21 | 21 | 0 |

\* env-only `ClassVar REACTION_MECHANICS_ENABLED` не является каталог-параметром (прецеденты `DIRECT_COORDINATOR_ENABLED`/`DIRECT_DECISION_MAKING_ENABLED`) и **не** учитывается в Settings-счётчике каталога.

- **Обратная совместимость:** сигнатура `react_moai` аддитивна; дефолты сохраняют старое поведение; миграционный откат не требуется.

## 9. Стратегия тестов

- **Единственный официальный путь (T-3671):** spy `bot.set_message_reaction` — вызов ровно один, `reaction=[ReactionTypeEmoji]`, `is_big=False`; нет custom/paid; нет `Message.react`/HTTP.
- **Доступность + альтернатива/отказ (§52.21; T-3673/T-3679):** primary `REACTION_INVALID` → альтернатива из фиксированного порядка принята (`REACTION_OK`, 2 вызова); все кандидаты `REACTION_INVALID` → `REACTION_UNAVAILABLE`, `set_message_reaction` = MAX попыток, 0 текста.
- **Нет текста на ошибку (T-3676/T-3679):** при любом отказе `send_message`/`_send_direct_answer` не вызываются (spy), исходящих сообщений 0.
- **Правильная цель + media-group (T-3675/T-3679):** A7-ветка передаёт trigger `message_id`; reply-ситуация → цель = trigger (не `reply_to_id`); `media_group_id`-сообщение → переданный `message_id` без подмены (first-non-deleted — серверное).
- **Детерминированная вариативность (U1/U3; T-3674):** один и тот же `reason_code` → одинаковый эмодзи при N повторах; разные `reason_code` (`laughter`/`emoji_reaction`/`emotion`) → разные эмодзи; `random` не вызывается.
- **Доставка выбора A7 (T-3678):** `CoordinatorDecision.reaction` == эмодзи, переданный в `set_message_reaction` (end-to-end на direct-ветке).
- **Таксономия/rate-limit/целостность (T-3677/T-3680):** `TelegramRetryAfter`→`rate_limited`, повтор **не** делается; forbidden/gone/service/unknown классифицируются; `message_id=None` → no-op; чат без прав → тихий отказ.
- **OFF-паритет (T-3681):** `REACTION_MECHANICS_ENABLED=false` → одиночная 🗿-попытка, контекстный выбор не применяется; сравнение с pre-A8.
- **R17 (T-3676):** логи содержат только id/enum/reason/эмодзи/код ошибки; приватный текст/имена/ключи отсутствуют.
- **Регресс/числа (T-3681/T-3682):** полный pytest (baseline → +N/0), JS; канон **12**; **Δ DDL=0**; **Δ каталога=0**; `APP_VERSION` **2.58.30** (без bump); `git diff --check`=0; diff-аудит границ (A7-правила §44/A9/§104/A1-контракт вне diff; `_decision_pre_action` меняет только значение эмодзи).
- **§54.9 evidence (T-3679/T-3680):** результаты тестирования реакций и молчания задокументированы (evidence.md фичи).

## 10. Deploy / rollback (EPIC_ONLY)

- **Deploy = `DEFERRED_TO_EPIC`** (T-3685): пер-фича деплоя/тега/bump нет; вклад в pending epic-release Эпика 3; `APP_VERSION` остаётся **2.58.30** (агрегатный bump 2.58.30 → 2.58.31 — на границе эпика). **@DevOps не вызывается.**
- **Hot-откат:** `REACTION_MECHANICS_ENABLED=false` → legacy 🗿; при необходимости — OFF A7-тумблера REACTIONS/IMAGE_REACTIONS (реакция не выбирается).
- **Cold-откат:** `git revert` к **`e8646af`** + агрегатный анкер Эпика 3; **DDL-откат не требуется**; F8-артефакты не меняются (Δ каталога=0). Теги/бэкапы/stash не удаляются (R18).
- **Release-order:** `A0 → A1 → A2 → A3 → A5 → A6 → A4 → A7 → A8 → A9 → A10`; A8 reuse контракты A1–A7; handoff → A9 (события `REACTION_SENT`, ExecutionGraph).

## 11. Ownership верификации / цепочка

- **Step 2 @Architect (T-3669):** `spec.md` + ADR-1026-21 (этот документ).
- **Сверка @PM (T-3670):** `PLANNING_CONSISTENT`; заполнение SC/ADR-колонок; фиксация Δ каталога=0/канон 12/Risk R2; реконсиляция `tasks.md`.
- **Build (T-3671…T-3682):** исполнитель → scope-аудит → доступность/альтернатива → источник эмодзи → цель/media-group → таксономия/no-text → права/лимиты → интеграция `reaction` → тесты ядра → §54.9/adversarial → kill-switch/регресс → diff-аудит границ.
- **@Reviewer (T-3683, единый gate):** обе линзы; REQ-A8-01…-13; §41; §44-механика; §52.21/§53.5844/§54.9; официальный `setMessageReaction` — единственный путь; доступность/альтернатива/отказ детерминированы; нет текста на ошибку; правильная цель/media-group; `reaction` A7 доставляется; A7-правила §44 не переопределены; A9 вне diff; канон 12; Δ DDL/каталог=0; OFF-паритет; risk. **@Scanner отсутствует.**
- **@Architect (T-3684):** merge **§90**; ADR-1026-21 → Accepted. **@PM:** архивация feature-папки.
- **T-3685 = `DEFERRED_TO_EPIC`; T-3686 — handoff → A9.**

## 12. Рассмотренные альтернативы (сводно; детали — ADR-1026-21)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Источник эмодзи (U1) | фиксированная 🗿; контекстная карта | **контекстная карта `reason_code→эмодзи`, 🗿 как fallback** | §44-мех «не одна и та же всегда»/«соответствие контексту»; механика делегирована A7→A8 (ADR D5); детерминизм |
| Проверка доступности (U2) | `getChat.available_reactions`+кэш; `can_react_to_messages`; try-and-fallback | **try-and-fallback (реактивно)** | нет лишнего вызова/race/stale; сервер — истина; проще и безопаснее |
| Альтернатива/отказ (U3) | случайная; фиксированный порядок; отказ без альтернативы | **фиксированный порядок, ≤2 попытки, затем тихий отказ** | §44 запрещает случайность; §41 допускает альтернативу/отказ |
| Цель (U4) | ручной резолв media-group; доверие серверу | **trigger-id, media-group — серверное** | verbatim Bot API «first non-deleted message in the group»; код не нужен |
| Ошибки (U5) | свободный текст; закрытый enum | **закрытый enum + R17-логи** | R17; §41 «не текст» |
| Rate limit (U6) | retry/sleep+повтор; пропуск | **без повтора, тихий отказ** | реакция некритична; блокировка handler |
| Эмодзи-набор (U8) | любой эмодзи; custom; курируемый стандарт | **курируемый стандартный {🗿,😂,👍,🔥}** | §41 «не любой произвольный»; боты: standard only |
| Каталог (U9) | новый тумблер; reuse A7 | **reuse A7-тумблеров, Δ=0** | §48/§48 уже реализованы A7; минимум настроек |
| Kill-switch (U10) | только A7-гейт; новый env | **новый env `REACTION_MECHANICS_ENABLED`** | пер-фича hot-откат к legacy 🗿 |
| Scope (U11) | миграция всех сайтов; direct-only | **direct-only по поведению** | нет `reason_code` на прочих сайтах; blast radius |
| Risk (U12) | R3 (+threat-артефакт); R2 | **R2** | локальная механика, fail-silently, без LLM/DDL/каталога |
| Дом механики (D11) | новый модуль; апгрейд `react_moai` | **апгрейд `react_moai`** | единственный call-site; §41 официальный путь; без второго исполнителя |

## 13. Risk-Level и усиление

- **Risk-Level: R2 (финальный).** Обоснование: A8 — **локальная механика исполнения** реакции (один существующий примитив + одна точка потребления), без нового пайплайна/LLM-вызова/DDL/каталога; любая ошибка fail-silently и **без текста**; blast radius ограничен direct-чатом и выбором эмодзи; прочие `react_moai`-сайты не меняют поведение (U11); OFF kill-switch возвращает точный legacy.
- **Что повысит до R3 (Reviewer-триггеры):** изменение поведения не-direct `react_moai`-сайтов; нарушение OFF-паритета; любой текстовый ответ на ошибку реакции; произвольный/custom/paid эмодзи; переопределение A7-правил §44/`_decision_pre_action` (action/приоритеты); утечка приватного контента в логи (R17); fallback, провоцирующий rate-limit-спам; рост числа API-вызовов без ограничения; срабатывание второго механизма `setMessageReaction` вне примитива.
- **Понижение/удержание R2:** доказанный OFF-паритет; 0 регрессий (в т.ч. `test_smartmodule_utils`); детерминизм вариативности; отсутствие текста; границы (Δ DDL/каталог=0, канон 12). **Финал — за Reviewer по фактическому diff.**
- **R3-артефакт `threat-failure-analysis.md` не требуется** (остаёмся R2); при подъёме Architect/Reviewer до R3 — обязателен.

## 14. Открытые вопросы / статус

- **U1–U12 — ✅ закрыты** решениями §4 (полные формулировки — ADR-1026-21 D1–D14).
- **C-1** (правила=A7, механика=A8) — ✅ соблюдён; A8 меняет только значение эмодзи ветки `react`.
- **Канон 12 / Δ DDL=0 / Δ каталога=0 / R2** — ✅ (§8, §13).
- **Open (не блокирует Step 2; для PM/Builder, не выдумывать требования):**
  - точные Telegram-error-маркеры (`unavailable`/`forbidden`/`gone`/`service`) — валидируются на Build по наблюдаемым ошибкам; неизвестный → `unknown` (безопасно);
  - media-group «first non-deleted» — **серверное** поведение (verbatim Bot API), локально тестируется только неизменность переданного `message_id`;
  - `can_react_to_messages` — Bot API 10.0, поле `ChatPermissions`/`ChatMemberRestricted`; в aiogram 3.31 `Chat`/`ChatFullInfo` его не несёт → проактивно не читается (реактивная классификация);
  - точное число новых pytest (baseline → +N) подтверждается фактическим прогоном Build;
  - финальные имена констант (`REACTION_*`, `_REACTION_BY_REASON`, `REACTION_MECHANICS_ENABLED`) — рабочие; изменяются только правкой spec/ADR, не Builder'ом;
  - **реконсиляция `tasks.md`** (@PM T-3670): зафиксировать Δ каталога=0, канон 12, Risk R2, SC/ADR-колонки, признание `_decision_pre_action`-значения эмодзи A8-механикой (не нарушением REQ-A7).
- **A3 owner-gate `PENDING OWNER VERIFICATION` — внешний**, A8 его не закрывает.
