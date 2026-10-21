# FIX-INITREPLY — reply_to_message_id binding для адресатных инициатив

Лейн: FIX-INITREPLY · Дата: 22.10.2026 · База: HEAD `24aacbd9`
Дефект: `plans/owner-obs-diagnostics-2026-10-21.md` §4 (подтверждённый
инженерный дефект диагностики владельца).

## Суть

Инициативный ответ нёс `addressee_user_id` + `source_refs` до Writer/L1, но
точка отправки в `handle_initiative` звала `_tg_send.send_text(bot, chat_id,
chunk)` без `reply_to_message_id` — все инициативные отправки уходили
standalone (24/24 за 7д по журналу 18–21.10, 14 старый + 10 новый чат).

## Изменение (services/direct_chat_service.py, минимальный дифф)

1. **Резолвер «адресат → сообщение»** `_initiative_reply_target` (§4.1):
   `source_refs` (`msg:<smart_messages.id>`, ≤4, порядок сохранён; читаются
   и ephemeral-строка `build_opportunity_row`, и durable `source_refs_json`)
   → колонка `smart_messages.tg_message_id` этого же чата; фолбэк — последний
   `tg_message_id` пользователя `addressee_user_id` в чате. Best-effort,
   fail-open → None, таблиц/миграций не нужно.
2. **Передача reply в цикле чанков** (§4.2): `reply_to_message_id=...` ТОЛЬКО
   у первого чанка (прецедент `smartmodule_utils.send_chunked_reply`);
   `send_text` уже принимал `**kwargs` — сигнатура не менялась.
3. **Защита от протухшей цели** (§4.3): цель старше 24 ч
   (`_INITIATIVE_REPLY_MAX_AGE_S`) → без reply; 400 «message to be replied
   not found» к моменту отправки → ровно один повтор без reply
   (переиспользован `smartmodule_utils._is_reply_target_gone`), прочие
   ошибки — наверх без изменений.

Ностальгия/heartbeat (тот же `handle_initiative` без адресата/ссылок):
резолвер детерминированно даёт None → отправка без reply, путь прежний.
R17/privacy: в логах только chat_id/message_id; содержимое не логируется;
0 provider-вызовов, 0 сообщений в реальные чаты.

## Биндинг карты требований

В `requirements-map.json` asap8 нет строк про адресата/reply-привязку
инициативы (поиск «инициатив» × «адресат/reply/отправ/standalone» → 0 строк).
По брифу лейна фикс легитимен как confirmed defect из диагностики §4;
перевода статусов карты не требуется. Гейт plan — EXIT 0 (см. ниже).

## Верификация

- Новые тесты `tests/test_asap8_initreply_binding.py` (5):
  - CONTRACT `test_addressed_initiative_reply_binds_to_addressee_message` —
    msg-ref → tg_message_id=555001 в kwargs первого вызова;
  - CONTRACT `test_addressed_initiative_reply_only_on_first_chunk` — 3 чанка,
    reply только у первого;
  - CONTRACT `test_nostalgia_without_addressee_sends_without_reply` —
    prepared_text без opportunity_row → kwargs без reply_to_message_id;
  - REGRESSION `test_stale_target_sends_without_reply` — цель 25ч → без reply;
  - REGRESSION `test_gone_target_retries_once_without_reply` — 400 gone →
    ровно 2 вызова, второй без reply, статус sent.
- Прогон: venv (aiogram 3.31.0): 5 passed; related сьюты —
  f6/p0-init-arch/w5-vitality/w5-gates/nostalgia/p0-initfix/smartmodule_utils
  **129 passed**, mca09 block_e/off_parity + mca10b a/c **58 passed** (EXIT 0).
- Гейт: `requirements_gate.py check --map
  plans/features/asap8-v6-3-live-correction/requirements-map.json --stage
  plan` → `inventory=148 manual=75 scoped=0 errors=0`, **EXIT 0**.

## Кандидат

- Файлы: `services/direct_chat_service.py` (+122/−2),
  `tests/test_asap8_initreply_binding.py` (новый, 5 тестов).
- Коммит: `77985666` — fix(initiative): reply_to_message_id binding for
  addressed initiative replies; НЕ запушен — поезд 2.58.109 после ревью.
- Docs-биндинг: append «ФИКС ПРИМЕНЁН @77985666» в
  `plans/owner-obs-diagnostics-2026-10-21.md` §4.
