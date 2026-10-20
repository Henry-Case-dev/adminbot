# FIX-25898-R1 — починка Блокера 1 ревью review-25898.md

- Дата: 20.10.2026, лейн FIX-25898-R1 (writer, без коммитов — коммитит оркестратор).
- База: кандидат `37097f7c` + правки лейна в рабочем дереве (см. список ниже).
- Скоуп: только синхронизация тестов/объявленных отпечатков/одна UI-строка.
  Логика кода не менялась (services/prompt_registry.py — только
  guard-константа, указатель потребителя и метка редакции, т.е. объявленные
  аннотации по контракту SOUL-AMD.3.2).

## Что изменено (файл → суть)

1. `tests/test_checkup_handlers.py` (3 строки ассертов) — хендлер с P0
   передаёт `chat_id=message.chat.id` (handlers/checkup.py:143-144); ассерты
   `assert_awaited_once_with(...)` обновлены на новую сигнатуру
   **с проверкой корректного значения** `chat_id=CHAT_ID`:
   - `TestCheckupTriggers::test_trigger_fetcher_called[*]` ×9 —
     `("логи", False)` → `("логи", False, chat_id=CHAT_ID)`;
   - `TestCheckupHandler::test_success_sends_report` — то же;
   - `TestCheckupHandler::test_fallback_phrase_before_checkup` —
     `("локальные логи", True)` → `(..., True, chat_id=CHAT_ID)`.
2. `tests/test_direct_chat.py::TestStyleAnchorsAndMood::test_style_anchors_section`
   — C6-якорь: владелец добавил «; настройки выражения владельца важнее
   образца» (services/direct_chat_service.py:7693-7696); ожидание теста
   обновлено байт-в-байт на новый шаблон (не ослаблено).
3. `tests/test_soul1_w4_humor_craft.py::test_common_guard_is_registered_and_carries_the_criterion`
   — перестройка H11 `humor.craft.common`: старые ассерты
   `«уместность»/«не частота мата»` заменены на строгие ассерты нового
   канона: `«причинная связность и уместность»`,
   `«не частота метафор или оскорблений»`,
   `«не растягивай на каждый ответ»` (добавлен — усиление);
   `«неприкосновенны»` (факты/числа/ссылки/суть просьбы) и ban-лист без
   изменений. Второй тест файла — fingerprint (см. п.4).
4. `services/prompt_registry.py` (только объявленные аннотации, без логики):
   - `FACTORY_SET_SHA256_12`: **`5bca81487001` → `64ec1c60e278`**.
     Отпечаток пересчитан ПРОЦЕДУРОЙ КОНТРАКТА: `factory_set_fingerprint()`
     = `sha12("\n".join(f"{block_id}::{sha12(factory_text)}" for отсортированных
     непустых фабричных текстов))` (prompt_registry.py:1417-1426); фактическое
     значение получено вызовом функции на текущей фабрике — `64ec1c60e278`
     (совпадает с независимо вычисленным в ревью). Ручных хешей нет.
     Провенанс-комментарий бампа добавлен в блок над константой
     («Бамп FIX-25898-R1 … было `5bca81487001`, стало `64ec1c60e278`»,
     SOUL-AMD.3.2).
   - Метка редакции `humor.craft.common`:
     `humor-craft-guard-w4` → `humor-craft-guard-h11` (владельческая
     перестройка H11; ни один тест метку не пинит — проверено grep).
   - Указатель потребителя `message.checkup_fallback_notice`:
     `checkup_service.py:59` → `checkup_service.py:71` (правка P0
     сдвинула строки; guard `test_registry_consumer_pointers_point_at_real_lines`
     требует реальную строку с `CHECKUP_FALLBACK_NOTICE`). Второй указатель
     `tests/test_checkup_service.py:55` валиден, не тронут.
5. `web/api/speech.py::EXPRESSION_NOTES` (одна UI-строка, поведение LLM не
   меняет) — остаток отменённой владельцем (20.10) жанровой оговорки убран:
   было «…Просьба «без мата» уважается всегда; сводки и цитаты не
   переписываются…», стало: «Настройки задают интенсивность и форму
   собственной речи; частоту определяет выбранный режим. Цитаты и чужой
   текст передаются как есть; сводки звучат тем же голосом персонажа;
   просьба «без мата» уважается всегда. Реальную частоту можно проверить
   в «Проверить вживую».». Стиль соседних строк сохранён. Синхронизация:
   `tests/test_add_exp_expression.py:615` сверяет API-ответ с константой
   (авто-зелёный); `tests/test_soul1_w6_speech_ui.py` строку не пинит
   (проверено grep); негативные байт-ассерты P0-шапки LLM-payload
   (`«не переписываются» not in HEADER`) не затронуты.

## Проверка

### Фокусированный набор (после правок)
`tests/test_checkup_handlers.py + test_direct_chat.py + test_soul1_w4_humor_craft.py +
test_soul1_registry_completeness.py + test_soul1_core_registry_api.py +
test_soul1_w6_speech_ui.py + test_unified_core_route_coverage.py +
test_add_exp_expression.py` → **328 passed / 0 failed**.

RED→GREEN подтверждён: до правок тот же набор (без direct_chat, отдельный
node id из-за класса) давал 17 failed — ровно перечисленные в ревью.

### Полный pytest (после правок)
`py -3 -m pytest -q` (без -x): **12 failed, 14632 passed, 1 skipped,
7 errors** за 651.87s.

Цель «кандидат не добавляет ни одного нового failed» — выполнена:
- все 18 новых failures ревью исчезли (11 checkup + 1 C6 + 2 humor +
  4 registry/fingerprint); passed вырос 14614 → 14632 (+18, сходится);
- остаток — ровно pre-existing/environment набор из ревью и базы `99f5672c`:
  | Тест | Атрибуция |
  |---|---|
  | `tests/test_asap7_direct_settings.py` ×2 (test_migration_v35_idempotent_twice, test_backup_guard_fires_before_pending_step) | pre-existing (timing/DDL) |
  | `tests/test_mca01_tx_task_supervisor_round1027.py::test_write_points_go_through_single_writer` | pre-existing (write-points audit drift) |
  | `tests/test_outgoing_guard_round1022.py` ×2 (TestTelegramSendWrappers) | env (ImportError aiogram InputRichMessageMedia) |
  | `tests/test_summary_asap2_failsoft_round1027.py::test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback` | pre-existing |
  | `tests/test_summary_publish_integration_round1026.py::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article` | pre-existing |
  | `tests/test_t5150_startup_migrations_round1046.py` ×5 | pre-existing (timing/log-format) |
  | `tests/test_p0_vision_ui_e2e.py` ×7 | errors, env (browser) |

Новых/изменившихся failures по сравнению с базовым набором — нет.

## Честные оговорки
- Правки `services/prompt_registry.py` — это guard-константа, метка и
  указатель-аннотация (объявленные отпечатки по контракту реестра), логика
  реестра не менялась; это потребовалось буквой задания (бамп отпечатка) и
  чинит второй registry-failure (указатель), который в ревью был отнесён к
  fingerprint-парности, но фактически вызван сдвигом строк checkup_service.
- `tests/ui_p0a_ux_speech_compact_e2e.py:261` содержит стаб-payload со
  старым текстом notes («уместность и жанр решают…») — это fixture заглушки
  UI-e2e, не ассерт на константу; не тронуто (вне скоупа находки,
  pre-existing дрейф стаба) — записано как incidental.
- Поведенческий критерий §4 (frequent/occasional) вживую по-прежнему не
  подтверждён (off-prod eval, см. ревью) — вне скоупа данного лейна,
  закрывается постдеплой F4-матрицей (Блокер 2 / ledger).
