# Release 2.58.240 — UR-C-CLOCK assembly (2026-11-24)

- Роль: **Builder** (release assembly; один writer в release-ветке).
- Локальное время: **2026-11-24 ~21:05 +12:00** (2026-11-24 09:05Z).
- Release branch: `release/unified-reply-ur-c-clock-2.58.240`
  (создана от approved tip `a200b8c9a`).
- Status: **REVIEW / READY_FOR_RELEASE_PREPARATION** — не выкачен.
- Deploy/SSH/LLM/prod не вызывались; DDL/миграций/флагов/UI нет.

## 1. Binding

| Роль | SHA / значение |
|---|---|
| Production base / rollback | `6123a1469bbfe1019d0a1ecdb65c383988444655` (APP_VERSION 2.58.239) |
| Slice commits | `3a1ec2192` (WIP) → `94466c16b` → `0eba142e2` → `05bd0d958` (R1 fix) |
| Product commit (R1 fix) | `05bd0d958f4c5781a72febc465eabcd198894bb8` |
| Approved candidate / content tip | `a200b8c9a361487a2601fc6f9e4c2b09cd6c901e` |
| Review r1 artifact commit | `46e059e6c7c0e5cecd163f21ebff35ef2ec4ff14` |
| Review r2 (binding verdict) | in `a200b8c9a` — APPROVED_FOR_RELEASE_PREPARATION |
| **Version bump / content RC** | **`f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9`** |
| Evidence/docs commit | этот коммит (после bump) |
| Proposed version | **2.58.240** |

## 2. Review / evidence references

| Артефакт | Путь | sha256 | git blob |
|---|---|---|---|
| Review r1+r2 | `plans/features/unified-reply/evidence/ur-c-clock/review-2026-11-25.md` | `b5f997a60ccd73c8f6f70f0230e4d01254deeb7e78694bc03996e6662834fa3f` | `17e00bb0ab8d536046142a58b08eeb4bc7b44997` |
| Implementation evidence | `plans/features/unified-reply/evidence/ur-c-clock/impl-2026-11-25.md` | `6354f1a0b3f2340ce85fcf65927554ecd661e7fb086e5663668f1ce08dfaf1a3` | `cc0960c87d4a87eea7f072d7fe9bb8d6223e2cba` |

Планировочные (не входят в code-RC, deliberate):

- Architecture (frozen contract D1–D9): `plans/features/unified-reply/evidence/ur-c-clock/arch-2026-11-25.md`,
  commit `8223e5a6e` (master; в ветке отсутствует намеренно — docs, не продукт).
- Scope amendment (R1 → `services/worker_budget.py`): `96da04ed3`
  (`plans/features/unified-reply/slice-graph.json`, master).
- Requirements map: `plans/features/unified-reply/requirements-map.json`
  (в ветке `candidate_commit` = `5d8c8598`, **stale**; rebind 10 строк на
  `f7e20e15d`/2.58.240 — шаг PM, не Builder).

Вердикт r2 (review §r2): `decision=APPROVED_FOR_RELEASE_PREPARATION`,
`URC-CLOCK-R1 = RESOLVED`, `UR-25 = UNBLOCKED`, 9 остальных строк — PASS из r1,
N1–N8 и R2-A/B/C — BACKLOG_ONLY/non-blocking; `p0_hc_blob`
`34d3d36fe71f3518b647274b1d85bc9b10ba905a`; `ddl_schema_ui_flags = 0`;
`visual_gate = N/A (UI 0, web/* diff empty)`.

## 3. Что входит в RC (продукт)

Один резолвер действующего пояса чата + пользовательские payload-маршруты +
наблюдаемость + окно сводки:

| Файл | Изменение |
|---|---|
| `services/chat_clock.py` | `LocalInstant`, `local_date`, `local_wall_to_utc` (gap/fold/полу-сдвиг), единый `resolve_chat_timezone_sync`, `window_utc`/`window_local` в блоке, `log_clock_call(skip_reason=)`, `refresh_time_context` сохраняет окно байт-в-байт |
| `services/tool_router.py` | `_local_epoch` → делегирование в ChatClock |
| `services/meme_initiative.py` | `resolve_timezone` → делегирование в ChatClock |
| `services/worker_budget.py` | **R1:** `_chat_tz_name` → делегирование в `resolve_chat_timezone_sync` (единственный hunk; `image_day`/пороги байт-идентичны) |
| `services/search_service.py` | D4: digest — блок `phase="answer"`; rerank — без блока + честный лог |
| `services/web_summarizer_service.py` | D4: пересказ страницы — блок `phase="answer"` |
| `services/youtube_summarizer_service.py` | D4: субтитры/локальный файл/мультимодалка; явный `snapshot=` из хендлера |
| `handlers/youtube.py` | снапшот на границе хендлера, 6 call-sites; contextvar-scope удалён (tool-путь без блока) |
| `services/summary_l1_clusterizer.py` | D6: `window_utc`/`window_local` в L1-блоке; D5 лог dedicated-ноги; `chat_id` |
| `services/summary_l2_writer.py` | D5 лог dedicated-ноги; `chat_id` |
| `services/summary_generator.py` | D5 `chat_id` в supervised/legacy ноги |
| `services/summary_llm_supervisor.py` | D5 `chat_id` в `make_wrapped`; лог dedicated/stream/fallback на фактическом payload |
| `tests/test_ur_c_clock.py` | + D2/D3/17.5/D6-пробы, UR-RES-08 матрица, `TestWorkerBudgetSingleResolver` (3 теста) |
| `tests/test_ur26_other_routes_payloads.py` | D4/D5 матрица (финальные payload'ы + транспортные логи) |
| `tests/test_p0im_s6_fresh.py` | oracle приведён к единому ChatClock-фоллбэку (тест-only, `0eba142e2`) |
| `impl-2026-11-25.md` | implementation evidence |
| `review-2026-11-25.md` | review r1+r2 |

Строки, которые после деплоя могут быть помечены VERIFIED по этому артефакту
(вердикты r1/r2, 10/10 satisfiable):

| Строка | Вердикт Reviewer |
|---|---|
| `UR-25` | UNBLOCKED (R1 RESOLVED, probe 6/6, mutation RED) |
| `UR-24` | PASS (агрегация) |
| `UR-25.4` | PASS |
| `UR-26` | PASS (агрегация) |
| `UR-26.6` | PASS |
| `UR-26.7` | PASS |
| `UR-27.2` | PASS |
| `UR-17.5` | PASS |
| `UR-RES-08` | PASS (агрегация) |
| `UR-SCOPE-TIME-MANDATORY` | PASS (docs) |

Остальные UR-C-CLOCK строки карты (`UR-24.2/24.3/24.4`, `UR-25.2/25.3/25.5/25.6`,
`UR-26.2–26.5`, `UR-27`, `UR-BAN-05`) уже VERIFIED и этим срезом не
переоткрывались. Rebind/статусы — PM.

## 4. Version wave 2.58.239 → 2.58.240

- `APP_VERSION = "2.58.240"` + `(24.11.2026)` — фактическая локальная дата
  сборки; прежняя сводка сохранена как `Prior 2.58.239 - …` (одна строка,
  формат 2.58.239).
- Ровно **32 files, 35 insertions / 35 deletions** — тот же набор, что в
  `6123a1469`: 1 `config/settings.py`, 1 generated
  `plans/docs/param-registry-round1025.meta.md`, 24 Python version-pin теста,
  4 JS hotfix-теста, 2 `tools/ui_mod_acl_m4b2|m4b3_status_e2e.py`.
- `git diff -U0 a200b8c9a..f7e20e15d`: 35/35 строк, **0** изменённых строк без
  version-токена (проверено скриптом: строки равны после обратной замены
  `2.58.240 → 2.58.239`; settings-line имеет сохранённый суффикс).
- `git grep 2.58.239` после bump: только `config/settings.py:1` (в
  `Prior 2.58.239 - …`) и `impl-2026-11-25.md:1` (историческая база). Текущих
  пинов нет.
- CRLF/BOM сохранены (byte-level замена, 3654 CRLF в settings.py до и после);
  `git diff --check` — exit 0.

## 5. Проверки на bumped tip `f7e20e15d`

Интерпретатор: `C:\Code\Python\adminbot\.venv\Scripts\python.exe`
(Python 3.12.0, pytest 9.1.1), cwd = release worktree.

### 5.1. Focused slice suites

```text
pytest tests/test_ur_c_clock.py tests/test_ur26_other_routes_payloads.py \
       tests/test_p0_hc_coverage.py -q -p no:randomly
  -> 135 passed in 13.32s            (40 + 18 + 77), EXIT=0

pytest tests/test_ur26_init_fc_payloads.py tests/test_ur26_summary_payloads.py \
       tests/test_payload_builder.py tests/test_unified_core_route_coverage.py \
       -q -p no:randomly
  -> 56 passed in 20.92s             EXIT=0

pytest tests/test_direct_chat.py tests/test_history_segments.py \
       tests/test_p0im_s6_fresh.py -q -p no:randomly
  -> 202 passed in 24.19s            EXIT=0
```

### 5.2. worker_budget / image_day набор

```text
pytest tests/test_image_daily_limit_round1026.py tests/test_cfg02a_image_quota_ui.py \
       tests/test_cfg02b_image_freq_limits.py tests/test_cfg02c_image_isolation.py \
       tests/test_mod_acl_ux_m2_runtime_edges.py tests/test_feature_gates.py \
       -q -p no:randomly
  -> 128 passed in 12.95s            EXIT=0
```

### 5.3. Version-pin wave (те же 24 Python-файла, что в bump)

```text
pytest <24 version-pin test files> -q -p no:randomly
  -> 856 passed, 4 failed in 76.62s  EXIT=1
FAILED test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff
FAILED test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools
FAILED test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged
FAILED test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline
```

Это ровно те же 4 node-id, что зафиксированы в release 2.58.239 как
base-pre-existing. Доказательство base-identical: detached worktree на
`6123a1469` (clean tree), те же 4 node-id:

```text
4 failed in 12.03s                   (6123a1469, без единого bump-байта)
```

Причина (статически, не догадка): тесты сравнивают `git diff --name-only
pre-round1026-a1` — от этого тега до `6123a1469` уже 9760 файлов, включая
`web/*`, `services/image_generation.py`, `summary_prompts.py`,
`prompt_migrations.py`, `execution_graph_source.py`. К 2.58.240/bump
отношения нет; acceptance не ослаблялась, тесты не правились.

### 5.4. JS version-pin тесты

```text
node tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js  -> HOTFIX7-SHELL-GLASS-HEARTBEAT-OK  exit 0
node tests/js/round1025_hotfix8_shell_aurora_test.js           -> HOTFIX8-SHELL-AURORA-OK           exit 0
node tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js-> HOTFIX9-SHELL-FLEX-GLASS-AURORA-OK exit 0
node tests/js/round1025_hotfix10_glass_geometry_bg_test.js     -> HOTFIX10-GLASS-GEOMETRY-BG-OK     exit 0
```

### 5.5. Static

```text
py -m py_compile <12 product modules + config/settings.py>   -> exit 0
git diff --check                                             -> exit 0
git diff --name-only 6123a1469 f7e20e15d -- migrations \
    services/database.py services/pg_db.py web/               -> пусто
test_p0_hc_coverage.py blob                                  -> 34d3d36fe71f3518b647274b1d85bc9b10ba905a (== base)
```

### 5.6. Manifest dry-run

Временный предыдущий manifest (2.58.239 / `6123a1469`) → `tools/release_manifest.py
--repo-root <worktree> --dry-run`; `.deploy/` после проверки удалён (в коммит
не попадает):

```json
{
  "schema": 1,
  "deployed_sha": "f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9",
  "version": "2.58.240",
  "deployed_at": "2026-11-24T09:02:54.780810Z",
  "deployer": "release-2.58.240-candidate",
  "effect": "deploy",
  "previous_sha": "6123a1469bbfe1019d0a1ecdb65c383988444655",
  "previous_version": "2.58.239",
  "release_branch": "release/unified-reply-ur-c-clock-2.58.240",
  "dirty_tracked": false
}
```

## 6. Diff composition (доказательство «только slice + bump»)

```text
git diff --name-only 6123a1469 f7e20e15d   -> 49 файлов
git diff --shortstat   6123a1469 a200b8c9a -> 17 files, +2400 / -216   (slice)
git diff --shortstat   a200b8c9a f7e20e15d -> 32 files, +35 / -35      (bump)
git diff --shortstat   6123a1469 f7e20e15d -> 49 files, +2435 / -251
```

49 = 17 (slice: 12 product + 3 test + 2 evidence) + 32 (bump). Пересечений нет.
Продуктовые файлы вне среза byte-identical: список изменённых файлов совпадает
с объединением двух наборов, третьих путей нет. Owner-файлы
(`plans/current_task.md`, `plans/owner_inputs/**`, `progress_scope.json`,
`workflow_state.md`) вне diff; `requirements-map.json`/`slice-graph.json` в
ветке не менялись.

## 7. Rollback

- Code-only: checkout `6123a1469` (2.58.239) + restart `admin_bot`.
- DDL/миграций нет (SQLite schema 48, PG DDL 0), данные не откатываются;
  новых флагов/настроек нет — конфигурацию накатывать/снимать не нужно.
- UI не менялся (`web/*` diff пуст) → TMA-кэш не требует действий.
- Изменение user-visible поведения, которое «откатится» вместе с кодом:
  блок `Chat_Time_Context` в поиске/вебе/YouTube, окно `window_utc/window_local`
  в сводке, и — для чатов с legacy/`GOODMORNING_TZ` поясом — совпадение
  суточного сброса image-лимита с локальной датой ChatClock.
- Manifest отката пишется штатно
  (`tools/release_manifest.py --effect rollback`).

## 8. Что намеренно НЕ входит / остаётся

1. Deploy, predeploy backup, health/identity/version/NRestarts, schema,
   disk audit/cleanup, журнал — **шаг DevOps**, см.
   `deploy-checklist-2.58.240.md`.
2. PM rebind 10 строк на `f7e20e15d` / 2.58.240 и plan/review/deploy gates —
   после этого evidence.
3. Backlog (не блокирует): `URC-CLOCK-N1` (`slot_claims.slot_instant_for` —
   второй wall→instant, consumer), `N2` (передача `chat_id` в `llm.generate`
   включает per-chat BYOK/budget-путь — наблюдение после деплоя), `N3`
   (`skip_reason` для технических ног), `N4` (env-хрупкость p0im oracle),
   `N5` (scope-таблица §4), `N6` (composed tool-turn), `N7` (fallback-лог
   module/payload), `N8` (inline re-render в `refresh_time_context`),
   `R2-A` (`_chat_tz_name(None)`), `R2-B` (static legacy copy в тесте),
   `R2-C` (переформатирование slice-graph amendment-коммитом).
4. 4 base-pre-existing падения version-pin wave (§5.3) — не относятся к RC.

## 9. Честные ограничения

- Живой production/effective config, SSH, реальный провайдер и реальные чаты
  не проверялись — это deploy-этап DevOps.
- Visual gate неприменим: UI 0, `web/*` diff пуст, меняется только текст
  payload'ов.
- `image_day()` напрямую не вызывается в тестах (зависит от «сейчас»);
  доказана зона-потребитель + байтовая неизменность функции.
- Ассемблирование выполнено в отдельном worktree; базовая рабочая копия
  (`C:\Code\Python\adminbot`, master) не изменялась.
