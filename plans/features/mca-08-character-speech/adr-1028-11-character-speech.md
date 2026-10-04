# ADR-1028-11 — mca-08-character-speech: слои характера, понимание речи, scoped-просьбы и форма-only постпроцессор

- **Статус:** **Accepted** (merge `plans/ARCHITECTURE.md` §115, 05.10.2026; ратифицирован прод-валидацией 2.58.55)
- **Дата:** 05.10.2026
- **Фича:** `mca-08-character-speech` (Wave 2, эпик `memory-context-autonomy`; после mca-03/07/22/06)
- **Источник:** `plans/current_task.md:436–462` (§12); приёмки §19 (A07/A34/A42/A58–A63); границы mca-18 §28 `:1486–1607`; MCA-22 `:15383–15385`
- **Spec:** `plans/features/mca-08-character-speech/spec.md`; **Задачи:** `tasks.md` (T-4891…T-4915); **Requirements-map:** `requirements-map.md` (R1–R4, CA-08-1…10)
- **Связи:** REUSE → ADR-1014-1 (personas), ADR-1027-3 (события mca-13), ADR-1027-1 (реестр миграций mca-14), ADR-1027-8 (реестр процессов mca-17a), ADR-1028-6 (claim/quote/attribution), ADR-1028-9 AM-3 (граница ядра); границы без изменений → ADR-1026-20 (decision/action), ADR-1027-7 (EvidenceBundle/M-MCA07-2)

---

## Решения (D1–D12)

**D1. Слои характера — read-side контракт без нового хранилища и без SelfModel.** Минимальный аддитивный AMEND `services/bot_persona.py`: `CHARACTER_LAYERS=("owner_core","owner_style","derived_traits")`, `CHARACTER_PRECEDENCE` (`owner_core → owner_style → scoped_request → derived_traits → state`, §28.4), `CharacterReadContext` + `resolve_character_context(chat_id)` поверх существующих `resolve_bot_persona`/`get_traits`. `build_persona_prompt_block`, `is_aware_ai`-ветка и пустая персона не меняются (зона mca-18, A58). `traits_scope="global"` — явный шов под будущий BehaviorFrame. *Альтернативы:* (а) версионируемый SelfModelSnapshot сейчас — отклонено (mca-18, `:1517`); (б) второй prompt-сборщик — запрещён (второй механизм). **OFF (K1)** = 2.58.54.

**D2. Anti-generic и «мнение vs факт» — канон-текст в существующих точках сборки.** `<Character_Rules>` (канон в spec §4) рендерится только вместе с непустым persona-блоком; direct — хвост системного промпта (`direct_chat_service.py:1897–1911`); System2/verbalizer — новый опциональный параметр `character_block=""` у `compose_verbalizer_system` (default "" → байт-паритет всех потребителей). Режимы/оффсеты не срезают persona; budget-оценка `_estimate_external_payload_tokens` учитывает новые блоки. Второй provenance/факт-контур не создаётся (правило + REUSE mca-22 write-gates). **OFF (K1)** = 2.58.54.

**D3. Scoped-просьбы — одна аддитивная таблица v26 `mca_style_requests`.** Почему не reuse: `user_prefs.tone_preset` — только temperature-пресет без facet/срока/отзыва/темы; расширение раздваивает модель просьб; `chat_params.overrides` требует каталожного ключа (Δ каталога) и не имеет семантики просьбы/supersede/expiry; `meta` — невалидированный side-channel. `tone_preset`/`/tone` не дублируются и не мигрируются. DDL — аддитивно/идемпотентно через реестр mca-14, PG no-op, backup-guard fail-closed, rollback-safe (старый код таблицу не читает). **OFF (K3)** = 2.58.54.

**D4. Ingestion explicit-only: команда + закрытая грамматика, один writer.** Скрытая `/style` (прецедент `/tone`; в `bot_commands.py` не добавляется) + детерминированный детектор только в адресованных боту сообщениях; scope по умолчанию participant; chat/topic — admin (`chat_access.is_admin`/`chat_lore_store.is_chat_admin`, fail-closed); неоднозначное — не пишем. Молчание/реакции/шутки/провокации никогда не создают/отменяют просьбу (анти-максимизация). Бюджеты: ≤20/чат, ≤5/участник, ≤5 записей/час/чат, topic-label `[0-9a-zа-яё _-]{2,48}`. **OFF (K3)** = 2.58.54.

**D5. Приоритет/конфликты/срок/сброс.** Для каждого facet активна одна директива: **participant > topic > chat**, внутри scope — последняя; проигравшие не рендерятся (без LLM-слияния); supersede ревокает предыдущую; ядро владельца выше любой просьбы. TTL: chat 7 дней / topic 30 дней (env-only), participant — до сброса; ленивый фильтр + bounded write-time sweep. Рендер `<Style_Requests>` (канон, cap 600) в хвосте direct-промпта и через `style_directives=""` у verbalizer. **OFF (K3)** = 2.58.54.

**D6. Речевые сигналы — фасад над существующим классификатором, отдельный носитель.** `SpeechUnderstanding` + `build_speech_understanding`/`render_speech_block`/`clarify_action` в `claim_envelope.py` (REUSE `classify_speech_act`, отрицание/quote-маркеры; повторный quote-resolver вызов запрещён). Носитель — `<Speech_Understanding>` в хвосте системного промпта (только при активном сигнале; cap 500). Поля M-MCA07-2 не занимаются; `CoordinatorDecision`/action-schema не меняются; второй классификатор/бандл не создаются. **OFF (K2)** = 2.58.54.

**D7. Уточнение только при материальной неоднозначности; bounded.** `ask` = короткая зависимая реплика (закрытый маркер-набор) без reply-родителя в группе без «вопроса бота-родителя»; иначе `assume` (явное допущение) или `none`. ≤1 вопрос на ответ; anti-loop по родителю-боту; action-schema/silent не затрагиваются. **OFF (K2)** = 2.58.54.

**D8. Постпроцессор «только форма» — расширение существующего контура.** Новые опциональные `form_contract`/`fallback_text` у `verbalize_validated`; гарды G1 (утечки через diff `sanitize_outgoing`), G2 (мультимножество чисел + отрицание ±40), G3 (без новых имён ростера); reject → ≤1 повтор внутри существующего бюджета → `fallback_text` (проверенный черновик), stats-ключи, события. Отдельный paraphrase-модуль запрещён (тест mca-22 `:810–813`); `sanitize_outgoing` — неизменный egress-канон; область mca-08 — direct/System2; прочие потребители композера не меняются. **OFF (K4)** = 2.58.54.

**D9. Наблюдаемость — расширение mca-17a без шума.** AMEND `direct.reply` (stages `character/speech/form_guard` + события notable-only); новый `style.scope` (CRUD-события); `_GATE_RESOLVERS` += K1–K4; события только на санкционированные reason-коды (per-reply «успехов» нет — урок M-ASAP31-2); виджеты — существующие `"Личность/интересы"`/`"Ответы (decision/System2)"`; рендер — mca-17c.

**D10. Kill-switches — ровно 4, env-only, default ON, OFF = байт-в-бит 2.58.54.** `MCA_CHARACTER_LAYERS_ENABLED`, `MCA_CHARACTER_SPEECH_ENABLED`, `MCA_STYLE_SCOPE_ENABLED`, `MCA_POSTPROCESS_FORM_GUARD_ENABLED` (реестр `mca_gates.KILL_SWITCHES` + Settings `ClassVar`); env-only лимиты `MCA_STYLE_SCOPE_CHAT_TTL_DAYS`/`MCA_STYLE_SCOPE_TOPIC_TTL_DAYS` — не kill-switches. Δ каталога **0** (F8 NOT_APPLICABLE).

**D11. Risk R2, threat-файл не требуется.** Новых внешних контрактов/send-path/очередей нет; DDL обратима; ингест закрыт грамматикой и правами; residual-риски FM1–FM5 (spec §12) митигированы. Обязательная эскалация R2→R3 (@Architect) при: сыром свободном тексте как инструкции; chat/topic-записи без admin; смысловой потере fallback'а в ревью.

**D12. Deploy/rollback/merge.** Пер-фичевый релиз CA-11 (прецедент mca-06 AM-4): bump **2.58.54→2.58.55**, атомарная feat+docs пара, миграция v26 идемпотентно + backup-guard, health-гейт, focused-повтор, prod ff без force; rollback soft = K1–K4 OFF, cold = `git revert` (v26 аддитивна); merge §115 + ADR → Accepted. Δ DDL **v26**, Δ каталога **0**, Δ bot-команд меню **0**.

## AMEND / REUSE register

| ID | Объект | Решение | Статус | Обоснование |
|---|---|---|---|---|
| **AM-1** | ADR-1014-1 (persona storage) | **Аддитивный read-API** (`resolve_character_context`, константы слоёв) + `character_block` в verbalizer; хранилище/политика/`is_aware_ai` не меняются | Accepted | Слои нужны на read-пути сейчас; перепроектирование ядра — mca-18 |
| **AM-2** | ADR-1023-3 / ADR-1024-10 (composer narrator) | **Опциональный** параметр у `compose_verbalizer_system` (default "" → байт-паритет); каноны/оффсеты/режимы не трогаются | Accepted | Единая точка применения формы без второго сборщика; второй вызов не добавляется |
| **AM-3** | ADR-1027-1 / ADR-1027-3 (mca-14/13) | **REUSE** реестра миграций (v26) и единого словаря `REASON_CODES` (+9); kill-switch реестр mca_gates расширяется | Accepted | Первый словарь единственный; прецедент mca-06 |
| **AM-4** | ADR-1027-7 §11.2 / M-MCA07-2 (carry-over) | **Граница зафиксирована:** поля `ambiguities/unknown/contradictions` (mca-09), `persona/interests` (mca-18), `local_context` (mca-05) не занимаются; речевой сигнал — отдельный носитель | Accepted | Второй bundle и подмена владельцев полей запрещены (`mca-round1027-plan.md:320`) |
| **AM-5** | ADR-1026-20 / ADR-1026-14 (decision/action) | **Изменений нет:** `reply/react/silent/tool`, `defer`-семантика, `CoordinatorDecision` не трогаются | No-op | Граница mca-09; политика уточнения — на уровне формулировки |
| **AM-6** | ADR-1028-9 AM-3 (граница ядра характера) | **Сохраняется:** mca-08 не добавляет write-путей к ядру (`CHARACTER_CORE_WRITE_API` вне diff) | No-op | Владелец: «не менять ядро характера во время каждого сна»; mca-08 — read-side |

**Supersede register:** пусто (ни один действующий ADR не отменяется).

## Последствия и совместимость

- **Сохраняется:** сигнатуры `bot_persona` API; формат `<Persona>`/`_NO_AI_DISCLOSURE_BLOCK`; `/tone`+`user_prefs.tone_preset`; EvidenceBundle/поля M-MCA07-2; `CoordinatorDecision`/action-schema; egress-канон `sanitize_outgoing`; словарь reason-кодов единственный; каталог 488/427/463/105/103/21.
- **Меняется (только ON):** read-side слои + Character_Rules; scoped-просьбы (новая таблица/команда/резолвер); speech-блок + clarify; form-гарды/fallback у verbalize_validated (direct/System2).
- **Килл-свитчи:** K1–K4 (D10); OFF = 2.58.54.
- **Риски:** R2; failure-mode register FM1–FM5 (spec §12); эскалация R3 — D11.
- **Откат:** soft (K1–K4 OFF) → cold (`git revert`; v26 аддитивна); restore БД — аварийный сценарий.

## Прод-валидация и история

**✅ Прод-валидация 2.58.55 (VERIFIED 05.10.2026; факты — серверное UTC 04.10.2026):** прод ff `495bcf4..2a4730a` (feat `3d03ff6` 46 файлов; docs `2a4730a` 7 файлов; deploy-doc `1880b35`), рестарт 21:07:32 UTC (PID 3726880), `/healthz` 200 `2.58.55` (первый 200 21:11:29 UTC — подъём ~3 мин: pre-migration VACUUM INTO ~1.3 GB) + `/api/health` 200. **Миграция v25→v26 идемпотентно через mca-14** с fail-closed backup-guard: полка `pre_migration_20261004_210851.db` — 1315704832 B, `integrity_check` ok, копия `user_version=25` без `mca_style_requests`, read-back ok; применена ровно один раз (`user_version` 25→26, книга `schema_migrations` 14→15 строк, ряд v26 ×1, таблица `mca_style_requests` + `idx_mca_style_requests_active`/`_participant`, 0 строк, tables 99→100); **второй рестарт 21:21:10 UTC (PID 3730314) — no-op** (0 re-apply). **PG no-op** (`pg_db.py` вне diff; 26 таблиц, таблицы нет — SQLite-only по дизайну D3; counter 17 → next 18, assignments 17 / assets 13 / provenance 24 не тронуты). **Данные целы:** `task_jobs` 639→641 (live), `summary_runs` 13, `summary_source_windows` 13, `mca_events` растут живой работой. **Kill-switches:** `.env` — 0 вхождений K1–K4 → дефолты ON; TTL не заданы → 7д/30д. **Проверки:** локально новые 135 (52+83) + миграционный фронтир 315 + K3/K4 focused 4; prod-venv 135 passed (30.4 с); F8 `--check` OK **489** Δ=0; 0 ERROR/CRITICAL/Traceback (WARNING — только known pre-existing embedding rotation/SIGTERM); **R17 = 0**; review T-4912 **Approved** (binding WTH `57E036674EB08E82F6E12498EBB34B80B5E203A3B5A319A443CDD739C82B656B`, files=29). **Live-приёмка T-4914 — [PENDING OWNER]** (реальный чат, no-false-acceptance: сохранённый стиль владельца, верные адресаты, отсутствие техвставок, юмор/несогласие без потери смысла, живая scoped-просьба, шутка/сарказм ≠ биография) → затем T-4915 архив/передача. **Rollback:** soft — K1–K4 `=false` + рестарт (OFF = бит-в-бит 2.58.54; v26 аддитивна и инертна — старый код её не читает); cold — revert до `495bcf4` (2.58.54); аварийный restore — полка `pre_migration_20261004_210851.db` (процедура mca-14).

**История ревизий:** 05.10.2026 — Proposed (Step 2 @Architect, design-freeze, санкции T-4892/T-4893); 05.10.2026 — **Accepted** (merge §115 + deploy 2.58.55 VERIFIED; T-4914 live — за владельцем).
