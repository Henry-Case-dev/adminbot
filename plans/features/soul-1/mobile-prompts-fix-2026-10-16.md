# SOUL-1 · lane B-MOBILE — мобильная библиотека промптов (финиш, попытка 3)

Дата: 2026-10-16. Режим: writer (верификация + открытый вопрос №2) без деплоя и коммитов.
Кандидат (git hash-object): `services/param_catalog.py`=ea5d5ddf260440b752b2c35b0fde5afbe75ec636,
`web/app.js`=cb116fdb927a66a341c6e98060f94e134d2a3290,
`web/index.html`=a984dbe2e7868c53d715ac7a36faec84aa9e6be9.
Диф предыдущей попытки принят как есть (не переписывался); вся верификация — на этом дереве.

## 1. Sanity (каталог + сборка `/api/config` + boot)

1. `services/param_catalog.py` импортируется; `prompts.direct_l1_planner_system_prompt`:
   group=`prompts_direct_chat`, stage=`synthesizer`, code_source=`services.chat_prompts.DIRECT_L1_PLANNER_SYSTEM_PROMPT`
   (канон 2423 симв.), `prompt_migrations.PROMPT_MIGRATIONS` знает ключ.
2. Реальная сборка роута (реплика фикстуры `tests/test_webapp_api.py::client`, реальный
   `web.app.create_app` + `ConfigCache` + `web/api/routes.py::get_config`):
   `_r3_config_assembly_probe.py` → 200, 24 ключа `prompts.*`, L1-ключ с верными
   метаданными и значением-каноном (`value_len=2423`), 9 групп категории prompts.
3. Проектные тесты: `pytest tests/test_webapp_api.py -k "config or me_"` → 54 passed;
   `pytest tests/test_prompts_round1024.py` → 21 passed; `node --check web/app.js` → OK.
4. Инвариант «читатель↔каталог»: каждый литеральный `resolve_prompt("prompts.*")` в `services/`
   имеет запись в каталоге (до правки L1-ключа не было — гэп закрыт).
5. Frontend boot: e2e на реальном `web/index.html` в 320/390/430/1024 — `page_errors=[]`,
   `scrollWidth==innerWidth` (горизонтального оверфлоу нет).

## 2. Открытый вопрос №2 — режимы Вербализатора под `PROMPTS_UI_V2_ENABLED` (=ON)

Вердикт: **достижимы и редактируемы, код не меняем** (флаг не выключался, табы не перестраивались).
- `web/index.html:2305-2308` пропускает только ОТДЕЛЬНУЮ карточку группы `prompts_verbilizer`
  (намеренно; ADR-1024-10 D4). Это не потеря доступности.
- Пути под V2:
  - таб-блоки режимов ВНУТРИ карточек модулей, секция «Вербализатор (Характер)»:
    `web/index.html:2365-2386` + `web/app.js:14732-14736` (`promptModeItem()` берёт те же
    элементы `configItems`, что и generic-карточка) → запись через sticky-save
    (`dirtyItems` `web/app.js:5110-5122` → `saveModalEdits` `:9307-9379`);
  - шапочный fallback-дропдаун `prompts.verbilizer_default_mode`: `web/index.html:2270-2291` +
    автосейв `web/app.js:14770-14779`.
- Реальный прогон: 6/6 видимых mode-блоков на каждом вьюпорте; ввод в Casual → sticky «Сохранить
  изменения» → POST → reload → значение пережило (все 4 вьюпорта, уникальные маркеры); смена
  fallback-селекта → автосейв → пережила reopen. Скриншоты: `_r3_sticky-mode-*.png`,
  `_r3_mode-reopen-*.png`, `_r3_fallback-reopen-*.png`, `_r3_bu-390-mode-tabs.png`.

## 3. Реальная цепочка «Ещё → ИИ → Промпты» (настоящий index.html + payload из каталога + store)

Прогон `_r3_mobile_prompts_e2e.py` (4 вьюпорта): на вкладке 25 элементов = 24 `prompts.*` +
`limits.anticliche_max_patterns`; `currentTabGroups`=10; все ключи имеют место рендера (`missing=[]`).

| вьюпорт | items | keys | missing | overflowX | L1: ввод→Save→POST→reopen | режим Casual | fallback | library direct/synth/verb |
|---|---|---|---|---|---|---|---|---|
| 320 | 25 | 24 | 0 | нет | ✓ маркер сохранён и виден | ✓ | ✓ | ✓ / ✓ / ✓ |
| 390 | 25 | 24 | 0 | нет | ✓ | ✓ | ✓ | ✓ / ✓ / ✓ |
| 430 | 25 | 24 | 0 | нет | ✓ | ✓ | ✓ | ✓ / ✓ / ✓ |
| 1024 | 25 | 24 | 0 | нет | ✓ | ✓ | ✓ | ✓ / ✓ / ✓ |

- L1 Planner: присутствует в карточке «Синтезатор (Логика)» модуля «Прямой чат», редактируется,
  значение переживает reopen; вторая дверь `#/ai/prompts/direct` и `/direct/synthesizer` содержит
  `prompts.direct_l1_planner_system_prompt` в дереве; `#/ai/prompts/direct/verbalizer` содержит
  ключ Вербализатора. `page_errors=[]` везде.
- RED (payload без записи каталога): 23 ключа / 24 items на всех вьюпортах — «ключ отсутствует
  в /api/config» воспроизведено (`_r3_result-red.json`); GREEN: `MOBILE PROMPTS E2E (_r3_): OK`.
- Payload до/после: `_r3r_config-payload-red.json` (23 prompt-ключа) vs
  `_r3_config-payload-after.json` (24).
- Пустые состояния (320, реальные состояния): restricted-роль → честный текст про права/область
  (`_r3_empty-state-320.png`); поиск «zzzz» → «Ничего не найдено по запросу «zzzz».»
  (`_r3_empty-state-search-320.png`).

## 4. Таблица видимости `prompts.*` (admin, V2; 320/390/430/1024 одинаково)

Машиночитаемо: `_r3_visibility-table.json` (в API 24 ключа; `prompts.summary_cover_style_id`
исключён каталогом как `hidden=True` — и до правки). `save persists`=✓ только там, где реально
прогнан ввод+Save+reopen; «общий путь» = та же sticky-save/persistItems-цепочка, но поштучно не
упражнялась.

```
ключ                                            рендер@320     editable  save persists
prompts.checkup_system_prompt                   item_card      True      общий путь
prompts.compress_system_prompt                  item_card      True      общий путь
prompts.direct_chat_synthesizer_system_prompt   item_card      True      общий путь
prompts.direct_chat_system_prompt               item_card      True      общий путь
prompts.direct_chat_verbalizer_system_prompt    item_card      True      общий путь
prompts.direct_l1_planner_system_prompt (НОВЫЙ) item_card      True      ✓ (4 вьюпорта)
prompts.extract_system_prompt                   item_card      True      общий путь
prompts.factcheck_analyst_system_prompt         item_card      True      общий путь
prompts.factcheck_system_prompt                 item_card      True      общий путь
prompts.factcheck_verbalizer_system_prompt      item_card      True      общий путь
prompts.search_system_prompt                    item_card      True      общий путь
prompts.summary_cover_style                     item_card      True      общий путь
prompts.summary_editor_system_prompt            item_card      True      общий путь
prompts.summary_l1_clusterizer_system_prompt    item_card      True      общий путь
prompts.summary_l2_writer_system_prompt         item_card      True      общий путь
prompts.summary_narrator_system_prompt          item_card      True      общий путь
prompts.summary_system_prompt                   item_card      True      общий путь
prompts.verbilizer_default_mode                 fallback_select True     ✓ (4 вьюпорта)
prompts.verbilizer_mode_casual                  mode_tabs      True      ✓ (4 вьюпорта)
prompts.verbilizer_mode_deep_research           mode_tabs      True      общий путь
prompts.verbilizer_mode_serious                 mode_tabs      True      общий путь
prompts.webpage_system_prompt                   item_card      True      общий путь
prompts.youtube_system_prompt                   item_card      True      общий путь
prompts.youtube_video_system_prompt             item_card      True      общий путь
итог: item_card=20, mode_tabs=3, fallback_select=1, MISSING=0
```

Группы: 8/9 групп prompts рендерятся карточками (title в DOM) на каждом вьюпорте;
`prompts_verbilizer` под V2 карточкой не рендерится — **намеренно**, её 4 ключа доступны путями
из §2 (функционально проверено). Соседняя группа вкладки `limits_anticliche` проверена точечно
(320): карточка `data-block="anticliche-monitor"` видима, ключ `limits.anticliche_max_patterns`
редактируем (`_r3_anticliche-probe.json`).

## 5. Browser Use — реальный рендер (390×844)

`_r3_bu-390-l1-card.png` — карточка «L1 Planner: план ответа» с описанием и живым textarea канона,
сразу под ней «ВЕРБАЛИЗАТОР (ХАРАКТЕР)» с табами Casual/Serious/Deep Research; ширина 390=390, без
обрезки. `_r3_bu-390-search-empty.png` — честный текст пустого поиска. `_r3_bu-390-mode-tabs.png` —
таб-блоки режимов. Playwright-скриншоты всех шагов — `_r3_chain/l1-*/mode-*/fallback-*/library-*`.

## 6. Что осталось открытым (честно)

- Persist реально прогнан для 3 из 24 ключей (L1, casual, default). Остальные 21 идут тем же
  общим путём записи (sticky-save → `persistItems`), но поштучно не прогонялись.
- Чат-скоуп (X-Chat-Id) редакции промптов этим прогоном не покрыт: проверен только текст
  пустого состояния для области «чат» (restricted-payload). Не в объёме этой правки.
- Бейдж «скрыт» на карточках в тестовом payload — артефакт стаба (`view_roles=[]`), не поведение
  продукта (в проде роут отдаёт реальные матрицы).
- `plans/features/soul-1/evidence/mobile-prompts/` содержит файлы попыток 1-2 (без `_r3_`) —
  устаревшие, не использовались как доказательство; актуальные — `_r3_*`.
- Деплой/commit не выполнялись (запрещено брифом).

## 7. Изменения кода (из диффа попытки 1-2; в этом прогоне ничего не менялось)

- `services/param_catalog.py:645-662` (+18) — запись каталога L1 Planner.
- `web/app.js:3361-3386` (+26) — `emptyTabReason()`.
- `web/index.html` (+23/-4, две правки): `+2193-2203`, `+2206-2213` — честные пустые состояния.
- Правок по вопросу №2 НЕ вносилось (достижимость подтверждена кодом и прогоном).

## Fix F1 (review-ui-fixes.md, блокирующая находка) — 2026-10-16

Правка только внутри `web/app.js::emptyTabReason()`; карточка `[data-empty-tab]` рендерится
исключительно при `currentTabItemCount === 0`, а `tabItemCount()` (app.js:15223) считает элементы
БЕЗ поиска → запрос структурно не может быть причиной пустоты. **Удалено** (было ложью во всех
состояниях рендера): `if (q) { return 'Ничего не найдено по запросу «' + q + '» — параметры вкладки
доступны, но не подходят под запрос.'; }`. **Теперь** причина всегда выводима из состояния:
`var why = (scopeKind !== 'global') ? 'Для выбранной области (ЛС/чат) …Переключите область на
«Весь бот».' : 'На этой вкладке нет параметров, доступных вашей роли (сервер отфильтровал их по
правам).'`, и лишь при непустом `configSearch` добавляется честная оговорка «Запрос «q» здесь
ничего не изменит: фильтровать в пустой вкладке нечего.». Ветка «сервер не отдал ни одного
значения» не менялась; сестринская карточка `web/index.html` не трогалась.

- Контрпример (RED, реальный payload = только `category=prompts`, вкладка `smart_cache`,
  запрос `zzzqqq`, 320 и 390): `_f1_result-red.json` — 8 падений, текст карточки
  «Ничего не найдено по запросу «zzzqqq» — параметры вкладки доступны, но не подходят под запрос.»
  (`_f1r_b-empty-with-query-390.png`); GREEN: `_f1_result.json` — 30/30, `_f1_run.txt`.
- Живые случаи (Playwright, реальные `web/**` + payload из `REGISTRY`, 320/390):
  a1) пустая вкладка без запроса → «На этой вкладке нет параметров, доступных вашей роли…»
  (`_f1_ab-empty-noglobal-*.png`); b) она же + запрос: `…доступных вашей роли (сервер отфильтровал
  их по правам). Запрос «zzzqqq» здесь ничего не изменит: фильтровать в пустой вкладке нечего.`
  (`_f1_b-empty-with-query-*.png`); a2) тот же запрос + реальная смена области
  (`setActiveChat('-1')`, путь дропдауна) → scope-текст «Для выбранной области (чат)…»
  (`_f1_a2-empty-chat-scope-*.png`); c) вкладка «Промпты» (25 элементов) + запрос → сестринская
  карточка `[data-empty-search]` «Ничего не найдено по запросу «zzzqqq».», `[data-empty-tab]`
  отсутствует; очистка поиска возвращает группы (`_f1_c-search-nomatch-*.png`, `_f1_result.json`);
  d) библиотека Direct 320/390: DOM-ключи дерева == `workspacePromptList`, L1 Planner на месте
  (`_f1_d-library-direct-*.png`, `_f1_d-library-ai-*.png`), оверфлоу нет.
- Второй браузер (Playwright MCP, 390): те же тексты и состояния; скриншоты
  `_f1_mcp-a1-*`, `_f1_mcp-b-*`, `_f1_mcp-c-*`, `_f1_mcp-d-library-direct-390.png`.
- Реальный Chrome (Browser Use, 390, TMA-контекст через `sessionStorage.adminbot.initData`):
  состояние (b) и (d) осмотрены визуально — карточка с честным текстом и оговоркой про запрос;
  дерево «ПРОМПТЫ» содержит «L1 Planner: план ответа». Сохранение PNG через CDP
  `Page.captureScreenshot` дважды упёрлось в таймаут демона, поэтому файлов `_f1_bu_*` нет —
  визуальный осмотр был живым (текст подтверждён `js()`-чтением).
- Точность к записи ревьюера: `setTab` очищает `configSearch` (app.js:14183), поэтому ложное
  состояние достигалось не «переносом поиска между вкладками», а вводом запроса уже на пустой
  вкладке либо реальной сменой области (`setActiveChat` поиск не чистит). Само состояние
  достижимо без devtools — контрпример не аннулируется.
- Тесты: `node --check web/app.js` → OK; `pytest tests/test_webapp_round107_ui.py
  tests/test_webapp_round1010_ui.py -q` → `32 passed in 3.24s`.
- Отпечаток после правки: `web/app.js` sha256 `9774DA6A4E932287123CC49F8C84337A77F2BDEF63385B3E76A9D47D5F9CB8AC`
  (до правки — 5F8FEFF6…EF92 из review-ui-fixes.md); правок вне `emptyTabReason` нет.
