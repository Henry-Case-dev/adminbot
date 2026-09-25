# A6 `memory-lookup-api-round1026` — Evidence (Builder, T-3611..T-3621)

- **Epic-ID:** Эпик 3 «Agentic Intelligence», Wave 4 — A6
- **Risk:** R2 (ADR-1026-18 D11)
- **Baseline anchor:** `e8646af` (HEAD) + UNCOMMITTED epic-release tree A2/A3/A5 (not touched/reverted/committed)
- **Feature dir:** `plans/features/memory-lookup-api-round1026/`
- **Release policy:** EPIC_ONLY — deploy DEFERRED to epic; no commit/tag/bump by Builder
- **Spec:** `spec.md` (REQ-A6-01..18 → SC-A6-01..22); **ADR:** `adr-1026-18-memory-lookup-and-canon-extension.md` (D1..D11, binding)

## Changed files (A6 contribution only)

Source:
- `config/settings.py:903-904` — `MEMORY_LOOKUP_ENABLED: ClassVar[bool] = _env_bool(..., True)` (env-only, Δ каталога=0).
- `services/tool_schemas.py:436-487` — `TOOL_GET_USER_CONTEXT` JSON schema (person required string, user_id optional int, purpose enum 6, max_items int≥1; `additionalProperties:false`; EN-description: memory ≠ factcheck, no-unconfirmed-as-fact).
- `services/tool_schemas.py:489-502` — `TOOL_CALLING_TOOLS` 11→12 (`get_user_context` в хвост; первые 11 — байт-в-байт).
- `services/tool_schemas.py:513` — `MEMORY_LOOKUP_TOOL_NAME`.
- `services/tool_schemas.py:534-541` — `_memory_lookup_enabled()`; `active_tools()` branch (`:551-563`) → OFF скрывает инструмент.
- `services/tool_router.py:547` — registry `"get_user_context": self._get_user_context`.
- `services/tool_router.py:1154-...` — `_get_user_context` + purpose-routing/lazy-RAG/caps/envelope/honesty/R17 helpers (constants at `:123-160`).
- `services/database.py:4653-4675` — `get_user_context_facts` (read-only: confirmed facts + provenance metadata; no DDL, SQLite v12).

Tests:
- `tests/test_memory_lookup_round1026.py` (new, **43 passed**).
- Canon re-pins (len==12 / active list + tail): `tests/test_tool_schemas.py`, `tests/test_agentic_ai_round1020.py`, `tests/test_image_generation_round1023.py`, `tests/test_media_transcribe_tool_round1024.py`, `tests/test_native_media_tools_round1024.py`, `tests/test_recent_history_tool_round1015.py`, `tests/test_tool_coordinator_round1026.py`, `tests/test_tool_chains_round1026.py`, `tests/test_tool_download_quality_round1017.py`, `tests/test_tool_calling_round1015.py`, `tests/test_unified_image_request_round1026.py`.

## T-3611..T-3621 — status

- [x] **T-3611 schema/регистрация** — атомарно: схема + хвост канона + `active_tools` + env-гейт + `MEMORY_LOOKUP_TOOL_NAME`. First 11 byte-identical.
- [x] **T-3612 диспетчер + R17-лог** — registry entry + `_get_user_context` (read-only). R17 log `[memory] lookup | purpose=… | user_id=… | chat_id=… | count=… | latency_ms=… | empty_reason=…`; structured `invalid_arguments`; envelope через A2 `result_for`.
- [x] **T-3613 purpose routing** — dict-таблица 6 purposes; unknown → `invalid_purpose`; выборочная выдача без dump.
- [x] **T-3614 резолв субъекта** — reuse AliasResolver (`deps.aliases` либо `build_alias_resolver`); `ambiguous` → id-кандидаты, факты не сливаются.
- [x] **T-3615 досье-выдача** — reuse `db.get_user_context_facts` / `db.get_persona_card` / `db.get_generated_dossier` / `format_dossier_block`; no new DB, Δ DDL=0.
- [x] **T-3616 lazy RAG + капы** — `search_long_term`/`get_rag_facts`/`get_rag_context` только {general, speech_style}; для speech_style RAG — если срез < минимума; caps.
- [x] **T-3617 5 полей** — facts/sources/confidence/time_context/no_data(+empty_reason/truncated).
- [x] **T-3618 честность** — `unknown` без носителя; `confirmed` только при `status='confirmed'` и weight≥0.5; срез ≤240 симв.; результат ≤4000.
- [x] **T-3619 adversarial-тесты** — 43 сценария (см. ниже).
- [x] **T-3620 регресс** — pytest **9213/0**, JS **47/47**, catalog без изменений, diff-check 0.
- [x] **T-3621 boundary audit** — см. раздел ниже.

## Verification commands + actual results (T-3620)

- `pytest -q` (full `.venv`) → **9213 passed / 0 failed** (153s). Baseline Step 0/A5 = **9170/0**; **+43** = `tests/test_memory_lookup_round1026.py` (43). No regressions in first-11 tools.
- `tests/test_memory_lookup_round1026.py` → **43 passed** (2.66s).
- Canon re-pin set + new file → 444 passed.
- JS: `node tests/js/*.js` (47 files, node v24.16.0) → **47/47, 0 failures**.
- Catalog: `REGISTRY 470 · Settings 427 · categorized 445 · GROUPS 101 · _TAB_BY_GROUP 99 · TAB_RULES 21` = **470/427/445/101/99/21** ✓ (unchanged).
- SQLite: `tests/test_database.py` in suite (asserts `user_version` = **12**); `Δ DDL = 0` ✓.
- `git diff --check` → exit **0** (only LF→CRLF informational warnings).
- `APP_VERSION` → **2.58.30** (config/settings.py:1886, unchanged; no bump).

## T-3621 — boundary audit (verified)

- **Δ DDL = 0 / нет новой БД памяти:** reader `database.get_user_context_facts` — только `SELECT` по существующему `graph_facts`; no `CREATE/ALTER TABLE/INDEX` in A6 sources; no new `*.sql` files (`Get-ChildItem -Recurse -Include *.sql` → none).
- **Δ каталога = 0:** `MEMORY_LOOKUP_ENABLED` отсутствует в `param_catalog.REGISTRY` и в `dataclasses.fields(Settings)` (tests assert); counts unchanged.
- **A5 (`worker_budget`/`image_*`/`limits.*`) не тронуты:** `rg MEMORY_LOOKUP|get_user_context|memory_lookup|_APPEARANCE_LEXICON` по `services/worker_budget.py`, `services/image_generation.py`, `services/pg_db.py`, `services/direct_chat_service.py`, `services/smartmodule_urls.py`, `services/param_catalog.py`, `web/app.js`, `web/index.html` → **0 совпадений**. (Эти файлы dirty в baseline из-за A2/A3/A5 — не наш diff.)
- **A4 (§22–§25) не реализован:** appearance = generic-лексиконный фильтр существующих `graph_facts` + honest `no_data`; извлечение/классификация внешности и image-prompt — A4.
- **A7 (§36–§37) не тронут:** `factcheck_tools()` = **3** (`dig_into_lore`/`compile_lore_story`/`execute_web_search`); `get_user_context` в фактчек-набор не входит; память ≠ фактчек в `description`.
- **§104 `generate_image`:** AST-identity gate A3 (`test_unified_image_request_round1026.py`) прошёл в полном прогоне; `_generate_image` не изменялся.
- **Второй резолвер/RAG/аналитика/3-й LLM:** нет — reuse `deps.aliases`/`deps.memory`/`deps.db`; 0 новых LLM-вызовов, `tool_loop` не менялся.
- **Промпты:** системные/воркерные промпты не в diff (ADR-1013-3 NOT_APPLICABLE); единственное промпт-соседнее изменение — `description` новой схемы в `tool_schemas.py` (санкционировано ADR-1026-18 D1).
- **Системная личность бота:** не менялась; speech_style возвращает compact-профиль (стилизация — caller'а).
- **Незатронутые чужие артефакты:** `plans/current_task.md`, машинный блок `workflow_state.md`, spec/ADR/backlog/metrics/ARCHITECTURE/MEMORY — не редактировались A6.

## New test scenarios (`tests/test_memory_lookup_round1026.py`, 43)

- **Контракт/канон:** schema shape; description EN + memory≠factcheck + no_data; canon 12 tail-only; first 11 byte-identical; `active_tools()` default (image OFF) = 11; `MEMORY_LOOKUP_ENABLED=OFF` → инструмент скрыт, baseline-набор 10 имён; `factcheck_tools`=3; kill-switch не в каталоге.
- **Невалидные аргументы (§52 п.14):** missing person+user_id; invalid purpose; non-string person; bad max_items (0/-3/"x"/True); non-int user_id; invalid-args не роняет цепочку (второй инструмент жив).
- **Purpose-роутинг:** identity (alias+persona facts+dossier); appearance (лексиконный фильтр; no-match → `no_storage_for_purpose`); biography (+ dossier_portrait, confidence unknown); relationships (links → edge); general (RAG facts + messages); speech_style (bounded slice + patterns).
- **Lazy RAG:** off для identity/appearance/biography/relationships (spy `memory.calls == []`); on для general; on для speech_style при тонком срезе.
- **Капы:** max_items hard-ceiling 20; message slice ≤5; фрагмент ≤240; результат ≤4000 + `truncated`.
- **Честность:** 5 полей всегда; unknown без носителя; weight<0.5 → `likely`; unknown_person honest; ambiguous без слияния и без имени; dump — чтение строго по одному canon-имени (1 вызов).
- **Kill-switch:** прямой вызов OFF → `{"status":"error","error":"disabled"}`.
- **R17:** лог только разрешённые поля; секрет-факт и имя человека не в логах; текст сообщения general не логируется.
- **§35-комбинирование:** envelope попадает в `ctx.result_for("get_user_context")`, `metered=False` (free/local); фактчек не расширен.

## 14 acceptance invariants — status

1. Новая БД памяти не создаётся (Δ DDL=0, SQLite v12): **OK** — read-only SELECT; `tests/test_database.py` (v12) + boundary.
2. Ни одного universal dump: **OK** — выдача по одному человеку/purpose; `test_no_universal_dump_only_asked_person`.
3. Lazy RAG (только {general, speech_style}): **OK** — `TestLazyRag` (spy).
4. Envelope 5 полей: **OK** — `test_five_fields_always_present`.
5. Неподтверждённое ≠ факт: **OK** — `test_unknown_never_confirmed_without_carrier`, `test_low_weight_is_likely_not_confirmed`.
6. Капы без «сотен сообщений»: **OK** — `TestCaps`.
7. Без больших цитат: **OK** — slice ≤240 + budget ≤4000; `test_slice_chars_capped`, `test_result_budget_4000_with_truncated_flag`.
8. Системная личность не меняется: **OK** — speech_style = compact-профиль, стилизация у caller; A6 не трогает промпты/персону.
9. Память ≠ фактчек: **OK** — `factcheck_tools`=3; `test_memory_tool_absent_from_factcheck`; description.
10. R17/R18-гигиена логов: **OK** — `TestR17Log`.
11. Канон 11→12 атомарно, с санкцией ADR-1026-18: **OK** — схема+хвост+диспетчер+active_tools+тесты len==12+env-гейт одним изменением; first 11 byte-identical.
12. Δ каталога = 0: **OK** — counts unchanged; kill-switch вне каталога.
13. Границы волн A4/A5/A7/§104: **OK** — boundary audit (0 A6-маркеров в чужих путях; §104 AST-gate зелёный).
14. Deploy = DEFERRED_TO_EPIC: **OK** — нет коммита/тега/bump; APP_VERSION 2.58.30; hot-откат `MEMORY_LOOKUP_ENABLED=OFF`; cold `git revert` e8646af; DDL-откат не нужен.

## R17 / R18

- **R17:** логи `_get_user_context` содержат только `purpose/user_id/chat_id/count/latency_ms/empty_reason`; никогда — тексты досье/сообщений/цитаты/имена/промпты/сырые аргументы. Envelope `data` — in-memory (A2 `tool_results`, не логируется/не персистится).
- **R18:** коммитов/тегов/branches не создавалось; `plans/current_task.md` и машинный блок не изменялись; бэкапы/`stash` целы.

## Epic inputs contributed by this feature (release-candidate)

- Code: `config/settings.py` (env-only `MEMORY_LOOKUP_ENABLED`), `services/tool_schemas.py` (канон 12 + gate), `services/tool_router.py` (`get_user_context` lookup), `services/database.py` (read-only facts+provenance reader).
- Tests: `tests/test_memory_lookup_round1026.py` (new) + contract re-pins в 11 suites.
- Deploy: **DEFERRED_TO_EPIC** (EPIC_ONLY) — no per-feature deploy/tag/bump.

## Blockers

None. All 11 tasks implemented and verified; new file 43/43; full suite 9213/0; ready for independent Reviewer (T-3622).
