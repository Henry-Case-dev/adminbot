# ADR-1026-21 — A8 «Telegram Reactions»: механика исполнения реакции (§41) поверх контракта A7 — официальный `setMessageReaction`, детерминированная доступность/альтернатива/отказ, контекстный стандартный эмодзи, правильная цель, no-text-on-error, env-only kill-switch, Δ DDL=0 / Δ каталога=0, границы A7/A9, R2

- **Статус:** **Accepted (merge to `plans/ARCHITECTURE.md` §90, 25.09.2026)** (T-3684 @Architect). **Accepted = решение принято и включено в pending epic-release Эпика 3; НЕ «deployed»** — release policy **EPIC_ONLY**, deployment **DEFERRED_TO_EPIC** (пер-фича деплоя/тега/bump нет; агрегатный bump **2.58.30 → 2.58.31** — на границе эпика).
- **Фича:** A8 `telegram-reactions-round1026` (Эпик 3 «Agentic Intelligence», Wave 5 — продолжение; Раунд 10.26). **P0.**
- **Тип:** backend/Telegram API — **механика** реакции (не политика): официальный `setMessageReaction`, доступность/детерминированная альтернатива/отказ, контекстный стандартный эмодзи, правильная цель, no-text-on-error. **Δ DDL = 0**; **Δ каталога = 0**; канон **12**; без LLM-вызова.
- **ТЗ-основание:** `plans/current_task.md` **§41** (`:5384–5409`, содержательные `:5388–5408`), **§44-механика** (`:5494–5501`); приёмка **§52 п.21** (`:5795`), **§53** (`:5839–5840`, `:5844`), **§54 п.9** (`:5885`); ориентиры **§52 п.16/17/20/22** (`:5785/5787/5793/5797`). **Правила §44** (`:5480–5498`) — **A7**, не переопределяются (C-1).
- **Durable-вход:** `plans/docs/agentic-audit-round1026.md` (A0, APPROVED) — EV-26/EV-32, `#epic3-reuse`, `#epic3-summary`.
- **Baseline (Step 0 @Memory, 25.09.2026):** HEAD **`e8646af`** + **UNCOMMITTED epic-release дерево A2–A7** — не трогать/не коммитить; `APP_VERSION` **2.58.30**; канон **12**; SQLite **v12**; Δ DDL=0; счётчики каталога после A7 **`473/430/448/102/100/21`**; анкер отката **`e8646af`**.
- **Связано:** **REUSE + effective-заметка** — ADR-1026-20 (A7: `action=react`, `reason_code`, `target_message_id`, `reaction`; D5 делегировал §41-механику и контекстный выбор A8); **REUSE** — ADR-1026-14 (A1 `CoordinatorDecision` — не дублировать), ADR-1026-13 (A0), ADR-1020-4/ADR-1020-1; **NOT_APPLICABLE** — ADR-1026-2 (F8 — Δ каталога=0), ADR-1013-3 (промпты); **граница** — §44-правила/A7, §49/§51/A9, §104.

## Контекст

§41 задаёт требования к **исполнению** реакции: «Использовать официальный Bot API: setMessageReaction»; «Проверять, разрешена ли реакция в конкретном чате»; «Не считать, что бот может отправить любой произвольный эмодзи»; «Если выбранная реакция недоступна, использовать разрешённую альтернативу или отказаться от реакции»; «Не превращать ошибку реакции автоматически в длинный текстовый ответ»; «Реакцию ставить на правильное сообщение»; «Не путать reply_to_id, message_id и ID предыдущего сообщения бота». §44-механика требует: «Не использовать одинаковую реакцию в любой ситуации»; «Не использовать случайность как основной механизм принятия решений»; «Реакция должна соответствовать контексту и характеру бота».

**Фактическое состояние baseline (Step 0 + карта кода).** A7 ✅ (Merge §89, ADR-1026-20 D1/D5) реализовал решение о действии: `CoordinatorDecision` (`services/direct_chat_service.py:590–624`) несёт `action`/`target_message_id`/`reaction`/`reason_code`; программная политика `_decision_pre_action` (`:801–869`) выбирает `react` на 4 ветках и возвращает **фиксированную** `REACTION_MOAI="🗿"` (`:477`). A7 **не** реализует §41-механику и переиспользует единственный примитив `services/smartmodule_utils.py::react_moai` (`:93–107`: `async def react_moai(bot, chat_id, message_id)` — 3 аргумента, жёстко `ReactionTypeEmoji(emoji="🗿")`, `is_big=False`, best-effort/fail-silently, единственный call-site `set_message_reaction`). **Разрыв T-3678:** потребитель `direct_chat_service.py:1279–1285` вызывает `react_moai(bot, chat_id, pre_target)` — **`pre_reaction`/`pre_reason` не передаются**, поле `reaction` решения не доходит до исполнителя. Прочие call-sites (без контекста A7): `handlers/youtube.py:800/815/1300`, `handlers/web.py:203`, `handlers/search.py:172`, `handlers/factcheck.py:305`, `handlers/checkup.py:148`, safety-net `direct_chat_service.py:1409/1475` — «пустой/битый ответ → 🗿-молчание».

**Проверенные внешние факты (research @Step 2):**
- aiogram **3.31.0** (`requirements.txt`: `aiogram>=3.31.0,<4.0.0`; установленная `.venv` — 3.31.0). `Bot.set_message_reaction(chat_id, message_id, reaction: list[ReactionTypeUnion] | None = None, is_big: bool | None = None, request_timeout: int | None = None) -> bool` — подтверждено `inspect.signature`; `ReactionTypeEmoji` несёт `{type, emoji}`.
- `ChatFullInfo.available_reactions`: «List of available reactions allowed in the chat. **If omitted, then all emoji reactions are allowed**» (core.telegram.org/bots/api; python-telegram-bot `ChatFullInfo`). Присутствующий список (в т.ч. пустой) ограничивает набор.
- `setMessageReaction`: «Service messages of some types can't be reacted to. … Bots can't use paid reactions.»; «If the message belongs to a media group, the reaction is set to the **first non-deleted message in the group** instead»; «as non-premium users, bots can set up to **one reaction per message**»; «A custom emoji reaction can be used if it is either already present on the message or explicitly allowed by chat administrators» (core.telegram.org/bots/api#setmessagereaction; aiogram docs 3.31).
- Ошибки: `400 Bad Request: REACTION_INVALID` (невалидный/недоступный эмодзи), `message not found`/`message to react not found` (удалено/невалидный id), `can't react to this message type` (служебное), `TOO_MANY_REACTIONS` (>1), `CUSTOM_EMOJI_NOT_ALLOWED`; `403 Forbidden` (недостаточно прав/бот заблокирован); `429 RetryAfter` (flood). Источники: GramIO setMessageReaction errors, Telegram Bot API, SO (`message to react not found`).
- `TelegramRetryAfter.retry_after: int` — подтверждено `inspect.getsource`.
- Bot API **10.0** (08.05.2026) добавил `can_react_to_messages` в классы **`ChatPermissions`** и **`ChatMemberRestricted`** (не в `ChatFullInfo`); aiogram 3.31 несёт это поле в `ChatPermissions`/`ChatMemberRestricted`.
- Апдейты реакций (`MessageReactionUpdated`/`MessageReactionCountUpdated`) — **A9**; A8 их не подписывает/не обрабатывает.

**Открытые вопросы Step 1 (U1–U12)** требуют lasting-решений; **U12 (риск)** и **U11 (scope)** — ключевые для границ. Дополнительно — закрытие разрыва **T-3678**.

## Решения

**D1. U1 — источник эмодзи: детерминированная карта `reason_code → эмодзи` из стандартного набора; A7-политика не меняется.**
- **Выбрано:** на ветках `action=react` функция `_decision_pre_action` возвращает **контекстный** эмодзи через `_reaction_for_reason(reason_code)` вместо константы `REACTION_MOAI`; `REACTION_MOAI="🗿"` остаётся **дефолтом/fallback**. Карта определена в `direct_chat_service.py` (дом reason-кодов) и использует константы-эмодзи из `smartmodule_utils`.
- **Карта (курируемый стандартный набор):**

| `reason_code` | Контекст (A7) | Эмодзи |
|---|---|---|
| `image_reaction` | смех/эмоция на **своё изображение** | 😂 (`REACTION_LAUGH`) |
| `laughter` | смех без изображения | 😂 (`REACTION_LAUGH`) |
| `emoji_reaction` | одиночный эмодзи в ответ | 👍 (`REACTION_APPROVE`) |
| `emotion` | одобрение/подтверждение (`ignore_trivial` OFF) | 🔥 (`REACTION_FIRE`) |
| иной / `None` / неизвестный | fallback | 🗿 (`REACTION_DEFAULT`) |

- **Атрибуция C-1:** §44-**правила** («когда/какую», приоритеты `react`) — **A7**, не меняются; A8 владеет **механикой** (конкретный эмодзи, доступность, доставка). Это прямо делегировано A7→A8 в **ADR-1026-20 D5** («контекстная реакция/альтернативы/отказ — §41/A8»; «разнообразие эмодзи/выбор по контексту через доступный набор — §41/A8»). A8 **не** переопределяет REQ-A7-17/-18/-19 (class/priority/`action` не меняются).
- **`CoordinatorDecision.reaction`** теперь несёт контекстный эмодзи (поле уже есть, A1/A7 — не дублируется). При `REACTION_MECHANICS_ENABLED=false` `_reaction_for_reason` возвращает `REACTION_MOAI` — OFF-лог и OFF-поведение совпадают.
- **Почему не выбирать эмодзи в исполнителе по `reason_code`:** reason-коды — дом A7-модуля, который импортирует `smartmodule_utils`; обратный импорт создал бы цикл. Выбор в `direct_chat_service` (дом кодов), доставка — в исполнителе.
- **Альтернативы:** (i) фиксированная 🗿 всегда — отклонено (§44-мех «не одна и та же всегда»/«соответствие контексту»; это дальняя волна/A8); (ii) случайный эмодзи — запрещено (§44 «не случайность»); (iii) LLM-выбор эмодзи — запрещён (нет LLM-вызова).

**D2. U2 — проверка доступности: реактивная (try-and-fallback); `getChat.available_reactions` не используется.**
- **Выбрано:** доступность разрешается **авторитетно результатом доставки**: попытка `setMessageReaction` → классификация ошибки → детерминированная альтернатива (при `REACTION_INVALID`) или тихий отказ. Это и есть §41-«проверка»: бот **никогда не предполагает**, что эмодзи разрешён, и всегда учитывает разрешение чата перед признанием реакции доставленной.
- **Анализ стоимость/race:** `getChat` — дополнительный сетевой вызов на hot-path реакции; `available_reactions` может измениться (stale-кэш), а его **отсутствие** означает «все стандартные разрешены», но **не** гарантирует приём (тип сообщения/права/служебное). Кэш+TTL добавляет состояние и точки отказа. Сервер — источник истины; повторная попытка при отказе уже даёт корректный результат без лишнего вызова.
- **Опциональный warm-кэш `available_reactions`** (read-through/TTL) — **вне scope A8** (не требуется для приёмки; при появлении — отдельное решение). Помечено genuine unknown для PM.
- **Альтернативы:** (i) реактивно (выбрано); (ii) `getChat`+кэш+TTL — отклонено (стоимость/race/состояние); (iii) `can_react_to_messages` проактивно — недоступно надёжно (поле на `ChatPermissions`/`ChatMemberRestricted`, не на `Chat`; требует `getChatMember`, лишний вызов) → реактивно (D7).

**D3. U3 — альтернатива/отказ: детерминированный порядок; ≤2 попытки; тихий отказ; без рандома.**
- `primary = reaction`, если `reaction ∈ STANDARD_REACTION_EMOJIS`, иначе `REACTION_DEFAULT`. `candidates = (primary,) + (первые (MAX_REACTION_ATTEMPTS-1) элементы `REACTION_FALLBACK_ORDER` без `primary`)`; `MAX_REACTION_ATTEMPTS = 2`; `REACTION_FALLBACK_ORDER = (😂, 👍, 🔥, 🗿)`.
- Только `REACTION_UNAVAILABLE` (`REACTION_INVALID`) допускает переход к следующему кандидату; любые иные классы останавливают цикл. Все кандидаты недоступны → `REACTION_UNAVAILABLE`, **0 реакций, 0 текста**.
- **Почему ≤2:** достаточно для §41 «альтернатива», ограничивает API-вызовы (rate-limit дружелюбно), детерминированно тестируется.
- **Альтернативы:** случайный выбор — запрещён (§44); отказ без альтернативы — допустим, но менее полезен; >2 попыток — риск лишних вызовов.

**D4. U4 — правильная цель: trigger `message_id`; media-group — серверное «первое неудалённое»; `reply_to_id`/prev-bot исключены.**
- A8 передаёт `target_message_id` (= `message.message_id`, trigger) без подмены. `reply_to_id` и id предыдущего сообщения бота **никогда** не используются как цель (§41 `:5407–5408`).
- **media-group:** Telegram сам ставит реакцию на **первое неудалённое сообщение группы**, если переданный id принадлежит медиа-группе (verbatim Bot API). **Специальный код не нужен**; тест фиксирует неизменность переданного `message_id` при `media_group_id`.
- **Служебные сообщения:** реактировать нельзя (часть типов) → классификация `service` → тихий отказ.
- **Альтернативы:** ручной резолв «первого неудалённого» в боте — отклонён (сервер уже это делает; лишний API-вызов/сложность).

**D5. U5 — таксономия ошибок: закрытый enum 7 исходов; только `unavailable` retryable; все fail-silently; R17-логи.**
- Коды: `REACTION_OK`, `REACTION_UNAVAILABLE`, `REACTION_FORBIDDEN`, `REACTION_MESSAGE_GONE`, `REACTION_SERVICE`, `REACTION_RATE_LIMITED`, `REACTION_UNKNOWN`.
- Классификация по `TelegramBadRequest.message` (lowercase-подстроки): `REACTION_INVALID`→unavailable; `not enough rights`/`CHAT_WRITE_FORBIDDEN`/`CHAT_ADMIN_REQUIRED`/`bot was blocked`→forbidden; `message to react not found`/`message not found`/`MESSAGE_ID_INVALID`→message_gone; `can't react to this message type`→service; иначе unknown. `TelegramRetryAfter`→rate_limited. Прочее → unknown.
- **Ни один исход не порождает текст** (§41 `:5402–5403`; §53 `:5839–5840`). Логи — только `chat_id`/`message_id`/enum/`reason_code`/эмодзи/краткий код ошибки; существующая строка `"SmartModule: moai reaction failed"` **сохраняется** (аддитивные поля) для регресс-совместимости `tests/test_smartmodule_utils.py`.
- **Альтернативы:** пробрасывать исключение наружу — отклонено (сломало бы best-effort/молчание); свободный текст причины в логи — запрещено (R17).

**D6. U6 — rate limits / `TelegramRetryAfter`: без повтора; `rate_limited`; тихий отказ.**
- На `TelegramRetryAfter.retry_after` повтор **не** выполняется: реакция некритична; `asyncio.sleep(retry_after)` блокировал бы handler до десятков секунд; очередь/планировщик = новое состояние/риск. Классифицируется `rate_limited`, цикл кандидатов останавливается, текста нет.
- **Альтернативы:** sleep+повтор — отклонено (блокировка); fire-and-forget-очередь — отклонено (новое состояние, вне scope).

**D7. U7 — права/типы чатов: реактивно.**
- private/group/channel/supergroup различаются доступностью; бот в ЛС реагирует на сообщения диалога; в группах/каналах права (`can_react_to_messages`, Bot API 10.0) и настройки чата могут запрещать. Проактивное чтение прав не делается (см. D2): ошибки `forbidden`/`unavailable` классифицируются, при отсутствии прав → тихий отказ.
- **Альтернативы:** проактивный `getChatMember`/`getChat` — отклонено (лишние вызовы, race; сервер — истина).

**D8. U8 — набор эмодзи: только стандартный; курируемый {🗿,😂,👍,🔥}; одна реакция.**
- `STANDARD_REACTION_EMOJIS = frozenset({REACTION_DEFAULT, REACTION_LAUGH, REACTION_APPROVE, REACTION_FIRE})`. Передаётся ровно один `ReactionTypeEmoji`; `ReactionTypeCustomEmoji`/`ReactionTypePaid` не используются; списки >1 не формируются (§41 «не любой произвольный»; боты — standard only, custom/premium/paid запрещены). Все 4 эмодзи входят в стандартный reaction-набор Telegram.
- Исполнитель фильтрует кандидатов по `STANDARD_REACTION_EMOJIS`; не-наборный primary → `REACTION_DEFAULT`.
- **Альтернативы:** произвольный эмодзи — запрещён; custom emoji — отклонён (путаница «уже на сообщении/разрешён админом», §41).

**D9. U9 — настройки/каталог: Δ каталога = 0; reuse A7-тумблеров; F8 не переиздаётся.**
- Гейт `react`-действия — существующие A7-параметры `CHAT_DECISION_REACTIONS_ENABLED`/`CHAT_DECISION_IMAGE_REACTIONS_ENABLED` (`param_catalog.py:856–864`, группа `flags_decision_making`). Новых параметров/групп/вкладок **нет**; `REGISTRY 473` / Settings `430` / categorized `448` / `GROUPS 102` / `_TAB_BY_GROUP 100` / `TAB_RULES 21` — **без изменений**. F8-артефакты не переиздаются.
- env-only `REACTION_MECHANICS_ENABLED` — `ClassVar` settings, **не** каталог-параметр (прецедент `DIRECT_COORDINATOR_ENABLED`/`DIRECT_DECISION_MAKING_ENABLED`), счётчик не растёт.
- **Альтернативы:** новый тумблер «контекстные реакции» — отклонён (минимум настроек; §48 уже покрыт A7).

**D10. U10 — kill-switch: `REACTION_MECHANICS_ENABLED` (env-only, default ON); OFF → legacy 🗿.**
- `config/settings.py` рядом с `DIRECT_COORDINATOR_ENABLED:552`/`DIRECT_DECISION_MAKING_ENABLED:560`: `REACTION_MECHANICS_ENABLED: ClassVar[bool] = _env_bool("REACTION_MECHANICS_ENABLED", True)`. Резолв per-call, никогда не бросает.
- **OFF → legacy-поведение:** одиночная попытка фиксированной 🗿, best-effort, без контекстного выбора/fallback/таксономии; `_reaction_for_reason` также возвращает 🗿 (лог = реально отправленному эмодзи). Hot-откат к pre-A8.
- **Альтернативы:** только A7-гейт без отдельного switch — отклонён (нужен пер-фича hot-откат механики, не трогая политику); каталожный kill-switch — отклонён (Δ каталога).

**D11. U11 — scope: direct-only по поведению; общий примитив апгрейдится обратносовместимо.**
- `react_moai` расширяется **аддитивно** (`*, reaction=None, reason_code=None`); позиционные 3 аргумента сохранены. Новые возможности активируются только при `reaction is not None` (A7-ветка). Прочие сайты (`youtube:800/815/1300`, `web:203`, `search:172`, `factcheck:305`, `checkup:148`, safety-net `direct_chat_service:1409/1475`) зовут legacy-форму → **поведение байт-в-байт** (🗿, одиночная попытка, best-effort).
- **Их миграция — вне scope:** нет `reason_code`-контекста; это «сигнал молчания» после пустого/битого ответа, а не контекстная реакция A7. Ценность апгрейда для них (контекстное разнообразие) не оправдывает расширение blast radius.
- **Альтернативы:** мигрировать все сайты — отклонено (риск/дифф без продукта); второй исполнитель/обёртка только для direct — отклонён (дублирование примитива; достаточно аддитивных параметров).

**D12. U12 — Risk: R2 (финальный); R3-артефакт не требуется; escalation-триггеры.**
- **R2-обоснование:** локальная механика (один примитив + одна точка потребления), без LLM-вызова/DDL/каталога/нового пайплайна; любая ошибка fail-silently и **без текста**; blast radius ограничен direct-чатом и выбором эмодзи; прочие сайты не меняют поведение (D11); OFF-kill-switch → точный legacy.
- **Повышает до R3 (Reviewer-триггеры):** изменение не-direct `react_moai`-сайтов; нарушение OFF-паритета; текст на ошибку реакции; произвольный/custom/paid эмодзи; переопределение A7-правил §44/`_decision_pre_action` (action/приоритеты); утечка приватного контента (R17); rate-limit-спам от fallback; второй механизм `setMessageReaction`.
- **R3-артефакт (`threat-failure-analysis.md`) при R2 не требуется**; при подъёме — обязателен.
- **Альтернатива R3** — отклонена (нет кор-смены поведения/AMEND пайплайна/каталога; A7 уже покрыл кор-политику под R3).

**D13. T-3678 — доставка `reaction`/`reason_code` из решения A7 в исполнитель.**
- В `direct_chat_service.py:1279–1285` ветка `pre_action == ACTION_REACT`: `await react_moai(bot, chat_id, pre_target, reaction=pre_reaction, reason_code=pre_reason)`. `pre_reaction`/`pre_reason` уже вычисляются A7 (`:1262–1273`) и передаются в `build_coordinator_decision` (`:1430`); `CoordinatorDecision.reaction` уже несёт `pre_reaction` при `action=react` (`:763`). **Контракт A1 не дублируется**; A7-политика (классы/приоритеты/`action`) не меняется; `reason_code` в чат не выводится.
- **Альтернативы:** строить эмодзи в исполнителе без проброса — отклонено (поле уже есть; нарушило бы «доставляй выбор A7»).

**D14. Границы (verbatim-critical).**
- **§44-правила** (`:5480–5498`) = A7 — **не переопределяются** (C-1); A8 меняет только **значение эмодзи** уже выбранной ветки `react`.
- **A9** (§49/§51): `REACTION_SENT`/`MESSAGE_IGNORED`, ExecutionGraph, Mini App, апдейты реакций — **вне diff**.
- **A10** (§52–§54): агрегатный gate — вне A8 (ориентиры §52.21/§53/§54.9 учтены как REQ).
- **A1:** `CoordinatorDecision` — **не дублировать** (reuse `reaction`/`reason_code`/`target_message_id`).
- **A2/A3/A4/A5/A6** — не переписываются.
- **Канон 12** — без нового инструмента; `action` — не tool; JSON-схемы не меняются.
- **Нет LLM-вызова; Δ DDL=0; Δ каталога=0; §104 `generate_image` — no-go; R17-логи; EPIC_ONLY/@DevOps не вызывается.**

## Санкции и вердикты (verbatim-critical)

- **Канон:** **НЕ расширяется.** `TOOL_CALLING_TOOLS == 12`; новый инструмент не вводится.
- **Δ DDL = 0.** SQLite остаётся **v12**; новых таблиц/колонок/индексов/PG нет.
- **Δ каталога = 0.** Новых параметров/групп/вкладок нет; F8 **не переиздаётся**; счётчики `473/430/448/102/100/21` без изменений.
- **Промпты:** ADR-1013-3 = **NOT_APPLICABLE** (промпты/JSON-схемы не меняются).
- **Обратный путь:** `REACTION_MECHANICS_ENABLED=false` → legacy 🗿; при необходимости A7-тумблер REACTIONS/IMAGE_REACTIONS OFF → реакция не выбирается; cold — `git revert` к **`e8646af`** + агрегатный анкер; DDL-откат не нужен.
- **Release policy:** **EPIC_ONLY** → deployment **DEFERRED_TO_EPIC**; @DevOps не вызывается; пер-фича тег/bump нет; `APP_VERSION` остаётся **2.58.30** (агрегатный bump 2.58.30 → 2.58.31 — на границе эпика).
- **§104 `generate_image`** — no-go (вне diff).

## AMEND / REUSE-карта

| ADR / артефакт | Статус в A8 | Суть |
|---|---|---|
| **ADR-1026-20** (A7 Decision Making, D1/D5) | **REUSE + effective-заметка** | A8 потребляет `action=react`/`reason_code`/`target_message_id`/`reaction`; исполняет делегированную §41-механику; поле `reaction` теперь несёт **контекстный** эмодзи (механика), политика «когда/какую» (правила §44) **не меняется**; REQ-A7-17/-18/-19 сохранены |
| **ADR-1026-14** (A1 `CoordinatorDecision`) | **REUSE / граница** | контракт не дублируется; A8 использует его поля как есть; второй координатор не создаётся |
| **ADR-1026-15/-16/-17/-18/-19** (A2/A3/A5/A6/A4) | **REUSE / граница** | не переписываются; вне diff |
| **ADR-1026-13** (A0) | **REUSE (ориентиры)** | durable-аудит/anti-duplication; EV-26/EV-32 |
| **ADR-1026-2** (F8-переиздание) | **NOT_APPLICABLE** | Δ каталога = 0 → F8 не переиздаётся |
| **ADR-1020-4 / ADR-1020-1** | **REUSE** | канон/ID-политика |
| **ADR-1013-3** | **NOT_APPLICABLE** | промпты не меняются |
| **§44-правила / A7** | **не переопределяются** | C-1: правила=A7, механика=A8 |
| **§49/§51 / A9** | **граница** | события/ExecutionGraph/апдейты реакций — вне diff |
| **§104** | **no-go** | `generate_image` не трогать |

| Решение | Задачи (`tasks.md`) |
|---|---|
| D1 (U1: источник эмодзи, C-1) | T-3671, T-3674, T-3678 |
| D2 (U2: доступность реактивно) | T-3673, T-3677 |
| D3 (U3: порядок/отказ) | T-3673 |
| D4 (U4: цель/media-group) | T-3675 |
| D5 (U5: таксономия/no-text) | T-3676 |
| D6 (U6: rate limits) | T-3676, T-3677 |
| D7 (U7: права/типы) | T-3677 |
| D8 (U8: стандартный набор) | T-3673, T-3674 |
| D9 (U9: Δ каталога=0) | T-3671, T-3681 |
| D10 (U10: kill-switch) | T-3681 |
| D11 (U11: scope direct-only) | T-3672, T-3678 |
| D12 (U12: R2) | T-3670, T-3683 |
| D13 (T-3678: проброс reaction) | T-3678 |
| D14 (границы) | T-3682 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Источник эмодзи (U1) | фиксированная 🗿; контекстная карта; LLM | **карта `reason_code→эмодзи`** | §44-мех «не одна и та же всегда»/«контекст»; делегировано A7→A8 (D5 A7); детерминизм; без LLM |
| Доступность (U2) | `getChat`+кэш; `can_react_to_messages`; try-and-fallback | **try-and-fallback** | нет лишнего вызова/race/состояния; сервер — истина |
| Альтернатива/отказ (U3) | случайно; фиксированный порядок; без альтернативы | **фиксированный порядок, ≤2** | §44 запрещает случайность; §41 допускает альтернативу/отказ |
| Цель (U4) | ручной media-group; доверие серверу | **trigger-id, сервер** | verbatim Bot API «first non-deleted» |
| Ошибки (U5) | текст; закрытый enum | **enum + R17-логи** | §41 «не текст»; R17 |
| Rate limit (U6) | sleep+повтор; очередь; пропуск | **пропуск без повтора** | реакция некритична; без блокировки |
| Эмодзи-набор (U8) | любой; custom; курируемый | **{🗿,😂,👍,🔥} standard** | §41 «не произвольный»; боты: standard only/1 реакция |
| Каталог (U9) | новый тумблер; reuse A7 | **reuse, Δ=0** | §48 закрыт A7; минимум настроек |
| Kill-switch (U10) | только A7-гейт; новый env | **`REACTION_MECHANICS_ENABLED`** | пер-фича hot-откат |
| Scope (U11) | миграция всех сайтов; direct-only | **direct-only** | нет reason-контекста; blast radius |
| Дом механики | новый модуль; апгрейд `react_moai` | **апгрейд `react_moai`** | единственный call-site; §41 официальный путь |
| Deploy | пер-фича; EPIC_ONLY | **EPIC_ONLY (deferred)** | агрегат эпика |
| Риск (U12) | R3; R2 | **R2** | локальная механика, fail-silently, без LLM/DDL/каталога |

## Последствия

- §41-механика реализована: исполнение — единственный официальный `setMessageReaction`; доступность разрешается реактивно; недоступная реакция → детерминированная альтернатива или тихий отказ; ошибка реакции **никогда** не становится текстом.
- Реакция ставится на **правильное** сообщение (trigger); media-group обрабатывается сервером; `reply_to_id`/prev-bot не путаются.
- Эмодзи **контекстный** (не всегда 🗿): `laughter/image_reaction→😂`, `emoji_reaction→👍`, `emotion→🔥`, fallback/дефолт → 🗿; выбор детерминирован, без случайности; A7-правила §44 не переопределены.
- Разрыв **T-3678** закрыт: `reaction`/`reason_code` решения A7 доставляются в исполнитель; контракт A1 не дублирован.
- Прочие `react_moai`-сайты не изменили поведение (U11); OFF kill-switch → точный legacy; канон **12**; **Δ DDL=0**; **Δ каталога=0**; F8 не переиздаётся.
- Риск **R2**; hot-откат env-OFF; cold — `git revert` к `e8646af`; deploy `DEFERRED_TO_EPIC`; handoff → A9 (события `REACTION_SENT`, ExecutionGraph).

## Ссылки

- `plans/features/telegram-reactions-round1026/{spec.md, tasks.md}` (spec — Step 2 T-3669; сверка — @PM T-3670).
- Durable-аудит: `plans/docs/agentic-audit-round1026.md` (EV-26/EV-32; `#epic3-reuse`, `#epic3-summary`).
- ТЗ: `plans/current_task.md` §41 (`:5384–5409`), §44 (`:5476–5501`); §52 п.16/17/20/21/22 (`:5785/5787/5793/5795/5797`), §53 (`:5839–5850`), §54 п.8/9 (`:5884–5885`).
- A7 (вход): ADR-1026-20 (`plans/archive/decision-making-round1026/adr-1026-20-decision-making-policy-and-action-contract.md`); Merge **§89**.
- Код (baseline `e8646af` + незакоммиченный epic-release A2–A7): `services/smartmodule_utils.py` (`react_moai:93–107`; импорты `settings`/`TelegramBadRequest`/`TelegramRetryAfter` уже присутствуют); `services/direct_chat_service.py` (`REACTION_MOAI:477`, `REASON_*:480–501`, `CoordinatorDecision:590–624`, `_decision_pre_action:801–869` (react-ветки `:832/839/847/859`), потребитель `:1257–1285`, `:1430`, safety-net `:1409/1475`, импорт `:132–138`); `config/settings.py` (`DIRECT_COORDINATOR_ENABLED:552`, `DIRECT_DECISION_MAKING_ENABLED:560`); `services/param_catalog.py` (`CHAT_DECISION_*:856–864`); прочие call-sites: `handlers/youtube.py:800/815/1300`, `handlers/web.py:203`, `handlers/search.py:172`, `handlers/factcheck.py:305`, `handlers/checkup.py:148`.
- Тех-контекст/версии: `requirements.txt` (`aiogram>=3.31.0,<4.0.0`); aiogram **3.31.0** (`Bot.set_message_reaction`/`ChatFullInfo.available_reactions`/`ChatPermissions.can_react_to_messages` — verify `inspect`); core.telegram.org/bots/api (`setMessageReaction`, `ChatFullInfo`, changelog **Bot API 10.0** 08.05.2026 — `can_react_to_messages` в `ChatPermissions`/`ChatMemberRestricted`).
- Архитектура: `plans/ARCHITECTURE.md` §89 (A7); ожидаемый merge — **§90** (следующий свободный; §91+ численно не заняты заголовками разделов).
- Точка отката: коммит **`e8646af`** (пер-фича тега не создаётся — `EPIC_ONLY`).
