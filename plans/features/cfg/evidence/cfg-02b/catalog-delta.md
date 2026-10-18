# CFG-02B — каталог-дельта, re-pin и заморозки

## Дельта (санкция: requirements-map слайс CFG-02B §02B.1/§02B.2/§02B.3)

+4 ParamSpec в СУЩЕСТВУЮЩУЮ группу `limits_images` (вкладка `mod_images`):

| pg_key | Settings-поле | тип | widget | заводской |
|---|---|---|---|---|
| `limits.image_freq_limit_enabled` | `IMAGE_FREQ_LIMIT_ENABLED` | bool | (тумблер) | False |
| `limits.image_freq_limit_burst` | `IMAGE_FREQ_LIMIT_BURST` | int | number | 3 |
| `limits.image_freq_limit_cooldown_seconds` | `IMAGE_FREQ_LIMIT_COOLDOWN_SECONDS` | int | number (+«≈ мин») | 300 |
| `limits.image_freq_limit_mode` | `IMAGE_FREQ_LIMIT_MODE` | str | select per_user\|per_chat | `per_user` |

## Счётчики до/после

| Счётчик | Было | Стало |
|---|---|---|
| REGISTRY | 575 | **579** |
| Settings-полей (`dataclasses.fields(Settings)`) | 454 | **458** |
| categorized (specs с category) | 550 | **554** |
| delta (inventory 411) | 164 | **168** |
| GROUPS / _TAB_BY_GROUP / TAB_RULES | 120 / 118 / 23 | 120 / 118 / 23 (in-place) |
| routes (`ROUTES_SHA256_F11`) | — | без изменений |

## Инструмент и переутверждённые пины

`tools/_cfg02b_reissue_f8.py` (прецедент `tools/_soul1_w5_reissue_f8.py`):
1. `gen_param_registry_round1025.py` → TSV/meta/screen-map перегенерированы (`--check` = OK);
2. `tests/fixtures/round1025/f8_baseline.json`: counts/sha256 + provenance-note CFG-02B;
3. `tests/fixtures/round1025/catalog_baseline.json`: registry_keys/group_ids/group_tab/tab_nav/counts;
4. счётчики-пины в тестах (57 файлов в выборке blast-radius, включая webapp-синки):
   `575→579`, `164→168`, `454→458`, `550→554`, `576→580` (F8-TSV), meta-пин `"575"→"579"`;
5. `PARAM_CATALOG_SHA256_FOLLOWUP` =
   `1fb5cee559b70279ac9473dcce52446708f32cc8b61cbdc029fe90c154a36738` (первый прогон) →
   `ad109003b936f4b2243ee4b2ceb52753dacb93b7f319a29995ce9ed9036bc5a6` (после правки
   описания под guard round109, финальный);
6. `FACTORY_SET_SHA256_12` = `7422c0385f7d` → **`5a3d211b36be`** (новый редактируемый текст
   `message.image_failure.freq_limited`).

## Ручные правки пинов (сверх авто-замен)

- `tests/test_param_catalog.py::TestGroups8424::test_group_counts_match_design` — limits 222→226;
- `tests/test_frontend_tab_mapping.py::test_widget_keyvalue_on_summary_aliases` —
  +`limits.image_freq_limit_mode` в набор select-виджетов;
- `tests/test_mca10b_random_applications_block_d_round1041.py` — stdout-пин `"575"→"579"`;
- `tests/test_unified_image_request_round1026.py` и `tests/test_tool_coordinator_round1026.py` —
  allowlist bounds-тестов: +`web/api/gates.py` с NOTE-санкцией (§02B.8, viewer_user_id);
- `tests/test_image_generation_round1023.py` — тест-двойник `generate_and_send` принимает
  новый kwarg `user_id` (проверка correlation_id не изменена).

## Проверки

```
py -3 -m pytest tests/test_cfg02b_image_freq_limits.py -q          → 35 passed
py -3 tools/gen_param_registry_round1025.py --check                → CHECK OK: реестр 579 == REGISTRY
py -3 -m pytest <20 файлов blast-radius> -q                        → 838 passed (blast-radius.txt)
py -3 -m pytest <57 файлов re-pin + новый тест> -q                 → 1930 passed,
   3 failed: только внешняя правка web/api/routes.py (чужой незакоммиченный лейн, mtime 03:35:46;
   HEAD-хэш routes.py == ROUTES_SHA256_F11 (989779c6…), рабочая копия — 21f72a8e…).
```
