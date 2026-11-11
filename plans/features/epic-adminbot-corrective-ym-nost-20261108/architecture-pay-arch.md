# PAY-ARCH — контракт контура ЮMoney

Эпик `EPIC-ADMINBOT-CORRECTIVE-YM-NOST-20261108`. Срез `PAY-ARCH`. Вердикт: `ARCHITECT_ADJUSTMENT_REQUIRED`. Продуктовая модель §§9–18 сохранена. Поправки ниже — несовместимость с продом `77a63bc5` и официальным API, не новый продукт. Код, карта, прод и провайдер не трогались. Исключено: Platega, Stars, крипто, СБП как обещание, 15-минутный TTL, автовыплаты, второй генератор картинок.

Код: только `git show 77a63bc5`. Документы ЮMoney, прочитаны 2026-11-11: [формы](https://yoomoney.ru/docs/payment-buttons/using-api/forms), [уведомления](https://yoomoney.ru/docs/payment-buttons/using-api/notifications), [operation-history](https://yoomoney.ru/docs/wallet/user-account/operation-history).

## 1. Сущности и состояния

Offer — текст и кнопки Telegram. Денег не резервирует, заказа не создаёт, в БД как платёж не пишется.

Order, таблица `image_pay_orders` (PG): `order_id` (случайный PK), `label` UNIQUE (случайный, ≤64, без Telegram ID), `chat_id`, `telegram_user_id`, snapshot `amount_kopeks` и `pack_size`, `currency=643`, `payment_method=yoomoney_wallet_collect`, `status`, hash непрозрачного form-token, `created_at`, `last_activity_at`, id временных сообщений. Колонки `expires_at` нет. Повтор клика одного намерения (`offer_id`) переиспользует один `waiting`-заказ. Новый intent — новый `label` и новый snapshot. Цена клика без заказа берётся из текущего effective и показывается в сообщении заказа до перехода; уже созданный snapshot админка не меняет.

Payment form — наша страница `POST /pay/yoomoney/{opaque_token}`. Это не инвойс и не токен ЮMoney. Сервер сам подставляет `receiver`, `quickpay-form=button`, `paymentType=PC|AC`, `sum` (рубли из snapshot, `Decimal`), `label` и делает POST на `https://yoomoney.ru/quickpay/confirm` только после явного нажатия. Цена и label из query пользователя в форму не попадают. Отзыв token прячет форму и не удаляет заказ.

Payment receipt — строка `image_payment_receipts`: `provider=yoomoney`, UNIQUE `(provider, operation_id)`, оба суммы в копейках, `label`, `order_id`, источник (`webhook`/`history`/`both`), `credit_event_id`.

Состояния заказа: `waiting` → `ui_closed` (отмена или уборка меню; финансово не отмена) | `credited` | `needs_reconciliation`. `credited` терминален для начисления; компенсация — отдельная проводка, не откат статуса. `ui_closed` и `needs_reconciliation` не терминальны для позднего совпадения. `rejected` — только явная финансовая отбраковка, никогда по таймеру. Переживают рестарт: заказ, label, receipt, ledger, inbox, outbox. В памяти ничего финансового нет. Уборка UI (`billing.image_order_ui_cleanup_minutes`, `0` = не удалять) не меняет статус денег.

## 2. Проверка поступления

Каноническая строка подписи — все поля POST кроме `sign`, сортировка A–Z, значения URL-encoded UTF-8/RFC 3986, склейка `key=value` через `&`. HMAC-SHA256, hex в нижнем регистре, сравнение constant-time. Секрет — секрет HTTP-уведомлений этого кошелька. `sha1_hash` не проверяет подлинность; если поле ещё пришло, оно остаётся в строке. Вектор документации: секрет `secret123`, sign `a452af731650e2c5b39abcdc7c28dd27db7b3b654c2230ad2c386e64afb98605`.

В теле уведомления поля `receiver` нет. «Наш кошелёк» = секрет этого кошелька + единственный URL уведомлений + `receiver` в нашей форме. Сопоставление: `label` нашего заказа, `currency=643`, `notification_type` ∈ {`p2p-incoming`,`card-incoming`}, `withdraw_amount` (Decimal → копейки) равен snapshot. `amount` хранится отдельно и не является причиной отказа. `unaccepted`/`codepro` не `false` → не начислять. `sender`, имя, комментарий, `@username` в сопоставлении не участвуют и в логи не пишутся.

Сверка истории: OAuth только `operation-history` (+ `operation-details` для чтения). Фильтр `label` в документации привязан к `request-payment`, для входящих quickpay не доказан: им не кредитовать. Поиск — `type=deposition`, окно времени, пагинация. Автокредит из истории только если details дают тот же `operation_id`, `direction=in`, `status=success`, наш `label` и сумму списания, равную snapshot. Иначе `PAY_HISTORY_INCOMPLETE`, без угадывания. Webhook и сверка зовут один `confirm_receipt`. Никогда не доверять: `successURL`, callback клиента, Telegram callback, query, `sha1_hash`, тексту LLM.

Недоплата, переплата, чужая валюта, два разных `operation_id` на один label → `needs_reconciliation`, автокредита нет. Повтор того же `operation_id` → +0. Оплата после `ui_closed` кредитуется, если подпись и сумма совпали.

## 3. Атомарное начисление

Одна транзакция PG, до любой речи: durable inbox (hash канонической строки + `operation_id`) → вставка receipt `ON CONFLICT DO NOTHING` → перевод заказа в `credited` только из `waiting|ui_closed` → append-only credit `+pack_size` → outbox с тем же `credit_event_id`. HTTP 200 только после commit inbox. Внешних вызовов в этой транзакции нет. Ключ идемпотентности: `(provider, operation_id)`; `credit_event_id` детерминирован от него и UNIQUE на receipt, ledger и outbox.

LLM и Telegram — после commit. До вызова durable-маркер `llm_attempted`. Смерть между receipt и сообщением: recovery читает outbox, кредит не повторяет. Если вызов оборван — только fallback, второй LLM нет. Неясная отправка → `DELIVERY_UNCERTAIN`, без второго начисления и без слепого повтора. Сбой удаления меню кредит не откатывает.

## 4. Баланс

Три контура не смешиваются: free `(chat_id, user_id, local_date)`, paid `(chat_id, user_id)`, технический shared cap. День free — календарная дата в IANA `ChatClock.resolve_chat_timezone` / `limits.chat_timezone`, не `WORKER_BUDGET_TZ` и не «24 часа». Сначала free, затем paid. `limits.image_free_per_user_per_chat_daily=0` — безлимит только этой настройки: paid не тратится и offer не показывается. Старый `limits.image_daily_limit` (`0`=запрет) из пользовательского пути убрать, строки и shared cap не удалять.

`available = credits + compensations + signed_adjustments − committed_debits − active_reservations`. Резерв — строка, не `UPDATE balance`. Release снимает активный резерв и не даёт второй `+1`. Покупки не сгорают в полночь и суммируются. Системные картинки (`consumption_type != user_image`: обложки, мемы) персональный контур не трогают. Сбой PG на персональном пути — отказ, не fail-open. Один `image_request_id` — один резерв/дебет.

## 5. Секреты и админка

Секрет `sign`, номер кошелька и read-only OAuth — только env/settings, класс `MEDIA_SHARE_SECRET`. Не каталог, не hot_config, не chat override, не промпт, не URL, не лог, не API. Номер кошелька допустим лишь в серверном POST формы; в логах и API — маска или отсутствие. Индикаторы подключения — read-only, вручную «подключено» не ставится.

Реестр админа строится из ledger/receipts: по человеку и чату число покупок, списано и поступило раздельно (копейки, валюта, статус), начислено, потрачено, возвращено, в резерве, доступный paid; free сегодня отдельно. Модератор — агрегаты без плательщика и без сумм чужих переводов. В лог/API не попадают: секрет, OAuth, сырое тело, `sender`, карта, `successURL`.

## 6. Миграция и выключенный провайдер

Аддитивный `CREATE TABLE IF NOT EXISTS` в `services/pg_db.py::DDL_STATEMENTS`, как `image_reservation`. SQLite `user_version` не повышать. Секреты в `bot_settings` не сеять. Новые несекретные ключи — в существующие группы вкладки `mod_images`, factory: free=1, pack=3, price=5000, `billing.image_yoomoney_enabled=false`. Это явное решение владельца: общее правило «готовое включено» этот флаг не перебивает.

Откат: флаг false и прежний пользовательский путь квоты. Таблицы с receipt не DROP. Пустые таблицы после неудачного деплоя без поступлений можно оставить. Отдельной миграционной системы нет.

OFF или неполный конфиг (нет кошелька, секрета, цены >0, pack >0, непроверенный провайдер): нет offer, кнопок, платёжных шаблонов, ссылки и списания; честное сообщение об исчерпании без продажи. Уже созданный заказ и пришедший receipt обрабатываются и после выключения новых продаж.

## 7. Коды отказов

`PAY_GATEWAY_UNAVAILABLE` / `PAY_CONFIG_INCOMPLETE` — нет ссылки и нет дебета. `PAY_NOTIFY_BAD_SIGN` — inbox, кредита нет. `PAY_NOTIFY_REPLAY` — второй кредит и второй LLM нет. `PAY_AMOUNT_MISMATCH` — сверка, автокредита нет. `PAY_LATE_AFTER_UI_CLOSE` — не ошибка: тот же `confirm_receipt`. `PAY_GEN_RELEASED` — резерв снят, финального дебета нет. `PAY_HISTORY_INCOMPLETE` — история без доказанных полей, кредита нет. `PAY_DELIVERY_UNCERTAIN` — кредит уже стоит.

## 8. Приёмка PAY-ARCH и границы

Срез закрывается этим файлом: одна модель order/receipt/ledger/inbox/outbox, идемпотентные ключи, откат, флаг OFF, запрет Platega/Stars/crypto/TTL. Реализация PAY-BALANCE и далее не требуется. Карту не менять этим срезом.

Не менять L1/Writer, Vision, календарь, сон, ностальгию, инициативу, FactCheck и остальную очередь. Узкое будущее исключение, не этот срез: два event-промпта через существующий реестр и `authorial_system`. Финансовые факты LLM не определяет.

Параллельность: этот срез только читает. Дальше `worker_budget.py` и `image_generation.py` сериализованы за `VISION-OWN` и `MEM-AUDIT`; `param_catalog.py` — за `PAY-ADMIN`. Новые `payment_*` не пишут чужие контуры. Риск R3.

## 9. Что переиспользовать

`image_generation.py` — расширить только пользовательский вход: персональный gate перед текущим генератором. Второй генератор не создавать. Путь обложек не менять.

`services/image_reservation.py` — на `77a63bc5` нет. Модуль не создавать. Таблицу `image_reservation` не делать платёжным ledger: purge 30 дней, день чата, мутабельный status, fail-open, `0`=запрет. Оставить техническим журналом.

`worker_budget.py` — переиспользовать `image_day` и shared cap. Персональный paid/free — отдельный fail-closed адаптер. `reserve_image` как баланс покупки не использовать и его fail-open для обложек не менять.

`param_catalog.py` — аддитивно во вкладку `mod_images` / группы `limits_images` и `flags_module_images`. Секреты в каталог не класть. `IMAGE_DAILY_LIMIT` оставить, из пользовательского пути убрать.

Реестр промптов — позже `declare_prompt` + `FACTORY_REVISION_SEALS`, заводской текст побайтно. Второй реестр не создавать. `services/speech.py` на проде нет: не создавать; звать `mca_authorial_speech.authorial_system`. Админка — существующие `/api/config` и раздел «Генерация изображений»; реестр покупок — read-проекция, не второе хранилище настроек.

DESIGN READY. При старте реализации перепроверить: вектор HMAC и состав полей кроме `sign`; что quickpay-входящий реально виден в operation-history с `label` и суммой списания (пока не доказано — из истории не кредитовать); что `ChatClock.resolve_chat_timezone` и `limits.chat_timezone` всё ещё один ключ; что группы `mod_images` не переименованы; что `image_reservation.py` не появился; что factory остаётся 5000 копеек и провайдер OFF.
