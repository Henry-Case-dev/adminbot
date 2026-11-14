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

Предпочтительно запускать **закоммиченный файл из самого deployed/release
дерева**, чтобы JSON имел `harness_identity.tracked=true` и
`blob_matches_head=true`:

```bash
cd /var/www/admin_bot && venv/bin/python \
  plans/features/smart-execution-reliability-01/evidence/postdeploy/live/harness/smart_live_canary.py \
  --json-out /tmp/smart_live_canary.json
```

Если файл копируется на сервер отдельно (deployed-дерево не меняем), хэш
обязателен к фиксации: `--expect-harness-sha256 <sha256 закоммиченной копии>`.
В JSON `harness_identity.tracked=false` и note явно скажет, что копия вне
Git; такую копию нельзя выдавать за candidate-bound evidence без сверки
sha256 с коммитом.

```bash
scp smart_live_canary.py root@192.255.209.205:/tmp/smart_live_canary.py
```

Базовый прогон (без платных LLM-вызовов):

```bash
cd /var/www/admin_bot
HARNESS=plans/features/smart-execution-reliability-01/evidence/postdeploy/live/harness/smart_live_canary.py
venv/bin/python "$HARNESS" --json-out /tmp/smart_live_canary.json
```

Полный прогон с двумя разрешёнными LLM-вызовами (чекап-отчёт и Direct L1):

```bash
cd /var/www/admin_bot && venv/bin/python "$HARNESS" \
  --allow-provider-calls --max-provider-calls 4 \
  --json-out /tmp/smart_live_canary.json
```

Офлайн-предпроверка (без сети; часть проверок честно скажет
`not_observed`, ошибок быть не должно):

```bash
cd /var/www/admin_bot && venv/bin/python "$HARNESS" \
  --offline --json-out /tmp/smart_live_canary.json
```

Dry-run/self-test (не трогают сеть/БД; запускать из deployed/release-дерева
или указать `--repo-path`):

```bash
cd /var/www/admin_bot
venv/bin/python "$HARNESS" --dry-run
venv/bin/python "$HARNESS" --self-test --offline
```

Self-test обязан исполняться на deployed-классах 2.58.200: перед проверками
он сверяет, что `config.settings`/`services.tool_loop`/`services.direct_execution`/
`services.model_capacity` импортированы из указанного дерева и что у
`CapacityResult` есть `as_window_meta`. Чужой/устаревший checkout даёт
явный `BLOCKED`-отказ без traceback, а не ложный PASS.

## Версия, self-hash и привязка к candidate

Harness `smart-live-canary/2`, `HARNESS_VERSION=1.2.0` (r2: defensive
`budgets_enabled`, provenance-aware `k3_settings`, `external_reads` доказывает
verified-файл исходника и отказ tool-path без сети). Каждый JSON-прогон
содержит:

- `harness_sha256` — sha256 самого исполняемого файла, посчитанный в рантайме;
- `harness_identity` — путь, sha256, Git-репозиторий/ветка/HEAD файла,
  `tracked`, `blob_matches_head`, `dirty_vs_head` и предупреждение, если
  файл не закоммичен;
- `repo` — корень deployed-дерева, `head`, `branch`, `origin`,
  `app_version`, `manifest_present`, распакованный `.deploy/release.json`,
  `clean_tracked`/`dirty_tracked`.

Перед evidence-прогоном harness должен быть закоммичен: `tracked=true` и
`blob_matches_head=true`. Если файл untracked или рабочая копия отличается
от HEAD, JSON честно пишет это в `harness_identity.note`, и такой прогон
нельзя выдавать за candidate-bound evidence. Для воспроизводимости можно
зафиксировать ожидаемый хэш:

```bash
venv/bin/python /tmp/smart_live_canary.py \
  --expect-harness-sha256 <sha256> --offline --json-out /tmp/selfcheck.json
```

Несовпадение хэша — выход 2 до запуска проверок. Production-прогон должен
показывать `repo.head` = deployed SHA, `repo.app_version` = `2.58.200`,
`manifest.deployed_sha` = тому же SHA; все три поля входят в JSON.

Документированная версия `HARNESS_VERSION=1.2.0` имеет
`sha256=21c7ac74dbe139d9784168b93cb0a1a6c7fb7f18c1e17f7aa497d6d12fffd820`
(именно это значение передаётся в `--expect-harness-sha256`).

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
| 1 | `effective_config` | SXR-L1-01, SXR-K3-01 | master budgets (global + все реальные чаты) по фактическому ключу deployed-резолвера `budgets_enabled` с источником значения, отсутствие env-enforcement, `MCA_TOOL_MAX_*`/fuse, legacy + async provider-catalog capacity для модели чата; неизвестная форма резолвера → честный провал с наблюдаемыми ключами (не `KeyError`) |
| 2 | `control_loop_off` | SXR-L1-01 | реальный `ToolRouter` + `chat_with_tools`: 5 LLM-раундов, 7 вызовов, 3 в одном раунде, каждый получил `role:"tool"`-результат, cap-скипов нет; сеть заблокирована на время сценария |
| 3 | `caps_on_and_override` | SXR-L1-01 | in-memory budgets ON: заводские `0`-политики не режут; операторский override даёт `chain_call_limit`/`same_call` со структурным результатом на каждый вызов; значения восстановлены |
| 4 | `evidence_payload` | SXR-L2-01 | 13 500 симв. несекретного источника под реальную ёмкость L2: доставлено целиком, хвостовой маркер сохранён, 3 связанных источника; при cap 900 — честная обрезка без «полного прочтения» |
| 5 | `capacity_scenarios` | SXR-L3-01 | 8 сценариев: current / <1M / >1M / unknown custom / switch / fallback / catalog-unavailable (in-memory инъекция) / context-overflow; source/confidence; 1M не выдаётся за verified |
| 6 | `local_source_read` | SXR-L4-01 | `read_source_code` читает `services/tool_loop.py`: local+verified, `network_calls=0`, repo/commit/path == deployed SHA, git HEAD и `.deploy/release.json` совпадают |
| 7 | `external_reads` | SXR-F2-01, SXR-F4-01, SXR-L5-01 | публичный GitHub реально прочитан по сети: (а) README — сеть + repo/commit/path identity и честный `verified=false` (по контракту SourceReader V1 `verified` выдаётся только файлу исходника, `source_kind=file`); (б) файл исходника `octocat/Spoon-Knife@main:index.html` — `verified=true`, kind=file, commit/path; (в) loopback/169.254.169.254 отклонены tool-path'ом ДО сети (`network_calls=0`; `read_source_code` — provider-scoped GitHub-инструмент, поэтому причина `unsupported/provider_unconfigured`, detail=host_not_supported); (г) прямой `SafeFetcher` — `destination_blocked`/`metadata_endpoint_blocked`, stage=resolve; (д) 404 отдан фактической причиной |
| 8 | `diagnostic_variants` | SXR-L6-01 | 7 вариантов на одном `chat_with_tools` (все источники / один отказ / GitHub blocked+local / local down+remote / исследование невозможно / финальный LLM недоступен / technical deadline): данные сохранены, бессмысленная заглушка не публикуется |
| 9 | `checkup_real` | SXR-H3-01, SXR-H4-01, SXR-L7-01 | реальный journal unit, `MainPID` не root, `deploy.identity` (`verified_deployed`), `.deploy/release.json` ↔ git ↔ процесс, `DiagnosticCollector.collect_for_checkup` и (при разрешении) `CheckupService.checkup` |
| 10 | `direct_continuation` | SXR-L7-01 | L1 Planner (`prompts.direct_l1_planner_system_prompt`) на двух независимых формулировках: решение LLM (`capabilities_needed`), затем фактический read-only tool-вызов; плюс реальный remainder/cursor и дочитывание следующего диапазона |
| 11 | `i1_spool` | SXR-I1-01 | read-only SQLite: журнал `meme_initiative_attempt` (агрегат, >0 строк, последняя попытка с outcome/reason_code), spool `*.attempts.pending.jsonl` (0 строк = дренаж), читаемое journal-окно и маркеры недоступности |
| 11 | `i2_stream` | SXR-I2-01 | durable job payload, cursor/scope по чатам, `semantic_progress_snapshot`, пересчёт lag `id > cursor`, backlog и терминальные drain-циклы |
| 12 | `k3_settings` | SXR-K3-01 | persisted `bot_settings` (кол-во/ключи/даты), `models.*` и `flags.budgets_enabled` (значение + дата записи против deploy-снимка), prompts без перезаписи после deploy, `chat_profiles` и counts override; изменение профиля после deploy-снимка допустимо ТОЛЬКО с провенансом (`prompt_activations` kind=manual_edit/… или `chat_lore_history` field=chat_params с `changed_by`), запись релиза/миграции без следа проваливает проверку; фиксы не в OFF/SHADOW |
| 13 | `l8_rollup` | SXR-L8-01 | свод I1–I6 только из уже наблюдённых фактов; I3/I5/I6 честно `not_run`, если сценариев не было |

Каждая проверка возвращает `{id, req_ids, status, evidence_class,
evidence_reason, production_observed, summary, details, duration_s}`.
`status` — `observed|not_observed|error`, `evidence_class` —
`plumbing|production|unavailable`.

## Классы доказательности (жёсткий контракт)

| evidence_class | Значение | Может ли дать `observed` |
|---|---|---|
| `production` | Реальный production-источник/путь: provider/сеть, PG, systemd-journal, deployed-файлы, реальный LLM-вызов | Да |
| `plumbing` | Production-код исполнен, но LLM/роутер/вход подменены харнессом или данные синтетические | **Нет** |
| `unavailable` | Нужный production-источник в этом окружении отсутствует (offline, нет PG/SQLite/systemd/provider) | **Нет** |

`status=observed` разрешён только при `evidence_class=production`; это
принудительно проверяется в раннере, а не только декларируется. Проверка,
исполненная на scripted-двойниках или синтетическом входе, возвращает
`not_observed` даже при полностью зелёном контракте и явно пишет
`plumbing_pass=true` в `details`. Поэтому offline-прогон никогда не
показывает `observed` и не маскирует отсутствие production-источника.

| check id | evidence_class | Что именно доказывает production-прогон |
|---|---|---|
| `effective_config` | production (иначе unavailable) | реальные env/settings + read-only PG `bot_settings`/`chat_profiles`, master OFF во всех чатах |
| `control_loop_off` | plumbing | контракт production `chat_with_tools`, но LLM scripted → production-путём не считается |
| `caps_on_and_override` | plumbing | in-memory подмена budgets/settings, scripted LLM |
| `evidence_payload` | plumbing | production `build_evidence_pack` на синтетическом источнике |
| `capacity_scenarios` | production онлайн / unavailable offline | реальный resolver + provider-каталог; один сценарий каталога инъецируется in-memory |
| `local_source_read` | production только при verified deployed identity | реальный `read_source_code` по deployed-дереву, `network_calls=0`, commit/path == deployed SHA |
| `external_reads` | production онлайн / unavailable offline | реальный публичный GitHub-read по сети (README + verified файл исходника) + реальный `SafeFetcher` SSRF-полиси и отказ tool-path без сетевого вызова |
| `diagnostic_variants` | plumbing | 7 вариантов production tool-loop с контролируемыми LLM/роутером |
| `checkup_real` | production при реальном journal / иначе unavailable | systemd unit, `MainPID`, `deploy.identity`, manifest ↔ git ↔ процесс, реальный отчёт чекапа (при provider) |
| `direct_continuation` | production при реальном provider call / иначе unavailable | решение LLM + реальный tool-вызов; плюс реальный remainder/cursor и дочитывание следующего диапазона |
| `i1_spool` | production при реальных SQLite-строках / иначе unavailable | журнал попыток, последняя попытка с `outcome/reason_code`, spool, journal-окно |
| `i2_stream` | production при реальном durable payload / иначе unavailable | durable cursor/scope, backlog, пересчёт lag, терминальные drain-циклы |
| `k3_settings` | production при PG / иначе unavailable | persisted настройки/модели/prompts не перезаписаны; post-deploy правки профиля атрибутированы провенансом владельца |
| `l8_rollup` | production только если I1 и I2 production+observed | свод без нового поведения |

Пустой/недоступный источник не даёт `observed`: `effective_config`,
`k3_settings` без PG, `i1_spool` без строк, `i2_stream` без durable payload,
`checkup_real` без journal, `external_reads` без сети и
`direct_continuation` без provider-вызова честно уходят в
`not_observed + unavailable`.

### Continuation-контракт (не заглушка)

`direct_continuation` больше не содержит безусловного `True`. Проверка
читает заведомо большой `services/tool_router.py` через production
`read_source_code`, требует:

1. `truncation.truncated=true`, `retrievable_remainder_lines > 0` и
   `next_line_start > line_range[1]`;
2. реальный второй read с `line_start=next_line_start`, у которого
   `status=ok`, `snippet_chars>0` и `line_range[0] == next_line_start`;
3. `network_calls=0` на обоих чтениях.

Если реализация перестанет отдавать remainder/cursor или второй диапазон
вернёт чужой/пустой фрагмент, проверка становится `not_observed`; self-test
отдельно проверяет положительный и два негативных случая.

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
- `plumbing`-проверки (2,3,4,8) не дают production-доказательства, даже если
  весь контракт зелёный: их результат — `not_observed` + `plumbing_pass=true`.
  Для acceptance нужен отдельный production-прогон на deployed-дереве.
- При `--offline` проверки 1,5,6,7,9,10,11,11b,12 честно
  `not_observed + unavailable`: нет PG, SQLite-базы, systemd/journal, сети
  или provider-вызова. Это ожидаемое поведение, а не сбой harness.
- Повторный прогон безопасен, но числа (`recent_jobs`, spool, lag) зависят от
  момента; сравнивать нужно отчёт против отчёта, а не против ожидаемых
  «красивых» значений.

## Чтение результата

- `summary.observed/production_observed/not_observed/error` — счётчики.
- `summary.by_evidence_class` — сколько проверок дали `plumbing`,
  `production`, `unavailable`.
- `harness_sha256` / `harness_identity` / `repo` — привязка к candidate
  (см. выше); без `tracked=true` и `blob_matches_head=true` JSON не является
  candidate-bound evidence.
- `checks[].evidence_class/evidence_reason/production_observed` — почему
  проверка дала или не дала `observed`.
- `details.assertions[]` — конкретные ожидания с `ok=true/false`;
  `details.plumbing_pass` — контракт прошёл, но production не наблюдался.
- `details.exception` — только для `status=error`.
- JSON пишется атомарно в `--json-out`; путь затем копируется в
  `plans/features/smart-execution-reliability-01/evidence/postdeploy/live/`
  как durable evidence (сам harness ничего в репозиторий не пишет).

## Локальная проверка (автор/CI)

Запускать из deployed/release-дерева (код 2.58.200) либо передать
`--repo-path`:

```bash
python -m py_compile smart_live_canary.py
python smart_live_canary.py --dry-run
python smart_live_canary.py --self-test --offline
python smart_live_canary.py --offline --json-out /tmp/offline.json
```

`--self-test --offline` — без БД/сети/провайдера: проверяет tool-loop
(раунды/вызовы/последовательность/капы), evidence pack с хвостом и честной
обрезкой, capacity-резолвер (unknown ≠ verified, overflow), два
finalization-варианта, continuation (реальный remainder + второй диапазон,
плюс два негативных случая), запрет `observed` для plumbing и redaction.
Отдельные блоки покрывают r2-правки: `budget_flag.*` (фактический ключ
`budgets_enabled` читается, неизвестная форма даёт `None` + наблюдаемые ключи,
сломанный `as_meta` не роняет проверку) и `k3.*` (правка владельца
атрибутирована; запись без провенанса, `deploy_activate`, анонимная запись
истории и запись вне окна — проваливают атрибуцию; нетронутый профиль — ок).
Ожидаемый результат: `failures=0`, код 0, без traceback. Ненулевой код или
`BLOCKED` означает, что сам harness либо его repo-binding сломан.
