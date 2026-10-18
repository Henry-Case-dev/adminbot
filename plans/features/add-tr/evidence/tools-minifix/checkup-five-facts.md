# get_bot_health — пять независимых фактов (§ADD-TR.3 L48)

Разделение состояний «зарегистрирован ≠ показан LLM ≠ вызван ≠ вернул
данные ≠ пользователь получил ответ» (source-add-tr-2026-10-19.md, L48).
Слайс ADTR-TOOLS, кандидат 19.10.2026 (worktree, без коммита).

| # | Факт | Доказательство (код/тест) | Статус |
|---|---|---|---|
| F1 | tool **зарегистрирован** | схема `TOOL_GET_BOT_HEALTH` `services/tool_schemas.py:317-327`, канон `TOOL_CALLING_TOOLS:685`; диспетчер `tool_router.py:691`; обработчик `tool_router.py:2673-2697` | ✅ существует и раньше (не пересоздавался) |
| F2 | tool **показан LLM** | L1: resolved-подсет `_l1_tool_subset` (`direct_chat_service.py:4188`); схема `get_bot_health` уходит только когда план запросил capability `health` — тест `test_l1_seam_announce_then_execute_once` + `announce-vocabulary.txt` (`health` в «ДОСТУПНЫЕ ВОЗМОЖНОСТИ»). Legacy (L1 OFF): `active_tools()` включает его всегда | ✅ после фикса (до: L1-планировщик физически не видел capability → resolved=∅) |
| F3 | **модель вызвала** tool | unit: ровно один dispatch (`test_health_simple_tools_dispatch_returns_data_for_writer`, `test_full_handle_health_evidence_reaches_l2_writer`); прод до фикса: **0 вызовов** `TOOL_CALL get_bot_health` за всю доступную историю (recon §3) | ⏳ живые вызовы — **postdeploy** (дать «бот, как состояние сервера?» / «проверь логи» в рабочих чатах) |
| F4 | tool **вернул данные** | реальный `ToolRouter._get_bot_health` → `CheckupLogsFetcher.fetch` → `CheckupService.checkup` → отчёт: `test_health_real_executor_report_flows_to_writer_context`; существующее `test_tool_calling_round1015.py::TestGetBotHealth::test_fetch_and_checkup`. OFF: «ОШИБКА get_bot_health: модуль выключен» без fetch/LLM (`test_disabled_module_short_circuits`); реестр OFF → `disabled` + notice (`test_registry_health_off_never_silent`); сбой → честная ошибка в evidence (`test_health_failure_is_visible_not_fabricated`) | ✅ unit-контур; живой отчёт — postdeploy |
| F5 | **пользователь получил корректный ответ** | отчёт в `tool_context` → L2-user-content Writer'а: `test_full_handle_health_evidence_reaches_l2_writer` (реальный handle → L1 → tool-фаза → L2). Telegram-доставка в живом чате инструментом не логируется отдельно | ⏳ live-проверка — **postdeploy** |

## Канон «чекап» (0g) — не задет

- Триггеры: `handlers/checkup.py:60-78` (`чекап`/префикс+канонические формы),
  тест `test_canonical_checkup_trigger_intact`;
- yield Direct → 0g: `handlers/direct_chat.py:116-144`
  (`flags.checkup_enabled`), тест `test_checkup_group_stays_functional_for_direct_yield`;
- обработчик и его кулдаун/пул/фразы не изменялись (файл не в диффе лайна).

## Границы доступа и секретов (сохранены)

- RBAC/скоуп: инструмент без аргументов (`additionalProperties: false`),
  chat scope — только из доверенного `ctx.chat_id`; доступа в чужие чаты
  не появилось; гейт модуля — тот же `flags.checkup_enabled`, что у 0g.
- Секреты: отчёт чекапа — существующий выход `CheckupService`; новых
  логов/полей с текстами не добавлено (реестр хранит коды/статусы; ключи
  гейтов участвуют только как ключ in-memory-кеша, не логируются).
- Честная недоступность: capability `disabled` + `checkup_module_disabled`
  (notice Writer'у), исполнитель — «ОШИБКА get_bot_health: …», пустой
  инструментальный подсет — `tool_not_active` в `L1_CAPABILITY_REJECTED`.
