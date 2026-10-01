# `mca-22-attribution-memory-coherence` — Builder evidence

> Статус: Build Step 3 выполнен в объёме §16 tasks.md (15 задач [x], ~20 partial, гейты следующих стадий открыты). Без коммитов (R18). Секретов нет (R17).
> Авторитетные SHA при старте: spec `C4B4043E…2ABA5B192E` ✅, ADR-1028-6 `6C8E82E5…276EF3` ✅, tasks `69C90CD8…3FBE4` ✅.
>
> **Fix round-1 (по review.md, 02.10.2026):** см. §5 ниже — M-1…M-4 исправлены; полный сьют **10520 passed / 2 failed** (оба pre-existing bound-фейла round1026, воспроизведены ревью на чистом HEAD); JS-харнесс 36/36 pytest-обёрток (52/52 JS-скрипта `tests/js/*_test.js` исполняются зелёными в составе сьюта); F8 `--check` EXIT=0; **WTH пересчитан по манифесту §5 (33 файла; формат/конвенция — review.md Binding), финальное значение — в хэндоффе Builder @Orchestrator** (числовой пин сознательно не вписан в файл — манифест включает сам evidence.md/tasks.md). Коммитов нет.

## 0. Baseline (T-4273)

- git HEAD: `7a86179` (docs-only; прод-HEAD `9906c9d`), worktree-чужой WIP не тронут (`plans/backlog.md`, `plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/reports/full_audit_results.md`, `plans/workflow_state.md`, `node_modules/`, `package*.json`, `.playwright-mcp/`, `extra_images/`).
- `APP_VERSION = "2.58.43"` — `config/settings.py` (анкер подтверждён).
- DDL хвост **v21** (`_SCHEMA_VERSION_EPISODES_STORIES = 21`, step `episodes_stories`) — подтверждён; свободна v22 (занята этой фичей санкционированно).

### Карта read-path 12 потребителей (перезамер 02.10.2026)

| # | Consumer | Read-path до | После MCA-22 |
|---|---|---|---|
| 1 | Direct Chat | thread_chain + composer + bot_replies/parents | + ledger-восстановление хода бота; bundle v2 роли; update-dedup; guard |
| 2 | thread chain | `get_smart_message_by_tg_id` (полный ряд) + bot_reply_parents | + ledger-fallback старше TTL (gate) |
| 3 | context composer | канон-рендер из узких рядов | без изменений (перевод — следующий инкремент) |
| 4 | retrieval | `search_messages_fts`/facts/vector | + provenance-колонки в `search_graph_facts_fts`, RetrievalCandidate metadata, identity-prior |
| 5 | GraphRAG extraction | `get_smart_window` | без изменений (след. инкремент) |
| 6 | dossier/live lore | `get_smart_window` | без изменений |
| 7 | dossier rebuild | chunk + SourceRef | без изменений |
| 8 | episodes/history | фасад mca-05 | без изменений |
| 9 | Summary-derived extraction | window/raw; memorize_facts | без изменений (validator доступен) |
| 10 | factcheck context | `get_recent_messages`/`get_messages_around` | без изменений |
| 11 | history-reading tools | FTS/retrieval | наследует metadata кандидатов |
| 12 | Analytics source cards | `web/api/memory_agi.py` | + `/memory/attribution/trace` + `/memory/attribution/metrics` |

## 1. Изменённые файлы

**Новые (product):** `services/canonical_messages.py` (C1 DTO+projection+render), `services/bot_output_ledger.py` (C2), `services/quote_resolver.py` (C3, лестница 1–7), `services/claim_envelope.py` (C4: speech acts/negation/speaker≠subject/coreference/producer-validator), `services/graphrag_provenance.py` (C5/C8: person-edge validator, legacy-классификация, correction plan, read policy), `services/response_freshness.py` (C7: update-dedup, duplicate guard, lineage).
**Новые (тесты):** `tests/test_mca22_core_round1027.py` (54), `tests/test_mca22_truthset_round1027.py` (17).
**Изменённые (product):** `config/settings.py` (+4 env-рубильника, spec §4.2), `services/mca_gates.py` (KILL_SWITCHES +4, аксессоры, инертности), `services/mca_events.py` (reason_code +12), `services/database.py` (v22 `_migrate_bot_outputs_v22` + ledger-методы `record_bot_output/get_bot_output_by_tg/find_bot_outputs_by_hash/list_recent_bot_outputs/resolve_source_ref_ids`; `search_graph_facts_fts` SELECT +5 provenance-колонок — аддитивно), `handlers/summary.py` (ingestion-фикс `quote_author_id` из `reply_to_message.from_user` при наличии `message.quote` — C1/Q3a), `services/direct_chat_service.py` (update-dedup, duplicate guard bounded-1, ledger-запись после send, correction path, bundle v2 поля, DIRECT_* события), `services/mca_retrieval_context.py` (RetrievalCandidate +8 полей, RetrievalRequest +4, `apply_identity_prior`, заполнение кандидатов), `services/summary_memory.py` (producer-validator «запомни»), `services/thread_chain.py` (ledger-walk старше TTL), `web/api/memory_agi.py` (+2 эндпоинта attribution trace/metrics).
**Изменённые (тесты-соседи, по конвенции волн):** `tests/test_direct_chat.py` (import mca_gates; 2 legacy-теста скоупнуты guard-off — намерение сохранено), `tests/test_mca01_tx_task_supervisor_round1027.py` (allowlist database.py 141→144: +3 commit v22), `tests/test_mca05_episodes_stories_round1027.py` (mark хвоста реестра v21→v22, v21-чеки без изменений), `tests/test_tool_coordinator_round1026.py` + `tests/test_unified_image_request_round1026.py` (NOTE+allow `web/api/memory_agi.py`).

## 2. Тесты и результаты

- `pytest tests/test_mca22_core_round1027.py tests/test_mca22_truthset_round1027.py` → **71 passed**.
- Полный сьют: `pytest tests --timeout=120 -q --tb=no` → **10508 passed, 2 failed** — оба pre-existing (bound-тесты web/-дрейф прежних волн, воспроизведены на чистом HEAD `7a86179` во временном worktree; НЕ являются регрессией MCA-22).
- Целевая регрессия до правок соседей: 365 passed (baseline-эквивалент) после фиксов.
- Ключевые acceptance-покрытия: truth-set A–O 15/15 (A/B/F/G/H/J/E/I/L/C/D/K/M/N/O); OFF-паритет всех 4 рубильников; v22 идемпотентность/индексы; ledger append-only/self-referential; лестница 1–7; exemption'ы guard'а; отсутствиe paraphrase-процессора; single-writer allowlist; каталог Δ=0.

## 3. Открытые/невыполненные проверки (честно)

- **Не реализовано:** T-4310 (previous answer в контексте второго generation), T-4300 (tool-loop сохранение ролей), `DIRECT_INTERMEDIATE_CACHE_HIT` (событие объявлено в словаре, emission-точка не подключена), переключение consumers 3/5/6/7/8/9/10 на projection, полный structure-first рефакторинг `_build_user_content` (branch/evidence ref-ID всё ещё из отрендеренных блоков), LLM-resolver ступеней 3–4/6 (bounded детерминированный вместо), web/app.js-виджеты Attribution Trace, dossier live/rebuild единый валидатор, T-4316 rebuild-регрессы, скриншотный self-quote E2E (Browser-Verification: REQUIRED — не выполнялась, Playwright-стенд не поднимался в этом шаге).
- **Аудит cache-веток (T-4308, частично):** единственный literal-replay источник — legacy `direct_dedup` (direct_chat_service ~:1598), активен только при `MCA_CONTEXT_ANSWER_CACHE_ENABLED=OFF`; autonomous/tool-loop/fallback-recompose/provider-retry собственных answer-кешей не имеют (подтверждено сканом); update-дедуп закрыт MCA-22; prod-env переопределения из репо неверифицируемы → T-4319.
- **Prod-гейты:** T-4319/T-4320/T-4321/T-4322 — вне Step 3 (прод не пишется; merge @Architect).
- Browser-Verification spec (scoped): не выполнена — Analytics-виджеты фронтенда не расширялись (только API); справка не менялась.

## 4. Continuity note

Свежая сессия Builder; наследования частичного состояния не было. Baseline-подтверждение: `git worktree add` на HEAD `7a86179` (clean) использовался для верификации pre-existing фейлов и удалён после. Коммитов нет; PRODUCT-дифф = перечисленное в §1.

## 5. Fix round-1 (M-1…M-4 по review.md @Reviewer, 02.10.2026)

**Роль:** свежая сессия Builder (fix-раунд поверх частичного состояния Build; чужой/служебный WIP вне скоупа фичи не тронут). Ревью-пин старого WTH `46621E46…E68310` устарел законно — скоуп расширен 5 файлами фиксов (см. манифест ниже).

### M-1 — update-dedup: TTL 24h wired, развязка с legacy-флагами
- `services/smart_cache.py:41` (`_UPDATE_MARKER_SWEEP_TTL = 24*3600`), `:183–198` (`_sweep_ttl` учитывает 24h БЕЗУСЛОВНО), `:359–367` (новые `get_update_marker`/`set_update_marker` с явным TTL-параметром; без гейта на `CHAT_DEDUP_ENABLED`/`SMART_CACHE_ENABLED` — единственный рубильник фичи `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` остаётся у вызывающего).
- `services/response_freshness.py:90–150` (`check_update_seen`/`mark_update_seen` читают/пишут маркер-методы с TTL `UPDATE_DEDUP_TTL_SECONDS`; docstring `mark_update_seen` честно фиксирует at-most-once трейд-офф маркировки ДО обработки).
- **Побочный прод-дефект, обнаружен и закрыт (wiring):** `services/direct_chat_service.py:1597–1618` — ранний `return` на dedup-hit происходил ПОСЛЕ захвата слота `smartmodule_concurrency` и до `try/finally` → permit утекал; повторная доставка того же update навсегда съедала per-chat слот (чат вставал на lock-wait). Старый TTL 300 с маскировал путь. Фикс: `permit.release()` перед return + регресс-тест `tests/test_direct_chat.py:2970` (`test_update_dedup_hit_releases_concurrency_slot`, lock-wait ужат до 2 c — до фикса тест вис/фейлил).
- Тесты: `tests/test_mca22_core_round1027.py:704–745` (+4: TTL==86400 wired; drift-guard `smart_cache._UPDATE_MARKER_SWEEP_TTL == fresh.UPDATE_DEDUP_TTL_SECONDS`; маркер жив >300 c и истекает >24 h на TTL-честном fake; `CHAT_DEDUP_ENABLED=OFF ∧ SMART_CACHE_ENABLED=OFF` не убивают update-dedup на реальном SmartCache). `_FakeCache` переписан на TTL-семантику маркеров (`:635–663`).

### M-2 — quote_resolver врезан в прод-путь
- `services/direct_chat_service.py:3875–3918` (`_rowval` + `_resolve_quote_live`: ручные `>`-цитаты из query + metadata-ряд MCA-03 → `_qres.resolve_quote`; fail-open, gate-aware), вызов из v2-ветки `_build_evidence_bundle` `:3780–3803` (metadata-first §29: ladder только при NULL `quote_author_id`), результат → `quoted_speaker`/`ambiguities` bundle v2 `:3835–3852` (ledger-реф `bot_output:<id>` → evidence-item label='quote').
- `services/quote_resolver.py:110–149,265–272` — новый параметр `exclude_tg_message_id`: триггер исключается из кандидатов ступени 6 (иначе `>`-цитата в самом триггере всегда давала «второго автора» → вырожденный ambiguous; self-restatement по ЧУЖИМ старым сообщениям остаётся ambiguous).
- Тесты: `tests/test_mca22_truthset_round1027.py:334–417` (+3: живой резолв ручной цитаты через прод-bundle → `quoted_speaker="2"`; spy: resolver вызван, ledger-реф попадает в evidence; ambiguous → автор не выдумывается, маркировка в `ambiguities`).

### M-3 — memory_agi.py CRLF→LF
- `web/api/memory_agi.py`: 1149 CRLF-строк → 0; реальные изменения сохранены. `git diff --numstat` = **168+/1−** (было 1149+/982−). Файл в `git diff --check` чист.

### M-4 — ledger: все типы ответов
- `services/bot_output_ledger.py:33–49,80–105` — default-db binding (`bind_default_db`/`_resolve_db`; `db=None` → binding; нет binding → честный skip).
- direct: `services/direct_chat_service.py:773–778` (`direct_output_kind`: `free_will` → `autonomous_reply`), вызов `:2447–2459`.
- summary: `services/summary_generator.py:1125–1167` (`_record_published_output` + `_document_plain_text`), 4 точки записи после успешной send: rich-статья `:1539`, rich без обложки `:1739`, plain-чанки `:1241` и plain-fallback `:1281` (kind `rich_message`, correlation_id рана, searchable plain-текст).
- подписи: `handlers/video_download.py:615,750–770,799` (fast-track + `_send_file`, kind `media_caption`), `services/goodmorning_relay.py:131–170` (photo/video/animation), `services/dead_page_relay.py:699–717` (fallback-фото, db явно).
- binding: `handlers/summary.py:110–127` (`setup_summary` привязывает db; bot.py не тронут).
- Тесты: `tests/test_mca22_truthset_round1027.py:419–511` (+4: rich/autonomous/media_caption пишутся с честными kind/хешем; `direct_output_kind` маппинг; fail-open без binding; `_publish_plain_document` пишет доставленную статью через default-binding). Truth-set H остался фикстурным (read-side контракт) — теперь прод-wiring закрыт записью.

### Гигиена фиксов
- Line endings восстановлены к HEAD-стилю после правок: `smart_cache.py`/`video_download.py`/`dead_page_relay.py` (LF, дифф снова компактный: 40+/3−, 48+/10−, 15+/0−). `git diff --check` по файлам фикса — EXIT 0. Остаточный `--check`-шум — pre-existing с Build-шага: LF-вставки Build в CRLF-файлах (`config/settings.py` ~27 строк, `test_tool_coordinator_round1026`/`test_unified_image_request_round1026`/`test_mca01…` по 3–6 строк) + чужой WIP `plans/workflow_state.md` — вне скоупа 4 фиксов, не расширял.

### Верификация (фактические прогоны, 02.10.2026)
- Новый/затронутый набор: `test_mca22_core_round1027.py` (58) + `test_mca22_truthset_round1027.py` (24) = **82 passed**; `test_direct_chat.py` **160/160**; соседи: epic33/hot_migration/mca03/goodmorning/summary-acceptance/video_download/dead_page/epic37 — **407 passed** суммарно по точечным прогонам.
- **Полный сьют:** `pytest tests -q --timeout=120 --tb=no` → **10520 passed / 2 failed** (было 10508/2; +12 новых тестов). Оба failed — те же pre-existing bound-тесты round1026 (`test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026::…test_forbidden_paths_out_of_diff_vs_baseline`), не связаны с фикса́ми. Один ложный hang полного прогона (Windows IOCP-флейк aiosqlite, L-7 debt) воспроизведён 1× и не повторился на ретрае с идентичным деревом.
- **JS:** `pytest tests/test_webapp_js_unit.py` → **36/36 passed**; 52/52 скриптов `tests/js/*_test.js` исполняются зелёными в составе полного сьюта (36 — в js_unit-файле, остальные — в webapp-hotfix тест-файлах).
- **F8:** `python tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 488 == REGISTRY…`, EXIT=0.
- **WTH пересчитан** — манифест 33 файлов (20 изменённых product/tests + 8 новых product/tests + 5 артефактов фичи, вкл. review.md), формат `path|size|sha256`, sorted, LF, SHA-256 по конкатенации строк с trailing-LF; финальное значение фиксируется в хэндоффе Builder (не в файле — манифест включает сам evidence/tasks). Δ против review-пина: +5 файлов фиксов (smart_cache, summary_generator, video_download, goodmorning_relay, dead_page_relay) +1 артефакт (review.md).
- `update_reference`: строка БД не менялась; DDL/каталог/reason-коды — Δ=0 против Build-состояния.

### Остатки (честно, поверх §3)
- Edit→revision-строка ledger (правка собственного сообщения бота) — не врезана (вне 4 фиксов; остаётся в §16-хвосте T-4287).
- Overflow-текст dead page (plain-продолжение после подписи) в ledger не пишется — записана только подпись.
- `alan_greeting` (caption = фиксированный ALAN_USERNAME) — не записывается: тег-упоминание, не содержательный вывод; решение за Reviewer.
- Исключения между захватом permit и большим try/finally в `handle()` (кроме dedup-hit) по-прежнему потенциально текут — точечный фикс только на dedup-hit (вне 4 фиксов).
