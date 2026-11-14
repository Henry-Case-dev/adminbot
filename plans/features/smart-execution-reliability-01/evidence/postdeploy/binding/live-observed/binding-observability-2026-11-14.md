# Binding: observability batch 2.58.200 → SXR-H3-01 / H4-01 / I1-01 / I2-01 / K3-01

- Дата: 2026-11-14. Прод: 2.58.200, `0e4a144db476a1535ae3a2b79a7cce30354ad866`, `release/2.58.200`.
- Источник доказательств (read-only batch DevOps, commit `695d4627`):
  - `plans/features/smart-execution-reliability-01/evidence/postdeploy/live/observability-2.58.200.md`
    (`sha256 c2f8de42e3ca40b3169b1247da13fa7565e4e54dabf9429c984b475dcadc38da`);
  - `plans/features/smart-execution-reliability-01/evidence/postdeploy/live/raw/observability-2.58.200-raw.txt`
    (`sha256 9de6cc71a01bae0e7c511907681e88fc2b9e9453b4cc1b3d42f9573e1bbf7330`).
- Изменение карты: 59 обязательных строк (5 req_id × все их required-строки в `additional_requirements` + `items`)
  получили по одной `production`-записи (`candidate_commit` = `deployed_commit` = `0e4a144d…`,
  `artifact_path` = отчёт, `artifact_sha256` = c2f8de…), `status: VERIFIED`,
  `verified_via: "production 2.58.200 @ 0e4a144d; observability batch 2026-11-14"`.
  Строковый `postrelease_wait` снят как исполненный; историческое `approved_postrelease_wait` в review-записи сохранено.
- Батч был строго read-only (ни деплоя, ни рестарта, ни Telegram-сообщений, ни платных LLM-вызовов);
  harness-сценарии (`smart_live_canary.py` / `fc_live_canary.py`) в него не входили.

## SXR-H3-01 — BOUND (10 строк)

| Клауза приёмки | Наблюдённый факт |
|---|---|
| чтение журнала своего unit проверено в фактическом окружении процесса | реальный in-process чекап 05:47:37: `[checkup fetcher] journal read | state=ok | window=300 | matched=8`; read-only прогон `CheckupLogsFetcher.fetch()` с identity из `/proc/<bot pid>/cgroup`: kind=systemd, unit=`admin_bot.service`, invocation совпал, `last_state=ok`, `used_fallback=false`, отчёт 1873 символа (§3, raw 61–75, 123) |
| восстановлено штатно с минимальными правами | `id adminbot` → uid=999, groups=987(adminbot),999(systemd-journal); `journalctl` от сервисного пользователя rc=0 (unit и точный argv с `_SYSTEMD_INVOCATION_ID=1a3ab8ad…`), без root/sudo |
| бот не root, произвольного sudo/доступа к чужим сервисам нет | unit `User=adminbot`, процесс uid 999; `sudo -l -U adminbot` → «not allowed to run sudo»; fetch пиннит только свой unit/invocation. Live-попытки чтения чужого unit в батче не было — ограничение чужого unit подтверждено независимым ревью-контрактом (не новое утверждение) |
| внутренний поток событий остаётся fallback реального отказа | ledger-fallback присутствует в коде и не использован, т.к. журнал читается; live-fallback не наблюдался, потому что отказа не было |

Открыто: ничего по приёмке. Ненаблюдённым остаётся только сам fallback-путь при реальном отказе журнала — это не блокер, путь покрыт тестами/ревью.

## SXR-H4-01 — BOUND (10 строк)

| Клауза приёмки | Наблюдённый факт |
|---|---|
| `.deploy/release.json` реально существует | файл 317 B, `adminbot:adminbot`, mode 644, sha256 `8c70494b…`, читается сервисным пользователем (rc=0) |
| формируется существующим процессом деплоя | mtime/deployed_at `05:18:53.894Z`, сервис стартовал `05:18:59`; `effect=deploy`, `previous_sha=d20a7f73…`/`previous_version=2.58.199`, `dirty_tracked=false` |
| привязан к выложенной версии | `deployed_sha=0e4a144d…`, HEAD=`0e4a144d…`, `APP_VERSION=2.58.200`; `version_provenance={runtime: 2.58.200, manifest: 2.58.200, consistent: true}` |
| согласован с запущенным процессом | `collect_identity(root, process_started_at=05:18:59Z)`: `code=verified_deployed`, `conflict=[]`, `deployed_sha=checkout_sha=0e4a144d…`, sources включают `release_manifest`, `git_head`, `process_start` |
| переживает рестарт | манифест записан до старта (05:18:53 → 05:18:59) и с тех пор не менялся (mtime тот же), сервис `NRestarts=0` весь батч |
| используется SourceReader и чекапом | тот же `collect_identity`; фактический чекап 05:47:37: `deployed_sha=checkout_sha=0e4a144db476`, `source_verified=True`, `git_meta=True`. `runtime=` пустой и `status=degraded` (12/15 источников) — pre-existing, как на 2.58.199, identity при этом verified |
| манифест задним числом не создан | `deployed_at`/mtime раньше старта процесса, `effect=deploy`, `previous_sha` заполнен |

Открыто: ничего по приёмке; `status=degraded` чекапа относится к трём недоступным источникам (pre-existing) и не отменяет verified identity.

## SXR-I1-01 — BOUND (20 строк)

| Клауза приёмки | Наблюдённый факт |
|---|---|
| установлена реальная причина OperationalError (операция, таблица, путь БД, исключение, схема, соединение, блокировка, права, диск, writer/transaction path) | recon 14.11 + read-only probe: SQLITE_BUSY `database is locked` на `INSERT OR IGNORE` в `meme_initiative_attempt` через файловое соединение; 15,147 с = 3 × busy_timeout 5 с; schema mismatch/readonly дали бы 0,000 с; диск 29,6 ГБ, `quick_check=ok`, права/ОС-блокировка исключены; исправление — единый writer `DatabaseService.serialized()` + короткий busy_timeout + durable spool (§6) |
| запись попыток в основной журнал восстановлена | после деплоя 92 новые строки (последние 06:19:11/06:19:13), journal `[meme]` — 0 строк (нет `attempt spooled`/`spool not drained`/`attempt LOST`; pre-deploy 64/45) |
| spool опустошается идемпотентно без потерь и дублей | spool-файл `local_database.db.attempts.pending.jsonl` отсутствует (и `.tmp`); обе известные spooled-попытки 13.11 (`266639345caf…`, `bf20677a446a…`) — ровно по 1 строке |
| последняя попытка отображается корректно | строки 06:19:13 совпадают по времени/полям с журналом; spool пуст, поэтому read-model `attempts()` склеивает только таблицу. Сам `attempts()` в prod не вызывался (у него есть путь записи при непустом spool); проверен источник данных, функция покрыта unit/review-тестами |
| накопленные записи сохранены | `meme_initiative_attempt`: 33 122 строки, MIN(ts)=2026-10-31T12:42:03Z, MAX=2026-11-14T06:19:13Z |

Открыто: прямой вызов read-model `attempts()` в production не выполнен (осознанно, чтобы не задействовать write-path spool); данные и совпадение последней строки проверены. Новый подробный формат ошибки вживую не проверялся из-за отсутствия контеншна.

## SXR-I2-01 — BOUND (13 строк)

| Клауза приёмки | Наблюдённый факт |
|---|---|
| источник fresh stream, идентичность/scope курсора | источник `smart_messages`; durable per-chat курсоры `semantic_cursor:<chat_id>` в payload `task_jobs(kind='experience.review')`, watermark 2 407 146, state version 2 |
| причина отставания / ошибочного расчёта | формула lag сверена с независимым `COUNT(*)`; расхождение всегда равно числу строк, прибывших после замера (2 057 878/2 057 880; 2 057 731/2 057 733; 2 057 733/2 057 739) — расчёт корректен, ноль не подставляется; большой backlog CHAT_C2 — реальные строки истории (с 2022-12-07), не ошибка расчёта |
| фактическое продвижение курсора | 15 345 → 15 945 (+600 за 12 батчей) → 16 095 (+150 за 3 батча); на провайдерском отказе курсор не откатился и не перескочил |
| выполнение заданий | 4 job'а после деплоя `completed` (05:34, 05:49, 06:04, 06:19), `i2_active_jobs=0`, attempt=1 |
| невалидные события | 32/8/6 ineligible (media/forward/command/пустой текст); `parse_invalid=0`, `read_errors=0`, `chats_deferred=0`; битый ответ провайдера курсор не двигает и другие чаты не блокирует |
| скрытые бюджеты | модуль не читает `budget_gate`/`flags.budgets_enabled`; effective master OFF во всех 3 чатах; лимиты — только явные `memory.experience_semantic_*` (12/180/6/50) |
| отсутствие потери/дублирования/систематического пропуска | курсор монотонен; `mca_experience_episodes` 2 105/2 105, `mca_experience_feedback` 1 355/1 355 — 0 дублей; ≤600 строк за прогон; CHAT_C1 (2 407 127) и CHAT_DM8 (2 407 145) дренированы до MAX(id), pending 0 |

Открыто: с 06:04 провайдер `nano-gpt.com` периодически отдаёт `empty content`/таймауты, поэтому последние два тика дренаж не продвинулся (внешняя доступность, не код); строки не потеряны, job завершается `completed`, повтор следующим проходом. Повторный успешный проход после отказа в окне не наблюдался.

## SXR-K3-01 — BOUND (6 строк)

| Клауза приёмки | Наблюдённый факт |
|---|---|
| сохранённые настройки/модели/ключи/промпты не перезаписаны | `bot_settings` 548 строк, `max updated_at=05:19:03.548386Z`; единственная обновлённая после деплоя строка — новая заводская `prompts.factcheck_subject_system_prompt` (len 2146); `models.llm_model_name` (11.11) и `llm_base_url`/`llm_fallback_*` (12.09/29.08) сохранили прежние даты; `CONFIG_MIGRATION_CUSTOM_PRESERVED` для `limits.chat_context_budget_tokens`, `models.image_base_url`, `models.image_model`; per-chat CHAT_C1 (11.11) и CHAT_DM8 (28.10) не менялись; ручное изменение владельца CHAT_C2 06:11:54 сохранено (`manual_edit`, `outcome=applied`, `reason=owner_edit`, actor=CHAT_DM8). Сохранность `keys.*`-строк следует из единственной обновлённой строки (таблицы `updated_at`) |
| исправления работают сразу после деплоя без OFF/SHADOW и ручного включения | `.env`, process env и unit `Environment=` — ни одного override для `BUDGETS_ENABLED`, `CHAT_UNKNOWN_MODEL_WINDOW`, `MCA_TOOL_*`, `TOOL_CHAIN_LIMITS_ENABLED`; factory `BUDGETS_ENABLED=true`, `TOOL_CHAIN_LIMITS_ENABLED=true`, `MCA_TOOL_*` caps=0; новых OFF/SHADOW-флагов SMART нет; исправления H3/H4/I1/I2 наблюдаемо работают в проде |
| техническая проблема не скрыта выключением функциональности | master OFF бюджетов — ранее сохранённое решение владельца (2026-10-25), а не отключение исправлений; функции релиза активны (см. H3/H4/I1/I2) |

Открыто: ничего по приёмке. Env-ключи (`.env`) отдельно не измерялись; деплой `git pull --ff-only` + рестарт `.env` не переписывает, DB-ключи `keys.*` покрыты наблюдением «единственная обновлённая строка».

## Гейты

- `check --stage deploy --candidate 0e4a144d…`: **exit 0, errors=0**
  (`gate-deploy-after-observability.txt`).
- `check --stage release --candidate 0e4a144d… --deployed-commit 0e4a144d…`: **exit 1, errors=117**;
  все ошибки одного класса — `mandatory not ['VERIFIED'] (got READY_FOR_LIVE)`
  (`gate-release-after-observability.txt`).
- Остаются не-VERIFIED (11 req_id): `SXR-A1-04`, `SXR-F2-01`, `SXR-F4-01`, `SXR-L1-01`, `SXR-L2-01`,
  `SXR-L3-01`, `SXR-L4-01`, `SXR-L5-01`, `SXR-L6-01`, `SXR-L7-01`, `SXR-L8-01`.
  Это harness/live-сценарии (`smart_live_canary.py` / `fc_live_canary.py`), live-factcheck, Telegram-доставка
  и trace-доказательства — отдельный assignment; батч их не выполнял.
- Не менялись: `SXR-M3-01`, `SXR-M4-01`, `SXR-M4-02` (уже VERIFIED, preprod), `SXR-A1-04`, `SXR-F2-01`,
  `SXR-F4-01`, все SFC-строки, корректирующая карта, `plans/progress_scope.json`, `plans/workflow_state.md`,
  `plans/current_task.md`, код и тесты.

Карта `requirements-map.json` на момент этой привязки содержала незакоммиченные изменения предыдущего
bulk-rebinding (candidate/deployed 0e4a144d); данный дельта-набор (59 строк) наложен поверх них и не откатывает их.
