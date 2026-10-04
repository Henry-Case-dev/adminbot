# deployment.md — asap-4-4-final-live-closure (prod 2.58.52)

Feature: `asap-4-4-final-live-closure` · Risk R3 · **Статус: VERIFIED**
Дата: 05.10.2026 (UTC) · Исполнитель: @DevOps · Задача T-4886 (owner spec §9; review.md T-4885 + аддендум F-N1)

## 1. Binding и окружение

- Кандидат: uncommitted working tree на HEAD `04e615d`; review **Approved** (`plans/features/asap-4-4-final-live-closure/review.md`, аддендум §8 «F-N1 resolved — recheck bounded rework» от 05.10.2026).
- WTH-биндинг: `plans/reports/asap44_wth_manifest_review.txt` — HEAD `04e615da9b9e03d056658ca7f02cc334089b4fec`, files=80, sha256(manifest) `75E9AEAD96F64B9D0F8BA67DA67ECA3F64C63CE00409BECC608418F773F7C0F1`, рецепт §6 review.md.
- **Preflight (DevOps самостоятельно):** per-file sha256 пересчитан по манифесту — **80/80 файлов size+sha256 совпали, drift=0**; sha256(манифеста) = декларации; HEAD == биндингу; аддендум присутствует. Дрейф после манифеста санкционирован только release-бампом (§2) — вне манифеста, по конвенции прошлых релизов.
- Прод: `nik@198.46.175.136:/var/www/admin_bot` (racknerd-f4e3456), systemd `admin_bot`, Ubuntu 24.04, venv `/var/www/admin_bot/venv` (Python 3.12, asyncpg). Диск: 5.8G free, load ~0.02.
- Деплой-авторизация: Orchestrator (T-4886; review Approved + re-bound аддендумом; пост-деплой §9 live A/B обязателен, но вне этого деплоя).

## 2. Коммиты

- **feat: `09fd5a8`** — runtime 12 (`cover_style_edit/jobs/pipeline/preview/registry`, `embedding_control_plane`, `execution_graph_source`, `image_capabilities`, `param_catalog`, `summary_l2_anchor_repair`, `summary_l2_review`, `summary_memory`) + web 3 (`web/api/cover_styles.py`, `web/app.js`, `web/index.html`) + тесты/фикстуры 59 по манифесту (вкл. `tests/fixtures/round1025/{catalog,f8}_baseline.json` и 3 новых asap44-py + 1 js) + **version bump**: `config/settings.py` APP_VERSION **2.58.52** + 23 release-пина тест-файлов по конвенции последних релизов (`1c47b5e`/`acbbe1f`: ровно те же 23 файла; 19 из манифеста + 4 вне манифеста — `test_scope_selector_round1025`, `test_webapp_design_tokens_round1025`, `test_webapp_f6_round1025`, `test_webapp_hotfix6_round1025`). **79 файлов, +3396/−476.**
- **docs: `1a6b5ba`** — 6 plans-docs манифеста (4.4 packet: evidence/requirements/tasks + F8: `param-registry-round1025.tsv`, `param-registry-round1025.meta.md` — meta APP_VERSION-пин приведён к 2.58.52 по конвенции F8; `screen-map-round1025.md`) + `review.md` (в манифест не входит; конвенция docs-коммитов 4.х) + WTH-манифест (конвенция docs-коммита 4.3) + `plans/features/asap-4-3-cover-style-surgical/canary-evidence.md` (RC-A live-пруф + §7.2 422 finding; docs-only, вне runtime-манифеста). **9 файлов, +801/−8.**
- **deploy-doc** — этот файл (docs-only; прод-runtime от него не зависит, второй рестарт не требуется; прод-дерево осталось на `1a6b5ba`, runtime-часть байт-равна — проверено §4).
- **`git add` только явными путями** (никогда `-A`): НЕ попали в коммиты `plans/metrics.md`, `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, `node_modules/`, `package*.json`, `.playwright-mcp/`, `plans/verification_cache.json`, `tools/_ui_asap43_*` ✓ (коммит-гигиена T-4866).
- origin/master push: `04e615d..1a6b5ba` (деплой) ✓ и deploy-doc — отдельным push (ниже, docs-only).

## 3. Деплой (факты)

- Прод до деплоя: HEAD `1c11336` (2.58.51), MainPID 3610541, NRestarts=0, /healthz 200.
- `git pull --ff-only origin master`: **`1c11336..1a6b5ba` fast-forward** ✓ (89 файлов — в диапазон входит также `04e615d` — docs-chore деплоя 2.58.51; untracked-копии `info_text.md.bak.epic*` конфликтов не давали).
- **Рестарт**: `sudo -n systemctl restart admin_bot` → rc=0; **active с Sun 2026-10-04 15:45:33 UTC, MainPID=3651908, NRestarts=0, ExecMainStatus=0** ✓.

## 4. Health / раздача

- `GET :8000/healthz` → **200** `{"status":"ok","version":"2.58.52"}` (спустя ~6 сек prod ещё поднимался, 200 на 15:46:17) ✓; `/api/health` → **200** ✓.
- Страница `/web/` отдаёт `?v=2.58.52` (2 вхождения — заголовок+запрос) ✓.
- Байт-паритет prod ↔ WTH-биндинг (sha256 на проде): `web/app.js` `71BEDD2D…`, `web/index.html` `EB3BC883…`, `cover_style_preview.py` `538CB8BD…`, `cover_style_registry.py` `B0802D53…`, `cover_style_jobs.py` `1E42568E…`, `cover_style_edit.py` `2F0C2BF6…`, `image_capabilities.py` `CE28E1A0…`, `summary_l2_review.py` `51A3319E…` — все == манифесту ✓ (runtime-файлы бампом не менялись: бамп = settings.py + 23 тест-файла + meta.md).
- Runtime код на проде = байт-часть feat-коммита `09fd5a8` (входит в `1a6b5ba`).

## 5. Миграции / DDL

- **SQLite: `PRAGMA user_version` 25 → 25, `schema_migrations_max` = 25 — ΔDDL = 0** ✓ (read-only PRAGMA после рестарта; 4.4 не вводит SQLite-DDL).
- **PG: НОВЫХ DDL в скоупе 4.4 нет ни одного** — `cover_style_profiles.preview_job_id` (additive nullable text) присутствует; фактически DDL-операций не выполнялось (`pg_db.py` и реестр поколений в 4.4-диффе не тронуты; report actual = none).
- **Данные целы (spot-check):** PG `cover_style_*` = 6 таблиц: assets **11**, connections **0**, issue_assignments **13**, profiles **1** (Medved seed), provenance **19**, references **1**; SQLite: task_jobs **626**, summary_runs **8**, summary_source_windows **8**, mca_events **9390**. Сравнение с деплой-фактом 2.58.50 (assets 6 / issue_assignments 11 / provenance 13) — рост только от live-канари 4.3 (Canary A repeat + повторный test-run), потерь/аномалий не видно ✓.
- **Counter state (live):** `cover_style_profiles.MAX(counter_value)` = **13** (внутреннее last_assigned), issue_assignments = 13 → `next_issue_number` = **14** на момент деплоя (live-стейт после Canary-фазы 4.3 + живых прогонов). Для §10 «next = 11» перед Canary A требуется owner-нормализация (NOTE 10: «counter normalized to next=11») — через новый UI-контракт (MiniApp «Следующий номер»), prod-DB напрямую не правим. НЕ блокер деплоя: 4.4-семантика (`next = counter_value+1`) совместима с этим стейтом.
- **§11-предусловие (Special Q4 #1):** `bot_settings` ключ `cover_style.prompt_limit_overrides` **ОТСУТСТВУЕТ** (manual 800 override не персистировался 05.10, снимать нечего; blind-800 on Pro запрещён §11) ✓; prod `.env`: 0 вхождений `COVER_STYLES_*/COVER_STYLE_*/IMAGE_PROMPT_*/MCA_DREAM_*` → кодовые дефолты (COVER_STYLES_ENABLED ON) ✓.

## 6. Проверки (только фокусные; полный suite НЕ запускался — release policy не требует, диф не меняет shared runtime)

Локальный venv `.venv` (после бампа; до коммитов):
1. **Cover focused** (`tests/test_asap44_cover_final_closure.py`) + **L2** (`test_asap44_l2_review_closure.py`) + **GraphRAG** (`test_asap44_graphrag_batch_breaker.py`) → **38 passed / 0 failed** (19+8+11) ✓ == пруф Reviewer.
2. **F-N1/каталог-пины** (`test_round1025_f8_registry.py`, `test_budget_data_repair_round1024.py`, `test_budget_guardrails_round1024.py`) → **85 passed / 0 failed** ✓ (было 82+3 red до микро-раунда F-N1).
3. **Legacy cover / release-пины**: `test_extra_cover_style_registry.py` + `test_scope_selector_round1025.py` → **53 passed**; `test_webapp_round1026_polygon.py` + `test_webapp_f11_round1025.py` → **56 passed** ✓ (бамповые пины двух форм `APP_VERSION ==`/`m.group(1)`/`in SETTINGS`).
4. **F8 каталог**: `python tools/gen_param_registry_round1025.py --check` → **CHECK OK: реестр 489 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны**, exit 0 ✓ (каталог Δ = ровно **+1** ключ `keys.embedding_quota_group_labels`; F8 re-issue 489/delta 78).
5. **JS**: `node --check web/app.js` → OK; `node tests/js/asap44_cover_final_closure_test.js` → **OK exit 0** ✓.

Прод-venv (после рестарта, `/var/www/admin_bot/venv`):
6. **asap44 focus** (те же 3 файла) → **38 passed / 0 failed (24.9 с)** ✓.
7. **Ladder/parity** (`test_extra_cover_style_registry.py` + `test_cover_styles_contract_asap32.py`) → **48 passed** ✓.
8. **RBAC unauth**: `POST /api/cover/test-style` → **401**; `GET /api/cover/test-style/{id}` → **401**; `GET /api/cover/prompt-limit` → **401**; `GET /api/cover/styles` → **401**; `GET /api/cover/capabilities` → **401**; `GET /api/cover/connections` → **401** — все реальные cover-руты защищены ✓.
9. **Логи (окно с 15:45:30 UTC, 170 строк):** ERROR|CRITICAL|Traceback = **0**; R17-скан (`sk-|Bearer|xox|AKIA|-----BEGIN|api_key=`) = **0** ✓; WARNING = **2**, оба известные pre-existing контуры (embedding pool `rotation=none` при старте пула + SmartModule graph backfill deferred — сигнатура раундов 1030–1032, деплой-факт [I-1] 2.58.50; теперь hint печатает `EMBEDDING_QUOTA_GROUP_LABELS` — новый ключ каталога 4.4).
10. Отдельный Playwright UI-смок на деплой не потребовался (по процедуре — критический changed flow это Live Canary A/B на плановой фазе; UI-артефакты покрыты JS-test + байт-паритет `app.js/index.html` §4; браузерная матрица Reviewer'а не повторялась).

## 7. Incidental findings

- **[I-1][Known, pre-existing]** warning-контур `embedding pool rotation=none → SmartModule graph backfill deferred` в стартовом окне — немедленного прод-риска нет (deferred по расписанию resume), документирован в 2.58.50 §7. НЕ расценивается как регрессия 4.4.
- **[I-2][Info, live-state]** counter live-стейт: MAX(counter_value)=13 → next=14 (см. §5). К Canary A нужно привести к 11 через редактор или явно документировать реальный прогон (покупка номеров живыми публикациями между 4.3 и 4.4). К Canary-агенту, не деплой.
- Новых инцидентных находок самого деплоя нет; F-N2–F-N5 из review — вне деплойного scope (Runtime/UI-детали), остаются на Orchestrator-триаж.

## 8. Rollback

- **Soft:** `COVER_STYLES_ENABLED=false` (+ рестарт) → базовая обложка/публикация живы, 4.4-styled контур OFF; `EMBED_QUOTA_KIND_PARKING_ENABLED=false` — прежний cooldown (если batch-breaker ведёт себя нештатно в production топологии). Оба env-only; prod `.env` сейчас их не содержит (кодовые дефолты).
- **Cold:** revert/reset к прод-предшествующему `1c11336` (2.58.51). ΔDDL=0 (SQLite 25↔25; PG-DDL новых в 4.4 нет, `preview_job_id` уже в проде) — миграционных откатов НЕ требуется, старый код совместим с текущей схемой; restore БД не нужен. Данные целы (§5).
- Backup-полка не потребовалась (untracked-мусор конфликтов не дал).

## 9. Next — LIVE acceptance (обязательный §9 owner spec; НЕ выполнено в этом раунде)

- **T-4887 Canary A** (real Test Style provider, before/after assets через новый registry-путь) → **Save/reopen** → **T-4888 Canary B** (issue ladder: установить next=11 через UI, Test Style рисует «ВЫПУСК 11», retry не расходует, next=12; publication = `styled`, НЕ `base_fallback`) → **T-4889 GraphRAG controlled repro** (нет warning-storm; quota-topology keys/groups/rotation/next_allowed_at видна без секретов).
- Исполнители: @Orchestrator/@DevOps с реальными кредами/UI (§11 мок-замены запрещены); job/run id зафиксировать в `evidence.md` §3/§4/§6; затем §12 отчёт + архив + возврат к MCA.
- **Paid canaries в этом деплое НЕ запускались**; prompt-limit overrides и counter state НЕ тронуты (manual 800 от 05.10 — отсутствует по §11; verify в §5).

## 10. Special Q4 — подтверждения деплоисполнителя

1. Manual 800 override ABSENT ✓ (факт: попытка 05.10 по §7.2 HTTP 422 — не персистировалась; §5).
2. «next = 11» достижим новым UI-контрактом (единый контракт UI/API/DB).
3. PG-DDL новых нет; SQLite Δ=0; health/version/commit — §3/§4; R17-мониторинг §6 #9; Inspector/логи — только id/коды, без текстов/секретов.
4. График §9 (T-4887 → T-4888 → T-4889) — как в §9; финальное закрытие 4.4 только после их успеха (DoD §10 owner spec).
