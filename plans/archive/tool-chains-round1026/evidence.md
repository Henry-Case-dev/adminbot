# A2 `tool-chains-round1026` — Evidence (Step 3 @Builder, T-3528…T-3544)

- **Epic-ID:** Эпик 3 «Agentic Intelligence» (Wave 2). **Feature-ID:** `tool-chains-round1026`.
- **Spec:** `plans/features/tool-chains-round1026/spec.md` (REQ-A2-01…-10, SC-A2-01…-13). **ADR:** `adr-1026-15-tool-chain-contract-and-limits.md` (D1–D12).
- **Risk:** **R3** — R3-артефакты: `threat-failure-analysis.md` (этот каталог) + rollback/adversarial ниже.
- **Release policy:** **EPIC_ONLY** — **deploy НЕ выполнялся**; `APP_VERSION` **не бампался** (2.58.30); фича — вклад в pending epic-release Эпика 3.
- **Baseline:** HEAD `e8646af2bcaa79b55cadda756d0e8cc7789fe24f` == tag `pre-round1026-a2` (annotated). Рабочее дерево — незакоммиченные изменения (см. §6). **Коммитов из Step 3 нет.**

## 1. Что реализовано (блоки B–G)

### Блок B — структурированный контракт §16 (T-3528/T-3529/T-3530)
- `services/tool_loop.py:48-55` — §17-константы/причины; `:55-60` `METERED_TOOLS`; `:120-127` `_chain_limits_enabled`; `:129-140` `_args_fingerprint` (R17-safe хэш 16 hex); `:143-184` `_classify_output` (status/error_code/error_type/data/truncated); `:187-198` `_record`; `:201-221` `_make_envelope`; `:96-104` `ToolLoopResult.__new__` — аддитивный `tool_results`; `:86-92` docstring envelope.
- `services/tool_router.py:456-468` — `ToolContext.result_for(tool_name)` (общий handoff); `:445` `ctx.tool_results`.
- Envelope на **каждый** вызов в `chat_with_tools` (все ветки: parse-error `:345-361`, dedup `:363-384`, skip `:387-411`, dispatch `:413-449`); модельно-видимый `role:"tool"`-content и `tool_context` **не изменены** (гибрид D1). Существующий `ToolLoopResult`/`tool_trace` переиспользованы аддитивно (ключи `tool_trace` байт-в-байт).
- Структурированные ошибки (D2): классификация «ОШИБКА …» и JSON `status:error`; ошибка одной не роняет цикл.

### Блок C — зависимые цепочки §15 + резолв ссылки (T-3531/T-3532/T-3533)
- Зависимые A→B исполняются существующим многораундовым `tool_loop` (последовательно); программный handoff — `ctx.result_for` (`services/tool_router.py:456-468`).
- `services/smartmodule_urls.py:44-62` — `resolve_context_url(*texts)` (общий, не per-phrase).
- `services/direct_chat_service.py:140` (импорт), `:951-963` — вычисление `resolved_url` (текущее сообщение → reply) и передача в `ToolContext` (`:958`).
- Параллельность не вводится (D4): `asyncio.gather` отсутствует в `tool_loop.py`/`tool_router.py` (тест `test_no_asyncio_gather_in_chain_sources`).

### Блок D — лимиты/тайм-аут/дедуп/частичный результат §17 (T-3534/T-3535/T-3536)
- `services/tool_loop.py:48-53` — `TOOL_MAX_TOTAL_CALLS=6`, `TOOL_CHAIN_TIMEOUT_SECONDS=360.0`, `_TOOL_MAX_SAME_CALL=2`, `TOOL_CHAIN_MAX_METERED_CALLS=4`.
- Мягкий тайм-аут: граница раунда `:264-275`, перед диспетчем `:389-411` (in-flight не отменяется).
- Дедуп `:363-384`; cap/стоимость `:387-411`; деградация `chain_timeout`/`chain_call_limit`/`chain_cost_limit` с частичным результатом `:451-465`; существующая `round_limit`/`llm_error` сохранена.
- Рубильник env-only `config/settings.py:892-895` (`TOOL_CHAIN_LIMITS_ENABLED`, default ON).

### Блок E — `fetch_article` атомарно (T-3537/T-3538)
- `services/tool_schemas.py:348-374` — `TOOL_FETCH_ARTICLE` (EN, `url` optional, `required=[]`, `additionalProperties=false`); `:375-387` — регистрация 11-й (в хвост); `:396` `ARTICLE_TOOL_NAME`; `:408-414` `_article_tool_enabled`; `:417-440` гейт `active_tools`; docstring `:49` «R9 = **11**».
- `services/tool_router.py:378-401` — `ToolDeps.extractor` (additive); `:438-445` `ToolContext.resolved_url`/`tool_results`; `:504` registry; `:1032-1099` `_fetch_article` (reuse `extractor.extract`, JSON-контракт, `source_id` 12-hex, `_ARTICLE_MAX_SYMBOLS=8000` `:121`, `_ARTICLE_TOOL_TIMEOUT=45.0` `:120`); `:1101-1109` best-effort `title`.
- `bot.py:504-510` — DI `extractor=_web_extractor` (тот же инстанс `WebContentExtractor`, без дубля сервиса).
- Рубильник env-only `config/settings.py:894-895` (`ARTICLE_TOOL_ENABLED`, default ON).

### Блок G — границы/интеграция (T-3543/T-3544)
- §104/§85-UI/ExecutionGraph не тронуты (diff-аудит §5); `factcheck_tools`=3 без изменений; A3/A4/A6/A7/A8/A9 не реализованы; 0 новых LLM-вызовов.

## 2. Файлы (изменённые / новые)

**Product code (7):**
| Файл | Суть |
|---|---|
| `config/settings.py` | +2 env-only `ClassVar` рубильника (:892-895) |
| `services/tool_schemas.py` | +`fetch_article` схема/регистрация/гейт; канон 11 |
| `services/tool_loop.py` | envelope + §17-лимиты/дедуп/тайм-аут/деградация |
| `services/tool_router.py` | `ToolDeps.extractor`, `ToolContext.resolved_url/tool_results/result_for`, `_fetch_article` |
| `services/smartmodule_urls.py` | +`resolve_context_url` |
| `services/direct_chat_service.py` | resolved_url в `ToolContext` |
| `bot.py` | +DI `extractor=_web_extractor` (5 insertions) |

**Тесты — новый файл:** `tests/test_tool_chains_round1026.py` (43 теста).
**Тесты — обновления канона 10→11/рубильников (10 файлов):** `tests/test_tool_schemas.py`,
`test_agentic_ai_round1020.py`, `test_image_generation_round1023.py`,
`test_media_transcribe_tool_round1024.py`, `test_native_media_tools_round1024.py`,
`test_recent_history_tool_round1015.py`, `test_tool_calling_round1015.py`,
`test_tool_coordinator_round1026.py`, `test_tool_download_quality_round1017.py`,
`test_summary_deploy_round1026.py`, `test_summary_publish_integration_round1026.py`.

## 3. Команды и результаты (фактические)

| Проверка | Команда | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **9125 passed / 0 failed** (baseline 9082 + **43** новых теста) |
| A2-набор | `.venv\Scripts\python.exe -m pytest tests/test_tool_chains_round1026.py -q` | **43 passed** |
| Канон/схемы/рубильники | `pytest tests/test_tool_schemas.py tests/test_tool_calling_round1015.py -q` | passed |
| 2-вызовность | `pytest tests/test_direct_two_call_round1022.py -q` | passed (`await_count==2`) |
| JS | `node tests/js/<каждый>.js` (47 файлов) | **JS OK=47 FAIL=0** (node v24.16.0) |
| Whitespace | `git diff --check` | **exit=0** (только CRLF-предупреждения) |
| Канон | `len(TOOL_CALLING_TOOLS)` | **11** (`fetch_article` в хвосте) |
| Каталог | импорт `param_catalog` (тест) | REGISTRY **469** / GROUPS **100** / `_TAB_BY_GROUP` **98** / TAB_RULES **21** / Settings **426** / categorized **444** |
| Δ DDL | grep `CREATE/ALTER/DROP TABLE|CREATE INDEX` в A2-источниках | **0** |
| `APP_VERSION` | `config/settings.py` | **2.58.30 (не бампался)** |

> Финальный полный прогон: **9125 passed / 0 failed** (baseline 9082, без регрессий; +43 новых в `test_tool_chains_round1026.py`).

## 4. Покрытие приёмки (SC → тест)

| SC | Тест |
|---|---|
| SC-A2-01 | `test_dependent_chain_a_then_b_sequential` |
| SC-A2-02 | `test_dependent_chain_a_then_b_sequential`, `test_two_tools_sequential_one_round` (baseline) |
| SC-A2-03 | `test_no_per_phrase_handler`, `test_resolve_context_url_*` |
| SC-A2-04 | `TestEnvelope::*`, `test_fetch_article_schema`-блок, `test_atomic_registration_canon_eleven` |
| SC-A2-05 | `test_envelope_recorded_on_every_call`, `test_model_visible_channel_unchanged` |
| SC-A2-06 | `test_structured_error_does_not_kill_llm`, `test_structured_error_from_json_status`, `test_adversarial_mixed_errors` |
| SC-A2-07 | `test_total_call_cap_six`, `test_metered_call_limit_four`, `test_dedup_same_call_max_two`, `test_soft_timeout_does_not_cancel_inflight`, `test_timeout_skips_new_calls`, `test_free_calls_not_cost_limited` |
| SC-A2-08 | `test_no_asyncio_gather_in_chain_sources` |
| SC-A2-09 | `test_resolve_context_url_single_current`, `test_resolve_context_url_falls_back_to_reply`, `test_uses_resolved_url_from_context` |
| SC-A2-10 | `test_no_ddl_in_a2_sources`, `test_catalog_counts_unchanged`, `test_two_call_condition_preserved` |
| SC-A2-11 | `test_kill_switches_not_in_catalog`, `test_catalog_counts_unchanged`, `test_no_ddl_in_a2_sources` |
| SC-A2-12 | `test_limits_off_does_not_change_model_visible`, `test_off_legacy_effective_canon_ten`, `test_limits_off_no_cap`, `test_direct_two_call_round1022` |
| SC-A2-13 | `test_atomic_registration_canon_eleven`, `TestFetchArticle::*`, `test_factcheck_tools_unchanged` |

R17: `test_no_payload_in_logs`, `test_degraded_log_r17_safe`, `test_fetch_article_url_not_logged`.
Adversarial: см. `threat-failure-analysis.md` §2 (все PASS).

## 5. Diff-аудит границ

```
git diff --name-only pre-round1026-a2
```
Список: `bot.py`, `config/settings.py`, `services/{direct_chat_service,smartmodule_urls,tool_loop,tool_router,tool_schemas}.py`,
тесты канона (11 файлов), а также **пред-существующие** `plans/MEMORY.md`, `plans/workflow_state.md`
(владелец — @Orchestrator/@Memory; в A2 **не менялись** мной).

**Запрещённые пути — ВНЕ diff:** `services/image_generation.py` (§104), `services/summary_prompts.py`,
`services/prompt_migrations.py`, `services/param_catalog.py`, `db/**`, `web/**`, `web/api/routes.py`,
публикационные/`summary_*`-модули. **`bot.py`** — только аддитивная DI-строка `extractor=_web_extractor`
(`git diff pre-round1026-a2 -- bot.py`: 5+/1−), санкционировано D5.

Неотслеживаемые (новые) файлы: `tests/test_tool_chains_round1026.py` (**A2**),
`plans/features/tool-chains-round1026/{spec.md,adr-…,tasks.md}` (Step 1/2) + этот `evidence.md`/`threat-failure-analysis.md`.

## 6. Точное состояние (binding-вход для @Reviewer)

- `git rev-parse HEAD` = `e8646af2bcaa79b55cadda756d0e8cc7789fe24f`.
- `git status --short` (tracked, A2-релевантные): ` M bot.py`, ` M config/settings.py`,
  ` M services/direct_chat_service.py`, ` M services/smartmodule_urls.py`, ` M services/tool_loop.py`,
  ` M services/tool_router.py`, ` M services/tool_schemas.py`, 11 ` M tests/...`.
  Untracked: `?? tests/test_tool_chains_round1026.py`, `?? plans/features/tool-chains-round1026/`.
- Коммитов нет; теги/бэкапы (`pre-round1026-a2` → `e8646af`) не удалялись (R18).

## 7. Отклонения / вопросы к @Reviewer

1. **Обновлены 2 boundary-теста прошлых фич** (`tests/test_summary_deploy_round1026.py::TestBounds::test_forbidden_paths_unchanged`,
   `tests/test_summary_publish_integration_round1026.py::TestBoundaries::test_forbidden_paths_outside_diff`):
   они объявляли `bot.py` «запрещённым» относительно тегов `pre-round1026-s10`/`pre-round1026-s6`, но A2
   санкционированно добавляет в `bot.py` одну DI-строку (`extractor=_web_extractor`, D5). `bot.py` убран из
   их списков с поясняющим комментарием; остальные запрещённые пути проверяются как прежде. Прошу подтвердить
   правомерность либо вернуть в иной форме.
2. **Значение `_ARTICLE_MAX_SYMBOLS=8000`** — spec не фиксирует; выбрано как bounded (статья богаче поиска,
   усечение честно отражается в `truncated`/`chars`). Прошу подтвердить/скорректировать при merge.
3. **R-1 (300 c vs 360 c)** — реализовано авторитетное значение ADR/spec **360.0 c** (`TOOL_CHAIN_TIMEOUT_SECONDS`).
4. **Границы OFF-байт-в-байт**: доказано эквивалентностью ON/OFF-ветвей одного кода (envelope out-of-band)
   + эффективным каноном 10 при `ARTICLE_TOOL_ENABLED=false`; отдельный прогон baseline-кода в сессии не делался.
5. `plans/MEMORY.md`/`plans/workflow_state.md` изменены **не** в A2 (владельцы @Memory/@Orchestrator) —
   исключить из A2-манифеста при расчёте binding.

## 8. Чего НЕ делалось (границы)

- Deploy/activation/bump версии (EPIC_ONLY, D8) — не выполнялись.
- §104 `generate_image`, §85-UI/каталог, промпты (ADR-1013-3 NOT_APPLICABLE), DDL — не менялись.
- A3/A4/A6/A7/A8/A9 — не реализованы; ExecutionGraph — REUSE (вторая аналитика не создана).
- Коммиты/Scanner/правки `current_task.md`/`tasks.md`/spec/ADR/backlog/metrics/ARCHITECTURE — не выполнялись.
