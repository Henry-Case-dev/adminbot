# F4 — Module completeness: оставшиеся orphans (ASAP 7, Wave 3)

Дата: 2026-10-09. База: HEAD `71b3b69` (Wave 2) + параллельный WIP F2 в общих
файлах. Режим: writer, LEAF (без subagent'ов). Коммитов нет.
Статус: готово к независимому ревью.

## 1. Изменения (file:line)

**`services/param_catalog.py`** (свои группы; flags_intent/limits_intent/
direct_l1 не тронуты)
- Группы: `flags_stories` :451 (order 29), `flags_character` :459 (order 30,
  Advanced). TAB_RULES in-place — 23 без роста: memory_rag + flags_stories
  (:2589), permsoc + flags_character (:2665). Новых вкладок нет (menu-freeze
  цел).
- 13 ParamSpec (`_STORIES` :2474 ×6, `_CHARACTER` :2480 ×7; регистрация
  :2533-2537) — паттерн `_INTENT` F3: settings_field = СУЩЕСТВУЮЩИЙ env-атрибут
  (default-ось), pg_id человекочитаемый (`flags.stories_vitrina_enabled`,
  `flags.self_model_enabled`, …), character-оси progressive_level=advanced.
  Storage не дублируется: одна семантика — один PG-ключ, ClassVar остаётся
  env-осью. Новых записей Settings НЕТ (config/settings.py не тронут).
- Δ каталога F4: REGISTRY +13, GROUPS +2, _TAB_BY_GROUP +2, TAB_RULES +0.

**`services/mca_gates.py`** — ОТКЛОНЕНИЕ №1 от WRITE_SCOPE (см. §5): без него
13 новых тумблеров были бы «мёртвыми ручками», а effective-дисплей (§4.3)
лгал. Переиспользован AND-гейт F3 (alias `_module_catalog_flag` :1353):
- stories/episodes: `stories_vitrina_enabled` :2097, `stories_manage_enabled`
  :2109, `episodes_enabled` :780, `episodes_backfill_enabled` :792,
  `episodes_continuation_enabled` :802, `episodes_compiler_facade_enabled`
  :812 — effective = env И каталоговый тумблер; композит mca-05 (подгейты
  инертны при мастере) сохранён; K2 stories независим от K1 (как было).
- character: `self_model_enabled` :1401, `trait_rules_enabled` :1415,
  `legacy_traits_migration_enabled` :1427, `character_layers_enabled` :1032,
  `character_speech_enabled` :1043, `style_scope_enabled` :1055,
  `postprocess_form_guard_enabled` :1067.
- Random/Experience runtime-гейты НЕ тронуты (новых тумблеров для них нет).

**`services/module_registry.py`** (расширение каркаса F3, не ломая)
- ModuleSpec + аддитивное поле `config_tab` :58 (поверхность подмодуля на
  СУЩЕСТВУЮЩЕЙ вкладке родителя).
- +4 ModuleSpec §3.2: `stories` :102 (parent memory, master
  `flags.stories_vitrina_enabled`, env MCA_STORIES_VITRINA_ENABLED),
  `character` :126 (parent persona, master `flags.self_model_enabled`,
  visibility=advanced, Advanced-размещение), `experience` :150 (parent memory,
  master `memory.experience_learning_enabled` — СУЩЕСТВУЮЩИЙ hot-ключ, читается
  mca_experience_jobs:119 — не мёртвый), `random` :173 (parent memory,
  «no master» rationale: мастер — env-ось MCA_RANDOM_SOURCE_ENABLED, дублировать
  тумблером нельзя; model_slots keys_random).
- ENV_GATES +4, PRODUCT_DEFAULTS +3 (:223-243); `_product_requested` —
  empty-master short-circuit :221.
- M2-ownership: 23 оси перенесены из rationale-группы «submodule→F4» в
  MODULE_ENV_GATES :368-397 (stories ×6, character ×7, random ×5,
  experience ×4); rationale-группа сжата до Vision (вне объёма F4). Покрытие
  KILL_SWITCHES 85 = 26 owned + 59 rationale, без дублей/мёртвых имён.
- `registry_for_frontend()` :272: + `config_tab` и + `gate` — снимок
  `gate_snapshot` (requested/effective/source/env_param) в УЖЕ существующий
  носитель GET /api/config (routes.py НЕ менялся; ROUTES_SHA256 цел).
- `validate_spec()` :308 — M4-машина: product_module без master → RED;
  «no master» легален только не-product-спекам с явным rationale;
  settings_groups ⊆ GROUPS; master ∈ каталога и migratable.

**`web/app.js`** (SECTION-MODULES + F4-helpers, 10 хунков с маркером F4)
- `f3ApplyModuleRegistry` :6987 — ветка подмодулей (F3 оставил точку
  расширения): подкарточки из реестра (icon-карта F4_ICONS, tab=config_tab,
  settingsGroups, gate, noToggle для «no master» — мёртвого переключателя
  нет), дубли исключены; fallback-витрина MODULES не расширалась (канон =
  реестр, §3.1). Cold deep-link на подкарточку — re-apply после merge :7097.
- `_workspaceGroupsFor` :9859 — фильтр `settingsGroups`: на settings-вкладке
  подкарточки ТОЛЬКО свои группы (паттерн Initiative), даже на общей вкладке
  родителя.
- `f4ModuleGate` :7061 / `f4RelatedLinks` :7070 — честный гейт (requested из
  configItems, effective/source из реестра) и ссылки-переходы.
- `moduleStateText`/`moduleEnabled` :9189/:9216 — ветки «no master»-карточек
  (состояние = env-ось, не «выключен из-за отсутствия ключа»).
- TABS-зеркала: memory_rag sources + flags_stories (:233), permsoc sources +
  flags_character (:268) — зеркало TAB_RULES (прецедент MCA-19 D16/F3).
- `intentRelatedLinks` :7014 — «Случайность» теперь ведёт на owner-карточку
  #/modules/random (бриф: ссылки из Initiative).
- `_routeLabel` :2321-область и `currentTabLabel` :9222 — заголовок/крошка
  подкарточки = title карточки («Случайность»), не tab-лейбл родителя («Сон»);
  только для fromRegistry+submoduleOf (пины топ-модулей не менялись).

**`web/index.html`** (регион модулей + точечные гварды протечек)
- F4-блок `data-f4-module-gate` :369-414 на «Обзоре» подмодуля:
  Работает/Не работает, requested (мастер-ключ или «мастер — env-ось»),
  source, env-ось + restart-пометка, ссылки-переходы. Amber-заметка :358 —
  guard по toggleKey (для no-master её отдаёт F4-блок).
- Протечки tab-specific шаблонов на страницах подкарточек (orphan controls):
  permsoc-секция :2665 + memory_rag-трио (chips :2277, lessons :2292,
  stories-manage :2392) — guard `!workspaceModule`. На самих вкладках
  «Память»/«PERMsoc» ничего не изменилось.

**Тесты/инструменты**
- NEW `tests/test_asap7_module_completeness.py` — 15 тестов, CONTRACT
  owner=asap7/F4 (M2-ext/M3/M4-механика/no-dead-knobs/JS-пины).
- `tests/test_asap7_module_registry.py` — M4-цикл легализует «no master»
  (классификация ≠ product_module + явный rationale) — бриф F4: «master_param
  из каталога (или explicit no master rationale)»; остальные проверки F3
  не тронуты.
- `tests/test_param_catalog.py` — _CLASSVAR_CATALOGUED +13 (ClassVar = оси
  каталога, прецедент F3: +9 Intent).
- `tests/test_mca10b_random_applications_block_d_round1041.py` — доведение
  механических пинов до канона общих фикстур (F2 переиздал их на 560/120/118/
  149 c нотой «финальные счётчики — за лейном, приземляющимся последним»,
  свой свип оборвал на полпини): secrets 33→34 (+1 = keys.direct_l1_api_key
  F2; F4 секретов не добавлял), "538"→"560" в stdout gen --check,
  delta 127→149, registry_keys 538→560.
- `tools/ui_asap7_f3_e2e.py` — пин ссылок «Настройки блока»: linkSleep →
  linkRandom (владелец переехал на свою подкарточку — следствие objective 4).
- NEW `tools/ui_asap7_f4_e2e.py` — Playwright-верификация (детерминированные
  DOM-контракты, desktop+mobile+emergency).
- NEW `tools/_asap7_f4_reissue_f8.py` — интеграторский re-issue (--check
  режим); после переиздания F2 остался как документация гонки общего файла.

## 2. Проверка

- `pytest tests/test_asap7_module_completeness.py tests/test_asap7_module_registry.py`
  → **29 passed**.
- Точечные соседи (mca12 stories, mca16 experience ×6, mca18 self-model ×7,
  mca10a/b/c random ×12) — **384 passed, 0 failed** (финальный комбинированный
  прогон; 2 механических пина в mca10b доведены до канона, см. §1).
- Каталог-контур `-k "f8 or catalog or param_catalog or module_registry or
  module_completeness"` → 308 passed; 18 RED — исторические пины эр
  round1012–1026 (489/502/510/513/523-семья), pre-red от WIP F2 ДО правок F4
  (live был 547 vs их пины), финальный свип — за лейном, приземляющимся
  последним (нота в f8_baseline от F2). Ни один не стал RED от F4 (все пины
  < 547 арифметически).
- `node --check web/app.js` → OK; py_compile всех правленых .py → OK.
- JS-харнессы (36 файлов round1020/24/25/46) → 29 OK; 7 RED — **воспроизведены
  1-в-1 на чистом HEAD 71b3b69** (git worktree-проба): stale-пины
  (menu-freeze старых эр, APP_VERSION 2.58.34-эры) — pre-existing, к F4 не
  относятся; релевантные (round1046 stories, round1025 module-store,
  round1024 image-module, round1021) — OK.

## 3. UI/визуальное доказательство (оба канала обязательны)

1. **Playwright детерминированно** — NEW `tools/ui_asap7_f4_e2e.py`
   (server/TMA-стаб reuse `ui_round1025_matrix`): desktop 1280×800 + mobile
   390×844 + env-emergency сценарий; **failures: 0**. Проверено: 4 подкарточки
   в хабе (без overflow), страницы stories/character/experience/random —
   data-f4-module-gate (Работает, requested, source, env-ось, restart),
  settings = ТОЛЬКО своя группа (6/7/2/свои ключи), ЧУЖИЕ группы отсутствуют,
   random — без переключателя + ссылки Сон/Инициатива, emergency OFF →
   честный «Не работает» + restart-пометка. Скриншоты и raw:
   `OPENCODE_WORKFLOW_SCRATCH` (`ui_asap7_f4_*.png`, `ui_asap7_f4_e2e.json`),
   в репозиторий не попадали. Прогон F3-e2e после моих правок — тоже
   **failures: 0** (обновлён только пин ссылки, §1).
2. **Browser Use (реальный Chrome)** через Code Mode: scratch стаб-сервер
   (реальные index.html/app.js + TMA-стаб инъекцией + /api/config с живым
   registry_for_frontend). DOM-пробы: хаб — 19 карточек (15+4), overflow=false;
   страницы подмодулей — head/gate/tabs/ссылки 1-в-1 с Playwright; settings
   character — «Мимикрия»/PERMsoc-блоки ОТСУТСТВУЮТ после гварда; крошка и
   заголовок экрана — «Случайность» (не «Сон»); скриншоты хаба и страницы
   «Случайность» зафиксированы в сессии (визуально: head-карточка без
   переключателя, badge «Работает», env-ось, ссылки; сетка не поехала).

## 4. Инварианты (acceptance)

- **M2-расширение**: 23 оси orphans → owner-модули (MODULE_ENV_GATES),
  Vision — rationale; KILL_SWITCHES покрыты без пропусков/дублей/мёртвых
  имён; каждый НОВЫЙ каталоговый тумблер прочитан runtime-гейтом
  (no-dead-knobs тест) — да.
- **M3**: подмодули имеют parent (§3.2-карта), own settings group на
  поверхности родителя, own effective state (both/product_toggle/
  emergency_env сценарии), no orphan controls (группы закрыты; tab-specific
  шаблоны загвардены) — да; runtime подчиняется тумблерам (hot, submaster
  inertia сохранён) — да.
- **M4 (drift)**: `validate_spec` — product_module без master_param,
  выдуманный master, «no master» без rationale, группа вне GROUPS, плохая
  classification → RED; все зарегистрированные спеки — [] — да.
-Neighbors зелёные; node --check; py_compile — да.

## 5. Отклонения от брифа

1. **`services/mca_gates.py` отсутствовал в WRITE_SCOPE**, но: (а) бриф
   требует «перенести ENV-оси в catalog», (б) §3.3 архитектуры объявляет
   AND-паттерн обязательным для «всех новых product toggles F4», (в) без
   AND-гейта 13 тумблеров — «мёртвые ручки» (запрещённый паттерн, см.
   комментарий param_catalog:2560-2565), effective-дисплей лгал бы. Правка
   минимальна и механична (паттерн F3, который ревью Approved); параллельные
   лейны mca_gates не трогают. Прецедент задокументированного отклонения —
   F3 §7.1 (routes.py).
2. `tests/test_asap7_module_registry.py`, `tests/test_param_catalog.py`,
   `tests/test_mca10b_…`, `tools/ui_asap7_f3_e2e.py` вне WRITE_SCOPE —
   доведение механических пинов до канона (F3-прецедент «~50 тест-файлов»);
   семантика контрактов не ослаблена.
3. `config/settings.py` — НЕ тронут (цель брифа выполнена: env-fallback через
   существующие attrs; новых Settings нет).

## 6. Инцидентальные находки

- **related-nonblocking (закрыто здесь)**: permsoc-master/чипы памяти/lessons/
  stories-manage протекали на страницы модулей с tab=permsoc/memory_rag —
  guard `!workspaceModule`; крошка/заголовок «Сон» вместо «Случайность»;
  мёртвый переключатель у no-master карточки.
- **related-nonblocking (не моё, передаю Ревьюеру)**: F2-WIP
  `models_direct_l1` — keys-слоты в models-группе роняют
  `test_param_catalog.py::test_group_ids_all_valid_and_prefixed`
  (прецедент NON_PREFIXED для models_summary_hybrid); `test_settings_field_count`
  RED от их новых ClassVar. Оба pre-red до F4.
- **unrelated/pre-existing**: 7 JS-харнессов (воспроизведены на чистом HEAD);
  18 исторических каталог-пинов (см. §2) — финальный свип за последним
  catalog-лейном (нота F2 в f8_baseline).
- **uncertain (задокументировано)**: холодный deep-link `#/modules/<subslug>`
  при свежем документе перезаписывается boot-роутером ДО loadConfig
  («Модуль не найден» → #/modules; семантика F5 D1). In-app навигация и
  in-doc hash-переходы работают (покрыто e2e); in-merge re-apply чинит
  незаписанный случай. Полное лечение = server-driven MODULES (вне ASAP 7,
  §3.1).

## 7. Фингерпринт кандидата

- База: HEAD `71b3b69`; в worktree на момент старта находился незакоммиченный
  WIP F2 (param_catalog/mca_gates-нет/app.js SECTION-DIRECT-UI/usage_events/
  pg_db/execution_graph/analytics/settings/index.html DIRECT-хунки) — не тронут
  и не входит в мой фингерпринт; секции размежеваны (F2-маркеры :107-117,
  :3312, :10793-10877 app.js против F4 :6965-7164/:9189-9238/:9859).
- Файлы F4 (новые): `tests/test_asap7_module_completeness.py`,
  `tools/ui_asap7_f4_e2e.py`, `tools/_asap7_f4_reissue_f8.py`,
  `plans/features/asap7-cognitive-direct-pipeline/f4-report.md`.
- Файлы F4 (правки): `services/param_catalog.py` (+112), `services/mca_gates.py`
  (13 гейтов + alias), `services/module_registry.py` (+230/-2),
  `web/app.js` (10 F4-хунков), `web/index.html` (7 хунков),
  `tests/test_asap7_module_registry.py` (M4 no-master),
  `tests/test_param_catalog.py` (+13 ClassVar- whitelist),
  `tests/test_mca10b_random_applications_block_d_round1041.py` (4 пина),
  `tools/ui_asap7_f3_e2e.py` (пин ссылки).
- Проверка: pytest 29/29 (registry+completeness), 384/384 (соседи),
  node --check OK, Playwright F4 0 failures + F3 0 failures, Browser Use
  (реальный Chrome) DOM+скриншоты OK.

## 8. Оставшийся реальный риск

1. 18 исторических каталог-пинов RED до финального свипа волны (не от F4;
   тул и нота готовы).
2. `memory.experience_learning_enabled` как requested-ось Experience покрывает
   learning-подконтур; env K1 `MCA_EXPERIENCE_LESSONS_ENABLED` остаётся
   аварийной осью (catalog-тумблера для неё нет по брифу — «настройки не
   дублировать»); на карточке это показано честно (env-ось в гейте).
3. Stories-мастер в effective-формуле — ось витрины (K1); эпизодный мастер
   `flags.episodes_enabled` показан отдельным тумблером в настройках
   подкарточки (своя AND-связка), в card-gate не суммируется — задокументировано
   в rationale спека.

@Orchestrator — лейн F4 закрыт, прошу строгого независимого ревью.
