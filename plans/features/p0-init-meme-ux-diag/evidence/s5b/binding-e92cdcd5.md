# S5b — оплаченное изображение при `publisher_not_bound` (кандидат `e92cdcd5`)

**Срез:** S5b, эпик `P0-INIT-MEME-UX-DIAG`.
**Кандидат:** `e92cdcd5caedb93dee865e9a819ac8b386787b52` (ветка `init/meme-s5b`,
база — `1dcbebca`, на которой одобрен S5; история не переписана).
**Строки карты:** `P0IM-S5B-NODISCARD`, `P0IM-S5B-DELIVERY-FACT`,
`P0IM-S5B-QUOTA` (источник — строки 27/83/120
`plans/owner_inputs/2026-11-11-p0-init-meme-ux-diag-corrective-excerpt.md`).
**Дефект:** R0 `D6`, `evidence/r0/diagnosis-2.58.188.md` §6 — 6 случаев
`publish_blocked / publisher_not_bound` за 7 дней, каждый с оплаченным
изображением и израсходованной квотой.
**Как проверялось:** штатный pytest на реальных объектах (`DatabaseService`,
журнал квоты SQLite, бронь публикации, файл артефакта; подменены только LLM,
image-провайдер и отправка в Telegram), JS-стенд
`tests/js/initiative_ui_rework_test.js` на реальном `web/app.js`, Playwright-прогон
реального UI и независимая проверка отрисованной карточки живым браузером.
Сообщения в чаты не отправлялись, production не трогался.

---

## 1. Где жил дефект (код `1dcbebca`)

`services/meme_initiative.py`, прямой авто-путь:

| строка | что было |
|---|---|
| 3126-3145 | слот квоты резервируется ДО вызова провайдера |
| 3150-3187 | провайдер вызван, байты получены, `ledger.mark(provider_called)` — слот списан |
| 3346-3355 | `if not allowed or sender is None:` → `_drop_claim(SKIP_PUBLISH, detail="publisher_not_bound")` → `_cancel` → байты просто исчезают |

Отложенный путь (`_deliver_deferred_row`, 2580-2585) вёл себя так же: при
`sender is None` удалял файл и закрывал строку.

Почему отправителя нет — штатная причина, а не поломка конфигурации:
`services/initiative_observer.dispatch_event` (событийный тик по живому
сообщению) берёт бота из `_service_attr("bot")`, а у `DirectChatService`
такого атрибута нет вовсе → `_meme_sender()` возвращает `None`, и любой
авто-мем, дошедший до публикации из событийного тика, падал в
`publisher_not_bound`.

## 2. Что изменено

**`services/meme_initiative.py`**

1. `P0IM-S5B-NODISCARD`: при `sender is None` (авто-режим) результат уходит в
   СУЩЕСТВУЮЩИЙ durable-механизм B1 — `defer_generated_meme` (`task_jobs`
   `kind=meme.pending_publish` + файл байтов). Затем бронь отпускается и
   попытка закрывается `publish_blocked / publisher_not_bound` с фактами
   `publication.artifact = {reason, bytes, preserved, deferred_job_id}` и
   `publication.delivery = "not_sent"`. Если durable-путь недоступен
   (`_task_store is None`), пишется `preserved=false` — потеря видна, а не
   замалчивается. Новых таблиц, очередей и планировщиков нет: доставку
   выполняет тот же тик (`on_initiative_cycle` → `deliver_deferred_all`).
2. Отложенная строка при `sender is None` больше НЕ терминальна: бронь
   отпускается, строка возвращается в `queued` (`_wait`), файл цел, строк
   журнала нет (ожидание — не попытка). Срок ограничен существующей
   ретенцией (`expires_at` = собственный кулдаун механизма), после него —
   честный `deferred_publication_expired` с `delivery="not_sent"`.
3. `P0IM-S5B-QUOTA`: `SqliteQuotaLedger.slot_delivery()` разделяет списанные
   слоты по факту ПОДТВЕРЖДЁННОЙ отправки (журнал попыток того же файла:
   `outcome='published'` у того же `job_id`). `quota_view()` отдаёт
   `delivered`, `not_delivered`, `not_delivered_reasons`. Списание
   (`COUNTED_STATUSES`) НЕ изменено.
4. `attempt_cause_code()` — точный код причины из фактов терминальной строки
   (`publisher_not_bound` живёт в `detail`, а `reason_code` там общий
   `publish_blocked`).

**`services/initiative_diagnostics.py`**

- `P0IM-S5B-DELIVERY-FACT`: новое состояние оси `not_delivered`; `delivery_block`
  несёт `reason_code`; `LAST_DELIVERY_FIELDS` расширен на `reason_code`.
  `_meme_last_closure()` читает факт доставки терминальной строки самой свежей
  попытки, `_apply_attempt_closure()` применяет его к оси: закрытая без
  отправки попытка читается как «не доставлено · <причина>», а `confirmed`
  (реальная отправка) не переписывается.
- `quota_block()`/`QUOTA_FIELDS`: у механизма с фактами доставки появились
  `delivered` / `not_delivered` / `not_delivered_reasons`; у механизма без них
  (текст) — `null`/пусто, а не «ноль неотправленных».

**`web/app.js`**: подпись `not_delivered` = «не доставлено», текст оси с
причиной (`iniDeliveryAxis`), приписка квоты «израсходовано без отправки: N
(причина)» в карточке мемов своего чата и в режиме «другой чат»; словарь
причин дополнен `publisher_not_bound` и `deferred_publication_expired`.
Текстовая квота приписку не получает.

**Почему списание не возвращается (выбор для `P0IM-S5B-QUOTA`).** Слот
списывается ровно тогда, когда провайдер реально вызван
(`reserved` → `provider_called`), и освобождается только если вызов
достоверно не начинался (`released`). Здесь вызов состоялся и деньги
потрачены: возврат слота разрешил бы второй платный вызов сверх суточного
капа, то есть разошёлся бы с фактическим списанием. Поэтому выбран второй
вариант контракта — слот остаётся израсходованным и показывается как
«израсходован без отправки» с причиной. Поздняя доставка отложенной строки
дописывает в журнал `published` с тем же `job_id`, и счётчик сам
пересчитывается в «отправлено».

## 3. Наблюдаемые значения (реальные объекты, один сценарий)

Сценарий: один авто-проход, image-провайдер вернул `b"paid-png-bytes"`,
`sender is None`.

| факт | до (`1dcbebca`) | после (`e92cdcd5`) |
|---|---|---|
| `result.reason / detail` | `publish_blocked / publisher_not_bound` | то же (причина честная, не «успех») |
| файл байтов | нет (удалён) | `var/meme_pending/<job>.bin`, SHA-256 = оплаченные байты |
| строка `task_jobs` | нет | 1, `status=queued`, `coalesce_key=meme:pending_publish:-100`, `deadline_at = now + cooldown` |
| `publication.artifact` в журнале | нет | `{reason: publisher_not_bound, preserved: true, bytes: 14, deferred_job_id: …}` |
| `publication.delivery` | нет | `not_sent` |
| `last_delivery.status` | `never` (пусто) | `not_delivered`, `reason_code=publisher_not_bound`, `at` = время попытки, `message_id=null` |
| `quota.spent / delivered / not_delivered` | `1 / — / —` | `1 / 0 / 1`, `not_delivered_reasons = {publisher_not_bound: 1}` |
| тот же слот после доставки отложенной строки | — | `spent=1, delivered=1, not_delivered=0` (списание не «вернулось») |
| событийный тик без бота, затем тик с ботом | отправки нет никогда | ровно 1 отправка, байты те же, файл потреблён, `task_jobs.status=completed` |
| истёк срок без отправителя | тишина | терминал `deferred_publication_expired`, `delivery=not_sent`, файл удалён |
| durable-путь недоступен (`_task_store=None`) | тишина | `artifact.preserved=false` + причина в журнале |

## 4. Тесты (могут падать по делу)

`tests/test_publication_binding_delivery.py` — 8 тестов, 8 passed:

1. `test_auto_meme_keeps_paid_image_when_publisher_not_bound` — файл+строка
   очереди существуют, SHA совпадает с оплаченными байтами, `preserved=true`.
2. `test_without_durable_path_the_attempt_is_closed_with_explicit_reason` —
   нет очереди → `preserved=false`, доставка `not_sent`.
3. `test_delivery_axis_reads_not_delivered_with_exact_reason` —
   `never` до попытки, `not_delivered` + `publisher_not_bound` после,
   `message_id=null`, набор полей = `LAST_DELIVERY_FIELDS`.
4. `test_confirmed_delivery_wins_over_a_later_blocked_attempt` —
   подтверждённая отправка не переписывается следующим отказом.
5. `test_quota_slot_stays_spent_and_is_shown_as_not_delivered` —
   `spent=1 / delivered=0 / not_delivered=1` + причина, набор полей =
   `QUOTA_FIELDS`.
6. `test_quota_slot_becomes_delivered_after_the_deferred_send` — поздняя
   доставка: `spent` тот же, `delivered=1`, `not_delivered=0`.
7. `test_deferred_row_waits_for_publisher_and_is_delivered_after_restart` —
   restartsafe: тик без бота → строка `queued`, байты целы, новых строк
   журнала нет; после «рестарта процесса» (новые объекты на том же файле) —
   ровно 1 отправка.
8. `test_expired_deferred_row_closes_as_not_sent_instead_of_vanishing` —
   `deferred_publication_expired`, `delivery=not_sent`, файл удалён.

**Мутации (каждая роняет свои тесты, проверено):**

| мутация | результат |
|---|---|
| M1: убрать `defer_generated_meme` из ветки `publisher_not_bound` | 4 failed (`№1, 6, 7, 8`) — воспроизведён дефект D6 |
| M2: вернуть терминал вместо ожидания при `sender is None` | 1 failed (`№7`) — рестарт-доставки нет |
| M3: не применять факт закрытия к оси доставки и не считать слоты | 3 failed (`№3, 5, 6`) |

JS-стенд `tests/js/initiative_ui_rework_test.js` (`node ...` →
`INITIATIVE-UI-OK`) дополнен блоками 3.4b и 3.7b: подпись «не доставлено»,
причина по-русски, `message_id` не подмешивается, незнакомый код деградирует
в «код: …», приписка квоты появляется только у мемов и только при
`not_delivered > 0` (при `0` и `null` её нет).

## 5. Живая отрисовка

- Playwright, реальные `web/index.html`/`app.js`/`app.css`, два вида
  (1536×960 и 390×844), состояния «не доставлено» и контроль «доставлено»:
  10 проверок, 0 падений, горизонтальной прокрутки нет.
  Артефакты: `playwright-visual.json`, `not-delivered-1536x960.png`,
  `not-delivered-390x844-card.png`, `control-delivered-1536x960.png`.
- Независимая проверка живым браузером (Browser Use, отдельный Chrome,
  настоящий бандл + стабы API): карточка мемов отрисовала
  «Последняя отправка → не доставлено · 15.01 08:00 UTC · причина:
  отправитель не привязан в этом процессе» и «Дневная квота → … ·
  израсходовано без отправки: 1 (отправитель не привязан в этом процессе)»;
  текстовая карточка не изменилась, обрезки и переполнения нет.

## 6. Регрессии

- Серии мемов/инициативы/публикаций (11 файлов): **265 passed**.
- `tests/js/initiative_ui_rework_test.js`: `INITIATIVE-UI-OK`.
- `tests/test_initiative_coordination.py` — те же 4 падения, что и на базовом
  `1dcbebca` (4 failed / 56 passed в обоих деревьях; текстовый путь
  инициативы, кандидатом не затронут).
- Изменения не касаются значений квоты, правил списания, обхода `/meme`,
  egress-гарда, image-only правила, промптов, моделей и настроек.

## 7. Что этот кандидат НЕ доказывает

- Реальный автоматический мем в рабочем чате с отказом связывания не
  прогонялся: `live_required` строки NODISCARD отмечен `preprod`, отправка в
  чаты в этом прогоне запрещена. Доказательство — на объектах с фейковым
  Telegram-швом.
- Привязка бота в событийном тике (`dispatch_event` → `_service_attr("bot")`)
  не менялась: изображение сохраняется и доставляется штатным проходом, но
  сам событийный тик по-прежнему не может отправить мем сразу. Это отдельный
  дефект, вынесенный в бэклог, а не «тихая» правка в этом срезе.
- Ось `last_attempt` (S4) для отказов публикации показывает терминальную
  служебную строку этапа «пропуск» (`остановилось: пропуск`) — поведение
  `1dcbebca` не менялось; вынесено в бэклог.
