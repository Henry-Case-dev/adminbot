# ADR-1028-6 — MCA-22: сквозная атрибуция, согласованная память и естественная свежесть ответов

> **Фича:** `mca-22-attribution-memory-coherence` (FINAL INTEGRATION Epic, P0/P1)
> **Статус:** Proposed — 01.10.2026 (Step 2 @Architect, T-4276) → **Accepted** (Merge `plans/ARCHITECTURE.md` §109, T-4321) → **+ prod-validated (full): 02.10.2026 прод 2.58.44 VERIFIED (feat `9c78760`, prod-HEAD `aa9031a`, health 200) — см. «Прод-валидация и история статуса»**
> **Спека:** `plans/features/mca-22-attribution-memory-coherence/spec.md` (RCA по зонам, Q1–Q17, контракты C1–C8, санкции §4)
> **ТЗ:** `plans/current_task.md:15305–16480` (§0–§39), блок SHA-256 `ad389212…660c`
> **Baseline:** прод 2.58.43 (прод-HEAD `9906c9d`), SQLite DDL v21, каталог 488/427/463/105/103/21, локальный HEAD `7a86179`
> **Предыдущие ADR:** 1028-5 (asap-32) — коллизий нет; **1028-6 свободен** (проверено по `plans/archive/*/adr-*` и рамке §4)

## Контекст

После MCA-03/04/04b/05/07 отдельные механизмы (identity, SourceRef/EvidenceLink, retrieval, dossier, episodes) работают, но сквозная структура теряется между слоями: БД знает роли/revision/provenance, а readers/renderers получают 11 колонок, рендер-строки и regex-собранный EvidenceBundle; реально отправленные ответы бота живут 3600 секунд (TTL `bot_replies`) либо нигде; update-identity идемпотентности нет; conversational финальный ответ кешировался по нормализованному тексту (политика MCA-07 закрыла основную ветку, но clozure на всех ветках не доведена). Задача MCA-22 — один инвариант «однажды установленное авторство/субъект/источник/время/revision не теряется и не угадывается заново» + отмена literal replay финальных ответов при сохранении идемпотентности update.

## Решения

### D1 — Canonical read = runtime DTO/projection поверх существующих таблиц (не новая БД)

**Выбрано:** frozen-DTO `CanonicalMessage` + batch projection-функция (`get_canonical_messages`) над `smart_messages`/`message_source_records` с полным набором роль/время-колонок (v16). Перевод 12 consumers §2 на контракт.
**Альтернативы:** (a) новая БД/таблица сообщений — отвергнуто (§2 прямо: «runtime DTO/projection, а не новую независимую БД»; второй stack запрещён §1); (b) всем consumers читать сырые ряды самим — отвергнуто (роли снова теряются; статус-кво и есть проблема).
**Следствия:** SELECT-функции (`get_smart_window`, `get_smart_raw`, `search_messages_fts`) расширяются; per-request maps/batched lookup против N+1 (§30); ingest-фикс: `quote_author_id` извлекается из `message.quote` (поле уже в схеме — это не изменение identity model, а заполнение честного unknown значением metadata).
**Затронутые контракты:** mca-03 (read-side), mca-07 (composer/retrieval read), mca-04b (live/rebuild читают projection). Kill-switch: `MCA_CANONICAL_ATTRIBUTION_ENABLED`.

### D2 — Own Output Ledger: отдельная durable-таблица `mca_bot_outputs` (DDL v22), наружу через SourceRef

**Выбрано:** минимальный output store `mca_bot_outputs` (v22, аддитивно, PG no-op), запись только реально доставленных outputs; чтение через quote resolver/thread_chain/Analytics; SourceRef `entity_type='message', entity_id='bot_output:<id>'`.
**Альтернативы:** (a) писать bot-сообщения в `smart_messages` — отвергнуто: FTS/окно/L1/L2/persona/GraphRAG трактуют таблицу как human-only corpus (§4 прямо предупреждает); (b) расширить `bot_replies` — отвергнуто: это TTL+LRU кеш по контракту 63.1, PK/поведение нельзя ломать; (c) не хранить durable — отвергнуто: кейсы §4/§14/§15 (reply на Summary, self-quote) не решаются.
**Следствия:** DDL v22 — единственная schema-дельта фичи; `bot_replies` остаётся fast cache; self-output = evidence «бот говорил X» c `independence='self_referential'`, никогда не independent proof внешнего факта.
**Kill-switch:** `MCA_BOT_OUTPUT_LEDGER_ENABLED`. Затронутые: mca-03/04a (SourceRef interface), 63.1 (bot_replies не меняется).

### D3 — Quote Resolver: единая детерминированная лестница 1–7

**Выбрано:** priority ladder §5 (native reply → TG quote metadata → exact in parent → exact/normalized in thread → ledger → bounded historical → unresolved); deterministic metadata раньше LLM (§29); fuzzy match ≠ авторство; sender ≠ автор цитаты по умолчанию; partial quote наследует parent speaker.
**Альтернатива:** LLM-first резолв цитат — отвергнуто: дорого, недетерминированно, склонно к hallucinated binding; §29 требует обратного.
**Kill-switch:** общий `MCA_CANONICAL_ATTRIBUTION_ENABLED` (отдельный не нужен — resolver без read-контракта не существует).

### D4 — Claim Envelope: runtime DTO + существующая persistence (без новой таблицы)

**Выбрано:** `ClaimEnvelope` как runtime-контракт; persist через существующие `graph_facts` v17-колонки (`subject_ref_id/attribution_method/assertion_kind/speaker_author_id`) + `mca_evidence_links` (`claim_key`, `checks_json` = author/object/time/negation/quote/joke/retelling/actuality) + `mca_provenance_status` (conflict/freshness). Speech-acts question/hypothesis/command/joke — write-gating (personal fact не создаётся), не колонки.
**Альтернативы:** (a) новая SQL-таблица claim envelope — отвергнуто: §6 «сначала проверить выразимость» — она доказана (весь словарь уже в проде, `provenance.py:46–84`); (b) новые колонки `speech_act/stance/negated` — отвергнуто: дублируют `checks_json`/link-семантику, DDL без необходимости нарушает §31.
**Следствия:** negation guard опирается на `checks_json.negation`; «Я не говорил, что X» не создаёт positive X (truth-set D).

### D5 — Speaker ≠ Subject: запрет fallback `subject=sender`, producer-validator единый

**Выбрано:** субъект без доказательства → unresolved-candidate / world-chat fact / skip personal write + diagnostic reason; все personal-fact producers («запомни», self_reply, bot_direct_reply, memes/portraits, summary-derived) проходят один validator с исходами `accepted+source / tentative+source candidate / unresolved / rejected`; Layer A local line → SourceRef сразу после parse (локальный номер — не durable evidence).
**Факт-база:** сегодня 5 producers пишут личные факты без SourceRef (Q7 — `remember_user_fact`, `memorize_self_reply`, bot_direct_reply вне post-хука, chat_meme/portrait, summary-derived).
**Kill-switch:** `MCA_CANONICAL_ATTRIBUTION_ENABLED` (+ уважение `MCA_FACT_ATTRIBUTION_ENABLED`/`MCA_PROVENANCE_ENABLED`).

### D6 — GraphRAG provenance: enforcement на запись, legacy — маркировка, не удаление

**Выбрано:** person-affecting edges требуют provenance (assertion + SourceRef/EvidenceLink + speaker + subject + revision + temporal); bare edge не поднимается в confident; legacy edges — `unverified`/weak hint, восстановление при востребованном чтении (`reconstruct_fact_provenance`); независимость по unique evidence roots (`evidence_independent_count`), повтор пересказа не считается подтверждением; конфликт (`contradicts/supersedes`) обязателен к показу downstream.
**Альтернатива:** массовый backfill всех legacy edges — отвергнуто: auto-bind по имени запрещён §31; восстановление — только exact/search-backed, bounded, по потребности.

### D7 — Retrieval/EvidenceBundle: structure-first, роли и SourceRefs обязательны

**Выбрано:** `RetrievalCandidate` дополняется subject/speaker/assertion_kind/verification/origin/contradiction_status + заполнение `source_ref_id`; rerank учитывает identity-фильтры наравне со сходством (exact subject match сильнее vector hit про другого); `EvidenceBundle` v2 строится из CanonicalMessage+Candidates **до** рендера (regex-парсинг render-строк устраняется), с раздельными author/direct_addressee/reply_addressee/quoted_speaker и реальными SourceRefs; tool loop дополняет bundle, не пересобирает.
**Факт-база:** сегодня bundle собирается regex-ом по отрендеренным блокам, `author==addressee==target_name`, `source_ref_id=None` (spec Z5).
**Kill-switch:** эволюция под существующими `MCA_RETRIEVAL_CONTEXT_ENABLED`/`MCA_EVIDENCE_BUNDLE_ENABLED`/`MCA_TYPED_RERANKER_ENABLED` (новых не добавляем — mca-07 движок не переписывается).

### D8 — Freshness closure: update-idempotency по identity, no-replay по политике, bounded duplicate guard

**Выбрано:** (1) дедуп Telegram update строго по `(chat_id, tg_message_id, revision)` — маркер в существующей `smart_cache` (без DDL); (2) финальный conversational ответ не кешируется между разными messages (разрешён только intermediate-кеш); (3) при точном совпадении нового ответа с недавним — максимум одна regeneration с фиксированным hint, exemptions §18, paraphrase-процессор запрещён; (4) lineage-события `DIRECT_*` через `mca_events` без private content; (5) второй generation context видит предыдущий ответ (через thread_chain/ledger).
**Альтернативы:** (a) keep legacy text-dedup — отвергнуто: он и есть literal replay, не различает update identity; (b) durable update-dedup таблица — отвергнуто: single-process бот, TTL-маркера в `smart_cache` достаточно (перезапустился после сбоя → максимум один повторный ответ, приёмлемо).
**Kill-switch:** `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED`; совместимость с `MCA_CONTEXT_ANSWER_CACHE_ENABLED`/`CHAT_DEDUP_ENABLED` — уважаются, не дублируются.

### D9 — Correction: только существующие статусы

**Выбрано:** correction path создаёт `contradicts`-EvidenceLink (`verification='tentative'`) + `conflict_status='conflicting'`; revalidation — существующий reconstruction → `resolved` либо остаётся `conflicting`; superseded — `supersedes`+`freshness_status='superseded'`; disputed = проекция `conflicting` (новых enum-значений нет); user correction — сигнал, не абсолют; edit-инвалидация — существующие `source_revision_changed`/recheck.
**Альтернатива:** новые статусы `disputed/revalidation_pending` в словарях — отвергнуто: дублируют `conflict_status`, второй статусный контур запрещён §12/Q11.

### D10 — Санкции (финал T-4277)

- **DDL v22** (единственная): `mca_bot_outputs` + 3 индекса (точный DDL — spec §4.1); реестр `MigrationStep`, аддитивно/идемпотентно, PG no-op; §31-обоснование: durable ledger без загрязнения human-only corpus невозможен на существующих таблицах.
- **Kill-switches: ровно 4** (см. D1/D2/D8/D9) — все env-only, default ON, OFF = паритет baseline; developer-switches не плодим (§32).
- **Δ каталога = 0**; F8 (ADR-1026-2) NOT_APPLICABLE.
- **reason_code +12** (spec §4.3); имена `DIRECT_*` — свободная ось event_name mca-13.
- **Deploy:** пер-фичевый + prod acceptance §37 (Epic вне волн §20); hot-откат — 4 рубильника, cold — `git revert`, DDL остаётся (безвреден).
- **Merge:** `plans/ARCHITECTURE.md` §109+ (хвост §108 = mca-05), этот ADR → Accepted по Merge.
- **Risk: R3** (ратифицирован; см. spec шапку и §9 failure-таблицу).

## Риски и последствия

- Регрессия read-path закрытых MCA-фич — главный риск: паритет обеспечивается OFF-режимами 4 рубильников и интеграционными тестами на включённых фичах (§36 mock-only недостаточен).
- Стоимость: +1 regeneration в редком guard-срабатывании; deterministic-first резолвы; intermediate-кеш сохраняется.
- Совместимость: `smart_messages`/`bot_replies`/`graph_facts`/`mca_source_refs` контракты не ломаются (только расширение SELECT и добавление записи в новую таблицу); `pg_db.py` вне diff.
- Отказ от standalone `threat-failure-analysis.md` в пользу инлайн-таблицы spec §9 — помечено PM на T-4278 (spec §10.2).

## Прод-валидация и история статуса (reconcile @Architect, 02.10.2026)

**История статуса:**

1. **01.10.2026 — Proposed (design):** решения D1–D10 утверждены этим ADR; спека Risk **R3** (spec шапка + §9 failure-таблица), санкции §4 (DDL v22 единственная, kill-switches ровно 4, reason_code +12, Δ каталога 0).
2. **01.10.2026 — Round 2 Review: APPROVED FOR RELEASE** (M-1…M-4 RESOLVED 4/4, 0 blocking; binding: Reviewed-Commit `7a86179` — совпадает с prod-базой релиза, spec-hash `C4B4043E…` воспроизведён байт-в-байт, tasks-пин `E17B0D5A…` MATCH).
3. **01.10.2026 — Merge → Accepted:** feat `9c78760` (55 файлов, +4352/−73) + docs `aa9031a`; push `7a86179..aa9031a` fast-forward; merge `plans/ARCHITECTURE.md` §109 ратифицирован reconcile 02.10.2026.
4. **02.10.2026 — прод 2.58.44 VERIFIED** (деплой 04:08–04:35 UTC+12; deploy-doc `7e33d9f`; прод-HEAD `aa9031a`, health 200) — **Accepted + prod-validated (full)**: все контуры D1–D10 живы (детали ниже). Сами решения D1–D10 не менялись; approval ревью не инвалидирован — код `9c78760` соответствует ревью-манифесту round 2 (пер-файловые пины spec/ADR/tasks MATCH; агрегат WTH отличается ровно самореференс-оговоркой пина — `review.md` переписан после фиксации пина, остальные 32/32 файла покрыты пином: mtime-freeze 28 product/test-файлов + numstat-кромки `memory_agi.py` 168+/1− и др.; полный pytest **10520/2** = ревью-числа, оба failed — pre-existing чужие bounds-пины round1026). Правки этого reconcile — docs-only.

**Прод-валидация 2.58.44 (evidence — `deployment.md` §3–§9):**

- **Деплой/гейты:** прод ff `e84600e..aa9031a` (прод-код до — отревьюенный хотфикс-базис 2.58.43, 3 docs-коммита позади); рестарт #2 active 16:19:04 UTC (PID 2796224, NRestarts=0); `GET /api/health` → **200 `{"status":"ok"}`**; runtime `APP_VERSION` **2.58.44**.
- **DDL v22 применена идемпотентно при старте 16:19:22 UTC:** авто-бэкап до DDL guard'ом mca-14 (`pre_migration_20261001_161922.db`, 1.2 GiB) → `user_version` 21→**22**, таблица **`mca_bot_outputs`** + ровно 3 индекса, **0 строк** (чистая append-only книга); данные целы (smart_messages 1 989 659, сверено с пре-миграционной копией); PG no-op. Инцидент рестарта #1 (`MigrationBackupError` — fail-closed guard свободного места mca-14, диск был 89% до деплоя) стабилизирован удалением дублирующего ручного и устаревших миграционных бэкапов **без отката кода**; дефект кода отсутствует, защита отработала как задумана (deployment.md §4; операционный долг по диску — backlog Follow-up mca-22).
- **Гейты фичи:** kill-switches ровно 4 — все **ON** (runtime-резолв `canonical_attribution_enabled` / `bot_output_ledger_enabled` / `response_freshness_guard_enabled` / `correction_revalidation_enabled`; Δenv=0); ladder/parity **82 passed** на прод-venv (core 58 + truthset 24, вкл. OFF-паритет всех контуров и лестницу цитат); каталог F8 **488 CHECK OK, Δ=0**; новые API `/api/memory/attribution/trace` и `/api/memory/attribution/metrics` → **401** без auth (эндпоинты живы, admin-only RBAC на месте); R17-скан журнала чист; 0 посторонних ошибок (весь error-фон — известный класс GraphRAG embed-429, вне фичи).
- **Честные границы (не acceptance):** ledger пуст до первого доставленного direct-ответа; live-смоук prod-acceptance §37 (**T-4319**) и UI-гейты **T-4317/T-4320** — за владельцем (Browser smoke 2.58.44 NOT_APPLICABLE — `web/app.js` вне диффа); edit→revision ledger-хвост T-4287 — с UI-инкрементом. Резюме — `plans/backlog.md` (Follow-up mca-22).

## Связанные документы

`plans/features/mca-22-attribution-memory-coherence/spec.md` · `tasks.md` (T-4273…T-4322) · рамка `plans/docs/mca-round1027-arch-frames.md` (§1 механизм DDL, §3 политика kill-switch, §4 нумерация) · ADR-1027-4/6/7/9/12 (mca-03/04a/07/04b/05 — reuse-база).
