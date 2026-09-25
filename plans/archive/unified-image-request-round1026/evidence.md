# A3 `unified-image-request-round1026` — evidence (Step 3 @Builder, T-3555…T-3579)

- **Epic-ID:** Эпик 3 «Agentic Intelligence» (Wave 2). **Дата:** 24.09.2026.
- **Baseline:** HEAD **`e8646af`** == `origin/master`; рабочее дерево содержит
  **незакоммиченный A2** (pending Epic 3 release candidate — сохранён, ни одна
  правка A2 не доломана, полная suite это подтверждает).
- **Точный фиксированный baseline-факт:** APP_VERSION **2.58.30** (без bump —
  разрешает D8; проверка `test_kill_switch_env_only_not_in_catalog` /
  `test_version_and_catalog`); pytest `.venv` **9125/0** (verified A2) → после A3
  **9156/0**; JS **47/47** → **47/47**; каталог 469/426/444/100/98/21 → **тот же**;
  канон **11** (`generate_image` — 9-й) → **тот же**; **Δ DDL=0** (SQLite v12).
- **Release policy:** `EPIC_ONLY`, deploy = `DEFERRED_TO_EPIC`; **коммитов нет**;
  **бамп-версии нет**; `README.md` не тронут (разрешён, не требован; факт-пункт —
  на границе эпик-релиза @DevOps); теги/бэкапы не удалялись (R18).

## 1. Диагностика блока B (T-3555…T-3558) — вердикты HY-01…HY-06

Полный протокол — `plans/features/unified-image-request-round1026/image-diagnostics.md`.

| HY | Вердикт | Ключевое доказательство |
|---|---|---|
| HY-01 | **НЕПОДТВЕРЖДЕНО** (проба из env невозможна: `https://apinet.cloud/v1` 500 `get_channel_failed` на `deepseek-v4-flash` — и с tools, и БЕЗ: не специфика tools; прод-конфиг — PG, отсюда недоступен) | Живая проба 10×`chat/completions` c `tools` через `services.llm_client` + контроль без tools; ключ не печатался |
| HY-02 | **НЕПОДТВЕРЖДЕНО / НЕ ОПРОВЕРГНУТО** (прод-логов нет) | Код-факт классификации (`[image] generation failed`/`attempt failed │ reason_class=…`); прод-логи → владельцу |
| HY-03 | **ЧАСТИЧНО ОПРОВЕРГНУТО**: env-слой — все рубильники ON (`IMAGE_*`, `TOOL_CHAIN_*`, `ARTICLE_*`); per-chat — не читаем (нет PG) | Чтение `.env`+settings 24.09.2026 |
| HY-04 | **НЕПОДТВЕРЖДЕНО / НЕ ОПРОВЕРГНУТО** (механизм `tool_loop.py:288–299` факт; прод-логов нет) | Повторное чтение кода; grep journald → владельцу |
| HY-05 | **НЕПОДТВЕРЖДЕНО** (A/B-проба не дала результат — env-эндпоинт лежит целиком) | A/B OLD/NEW описание на 5 фразах — все 10 попыток `LLMServerError` |
| HY-06 | **МЕХАНИКА ПОДТВЕРЖДЕНА** (узкий scope пре-гейта доказан кодом: только «бот/bot + глагол рисования»); привязка к observed-сбоям — недоказуема (corpus нет) | `IMAGE_KEYWORD_RE` (`image_generation.py:93–101`) + разветвление `image_pre_gate_fired → image_enabled=False` (`direct_chat_service.py:881/938`) |

**Согласованность минимального фикса с ADR-1026-16 (D1):** внешняя причина
(провайдер/модель) **не доказана** ⇒ стоп-ветка «внешняя причина → останавливать
C/D/E» **не активирована** — и это обоснованно: ни один факт не указывает на отказ
прод-провайдера. Унификация §18/§20 выполняется всегда (требование ТЗ, п.1 правила
решения D1); остальные фиксы (D3-маркер, §21-валидация/доведение reason/возврат в
цикл, D4-текст) являются фактом требований §18–§21 и не опираются на нераскрытые
гипотезы. **AMEND-черновик (вносится @Architect, T-3582; ADR-1026-16 не редактировался
Builder-ом:** см. раздел 7 ниже.

## 2. Изменённые файлы (A3, точно)

| Файл | Что (A3) | Ключевые строки (факт) |
|---|---|---|
| `services/image_generation.py` | **A3 only** (файл не входил в A2‑diff): ClassVar-гейт `unified_image_request_enabled`; dataclass `ImageRequest`; конструктор `build_image_request`; единственная сборка `build_final_prompt`; раннер `run_image_request` → существующий `generate_and_send`; прямой путь `maybe_handle_keyword` строит `ImageRequest(source="direct")` при ON, при OFF — legacy-вызов по-байту прежний | `:190`, `:202`, `:227`, `:246`, `:256`, `:1047` (ON-ветка `:1064–1068`, OFF-ветка `:1073+`) |
| `services/tool_router.py` | A3 поверх A2: аддитивное поле `ToolContext.image_request_handled` (keyword-only, default False); `_generate_image`: проверка маркера ПЕРВЫМ делом → `{"status":"skipped","reason":"already_handled"}` без генерации/бюджета; при ON строит `ImageRequest(source="tool")` → `run_image_request`; при OFF — прежний прямой вызов. Гейт модуля/валидация/доведение реального `reason` — прежние | `:425`, `:446`, `:1559` (маркер `:1579–1590`, ImageRequest-ветка `:1596–1607`, legacy `:1608+`) |
| `services/direct_chat_service.py` | A3 поверх A2: исполнимого логика та же (`image_pre_gate_fired → image_enabled=False` — сохранена, `:938–939`); прокид маркера в `ToolContext` (`image_request_handled=image_pre_gate_fired`) | `:967–968` |
| `services/tool_schemas.py` | A3 поверх A2: **только текст** описания → два варианта схемы (`*_LEGACY` байт-в-байт baseline-текст; `*_V21` — 6 пунктов §21); активный — по env-only киль-свитчу (default ON). Состав/имена/порядок/`required`/`additionalProperties`/`factcheck_tools`=3 — без изменений; канон 11 | `:329`, `:350`, `:389–393` (+ апдейт комментария-счётчика над канон-листом) |
| `config/settings.py` | A3 (env-only `ClassVar`, Δ каталога=0): `UNIFIED_IMAGE_REQUEST_ENABLED` (default True) | `:897–905` |
| `tests/test_unified_image_request_round1026.py` | **Новый** (31 тест): контракт/одна сборка/раннер; прямой ON/OFF; tool ON/OFF; `already_handled`+бюджет; двойной триггер через `chat_with_tools`; fail-closed; реальная ошибка; R17; канон/варианты описания; §104 AST-гейт vs `e8646af`; DDL/каталог/версия; env-only киль-свитч | — |
| `tests/test_tool_coordinator_round1026.py` | A3: `test_forbidden_paths_out_of_diff` — `services/image_generation.py` исключён с NOTE-санcцией (A3); остальные баund-статусы прежние | `:617–638` |
| `tests/test_summary_deploy_round1026.py` | A3: аналогично (NOTE-исключение `image_generation.py`) | `:493–512` |
| `tests/test_summary_execution_graph_round1026.py` | A3: аналогично | `:435–452` |
| `tests/test_summary_publish_integration_round1026.py` | A3: аналогично | `:1237–1250` |

Обновления 4 bound-гейтов — прецедент A2 (`bot.py` NOTE): формальные запреты
прошлых волн передиффятся от **своих** старых тегов; под A3-санкцию `image_generation.py`
попадает допуск (гейт §104 перенесён в AST-тест A3 `TestBoundsA3` —
`git show e8646af` AST-эквивалентность `generate/generate_and_send/generate_image/
generate_image_verbose/extract_prompt/is_image_keyword` + литерал fallback-фразы).

## 3. Границы diff (A2 vs A3) — `git diff --name-only e8646af`

**A2-only пути (не тронуты A3 — byte-проверка A2-набора тестов ✅):** `bot.py`,
`services/smartmodule_urls.py`, `services/tool_loop.py`, `plans/ARCHITECTURE.md`,
`plans/MEMORY.md`, `plans/backlog.md`, `plans/docs/agentic-audit-round1026.md`,
`plans/metrics.md`, `plans/reports/audit_backlog.md`, `plans/round1025-architecture.md`,
`plans/workflow_state.md`, `tests/test_agentic_ai_round1020.py`,
`tests/test_image_generation_round1023.py`, `tests/test_media_transcribe_tool_round1024.py`,
`tests/test_native_media_tools_round1024.py`, `tests/test_recent_history_tool_round1015.py`,
`tests/test_tool_calling_round1015.py`, `tests/test_tool_download_quality_round1017.py`,
`tests/test_tool_schemas.py`.

**Смешанные (A2 baseline-вектор + A3-дополнение):** `services/direct_chat_service.py`
(A3 — одна строка-врезка в существующий конструктор ToolContext), `services/tool_router.py`
(A3 — маркер ToolContext + `_generate_image`- на徽из), `services/tool_schemas.py`
(A3 — только два текстовых варианта описания generate_image), `config/settings.py`
(A3 — один env-only ClassVar).

**A3-only пути:** `services/image_generation.py`,
`tests/test_unified_image_request_round1026.py` (новый; untracked),
4 bound-теста (исключения NOTE),
`plans/features/unified-image-request-round1026/{evidence.md, image-diagnostics.md}` (новые).

**Запрещённые пути — вне diff A3 ✅:** `services/summary_prompts.py`,
`services/prompt_migrations.py`, `services/param_catalog.py`, `db/**`, `web/**`,
`web/api/routes.py`, `services/telegram_send.py`, `services/execution_graph_source.py`,
summary-публикационные модули — не изменены относительно `e8646af` (добавлен A3-гейт
`test_forbidden_paths_out_of_diff_vs_baseline`). §104-генератор — **AST-байт-эквивалентен**
baseline (`test_104_generator_functions_ast_identical`, `test_104_fallback_phrase_unchanged`).
A4 (§22–§25)/A7 (§36–§37)/A5 (§26–§31) вне diff — поля-заглушки `ImageRequest` (`context_required/False`, `context_sources/[]`, `resolved_subjects/[]`) не читают память/RAG/досье.

## 4. Прогоны (номера)

| Проверка | Результат |
|---|---|
| Полный pytest `.venv` (`tests/`, -x, timeout 60) | **9156 passed / 0 failed** (шумов 1 deprecation-warning; baseline 9125 + 31 новый A3) |
| JS (`node`, все 47 `tests/js/*.js`) | **47 passed / 0 failed** (exit=0) |
| `git diff --check` | **exit=0** (0 whitespace-ошибок) |
| Каталог: REGISTRY/Settings-fields/categorized/GROUPS/_TAB_BY_GROUP/TAB_RULES | **469 / 426 / 444 / 100 / 98 / 21** — без Δ |
| Канон `TOOL_CALLING_TOOLS` | **11**, `generate_image` — 9-й (индекс 8) |
| Δ DDL | **0** (нет CREATE/ALTER TABLE в затронутых исходниках — гейт A3; SQLite v12 неизменен) |
| Δ каталога | **0** (`UNIFIED_IMAGE_REQUEST_ENABLED` — env-only `ClassVar`; НЕ в `param_catalog.REGISTRY`, НЕ поле dataclass) |
| APP_VERSION / README | **2.58.30**, без bump, README без Δ |
| `await_count==2` (2-вызовность System 2) | Сохранена (полная suite прошла, включая coordinator-набор; статический гейт: в `image_generation.py` нет `generate_chat`-вызовов, `tool_router.py` не добавлял вызов — `test_two_llm_calls_intact`) |

## 3. Новые/обновлённые тесты (31, файл `tests/test_unified_image_request_round1026.py`)

- **C/D2 (SC-A3-01/-03/-04)**: `TestUnifiedContract` — контракт `ImageRequest`;
  `build_final_prompt` → `extract_prompt` (`Бот, нарисуй красного кота` → `красного кота` — байт-в-байт прежний промпт); `run_image_request` вызывает **существующий** `generate_and_send` с прежними параметрами.
- **C/T-3560 (SC-A3-02)**: `TestDirectPath` — ON строит `ImageRequest(source="direct")`
  с полями из ctx и даёт **байт-в-байт тот же вызов генератора**, что и OFF; OFF —
  без ImageRequest, прямым вызовом baseline.
- **C/T-3561 (SC-A3-01)**: `TestToolPath` — tool-путь строит `ImageRequest(source="tool")`
  и идёт в один раннер; OFF — прежний прямой вызов.
- **D3/T-3563/T-3574 (SC-A3-09)**: `TestAlreadyHandled` — маркер первым делом →
  `skipped/already_handled`, `generate_and_send`/`run_image_request`/`_consume_budget`
  **не вызываются** (бюджет на повтор не тратится); при OFF-киль-свитче — прежнее
  поведение; **adversarial**: полный `chat_with_tools` где модель вызывает
  `generate_image` при `image_request_handled=True` → ровно одна генерация,
  tool-роль содержит skipped, A2-envelope видит `data.status=="skipped"`.
- **D4/T-3568 (SC-A3-06)**: `TestValidation` — fail-closed (`{}` → `status:"error"`
  без генерации; классификация A2-envelope `status=error`, работа цикла не исключается); module OFF → error без генерации.
- **D4/T-3570/T-3575 (SC-A3-08)**: `TestRealErrorPropagation` — реальный `reason`
  (`timeout`/`network`) доводится, сообщение равно `IMAGE_GENERATION_FALLBACK_PHRASE`,
  **не содержит «модель отказалась»**; ошибка входит в цикл как `role:"tool"`
  JSON; envelope reuse (`ctx.tool_results` — тот же A2-контракт, `metered=True`,
  `error_code=reason`).
- **D4/T-3567 (SC-A3-06/-13)**: `TestToolDescriptionU21` — канон 11 (
  имена/порядок/`required`/`factcheck` неизменны); структурная идентичность
  всех вариантов схемы; V21 покрывает 6 пунктов §21; LEGACY байт-в-байт
  baseline-текст; default → V21; kill-switch OFF (subprocess env) → LEGACY;
  `active_tools`-гейт прежний.
- **D10/T-3576 (SC-A3-11/-12)**: `TestR17Logs` — в логах отказа только коды
  (`reason=…`), ни промпт, ни `http`, ни `Bearer`.
- **G/D6/D7/D8 (SC-A3-10…14)**: `TestBoundsA3` — §104 AST-байт-эквивалентность
  генератора vs `e8646af` (не переписывали); литерал fallback-фразы; banned-пути
  вне diff; нет DDL; киль-свитч env-only (не в каталоге/не поле);
  counts каталога неизменны; APP_VERSION==2.58.30; без новых LLM-вызовов.
- Регрексировано 4 bound-гейта прошлых волн (исключение image_generation.py с
  NOTE-санкцией) — смысл ‑ запретов сохранён; сам защитный §104-гейт перенесён
  в AST-тест A3 (жёстче: до уровня AST, не только список путей).

## 4. Rollback-эквивалентность (D8, OFF → байт-в-байт) — сделано

- **Hot:** env `UNIFIED_IMAGE_REQUEST_ENABLED=false` → (i) прямая ключевая фраза —
  тот же legacy-вызов `generate_and_send(extract_prompt(query), …)` байт-в-байт
  (`test_direct_on_same_prompt_as_legacy` + `test_direct_off_no_image_request`);
  (ii) tool-путь — прежний прямой вызов без ImageRequest (`test_tool_off_direct_call`);
  (iii) маркер прогона не проверяется (`test_marker_off_legacy`); (iv) описание
  инструмента — байт-в-байт baseline-текст (`test_kill_switch_off_restores_legacy_via_env`,
  `test_legacy_text_is_baseline`).
- **Cold:** `git revert` к `e8646af` (пер-фича тег НЕ создавался — `EPIC_ONLY`); A3
  трогает ровно 5 product-файлов + tests; все изменения — аддитивные ветки по киль-свитчу.

## 5. Adversarial-приёмка (R3, D9) — покрыто тест-матрицей

| Угроза | Тест-контроль |
|---|---|
| Вторая генерация (двойной триггер) | `test_loop_double_trigger_is_one_generation`, `test_skipped_without_regeneration` |
| Tool при пре-гейте (маркер) | `test_skipped_without_regeneration`, `test_marker_off_legacy` |
| Реальная ошибка генератора → вымышленный отказ | `test_generator_reason_is_surfaced` (реальный reason, нейтральный текст) |
| Пустой/битый prompt | `test_missing_prompt_fail_closed` |
| Модуль OFF | `test_module_off_error_and_no_generation`, `test_direct_off_no_image_request`, OFF-варианты в `TestToolDescriptionU21` |
| Память ради факта (политика контекста) | `TestUnifiedContract::test_build_image_request_defaults`, `test_build_final_prompt_reuses_extract_prompt` |
| Утечkи R17 (промпт/ключ/URL) | `TestR17Logs` |
| §104 drift | `TestBoundsA3::test_104_* AST/литерал`; 4 NOTE-гейта |
| DDL/каталог/версия drift | `test_no_ddl_in_touched_sources`, `test_kill_switch_env_only_not_in_catalog`, `test_catalog_counts_unchanged` |
| 3-й LLM-вызов | `test_two_llm_calls_static` (статическая проверка) + полная suite (coordinator `await_count==2` тесты живы) |

## 6. Что **не** проверено отсюда (честно)

- **Живая прод-проба HY-01/HY-04/HY-05** (tool-совместимость прод-модели,
  plain-fallback-логи, A/B call-rate) — требует прод-хоста/PG; передана
  владельцу/оператору (команды/критерии — `image-diagnostics.md` §1).
- **Per-chat состояние `flags.image_generation_module_enabled`** — требует PG.
- Деплой не выполнялся (EPIC_ONLY, `DEFERRED_TO_EPIC`) — и не должен.
- `deploy`-факт-пункт README/bump — на границе эпика (T-3584), вне A3.

## 7. AMEND-черновик для ADR-1026-16 (вносит @Architect при T-3580/T-3582; ADR Builder-ом не исправлялся)

> **AMEND (D1/T-3558, блок B — вердикт HY-01…HY-06):** завершён протокол D1.
> Вердикты: HY-06 — механика подтверждена (узкий scope пре-гейта, код-факт); HY-03
> — env-слой опровергнут (все рубильники ON), per-chat — неизвестен (PG недоступен
> из окружения); HY-01/HY-02/HY-04/HY-05 — **не подтверждены и не опровергнуты**
> (живая прод-проба/прод-логи недоступны из билд-окружения; попытка пробы выявила
> недоступность `deepseek-v4-flash` на env-эндпоинте `apinet.cloud` — и с tools и
> БЕЗ, что НЕ доказывает отказ прод-провайдера). Следствие по D1: внешний отказ
> не доказан ⇒ блоки C/D/E выполнены как требование ТЗ (унификация — «всегда»)
> и страховочный минимум (D3-маркер, §21-обязательства, D4-текст), без «фикса на
> гипотезе». Живые пробы перенесены владельцу: (1) `chat/completions` c активным
> прод-набором tools; (2) grep `\[image\] generation failed`/`provider rejected tools`
> по journald; (3) чтение per-chat флага; (4) A/B-описание. KG
> `Risk-a3-unproven-root-cause` — письменно закрыт: реальная причина не доказана,
> доказательно обоснованные предположения не строятся (фикс не опирается на причину). Внешняя
> причина, если докажется на проде ⇒ ограничение по D1 (наблюдаемость/маршрутизация,
> `ARCHITECT_DECISION_REQUIRED` владельцу — при смене модели/провайдера).
>
> Контракты §18/§20 — не переписывались.

## 8. Готовность к приёмке

Feature A3 **завершена в реализации** (блоки B/C/D/E/F/G — задачи T-3555…T-3579
выполнены; задачи блоков в `tasks.md` отмечает @PM/сверка — Builder не редактирует
`tasks.md`). Полная suite 9156/0 + JS 47/47 + diff-аудит. Готово к независимому
Reviewer gate: **линза 1** (T-3580) + **линза 2** (T-3581). Awaiting Reviewer.
