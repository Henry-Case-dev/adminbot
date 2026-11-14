# SMART live canary (`smart_live_canary.py`)

Один standalone read-only harness для production-наблюдений по строкам
`READY_FOR_LIVE`, у которых остался только post-deploy evidence. Скрипт
**ничего не проверяет «вместо» карты требований**: он собирает наблюдённые
факты, а решение `VERIFIED` принимает Reviewer/PM по requirement map.

## Файл

`smart_live_canary.py` — самодостаточный Python 3.12+ скрипт. Использует
только stdlib и уже установленные зависимости проекта (`httpx`, `asyncpg`,
`aiosqlite`, `dotenv`, `psutil` и т.д.). Новые пакеты не нужны.

## Точная production-команда

DevOps копирует файл на сервер (deployed-дерево остаётся чистым):

```bash
scp smart_live_canary.py root@192.255.209.205:/tmp/smart_live_canary.py
```

Базовый прогон (без платных LLM-вызовов):

```bash
cd /var/www/admin_bot && venv/bin/python /tmp/smart_live_canary.py \
  --json-out /tmp/smart_live_canary.json
```

Полный прогон с двумя разрешёнными LLM-вызовами (чекап-отчёт и Direct L1):

```bash
cd /var/www/admin_bot && venv/bin/python /tmp/smart_live_canary.py \
  --allow-provider-calls --max-provider-calls 4 \
  --json-out /tmp/smart_live_canary.json
```

Офлайн-предпроверка (без сети; часть проверок честно скажет
`not_observed`, ошибок быть не должно):

```bash
cd /var/www/admin_bot && venv/bin/python /tmp/smart_live_canary.py \
  --offline --json-out /tmp/smart_live_canary.json
```

Dry-run/self-test (не трогают сеть/БД; можно запускать где угодно с
`--repo-path <deployed-tree>`):

```bash
venv/bin/python /tmp/smart_live_canary.py --dry-run --repo-path /var/www/admin_bot
venv/bin/python /tmp/smart_live_canary.py --self-test --repo-path /var/www/admin_bot
```

Дополнительно: `--checks a,b`, `--check-timeout SEC`, `--db-path PATH`,
`--checkup-unit admin_bot`, `--chat-id N`.

## Обязательные предпосылки production-прогона

1. `cwd = /var/www/admin_bot` (иначе `load_dotenv()` не увидит `.env`, а
   `--repo-path` по умолчанию равен cwd).
2. Запуск через `venv/bin/python` этого же дерева (импорт `config`/`services`
   идёт из deployed checkout; `--repo-path` вставляется в `sys.path`).
3. Доступны: `.env` (в т.ч. `POSTGRES_DSN`), `local_database.db`, каталог
   `.deploy/`, `systemctl`/`journalctl` и чтение журнала `admin_bot`.
4. Для journal-проверки харнесс синтезирует identity своего unit
   (`--checkup-unit`, по умолчанию `admin_bot`), потому что сам он не является
   процессом бота. Чтение — тот же `journalctl --unit`, read-only.
5. Запуск от `root` допустим для DevOps, но проверка H3 смотрит пользователя
   **процесса бота** (`/proc/<MainPID>/status`), а не харнесса.

## Что именно проверяется (check → requirement ids)

| # | check id | req ids | Наблюдаемый факт |
|---|----------|---------|------------------|
| 1 | `effective_config` | SXR-L1-01, SXR-K3-01 | master budgets (global + все реальные чаты), отсутствие env-enforcement, `MCA_TOOL_MAX_*`/fuse, legacy + async provider-catalog capacity для модели чата |
| 2 | `control_loop_off` | SXR-L1-01 | реальный `ToolRouter` + `chat_with_tools`: 5 LLM-раундов, 7 вызовов, 3 в одном раунде, каждый получил `role:"tool"`-результат, cap-скипов нет; сеть заблокирована на время сценария |
| 3 | `caps_on_and_override` | SXR-L1-01 | in-memory budgets ON: заводские `0`-политики не режут; операторский override даёт `chain_call_limit`/`same_call` со структурным результатом на каждый вызов; значения восстановлены |
| 4 | `evidence_payload` | SXR-L2-01 | 13 500 симв. несекретного источника под реальную ёмкость L2: доставлено целиком, хвостовой маркер сохранён, 3 связанных источника; при cap 900 — честная обрезка без «полного прочтения» |
| 5 | `capacity_scenarios` | SXR-L3-01 | 8 сценариев: current / <1M / >1M / unknown custom / switch / fallback / catalog-unavailable (in-memory инъекция) / context-overflow; source/confidence; 1M не выдаётся за verified |
| 6 | `local_source_read` | SXR-L4-01 | `read_source_code` читает `services/tool_loop.py`: local+verified, `network_calls=0`, repo/commit/path == deployed SHA, git HEAD и `.deploy/release.json` совпадают |
| 7 | `external_reads` | SXR-F2-01, SXR-F4-01, SXR-L5-01 | публичный GitHub-файл реально прочитан по сети; loopback/169.254.169.254 заблокированы (tool path + прямой `SafeFetcher`, stage=resolve); 404 отдан фактической причиной |
| 8 | `diagnostic_variants` | SXR-L6-01 | 7 вариантов на одном `chat_with_tools` (все источники / один отказ / GitHub blocked+local / local down+remote / исследование невозможно / финальный LLM недоступен / technical deadline): данные сохранены, бессмысленная заглушка не публикуется |
| 9 | `checkup_real` | SXR-H3-01, SXR-H4-01, SXR-L7-01 | реальный journal unit, `MainPID` не root, `deploy.identity` (`verified_deployed`), `.deploy/release.json` ↔ git ↔ процесс, `DiagnosticCollector.collect_for_checkup` и (при разрешении) `CheckupService.checkup` |
| 10 | `direct_continuation` | SXR-L7-01 | L1 Planner (`prompts.direct_l1_planner_system_prompt`) на двух независимых формулировках: решение LLM (`capabilities_needed`), затем фактический read-only tool-вызов; без обязательных слов-маркеров |
| 11 | `i1_spool` | SXR-I1-01 | read-only SQLite: журнал `meme_initiative_attempt`, последняя попытка, spool `*.attempts.pending.jsonl` (0 строк = дренаж), маркеры недоступности журнала в окне логов |
| 11 | `i2_stream` | SXR-I2-01 | durable job payload, cursor/scope по чатам, `semantic_progress_snapshot`, пересчёт lag `id > cursor`, backlog и терминальные drain-циклы |
| 12 | `k3_settings` | SXR-K3-01 | persisted `bot_settings` (кол-во/ключи/даты), `models.*` и `flags.budgets_enabled`, prompts без перезаписи после deploy, `chat_profiles` и counts override; фиксы не в OFF/SHADOW |
| 13 | `l8_rollup` | SXR-L8-01 | свод I1–I6 только из уже наблюдённых фактов; I3/I5/I6 честно `not_run`, если сценариев не было |

Каждая проверка возвращает `{id, req_ids, status, summary, details,
duration_s}`; `status` — `observed|not_observed|error`. Скрипт завершается
кодом 0, если он отработал; провал проверки остаётся в JSON.

## Жёсткие гарантии безопасности

- **Никакого Telegram I/O**: aiogram Bot/сообщения не создаются.
- **Конфигурация не пишется**: `PgDatabase.connect()` создаёт только пул;
  `ConfigCache._load_all()` выполняет SELECT'ы; DDL/сиды/миграции не
  запускаются. `ChatParamsCache` заполняется чтением.
- **SQLite только `mode=ro`** через существующий
  `DatabaseService.initialize_readonly()`.
- **Git-команды только читающие** (`rev-parse`, `log`, `status`); `status`
  может обновить служебный index-файл Git, но не меняет tracked-контент
  deployed-дерева.
- **Сценарии бюджета/каталога** — подмена функций/прокси только в памяти,
  восстановление в `finally`; после прогона значения сверяются.
- **Никаких destructive записей**. Production-пути (tool loop, router,
  `mca_events`, execution graph) эмитят только in-memory телеметрию: durable
  flush/sink БД в этом процессе не конфигурируется.
- **Секреты/chat_id**: значения ключей не читаются (кроме несекретных
  `models.llm_model_name/base_url` и `flags.budgets_enabled`); chat_id
  заменяются на `chat-<sha8>`, строки проходят redaction (bot-token, `sk-`,
  Bearer, абсолютные пути).
- **Платные вызовы** — только с `--allow-provider-calls`, не более
  `--max-provider-calls` (по умолчанию 4); при `--offline` — ноль.
- **Никаких фоновых циклов**: конечные проверки под `asyncio.wait_for`.

## Что харнесс НЕ доказывает (честные границы)

- Не отправляет сообщения в Telegram и не проверяет реальную доставку ботом;
  это остаётся отдельному контролируемому live-прогону.
- I3 (`lesson_rejected`), I5 (инциденты), I6 (событийный путь) в этом
  canary не исполняются как сценарии; L8 показывает их `not_run`. I4
  (`reason_codes`) читается read-only из `experience_pipeline_reasons`.
- Проверка №9 без `--allow-provider-calls` собирает факты/identity/manifest,
  но не строит финальный текст отчёта чекапа (это платный LLM-вызов).
- Проверка журнала использует синтезированную identity unit (`--checkup-unit`);
  если у процесса харнесса нет прав на journal, статус будет `not_observed`
  с причиной, а не «ошибок нет».
- `SXR-F4-01` в части «естественный пользовательский запрос в Telegram»
  требует live-чата; здесь проверяется тот же `read_source_code`-путь на
  реальном публичном репозитории.
- Наблюдённый `observed` — не `VERIFIED`: строка карты закрывается только
  после независимой проверки Reviewer и фиксации evidence.
- Повторный прогон безопасен, но числа (`recent_jobs`, spool, lag) зависят от
  момента; сравнивать нужно отчёт против отчёта, а не против ожидаемых
  «красивых» значений.

## Чтение результата

- `summary.observed/not_observed/error` — счётчики проверок.
- `details.assertions[]` — конкретные ожидания с `ok=true/false`.
- `details.exception` — только для `status=error`.
- JSON пишется атомарно в `--json-out`; путь затем копируется в
  `plans/features/smart-execution-reliability-01/evidence/postdeploy/live/`
  как durable evidence (сам harness ничего в репозиторий не пишет).

## Локальная проверка (автор/CI)

```bash
python -m py_compile smart_live_canary.py
python smart_live_canary.py --dry-run --repo-path <deployed-or-release-tree>
python smart_live_canary.py --self-test --repo-path <deployed-or-release-tree>
```

`--self-test` — офлайн, без БД/сети/провайдера: проверяет tool-loop
(раунды/вызовы/последовательность/капы), evidence pack с хвостом и честной
обрезкой, capacity-резолвер (unknown ≠ verified, overflow), два
finalization-варианта и redaction. Ненулевой код возврата означает, что
сломан сам харнесс.
