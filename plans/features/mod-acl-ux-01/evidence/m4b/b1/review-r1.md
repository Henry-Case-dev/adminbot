# M4B B1 - независимое ревью r1

- Фича: MOD-ACL-UX-01, M4B B1 «Пять лент: досье, дедупликация, сетка».
- База: `40fe603f0aac853af99656bac1934ec5f3d160f9` / 2.58.223 (deployed).
- Product candidate: `333b18da3a4e45e99b7e50b2f947d0c40ffe1953`.
- Branch tip: `95e4c101095a17e7fa58866f091ee1001bd83d56` (docs/evidence only above product).
- Branch: `release/mod-acl-m4b1-2.58.224`.
- Worktree: `WorkspaceData/worktrees/.../mod-acl-ux-01-1e46be007668-512d7d77`.
- Reviewer: независимый; продукт/тесты/карта/статусы не изменялись. Дата: 2026-11-20 21:00 +12.
- Контракт: `plans/features/mod-acl-ux-01/evidence/m4b/m4b-m4c-brief.md` §4.1, §3, §6, §7; owner input `2026-11-09-mod-acl-ux-01.md` §5.7/§6/AC-14/15/16/18; design §4.7/§6/§8/§11.

## 1. Вердикт

**NEEDS_FIXES.** Продуктовая часть B1 в основном соответствует контракту: пять лент, person-проекция, сетка 3+2 / 2+2+1 / 1, detail/provenance/pause/resume, a11y и клавиатура реально работают; backend/API/DDL/flags/prompts не тронуты. Но candidate нельзя принять из-за трёх IN_SCOPE расхождений: 14 ранее зелёных Python-тестов, сломанные e2e-инструменты старого тикера и сквозной cross-scope stale-показ досье (MAC-S15-03).
```json
{
  "verdict": "NEEDS_FIXES",
  "feature": "MOD-ACL-UX-01",
  "increment": "M4B B1",
  "base": "40fe603f0aac853af99656bac1934ec5f3d160f9",
  "candidate": "333b18da3a4e45e99b7e50b2f947d0c40ffe1953",
  "branch_tip": "95e4c101095a17e7fa58866f091ee1001bd83d56",
  "branch": "release/mod-acl-m4b1-2.58.224",
  "covered_rows": [
    {"id": "MAC-S6-307", "status": "PASS_UI_POSTDEPLOY_LIVE"},
    {"id": "MAC-AC-16", "status": "PASS_UI"},
    {"id": "MAC-S6-FEED-01", "status": "PASS"},
    {"id": "MAC-S6-FEED-02", "status": "PASS_COMPONENT"},
    {"id": "MAC-S6-FEED-03", "status": "PASS_UI_POSTDEPLOY_LIVE"},
    {"id": "MAC-S15-03", "status": "FAIL_BLOCKING"},
    {"id": "MAC-S15-04", "status": "PARTIAL_COMPONENT_B3"},
    {"id": "MAC-S0-11", "status": "PARTIAL_B1"},
    {"id": "MAC-S15-15", "status": "PASS_UI_POSTDEPLOY_LIVE"}
  ],
  "findings": [
    {"id": "B1-R1-F01", "scope": "IN_SCOPE", "severity": "high", "blocking": true, "title": "14 ранее зелёных Python-тестов стали красными; нет осознанного обновления контракта"},
    {"id": "B1-R1-F02", "scope": "IN_SCOPE", "severity": "medium", "blocking": true, "title": "e2e-инструменты w10/w15 ссылаются на удалённые тикер/карточку и детерминированно падают"},
    {"id": "B1-R1-F03", "scope": "IN_SCOPE", "severity": "medium", "blocking": true, "title": "MAC-S15-03: смена чата вне «Статуса» оставляет чужие строки досье до ответа"}
  ],
  "non_blocking_count": 9,
  "tests": {
    "node_targeted": "9/9 маркеров rc=0",
    "node_broad": "125 файлов, те же 4 baseline-падения на base и candidate",
    "pytest_mandatory_24": "386 passed, 0 failed",
    "pytest_contract_6files": "base 9 failed/171 passed; candidate 23 failed/157 passed (delta +14)",
    "e2e_b1": "131 checks, 0 failures",
    "mutations": "4/4 мутации падают, восстановление зелёное",
    "red_on_base": "новый node-тест на базовых байтах: 4 != 5, rc=1"
  },
  "limitations": [
    "Playwright/Browser Use - локальный стенд на candidate-байтах с синтетическими API, не живая TMA/production.",
    "Live MAC-S6-307/S15-03 остаются postdeploy; живой 503/пустой чат - RFL.",
    "e2e-инструменты ui_evol_w10_sections_e2e.py / ui_evol_w15_composition_e2e.py не исполнялись: статически доказан детерминированный разрыв селектора.",
    "Визуальный diff tools/ui_cmv_perf_parity.py не запускался; baseline сетки B1 намеренно меняется."
  ]
}
```

## 2. Покрытие строк

| Строка | Статус ревью | Что проверено лично |
|---|---|---|
| MAC-S6-307 | **PASS (UI)**; live - postdeploy | Ровно 5 секций в одной карточке, «Досье» пятая и последняя; старой нижней карточки нет; e2e + real Chrome. |
| MAC-AC-16 | **PASS (UI)** | Нет нижней копии, нет `.dossier-ticker`, нет 1:1-дубля: 5 записей -> 4 person-строки; detail/provenance/pause/resume общие. |
| MAC-S6-FEED-01 | **PASS** | 1920/1440/1280 - 3 колонки и ряды 3/2; 768 - 2 и 2/2/1; 390/320 - 1 колонка + 5 вкладок; `scrollWidth <= innerWidth+1`. |
| MAC-S6-FEED-02 | **PASS (компонентная часть)** | Тот же `v-sfeed`/`SFeed`, 168 px, wheel/touch пауза, возврат, позиция, reduced-motion; W2a 141 и W2c 84 зелёные. |
| MAC-S6-FEED-03 | **PASS (UI)**; live - postdeploy | Тот же `/api/oversight/dossier_feed?limit=16` (+`chat_id`); пустой чат - честная строка без чужих имён; ACL/backend не менялись. |
| MAC-S15-03 | **FAIL - B1-R1-F03** | Внутри «Статуса» смена чата очищает ленту; при смене чата на другой вкладке старые строки показываются при возврате (см. repro). |
| MAC-S15-04 | **PARTIAL (компонентная часть B1)** | Pause/resume, touch 44, keyboard, длинные/неизвестные значения не ломают общий слой; полный resilience-набор - B3, как в брифе. |
| MAC-S0-11 | **PARTIAL (B1)** | Досье переехало к живым лентам; «Последний вызов» и воронка - B2, не заявляются. |
| MAC-S15-15 | **PASS (UI)** | Строка досье датируется `created_at` (не `message_timestamp`/`last_confirmed_at`), дата - день/месяц, не «сегодня» вне окна; e2e/node. |

## 3. Фактический candidate и scope

`git diff 40fe603f..95e4c101 --name-status`: product - только `web/app.js`, `web/index.html`, `web/static/app.css`; tests - 1 новый и 6 изменённых `tests/js/*`; tools - новый `ui_mod_acl_m4b_status_e2e.py`; evidence `m4b/b1/**`. `web/api`, `services`, `config`, `database.py`, `migrations`, prompt-файлы - 0 изменений.

Product numstat (совпадает с заявленным): app.js +246/-76, index.html +63/-76, app.css +35/-138 = **+344/-290**. Blob SHA продукта совпадают с `tests.json` (`6bf9ee95...`, `efb60bdc...`, `300f1659...`). `git diff --check 40fe603f..95e4c101` rc=0; `node --check web/app.js` rc=0; `git diff 333b18da..95e4c101 -- web tests tools` пусто (тип - evidence).

**Удалённые 138 CSS-строк.** Удалены `.dossier-ticker*`, `.status-dossier__track`, `.dossier-ticker__excerpt/__meta` и их reduced-motion-ветки. Grep по продукту (`web/app.js`, `web/index.html`, `web/static/app.css`) не находит потребителей; остаются только `plans/docs/widget-map-round1025.md`, старые Python/JS-тесты и e2e-инструменты (F01/F02). `.dossier-auto`, `statusRowDateLabel`, `statusRowTitle`, `openFeedDossier` не тронуты.

**`DOSSIER_LIVE_FEED_ENABLED` - non-blocking.** На базе флаг был env-only `ClassVar` (default ON, вне `param_catalog`, `config/settings.py:1277-1282`), доставлялся через `/api/me.ui_flags` и выбирал только стиль нижнего тикера: ON - вертикальный, OFF - прежняя горизонталь 42s; **оба** рендерили один и тот же `dossierFeedLoop`, данные не скрывались. UI больше не читает флаг; backend-значение не менялось, `test_flag_delivered_additionally` зелёный. Это не пользовательская настройка и не скрытие данных, поэтому не blocker; остаётся мёртвый kill-switch для отдельного cleanup.

**Продуктовый код (личный осмотр).** `dossierPeopleFeed` (`app.js:13057+`) группирует по `user_id`, fallback по имени, иначе `unknown`; `latest` - по `created_at`; число записей/чат/origin сохраняются. `_resetDossierFeedScope` (13938) вызывается только в ветке `activeTab === 'status'` (14872/14893). `loadDossierFeed` (22111) берёт epoch до `await`, проверяет `_scopeGuard` после ответа и в `finally` снимает busy. `onStatusRibbonKeydown`/`statusRibbonKeyTarget` без wrap и с `_wsKeyIgnored`. `index.html`: пятая секция `data-intel-section="dossier"`, `role=tablist/tab`, `aria-selected`, `aria-current="page"`, roving tabindex, `ref="intelTabs"`, touch-стили; клонов/`aria-hidden` больше нет. CSS: 1 колонка по умолчанию, 2 при >=768, 3 при >=1280, вкладки только <=767.

**W2a/W2c/W3.** W2a 141 и W2c 84 проверки зелёные; W2b history (397) зелёный и покрывает `unavailable/off/denied/empty`; W3-файлы не менялись.

## 4. Выполненные проверки (команды и результаты)

| # | Команда | Результат |
|---|---|---|
| 1 | `node tests/js/mod_acl_ux_m4b_feeds_test.js` | `MOD-ACL-UX-M4B-B1-FEEDS-OK`, rc=0 |
| 2 | 7 изменённых/новых JS-файлов | ASAP-UI02-RIBBONS-OK, DOSSIER-FEED-OK, F11-STATUS-GRID-OK, SOUL1-W5-PANEL-OK, JS-UNIT-OK, EVOL-001-005-OK, B1-маркер; rc=0 |
| 3 | `node tests/js/mod_acl_ux_m4a_w2a_tabs_freshness_test.js` | 141 проверка, rc=0 |
| 4 | `node tests/js/mod_acl_ux_m4a_w2c_navigation_layout_test.js` | 84 проверки, rc=0 |
| 5 | `node tests/js/mod_acl_ux_m4a_w2b_history_test.js` | 397 проверок, rc=0 |
| 6 | broad: каждый `tests/js/*_test.js` по одному | candidate **125 файлов, 4 failed**; base **124, те же 4** (`asap6_wave2_ux_tabs`, `evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings`) |
| 7 | mandatory 24-file pytest set (точно из 2.58.210 evidence) | **386 passed, 0 failed**, 27.34 s |
| 8 | `py -3.12 -m pytest -q -p no:cacheprovider tests/test_dossier_feed_round1024.py` | candidate **5 failed / 11 passed** (см. F01) |
| 9 | те же 6 файлов на base `40fe603f` | **9 failed / 171 passed**; на candidate **23 failed / 157 passed**; delta **+14** candidate-only |
| 10 | `py -3.12 tools/ui_mod_acl_m4b_status_e2e.py` (свои SHOTS/REPORT в temp) | `{"ok": true, "checks": 131, "failures": []}` |
| 11 | RED: candidate-тест + base `web/*` в temp | `actual 4, expected 5`, rc=1 |
| 12 | мутации M1-M4 (temp-копия candidate-байтов) | M1 4 vs 5 секций; M2 «>=1280: три колонки»; M3 4 vs 3 строки; M4 «выбранный чат реально фильтрует запрос (S15-03)»; после restore rc=0 |
| 13 | `git diff --check`, `node --check` | rc=0, rc=0 |

### Browser Use / real Chrome (независимо)

- 1920x1080: 3 колонки, ряды 3/2, 4 строки досье, `hScroll=false`.
- 1440x900: 5 видимых секций, 3 колонки (373 px), 3/2, 4 строки досье (`Аня · 2`, `Борис · 1`, `Гость · 1`, `Участники не определены`), `data-status-dossier` = 0, `.dossier-ticker` = 0, aria содержит «записей: 2 ... источник: chat_history, summary».
- 1280x800: 3 колонки, 3/2. 768x1024: 2 колонки, 2/2/1, вкладки скрыты.
- 390x844: 1 колонка, видна одна лента, 5 вкладок (высоты 44, ширины 63-93), после клика «Досье» `aria-current="page"`, `aria-selected="true"`, видна только досье-лента; `hScroll=false`.
- Клавиатура в реальном Chrome: «Досье» -> ArrowLeft -> «Эволюция», End -> «Досье», ArrowRight на краю остаётся «Досье».
- Detail: клик по «Аня» открывает `[data-sfeed-modal]` с полным текстом, типом, чатом, subject, Telegram user id, `created_at`/`message_timestamp`/`last_confirmed_at`; `[data-rec-dossier]` открывает `#dossier-edit`.
- Визуально (1440 и 390): иерархия читаемая, клиппинга/overflow нет; на 390 пять вкладок переносятся в две строки - косметика, не нарушение.

## 5. Findings

### B1-R1-F01 - 14 ранее зелёных Python-тестов красные (IN_SCOPE, high, **blocking**)

- **Ожидаемо:** при намеренной замене контракта (удалён нижний тикер/`dossierFeedLoop`/`DOSSIER_LIVE_FEED_ENABLED`-ветка, 4->5 секций, `aria-pressed`->`aria-selected`) все затронутые статические тесты осознанно обновлены на новые assertions, как сделано для `tests/js/**`.
- **Фактически:** 14 тестов, зелёных на base, падают на candidate:

1. `tests/test_dossier_feed_round1024.py::TestDossierFeedStatic::test_css_vertical_marker_and_reduced_motion`
2. `...::test_css_seamless_uses_gap_var`
3. `...::test_css_speed_var_used_by_track`
4. `...::test_index_gates_flag_and_keeps_off_branch`
5. `...::test_appjs_speed_and_click_path`
6. `tests/test_webapp_evol_w10_sections.py::TestEvol026Widgets::test_dossier_feed_lives_in_status`
7. `tests/test_webapp_evol_w10_sections.py::TestEvol029MemoryCatalog::test_chat_title_instead_of_raw_id`
8. `tests/test_webapp_evol_w10_sections.py::TestEvolStatusOrderWave2::test_order_health_map_widget_others`
9. `...::test_one_widget_with_four_sections`
10. `...::test_phone_switcher_markup_and_css`
11. `tests/test_webapp_evol_w15_composition.py::test_dossier_ticker_row_aligned_with_feeds`
12. `tests/test_webapp_round1020_ui.py::TestLiquidGlassAndGrid::test_reduced_motion`
13. `tests/test_webapp_round1020_ui.py::TestDossierTicker::test_markup_and_css`
14. `...::TestDossierTicker::test_reactivity_markers`

- **Не pre-existing:** base-прогон тех же 6 файлов даёт 9 других падений (catalog/live e2e/role classes/tabs-navbar-labels), ни одного из 14 перечисленных.
- **Почему blocking:** это доказанная candidate-регрессия тестового контракта, а не «чужая старая поломка»; проектная политика требует не пропускать тесты и не понижать assertions. Механический release-гейт 386 их не включает, поэтому 386 честно зелёный, но репозиторий после candidate краснее базы на 14 тестов. Исправление - только тесты: переписать статику под 5 лент/person-проекцию/отсутствие тикера/`aria-selected`/roving tabindex, сохранив смысловые проверки; тест не удалять.
- **Scope note:** заявленный write scope B1 - `tests/js/**`; для корректного закрытия нужен явный test-only addendum на `tests/test_webapp_*.py` (продукт не меняется).

### B1-R1-F02 - e2e-инструменты старого тикера сломаны (IN_SCOPE, medium, **blocking**)

- `tools/ui_evol_w10_sections_e2e.py:74` считает `[data-status-dossier] .dossier-ticker`; `:488` падает при `<1`. На candidate оба селектора отсутствуют, поэтому fail на `#/` детерминирован.
- `tools/ui_evol_w15_composition_e2e.py:143,485,3194` ищут `[data-status-dossier]` / `.dossier-ticker__item`; парный Python-тест `test_dossier_ticker_row_aligned_with_feeds` уже падает (`правило .dossier-ticker__track--y .dossier-ticker__item не найдено`).
- `tests/js/asap6_wave2_ux_tabs_test.js:438` (`dossier-ticker-wrap`) уже в 4 baseline-падениях на base, поэтому отдельно не считается новой регрессией, но после B1 навсегда устарел; обновить в том же test-cleanup.
- **Требуется:** осознанно перевести инструменты на 5-ленточный контракт (пятая секция / отсутствие тикера), приложить RED на base и зелёный прогон; либо явно вывести инструмент из эксплуатации решением Orchestrator/PM с записью, но не удалять молча.

### B1-R1-F03 - cross-scope stale досье при смене чата вне «Статуса» (IN_SCOPE, medium, **blocking**)

- **Код:** `_resetDossierFeedScope` (`app.js:13938`) вызывается только из ветки `activeTab === 'status'` (`14872`/`14893`). Глобальная смена чата (`scopeEpoch++`, `14800`) досье не очищает; при входе в «Статус» `startDossierFeedPolling()` (`29257`) рисует старый `dossierFeed` до ответа нового запроса.
- **Repro (real Chrome, локальный стенд, кандидатские байты):** (1) 1440, выбрать `Audit Chat`, дождаться 4 строк досье; (2) обернуть `window.fetch`, задержав только `dossier_feed` с `chat_id=-1009876543210` на 2.5 s (задержка нужна лишь чтобы окно стало наблюдаемым; путь unconditional); (3) `#/modules`, сменить scope на `Тихий чат`, затем `#/` («Статус»); (4) сразу после возврата видны строки `["Аня","Борис","Гость","Участники не определены"]` из `Audit Chat`; через 3.2 s - честное пустое состояние «В выбранном чате досье пусто... Данные других чатов не подставляются.»
- **Ожидаемо (MAC-S15-03):** после смены scope ни в один момент не показывается личная история другого чата.
- **Причина/фикс:** shared state `dossierFeed` живёт дольше scope; нужен scope-ключ на данных (рендерить только при совпадении) или сброс при любой смене чата/входе в «Статус», а не только в status-ветке. Затрагивает и первую ленту «Новые факты» (тот же массив), поэтому чинится общий источник.
- **Честно:** поведение не введено B1 - старая нижняя карточка и первая лента имели тот же stale-путь; но MAC-S15-03 заявлена в B1 и унаследована пятой лентой, поэтому это открытая контрактная строка. Исправление маленькое и в write scope B1 (`web/app.js` + тест).

## 6. Non-blocking / backlog

1. **N01 `DOSSIER_LIVE_FEED_ENABLED`** больше не читается UI; backend-флаг остался мёртвым kill-switch. Не blocker: флаг был env-only, не пользовательский, скрывал только стиль удалённого тикера, данные не прятал. Cleanup - отдельной задачей; backend в B1 не трогать.
2. **N02** Устаревший комментарий «Телефон: ... все четыре ленты» (`app.js` рядом с `switchStatusRibbon`) и подобные - docs/comment-only.
3. **N03** `tests.json` заявляет broad **126** файлов; фактически **125** (`git ls-files`), 121 passed + 4 baseline. Поправить evidence-артефакт.
4. **N04** На 390 пять вкладок переносятся в две строки (4+1) - тач-цели 44 px сохранены; косметика.
5. **N05** Окно записи из «Досье» озаглавлено «Новые факты · запись #...» (переиспользованное окно); приемлемо, можно уточнить подпись в B2/B3.
6. **N06** При 503 одинаковый error-блок показывается и в «Новых фактах», и в «Досье» (общий источник); дубля данных нет, поведение честное.
7. **N07** В рабочем дереве на момент ревью присутствуют чужие modified evidence: `plans/features/evol/audit/evidence/w10-sec-*` (24 файла, mtime 20:39, писатель `ui_evol_w10_sections_e2e.py`, не этот ревью). Продукт не затронут; не включать эти файлы в коммит/релиз B1 и не откатывать чужую работу.
8. **N08** `dossierFeedBusy` - boolean: после `_resetDossierFeedScope` старый in-flight `finally` может снять busy у нового запроса, возможны параллельные `dossier_feed`; epoch защищает данные, наблюдаемого UI-дефекта нет.
9. **N09** `tools/ui_cmv_perf_parity.py` (visual diff 320-1440, baseline под новую сетку) не запускался ни автором, ни ревью; продуктовая регрессия не доказана, но evidence-строка брифа остаётся незакрытой - решение за release-lane.

## 7. Independent challenge summary

| Мутация | Ожидание | Факт |
|---|---|---|
| M1 убрать 5-ю секцию (`ribbon--dossier`) | node fail | 4 != 5, rc=1 |
| M2 4 колонки на >=1280 | node fail | «>=1280: три колонки (3+2, не пять узких)», rc=1 |
| M3 person-группировка -> 1:1 (`user_id#id`) | node fail | 4 != 3 строки, rc=1 |
| M4 убрать `chat_id` из запроса | node fail | «выбранный чат реально фильтрует запрос (S15-03)», rc=1 |
| restore | green | `MOD-ACL-UX-M4B-B1-FEEDS-OK`, rc=0 |

RED на базовых байтах: candidate-тест падает `actual 4 / expected 5`; тест действительно дискриминирует, а не тавтологичен.

## 8. Ограничения ревью (честно)

- Playwright и Browser Use - локальный стенд на candidate-байтах, синтетические API; это не живая TMA/Telegram и не production-данные.
- `MAC-S6-307`/`MAC-S15-03` live на выкаченных байтах остаются postdeploy; натуральный 503/пустой чат - RFL (брифинг §8 это разрешает).
- `ui_evol_w10_sections_e2e.py`/`ui_evol_w15_composition_e2e.py` не исполнялись: падение доказано статически (селектор отсутствует, проверка `<1`/`_rules_of` -> ValueError).
- Визуальный diff `ui_cmv_perf_parity.py` не запускался (N09).
- Ревью не меняло candidate/карту/статус; все temp-стенды остановлены, вкладки Browser Use закрыты. В рабочем дереве остаётся только этот review-файл плюс чужие w10-evidence (N07).

## 9. Что остаётся release/live

1. Исправить F01-F03 (тесты/инструменты + scope-guard), повторно прогнать затронутые наборы и e2e.
2. Deploy ровно `2.58.224` (после bump/assembly) на точный SHA; live-проверка S6-307 (5 лент, 3+2/2+2+1/1) и S15-03 (пустой/непустой чат) на deployed bytes; live 503/пустой чат - RFL.
3. MAC-S15-04 полностью - на B3; MAC-S0-11 - после B2 (последний вызов/воронка).
4. M6 (финальная live-приёмка TMA, 5 viewport, deploy/rollback) - после M4B+M4C; в B1 не заявлять VERIFIED.

## 10. Стабильность findings

- Это первое ревью B1; ранее открытых findings нет. Все три finding - новые, стабильные ID: `B1-R1-F01`, `B1-R1-F02`, `B1-R1-F03`.
- Исправление F01/F02 - test/tool-only; F03 - небольшой shared-state guard в `web/app.js` + тест. После правки повторно проверить только затронутые наборы, e2e и S15-03 repro.
