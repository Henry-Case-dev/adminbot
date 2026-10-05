# ADR-1028-17 — MCA-10b `mca-10b-random-applications`: единая интеграция применений случайности

**Дата:** 05.10.2026. **Статус:** **Accepted** (merge `plans/ARCHITECTURE.md` **§121**, 06.10.2026 + прод-валидация 2.58.61 VERIFIED: рестарты 13:23:08/13:31:08 UTC, `/healthz` 200 ×2, v29→v30 идемпотентно — guard fail-closed `pre_migration_20261005_132427.db` 1.319 GB read-back @v29, `(30, random_uses)` ×1, повтор no-op; PG no-op; `MCA_RANDOM_USES_ENABLED` ON 0 env-оверрайдов; R17=0; Proposed — Step 2 @Architect, design-freeze 05.10.2026, T-5048/T-5049).
**Фича:** `mca-10b-random-applications` (Wave 3 эпика `memory-context-autonomy`, хвост; критпуть `…→10a→10b→release`). ТЗ `plans/current_task.md:602–716` §14.5–§14.11; приёмки A18 `:899`, A29–A35 `:910–916`, A37 `:918`; §20.2 `:1019`; §27.1 `:1355`.
**Артефакты:** `plans/features/mca-10b-random-applications/` (spec.md, threat-failure-analysis.md, tasks.md, requirements-map.md).
**База:** прод 2.58.60; HEAD `897ce4f`; SQLite v29 (свободна v30); каталог 504/108/106/21; `REASON_CODES` 237; `KILL_SWITCHES` 72; последний ADR-1028-16 (merge §120 mca-09).

## D1. Контракт — тонкий модуль `services/mca_exploration.py`
`ExplorationRequest`/`ExplorationResult` (поля — ТЗ `:606`) + lifecycle-константы + фасад над `ExplorationPolicy.choose` (10a reuse; `PolicyChoice` `mca_random_source.py:949–965`). Новый агент/сервис/второй координатор/второй контракт 10a не создаются. Журнал переходов — `mca_events`; durable-состояние jobs — `task_jobs`; conversation-исходы — read-only `random_metadata` (v22 `mca_bot_outputs`). Отдельной таблицы Request/Result **нет** (контракт+журнал, не реляционная сущность).

## D2. Purposes — санкционированное расширение закрытого набора 10a
В `EXPLORATION_PROBABILITY_KEYS` (`mca_random_source.py:79–83`; резерв «расширение — санкция 10b», `:73`) добавляются ровно 5: `conversation_variant`, `memory_recall` → `memory.random_exploration_probability`; `archive_sample`, `belief_review`, `association_pair` → `memory.random_sleep_exploration_probability`. **Новых probability-настроек нет** (гейта два: разговор / после сна). `ui_replay` — НЕ purpose (read-only маркер витрины; `choose()` отвергает); `ui_visualization` — настройка `random.uses.*`, не purpose. `policy_version` потребителей — `mca10b-v1`. Разделение статистики — по purpose; draw раздельные по решениям (`:620`).

## D3. Один выбор в разговоре
Ровно одна probability-проверка на conversation operation; общий пул **целостных** кандидатов (memory + форма участия + grounds); один выбранный кандидат; внутренние повторы 5% и «перекрутки» запрещены; один дополнительный draw выбора истории среди одинаково допустимых (purpose `memory_recall`) — draw корректной выборки, не вторая проверка. Пустой пул → primary + `no_eligible_alternative` (без draw). LLM ради набора альтернатив не вызывается. Уместность/проверка перед отправкой — у потребителя (не подменяются).

## D4. Один выбор фонового направления, без рекурсии
Существующая точка `sleep_exploration_probability` (стык mca-06) → максимум 1 job `exploration.<type>` в `task_jobs`, тип — равномерный draw из доступных (недоступные — причина `exploration_type_unavailable`); уникальный ключ `(chat_id, package_run_id, type)` — рестарт не дублирует; завершение job не запускает новую лотерею; exploration-job никогда не создаёт exploration-job. Job — отдельный kind, который основной archive worker не выбирает: FIFO-приоритет основного прохода — by construction. Исходы → память/очередь кандидатов инициативы, не Telegram.

## D5. Lifecycle
`candidate→selected→checking→accepted/rejected/deferred/failed` + финальный `used_in_reply|stored_only|not_used`; `selected` ≠ истина/публикация. Переходы — события `mca_events` (R17-safe); состояние — `task_jobs` payload/status. Повторную выборку после неудачного варианта не крутить (primary или молчание + причина).

## D6. `memory_recall`
Кандидаты только через `retrieve()` (L-MCA07-5); релевантность → разнообразие; допуск привязан к версии ранжирования; `last_retrieved_at` ≠ `last_used_in_chat_at` (сон ≠ чат; чат — только после подтверждённой доставки); dedup по canonical event ID (перефраз = повтор); прямой запрос — обычный поиск (`direct_request` ineligible). `delivery_unknown` фиксируется отдельно и подавляет немедленный повторный выбор.

## D7. `archive_sample`
Существующий resumable worker; карта покрытия — v30 `mca_archive_coverage`; выбор: нижняя группа по доле verified → равномерный draw периода → непроверенный поддиапазон по стабильным ID (без занятых). Random OFFSET запрещён. Checkpoint/refs/версия экстрактора обычные; покрытие объединяется; основной cursor не двигается через непроверенное; «всё покрыто» — exploration только по причине пересмотра/новой версии экстрактора.

## D8. `belief_review`
Обязательная перепроверка изменённых источников — существующая очередь (без изменений). Random-выбор объекта — активные убеждения с oldest `last_reviewed_at`, минус ожидающие и ядро личности; **случайность выбирает объект, не вердикт**; ищутся подтверждения И опровержения; исходы kept/narrowed/split/disputed/replaced; отсутствие контрпримера не повышает уверенность; защита от колебаний — `material_refs_hash` в v30 `mca_belief_reviews`: те же материалы без новых обстоятельств → kept, версия не растёт, счётчик «улучшений» не увеличивается. Пересмотр — существующим write-путём mca-06 (коды `superseded` и др., без новых). Overrides уважаются; событие — в существующей ленте убеждений.

## D9. `association_pair` и размещение Association (CA-10B-4)
Конечный набор пар (cap ≤8; сторона A — актуальный контекст, B — retrieval-пул; разные canonical event ID; не декартов перебор); один draw пары; link-тип `analogy|motif|contrast|continuation|insufficient` + основание + SourceRef обеих сторон (LLM-классификация, не random). Association — **v30 доменная таблица `mca_associations`** (версии сторон, status candidate/accepted/rejected/stale): производная интерпретация, не досье, не усиливает убеждения, не склеивает истории (continuation — по правилам EpisodeService). Изменение стороны → stale; rejected = кэш по версиям; принятая — кандидат координатору; прямой отправки нет. Атрибуция упомянувших outputs — существующий v22 `mca_bot_outputs` без изменений.

## D10. `conversation_variant`
Intent ∈ `COMMUNICATIVE_INTENTS` (`mca_intents.py:68`) — семантика кандидата, не новая action-schema; кандидат = цель/длина/предмет/источники/ограничения стиля; непригодные формы в пул не входят; выбор в общей процедуре D3 (отдельного стилевого броска нет); verbalizer получает смысл, редактор сохраняет; повтор фразы ≠ запрет слова; в чат без меток; direct не теряет смысл.

## D11. Визуализация §14.11
Расширение существующего блока 10a (`status_service.random_source_snapshot:410`, read-only; UI_STATUS_GRID_V2); данные из exploration-журнала `mca_events`/Telemetry; event cursor/dedup/bounded history (20) существующим механизмом миниаппа; **Δ routes = 0**. Анимация воспроизводит записанное (повтор помечен); новые QRNG/LLM на открытии/кадре/повторе запрещены; «Пока нет событий»; actual_source как метка; пауза/reduced motion/mobile/scroll-focus/текстовая альтернатива; права/chat scope (R17). Отказ визуализации не влияет на координатор.

## D12. Наблюдаемость
Процесс `random.uses` v1 в `mca_process_registry` (прецеденты `random.source:596`, `intent.initiative:946`); стадии = lifecycle; widget-ID строки §27.1 `:1355` для mca-17c; OFF → честный `not_run`; trace `mca_pipeline_runs` — сквозной выбор→проверка→исход (`:622`).

## D13. Настройки и kill-switches
Каталог: 6 bool `memory.random_uses_*` (группа `memory_random` существующая; per-chat `chat_params`), default **true** (§20.2 `:1019`; §23: 0.05/defaults — не оптимум, но релиз по ТЗ); stub §14.12 не входит. Kill-switch env-only ровно один новый: **`MCA_RANDOM_USES_ENABLED`** (default ON); per-purpose env-дубликатов нет (каталог — user-facing permission; F8 п.2 `arch-frames.md:171`; прецедент mca-16 `param_catalog.py:2062–2063`). Эффективное разрешение = каталог AND master AND существующие K1/K4 для probability-веток. **OFF = бит-в-бит 2.58.60** для всей 10b-поверхности.

## D14. reason_code: ровно +10 (237→247) в единый `REASON_CODES`
`exploration_accepted, exploration_rejected, exploration_deferred, exploration_failed, exploration_used_in_reply, exploration_stored_only, exploration_not_used, exploration_type_unavailable, association_stale, belief_review_unchanged`. Переиспользуются: `no_eligible_alternative`, `disabled`, `delivery_unknown`, `random_fallback`, коды пересмотра mca-06. Второго словаря нет.

## D15. Δ DDL = additive **v30** (≠ 0)
Один `MigrationStep(30)` через реестр mca-14 + backup-guard fail-closed (прецедент 10a-полки `pre_migration_*.db`), PG no-op, книга `schema_migrations` дописывается: ALTER `mca_episodes` (+2 колонки, +1 индекс); CREATE `mca_associations` / `mca_archive_coverage` / `mca_belief_reviews` (+индексы). **Обоснование Δ≠0:** индексированные min/order-by выборки (покрытие/давность), точечные stale-lookups по side-ref+версии, durable `material_refs_hash` — на логе/одноразовых jobs это сканы и потеря состояния. v29/прод не затрагивается.

## D16. Δ каталога ≠ 0 — F8 (ADR-1026-2) обязателен
REGISTRY 504→510 (+6), GROUPS/_TAB_BY_GROUP/TAB_RULES без роста (21 in-place); Settings +6, screen-map +6; секретов новых нет. Полная процедура F8: repin → TSV/meta/ScreenMap/widget-map → recount → `f8_baseline.json` + ассерты (прецедент `tools/_extra_reissue_f8.py`, AM-4 ADR-1028-14). Производные счётчики — по выводу тула, не вручную (errata-урок 10a).

## D17. Deploy/rollback
CA-11 per-feature bump **2.58.60→2.58.61**; миграция идемпотентна (повторный рестарт — no-op). Rollback: **soft** — `MCA_RANDOM_USES_ENABLED=false` (+ `random.uses.*` при необходимости) → паритет 2.58.60, v30 инертна; **cold** — `git revert` feat-коммита; v29 мультивалидна (v30 строго аддитивна); restore из полки — только R18-авария. Live-приёмка — PENDING OWNER (no-false-acceptance `:15167+`).

## AMEND-реестр
| # | Что | Суть |
|---|---|---|
| AM-1 | **AMEND ADR-1028-14 (mca-10a)** | Зарезервированная санкция «расширение имён purposes — 10b» исполнена: `EXPLORATION_PROBABILITY_KEYS` +5 по D2; политика/источник/журнал 10a — без изменений (reuse, не fork); `POLICY_VERSION` 10a не тронут (потребители несут `mca10b-v1`). |
| AM-2 | **AMEND ADR-1026-2 (F8)** | Очередное переиздание каталога по D16 (процедура — как в AM-4 ADR-1028-14). |
| AM-3 | ADR-1028-16 (mca-09) — без amend | `DecisionCandidate`/`COMMUNICATIVE_INTENTS`/`random_metadata` используются read-only; второй action-schema/процента нет; изменений контракта mca-09 нет. |
| AM-4 | mca-22 (атрибуция) — без amend | Association — доменная v30; `mca_bot_outputs` v22 без изменений (D9). |

## Риски и верификация
Risk **R3** (подтверждён): общий контракт на 5 потребителей + фоновые jobs на большом архиве + DDL/F8 + поведенческая заметность. Обязателен `threat-failure-analysis.md` (THR-1…THR-14). Верификация — spec §14: focused-фикстуры A18/A29–A35/A37, гейт-матрица OFF-паритета, миграция ×2, F8 `--check`, R17-скан, focused-регресс смежных контуров. Полная формулировка санкций — spec §13.

## ✅ Прод-валидация 2.58.61 (VERIFIED 05.10.2026; факты — серверное UTC)
Прод ff `5fe2d31..e26dcf9` (feat `780f77c` 83 файла + docs `bcb1a32` 8 + deploy-doc `e26dcf9`); рестарт #1 13:23:08 UTC (PID 3925252) + идемпотентный #2 13:31:08 UTC (PID 3927271), NRestarts=0, `/healthz` 200 `2.58.61` ×2 + `/api/health` 200. **DDL v29→v30 применена ровно один раз** (13:26:59 UTC): backup-guard fail-closed `pre_migration_20261005_132427.db` 1.319 GB read-back ok @v29 (ручной DevOps-бэкап 1.387 GB read-back @v29 ротирован retention'ом — ожидаемо, прецедент mca-09; якорь — guard-копия); `user_version` 30, `schema_migrations` `(29, intents)` + `(30, random_uses)` ×1, таблицы 109→112, `idx_mca_episodes_last_used` на месте, integrity ok, новые таблицы 0 строк; рестарт #2 — no-op; PG no-op. Данные целы (`task_jobs` 655→656, `mca_events` 11055→11061, `mca_bot_outputs` 88=88, `mca_random_draws` 0=0, `summary_runs` 15=15). Kill-switch — 0 env-оверрайдов (default ON). Проверки: 10b A–D 59 + репро F-1/F-2 4 (оба venv), смежные 134+134, js-unit 38, F8 `--check` OK **510** ×2, 0 ERROR/CRITICAL/Traceback, R17=0. Review T-5063 **Approved финал** (Needs Fixes → rework F-1/F-2 ровно 4 файла → addendum; binding ITER2 82 файла `48e0c979…bb4d385`). Rollback: soft `MCA_RANDOM_USES_ENABLED=false` / cold revert `780f77c` (v30 аддитивна). Live T-5065 — PENDING OWNER. Полная фактура — `deployment.md` (VERIFIED).

## История ревизий
05.10.2026 — Proposed (Step 2 @Architect, design-freeze, T-5048/T-5049; merge-цель §121 подтверждена — §120 занята mca-09, номер свободен проверен grep'ом); 05.10.2026 — review T-5063 Needs Fixes → bounded rework F-1/F-2 (honest outcomes + `close_stale_queued_explorations`) → **Approved (финал)**; 06.10.2026 — **Accepted** (merge §121 + deploy 2.58.61 VERIFIED; live T-5065 — за владельцем).
