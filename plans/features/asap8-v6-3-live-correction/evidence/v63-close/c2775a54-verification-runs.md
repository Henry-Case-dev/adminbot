# c2775a54 — verification runs (lane V63-CLOSE, 2026-10-16)

Все прогоны выполнены на **точном дереве задеплоенного кандидата**
`c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79), а не на HEAD и не на
рабочем дереве репозитория (в рабочем дереве есть незакоммиченные правки
`services/disk_retention.py`, `services/param_catalog.py`, `web/app.js`,
`web/index.html` — они в деплое не участвовали, см. `live-canary.md`).

Способ привязки: дерево кандидата развёрнуто в managed scratch через

```
git worktree add --detach <scratch>/c2775a54 c2775a54258512a3e20c97341d3e8a6738b1a33b
```

и проверено: `git rev-parse HEAD` в этом дереве = `c2775a54…`, `web/index.html`
= blob кандидата (727257 байт, 14 вхождений `__APP_VERSION__`). Интерпретатор —
`.venv` основного репозитория (те же зависимости, что на прод-венве).

## 1. pytest — волна v6.3 (B01–B09/B11 + W3)

```
py -m pytest tests -q -p no:cacheprovider --tb=no -k "asap8_v63"
→ 152 passed, 13362 deselected   (exit 0, 52.05s / 17.93s)
```

Разбивка по файлам (collect-only на кандидате):

| файл | тестов |
|---|---|
| tests/test_asap8_v63_b01_initiative_observer.py | 13 |
| tests/test_asap8_v63_b02_semantic_experience.py | (в наборе) |
| tests/test_asap8_v63_b03_memory.py | 11 |
| tests/test_asap8_v63_b04_edit_contract.py / _scene_delivery.py | (в наборе) |
| tests/test_asap8_v63_b06_summary_scope.py | 17 |
| tests/test_asap8_v63_b07_temporal_factcheck.py | 12 |
| tests/test_asap8_v63_b08_stories.py | 24 |
| tests/test_asap8_v63_b09_migration.py | (в наборе) |
| tests/test_asap8_v63_b11_report.py | 17 |
| tests/test_asap8_v63_w3_analytics_viz.py | 5 |

Ключевые тесты под конкретные строки карты:

* `test_b01_frequency_profiles_and_thin_limits`, `test_b01_day_cap_and_min_gap_cuts_spam`,
  `test_b01_zero_opportunities_24h_is_diagnostic_event` — B01.4 (кроме live-клаузы).
* `TestSeedTemporal::test_seed_categories_include_temporal` — REQ-B07 (сид `CATEGORY_TEMPORAL`).
* `TestNotAModuleCard::test_factcheck_temporal_absent_from_cards_output` /
  `test_no_new_top_level_card_added` — REQ-B07 (Temporal не карточка модуля).
* `TestTenReadyStories::test_ten_episodes_deterministic_ready`,
  `TestIndependentTopics::*`, `TestArchiveDates::*`, `TestUnknownOutcome::*`,
  `TestRefsAndProvenance::test_provenance_not_lost` — REQ-B08 / B08.4.
* `TestExpiredRetrievalEligibility::test_expired_found_by_historical_query_only`,
  `TestInfiniteRetentionNoDelete::*`, `TestGraphKnnChatScope::*` — B03 / V03 (код-уровень).
* `TestTwoChatsAndRestart::*`, `TestMatrixRealGeneration::*` — B06 / V05.
* `TestTenMechanisms::test_ten_mechanisms_full_chain` — REQ-B11-SCOPE.

## 2. pytest — пере-приёмка legacy v6 (B10-R01…R19)

```
py -m pytest tests -q -p no:cacheprovider --tb=no \
  -k "asap8_f1 or asap8_f2 or asap8_f3 or asap8_f4 or asap8_f5 or asap8_f6
      or asap8_f7 or asap8_f8 or asap8_f9 or asap8_v6"
→ 616 passed, 12898 deselected   (exit 0, 46.92s)
```

Файлы, которыми закрываются строки legacy-таблицы:

| Строка карты | Файл(ы) | Тестов |
|---|---|---|
| B10-R01 (C01/C02) | tests/test_asap8_f1_summary_l2_repair.py, test_asap8_f2_summary_execution_input.py | 39 + 20 |
| B10-R02 (C03/C03A/C04) | test_asap8_f3_style_preservation.py, test_asap8_v6_c03a_style_recovery.py | (в наборе) |
| B10-R03 (C05) | test_asap8_v63_b06_summary_scope.py (`TestMatrixRealGeneration`, `TestSchedulerFollowsResolver`) | 17 |
| B10-R04 (C06/C06A) | test_asap8_f6_initiative.py, test_asap8_v6_c06a_heartbeat.py, test_asap8_v6_c06a_status_ui.py | (в наборе) |
| B10-R05 (C07) | test_asap8_f7_stories.py, test_asap8_v63_b08_stories.py | 9 + 24 |
| B10-R06 (C08) | test_asap8_f8_embeddings.py | (в наборе) |
| B10-R07 (C09) | test_asap8_f9_youtube_proxy.py (407-классификация, каскад, health, proxy-auth probe) | 41 |
| B10-R08 (C10/D14) | test_asap8_v6_d14_help_sync.py (канон help, версии/реестры, миграции, запрет jargon/false promises) | 24 |
| B10-R09 (D01) | — | не найдено |
| B10-R10 (D02) | test_asap8_v6_wa3_migration.py | (в наборе) |
| B10-R11 (D03/D04) | test_asap8_v6_wc_direct_d03.py, test_asap8_v6_wc_direct_d04.py | 9 + 34 |
| B10-R12 (D05) | test_asap8_v6_d05_experience.py (e2e коррекция→применённый урок, негативы) | 18 |
| B10-R13 (D06) | test_asap8_v6_d06_isolation.py | 9 |
| B10-R14 (D07/D08) | test_asap8_v6_d07_overrides.py | 11 |
| B10-R15 (D09) | test_asap8_v6_p1_d09_dream.py, _p1_d09_deep_stages.py, _p1_d09_memory.py | 5 + 5 + … |
| B10-R16 (D10/D11) | test_asap8_v6_p1_d10_temporal.py, test_asap8_v6_p1_d11_registry.py | 23 + 16 |
| B10-R17 (D12/D13) | test_asap8_v63_w3_analytics_viz.py | 5 |
| B10-R18 (U07) | w2-evidence-fullscreen/_results.json (mock-матрица) | — |
| B10-R19 (U08) | tests/js + w2-evidence-glass/*.json | — |

## 3. node tests/js (UI-контракты)

```
cd tests/js && node <file>.js     (по одному файлу, как-run)
→ asap8*: 11 файлов, 11 pass / 0 fail
→ все *.js: 80 pass / 4 fail
```

**RED (обнаружен этой lane, воспроизводимо на кандидате):**

| файл | причина |
|---|---|
| tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js | `assert.ok(/APP_VERSION = "2.58.78"/)` — релизный bump c2775a54 → 2.58.79 |
| tests/js/round1025_hotfix8_shell_aurora_test.js | то же |
| tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js | то же |
| tests/js/round1025_hotfix10_glass_geometry_bg_test.js | то же |

Текст ассерта внутри файлов (`'D: APP_VERSION 2.58.34'`) устарел сильнее самого
пина — тесты проверяли bump 2.58.78 и сломались о bump 2.58.79. Это механический
версионный пин, не функциональная регрессия, но это **незакрытый RED на
задеплоенном кандидате** (REV-W2/REV-W3 фиксировали 0 failed до bump).
Правка кода/тестов — вне WRITE_SCOPE этой lane; вынесено в отчёт lane.

Зелёные на кандидате (релевантно строкам карты):
`asap8_v63_w3_modules_ui_test.js` (B01.4 UI: select «редко/нормально/активно» +
группы limits_intent), `asap8_v63_w3_status_logs_test.js` (U03/U04),
`asap8_v63_w3_analytics_test.js` (U05), `asap8_f7_stories`, `asap8_f9_youtube_proxy_health_test.js`,
`asap8_v6_d05_experience_ui_test.js`, `asap8_v6_d07_override_stack_test.js`,
`asap8_v6_wa2_dossier_guard_test.js`, `asap8_w2_shell_mobile_nav_test.js`,
`asap8_d1213_save_contract_test.js`, `asap6_wave2_ux_tabs_test.js`.

## 4. B11-инструмент на кандидате (read-only)

```
py -3 tools/v63_b11_mechanisms_report.py --db <db> --json out.json     → exit 0
```

* На выгруженном локальном `local_database.db` (12 КБ, без таблиц): все 10 секций
  честно `unavailable` (fail-soft), отчёт собран, RC=0 — речек фикса REV-W3PRE-N2
  (запуск из корня без PYTHONPATH).
* На `local_database_2026-09-04_history.db` (755 МБ, реальные таблицы):
  summary `{"producer_off": 3, "no_input": 3, "unavailable": 2, "never_run": 2}`;
  артефакт — `evidence/v63-close/b11-mechanisms-report-history-db.json`
  (10 секций, полная цепочка REQ-B11-CHAIN, `not_green_rule` соблюдён:
  never_run/producer_off/no_input не зелёные). PG-слой не покрыт
  (`pg_available=false`, `pg_dsn_not_provided`).

Прод-прогон инструмента задокументирован в `w4-live-probes.md §1`
(8 ok / 2 never_run) и `live-canary.md` (команда без `--pg-dsn`). **Расхождение
двух артефактов о покрытии PG зафиксировано в отчёте lane.**

## 5. Coverage gate

```
requirements_gate.py check --map plans/features/asap8-v6-3-live-correction/requirements-map.json \
  --stage release --candidate c2775a54… --deployed-commit c2775a54…
→ FAIL, exit 1, inventory=148 manual=74 scoped=200 errors=110

requirements_gate.py check --map … --stage plan
→ exit 0, errors=0
```

Карта на момент прогона — рабочее дерево (post-reconciliation: 129/44/31/18);
HEAD-версия карты — предреконсиляционная (138/48/22/14). Правки карты этой lane
не вносились (`requirements-map.json` READ-ONLY).
