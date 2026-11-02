# Инициативы: независимость механизмов и координация публикаций (Architect, 03.11.2026)

Основание: `plans/owner_inputs/2026-11-03-initiative-independence-coordination.md` (sha 42D6EB80), пп. 1–9 §«Инженерная трактовка». Код: worktree `evol/impl`, база `62e02ff0`. Новый пакет **`INIT-COORD`** (добавить в `slice-graph.json` эпика).
**В scope:** независимость планирования, единый `RandomSourceService`, pre-send координация, межтиповой интервал, диагностика, приоритет `/meme`. **Вне scope:** Direct-ответы и их антифлуд, второй планировщик/cron/воркер, второй QRNG-клиент, RBAC, «успех = только изображение» (`arch/integration-decisions.md` §6), промпты/Writer (P6/P7).

## 1. Независимость: что уже так и все места общего состояния

Уже независимо: ключи/дефолты мемов `meme_initiative.py:84-101`, коды причин `:105-140`, журнал квоты/попыток `:754-943`, статистика `:1727-1763` (`separate_from_initiative`), `blocks_text_initiative()==False` `:267-269`; текстовая — профили/кулдауны/квоты `initiative_observer.py:162-184, 325-334, 1546-1567, 1631-1637`. **Общего helper-сброса нет:** мем пишет только `payload["meme"]` (`:1152-1156`), текст его не читает, мем не пишет `chats`/`counters` — ни один механизм не сбрасывает чужое состояние.

Нарушения (все чинятся в `INIT-COORD`):
- **V1 ростер:** `initiative_observer.py:1139-1146` + `:1315-1331` (`CHATS_TRACKED_MAX=32`) + `:1492` (`MAX_CHATS_PER_PASS`) — список чатов мема = результат текстового scan, тихий чат вытесняется и мем в нём не рассматривается. Решение: свой `meme_chat_roster(db)` — PG `chat_profiles` (прецедент `summary_scheduler.py:104-107`), иначе `db.get_smart_chat_ids()` (`database.py:9263`), фильтр `chat_id<0`, затем `chat_observer_enabled` + настройки мема; лимит попыток за проход — существующая `MAX_CHATS_PER_PASS`.
- **V2 общий try:** `initiative_observer.py:1107-1116` — `_meme_phase` в одном `try` с scan/evaluate, исключение текстовой фазы отменяет проход мема. Решение: отдельный `try`; код `cycle_exception` уже есть (`:1157-1173`).
- **V3 мем невидим ledger:** `initiative_observer.py:1189-1197` — отправка `send_photo` без записи в `mca_bot_outputs`, поэтому `_last_bot_output_age` (`:1367-1382`) не видит мем и текст может ответить сразу после мема. Решение: `record_delivered_output(..., output_kind="meme_initiative", correlation_id=job_id)` (`bot_output_ledger.py:80-141`, `tg_message_id` из возвращённого `Message`, `telegram_send.py:115-124`) + `"meme_initiative"` в `BOT_OUTPUT_KINDS` (`database.py:871-877`, DDL не меняется).
- **V4 chat scope не передан:** `:1147-1151` → `meme_initiative.py:1302-1303` — `chat_enabled` отсутствует, поэтому `initiative.enabled=false` чата мемы **не** останавливает. Решение: передать `chat_enabled=chat_observer_enabled`.
- **V5 нет учёта чужого типа:** `meme_initiative.py:1326-1329` (кулдаун только по своей брони) vs `initiative_observer.py:1546-1552` (`INITIATIVE_OUTPUT_KINDS`) → «спам-пара». Закрывается §3–§4.
- **V6 (не дефект):** `initiative_observer.py:1639-1650` потребляет `worker_budget.llm_calls`, мем — нет; асимметрия без взаимного лимита, менять не нужно.

## 2. Случайность: один сервис, два независимых draw

Клиент один — `mca_random_source.py` (`:1537-1569 draw_probability`); второго клиента/генератора/локального `random` нет. Два санкционированных purpose: существующий `meme_trigger` (`:93, 109-116`) и новый `initiative_trigger` (в `SANCTIONED_DRAW_PURPOSES`, в `EXPLORATION_PROBABILITY_KEYS` — нет).
Порог — своя настройка каждого: `initiative.meme_trigger_probability` (0.05, `meme_initiative.py:100`) и новая `initiative.trigger_probability` (дефолт **1.0** ⇒ draw не выполняется, пишется `probability_one`; поведение текстовой инициативы байт-паритетно, шов тестируется при `p<1`).
Правило фактического источника (одно на оба): `deferred`/`value is None`/gate OFF → `random_unavailable` без действия; значение есть → решение действительно, в трассировку идёт **реально использованный** `source/provider/fallback_reason`. Отвергнуто поведение `meme_initiative.py:1070-1073` (`fallback_reason` = недоступность): оно отменяет настройку владельца `memory.random_fallback_to_pseudorandom` (`mca_random_source.py:137, 149-150`) и глушит мемы на всё время недоступности QRNG; тест `tests/test_evol014_meme_initiative.py:250-257` (кейс `c`) меняет ожидание на «публикация с `source=pseudorandom`», кейсы `a`/`b` остаются `random_unavailable`.
Поля трассировки (одинаковый JSON): `purpose, probability, value, hit, draw_id, source, source_impl, provider, selected_source, fallback_reason, policy_version, attempts, deferred, reason, ts` (`DrawResult` `mca_random_source.py:961-978`, `_meta` `:1581-1596`).
Хранение: мем — `facts["eligible"]["random"]` + тот же JSON в `detail` скипа (`no_random_hit`/`random_unavailable`), разбор единственным `parse_attempt_facts` (`meme_initiative.py:1154-1168`); текстовая — `chats[chat]["last_decision"]` в durable payload `task_jobs` + событие `initiative_observer_decision`.

## 3. Координация публикаций: где проверка и чем обеспечена атомарность

Новый модуль `services/publication_coordination.py` (интервал, чтение ledger, claim, маркер). Читаемая модель «недавние публикации» — **существующий** ledger: `db.list_recent_bot_outputs(chat_id, limit=2, kinds=PUBLICATION_KINDS)` (`database.py:5202-5225`), `PUBLICATION_KINDS=("initiative_reply","meme_initiative")` (первый пишется `direct_chat_service.py:13293-13297`, второй — V3). Два уровня, не путать: **проверка объясняет** (дешёвая, до дорогой генерации), **claim решает** (атомарно, перед отправкой).

1. Pre-check: текст — `initiative_observer.py:1555-1561` (рядом с антифлудом, до day-cap и LLM); мем — `meme_initiative.py:1326-1332` (после кулдауна/тихих часов, до чтения окна). Причина — `publication_conflict` + `detail` ∈ `cross_type_interval|claim_held|manual_priority`.
2. Claim — v41 таблица `chat_publish_claim`: PK `chat_id` (одна строка на чат), поля `claim_id, holder_kind, holder_ref, state, claimed_at, expires_at, last_publish_ts, last_publish_kind, last_publish_ref, manual_priority_until, updated_at`. Шаг `_migrate_chat_publish_claim_v41` рядом с v40 (`database.py:2983-2985`, образец `:3342-3367`), `CREATE TABLE IF NOT EXISTS`, откат — cold revert (таблица инертна). PG-копии нет: состояние отправки живёт в операционной SQLite рядом с `mca_bot_outputs`.
3. **Примитив «ровно одна публикация» — compare-and-set одним `UPSERT`-стейтментом** по строке `chat_id`, без `BEGIN IMMEDIATE`-блока и без in-process lock:

```sql
INSERT INTO chat_publish_claim(chat_id, claim_id, holder_kind, holder_ref, state, claimed_at,
  expires_at, last_publish_ts, last_publish_kind, last_publish_ref, manual_priority_until, updated_at)
VALUES(:chat,:cid,:kind,:ref,'claimed',:now,:exp,NULL,NULL,'',NULL,:now)
ON CONFLICT(chat_id) DO UPDATE SET claim_id=excluded.claim_id, holder_kind=excluded.holder_kind,
  holder_ref=excluded.holder_ref, state='claimed', claimed_at=excluded.claimed_at,
  expires_at=excluded.expires_at, updated_at=excluded.updated_at
WHERE (chat_publish_claim.state IN ('released','cancelled')
    OR chat_publish_claim.expires_at <= :now
    OR (:manual = 1 AND chat_publish_claim.state = 'claimed'))
  AND (:manual = 1 OR chat_publish_claim.manual_priority_until IS NULL
       OR chat_publish_claim.manual_priority_until <= :now)
  AND (:manual = 1 OR :other_ts IS NULL OR :now - :other_ts >= :interval);
```

   `rowcount==1` → claim выдан, `0` → проигравший (`:other_ts` — `sent_at` последней публикации **другого** типа; равный тип интервалом не ограничивается). Разрешение звать sender — второй стейтмент: `UPDATE ... SET state='sending', expires_at=:exp2 WHERE chat_id=:chat AND claim_id=:cid AND state='claimed' AND expires_at > :now AND (manual_priority_until IS NULL OR manual_priority_until <= :now)`; `rowcount==1` → отправляем, `0` → отмена с причиной (`publication_conflict`/`manual_priority`/`publication_expired`), sender не вызывается. Release после отправки: `state='released', last_publish_ts=:sent_at, last_publish_kind=:kind, last_publish_ref=:ref`. Оба стейтмента — через `write_transaction` (`database.py:2578-2617`); атомарность даёт сам `UPSERT`/`UPDATE` в SQLite (WAL), поэтому N воркеров и N процессов видят один результат. TTL-константы: `claimed` 90 с, `sending` 120 с, `manual_priority_until` 600 с (срок жизни брони, не «пауза», без `sleep`).
4. Проигравший/устаревание: **мем** — отмена с явной причиной, сгенерированная картинка позже не отправляется никогда, свой кулдаун/квота не сбрасываются; **текстовая** — отмена реплики, durable intent остаётся `pending` и существующий `_f6_plan_next_check` перепроверит на свежем контексте (это и есть «отложить с повторной проверкой», без нового планировщика); **свежесть** — текст: существующий `plan_logical_send`/`SendRecheck` перед send (`direct_chat_service.py:13067-13200`) + guard ниже; мем: после claim перечитывается watermark окна (`MAX(id)` в `smart_messages` по чату) и сравнивается с watermark на старте генерации, изменился → `publication_stale`, claim освобождён, отправки нет.
5. Точки вызова (заморожены; полный перечень вызывающих расширен и заморожен в §10): текст — claim перед `handle_initiative` (`initiative_observer.py:1828-1832`), release в `finally`, внутри — необязательный `publish_guard: Callable[[], Awaitable[str|None]]` ровно в `direct_chat_service.py:13173-13178` (после `note_recheck_passed`, до отправки): делает `claimed→sending` и возвращает код причины при отказе (исход `cancelled`, intent жив), дефолт `None` = текущее поведение Direct. Мем — claim перед `SendRecheck`-гейтом (`meme_initiative.py:1519-1527`), `claimed→sending` перед `sender` (`:1543-1546`), release сразу после записи в ledger.
6. Деградация: таблицы нет → мем останавливается на существующем `schema_absent`; текстовая **публикует** с `coordination=degraded` + один WARN (нельзя молча выключать основной механизм из-за служебной таблицы).
Отвергнуто: глобальный `asyncio.Lock` на чат (не работает между воркерами/рестартами, запрещён владельцем); уникальный индекс `(chat_id, bucket)` (не выражает «разрешено после TTL»); CAS по `mca_bot_outputs` (append-only пишется ПОСЛЕ отправки); PG advisory lock (состояние отправки не PG); очередь публикаций/второй воркер (запрещено).

## 4. Межтиповой интервал (не вместо кулдаунов)

Ключ `initiative.cross_type_publication_interval_seconds`, дефолт `MIN_GAP_FLOOR_SECONDS = 1800` (`initiative_observer.py:200`) — существующая константа, не новое число. Резолв — как у мем-настроек: chat override → hot → дефолт (`meme_initiative.py:342-353`), одна функция модуля, оба механизма читают её. Область: глобально + per-chat; UI/API — аддитивное поле в открытом web-пакете (P4), рантайм работает без UI.
Взаимодействие: интервал ограничивает **только пару разных типов** и только по `sent_at` чужой публикации; свои кулдаун/расписание/квота остаются; действующий зазор = `max(свой кулдаун, интервал)`. `interval=0` → координация по интервалу выключена (claim всё равно даёт ровно одну публикацию); `0<interval<cooldown` ничего не укорачивает (кулдаун больше); `interval>cooldown` удлиняет паузу между типами — ожидаемо. Отвергнуто: хардкод 300/1800 в точках отправки; общий анти-спам-счётчик на оба типа (ограничил бы механизмы друг другом).

## 5. Настройки и мастер-тумблер

Остаются как есть: мастер `flags.initiative_observer_enabled` (`initiative_observer.py:325, 374-390`), чат `initiative.enabled` (`:326, 409-419`), мем `flags.meme_initiative_enabled` (`meme_initiative.py:84, 95`). Кулдауны/квоты текста — `initiative.min_gap_seconds`, `initiative.max_replies_per_day`, `initiative.max_replies_per_topic`, `initiative.eval_llm_budget_per_day`; мема — `initiative.meme_cooldown_seconds`, `initiative.meme_daily_limit`, `initiative.meme_trigger_probability`, `initiative.meme_min_messages`, `initiative.meme_quiet_hours`; пересечений нет. Новые оси пакета: `initiative.trigger_probability` (§2) и `initiative.cross_type_publication_interval_seconds` (§4). Выключение мемов не меняет ни одного текстового гейта, и наоборот; V4 закрывает единственную утечку в обратную сторону.

## 6. `/meme` — приоритет без гонки

RBAC/автоудаление/генерация — по `arch/integration-decisions.md` §4/§10 (не меняются). Перед генерацией ставится маркер `UPDATE chat_publish_claim SET manual_priority_until=:now+600 WHERE chat_id=:chat` одним стейтментом (строки нет — вставка со `state='cancelled'`): с этого момента авто-путь не может перейти в `sending` (§3), приоритет заявлен атомарно. Публикация: manual-claim (`:manual=1`) забирает строку у `claimed`; при `sending` — ждёт in-process событие владельца брони и делает одну повторную попытку, не дождались → честный `publication_in_flight` в админский ответ, второй публикации нет. Авто-путь при активном маркере получает `publication_conflict/manual_priority`: мем отменяется, текстовая откладывается через intent (§3.4). Ручной запрос интервалом не ограничивается (он приоритетный), но его публикация пишется в ledger, поэтому интервал потом считается и от неё.

## 7. Диагностика (поля; хранение — существующее)

| Поле | Текстовая инициатива | Мем |
|---|---|---|
| последняя проверка | `chats[chat].last_eval_ts` | `last_provider_ts` + `MAX(ts)` журнала попыток |
| следующая проверка | `last_eval_ts + eval_min_interval_seconds` (гейт `eval_interval`, `:2041-2052`) | `max(last_provider_ts+cooldown, начало дня квоты)` |
| результат random | `last_decision.random` (§2) | `facts.eligible.random` / `detail` скипа |
| источник случайности | `source/provider/source_impl/fallback_reason` | те же поля |
| выполненные условия | гейты `chat_block_state` `:1977-2172` | `counters` этапов журнала |
| причина пропуска | `counters.eval_skips` + `random_miss`/`publication_conflict` | `reason_code` строки журнала |
| собственный кулдаун | гейт `min_gap` (есть) | новый гейт `meme_cooldown` в `availability` |
| конфликт публикаций | гейт `publication` (state/holder/last_publish_ts/интервал/gap) | `facts.publish.publication` + строка скипа |

Источники только существующие: payload `task_jobs` (`initiative_observer.py:1919-1945`), журнал `meme_initiative_attempt` (`meme_initiative.py:917-933`), `analytics_snapshot` (`:1727-1763`), ledger (чтение). Новых таблиц диагностики нет; читается тем же `/api/memory/initiative-vitality` и мем-аналитикой. События: `initiative_publication_claim` (`stage=claim:granted|held|released|preempted|expired`, `reason_code`, `entity_id=claim_id`) и `initiative_publication_conflict` (+`other_kind`): только ID/коды/числа.

## 8. Контракт Reviewer (фальсифицируемые проверки)

- **R1 независимость:** выключение мемов не мешает текстовой публикации (`tests/test_evol014_meme_initiative.py:138`); `initiative.enabled=false` → мем не публикует (V4); исключение в `_evaluate_phase` → `payload["meme"]` содержит попытку (V2); тихий чат без новых сообщений → мем всё равно рассматривается (V1).
- **R2 одновременная готовность:** оба готовы → ровно одна публикация, у проигравшего `publication_conflict/cross_type_interval`, sender не вызван (счётчик вызовов на двоих = 1).
- **R3 N воркеров:** 8 корутин `asyncio.gather` на одном tmp-файле SQLite → ровно один `claim_id` дошёл до `sending`, sender вызван один раз (проверка по `claim_id`, не по времени).
- **R4 рестарт:** `state='sending'` с истёкшим `expires_at` → следующий acquire проходит, `last_publish_ts=claimed_at`, причина `delivery_unknown` видна, повторной отправки нет.
- **R5 `/meme`:** при чужом `claimed` маркер ставится до генерации, авто-путь не отправляет, ручной публикует ровно один раз; при чужом `sending` — `publication_in_flight` без второй публикации.
- **R6 разные чаты:** одновременные acquire в двух чатах оба успешны (глобальной блокировки нет).
- **R7 без дублей:** на `correlation_id`/`job_id` максимум одна delivered-строка (`database.py:5481-5485`), в том числе после рестарта; на `claim_id` — один `sending`.
- **R8 источник случайности:** один кейс через реальный `RandomSourceService.draw_probability` (gate ON, PRNG) показывает фактический `source`; для QRNG `provider/source_impl` не выдумываются.
- **Запрещено:** `asyncio.sleep`/`time.sleep` в тестах для эмуляции таймингов (время — параметром `now`/`now_ts`), хардкод таймингов вместо настроек, глобальный `asyncio.Lock` на все чаты, второй планировщик/cron/воркер, второй random-клиент, подмена subject-under-test моками (`sender`/`image_provider`/`source` как существующий DI-шов — допустимы).

## 9. Параллельность, миграция, откат, риск

`SERIALIZE`: `services/meme_initiative.py` — за P5/P6; `services/initiative_observer.py`, `handlers/meme_command.py` — за P3 `MEME-MANUAL-CMD`; `services/direct_chat_service.py` — за P6; поэтому `INIT-COORD` идёт после P1–P6. `PARALLEL_SAFE` внутри пакета: `services/publication_coordination.py`, `tests/test_initiative_coordination.py`. `READ_ONLY_PARALLEL`: `mca_random_source.py` (только purpose-константа), `bot_output_ledger.py`, `web/api/*`.
Схема: одна аддитивная таблица v41 (PK `chat_id`, без индексов и backfill); `BOT_OUTPUT_KINDS` — правка frozenset, DDL не меняется. Откат: cold git revert — таблица инертна, старый код её не читает, ledger-строки `meme_initiative` валидны. Риск **R2**: хрупкий шов — порядок «claim → fresh recheck → sending» и одинаковое чтение интервала обоими механизмами; ошибка даёт либо дубль публикации, либо тихую остановку текстовой инициативы (деградация §3.6). Живая приёмка: прогон `/meme` в чате владельца + наблюдение, что после мема текстовая инициатива не публикует в пределах интервала (PET_PROJECT, без новых гейтов).
**Реального решения за владельцем не остаётся:** приоритет `/meme`, независимость настроек, мастер-тумблер и запрет второго планировщика заданы дословно; дефолты пакета берут существующие константы (`MIN_GAP_FLOOR_SECONDS`, `ANTI_FLOOD_AFTER_BOT_OUTPUT_SECONDS`), а поведение текстовой инициативы при `trigger_probability=1.0` байт-паритетно.

## 10. B2 координационного ревью: третьи точки текстовой отправки — включить (вариант A)

Решение: **включить, и не только nostalgia — закрыть весь класс вызывающих.** §10 заменяет перечень вызывающих из §3.5; остальные решения §3–§4 не меняются. Human Gate не нужен: требование владельца дано дословно.

### 10.1 Что показал код (`evol/impl`, база `fb5d7f97`)

`handle_initiative` (`direct_chat_service.py:12798`) — единственный шов текстовой отправки: текст уходит только в `:13204`/`:13236` после `note_recheck_passed` (`:13153`), запись в ledger — `:13270-13282` с `output_kind="initiative_reply"` (`direct_output_kind`, `:1316-1324`). Координация §3.5 сделана **на стороне вызывающего**, поэтому любой вызывающий без неё проходит шов молча.

| Вызывающий (production) | Что делает | Координация |
|---|---|---|
| `initiative_observer.py:1828` | плановая текстовая инициатива | claim по §3.5 |
| `nostalgia_worker.py:1093` (`_delegate_initiative`, K1+K3 ON) | инициативный текст `trigger_kind=nostalgia_due` | нет |
| `nostalgia_worker.py:1051-1054` (K1/K3 OFF, `:187`) | прямой `bot.send_message`, ledger не пишется | нет |
| `memory_maintenance.py:593` (`_run_initiative_candidate`, тик `:474`, job `:301`) | доставка due-интентов тем же `handle_initiative` с `writer_service` (F6: REPLY пересобирается L2 Writer) | нет |
| `initiative_diagnostics.py:1047` | админ-проверка; `use_mock` `:1010`, при `publish and publish_axis and confirm_publish` — реальная отправка | нет |

Два факта снимают довод «dormant, значит неважно»:

1. **nostalgia — не третий механизм, а триггер этого же:** `mca_intents.candidate_from_trigger(trigger_kind="nostalgia_due", source="nostalgia")` → делегирование в `handle_initiative`; её публикация уже пишется в ledger как `initiative_reply`, то есть мем её видит, а она мема — нет. Границы §0 (Direct вне scope) не размываются: `mimic_relay.py:56`, `dead_page_relay.py:718`, `progress_reporter.py:160` — реактивные ответы, не автономные публикации инициативы.
2. **heartbeat не dormant:** K1/K2/K3 = True (`settings.py:1607-1612`), job ставится в `MemoryMaintenanceService.start()` (`:301`), сервис поднимается в `bot.py:678-682`. Пара «мем → текстовая инициатива через 20 с» достижима в текущей живой конфигурации без флагов владельца.

Пауза nostalgia не спасает: её тишина считается от последнего **пользовательского** сообщения (`nostalgia_worker.py:802`), публикация бота её не сдвигает.

### 10.2 Почему не вариант B

Оставлять путь исключённым нельзя: (а) он внутри механизма, который владелец назвал, и пишет в тот же чат; (б) `memory.nostalgia_enabled` — hot-флаг, включается без правки кода, «dormant» не инвариант, а состояние на сегодня; (в) сужение `MEME-IIC-PRESEND-RECENT-CHECK` зафиксировало бы непокрытое поведение как покрытое — карта перестала бы быть доказательством. Требование владельца — про наблюдаемое поведение в чате, поэтому третий путь в scope.

### 10.3 Замороженный контракт (Builder)

`services/publication_coordination.py` получает текстовый набор поверх §3.3: `precheck_text(chat_id, now)` (только чтение, объясняет причину), `acquire_text(chat_id, holder_ref, now)` (CAS-UPSERT §3.3, `holder_kind="text_initiative"`), `permit_send(claim)` (`claimed→sending`), `release(claim, kind="initiative_reply", ref, sent_at)`, `cancel(claim, reason)`; повторный release/cancel идемпотентен по `claim_id`+`state`.

**Источник интервала — строка claim (`last_publish_ts`, `last_publish_kind`)**; ledger — для pre-check/объяснения и для путей без claim (Direct). Уточнение §3.1: иначе legacy-ветке nostalgia понадобился бы новый `output_kind` и правка `BOT_OUTPUT_KINDS`/аналитики.

Порядок у всех вызывающих двухуровневый (§3): дешёвый `precheck_text` до дорогой генерации, авторитетный `acquire_text` перед отправкой, `release`/`cancel` в `finally`.

- **nostalgia, делегированная ветка** (`:1093`): precheck после своего кулдауна (`:825-831`), acquire перед `_delegate_initiative`, `publish_guard=` в вызов, release при `status=="sent"` (`sent_at=then`), cancel при прочих статусах. Отказ → `skipped`, `reason="publication_conflict"` + `detail` (`cross_type_interval|claim_held|manual_priority`); кандидат не сгорает — следующий тик пересоберёт выборку.
- **nostalgia, legacy-ветка** (`:1051-1054`): acquire → `permit_send` → `bot.send_message` → release(`initiative_reply`). Отказ → `skipped/publication_conflict`, `bot.send_message` не вызывается. При выключенных K1/K3 это единственный текстовый отправитель, а мемы от K1/K3 не зависят — пару держим и здесь.
- **heartbeat** (`_run_initiative_candidate`): precheck до `worker_budget.consume` (отказ не тратит LLM-бюджет), acquire перед `initiative_entry(...)` (`:593`), `publish_guard=` в вызов, release/cancel в `finally`. Отказ → интент остаётся `pending`/`deferred` (не закрывается, не помечается ошибкой), причина в существующий лог/событие heartbeat; повтор — следующим тиком (≈300 с), то есть «отложить с повторной проверкой» без нового планировщика.
- **диагностика** (`:1047`): `use_mock=True` → `publish_guard=None`, claim не трогаем; реальная публикация — как manual: маркер `manual_priority_until` до генерации + claim + release(`initiative_reply`), чтобы интервал считался и от неё (§6).
- Сигнатура `handle_initiative` не меняется: `publish_guard` остаётся опциональным, `None` = прежнее поведение (Direct, тесты). Обязательный kwarg отвергнут: ~60 прямых вызовов в тестах плюс dry-run диагностики, выигрыша нет при наличии структурной проверки ниже.

**Структурная защита от повтора класса:** тест в `tests/test_initiative_coordination.py` обходит AST `services/*.py`, находит вызовы `handle_initiative` и падает, если у вызова нет `publish_guard=`; `None` допустим только в явно перечисленных dry-run местах. Проверка обязана уметь падать (T5).

TTL остаётся из §3.3 (90/120 с); Reviewer отдельно подтверждает, что `sending`-TTL больше бюджета Writer-вызова, иначе долгая генерация даст лишний `publication_expired`.

### 10.4 Проверка (фальсифицируемо)

- **T1** nostalgia (K1+K3 ON) + claim-строка с `last_publish_kind="meme_initiative"` внутри интервала → `handle_initiative` не вызывается, отправки нет, skip `publication_conflict/cross_type_interval`.
- **T2** nostalgia (K1/K3 OFF) + та же строка → `bot.calls == []`, skip `publication_conflict`, статус `skipped` (не `error`).
- **T3** чистая строка claim → ровно одна отправка + release с `last_publish_kind="initiative_reply"`; следующий `acquire` мема внутри интервала → отказ `cross_type_interval` (обратное направление пары).
- **T4** heartbeat: due-интент + мем в интервале → отправки нет, интент `pending`, LLM-бюджет не потрачен; после сдвига `now` за интервал — одна отправка и release.
- **T5** структурная проверка §10.3 падает на синтетическом вызове без `publish_guard=`.
- Деградация: таблицы claim нет → nostalgia/heartbeat публикуют с `coordination=degraded` + один WARN (§3.6 распространён на них); мем по-прежнему `schema_absent`.
- Без `sleep`, время параметром `now`. Тесты — новые в `tests/test_initiative_coordination.py` и в существующем harness `tests/test_nostalgia_worker.py:801-830` (`_spy` получает `publish_guard`).

### 10.5 Карта, владение, параллельность, риск

- **Карта (PM):** строку `MEME-IIC-PRESEND-RECENT-CHECK` **не сужать**; добавить в slice `MEME-INIT-COORDINATION` строку `MEME-IIC-TEXT-CALLSITES-COORDINATED` (все отправляющие вызовы `handle_initiative` держат claim: observer, nostalgia обе ветки, heartbeat, диагностика в реальном режиме + структурная проверка) и расширить `write_scope` слайса на `services/nostalgia_worker.py`, `services/memory_maintenance.py`, `services/initiative_diagnostics.py`, `tests/test_nostalgia_worker.py`.
- **Владение:** Builder — код и T1–T5 внутри `MEME-INIT-COORDINATION`; PM — только строка и scope; Reviewer — независимая фальсификация (T5 + попытка провести пару через heartbeat).
- **Параллельность:** три файла не входят ни в один активный write-scope (активны P2 `MEME-API-SCOPE` и COG-MAP S3) → `PARALLEL_SAFE` внутри пакета; `services/direct_chat_service.py` по-прежнему за P6 (`SERIALIZE`).
- **Риск:** новый отказной режим — «nostalgia/heartbeat отложены из-за чужой публикации», виден как `publication_conflict` (интент остаётся pending, nostalgia-кандидат пересобирается), тихой потери публикации нет; риск пакета остаётся R2. Обратный риск (не сделать) — действующий разрыв требования владельца в живой конфигурации.
- **Живая приёмка:** после релиза `/meme` в чате владельца и наблюдение, что в пределах интервала не приходит ни инициативная реплика, ни heartbeat-текст (PET_PROJECT, без новых гейтов).
