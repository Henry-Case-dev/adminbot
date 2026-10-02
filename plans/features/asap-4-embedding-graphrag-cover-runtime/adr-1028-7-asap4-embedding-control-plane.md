# ADR-1028-7 — ASAP-4: Embedding Control Plane, Cover Style единый production path, Summary bounded revision

> **Фича:** `asap-4-embedding-graphrag-cover-runtime` (ASAP-4).
> **Задача-инициатор:** T-4401/T-4414/T-4421/T-4427/T-4439 [@Architect]; потребители — Builder/Reviewer/DevOps волн A–F (tasks.md, T-4402…T-4452).
> **Статус:** Accepted (02.10.2026).
> **Контекст:** прод 2.58.44 (`racknerd-f4e3456`, SQLite `user_version=22`, PG cover_style_* 6 таблиц); источник — `plans/current_task.md:16484–20843` (§0–§87, Q1–Q37), PM-пакет эпика, прод-факты `prod-facts.md` (journalctl/DB-выдержки 29.09–02.10.2026).
> **Связь:** AMEND → ADR-1028-5 (D2/D3-политика 429); SUPERSEDE → ASAP-2 ADR-решение «L2 correction retry НЕ вводится» + L2-промпт-запрет цитат; REUSE/EXTENSION → ADR-1028-6 D3 (Quote Resolver ladder); не трогает → ADR-1028-1…-4, -6 (остальные решения).

---

## AM-1. AMEND ADR-1028-5 (D2): 429 — пауза и resume, а не честный terminal failed

**Что меняется.** ADR-1028-5 D2/прод-валидация 2.58.40 зафиксировали политику «при исчерпании лимитов джоба честно переходит в терминальный `failed` (LLMRateLimitError)». Эксплуатация показала: для **quota-pressure класса** это не honesty, а дефект управления — генерация `graph_facts_vec` gen=1 терминально упала на 429 с сохранённым checkpoint (`cp:graph_facts_vec:1`, `processed=5450/15277`, job `7ed322e6…`, 2026-10-01 16:22:28 UTC) и без прогресса при каждом рестарте упирается в тот же 429 (прод-факт Q11).

**Решение.**
1. `429 RESOURCE_EXHAUSTED` (и provider-unavailable класс) на background rebuild → **`paused_rate_limit` / `paused_provider`** с сохранением checkpoint/progress/batch position/`next_allowed_at`/attempt history; job resumes после cooldown. Terminal `failed` — только по критериям §25 ТЗ (auth/config invalid; model/dim; deterministic schema/DB error; исчерпание bounded retry horizon `EMBED_RETRY_HORIZON_HOURS` (default 24h); operator cancel; структурная validation fail).
2. Resume same generation (§27 ТЗ): при неизменном fingerprint продолжается та же generation/checkpoint — новых generations 2,3,4… не плодим. Механика D2 (resumable на `task_jobs`, shadow-build D1, 9 критериев активации D3) **не меняется** — меняется только классификация quota-фейла.
3. Retry-After уважается с hard safety ceiling 300s; transport-backoff (cap 8s, `llm_client.py:661`) остаётся только транспортным механизмом и больше не участвует в quota-cooldown.

**Consequences.** Снимает Follow-up ASAP-3.2 п.1 (resume после honest-fail) правильным способом; OFF-паритет: `EMBED_CONTROL_PLANE_ENABLED=false` возвращает прежний «честный terminal» контур; существующие failed-джобы (обе gen=1) при деплое конвертируются в paused/resumable без DDL-разрушения (checkpoint-ref уже хранит позицию).

---

## D1. Embedding Control Plane: credentials pool, quota groups, EmbeddingExecutor

**RCA-основание (прод-факты Q1–Q8):** три Gemini key работают на один endpoint (`generativelanguage.googleapis.com/v1beta/openai/embeddings`); fallback#2 — «запасной аккаунт» (комментарий `settings.py:397-399`) → независимых групп ≥1, вероятно 2, machine-proof нет; один логический embed разворачивается в **21 HTTP-вызов** (`3 × (3+2+2)`: `summary_memory.py:282` + `llm_client.py:371-373,381/406-407`); Retry-After капится 8s (`llm_client.py:661`); оба rebuild-джоба стартуют в одну секунду (`created_at=1790807059`) и делят квоту с live-путём (`_save_graph_fact_embedding`, traceback 01.10 19:27); батч rebuild = 50 фактов/0.5s → ~100–120 RPM demand против free tier.

**Решение (детальные контракты — spec.md §1):**
1. `EmbeddingCredential`/`EmbeddingQuotaGroup` — pool вместо hardcode `primary+2`; лестница определения группы §5 (runtime metadata → connection metadata → developer label → unknown); unknown = одна общая группа (safe default), UI «Проект/квота: не определены»; ключи никогда не логируются.
2. **Единственный retry-owner — `EmbeddingExecutor`**: один logical request = одна orchestration policy (attempt budget ≤4, quota cooldown вне transport-backoff); вложенные каскады `summary_memory._embed_api` и `llm_client` embed-fallback демонтируются как самостоятельные policy.
3. 429 → классификация (RPM/TPM/daily/spend/unknown) → quota-group cooldown: при project-level 429 keys той же группы не бомбятся (продоказано: перебор одной группы только усиливает burst).
4. Global scheduler **P0 online query → P1 live write → P2 repair → P3 full rebuild** + adaptive token-bucket reserve для P0/P1 (без магических процентов); AIMD concurrency/batch в developer bounds; burst-pressure ≠ quota-unavailable.
5. Shared lease на deployment через существующую `task_jobs`/`write_transaction` (Redis запрещён): ≤1 active full-rebuild на deployment; `graph_facts_vec` и `smart_archive` не открывают race.
6. Provider-agnostic `EmbeddingProviderAdapter` поверх существующего LLMClient; `gemini-embedding-001` input ≤2048 token/item — сегментация до embed; авто-миграция на `gemini-embedding-2` запрещена; sync batch — база rebuild, async Batch API — gated-опция (`EMBED_ASYNC_BATCH_ENABLED`, default OFF) с обязательной live-верификацией контракта.
7. Δ SQLite DDL: additive `embedding_quota_state` + 3 nullable колонки в реестре поколений (spec §7); PG — no-op.

**Альтернативы, отклонённые:** «просто поднять паузы» — не лечит daily-quota и 21×amplification; «мигрировать на embedding-2» — меняет fingerprint/retrieval без решения control-plane (§15); «Redis limiter» — новая инфраструктура без необходимости (§22).

## D2. KNN/activation closure (прод-факт Q10/Q11)

`knn_smoke_failed` на `smart_archive` — smoke на пустом source (`smart_archive_facts=0`, processed=0). Решение: distinct reason codes (`knn_source_empty`, `knn_dim_mismatch`, `knn_vec_extension_missing`, `knn_zero_results`, `knn_row_corrupt`, `knn_query_vector_failed`, `knn_index_schema_mismatch`) без raw text; validation failure сохраняет vectors (`validation_failed`, не снос build); activation — 9 критериев D3 ADR-1028-5 + atomic swap, согласовано с N-MCA07-1 (второго activation API нет). FTS fail-soft и его механика неприкосновенны.

## D3. SUPERSEDE: «L2 correction retry НЕ вводится» → bounded semantic revision ×2

**Supersede-процедура §50.65 выполнена:**
1. Старое решение найдено и зафиксировано: ASAP-2 (ADR-класс mca-asap2-summary-pipeline) — «L2 unusable → сразу LEVEL-3 Legacy»; кодовый контракт «L2 correction retry НЕ вводится» (`summary_generator.py`, прод: `quote_attribution`/`invalid_paragraph` → немедленный Legacy, 4 случая 29.09–01.10).
2. Owner decision §50.1 явно заменяет его: Writer → Deterministic Validation → **Semantic Reviewer** → (NEEDS_FIXES) → Targeted Revision #1 → revalidate → Revision #2 → Final Review → APPROVED | Legacy. Максимум **две** semantic revision итерации; progress criterion §50.25 (findings не уменьшились → сразу safe fallback); autonomous multi-agent loops запрещены.
3. Bounded call budget (§50.57, ответ Q31): L2-стадия ≤ **6** логических LLM-вызовов (writer 1 + reviewer ≤3 + revision ≤2); happy = writer+reviewer = 2; rev1 = 4; rev2 = 6; Legacy-прямой = writer 1 + Legacy L; k = L1-чанки (planning §52); transport-ретраи в budget не входят. Нового 10–15-call каскада нет — потолок тестируется (golden M/J).
4. Rollback path: `SUMMARY_L2_REVIEW_ENABLED=false` → прежнее «invalid → Legacy немедленно» (бит-в-бит). ARCHITECTURE/эталоны: единственный канон — этот ADR; старый запрет в эталоне помечается superseded (без двух противоречащих канонов).
5. `review_degraded` (§50.29, обязательный ADR-пункт): при reviewer runtime-fail — deterministic validator остаётся источником safety; provider/model fallback по существующим правилам; publish как `review_degraded` допускается ТОЛЬКО при валидных evidence refs и пройденных deterministic checks (Architect-обоснование: deterministic-слой уже ловит структурные/ID/quote-lookup ошибки; потеря хорошего документа из-за reviewer-таймаута хуже контролируемой деградации); при недоказуемом factual support — Legacy. Решение фиксируется в stage-events как degraded, не success.

## D4. SUPERSEDE: L2 prompt prose-first / quote-allowed (§50.3–§50.6)

Старое правило «Прямые цитаты не приводи: пересказывай реплики своими словами» удалено из активного промпта (код+эталон+тесты одним коммитом). Новый канон Writer: основной формат — связная проза (косвенная речь default); прямые цитаты разрешены как редкий выразительный приём с доказанным source+speaker; статья ≠ transcript; narrative continuity; нормальная грамматика при сохранении голоса бота (сарказм/мат/ирония); «видимая действительность» окна — первая истина; modality (вопросы/гипотезы/шутки/гиперболы) не инвертируется в факты; стилистический комментарий не маскируется под событие. Legacy-промпт не меняется. Старый промпт в эталоне помечен superseded этим ADR.

## D5. Revision contract: paragraph-patch (основной) vs full-doc (escape-hatch) — §50.23

**Выбор: paragraph-level replacement** `{"replace_paragraphs":[{"index","text","evidence_refs"}]}` как основной контракт Revision; full-document revision допускается только если (а) findings покрывают >50% абзацев или (б) патч дважды провалил deterministic валидацию — с жёстким preserve-инструктажем и regression-тестами.

**Обоснование:**
1. Принцип §50.2 «сломалась плитка — не сносим дом»: патч гарантирует байт-в-байт сохранность нетронутых абзацев → устраняет главный риск full-rewrite «починил одну цитату → сломал три других факта» (пример владельца в §50.23).
2. Валидация механическая: index existence + те же paragraph-проверки на заменённых; semantic reviewer повторно смотрит только затронутые абзацы + дифф-контекст — дешевле и стабильнее.
3. Токен-бюджет предсказуем (fit в один call почти всегда), в отличие от full-doc на 688-message пакете.
4. Full-rewrite оставлен как escape-hatch осознанно: хронологические массовые перестановки (timeline_inconsistency по всему документу) патчем чинить опаснее, чем перегенерировать под preserve-инструкцией.
5. Kill-switch `SUMMARY_REVISION_PATCH_ENABLED` деградирует до full-doc (не до Legacy) — обе ветки bounded.

## D6. Cover Style — единый production pipeline (зоны B)

Прод-диагноз (Q12–Q16): selection/события/персистенция/вызов style после Legacy **работают** (3/3 runs: `COVER_STYLE_START medved_press rev=1`; Legacy-run `b1acbc39…` дошёл до style stage); фейл — `not_configured` (edit connection/model не заданы; владелец-гейт DC-4), 72 мс, image API не вызывался, reference не уходил; mca_events схлопнул причину в generic `style_failed`; issue counter сгорел на фейлах (1→2→3).

**Решения:**
1. Cover styling — publication concern, один pipeline для всех текстовых outcomes (Hybrid success / fallback package / Legacy / manual / scheduled). Regression §39 обязателен: `selected medved_press → force Legacy → style stage invoked`.
2. Run snapshot (§36): `chat_id/selected_style_id/style_revision/selection_source/enabled/pipeline_mode` фиксируются на старте cover publication — одна точка резолва; event `COVER_STYLE_SELECTION` до image API (R17-safe).
3. Видимый fail-open (§42–§44): каждый ранний выход — отдельный reason (`not_configured/edit_unsupported/connection_missing/reference_missing/capability_unknown/…`), человекочитаемая причина в run detail; provenance `styled|base_fallback|no_cover` обязателен при всех исходах.
4. Test↔prod resolver единый (§40) — различия только issue assignment/provenance/brief/side-effects; при касании закрывается L-ASAP31-4.
5. Issue counter расходуется только на реальные submissions (конфигурационные фейлы — до counter).
6. Capability `image_edit` — доказанная реальным test call для Qwen-connection; «модель не умеет редактировать» — явный статус, не видимость.
7. Хвосты при касании: L-EXTRA-6 (checkpoint merge вместо overwrite), L-EXTRA-7 (стабильный run_id в job key → e2e resume), rowcount-200. Реюз D14 ADR-1028-5 (connection model, PgDatabase-контракт) — без дублей Registry.

## D7. Summary zones C/D — сводные архитектурные решения

1. **L1 capacity guard** (§50.36/§51–§52): planning estimate до model call → semantic sharding; caps 30/1000 — structural ceiling, не semantic guillotine (прод-кейс Q17: chunks=1 на 688 сообщений → invalid → fallback-пакет); reduction через `summary_semantic_reduction` (REUSE D8 ADR-1028-5) до бюджета L2 без потери major topics.
2. **Quote-контур** (§53): 5 reason codes + локальный repair pipeline (de-quote/paraphrase/drop-speaker/direct→indirect) + revalidate до решения о Legacy; баг §50.20 (named quote reject при найденной цитате, прод-кейс Q18: `quote_unverified=0` при reject) устраняется контрактом «found+доказан → valid; found+не доказан → needs_fix; not found → paraphrase». Один контракт с MCA-22 D3 Quote Resolver ladder — extension, не fork (conflict-audit §6).
3. **Legacy full-window** (§55–§56): silent XML 50k hard stop удалён; минимально рискованный вариант — reuse full-window semantic package для Legacy (или chunked+reduction при его отсутствии); плоский `<chat_history>` — только для малых окон (бит-в-бит); `MAX_SUMMARY_PARTS` не трогается (§58); coverage 100% — target, отсутствие — явный degraded, не молча.
4. **Evidence trace** (§50.7): paragraph `evidence_message_ids[]` — реюз существующих stable message-id (id_space-проверка уже в коде); invented refs → validation error; refs internal, не публикуются. Participant roster + `kind: msg|reply|forward|quote` в пакете (прод-факт Q35: forward-метаданные сегодня теряются до L2).
5. **Deterministic validator до Reviewer** (§50.18); mechanical formatting repair без LLM (§50.19).
6. **Stage history immutable** (§50.53, прод-факт Q36: `summary_generator.py:840-841` стирает DEGRADED→OK после успешного Legacy): `publication_status` / `pipeline_health` / `stage_events[]` разделены; append-only; Run Inspector строится из structured events, не из логов (§61.12 — guard-тест).
7. **Delivery ≠ Legacy** (§50.49/§50.52, ответ Q37): formatter/Cover/delivery-фейлы не отправляют approved текст в Legacy (ladder: styled→base→no_cover→plain); Legacy — только для семантически непригодного текста после исчерпания repair/revision. Publication idempotency (§50.51) против дублей RichMessage.

## D8. Analytics (зона E)

Единая normalized stage-record схема поверх mca-17a (`mca_events`/`mca_pipeline_runs`) — Last Run и агрегаты 24h/7d из одного источника (§61.11/§61.12); reason codes — в существующий `mca_events.py:REASON_CODES`; run health = `publication_status × source_coverage` (degraded при coverage<100%, §61.6); repair/fallback/failure различаются семантически; cover branch видима независимо от text branch; embedding-панель — эволюция GraphRAG health (ADR-1028-5 D13), без нового корневого dashboard.

---

## Sanctions (сводка)

| Решение | SQLite DDL | PostgreSQL | Kill-switches (env-only) |
|---|---|---|---|
| AM-1 + D1 + D2 | v22→v23 additive: `embedding_quota_state`, +3 nullable колонки реестра | no-op | `EMBED_CONTROL_PLANE_ENABLED`, `EMBED_QUOTA_GROUP_COOLDOWN_ENABLED`, `EMBED_PRIORITY_SCHEDULER_ENABLED`, `EMBED_ADAPTIVE_CONCURRENCY_ENABLED`, `EMBED_ASYNC_BATCH_ENABLED` (default OFF) |
| D3/D4/D7 (Summary) | 0 | 0 | `SUMMARY_L2_REVIEW_ENABLED`, `SUMMARY_REVISION_PATCH_ENABLED`, `SUMMARY_QUOTE_REPAIR_ENABLED`, `SUMMARY_L1_CAPACITY_GUARD_ENABLED`, `SUMMARY_LEGACY_FULL_WINDOW_ENABLED` |
| D6 (Cover) | 0 | 0 | `COVER_STYLE_SNAPSHOT_ENABLED` |
| D8 (Analytics) | 0 | 0 | `SUMMARY_PIPELINE_EVENTS_ENABLED` |

Все default-ON (кроме `EMBED_ASYNC_BATCH_ENABLED`); OFF = bit-identical legacy (parity-тест каждой зоны). Rollback: soft (флаг+рестарт) или cold revert; additive DDL совместима со старым кодом (NULL/default, неиспользуемая таблица). Secrets: нигде (логи/events/UI/доки) нет значений ключей — только алиасы; R17-скан обязателен перед релизом.

## Consequences для Builder/Reviewer/DevOps

- **Builder** получает: контракты spec.md §1–§5, DDL-лист §7, флаги §8, budget D3.3, patch-схему D5, parity-требование OFF-веток.
- **Reviewer** (§83): 14 runtime + 21 semantic пункт; дополнительно — OFF-паритет каждой зоны, отсутствие второго resolver/pipeline/реестра, честность reason codes (никаких generic-схлопываний типа `style_failed`/`knn_smoke_failed`/`quote_attribution` для новых кодов).
- **DevOps**: live acceptance §77–§79; ветка evidence §34 (scheduler не падает, pause/resume, меньший slice → ACTIVE) допустима, если реальный project quota делает full-ACTIVE физически долгим — но хотя бы один реальный KNN path каждого index обязан быть проверен (§34); owner-гейты: DC-4 (edit connection) для §48/§78, платные вызовы.

## Supersede / Amend register (итог)

| Старое решение | Новый статус | Где |
|---|---|---|
| ADR-1028-5 D2: quota-исчерпание → честный terminal failed | **AMENDED** (AM-1): paused_rate_limit/resume | D3 ADR-1028-5 сохранён |
| ASAP-2: «L2 unusable → сразу Legacy» / «L2 correction retry НЕ вводится» | **SUPERSEDED** owner'ом (§50.1) | D3 этого ADR |
| ASAP-2 prompt: запрет прямых цитат | **SUPERSEDED** owner'ом (§50.3) | D4 этого ADR |
| ADR-1028-6 D3 Quote Resolver ladder | **REUSED/EXTENDED** (не superseded) | D7.2 |
| MAX_SUMMARY_PARTS, FTS fail-soft, ASAP-2.1 prefilter-удаление, fail-soft L1 IDs, gemini-embedding-001 | **ДЕЙСТВУЮТ без изменений** | spec §0.4 |
