# SELF-DIAG-01 — финальная интеграция: один релизный кандидат (D6-трейн + D2 + D4 + D5-final)

- **Срез:** финальная интеграция `self-diag-01` — один кандидат из уже одобренных веток.
- **Код/тесты (кандидат):** `454727ede7a2577b80dbef1b5d9c1ce3c4a3342d` (ветка `self-diag/final`).
- **Обновление (final-fixes, 13.11.2026):** F1–F3 DevOps закрыты отдельным
  кандидатом `34754c9c4749cdd79da33da20368db9c0dfd028a` (ветка
  `self-diag/final-fixes`) — см.
  `evidence/final/binding-final-fixes-34754c9c4749cdd79da33da20368db9c0dfd028a.md`.
  Этот кандидат сохранён без изменений для воспроизводимости.
- **Docs-коммит:** этот файл (SHA фиксируется в handoff; код-кандидат выше не меняется).
- **База диффа:** `25876167` (release 2.58.197, пин-релиз).
- **Ветка/worktree:** `self-diag/final`,
  `WorkspaceData/worktrees/c742e4de9e92c489/SELF-DIAG-01-25283fad06db-057b5a4c`.
- **Статус:** **REVIEW** — кандидат для независимого Reviewer; PM/DevOps решают
  приёмку/выкат. `self-diag` DONE **не** объявляется.
- **Не делалось:** деплой, `master`, `settings`, `prompts`, `models`, DDL/миграции,
  новые LLM/агенты/хранилища, новые требования. Никаких правок промптов.

## 1. Собранные SHA (что именно влито)

| Срез | Ветка | Влитый код | Docs |
|---|---|---|---|
| D6-трейн (D4-A/B + D3 + D5 + D6) | `self-diag/d6` | `16fa04e7` (**база worktree**) | `9334c0c2` — **не влит** (см. §6, п.1) |
| D2 closure | `self-diag/d2-closure` | `aa1d4127` | `d79648c4` |
| D4 trace | `self-diag/d4-trace` | `018e8d77` | `6474c570` (+`d5d8a31a`) |
| D5-final | `self-diag/d5-final` | `b3e9fe6e` | `e617bc8e` |

Merge-коммиты: `c71b0778` (D2), `fe50a565` (D4), `0a818426` (D5-final);
сверху один интеграционный test-коммит `454727ed`.

## 2. Дифф `25876167..HEAD`

```
130 files changed, 21235 insertions(+), 256 deletions(-)
added=35  modified=95  deleted=0
services: 16  handlers: 2  web: 3  config: 1  tools: 1  tests: 87  docs/evidence: 20
```

- **Файлов вне одобренного объединения: 0** (`16fa04e7` ∪ D2 ∪ D4 ∪ D5-final).
- **DDL/миграций: 0** (`services/pg_db.py`, `*.sql`, `alembic/`, `migrations/` — не тронуты).
- **Новых LLM-клиентов/БД-клиентов/`eval`/`exec`/`shell=True`: 0.** Единственный
  новый `subprocess` — одобренный D4 read-only git-коллектор (закрытые наборы,
  `shell=False`, path-safety тесты).
- Новые файлы продукта: `services/deploy_identity.py`, `services/diagnostic_collector.py`,
  `services/evidence_bundle.py`, `services/runtime_probes.py`, `services/settings_view.py`,
  `services/prompt_readback.py`, `handlers/prompt_readback.py`
  (+ `tools/_selfdiag01_d4b_reissue_f8.py` — переиздание F8 из D4-B).
- Изменённые продуктовые файлы: `config/settings.py`, `handlers/checkup.py`,
  `services/checkup_service.py`, `services/debug_config.py`, `services/diagnostic_policy.py`,
  `services/log_ring.py`, `services/memory_health.py`, `services/output_projection.py`,
  `services/param_catalog.py`, `services/source_reader.py`, `services/tool_router.py`,
  `services/tool_schemas.py`, `web/api/routes.py`, `web/app.js`, `web/index.html`.

Ключевые файлы задания на месте и соответствуют одобренным веткам:
`services/deploy_identity.py` (D4), `services/param_catalog.py`/`output_projection`/`log_ring`/
`debug_config` (D2), `services/runtime_probes.py` (D3+D2+D4),
`tests/test_self_diag_golden.py` (38) и `tests/test_prompt_readback.py` (62) (D5-final).

## 3. Конфликты слияния

| Файл | Причина | Решение |
|---|---|---|
| `services/runtime_probes.py` | D2 и D4 вставляли новый `ProbeSpec` в одну точку (после `config.effective`) | Оставлены **оба** блока (аддитивно): `config.secret_status` (D2), затем `deploy.traceback` (D4). Семантика не менялась |

Доказательство аддитивности (байтовые диффы после слияния):

```
HEAD vs self-diag/d2-closure -- services/runtime_probes.py  → 166/4  (это ровно Δ D4)
HEAD vs self-diag/d4-trace    -- services/runtime_probes.py  →  46/0  (это ровно Δ D2)
16fa04e7 vs self-diag/d4-trace                                 → 166/4  (Δ D4 эталон)
```

Других конфликтов нет (только это пересечение файлов между ветками).

## 4. Сохранность одобренного кода (byte-for-byte)

| Сравнение | Идентично | Расхождения |
|---|---|---|
| D2 `self-diag/d2-closure` (12 файлов) | 11/12 | только `services/runtime_probes.py` (аддитивный union, §3) |
| D4 `self-diag/d4-trace` (7 файлов) | 6/7 | только `services/runtime_probes.py` (там же) |
| D5-final `self-diag/d5-final` (4 файла) | **4/4** | — |
| D6-трейн `16fa04e7` (114 файлов) | 91/114 | 4 файла из D2/D4 + `runtime_probes` + 18 тестов (17 интеграционных re-pin + `test_prompt_readback` из D5-final) |

Ни один файл, не затронутый D2/D4/D5-final, не изменён относительно `16fa04e7`,
кроме перечисленных тестовых re-pin (§5).

## 5. Что пришлось починить в интеграции (только тесты, 2 корня)

Обе находки **воспроизводятся на одобренной базе `16fa04e7` до слияния** —
это не регресс merge, а незакрытые хвосты одобренных срезов.

### 5.1 `SD1-D2-23` × F8 (`L-F11S-1`): пин `param_catalog.py` не переутверждён

`tests/test_round1025_f8_registry.py::TestFrozenInvariants::test_param_catalog_unchanged`
падал на базе: D2 добавил в каталог обязательный `sensitivity`/типизированный
`register_param`, но байтовый пин `PARAM_CATALOG_SHA256_FOLLOWUP` никто не переутвердил
(в binding D2 F8 не упоминался).

Минимальный фикс: переутверждён только SHA256 + комментарий-санкция
(`f5bb7ae8…` → `bcdf8f02…`). Состав каталога не изменился:
`REGISTRY 644 / GROUPS 121 / _TAB_BY_GROUP 119 / TAB_RULES 22`;
`fixtures/round1025/*` не переиздавались; `tools/gen_param_registry_round1025.py --check`
→ `CHECK OK` (TSV/screen-map идемпотентны).

### 5.2 Канон инструментов 17→18: частичный re-pin между D3 и D6

D3 (`fd756738`) поднял канон до 17 (`inspect_runtime`) и перепинил свой набор тестов.
D6 (`61e50806`) зарегистрировал 18-й инструмент (`prompt_readback`) и перепинил
**только свои** файлы. В результате 22 гарда в 14 файлах остались на 17 и были RED
на одобренной базе (`22 failed, 1303 passed` из 1325).

Минимальный фикс: те же механические re-pin, что сделал D6 в своих файлах
(счётчики `17→18`, `16→17`, `15→16`, хвостовые списки `+ "prompt_readback"`,
сдвиг индексов), плюс `external_read: 10→11` в `test_mca11` (новый инструмент
консервативно классифицируется как `external_read`, как и `read_source_code`/
`inspect_runtime`; в `admin`-категорию он не попадает). Продуктовый код не менялся.

Файлы (17): `test_agentic_ai_round1020`, `test_asap5_image_admin`,
`test_asap5_integration_w3`, `test_decision_making_round1026`,
`test_image_context_memory_round1026`, `test_mca11_tool_result_round1028`,
`test_mca15_chat_statistics_round1028`, `test_mca17c_invariants_round1047`,
`test_mca19_block_g_round1043`, `test_mca20_integration_round1045`,
`test_media_transcribe_tool_round1024`, `test_memory_lookup_round1026`,
`test_native_media_tools_round1024`, `test_recent_history_tool_round1015`,
`test_round1025_f8_registry`, `test_telegram_reactions_round1026`,
`test_tool_download_quality_round1017`.

## 6. Прогоны на кандидате `454727ed` (Windows, Python 3.12, без PG/сети)

| Набор | Кандидат | Одобренная база | Комментарий |
|---|---|---|---|
| D6 `test_checkup_contract.py` | **41 passed** | 41 | совпадает |
| D6 broad 22 файла | **946 passed** | 934 | `+12` = новые security-тесты D5-final в `test_prompt_readback` (50→62); арифметика точная |
| D6 16 файлов (D4-B + prompt) | **661 passed, 1 failed** | 661 + 1 failed | тот же единственный pre-existing `mca10b` пин 643/644 |
| D2 5 файлов | **145 passed** | 145 | совпадает |
| D2 6 файлов | **216 passed** | 216 | совпадает |
| D2 `debug_config+log_ring` | **42 passed** | 42 | совпадает |
| D2 9 файлов (param/settings) | **244 passed, 1 failed** | 232 + 1 failed | `+12` из D5-final; тот же pre-existing `cfg03` dead knob |
| D4 `test_deploy_identity_d4c.py` | **22 passed** | 22 | совпадает |
| D4 9 файлов | **366 passed** | 366 | итого D4 = 388 |
| D5 `test_prompt_readback.py` | **62 passed** | 62 | совпадает |
| D5 `test_self_diag_golden.py` | **38 passed** | 38 | AC-23 (36 кейсов + 2 shape/anonymized) |
| D5 8 файлов | **355 passed** | 355 | совпадает |
| D5 prompt-контракты (3 файла) | **56 passed, 1 skipped** | 56+1s | совпадает |
| D3 `bundle+probes` | **80 passed** | 80 | совпадает |
| D3 focused 35 файлов | **1325 passed** | 1325 | после §5.2 — впервые зелёный на этом трейне |
| web/api контракты (2 файла) | **190 passed** | — | аддитивная проверка |

Повторные прогоны стабильны; единственный нестабильный эпизод —
`test_asap5_integration_w3.py::TestNostalgiaProvenance::test_d14_active_conversation_scenario_a`
(`database: connection unrecoverable`) один раз в середине работы, зелёный изолированно
(16 passed) и во всех остальных прогонах набора; к правкам §5 отношения не имеет
(файл-владелец — чужой срез, тест не менялся). Классификация: `BACKLOG_ONLY`
(флак порядка тестов/пула соединений, не блокирует).

### Разрешённые pre-existing сбои (совпадают с базой)

1. `tests/test_mca10b_random_applications_block_d_round1041.py::test_blockE_f8_check_green_and_baselines`
   — пин `643` vs `644` (наследие D4-B, зафиксировано в D6 binding).
2. `tests/test_cfg03_param_audit.py::TestConsumerCoverage::test_visible_dead_knobs_are_exactly_documented`
   — «мёртвый» knob (зафиксировано в D2 binding §7).
3. Два RED, не входящих в focused-наборы и воспроизведённых на кандидате:
   `test_addtr_tools_minifix.py::test_l1_seam_announce_then_execute_once`,
   `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`.

**Новых падений относительно одобренной базы нет.**

## 7. Effective configuration (что реально влияет на поведение)

Новых флагов самим интеграционным коммитом не вводилось (только `tests/`).
Одобренный трейн приносит env-only оси (все — `ClassVar`/getenv, без DDL и без
persisted-настроек), заводские значения на этом стенде:

| Ключ | Заводское | Наблюдаемое в тестах | Смысл |
|---|---|---|---|
| `SELF_DIAG_PROBE_TIMEOUT_SECONDS` | `5.0` (мин 0.2) | не задавался (default) | таймаут одного probe |
| `SELF_DIAG_PROBE_MAX_OUTPUT_CHARS` | `9000` | default | кап facts на страницу |
| `SELF_DIAG_PROBE_MAX_ROWS` | `200` | default | строки выборок |
| `SELF_DIAG_PROBE_EXPENSIVE_ENABLED` | `"1"` | default | дорогие probe разрешены (db.integrity) |
| `SELF_DIAG_LOCAL_REPO_ROOT` | `""` (пусто) | пусто | локальный snapshot **выключен**, поведение = GitHub-провайдер |
| `ADMINBOT_DEPLOYED_SHA` | не задан | не задан | identity падает на локальные git-доказательства, `verified` не выдумывается |
| `flags.self_diag_repo_origin` (D4-B, PG-only owner-настройка) | заводское значение каталога | 644-я запись каталога | канонический repo identity; пользовательские значения не сбрасывались |

Тестовые прогоны шли с `ADMINBOT_SKIP_DOTENV=1` (корневой `conftest.py`), т.е. без
боевого `.env`; PG-ветка не исполнялась.

## 8. Честные границы (не проверено здесь)

1. **Деплоя нет**; прод/SHA-паритет/`/healthz` — зона DevOps, не этого среза.
2. **Live Telegram**: реальные `getChatMember`, фактические лимиты Bot API и реальная
   отправка не выполнялись (транспорт — существующие FakeBot/FakeCache; это же
   ограничение зафиксировано в D5/D6 bindings). Остаётся postdeploy-проверкой.
3. **PG-путь** chat-слоя не исполнялся (Windows-хост, SQLite/`юнит`-двойники).
4. **UI** (`web/app.js`, `web/index.html`) в интеграции не менялся и браузером
   повторно не проверялся — визуальная часть остаётся за одобрением D6/D7.
5. Симуляция не выдаётся за production-событие: окно реальных наблюдений не эмулировалось.

## 9. Классификация находок

- `IN_SCOPE` (исправлено здесь): §5.1 F8-пин `param_catalog.py`; §5.2 канон 17→18
  в 17 гардах. Оба — тестовые, доказаны как pre-existing на `16fa04e7`.
- `IN_SCOPE` (для Reviewer, без правки): расхождение счётчиков с одобренными
  bindings объяснено арифметикой D5-final (`934→946`, `232→244`), не регресс.
- `BACKLOG_ONLY`: флак `TestNostalgiaProvenance::test_d14_active_conversation_scenario_a`
  (порядок тестов/пул соединений); флак порядка в 35-файловом наборе не влияет на
  итоговый зелёный прогон.
- `CRITICAL_OUT_OF_SCOPE`: не обнаружено.

## 10. Кандидат для PM/DevOps

```
Код/тесты:  454727ede7a2577b80dbef1b5d9c1ce3c4a3342d   (ветка self-diag/final)
docs:       коммит с этим файлом (поверх кода, продуктовых изменений нет)
дифф-база:  25876167
```

Финальный `DONE`/приёмка — за Reviewer/PM/DevOps. Срез сознательно оставлен в `REVIEW`.

## 11. Housekeeping

- Baseline-прогоны выполнялись в одноразовом detached-worktree
  `runs/…/probe-2132f1eed5/base-16fa04e7` (после сбора доказательств снят).
- Логи прогонов (`run-*.log`), диффы re-pin и скрипты аудита — в
  `WorkspaceData/runs/…/SELF-DIAG-01-25283fad06db/probe-2132f1eed5/`;
  путь **сохранён на время ревью** (сырые логи для Reviewer), закрывается
  после приёмки среза.
- Worktree `self-diag/final` сохранён для Reviewer.
