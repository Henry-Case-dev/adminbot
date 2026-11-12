# D2 source-of-truth fix - независимое re-review SD1-D2-23 / SD1-D2-24

Дата: 2026-11-13. Reviewer, не Builder и не автор evidence.
Кандидат: code `aa1d41277acc30d1ba05b537de2d0361f7b166e0`, docs `d79648c4a4458f561da46b9f701dd88b97bf40ed`.
База: `16fa04e77c56db44c23cb5c8a9386f6cfd756628`; предыдущий кандидат `f2f25838` (Needs Fixes).
Diff `f2f25838..HEAD`: `param_catalog.py`, `output_projection.py`, `log_ring.py`,
`debug_config.py`, тест-файл и evidence; новых сторов/DDL/настроек нет.

**Вердикт: Approved для D2-23/D2-24.** Блокер единого source-of-truth
закрыт: все пять выходных границ используют `ParamSpec.is_secret_value`
(`resolved_sensitivity == SECRET_VALUE`), legacy `secret` больше не решает
защиту значения. D2/self-diag DONE не объявляется; остальные D2-строки не
пересматривались.

## 1. Что проверено в реализации

- `ParamSpec.is_secret_value` - единственный предикат; `secret` остаётся
  catalog/UI hint. `_catalog_secret_keys`, `_settings_secret_values`,
  `_env_secret_values`, `log_ring._collect_secrets`, `debug_config._is_secret`
  используют его; в secret collection не осталось `if spec.secret`.
- `per_chat`, сохранённые значения, `REGISTRY`, sensitivity/source, audit,
  projection mapping не менялись; 644 legacy-записи по-прежнему имеют
  derived type; `PUBLIC_DIAGNOSTIC` для unknown.
- `log_ring` больше не отдаёт значение нового SECRET_VALUE в строке журнала;
  `debug_config` помечает его `secret=true` и скрывает value.
- Новый `keys.*` с `SECRET_VALUE` + `secret=False` регистрируется,
  `resolved_sensitivity=SECRET_VALUE`, `is_protected=True`; значение
  собирается из env/settings/cache и редактируется.

## 2. Независимое воспроизведение

Временный провайдер `keys.review_provider_key` (`SECRET_VALUE`, `secret=False`),
env/settings/cache токены; независимый прогон на exact candidate:

```text
PREDICATE True False SECRET_VALUE
SNAPSHOT True {env: True, settings: True, cache: True}
CATALOG_HAS True
SANITIZE True partially_redacted False  # токенов в тексте нет
LOG True True                        # *** в строке журнала
DEBUG True True                      # secret=true, value скрыт
NORMAL True False                    # normal secret true; flag false
```

Нормальный secret (`keys.llm_api_key`) остаётся защищённым;
`flags.checkup_enabled` - NON_SECRET_CONFIG; unknown key по-прежнему не
раскрывает значение.

## 3. Тесты и mutation

- 145 focused set (13 sensitivity + 40 catalog + 12 adapter + 22 bundle +
  58 probes) -> **145 passed**.
- 216 core set -> **216 passed**, 1 warning.
- 42 log/debug tests -> **42 passed**.
- 232+cfg03 set -> **232 passed, 1 failed**; failure
  `test_cfg03_param_audit.py::TestConsumerCoverage::test_visible_dead_knobs_are_exactly_documented`
  (`flags.dig_pre_gate_enabled`) pre-existing на базе; BACKLOG.
- **Independent mutation:** в отдельном worktree @ `aa1d4127`
  `_catalog_secret_keys` возвращён к `if spec.secret`;
  `test_new_secret_provider_value_is_collected_and_redacted` -> **1 failed**
  (cache token not in snapshot); restore -> **13 passed**.
- RED на `f2f25838` по binding: 3 failed; GREEN 13.

## 4. Строки D2

- `SD1-D2-23` и `SD1-D2-24`: **REVIEW**-кандидат; blocker снят, независимые
  проверки пройдены.
- Остальные D2-строки (37 VERIFIED/4 READY) не пересматривались и не менялись;
  diff их файлы не затрагивает.
- `cfg03` dead knob - BACKLOG, не D2-блокер. D2/self-diag DONE не объявляется.
- Карта/progress_scope не менялись; PM-синхронизация D2-23/24 после этого
  review.

## 5. Три опоры

- **Implementation:** прочитаны `ParamSpec.is_secret_value`, все пять границ,
  `settings_view`, `config.secret_status`, тест-файл; проверены closed set,
  legacy derivation, отсутствие legacy-фильтра в secret collection.
- **Test validity:** 145/216/42/232(+1 pre-existing) запусканы; assertions
  13 sensitivity и независимый провайдер прочитаны; mutation legacy-filter
  red/restore green.
- **Independent challenge:** новый SECRET_VALUE + secret=False -> env/settings/
  cache в snapshot, tool_result partially_redacted без токенов, log `***`,
  debug `secret=true`; normal secret true, non-secret flag false.

## 6. Итог

**Approved** для D2-23/D2-24 на `aa1d4127` / `d79648c4`. D2/self-diag DONE не
объявляется; остальные D2-строки и PM-синхронизация остаются вне этого
review. Продуктовый код/настройки/прод не менялись; деплоя не было;
mutation worktree и probe-run закрыты.

