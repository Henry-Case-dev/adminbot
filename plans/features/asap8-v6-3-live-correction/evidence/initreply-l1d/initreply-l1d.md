# INITREPLY-L1D — L1 решает форму участия, транспорт исполняет (22.10.2026)

Lane FIX-INITIATIVE-L1D. Директива владельца:
`plans/features/owner-corrective-initreply-2026-10-22.md` (исправление
архитектурной ошибки 2.58.109, не новый эпик).

## Дефект 2.58.109 (подтверждён, исправлен этим лейном)

`_initiative_reply_target` (direct_chat_service.py, 2.58.109 @77985666)
детерминированно выбирал цель reply: `source_refs` → первое сообщение →
reply, фолбэк — последнее сообщение `addressee_user_id`. Транспорт принимал
смысловое решение вместо LLM — прямое нарушение §1/§4 директивы
(«наличие контекстных сообщений превращает обычную инициативу в reply»).

**Исправление:** резолвер УДАЛЁН. Форму участия выбирает L1 в существующем
плане (`L1Plan.delivery/target_message_id/target_user_id`); транспорт только
исполняет решение и технически проверяет выбранную цель (§6).

## Изменения (файл:что)

- `services/direct_l1.py` — контракт: `L1_DELIVERY_MODES=("chat","reply")`;
  `L1Plan.delivery/target_message_id/target_user_id` (нормализация
  никогда не бросает; отсутствие/мусор → обычное сообщение);
  `reply_binding_requested()` (reply включается ТОЛЬКО тройкой
  action=reply + delivery=reply + target_message_id);
  `render_window_lines(with_ids=)` — разметка `[msg:ID] [user:UID] …
  (ответ на msg:N)` (прямой чат — прежний формат, with_ids=False);
  `build_l2_plan_block(include_delivery=)` — форма доставки доезжает до
  Writer'а инициативы; `INITIATIVE_LINE` — равноправие форм, повод
  наблюдателя = предложение.
- `services/chat_prompts.py` — канон L1-планера: схема + `delivery`/
  `target_message_id`/`target_user_id` + блок «ФОРМА УЧАСТИЯ» без
  приоритетов (§1/§3); правила 1–7 байт-в-байт прежние. Прежний канон
  (прод 2.58.109) заморожен: `PREV_DIRECT_L1_PLANNER_1022` =
  SHA256[:16] `5fdc90b3f114`, 3022 символа.
- `services/prompt_migrations.py` — ступень лестницы
  `(PREV_DIRECT_L1_PLANNER_1022 → DIRECT_L1_PLANNER_SYSTEM_PROMPT)`
  (процедура ADR-1013-3: без неё прод-значение PG-ключа не ведётся на
  новый канон и контракт не доезжает до L1; вне базового WRITE_SCOPE,
  добавлено как обязательный шаг канон-процедуры — на усмотрение Reviewer).
- `services/prompt_registry.py` — FACTORY_SET бамп по SOUL-AMD.3.2:
  `c19d35a1c093 → 3507bd6f92eb` (changed = 1 блок direct.base.l1_planner);
  метка ревизии `l1-planner-r1028 → l1-planner-l1d`.
- `services/direct_chat_service.py`:
  - `plan_initiative_decision` (~:8652): окно с id/reply-связями
    (`with_ids=True`), ответы бота (`_recent_bot_replies`, инфра 47522e7b),
    allowed-реакции одной строкой (прецедент P3), адресат наблюдателя —
    контекстом; текст задачи «Предложение наблюдателя (можешь отклонить)…»;
  - `generate_initiative_reply` (~:8712): окно Writer с теми же id;
    plan-блок с формой доставки;
  - транспорт `handle_initiative` (~:9100+): удалены
    `_INITIATIVE_REPLY_MAX_AGE_S`/`_initiative_ref_ids`/
    `_initiative_reply_target`; добавлены `_validate_plan_target`
    (технические проверки §6: существует/принадлежит чату/есть tg-id/
    не устарело относительно окна контекста/соответствует адресату) и
    `_execute_initiative_react` (существующий `react_moai`);
    привязка reply — только из плана; при провале цели БЕЗ произвольной
    перепривязки: fail-soft обычная отправка (текст самостоятелен) либо
    отмена/SendRecheck-семантика (прямой ответ человеку потерял бы смысл,
    в т.ч. на 400 «message to be replied not found»);
    хардкод 24ч заменён окном контекста `limits.summary_window_hours`
    (§6: «без обоснования» — граница следует за реальным окном L1);
  - react-исход: SILENT/react более не демотируются молча: реакция
    исполняется без текста; статус `reacted`.
- `services/initiative_observer.py` — ярлыки честных кодов `target_*` в
  `REASON_LABELS`; runner учитывает статус `reacted` (свой счётчик +
  `initiative_reacted` + тот же анти-спам учёт sent_stamps/topics).
- `plans/features/soul-1/evidence/direct-runtime-assembly.txt` — P4-секция
  перегенерирована реальным дамп-скриптом: SYSTEM 4264 симв /
  `ace6246bd360`; прежние байты задокументированы в note (3022/5fdc90b3f114).

Не тронуто: антифлуд/cooldown/SendRecheck/окно/память/Core+Expression,
инфраструктура реакций, force-контракт Direct (прямой чат игнорирует
delivery-поля плана), ностальгия/heartbeat (без L1 — путь прежний).

## Тесты

- `tests/test_asap8_initreply_binding.py` — переписан на контракт L1D:
  8 кейсов §8 (CONTRACT) + регрессии 2.58.109 (source_refs ≠ команда
  reply; нет произвольной перепривязки) + ностальгия. 12 тестов, моки,
  0 provider-вызовов.
  TEST-LIFECYCLE: CONTRACT/REGRESSION owner=INITREPLY-L1D.
- `tests/test_direct_l1_l1d_contract.py` — НОВЫЙ: канон (схема/приоритеты/
  слепок 2.58.109 байт-в-байт/лестница), нормализация (мусор → без reply),
  fallback без привязки, with_ids-разметка окна, plan-блок Writer,
  INITIATIVE_LINE, граница свежести. 17 тестов.
  TEST-LIFECYCLE: CONTRACT owner=INITREPLY-L1D.
- Обновлены пины: `test_direct_l1_corrective_r1` (слепок 1021 собирается из
  замороженной базы R1022 — байты те же, SHA 99a207313889711d),
  `test_expression_isolation_followup` (фингерпринт 3507bd6f92eb),
  дамп-паритет P4 (перегенерация, не ослабление).

## Гейты/прогоны (venv aiogram 3.31.0)

- related-селект (`initiative|initreply|init_arch|initfix|w5|nostalgia|
  smartmodule|mca09|mca10b|direct_l1|prompt_migration|expression_isolation|
  composer_parity|soul1_registry|core_registry|samples_fewshot`):
  **806 passed / 0 failed**.
- requirements_gate plan (asap8-v6-3-live-correction): **EXIT 0**
  (inventory=148, manual=75, errors=0).
- syntax py_compile: OK (все изменённые файлы).

## Офлайн-пробы L1 (БЕЗ Telegram; harness `OPENCODE_WORKFLOW_SCRATCH/
initreply-l1d/verify_l1d.py`)

Реальная сборка `build_l1_context` (with_ids + INITIATIVE_LINE +
allowed-реакции + bot_replies) + реальный `parse_l1_plan`, канон L1D
(SHA256[:12] ace6246bd360). Endpoint: прод-модель `deepseek-v4-flash`
недоступна с дев-машины (apinet.cloud ConnectTimeout) → та же модель через
OpenRouter (`deepseek/deepseek-v4.1-flash`; reasoning-исключение и
max_tokens=768 — артефакт шлюза, задокументирован в harness). 8
разнородных переписок (общий спор / персональный спор / обращение-поиск /
юмор / быт без повода / бессмыслица / тред на 16 реплик / спор после
ответа бота). Промпт НЕ подгонялся под сценарии (запрет §8).

Итог (result_l1d_run3.json + result_l1d_retry.json):

| контекст | решение L1 | форма |
|---|---|---|
| общий спор о графике (7 сообщ., 3 участника) | reply **delivery=chat**, без цели | самостоятельная реплика (сценарий A) |
| персональный тезис Марка | react 😂 на [msg:406] | реакция на выбранную реплику |
| Галя ищет инструкцию | reply **delivery=reply** на [msg:501], target_user=Галя | Telegram-reply адресату (сценарий B) |
| юмор про принтер | reply **delivery=reply** на [msg:603] | ответ на конкретный бит шутки |
| быт: переговорка | silent | молчание (сценарий E) |
| бессмыслица «огурец в шапке» | silent | молчание |
| тред миграции (16 реплик) | react 👍 на [msg:916] | реакция-одобрение в длинном треде (F) |
| спор после ответа бота | silent | отказ от вмешательства |

Распределение: chat 1 / reply 2 / react 2 / silent 3 — все четыре формы
достижимы, приоритетов и пропорций не наблюдается; наличие id/участников в
окне НЕ превращает инициативу в reply (кейс 1 — прямой анти-дефект 2.58.109).
Учёт вызовов: 11 успешных LLM-вызовов (≤12), плюс задокументированные
неудачные транспортные попытки (apinet timeout; reasoning-артефакт шлюза).

## Ответ на вопрос владельца (§ отчётности)

**Как теперь L1 решает форму и почему транспорт не может подменить выбор:**
L1 в одном существующем вызове возвращает план с `action`
(reply=написать/ react / silent) и `delivery` (chat=обычное сообщение /
reply=Telegram-reply на `target_message_id` — конкретное сообщение из
размеченного окна, выбранное моделью по смысловой связи);
`target_user_id` — смысловой адресат, сам по себе reply не включающий.
Транспорт больше не содержит кода выбора: единственный путь к reply —
`reply_binding_requested(plan)`, и после него возможны только технические
проверки §6 (существует/в этом чате/есть tg-id/не устарела/соответствует
адресату). При провале проверки транспорт не выбирает другую цель: текст
самостоятелен → обычная отправка; текст — прямой ответ человеку → отмена с
переоценкой (SendRecheck-семантика). Все решения L1 журналируются
R17-safe-кодами (`l1_silent/l1_react/target_*`), реакция исполняется
существующим `react_moai`.

## Остаточный риск / для живой проверки владельцем (owner_live_checks)

- Реальное поведение форм в проде после деплоя (распределение
  delivery/reaction в журнале) — наблюдение владельца, не блокер
  (PET_PROJECT: включение готовой функции штатное).
- OpenRouter-артефакт reasoning в офлайн-пробах не влияет на прод-эндпоинт.
