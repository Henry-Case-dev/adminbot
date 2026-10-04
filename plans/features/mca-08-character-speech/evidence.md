# MCA-08 `mca-08-character-speech` — evidence (Builder, блоки A+B, C+D+E)

- **Статус:** blocks A+B+C+D+E implemented + focused verification PASS;
  не коммичено, ничего не застейджено; `plans/current_task.md` не изменялся.
- **Fingerprint:** HEAD `192e229` (код-база 2.58.54) + незакоммиченный worktree:
  `services/bot_persona.py`, `services/claim_envelope.py`,
  `services/direct_chat_service.py`, `services/prompt_style_blocks.py`,
  `services/mca_gates.py`, `services/mca_events.py`,
  `services/mca_process_registry.py`, `services/database.py`,
  `services/negative_constraints.py`, `services/smartmodule_phrases.py`,
  `handlers/direct_chat.py`, `config/settings.py`,
  `tests/test_direct_chat.py`, `tests/test_mca07_retrieval_context_round1027.py`,
  `tests/test_mca01_tx_task_supervisor_round1027.py`,
  `tests/test_mca05_episodes_stories_round1027.py`,
  `tests/test_mca06_sleep_fg_round1035.py`,
  `tests/test_summary_run_store_asap41.py`,
  `tests/test_summary_source_window_asap41.py`,
  новые `tests/test_mca08_character_speech.py` (A+B) и
  `tests/test_mca08_style_form.py` (C+D+E).
  ΔDDL = **v26** (`mca_style_requests` + 2 индекса; PG no-op),
  Δкаталога = 0, `user_version` = 26 (локально проверено).
- **Granularity note:** K1–K4 все зарегистрированы; `REASON_CODES` +9/9
  израсходованы (+2 A+B clarify, +5 C style_request_*, +2 D form_guard_*);
  `_GATE_RESOLVERS` +4; реестр mca-17a — T-4910 выполнен.

## Pre-observations (до кода)

- **A:** `build_persona_prompt_block` (`bot_persona.py:203`) отдавал
  `<Persona>`-хвост; direct врезал persona-блок в
  `direct_chat_service.py:1897–1911`; verbalizer — `compose_verbalizer_system`
  (`prompt_style_blocks.py:248`), хвоста персонажа не было (риск generic-
  narrator); бюджет — `_estimate_external_payload_tokens:2697–2759`.
  Полный prompt-паритет проверялся `tests/test_direct_chat.py::TestPersonaPromptIntegration`.
- **B:** `classify_speech_act` (`claim_envelope.py:145`) существовал, но в
  ответном пути не использовался (grep: только `build_envelope`/
  `gate_personal_text_write`); quote/reply-контур mca-22 живой в
  `_build_evidence_bundle` (`_resolve_quote_live`, `bundle.quoted_speaker`).
  `SpeechUnderstanding`/носителя не было.

## Изменения (по санкции T-4892/T-4893)

- **T-4894:** `bot_persona.py`: `CHARACTER_LAYERS`/`CHARACTER_PRECEDENCE`
  (§28.4: `owner_core → owner_style → scoped_request → derived_traits →
  state`), frozen `CharacterReadContext`, `resolve_character_context(chat_id)`
  (REUSE `resolve_bot_persona` + `get_traits(limit, chat_id=None)`,
  fail-open, `traits_scope="global"` — шов mca-18). `build_persona_prompt_block`/
  `is_aware_ai`/пустая персона не менялись; сигнатуры `get_traits`/
  `resolve_bot_persona` сохранены (тест сигнатур).
- **T-4895:** `build_character_rules_block()` (канон §4); direct-хвост:
  persona → `<Character_Rules>` (только при непустом persona-блоке);
  `compose_verbalizer_system(..., character_block="")` (default → байт-паритет
  всех потребителей); System2 получает `character_block` из `handle()`;
  `_estimate_external_payload_tokens(..., extra_prompt_blocks=())` считает
  правила (K1) и speech (K2) тем же `count_tokens`.
- **T-4896:** канон `<Character_Rules>` (мнение помечается; события/люди —
  только по материалам; нет материалов → честно сказать, не выдумывать).
  Второго provenance-контура нет (REUSE mca-22 write-gates, T-4901).
- **T-4898/T-4900:** `claim_envelope.py`: frozen `SpeechUnderstanding`
  (`speech_act/quote/quote_attribution/reply_parent/short_dependency/
  humor_risk/negation/clarify/flags`), `build_speech_understanding` (REUSE
  `classify_speech_act`; наличие/автор цитаты только из уже построенного
  mca-22-контура — `bundle.quoted_speaker` или `quote:`-ambiguous-маркировка;
  повторный resolver-вызов запрещён), `render_speech_block` (`<Speech_Understanding>`,
  cap ≤500, только при активном сигнале), `clarify_action` (ask/assume/none,
  ≤1 вопрос, anti-loop по родителю-вопросу бота, команды → none).
  Канон-ветка цитаты attribution-agnostic (known/unknown — в поле/флагах
  DTO): оценка бюджета и фактический промпт строятся одной функцией и
  совпадают. Direct-врезка после Character_Rules; notable-события
  `clarification_asked`/`clarification_assumption_used` (per-reply «успехов»
  нет). M-MCA07-2-поля, CoordinatorDecision/action-schema не тронуты.
- **T-4899 (верификация):** склейка mca-22 canonical envelope/reply/quote на
  прямом пути уже рабочая; пробелов не найдено — код не расширялся.
- **T-4901 (верификация):** write-gate `gate_personal_text_write` на
  существующих контурах; конкретных gap'ов, требующих кода, не найдено
  (матрица ниже).

## Focused-команды и результаты (exit=0, без платных вызовов; PG отсутствует — fail-open)

1. `pytest tests/test_mca08_character_speech.py -q` → **52 passed**.
2. `pytest tests/test_persona_prompt.py tests/test_bot_persona.py tests/test_direct_two_call_round1022.py -q` → **45 passed** (подмножество №3 — первичная обсервация, до финального прогона).
3. `pytest tests/test_direct_chat.py tests/test_direct_chat_handlers.py tests/test_direct_chat_prompts.py tests/test_direct_two_call_round1022.py tests/test_persona_prompt.py tests/test_bot_persona.py tests/test_persona_api.py tests/test_mca22_core_round1027.py tests/test_mca22_truthset_round1027.py tests/test_mca07_retrieval_context_round1027.py tests/test_mca13_event_contract_round1027.py tests/test_mca17a_observability_core_round1027.py -q` → **552 passed**.
4. `pytest tests/test_memory_commands.py tests/test_dream_persona_traits.py tests/test_mca04a_provenance_round1027.py tests/test_direct_context_composer_asap3.py tests/test_direct_decision_matrix_asap3.py tests/test_direct_llm_decision_asap32.py -q` → **201 passed**.
5. `pytest tests/test_smoke_round1016_nostalgia_persona.py tests/test_direct_chat_concurrency.py tests/test_direct_chat_lore_inject.py tests/test_direct_chat_relations_inject.py tests/test_direct_fallback_recompose_asap32.py tests/test_direct_context_capacity_asap3.py tests/test_direct_context_scenarios_asap3.py -q` → **82 passed**.

Изменения в существующих тестах (обе — под новое ON-поведение с сохранением
OFF-паритета):
- `test_direct_chat.py::test_block_appended_to_system_prompt` — ожидание
  дополнено `<Character_Rules>` (K1 default ON); OFF-паритет — в новом тесте
  `test_k1_off_byte_parity`.
- `test_mca07...::_budget_svc._est` — фейк принимает аддитивный kwarg
  `extra_prompt_blocks` (контракт живого call-site; продукт-код не менялся).

## OFF-паритет (K1/K2)

| Проверка | Команда | Результат |
|---|---|---|
| K1 OFF: direct-промпт = `CHAT_SYSTEM_PROMPT + persona_block` (2.58.54) | (1) `test_k1_off_byte_parity` | PASS |
| K2 OFF: реплика с отрицанием → ровно `CHAT_SYSTEM_PROMPT` | (1) `test_k2_off_byte_parity` | PASS |
| Пустая персона → нет правил (паритет) | (1) `test_empty_persona_no_rules_parity` | PASS |
| verbalizer default → байт-паритет (существующий вызов) | (1) `test_verbalizer_default_parity` + (3) | PASS |
| write-gate canonical OFF → accepted (baseline) | (1) `test_gate_off_parity` | PASS |

K1/K2 прописаны в `mca_gates.KILL_SWITCHES` (default True, OFF-паритет
описан), резолверы `character_layers_enabled`/`character_speech_enabled`,
ClassVar'ы `settings` — тесты `TestKillSwitches`; Δ каталога = 0 (тест).

## T-4899 — верификация reply/quote (без нового кода)

- Переиспользовано: `test_mca07...::test_a04_different_branch_different_context_version`,
  `test_mca22_truthset...::TestRolesTruthSet` (A/B/F), `TestBundleV2`
  (`_resolve_quote_live`, ambiguous → не выдумывать).
- Новое (реальная SQLite): `test_same_question_different_parents` — одно
  «почему?» под разными родителями → разные `<Conversation_Branch>` и
  `reply_addressee` (2 vs 3), `direct_addressee='bot'` не теряется,
  `context_version` различается; `test_quote_not_attributed_to_sender` —
  `author=1`, `quoted_speaker=2` (A07). Второй identity/quote-резолвер не
  создан (структурный тест: speech-фасад не вызывает `resolve_quote`).

## T-4901 — матрица write-gate (сценарий → статус)

| Сценарий | Исход (`gate_personal_text_write`) | Источник |
|---|---|---|
| «шучу, я вчера был на Марсе» | rejected `gated_speech_act:joke_candidate` | (1) + интеграция: `remember_user_fact` → `skipped_gated`, 0 строк |
| «ну да, я великий спортсмен))» (сарказм-маркер) | rejected (joke_candidate) | (1) |
| «я не говорил, что был на встрече» | rejected `negation_guard` | (1) |
| question/hypothesis/command | rejected `gated_speech_act:*` | (1) |
| «по словам Васи, …» (цитата) | accepted; `validate_personal_write` third_party → **tentative**, не confirmed | (1) |
| гипербола «миллион раз» | accepted (детерминированный закрытый набор её не детектирует) | (1) |

Гипербола: gap не закрывался кодом осознанно — в закрытом классификаторе
mca-22 гиперболы нет, а эвристики «на глаз» противоречат принципу «не строим
несостоятельный NLP» (spec §8 G3); генерационная сторона закрыта
Character_Rules, запись — conservative-гейтами. Кандидат в
`related-nonblocking` для ревью (не блокер блока B).

## Замеченные ограничения (для ревью)

- Бюджетная оценка (`_build_user_content`/`_compose_user_content`) строится до
  EvidenceBundle: для native TG-цитаты (наличие только в bundle) фактический
  speech-блок может быть на канон-строку цитаты (≤~100 символов) длиннее
  оценки; сам блок ≤500. Текстовые цитаты (`>`, speech-act-маркеры) и прочие
  сигналы оцениваются точно (та же функция, те же входы).
- Гипербола не детектируется закрытым классификатором (см. T-4901) —
  `related-nonblocking`, код не добавлялся осознанно.

## Для Builder-2 (блоки C–E) — статус: ✅ выполнено 05.10.2026

1. Порядок direct-хвоста: persona → **Character_Rules → Style_Requests
   (K3) → Speech_Understanding (K2)** — врезка сделана в помеченном месте.
2. Verbalizer: `compose_verbalizer_system(..., style_directives="")` рядом с
   `character_block`; System2 call-site передаёт оба.
3. Бюджет: style-блок учтён в `extra_prompt_blocks` на обоих call-site'ах
   (`_build_user_content` legacy + `_compose_user_content` composer).
4. REASON_CODES: +9/9; реестр `direct.reply` (character/speech/form_guard)
   и процесс `style.scope` — T-4910 сделан.
5. `pre_migration_*` backup-guard v26 проверен локально (см. ниже).
6. DDL v26/`mca_style_requests` — реализовано; `plans/current_task.md`
   не изменялся.

---

# Блоки C+D+E (T-4903…T-4910)

## Изменения по блокам

- **T-4903 (D3–D5):** `services/mca_style_scope.py` — единственный сервис
  (парсер закрытой грамматики, права, бюджеты, CRUD, резолвер/рендер,
  команда). ΔDDL **v26** через реестр mca-14 (`_migrate_style_requests_v26`,
  `CREATE TABLE IF NOT EXISTS` + 2 индекса, self-guard, повтор — no-op,
  PG — no-op); `database.py` — только DDL/шаг. Скрытая `/style` —
  `handlers/direct_chat.py` (в `bot_commands.py` не добавлялась); канон-фразы
  `CHAT_STYLE_*` в `smartmodule_phrases.py`. Права: participant — сам;
  chat/topic — `chat_access.is_admin` ИЛИ
  `chat_lore_store.is_chat_admin`, ошибка → denied (fail-closed). Бюджеты
  ≤20/чат, ≤5/участник, ≤5/час/чат (превышение → WARNING без события).
  TTL: participant — без срока; chat 7д / topic 30д (env-only ClassVar +
  резолверы); ленивый фильтр + bounded sweep ≤5 событий. Supersede
  `(scope, scope-key, facet)`; сброс идемпотентен.
- **T-4904 (D5):** ingestion/резолв в `handle` **до** `_build_user_content`
  (принятая просьба применяется к текущему ответу), гейт addressed
  (REUSE `_decision_addressed`); блок — хвост промпта после Character_Rules
  и до Speech; `style_directives` → verbalizer; участвует в оценке бюджета.
  Смысл/адресат/факты/action-слой не тронуты; тишина/негативные реакции
  state не мутируют (нет кода, реагирующего на них).
- **T-4905 (анти-максимизация):** инварианты: единственный INSERT в
  `_apply_request`; в модуле нет `asyncio`/`create_task`/счётчиков
  ответов/конфликтов; повторные просьбы не накапливаются (supersede);
  шутки/провокации/тишина → 0 записей и 0 событий. Аудит смежных счётчиков
  direct-пути: throttle/silence_streak только снижают активность; mca-15
  (banter≠stats) не затронут; lessons (mca-16) не создаются.
- **T-4907/T-4908 (D8):** `negative_constraints.py` — frozen `FormContract`,
  G1 (`sanitize_outgoing` diff → `form_guard_leak_blocked`), G2
  (мультимножество чисел + отрицание в окне ±40, NBSP/пробелы/разделители/‘,’),
  G3 (новые имена ростера, границы слов). ≤**1** form-повтор
  (`FORM_GUARD_RETRY_SYSTEM_PROMPT`) внутри существующего бюджета (≤2
  retries; не растёт); после reject'а — `fallback_text` (санитизированный
  проверенный черновик), иначе best + `form_fallback=True`. Stats-ключи
  только при `form_contract`+K4 ON (`form_guard_rejects/_reason/form_retry/
  form_fallback`). System2: `fallback_text = strip_reasoning_tags(str(raw))`,
  событие `postprocess_form` (notable-only, reason = последний
  `form_guard_rejected|form_guard_leak_blocked` = эквивалент
  `meaning_changed` из санкции; 10-го reason-кода нет). paraphrase-модуль
  не создавался.
- **T-4910:** `mca_process_registry.py` — `direct.reply` stages
  `character/speech/form_guard` (+`speech→speech_understanding`,
  `form_guard→postprocess_form`), новый `style.scope` v1 (stages
  ingest/resolve/apply/expire, `state_source=mca_style_requests`,
  gate K3, widget «Личность/интересы», events `style_scope`);
  `_GATE_RESOLVERS` += K3/K4. `character` — read-side без per-reply
  success-события (честно в note; событие не выдумано).

## DDL v26 — локальные факты

- Свежая БД: `PRAGMA user_version = 26`; таблица `mca_style_requests` +
  `idx_mca_style_requests_active`/`idx_mca_style_requests_participant`;
  строка книги `schema_migrations` (version=26, name=`style_requests`)
  ровно одна; рестарт/повторный `initialize()` — no-op.
- Прод-путь v25→v26: `pre_migration_*.db` создан ДО применения и прошёл
  read-back (`user_version` копии = 25), затем шаг применён (тест
  `test_v25_to_v26_backup_guard_and_apply`).
- CHECK-констрейнты scope, PG — no-op (в `services/pg_db.py` нет таблицы;
  проверено источником); `user_prefs`/`chat_params`/`persona_*` не менялись.
- Пины старых фич обновлены по конвенции волн (frontier >= v25 / tail = v26):
  mca01 commit-census `database.py` 159→162, mca05 mark v26,
  mca06/summary-asap41 frontier, без ослабления проверок (см. диффы).

## Focused-команды и результаты (exit=0)

1. `pytest tests/test_mca08_style_form.py -q` → **83 passed**
   (C+D+E: DDL/backup-guard, парсер, права, приоритет/supersede/TTL/sweep/
   сброс, explicit-only/анти-максимизация, рендер, direct-врезка,
   G1–G3/≤1 повтор/fallback/stats/событие, реестр/каталог).
2. `pytest tests/test_mca08_character_speech.py -q` → **52 passed**
   (регресс A+B без изменений).
3. `pytest tests/test_negative_constraints_round1022.py
   tests/test_anticliche_round1023.py
   tests/test_verbilizer_response_modes_round1023.py -q` → **184 passed**
   (смежный постпроцессор/validator-loop; default-params stats-паритет
   сохранён строгим тестом).
4. `pytest tests/test_direct_chat.py tests/test_direct_chat_handlers.py
   tests/test_direct_chat_prompts.py tests/test_direct_two_call_round1022.py
   tests/test_verbilizer_response_modes_round1023.py -q` → **355 passed**.
5. `pytest tests/test_database.py
   tests/test_mca17a_observability_core_round1027.py
   tests/test_mca13_event_contract_round1027.py -q` → **193 passed**.
6. `pytest tests/test_mca22_core_round1027.py
   tests/test_mca22_truthset_round1027.py
   tests/test_mca07_retrieval_context_round1027.py tests/test_persona_prompt.py
   tests/test_bot_persona.py tests/test_persona_api.py
   tests/test_mca04a_provenance_round1027.py tests/test_memory_commands.py
   tests/test_dream_persona_traits.py
   tests/test_direct_context_composer_asap3.py
   tests/test_direct_decision_matrix_asap3.py
   tests/test_direct_llm_decision_asap32.py -q` → **375 passed**.
7. Миграционный фронтир (все файлы, где встречается `user_version`):
   `pytest @(<30 files>) -q` → **1115 passed** (после обновления пинов);
   отдельно mca01/mca05/mca06/summary-asap41 → **157 passed**.
8. **T-4911 интегрированный пакет** (A–D focused + смежные
   direct/persona/claim/provenance/quote/verbalizer/bounds + миграционные):
   `pytest tests/test_mca08_character_speech.py
   tests/test_mca08_style_form.py tests/test_negative_constraints_round1022.py
   tests/test_anticliche_round1023.py
   tests/test_verbilizer_response_modes_round1023.py
   tests/test_direct_chat.py tests/test_direct_chat_handlers.py
   tests/test_direct_chat_prompts.py tests/test_direct_two_call_round1022.py
   tests/test_persona_prompt.py tests/test_bot_persona.py
   tests/test_persona_api.py tests/test_mca22_core_round1027.py
   tests/test_mca22_truthset_round1027.py
   tests/test_mca07_retrieval_context_round1027.py
   tests/test_mca13_event_contract_round1027.py
   tests/test_mca17a_observability_core_round1027.py
   tests/test_mca04a_provenance_round1027.py tests/test_memory_commands.py
   tests/test_dream_persona_traits.py
   tests/test_direct_context_composer_asap3.py
   tests/test_direct_decision_matrix_asap3.py
   tests/test_direct_llm_decision_asap32.py tests/test_database.py
   tests/test_mca14_schema_additive_round1027.py
   tests/test_mca01_tx_task_supervisor_round1027.py
   tests/test_mca05_episodes_stories_round1027.py
   tests/test_mca06_sleep_fg_round1035.py
   tests/test_summary_run_store_asap41.py
   tests/test_summary_source_window_asap41.py -q` → **1344 passed, 0 failed**.
   Полный suite не гонялся (spec не требует; release policy §25148).
   JS не гонялся — UI не тронут; F8 не гонялся — Δ каталога = 0
   (тест `test_pg_no_op_and_no_catalog_delta`).

## OFF-паритет (K3/K4)

| Проверка | Где | Результат |
|---|---|---|
| K3 OFF: ingestion не пишет, резолв `""`, `/style` → None (UNHANDLED), direct-промпт = 2.58.54 | (1) `test_k3_off_byte_parity_and_no_write` | PASS |
| K3 OFF: команда неактивна + таблица не читается (0 строк) | (1) там же | PASS |
| K4 OFF: `form_contract` игнорируется, кандидат без гардов, stats без новых ключей (строгое равенство) | (1) `test_k4_off_ignores_contract_and_stats_parity` | PASS |
| K4 OFF System2: текст кандидата как есть, `postprocess_form` не эмитится | (1) `test_k4_off_no_event_and_no_new_stats` | PASS |
| Default-параметры (без `form_contract`) → точный прежний stats-dict | (1) `test_default_params_byte_parity` + (3) | PASS |
| K1/K2 OFF — паритет A+B сохранён | (2) | PASS |

## R17 / наблюдаемость

- В логи/события — только коды/ID/числа: логи `mca_style_scope` содержат
  chat/user/scope/facet/source/superseded (без label/текста/args);
  события `style_scope` — reason_code + chat/entity/message id;
  `postprocess_form` — reason_code/chat_id/attempt. Label попадает только
  в БД-условие, prompt-блок и ответ команды (данные, не журнал).
- Notable-only: per-reply success-событий read-side нет; CRUD-события
  записываются только на реальные мутации/отказы.
- Реестр T-4910 отдаёт стадии/`style.scope`/виджет-ID; K3/K4 OFF →
  честный `disabled`/`not_run` (`test_off_status_is_honest_not_run_disabled`).

## Ограничения и для ревью

- Топик-матч — детерминированный токен-матч без стемминга (spec: без LLM);
  «рыбалка» в label не матчит «рыбалку» в сообщении — осознанное ограничение
  (в сообщении должна встречаться та же словоформа).
- Команда `/style тема <label> …` трактует label как одно слово (пробелы —
  разделитель), хотя сообщение-детектор допускает multi-word label до
  директивы; закрытая грамматика, задокументировано.
- Мульти-директивная фраза («короче и без шуток») — `ambiguous_skipped`
  (одна фраза = одна просьба), одиночный повтор не эскалирует.
- Форма/смысл сверх G1–G3 детерминированно не проверяются (spec §8 —
  «не строим несостоятельный NLP»); покрытие — fallback на проверенный
  черновик + live A34.
- Гипербола по-прежнему не детектируется (carry-over блока B,
  related-nonblocking).
- Замечено предсуществующее (вне дельты): 21 leaked aiosqlite connection
  в части сторонних тест-файлов (не в mca-08/затронутых); тест-тюнинг
  `test_v25_idempotent` вызывает `_migrate_dream_runs_v25` на v26-БД и
  локально понижает маркер (prod-раннер вызывает шаги только `version >
  current`, так что прод не задет).

## R17 (итог)

В события/логи — только ID/коды/числа; секретов/сырья в evidence нет;
`plans/current_task.md` и `plans/workflow_state.md` не изменялись.
