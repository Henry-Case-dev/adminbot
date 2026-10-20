# PKG-99 fix lane FIX-PKG99-CATALOG — каталогизация 3 флагов CFG-06 v2 (20.10)

**Статус:** выполнено. Оба красных теста `test_param_catalog.py` закрыты
(34 passed), каскад счётчиков проведён по процедуре
(`tools/_cfg02b_reissue_f8.py`, прецедент CFG-02B), F8 `--check` OK (582),
offline-агрегат EXIT 0. Коммиты НЕ создавались (бриф). Дата: 20.10.2026.
HEAD на протяжении всей работы: `8f220b60`.

## 1. Корень и фикс

Кандидат CFG-06 (`5af56d8b`, Approved) добавил 3 Settings-поля фактчек-конвейера
v2 без записей каталога → `test_every_settings_field_covered` (missing=3) и
`test_settings_field_count` были красными ещё на чистом HEAD (зафиксировано
в guards PKG-99 как «2f pre-existing, фикс-лейн services/** разрешён»).

Фикс: **+3 ParamSpec** в `services/param_catalog.py` (новый блок `_FACTCHECK_V2`,
merge в `_build_registry` после `_TEMPORAL`). Группа **`flags_module_factcheck`
in-place** (GROUPS 120 / `_TAB_BY_GROUP` 118 / TAB_RULES 23 / routes — без
изменений), вкладка mod_factcheck. Рантайм читает hot-ключи БЕЗ суффикса
`_enabled` (`factcheck_context.py:80`, `factcheck_suitability.py:106`,
`factcheck_orchestrator.py:186`, `factcheck_planner.py:70`) → **pg_id-ренейм**,
прецедент product-осей §3.3 (`flags.initiative_enabled…`).

| Поле | pg_key (pg_id) | Описание (существу) | Default |
|---|---|---|---|
| `FACTCHECK_WIDE_CONTEXT_ENABLED` | `flags.factcheck_wide_context` | «Фактчек: широкий контекст» — расширенное адаптивное окно 200–500 с якорями тейков; гейт отката | False |
| `FACTCHECK_SUITABILITY_GATE_ENABLED` | `flags.factcheck_suitability_gate` | «Фактчек: гейт осмысленности» — проверка осмысленности до платного поиска; активен только с широким контекстом | False |
| `FACTCHECK_PIPELINE_V2_ENABLED` | `flags.factcheck_pipeline_v2` | «Фактчек: конвейер v2» — единый конвейер (гейт осмысленности → упоминания → план → поиск → вердикт → оформление); миграционный рубильник отката, при v2 широкое окно и гейт подразумеваются | False |

Все `default False` — v2-конвейер за миграционным рубильником (выкат OFF,
hot-включение владельцем после смоука). Прогрессивный уровень: авто-правило
(`flags.factcheck_wide_context` → advanced по маркеру «context»; остальные
basic). Описание pipeline_v2 прошло контракт UI-копирайта
`test_webapp_round109_ui::test_no_ai_template_pattern` (запрещён шаблон
«включ\*…выключ\*» — первая редакция попадала, переписана, RED→GREEN).

## 2. Счётчики было/стало

| Счётчик | Было | Стало |
|---|---|---|
| REGISTRY | 579 | **582** |
| Settings-поля | 458 → 461 (ресанкция FIX-PKG99-PINS, вне этого лейна) | 461 |
| categorized | 554 | **557** |
| delta (inventory 411) | 168 | **171** |
| F8 TSV строк | 580 | **583** |
| GROUPS / _TAB_BY_GROUP / TAB_RULES | 120 / 118 / 23 | без изменений |
| flags-категория (counts-пин) | 99 | **102** |
| `PARAM_CATALOG_SHA256_FOLLOWUP` | `4886ff03…` | `a4214ef9…` |

## 3. Прогоны (финал, всё на рабочем дереве поверх bump 2.58.99)

| Гвард | Результат |
|---|---|
| `tests/test_param_catalog.py` (целиком) | **34 passed** (было 32p/2f) |
| `tests/test_round1025_f8_registry.py` (F8-пины) | **29 passed** |
| `gen_param_registry_round1025.py --check` | **CHECK OK: реестр 582 == REGISTRY** |
| Offline-агрегат PKG-99 (`verify_25899.py`, 16 проверок) | **EXIT 0**; пары 84 = 33 версии + 15 ресанкций + **36 каталог-пар**; дизъюнктность бампа с samples-ux/фактчеком PASS; ΔDDL=0 PASS |
| Sweep: 54 файла (все перепинованные + каталоговые) | **1810 passed / 2 failed**; 2f = известные вне диффа: `test_mca17c::test_no_ddl_catalog_ks_tools_delta` (foreign samples-ux `database.py` v37), `test_on_l1_not_usable_level2_l2_publishes_article` (flake, вне скоупа) |
| Сustom-set: param_catalog + F8 + cfg03 TestPins + ia_inventory | **71 passed** |

## 4. Что вошло в чужие файлы (для оркестратора — собирает релизный коммит)

**Файлы бампа (31-набор), процедурно-обязательные правки поверх бампа:**

1. `plans/docs/param-registry-round1025.meta.md` — **переэмитирован
   генератором целиком** (не ручные анкоры): счётчики 582/171, +3 буллета
   delta-списка (`flags.factcheck_*`), APP_VERSION `2.58.99` и HEAD `8f220b60`
   сохранены (генератор берёт текущие значения; stale `2.58.98`/`1b23d4c`
   отсутствуют — assert агрегата PASS). Строк пар в diff: 4 каталог + 2 бамп.
2. `tests/test_round1025_f8_registry.py` — NOTE-блок CFG-06 v2 (7 строк,
   провенанс L-F11S-1), `PARAM_CATALOG_SHA256_FOLLOWUP` → `a4214ef9…`,
   пины: 579→582 (×3), 168→171, meta-строка, + существовавший бамп/ресанкция.
3. **19 py-файлов бампа** — по одной строке `len(pc.REGISTRY) == 579` → `== 582`
   (decision_making, image_context_memory, mca17c, summary_deploy,
   summary_fact_package, summary_logging_runid, summary_publish_integration,
   summary_test_run, telegram_reactions, tool_coordinator,
   unified_image_request, webapp_f11/f7/f9, webapp_hotfix10/7/8/9,
   webapp_round1026_polygon) + **7 из них** дополнительно `categorized == 554`
   → `== 557`. Форма пина однозначная, провенанс — NOTE в F8-тесте + записи
   ниже; агрегат распознаёт обе формы (36 каталог-пар).

**Файлы вне бампа (foreign, ожидаемо):** `services/param_catalog.py` (+47),
`tests/test_param_catalog.py` (counts-пин flags 102 + якорь-комментарий),
F8-артефакты `param-registry-round1025.tsv` (+3) / `screen-map-round1025.md`
(+3 строки), fixtures `f8_baseline.json` / `catalog_baseline.json`, **70
файлов тестов с пинами** (52 + 18 во второй волне; полные списки — вывод
`recatalog_582_25899.py`), включая ранее чистый `tests/test_webapp_api.py`
(одна строка `categorized 554→557`).

**Не тронуты (DO_NOT_TOUCH соблюдён):** `config/settings.py` (дифф = только
бамп-строка APP_VERSION), фактчек-сервисы, `database.py`/samples-ux файлы,
routes (ROUTES_SHA256_F11 без изменений — F8-тест зелёный), `web/**`, git.

## 5. Инструмент лейна (scratch, в пакет не входит)

`OPENCODE_WORKFLOW_SCRATCH/pkg99/recatalog_582_25899.py` — fixtures + массовая
пересанкция + re-pin хэша (идемпотентен). `verify_25899.py` расширен по
прецеденту FIX-PKG99-PINS: hunk-aware разбор, санкционированные каталог-пары
(579→582 / 554→557 / 168→171 / hex64 re-pin) и вставки (3 буллета meta,
`# ` строки NOTE в 2 санкционированных файлах); удаления и любой прочий
не-токенный шум по-прежнему FAIL.
