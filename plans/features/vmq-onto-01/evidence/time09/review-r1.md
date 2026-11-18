# VMQ-TIME-09 - независимое ревью R1 (per-run годы/исключения)

**Кандидат:** `fix/vmq-time09`, tip `eefd555c24231bacbf91209332351b6de96515ce` (evidence), продуктовый коммит `738bd3a2f`; база/deployed `f68e7631dede326995b985bf8c3849d62def1bcb` (2.58.217, content `b6c9bb0b`, schema 48).
**Ревью-окружение:** собственный чистый detached-worktree от точного tip (`.../time09-review-r1-68b14f8c5248-59b6b2ca`); Python 3.12.0, pytest 9.1.1, node v24.16.0; temp SQLite + инжектированный ASGI/HTTP; production/SSH/БД не трогались, деплоя нет.
**Контракт:** `plans/features/vmq-onto-01/evidence/time09-ui-brief-2026-11-19.md` (`511db744`).
**Вердикт: NEEDS FIXES.** Backend/контракт/тесты в целом корректны и подтверждены собственными прогонами; на двух изменённых UI-поверхностях найдены 4 IN_SCOPE дефекта честности/меток (1 major, 3 medium). Все они локальны в `status-analytics.js`/`app.js`/`index.html`, воспроизводятся на реальном рендере; исправление объёмом около 10 строк + 1-2 теста.

## 1. Что фактически прочитано

| Место | Проверено |
|---|---|
| `services/mca_retrieval_context.py:1127-1133, 2542-2548, 3187-3193` | `RetrievalRequest.trace_id: str\|None=None` (frozen dataclass, без `__post_init__`); `trace_id=request.trace_id` в `invalid` и основном `success/silent` emit; иных изменений `retrieve()` нет |
| `services/mca_events.py:390-404, 642-711, 736-765` | `emit_stage_event` -> `build_event`; `trace_id` в `_ID_FIELDS`, `_safe_value(None)->None`, при `None` поле НЕ добавляется (event-паритет); строка `[A-Za-z0-9_\-:.]{0,64}` принимает uuid4 hex `new_correlation_id()` |
| `services/direct_chat_service.py:5089, 5311-5321, 10518, 10601-10605, 11086, 11330-11333, 14746-14762, 14850-14854, 14943-14958, 15286, 15494, 15590-15607` | один `correlation_id` хода протянут в `_build_user_content` -> `_build_rag_block` -> `_rag_unified_rows`/`_rag_retrieve` (включая period extra и plan-rescope) и `_build_old_episodes`; `trace_id=None` -> kwarg не добавляется; `prepared.correlation_id` - тот же id, что у `direct_turn_selection` (`:3410`) |
| `web/api/routes.py:1845-1900, 2138-2155, 2217-2290, 2736-2756` | схемы `years`/`years_present`/`_TURN_PERIOD_SCHEMA`; `_turn_retrieval_view` (закрытый R17-набор, `period_selection` отброшен, `excluded` нормализуется только при наличии положительных); bounded `<=6` по `ts`; отдельный запрос `limit=32`; `stages.retrieval`; 403/RBAC - существующий гейт (`:2671`) |
| `web/static/status-analytics.js` (весь) | helper `sortedYears/exclusionRows/writerBlocks/primaryRun/latestRun/sortRuns/view`; `_writerRow` и `_runView` |
| `web/app.js:10210-10290, 13299-13307, 19164-19255, 22193-22212, 28925-28929` | один store/loader, TTL 15 c, single-flight, `seq`-guard, очистка при смене чата; entry Status force, entry Analytics cache |
| `web/index.html:9397-9567, 15550-15635, 19201-19210` | вставки Status (после `data-memory-tech`, до `data-intents`), Analytics (после `data-viz-flow`, до `mca-17c`/Embeddings), подключение скрипта до app.js |
| `tests/test_vmq_time09_turn_coverage.py`, `tests/js/vmq_time09_year_coverage_ui_test.js`, `tests/ui_vmq_status_analytics_e2e.py`, `tests/test_ur_f_inspector_step2.py:354,435` | ассерты прочитаны; 2 `stages`-ассерта - строгое dict-равенство (не ослаблено, добавлен `retrieval: False`) |
| `tests/test_round1025_f8_registry.py:261-291, 576-581`, `tests/test_mca23_planned_vs_actual.py:97-105` | re-pin - sha256 ВСЕГО `web/api/routes.py`; отдельный `test_routes_set_unchanged` доказывает дельту routes=0 |
| `plans/.../time09/{implementation.md,limitations.md,tests-time09.json,mutations-time09.json,red-base-time09.*,time09-playwright.json}` | точность evidence сверена с моими прогонами |

`git diff --name-only f68e7631d..HEAD`: ровно 6 product-файлов + 5 тестовых + evidence/brief. Байт-идентичны (`git diff --quiet` = 0): `app.css`, `web/app.py`, `handlers/web.py`, `web/api/memory_overview.py`, `services/memory_diagnostics.py`, `services/database.py`, `config/settings.py`, `tests/fixtures/round1025/f8_baseline.json`.

## 2. Мои независимые прогоны (из своего worktree)

| Команда | Результат |
|---|---|
| `pytest tests/test_vmq_time09_turn_coverage.py -q` | **12 passed** (9.05 s) |
| `pytest tests/test_ur_f_inspector_step2.py -q` | **19 passed** |
| `pytest <16 affected files> -q` (набор 481) | **481 passed** |
| `pytest <24 mandatory-386 files> -q` | **386 passed** (42.03 s) |
| `pytest` QRNG P1/P3 + voice (5 файлов) | **204 passed** (регрессий QRNG/voice нет) |
| `node tests/js/vmq_time09_year_coverage_ui_test.js` | `VMQ-TIME09-UNIT-OK` |
| все `tests/js/*.js` на кандидате | **124 файла, 4 failed**: `asap6_wave2_ux_tabs`, `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings` |
| те же на чистой базе `f68e7631d` | **123 файла, те же 4 failed** -> регрессий 0 |
| `python tests/ui_vmq_status_analytics_e2e.py` | `ok=true`, 51/51, console 0, `retrieval_coverage=0`, 7 GET diagnostics (non-admin - 0) |
| RED-эссенция на базе `f68e7631d` (probe): `_turn_selection_view` с `years`/`memory_period` | база отдаёт `years=None`, `memory_period=None`; у `RetrievalRequest` нет поля `trace_id`; `_turn_retrieval_view` отсутствует. Заявленный RED правдоподобен |
| реальный app (`create_app`): GET `/web/index.html` + `/static/status-analytics.js?v=<APP_VERSION>` | 200; подстановка версии есть, `__APP_VERSION__` не остаётся; новый файл реально раздаётся (e2e это не проверял) |

### Собственные мутации (все убиты, откачены, `git status` чист)

| # | Мутация | Результат |
|---|---|---|
| MUT-1 | `view()` добавляет `pct: "49%"` | node: `AssertionError: в view не должно быть процентов` |
| MUT-2 | `out.primary = latestRun(runs)` (самый свежий периодный выдан за основной) | node: `Status показывает основной вызов, а не периодный добор` |
| MUT-3 | `_writerRow().delivered = !!block` (rendered=false засчитан доставленным) | node: `rendered=false не считается доставленным до Writer` |
| MUT-4 | `truncated = false` (скрытие усечения) | node: падение на `state !== truncated` |
| MUT-5 | убрать фильтр `period_selection` в `_turn_retrieval_view` | pytest: `1 failed` (`bounded: ... period_selection не строка`), 11 passed |

### Собственные контрактные челленджи

1. **Cap <=6 и порядок** (temp pytest): 8 основных retrieval-событий одного `trace_id` + selection -> API вернул **6** строк `ts=[1700100000..1700100005]`, отсортированы по возрастанию, т.е. сознательные первые 6. Кандидатский тест этот cap не проверяет (см. B1).
2. **Изоляция чатов**: retrieval-событие того же `trace_id`, но другого `chat_id`, в ответ не попало; фильтр запроса + пост-проверка работают.
3. **`years_present` для Writer-блока**: реальное событие `direct_turn_selection` с `rag.years={}` -> API `{"years": null, "years_present": true}` (измеренный ноль сохранён как факт).
4. **Мобильный Analytics**: 390/320, 4 вызова: `scrollWidth-innerWidth = 0`, `card scrollWidth-clientWidth = 0`, 44 px у кнопок навигации/обновления, скрытый 4-й вызов в `<details>`.
5. **Смена хода**: после кнопки предыдущего хода в Аналитике возврат в Статус делает `turn=2` и показывает более ранний ход, подписанный как последний.

## 3. Проверка контракта (что подтверждено)

1. **Аддитивность/паритет.** `trace_id=None` не добавляет поле в durable-событие (`_safe_value(None)->None`; тест `test_retrieval_event_carries_trace_id_and_parity_without_it` проверяет durable-строку). `retrieve()`, ранжирование, бюджеты, лимиты не менялись; новых retrieval/search/model-вызовов нет; добавлен только bounded-запрос телеметрии в endpoint.
2. **Корреляция.** `direct_turn_selection` и `mca07_retrieval` одного хода несут один `correlation_id` (создаётся один раз в `_handle_turn`:5089, попадает в prepared/selection:3410 и в оба retrieval-пути). Plan-rescope и period extra - тот же id; старые двойники с узкой подписью не ломаются (TypeError-fallback без trace).
3. **API.** `selection.blocks[].years`/`years_present`, `selection.memory_period`, `retrieval[]` не более 6 по `ts`, `period_selection` исключён, `excluded` - закрытый набор 5 причин только при наличии положительных, `{}` отличим от отсутствия; R17 - только коды/числа (маркер свободного текста в ответ не прошёл); 403 без доступа; старый ход без retrieval - `[]` + `stages.retrieval=false`.
4. **RBAC/данные/конфиг.** Гейт - существующий chat-access; non-admin не видит блок и не делает запрос (e2e + карточка Status под `v-if="isGlobalAdmin"`). DDL/schema 48, новых таблиц/store/флагов/endpoint нет; `APP_VERSION=2.58.217` не менялся; `f8_baseline` не переиздавался.
5. **Re-pin `ROUTES_SHA256_F11`.** Обоснован: пин - sha256 всего файла; отдельный тест `test_routes_set_unchanged` доказывает одинаковый набор маршрутов (76 декораторов, 63 уникальных пути и на базе, и на кандидате); новых `@api_router` нет; `f8_baseline` идентичен. Nit: комментарий говорит про 62 уникальных пути, фактически 63.
6. **UI.** Точное место: Status - после «Здоровья памяти» (`data-memory-tech`), до «Инициативы» (`data-intents`); Analytics - после «Цикл памяти (24ч)» (`data-viz-flow`), до «Embeddings» (между ними `v-if`-скрытый mca-17c на вкладке memory). Нет процентов/доната/KPI/таблицы/canvas/svg; 5 причин; кнопки 44 px; «Подробнее» - 44 px через существующий `btn-ghost`; `app.css` байт-идентичен; 320/390/1280 без горизонтального overflow; существующие карточки и 7 суб-вкладок не изменены; запрос ровно один на вход/обновление, aggregate-endpoint не вызывается. `status-analytics.js` отдаётся реальным FastAPI `/static`-mount с версией.

## 4. Дефекты (все IN_SCOPE, требуют исправления до release preparation)

| # | Severity | Место | Воспроизведение | Ожидание -> Факт |
|---|---|---|---|---|
| F1 | **major** | `web/static/status-analytics.js:201-221` (`_runView` не возвращает `yearsPresent`), потребители `web/index.html:9502`, `:9529` | `node -e "const A=require(\"./web/static/status-analytics.js\"); const r=A.view({available:true,selection:{blocks:[],truncated:false},retrieval:[{ts:1,years:{\"2023\":2},years_present:true,excluded:{budget:1},excluded_present:true}]}).runs[0]; console.log(r.yearsPresent)"` -> `undefined`; Playwright (temp probe, 390/320/1280): каждая строка показывает годы и рядом **нет данных** | Присутствие лет (chips показаны) -> подпись нет данных не выводится; unknown -> только нет данных. **Факт: противоречие на каждой строке каждого вызова** |
| F2 | medium | `web/index.html:15613-15622` + `web/app.js:10253-10259` | API-ответ с `primary.excludedPresent=false` (реальный кейс события без `excluded`; покрыт pytest `:523-524`); Playwright probe: строка «Исключено:» пустая | «Исключено: нет данных» -> **факт: пусто после «Исключено:»** (не нули, но и не честная подпись) |
| F3 | medium | `web/static/status-analytics.js:123-135` (строка 132), API подтверждение `web/api/routes.py:2138-2155` | Реальное `direct_turn_selection` с `rag.years={}` -> API `{"years": null, "years_present": true}`; helper `yearsText(null)` -> нет данных | Измеренный `{}` -> «нет фактов» (brief §3.4: «0 фактов»; принцип ноль не равен неизвестно) -> **факт: нет данных**, т.е. измеренный ноль выдан за отсутствие данных |
| F4 | medium | `web/app.js:28925-28929` (entry Status force без сброса `memoryYearCoverageTurn`), метки `web/index.html:9447`, `:15588`; сообщение `status-analytics.js:286-288` | Playwright probe: Аналитика -> предыдущий ход; возврат в Статус -> запрос `turn=2`, текст «**последний ход** · 18.11.2026, 23:05:40 · ... ход t2»; `no_selection` тоже говорит «У последнего хода» | Статус по контракту показывает последний ход (сброс turn=1 на входе) ИЛИ метка отражает выбранный ход; **факт: более ранний ход назван последним** |

Дефектов в backend-контракте, корреляции, R17, RBAC, cap/sort, DDL и сохранении соседних карточек не найдено. F1-F4 - локальные UI-дефекты; F1 виден всегда, F2-F4 - на явно предусмотренных контрактом состояниях.

## 5. Неблокирующие замечания (BACKLOG_ONLY / исправить заодно, если рядом)

| # | Severity | Место | Суть |
|---|---|---|---|
| B1 | low (test gap) | `tests/test_vmq_time09_turn_coverage.py:463-505` | Название теста про bounded, но он не подаёт больше 6 основных вызовов: cap `_TURN_RETRIEVAL_MAX=6` не покрыт (мой probe: 6 из 8, первые по ts; код работает). Добавить кейс с 8 вызовами. |
| B2 | low (test/evidence) | `implementation.md` §4, `tests-time09.json` | Формулировка bounded в отчёте опирается на тест, который cap не проверяет; факт подтверждён только ревью-пробой. |
| B3 | low | `web/static/status-analytics.js:183-193` | `latestRun` экспортируется и тестируется, но в UI не используется (Status использует `primaryRun`): тест про stale-run защищает мёртвый helper; использовать или убрать. |
| B4 | low | `web/app.js:10219-10246`, поле `memoryYearCoverageTrace` | Ветка явного `trace_id` в загрузчике недостижима: UI нигде не ставит `memoryYearCoverageTrace` непустым (мёртвый код). |
| B5 | low | `web/index.html:9502/9529` vs API | При более 6 вызовов API молча отбрасывает поздние; UI не сообщает, что показаны не все (для реального хода обычно не более 4, практически недостижимо). |
| B6 | low | `web/index.html:9447/15588` + `:9409` | «последний ход» дублируется в подзаголовке и runline; после фикса F4 проверить единообразие. |
| B7 | nit | `web/index.html:9429-9430` | `aria-busy="true"` стоит на spinner-div, а не на контейнере блока (brief §3.4 просит на блоке). |
| B8 | nit | `web/static/status-analytics.js:216-220` | При измеренном нуле (`years_present=true, years={}`) не выводится причина `retrieval_empty` (brief §3.4 приводит «0 фактов, причина retrieval_empty»); сейчас только «нет фактов». |
| B9 | nit | `tests/test_round1025_f8_registry.py:270` | Комментарий про 62 уникальных пути: фактически 63 (пин при этом верный). |

## 6. Ответы на вопросы автора

1. **Достаточно ли `stages.retrieval` + 2 обновлённых assert?** Да. Оба assert - строгое равенство словаря, добавлен только `retrieval: False` (не ослабление); отдельного теста обратной совместимости сверх этого не нужно: старый ход уже проверяется (`stages.retrieval=False`, `selection=None`).
2. **Приемлем ли re-pin `ROUTES_SHA256_F11`?** Да, осознанный re-pin по L-F11S-1 обоснован: это sha256 всего файла, а `test_routes_set_unchanged` доказывает дельту routes=0; `f8_baseline` не переиздавался, версия/DDL не менялись. Nit - число 62 в комментарии (факт 63).
3. **«Первые не более 6 по времени» вместо «последние 6»?** Приемлемо: основной вызов хода ранний, поэтому первые 6 сохраняют главный вызов и периодный добор; для реального хода (не более 4) cap недостижим. Рекомендую тест на больше 6 (B1) и, при желании, маркер «показаны не все» (B5).
4. **Достаточно ли inline 44 px?** Да: `app.css` байт-идентичен (требование брифа), все четыре кнопки измерены 44 px, «Подробнее» - 44 px через существующий `btn-ghost`; иной путь не нужен.
5. **Нужен ли `block.years_present`?** Да, нужен: API-проекция схлопывает `{}` в `null`, и только `years_present` отличает измеренный ноль от отсутствия данных (подтверждено реальным событием). Но сейчас UI это не использует -> F3; после фикса поле обязательно к сохранению.

## 7. Ограничения этого ревью

- **Browser Use - blocked** (как и в evidence): `BU_CDP_URL=http://127.0.0.1:9222` недоступен (`WinError 10061`), browse-расширение `paired-offline`, подключённых браузеров нет. Реальный browser-осмотр не заявляется; визуальный слой выполнен Playwright-рендером реальных `index.html`+`app.js`+`app.css` и element-скриншотами (390/320/1280), просмотренными глазами.
- **Нет live-прогона/прода**: только temp SQLite, ASGI/HTTP и детерминированные стабы; реальный ход с `mca07_retrieval.trace_id` и сверка SQL-UI остаются post-deploy агентской проверкой.
- **Playwright-стабы** повторяют схемы реального API (не прод-БД); e2e не покрывает Analytics-overflow на 390/320, состояния `excluded_present=false`, `years={}` у блока и переход «Аналитика -> Статус» с turn больше 1. Именно эти пробелы и выявили F1-F4; рекомендую добавить их в e2e при фиксе.
- **RED** проверен по эссенции на базе (поля/класс отсутствуют) и по сохранённому выводу автора; новый тест-файл на базу не копировал (чужой worktree не трогал).
- Temp-артефакты ревью (не в репозитории): `C:\Users\main\AppData\Local\Temp\opencode\time09-review-r1\` - `analytics_390.png`, `analytics_320.png`, `elem_390_an.png`, `elem_320_an.png`, `elem_320_st.png`, `status_zero.png`, `status_missing.png`, `status_skipped.png`, probe-скрипты/JSON. Секретов нет; продовые данные не читались.
- Worktree ревью - detached от `eefd555c2`; продуктовых правок не вносил, временные мутации откатывал через `git checkout --`. Worktree удалён после проверки.

## 8. Точные команды (из worktree ревью)

- `python -m pytest tests/test_vmq_time09_turn_coverage.py -q`
- `python -m pytest tests/test_ur_f_inspector_step2.py -q`
- `python -m pytest <16 affected files> -q`
- `python -m pytest <24 mandatory-386 files> -q`
- `node tests/js/vmq_time09_year_coverage_ui_test.js`
- `node <каждый tests/js/*.js>` (124/4; база 123/4, те же 4)
- `python tests/ui_vmq_status_analytics_e2e.py --out <temp>/pw.json --shots <temp>/shots`
- `python -m pytest <temp>/test_time09_cap_probe.py -q -s`
- `python -m pytest <temp>/test_time09_zero_probe.py -q -s`
- `python -m pytest <temp>/test_time09_static_probe.py -q -s`
