# Production recon — SMART-EXECUTION-RELIABILITY-01

- Дата: 2026-11-14 (локальная), сервер UTC `2026-11-13 12:33–12:38`.
- Хост: `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`.
- Режим: **только чтение**. Код, настройки, сервис и БД не менялись; сообщений
  в чаты не отправлялось; платных LLM-вызовов не было.
- SSH: 3 коротких сессии (1 прервана локальным лимитом вывода после
  identity/journal-чтения, 1 основная, 1 короткая контрольная). Параллельных
  коннектов не было; секреты не печатались.
- Редакция: chat id заменены на `CHAT_C1`, `CHAT_C2`, `CHAT_DM`.
- Итог: identity, effective configuration, trace чекапа, причина SafeFetch,
  I2 и I4 доказаны. По I1 точное сообщение SQLite отсутствует в журнале —
  граница доказанного зафиксирована ниже.

## 1. Deployed identity

| Поле | Значение |
|---|---|
| HEAD | `d20a7f730715ba9e9cba7673c0557794979be339` |
| Branch / upstream | `release/2.58.199` / `origin/release/2.58.199`, ahead/behind `0/0` |
| Рабочее дерево | dirty только `?? .cache/` (tracked/staged чисто) |
| `APP_VERSION` | `2.58.199` (`config/settings.py`) |
| Сервис | `active (running)`, старт `2026-11-13 08:36:18 UTC`, PID `454989` |
| InvocationID | `b186b2f407c0421982951ebc63e37313` (systemd = process env) |
| Пользователь unit | `adminbot`; `Group` не задан (фактически `adminbot`); `EnvironmentFile=/var/www/admin_bot/.env` |
| `/healthz` | `200` `{"status":"ok","version":"2.58.199"}`, 2 мс |
| `.deploy/release.json` | schema 1: `deployed_sha=d20a7f73…`, `version=2.58.199`, `effect=deploy`, `deployed_at=2026-11-13T08:36:16.759775Z`, `previous_sha=null`, `release_branch=release/2.58.199`, `dirty_tracked=false` |
| Схема SQLite | `user_version=47`, `journal_mode=wal`, `page_count=686546` (~2.81 ГБ), `freelist_count=0` |

**Lineage (важно для следующих этапов):** `release/2.58.199` не является
предком `master`: расхождение `master...release/2.58.199` = `377 / 1446`
коммитов, merge-base `3193b657`. То есть на `master` нет кода 2.58.199,
который реально работает в production. Новая работа по эпику должна
ответвляться от release-линии (или сначала интегрировать её), иначе
исправления 2.58.199 будут потеряны. Это факт для Orchestrator, здесь ничего
не менялось.

## 2. Effective configuration

Источники: PG `bot_settings` (global), PG `chat_profiles.chat_params.overrides`
(per-chat), `config/settings.py` (factory), env unit/.env/process.

### Бюджеты

| Слой | `flags.budgets_enabled` |
|---|---|
| Global | **false** (обновлено `2026-10-25T06:13:07Z`) |
| `CHAT_C1` | **false** (override, `2026-11-13T11:07:51Z`) |
| `CHAT_C2` | **false** (override, `2026-11-11T13:14:05Z`) |
| `CHAT_DM` | override отсутствует → global **false** |
| Factory | `BUDGETS_ENABLED=true` |
| **Effective (все три чата)** | **false** |

То есть бюджеты выключены и глобально, и в обоих групповых чатах; в DM
действует global false.

### Модель и провайдер

| Ключ | Global | Per-chat overrides | Effective |
|---|---|---|---|
| `models.llm_model_name` | `z-ai/glm-5.3-flash-uncensored` (`2026-11-11T12:04:22Z`) | нет | **`z-ai/glm-5.3-flash-uncensored`** |
| `models.llm_base_url` | `https://nano-gpt.com/api/v1` | нет | **NanoGPT** |
| `models.llm_provider` | записи нет | нет | провайдер выводится из host base_url → `nanogpt` |
| `models.llm_fallback_model` | `deepseek-flash` | нет | hot-слой `deepseek-flash`; env `LLM_FALLBACK_MODEL=deepseek-v4-flash` |
| `models.llm_fallback_base_url` | `https://api.deepseek.com` | нет | `https://api.deepseek.com` |

Побочное наблюдение: `models.llm_display_name` всё ещё `"NanoGPT Deepseek"`
— устаревшая подпись после смены модели на GLM; на поведение не влияет.

### Ёмкость контекста (`CHAT_UNKNOWN_MODEL_WINDOW`)

| Что | Значение |
|---|---|
| env unit/process/.env | ключ отсутствует |
| `settings.CHAT_UNKNOWN_MODEL_WINDOW` | **16384** (factory) |
| Фактический runtime-путь | синхронный `resolve_model_context_window()` → **`[16384, "unknown_fallback"]`**, WARN `model_capacity: unknown model 'z-ai/glm-5.3-flash-uncensored' — conservative window=16384` |
| Расширенный async-резолв (`resolve_capacity`, NanoGPT catalog) | `effective_context_window=1048576`, `max_output_tokens=32768`, `source=provider_catalog`, `confidence=verified`, `fallback_used=false` |
| Кэш | процесс-локальный `_WINDOW_CACHE`; WARN печатается один раз на модель в процессе |

Вывод: чат-путь реально использует **16384**, хотя каталог провайдера
подтверждает **1 048 576**. Это не догадка: WARN возник в том же trace
(`09:42:55.624`), а async-резолв того же имени модели дал `provider_catalog`.

### SELF-DIAG

| Параметр | Значение |
|---|---|
| `SELF_DIAG_LOCAL_REPO_ROOT` | `""` (env нет) → локальный провайдер выключен, чтение идёт в GitHub |
| `flags.self_diag_repo_origin` | PG-записи нет → factory `Henry-Case-dev/adminbot` |
| `resolve_self_repo_identity()` | repo `Henry-Case-dev/adminbot`, ref `d20a7f73…`, `ref_source=deployed_sha`, `deployed_sha == checkout_sha`, `local_source_verification=verified_deployed`, `dirty=false` |
| `deploy_identity.collect_identity()` в отдельном процессе | `code=unavailable`, sources только `runtime_app_version` — ожидаемое ограничение standalone-запуска; в самом чекапе identity-лог: `deployed_sha=checkout_sha=d20a7f730715`, `source_verified=True`, `sources=12/15`, `status=degraded` |

### Tool-chain лимиты

`TOOL_CHAIN_LIMITS_ENABLED` отсутствует в unit/process/.env →
`settings.TOOL_CHAIN_LIMITS_ENABLED=true` (factory). Лимиты действуют
независимо от `flags.budgets_enabled=false`:
`TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2`, `TOOL_MAX_TOTAL_CALLS=6`,
`TOOL_CHAIN_TIMEOUT_SECONDS=360`, `_TOOL_MAX_SAME_CALL=2`,
`TOOL_CHAIN_MAX_METERED_CALLS=4`.

## 3. Воспроизведение чекапа `checkup:3f9bd22a592e4532a3790051cb87e320`

Окно: `2026-11-13 09:42:49–09:43:08 UTC` (журнал 1018 строк за 09:35–09:50).

| Время (UTC) | Событие |
|---|---|
| 09:42:49.039 | `[checkup] triggered | chat=CHAT_DM` |
| 09:42:49.226 | identity: `runtime=`, `deployed_sha=checkout_sha=d20a7f730715`, `source_verified=True`, `git_meta=True`, `commits_since_deploy=None`, `sources=12/15`, `status=degraded` |
| 09:42:55.597 | `TOOL_PLAN_CREATED` tools=`inspect_runtime,read_source_code` |
| 09:42:55.621 | `inspect_runtime` ok, out_chars=8905 (`incidents.investigate_incident`, status=degraded) |
| 09:42:55.624 | `model_capacity: unknown model … window=16384` |
| 09:42:55.936 | `safe_fetch` ERROR: `destination_blocked`, stage=`connect`, retryable=false (первый read_source_code) |
| 09:42:55.942 | `tool_call` failed `destination_blocked`, out_chars=1478 |
| 09:43:00.916 | round 2 `inspect_runtime` ok, 1940 chars |
| 09:43:01.153 | повторный `safe_fetch` ERROR `destination_blocked` stage=connect |
| 09:43:01.160 | второй `read_source_code` failed |
| 09:43:03.696/700 | round 3: два `inspect_runtime` ok (4049 и 6691 chars) |
| 09:43:08.049 | `[tools] chain limit | reason=chain_call_limit | unit=calls | scope=chain | value=6 | tool=inspect_runtime | round=4 | total_calls=6 | metered_calls=2` |
| 09:43:08.049 | вызов отклонён: `tool_call … reason_code=tool_step_limit`, `error_code=chain_call_limit` |
| 09:43:08.049 | `[tools] degraded | reason=chain_call_limit | rounds_used=4 | lost_rounds=0 | tools=inspect_runtime,read_source_code | partial_chars=87` |
| 09:43:08.165 | `[checkup] report sent`; `report_chars=87`, `research_calls=7`, `research_rounds=4`, `research_degraded=true`, `research_reason=chain_call_limit`, `latency_ms=18791`, `bundle_status=degraded`, `sources=15`, `not_checked=25` |

Фактически отправленный текст (durable `mca_bot_outputs` id=1661,
`output_kind=checkup_report`, `delivery_status=delivered`, chat `CHAT_DM`,
`tg_message_id=222`, тот же correlation_id):

> «Чет долго думал, аж перегрелся - и всё равно ни к чему не пришёл. Спроси проще, что ли»

**Что присутствует:** все шаги tool-loop, оба отказа SafeFetch, лимит,
деградация, телеметрия и точный финальный текст.
**Чего нет:** сырого traceback/peer-адреса SafeFetch (в журнале только
`code/stage/retryable`), поэтому причину пришлось воспроизводить отдельно;
точный LLM-ответ (только `report_chars`); отдельной строки, объединяющей
`total_calls=6` и `rounds_used=4`, нет — эти числа в двух соседних строках.

## 4. SafeFetch/GitHub — доказанная причина

Диагностика выполнена из deployed venv (`/var/www/admin_bot/venv/bin/python`,
uid `adminbot`, cwd `/var/www/admin_bot`) через существующий код
`services.safe_fetch`; без curl и без отключения защит.

| Наблюдение | Значение |
|---|---|
| Proxy env | пусто (`PROXY_ENV {}`) |
| `getaddrinfo(api.github.com, 443)`, 3 запроса | `AF_INET:140.82.114.6`, `AF_INET:140.82.114.6`, `AF_INET:140.82.113.5` (только IPv4, AAAA нет) |
| `guarded_target(...)` resolved | `["140.82.114.5"]` |
| TLS к `140.82.114.5` | peer `140.82.114.5`, TLSv1.3, сертификат `*.github.com` — валиден |
| Реальный peer httpx-соединения | **`140.82.112.6:443`** |
| Проверка `peer_allowed` | `validated=false` |
| Итог `SafeFetcher.fetch` | `SafeFetchError code=destination_blocked stage=connect reason="actual peer address not validated" retryable=false` |

Причина: `aguarded_target()` резолвит host **один раз** и сохраняет один
снимок A-записей; GitHub отдаёт несколько A-записей с ротацией, и фактическое
TCP-соединение уходит на другой edge-IP (`140.82.112.6`) из того же GitHub.
Anti-rebinding проверка сравнивает peer с устаревшим снимком и отклоняет
легитимное соединение. Это не proxy, не IPv6 и не блокировка egress.
Отказ интермиттирующий и зависит от момента DNS-ответа.

## 5. Доступ к журналу

```
sudo -u adminbot journalctl -u admin_bot -n 20 --no-pager   # rc=0
```
Invocation в логе совпадает с текущим (`b186b2f4…`). Чекап читает журнал
через свой `system_logs_fetcher` (journalctl + `_SYSTEMD_INVOCATION_ID`).

## 6. I1 — `[meme] attempt spooled … error=OperationalError`

Наблюдённые эпизоды 13.11.2026 UTC: `02:26`, `06:13`, `06:28`, `09:36–09:37`,
`09:47`, `10:38`, `11:36–11:38`; каждый — `attempt spooled` и через ~5 с
`attempt spool not drained | failed=1..3`. Пример:

```
09:36:44.601 [meme] attempt spooled (journal unavailable) | attempt=266639345caf | error=OperationalError
09:36:49.612 [meme] attempt spool not drained (journal unavailable) | failed=1
```

Код (`services/meme_initiative.py`) логирует только
`type(last_error).__name__`; **текст и traceback SQLite не пишутся** — это и
есть главный недостающий факт.

Состояние БД/носителей (read-only):

- таблица `meme_initiative_attempt` существует: 28 678 строк,
  `MIN(ts)=2026-10-31T12:42:03Z`, `MAX(ts)=2026-11-13T12:31:21Z`;
  за 7 дней: `considered/passed` 10 733, `skipped/cooldown_active` 5 598,
  `skipped/daily_quota_reached` 4 172, `published/sent` 42;
- spool-файл `local_database.db.attempts.pending.jsonl` **отсутствует**
  (0 строк) — на момент проверки очередь пуста; были ли слиты именно
  spooled-строки, не доказано (нужно сверять attempt_id);
- `PRAGMA quick_check(1)` → `ok`; `journal_mode=wal`; `freelist_count=0`;
- один процесс (`python`, PID 454989) держит 3 handle БД; WAL ~11.5 МБ;
- права: БД `adminbot:adminbot 640`, каталог и БД доступны сервису на запись
  (`service_write_db_rc=0`); диск: 32 ГБ свободно (67% занято), inode 3%;
- `dmesg`: ошибок I/O/ext4/read-only не найдено.

Доказано: intermittent-сбой записи в `meme_initiative_attempt` при живом
journal-пути; fallback-spool сработал. Не доказано: конкретное исключение
(`database is locked` vs иное) — в журнале его нет; также не проверено
побайтовое восстановление spooled-строк.

## 7. I2 — `experience.fresh_stream_lag`

Последний durable job `experience.review:global` (id `4a347a37…`, completed
`2026-11-13T12:21:36Z`, attempt 1, max 3; очередь не пуста: 0 running):

| Поле | Значение |
|---|---|
| `semantic_pending[CHAT_C1]` | **14 399** |
| `semantic_pending_since[CHAT_C1]` | `2026-08-15T21:24:21Z` |
| `semantic_cursor:CHAT_C1` | **12 992** |
| `semantic_watermark` | 2 405 380 |
| `smart_messages.MAX(id)` для `CHAT_C1` | 2 405 456 |
| Строк после курсора | **2 059 418** |
| `semantic_progress.lag_seconds` | 7 743 420 (~89.6 дней) |
| `CHAT_C2`, `CHAT_DM` | pending 0, курсор = max(id) |

Курсор **двигается**: в журнале `cursor_rowid` растёт ровно на 50 за прогон
(12 236 → 12 291 → … → 12 941 → 12 992), прогон — примерно каждые 15 минут.
`SEMANTIC_PER_CHAT_MAX=50`, окно читается `WHERE chat_id=? AND id > cursor
ORDER BY id LIMIT 50` — то есть **самые старые** строки. При объёме чата
~7 200 строк/сутки и потолке ~4 800 строк/сутки отставание не сходится, а
2 059 418 строк при 50 за прогон — практически негасимый backlog.

Событие `lag_rows=14 399` считает `semantic_pending` (обнаруженные, но не
обработанные строки), а не дистанцию до `max(id)`. Сигнал не ложный, но
семантика поля уже, чем фактическое отставание. Планировщик исправен: job
завершается `completed`, без ошибок, retry не нужен.

## 8. I4 — unmapped reason codes

Подтверждено в `mca_events` (и в журнале):

| event | reason_code в строке | producer-код | sha256[:8] |
|---|---|---|---|
| `experience.fresh_stream_lag` | `unmapped:18d14796` | `fresh_stream_lag` | `18d14796` |
| `detector_scan` | `unmapped:4f8aced7` | `detector_scan` | `4f8aced7` |

Оба кода отсутствуют в `REASON_CODES` (`services/mca_events.py`), механизм
`unmapped:<sha8>` работает как задумано. Дополнительно в проде видны другие
unmapped-маркеры (`detector_signal a999e0fd`, `factcheck_temporal 373cf2f7`,
`COVER_LIMIT_UNKNOWN d07c353d`, `experience.archive_direction_selected
69e80269`, `experience.archive_coverage 38dc4799`, `humor_samples_selected
54c94ee2`) — расхождение реестра шире двух кодов владельца. Для этих
дополнительных маркеров producer-строка не декодирована (их sha8 не совпал с
именем события), поэтому они зафиксированы как наблюдение, без вывода.

## 9. Итог: доказано / не доказано

Доказано:
1. Production = `d20a7f73` / `2.58.199`, manifest и checkout совпадают,
   сервис здоров, schema 47, журнал доступен сервисному пользователю.
2. Effective budgets = false во всех трёх чатах; tool-chain лимиты при этом
   активны (env default true).
3. Модель `z-ai/glm-5.3-flash-uncensored` через NanoGPT, без chat-override;
   fallback `deepseek-flash` / `api.deepseek.com`.
4. Чат-путь ёмкости реально берёт 16 384 (`unknown_fallback`), каталог даёт
   1 048 576 (`provider_catalog`).
5. Полный trace чекапа и точный финальный текст-заглушка.
6. Причина SafeFetch: peer `140.82.112.6` не входит в единичный снимок
   `["140.82.114.5"]`.
7. I2: реальный backlog, курсор +50/прогон, 2 059 418 строк после курсора.
8. I4: оба кода — producer-имена событий, отсутствующие в реестре.

Не доказано / отсутствует:
1. Точное SQLite-исключение I1 (код логирует только класс).
2. Судьба конкретных spooled-строк (файл пуст; сверка attempt_id не делалась).
3. Табличное число таблиц SQLite в первой сессии — `sqlite3` CLI на сервере
   отсутствует; `user_version` получен через Python.
4. `deploy_identity.collect_identity()` в standalone-процессе даёт
   `unavailable`; identity подтверждена in-process логом чекапа и
   `resolve_self_repo_identity()`.
5. Декодирование дополнительных unmapped-маркеров (кроме двух кодов владельца).

## 10. Безопасные ближайшие наблюдения (без изменений)

- Повторить SafeFetch-проверку в разное время: при совпадении снимка и peer
  отказ исчезает — это подтвердит DNS-ротацию как единственную причину.
- Снять `attempt_id` из следующих `attempt spooled` и проверить их наличие в
  `meme_initiative_attempt` после дренажа — закроет вопрос потерь I1.
- Через один прогон `experience.review` зафиксировать дельту курсора и
  `pending` — подтвердит скорость роста backlog (ожидаемо +50 / ~+150).
- Проверить `mca_events` на отсутствие новых unmapped-кодов после правки
  реестра (когда она появится).

## Evidence

- `evidence/production-recon-2026-11-14/identity-and-config.txt`
- `evidence/production-recon-2026-11-14/settings-layers.txt`
- `evidence/production-recon-2026-11-14/checkup-trace.txt`
- `evidence/production-recon-2026-11-14/safefetch-diagnostic.txt`
- `evidence/production-recon-2026-11-14/db-jobs.txt`
- `evidence/production-recon-2026-11-14/fs-spool.txt`
