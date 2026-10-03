# ASAP 4.2 — reuse-inventory.md (Step 1 @PM, 04.10.2026)

Цель ASAP 4.2 — **хирургический corrective pass**, не новый контур. Ниже — что уже доставлено ASAP 4.1 и в дереве (проверено `Glob`/`rg`/чтением 04.10.2026, прод 2.58.47, SQLite v24) и что именно правим точечно. Не строим второй Summary-контур.

## 1. Компоненты после ASAP 4.1 — REUSE как есть

| Компонент | Файл / носитель | Роль в 4.2 |
|---|---|---|
| `SummarySourceWindow` (immutable snapshot) | `services/summary_source_window.py`; SQLite `summary_source_windows` (v24, write-once) | **Не трогать.** Anchors §2 цепляются к этому окну; SourceAnchorMap строится поверх него |
| Semantic map v1 | `services/summary_l1_semantic_map.py` | REUSE валидатор/compaction/merge/minimal_map; расширяем на anchor-repair |
| Durable SummaryRun + stages | `services/summary_run_store.py`; `summary_runs`/`summary_run_stages` | REUSE для state/lifecycle/Inspector-полей |
| Coverage ledger | `services/summary_coverage_ledger.py` | REUSE (overflow-ветка) |
| L1 capacity / clusterizer | `services/summary_l1_capacity.py`, `services/summary_l1_clusterizer.py` | REUSE capacity-математику; правим correction-retry policy и repair-вход |
| Legacy full-window | `services/summary_legacy_fullwindow.py` | REUSE (fallback-путь; не основной) |
| L2 writer / review | `services/summary_l2_writer.py`, `services/summary_l2_review.py` | REUSE bounded revision/patch-контракт; правим evidence-repair и verdict |
| FactPackage/derived view | `services/summary_fact_package.py`, `services/summary_fact_view.py` | REUSE как derived view; правим prompt-формулировки (audit) |
| LLM Supervisor | `services/summary_llm_supervisor.py` | REUSE attempt-ceiling ≤4 HTTP/watchdog/telemetry; добавляем real streaming liveness + Inspector `network_attempts` |
| Media policy / window estimator | `services/media_execution.py` (MediaExecutionPolicy, submit_edit, ImageProviderAdapter) | REUSE паттерны; правим edit-route на реальный provider contract |
| Seeds | `services/cover_style_registry.py` (`SEED_FILES`), `extra_images/{medved_press.png,style_example_01.png,style_example_02.jpg}` | REUSE seed-механику; правим только конкретный defect, если найдётся |
| Cover style pipeline | `services/cover_style_edit.py`, `cover_style_pipeline.py`, `image_capabilities.py`, `image_prompt_compiler.py`, `image_generation.py` | REUSE P0/P1/P2-компилятор и capability-gate; доводим prompt_limit до реального runtime |
| MiniApp | `web/index.html`, `web/app.js`, `web/static/app.css` | Правим `.more-sheet`, Quick Access, style cards/editor, naming |
| Inspector/events | `services/pipeline_events.py`, `pipeline_analytics.py` | REUSE; аддитивные поля root-cause visibility |

## 2. Что правим хирургически (root cause → файл)

| # | Root cause | Точка правки (факт) | Характер |
|---|---|---|---|
| 1 | L1 fail-closed на `unknown_message_id` / raw ID contract | `services/summary_l1_contract.py` (`invalid_result`, `validate_l1_response`), `services/summary_l1_semantic_map.py`, `summary_l1_clusterizer.py:2010` (L1_CORRECTION_RETRY) | Новый модуль anchors + repair-flow вместо fail-closed |
| 2 | `unassigned_message_ids` приходит от LLM | `services/summary_fact_package.py` (`unassigned_message_ids`), L1 map | Пересчёт кодом; поле optional |
| 3 | L2 `invalid_evidence` → `document=None` | `services/summary_l2_writer.py:134` (`REASON_INVALID_EVIDENCE`), `_make_result` | Repair вместо kill |
| 4 | Reviewer/revision | `services/summary_l2_review.py`, `summary_l2_writer.py` (`build_review_content`, `build_revision_content`) | Структурированный verdict + full source |
| 5 | Противоречащие prompts | `services/summary_prompts.py`, `plans/docs/canon/architecture.md` | Audit + миграция канона |
| 6 | Capacity resolver зажат stale registry | `services/model_capacity.py` (`_resolve_uncached`:777, `_cache_key`:679, `_capability_fingerprint`:641, `decide_summary_mode`:935), `output_reserve_tokens`:256 | Live metadata precedence + capability-aware reserve |
| 7 | Streaming liveness почти не используется | `services/summary_llm_supervisor.py` (`select_execution_mode`:134; `SUMMARY_LLM_STREAMING_MODE_ENABLED`/`_ASYNC_MODE_ENABLED` default OFF) | Реальная проверка stream=true на поддерживающем route |
| 8 | NanoGPT invented contract | `services/cover_style_edit.py` (`EDIT_ROUTE="/images"`:38, `build_edit_payload` `input_references`:155), `services/media_execution.py` (`submit_edit`:374) | Реальный provider-specific contract/adapter |
| 9 | prompt_limit не заполняется runtime | `services/image_capabilities.py` (`PromptLimit`, precedence §16), `services/image_prompt_compiler.py` (`compile_prompt` unknown-ветка:157) | Довести discovery/400-extract/cache до рабочего runtime; без hardcode 800 |
| 10 | MiniApp (`.more-sheet`, Quick Access, cards, editor, naming) | `web/index.html:2373,5477`; `web/static/app.css:2333-2356`; `web/app.js:1545,5828` | Root-cause fix + UX, не pixel nudges |

## 3. Не трогать (25383–25393)

SourceWindow renderer, RichMessage renderer, Base Cover generation, unrelated GraphRAG, MCA features, message history, unrelated modules. Kill-switches/DDL ASAP 4.1 (v24 аддитивна) сохраняются; новые механизмы — env-only с OFF=бит-в-бит, если Architect не решит иначе.
