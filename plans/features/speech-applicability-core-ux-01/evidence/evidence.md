# SAC-S1 / SAC-CORE — evidence (28.11.2026)

Источник: `plans/owner_inputs/2026-11-28-speech-applicability-personality-core-ux.md`
и расширяющий `plans/owner_inputs/2026-11-28-unified-personality-architecture.md`.
База: `886d11073` (2.58.258). Ветка: `feat/speech-applicability-core-ux`.
Кандидат: tip этой ветки на момент сдачи (см. `git log -1`).

## 1. Причина и вывод аудита

| Что проверено | Факт |
|---|---|
| `web/api/routes.py` GET `/api/config` | помечал `status=inactive` ВСЕ ключи группы `limits_temperature` при `provider_ignores_temperature(_primary_model_name())`, включая `limits.chat_temperature_preset_default` (str-селектор) |
| `services/param_catalog.py` | `provider_ignores_temperature` — узкий детектор по имени модели; `EFFECTIVE_STATUS_META` не содержит `inactive` ни для одного ключа |
| `services/mca_vision._is_reasoning_model` | влияет только на предел вывода vision и reasoning-режим; к текстовым слоям промпта не подключён |
| `services/direct_chat_service.py` / `services/prompt_composer.py` | Core/Identity/Speech/Expression/Style/примеры гейтятся только флагами (`character_core_enabled`, `persona_enabled`, …), не семейством модели; temperature передаётся и при отказе провайдера снимается по фактическому ответу (`llm_client._INCOMPATIBLE_PARAMETERS`, retry без temperature) |
| `services/bot_persona.build_persona_prompt_block` | `system_prompt_overrides` рендерится в `<Persona>` как «Характер: …»; пути Core/Identity не зависят от модели |
| `services/prompt_composer._duplicate_character_segment` | снимает owner-характер, уже пришедший слоем Core (SOUL-03.6); после UI-правки остаётся нужным для legacy-значений |

**Вывод:** дефект применимости речи был только ошибкой индикации (UI/effective-config).
Реального runtime-гейта, отключающего текстовые инструкции по reasoning/temperature,
не обнаружено. Генеративный контур не менялся.

## 2. Устранённые программные ограничения

1. `routes.py` — temperature-пометка сужена до float-значений самой температуры
   (`limits.chat_temperature_{precise,balanced,chatty}`); селектор
   `limits.chat_temperature_preset_default` больше не получает `inactive`.
   Формулировка пометки: «значение влияет только на подбор слов и не отключает
   инструкции личности и речи».
2. `web/app.js::speechModeStatus` — карточка «Речь и характер» больше не выводит
   `не применяется` из temperature-меты; собственный `no_op`/`legacy` настройки
   остаётся честным.
3. `directModesView().speech.line` — technical reason больше не дублируется в
   строке карточки; пометка живёт у самой температурной настройки
   (`configEffBadge` + `configItemNotice`).
4. Новых allowlist/проверок пригодности модели/гейтов речи нет; сохранённые
   модель/провайдер/temperature/режим не менялись и не мигрировались.

## 3. Задвоение источника характера

Фактическая read-only сверка production (один SSH-коннект, только длины/хеши,
текст не выгружался):

```
select coalesce(chat_id::text,'global'), length(system_prompt_overrides),
       md5(system_prompt_overrides) from personas order by 1;
global|0|d41d8cd98f00b204e9800998ecf8427e
-1002661910336|0|d41d8cd98f00b204e9800998ecf8427e
```

Оба сохранённых значения пусты (`length=0`); непустых legacy-значений нет.
Единственная действующая редакция Core — глобальная `character.core`
(1778 символов JSON, md5 `6bc858986e846f49bf81c56d28882147`).

Решение по `system_prompt_overrides`:

* поле «Характер» удалено из основного UI; замена другим полем не создавалась;
* `savePersona()` больше не отправляет ключ — partial-PUT сохраняет существующее
  значение (проверено `bot_persona.save_persona` с существующей строкой);
* runtime не менялся: непустое legacy-значение (если появится) продолжает
  рендериться как раньше; пустое — ничего не формирует;
* условная read-only плашка `data-speech-legacy-character` показывается только
  в собственной области значения; на production она не рендерится (значений нет);
* столбец PostgreSQL и данные не удалялись, массовой миграции нет;
* `_duplicate_character_segment` оставлен: он защищает от повторной передачи
  legacy-характера, уже вошедшего в Core (backward compatibility).

## 4. Состав вкладки «Личность»

Порядок сверху вниз (id/анкеры для проверок):

1. `#speech-core-editor` — «Ядро личности (Personality Core)»: редактор сразу,
   существующая настройка включения, действующая область/редакция, высота,
   fullscreen (существующий), «Вернуть заводской», diff/обновление/наследование
   в существующем ⋯-меню, единственный sticky-save CTA, `data-speech-core-versions`
   (существующий `prompt-version-card` с историей/восстановлением).
2. `[data-speech-identity-editor][data-speech-persona-editor]` — «Идентичность»:
   имя, биография, «Осознаёт себя ИИ», существующие сохранение/сброс; поля
   «Характер» нет.
3. `[data-speech-acquired]` — «Приобретённые черты личности»: компактная ссылка
   в существующий «Статус» (`navigateTo('#/status')`), без переноса дашборда.
4. `[data-speech-persona-advanced]` — «Дополнительные настройки»: просмотр
   полной/компактной редакции, runtime-выбор (`saveSpeechCoreLevel`), техническая
   информация, ссылки на инспектор/«Все инструкции», legacy-плашка при наличии.

Навигация: `openSpeechSection('core')` → `persona` + фокус на `#speech-core-editor`;
deep-link `#/ai/persona` идёт через тот же загрузчик; отдельной страницы
`speechSection === 'core'` нет; «Правила и источники», инспектор и диагностика
сохранены. Просмотр другой редакции не меняет runtime-выбор (проверено:
после клика «Компактная» textarea показывает компактный текст, `Редакция по
умолчанию` остаётся `full`).

## 5. Проверки (фактические прогоны)

Кандидат, окружение: `.venv` (Python 3.12), node v24.16.0.

### RED/GREEN

RED на базе `886d11073` (подмена только `web/api/routes.py`, `web/index.html`,
`web/app.js` базовыми байтами; восстановление сверено по sha256):

```
4 failed, 9 deselected — test_reasoning_model_marks_only_temperature_values,
  test_core_block_is_first_and_inside_persona,
  test_identity_save_does_not_send_or_erase_legacy_value,
  test_direct_modes_card_ignores_temperature_metadata
```

GREEN на кандидате:

```
pytest tests/test_speech_applicability_core_ux.py -q  → 13 passed
```

Что доказывают зелёные (не grep-only):

* `/api/config` при `_primary_model_name()="o3-mini"`: пресет `active` без
  reason; три float-ключа `inactive` с температурной причиной; значения и
  источник не изменены; при `gpt-4o` всё `active`;
* реальная сборка `prompt_composer` на reasoning-модели: слои Core, Identity и
  речевой блок рендерятся, текст Core/«Имя: Бот» присутствуют в system;
  дублирующийся owner-характер по-прежнему снимается один раз;
* `bot_persona.save_persona(None, {"name": ...})` без ключа сохраняет
  `LEGACY_ХАРАКТЕР_ТЕКСТ` в UPSERT-параметрах;
* статический контракт UI: Core внутри `#speech-persona` до Identity, нет
  `speechSection === 'core'`, нет поля «Характер», deep-link через загрузчик,
  CSS min-height 300/220, полная ширина блока.

### Регрессия (профильные наборы)

```
pytest test_ur_ui_effective_config.py test_soul1_w6_speech_ui.py
       test_evol017_prompt_history_ui.py test_webapp_round1014_ui.py
       TestPersonaForm test_webapp_evol_w10_sections.py::TestEvol028AiHub
       test_speech_applicability_core_ux.py          → 54 passed
pytest test_round1025_f8_registry.py test_mca23_planned_vs_actual.py
       test_webapp_api.py test_ur_ui_effective_config.py
       test_evol017_prompt_history_ui.py             → 261 passed
node tests/js/ur_ui_settings_test.js                 → UR-F-UI-OK
node tests/js/prompt_version_card_test.js            → PVR-S4-CARD-OK
node tests/js/evol_w12_internals_test.js             → EVOL-W12-INTERNALS-OK
node tests/js/initiative_ui_rework_test.js           → INITIATIVE-UI-OK
node tests/js/app_methods_dup_keys_guard_test.js     → METHODS-DUP-KEYS-OK
```

Пины: `ROUTES_SHA256_F11` переутверждён осознанно (L-F11S-1) в каноне
`tests/test_round1025_f8_registry.py` и копии
`tests/test_mca23_planned_vs_actual.py`; новый sha256 routes.py =
`b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a`.
`services/param_catalog.py` не менялся — `PARAM_CATALOG_SHA256_FOLLOWUP` цел.

### Живой UI (Playwright, настоящие index.html/app.js/app.css на стабах API)

| viewport | Core первый | textarea h | min-height | Core/ширина контента | overflow X | history |
|---|---|---|---|---|---|---|
| 1280×900 | да | 300 px | 300px | 1008 / 1032 px | 0 | 1 |
| 390×844 | да | 338 px | 220px | 350 / 374 px | 0 | 1 |
| 320×568 | да | 227 px | 220px | 280 / 304 px | 0 | 1 |

Дополнительно: textarea «Характер» — 0; textarea идентичности — 1; legacy-плашка
— 0 (значений нет); «Развернуть» присутствует; кнопки редакций — 2; console
errors — 0. Поток «Правила и источники → Редактор Core» открывает ту же
вкладку и блок (`#speech-core-editor`, scrollY=285, top=16). Deep-link
`#/ai/persona` открывает ту же вкладку и загружает Ядро (history=1).

Дополнительно: сохранение Core реально уходит существующим контрактом
(`POST /api/speech/block/core.personality` с `text/scope/reason`), а сохранение
идентичности — `PUT /api/persona` без ключа `system_prompt_overrides`
(`{"name":…,"biography":…,"is_aware_ai":…,"updated_at":…}`); console errors 0.

Независимая проверка Browser Use (Chrome, та же страница на локальном стенде):
desktop 1036×905 — Core первый (`first=speech-core-editor`), textarea 300 px,
Core 965/989 px, history 1, поле «Характер» 0; переход по старой ссылке
«Правила и источники → Редактор Core» ведёт к тому же блоку; мобильный
390×844 — Core виден сразу, textarea 338 px, overflow 0, console errors 0.

Ограничение стенда: `prompt-version-card` на стабе без журнала показывает
честное «журнал недоступен» — это свойство стаба, не регрессия; реальная
история/восстановление не менялись.

### Предсуществующие red (не относятся к диффу)

Проверены на базе/по неизменённым файлам:

* `test_webapp_js_unit.py`: 7 red (`routing_test`, `round1024_image_key`,
  `round1025_hotfix7/8/9/10`, `round1025_f7_permsoc_local`) — `TypeError:
  this._embedModelSwapGuard is not a function`; воспроизведено на базовом
  `web/app.js` (886d11073) до правок.
* `test_webapp_round1014_ui.py::TestTraitsRibbon` (2) и
  `::TestStatusLayoutOrderF7` (1) — на базе 5 лент `class="ribbon "` вместо 4.
* `test_webapp_evol_w10_sections.py` — 6 статических red (`filteredModules.length`,
  `matrixRoleToggle` отсутствуют на базе) + live e2e (стенд/каталог/roles).
* `test_frontend_tab_mapping.py` (3) и `test_webapp_asap_cover_ui_v21.py` (5) —
  отсутствующие на базе маркеры (`nav.sections`, `a.created_at` и др.).
* `test_asap_speech_i_matrix.py` (9) — сервисные сценарии инициативы/случайности;
  изменённые файлы кандидата ими не импортируются (services не менялись).

## 6. Обновлённые существующие тесты (осознанная смена контракта)

* `test_soul1_w6_speech_ui.py` — `core` исключён из списка отдельных секций;
  добавлен инвариант «`#speech-core-editor` есть, `speechSection === 'core'` нет»;
  кнопка заводского сброса — с существующим аргументом раздела.
* `test_webapp_round1014_ui.py`, `test_webapp_evol_w10_sections.py` —
  на вкладке «Личность» больше нет поля `system_prompt_overrides`; 2 textarea
  теперь «Ядро + Биография», 3 input (Имя + 2 чекбокса).
* `test_evol017_prompt_history_ui.py`, `tests/js/prompt_version_card_test.js` —
  граница блока истории — `data-speech-core-editor` (вместо удалённой страницы
  `core`); компонент/ключи не менялись.
* `tests/js/ur_ui_settings_test.js` — карточка «Речь и характер» остаётся
  `active` при temperature-помеченном пресете; technical note проверяется на
  самой температурной настройке (`configEffBadge`).
* `tests/ui_p0a_ux_speech_compact_e2e.py`, `tests/ui_prompt_version_card_e2e.py`
  — перед переключением редакций открывается `[data-speech-core-editions]`
  (переключатель перенесён в «Дополнительные настройки»).
* `ROUTES_SHA256_F11` переутверждён (комментарий в каноне), копия синхронизирована.

## 6.1 Приёмка владельца (11 критериев)

| № | Критерий | Факт / доказательство |
|---|---|---|
| 1 | Core — единственный основной редактируемый источник постоянного характера | поле «Характер» удалено из UI; вкладка «Личность» ведёт в реестр Core; legacy-значений в production нет (length=0) |
| 2 | Отдельного поля «Характер» нет в основном интерфейсе | `#speech-persona` не содержит `system_prompt_overrides`; 2 textarea (Ядро+Биография), 3 input |
| 3 | Непустые legacy не потеряны/не отключены незаметно | значений нет; partial-PUT сохраняет значение (тест); read-only плашка только при наличии |
| 4 | Имя/биография/самопредставление работают | persona API/форма не менялись; payload Identity в промпте (тест) |
| 5 | Динамические черты/опыт/отношения/речь сохранены | ссылка в «Статус»; алгоритмы/сервисы не тронуты; speech-наборы зелёные (кроме предсуществующих red) |
| 6 | Core первый на вкладке без переходов | desktop/390/320: `first=speech-core-editor`, видим сразу |
| 7 | История/восстановление/области/права/редакции сохранены | `prompt-version-card` (1), «Вернуть заводской», ⋯-меню, scope-select; права `can_edit` |
| 8 | Полная/компактная доступны, выбор владельца не изменён | просмотр в «Дополнительных»; runtime select после переключения остаётся `full`; `selection.level` из API |
| 9 | Сохранение Core и Identity не перезаписывают друг друга | разные endpoint'ы; identity PUT без ключа характера; тест `save_persona` |
| 10 | Temperature не определяет применимость | 3 float-ключа `inactive`, пресет `active`; Core/Identity/Speech в payload |
| 11 | Desktop/mobile без дублирующих редакторов/полей | один `#speech-core-editor`, один `data-speech-identity-editor`; overflow 0 на 1280/390/320 |

## 6.2 Назначение поля «Характер» (факт по коду)

`personas.system_prompt_overrides` рендерится `bot_persona.build_persona_prompt_block`
в блок `<Persona>` строкой «Характер: …»; этот блок добавляется к system prompt
модели ответов (`direct_chat_service`, Writer-путь). Это короткая характеристика
в блоке идентичности, а не второй Personality Core; UI-поле удалено, значения и
механизм для legacy сохранены, тексты не объединялись.

## 7. Ограничения

* Массовых LLM-генераций, оценки качества речи/юмора и новых метрик нет.
* На production непустых `system_prompt_overrides` нет; специальный UI миграции
  не создавался (прямое указание владельца). Если значение появится, оно
  показывается read-only в «Дополнительных настройках» своей области и
  продолжает действовать до отдельного решения.
* Содержимое Core/Writer/L1 и пользовательские редакции не изменялись;
  `services/direct_chat_service.py`, `mca_retrieval_context.py`,
  `factcheck_planner.py`, `search_aggregator.py`, `direct_execution.py`
  не тронуты; схема/миграции/version-пины — без изменений.
