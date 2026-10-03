# ASAP 4.1 — spec.md (Step 2 @Architect, 03.10.2026)

Дизайн-спецификация фичи `asap-4-1-durable-whole-window-summary` (T-4601). Статус: **Proposed → Accepted** (решения — `adr-1028-8-durable-whole-window-summary.md`; этот документ — контракты для Builder/Reviewer/DevOps).

Источники: ТЗ владельца §0–§52 (`current_task.md:22345–23844`, прочитано полностью, файл не изменяется), PM-пакет (`requirements-map.md` R6-xxx, `reuse-inventory.md`, `conflict-audit.md` AM-1…AM-6, `tasks.md` T-4600+), база ASAP-4 (`plans/archive/asap-4-embedding-graphrag-cover-runtime-round1030/{spec.md, adr-1028-7-…md}`), фактический код прод 2.58.46 (SQLite v23) — якоря ниже проверены по дереву 03.10.2026.

**Границы:** дизайн и контракты, без implementation. Запрещено (§0-директива 22361): превращать 4.1 в бесконечный redesign — аменд/расширение существующего контура Summary, второй контур не строится. **Scope = §0–§52 ТЗ целиком; excluded scope:** Direct/STT/embeddings/image-генерация (кроме §35/§36 style), GraphRAG corrective pass (T-4508–T-4510 — предпосылка старта Builder'а, AM-6), episodes/dossier (чужие task_jobs-потребители).

**Risk-Level: R3.** Основание: перепевязка орchestration production Summary-пайплайна (инцидент §0), новая SQLite DDL (v23→v24), 6+ новых kill-switches, Supervisor меняет тайминги главного пользовательского контура. Что могло бы поднять риск выше шкалы — ничего; понизить до R2 можно было бы только без durable-state/DLL — не наш случай.

**Browser-Verification: REQUIRED.** Основание: зона G меняет user-visible Run Inspector (новые карточки «КОНТЕКСТ МОДЕЛИ», liveness, cover style, раздельная coverage). Верификация: Playwright MCP, desktop 1280×800 + mobile 390×844, entry point `/api/analytics/pipeline/inspector` + run detail (существующий Inspector R4-E), fixture-run через реальный mca-17a-транспорт на temp-SQLite (прецедент ADR-1028-7 §61.16 A–D, прод-БД не загрязняется). Консоль/сеть: 0 новых JS-ошибок на проверяемых сценариях. Пиксель-точность не требуется — проверяются наличие карточек, значения из structured state и человеческая читаемость.

---

## 0. Общие принципы (обязательные для всех зон)

### 0.1 DDL-дисциплина

| Сторона | Правило |
|---|---|
| SQLite | Только **additive** MigrationStep: `user_version 23 → 24` (прод факт. 23 — ADR-1028-7; corrective pass DDL не добавлял). Новые таблицы `CREATE TABLE IF NOT EXISTS`; новые колонки — `ALTER TABLE … ADD COLUMN` NULL/DEFAULT; ни одного UPDATE/DELETE существующих строк при миграции. Полный список — §10 |
| PostgreSQL | **no-op обязателен** (Summary живёт в SQLite + runtime; cover_style_* PG-таблицы не изменяются). Невозможность — только через ADR-waiver, не молча |

### 0.2 Kill-switches

Все новые ветки — env-only, default **ON**, `false` → **бит-в-бит путь 2.58.46** (parity-тест каждой зоны; полный список — §11). Resolves per-call, никогда не бросают (прецедент `summary_l1_capacity.capacity_guard_enabled`, summary_l1_capacity.py:47).

### 0.3 R17 / секреты

Нигде (логи/events/Inspector/доки) нет: API keys, полных сообщений, полных промптов, reference image bytes. Допустимо: counts, token estimates, safe message IDs, hashes, reason codes, provider host/model, latency, coverage (ТЗ §43, 23507–23528). Единый транспорт — существующий `mca_trace.emit_stage`/`mca_events` (pipeline_events.py:74-105); новых reason-кодов только через `mca_events.py:REASON_CODES`.

### 0.4 Не трогаем (hard parity-список)

`MAX_SUMMARY_PARTS` (§32; только Legacy output chunks — settings.py:1210, чтения в Legacy-путях); FTS fail-soft; seeded «Медведь Press»; числа `MAX_FACTS_PER_THREAD=30`/`MAX_FACTS_TOTAL=1000`/`MAX_THREADS=100` (summary_l1_contract.py:61-63 — меняется их роль: structural ceiling derived view, не whole-run invalid, см. §2); fail-soft L1 unknown-ID (§50.35); bounded revision ×2 (ADR-1028-7 D3/D5 — §18 ТЗ явно сохраняет); LLM_TIMEOUT/LLM_MAX_RETRIES для **не-Summary** потребителей llm_client (Direct/STT/image — AM-3 boundary); embed-fallback каскады (`EMBEDDING_FALLBACK_*`) — вне скоупа.

---

## 1. Зона A — Immutable SummarySourceWindow + capacity engine (§1–§10; T-4603–T-4606)

### A.1 SummarySourceWindow — durable first-class snapshot (§1–§2; T-4603, AM-1 носитель)

**Решение (носитель):** per-run durable row в новой SQLite-таблице `summary_source_windows` (DDL §10.1). Альтернативы отклонены:

1. *In-memory object* — не рестарт-безопасен (§21 требует resume) — отклонено;
2. *Перечитывание истории при resume* — окно может уйти (`compress_and_purge` выполняется ДО чтения окна, summary_generator.py:497-498; повторное чтение даёт другое окно) — нарушает immutability §2 — отклонено;
3. *Snapshot в `task_jobs` payload* — наследует L-EXTRA-6 (checkpoint перезаписывает payload-колонку) + сотни КБ JSON в job-строке — отклонено;
4. *Per-run row* (выбрано): одна запись на run, пишется ровно один раз в стадии SOURCE_READY, после — immutable (никаких UPDATE после создания).

```text
summary_source_windows:
  run_id          TEXT PRIMARY KEY     -- = correlation_id (S7, ADR-1026-9 D1)
  chat_id         INTEGER NOT NULL
  window_from     INTEGER              -- min timestamp окна
  window_to       INTEGER              -- max timestamp окна
  source_message_count INTEGER NOT NULL
  messages_json   TEXT NOT NULL        -- serialized окно (§2-схема), immutable
  created_at      INTEGER NOT NULL
  retention: удаляется только cleanup'ом (TTL SUMMARY_SOURCE_WINDOW_RETENTION_DAYS,
             default 7; env-only, Δ каталога = 0) после DONE/FAILED
```

Схема messages[] (§2, 22439–22449): message_id, author_id, display_name, username/alias if needed, timestamp, text, reply_to_message_id, forward/source metadata, media-derived text if already available. Источник полей — те же строки окна, что сегодня читаются `memory.get_window_messages` (summary_memory.py:2141) и идут в `build_l1_payload`/Legacy (summary_generator.py:498, 1085); **новой предфильтрации не вводить** (ASAP-2.1 R4-D-038 остаётся).

- Точка создания — ЕДИНАЯ: сразу после `SOURCE_WINDOW` (summary_generator.py:500-512), до любой LLM-стадии; событие `SOURCE_WINDOW_READY` (§42) с числами (R17).
- Все производные стадии (L1, FactPackage-синтез, Writer, Reviewer, Legacy, cover prompt) ссылаются по `run_id/source_ref`; **после создания SourceWindow новые «источники истины» из L1 JSON/FactPackage/XML не строятся** (22455–22457). В коде это фиксируется контрактом: единственный mutable-поток окна в run — snapshot; `L1Result.payload`/FactPackage становятся derived views (§2, §3).
- Immutability-тест (R6-A-002): повторное чтение snapshot'а после «мутации» потребителя байт-идентично; поле `messages_json` не апдейтится никаким кодом (guard-тест: попытка UPDATE после создания = дефект).
- Офф-паритет: `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED=false` → snapshot не пишется, стадии работают как сегодня (in-memory rows) — бит-в-бит 2.58.46. **Внутри run** объект в памяти в ON-режиме — тот же immutable-контракт (dataclass frozen / deep-copy на выдаче).

### A.2 Whole-window-first и capacity engine (§3–§7; T-4604/T-4605, AM-2)

**Решение (AM-1/AM-2):** режим входа выбирается **только реальной effective model capacity**, не плотностью фактов и не именем модели.

Capacity Resolver — расширение существующего `services/model_capacity.py` (ASAP-3.1 ADR-1028-3), не новый модуль:

```text
Цепочка приоритетов (ТЗ §5, 22520–22528 — дословно, AMEND ADR-1028-3):
  1. runtime/provider capability discovery   (адаптеры model_capacity.py:455+)
  2. provider model metadata/catalog          (OpenRouter/NanoGPT каталоги)
  3. project registry                         (наследник MODEL_CONTEXT_WINDOWS,
                                               model_capacity.py:98 — уровень 3, AM-2)
  4. explicit developer override              (models.chat_context_window_override)
  5. conservative fallback                    (≤16384 + WARNING, как сейчас)
```

- **Δ против текущего кода:** в ADR-1028-3 override стоит уровнем 1 (model_capacity.py:420-435); по директиве владельца §5 override переносится на уровень 4 — применяетcя только когда runtime/catalog/registry не дали значения. «Controlled lower-capacity» сценарии (§48 Run 2, §44-B/C) форсируются конфиг-фикстурой модели/каталога (регистрируемая запись или unknown-model fixture), а не override'ом поверх живого каталога — override больше не бьёт discovery.
- **Учёт по фактическому serialized prompt (§6, 22541–22573):** до LLM-вызова собирается реальный payload: system prompt (resolve_prompt L1/L2) + source JSON/XML + semantic instructions + response schema + metadata + output reserve + provider framing overhead → `required_input_tokens` (та же токенизация, что `_serialized_len`, summary_l1_clusterizer.py:341-346, но на ПОЛНОМ сообщении) + `reserved_output_tokens` + `safety_margin` vs `effective_context_window`. Решение: `required + reserve ≤ effective → WHOLE_WINDOW`, иначе `CAPACITY_OVERFLOW`. Оценка «только message.text» запрещена (fixture-контрпример обязателен).
- **Capacity cache (§7):** ключ = provider + base_url + model + capability fingerprint (Δ против ADR-1028-3: сейчас provider/base_url/model/override — добавить capability fingerprint); смена модели/base_url/provider → новый ключ; runtime 400/context-length error → инвалидация + переоценка в рамках run (событие `CAPACITY_RESOLVED` с причиной). TTL-механика `_ttl_for` (model_capacity.py:438-450) сохраняется.
- **Inspector-поля** закладываются в результат resolver'а сразу (R6-G-002): provider/model/effective window/serialized input/output reserve/mode/причина.

**Стратегии входа:**

```text
WHOLE_WINDOW:      L1 = ровно 1 запрос со всем serialized окном (§3: 22463–22478)
CAPACITY_OVERFLOW: см. A.3 (единственный легитимный chunking-режим)
```

- `MAX_SUMMARY_PARTS` не участвует в решении (§32). Статические бюджеты `limits.summary_hybrid_context_*` (resolve_l1_budget, summary_l1_clusterizer.py:600-611) теряют роль триггера стратегии: на ON-пути стратегию выбирает capacity resolver; static-ключи остаются только в OFF-паритет-пути (`budget_mode=legacy_static`) без изменения их значений/семантики.
- **Re-plan при смене провайдера/окна (§27–§28; T-4605):** перед отправкой на fallback-провайдера Supervisor обязан resolve fallback capacity → compare required input: вмещает → тот же whole-window task; меньше → switch to CAPACITY_OVERFLOW plan (lossless, §A.3); больше → допустим переход на whole-window, если run ещё не создал сегментные артефакты (иначе — не ломаем созданный run, §44-E). Семантика задачи НЕ меняется: window/coverage requirement/style/target completeness инвариантны (23139–23156); меняются только execution mode/strategy/transport/segmentation.
- Kill-switch master: `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED` (default ON). OFF → текущий контур 2.58.46 (planning-estimate sharding волны C + SUMMARY_COVERAGE_CHUNKING_ENABLED) байт-в-бит.

### A.3 CAPACITY_OVERFLOW — иерархический, lossless (§8–§10; T-4606)

- Отдельный явный режим (не «обычный flow с чанками»): Full SourceWindow → capacity-aware segmentation (переиспользование `_partition_lossless`, summary_l1_clusterizer.py:927-964 — по реальному serialized размеру, overlap=1, oversized-сообщение verbatim) → segment semantic maps (по карте §2) → merge (`merge_l1_payloads`/`summary_semantic_reduction` REUSE) → Writer stages (§2-B).
- **CoverageLedger** (new, чистый модуль): `source_message_ids / segment_assignments / processed_ids / fallback_ids / missing_ids`; инвариант XOR-покрытия: каждое сообщение окна ∈ ровно ≥1 сегмента; `merge`-дедуп overlap по stable ID (существующая семантика, summary_l1_clusterizer.py:695-802). Перед Writer `coverage == 100%`; иначе — восстановление сегмента (re-run только проблемного сегмента) либо честный `degraded` (run не может выглядеть как нормальный success; событие `COVERAGE_LEDGER`).
- Потеря сообщений запрещена (§10): fixture-тест «839 → 3 сегмента → все 839»; контрпример «взять 300» невозможен по построению (ledger).
- L1-запросов = число сегментов; каждый сегментный запрос Supervised (§4); partial success §14 (успешные maps сохраняются, проблемный сегмент — deterministic minimal map, не 0/839).
- Kill-switch: `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED` (default ON; OFF → текущий lossless-chunking контур 2.58.46).

---

## 2. Зона B — L1 semantic map / Writer / Reviewer (§11–§19; T-4607–T-4610)

### B.1 L1 = компактная semantic map (§12; T-4607, AM-1)

**Новый контракт выхода L1 (semantic map v1) — замена «фактов с текстами» на карту без source payload:**

```text
{
  "schema_version": 1,
  "topics":    [{topic_id, title, message_ids[], participants[], short_hint}],
  "events":    [{kind, message_ids[]}],          # kind ≤ 32 симв.
  "relationships": [{type, message_ids[], topic_ids[]}],   # optional
  "unassigned_message_ids": []
}
```

- Текст/timestamp/author/reply **materialize детерминированно из SummarySourceWindow** (по `run_id/source_ref`); source payload (тексты сообщений) в L1 output ЗАПРЕЩЁН — тест «в L1 output нет текстов сообщений» (R6-B-002).
- Компактность-бюджеты (output control, ответ на открытый вопрос PM по AM-1 — см. §12-сводку и ADR D3): `topics ≤ MAX_THREADS (100)`, `title ≤ TOPIC_MAX (200)`, `short_hint ≤ 160` (env-only `SUMMARY_L1_HINT_MAX_CHARS`, Δ каталога = 0), total map budget `SUMMARY_L1_MAP_MAX_TOKENS` (env-only, default 6000). Переполнение бюджета → **deterministic compaction** (merge мелких тем по пересечению message_ids, дедуп, обрезка hints по нижней границе) + статус `map_degraded` в `L1_RESULT` — **никогда не whole-run invalid и не «гильотина»**: sharding карты = fallback последней инстанции (сегменты карты с сохранением полного покрытия message_ids), не первичный механизм.
- **`MAX_FACTS_PER_THREAD=30` — structural ceiling derived view, не L1-запроса** (согласование с R4-D-036): фактов в L1 output больше не существует (см. B.2), поэтому `too_many_facts`-класс исходов из L1-валидации невозможен в WHOLE_WINDOW по построению; кап живёт в детерминированном синтезе FactPackage (B.3). Числа капов не меняются (§0.4).
- Prompt-миграция L1 (явная, прецедент R4-D-003): system-промпт L1 (SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT, summary_prompts.py) переписывается под map-схему одним коммитом «код+эталон+тесты»; старый промпт в эталоне помечается superseded (ADR-1028-8 D3).
- Валидатор новой схемы: структура/типы/unknown-field (строго, как сейчас), id-space (TG message_id, как сегодня), topic/title лимиты; **unassigned_message_ids обязателен**; события `L1_START/L1_ACTIVITY/L1_RESULT`.
- Kill-switch: `SUMMARY_L1_SEMANTIC_MAP_ENABLED` (default ON). OFF → L1 держит контракт §95-v2 (`summary_l1_contract.py`) и текущую валидацию/`too_many_facts` — бит-в-бит 2.58.46. **В OFF-ветке chunking-триггер остаётся как сегодня** (planning estimate); ON-ветка подчиняется только capacity resolver (A.2) — одно решение о режиме на run, не два.

### B.2 L1 fail-soft + partial success (§13–§14; T-4608)

- L1 total failure (timeout/provider unavailable/malformed/invalid) → Writer всё равно получает Full SourceWindow + instruction «semantic map unavailable — structure source yourself». `L1 failed ≠ Summary failed`; **переход на урезанный Legacy из-за L1 запрещён** (§48 Run 1: 23700–23701). Текущая LEVEL-2 цепочка «L1 непригоден → fallback package → L2» (summary_generator.py:1088-1132) перестраивается: fallback-package становится опциональной derived view (AM-5), а не обязательным путём выживания.
- CAPACITY_OVERFLOW partial success: 3/4 сегментов → 3 semantic maps + 1 deterministic minimal map (структурная заготовка сегмента из ledger: хронология/участники без LLM); SourceWindow для Writer остаётся полным; никогда не превращать в 0/839.
- Событие `L1_RESULT` несёт честный result (failed) при сохранном покрытии — Inspector не показывает «L1 ok» рядом с failed (R6-G-001).
- Regression: kill-switch OFF возвращает существующую LEVEL-2 механику (L1_FALLBACK_PACKAGE) байт-в-бит.

### B.3 Writer вход — Full SourceWindow первоклассно (§15–§16; T-4609, AM-4)

```text
WriterInput:
  source_window      — ОБЯЗАТЕЛЕН (snapshot A.1; serialized §92-формат без срезов)
  semantic_map?      — опционален (map v1 из B.1; отсутствует при L1 failure)
  fact_view?         — опционален (FactPackage = derived view)
  memory/context     — optional (existing)
  target_style / target_extent — existing (length-блок build_l2_input)
```

- **FactPackage понижен до derived view** (analytics/debugging/Reviewer/memory/fallback/compat; §15): `summary_fact_package.py` не удаляется; синтез детерминированный — SourceWindow + semantic_map → package (fragments materialize; chronology; roster), потолки `MAX_FACTS_PER_THREAD/MAX_FACTS_TOTAL` применяются здесь через существующий `repair_capacity_overflow` (summary_l1_capacity.py:173-318, переиспользуется без изменений). Writer **не зависит от степени урезания FactPackage** (тест: Writer работает на полном окне с сильно урезанным/отсутствующим fact_view).
- Prompt-миграция Writer (явная): `build_l2_input` (summary_l2_writer.py:456-540) расширяется секцией source window (serialized §92 + map) + инструкция «пакет фактов — вспомогательный индекс, оригинал — истина»; prose-first канон ADR-1028-7 D4 сохраняется (regression R4-D-003/004/021 зелёные).
- Проверки Writer против оригинала (§16): кто что сказал, reply, шутка vs факт, forward-новость, цифра, что Structurer пропустил (fixture §47-сценарий «Structurer пропустил — Writer восстановил»).
- Capacity-aware Writer (CAPACITY_OVERFLOW): Writer-вход тоже подчиняется capacity — если full window не влезает в Writer-модель, Writer идёт **иерархически** (per-segment source+map → сегментные черновики → merge-pass c бюджетом; покрытие по ledger, evidence_message_ids абзацев объединяются); lossless-требование то же, что A.3. В WHOLE_WINDOW Writer = один вызов с полным окном.
- Kill-switch: `SUMMARY_WRITER_SOURCE_INPUT_ENABLED` (default ON). OFF → Writer получает FactPackage-центричный вход как сегодня (бит-в-бит 2.58.46).

### B.4 Reviewer видит оригинал + bounded revision сохраняется (§17–§19; T-4610)

- `ReviewResult = Draft + Full SourceWindow + SemanticMap` (не только L1/FactPackage): проверка attribution/quote attribution/people identity/numbers-dates/reply context/major topic omission против реального source. Fixture §47: Reviewer ловит wrong speaker из оригинала, даже когда FactPackage этого не содержал (R6-B-007).
- CAPACITY_OVERFLOW Reviewer: полный window если влезает; иначе — evidence-slices (paragraph `evidence_message_ids[]` + reply-контекст, разворачиваемые детерминированно из SourceWindow) + segment maps для completeness-проверки; никогда только FactPackage.
- **Сохраняется без изменений** (§18/§19): bounded revision ×2 + patch-контракт `replace_paragraphs` + progress criterion (ADR-1028-7 D3/D5); prose-first/quote policy; review_degraded-политика. Quote repair ladder (summary_quote_repair.py) сохраняется; резолв цитат против SourceWindow усиливает D3-resolver MCA-22 (extension, не fork).
- Kill-switch OFF (`SUMMARY_L2_REVIEW_ENABLED=false`) — прежний single-call L2 → Legacy, бит-в-бит.

---

## 3. Зона C — Legacy и output (§31–§33; T-4611)

- **Legacy начинает с SummarySourceWindow (source_ref)** — единый snapshot с Hybrid (сегодня `_run_legacy_pipeline` получает те же `rows`, summary_generator.py:1002-1009; под 4.1 — чтение из snapshot'а run'а, тот же материал).
- **`hard cap 50000 chars → stop` запрещён окончательно** (§31): R4-C-007/008 сняли silent-stop, но фиксированные капы `SUMMARY_MAX_WINDOW_MESSAGES=500` / `SUMMARY_MAX_CONTEXT_CHARS=120000` (settings.py:1301-1303, resolve_window_caps — summary_legacy_fullwindow.py:56-75) больше НЕ триггер «стоп»: ветка Legacy capacity-aware — (а) Legacy-модель вмещает full-window → one request (плоский XML на малых окнах остаётся бит-в-бит); (б) не вмещает → CAPACITY_OVERFLOW hierarchical legacy (reduction `summary_semantic_reduction` REUSE) со 100% source coverage; (в) coverage <100% → честный degraded (событие + run state), не молча. Dead-path-проверка «XML context: hard cap … reached» (summary_xml.py:76) обязательна (R6-E-001).
- `MAX_SUMMARY_PARTS` — только число Telegram sendMessage chunks Legacy output; не влияет на Hybrid input/SourceWindow/L1/L2/Rich (§32; регресс R4-C-010 + hybrid budget-тест DoD 13).
- **Output length (§33):** готовый текст не обрезается алгоритмически (`text[:N]`/`paragraphs[:N]` запрещены; runaway-guard отделён от «нормально длинного» — hard limit только API/transport/pathological); target length — soft semantic target Writer'у (существующий length-блок, summary_l2_writer.py:531-539); слишком длинный plain → split delivery без потери tail.
- Kill-switch: `SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED` (default ON; OFF → текущий контур Legacy full-window 2.58.46, байт-в-бит; бит-в-бит включает и действующие капы окна).

---

## 4. Зона D — LLMExecutionSupervisor (§22–§30; T-4612–T-4615, AM-3)

### D.1 Scope и границы (решение AM-3)

- **Scope Supervisor = Summary-пайплайн ТОЛЬКО** (L1/L2/Writer/Reviewer/Revision/Legacy LLM-вызовы). Прочие потребители llm_client (Direct, STT, image, embeddings, lore/dream workers) **не трогаются**: их `LLM_TIMEOUT`/`LLM_MAX_RETRIES`/fallback-каскады работают как сегодня. ТЗ §22–§30 адресует Summary-инцидент; обобщение на background-LLM — отдельное решение, в 4.1 не входит (MCA-05 граница).
- **Механизм интеграции (модификация client минимальна):** Supervisor — wrapper-уровень над существующим per-call contract `llm_client._post(budget=, max_retries=, retry_statuses=)` (llm_client.py:665-696, ADR-1024-6 F1 + ASAP-4 allowlist) через существующий канал `generate_background`-класса (llm_client.py:1098-1132) и точки инъекции `llm_call` (`_make_llm_call`, summary_l1_clusterizer.py:1038 / summary_l2_writer.py:1005). Для Summary-вызовов: `max_retries=1` (transport), `retry_statuses=()` (статус-ретраи — решение Supervisor'а, не нижнего слоя), fallback-каскад llm_client для Summary-канала НЕ используется (`LLM_FALLBACK_*` остаётся для прочих потребителей) — провайдерский fallback резолвит Supervisor с capacity re-plan (D.3).
- **AMEND ADR-1024-6 (по факт-листу conflict-audit п.4):** для Summary-пути wall-clock `LLM_TIMEOUT`/`LLM_TOTAL_BUDGET` перестают быть health-критерием; контракт _post сохраняется для остальных потребителей байт-в-бит.

### D.2 Один владелец retry — no retry multiplication (§23; T-4612)

Фактический максимум попыток СЕГОДНЯ на один логический L1-запрос (посчитано, R6-D-002):

```text
llm_client._post: (LLM_MAX_RETRIES=2 + 1) = ≤3 HTTP   [llm_client.py:704-705]
  × nested fallback-провайдер: (LLM_FALLBACK_MAX_RETRIES=2 + 1) = ≤3 HTTP
  = ≤6 HTTP на один llm-вызов [llm_client.py:886-943]
× L1 correction retry (≤2 логических вызова) = ≤12 HTTP
× stage-цепочка (L1 → fallback package → L2 ≤6 logical) → десятки HTTP на run
```

Контракт Supervisor'а:

```text
Один LLMExecutionSupervisor владеет (§23, 22993–23020):
  request_id, provider, model, operation, started_at, last_activity_at,
  state, attempt, fallback
Один attempt-бюджет на логический request:
  HTTP-потолок на логический вызов ≤ 4 (задокументирован, закреплён тестом):
    1 primary + ≤1 primary-transport-retry + ≤1 fallback-provider
    + ≤1 fallback-transport-retry
Логические бюджеты стадий сохраняются (ADR-1028-7 D3.3): L1 ≤2 (вкл. semantic
correction retry), L2 ≤6; transport-ретраи в них не входят (как и сейчас).
Вложенных retry-циклов нет: stage retry × llm_client retry × provider retry
× fallback retry → одна orchestration policy.
```

- Паттерн-донор: `media_execution.py` MediaExecutionPolicy/JobState (REUSE адаптивных окон, capability-деклараций, job-state polling) + executor-прецедент `embedding_control_plane.py` (единый attempt-бюджет, EmbeddingExecutor, embedding_control_plane.py:910+). Второго контура media не создаётся.
- Kill-switch: `SUMMARY_LLM_SUPERVISOR_ENABLED` (default ON). OFF → Summary-вызовы идут через прежний llm_client-контур (бюджеты/каскады 2.58.46) байт-в-бит.

### D.3 Execution modes + capability discovery (§24, §26; T-4613)

- Адаптеры честно декларируют (обязательные поля, расширение LLMClient-обёртки Summary-канала): `supports_streaming_liveness / supports_async_status / supports_cancel / opaque_sync_only`. **«Пинговать генерацию» выдуманным endpoint запрещено** (23093–23108); capability — только из реальных данных провайдера (схема OpenAI-compatible `/chat/completions` без job/status API → `opaque_sync_only=True`; streaming — только если реально реализован SSE-транспорт, не декларативно).
- Mode A — Async Job: submit → queued → processing → completed; polling реального статуса; живой status = живой запрос. Mode B — Streaming: последний token/event/keepalive → `last_activity_at`; elapsed time не убивает; inactivity/stall detection. Mode C — Sync opaque: adaptive watchdog как последний рубеж.
- **Реалистичный базис (honest posture):** текущий llm_client — sync-opaque (Mode C) — это реализуемая база; Mode A/B — контрактные слоты, активируемые ТОЛЬКО при верифицированном провайдер-адаптере (прецедент `EMBED_ASYNC_BATCH_ENABLED` default OFF до live-верификации). Декларации в Inspector отражают фактическое состояние (не «stream ✓» при sync-транспорте).

### D.4 Adaptive watchdog + hard deadline fuse + telemetry (§25, §29; T-4614)

- Основной критерий unhealthy: **нет подтверждённой активности / provider status stalled** — не «прошло N секунд» (23079–23083). Живой длинный запрос (stream/heartbeat активен) не убивается wall-clock (§45).
- **Hard deadline — только safety fuse:** developer-level env (`SUMMARY_LLM_HARD_DEADLINE_SECONDS`, default большой, clamp [600, 7200]; Δ каталога = 0), зависит от operation/model/input; последняя аварийная защита.
- **Inactivity threshold:** adaptive — из телеметрии per (provider, model, operation, input-token bucket, output-token bucket): queue time, time-to-first-activity, generation duration, tokens/sec where available, failure rate (23159–23185). Cold default env `SUMMARY_LLM_INACTIVITY_SECONDS` (clamp [60, 900]); percentile-оценщик по успешным наблюдениям — REUSE паттерна `media_execution.resolve_windows` (media_execution.py:24-35, adaptive estimator строится ТОЛЬКО по успешным длительностям).
- Telemetry хранится process-local + в stage-events (R17-safe числа); питает watchdog; единого глобального timeout-числа на проект нет.

### D.5 Rename `total_budget_exceeded` (§30; T-4615)

- time/retry-budget причина → `execution_deadline_exceeded` (fuse) / `retry_time_budget_exhausted` (исчерпание попыток); точка эмиcсии — llm_client.py:858-874 для Summary-канала (через Supervisor) + события Summary; `budget` не должен выглядеть как денежный balance.
- Совместимость старых логов — **read-side alias only** (`map_reason` в pipeline_events.py:58-67 + human-переводы Analytics); новых эмиссий старого кода нет. Для не-Summary потребителей llm_client лог «total_budget_exceeded» остаётся (их контракт не трогается) — R6-D-009 фиксирует только Summary-эмиccию.
- Kill-switch: rename живёт под `SUMMARY_LLM_SUPERVISOR_ENABLED` (OFF → прежние логи байт-в-бит).

---

## 5. Зона E — Durable SummaryRun + resume (§20–§21; T-4616/T-4617)

### E.1 Носитель и state machine (§20; T-4616)

**Решение (носитель): dedicated additive SQLite-таблицы** `summary_runs` + `summary_run_stages` (DDL §10), а НЕ task_jobs payload и НЕ перегрузка `mca_pipeline_runs`:

- `mca_pipeline_runs` (v19, database.py:480-505) остаётся root-lifecycle/heartbeat/watchdog-уровнем mca-17a; `summary_runs` — сервисная надстройка с domain-состоянием (прецедент: cover_style_jobs поверх task_jobs+mca_pipeline_runs, cover_style_jobs.py:1-6);
- task_jobs (v14) используются как execution-носитель (heartbeat/fencing/resume очереди — TaskJobStore, task_supervisor.py), НО checkpoint run-state хранится в `summary_runs`, а не в payload-колонке — **L-EXTRA-6 не наследуется** (checkpoint-cover проблема перезаписи payload известна, reuse-inventory §2);
- L-EXTRA-7: `summary_run_id` — stable: создаётся один раз при создании джобы run'а и персистится в `summary_runs`/task_jobs; cover-джоба уже ключуется от `summary_run_id|style_id` (cover_style_jobs.py:566-573, coalesce по run_id, :592) — кросс-рестарт resume закрыт.

```text
State machine (ТЗ §20, 22936–22951):
CREATED → SOURCE_READY → STRUCTURING → STRUCTURE_READY → WRITING → REVIEWING
        → TEXT_READY → BASE_COVER → STYLE_EDIT → PUBLISHING → DONE
        (любая стадия → DEGRADED | FAILED)
Каждая стадия персистит (summary_run_stages, append-only §50.54):
  status, started_at, last_activity_at, finished_at, attempt, provider, model,
  result_ref, failure_reason
```

- `summary_runs`: run_id (PK, stable), chat_id, state, manual, window_from/to, source_ref (= run_id → summary_source_windows), publication_status/publication_result_ref, pipeline_health, created/updated_at. Тесная связь с RunContext (summary_run_log.py) и mca_pipeline_runs — интеграция, не дубль (R6-C-001).
- Kill-switch: `SUMMARY_RUN_DURABLE_ENABLED` (default ON). OFF → runs не персистятся, workflow как сегодня (бит-в-бит); `stage_events` append-only семантика (ADR-1028-7 D7.6, pipeline_events) остаётся независимо.

### E.2 Resume + no duplicate publication (§21; T-4617)

- Рестарт: TaskJobStore восстанавливает незавершённую джобу run'а → читается `summary_runs` → последняя успешно завершённая стадия → продолжение с неё (не начинать заново); SourceWindow/semantic map/writer draft берутся из durable-артефактов по run_id.
- **Идемпотентность публикации (DoD 21):** переход в PUBLISHING фиксируется в `summary_runs` ДО отправки; перед отправкой — проверка `publication_status` (не публиковать, если DONE/published) + существующая лестница R4-D-051 (sent unknown → reconcile → retry) + content-hash барьер `bot_output_ledger` (REUSE); двойной финальный месседж невозможен (тест: kill в PUBLISHING → рестарт → ровно одна публикация).
- Cover-джоба продолжает работу из task_jobs с тем же run_id (existing, cover_style_jobs.py:483-610).
- Kill-switch общий с E.1.

---

## 6. Зона F — Cover pipeline и Style (§34–§37; T-4618–T-4620)

### F.1 Cover/text independence (§34; T-4618)

- После TEXT_READY: Base Cover → Optional Style Edit → Publish; cover-ветка подписывается на approved text snapshot (`publication_result_ref`), text pipeline **не регенерируется из-за cover failure** (сегодня уже фактически так — run_style_job отдельная джоба; контракт фиксируется regression-тестом + R4-B-003 ladder зелёный).
- Text-fallbacks не наследуются cover'ом: обложка деградированных путей строится детерминированно из финального документа (existing `_derive_fallback_cover_prompt`), не из текстовых fallback-механик.

### F.2 Medved Press connection inheritance fix (§35; T-4619)

Прод-инцидент: Base cover ✓, Selected style Medved Press, «Не настроены адрес/модель обработки (Connections layer)» → Style edit NOT EXECUTED → published base cover (§0/§35).

- Root-cause (код): `resolve_style_slot` резолвит глобальный слот из `models.image_style_base_url`/`models.image_style_model` (cover_style_pipeline.py:68-71); при модели профиля «По умолчанию (глобальная настройка)» пустой глобальный слот даёт `configured=False` → `connection_status` «Адрес и модель не настроены» (cover_style_pipeline.py:214-215) → `not_configured` → style edit не выполнен. Отдельная style connection трактуется как обязательная.
- **Фикс (наследование profile → global default → chat):** если профиль настроен как «По умолчанию (глобальная настройка)» (`model_mode != custom`), runtime обязан реально разрешить **global/default image-edit provider + model** по лестнице наследования:

```text
1. per-chat override (`prompts.summary_cover_style_id`-слой) — как есть
2. profile connection override (model_mode=custom, connection_id) — как есть
3. global default image-edit slot: Connections layer default-подключение,
   поддерживающее image_edit; иначе models.image_style_* (existing глобальный слот)
4. ничего не разрешилось → честный reason (не «успех без стиля»)
```

- Отдельная style connection НЕ обязательна (23285–23314); наследование «По умолчанию» → глобальный image-edit provider+model проверяется тестом; prod-инцидент воспроизводится как исправленный (T-4633); явно настроенная style connection по-прежнему работает (регресс).
- Kill-switch: `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` (default ON; OFF → текущий resolver байт-в-бит).

### F.3 Capability registry + fail-soft ladder (§36–§37; T-4620)

- Выбор обработчика стиля — через **существующий capability registry** (`services/image_capabilities.py` + `ImageProviderAdapter` media_execution.py:308+): поля image_edit, reference_images, max_reference_images, prompt_limit if known, async/stream/sync mode. Хардкоды NanoGPT/Qwen запрещены (инспекция T-4629).
- При смене image provider стиль либо продолжает работать, либо Inspector честно показывает «selected model does not support image_edit» (текущий `check_edit_allowed` gate, cover_style_pipeline.py:126-137, сохраняется; source виден в карточке §41).
- **Fail-soft ladder (§37) — без изменений по сути, фиксация контракта:** TEXT_READY → Base Cover (fail → publish text without image) → Style Edit (success → Styled; fail → Base Cover) → RichMessage (success | fail → Plain text). Никакой cover/style failure не уничтожает текст. Style failure → Base cover; Base cover failure → Rich без image/plain; Rich failure → Plain **same ResponseDocument** (тесты §46).
- События `STYLE_RESOLVE` (источник резолва — часть фикса F.2), `STYLE_EDIT_START/RESULT` с точной причиной (не generic `style_failed`; правило ADR-1028-7 D6.3 сохраняется).

---

## 7. Зона G — Run Inspector + structured events (§38–§43; T-4621–T-4624)

### G.1 Честная coverage semantics (§38; T-4621)

Раздельные метрики (источник — `summary_runs`/`summary_run_stages`/CoverageLedger, НЕ парсинг логов):

```text
Источник:                839/839 · 100%
Structurer/L1:           839/839 whole-window input; result: failed
Writer input coverage:   839/839 · 100%
Final text source coverage: 839/839 · 100%
Overflow:                segments 4/4; messages covered 839/839
```

- «839/839 Coverage 100%» рядом с L1 failure НЕ показывается как единый успех (fixture-тест обязателен; R4-E coverage-first-class сохраняется).

### G.2 Capacity + liveness + style cards (§39–§41; T-4622/T-4623)

- Карточка «КОНТЕКСТ МОДЕЛИ»: Provider / Model / Effective window / Serialized input / Output reserve / Mode (WHOLE_WINDOW | CAPACITY_OVERFLOW + человеческая причина).
- Liveness на каждой LLM stage: execution mode (stream/async job/sync), last activity, provider fallback, reason; default-вид человекочитаем, без машинной каши (23434).
- Cover style card (§41): Base cover ✓ / Selected style / Style provider / Style model / Style capability image-edit ✓ / Reference assets / Style edit ✓-✕ / Published cover Styled-Base-None + точная причина fallback.
- Развитие существующего Inspector (R4-E-002 правило: не новый продукт; pipeline_analytics + mca_events).

### G.3 Structured events (§42; T-4624)

Единый run_id; аддитивное расширение `pipeline_events.py` (существующие имена не переименовываются — совместимость mca_events/Analytics):

| ТЗ §42 | Фактическое имя события | Статус |
|---|---|---|
| SUMMARY_START | `SUMMARY_RUN_START` | есть (pipeline_events.py:27) |
| SOURCE_WINDOW_READY | `SUMMARY_SOURCE_WINDOW_READY` | new |
| CAPACITY_RESOLVED | `SUMMARY_CAPACITY_RESOLVED` | new |
| EXECUTION_MODE_SELECTED | `SUMMARY_EXECUTION_MODE_SELECTED` | new |
| L1_START/ACTIVITY/RESULT | `SUMMARY_L1_STAGE` + `SUMMARY_L1_ACTIVITY` | есть + new ACTIVITY |
| WRITER_START/ACTIVITY/RESULT | `SUMMARY_L2_STAGE` (writer) + `SUMMARY_WRITER_ACTIVITY` | есть + new |
| REVIEW_START/RESULT | `SUMMARY_L2_REVIEW` | есть |
| REVISION_START/RESULT | `SUMMARY_REVISION_*` | new |
| TEXT_READY | `SUMMARY_TEXT_READY` | new |
| BASE_COVER_START/RESULT | `COVER_BASE_*` (cover ветка) | есть |
| STYLE_RESOLVE | `COVER_STYLE_RESOLVE` | new |
| STYLE_EDIT_START/RESULT | `COVER_STYLE_*` | есть |
| PUBLISH_START / RICH_PUBLISH_RESULT / PLAIN_FALLBACK_RESULT | `PUBLISH_*` (summary_run_log S6) | есть |
| SUMMARY_DONE | `SUMMARY_RUN_DONE` | есть |
| SEGMENT_PLAN / SEGMENT_RESULT / COVERAGE_LEDGER (overflow) | `SUMMARY_SEGMENT_PLAN/_RESULT/_LEDGER` | new |

- append-only (§50.54); fail-open эмиссия; R17-скан обязателен (нет полных сообщений/промптов/ключей/image bytes).
- L1_TIMEOUT-вопрос производительности: **не решается константой** — нового admin-ключа L1_TIMEOUT нет; длительность L1 управляется Supervisor'ом (adaptive inactivity + hard fuse developer-level, D.4) и самой whole-window архитектурой (1 запрос вместо k×ретраев). Производственная метрика — вехи §50 (time to first activity, active generation duration, wait/queue, fallback count, total run duration), **без выдуманного SLA** (R6-H-007).

---

## 8. Зона H — Контракт настроек (§51; T-4602)

### 8.1 Таблица «ключ → уровень → описание»

| Ключ | Уровень | Судьба |
|---|---|---|
| `L1_CHUNK_SIZE` / `L2_TIMEOUT` / `MAX_INPUT_CHARS` / `SUMMARY_CONTEXT_TOKENS` | — | **НЕ создаются** (запрещены §51, 23777–23782; тест-контракт «нет новых admin-цифр») |
| `LLM_TIMEOUT` / `models.llm_timeout` (param_catalog.py:735) | обычная админка (остаётся) | Не трогается: health-метрика **не-Summary** потребителей; Summary перестаёт зависеть от неё (D.1/D.4). Описание в каталоге дополняется пометкой «не управляет Summary» |
| `LLM_TOTAL_BUDGET` / `models.llm_total_budget` (param_catalog.py:745) | обычная админка (остаётся) | Аналогично: не-Summary; Summary-канал — под Supervisor |
| `LLM_MAX_RETRIES`, `LLM_FALLBACK_*`, `models.llm_*` backoff | обычная админка (остаётся) | Не трогаются (чужие потребители); Summary-канал не использует каскад (D.1) |
| `SUMMARY_LLM_HARD_DEADLINE_SECONDS` | **developer deep** (env-only, Δ каталога = 0) | Safety fuse §25; человеческое описание |
| `SUMMARY_LLM_INACTIVITY_SECONDS` | developer deep (env-only) | Inactivity threshold §25 |
| `SUMMARY_LLM_*_COLD_DEFAULTS` (ttfa/generation per mode) | developer deep (env-only) | Cold defaults adaptive watchdog |
| `models.chat_context_window_override` (существует, каталог) | developer deep | AM-2: остаётся override-слой 4; описание уточняется («применяется, когда discovery/каталог/реестр не дали значения») |
| `SUMMARY_L1_MAP_MAX_TOKENS`, `SUMMARY_L1_HINT_MAX_CHARS` | developer deep (env-only) | Output-бюджет semantic map §B.1 |
| `SUMMARY_L1_TARGET_FACTS_PER_CHUNK`, `SUMMARY_L1_FACT_DENSITY_MESSAGES_PER_FACT` (env-only уже) | developer deep (остаются env-only, Δ каталога = 0) | Demoted: больше НЕ триггер sharding (AM-1); используются только как bounds внутри CAPACITY_OVERFLOW-планирования/output-бюджета derived view |
| `limits.summary_hybrid_context_*` (существуют, каталог) | demote → developer-группа | Теряют роль триггера стратегии (A.2); остаются OFF-паритет legacy_static |
| `SUMMARY_SOURCE_WINDOW_RETENTION_DAYS` | developer deep (env-only) | Retention snapshot'ов |
| `SUMMARY_MAX_WINDOW_MESSAGES` / `SUMMARY_MAX_CONTEXT_CHARS` | demote → developer | Перестают быть триггером «стоп» (§3); остаются caps OFF-паритета |

### 8.2 Contract-тест

«Нет новых ручных магических цифр в обычной админке»: ни один новый ключ §D.4/B.1/A.1 не попадает в каталог/обычные вкладки; developer-ключи документированы с человеческим описанием (R6-H-008).

---

## 9. Тестовые волны (§44–§47; T-4625–T-4628)

- **T-4625 (§44 A–E):** A large-context → WHOLE_WINDOW, L1 requests=1, coverage 100%; B 32k → CAPACITY_OVERFLOW, все covered, no truncation; C смена модели → cache invalidated + auto strategy re-plan; D fallback меньше → re-plan, не oversized вслепую; E fallback больше → whole-window допустим, если не ломает созданный run.
- **T-4626 (§45):** streaming long generation не убивается wall-clock; async job processing → polling + persisted state, no duplicate submit; stalled stream → cancel/fallback по capability; opaque sync → adaptive watchdog + finite fallback.
- **T-4627 (§46):** L1 total failure → Writer с full SourceWindow (без урезанного Legacy); Reviewer failure → usable draft не теряется (controlled fallback policy R4-D-029); base cover failure → Rich без image/plain; style failure → base cover; Rich failure → Plain same ResponseDocument.
- **T-4628 (§47):** 8 fixture-сценариев attribution против SourceWindow: два похожих имени, reply chain, forwarded, цитата, шутка vs факт, числа, даты, конфликтующие реплики.
- Плюс: OFF-parity каждой зоны (бит-в-бит 2.58.46), ledger-инварианты, immutability SourceWindow, идемпотентность публикации, R17-скан.

## 10. DDL delta (полный список)

| # | Store | Изменение | Тип | Обратимость |
|---|---|---|---|---|
| 1 | SQLite `user_version 23→24` | `summary_source_windows` (run_id PK, chat_id, window_from/to, source_message_count, messages_json, created_at) | additive CREATE TABLE IF NOT EXISTS | DROP безопасен |
| 2 | SQLite | `summary_runs` (run_id PK, chat_id, state, manual, window_from/to, publication_status, publication_result_ref, pipeline_health, created_at, updated_at) + индексы (state, chat_id, started) | additive | DROP безопасен |
| 3 | SQLite | `summary_run_stages` (id PK autoincrement, run_id FK, stage, status, started_at, last_activity_at, finished_at, attempt, provider, model, result_ref, reason_code) — **append-only** | additive | DROP безопасен |
| 4 | SQLite | retention — cleanup-механика (DELETE только новых таблиц по TTL) | runtime | — |
| 5 | PostgreSQL | **no-op** | — | — |

Идемпотентность: повторный прогон — no-op; на чистой БД — в составе штатного DDL; старый код совместим (таблицы не читаются старым кодом). Бэкап до DDL по fail-closed guard'у (прецедент ADR-1028-7 §5 deployment).

## 11. Kill-switches / rollback

### 11.1 Список (все env-only, default ON)

| Флаг | Зона | OFF-поведение (= 2.58.46) |
|---|---|---|
| `SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED` | A.1 | без durable snapshot (in-memory rows) |
| `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED` | A.2 master | planning-estimate sharding/статические бюджеты как сегодня |
| `SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED` | A.3 | текущий lossless-chunking без ledger-семантики |
| `SUMMARY_L1_SEMANTIC_MAP_ENABLED` | B.1 | L1 §95-v2 контракт + too_many_facts валидация как сегодня |
| `SUMMARY_WRITER_SOURCE_INPUT_ENABLED` | B.3 | Writer = FactPackage-центричный вход |
| `SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED` | §3 | Legacy full-window контур 2.58.46 |
| `SUMMARY_LLM_SUPERVISOR_ENABLED` | D master | llm_client-каскады/тайминги 2.58.46, старые reason-коды |
| `SUMMARY_RUN_DURABLE_ENABLED` | E | без персистентного run state/resume |
| `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` | F.2 | текущий resolver слота |

Существующие Summary-флаги (SUMMARY_HYBRID_L2_ENABLED, SUMMARY_L2_REVIEW_ENABLED, SUMMARY_REVISION_PATCH_ENABLED, SUMMARY_QUOTE_REPAIR_ENABLED, SUMMARY_LEGACY_FALLBACK_ENABLED, SUMMARY_COVERAGE_CHUNKING_ENABLED, SUMMARY_L1_CAPACITY_GUARD_ENABLED, SUMMARY_LEGACY_FULL_WINDOW_ENABLED, SUMMARY_PIPELINE_EVENTS_ENABLED) сохраняются с их семантикой OFF-паритета; где новая зона перекрывает старую — новая ON-ветка главенствует, старая остаётся OFF-путём (single source of decision в коде: первыми проверяются новые флаги).

### 11.2 Rollback-матрица

| Сценарий | Действие |
|---|---|
| Деградация whole-window/L1 | `SUMMARY_WHOLE_WINDOW_FIRST_ENABLED=false` (+при необходимости `SUMMARY_L1_SEMANTIC_MAP_ENABLED=false`) + рестарт → контур 2.58.46 |
| Деградация Supervisor | `SUMMARY_LLM_SUPERVISOR_ENABLED=false` + рестарт |
| Деградация durability | `SUMMARY_RUN_DURABLE_ENABLED=false` (runs не читаются старым кодом; данные additive) |
| Деградация cover/style | `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED=false` |
| Полный откат | cold revert деплой-коммита; additive DDL v24 совместима со старым кодом |
| Незавершённые runs при откате | остаются в `summary_runs`/`summary_source_windows` как данные; старый код их не читает; retention их удалит |

## 12. Acceptance-привязки (не дублирует tasks.md)

- Production Run 1 (§48, large-context) → T-4631; Run 2 (lower-capacity, конфиг-фикстура) → T-4632; Medved Press §49 → T-4633; performance §50 (базис 622/155/1331, без SLA) → T-4634; DoD 35/35 + финальная строка §52 → T-4635/T-4636.
- No-false-acceptance (§0 директива): запуск не считается успешным Hybrid из-за того, что «что-то опубликовалось» — health = publication_status × раздельная coverage × честные stage results.
- Reviewer gate T-4629 линзы: механизм против заглушки; OFF-паритет; AM-1…AM-4 по ADR-1028-8; R17; контроль разрастания.

## 13. Матрица spec → tasks (T-4600–T-4636)

| Spec-раздел | Задачи | R6 |
|---|---|---|
| §0 общие принципы | все Builder-зоны | сквозное |
| §1 A.1 SourceWindow durable snapshot | T-4603 | R6-A-001/002 |
| §1 A.2 whole-window-first + capacity engine + cache/re-plan | T-4604, T-4605 | R6-A-003…007, R6-D-006/007 |
| §1 A.3 CAPACITY_OVERFLOW + CoverageLedger | T-4606 | R6-A-008…010 |
| §2 B.1 L1 semantic map | T-4607 | R6-B-001/002 |
| §2 B.2 L1 fail-soft/partial | T-4608 | R6-B-003/004 |
| §2 B.3 Writer full source + FactPackage derived | T-4609 | R6-B-005/006 |
| §2 B.4 Reviewer full source + bounded revision | T-4610 | R6-B-007/008/009 |
| §3 Legacy/output | T-4611 | R6-E-001…003 |
| §4 Supervisor core/modes/watchdog/rename | T-4612, T-4613, T-4614, T-4615 | R6-D-001…009 |
| §5 SummaryRun + resume | T-4616, T-4617 | R6-C-001/002 |
| §6 Cover/style | T-4618, T-4619, T-4620 | R6-F-001…004 |
| §7 Inspector/events | T-4621, T-4622, T-4623, T-4624 | R6-G-001…006 |
| §8 Settings contract | T-4602 | R6-H-008 |
| §9 Тестовые волны | T-4625–T-4628 | R6-H-001…004 |
| §12 Acceptance/release | T-4629–T-4636 | R6-H-005…009 |

ARCH-задачи: T-4601 закрыт этим spec+ADR; T-4602 закрыт §8 (таблица + contract-тест).
