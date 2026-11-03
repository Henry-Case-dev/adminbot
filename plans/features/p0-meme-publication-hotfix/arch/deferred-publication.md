# B1 — durable-доставка отложенного мема (готовый артефакт не выбрасывается)

Источник (позже и главнее arch §3.3/§3.5 от 08:34): `plans/owner_inputs/2026-11-03-hotfix-meme-publication-initiative-ui.md`
§1.2.5 — «При конфликте отложить/координировать доставку через существующие ledger/durable-механизмы,
не выбрасывать уже готовый результат и не перегенерировать из-за новых сообщений».
Кандидат: `b95b7363` (`fix/p0-publication-stale`). Роль: Architect. Ниже — единственное решение, без ADR.
Статус: **решение принято; вопрос владельцу не требуется** (обоснование §11).

## 0. Решение одной строкой

Готовый авто-мем, проигравший бронь публикации, **сохраняется** как `task_jobs`-строка вида
`kind="meme.pending_publish"` (существующая таблица v14, без изменения схемы) + байты в
`var/meme_pending/<job>.bin` (существующий git-ignored managed-каталог рантайма), и доставляется
следующим проходом **существующего** мем-тик-а (`initiative_observer._meme_phase` → `meme_initiative.on_initiative_cycle`,
тик 300 с) при законно свободном слоте — ровно один раз, без повторного списания квоты и без повторной генерации.
По истечении ретенции — честный терминальный исход с кодом, а не тихая потеря.

## 1. Что происходит сейчас (факты кандидата, с якорями)

- `services/meme_initiative.py:2078-2090` — `coordinator.acquire(...)`; `:2091-2107` — при `not claim.granted`
  пишется `publication_deferred_conflict`, `_finish` закрывает попытку, а `content` (байты) **никуда не сохраняется**.
  `generated=True`, `published=False`, квота при этом уже списана (`COUNTED_STATUSES` `:243`; провайдер вызван,
  `ledger.mark(jid,"provider_called")` `:2029`).
- Квота одноразовая по `job_id` (`reserve` `:1009-1061`, повтор того же job → `already/provider_called`), поэтому
  «дождаться слота и переиспользовать бронь» невозможно: артефакт теряется, следующий проход берёт новый `job_id`
  (`:1713`) и делает **второй платный вызов**.
- Межтиповой интервал по умолчанию 1800 с (`services/publication_coordination.py:82,355-373`,
  `initiative_observer.MIN_GAP_FLOOR_SECONDS`), значит «просто подождать» в рамках одного прохода бессмысленно:
  нужен durable носитель, переживающий проходы и рестарт.
- Готовый контент — сырые байты в памяти: `_default_image` `:2478-2487` (`services/image_generation.GenerationResult.content`,
  `bytes | None`), лимит `IMAGE_MAX_BYTES = 9 MiB` (`config/settings.py:779`, `image_generation.py:1547`).
- Уже есть ровно тот durable-механизм, который называет владелец: **`task_jobs`** (v14, `services/database.py:205-235`:
  `coalesce_key` + unique partial на активных статусах, `deadline_at`, `fencing_token`, `attempt`)
  с API `TaskJobStore` (`services/task_supervisor.py:407-753`) и **существующим прецедентом «отложенное намерение»**:
  `media_readiness.register_pending_intent` (`services/media_readiness.py:856-890`, `kind="vision.pending_intent"`,
  TTL из `limits.vision_pending_intent_ttl_seconds`, честное закрытие `_expire_intent` `:916-934`,
  возобновление `resume_deferred_requests` `:2068`).
- Существующие тик-энтри: `memory_maintenance._tick_initiative_observer` (`services/memory_maintenance.py:430-447`,
  `_INITIATIVE_OBSERVER_TICK_SECONDS = 300` `:90`) → `initiative_observer.observe_tick` → `_meme_phase`
  (`services/initiative_observer.py:1447-1475`, вызов `:1426`) → `meme.on_initiative_cycle` (`:2490-2515`).
- Бронь публикации — `chat_publish_claim` (v41, `publication_coordination.py:69-76,103-141`), единственный
  разрешающий механизм отправки: `acquire` `:434+`, `begin_sending` `:193-200`, `release` `:202-214`.
- Каталог рантайма: `var/` в `.gitignore:86`, прецедент durable-файлов `var/cover_style_assets`
  (`services/cover_style_assets.py:34-39`, «метаданные в БД, байты НЕ в БД»).

## 2. (a) Хранение: bytes на диске + метаданные в существующей `task_jobs`. Схема НЕ меняется

**Метаданные — строка `task_jobs`**, без новой таблицы:

| Поле `task_jobs` | Значение для отложенного мема |
|---|---|
| `job_id` | новый `uuid4().hex` (безопасное имя файла) |
| `owner` | `"meme.initiative"` |
| `kind` | `"meme.pending_publish"` (новое значение колонки, не новая сущность) |
| `coalesce_key` | `"meme:pending_publish:<chat_id>"` → unique partial v14 гарантирует **одну** активную запись на чат |
| `payload` | компактный JSON (см. §3), без текста сообщений (R17-safe) |
| `status` | `queued` → `running` → `completed`/`failed`/`cancelled`/`interrupted` |
| `deadline_at` | `now + retention` (§6) |
| `attempt` | счётчик проходов-попыток (диагностика, не политика) |
| `result_ref` | путь файла (`var/meme_pending/<job_id>.bin`) |

**Байты — файл** `var/meme_pending/<job_id>.bin`, режим `0600`, атомарная запись temp + `os.replace`
(тот же приём уже есть: `services/cover_style_jobs.py:476-480`, `services/image_generation.py:1631`).
Каталог кладётся рядом с существующим `var/` (env-override по образцу `cover_style_assets.assets_dir()`),
в git не попадает, `git pull --ff-only` на проде не пачкает.

**Почему не другая форма:**
- *не base64 в `payload`*: до 9 MiB → ~12 MiB TEXT в WAL/бэкапах и JSON-парсинг на каждом чтении; проект уже
  зафиксировал правило «байты не в БД» (`cover_style_assets.py:9-14`);
- *не `media/`*: `MEDIA_BASE="media"` (`config/settings.py:183`) лежит **внутри git-дерева деплоя** — рантайм-запись
  сделала бы рабочее дерево грязным и сломала бы `git pull --ff-only`;
- *не `cover_style_assets` registry*: это пользовательский каталог стилей обложек (durable library, `deleted_at`),
  смешивание с 30-минутными мем-артефактами испортит инвентарь и потребует других жизненных циклов;
- *не `meme_initiative_attempt`*: журнал append-only (`INSERT OR IGNORE` `:1127-1141`), терминальная строка —
  аудит «что произошло», а не рабочий элемент с изменяемым состоянием;
- *не `chat_publish_claim`*: это локалка/бронь с TTL 90/120 с, не очередь с payload;
- *новая таблица не нужна*: `task_jobs` уже даёт singleflight, deadline, fencing и существующий API, а прецедент
  `vision.pending_intent` — то же самое «отложить до условия». Новая таблица добавила бы миграцию v42 без выгоды.

## 3. Payload (ровно то, что нужно для поздней доставки)

```json
{"chat_id": 123, "run_id": "meme:123:<bucket>:<hex>", "created_at": 0, "expires_at": 0,
 "sha256": "…", "size": 0, "mime": "image/png",
 "deferred_reason": "publication_conflict", "deferred_detail": "cross_type_interval",
 "msg_ids": [..], "msg_count": 0, "first_id": 0, "last_id": 0, "snapshot_digest": "…",
 "prompt_origin": "factory|custom", "purpose": "meme_initiative", "mode": "automatic"}
```

`prompt`/`joke` **не** сохраняются: отправитель их не использует (контракт «только изображение»,
`initiative_observer._meme_sender` → `send_photo` без caption; `sender(chat_id, content, prompt)` принимает
`prompt=""`). `msg_ids` нужны ровно для честной проверки «источник удалён» (`_default_source_check` `:1567-1595`,
`SourceSnapshot` `:1479-1514`).

## 4. (b) Кто выполняет ретрай — существующий мем-тик, новых планировщиков нет

Точка входа — `on_initiative_cycle` (`:2490`), которая уже вызывается каждые ~300 с из
`_meme_phase` (`initiative_observer.py:1426,1468-1475`). В начале цикла:

```
deliver_deferred_all(db, chat_ids=<ростер этого прохода>, ledger, sender, publish_gate,
                     claim_store, publication, chat_enabled, initiative_enabled, settings, now_ts)
```

— перебирает **только активные строки `meme.pending_publish`** (их максимум по одной на чат) и не зависит
от ротации `MAX_CHATS_PER_PASS` (`meme_initiative.py:402-406`), иначе «голодный» чат мог бы ждать неделями.

Внутри `consider_chat` (`:1615`) — только анти-перегенерация: при наличии активной строки и неудавшейся
попытке доставки проход **не генерирует** новый мем и возвращает результат ожидания (§8, п.4).

## 5. (c) Ретрай-машина состояний

```
нет строки --[генерация ok, claim не выдан, mode=automatic]--> queued   (файл записан, deadline=now+retention)
queued --[страж ok; mark_running CAS]--> running --[claim+begin_sending ok; sender ok]--> completed (publication_sent, bytes удалены)
running --[sender бросил]--> failed (delivery_unknown: НЕ переотправлять, bytes удалены)
queued --[слот занят / тихие часы]--> queued (requeue, без строки журнала, bytes сохранены)
queued --[терминальный страж: модуль/инициатива/права/источник/гейт]--> cancelled (<свой код>, bytes удалены)
queued --[now >= deadline_at]--> cancelled "deferred_publication_expired" (bytes удалены)
running --[падение процесса]--> interrupted (watchdog recover_stale :547-569) --> failed delivery_unknown (bytes удалены)
```

Страж-порядок при каждой попытке доставки (сначала дешёвое, дорогое — перед отправкой):

1. `_param(chat_id, KEY_ENABLED, cfg.enabled)` → off ⇒ `disabled_by_setting`;
2. `initiative_enabled()` → off ⇒ `initiative_disabled`;
3. `chat_enabled(chat_id)` → off ⇒ `initiative_disabled` (`detail=chat_gate_disabled`);
4. чат отсутствует в реальном ростере кандидатов (`_candidate_chat_ids` `:365-387`) ⇒ **`rights_revoked`** (новый код, §7);
5. исходные сообщения снапшота удалены (`_default_source_check`) ⇒ `source_material_gone`;
6. `publish_gate` (существующий шов, `_default_publish_gate` `:1598-1612`) ⇒ `publish_blocked`;
7. тихие часы (`quiet_hours_block` `:923`) ⇒ **не** терминал: остаётся `queued`, без брони и без записи журнала;
8. `acquire` не выдан ⇒ остаётся `queued` (requeue), причина в `reason_code` строки, без записи журнала;
9. `claim.recovered_delivery_unknown == True` (`:2085-2090`) ⇒ **не отправлять**: терминал `delivery_unknown`
   (предыдущая отправка не доказана и не опровергнута — повтор дал бы дубль).

## 6. (d) Ретенция и уборка — существующие числа

- **Ретенция = `cfg.cooldown_seconds`** (единственный реальный ритм механизма: `DEFAULT_COOLDOWN_SECONDS = 6*3600`
  `:129`, читается из `initiative.meme_cooldown_seconds` `:118` с чат-override через `load_settings:528-538`). Почему не выдуманный TTL:
  (а) обязана быть ≥ межтипового интервала 1800 с, иначе первый же законный слот не наступит;
  (б) после собственного кулдауна механизм вправе сделать **новый** мем — значит артефакт старше этого срока
  уже не «текущий мем» и выдавать его за свежий нельзя (`§1.2`: не выдавать устаревшее за актуальное);
  (в) значение уже существует и настраивается владельцем — новых бюджетов/таймаутов не вводится.
  Никакого собственного счётчика попыток и «N retry» — попытки ограничены только ретенцией (не политика, а срок жизни данных).
- `deadline_at = now + retention` (существующая колонка), `payload.expires_at` — зеркало (как в `vision.pending_intent`).
- Уборка байтов: удаление файла в **каждом** терминальном переходе (`completed`/`failed`/`cancelled`), плюс
  самолечение при чтении: терминальная строка с ещё существующим файлом → файл удаляется.
- Уборка строк: терминальные строки удаляет **существующий** `TaskJobStore.prune`
  (`task_supervisor.py:571-584`; активные `queued/running` не трогает). Отдельный уборщик не заводится.
- Ограничение размера: один файл ≤ `IMAGE_MAX_BYTES` (9 MiB), одна активная строка на чат ⇒ верхняя граница
  занимаемого места — `9 MiB × число чатов`, фактически ~сотни КБ.

## 7. (e) Коды причин и события

Новые **коды причин** (не сущности; §1.2.4 требует отдельный код на каждый реальный случай):

| Код | Когда |
|---|---|
| `rights_revoked` | чат больше не является допустимой целью публикации (нет в реальном ростере кандидатов) |
| `deferred_publication_expired` | ретенция истекла, артефакт не доставлен |

Переиспользуются без изменений: `publication_conflict`, `publication_in_flight`, `disabled_by_setting`,
`initiative_disabled`, `source_material_gone`, `publish_blocked`, `delivery_unknown`, `publication_expired`
(смысл последнего — истечение **брони**, не артефакта: смешивать нельзя).

**Новых имён событий не вводится** — набор `MEME_EVENTS` (`:212-218`) закрыт:
цепочка доставки отложенного = `publication_requested` (бронь запрошена) → `publication_sent`
(`delivered=true`) | `publication_deferred_conflict` (слот занят) | `publication_cancelled`
(терминальный страж, включая `deferred_publication_expired`/`rights_revoked`) | `publication_failed`
(отправителя нет) | `delivery_unknown`. Принадлежность к отложенному пути видна в `detail` (`"deferred"`,
`claim:<id>`) и в `run_id` = исходный `jid`.

Дисциплина журнала: **одна строка `meme_initiative_attempt` на терминальный переход**; повторные проходы-ожидания
строк не пишут (иначе 12 строк/час на чат — фальшивая активность). Ожидание видно в `task_jobs` (`attempt`,
`reason_code`) и в `state["meme_chats"]` через `_note_state` (`:2518-2578`).

## 8. (f) Взаимодействие с ручным `/meme`

1. Ручной путь **не откладывает**: `manual=True` сохраняет текущее поведение (`:2091-2107` → код причины);
   `wait_for_sending`/приоритет — зона B3, контракт B1 его не меняет.
2. Ручной путь **обходит** гейт «есть отложенный»: пользователь явно попросил мем.
3. Отложенный артефакт получает бронь через тот же `acquire(manual=False)`; ручной запрос имеет приоритет
   (`MANUAL_PRIORITY_SECONDS=600`, `publication_coordination.py:78`), отложенный при этом просто остаётся `queued`.
4. Если в чате есть отложенный артефакт, авто-проход **не генерирует** новый (иначе снова второй платный вызов):
   возвращается результат ожидания (§5, п.8) без строки журнала.
5. Двойной отправки нет по построению: обе ветки проходят **одну** бронь `chat_publish_claim`.

## 9. (B2) Что обязательно перепроверяется во время поздней отправки

Перепроверка — **на реальном пути отправки**, а не только до генерации (иначе за 30+ минут состояние меняется):

- тумблер мема (`initiative.meme_enabled` через `_param`), мастер инициативы (`observer_enabled`), чат-гейт
  (`initiative.enabled`) — существующие три уровня; каждый со своим кодом;
- **права/допустимость чата** — реальный ростер (`_candidate_chat_ids`: PG `chat_profiles`, SQLite
  `get_smart_chat_ids`, `:365-387`), не синтетическая строка. Отсутствие в ростере ⇒ `rights_revoked`;
- **исходный материал** — `_default_source_check` по сохранённым `msg_ids`;
- **гейт публикации** — существующий шов (`publish_gate`), плюс координация брони;
- **жизненный цикл intent** — для мема **N/A**: мем не привязан к intent-записи, у него свой `run_id`
  и собственный снапшот. Это фиксируется как N/A с причиной (в отчёте/карте), а не имитируется:
  `_default_publish_gate` `:1598-1612` строит синтетический контекст `{"created_at": now, "status": "open"}`
  и потому **не может** служить доказательством проверки прав/intent (это и есть дефект B2). Отложенный путь
  обязан опираться на пункты выше; мок гейта доказательством не считается.
- **недоступность image-backend НЕ проверяется** на поздней отправке: байты уже есть, провайдер не вызывается.
  Блокировать оплаченный артефакт из-за здоровья провайдера — потеря данных, запрещённая §1.2.5.

## 10. (g) Миграция, откат, поверхность изменений

**Схема: дельта ноль.** `task_jobs` v14 уже мигрирована (`services/database.py:205-235`, PG — no-op);
новый `kind` — значение колонки. Новых таблиц/колонок/индексов нет. Каталог `var/meme_pending/` создаётся лениво.

**Откат = только код.** После revert строки `meme.pending_publish` остаются `queued` и инертны; файлы —
в git-ignored `var/meme_pending/` (ограничены сверху §6). Останавливать/чистить их штатной уборкой `task_jobs`
(`prune` не трогает активные) или вручную — на данные бота это не влияет, API и память не затронуты.

**Поверхность изменений (оценка):**

| Файл | Что |
|---|---|
| `services/meme_initiative.py` | новые константы (`DEFERRED_KIND`, `DEFERRED_COALESCE_PREFIX`, `SKIP_RIGHTS_REVOKED`, `SKIP_DEFERRED_EXPIRED`); `deferred_dir()`; `save_deferred_artifact()`; `load_deferred()`; `deliver_deferred()` (стражи §5 + бронь + sender + журнал); `deliver_deferred_all()`; в `consider_chat` — вызов доставки/анти-перегенерации и сохранение артефакта в ветке `:2091-2107` (только `not manual`); `_deferred_wait_result()` (результат без записи журнала) |
| `services/initiative_observer.py` | 2 ярлыка в `REASON_LABELS` (`rights_revoked`, `deferred_publication_expired`); `_meme_phase` — передать/донести параметры, если `deliver_deferred_all` вызывается из цикла (1–3 строки) |
| `services/publication_coordination.py` | не меняется (B3 — отдельная правка Builder) |
| `services/database.py` | не меняется |
| `tests/test_p0_meme_publication_hotfix.py` | +тесты §11 (инварианты), существующие 28 не ослабляются |

Порядок реализации: (1) сохранение артефакта в ветке отказа брони; (2) чтение/доставка в тике;
(3) стражи/коды/ретенция; (4) тесты. B1 не требует B3 и наоборот.

## 11. Инварианты (каждый — отдельный тест, падающий при потере артефакта)

1. **Не теряется.** Бронь не выдана при `generated=True` (авто) ⇒ `sender` не вызван, файл существует,
   строка `queued`, `payload.sha256` = sha256(content).
2. **Одна доставка.** Слот занят 3 прохода подряд → 0 вызовов sender; слот освободился → ровно 1 вызов;
   ещё 3 прохода → 0 вызовов; строка `completed`, файл удалён.
3. **Без второй генерации.** При активном артефакте `image_provider`/`llm` не вызываются ни разу.
4. **Рестарт.** Новый процесс/новый экземпляр сервиса видит `queued` + файл и доставляет (проверка с пересозданием
   зависимостей, не in-memory состояния).
5. **Квота.** `spent` не растёт, новой строки `meme_initiative_reservation` нет, `reserve` не вызывается.
6. **Права/модуль.** Отзыв чата из ростера и выключение тумблера между генерацией и отправкой ⇒ sender не вызван,
   свои коды `rights_revoked` / `disabled_by_setting`, файл удалён, строка терминальная.
7. **Честное истечение.** `now >= deadline_at` ⇒ ровно одна attempt-строка `deferred_publication_expired`,
   `delivery=not_sent`, файла нет; повторный проход строк не добавляет.
8. **Дубль невозможен.** Две параллельные попытки доставки (два вызова `deliver_deferred_all` без await-сериализации)
   ⇒ sender вызван один раз (`mark_running` CAS + бронь).
9. **delivery_unknown не переотправляется.** Исключение sender'а ⇒ одна попытка, `delivery_unknown`, файл удалён,
   последующие проходы не отправляют.
10. **Журнал не спамится.** N проходов ожидания ⇒ 0 новых строк `meme_initiative_attempt`.

## 12. Нужен ли вопрос владельцу — нет

- Спека §1.2.5 прямо предписывает «отложить/координировать через существующие ledger/durable-механизмы,
  не выбрасывать готовый результат». Это не развилка, а требование; отказ от B1 означал бы нарушение ТЗ.
- Ранее принятое arch §3.3/§3.5 («durable-хранилища готовой картинки нет») описывало **отсутствие** хранилища
  на тот момент, а не запрет его вводить; более позднее ТЗ владельца главнее.
- Бан-лист владельца не нарушен: новых планировщиков нет (существующий тик 300 с), второго RandomSource нет,
  новых сложных сущностей нет (существующая таблица + каталог), искусственных бюджетов/таймаутов нет
  (ретенция = существующий `cooldown_seconds`), поддельных статусов нет (неизвестная доставка остаётся
  `delivery_unknown`, истечение — честным кодом), хардкода по чатам/именам/фразам нет.
