# `mca-22-attribution-memory-coherence` — spec (Step 2 @Architect, консолидированный RCA)

> **Статус:** 🟦 Proposed — 01.10.2026, T-4276/T-4277. Код НЕ менялся; правки — только `plans/**`.
> **ADR:** `adr-1028-6-attribution-memory-coherence.md` (этот же каталог; Proposed → Accepted по Merge §109+).
> **ТЗ-источник (IMMUTABLE):** `plans/current_task.md:15305–16480` (§0–§39), блок SHA-256 `ad389212…660c`; полный файл `7025FEF7…13BA0`.
> **Задачи:** `tasks.md` T-4273…T-4322 (этот же каталог). Baseline: прод 2.58.43, SQLite DDL v21, каталог 488/427/463/105/103/21, HEAD `7a86179` (прод-HEAD `9906c9d`).
> **Дисциплина:** R17/R18 соблюдены — секреты/сырьё не цитируются; все анкеры кода — только структура/контракты.

**Risk-Level: R3 (ратифицирован).** Обоснование: сквозное изменение read-path **всех** потребителей сообщений (12 consumers §2) + семантика персональной памяти (producers/GraphRAG/correction) + freshness-контур Direct. Регрессия уже задеплоенных MCA-03/04/04b/05/07 = порча производной памяти и атрибуции на живых данных, откат только env-рубильниками. Что могло бы поднять риск выше R3: потеря/перезапись существующих строк памяти при backfill (запрещено дизайном — все Δ аддитивны, backfill не удаляет и не auto-bind'ит) и DDL, меняющий существующие таблицы (санкционирован только аддитивный v22).

**Browser-Verification: REQUIRED (scoped).** Причина: §24 добавляет user-visible раскрытие в существующие Analytics-виджеты админ-миниаппа (Attribution Trace, source card, correction trace) и §38 меняет доставляемую справку (`/api/info/guide`). Требуется структурированная browser-проверка (Playwright MCP) виджетов/справки на локальном стенде с fixture-БД; скриншот-инспекция — только для справки (markdown/html/desktop/mobile) и санити source card. Пиксельная точность не требуется. Аутентификация — существующая локальная схема стенда; выдуманные креды/Telegram-состояние запрещены. E2E Telegram-ветки (§37) — вне browser-верификации (prod acceptance живыми сообщениями).

---

## 0. Scope / excluded scope

**В scope:** единый canonical read contract (runtime DTO/projection, без новой БД) для 12 consumers §2; Durable Own Output Ledger + evidence-политика self-output; единый Quote Resolver; Claim/Assertion Envelope (runtime + существующая persistence); speaker≠subject + coreference; GraphRAG provenance enforcement + legacy-маркировка; attribution-aware RetrievalCandidate/query planning; EvidenceBundle structure-first (v2); correction/revalidation; freshness (update dedup, no-replay, duplicate guard, lineage); Analytics Attribution Trace (расширение существующих виджетов); метрики §25; truth-set A–O; справка «Мозг бота» (T-4320).

**Excluded:** второй memory/retrieval/context/provenance/identity stack (§1); переписывание identity model/provenance контракта/retrieval-движка/personality/корневого Analytics (MCA-03/04/04b/07/08/17/18 reuse — §33 ниже); model capacity/budgets/provider discovery/GraphRAG generation lifecycle/Summary transport (ASAP-3.x); новый help-механизм (только повторная актуализация по MCA-21); академический NLP-комбайн (§6); paraphrase-postprocessor (§18); изменения §87-чеклиста ASAP-3.2 (image/provider lifecycle — вне фичи, см. §8 ниже).

---

## 1. RCA по зонам (факт кода, 01.10.2026)

### Z1 — Canonical read: контракт есть в DB, теряется в readers (Q1/Q2/Q3)

- **Запись богата:** v16 (`mca-03`) добавила в `smart_messages` 18 nullable-колонок (`services/database.py:256–262`), включая `reply_to_author_id`, `quote_text`, `quote_author_id`, `forward_author_id`, `current_revision`, `sent_at/ingested_at/edited_at`, `message_state`. Контракт ролей жив: `services/message_identity.py:132–140` (`roles()` → author/reply_addressee/quoted_author/forward_author).
- **Чтение узкое.** Три главных read-path возвращают только 11 колонок (`id, user_id, chat_id, text, reply_to_id, timestamp, media_type, author_name, is_forward, forward_source, tg_message_id`):
  - `get_smart_window` (`database.py:4191`) — окно L1/саммари/GraphRAG-extraction/досье;
  - `get_smart_raw` (`database.py:4214`) — L2/сжатие;
  - `search_messages_fts` (`database.py:4862`) — retrieval exact/lexical.
  Роль-колонки, revision и `sent_at` в consumers **не доезжают**: следующий слой вынужден угадывать роли по тексту — точный анти-паттерн §2.
- **Ingestion сам теряет автора цитаты:** `handlers/summary.py:226–229,258` извлекает `quote_text` из `message.quote`, но `quote_author_id` в `save_live_message` **не передаётся** — колонка есть, живой путь её никогда не заполняет (Q3a).
- **Рендер без слотов ролей:** канон-строка `[Дата | Автор | ID | Переслано]: текст` (`services/canonical_context.py:252–295`) имеет слот только для forward; «кому отвечено» и «кого цитирует» в prompt не различимы; ручные `>`-цитаты не разрешаются вовсе.
- **Вывод:** единого canonical read contract нет; consumers читают через ~5 разных путей (thread_chain / window / FTS / RAG-факты / chunk-строки досье). MCA-22 вводит projection-слой поверх `smart_messages` + `message_source_records`, не новую БД.

### Z2 — Own Output Ledger: бот забывает себя за час (Q4/Q5/Q15)

- Реально отправленные direct-ответы живут только в `bot_replies` (`database.py:3159`, `:6421–6483`): PK `(chat_id, tg_message_id)`, `text`, `last_used_at`; **TTL 3600 c** (лениво на чтении) + **LRU cap 200/чат**; пишется только после успешной отправки (`direct_chat_service.py:1292`); правки бота — UPSERT (`handlers/direct_chat.py:333–345`). Parent-цепочка — `bot_reply_parents` (`database.py:1182+`).
- Summary/RichMessage-статьи, медиа-подписи, autonomous-ответы **durable не хранятся нигде**: observer скипает bot-сообщения (`handlers/summary.py:193`), `bot_replies` — только direct. Reply на статью старше TTL → source восстановить нечем (кейс §14/H).
- Параллельно бот-реплики попадают в память косвенно: `memorize_facts(..., "bot_direct_reply", target_user=asker)` + `memorize_self_reply` (`direct_chat_service.py:3840–3900`) — т.е. «что бот сказал» смешано с «что бот знает».
- **Вывод (Q5):** в `smart_messages` bot-output писать нельзя (FTS/окно/L1/L2/persona/GraphRAG трактуют его как human-only corpus — загрязнение гарантировано); `bot_replies` расширять нельзя (TTL-кеш по контракту 63.1). Нужен минимальный durable store `mca_bot_outputs`, наружу через SourceRef (`entity_type='message'`).

### Z3 — Claim/speaker/subject: инверсии возможны на трёх producers (Q6/Q7)

- **Хорошо:** direct-live атрибуция (`_apply_fact_attribution`, `direct_chat_service.py:3930+`) и dossier Layer A (`lore_worker._write_person_facts`, `lore_worker.py:1682–1775`) пишут `subject_ref_id/attribution_method/assertion_kind` + EvidenceLinks; `provenance.py` имеет полный словарь (`ATTRIBUTION_METHODS`, `ASSERTION_KINDS`, `CHECK_KEYS` c `negation/quote/joke/retelling`, `BOT_ORIGINS`→self_referential).
- **Дыры (producers личных фактов без постоянного SourceRef):**
  1. `remember_user_fact` («запомни», `summary_memory.py:2881–2932`) — INSERT в `graph_facts` без provenance-хука и без `tg_message_id`;
  2. `memorize_self_reply` (`summary_memory.py:2936–2983`) — `bot_self_reply` без provenance;
  3. `bot_direct_reply`-факты: `_attach_fact_provenance` пропускается (`summary_memory.py:2685`), покрытие — только пост-хуком direct при `MCA_FACT_ATTRIBUTION_ENABLED=ON`;
  4. `chat_meme`/`dossier_portrait` (`lore_worker.py:1563–1680`) — `target_user` без SourceRef;
  5. `memorize_facts(chat_history)` из сводок (`summary_generator.py:495,625`) — speaker не передаётся.
- **Speech-acts:** `parse_fact_list_ex`/`parse_triplets` не различают assert/deny/quote/retell — «Я не говорил, что X» может дать positive X (запрещено §6); guard должен опираться на `CHECK_KEYS.negation` + write-gating.

### Z4 — GraphRAG provenance: bare edges легальны сегодня (Q8)

- Базовый DDL `graph_facts` (`database.py:1133–1150`) не требует provenance; v17-колонки nullable. Личное знание с `subject_ref_id IS NULL` читается теми же `search_graph_facts_fts`/vector-каналами наравне с provenance-backed — «bare edge = уверенное знание». Повторы экстракций одного пересказа поднимают `weight/confirmed_at` без роста независимых evidence roots (`evidence_independent_count` в `provenance.py` есть, но retrieval его не применяет).

### Z5 — Retrieval/EvidenceBundle: metadata теряется в кандидатах, bundle — regex от строк (Q9/Q10)

- `RetrievalCandidate` (`mca_retrieval_context.py:299–313`) несёт `source_ref_id/sent_at/author_id/revision`, но фактические конструкторы не заполняют: `_message_candidate`/`_fact_candidate`/`_fact_meta_candidate`/`_chain_candidate`/`_episode_candidates` (`:525–637`) читают только id/user/ts/text; **ни один** не проставляет `subject_entity_id/assertion_kind/verification/origin/contradiction_status`; vector-кандидат не несёт даже `chat_id/author/source_ref`. Фильтр `_apply_filters` умеет только время/участников.
- `EvidenceBundle` собирается в `direct_chat_service._build_evidence_bundle` (`:3455–3548`) **из отрендеренных user-блоков regex-ом** (`_REF_ID_RE` по `Conversation_Branch/Thread/RAG_Memory`) — прямо запрещённый §11 паттерн; `author` и `addressee` = одна строка `target_name` (`:3538`); `source_ref_id=None` у всех EvidenceItem; полей quoted_speaker/reply-addressee/forward нет; `current_revision` = `"tg:<id>"`, а не MCA-03 revision.

### Z6 — Correction: сигнала нет, статусы есть (Q11)

- Фразы «ты сам это написал / это говорил Лёха / ты меня перепутал» сегодня не имеют выделенного пути: они обрабатываются как обычный диалог; contradiction-evidence не создаётся. При этом вся механика для этого уже есть: `link_type ∈ {contradicts, supersedes}` + `mca_provenance_status.conflict_status ∈ {none, conflicting, resolved}` + `freshness_status='superseded'` (`provenance.py:46–71`), пере-проверка источников — `reconstruct_fact_provenance` (`:704+`), revision-инвалидация — `message_identity.record_edit` → `source_revision_changed` + episodes recheck (`message_identity.py:218–265`).

### Z7 — Freshness/cache: replay закрыт частично, идемпотентности update нет (Q12/Q13/Q14)

- Legacy text-replay (`direct_dedup` по `chat+user+normalize(text)`; `direct_chat_service.py:1598–1621`, `smart_cache.py:314–330`) активен **только при `MCA_CONTEXT_ANSWER_CACHE_ENABLED=OFF`** (`_legacy_text_replay_enabled`, `:252–257`). При дефолтном ON replay-ветка мертва — но вместе с ней исчезла и единственная защита от повторной обработки того же Telegram update: **update-identity дедупа `(chat_id, tg_message_id, revision)` нет нигде** (`handlers/direct_chat.py:458–487` вызывает `_service.handle` напрямую; throttle/lock — rate-limit, не identity). Повторная доставка update (retry Telegram) = вторая оплата LLM + второй ответ.
- Ingestion идемпотентен (`save_smart_message_identity` — get-or-create по `(chat_id, tg_message_id)`, `database.py:4370–4453`) — дубли в памяти не плодятся, но LLM/reply платят дважды.
- Прочие ветки финального ответа (autonomous reply, tool-loop вербализатор, fallback recompose при provider switch, memory-команды) собственного answer-cache не имеют; единственный literal-replay источник — legacy dedup. Env-переопределения prod из репо не верифицируемы → чек в §37/T-4308.

### Z8 — Analytics/наблюдаемость: атрибуцию не проследить (Q16)

- Существующие surface: `web/api/memory_agi.py` (graph/stats/timeline/dream/health), `/persona` карточки, `mca_trace` (счётчики provenance-статусов, `mca_trace.py:556–563`), tool `memory_lookup`. Ни один не показывает «кто сказал / о ком / какой источник / что отброшено / какие противоречия» — раскрытие §24 строится расширением этих же виджетов (новый корневой dashboard запрещён §1).

---

## 2. Ответы на 17 обязательных вопросов §34

| # | Вопрос | Ответ (кратко) | Анкеры |
|---|---|---|---|
| Q1 | Какой canonical read contract реально используют Direct/Lore/GraphRAG/Dossier? | Единого нет. Direct: `thread_chain` (полный ряд `get_smart_message_by_tg_id`) + `bot_replies/parents` + mca-07 контракты; Lore/GraphRAG-extraction: `get_smart_window`/`get_smart_raw` (11 колонок); Retrieval: narrow FTS-SELECT; Dossier rebuild: chunk-строки + `_source_ref_ids` (единственный с SourceRef). Вводим **projection-слой** (runtime DTO + projection-функция) поверх `smart_messages` — не новая БД (§2 ТЗ). | Z1 |
| Q2 | Какие MCA-03 поля есть в DB, но теряются? | `reply_to_author_id`, `quote_text`, `quote_author_id`, `forward_author_id`, `sent_at`, `ingested_at`, `edited_at`, `current_revision`, `caption`, `source_kind`, `message_state` — присутствуют в таблице, отсутствуют в SELECT `get_smart_window`/`get_smart_raw`/`search_messages_fts` и во всех кандидатах retrieval. | `database.py:256–262,4191,4214,4862` |
| Q3 | Где теряется quote speaker? | (a) ingestion: `quote_author_id` не извлекается из `message.quote`; (b) read: quote_* не выбираются; (c) render: канон-строка не имеет слота «цитата + её автор»; (d) bundle: нет поля quoted_speaker. | `handlers/summary.py:226–258`, `canonical_context.py:252–295` |
| Q4 | Где хранятся отправленные bot outputs и сколько живут? | Только `bot_replies` (direct-ответы): TTL **3600 c** + LRU cap 200/чат, запись после успешной send; parent — `bot_reply_parents`. Summary/RichMessage/подписи/autonomous — нигде durable. | `database.py:6421–6483`, `direct_chat_service.py:1292` |
| Q5 | Как хранить durable bot outputs без загрязнения human-only consumers? | Отдельная минимальная таблица `mca_bot_outputs` (DDL **v22**), наружу через SourceRef `entity_type='message'`; НЕ `smart_messages` (corpus-загрязнение), НЕ расширение `bot_replies` (TTL-кеш по контракту). Читают только quote-resolver, thread_chain, ledger-read и Analytics. | §3-C2 |
| Q6 | Можно ли Claim Envelope выразить без новой таблицы? | Да. Runtime DTO `ClaimEnvelope`; persistence — существующие `graph_facts`-колонки (v17) + `mca_source_refs/mca_evidence_links` (`claim_key`, `checks_json`: negation/quote/joke/retelling) + `mca_provenance_status` (conflict/freshness). Speech-acts question/hypothesis/command/joke — write-gating (personal fact не пишется), не отдельные колонки. Новая SQL-таблица запрещена. | `provenance.py:46–84`, §3-C4 |
| Q7 | Какие producers способны записать personal fact без permanent SourceRef? | (1) `remember_user_fact` («запомни»); (2) `memorize_self_reply`; (3) `bot_direct_reply` (attach пропущен, покрыт только post-хуком при гейте ON); (4) `chat_meme`/`dossier_portrait`; (5) `memorize_facts` из сводок. Все проходят единый validator: accepted+source / tentative+source candidate / unresolved / rejected (§13). | Z3 |
| Q8 | Какие person GraphRAG edges без provenance/fact_id? | Вся legacy-память до v17 (`subject_ref_id IS NULL`) + текущие ветки Q7. Политика: не удалять, маркировать `legacy/unverified` (по `mca_provenance_status.origin_status`/колонкам), weak retrieval hint, восстановление через `reconstruct_fact_provenance` при востребованном чтении. | Z4, `provenance.py:704+` |
| Q9 | Какие retrieval channels теряют subject/speaker metadata? | Все пять: exact/lexical-messages, lexical-facts, vector (худший — нет chat_id/author/source_ref), reply_graph, episodes. v17-колонки фактов не читаются ни одним каналом. | `mca_retrieval_context.py:525–637` |
| Q10 | Почему EvidenceBundle строится из rendered blocks и какие поля фиктивны? | Наследие M-MCA07-2 («без нового I/O»): bundle собран regex по user-блокам. Фиктивно/пусто: `source_ref_id=None` везде; `author==addressee==target_name`; quoted_speaker/reply-addressee/forward отсутствуют; `current_revision="tg:<id>"`. MCA-22: structure-first из Canonical Envelope + RetrievalCandidates; bundle v2 — под существующим гейтом `MCA_EVIDENCE_BUNDLE_ENABLED`. | `direct_chat_service.py:3455–3548` |
| Q11 | Как встроить correction/revalidation в текущие EvidenceLink statuses? | Без нового статусного контура: correction создаёт `contradicts`-EvidenceLink (verification=`tentative` до пере-проверки) + `conflict_status='conflicting'`; пере-проверка через существующий reconstruction → `resolved` или остаётся `conflicting`; superseded — `freshness_status='supersedes'`-link. disputed/revalidation_pending = проекции `conflicting`/`tentative` (отдельные значения не вводятся). User correction = сильный сигнал, не абсолют. | `provenance.py:46–71`, §3-C6 |
| Q12 | Есть ли в prod literal answer replay несмотря на MCA-07 policy? | При дефолтных гейтах — в Direct main-ветке нет (replay требует `MCA_CONTEXT_ANSWER_CACHE_ENABLED=OFF`). Но: update-identity дедупа нет → повторная доставка update = повторная генерация и ответ; при OFF-override legacy replay возвращается целиком. Prod-env проверяется на §37/T-4308 (репо не знает env). | Z7 |
| Q13 | Какие cache-related gates реально включены на prod? | По коду: все `MCA_*` default **ON** (env-only, реестр `mca_gates.KILL_SWITCHES`); `CHAT_DEDUP_ENABLED` — в param_catalog (UI, default ON), влияет только на dedup-ветку при политике OFF. Фактические env-переопределения prod подтверждаются живой проверкой (§37). | `mca_gates.py:23–193`, `settings.py:1601–1606,2043` |
| Q14 | Где ещё final answer может replay'иться? | Ветки: (1) Direct main dedup — закрыт политикой ON; (2) Direct autonomous reply — общий send-path, покрывается guard'ом; (3) memory-команды — детерминированные фразы, exemption; (4) tool-loop вербализатор — без своего кеша; (5) fallback recompose — пересборка, не replay (фиксируется тестом); (6) provider retry — новый вызов. Реальный replay-источник один — legacy dedup; закрывается no-replay + update-dedup. | Z7, §3-C7 |
| Q15 | Какие bot output types включить в durable ledger? | direct replies, autonomous replies, RichMessage/Summary-статьи, медиа-подписи, правки собственных сообщений (новая revision-строка). Исключены: недоставленные draft (`delivery_status`), tool-результаты (не Telegram-сообщения). | §3-C2 |
| Q16 | Как расширить Analytics без нового dashboard? | Расширение существующих `web/api/memory_agi.py`-виджетов (graph/stats/timeline), trace (`mca_trace`), source card в `/persona`-карточке, correction trace; фронт — существующие Memory/Analytics/RAG/Context вкладки (MCA-17). | Z8, T-4313 |
| Q17 | Нужен ли DDL delta? | Да, минимальный: **v22** — `CREATE TABLE IF NOT EXISTS mca_bot_outputs` + 3 индекса, PG no-op. Больше DDL нет: canonical read = projection; claim = существующие поля; update-dedup = slug в существующей `smart_cache`; события = `mca_events`. | §4.1 |

---

## 3. Контракты (для Builder; архитектура — ADR-1028-6)

### C1 — Canonical Message Envelope + canonical read contract (§2/§3, T-4279–T-4283)

- Runtime frozen-DTO `CanonicalMessage` с полями §2 ТЗ (message_ref, source_ref_id, chat_id, tg_message_id, revision, source_kind, speaker_entity_id/display_name, sent_at/ingested_at/edited_at, reply_to_*, quote_*, forward_*, thread/topic/media, raw_text, caption). Неизвестное = `None` (никогда не выдумывается).
- Форма доступа — **projection-функция** (batch: `get_canonical_messages(chat_id, refs|window) -> list[CanonicalMessage]`) поверх существующих таблиц; SELECT расширяется до полного набора роль/время-колонок (одним проходом, без N+1 — §30: batched JOIN/per-request map; short-lived identity cache с invalidation по `current_revision`).
- Перевод 12 consumers (§2 ТЗ): Direct Chat, thread chain, context composer, retrieval, GraphRAG extraction, dossier/live lore, dossier rebuild, episodes/history, Summary-derived extraction, factcheck context, history-reading tools, Analytics source cards. Требование инварианта: если БД знает роль — следующий слой не угадывает её по тексту.
- **Fix ingestion (Q3a):** `summary_observer` извлекает и передаёт `quote_author_id` (автор цитаты из `message.quote`), а также `quote`-источник, где Telegram его отдаёт.
- **Rendering (§3):** `store rich → retrieve rich → render only relevant metadata`; но если без поля меняется смысл (reply-адресат, автор цитаты, автор пересылки) — поле обязательно в model-facing context. Reply ≠ quote ≠ forward различимы в prompt-рендере.
- OFF-паритет: `MCA_CANONICAL_ATTRIBUTION_ENABLED=false` → потребители читают как сегодня (существующие SELECT), без новых записей.

### C2 — Durable Own Output Ledger (§4/§14, T-4286–T-4289)

- Таблица `mca_bot_outputs` (точный DDL — §4.1). Поля ≥ минимума §4: bot_user_id, chat_id, tg_message_id, sent_at, parent_message_ref, output_kind (`direct_reply|autonomous_reply|rich_message|media_caption|other`), content_text или content_ref, content_hash, revision_no, correlation_id, source_feature, delivery_status (`delivered|failed|unknown`).
- **Write-path:** только реально доставленные outputs (после успешной send; недоставленный draft не пишется или `delivery_status='failed'` → не «слова бота»); правка собственного сообщения → новая revision-строка (append-only, без удаления).
- **Read-path:** quote resolver (приоритет 5 §5), thread_chain (восстановление цепочки через бот-ход старше TTL `bot_replies`), «ты сам это написал», reply на RichMessage → relation к summary/article run (correlation_id), история обещаний.
- **Evidence-политика:** bot output — evidence для «бот говорил X»; запрещён как независимое proof «X правда» (механика — `independence='self_referential'`, уже есть в `provenance.py`; распространяется на ledger-происхождение).
- SourceRef: `store='sqlite', entity_type='message', entity_id='bot_output:<id>'` — совместимо с существующим контрактом mca-04a.
- OFF: `MCA_BOT_OUTPUT_LEDGER_ENABLED=false` → `bot_replies` как сегодня, quote-priority 5 недоступна (лестница падает на 6/7).

### C3 — Quote Resolver (§5, T-4290)

- Единая лестница: 1 native reply target → 2 Telegram quote metadata → 3 exact quote inside known parent → 4 exact/normalized match in current thread → 5 exact match in Own Output Ledger → 6 bounded local historical search → 7 unresolved.
- Partial quote внутри reply target: quote source/speaker = parent; current speaker = sender. Ручные `>`-цитаты: короткие общие фразы не auto-bind; ≥2 совпадения → `ambiguous`; нет уверенного → `unknown`; sender никогда не назначается автором цитаты по умолчанию. Fuzzy semantic match ≠ доказанное авторство.
- Deterministic-first (§29): Telegram metadata закрывает ступени 1–2 без LLM; LLM-резолвер только для 3–4/6, его entity ID обязан быть из candidate set; `unknown` лучше hallucinated binding.

### C4 — Claim/Assertion Envelope + speaker≠subject (§6/§7/§8, T-4291–T-4294)

- Runtime frozen-DTO `ClaimEnvelope`: speaker_entity_id, subject_entity_id, mentioned_entity_ids, claim_text/normalized proposition, speech_act (`assert|deny|correct|quote|retell|question|hypothesis|joke_candidate|command`), stance, negated, quoted_source_ref, reply_target_ref, event_time/valid_from/valid_to, source_refs, attribution_method, verification, revision.
- Persistence — существующая схема (Q6): graph_facts v17-колонки + EvidenceLink (`claim_key`, `checks_json`), provenance_status. Question/hypothesis/command/joke-candidate personal fact **не создают**; deny/`negated` — guard: «Я не говорил, что X» не создаёт positive X (test truth-set D).
- Speaker≠subject (§7): `speaker=A, subject=Лёха`; запрещён fallback `subject=sender`; недоказанный subject → unresolved-candidate / world-chat fact / skip personal write + diagnostic reason. Third-party claim = attributed assertion, не биография. Attribution certainty ≠ truth status.
- Coreference (§8): stable IDs + reply graph + thread + aliases + recent mentions; `ALIAS > real_name > username` — display preference, не слияние; местоимения без достаточного контекста → `unresolved`.
- Producer-validator (§13): все personal-fact producers (список Q7) проходят один normalizer с исходами `accepted+source / tentative+source candidate / unresolved / rejected`; Layer A `evidence:[n]` → local line → CanonicalMessage → SourceRef сразу после parse; manual/admin fact — явный provenance type (`method='manual'` уже в словаре).

### C5 — GraphRAG provenance + retrieval attribution (§9/§10/§21, T-4295–T-4298)

- Person-affecting edges (user→user/topic/relation): запись требует source assertion + SourceRef/EvidenceLink + speaker + subject + revision (+temporal где применимо); bare edge не поднимается в confident. Legacy (`subject_ref_id IS NULL` или `origin_status='unknown'`): не удалять, маркировать, weak hint, восстановление при востребованном чтении. Повтор пересказа ≠ независимое подтверждение (unique evidence roots через `evidence_independent_count`). `supports/contradicts/supersedes` видимы downstream.
- `RetrievalCandidate` дополняется: `subject_entity_id`, `speaker_entity_id`, `assertion_kind`, `verification`, `origin_type`, `contradiction_status` + заполнение `source_ref_id` там, где SourceRef существует. Read-функции (`search_graph_facts_fts`, `search_messages_fts`, window/raw) расширяются до полной выборки идентичность+provenance-колонок.
- Rerank/filter: exact subject / participant scope / source role / reply-thread relation / revision / provenance quality / recency / lexical-vector score; exact SourceRef/reply match про нужного subject сильнее vector hit про другого (truth-set K).
- Query planning (§21): retrieval request для person-запросов несёт структурированно speaker/addressee/mentioned/reply target/resolved quote source/subject candidates/time scope; episodes-first сохраняется, episode несёт participant roles + SourceRefs.

### C6 — EvidenceBundle structure-first v2 (§11/§28, T-4299–T-4300)

- Сборка: `CanonicalMessages + RetrievalCandidates → EvidenceBundle → prompt rendering`. Regex-парсинг render-строк устраняется в direct-пути (bundle строится из structured данных, render — отдельная функция от bundle).
- Поля bundle v2: `author`, `direct_addressee`, `reply_addressee`, `quoted_speaker`, `mentioned`, `subjects`, `ambiguities`, `contradictions`, `source_refs` (реальные `source_ref_id`), `context_version` (по MCA-03 revision), `excluded`. Author и addressee — раздельные слоты.
- Tool loop (§28): bundle дополняется tool-результатами, не пересобирается урезанным; до/после tool сохраняются author/addressee/parent/quote source/subject/contradictions/context_version lineage.

### C7 — Freshness closure (§16–§20, T-4307–T-4312)

- **Update dedup:** identity `(chat_id, tg_message_id, revision)`; маркер в существующей `smart_cache` (slug `direct_update`, TTL ≈ 24h) — без DDL. Инвариант: same update → idempotent (0 LLM, 0 reply, 0 memory); different update, same text → fresh processing.
- **No-replay:** conversational финальный ответ не кешируется между разными messages; intermediate-кеш разрешён (embeddings, provider metadata, retrieval intermediates, immutable source lookup, tool results, static prompt prefix). Legacy text-dedup остаётся только как OFF-политика `MCA_CONTEXT_ANSWER_CACHE_ENABLED=false` (уже так).
- **Previous answer in context (§17):** второй generation context включает прошлый ответ (через thread_chain/ledger) + новый turn; факт-база может совпадать.
- **Exact duplicate guard (§18):** `new tg_message_id AND normalized(final)==normalized(recent bot answer)` → максимум одна regeneration с фиксированным коротким hint; второй совпавший ответ отправляется + metric. Exemptions: точная цитата, deterministic command result, status/error phrase, structured output, code/hash/ID, tool-result-данные, system/safety text. Paraphrase-процессор запрещён.
- **Lineage (§20):** safe snapshot (reply/trigger/parent refs, context_version, model/provider, generation attempt, freshness retry flag, source refs used) + события `DIRECT_UPDATE_DEDUP_HIT / DIRECT_FINAL_REPLAY_BLOCKED / DIRECT_FRESH_GENERATION / DIRECT_FRESHNESS_RETRY / DIRECT_INTERMEDIATE_CACHE_HIT` через `mca_events`; без hidden CoT и raw private content.

### C8 — Correction/revalidation + read policy (§12/§22/§23, T-4301–T-4302, T-4305–T-4306)

- Триггеры-фразы (§12) → correction path: contradiction-EvidenceLink (`contradicts`, verification=`tentative`) + `conflict_status='conflicting'`; пере-проверка source (существующий reconstruction + quote resolver) → `resolved` / остаётся `conflicting`; superseded — `supersedes` + `freshness_status='superseded'`. Message edit → инвалидация зависимых current conclusions (существующие `source_revision_changed` + recheck-очередь).
- Disputed/`conflicting` факт: не удаляется, виден в Analytics/Memory, не подаётся как confident personalization.
- Conflict arbitration (§22): source-backed > derived memory; old bot output не решает спор о факте мира; temporal — существующие supersedes-семантики.
- Read policy (§23): verified/current → attributed tentative (маркированно) → disputed не персонализация; memes отдельно; bot outputs не personal facts; graph: current + provenance-backed + subject-matched + non-contradicted выше legacy bare.

---

## 4. Санкции (@Architect, T-4277)

### 4.1 Δ DDL — v22 (единственная; аддитивная; PG no-op)

```sql
CREATE TABLE IF NOT EXISTS mca_bot_outputs (
    output_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_user_id      INTEGER,
    chat_id          INTEGER NOT NULL,
    tg_message_id    INTEGER,
    revision_no      INTEGER NOT NULL DEFAULT 1,
    sent_at          INTEGER,
    parent_message_ref TEXT,
    output_kind      TEXT NOT NULL,
    content_text     TEXT,
    content_ref      TEXT,
    content_hash     TEXT,
    correlation_id   TEXT,
    source_feature   TEXT,
    delivery_status  TEXT NOT NULL DEFAULT 'delivered',
    created_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mca_bot_outputs_chat_tg ON mca_bot_outputs (chat_id, tg_message_id);
CREATE INDEX IF NOT EXISTS idx_mca_bot_outputs_hash    ON mca_bot_outputs (content_hash);
CREATE INDEX IF NOT EXISTS idx_mca_bot_outputs_corr    ON mca_bot_outputs (correlation_id);
```

- Регистрация шага v22 в реестре `MigrationStep` (`services/database.py`, хвост v21 `_SCHEMA_VERSION_EPISODES_STORIES`); аддитивно/идемпотентно (guard `sqlite_master`), `user_version` 21→22, повторный прогон — no-op; backup+read-back по механизму mca-14. **Обоснование §31:** durable ledger реально требует durable-хранилища; reuse `smart_messages` загрязняет human-only corpus, reuse `bot_replies` ломает контракт TTL-кеша 63.1. Номер резервируется этой санкцией (запись в рамке `mca-round1027-arch-frames.md` — при старте Build). Остальные потребности (canonical read, claim, dedup, события) — **без DDL**. PG: `pg_db.py` вне diff (memory-контур SQLite-only — подтверждено сканом DDL `pg_db.py`).
- Backfill: не требуется для инвариантов «вперёд» (новые outputs пишутся сразу); опциональный архивный backfill исторических bot-ответов — resumable `task_jobs`, не блокирует production, старые записи без уверенного source не auto-bind'ятся.

### 4.2 Kill-switches (финальный набор; env-only `ClassVar`, default ON, per-call, OFF = паритет baseline)

| Switch | Зона | OFF-паритет |
|---|---|---|
| `MCA_CANONICAL_ATTRIBUTION_ENABLED` | C1/C3/C4/C5: canonical envelope+read projection, quote resolver, claim envelope, speaker≠subject, producer-validator, GraphRAG provenance enforcement, retrieval attribution | потребители читают/пишут как сегодня (существующие SELECT/записи); роль-колонки не используются |
| `MCA_BOT_OUTPUT_LEDGER_ENABLED` | C2: write/read `mca_bot_outputs` | `bot_replies` как сегодня; quote-priority 5 недоступна |
| `MCA_CORRECTION_REVALIDATION_ENABLED` | C8: correction path, disputed-состояния, read-policy | фразы-триггеры обрабатываются как обычный диалог; существующие статусы не меняются |
| `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` | C7: update-dedup, no-replay, duplicate guard, freshness retry, lineage-события | текущее поведение: legacy text-dedup ветка живёт под собственной политикой `MCA_CONTEXT_ANSWER_CACHE_ENABLED` |

- Существующие рубильники **уважаются, не дублируются**: `MCA_CONTEXT_ANSWER_CACHE_ENABLED`, `CHAT_DEDUP_ENABLED`, `MCA_EVIDENCE_BUNDLE_ENABLED` (bundle v2 — под ним), `MCA_RETRIEVAL_CONTEXT_ENABLED`, `MCA_TYPED_RERANKER_ENABLED`, `MCA_MESSAGE_IDENTITY_ENABLED`, `MCA_MESSAGE_REVISION_TRACKING_ENABLED`, `MCA_PROVENANCE_ENABLED`, `MCA_FACT_ATTRIBUTION_ENABLED`, `MCA_EVIDENCE_RECONSTRUCTION_ENABLED`, `MCA_EPISODES_*`, `MCA_DOSSIER_*`, `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` (линия событий). Инертности: canonical OFF ⇒ quote/claim/attribution-ветки недостижимы; ledger OFF ⇒ correction не может резолвить бот-цитаты через priority 5 (fallback 6/7); observability OFF ⇒ события только structural log.
- Developer-level тумблеров не добавляем (4 рубильника — весь набор фичи); в админку UI не выносятся.

### 4.3 reason_code additions (словарь `services/mca_events.py:REASON_CODES`, расширяемый — прецедент mca-03/04a/07)

`direct_update_dedup_hit`, `direct_final_replay_blocked`, `direct_fresh_generation`, `direct_freshness_retry`, `direct_intermediate_cache_hit`, `quote_resolved`, `quote_ambiguous`, `quote_unresolved`, `subject_unresolved_skipped`, `correction_revalidation_queued`, `bot_output_recorded`, `bot_output_undelivered_skipped`. Имена событий `DIRECT_*` (§20) — свободная ось `event_name` (контракт mca-13), словаря не требуют.

### 4.4 Каталог, метрики, merge, deploy

- **Δ каталога = 0:** все новые настройки env-only; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; F8 (ADR-1026-2) NOT_APPLICABLE. Каталог 488/427/463/105/103/21 не меняется.
- **Метрики §25** — вывод в существующую телеметрию (`mca_events`-агрегаты + Analytics-виджеты); `final_answer_literal_replay_rate` ≈ 0 для разных messages (кроме exemptions).
- **Deploy:** пер-фичевый + prod-acceptance §37 на реальном безопасном чате (MCA-22 — отдельный Epic вне волнового `DEFERRED_TO_RELEASE`); bump 2.58.43 → следующая минорная (финальный номер — @Builder по реестру релиза). Hot-откат — 4 рубильника (env, без редеплоя); cold — `git revert`; DDL v22 аддитивен (данные не теряются при откате кода).
- **Merge:** `plans/ARCHITECTURE.md` **§109+** (следующий фактически свободный на момент merge; хвост §108 = mca-05 — подтверждено); ADR-1028-6 → Accepted по Merge.

---

## 5. DoD §39 — mapping (32 пункта)

| DoD | Покрытие | Контракт/задача |
|---|---|---|
| 1 | C1 (projection для 12 consumers) | T-4279–T-4282 |
| 2 | C1 rendering | T-4283 |
| 3 | C2 ledger + read после TTL | T-4287/T-4288 |
| 4 | C2 evidence-политика (`self_referential`) | T-4289 |
| 5 | C3 лестница 1–7 + bounded manual | T-4290 |
| 6 | C4 speaker≠subject во всех producers | T-4293 + validator T-4303 |
| 7 | C4 speech acts/negation guard | T-4292 |
| 8 | C4 запрет subject=sender | T-4293 |
| 9 | C4 producer-validator outcomes | T-4303 |
| 10 | C4 один contract live/rebuild | T-4303 |
| 11 | C5 provenance enforcement + legacy-маркировка | T-4295/T-4296 |
| 12 | C5 RetrievalCandidate metadata | T-4297 |
| 13 | C5 identity filters alongside vector | T-4297/T-4298 |
| 14 | C6 structure-first до render | T-4299 |
| 15 | C6 реальные SourceRefs | T-4299 |
| 16 | C6 tool loop | T-4300 |
| 17 | C8 correction→contradiction/revalidation | T-4305 |
| 18 | C8 disputed не персонализация | T-4306/T-4302 |
| 19 | C8 edit invalidation | T-4306 |
| 20 | C7 no-replay same text/new message | T-4309 |
| 21 | C7 update idempotent | T-4307 |
| 22 | C7 guard bounded 1 | T-4311 |
| 23 | C7 не жертвовать фактами ради уникальности | T-4310/T-4311 |
| 24 | Analytics lineage | T-4313 |
| 25 | truth-set A–O | T-4315 (+распределение по tasks.md) |
| 26 | self-quote E2E скриншот-регресс | T-4317 |
| 27 | prod acceptance §37 | T-4319 |
| 28–30 | справка «Мозг бота» + доставка | T-4320 |
| 31 | REUSE §33, нет параллельного стека | эта спецификация (§7) + T-4275/T-4278 |
| 32 | conflict matrix confirm | T-4275 (PM, precondition `PLANNING_CONSISTENT`) |

**Build order §35 — подтверждён без изменений** (13 шагов как в ТЗ). Примечание: блок H (freshness, T-4307–T-4312) не зависит от блоков D–G и допускает параллельный трек после C3; финальная последовательность merge-проверок — по tasks.md.

---

## 6. Acceptance §37 — mapping

| Группа §37 | Как проверяется | Где закреплено |
|---|---|---|
| Attribution: reply / partial quote / third-party fact / bot self-quote | truth-set A/B/C/G + prod-чат; bundle показывает роли | T-4315, T-4319; §36-1/2 |
| Memory: source card / graph provenance / correction event | Analytics card (C8+Z8), `conflict_status`-трейс; Browser check виджета | T-4313, T-4319; §36-12 |
| Retrieval: exact source / vector candidate / conflict | truth-set K + arbitration C8; candidates несут subject/speaker | T-4297/T-4301, T-4319 |
| Freshness: одинаковый вопрос двумя разными messages | EXPECT: нет literal dedup replay; 2 processing traces; generation вызван; previous answer в context; formulation естественная. Проверять отсутствие cache replay + bounded guard, НЕ «LLM выдал другие символы» (анти-flaky) | T-4309/T-4310/T-4319; §36-10 |
| Idempotency: повторная доставка update | нет второго reply/LLM-charge (метрика + событие `DIRECT_UPDATE_DEDUP_HIT`) | T-4307, T-4319; §36-11 |

---

## 7. Правила §33 — reuse matrix (не появился второй контракт)

| Существующее | Статус | MCA-22 |
|---|---|---|
| MCA-03 identity (`smart_messages`+roles, revisions, source records) | в проде (v16) | **переиспользует** как единственный источник идентичности; достраивает только read-side (projection) |
| MCA-04/04a provenance (`mca_source_refs/evidence_links/status`, словари) | в проде (v17) | **переиспользует**; correction/llegacy-политика — над существующими статусами, второй provenance-контракт запрещён |
| MCA-04b dossier (v20; Layer A/B, staging) | в проде | **переиспользует**; один validator live/rebuild (C4); rebuild уже с SourceRef — live подтягивается |
| MCA-07 retrieval/EvidenceBundle/cache policy (v18) | в проде | **переиспользует** движок; bundle v2 и кандидаты — эволюция существующего контракта под его гейтами; no-replay — production closure правила MCA-07 |
| mca-05 episodes (v21) | в проде | **переиспользует** (episodes-first, participant roles); recheck-очередь редактирований |
| MCA-08/18 personality | в проде | не трогается; атрибуция только делает формулировку честнее |
| MCA-17 Analytics | в проде | расширяет существующие виджеты, новый корневой dashboard запрещён |
| MCA-21 справка | закрыта | повторная актуализация тем же механизмом/стилем (T-4320) |
| ASAP-3/3.1/3.2 | закрыты | model capacity/budgets/provider lifecycle/Summary transport не трогаются |
| mca-01 `task_jobs`/`write_transaction`, mca-13 `mca_events`, mca-14 `MigrationStep`, mca-17a registry | в проде | ledger-backfill (если будет) — `task_jobs`; события/lineage — `mca_events`; DDL — `MigrationStep` v22 |

---

## 8. Reviewer checklist

**Применимый чеклист — §36 ТЗ (12 критериев непринятия), evidence — T-4318:**
1. quote ≠ слова quoting user → truth-set A, C3; 2. third-party claim ≠ speaker → C4, truth-set L; 3. SourceRefs materialized → C4/C5; 4. bot output доступен после TTL fast-cache → C2, truth-set G/H; 5. bot output ≠ proof внешнего факта → C2; 6. graph edges provenance-backed либо legacy/unverified → C5; 7. retrieval переносит subject/speaker → C5; 8. bundle structure-first → C6; 9. correction делает revalidation → C8, truth-set E; 10. different TG message same text без literal cached answer → C7, truth-set M/O; 11. duplicate update idempotent → C7, truth-set N; 12. Analytics прослеживает ошибку атрибуции → Z8/T-4313.

**Насчёт «§87»: секция 87 «Reviewer checklist» относится к блоку ASAP-3.2 (`current_task.md:13924`) — image/provider/GraphRAG-lifecycle инварианты, вне изменяемой поверхности MCA-22 (image/provider-код фича не трогает). К примирению с PM: для MCA-22 чеклист — §36; пункты §87 проверяются отдельной регрессией закрытого ASAP-3.2 при необходимости, не этой фичей.**

Mock-only acceptance недостаточен (§36): обязательны real DB integration, real SourceRefs, real retrieval path, real Direct pipeline, tool-loop fixture, live-like Telegram objects, Browser Analytics checks.

---

## 9. Failure modes / тесты / откат (R3-обязательства)

| Риск | Митигирование | Проверка |
|---|---|---|
| Ложная идемпотентность (разные updates склеены) | dedup строго по `(chat_id, tg_message_id, revision)`, не по тексту | truth-set M/N/O, T-4307 |
| Literal replay выживает на непроверенной ветке | аудит матрицы веток (§19) + guard на общем send-path + метрика replay-rate | T-4308/T-4314 |
| Semantic inversion (negation/quote) | speech-act gating + negation guard | truth-set D/A, T-4292/T-4293 |
| Регрессия read-path закрытых MCA-фич | OFF-паритет 4 рубильников; интеграционные тесты на включённых фичах | T-4281/T-4282, T-4318 |
| Auto-bind по похожему имени (backfill/legacy) | запрет auto-bind; unresolved честно | T-4304, §31 |
| N+1 canonical read | batched projection + per-request map; счётчик запросов | T-4285 |
| Ложные срабатывания duplicate guard | exemptions §18 + bounded 1 attempt | T-4311 |
| Flaky freshness-приёмка | проверять отсутствие cache replay, не «другие символы» | T-4319 |
| Дублирование памяти при повторной доставке | ingestion уже идемпотентен; memory-запись после dedup-гейта | T-4307 |
| Загрязнение human-only corpus bot-текстом | ledger изолирован; в `smart_messages` не пишем | T-4286/T-4289 |

Откат: hot — 4 рубильника (env-only; OFF = паритет); cold — `git revert`; DDL v22 аддитивен (остаётся, безвреден). Никакой существующей MCA/ASAP функции не заменяется параллельным дубликатом (DoD-31).

---

## 10. Расхождения/вопросы к PM (для T-4278)

1. **«Reviewer checklist §87»** в задании Orchestrator — ссылка на блок ASAP-3.2 (`current_task.md:13924`); для MCA-22 применим §36 (12 критериев). §87 учитывается только как регресс закрытого ASAP-3.2, не гейт этой фичи.
2. **`threat-failure-analysis.md`**: tasks.md:14 требует отдельный файл при R3. В этой спецификации failure-анализ дан инлайн (§9). Решение требуется: либо отдельный файл создаёт @Architect до старта Build (T-4279), либо фиксируется, что §9 spec удовлетворяет обязательству. Дефолт @Architect: отдельный файл не плодим — §9 считается выполнением обязательства, если PM не возразит в T-4278.
3. **Ingestion-фикс `quote_author_id`** (Q3a) формально меняет writer-строку `handlers/summary.py` — входит в C1 (T-4279–T-4283); подтверждение, что это не считается «изменением identity model» MCA-03 (по §1 не является: поле уже в схеме, заполняется честным значением из metadata).
4. **prod-env переопределения гейтов** (Q12/Q13) из репо неверифицируемы — в чеклист T-4319 добавлена явная проверка отсутствия OFF-override `MCA_CONTEXT_ANSWER_CACHE_ENABLED`/новых рубильников на живом стенде.

## MEMORY_DELTA (для @Memory/Orchestrator)

- mca-22 design закрыт: `spec.md` + `adr-1028-6-attribution-memory-coherence.md` (Proposed), Risk **R3** ратифицирован, deploy пер-фичевый + prod-acceptance §37, merge §109+.
- Санкции: DDL **v22** = только `mca_bot_outputs` (+3 индекса), PG no-op; kill-switches ровно 4 (`MCA_CANONICAL_ATTRIBUTION_ENABLED`, `MCA_BOT_OUTPUT_LEDGER_ENABLED`, `MCA_CORRECTION_REVALIDATION_ENABLED`, `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED`); Δ каталога 0 (F8 NOT_APPLICABLE); reason_code +12.
- Ключевые RCA-факты: quote_author_id теряется на ingestion; роль-колонки v16 не выбираются read-функциями; bundle = regex от render-строк, author==addressee, source_ref_id=None; bot outputs живут 3600 c (bot_replies) либо нигде; update-identity дедупа нет; «запомни»/self_reply пишут факты без SourceRef.
- Следующий шаг: @Orchestrator — design → PM сверка T-4275/T-4278 (`PLANNING_CONSISTENT`, precondition conflict-аудит §33), затем Build.
