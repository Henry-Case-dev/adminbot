# deployment.md — mca-15-chat-statistics (prod 2.58.56)

Фича: `mca-15-chat-statistics` — Risk R3 — **Результат: VERIFIED**
Дата: 05.10.2026 (дев-календарь; сервер-факты в UTC 04.10.2026 23:3x–23:4x — известный день-лаг [I-2], прецедент mca-08) — ответственный: @DevOps по T-4939 (review.md T-4938 вердикт `Approved`; санкции ADR-1028-12; deploy §9.6 spec, CA-11)

## 1. Binding и preflight

- Кандидат: uncommitted working tree поверх HEAD `f1cacbd21c229121ef24a3d20c17c230fd9c3d7e`; review `Approved` (review.md, T-4938, один вердикт, без rework).
- WTH-манифест: проверка @DevOps per-file sha256+size (независимо от Reviewer) → один инцидент [I-1] и его разрешение:
  - изначально `plans/workflow_state.md` (процесс-журнал @Orchestrator, out-of-scope F-5) показал drift vs ревью-пин (+1551 B, префикс-хэш не совпал → mid-file правки при параллельных сессиях);
  - **санкция @Orchestrator (05.10.2026):** запись журнала УДАЛЕНА из манифеста (без замены хэша), остальные 28 продуктовых записей байт-в-байт; продукт 28/28 байт-в-байт идентичен ревью-снепшоту; вердикт `Approved` НЕ менялся;
  - конечный агрегатный sha256 манифеста (28 записей; рецепт path|bytes|sha256hex, LF/ASCII/trailing-newline/sort-by-path): **`2B2EE1C9409ED0222DB1D33768613214B864B2F598B565BE0B23D1AE19C78FE1`** (зафиксирован в review.md §5 Binding note).
- Урок (процесс): **фичевые биндинги НЕ должны включать непрерывно редактируемые процесс-журналы** — они гарантируют ложные drift-срабатывания и форсируют ручные фиксы биндинга.
- Prod pre-state: HEAD `2a4730a` (2.58.55), MainPID 3730314, ActiveState active, NRestarts 0; `/healthz` 200 `{"status":"ok","version":"2.58.55"}`.

## 2. Коммиты (git add — только явные пути; чужой dirty/untracked не включён)

- **feat: `35c1c71`** — 45 файлов (+4219/−167): манифестный runtime (14 services incl. новый `services/chat_statistics.py` + `config/settings.py`) + манифестные тесты (6: новый `tests/test_mca15_chat_statistics_round1028.py` + 5 правок) + **bump 2.58.55→2.58.56**: `APP_VERSION` в settings.py с mca-15-преамбулой (проверка «инверт-замены == ревью-пин `8127D5BC…AD98A2`» → **целевой дифф settings.py ровно APP_VERSION-строкой**) + **23 release-pin тест-файла** per `1c47b5e/615857c/3d03ff6` конвенция + F8 meta-pin `plans/docs/param-registry-round1025.meta.md` → 2.58.56.
- **docs: `a80cd4b`** — 8 файлов (+996): `plans/features/mca-15-chat-statistics/{spec.md, adr-1028-12-chat-statistics.md, threat-failure-analysis.md, tasks.md, requirements-map.md, evidence.md, review.md, _review_wth_manifest.txt}` (docs-bundle как отревьюено + Binding note §5).
- **deploy-doc:** отдельный коммит (этот `deployment.md`, docs-only).
- Исключено из стейджа: `plans/workflow_state.md`, `plans/docs/mca-round1027-arch-frames.md` (чужой dirty), untracked-junk (`node_modules/`, `package*.json`, `.playwright-mcp/`, `plans/verification_cache.json`, `tools/_ui_asap43_*`).
- push origin/master: `f1cacbd..a80cd4b`.

## 3. Деплой (leave-fast, без даунтайма контура миграций)

- `git pull --ff-only origin master`: `2a4730a..a80cd4b` fast-forward (untracked тронут не был); origin_sha `a80cd4b`.
- restart 1: `sudo -n systemctl restart admin_bot` rc=0 в **23:36:27 UTC**; MainPID **3757743**, ActiveEnterTimestamp **Sun 2026-10-04 23:37:27 UTC**, ExecMainStatus=0, **NRestarts=0**.
- `/healthz` → **200 @ `{"status":"ok","version":"2.58.56"}` через ~6.5 с опроса** (первый 200 ≈ 23:37:35 UTC, полный старт < 1 мин; без VACUUM — миграций нет); `/api/health` → **200** `{"status":"ok"}`.

## 4. Миграции / DDL — ΔDDL = 0 (санкция ADR-1028-12 D8; SQLite v26 не тронут)

- **Backup-guard не запускался, миграционных строк нет**: журнал окна запуска содержит только INFO `prompt_migrations` (идемпотентные патчи промптов, R17-safe) — **0** строк `migration v27` / `pre-migration copy` / `backup`.
- SQLite: `PRAGMA user_version` **26 → 26**; `schema_migrations` **15 → 15 строк** (`v27` **отсутствует**); total tables **100 → 100**; новых таблиц **0** по маскам `mca_chat*`/`cs_*` (нового durable-хранилища нет — правило D4: метрики вычисляются на лету + watermark).
- PG no-op: public tables **26 → 26**; `mca_bot_outputs` в PG отсутствует (SQLite-only, CoreData-инвариант mca-22 — подтверждено `to_regclass`); counters/assignments/assets/provenance байт-равны пререстарту (см. §5).

## 5. Целостность данных (spot-check pre → post)

- SQLite: `task_jobs` **641 → 642** (live +1 — фоновая активность бота, естественное движение борды; НЕ действие деплоя), `summary_runs` **13 → 13**, `summary_source_windows` **13 → 13**, `mca_events` **10024 → 10027** (live +3 при старте: сервисные события загрузки, notable-контур не тронут), `mca_style_requests` **0 → 0**, `mca_bot_outputs` **74 → 74**.
- PG: `cover_style_issue_assignments` **17 → 17**, next counter `MAX(counter_value)+1` **18 → 18** (`cover_style_profiles.counter_value` не тронут), assets **13 → 13**, provenance **24 → 24**.
- Kill-switches/контент: counter/override/config состояния **0 изменений** со стороны деплоя.

## 6. Kill-switches / окружение

- `.env` на проде: записи `MCA_CHAT_STATISTICS_ENABLED` / `MCA_NUMERIC_CLAIM_GUARD_ENABLED` / `MCA_STATS_INTENT_ENABLED` / `MCA_CHAT_STATS_OCCURRENCE_MAX_ROWS` / `MCA_CHAT_STATS_EXAMPLES_MAX` — **0 overrides** (grep count = 0 по каждой) → K1–K3 **default ON** (env-only ClassVar defaults), лимиты **20000/20 по умолчанию**; файл `.env` деплой не менял.
- Δ каталога = 0: F8 NOT_APPLICABLE; `gen_param_registry_round1025.py --check` на prod venv → **CHECK OK: реестр 489 == REGISTRY** (TSV/map идемпотентны, R17-чисто).

## 7. focused-проверки (без полного suite — release policy; gateway CA-11 выполнен)

1. Локально (pre-commit), post-bump дерево: `tests/test_mca15_chat_statistics_round1028.py` → **91 passed (3.41s)** — байт-в-байт число ревью.
2. Repeat pin-класса после bump: `test_round1025_f8_registry.py` + `test_webapp_round1026_polygon.py` + `test_summary_deploy_round1026.py` → **78 passed** (пины APP_VERSION/мета F8/ΔDDL-инвариант).
3. Representative adjacent: интегрированный срез mca15-5 (7 файлов: tool_router, negative_constraints_round1022, database, tool_schemas, summary_memory, memory_core_round1020, scanner_fixes_round1020) → **336 passed (10.73s)**.
4. K-связка (mca-08 × K2 mca-15): `test_mca08_character_speech` + `test_mca08_style_form` + `test_verbilizer_response_modes_round1023` + `test_anticliche_semantics_round1025` → **214 passed (4.68s)**.
   Итого локально: **719 passed / 0 failed**; числа ревью (91/336/214) воспроизведены идентично.
5. Prod-venv (фокус повторного деплоя): `test_mca15…` + `test_tool_router` + `test_negative_constraints_round1022` → **169 passed / 0 failed (25.24s)**; 2 warnings = pre-existing `PytestConfigWarning: Unknown config option: timeout` (env-artifact, известен с mca-08).

## 8. Логи / R17

- Окно от `ActiveEnterTimestamp` (23:37:27 UTC): `ERROR|CRITICAL|Traceback` = **0**; R17-скан (`sk-`/`Bearer`/`AKIA`/`-----BEGIN`/`*_api_key=`/`xox[bpa]-`) = **0**; уровень WARNING = **0**.
- Выходное упоминание только INFO `prompt_migrations` (идемпотентные патчи, коды/имена ключей — R17-safe).

## 9. Rollback

- **Soft:** `.env` += `MCA_CHAT_STATISTICS_ENABLED=false`, `MCA_NUMERIC_CLAIM_GUARD_ENABLED=false`, `MCA_STATS_INTENT_ENABLED=false` (+ рестарт): OFF = байт-в-бит 2.58.55 (паритеты закреплены тестами: K1 payload 30/30, build_fts_query 9/9, K2 env-прогон, K3 `("",None)`, all-OFF полный паритет; честные `disabled`/`not_run` в реестре). SQLite v26 остаётся — старый код её читает (v26 мультивалидна). env-лимиты не требуют отката (bounded-scan).
- **Cold:** `git revert` feat-коммита `35c1c71` (или checkout `2a4730a` — 2.58.55; **никаких миграций/DDL/бэкапов не требуется**: ΔDDL=0, каталог 489 не тронут, PG no-op). Emergency-полка не создавалась (нет мутации данных), целостность подтверждена §5.

## 10. Incidental findings (для Orchestrator, не блокеры релиза)

- **[I-1][решено в деплое]** drift процесс-журнала в биндинге — разрулено санкционированной правкой манифеста; урок зафиксирован в §1/review.md §5. Рекомендация: PM при следующей архитектурной каске описать правило «в биндинг — только продуктовые файлы» (можно аналогично [I-1] mca-08).
- **[I-2][Info, известный]** сервер-часы отстают от дев-календаря ~1 сутки (сервер 04.10 23:3x UTC vs 05.10.2026 деплой-дата) — прецедент mca-08 [I-2]; факты в UTC.
- **[I-3][Info, pre-existing]** untracked-junk (`node_modules/`, `package*.json`, `.playwright-mcp/`, `tools/_ui_asap43_*`, `plans/verification_cache.json`) — вне скоупа, не тронут (F-5 ревью; известен Orchestrator).
- Live-активность во время деплоя: task_jobs 641→642, mca_events 10024→10027 — бизнес-фоновые события живого бота (деплой не triggered); состояние counter/override/config не менялось.

## 11. Финализация и выход @DevOps

T-4939 завершён: prod **2.58.56 VERIFIED** (feat `35c1c71` + docs `a80cd4b` + deploy-doc отдельным коммитом), ΔDDL=0, миграций нет, health 200, kill-switches default ON 0 overrides, focused-лестница зелёная, rollback-пара известна. **Далее — T-4940 live-верификация [PENDING OWNER]** (реальный чат: подкол без просьбы → нет отчёта; явная просьба → проверяемое число с единицей/областью; диагностика по trace; unfakeable сценарии) и затем T-4941 reconcile/archive (tasks.md статусы, merge §116, ADR-1028-12 → Accepted). DevOps live-чат НЕ проверял и не имитировал.
