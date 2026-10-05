# ADR-1028-18 — SelfModel: действующая личность, модель себя и применение памяти к поведению (`mca-18-self-model`)

- **Статус:** Proposed (→ Accepted по merge `plans/ARCHITECTURE.md` §122+ и прод-валидации, прецедент волновых ADR)
- **Дата:** 06.10.2026 · **Автор:** @Architect (Step 2, T-5073) · **Фича:** `mca-18-self-model` (эпик `memory-context-autonomy`, Wave 4, Risk **R3**)
- **Требования:** §28 `plans/current_task.md:1486–1606`; приёмки A58–A63 `:939–944`; GEN-R17 `:1364`, GEN-R18 `:43`
- **Baseline:** HEAD `23cb2a1`, прод 2.58.61, SQLite v30, ADR-1028-17 (последний занят — grep 06.10.2026)

## 1. Контекст

Черты характера существуют как текст-список (`persona_traits`), включаются в `<Persona>` без условий/конфликтов/степени; `if not lines: return ""` срабатывает до `is_aware_ai`; `is_aware_ai=True` не даёт положительной тех-идентичности; `get_traits` без chat_id; ошибки чтения self-фактов превращаются в пустые списки; `bot_self_awareness_enabled` путается с `is_aware_ai` (§28.1 `:1494–1512`). mca-08 (ADR-1028-11) оставила швы (`traits_scope`, слои `derived_traits`/`state`) именно под эту фичу; полное закрытие A58–A63 — здесь (`backlog.md:207`).

## 2. Решения

**D1 — SelfModelSnapshot в существующем контуре.** Frozen-dataclass в новом модуле `services/mca_self_model.py` (без отдельного сервиса/провайдера; `direct_chat_service` не растёт — `:1568`). Поля §28.2 `:1517`: agent_id (стабильный UUID, таблица `mca_self_identity` v31; rebind Telegram-аккаунта — явное действие), bot_user_id, persona_id/persona_version (хеш содержимого PG-строки; смена модели/токена НЕ создаёт новую личность — R2d), scope_chat_id, имя/алиасы с периодами (REUSE mca-03), биография, style_version, черты/интересы/отношения, состояние (mood + TTL), позиции с provenance, режим самопредставления, capabilities/limits (из реестра инструментов/runtime, не из биографии — `:1527`). Один snapshot на запуск; version — в trace.

**D2 — Три независимые настройки.** `persona_enabled` — новый ключ `flags.persona_enabled` (механизм `chat_params.get_chat_param`, прецедент `direct_chat_service.py:4856–4861`; OFF ≠ отмена авторства/тех-идентичности/атрибуции); `is_aware_ai` — без изменения хранения (PG `personas`, global+chat, наследование существующим резолвом); `bot_self_awareness_enabled` — существующий flags-путь + UI-пояснение «Рефлексия собственных ответов». `False` / `null-наследовать` / `ошибка загрузки` — три разных состояния; effective + источник наследования в UI. Существующие ключи/API не инвертируются (`:1525`).

**D3 — Одна точка сборки.** Единственное место разрешения конфликта «старый промпт-запрет vs True» — `build_persona_prompt_block` (`services/bot_persona.py:237`). Мастер-гейт ON → рендер из BehaviorFrame; формулировка False **заменяет** `_NO_AI_DISCLOSURE_BLOCK` (`:32`, врезка `:272`) — без противоположных указаний в конец. Вставка в любые пути — только через швы mca-08 (`<Character_Rules>`/`character_block`); `form_contract` не трогается; нового слоя промпта нет (CA-18-1/4).

**D4 — Расширение единого контракта памяти (AMEND mca-03/04a, не копия графа).** На `graph_facts` + provenance v17 аддитивно: `subject_entity_id`, `speaker_entity_id`, `perspective` (self/other/quoted/third_party/ambiguous), `memory_kind` (world_fact/self_event/self_trait/opinion/belief/paradigm/mood/lesson), `scope`, `valid_from/valid_to`, `confidence_basis`, `revision`; REUSE `status`/`supersedes`/`weight`/`mca_source_refs`/`mca_evidence_links`. `self` — по стабильному agent_id; «я» в цитате → автор цитаты; «бот» без референта → ambiguous (характер не меняет); автор пересылки/поста/изображённый — разные роли. `mca_adoption_links` — связь принятия мнения с основаниями/временем; «в чате принято X» ≠ «я предпочитаю X». Таблица запретов `:1535–1544` enforced кодом + негативными тестами.

**D5 — TraitObservation → BehaviorRule (v31-таблицы SQLite).** Стадии observed→candidate→active/rejected/suspended/superseded; авто-валидация (субъект/источник/конфликт с ядром/допустимое влияние) без ручного одобрения каждого; 8 начальных dimensions; новое имя dimension от LLM → candidate с причиной (исполняемый код не создаётся). Конфликты разрешаются ДО генерации в порядке `CHARACTER_PRECEDENCE` (`bot_persona.py:44–46`) — не менять. Анти-самоусиление: ответы под чертой помечены rule version/id (mca-22 `mca_bot_outputs` — не независимое подтверждение); дедуп по исходным событиям; шаг ≤0.1/цикл, ≤0.2/24 ч (env-only инженерные дефолты, GEN-R27); ослабление допускается; TTL настроения 6 ч. `quality_regression` → наблюдение в mca-16, никогда не правило «менее полезные ответы» (CA-18-2). Lesson ≠ trait ≠ парадигма ≠ style request — границы в коде/тестах (CA-18-2/3).

**D6 — Один компилятор.** `resolve_self_model(scope)` → `select_behavior(snapshot, EvidenceBundle)` → `BehaviorFrame` (детерминированная сериализация структурированных данных во 2-м лице; сырые тексты памяти НЕ системные инструкции — GEN-R18 `:43`, CA-18-4). Frame подаётся аддитивно в decision/direct/autonomous/synthesis/verbalizer/postprocessor; тех-вызовы без стиля; фактчек — вердикт → стиль. Второй bundle запрещён; `CoordinatorDecision` — аддитивное поле, enum mca-09 не меняется (CA-18-7).

**D7 — Кеш и деградация.** Ключи кеша: `persona_version` + `rules_version` + `flags_revision` (прецедент `mca_retrieval_context.py:257`; carry-over M-MCA07-2 → mca-18). Настройки действуют со следующего запуска; in-flight версия в trace (без смеси личностей). PG недоступен → last-known-good со stale-маркером либо минимальная тех-идентичность; честные reason-коды; тихий ON запрещён; OFF = бит-в-бит 2.58.61 (CA-18-9).

**D8 — Legacy-черты.** Фоновый идемпотентный разбор `persona_traits` (job mca-01 `task_jobs`, kind=`legacy_traits_parse`): original ID/text/source/chat/time; source_refs по mca-04a без фабрикации; без субъекта → candidate/`legacy_unverified`; подтверждённые — сразу; ручная черта — основание = действие владельца; повтор = no-op; FIFO не удаляет активное состояние/provenance; chat→global — явное правило + обезличивание. UI — в существующих разделах (редактор/витрина/«Память»/компакт «Аналитики»), без нового маршрута (CA-18-8); фуннель — mca-17c.

**D9 — Граница N-1 mca-10b (CA-18-6).** `select_memory_recall_candidates` (`mca_exploration.py:2083`) живым путём НЕ подключается в mca-18: селектор воспоминаний ≠ компилятор поведения; остаётся disclosed backlog-пунктом mca-10b (`backlog.md:289`). Случайность не рандомизирует черты/истинность (`:1569`-рамка).

**D10 — Наблюдаемость (GEN-R17).** Процесс `self.model` v1 в реестре mca-17a (code-declared); 8 стадий §28.6 (`observation_read`…`final_check`); included/excluded/conflict/stale + frame version; widget-ID — контракт mca-17c; OFF → честный `disabled/not_run`.

## 3. Регистр SUPERSEDE / AMEND

| Отношение | ADR | Что именно |
|---|---|---|
| **AMEND** | ADR-1028-11 (mca-08 character speech) | слои `derived_traits`/`state` наполняются BehaviorFrame; шов `traits_scope` потреблён; `<Character_Rules>`/`character_block` остаются единственными точками врезки; `_NO_AI_DISCLOSURE_BLOCK` заменяется в одной точке сборки (D3); precedence не меняется |
| **AMEND** | ADR-1027-4 (mca-03 message identity) | память получает subject/speaker/perspective поверх стабильных ID/ролей; второй контракт идентичности не создаётся; алиасы/роли REUSE |
| **AMEND** | ADR-1027-6 (mca-04a provenance) | memory_kind/scope/validity/confidence/revision над SourceRef/EvidenceLink; reuse `status`/`supersedes`/`weight` (семантика документирована в spec §3); source_refs без фабрикации |
| **AMEND** | ADR-1028-15 (mca-16 lessons) | lesson ≠ trait; `quality_regression` → `mca_experience`, не BehaviorRule |
| Не затрагивается | ADR-1026-20 (A7 decision policy) | frame — аддитивный вход в Decision; policy-классы не меняются (AMEND A7 уже сделан mca-09 в ADR-1028-16) |
| Не затрагивается | ADR-1028-16 (mca-09) | `CoordinatorDecision` — аддитивное поле, enum/action-schema целы |
| Не затрагивается | ADR-1028-17 (mca-10b) | N-1 граница зафиксирована (D9), wiring не выполняется |
| SUPERSEDE | — | ничего; предыдущие решения не заменяются |

## 4. Δ DDL / Δ каталога / kill-switches / reason_code / deploy

- **Δ DDL SQLite = v31** (одна аддитивная миграция через реестр mca-14 + backup-guard; точные объекты — spec §8.1: `mca_self_identity`, `mca_trait_observations`, `mca_behavior_rules`, `mca_adoption_links`, +9 колонок `graph_facts`, 4 индекса). **Δ PG-DDL = 0.** Бронь в arch-frames зафиксирована.
- **Δ каталога = 0** (errata 06.10.2026: исходная санкция «+1 `flags.persona_enabled`» отозвана @Architect — ключ уже существует как pg_key параметра `PERSONA_ENABLED`, `param_catalog.py:1182`; дубликат ломает инвариант F8; настройка уже owner-manageable, F8 НЕ переиздаётся). Пороги/kill-switches — env-only, Δ=0.
- **Kill-switches ровно 3** (default ON, OFF = паритет 2.58.61): `MCA_SELF_MODEL_ENABLED`, `MCA_TRAIT_RULES_ENABLED`, `MCA_LEGACY_TRAITS_MIGRATION_ENABLED` (реестр `mca_gates.py` 73→76).
- **reason_code +10** (247→257) в единственный словарь `mca_events.py` (список — spec §8.4).
- **Deploy: пер-фичевый bump 2.58.62** (CA-11; прецедент mca-15/16/09/10b), не `DEFERRED_TO_RELEASE`. Rollback: soft — 3 рубильника + рестарт; cold — `git revert` (v31 аддитивна, старый код новые объекты не читает); restore — аварийный.
- **Риск R3 подтверждён;** `threat-failure-analysis.md` обязателен и выпущен (папка фичи).

## 5. Последствия / отказы

Позитив: один контракт характера для всех путей; честные состояния настроек; память различает субъект/перспективу; черты версионируемы с provenance; самоусиление ограничено конструктивно.
Негатив/цена: +1 модуль и 4 таблицы; двойной путь сборки до конца Wave-4 (OFF-паритет требует содержать legacy-ветку `build_persona_prompt_block` — снос legacy-ветки возможен только отдельным решением после live-приёмки); replay стоит генераций (учёт mca-11).
Отказы: PG down → stale/минимальная идентичность с reason-кодом (никогда не «успешная персона»); ошибка чтения self-фактов → событие/статус, не пустой список (T-5087); неоднозначная атрибуция → ambiguous/candidate, характер не меняется.

## 6. Верификация (пропорциональна R3)

Контрактные тесты §28.7 (100%, блокер) → paired replay 30×≥3 (направленный эффект, рубрика до прогона, слепой оценщик, без рабочего чата) → широкая регрессия только в Block H с OFF-паритетом. Автоматическая оценка — вспомогательная; «передано» ≠ «проявилось» ≠ «доказан эффект».
