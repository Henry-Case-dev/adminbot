# SMART-CORRECTIVE-01 — S6-ACTIVATION: метка заводской ревизии чекапа

Статус: **REVIEW** (кандидат для независимого ревью; не VERIFIED).
Дата: 2026-11-15.
Срез: `S6-ACTIVATION` (шаг активации поверх `S6-PROMPT` + `S6-prompt-guard`).
Источник: owner §8.5 (устаревшие инструкции Betterstack не должны оставаться
в активном контуре) + production-наблюдение, что новый заводской текст не
стал действующим; §8.1 (сохранённая ручная редакция владельца) обеспечивается
сторожем, задеплоенным в 2.58.202.

## Идентичность кандидата

- Epic: `smart-corrective-01`, срез `S6-ACTIVATION`.
- Базовая линия: `release/smart-corrective-01` @ `0beed63d`
  (`0beed63df8037002ccfaacef019b8ea948d957f6` — задеплоенный поезд 2.58.202,
  включающий сторож §8.1).
- Рабочая ветка: `sc/corrective-checkup-label`.
- Commit кандидата: `1a945ec5`
  (`1a945ec5b5c47ff18d30c5782ee91e63a5e23441`) —
  `fix(prompts): release S6 checkup factory edition via label bump`.
- Worktree: `...\WorkspaceData\worktrees\c742e4de9e92c489\`
  `smart-corrective-01-0097aecc4a7a-c1b9af67` (регистрирован как `checkup-label`).
- `APP_VERSION` не менялся (2.58.202); бамп до 2.58.203 — релизный поезд.
- Схема/DDL, флаги, настройки и модели не менялись. Затронуто 5 файлов,
  из них 1 новый тестовый.

## Причина (воспроизведена на базовой линии)

`S6-PROMPT` исправил заводской жанр чекапа (удалены Betterstack и пример 401,
добавлена граница смешанного состояния) и обновил печать содержимого, но
оставил прежнюю метку `checkup-p0-24-10`. Релизная политика EVOL-016 решает
активацию по МЕТКЕ (`prompt_registry.activation_plan`: `applied == code
revision` → `PLAN_NOOP`), поэтому релиз видел ту же заводскую ревизию и не
писал новое значение. Итог: глобальный слой `prompts.checkup_system_prompt`
продолжал отдавать редакцию 2.58.200 (3 030 симв., sha256_16 `b0c70f97`, с
Betterstack/401) чатам без override; `factory`-слой в коде при этом уже был
новым (3 462 симв., sha256_16 `3140bb36`).

RED на базе `0beed63d` (до правки, реальные прогоны):
`tests/test_smart_corrective_checkup_label_activation.py` +
`tests/test_smart_corrective_prompt_delivery.py` → **4 failed, 23 passed** —
падают ровно те проверки, что описывают дефект: метка/печать (метка та же),
активация глобального слоя (остаётся stale-текст), чат без ручной ревизии (не
получает новую фабрику), сквозной сценарий ручной редакции (глобальный слой не
обновился).

## Что изменено

1. `services/prompt_registry.py` — `FACTORY_REVISION_LABELS["checkup.base.system"]`
   и `FACTORY_REVISION_SEALS["checkup.base.system"]` подняты на новую стабильную
   метку `checkup-p0-24-10-mixed-state`. Байты заводского текста НЕ менялись
   (печать остаётся `3140bb364044`), `PREV_CHECKUP_P0_24_10_SYSTEM_PROMPT`
   сохранён без изменений. Комментарии у обеих записей объясняют, почему бамп
   стал безопасным именно сейчас (сторож §8.1 в проде с 2.58.202).
2. `services/checkup_prompts.py` — только docstring: зафиксировано, что
   правка текста «под той же меткой» в 2.58.202 не активировала редакцию, и что
   именно меняет S6-ACTIVATION. Текст промпта не менялся.
3. Код релизной политики (`services/prompt_release_policy.py`) **не менялся**:
   поведение «global + чаты без ручной ревизии получают новую фабрику, живая
   ручная ревизия сохраняется с `factory_superseded_manual`, явный
   `baseline_assign` сохраняет приоритет» уже реализовано и задеплоено в
   2.58.202. Срез включает только метку и доказательства инвариантов.

## Матрица поведения (проверено тестами)

| Ситуация | До (метка не менялась) | После (метка бампнута) | Диагностика |
|---|---|---|---|
| Глобальный слой (factory-origin, без ручной ревизии) | `PLAN_NOOP`, stale Betterstack | `activate`, значение = новая фабрика (3 462, `3140bb36`) | `deploy_activate` / `applied` / `factory_activate` |
| Чат с override, без ручной ревизии | ничего не происходило | override снят, чат читает новую фабрику; старые байты — в истории | `deploy_activate` / `applied` / `factory_activate` |
| Чат с живой ручной ревизией (C2-класс) | ничего не происходило | байты владельца байт-в-байт, override сохранён, заводская ревизия — в истории | `deploy_activate` / `skipped_same` / `factory_superseded_manual` |
| Тот же чат с явным `baseline_assign` | — | приоритет baseline сохранён | `activate_pinned` / `factory_superseded_pinned` |
| Повтор/рестарт после поставки | no-op | no-op (ни строк, ни записей, ни дрейфа) | `no_op` / `skipped_same` / `restart_same_revision` |
| Другой чат без ручной ревизии | — | получает новую фабрику | `factory_activate` |

Клоны/переписывание значений отсутствуют: ручная ревизия не меняет
`content_sha12`, число новых ревизий при поставке — ровно 2 (global + чат),
чат не получает уведомление, потому что его значение не менялось.

## Тесты (реальные прогоны на кандидате `1a945ec5`)

Новый файл `tests/test_smart_corrective_checkup_label_activation.py`
(7 проверок, `TEST-LIFECYCLE: CONTRACT owner=smart-corrective-01 §8.5 + §8.1`):
согласованность метки/печати/текста; активация глобального слоя; чат без
ручной ревизии; сохранение ручной редакции с `factory_superseded_manual`;
приоритет `baseline_assign`; истинный no-op рестарта; чатовая изоляция.
В `tests/test_smart_corrective_prompt_delivery.py`:
- заменён тест, который утверждал прежний контракт «метка не менялась ⇒
  `PLAN_NOOP`», на проверку «бамп метки ⇒ `PLAN_ACTIVATE`
  (`new_factory_revision`) при целой печати»;
- добавлен сквозной `test_label_bump_activation_reaches_checkup_route`:
  реальный релизный проход заменяет глобальное значение, и маршрут чекапа без
  override строит system из исправленной редакции (нет Betterstack/401, есть
  формулировка смешанного состояния, `prompt_base_hash` = sha16 новой фабрики).
В `tests/test_p0_prompts_core.py` пин метки переутверждён осознанно.

```
py -3 -m pytest tests/test_smart_corrective_checkup_label_activation.py \
  tests/test_smart_corrective_prompt_delivery.py tests/test_smart_corrective_budget_policy.py \
  tests/test_smart_corrective_completion.py tests/test_smart_corrective_input.py \
  tests/test_smart_corrective_source_reader.py tests/test_prompt_baseline.py \
  tests/test_evol016_prompt_activation.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_evol018_prompt_audit.py \
  tests/test_prompt_history_pagination.py tests/test_prompt_readback.py \
  tests/test_prompt_versioning_enforcement.py tests/test_pvr_backend_state.py \
  tests/test_pvr_rev01_prompt_conflict_no_write.py tests/test_asap_prompt_history_integrity.py \
  tests/test_evol012_barrier_retired.py -q
→ 328 passed, 2 skipped      (база: 320 passed, 2 skipped; +8 новых проверок)

py -3 -m pytest tests/test_checkup_prompts.py tests/test_checkup_contract.py \
  tests/test_checkup_service.py tests/test_checkup_handlers.py tests/test_checkup_logs_fetcher.py \
  tests/test_p0_checkup_core_contract.py tests/test_p0_prompts_core.py \
  tests/test_expression_isolation_followup.py tests/test_prompt_migrations.py \
  tests/test_soul1_factory_defaults.py tests/test_soul1_registry_legacy_removal.py \
  tests/test_direct_chat_prompts.py tests/test_summary_prompts.py -q
→ 331 passed               (идентично базе)

py -3 -m pytest tests/test_checkup_handlers.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_prompt_field_audit.py \
  tests/test_prompt_history_pagination.py tests/test_prompt_readback.py \
  tests/test_prompt_versioning_enforcement.py tests/test_pvr_rev01_prompt_conflict_no_write.py \
  tests/test_prompts_round1024.py tests/test_summary_asap21_prompt_migrations.py \
  tests/test_soul1_direct_prompt_reads.py tests/test_soul1_legacy_custom_preserved.py \
  tests/test_soul1_core_version_propagation.py tests/test_round1025_f8_registry.py -q
→ 264 passed, 1 known pre-existing failure (см. ниже)

py -3 -m pytest tests/test_evol016_prompt_activation.py tests/test_evol016_prompt_journal_v39.py \
  tests/test_evol017_prompt_history_ui.py tests/test_evol018_prompt_audit.py \
  tests/test_prompt_baseline.py tests/test_prompt_history_pagination.py \
  tests/test_prompt_readback.py tests/test_prompt_versioning_enforcement.py \
  tests/test_prompt_field_audit.py tests/test_prompt_migrations.py \
  tests/test_pvr_backend_state.py tests/test_pvr_rev01_prompt_conflict_no_write.py \
  tests/test_asap_prompt_history_integrity.py tests/test_evol012_barrier_retired.py -q
→ 274 passed, 2 skipped, 1 known pre-existing failure

py -3 -m pytest tests/test_soul1_core_doc_text.py tests/test_soul1_core_registry_api.py \
  tests/test_soul1_core_composer_integration.py tests/test_soul1_factory_defaults.py \
  tests/test_soul1_w4_authorial_genre.py tests/test_soul1_w4_humor_craft.py -q
→ 72 passed

py -3 -m py_compile services/prompt_registry.py services/checkup_prompts.py \
  tests/test_smart_corrective_checkup_label_activation.py \
  tests/test_smart_corrective_prompt_delivery.py tests/test_p0_prompts_core.py → 0
git diff --check → clean
```

### Известные pre-existing падения (не связаны с срезом, те же на базе `0beed63d`)

1. `tests/test_prompt_field_audit.py::test_every_editable_prompt_has_reachable_surface`
2. `tests/test_soul1_registry_completeness.py::test_registry_consumer_pointers_point_at_real_lines`

Прямой прогон пары на кандидате: `2 failed` — те же тесты, причины те же
(подтверждено на чистой базовой линии до правки).

## Acceptance mapping

| Пункт | Чем доказан |
|---|---|
| Метка/печать согласованы, текст не менялся | `test_label_bumped_with_intact_seal_and_unchanged_text`; `pr.seal_integrity() == {}`; `test_p0_prompts_core` (пин метки) |
| Global получает новую фабрику | `test_new_label_activates_factory_in_global_layer` |
| Чат без ручной ревизии получает фабрику | `test_chat_without_manual_revision_gets_new_factory` |
| Ручная редакция чата сохраняется байт-в-байт + `factory_superseded_manual` + фабрика в истории | `test_manual_chat_edition_survives_label_bump` |
| `baseline_assign` сохраняет приоритет | `test_explicit_baseline_assign_still_wins` |
| Рестарт/повтор — no-op | `test_restart_after_label_bump_is_true_noop` |
| Stale Betterstack/401 отсутствует в активном тексте | `test_label_bumped_with_intact_seal_and_unchanged_text`, `test_new_label_activates_factory_in_global_layer`, `test_label_bump_activation_reaches_checkup_route` |
| Байты владельца не менялись, клонов нет | `test_manual_chat_edition_survives_label_bump` (sha/body до-после, число ревизий, отсутствие уведомления) |
| Чатовая изоляция | `test_manual_guard_is_isolated_to_its_chat` |

## Исполнение и конфигурация

- Флаги/настройки/провайдеры для этого среза не задействованы: активация
  происходит на старте процесса релизной проводкой `apply_release` (EVOL-016),
  условия — метка + целая печать. Тестовых override флагов нет.
- Эффективная конфигурация релиза: `FACTORY_REVISION_SEALS`/`LABELS` из кода
  кандидата; `factory_set_fingerprint` не изменился (`2cd38b272139`) — набор
  текстов тот же, меняется только идентичность ревизии.

## Ограничения (честная граница)

- Production в этом срезе не трогался (правило: без доступа к проду из этой
  задачи). Постдэплой-подтверждение требует реального процесса бота: после
  выката 2.58.203 посмотреть строки `[prompt_release] activation | ... |
  checkup.base.system` в журнале, `factory_revision_applied =
  fac:<sha12(checkup-p0-24-10-mixed-state)>` в журнале активаций и
  `prompt_source/prompt_base_hash` в телеметрии реального чекапа; для C2 —
  `factory_superseded_manual` и неизменный sha ручной ревизии.
- Если у CHAT_C2 chat-override был снят ещё релизом 2.58.201 (состояние
  «сохранённая редакция без override»), чат в релиз не входит и читает
  глобальный слой; сама ручная ревизия остаётся в истории. Возврат редакции на
  маршрут — отдельное data-only действие владельца/UI, этот срез его не
  выполняет и не переписывает значение.
- Владелец не привлекается к проверкам (owner QA не назначается); все
  технические проверки выполнены агентом.
