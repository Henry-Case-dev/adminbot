# EVOL — выпуск 2.58.149: голос фактчека (P0), L1-профиль решений (P1), UI-линия S12, ER-08-RC

Дата: 01.11.2026, 22:52–22:56 UTC, VPS `192.255.209.205`. Роль: DevOps.
Итог: **успешный выпуск, прод на 2.58.149 @ `40d615f1`.** Ветка выпуска: `release/2.58.149`.

## 1. Привязка выпуска

| Параметр | Значение |
|---|---|
| `DEPLOY_SOURCE` | commit `40d615f1011c2ed80badf8d8d430b696e16a4ea3` (ветка `release/2.58.149`, запушена в `origin`, сверена на сервере **до** любых изменений) |
| Ревью-кандидат (продуктовый код) | `5fc2ded5` — `evol/impl`: четыре независимо одобренные линии (P0 голос фактчека, P1 L1-профиль решений, UI S12, ER-08-RC) |
| Bump-коммит | `40d615f1` (2.58.144 → 2.58.149; **31 файл / 32 вхождения** — набор идентичен bump'у 2.58.148) |
| Предыдущий прод (baseline, цель отката) | `6645ae8d` — 2.58.148, ветка `release/2.58.148`, SQLite `user_version=40`, 123 таблицы |
| `MUTABLE_WORKTREE_REQUIRED` | **no** — сборка в отдельном worktree от `5fc2ded5`; грязная общая `master` в релиз не попала |
| Write scope на проде | `.git` (ветка/HEAD), `/tmp/predeploy-258149.db`, `/tmp/a258149/`, `/tmp/j258149.log`, журнал сервиса, PG-журнал `prompt_activations` + `prompt_revisions` (активация канонов при старте); файлы приложения деплой не меняет |
| Схема/миграции | Δ DDL = 0 (`user_version` остаётся 40), Δ внешних зависимостей = 0 |

**Отличие базы кандидата (та же ситуация, что и в 2.58.147/2.58.148):** `6645ae8d` = `613fae5d` + один bump-коммит, а `evol/impl` ответвился именно от `613fae5d`, поэтому в кандидате стояла версия `2.58.144`. Продуктовое содержимое 2.58.148 присутствует полностью: `git diff 6645ae8d → 5fc2ded5` по коду — только изменения четырёх одобренных линий (24 файла вне `plans/`, партиционирование `git diff --stat` совпадает с отчётами ревью).

Состав дельты (не-`plans`, не-`tests`): `bot_persona.py`, `chat_prompts.py`, `direct_chat_service.py`, `direct_l1.py`, `factcheck_orchestrator.py`, `factcheck_prompts.py`, `factcheck_renderer.py`, `factcheck_service.py`, `mca_self_model.py`, `prompt_composer.py`, `prompt_migrations.py`, `prompt_registry.py`, `prompt_style_blocks.py`, `system2_handoff.py`, `temporal_factcheck.py`, `usage_events.py`, `web/app.js`, `web/index.html`, `web/static/app.css`. Ни одного файла схемы/миграций БД — **Δ DDL = 0**.

## 2. Ход выпуска (3 одиночных логина; ни одной неудачной аутентификации, без поллеров)

- **recon 22:51:11 UTC** (закрыт сразу): `HEAD=6645ae8d`, ветка `release/2.58.148`, tracked-dirty=1 (`?? .cache/` — пре-существующий), `active/running`, `MainPID=1112507`, `NRestarts=0`, `/healthz` 200 `2.58.148`, schema v40, `quick_check=ok`, media 66, диск 26%.
- **основной прогон 22:52:05 UTC** (всё в одном соединении):
  - снимок БД `/tmp/predeploy-258149.db` через sqlite backup API: `1 679 773 696 Б`, `user_version=40`, `quick_check=ok`, 123 таблицы;
  - `git fetch` → `origin/release/2.58.149 = 40d615f1…` — сверено с ожидаемым SHA **до** любых изменений (`SHA_MATCH=1`, иначе прогон прерывался без изменений);
  - `git checkout -B release/2.58.149 origin/release/2.58.149` → `HEAD=40d615f1`, ветка `release/2.58.149`, tracked-dirty=1 (`?? .cache/`), `APP_VERSION = "2.58.149"`, `FACTORY_SET_SHA256_12 = "630ca46dff76"`;
  - `chown adminbot:adminbot` по отслеживаемым файлам и `web/` (rc=0);
  - `systemctl restart admin_bot` в 22:52:36 UTC; `/healthz` отдал `2.58.149` на первой же пробе.
- **стабилизация в том же соединении:** окно 75 с → тот же `MainPID=1178931`, `NRestarts=0`.
- **финальный короткий коннект 22:55:28 UTC** (read-only): `uptime=172 c`, `MainPID=1178931`, `NRestarts=0`, `HEAD=40d615f1`, `dirty=1` (`.cache/`), журнал/маркеры/PG-история.

Все RFC-проверки (ассеты, маркеры, журнал, PG) уложены в основной прогон и одну read-only сессию — 3 логина суммарно, без повторов после неудач.

## 3. Проверки до выпуска (worktree на `5fc2ded5` + bump)

| Проверка | Результат |
|---|---|
| `compileall` (`bot.py`, `config`, `services`, `web`, `tests`) | rc=0 |
| Node-пины (4 bump-пина + `round1026_polygon_background` + `routing_test` + `asap_ui02_delta` + `evol_w9_responsive` + `round1025_f9_savebar_visual` + `evol_w7_nav`) | **11/11 OK** |
| Пин-набор python: 59 тестовых файлов, затронутых четырьмя линиями (включая 24 bump-пина, `test_asap_fc_voice01_verbalizer`, `test_asap_fc_voice_l1_decision_profile`, `test_er08_limits_context`, `test_er65_sent_segment_snapshot`, `test_prompt_migrations`, `test_webapp_evol_w14_states`, `test_factcheck_*`, `test_direct_l1_*`) | **1790 passed, 1 failed** (112 с) |
| Дифф bump'а | 31 файл / 32 вхождения; `non_version_lines=0` (изменены только литералы версии, включая regex-форму `2\.58\.144` в 4 JS-пинах) |
| Чистота bump-коммита | строго 31 файл; evidence-артефакты не тронуты (тест `test_webapp_evol_w12_internals`, перезаписывающий скриншоты, в набор намеренно не включён) |

**Единственный failed-тест — пре-существующий, не регрессия:**
`tests/test_verbilizer_response_modes_round1023.py::TestTwoCallModes::test_summary_kill_switch_off_prev_narrator`.
Он требует, чтобы при `SMART_VERBALIZER_MODES_ENABLED=False` Stage-2 system равнялся ровно `PREV_SUMMARY_NARRATOR_R1023`, а фактический payload содержит хвост `<Speech_Base>…` (781 символ из **локальной** конфигурации владельца, `speech_owner_block`).
Проверка на развёрнутой базе: тот же тест, запущенный на worktree `6645ae8d` (прод 2.58.148), падает **идентично** → дефект изоляции теста, а не выпуска. Ассерт не затронут дельтой (её хунк в этом файле — в `TestFactcheckTwoCallMode`, строка ~417), `services/summary_generator.py` и `speech_owner_block` в выпуске не менялись, поэтому OFF-паритет пути саммари сохранён.

## 4. Проверки после выпуска

| Проверка | Результат |
|---|---|
| `/healthz` (127.0.0.1:8000) | **200** `{"status":"ok","version":"2.58.149"}` |
| `/healthz` публично (`https://admin-bot.duckdns.org`, с рабочей машины) | **200** `{"status":"ok","version":"2.58.149"}` |
| `/api/health`, `/web/` (локально и публично) | **200 / 200** |
| Сервис | `active/running`, `MainPID=1178931` (не менялся за 172 с), **`NRestarts=0`**, `ExecMainStatus=0` |
| Число процессов | **1** (`/var/www/admin_bot/venv/bin/python /var/www/admin_bot/bot.py`) |
| SQLite | `user_version=40` (без изменений), `quick_check=ok` |
| Media | **66 файлов** до и после — без изменений |
| Git на проде | `40d615f1`, ветка `release/2.58.149`, dirty=1 (`?? .cache/` — пре-существующий неотслеживаемый) |
| Диск | 26% → 27% (снимок БД) |

## 5. Смоук развёрнутых ассетов (только чтение, без отправок в Telegram)

| Актив | Проверка |
|---|---|
| `/web/` (HTML) | 1 115 149 Б, sha256 `b11560d5…` — **байт-в-байт** совпадает с `web/index.html` кандидата после подстановки `__APP_VERSION__` → `2.58.149` (15 подстановок, −105 Б) |
| `/static/app.css` | 397 950 Б, sha256 `dde23c3e…` — **байт-в-байт** с `web/static/app.css` кандидата после такой же подстановки (2 подстановки, −14 Б) |
| `/web/app.js` | 1 643 611 Б, sha256 `3955674b…` — **байт-в-байт** с `web/app.js` кандидата и с файлом на диске сервера |
| Файлы на диске сервера | `web/index.html` и `web/static/app.css` совпали с сырыми хешами кандидата (`318ecf07…`, `691a9ff6…`) → правок «на месте» нет |
| Маркеры UI-линии S12 в отданных ассетах | `teleport` в HTML = **19** вхождений (`<teleport to="body">` для save-bar), `speech-savebar` = **8** вхождений (5 строк), `--z-toast: 105` = **1**, различных `--z-*` токенов = **15**, `teleport` в `app.js` = **1** |
| Маркеры P0/P1 в развёрнутом коде | `compose_speech_system` = 1, `speech_owner_block` = 1 (вызовы Direct/Summary сохранены); `ПРОФИЛЬ РЕШЕНИЙ` ×3 + `def build_decision_profile_block` в `services/bot_persona.py`; в `services/direct_l1.py` — использование builder ×2 + ссылка на секцию ×1 (строки 864, 1454) |
| Маркеры ER-08-RC | `l1_reply_chars_cap/total_chars/delivered_chars/truncated` + `l1_kept_mid` — 27 вхождений в `services/direct_chat_service.py`, 3 — в R17-whitelist `services/usage_events.py` |
| Реестр промптов | `FACTORY_SET_SHA256_12 = "630ca46dff76"`; пары метка→печать совпали ровно: `factcheck-voice-historic-01`/`45361c23221c`, `factcheck-analyst-voice01-semantics`/`ed4c7a642804`, `factcheck-single-voice01`/`dcbd765fb860`, `temporal-analyst-voice01-semantics`/`506f9787af4e`, `l1-planner-decision-profile`/`ef61a9dd6798` |

Аутентифицированные вызовы истории промптов не выполнялись (нужна TMA-сессия владельца); подпись `initData` на сервере не подделывалась.

## 6. Журнал после деплоя

Окно после рестарта 22:52:36 → 22:55:28 UTC, **276 строк**:

- `Traceback` = **0**, `ERROR`/`CRITICAL` = **0** — новых ошибок нет;
- `WARNING` = **1** — известный предсуществующий класс: `services.summary_memory - SmartModule: embedding generation not serviceable | index=smart_archive | status=superseded` (тот же класс наблюдался на 2.58.146/2.58.147/2.58.148, вне рамок выпуска);
- `anticliche` — **5 строк, все INFO** (`stopped` при рестарте, `Added job`, `started | first_run_delay_min=5`, `pipeline_step …status=ok`, инициализация). Отказов `en.wikipedia.org` (403) в этом окне **не было** — известный класс не проявился, а не «подавлен»;
- `[prompt_migration]` = 0 строк (лестница `PROMPT_MIGRATIONS` на старте действительно не работает — активация идёт политикой релиза);
- `[budget_migration]` — INFO-строки «уже новый дефолт» (4 ключа), `CONFIG_MIGRATION_CUSTOM_PRESERVED` для `limits.chat_context_budget_tokens` — владельческая настройка сохранена.

## 7. Постдеплой-наблюдения (честно)

**7a. Активация канонов на старте — OBSERVED (все пять блоков).**
`[prompt_release] релиз применён | release=evol-016-cutover | blocks=109 | changed=5 | retired=0` в 22:52:42 UTC; активации `outcome=applied`:

| Блок | Метка | `rev` (PG) | `fac` (PG) | detail |
|---|---|---|---|---|
| `factcheck.base.verbalizer` | `factcheck-voice-historic-01` | `rev:a124fc8074a9` | `fac:d89b5d3196fa` | factory_activate |
| `factcheck.base.analyst` | `factcheck-analyst-voice01-semantics` | `rev:fd4fe7110feb` | `fac:9b3d10ff9101` | factory_activate |
| `factcheck.base.single` | `factcheck-single-voice01` | `rev:aba72f127099` | `fac:719f9106455c` | factory_activate |
| `temporal.analyst` | `temporal-analyst-voice01-semantics` | `rev:c044cbccca7e` | `fac:f158076975b2` | code_revision_recorded (scope=code) |
| `direct.base.l1_planner` | `l1-planner-decision-profile` | `rev:bfb6c7eedfc4` | `fac:efc5da44f2d0` | factory_activate |

Подтверждение новизны байтов (а не повторной активации старых): все `rev` отличаются от значений 2.58.148 (17:29:34 UTC), где было `direct.base.l1_planner=dc593e4f6264`, `factcheck.base.analyst=d4d7fcba222f`, `factcheck.base.single=d1ec63b8569c`; `factcheck.base.verbalizer` в 2.58.148 вообще не активировался фабрикой (последняя запись — `legacy_import`), сегодня получил первую фабричную активацию.

**Ограничение наблюдения (важно):** журнал печатает `block`-id, а не текст метки; связка block→метка→печать подтверждена **кодом развёрнутого коммита** (`services/prompt_registry.py`, пары из §5 — все пять совпали) плюс фактом `factory_activate`. Сами PG-записи хранят `rev`/`fac` хеши; отдельной строки «метка=…; печать=…» в журнале нет.

**Владельческие настройки не разрушены — OBSERVED.** История `prompt_activations` по этим пяти блокам содержит только `deploy_activate`/`legacy_import` (никаких `manual_edit`/`owner_edit`), поэтому перезаписывать было нечего. Единственная владельческая правка в журнале — `summary.cover.style` (`scope=chat`, `manual_edit`, `owner_edit`, 31.10.2026 19:17 UTC) — не затронута: `retired=0`, блок вне пакета. Конфигурационные владельческие значения также сохранены (`CONFIG_MIGRATION_CUSTOM_PRESERVED` для контекстного бюджета).

**7b. `FACTORY_SET_SHA256_12 = 630ca46dff76` — OBSERVED в развёрнутом коде.** Константа присутствует в `services/prompt_registry.py` развёрнутого коммита (`FACTORY_SET_SHA256_12 = "630ca46dff76"`), git-дерево на проде совпадает с `40d615f1` (dirty только `.cache/`). Отдельного рантайм-эндпоинта, печатающего константу, нет — наблюдение сделано по коду + совпадению печатей при `factory_activate`.

**7c. `plan_meta.l1_context_source` и новые `l1_reply_*` — NOT_OBSERVED.** В окне не было ни одного живого диалогового хода: 0 событий `plan_meta`, 0 вхождений `l1_context_source`, 0 `l1_reply_`, 0 вызовов `llm.generate`. Единственное упоминание `direct_l1` — INFO `config_cache: set | key=prompts.direct_l1_planner_system_prompt` при старте. Причина: за 3 минуты окна в 1–2 личных чатах не было сообщений; тестовые сообщения в реальные чаты без отдельной авторизации не отправлялись и не отправляются. Проверить на первом же естественном ходу (durable `llm_usage_events.plan_meta` + журнал): `l1_context_source` ≠ `hot` и наличие осей `l1_reply_chars_cap/total_chars/delivered_chars/truncated/kept_mid`.

**7d. Ошибки/предупреждения по `factcheck` / `verbalizer` / `prompt_release` / `direct_l1` / бюджетам — OBSERVED (отрицательный результат).** Строк уровня error/warn по этим темам нет. Все совпадения — INFO: активации `prompt_release`, `config_cache: set prompts.factcheck_*`, `[budget_migration] уже новый дефолт`, `[factcheck_context_migration] legacy == дефолт`, `[factcheck_wide_context_migration] уже применено — no-op`.

## 8. Побочные наблюдения

- **Пре-существующий дефект изоляции теста (не выпуск):** `test_summary_kill_switch_off_prev_narrator` падает и на развёрнутой базе `6645ae8d`, потому что ожидает пустой owner-блок, а локальная конфигурация владельца даёт `<Speech_Base>` 781 символ. Риск: низкий (ложный красный в наборах пинов, маскирует реальные регрессии OFF-паритета). Owner — Builder; рекомендация: замокать `speech_owner_block` в этом тесте.
- **Пре-существующее, не связано с выпуском:** `services/anticliche_worker` исторически получает внешние отказы от `en.wikipedia.org` (класс с 25.10); в этом окне отказов не было (воркер только стартовал, `first_run_delay_min=5`). Файл воркера в релизе не менялся.
- **Инструментарий релиза:** скрипты прогона передаются в `bash` по stdin; локальные файлы с CRLF дают безвредную строку `bash: line N: $'\r': command not found` в конце (все команды уже выполнены; коды выхода ssh 127 — артефакт обёртки, не сервера). Исправление на будущее: писать скрипты сразу с LF.
- **Измерения:** `pgrep -c -f 'bot.py'` = 1 при точном шаблоне; фактический процесс один (`pgrep -a` → `MainPID`). `grep -c` считает строки, поэтому «`speech-savebar`=5» в отчёте прогона — это 5 строк (8 вхождений).
- **Кириллица в удалённых грепах:** PowerShell кодирует stdin в кодовую страницу консоли, поэтому первый прогон дал `DECISION_PROFILE_SECTION=0` — артефакт кодировки, проверено повторно через Python с `\u`-эскейпами (§5: маркер на месте, 3 вхождения).

## 9. Откат

- **Код:** цель **`6645ae8d`** (2.58.148). Механика: `git checkout -B release/2.58.148 6645ae8d` + `systemctl restart admin_bot` + `/healthz` (ожидается `2.58.148`). Схема та же (v40) → откат схемо-безопасен. Ветка доступна в `origin/release/2.58.148`.
- **Данные:** снимок БД до выпуска `/tmp/predeploy-258149.db` (1 679 773 696 Б, `user_version=40`, `quick_check=ok`, 123 таблицы).
- **Промпты:** откат — `activate_revision` на предыдущие ревизии (лестница `PROMPT_MIGRATIONS` на старте мертва, `rollback_prompt_canons` не применять). Зафиксированные предыдущие ревизии (2.58.148, 17:29:34 UTC): `direct.base.l1_planner` → `rev:dc593e4f6264`, `factcheck.base.analyst` → `rev:d4d7fcba222f`, `factcheck.base.single` → `rev:d1ec63b8569c`; для `factcheck.base.verbalizer` предыдущая запись журнала — `legacy_import`-снимок (фабричной ревизии до сегодня не было), для `temporal.analyst` — `scope=code` (откат только кодом).
- **Текущее состояние:** откат не потребовался.

## 10. Замечания

- Карта требований (`plans/features/evol/requirements-map.json`), `plans/progress_scope.json` и `plans/workflow_state.md` этим выпуском **не менялись** — привязка доказательств к релизу `40d615f1` остаётся работой PM/Orchestrator.
- Границы выпуска: 2.58.149 содержит ровно четыре одобренные линии; COG-MAP (2 заблокированных сценария S12) в выпуск не входит.
- Функциональная приёмка поведения (голос фактчека, L1-профиль решений, визуал S12, ER-08-RC на живом ходу) — за Reviewer/PM; здесь подтверждены идентичность развёрнутого артефакта, активация всех пяти канонов и работоспособность сервиса. Обязательные live-наблюдения, которых в окне не было, честно помечены `NOT_OBSERVED` в §7c.
