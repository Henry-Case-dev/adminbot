# ADR-1027-12 — `mca-05-episodes-stories`: Episode/Story-модель и пайплайн сборки (детерминированная сегментация → LLM-извлечение → подтверждённые продолжения → версии/merge/split/redirect/overrides), интеграция `lore_stories`/`lore_compiler_service` фасадом, Δ DDL = v21, Δ каталога = 0, R2

- **Статус:** **Proposed** (Step 2 @Architect, 01.10.2026, T-4246). → **Accepted по Merge** в `plans/ARCHITECTURE.md` **§108+** (T-4271, «следующий фактически свободный» на момент merge; §107 занят `mca-04b`).
- **Фича:** `mca-05-episodes-stories` (эпик round 10.27 MCA, Wave 2 — когниция). **Deploy: `DEFERRED_TO_RELEASE`** (§20, единый релиз на `mca-release`; пер-фичевых деплоев/тегов/bump нет).
- **ТЗ-основание:** `plans/current_task.md` v1.8 §9 (`:302–334`: §9.1 `:310–318`, §9.2 `:320–334`); §8.1 (`:210–226`); §2 п.2/п.13/п.14 (`:24`,`:33–34`); §11.2 (`:401–416`); §16 (`:762–806` — граница потребителя `mca-12`); §17 (`:818–846`); §18 (`:856–872`); §19 A11–A13 (`:892–894`); §20.2 (`:1012`); §27.1 (`:1339–1350`); §4 (`:77–101`).
- **Baseline (по Orchestrator/прод, 01.10.2026):** прод **2.58.41**, прод-HEAD **`0b1ae9c`** (архив `mca-04b`); `APP_VERSION` 2.58.41; SQLite DDL **v20** (хвост `MigrationStep` = `_SCHEMA_VERSION_DOSSIER_STAGING`, `services/database.py:598`); каталог **488/427/463/105/103/21** (Δ=0 с 2.58.39); канон инструментов 12; последний раздел `plans/ARCHITECTURE.md` — **§107** (`mca-04b`); pytest-анкер **10369 passed / 2 failed** (известные чужие bounds-тесты), JS **52/52**. Фактический binding для Build — по факту старта Step 3.
- **Связано:** REUSE `services/provenance.py` (`mca-04a`), `mca_source_refs`/`mca_evidence_links` (v17), `message_source_records`/`message_revisions` (mca-03 v16), `task_jobs`/`TaskSupervisor`/`write_transaction` (mca-01 v14), `mca_events`/`REASON_CODES` (mca-13 v15), `mca_process_registry`/`mca_pipeline_runs` (mca-17a v19), `MigrationStep` (mca-14 v13), `mca_retrieval_context.py` (`_episode_candidates`/`EvidenceBundle.local_context`, mca-07 v18); AMEND `services/lore_compiler_service.py`, `services/mca_retrieval_context.py`, `services/database.py` (v21 + репозиторий); **старые `lore_stories`/`lore_compiler_service`-пути сохраняются**; рамка `plans/docs/mca-round1027-arch-frames.md` **§1.2.6** (дополнена этим Step 2).

## Контекст

§9.1 требует модель: Episode — связный эпизод разговора, Story — связанная история из ≥1 эпизодов с продолжениями; «общая тема сама по себе не является общей историей»; хранить ID/chat_id/название/содержание/участников по ID/`event_start`/`event_end`/`discovered_at`/`updated_at`/утверждения/итог и открытые вопросы/source links/версию/состояние `open|closed|uncertain`/состояние проверки/исключение из retrieval/ручные overrides; состояние завершённости и статус задания — **разные поля**; события 2022, найденные сегодня, — события 2022; неизвестный исход — «исход неизвестен», финал не выдумывается. §9.2 требует пайплайн: сегментация по времени/reply-графу/участникам/теме с учётом параллельных разговоров; overlap без дублей; извлечение с источниками и unknown; кандидаты продолжений по событию с подтверждением связи; объединение с сохранением эпизодов и версий; повторы/противоречия/исправления без потери различий; индекс и событие витрины после фиксации. Интеграция: `topic_key` не идентичность события; **не создавать конкурирующие каталоги**; компилятор — потребитель/фасад; старые данные сохранить и сопоставить без автоматической ложной склейки; повторная сборка — версия с сохранением ручных изменений, merge/split, redirect; изменение источника — перепроверка зависимых; backfill не публикует в Telegram сам. §8.1: эпизод обязан иметь SourceRef/EvidenceLink или явный unknown. §16.1 фиксирует имена событий витрины (`story_discovered/story_extended/source_linked/contradiction_found/story_rebuilt`) — контракт потребителя `mca-12`.

**Фактическое состояние baseline (сверено 01.10.2026, анкеры PM T-4245 перепроверены):**
- `services/database.py:1117` — `lore_stories (id, chat_id, topic_key, topic, story, last_ts, created_at, updated_at, UNIQUE(chat_id, topic_key))` — плоская topic-keyed модель без участников/дат событий/источников/версий; `get_lore_story:4775`, `list_lore_stories:4794` (эпизоды-фасад mca-07), `upsert_lore_story:4811` (`_serialized_write`).
- `services/lore_compiler_service.py::compile` (`:81`) — `topic_key = normalize_text(clean)` (`:92`), UPD-дифф по `last_ts`; инструмент `compile_lore_story` через `tool_router`.
- `services/mca_retrieval_context.py` — `_CHANNEL_ORDER` (`:274`, канал `episode` weight 20.0), `_episode_candidates` (`:581`) читает `list_lore_stories`; `EvidenceBundle.local_context` (`:196`) пуст по умолчанию — carry-over **M-MCA07-2** (`mca-05` владелец наполнения).
- `services/provenance.py` — `SourceRef`/`EvidenceLink`, `ENTITY_TYPES` уже содержит `"episode"`/`"story"` (`:42–45`); второй SourceRef-контракт запрещён.
- `services/mca_process_registry.py` — code-declared реестр (ADR-1027-8 D1), прецеденты `dossier.rebuild`/`provenance.record`; `mca_pipeline_runs` (v19).
- Хвост `MigrationStep` = **v20**; `mca_episodes`/`mca_stories`/versions/redirect в коде отсутствуют → свободна **v21+**.
- `services/mca_events.py::REASON_CODES` (`:60`) — словарь §17.2 расширяем по прецеденту (mca-03/-02/-04a/-07/-17a/EXTRA/mca-04b-блоки).

## Решения

**D1. EpisodeService — отдельный логический компонент (§4), один владелец пайплайна и записи.**
- **Выбрано:** новый модуль в стиле проекта (рабочее имя `services/mca_episodes.py`; финальное имя — стиль проекта) — единственный владелец таблиц эпизодов/историй/версий/redirect/overrides и пайплайна сборки. Все записи — через `write_transaction`/`_serialized_write` (single-writer mca-01), чтение → LLM → короткая запись разделены (MCA14-R3). `lore_worker`/dream/summary не трогаются: кооперация — coexistence на single-writer + общий `TaskSupervisor`; второй контур обработки сообщений не создаётся (EpisodeService читает уже сохранённые сообщения, ничего не принимая из Telegram).
- **Обоснование:** §4 (`:87` EpisodeService, `:99` — UI не в БД, сеть вне транзакции); §2 п.2; GEN-R21; Q3. Врезка в `lore_worker` сделала бы его вторым владельцем dossier/sleep-записей (реворк mca-04b/mca-06 — прямо запрещён границами фичи).
- **Альтернатива:** расширение `lore_worker` — отклонено (смешение доменов досье и эпизодов; конфликт write-path с mca-04b staging-активацией).

**D2. Δ DDL SQLite = v21; PG — no-op.**
- **Выбрано:** аддитивная идемпотентная миграция через реестр `MigrationStep` (mca-14), guard `sqlite_master`/`PRAGMA table_info`, книга `schema_migrations`, `user_version` → 21. Состав объектов — §5. Старые `lore_stories` не трогаются; PG-объектов нет (`pg_db.py` вне diff; GEN-R4).
- **Обоснование:** MCA14-R1/R2; Q2. **Развилка v21/v22 закрыта документированным ограничением:** рамка §1.2.5 пометила v21 «свободной за `mca-04b` (не объявляется)», но `mca-04b` закрыт/архивирован и в проде 2.58.41 с финальным **v20** — вторая аддитивная потребность не заявлена; версии в реестре — упорядоченные клеймы (гэп безвреден, коллизия технически невозможна). Бронь растворяется явной санкцией §1.2.6: **v21 закреплена за `mca-05`**; гипотетическая вторая потребность `mca-04b` берёт следующий фактически свободный номер при заявке. Консультация владельца не требуется (чисто техническая нумерация, пользовательских tradeoff нет).
- **Альтернатива:** v22 с сохранением брони — отклонена: увековечивает гэп за закрытой фичей без заявленной потребности; бронь «не объявляется» не блокирует следующую фичу бесконечно.

**D3. Модель и инварианты (§9.1).**
- **Выбрано:** `mca_episodes` + `mca_stories` с полями §9.1 `:316` дословно; участники — устойчивые ID (mca-03), не имена; `state ∈ {open, closed, uncertain}` и job-статус — **разные сущности** (контрактный тест: `story_closed` при незавершённом job невозможен и наоборот); `verification` — словарь `mca-04a` (`verified/rejected/tentative/unknown`); `excluded_from_retrieval` (bool); override-поля; `extractor_version`. Уникальность — по `story_id`/canonical event-идентичности, не по `topic_key` (инвариант «тема ≠ история»); `event_start/end` — по проверяемому времени исходных сообщений (mca-03 revision), `discovered_at` отдельно (A11, детерминированный тест без LLM); неизвестный исход → `uncertain`/«исход неизвестен», финал не выдумывается.
- **Обоснование:** §9.1 verbatim; A11/A13.
- **Альтернатива:** продолжить `lore_stories` новыми колонками — отклонено: ломает §9.2 (topic_key как идентичность), не даёт версий/redirect; против «не создавать конкурирующие каталоги» не направлено, но не отвечает модели.

**D4. Пайплайн: детерминированное ядро сегментации + LLM-суждения.**
- **Выбрано:** сегментация (гэп-порог времени, reply-граф, участники) — детерминированная, стабильный keyset-порядок `(timestamp, id)` без OFFSET; LLM — только тематическое суждение/извлечение/подтверждение продолжений. Overlap границ batch дедуплицируется по стабильному message-ключу mca-03 (`chat_id + tg_message_id`/source record) — overlap не создаёт дублей (§9.2 п.2). Параллельные разговоры не смешиваются (A12-негатив).
- **Обоснование:** §9.2 п.1–2; §8.3-прецедент стабильного порядка; Q7.

**D5. Извлечение: LLM-контракт с источниками и unknown; канон промптов.**
- **Выбрано:** новые ключи канона `episodes_extract`/`continuation_confirm` с canon-версией (миграция по прецеденту реестра промптов; GEN-R2 — существующие провайдеры/маршрутизация). LLM-ответ — строгий JSON-контракт: участники = устойчивые ID; утверждения = message refs (→ SourceRef, контракт (k) spec); неизвестные детали = unknown; offline-валидатор контракта (fixture без LLM) + опциональный offline-прогон выбранной модели. Unknown не превращается в факт.
- **Обоснование:** §9.2 п.3; §8.1 (`:224` эпизод обязан иметь ссылки или unknown); §2 п.1.

**D6. Бюджет LLM — standalone env-only (прецедент ADR-1027-9 D14); интеграция с Resolver ASAP-3.1 отклонена.**
- **Выбрано:** `MCA_EPISODES_BATCH_MAX_MESSAGES` (default 500 — размер обработки, не предел истории), `MCA_EPISODES_DIRECT_PRIORITY_ENABLED` (ON); 1 активный LLM batch/чат; приоритет прямых ответов; источник исчерпания — существующий worker-бюджет lore-стиля; инвариант «budget exhaustion → `paused` (`story_backfill_paused_budget`), никогда `completed`».
- **Обоснование:** §8.3-конфиг (`:248`); ADR-1027-9 D14 (та же аргументация: разные единицы, AMEND свежего кода ASAP-3.1 без требования ТЗ против GEN-R19, инвариант инвариантен к источнику исчерпания); Q5.
- **Альтернатива:** интеграция с `auto_budget`/`model_capacity` — отклонена; будущая потребность — отдельная санкционированная amendment.

**D7. Продолжения: подтверждение события до склейки; сборка без потери различий.**
- **Выбрано:** кандидаты — поиск по событию (участники + сущность + время) в другие дни/месяцы, тема/сходство — кандидат, не доказательство; склейка только после LLM-подтверждения связи с источниками (`story_continuation_confirmed`/`story_continuation_rejected`); повторы связываются по canonical event-идентичности (повтор ≠ независимое событие — принцип A10); противоречие фиксируется (`contradiction_found` + `verification='tentative'`/conflict), не разрешается молча.
- **Обоснование:** §9.2 п.4–6; A12; §9.1.

**D8. Фасад компилятора и legacy `lore_stories`: ленивый маппинг без автосклейки.**
- **Выбрано:** `lore_compiler_service` — потребитель/совместимый фасад: `topic_key` остаётся ключом компилятора, но не идентичностью события; связывание — через `mca_story_legacy_links` **только по подтверждённой event-связи** (никогда по равенству темы); статус `mapping_status ∈ {mapped, legacy, unmapped}`; unmapped видимы с честным unknown (`story_legacy_unmapped`); **отдельный фоновый ремап-проход не создаётся** (ленивый маппинг при касании — достаточно для контракта «сопоставить без автоматической ложной склейки»; A12-негатив закрывает риск). Инструмент `compile_lore_story` и потребители лора продолжают работать.
- **Обоснование:** §9.2 `:332` verbatim («не создавать конкурирующие каталоги… сопоставить без автоматической ложной склейки»); Q8; GEN-R19.
- **Альтернатива:** bounded-фоновый проход ремапа — отклонен (дополнительный LLM-проход без требования ТЗ; расширяет стоимость; ленивый путь покрывает наблюдаемость unmapped).

**D9. Версии, merge/split, redirect, overrides; конкурентная правка — CAS.**
- **Выбрано:** повторная сборка создаёт новую версию — полный снимок в `mca_story_versions`, активная запись ссылается на версию (старая доступна); override-поля пайплайн никогда не затирает и переносит на новую версию (A13); merge/split — новая версия + строки `mca_story_redirects` (old → new; резолв фасадом для внешних ссылок mca-07/будущих mca-12/убеждений); конкурентная правка — оптимистичный CAS `expected_version` (прецедент F0 persistItems/mca-04b staging): stale update отклоняется, не затирает. Связи продолжений — `mca_story_continuations`; состав эпизодов истории — `mca_story_episode_links`.
- **Обоснование:** §9.2 `:334`; §16.2-семантика (модель без UI); A13; Q9.
- **Альтернатива:** только supersedes-указатель без таблицы redirect — отклонён: redirect обязан резолвить внешние ссылки неограниченно долго; цепочка указателей дороже и хрупче прямого маппинга.

**D10. Backfill — отдельный resumable job; revision → перепроверка; без публикации.**
- **Выбрано:** durable `task_jobs`, unique key `episodes.backfill:<chat_id>` (coalescing, без параллельного старта); checkpoint после фиксации; heartbeat/attempt/lease (v19-поля); счётчики processed/linked/unresolved/errors; честная финализация по прецеденту mca-04b D3 (`paused/interrupted/failed`, никогда ложный `completed`; нулевой результат при полном корректном проходе валиден). **Не врезка** в dossier backfill (другой домен) и не в mca-10b (будущий archive_sample); доменные проходы сосуществуют по прецеденту mca-04b, от дублирования защищают unique key + 1 batch/чат + direct priority + отдельный kill-switch. Изменение источника (mca-03 revision) ставит зависимые эпизоды/истории в очередь перепроверки (`story_source_recheck_queued`), без немедленной рекурсивной ветки. **Пайплайн физически не имеет пути отправки в Telegram** (grep-гейт-тест; публикация — только единый выбор инициативы, контур mca-09 — будущий потребитель читает готовые записи, §2 п.2).
- **Обоснование:** §9.2 `:334`; §7 (редакция → пересмотр); MCA14-R3; Q4/Q6; §2 п.2.

**D11. Интеграция retrieval и EvidenceBundle: AMEND канала + carry-over M-MCA07-2.**
- **Выбрано:** `_episode_candidates` читает новый store через фасад (REUSE `list`-контракт), уважает `excluded_from_retrieval`, chat scope и статусы; fail-open mca-07 сохранён; второй retrieval-движок запрещён (L-MCA07-5). **M-MCA07-2:** EpisodeService наполняет `local_context` живого EvidenceBundle (текущая ветка/важный локальный контекст); инвариант пустого = `not_available`; второй bundle запрещён.
- **Обоснование:** §9.2 п.7; §11.2 (`:409`); §99.4; GEN-R19.

**D12. События витрины и наблюдаемость — REUSE единственной системы телеметрии.**
- **Выбрано:** post-commit испускание `story_discovered/story_extended/source_linked/contradiction_found/story_rebuilt` через `emit_mca_event`/`mca_events` (имена фиксированы §16.1 — контракт mca-12); поля: story/episode refs, обе даты, участники-ID, краткое R17-safe описание, reason_code; событие — только после фиксации (тест rollback → нет события); индекс обновляется атомарно с фиксацией; ретенция mca-13 14/90, bounded-history чтение mca-12 — без нового канала (§27.1). Процесс `episodes.build`/`episodes.backfill` — в `mca_process_registry` по прецеденту `dossier.rebuild` (стадии segment/extract/confirm/assemble/link/index; `state_source=task_jobs`; widget-ID; `mca_pipeline_runs`); «новый процесс без наблюдаемости = незавершённая интеграция». Расширение `REASON_CODES` — 10 кодов (см. санкции); переиспользуются `parse_error`, `model_unavailable`, `evidence_invalid`, `provenance_unresolved`, `source_revision_changed`, `cancelled`, `insufficient_evidence`, `contradictory_evidence`.
- **Обоснование:** §9.2 п.7; §16.1 (`:786`); §17; §27.1; MCA13-R1/R2; GEN-R17; Q10/Q11.

**D13. Границы (фиксация для spec/PM):**
- UI-виджет/лента/таблица/карточка/настройки — `mca-12` (Wave 5); mca-05 не создаёт маршрутов/настроек/верхнеуровневого раздела «Истории» (§2 п.13/п.14).
- Verbatim-episode прямого контекста ASAP-3 (`model_slots`/composer) не трогается — регресс-тест границы.
- Сон/досье (mca-04b/mca-06) — только потребительская кооперация.
- Публикация историй — вне фичи (mca-09/mca-10b, §2 п.2); D-MCA05-1 (пользовательская развилка не требуется: поведение диктуется §9.2/§2 п.2 дословно).

## Санкции (Step 2, T-4246/T-4247)

- **Δ DDL SQLite = v21** (аддитивно/идемпотентно, реестр `mca-14`; состав — §5; PG no-op; старые таблицы/ID сохранены; повторный прогон — no-op). Бронь v21 «за mca-04b» растворена (D2); рамка дополнена **§1.2.6**.
- **Δ каталога = 0** (env-only `ClassVar`; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; F8 ADR-1026-2 **NOT_APPLICABLE**; каталог `488/427/463/105/103/21` не меняется).
- **Kill-switch (4 + 2 env-лимита; default ON, OFF = паритет baseline):** `MCA_EPISODES_ENABLED` (master), `MCA_EPISODES_BACKFILL_ENABLED`, `MCA_EPISODES_CONTINUATION_ENABLED`, `MCA_EPISODES_COMPILER_FACADE_ENABLED`; env-only лимиты (не каталог): `MCA_EPISODES_BATCH_MAX_MESSAGES` (500), `MCA_EPISODES_DIRECT_PRIORITY_ENABLED` (ON). Состав — в manifest-список релиза (прецедент «26+1»); effective-state строка §20.2 «Эпизоды и истории — ON» подтверждаема через runtime/API.
- **reason_code (+10):** `episode_extracted`, `story_segment_empty`, `story_continuation_confirmed`, `story_continuation_rejected`, `story_contradiction_found`, `story_legacy_unmapped`, `story_backfill_paused_budget`, `story_source_recheck_queued`, `story_merged`, `story_split`.
- **Risk: R2** (ратификация — ниже). **Deploy:** `DEFERRED_TO_RELEASE`. **Merge:** `plans/ARCHITECTURE.md` **§108+**, ADR-1027-12 → Accepted по Merge (T-4271).

## Состав Δ DDL v21 (контракт для Builder; точный SQL — Build, индексы — по EXPLAIN QUERY PLAN фактических запросов репозитория)

| Таблица | Назначение | Ключевые поля (аддитивно/nullable = честный unknown) |
|---|---|---|
| `mca_episodes` | Эпизод разговора | `episode_id` PK, `chat_id`, `title`, `summary`, `participants_json`, `event_start_ts`/`event_end_ts`, `discovered_at`, `updated_at`, `claims_json` (R17-safe), `outcome`/`open_questions`, `extraction_version`, `mapping_status` |
| `mca_stories` | История (карточка §9.1) | `story_id` PK, `chat_id`, `title`, `summary`, `participants_json`, `event_start_ts`/`event_end_ts`, `discovered_at`, `updated_at`, `claims_json`, `outcome`/`open_questions`, `state ∈ {open,closed,uncertain}`, `verification`, `excluded_from_retrieval`, `active_version_id`, `expected_version` (CAS), `extractor_version`, override-колонки (nullable), `task_status_ref` (≠ state) |
| `mca_story_versions` | Полные снимки версий | `version_id` PK, `story_id`, `version_no`, `payload_json`, `created_at`, `created_by` (pipeline/manual), `extractor_version` |
| `mca_story_episode_links` | Состав истории | `story_id`, `episode_id`, `order_no` (уникальность пары) |
| `mca_story_continuations` | Связи продолжений | `from_episode_id`, `to_episode_id`, `confirmation` (LLM-подтверждение + refs), `status` |
| `mca_story_redirects` | Redirect старых ID | `old_kind`/`old_id` PK, `new_kind`/`new_id` (внешние ссылки резолвятся фасадом) |
| `mca_story_legacy_links` | Фасад legacy `lore_stories` | `lore_story_id`, `story_id` (nullable), `mapping_status ∈ {mapped, legacy, unmapped}` |

Индексы — только под фактические запросы (chat-scope списки, redirect-резолв, legacy-link lookup); candidates: `idx (chat_id, updated_at)`, `idx (chat_id, state)`, unique `(chat_id, episode natural key)` — финальный набор по EXPLAIN QUERY PLAN на Build.

## Риск: R2 — ратификация

**R2 (не R3):** портится только **производные** сущности; первичные сообщения не трогаются; ущерб обратим (версии + redirect + kill-switch OFF = паритет); нет merge идентичностей (участники по готовым stable ID mca-03), нет network-поверхности, нет удаления данных, нет пути отправки в Telegram. Условия эскалации в R3 (при Build/Review): путь записи в первичные таблицы, автоделит legacy, send-path в пайплайне, слияние идентичностей — все исключены контрактом; если обнаружатся — стоп, эскалация @Architect.

Риски/митигации — spec §9 (false-glue High → подтверждение события + детерминизм + негативные тесты; регресс потребителей Medium → фасад+паритет; стоимость LLM Medium → env-бюджет+paused; write-path Medium → single-writer; semantic-путаница ASAP-3 Low → граница+регресс; события без UI Low → ретенция 14/90; **DDL-бронь v21 — снята санкцией D2**).

## Последствия

- `mca-12` получает: модель с merge/split/overrides/versions + контракт событий `story_*` (имена §16.1) + redirect — UI-обвязка без изменений модели.
- `mca-09`/`mca-10b` получают читаемый каталог событий с provenance — будущие потребители инициативы.
- `mca-07` канал усиливается (новый store через фасад, excluded-уважение); `lore_compiler_service` сохраняется как потребитель.
- Обязательства наблюдаемости: процесс в реестре + события `mca_events` + reason_code — иначе интеграция не считается завершённой (§27.1).

## Почему не консультация владельца

Все развилки (Q1–Q12) закрыты: (Q1/Q2) хранилище/номер версии — техническая нумерация и фактическая реализация лора в SQLite; (Q3/Q4/Q6/Q9) — диктует §4/§9.2/§2 п.2 дословно; (Q5) — прецедент ADR-1027-9 D14; (Q7/Q8/Q10/Q11) — контракты §9.2/§16.1/§17/§18; (Q12) — R2-ратификация и свободные номера (ADR-1027-12 свободен: -9 за mca-04b, -10/-11 выпущены, ADR-1028-* за ASAP/EXTRA-серией). Пользовательских tradeoff (privacy/cost/interop/внешне видимое поведение) нет.
