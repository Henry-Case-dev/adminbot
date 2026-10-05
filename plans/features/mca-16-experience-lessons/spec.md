# MCA-16 `mca-16-experience-lessons` — spec (design-freeze, Step 2 @Architect, 05.10.2026)

**Фича:** `mca-16-experience-lessons` (Wave 3 эпика `memory-context-autonomy`; параллельный сиблинг `mca-10a` — закрыт 2.58.58). ТЗ `plans/current_task.md:1173–1282` §25.1–§25.7 (файл НЕ изменялся, R17); приёмки A43–A47 `:924–928`, A57 `:938`, A49 `:930` (сквозная, владелец mca-17a); §20.2 `:1018` («Банк опыта … ON; candidate не активируется без проверки»); GEN-R27 `:1092`; матрица §27.1 `:1544`; no-false-acceptance `:15167`; план `plans/docs/mca-round1027-plan.md:139–145`, строка `:208`, Wave 3 `:238–240`, открытый вопрос №11 `:412`. Артефакты Step 1 — `requirements-map.md` (MCA16-R1…R7, CA-16-1…9), `tasks.md` (T-4988…T-5016).

**База (перепроверено на дереве 05.10.2026; HEAD на момент проверки `e6d1616`, актуальный `92252d1` — docs-only архив mca-10a, факты не затронуты):** прод **2.58.58**, SQLite **v27** (`_SCHEMA_VERSION_RANDOM_SOURCE = 27`, `services/database.py:999`; `MigrationStep(27)` `:2025–2027` — v28 свободна), каталог **502/107/105/21** (`tools/gen_param_registry_round1025.py --check` → `CHECK OK: реестр 502`, запущено 05.10.2026; meta `plans/docs/param-registry-round1025.meta.md` APP_VERSION 2.58.58, delta 91, Settings 439), канон инструментов **12**, `REASON_CODES` **221** (`services/mca_events.py:60–252`), `KILL_SWITCHES` **64** (`services/mca_gates.py:29–344`). **ADR-1028-15 свободен** (grep `plans/**`: `ADR-1028-1[5-9]`/`ADR-1028-2x` — 0 хитов; последний занятый — ADR-1028-14 mca-10a); merge-цель — **§119+** (последний занятый §118 mca-10a). mca-10a код опыта не касался (grep `experience|lesson` по `services/**`: только placeholder-реестра `mca_process_registry.py:899` и комментарий `:121`).

**Границы (не создавать вторые):** банк опыта-дубликат, очередь, write-механизм, словарь событий, bundle, RandomSource, координатор, LLM-провайдер, второй процент экспериментов. Вне скоупа: mca-09 (Intent/Decision/action-schema), mca-10b (применения 14.5–14.11), mca-10c (stub 14.12), mca-12 (истории), mca-17c (полная визуализация/фуннель §27.8), mca-18 (черты/парадигмы), mca-19/20; полный MemRL/MemQ/TD(λ), графовый RL, fine-tuning/LoRA/DPO/online RL (`:1194–1198`).

---

## 1. D1 — ExperienceService: один контур опыта, один сервис

**Модули (два файла — один механизм; прецедент mca-05 `mca_episodes.py` + `mca_episode_jobs.py`):**
- `services/mca_experience.py` — единственный контур: `ExperienceStore` (доступ к v28-таблицам), `ExperienceService` (запись эпизодов/feedback, сигналы, идемпотентность), `LessonService` (жизненный цикл, проверки/активация, отбор, полезность, compatibility), `ExperiencePolicy` (пороги/версии). Фасад `get_service()`.
- `services/mca_experience_jobs.py` — durable-job `experience.review` (пакетный review; §7).

Все записи — только через `write_transaction` (mca-01, §95); чтение — SQL. Второго store/сервиса/координатора нет; retrieval-примитивы — существующие mca-07 (§6); события — `emit_mca_event` (§10); provenance — mca-04a (§2).

**Версии (контракт, «versions per component table»):** `EXPERIENCE_POLICY_VERSION = "mca16-policy-1"`, `PROPOSAL_VERSION = "mca16-proposal-1"`, `VALIDATOR_VERSION = "mca16-validator-1"`, `SELECTION_POLICY_VERSION = "mca16-select-1"`; в журнал/события/урок пишутся policy/proposal/validator версии, `config_version` запуска и compatibility-fingerprint (§5). Версии — часть контракта, меняются только санкцией @Architect.

**OFF (K1):** модуль инертен — ни записей, ни чтений, ни block, ни job; ровно 2.58.58.

---

## 2. D2 — ExperienceEpisode и Feedback: поля, идемпотентность, R17

**ExperienceEpisode (§25.2 `:1204`; таблица `mca_experience_episodes`, §8).** Поля: `episode_id` (uuid), `idempotency_key` (UNIQUE), `created_at/updated_at`, `scope` (`global|chat|user_in_chat|task`), `chat_id`, `user_id` (для `user_in_chat`), `task_type`, `operation_ref` (`operation_id`/`trace_id`), `source_ref_json` (ссылки mca-04a, не копии), `decision_json` (наблюдаемые действия/результаты — **без hidden chain-of-thought**), `tool_ids_json`, `metric_ids_json`, `lesson_ids_json` (применённые), `output_ref` (mca-22 `output_id`/delivery), `outcome_kind` (`success|failure|unknown`), `outcome_source` (`technical|explicit|social|llm_hypothesis`), `outcome_reliability` (`verified|weak|hypothesis`), `feedback_ids_json`, `model_version`, `tool_schema_hash`, `config_version`.

**Захват (дёшево, без LLM на сообщение):** эпизод создаётся только для трасс с типизированным исходом — tool chain (mca-11 ToolResult), direct-ответ с явной обратной связью, stats-ответ (mca-15 MetricResult), коррекция; не для каждого сообщения. Запись — одна короткая транзакция.

**Идемпотентность (A47-часть):** `idempotency_key = sha1-16(source_kind|trace/operation|feedback_id)`; повторный ingest того же trace/feedback после рестарта → no-op (SELECT/INSERT-guard в одной транзакции); повторные эпизоды исключены.

**Feedback (§25.3; таблица `mca_experience_feedback`).** Поля: `feedback_id`, `dedup_key` (UNIQUE = sha1-16(source_kind|chat_id|ref_type|ref_id)), `source_kind` (`owner_correction|participant_correction|social_reaction|llm_hypothesis|technical`), `reliability`, `authority` (`owner|participant|system`), `status` (`active|cancelled|corrected`), `supersedes_id`, `chat_id`, `trace_id`/`operation_id`, `episode_id`, `signal_json` (только типизированные refs/коды — не сырой текст), `ts`. Дедуп повторного сигнала → no-op; запоздалая обратная связь линкуется по reply/trace; отмена/исправление — новая строка со `status` и `supersedes_id` (история сохраняется).

**R17:** в эпизодах/feedback/журналах/событиях — только ID/коды/числа/enum/ссылки; сырой текст сообщений, секреты, hidden CoT не сохраняются. Рекомендации уроков — серверно-канонические формулировки (§3), не копии реплик.

**OFF (K1):** записей нет. **OFF (K2):** feedback-контур (source_kind ≠ technical) не пишется/не читается; технические эпизоды продолжают фиксироваться.

---

## 3. D3 — Lesson: поля, scope, версии/lineage, изоляция, границы

**Lesson (§25.2 `:1206`; таблица `mca_lessons`; версионирование содержания — append-only, статус — in-place на текущей версии, §5).** Поля: `lesson_id`, `version` (PK `(lesson_id, version)`), `type` (`tool_usage|retrieval|context|social_preference|failure_pattern`), `scope` (`global|chat|user_in_chat|task`), `scope_chat_id`/`scope_user_id`, `applicability` (условия применимости), `recommendation` (серверно-канонический текст), `exceptions`, `status` (`candidate|validated|active|suspended|superseded`), `source_ref_id` (собственный SourceRef mca-04a, `entity_type="lesson"`), `supersedes_lesson_id/version`, `merged_from_json`, `compat_tool_schema_hash`, `compat_model_fingerprint`, `compat_config_version`, `recheck_required`, `historical`, `unverified`, `last_validated_at`, счётчики `counters_success/failure/unknown`, `applications_count`, `policy_version`/`proposal_version`/`validator_version`, `created_at/updated_at`.

**Версии/lineage (delta, не переписывание):** новый урок — insert v1; содержательное изменение (recommendation/applicability/exceptions/scope) — новая версия n+1 + `supersedes` → старая `superseded`; смена статуса (validate/activate/suspend/reactivate) — in-place на текущей версии (аудит событием); merge дублей — новая версия с `merged_from_json`, источники `superseded`. Grounding — `mca_evidence_links` (subject=lesson-ref, source=episode-ref, `link_type` supporting/contradicting/derived_from) — второй контракт связей не создаётся (mca-04a).

**Scope и изоляция (§25.2 `:1210–1215`):**
- `global` — только обезличенный технический урок; без имён/цитат/фактов/ID исходного чата (проверка анонимизации при валидации/активации);
- `chat` — нормы/повторяющиеся ситуации чата; `user_in_chat` — явная предпочтительная форма участнику этого чата; `task/context` — узкий временный способ.
- Опыт чата по умолчанию остаётся в чате; правила чужого чата недоступны retrieval без разрешённого scope (фильтр отбора §6); закрытые trace — только владельцу/уполномоченным ролям.

**Ограниченный контракт:** урок — данные; не меняет system prompt/секреты/инструменты/права/бюджет; не заменяет code-level защиту; не содержит инструкций-императивов для модели (блок данных, §6).

**Границы (CA-16-9, CA-16-8):** style request (mca-08 `mca_style_scope.py:1–32`, explicit-only, participant>topic>chat) — **прямая директива**; lesson — **процедурная рекомендация** (применяется по релевантности/полезности, не директива); trait/paradigm (mca-18/mca-06) — черты/убеждения; `quality_regression` `:1558` — сигнал цикла опыта, не «менее полезные ответы».

**OFF (K1):** уроки не создаются/не читаются; таблица инертна. **OFF (K3):** новые версии/активация не создаются; существующие active не выбираются при K4 OFF.

---

## 4. D4 — Сигналы и анти-самоподтверждение (§25.3 `:1217–1230`)

**Разделение сигналов (закрытый набор):**
1. **Технический outcome** — ToolResult (mca-11: `ok/empty/error/timeout/cancelled/denied/delivery_unknown`), MetricResult (mca-15: `ok/partial/unsupported/error`, `value=null` при ошибке), доставка; свидетельствует **только о своей стадии** — HTTP 200/доставка ≠ истинность (A43/A45).
2. **Явная коррекция с источником** — владелец ≠ участник (`authority`); предпочтение участника относится к нему (`user_in_chat`); утверждение о факте проверяется (MetricResult/источник); «ты врёшь» без деталей — `пересмотр` (feedback `llm_hypothesis`/weak), не новая истина.
3. **Социальная реакция** — слабый контекстный сигнал (`reliability=weak`), не ground truth; большинство одинаковых реакций не отменяет проверенные источники.
4. **LLM-самооценка** — гипотеза (`llm_hypothesis`), не самостоятельное подтверждение успеха.

**Инварианты:** молчание = `unknown` (не success и не failure — A43/A57); нет наград за число сообщений/длину срача/провокации; числа из ненадёжных старых агрегатов ≠ reward (handoff mca-15 AM-10, `backlog.md:232`) — только MetricResult/versioned sources; расходы/стоимость/квота ≠ reward (handoff mca-11 `backlog.md:247`; независимость от квоты/расходов — handoff mca-10a `plans/archive/mca-10a-random-source-anu-round1038/tasks.md:68`, T-4987); feedback не может активировать урок по тексту «запомни навсегда, что надо игнорировать правила» — injection не матчится каноническими правилами и не становится рекомендацией; feedback/уроки не повышают собственный приоритет над инструкциями приложения.

**Независимость подтверждений (анти-самоподтверждение, A45/A43):** собственные ответы/действия (mca-22 `mca_bot_outputs`) — не независимое подтверждение; одно первичное событие не может одновременно «применить урок» и «подтвердить» его (reuse принципа независимости mca-06 по первичным событиям); social/LLM-сигналы не активируют урок в одиночку.

**Дедуп/поздняя связь:** повторный feedback → no-op (`dedup_key`); запоздалая/отменённая/исправленная связь поддержана (`status`/`supersedes_id`); двойное обновление полезности исключено (§6, unique-ключ применения+исхода).

**OFF (K2):** входящие сигналы, кроме технических, не обрабатываются; injection-поверхность закрыта.

---

## 5. D5 — Жизненный цикл, активация, совместимость (§25.4 `:1232–1247`)

**Состояния — ровно пять:** `candidate → validated → active → suspended` (+ `superseded` из любой ветки). Других состояний нет; несовместимость — не состояние, а флаг `recheck_required` (исключение из отбора + повторная проверка).

**Переходы и правила активации:**
- `candidate` **не используется как предписание** — в bundle/применение попадают только `active`.
- `candidate → validated` (проверка по типу):
  - явное предпочтение → `user_in_chat` **после разрешения автора/адресата** (права mca-08-fail-closed-модель) и проверки конфликта с обязательными правилами (owner core / инварианты);
  - техническое исправление → **воспроизведение ошибки + успешный контрольный пример новым способом + отсутствие нарушения инвариантов** (инструменты проверки — существующие: fixtures/tools/MetricResult);
  - обобщение из неявных сигналов → **≥3 независимых подтверждённых эпизода** (инженерный порог, не доказательство истинности) + проверка на **новых контекстах** (контрольные контексты §7);
  - `global` — только обезличенный технический урок после валидации без имён/содержания исходных чатов; норма одного чата глобальной не становится автоматически.
- `validated → active`: compatibility текущая + отсутствие противоречий + для `global` — пройденная анонимизация; **включено сразу, без Human Gate** (валидация — обычная операция; §20.2 `:1018`).
- `active → suspended`: сильное противоречие инварианту/подтверждённая ошибка источника/действие владельца (`owner_disabled`) — **suspend, не спор с пользователем**; suspended исключён из bundle и UI-применения (A47); реактивация — через `validated` после повторной проверки.
- `* → superseded`: новая версия/merge; старые версии сохраняются для lineage и не выбираются.

**Совместимость/старение (A46):** `compat_*` фиксируются при активации; смена tool schema/model fingerprint/config → `recheck_required=1` → урок **не применяется** до повторной проверки (успешный контрольный пример); провал проверки → `suspended` с причиной. Изменение источника (mca-04a `source_revision_changed`) распространяет статус на связанные уроки (recheck/suspend) — «изменение источника распространяет статус».

**Исторический bootstrap (§25.6 `:1267`, T-5001):** только `candidate` с `historical=1, unverified=1`; проверяемые явные предпочтения — после разрешения идентичности (mca-03/22); 2 млн сообщений без полного trace **не восстанавливают** решение/инструмент/успех (эпизоды не выдумываются, outcome=unknown); массового backfill-успеха нет; активация — только после свежей проверки на новых контекстах. Bootstrap-часть review-job — bounded, без LLM на сообщение; автоматический архивный проход — env-only `MCA_EXPERIENCE_BOOTSTRAP_ENABLED` (default ON, безопасная семантика: только candidates).

**OFF (K1):** переходов нет. **OFF (K3):** propose/validate/activate/recheck не выполняются (статусы заморожены); отбор — только по уже active при K4 ON.

---

## 6. D6 — Отбор, полезность, EvidenceBundle (§25.5 `:1249–1259`)

**Отбор (строгий порядок):** разрешённый scope и `active` → compatibility (не stale, `recheck_required=0`) → **релевантность** текущей задаче → полезность. Реализация: кандидаты SQL-фильтром (scope: global + текущий chat + текущий user + task), затем semantic gate **существующими примитивами mca-07** (FTS/embedding cache; порог `MCA_LESSON_RELEVANCE_MIN_SCORE`) — урок без семантической связи **не проходит только из-за высокого рейтинга**; второй retrieval-движок/индекс запрещён; корпус уроков bounded (лимиты §11).

**Полезность (§25.5):** измерения `correctness|tool_success|contextual_fit|preference_fit`; исходы `success|failure|unknown`; сглаживание Beta(1,1) на измерение; **ESS** (success+failure с учётом сглаживания); `unknown` **не обновляет** ни success, ни failure; новые уроки — нейтральная оценка (0.5); обновляются **только реально применённые** уроки (не retrieval-кандидаты и не предки); «применение ≠ причинное доказательство» — отмечается наблюдаемый исход. Журнал вклада — `mca_lesson_applications` (содержимое применения не переписывается; единственное допустимое обновление — однократная идемпотентная линковка исхода по dedup-ключу `(lesson_id, version, application_ref, outcome_ref)`) — основа будущей более сложной оценки (графовый RL не включается).

**EvidenceBundle (M-MCA07-2; `services/mca_retrieval_context.py:182`):** lessons — **отдельный тип** в **единственном** bundle: аддитивное поле `lessons: tuple[LessonRef, ...] = ()` (frozen dataclass `LessonRef`: lesson_id/version/type/scope/applicability/recommendation/exceptions), `BUNDLE_SCHEMA_VERSION` не меняется (аддитивно; пустое поле = байт-паритет); поля `ambiguities/unknown/contradictions` не трогаются (владелец mca-09). Bounded адаптивный блок: `MCA_LESSON_BLOCK_MAX_ITEMS`=5, `MCA_LESSON_BLOCK_MAX_TOKENS`=600; **не вытесняет вопрос/источники** (аллокация только из остатка; не влезло — не включается, честно виден `ExcludedItem` с `budget_exceeded`); блок — данные («проверенные уроки»), не инструкции; suspended/disabled/stale не включаются (A47).

**Интеграция (один вызов, без второго координатора):** сборка — в существующем `_build_evidence_bundle` (`services/direct_chat_service.py:1944–1948`; scoped-срез `:421–441` — образец врезки блока); direct/System2/final и автономный decision-путь используют **тот же** bundle (`:2086–2088`); уроки **не участвуют** в action-schema/Decision (mca-09) и не меняют координатор. Пометка применения: при генерации с непустым блоком пишутся `mca_lesson_applications` (≤5, одна транзакция; outcome=unknown) + событие `applied`; исход линкуется review-job (идемпотентно, один раз).

**OFF (K4):** lessons не отбираются/не включаются/не применяются; bundle/context_version байт-идентичны 2.58.58; журнал применения не пишется.

---

## 7. D7 — Пакетный review, сон, случайность, holdout (§25.6–§25.7)

**Job (один тип в существующей очереди):** `kind="experience.review"`, `owner="mca16"`, `coalesce_key="experience.review:global"` (singleflight; прецедент `mca_episode_jobs.py:40–51,68–87`, `TaskJobStore.enqueue` `services/task_supervisor.py:407–458`); durable checkpoint/counters через `task_jobs` (mca-01). Триггеры: каденция `memory.experience_review_cadence` (hourly/daily/weekly; default daily) из существующего расписания обслуживания + немедленный enqueue при содержательной коррекции. Шаги: capture-cursor → propose → validate → activate/suspend → outcome-link → utility-update → recheck → prune (retention). **На каждое сообщение отдельной LLM-рефлексии нет** (R6a): предложения — детерминированные канонические правила; существующий LLM-клиент допустим только как формулятор гипотез внутри пакета (bounded ≤1 вызов на запуск), его вывод **никогда** не активация (A45). Второй очереди/планировщика нет.

**Сон/парадигмы:** review — **отдельный тип job**; deep sleep не смешивает lessons с парадигмами/фактами/историями (отдельные сущности/таблицы; пайплайн mca-06 не меняется; R6b). «Факт/убеждение/история/experience/lesson» — раздельные сущности (CA-16-1).

**Случайность (граница mca-10a, CA-16-3):** опыт от exploration читается из существующего журнала `mca_random_draws` (purpose/selected/candidates/fallback; `database.py:1017+`) как **наблюдение**; случайность разнообразит допустимые действия, но **не рандомизирует истинность/успех/оценку урока**; второй процент/второй RandomSource запрещены; массовых социальных экспериментов ради reward нет (R6d). Новая версия поведения сравнивается с **контрольными контекстами** (без блока уроков) — детерминированно, не экспериментом над людьми.

**Temporal holdout (T-5010, §25.7 `:1281`):** уроки извлекаются только из прошлого; проверочные эпизоды — позже и не были источником урока; сравнение OFF/ON на одной версии модели и сопоставимых запросах; отчёт: повтор ошибок, корректность, уместность, дополнительная стоимость; replay без реального outcome проверяет инварианты, но не доказывает реакцию человека; отсутствие измеренного улучшения — честно, не подменяется числом созданных lessons (GEN-R27).

**OFF (K3):** job не запускается; **OFF (K1):** job/журналы инертны.

---

## 8. D8 — Хранение: additive v28, retention, восстановимость

**Δ DDL = v28** (`MigrationStep(28)`, реестр mca-14; v28 свободна — прод v27): **4 аддитивные таблицы + 9 индексов**, точные колонки — §2/§3/§6:
- `mca_experience_episodes` + 3 idx (UNIQUE `idempotency_key`; `(chat_id, created_at)`; `(scope, task_type)`);
- `mca_experience_feedback` + 2 idx (UNIQUE `dedup_key`; `(chat_id, created_at)`);
- `mca_lessons` + 2 idx (PK `(lesson_id, version)`; `(status, scope, scope_chat_id)`; `(type, status)`);
- `mca_lesson_applications` + 2 idx (UNIQUE `dedup_key`; `(lesson_id, lesson_version, applied_at)`).

Аддитивно, идемпотентно (повтор — no-op), **PG — no-op**; backup-guard fail-closed до DDL + read-back (mca-14); старый код v28 не читает (cold-совместимо). Backfill нет (новые таблицы пустые — честный unknown).

**Retention (env-only, bounded; GEN-R8):** эпизоды 90 дней (unreferenced), feedback/applications 180 дней; **никогда не прунятся строки, на которые ссылаются active/validated уроки или lineage**; прунинг — шагом review-job; жёстких квот на число уроков нет (bounded через retention и пороги).

**Восстановимость:** изменения опытной памяти — delta-версии/статусы; ошибочный урок отключается (suspend) без очистки памяти чата; экспорт проверенных пар для будущего обучения возможен позднее (вне скоупа).

**OFF (K1):** таблицы инертны; миграция v28 безопасна (аддитивна).

---

## 9. D9 — Витрина и права (§25.7 `:1271–1279`; CA-16-8)

**«Статус» — лента «Опыт»** в существующем мониторинге интеллекта (врезка в `GET /api/status`, `services/status_service.py` — прецедент `random_source_snapshot:410–474`, payload `:703`; JS — существующий грид Статуса, прецедент блока «Источник случайности» `web/index.html:5170`): «исправлен способ подсчёта», «учтено предпочтение», «урок применён», «урок приостановлен» — из реальных записей; **при unknown outcome — без выдуманного улучшения** (A57: видны основания и недостаток измерений); не IQ-шкала; только чтение (без LLM/внешних вызовов). K1/K4 OFF → честный `disabled/not_run`.

**«Память» — таблица lessons** в существующей «Памяти» (`#/ai/memory`; не новый раздел): scope/тип/статус/условия/основания/версии/применения/проверенные исходы; **карточка**: конкретный пример, чему научились, где применяется, ограничения; suspended виден и не применяется. **Права:** отключить/исправить урок, открыть разрешённый trace без раскрытия чужого чата (RBAC; trace — существующие контуры mca-22 `memory_agi.py:920`/mca-17a).

**API (расширение существующего memory-API, не второй API):** `GET /api/memory/lessons` (таблица/карточка, RBAC как «Память») и `POST /api/memory/lessons/action` (suspend/activate/correct; admin; идемпотентно; аудит событием; correct = новая версия/статус) — в `web/api/memory_agi.py` (`memory_router`, монтирование `web/app.py:187–188`; прецедент mca-22 `memory_agi.py:927`). **`web/api/routes.py` не меняется → `ROUTES_SHA256_F11` без изменений** (пин `tests/test_round1025_f8_registry.py:74,132`).

**Настройки:** группа `memory_experience` («Опыт и уроки») на существующей вкладке `memory_rag` («Память»): `memory.experience_learning_enabled` (bool, default **true**) и `memory.experience_review_cadence` (select hourly/daily/weekly, default **daily**); применение без рестарта (ConfigCache); выполняющиеся решения — со своей `config_version`; при релизе enabled=true (§20.2). Δ каталога — §12.

**OFF (K1):** лента/таблица отдают `disabled/not_run`; действия недоступны; настройки инертны.

---

## 10. D10 — Наблюдаемость (mca-17a/mca-13, без второго канала; GEN-R17)

**Процесс:** placeholder `self_learning.run` v0 (`mca_process_registry.py:899`, owner mca-16, «не реализовано») **амendится до v1** (не второй процесс): purpose «Опыт и уроки: эпизод → review → кандидат → проверка → активация → применение → исход → полезность»; stages `("capture","review","propose","validate","activate","select","apply","outcome","utility","suspend")`; `stages_to_events` на notable-события; `instrumentation=("review","propose","validate","activate","suspend")` (notable-only; per-turn select/apply — журнал + bounded события); `state_source=("mca_experience_episodes","mca_lessons","mca_lesson_applications","task_jobs")`; `enabled_gate="MCA_EXPERIENCE_LESSONS_ENABLED"`; `widget_id="Опыт и уроки"` (контракт mca-17c; рендер не здесь); `recovery_ops=("review_resume","outcome_reconcile")`; OFF → честный `disabled/not_run`.

**События — notable-only через единственный `emit_mca_event` (`mca_events.py:520–548`)**, имена §25.7 `:1277`: `experience_recorded` (per-episode, INFO), `lesson_proposed`, `validation_passed`/`validation_failed`, `activated`, `retrieved` (≤1 на ход при непустом блоке), `applied` (≤1 на ход), `feedback_linked`, `utility_updated` (агрегированно на review-запуск), `suspended`, `superseded`; версии/причины/связи с trace обязательны. **`REASON_CODES` — ровно +10** (единый словарь `mca_events.py:60–252`): `experience_recorded`, `lesson_proposed`, `validation_passed`, `activated`, `retrieved`, `applied`, `feedback_linked`, `utility_updated`, `suspended`, `superseded`; `validation_failed` переиспользуется; второй словарь запрещён. Сквозной trace A49 (`:930`) не рвётся: эпизод↔trace/operation, lesson↔episode (evidence links), application↔trace, job↔causation — на границе очереди связи сохраняются.

**OFF (K1):** событий/стадий нет, registry `not_run`; K4 OFF — `retrieved/applied` не эмитятся.

---

## 11. D11 — Kill-switches и env-only лимиты

Kill-switches — env-only `ClassVar[bool]` (`config/settings.py`; прецедент `:1427/:2268`), реестр `mca_gates.KILL_SWITCHES` (`:29–344`) + резолверы (per-call, не бросают):

| # | Имя | Default | OFF-паритет |
|---|---|---|---|
| K1 | `MCA_EXPERIENCE_LESSONS_ENABLED` (master) | ON | бит-в-бит 2.58.58: нет записей/чтений/блока/job/событий; v28 инертна; UI `disabled/not_run` |
| K2 | `MCA_EXPERIENCE_FEEDBACK_ENABLED` | ON | нет обработки feedback (кроме технических исходов); injection-поверхность закрыта; utility не обновляется по feedback |
| K3 | `MCA_EXPERIENCE_REVIEW_ENABLED` | ON | review-job не запускается: нет propose/validate/activate/recheck; статусы заморожены |
| K4 | `MCA_EXPERIENCE_CONTEXT_ENABLED` | ON | lessons не отбираются/не включаются/не применяются (bundle/context_version = 2.58.58); сбор опыта может продолжаться |

Переиспользуются и **не дублируются**: `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` (mca-13), `MCA_OBSERVABILITY_ENABLED` (mca-17a), `MCA_RETRIEVAL_CONTEXT_ENABLED`/`MCA_EVIDENCE_BUNDLE_ENABLED` (mca-07), `MCA_DREAM_*` (mca-06), `MCA_RANDOM_*` (mca-10a), `MCA_MONEY_LIMITS_ENABLED` (mca-11; K5 OFF не трогается).

Env-only лимиты (не каталог): `MCA_EXPERIENCE_REVIEW_BATCH_MAX`=100, `MCA_EXPERIENCE_EPISODE_RETENTION_DAYS`=90, `MCA_EXPERIENCE_FEEDBACK_RETENTION_DAYS`=180, `MCA_LESSON_APPLICATION_RETENTION_DAYS`=180, `MCA_LESSON_BLOCK_MAX_ITEMS`=5, `MCA_LESSON_BLOCK_MAX_TOKENS`=600, `MCA_LESSON_MIN_INDEPENDENT_EPISODES`=3, `MCA_LESSON_RELEVANCE_MIN_SCORE` (стартовый, инженерный), `MCA_EXPERIENCE_BOOTSTRAP_ENABLED`=ON (bounded, candidates-only). Пороги — инженерные стартовые (GEN-R27), не научный оптимум.

---

## 12. D12 — Санкции T-4990 (поимённо)

1. **Δ DDL = additive v28** (`MigrationStep(28)`, mca-14): 4 таблицы + 9 индексов (§8), backup-guard fail-closed, идемпотентно (повтор no-op), PG no-op, v28 свободна. Обоснование: durable-банк требует собственных сущностей; reuse `smart_messages`/`graph_facts` загрязнил бы human-only корпус (прецедент-обоснование mca-22 `database.py:806+`); файловый store/JSON-блобы отклонены (второй write-механизм, нет запросов/retention).
2. **Δ каталога ≠ 0:** REGISTRY 502→**504** (+2), GROUPS 107→**108** (+1 `memory_experience`), `_TAB_BY_GROUP` 105→**106**, TAB_RULES **21 in-place** (существующая вкладка `memory_rag`), delta 91→**93**, Settings 439→**441**, secret — **без изменений**, screen-map/widget-map +2 (точные счётчики фиксирует F8-переиздание; расхождение — errata при reconcile, прецедент mca-10a F-3); **F8 ADR-1026-2 обязателен** (переиздание TSV/meta/screen-map/widget-map/config_diff + фикстуры/ассерты; прецедент `tools/_mca10a_reissue_f8.py`; проверка `python tools/gen_param_registry_round1025.py --check`); **routes.py не меняется → `ROUTES_SHA256_F11` без изменений**.
3. **Канон инструментов 12** — без изменений; новых tools/handlers нет.
4. **reason_code: ровно +10** в единственный `REASON_CODES` (§10; `validation_failed` переиспользуется).
5. **Risk: R3** (подтверждение планового `mca-round1027-plan.md:208`) — `threat-failure-analysis.md` обязателен (THR-1…THR-14).
6. **Deploy: CA-11 per-feature bump** `APP_VERSION 2.58.58 → 2.58.59` (прецедент mca-06/08/15/11/10a), пер-фичевый; проверки: health/версия, backup-guard + миграция v27→v28 идемпотентно (повтор no-op), PG no-op, kill-switches default ON 0 env-оверрайдов, R17=0, F8 `--check` OK 504, focused-повтор; **rollback:** soft — K1–K4=false + рестарт (v28 аддитивна/инертна), cold — git revert feat-коммита (checkout 2.58.58; restore не требуется).
7. **Merge:** `plans/ARCHITECTURE.md` **§119+** + **ADR-1028-15** → Accepted (по merge). Клейм v28 фиксируется здесь и в ADR-1028-15 D8.
8. **Live (PENDING OWNER, no-false-acceptance `:15167`):** реальный чат без имитации — техническая коррекция → урок применяется на похожем запросе; preference участника → scope; лента/таблица/отключение урока (T-5015); непроверяемое — явно помечено с причиной.
9. **UI-контракт:** «Статус» лента + «Память» таблица/карточка/права + настройки; без нового верхнего раздела/маршрута; widget-ID «Опыт и уроки» — контракт mca-17c (рендер — не здесь).

---

## 13. REQ → приёмки → задачи

| REQ | Решения | Приёмки | Задачи |
|---|---|---|---|
| MCA16-R1 (рамка) | D1, §12 | A43–A47 `:924–928` | T-4989/T-4990 + сквозные |
| MCA16-R2 | D1, D2, D3 | A44 `:925`, A47 `:928` | T-4991–T-4993 |
| MCA16-R3 | D2, D4 | A43 `:924`, A45 `:926` | T-4996–T-4998 |
| MCA16-R4 | D3, D5, D7 | A45/A46 `:926–927` | T-4999–T-5002 |
| MCA16-R5 | D6 | A43/A47 | T-4993–T-4995 |
| MCA16-R6 | D7 | A45/A46 | T-5003–T-5004 |
| MCA16-R7 | D9, D10, §7 (holdout) | A57 `:938`, A47 | T-5005–T-5010 |
| GEN-R17/§27.1 | D10 | A48/A73 (частично), A49 `:930` | T-5008 |
| Санкции/ревью | §12 | §19 `:874–976` | T-5011–T-5013 |
| Deploy/live/reconcile | §12.6–12.8 | §20 `:986–1045`, `:15167` | T-5014–T-5016 |

## 14. OFF-паритет по решениям

D1→K1, D2→K1 (+K2 для feedback), D3→K1 (K3/K4 — этапы), D4→K2, D5→K3, D6→K4, D7→K3/K1, D8→K1 (таблицы инертны), D9→K1/K4 (`disabled/not_run`), D10→K1, D11→K1–K4. **K1 OFF = бит-в-бит 2.58.58** для всего пути; каждый под-гейт OFF — документированное подмножество (таблица §11); дефолты ON аддитивны и не меняют baseline без новых записей.

## 15. Статус

`DESIGN_FROZEN` — санкции §12 обязательны для T-4991+; `plans/current_task.md` не изменялся (R17); runtime/test-код на Step 2 не менялся; ADR-1028-15 — Proposed (merge §119+ по reconcile). Следующий шаг — @Builder T-4991+ без дополнительных решений; live-часть — PENDING OWNER.
