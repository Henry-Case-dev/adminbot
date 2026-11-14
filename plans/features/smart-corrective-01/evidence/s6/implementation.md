# SMART-CORRECTIVE-01 — S6-PROMPT implementation evidence

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-14/15.
Уровень приёмки: predeploy, кандидат-связанный. Production-проверка реальной
доставки сохранённой редакции — отдельный postdeploy-шаг (см. «Ограничения»).

## Идентичность кандидата

- Epic: `smart-corrective-01`, срез `S6-PROMPT`.
- Базовая линия: ветка `sc/corrective-s3b` @ `b04dd8f7`
  (S3B code candidate `1bbe767d`, S3B approved, base release line
  `release/2.58.200` @ `13884daa` = deployed `0e4a144d`).
- Рабочая ветка: `sc/corrective-s6`.
- Code candidate commit: `5d2eb427` (`fix(checkup): deliver saved prompt via
  registry chat precedence (S6)`).
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-e7b064d8`
  (managed `WorkspaceData/worktrees`, registered как `s6-prompt`).

## Что именно изменилось

### 1. Резолв базы чекапа: chat override → global → factory

`services/checkup_service.py`:

- Новый helper `_resolve_checkup_base_prompt(chat_id)`:
  - `chat_id is not None` (пользовательская команда, фактический маршрут
    handler'а `handlers/checkup.py:549`) → **существующий** резолвер реестра
    `prompt_registry.resolve_chat_speech_ex("prompts.checkup_system_prompt",
    CHECKUP_SYSTEM_PROMPT, chat_id=...)` — тот же порядок chat → global →
    default, что у Direct-канала (`direct_chat_service.py:5438`), включая
    провенанс/удержание реестра и детерминированную вычистку известных
    legacy-сегментов;
  - `chat_id is None` (внутренний tool-loop `get_bot_health`) → **прежний**
    `resolve_prompt_with_source` (global → default, per-chat слой не читается).
- До среза сервис читал только global-слой (`resolve_prompt` +
  `resolve_prompt_with_source`), поэтому production run A дал
  `prompt_source=global`, а сохранённая владельцем редакция `CHAT_C2`
  (12 469 chars, `31d175065461`, `manual_edit` 06:11:54Z) не доходила до
  маршрута.
- Сервис **не пишет** промпт: в `checkup_service.py` нет
  `write_prompt_values`/`write_speech_value`/`write_versioned_value`/
  `set_chat_params`/`apply_factory_reset` (проверяется тестом).
  Сохранённые байты владельца остаются в PG/chat_params без изменений.
- `{max_symbols}` по-прежнему единственная подстановка, только в system.

### 2. Провенанс/телеметрия

`CheckupService._prompt_telemetry` — прежние ключи сохранены, добавлены
additive-ключи (без текста промпта):

| Ключ | Смысл |
|---|---|
| `prompt_source` | фактический слой `chat|global|default` (как раньше для global/default; `chat` — новое значение для своего чата) |
| `prompt_hash` | sha256[:16] ФИНАЛЬНОГО system (ровно байты, уходящие в LLM) |
| `prompt_version_used` | `<source>:<sha12(system)>` |
| `prompt_chars` | длина финального system |
| `prompt_layer` | additive: фактический слой резолва (тот же словарь) |
| `prompt_base_hash` / `prompt_base_chars` | additive: hash/длина **резолвнутой сохранённой редакции до сборки** (до `{max_symbols}`, owner-block, addendum) — прямая сверка с сохранённым значением |
| `prompt_withheld` | additive: реестр не сделал PG-значение эффективным слоем (действует заводская редакция) |
| `prompt_provenance_reason` | additive: машинный код причины удержания |

Телеметрия кладётся в per-run словарь вызывающего (`telemetry.update`) и
хендлером — в существующий `checkup_triggered.source_ref_json`
(`handlers/checkup.py:349-382`, без whitelist), т.е. реальная доставка
наблюдаема по production-событиям.

### 3. Активный заводской жанр очищен от устаревшего Betterstack

`services/checkup_prompts.py`:

- Активная редакция `CHECKUP_SYSTEM_PROMPT` (жанр + действующий
  `STYLE_BLOCKS_SUFFIX`):
  - удалён Betterstack как источник («по переданным логам, локальным
    журналам и метрикам»);
  - удалён 401-пример удалённого облачного провайдера; вместо него —
    «отказ источника ≠ отказ всей системы/всех маршрутов диагностики»
    (owner §8.5, SC-PRM-ADD-03);
  - добавлена смысловая граница смешанного состояния: чистое свежее окно
    журналов не отменяет доказанный существенный косяк и активный
    ERROR-инцидент; историческая запись не выдаётся за текущее падение;
    доказанный косяк не смягчается работающей системой (owner §8.4).
- Языковое ядро «СУТЬ АНАЛИЗА» (4 пункта, включая «человеческо-токсичный»)
  сохранено дословно; `{max_symbols}` — по-прежнему единственный placeholder.
- Прежняя активная редакция сохранена **байт-в-байт** как
  `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT` (3 030 chars, sha256_16
  `b0c70f974e0e`) — ровно байты прода 2.58.200. Исторические
  `PREV_CHECKUP_*` не переписаны.
- `CHECKUP_FALLBACK_NOTICE` не менялся (уже очищен SELF-DIAG-01 D1).
- `CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM`: операционные инструкции приведены в
  соответствие с фактическим поведением инструментов (S1/S2/S3/S3B/S4):
  недостаточность первого результата допускает продолжение (другой
  символ/путь/диапазон, `cursor`, `time_window`); отсутствие необходимости в
  исследовании допускает обычное завершение; отказ источника не равен отказу
  всех маршрутов; существенную непроверенность нельзя скрывать; после
  исчерпания подходящих маршрутов допустим честный частичный отчёт; активный
  ERROR-инцидент и чистые свежие логи могут быть верны одновременно. Жанровый
  промпт в addendum не дублируется; словарей/проверок мата/обязательного
  перефразирования нет.

### 4. Реестр и версия

`services/prompt_registry.py`:

- `FACTORY_REVISION_SEALS["checkup.base.system"] = ("checkup-p0-24-10",
  "3140bb364044")` — печать содержимого обновлена синхронно с текстом;
  `seal_integrity()` пуст.
- `FACTORY_SET_SHA256_12 = "2cd38b272139"` (осознанный бамп отпечатка набора;
  changed = 1 — только `checkup.base.system`).
- **Метка заводской ревизии осознанно НЕ менялась.** В EVOL-016 новая метка
  активирует заводской текст поверх ручной правки и снимает chat-override
  (`prompt_release_policy._apply_scope_release`, §1.5). Для этого corrective
  owner §8.1 прямо запрещает заменять сохранённую ручную редакцию
  (`CHAT_C2`) новой заводской. Поэтому текст исправлен на месте под прежней
  меткой: `activation_plan` на деплое даёт `PLAN_NOOP`, PG-значения не
  перезаписываются, override владельца сохраняется. Исторические байты — в
  `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT`.

### 5. Слой речи

- Порядок system не менялся: жанр → `speech_owner_block` (Core + Expression) →
  `CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM` (только при реальных схемах) →
  `CHECKUP_FALLBACK_NOTICE` последним.
- Второй Personality Core/Expression/регулятор мата не добавлялись; жанр не
  заменён нейтральным голосом; единственный outbound-проход Style Policy
  (`checkup_pre_send`) сохранён, второй обработки нет.
- Искусственных символьных/токенных квот на инструкции не добавлялось.

## Тесты (кандидат `5d2eb427`)

Новый файл:

- `tests/test_smart_corrective_prompt_delivery.py` (16 тестов):
  матрица chat → global → factory, per-chat scope, неизменность сохранённого
  значения, наблюдаемость изменения текста реестром, телеметрия без текста,
  активный контур без Betterstack/401 при целых исторических `PREV_*`,
  операционное соответствие addendum, отсутствие дубля жанра/словарей мата,
  смешанное состояние, полная доставка инструкций (owner-редакция >12 000
  chars + addendum + notice, точное равенство собранному system), один слой
  речи, `seal_integrity` + `PLAN_NOOP` на деплое.

Обновлены тесты, кодировавшие прежнее поведение (осознанно):

| Файл | Что изменено и почему |
|---|---|
| `tests/test_checkup_prompts.py` | `test_base_is_owner_text_byte_exact` → `test_prev_edition_is_owner_text_byte_exact`: байт-эталон owner-источника §2 теперь у исторического `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT` (3 030 chars, `b0c70f97`); добавлен тест, что активная редакция отличается от источника только документированными §8.5-правками |
| `tests/test_checkup_contract.py` | пин sha256 заводского промпта обновлён на `3140bb364044…` (осознанная новая активная редакция); назначение пина (один промпт/один writer) сохранено |
| `tests/test_p0_prompts_core.py` | `FACTORY_SET_SHA256_12` переутверждён → `2cd38b272139`; метка `checkup-p0-24-10` осталась (проверяется там же) |
| `tests/test_expression_isolation_followup.py` | тот же fingerprint-пин переутверждён → `2cd38b272139` |
| `tests/test_checkup_logs_fetcher.py` | `test_bare_checkup_uses_same_prompt_key` следит за фактическим резолвером внутреннего маршрута (`resolve_prompt_with_source`), ключ и байты те же |

Точные команды и результаты:

```
py -3 -m pytest tests/test_smart_corrective_prompt_delivery.py \
  tests/test_checkup_prompts.py tests/test_checkup_contract.py \
  tests/test_checkup_service.py tests/test_checkup_handlers.py \
  tests/test_checkup_logs_fetcher.py tests/test_p0_checkup_core_contract.py \
  tests/test_p0_prompts_core.py tests/test_evol016_prompt_activation.py \
  tests/test_evol018_prompt_audit.py tests/test_soul1_factory_defaults.py \
  tests/test_soul1_registry_legacy_removal.py tests/test_prompt_migrations.py \
  tests/test_prompt_baseline.py tests/test_asap_prompt_history_integrity.py \
  tests/test_evol012_barrier_retired.py -q
→ 360 passed, 2 skipped
```

```
py -3 -m pytest tests/test_smart_corrective_budget_policy.py \
  tests/test_smart_corrective_completion.py tests/test_smart_corrective_input.py \
  tests/test_smart_corrective_prompt_delivery.py \
  tests/test_smart_corrective_source_reader.py -q
→ 96 passed
```

```
py -3 -m pytest tests/test_add_exp_expression.py tests/test_asap8_f4_prompt_truth.py \
  tests/test_direct_chat_prompts.py tests/test_dossier_prompts.py \
  tests/test_dream_prompts.py tests/test_expression_isolation_followup.py \
  tests/test_factcheck_prompts.py tests/test_lore_prompts.py \
  tests/test_nostalgia_prompts.py tests/test_p0e_expression_frequent.py \
  tests/test_p0_expression_final_contract.py tests/test_p0_factual_memory_prompts.py \
  tests/test_persona_prompt.py tests/test_smartsearch_prompts.py \
  tests/test_soul1_style_payload.py tests/test_soul1_style_policy.py \
  tests/test_soul1_style_repetition.py tests/test_summary_prompts.py \
  tests/test_web_prompts.py tests/test_youtube_prompts.py -q
→ 637 passed, 2 skipped; 1 pre-existing failure (см. Incidental findings)
```

```
py -3 -m pytest tests/test_checkup_handlers.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_prompt_field_audit.py \
  tests/test_prompt_history_pagination.py tests/test_prompt_readback.py \
  tests/test_prompt_versioning_enforcement.py tests/test_pvr_rev01_prompt_conflict_no_write.py \
  tests/test_prompts_round1024.py tests/test_summary_asap21_prompt_migrations.py \
  tests/test_soul1_direct_prompt_reads.py tests/test_soul1_legacy_custom_preserved.py \
  tests/test_soul1_core_version_propagation.py tests/test_round1025_f8_registry.py -q
→ 264 passed; 1 pre-existing failure (см. Incidental findings)
```

```
py -3 -m py_compile services/checkup_prompts.py services/checkup_service.py \
  services/prompt_registry.py tests/test_smart_corrective_prompt_delivery.py
→ 0
git diff --check → clean
```

## Карта строк (S6-PROMPT)

Все наблюдения — на кандидате `5d2eb427`; ref — тесты/код этого кандидата.

| req_id | Наблюдение на кандидате |
|---|---|
| SC-PRM-CHECK-01 | `_resolve_checkup_base_prompt`: chat override читается `resolve_chat_speech_ex`, global/factory — фолбэк; тесты `test_chat_override_applies_on_checkup_route`, `test_global_layer_applies_without_chat_override`, `test_factory_fallback_without_persisted_value` |
| SC-PRM-CHECK-02 | `_prompt_telemetry`: source/hash/version_used/chars + layer/base hash/chars/withheld/reason; `test_telemetry_has_no_prompt_text` |
| SC-PRM-CHECK-03 | Сохранённая редакция применяется в своём чате и не применяется в другом; `test_chat_override_applies_on_checkup_route`, `test_chat_override_is_scoped_to_its_own_chat` |
| SC-PRM-CHECK-04 | Возможное изменение текста реестром наблюдаемо (`prompt_base_hash` ≠ сохранённый hash), PG-значение цело; `test_registry_change_is_observable_and_store_untouched` |
| SC-PRM-CHECK-05 | `{max_symbols}` — единственная подстановка, только в system; `test_full_instructions_reach_the_model`, `tests/test_checkup_prompts.py::test_max_symbols_is_the_only_placeholder` |
| SC-PRM-CHECK-06 | Порядок блоков: жанр → owner (Core+Expression) → addendum → fallback notice; `test_full_instructions_reach_the_model`, `test_single_speech_layer_no_second_engine` |
| SC-PRM-CHECK-07 | Effective Personality Core по-прежнему приходит `speech_owner_block`; `tests/test_p0_checkup_core_contract.py::test_sp01_checkup_gets_active_core` + `test_full_instructions_reach_the_model` |
| SC-PRM-CHECK-08 | Effective Expression владельца в его чате не изменился (тот же owner-block); `tests/test_p0_checkup_core_contract.py::test_sp02_checkup_gets_effective_chat_expression` |
| SC-PRM-CHECK-09 | Модельный payload проверяется на фактическом маршруте: тесты читают `messages[0][0]["content"]` из вызова `llm.generate` после `CheckupService.checkup` |
| SC-PRM-CHECK-10 | Addendum подключается при реальных схемах и сохраняется вместе с fallback-notice; `test_full_instructions_reach_the_model` (tool_runtime) + S4/loop-тесты |
| SC-PRM-CHECK-11 | Инструкции не обрезаются: owner-редакция >12 000 chars + addendum + notice входят целиком, system равен точной сумме блоков; `test_full_instructions_reach_the_model` |
| SC-PRM-CHECK-12 | `cleanup_llm_text` и единственный outbound Style Policy проход не менялись; `test_single_speech_layer_no_second_engine` (ровно 1 вызов) |
| SC-PRM-LAYER-01 | Personality Core — единственный, через существующий `speech_owner_block`; нового Core нет (`test_single_speech_layer_no_second_engine`) |
| SC-PRM-LAYER-02 | Expression не дублируется; жанр ссылается на Expression, второй копии нет (`test_single_speech_layer_no_second_engine`, `tests/test_p0_checkup_core_contract.py`) |
| SC-PRM-LAYER-03 | Жанровый промпт остаётся назначением/формой/выразительностью тех-разбора; не заменён нейтральным голосом (`test_single_speech_layer_no_second_engine`) |
| SC-PRM-LAYER-04 | Style Policy — единственный outbound-проход, сохранён; второго постпроцессора нет (`test_single_speech_layer_no_second_engine`) |
| SC-PRM-SEM-01 | «текущее состояние инфраструктуры» различимо: жанр требует отражать рабочую инфраструктуру и инциденты одновременно |
| SC-PRM-SEM-02 | «свежие ошибки журналов»: сохранённый блок «СУТЬ АНАЛИЗА» + смысловая граница чистого окна |
| SC-PRM-SEM-03 | «активные и исторические инциденты»: формулировки «активная историческая запись не доказывает текущее падение» |
| SC-PRM-SEM-04 | «подтверждённые дефекты исходников»: «доказанный косяк не смягчается»; addendum различает подтверждённое/гипотезу |
| SC-PRM-SEM-05 | «восстановившиеся сбои»: сохраняется различение успешного fallback и гипотезы (ГРАНИЦЫ ДОСТОВЕРНОСТИ) |
| SC-PRM-SEM-06 | «вероятные причины»: гипотеза не подаётся как установленная причина (жанр + addendum) |
| SC-PRM-SEM-07 | «непроверенные сведения»: addendum — существенную непроверенность нельзя скрывать, unknown ≠ ноль |
| SC-PRM-CLEANLOG | «чистое свежее окно не отменяет резкий разбор существенных проблем» — дословно в активном жанре; `test_mixed_state_is_prompt_wording_not_a_new_mechanism` |
| SC-PRM-BOTH | «рабочая инфраструктура и активный инцидент могут быть верны одновременно» — активный жанр + addendum; тот же тест |
| SC-PRM-NOACTIVEFALSE | «активная историческая запись сама по себе не доказывает, что компонент падает прямо сейчас»; тот же тест |
| SC-PRM-NOSOFT | «доказанный косяк не смягчается тем, что остальная система работает»; тот же тест |
| SC-PRM-NOINVENT | «не выдумывай неисправности ради шутки» / «не выдумывай проблем, которых нет в фактах» сохранены |
| SC-PRM-STALE-01 | Проверены активный жанр, addendum, fallback notice; `test_active_contour_has_no_stale_betterstack` |
| SC-PRM-STALE-02 | В активном контуре нет `betterstack`/`401` (жанр, addendum, notice); исторические `PREV_*` целы — `test_active_contour_has_no_stale_betterstack`, `test_historical_editions_still_contain_old_bytes` |
| SC-PRM-STALE-03 | `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT` = прежние байты прода (3 030, `b0c70f97`); старые `PREV_CHECKUP_*` не переписаны; `tests/test_checkup_prompts.py` |
| SC-PRM-STALE-04 | Реестр согласован: `seal_integrity()` пуст, печать = sha12 активного текста, метка сохранена → `activation_plan == PLAN_NOOP`, ручная редакция не заменяется; `test_factory_content_fix_does_not_activate_over_owner_edition` |
| SC-PRM-ADD-01 | Addendum: «Недостаточность первого результата не является основанием прекращать исследование… cursor/time_window»; `test_addendum_states_new_tool_behaviour` |
| SC-PRM-ADD-02 | Addendum: «Отсутствие необходимости в исследовании — нормальное завершение отчёта» |
| SC-PRM-ADD-03 | Addendum: «Отказ одного источника или инструмента не равен отказу всех доступных маршрутов»; жанр: «отказ источника ≠ отказ всей системы» |
| SC-PRM-ADD-04 | Addendum: «Существенную непроверенность нельзя скрывать» |
| SC-PRM-ADD-05 | Addendum: «после исчерпания подходящих маршрутов допустим честный частичный отчёт с указанием, что именно не проверено и почему» |
| SC-PRM-ADD-CHECK | Addendum проверен отдельно и согласован с S1/S2/S3/S3B/S4; `test_addendum_states_new_tool_behaviour` |
| SC-PRM-ADD-NODUP | В addendum нет «СИСТЕМНАЯ РОЛЬ И ЗАДАЧА»/«СУТЬ АНАЛИЗА»/«ЖАНР ОТЧЁТА»; `test_addendum_does_not_duplicate_genre_or_add_mat_machinery` |
| SC-PRM-ADD-NOEXTRA | Нет словарей ругательств, проверок количества мата, обязательного перефразирования, шаблонных «токсичных» вставок; тот же тест |
| SC-PRM-GENRE | Активный жанр сохраняет/усиливает резкий технический разбор: «язвительный участник чата», «жестко разъеби», «держится на соплях»; `test_single_speech_layer_no_second_engine`, `tests/test_checkup_prompts.py` |
| SC-PRM-PRESERVE | Сервис не пишет сохранённые значения (нет write-путей), stored override побайтно цел после чекапа; `test_owner_saved_value_is_not_rewritten`, `test_chat_override_applies_on_checkup_route`; заводская метка не менялась → `PLAN_NOOP` |
| SC-PRM-SCOPE | Сохранение относится к текущей ручной редакции этого corrective; исторические `PREV_*` и другие каноны не тронуты (diff: только checkup.base.system) |
| SC-PRM-NOTHIRD | Третьей версии текста нет: активный жанр = прежний owner-текст ровно с §8.5-правками; `test_active_edition_is_documented_stale_fix_only` |
| SC-PRM-NOTPROOF | Доказательством считается фактический payload/телеметрия (`messages[0][0]`, `source_ref_json`), а не константа/админка/preview; `test_telemetry_has_no_prompt_text`, `test_full_instructions_reach_the_model` |
| SC-PRM-NOCORE2 | Второй Personality Core не появился; `test_single_speech_layer_no_second_engine` + `tests/test_p0_checkup_core_contract.py` |
| SC-PRM-NOMATRIX | Отдельного регулятора мата нет: в сервисе/prompt нет `PROFANITY_INSTRUCTIONS`/словарей; `test_single_speech_layer_no_second_engine`, `test_addendum_does_not_duplicate_genre_or_add_mat_machinery` |
| SC-PRM-NOEXPR2 | Второй копии Expression нет: owner-block прежний, addendum Expression не дублирует |
| SC-PRM-NOFLATTEN | Жанр не стёрт нейтральным голосом: активная редакция сохраняет «язвительный участник чата» и жанровые формулировки; `test_single_speech_layer_no_second_engine` |
| SC-PRM-MATSET | Настройки Expression соблюдаются: мат задаётся только Expression (жанр на него ссылается); `tests/test_p0_checkup_core_contract.py::test_sp02_checkup_gets_effective_chat_expression` |
| SC-PRM-NOWORDS | Конкретные матерные слова не требуются: в активном жанре/addendum нет обязательного набора слов |
| SC-PRM-NOSUPPRESS | Нет нового подавления мата: единственный Style Policy не переопределяет мат (`style_policy.py:245`), новых постпроцессоров нет; `test_single_speech_layer_no_second_engine` |

Строки S8-приёмки, для которых S6 даёт механизм (статус остаётся за S8):

- **AC-15** — сохранённая владельцем редакция реально применяется на маршруте
  чекапа без скрытой подмены: кандидат резолвит chat override существующим
  реестром и отдаёт `prompt_source=chat` + `prompt_base_hash/chars` в
  production `source_ref_json`. Финальное production-подтверждение —
  postdeploy (см. «Ограничения»).
- **AC-19** — сохранённый владельцем промпт не перезаписывается при
  исправлениях и деплое: в кандидате нет записи промпта, метка не менялась,
  `PLAN_NOOP`; stored bytes проверены тестом.

## Ограничения и что осталось непроверенным

1. **Реальная production-доставка сохранённой редакции (AC-15/AC-19) не
   проверена в этом кандидате** — по правилу среза нет доступа к production.
   После релиза нужен один реальный чекап в чате с сохранённой редакцией
   (CHAT_C2) и сверка `checkup_triggered.source_ref_json`:
   `prompt_source=chat`, `prompt_base_chars=12469`, `prompt_base_hash=31d175065461…`,
   `prompt_withheld=false` — то есть байты сохранённой редакции, а не только
   наличие текста в админке. Отдельного владельческого QA-действия не
   создаётся: проверка выполняется агентом по production-событиям/логам.
2. **Persisted global row в ЛС не перезаписывается этим кандидатом.** Он
   остаётся прежней заводской редакцией (3 030 chars, `b0c70f97`) до
   owner-approved заводской активации: смена метки в EVOL-016 активировала бы
   заводской текст поверх сохранённой ручной редакции и сняла бы chat-override
   (запрещено owner §8.1/AC-19). Поэтому очистка Betterstack доставлена в
   активном code-контуре (жанр/addendum/notice), а не через перезапись
   сохранённых PG-значений. Если потребуется обновить и persisted global row
   без потери ручной редакции — это отдельное архитектурное решение
   (owner baseline/pin или изменение политики активации), не входящее в S6.
3. `prompt_base_hash` — hash эффективного текста ПОСЛЕ реестрового
   провенанс/legacy-прохода. Если реестр детерминированно вычистит известный
   legacy-сегмент, hash будет отличаться от сохранённых байт — это и есть
   наблюдаемое «возможное изменение текста реестром» (SC-PRM-CHECK-04), а не
   скрытая подмена.
4. Production-флаги/маршрут: `checkup_enabled=true`,
   `checkup_memory_metrics_enabled=true` (production-факт investigation);
   кандидат их не меняет.
5. Prompt text в телеметрию/логи не пишется (только hash/length/source/коды).

## Incidental findings (BACKLOG_ONLY, pre-existing)

1. `tests/test_soul1_registry_completeness.py::test_registry_consumer_pointers_point_at_real_lines`
   падает на базовой ветке `sc/corrective-s3b` (`internal.lore.init`:
   `lore_worker.py:709` не содержит `LORE_INIT_SYSTEM_PROMPT`) — воспроизведено
   на базовом worktree S3B до изменений S6; устаревший consumer-pointer.
2. `tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`
   падает на той же базе (проверка видимости каталога) — воспроизведено на
   S3B; не связано с S6.

## Домохозяйство

- Disposable-аллокаций и probe-каталогов срез не создавал (тесты запускались
  в worktree).
- Worktree сохранён зарегистрированным для Reviewer (`s6-prompt`).
