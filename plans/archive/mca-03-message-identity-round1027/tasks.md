# `mca-03-message-identity` — MCA-03: сообщения, идентичность, время, версии (round 10.27, Wave 1)

> **Статус:** 🟦 PLANNING — Step 1 @PM. Код НЕ менялся (только `plans/**`). Secret-дисциплина (R17/R18).
> **Эпик:** Раунд 10.27 `memory-context-autonomy` (MCA), **Wave 1** (данные). **Фича-ID:** `mca-03-message-identity`.
> **Тип:** backend/data — логическая идентичность сообщений, поля/время/версии, роли/алиасы, миграция `chat_id`. **P0-предпосылка** для `mca-04a` (provenance) → `mca-07` (retrieval) и последующих (`mca-05`/`mca-08`/`mca-15`/`mca-18`).
> **ТЗ-источник (IMMUTABLE):** `plans/current_task.md` v1.8, **§7** «MCA-03 — сообщения, идентичность, время, версии» (`:180–198`); §3/§3.1 (совместимость/REUSE, `:45–75`); §4 (компоненты, `:77–101`); §6.2 (не удалять cookies — смежно, `:164–178`); §17.1 (контракт события, `:818–828`); §18 (аддитивные миграции — механизм `mca-14`, `:856–872`); §22 (ориентиры, `:1062–1077`); проверки §19 **A07/A08/A11/A88** (`:888`, `:889`, `:892`, `:969`).
> **Приёмочные ориентиры §19:** **A07** (два Макса; цитата; пересылка; смена алиаса — идентичности и роли не перепутаны), **A08** (изменено исходное сообщение — версия обновлена, зависимые выводы помечены), **A11** (история 2022 найдена сегодня — две даты, нет подмены времени события), **A88** (одноимённые люди/чужой evidence — субъект разрешён по устойчивому ID, источники не смешаны).
> **Зависимости:** **`mca-14` ✅** (v13 migration-runner + книга `schema_migrations`; доменные таблицы волны 1 — **v16**, санкция @Architect; рамка §1.2.1); **`mca-01` ✅** (единый write-механизм `write_transaction`/`serialized()`/`@_serialized_write`; `task_jobs`); **`mca-13` ✅** (event-контракт §17.1, `mca_events` — единый durable-стор; вторая телеметрия запрещена). Доменные таблицы не дублировать. **Потребители:** `mca-04a` (SourceRef/EvidenceLink), `mca-07` (retrieval/EvidenceBundle), `mca-05`, `mca-08`, `mca-15`, `mca-18`, `mca-19`, `mca-20`.
> **Baseline (Step 0 @Memory, 26.09.2026; используется как данность):** HEAD **`7165ff7`** (master); `APP_VERSION` **2.58.31**; SQLite DDL **v12 → v15** (волна 0: v13 `schema_migrations`, v14 `task_jobs`, v15 `mca_events`); каталог **473/430/448/102/100/21**; канон инструментов **12**; pytest **9588/0** + JS **47/47** (verified волны 0). Пост-волновая сверка: Reviewed-Commit **`05bc870`**, Working-Tree-Hash `9cd581e4…`, Product-Code-Hash `9d925418…`.
> **Deploy — `DEFERRED_TO_RELEASE`** (§2.4–2.5; §20 — единый production-релиз; пер-фичевых деплоев/тегов/bump нет; агрегатный релиз — на `mca-release`). Точка отката (код) — анкер `7165ff7` + `git revert`; DDL аддитивен (новые таблицы безвредны).
> **Risk — предварительно `R3`** (identity/версии — основа памяти и provenance; санкция/финал — @Architect Step 2, ратификация — @Reviewer).
> **⛔ Границы:** product code — только Step 3 @Builder (после Step 1/2 и сверки); `plans/current_task.md` — IMMUTABLE; `workflow_state.md`/`metrics.md`/`MEMORY.md` — не трогать; `plans/ARCHITECTURE.md` — Merge только @Architect (Step H); без коммитов из этого шага.

## Трассируемость (REQ → verbatim §ТЗ → блок → задачи → приёмка)

| REQ | Источник (verbatim, `current_task.md`) | Блок | Задачи | SC (spec §6) | ADR-1027-4 | Приёмка |
|---|---|---|---|---|---|---|
| MCA03-R1 | §7 «Логическая идентичность Telegram-сообщения: пара `chat_id + tg_message_id`, а не один message_id. Импорт должен иметь namespace/dataset ID и стабильный source record ID. Если Telegram ID сохранён… связаны с одним canonical source. Если ID отсутствует, локальный стабильный идентификатор не выдавать за Telegram ID.» (`:188`) | A, B, C, D | T-3779, T-3780, T-3782, T-3783, T-3787, T-3788 | SC-01, SC-02, SC-03 | D1, D2 | A07, A88 |
| MCA03-R2 | §7 «Сохранять: текст/подпись, author_id, имя на момент сообщения, sent_at, ingested_at, edited_at при наличии, reply target, forward/quote metadata, media reference, source_kind, revision/hash. Дата события не равна дате импорта. Значение timestamp из старой базы не переименовывать в sent_at без проверки семантики.» (`:190`) | B, C, E | T-3784, T-3786, T-3790, T-3791 | SC-05, SC-06 | D3 | A08, A11 |
| MCA03-R3 | §7 «Разделять автора сообщения, адресата ответа, процитированного автора и человека, о котором говорят. ALIAS > real_name > username относится к отображению, а не к слиянию идентичностей. Совпадение имени или прозвища недостаточно для автоматического объединения.» (`:192`) | C, D, E | T-3785, T-3788, T-3789, T-3790, T-3791 | SC-07, SC-08 | D4 | A07, A88 |
| MCA03-R4 | §7 «Редакция сообщения создаёт новую версию, обновляет поиск и помечает зависимые выводы на пересмотр. Telegram не гарантирует получение ботом всех удалений: статус unavailable/deleted устанавливать только при соответствующем свидетельстве. Не объявлять отсутствие API-события доказательством сохранности сообщения.» (`:194`) | C, E | T-3786, T-3790, T-3791, T-3792 | SC-09, SC-10 | D5 | A08 |
| MCA03-R5 | §7 «Исторические смены ID чата при миграции Telegram-группы учитывать явным mapping, если он подтверждён метаданными; не объединять по похожему названию.» (`:196`) | C, E | T-3787, T-3790 | SC-11 | D6 | A07 |
| MCA03-A88 | §19 A88 «Evidence=1 в двух чанках, несуществующая строка и одноимённые люди — источники чанков не смешаны; неверные ссылки отвергнуты; субъект разрешён по устойчивому ID.» (`:969`) | B, C, D, E | T-3783, T-3789, T-3791 | SC-04, SC-07, SC-08 | D1, D4 | A88 |
| GEN-R19 | §3/§3.1 «Если требование уже выполнено, проверить его вместо создания второй реализации»; совместимость с Epic 1–3 (identity/dossier, ToolResult) (`:47`, `:60–75`) | A, C, D | T-3779, T-3785, T-3788 | SC-13, SC-14 | D8 | REUSE-карта |
| GEN-R20 | §3 «Собрать фактические данные… заполненность ID автора/сообщения/чата, reply-связей и источников; пересечения импортированной и живой истории, старые форматы идентификаторов» (`:49–53`) | A, D | T-3779, T-3788 | SC-13, SC-14 | D8 | A88 |
| MCA14-R1/R2 | §18 аддитивные идемпотентные миграции через реестр; старые ID/таблицы сохраняются; nullable = честный unknown (`:864–866`) | B | T-3782, T-3784 | SC-12 | D7, D11 | A87 |
| MCA13-R1/R2 | §17.1/§17.2 JSON-событие `start`+`outcome`; словарь `reason_code` (`ambiguous_identity`, `source_revision_changed`, `source_missing`) (`:818–836`) | F | T-3792, T-3793 | SC-15, SC-16 | D10 | A27, A53 |
| GEN-R17 | §2.19/§27 — регистрация стадий/виджет-ID процесса (MCA-17a) для новых функций (`:41`) | F | T-3792 | SC-15 | D10 | A48 |
| GEN-R14/R17 | §2.16/§17.3 — журналировать решения/пропуски/ошибки; секреты не журналировать; `sanitize()`/SourceRef (`:36`, `:844`) | F | T-3793 | SC-16 | D10 | A53 |
| FIN-R1 | после §31 — максимальное покрытие тестами, прогон, отсутствие конфликтов (`:1865`) | E, G | T-3790, T-3791, T-3794 | SC-17 | D7, D9 | A01–A95 |
| MCA14-R5 | §18 — оперативный kill-switch (env-only, default ON); релиз со всеми ON (`:872`) | G | T-3794, T-3795 | SC-17 | D9 | A28 |

**Соответствие ID:** табличные `MCA03-R1…R5` ↔ спека `REQ-MCA03-01…05`; `MCA03-A88` → `REQ-MCA03-04`/`-08` (A88); `GEN-R19/R20` → `REQ-MCA03-08`; `MCA14-R1/R2` → `REQ-MCA03-07`; `MCA13-R1/R2`, `GEN-R17`, `GEN-R14/R17` → `REQ-MCA03-09`; `FIN-R1`, `MCA14-R5` → `REQ-MCA03-10`. Столбец `SC` — сценарии `spec.md` §6; `ADR` — решения ADR-1027-4 (D1–D12). **Orphan-REQ/SC нет:** каждый `REQ-MCA03-01…11` покрыт ≥1 задачей (spec §2), каждая задача — REQ/SC либо процессная (T-3777/3778/3796/3797).

## Матрица трассировки задач (task → REQ → приёмка → §ТЗ)

| Task | REQ | SC (spec §6) | ADR-1027-4 | Приёмка | §ТЗ |
|---|---|---|---|---|---|
| T-3777 | — (Step 0) | gate | — | gate | baseline §0 |
| T-3778 | — (Step 1) | gate | — | gate | — |
| T-3779 | MCA03-R1…R5, GEN-R19/R20 | SC-01…SC-18 (авторство spec) | D1–D12 | A07, A88 | §7, §3 |
| T-3780 | MCA03-R1, MCA14-R1/R2 | SC-12 | D7, D11 | gate (санкция) | §18, §7 |
| T-3781 | MCA03-R1…R5 | gate (сверка) | D1–D12 | gate | §7 |
| T-3782 | MCA03-R1, MCA14-R1/R2 | SC-12 | D7, D11 | A88 | §7, §18 |
| T-3783 | MCA03-R1, MCA03-A88 | SC-01, SC-02, SC-03, SC-04, SC-18 | D1, D2, D12 | A07, A88 | §7 |
| T-3784 | MCA03-R2, MCA14-R2 | SC-05, SC-06, SC-12 | D3, D7 | A08, A11 | §7, §18 |
| T-3785 | MCA03-R3, GEN-R19 | SC-07, SC-08 | D4 | A07, A88 | §7, §3.1 |
| T-3786 | MCA03-R4 | SC-09, SC-10 | D5 | A08 | §7 |
| T-3787 | MCA03-R5 | SC-11 | D6 | A07 | §7 |
| T-3788 | MCA03-R1, MCA03-R3, GEN-R19/R20 | SC-03, SC-04, SC-13 | D1, D2, D8 | A07, A88 | §7, §3 |
| T-3789 | MCA03-R3, MCA03-A88 | SC-07, SC-08, SC-14, SC-18 | D4, D8, D12 | A88 | §7 |
| T-3790 | MCA03-R2…R5 | SC-01, SC-02, SC-11 | D1, D6 | A07, A08, A11 | §7 |
| T-3791 | MCA03-R1…R4, MCA03-A88 | SC-05, SC-06, SC-07, SC-08, SC-09, SC-10 | D3, D4, D5 | A07, A08, A11, A88 | §7, §19 |
| T-3792 | MCA03-R4, MCA13-R1/R2, GEN-R17 | SC-10, SC-15, SC-16 | D5, D10 | A27 | §7, §17, §27.1 |
| T-3793 | GEN-R14/R17 | SC-16 | D10 | A53 | §17.3 |
| T-3794 | MCA14-R2/R5, FIN-R1 | SC-17 | D7, D9 | A28, A87 | §18, §3.1 |
| T-3795 | MCA14-R4/R5, GEN-R23/R24 | SC-17 | D9, D12 | A28 | §18, §20 |
| T-3796 | MCA03-R1…R5 | gate (все SC) | gate (Accepted) | gate (merge) | §7 |
| T-3797 | — | — | — | gate (archive) | — |

## Приёмочные инварианты MCA-03 (нарушение = НЕ принято)

1. Логическая идентичность = **`chat_id + tg_message_id`** (не одиночный `message_id`); два разных чата с одинаковым `message_id` не конфликтуют. **MCA03-R1; T-3783, T-3790.**
2. Импорт имеет **namespace/dataset ID** и стабильный **source record ID**; локальный ID **не выдаётся** за Telegram ID; импорт и live одной записи связаны с одним canonical source (при наличии TG ID). **MCA03-R1; T-3783, T-3788.**
3. Сохраняются: текст/подпись, `author_id`, имя на момент, `sent_at`, `ingested_at`, `edited_at`, reply target, forward/quote, media ref, `source_kind`, revision/hash. **Дата события ≠ дата импорта**; старый `timestamp` не переименовывается в `sent_at` без проверки семантики. **MCA03-R2; T-3784, T-3791.**
4. Автор / адресат ответа / процитированный автор / субъект обсуждения **разделены**; цитата не становится мнением цитирующего. **MCA03-R3; T-3785, T-3790.**
5. `ALIAS > real_name > username` — только **отображение**; совпадение имени/прозвища **не** сливает идентичности (два Макса не объединяются). **MCA03-R3; T-3785, T-3791.**
6. Редакция → **новая версия**; поиск обновлён; зависимые выводы помечены на пересмотр; устаревшая версия не остаётся актуальной. **MCA03-R4; T-3786, T-3791.**
7. `unavailable/deleted` — **только по свидетельству**; отсутствие API-события ≠ доказательство сохранности. **MCA03-R4; T-3786, T-3792.**
8. Смена `chat_id` — **явный mapping** (по подтверждённым метаданным), **не** по похожему названию. **MCA03-R5; T-3787.**
9. Старые записи/ID/таблицы сохраняются; новые nullable-поля = честный unknown. **MCA14-R2; T-3782, T-3784.**
10. Deploy `DEFERRED_TO_RELEASE`; kill-switch env-only default ON, OFF = паритет baseline; R17: секреты/сырой контекст не логируются (SourceRef). **T-3793, T-3794, T-3795.**

## REUSE-карта (не дублировать Epic 1–3)

| Что | Где (ориентир §22) | Режим | Задачи |
|---|---|---|---|
| Логическая идентичность в ingestion | `handlers/summary.py` (ingestion + edited messages) | **AMEND** (не второй ingestion) | T-3788 |
| Хранение сообщений | `services/database.py::smart_messages` | **AMEND** аддитивно; старые ID/FTS сохранить | T-3782, T-3783 |
| Единый write-механизм | `write_transaction`/`serialized()`/`@_serialized_write` (`mca-01`) | **REUSE** | T-3782, T-3788 |
| Алиасы/identity | `services/aliases*`, identity/dossier Epic 3 | **REUSE** (display-only алиасы) | T-3785, T-3789 |
| Provenance | ToolResult/SourceRef Epic 3, ToolResult-конверт | **REUSE** контрактов `mca-04a` (без второго контракта) | T-3783, T-3789 |
| Миграции | реестр `MigrationStep` + `schema_migrations` (`mca-14` §93) | **REUSE** (регистрация единого шага `v16`, рамка §1.2.1) | T-3782 |
| События | `emit_mca_event`/`mca_events` (`mca-13` §94) | **REUSE** (второй telemetry-store запрещён) | T-3792 |
| Retrieval/досье | `services/summary_memory.py`, `services/direct_chat_service.py`, `lore_*` | **Потребители** canonical identity (без дубля логики) | T-3789 |

## Заявки для @Architect (Step 2 — требуют санкции/решения)

1. **Δ DDL — версия `v16` (заявка).** Доменные объекты identity: логическая идентичность `chat_id + tg_message_id` (если не покрывается существующими колонками `smart_messages` — только аддитивные колонки/индекс), namespace/dataset ID + стабильный source record ID, записи версий/ревизий (revision/hash), mapping `chat_id` при миграции. Реализация — **через реестр `mca-14`** (шаг `v16`, идемпотентный, `CREATE ... IF NOT EXISTS`/`ALTER ADD COLUMN`, старые таблицы/ID не удаляются/не переименовываются). Санкция подтверждена (@Architect, рамка `mca-round1027-arch-frames.md` §1.2.1): единый шаг **`v16`**; duplicate pre-check перед опциональным partial UNIQUE (иначе WARN `duplicate_identity_rows` + non-unique индекс); backfill bounded/resumable (guard `sent_at_source IS NULL`); старые `id`/`timestamp`/FTS сохраняются.
2. **Δ каталога — предварительно `0`.** Рубильники — **env-only `ClassVar`** (прецедент `DB_LOCK_RESILIENCE_ENABLED`; F8 NOT_APPLICABLE), каталог `473/430/448/102/100/21` не меняется. Если @Architect решит, что identity-настройка управляется из UI → фича обязана заявить точный Δ каталога и запустить процедуру ADR-1026-2 (repin/regenerate). **По умолчанию — 0.**
3. **Kill-switch — имена (предложение, default ON, env-only `ClassVar`, резолв per-call, OFF = паритет baseline):**
   - `MCA_MESSAGE_IDENTITY_ENABLED` — OFF: legacy-путь идентичности/полей (как сейчас), без новых записей.
   - `MCA_MESSAGE_REVISION_TRACKING_ENABLED` — OFF: редакции без версионирования (текущее поведение).
   Финальные имена/число — за @Architect; OFF фиксируется в release-manifest/логе при отключении (причина/время/план).
4. **Границы/совместимость:** взаимодействие с `mca-04a` (SourceRef/EvidenceLink), `mca-07` (EvidenceBundle), `mca-18` (subject/speaker entity), `mca-19` (Message/SourceRef расширение), `mca-20` (ClaimEnvelope) — во избежание второго контракта; `mca-19`/`mca-18` расширяют MCA-03, а не дублируют.

## Блок 0 — Step 0 / baseline (T-3777) + Step 1 (T-3778)

- [ ] **T-3777 [@Memory/@Orchestrator — подтверждение Step 0]** — **Цель:** подтвердить baseline (HEAD `7165ff7`, 2.58.31, DDL v15 после волны 0, каталог 473/430/448/102/100/21, канон 12, pytest 9588/0 + JS 47/47) и точку отката. **Выход:** подтверждение в KG/`workflow_state`. **Критерий:** baseline/точка отката согласованы; волна 0 заархивирована. **Зависимости:** Step 0 ✅.
- [ ] **T-3778 [@PM — Step 1: `tasks.md`]** — **Цель:** разложить §7, создать этот файл. **Выход:** `plans/features/mca-03-message-identity/tasks.md`. **Критерий:** REQ/инварианты/блоки/трассировка согласованы; orphan-REQ нет. **Зависимости:** T-3777.

## Блок A — Step 2 spec + ADR + санкции (T-3779…T-3781)

- [ ] **T-3779 [@Architect — `spec.md` + ADR]** — **Цель:** `spec.md` (REQ-MCA03-01…; границы с `mca-04a`/`mca-07`/`mca-18`/`mca-19`/`mca-20`) + **новый ADR** (следующий после ADR-1027-3). Решения: (i) модель логической идентичности и canonical source; (ii) namespace/dataset ID + стабильный source record ID; (iii) поля/время (event vs import time) и `source_kind`; (iv) модель ролей (автор/адресат/цитируемый/субъект) и display-only алиасы; (v) версии/ревизии и пометка зависимых выводов; (vi) свидетельство для `unavailable/deleted`; (vii) mapping `chat_id`; (viii) Δ DDL `v16` (заявка); (ix) Δ каталога/калькулятор (0/env-only); (x) kill-switch-имена; (xi) R17/наблюдаемость (MCA-13/17a); (xii) финальный Risk. **Выход:** `spec.md` + ADR (Proposed). **Критерий:** каждый REQ имеет SC; §7 не сужен. **Зависимости:** T-3778.
- [ ] **T-3780 [@Architect — санкция Δ DDL/каталога/kill-switch]** — **Цель:** зафиксировать **санкцию Δ DDL v16** (точные `CREATE TABLE/ALTER TABLE/CREATE INDEX`, `nullable`/default, обратный путь) в `mca-round1027-arch-frames.md` §1.2.1; подтвердить Δ каталога (0) и имена kill-switch; определить границы с `mca-04a`. **Выход:** раздел «Δ DDL» в `spec.md` + бронь версии в рамке. **Критерий:** самовольного DDL нет; механизм `mca-14` соблюдён; старые ID/таблицы сохраняются. **Зависимости:** T-3779.
- [ ] **T-3781 [@PM — сверка]** — **Цель:** сверка `tasks.md` ↔ `spec.md` ↔ ADR; заполнение колонок SC/ADR. **Выход:** `PLANNING_CONSISTENT` либо список расхождений. **Критерий:** scope/исключения/risk/приёмка A07/A08/A11/A88/зависимости/deploy `DEFERRED_TO_RELEASE`/rollback согласованы. **Зависимости:** T-3779, T-3780.

## Блок B — Δ DDL v16 и контракт идентичности (T-3782…T-3784)

- [x] **T-3782 [@Builder — migration step v16]** — **Цель:** зарегистрировать единый шаг **`v16`** в реестре `mca-14` (аддитивно, идемпотентно): 18 nullable-колонок `smart_messages` + `message_source_records`/`message_revisions`/`chat_id_migrations` + индексы; новые nullable-колонки = честный unknown; старые таблицы/ID/FTS не переименовывать/не удалять; **duplicate pre-check** перед опциональным partial UNIQUE (иначе WARN `duplicate_identity_rows` + non-unique индекс); **backfill bounded/resumable** (guard `sent_at_source IS NULL`; импорт `sent_at=timestamp`/`import_date`, live `sent_at=NULL`/`legacy_unverified`). **Выход:** правки `services/database.py` + тесты. **Критерий:** MCA03-R1/MCA14-R1/R2; SC-12; инварианты 1, 9; A88. **Зависимости:** T-3781.
- [x] **T-3783 [@Builder — контракт логической идентичности]** — **Цель:** контракт `chat_id + tg_message_id` + namespace/dataset ID + canonical source + стабильный source record ID; REUSE `smart_messages` (аддитивно), не второй store; локальный ID не выдаётся за TG ID. **Выход:** модуль/контракт + тесты. **Критерий:** MCA03-R1; инварианты 1, 2; A07/A88. **Зависимости:** T-3782.
- [x] **T-3784 [@Builder — поля/время/версии]** — **Цель:** хранение полей §7 (текст/подпись, `author_id`, имя на момент, `sent_at`/`ingested_at`/`edited_at`, reply target, forward/quote, media ref, `source_kind`, revision/hash); дата события ≠ дата импорта; старый `timestamp` не переименовывать без проверки семантики; REUSE write-механизм `mca-01`. **Выход:** правки + тесты. **Критерий:** MCA03-R2; инварианты 3, 9; A08/A11. **Зависимости:** T-3783.

## Блок C — роли/алиасы, редакции, миграция chat_id (T-3785…T-3787)

- [x] **T-3785 [@Builder — роли и алиасы]** — **Цель:** разделить автор/адресат/цитируемый/субъект; `ALIAS > real_name > username` — display-only; REUSE `services/aliases*`/identity Epic 3; одноимённые не объединять. **Выход:** правки + тесты. **Критерий:** MCA03-R3/GEN-R19; инварианты 4, 5; A07/A88. **Зависимости:** T-3783.
- [x] **T-3786 [@Builder — редакции/версии]** — **Цель:** редакция → новая версия + обновление поиска + пометка зависимых выводов на пересмотр; `unavailable/deleted` — только по свидетельству. **Выход:** правки + тесты. **Критерий:** MCA03-R4; инварианты 6, 7; A08. **Зависимости:** T-3784.
- [x] **T-3787 [@Builder — миграция chat_id]** — **Цель:** явный mapping исторических смен `chat_id` по подтверждённым метаданным; не объединять по похожему названию. **Выход:** правки + тесты. **Критерий:** MCA03-R5; инвариант 8; A07. **Зависимости:** T-3783.

## Блок D — producers/consumers (T-3788…T-3789)

- [x] **T-3788 [@Builder — producers]** — **Цель:** live ingestion + edited messages + импорт (namespace/dataset) пишут canonical identity через **существующий** путь (`handlers/summary.py`); собрать фактическую заполненность ID/пересечения импорт/live (GEN-R20). **Выход:** правки + evidence. **Критерий:** MCA03-R1/R3, GEN-R19/R20; инварианты 1, 2; A07/A88. **Зависимости:** T-3784, T-3785.
- [x] **T-3789 [@Builder — consumers]** — **Цель:** потребители (досье/RAG/retrieval/истории) используют canonical identity и устойчивый source record ID; legacy/unknown корректны; второй контракт не создаётся. **Выход:** правки + тесты. **Критерий:** MCA03-R3/A88; инвариант 2; A88. **Зависимости:** T-3788.

## Блок E — тесты (T-3790…T-3791)

- [x] **T-3790 [@Builder/@Tester — контрактные тесты]** — **Цель:** два одинаковых имени не сливаются; цитата ≠ мнение; два чата с одинаковым `message_id` не конфликтуют; редакция обновляет версию; `unavailable` только по свидетельству; mapping `chat_id`. **Выход:** тесты. **Критерий:** инварианты 1, 4, 5, 6, 7, 8; A07/A08/A11. **Зависимости:** T-3785, T-3786, T-3787.
- [x] **T-3791 [@Builder/@Tester — интеграционные тесты]** — **Цель:** end-to-end на **обновлённых** путях с реально включёнными функциями: A07 (два Макса/цитата/forward/смена алиаса), A08 (редакция→версия+пометка), A11 (2022 найдено сегодня → две даты), A88 (не смешать источники/одноимённые по устойчивому ID). Перенос старого unit-теста недостаточен. **Выход:** тесты + evidence. **Критерий:** A07/A08/A11/A88; инварианты 3, 5, 6. **Зависимости:** T-3788, T-3789, T-3790.

## Блок F — диагностика (MCA-13 события / стадии MCA-17a) (T-3792…T-3793)

- [x] **T-3792 [@Builder — события/наблюдаемость]** — **Цель:** события по контракту `mca-13` (`start`+`outcome`) с `reason_code` (`ambiguous_identity`/`source_revision_changed`/`source_missing` при применимости); регистрация стадий/виджет-ID процесса для `mca-17a` (новый процесс без наблюдаемости = незавершённая интеграция). REUSE `emit_mca_event`/`mca_events` — второй store запрещён. **Выход:** события + тесты. **Критерий:** MCA03-R4, MCA13-R1/R2, GEN-R17; A27. **Зависимости:** T-3786.
- [x] **T-3793 [@Builder — R17-маскирование]** — **Цель:** в логах/событиях только id/коды/`error_type`; SourceRef вместо полного сырого контекста; `sanitize()` до записи во все каналы; маскирование секретов. **Выход:** тесты. **Критерий:** GEN-R14/R17; инвариант 10; A53. **Зависимости:** T-3792.

## Блок G — регрессии + deploy-подготовка (T-3794…T-3795)

- [x] **T-3794 [@Builder — регрессии]** — **Цель:** identity/dossier Epic 3 и FTS/поиск не регрессируют; старые ID/таблицы сохранены; kill-switch OFF = точный legacy-путь (паритет baseline); старые форматы ID обработаны. **Выход:** тесты. **Критерий:** GEN-R19, MCA14-R2/R5, FIN-R1; инварианты 9, 10; A28/A87. **Зависимости:** T-3791.
- [x] **T-3795 [@Builder/@DevOps — deploy-подготовка `DEFERRED_TO_RELEASE`]** — **Цель:** подготовить вход в единый релиз `mca-release`: migration smoke `v16`, запись в manifest §20 (`config changes`, путь возврата), effective-state/rollback (аддитивный `v16` безвреден; hot — kill-switch; cold — `git revert` к `7165ff7`). Пер-фичевого деплоя/тега/bump нет. **Выход:** раздел deploy/rollback. **Критерий:** MCA14-R4/R5, GEN-R23/R24; инвариант 10; A28. **Зависимости:** T-3794.

## Блок H — ревью / merge / архивация (T-3796…T-3797)

- [ ] **T-3796 [@Reviewer/@Architect — ревью + merge]** — **Цель:** единый Reviewer gate (обе линзы: requirements/correctness + focused change audit; при R3 — `threat-failure-analysis.md`); при отсутствии блокеров — Merge в `plans/ARCHITECTURE.md` (**§96+**, следующий фактически свободный), ADR Accepted; binding (Reviewed-Commit/Working-Tree-Hash/Product-Code-Hash). **Выход:** `review.md` + раздел Merge. **Критерий:** release-blocking findings закрыты; deploy `DEFERRED_TO_RELEASE`. **Зависимости:** T-3794, T-3795.
- [ ] **T-3797 [@PM — архивация]** — **Цель:** архивировать **полную** папку фичи в `plans/archive/` при подтверждённом `Approved`+binding+deploy-VERIFIED/NOT_APPLICABLE+reconcile @Architect; сохранить стабильные ID, разрешить относительные ссылки, обновить backlog (без потери истории). **Выход:** `plans/archive/mca-03-message-identity-round1027/`. **Критерий:** архив только после подтверждённого gate; ссылки разрешены. **Зависимости:** T-3796.

## Блок I — rework round 10.27 (по итогам Reviewer gate; B-MCA03-1/B-MCA03-2 + non-blocking)

- [x] **T-3796-R1 [@Builder — B-MCA03-1 namespace per-import]** — **Цель:** устранить коллизию `message_source_records` при импорте ≥2 экспортов с пересечением record-id. **Фикс:** `tools/history_import/loader.py` — `_dataset_namespace(path)` (`import:<export_id>:<file-fingerprint>`), per-file namespace по умолчанию, `load_file`/`import_history_fts` принимают явный override; legacy-backfill namespace не меняется. **Тест:** `test_import_two_exports_same_record_ids_keep_provenance` (2 экспорта с одинаковой шапкой/record-id → `message_source_records == 4`, 2 namespace). **Готово.**
- [x] **T-3796-R2 [@Builder — B-MCA03-2 две даты live]** — **Цель:** сделать различие `sent_at` (дата события) и `ingested_at` (время записи) явным и проверяемым. **Фикс:** `handlers/summary.py` — независимые `sent_at=_sent_at_of(message)`/`ingested_at=now`, legacy `timestamp`=время записи; ослабленный assert заменён строгим. **Тест:** `test_observer_sent_at_is_telegram_date_not_ingest_time` (2022-событие → `sent_at < ingested_at`), `test_observer_live_writes_identity` (строго). **Готово.**
- [x] **T-3796-R3 [@Builder — M-MCA03-4 связывание импорт↔live]** — **Фикс:** `services/database.py::save_smart_message_identity._record_occurrence` пишет вхождение и на существующей canonical-строке (`INSERT OR IGNORE`). **Тест:** `test_import_and_live_share_one_canonical_source`. **Готово.**
- [x] **T-3796-R4 [@Builder — M-MCA03-5 `sent_at` в changed-ветке]** — подтверждено наличие `COALESCE(sent_at, ?)` в changed-UPDATE; добавлен регресс-тест `test_existing_row_backfills_sent_at_on_changed_update`. **Готово.**
- [x] **T-3796-R5 [@Builder — M-MCA03-3 wiring `chat_id_migrations`]** — **Фикс:** DI `db` в `setup_chat_lifecycle` (bot.py) + запись `register_chat_id_migration` в `on_chat_migrated` (fail-open). **Тест:** `test_chat_migrated_wiring_records_chat_id_mapping`. **Готово.**
- [x] **T-3796-R6 [@Builder — L-MCA03-6/-7 границы]** — зарегистрированы как границы (re-observation echoyun не пишет revision — версии только через `edited`; bot-edit остаётся вне revision-логики). Документировано в `evidence.md` §9. **Готово.**

## Критерий готовности фичи

Логическая идентичность `chat_id + tg_message_id`, namespace/dataset + source record ID, canonical source; поля/время/версии (event≠import time); разделение автора/адресата/цитируемого/субъекта с display-only алиасами; редакции→версии с пометкой зависимых; `unavailable/deleted` только по свидетельству; явный mapping `chat_id`; Δ DDL `v16` через реестр `mca-14` (duplicate pre-check, backfill bounded); REUSE Epic 1–3 (identity/dossier, ToolResult) сохранён; события MCA-13/стадии MCA-17a; R17-маскирование; тесты A07/A08/A11/A88 на обновлённых путях с ON; @Reviewer Approved; Merge (§96+) — @Architect. **Deploy — `DEFERRED_TO_RELEASE`** (§20).
