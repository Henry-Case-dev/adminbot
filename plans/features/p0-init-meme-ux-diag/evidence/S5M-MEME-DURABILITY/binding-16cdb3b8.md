# P0IM-ID-FINISH — durable-запись терминальной строки попытки (кандидат `16cdb3b8`)

> **CORRECTION (Builder, 12.11.2026).** Утверждение ниже «окно закрывается
> переносом при следующей записи в этом процессе» **неверно для production**:
> реестр удержания жил на экземпляре `SqliteQuotaLedger`, а `open_ledger`
> (`services/meme_initiative.py:374`) создаёт новый экземпляр на каждый проход
> (наблюдатель `:2029`/`:2090`, `/meme`, «Публикации», отчёты, диагностика).
> Следующий проход начинал с пустым списком, поэтому после отказа ОБОИХ носителей
> строка не доезжала ни до журнала, ни до спула даже после восстановления
> носителей: единственным следом оставалась ERROR-строка. Принятым остаточным
> окном является только смерть процесса при мёртвых носителях.
> Исправлено в `926b093a` (реестр на процесс, ключ — путь журнала, один замок);
> актуальная привязка — `../final-train/binding-durability-926b093a.md`.
> Остальной текст ниже сохранён без изменений.

**Срез:** `RW-D4-BOTH-WRITE-FAIL` + `P0IM-ID-CONC`, эпик `P0-INIT-MEME-UX-DIAG`.
**Решение:** `plans/features/p0-init-meme-ux-diag/architecture-identity.md` §1–§2.
**Кандидат:** `16cdb3b82424bfebb7594bfe8cc71a49a09bb879`, ветка
`fix/meme-attempt-durability`, база — production `6c11fc08` (2.58.194).
**Область:** только `services/meme_initiative.py` + `tests/test_evol014_meme_initiative.py`.
`services/initiative_diagnostics.py` не тронут (другая полоса), читатели,
группировка, формат спула, схема, бронь и маркер приоритета не менялись.
**Как проверялось:** штатные pytest-серии + проба на реальном файле SQLite
(журнал `meme_initiative_attempt` + спул `<db>.attempts.pending.jsonl`), логи
перехвачены `caplog`/handler. Чаты не задействованы, production не трогался.

---

## 1. Что добавлено (ровно решение Архитектора)

- `_spool_payload(row)` — 11 существующих полей вынесены из `_spool_attempt` и
  переиспользованы в двух местах: durable-спул и аварийный ERROR-лог;
  `SPOOL_FIELDS` фиксирует набор, формат не изобретался.
- `record_attempt`: после отказа журнала и спула строка удерживается в
  `self._unpersisted` (`ATTEMPT_UNPERSISTED_MAX = 200`), вытеснение самой
  старой строки сопровождается её ПОЛНОЙ ERROR-записью.
- `_retry_unpersisted()` в начале `record_attempt` (после
  `_flush_pending_attempts()`): на строку одна попытка журнала → при отказе
  одна попытка спула → успех любого носителя убирает строку; не более
  `ATTEMPT_SPOOL_BATCH` строк за вызов; не бросает.
- Схема/таблицы/очередь/планировщик/флаг/промпт/модель не менялись.

## 2. Наблюдаемые значения (проба, оба носителя выключены)

| величина | `6c11fc08` (было) | `16cdb3b8` (стало) |
|---|---|---|
| удержанных строк в процессе | нет механизма (`None`) | `1` |
| спул-файл | нет | нет (он тоже выключен) |
| видимых строк читателю, пока строка удержана | `[]` | `[]` |
| ERROR-записей о потере | 1 | 1 |
| в записи есть полный JSON строки | **нет** | **да** |
| `attempt_id` в логе | `attempt-0123` (усечён до 12) | `attempt-0123456789abcdef` |
| `outcome` в логе | нет | `published` |
| `reason_code` в логе | нет | `sent` |
| `publication.output.tg_message_id` в логе | нет | `4321` |
| после возврата носителя читатель видит | `['attempt-after-carrier']` | `['attempt-after-carrier', 'attempt-0123456789abcdef']` |
| удержано после переноса | — | `0` |

## 3. По свойствам из задания

1. **Журнал упал, спул жив** — строка в спуле, удержания нет
   (`_unpersisted == []`), читатель её видит; поведение прежнее
   (`test_journal_failure_keeps_the_row_in_the_spool_without_holding`).
2. **Оба упали** — удержана; следующая запись сначала переносит её:
   `attempts(-100)` даёт `held-1` и `held-2`, `_unpersisted == []`, повторная
   запись того же `attempt_id` — no-op (ровно один раз)
   (`test_both_carriers_fail_hold_the_row_then_flush_it_exactly_once`).
3. **Оба упали, повтора не было** — ERROR содержит `row=<JSON>`; проверено, что
   JSON парсится, `attempt_id` не усечён (`attempt-0123456789abcdef`),
   присутствуют `outcome`, `reason_code`, `detail` с `attempt_mode` и
   `publication.output.tg_message_id`, набор полей равен `SPOOL_FIELDS`
   (`test_both_carriers_fail_log_the_full_row_without_truncation`).
4. **Что видит read-model, пока строка удержана** — durable-читатель
   показывает ПРЕДЫДУЩУЮ попытку (`['older']`), удержанной строки в ответе нет
   вовсе: она не подделывается и не появляется половинчатой; после переноса
   `['after', 'held', 'older']`. **Держится такая гарантия:** удержанная строка
   не теряется (полный payload в логе) и переносится в первый освободившийся
   носитель при следующей записи в этом процессе; до переноса карточка
   показывает предыдущую попытку — это принятое остаточное окно
   `RW-D4-BOTH-WRITE-FAIL` (architecture-identity.md §1), а не выданная за
   правду «последняя» попытка
   (`test_held_row_is_not_fabricated_into_the_read_model`).
5. **Потолок 200** — 201 удержанная строка: в списке 200 (`cap-001…cap-200`),
   вытесненная `cap-000` записана в лог ПОЛНОСТЬЮ (`evicted over cap=200`,
   JSON с `SPOOL_FIELDS`)
   (`test_unpersisted_cap_logs_the_oldest_in_full`).
6. **P0IM-ID-CONC** — две попытки в разных чатах с одинаковым `ts` дают две
   группы, чтение изолировано (`attempts(-100)`/`attempts(-101)`), склейки нет;
   два конкурирующих холдера в одном чате (живой `sending` + претендент) дают
   две терминальные строки с разными родителями (`sent` и
   `publication_in_flight`), третьей псевдо-группы `meme:row:{id}` нет,
   `incomplete_historical=False`, обе строки на месте. Претендент-автомат
   честно получает `publication_conflict` + `detail=claim_held` — семантика
   брони не менялась (`test_id_conc_aggregator_keeps_chats_and_competitors_apart`).
   Предусловие **ID5** (один процесс-писатель на файл журнала) названо в
   докстринге теста; реальная гонка двух процессов вне контракта и не
   моделировалась.

## 4. Мутации

| мутация | что сломано | красных |
|---|---|---|
| M1 | убран `self._retry_unpersisted()` из `record_attempt` | 2: `test_both_carriers_fail_hold_the_row_then_flush_it_exactly_once`, `test_held_row_is_not_fabricated_into_the_read_model` |
| M2 | ERROR-запись возвращена к `attempt[:12] + chat/stage/error` | 2: `test_both_carriers_fail_log_the_full_row_without_truncation`, `test_unpersisted_cap_logs_the_oldest_in_full` |
| M3 | вытеснение за потолком без записи (`pop(0)` молча) | 1: `test_unpersisted_cap_logs_the_oldest_in_full` |

## 5. Прогоны

- `tests/test_evol014_meme_initiative.py` — **56 passed** (в файле +6 новых).
- Серия 15 файлов мемов/инициативы/публикаций/диагностики —
  **362 passed, 4 failed**; все четыре (`test_act_on_opportunity_conflict_defers_to_intent`,
  `test_evaluate_phase_precheck_blocks_before_llm`,
  `test_t1_nostalgia_delegated_refusal_sends_nothing`,
  `test_t5_every_text_send_site_passes_publish_guard`) воспроизводятся
  идентично на базе `6c11fc08` (4 failed / 56 passed там и там) — текстовый
  путь инициативы, кандидатом не затронут.

## 6. Что этим кандидатом НЕ доказано

- Смерть процесса, пока строка удержана: единственный след — полная ERROR-запись
  (принятое остаточное окно `RW-D4-BOTH-WRITE-FAIL`, запись в
  `residual_windows` — задача PM/Architect, не Builder).
- Реальная файловая авария (диск/права/IO) проверялась подменой обоих носителей,
  а не физическим отказом диска; транзиентный лок покрыт существующими тестами.
- Видимость удержанной строки через read-model ДРУГОГО экземпляра журнала: её
  нет по конструкции (список живёт на экземпляре — решение Архитектора §1 п.2);
  окно закрывается переносом при следующей записи в этом процессе.
- Гонка двух процессов-писателей (ID5) не моделировалась: это предусловие
  контракта, а не свойство кода.
