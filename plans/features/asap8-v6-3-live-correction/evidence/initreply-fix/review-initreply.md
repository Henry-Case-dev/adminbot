# REV-INITREPLY — независимое ревью фикса INITIATIVE-REPLY

Вердикт: **Approved** (кандидат `77985666` fix + `1e3e5949` docs, база `24aacbd9`) → поезд 2.58.109.
Дата: 22.10.2026. Режим: read-only, фокус-ревью по брифу lanes REV-INITREPLY.

## Проверено ( independently, не по отчёту Builder )

1. **Дифф минимален** — `git show --stat 77985666`: только `services/direct_chat_service.py` (+122/-2), новый `tests/test_asap8_initreply_binding.py`, evidence-doc. Docs-коммит `1e3e5949` — только документация (честный «PENDING DEPLOY»). Сигнатура `send_text(bot, chat_id, text, **kwargs)` (`telegram_send.py:105`) не менялась; reply передаётся kwarg'ом только первому чанку — прецедент `smartmodule_utils.send_chunked_reply` (`reply_id = reply_to_message_id if index == 0 else None`) подтверждён в исходнике.
2. **Резолвер** `_initiative_reply_target`/`_initiative_ref_ids`: SQL параметризован (инъекций нет); `msg:<smart_messages.id>` → `tg_message_id` того же чата с фрешностью ≥ now-24ч прямо в WHERE; фолбэк — последний `tg_message_id` адресата (user_id) в чате ≤24ч; fail-open тотальный (ни одна ветка не бросает; ошибка резолва → WARNING + None, отправка не блокируется); мусорные токены (включая не-msg) отбрасываются, ≤4 id. Privacy R17: в логах только chat_id и msg id; содержимое не логируется.
3. **Защита**: цель старше 24ч → None → отправка без reply (SQL-уровень, тест 25ч); 400 «message to be replied not found» → ровно один повтор без reply, предикат `_is_reply_target_gone` **переиспользован** (импорт, маркер `smartmodule_utils.py:39`), не задублирован; прочие TelegramBadRequest и любые другие исключения — наверх без изменений (re-raise), контур ошибок прежний.
4. **Нетронутые пути**: ностальгия (`nostalgia_worker.py:667`, prepared_text без opportunity_row) и heartbeat → `intent_row is None` → резолв возвращает None до любого SQL (isinstance-guard) → `send_text(bot, chat_id, chunk)` байт-в-байт прежний; тест `test_nostalgia_without_addressee_sends_without_reply` подтверждает. Force-Direct/обычный reply-контур Direct в диффе отсутствует.
5. **Тесты (venv, aiogram 3.31.0)**: новый файл **5 passed**. Related независимо: f6 23p + p0-init-arch 17p + w5 vitality+gates 35p + p0-initfix 10p + smartmodule_utils 36p = **121 passed EXIT 0** (в evidence заявлено 129 — другая композиция «nostalgia»-файла; исход всех зелёный, расхождения исходов нет). mca09 block_e/off_parity + mca10b a/c = **58 passed EXIT 0** — точное совпадение.
6. **Гигиена/гейт**: чужие незакоммиченные изменения не тронуты; гейт воспроизведён: `requirements_gate.py check --map plans/features/asap8-v6-3-live-correction/requirements-map.json --stage plan` → `inventory=148 manual=75 scoped=0 errors=0`, EXIT 0.
7. **Live**: реальный reply проверяется на живой инициативе существующей 48ч телеметрией (автоматически, не owner-гейт) — соответствует PET_PROJECT-правилу; деплой-гейтом не является.

## Замечания (все NONBLOCKING)

- Фолбэк «последнее сообщение адресата ≤24ч» может привязать reply не к семантически адресованному сообщению — это задокументированный best-effort §4.1 диагностики, принят планом.
- Docstring `_initiative_ref_ids` упоминает durable `source_refs_json`; фактически durable хранит provenance-id (int) — корректно отбрасываются, а у durable-интенций нет `addressee_user_id` вовсе → детерминированно без reply (ошибочного reply из коллизии id не возникает). Косметика.
- Retry-паттерн инлайн (~6 строк) повторяет форму `_send_once` вместо вызова хелпера; предикат переиспользован, новых подсистем нет (ограничение owner-corrective соблюдено).

Блокеров нет. Evidence привязана к точному кандидату `77985666`; любые изменения до поезда инвалидируют.
