# deployment.md — mca-08-character-speech (prod 2.58.55)

Feature: `mca-08-character-speech` · Risk R2 · **Статус: VERIFIED**
Дата: 05.10.2026 (локальный календарь) · Исполнитель: @DevOps · Задача T-4913 (review.md T-4912 → Approved; санкции ADR-1028-11 D10–D12; процедурный рецепт §9.6 spec)

> Факты ниже — по **серверному UTC** (на сервере `Sun Oct 4 2026 21:xx UTC`; локальный календарь dev-машины — 05.10.2026; расхождение часов/календарей зафиксировано в [I-2]).

## 1. Binding и preflight

- Кандидат: uncommitted working tree на HEAD `192e2293137997fc13a22addc43ecc2c2b741d6e`; review **Approved** (`review.md`, T-4912, один вердикт, без аддендумов).
- WTH-биндинг: `_review_wth_manifest.txt` — 29 файлов, sha256(манифеста) `57E036674EB08E82F6E12498EBB34B80B5E203A3B5A319A443CDD739C82B656B` (рецепт §review).
- **Preflight (DevOps, самостоятельный пересчёт per-file sha256+size):**
  - все 27 in-scope файлов (runtime/тесты/docs-пакет) — **0 drift**;
  - `plans/docs/mca-round1027-arch-frames.md` (out-of-scope F-6) — 0 drift;
  - `plans/workflow_state.md` (out-of-scope F-6, чужой dirty-state предыдущих сессий) — дрейф vs манифесту (+84/−14 строки, ноты параллельных сессий). По review.md изменение вне in-scope инварианта не инвалидирует вердикт; файл в коммиты не входит (commit-гигиена §2). Зафиксировано как [I-1], в дельту релиза не попадает.
- Prod до деплоя: HEAD `495bcf4` (2.58.54), MainPID 3687549.

## 2. Коммиты

- **feat: `3d03ff6`** — 46 файлов (+3414/−69): 20 runtime/тест-файлов манифеста (12 services incl. Новый `services/mca_style_scope.py` + миграционный код в `database.py`, `handlers/direct_chat.py`, `config/settings.py`, 9 тест-файлов манифеста incl. 2 новых `test_mca08_*`) + **version bump 2.58.54→2.58.55**: `config/settings.py` APP_VERSION **2.58.55** + 23 release-пина тест-файлов по конвенции `1c47b5e`/`615857c` + метапин `plans/docs/param-registry-round1025.meta.md` → 2.58.55 (release-standard pin, вне манифеста — drift=0 не нарушен).
- **docs: `2a4730a`** — 7 файлов (+981): `plans/features/mca-08-character-speech/{spec.md, adr-1028-11-character-speech.md, tasks.md, requirements-map.md, evidence.md, review.md, _review_wth_manifest.txt}` (конвенция docs-пакета).
- **deploy-doc** — этот файл (docs-only; второй рестарт не требуется).
- `git add` только явными путями: НЕ попали `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, `node_modules/`, `package*.json`, `.playwright-mcp/`, `plans/verification_cache.json`, `tools/_ui_asap43_*` ✓ (все — чужой dirty-state/untracked, F-6).
- origin/master push: `192e229..2a4730a` ✓; прод `git pull --ff-only origin master`: **`495bcf4..2a4730a` fast-forward** ✓ (untracked не конфликтовали).

## 3. Деплой (факты)

- Рестарт 1: `sudo -n systemctl restart admin_bot` rc=0 в **21:07:32 UTC**; MainPID **3726880** (start `Sun 2026-10-04 21:08:32 UTC`), ExecMainStatus=0, NRestarts=0.
- `/healthz` → **200** `{"status":"ok","version":"2.58.55"}` на 21:11:29 UTC (подъём ~3 мин — контур pre-migration VACUUM INTO ~1.3 GB + миграция до старта сервинга); `/api/health` → **200** `{"status":"ok"}` ✓.
- Прод-venv `/var/www/admin_bot/venv` (Python 3.12): `pytest tests/test_mca08_character_speech.py tests/test_mca08_style_form.py` → **135 passed / 0 failed (30.4 с)**; 2 warnings — `PytestConfigWarning: Unknown config option: timeout` (pre-existing env-артефакт prod-venv, не код).

## 4. Миграции / DDL — v25 → v26 (контур mca-14 как есть)

- **Backup-guard ДО применения шага (fail-closed, существующий механизм):** 21:11:14 `memory_backup: pre-migration copy created + read-back ok | target_version=25`. Полка: `/var/www/admin_bot/pre_migration_20261004_210851.db`, **1315704832** байт, `integrity_check` **ok**, копия `PRAGMA user_version` = **25**, `mca_style_requests` в копии отсутствует, `task_jobs` в копии = 639 (= pre-state). Пожелаешь adventure: суточная ротация `_MIGRATION_BACKUP_KEEP=1` держит одну последнюю полку; это она.
- **Применение v26:** 21:11:15 `[database] migration v26: mca_style_requests` → `migration v26 applied | style_requests` — ровно один раз.
- **Факты после:** SQLite `PRAGMA user_version` **25 → 26**; книга `schema_migrations` 14 → **15 строк**, ряд `v26` ровно **один**; таблица `mca_style_requests` создана (+ **0 строк**), индексы `idx_mca_style_requests_active` + `idx_mca_style_requests_participant` присутствуют; `tables_total` 99 → 100; больше ничего в схеме не менялось.
- **Идемпотентность (второй рестарт, 21:18–21:21 UTC, MainPID 3730314):** в окне рестарта **0** строк `migration v26` / `pre-migration copy`; `/healthz` → 200 @2.58.55; версия/книга/таблица не изменились — **повтор = no-op** ✓.
- **PG no-op:** `pg_db.py` вне diff; таблиц PostgreSQL не создавал/не менял (`information_schema.tables` public = 26, `mca_style_requests` в PG нет — по дизайну D3 таблица SQLite-only) ✓.
- **Живые данные целы (spot-check pre → post):** SQLite `task_jobs` 639 → 640 → 641, `summary_runs` 13, `summary_source_windows` 13, `mca_events` 9870 → 9882 (растут от live-работы бота; миграционные дельты отсутствуют). PG `cover_style_issue_assignments` **17**, `cover_style_assets` **13**, `cover_style_provenance` **24**, MAX(counter_value) **17** (= next 18) — **не тронуты**; counter/override/config states не менались; `mca_style_requests` = 0 строк (записей не создавали — live-поведение смотрит T-4914) ✓.

## 5. Kill-switches / конфигурация

- `.env`: ключи `MCA_CHARACTER_LAYERS_ENABLED` / `MCA_CHARACTER_SPEECH_ENABLED` / `MCA_STYLE_SCOPE_ENABLED` / `MCA_POSTPROCESS_FORM_GUARD_ENABLED` — **0 строк** (env-перекрытий нет) → дефолты кода, **K1–K4 = ON**; TTL `MCA_STYLE_SCOPE_CHAT_TTL_DAYS`/`TOPIC_TTL_DAYS` не заданы → дефолты 7д/30д. Только `DB_PATH` — как и было ✓.
- Δ каталога **0** (F8 NOT_APPLICABLE): `gen_param_registry_round1025.py --check` → **CHECK OK: реестр 489 == REGISTRY** ✓.

## 6. Логи / R17

- Окно с 21:07:32 UTC (перезапуск 1 + ~8 мин работы): `ERROR|CRITICAL|Traceback` = **0**; R17-скан (`sk-|Bearer|xox|AKIA|-----BEGIN|api_key=`) = **0** ✓.
- WARNING = 2 контура, оба **known pre-existing**: `embedding pool rotation=none → graph backfill deferred` при старте пула (сигнатура [I-1] 2.58.50–52) + `Received SIGTERM signal` старого процесса при штатной остановке.
- Окно второго рестарта (no-op): `ERROR|CRITICAL|Traceback` = **0** ✓.

## 7. Локальные focused-проверки (до коммитов; полный suite — release policy, НЕ гонялся)

1. Новые сьюты (52+83) → **135 passed / 0 failed** ✓.
2. Миграционный фронтир+смежные (8 файлов) → **315 passed / 0 failed** ✓.
3. K3/K4 focused (`-k "k3_off or k4_off or default_params"`) → **4 passed** ✓.
4. F8 `--check` OK, каталог 489 / Δ=0 ✓ (см. §5).
- Пины бампа: 24 assert-строки в 23 release-пин файлах + метапин — bump 2.58.55; файлы кандидата, кроме `config/settings.py` (только строка APP_VERSION/note), байтово не менялись.

## 8. Incidental findings

- **[I-1][Info, вне дельты]** `plans/workflow_state.md` дрейфовал после манифеста (+84/−14, чужие ноты параллельных сессий) — out-of-scope по review F-6; не коммитил; ретрив-теги/уборка — на commit-плане Orchestrator.
- **[I-2][Info, окружение]** часы сервера отстают от локального календаря dev-машины на ~1 сутки (server `date -u` = Oct 4 21:xx UTC при локальном 05.10.2026). Все временные штампы в этом документе — серверное UTC (как и в предыдущих deploy-фактах). Даты в стампах бэкапа/логов следуют серверному календарю — ковырять TZ не стал (не дельта релиза).
- **[I-3][Cosmetic, pre-existing]** файл-мусор `pre_migration_20261001_161834.db-journal` (1 KB, Oct 1) в корне — не трогал.
- Прод-вещь вне скоупа: живые `mca_events`/`task_jobs` продолжают расти (бот жив) — это работа, а не миграция; не fold-ится в релиз.

## 9. Rollback

- **Soft:** `.env` += `MCA_CHARACTER_LAYERS_ENABLED=false`, `MCA_CHARACTER_SPEECH_ENABLED=false`, `MCA_STYLE_SCOPE_ENABLED=false`, `MCA_POSTPROCESS_FORM_GUARD_ENABLED=false` (+ рестарт) → все поверхности K1–K4 байт-в-бит 2.58.54 (OFF-паритет пруфнут тестами); таблица v26 остаётся (аддитивна, старый код её не читает). Оба TTL-перекрытия при необходимости туда же. Сейчас перекрытий нет (кодовые дефолты ON).
- **Cold:** `git revert` feat-коммита `3d03ff6` (или reset) на предшествующий `495bcf4` (2.58.54) — v26 аддитивна и инертна: старый код таблицу не читает, миграционных откатов НЕ требуется. Аварийный сценарий (повреждение БД): полка `pre_migration_20261004_210851.db` (UV 25, integrity ok, 1.3 GB) — restore по mca-14 процедуре.

## 10. Следующий шаг для Orchestrator

T-4913 закрыт: prod **2.58.55** VERIFIED (feat `3d03ff6` + docs `2a4730a` + этот deploy-doc), миграция v25→v26 идемпотентна, health 200, сосредоточенные повторяемые проверки зелёные, rollback-план известен. **Дальше — T-4914 live-акцепт [PENDING OWNER]** (реальный чат: примеры до/после — сохранённый стиль, адресаты, живая scoped-просьба, шутка ≠ биография, отсутствие техвставок; unfakeable — в реальном чате, имитировать нельзя) → затем T-4915 reconcile/archive (чекбоксы `tasks.md` на архиве, merge §115, ADR-1028-11 → Accepted).
