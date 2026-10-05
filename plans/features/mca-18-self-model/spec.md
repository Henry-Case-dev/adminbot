# MCA-18 `mca-18-self-model` — spec.md (Step 2 @Architect, design-freeze, 06.10.2026)

**Статус:** 🟦 **PLANNING_CONSISTENT + design-freeze** (T-5073/T-5074 исполнены). Санкции — §8 этого файла + `adr-1028-18-self-model.md` (Proposed) + `plans/docs/mca-round1027-arch-frames.md` (доп. запись).
**Требования:** §28.1–§28.7 `plans/current_task.md:1494–1606` (не изменялся, R17); приёмки A58–A63 `:939–944`; реестр процессов `:1364`; GEN-R18 `:43`.
**Baseline (проверено на HEAD `23cb2a1`, 06.10.2026):** прод 2.58.61; SQLite **v30** (`_SCHEMA_VERSION_RANDOM_USES = 30`, `database.py:1273`); каталог F8 **510/108/106/21**; KILL_SWITCHES **73**; REASON_CODES **247** (`services/mca_events.py:60`); последний ADR — **ADR-1028-17** (mca-10b, архив); max task-ID T-5071. mca-10b/mca-16 `bot_persona.py` **не трогали** — швы mca-08 нетронуты (подтверждено чтением).

---

## 0. Scope / исключения

**In scope:** MCA18-R1…R7 (`requirements-map.md` §2) — SelfModelSnapshot, три настройки, расширение контракта памяти, TraitObservation→BehaviorRule, компилятор BehaviorFrame, legacy-разбор, контрактные тесты + paired replay, наблюдаемость (GEN-R17).
**Out of scope:** vision/mca-19, временной фактчек/mca-20, истории/mca-12, полная матрица самообучения/mca-17c, Intent-жизненный цикл/mca-09, обучение весов/новый провайдер/доказательство сознания (`:1606`, GEN-R2). Вторые механизмы (личность/слой промпта/bundle/контракт памяти/реестр/координатор/словарь событий) запрещены — CA-18-1…9 (`requirements-map.md` §4).
**Решение границы N-1 mca-10b (CA-18-6, `backlog.md:289`):** `select_memory_recall_candidates` (`services/mca_exploration.py:2083`; живой путь не подключён — проверено grep) в mca-18 **НЕ подключается**. Граница: mca-18 определяет *какое поведение* (frame), селектор mca-10b — *какие воспоминания* вызываются; связывание расширяет радиус поражения без требования владельца. Остаётся disclosed backlog-пунктом mca-10b (кандидат — волна наблюдаемости/release). Фиксируется в ADR-1028-18 D9.

---

## 1. Контракт SelfModelSnapshot (MCA18-R1/R2; задачи T-5075/T-5076)

**D1.** Новый модуль **`services/mca_self_model.py`** (один модуль: snapshot + резолвер + компилятор frame + lifecycle черт; БЕЗ отдельного сервиса/провайдера, `direct_chat_service` не растёт — `:1568`).

`SelfModelSnapshot` — frozen-dataclass, **не хранимая сущность**, а снимок на запуск (версия — производный токен):

| Поле | Источник |
|---|---|
| `agent_id` | стабильный UUID (таблица `mca_self_identity`, v31) — переживёт смену токена/модели; смена Telegram-аккаунта = ЯВНЫЙ rebind (admin-действие), не по похожему имени (`:1517`) |
| `bot_user_id` | фактический Telegram bot user ID (runtime `get_me`) |
| `persona_id`, `persona_version` | PG `personas` effective-строка; `persona_version` = хеш (name, biography, overrides, is_aware_ai, updated_at) — **смена модели/токена НЕ сбрасывает** (R2d) |
| `scope_chat_id` | None = global |
| `name`, `aliases` | PG `personas.name` + display-алиасы mca-03 с периодами действия (REUSE, второй контракт идентичности запрещён) |
| `biography`, `style_version` | PG `personas` (biography; style_version = хеш `system_prompt_overrides`) |
| `traits` | активные BehaviorRule (v31-таблица), компилированное view |
| `interests`, `relations` | структурированные правила (§28.4 `:1554`); relations — локальны по chat |
| `state` | настроение с TTL (`valid_to`); обратимо |
| `positions` | собственные мнения с provenance (`mca_adoption_links`, v31) |
| `self_presentation_mode` | резолв `is_aware_ai` effective → `aware` / `in_character` (режим ролевого поведения, не онтология; `:1522`) |
| `capabilities`, `limits` | **реестр инструментов + runtime-состояние**, не биография (`:1527`); «могу/посмотрел/помню» — по фактическому доступу |

**Инварианты:** (I-1) один snapshot на запуск ответа (`:1572`); (I-2) `agent_id`/`persona_version` не меняются от смены модели/токена; (I-3) capabilities ≠ вымысел (нет vision → «посмотреть изображение» не заявляется).

---

## 2. Три настройки — одна точка сборки (MCA18-R2; T-5075)

**D2.** Настройки разводятся, хранение существующее, где возможно:

| Настройка | Хранение | Effective/наследование | OFF-семантика |
|---|---|---|---|
| `persona_enabled` | **НОВЫЙ** ключ `flags.persona_enabled` через `chat_params.get_chat_param` (прецедент `direct_chat_service.py:4856–4861`: override → global) | UI: effective + источник наследования | без характера/образа в речи, НО авторство, тех-идентичность, разделение участников/источников сохраняются (`:1521`) — **OFF persona ≠ отмена авторства** |
| `is_aware_ai` | PG `personas.is_aware_ai` (без изменений схемы) | global/chat строки `personas` (существующий `resolve_bot_persona`) | False = держится образа, не вставляет тех-самоописание без повода; **тех-идентичность в runtime сохраняется при обоих значениях** (`:1522`) |
| `bot_self_awareness_enabled` | существующий flags-путь (`direct_chat_service.py:4836–4861`) | существующий per-chat override | OFF останавливает рефлексию, НЕ склеивает слова пользователя и бота в один факт (`:1523`); UI-пояснение «Рефлексия собственных ответов» |

**Состояния различаются** (`:1525`): `False` / `null-наследовать` / `ошибка загрузки` — три разных значения резолва (статус-enum в snapshot; ошибка никогда не сворачивается в False — разрыв §28.1 `:1509`).
**Одна точка сборки (D3):** `build_persona_prompt_block` (`services/bot_persona.py:237`) — единственное место разрешения конфликта «старый промпт-запрет vs True». Мастер-гейт ON → функция рендерит из BehaviorFrame; формулировка False **заменяет** абсолютный запрет `_NO_AI_DISCLOSURE_BLOCK` (`bot_persona.py:32–36`, врезка `:272`), а не дописывает противоположное указание в конец (`:1525`). Все конечные пути (direct/autonomous/System2/инструменты/редактура) вставляют характер только через существующие швы mca-08: `<Character_Rules>`/`character_block`; form-постпроцессор `form_contract` в `verbalize_validated` **не трогается** (не второй редактор). Шов `traits_scope` (`bot_persona.py:183/:190/:394`) потребляется: `CharacterReadContext` получает компилированные правила вместо сырых строк.

---

## 3. Типы памяти и субъект (MCA18-R3; T-5077/T-5078)

**D4.** Расширение единого контракта mca-03/04 поверх `graph_facts` + provenance v17 (`database.py:1754`; mca-04a `:330–339`) — **не копия графа** (`:1533`).

**Δ колонки `graph_facts` (все nullable/DEFAULT, кроме revision):** `subject_entity_id TEXT` (стабильный ID участника/источника mca-03), `speaker_entity_id TEXT`, `perspective TEXT` CHECK IN (`self`,`other`,`quoted`,`third_party`,`ambiguous`), `memory_kind TEXT` CHECK IN (`world_fact`,`self_event`,`self_trait`,`opinion`,`belief`,`paradigm`,`mood`,`lesson`; NULL = legacy `world_fact`), `scope TEXT` (`global`/`chat`), `valid_from INTEGER`, `valid_to INTEGER`, `confidence_basis TEXT` (JSON), `revision INTEGER NOT NULL DEFAULT 1`.
**REUSE (не дублировать):** `status` (`database.py:4685`, default 'confirmed'), `supersedes` (`:4687`), `weight`, `source_refs` = `mca_source_refs`/`mca_evidence_links`/`mca_provenance_status` (v17). Семантика reuse-колонок фиксируется в ADR-1028-18 (AMEND ADR-1027-6).

**Правила атрибуции (`:1533`):** `self` — только по стабильному `agent_id` + исходным сообщениям; «я» внутри цитаты → автор цитаты; «бот» без доказанного референта → `perspective='ambiguous'` (не меняет характер); автор пересылки / автор исходного поста / изображённый автор — разные роли (роли mca-03).

**Новая таблица `mca_adoption_links`** (v31): принятие собственного мнения из опыта — subject='self', basis_refs (source_ref_id), adopted_at, direction; `mca_adoption_links` обязателен для «я предпочитаю X»; повтор фразы группой сам по себе мнение не создаёт (`:1546`).

**Таблица запретов `:1535–1544`** — enforced в коде компилятора + write-путях памяти + негативные тесты на каждый запрет (факт ≠ черта себя; свой ответ ≠ доказательство; self-trait ≠ всем темам/адресатам; мнение ≠ факт; убеждение сна ≠ личная ценность; парадигма вне периода; настроение обратимо; lesson ≠ идентичность).

---

## 4. TraitObservation → BehaviorRule (MCA18-R4; T-5079/T-5082/T-5083)

**D5.** Таблицы v31 (SQLite — транзакции с памятью через `write_transaction` mca-01; сон/разбор — те же worker-очереди):

`mca_trait_observations`: id, agent_id, chat_id NULL, dimension TEXT NULL (NULL = неприведённое), raw_text (дословно), normalized TEXT, source_refs JSON (mca_source_refs-id), subject_status (`self`/`ambiguous`/`other`), observed_at, source_chat_id, legacy_ref (persona_traits.id для legacy), created_at.

`mca_behavior_rules`: id, agent_id, dimension, target_value REAL, strength REAL, confidence_basis TEXT, scope, applicability JSON, exclusions JSON, expiry_at, review_at, examples JSON, counterexamples JSON, **status** (`observed`→`candidate`→`active`/`rejected`/`suspended`/`superseded`), status_reason, source_observation_ids JSON, version INTEGER, event_dedup_hash, updated_at.

- **Авто-валидация** (без ручного одобрения каждого, `:1552`): структурная валидность, субъект=self доказан, источник существует, конфликт с ядром (owner_core), допустимое влияние. Новое имя dimension от LLM → **candidate с причиной**, исполняемый код не создаётся (`:1554`). 8 начальных dimensions: прямота, резкость, сарказм, краткость, инициативность, любопытство, склонность спорить, теплота.
- **Конфликты ДО генерации** (`:1560`), порядок = `CHARACTER_PRECEDENCE` (`bot_persona.py:44–46`), не менять: owner_core → owner_style → scoped_request → derived_traits → state. Одноразовая просьба («без шуток») действует на ответ, не удаляет черту (mca-08 `mca_style_scope.py`); противоположные наблюдения — supersede либо явная локализация.
- **Анти-самоусиление (A61, `:1562`):** ответы под чертой помечены rule version/id (mca-22 `mca_bot_outputs` — свои ответы ≠ независимое подтверждение); повторное извлечение ≠ подкрепление; дедуп по **исходным событиям**, не по summary; шаг ≤ **0.1/цикл**, ≤ **0.2/24 ч** (env-only, инженерные дефолты — GEN-R27 `:1092`); ослабление/отмена допускаются; TTL настроения **6 ч**.
- **Границы (CA-18-2/3, `:1544`/`:1558`):** `quality_regression` → наблюдение в `mca_experience` (mca-16), НЕ правило «менее полезные ответы»; lesson (mca-16) ≠ trait ≠ парадигма (mca-06) ≠ style request (mca-08) — кросс-тесты T-5083. «Склонен перекладывать вину» не компилируется в ложную атрибуцию чужих сообщений.

---

## 5. Один компилятор: resolve → select → BehaviorFrame (MCA18-R5; T-5080/T-5081/T-5088)

**D6.** В `services/mca_self_model.py`:
`resolve_self_model(scope) -> SelfModelSnapshot` → `select_behavior(snapshot, EvidenceBundle) -> BehaviorFrame`. Компиляция **детерминирована** (без LLM-пересказа личности на каждый ответ — `:1568`).

`BehaviorFrame` (frozen, сериализация структурированных данных — не «бот»→«я» replace, `:1570`): `snapshot_version`, адресат/ситуация, self identity, режим самопредставления, применимые правила **с ID** (подтверждённые — во 2-м лице, явно отличны от цитат/справок), выбранные мнения, эмоциональная поправка, factual constraints, `rejected_rules` с причинами.

- **Frame во ВСЕ конечные пути** (`:1572`): decision (аддитивное поле `CoordinatorDecision` — enum mca-09 не меняется, CA-18-7), direct, autonomous, synthesis, verbalizer, postprocessor. Тех-вызовы (поиск/OCR/tool payload/JSON/сырая транскрипция) стиль не получают. Фактчек: сначала вердикт+источники, потом голос персонажа без смены смысла. Обходные пути фиксируют применение либо обоснованный skip.
- **Кеш** (D7): ключ = `persona_version` + `rules_version` (max rules.updated_at/hash) + `flags_revision` (прецедент `mca_retrieval_context.py:257` `"persona=" + ...`). Настройка действует со следующего запуска; **in-flight ответ сохраняет свою версию в trace** (не смешиваются две личности, `:1574`). Стабильный префикс отделён от динамического frame.
- **Fallback (R5c, `:1576`):** PG недоступен → last-known-good snapshot со **stale-маркером** (ограниченный TTL) либо минимальная тех-идентичность; честные reason-коды (`self_model_stale`/`self_model_unavailable`); fallback никогда не отчитывается как «успешно загруженная персона»; тихий ON запрещён.
- **Гибрид пустой персоны (A58, `:1503`):** пустые поля при True/False дают различимое поведение (минимальная тех-идентичность/режим), не пустую строку-заглушку; `if not lines: return ""` до `is_aware_ai` устраняется внутри одной точки сборки.

---

## 6. Legacy-черты и интерфейс (MCA18-R6; T-5084/T-5085/T-5086)

**D8.** Фоновый **идемпотентный** разбор PG `persona_traits` (`pg_db.py:260`: id/chat_id/trait/source/created_at) — job существующей очереди mca-01 (`task_jobs`, kind=`legacy_traits_parse`, coalesce-key, повтор = no-op по `legacy_ref`):
- сохраняются original ID/text/source/chat/time; source_refs — по mca-04a **только из реального происхождения**, фабрикация запрещена (`:1582`);
- без доказанного субъекта/оснований → candidate + `legacy_unverified` (не active); подтверждённые включаются сразу по мере обработки; ручная черта (`source='manual'`) — основание = действие владельца;
- весь архив ДО включения перерабатывать не требуется;
- глобальное ядро сохраняется; отношения/локальные реакции — локальны; chat→global — явное правило + обезличивание; отсутствие chat_id не доказывает универсальность (`:1584`); FIFO не удаляет единственную запись активного состояния и provenance-ссылки.

**UI (без нового раздела/маршрута, CA-18-8):** редактор личности — настройки + effective + наследование + пояснения трёх переключателей; витрина — живое превью эволюции; «Память» — правка/пауза/источники черт; «Аналитика» компакт — «Что сейчас формирует характер» (база/динамика/настроение/версии; клик → основания → примеры → результат). Фуннель/матрица — mca-17c.

**Наблюдаемость (GEN-R17, `:1364`, `:1588`):** процесс **`self.model` v1** в реестре mca-17a (code-declared, прецеденты `services/mca_process_registry.py:222+`); стадии: `observation_read`, `attribution`, `candidate_compile`, `validation`, `activation`, `selection`, `prompt_render`, `final_check`; per-rule included/excluded/conflict/stale + причина + frame version; widget-ID — контракт для mca-17c. Три статуса различимы: «передано модели» ≠ «проявилось по оценке» ≠ «доказан сравнительный эффект».

---

## 7. Верификация (MCA18-R7; T-5089/T-5090)

**Прогрессивно (риск R3):**
1. **Контрактные тесты §28.7 `:1594`** — 100% зелёные, блокер: пустая персона True/False; override/сброс `persona_enabled`; self/другой бот/цитата; все конечные пути (один frame+версия); смена версии; конфликт с ядром (порядок precedence); отсутствие фактической подмены; сбой PG → честный stale/fallback; повторное подкрепление одним эпизодом подавлено; гарды 0.1/0.2/6 ч; идемпотентность legacy-разбора; запреты таблицы `:1535–1544`.
2. **Offline paired replay** — 30 сценариев (шутка/спор/просьба/фактчек/длинная ветка/смена темы/провокация подмены) × ≥3 генерации, с правилом и без, модель/настройки равны; **рубрика заморожена ДО прогона** (прямота/резкость/сарказм, соблюдение задачи, адресат, фактологические/временные ошибки, мета-самоописание, устойчивость); оценщик без знания условия; авто-оценка вспомогательная; бюджет генераций — через учёт mca-11; случайность сценариев — read-only `mca_random_draws` (не вердикт); **без посылки в рабочий чат**. Мягкий признак: направленный воспроизводимый эффект иначе правило НЕ «проверено» (R7c); не объявлять 100% управление личностью LLM.
3. Широкая регрессия — только Block H (T-5091): полный pytest/JS + OFF-паритет 2.58.61 + смежные (mca-08 form-guard, mca-15 numeric, mca-16 lessons, mca-09 Decision, mca-10b conversation_variant).

---

## 8. САНКЦИИ (T-5074; @Architect)

### 8.1 Δ DDL — SQLite **v31**, одна аддитивная миграция через реестр mca-14 (`MigrationStep(31, "self_model")`, backup-guard, идемпотентно; PG DDL = **0** — `personas`/`persona_traits`/`persona_state` не изменяются):

| Объект | Точно |
|---|---|
| `CREATE TABLE mca_self_identity` | id BOOLEAN PK DEFAULT true CHECK(id), agent_id TEXT NOT NULL, bot_user_id INTEGER, bound_at INTEGER, note TEXT, updated_at INTEGER; сид-строка ON CONFLICT DO NOTHING |
| `CREATE TABLE mca_trait_observations` | §4 (поля выше) + idx (agent_id, observed_at DESC), idx (chat_id, observed_at DESC) |
| `CREATE TABLE mca_behavior_rules` | §4 + idx (agent_id, status, dimension), idx (scope, status) |
| `CREATE TABLE mca_adoption_links` | id, subject_entity_id TEXT NOT NULL DEFAULT 'self', opinion_ref TEXT NOT NULL, basis_refs TEXT NOT NULL, adopted_at INTEGER NOT NULL, direction TEXT NOT NULL DEFAULT 'adopted', UNIQUE (subject_entity_id, opinion_ref) |
| `ALTER TABLE graph_facts ADD COLUMN` ×9 | `subject_entity_id TEXT`, `speaker_entity_id TEXT`, `perspective TEXT`, `memory_kind TEXT`, `scope TEXT`, `valid_from INTEGER`, `valid_to INTEGER`, `confidence_basis TEXT`, `revision INTEGER NOT NULL DEFAULT 1` (9 новых; `status`/`supersedes`/`weight` — reuse), каждый под guard `PRAGMA table_info`; idx (chat_id, memory_kind, status), idx (subject_entity_id) |

Rollback DDL: аддитивна, старый код новые колонки/таблицы не читает; cold revert безвреден.

### 8.2 Δ каталога = **0** (errata 06.10.2026, ре-санкция после Step A/B @Builder). Исходная санкция «+1 `flags.persona_enabled`» **отозвана**: ключ **уже существует** как pg_key параметра `PERSONA_ENABLED` (`services/param_catalog.py:1182`, группа `flags_memory`, «Личность бота (Persona)»; прецедент round 10.14 F2/ADR-1014-1) — кастинг/наследование/per-chat уже работают через существующую запись (воспроизведено Builder-1; дубликат pg_key ломает инвариант F8). Настройка уже управляема владельцем через существующую запись каталога — семантического гэпа нет; OFF-семантика «≠ отмена авторства» — это поведение snapshot/frame-пути (spec §2/D2), а не новый ключ. **F8 (ADR-1026-2) для mca-18 НЕ переиздаётся**, каталог 510 не меняется (репетиция re-issue Builder-ом откатлена до HEAD-510, F8 green 29). Пороги 0.1/0.2/6 ч и kill-switches — **env-only ClassVar** (Δ=0). `bot_self_awareness_enabled`/`is_aware_ai` — существующие ключи, без Δ.

### 8.3 Kill-switches — ровно **3**, env-only `ClassVar[bool] = _env_bool(..., True)`, регистрация в `mca_gates.py` (73→76), **OFF = бит-в-бит 2.58.61** (в т.ч. старая формулировка `_NO_AI_DISCLOSURE_BLOCK` при OFF):

| Switch | Зона OFF |
|---|---|
| `MCA_SELF_MODEL_ENABLED` | мастер: snapshot/resolve/frame/сборка — legacy-путь `build_persona_prompt_block` как в 2.58.61 |
| `MCA_TRAIT_RULES_ENABLED` | lifecycle TraitObservation/BehaviorRule + анти-самоусиление + гарды; v31-таблицы инертны |
| `MCA_LEGACY_TRAITS_MIGRATION_ENABLED` | фоновый разбор `persona_traits` не запускается |

### 8.4 reason_code — **+10** (247→257) в единственный словарь `services/mca_events.py:60`: `self_model_unavailable`, `self_model_stale`, `self_model_disabled`, `self_model_snapshot_error`, `trait_attribution_ambiguous`, `trait_conflict_core`, `trait_step_limit`, `trait_reinforcement_dedup`, `legacy_trait_unverified`, `trait_rule_rejected`.

### 8.5 Risk: **R3 подтверждён** (`:209`) — память→поведение на живых ответах, риск инъекции/самоусиления/подмены идентичности. `threat-failure-analysis.md` выпущен (этой папки). Отдельные env-only лимиты: `MCA_TRAIT_MAX_STEP_PER_CYCLE` (0.1), `MCA_TRAIT_MAX_STEP_24H` (0.2), `MCA_MOOD_TTL_HOURS` (6).

### 8.6 Deploy: **пер-фичевый bump 2.58.61→2.58.62** (CA-11; прецедент mca-15/16/09/10b), НЕ `DEFERRED_TO_RELEASE`: R3-фича с межбазовым контрактом и live-приёмкой A58–A63 — изоляция отката важнее одной платформы Wave-4. Rollback: soft = 3 kill-switch + рестарт; cold = `git revert` (DDL v31 аддитивна); restore backup-guard — аварийный. Merge-цель `plans/ARCHITECTURE.md` **§122+**; ADR → Accepted по прод-валидации.

### 8.7 ADR: **ADR-1028-18** — следующий свободный (grep 06.10.2026: занят до ADR-1028-17 вкл.; упоминание -18 в `workflow_state.md:563` — лишь планировочная заметка этого же dispatch).

---

## 9. Якоря (проверены на HEAD `23cb2a1`, 06.10.2026)

- Швы mca-08: `services/bot_persona.py:42` (`CHARACTER_LAYERS`), `:44–46` (`CHARACTER_PRECEDENCE`), `traits_scope` `:183/:190/:394`, `resolve_character_context` `:368` (fail-open `:373–390`), `build_persona_prompt_block` `:237`, `_NO_AI_DISCLOSURE_BLOCK` `:32`/врезка `:272`, `<Character_Rules>` `:50–56`. Потребители: `direct_chat_service.py:2176–2178` и `:3223–3225` (get_traits+persona-блок) — обе точки переходят на frame через ту же функцию.
- Разрывы §28.1: `get_traits(limit)` без chat_id — подтверждено; ошибки чтения → пустой список — подтверждено (`bot_persona.py:387–390`); F-3 (`backlog.md:216`) закрывается T-5087.
- `flags.bot_self_awareness_enabled`: `direct_chat_service.py:4836–4861`, `summary_memory.py:3130–3141`; механизм effective — `chat_params.get_chat_param` (`:4857–4861`, прецедент наследования mca-06).
- PG: `pg_db.py:215` (`persona_state`), `:231–254` (`personas`, is_aware_ai `:238`), `:260–271` (`persona_traits` + idx).
- SQLite: `database.py:1754–1777` (`graph_facts`), `:330–339` (v17 provenance, REUSE-контракт), `:4684–4687` (`weight/status/last_confirmed_at/supersedes`), `:1273` (v30), `:1589` (`MigrationStep`), `:222+` (реестр шагов).
- События/гейты: `services/mca_events.py:60` (REASON_CODES), `services/mca_gates.py:347–368` (паттерн регистрации), `config/settings.py:1461–1462` (паттерн `_env_bool`).
- Реестр процессов: `services/mca_process_registry.py:54/:222+` (process_id/version, code-declared).
- Кеш-прецедент: `services/mca_retrieval_context.py:218–219/:243/:257` (persona/persona_version в bundle-ключе — carry-over **M-MCA07-2** переходит к mca-18).
- N-1: `services/mca_exploration.py:2083` — живых вызовов нет (grep).

**Статус:** Builder T-5075+ разблокирован. Противоречий с §28/A58–A63/handoffs (mca-08/16/09/11/15/10b) не найдено; расхождение брифа («mca-10b/mca-16 могли трогать bot_persona.py») снято — не трогали.
