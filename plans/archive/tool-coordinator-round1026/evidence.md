# A1 `tool-coordinator-round1026` — evidence (Step 3 @Builder, T-3503…T-3517)

- **Фича:** A1 `tool-coordinator-round1026` (Эпик 3 «Agentic Intelligence», Wave 1, Раунд 10.26). **P0. Risk R2.**
- **Спека/ADR:** `spec.md` (REQ-A1-01…-12 / SC-A1-01…-12); `adr-1026-14-coordinator-scope-in-synthesizer.md` (**D1–D10**).
- **Дата:** 24.09.2026. **Автор:** @Builder.
- **Baseline:** HEAD **`e3ea367`** == annotated-тег **`pre-round1026-a1`**; `APP_VERSION` был **2.58.29**; pytest `.venv` **9026/0**; JS **47/47**; каталог **REGISTRY 469 / Settings 426 / categorized 444 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21**; **Δ DDL=0** (SQLite v12).
- **Итог Step 3:** реализован программный слой Координатора **внутри** существующего Синтезатора (`services/direct_chat_service.py`); `APP_VERSION` → **2.58.30**; pytest **9082/0** (+56); JS **47/47**; `git diff --check`=0; Δ DDL=0 / Δ каталога=0. **Коммит не делался.**
- **Ограничения процесса:** `plans/current_task.md`, машинный блок `OPENCODE_WORKFLOW_STATE_V1`, `tasks.md`, `spec.md`/ADR (заморожены Step 2), `backlog.md`, `metrics.md`, `ARCHITECTURE.md`, durable-аудит A0 — **не изменялись**; `@Scanner` не создавался. Чекбоксы `tasks.md` не проставлялись (правки `tasks.md` — только @PM).

## 1. Что реализовано (по блокам tasks.md)

### Блок B — контракт Координатора в Синтезаторе (T-3503…T-3505) — @Builder
- **`services/direct_chat_service.py:467–643`** — новый программный слой (0 LLM):
  - внутренний enum `ACTION_REPLY/REACT/SILENT/TOOL` (`:467–472`) — **не** wire-контракт (граница A7);
  - R17-safe коды намерения/адресата/оценки (`INTENT_*`, `ADDRESSEE_*`, `EVAL_*`) (`:474–496`);
  - `@dataclass CoordinatorDecision` (`:499–515`) — внутренний объект решения (intent/addressee/memory_need/tool_calls/evaluation/action/style);
  - `coordinator_enabled()` (`:517`) — kill-switch per-call;
  - `_coordinator_intent` (`:525`), `_coordinator_addressee` (`:540`), `_coordinator_tool_names` (`:552`), `_coordinator_evaluate` (`:563`), `_coordinator_choose_action` (`:578`), `_coordinator_memory_need` (`:593`), `build_coordinator_decision` (`:602`), `_log_coordinator_decision` (`:625`), `_log_coordinator_outcome` (`:637`).
- **T-3503 (намерение/адресат/память):** программно из существующих маркеров пре-гейтов (image/nostalgia), forward/reply-резолва, `tool_trace`/`dig_fired`/`lore_compiled`. **0 LLM-вызовов.**
- **T-3504 (выбор инструментов + оценка):** `tool_calls` = имена фактически вызванных моделью инструментов из `ToolLoopResult.tool_trace` (модельный выбор сохранён, `tool_choice='auto'` не форсируется/не дублируется); `evaluation ∈ {none,ok,partial,failed,degraded}`. Reuse `tool_loop`/`ToolRouter`; **freeze 10** не нарушен.
- **T-3505 (решение о действии ≠ текст):** решение строится **до** Stage-2 (`direct_chat_service.py:1004–1011`); точка интеграции — существующий гейт Stage-2 (`:1019–1026`); **wire-`action` не введён**.

### Блок C — общий механизм цепочек на `tool_loop` (T-3506…T-3508) — @Builder
- **Код `services/tool_loop.py` НЕ менялся** (структурное изменение подняло бы риск до R3 — ADR D10). Механизм цепочек **reuse** существующего многораундового цикла (`TOOL_MAX_ROUNDS=4`, `_TOOL_CALLS_PER_ROUND_MAX=2`, role `tool`, повтор LLM-вызова, fail-open `degraded`).
- **T-3506/SC-A1-02:** зависимые A→B последовательны (тесты `TestChainMechanism::test_dependent_calls_are_sequential`).
- **T-3507/SC-A1-02:** лимиты/деградация — `test_calls_per_round_truncated`, `test_round_limit_degraded`, `test_late_llm_error_fail_open`, `test_provider_reject_plain_fallback`.
- **T-3508/SC-A1-10:** граница A2 задокументирована; per-combination обработчиков нет (`test_tool_loop_is_tool_agnostic`, `test_no_second_router_in_direct_service`).

### Блок D — изоляция Вербализатора (T-3509…T-3510) — @Builder
- `_synthesize_direct_answer` **не менялся**: Stage-2 получает только `stage2_payload(data)` + стиль (`compose_verbalizer_system`), без сырья (`:956–975` существующий контур). Серверных операций Вербализатор не выполняет.
- **T-3510:** гейт Вербализатора теперь выражен через решение координатора (`action == tool` ⇔ существующие условия) — при не-текстовом решении (молчание/реакция) Вербализатор не запускается. Тесты `TestHandleGate::test_plain_turn_skips_verbalizer / test_degraded_skips_verbalizer / test_lore_compiled_skips_verbalizer`, `TestVerbalizerIsolation`.

### Блок E — промпты/наблюдаемость (T-3511…T-3512) — @Builder
- **T-3511 — NOT_APPLICABLE:** промпты **не менялись** (`services/chat_prompts.py`, `services/prompt_migrations.py`, `summary_prompts.py` — вне diff); `PREV_*`/`PROMPT_MIGRATIONS`/эталонные байт-тесты **не добавлялись** (ADR-1013-3, ADR-1026-14 D5).
- **T-3512:** R17-safe события `[coordinator] decision` / `[coordinator] outcome` через существующий `logging` (`:625–645`); числа/коды/имена инструментов/длины — без сырья/промптов/секретов. Вторая аналитика не создаётся; ExecutionGraph — **REUSE** (`execution_graph_source.py` вне diff).

### Блок F — тесты/R17/регресс (T-3513…T-3515) — @Builder
- **NEW `tests/test_tool_coordinator_round1026.py`** (56 тестов, `pytestmark = pytest.mark.system2`): чистые функции координатора; сборка решения; механизм цепочек; изоляция Вербализатора; отсутствие wire-`action`; гейт Stage-2 и OFF/legacy; 2-вызовность (`await_count==2`); R17; границы diff/версия/канон.

### Блок G — интеграция/границы (T-3516…T-3517) — @Builder
- **T-3516:** §104 `generate_image` — вне diff; §85-UI/каталог — вне diff (Δ каталога=0); REUSE ExecutionGraph (вторая аналитика не создана); Δ DDL=0; freeze 10; `param_catalog.py` вне diff.
- **T-3517:** границы волн A2/A7/A3/A4/A6/A8/A9 **не реализованы** (вход зафиксирован; §15–§17 — A2, `action`/`style` — A7).

### Kill-switch / версия (D6/D7)
- **`config/settings.py:552–553`** — `DIRECT_COORDINATOR_ENABLED: ClassVar[bool] = _env_bool("DIRECT_COORDINATOR_ENABLED", True)` (env-only, default ON, Δ каталога=0, резолв per-call; OFF → точный legacy-путь).
- **`config/settings.py:1835`** — bump `APP_VERSION` **2.58.29 → 2.58.30** (+ A1-описание); **`README.md:5`** — `v2.58.30` + A1-раздел.

## 2. Команды и фактические результаты

| Проверка | Команда | Результат |
|---|---|---|
| Полный регресс | `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=120` | **9082 passed, 0 failed** (153.4 с); baseline 9026 → **+56** |
| Новый файл координатора | `pytest tests/test_tool_coordinator_round1026.py -q` | **56 passed** |
| System-2/direct-группа | `pytest tests/test_direct_two_call_round1022.py tests/test_direct_chat*.py tests/test_negative_constraints_round1022.py -q` | **345 passed** |
| Версии/каталог/UI | `pytest tests/test_round1025_f8_registry.py tests/test_webapp_round1026_polygon.py tests/test_scope_selector_round1025.py tests/test_summary_*round1026*.py tests/test_webapp_*round1025.py -q` | **405 passed** |
| JS-unit (pytest) | `pytest tests/test_webapp_js_unit.py -q` | **34 passed** |
| JS (все 47 файлов) | цикл `node tests/js/*.js` | **OK=47 FAIL=0** |
| `git diff --check` | — | exit **0** |
| Каталог/версия | импорт `param_catalog`/`settings` | `APP_VERSION` **2.58.30**; **469/426/444/100/98/21** |
| Каталог `--check` | `python tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 469 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны` |
| Δ DDL=0 | `git diff --name-only pre-round1026-a1 -- db/` | **пусто** (0) |
| Границы diff | `git diff --name-only pre-round1026-a1` | запрещённые пути **вне diff** (см. §5) |

## 3. Покрытие SC (сжато)

- **SC-A1-01/-04** — `TestCoordinatorIntent/Addressee/MemoryAndTools`, `TestBuildCoordinatorDecision`; §13-поток программно, без LLM.
- **SC-A1-02/-07/-08** — `TestChainMechanism` (зависимые A→B последовательны; лимиты 4/2; fail-open; tool-loop tool-agnostic).
- **SC-A1-03** — `TestHandleTwoCallPreserved::test_await_count_is_two` (`await_count==2`); 0 новых LLM-вызовов (координатор — чистые функции).
- **SC-A1-05** — решение строится до Stage-2 (`:1004–1011`); `TestBuildCoordinatorDecision` (action ≠ текст).
- **SC-A1-06** — `TestVerbalizerIsolation`, `TestHandleGate` (не запускается при молчании/реакции/деградации/lore).
- **SC-A1-09/-12** — R17-тест `TestCoordinatorObservability`; REUSE ExecutionGraph (вне diff); вторая аналитика не создана.
- **SC-A1-10/-11** — границы A2/A7/смежных волн: код не реализует §15–§17/§38–§48/§18–§25/§32–§35/§41/§44/§49/§51; `TestBounds`.
- **SC-A1-12** — freeze 10; Δ DDL=0; Δ каталога=0; OFF/legacy; версия/канон (`TestBounds`).

## 4. R17 / R18 / инварианты

- **R17:** `TestCoordinatorObservability::test_r17_no_raw_text_in_logs` — сырой запрос и сырой `tool_context` отсутствуют в `[coordinator]`-логах; логируются только коды/числа/имена инструментов/длины. R17-контракты существующих логов не менялись.
- **R18:** тег `pre-round1026-a1` → `e3ea367` и бэкапы не удалялись.
- **Δ DDL=0** (SQLite v12); **Δ каталога=0** (469/426/444/100/98/21; `--check` OK); **0 новых зависимостей** (манифесты/локи вне diff); **2-вызовность** (`await_count==2`); **OFF/legacy** — координатор не строится (`coordinator is None` ⇒ гейт байт-в-байт прежний).
- **freeze канона 10** инструментов; wire-`action` не введён; per-combination обработчиков нет.

## 5. Границы diff (факт)

- **Изменено @Builder (tracked) — 25 файлов:** `services/direct_chat_service.py` (Координатор + интеграция), `config/settings.py` (kill-switch + `APP_VERSION`), `README.md` (версия + A1-раздел), `plans/docs/param-registry-round1025.meta.md` (провенанс-штамп `APP_VERSION`, прецедент S10) + **21 файл в `tests/`/`tests/js/`** (re-pin версии `2.58.29 → 2.58.30`).
- **Untracked:** `plans/features/tool-coordinator-round1026/` (spec/ADR/tasks + `evidence.md`), `tests/test_tool_coordinator_round1026.py`.
- **Вне diff (подтверждено пустым diff и тестом `TestBounds::test_forbidden_paths_out_of_diff`):** §104-контур `services/image_generation.py`, `services/summary_prompts.py`, `services/prompt_migrations.py`, `services/param_catalog.py`, `services/telegram_send.py`, `services/chat_prompts.py`, `services/execution_graph_source.py`, `web/api/routes.py`, `web/**`, `db/**`, `plans/current_task.md`; `services/tool_loop.py` не менялся (reuse).
- **Pre-existing (не @Builder, изменены до старта Step 3):** `plans/MEMORY.md`, `plans/workflow_state.md` (роли @Memory/@Orchestrator).

## 6. Хэши (SHA-256, на момент финальных прогонов)

| Файл | SHA-256 |
|---|---|
| `services/direct_chat_service.py` | `B0F8BB071D5603924A2EDB5437CB14270CE0185B7CDD87609AE58A940FC7CB79` |
| `config/settings.py` | `28C554BBFE3349D935C724EFD0E71D86B5BF71ED74A9C9FF4BBDB7CCF8C61AD2` |
| `README.md` | `01B8621E456C666888DA9671A65FF9F7067AC29624BBE14CB328B7BE3EB3A064` |
| `plans/docs/param-registry-round1025.meta.md` | `B0BCDB723FEB0CB54BB6EB7163B5DEF9DC47994CF653C0F81B91E3C3ACF7BE19` |
| `tests/test_tool_coordinator_round1026.py` | `44738081B246E651ED21177FDD5287EE34F57BDF0C679E1C5E06C16E8F9AFBCE` |

## 7. Решения/отклонения (для Reviewer)

1. **Список разрешённых файлов diff в ADR-1026-14 отсутствует** (в задании Step 3 он заявлен, но в тексте ADR/spec его нет — только REUSE-ориентиры §9). Принят наиболее консервативный набор: **координатор реализован внутри существующего `services/direct_chat_service.py`** (новый product-модуль не создавался), плюс `config/settings.py` (kill-switch/версия), `README.md`, `tests/**`. Если @Architect ожидает иной allowlist — вернуть уточнение.
2. **`plans/docs/param-registry-round1025.meta.md`** — обновлён только провенанс-штамп `APP_VERSION` 2.58.29 → 2.58.30 (прецедент S10: иначе `test_round1025_f8_registry.py::test_meta_provenance` краснеет при bump). Каталог/TSV/F8 не переиздаются (Δ каталога=0, `--check` OK).
3. **`services/tool_loop.py` не менялся** — «подтверждение/усиление» общего механизма (T-3506…T-3508) выполнено тестами; структурная правка подняла бы риск до R3 (ADR D10). Per-combination обработчиков нет.
4. **Внутренний enum и пред-текстовое действие.** `action` решения ∈ {`tool`,`reply`} (пред-текстовое, до Вербализатора — §14 «решение о действии ≠ текст»); исход доставки логируется отдельно ∈ {`reply`,`react`} (пустой финал ⇒ существующая 🗿-реакция). Значение `silent` присутствует в enum, но **A1 не вводит политику молчания/реакций** (§41/§44 — A8); ветки cooldown/silence-streak/dedup возвращаются до Stage-2 (Вербализатор не запускается) — существующее поведение.
5. **Kill-switch `DIRECT_COORDINATOR_ENABLED`** — env-only `ClassVar` с резолвом per-call (прецедент ADR-1022-4/-5); «hot-OFF» действует на уровне атрибута настроек; смена env требует рестарта — как у существующих env-kill-switch'ей (Δ каталога=0).
6. **Гейт Stage-2 эквивалентен baseline:** `action == ACTION_TOOL` ⇔ `tool_trace` непуст ∧ не `degraded` ∧ не `lore_compiled`. Проверено `TestHandleGate::test_gate_equivalence_on_off` (ON ≡ OFF по исходу гейта).

## 8. Незакрытое / вне Step 3

- **Коммит, единый Reviewer gate (T-3518/T-3519), merge (T-3520), архивация (T-3521), deploy/bump в прод (T-3522), handoff → A2 (T-3523/T-3524)** — не выполнялись (следующие шаги).
- **Чекбоксы `tasks.md`** не проставлялись (правки `tasks.md` — только @PM).
- **A2 (§15–§17), A7 (`action`/`style`)** — вход зафиксирован, не реализованы.
