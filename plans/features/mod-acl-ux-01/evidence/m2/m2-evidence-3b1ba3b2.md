# M2 — доказательство кандидата `3b1ba3b2`: полное состояние capability и явный INHERIT

Артефакт составлен PM после независимого ревью кандидата `3b1ba3b2` и связывает срез **M2**
карты `plans/features/mod-acl-ux-01/requirements-map.json` с фактически проверенным кодом.
Продуктовый код в этом проходе не менялся и тесты PM не перепрогонял: поведенческий вердикт
принадлежит Reviewer, здесь он зафиксирован построчно, с именами тестов из дерева кандидата и с
честной границей непроверенного.

Источник требований: `plans/owner_inputs/2026-11-09-mod-acl-ux-01.md` §2.1–§2.5, §3.2, §4.2,
§10, §11, §12 (строки 16–23, 48–49, 65–74, 81–92, 96–116, 570–619, 678–686).

## 1. Кандидат

| Что | Значение |
|---|---|
| Кандидат | `3b1ba3b2c0b3cb69ecdc5fcc0c5cd54ddfc53515` |
| Родитель | `53c7859449e2b526fbb2f6814d1c2b7bda1e3a8b` |
| Сообщение | `feat(acl): MOD-ACL-UX-01 M2 - полное состояние capability и явный INHERIT` |
| Ветка | `integ/unify-release` (в `master` не влит: `git merge-base --is-ancestor 3b1ba3b2 master` → 1) |
| Объём | 14 файлов, +1725 / −118 |
| Продуктовые файлы | `services/chat_params.py` (+334), `services/feature_gates.py`, `services/module_registry.py`, `services/permsoc.py`, `services/lore_worker.py`, `services/nostalgia_worker.py`, `services/status_service.py`, `web/api/gates.py`, `web/api/routes.py` |
| Тесты кандидата | 3 новых файла: `tests/test_mod_acl_ux_m2_capability_state.py` (14 проверок), `tests/test_mod_acl_ux_m2_consumers.py` (9), `tests/test_mod_acl_ux_m2_tristate_write.py` (10); правки `tests/test_mod_acl_ux_m2_resolver.py` (6 строк) и `tests/test_lore_worker.py` (+1 тест, 2 ожидания) |
| Предшественник | `97cfdef1` — **ancestor** кандидата (`git merge-base --is-ancestor 97cfdef1 3b1ba3b2` → 0), работа M2 накоплена на ветке, не переписана |
| Развёрнуто | **нет.** `deployed_commit` карты относится к релизу M5L (2.58.172 @ `bee14188`) и к M2 не применяется |

Проверенный Reviewer'ом объём прогонов: 24 M2-теста записи/состояния (14 + 10), 50 тестов
потребителей/резолвера/lore-воркера (9 + 10 новых/обновлённых + 31 существующий затронутый), 21
тест родительских наборов на 409-контракт `set_chat_params`.

## 2. Почему карта не лежит в checkout кандидата и постоянное решение

Ревьюер дважды запускал review-gate из **изолированного checkout релизной ветки** и получал
отказ ещё до проверки строк:

```
requirements_gate.py check --map plans/features/mod-acl-ux-01/requirements-map.json ...
→ map недоступна: в дереве кандидата файла requirements-map.json нет
```

Причина — расхождение веток, а не дефект продукта: `requirements-map.json`, `plan.md`,
`slice-graph.json`, `m0-baseline.md` и `plans/owner_inputs/` живут в `master`, а релизная ветка
исторически несёт только подмножество `plans/`. Два цикла ревью ушли на процессную проблему,
которую можно было решить один раз.

**Решение зафиксировано в `plan.md` §8 и внесено в релизный чек-лист:** review-gate **всегда**
запускается из основного checkout против SHA кандидата (`--repo . --candidate <sha>`), карта из
релизную ветку не переносится. Причина в одну строку: карта — один живой леджер, и вторая её
копия на релизной ветке немедленно разошлась бы с master. Перенос `plans/features/<epic>/` на
релизную ветку оставлен как явная альтернатива только для случая, когда ревью обязано быть
воспроизводимым из одного checkout; в этом проходе файлы не перемещались.

## 3. Что именно доказано — построчный леджер

Все наблюдения ниже — из дерева кандидата `3b1ba3b2`; тесты указаны по именам, утверждения
приведены по тексту assertions, а не по названию.

| Строка | Доказательство на `3b1ba3b2` |
|---|---|
| `MAC-S0-01` | `test_six_case_table_global_module` и `test_six_case_table_per_chat_experience` (строка 5: GLOBAL OFF + CHAT ON → ON), `test_global_off_chat_on_worker_runs_and_selects` (`review_enabled() is True` при GLOBAL OFF, `learning_enabled_for_chat(-100) is True`), `test_every_consumer_reaches_single_resolver` (все четыре потребителя дают `True` при GLOBAL OFF + явном CHAT ON), `test_global_off_chat_on_lore_runs` (lore-воркер генерирует при глобальном OFF и чатовом ON) |
| `MAC-S0-02` | `test_inherit_removes_only_this_chat_override` (`overrides` чата A становится `{KEY2: False}`, чат B и `bot_settings` не тронуты, `state.chat_state == inherit`), `test_inherit_then_explicit_on_round_trip` (INHERIT → ON → INHERIT пишет и снимает, а не «переключает»), `test_gates_put_accepts_inherit` (`enabled="inherit"` снимает только этот гейт), `test_inherit_is_idempotent` |
| `MAC-S0-08` | Новый реестр не введён: `test_no_second_resolver_module` (функция `resolve_capability` определена только в `services/chat_params.py`), `test_gates_api_and_config_use_canonical_state` (`feature_gates.gate_state`, `resolve_module_capability`, `module_registry.gate_snapshot`), в диффе нет новых таблиц/хранилищ — только существующие `chat_params`, `module_registry`, `chat_profiles` |
| `MAC-S2-48` | `test_overrides_priority_is_implemented_once` (ни один потребитель не читает `overrides` напрямую), `test_one_resolver_no_second_gateway`, `test_gate_domain_rows_and_permsoc_alias`; хранение не дублируется — три адаптера над одним ядром `resolve_capability` |
| `MAC-S2-85` | `CapabilityState.as_dict()` отдаёт ровно `source, desired, effective_runtime, ready, observed_at, last_activity_at, reason_code, pending_restart, version, can_read, can_edit` (+ `chat_state`, `consent`, `conflict`); `test_state_snapshot_exposes_separate_axes` утверждает **точный** набор ключей снимка, `test_consumer_state_exposes_tri_state` — наличие осей в ответе потребителя, `test_gates_api_keeps_choice_when_not_ready` — те же поля в `states{}` HTTP-ответа |
| `MAC-S2-91` | `test_global_off_chat_on_worker_runs_and_selects`: `review_enabled() is True` (общий worker жив) при `learning_enabled_for_chat(-200) is False` (наследованный OFF); `test_opt_in_legacy_does_not_disable_chat_gates`: `nostalgia` при INHERIT выключена, но это наследование, а не остановка общего механизма; изоляция подтверждена `test_u4_chat_off_is_local_other_chat_learns` (родительский набор, проходит) |
| `MAC-S2-92` | `test_gates_opt_in_is_consent_not_veto` (`opt_in=False` → `effective_runtime is True`, `consent is False`, `reason_code == "consent_required"`: согласие — ось, а не veto; у лёгких фич `consent is None`), `test_opt_in_legacy_does_not_disable_chat_gates` (отсутствие согласия не превращает явные чатовые гейты в «всё выключено»), `test_has_opt_in_reads_profile_column_not_empty_root` (согласие читается из `chat_profiles.gates_opt_in`; `root` этой колонки не содержит) |
| `MAC-S2-103` | Единый резолвер на существующем слое: `resolve_capability` + `resolve_param_capability` / `resolve_gate_capability` / `resolve_module_capability`; mapping `ModuleSpec.master_param → pg-ключ` через `module_registry`; `test_no_second_resolver_module`, `test_gates_api_and_config_use_canonical_state` |
| `MAC-S2-104` | `test_absent_is_inherit_explicit_false_is_off` (нет записи → `INHERIT`, записанный `false` → `OFF`, разный effective), `test_inherit_removes_only_this_chat_override`, `test_inherit_then_explicit_on_round_trip`, `test_inherit_survives_stale_token` (снятие не «возвращается» при ретрае), `test_stored_explicit_false_is_never_rewritten` (сохранённые `false` не перезаписаны) |
| `MAC-S2-107` | `test_write_bumps_updated_at_notifies_and_invalidates` (запись **того же** значения `True` всё равно даёт `pg_notify == 1`, `updated_at == NEW_TS`, инвалидацию кэша), `test_notify_invalidates_cache_and_change_is_visible` (payload канала сбрасывает кэш, следующий резолв видит новое значение без рестарта), `test_hot_change_reaches_running_process` (глобальная правка видна следующему резолву, чатовый выбор не меняется), `test_inherit_is_idempotent` (no-op только для чистого INHERIT: без UPDATE/NOTIFY и без сдвига метки) |
| `MAC-S2-108` | `test_stored_explicit_false_is_never_rewritten`: `set_chat_params` подменён на функцию, **бросающую** `AssertionError`, затем вызваны read-пути (модуль, гейты двух чатов, резолв опыта); утверждается `cache.by_chat == snapshot` и `invalidated == []`; `test_inherit_is_idempotent` — повторное сохранение не создаёт записей |
| `MAC-S2-116` | `test_global_off_chat_on_worker_runs_and_selects` (тик выбирает только eligible-чаты: явный ON → `True`, INHERIT при глобальном OFF → `False`), `test_every_consumer_reaches_single_resolver`, `test_global_off_chat_on_lore_runs` |
| `MAC-S2-AX-01` | `desired = chat_override != INHERIT ? chat_override : global_default`; шесть строк таблицы проверяют `desired/source/chat_state`, `test_state_snapshot_exposes_separate_axes` — `desired=True` одновременно с `ready=False`/`authorized=True`/`observed=None` |
| `MAC-S2-AX-02` | `effective_runtime = desired AND prerequisites AND NOT emergency_block`; `test_permission_denied_is_distinct_from_consent_required` (`desired True` + `effective_runtime True` при отказе в правах — оси не схлопнуты), `test_desired_on_ready_false_with_exact_reason` (`ready=False` → `effective_runtime False`, `desired` не тронут), `test_env_kill_switch_overrides_table` (emergency → `effective_runtime False` при `desired True`); формула `global_master AND chat_enabled` удалена — строка 5 таблицы |
| `MAC-S2-AX-03` | `test_prerequisites_report_concrete_reason_per_group` (группы дают `provider_missing:stt`, `index_missing:embeddings`, `dependency_missing:dream_worker`, `permission_missing:chat_profile`; порядок групп фиксирован; пустой набор → `ready=None`, «не оценивалось»), `test_gate_readiness_uses_real_llm_provider_check` (реальная проверка `models.llm_*`, а не заглушка; у фич без LLM `ready is None`), `test_gates_api_keeps_choice_when_not_ready` (`states[].ready=False` + `reason_code` в HTTP-ответе) |
| `MAC-S2-AX-04` | `test_can_read_differs_from_can_edit_for_reader` (moderator: `can_read=True/can_edit=False`; local_admin: тяжёлые `(True, True)`, `permsoc` `(True, False)`; global admin `permsoc` `(True, True)`), `test_permission_denied_is_distinct_from_consent_required` (`can_read=False` при `desired True`, `effective_runtime True` — модуль не превращён в OFF), `test_gates_api_keeps_choice_when_not_ready` (`can_read/can_edit` в ответе) |
| `MAC-S2-GATE-01` | `test_permission_denied_is_distinct_from_consent_required` (разные коды `permission_denied` / `consent_required` / `emergency_block` / `capability_off`, ни один не подменяет emergency-ось), `test_gate_conflict_is_named_not_silent` (`gate_conflict:flags.permsoc_enabled` вместо тихого `false`, authoritative-путь не меняется; согласованные значения конфликтом не считаются), `test_declared_conflicts_are_reported`, `test_no_second_resolver_module`, `test_gates_opt_in_is_consent_not_veto` (default не отменяет согласие: ось `consent` сохраняется) |
| `MAC-S10-02` | `test_inherit_removes_only_this_chat_override` (снятие у A не меняет B), `test_hot_change_reaches_running_process` (два чата с разными выборами дают разные `effective_runtime`, отсутствие записи = `INHERIT`), `test_absent_is_inherit_explicit_false_is_off` |
| `MAC-S10-06` | `test_desired_on_ready_false_with_exact_reason` (GLOBAL OFF + CHAT ON + провайдер недоступен → `desired True`, `chat_state ON`, `ready False`, `effective_runtime False`, `reason_code provider_missing:stt`, сохранённое значение не переписано), `test_gates_api_keeps_choice_when_not_ready` (`gates.dream is True` при `states.dream.ready False` и `provider_missing:llm` — значение тумблера не подменяется «неготовностью») |
| `MAC-S15-1-02` | `test_permission_denied_is_distinct_from_consent_required`: основание отказа выводится машиночитаемым кодом (`consent_required`, `permission_denied`, `emergency_block`) при неизменном `desired`; смена глобального default не стирает ось согласия (`test_gates_opt_in_is_consent_not_veto`) и прав (`test_can_read_differs_from_can_edit_for_reader`) |

Интерпретационная граница двух строк: `MAC-S2-AX-03` и `MAC-S15-1-02` содержат слово
«показывается». Здесь доказан именно тот машиночитаемый контракт, который UI печатает
(`ready`/`reason_code`/`can_read`/`can_edit` в `states{}`); композиция экрана — отдельные строки
M4B и этой привязкой не считается доказанной.

## 4. Четыре дефекта, найденные в прерванной работе M2

Все четыре воспроизводимы только на пути, которого на `97cfdef1` не было (явный INHERIT и полная
запись состояния); два из них существовали уже на `97cfdef1`, но были скрыты отсутствием этого
пути. Ниже — механизм, исправление и тест, который ловит регресс.

| № | Дефект | Механизм | Исправление на `3b1ba3b2` | Тест-сторож |
|---|---|---|---|---|
| D1 | Ложный `consent_required` у каждого тяжёлого гейта | `has_opt_in(chat_id, pg, root=root)` читал `gates_opt_in` из `chat_params`-root, где этой колонки нет; результат всегда `False` → `consent_required` как постоянный фон | согласие читается из профиля (`chat_profiles.gates_opt_in`), `root` уважается только если значение в нём реально положено | `test_has_opt_in_reads_profile_column_not_empty_root` |
| D2 | «Тихий OFF» в легаси-ключе `gates[f]` | `gates[f] = bool(state.effective_runtime)`, а `effective_runtime` включает ось `ready`: ненастроенный провайдер гасил тумблер в UI, хотя чат выбрал ON | `gates[f]` считается по базовому состоянию **без** готовности (как решает воркер), полный снимок с `ready` — в `states[f]` | `test_gates_api_keeps_choice_when_not_ready` |
| D3 | INHERIT ломался при устаревшем токене и «воскресал» на ретрае | набор снятых ключей не доходил до optimistic short-circuit и до retry-merge; `fresh_overrides.update(new_overrides)` возвращал удалённый ключ из свежего root — «наследовать» молча не включалось ровно в конкурентном случае | `removed`-набор прокинут в `set_chat_params` и в retry-merge (`fresh_overrides.pop(key)`), идемпотентный no-op только для чистого INHERIT | `test_inherit_survives_stale_token`, `test_inherit_removes_only_this_chat_override` |
| D4 | Запись того же значения теряла `updated_at`/NOTIFY | идемпотентный short-circuit применялся ко всем записям: повторное сохранение уже установленного значения не двигало optimistic-метку, не писало историю и не отправляло PG NOTIFY → hot-config не доходил до живого процесса | no-op только при чистом INHERIT (`not settings_overrides and new_overrides == base_overrides`); явная запись значения всегда пишет | `test_write_bumps_updated_at_notifies_and_invalidates` (пишется `True` поверх `True`, ожидается `pg_notify == 1` и новая метка) |

## 5. Изменённые ожидания тестов — почему это не ослабление

| Файл : тест | Что изменено | Почему это контракт, а не поблажка |
|---|---|---|
| `tests/test_mod_acl_ux_m2_resolver.py::test_state_snapshot_exposes_separate_axes` | множество ключей снимка расширено на `observed_at, last_activity_at, reason_code, pending_restart, version, can_read, can_edit, consent, conflict` | проверка осталась строгой (`set(snapshot) == {…}`), то есть запрещает лишние/пропавшие поля; расширение соответствует `MAC-S2-85` и не ослабляет ни одного прежнего утверждения |
| `tests/test_lore_worker.py::TestProfileGates::test_auto_flag_disabled_skips` | `reason == "auto_flag_disabled"` → `"gate_lore_auto"` | прежний код причины принадлежал **второму решателю** внутри воркера (`hot.get("flags.lore_auto_enabled")`); после снятия второго решателя причина приходит из канонического резолвера. Тест по-прежнему требует `skipped` и `llm.call_count == 0` — свойство безопасности не ослаблено |
| `tests/test_lore_worker.py::TestProfileGates::test_manual_ignores_period_but_respects_gates` | тот же код причины; добавлен `test_global_off_chat_on_lore_runs` | смена кода причины обязательна (решатель теперь один), плюс новый тест закрывает прежнюю дыру: GLOBAL OFF + явный чат ON реально генерирует |
| родительский набор 409-контракта | удалено прежнее ожидание 409 у `POST /api/config` со устаревшим токеном | это было **вакуумное** утверждение: `/api/config` по документированному контракту (2.58.139, ADR-1025-2 D-409-3) делает один bounded-ретрай с merge, а строгий 409 живёт на прямом пути `set_chat_params` (`ChatParamsConflict`). Оба родительских теста на месте и проходят: `tests/test_chat_params.py::test_set_chat_params_conflict` и `tests/test_asap8_v63_b10r09_settings_409_race.py::test_concurrent_edit_race_409_then_refresh_retry`. Замена ожидания в новых тестах (`test_stale_token_recovers_and_keeps_foreign_keys`) проверяет более сильное свойство: значение применено, чужие ключи целы, метка сдвинута, NOTIFY отправлен |

## 6. Что осталось PENDING и при каком условии

Срез `M2` после привязки: **23 VERIFIED**, **31 PENDING**. Ни одна строка не помечена VERIFIED
без доказательства на этом кандидате.

| Группа | Строки | Точное условие закрытия |
|---|---|---|
| Impact report — **закрыто** отдельным прогоном | `MAC-S2-105`, `MAC-S2-106`, `MAC-S10-10` | повторный read-only прогон на `3b1ba3b2` выполнен: `reports/m2-impact-3b1ba3b2.md` (sha256 `1227f1ce…e0d1`, docs-коммит `de9addc5` на `release/2.58.174`). Измеренный ответ: 16 capability × 3 профиля, **0 изменённых пар**, 0 чатов с изменением поведения; единственная строка «явный чат ON при глобальном OFF» — `gate:permsoc` в чате `-1002661910336`, и она резолвилась ON и раньше. Оговорка: прод `2.58.174` (`ac943f40`) не содержит `resolve_capability`, поэтому колонка OLD — реконструкция домигрированной семантики, а не рантайм прода (см. §7 и сам отчёт, раздел «Остаточные риски») |
| Живое наблюдение (`live_required: true`) | `MAC-S2-81`, `MAC-S2-TT-1…6`, `MAC-S2-AX-05`, `MAC-S2-SHARED-01`, `MAC-S10-01`, `MAC-AC-02`, `MAC-AC-03`, `MAC-AC-04`, `MAC-S15-12`, `MAC-S15-1-01` | выкат кандидата и наблюдение на **задеплоенном SHA**: пять комбинаций truth-table на реальных чатах, «включён · работа не подтверждена» на живом экране, реальные события для оси `observed`, shared scheduler при GLOBAL OFF, сохранность промптов/ключей/ролей после деплоя |
| CHAT OFF в полёте (in-flight) | `MAC-S2-113`, `MAC-S2-114`, `MAC-S2-115` | проверка настройки перед первым side effect инициативы; остановка новой обработки с сохранением истории/прошлых ответов/индекса; повторное включение без replay/backfill. Ни один из трёх сценариев кандидат не исполняет |
| Прочие сценарии §10 | `MAC-S10-03`, `MAC-S10-04`, `MAC-S10-05`, `MAC-S10-07`, `MAC-S10-08`, `MAC-S10-09`, `MAC-S10-14`, `MAC-S10-15`, `MAC-S10-19`, `MAC-S10-20` | 409 без потери записи и двойной клик (UI-путь M4C; прямой контракт `set_chat_params` подтверждён родительским набором); late-ответ при смене чата; сценарий рестарта процесса; in-flight при CHAT OFF; retrieval у B при OFF у A; старые сохранённые флаги; «Время»/timezone; векторный поиск; runtime counters на проде; отложенный результат |
| Документальная инвентаризация | `MAC-S2-102` | приложить инвентарь storage-ключей и **всех** runtime-читателей (hot.get, `get_chat_param`, `gates_enabled`, env-guards, workers, schedulers, UI). В кандидате перечислены 6 потребителей, но не tool router, планировщики и UI |
| Деплой | `MAC-S0-03` | деплой кандидата: снимок сохранённых значений/промптов/версий до и после, diff миграций. M2 DDL не вводит — это подтверждается пустым diff'ом при упаковке, а не ссылкой на отсутствие изменений |
| Сводная строка среза | `MAC-M2-01` | закрывается только после всех строк M2, включая impact report на финальном кандидате и живые наблюдения |

## 7. Честная граница

- PM не перепрогонял тесты: имена тестов и утверждения взяты из дерева `3b1ba3b2`, поведенческий
  вердикт — независимого Reviewer.
- Кандидат **не развёрнут**; ни одно живое поведение этим артефактом не подтверждено.
- `deployed_commit` карты по-прежнему указывает на релиз M5L (`bee14188`) и к M2 не относится;
  строка «M2 выкачен» этим артефактом не появляется.
- Impact report на финальном кандидате выполнен отдельным read-only прогоном
  (`reports/m2-impact-3b1ba3b2.md`), привязан к тем же трём строкам; его колонка OLD —
  **реконструкция** домигрированной семантики (прод `2.58.174` не содержит `resolve_capability`),
  поэтому это не живое сравнение рантаймов, а сравнение семантик на реальных сохранённых строках.
  Ни один чат при выкате не меняет поведение; живые подтверждения остаются за live-строками.

## 8. Результат gate (main checkout, `--repo .`)

До привязки, кандидат `3b1ba3b2`:

```
requirements_gate.py check --map plans/features/mod-acl-ux-01/requirements-map.json \
  --stage review --slice M2 --candidate 3b1ba3b2… --repo .
→ stage=review inventory=279 manual=99 scoped=54 errors=67
```

Категории 67 ошибок: 1 `candidate mismatch` (карта была привязана к `97cfdef1`), 42 ×
`mandatory not ['VERIFIED'] (got PENDING)`, 12 × пара `no evidence bound to reviewed candidate` +
`no candidate-bound evidence points to an existing repo artifact`.

После привязки — результат в §9 ниже (числа сняты фактическим прогоном, а не ожиданием).

## 9. Фактический результат после привязки

```
--stage plan   → stage=plan   inventory=279 manual=99 scoped=0  errors=0
--stage review --slice M2 --candidate 3b1ba3b2… --repo .
               → stage=review inventory=279 manual=99 scoped=54 errors=34
```

Все 34 ошибки одной категории — `mandatory not ['VERIFIED'] (got PENDING)`. Ни одной ошибки привязки
доказательств (`artifact_path`/`artifact_sha256`), ни `candidate mismatch`, ни ошибки slice-graph:
20 привязанных строк прошли strict-проверку существования артефакта, Git-объекта кандидата и типа
доказательства.

Итог по срезу: **23 VERIFIED / 31 PENDING** после привязки impact report
(`reports/m2-impact-3b1ba3b2.md`: `MAC-S2-105`, `MAC-S2-106`, `MAC-S10-10`; прогон по срезу —
`scoped=54 errors=31`, единственная категория `mandatory not ['VERIFIED'] (got PENDING)`).
Полного `VERIFIED` у M2 нет — и это состояние среза, а не недоделанная привязка.

