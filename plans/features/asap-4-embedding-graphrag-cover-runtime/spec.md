# ASAP-4 — spec.md (Step 2 @Architect, 02.10.2026)

Дизайн-спецификация эпика `asap-4-embedding-graphrag-cover-runtime`. Статус: **Accepted** (решения — в `adr-1028-7-asap4-embedding-control-plane.md`; этот документ — контракты для Builder/Reviewer/DevOps).

Источники: ТЗ владельца §0–§87 (`current_task.md:16484–20843`), PM-пакет (requirements-map / reuse-inventory / conflict-audit / tasks.md), прод-факты (`prod-facts.md`, 02.10.2026), ADR-1028-5 (reuse-база), conflict-audit §8 (supersede/amend-карта).

**Границы:** дизайн и контракты; без implementation. Запрещено §1 (R4-G-001): второй GraphRAG / второй Cover pipeline / второй Summary.

---

## 0. Общие принципы (обязательные для всех зон)

### 0.1 DDL-дисциплина

| Сторона | Правило |
|---|---|
| SQLite | Только **additive** MigrationStep: `user_version 22 → 23` (на проде факт. 22). Новые таблицы — `CREATE TABLE IF NOT EXISTS`; новые колонки — `ALTER TABLE … ADD COLUMN` с NULL/DEFAULT. Ни одного `UPDATE` существующих строк при миграции. Реестр поколений (`mca_embedding_index_generations`, v18) остаётся единственным; аналогично v22-состояние не пересоздаётся |
| PostgreSQL | **no-op обязателен**: embedding control-plane живёт в SQLite + runtime; credential-метаданные (label quota group) — в существующих PG config/KV-структурах без схемы-изменений. Если Builder докажет невозможность — только через ADR-waiver (прецедент T-4242), не молча |
| PG (cover/connections) | Существующие `cover_style_*` (включая `cover_style_connections`, ADR-1028-5 D14) не изменяются — зона B работает поверх |

### 0.2 Kill-switches (env-only, default-ON, OFF = bit-identical legacy)

Все новые ветки кода защищены флагом; при OFF путь выполнения обязан быть **бит-в-бит** прежним (тот же порядок вызовов, тот же формат логов/событий). Rollback-единица — env + рестарт (soft), либо cold revert. Полный список — §8.2.

### 0.3 Секреты и R17

Ключи — только алиасы/credential_id; в логах, events, Analytics, UI — никогда значений (прод-факт: даже diagnostics обязаны обходиться `key_idx`). Raw fact/chat text — не логировать (R17).

### 0.4 Не трогаем (hard parity-список)

`MAX_SUMMARY_PARTS` (§58); FTS fail-soft и механику (§62 ADR-1028-5); удалённую ASAP-2.1 предфильтрацию; fail-soft L1 unknown-ID (§50.35); модель `gemini-embedding-001` (авто-миграция на `-2` запрещена, §15); `MAX_FACTS_PER_THREAD/MAX_FACTS_TOTAL` как **числа** (меняется их роль: ceiling вместо guillotine, §50.36); seeded `Медведь Press` и его сид-механику.

---

## 1. Зона A — Embedding Control Plane (P0: 429/building → FTS-only)

### A.1 Модель credentials и quota groups (§3–§5, §11, §12; T-4402)

Контракты:

```text
EmbeddingCredential:  credential_id, provider, base_url, model, alias,
                      quota_group_id, health, cooldown_until, updated_at
EmbeddingQuotaGroup:  quota_group_id, state(healthy|cooling_down|exhausted|unknown),
                      next_allowed_at, note
```

- Credential pool — **список** в существующей конфигурации (PG hot-config `keys.*`/env-алиасы). Три нынешних ключа (`keys.embedding_api_key` + `EMBEDDING_FALLBACK_API_KEY[_2]`) становятся entries; hardcode `primary+2` удаляется из контракта (код-факт: `llm_client.py:296-303,371-373`).
- Определение quota group — лестница §5: (1) provider/runtime metadata (если безопасно доступна); (2) connection metadata из Connections layer; (3) явный developer label (`quota_group` в конфиге credential); (4) `unknown`. **Запрещено** вычислять project из значения ключа. `unknown` → UI «Проект/квота: не определены».
  - **Уточнение (rework round 1, ратификация L-ASAP4-6):** в реализации Wave A шаги 1–2 (provider runtime metadata / Connections layer) **слиты в один label-источник**: developer label (`EMBEDDING_QUOTA_GROUP_LABELS` env / hot `keys.embedding_quota_group_labels`) → иначе сразу `unknown`. Основание — прод-факты Q1/Q8: один endpoint на все ключи, provider-runtime quota metadata недоступна без платного вызова, Connections layer не содержит embedding-credentials. Семантика лестницы сохранена (safe default «все unknown = одна группа», запрет вычислять project из ключа, разделение только явным label'ом); шаги 1–2 остаются опциональным будущим расширением, не контрактом Wave A. Схема источников: label → `unknown` (2 ступени вместо 4).
- **Safe default:** все `unknown` credentials считаются **одной** группой (прод-факт Q1: одна endpoint-точка; перебор ключей одной группы усиливает burst). Разделение — только явным label'ом.
- Key health states (§11): `healthy / cooldown / auth_failed / quota_exhausted / provider_unavailable / disabled`. 401/403 → `auth_failed` (без ретраев как 429); auth-fail одного credential не отключает другие группы.
- DDL: runtime-состояние групп/credential'ов — additive-таблица SQLite `embedding_quota_state` (см. §8.1); сами credentials — конфиг, не БД.

### A.2 EmbeddingExecutor — единственный владелец retry (§6–§8, §21; T-4403)

- Один logical embedding request = одна orchestration policy. Иерархия сегодня (прод-факт Q2/Q3: 3×(3+2+2)=21) заменяется:

```text
EmbeddingExecutor(logical_request):
  knows: batch, provider, quota_group, credential list, attempt budget,
         rate-limit cooldown, priority(P0..P3)
  нижние слои (LLMClient._post): transport retry ONLY, ≤1 повтор на transient
  сеть, БЕЗ независимых key-каскадов и внешних ретрай-циклов
```

- Attempt budget (ADR-1028-7 D2): `≤ 4 попытки logical request` суммарно: 1 начальная + до 3 (только на retryable: 429-with-Retry-After → не считается попыткой «в лоб», а переносом по `next_allowed_at`; transport 5xx/timeout). Конкретный тайминги — Builder, но **ceiling логических HTTP-вызовов на батч зафиксирован тестом** (fixture §64: не 21).
- `summary_memory._embed_api`-обёртка (сегодня 3 внешних попыток) и embed-fallback каскад `llm_client` (сегодня 2 ключа × 2) — демонтируются как **самостоятельные** policy; их ответственность переезжает в Executor. OFF-паритет: kill-switch возвращает оба старых контура.
- 429 = scheduling signal: классификация (RPM / TPM / daily-project / spend / unknown) по status + Retry-After + provider error body (безопасные поля), без логирования содержимого запроса.
- Retry-After уважается: `sleep = min(provider_value, HARD_CEILING=300s)`; transport backoff (min(1·2ⁿ, 8)) остаётся **только** для транспортных ошибок. Отдельные механизмы (§9).

### A.3 Provider-agnostic adapter (§13–§16; T-4405)

```text
EmbeddingProviderAdapter:
  capabilities() / batch_limits() / token_limit_per_item() / embed_batch()
  quota_metadata() if available / classify_error(status, body, headers)
```

- Реализация **поверх** существующего LLMClient (сеть/clients переиспользуются, §13); Gemini Developer API — первый adapter; OpenAI-compatible — второй (тест §35: ≥2 провайдера в fixture).
- `gemini-embedding-001`: input ≤ 2048 token/item — сегментация до embed (lossless, stable parent ref), silent truncation запрещён (§14). Авто-переход на `-2` запрещён (§15).
- Batch-механизмы (§16, Q9): база — sync batch (`/embeddings` batch≤50 фактов, адаптивно A.5); async Batch API — gated-опция `EMBED_ASYNC_BATCH_ENABLED` (default OFF) для P2/P3, отдельная quota-группа, latency-insensitive; live-верификация контракта обязательна до включения.

### A.4 Global priority scheduler + reserve (§17–§18, §22–§23; T-4406, T-4407)

- Приоритеты: `P0 query-embed (online retrieval) → P1 live write/new fact → P2 small repair/backfill → P3 full rebuild`. Rebuild не имеет права съесть весь RPM/TPM.
- Reserve policy (§18, без магических процентов): **adaptive token-bucket** на квоту-группу — P0/P1 имеют гарантированный bucket; P3 потребляет только остаток (surplus bucket); при 429 на P0/P1 scheduler мгновенно замораживает P3 (preemption по next_allowed_at).
- Adaptive concurrency (§19): AIMD controller в developer bounds `EMBED_CONCURRENCY_MIN=1 / EMBED_CONCURRENCY_MAX` (env): cold start = 1; success streak → +1 (медленно); 429 → ÷2 (резко); group cooldown → 0 (pause). Batch size (§20): функция от item count, total tokens, per-item limit, observed latency, 429-частоты, provider batch limit — старт 32–50, границы env.
- Burst pressure vs quota unavailable (§21): 429 с Retry-After ≤ 60s при concurrency=1 → burst (просто ждать); 429 daily/spend-класса или Retry-After > 60s → group `exhausted` (не лечится concurrency).
- Multi-worker coordination (§22–§23): shared lease на deployment через существующую DB (`task_jobs` + `write_transaction`, REUSE mca-01 — Redis запрещён): (а) один active rebuild-job на index; (б) общий embedding-permit через quota-state таблицу → `graph_facts_vec` и `smart_archive` не стартуют full-rebuild одновременно (прод-факт Q6: сейчас стартуют в одну секунду); последовательность: сначала меньший/застрявший, затем второй. Process-local semaphores недостаточны, если появится второй процесс — lease в DB покрывает.

### A.5 Rebuild state machine + 429-policy (§24–§27; T-4408) — **AMEND ADR-1028-5 (AM-1)**

Машина состояний generation (расширяет D1/D2, не заменяет shadow/reuse):

```text
queued → building ⇄ paused_rate_limit | paused_provider → validating
                     ↓ (operator)                          ↓ ok
                  cancelled                    validation_failed | active
building/paused_* → failed (ТОЛЬКО terminal criteria §25)
```

- **429 / provider-quota pressure → `paused_rate_limit`** (не terminal FAILED — отмена ADR-1028-5 «honest terminal» для quota-класса; исправление Follow-up ASAP-3.2 п.1). Сохраняются: checkpoint (уже есть: `cp:graph_facts_vec:1`, `processed=5450`), progress, batch position, `next_allowed_at`, attempt history (в additive-колонках реестра / checkpoint-ref JSON).
- Terminal `FAILED` только: auth/config invalid; model/dim несовместимость; deterministic schema/DB error; bounded retry horizon исчерпан (env: `EMBED_RETRY_HORIZON_HOURS`, default 24h wall-clock pause-циклов); operator cancel; структурная validation-fail (§25).
- **Resume same generation (§27):** при `fingerprint unchanged` и `building/paused_*` — продолжение той же generation/checkpoint (не генерировать gen 2,3,4…). Прод-факт Q11: `cp:graph_facts_vec:1` уже хранит позицию — механика D2 остаётся, меняется только реакция на 429.
- Restart during pause (тест §68): job читает `next_allowed_at`, не сбрасывает generation, не дублирует работу.
- FTS serviceable во всех non-active состояниях (без изменений).

### A.6 KNN validation diagnostics + validation_failure сохранение (§28–§30; T-4409)

- Distinct reason codes вместо generic `knn_smoke_failed` (прод-факт Q10: пустой source неотличим от битого индекса): `knn_source_empty / knn_dim_mismatch{expected,actual} / knn_vec_extension_missing / knn_zero_results / knn_row_corrupt / knn_query_vector_failed / knn_index_schema_mismatch`. Диагностика без raw fact text: source_count, vector_count, expected/actual dim, gen fp, sqlite-vec availability, query-vector ok, executed, returned rows, distance sanity, exact stage.
- Полный build при непрошедшем smoke → `validation_failed`, **vectors сохраняются** для диагностики/repair; повторный full rebuild с нуля — только при доказанной invalid data (§29).
- Activation criteria §30 = 9 критериев ADR-1028-5 D3 (без изменений) + explicit `swap` транзакция; согласование с N-MCA07-1 activation API (не создавать второй).

### A.7 Log/UI hygiene + Analytics зоны A (§31–§33, §32, §62–§63; T-4410, T-4411)

- `paused_rate_limit` на запросах НЕ спамит WARNING: state-transition log + coalesced periodic status; FTS-fallback запросы = INFO/metrics (§31).
- Панель «Векторная память» (per index: статус по-русски, готовность %, next attempt, источник поиска) и «Embedding provider» (provider/model, credentials=N, независимых групп 1/2/неизвестно, текущая concurrency/batch, 429 за 10 мин) — §32; Embedding Run Inspector §62 (index, generation, provider/model, quota group, credential alias, progress, batch, concurrency, 429 count, cooldown, last successful batch, validation state, KNN smoke). Только aliases (§63).

---

## 2. Зона B — Cover Style production path (P0: стиль не применился)

Прод-диагноз (Q12–Q16): selection/персистенция/события/единый-pipeline-после-Legacy **работают**; фейл — `not_configured` (edit connection не задан, owner-гейт DC-4) + невидимость причины владельцу + generic reason_code + расход issue-номеров на фейлах. Зона B — production closure видимости и контрактов, не переписывание.

### B.1 Run snapshot + COVER_STYLE_SELECTION (§36–§37; T-4415)

- В начале cover publication фиксируется snapshot: `chat_id, selected_style_id, style_revision, selection_source(chat|global|none), enabled, pipeline_mode` — единая точка резолва style id (сегодня резолв в одном месте — сохранить; запрет трёх разных резолвов — контракт).
- Новый event `COVER_STYLE_SELECTION` (R17-safe) до base generation/style edit; если выбран `medved_press` — видно до image API. Расширение `mca_events.py:REASON_CODES`, не новый словарь.

### B.2 Единый pipeline для всех outcomes + ladder (§38–§39; T-4416)

- Publication concern: один pipeline для Hybrid L2 success / fallback package / Level-3 Legacy / manual / scheduled (прод-факт Q16: Legacy уже проходит — контракт фиксируется regression-тестом §39: `medved_press → force Legacy → style stage invoked`).
- Ladder: base+style → styled; style fail → base publish; base fail → Rich без cover; Rich fail → plain. Provenance обязателен при всех исходах (§44): `styled | base_fallback | no_cover`.

### B.3 Resolver unification test↔prod (§40–§41; T-4417, T-4418)

- «Протестировать стиль» и production совпадают по: profile load, connection resolution, model, capability check, reference load, prompt compiler, execution adapter (различия только: issue assignment, provenance, Summary-derived brief, side effects). При касании тест-контура — закрыть хвост L-ASAP31-4 (budget в dry-run `summary_test_run.py`).
- Profile diagnostics §41: полный чек-лист полей (profile_id/revision/enabled/pipeline_mode/connection/provider/model/capability image_edit/reference count/file readable/instruction/counter) — без секретов.
- Capability `image_edit` реален: для configured Qwen-connection — доказательство реальным test call (§47); «не умеет редактировать» — явный UI-статус, не видимость стиля.

### B.4 Reason codes + видимый fail-open + provenance (§42–§46; T-4419)

- Каждый ранний выход — отдельный reason: `no_style / profile_missing / disabled / edit_unsupported / connection_missing / reference_missing / capability_unknown / not_configured` (последний — уже в коде `cover_style_edit.py:212`; прод-кейс Q14 — Raise видимости: mca_events `reason_code` перестаёт схлопывать в `style_failed`, человекочитаемый перевод в Analytics).
- Fail-open остаётся (публикация не ломается), но виден: run detail «Обложка: … Обработка стилем — не выполнена. Причина: …» (§43).
- Reference integrity (§45): DB-row/file/MIME/readable/включён в request; метрики `reference_count / reference_bytes_total` без контента. Прод-факт: `reference_count=1` уже логируется — расширить контрактом целостности.
- Prompt compilation diagnostics (§46): instruction/brief chars, issue text present, references count, compiled chars, limit source, dropped sections (бренд-инструкция, выброшенная по cap — видна).

### B.5 Хвосты при касании (reuse-inventory §4)

- L-EXTRA-6 (`TaskJobStore.save_checkpoint` перезаписывает payload) и L-EXTRA-7 (`cover_job_key` из UUID → стабильный run_id для e2e-resume) — закрываются в зоне B: coalesce/job key от `run_id` (связка с E.1 run trace), checkpoint-payload — merge, не overwrite.
- `update_reference` rowcount→200 — при касании Registry.
- Issue counter не увеличивается на pre-execution конфигурационных фейлах (`not_configured/edit_unsupported/connection_missing`) — расход только на реальные submissions (прод-факт Q15: 1→2→3 на фейлах).

---

## 3. Зона C — Summary full-window (P0: 688→307 молча)

### C.1 `too_many_facts` → capacity guard (§51–§52, §50.36; T-4422)

- До model call: L1 planning estimate (source size, message count, reply density, expected topics/facts, output reserve) → при высокой плотности **заранее** больше chunks (semantic sharding). Прод-кейс Q17 (chunks=1 на 688 сообщений, tokens_in=46118) — planning обязан был дать >1 chunk.
- Dense thread >30 полезных фактов: sharding topic / split semantic subthread / reduce duplicates / allocate budget **до** валидации; `MAX_FACTS_PER_THREAD=30`/`MAX_FACTS_TOTAL=1000` остаются ceiling'ами структуры, но нормальный плотный chat не invalid (§50.36). После merge — reduction (`summary_semantic_reduction`, REUSE D8) приводит пакет к бюджету L2 без потери major topics.
- Invalid остаётся валидным исходом только для структурно битых ответов (bad type/unknown field/unknown id — fail-soft §50.35 сохраняется).

### C.2 Quote-контур: 5 reason codes + repair (§53–§54, §50.20; T-4423)

- Разбить `quote_attribution` на: `quote_text_not_found / quote_speaker_unresolved / quote_speaker_mismatch / quote_source_ambiguous / quote_attribution_repaired` (umbrella-код остаётся в логах для совместимости; Analytics показывает подпричину).
- Фикс бага §50.20 (код-факт `summary_l2_writer.py:722-731`): `quote found + speaker доказан → valid; quote found + speaker не доказан → needs_fix (repair: снять имя/кавычки, не текст); quote not found → paraphrase/de-quote`. Именные цитаты как класс не запрещаются.
- Repair pipeline §53.2: extract → resolve против FactPackage/SourceRefs → validate speaker → deterministic safe repair → revalidate → только потом решение о Legacy. Допустимые repairs: de-quote в пересказ; drop speaker-name при известном факте; удалить только недоказуемую формулировку, сохранив событие; direct→indirect speech. Запрещены: invent text/speaker, смена смысла, скрытие contradiction, тихий drop куска статьи.
- Контракт один с MCA-22 D3 Quote Resolver (conflict-audit §6): Summary-локальная проверка переиспользует/согласуется с лестницей (text/speaker/source), второй resolver не создаётся; где лестница не покрывает L2-случаи — extension, не fork.
- Attribution не ослабляется (§54): неподтверждённая прямая речь не публикуется никогда.
- Метрики: `quotes_total / verified / repaired / removed / failure_reason` (safe).

### C.3 Legacy full-window (§55–§57; T-4424)

- Убрать silent XML hard stop (`summary_xml.py:72-79`, прод: 307/688). Вариант (минимально рискованный, выбран по §56): **reuse full-window semantic package** — Legacy получает тот же hierarchical-reduced пакет, что и L2 (или, при его отсутствии, chunked XML + safe hierarchical reduction перед генерацией). Плоский `<chat_history>` остаётся только для малых окон (≤ cap — поведение бит-в-бит).
- Coverage: Legacy target `source_coverage=100%`; если реально не может — run помечается `degraded coverage` и это видно (не молча) (§57).
- `MAX_SUMMARY_PARTS` не трогается (§58) — только выходные Telegram-части.

### C.4 Coverage-метрики source window (§50.37; T-4425)

`source_messages_total / considered / dropped_reason×` (edits, duplicates, deleted, service msgs, ordering/reply integrity) — каждая потеря видима в coverage metrics (числа, R17-safe). Паритет §58 — guard-тест.

---

## 4. Зона D — Hybrid L2 Writer/Reviewer (bounded revision)

### D.1 Prompt migration prose-first (§50.3–§50.6; T-4428)

- Удалить из активного L2-промпта запрет прямых цитат; вставить: основной формат — связный прозаический рассказ; косвенная речь — default; цитаты разрешены, редкие, осмысленные, с доказанным source+speaker; статья ≠ список реплик; narrative continuity (событие → реакция → развитие → поворот); нормальная русская грамматика/пунктуация/абзацы; без канцелярита и Direct-lowercase; голос бота (сарказм/мат/ирония) сохраняется; стилистический комментарий ≠ новый факт; «видимая действительность» окна — первая истина; modality (вопросы/гипотезы/шутки) не инвертируется в факты.
- Механика: код + эталон промпта + тесты одним коммитом (правило project.md); старый промпт в эталоне помечен superseded (ADR-1028-7 D4); Legacy-промпт не меняется (его OFF-паритет).

### D.2 Evidence-трассировка + roster + relations (§50.7–§50.9; T-4429)

- Paragraph schema: `evidence_message_ids[]` (реюз существующих стабильных message-id, Q28) — internal metadata, не публикуется; только refs из переданного пакета; invented → validation error (id_space-проверка уже существует); несколько refs на абзац и shared evidence разрешены. Если FactPackage уже даёт достаточные refs — нового schema не вводить (§50.7 — проверка Builder'ом; ожидаем: достаточно).
- Participant roster (§50.8): `author_id, display_name, resolved aliases` — Writer не выдумывает имена; дубли display-name различаются по ID; user-facing текст без тех-ID.
- Relations (§50.9): fragment'ы пакета получают `kind: msg|reply|forward|quote` (прод-факт Q35: сейчас теряются); правила: forward ≠ слова переславшего; reply ≠ согласие/авторство; quoted ≠ слова цитирующего; ближнее имя ≠ proof speaker.

### D.3 Deterministic Validator ДО Reviewer (§50.18–§50.20; T-4430)

Порядок обязателен: JSON/schema, unknown fields, invalid IDs, paragraph structure, evidence-ref existence, emphasis spans, technical length, exact quote lookup, deterministic speaker/source mismatch, raw service IDs в user text. Mechanical formatting repair (кавычки/тире/whitespace/invalid span/Markdown escape/RichMessage-safe) — кодом, без LLM (§50.19). Semantic Reviewer не тратится на доказуемое кодом.

### D.4 L2 Semantic Reviewer (§50.10–§50.17, §50.26–§50.28; T-4431)

- Отдельный Review stage после deterministic validation. Вход: FactPackage, roster, evidence index, draft, deterministic findings. Выход — только structured verdict: `status: approved|needs_fixes|unusable` + findings `{code, severity, paragraph_index, evidence_refs, instruction}`. Новую статью не пишет.
- Не источник истины (§50.11): finding валиден только с refs ⊆ package (или deterministic rule); invalid findings отбрасываются; допустимые вердикты по спикеру: подтверждён/не подтверждён/противоречие/неоднозначность/claim не найден; unknown > hallucinated correction.
- Минимальный набор codes (§50.12): unsupported_claim, wrong_person_attribution, quote_text_not_found, quote_speaker_unresolved, quote_speaker_mismatch, quote_source_ambiguous, forward_attribution_error, reply_attribution_error, unsupported_number, timeline_inconsistency, contradiction_with_package, invented_name, duplicate_event, major_topic_omitted, factual_overstatement.
- Style vs fact (§50.26): мат/сарказм/ирония не бракуются; брак — только создаваемое проверяемое событие/утверждение (операционализация Q34: modality + конкретика actor/action/time/числа + обязательные refs).
- Commentary markers пользователю не видны (§50.27).
- Model slot (§50.28): Reviewer наследует L2 model/provider; developer override — только если слот-архитектура позволяет чисто; новый config key — с безопасным default.

### D.5 Bounded Revision ×2 (§50.1–§50.2, §50.22–§50.25; T-4432) — **SUPERSEDE (ADR-1028-7 D3)**

- Поток: Draft → Review → (NEEDS_FIXES) → Revision #1 → Validate+Review → (NEEDS_FIXES, progress ok) → Revision #2 → Final Review → APPROVED | LEGACY. После второй итерации autonomous-циклов нет.
- Revision input: original draft + FactPackage + конкретные findings + разрешённый evidence set. Инструкция §50.22 (исправить только необходимое; корректные абзацы сохранить; без новых фактов/имён/чисел/цитат).
- Patch-контракт (§50.23, выбор обоснован в ADR-1028-7 D5, ответ Q30): `replace_paragraphs[{index, text, evidence_refs}]` — primary; full-document revision — escape-hatch при findings>50% абзацев или дважды невалидном патче (с preserve-инструкцией + regression tests).
- Progress criterion (§50.25): blocking findings уменьшились → Revision #2 допустима; иначе — сразу safe fallback (без бесконечного repair).

### D.6 FactPackage proof-of-material + reduction (§50.30–§50.32; T-4433)

- До Writer доказывается, что пакет не потерял существенный material (source count, topics, chronology, fragments, author/reply metadata, evidence refs, dedupe/reduction, serialization budget). `L1_FALLBACK_PACKAGE fragments=30 chronology=688` ≠ полноценный semantic package (прод-факт) — статус `degraded_package` виден.
- Truncation не «ножницами»: hierarchical semantic reduction (`summary_semantic_reduction`, REUSE) с сохранением major topics / unique events / attribution anchors / chronology anchors / evidence refs (§50.31).
- Coverage map (§50.32): `source_messages_total/considered, major_topics_total/represented, unique_events_total/represented` — в Analytics. При касании — развести семантику `FACT_PACKAGE_TRUNCATED` (хвост ASAP-3.1 п.5): per-topic cap vs бюджетный потолок — один контракт с C.1.

### D.7 Chunk boundary + L1 merge (§50.33–§50.34; T-4434)

Overlap/reply-chain preservation между chunks (вопрос в A — ответ в B не теряется); после merge: semantic-dedupe, объединение evidence, без уничтожения уникальных фактов, many-to-many membership. Fail-soft unknown/malformed L1 IDs (§50.35) — без изменений.

### D.8 Факто-сохраняющий набор (§50.39–§50.47; T-4435)

Длинное сообщение: content-safe segmentation + stable parent ref + reassembly (автор/время/reply/identity сохраняются). Forwarded: `forward sender ≠ content author` (§50.40). Вопросы ≠ assertions (§50.41). Jokes/ирония/гиперболы ≠ factual events (§50.42, reason `factual_overstatement/modality_lost`). Имена/aliases: identity по stable author_id; display names для prose; смена имени в окне ≠ два человека; same/similar names — по ID, без склейки строк (§50.43–§50.44). Внешняя реальность не «допроверяется» (§50.45). Title — factual surface тоже (§50.46). Финал «главный шиз»: участник существует в roster и связан со статьёй (§50.47).

### D.9 Publication-контур (§50.48–§50.56; T-4436)

- Emphasis span error → span drop/repair, текст сохраняется; никогда «невалидная жирность → Legacy» (§50.48).
- Formatter failure ≠ перегенерация: approved prose сохраняется → safe plain formatter → plain Telegram (§50.49).
- «Читать дальше»: длинная статья → body под катом, компактный preview (§50.50).
- Idempotency: network timeout после отправки не создаёт дубль статьи; reconcile результата до retry; approved текст не меняется при delivery retry (§50.51).
- Publication ladder §50.52: approved → Base Cover → optional Style Edit → Rich Publish; style fail → base Rich; base fail → Rich без cover; Rich fail → plain approved (не Legacy!); Hybrid fundamentally unusable → Legacy; Legacy Rich fail → Legacy plain. Cover/formatter-ошибки НЕ перескакивают в Legacy (ответ Q37).
- Immutable stage history (§50.53, прод-факт Q36: `summary_generator.py:840-841`): разделить `publication_status` / `pipeline_health` / `stage_events[]`; успешный Legacy никогда не стирает `L2 rejected → Legacy used`.
- Append-only stage events (§50.54) — schema Q24.
- Legacy качество (§50.56): 100% coverage; без обрубка первых N символов; авторы не теряются; forward ≠ claim; без пустого/мета-текста.

### D.10 Metrics + golden scenarios (§50.58, §50.63, §75; T-4437)

- Метрики: `l2_first_pass_approved, l2_review_findings_total, l2_revision_count, l2_revision_fixed_count, l2_revision_new_findings, l2_final_approved, l2_legacy_after_review` + агрегаты 24h/7d.
- Golden fixtures A–M (13): reply conflict; forwarded news; valid direct quote; wrong-speaker quote → Revision; unsupported number; question; sarcasm; same names; parallel topics; 31+ facts thread (sharding, не invalid); 600–700+ messages (coverage 100%); major topic omission → Revision; first-pass approved без лишнего rewrite. Плюс quote-repair regression §75.

---

## 5. Зона E — Pipeline Analytics (Run Inspector)

### E.1 Normalized stage events (§60, §61.11–§61.12; T-4439, T-4440)

- Единая stage-record схема (Q24) поверх mca-17a (`mca_events`/`mca_pipeline_runs`) — вторая «аналитика с собственной истиной» запрещена (§61.11). Human-log и события из одного structured source (§61.12 — guard-тест T-4445: запрет парсинга логов на пути данных).
- Сквозной trace по `run_id`: `SUMMARY_START → SOURCE_WINDOW → L1… → L2… → LEGACY_FALLBACK? → COVER_STYLE_SELECTION → COVER_BASE… → COVER_STYLE… → RICH_PUBLISH… → SUMMARY_DONE` (§60). Существующие события маппятся адаптером, новых дублей нет; новые reason codes — в `mca_events.py:REASON_CODES`.
- Пайплайн-карта узлов (§61.1): Источник → HYBRID (L1/L2/Revision) → ТЕКСТ → ОБЛОЖКА (Base/Style branch независимо от Text branch, §61.8) → ИТОГ; семантика статусов ✓/⚠/✕/○/… (§61.2, цвет не единственный носитель), пояснения 1–3 строки + human-переводы причин (§61.3: `too_many_facts`, `quote_speaker_mismatch`, `rate_limit`, `reference_missing` — словарь переводов).

### E.2 Run Inspector + агрегаты (§61.4–§61.10; T-4441, T-4443, T-4444)

- Режимы: Последний запуск / 24ч / 7 дней — один виджет, одни данные (§61.4). Aggregate cards: success/fallback/failure rate, median/p95 latency, top-3 failure reasons (§61.5).
- Coverage first-class (§61.6, Q25): health = publication_status × source_coverage; «RichMessage опубликован + Coverage 44.6% = degraded». Repair ≠ Fallback ≠ Failure — разные термины/статусы (§61.7).
- Drill-down по run_id (§61.9): timestamps, provider/model, attempts, budget actual/theoretical, counts, coverage, style selection/revision, assets, publication, message id — без keys/prompts/reasoning/raw chat. Список runs (§61.10) с бейджами.
- Health badge — только Здоровый/С деградацией/Не завершён (без opaque score, §61.13). Mobile — вертикальный timeline (§61.14). Live updating — polling/существующий механизм (§61.15).
- Acceptance-сценарии §61.16 A–D (healthy / L2→Legacy / style failure / coverage-fixture не healthy) — Browser Use + Playwright desktop+mobile (T-4446).

### E.3 Embedding-панели (зона A.7) и Cover run state — те же structured events; §76 (embedding status/quota groups/rebuild progress/cooldown/Inspector/Cover state, mobile+desktop, developer details collapsible).

---

## 6. Матрица «spec-раздел → T-задачи» (T-4400+, tasks.md)

| Spec-раздел | Задачи | Ключевые требования (R4) |
|---|---|---|
| A.1 credentials/quota groups | T-4402 | R4-A-001/002/003/010 |
| A.2 EmbeddingExecutor / 429-конвейер | T-4403, T-4404 | R4-A-004…009 |
| A.3 provider adapter | T-4405 | R4-A-011/012/013/014 |
| A.4 scheduler P0–P3 + lease | T-4406, T-4407 | R4-A-015…021 |
| A.5 state machine + AM-1 pause/resume | T-4408 | R4-A-022/023/024/025 |
| A.6 KNN diagnostics + activation | T-4409 | R4-A-026/027/028 |
| A.7 log hygiene + панели | T-4410, T-4411 | R4-A-029/030/031/034/035 |
| A-тесты (§64–§69, §35) + gate | T-4412, T-4413 | R4-A-033/036…041 |
| B.1 snapshot + SELECTION event | T-4415 | R4-B-001/002 |
| B.2 единый pipeline + ladder | T-4416 | R4-B-003/004 |
| B.3 resolver unification + §41/§45–§47 | T-4417, T-4418 | R4-B-005/006/010/011/012 |
| B.4 reason codes + provenance | T-4419 | R4-B-007/008/009 |
| B-тесты §70–§73 | T-4420 | R4-B-015…018 |
| C.1 too_many_facts guard | T-4422 | R4-C-001/002, R4-D-036 |
| C.2 quote reason codes + repair | T-4423 | R4-C-003…006, R4-D-020 |
| C.3 Legacy full-window | T-4424 | R4-C-007/008/009 |
| C.4 coverage-метрики + §58 паритет | T-4425 | R4-C-009/010, R4-D-037 |
| C-тест §74 | T-4426 | R4-C-012 |
| D.1 prompt migration | T-4428 | R4-D-003…006 |
| D.2 evidence + roster + relations | T-4429 | R4-D-007/008/009 |
| D.3 deterministic validator | T-4430 | R4-D-018/019 |
| D.4 semantic reviewer | T-4431 | R4-D-010/011/012/026/027/028 |
| D.5 revision ×2 + patch | T-4432 | R4-D-022/024/025 |
| D.6 FactPackage coverage/reduction | T-4433 | R4-D-030/031/032 |
| D.7 chunk boundary + merge | T-4434 | R4-D-033/034 |
| D.8 факто-сохранение | T-4435 | R4-D-039…047 |
| D.9 publication-контур | T-4436 | R4-D-048…056 |
| D.10 metrics + golden A–M | T-4437 | R4-D-058/063/066 |
| D-gate | T-4438 | §83 semantic 21 пункт |
| E.1 stage events + trace | T-4439, T-4440 | R4-E-001/013/014 |
| E.2 Inspector + карта + coverage | T-4441–T-4444 | R4-E-002…012/015…017 |
| E-guard + Browser suite | T-4445, T-4446 | R4-E-014/018/019 |
| Production acceptance | T-4447–T-4449, T-4450, T-4451, T-4452 | R4-A-032/041, R4-B-013/014/019, R4-C-011/013, R4-E-020, R4-G-009/010/011 |

ARCH-задачи данного Step 2: T-4401 (зона A — закрыт этим spec+ADR), T-4414 (зона B — закрыт §2), T-4421 (зона C — закрыт §3; quote-контракт C.2 един для C/D), T-4427 (зона D ADR — закрыт adr-1028-7), T-4439 (E.1 — закрыт §5).

---

## 7. DDL delta (полный список)

| # | Store | Изменение | Тип | Обратимость |
|---|---|---|---|---|
| 1 | SQLite `user_version 22→23` | `embedding_quota_state` (quota_group_id PK, state, next_allowed_at, note, updated_at) | additive CREATE TABLE IF NOT EXISTS | DROP безопасен |
| 2 | SQLite | `mca_embedding_index_generations` + `pause_reason TEXT NULL, next_allowed_at INTEGER NULL, attempts_total INTEGER NOT NULL DEFAULT 0` | additive ALTER ADD COLUMN | NULL/default — старый код совместим |
| 3 | SQLite | KNN/attempt diagnostics — в `task_jobs` payload/checkpoint (REUSE, без DDL) | — | — |
| 4 | PostgreSQL | **no-op** (credential labels — существующие config/KV; cover_* не трогаем) | — | — |
| 5 | Summary/Cover/Analytics | **Δ DDL = 0** (stage events — существующие mca_events/mca_pipeline_runs) | — | — |

Идемпотентность: миграция повторно безопасна; на чистой БД — в составе штатного DDL. Бронь v20-истории нерелевантна (прод уже v22; v23 — следующая свободная).

## 8. Kill-switches / rollback

### 8.1 Правило

env-only (через config hot-get как существующие), default **ON** (фичи активны после деплоя), `false` → **bit-identical legacy path** (проверяется parity-тестом каждой зоны).

### 8.2 Список

| Флаг | Зона | OFF-поведение (legacy) |
|---|---|---|
| `EMBED_CONTROL_PLANE_ENABLED` | A master | прежний embed-каскад llm_client+summary_memory (21-аттемпный), прежний lifecycle |
| `EMBED_QUOTA_GROUP_COOLDOWN_ENABLED` | A.1/A.2 | нет group cooldown (перебор ключей как сейчас) |
| `EMBED_PRIORITY_SCHEDULER_ENABLED` | A.4 | rebuild без приоритетов/reserve (как сейчас) |
| `EMBED_ADAPTIVE_CONCURRENCY_ENABLED` | A.4 | статические GRAPHRAG_REBUILD_BATCH/SLEEP |
| `EMBED_ASYNC_BATCH_ENABLED` | A.3 | async Batch API выключен (default OFF — единственный default-OFF) |
| `SUMMARY_L1_CAPACITY_GUARD_ENABLED` | C.1 | too_many_facts → invalid → fallback package (как сейчас) |
| `SUMMARY_QUOTE_REPAIR_ENABLED` | C.2 | прежний validator-матрица (§50.20 баг живёт) |
| `SUMMARY_LEGACY_FULL_WINDOW_ENABLED` | C.3 | XML 50k hard stop (как сейчас) |
| `SUMMARY_L2_REVIEW_ENABLED` | D master | L2 без Reviewer/Revision: invalid → Legacy немедленно (как сейчас) |
| `SUMMARY_REVISION_PATCH_ENABLED` | D.5 | revision полным документом (если master ON) |
| `COVER_STYLE_SNAPSHOT_ENABLED` | B.1 | без snapshot/SELECTION event (events COVER_* остаются как есть) |
| `SUMMARY_PIPELINE_EVENTS_ENABLED` | E | Run Inspector из state-проекций (без stage-событий) |

### 8.3 Rollback-матрица

| Сценарий | Действие |
|---|---|
| Деградация зоны A после деплоя | `EMBED_CONTROL_PLANE_ENABLED=false` + рестарт → прежний контур; данные (generations/checkpoints/quota-state) не разрушаются — additive |
| Деградация Summary-качества | `SUMMARY_L2_REVIEW_ENABLED=false` (revision off) или точечно `SUMMARY_QUOTE_REPAIR_ENABLED=false` |
| Деградация Legacy | `SUMMARY_LEGACY_FULL_WINDOW_ENABLED=false` → прежний XML-cap путь |
| Деградация Cover | `COVER_STYLE_SNAPSHOT_ENABLED=false` (pipeline D14/hotfix-поведение сохранён) |
| Полный откат | cold revert деплой-коммита; additive DDL остаётся (совместим со старым кодом: новые колонки NULL/default, новая таблица не читается старым кодом) |
| Миграция | откат миграции не требуется для revert; форвард-фикс — только аддитивный |

## 9. Acceptance-привязки (не дублирует tasks.md — только якоря)

- Embeddings: §77 (9 пунктов) → T-4447; тесты §64–§69, §35 → T-4412; ветка evidence §34 (scheduler-proof vs full ACTIVE) — выбор фиксируется на T-4447 по факту реального quota (риск-строка tasks.md).
- Medved Press: §48 (11 пунктов) + §49 + §78 → T-4448 (owner-гейт DC-4: прод-факт Q14 — connection отсутствует).
- Summary full window: §79 + §59 → T-4449 (окно 600–700+, coverage 100%).
- Reviewer gates: §83 (14 runtime + 21 semantic) → T-4413/T-4438/T-4450; no-false-acceptance §84 — в формулировках отчёта запрещены «GraphRAG fixed» при building→FTS-only и т.п.
