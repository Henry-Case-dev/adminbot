# Аудит: фактическое распределение инициативы (chat / Telegram-reply), 48 ч

LANE_ID: INIT-DELIVERY-AUDIT · режим: read-only · прод `198.46.175.136`

## Окно и метод

| Параметр | Значение |
|---|---|
| Часы сервера | UTC (`2026-10-23T21:05:38Z` в момент снятия) |
| Окно | `2026-10-21T21:05:38Z` → `2026-10-23T21:05:38Z` (ровно 48 ч) |
| БД | `/var/www/admin_bot/local_database.db`, `mode=ro` + `PRAGMA query_only=ON` |
| Журнал | `journalctl -u admin_bot`, покрытие окна с `2026-10-21T21:11:35Z` |
| Изменения | нет: ни кода, ни конфигов, ни рестартов, ни сообщений в чаты |

## Главный вывод

**Распределение «chat vs Telegram-reply» за окно измерить нельзя — оно нигде не записывается. `NOT_INSTRUMENTED`.**
Текстов инициативы доставлено 16 (8 + 8 по чатам), реакция — 1, отмен по target binding — 0.
Ни одно событие, ни ledger не содержат выбранную L1 форму доставки (`delivery`) или фактический `reply_to`.
Поэтому утверждение «инициатива уходит в общий чат, а не reply» **ни подтверждено, ни опровергнуто** данными.
Кодовый факт: форму выбирает L1 (директива L1D 22.10.2026), транспорт её только исполняет — значит перекос, если он есть, не может происходить из Observer или транспорта.

## Сводка по чатам (UTC-окно)

| Чат | Решений `initiative_decided` | Текстов доставлено | Реакций | Silent | Отмен (`cancelled`) | Доля chat/reply |
|---|---|---|---|---|---|---|
| `-1002661910336` (A) | 18 | 8 | 1 | 9 | 0 | `NOT_INSTRUMENTED` |
| `-1004482340693` (B) | 9 | 8 | 0 | 1 | 0 | `NOT_INSTRUMENTED` |
| **Итого** | **27** | **16** | **1** | **10** | **0** | `NOT_INSTRUMENTED` |

Баланс сходится: 27 = 16 текстов + 1 реакция + 10 молчаний.
Разбивка молчаний: `l1_silent` 5, неудавшаяся реакция (`l1_react`) 4, явный `silent` L1 1.

Активность чатов за то же окно (для контекста): A — 4365 сообщений (1645 с reply), B — 1173 (214 с reply).

## Поводы Observer

| Метрика | Значение |
|---|---|
| `initiative_observer_scan` | 458 (все `stage=observed`) |
| `initiative_opportunity` всего | 38 |
| из них с действием (`say`/`react`) | 24 (23 `say`, 1 `react`) |
| `opportunity:none` (скан без повода) | 14 |
| Реализовано из 24 | 14 (13 текстов + 1 реакция) |
| Текстов из nostalgia-пути | 3 (не из Observer) |
| `initiative_observer_diagnostic` | 1 (`diagnose:no_opportunities_24h`) |

Кумулятивные счётчики задания Observer (за всё время жизни job, **не** за окно): `opportunities 64`, `sent 35`, `react_decisions 5`, `silent_decisions 26`.

## Все 16 доставленных инициативных текстов

| UTC | Чат | tg_msg | correlation_id | reply target в ledger |
|---|---|---|---|---|
| 10-22 06:26 | A | 1169991 | `bc951871491642d6` | `NULL` |
| 10-22 08:19 | B | 3569 | `8ee9b796490847e3` | `NULL` |
| 10-22 10:19 | A | 1170214 | `NULL` (nostalgia) | `NULL` |
| 10-22 10:44 | B | 3815 | `77ecf14f06ca45e3` | `NULL` |
| 10-22 12:59 | A | 1170589 | `94c36bd0381d4bca` | `NULL` |
| 10-22 13:50 | B | 4325 | `e44124b89f0b4c6d` | `NULL` |
| 10-22 17:50 | B | 4433 | `e197878d3e7a4fb1` | `NULL` |
| 10-22 20:55 | B | 4445 | `ce0522f0cd604692` | `NULL` |
| 10-22 23:00 | A | 1172138 | `NULL` (nostalgia) | `NULL` |
| 10-23 01:20 | A | 1172238 | `ce0f8c0533be4fee` | `NULL` |
| 10-23 03:20 | B | 4468 | `f4420ac67e3c4f9e` | `NULL` |
| 10-23 06:24 | A | 1172502 | `ca59d036cfa6483c` | `NULL` |
| 10-23 08:40 | B | 4510 | `4334cfd969f94003` | `NULL` |
| 10-23 11:10 | A | 1172843 | `4a20c35ec5b74dec` | `NULL` |
| 10-23 11:45 | A | 1172887 | `NULL` (nostalgia) | `NULL` |
| 10-23 20:42 | B | 4647 | `a8fd944ddf0140fe` | `NULL` |

Для сравнения: Direct-ответы в тех же чатах — `parent_message_ref` заполнен у **604 из 604** (`533` в A, `71` в B). Колонка есть, инициативный путь её не передаёт.

Важно: `output_kind=initiative_reply` и лог `kind=initiative_reply` — это **вид инициативного текста** (text vs silent/tool/react), а не признак Telegram-reply. Как признак reply использовать нельзя.

## Разбор пунктов задания

1. **Повод → адресат → L1 → доставка.** Свести по `correlation_id` нельзя: в `initiative_decided` нет ни correlation, ни intent_id (`entity_ids` и `trace_id` = `NULL` у всех 27), в ledger correlation есть у 13 из 16. Сведение возможно только по времени (минута) и чату.
2. **Все `initiative_delivery_manifest`** — 16, ровно по числу доставок, 1:1 с ledger (8/8). Токены: `corr`, `msg`, `core`, `style`, `identity`, `manifest`, `composer`. `config_version` пуст у всех 16 (код передаёт сводку — в событие она не попала).
3. **`initiative_sent`**: 13 событий, все `stage=observer:<kind>` (уровень Observer). Фуннельного `initiative_sent` (`stage=delivery`) — **0**. `initiative_recheck_passed` — **0**. Причина: оба эмитятся только при непустом `intent_id`, а durable-намерений в окне не было (`intents_created: 0`).
4. **Observer**: 24 повода с действием → 14 реализовано, 10 молчаний. Отмен по правилам (SendRecheck `cancelled`) — 0.
5. **Отдельные случаи:**
   - (а) «общая тема получила reply на конкретное сообщение» — определить нельзя (нет записи target).
   - (б) «L1 выбрала chat, но не отправлено» — таких случаев нет по данным: все 16 выбранных текстов доставлены; 10 молчаний — это `silent`/неудавшаяся реакция, а не «chat без отправки».
   - (в) **отмены/ошибки target binding**: отмен 0; но **4 из 5 решений `react` не исполнились** (`reason=target_invalid` в журнале, событие пишет только `reason_code=l1_react` и `outcome=silent`). Это единственный наблюдаемый сбой привязки цели.
   - (г) **повторная переоценка**: 3 ситуации с двумя `initiative_writer_generated` перед одной отправкой (10-22 13:50, 10-22 17:50, 10-23 03:20; все — чат B). Итоговое решение одно на ситуацию, дублей отправки нет.
6. **Доля chat/reply среди доставленных текстов**: `NOT_INSTRUMENTED` (нет числителя и знаменателя).
7. **Связь `addressee_user_id` с reply**: `addressee_user_id` из verdict Observer попадает в `opportunity_row` как контекст L1, но нигде не сохраняется и с фактической доставкой не сопоставим.

## Пробелы телеметрии (что именно отсутствует и где добавить)

| № | Что отсутствует | Где | Следствие в этом окне |
|---|---|---|---|
| G1 | `delivery` (chat/reply), `target_message_id`, `target_user_id`, `correlation_id` в решении | `services/mca_intents.py:760-768` (`note_decision`) | нельзя ответить на главный вопрос аудита; 27 решений не связаны с доставками |
| G2 | `status` = `decision.action`, а он остаётся `reply` даже когда L1 выбрала `react` | там же; `services/direct_chat_service.py:9446` | 5 решений-реакций выглядят как `reply`; реакция опознаётся только по `reason_code=l1_react` |
| G3 | `reply_to`/`delivery` в манифесте доставки; `config_version` не сохраняется | `services/mca_intents.py:713-747` | 16 манифестов не говорят, был ли reply; сводка Core/Style потеряна |
| G4 | `parent_message_ref` не передаётся в ledger | `services/direct_chat_service.py:9878-9884` (ср. Direct: `3969`) | 0/16 против 604/604 у Direct — фактическая цель reply недоказуема постфактум |
| G5 | Причина отмены привязки не проходит whitelist `reason_code` (`target_*`) | `services/mca_events.py:344-352` | при будущих отменах причина сохранится как `NULL` |
| G6 | Колонки `entity_id` нет в insert-списке `mca_events` | `services/mca_events.py:652-661`; эмиссия `services/initiative_observer.py:1655,1663` | correlation Observer-событий теряется |
| G7 | Фуннельные `initiative_sent`/`initiative_recheck_passed` только при `intent_id` | `services/direct_chat_service.py:9786-9788, 9888-9892` | 3 отправки nostalgia (19%) вне воронки |
| G8 | Нет события «форма доставки выбрана L1» (успешная привязка не логируется, только неудача) | `services/direct_chat_service.py:9800-9826` | chat/reply не наблюдаемы даже в журнале |

Минимально достаточное исправление (без реализации здесь): в `note_decision` писать `delivery`, `target_message_id`, `target_user_id` и correlation; в ledger передавать `parent_message_ref="tg:<reply_target>"`; добавить `target_*`-коды в whitelist; отличать реакцию собственным `delivery=react`.

## Ограничения полноты

- Сохранённый файл журнала обрезан (`tail -n 1200` ≈ последние ~12 ч). Полновиндовые счётчики получены отдельным grep по всему окну: `binding unavailable` 0, `initiative cancelled` 0, `initiative sent` 16 (8+8).
- Сообщения самого бота не попадают в `smart_messages` (0 строк для bot_id `8802473181` за окно; ни один из 16 tg-id не найден) — независимого `reply_to` нет.
- Telegram API не опрашивался: у Bot API нет метода чтения `reply_to_message` отправленного сообщения.
- 3 отправки без correlation → сопоставление только по времени.
- Счётчики задания Observer кумулятивные (за жизнь job), не за окно; в отчёте помечены отдельно.
- Проверка «reply/chat» возможна только после добавления полей G1/G4 и нового окна наблюдения.

## Воспроизводимость

- `db_window_snapshot.json` — все выборки окна (`mca_events` по `initiative*`, `mca_bot_outputs`, `smart_messages`, `task_jobs` counters).
- `db_ledger_vs_smart.json` — сверка 16 tg-id с `smart_messages`, bot_id, наличие `entity_id` в `mca_events`.
- `journal_fullwindow_counts.txt` — полновиндовые grep-счётчики.
- `journal_mca09_lines.txt` — уникальные строки `[mca09]` (R17-safe).

SSH: 2 успешных логина (09:05:38Z и ~09:16Z), интервал > 60 с, один пользователь, без ретраев; один локально прерванный коннект в 09:04:36Z (таймаут 0.6 с, аутентификация не завершалась). Записи в БД/код/конфиги отсутствуют; временные файлы `/tmp` удалены штатной командой очистки.
