# ADR-1028-7 — ASAP-4: Embedding Control Plane, Cover Style единый production path, Summary bounded revision

> **Фича:** `asap-4-embedding-graphrag-cover-runtime` (ASAP-4).
> **Задача-инициатор:** T-4401/T-4414/T-4421/T-4427/T-4439 [@Architect]; потребители — Builder/Reviewer/DevOps волн A–F (tasks.md, T-4402…T-4452).
> **Статус:** Accepted (02.10.2026); прод 2.58.45 VERIFIED — Accepted + prod-validated (ядро; owner live-приёмка T-4447–T-4449 PENDING — см. «Прод-валидация и история»).
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
| AMEND T-4502 (kind-parking + backoff) | 0 | 0 | `EMBED_QUOTA_KIND_PARKING_ENABLED`, `EMBED_RESUME_BACKOFF_ENABLED` |

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

---

## Прод-валидация и история (reconcile @Architect, 02.10.2026)

**История статуса:**

1. **02.10.2026 — Proposed (design):** AM-1 + D1–D8 утверждены в ADR; консистент-гейт с PM — решения включены в критерии `tasks.md`; Risk **R3** (прод-инциденты Q1–Q18 как RCA-основание, DDL v23, 12 kill-switches, новые публичные эндпоинты).
2. **02.10.2026 — Wave gates:** Wave A (Control Plane) round 1 NEEDS FIXES (2H/2M blocking) → round 2 **APPROVED (WAVE A)**; Wave D (Writer/Reviewer bounded revision) round 1 NEEDS FIXES (1M blocking) → round 2 **APPROVED (WAVE D)**.
3. **02.10.2026 — Final gate round 2 (T-4450, волны B/C/E + cross-wave + чек-лист владельца §83): `Approved for release`** (round 1 — NEEDS FIXES 1M/3L; round 2 — 0 blocking, **M-ASAP4-E1 RESOLVED** кодом: durable-канальные статусы rich/text + рестарт-паритет `review_degraded`; binding: HEAD `f04564b` + WTH `f62243b7…` + spec `ab9dec94…`; полный pytest detached **10773/2**, оба failed — pre-existing bounds round1026).
4. **02.10.2026 — Deploy — VERIFIED (2.58.45):** feat `9930fc6` (78 файлов, +14456/−348: 52 файла скоупа ревью + 26 релизного свипа версий) + docs `b5eaecd` + deploy-doc `c669c9d`; свип 2.58.44→2.58.45 санкционирован заданием (дрейф WTH ровно 3 манифест-файла — только version-pin ханки; 49/52 файлов скоупа байт-идентичны ревью-состоянию; пер-файловые пины round-2 дельты MATCH) — **Accepted + prod-validated (ядро)**; все решения AM-1/D1–D8 в силе, approval не инвалидирован; правки reconcile — docs-only.

**Прод-валидация 2.58.45 (evidence — `deployment.md` §5–§9):**

- **DDL v23 применена идемпотентно 10:18:26 UTC** с fail-closed guard'ом mca-14: авто-бэкап ДО DDL `pre_migration_20261002_101544.db` (read-back ok; старый pre_v22 ротирован disk_retention), `user_version=23`, `embedding_quota_state` + 3 nullable-колонки реестра (`pause_reason`/`next_allowed_at`/`attempts_total`); данные целы (smart_messages 1 990 358); PG no-op; рестарт один (10:14:16 UTC), health 200 / runtime 2.58.45.
- **AM-1 + D1 доказаны live:** `graphrag_rebuild` resume с checkpoint `cp:graph_facts_vec:1` (5500/frontier 6712) → при 429 **`paused_rate_limit`** + «checkpoint preserved» (cooldown ~19s) → **авто-resume** (`cooldown_expired`) — **НЕ failed**: ровно новая политика вместо терминального честного failed; v23-колонки пишутся (pause_reason=`rate_limit:quota_group`, attempts_total=14); lease-санити — дублей активных джоб нет, `embedding_rebuild_lease` без зависших.
- **Гейты прод:** kill-switches **11 ON + `EMBED_ASYNC_BATCH_ENABLED` OFF** (ровно дефолт, **Δenv=0**); ladder/parity **309 passed / 0 failed на прод-venv** (5 asap4 волновых файлов + `test_mca22_core_round1027`); каталог F8 488 CHECK OK Δ=0; новые эндпоинты `/api/analytics/pipeline/inspector`, `/api/analytics/pipeline/runs/{id}`, `/api/memory/embeddings` — **401 unauth** (admin-only RBAC жив); R17-скан чист; 0 посторонних ошибок пост-рестарт (фон 14×429 обработан control plane без traceback'ов).
- **Browser §61.16 A–D (T-4446, desktop 1280×800 + mobile 390×844, Playwright; API-фикстуры через реальный mca-17a-транспорт на temp-SQLite v23; прод-БД не загрязнялась): failures: 0** — A healthy / B L2→Legacy degraded с человечьей причиной / C style fail-open (base + причина, публикация ок) / D coverage 44.6% → не-healthy (coverage first-class); Run Inspector рендерится на обоих вьюпортах, mobile — без горизонтального скролла; 2 консоль-ошибки вне скоупа эпика (favicon 404, usage/summary 500 урезанного fake-PG стенда) — сценарии не затрагивают.
- **Границы приёмки (PENDING OWNER, no-false-acceptance):** live-приёмка **T-4447** (live embeddings: оба индекса → ACTIVE, live KNN; платные вызовы), **T-4448** (live Medved Press; precondition **DC-4** — edit connection/model за владельцем), **T-4449** (live full window 600–700+, coverage 100% на проде); SUMMARY_*/COVER_* эмиссия на прод-данных оживёт с первым реальным Summary-прогоном владельца; `EMBED_ASYNC_BATCH_ENABLED` остаётся OFF до live-верификации контракта Batch API. Детали хвостов — backlog Follow-up ASAP-4.

---

## AMEND 02.10.2026 (corrective pass T-4502): kind-aware quota parking + resume backoff

**Основание (прод-инцидент 2.58.45, RCA):** `plans/features/post-asap4-corrective-pass/rca-graphrag.md` — пул из 3 ключей резолвится в одну группу `unknown` (labels не заданы, safe default D1); провайдер отдаёт 429 класса **spend** (дневной бюджет) без Retry-After; kind не влиял на длительность cooldown → `next_allowed_at = now+20s` при суточном бюджете → вечный цикл «auto-resume → 1 реальный 429 → pause 20с» ≈3 попытки/мин, `attempts_total` 14→157/ч без прогресса checkpoint; публичный 429-счётчик задвоен повторным `record_rate_limit` в pause-конверсии.

**Решение (внутри D1/AM-1, полный контракт — `plans/features/post-asap4-corrective-pass/design-fix.md`):**
1. **Kind-aware parking**: spend/daily-exhausted без RA → `next_allowed_at` = конец суток UTC + margin (оценка reset, честно помечена `est=utc_day_end`, без фальшивой точности; RA при наличии уважается с ceiling 300s как в AM-1); rpm/tpm/rate — как сейчас. Существующие гейты §68 (`_ensure_job`, `_resume_later`) удерживают джобу в `paused_rate_limit` с checkpoint до `next_allowed_at`, рестарты включительно — 0 запросов в охлаждённую группу до срока.
2. **Нелинейный resume-backoff** (×2, cap 3600s, jitter ≤25%) с рестарт-персистентным счётчиком в `task_jobs.result_ref` (REUSE `_pause_bookkeeping`, ΔDDL=0); отмена при первом успешном батче; горизонт 24h (`EMBED_RETRY_HORIZON_HOURS`) без изменений — парковка расходует его, исчерпание → честный terminal `retry_horizon_exhausted`.
3. **Честная диагностика вырожденного пула**: панель/лог прямо репортят `rotation: none | group=unknown | keys=N` + hint на `EMBEDDING_QUOTA_GROUP_LABELS` / hot `keys.embedding_quota_group_labels` (подхват живьём); фейковая ротация не вводится, `_pick_credential` не меняется.
4. **Дедуп счётчика 429**: точка истины — `_on_error` (embedding_control_plane.py:1157); повторный `record_rate_limit` в graphrag_rebuild.py (pause-конверсия CoolingDown) удаляется.

**Границы:** ΔDDL 0 (task_jobs.result_ref + существующие v23-структуры); PG no-op; kill-switches env-only default-ON, OFF = бит-в-бит 2.58.45; R17. Альтернатива «просто поднять 20s→24h константой» отклонена: не различает kind, ломает honest RA для burst-классов. Ownership: T-4503 [@Builder] юнит-механика, T-4509 [@DevOps] прод-evidence (критерии — design-fix.md «Acceptance»).

**AMEND prod-валидация 2.58.46 (corrective pass, 02.10.2026 — evidence `plans/features/post-asap4-corrective-pass/deployment.md` §5):** механизм доказан на живом проде — после рестарта 13:36:04 UTC `graphrag_rebuild` resume **той же generation** (не пересоздана) → 1 реальный 429 spend → **парковка до конца суток UTC: `cooldown_s=37712`, `parked=1`** (D1), `429_last_10m=1` одинарный (D4, было задвоение), `quota_exhaust_streak=1` персистентен в `task_jobs.result_ref` (D2), панель честно репортит `rotation=none | group=unknown | keys=3` + hint `EMBEDDING_QUOTA_GROUP_LABELS` (D3); **0 повторных embed-запросов в исчерпанную группу за 10+ мин наблюдения** (до фикса: 298 BUILD_START/4ч, цикл ~20с); checkpoint продвинулся `last_id 7608→7640 / processed 6395→6427` и цел; generation/attempts не сброшены рестартом; kill-switches 2×ON Δenv=0; health 200/2.58.46, 0 ошибок, R17 чист. **NATURAL RESUME pending:** провайдерский reset spend-квоты ~конец суток UTC — resume с checkpoint произойдёт автоматически (mechanism-verified, exit FTS-only подтвердится живым прогоном). Owner-опции ротации: `EMBEDDING_QUOTA_GROUP_LABELS` (если ключи реально разных проектов — сейчас 1 группа) + опционально `EMBED_QUOTA_RESET_HORIZON_SECONDS`.
