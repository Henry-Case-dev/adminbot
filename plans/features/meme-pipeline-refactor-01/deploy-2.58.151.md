# MEME-PIPELINE-REFactor-01: выкладка 2.58.151

Дата: 03.11.2026, 03:54–03:59 UTC, VPS `192.255.209.205`. Роль: DevOps.
Итог: **успешно, прод на 2.58.151 @ `bd0f38ed`**. Ветка: `release/2.58.151`.

## 1. Что выложено

| Параметр | Значение |
|---|---|
| `DEPLOY_SOURCE` | commit `bd0f38ed1bb08e9787c67c516b1ce76f1da42cb7` (ветка `release/2.58.151`; на сервере `FETCH_HEAD == HEAD == bd0f38ed`, ветка совпала) |
| Родитель | `06cfd722` (map-биндинг P4 поверх `092734a6`), т.е. ровно проревьюенный кандидат `092734a6` + bump |
| База линии | merge-base с прод-линией `5fc2ded5` (прод 2.58.149/2.58.150 построены на нём) |
| Bump | `bd0f38ed`: 2.58.144 → 2.58.151, **31 файл / 32 вхождения**, тот же bump-набор, что в 2.58.149/2.58.150, `LEFTOVER=0` в продуктовых/тестовых путях |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — деплой из иммутабельного коммита; рабочий каталог владельца (`master`, грязный) не использовался |
| Write scope на проде | `.git` (ветки `release/2.58.150`→`release/2.58.151`, HEAD), `/tmp/predeploy-258151.db`, `/tmp/rel258151_*`, `/tmp/j2.txt`; файлы приложения — только из коммита |
| Дельта кода | 415 изменённых путей, **0 удалённых файлов** (переключение NON-FF: ветка прод-линии собрана черри-пиками, поэтому ancestry отличается; старый ref сохранён) |

Версия в дереве кандидата была `2.58.144`: `evol/impl` форкнут от `5fc2ded5` (база 2.58.144), bump 2.58.149/2.58.150 жил только на релизных ветках. Поэтому bump сделан 2.58.144 → 2.58.151 по тому же набору файлов.

### 1.1. Состав релизного дерева (существенное)

`evol/impl` с базы `5fc2ded5` содержит 15 merge-коммитов, из которых 9 — мем-стек (P0/P1/P2/P3/P4/P6/P7/P8/P9), а **4 линии — не мемные**:

| Линия | Коммит | Ревью ветки | Строки карты `plans/features/evol/requirements-map.json` |
|---|---|---|---|
| EVOL-COG-MAP S1/S2/S3 | `25725265`, `1eaa6c24`, `a9f326f8` | S1 Approved, S3 Approved (Re-review 3), S2 — после Needs Fixes исправлен и слит | **0 VERIFIED / 54 PENDING** (биндинг не сделан) |
| EVOL-SRC-READER | `49570c9e` | Approved (B1–B3) | 50 V / 11 P |
| EVOL-UI-FULLDOD (W15 composition) | `4af1f197` | Approved (Re-review 2) | 24 VERIFIED |
| FINAL v8 AC-P0 (AntiCliche) | `49d1fcde` | отчёт ревью есть | EVOL-FACTCHECK-CRITICAL 24 VERIFIED |
| P0 мем «только изображение» | `8f01f7b5` | Approved (2.58.150) | уже в проде |

Иными словами, этот релиз = снимок интеграционной ветки, а не «только мем». Ветки прошли независимое ревью, но строки COG-MAP в карте `evol` остаются PENDING (биндинг отстал). Возврата к 2.58.150-практике «только дельта» здесь нет: мем-P4 правит те же `web/index.html`, `web/app.js`, `web/static/app.css`, что и W15/COG-MAP, механический cherry-pick мем-стека на базу без этих линий дал бы конфликты в UI-файлах и неэквивалентное дерево. Решение о составе — за Orchestrator/PM (§11.1).

## 2. Тесты кандидата (worktree `release/2.58.151`)

| Проверка | Результат |
|---|---|
| `compileall` (`bot.py`, `config`, `services`, `web`, `handlers`, `tests`) | **rc=0** |
| Node (4 bump-пина + routing + asap_ui02_delta + asap_ui02_status_ribbons + evol_w9 + evol_w7_nav + f9 + app_methods_dup_keys_guard + meme_ui_fields + 2 cog-map) | **14/14 OK** |
| `pytest` по 24 bump-пин тестам | **858 passed, 10 failed** — все 10 разобраны как устаревшие пин-контракты, не дефекты (ниже) |
| Мем/инициативные наборы (`test_meme_pipeline_stages`, `_api`, `_command_autodelete`, `_joke_speech_layers`, `_init_diagnostics`, `test_initiative_coordination`, `test_initiative_speech_layers_chat_overrides`, `test_p0_meme_image_only`) | **149 passed** |

Разбор 10 красных (все — предмет Builder, продукт не затронут):

- **7× счётчик каталога параметров 572 vs 570** (`test_summary_fact_package`, `test_summary_logging_runid`, `test_summary_publish_integration_round1026`, `test_summary_test_run`, `test_tool_coordinator_round1026::test_version_and_catalog`, `test_decision_making_round1026::test_counts_sanctioned`, `test_telegram_reactions_round1026::test_counts_unchanged`) — P2 добавил два РЕДАКТИРУЕМЫХ промпта `prompts.meme_joke` / `prompts.meme_image` в `param_catalog` (ровно +2 категоризированных). Пересанкционирование чисел не входило в write scope P2.
- **2× запрет изменений `web/*` vs baseline** (`test_tool_coordinator_round1026::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026::test_forbidden_paths_out_of_diff_vs_baseline`) — P4 по определению правит админ-UI (`web/index.html`, `web/app.js`).
- **1× `_onResize` → `_auroraResize()` в пределах 400 символов** (`test_webapp_hotfix10_round1025`) — фактический зазор 459 символов, но вызов на месте (`web/app.js:8753`, `_onResize` на `:8744`); ассерт хрупкий по длине, поведение сохранено.

Ни один из 10 не относится к мем-поведению; мем-наборы зелёные. Пересанкционирование — за Builder (§11.2).

## 3. Ход выкладки

- **recon (одно короткое подключение, read-only, ~03:52Z)**: `HEAD=345a2ed7`, ветка `release/2.58.150`, tracked-dirty=0 (только untracked `.cache/`), `active/running`, `MainPID=1360587`, **`NRestarts=0`**, `/healthz` 200 `2.58.150`, `user_version=40`, 123 таблицы, `chat_publish_claim` отсутствует, media 66, диск 65 ГБ свободно.
- **основной прогон**: снимок БД через sqlite backup API → `/tmp/predeploy-258151.db` (**1 679 773 696 Б**, `user_version=40`, 123 таблицы, **`quick_check=ok`**); `git fetch origin release/2.58.151` → `FETCH_HEAD=bd0f38ed`, SHA совпал с локальным; `git checkout -B release/2.58.151 bd0f38ed`; `systemctl restart admin_bot` в **03:54:08Z**.
- Две попытки были **остановлены до любых изменений**: (1) защита «ff-only» — ancestry отличается (прод-линия собрана черри-пиками), (2) ошибка переменной в самом скрипте. Прод не менялся до 03:54:08Z.
- Замена проверки «ff» на проверку **включения поведения**: перед переключением подтверждено, что P0-фикс 2.58.150 присутствует в новом дереве (`_image_delivered_this_turn`, `image delivered`, `_mark_turn_text_replied`, `tests/test_p0_meme_image_only.py`); по диффу прод→кандидат **ни одной строки** этих маркеров не удалено.

## 4. Проверка после выкладки

| Проверка | Результат |
|---|---|
| `/healthz` (127.0.0.1:8000) | **200** `{"status":"ok","version":"2.58.151"}`, первая же проба через **25 с** после рестарта |
| `/healthz` публично (`https://admin-bot.duckdns.org`) | **200** `{"status":"ok","version":"2.58.151"}` |
| `/api/health`, `/web/` | **200 / 200** |
| Сервис | `active/running`, `ExecMainStatus=0`, **`NRestarts=0`** (проверки 03:54, 03:55, 03:56, 03:59 UTC) |
| Процессы | 1: `MainPID /var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py`, `pgrep -c` по `python* bot.py` = 1 |
| Git на сервере | `bd0f38ed`, ветка `release/2.58.151`, tracked-dirty=0 |
| Media | **66 → 66** (без изменений) |

### 4.1. Отдаваемые ассеты — байт-в-байт с кандидатом

| Ресурс | Результат |
|---|---|
| `/web/app.js` | 1 739 764 Б, sha256 `01768e05…` — **идентичен файлу кандидата** (подстановок нет) |
| `/static/app.css` | 428 228 Б, sha256 `53f222ff…`; файл кандидата с подстановкой `__APP_VERSION__→2.58.151` (2 места) даёт ровно `53f222ff…` и 428 228 Б — **только версия** |
| `/web/` HTML | 1 161 616 Б, 16 подстановок версии; нормализованный (плейсхолдер) sha256 `0f27bbc8…` — **совпал** с локальным `web/index.html` |

### 4.2. Маркеры в выложенном дереве

| Маркер | Значение на проде |
|---|---|
| `chat_publish_claim` (владение таблицей) | `services/publication_coordination.py` (2), `services/database.py` (4) |
| Проводка координации | `publication_coordination` импортируется 7 модулями: `handlers/meme_command.py`, `services/{database,initiative_diagnostics,initiative_observer,meme_initiative,memory_maintenance,nostalgia_worker}.py` (все точки `handle_initiative` + приоритет `/meme`) |
| `PUBLICATION_KINDS` | `('initiative_reply', 'meme_initiative')` — мем получает собственный kind |
| Ключ межтипового интервала | `publication_coordination.KEY_CROSS_TYPE_INTERVAL = initiative.cross_type_publication_interval_seconds`, функции `resolve_cross_type_interval`, `resolve_gap_seconds` |
| Промпты в каноне | `prompts.meme_joke` / `prompts.meme_image` — 5 вхождений в `services/param_catalog.py` + `services/prompt_registry.py`; на старте `[config_cache] set` и `[prompt_release] activation` для `initiative.meme.{joke,image,summary}` |
| Диагностика | маршрут `GET /api/initiative/mechanism-diagnostics` зарегистрирован: `web/api/mechanism_diagnostics.py:34` (`@mechanism_diagnostics_router.get(...)`), реэкспорт в `web/api/__init__.py` |
| Схема | `services/database.py:1773` `_SCHEMA_VERSION_PUBLISH_CLAIM = 41` |
| Аналитика этапов | `STAGES`=5, `J = max(0, L - T)`=4, `reason_code`=13, `limit_source`=5, `analytics_snapshot`=1, `meme_initiative_attempt`=1, `MEME_JOKE_PROMPT`=4, `MEME_IMAGE_PROMPT`=2 |
| `/meme` | `handlers/meme_command.py` (RBAC + удаление принятого сообщения) |

## 5. Миграция v41 — аддитивная, рестарт идемпотентен

| Проверка | Было (снимок) | Стало (прод) |
|---|---|---|
| `user_version` | **40** | **41** |
| Таблиц | 123 | **124** (`+ chat_publish_claim`, удалённых **0**) |
| `chat_publish_claim` | нет | есть, `PK chat_id` |
| Строк в таблице | — | **0** (броней нет) |
| `quick_check` | ok | **ok** |
| `schema_migrations` | 29 строк | **30** (+ v41, checksum `3190b3fb…`), дублей нет |

Колонки `chat_publish_claim` (ровно как в DDL модуля-владельца):
`chat_id INTEGER PK, claim_id TEXT, holder_kind TEXT, holder_ref TEXT, state TEXT, claimed_at INTEGER, expires_at INTEGER, last_publish_ts INTEGER, last_publish_kind TEXT, last_publish_ref TEXT, manual_priority_until INTEGER, updated_at INTEGER`.

**Аддитивность (доказательство без потери данных):** сравнение снимка и живой БД по **119 невиртуальным таблицам** — `6 604 427 → 6 604 535` строк (+108), **ни одной таблицы с отрицательной дельтой**. Дельты только от живого трафика: `mca_events +29`, `message_revisions +11`, `smart_messages +11` (+ FTS-тени), `message_source_records +10`, `mca_media_assets/_analyses +2`, `task_jobs +2`, `schema_migrations +1`. 4 virtual-таблицы (`smart_archive`, `graph_facts_vec*`) исключены из подсчёта: без расширения `vec0` счёт недоступен.

**Рестарт — no-op для схемы:** второй рестарт в 03:56:31Z → `user_version=41`, 124 таблицы, `schema_migrations` по-прежнему 30 строк, `migration v41` в журнале второго старта — **0 вхождений**; `/healthz` 200 через 6 с, `NRestarts=0`.

## 6. Журнал

Окно 03:54:08Z → второй рестарт: **246 строк** — `Traceback` **0**, `ERROR`/`CRITICAL` **0**, `database is locked` **0**, `WARNING` **1** (предсуществующий `embedding generation not serviceable | index=smart_archive | status=superseded` — тот же, что в 2.58.149/2.58.150).
Окно после второго рестарта: **358 строк** — `Traceback` 0, `ERROR`/`CRITICAL` 0, `publication` 0, `meme` 0, повтор `migration v41` 0, `WARNING` 1 (тот же).

В окне миграции единственные записи про мемы — штатный bootstrap: `[config_cache] set | key=prompts.meme_image|prompts.meme_joke` и `[prompt_release] activation` для трёх мем-блоков; и одна строка схемы: `[database] migration v41: chat_publish_claim` → `migration v41 applied in 0.0s | chat_publish_claim_v41`. Ошибок с `meme` / `joke` / `claim` / `publication` / `coordination` / `migration` нет.

## 7. Гейт требований (мем-карта)

`requirements_gate.py check --stage release`:

- `--candidate 092734a6… --deployed-commit 092734a6…` → **errors=1**: `map deployed_commit does not match actual deployment` (поле пустое). Иных ошибок нет: **164 scoped-строки имеют candidate-bound evidence и существующие артефакты (0 ошибок доказательств)**.
- фактическая пара `--candidate 092734a6… --deployed-commit bd0f38ed…` → **errors=2**, обе — идентичность развёртывания: `deployed commit missing or differs from reviewed candidate` (гейт требует `deployed == candidate`, а выложен bump-коммит с тем же деревом) и `map deployed_commit does not match actual deployment`.

Это **не** дефект продукта и не ошибка доказательств: разрыв чисто учётный. Карту я не правил (запрещено заданием) — биндинг `deployed_commit`/`deployed_release` за PM (§11.3).

## 8. Наблюдения после выкладки

- **(c) Схема/таблица после рестарта — НАБЛЮДАЛОСЬ:** `user_version=41`, 124 таблицы, `chat_publish_claim` на месте (12 колонок, PK `chat_id`), 0 строк, дубля миграции нет (03:56Z, 03:59Z).
- **(a) Естественный мем или `/meme` в окне — NOT_OBSERVED.** Причина: за окно 03:54–03:59Z естественного мем-хода не было (`meme`=0, `meme_initiative_attempt`=0, `send_photo` по мему — 0). Тестовые сообщения в реальные чаты не отправлялись (запрещено). Маркер для первой естественной проверки: ровно один `send_photo` без `caption`, без follow-up текста, и (для инициативы) строка `[direct] image delivered - text reply suppressed`.
- **(b) Первый естественный цикл инициативы / `publication_conflict` — NOT_OBSERVED.** Причина: воркер только зарегистрирован в планировщике (`Added job "MemoryMaintenanceService._tick_initiative_observer"`, 03:56:36Z); за окно ни одного тика с публикацией не произошло: строк `publication`/`coordination` — 0, броней в `chat_publish_claim` — 0. Это честное «наблюдения не было», а не подтверждение поведения.

## 9. Откат

- **Код:** `release/2.58.150` = `345a2ed7cff5df4ea8d4b2a4940d9e70e32a177a` (2.58.150). Ref на сервере сохранён: `git checkout -B release/2.58.150 345a2ed7 && systemctl restart admin_bot` (≈25 с до `healthz`).
- **Данные:** `/tmp/predeploy-258151.db` — 1 679 773 696 Б, `user_version=40`, 123 таблицы, `quick_check=ok`.
- **Схема при откате — только код.** Таблица `chat_publish_claim` остаётся (аддитивная, пустая) и **безвредна**: раннер применяет шаги со `version > current user_version`, у кода v40 максимальный шаг 40, поэтому на БД с `user_version=41` не применяется ни один шаг и ошибки нет; таблицу код v40 не читает ни в одном месте. Понижение `user_version` не требуется и не делается. Снимок БД — страховка, не обязательный шаг.
- Откат не выполнялся: блокирующих сбоев нет.

## 10. Побочные наблюдения

1. **Состав релиза шире мема** (§1.1): 4 не мем-линии уехали в прод с этим снимком. Ветки проревьюены, но COG-MAP в карте `evol` — 0/54 VERIFIED, у `EVOL-SRC-READER` 11 строк PENDING. Требуется решение Orchestrator/PM: считать это штатным trunk-релизом (тогда добрать биндинг в карте `evol`) либо впредь собирать по-линейные кандидаты. Практическое следствие: регрессии в cog-map/src-reader на проде формально не покрыты картой.
2. **10 красных пин-контрактов** (§2) — устаревшие числа/пути/длины, не дефекты; пересанкционирование за Builder.
3. На проде висит untracked `.cache/` — не мешает `git pull`, но стоит внести в `.gitignore` либо чистить (не трогал).
4. `pgrep -c -f 'bot.py'` может считать служебные процессы; надёжнее сверка с `MainPID` + `ps -o cmd= -p <MainPID>`.

## 11. Что дальше (владельцы)

1. **PM/Orchestrator:** зафиксировать состав релиза (§1.1) и состояние линии COG-MAP.
2. **Builder:** пересанкционировать 10 устаревших пин-контрактов (§2) — отдельным мелким коммитом, продукт не меняется.
3. **PM:** биндинг `deployed_commit = bd0f38ed…` + `deployed_release` (ветка, дата, tree-equivalence с `092734a6`) и повторный `--stage release`; либо решить вопрос эквивалентности bump-коммита на уровне карты (сейчас гейт требует `deployed == candidate`).
4. **Наблюдение на живом трафике:** первый естественный мем и первый цикл инициативы (маркеры в §8) — без тестовых сообщений в чаты.
