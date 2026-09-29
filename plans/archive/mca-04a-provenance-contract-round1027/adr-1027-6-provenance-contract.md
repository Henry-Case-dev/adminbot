# ADR-1027-6 — `mca-04a-provenance-contract`: типизированные SourceRef/EvidenceLink, статусы происхождения, правила восстановления §8.2, единая семантика личного факта §8.3.2 — Δ DDL = v17, Δ каталога = 0, R3

- **Статус:** **Accepted** — фактом Merge в `plans/ARCHITECTURE.md` **§98** (27.09.2026, T-3835/T-3836; было `Proposed`).
- **Фича:** `mca-04a-provenance-contract` (Wave 1, данные, P0-предпосылка для `mca-07`). **Deploy:** `DEFERRED_TO_RELEASE`.
- **ТЗ-основание:** `plans/current_task.md` §8.1 (`:208–226`), §8.2 (`:228–236`), §8.3.2 (`:268–280`); §2.3/§4 (`:23`,`:77–101`); §3/§3.1 (`:47`,`:60–75`); §17.1–§17.3 (`:818–844`); §18 (`:856–872`); §19 A09/A10/A85/A86/A88/A95; §22; R17/R18.
- **Baseline:** Reviewed-Commit `05bc870`; `APP_VERSION` 2.58.31; SQLite DDL **v16** (после `mca-03`); каталог `473/430/448/102/100/21`; канон 12.
- **Связано:** AMEND `services/database.py` (`graph_facts` provenance-колонки + v17), `services/summary_memory.py`, `services/direct_chat_service.py`, `services/lore_worker.py`, `services/dossier_prompts.py`; NEW `services/provenance.py`; REUSE `mca-03` (`(chat_id, tg_message_id)`/namespace/`source_record_id`/`message_revisions`), `source_ids`/`graph_facts`, `write_transaction`/`serialized()` (`mca-01`), `emit_mca_event`/`mca_events` (`mca-13`), `MigrationStep` (`mca-14`), `thread_chain`, SafeFetcher (`mca-02`); Unblocks `mca-07`; рамка `plans/docs/mca-round1027-arch-frames.md`.

## Контекст

§8.1 требует типизированную ссылку на источник и типизированную связь «производное ↔ источник»: `store/entity_type/entity_id/chat_id/revision`, для оригинала — `tg_message_id`/`dataset_id`; SQLite fact ID, PG row ID и Telegram message ID **не** взаимозаменяемы. EvidenceLink несёт объект+версию, источник+версию, тип (`derived_from`/`supports`/`contradicts`/`mentions`/`supersedes`), способ установления, статус проверки, время, версию экстрактора и проверяемое основание. Производное утверждение хранит статус происхождения `original/reconstructed_support/tentative/unknown`, при этом конфликтность/актуальность/покрытие — **отдельные** поля; собственные ответы бота не подтверждают факты о людях; личные предпочтения персонажа отделены от фактов. §8.2 задаёт правила восстановления старых записей: сохранить ID, прямое→поиск→контекст, проверки, вектор-кандидат, покрытие по каждому утверждению, ambiguous→tentative, `reconstructed_support`≠`original`, неподтверждённое не удалять. §8.3.2 задаёт единую семантику личного факта (speaker/subject/mentioned/source, устойчивый ID, unresolved, self-report, третье лицо), а §8.3.1 фиксирует конкретные разрывы кода.

**Фактическое состояние baseline (сверено с рабочей веткой):** `graph_facts` (`database.py:607–624`) не имеет provenance-полей/ссылок; `origin` — CHECK-ограниченный список; `target_user` — канон-имя, не ID. `_memorize_direct_reply` (`direct_chat_service.py:2168–2240`) ставит `target_user=asker_canon` и `_reassign_fact_owners` переназначает по имени; `_memorize_facts_inner` (`summary_memory.py:2037–2241`) пишет переданный target. `get_persona_card`/`get_user_context_facts` (`database.py:5769–5820`) читают `confirmed` по `target_user`-имени. `_classify_dossier_multilayer`/`_classify_chunked_user` (`lore_worker.py:636–875`) пишут портреты/мемы, но не сохраняют `person_facts`; `filter_layer_a_candidates` (`dossier_prompts.py:335–379`) не валидирует соответствие/границы. Все разрывы §8.3.1 п.1/2/3/5-контракт присутствуют. Прецедент хранения производных досье: мемы как `graph_facts` c `origin='chat_history'` + `status='chat_meme'` (нулевой DDL).

## Решения

**D1. SourceRef — типизированный opaque-адрес в реестре.**
- **Выбрано:** SourceRef = `store` (`sqlite`|`postgres`|`telegram`|`external`|`legacy`), `entity_type`, `entity_id` (opaque в пространстве store/type), `chat_id`, `revision`; для оригинала-сообщения — `tg_message_id` (только для message) и `dataset_id`/`source_record_id` (mca-03 namespace/occurrence); `resolution` (`resolved`|`unresolved`|`unknown`). Хранение — реестр `mca_source_refs` с дедупом по `(store, entity_type, entity_id, chat_id, revision)`.
- **Обоснование:** §8.1 (`:212`); A88; GEN-R4 (типизированные межбазовые ссылки). `entity_id` никогда не сравнивается между store; SQLite/PG/TG ID не смешиваются.
- **Альтернатива:** хранить строку вида `"sqlite:graph_fact:123"` — отклонено (плохо типизируется, смешивает пространства, неудобно индексировать/валидировать); отдельные таблицы на каждый store — отклонено (фрагментация provenance).

**D2. Связь с контрактом MCA-03 (один контракт идентичности).**
- **Выбрано:** SourceRef сообщения **ссылается** на `(chat_id, tg_message_id)`/namespace/`source_record_id`/revision (mca-03), внутренний `smart_messages.id` — `entity_id` при `store='sqlite'`,`entity_type='message'`; `tg_message_id` — отдельное поле. Второй контракт идентичности/версий запрещён.
- **Обоснование:** §96.1/§96.4 (`mca-04a` строится поверх контракта MCA-03); GEN-R19 (REUSE, не вторая реализация).

**D3. EvidenceLink — объект+источник с версиями + полный набор полей.**
- **Выбрано:** `subject_ref_id`+revision, `source_ref_id`+revision, `link_type` (5), `method` (direct_reference|metadata|exact_search|semantic_search|reply_context|thread_context|migration_backfill|manual|unknown), `verification`, `independence`, `claim_key`, `extractor_version`, `basis`, `checks_json`, `established_at`. Дедуп по `(subject_ref_id, source_ref_id, link_type, claim_key)`.
- **Обоснование:** §8.1 (`:214–222`) verbatim; A09/A86.
- **Альтернатива:** `source_ids` JSON как единственный носитель связи — REUSE для типизации существующих строк, но недостаточен (нет версий/типа/статуса/основания/независимости); отдельная JSON-колонка на каждом объекте — отклонено (нельзя запрашивать/индексировать, дублирование).

**D4. Независимость доказательства и запрет самоподтверждения.**
- **Выбрано:** `independence ∈ {independent, self_referential, unknown}`; в подтверждении участвуют только `independent`+`verified` связи `derived_from`/`supports`. Ответы бота → `self_referential`, не подтверждают факты о людях. Два вывода из одного SourceRef — одно доказательство (A10). `claim_key` обеспечивает покрытие по каждому утверждению.
- **Обоснование:** §8.1 (`:226`); A10; §8.2 (покрытие).
- **Альтернатива:** считать любой сохранённый источник независимым — отклонено (прямо запрещено §8.1; ведёт к самоподтверждению).

**D5. Статусы происхождения + отдельные поля.**
- **Выбрано:** `origin_status` — только происхождение (`original`/`reconstructed_support`/`tentative`/`unknown`); `conflict_status`, `freshness_status`, `coverage_status`+`coverage_covered`/`coverage_total` — **отдельные** поля (таблица `mca_provenance_status` 1:1 с объектным SourceRef). `original` — только из сохранённого при создании прямого источника.
- **Обоснование:** §8.1 (`:224`) verbatim («конфликтность, актуальность и полнота покрытия — отдельные поля, а не взаимоисключающие значения»); A09/A10.
- **Альтернатива:** одно поле-перечисление с комбинациями — отклонено (§8.1 запрещает; одно утверждение может иметь источник и быть устаревшим).

**D6. Правила восстановления §8.2.**
- **Выбрано:** сохранить записи/ID; порядок direct→exact→semantic→reply/thread; проверки автор/объект/время/отрицание/цитата/шутка/пересказ/актуальность (в `checks_json`); вектор — candidate (`tentative`) до проверки; покрытие по `claim_key`; ambiguous→`tentative`; `reconstructed_support` не переименовывать в `original`; не удалять неподтверждённое; ложный `original` не создавать. Backfill v17 — только прямые ссылки (без семантики).
- **Обоснование:** §8.2 (`:232–236`) verbatim; A09/A10/A95.
- **Альтернатива:** семантический поиск в backfill как источник `original` — отклонено (§8.2 прямо запрещает; A09).

**D7. Единая семантика личного факта §8.3.2.**
- **Выбрано:** на `graph_facts` — `subject_ref_id` (устойчивый субъект), `attribution_method` (self_report/third_party/direct_evidence/bot_self_reply/world_knowledge/unknown), `assertion_kind` (biographical/preference/event/relation/opinion/world_knowledge/unknown), `speaker_author_id` (автор из MCA-03), `extractor_version`, `provenance_channel`; раздельные времена — из MCA-03 (`message_timestamp`/`tg_message_id`/`created_at`); статус подтверждения — `graph_facts.status`; происхождение/конфликт/актуальность/покрытие — `mca_provenance_status`. Импорт без TG ID → SourceRef `resolution='unresolved'`; одноимённые не сливаются; упоминание имени ≠ доказательство; self-report допустим; третье лицо — `third_party`.
- **Обоснование:** §8.3.2 (`:270–278`) verbatim; A85/A86/A95.
- **Альтернатива:** хранить субъект только именем (`target_user`) — отклонено (§8.3.2: устойчивый ID; одноимённые).

**D8. FIX-точки 04a (§8.3.1 п.1/2/3 + контракт п.5).**
- **Выбрано:** (1) `_memorize_direct_reply` — субъект-атрибуция вместо `target=asker`, `_fact_owner_canon`/`_reassign_fact_owners` заменяются валидируемой атрибуцией; (2) `get_persona_card`/`get_user_context_facts` — subject-scope по `subject_ref_id`, исключение `world_knowledge`/self-referential, одинаково в UI/`get_user_context`/RAG; (3) Layer B person_facts сохраняются независимо от портрета (REUSE-паттерн `origin='chat_history'`, CHECK не расширяется); (5-контракт) локальные evidence→постоянные SourceRef + строгий валидатор `filter_layer_a_candidates`. Всё через существующие write-пути; уже исправленное — тестом (по факту не исправлено).
- **Обоснование:** §8.3.1; A85/A86/A88; REUSE §3.1.

**D9. Producers/consumers и REUSE.**
- **Выбрано:** producers — `summary_memory`/`direct_chat_service`/`lore_worker`/`dream_worker`/импорт; consumers — `get_persona_card`/`get_user_context_facts`/`tool_router`/`image_context_memory`/`chat_lore` (UI). `source_ids` типизируются в SourceRef; `graph_facts`/`message_source_records`/`message_revisions`/`thread_chain`/SafeFetcher — REUSE. Второй контракт не создаётся.
- **Обоснование:** GEN-R19; §3/§3.1; §4 (один контур).

**D10. Δ DDL = v17; legacy-совместимость; индексы по запросам.**
- **Выбрано:** `mca_source_refs`, `mca_evidence_links`, `mca_provenance_status` + 6 nullable-колонок `graph_facts`; аддитивно через `MigrationStep`; backfill только прямые ссылки (bounded/resumable, guard по объектному SourceRef); `origin` CHECK не трогается; PG no-op; индексы — только под `EXPLAIN QUERY PLAN`.
- **Обоснование:** §18 (`:864–866`); MCA14-R1/R2; A87/A88.
- **Альтернатива:** rebuild `graph_facts` для расширения `origin` CHECK — отклонено (риск на большой таблице; требование аддитивности).

**D11. Δ каталога = 0 + kill-switch.**
- **Выбрано:** `MCA_PROVENANCE_ENABLED`, `MCA_FACT_ATTRIBUTION_ENABLED`, `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` — env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline; приоритет: reconstruction/attribution инертны при `MCA_PROVENANCE_ENABLED=OFF`. F8 NOT_APPLICABLE.
- **Обоснование:** §18 (`:872`); MCA14-R5; рамка §2/§3; прецедент `DB_LOCK_RESILIENCE_ENABLED`.

**D12. Наблюдаемость и R17.**
- **Выбрано:** `start`+`outcome` через `emit_mca_event`/`mca_events`; расширение `reason_code`: `provenance_linked`, `provenance_unresolved`, `evidence_invalid`, `provenance_reconstructed`, `provenance_conflict`; стадии/виджет-ID для `mca-17a`; `sanitize()` до записи; `basis`/`checks_json` — короткие коды, без CoT; SourceRef вместо сырого контекста.
- **Обоснование:** §17.1–§17.3; §27.1; GEN-R14/R17; A27/A53.

**D13. Границы, carry-over, risk, deploy.**
- **Выбрано:** 04a = контракт/атрибуция (п.1–3, контракт п.5); 04b = пересборка/job/врезка п.5. Потребители (`mca-07`/`05`/`06`/`16`/`18`/`19`/`20`) расширяют, не заменяют. L-MCA03-8 — **не** в 04a, обязательный вход `mca-04b` (версионировать отпечаток при фиксе). Risk **R3**; deploy `DEFERRED_TO_RELEASE`; hot env-OFF; cold `git revert`→`05bc870`.
- **Обоснование:** tasks.md T-3819; §2.4–2.5; §20.

## Санкции и вердикты

- **Δ DDL = v17** — три таблицы (`mca_source_refs`, `mca_evidence_links`, `mca_provenance_status`) + индексы + 6 nullable-колонок `graph_facts`; через реестр `mca-14` (`ARCHITECTURE.md` §93); backfill только прямых ссылок; старые таблицы/ID/FTS/`origin` CHECK сохранены; PG — no-op. Версия бронируется в `mca-round1027-arch-frames.md` §1.2.2. Точные `CREATE/ALTER/INDEX` — spec §5.
- **Δ каталога = 0**; F8 (ADR-1026-2) **NOT_APPLICABLE**.
- **Kill-switch:** `MCA_PROVENANCE_ENABLED`, `MCA_FACT_ATTRIBUTION_ENABLED`, `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` (env-only, default ON, OFF-паритет baseline; приоритет зафиксирован — spec §5).
- **reason_code:** расширение реестра MCA-13 пятью кодами (spec §4.8).
- **Нарезка 04a/04b:** санкционирована (spec §8.1).
- **L-MCA03-8:** не в 04a; обязательный вход `mca-04b` (версионирование отпечатка при исправлении); `legacy_import_v1` не переприсваивается.
- **Risk:** **R3** (основа памяти/provenance/субъект; каскад на досье/RAG/retrieval/парадигмы); `threat-failure-analysis.md` обязателен (T-3835). Понижение — при доказанной изоляции и A09/A10/A85/A86/A88/A95 на фактическом diff.
- **Обратный путь:** hot env-OFF; cold `git revert` → `05bc870` (анкер `7165ff7`); v17 аддитивна.
- **Release policy:** `DEFERRED_TO_RELEASE`.

## AMEND / REUSE-карта

| Артефакт | Режим | Суть |
|---|---|---|
| `services/database.py` (v17, `graph_facts`) | **AMEND** | 3 таблицы + 6 nullable-колонок + индексы; backfill прямых ссылок (bounded) |
| `services/provenance.py` | **NEW** | SourceRef/EvidenceLink билдеры, резолверы, правила восстановления, статусы (единый контракт) |
| `services/summary_memory.py` (`_memorize_facts_inner`) | **AMEND** | субъект/атрибуция SourceRef вместо переданного target |
| `services/direct_chat_service.py` (`_memorize_direct_reply`/`_reassign_fact_owners`) | **AMEND (FIX п.1)** | target=asker → субъект-атрибуция |
| `services/database.py` (`get_persona_card`/`get_user_context_facts`) | **AMEND (FIX п.2)** | subject-scope |
| `services/lore_worker.py` (`_classify_dossier_multilayer`/`_classify_chunked_user`) | **AMEND (FIX п.3/п.5)** | сохранение person_facts; локальные evidence→SourceRef |
| `services/dossier_prompts.py` (`filter_layer_a_candidates`) | **AMEND (FIX п.5)** | валидация subject/источник/row-bound |
| `graph_facts`/`source_ids`/`message_source_records`/`message_revisions` | **REUSE** | типизируются/ссылаются, не второй store |
| `write_transaction`/`serialized()` (`mca-01`) | **REUSE** | единый write-механизм |
| `emit_mca_event`/`mca_events` (`mca-13`) | **REUSE** | события; второй store запрещён |
| реестр `MigrationStep`/`schema_migrations` (`mca-14`) | **REUSE** | механизм Δ DDL |
| `services/thread_chain.py` | **REUSE** | reply-цепочки при восстановлении |
| SafeFetcher (`mca-02`) | **REUSE** | внешние материалы-источники |
| `mca-18`/`mca-19`/`mca-20`/`mca-05`/`mca-06`/`mca-07`/`mca-16`/`mca-04b` | **Consumers (расширяют)** | второй контракт запрещён |

| Решение | Задачи |
|---|---|
| D1 (SourceRef) | T-3821, T-3822 |
| D2 (связь MCA-03) | T-3821, T-3822 |
| D3 (EvidenceLink) | T-3822, T-3826 |
| D4 (независимость/claim_key) | T-3822, T-3827 |
| D5 (статусы/поля) | T-3822, T-3827 |
| D6 (восстановление §8.2) | T-3828, T-3829 |
| D7 (семантика личного факта) | T-3825, T-3826 |
| D8 (FIX 04a) | T-3826 |
| D9 (producers/consumers/REUSE) | T-3823, T-3824 |
| D10 (Δ DDL v17) | T-3821 |
| D11 (Δ каталога/kill-switch) | T-3819, T-3833 |
| D12 (наблюдаемость/R17) | T-3832, T-3833 |
| D13 (границы/carry-over/risk) | T-3819, T-3834 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Форма SourceRef | строка `store:type:id`; реестр + opaque `entity_id` | **реестр `mca_source_refs`** | типизация/дедуп/индекс; запрет смешения ID |
| Хранилище EvidenceLink | JSON на объекте; таблица связей | **таблица `mca_evidence_links`** | версии/тип/статус/основание/независимость; запрашиваемость |
| Статус/конфликт/актуальность/покрытие | одно enum-поле; отдельные поля | **отдельные поля** | §8.1 verbatim; источник+устаревание одновременно |
| Субъект | `target_user`-имя; SourceRef-субъект + ID | **SourceRef-субъект** | §8.3.2; одноимённые; unresolved импорт |
| Layer B person_facts | только промпт/портрет; отдельная таблица; `graph_facts` | **`graph_facts` (REUSE-паттерн)** | A86; не второй контракт; CHECK не трогать |
| Расширить `origin` CHECK | rebuild таблицы; nullable-колонка канала | **nullable `provenance_channel`** | аддитивность/риск rebuild большой таблицы |
| Восстановление | семантика→`original`; direct-only→`original` | **direct-only для `original`** | A09; §8.2 |
| Отпечаток L-MCA03-8 | фикс в 04a; defer | **defer в `mca-04b`** | не предмет provenance; версионирование при фиксе |
| Risk | R2; R3 | **R3** | основа памяти/provenance/субъект |

## Последствия

- Вводится единый типизированный provenance-контракт (SourceRef/EvidenceLink/статусы), на который опираются `mca-07` и последующие фичи; второй контракт запрещён.
- `graph_facts` расширяется аддитивно (6 nullable-колонок) + 3 новые таблицы; legacy сохраняется; PG не меняется.
- FIX-точки §8.3.1 п.1/2/3/5-контракт закрываются в 04a; п.4/6/7 и врезка п.5 — в 04b.
- Δ каталога = 0; risk R3 + threat-артефакт; hot env-OFF; cold `git revert` → `05bc870`; deploy `DEFERRED_TO_RELEASE`.

## Ссылки

- Feature: `plans/features/mca-04a-provenance-contract/{spec.md, tasks.md, adr-1027-6-provenance-contract.md}`.
- Рамка: `plans/docs/mca-round1027-arch-frames.md` (§1.2.2 v17, §2, §3, §4).
- План: `plans/docs/mca-round1027-plan.md` §3.4.
- Код: `services/database.py` (`graph_facts:607–624`, `insert_graph_fact:3856–3935`, `get_persona_card:5769–5796`, `get_user_context_facts:5798–5820`, `migration_steps`); `services/summary_memory.py` (`_memorize_facts_inner:2037–2241`); `services/direct_chat_service.py` (`_memorize_direct_reply:2168–2240`, `_reassign_fact_owners:2242–2286`); `services/lore_worker.py` (`_classify_dossier_multilayer:636–716`, `_classify_chunked_user:808–875`, `_extract_chunk:877–903`); `services/dossier_prompts.py` (`parse_layer_a:267–332`, `filter_layer_a_candidates:335–379`); `services/mca_gates.py`; `services/mca_events.py` (`REASON_CODES:57–80`); `config/settings.py`.
- Архитектура: входы §93 (`mca-14`), §94 (`mca-13`), §95 (`mca-01`), §96 (`mca-03`), §97 (`mca-02`); merge → §98 (**Accepted**, 27.09.2026).
- Точка отката: коммит `7165ff7` (анкер), reviewed `05bc870`.
