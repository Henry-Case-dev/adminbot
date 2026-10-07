# deployment.md — asap5-final-fixes 2.58.68 (T-5273, DevOps)

## Итог: **VERIFIED** — 2.58.68 LIVE @ `dd134cc`

Дата: 07.10.2026 · Прод: 198.46.175.136, `/var/www/admin_bot`, systemd-юнит `admin_bot`.
Биндинги: review `review.md` **APPROVED** (0 блокирующих) + scanner `plans/reports/asap5_scanner_audit.md` **«к деплою ДА»** (C0/H0). Финальный деплой программы MCA.

## 1. Кандидат и DEPLOY_SOURCE

- **DEPLOY_SOURCE:** immutable git-коммит `dd134cc` (feat, push ff `e9d71c8..dd134cc` в origin, без force). Прод: `git pull --ff-only` `6f062fa → dd134cc`. **MUTABLE_WORKTREE_REQUIRED: no** (деплой из коммита; локальный worktree использовался только для бампа/прогонов до коммита).
- Состав: 3 лейна ASAP 5 (B1 Summary / B2 Cover / B3 GraphRAG+Random) + release-свип (бамп). Биндинг-манифест `t5270_candidate_hashes.json` (143 файла): **preflight DevOps 142/143 MATCH, 0 missing**, единственный drift `plans/workflow_state.md` — задокументированный чужой WIP (бит-в-бит с review §1/scanner §0).
- Бамп (release-owned, у DevOps по санкции review §1/§1.2.14 до коммита): APP_VERSION 2.58.67→2.58.68 (`config/settings.py:3209`), README header, F8 meta APP_VERSION, py-пины 24 тест-файлов (25 пинов), 4 js-харнесса `2\.58\.68`. Остаточных пинов 2.58.67 в коде — 0 (grep); исторические упоминания в планах не тронуты.

## 2. Прогоны окна

| Набор | Результат |
|---|---|
| Фокус (канон mca-21 21 + asap5-домены 73 + пин-набор 104 + backend_additions 11) | **209 passed** |
| JS по-файлово | **63/63** |
| Полный pytest (foreground, .venv, сегменты G1/G2/G3) | **12422/5** — 4 pre-existing identity (tool_loop/nav_disclosure/status_control/mca09-registry) + mca09-флейк, изолированно зелёный (пара 2/2, файл 15/15); арифметика 12427+11 = **12438 collect** байт-в-байт с барьером T-5270 (12434/4, `full_pytest_t5270.log`); hang #121 нет |
| Полный pytest (оркестратор, контрольный) | **12434/4** — ровно 4 pre-existing identity, 0 новых |
| DDL-инварианты прод (pre→post) | `PRAGMA user_version` **33→33**, tables **120→120** — Δ DDL = 0, **МИГРАЦИЙ НЕТ** (не вызывались; v34 не появлялась, grep журнала DDL-строк = 0) |

## 3. Фазы деплоя (один основной поток + resume-продолжения после безмутационных абортов)

- **A. Pre-state + pull + identity:** HEAD_BEFORE `6f062fa`, healthz `{"status":"ok","version":"2.58.67"}`, DIRTY=13 — **все `??` untracked runtime-джанк** (баки info_text.md.epic*, pre_migration_*-journal, tools/_s41_precheck.py; TRACKED=0) — ff-pull не блокируют (прецедент T-5216); UV=33/120 pre; **KS: `grep -c '^MCA_' .env` = 0 оверрайдов, все 85 ON**; pull `--ff-only` → `dd134cc`; **identity sha256 8/8** (info_service, oversight_router, summary_l2_review, cover_prompt_assembly, graphrag_rebuild, settings, app.js, index.html); settings `2.58.68` ✓.
- **B. Бэкап + рестарт #1:** VACUUM INTO → `/var/www/admin_bot/backups/pre_t5273_20261007_045424.db`, integrity ok, **UV=33, tables=120**, 1.32 GB (rollback-якорь); рестарт #1 → healthz 502×6 → **200 @2.58.68** (systemd-интервал, прецедент mca-12/mca-release).
- **C. Canon-gate + рестарт #2 + батарея:** gate venv-питоном (системный python3 без asyncpg — поправлено на ходу): `content.info_how_it_works` sha `1df850a6…` **ver=6 delivered=6 CANON** (len 9685, маркер G2), `content.intelligence_guide` sha `149ae469…` **ver=3 delivered=3 CANON** (len 27590, маркер G1) — **GATE_DRIFT=0**, гайды mca-21 не затронуты, отдают канон v6/v3; рестарт #2 → healthz 502×4 → **200 @2.58.68** ×2, `/api/health` **200**.

## 4. Health/смоуки (boot #2)

- **healthz 200 @2.58.68** ×2 (после обоих рестартов), `/api/health` 200, `MainPID=203019`, **NRestarts=0**, ExecMainStatus=0.
- Unauth-смоуки (маршруты смонтированы, TMA-RBAC жив): `/api/info` **401**, `/api/info/guide` **401**, oversight **401 ×3** (GET runs, GET funnel, POST jobs action). Live-TMA-приёмка — owner-gate (T-5274), не имитируется.
- **Журнал boot #2** (с `ActiveEnterTimestamp` `Wed 2026-10-07 05:00:51 UTC`, 439→442 строк): **ERROR/CRITICAL=0, Traceback/NameError=0, database-locked=0**, приоритет-батарея `journalctl -p err` = **0**, DDL-строк 0; **`[vision] media worker started` — жив** (boot #2: 1).
- **R17:** журнальный скан 6 паттернов (sk/xox/ghp/AIza/TG/DB-URL) = **0**; локальный скан артефакта `startup_prod_t5273.log` (442 строки) = **0 секретов**; живые chat-ID ×4 — tracked-прецедент startup_prod_t5198/t5216 (I-1 Info, байт-в-байт тот же класс). Приложение лога — `git add -f` по прецеденту.
- Ранние аномальные цифры (533/837/locked 6, total 165k) — артефакт окна `journalctl -b` (аптайм машины, дни истории), устранены окном `--since ActiveEnterTimestamp`; перезамер boot #2 чистый.

## 5. Замечания окна деплоя (операционные, не продуктовые)

1. Два безмутационных аборта старта (жёсткий DIRTY-чек без разделения untracked/tracked; парсинг KS-вывода) — исправлены в деплой-скрипте, прод не затронут.
2. `GATE_ERROR=pg: ModuleNotFoundError` — запуск gate системным python3; переход на прод-venv (`venv/bin/python3`) — gate зелёный.
3. ANSI-глю UITextView-канала рвал числовой парсинг — заменён на remote-python-скрипты с `KEY=value` + regex-парсинг (надёжно).
4. Санкции §1.2.14 цифра-в-цифру подтверждены продом: DDL 0 (v33), каталог 529, KS 85/0 оверрайдов, reason 280, тулы 14, routes-пин `8153b8bd…c7b45` цел (Δ эндпоинтов 0).

## 6. Rollback

- **Soft:** reason-коды/Decision Trace/degraded-публикации — read-side нейтральны; KS 85 не менялись (0 оверрайдов до/после); каноны MCA/гайдов не затронуты (gate CANON v6/v3 до и после); конфиг/env-переключений не было.
- **Cold:** `git revert dd134cc` (+ deploy-doc-коммит) → рестарт; DDL=0 — v33 совместима в обе стороны (pre/post UV=33/tables=120 доказано продом); restore-якорь `backups/pre_t5273_20261007_045424.db` (integrity ok). Канон-откаты гайдов — зелёный прецедент Лейн B (mca-21): версии/слепки через `reset_canon`, не требовались.

## 7. Хвосты (не блокеры, вне окна деплоя)

- F1 (review) / M (scanner): web-слайс CoverPromptManifest T-5252/T-5253 (+T-5266 visual) — до T-5275; серверный субстрат fail-closed, экспозиции нет.
- Advisory: обернуть `database.py:5454` / `embedding_control_plane.py:2022` в `serialized()` при активации future-resume воркера.
- Owner-gates: T-5248/T-5254 (real-provider), T-5274 (live-приёмка).

**Статус: VERIFIED.** Прод `dd134cc` / 2.58.68 / v33 / каталог 529 / KS 85 (0 env) / reason 280 / тулы 14. R17: секретов нет.
