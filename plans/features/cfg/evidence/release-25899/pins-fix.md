# PKG-99 fix lane FIX-PKG99-PINS — пересанкция инвариантов 458→461 (20.10)

**Статус:** выполнено. 34 инварианта пересанкционированы, гварды пересчитаны,
агрегат EXIT 0. Коммиты НЕ создавались (бриф). Дата: 20.10.2026.

## 1. Корень и санкция

Кандидат **`5af56d8b`** (CFG-06 v2, Approved) добавил в `config/settings.py`
3 поля фактчек-конвейера P0 (строки 2705–2718 рабочего файла):

| Поле | Default | Проверено рантаймом |
|---|---|---|
| `FACTCHECK_WIDE_CONTEXT_ENABLED` | `False` (`_env_bool`) | ✓ дубликатов нет |
| `FACTCHECK_SUITABILITY_GATE_ENABLED` | `False` (`_env_bool`) | ✓ |
| `FACTCHECK_PIPELINE_V2_ENABLED` | `False` (`_env_bool`) | ✓ |

⇒ `len(dataclasses.fields(Settings))` **458 → 461** (рантайм-факт: 461).
Сознательное владельческое изменение — тесты пересанкционированы;
`config/settings.py`, `services/**`, фактчек-код не тронуты.
`5af56d8b` НЕ в линии прод-98 (`git merge-base --is-ancestor 5af56d8b f9e7dd67`
→ нет), поэтому в линии 98 санкция 458 была валидна.

## 2. Что изменено (было/стало)

Правило: `== 458` → `== 461` + хвост-комментарий
`# CFG-06 v2 (5af56d8b): +3 поля фактчек-конвейера, пересанкционировано 20.10`
(при существующем хвост-комментарии — дописан через `; `). Исторические
комментарии-каноны (например «454→458», «categorized 458→459») не правились —
это точная история прошлых санкций.

**A. 15 сайтов внутри 24 py pin-файлов (бамп-набор):**

| Файл | Строка | Было → Стало |
|---|---|---|
| `tests/test_decision_making_round1026.py` | 915 | `…fields(Settings)}) == 458` → `== 461  # CFG-06 v2 …` |
| `tests/test_image_context_memory_round1026.py` | 1158 | `…fields(Settings)) == 458` → `== 461  # …` |
| `tests/test_summary_fact_package.py` | 636 | `== 458` → `== 461  # …` |
| `tests/test_summary_publish_integration_round1026.py` | 1311 | `== 458` → `== 461  # …` |
| `tests/test_summary_logging_runid.py` | 938 | `== 458` → `== 461  # …` |
| `tests/test_summary_test_run.py` | 468 | `== 458` → `== 461  # …` |
| `tests/test_telegram_reactions_round1026.py` | 511 | `== 458` → `== 461  # …` |
| `tests/test_tool_coordinator_round1026.py` | 936 | `== 458` → `== 461  # …` |
| `tests/test_webapp_f7_round1025.py` | 120 | `== 458` → `== 461  # …` |
| `tests/test_webapp_f9_round1025.py` | 166 | `== 458` → `== 461  # …` |
| `tests/test_webapp_hotfix7_round1025.py` | 218 | `== 458` → `== 461  # …` |
| `tests/test_webapp_hotfix8_round1025.py` | 232 | `== 458` → `== 461  # …` |
| `tests/test_webapp_hotfix9_round1025.py` | 225 | `== 458` → `== 461  # …` |
| `tests/test_webapp_hotfix10_round1025.py` | 219 | `== 458` → `== 461  # …` |
| `tests/test_webapp_round1026_polygon.py` | 145 | `== 458` → `== 461  # …` |

**B. 19 сайтов вне pin-гарда** (указание брифа «синхронизируй если тестовые»):

| Файл | Строка |
|---|---|
| `tests/test_budget_global_toggle_round1024.py` | 577 |
| `tests/test_budget_settings_round1019.py` | 46 |
| `tests/test_help_guide_round1014.py` | 211 |
| `tests/test_mca10a_random_source_block_c_round1037.py` | 131 |
| `tests/test_param_catalog.py` | 168 (`len(fields) == 458`; fields = имена полей Settings, строка 85) |
| `tests/test_round106_ia_smoke.py` | 48 |
| `tests/test_self_reflection_provider_round1014.py` | 79 |
| `tests/test_settings_persistence_round1014.py` | 51 |
| `tests/test_summary_l1_clusterizer.py` | 976 |
| `tests/test_summary_l2_writer.py` | 564 (многострочный хвост `== 458 # +4 TEMPORAL_*…` → `== 461 …; CFG-06 v2 …`) |
| `tests/test_webapp_f4_round1025.py` | 183 |
| `tests/test_webapp_f5_round1025.py` | 324 |
| `tests/test_webapp_parity_smoke.py` | 66 |
| `tests/test_webapp_round109_ui.py` | 234 |
| `tests/test_webapp_round1010_ui.py` | 200 |
| `tests/test_webapp_round1011_ui.py` | 165 |
| `tests/test_webapp_round1012_ui.py` | 197 |
| `tests/test_webapp_round1013_ui.py` | 40 |
| `tests/test_webapp_round1014_ui.py` | 43 |

Grep-контроль: `git grep '== 458' -- tests` → **0**; провенанс-маркер — 34 файла /
34 вхождения. Исторические упоминания 458 (комментарии `test_frontend_tab_mapping:160`,
`test_round1025_f8_registry:142`, каноны) не пины — не тронуты. Вне `tests/` «458»
живёт только в исторических re-pin-скриптах `tools/_asap31_*`,
`tools/_cfg02b_reissue_f8.py` (одноразовые, уже отработали) и vendor-бандле
`web/static/vendor/vis-network` — не тронуто. В `plans/docs/` упоминаний 458 нет.

Скрипт правки: `OPENCODE_WORKFLOW_SCRATCH/pkg99/resanction_461_25899.py`
(fail-closed: каждый сайт обязан совпасть с ожидаемой подстрокой), лог —
`pkg99/resanction-log.txt`.

## 3. Верификация

| Проверка | Результат |
|---|---|
| settings import | `APP_VERSION == 2.58.99`; `len(fields(Settings)) == 461`; 3 поля `False`, без дублей — PASS |
| Offline-агрегат PKG-99 (`verify_25899.py`, расширен строгим классом ресанкций) | **EXIT 0**, 13/13 PASS: pairs=48 = 33 версии + 15 ресанкций с провенансом; дизъюнктность с samples-ux/фактчеком PASS; ΔDDL=0 PASS |
| 24 py pin-файла целиком | **867 passed / 1 failed** (см. §4); в лучшем прогоне единственный fail — foreign samples-ux |
| 19 синхронизированных не-пиновых файлов | **571 passed / 2 failed**; 2f — pre-existing красота чистого HEAD, см. §6 |

Прогоны pins24 (полные, все 24 файла):

| Прогон | Итог | Упавшие |
|---|---|---|
| до фикса (`pins24-full.txt`) | 852p / 16f | 15×458-инварианты + mca17c (v37) |
| после фикса #1 | 866p / 2f | mca17c + флейк test_on_l1 |
| после фикса #2 | 866p / 2f | mca17c + флейк test_on_l1 |
| после фикса #3 (fulltrace, `-rA`) | **867p / 1f** | только mca17c (foreign) |

## 4. 16-е падение — НЕ 458: foreign samples-ux v37 (важно)

`test_mca17c_invariants_round1047.py::test_no_ddl_catalog_ks_tools_delta`
падает на `assert int(row[0]) == 36` (PRAGMA user_version = **37**).
README до фикса неверно обобщал «все 16 — один отказ 458» — на самом деле:

- корень: **чужие незакоммиченные правки samples-ux** в `services/database.py`
  (ADD-SAMPLES-UX §1/§3: `_SCHEMA_VERSION_HUMOR_SAMPLES = 37`, миграция
  `humor_samples_v37`);
- в HEAD `8f220b60`: `_SCHEMA_VERSION_HUMOR_SAMPLES = 36` (проверено
  `git show HEAD:services/database.py`) → на чистом чекауте релиз-коммита тест
  **зелёный** (пин ассертит именно 36);
- пин 36→37 сознательно **не менялся**: (а) это узаконило бы чужую
  незакоммиченную миграцию, не входящую в пакет; (б) в закоммиченном состоянии
  (бамп `--only` без database.py) такой пин стал бы красным; (в) `services/**`
  запрещён брифом.

**Действие:** лейн samples-ux пересанкционирует пин 36→37 при приземлении v37.
Для процедуры релиза: 868p/0f достижим на чистом чекауте релиз-коммита
(в рабочем дереве с чужой волной — 867p/1f по независящей причине).

## 5. Флейк `test_on_l1_not_usable_level2_l2_publishes_article` (новое наблюдение, вне 16)

`tests/test_summary_publish_integration_round1026.py::TestOnDelivery` — падал в
полных прогонах #1/#2, прошёл в #3, проходит соло (2.9s) и целым файлом (72/72).
Лог падения: `L1_FALLBACK_PACKAGE reason=invalid_json` → `L2_PACKAGE_DEGRADED`
(41 символ, 1 абзац) вместо semantic-пакета — недетерминизм в services
summary-пути (мок-модель, порядок/парсинг L1 JSON). К правкам лейна отношения не
имеет (ассерт-константы в других тестах; прогон #3 с теми же правками зелёный).
Классификация: **related-nonblocking, pre-existing flake**, root в
`services/summary_*` — владельцу summary-контура.

## 6. `test_param_catalog.py`: 2 красных теста вне guards (pre-existing, HEAD)

`TestCompleteness.test_every_settings_field_covered` и
`test_settings_field_count` (строка 170) падают **на чистом HEAD тоже**:
`pc.settings_field_coverage()` возвращает 3 новых поля как не покрытые —
`services/param_catalog.py` не содержит ключей `flags.factcheck_wide_context` /
`factcheck_suitability_gate` / `factcheck_pipeline_v2`, кандидат `5af56d8b`
каталог не трогал (`--stat`: только settings.py/handlers/plans), при том что
комментарии полей ссылаются на hot-ключи `flags.factcheck_*`. До фикса эти
тесты тоже были красные (первый — по покрытию, второй — на 458≠461, строка 168;
теперь второй падает строкой ниже на той же корневой причине).

**Действие (вне лейна, `services/**` запрещён):** владелец CFG-06 / F8-каталог
выбирает: каталогизация 3 полей (REGISTRY 579→582, каскад каталожных пинов) или
явная санкция исключения (пополнение `_CLASSVAR_CATALOGUED`/эквивалент с
обоснованием). До решения эти 2 теста остаются красными в линии кандидата —
**это не входит в guards релиза** (файл не в 24 пинах и не в бамп-наборе), но
должно быть видно ревью.

## 7. Изоляция и пакет

Изменены ровно 34 файла `tests/**`. 15 из них входят в 31-файловый бамп-набор
(ресанкция легальна — расширение санкции пин-строк тем же пакетом); 19 — вне
набора: **оркестратору** включить их в релиз-пакет (или отдельным
`--only`-коммитом тем же релизом), иначе закоммиченная линия останется со
stale-инвариантом 458 в этих файлах. Остальные чужие незакоммиченные правки
(50-файловая дельта tests минус наши 34; services/web/plans) — параллельные
лейны, не тронуты.
