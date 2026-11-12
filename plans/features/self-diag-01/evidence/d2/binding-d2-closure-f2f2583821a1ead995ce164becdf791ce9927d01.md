# D2 closure — binding evidence `SD1-D2-23`, `SD1-D2-24`

Кандидат: `f2f2583821a1ead995ce164becdf791ce9927d01` (`self-diag/d2-closure`)
База: `16fa04e77c56db44c23cb5c8a9386f6cfd756628` (`self-diag/d6`)
Статус: **REVIEW** (реализация + кандидат-привязанные проверки; независимое
ревью и производственная приёмка не выполнялись и не заявляются).

Источник требований: `plans/owner_inputs/2026-11-09-self-diag-01.md`
строки 269–270 (§9.1), записи карты `SD1-D2-23`, `SD1-D2-24`
(`plans/features/self-diag-01/requirements-map.json`, `PENDING`).

Дословно:

> 269: Источник истины о секретных полях — конфигурационный каталог/secret
> store с **типами и флагом sensitivity**: `SECRET_VALUE`, `PROMPT_CONTENT`,
> `NON_SECRET_CONFIG`, `PUBLIC_DIAGNOSTIC`. Для нового провайдера метаданные
> sensitivity обязательны при регистрации.
>
> 270: Секретный blob никогда не сериализуется в DiagnosticEvidenceBundle или
> обычный ToolResult. При технической проверке возвращаются `configured`,
> `effective`, `last_success`, `last_error_code`, `key_fingerprint` (только
> если уже безопасно принят проектом), но не value.

Границы задания соблюдены: без деплоя, без правок production/settings/prompts,
без нового стора/БД/агента/LLM/DDL. Значения сохранённых настроек и ключей не
менялись.

---

## 1. Что изменено (6 файлов, +1015 / −8)

| Файл | Роль |
|---|---|
| `services/param_catalog.py` | Канонический закрытый набор sensitivity, `ParamSpec.sensitivity` + `sensitivity_source`, `derived_sensitivity`, `register_param` (обязательный тип), `audit_sensitivity`, import-time fail-fast, `secret_setting_specs` |
| `services/output_projection.py` | `sensitivity_of_pg_key` больше не выводит правило само — читает `spec.resolved_sensitivity` (одно место истины); константы зеркалят каталог |
| `services/settings_view.py` (новый) | Typed settings adapter: `setting_view`, `capability_outcomes`, `secret_status_summary`, `compact_view`, `secret_setting_keys` |
| `services/runtime_probes.py` | Probe `config.secret_status` (area `config`, scope `instance`) поверх адаптера и существующего D3-коллектора |
| `tests/test_param_sensitivity_registration.py` (новый) | 10 тестов D2-23 |
| `tests/test_diagnostic_settings_adapter.py` (новый) | 12 тестов D2-24 |

Документы/машиночитаемые артефакты этого же среза:
`plans/features/self-diag-01/evidence/d2/binding-d2-closure-f2f2583821a1ead995ce164becdf791ce9927d01.md`,
`sd1_d2_23.json`, `sd1_d2_24.json`, `collect_d2_closure.py` (измеритель).

---

## 2. `SD1-D2-23` — каталог как источник истины, sensitivity обязательна

### 2.1. Тип записан в самой записи каталога

`ParamSpec` получил `sensitivity` (закрытый набор из 4 значений) и
`sensitivity_source` (`declared` | `legacy_derivation`). Легаси-строки не
переписывались вручную: `_build_registry()` фиксирует для них выведенный тип
**в самой записи** с явной пометкой происхождения, а не оставляет пустое
значение и не полагается на вывод «на месте использования».

Измерено на кандидате (`sd1_d2_23.json`):

```
registry_entries = 644
sensitivity_distribution = {SECRET_VALUE: 41, NON_SECRET_CONFIG: 575,
                            PROMPT_CONTENT: 28}
sensitivity_source_distribution = {legacy_derivation: 644}
audit_problems = []
projection_matches_catalog = true
```

`PUBLIC_DIAGNOSTIC` в распределении отсутствует осознанно: это класс для
данных вне каталога (ключ не найден), и `sensitivity_of_pg_key` возвращает его
именно в этом случае — поведение не менялось.

Правило вывода легаси-типа консервативно и совпадает с прежним правилом
проекции: `keys.*` целиком → `SECRET_VALUE` (в категории есть и несекретные по
смыслу ключи `keys.random_quantum_*`; сужать защиту было бы послаблением),
`prompts.*` → `PROMPT_CONTENT`, остальное → `NON_SECRET_CONFIG`.

### 2.2. Обязательность при регистрации нового провайдера

Единственная публичная точка регистрации нового параметра/провайдера —
`param_catalog.register_param(spec, registry=..., replace=...)`:

* без явного `sensitivity` → `ParamSensitivityRequired` (подкласс
  `ParamSensitivityError`), запись в реестр не попадает;
* объявленный тип обязан совпадать с классом записи: `keys.*` нельзя объявить
  `NON_SECRET_CONFIG`, `secret=True` нельзя объявить несекретным →
  `ParamSensitivityError`;
* тихого `secret=False` у нового провайдера не существует: не указал тип —
  ошибка, а не «по умолчанию несекретно»;
* дубликат ключа без `replace=True` — прежняя ошибка (поведение сохранено).

`ParamSpec.__post_init__` отклоняет неизвестный тип и противоречивые метаданные
при любом пути создания записи, а `audit_sensitivity()` вызывается на импорте
каталога: противоречивая строка ломает сборку, а не утекает в вывод.

### 2.3. Тесты (`tests/test_param_sensitivity_registration.py`, 10 passed)

| Тест | Что реально утверждает |
|---|---|
| `test_new_provider_without_sensitivity_is_rejected` | новый ключ провайдера без типа → `ParamSensitivityRequired`, реестр пуст |
| `test_new_provider_unknown_sensitivity_is_rejected` | `sensitivity="TOP_SECRET"` → `ParamSensitivityError`, реестр пуст |
| `test_new_provider_with_sensitivity_registers` | с `SECRET_VALUE` регистрация проходит, `sensitivity_source="declared"`, `is_protected`, `per_chat=False` |
| `test_provider_credential_cannot_be_declared_non_secret` | `keys.*` как `NON_SECRET_CONFIG` (и `secret=True` + несекретный тип) → отказ, реестр пуст |
| `test_new_non_secret_config_requires_explicit_class` | несекретный `models.*` регистрируется только с явным `NON_SECRET_CONFIG`; без типа — отказ |
| `test_duplicate_registration_is_still_rejected` | дубликат без `replace` — `ValueError`, с `replace` — одна запись |
| `test_every_catalog_entry_records_a_sensitivity_type` | у всех 644 записей тип из закрытого набора, источник заполнен, `resolved_sensitivity == sensitivity`, `audit_sensitivity() == []` |
| `test_audit_detects_contradictory_metadata` | аудит находит запись без типа («sensitivity not recorded») |
| `test_projection_reads_catalog_instead_of_duplicating_the_rule` | для всех 644 ключей `output_projection.sensitivity_of_pg_key == spec.resolved_sensitivity`; константы проекции и каталога совпадают |
| `test_existing_secret_and_prompt_classes_are_unchanged` | `keys.llm_api_key`/`postgres_password` секретны, промпт → `PROMPT_CONTENT`, флаг → `NON_SECRET_CONFIG`, неизвестный ключ → `PUBLIC_DIAGNOSTIC`, `per_chat` не изменился |

---

## 3. `SD1-D2-24` — typed settings adapter, blob не сериализуется

### 3.1. Адаптер (`services/settings_view.py`)

`setting_view(pg_key, cache=..., outcomes=...)` — закрытый набор полей
(`VIEW_FIELDS`): `key`, `classified`, `sensitivity`, `sensitivity_source`,
`configured`, `effective`, `effective_kind`, `effective_source`,
`value_exposed`, `last_success`, `last_error_code`, `last_checked_at`,
`outcome_observed`, `key_fingerprint`, `fingerprint_kind`, `reason_code`.

Правила (наблюдаемые, а не «по фильтру слов»):

* `SECRET_VALUE` / `PROMPT_CONTENT` → `effective` = статус-токен
  `configured`/`not_configured`, `value_exposed=false`, значения нет ни в одном
  поле;
* `NON_SECRET_CONFIG` / `PUBLIC_DIAGNOSTIC` → `effective` = действующее
  значение, `value_exposed=true`;
* ключ вне каталога и вне реестра credential-полей → `classified=false`,
  `effective=null`, `reason_code=unclassified_key` (факт наличия — можно,
  значение — нельзя, пока каталог не объявил класс);
* `key_fingerprint` — только `last4` (уже принятая проектом форма
  `project_secret_value`), только для скалярного `SECRET_VALUE` длиной ≥ 8;
  промпты и списки фингерпринта не получают;
* источник значения: кэш настроек (`pg`) → env (`env`) → Settings-дефолт
  (`settings`) → `none`.

`last_success` / `last_error_code` берутся из **существующих** наблюдаемых
исходов `capability_registry.capability_view` (`last_result`,
`last_result_code`, `checked_at`, связь через `gates`-ключи); второго стора
нет. Где исхода ещё не было — `None` и `outcome_observed=false`.

Измерено (`sd1_d2_24.json`, фейковый кэш со значением
`sk-live-abcdef123456`):

```
secret_view.effective = "configured", effective_kind = "status",
value_exposed = false, key_fingerprint = "…3456", last_success = null,
last_error_code = null
secret_value_in_view = false
config_view_effective = 1200, value_exposed = true
summary_total = 44, summary_configured = 9, summary_value_exposed = false
```

### 3.2. Bundle и обычный ToolResult

Probe `config.secret_status` (area `config`, scope `instance`) отдаёт сводку
адаптера через **существующий** D3-коллектор и `DiagnosticEvidenceBundle`:
настроенные ключи — с полями §9.1, ненастроенные — только именами; подробности
ограничены `MAX_DETAILED_SECRETS=20`, остальные имена — в `truncated_keys`
(молчаливого усечения нет), `value_exposed=false` в самой сводке,
`not_checked=(secret_values, live_provider_probe[, provider_outcomes])`.

Обычный ToolResult (`inspect_runtime` → `ToolRouter._diagnostic_output`) идёт
через **ту же единственную** границу редактирования (`output_projection.
sanitize(kind="tool_result")`), без второго фильтра и без новых правил
редактирования; при неполных источниках секретов результат блокируется
(fail-closed) — проверено тестом.

### 3.3. Тесты (`tests/test_diagnostic_settings_adapter.py`, 12 passed)

| Тест | Что реально утверждает |
|---|---|
| `test_adapter_returns_closed_field_set_without_secret_value` | набор полей = `VIEW_FIELDS`; `configured=true`, `effective="configured"`, `value_exposed=false`, фингерпринт `…3456`; значения нет в сериализованном виде |
| `test_prompt_content_is_a_status_not_a_text` | промпт → `PROMPT_CONTENT`, статус-токен, нет фингерпринта, текста нет |
| `test_non_secret_config_keeps_its_value` | `limits.checkup_max_symbols` → `effective=1200`, `value_exposed=true` |
| `test_unclassified_key_never_leaks_value` | неизвестный ключ → `classified=false`, значения нет, `reason_code=unclassified_key` |
| `test_short_and_list_values_get_no_fingerprint` | значение из 3 символов и список ключей фингерпринта не получают, ни один фрагмент не печатается |
| `test_capability_outcomes_map_gates_to_provider_results` | `success → last_success`, `failed → last_error_code`, `unknown` не выдумывает исход |
| `test_summary_is_bounded_and_reports_truncation` | `max_detailed=5` → 5 подробностей + `truncated_keys`, `value_exposed=false`, значений в JSON нет |
| `test_bundle_has_required_fields_and_never_the_secret` | bundle/page: значения нет; у `keys.image_api_key` есть `configured/effective/key_fingerprint/last_success/last_error_code`; `not_checked` содержит `secret_values` |
| `test_provider_outcomes_reach_the_bundle` | инжектированный исход провайдера доходит до bundle (`last_error_code=provider_timeout`) |
| `test_tool_result_never_contains_secret_blob` | реальный `dispatch("inspect_runtime")` с настоящей output-границей: значения нет, набор полей = `COMPACT_FIELDS`, поля присутствуют |
| `test_secret_never_appears_in_logs` | за весь прогон (DEBUG) ни одна запись журнала не содержит значение/фрагмент |
| `test_tool_result_blocked_when_secret_sources_incomplete` | неполные источники секретов → tool result заблокирован (fail-closed) |

---

## 4. RED → GREEN

RED снят на базовом кандидате `16fa04e7` (те же тест-файлы, исходники
возвращены к базе, `settings_view.py` убран из пакета):

```
tests/test_param_sensitivity_registration.py → 10 failed
  AttributeError: module 'services.param_catalog' has no attribute
  'SENSITIVITY_PROMPT_CONTENT' / 'register_param'
tests/test_diagnostic_settings_adapter.py → collection error
  ImportError: cannot import name 'settings_view' from 'services'
```

Характер RED честный: оба требования вводят новый контракт (тип в каталоге,
обязательная регистрация, адаптер), поэтому «до» контракта нет вовсе —
поведенческого RED для уже существующей защиты секретов не существует, она
работала и до среза.

GREEN на `f2f25838`:

```
tests/test_param_sensitivity_registration.py → 10 passed
tests/test_diagnostic_settings_adapter.py     → 12 passed
```

---

## 5. Прогоны (точные счётчики, команды дословно)

```
python -m pytest tests/test_param_catalog.py tests/test_param_sensitivity_registration.py \
  tests/test_diagnostic_policy.py tests/test_diagnostic_probes.py \
  tests/test_evidence_bundle.py tests/test_diagnostic_settings_adapter.py -q
→ 213 passed, 1 warning

python -m pytest tests/test_checkup_contract.py tests/test_prompt_readback.py \
  tests/test_cfg03_param_audit.py tests/test_chat_params.py tests/test_settings_helpers.py \
  tests/test_asap7_direct_settings.py tests/test_rlr_admin_manifest.py \
  tests/test_summary_param_catalog_annotation_asap41.py \
  tests/test_mod_acl_ux_01_m4_module_params.py -q
→ 232 passed, 1 failed (pre-existing, см. §7)

python -m pytest tests/test_param_catalog.py -q          → 40 passed
python -m pytest tests/test_evidence_bundle.py -q        → 22 passed
python -m pytest tests/test_diagnostic_probes.py -q      → 58 passed
```

D6/D3/D4/D5-затронутые наборы (`test_checkup_contract`, `test_prompt_readback`,
D3 probes/bundle) входят в прогоны выше и зелёные. Полный набор репозитория
намеренно не запускался (границы задания).

---

## 6. Effective configuration / blast radius

* Новых флагов, env-переменных, persisted-настроек и DDL нет; `bot_settings`
  не читается иначе, значения не пишутся.
* Probe `config.secret_status` регистрируется динамически (как остальные
  builtin-probes); лимиты `SELF_DIAG_PROBE_*` не менялись
  (`max_output_chars=9000` по умолчанию). Измеренная страница на этом
  окружении — 5019 символов, `facts_omitted` не возникает (подробностей 8,
  всего ключей 44); при аномально большом числе настроенных ключей работает
  наблюдаемое усечение (`truncated_keys` + `MAX_DETAILED_SECRETS=20`).
* Область данных probe — `instance`; доступ к `inspect_runtime` остаётся
  прежним (`deep_diagnostics`, CHAT_SCOPED); содержимого секретов probe не
  возвращает ни одной роли.
* Секретные значения по-прежнему даёт только существующая граница
  `output_projection`; новых путей выдачи нет.

---

## 7. Честные границы (что НЕ доказано)

1. `register_param` пока не имеет производственного вызывающего: существующие
   644 записи построены легаси-путём `_build_registry` (тип выведен и записан
   с пометкой `legacy_derivation`). Мандат «sensitivity обязательна»
   действует для **новой** регистрации через публичный API и для аудита на
   импорте; массовая ручная разметка 644 легаси-строк не выполнялась (это был
   бы риск без пользы для поведения).
2. `last_success`/`last_error_code` заполняются только там, где
   `capability_registry` уже наблюдал исход вызова (image/web search/
   dependencies). Для остальных ключей — `None` + `outcome_observed=false` +
   `not_checked` с `live_provider_probe`: живых сетевых проб среза не делает.
3. `key_fingerprint` = `last4` — уже принятая проектом форма; для списков,
   промптов и значений короче 8 символов фингерпринт не выдаётся.
4. Реальные прод-значения и реальные коды отказа провайдеров не проверялись:
   деплоя в этой задаче нет, production не трогался.
5. UI/API-поверхность не менялась (новых маршрутов/рендера нет), поэтому
   визуальные проверки к этому срезу неприменимы.
6. Полный регресс репозитория не выполнялся — только заявленные затронутые
   наборы.

---

## 8. Найденное вне scope (BACKLOG_ONLY)

`tests/test_cfg03_param_audit.py::TestConsumerCoverage::test_visible_dead_knobs_are_exactly_documented`
падает **и на базе `16fa04e7`** (проверено прогоном того же файла в
worktree базы): недокументированная «мёртвая ручка»
`flags.dig_pre_gate_enabled`. К этому кандидату отношения не имеет, не
исправлялось; нужна отдельная строка бэклога PM.

---

## 9. Машиночитаемые артефакты

* `plans/features/self-diag-01/evidence/d2/sd1_d2_23.json` — измеренные
  значения каталога, гейт регистрации, RED/GREEN, прогоны.
* `plans/features/self-diag-01/evidence/d2/sd1_d2_24.json` — поля адаптера,
  фактические значения представлений, сводка, прогоны, границы.
* `plans/features/self-diag-01/evidence/d2/collect_d2_closure.py` — измеритель,
  которым получены оба JSON (запускается из корня worktree).

Статусы строк в карте не менялись: `SD1-D2-23`, `SD1-D2-24` остаются
`PENDING` до независимого ревью и привязки PM/Orchestrator.
