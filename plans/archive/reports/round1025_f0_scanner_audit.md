# Scanner-аудит F0 `f0-config-bugfixes-round1025` (раунд 10.25)

> Режим: точечный diff-аудит. Диапазон: `pre-round1025..HEAD`
> (коммиты `c0cb8aa`, `7af2539`, `82722ad`, `2c3b7ed`, `5030fc6`, `d5750fc`,
> `d6ed9db`, `9a5f265`). @Reviewer уже дал Approved — здесь независимый поиск
> логических ошибок/регрессий. Код не менялся.
>
> **ОБНОВЛЕНО (повторный аудит после `5dd2b0d`/`83fc4c4`): Critical 0 / High 0 —
> к Шагу 7 (Merge) ДА.** H-1, M-1, M-3 и Low L-1/L-3/L-4/L-5/L-6 закрыты и
> подтверждены доказательно (см. §5). Ниже §1–§4 — исходный аудит (исторический
> снимок на `9a5f265`).

---

## 1. Сводка

| Severity | Кол-во |
|---|---|
| **Critical** | **0** |
| **High** | **1** |
| **Medium** | **3** |
| **Low** | **8** |
| Info | 6 |

Проверено исполнением: `pytest` по 4 файлам раунда — **32 passed**;
`node tests/js/round1025_save_state_test.js` и `round1025_cliche_ui_test.js` — **OK**.
Секретов в диффе нет (см. §3).

---

## 2. Находки

### [High] H-1. Карточное сохранение (`saveBlock`) ложно сообщает «Сохранено» при частичном провале и при полном in-flight-пропуске

- **Файл:** `web/app.js:3861-3908` (ветка `saveBlock`), совместно с
  `web/app.js:5165-5210` (`persistItems`).
- **Суть:** единственная проверка ошибки — `if (!res.saved.length && res.failed.length) throw …`.
  Два ложных успеха:
  1. **Частичный провал:** `persistItems` делает scope-split (chat-группа + global-группа).
     Если chat-группа прошла, а global-группа упала (503/422/сеть/409), то
     `res.saved` непуст, `res.failed` непуст → условие ложно (нет throw) → далее
     безусловный `this.toast('Сохранено: ' + b.title, 'ok')`.
  2. **Полный in-flight-пропуск:** если все ключи карточки уже летят другой операцией,
     `persistItems` возвращает `{saved:[], failed:[], skipped:[…]}` → условие ложно →
     снова «Сохранено», хотя не отправлено ничего.
- **Сценарий:** карточка блока с полями разных scope (per_chat=true и per_chat=false);
  пользователь жмёт «Сохранить»; сервер отвечает ошибкой на global-подзапрос
  (например, 503 PG) → тост «Сохранено», подсветка поля есть (`stickyFailedKeys`
  ставится внутри `persistItems`), но `loadConfig()` откатывает значение — UI
  утверждает успех при потере.
- **Регрессия:** до F0 сохранение карточки делало POST-ы подряд; падение второго
  POST всплывало в `catch` → тост ошибки. Теперь — тихий частичный успех.
- **Направление фикса:** считать успехом только `res.state === 'saved' && !res.failed.length && !res.skipped.length`;
  иначе тост по факту (warn/err, как в `saveModalEdits`). Одной строки достаточно.

### [Medium] M-1. `write_transaction` не откатывает транзакцию при `CancelledError` (расходится с docstring)

- **Файл:** `services/database.py:596-616` (ON) и `584-595` (OFF); `618-624`.
- **Суть:** ловится только `except Exception`, а `asyncio.CancelledError` — `BaseException`.
  При отмене корутины внутри `op` (или на `commit`) `self._lock` освобождается
  (через `async with`), но `rollback` **не** вызывается. Docstring (строки 580-583)
  обещает «rollback на любое исключение».
- **Последствие:** частично выполненные стейтменты остаются в незакоммиченной
  транзакции общего соединения; следующая операция `write_transaction` своим
  `commit()` зафиксирует «огрызки» (в тесте `test_non_lock_error_rolls_back`
  как раз показано, почему это опасно).
- **Сценарий:** отмена задачи во время `_embed_cache_store` (обрыв запроса /
  shutdown) → часть `INSERT embedding_cache` уйдёт в коммит следующего писателя.
- **Направление фикса:** откатывать в `except BaseException:` (и всегда `raise`),
  либо вынести rollback в `finally` вокруг `op`/`commit` под тем же `self._lock`.
- **Риск:** низкая частота, но класс «тихая неполная запись» — ровно то, против чего F0.5.

### [Medium] M-2. Глобальный per-key optimistic не подключён на клиенте — фича инертна через UI

- **Файл:** `web/app.js:5217-5220` (`persistItems` строит `{key, value}` — без
  `updated_at`), при том что `web/api/routes.py:474` уже отдаёт per-key
  `updated_at` в GET, а `ConfigItemUpdate.updated_at` (`routes.py:97-100`)
  и второй проход `_post_config_global` (`routes.py:971-993`) его читают.
- **Суть:** UI никогда не шлёт per-key токены → `tokens_used` всегда `False` →
  ветки `revalidated`/409 `conflicting` для глобальных ключей не срабатывают →
  глобальные сохранения остаются last-write-wins.
- **Не регрессия** (раньше токенов вообще не было; spec §2/D-409-3 аддитивна:
  «если клиент прислал `updated_at` для ключа»), но цель защиты от конкурентной
  перезаписи глобального ключа не достигнута end-to-end.
- **Направление:** прокинуть `item.updated_at` (из GET) в тело POST для global-группы
  и отдать 409-ветку в `persistItems` (там уже есть разбор `conflicting`).

### [Medium] M-3. Терло 409 глобального пути может вернуть сырое серверное значение секрета (R17-риск)

- **Файл:** `web/api/routes.py:995-1002` (`conflicting` c `server_value`),
  совместно с `937-940` (для `CATEGORY_KEYS` доступ проверяется через
  `can_view_key_value`, а не отклоняется).
- **Суть:** если API-клиент пришлёт per-key `updated_at` для `keys.*` (глобальный
  секрет, напр. `keys.image_api_key`), при несовпадении токена и значения в теле
  **409** вернётся `your_value`/`server_value`, где `server_value` — текущий
  сохранённый секрет. Ответы 4xx часто логируются/кэшируются прокси.
- **Достижимость:** только внешним API-клиентом (UI токенов не шлёт — см. M-2);
  через браузер недостижимо. Chat-путь безопасен: там namespace `keys` — это
  метаданные (`allow_global`), а не секреты (`services/chat_params.py:7`).
- **Направление:** не включать значения для ключей категории `keys` в `conflicting`
  (только `key`), либо маскировать `server_value` как `***`.

### [Low] L-1. `_patch_already_applied` игнорирует `meta`/`v` и не-словарные namespace

- `services/chat_params.py:167-178`. Патч без изменений в
  `overrides/gates/keys/perm_overrides` даёт `True` → ложный `revalidated`.
  Через текущие роуты недостижимо (`post_config` всегда кладёт непустой
  `overrides`), но прямой вызов `set_chat_params` с meta-only патчем — ложный успех.

### [Low] L-2. LRU `_chat_write_locks` — soft-cap не ограничивает рост, если все локи удерживаются

- `services/chat_params.py:118-140`. При `len ≥ 1024` и всех занятых локах
  вытеснить нечего → словарь растёт (1050, 1100…). Утечка памяти под штормом
  параллельных чатов; документирована как «soft-cap», но верхней границы нет.

### [Low] L-3. `notify` читает `_opNotified` до проверки, что это объект

- `web/app.js:5113-5120`: `if (this._opNotified[operationId])` вызывается раньше
  `if (!this._opNotified || typeof … )`. При отсутствии поля — `TypeError`.
  В проде поле есть; дефект — хрупкость.

### [Low] L-4. Очередь тостов молча вытесняет новый тост того же приоритета; дедуп по (text, kind) может скрыть повторный сбой

- `web/app.js:2153-2178`. При 3 видимых тостах новый с тем же приоритетом
  отбрасывается (slice после stable-sort). Повторная независимая ошибка с тем же
  текстом («Ошибка сохранения: …») в окне 4.2 c не показывается.

### [Low] L-5. `saveState` root никогда не возвращает `'saved'`

- `web/app.js:1659-1668` не выдаёт `'saved'`, а `stateLabel` (`app.js:8097-8102`)
  содержит ветку `saved: 'Сохранено'` — мёртвая ветка. Косметика.

### [Low] L-6. Дублирующееся присваивание `_REFRESH_ACTIVE_CAP = 5000`

- `services/database.py:48` и повтор ниже (после нового блока констант).
  Безвредно, но засоряет дифф.

### [Low] L-7. `tests/js/round1025_cliche_ui_test.js` — статический grep-тест, не проверяет логику

- Строки 17-42: проверяют наличие подстрок в `app.js`/`index.html`/`anticliche.py`.
  «Честные статусы» и `clichePerRun` фактически не исполняются — тест не поймает
  регрессию поведения (в отличие от `round1025_save_state_test.js`, который
  действительно гоняет методы).

### [Low] L-8. `set_many`: fallback без `conn.transaction` может дать частичную запись

- `services/config_cache.py:548-559`. Ветка для двойников без `transaction`
  выполняет UPSERT-ы по одному без общей транзакции; при падении посередине —
  частичная запись в PG, при этом in-memory не обновляется (расхождение).
  В проде `asyncpg` всегда имеет `transaction`, ветка — только для тестов.

### Info
- I-1. Анти-клише теперь делает до `ANTICLICHE_MAX_ROUNDS` (default 3) LLM-вызовов
  за прогон (bounded) — рост стоимости/бюджета vs прежний 1 вызов, но ограничен.
- I-2. Merge-семантика (`_normalize_stored` + `write_patterns(merged)`) не удаляет
  устаревшие паттерны и не тримит `merged` при понижении вместимости; `added_at`
  переставляется на «сейчас» у stored-паттернов без поля. Потребителей у `added_at`
  нет, влияния на UI/memory не найдено.
- I-3. `_chat_write_locks_guard` — module-level `asyncio.Lock()`; на Python 3.12
  (проверено) ленивая привязка к loop, проблемы «different loop» нет.
- I-4. `pg_advisory_xact_lock` не имеет таймаута: залипшая чужая транзакция
  заблокирует мутации профиля этого чата (штатное свойство advisory-lock).
- I-5. `saveConfigItem` в legacy-ветке (без `persistItems`) больше не ведёт
  `this.saving` — in-flight guard отсутствует; только тест-контексты.
- I-6. `loader.py` PRAGMA-паритет (`synchronous=NORMAL`) — вне рантайма, безопасно.

---

## 3. Что проверено и чисто

- **Конкурентность БД:** `test_write_transactions_serialized` подтверждает
  single-writer (max одновременных `op` = 1). Порядок «rollback перед повтором»,
  backoff 0.1/0.2/0.4, счётчик/`WARNING` при исчерпании (`_LOCK_RETRIES=3` → 4
  попытки) — консистентно.
- **Порядок отката и лок:** `rollback` вызывается после выхода из `async with`,
  но `aiosqlite` кладёт задание в FIFO-очередь одного worker-потока **до** первого
  `await`, поэтому откат гарантированно попадает в очередь раньше операций
  следующей корутины. Гонки «откат чужой транзакции» не подтвердил.
- **Отменяемость:** не покрыта (M-1).
- **`commit_if` (touch_graph_facts):** паритет с baseline (`touched==0` → без
  commit) подтверждён тестами ON/OFF.
- **`insert_graph_fact(commit=False)`:** обёртка сознательно не применяется —
  сохраняется атомарность пары fact+edge; `commit=True` — через `write_transaction`.
- **Реентерабельность:** `write_transaction` использует `self._lock`; обёрнутые
  методы (`insert_graph_fact`, `upsert_bot_reply`, `touch_graph_facts`,
  `_embed_cache_store`) вызываются вне `async with self._lock` → дедлока нет.
  `increment_and_get_count`/`slavic_photo_count_tick` под локом не вызывают
  обёрнутых методов.
- **Advisory-lock (PG):** берётся внутри транзакции (`pg_advisory_xact_lock`),
  снимается на commit/rollback; порядок «in-process lock → advisory» единообразен,
  кросс-дедлока по ключам не найдено. Ошибка advisory проглатывается в `debug` —
  остаётся in-process lock (заявленный fail-safe).
- **Idempotent short-circuit (chat):** 200 `revalidated=true` без NOTIFY/history
  при совпадающих значениях; реальный конфликт → 409 с `conflicting` только по
  изменённым ключам; scope-изоляция A≠B подтверждена тестом.
- **Секреты (R17/R18):** `git diff` не содержит password/ssh/api-key строк; новых
  секретов нет. Известный tracked-фрагмент в
  `plans/archive/security-rotation-finalize-round1016/spec.md` (R10.18-12) диффом
  **не** затронут, значение в отчёт не копировалось. Логи новых событий
  (`_note_lock_exhausted`, `_event`) — только op/attempts/chat_id/числа/model,
  без фраз/значений.
- **XSS/инъекции (клиент):** серверные значения/ошибки/имена ключей рендерятся
  через `{{ }}` (экранирование Vue); `v-html`/`innerHTML` с серверным текстом не
  добавлены; `toast()` приводит текст к строке. В `index.html` тост — interpolation.
- **Анти-клише:** расход ограничен (bounded rounds, per-run clamp `[1, capacity]`,
  дедуп против БД и внутри партии); «0 новых» = успех, кэш не затирается;
  per-chat trap не появился (воркер по-прежнему global-скоуп).
- **`set_many`:** одна транзакция + согласованное обновление in-memory; при ошибке
  PG in-memory не трогается (сначала запись, потом память).
- **Валидация пакета:** глобальный путь валидирует **все** ключи до записи;
  частично-валидный пакет не пишется (атомарность 200/409).

---

## 4. Вердикт

- **Critical = 0.** Данных-порчи/утечек секретов не найдено.
- **High = 1 (H-1)** — ложный успех сохранения карточки (UI-регрессия против
  мандата F0 «честный результат»). **Обязательно закрыть до архивации/Шага 7.**
- **Medium M-1** (откат при `CancelledError`) — рекомендую закрыть в этом же
  круге: правка тривиальная (`except BaseException`/`finally`), иначе docstring
  F0.5 остаётся неверным.
- **M-2/M-3** — не блокеры (аддитивные ветки/внешний API), но требуют решения
  @Architect: либо довести клиентские токены, либо явно зафиксировать «global
  optimistic — только для API-клиентов» и замаскировать секрет в `conflicting`.
- **Low** — не блокеры, заносятся в техдолг.

**Продолжать к Шагу 7 без правок: НЕТ** — до закрытия H-1 (и, желательно, M-1).
После закрытия H-1 достаточно точечной проверки + повторного прогона
`test_save_state_machine_round1025.py`/JS save-state теста.

---

## 5. Повторный аудит (после `5dd2b0d`, `83fc4c4`) — 20.09.2026, @Scanner

> Проверялось по коду и запуском тестов, не по отчёту Builder.

**Вердикт: Critical 0 / High 0 → можно к Шагу 7 (Merge) — ДА.**

### 5.1. Подтверждение закрытия

- **H-1 (был High) — ЗАКРЫТ.** `web/app.js:3916-3944` (`saveBlock`):
  `allOk = state==='saved' && !failed.length && !skipped.length`; при false —
  `warn`/`err` с числом сохранённых и перечнем неподтверждённых, `ok`-тоста нет.
  Ветка `persistResult === null` (только секреты / legacy) сохранена.
  **Доказательство «падает без фикса»:** отдельный worktree на pre-fix `9a5f265`
  (репозиторий не менялся) — изолированная проба `saveBlock` дала
  `ok-toast=true` и при частичном провале, и при полном in-flight-пропуске
  (`H1-PROBE-FAILS-ON-PREFIX`); полный JS-тест на pre-fix падает. Post-fix: JS
  тесты 10a/10b (реальный `saveBlock`, не заглушка) проходят.
- **M-1 (был Medium) — ЗАКРЫТ.** `services/database.py:593` (OFF) и `:606` (ON):
  `except BaseException`; `rollback` вызывается, retry — только для `locked`
  (`_is_locked`), `CancelledError`/`KeyboardInterrupt` пробрасываются дальше.
  `test_cancelled_error_rolls_back` (cancel во время `op` + проверка, что
  следующий писатель не «подхватывает» огрызки) на pre-fix **падает**,
  post-fix проходит.
- **M-3 (был Medium) — ЗАКРЫТ.** `web/api/routes.py:997-1004`: для
  `entry["category"] == CATEGORY_KEYS` в `conflicting` кладётся
  `server_value: null` + `secret: true`; сырое серверное значение не отдаётся
  (chat-путь и так безопасен — там `keys` = метаданные). Тест
  `test_secret_conflict_does_not_leak_server_value` на pre-fix падает,
  post-fix проверяет отсутствие значения в сериализованном `detail`.
- **Low, заявленные закрытыми — ЗАКРЫТЫ:**
  - **L-1** `_patch_already_applied`: флаг `compared`; meta-only/пустой патч
    больше не даёт `revalidated` (+тест `test_patch_already_applied_requires_value_keys`,
    падает на pre-fix).
  - **L-3** `notify`: нормализация `_opNotified` до чтения ключа (`app.js:5147-5153`).
  - **L-4** `toast`: цикл вытеснения удаляет **самый старый** тост наименьшего
    приоритета; новый виден (+обновлённое утверждение в JS-тесте, падает на pre-fix).
  - **L-5** `stateLabel`: мёртвая ветка `saved` удалена (`app.js:8130-8134`).
  - **L-6** дубль `_REFRESH_ACTIVE_CAP` удалён — осталось ровно одно определение
    (`services/database.py:49`).
- **M-2 (не блокер) — корректно отложен и зафиксирован.**
  `plans/reports/f0-round1025-report.md:123` — статус `⏳`, явно: «Не в этом круге
  (аддитивная ветка; UI шлёт без токенов). Требует прокидывания `item.updated_at`».
  Согласуется с ADR-1025-2 A2 (per-key optimistic — отложено) и spec §2/D-409-3
  («если клиент прислал `updated_at`»). Регрессии нет.

### 5.2. Фактические цифры и инварианты

- **pytest:** `.venv` Python 3.12 → **7946 passed, 1 warning in 106.27s** (заявленное подтверждено).
- **JS:** все **19/19** файлов `tests/js/*` → `exit 0` (включая оба `round1025_*`).
- **Валидность новых тестов (pre-fix `9a5f265`, отдельный worktree):**
  `3 failed, 25 passed` — падают ровно три новых Python-теста (M-1, M-3, L-1);
  JS save-state падает. Значит тесты не тавтологичны.
- **Δ DDL = 0, Δ каталога = 0:** среди файлов фикса нет `migrations/schema/param_catalog/settings.py`
  (проверено `git diff --name-only 9a5f265..HEAD`); `services/database.py` изменён
  только в логике `write_transaction`.
- **Промпты не тронуты; `smart_cache` не тронут** (в списке изменённых файлов их нет).
- **Секреты:** в диффе фикса `password/passwd/BEGIN …KEY/ssh/api_key=` — 0 совпадений;
  M-3-тест использует плейсхолдеры (`SECRET-OLD-VALUE`); значение нигде не логируется.
- **`git diff --check 9a5f265..HEAD`** → exit 0 (пробельных ошибок нет).
- **Новых регрессий от правок не найдено.** Замечаний/находок сверх закрытых — нет;
  остаточные Info из §2 (anticliche merge, advisory-таймаут и т.п.) в силе как Info.

**Итог §5: Critical 0 / High 0 / новых Medium 0 / новых Low 0 → к Шагу 7 (Merge) — ДА.**

