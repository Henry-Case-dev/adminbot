# EXTRA — deployment / migration / rollback (Block K, T-4183…T-4188) + **Delivery record**

> **Фича:** `extra-cover-style-pipeline` (EXTRA, round1029). **Risk:** R3.
> **Deploy:** `nik@198.46.175.136:/var/www/admin_bot` (systemd `admin_bot`, Ubuntu 24.04.4).
> **Статус деплоя: `VERIFIED`** (все 9 обязательных прод-проверок выполнены; отложенные
> пункты — D8 owner-value и DC-4 edit-capable provider — задокументированы ниже).

---

## 0. Delivery record (2026-09-30, ~08:41–08:52 UTC)

| Поле | Значение |
|---|---|
| **Deployed version** | **2.58.39** (`/healthz` = `{"status":"ok","version":"2.58.39"}`, `/api/health` = 200) |
| **Deployed commit (docs HEAD)** | `7d03b58377c63949425eacfe3ff0d83ee9066254` |
| **FEAT commit** | `cc1b960` — feat(round1029): Extra Cover Style pipeline (95 файлов) |
| **DOCS commit** | `7d03b58` — feature folder + review + WTH-манифест + full_audit_results + builder-скриншоты (12 файлов) |
| **Push** | `origin/master` `bbdee1c..7d03b58` (без force) |
| **Prod restart** | `sudo -n systemctl restart admin_bot`; `active`; `pg_available=True`; `settings=462` |
| **Deploy doc** | этот файл (`plans/features/extra-cover-style-pipeline/deployment.md`), docs-коммит после деплоя |

### 0.1. Binding (re-measured, совпадает)

| Набор | Значение | Проверка |
|---|---|---|
| Reviewed-Commit | `bbdee1ca44bf6695a1a421a3629792f6a0114edc` | HEAD до коммитов; matches |
| Spec-Hash | `CE34421C6B1B3282B047AF6D54E68FD3E1BF8FADBC4C1EA4ABB61E0D9C8577EF` | `sha256(spec.md)` — совпал |
| Working-Tree-Hash (gate) | `d0203e00fc46b328989fff83c4e4b478a40f71e739dc2d258843cacefed9dc9b` | re-measure на момент коммита — **совпал** (102/102 файла, ordinal-sort, идемпотентно) |
| tasks.md | `82B12AF0703E3483B6E8171578B04FDC91613C88ACDF33BA8BAB4F1DACB205B2` | совпал |
| adr-1028-4 | `E9C44ACCADF4FC0F9921A3F73054768A49EA1D8F700C1D744DBC006D92807251` | совпал |

> Примечание: сервисные файлы `plans/metrics.md`, `plans/workflow_state.md` не входят в
> release-scope manifest, поэтому gate-WTH не дрейфовал — re-measure совпал **до байта**
> (`d0203e00…dc9b`). После записи этого delivery-документа рабочее дерево меняется (evidence,
> не код); binding-reviewed кандидат остаётся `d0203e00…dc9b`.

### 0.2. Локальная верификация до push

- Clean-worktree (`git worktree add --detach HEAD`): `import web.app` + все новые модули → **IMPORT_OK**, `APP_VERSION 2.58.39`; `git status` чистый.
- EXTRA pytest-срез: `tests/test_extra_*.py` → **149 passed**; F8 `--check` → **CHECK OK 488**; JS `round1029_extra_cover_styles_test.js` → **EXTRA-COVER-STYLES-UI-OK**; `web/app.py` `4 0` (LF, 0 CR-байт).
- 3 seed-asset теста (`test_import_seed_does_not_mutate_source`, `test_seed_uses_actual_jpg`, `test_seed_files_exist_with_documented_sha`) в чистом checkout падают **только** из-за отсутствия untracked owner-ассетов `extra_images/*` (R18); с ними — **43/43 passed**. Не дефект кода.
- Secret-scan (R17) по 102 файлам release-scope: реальных секретов нет (только placeholder/synthetic-токены тестов).

### 0.3. Обязательные прод-проверки (binding approval) — 9/9 выполнены

| # | Проверка | Метод | Результат |
|---|---|---|---|
| 1 | **PG-DDL применён дважды** | `PgDatabase.init(seed_settings=False)` ×2 на боевом asyncpg + `pg_tables`/`pg_indexes` | **APPLY1_OK / APPLY2_OK**; 5 таблиц + 5 индексов (partial unique `idx_cover_style_assets_sha … WHERE deleted_at IS NULL`, `idx_cover_style_issue_unique`); **0 дублей**, без ошибок |
| 2 | **Real-pool CRUD-smoke** | asyncpg (боевой PG), `cover_style_registry`/`cover_style_assets` | create/get/duplicate(origin=custom)/edit(revision 1→2)/delete; ref add/replace(label L1→L2)/remove; upload дедуп по `sha256` → **тот же asset_id, count=1**; cleanup → leftovers=0 |
| 3 | **Counter/concurrency** | 10 параллельных `resolve_issue_number` разных run + reuse | номера **1..10 (10 distinct, без пропусков)**; тот же `summary_run_id` → **тот же номер**; `UNIQUE(profile_id, issue_number)` → **UniqueViolation**; Test Style (`preview_issue_number()==0`, `set_preview`) counter **не расходует** (10→10) |
| 4 | **UPDATE…RETURNING + `resolve_issue_number`** | тот же боевой READ COMMITTED (``SHOW transaction_isolation` = read committed`)`, `conn.transaction()` | без задвоенных/пропущенных номеров (1..10), `counter_value` = 10 |
| 5 | **`update_reference` rowcount** | PUT-путь → `update_reference(nonexistent ref_id)` | `raw` `conn.execute()` возвращает **строку** `"UPDATE 0"` (не курсор) → `getattr(rowcount,1)=1` → функция вернула **True** → API отдаёт **200**, а не 404. Зафиксировано как известное non-blocking (`L`, валидный путь корректен). |
| 6 | **Durable restart-resume** | прод-прогон `tests/test_extra_cover_style_jobs.py -k "DurableRestart or ProductionWiring"` (реальные `DatabaseService(":memory:")` + `TaskJobStore`) | **4 passed**; resume из `task_jobs` (`provider_task_id` переиспользован, `existing_task_id` ⇒ повторного submit нет); статическая wiring в `services/summary_generator.py` (begin/run/finish) подтверждена. **Живой async-polling** не наблюдался — async-провайдер не настроен (см. DC-4). |
| 7 | **DC-4 / T-4173 (§85/§86 + live style-success)** | проверка Connections: `models.image_style_base_url/_model` = пусто, `keys.image_style_api_key` = absent, `connection_status` → `configured=False`, `edit_supported=None` | **Edit-capable провайдера НЕТ** → §38-сообщение; живой style-success и visual §85/§86 **отложены владельцу**; базовая обложка обязана публиковаться (runtime-тесты §78/§90 зелёные). Честно задокументировано. |
| 8 | **Ladder/parity на проде** | прод-прогон `tests/test_extra_cover_style_runtime.py` + jobs/pipeline (61 passed) | 7/7 runtime-тестов: `test_no_style_base_cover_rich_regression`, `test_style_success_publishes_styled`, `test_style_failure_uses_base_no_regen`, `test_base_failure_degraded_rich_without_cover`, `test_base_failure_parity_plain_when_degraded_off`, `test_kill_switch_off_parity`, `test_degraded_rich_failure_falls_back_to_plain` — **все зелёные** |
| 9 | **Операционка** | health/version/locked/R17 | `/api/health`=200, `/healthz`=**2.58.39**; `database is locked` — за деплой **0** (последнее вхождение в журнале — 27.09); R17-скан `COVER_*`-логов — **0 утечек** (только run_id/chat_id/provider/duration) |

### 0.4. SEED (§59) + D8

- `seed_seeded_style(pg)` выполнен на проде: профиль **`medved_press`** (`origin=seeded_example`), `counter_enabled=True`, **`counter_value=0`** (D8 — обратимый дефолт, `SEEDED_COUNTER_START`, owner-input PENDING), 1 reference «Медведь Press».
- Импортировано 3 ассета из `extra_images/` в `var/cover_style_assets/` (`cas_<sha256[:32]>`): `medved_press.png`, `style_example_01.png`, `style_example_02.jpg`; **идемпотентно** (profiles 1→1, assets 3→3, refs 1→1); оригиналы `extra_images/*` **байт-в-байт не изменены** (R18).
- `extra_images/*` (owner read-only, вне git) доставлены на прод `scp`; в репозиторий не коммитятся.
- Итоговые боевые строки: `cover_style_profiles=1` (seeded), `references=1`, `assets=3`, `issue_assignments=0`, `provenance=0`.

### 0.5. Browser smoke (delivered env, bounded)

- Route: `https://admin-bot.duckdns.org/web/` → **200**, title «AdminBot — Админка», **0 console errors** (7 warnings).
- Delivered bundle (`/web/app.js`, `/web/index.html`) содержит маркеры фичи: `Стили обложки`, `coverStyles`, `openCoverConnections`, `preview_stale`/«Обновить пример», «предыдущей версии стиля» — **все present**.
- Авторизованные UI-потоки (CRUD/preview/references) проверены @Reviewer на stub-backend (см. `review.md`); guest-сессия к секции Config не переходит. Живой backend-visual §85/§86 — DC-4 (см. п.7).

### 0.6. Foreign WIP / hygiene

- **Не коммитилось** (чужой WIP/вне scope): `plans/features/mca-04b-dossier-rebuild/`, `extra_images/`, `node_modules/`, `package.json`, `package-lock.json`, `.playwright-mcp/`. `plans/metrics.md`, `plans/workflow_state.md` — сервисные (или обновляются оркестратором), оставлены незакоммиченными.
- Релиз-коммиты содержат ровно 95 (feat) + 12 (docs) файлов; чужого нет.
- **Временное действие на проде (обратимое):** managed-каталог `var/cover_style_assets/` создан и на время seed/CRUD доступен `nik` (через группу `docker`); по завершении `var` возвращён к `root:developers 0700`, каталог — `root:developers 0755` (app работает как `root`). Секретов в отчётах нет.

### 0.7. Rollback (§95)

| Уровень | Действие | Результат |
|---|---|---|
| **Hot (soft)** | `COVER_STYLES_ENABLED=false` (env-only) | Style-стадия пропущена; base cover + публикация живы; Style UI disabled. |
| **Hot (контур)** | `COVER_RICH_DEGRADED_ENABLED=false` | cover-failure снова plain (baseline parity §90). |
| **Cold** | `git revert` релизных коммитов | PG-таблицы аддитивны (SQLite Δ=0); откат base-cover не требуется. |

### 0.8. Отложено владельцу

1. **D8** — стартовое значение counter сида (сейчас обратимый дефолт `0` → следующий выпуск = 1).
2. **DC-4** — edit-capable image-провайдер в Connections (`models.image_style_*` / `keys.image_style_api_key`); без него живой style-success и visual §85/§86 недоступны (база публикуется корректно).
3. Живой async restart-resume polling (зависит от DC-4-провайдера; store-уровень resume подтверждён).

---

## 1. Версия и артефакты (план)

- **bump:** `APP_VERSION` `2.58.38 → 2.58.39` (`config/settings.py`).
- **Δ DDL SQLite = 0** — `PRAGMA user_version` остаётся **19**; `mca-04b` сохраняет бронь `v20`.
- **Δ PG-DDL ≠ 0** — 5 аддитивных таблиц + индексы через `services/pg_db.py::DDL_STATEMENTS`.
- **Δ каталога = +4** ParamSpec; F8 `--check` OK 488; `datadir`/`user_version` не поднимаются.
- **Файлы ассетов:** `var/cover_style_assets/` (env `COVER_STYLE_ASSETS_DIR`); seed из `extra_images/*` копируется (R18).

## 2. Migration safety (§94)

1. **PG-инициализация идемпотентна** (`CREATE TABLE IF NOT EXISTS`); повтор — no-op.
2. **Существующие Summary не ломаются:** config без выбора стиля → `Без дополнительного стиля` → текущий base-путь.
3. **Seed идемпотентен (§59).**
4. **PG недоступен:** Style-функции fail-soft (base + публикация живут).

## 3. Env-only переключатели EXTRA (Δ каталога = 0)

| Переменная | Default | Назначение |
|---|---|---|
| `COVER_STYLES_ENABLED` | ON | Master kill-switch optional Style-слоя. |
| `COVER_RICH_DEGRADED_ENABLED` | ON | Degraded RichMessage без обложки (§51). |
| `COVER_STYLE_EDIT_TIMEOUT_SECONDS` | 240 | Окно одной попытки edit (кламп [30, 900]). |
| `COVER_STYLE_EDIT_MAX_ATTEMPTS` | 1 | Попытки edit (кламп [1, 3]). |
| `COVER_STYLE_EDIT_RETRY_BACKOFF_SECONDS` | 5 | Пауза между попытками. |
| `COVER_STYLE_HEARTBEAT_SECONDS` | 30 | Период heartbeat. |
| `COVER_STYLE_METRICS_ENABLED` | ON | Process-local latency/cost метрики. |
| `COVER_STYLE_CAPABILITY_TTL_SECONDS` | 900 | TTL кэша capability. |
| `COVER_STYLE_CAPABILITY_OVERRIDES` | "" | JSON-override capability (escape hatch). |
| `COVER_STYLE_ASSETS_DIR` | `var/cover_style_assets` | Managed-каталог файлов ассетов. |
| `COVER_STYLE_ASYNC_SUBMIT_URL` / `_STATUS_URL` | "" | Async submit/poll (capability-gated). |

## 4. Production acceptance checklist (§100, T-4186)

- [x] **No Style** — base cover + RichMessage, без деградации (§90; runtime-тест на проде).
- [~] **Medved Press** — профиль seeded (counter 0, ref `medved_press.png`); живой styled-publication недоступен без edit-capable провайдера (DC-4).
- [x] **Style failure → base** — `test_style_failure_uses_base_no_regen` (без перегенерации base).
- [x] **Base failure → Rich без изображения** — `test_base_failure_degraded_rich_without_cover`.
- [x] **Rich failure → plain** — `test_degraded_rich_failure_falls_back_to_plain`.
- [x] **UI** — delivered-бандл содержит вкладку/редактор/preview-маркеры; авторизованные потоки — @Reviewer (stub).
- [x] **Logs** — `COVER_*` без утечек; точная стадия/fallback трассируются.
- [x] **Health** — 200, `version=2.58.39`, `database is locked`=0.

## 5. Продуктовые предусловия

- **DC-4:** реальный Style Edit требует edit-capable provider; **не настроен** → §38-сообщение, base публикуется корректно. **Отложено владельцу**, не блокер деплоя.
- **D8:** стартовое значение seeded counter — **owner-input required**; действует обратимый дефолт `0`.
