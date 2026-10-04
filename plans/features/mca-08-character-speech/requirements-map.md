# MCA-08 `mca-08-character-speech` — requirements-map (Step 1 @PM, 05.10.2026)

Feature: **`mca-08-character-speech`** — характер и понимание речи (эпик `memory-context-autonomy`, Wave 2).
Источник: `plans/current_task.md:436–462` (§12; файл НЕ изменялся, R17). Смежные обязательные разделы: §28 MCA-18 (`:1486–1607`), §19 приёмки (`:874–976`), §20 (`:986–1045`), §21 (`:1046–1093`), MCA-22 граница (`:15305–15395`).
Планирование: волновой план `plans/docs/mca-round1027-plan.md:99–102` (REQ MCA08-R1…R4), строка фичи `:201`, порядок Wave 2 `:235`.
Нумерация задач: **T-4891+** (max занятого = T-4890, `plans/features/asap-4-4-final-live-closure/tasks.md:74`; T-4891 зарезервирован в `plans/workflow_state.md` NOTE 30 как следующий свободный).

---

## 1. Подтверждение: следующая незавершённая MCA-задача

Порядок из плана (`mca-round1027-plan.md:235`, дубль волн — `plans/backlog.md:13`):

**Wave 2 (когниция):** `mca-04b` ∥ `mca-05` ∥ `mca-06` ∥ **`mca-08`** ∥ `mca-15` ∥ `mca-11` (внутри волны — параллель по зависимостям; порядок списка — приоритетный хвост).

Фактические статусы (по `plans/backlog.md`/`plans/metrics.md`/архивам):

| Фича | Статус | Ссылка |
|---|---|---|
| `mca-04b-dossier-rebuild` | ✅ RELEASED 2.58.41 + ARCHIVED | `plans/archive/mca-04b-dossier-rebuild-round1029/` |
| `mca-05-episodes-stories` | ✅ RELEASED 2.58.42 + ARCHIVED | `plans/archive/mca-05-episodes-stories-round1029/` |
| `mca-06-sleep-paradigms` | ✅ RELEASED 2.58.49 + ARCHIVED | `plans/archive/mca-06-sleep-paradigms-round1034/` |
| **`mca-08-character-speech`** | ⏭️ **следующая незавершённая Wave 2** | `mca-round1027-plan.md:201` |
| `mca-15-chat-statistics` | не начата (dep mca-03+mca-07 — готова, но по порядку после mca-08) | `mca-round1027-plan.md:202` |
| `mca-11-tools-costs` | не начата | `mca-round1027-plan.md:203` |

Почему не другие кандидаты:

- **`mca-17c-analytics-matrix`** — Wave 5 (`mca-round1027-plan.md:213, 247`), зависит от `mca-17a` + **всех** фич; её входы/hair-over (F12/F14–F17 `mca-17a`; M-2 chain-UI amend от `mca-06`) намеренно отложены в Wave 5 и до mca-08 не стоят (`mca-06` follow-up п.1, `plans/backlog.md:185–186`). UI-виджеты mca-08 — только контрактные ID, рендер → mca-17c.
- **`mca-22`** — интеграционный эпик уже RELEASED 2.58.44 + ARCHIVED; зафиксировал границу «не переписывать personality» (`current_task.md:15383–15385`) и закрыл read-side атрибуцию; tail-ов, блокирующих mca-08, нет (его no-replay/freshness — вход для mca-08, не очередь).
- **`mca-23`** — явно заперт: «его запрещено выбирать следующей фичей после ASAP-4» и «разблокируется только когда PM подтвердил, что все предшествующие MCA production-accepted/archived» (`current_task.md:20852–20859`). Преждевременная реализация запрещена, сохранять только integration notes.
- **`mca-09-intents-initiative`** (Wave 3) зависит от mca-07/mca-08/mca-11 — mca-08 на критическом пути к автономии; дополнительные основания тянуть её вперёд нет.
- Владелец в отчёте ASAP 4.4 явно зафиксировал: «Дальше: возвращаемся к MCA — следующая по очереди `mca-08-character-speech` (Wave 2)» (`plans/features/asap-4-4-final-live-closure/owner-report.md:20`).

**Вывод:** mca-08 — корректная следующая задача. Отклонений от документированного порядка не найдено.

---

## 2. Требования владельца (§12 `current_task.md:436–462`)

Ключевая рамка (`:438`): подробный обязательный контракт личности и модели себя — **MCA-18 (§28)**; mca-08 — **развитие этого блока, не второй конкурирующий механизм**. Значит mca-08 делает применимую (pre-SelfModel) часть и обязан оставить mca-18 чистые швы.

| REQ | Требование (дословная суть из §12) | Якорь | Проверяемый критерий | Приёмки |
|---|---|---|---|---|
| **MCA08-R1** | Использовать настроенную владельцем личность и действующие стилевые требования; не подменять «универсальным вежливым помощником» (446). Разделить: стабильное ядро/стиль; изменяемые интересы; текущие состояния/настроение; отношения, основанные на событиях; факты и собственные субъективные мнения (448–454). Юмор/сленг/любопытство/несогласие допустимы; мнение без внешней ссылки допустимо; утверждение о событии/человеке — только по материалам; не выдумывать встречи/действия (456). | `:440–456` | (R1a) реплики в стиле владельца, не generic-assistant; (R1b) слои различимы на read-пути и в сборке ответа, приоритет документирован (ядро/настройка → локальное правило → динамика → состояние — порядок §28.4/`:1560`); (R1c) мнение помечено как мнение; фактическое утверждение без материалов не публикуется как факт; провокация на выдуманное событие → отказ/уточнение | A58–A63 (**совместно с mca-18**; см. §6), GEN-R9 (`mca-round1027-plan.md:33`), A42 (`:923`), A34 (`:915`) |
| **MCA08-R2** | Понимать короткие ответы через reply-ветку; уточнять только когда неоднозначность существенно меняет ответ; различать цитату, сарказм, гиперболу, отрицание и буквальное утверждение; при сомнении отражать неопределённость в памяти, а не записывать шутку как биографический факт (458). | `:458` | (R2a) «почему?» под разными родителями → разные контексты/ответы (регресс к A04, сквозь mca-22); (R2b) цитата не становится утверждением цитирующего; сарказм/гипербола не подтверждаются как биография; сомнение → tentative/unknown, не confirmed; (R2c) уточнение выдаётся только при материальной неоднозначности; иначе ответ с явной оговоркой/допущением и без петли уточнений | A07 (`:888`), A42 (`:923`), GEN-R9 |
| **MCA08-R3** | Учитывать явные просьбы по стилю и темам с областью действия: участник, чат, конкретная тема; отсутствие реакции не означает согласие или запрет; не обучать поведение на максимизацию количества ответов, конфликтов и провокаций (460). | `:460` | (R3a) явная просьба фиксируется с корректным scope и применяется только к нему; конфликт scope → документированный приоритет; сброс/истечение семантики по spec; (R3b) молчание/«не ответили» не создаёт и не отменяет разрешение; (R3c) нет кода/сигнала, который повышает активность реплик из-за числа ответов/конфликтов/провокаций | A34 (`:915`) |
| **MCA08-R4** | Постпроцессор меняет только форму, не адресата, факты, позицию или действие; технические метки/JSON/внутренние заметки не попадают в Telegram; если редактура меняет смысл — использовать проверенный исходный вариант либо повторить ограниченный этап с причиной в журнале (462). | `:462` | (R4a) fixture редактуры, меняющей адресата/число/позицию → правка отклонена; (R4b) JSON/техметки/внутренние маркеры отсутствуют в финальном тексте всех путей постобработки; (R4c) при отклонении по смыслу — исходный вариант либо ≤1 ограниченный повтор, причина видна в журнале (mca-17a-контракт) | A34 (`:915`), проверка владельца `:444` (примеры до/после) |

Проверка владельца (§12 `:442–444`): примеры до/после показывают сохранённый стиль, правильных адресатов, отсутствие технических вставок редактора; сон не переписывает личность целиком; саркастическая фраза не становится фактом.

---

## 3. Reuse-inventory (существующий код — переиспользовать, вторых механизмов не создавать)

### 3.1. Ядро/черты/состояния
- `services/bot_persona.py` — PG `personas` (`:231` pg_db; scope `is_global`+`chat_id`, name/biography/system_prompt_overrides/`is_aware_ai`) и `persona_traits` (`:260` pg_db; пишет глубокий сон): `resolve_bot_persona` (`bot_persona.py:178`), `build_persona_prompt_block` (`:203`), `get_traits` (`:292`), `append_traits` (`:462`), `record_trait_status` (`:508`), `save_persona` (`:395`), `get_persona_health` (`:325`).
- Известные разрывы, но **зона mca-18** (§28.1 `:1502–1509`): `if not lines: return ""` до обработки `is_aware_ai`; три настройки `persona_enabled`/`is_aware_ai`/`bot_self_awareness_enabled` (`:1519–1525`); SelfModelSnapshot/BehaviorFrame (`:1517, :1568–1574`). mca-08 их **не реализует** и не эскизирует; обязан не ухудшить и оставить совместимые швы (AMEND `bot_persona.py` «совместно с MCA-18» — `mca-round1027-plan.md:201`).
- Отрицательная граница ядра (mca-06 AM-3): `services/mca_dream_evidence.py:65–97` — `CHARACTER_CORE_WRITE_API` запрещён всем фоновым контурам; derived-слой (`append_traits`/`record_trait_status`) разрешён. mca-08 не создаёт новый write-путь к ядру.
- Направление mca-18 (для швов, не для реализации): разделение типов памяти/субъекта (`:1529–1546`), `TraitObservation→BehaviorRule` (`:1548–1562`), один компилятор на все пути (`:1564–1576`), legacy-разбор черт и UI (`:1578–1588`), paired replay (`:1590–1606`).

### 3.2. Стиль/тон/настроение (существующие механизмы)
- **Per-participant тон:** `user_prefs.tone_preset` (`services/database.py:4034` схема, `:7732` `get_user_tone_preset`, `:7743` `set_user_tone_preset`), команда `/tone` (`handlers/direct_chat.py:285–307`), применение в ответе (`services/direct_chat_service.py:1915–1918`, `:4917–4936`). Это готовый scoped-механизм для «участник».
- **Стилевые якоря чата:** `<style_anchors>` (`direct_chat_service.py:4772–4818`, флаг `CHAT_STYLE_ANCHORS_ENABLED`/`CHAT_STYLE_ANCHORS_COUNT`, `config/settings.py:2252–2254`) — подражание интонации прошлых ответов бота.
- **Настроение собеседника:** `<mood>` по словам-триггерам (`direct_chat_service.py:4820–4837`, `CHAT_MOOD_ENABLED`, слова — каталог `param_catalog.py:1037–1038, 1771–1773`); приоритет в сборке контекста — P2 (`services/direct_context_composer.py:53–111`).
- **Речевой профиль человека:** tool `get_user_context` purpose `speech_style` (`services/tool_router.py:1412, 1578–1647`, `tool_schemas.py:447–471`) — per-user «как человек говорит», bounded-slice + patterns, без нового хранилища (`plans/ARCHITECTURE.md:3489–3495`).
- **Композер стилевых блоков:** `services/prompt_style_blocks.py:248` `compose_verbalizer_system(base, response_mode, format, html_safe)` — режимы casual/serious/deep_research, rich/plain.

### 3.3. Понимание речи (уже реализовано, требует верификации/склейки)
- **Speech acts (mca-22):** `services/claim_envelope.py:145` `classify_speech_act` (закрытый детерминированный набор), `:309` `gate_personal_text_write` — joke/question/hypothesis/command не пишутся в личные факты; quote без источника → source unknown; negation-guard.
- **Резолвер цитат (mca-22):** `services/quote_resolver.py` (лестница 1–7, metadata-first, ambiguous не превращается в утверждение), `services/canonical_messages.py` (Canonical Message Envelope: автор/адресат/цитата/forward — цитата помечена `>` и подписана автором цитаты, `:235–262`).
- **EvidenceBundle (mca-07):** `services/mca_retrieval_context.py` — поля `quoted_speaker` (`:215`), `quote_source_ref` (`:312`), адресат/участники/неоднозначности. Внимание: carry-over M-MCA07-2 распределяет наполнение полей bundle: `ambiguities/unknown/contradictions` → mca-09, `persona/interests` → mca-18 (`mca-round1027-plan.md:320`); mca-08 не занимает чужие поля, добавляет только то, что санкционирует @Architect.
- **Свежесть/дедуп (mca-22):** `services/response_freshness.py`; запрет отдельного paraphrase-постпроцессора зафиксирован тестом `tests/test_mca22_core_round1027.py:810–813`.
- **Anti-echo self:** `plans/ARCHITECTURE.md:55, 698` — origin `bot_self_reply`, `_SELF_ECHO_INSTRUCTION`, критическое отношение к прошлым словам.

### 3.4. Постпроцессор/редактура
- `services/negative_constraints.py:342` `verbalize_validated(gen, messages, ...)` — валидация после LLM-генерации (запрещённые подстроки/фантомные ID → stats) — существующая опора R4.
- `services/direct_chat_service.py:2600–2625` — verbalizer-путь direct (режимные блоки, изоляция от tool-логов); `services/system2_handoff.py:44–74` — ключ-предохранитель композера; `services/factcheck_service.py:167–200`, `services/summary_generator.py:3288–3309` — другие потребители того же композера (единый контракт формы).
- `services/chains`/`response_freshness` — провенанс ответа (lineage, R17-safe: `tests/test_mca22_core_round1027.py:799–808`).

### 3.5. Наблюдаемость (mca-17a) и модерация
- `services/mca_process_registry.py:455–462` — процесс «Черты личности/интересы бота», widget «Личность/интересы».
- `services/mca_events.py` — единый контракт событий/reason_code (`REASON_CODES`, аддитивное расширение — прецедент mca-06).
- `services/direct_chat_service.py:890` — `CoordinatorDecision` (A7/ADR-1026-20; action/style разделены) — точка интеграции сигналов понимания речи, **не** переписывать.

---

## 4. Conflict-audit (CA-08-1…CA-08-10)

| # | Конфликт-кандидат | Существующий контракт | Действие mca-08 | Правило |
|---|---|---|---|---|
| CA-08-1 | Второй механизм личности | mca-18 §28 — «развитие данного блока, не второй конкурирующий механизм» (`:438`); mca-06 AM-3 граница ядра | Только read-side слой/швы поверх `personas`/`persona_traits`; SelfModel/BehaviorFrame/три тумблера/компилятор черт/paired replay **не** реализуются | AMEND `bot_persona.py` «совместно с mca-18» (`mca-round1027-plan.md:201`); интерфейсы совместимы |
| CA-08-2 | Второй identity/quote-контракт | mca-03 `(chat_id, tg_message_id)`, revisions; mca-22 canonical envelope + quote resolver (`:15363–15367`) | REUSE; проверка склейки коротких reply-ответов; новых резолверов нет | GEN-R19 (`mca-round1027-plan.md:43`) |
| CA-08-3 | Запись шутки как факта | mca-04a/mca-22 write-gate (`claim_envelope.gate_personal_text_write`) | Верификация + возможная аддитивная форма неопределённости (tentative/unknown), без второго provenance | `:15369–15371`, MCA04-R3/R4 (`mca-round1027-plan.md:75–76`) |
| CA-08-4 | Второй retrieval/EvidenceBundle | mca-07 bundle; M-MCA07-2 распределение полей (`mca-round1027-plan.md:320`) | Только аддитивные санкционированные сигналы; чужие поля не заполнять | второй bundle запрещён |
| CA-08-5 | Второй postprocessor | mca-22 §18: отдельный paraphrase-постпроцессор запрещён (`tests/test_mca22_core_round1027.py:810`); `verbalize_validated` существует | Расширять существующий контракт формы/валидации, не создавать перефразер | REUSE |
| CA-08-6 | Второе хранилище стиля | `user_prefs` (участник), `chat_params` (чат) уже есть | Хранилище scoped-просьб — решение @Architect (reuse vs аддитивная таблица через реестр mca-14); второй per-user профиль запрещён | ARCHITECTURE:3489–3495 |
| CA-08-7 | Пересечение с mca-09 (Decision/Intent) | Action schema `reply/react/silent/tool` (`:496`), `CoordinatorDecision` | Политика уточнения — на уровне формулировки ответа; action-schema не менять; intents — mca-09 | `:15383–15385` (не переписывать personality), mca-09 — Wave 3 |
| CA-08-8 | Пересечение с mca-15 (banter vs statistics) | A15-R1 `social_banter/historical_evidence/chat_statistics` (`mca-round1027-plan.md:135`) | mca-08 гарантирует, что подкол/шутка не форсирует отчёт; статистика — mca-15 | A42 (`:923`) |
| CA-08-9 | Публикация/витрина | mca-17a-контракт наблюдаемости; mca-17c — UI (Wave 5) | Регистрация процессов/стадий/ID виджета; рендер UI не делать | прецедент `mca-06` M-2 → mca-17c |
| CA-08-10 | Deploy-политика §20 vs практика Wave 2 | §20 «единый релиз» (`:986–1045`) vs фактические пер-фичевые релизы 2.58.41+ (CA-11 `mca-06`) | Политику фиксирует @Architect в spec (пер-фичевый bump по практике CA-11 либо DEFERRED); PM не решает | `plans/archive/mca-06-sleep-paradigms-round1034/conflict-audit.md:34` |

Сквозные запреты: R17 (секреты не журналировать/не переносить), не трогать runtime вне санкций, не изменять `plans/current_task.md` (R17/R18), не создавать второй контур отправки/инициативы, не менять фиксированные пороги/формулировки MCA-18.

---

## 5. Что уже покрыто и что реально добавляет mca-08

| Область | Уже есть (проверить, не дублировать) | Реально добавить в mca-08 |
|---|---|---|
| Ядро/стиль в ответе | persona-блок в direct (`direct_chat_service` `_cpg`), style anchors, mood, tone preset | явное разделение слоёв/приоритетов на read-пути; защита от подмены generic-помощником; швы под mca-18 |
| Цитата/сарказм/шутка (запись) | mca-22 speech acts + write-gate; quote resolver | верификация + склейка сигналов в ответный путь; «неопределённость вместо факта» как видимый статус |
| Короткие reply-ответы | mca-03 reply-связи, mca-22 canonical envelope, thread-chain Summary | регресс-доказательство на прямом пути (не только Summary) |
| Стиль со scope | участник — `/tone`; чат — chat_params; тема — **нет** | сквозная scoped-модель просьб (участник/чат/тема), explicit-only, приоритет/сброс |
| Постпроцессор формы | `verbalize_validated`, negative constraints, режимные блоки | контракт «только форма», тех-утечки, meaning-change fallback с причиной в журнале |
| Наблюдаемость | mca-17a реестр/события | регистрация стадий характера/речи/постобработки |

---

## 6. Открытые зависимости и разграничение приёмок

1. **A58–A63 — совместная зона mca-08/mca-18** (`mca-round1027-plan.md:99`). Полное закрытие (SelfModelSnapshot, три тумблера, TraitObservation→BehaviorRule, BehaviorFrame на всех путях, legacy-разбор, paired replay 30×3) — **mca-18 (Wave 4)**. mca-08 покрывает применимую pre-SelfModel часть (слои в поведении, юмор/мнение, уточнения, адресаты) и **не заявляет** их полное закрытие; в evidence фиксировать вклад.
2. **Решение @Architect (Step 2) обязательно** — дизайн затрагивает выборы, которые нельзя решить «по инерции»:
   - (a) форма read-side слоя/швов под mca-18 и минимальный AMEND `bot_persona.py` (какие поля/API, что фиксируем, что откладываем);
   - (b) хранилище и семантика scoped style/topic-просьб: reuse (`user_prefs`/`chat_params`) vs аддитивная таблица через реестр `mca-14` (Δ DDL v26±), explicit-only, приоритет/конфликт, истечение/сброс, UI (нужен ли; каталог);
   - (c) какие детерминированные сигналы речи попадают в ответный путь и в какой носитель (аддитивно; не занимать поля, закреплённые M-MCA07-2 за mca-09/mca-18);
   - (d) политика уточнения (материальность неоднозначности) без изменения action-schema mca-09;
   - (e) контракт «только форма» и meaning-change fallback (≤1 повтор, reason_code);
   - (f) kill-switches (env-only default ON, OFF = бит-в-бит), Δ каталога/переиздание F8, Risk (предв. R2) и необходимость `threat-failure-analysis.md`;
   - (g) deploy-политика (CA-11) и bump; backup-guard при Δ DDL.
3. **Живые примеры владельца** (§12 `:442–444`) — реальный чат; до/после и адресаты. Без owner-примеров live-часть помечать `PENDING OWNER`, не имитировать (no-false-acceptance, прецедент `:15167`/ASAP 4.4).
4. **Фон mca-06/mca-05** (live deep sleep, episodes pool = 0) — не блокеры mca-08; не смешивать статусы.
5. **mca-17c** получает от mca-08 только контрактные ID стадий/виджета; UI — Wave 5.
6. **mca-09/mca-10b/mca-15** — потребители результатов mca-08 (стиль/форма участия/banter); handoff-заметки обязательны в reconcile.

---

## 7. Out of scope (явно)

- SelfModel/BehaviorFrame, три настройки (`persona_enabled`/`is_aware_ai`/`bot_self_awareness_enabled`), компилятор черт, legacy `persona_traits` UI, paired replay — **mca-18**.
- Intent/Decision lifecycle, `defer`-семантика — **mca-09**; статистика/`MetricResult` — **mca-15**; рандомизация формы участия — **mca-10b**; experience/lessons — **mca-16**.
- Вторые: identity/provenance/retrieval/bundle/postprocessor/личность/очередь/аналитика.
- Рендер виджетов и диагностических действий — **mca-17c**; гайды — **mca-21**.

---

## 8. Маппинг «REQ → приёмки → задачи»

| REQ | Приёмки | Задачи tasks.md |
|---|---|---|
| MCA08-R1 | A58–A63 (частично, совместно с mca-18), A34, GEN-R9 | T-4894…T-4897 |
| MCA08-R2 | A07, A42, GEN-R9 | T-4898…T-4902 |
| MCA08-R3 | A34 | T-4903…T-4906 |
| MCA08-R4 | A34, проверка владельца `:444` | T-4907…T-4909 |
| Наблюдаемость (GEN-R17/MCA-17) | A48, A73 (контрактная часть) | T-4910 |
| Сводная проверка/ревью | §19 `:874–976`, §21 | T-4911…T-4912 |
| Deploy/live/reconcile | §20 `:986–1045`, no-false-acceptance `:15167` | T-4913…T-4915 |

**Статус документа:** `PLANNING_CONSISTENT` — при условии санкций @Architect (T-4892/T-4893) по пунктам §6.2. Код на шаге PM не менялся; `plans/current_task.md` не изменялся.
