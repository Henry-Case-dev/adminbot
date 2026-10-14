# Отчёт @Reviewer — раунд 10.23, F8 `ui-verbilizer-tabs-round1023`

- **Коммит:** `2433343` — «feat(services,web,tests): раунд 10.23 F8 — UI Синтезатор/Вербализатор, табы режимов, монитор анти-клише, hot-get промптов»
- **Ревью:** Step 5, строгий аудит @Reviewer
- **Spec / ADR / задачи:** `plans/features/ui-verbilizer-tabs-round1023/spec.md`, `ADR-1023-8.md`, `tasks.md` (T-2167…T-2175)
- **Сквозной слой:** `plans/features/round1023-architecture.md` §3.4, §5
- **Гейты:** `node --check web/app.js` — OK; JS-юнит `VERBILIZER-UNIT-OK`; целевые pytest — 255 passed; полный pytest — **7398 passed / 0 failed** (заявленные 7375/0 — устаревшее число до +23 тестов F8).

## Статус: **Changes Requested**

Коммит в целом аккуратный: Δ каталога зафиксирован аддитивно, рантайм hot-get реализован с фолбэком, F4-инвариант (клише питает детектор, не промпт) соблюдён, freeze-меню и порядок роутеров не тронуты, полный pytest зелёный. Но один пункт критериев приёмки **не работает** (селектор «Режим по умолчанию» не сохраняется), а ещё два — дают видимые дефекты/регрессии UI. Это не «почти готово» — это недоделанная приёмка.

---

## Findings

### [High] Селектор «Режим по умолчанию» никогда не автосохраняется
**Файл:** `web/index.html:458-460` (шаблон) + `web/app.js:3835-3842` (`selectPromptMode`)
**Проблема.** Обработчик `@change="selectPromptMode(promptDefaultModeItem().value)"` передаёт в функцию **то же самое** значение, с которым функция сравнивает: `if (item && item.value !== mode && canEditConfig(...)) saveConfigItem(item)`. `promptDefaultModeItem().value` и `item.value` — одно и то же свойство одного и того же объекта (`configItems.find(...)`), между вычислением аргумента и входом в функцию оно не меняется. Значит `item.value !== mode` **всегда false** → `saveConfigItem` не вызывается никогда. Порядок DOM-события `v-model`/`@change` значения не меняет: и до, и после записи `v-model` аргумент равен текущему `item.value`.
Я проверил реальный рендер селекта через `Vue.compile` (vendor `vue.global.prod.min.js`): `onChange: $event => (selectPromptMode(promptDefaultModeItem().value))` — аргумент именно текущее значение, а не `$event.target.value`.
**Почему это важно.** Пункт ТЗ/спеки «UI-селектор … задаёт режим по умолчанию» и критерий приёмки «селектор режимов работает» не выполнены: пользователь выбирает режим в выпадающем списке, визуально он меняется, но в PG не уходит. При следующем `loadConfig`/`_syncPromptModeFromConfig` значение молча откатывается к старому — ровно тот «работает на моей машине», за который нельзя пускать в прод. Кнопки-табы (Tabs) сохраняют режим по другому пути (`selectPromptMode(m.id)`, где `mode !== item.value`), поэтому баг маскируется и не заметен при ручном клике по табам.
**Тест-пробел.** `tests/js/round1023_verbilizer_tabs_test.js:103-106` проверяет только путь таба (`'serious'` → `'casual'`), путь селекта не покрыт.
**Обязательное исправление.** Убрать самосравнение: в `selectPromptMode` сохранять всегда, когда режим реально сменился, а не когда `item.value !== mode`. Например:

```
selectPromptMode: function (mode) {
  if (!mode) return;
  var changed = this.promptMode !== mode;
  this.promptMode = mode;
  var item = this.promptDefaultModeItem();
  if (item && changed && this.canEditConfig(item.key)) {
    item.value = mode;
    this.saveConfigItem(item);
  }
},
```
и в шаблоне вызывать `@change="selectPromptMode($event.target.value)"` (не `promptDefaultModeItem().value`). Добавить в JS-юнит проверку пути селекта (значение из `$event.target.value`, факт вызова `saveConfigItem`).

---

### [Medium] Фейковые секции у групп без Stage-1/Stage-2 (`prompts_memory`, `prompts_checkup`)
**Файл:** `web/index.html:486-504` (секция «Вербализатор (Характер)» без `v-if` по наличию элементов) и `:490-493` (пометка «Модуль одностадийный»)
**Проблема.** Секция «Вербализатор (Характер)» рендерится **безусловно** для любого модуля. По факту (проверено через `param_catalog`) у групп `prompts_memory` (`prompts.extract_system_prompt`, `prompts.compress_system_prompt`) и `prompts_checkup` (`prompts.checkup_system_prompt`) **нет ни одного элемента со `stage`**. Итог: карточки «Память и граф знаний» и «Проверка» показывают пустую секцию «Вербализатор (Характер)» с ложной пометкой «Модуль одностадийный — только Вербализатор», хотя это фоновые промпты извлечения/сжатия, а не одностадийный ответ.
**Почему это важно.** Spec §3.2 прямо ограничивает правило одностадийности модулями Поиск/YouTube/Веб. Сейчас UI дезинформирует владельца.
**Обязательное исправление.** Рендерить секцию «Вербализатор (Характер)» и пометку об одностадийности только если `promptStageItems(grp, 'verbalizer').length > 0`; если у группы вообще нет staged-элементов — не рисовать секцию вовсе (сразу «Прочие промпты модуля»). Добавить тест-маркер на это поведение (или расширить JS-юнит для `grp` без staged-элементов).

---

### [Medium] Регрессия прав/оверрайдов на вкладке «Промпты» — выпал generic-рендер
**Файл:** `web/index.html:611` (`v-if="activeTab !== 'prompts' && …"`) и новый шаблон `:426-522`
**Проблема.** На вкладке «Промпты» полностью отключён generic-рендер, а новый шаблон повторяет только часть возможностей старого. Потеряны: шестерёнка `openPermPicker(item)` (права ключа, global admin), бейдж `item.chat_source === 'chat'` и кнопка `resetChatOverride(item)` («↪ глобальное»), а также прогрессивное раскрытие basic/advanced (advanced-ключи всегда развёрнуты). Ничего из этого spec/ADR не отменяли — «меняется только внутренний рендер вкладки» не означает потерю функций управления правами.
**Почему это важно.** Владелец теряет на вкладке «Промпты» штатный инструмент выдачи прав на конкретный промпт и сброса per-chat-оверрайда — это молчаливая деградация админ-функций.
**Обязательное исправление.** Вернуть в карточки F8 шестерёнку прав (для `isGlobalAdmin`), бейдж per-chat и «↪ глобальное»; либо явно подтвердить у @Architect/владельца удаление этих элементов и зафиксировать в spec (Human Gate). Без этого — восстановить.

---

### [Low] Phantom-ключ `content.dynamic_cliche_list` — его никто не читает/не пишет
**Файл:** `services/param_catalog.py:1804-1815`
**Проблема.** Ключ зарегистрирован как `hidden` PG-only, но ни один код-путь его не читает и не записывает: F4 хранит клише в PG-таблице `anticliche_cache` (см. `services/anticliche_cache.py`), GET `/api/config` hidden-ключи отфильтровывает (`web/api/routes.py:337-339`), `params-meta` — тоже (`:557-559`), UI-блок работает через `/api/anticliche`. Фактически ключ живёт только в REGISTRY и матрице прав. Дополнительно: spec §3.4 обещал «REGISTRY +1, categorized **не растёт**», а фактически categorized 422 → 433 (+11, включая этот ключ), и это зафиксировано во всех пинах.
**Почему это важно.** Владелец может выдать/увидеть право на ключ, который ни на что не влияет — «мёртвая ручка» в админке. Это техдолг-обманка.
**Обязательное исправление.** Либо удалить регистрацию ключа (тогда Δ = +10: REGISTRY 457, categorized 432, `prompts` 21/`content` 5) и обновить пины, либо оставить, но добавить в spec/ADR запись «права-only, значение не потребляется; владелец — F4-таблица» и пояснить расхождение с §3.4. Скрыть без объяснения нельзя.

---

### [Low] Пустое PG-значение не откатывается на код-константу у Stage-1/Stage-2 ридеров
**Файл:** `services/summary_generator.py:452-456`, `:472-478`; `services/factcheck_service.py:135-137`, `:163-167`; `services/direct_chat_service.py:909-911`, `:930-934`
**Проблема.** Spec §4.1/ADR D4 требуют: «пустота/отсутствие ключа → прежняя код-константа». `hot.get(key, CONST)` возвращает `""`, если ключ в кэше есть, но пуст (`services/hot_config.py:71-76`), — откат срабатывает только на отсутствие ключа. Обработка пустоты есть лишь в `_resolve_mode_block` (`services/prompt_style_blocks.py:161-172`), у трёх Stage-ридеров её нет.
**Почему это важно.** Сейчас риск смягчён серверной валидацией (`web/api/routes.py:514-519` не даёт записать пустой промпт), но инварианта как такового нет: значение из миграции/прямой правки PG даст LLM пустой system-промпт вместо канона.
**Обязательное исправление.** Ввести общий хелпер (по образцу `_resolve_mode_block`) или защитить каждый ридер: `val = hot.get(key, CONST); use val if isinstance(val, str) and val.strip() else CONST`.

---

### [Low] Тест `GET /api/config` на `stage` — тавтологичный (grep исходника)
**Файл:** `tests/test_ui_verbilizer_tabs_round1023.py:311-316`
**Проблема.** `test_config_exposes_stage` проверяет подстроку `'"stage": spec.stage if spec else None'` в тексте `web/api/routes.py`, а не фактический ответ эндпоинта. Это не тест контракта, а проверка «строка есть в файле».
**Почему это важно.** Регресс, из-за которого `stage` пропадёт из ответа (например, при рефакторе словаря), пройдёт мимо теста.
**Обязательное исправление.** Добавить поведенческий тест через TestClient (`GET /api/config`) на наличие `stage == 'synthesizer'` у `prompts.factcheck_analyst_system_prompt` и `stage is None` у обычного ключа. Grep-проверку оставить как дополнительную.

---

### [Low] Дублирование триггеров и незначительные хвосты UI
**Файл:** `web/app.js:1547-1552` (watcher), `:3637-3640` (`setTab`), `:4029-4030` (`loadConfig`)
**Проблема.** `_syncPromptModeFromConfig()`/`maybeLoadCliche()` дёргаются из трёх мест; фактически защита от двойного запроса есть (`clicheLoading`), но код избыточен. `maybeLoadCliche` после первого успеха больше никогда не обновляет дату в рамках сессии. `_syncPromptModeFromConfig` не санитизирует невалидное PG-значение (тогда ни один таб не подсвечен).
**Почему это важно.** Низкая, но это «мусор в горячем UI-пути».
**Обязательное исправление.** Оставить один канал (watcher достаточен), в `maybeLoadCliche` добавить refresh по TTL либо явную кнопку (она уже есть — force); `_syncPromptModeFromConfig` сверять значение со списком `promptModeTabs`.

---

## Контракт: чекбоксы

| Пункт | Статус | Комментарий |
|---|---|---|
| Spec §2.1 секции Синтезатор/Вербализатор | ⚠️ | Реализовано, но у групп без staged-элементов рисуется ложная секция (Medium) |
| Spec §2.2 селектор режимов | ❌ | Табы работают; выпадающий селект default-mode не сохраняется (High) |
| Spec §2.3 блок `dynamic_cliche_list` (дата/force/PUT/fail-open) | ✅ | F4-API `/api/anticliche`, `/refresh`, PUT; fail-open скрывает блок |
| Spec §2.4 правка Stage-1/2 влияет на рантайм | ✅ | hot-get в 3 сервисах; тесты на кэш/fallback; 2 LLM-вызова сохранены |
| Spec §2.5 freeze (NAV_ITEMS/20/витрина) | ✅ | новых вкладок нет, `TAB_RULES`=20, витрина не тронута |
| `ParamSpec.stage` (+ `GET /api/config`) | ✅ | аддитивно; поведенческий тест отсутствует (Low) |
| F4-инвариант: клише не в промпте/не scrubber | ✅ | `dynamic_cliche_list` нигде не читается как промпт; детектор не тронут |
| Рантайм hot-get: без рестарта | ✅ | `hot.get` + fallback; правки PG применяются |
| fallback на код-константы | ⚠️ | на «отсутствие» — да; на «пустое значение» — только у режимов (Low) |
| `physical-two-call-pipeline` (2 вызова) | ✅ | тесты `await_count == 2` |
| egress-реестр (новых точек нет) | ✅ | новых egress/роутов нет; F4-роутер подключён ранее |
| R16/R17/R18 | ✅ | API аддитивно; значения не логируются; секреты не закоммичены |
| `parse_mode=None` | ✅ | F8 разметку не менял |
| порядок роутеров `bot.py` | ✅ | `bot.py` в коммите не менялся |
| F1–F7 не сломаны | ✅ | полный pytest 7398/0 |
| XSS | ✅ | интерполяция только `{{ }}`, `v-html` не добавлен |
| UI: Синтезатор/Вербализатор + Tabs | ✅ | табы `Casual|Serious|Deep Research` |
| UI: блок клише (дата/форс/ручная правка) | ✅ | дата `fake`/`fetched_at`, POST refresh, PUT |
| UI: `node --check` + JS-юниты | ✅ | `VERBILIZER-UNIT-OK` |

## Δ каталога (фактически проверено)

| Метрика | Было (F7) | Стало (F8) | Δ | Совпадает с отчётом |
|---|---|---|---|---|
| REGISTRY | 447 | **458** | +11 | ✅ |
| Settings-поля | 416 | **416** | 0 | ✅ |
| categorized | 422 | **433** | +11 | ✅ (но §3.4 spec обещал «не растёт» — см. Low) |
| GROUPS | 95 | **96** | +1 (`prompts_verbilizer`, order 9) | ✅ |
| `_TAB_BY_GROUP` | 93 | **94** | +1 | ✅ |
| TAB_RULES / TAB_NAV / вкладки | 20 | **20** | 0 | ✅ |
| prompts-ключей | 11 | **21** | +10 | ✅ |
| content-ключей | 5 | **6** | +1 (hidden cliche) | ✅ |

Пины обновлены **осознанно и консистентно** в `test_param_catalog.py`, `test_frontend_tab_mapping.py`, `test_webapp_api.py`, `test_webapp_parity_smoke.py`, `test_budget_settings_round1019.py`, `test_help_guide_round1014.py`, `test_self_reflection_provider_round1014.py`, `test_settings_persistence_round1014.py`, `test_round106_ia_smoke.py`, `test_webapp_round109/1010/1011/1012/1013/1014/1020_ui.py` — без ослабления assertions.

## Тесты

- Целевые: `test_ui_verbilizer_tabs_round1023`, `test_param_catalog`, `test_frontend_tab_mapping`, `test_webapp_js_unit`, `test_webapp_api` — **255 passed**.
- Полный pytest: **7398 passed / 0 failed** (заявлено 7375/0 — stale-число). `node --check web/app.js` — OK; JS-юнит — OK.
- Замечания к качеству: (1) не покрыт путь селекта default-mode (пропущен High-баг); (2) `test_config_exposes_stage` — grep исходника, а не ответ API (Low); (3) нет теста на ложную секцию у `prompts_memory`/`prompts_checkup` (Medium не пойман).

## Список для @Builder (обязателен к исправлению)

1. **High:** `web/app.js:3835-3842` — `selectPromptMode` сохранять по факту смены режима (не `item.value !== mode`); `web/index.html:460` — `@change="selectPromptMode($event.target.value)"`. Добавить JS-юнит на путь селекта.
2. **Medium:** `web/index.html:486-504` — секцию «Вербализатор (Характер)» и пометку «Модуль одностадийный» рендерить только при наличии `verbalizer`-элементов; иначе группа без staged-элементов рендерит только «Прочие промпты модуля». Тест на `prompts_memory`/`prompts_checkup`.
3. **Medium:** `web/index.html:426-522` — вернуть в карточки F8 шестерёнку прав (`openPermPicker` для global admin), бейдж `chat_source`/сброс оверрайда («↪ глобальное») и basic/advanced-дисклоузер; либо зафиксировать их удаление у @Architect (Human Gate).
4. **Low:** `services/param_catalog.py:1804-1815` — либо удалить phantom-ключ `content.dynamic_cliche_list` (Δ = +10, REGISTRY 457, categorized 432, content 5) с обновлением пинов, либо добавить в spec/ADR явную запись «права-only, не потребляется» и синхронизировать §3.4 про categorized.
5. **Low:** Stage-ридеры (`summary_generator`, `factcheck_service`, `direct_chat_service`) — добавить откат на код-константу при пустом/whitespace PG-значении (общий хелпер).
6. **Low:** `test_ui_verbilizer_tabs_round1023.py:315-316` — заменить grep на поведенческий тест `GET /api/config` (поле `stage`).
7. **Low:** `web/app.js` — сократить дублирующиеся триггеры (`watcher`/`setTab`/`loadConfig`), санитизировать `promptMode` по списку `promptModeTabs`.

После правок — повторный прогон целевых тестов, JS-юнита, `node --check web/app.js` и полного pytest; обновить `plans/reports/round1023_f8_reviewer.md` (итерация 2).

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — повторный аудит

- **Коммит-фикс:** `27c7b2a` — «fix(services,web,tests): раунд 10.23 F8 — автосейв режима, секции/права карточек, fail-safe промптов (review iter1)»
- **База сравнения:** `27c7b2a^` = `f69551f` (F9). **Важно:** F9 (`f69551f`, Справка v5/Гайд v2) влит до фикса; изменения F9 к F8-фиксу не приписываю (диф `27c7b2a^..27c7b2a` их не содержит — файлы `services/info_service.py`, `web/index.html` в части Справки, `plans/docs/canon/**` не затронуты).
- **Гейты итерации 2:** `node --check web/app.js` — OK; JS-юнит `VERBILIZER-UNIT-OK`; целевые pytest — **261 passed**; полный pytest — **7413 passed / 0 failed** (повторный прогон; в первом прогоне была 1 flaky-ошибка F9 — см. Info).

## Статус итерации 2: **Approved**

Все 7 замечаний итерации 1 закрыты по существу, а не косметически. Ключевой High подтверждён **независимо**: я скомпилировал шаблон через `Vue.compile` (vendored `vue.global.prod.min.js`) — обработчик стал `onChange: $event => (selectPromptMode($event.target.value))`, а `selectPromptMode` сравнивает `this.promptMode !== mode` (не `item.value`). Проверил и численно, и логически путь селекта: v-model успевает записать `item.value`, аргумент = `$event.target.value`, `changed = promptMode(старый) !== mode(новый)` → `saveConfigItem` вызывается. Ложных секций у памяти/проверки больше нет, права/оверрайды/дисклоузер вернулись, phantom-ключ удалён, fail-safe пустоты покрыт тестами.

## Верификация закрытия замечаний

| # | Замечание iter1 | Факт итерации 2 | Статус |
|---|---|---|---|
| High 1 | Автосейв селекта default-mode | `web/index.html:460` → `@change="selectPromptMode($event.target.value)"`; `web/app.js:3871-3881` → `changed = this.promptMode !== mode`. Реальный compiled-render подтверждает. JS-юнит `round1023_verbilizer_tabs_test.js:140-166` моделирует v-model (`item.value='deep_research'`) и проверяет `savedSel == ['deep_research']`, плюс повторный выбор — без повторного сохранения. Тест не тавтологичен (на старом коде падал) | ✅ |
| Medium 2 | Ложные секции у memory/checkup | `promptSections(grp)` (`web/app.js:3816-3849`) — секции строятся условно: `synth.length → synthesizer`, `verb.length → verbalizer` (+ note об одностадийности только при `synth.length==0`), `other.length → other`. Группы без staged-элементов дают только «Прочие промпты модуля». JS-юнит 1b проверяет 3 кейса; отдельно — отсутствие ложной секции | ✅ |
| Medium 3 | Права/оверрайды/дисклоузер | В обеих ветках (basic/advanced) восстановлены `item.chat_source==='chat'`, `itemHiddenDev`, `openPermPicker(item)` (global admin), `itemOverriddenByChat` + `resetChatOverride(item)`; advanced — в `<details>` c `expandOpen(activeTab)`/`toggleExpand`. Тест `test_html_restores_perms_and_override_controls` | ✅ |
| Low 4 | Phantom `content.dynamic_cliche_list` | Удалён из `_build_registry` (`services/param_catalog.py:1804-1809`). Δ = +10: REGISTRY **457**, categorized **432**, prompts **21**, content **5**; все пины обновлены (15 файлов на 457, `test_param_catalog` на content:5, `test_webapp_api` на 432). Spec §3.5/§3.4 и ADR D7 синхронизированы; `test_phantom_cliche_key_not_registered` — `get_by_pg_key(...) is None` | ✅ |
| Low 5 | Пустое PG-значение → код-константа | Введён `resolve_prompt(pg_key, code_default)` (`services/prompt_style_blocks.py:163-175`): `value.strip()` → код-канон. Подключён во всех трёх Stage-ридерах (`summary_generator` Stage-1/2, `factcheck_service` Stage-1/2, `direct_chat_service` Stage-1/2). `TestEmptyPgFallback` покрывает helper + summary/factcheck/direct | ✅ |
| Low 6 | Тест `stage` — grep | Добавлен поведенческий `tests/test_webapp_api.py::test_config_exposes_prompt_stage` (POST/GET `/api/config`): `synthesizer` у analyst-ключа, `None` у обычного; grep оставлен как дополнительный гейт | ✅ |
| Low 7 | Дубли триггеров / refresh / санитайз | Триггер в `setTab` удалён (остался watcher `activeTab` + `loadConfig`); `maybeLoadCliche` обновляет список при каждом входе (`!clicheLoading` — защита от параллели); `_syncPromptModeFromConfig` санитайзит значение по `promptModeTabs` → `serious` | ✅ |

## Findings итерации 2

### [Low] У группы режимов Вербализатора нет inline-шестерёнки прав
**Файл:** `web/index.html:432-467` (спец-блок `prompts_verbilizer`)
**Проблема.** В обычных карточках модулей `openPermPicker`/сброс оверрайда восстановлены, а в специфическом блоке режимов (4 ключа `prompts.verbilizer_mode_*` + `..._default_mode`) inline-шестерёнки прав и бейджа per-chat по-прежнему нет; доступно только `canEditConfig`-дизейбл.
**Почему это важно.** Не блокер: права на эти ключи настраиваются на вкладке «Доступы» (матрица `param_permissions`), функциональность не потеряна — потерян лишь inline-ярлык для группы режимов.
**Обязательное исправление (не блокирует приёмку).** При следующей правке UI — вынести блок режимов на общий рендер с секциями или добавить к каждому mode-элементу ту же кнопку прав/сброса. Оформить как follow-up Low.

### [Info] Разовый flaky-тест F9 в полном прогоне (не F8)
**Файл:** `tests/test_help_ui_round1023.py::TestGuideMigrationV1ToV2::test_reset_guide_returns_to_canon_with_backup`
**Наблюдение.** В первом полном прогоне — 1 failure (`7412 passed`), во втором — `7413 passed / 0 failed`; изолированно и в семейном прогоне `guide/info`-модулей — зелёный. К F8 отношения не имеет (F9-канон/`content.info_how_it_works`, F8-ключи не пересекаются; совместный прогон F8+F9-файлов — чисто). Это ранее известная нестабильность guide/info-порядка. Рекомендация @Builder/@DevOps (вне F8): стабилизировать фикстуры guide-миграций. Заявленные «7404 passed» — неполное число; фактическое на HEAD — **7413/0**.

## Контракт (итерация 2)

| Пункт | Статус |
|---|---|
| Spec §2.1 секции Синтезатор/Вербализатор | ✅ (условные, без ложных) |
| Spec §2.2 селектор режимов (Tabs + select default) | ✅ (автосейв обоих путей) |
| Spec §2.3 блок `dynamic_cliche_list` (дата/force/PUT/fail-open) | ✅ |
| Spec §2.4 правка Stage-1/2 влияет на рантайм без рестарта | ✅ (`resolve_prompt` + hot-get) |
| Spec §2.5 / `tma-menu-freeze` (20 вкладок, NAV_ITEMS, витрина) | ✅ (freeze-тесты зелёные) |
| `ParamSpec.stage` + поведенческий `GET /api/config` | ✅ |
| F4-инвариант (клише — только детектор/мониторинг, не промпт/scrubber) | ✅ (ключ удалён из каталога, UI через `/api/anticliche`) |
| fallback на код-константы (включая пустое значение) | ✅ (`resolve_prompt`) |
| `physical-two-call-pipeline` (ровно 2 вызова) | ✅ (`await_count == 2`) |
| egress-реестр (новых точек нет) | ✅ |
| R16 (аддитивный API) / R17 (без секретов в логах) / R18 (секреты не коммичены) | ✅ |
| `parse_mode=None`, порядок роутеров `bot.py`, F1–F7/F9 не сломаны | ✅ |
| XSS (`{{ }}`, без `v-html`) | ✅ |
| UI: `node --check` + JS-юниты | ✅ |

## Δ каталога (фактически, после `27c7b2a`)

| Метрика | F8 iter1 | iter2 | Итог Δ от F7 |
|---|---|---|---|
| REGISTRY | 458 | **457** | +10 |
| Settings-поля | 416 | **416** | 0 |
| categorized | 433 | **432** | +10 |
| GROUPS | 96 | **96** | +1 (`prompts_verbilizer`) |
| `_TAB_BY_GROUP` | 94 | **94** | +1 |
| TAB_RULES / TAB_NAV | 20 | **20** | 0 |
| prompts-ключей | 21 | **21** | +10 |
| content-ключей | 6 | **5** | 0 (phantom удалён) |

## Тесты (итерация 2)

- Целевые: `test_ui_verbilizer_tabs_round1023`, `test_param_catalog`, `test_frontend_tab_mapping`, `test_webapp_js_unit`, `test_webapp_api` — **261 passed**.
- Полный pytest — **7413 passed / 0 failed** (повторный прогон; см. Info про разовый flaky F9).
- `node --check web/app.js` — OK; `node tests/js/round1023_verbilizer_tabs_test.js` — `VERBILIZER-UNIT-OK`.

## Follow-up (не блокирует F8)

1. **Low:** inline-шестерёнка прав/сброс оверрайда для группы `prompts_verbilizer`.
2. **Info (F9, вне F8):** стабилизировать fixture-порядок guide-миграций (flaky).

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
