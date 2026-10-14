# Ревью F6 `prompts-refactor-accordion-modes-round1024` (шаг 5, раунд 10.24)

- **Коммиты:** iter1 `109cbce` → iter2 `c812f4d` (ответ на ревью 1; поверх влита F5-iter1 `235199a`).
- **Ревьюер:** @Reviewer
- **Метод:** изолированные worktree на каждом коммите (рабочее дерево основного репозитория содержало незакоммиченные правки других фич — F5/F21; ревью по грязному дереву некорректно). Полный pytest, JS-юниты и `node --check` прогнаны на коммитах.
- **Статус (итог, iter2):** **Approved**
- **Статус (iter1):** Changes Requested (раздел «Итерация 1» ниже — сохранён как история).

## Кратко (без смягчений)

Раскладку сделали хорошо: аккордеоны на «Промптах» убраны ровно и только там, `details.advanced` у `llm_providers` не тронут, табы режимов перенесены внутрь карточек, fallback-дропдаун рендерится один раз, Δ каталога = 0, Δ DDL = 0, полный pytest/JS-гейт зелёные. Но **главный контракт F6 — «предохранитель срабатывает только при сбое» — в реальной системе не работает**: до `compose_verbalizer_system` невалидный `response_mode` никогда не доходит, потому что `normalize_response_mode()` заранее подменяет его на жёсткий `"serious"`. То есть ключ `prompts.verbilizer_default_mode` (дефолт `casual`, который просил владелец) на боевом сбойном пути **не читается вообще**, а дропдаун остаётся декоративным. Тесты это не ловят — они проверяют изолированную функцию, а не проводку. Плюс клик по табу режима (чисто редактирование промпта) молча перезаписывает сам fallback-ключ из каждой карточки модуля — это прямо противоречит заявленной цели ADR «один ключ не редактируется из нескольких мест».

## Findings

### [High] Fallback-предохранитель недостижим на боевом сбойном пути — дропдаун не имеет runtime-эффекта

**Файлы/строки:**
- `services/system2_handoff.py:63-70` — `normalize_response_mode()`: любой неизвестный/пустой/`None` → `_DEFAULT_RESPONSE_MODE = "serious"` (`:42`).
- `services/direct_chat_service.py:945` — `response_mode = normalize_response_mode(data.get("response_mode"))`.
- `services/factcheck_service.py:165` — то же.
- `services/system2_handoff.py:221` (`parse_summary_handoff`) → `services/summary_generator.py:485` — то же.
- `services/prompt_style_blocks.py:185-190` (`_resolve_default_mode`) — ключ читается **только** из ветки `candidate not in MODE_BLOCKS` (`:253-254`).

**Проблема:** все три боевых вызова `compose_verbalizer_system` получают уже **валидный** `response_mode` — на сбое это принудительно `"serious"`, а не пусто/мусор. Ветка `_resolve_default_mode()` физически недостижима из продакшена. Значит:
- оператор ставит «Резервный режим (Fallback)» = `casual`, ожидая деградацию в `casual`, а система на сбое использует `serious`;
- ключ `prompts.verbilizer_default_mode` — мёртвый груз в UI.

**Почему это важно:** UPD3 №2 владельца назвал это «*Критично*: селектор… включается только при сбое». Спека §3.2/§8 и ADR-1024-10 D3 обещают «срабатывает только на сбойном пути (доказано тестами)». На деле не доказано и не срабатывает: зелёные тесты `tests/test_prompts_round1024.py` проверяют `compose_verbalizer_system("BASE", "wat")` в вакууме, куда боевой код никогда не попадает (туда приходит `"serious"`). Это классический «зелёные тесты — мёртвая фича»: операторский предохранитель, которым нельзя воспользоваться.

**Что сделать (выбрать одно и зафиксировать):**
1. Провести сбойную ветку до fallback: либо не коэрсить `"serious"` в `normalize_response_mode` (возвращать пусто/`None` для невалида, чтобы решение принимал `compose_verbalizer_system`), либо резолвить ключ `prompts.verbilizer_default_mode` в самой точке нормализации. После — **интеграционный** тест: Stage-1 JSON без валидного `response_mode` → собранный промпт использует значение ключа (не хардкод `serious`).
2. Либо, если команда сознательно ограничивает F6 слоем `compose`, — переписать §3.2/§5/§8 спеки и D3 ADR: убрать формулировку «срабатывает на сбойном пути», честно указать, что ключ сейчас inert (upstream coerces to `serious`), и получить явное подтверждение владельца. Молчаливое расхождение «владелец ↔ спека ↔ код» недопустимо.

### [Medium] Клик по табу режима перезаписывает fallback-ключ — противоречит ADR D4

**Файлы/строки:**
- `web/index.html:553-557` (V2-табы внутри карточек модулей): `@click="selectPromptMode(m.id)"`.
- `web/app.js:4073-4082` (`selectPromptMode`): `item.value = mode; this.saveConfigItem(item);` — пишет `prompts.verbilizer_default_mode`.

**Проблема:** табы в V2 нужны, чтобы **редактировать** промпт режима, но они дергают `selectPromptMode`, который сохраняет выбранный режим в ключ «Резервный режим (Fallback)». Т.е. переход на «Serious», чтобы поправить текст, молча меняет предохранитель на `serious` и шлёт PUT. И это происходит из каждой карточки с Вербализатором (6+ модулей) — один ключ редактируется из N+1 мест.
**Почему это важно:** ADR-1024-10 D4 обосновывает единственный рендер дропдауна именно тем, «чтобы один ключ не редактировался из нескольких мест» — сейчас эта цель нарушена в обход: сам дропдаун один, а пишет в него каждая карточка. «Строгий предохранитель» становится нестабильным значением, которое незаметно переписывается при обычной правке промпта.
**Что сделать:** развести семантику — таб только переключает `promptMode` (без `saveConfigItem`), fallback-ключ пишет **только** дропдаун в шапке. Если «сохранение как в 10.23» сознательно сохраняется — обновить спек/ADR и пометить явную нестыковку с «строгим предохранителем», плюс тест «переключение таба не меняет `prompts.verbilizer_default_mode`».

### [Medium/Low] Второй источник правды для fallback — дефолт аргумента `"serious"`

**Файл:** `services/prompt_style_blocks.py:234` — `def compose_verbalizer_system(base_prompt, response_mode: str = "serious", ...)`.
**Проблема:** канон fallback теперь `VERBILIZER_DEFAULT_MODE = "casual"` (`:163`), а дефолт параметра остался `"serious"`. Любой будущий вызов без `response_mode` получит `serious` (валидный режим) и **обойдёт** `_resolve_default_mode()`. Заявленный «единый канон в одном месте (ADR-1013-3)» нарушен.
**Что сделать:** привести дефолт к `casual` либо сделать параметр обязательным; комментарий с описанием канона — рядом.

### [Low] OFF-ветка не восстанавливает дефолт 10.23, как обещает ADR D5

**Файлы/строки:** `web/app.js:974` (`promptMode: 'casual'`), `web/app.js:4090` (`... ? value : 'casual'`), `services/prompt_style_blocks.py:163`.
**Проблема:** ADR-1024-10 D5 гласит: «OFF → раскладка и дефолт 10.23 (`serious` …)». Фактически и стартовое значение Vue, и синк из конфига, и код-дефолт — `casual` безусловно, флагом не гейтятся. Спека §3.2 при этом **требует** `casual` безусловно, так что код спеке соответствует, а ADR D5/спека §9 сформулированы неточно.
**Что сделать:** поправить формулировку ADR D5 (дефолт `serious` возвращается только `git revert`, не флагом OFF). Функционального дефекта нет, но расхождение «ADR ↔ код» в отчётах фиксируется.

### [Low] Тесты раскладки — по подстрокам, слабо и с over-claim

**Файл:** `tests/test_prompts_round1024.py` (`test_fallback_dropdown_rendered_once`, `test_mode_tabs_live_inside_module_cards`, `test_prompts_accordion_gated_by_flag`).
**Проблема:** тест с названием «rendered_once» проверяет лишь наличие подстроки `data-block="prompts-fallback-mode"`, но не «ровно один раз»; «отсутствие аккордеонов в V2» доказывается строкой `v-if`, а не рендером. Функциональный JS-тест (`tests/js/round1024_prompts_ui_test.js`) закрывает часть (плоский список, sync→casual, переключение таба), но именно fallback-проводка (#1) не покрыта.
**Что сделать:** считать вхождения `data-block="prompts-fallback-mode"` (assert == 1), добавить DOM-проверку отсутствия `<details class="advanced">` на «Промптах» в V2 и интеграционный тест сбойного пути (см. #1).

## Контракт

### Чекбоксы `tasks.md` (заявленные `[x]`)
- [x] T-2227 (AMEND ADR) — файл `ADR-1024-10.md` есть, D1–D5 описаны. Формально ок; D3-формулировка расходится с фактической проводкой (см. #1).
- [x] T-2228 (убрать аккордеоны) — подтверждено: `details.advanced` на «Промптах» гейтится `!uiFlag('PROMPTS_UI_V2_ENABLED')` (`index.html:594-596`), advanced идут в общий grid через `promptVisibleItems` (`app.js:4096-4102`). Пустые секции не рисуются.
- [x] T-2229 (дропдаун «Резервный режим (Fallback)») — подтверждено: `index.html:454-475`, `data-block="prompts-fallback-mode"`, `param_catalog.py:479-482` title/description обновлены. **Дефолт-эффект не подтверждён** (см. #1).
- [x] T-2230 (табы внутрь карточек) — подтверждено: `index.html:549-570`, над полем Вербализатора. **Регресс семантики** (см. #2 Medium).
- [x] T-2231 (backend fallback) — `VERBILIZER_DEFAULT_MODE="casual"`, fail-safe на мусор есть (`:185-190`); но шататный/сбойный роутинг на уровне системы не разведён (см. #1).
- [x] T-2232 (анти-клише не сломан) — подтверждено: блок `data-block="anticliche-monitor"` не тронут, тесты клише зелёные.
- [x] T-2233 (тесты) — часть есть, но fallback-проводка и `rendered_once` не доказаны (см. #1/#5).
- [x] T-2234 (пин-тесты каталога) — обновлены (`test_ui_verbilizer_tabs_round1023.py`, `test_verbilizer_response_modes_round1023.py`), ключ сохранён.
- [ ] T-2235 — данное ревью.
- [ ] T-2236 (DevOps) — вне scope ревью.

### Инварианты
- **Δ каталога = 0:** подтверждено — ключ `prompts.verbilizer_default_mode` на месте, изменился только `title_ru`/`description`; новых/удалённых ключей в диффе нет, `test_param_catalog` зелёный.
- **`VERBILIZER_DEFAULT_MODE = casual` + fail-safe:** подтверждено — `_resolve_default_mode()` при мусоре отдаёт `VERBILIZER_DEFAULT_MODE`.
- **`details.advanced` для `llm_providers` не тронут:** подтверждено — CSS `web/static/app.css` в диффе отсутствует; блоки `index.html:875/2124/2492` не изменены.
- **Флаг `PROMPTS_UI_V2_ENABLED`:** default ON (`config/settings.py:634-635`), доставлен через `web/api/routes.py:316-317`, потребляется `uiFlag`. OFF-логика в шаблоне покрыта (см. Low #4 и Medium #2).
- **`tma-menu-freeze`:** не нарушен — меню/`TABS`/`MODULES` коммит не трогал; `round1024_image_module_test.js` (`IMAGE-MODULE-OK`), `round1024_budget_toggle_test.js` (`BUDGET-TOGGLE-OK`) зелёные.
- **R16/R17/R18:** наружу только `bool` в `/api/me.ui_flags`; секретов/сырых значений в диффе и отчёте нет.
- **`parse_mode=None` / Δ DDL = 0:** миграций/`.sql`/канон-слепков в диффе нет.

### Тесты (прогон в чистом worktree `109cbce`)
- `node --check web/app.js` — OK.
- `node tests/js/round1024_prompts_ui_test.js` — `PROMPTS-UI-UNIT-OK`.
- `node tests/js/round1023_verbilizer_tabs_test.js` — `VERBILIZER-UNIT-OK`.
- `node tests/js/vue_mount_test.js` — `VUE-MOUNT-OK`.
- `node tests/js/round1024_image_module_test.js` / `round1024_budget_toggle_test.js` — OK.
- **Полный pytest:** `7803 passed, 1 failed` (собрано 7804). Упавший — `tests/test_history_cli.py::TestCliFts::test_scope_is_required` — **пре-существующий** артефакт кодировки консоли Windows (кириллица в stderr превращается в `?????`); воспроизводится на родительском коммите (задокументировано в `round1024_f5_reviewer.md`), к F6 отношения не имеет.

## Требуемые правки (точный список)

1. **`services/system2_handoff.py` / `services/direct_chat_service.py:945` / `services/factcheck_service.py:165` / `services/summary_generator.py:485`** — сделать fallback реально достижимым на сбойном пути (не коэрсить невалидный `response_mode` в `"serious"` до `compose`, либо резолвить `prompts.verbilizer_default_mode` там же). Добавить **интеграционный** тест: невалидный/пустой `response_mode` из Stage-1 → используется значение ключа (`casual`). Иначе — переписать §3.2/§5/§8 спеки + D3 ADR и подтвердить у владельца.
2. **`web/index.html:553-557` + `web/app.js:4073-4082`** — развести «переключение редактируемого режима» и «запись fallback-ключа»: таб не должен сохранять `prompts.verbilizer_default_mode` (только шапочный дропдаун). Тест: переключение таба не меняет ключ. Либо — обновить спек/ADR и зафиксировать противоречие с «строгим предохранителем».
3. **`services/prompt_style_blocks.py:234`** — дефолт `response_mode` привести к канону (`casual`) или сделать параметр обязательным.
4. **`ADR-1024-10 D5` (и §9 спеки)** — убрать неверное утверждение, что флаг OFF возвращает дефолт `serious`: код-дефолт `casual` безусловен, `serious` возвращается только `git revert`.
5. **`tests/test_prompts_round1024.py`** — усилить: `data-block="prompts-fallback-mode"` встречается ровно один раз; в V2 на «Промптах» `<details class="advanced">` не рендерится; покрыть проводку из п.1.

Верни исправленную версию. Текущий код отклонён.

---

# Итерация 2 — коммит `c812f4d` — **Approved**

- **Коммит:** `c812f4d` — `fix(services,web,tests): раунд 10.24 F6 — fallback на сбойном пути, таб не пишет ключ, дефолт casual (review iter1)` (10 файлов; поверх `235199a` влита F5-iter1 — к F6 не относится, не приписываю).
- **Метод:** чистый worktree на `c812f4d`; полный pytest, целевые тесты, JS-юниты, `node --check`.
- **Статус:** **Approved**.

## Findings итерации 2

Повторный аудит закрыл все блокеры итерации 1. Остаётся один **не блокирующий** nit:

### [Low / не блокирует] Устаревший docstring `validate_summary_digest`
**Файл:** `services/system2_handoff.py:248-249`.
**Проблема:** docstring всё ещё гласит «не-JSON raw проходит как выжимка с **режимом `serious`**», тогда как этот же коммит перевёл legacy-путь на `response_mode=""` (`:242`). Комментарий противоречит новому контракту сбойного сигнала.
**Почему не блокирует:** `validate_summary_digest` возвращает только `digest`, режим наружу не отдаётся; рантайм/тесты/контракт не затронуты. Мелкий техдолг — поправить в удобной правке («режим не выбран»).

### [Info] `test_history_cli` — среда, не F6
В чистом worktree полный pytest даёт `7809 passed, 1 failed` (собрано 7810). Единственное падение — `tests/test_history_cli.py::TestCliFts::test_scope_is_required` — артефакт кодировки консоли Windows (кириллица → `?????`); воспроизводится на родителе и в F5-ревью, к F6 не относится. В среде @Builder → `7810 passed / 0 failed`; заявленное число сходится.

## Проверка исправлений (по пунктам ревью 1)

1. **High (fallback недостижим) — ЗАКРЫТ.**
   - `normalize_response_mode` (`system2_handoff.py:68-81`) больше не коэрсит в `"serious"`: невалид/пусто/`None`/не-строка → `""` (сигнал сбоя); `_DEFAULT_RESPONSE_MODE` удалён полностью (grep по репо — 0 вхождений).
   - Парсеры кладут `""`: `parse_factcheck_analysis:201`, `parse_direct_synthesis:302`, `parse_summary_handoff:233,242`.
   - Все три боевых сервиса доходят до `compose_verbalizer_system` → `_resolve_default_mode()` → ключ `prompts.verbilizer_default_mode` (код-дефолт `casual`): `direct_chat_service.py:945-954`, `factcheck_service.py:165-176`, `summary_generator.py:487,508`.
   - **Интеграционные тесты** (`tests/test_prompts_round1024.py::TestFailurePathWiring`) идут через **реальные** `DirectChatService._synthesize_direct_answer`, `FactCheckService.check_claim`, `SummaryGenerator._generate_two_call` с замоканным LLM; сентинел `CASUAL_SENTINEL` в Stage-2 доказывает, что сбойный путь берёт **ключ**, а не жёсткий `serious`. Плечо «валидный режим побеждает» проверено: `deep_research` → `DEEP_SENTINEL` и отсутствие `CASUAL_SENTINEL`. Тесты не тавтологичны.
2. **Medium (таб писал fallback-ключ) — ЗАКРЫТ.** `switchPromptMode` (`app.js:4121-4124`) только переключает `promptMode`; `savePromptFallbackMode` (`:4128-4135`) — единственная точка записи ключа (шапочный дропдаун `index.html:467`); OFF-карточка 10.23 сохраняет `selectPromptMode` (`index.html:507,525`). JS-тесты блоков 4–5 прямо проверяют: таб не вызывает `saveConfigItem`, дропдаун пишет ровно один раз и не пишет при read-only. Правки режимных `textarea` персистятся штатным sticky-save (`dirtyItems` + `<sticky-save>`), не таб-кликом — регресса нет.
3. **Medium/Low (второй источник правды) — ЗАКРЫТ.** `compose_verbalizer_system(..., response_mode="")` (`prompt_style_blocks.py:234`); `SummaryDraft.response_mode=""` (`summary_generator.py:104`). Вызов без явного режима уходит на fallback-ключ.
4. **Low (ADR D5/§9) — ЗАКРЫТ.** `ADR-1024-10 D5` и `spec.md §9` приведены к факту: флаг OFF откатывает **только раскладку**, код-дефолт `casual` безусловен, `serious` — лишь полным `git revert`. (Файлы фичи — untracked, правки в рабочем дереве.)
5. **Low (слабость тестов раскладки) — ЗАКРЫТ.** `test_fallback_dropdown_rendered_exactly_once` считает вхождения (`HTML.count == 1`) и проверяет позицию до цикла карточек; аккордеон вынесен в render-предикат `promptsShowAccordion` (`app.js:4139-4145`, `index.html:595`) с функциональным JS-тестом блока 6; добавлены проверки привязок `switchPromptMode`/`savePromptFallbackMode`.

## Контракт (итерация 2)

- **Fallback-инвариант:** валидный `response_mode` приоритетен (ключ не читается); невалид/пусто → ключ-предохранитель. Доказано на реальной проводке (см. п.1). ✅
- **Δ каталога = 0:** `param_catalog.py` коммитом не тронут. ✅
- **Δ DDL = 0:** миграций/`.sql`/канон-слепков в диффе нет. ✅
- **`tma-menu-freeze`:** меню/`TABS`/`MODULES` не тронуты; `round1024_image_module_test.js` (`IMAGE-MODULE-OK`), `round1024_budget_toggle_test.js` (`BUDGET-TOGGLE-OK`). ✅
- **R16/R17/R18:** секретов/сырых значений в диффе нет; наружу — только `bool`. ✅
- **`parse_mode=None`:** не затронут. ✅
- **`SMART_VERBALIZER_MODES_ENABLED`:** поведение сохранено — при OFF direct-chat использует `"serious"` + прежний шаблон без `compose` (`direct_chat_service.py:942-955`), factcheck/summary аналогично; покрыто `tests/test_verbilizer_response_modes_round1023.py` (4 ссылки, зелёные). ✅
- **OFF-ветка 10.23:** карточка `prompts_verbilizer` с `selectPromptMode` сохранена; `promptsShowAccordion` в OFF эквивалентен прежнему `sec.advanced.length > 0`. ✅

## Тесты (чистый worktree `c812f4d`)

- `node --check web/app.js` — OK; `round1024_prompts_ui_test.js` → `PROMPTS-UI-UNIT-OK`; `round1023_verbilizer_tabs_test.js` → `VERBILIZER-UNIT-OK`; `vue_mount_test.js` → `VUE-MOUNT-OK`; `round1024_image_module_test.js` → `IMAGE-MODULE-OK`; `round1024_budget_toggle_test.js` → `BUDGET-TOGGLE-OK`.
- Целевые (F6/пины/двухвызовные direct+summary): `146 passed`.
- Тематические (system2/prompt/verbilizer/factcheck/summary/negative/handoff/cliche): `1349 passed`.
- `SMART_VERBALIZER_MODES_ENABLED`/R1023: `22 passed`.
- **Полный pytest:** `7809 passed, 1 failed` (собрано 7810) — падение единственного `test_history_cli` (см. [Info] выше), **не F6**. В среде @Builder — `7810 passed / 0 failed`.

## Итог

Все блокирующие findings итерации 1 закрыты корректно и подтверждены реальными интеграционными тестами. Инварианты (Δ каталога=0, Δ DDL=0, menu-freeze, R16/17/18, `parse_mode=None`, `SMART_VERBALIZER_MODES_ENABLED`) целы. Остался один не блокирующий устаревший docstring (`services/system2_handoff.py:249`).

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
