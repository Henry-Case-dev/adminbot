# `mca-04b-dossier-rebuild` — спецификация (Step 2 @Architect, T-3889)

> **Статус:** 🟦 PLANNING — Step 2 @Architect (refresh Step 2b 30.09.2026; **confirm Step 2b-confirm 01.10.2026**). Код НЕ менялся (только `plans/**`). `ADR-1027-9` — **Accepted-ready** (финальный Accepted — только по Merge в `plans/ARCHITECTURE.md` **§107+**; §101–§105 заняты ASAP-2/2.1/3/3.1 + EXTRA; §106 — release-marker ASAP-3.2). Секреты источника не цитируются (R17/R18).
> **Фича:** `mca-04b-dossier-rebuild` (эпик round 10.27 MCA, **Wave 2 — когниция**; §8.3/§8.3.1/§8.3.3/§8.3.4). **Deploy:** `DEFERRED_TO_RELEASE`.
> **ТЗ-основание:** `plans/current_task.md` v1.8, §8.3 (`:238–250`), §8.3 «Обязательное исправление досье» (`:252–254`), §8.3.1 (`:256–266`), §8.3.3 (`:282–292`), §8.3.4 (`:294–300`); §3/§3.1 (`:47`, `:60–75`); §17.1–§17.3 (`:818–844`); §18 (`:856–872`); §19 A85/A86/A87/A88/A89/A90/A95; §20; §22; R17/R18.
> **Baseline (confirm 01.10.2026, Step 2b-confirm @Architect):** прод **2.58.40** — прод-HEAD **`4cb267a`** (feat `0483386`; локальный docs-HEAD `486b3e9`); `APP_VERSION` **2.58.40**; SQLite DDL **v19** (не менялась; Δ=0 во всех ASAP/EXTRA/ASAP-3.2-релизах; v20-объекты в коде отсутствуют — верифицировано); каталог **488/427/463/105/103/21** (Δ=0 с 2.58.39); последний раздел `ARCHITECTURE` — **§106** (release-marker ASAP-3.2); merge-цель — **§107+**; точка отката (код) — фактический базовый коммит Build (прод `4cb267a`; исторические анкеры `1287130`/`05bc870`/`7165ff7`). Историческое: refresh-анкер `1287130`/2.58.39 (30.09.2026); `2.58.31` / `473/430/448/102/100/21` / pytest `9828/0` + JS `48/48`.
> **Входы (✅ закрыты):** §93 (`mca-14`), §94 (`mca-13`, carry-over §94.5), §95 (`mca-01`, L-MCA01-5 §95.5), §96 (`mca-03`), §97 (`mca-02`), §98 (`mca-04a`, carry-over §98.4), §99 (`mca-07`, N-MCA07-1 §99.4), §100 (`mca-17a`).
> **Risk-Level:** **R3** (см. §7). `Browser-Verification:` **OPTIONAL** (см. §6.3).

## 1. Назначение и границы

### 1.1. Что делает фича

Один контракт **полной пересборки досье** (chat/subject) для UI и CLI, три включённых режима пополнения памяти, durable batch-состояния с честной финализацией, замена «архива в RAM / одним промптом» на дисковый поточный проход с иерархическим синтезом, **безопасное исправление накопленных досье** (staging/generation + атомарная активация + backup/rollback), каскадный пересчёт производных, врезка контракта `mca-04a` (`local → SourceRef`) в фактический chunk-пайплайн, операция активации vec-поколения (`N-MCA07-1`) и проверяемая выборка точности/полноты (Леха/Вася/Ярик).

### 1.2. В границах (scope)

- **Full rebuild контракт:** область `chat/subject`, заданный диапазон, **snapshot boundary**, **версия экстрактора**, **устойчивый cursor**; live-window limit ≠ предел пересборки.
- **Три режима:** (1) новые данные (инкрементальный live), (2) восстановление при востребованном чтении старой записи, (3) фоновый проход по архиву (не только популярные темы).
- **Batch-состояния/checkpoint/идемпотентность/сортировка** и финализация без подмены `processed → total`.
- **Дисковый поточный проход:** порции чтения ≤500 с дальнейшим делением по токенам/эпизодам; 1 активный LLM batch на чат; приоритет прямых ответов; backlog на диске; результаты извлечения по batch на диске; иерархический синтез по субъекту и периодам.
- **Исправление накопленных данных (§8.3.4):** безопасная реклассификация, исправление subject, отделение общих знаний от личных фактов, сохранение исходных сообщений/ручных правок/защищённых сведений, `unknown`/quarantine вместо ложного `confirmed` и вместо удаления.
- **Staging/generation + атомарная активация + backup/rollback**; сохранение обновлений, пришедших во время пересборки; идемпотентная повторная активация.
- **Каскадный пересчёт** зависимых (портреты → RAG → убеждения → парадигмы) по очереди с сохранением истории.
- **Выборка A95** (Леха/Вася/Ярик): precision/recall **отдельно от охвата**, негативные примеры, отчёт с пропусками и причинами.
- **Наблюдаемость/счётчики/покрытие** по годам/месяцам; регистрация стадий/виджет-ID для `mca-17a`.
- **Carry-over 04a:** прод-вызов `reconstruct_fact_provenance`; врезка `local → SourceRef` в chunk-пайплайн (row-bound уже подключён); `N-MCA04A-1..3`; `L-MCA03-8` (версионирование namespace-отпечатка); `N-MCA07-1` (активация vec-поколения).

### 1.3. Вне границ (excluded scope)

- **Второй dossier-движок/job-store/embedding-активатор/`TaskSupervisor`/write-механизм** — запрещены (GEN-R19). Переиспользуются существующие (см. §4.9).
- **Второй контракт идентичности/версий/provenance/субъекта** — запрещён; §8.3.2 берётся из `mca-04a`.
- **UI-витрина** полного представления процессов/инцидентов/уровней/drill-down и полная матрица §27.2/§27.8/§27.10 — зона `mca-17c` (A54/A56/A57/A73). `mca-04b` регистрирует стадии/виджет-ID и отдаёт backend-счётчики (как `mca-17a`).
- **Эпизоды/истории** (§9, `mca-05`), **сон/парадигмы** (§10, `mca-06`) — потребители исправленных фактов; `mca-04b` их **не** переписывает, а инициирует существующий каскад.
- **Миграция/деплой** — `DEFERRED_TO_RELEASE`; пер-фичевых деплоев/тегов/bump нет.
- **PG** — вне diff (`pg_db.py` no-op, GEN-R4).
- **Новые UI-настройки** — не вводятся (Δ каталога = 0).

## 2. Требования REQ → SC

> REQ-ID — авторство @Architect (T-3889). Соответствие табличным `MCA04-R5…R9` — §2.1. **Орфан-REQ/SC нет.**

| REQ | §ТЗ | Требование (нормативно) | SC |
|---|---|---|---|
| REQ-MCA04B-01 | §8.3 (`:242`,`:244`,`:246`) | Три включаемых режима; job-поля `dataset/range/cursor/version/status/heartbeat/attempt/processed_count/linked_count/unresolved_count/errors`; уникальный ключ; checkpoint после фиксации; идемпотентный повтор; стабильная сортировка без OFFSET; никакого «архива в RAM/одним промптом». | SC-01, SC-02, SC-05, SC-06 |
| REQ-MCA04B-02 | §8.3 (`:248`) | Worker-конфигурация: 1 активный LLM batch на чат; чтение порциями до 500 с делением по токенам/эпизодам; приоритет прямых ответов; backlog на диске; конфигурация увеличиваема. | SC-07, SC-09 |
| REQ-MCA04B-03 | §8.3.3 (`:288`) | Сохранение результатов извлечения на диск по batch; иерархический синтез по субъекту и периодам; новый live-batch **обновляет** накопленную картину, не заменяет её портретом последних 300 сообщений; изменения/противоречия версионируются. | SC-06 |
| REQ-MCA04B-04 | §8.3.3 (`:284`) | Один контракт full rebuild для UI и CLI: область chat/subject, заданный диапазон, snapshot boundary, версия экстрактора, устойчивый cursor; live-window limit = размер окна/batch, но не предел; новые сообщения после границы снимка догоняются инкрементально; кандидаты не грузятся одним списком в RAM/LLM. | SC-03, SC-01 |
| REQ-MCA04B-05 | §8.3.3 (`:286`) | Учёт собственных сообщений участника, надёжно разрешённых упоминаний другими и reply-контекста; отбор только по имени/автору недостаточен; короткие ответы не отбрасываются механически; бесшумные участники — из всего нужного scope. | SC-08, SC-16 |
| REQ-MCA04B-06 | §8.3.3 (`:290`) | Различимые batch-состояния `queued/running/paused/interrupted/failed/completed` (или эквивалент); budget exhaustion/недоступность модели/parse error/отмена/перезапуск ≠ «всё обработано»; неполные диапазоны остаются в очереди; полное завершение — только при обработке всех диапазонов без потерянных batch; `processed` не подменяется `total`. | SC-04, SC-11 |
| REQ-MCA04B-07 | §8.3.4 (`:296`) | Новые правила не очищают старые `confirmed` автоматически; безопасная повторная классификация производных; исправление subject; отделение общих знаний от личных фактов; исходные сообщения/ручные правки/защищённые сведения сохраняются; не удалять все `confirmed` по совпадению target; записи без восстановимого источника → явный `unknown`/quarantine (не ложное подтверждение, не удаление всей памяти). | SC-10 |
| REQ-MCA04B-08 | §8.3.4 (`:298`) | Новая версия строится в staging/generation с последующей атомарной активацией проверенного результата; прежняя рабочая версия доступна до замены; существующий backup/rollback сохранён; обновления во время пересборки не теряются; сбой Layer B/лимит/частичный проход не уничтожают старые факты; повторная активация и рестарт идемпотентны. | SC-12 |
| REQ-MCA04B-09 | §8.3.4 (`:298`) | После исправления зависимые портреты, RAG, убеждения и парадигмы пересчитываются **по очереди** с сохранением истории. | SC-13 |
| REQ-MCA04B-10 | §8.3.1 (`:263`,`:265`,`:266`) | `_WINDOW_SQL LIMIT`/`start_dossier_rebuild`-прогресс от bounded window → пересборка охватывает весь заданный диапазон; budget-exhaustion в `run_dossier_rebuild` больше не даёт `done`/`processed=total`; `upsert_generated_dossier` не стирает долгосрочную картину. | SC-01, SC-11, SC-06 |
| REQ-MCA04B-11 | §8.3.1 (`:264`), §8.3.2 (`:276`) | `_classify_chunked_user` переводит локальные номера evidence в **постоянные SourceRef** сразу после каждого чанка, с проверкой существования/версии/чата/диапазона строки; одинаковый локальный номер в разных чанках ≠ один источник; невалидный кандидат → диагностируемая причина. | SC-08, SC-16 |
| REQ-MCA04B-12 | §8.3.4 (`:300`) | Проверка реальных кейсов Лехи/Васи/Ярика по источникам (не подгонка под ожидания); выборка разных лет и типов; зафиксированные ожидаемые включения/исключения; precision/recall **отдельно от охвата**; заведомо чужие/общие сведения в негативных примерах исключены; отчёт показывает пропущенные примеры и причины; длина портрета — не критерий. | SC-14, SC-15 |
| REQ-MCA04B-13 | GEN-R19 (§3/§3.1) | REUSE, не второй контур: `services/lore_worker.py`/`services/dossier_rebuild_jobs.py`/`web/api/chat_lore.py`/`services/database.py::upsert_generated_dossier`/`TaskSupervisor`/`task_jobs`/`write_transaction`/`mca_events`/`MigrationStep`/`mca_embedding_index_generations`. | SC-17 |
| REQ-MCA04B-14 | MCA13-R1/R2, GEN-R17/R14 (§17/§27) | Раздельные счётчики (доступно/просмотрено/отобрано/кандидаты/принято/отвергнуто по причинам/`unresolved`/обновлено/ошибки/пропуски) + покрытие по годам/месяцам; размер окна ≠ прочитано ≠ передано модели; `start`+терминальный `outcome`; регистрация процесса/стадий/виджет-ID для `mca-17a`; нулевой результат при полном проходе — валиден; секреты не логируются. | SC-19, SC-18 |
| REQ-MCA04B-15 | MCA14-R1/R2/R3/R5 (§18) | Аддитивные идемпотентные миграции через реестр `mca-14`; старые ID/таблицы сохранены; `nullable` = честный unknown; архивные jobs без долгой транзакции; resume с checkpoint; kill-switch env-only default ON, OFF = паритет baseline. | SC-20 |
| REQ-MCA04B-16 | §98.4/§99.4 (carry-over) | `D-MCA04A-2` (прод-вызов `reconstruct_fact_provenance`), `D-MCA04A-3` (A95-выборка), `D-MCA04A-7` (perf-оценка provenance), `N-MCA04A-1..3`, `L-MCA03-8` (namespace `import:<export_id>:<v2>`), `N-MCA07-1` (API активации vec-поколения, REUSE v18). | SC-16, SC-12 |
| REQ-MCA04B-17 | GEN-R20 (§3) | Собрать фактические данные (ID-заполненность, объём архива, пересечения) на прод/рабочей БД при релизе; не блокировать деплой ожиданием обработки. | SC-18 |
| REQ-MCA04B-18 | FIN-R1 (§31) | Максимальное покрытие тестами, прогон, отсутствие конфликтов; интеграционные — с реально включёнными функциями; перенос старого unit-теста недостаточен. | SC-01…SC-20 |

### 2.1. Соответствие табличным REQ (`tasks.md`)

| `tasks.md` | spec REQ |
|---|---|
| MCA04-R5 | REQ-MCA04B-01/02/03 |
| MCA04-R8 | REQ-MCA04B-04/05/06 |
| MCA04-R9 | REQ-MCA04B-07/08/09/12 |
| MCA04-R6 | REQ-MCA04B-10/11 |
| MCA04-R7 | REQ-MCA04B-11 (shared) |
| GEN-R19 | REQ-MCA04B-13 |
| GEN-R20 | REQ-MCA04B-17 |
| MCA13-R1/R2 + GEN-R17/GEN-R14 | REQ-MCA04B-14 |
| MCA14-R1/R2/R3/R5 | REQ-MCA04B-15 |
| FIN-R1 | REQ-MCA04B-18 |
| carry-over §98.4/§99.4 | REQ-MCA04B-16 |

> **Уточнение к легенде `tasks.md`** (T-3891): предварительная легенда PM «REQ-10 = GEN-R19 / REQ-13 = MCA13 / REQ-14 = FIN-R1 / REQ-18 = GEN-R20» заменена авторской нарезкой @Architect выше. `tasks.md`-колонки `REQ`/`SC` заполняются @PM при сверке по этой таблице.

## 3. Наблюдаемое поведение и отказы

### 3.1. Нормальные сценарии

1. **Запуск full rebuild** (UI `start_dossier_rebuild` или CLI) для `chat/subject` с диапазоном: фиксируется `snapshot_boundary=(ts,id)`; job регистрируется с уникальным ключом (chat,subject,scope,range); прогресс считается от **полного** диапазона, а не от bounded window.
2. **Поточный проход:** чтение keyset-батчами `(timestamp,id)` ASC без OFFSET; каждый батч ≤500, при необходимости дробится по токенам/эпизодам; Layer A → дисковый артефакт извлечения по batch; накопление кандидатов; **один** Layer B синтез (иерархия по субъекту/периодам); запись производных.
3. **Checkpoint:** после фиксации результата батча cursor продвигается (в job state и `checkpoint_ref`); повторный запуск продолжает с cursor.
4. **Инкрементальный live (режим 1):** новые сообщения после границы снимка обрабатываются отдельным batch-путём и **обновляют** накопленную картину.
5. **Read-time recovery (режим 2):** при чтении старой записи вызывается `reconstruct_fact_provenance` (прод-путь); вектор — кандидат, не доказательство.
6. **Фоновый проход (режим 3):** периодически обходится весь доступный диапазон по покрытию (не только популярные темы), resumable.
7. **Исправление:** реклассификация строит новое поколение в staging; активация атомарна; прежняя версия остаётся доступной; каскад пересчитывает зависимые по очереди.

### 3.2. Отказы и их наблюдаемость (fail-closed там, где требуется)

| Ситуация | Поведение | Наблюдаемость |
|---|---|---|
| **Budget exhaustion** | job → `paused` (не `completed`); неполный диапазон остаётся в очереди; `processed` < `total` | событие `outcome=skipped`, `reason_code=budget_exhausted`; состояния/счётчики |
| Недоступность модели | job → `paused`/`failed` (по retryability); не `completed` | `reason_code=model_unavailable` |
| Parse error чанка | чанк пропущен (fail-open по извлечению), батч не «завершён»; ошибка зафиксирована | `reason_code=parse_error`; счётчик `errors` |
| Отмена | job → `interrupted`/`cancelled`; прежняя версия не тронута | `reason_code=cancelled/interrupted` |
| Рестарт процесса | незавершённые job → `interrupted`; resume с checkpoint; без дублей | `reason_code=interrupted`; checkpoint-ref |
| Сбой Layer B / частичный проход | старая версия/старые факты **не** уничтожены; job не `completed` | `outcome=failed/skipped`, `failed_stage` |
| Запись без восстановимого источника | `unknown`/quarantine; **не** `confirmed`, **не** удаление | `reason_code=provenance_unresolved` |
| Нет источника при восстановлении | кандидат `tentative` + причина; `original` не присваивается | `reason_code=provenance_unresolved` |
| Невалидный evidence чанка | кандидат отвергнут с причиной | `reason_code=evidence_invalid`; счётчик `rejected_by_reason` |
| Vec-fingerprint mismatch | FTS-only (gate `mca-07`); активация не выполняется | `reason_code=embedding_generation_changed` |
| Нулевой результат при полном корректном проходе | **валиден**; выдуманные факты/фиксированная норма не допускаются | счётчики + покрытие показывают полный проход |

### 3.3. Инварианты (нарушение = НЕ принято)

1. `live-window limit` (300 по умолчанию) — размер окна/batch, **не** предел пересборки.
2. `budget exhaustion`, недоступность модели, `parse error`, отмена, рестарт **никогда** не дают `completed`/100%.
3. `processed` не подменяется `total` при финализации.
4. Checkpoint продвигается **после** фиксации; повтор идемпотентен (перезапуск не удваивает связи).
5. Сортировка стабильным ключом `(timestamp, id)`; **без OFFSET** по изменяющимся миллионам строк.
6. Архив не грузится в RAM и не отправляется одним промптом; результат извлечения — на диск по batch.
7. Активация нового поколения досье атомарна; прежняя версия доступна до замены; повтор идемпотентен.
8. Реклассификация не удаляет исходные сообщения/ручные правки/защищённые сведения; не чистит `confirmed` автоматически; не удаляет всю память.
9. Записи без источника → `unknown`/quarantine (не ложный `confirmed`, не удаление).
10. `upsert_generated_dossier` больше не стирает долгосрочную картину.
11. Один контракт §8.3.2 (`SourceRef`/`EvidenceLink` из `mca-04a`); локальные номера evidence → постоянные SourceRef сразу после чанка.
12. Второй dossier-движок/job-store/embedding-активатор/`TaskSupervisor`/write-механизм не создаются.
13. Разные счётчики — разные единицы; «размер окна ≠ прочитано ≠ передано модели».
14. Нулевой результат при полном проходе — валиден.
15. Δ DDL (если и где необходимо) — только через реестр `mca-14`, аддитивно/идемпотентно; старые ID/таблицы сохранены.
16. R17: секреты/сырой контекст не логируются; `sanitize()` до записи во все каналы.

## 4. Интерфейсы и контракты данных

### 4.1. Full rebuild контракт (D1)

- **Область:** `chat_id` + `subject_ref_id` (`mca_source_refs`: `store='telegram'`, `entity_type='user'`, `entity_id=user_id`) — субъект устойчивым ID, не именем (§8.3.2).
- **Диапазон:** `range_from_ts`/`range_to_ts` (unix; `NULL` = от начала доступной истории). `scope_kind ∈ {full, range, incremental}`.
- **Snapshot boundary:** `snapshot_boundary_ts`/`snapshot_boundary_id` — зафиксированные при старте максимум `(timestamp, id)` в области. Проход охватывает `(timestamp,id) <= boundary`. Сообщения после границы догоняются режимом 1.
- **Версия экстрактора:** `extractor_version` (единая с `services/provenance.py::EXTRACTOR_VERSION`) + `kernel_version` (версия правил реклассификации/деления).
- **Устойчивый cursor:** keyset `(last_ts, last_id)`; SQL-шаблон `WHERE (timestamp > :last_ts) OR (timestamp = :last_ts AND id > :last_id) ORDER BY timestamp, id LIMIT :batch` — **без OFFSET**.
- **Batch-конфигурация:** `MCA_DOSSIER_BATCH_MAX_MESSAGES` (default 500) — размер обработки; далее дробление по токенам/эпизодам; 1 активный LLM batch на чат; приоритет прямых ответов (`direct`-flow не блокируется).
- **Backlog на диске:** незавершённые batch/diagnostic-артефакты — в `jobs_dir`/`archive_dir` (REUSE существующих каталогов dossier-jobs).

### 4.2. Batch-состояния (D3) и связь с `mca-01`/`mca-17a`

- **Rebuild-состояния** (authoritative в `DossierRebuildJobStore`): `queued | running | paused | interrupted | failed | completed` (+ `cancelled` как отдельное терминальное, эквивалент ТЗ «отмена»).
- **Маппинг в `task_jobs` (`mca-01`, v14/v19):** `queued→queued`, `running→running`, `paused→queued` (+`reason_code=budget_exhausted`/`paused`), `interrupted→interrupted`, `failed→failed`, `completed→completed`, `cancelled→cancelled`. `paused` ≠ `completed`.
- **Связь с lifecycle `mca-17a` (v19):** run-level `mca_pipeline_runs.status ∈ {running, succeeded, partial, degraded, failed, cancelled, interrupted}`; стадии — 9 состояний `mca-17a`. Rebuild `paused` отражается `partial`/`degraded` при частичном проходе (не `succeeded`), `stalled` — диагностическое.
- **Финализация:** `completed` — только если все предусмотренные диапазоны обработаны и нет потерянных/необработанных batch; `processed` фиксируется фактическим значением, не `total`.

### 4.3. Счётчики и покрытие (D11)

Раздельно и в разных единицах: **доступно в диапазоне** (SELECT COUNT по области до boundary) / **просмотрено** (прочитанные строки) / **отобрано для субъекта** (после фильтра субъекта) / **извлечено кандидатов** / **принято личных фактов** / **отвергнуто по причинам** / **`unresolved`** / **обновлено портретов и мемов** / **ошибки** / **пропуски**; job-счётчики `processed/linked/unresolved/errors`; **покрытие по годам/месяцам** (`coverage_json`). Размер окна ≠ прочитано ≠ передано модели. Нулевой результат при полном корректном проходе — валиден.

### 4.4. Staging/generation и активация (D8)

- **Регистр поколений** `mca_dossier_generations` (v20): `state ∈ {building, active, superseded, failed}`; одна `active` на `(chat_id, subject_ref_id)` (partial UNIQUE).
- **Staging** `mca_dossier_staging_items` (v20): предлагаемые производные (портрет/личный факт/мем/дерево) с классификацией/`source_ref_id`/`verification` — до активации не видны читателям.
- **Активация** (single-writer, одна короткая транзакция `write_transaction`): применить staged-элементы к `graph_facts` (с `dossier_generation_id = generation_id`), пометить предыдущую `active → superseded`, новую `building → active`. Идемпотентно (повтор на активном поколении — no-op).
- **Прежняя версия доступна:** строки `superseded`-поколения остаются в `graph_facts` (читатели используют активное поколение; legacy `dossier_generation_id IS NULL` — честный unknown/legacy).
- **Rollback:** REUSE `services/memory_backup.py` (VACUUM INTO прецедент) + повторная активация предыдущего поколения; restore БД — только аварийный сценарий (R18).
- **Сохранение ручных правок:** `persona_dossier_overrides`/`dossier_override` и защищённые сведения не затрагиваются активацией.

### 4.5. Реклассификация накопленных данных (§8.3.4) (D7)

- Безопасная повторная классификация производных записей (`confirmed`/`dossier_portrait`/`chat_meme`) в staging: исправление subject, отделение `world_knowledge` от личных фактов (контракт `mca-04a`: `attribution_method`/`assertion_kind`).
- Старые `confirmed` **не** очищаются автоматически; не удаляются все `confirmed` по совпадению `target`.
- Записи без восстановимого источника → `origin_status='unknown'`/quarantine; при неудачной проверке — кандидат + причина, не удаление.
- Исходные сообщения (`smart_messages`), `message_revisions`, ручные правки, защищённые сведения сохраняются.

### 4.6. Каскадный пересчёт (D9)

После активации — упорядоченный каскад через **существующие** контуры: (1) портреты/мемы (Layer B), (2) RAG/производные, (3) убеждения (сон), (4) парадигмы (глубокий сон). Каждый шаг — идемпотентный job (coalescing `TaskSupervisor`), версионирование с сохранением истории (старое место работы не удаляется). Второй контур не создаётся.

### 4.7. Врезка `local → SourceRef` в chunk-пайплайн (D8/04a) (T-3904)

В `services/lore_worker.py::_extract_chunk` после `filter_layer_a_candidates(..., row_count=len(lines))` (row-bound уже подключён) **добавляется** `services/provenance.py::local_evidence_to_source_refs(db, chat_id, window_rows, local_numbers)` с сохранением постоянных `SourceRef`/`EvidenceLink` (`derived_from`/`supports`); невалидные локальные номера → `valid=False` + `reason_code=evidence_invalid`; одинаковый локальный номер в разных чанках ≠ один источник (каждый чанк — свой `window_rows`). Второй контракт не создаётся.

### 4.8. Активация vec-поколения (`N-MCA07-1`) (D12)

REUSE `mca_embedding_index_generations` (v18). Добавляется **операция** (без новой таблицы) `activate_embedding_generation(index_name, generation_id)` — single-writer: пометить текущее `active → superseded`, целевое `building/failed → active`; `ensure_embedding_generation` при существующем `active` остаётся no-op. Вызывается после фактической перестройки несовместимого индекса (холодный/background job с причиной). Гейт `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED`.

### 4.9. REUSE-карта (D12)

| Артефакт | Режим | Суть |
|---|---|---|
| `services/dossier_rebuild_jobs.py` (`DossierRebuildJobStore`/`run_dossier_rebuild`) | **AMEND/FIX** | batch-состояния, checkpoint, не подменять `processed→total`, `paused` при budget/ошибке; durable job-store — **единственный** |
| `services/lore_worker.py` (`rebuild_dossier_for_user`/`_WINDOW_SQL`/`_classify_chunked_user`/`_extract_chunk`) | **AMEND/FIX** | full-rebuild контракт, снятие LIMIT как предела, keyset-проход, врезка `local→SourceRef`, сохранение `person_facts` |
| `web/api/chat_lore.py::start_dossier_rebuild` | **AMEND** | прогресс от полного диапазона; `snapshot boundary`/`extractor_version`; UI-парсинг существующих полей |
| `services/database.py::upsert_generated_dossier` (+ чтения `get_persona_card`/`get_user_context_facts`) | **FIX/AMEND** | не стирать долгосрочную картину; учёт активного `dossier_generation_id` |
| `services/provenance.py` (`reconstruct_fact_provenance`/`local_evidence_to_source_refs`/`validate_layer_a_row_bounds`) | **REUSE + прод-вызов** | контракт §8.3.2; не дублируется |
| `services/task_supervisor.py`/`task_jobs`/`write_transaction` (`mca-01`) | **REUSE** | очередь/coalescing/single-writer |
| `services/mca_events.py`/`mca_process_registry.py`/`mca_trace.py` (`mca-13`/`mca-17a`) | **REUSE** | события/стадии/виджет-ID/heartbeat |
| `mca_embedding_index_generations` (`mca-07`) | **REUSE + ADD операция** | API активации (без второй таблицы) |
| `services/memory_backup.py` | **REUSE** | backup/rollback |
| реестр `MigrationStep`/`schema_migrations` (`mca-14`) | **REUSE** | шаг **v20** |
| `services/message_identity.py`/`tools/history_import/loader.py` (`mca-03`) | **AMEND (L-MCA03-8)** | версия namespace-отпечатка `v2` |

## 5. Δ DDL (санкция) / Δ каталога / kill-switch

### 5.1. Санкция Δ DDL

- **Δ DDL = v20** (`user_version` 19→20), аддитивно/идемпотентно через реестр `mca-14` (§93). **Бронь:** доменные версии `mca-04b` начинаются с **v20** (v19 — `mca-17a`); **v21 остаётся свободной для `mca-04b`** (не объявляется/не используется, если не появится вторая аддитивная потребность на релизе).
- **Объекты v20:**
  1. `CREATE TABLE IF NOT EXISTS mca_dossier_generations` — регистр staging/generation (state/snapshot boundary/extractor_version/counters_json/coverage/supersedes/backup_ref/timestamps) + 2 индекса (в т.ч. partial UNIQUE `active`).
  2. `CREATE TABLE IF NOT EXISTS mca_dossier_staging_items` — предлагаемые производные (kind/subject_ref_id/source_ref_id/classification/payload_json/verification/extractor_version) + 1 индекс.
  3. `ALTER TABLE graph_facts ADD COLUMN dossier_generation_id TEXT` (nullable; `NULL` = legacy/unknown) + `idx_graph_facts_dossier_gen`.
- **Δ DDL = 0 доп.** для: batch-состояния/прогресс/покрытие — REUSE `DossierRebuildJobStore` (файловый, durable) + `task_jobs`/`mca_pipeline_runs` (v14/v19) + `payload`/`counters_json`; активация vec — REUSE `mca_embedding_index_generations` (v18); версия namespace `v2` — в строке отпечатка (`message_source_records.namespace`, без колонки).
- PG — **no-op** (`pg_db.py` вне diff; GEN-R4). Старые таблицы/ID/FTS/vec/`origin` CHECK сохранены; `nullable` = честный unknown; индексы — только под подтверждённый `EXPLAIN QUERY PLAN`; повторный прогон — no-op.
- **Обратный путь:** аддитивность (совместимый откат кода оставляет данные; новые таблицы/колонка безвредны); forward fix для несовместимого отката; restore БД — аварийный сценарий.

### 5.2. Точный DDL v20 (нормативно; Builder — по этому тексту)

```sql
-- v20 (mca-04b) — staging/generation исправления досье (§8.3.4)
CREATE TABLE IF NOT EXISTS mca_dossier_generations (
    generation_id            TEXT PRIMARY KEY,       -- UUID4 hex
    chat_id                  INTEGER NOT NULL,
    subject_ref_id           INTEGER NOT NULL,       -- mca_source_refs.source_ref_id (store=telegram,user)
    state                    TEXT NOT NULL,          -- building|active|superseded|failed
    scope_kind               TEXT,                   -- full|range|incremental
    range_from_ts            INTEGER,
    range_to_ts              INTEGER,
    snapshot_boundary_ts     INTEGER,
    snapshot_boundary_id     INTEGER,
    extractor_version        TEXT NOT NULL,
    kernel_version           TEXT,
    counters_json            TEXT,                   -- группы счётчиков + coverage по годам/месяцам (R17-safe)
    staging_ref              TEXT,                   -- ссылка на дисковые артефакты извлечения (R17-safe)
    supersedes_generation_id TEXT,
    backup_ref               TEXT,                   -- memory_backup ref
    created_at               INTEGER NOT NULL,
    activated_at             INTEGER,
    finished_at              INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mca_dossier_gen_subject
    ON mca_dossier_generations (chat_id, subject_ref_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mca_dossier_gen_active
    ON mca_dossier_generations (chat_id, subject_ref_id) WHERE state = 'active';

CREATE TABLE IF NOT EXISTS mca_dossier_staging_items (
    staging_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id      TEXT NOT NULL,
    item_kind          TEXT NOT NULL,                -- portrait|person_fact|meme|tree
    subject_ref_id     INTEGER,
    source_ref_id      INTEGER,
    classification     TEXT,                         -- assertion_kind/attribution_method (коды)
    payload_json       TEXT NOT NULL,                -- R17-safe структура (без сырого контекста)
    verification       TEXT NOT NULL,                -- verified|tentative|unknown|rejected
    extractor_version  TEXT,
    created_at         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mca_dossier_staging_gen
    ON mca_dossier_staging_items (generation_id, item_kind);

ALTER TABLE graph_facts ADD COLUMN dossier_generation_id TEXT;  -- nullable; NULL = legacy/unknown
CREATE INDEX IF NOT EXISTS idx_graph_facts_dossier_gen
    ON graph_facts (dossier_generation_id);
```

> Self-guard шага — `sqlite_master`/`PRAGMA table_info`; `user_version` фиксируется шагом (v20) в общем runner'е. `payload_json`/`counters_json`/`staging_ref`/`basis` — R17-safe (без сырого контекста/секретов).

### 5.3. Δ каталога = 0

Все рубильники/лимиты/пороги — env-only `ClassVar`; `param_catalog.py`/TSV/`_TAB_BY_GROUP`/TAB_RULES вне diff; каталог **488/427/463/105/103/21** не изменяется; F8 (ADR-1026-2) **NOT_APPLICABLE**. Существующий UI-запуск `start_dossier_rebuild` расширяется функционально, но **новых параметров каталога не вводит**. **Admin-only (confirm 01.10.2026):** действующий `_is_global_admin`-гейтинг `web/api/chat_lore.py` (определение `:169`; вызовы `:183/:267/:327/:348/:500`) **сохраняется на всех AMEND-путях** (запуск пересборки/чтение статусов) — продолжение политики admin-only мутаций (§104/§135); admin-проверка — код-уровень, не параметр каталога.

### 5.4. Kill-switch (утверждены, 7 имён; env-only `ClassVar`, default ON, резолв per-call, OFF = паритет baseline)

| # | Имя | OFF-паритет |
|---|---|---|
| 1 | `MCA_DOSSIER_REBUILD_ENABLED` (master) | legacy `run_dossier_rebuild` как сейчас (без нового контракта/состояний) |
| 2 | `MCA_DOSSIER_BACKGROUND_PASS_ENABLED` | фоновый проход по архиву не запускается |
| 3 | `MCA_DOSSIER_READ_RECONSTRUCTION_ENABLED` | read-time восстановление не запускается (связка с `MCA_EVIDENCE_RECONSTRUCTION_ENABLED` §98 — не дублируется) |
| 4 | `MCA_DOSSIER_RECLASSIFY_ENABLED` | безопасная реклассификация накопленных данных не выполняется |
| 5 | `MCA_DOSSIER_STAGING_ACTIVATION_ENABLED` | прямая запись как сейчас (без staging/generation) |
| 6 | `MCA_EMBEDDING_GENERATION_ACTIVATION_ENABLED` | gate `mca-07` FTS-only как сейчас (активация не выполняется) |
| 7 | `MCA_DOSSIER_NAMESPACE_FINGERPRINT_V2_ENABLED` | прежний отпечаток (`legacy_import_v1`/v1) |

Дополнительно env-only лимиты (не каталог): `MCA_DOSSIER_BATCH_MAX_MESSAGES` (default 500), `MCA_DOSSIER_DIRECT_PRIORITY_ENABLED` (default ON). **Приоритет/совместимость:** `MCA_DOSSIER_*` инертны при OFF соответствующих нижележащих (`MCA_TASK_SUPERVISOR_ENABLED`, `MCA_PROVENANCE_ENABLED`, `MCA_EVIDENCE_RECONSTRUCTION_ENABLED`, `MCA_FACT_ATTRIBUTION_ENABLED`, `MCA_RETRIEVAL_CONTEXT_ENABLED`, `MCA_OBSERVABILITY_ENABLED`, `MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED`, `MCA_MESSAGE_IDENTITY_ENABLED`). Существующие рубильники уважаются, не дублируются. **Auto-budgets (ASAP-3.1, ADR D14, confirm 01.10.2026):** бюджетная семантика `mca-04b` — **standalone env-only**; `MCA_DOSSIER_BATCH_MAX_MESSAGES` — размер обработки порции в **сообщениях** (не токен-бюджет); источник budget exhaustion — **существующий `worker_budget`** (baseline-поведение `lore_worker`); реакция — D3 (`paused` ≠ `completed`). Интеграция с `services/auto_budget.py`/`model_capacity.py` (Model Capacity Resolver, stage-aware бюджеты Summary/Direct) **не выполняется**: разные единицы учёта (инвариант 13), AMEND свежего кода ASAP-3.1 без требования ТЗ, риск для инварианта «budget exhaustion ≠ completed» не оправдан; Builder запрещено переподключать exhaustion на `auto_budget` (детали — ADR-1027-9, Confirm 01.10.2026, D14).

## 6. Приёмочные сценарии (SC) и браузерная проверка

### 6.1. SC-01…SC-20

| SC | Проверяемое утверждение | Приёмка | Задачи (ориентир) |
|---|---|---|---|
| SC-01 | Full rebuild при числе сообщений > live-window limit обрабатывает все диапазоны снимка, включая ранние годы; размер batch не ограничивает историю; есть доказательство охвата по годам. | A87 | T-3892/3893/3912 |
| SC-02 | Три режима реально включены и различимы: новые данные; read-time recovery; фоновый проход (не только популярные темы). | — | T-3895/3896/3898 |
| SC-03 | Один контракт full rebuild (chat/subject/range/snapshot boundary/версия экстрактора/устойчивый cursor); live-window ≠ предел; post-boundary сообщения догоняются инкрементально. | A87 | T-3893/3895 |
| SC-04 | Различимые batch-состояния; budget/модель/parse/отмена/рестарт ≠ `completed`; неполные диапазоны остаются в очереди; отключение budget-настройки не подменяет статус. | A89 | T-3894/3898 |
| SC-05 | Checkpoint после фиксации; идемпотентный рестарт без дублей связей; стабильный ключ `(timestamp,id)` без OFFSET. | A89 | T-3894/3897 |
| SC-06 | Архив не в RAM/одним промптом; извлечение на диск по batch; иерархический синтез по субъекту/периодам; новый live-batch обновляет, не заменяет. | A87 | T-3895/3897 |
| SC-07 | 1 активный LLM batch/чат; чтение ≤500 с делением по токенам/эпизодам; конфигурация увеличиваема. | A87 | T-3896/3898 |
| SC-08 | Локальные номера evidence → постоянные SourceRef сразу после чанка (существование/версия/чат/row-bound/субъект); одинаковый номер в разных чанках ≠ один источник. | A85/A86/A88 | T-3897/3904 |
| SC-09 | Приоритет прямых ответов; backlog на диске; проход разрешён и resumable; direct-flow не блокируется. | A87/A89 | T-3898 |
| SC-10 | Реклассификация не чистит старые `confirmed`; subject исправлен; общие знания отделены от личных; источник/ручные/защищённые сохранены; нет удаления всех `confirmed` по target; записи без источника → `unknown`/quarantine. | A90 | T-3899 |
| SC-11 | Budget/модель/parse/отмена/рестарт → различимые состояния, нет ложного `done`/`processed=total`. | A89 | T-3899/3909 |
| SC-12 | Staging/generation + атомарная активация; прежняя версия доступна до замены; обновления во время пересборки не теряются; повтор/рестарт идемпотентны; сбой Layer B/лимит/частичный проход не уничтожают старые факты; rollback через существующий backup. | A90 | T-3900/3901/3907 |
| SC-13 | После активации портреты/RAG/убеждения/парадигмы пересчитываются по очереди с сохранением истории; изменения/противоречия версионируются. | A90 | T-3901 |
| SC-14 | Реальная выборка Лехи/Васи/Ярика: собственные сведения/чужие рассказы/ответы/пересылки/новости/шутки/смена обстоятельств; ожидаемые включения/исключения зафиксированы; precision/recall измерены **отдельно от охвата**; негативные примеры исключены. | A95 | T-3902/3908 |
| SC-15 | Отчёт показывает пропущенные примеры и причины; длина текста не критерий; без подгонки под ожидания владельца. | A95 | T-3908 |
| SC-16 | Прод-вызов `reconstruct_fact_provenance`; `N-1` (name-резолв ограничен ростером/окном), `N-2` (chunked-путь сохраняет `person_facts`), `N-3` (детерминизм `guess_subject` пином); `L-MCA03-8` (namespace `import:<export_id>:<v2>`, `legacy_import_v1` не переприсваивается). | A85/A86/A88 | T-3903/3904/3905/3906 |
| SC-17 | REUSE-карта соблюдена: второй dossier-движок/job-store/embedding-активатор/`TaskSupervisor`/write-механизм не созданы; §8.3.2 — из `mca-04a`. | — | T-3900/3904/3907 |
| SC-18 | Фактические данные (ID-заполненность, объём архива, пересечения) собраны на прод/рабочей БД; скорость/стоимость измерены на разнообразной выборке; полный проход — оценка, не обещание. | GEN-R20 | T-3908/3915 |
| SC-19 | Раздельные счётчики (разные единицы) + покрытие по годам/месяцам; `start`+терминальный `outcome`; стадии/виджет-ID зарегистрированы для `mca-17a`; нулевой результат при полном проходе валиден; секреты не логируются. | A27/A48 | T-3910/3911 |
| SC-20 | Δ DDL v20 аддитивна/идемпотентна через `mca-14`; старые ID/таблицы сохранены; resume с checkpoint; kill-switch env-only default ON, OFF = baseline. | A28 | T-3892/3914/3915 |

### 6.2. Верификация по каждой проверке (ownership)

| Проверка | Владелец | Метод |
|---|---|---|
| SC-01/SC-03/SC-06/SC-07 (охват/поточность) | @Builder/@Tester | интеграционный тест на синтетической/реальной истории > окна; доказательство покрытия по годам |
| SC-04/SC-05/SC-09/SC-11 (состояния/checkpoint) | @Builder/@Tester | сценарии budget-exhaustion/ошибка/рестарт/отмена после части архива |
| SC-08/SC-16 (evidence/атрибуция) | @Builder | focused unit + real-DB smoke |
| SC-10/SC-12/SC-13 (реклассификация/активация/каскад) | @Builder/@Tester | staging→activation/rollback/idempotency + сохранение ручных правок |
| SC-14/SC-15 (A95) | @Builder + @Reviewer | фиксированная выборка/фикстуры + отчёт |
| SC-02/SC-19/SC-20 (режимы/наблюдаемость/DDL) | @Builder/@Tester | события/реестр стадий + migration smoke/идемпотентность |
| SC-17/SC-18 | @Reviewer/@DevOps | REUSE-аудит; GEN-R20-инспекция на релизе |

### 6.3. Browser-Verification

- **`Browser-Verification: OPTIONAL`.**
- **Обоснование:** `mca-04b` — преимущественно backend/data-контракт; единственная user-visible поверхность — **существующий** запуск пересборки (`start_dossier_rebuild`/`latest`/`get`) и регистрация стадий/виджет-ID для `mca-17a`. Полные представления/витрины/уровни/drill-down — зона `mca-17c` (A54/A56/A57/A73).
- **Если Builder затрагивает рендеринг существующей поверхности пересборки** (прогресс/счётчики/покрытие в минеаппе), обязателен **структурный** browser-check (Playwright MCP): маршрут `#/memory` → карточка досье → запуск пересборки → прогресс; проверить, что прогресс/счётчики считаются от **полного** диапазона (не от window), состояния различимы, `processed` не показывается как `total`; без пиксельных требований. При появлении визуально значимых изменений — эскалация до `REQUIRED` + Browser Use.
- **Креденшелы/WebView не изобретаются:** используется существующий тестовый контур miniapp (как в `mca-17a`: Playwright, RBAC global-admin); production-авторизация не запрашивается.

## 7. Зависимости, риски, откат, Risk-Level

- **Зависимости (✅):** `mca-04a` (§98), `mca-07` (§99), `mca-01` (§95), `mca-17a` (§100), `mca-03` (§96), `mca-13`/`mca-14` (§94/§93).
- **Потребители (исходящие):** `mca-05` (эпизоды), `mca-06` (сон/парадигмы), `mca-16` (lessons), `mca-18` (SelfModel/портрет), `mca-19`/`mca-20`; `mca-17c` (витрина); `mca-release`.
- **Риски:** (1) полнота охвата (`_WINDOW_SQL LIMIT` как предел) → SC-01/03; (2) ложный `done` → SC-04/11; (3) потеря данных при реклассификации → SC-10/12; (4) контаминация субъектов → SC-08/16; (5) ресурсы/OOM → SC-06/07; (6) смешивание embeddings → SC-12/16; (7) конкуренция за single-writer lock фоновым проходом → REUSE `TaskSupervisor`/короткие записи; (8) подгонка A95 → SC-14/15; (9) коллизия брони версий → зафиксирована (v20).
- **Risk-Level:** **R3** — пересборка/реклассификация меняет память/досье субъектов; каскад на RAG/убеждения/парадигмы/retrieval; фоновый обход архива конкурирует за single-writer lock; v20 меняет схему. **Что могло бы поднять:** перестройка vec-индекса на hot-path или мутация `graph_facts` под транзакцией с сетью/LLM (эскалация до R3+ и повторный reassessment `@Reviewer`). **Что могло бы понизить:** доказанная изоляция активации от hot-path + SC-01/04/08/10/12/16 на фактическом diff (как `mca-07` R3→R2).
- **`threat-failure-analysis.md`** — обязателен (R3).
- **Deploy:** `DEFERRED_TO_RELEASE` (§20). Точка отката: hot — `MCA_DOSSIER_REBUILD_ENABLED=false` (и/или под-гейты); cold — `git revert` → фактический базовый коммит Build (прод 2.58.40 = `4cb267a`; локальный docs-HEAD `486b3e9`; исторические анкеры `1287130`/`05bc870`/`7165ff7`; v20 аддитивна; restore БД — аварийный сценарий, R18).

## 8. Границы и carry-over

- **Нарезка 04a/04b:** 04a — контракт/атрибуция (§8.3.1 п.1/2/3 + контракт п.5); 04b — п.4/6/7 + фактическая врезка п.5 в chunk-пайплайн + прод-вызов `reconstruct_fact_provenance`.
- **Carry-over `mca-04a` (обязательные входы):** D-MCA04A-2 (прод-вызов reconstruction), D-MCA04A-3 (A95-выборка), D-MCA04A-7 (perf-оценка provenance-записи), N-MCA04A-1..3.
- **Carry-over `mca-03`:** L-MCA03-8 — версионирование namespace-отпечатка `import:<export_id>:<v2>` при касании loader'а; `legacy_import_v1` не переприсваивается; устранить пропуск source record при in-place регенерации файла с тем же размером.
- **Carry-over `mca-07`:** N-MCA07-1 — операция активации поколения; перестройка несовместимого vec-индекса остаётся зоной `mca-04b`.
- **Не блокирует:** GEN-R20-инспекция фактических данных на прод-БД — на `mca-release`.

## 9. Допущения / MEMORY

- Имена существующих символов (`_WINDOW_SQL`, `run_dossier_rebuild`, `start_dossier_rebuild`, `upsert_generated_dossier`, `ensure_embedding_generation`, `reconstruct_fact_provenance`, `local_evidence_to_source_refs`, `filter_layer_a_candidates`) — сверены на baseline `05bc870`; REUSE-файлы байт-в-байт не менялись с `1287130` (проверено PM на прод 2.58.40, 01.10.2026); актуальный baseline — прод 2.58.40/`4cb267a` (confirm 01.10.2026); при расхождении Builder сверяет фактические пути (граница §22).
- `LORE_WINDOW_MAX_MESSAGES` (300) остаётся размером обычного окна/чтения; предел пересборки задаёт диапазон/граница снимка, а не это значение.
- Секреты источника не переносятся/не цитируются (R17/R18).

_Конец spec. Создано @Architect в Step 2 задачи `mca-04b-dossier-rebuild`; код/тесты не менялись; `plans/current_task.md`/`workflow_state.md`/`metrics.md`/`MEMORY.md` не изменялись; ADR-1027-9 — **Accepted-ready** (Accepted — по Merge **§107+**). Refresh Step 2b 30.09.2026: baseline/merge-цель обновлены (HEAD `1287130`, 2.58.39, v19, каталог 488/427/463/105/103/21), санкции/DDL v20/kill-switch без изменений. Confirm Step 2b-confirm 01.10.2026: baseline прод **2.58.40**/`4cb267a`, merge-цель **§107+**; v20 — единственная SQLite-Δ (PG no-op, v21 свободна); **D14** auto-budgets — standalone env-only, источник exhaustion — существующий `worker_budget`, без интеграции с Model Capacity Resolver; admin-only `_is_global_admin`-гейтинг сохранён на AMEND-путях; санкции/DDL/kill-switch/R3 — без изменений._
