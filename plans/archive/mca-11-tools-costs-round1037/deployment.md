# deployment.md — mca-11-tools-costs (prod 2.58.57)

**Пакет:** `mca-11-tools-costs` (T-4960) — Risk R2 — **Статус: VERIFIED**
**Выполнен:** 05.10.2026 (UTC 01:00:04) — деплой @DevOps T-4960 (Reviewer `Approved` T-4959; санкция F-2: CA-11 bump DEFERRED_TO_RELEASE, исполнен в релизе). Не-блокирующие findings F-1…F-6 (review.md) — вне релиза.

## 1. Binding и preflight

- Кандидат: uncommitted working tree на HEAD `a34e1632538840fe36f6d81446ff6b6ad54db7fa` (master); review **Approved** (review.md, T-4959).
- WTH-манифест Reviewer (24 файла): `plans/reports/mca11_wth_manifest_review.txt`; **sha256 тела (LF, UTF-8, sorted, `path␣␣hash␣␣(origin)`; tracked=`git diff HEAD -- path`, новые=content) = `4d3fe09150f15e1f49062daa5e2a03657db390cd35e91635dc05855bce030407`** — пересчитан @DevOps тем же рецептом, **MATCH; per-file 24/24 нет дрейфа** (drift=0; состав: 13 tracked-diff + 6 новых кода + 5 пакетных доков).
- Сверка санкций (ADR-1028-13): **Δ DDL = 0; Δ каталога = 0 (F8 489); К1–К4 ON + К5 `MCA_MONEY_LIMITS_ENABLED` OFF** (env-only, 0 переопределений; К5-OFF = bit-for-bit 2.58.56); канон инструментов 12; reason codes +1 (`accounting-unknown`).
- Prod pre-state: HEAD `a80cd4b` (2.58.56), MainPID 3757743, active/running, NRestarts 0; `/healthz` 200 `2.58.56`.

## 2. Version bump CA-11 (F-2) и коммиты (явные пути; без `git add -A`)

- **Bump 2.58.56→2.58.57** per convention `1c47b5e/615857c/3d03ff6`: `APP_VERSION` в `config/settings.py:2934` (аннотация mca-11 → Prior-цепочка сохранена) + **23 release-pin test файла** (`APP_VERSION ==`/`'APP_VERSION = "`/`m.group(1)` пины) + F8 meta-pin `plans/docs/param-registry-round1025.meta.md`.
- **feat: `b88bfb1`** — 43 файла (+2938/−76): 13 tracked-diff манифеста (`config/settings.py` + 11 `services/*` + `tests/test_tool_chains_round1026.py`) + 6 новых (`services/tool_result.py`, `services/mca_money_limits.py`, 4 теста mca11) + 23 pin-теста + meta-pin. Диф settings.py = ревью-пин + добавка APP_VERSION-бампа (санкция F-2 — единственное отклонение от пина review, см. review.md §Binding).
- **docs: `9f4989c`** — 7 файлов (+646): `plans/features/mca-11-tools-costs/{spec.md, adr-1028-13-tools-costs.md, tasks.md, requirements-map.md, evidence.md, review.md}` + `plans/reports/mca11_wth_manifest_review.txt`.
- **deploy-doc:** этот файл (коммит после deploy, docs-only).
- push origin/master: **`a34e163..9f4989c`** (без force). Исключены (per манифест-заголовок): `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md`, untracked debris (`node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*`, `plans/verification_cache.json`).

## 3. Деплой (leave-fast, тайм-стемпы UTC)

- Прод: `git pull --ff-only origin master`: `a80cd4b..9f4989c` fast-forward ✅; untracked мусор не мешал.
- Restart: `sudo -n systemctl restart admin_bot` rc=0 в **01:00:04 UTC**; MainPID **3774675**, ActiveEnter **Mon 2026-10-05 01:00:04 UTC**, ExecMainStatus=0, **NRestarts=0** (старый PID 3757743, uptime 01:18:59).
- `/healthz` «200 @ `{"status":"ok","version":"2.58.57"}`» — **первая же попытка**; `/api/health` **200** `{"status":"ok"}`.

## 4. Миграции/DDL — Δ DDL = 0 (SQLite v26 не тронут)

- `PRAGMA user_version` **26=26**; `schema_migrations` **15=15** (`v27` **не существует**); total tables **100=100**; `mca_money*`/`money_*` таблиц **0** (D5 — без DDL).
- Журнал: 0 строк `migration v27`/`pre-migration copy`; миграционные INFO = idempotent («уже новый канон», prompt/config миграции — R17-safe); MemoryBackup scheduler — штатно (daily 05:00).

## 5. Спот-проверки данных (pre → post)

- SQLite: `task_jobs` **642→643** (+1 live), `summary_runs` **13=13**, `summary_source_windows` **13=13**, `mca_events` **10108→10111** (+3 live при boot — канал notable, как в 1036), `mca_style_requests` **0=0**, `mca_bot_outputs` **74=74**, `llm_usage_events` нет в SQLite (PG).
- PG: tables **26=26**; `cover_style_issue_assignments` **17=17**; next counter **18=18**; `cover_style_assets` **13=13**; `cover_style_provenance` **24=24**; `llm_usage_events` **2890=2890** — byte-равно pre; счётчики/override/config **0 изменений**.

## 6. Kill-switches / F8

- `.env`: **0 переопределений** по `MCA_CHAT_STATISTICS_ENABLED`/`MCA_NUMERIC_CLAIM_GUARD_ENABLED`/`MCA_STATS_INTENT_ENABLED`/`MCA_TOOL_CHAIN_STAGES_ENABLED`/`MCA_MONEY_LIMITS_ENABLED` + `MCA_MONEY_LIMIT_*` + `MCA_TOOL_TRANSIENT_RETRIES_MAX` (grep = 0 по каждому) → K1–K4 **default ON**, K5 **default OFF**; money-лимиты инертны (caps None/unset).
- **Δ каталога = 0:** `gen_param_registry_round1025.py --check` (prod venv, pre-restart) → **CHECK OK: реестр 489 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны**.

## 7. Focused-проверки (не полный suite; до commit и pre-restart на prod-venv)

1. **Локально (pre-commit, post-bump):** mca11 новые + `test_tool_chains_round1026` → **138 passed (4.13s)**; mca22/safe_fetch/tool_router → **166 passed (5.53s)**; mca15/media/image → **140 passed (4.46s)**; direct/negative/image_generation → **265 passed (17.83s)**; `test_tool_loop + test_migrate_env_to_pg` → **2 failed / 30 passed** (ровно 2 pre-existing red, см. §9).
2. **Prod-venv (pre-restart):** mca11 новые + `test_tool_chains_round1026` → **138 passed (21.63s)**; F8 --check → OK 489.
3. Суммарно локально: **709 passed / 2 failed (обе — документированные pre-existing)**.

## 8. Логи / R17 (после ActiveEnter 01:00:04 UTC)

- **ERROR/CRITICAL/Traceback = 0** (окно 170 строк, до 01:04:28 включительно); R17-паттерны (`sk-`/`Bearer`/`AKIA`/`-----BEGIN`/`*_api_key=`/`xox[bpa]-`) = **0**.
- WARNING 5: 1× `SIGTERM` (штатная остановка старого PID), 4× embedding-quota (см. §10 — pre-existing квотный механизм, не mca-11).

## 9. Rollback

- **Soft (первый выбор):** `.env` += `MCA_CHAT_STATISTICS_ENABLED=false` / `MCA_NUMERIC_CLAIM_GUARD_ENABLED=false` / `MCA_STATS_INTENT_ENABLED=false` / `MCA_TOOL_CHAIN_STAGES_ENABLED=false` (+ K5 остаётся false по умолчанию) — K1/K3-OFF = бит-в-бит 2.58.56, K2/K4/K5-OFF = legacy-оболочка (env-only; K1 payload 30/30, K2/K3/K5-OFF проверено тестами; SQLite v26 полностью архитектурно совместим). Применение env-флагов — с одним рестартом admin_bot (kill-switch читаются при boot).
- **Cold:** `git revert` feat-коммита `b88bfb1` (либо checkout `a34e163` = 2.58.56). Дополнительные рестарты/DDL безопасны: Δ DDL = 0, v27 отсутствует, PG no-op; emergency-восстановление через daily MemoryBackup (05:00 Asia/Yekaterinburg, backup_ref в task-состоянии).

## 10. Incidental findings (не связаны с mca-11; для Orchestrator)

- **[I-1][не блокер][pre-existing]** `services.embedding_control_plane` — embed rate limit 429 (group=unknown, `state=exhausted`, cooldown ≈23ч, `parked=1`, 429_last_10m=1) →
  deferred «SmartModule graph backfill» и «EMBEDDING_GENERATION_PAUSED graph_facts_vec» (checkpoint preserved). Это штатный fail-closed механизм `EMBED_QUOTA_KIND_PARKING` (round1030); известное поведение, не изменилось деплоем 2.58.57; text/plain-пути не блокирует.- **[I-2][Info][pre-existing]** «embedding pool rotation=none | group=unknown | keys=3 | hint=EMBEDDING_QUOTA_GROUP_LABELS» — известная warning round1030/1042 (подсказка к настройке групп-quota-меток), не блокер.
- Оба — вне mca-11; трекинг через backlog/monitoring, присущие prod-окружению; проявились сразу после рестарта.

## 11. Заключение @DevOps

T-4960 выполнен: prod **2.58.57 VERIFIED** (feat `b88bfb1` + docs `9f4989c` + deploy-doc этот файл), preflight 24/24 с drift=0, Δ DDL = 0 (v26=26), Δ каталога = 0 (F8 489 — CHECK OK), kill-switches по манифесту (K1–K4 ON, K5 OFF; 0 env-переопределений), health 200 x2, focused-проверки целы (локально 709 passed / 2 документированных red; prod-venv 138 passed), логи чистые (0 ERROR/CRIT/Traceback, R17=0), PG no-op, данные intact, counters/override/config — 0 изменений. Rollback: soft env-off K1..K4 + cold git revert `b88bfb1`.
**Следующий шаг:** live-приёмка **T-4961 [PENDING OWNER]** (реальный чат: цепочка/затраты в tool-surface, envelope L2, media/gating — по спеке §7; см. tasks.md §9.6). После T-4961 — @Architect/Archive: ADR-1028-13 → Accepted, merge, метрики.
