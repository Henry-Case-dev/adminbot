# W-A1 отчёт — ASAP 8 v6, Wave A (D08 + D09-S)

Lane: W-A1 (writer). Baseline: HEAD `1e98027` + незакоммиченный кандидат W-A3
(`services/chat_lore_store.py`, `handlers/chat_lifecycle.py`) — не тронут, тесты
прогнаны поверх как есть. Дата: 14.10.2026. Коммит: НЕТ (по брифу).

## FIX 1 — D08 P0: PG-only ключи отсутствовали в /api/config (тумблер Random)

Root cause (подтверждён, не переоткрывался): `config_cache.get_all()` синтезировал
catalog-only items только для группы `keys_random`; PG-only ParamSpec
`memory.random_enabled` (нет Settings-поля, нет строки bot_settings до первой
записи, сидом не создаётся — `pg_db._seed_settings` пропускает PG-only) отсутствовал
в снапшоте → `GET /api/config` не отдавал ключ → карточка Random получала null →
toast «Параметр недоступен: memory.random_enabled» (владелец не мог управлять
мастером модуля из UI вообще).

Фикс (`services/config_cache.py`):
- `_synthetic_group_items()` обобщена: слой D13 (keys_random) сохранён
  байт-в-байт (секреты → "", не-секреты с Settings-полем → дефолт Settings);
  добавлен слой для ВСЕХ PG-only ключей каталога (`settings_field is None and
  env_name is None`, категория задана, не `hidden`).
- Честные дефолты по классам спецификации:
  - `code_source` → `resolve_code_source` (прецедент сида; не резолвится → item
    не синтезируется, WARNING);
  - секрет → `""` → маска routes `{configured: false, last4: null}` (ANU-прецедент);
  - bool → `module_registry.PRODUCT_DEFAULTS` → `_PG_ONLY_BOOL_DEFAULTS` (новая
    таблица — ЗЕРКАЛО рантайм-резолверов: direct_l1 True/True, summary-флаги из
    env ClassVar, chat_silent_ack из env, random_enabled True (F5 §5.3),
    random_uses_* True (MCA-10b fail-open)); не покрытый таблицей bool НЕ
    синтезируется (угаданный bool не выдаём), контракт-тест требует полного
    покрытия каталога;
  - str → `""` («пусто = наследуется/по умолчанию» — семантика слотов);
  - int/float/json → `None` («не задано владельцем»).
- Честный флаг источника: синтетический item → `get_updated_at(key) is None`
  (default); после первой записи — persistent (строка БД/память, синтетика
  уступает).
- Env AND-гейт и рантайм не затронуты: `get()`/`hot_config` читают только
  `_settings` (bot_settings), синтетика живёт только в `get_all()`;
  `MCA_RANDOM_SOURCE_ENABLED` не читается и не дублируется.

## FIX 2 — D09-S: `int(x or 7)` подменял валидный 00:00

Фикс (`services/dream_worker.py`): новый хелпер `_hour_or(raw, default)`
(семантика как у `_hour_number`-прецедента `_hot_number`, S10.13-7:
None/missing/пусто/мусор → default, числовой 0 и "0" → 0), применён во ВСЕХ
местах файла с часовой семантикой:
- `:1691` `memory.deep_sleep_hour` (per-chat hot, Deep Sleep fixed) — прежний
  литерал `or 7` заменён на env-дефолт `settings.DEEP_SLEEP_HOUR`;
- `:1080` `window_start_hour` (per-chat hot) — прежний `or 4` →
  `settings.DREAM_WINDOW_START_HOUR`;
- `:1085` `window_end_hour` (per-chat hot) — прежний `or 6` →
  `settings.DREAM_WINDOW_END_HOUR`.

Сознательно НЕ трогал (не часовая семантика, 0 не является валидным значением):
`DREAM_TICK_MINUTES or 60`, окна/лимиты/пороги (`or 168/5/10/30/2/3/12/5`) —
fail-safe полы; `_daily_limit_for ... or 0` уже zero-safe.

## Acceptance — по пунктам

| Пункт | Статус | Доказательство |
|---|---|---|
| D08: `memory.random_enabled` в /api/config без строки БД | PASS | `test_d08_random_enabled_present_without_db_row`; RED-проба: старая синтетика → ключа нет, новая → есть |
| D08: значение default | PASS | `test_d08_synthetic_items_are_default_source` (True + updated_at None) |
| D08: после записи — persistent | PASS | `test_d08_write_makes_item_persistent`, `test_d08_persistent_row_wins_over_synthetic` |
| D08: env AND-гейт не задет | PASS | `test_d08_runtime_read_and_env_gate_unaffected` (get()/ENV_GATES не тронуты); M7/M6 сюиты зелёные |
| D08: существующие config-тесты без просадки | PASS | test_config_cache, test_hot_config, test_webapp_api, test_global_config_optimistic_round1025, test_debug_config_handler — зелёные |
| D08: ANU-синтетика keys_random не сломана | PASS | `test_d08_anu_keys_random_synthesis_intact` + test_asap5_random_bootstrap_config (5/5) |
| D08: ВСЕ PG-only ключи синтезируются честно | PASS | `test_d08_all_pg_only_keys_present_with_honest_defaults` (70 ключей), `test_d08_pg_only_bool_defaults_cover_catalog` (контракт покрытия), маска секрета — `test_d08_api_render_contract_for_synthetic_items` |
| D09: 00:00 → 0 | PASS | `_hour_or(0,7)==0`; `test_deep_tick_fires_at_midnight_when_configured_00`; окно `test_window_open_at_midnight_when_start_00` |
| D09: 01:00 → 1, 23:00 → 23 | PASS | `test_hour_or_regular_hours`, `test_deep_tick_hours_01_and_23` (+ чужой час не запускает) |
| D09: missing/None → дефолт | PASS | `test_hour_or_missing_falls_back_to_default`, `test_deep_tick_missing_value_uses_env_default`, `test_window_missing_keys_use_env_defaults` |
| Команда брифа | PASS | `pytest tests/test_asap8_v6_wa1_*.py tests/test_config_cache*.py tests/test_dream_worker*.py -q` → 74 passed |
| Смежные | PASS | 504 passed: module truth/registry/completeness, hot_config, mca10a/10b, webapp_api, dream_persona/prompts, direct_l1/settings, summary_l1, debug_config |

## RED-доказательство (scratch, зафиксировано до/после)

- D08: старый `_synthetic_group_items` на пустом кэше → `memory.random_enabled`
  ОТСУТСТВУЕТ в get_all(); при этом keys_random-секрет = "" (работал) — дефект
  воспроизведён, фикс чинит именно его.
- D09: старое выражение `int(0 or 7)` → 7 (deep), `int(0 or 4)` → 4 (окно);
  новый `_hour_or(0, 7)` → 0, `_hour_or(None, 7)` → 7.

## Файлы

- `services/config_cache.py` — обобщённая синтетика + `_PG_ONLY_BOOL_DEFAULTS`
  (14 bool-ключей) + docstrings get_all/_synthetic_group_items.
- `services/dream_worker.py` — `_hour_or` + 3 точки чтения часов.
- `tests/test_asap8_v6_wa1_config_cache.py` — НОВЫЙ, 13 тестов
  (TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/D08).
- `tests/test_asap8_v6_wa1_dream_hours.py` — НОВЫЙ, 14 тестов
  (TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/D09).

Счётчики: 27 новых тестов; полный фокус 74 passed; смежные 504 passed; 0 failed.
Существующие тесты НЕ правились (правки не потребовались). Не коммичено.

## Incidental findings

1. `related-nonblocking` — `services/mca_gates.py` (~:1758–1784, 2 call sites):
   ТОТ ЖЕ баг `int(... or 7)` при чтении `memory.deep_sleep_hour` — вне
   WRITE_SCOPE (DO_NOT_TOUCH). Влияние: при настройке 00:00 гейт/трасса deep
   считает цель 7 (риск противоречивой телеметрии/логики расписания рядом с
   починенным `_deep_tick`). Требует точечного фикса в чужой зоне.
2. `related-nonblocking` (edge, диагностика-only) — `services/debug_config.py`
   :203/:239: для синтетических ключей `pg_key in get_all()` даёт
   `source="memory-cache"` при `cache.get(key)=None`. Существовало и раньше для
   ANU-синтетики; D08-слой расширяет класс ключей. Проявляется только в
   деградации PG; не блокирует.
3. `unrelated/pre-existing` — незакоммиченные чужие изменения в дереве
   (chat_lore_store.py, chat_lifecycle.py, disk_retention.py, plans/*) — не
   тронуты, тесты поверх зелёные.

## Остаточный риск

- UI-рендер null-значений int/float/json карточек (пустой инпут «Авто») не
  проверялся в браузере: web/app.js — чужая зона (W-A2), UI-волна по v6 phasing
  идёт отдельно; бэкенд-контракт рендера доказан юнитом маски/типов.
- Прод-выкатка и live-проверка тумблера Random — вне лейна (нет деплоя из
  Builder).
