# S7-ACCEPT — матрица приёмки `p0-init-meme-ux-diag`

- кандидат: `6d3b566e633c40088463be6d5f4ef8912f260cab` (ветка `init/meme-s7-accept`)
- режим: code+live+visual
- снимок прода: `plans\features\p0-init-meme-ux-diag\evidence\s7accept\prod-snapshot-2.58.194.json` (снят 2026-11-12T00:45:23Z)
- статус прогона: **partial**

## Счётчики

| статус | сколько |
|---|---|
| пройдено | 28 |
| НЕ ПРОЙДЕНО | 0 |
| не наступило | 1 |
| заблокировано | 0 |

## Матрица

| проверка | вид | строка карты | статус | наблюдение |
|---|---|---|---|---|
| `AC-MATRIX-CONFIG-FACTORY` — configuration: заводское значение названо заводским | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | configuration.enabled=true, слои: chat_toggle=factory, meme_settings=factory, module_gate=global, observer=global; источник решения 'meme_settings' |
| `AC-MATRIX-CONFIG-GLOBAL` — configuration: общая настройка названа общей | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | configuration.enabled=true, слои: chat_toggle=global, meme_settings=global, module_gate=global, observer=global; источник решения 'meme_settings' |
| `AC-MATRIX-CONFIG-CHAT` — configuration: сохранённый override чата назван слоем чата | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | configuration.enabled=true, слои: chat_toggle=chat, meme_settings=chat, module_gate=global, observer=global; источник решения 'chat' |
| `AC-MATRIX-CONFIG-OFF` — configuration: выключенный механизм — это ВЫКЛ и blocked, а не ожидание | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | meme: configuration.enabled=false, readiness=blocked; текстовая инициатива остаётся True |
| `AC-MATRIX-CONFIG-UNKNOWN` — configuration: нечитаемая настройка — unknown, а не ВЫКЛ | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | configuration.enabled=null, source=read_failed, readiness=unknown |
| `AC-MATRIX-WAIT-COOLDOWN` — ожидание: кулдаун — включено + waiting (полный путь) | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | enabled=true, waiting/cooldown (cooldown_active), «не раньше» 1800003300 = последний вызов + 3600 с |
| `AC-MATRIX-WAIT-MESSAGES` — ожидание: нехватка сообщений — включено + waiting | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | enabled=true, waiting/not_enough_messages, код not_enough_messages, основание unknown |
| `AC-MATRIX-WAIT-QUOTA` — ожидание: дневная квота — включено + waiting с границей сброса | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | enabled=true, waiting/quota, код daily_quota_reached, основание quota_next_reset |
| `AC-MATRIX-WAIT-QUIET` — ожидание: тихие часы — включено + waiting | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | enabled=true, waiting/quiet_hours, код quiet_hours, основание quiet_hours |
| `AC-MATRIX-WAIT-LOTTERY` — ожидание: жребий не выпал — включено + waiting без выдуманного ETA | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | enabled=true, waiting/lottery, код no_random_hit, основание unknown |
| `AC-MATRIX-WAIT-DEFERRED` — ожидание: отложенный артефакт — включено + waiting/deferred | code | `P0IM-AC-MATRIX-CONFIG` | пройдено | enabled=true, waiting/deferred, код publication_conflict, основание unknown |
| `AC-EXPIRED-NOT-BUSY` — истёкший маркер и просроченная бронь не выглядят ожиданием | code |  | пройдено | publication.manual_priority_active=false, expired=true, readiness=waiting, next_basis=unknown |
| `AC-DELIVERY-THREE-STATES` — три состояния доставки различимы | code | `P0IM-AC-MATRIX-FAIL` | пройдено | confirmed(message_id=910011) / unknown / never — три разных состояния |
| `AC-TRACE-PUBLISHED` — трасса опубликованной попытки читается одной историей | code |  | пройдено | run_id=J-pub, outcome=published, stop_stage=publish, mode=auto, incomplete=false |
| `AC-TRACE-STOPPED` — трасса остановленной попытки называет этап остановки | code | `P0IM-AC-MATRIX-FAIL` | пройдено | run_id=J-stop, outcome=failed, stop_stage=image_generation (один связный run) |
| `AC-TRACE-NEVER-STARTED` — отсутствие попытки не выдаётся за попытку | code | `P0IM-AC-MATRIX-FAIL` | пройдено | пустой журнал → last_attempt без времени и без run_id |
| `AC-CODES-UNKNOWN-READABLE` — незнакомый код причины читается и не теряется | code | `P0IM-AC-MATRIX-FAIL` | пройдено | незнакомый код сохранён (matrix_unknown_reason_from_future_release), подпись не пустая ('matrix_unknown_reason_from_future_release'), ось честно unknown, известный код имеет русскую подпись |
| `AC-RBAC-NONADMIN-DENIED` — не-админ получает отказ, запрос без чата отвергается | code | `P0IM-AC-MATRIX-RBAC` | пройдено | не-админ: 403 на диагностике и журнале; запрос без X-Chat-Id: 422 |
| `AC-RBAC-NO-CROSS-CHAT-LEAK` — ответ админа не смешивает данные другого чата | code | `P0IM-AC-MATRIX-RBAC` | пройдено | админ: chat_id=A, run_id=A-ONLY, message_id=510; запрос B отдаёт B-ONLY — данные чатов не смешаны |
| `AC-FRESH-TZ-SOURCE` — свежесть: пояс чата и его источник | code |  | пройдено | пояс: Europe/Moscow (chat) / Asia/Tokyo (global); смещение 10800 с |
| `AC-FRESH-SNAPSHOT-STAMP` — свежесть: серверный штамп и чат-скоуп ответа | code |  | пройдено | basis=server_snapshot, generated_at=1800000300 своего ответа, chat_id=-100777 |
| `AC-LIVE-DEFERRED-CHAIN` — реальная цепочка publisher_not_bound → deferred → delivered | live |  | не наступило | события в снимке нет: отложенных строк 2 (причины: claim_held×2); строк журнала 500; доставок с correlation_id 463 |
| `AC-LIVE-MESSAGE-ID` — доставленная попытка с реальным message_id в журнале | live | `P0IM-AC-MATRIX-FAIL` | пройдено | job_id=meme:-1004482340693:2026-11-12:5dbad95f9091, chat_id=-1004482340693, message_id=11107 сверен с mca_bot_outputs |
| `AC-LIVE-ENDPOINT-AXES` — живой payload эндпоинта: оси, слои и штамп на двух чатах | live | `P0IM-AC-MATRIX-CONFIG` | пройдено | -1002661910336: enabled=True/True, readiness=ready, attempt='meme:-1002661910336:2026-11-12:ebe6f1195118', delivery=confirmed; -1004482340693: enabled=True/True, readiness=waiting, attempt='meme:-1004482340693:2026-11-12:5ce9f57d713b', delivery=confirmed |
| `AC-VISUAL-AXES-DESKTOP` — пять осей и геометрия, 1536×960 | visual | `P0IM-AC-MATRIX-UI` | пройдено | 2 чата; doc.scrollWidth=1536 doc.clientWidth=1536 body.scrollWidth=1536; обрезанных id/дат — 0; версия 2.58.194; text: config='Разрешеновключено — глобальный выключате' now='Сейчасждёт: мало сообщений в окне (код: ' attempt='Последняя попытка12.11 01:09 · автоматич' delivery='Последняя отправкаподтверждено · 11.11 1'; meme: config='Разрешеновключено — настройки мемов этог' now='Сейчасждёт: кулдаун, осталось 5 ч 20 мин' attempt='Последняя попытка12.11 01:09 · автоматич' delivery='Последняя отправкаподтверждено · 12.11 0' |
| `AC-VISUAL-AXES-MOBILE` — пять осей и геометрия, 390×844 | visual | `P0IM-AC-MATRIX-UI` | пройдено | 2 чата; doc.scrollWidth=390 doc.clientWidth=390 body.scrollWidth=390; обрезанных id/дат — 0; версия 2.58.194; text: config='Разрешеновключено — глобальный выключате' now='Сейчасждёт: мало сообщений в окне (код: ' attempt='Последняя попытка12.11 01:09 · автоматич' delivery='Последняя отправкаподтверждено · 11.11 1'; meme: config='Разрешеновключено — настройки мемов этог' now='Сейчасждёт: кулдаун, осталось 5 ч 20 мин' attempt='Последняя попытка12.11 01:09 · автоматич' delivery='Последняя отправкаподтверждено · 12.11 0' |
| `AC-VISUAL-STALE-DISCARD` — гонка scope при медленном API | visual | `P0IM-AC-MATRIX-UI` | пройдено | переключение -1004482340693→-1002661910336 при ответе в полёте (задержка 2.4 с); sentinel 777000111 не появился; карточка после смены: '', после прихода позднего ответа: 'Сейчасможет сработать сейчас — ничего не мешает' |
| `AC-VISUAL-FOREIGN-EXPIRED` — контрпример: чужой chat_id и истёкший маркер | visual | `P0IM-AC-MATRIX-UI` | пройдено | чужой chat_id=-1002661910336 отклонён (карточка «Сейчаснет данных», причина «Состояние механизмов не прочитано: Диагностика при»), sentinel 777000112 в DOM отсутствует; истёкший маркер не изменил ось ('Сейчасждёт: кулдаун, осталось 5 ч 19 мин (код: coo') и не дал busy |
| `AC-POSTREL-BOTH-CHATS` — послерелизные снимки: обзор, трасса, счётчики, доставка/квота | visual | `P0IM-AC-POSTREL` | пройдено | 2 чата, версия на странице 2.58.194, выложено 2.58.194 (6c11fc08); доставка: 'Последняя отправкаподтверждено · 12.11 00:34 · чат -10044823'; счётчики/квота: 'Дневная квотаГенерации сегодня: 1 / 3 · Осталось: 2 · сброс:'; трасса: пропущено |

## Не наступило (событие ещё не произошло)

- `AC-LIVE-DEFERRED-CHAIN`: искали `task_jobs.kind='meme.pending_publish'`, `task_jobs.payload.deferred_detail='publisher_not_bound'`, `task_jobs.payload.run_id`, `task_jobs.status (терминальный)`, `meme_initiative_attempt.job_id = payload.run_id`, `mca_bot_outputs.correlation_id = payload.run_id`, `mca_bot_outputs.tg_message_id IS NOT NULL`.

## Строки карты: что матрица закрывает, а что нет

**Заявляются этой матрицей** (только те пункты, которые реально проверены):

- `P0IM-AC-MATRIX-CONFIG` — проверки: `AC-MATRIX-CONFIG-FACTORY`, `AC-MATRIX-CONFIG-GLOBAL`, `AC-MATRIX-CONFIG-CHAT`, `AC-MATRIX-CONFIG-OFF`, `AC-MATRIX-CONFIG-UNKNOWN`, `AC-MATRIX-WAIT-COOLDOWN`, `AC-MATRIX-WAIT-MESSAGES`, `AC-MATRIX-WAIT-QUOTA`, `AC-MATRIX-WAIT-QUIET`, `AC-MATRIX-WAIT-LOTTERY`, `AC-MATRIX-WAIT-DEFERRED`, `AC-LIVE-ENDPOINT-AXES`
  - закрыто: слой каждого гейта (чат/общий/заводской), «разрешено ВКЛ» при каждом ожидании (кулдаун — полный путь, нехватка сообщений, квота, тихие часы, жребий, отложенный артефакт), выключенный и нечитаемый configuration, живой payload двух боевых чатов с осями и слоями
  - **не закрыто этой матрицей**: «100% вероятности, когда жребий не нужен» и «отсутствие повода у L1» — этой матрицей не проверяются
- `P0IM-AC-MATRIX-FAIL` — проверки: `AC-DELIVERY-THREE-STATES`, `AC-TRACE-STOPPED`, `AC-TRACE-NEVER-STARTED`, `AC-CODES-UNKNOWN-READABLE`, `AC-LIVE-MESSAGE-ID`
  - закрыто: провайдерное исключение на этапе картинки (одна связная история с этапом остановки), отсутствие строки журнала, три состояния доставки включая delivery_unknown, незнакомый код причины, реальный message_id доставленной попытки
  - **не закрыто этой матрицей**: ранние гейты без job_id, обрыв после LLM A/B, пустое изображение, конфликт отправок, старые неполные записи — этой матрицей не проверяются; живая цепочка publisher_not_bound → deferred → delivered ещё НЕ НАБЛЮДАЛАСЬ (отдельная проверка AC-LIVE-DEFERRED-CHAIN)
- `P0IM-AC-MATRIX-RBAC` — проверки: `AC-RBAC-NONADMIN-DENIED`, `AC-RBAC-NO-CROSS-CHAT-LEAK`
  - закрыто: не-админ получает 403, запрос без чата — 422, ответ админа не смешивает данные другого чата (run_id и message_id своего чата)
  - **не закрыто этой матрицей**: полная трасса без утечки секретов не сканируется; конкурирующие чаты и держатели брони этой матрицей не проверяются
- `P0IM-AC-MATRIX-UI` — проверки: `AC-VISUAL-AXES-DESKTOP`, `AC-VISUAL-AXES-MOBILE`, `AC-VISUAL-STALE-DISCARD`, `AC-VISUAL-FOREIGN-EXPIRED`
  - закрыто: реальные рендеры отданной сборки на двух боевых чатах в двух вьюпортах: пять осей обеих карточек, отсутствие горизонтальной прокрутки, отсутствие обрезанных id и дат, гонка scope при медленном ответе (поздний ответ отброшен, причина на экране), контрпример «чужой chat_id и истёкший маркер»
  - **не закрыто этой матрицей**: контрпримеры Reviewer, которые нужно придумывать заново под каждое изменение UI, и мобильный Telegram клиент (реальный TMA-хост): проверяется Chromium с мобильным вьюпортом
- `P0IM-AC-POSTREL` — проверки: `AC-POSTREL-BOTH-CHATS`
  - закрыто: послерелизные снимки отданной сборки по обоим боевым чатам: обзор, раскрытая трасса попытки, строка счётчиков/квоты и строка доставки, штамп версии в DOM и сверка с выложенным SHA
  - **не закрыто этой матрицей**: Telegram-клиент реального устройства и продуктовый вердикт Reviewer по релизу

**НЕ заявляются этой матрицей**:

- `P0IM-AC-MATRIX-MANUAL` — нужен живой ручной `/meme` при исчерпанной квоте и истечение manual_priority_until на проде. Матрица проверяет только семантику истёкшего маркера (AC-EXPIRED-NOT-BUSY и визуальный контрпример)
- `P0IM-AC-DONE` — агрегатный критерий готовности: собирается PM по всем срезам эпика, отдельной проверкой не закрывается

## Покрытие строк карты (только заявленные)

| строка | пройдено | не пройдено | не наступило | заблокировано |
|---|---|---|---|---|
| `P0IM-AC-MATRIX-CONFIG` | 12 | 0 | 0 | 0 |
| `P0IM-AC-MATRIX-FAIL` | 5 | 0 | 0 | 0 |
| `P0IM-AC-MATRIX-RBAC` | 2 | 0 | 0 | 0 |
| `P0IM-AC-MATRIX-UI` | 4 | 0 | 0 | 0 |
| `P0IM-AC-POSTREL` | 1 | 0 | 0 | 0 |

Сводка построена из `plans\features\p0-init-meme-ux-diag\evidence\s7accept\run\result.json` (schema `p0im-accept-matrix/1`): другого источника у неё нет.
