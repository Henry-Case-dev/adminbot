# QUOTA-REMOVAL — evidence (ADDENDUM #3 §2.7, A1–A6)

Лейн: `QUOTA-REMOVAL` (backend; UI-панель бюджета — отдельная полоса).
Источник: `plans/features/p0-corrective-factcheck-speech/arch-quota-audit.md` §2 A1–A6, §3;
`source-addendum3-2026-10-24.md` §2.1–§2.10.
Кандидат: см. `git log -1 --format=%H` в конце файла (поле `candidate`).

## A1 — `composer_additive_budget_tokens()` + `COMPOSER_LAYER_BUDGET_TOKENS`

| | было | стало |
|---|------|-------|
| `services/mca_gates.py` | `composer_additive_budget_tokens()`: `getattr(settings,…)` + env-ветка, дефолт **1200**, `<=0 → 0` (не `None`) — строки 2473–2495 | функция **удалена** целиком; env/`settings` больше не читаются (ключа в `config/settings.py`, `param_catalog.py`, `config_migrations.py` не было — миграция не требуется) |
| семантика `0/None` | третье состояние, включавшее/выключавшее вытеснение | исчезла вместе с функцией; новых состояний не введено |
| витрина | `web/api/speech.py:_composer_budget()` → `mca_gates.composer_additive_budget_tokens()` | вызов теперь даёт `AttributeError` внутри существующего `try/except` → `0`; панель/строку удаляет UI-полоса. `core_selection_view(..., budget_tokens=…)` принимает аргумент **инертно** (совместимость окна до UI-правки), значение не влияет |

Проверка: `tests/test_quota_removal_composer.py::test_quota_api_is_gone_not_disabled`,
`::test_long_instructions_reach_payload_whatever_env_says[0/-1/1/40]`.

## A2/A3/A6 — Composer: вытеснение слоёв и `budget_excluded`

| | было | стало |
|---|------|-------|
| `services/prompt_composer.py` | `budget = …; consumed = 0` (1242–1243); `if budget is not None and consumed + cost > budget` в 6 местах (1330 Core, 1523 Expression, 1574 humor, 1612 expression_examples, 1641 samples, 1680 hint) | `budget`/`consumed` удалены; ни одна ветка вытеснения не осталась |
| Core | конфликт `core_protected_from_budget` (`exempted_protected`) + расход | конфликт не производится; Core рендерится всегда, `detail_level` — единственный источник |
| Expression | конфликт `expression_protected_from_budget` + WARN | не производится |
| `humor_craft` / `expression_examples` / `few_shot` / `style_policy_hint` | `skip_reason="budget_excluded"` при исчерпании 1200 | рендерятся при применимости; `skip_reason` — только смысловые (`*_absent`, `*_disabled`, `profile:*`, `not_owner_approved`) |
| закрытый набор | `SKIP_REASONS` содержал `budget_excluded` (+ человекочитаемая метка) | удалено из набора и из `LAYER_SKIP_LABELS`; `SKIP_REASONS` остаётся закрытым |
| события | `reason=="budget_excluded"` → `skipped/INFO/budget_exceeded` | ветка удалена; производителя причины нет |
| `_BUDGET_LAYERS` | кортеж «слои под бюджетом» | удалён (был мёртвым после снятия квоты) |
| сохранено | — | порядок слоёв (`LAYER_ORDER`), `_append`/`_joined`, `traces`, `ConflictRecord`, `estimate_tokens` (только `tokens_total`), `manifest_for_events` |

Прод-симптом `style_policy_hint → budget_excluded` закрыт:
`tests/test_asap3_acceptance.py::test_s10_composer_style_layer_has_no_local_quota` (env `=1`, hint в payload).

## A4 — Personality Core: принудительное `full → compact`

`services/prompt_registry.py`:
- было: `core_selection(..., budget_tokens=…)` + `elif budget_tokens and budget_tokens > 0 and _token_estimate(full_text) > budget_tokens: level, reason = "compact", "context_budget"` (1209–1214);
- стало: параметр и ветка удалены; причина `context_budget` убрана из `CORE_DETAIL_REASONS`;
- `full_text_missing` / `compact_text_missing` (fallback редакции) сохранены; `owner_setting`/`factory_default`/`document_default` без изменений;
- `core_selection_view`: ключ `budget_tokens` больше не публикуется (Inspector не показывает удалённую настройку).

Проверка: `test_soul1_core_composer_integration.py::test_full_requested_is_never_downgraded_by_local_quota`
(env `=3` → `level=full reason=owner_setting`), `test_soul1_core_registry_api.py::test_core_selection_is_deterministic_and_reasons_are_closed`.

## A5 — Expression few-shot: `MAX_ITEMS=4 / MAX_CHARS=700 / MAX_TOKENS=140`

`services/mca_expression.py`:
- константы `EXPRESSION_EXAMPLES_MAX_ITEMS/MAX_CHARS/MAX_TOKENS` **удалены** (181–185);
- `render_expression_examples_block`: цикл «pop последней строки, пока блок не влезет» удалён (518–542) — в блок входят все применимые строки; `ExampleRender` продолжает отдавать честные числа (`total_items`/`included_items`/`dropped`/`limited_by`);
- `build_expression_examples_refs`: ветка `skip_reason="budget_excluded"` при «не влезло ничего» удалена (596–599); `not_owner_approved` (смысловая причина) сохранена;
- WARN о частичном составе переименован `examples capped` → `examples selected` (числа те же: `kept=X/Y`, `by=…`; R17 — без текста реплик).

Реальное переполнение окна: не локальная квота, а `model_capacity`/`CHAT_CONTEXT_BUDGET_TOKENS`
на стороне вызова — не изменялись. Честная деградация окна остаётся там же.

Остаточное ограничение (вне WRITE_SCOPE лейна, зафиксировано для Architect):
`services/mca_sample_library.py:71 EXPRESSION_RESOLVE_MAX_ITEMS = 4` ограничивает **отбор**
строк из библиотеки (категория B аудита — «ограничения числа элементов выборки»), поэтому
при >4 одобренных примерах в блок войдут 4. Рендер их больше не режет; потеря видна числами
(`kept=4/N`) и не маскируется под «набор пуст».

## A6 — сравнение с бюджетом у Core/Expression

Сравнения и служебные `ConflictRecord` удалены вместе с `budget`/`consumed`; `conflicts`
продолжает нести смысловые записи (например, `stale_soul_label`). Проверка отсутствия
служебных id: `test_quota_removal_composer.py::test_quota_api_is_gone_not_disabled`.

## B — сохранено (не тронуто)

`model_capacity` / `CHAT_CONTEXT_BUDGET_TOKENS` / `limits.chat_context_budget_tokens` (модуль
«Бюджеты» и его UI), `summary_hybrid_budget`, `llm_client.max_tokens`, retry/fallback/таймауты,
`token_counter`, `context_middleware`, rate limits, `{max_symbols}`, лимиты выборки/ранжирования,
`mca_gates.adaptive_context_budget_enabled`, `style_policy.hint_limits` (C4: дефолт 0 = off,
видимый выбор владельца).

## Тесты

Новые: `tests/test_quota_removal_composer.py` (7 тестов, `TEST-LIFECYCLE: REGRESSION`).
Переведены на новый контракт (защищали отменённую квоту): `test_soul1_composer_layers.py`,
`test_soul1_core_composer_integration.py`, `test_soul1_core_registry_api.py`,
`test_add_exp_expression.py`, `test_p0e_expression_frequent.py`, `test_asap3_acceptance.py`,
`test_asap3_hidden_limits.py`. Удалён `test_inspector_shows_budget_class_for_expression_conflict`
(проверял отображение несуществующего конфликта).

Прогоны (Python 3.12, локально, без сети/прода):

| набор | результат |
|-------|-----------|
| `test_quota_removal_composer.py` + `test_soul1_composer_layers` + `test_soul1_core_composer_integration` + `test_soul1_core_registry_api` + `test_soul1_composer_parity_off` + `test_add_exp_expression` + `test_p0e_expression_frequent` + `test_p0_expression_final_contract` + `test_asap3_acceptance` + `test_asap3_hidden_limits` + `test_asap2_boundary_marker` + `test_direct_context_composer_asap3` + `test_expression_isolation_followup` | **186 passed** |
| `-k "soul1 or inspector or prompt_layers or mca_events"` | **689 passed** |
| `-k "composer or expression or prompt_registry or core_selection or style_policy or budget"` | 614 passed, 1 failed — `test_direct_fallback_recompose_asap32` (см. ниже) |
| `-k "p0_ or asap"` | 2592 passed, 9 failed + 7 errors — все вне лейна (см. ниже) |

Pre-existing/внешние (подтверждено прогоном на чистом `HEAD` в отдельном worktree):
`test_direct_fallback_recompose_asap32` (5), `test_summary_asap2_failsoft_round1027` (1),
`test_asap7_direct_settings` (2) — падают на `HEAD` без правок лейна
(`llm_client._fallback_with_retries(..., sent=…)` vs тестовые стабы; summary-cover mock).
`test_p0_vision_ui_e2e` (7 errors) — в окружении нет модуля `playwright`
(UI-полоса/визуальные проверки). `test_asap8_initreply_binding::test_case7` — нестабилен
по порядку, в изоляции проходит (14 passed).

## Риск

R2 (из аудита §6): снятие квот увеличивает payload. Закрывается реальным окном
(`model_capacity`) и честной деградацией, а не новым лимитом инструкций. Проверка на боевой
модели — вне лейна (без сети/прода).

candidate: `2156b79682e5bf4188b7dcf3d628ba55061d8f2b`
