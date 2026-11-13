# S7-FINALIZE (этап G) — обязательная финализация инструментального исследования

- **Epic:** SMART-EXECUTION-RELIABILITY-01, slice **S7-FINALIZE** (этап G).
- **Owner input:** `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`,
  §G1–§G5; требования `SXR-G1-01`, `SXR-G2-01`, `SXR-G3-01`, `SXR-G4-01`,
  `SXR-G5-01`.
- **Кандидат:** `cffc9fb2` (ветка `smart/g-finalize`); родитель — `8d15d2c3`
  (финальная фаза), база — одобренный `8fc8b534` (A+B).
- **Диапазон:** `8fc8b534..cffc9fb2` — 2 коммита: `8d15d2c3` (финальная фаза)
  и `cffc9fb2` (корректировки маршрутов/evidence/prompt-реестра).
- **Изменённые файлы:** `services/tool_loop.py`, `services/prompt_registry.py`,
  `docs/prompt-versioning-contract.md`, `tests/test_smart_g_finalize_round1114.py`,
  `tests/test_agentic_ai_round1020.py`, `tests/test_smoke_round1016_tool_loop.py`,
  `tests/test_tool_calling_round1015.py`, `tests/test_tool_coordinator_round1026.py`,
  `tests/test_prompt_field_audit.py`, `tests/test_ur_f_inspector_step1.py`,
  `tests/test_evol018_prompt_audit.py`.
- **Не менялось:** деплой, прод, схема БД, каталог, второй агент/пайплайн.

## 1. Реализованный контракт (наблюдаемое поведение)

| Требование | Поведение в кандидате | Где |
|---|---|---|
| G2: две фазы без нового агента | Исследование — существующие tool-раунды; финал — существующий `llm.generate` без tools, один вызов | `_finalize_from_evidence`, `_finish_degraded` |
| G2: нет лишнего вызова при готовом ответе | Штатный финальный текст модели возвращается как есть (`finalize_mode=""`, 0 доп. вызовов) | ветка `not result.tool_calls` |
| G2: финал не зависит от лимита исследования | `_finish_degraded` не вызывает `_volume_skip`/fuse; причина остановки передаётся как факт | `_finish_degraded` |
| G3: сохранение при любом исходе | `ToolLoopResult` сохраняет `tool_results`/`tool_context`/`tool_trace`; финальный payload содержит исходные сообщения, tool-результаты и директиву с запросом/причиной/отказами/непроверенным | `_evidence_inventory`, `_finalize_directive`, `_structured_partial` |
| G3: отказ одного источника не обнуляет run | Ошибки/таймауты/`denied` остаются в журнале, остальные результаты используются | `_usable_evidence`/`_failed_evidence` |
| G3: не только последний текст модели | При наличии tool-результатов `partial_text` не подменяет финал | `_finish_degraded` |
| G4: нормальный финал | Ответ модели по evidence, без повторных инструментов | штатная ветка |
| G4: деградация содержательна | LLM-финал по фактическим данным; недоступен/пуст — детерминированный структурный partial с подтверждённым, отказами, provenance, непроверенным и причиной | `_finish_degraded`, `_structured_partial` |
| G4: без саркастичной заглушки при данных | `TOOL_LOOP_FALLBACK_PHRASE` — только когда данных нет вовсе | `_finish_degraded` |
| G5: структурированные ошибки | Используются существующие `status/error_code/retryable` envelope | `tool_result` |
| G5: `retryable=false` терминален | Идентичный вызов не диспетчится; другие URL/хосты того же терминального маршрута получают структурный `route_terminal` без сетевого вызова | `_reuse_reason`, `_remember_terminal`, `_route_suppression` |
| G5: tool-scoped отказы | `disabled`/`unknown_tool`/`provider_unconfigured` закрывают инструмент целиком (смена аргументов не помогает) | `TOOL_SCOPED_TERMINAL_CODES`, `_terminal_route_of` |
| G5: транзиентный `retryable=true` не закрывает маршрут | `provider_unavailable`/`provider_stalled` не попадают в terminal-routes; retry/dedup работает как раньше | `_terminal_route_of` |
| G5: альтернативный источник | Маршрут идентифицируется по `tool|host`; другой хост диспетчится; для single-provider инструментов маршрут = инструмент; `verified_url` участвует в host-идентичности | `_route_key`, `_route_host_from_info` |
| G5: ресурсный отказ не закрывает host | `extract_failed` (конкретный URL) исключён из terminal-routes; другой URL того же хоста пробуется | `ROUTE_TERMINAL_CODES`, `_terminal_route_of` |
| G5: без анализа пользовательского текста | Только структурные `status/error_code/data` | — |
| EVOL-018 | Новый prompt-блок `direct.tool_finalize` объявлен в реестре, заводская ревизия/печать и `FACTORY_SET_SHA256_12` обновлены; §2 контракта — 113 блоков | `prompt_registry.py`, docs |
| UR-F | Новый исходящий вызов `_finalize_from_evidence.llm.generate` классифицирован в inventory как `covered:tools` | `tests/test_ur_f_inspector_step1.py` |

## 2. RED на базе `8fc8b534`

Проба: `evidence/g/g_probe.py` (self-contained, cwd = checkout), вывод —
`evidence/g/red-base-8fc8b534.jsonl`. Команда:

```
python plans/features/smart-execution-reliability-01/evidence/g/g_probe.py
```

| Сценарий | Наблюдение на `8fc8b534` |
|---|---|
| остановка после tool-результата (`llm_error`) | саркастичная заглушка, `finalize_calls=0`, `finalize_mode` отсутствует |
| финальный LLM недоступен | та же заглушка, structured partial отсутствует |
| `no_progress` с 3 результатами | заглушка вместо ответа по данным |
| исчерпан явный лимит вызовов | заглушка вместо ответа по накопленному результату |
| `retryable=false`, другой URL того же host | повторно диспетчится (2 сетевых вызова) |
| `retryable=false`, single-provider инструмент | повторно диспетчится (2 вызова) |
| `retryable=false`, host из `verified_url` | повторно диспетчится (2 вызова) |
| план + отказ политики + финальный LLM недоступен | `LLMError: writer down` — ответа нет вообще |

Транзиентный `retryable=true` на базе также диспетчится повторно (2 вызова) —
это ожидаемое поведение, сохранённое в кандидате (не over-suppression).

## 3. GREEN на кандидате `cffc9fb2`

Точный код: отдельный detached-worktree `HEAD=cffc9fb2`,
`tree=d325ce7f51f7af21fd6d5e270a085d69e4f83215`,
`services/tool_loop.py` blob `b228e6ba`; `git diff --exit-code cffc9fb2` по
`services tests docs` — пусто. Проба запускалась из этого worktree:
`python <candidate>/plans/features/smart-execution-reliability-01/evidence/g/g_probe.py`.
SHA256 probe — `5f238ad1636fc3aba45456876469eb77d9bf4b530da743e31b37d21962bf2fcc`;
вывод — `evidence/g/green-cffc9fb2.jsonl` (SHA256
`96fcb794da5f1a867b8dd10be77ddcac7870e0f6ada42be9d068772f62e1fed7`), идентичен
прогону в рабочем worktree.

Предыдущий committed `green-cffc9fb2.jsonl` был сгенерирован до синхронизации
probe-скрипта и показывал 2 вызова для `nonretryable_same_host`; артефакт
перегенерирован на точном `cffc9fb2`, расхождение устранено (1 вызов,
`denied/route_terminal`).

| Сценарий | Наблюдение на кандидате |
|---|---|
| остановка после tool-результата | `finalize_mode=llm`, 1 финальный вызов, ответ по evidence |
| финальный LLM недоступен | `finalize_mode=structured_partial`, причина `llm_error`, запрос/источник/provenance в тексте, заглушки нет |
| `no_progress` | `finalize_mode=llm`, ответ по 3 результатам |
| исчерпан лимит | `finalize_mode=llm`, ответ по доступному результату; отказ политики в журнале |
| `retryable=false`, другой URL host | `router_calls=1`, второй — `statuses=["error","denied"]`, `route_terminal` |
| `extract_failed` одного URL, другой URL того же host | 2 вызова: ресурсный отказ не закрывает альтернативу (statuses `error`, `ok`) |
| `retryable=true`, другой запрос | 2 вызова (транзиентный отказ не закрывает маршрут) |
| single-provider `retryable=false` | 1 вызов; второй запрос — `denied` |
| host из `verified_url` | 1 вызов; другой файл — `denied` |
| план + отказ политики + финальный LLM недоступен | `structured_partial` называет `fetch_article: chain_call_limit`, сохраняет данные первого шага |

## 4. Тесты (venv `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, `-p no:cacheprovider`)

- `tests/test_smart_g_finalize_round1114.py` — **17 passed**:
  `evidence/g/pytest-g-cffc9fb2.txt`.
- Фокусный набор (G + обновлённые round1015/1016/1020/1026 + mca11/mca23/agentic
  events/checkup/factcheck/UR-F/prompt pins) — **435 passed, 2 failed**;
  оба падения — pre-existing bounds-тесты (см. §5):
  `evidence/g/pytest-focused-cffc9fb2.txt`.
- Широкий набор файлов, упоминающих `chat_with_tools|tool_loop` (44 файла,
  без `test_evol018_prompt_audit.py`: он добавлен в выборку только из-за
  текста комментария и загрязняет общий прогон, см. §5) — **1574 passed,
  14 failed**; те же 14 падений воспроизводятся на `8fc8b534`
  (`14 failed / 1557 passed`; дельта +17 passed — это 17 G-тестов):
  `evidence/g/pytest-tool-loop-cffc9fb2.txt`.
- Prompt-audit отдельно — **23 passed, 3 failed** (pre-existing, см. §5):
  `evidence/g/pytest-prompt-audit-cffc9fb2.txt`.

Счётчики G-файла: 17 тестов, 0 skipped, 0 xfail; покрыты нормальный финал,
остановка с evidence, отказ одного источника, все недоступны, недоступный
финальный LLM, исчерпанные счётчики, `retryable=false` (идентичный вызов,
другой host, single-provider, `verified_url`, tool-scoped `disabled`),
транзиентный `retryable=true`, ресурсный `extract_failed` с альтернативой на
том же host, план + отказ политики, отсутствие заглушки при данных, общий
контракт checkup/factcheck.

## 5. Обязательные мутации (review blocker)

### 5.1. Возврат саркастичной заглушки при наличии данных

Мутация — `evidence/g/mutation-a-fallback-with-data.diff`: в
`_finish_degraded` при `items` безусловно возвращается
`TOOL_LOOP_FALLBACK_PHRASE` (finalize/structured partial обойдены).

- RED: `evidence/g/mutation-a-red.txt` — **8 failed / 9 passed**:
  `test_stop_with_evidence_finalizes_with_context`,
  `test_one_failed_source_does_not_reset_research`,
  `test_all_sources_failed_finalize_names_failures`,
  `test_final_llm_unavailable_gives_structured_partial`,
  `test_exhausted_research_counters_do_not_block_finalize`,
  `test_checkup_research_stop_returns_finalized_text`,
  `test_factcheck_tool_path_uses_same_finalization`,
  `test_policy_denied_plan_step_named_in_structured_partial`.
- Restore: `git checkout -- services/tool_loop.py`;
  `git diff --exit-code cffc9fb2 -- services/tool_loop.py` → exit 0
  (`evidence/g/mutation-a-restore.txt`).
- GREEN: `evidence/g/mutation-a-green.txt` — **17 passed**.

### 5.2. Разрешение повтора терминального маршрута

Мутация — `evidence/g/mutation-b-terminal-repeat.diff`: `_terminal_route_of`
безусловно возвращает `""`, terminal-routes не записываются.

- RED: `evidence/g/mutation-b-red.txt` — **4 failed / 13 passed**:
  `test_disabled_tool_is_terminal_tool_wide`,
  `test_route_host_from_verified_url`,
  `test_single_provider_route_is_tool_wide`,
  `test_other_query_to_blocked_host_not_dispatched`.
- Restore: exit 0 (`evidence/g/mutation-b-restore.txt`).
- GREEN: `evidence/g/mutation-b-green.txt` — **17 passed**.

## 6. Requirements map и strict review gate

Карта скопирована в ветку кандидата байт-в-байт с master
(`plans/features/smart-execution-reliability-01/requirements-map.json`,
SHA256 `61c99c0e8fe4a6184fe3511a2803c42104936f36ca54c9f46240849bce89bafd`);
содержимое не менялось. Также скопированы `slice-graph.json`,
`requirements-map-fc-amendment.json`, source-inventory, evidence-артефакты и
owner-inputs (`32ef8c82…` и `767baf0a…`) — без правок.

Команда gate:

```
python <OPENCODE_CONFIG>/tools/requirements_gate.py check \
  --map plans/features/smart-execution-reliability-01/requirements-map.json \
  --stage review --slice S7-FINALIZE --candidate cffc9fb2
```

Результат (`evidence/g/gate-review-cffc9fb2.txt`): карта найдена и
инвентаризация выполняется (`inventory=509 manual=359 scoped=47`), но
**errors=48**: 1 `candidate mismatch` (map-level `candidate_commit` пуст в
master-карте) + 47 строк S7 со статусом `PENDING`. Это состояние
PM-owned карты; §G её не правит. Gate больше не падает на
`FileNotFoundError` — структурная блокировка «карты нет» снята.

## 7. Pre-existing падения базы (не дельта §G)

Все перечисленные падения воспроизведены на `8fc8b534` в отдельном
detached-worktree (`smart-execution-reliability-01-...`, временный):

- `tests/test_tool_coordinator_round1026.py::TestBounds.*` (2) — drift базы:
  `TOOL_CALLING_TOOLS` 18 против пина 17 и diff-baseline содержит
  несанкционированные web-пути.
- `tests/test_direct_fallback_recompose_asap32.py` (5) — несовпадение
  сигнатуры `_fallback_with_retries(..., sent=...)` в базе.
- `tests/test_image_generation_round1023.py` (3) — канон инструментов 18 vs 8/9.
- `tests/test_unified_image_request_round1026.py` (2) — канон/границы путей.
- `tests/test_er65_sent_segment_snapshot.py` — снимок недетерминирован на базе.
- `tests/test_mca16_experience_block_d_round1039.py` — drift блока опыта.

Отдельно, prompt-audit (не входит в широкую выборку §4):

- `tests/test_evol018_prompt_audit.py` (2) — на базе 323 файла против пина 312
  и `services/prompt_readback.RESOURCE_KIND_PROMPT` вне реестра; §G добавил
  ровно +1 зарегистрированный кандидат (`TOOL_FINALIZE_PROMPT`), пины §5
  обновлены на 76/75, но файловый пин остаётся красным из-за параллельного
  среза.
- `tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`
  — `direct.base.synthesizer` без поверхности в базе ветки.

Наблюдение по изоляции (BACKLOG_ONLY, не §G):
`test_asap5_integration_w3.py::TestNostalgiaProvenance::test_d13_published_memory_not_reproposed`
проходит одиночно и всем файлом, но падает, если `test_evol018_prompt_audit.py`
исполнялся раньше в том же процессе. Это pre-existing загрязнение глобального
состояния тестами prompt-audit, не дефект кандидата.

## 8. Конфигурация и границы проверки

- Поведение §G не гейтится новым флагом: финализация и route-suppression
  работают при заводских значениях `MCA_TOOL_MAX_*=0` (политика объёма не
  задана). В тестах счётчиков явно включены `budget_gate.budgets_enabled=True`
  и `MCA_TOOL_MAX_TOTAL_CALLS=1` — это тестовый override, не продакшен-дефолт.
- `MCA_TOOL_RESULT_ENABLED` (K1) заводски ON; существующие K1 OFF тесты
  (`test_mca11_tool_result_round1028.py`) прошли — envelope legacy-формы не
  сломан.
- **Не проверено в этом срезе:** реальные внешние provider-endpoint’ы и живой
  Telegram-путь (деплой в задачу не входил). Route-suppression — структурная
  эвристика по `tool|host`; `extract_failed` намеренно оставлен ресурсным
  (альтернативный URL того же хоста пробуется), а `destination_blocked`/
  `auth_failed`/`provider_*` закрывают маршрут. Реальная прод-таксономия
  провайдеров не воспроизводилась — это остаётся для независимой проверки
  Reviewer’ом.
- Деплой/прод не выполнялись.

## 9. Housekeeping

- Проба и JSONL — `evidence/g/`; pytest-логи — `evidence/g/`.
- Одноразовый run `.../probe-207f3231f9` удалён после переноса доказательств.
- Точный detached-worktree `cffc9fb2` удалён после probe/pytest; base-worktree
  `8fc8b534` удалён после снятия RED.
- `unit-check` для `smart-g-finalize`: `cleanup_complete=true`,
  `handoff_accounted=true`, `remaining=[]`; candidate-worktree сохранён для
  независимого review.
