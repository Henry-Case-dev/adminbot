# MCA-10b `mca-10b-random-applications` — evidence.md (Builder-1, T-5051…T-5056)

**Срез:** T-5051 (контракт ExplorationRequest/Result + purposes), T-5052 (один выбор в разговоре),
T-5053 (одно фоновое направление + lifecycle), T-5054 (настройки/kill-switch), T-5055 (memory_recall),
T-5056 (archive_sample) + санкция §13.1 DDL v30 + §13.3 kill-switch 72→73 + §13.4 reason_code +10.
Каталог Δ +6 (`memory.random_uses_*`) — блок E; рантайм читает `memory.random_uses_*` через
существующий read-path (`worker_settings.resolve_setting`, fail-open default True).

---

# Rework (Reviewer F-1/F-2, 06.10.2026) — bounded zone Builder-2

## Дефекты и фиксы
- **F-1 (dishonest post-selection outcome):** `after_sleep_direction` при `select_and_enqueue`
  → `not_run`/`deferred` (`range_occupied` и др.) продолжал эмитить `success/exploration_accepted`,
  перезаписывал статус в `enqueued` и никогда не звал `trace_finish` (run оставался running/stalled).
  **Фикс:** ветвление по статусу выбора — `selected` → success/`exploration_accepted` +
  `trace_finish(succeeded, exploration_accepted)` + `enqueued`; `deferred` → skipped/
  `exploration_deferred` + `trace_finish(partial, exploration_deferred)`; `not_run`/иной → skipped/
  `exploration_not_used` + `trace_finish(succeeded, exploration_not_used)`; конкретная причина
  выбора (`range_occupied`/`fully_covered`/…) остаётся в entity события → витрина показывает
  реальный исход («пропущено»/отклонено), а не «выполнено». Джоба при не-selected не создаётся и
  `enqueued` не пишется.
- **F-2 (orphaned queued exploration-job вечен):** executor выбирает только свои jobs,
  `recover_stale` чистит только `running` → зависший queued-job навсегда блокирует busy-check чата
  (`_uncovered_range` → None). **Фикс (bounded):** `mca_exploration.close_stale_queued_explorations`
  — queued `exploration.*` jobs ПРОШЛОГО прогона (`instr(coalesce_key, ':<current_run>:') = 0`),
  старше bounded-порога (`_STALE_QUEUED_EXPLORE_MAX_AGE = 3600`, env-free константа), кап 8 за
  проход → терминально `cancelled`/`exploration_deferred` (ничего не исполнялось) + lifecycle-
  событие (stage=deferred) → release busy-check. Вызов в hook `_maybe_random_uses_after_sleep`
  ДО `after_sleep_direction` (fail-open); текущий прогон не трогается.

## Pre-fix RED (фикстуры написаны ДО фикса, прогон зафиксирован)
- `test_F1_selection_not_run_honest_outcome`: `assert 'enqueued' == 'not_run'` — перезапись статуса
  воспроизведена; в captured-событии был `success/exploration_accepted`, run — без finish.
- `test_F2_stale_queued_job_released`: `AttributeError: module 'services.mca_exploration' has no
  attribute 'close_stale_queued_explorations'`; дефект-репро занятости подтверждён отдельным
  ассертом (`_uncovered_range` → None при живом stale-зависшем queued-job, green и до фикса —
  это и есть дефект).

## Пост-фикс прогон (`.venv\Scripts\python.exe -m pytest … -q`)
| Набор | Результат |
|---|---|
| block C rework (`-k "F1 or F2"`, 4 фикстуры) | **4 passed** |
| block C весь | **20 passed** |
| 10b blocks A+B+C+D | **59 passed** |
| mca-06 сон B–I + dream_worker (hook-носитель) | 148 passed |
| F8 `--check` | CHECK OK, EXIT=0 (510) — не затронут |

Покрытие rework-сценариев ревьюера: stale queued job → закрыт (`cancelled`/`exploration_deferred`)
+ release (busy-check снова даёт (1,3)); `not_run`/`deferred` выбор → честный skipped-исход +
`trace_finish` (run `succeeded`/`partial`, причина в reason_code); событие/entity отражает реальный
исход (для витрины: «пропущено»/отклонено, не «выполнено»); busy-check больше не блокирует;
текущий прогон не закрывается; happy-path `selected → enqueued/accepted` не регрессировал
(`test_T5057_T5058_direction_registry_and_execution`, block A direction-тесты — green).

**Файлы rework:** `services/mca_exploration.py` (ветвление F-1 + `close_stale_queued_explorations`),
`services/dream_worker.py` (cleanup-вызов в hook), `tests/…block_c…` (+4 фикстуры). Больше ничего
не менялось; commit/stage нет; `plans/current_task.md` не тронут.

---

# Builder-2 — T-5057…T-5062 + блок E (срез 05–06.10.2026)

**Source fingerprint:** работа в том же worktree поверх uncommitted Builder-1 дельты; HEAD `897ce4f`;
без commit/stage. Дельта Builder-2: `services/mca_exploration.py` (T-5057/T-5058/T-5059/T-5061),
`services/dream_worker.py` (исполнение belief_review/association_pair job), `services/direct_chat_service.py`
(пул форм в `handle_initiative` — sanctioned point), `services/mca_process_registry.py` (процесс
`random.uses` v1 + PipelineVersion + gate-resolver), `services/status_service.py` (`random_uses_snapshot`,
поле `uses` в существующем `random`-блоке), `web/app.js` + `web/index.html` (лента «Применения» внутри
СУЩЕСТВУЮЩЕЙ карточки «Источник случайности»; Δ routes = 0), `services/param_catalog.py` (+6 PG-only
bool, блок E), `tools/_mca10b_reissue_f8.py` (новый, F8-переиздание), артефакты F8
(`plans/docs/param-registry-round1025.{tsv,meta.md}`, `screen-map-round1025.md`,
`tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`), catalog-guard'ы в ~54 тестах
(504→510 / 479→485 / 93→99 / 504→510 screen-map / memory 40→46). Тесты: блоки C/D (новые).

## T-5057 — belief_review (§14.8, D8, A32)
- Реестр `background_types()` + `belief_review` (`BackgroundTypeSpec(use/available/select_and_enqueue)`
  — второй механизм не появлялся). Выбор ОБЪЕКТА: активные beliefs (`db.list_confirmed_beliefs` —
  существующий контур DreamWorker), старшая группа по `last_reviewed_at` (книга v30, NULLS FIRST =
  никогда), исключения: ожидающие обязательную перепроверку (`mca_dream_evidence.RevisionQueue` —
  существующая обычная очередь, CA-10B-6) и защищённые владельцем (`protected_facts`, overrides);
  ядро личности — структурно вне набора (derived graph_facts; граница AM-3). РАВНОМЕРНЫЙ draw объекта
  (`purpose=belief_review`) — «выбор ≠ вердикт».
- Исполнение (`execute_belief_review_job`): материалы = подтверждения И опровержения (факты чата,
  overlap REUSE `mca_dream_evidence.topic_overlap`, дрейф-маркеры REUSE `CONTRADICTION_MARKERS`);
  вердикт ДЕТЕРМИНИРОВАННЫЙ: `kept` / `narrowed` (applicability AM-5 через существующий
  `set_belief_status(belief_meta_patch)`; сужение ≠ отвержение) / `split` / `disputed` / (`replaced`
  зарезервирован существующим supersede-путём mca-06 — без LLM-пересмотра не создаётся).
  Отсутствие контрпримера НЕ усиливает (weight/last_confirmed_at/счётчики не трогаются).
- Защита от колебаний (THR-8): durable `material_refs_hash` (sha1 R17-safe refs) в `mca_belief_reviews`;
  те же материалы → `kept` + `belief_review_unchanged`, версия/вес не растут.
- Событие «Убеждение проверено/уточнено» — существующая лента снов (`db.log_dream_event` kind=
  `belief_review`, до/после через статус) + единый журнал (`random_uses_lifecycle`).

## T-5058 — association_pair (§14.9, D9, A33)
- Реестр `background_types()` + `association_pair`. КОНЕЧНЫЙ набор пар (cap ≤ 8, не декартов): сторона
  A — актуальный эпизод контекста сна (max `updated_at`), сторона B — СТРОГО `retrieve()` (L-MCA07-5);
  разные canonical event ID (redirect-резолв); тематическая связь (`topic_overlap`); обе стороны
  резолвятся (подтверждённые источники). Один draw пары (`purpose=association_pair`).
- Классификация связи — LLM (НЕ random): `analogy|motif|contrast|continuation|insufficient` + basis +
  SourceRef обеих сторон (`episode:<canonical>` refs; R17). Без LLM — честный `deferred` (fail-closed,
  семантика mca-05); `insufficient` → `rejected` = кэш попытки ПО ВЕРСИЯМ (версия стороны =
  `updated_at` эпизода; та же пара на тех же версиях повторно не выбирается).
- Хранение — v30 `mca_associations` (candidate — транзиент той же транзакции; финал
  accepted/rejected); АССОЦИАЦИЯ НЕ СКЛЕИВАЕТ истории (продолжения EpisodeService не создаются —
  проверено фикстурой), в досье/убеждения не попадает; принятая — кандидат координатору (статус
  `accepted` + событие), ПРЯМОЙ ОТПРАВКИ НЕТ (CA-10B-3/THR-10); атрибуция outputs — v22 без изменений.
- Редакция источника → `stale` (по версиям, ленивая инвалидация `mark_associations_stale` при
  выборе/исполнении; код `association_stale` из санкционированных +10).

## T-5059 — conversation_variant (§14.10, D10, A34)
- `build_conversation_form_candidates`: допустимые `communicative_intent` (observation/question/
  opinion/joke/recall/silence — read-only REUSE `COMMUNICATIVE_INTENTS` mca-09; НЕ новая
  action-schema) с целью/длиной/предметом/источниками/ограничениями стиля; неуместная шутка при
  direct — `admissible=False` + причина (R10b); recall требует источников-историй; молчание
  легитимно (`action=silent` — существующий). Формы — обычные `DecisionCandidate` в ОБЩЕМ пуле §14.5
  (`to_decision_candidate`): выбор в готовой процедуре D3 — РОВНО одна probability-проверка, БЕЗ
  отдельного стилевого броска (R10d), БЕЗ повторных процентов.
- Интеграция — точка `handle_initiative` (sanctioned): формы строятся ТОЛЬКО при разрешённом
  exploration (`exploration_allowed`); OFF → пул форм не строится, путь 2.58.60 бит-в-бит.
- Раскрытие решения: выбранная форма в `random_uses`-событии (entity `form`, R17-enum) +
  `candidate_actions` (исключённые с причинами); в чат — только естественная реплика, БЕЗ меток
  (в текст ничего не добавляется); форма не меняет факты/адресата/стилевые запреты.
- `is_repeated_phrase`: повтор фразы = повтор (bounded окно недавних своих реплик, overlap≥2 —
  REUSE `topic_overlap`; БЕЗ постоянного запрета слов).

## T-5060 — живая визуализация (§14.11, D11, A35)
- Бэкенд: `StatusService.random_uses_snapshot` — read-only проекция `mca_events` (компонент
  `random`, `random_uses*`), bounded 20, event-key cursor/dedup, chat scope (как у recent_draws:
  свой чат / global admin; иначе честный `restricted` без событий), additive поле `uses` внутри
  СУЩЕСТВУЮЩЕГО `random`-блока `GET /api/status` — Δ routes = 0, второго виджета/маршрута нет.
  НИКАКИХ QRNG/LLM-вызовов (фикстура с подорванным `RandomSourceService` — чтение работает).
- Метка источника = фактический (`actual_source` в entity события); «Пока нет событий» без имитации;
  отклонённый проверкой исход показан как отклонённый (`exploration_not_used`/`no_eligible_alternative`
  → «отклонено проверкой»), не как отправленный.
- Фронтенд: раздел «Применения» внутри карточки `data-random-source` (index.html) + computed
  `randomUsesView`/`replayRandomUses`/`toggleRandomUsesPause` (app.js): воспроизведение записанного
  (кандидаты → выбор), «Повторить» помечается бейджем «повтор», пауза, `prefers-reduced-motion` →
  подсветка без движения, текстовый список = альтернатива анимации, key-based рендер сохраняет
  scroll/focus, компактная мобильная вёрстка в сетке Статуса; OFF (`random.uses.ui_visualization`
  или master) → живая часть скрыта, остаётся статичный блок 10a.

## T-5061 — наблюдаемость (§14.11/§14.12, D12)
- Процесс `random.uses` v1 в `mca_process_registry` (code-declared, прецедент `random.source`):
  стадии = lifecycle §14.5 (`candidate→selected→checking→accepted/rejected/deferred/failed`),
  widget-ID «Случайность и её применения» — строка §27.1, контракт mca-17c (рендер не здесь);
  `PipelineVersion("random.uses","1")`; `_GATE_RESOLVERS["MCA_RANDOM_USES_ENABLED"]`;
  OFF → честный `disabled`, без событий → `not_run` (фикстуры).
- Trace `mca_pipeline_runs`: сквозной run на operation (разговор — в `choose_conversation_alternative`;
  фоновой — в `after_sleep_direction`, пробрасывается в исполнение job), события `random_uses*` несут
  `pipeline_run_id` (`query_run_events` связывает), честный итог (`succeeded`/`partial`/`failed` +
  reason-код). Master OFF → НИКАКИХ trace/событий (бит-в-бит 2.58.60).
- reason-коды — только санкционированные +10 (словарь 247, без изменений в этом срезе).

## Блок E — каталог Δ +6 + F8 (§13.2/D16)
- `services/param_catalog.py`: +6 PG-only bool `memory.random_uses_{conversation_variant,
  memory_recall, archive_sample, belief_review, association_pair, ui_visualization}` (прецедент
  `flags.chat_silent_ack_enabled`), существующая группа `memory_random`, per-chat, не-секреты,
  все default true (рантайм fail-open True; Settings-полей нет); master kill-switch в каталог НЕ
  входит (env-only, прецедент mca-16); игровой stub вне списка.
- Факты каталога (импорт `param_catalog`): **REGISTRY 510** / GROUPS **108** (0) / `_TAB_BY_GROUP`
  **106** (0) / TAB_RULES **21 in-place** / categorized **485** (+6) / memory **46** (+6) /
  секреты **32** (0) / Settings 441 (0).
- F8-переиздание (`tools/_mca10b_reissue_f8.py`, прецедент `tools/_mca10a_reissue_f8.py`):
  emit TSV/meta/screen-map → производные счётчики ПРОЧИТАНЫ ИЗ ВЫВОДА ТУЛА (meta: REGISTRY 510 /
  GROUPS 108 / TABS 106 / RULES 21 / rows 510 / **delta 93→99**) — не вручную (errata-урок 10a);
  `f8_baseline.json` (counts 510/108/106/21/99 + sha256 param_catalog + routes 33 без изменений) +
  `catalog_baseline.json` (510 ключей) обновлены; guard'ы тестов синхронно (504→510, 479→485,
  93→99, screen-map 504→510, memory 40→46).
- **F8 `--check`: `CHECK OK: реестр 510 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны`
  (EXIT=0).** Δ routes = 0: `web/api/routes.py` не менялся, `ROUTES_SHA256_F11` НЕ переутверждается
  (hash `efcbc457…dea90f2` — проверен фикстурой).

## OFF-паритет (срез Builder-2)
- Master OFF: `choose_conversation_alternative` → None/`disabled` без draw, БЕЗ trace/событий
  (trace_start перенесён ПОСЛЕ master-гейта — паритет 2.58.60); `after_sleep_direction` → `disabled`;
  пул форм не строится; `random_uses_snapshot` → `{enabled: false, events: []}`.
- Per-use OFF: `random.uses.conversation_variant=false` → формы не строятся, choose не вызывается
  (fixture `test_A34_per_use_off_pool_not_built`: sent, prob_calls==0); `ui_visualization=false` →
  живая часть скрыта; выключение одного применения остальные не ломает (механика part-1).

## Focused-прогоны Builder-2 (`.venv\Scripts\python.exe -m pytest … -q`)
| Набор | Результат |
|---|---|
| `tests/test_mca10b_random_applications_block_c_round1041.py` (T-5057/T-5058/T-5059, A32–A34) | **16 passed** |
| `tests/test_mca10b_random_applications_block_d_round1041.py` (T-5060/T-5061/блок E, A35) | **9 passed** |
| 10b все блоки A+B+C+D | **55 passed** |
| F8 `--check` (tools/gen_param_registry_round1025.py) | **CHECK OK, EXIT=0 (510)** |
| mca-10a блоки A–E (draw/запас/квота) | 78 passed |
| mca-09 блоки A–E + off_parity (Decision/инициатива) | 78 passed (повторно) |
| mca-06 сон B–I + dream_worker | 148 passed |
| mca-05 episodes + mca-07 retrieval + mca-01 task_supervisor | 139 passed |
| mca-16 experience A–F («расходы ≠ reward») | 91 passed |
| mca-13 events + mca-17a observability (реестр) | 95 passed |
| kill/reason/f8/catalog/pins selection (`-k "kill_switch or reason_codes or f8_baseline or release_manifest or counter_sweep or schema_frontier or param_catalog or round1025_f8 or frontend_tab_mapping or webapp_parity"`) | 203 passed |
| mca-22 core + truthset | 82 passed |
| budget/decision/miniapp pins | 154 passed |
| mca-04b dossier (потребитель реестра) | 50 passed |
| webapp_status_control + webapp_api | 177 passed / 1 pre-existing red (см. ниже) |
| webapp_js_unit + polygon/help/settings pins | 105 passed / 4 pre-existing red (см. ниже) |

## R17-скан (срез Builder-2)
События `random_uses*` — только ID/коды/enum/числа/refs (entity через `_short`; `basis` ассоциации в
СОБЫТИЯ не попадает — только доменная v30-таблица, как summary эпизодов). Витрина — whitelist-проекция
(`_USES_EVENT_FIELDS` + scalar-details из sanitized entity). Ключи ANU/провайдеров в снапшоте
отсутствуют конструктивно (прецедент 10a). Grep по emits — без сырых текстов/секретов.

## Incidental findings (не блокирующие; обработано/задокументировано)
1. **`trace_start` при master OFF** (найдено fixture `test_master_off_bit_parity`, исправлено в этой
   же дельте): trace-run открывался до master-гейта → событие PIPELINE_START при выключенном
   применении. Перенесён после `master_enabled()` — бит-в-бит восстановлен.
2. **CRLF-фантомные диффы worktree (pre-existing, окружение):** ~79 отслеживаемых файлов лежали на
   диске с CRLF при LF-блобах (mtimes сентября, вне срезов) — при пересборке индекса git показывал
   whole-file диффы. Нормализованы ТОЛЬКО файлы, чьё содержимое после EOL-нормализации байт-в-байт
   равно HEAD (дельта срезов не тронута); после этого `git diff` — ровно дельта Builder-1+2.
3. **Pre-existing reds (проверены на чистом HEAD `897ce4f` через worktree — НЕ дельта 10b):**
   - `test_webapp_status_control.py::test_status_public_for_all_roles` — пин `set(body)` не обновлён
     при добавлении top-level `experience` (mca-16) / `intents` (mca-09);
   - 4 × `test_webapp_js_unit` hotfix7–10 — пины `APP_VERSION = "2.58.59"` в харнессах против
     2.58.60 (mca-09 bump без обновления харнессов);
   - интер-тестовая pollution `test_mca09_intents_block_e::test_registry_process_intent_initiative`
     при прогоне после mca-17a (settings-mutation без отката); изолированно и в своём наборе — green.
   Класс — как принятый с-note `test_tool_loop` в mca-09; вне среза 10b, триаж @Orchestrator.

## Ограничения среза / notes
- «Verbalizer получает выбранный смысл» — в инициативном срезе mca-09 текст готовит вызывающий;
  семантика выбранной формы доезжает до потребителя контрактом mca-09
  (`selected_candidate.communicative_intent` + цель/длина/предмет/стиль на объекте формы в
  `mca_exploration.ConversationFormCandidate`); глубокой интеграции в Stage-2 вербализатор нет
  (зона mca-09 не трогалась сверх sanctioned point).
- Потребление accepted-ассоциаций координатором — через v30-таблицу + события; отдельного
  intent-кандидата worker не создаёт (отправка/кандидатура — только координатор, CA-10B-3).
- `replaced`-исход belief_review без LLM не синтезируется (текст новой версии не выдумывается) —
  только существующий supersede-путь mca-06; перечислено в D8-множестве, честный предел.
- Известный предел part-1 сохраняется: bounded `_candidate_chat_ids`/scan-caps — направление выбора
  смещено в нижнюю группу (безопасно), полный расчёт покрытия — эволюция.

**Source fingerprint (final):** HEAD `897ce4f` + uncommitted delta Builder-1 + Builder-2
(перечень файлов выше); `git diff` — ровно дельта; F8 `--check` EXIT=0 (510); 10b focused 55/55.

**Source fingerprint:** worktree HEAD `897ce4f` (uncommitted builder-delta поверх; без commit/stage —
по ограничению среза). Дельта: `services/mca_exploration.py` (новый), `services/mca_random_source.py`,
`services/mca_events.py`, `services/mca_gates.py`, `config/settings.py`, `services/database.py`,
`services/direct_chat_service.py` (sanctioned integration `handle_initiative`), `services/dream_worker.py`
(hook после пакета сна); тесты `tests/test_mca10b_random_applications_block_{a,b}_round1041.py` (новые) +
4 frontier/allowlist-пина в смежных тестах (см. «Incidental findings»).

## T-5051 — контракт + purposes
- `services/mca_exploration.py`: `ExplorationRequest`/`ExplorationResult` (поля spec §1: operation_id,
  chat_id, purpose, context_version, candidate_ids+versions, primary/eligible/excluded-grounds,
  probability, policy_version `mca10b-v1`, requested_source; result: selected, actual_source, draw_ids,
  fallback_reason, explanation, outcome, lifecycle, final_outcome) + lifecycle-константы
  `candidate→selected→checking→accepted/rejected/deferred/failed` + `used_in_reply|stored_only|not_used`.
- Purposes — ровно +5 в ЕДИНСТВЕННУЮ карту 10a `EXPLORATION_PROBABILITY_KEYS` (`mca_random_source.py`,
  AM-1): `conversation_variant`/`memory_recall` → `memory.random_exploration_probability`;
  `archive_sample`/`belief_review`/`association_pair` → `memory.random_sleep_exploration_probability`.
  Новых probability-ключей нет; `ui_replay` — read-only маркер (в `choose()` отвергается существующей
  проверкой неизвестного purpose); `ui_visualization` — настройка `random.uses.*`.
- Один источник draw — `RandomSourceService.choose`/`draw_index`/`draw_probability` (10a reuse);
  второй RandomSource/координатор/очередь/словарь не созданы; отдельной таблицы Request/Result нет
  (журнал `mca_events`, jobs `task_jobs`).
- Фикстуры: запрос/результат воспроизводимы по журналу (`test_request_result_reproducible_from_journal`);
  `ui_replay` не создаёт draw (`test_ui_replay_creates_no_draw`); purpose вне набора отклонён
  (`test_unknown_purpose_rejected`).

## T-5052 — один выбор в разговоре (A29)
- `choose_conversation_alternative()` (mca_exploration): РОВНО одна probability-проверка на operation;
  общий пул целостных кандидатов (DecisionCandidate mca-09 read-only: memory-варианты с refs
  `episode:<id>` + формы участия — точки расширения T-5059); пустой пул → primary +
  `no_eligible_alternative` БЕЗ draw; LLM ради альтернатив не вызывается; memory-история в выборе →
  один дополнительный РАВНОМЕРНЫЙ draw (purpose=`memory_recall`, draw корректной выборки — не вторая
  probability-проверка); `direct_request`/иные ineligible-измерения отвергает политика 10a.
- Интеграция: `handle_initiative` (direct_chat_service, единый вход инициативного Decision) —
  `random_choice` → существующий `decide_initiative` (mca-09 контракт не менялся; уместность/проверка
  перед отправкой остаются у потребителя).
- Фикстуры: `test_one_check_one_draw_A29` (prob_calls==1, ровно 1 доп. draw только для истории),
  `test_empty_pool_normal_outcome_without_draw`, `test_randomness_does_not_substitute_retrieval_addressee`,
  интеграция `test_handle_initiative_one_check_per_operation`.

## T-5053 — одно фоновое направление + lifecycle (A37)
- Hook `_maybe_random_uses_after_sleep` (dream_worker) — ТОЛЬКО после завершения обычного пакета сна
  (`_tick` и `run_once`); `after_sleep_direction`: доступность типов (реестр `BackgroundTypeSpec`;
  недоступные → событие `exploration_type_unavailable`) → одна probability-проверка существующей точки
  (`sleep_after_consolidation` = существующий purpose ключа `memory.random_sleep_exploration_probability`)
  → равномерный draw типа → МАКСИМУМ 1 job.
- Job: kind `exploration.archive_sample` (основной archive worker его не выбирает — FIFO by construction),
  owner `random.uses`, уникальный coalesce-ключ `exploration:<chat_id>:<package_run_id>:<type>` (v14
  partial-unique) — рестарт не дублирует; повтор direction с тем же прогоном → `coalesced` (0 новых
  лотерей); исполнение — отдельный шаг, exploration-job никогда не создаёт exploration-jobs (без
  рекурсии, THR-2); lifecycle-переходы — `random_uses_lifecycle` (reason-коды из санкционированных +10);
  результаты → память (эпизоды), НЕ Telegram (CA-10B-3).
- Фикстуры: `test_exploration_job_key_unique_per_package`, `test_direction_no_lottery_after_job_completion`,
  `test_A31_no_recursion_exploration_to_exploration`.

## T-5054 — настройки/kill-switch
- `MCA_RANDOM_USES_ENABLED`: env-only ClassVar default ON (`config/settings.py`) + `mca_gates.KILL_SWITCHES`
  72→**73** + `mca_gates.random_uses_enabled()` (per-call). Per-purpose env-дубликатов нет.
- `random.uses.*` (6 uses, все default True; игровой stub вне списка): `use_enabled()` через
  `worker_settings.resolve_setting` (per-chat override работает уже сейчас; каталог-ключи те же — блок E
  регистрирует их в F8 без изменения read-path).
- `exploration_allowed()` = master AND use AND существующие K1/K4; OFF → честный `disabled`/`not_run`.
- Фикстуры: `test_kill_switch_registry_73_and_defaults` (73; reason 247), `test_master_off_bit_parity`
  (0 draw, 0 событий, direction disabled), `test_per_use_off_disables_only_itself` (OFF belief_review не
  ломает остальные + per-chat override), `test_off_parity_gate_matrix_focused` (K4/per-use комбинации).

## T-5055 — memory_recall (A30)
- Кандидаты только через `retrieve()` (`mca_retrieval_context`); релевантность → разнообразие (порог
  допуска ПРИВЯЗАН к версии ранжирования `RANKING_ADMIT_SHARE = {"mca07-retrieval-1": 0.5}`; неизвестная
  версия → fail-closed `insufficient_evidence`); dedup по canonical event ID (redirect-резолв — перефраз
  = повтор); предпочтение давно не использовавшимся.
- DDL: `mca_episodes.last_retrieved_at` (любой retrieval, включая поиск во сне) ≠ `last_used_in_chat_at`
  (только подтверждённая доставка) + индекс `idx_mca_episodes_last_used`.
- `handle_initiative`: штамп `mark_episodes_used_in_chat` — после фактической отправки (sent);
  исключение отправки → `delivery_unknown` (существующий код) отдельно + bounded-подавление немедленного
  повтора той же истории (`note_delivery_unknown`/`delivery_pending`, TTL 1 ч, cap 64).
- Событие выбора: `random_uses` stage=`memory_recall` (selected/candidates/excluded/давность).
- Фикстуры: `test_A30_fixed_draw_admissible_old_story`, `test_A30_paraphrase_recognized_as_repeat`,
  `test_A30_retrieved_vs_used_in_chat` (R6d), `test_A30_delivery_unknown_suppresses_immediate_repeat`,
  `test_A30_unknown_ranking_version_fail_closed`, `test_A30_episode_ids_of_candidate`.

## T-5056 — archive_sample (A31)
- Существующий resumable worker (`episodes.backfill`, task_jobs) — нового сканера/второй очереди НЕТ;
  exploration-job — отдельный kind, основной cursor/backfill-payload не трогается (проверено fixture:
  payload байт-в-байт до/после исполнения exploration-job).
- Карта покрытия `mca_archive_coverage` по календарным месяцам (msgs_total/verified_unique/episodes/
  last_explored_at/extractor_version; «нет истории» ≠ «не обработано»); merge через upsert
  (MAX — покрытие без дублей).
- Выбор: непустые периоды → нижняя группа по доле `verified_unique/msgs_total` → равномерный draw периода
  (purpose=`archive_sample`) → непроверенный поддиапазон ПО СТАБИЛЬНЫМ ID (первый блок, не покрытый
  эпизодами совместимой версии экстрактора); **random OFFSET отсутствует** (только keyset/агрегаты по ID).
- «Всё покрыто» → job только по причине пересмотра/новой версии экстрактора; БЕЗ причины — job не
  создаётся и draw НЕ расходуется (гейт до draw, THR-13). Диапазоны, занятые активными jobs того же чата,
  исключаются (coalesce/unique v14). Metadata job: причина/период/диапазон/покрытие/
  `additional_research=true`/checkpoint/extractor_version. Пустой результат → диапазон отмечен покрытием
  (R7c). Исполнение — существующий `EpisodeService.process_batch` (без LLM — записи не выдумываются).
- Фикстуры: `test_A31_coverage_map_by_periods`, `test_A31_lowest_coverage_uniform_draw_no_random_offset`,
  `test_A31_restart_does_not_duplicate_job`, `test_A31_range_ahead_of_cursor_main_cursor_untouched`
  (cursor untouched + R7c), `test_A31_main_worker_priority_by_construction` (R7d),
  `test_A31_no_recursion_exploration_to_exploration`, `test_A31_fully_covered_requires_reason`.

## Санкция §13.1 — DDL v30 (локально верифицировано)
Один `MigrationStep(30, "random_uses")` реестра mca-14 + `_migrate_random_uses_v30`:
ALTER `mca_episodes` (+`last_retrieved_at`/`last_used_in_chat_at` + `idx_mca_episodes_last_used`) +
CREATE `mca_associations` (+idx chat/status, side-a, side-b) + `mca_archive_coverage` (PK = санкционированный
idx (chat_id, period)) + `mca_belief_reviews` (+idx belief/reviewed). PG no-op (memory-контур SQLite-only,
GEN-R4); повтор — no-op; v30 строго аддитивна (cold-revert безопасен).
Локальные факты (`test_ddl_v30_fresh_and_idempotent`, `test_ddl_v30_simulation_from_v29_with_backup`):
- fresh: `user_version=30`; 3 таблицы + 2 колонки + индекс; книга `(30, random_uses)` ровно ×1;
  повторный `initialize()` — no-op (книга/таблицы/индексы без дублей).
- v29→v30 симуляция (прод-подобный апгрейд): непустые `smart_messages` + 1 эпизод переживают апгрейд;
  backup-guard создал `pre_migration_*.db` с read-back `user_version=29` (fail-closed-семантика рамки);
  после апгрейда данные на месте, `last_retrieved_at`/`last_used_in_chat_at` = NULL (честный unknown);
  повтор на обновлённой БД — no-op.

## Focused-прогоны (`.venv\Scripts\python.exe -m pytest … -q`)
| Набор | Результат |
|---|---|
| `tests/test_mca10b_random_applications_block_a_round1041.py` | **17 passed** |
| `tests/test_mca10b_random_applications_block_b_round1041.py` | **13 passed** |
| mca-10a blocks A–E (regression политик/источника) | 78 passed |
| mca-09 blocks A–E + off_parity (Decision/инициатива) | 78 passed |
| mca-06 sleep B–I + dream_worker (сон/hook-носитель) | 148 passed |
| mca-05 episodes + mca-07 retrieval + mca-01 task_supervisor | 139 passed |
| mca-16 experience A–F | 91 passed |
| mca-13 events + mca-17a observability | 95 passed |
| kill/reason/f8-related selection (`-k "kill_switch or reason_codes or f8_baseline or release_manifest or counter_sweep or schema_frontier"`) | 138 passed |
| mca-22 core + direct decision matrix (зоны смежного кода) | 90 passed |

## OFF-паритет
- `MCA_RANDOM_USES_ENABLED=false` → `choose_conversation_alternative` возвращает None без draw и без
  событий; `after_sleep_direction` → `disabled`; `handle_initiative` идёт primary-путью (fixture
  `test_handle_initiative_master_off_bit_parity`: sent, prob_calls==0). Существующие контуры
  (10a политика, mca-06 сон, mca-09 Decision) не изменялись → бит-в-бит 2.58.60.
- `random.uses.X=false` отключает только X (`test_per_use_off_disables_only_itself`); K1/K4 OFF →
  честный `disabled` через существующую семантику 10a.

## Incidental findings (не блокирующие, обработаны)
1. **Frontier-пины смежных тестов (related, fixed in-slice, прецедент counter-sweep mca-09 [D-1]):**
   глобальный schema-frontier 29→30 сломал точные пины в `test_mca09_intents_block_a_round1040.py`
   (2 теста), `test_mca16_experience_block_a_round1039.py` (2), `test_mca05_episodes_stories_round1027.py`
   (3, mark-константа) — обновлены на «frontier ≥ mark» по существующей конвенции «mark обновлён по
   хвосту реестра» (прецедент v27→v28→v29 в самом файле mca-05).
2. **Census-allowlist mca-01 (`test_mca01_tx_task_supervisor_round1027.py`):** `database.py` commit-сайтов
   171→**176** (+5 в `_migrate_random_uses_v30`) — L-MCA14-3 (раннер до старта писателей), тот же
   санкционированный паттерн, что +3 v29. Рантайм применений — через `write_transaction`.
3. **Опережение draw при «всё покрыто»** (найдено при fixture, исправлено в этой же дельте): изначальный
   порядок тратил draw периода до гейта «всё покрыто» — перенесён гейт ДО draw (THR-13, квота 10a).

## Ограничения среза / notes для Builder-2 (T-5057–T-5062)
- T-5057 belief_review / T-5058 association_pair: v30-таблицы готовы; типы в реестре
  `background_types()` не зарегистрированы → сейчас честно `exploration_type_unavailable`; добавление =
  `BackgroundTypeSpec(use=…, available=…, select_and_enqueue=…)` — второй механизм появляться не должен.
- T-5059 conversation_variant: пул-процедура принимает формы участия как обычные DecisionCandidate
  (`communicative_intent`); «одна проверка» уже гарантирована процедурой.
- T-5060 ui_visualization: `random_uses`-события (stage= purpose/lifecycle/direction) — источник данных;
  `ui_replay`-маркер в контракте (`ExplorationRequest.replay`, read-only).
- T-5061: процесс `random.uses` в `mca_process_registry` + trace `mca_pipeline_runs` + строка матрицы
  §27.1 — НЕ сделано (вне среза); reason-коды уже в едином словаре (247).
- Блок E: каталог Δ +6 `memory.random_uses_*` (REGISTRY 504→510) + F8-переиздание; read-path уже читает
  эти pg-ключи — после регистрации F8 рантайм менять не нужно; `MCA_RANDOM_USES_ENABLED` в каталог не
  добавлять (kill-switch вне каталога, прецедент mca-16).
- Известный осознанный предел: `_candidate_chat_ids` bounded (8 чатов) и `_ARCHIVE_EPISODES_SCAN_CAP=2000`
  — покрытие больших чатов может быть частично-заниженным (безопасное направление выбора: в сторону
  нижней группы); полный расчёт покрытия — блок E/настраиваемая эволюция, не блокер контракта.
