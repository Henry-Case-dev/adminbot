# Ревью `57efa10a` — телеметрия формы доставки инициативы (G1–G7)

LANE_ID: REV-INIT-TELEMETRY · reviewer, read-only · 24.10.2026
Кандидат: `57efa10a851da6e485e0e2cf83b7feb56d65f6b9` (HEAD; в рабочем дереве
дополнительно только незакоммиченные PNG/evidence и мусор вне scope).
Scope: `services/mca_intents.py`, `services/mca_events.py`,
`services/direct_chat_service.py`, `services/initiative_diagnostics.py`,
`tests/test_initiative_delivery_telemetry.py`, evidence.

## Вердикт: NEEDS FIXES (функционально G1–G7 закрыты, дерево тестов не зелёное)

Код по существу решает задачу: форма доставки стала измеримой существующими
событиями, без DDL и без текста. Блокируют выпуск два пункта ниже — оба
локальные, переделывать подход не нужно.

## G1–G7 (по коду и тестам)

- **G1 — ЧАСТИЧНО.** `note_decision` пишет `delivery:chat|reply`, `tgt:`,
  `tgt_user:`, `addr:`, `corr:` + `trace_id`. Остаток: при пустом
  `l1_plan.delivery` (LLM не указала форму) токена `delivery:` нет вовсе —
  «выбранное» не фиксируется, хотя дефолт фактически `chat`. Фактическая форма
  всё равно видна в `form:` манифеста.
- **G2 — ДА.** `status = action.delivery_kind` (`reply.text`, `react.react`,
  `silent.silent`); `react` больше не выглядит как reply. Чтение legacy
  (`reply` без точки → `("reply","")`) сохранено в `_split_decision_status`,
  оба потребителя (`_decision_rows`, `_action_counts`) переведены.
- **G3 — ДА.** Манифест несёт `reply:`, `delivery:`, `form:`, `mismatch:`;
  `config_version` теперь непустой (прежний `core=..;` формат молча
  отбрасывался `_IDENT_RE`; 59 из 64 символов — в пределе).
- **G4 — ДА.** `parent_message_ref = "tg:<id>"` ставится только из
  `actual_reply_id`, который присваивается после успешной отправки с
  `reply_to_message_id`; fail-soft и `target_gone` → NULL. Проверено живым
  send-путём в тестах (`tg:555003` / `[None]`).
- **G5 — ДА.** Семь `target_*` в `REASON_CODES` (309), метки в
  `initiative_observer.reason_label` уже есть; причина отмены больше не
  теряется (`binding_code`/`code` доходят до `reason_code`).
- **G6 — ЧАСТИЧНО/С ОГОВОРКОЙ.** Отступление `entity_id → trace_id` работает и
  документировано, но реализовано в общем `_insert_event` (см. finding 2).
  Плюс ветка `plan.outcome.proceed == False` (`direct_chat_service.py:9813`)
  пишет решение без `correlation_id` — эти cancelled-события не свяжутся.
- **G7 — ДА.** Текст: `form:reply|chat` в том же `initiative_delivery_manifest`;
  реакция — тот же путь с `form:react`. Учесть: в react-событии `reply:<id>`
  означает цель реакции, не Telegram-reply (в evidence отмечено).

## Блокирующие находки

1. **BLOCKER (1 строка): устаревший пин словаря причин.**
   `tests/test_mca10b_random_applications_block_a_round1041.py:270`
   (`test_kill_switch_registry_73_and_defaults`) всё ещё ждёт
   `len(REASON_CODES) == 302`. Воспроизведено на кандидате изолированно:
   `assert 309 == 302`, `1 failed, 16 passed`. Обновлены 4 пина из 5.
   Исправление: 302 → 309 с той же конвенцией комментария.
   Перепроверка: этот файл целиком (17 passed).
2. **MEDIUM / contract drift (локально): глобальный `entity_id → trace_id`.**
   `services/mca_events.py:674-688` подставляет `entity_id` в `trace_id` для
   ЛЮБОГО события без `trace_id`, а `entity_id` без `trace_id` эмитят
   `intent_fulfilled`/`intent_abandoned` (`_emit_close_event`),
   `capability_registry`, `mca_episodes`, `mca_experience`, `database.py` и др.
   По §17.1 `trace_id` = run/correlation id; теперь туда попадают intent/episode/
   capability id — смещение семантики за пределы инициативы, тихо для тестов
   (проверок `trace_id is None` в наборе нет). Минимальная правка: ограничить
   fallback именами `initiative_sent`/`initiative_reacted` (или передавать
   `trace_id` в двух call-site Observer'а).
   Перепроверка: тест G6 + одно неinitiative событие с `entity_id` остаётся с
   `trace_id = NULL`.

## Неблокирующие замечания

- Смешанная семантика `reply:` у реакции — читать только вместе с `form:`.
- Pre-existing, вне диффа: `_execute_initiative_react` на успехе возвращает
  `status="silent"`, поэтому ветка `initiative_reacted` в Observer
  (`status == "reacted"`) недостижима, а anti-spam `sent_stamps` для реакции
  не обновляется. К G1–G7 не относится, но всплывёт при аудите реакций.
- `_parse_manifest_version` попутно починил старый парсер: прежние ключи
  `core=` не совпадали с `core_revision`, т.е. сводки всегда читались пустыми.
  Это улучшение, а не регрессия; токены с полными ревизиями не перетираются
  (fallback только при пустом `core:`).

## Числа (проверено лично)

- `tests/test_initiative_delivery_telemetry.py` — **11 passed** (совпадает).
- `REASON_CODES` — **309**; пинов на 309 четыре, один остался 302 (finding 1).
- `test_mca17c_invariants_round1047.py` + `test_asap8_initreply_binding.py` —
  **22 passed** (первый совместный прогон дал ложный сбой из-за моего
  параллельного запуска pytest; изолированно и повторно — зелено).
- Заявленные 120 и 131+1 в рамке времени не перепрогонялись; «полностью зелёный
  набор» опровергнут finding 1.
- Новых таблиц/колонок/событий/LLM-вызовов/текста в диффе нет; `build_event`
  по-прежнему режет не-whitelisted поля.

## Достаточно ли для нового окна аудита

**Да для фактической формы и расхождений:** один запрос по
`initiative_delivery_manifest` (`form:chat|reply|react`) даёт распределение
доставленного, `mismatch:<target_*|target_gone|reply_unavailable>` — причины
reply→chat, `corr:`/`trace_id` связывают решение с доставкой, `target_*` в
`reason_code` объясняют отмены.

**Чего не хватает для полной картины:**
1. покрытие — нет пары «ok-решение ↔ манифест», поэтому долю доставок без
   события (`note_delivery_manifest` fail-soft) считать нечем, кроме сравнения
   счётчиков;
2. «выбранная форма» для планов с пустым `delivery` не записана (G1-остаток);
3. cancelled-решения из ветки `proceed == False` без correlation — воронка
   «почему не отправили» свяжется с ситуацией только по времени/чату;
4. `reply:` у реакции требует чтения вместе с `form:`.
