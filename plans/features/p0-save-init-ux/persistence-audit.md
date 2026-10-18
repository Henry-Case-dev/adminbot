# P0 save/init — сквозной аудит persistence SOUL-1 (lane PERSIST-AUDIT, read-only)

Дата аудита: 2026-10-18 (UTC 08:20–09:10). Источник задания:
`plans/features/p0-save-init-ux/source-p0-hotfix-2026-10-18.md` §2 (читан целиком).

Код не изменялся, коммитов нет. В прод — только чтение (SELECT, journalctl,
GET). SSH: 4 коротких сессии (все с успешной авторизацией, паузы между ними,
без ретраев после ошибок; одна из них прервалась по таймауту в середине
диагностики — соединение закрыто штатно). Ни одной записи в БД/файлы/сервис.

## 1. Фиксация кандидата (что именно аудировалось)

| Что | Значение |
|---|---|
| prod build | `APP_VERSION = 2.58.89`, git HEAD сервера `/var/www/admin_bot` = `d59fab94`, сервис `admin_bot` стартовал `2026-10-18 07:37:17 UTC` |
| Аудит-база (локально) | рабочая копия `C:\Code\Python\adminbot`; файлы персистенса **байт-в-байт** совпадают с задеплоенным `d59fab94` (`git diff HEAD d59fab94 -- <файлы>` пуст) |
| prod UI | отданный сервером `web/app.js` скачан и сверен: `sha256 2757a25d663dfe7ef6642d7e…`, совпадает с локальной ревизией на момент аудита |
| Аудируемые файлы (blob@d59fab94) | `web/api/speech.py 5d8f6ce0fd2a`, `services/style_policy.py 32217059afa1`, `services/chat_params.py 911c088a9f25`, `services/prompt_factory.py 253b2370d9fb`, `services/mca_humor_feedback.py a56eb94cb34f`, `services/config_cache.py 00ef5dcb735f`, `web/app.js 5e9cb25deb88`, `web/index.html 0656e0fc5896` |

> Замечание по времени: после моих замеров рабочая копия ушла вперёд (другие
> lane правят `web/app.js` — статусы инициативы). Ссылки на строки UI даны по
> **prod-ревизии** (её точные цитаты сняты в `ui_quotes_prod.json`).

## 2. Главный вывод (одной фразой)

Всё, что владелец пытался сохранить в разделе «Речь и характер» **в контексте
чата** (когда в MiniApp выбран активный чат), падало не из-за валидации
документа, не из-за конфликта версий, не из-за прав и не из-за БД. Причина —
**ошибка вызова внутреннего API записи**: `chat_params.set_chat_params()`
вызывается без PG-пула (`pg=`), функция это считает «PostgreSQL недоступен» и
бросает `ChatLorePgUnavailable` **до** любого обращения к хранилищу. Ошибка
глушится в `except Exception` и превращается в строку-причину
(`write_error` / `save_error`), а API отдаёт её как 409 (или 200 `ok:false`),
и UI показывает вводящее в заблуждение сообщение.

Глобальные (scope=global) сохранения того же экрана при этом исправны — это
подтверждено и логами прода, и строкой в `bot_settings`.

## 3. Таблица «симптом → точная причина → доказательство → минимальный фикс → потребители»

Порядок строк = порядок из §2 источника.

### 3.1. Speech Style Policy: «Документ не прошёл проверку или конфликт версии»

| Поле | Значение |
|---|---|
| Симптом | POST `/api/speech/style` → 409 → UI-тост «Документ не прошёл проверку или конфликт версии» |
| Класс по §2.2 | **транзакция/БД-слой вызван неверно** (нет пула) — НЕ невалидная структура, НЕ front/back-схема, НЕ revision/ETag, НЕ ложный optimistic-конфликт |
| Точная причина | `services/style_policy.py:2272 await set_root(int(chat_id), patch)` → `set_root` = лямбда `chat_params.set_chat_params(chat, patch)` без `pg` (строки 2236-2238) → `services/chat_params.py:422-424` `pool = getattr(pg, "pool", None) if pg is not None else None; if pool is None: raise _PgUnavailable("PostgreSQL недоступен (пул отсутствует)")` → исключение ловится `except Exception` (2289-2291) → `{"applied": False, "reason": "save_error"}` → `web/api/speech.py:2063-2065` `raise HTTPException(409, detail="save_error")` |
| Доказательство (прод) | `journalctl -u admin_bot`, `2026-10-18 08:02:21`: `WARNING services.style_policy: [style_policy] document save failed` + трейс `style_policy.py:2272 → chat_params.py:424 → ChatLorePgUnavailable` (полный трейс: `probe_prod_readonly3.json` → `steps.trace_style`) |
| Доказательство (локально) | `probe_persistence_audit.py` A2 (сервис-слой, тот же трейс) и B2 (HTTP 409 `{"detail":"save_error"}`) — `probe_persistence_audit.json` |
| Почему сообщение ложное | UI трактует **любой** 409 как «документ не прошёл проверку или конфликт версии» (`app.js:19270`), хотя реальная причина — инфраструктурная ошибка записи; detail сервер отдаёт строкой (`write_error`/`save_error`/`document_invalid`/…) |
| Минимальный фикс (предложение) | Вариант A (точечный): передать пул — `save_policy_document(..., pg=cache.pg)` из `post_style`. Вариант B (централизованный, закрывает все 10 вызовов сразу): в `chat_params.set_chat_params` при `pg is None` брать пул из process-глобала — `ChatParamsCache` уже создаётся с пулом (`bot.py:1332 set_chat_params_cache(ChatParamsCache(cache.pg))`), поэтому достаточно аксессора. ОБЯЗАТЕЛЬНО дополнительно: различать в API 4xx (валидация/конфликт) и 5xx (инфраструктура) |
| Потребители | POST `/api/speech/style` (chat scope); `save_policy_document` вызывается только отсюда (`web/api/speech.py:2059`) |

### 3.2. Expression Settings: «Не сохранено: write_error»

| Поле | Значение |
|---|---|
| Симптом | POST `/api/speech/expression` → 409 `{"detail":"write_error"}` → UI-тост «Не сохранено: write_error» |
| Класс по §2.2 | **транзакция/БД-слой вызван неверно** (тот же дефект, другой вызывающий) |
| Точная причина | `web/api/speech.py:2184 await chat_params.set_chat_params(int(chat_id), {"overrides": overrides})` без `pg` → `chat_params.py:424` raise → `except Exception` (2188-2190) → `{"applied": False, "reason": "write_error"}` → `post_expression` (2133-2135) → 409 `"write_error"` → `loreErrText` (`app.js:19909`) возвращает `e.message` = строка `write_error` |
| Доказательство (прод) | `journalctl`, `2026-10-18 08:09:49`: `WARNING web.api.speech: [speech] expression chat write failed` + трейс `web/api/speech.py:2184 → chat_params.py:424 → ChatLorePgUnavailable` (`probe_prod_readonly3.json` → `steps.trace_expr`) |
| Доказательство (локально) | `probe_persistence_audit.py` A3 + B1 (HTTP 409 `write_error`, точный UI-тост воспроизведён) |
| Минимальный фикс | передать `pg=cache.pg` в `_write_expression` (chat-ветка) и в `post_expression_reset_chat`; плюс человеческая причина ошибки вместо кода (`services/chat_lore_store.ChatLorePgUnavailable` ≠ «конфликт версии») |
| Потребители | POST `/api/speech/expression` (chat scope) |

### 3.3. Personality Core: запись/версии/повторное чтение

| Поле | Значение |
|---|---|
| Что сломано | **chat-scope** запись Core: POST `/api/speech/block/core.personality` (текст редакции) → 503 «запись недоступна»; POST `/api/speech/core/meta` (полная/компактная + вкл/выкл) → **200 с `ok:false`** (тихий провал); POST `/api/speech/block/core.personality/reset` (mode=chat) → необработанное исключение → **HTTP 500** |
| Класс по §2.2 | та же ошибка вызова БД-слоя (нет пула); плюс два UI/API-дефекта обработки: «искусственный 200» и «неперехваченное исключение» |
| Точная причина (503) | `services/prompt_factory.py:562 await set_root(chat_id, patch)` (без `pg`) в `_write_chat_speech_value` → raise → `web/api/speech.py:1807-1814` `except Exception` → 503 «запись недоступна» |
| Точная причина (тихий 200) | `web/api/speech.py:2020` (та же ошибка) → `_write_core_meta` возвращает `{"applied": False, "reason": "write_error"}` → `post_core_meta` (1959-1960) отвечает **200** `{"ok": false, "result": {...}}`; UI (`app.js:19010-19025`) не проверяет `ok` и показывает «Core включён/Действующая редакция: …» |
| Точная причина (500) | `services/prompt_factory.py:611-615 reset_chat_override` всегда зовёт `set_root(chat_id, patch, pg=pg)` с `pg=None` → raise; `post_block_reset` (1867-1876) **не оборачивает** вызов в try/except → исключение уходит из хендлера (в проде 500) — замерено на стенде. То же строение у `post_block_rollback` (1921-1924) при scope=chat: try/except отсутствует, а под ним тот же `write_speech_value(chat_id=...)`, который по A4 бросает `ChatLorePgUnavailable` → 500 (вывод по коду + трейс A4; отдельным HTTP-замером в матрице не покрыто) |
| Доказательство | локально: `probe_part_d.py` D1 (матрица из 9 chat-scope записей: 409/409/200-ok:false/503/200-ok:false/503/исключение/503/409) — `probe_part_d.json`; A4 — трейс `prompt_factory.py:562 → chat_params.py:424` |
| Что при этом РАБОТАЕТ | глобальный Core: POST `/api/speech/block/...` (scope=global) → `cache.set` → строка `character.core` в `bot_settings` (rev 1, `detail_level=full`, `origin=owner_edit`, `updated_at=2026-10-17T21:55:18Z`, `full_text` 2835 знаков = заводской текст, `compact_text` 0, история 0 записей) |
| Версии/откат (факт) | `history` для блока появляется только со **второй** правки (первая правка пустого поля не пишет предыдущую ревизию — `prompt_factory.py:468 if previous:`); в проде `history_len = 0`. Провенанс правок живёт отдельно: `character.prompt_history` (374 знака) — есть. Откат (`/rollback`) читает тот же `history` → в chat-scope он и вовсе недоступен (500) |
| Минимальный фикс | `pg=cache.pg` в 3 местах; `post_core_meta` → честный статус (409/503) вместо 200-с-`ok:false`; `post_block_reset(mode=chat)`/`post_block_rollback` → try/except с человеческой ошибкой |
| Потребители | POST `/api/speech/core/meta`, POST `/api/speech/block/{id}`, POST `/api/speech/block/{id}/reset (mode=chat)`, POST `/api/speech/block/{id}/rollback (scope=chat)` |

### 3.4. Остальные редакторы SOUL-1 и общие обработчики сохранения MiniApp

| Экран/вызов | HTTP (chat scope, статус-кво) | Что видит владелец | Причина | Потребитель кода |
|---|---|---|---|---|
| POST `/api/speech/humor/craft` | 503 | «Не сохранено: локальная запись недоступна» | `_write_document` (chat) → `speech.py:443` без `pg` → `post_humor_craft` 2330-2332 → 503 | ремесло юмора (вкл/выкл приёма) |
| POST `/api/speech/learning/humor` (pause/resume/reset) | 409 `write_error` | «Не сохранено: write_error» | `services/mca_humor_feedback.py:876/950` → `set_chat_params` без `pg` → `{"ok": False, "reason": "write_error"}` → `speech.py:2814-2816` 409 | «Опыт/Обучение юмора» |
| POST `/api/speech/style/reset-chat` | 200 `{ok:false, reason:"reset_error"}` | **«Переопределения для чата не было»** (неправда: сброс не выполнен) | `style_policy.py:2305` лямбда без `pg` → `reset_chat_policy` ловит → `reset_error`; UI ветка `app.js:19284-19285` | кнопка «Сбросить в inherited» (стиль) |
| POST `/api/speech/expression/reset-chat` | 503 | «Не сброшено: локальная запись недоступна» | `speech.py:2213` без `pg` → `except` 2215-2218 → 503 | кнопка «Сбросить в inherited» (выражение) |
| POST `/api/speech/examples*` (примеры, библиотека) | не затронут этим дефектом | — | другой носитель: SQLite-лор (`services/mca_sample_library.py:325` → `lore_runtime.get_lore_db()`, таблицы через `sqlite_master`); собственный `write_error` там возможен (618/668/703), но в прод-логах за 30 дней таких строк нет. Вживую не прогонялся (только чтение) |
| GET-разделы (проверены живьём: `/overview`, `/style`, `/expression`, `/core`, `/block/{id}`, `/config`) | 200 | — | только чтение | — |
| POST `/api/speech/try` (предпросмотр) | по коду записи не делает (0 LLM) | — | вживую не прогонялся | — |

**Общий механизм (доказано):** все 10 вызовов `chat_params.set_chat_params(...)`
**без `pg`** находятся ровно в четырёх модулях SOUL-1:
`web/api/speech.py` (443, 2020, 2184, 2213), `services/style_policy.py` (2236-2238,
2305), `services/prompt_factory.py` (518-519, 601-602), `services/mca_humor_feedback.py`
(876, 950). Все остальные потребители того же API в проекте **передают пул** и
дефекта не имеют: `web/api/routes.py:706` и `:1013` (`pg=cache.pg`),
`web/api/access.py:443`, `web/api/oversight.py:363`,
`web/api/cover_styles.py:673` (`pg=pg`), `services/feature_gates.py:185`,
`handlers/chat_lifecycle.py:147`, `services/chat_settings_seed.py:192`,
CLI-скрипты `scripts/*`.

**Проверка «фикс достаточен»:** локально прогнан тот же HTTP-стек (реальный
FastAPI + реальная TMA-авторизация + PG-двойник уровня asyncpg), с
единственной подменой «прокинуть `pg` при `pg is None`» в
`chat_params.set_chat_params` — **все 9 chat-scope записей экрана дают 200
`ok:true`**, а значения читаются обратно из хранилища (см. §3.5). Файлы:
`probe_part_d.py` → `D2_chat_scope_with_minimal_fix`, `D3_read_after_write_with_fix`.

### 3.5. Read-after-write по цепочке (что проверено фактически)

| Слой | Как проверено | Результат |
|---|---|---|
| UI → payload | сверены точные тела POST из `app.js` (сняты из prod-копии) | `style`: `{document, scope, reason}`; `expression`: `{values:{wit,sharpness,profanity,verbosity,note}, scope}`; `core/meta`: `{detail_level|enabled, scope}` — совпадают с pydantic-моделями `StyleWrite/ExpressionWrite/CoreMeta` (`web/api/speech.py`) → **несовпадения front/back схем нет** |
| API → валидация | `validate_document` (`style_policy.py:598`) не бросает и не режет нормальный документ; `_normalize_expression` закрывает значения | валидация **не является** причиной отказа |
| concurrency/revision | `expected_updated_at` UI в этих POST **не отправляет**; 409 возникает не из optimistic-протокола (в трейсах его нет) | ложного optimistic-конфликта нет; «конфликт версии» в тексте тоста — вымысел UI |
| PostgreSQL | прод-строки (read-only): `character.core` (rev 1), `style.policy` (rev 6), `character.prompt_history`; **`character.expression` — 0 строк**; `chat_profiles` — 0 строк с речевыми ключами | global-записи пишутся; chat-записи речевого экрана в проде отсутствуют вовсе |
| reread из хранилища | live GET (read-only) `GET /api/speech/expression` (global) → `present:false, inheritance:factory_default`; `GET /api/speech/style` → `global_present:true, global_revision:6, rules:0, soft:0`; `GET /api/speech/core` → `global_present:true, document.revision:1, detail_level:full, updated_at 2026-10-17T21:55:18Z` | чтение честно отражает хранилище |
| effective | `editions.full.source=global, chars=2835, differs_from_factory=false`; `selection.level=full, reason=owner_setting` | совпадает с содержимым документа |
| runtime LLM payload | путь существует и наблюдаем: `/api/speech/inspector` (preview-манифест, `speech.py:1308-1420`, слой `expression` — 1395) и `services/prompt_composer.py` (слои core/identity/expression/style_policy) | при `present:false` слой выражения пуст (`rendered_text` = 0 знаков) — то есть несохранённые настройки действительно не влияют; чтобы доказать влияние после сохранения, нужен прогон манифеста (см. §6) |

## 4. Вердикт: дефект общий или частный

- **Не общепроектный.** Общий инфраструктурный слой (`ConfigCache.set`,
  `chat_params.set_chat_params`) исправен; остальные разделы MiniApp (конфиг,
  доступы, oversight, стили обложек, гейты) передают пул и этим дефектом не
  затронуты.
- **Общий внутри SOUL-1.** Один корень (`pg` не передаётся) поражает **весь
  раздел «Речь и характер» в chat-контексте**: характер (текст + редакция +
  вкл/выкл), стиль письма, выражение, ремесло юмора, пауза обучения, обе кнопки
  «сбросить в inherited», сброс переопределения чата и откат. То есть
  «отдельная заплатка на каждый экран» — ровно то, чего просил не делать
  источник (§2.1): фикс централизованный (прокидывание пула + честные статусы).
- **Причина, по которой это не поймали:** существующие контрактные тесты
  подменяют сам виновный вызов — `tests/test_soul1_w6_speech_ui.py:88-89`
  делает `monkeypatch.setattr("services.chat_params.set_chat_params", set_root)`
  с in-memory реализацией, поэтому API-путь с реальной сигнатурой (`pg`
  обязателен) ни в одном тесте не исполнялся.

### Smoke по разделам админки (кто ещё пользуется тем же путём)

| Раздел | Использует `set_chat_params`? | Пул передан | Статус |
|---|---|---|---|
| Речь и характер (все подразделы) | да (10 вызовов) | **нет** | дефект |
| Конфиг/чаты (`/api/config` chat) | да | да (`routes.py:706,1013`) | ок |
| Доступы/гранты (`/api/access/*`) | да | да | ок |
| Гейты/бюджет (`/api/gates`, `feature_gates`) | да | да | ок |
| Oversight (ключи чата) | да | да | ок |
| Стили обложек (`/api/cover_styles`) | да | да | ок |
| Жизненный цикл чата/сид настроек | да (`pg=`) | да | ок |
| Примеры юмора (SQLite-лор) | нет | н/п | ок |

## 5. Что сейчас лежит в проде (read-only факты, важные для приёмки)

1. `character.expression` — **строки нет** (`expr_rows = 0`): настройки
   выражения никогда не сохранялись успешно (ни глобально, ни в чате).
2. `style.policy` — rev 6, но **документ пустой**: `rules: []`,
   `soft_instructions: []`, `reason: "agent-check-w2 restore"`; в истории
   ревизии 1-5 (все с пустыми правилами, `rules_sha256_12 = 4f53cda18c2b`).
   То есть действующих правил стиля нет.
3. `character.core` — rev 1, `detail_level=full`, `origin=owner_edit`,
   `full_text` = заводской текст (2835 знаков), `compact_text` пуст,
   история пуста. Глобальный Core записан корректно.
4. `chat_profiles` — **ни одной строки** с речевыми ключами
   (`style.policy`/`character.expression`/`character.core`) ни в одном чате.
5. Живой UI-факт: `GET /api/speech/overview` с `X-Chat-Id` возвращает
   `scope: "chat"` → `app.js:18885` автоматически ставит
   `speechScopeChoice = 'chat'` (селектор «глобально / этот чат» рядом с
   кнопкой «Сохранить», `index.html:7853`). Активный чат MiniApp помнит в
   `localStorage['adminbot.active_chat_id']` (`app.js:6314`) и подставляет в
   заголовок `X-Chat-Id` (`app.js:6109-6110`). Итог: у владельца с выбранным
   чатом **любое** сохранение уходило в chat-scope, то есть в гарантированный
   отказ.

> Побочно зафиксировано (incidental, не гейт): глобальные речевые записи в
> проде делались и с `updated_by = 5885953495`, и с `reason = "agent-check-w2
> restore"` (агентские live-проверки прошлых волн). Поэтому «пустой стиль» в
> проде — не обязательно следствие клика владельца; при разборе жалобы это
> стоит учитывать.

## 6. Предложение по приёмке read-after-write (как доказывать сохранение)

Приёмка должна фиксировать **постоянное** хранилище, а не ответ API. Минимум
на каждый тип настроек (style/expression/core-meta/core-text + scope global и
chat):

1. `POST` (UI-путь, реальный initData) → ожидаем 200 **и** `applied/ok = true`
   в теле; любой 409 → диагноз обязан быть человеческим и указывать класс
   (валидация/конфликт/инфраструктура).
2. **Reread из БД напрямую**: `SELECT key, jsonb_typeof(value), value->>'revision',
   updated_at FROM bot_settings WHERE key = '<ключ>'` (global) и
   `SELECT chat_params->'overrides'->'<ключ>' FROM chat_profiles WHERE chat_id=$1`
   (chat). Значение и ревизия обязаны совпасть с отправленным.
3. **Reread через API** после `reloadSpeech()`/перезагрузки MiniApp:
   `present/global_present/chat_present`, `revision`, `inheritance` — значение
   то же, наследование осмысленное.
4. **Effective + runtime payload**: `GET /api/speech/block/{id}` → `effective.source`,
   `revision`, `differs_from_factory`; `GET /api/speech/inspector` (или
   `services/prompt_composer` на стенде) → в манифесте должен появиться реальный
   слой (`expression`/`style_policy`/core) с ненулевым `chars` и тем же sha/ревизией.
5. **Изоляция**: значение в другом чате не изменилось; `chat_overrides` соседних
   чатов нетронуты.
6. **Отрицательные сценарии** (обязательны): невалидный документ → 4xx с
   понятной причиной и сохранённым текстом; чужая ревизия (`expected_updated_at`)
   → конфликт без потери текста; недоступная БД (пул снят) → явная ошибка, **не**
   200 и **не** тихий in-memory успех.
7. **Hot без рестарта**: после записи runtime читает новое значение (шаг 4) без
   перезапуска бота.

Минимальные тесты, которые поймали бы именно этот дефект (без новых ритуалов):
сервис-тест на реальной сигнатуре `chat_params.set_chat_params` (без monkeypatch
этой функции) для 4 chat-scope путей + проверка, что «нет пула» → не 409-«конфликт»,
а честная 5xx с человеческой причиной.

## 7. Опровергнутые версии (что НЕ является причиной)

| Версия | Вердикт | Почему |
|---|---|---|
| Невалидная структура документа | нет | `validate_document` не бросает и не режет нормальный документ; в трейсах его нет; `document_invalid` достижим только при нечитаемом документе |
| Несовпадение front/back схем | нет | тела POST из prod `app.js` совпадают с `StyleWrite/ExpressionWrite/CoreMeta` |
| revision/ETag, ложный optimistic-конфликт | нет | UI не отправляет `expected_updated_at` в этих запросах; в трейсах нет `ChatParamsConflict` |
| Права/RBAC | нет | все запросы проходят `_can_edit_speech` (глобальный админ), 403 не наблюдается |
| scope как таковой | нет (косвенно да) | scope обрабатывается корректно; проблема в том, что chat-ветка вызывает запись без пула |
| Сериализация json | нет | `json.dumps` не падает; в прод-PG значения лежат как `jsonb object` |
| Кеш/effective расходится с хранилищем | **частично да, отдельный риск** | `ConfigCache.set` обновляет in-memory **до** записи в PG (`config_cache.py:686-702`): при ошибке PG-записи значение уже изменено в кэше → reread-эффектив показывает «сохранённое», которого нет в БД; при полностью недоступной PG функция возвращает успех без персиста (`config_cache.py:689-691`). Локально воспроизведено (`probe_persistence_audit.json` → B4, B5): B4 — 200 без персиста; B5 — 409 `write_error`, при этом `GET /api/speech/expression` уже отдаёт новое значение |
| «jsonb приходит строкой и документы не читаются после рестарта» | **опровергнуто** | прод-факт: после рестарта `GET /api/speech/core` возвращает `document.revision=1, detail_level=full` → в кэше словарь. Причина: `services/pg_db.py:642-647` регистрирует json/jsonb-кодеки (`init=_init_connection`) на каждом соединении пула. Моя локальная симуляция «строка вместо dict» (C1) — **не прод-сценарий**; остаётся лишь латентный риск: `_expression_document`/`_core_payload` проверяют `isinstance(doc, dict)` и не парсят строку (в отличие от `style_policy._as_document`), поэтому путь без кодека (прямой asyncpg-коннект) сломал бы именно выражение и Core |

## 8. Остаточные неопределённости / риски

1. **Кто именно был инициатором прод-записей** речи (owner vs агентские live-проверки) — по логам видно `updated_by` владельца и `reason: agent-check-w2 restore`; это не влияет на вывод о дефекте, но влияет на трактовку текущего состояния стиля (пустой документ).
2. **Что владелец видел «в моменте»** — точные скриншоты в репозиторий не переносились; сопоставление сделано по времени (два трейса прода 08:02:21 и 08:09:49 совпадают с описанными симптомами) и по точному совпадению строк UI.
3. **Примеры (библиотека SOUL-07)** живут в SQLite-лоре — у них свой источник `write_error` (`services/mca_sample_library.py:618/668/703`). В прод-логах за 30 дней таких ошибок нет, но если владелец видел `write_error` на экране примеров — это другой механизм (проверять отдельно).
4. **Побочные дефекты обработки** (ложный успех Core-меты, ложное «переопределения не было», 500 на reset/rollback, 409 вместо 5xx) — это самостоятельные пункты §2.2/§3.4 («нельзя ставить искусственный 200», «человеческая причина ошибки»), их стоит закрывать вместе с основной причиной.
5. **Тихая потеря правил стиля.** `validate_document` отбрасывает правило с неизвестным `kind`/не-объект, добавляет диагностику `rule_kind_unknown:<kind>` и **всё равно** отвечает `applied: true` (локально: A2b — `{"applied": true, "rules": 0, "soft_instructions": 1, "issues": ["rule_kind_unknown:quotes"]}`). UI показывает «Правила сохранены». При штатном потоке kinds приходят с сервера, поэтому это не причина жалобы владельца, но при устаревшем UI/пресете правило исчезнет без внятного сообщения (связанное, неблокирующее).
6. **Порядок побочных эффектов при неудачной chat-записи.** `prompt_factory._write_chat_speech_value` пишет провенанс (`_mark_provenance`, строки 552-555) **до** записи значения (562): при падении записи журнал «помнит» ревизию, которой в слое нет (для global-пути это осознанное решение — 473-477; для chat-пути последствие не проверялось). Не влияет на диагноз, но влияет на честность истории (низкая важность).
7. Файл `plans/owner_questions.md` и human gate не требуются: все выявленные причины решаются в коде.

## 9. Артефакты аудита (все — воспроизводимые)

Каталог: `plans/features/p0-save-init-ux/evidence/audit-2026-10-18/`

| Файл | Что доказывает |
|---|---|
| `probe_persistence_audit.py` / `.json` | A1-A6 (слои сервисов: точные трейсы `chat_params.py:424`), B1-B2 (реальные HTTP 409 `write_error`/`save_error` + UI-тосты), B3 (smoke остальных POST), B4-B5 (тихий успех без перса и расхождение кэш↔БД), C1 (симуляция jsonb-строки — для полноты, **не** прод-сценарий) |
| `probe_part_d.py` / `.json` | D1 — матрица 9 chat-scope записей (409/409/200-ok:false/503/200-ok:false/503/исключение/503/409); D2 — те же 9 записей с минимальным фиксом (все 200 `ok:true`); D3 — read-after-write из хранилища |
| `probe_prod_readonly.py` / `.json` | meta прода (HEAD `d59fab94`, `APP_VERSION 2.58.89`, старт сервиса), первичный срез логов |
| `probe_prod_readonly2.py` / `.json` | лог-доказательства: `[style_policy] document save failed` (08:02:21), `[speech] expression chat write failed` (08:09:49), успешные global-записи (`document saved | scope=global | revision=1..6`), счётчик сбоев за 30 дней = 2 |
| `probe_prod_readonly3.py` / `.json` | **полные трейсбеки** обоих сбоев; systemd-юнит; строки `bot_settings`/`chat_profiles` (read-only SELECT) |
| `probe_live_readonly.py` / `.json`, `probe_live_chat_scope.py` / `.json`, `probe_live_readonly3.py` / `.json` | живые read-only GET: состояние выражения/стиля/Core (global и по 3 чатам владельца), `scope=chat` в overview, `/api/config` по чату |
| `extract_ui_quotes.py` / `ui_quotes_prod.json` | точные цитаты UI из **prod** `app.js` (sha256 `2757a25d…`) с номерами строк |
