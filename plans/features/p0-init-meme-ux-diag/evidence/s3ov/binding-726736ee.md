# S3-OV — привязка одобренного кандидата `726736ee` (`candidate approved`, НЕ задеплоен)

Дата: 2026-11-12. Автор записи: PM (привязка статуса/доказательств). Это **не** новый ревью-проход и не вердикт Reviewer:
здесь фиксируются наблюдения двух независимых проходов Reviewer по кандидату `726736ee`, переданные оркестратором,
и то, к каким строкам карты они относятся.

## Кандидат

| Что | Значение |
| --- | --- |
| Кандидат среза | `726736ee38955dfe605dfcbfb3ec1e1213cdcede` (`init/meme-axes`) |
| Коммиты среза | `d58fbb56` (обзор на пяти осях), `d55abf0d` (пять блокеров ревью), `726736ee` (`P0IM-OV-HEADER`, переключатель чатов) |
| База кода | `c087253d` (release 2.58.188) |
| Предыдущий принятый кандидат линии | `4c59a483` (S1-AXES/S2-ID) |
| Деплой | **нет**. Продакшен остаётся на `c087253d` |
| Статус | одобрено Reviewer на `726736ee`, ожидает выкладки → строки в состоянии `REVIEW`, ни одна не `VERIFIED` |

## Дословные наблюдения Reviewer (переданы оркестратором)

Пронумерованы для ссылок из карты (O1…O11). Формулировки приведены как получены, без переписывания:

- **O1.** `ready=false` never renders as disabled; each waiting case (cooldown, quota, quiet hours, not enough messages,
  lottery miss, waiting for the tick, waiting on publication coordination) shows enabled plus a waiting explanation.
- **O2.** Configuration comes only from the configuration axis; `enabled=null` renders as unknown, never off.
- **O3.** Next-eligible time appears only with a backend stamp and a named basis; empty basis produces no «не раньше».
- **O4.** Delivery states stay distinct: confirmed with a message id, delivery unknown, not delivered (and «бот решил не
  публиковать» vs «попытка отложена»); `message_id=0` is treated as absent.
- **O5.** Chat switch clears the snapshot immediately; a late response for another chat is discarded (mutation proves the
  guard is tested).
- **O6.** An expired `manual_priority_until` shows no bar and no «приоритет ручного» wording; a live deadline with the
  backend flag shows it.
- **O7.** «Показать попытку» opens the existing diagnostics focused on that attempt (`meme:job-77`, mechanism, outcome)
  and is absent when there is no parent.
- **O8.** Header switcher: «Этот чат / Другой чат / Сравнить чаты»; the other-chat state shows that chat's own payload with
  no leakage; compare shows two labelled columns per mechanism and axis with no third computed set, no averaging and no
  winner; with one chat available the switcher is absent.
- **O9.** Measured by the reviewer himself in the existing Playwright stand: 390x844 and 1536x960, `hScroll=0`,
  `scrollWidth` equal to the viewport, zero truncation, zero off-screen.
- **O10.** Suites: JS `INITIATIVE-UI-OK` plus the other JS checks; web/api 1534 passed / 15 failed identical to base;
  initiative/meme 303 passed / 4 failed (same four pre-existing `test_initiative_coordination.py`); e2e 2 pre-existing
  failures (prompt-version card on the Memes tab).
- **O11.** Backend axes unchanged relative to `4c59a483`; no new endpoint, store, LLM call, prompt, model or saved setting.

Отдельно от переданной выжимки PM сам прочитал файлы кандидата; такие ссылки в карте помечены как «проверено PM по
файлу кандидата» и не выдаются за наблюдение Reviewer.

## Два зафиксированных ограничения

1. **Живого браузерного прохода в последнем раунде не было.** Геометрия и отсутствие переполнения подтверждены
   замерами Playwright в существующем стенде (O9: 390x844 и 1536x960, `hScroll=0`, `scrollWidth == viewport`,
   0 обрезаний, 0 элементов за экраном). Проход в реальном браузере (Browser Use) на этом кандидате **не выполнялся** и
   в качестве доказательства не заявляется нигде.
2. **Режим «Сравнить чаты» читает второй чат существующим эндпоинтом со своим `X-Chat-Id`** (O8 + O11). Новых
   эндпоинтов, агрегирующего «третьего набора» и серверного усреднения нет; клиент сопоставляет два уже полученных
   payload'а колонками.

## Что именно этим кандидатом подтверждено (срез S3-OV)

- Пять осей на карточке читаются из ответа сервера; «Разрешено» — только `configuration.enabled`, `null` → «неизвестно»;
  ожидания (кулдаун, квота, тихие часы, нехватка сообщений, жребий, тик, координация) остаются «включено + причина»
  (O1, O2).
- Время следующей возможности печатается только при серверном штампе и названном основании; без основания строка
  «не раньше» не появляется (O3).
- Доставка: подтверждено с id / неизвестно / не доставлено, с разделением «бот решил не публиковать» и «попытка
  отложена»; `message_id=0` = отсутствует (O4).
- Снимок своего чата очищается при смене чата, поздний ответ чужого чата отбрасывается, guard проверен мутацией (O5).
- Истёкший `manual_priority_until` не показывается как текущее ожидание (O6).
- «Показать попытку» ведёт в существующую диагностику этой попытки и отсутствует без родителя (O7).
- Шапка: выбранный чат, дата/TZ, «Обновить» и переключатель «Этот чат / Другой чат / Сравнить чаты»; «другой чат» без
  утечек, «сравнить» — две подписанные колонки без третьего набора и без победителя; при одном чате переключателя нет (O8).
- Мобильная ширина без горизонтальной прокрутки и без обрезки (O9).

## Что этим кандидатом НЕ доказано

- **Выкладка**: продакшен на `c087253d`, кандидат только одобрен. Ни одна строка не `VERIFIED`.
- **Живой браузер**: см. ограничение 1.
- **Дословная форма образца из ТЗ** (`«Мемы · Разрешено: ВКЛ | Сейчас: пауза 33 мин»`, `Telegram #1234`): в переданной
  выжимке отдельного наблюдения по дословной формулировке нет. Доказательство строк `P0IM-OV-SAMPLE` ограничено
  снимками кандидата (`evidence/S3-OV/overview-filled-390x844-top.png`), наблюдениями O1/O7 и тем, что срез одобрен
  целиком; дословная сверка текста образца выполняется при выкладочной проверке.

## Тестовые серии на кандидате (O10)

- JS: `INITIATIVE-UI-OK` и остальные JS-проверки — проходят.
- web/api: 1534 passed / 15 failed — идентично базе.
- initiative/meme: 303 passed / 4 failed — те же четыре допредсуществующих в `test_initiative_coordination.py`.
- e2e: 2 допредсуществующих падения (карточка prompt-version на вкладке «Мемы»).
- Backend-оси не изменены относительно `4c59a483` (O11): ни нового эндпоинта, стора, LLM-вызова, промпта, модели или
  сохранённой настройки.

## Область правки и её фактическое совпадение с графом

Коммиты среза меняют `web/app.js`, `web/index.html`, `web/static/app.css`, `tests/js/initiative_ui_rework_test.js` —
это объявленный `write_scope` S3-OV. UI-e2e утверждения среза лежат в `tests/ui_initiative_rework_e2e.py`, который граф
относит к S4-TRACE (S3 — его предок, поэтому конфликта одновременных писателей нет). Переприсвоение файла не делается:
это наблюдение для владельца S4, а не изменение плана.

## Половины строк S1-AXES, которые закрываются этим срезом

| Строка | Backend-половина | UI-половина на `726736ee` | Итог |
| --- | --- | --- | --- |
| `P0IM-BAN-ENABLED` | доказана на `4c59a483` | O1 + O2 | обе половины существуют → `REVIEW` (не `VERIFIED`, не задеплоено) |
| `P0IM-AX-SERVER` | доказана на `4c59a483` | клиент читает только оси, tri-state, ничего не выводит из отсутствия полей (O2) | обе половины существуют → `REVIEW` |
| `P0IM-BAN-NOETA` | ось `readiness.next_eligible_at` — только по закрытому списку базисов | обзор не выдумывает время (O3) | **не закрыта**: в `services/meme_initiative.py` `next_check = max(now, last_provider_ts + cooldown)` по-прежнему возвращается как `next_check_ts` и рисуется на вкладке «Диагностика мемов» строкой «Следующая проверка» (подпись «из записанного состояния прохода»). Остаётся `PENDING` |

Ни одна из этих строк не считается дважды: они остаются за S1-AXES, S3-OV лишь поставляет UI-половину.

## Следующая волна релиза (без создания задачи)

В следующую выкладку входят два одобренных, но не задеплоенных кандидата:

1. `10ab50b5` — область инструмента ремонта (`repair tool scope`), одобрено, не задеплоено.
2. `726736ee` — этот срез (S3-OV).

Отдельная релизная задача не создаётся: это заметка для DevOps/оркестратора.
