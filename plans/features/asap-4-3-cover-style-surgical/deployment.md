# deployment.md — asap-4-3-cover-style-surgical (prod 2.58.50)

Feature: `asap-4-3-cover-style-surgical` · Risk R2 · **Статус: VERIFIED**
Дата: 04.10.2026 (UTC) · Исполнитель: @DevOps · Задача T-4862 (owner spec §17)

## 1. Binding и окружение

- Кандидат: working tree на HEAD `2e80071`, база APP_VERSION 2.58.49. **WTH preflight: `39E5330B…A9AFDD7` пересчитан — совпал с review-биндингом; 30/30 файлов манифеста — size+sha256 без дрейфа.** `git ls-files extra_images` → 3 файла после стейджа ✓.
- Прод: `nik@198.46.175.136:/var/www/admin_bot` (racknerd-f4e3456), systemd `admin_bot`, Ubuntu 24.04, venv `/var/www/admin_bot/venv` (Python 3.12, asyncpg 0.31.0).
- Деплой-авторизация: Orchestrator (T-4862, review Approved C0/H0 + 2 Low non-blocking).

## 2. Коммиты

- **feat: `1c47b5e`** — runtime (11) + тесты (11 py + 2 js) + tool `ui_asap32_cover_styles_e2e.py` + `extra_images/` (3 staged) + version bump (settings.py APP_VERSION **2.58.50**, 23 тест-пина, plans/docs/param-registry-…meta.md). 49 файлов, +3538/−766.
- **docs: `3ad0948`** — requirements-map/tasks/evidence/review + WTH-манифест (5 файлов).
- origin/master: `2e80071..3ad0948` push ✓; unrelated WIP (metrics/workflow_state/round1027-frames) в коммиты не попал, `node_modules/`, `package*.json`, `verification_cache.json`, `tools/_ui_asap43_*` — не тронуты.

## 3. Деплой (факты)

- Предусловие: на проде лежали untracked копии старых `extra_images/` (размеры 2074036/385055 ≠ staged) → `git pull` аборт. Ожидаемо: файлы сдвинуты в `pre_migration_backup/extra_images_pre25850/`, после pull — **sha256 трёх seed'ов на проде == WTH-манифесту** (be0a70…/543283…/ed77de…) ✓.
- `git pull --ff-only`: `04b5fdd..3ad0948` fast-forward ✓ (диск 5.7G free — без дефицита).
- **Рестарт**: `sudo -n systemctl restart admin_bot` → rc=0; **active с Sun 2026-10-04 11:28:30 UTC, MainPID=3594974, NRestarts=0, ExecMainStatus=0** ✓.

## 4. Health

- `GET :8000/healthz` → **200** `{"status":"ok","version":"2.58.50"}` ✓; `/api/health` → **200** ✓.
- Отданный `/web/app.js?v=2.58.50` sha256 **= binding-манифесту** (0E8584…) байт-в-байт; `web/index.html` на проде = binding (BEB0F7…) ✓; страница `/web/` отдаёт `v=2.58.50`.

## 5. Миграции

- **SQLite: user_version = 25 → 25, schema_migrations_max = 25 — ΔDDL = 0** ✓ (read-only PRAGMA после рестарта).
- **PG additive**: колонка `cover_style_profiles.preview_job_id` (text, nullable) применена идемпотентно; таблиц `cover_style_*` = 6 (assets/connections/issue_assignments/profiles/provenance/references); counts: assets 6, issue_assignments 11, **profiles 1 (Medved seed)**, provenance 13, references 1, connections 0 — **данные целы, Δ не наблюдается** ✓. Прочих DDL нет.

## 6. Проверки

1. **Фокусные (job, локальный venv до коммита):** pytest 6 файлов → **119 passed / 0 failed**; `node` asap43 + round1029 → OK; `node --check web/app.js` → OK.
2. **Прод-venv ladder/parity** (11 файлов: asap43, extra_jobs, registry, api, ui, pipeline, contract_asap32, asap42 step2c2/step3, wave_b, wave_f) → **220 passed / 0 failed** (31 с) ✓.
3. **F8 каталог**: `gen_param_registry_round1025.py --check` → **CHECK OK: 488, Δ=0**, EXIT=0 ✓.
4. **RBAC unauth**: `POST /api/cover/test-style` → **401** `{"detail":"missing init data"}`; `GET /api/cover/test-style/{job_id}` → **401** ✓.
5. **Логи (с 11:28 UTC):** `ERROR|CRITICAL|Traceback` = **0**; R17-скан (`sk-|Bearer|xox|AKIA|-----BEGIN|api_key=`) = **0** ✓.
6. **Config cache / env:** прод-.env — **0 вхождений** COVER_STYLES_*/COVER_STYLE_*/IMAGE_PROMPT_*/MCA_DREAM_* → кодовые дефолты (COVER_STYLES_ENABLED ON, `?v=` — `__APP_VERSION__` — пинов нет); config_migrations при старте — идемпотентные INFO «уже новый дефолт»; **0 HTTP-401** в окне; 2 WARNING — известный pre-existing контур GraphRAG embed deferred (rotation=none при старте пула; сигнатура раундов 1030–1032, вне скоупа, инцидентным не считаю).
7. **Прод UI unauth smoke (Playwright, desktop 1280×800):** страница грузится, title OK, **console 0 errors**, честная unauth-заглушка; отдельно e2e-харнесс `ui_asap32_cover_styles_e2e.py` на прод не гонялся (необязателен по процедуре; был зелёный у Reviewer: 3 viewport, failures=[]).

## 7. Incidental findings

- **[I-1][Info, pre-existing]** warning-контур `embedding_control_plane rotation=none → SmartModule graph backfill deferred` в стартовом окне — документирован в раундах 1030–1032; немедленного прод-риска нет (deferred по расписанию resume).
- **[I-2]** (из review-планшки, повтор) Low: GET `/cover/test-style/{job_id}` доступен юзерам с `access` в момент админ-теста — не блокирует; @Orchestrator на triage.

## 8. Rollback

- **Soft:** `COVER_STYLES_ENABLED=false` + рестарт → базовая обложка/публикация живы (фича OFF).
- **Cold:** `git revert`/revert до prod HEAD-предшественника `04b5fdd` (2.58.49); PG DDL аддитивен (nullable text-колонка) — старый код её не читает, restore БД не требуется; SQLite v25 не менялся.
- Backup-полка старых seed-копий на проде: `pre_migration_backup/extra_images_pre25850/`.

## 9. PENDING OWNER (residual)

- **Canary A (T-4859)** — реальный Test Style на прод-провайдере (base+edit+reference → completed, атомарная pair, issue без изменений).
- **Canary B (T-4860)** — production publish = именно styled cover.
- **Live acceptance (T-4863/4864)** — реальный Telegram WebView mobile + живой Summary с Medved Press; ladder.
- Платные провайдер-канари в этом шаге не запускались — следуют отдельно.
