# ADR-1027-7 — `mca-07-retrieval-context`: единый retrieval-контракт, типизированный reranker, embedding identity/fingerprint/поколения, EvidenceBundle §11.2 (in-memory), адаптивный бюджет, singleflight/HWM/CAS сводок и отключение прежнего ответного кеша — Δ DDL = v18, Δ каталога = 0, R2 (понижен с R3 решением Reviewer gate T-3857 итер.2)

- **Статус:** **✅ Accepted** (27.09.2026, T-3857) — повторный единый Reviewer gate **итер.2 = Approved** (Risk **R2**, понижен с R3); **MERGED** в `plans/ARCHITECTURE.md` **§99**. AMEND 27.09.2026 (T-3857, адъюдикация carry-over после rework B-MCA07-1/-2) **исполнен**: ADR переведён в Accepted фактом мержа §99; carry-over `M-MCA07-2`/`L-MCA07-5` санкционированы (см. «Санкции и вердикты» → AMEND).
- **Фича:** `mca-07-retrieval-context` (Wave 1, данные; потребитель `mca-03`/`mca-04a`; предпосылка `mca-09`/`mca-15`/`mca-16`/`mca-20`/`mca-10b`). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` v1.8 §11.1 (`:395–399`), §11.2 (`:407–416`), §11.3 (`:422–426`), §11.4 (`:432–434`); §2.3/§2.10/§3/§3.1/§4; §17.1–§17.3; §18; §19 A03/A04/A05/A06/A24; §22; R17/R18.
- **Baseline:** Reviewed-Commit `05bc870`; `APP_VERSION` 2.58.31; SQLite DDL **v17** (после `mca-04a`); каталог `473/430/448/102/100/21`; канон 12; pytest 9712/0 + JS 47/47.
- **Связано:** AMEND `services/summary_memory.py` (`_embed`/`_embed_cache_key`/`embedding_cache` identity + `rerank_rag_facts` типизированный + `get_window_messages`/`_build_running_summary` CAS), `services/direct_chat_service.py` (`_apply_context_budget` полный учёт + answer-cache политика), `services/database.py` (`upsert_running_summary` CAS + v18), `services/search_service.py::_rerank_results` (адаптер), `services/token_counter.py` (protected spans/метод оценки); REUSE `thread_chain`, `search_messages_fts`/`search_graph_facts_fts`, `lore_stories`/`lore_compiler_service`, `provenance.py` (`mca-04a`), `TaskSupervisor`/`task_jobs` (`mca-01`), `lore_cache.generation`, `emit_mca_event`/`mca_events` (`mca-13`), `MigrationStep` (`mca-14`); рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§11.1 требует комбинацию retrieval-каналов и поиск точной фразы/имени/даты; reranker возвращает **типизированный список ID**, валидный пустой список **не** превращается обратно во всех кандидатов, а ошибка формата/timeout — **отдельный статус** с явной политикой fallback; embedding cache key включает текст + provider/model + dimensions + preprocessing/version (+endpoint там, где меняет модель); один dimension не доказывает совместимость; индексы имеют fingerprint и поколение. §11.2 задаёт обязательные поля `EvidenceBundle` и требование использовать **один** bundle для решения/инструментов/синтеза/формулировки, при этом System2 после tool loop не должен получать только исходный вопрос + tool output, теряя адресата/ветку/ограничения. §11.3 требует считать **полный** запрос (system/developer/personality, user context, tools schemas, tool results, output reserve, служебный overhead), консервативную оценку с методом, адаптивный объём, сохранение отрицаний/ID/дат, запрет заведомо переполненного запроса и логирование размера/резерва/исключений. §11.4 требует singleflight/coalescing + high-watermark/CAS сводок, отдельной revision источников, отключения прежнего кеша по одному нормализованному query/chat/user для контекстных ответов при сохранении дедупликации Telegram update, повторной обработки «почему?» под другим родителем и ключа «иного кеша» с зависимыми версиями/родителем.

**Фактическое состояние baseline (сверено с рабочей веткой):** `rerank_rag_facts` (`summary_memory.py:2612–2646`) возвращает исходных кандидатов при ошибке и при пустом парсе; `_rerank_results` (`search_service.py:105–128`) — fail-open на текст. `_embed_cache_key` (`:294`) = `sha256(casefold+strip)`; `embedding_cache` (`database.py:1958–1961`) матчит по `dim` (`summary_memory.py:1418–1423`); vec-таблицы (`:93–117`) несут только `float[N]`, при смене размерности DROP+rebuild (`:1276–1283`), но смена модели при той же размерности оставляет старые векторы в обслуживании → смешивание. `upsert_running_summary` (`database.py:5842–5862`) — слепой UPSERT без high-watermark; `chat_summary_levels.msg_count_highwater` — прецедент. `direct_chat_service.py:1233–1256` — text-based `direct_dedup` replay. `_apply_context_budget` (`:2443–2594`) считает только блоки; `truncate_keep_header`/`truncate_to_tokens` не защищают отрицания/ID/даты. Единого bundle нет. Все разрывы присутствуют.

## Решения

**D1. Единый retrieval-контракт — обёртка над существующими каналами (комбинация).**
- **Выбрано:** одна точка `RetrievalRequest → RetrievalResult`; каналы: lexical/FTS+exact (REUSE `search_messages_fts`/`search_graph_facts_fts`/`search_archive_facts_fts`), vector (REUSE `smart_archive`/`graph_facts_vec` KNN, ограниченный активным поколением — D4), фильтры времени/участников (по `sent_at`/`author_id` `mca-03`), reply-граф (REUSE `thread_chain.collect_thread_chain`), эпизоды (REUSE `lore_stories`/`lore_compiler_service`). Кандидат несёт SourceRef-ссылку (`mca-04a`) + время, не копирует сырьё.
- **Обоснование:** §11.1 (`:395`) verbatim; GEN-R19 (не второй движок); GEN-R10 (память↔веб раздельно).
- **Альтернатива:** новый retrieval-движок — отклонено (запрет второй реализации; дублирование FTS/vec/цепочки). Слить память и веб в один канал — отклонено (GEN-R10).

**D2. Приоритет эпизодов для истории; сохранение точной фразы/имени/даты.**
- **Выбрано:** при историческом запросе — сначала эпизоды (`lore_stories`/компилятор-фасад), затем спуск к сообщениям при недостатке/неоднозначности; exact/FTS-канал всегда доступен (точная фраза), имя — через идентичность/алиасы (display-only, `mca-03`), дата/период — фильтр по событийному времени (`sent_at`), не по дате записи; короткие ответы не отбрасываются.
- **Обоснование:** §11.1 (`:395`); §7 MCA-03 (дата события ≠ дата импорта); A04.
- **Альтернатива:** всегда идти от сообщений — отклонено (требование «сначала эпизоды»); порог минимальной длины — отклонено (короткие reply значимы).

**D3. Типизированный reranker с отдельным статусом и явным fallback.**
- **Выбрано:** `RerankResult { status: ok|empty|invalid|timeout|error, selected: [{id, score}] }`; `ok`+empty → пусто (не все кандидаты); `invalid`/`timeout`/`error` → **отдельный статус** + детерминированный fallback = pre-rerank-порядок (retrieval score), bounded `top_k`, статус виден потребителю; порядок = оценке. Существующие `rerank_rag_facts`/`_rerank_results` приводятся к единому ядру как адаптеры (второй reranker запрещён); текущее «ошибка/пустой парс → исходные кандидаты» устраняется.
- **Обоснование:** §11.1 (`:397`) verbatim; A05; GEN-R19.
- **Альтернатива:** пустой/битый ответ → все кандидаты — отклонено (прямо запрещено, A05). Fallback = пусто при ошибке — отклонено (теряет значимый контекст; явная политика допускает bounded pre-rerank-порядок). Два разных reranker — отклонено (GEN-R19).

**D4. Embedding identity/fingerprint/поколения.**
- **Выбрано:** cache key = `H(identity_fingerprint \x00 casefold(strip(text)))`, `identity_fingerprint = sha256(provider|model|dims|preprocessing_version|endpoint_fingerprint)`; `endpoint_fingerprint` включается при непустом значении (консервативно — over-invalidation безопаснее under-invalidation); lookup **не** считает совпадение `dim` доказательством; legacy-строки вытесняются TTL/LRU. Индексы: durable реестр `mca_embedding_index_generations` (`fingerprint`/`generation`/`provider`/`model`/`dims`/`preprocessing_version`/`endpoint_fingerprint`/`status`); на старте текущий fingerprint сравнивается с активным поколением; mismatch → FTS-only (не смешивать), перестройка — `mca-04b`. AMEND `_embed`/`_embed_cache_key`/`embedding_cache`; NULLable identity-колонки кэша — аудит/детерминированный sweep.
- **Обоснование:** §11.1 (`:399`) verbatim; A06; §8.3 «сравнивать embeddings только внутри совместимого fingerprint; недоступный старый embedding model — сохранить старый индекс + лексические пути, перестройку — отдельным resumable job».
- **Альтернатива (Δ DDL=0):** fingerprint только in-memory/из DDL vec-таблицы — отклонено: после рестарта негде узнать модель, построившую сохранённые векторы → смешивание (A06 не держится). Смена ключа без реестра индекса — отклонено (не закрывает §11.1 «индексы имеют fingerprint и поколение»). Rebuild-таблица per-generation — избыточно (vec0 не изменяется; реестр достаточен).

**D5. EvidenceBundle §11.2 — in-memory, ссылки на SourceRef, derived `context_version`.**
- **Выбрано:** frozen dataclass с полным набором §11.2; **не** персистится как единая таблица (ссылается на `mca_source_refs`/`mca_evidence_links`/`smart_messages`); durable — только `context_version` + SourceRef-ссылки в событиях/decision-record; `excluded[]` несёт ссылку + `reason_code` + оценку. `context_version` — детерминированный fingerprint над зависимостями (schema bundle + revision текущего сообщения + `(SourceRef-id, revision)` выбранных + `summary_revision` + версии persona/config/policy + active generation при vector + версия retrieval-политики).
- **Обоснование:** §11.2 (`:407–416`, «не требуется дублировать весь архив на каждом этапе»); A04/A24; R17.
- **Альтернатива:** персистить bundle целиком — отклонено (дублирует архив, ретенция/риск утечки, противоречит §11.2). `context_version` отдельной таблицей — отклонено (derived; достаточно в событиях/decision-record).

**D6. Bundle↔Summary Hybrid/System2/verbalizer.**
- **Выбрано:** один bundle проходит decision→tools→synthesis(Summary Hybrid/System2)→verbalizer; Summary Hybrid — поставщик блоков (L1/L2, `resolve_context_tokens`/`resolve_chat_limit`/`safe_budget`), System2 после tool loop получает bundle (адресат/ветка/ограничения/current сохранены), а не только вопрос+tool output; полный архив не дублируется (ссылки); GEN-R21 (UI в БД не ходит).
- **Обоснование:** §11.2 (`:416`) verbatim; §3.1 (Summary Hybrid — исходная архитектура); GEN-R21.
- **Альтернатива:** раздельные контексты на стадиях (как сейчас) — отклонено (§11.2 «один согласованный bundle»). Новый параллельный контекст-сборщик — отклонено (GEN-R19).

**D7. Адаптивный бюджет — полный учёт payload.**
- **Выбрано:** учитывать system/developer/personality + user context + tools schemas + tool results + output reserve + служебный overhead с учётом реального API; при неизвестном tokenizer — консервативная оценка с запасом + логирование метода; адаптивный объём (нет лимита 6000/8); целые блоки → затем сжатие менее важных; protected spans (отрицание/ID/дата) не режутся по смыслу; при переполнении — суммирование с сохранением источников/доп. retrieval/уточнение; pre-flight запрет заведомо переполненного запроса; логировать размер/резерв/исключения/причину. AMEND `_apply_context_budget`+`token_counter`.
- **Обоснование:** §11.3 (`:422–426`) verbatim; A24; REUSE tokenizer Epic 2.
- **Альтернатива:** считать только блоки (как сейчас) — отклонено (не полный запрос; tools/system/tool results вне учёта). Фиксированный лимит 6000/8 — отклонено (прямо запрещено).

**D8. Сводки: singleflight/coalescing + high-watermark/CAS + source revision.**
- **Выбрано:** единая точка сводки (coalescing `TaskSupervisor` `task_jobs` и/или in-process singleflight, `mca-01`); `upsert_running_summary` → **CAS** по high-watermark (`window_end_ts`/`raw_count`; запись только если новый ≥ текущего); `summary_revision` (derived) участвует в `context_version`. REUSE `chat_summary_levels.msg_count_highwater`/`lore_cache.generation`. **Δ DDL для сводок не требуется.**
- **Обоснование:** §11.4 (`:432`) verbatim; A03; §5.2 (coalescing/singleflight — MCA-01).
- **Альтернатива:** in-memory lock без durable CAS — отклонено (не переживает несколько воркеров/рестарт). Новая таблица версий сводок — отклонено (существующих колонок достаточно; аддитивность/Δ DDL=0 по этой оси).

**D9. Ответный кеш — отключить text-replay, сохранить update-дедуп.**
- **Выбрано:** для контекстных ответов прежний кеш по одному нормализованному query/chat/user (`direct_dedup`) **не** используется; сохраняется идемпотентность одного Telegram update по идентичности сообщения (`chat_id, tg_message_id`, `mca-03`); повторное «почему?» под другим родителем — заново; «иной кеш» (опционально) — ключ включает зависимые версии + родителя (`H(context_version + parent_ref)`), не сводится к тексту. `CHAT_DEDUP_ENABLED`/`CHAT_DEDUP_TTL_SECONDS` не удаляются (Δ каталога 0), действуют на legacy-пути при OFF.
- **Обоснование:** §11.4 (`:434`) verbatim; A03/A04; MCA14-R5 (kill-switch).
- **Альтернатива:** оставить text-replay — отклонено (прямо запрещено для контекстных ответов). Удалить `CHAT_DEDUP_*` из каталога — отклонено (Δ каталога/пользовательская настройка; достаточно bypass при ON).

**D10. REUSE; второй контур запрещён.**
- **Выбрано:** переиспользуются `summary_memory` (embed/rerank/window/summary), `direct_chat_service` (budget/answer-cache), `lore_cache` (generation/CAS-прецедент), `thread_chain`, `search_service`, `lore_stories`/`lore_compiler_service` (эпизоды-фасад), `provenance` (`mca-04a`), `token_counter`, `TaskSupervisor` (`mca-01`); второй retrieval/EvidenceBundle/reranker/бюджет **не создаётся**.
- **Обоснование:** GEN-R19; §3/§3.1; §4 (один контур).

**D11. Наблюдаемость/R17.**
- **Выбрано:** `start`+`outcome` через `emit_mca_event`/`mca_events` (второй store запрещён); стадии `retrieval`/`reranker`/`bundle`/`budget`/`summary`; расширение `reason_code`: `retrieval_empty`, `rerank_invalid`, `rerank_timeout`, `budget_exceeded`, `context_overflow`, `embedding_generation_changed`, `summary_stale_dropped`, `answer_cache_disabled`, `exact_match_used`, `episodes_used`; регистрация стадий/виджет-ID для `mca-17a`; `sanitize()` до записи; SourceRef вместо сырого контекста.
- **Обоснование:** §17.1–§17.3; §27.1; GEN-R14/R17; A27/A48/A53.

**D12. Δ DDL = v18; Δ каталога = 0; kill-switch; risk/deploy.**
- **Выбрано:** Δ DDL **v18** (реестр `mca_embedding_index_generations` + nullable identity-колонки `embedding_cache`); аддитивно/идемпотентно через `MigrationStep`; PG no-op; vec-таблицы не трогаются; backfill не требуется. Δ каталога = 0 (env-only `ClassVar`; F8 NOT_APPLICABLE). Kill-switch: `MCA_RETRIEVAL_CONTEXT_ENABLED`, `MCA_EVIDENCE_BUNDLE_ENABLED`, `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED`, `MCA_TYPED_RERANKER_ENABLED`, `MCA_SUMMARY_SINGLEFLIGHT_ENABLED`, `MCA_CONTEXT_ANSWER_CACHE_ENABLED` (default ON, OFF = паритет baseline). Risk **R3**; deploy `DEFERRED_TO_RELEASE`; hot env-OFF; cold `git revert`→`05bc870`. Бронь версии: v18 за `mca-07`, `mca-04b` сдвигается на **v19+** (рамка §1.2.3).
- **Обоснование:** §18 (`:864–872`); §2.4–2.5; §20; A06/A24/A28.
- **Альтернатива (Δ DDL=0):** отклонено (см. D4: durable fingerprint индексов необходим для A06 после рестарта).

## Санкции и вердикты

- **Δ DDL = v18** — `mca_embedding_index_generations` (+3 индекса) + nullable `provider`/`model`/`preprocessing_version`/`endpoint_fingerprint`/`identity_fingerprint` в `embedding_cache`; через реестр `mca-14`; vec-таблицы не модифицируются; PG — no-op; backfill не требуется. Версия бронируется в `mca-round1027-arch-frames.md` **§1.2.3**. **Бронь:** `mca-04b` сдвигается на **v19+**. Точные `CREATE/ALTER` — spec §5.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; `CHAT_DEDUP_*`/`EMBED_CACHE_*` не удаляются.
- **Kill-switch (утверждены):** `MCA_RETRIEVAL_CONTEXT_ENABLED`, `MCA_EVIDENCE_BUNDLE_ENABLED`, `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED`, `MCA_TYPED_RERANKER_ENABLED`, `MCA_SUMMARY_SINGLEFLIGHT_ENABLED`, `MCA_CONTEXT_ANSWER_CACHE_ENABLED` (env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline). **`MCA_CONTEXT_ANSWER_CACHE_ENABLED` — инверсия подтверждена:** ON (default) = активна MCA-07 context-keyed политика (legacy text-replay отключён, update-дедуп сохранён); OFF = прежний ответный кеш (baseline). Имя обозначает новую политику, не legacy reuse.
- **reason_code:** расширение реестра MCA-13 десятью кодами (spec §4.9).
- **Открытые вопросы @Architect (§6 п.5 плана) закрыты:** материализация bundle — **in-memory** (D5); `context_version` — derived fingerprint (D5); связь Summary Hybrid/System2/verbalizer — один bundle (D6); место fingerprint/generation — реестр **v18** (D4/D12); связь reranker — единое ядро + адаптеры (D3).
- **Risk:** **R2** (понижен с R3 решением Reviewer gate T-3857 итер.2). Исходный класс — R3 (retrieval/bundle/бюджет на критическом пути ответа; смешивание векторов; гонка сводок; переполнение payload). `threat-failure-analysis.md` сохранён (глубина ревью R3-уровня). Триггеры понижения выполнены на фактическом diff: изоляция retrieval/бюджета от hot-path записи; A03/A04/A05/A06/A24 доказаны; отсутствие перезаписи/удаления legacy-строк (v18 аддитивна). Оговорка: при требовании полного `handle`-e2e для A04 как условия релиза R3 остаётся правомерным (review §Unavailable).
- **Обратный путь:** hot env-OFF (6 гейтов); cold `git revert` → `05bc870` (анкер `7165ff7`); v18 аддитивна.
- **Release policy:** `DEFERRED_TO_RELEASE`.

### AMEND 27.09.2026 — адъюдикация carry-over T-3857 (только `plans/**`; код/тесты не менялись)

- **D5 (EvidenceBundle) — уточнение области наполнения, контракт без изменений.** Контракт §11.2 остаётся **полным**. Живой builder mca-07 наполняет детерминированно выводимые поля; `ambiguities`/`unknown`/`contradictions` (→ **`mca-09`**, §13), `local_context` (→ **`mca-05`**, §9), `persona`/`interests` (→ **`mca-18`**, §28) — **санкционированный carry-over** первого заполняющего. Пустое значение = `not_available`, **не** отсутствие; заполняющий обязан не создавать второй bundle (GEN-R19) и отразить новые влияющие поля в `context_version`. Детали — spec §4.4/§8.1.
- **D1/D2 (retrieval-контракт) — зона потребителей.** `retrieve()` — единая точка комбинированного retrieval (контракт+каналы+тесты); живой caller — **обязательство потребителей** `mca-09`/`mca-10b`/`mca-15`; второй комбинированный retrieval запрещён (GEN-R19). Детали — spec §8.1.
- **Статус (обновлено 27.09.2026):** повторный gate T-3857 **итер.2 = Approved**; ADR-1027-7 переведён в **Accepted** фактом мержа `plans/ARCHITECTURE.md` **§99**. AMEND исполнен (carry-over `M-MCA07-2`/`L-MCA07-5` — санкционированы; §99.4).
- **Binding:** Spec-Hash/ADR-Hash из review T-3857 (`ACE242D0…`/`7420FBE9…`) устаревают; повторный gate пересобирает binding. `plans/current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не трогались; R17/R18 соблюдены.

## AMEND / REUSE-карта

| Артефакт | Режим | Суть |
|---|---|---|
| `services/summary_memory.py` (`_embed`/`_embed_cache_key`/`embedding_cache` lookup) | **AMEND** | identity-fingerprint в ключе; lookup по identity (не dim); audit-колонки |
| `services/summary_memory.py` (`rerank_rag_facts`) | **AMEND** | типизированный результат; empty≠кандидаты; invalid/timeout→отдельный статус |
| `services/search_service.py` (`_rerank_results`) | **AMEND (адаптер)** | к единому типизированному ядру reranker |
| `services/summary_memory.py` (`get_window_messages`/`_build_running_summary`) | **AMEND** | singleflight/coalescing + CAS-запись |
| `services/database.py` (`upsert_running_summary`) | **AMEND** | high-watermark/CAS (`window_end_ts`/`raw_count`) |
| `services/direct_chat_service.py` (`_apply_context_budget`) | **AMEND** | полный учёт payload; protected spans; pre-flight; логирование |
| `services/token_counter.py` | **AMEND** | защита отрицаний/ID/дат; метод консервативной оценки |
| `services/direct_chat_service.py` (answer-cache) | **AMEND** | text-replay off для контекстных; update-дедуп через `(chat_id, tg_message_id)` |
| NEW retrieval/bundle-контракт (в существующих модулях) | **NEW-контракт** | `RetrievalRequest/Result`, `RerankResult`, `EvidenceBundle` — без второго движка |
| `services/database.py` (v18) | **AMEND** | реестр поколений + nullable identity-колонки |
| `thread_chain`/`search_*_fts`/`lore_stories`/`lore_compiler_service`/`provenance`/`token_counter`/`TaskSupervisor`/`lore_cache` | **REUSE** | не дублировать |
| `emit_mca_event`/`mca_events` (`mca-13`), `MigrationStep` (`mca-14`), `write_transaction`/`serialized()` (`mca-01`) | **REUSE** | событийный/миграционный/write-контракты |
| `mca-04b`/`mca-09`/`mca-10b`/`mca-15`/`mca-16`/`mca-20`/`mca-11`/`mca-05` | **Consumers (расширяют)** | второй контур запрещён |

| Решение | Задачи |
|---|---|
| D1 (retrieval-контракт) | T-3843, T-3844 |
| D2 (эпизоды/точная фраза) | T-3844, T-3845 |
| D3 (reranker) | T-3846 |
| D4 (embedding identity) | T-3847 |
| D5 (bundle/context_version) | T-3848 |
| D6 (bundle↔Summary/System2) | T-3852 |
| D7 (бюджет) | T-3849 |
| D8 (сводки CAS) | T-3850 |
| D9 (ответный кеш) | T-3851 |
| D10 (REUSE) | T-3843, T-3844, T-3846, T-3848, T-3852 |
| D11 (наблюдаемость/R17) | T-3853 |
| D12 (Δ DDL/каталог/kill-switch) | T-3840, T-3842, T-3856 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Retrieval | новый движок; обёртка над каналами | **обёртка (комбинация)** | §11.1; GEN-R19; GEN-R10 |
| Reranker | «ошибка→все кандидаты»; typed + отдельный статус | **typed + отдельный статус/fallback** | §11.1; A05 |
| Fallback reranker | пусто; все кандидаты; pre-rerank bounded | **pre-rerank bounded** | явная политика без потери контекста; §11.1 |
| Embedding cache key | `dim`-проверка; identity-хэш | **identity-хэш** | §11.1 verbatim; A06 |
| Index fingerprint | in-memory/DDL-парсинг; durable реестр | **реестр v18** | A06 переживает рестарт; §11.1 |
| Bundle | персистентный; **in-memory** | **in-memory** | §11.2 (не дублировать архив); R17 |
| context_version | отдельная таблица; derived | **derived fingerprint** | достаточно в событиях/decision-record |
| Сводки CAS | in-memory lock; **durable CAS** | **durable CAS** | A03; несколько воркеров/рестарт |
| Ответный кеш | оставить text-replay; отключить | **отключить text-replay, сохранить update-дедуп** | §11.4 verbatim |
| Δ DDL | 0; **v18** | **v18** | A06 durable fingerprint; §11.1 |
| Бронь версии | v18 за mca-04b; **v18 за mca-07** | **v18 за mca-07, mca-04b→v19+** | критический путь: mca-07 раньше mca-04b |
| Risk | R2; **R3** | **R3** | критический путь контекста ответа |

## Последствия

- Появляется единый retrieval/reranker/bundle/budget-контракт, на который опираются `mca-09`/`mca-15`/`mca-16`/`mca-20`/`mca-10b`; второй контур запрещён.
- Вводится durable identity векторных индексов (v18) → **`mca-04b` сдвигается на v19+**; перестройка несовместимого индекса — resumable job `mca-04b`.
- Смена embedding-модели при той же размерности перестаёт смешивать векторы (A06); поздняя сводка не перезаписывает новую (A03); valid-empty reranker не разворачивается в кандидатов (A05); «почему?» под разными родителями не отдаёт старый кеш (A04); полный payload учитывается с причинами сжатия (A24).
- Δ каталога = 0; risk R3 + threat-артефакт; hot env-OFF; cold `git revert` → `05bc870`; deploy `DEFERRED_TO_RELEASE`.

## Ссылки

- Feature: `plans/features/mca-07-retrieval-context/{spec.md, tasks.md, adr-1027-7-retrieval-context.md}`.
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1.2.3 v18, §2, §3, §4).
- План: `plans/docs/mca-round1027-plan.md` §3.5 (закрытие `mca-04a`) / §3.6 (старт `mca-07`) / §6 п.5 (EvidenceBundle).
- Код baseline: `services/summary_memory.py` (`_embed_cache_key:294`, `_embed:1351`, `_embed_cache_lookup:1398`, `_embed_cache_store:1465`, `get_window_messages:1692`, `_build_running_summary:1733`, `rerank_rag_facts:2612`, `_search_graph_facts:2684`, vec DDL `:93–117`, dim-guard `:1256–1295`); `services/direct_chat_service.py` (`direct_dedup:1233–1256`, `set_dedup:1595`, `_apply_context_budget:2443–2594`, `_truncate_block:2596`, `_build_global_context:3246`, `_render_thread:3458`); `services/database.py` (`embedding_cache:1958`, `search_messages_fts:3654`, `search_graph_facts_fts:5055`, `get_running_summary:5823`, `upsert_running_summary:5842`, `chat_summary_levels:791/5869/5878`); `services/search_service.py::_rerank_results:105`; `services/thread_chain.py::collect_thread_chain:94`; `services/lore_cache.py` (`generation:174`); `services/token_counter.py` (`count_tokens`/`resolve_context_tokens`/`safe_budget`); `services/lore_compiler_service.py::compile:81`; `services/provenance.py`; `services/mca_gates.py`; `services/mca_events.py`; `config/settings.py`.
- Архитектура: входы §93 (`mca-14`), §94 (`mca-13`), §95 (`mca-01`), §96 (`mca-03`), §97 (`mca-02`), §98 (`mca-04a`); merge → §99+ (Proposed).
- Точка отката: коммит `7165ff7` (анкер), reviewed `05bc870`.
