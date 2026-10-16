# integration-evidence — ASAP 8 v6.3 live correction

Артефакт, требуемый строкой `source-lines-37423-EOF.md:409` (B12.1). Здесь
зафиксировано, **что именно интегрировалось в каждой волне**, какими
тестами/пробами это проверялось, в каких артефактах лежит доказательство и
каким коммитом. Деплой-кандидат всего эпика:
`c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79).

## 1. Волны

| Волна | Коммит(ы) | Что интегрировано | Тесты/пробы | Артефакты |
|---|---|---|---|---|
| W0 — карта и база | `bc91b902` | карта покрытия 222 позиций, source-reconciliation, baseline-inventory, waves, review-coverage, b10 baseline, w2-contract | `requirements_gate.py check --stage plan` → exit 0 | `requirements-map.json`, `requirements-map.md`, `source-reconciliation.md`, `baseline-inventory.md`, `waves.md`, `review-coverage.md`, `baseline-pytest-b10.md`, `w2-contract.md` |
| W1 — backend P0 | `1e24eca4` (+docs `f1418d78`, фикс `72cab8fc`) | B01 initiative observer, B02 semantic Experience, B03 expired-память + D06-fix, B09 supergroup-перенос, B04 style-EDIT, B06 per-chat Summary, B07 temporal в Фактчеке; join: settings ClassVar, `chat_migration` write в `serialized()` (mca01 single-writer), catalog re-pin 561→571/536→546 | pytest W1-файлы зелёные; REV-W1: фокус 108 passed + смежные 426 passed; после фикса B09 — 39 passed | `w1-reports/W1-CHAT-INTEL.md`, `W1-MEMORY-MIG.md`, `W1-COVER-MODULES.md`, `W1-REPIN.md`, `w1-reports/B10-TESTFIX.md`, `review-w1.md` |
| W2 — frontend P0 | `c0535280`, CORR-1 `db8dae53` | U01 мобильная шапка/«Ещё», U02 dropdown Аналитики, U07 FullscreenPolicy, U08 optical glass; фон (`polygon-background.js`, aurora) не тронут | node tests/js 81/81; pytest 9 файлов 231 passed; Playwright SHELL 129/129, FULLSCREEN 7/7 (70 проверок), GLASS сканлайн-корреляция | `w2-evidence-shell/*`, `w2-evidence-fullscreen/*`, `w2-evidence-glass/*`, `ui-acceptance.md`, `w2-reports/W2-SHELL.md`, `W2-FULLSCREEN.md`, `W2-GLASS.md`, `W2-REPIN.md`, `review-w2.md` |
| W3-pre — B08+B11 backend | `4b64b38e`, `ccdd0a76`, фикс `f8f9d9a0` | детерминантная сборка Stories (content_status, три даты, участники ≤5, bounded backfill), read-only отчёт по 10 механизмам | `test_asap8_v63_b08_stories.py` + `test_asap8_v63_b11_report.py` 39 passed; смежные 94 passed | `w3-reports/W3-STORIES-MECH.md`, `review-w3-stories-mech.md`, `tools/v63_b11_mechanisms_report.py` |
| W3a — B05/U06/U03/U04 | `2d95689e` | редактор обложек (opaque surface, серверные снимки, guard), U06 порядок панелей, U03 один блок Сна + 1970-фикс + воронки, U04 логи только в Статусе | EDITOR e2e 40/40; STATUS e2e 26/26; js ~85 файлов; pytest 203+551+73+401+7 | `w3-evidence-editor/*`, `w3-evidence-status/*`, `w3-reports/W3-EDITOR.md`, `W3-STATUS.md` |
| W3b — U05/B08-UI/B06-UI/B07-UI/B01.4-UI | `da58e24b` | 7 визуализаций Аналитики на durable-данных, карточки Stories, B06 chat-scope Summary, B07 «Время и источники», B01.4 профиль частоты | ANALYTICS e2e 74/74; MODULES e2e 42/42; js 84/84 (на том кандидате); REV-W3 перепрогон: EDITOR 40/40, STATUS 26/26, ANALYTICS 74/74, pytest 237 passed | `w3-evidence-analytics/*`, `w3-evidence-modules/*`, `w3-reports/W3-ANALYTICS.md`, `W3-MODULES-UI.md`, `review-w3.md` |
| Release | `c2775a54` | bump 2.58.79, APP_VERSION/README/версионные пины 24 py, F8-meta reissue | версионные/F8-тесты зелёные | `live-canary.md`, `release-reconciliation.md` |
| W4 — живые пробы и аудит | — (docs `225c3c2b`, `a854ad95`) | прод-факты, V01–V07, независимый аудит, реконсиляция карты | 5 HTTPS-запросов этой lane + серверные проверки прежних лейнов | `w4-live-probes.md`, `verification-report-2026-10-16.md`, `map-reconciliation-2026-10-16.md`, `evidence/v63-frontend/*` (untracked) |
| W4 — агентское закрытие (эта lane) | — (без коммита) | три обязательных документа, реальные артефакты с привязкой к кандидату | pytest 152 + 616, js 11/11 (asap8) + 80/84, B11-инструмент exit 0, coverage gate | `evidence/v63-close/*`, `review-ledger.md`, этот файл, `v63-final-coverage-report-2026-10-16.md`, `v63-agent-close-2026-10-16.md` |

## 2. Швы (seams) и чем они закрыты

| Шов | Чем integrated | Проверка |
|---|---|---|
| B01 (backend) ↔ B01.4 UI | API-поля профиля «редко/нормально/активно» + `limits_intent` | `tests/js/asap8_v63_w3_modules_ui_test.js` (зелёный на `c2775a54`), REV-W3 §7, `test_b01_frequency_profiles_and_thin_limits` |
| B06 ↔ summary_scheduler ↔ UI | единый резолвер emergency→chat→global, применён в cron/generate/`/summary` | `TestSchedulerFollowsResolver` (17 passed), REV-W3 §7 |
| B04 ↔ B05/U06 | маршрут `edit_report` = production preview; join-фикс `web/api/cover_styles.py` | REV-W1 B04 + REV-W3 §2, EDITOR 40/40 |
| B07 ↔ seed/hot/registry | `SEED_CATEGORIES+temporal`, hot-чтение `tool_enabled`, скрыт из витрины | `TestSeedTemporal`, `TestGateLifecycle`, `TestNotAModuleCard` (12 passed) |
| B08 ↔ stories_feed ↔ UI | единые display-правила (`_stories_display`), заглушки не проходят | `TestFeedHonestDisplayRevW3preN1`, REV-W3 §8 |
| B02/B03 ↔ Status/Analytics | durable-счётчики и воронки из `task_jobs`/`mca_events`, а не заглушки | REV-W3 §4, `test_asap8_v63_w3_analytics_viz.py` |
| B11 ↔ прод | read-only отчёт по 10 механизмам, выполнения на сервере | `w4-live-probes.md §1` (8 ok / 2 never_run), `live-canary.md`, артефакт `evidence/v63-close/b11-mechanisms-report-history-db.json` |
| frontend ↔ прод | `/web/` и `fullscreen-policy.js` побайтово = кандидат | `evidence/v63-close/prod-probes-2026-10-16.md` |
| тесты ↔ изоляция | `conftest.py` — сброс persona/settings-identity, per-file singleton reset | REV-W1 «смежные 426 passed», вся серия `asap8_*` зелёная на кандидате |

## 3. Цепочка source→event→processing→decision→output→feedback (PRIN-PIPELINE-FIRST)

Для каждого B-требования — артефакт, который доводит evidence до изменения
телеметрии/статусов. «test» = наблюдаемо в тесте/рантайме кандидата;
«live» = требует прод-окна/владельца.

| Требование | source | event | processing | decision | output | feedback | Где |
|---|---|---|---|---|---|---|---|
| B01 | журнал/сообщения чата | `mca_events` (opportunity, reason codes) | observer tick, окно ≤14, бюджеты | SAY/REACT/SILENT из evaluated opportunity | решение наружу | воронка + диагностика «24ч ноль» | `test_b01_funnel_events_chain_with_reason_codes`, `test_b01_zero_opportunities_24h_is_diagnostic_event` (test) |
| B02 | диалог | `mca_experience_*` | семантический extract (батч ≤4×10) | candidate→validated | lesson | cursor двигается после durable-записи + outcome | `test_asap8_v6_d05_experience.py` (test); live-метрики — owner |
| B03 | GraphRAG/память | memory-события | staged overfetch, fresh-first + архивный top-up | expired ≠ delete | ответ с as-of | overview bounded counts | `test_asap8_v63_b03_memory.py` (test) |
| B04 | cover/style jobs | job-события | compact EDIT-промпт, dedupe, preflight | публикация/замена | `editMessageMedia` | `format_valid` ≠ `scene_preserved` | REV-W1 B04 (test); live-доставка — owner |
| B06 | настройки чата | resolver | emergency→chat→global | run/no-run | публикация Summary | `summary_runs.publication_status` | `TestMatrixRealGeneration` (test); прод-матрица — owner |
| B07 | настройки Фактчека | hot-чтение | temporal.tool_enabled, режимы/TTL | вердикт Фактчека | evidence-таймлайн | registry visibility | `TestGateLifecycle` (test); прод-сид — owner |
| B08 | сообщения эпизода | `mca_episodes`/stories | детерминантная сборка, backfill | ready / insufficient_sources | карточка + лента | `content_status`, три даты | `test_asap8_v63_b08_stories.py` (test) |
| B09 | перенос supergroup | backup | chunked backup, 0 DELETE | перенос/abort | verify | результат в `migrate_chat_memory` | `test_asap8_v63_b09_migration.py` (test); live-перенос — owner |
| B12 | карта/гейт | validator | сверка ID/артефактов/SHA | RED/GREEN | release-gate | exit code + errors | `requirements_gate.py` (прогоны этой lane: plan 0 / release 110) |

Недостающие «live»-плечи (B02, B04, B06, B09 + B01-воронка) относятся к
owner-гейтам (`REQ-B02-DOD`, `REQ-B04-DOD`, `REQ-B06-DOD`, `REQ-B09-BODY`,
`REQ-B01-DOD`) и в этом файле не перекрашиваются.
