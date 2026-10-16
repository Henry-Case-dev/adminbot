# SOUL-1 / W2 — отчёт Builder'а: единый Prompt Composer (флаг-gated, паритет OFF)

- **Lane:** W2-COMPOSER (writer). **Join barrier:** JB-2 → разблокирует W3/W4/W6.
- **Кандидат (worktree, без коммита):** master `50a7e689` + рабочее дерево 2026-10-16.
  `sha256_12`: `prompt_composer.py`=`44D2780B04E7`, `direct_chat_service.py`=`701B6C8C2B70`,
  `mca_gates.py`=`2DA5986D8CCD`, `prompt_style_blocks.py`=`A62AB337A2D6`.
- **Контракт:** `design-composer-contract.md` (§2 API, §3 уровни, §4 точка инъекции
  Core, §5 приоритеты, §6/§8 швы), `design-source-of-truth.md` (R5/R6, §6 флаги, §7 границы).

## 1. Что реализовано (файл:строки)

### 1.1 Новый владелец сборки — `services/prompt_composer.py` (новый, 1454 строки)

| Что | Строки |
|---|---|
| Таксономия слоёв (11), закрытые наборы `LAYERS/OWNERS/SOURCES/SKIP_REASONS`, профили §2.2 | 33–176 |
| Оценщик токенов (тот же, что в Experience: 4 симв. ≈ токен), хеши, нормализация для детекта дубля | 180–230 |
| Типизированный вход: `Block, CoreRef, IdentityRef, SelfModelRef, PlanRef, StylePolicyRef, ExpressionSettings, HumorStrategy, LessonRef, SampleRef, GateState, PromptPlan` | 236–432 |
| Выход: `LayerTrace, ConflictRecord, PromptManifest` (+ `manifest_id = sha256(system｜user｜versions)[:16]`) | 434–475 |
| Резолв осей: `gates_from_config`, `resolve_gates` (env AND catalog, per-chat) | 460–540 |
| Аксессоры сущностей (read-only): `resolve_core_ref` (`character.core`, chat→global, видимый источник, compact/full, версии), `resolve_style_policy_ref` (`style.policy`, короткий hint soft-правил) | 554–720 |
| Per-turn snapshot: `pin_turn_refs` (merge по слоям), `identity_from_text`, `turn_snapshot`, `recall_turn_refs` | 722–805 |
| Провенанс базы (`resolve_base_source`), `PlanRef` из ResponsePlan (extent значением, без алиасов) | 805–845 |
| **Сборка `compose_prompt`** (никогда не бросает), порядок 11 слоёв, единая инъекция Core, сворачивание дубля owner-характера, аддитивный бюджет, `compose_machine_system` | 890–1520 |
| **«Покажи effective layers»** `render_effective_layers` (+ diff по `manifest_id`), **R17-safe** `manifest_for_events` | 1516–1600 |
| Notable-события деградации `emit_layer_events` (dedup на (chat, layer, reason), без текста промпта) | 1602–1655 |

### 1.2 Интеграция (композер = единственный владелец сборки при ON)

| Точка (§4) | Файл:строки | Что делает |
|---|---|---|
| 1. Хвост tool-phase | `direct_chat_service.py:2364–2369` (оси+база), `2713–2755` (сборка) | при ON `system` собирает композер из тех же блоков; OFF — прежние инкрементальные джойны байт-в-байт |
| 2. L2 Writer | `direct_chat_service.py:3995–4040` (`_compose_speech_system`), `4099–4150` | профиль `speech_plain`, writer `l2_writer`; user-часть строится как раньше и передаётся как защищённая |
| 3. System2 Stage-2 | `direct_chat_service.py:4309–4340` | тот же композер, writer `system2_stage2`, одинаковая ревизия личности с L2 |
| 4. System2 Stage-1 | `direct_chat_service.py:4267–4276` | `machine_json`: только канал-контракт (байты канона) |
| 5. Direct L1 / Initiative L1 | `direct_chat_service.py:3712–3717`, `7767–7772` | `machine_json` без Core/юмора |
| 6. Initiative Writer | `direct_chat_service.py` (`generate_initiative_reply`, `writer="initiative_writer"`) | тот же `_l2_write_answer` |
| Резолвер осей | `services/direct_chat_service.py:499–514` | OFF-путь: одно чтение env-оси, нулевые обращения к `chat_params` |

### 1.3 Низкоуровневый рендерер — без второго владельца

`services/prompt_style_blocks.py:268–292` — новый `resolve_mode_parts(...)` (режим/дефолт/
overrides/extent), `compose_verbalizer_system` собран поверх него **байт-в-байт** и остаётся
низкоуровневым рендерером базы/режима/формата. `STYLE_BLOCKS_SUFFIX` не копируется
(композер трактует склеенные каноны как `channel_contract`).

### 1.4 Флаги — `services/mca_gates.py:502–545`, `2193–2306`

`W2_GATES`: `UNIFIED_COMPOSER_ENABLED` (**default OFF** — фича включается владельцем),
`CHARACTER_CORE_ENABLED`, `SPEECH_STYLE_POLICY_ENABLED` (ON), `HUMOR_LIBRARY_ENABLED`,
`HUMOR_FEEDBACK_ENABLED` (OFF) — форма «имя → (default, OFF-паритет)», резолв per-call,
`effective = env AND каталоговый тумблер` (per-chat через `chat_params`).
Плюс `composer_additive_budget_tokens()` (env `COMPOSER_LAYER_BUDGET_TOKENS`, default 1200).

**Сознательное отклонение:** оси живут в `W2_GATES`, а **не** в `KILL_SWITCHES`, потому что
`KILL_SWITCHES` связан 1:1 с `module_registry.MODULE_ENV_GATES` тремя существующими тестами,
а `services/module_registry.py` и каталог `flags.*` — вне WRITE_SCOPE этого слайса (их ведёт
слайс регистрации). Env-половины читаются из `settings`, а до появления атрибутов — из
окружения, поэтому оси работают без правки `config/settings.py`.

## 2. Пример манифеста реального Direct-сценария

Артефакт: `evidence/w2/manifest-direct-l2.{json,txt}` (генератор — `evidence/w2/dump_manifest_direct_l2.py`,
офлайн, без Telegram/LLM/БД). Тот же ход, две стадии — сжатая выжимка L2 Writer:

```
## l2_writer: system chars=2520 sha12=696324bf5f9d tokens_total=630 manifest_id=c2146e40b6b27465
layer               rendered  source      revision        chars  tok  skip_reason
channel_contract    True      default     39a7cce1523e     1690  423
core                True      global      r7.ac206fe822a2   273   69
identity            True      chat        44d962217014a041   94   24
self_model_traits   False     code                           0    0  self_model_folded_into_identity
context_lessons     True      participant 967168fb043a       56   14   (<Style_Requests>)
context_lessons     True      chat        3ee71340094e       58   15   (<Verified_Lessons>)
context_lessons     True      code        2f9d2b031b87       57   15   (<Speech_Understanding>)
response_plan       True      code        2579eaeb36dc      211   53
expression          False     global                         0    0  expression_absent
humor_craft         False     code                           0    0  humor_no_strategy
few_shot            False     code                           0    0  samples_disabled
style_policy_hint   True      global      r12.032d748a43d7   67   17
channel_output      False     code                           0    0  channel_output_not_required
versions: core r7.ac206fe822a2 | style_policy r12.032d748a43d7 | identity 44d962217014a041 |
          lessons 828db8cf0df3 | response_plan 2579eaeb36dc | channel speech_plain/plain/text/…
order_matches_canonical: True
shared identity version (tool-phase | l2_writer): 44d962217014a041 | 44d962217014a041
```

Читается как контракт: Core ровно один и стоит между каналом и личностью; `identity`
имеет **одну** ревизию на оба вызова хода (SOUL-03.6); у каждого пропуска — названная
причина из закрытого набора (SOUL-15.7); вопрос/инструкция/evidence не тронуты.

## 3. Доказательства приёмки

### 3.1 Байт-паритет OFF (шов 2) — `evidence/w2/parity-off.txt`

`tests/test_soul1_composer_parity_off.py` (11 тестов) прогоняет **реальные** методы
(`_l2_write_answer`, `_synthesize_direct_answer`, `_plan_direct_l1`) ровно в условиях дампа
(PG down → код-каноны) и сверяет `chars + sha256_12` с **артефактом**
`evidence/direct-runtime-assembly.txt` (хеши читаются из файла, не из констант теста):

```
test_p1_l2_writer_detailed_matches_recorded_dump          PASSED  (2088 / 6dc4aafa6167, user 5bbb2c1c44e7)
test_p2_l2_writer_micro_matches_recorded_dump             PASSED  (1936 / abd6cc49be6c, user e9cd60e6a92e)
test_p3_modes_off_matches_recorded_dump                   PASSED  (1289 / 18af54a36e67)
test_p4_l1_planner_system_matches_recorded_dump           PASSED  (2423 / 99a207313889)
test_p5_system2_stage1_and_stage2_match_recorded_dump      PASSED  (1107 / 6bae7eb26bc3; 2088 / 6dc4aafa6167)
test_off_path_is_default_and_does_not_consult_composer     PASSED  (compose_prompt=sabotage → байты прежние)
test_tool_phase_on_equals_legacy_tail_without_new_layers   PASSED  (ON без новых слоёв == легаси-склейка)
test_l2_on_keeps_block_set_and_applies_designed_order      PASSED  (набор блоков тот же, порядок §3)
test_l2_on_without_plan_keeps_mode_block                   PASSED  (нет плана → MODE-блок, байт-в-байт)
test_tool_phase_on_and_off_scrub_identically_on_longform   PASSED  (единый проход скраба на финальной сборке)
```

Итог `[A]`: **52 passed** (layers 12, parity 11, core-version 5, legacy-custom 5,
flags 13, machine 6), см. `evidence/w2/focused-suites.txt`.

### 3.2 Тесты W2 — `evidence/w2/focused-suites.txt` (блок [A], итог 52 passed)

`52 passed` в шести файлах: `test_soul1_composer_layers.py` (12, включая негативные:
дубль owner-характера и `one_word` → `conflict_reported` с провенансом; ошибка источника →
`skip_reason`+событие; бюджет не вытесняет вопрос/evidence; нет текста промпта в событиях;
дедуп событий), `test_soul1_composer_parity_off.py` (11),
`test_soul1_core_version_propagation.py` (5:
hot apply, два чата, in-flight snapshot, одна ревизия личности на ход),
`test_soul1_legacy_custom_preserved.py` (5: read-only аксессоры, байт-в-байт кастом,
нормализация не задваивается), `test_soul1_flags_composition.py` (13: 10 функций + параметризация; таблица истинности,
OFF-ветки = паритет+причина, `humor_feedback=false` не ломает речь, 0 доп. LLM-вызовов),
`test_soul1_machine_profile_no_core.py` (6: machine_json = канал-контракт; L1/Stage-1 на
реальных методах дают тот же канон и то же число LLM-вызовов, что OFF; eligibility
`editorial_report`/`internal_silent`). Итог W2: **52 passed** (см. `[A]`).

TEST-LIFECYCLE: все новые тесты — `CONTRACT owner=SOUL-1/W2` (шапки файлов).

### 3.3 Затронутые существующие сьюты — `evidence/w2/focused-suites.txt`

```
[B] Direct/L1/L2 + style-blocks + persona + реестр mca_gates: 432 passed
[C] character/SelfModel/mca-08/источниковые пины:            200 passed
```

Имена: `test_direct_chat_prompts.py`, `test_verbilizer_response_modes_round1023.py`,
`test_asap7_direct_l1.py`, `test_direct_two_call_round1022.py`, `test_asap8_v6_wc_direct_d03.py`,
`test_asap8_v6_wc_direct_d04.py`, `test_asap8_v6_wc_direct_matrix.py`, `test_persona_prompt.py`,
`test_direct_chat.py`, `test_asap7_module_registry.py`, `test_asap7_module_completeness.py`,
`test_asap8_v6_p1_d11_registry.py`, `test_mca08_character_speech.py`, `test_mca08_style_form.py`,
`test_mca18_contract_round1042.py`, `test_mca18_self_model_block_a_round1042.py`,
`test_mca18_paired_replay_round1042.py`, `test_asap8_f4_prompt_truth.py`, `test_webapp_dm_ui.py`.

**Не мои падения:** 3 теста на счётчиках каталога (`test_unified_image_request_round1026.py::
TestBoundsA3::test_catalog_counts_unchanged`, `test_ui_verbilizer_tabs_round1023.py::TestCatalogDelta`)
падают от незакоммиченного diff'а соседнего слайса в `services/param_catalog.py` (+1 ключ
`prompts.direct_l1_planner_system_prompt` → 571→572, 24→25). Доказано эмпирически на чистом
HEAD без кода W2 (`evidence/w2/catalog-count-failures-are-not-w2.txt`): те же три теста падают.

## 4. Что теперь разблокировано для W3 (JB-2)

1. **Слой `style_policy_hint` и `versions.style_policy`** — W3 отдаёт снимок
   `effective_style_policy` через `PlanRef`/`StylePolicyRef`; аксессор W2 (`resolve_style_policy_ref`)
   читает `style.policy` (global/chat) и рендерит короткий hint — W3 заменяет источник hint на
   типизированные правила.
2. **Единый пост-проход**: композер владеет сборкой, W3 — нормализацией. Порядок в рантайме
   зафиксирован: композер → `scrub_for_plan` (существующий владелец) → `verbalize_validated` →
   `sanitize_outgoing`; оба Stage-2 и tool-phase приведены к одному решению (скраб не гейтится
   режимами) и покрыты тестами идемпотентности.
3. **`one_word`**: `PlanRef.extent` переносит значение строкой; при отсутствии в `EXTENTS`
   манифест отдаёт `conflict=one_word_not_supported` (`conflict_reported`, провенанс `plan:<sha12>`).
   Тест: `test_soul1_composer_layers.py::test_one_word_extent_is_not_lost_and_reports_conflict`.
4. **Инспектор (W6)**: `get_manifest(chat_id, run_id=…, writer=…)` + `render_effective_layers`
   (порядок/источник/ревизия/причины/Σ токенов/diff) — публичный API без сырого текста.
5. **W4**: слоты `HumorStrategy`/`SampleRef`/`humor_library_enabled` готовы; W2 ничего не
   рендерит в этих слоях, кроме полученного текста.

## 5. Чего W2 сознательно НЕ сделал

1. **`mca_self_model`-хеши (шов 1)** — Core-ревизия пока **не** входит в
   `persona_version_hash`/`_snapshot_version` (`services/mca_self_model.py:378–411`): файл вне
   WRITE_SCOPE этого слайса. Ревизия Core прослеживается в манифесте (`versions.core`,
   `manifest_id`, diff), но для «snapshot/провайдер-трасса показывает новую личность»
   нужна правка одного места в `mca_self_model` (+ повторить её в `_flags_revision`-стиле).
   **Требуется решение Orchestrator: расширить scope или отдельный мини-слайс.** SOUL-15.5
   в части «правка Core действует со следующего ответа» закрыта (тесты hot apply/in-flight).
2. **Пять независимых семейств** (factcheck/search/web/youtube/checkup/summary) не переведены
   на композер: их файлы вне WRITE_SCOPE. Профили (`machine_json`, `speech_plain`,
   `channel_text_only`, `editorial_report`, `internal_silent`) и правила eligibility
   реализованы и покрыты тестами — подключение точек = отдельный слайс.
3. **Каталог `flags.*` + `module_registry` + UI** — отдельный слайс (см. §1.4).
4. **SOUL-15.2 (per-chat vs global у 4 «тихих» рубильников)** — не правил: правка требует
   `param_catalog.py` (вне scope). Новые оси W2 читаются per-chat корректно.
5. **`_compose_speech_system` берёт базы/блоки из вызывающего** — композер не резолвит
   персону/уроки/политику сам (никаких вторых владельцев, никаких лишних I/O).

## 6. Остаточный риск

* ON-путь меняет **порядок** блоков на L2/Stage-2 (extent после личности/lessons — как требует
  §3 «порядок рендера = порядок приоритета»); состав блоков тот же, тест на набор. Это
  осознанное изменение контракта и оно недостижимо в проде до включения флага (default OFF).
* Деградации наблюдаемы событиями `prompt_layers` (outcome `skipped/silent/failed`,
  `status=<layer>:<reason>`, dedup на процесс) — при выключенном `MCA_EVENT_CONTRACT_ENABLED`
  события остаются только структурным логом (существующая политика).
* Core-документ в проде ещё не создан (ключ не в каталоге): до появления владельческого
  текста честная причина — `core_absent` (не «тихая» подмена).

## Fix pass (review-w2 F1–F3 + Core budget) — 2026-10-16

Правки по списку ревью применены точечно; архитектура/порядок слоёв/дефолты флагов не тронуты.
Кандидат — то же рабочее дерево без коммита, sha256_12 ПОСЛЕ правок:
`prompt_composer.py=426D93014FC9`, `direct_chat_service.py=D603E00DB241`,
`mca_gates.py=2DA5986D8CCD`, `prompt_style_blocks.py=A62AB337A2D6`;
тесты: `parity_off=33C0D128B3A4`, `layers=296BE6D5F300`, `legacy_custom=13801A5FCB88`.
(Ссылки §1.2 на строки `direct_chat_service.py` — на ревизию ДО правок; после 4074 нумерация сдвинута на +8.)

| Finding | Статус | Правка (файл:строка) |
|---|---|---|
| F2 (blocker) | исправлено | `direct_chat_service.py:4087–4115` — резолв осей до сборки user-части, `if not _c_on:` гейтит добавление `speech_block`/`lessons_block` в `parts` (ON: единственный владелец — композер, слои `context_lessons` в system); `:4116` — ветка композера. Тесты: `tests/test_soul1_composer_parity_off.py:543` (payload-уровень, ×1 на маркер + edge «вопрос не потерян»), `:405` (block-set теперь с lessons/speech, каждый блок ×1). |
| F1 | переанкорено | `tests/test_soul1_legacy_custom_preserved.py:1–26` (шапка: SOUL-AMD.1.2/8.4 вместо отменённых SOUL-04.4/15.3), `:116` — `test_stored_custom_base_is_retrievable_but_not_active_layer` (retention/read-only/идемпотентность; ассерты «кастом в effective prompt» удалены). Блокер F1.2 — ниже. |
| F3 | усилено + добавлено | `tests/test_soul1_legacy_custom_preserved.py:160` — точные счётчики владельца (1 известная фраза под longform-план, 0 без плана, идемпотентность; проверка `inspect.getsource(pc)` по всему модулю). `tests/test_soul1_composer_parity_off.py:469` — реальный Stage-2 modes-off через `_synthesize_direct_answer` (`removed == 1`, байт-в-байт). `:503` — новый интеграционный кейс Stage-2 modes-off + ON-композер (один проход скраба, провенанс `legacy_mode`, Core инъектирован). |
| Core budget (F5) | исправлено | `prompt_composer.py:1021–1041` — Core НЕ вытесняется аддитивным бюджетом; перерасход виден `ConflictRecord(conflict_id="core_protected_from_budget", outcome="exempted_protected")`, бюджет режет только добавку. Комментарий `:136–138`. Тест: `tests/test_soul1_composer_layers.py:195`. |
| F4 (гейт/PM) | вне scope Builder | кандидат/статусы в картах — за PM; правок карт в этом проходе нет. |

**BLOCKER[F1.2] composer_flag_release_gate (machine-checkable):** `UNIFIED_COMPOSER_ENABLED`
(env + `flags.unified_composer_enabled`) НЕ включается в проде, пока слайс-amendment не
уберёт legacy speech-каноны/кастомы из effective-слоя с предварительным backup (§7.2,
SOUL-AMD.1.2/8.4). Маркер дублирован кодом: `services/prompt_composer.py:524–538`
(`composer_enabled_now`) и шапкой `tests/test_soul1_legacy_custom_preserved.py`. После
слайса-amendment — повторная проверка F1 и только затем включение.

Доказательства fix-pass:
* `evidence/w2/on-payload-single-copy.txt` — дамп payload реального `_l2_write_answer` с флагом ON:
  system ×1 / user ×0 / payload ×1 для `<Speech_Understanding>` и `<Verified_Lessons>`
  (edge: user-часть без блоков = вопрос, не пусто).
* `evidence/w2/focused-suites.txt` — [A] **55 passed** (было 52; +3 новых теста), [B] **432 passed**,
  [C] **200 passed** (те же списки).
* `evidence/w2/parity-off.txt` — **13 passed**, включая P1/P2/P3/P5a/P5b байт-в-байт: OFF-путь
  после F2 не изменился ни на байт.

Остаточное (осознанное): при ON `speech/lessons` едут секцией system (владелец — композер §3),
а не user — следствие единого владельца, OFF-путь паритетен; L2 fallback-репак при ON видит их
частью защищённой `system` (сжимаемая user-часть укорачивается как раньше).

