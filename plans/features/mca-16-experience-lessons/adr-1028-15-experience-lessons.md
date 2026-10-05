# ADR-1028-15 — mca-16-experience-lessons: банк опыта (ExperienceEpisode/Lesson), проверяемая активация, отбор в EvidenceBundle и полезность без изменения весов модели

**Статус:** **Proposed** (Step 2 @Architect, design-freeze, 05.10.2026; T-4989/T-4990) → Accepted по merge `plans/ARCHITECTURE.md` §119+ (последний занятый — §118 mca-10a) + прод-валидация.
**Дата:** 05.10.2026 (Step 2 @Architect, T-4989/T-4990)
**Номер проверен:** `ADR-1028-15` нигде не занят (grep по `plans/**` 05.10.2026: последний фактический — ADR-1028-14 mca-10a, Accepted 05.10.2026; `ADR-1028-1[5-9]`/`ADR-1028-2x` — 0 хитов). Merge-цель — следующий фактически свободный **§119+**.
**Фича:** `mca-16-experience-lessons` (Wave 3 эпика `memory-context-autonomy`); ТЗ `plans/current_task.md:1173–1282` §25.1–§25.7; приёмки A43–A47 `:924–928`, A57 `:938`, A49 `:930`; §20.2 `:1018`; §27.1 `:1544`. Артефакты — `plans/features/mca-16-experience-lessons/` (spec, threat-failure-analysis, tasks, requirements-map). База: HEAD `e6d1616` на момент проверки (актуальный `92252d1` — docs-only архив mca-10a), прод 2.58.58, SQLite v27, каталог 502/107/105/21 (F8 `--check` OK), канон инструментов 12, `REASON_CODES` 221, `KILL_SWITCHES` 64.

---

## Контекст

Владелец требует инженерную адаптацию «банка опыта»: бот запоминает проверенные способы действий и ошибки, отличает «что случилось» / «чему это учит» / «где применимо», не объявляет себя обучившимся по самопохвале или числу реакций, и показывает реальную витрину «Опыт» (§25.1–§25.7). Без fine-tuning/LoRA/DPO/online RL, без новых framework-зависимостей; включено сразу, без Human Gate; candidate не активируется без проверки (§20.2 `:1018`). Уроки — процедурные поправки, не идентичность (§27.1 `:1544`); пороги (3 независимых эпизода, ESS, сглаживание) — инженерные стартовые (GEN-R27 `:1092`).

Зависимости закрыты: mca-15 (2.58.56, достоверные измерения — handoff: числа из ненадёжных агрегатов ≠ reward, `backlog.md:232`), mca-04a (§98, provenance), mca-17a (§100, реестр/trace), mca-01 (§95, очереди/транзакции), mca-06 (2.58.49, сон — lessons ≠ парадигмы), mca-07 (§99, единый EvidenceBundle), mca-08 (2.58.55, style request — граница), mca-11 (2.58.57, ToolResult; учёт расходов ≠ reward, `backlog.md:247`), mca-10a (2.58.58, RandomSource; независимость от квоты/расходов, `plans/archive/mca-10a-random-source-anu-round1038/tasks.md:68`). mca-16 разблокирует mca-18 (lessons ≠ traits, `quality_regression` `:1558`) и mca-12 (лента опыта/истории).

---

## Решения

### D1. ExperienceService — один контур опыта (один сервис, один write-механизм)

Дом — `services/mca_experience.py` (`ExperienceStore` + `ExperienceService` + `LessonService` + `ExperiencePolicy`, фасад `get_service()`) и `services/mca_experience_jobs.py` (durable-job `experience.review`; прецедент mca-05 `mca_episodes.py`/`mca_episode_jobs.py`). Все записи — `write_transaction` (mca-01); provenance — mca-04a; retrieval — mca-07; события — `emit_mca_event` (mca-13); очередь — `task_jobs` (mca-01). Второй store/сервис/координатор/словарь/очередь запрещены. Версии контракта: `mca16-policy-1`, `mca16-proposal-1`, `mca16-validator-1`, `mca16-select-1` (пишутся в журналы/уроки). **OFF (K1) = бит-в-бит 2.58.58.** (spec §1)

### D2. ExperienceEpisode и Feedback — контракт, идемпотентность, R17

Эпизод (§25.2 `:1204`): id/operation-trace/scope/chat/user/task type/decision (без hidden CoT)/tool-metric-lesson IDs/output ref/observed outcome/feedback refs-type-reliability/model-tool-config versions/timestamps; создаётся только для трасс с типизированным исходом (tool chain, direct+feedback, stats, коррекция) — не для каждого сообщения. Идемпотентность: `idempotency_key` UNIQUE (sha1-16 источника) — повторный ingest после рестарта = no-op (A47). Feedback (§25.3): `dedup_key` UNIQUE, source_kind (owner/participant/social/llm_hypothesis/technical), reliability, authority, status (`active|cancelled|corrected`) + `supersedes_id` — поддержаны дедуп, запоздалая связь по reply/trace, отмена/исправление. R17: только ID/коды/числа/ссылки; сырой текст/секреты/CoT не сохраняются. **OFF (K1) — записей нет; K2 — feedback-контур (кроме technical) закрыт.** (spec §2)

### D3. Lesson — поля, scope, delta-версии/lineage, изоляция, границы

Урок (§25.2 `:1206`): ID/version/type (`tool_usage|retrieval|context|social_preference|failure_pattern`)/applicability/scope/recommendation (серверный канон)/exceptions/grounding (mca-04a evidence links: supporting/contradicting)/status/counters/last_validated_at/compat. Scope `global|chat|user_in_chat|task`; `global` — только обезличенный техурок (без имён/цитат/фактов/ID чата); правила чужого чата недоступны retrieval без разрешённого scope; закрытые trace — только уполномоченным. Урок — данные ограниченного контракта: не меняет system prompt/секреты/инструменты/права/бюджет. Версии: insert v1; содержательное изменение — новая версия + `supersedes`; статус — in-place (аудит); merge — новая версия `merged_from_json`; delta, не переписывание книги. Границы: style request (mca-08, explicit-only, `mca_style_scope.py:1–32`) — директива; lesson — процедурная рекомендация; trait/paradigm (mca-18/mca-06) — не lesson; `quality_regression` `:1558` — сигнал цикла. **OFF (K1) — уроки инертны.** (spec §3)

### D4. Сигналы и анти-самоподтверждение (§25.3)

Закрытый набор сигналов: технический outcome (только своя стадия; HTTP 200/доставка ≠ истинность), явная коррекция с источником (владелец ≠ участник; «ты врёшь» — пересмотр, не истина), социальная реакция (слабая, не ground truth), LLM-самооценка (гипотеза). Молчание = unknown; нет наград за провокации/длину/число сообщений; числа из ненадёжных агрегатов ≠ reward (mca-15); расходы/квота ≠ reward (mca-11/mca-10a); injection «запомни навсегда…» не проходит как lesson; feedback/уроки не повышают собственный приоритет над инструкциями приложения. Анти-самоподтверждение: собственные ответы (mca-22) — не независимое подтверждение; одно первичное событие не может «применить» и «подтвердить» урок; social/LLM не активируют в одиночку. Дедуп/поздняя/отменённая связь — D2. **OFF (K2).** (spec §4)

### D5. Жизненный цикл и активация (§25.4)

Ровно пять состояний: `candidate/validated/active/suspended/superseded`; несовместимость — флаг `recheck_required`, не состояние. `candidate` не применяется. Активация: явное предпочтение → `user_in_chat` после разрешения автора/адресата + проверки конфликтов; техфикс → воспроизведение ошибки + успешный контрольный пример + инварианты; обобщение неявных сигналов → ≥3 независимых эпизода + проверка на новых контекстах (инженерный порог); `global` — только обезличенный техурок. Сильное противоречие → suspend (не спор с пользователем); смена tool schema/model fingerprint/config → recheck, исключение из отбора; изменение источника распространяет статус на связанные уроки (mca-04a `source_revision_changed`). Включено сразу, без Human Gate (§20.2). Исторический bootstrap — только candidate `historical/unverified`, явные проверяемые предпочтения после разрешения идентичности; без mass-backfill успеха; 2 млн сообщений без trace ≠ успешный опыт. **OFF (K3) — propose/validate/activate/recheck не выполняются.** (spec §5)

### D6. Отбор, полезность, EvidenceBundle (§25.5)

Отбор: scope+active → compatibility → релевантность (semantic gate существующими примитивами mca-07; без семантической связи урок не проходит по рейтингу) → полезность. Полезность: измерения correctness/tool_success/contextual_fit/preference_fit, success/failure/unknown, Beta(1,1)-сглаживание, ESS; unknown не обновляет; новые — нейтральны; обновляются только применённые уроки (журнал `mca_lesson_applications`, dedup-ключ; «применение ≠ причинность»); графовый RL не включается. Lessons — **отдельный тип в единственном** EvidenceBundle: аддитивное поле `lessons: tuple[LessonRef, ...] = ()` (`mca_retrieval_context.py:182`; `BUNDLE_SCHEMA_VERSION` не меняется; M-MCA07-2-поля не трогаются); bounded-блок (≤5 уроков / ≤600 токенов; не вытесняет вопрос/источники; не влез — `ExcludedItem budget_exceeded`); suspended/stale не включаются (A47). Интеграция — существующий `_build_evidence_bundle` (`direct_chat_service.py:1944–1948`) и scoped-срез (`:421–441`); один координатор, action-schema mca-09 не трогается; применение журналируется, исход линкуется review-job. **OFF (K4) — bundle/context_version = 2.58.58.** (spec §6)

### D7. Review-job, сон, случайность, holdout (§25.6–§25.7)

Один новый тип job в существующей очереди: `kind="experience.review"`, `owner="mca16"`, `coalesce_key="experience.review:global"` (singleflight; прецедент `mca_episode_jobs.py:40–51,68–87`); триггеры — каденция `memory.experience_review_cadence` + содержательная коррекция; шаги: capture-cursor → propose → validate → activate/suspend → outcome-link → utility-update → recheck → prune; **LLM-рефлексии на каждое сообщение нет** (предложения — детерминированные правила; LLM — только гипотеза внутри пакета, никогда активация). Deep sleep не смешивает lessons с парадигмами (отдельный job/сущности; mca-06 не меняется). Случайность: опыт exploration — из существующего журнала `mca_random_draws` как наблюдение; истинность/успех не рандомизируются; второго процента/RandomSource нет; контрольные контексты вместо массовых соцэкспериментов. Temporal holdout (§25.7 `:1281`): уроки только из прошлого; проверка на более поздних не-источниках; OFF/ON на одной модели; честный отчёт (повтор ошибок/корректность/уместность/доп.стоимость); отсутствие улучшения не подменяется числом lessons. **OFF (K3) — job не запускается.** (spec §7)

### D8. Хранение — additive v28 через mca-14

**v28** (`MigrationStep(28)`): 4 аддитивные таблицы + 9 индексов — `mca_experience_episodes` (UNIQUE idempotency_key; chat+created; scope+task), `mca_experience_feedback` (UNIQUE dedup_key; chat+created), `mca_lessons` (PK (lesson_id,version); status+scope; type+status), `mca_lesson_applications` (UNIQUE dedup_key; lesson+version+applied). Идемпотентно, повтор — no-op, PG — no-op, backup-guard fail-closed pre-DDL + read-back; старый код v28 не читает (cold-совместимо); backfill нет. Retention env-only (эпизоды 90д, feedback/applications 180д; строки, связанные с active/validated/lineage, не прунятся); прунинг — шагом review-job. Восстановимость: delta/статусы; suspend без очистки памяти чата; экспорт проверенных пар позднее (вне скоупа). **OFF (K1) — таблицы инертны.** (spec §8)

### D9. Витрина, права, настройки (§25.7; CA-16-8)

«Статус» — компактная лента «Опыт» в существующем мониторинге интеллекта (врезка в `GET /api/status`; прецедент `status_service.random_source_snapshot:410–474`; JS-блок — прецедент `web/index.html:5170`): реальные записи, при unknown — без выдуманного улучшения (A57), не IQ-шкала, только чтение. «Память» (`#/ai/memory`) — таблица lessons (scope/тип/статус/условия/основания/версии/применения/исходы) + карточка (пример/чему научились/где применяется/ограничения); suspended виден и не применяется; права — отключить/исправить/разрешённый trace без чужого чата. API — расширение существующего memory-API (`web/api/memory_agi.py`): `GET /api/memory/lessons`, `POST /api/memory/lessons/action` (admin, идемпотентно, аудит); `web/api/routes.py` не меняется → `ROUTES_SHA256_F11` без изменений (`tests/test_round1025_f8_registry.py:74,132`). Настройки — группа `memory_experience` («Опыт и уроки») на существующей вкладке `memory_rag`: `memory.experience_learning_enabled` (true) + `memory.experience_review_cadence` (daily); без рестарта; enabled=true при релизе. Верхнеуровневых разделов нет; рендер аналитики — mca-17c. **OFF (K1) — `disabled/not_run`.** (spec §9)

### D10. Наблюдаемость — один реестр, один словарь

Placeholder `self_learning.run` v0 (`mca_process_registry.py:899`, owner mca-16) амendится до **v1**: stages capture/review/propose/validate/activate/select/apply/outcome/utility/suspend; `stages_to_events` на notable-события; `instrumentation=("review","propose","validate","activate","suspend")`; `enabled_gate="MCA_EXPERIENCE_LESSONS_ENABLED"`; `widget_id="Опыт и уроки"` (контракт mca-17c); `recovery_ops=("review_resume","outcome_reconcile")`; OFF → `disabled/not_run`. События — notable-only через единственный `emit_mca_event` (`mca_events.py:520–548`) с именами §25.7: experience_recorded/lesson_proposed/validation_passed|failed/activated/retrieved/applied/feedback_linked/utility_updated/suspended/superseded; версии/причины/trace обязательны; `retrieved`/`applied` — ≤1 на ход. **`REASON_CODES` — ровно +10** (единый словарь; `validation_failed` переиспользуется); второй канал/словарь запрещён. Сквозной trace A49 не рвётся (episode↔trace, lesson↔episode, application↔trace, job↔causation). **OFF (K1) — событий нет.** (spec §10)

### D11. Kill-switches и env-only лимиты

K1 `MCA_EXPERIENCE_LESSONS_ENABLED` (master; OFF = бит-в-бит 2.58.58), K2 `MCA_EXPERIENCE_FEEDBACK_ENABLED` (OFF = feedback-контур закрыт), K3 `MCA_EXPERIENCE_REVIEW_ENABLED` (OFF = review-job не запускается), K4 `MCA_EXPERIENCE_CONTEXT_ENABLED` (OFF = уроки не отбираются/не применяются). Env-only `ClassVar` + `mca_gates.KILL_SWITCHES` + резолверы (per-call, не бросают). Переиспользуются: mca-13/mca-17a/mca-07/mca-06/mca-10a/mca-11-гейты — не дублируются. Env-only лимиты: review batch 100, retention 90/180/180, block ≤5/≤600 токенов, ≥3 независимых эпизода, relevance min score, bootstrap ON (bounded, candidates-only). **OFF (K1–K4).** (spec §11)

### D12. Санкции T-4990 — поимённо

Δ DDL = **v28** (4 таблицы + 9 индексов, mca-14, backup-guard, PG no-op); Δ каталога ≠ 0: REGISTRY 502→**504** (+2), GROUPS 107→**108** (+1 `memory_experience`), `_TAB_BY_GROUP` 105→**106**, TAB_RULES 21 in-place (`memory_rag`), delta 91→**93**, Settings 439→**441**, secret без изменений, screen-map/widget-map +2 (точные счётчики — по F8-переизданию; расхождение — errata при reconcile, прецедент mca-10a F-3); **F8 ADR-1026-2 обязателен**; routes.py не меняется (`ROUTES_SHA256_F11` без изменений); канон инструментов **12** без изменений; reason_code **ровно +10**; Risk **R3** + `threat-failure-analysis.md` (THR-1…THR-14); deploy **CA-11** bump 2.58.58→**2.58.59**, rollback soft (K1–K4=false) / cold (v28 инертна); merge **§119+**; live — **PENDING OWNER** (реальный чат, без имитации; no-false-acceptance `:15167`). Полная формулировка — spec §12. (spec §12)

---

## AMEND/REUSE-регистр

| # | Отношение | Решение |
|---|---|---|
| **AM-1** | **AMEND ADR-1027-7 (mca-07)** | Единственный EvidenceBundle получает аддитивное поле `lessons` (отдельный тип; bounded-блок); второй bundle запрещён; M-MCA07-2-поля (`ambiguities/unknown/contradictions`) не трогаются (владелец mca-09). |
| **AM-2** | **AMEND ADR-1027-8 (mca-17a)** | Placeholder-процесс `self_learning.run` v0→v1 + стадийные события; контракт реестра/trace не меняется; widget-ID — контракт mca-17c. |
| **AM-3** | **AMEND ADR-1027-2 (mca-13)** | `REASON_CODES` +10 аддитивно в единственный словарь; события — notable-only через единственный `emit_mca_event`. |
| **AM-4** | **AMEND ADR-1027-6 (mca-04a)** | Grounding эпизодов/уроков — существующие SourceRef/EvidenceLink (`entity_type=episode|lesson`); второй контракт связей запрещён. |
| **AM-5** | **REUSE/CONFIRM ADR-1028-9 (mca-06)** | Review — отдельный job; deep sleep не смешивает lessons с парадигмами; принцип независимости по первичным событиям переиспользуется; пайплайн mca-06 не меняется. |
| **AM-6** | **REUSE/CONFIRM ADR-1028-14 (mca-10a)** | Опыт exploration — из журнала `mca_random_draws` как наблюдение; второго RandomSource/процента нет; «выбор ≠ вердикт»; квота/расходы не reward. |
| **AM-7** | **AMEND ADR-1026-2 (F8)** | Δ каталога ≠ 0 — переиздание TSV/meta/screen-map/widget-map/config_diff + фикстуры/ассерты (прецедент `tools/_mca10a_reissue_f8.py`). |
| **AM-8** | **AMEND ADR-1027-1 (mca-14)** | Клейм версии **v28** для 4 аддитивных таблиц; идемпотентность/backup-guard/PG no-op — по действующему контракту. |
| **AM-9** | **AMEND ADR-1027-3 (mca-01)** | Новый kind `experience.review` в существующей durable-очереди; один write-механизм; второй планировщик/очередь запрещены. |
| **AM-10** | **CONFIRM ADR-1028-12 (mca-15)** | MetricResult — основа outcome-проверки; числа из ненадёжных агрегатов ≠ reward (handoff AM-10). |
| **AM-11** | **CONFIRM ADR-1028-11 (mca-08)** | Граница: style request — прямая директива; lesson — процедурная рекомендация; explicit-only-контур mca-08 не меняется. |
| **AM-12** | **CONFIRM ADR-1028-6 (mca-22)** | Собственные ответы (`mca_bot_outputs`) — не независимое подтверждение; `contradicts`-связи не дублируются. |
| **AM-13** | **CONFIRM ADR-1026-20 (decision-making)** | Уроки не участвуют в action-schema/Decision; второго координатора нет. |

**Supersede-регистр:** пуст — существующие решения не заменяются/не отменяются.

---

## Последствия

- Появляется единственный контур опыта: эпизоды/feedback/уроки/применения с проверяемой активацией, честной полезностью и bounded-блоком в единственном bundle; обучение без изменения весов модели и без новых зависимостей.
- Владелец получает витрину «Опыт» (Статус), таблицу/карточку/права (Память) и настройки learning enabled/review cadence; при unknown outcome улучшение не выдумывается; suspended не применяется.
- Деплой: пер-фичевый bump 2.58.58→2.58.59, миграция v27→v28 с backup-guard; откат — soft-гейты или cold revert (аддитивная схема инертна).
- Риск R3 (анти-самоподтверждение/injection/изоляция чатов/совместимость/retention) — митигации в `threat-failure-analysis.md`; live-часть — за владельцем.

**История ревизий:** 05.10.2026 — Proposed (Step 2 @Architect, design-freeze, T-4989/T-4990; номер свободен, merge-цель §119+); Accepted — по merge §119+ и прод-валидации 2.58.59.
