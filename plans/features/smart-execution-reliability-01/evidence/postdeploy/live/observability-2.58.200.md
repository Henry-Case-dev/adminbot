# 2.58.200 — production observation batch: identity / observability / I1 / I2

- Дата: 2026-11-14, сервер UTC `05:54:29–06:22:00` (локально `17:54–18:22 +12:00`).
- Прод: `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot` (user `adminbot`),
  deployed `0e4a144db476a1535ae3a2b79a7cce30354ad866` / `2.58.200`, branch `release/2.58.200`.
- Режим: **только чтение**. Ничего не деплоилось, не рестартилось, не менялось;
  Telegram-сообщений не отправлялось; платных LLM-вызовов нет (capacity — только
  каталог провайдера). Все DB-сессии PostgreSQL — `READ ONLY`, SQLite — `mode=ro`.
- Требования этого batch: `SXR-H3-01`, `SXR-H4-01`, `SXR-I1-01`, `SXR-I2-01`,
  `SXR-K3-01`, observer-часть `SXR-L1-01`. Статусы карты и
  `plans/progress_scope.json` **не менялись**.
- **Harness execution (`smart_live_canary.py` / `fc_live_canary.py`) в этот batch
  не входил** — контрольные сценарии >4 раундов / >6 вызовов / >2 tool calls в
  раунде, budgets ON/override и live-factcheck остаются на отдельный assignment.
- SSH: 1 recon + 1 основной batch (1038 с) + 3 коротких добивочных сеанса
  (2/1/1 с) после дефекта собственной probe-обвязки: первый probe запускался из
  `/tmp` без `PYTHONPATH` и читал `POSTGRES_DSN` до загрузки `.env`. Все 5
  подключений успешны, без параллельных сессий и без повторов auth; fail2ban не
  срабатывал; `/healthz` был доступен всё время. Prod-состояние не менялось.
- Метки чатов: `CHAT_C1` = `-1004482340693` (группа), `CHAT_C2` =
  `-1002661910336` (группа, большой backlog), `CHAT_DM8` = `5885953495` (DM
  владельца). **`CHAT_C2` здесь — это `CHAT_C1` из recon 13.11.2026.**

Raw (redacted) выводы команд: `evidence/postdeploy/live/raw/observability-2.58.200-raw.txt`.

## 1. Identity / health (H4, K3)

| Поле | Наблюдение |
|---|---|
| HEAD | `0e4a144db476a1535ae3a2b79a7cce30354ad866` |
| Branch / upstream | `release/2.58.200` / `origin/release/2.58.200`, ahead/behind `0/0` |
| Рабочее дерево | tracked/staged чисто, только `?? .cache/` |
| `APP_VERSION` | `2.58.200` (grep `config/settings.py`; runtime — `/healthz` и identity) |
| Service | `active (running)`, PID `709883`, `ExecMainStartTimestamp` 2026-11-14 05:18:59 UTC, `NRestarts=0` (весь batch) |
| Пользователь unit | `User=adminbot`; `Group` не задан (primary `adminbot`); процесс uid 999, gid 987 |
| InvocationID | `1a3ab8ad1f38460ea397417f8c762845`; совпадает с `/proc/709883/environ` |
| cgroup | `/system.slice/admin_bot.service` |
| `/healthz` | 200 `{"status":"ok","version":"2.58.200"}` — проверено 4 раза (05:54, 06:14, 06:17, 06:21 UTC; 0.08–0.09 с) |
| `.deploy/release.json` | 317 B, owner `adminbot:adminbot`, mode 644, mtime 05:18:53.894, sha256 `8c70494bfb7d6659ab24609002e6ed9c728b883e72f1ca38e0dc7c96b8e12611` |
| Manifest content | `schema=1`, `deployed_sha=0e4a144d…`, `version=2.58.200`, `effect=deploy`, `previous_sha=d20a7f73…`, `previous_version=2.58.199`, `release_branch=release/2.58.200`, `dirty_tracked=false` |
| Manifest ↔ restart | записан 05:18:53, сервис стартовал 05:18:59 → пережил рестарт, с тех пор не менялся (mtime тот же) |

## 2. Schema / startup

| Поле | Наблюдение |
|---|---|
| `PRAGMA user_version` | `47` |
| `journal_mode` | `wal` |
| `PRAGMA quick_check(1)` | `ok` (полный проход 2,8 ГБ занял **46,1 с** — разовая read-only проверка, не штатная операция приложения) |
| Миграции | `[database] migrations: start \| current user_version=47 \| pending=[]`; `complete \| user_version=47 \| total 0.0s` |
| Startup | `[webapp] lifespan started \| pg_available=True` (05:19:04); `CONFIG_MIGRATION_CUSTOM_PRESERVED` для `limits.chat_context_budget_tokens`, `models.image_base_url`, `models.image_model` — пользовательские значения сохранены |
| Таблицы I1/I2 | `task_jobs`, `smart_messages`, `meme_initiative_attempt`, `mca_events`, `mca_experience_episodes`, `mca_experience_feedback` присутствуют |

Журнал с момента старта (окно 05:18:59–06:21:59, 4 179 строк):

- `Traceback` — **2**; `ERROR/CRITICAL` — **3**; `WARNING` — **113**.
- ERROR: 2 × `anticliche_worker` (`sources_unavailable` / wikipedia, 05:24:03) и
  1 × `llm_client` (`LLM timeout … reason=total_budget_exceeded`, nano-gpt, 05:57:23).
- Оба traceback — **пойманные** отказы семантического батча
  (`[mca16] semantic batch failed — retry next pass`, 06:05 и 06:19); job при
  этом завершается `completed`, падения процесса нет.
- Классификация предупреждений (сравнение с предыдущим прогоном
  13.11 08:36–14.11 05:18: 69 339 строк / 58 traceback / 62 ERROR / 969 WARNING):
  - `mca_event=suspended` — 84 WARNING-строки (в pre-окне 24 за 20,7 ч);
    WARN-уровень жизненного цикла уроков, не ошибка; в этом же окне
    136 событий `activated` (первый массовый дренаж после деплоя).
  - `mca_event=experience.fresh_stream_lag` — 2 (ожидаемый WARN: реальный lag
    больше порога 500).
  - `[vision] claim sweep slow` — 3 (6–9,7 с; pre — 17) — pre-existing класс.
  - `model_capacity: unknown model … planning window=1000000` — 1 (05:47:54);
    прежний аварийный `16384` больше не используется.
  - LLM retry / fallback (`ReadTimeout`, `fallback OK model=deepseek-flash`) —
    внешний провайдер, обработано; `total_budget_exceeded` — таймаут запроса,
    не бюджет токенов.
  - `[direct] tool-loop degraded | reason=finish | rounds_used=4` — 1 (05:56:23);
    `reason=finish`, не код лимита (побочное наблюдение, не доказательство L1).
  - APScheduler «job was missed» (05:20, startup) и FTS-only warning — pre-existing.

## 3. H3 — журнал сервисного пользователя

| Проверка | Наблюдение |
|---|---|
| `id adminbot` | `uid=999(adminbot) gid=987(adminbot) groups=987(adminbot),999(systemd-journal)` |
| `sudo -l -U adminbot` | `User adminbot is not allowed to run sudo on …` |
| `sudo -u adminbot journalctl -u admin_bot -n 20` | rc=0 |
| Точный argv fetcher'а: `journalctl --no-pager --quiet --output=short-iso --lines=10 _SYSTEMD_INVOCATION_ID=1a3ab8ad…` | rc=0 |
| Реальный in-process чекап (05:47:37) | `[checkup fetcher] journal read \| state=ok \| window=300 \| matched=8`; `used_fallback` не сработал |
| Read-only прогон кода `CheckupLogsFetcher.fetch()` (identity из `/proc/<bot pid>/cgroup`) | identity `systemd`, unit `admin_bot.service`, invocation совпадает; `last_state=ok`, `used_fallback=false`, отчёт 1 873 символа |
| Внутренний ledger fallback | присутствует в коде (не использован: journal читается); live-fallback не наблюдался, потому что отказ не возникал |

Проблема `No journal files were opened due to insufficient permissions` **не
воспроизводится**: чтение идёт от `adminbot` через группу `systemd-journal`,
без root и без произвольного sudo. Unit не запущен от root.

## 4. H4 — manifest и потребители

- `sudo -u adminbot cat .deploy/release.json` → rc=0 (файл читается сервисным
  пользователем).
- `collect_identity('/var/www/admin_bot', process_started_at=05:18:59Z)`
  (тот же код, что используют SourceReader/чекап):
  - `code=verified_deployed`, `reason=""`, `conflict=[]`;
  - `deployed_sha = checkout_sha = 0e4a144d…`, `dirty=false`;
  - `version_provenance = {runtime: 2.58.200, manifest: 2.58.200, consistent: true}`;
  - `sources = [release_manifest, git_head, git_cli, runtime_app_version, process_start]`;
  - `artifact = git_checkout / release_branch=release/2.58.200`,
    `deployed_at=05:18:53.892873Z`, `process_started_at=05:18:59Z`;
  - `previous_sha=d20a7f73…`, `previous_version=2.58.199`.
- Фактический in-process чекап 05:47:37:
  `[checkup] identity | runtime= | deployed_sha=0e4a144db476 | checkout_sha=0e4a144db476 | source_verified=True | git_meta=True | commits_since_deploy=None | sources=12/15 | status=degraded`.
  `status=degraded` — из-за 3 недоступных источников (12/15), ровно как на
  2.58.199 в recon 13.11 (пустой `runtime=` — тоже pre-existing); identity при
  этом verified, SHA совпадает с manifest и checkout. Манифест задним числом не
  создавался: mtime/`deployed_at` раньше старта процесса, `effect=deploy`,
  `previous_sha` заполнен.

## 5. Effective config — K3 и observer-часть L1

| Слой / ключ | Значение |
|---|---|
| `.env` overrides (`BUDGETS_ENABLED`, `CHAT_UNKNOWN_MODEL_WINDOW`, `MCA_TOOL_*`, `TOOL_CHAIN_LIMITS_ENABLED`) | **нет ни одного** |
| Process env / unit `Environment=` для тех же ключей | **нет ни одного** |
| Factory `settings` | `BUDGETS_ENABLED=true`, `TOOL_CHAIN_LIMITS_ENABLED=true`, `CHAT_UNKNOWN_MODEL_WINDOW=1000000`, `MCA_TOOL_MAX_TOTAL_CALLS=0`, `MCA_TOOL_MAX_METERED_CALLS=0`, `MCA_TOOL_MAX_SAME_CALL=0`, `MCA_TOOL_CHAIN_TIMEOUT_SECONDS=0.0` |
| PG `flags.budgets_enabled` | `false`, updated 2026-10-25T06:13:07Z (не менялось) |
| `CHAT_C1` override | `flags.budgets_enabled=false` (8 ключей) |
| `CHAT_C2` override | `flags.budgets_enabled=false` (32 ключа на 06:11) |
| `CHAT_DM8` | override отсутствует → global `false` |
| **Effective master OFF** | **все 3 реальных чата** |
| Budget-related PG rows | `flags.chat_context_budgets_enabled=true` (2026-08-29), `models.llm_total_budget=60.0` (2026-08-29) и старые `limits.*` — исторические, не включают master enforcement |
| Gate опыта | `experience_lessons_enabled=true`, `experience_review_enabled=true`, `review_enabled=true`, cadence `daily`; дренаж 6 чатов / 50 строк / 12 батчей / 180 с |
| Capacity (chat model `z-ai/glm-5.3-flash-uncensored`, base `nano-gpt.com`) | sync resolver `1000000 / unknown_fallback`; async provider catalog `effective=1048576`, `max_output=32768`, `source=provider_catalog`, `confidence=verified`, `fallback_used=false`, `declared=1048576` |
| Сохранённые значения | `bot_settings`: 548 строк, max `updated_at=05:19:03.548386Z`; **единственная новая строка** — `prompts.factcheck_subject_system_prompt` (len 2146, category prompts). `models.llm_model_name`/`llm_base_url`/fallback — прежние даты (11.11 / 12.09 / 12.09). |
| Per-chat после деплоя | `CHAT_C1` updated 11.11, `CHAT_DM8` updated 28.10 — не менялись. `CHAT_C2` обновлён **06:11:54** живым действием владельца: `prompt_activations` / `prompt_revisions` — `block_id=checkup.base.system`, `scope=chat`, `kind=manual_edit`, `outcome=applied`, `reason=owner_edit`, actor — DM владельца; к deploy (05:19) это отношения не имеет |

Вывод по K3: деплой не перезаписал сохранённые настройки/модели/промпты
(на 05:19 — только новая заводская строка); ручное изменение владельца после
деплоя сохранено, а не затёрто. Новых OFF/SHADOW-флагов для SMART-функций нет;
исправления стартуют без ручного включения.

Ограничение L1: observer-часть (effective OFF, отсутствие env-принуждения, caps 0,
capacity) подтверждена. Контрольный сценарий >4 раундов / >6 вызовов / >2
корректных tool calls в раунде, budgets ON и пользовательский override **не
выполнялся** — это harness assignment.

## 6. I1 — журнал инициативы/мемов

| Проверка | Наблюдение |
|---|---|
| Таблица | `meme_initiative_attempt` (SQLite `/var/www/admin_bot/local_database.db`, schema v47, шаг v40 присутствует) |
| Накопленные записи | 33 122 строки; `MIN(ts)=2026-10-31T12:42:03Z`, `MAX(ts)=2026-11-14T06:19:13Z` — старые записи не потеряны |
| Записи после деплоя | **92** (на 06:19), последние 06:19:11/06:19:13: `considered/passed` + `skipped/no_random_hit`, затем `considered/passed` + `skipped/cooldown_active` (detail 0/47 байт) |
| Spool | `local_database.db.attempts.pending.jsonl` **отсутствует**; `.tmp` отсутствует |
| Известные spooled `attempt_id` 13.11 | `266639345caf…` — 1 строка; `bf20677a446a…` — 1 строка (без дублей) |
| Journal `[meme]` после деплоя | **0** строк: нет `attempt spooled`, нет `spool not drained`, нет `attempt LOST` |
| Для сравнения pre-deploy | 126 `[meme]`, 64 `attempt spooled`, 45 `spool not drained` за 20,7 ч |

Установленная причина (recon 14.11 + read-only probe, не отменена):
`OperationalError: database is locked` (SQLITE_BUSY) на
`INSERT OR IGNORE` в `meme_initiative_attempt` файловым соединением; 15,147 с =
3 × `busy_timeout` 5 с + задержки; schema mismatch/readonly дали бы 0,000 с;
диск 29,6 ГБ свободно, `quick_check=ok`, права и блокировка ОС ни при чём.
Исправление — запись через единого писателя `DatabaseService.serialized()` +
короткий `busy_timeout` и durable-spool. В production после деплоя journal-путь
пишет штатно (92 строки, spool пуст), отказа не было. Новый подробный формат
ошибки (`op/table/db/busy_timeout_ms/elapsed_ms/error=…`) в этом окне **не
проверялся вживую**, потому что контеншна не было; он покрыт unit/review.

Последняя попытка: данные строки 06:19:13 совпадают по времени/полям с журналом;
spool пуст, поэтому read-model `attempts()` склеивает только таблицу. Сам
`attempts()` не вызывался (у него есть путь записи при непустом spool — не
рисковали), проверен источник данных; функция покрыта тестами Reviewer.

## 7. I2 — fresh stream

Источник/scope: `smart_messages`; durable per-chat курсоры
`semantic_cursor:<chat_id>` в payload `task_jobs(kind='experience.review')`;
watermark `2 407 146`; state version 2.

| Прогон (UTC) | Job | Длительность | Результат |
|---|---|---|---|
| 05:34:03→05:37:16 | `64edddc2c060` | 193 с | completed; событие 05:37:16: `cursor_rowid=15 345`, `lag_rows=2 058 465`, pending 13 521 |
| 05:49:03→05:51:12 | `afa74d4bfe6e` | 129 с | completed; **12 батчей**, прочитано 601, throughput 601, selected 569, `llm_unavailable=0`; курсор **15 945** (+600) |
| 06:04:03→06:05:01 | `3dc1fff704d2` | 58 с | completed; **3 батча** (+150) → курсор **16 095**; на 4-м батче `LLMBadResponseError: chat/completions: empty content` (nano-gpt), `retry next pass` |
| 06:19:04→06:19:20 | `e1251a4a9187` | 16 с | completed; 0 успешных батчей, `semantic_llm_unavailable=1`, курсор **16 095** (без потери строк) |

- Активных/зависших job нет (`i2_active_jobs=0`), attempt=1, retry не зациклен.
- Backlog/lag (payload → независимый read-only `COUNT(*)`):
  - 05:51: `lag_rows=2 057 878`, independent `2 057 880` (за время замера пришло 2 строки);
  - 06:05: `2 057 731` vs `2 057 733`;
  - 06:19: `2 057 733` vs `2 057 739` (6 новых строк).
  Расхождение всегда равно числу прибывших после замера строк → формула lag
  корректна, ноль не подставляется. `lag_seconds` 124 215 446 → 124 217 254,
  `lag_seconds_source=cursor_distance`, `lag_source=cursor_distance`,
  `partial=false`; самая старая необработанная реплика — 2022-12-07 (импорт
  истории), поэтому lag в секундах огромный и честный.
- `semantic_pending` (discovered-не-обработано): 12 935 → 12 788 → 12 790;
  отдельно от `lag_rows`, как и задумано.
- `CHAT_C1` (вторая группа): курсор 2 407 127 = `MAX(id)`, pending 0 — дренаж
  завершён. `CHAT_DM8`: курсор 2 407 145 = `MAX(id)`. Большой backlog — только
  `CHAT_C2`.
- Invalid events: `semantic_rows_ineligible` 32 / 8 / 6 (media/forward/command/
  пустой текст) — курсор двигался на успешных батчах; `semantic_parse_invalid=0`,
  `semantic_read_errors=0`, `semantic_chats_deferred=0`. Битый ответ провайдера
  не двигает курсор и не блокирует другие чаты (повтор на следующем проходе).
- Скрытые бюджеты: модуль не читает `budget_gate`/`flags.budgets_enabled`;
  effective master OFF во всех чатах; лимиты дренажа — только явные
  `memory.experience_semantic_*` (12/180/6/50).
- Потери/дубли/пропуски: курсор монотонен (15 345 → 15 945 → 16 095; на
  провайдерском отказе не откатывается и не перескакивает); уникальные ключи
  `mca_experience_episodes` 2 105/2 105 и `mca_experience_feedback` 1 355/1 355 —
  **0 дублей**; `semantic_duplicates` 0–1 (нормальная дедупликация кандидатов).
  Число строк на прогон не превышает программный потолок (≤600 за 12 батчей на
  чат), систематического перескока не видно.

Ограничение: с 06:04 провайдер `nano-gpt.com` intermittently отдаёт пустой
`chat/completions`/таймауты (`ReadTimeout`, `empty content`), поэтому последние
два тика дренаж не продвинулся (05:49-прогон до этого прошёл 12 батчей).
Строки не потеряны (лежат после курсора), job завершается `completed`, повтор —
следующим проходом. Это внешняя доступность провайдера, не дефект кода дренажа;
но пока провайдер в таком состоянии, backlog `CHAT_C2` не будет сокращаться.

## 8. Findings / классификация

1. **MEDIUM (внешняя зависимость, не код):** nano-gpt `empty content`/таймауты
   с ~05:56; семантический дренаж 06:04 (частично) и 06:19 (0 батчей) не
   продвинулся. Следствие: live-canary с реальными LLM-вызовами нужно запускать
   при здоровом провайдере, иначе будет ложный отрицательный результат. Данные
   не теряются. Тот же класс был pre-deploy (29 `semantic batch failed`).
2. **LOW:** `mca_event=suspended` 84 за 35 мин (pre 24/20,7 ч) — WARN-события
   жизненного цикла уроков при первом массовом дренаже; не ошибка, наблюдать.
3. **LOW:** `[vision] claim sweep slow` 3 раза (6–9,7 с), `anticliche`
   `sources_unavailable` 2 ERROR — pre-existing классы, не этот релиз.
4. **INFO:** `models.llm_display_name` всё ещё `"NanoGPT Deepseek"` при модели
   GLM — косметика, pre-existing.
5. **INFO:** unit не имеет дополнительного hardening (`NoNewPrivileges=no`,
   `ProtectSystem=no`, `ProtectHome=no`, `PrivateTmp=no`); журнал при этом
   доступен только через группу `systemd-journal`, root/sudo у сервиса нет.
   Pre-existing, в объём H3 не входит, но зафиксировано.
6. **INFO:** полный `PRAGMA quick_check` 2,8 ГБ занял 46,1 с; сервис всё время
   оставался активным, но как штатная проверка это дорого.

## 9. Что не наблюдалось (границы)

- Harness-сценарии `smart_live_canary.py` / `fc_live_canary.py` (L1 control,
  live factcheck, Telegram delivery) — **не выполнялись**, отдельный assignment.
- Новый формат детальной ошибки I1 в production не сработал (контеншна не было).
- `attempts()` read-model не вызывался (во избежание записи spool); проверен
  источник и совпадение последней строки.
- In-process чекап `status=degraded` (12/15 источников) — состав трёх
  недоступных источников не перечислен; на 2.58.199 было так же.
- Повторный успешный проход I2 после провайдерского отказа (06:19+) не
  наблюдался — провайдер отказывал до конца окна.
- Реальная Telegram-доставка новых функций, живые ответы провайдера/поиска и
  live-factcheck — вне этого batch.
- WAL/IO-нагрузка дренажа не измерялась; наблюдаемые `COUNT(*)` — 94–187 мс.

## 10. Housekeeping

- Remote: все probe-скрипты и `/tmp/devops_obs*` удалены в каждом сеансе
  (cleanup-строки `probe_removed=yes tmp_removed=yes`); production-tree чистый.
- Local: `WorkspaceData/runs/…/report-091878341c` закрывается `run-close` после
  промоушена отчёта; в репозиторий добавлены только этот отчёт и redacted raw.
- Рабочие worktree и ветки не трогались; `plans/progress_scope.json`,
  `plans/workflow_state.md` и карта требований не менялись.

## 11. Команды (redacted)

- recon: `echo RECON_OK; date -u; systemctl is-active admin_bot`
- identity: `git rev-parse HEAD`, `git status --porcelain`, `grep '^APP_VERSION' config/settings.py`
- service: `systemctl show admin_bot -p …`, `ps -o pid,user,group,etime,args -p <pid>`, `tr '\0' '\n' < /proc/<pid>/environ`
- env: `grep -E '^(BUDGETS_ENABLED|CHAT_UNKNOWN_MODEL_WINDOW|MCA_TOOL_…|TOOL_CHAIN_LIMITS_ENABLED)=' .env` (и то же по `/proc/<pid>/environ`)
- manifest: `sudo -u adminbot cat .deploy/release.json`, `sha256sum`, `stat`
- journal: `sudo -u adminbot journalctl -u admin_bot …`,
  `sudo -u adminbot journalctl _SYSTEMD_INVOCATION_ID=<id> …`
- DB: `venv/bin/python` read-only probe (`sqlite3` `mode=ro`, `PRAGMA query_only=1`;
  `asyncpg` с `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`)
- identity code: `deploy_identity.collect_identity(root, process_started_at=…)`
- journal code: `CheckupLogsFetcher.fetch()` с identity из `/proc/<pid>/cgroup`
- capacity: `model_capacity.resolve_model_context_window` + `resolve_capacity` (каталог провайдера, без LLM)
