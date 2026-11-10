# UR-F Step 1 — единый снимок доставленного хода

База: `92070d0e`; проверенный кандидат: `a8e71324`, ветка `ur/f-inspector-step1`.
Статус: **ARCHITECT_ADJUSTMENT_REQUIRED**. Риск: R2. Внешние источники не использовались.

## Замороженный контракт

1. Сборка payload сама по себе не доказывает доставку: fallback может заменить body, а вызов — не вернуться. Поэтому сборщик создаёт только `PreparedTurnPayload`, без событий.
2. После успешного возврата model-call ровно один раз запечатывается неизменяемый `DeliveredTurnSnapshot`; при отсутствии успешного receipt снимка доставки нет.
3. `DeliveredTurnSnapshot` содержит `chat_id`, `trace_id`, outbound-path, digest/внутрипроцессный final context, `included_items`, `available_item_ids`, budget/drop-факты, `delivered_quote_ids`, completeness/truncation flags и применимые финальные search/clock/style-факты.
4. `included_messages` выводится только из уникальных message-items. Memory facts и служебные блоки сообщениями не считаются; `available_messages` — размер множества уникальных доступных message IDs.
5. Цитаты выводятся только по стабильному item ID и доказанному span собственной quote-аннотации. Совпадение текста запрещено; один item в двух блоках учитывается один раз.
6. Все durable-события фактов шага 1 являются bounded-проекциями одного снимка. Сырой context остаётся только в памяти и в `mca_events` не пишется.

## Точная граница и поток данных

- Транспортная граница истины — успешный возврат `LLMClient.generate_with_metadata()` / `generate_chat()`: там уже известен фактический `sent_body` после primary/fallback.
- Composer ON и legacy budget возвращают один тип `PreparedTurnPayload`; ни `_compose_user_content`, ни legacy-path событий не эмитят.
- Fallback materializer создаёт новый prepared-вариант синхронно с адаптированным body. Неизвестная мутация body не реконструируется по тексту.
- `l2_writer`, `react`, `chat_with_tools`, `single` сохраняют только successful receipt; ручные `_mark_quote_delivery_used` удаляются.
- `chat_with_tools` протягивает body финального ответообразующего call; continuation использует исходный `l2_writer` body. Дополнительные раунды не создают второй снимок.
- Единый settler: `_settle_delivered_turn(receipt, prepared, style_outcome) -> DeliveredTurnSnapshot`; он вызывается один раз из `finally`, затем проектирует события.
- `apply_style_policy(..., emit_events=False)` возвращает итог; событие стиля выпускает только projector снимка.

## Q1 — форма receipt и обратная совместимость

Выбор: **аддитивные поля, не side channel и не замена публичных return types**.

- `LLMCompletion.sent_body: dict[str, Any] | None = None` и `LLMChatResult.sent_body: dict[str, Any] | None = None`; значение — defensive copy последнего успешного фактически отправленного body, только in-process, без сериализации/логирования.
- `ToolLoopResult` получает необязательный атрибут `sent_body=None` и протягивает body финального ответообразующего call; он остаётся подклассом `str`.
- `_l2_write_answer` возвращает `L2WriterResult`, двухэлементный tuple-compatible объект `(text, response_mode)` с атрибутом `sent_body`; существующая распаковка двух значений не меняется.
- `generate()` по-прежнему возвращает `str`; старые конструкторы dataclass работают благодаря последнему полю с default `None`. Сотни прочих callers менять не требуется.
- Direct-path `react`/`single` использует metadata-вариант реального клиента; у тестового/legacy-клиента без receipt результат допустимо имеет `sent_body=None` и не доказывает доставку.

## Q2 — `PreparedTurnPayload`, spans и identity

- `PreparedTurnPayload` содержит финальные blocks/messages этого варианта, `included_items`, `available_item_ids`, budget/drop-факты и spans.
- Spans задаются **относительно текста собственного блока**, не concatenated `sent_body`: fallback/reordering меняет порядок блоков, но не должен инвалидировать чужие offsets.
- Span обязателен для каждого identity-bearing item, влияющего на counters/attribution; у quoting item дополнительно хранится точный quote-subspan. Только quote-items недостаточны: иначе частично усечённый thread снова завысит counters.
- `available_item_ids` — `frozenset[str]` канонических namespaced IDs (`msg:`, `tg:`, `bot_output_tg:` и т. п.), не `(kind,item_id)`: один источник в thread/tail/episode обязан дедуплицироваться. `kind` и `block_kind` остаются полями `included_items`, но не частью dedup-key.

## Q3 — `style_outcome`

- На `react` style-pass не выполняется: settler получает `style_outcome=None`.
- На текстовом primary или fallback передаётся фактический финальный `StyleOutcome`, полученный после model-call; он не зависит от того, какая модельная нога вернула текст.
- При `None` projector не эмитит `style_policy` и не подставляет ложные нули/`disabled`; selection/quote projections продолжают выпускаться. Если проход выполнялся и вернул `applied=False`, это не `None` и обрабатывается существующей семантикой события.

## Q4 — bounded serializer

Projector обязан вызывать существующую функцию `services.style_policy.bounded_style_payload`; новый сериализатор не создаётся.

## Q5 — message kinds для counters

Переиспользуется существующая `_MESSAGE_BLOCK_KINDS` без второй таблицы, точный набор: `("global_tail", "global_middle", "thread", "episode")`.

## Q6 — fallback refusal и prepared-вариант

1. Adapter вернул валидный `dict` с непустым `messages`: это успешный recompose, не refusal; при успешной fallback-ноге используется соответствующий `fallback PreparedTurnPayload`.
2. Adapter вернул invalid shape/пустые `messages`: это `recompose_refused_invalid`, но не delivery refusal; `llm_client` отправляет исходный primary body, поэтому используется **primary prepared-вариант**.
3. Adapter бросил исключение: это `recompose_refused_error`, но не delivery refusal; отправляется исходный primary body и используется **primary prepared-вариант**.
Во всех трёх случаях отсутствие успешного ответа fallback-модели означает отсутствие successful receipt и отсутствие `DeliveredTurnSnapshot`; invalid/exception нельзя выдавать за «ничего не отправлено».

## Q7 — совместимость события

**Да:** `direct_turn_selection`, его payload, `policy_version`, event/stage/component и действующие limits остаются неизменными; меняется только авторитетный источник данных, поэтому API reader и БД-миграция не нужны.

## Оценка `a8e71324`

Кандидат контракту ещё не соответствует, даже при зелёной текущей проверке:

- `note_selection` эмитится внутри `_compose_user_content` из primary allocation (`direct_chat_service.py:10287-10308`) до окончательного model-call.
- Fallback меняет только `_quote_delivery["texts"]` (`9951-9953`), но уже записанные counters/blocks не пересчитывает; L2 fallback имеет отдельный adapter (`direct_execution.py:2752-2879`).
- Legacy-путь (`9211-9225`) не выпускает `direct_turn_selection`.
- Четыре ручных маркера (`5371`, `5586`, `5617`, `6025`) и `_settle_quote_delivery` (`6418`) остаются несколькими источниками истины.
- AST-инвентарь полезен как guard появления пятого call-site, но не доказывает тождество событий фактическому outbound body.

Минимальная дельта: заменить раннюю эмиссию и mutable quote-dict на prepared/receipt/snapshot. Новых продуктовых требований, событий или API-полей это не добавляет.

## Граница шагов

- **Шаг 1:** валидность JSON, полнота/cap counters, типы элементов, identity, фактическая доставка, fallback, cancellation, correlation, style facts и покрытие outbound-путей. Все дефекты 1–10 принадлежат сюда.
- **Шаг 2:** только join и API-проекция durable-событий, права, старые трассы и `null/unknown`.
- **Шаг 3:** подписи, формулировки, карточки, сворачивание и responsive UI. Rendering/wording/UI в шаг 1 не входят.
- DDL, backfill и миграция не нужны; rollback — возврат внутреннего result/settler-контракта без изменения сохранённых строк.

## Допустимые недоучёты

- Final body не выводится из identity-spans — `identity_complete=false`, спорные items/quotes не засчитываются.
- Отмена, timeout, transport/parse error после возможной отправки, но до успешного возврата — доставки не подтверждают.
- Legacy reordering или неизвестная трансформация, разрушающая span-привязку, даёт только доказуемое подмножество.
- Внутренняя провайдерская токенизация/усечение после принятия HTTP body не утверждается: контракт описывает фактически отправленное тело.
- Элемент без стабильного ID или с неоднозначной идентичностью не атрибутируется по тексту.

## Параллельность, проверка и закрытие

- `SERIALIZE` для Step 1 на `direct_chat_service.py`, `llm_client.py`, `tool_loop.py`, `direct_execution.py`, `style_policy.py`, `turn_trace.py`; текущую проверку `a8e71324` не прерывать.
- Step 2 — `BLOCKED_BY:Step1`; Step 3 — `BLOCKED_BY:Step2`.
- Проверка дельты: четыре outbound-пути, composer ON/OFF, valid/invalid/exception fallback, cancellation до возврата, одинаковые quote-тексты с разными IDs, частичное усечение и валидный bounded JSON.
- Критерий закрытия: **Step 1 принимается только когда каждый успешный `l2_writer/react/chat_with_tools/single` на primary и fallback создаёт ровно один correlated snapshot, а persisted counters, quote IDs и применимые style-факты являются его точной bounded-проекцией без единого ложноположительного события.**

Builder может приступать к этой структурной дельте без расширения требований Step 1.

CONTRACT FINAL
