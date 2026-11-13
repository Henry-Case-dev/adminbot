# SELF-DIAG-01 corrective §6 — binding identity/manifest + honest counters

**Слайс:** `self-diag-01` / corrective 2026-11-13, часть «deploy identity/manifest + счётчики» (Architect contract item 4 + counters half of item 3).
**Owner input:** `plans/owner_inputs/2026-11-13-selfdiag-corrective-journal-code-identity.md` §6.
**Контракт:** `plans/features/self-diag-01/corrective-2026-11-13/architecture-corrective.md` (deploy identity, counters).
**База:** `234776589c934024ed0e8dceba189fb9d70d3215` (2.58.198).
**Код-коммит:** `ea9e9f2a1dc8b04bb82607acf9939bdefa3c16be`.
**Ветка/worktree:** `self-diag/identity`, `WorkspaceData/worktrees/c742e4de9e92c489/self-diag-01-0ccfa8fbf52b-cf77b5ba`.
**Деплой не выполнялся.** Прод до следующего релиза остаётся в честном `no_manifest`.

## 1. Доказанная причина `no_manifest` / `deployed_sha=None` / `healthy=unknown`

Причина не в парсере identity, а в **отсутствии producer'а манифеста в штатном deploy-пути**:

1. В базовом дереве нет ни одного писателя `.deploy/release.json`. `git grep -n "release.json" 23477658 -- '*.py' '*.sh'` находит только читатель `services/deploy_identity.py` (путь — `:43`, чтение/валидация — `:314–383`), тесты и docs. Единственный tracked deploy-скрипт `deploy_v2.9.2.py` — legacy для старого VPS: host `198.46.175.136` (`:18`), шаги только `git pull` + `systemctl restart` + `journalctl` (`:94–123`), пишет `deploy_result.json` (`:146–147`), манифест не создаёт.
2. Штатный путь деплоя в базе — `README.md:62–74` (`git pull --ff-only` → `systemctl restart admin_bot`) и `AGENTS.md`; шага записи манифеста нет. Поэтому после выкатки 2.58.198 манифест не появился.
3. `.gitignore` базы не содержит `.deploy/` — контрактная строка `architecture-d4-identity.md §1.2` («одна строка `.deploy/` в `.gitignore`») тоже не была реализована.
4. Обязанность `EXT-DEPLOY-MANIFEST` была зафиксирована как **невыполненная** в binding D4-A (`plans/features/self-diag-01/evidence/d4/binding-d4a-673fa0e67481119108dcae7c511f835fd3271d69.md` §3/§4), и production-проверка это подтвердила. То есть манифест не «сломался» — его никогда не писали.

Следствие в коде: при отсутствии файла `_read_manifest` возвращает `no_manifest` → `deployed_sha` остаётся `None` (env `ADMINBOT_DEPLOYED_SHA` на проде не задан) → `local_unverified/no_manifest` (`services/deploy_identity.py:1038–1041` базы). Наличие checkout намеренно не повышается до deployed: `checkout_sha` заполняется отдельно из `.git/HEAD`.

`healthy=unknown` — отдельный слой: probe `deploy.identity` в базе объявлял `health_criterion="none"` и `healthy=None` всегда (`services/runtime_probes.py:1908–1914` базы), а `render_facts_text` печатает None как `healthy=unknown` (`services/evidence_bundle.py:705`). Даже при валидном манифесте строка оставалась бы unknown. Исправлено: verified → healthy=true, mismatch → false, unknown/local_unverified → None.

## 2. Что сделано

### 2.1 Producer: `tools/release_manifest.py` (новый, 375 строк)

Штатный шаг деплоя — после обновления checkout и **до** рестарта:

```bash
cd /var/www/admin_bot
git pull --ff-only
venv/bin/python tools/release_manifest.py      # пишет .deploy/release.json
sudo systemctl restart admin_bot
```

Либо `--restart` (если у процесса есть права на `systemctl`). Свойства:

- `deployed_sha` = `git rev-parse HEAD` **фактического checkout**; `version` = `APP_VERSION` из `config/settings.py` этого checkout (AST-разбор, без импорта/исполнения кода); `deployed_at` = UTC-время записи, `...Z`; `effect` = `deploy|rollback`; `previous_sha`/`previous_version` — из предыдущего **валидного** манифеста; `release_branch` — из `git symbolic-ref`; `deployer` — только явный `--deployer`/`ADMINBOT_DEPLOYER`, без логинов по умолчанию.
- Грязное **tracked**-дерево отклоняется (`ManifestError`, rc=2): SHA не идентифицирует исполняемый код. Untracked-файлы не блокируют (на проде они постоянны и код не меняют).
- Запись атомарная: временный файл в `.deploy/` + `os.replace`, режим `0644`, fsync файла и каталога. `.deploy`/`release.json` не могут быть symlink'ом наружу.
- `--dry-run` печатает манифест, ничего не пишет. Битый/отсутствующий предыдущий манифест не подменяется догадкой — `previous_* = null`.
- `.deploy/` добавлен в `.gitignore`; манифест не отслеживается git, переживает `git pull`/checkout и рестарт.
- README обновлён: шаг 2 штатного деплоя — запись манифеста (тот же пользователь, что владеет checkout).

### 2.2 Deploy identity: audit процесса и честный mismatch

- `services/deploy_identity.py`: в запись добавлен `process_started_at` (нормализованный ISO из `status.started_at`) — теперь видно, с чем сравнивается `deployed_at`, а не только факт `sources=["process_start"]`. Ключ аддитивный; существующие поля/коды не менялись.
- `services/runtime_probes.py` (`deploy.identity`): `mismatch` теперь `STATUS_DEGRADED` (раньше отсутствовал в map → `unknown`), `verified=false`, `healthy=false`; `verified_deployed` → `healthy=true`; `local_unverified`/`unknown` → healthy `None` (не «здоров», но и не ложный mismatch). В facts добавлены `process_started_at`, `effect`, `previous_sha`, `conflict_values`; `deployed_sha` и `checkout_sha` остаются раздельными. `healthy` не подменяет health процесса: это согласованность identity.
- Checkout никогда не становится `deployed_sha`: без манифеста код остаётся `local_unverified/no_manifest`, `deployed_sha=None`.

### 2.3 Счётчики: отсутствие наблюдения ≠ доказанный ноль

- **`logs.errors`** (`services/log_ring.py`, `services/runtime_probes.py`): в существующий ring добавлен `records_total` (счётчик записей, прошедших через handler, + `started_at`); `get_records_total()` под тем же lock. Если ring не видел ни одной записи → `status=not_checked`, `reason_code=no_observations`, `error_entries=null`, `errors_total=null`, `not_checked` содержит `error_entries/errors_total`. Если записи были и ошибок 0 → доказанный ноль (`error_entries=0`, `records_observed>0`, `no_error_entries`). Ошибка чтения ring → `unavailable/log_ring_read_failed`, не ноль. `logs.window`: пустое окно даёт `error_marker_count=null` и `error_marker_basis=no_observations` (раньше 0).
- **`telegram.delivery`**: различаются `ledger_disabled`/`ledger_reader_absent` (`not_configured`) и `ledger_read_failed` (`unavailable`) — во всех трёх `delivered=null`, `not_checked` содержит `delivered`. Для этого `bot_output_ledger.list_bot_output_history` получил keyword-only `raise_on_error=False` (default-поведение прежнее); диагностика передаёт `True`. Успешное чтение окна по-прежнему даёт `delivered=<число строк>` с явным `basis=bot_output_ledger_rows`/`observations`; 0 здесь — ноль записей ledger, не «доставка здорова» (`delivery_errors_per_chat` остаётся not_checked).
- **`media.stt`**: если в окне нет ни одной voice-строки (`voice_rows=0`), возвращается `status=not_checked`, `reason_code=no_voice_rows`, `failed=null`, `pending=null`, `not_checked+=voice_transcripts` — а не `failed=0`. При наблюдённых строках счётчики прежние (включая доказанный `failed=0`). `rows_scanned`/`voice_rows` видны в facts.

Новой телеметрии/БД/DDL/настроек нет: используются существующий ring, gate+ledger и `get_voice_window`.

## 3. Точный diff против `23477658`

```
 .gitignore                      |   3 +
 README.md                       |  13 +-
 services/bot_output_ledger.py   |  12 +-
 services/deploy_identity.py     |   8 +-
 services/log_ring.py            |  12 ++
 services/runtime_probes.py      | 162 +++++++++++++++++----
 tests/test_deploy_identity.py   |   5 +-
 tests/test_diagnostic_probes.py | 194 +++++++++++++++++++++
 tests/test_release_manifest.py  | 380 ++++++++++++++++++++++++++++++++++++++++
 tests/test_self_diag_golden.py  |  35 +++-
 tools/release_manifest.py       | 375 ++++++++++++++++++++++++++++++++++++++++
 11 files changed, 1152 insertions(+), 47 deletions(-)
```

Не тронуты: `handlers/checkup.py`, `services/checkup_service.py`, `services/direct_l1.py`, `services/direct_chat_service.py`, `services/tool_schemas.py`, `services/tool_loop.py`, `services/source_reader.py` (другой писатель), `web/api/routes.py` (byte-freeze, см. §7), `services/database.py`, unit/systemd, `.env`, промпты, настройки, БД/DDL. Код деплоя продукта не меняется — добавлен отдельный deploy-artifact.

## 4. Тесты, RED → GREEN

**RED на базе `23477658`:** новые тесты `TestCounterHonesty` против базовых `runtime_probes.py`/`log_ring.py`/`bot_output_ledger.py` — **10 failed / 0 passed**: старый `logs.errors` давал 0 без записей, `telegram.delivery` давал 0 при выключенном/сломанном ledger, STT давал `failed=0` без voice-строк, `mismatch` был `unknown`/`healthy=None`, `verified` был `healthy=None`. Producer в базе отсутствует (см. §1), поэтому `no_manifest` на базовом коде — воспроизведён существующим `test_no_manifest_is_local_unverified_never_verified` и production-симптомом.

**GREEN на `ea9e9f2a1dc8b04bb82607acf9939bdefa3c16be`:**

| Команда/набор | Результат |
|---|---|
| `pytest tests/test_release_manifest.py` | **20 passed** |
| `pytest tests/test_deploy_identity.py tests/test_release_manifest.py` | **58 passed** |
| `pytest tests/test_diagnostic_probes.py` | **68 passed** (58 старых + 10 новых) |
| `pytest tests/test_self_diag_golden.py` | **39 passed** (G02 обновлён, добавлен G02b, G03 уточнён) |
| `pytest` 16 затронутых файлов (identity D4-A/B/C, probes, settings adapter, golden, prompt_readback, checkup contract/handlers/logs/prompts/service, p0 checkup, UR bot output, mca22) | **555 passed / 0 failed** |

Новые тесты `tests/test_release_manifest.py` (20) проверяют именно связку producer→identity:

- schema/ключи манифеста, `deployed_sha==HEAD`, `version==APP_VERSION`, `deployed_at=...Z`, ветка, отсутствие фиктивных previous;
- `collect_identity` → `verified_deployed`, `deployed_sha==checkout_sha==HEAD`, `process_started_at` записан, `version_provenance.consistent=true`;
- манифест переживает «рестарт» (повторный collect с более поздним process start, байты манифеста не меняются);
- без манифеста `deployed_sha=null`, `checkout_sha` заполнен, код `local_unverified/no_manifest`;
- checkout сдвинулся после манифеста → `mismatch/sha_conflict` с обоими SHA;
- process start раньше `deployed_at` → `mismatch/process_predates_deploy`;
- версия чужого checkout не скрывается (`version_conflict`);
- rollback-манифест: `effect=rollback`, `deployed_sha=старый SHA`, `previous_sha=откатываемый SHA`;
- грязный tracked-tree отклоняется, существующий манифест не перезаписывается;
- untracked-файлы не блокируют, `.deploy` не попадает в git;
- symlinked `.deploy` наружу отклоняется; битый предыдущий манифест не отравляет новый;
- `--dry-run` ничего не пишет; CLI на не-git каталоге rc=2; `MANIFEST_REL_PATH` совпадает с reader'ом;
- `config/settings.py` с UTF-8 BOM читается так же, как Python-импорт (реальный файл начинается с BOM; без этого deploy ложно блокировался).

**Ручной production-like smoke (clean git checkout, CLI из committed `tools/release_manifest.py`):**

```
CLI rc: 0
wrote .deploy/release.json | sha=af3dfe25… version=2.58.198
effect=deploy deployed_at=2026-11-13T04:56:53.914861Z
manifest exists: True
git status: <пусто>
identity code: verified_deployed
deployed_sha==HEAD: True checkout_sha==HEAD: True
version_provenance: {'runtime':'2.58.198','manifest':'2.58.198','consistent':True}
sources: [release_manifest, git_head, git_cli, runtime_app_version, process_start]
```

## 5. Production-размещение и определение identity

- Манифест: `/var/www/admin_bot/.deploy/release.json` — ровно тот путь, что читает `services/deploy_identity.py` (`MANIFEST_REL_PATH`), внутри checkout, вне git.
- Process start: существующий `services.status_service.status.started_at` (выставляется на импорте и `mark_started()` первой строкой `bot.py:1356`), передаётся в `collect_identity` из `DiagnosticCollector`/probe; в записи теперь виден как `process_started_at`.
- `verified_deployed` требует: валидный манифест; `deployed_sha == checkout HEAD`; `dirty=false`; `manifest.version == APP_VERSION` загруженного `config.settings`; `process_started_at >= deployed_at`. Любое расхождение даёт `mismatch`/`unknown`/`local_unverified` с причиной; checkout отдельно.
- Манифест пишется **до** рестарта. Это осознанно: D4 §1.3 шаг 6 («rollback: restart → записать манифест») дал бы `process_started_at < deployed_at` и постоянный `process_predates_deploy`; corrective contract (§deploy identity) требует запись до рестарта. Для rollback `previous_*` читаются из предыдущего манифеста, поэтому история отката честная.

## 6. Эффективная конфигурация

| Параметр | Значение в тестах | Прод/релиз |
|---|---|---|
| `MCA_BOT_OUTPUT_LEDGER_ENABLED` | default ON; тест OFF — через monkeypatch `ledger_enabled` | default ON (не менялся); при OFF теперь `not_configured/ledger_disabled`, не 0 |
| `SELF_DIAG_LOCAL_REPO_ROOT` / `ProbeDeps.repo_root` / cwd | тесты — temp repo / cwd | `/var/www/admin_bot` (WorkingDirectory unit'а), значение не менялось |
| `ADMINBOT_DEPLOYED_SHA` | не задан; fallback покрыт старыми тестами | не задан; манифест его перебивает, env никогда не повышает код до verified |
| `ADMINBOT_DEPLOYER` | не задан | опционально; только текстовая метка, без логина по умолчанию |
| Новые флаги/настройки/DDL | 0 | 0 |

Тесты OFF-ветки: `test_telegram_delivery_ledger_disabled_is_not_configured` (gate off → `delivered=null`). Основной путь проверен с ledger ON (default) и реальным `DatabaseService`.

## 7. Честные границы и что осталось проверить

1. **Прод-манифеста ещё нет.** Он появится только на следующем штатном релизе, который выполнит новый шаг. Задним числом манифест не создавался: без реального deploy-прогона это было бы фиктивным доказательством. До этого прод честно показывает `local_unverified/no_manifest`, `deployed_sha=None`.
2. **Producer — это deploy-шаг, а не автоматика внутри процесса.** Репозиторий не управляет внешними SSH-командами DevOps; если шаг пропустить, identity останется `no_manifest` (никогда не «verified»). README и этот документ фиксируют обязательную команду и порядок.
3. `healthy=true` означает согласованность identity, а не здоровье бота; при `local_unverified`/`unknown` остаётся `unknown` (None), при `mismatch` — false. Это не маскирует неверифицированное состояние.
4. Identity доказывает: манифест относится к текущему HEAD, версия совпадает с загруженной, процесс стартовал после записи манифеста. Это не доказывает, что каждый импортированный модуль не был подменён из другого пути; существующий контракт D4 этого и не обещает.
5. Telegram: 0 строк ledger при успешном чтении остаётся 0 с `basis/observations`; это не доказательство успешности доставки или отсутствия ошибок доставки (они в `not_checked`). STT/логи: при отсутствии наблюдений — `null` + `not_checked`.
6. `--restart` требует прав на systemctl; стандартный путь в README — запись манифеста, затем `sudo systemctl restart`.
7. **BACKLOG_ONLY (не в этом кандидате):** `web/api/routes.py` в `_self_diag_payload` читает `identity.get("branch")` и `identity.get("source")`, тогда как branch лежит в `local_identity`, а источника с таким именем нет → UI `runtime.branch`/`identity_source` всегда пусты. Файл под строгим byte-freeze (`tests/test_round1025_f8_registry.py::test_routes_file_unchanged`), правка требует осознанного re-pin и не нужна для §6; оставлено в backlog. На `deployed_sha`/`checkout_sha`/`healthy` это не влияет.
8. `tests/test_cfg03_param_audit.py::test_visible_dead_knobs_are_exactly_documented` падает на `flags.dig_pre_gate_enabled` — pre-existing, не связан с identity/счётчиками (зафиксирован в release 2.58.198 как известный 1 failed).

## 8. Откат

- Код: `git revert ea9e9f2a1dc8b04bb82607acf9939bdefa3c16be` (или deploy предыдущего проверенного SHA) → `git pull --ff-only`/checkout → `systemctl restart admin_bot`. DDL/миграций нет, данные не затрагиваются.
- Манифест при откате: если откатываемое дерево содержит producer — `venv/bin/python tools/release_manifest.py --effect rollback` перед рестартом (previous_* возьмутся из текущего манифеста). Если producer в откатываемом дереве уже нет — запустить копию скрипта из кандидата с `--repo-root /var/www/admin_bot --effect rollback` до рестарта. Если манифест переписать нельзя — identity честно даст `mismatch`/`no_manifest`, без подмены.
- После рестарта: `systemctl is-active admin_bot`, `/healthz` 200, `deployed_sha` в `/api/status`/чекапе.

## 9. Границы коммита

Только 11 файлов из §3. Прод не менялся, деплой не выполнялся, `plans/current_task.md`/карты не редактировались. Reviewer/DevOps независимо проверяют behavior и следующий production deploy; этот документ — Builder-handoff, не approval.
