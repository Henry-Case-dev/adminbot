# FIX-SPEECH-MOBILE — «Речь и характер» реально доступна на мобильном

Дата: 2026-10-18. Режим: writer (web/** + tests/** + evidence), **без коммита** —
результат на независимое ревью (прецедент DROPDOWN-WG).

## 0. Что чиним (живой дефект владельца, 18.10)

> «Речь и характер» на мобильном ОТСУТСТВУЕТ — «её просто нет: ни в одном
> разделе, ни в модулях, ни в разделе ИИ».

Директива владельца §6.3 (`source-architectural-clarification.md:105`):
мобильный путь **«Ещё» → «ИИ»** правильный, навигацию не переделывать; надо
обеспечить реальную доступность полного списка редакторов и возможность
редактировать/сохранять на узком экране.

## 1. Воспроизведение (как у владельца)

Стенд: реальные `web/index.html` + `web/app.js` + `web/static/app.css`,
route-стабы `/api/*` (прецедент `tools/ui_asap8_w2_shell_e2e.py`),
Telegram SDK — route-mock; роль — глобальный админ; вьюпорт 320×640 / 390×844
(is_mobile + touch) и desktop 1280×900 (контроль).

Итог на дереве прода (2.58.88 == master, `app.js` sha == прод):

| шаг | 320 | 390 | 1280 |
|---|---|---|---|
| «Ещё» → «ИИ» → карточки хаба | 5 карточек, «Речь и характер» нет | то же | то же |
| `[data-speech-hub-entry]` | **НЕТ** | **НЕТ** | **НЕТ** |
| persona-таб `#/ai/persona` → `[data-speech-entry]` | есть | есть | есть |
| прямой `#/ai/speech` | открывается | открывается | открывается |

RED-лог: `red-entry-e2e.txt` / `red-entry-e2e.json` (3/3 FAIL: «НЕТ явного
входа [data-speech-hub-entry] на хабе „ИИ“»). DOM-выдержка:
`dom/hub_before_390.json` (`entryPresent: false`, первый ребёнок сетки —
`BUTTON.hub-card`, 5 карточек). Скриншоты: `before/entry_hub_390.png`,
`before/entry_hub_320.png`, реальный Chrome — `before/bu_hub_no_entry_390.png`.

**Вывод:** экран `#/ai/speech` и дверь внутри «Личность и стиль» живы; на
хабе «ИИ» — единственном месте, куда приводит мобильный путь «Ещё» → «ИИ» —
не было ни одной двери с именем «Речь и характер». Владелец, искавший раздел
по имени (на подписях-подсказках не строится), не мог его найти.

## 2. Root cause (файл:строка)

* `web/app.js:2921` (`hubCards`) — хаб «ИИ» рендерит только карточки
  `HUBS_V2['#/ai']` (5 страниц, F5-контракт); входа «Речь и характер» среди
  них нет по замыслу W6 («не шестая страница»).
* `web/index.html:10030` — единственная дверь (карточка `data-speech-entry`)
  живёт в шаблоне `activeTab === 'persona'` (внутри «Личность и стиль»).
* Мобильный путь Ещё → ИИ ведёт только на хаб `#/ai` (`web/app.js`
  `mobileMoreItems`), поэтому до persona-таба владелец не доходил.

(Номера строк — интегрированное дерево на момент отчёта; на чистом master
`hubCards` — 2872, `data-speech-entry` — 9930; семантика привязана к
маркерам, не к номерам.)

Сопутствующая находка (REFINE рядом с правкой): в `ICONS` (`web/app.js:366`)
нет глифа `record_voice_over` — у всех трёх «Речи и характера» (шапка экрана,
карточка в persona, прежняя задумка) значок рендерился пустым (span 0×0).
Проверено в живом DOM: `hub icon` до правки — `text:''`, `w:0`.

Проверены и **исключены** версии из брифа:
* (а) CSS-медиа-скрытие `.speech-entry`/`.speech-editor` — таких правил нет
  (`app.css` W6-блок: только min-height/размеры); вход виден на 320/390.
* (б) RBAC-фильтры `mobileMoreItems`/`hubCards` — для владельца
  (`5885953495` = legacy-роль `admin`, `web/app.js:3593`) «ИИ» и «Личность и
  стиль» видимы; `canViewTab('persona'/'speech')` — true.
* (в) мобильный `navItems` — тот же фильтр; пункт «ИИ» присутствует.
* (г) «экран речи пуст» — все 10 разделов открываются, витрина рисуется
  (см. §5, W6-deep e2e: failures=0).

## 3. Фикс (минимальный, навигация НЕ переделана)

`web/app.js` (+16) — computed `hubSpeechEntry`: хаб «ИИ» и право
`canViewTab('speech')` (существующие права: edit_persona / section.content /
локадмин; новых прав нет).

`web/index.html` (+15) — на хабе «ИИ», первой строкой сетки, явная
строка-вход `<button data-speech-hub-entry>` → существующий маршрут
`#/ai/speech`. Это НЕ шестая страница хаба: `HUBS_V2` не тронут (тесты
`test_soul1_w6_speech_ui.py` и `test_ia_inventory_round1025.py` зелёные,
`hub.count("route: '#/ai/") == 5`). Вход в persona-табе сохранён (вторая
дверь, не замена).

REFINE (в том же изменении): у всех трёх дверей/шапки «Речи и характера»
глиф `record_voice_over` → `edit_note` (присутствует в сабсете `ICONS`),
значок стал видимым (22×22 / 24×24 в живом DOM).

`web/static/app.css` (+34) — `.speech-hub-entry`: `grid-column: 1 / -1`,
`min-height: 56px`, акцентная рамка/подложка на существующих токенах.
Поверхность намеренно НЕ стеклянная (не входит в glass-селектор поверхностей),
стекло/линза/полигон/шапка не тронуты.

Поведение одинаково на всех ширинах (одна и та же дверь хаба; без
mobile-only форка), права — та же функция `canViewTab('speech')`, поэтому для
роли без прав ни входа, ни экрана.

## 4. Отпечаток кандидата

* База: `2bc13f44` (на момент правки; к моменту отчёта HEAD = `ecd03414`
  — это коммит CFG-02A, чужие изменения; мои 3 файла остались
  uncommitted поверх, diff vs HEAD = ровно мои хунки: +16/+15/+34).
* Изолированный кандидат (base + только мои правки):
  `OPENCODE_WORKFLOW_SCRATCH/speech-mobile/wt-clean` (worktree, 2bc13f44)
  и `…/web-fixed` (то же дерево без git).
  sha256_16: app.js `c24c6eb75151a796`, index.html `fcc7f7eadf421b52`,
  app.css `d6b848cdecd0a162`.
* Рабочее дерево (интегрированное, c CFG-02A):
  app.js `4078b1997aa2210f`, index.html `f79f9ad5845782c4`,
  app.css `d6b848cdecd0a162`; новые тесты:
  `tests/ui_speech_mobile_entry_e2e.py` `eccf7509c0a78109`,
  `tests/test_speech_mobile_entry_contract.py` `3e444435d9e7d2af`.
  (app.css рабочего дерева и копий-кандидатов байт-идентичен;
  хвостовые `git diff --check` — чисто.)
* ВНИМАНИЕ (интеграция): коммит CFG-02A `1908a657` на короткое время
  «смёл» мои правки `web/app.js|index.html`, затем CFG-02A переписал коммит
  (`ecd03414`) — сейчас мои правки в HEAD НЕ входят (проверено `git show
  HEAD:web/...`). Ревьюеру: смотреть uncommitted-дифф vs HEAD.

## 5. Проверки (candidate-bound)

| Проверка | Где | Результат |
|---|---|---|
| Новый entry-e2e (320/390/1280) | `tests/ui_speech_mobile_entry_e2e.py` | **RED 3/3** на базе (`red-entry-e2e.*`) → **GREEN 0/3** на кандидате (`green-entry-e2e.json`) и на интегрированном дереве (`green-entry-e2e-integrated.*`) |
| Контрактный pytest (6) | `tests/test_speech_mobile_entry_contract.py` | 6 passed (и в интегрированном дереве) |
| W6 speech-ui + IA inventory pytest | `test_soul1_w6_speech_ui.py`, `test_ia_inventory_round1025.py` | 35 passed (вместе с контрактными) |
| W6 deep e2e (8 вьюпортов + interactions) | `tools/ui_soul1_w6_speech_e2e.py` на wt-clean | **failures=0, POST=16, shots=94**; на интегрированном дереве 390+interactions — тоже 0/16 |
| node `tests/js` (87 файлов) | wt-clean | **87/87 OK** (`node-tests-js.txt`), рефракция — `JS-UNIT-OK glass-refraction` |
| W2-SHELL e2e | `tools/ui_asap8_w2_shell_e2e.py` на wt-clean | `failed_checks {}`, `W2-SHELL-E2E-OK` (`shell-e2e.txt`) |
| WG-REFRACT e2e | `tools/ui_win_glass_refraction_e2e.py` на wt-clean | **37/37 OK** — `WG-REFRACT-E2E-OK` (21+4+10+2), `refraction-e2e.txt` |
| Тиера A/B (дельта) | `tests/ui_soul1_glass_tiera_e2e.py verify` base vs кандидат | base **33 pass / 45 fail**, кандидат **33/45**, наборы FAIL **идентичны** (дельта 0; 45 fail — предсуществующий baseline headless-окружения) |
| Живой Chrome 390 | Browser Use (реальная отрисовка) | BEFORE `before/bu_hub_no_entry_390.png`; AFTER `after/bu_hub_entry_390.png`; DOM-факты: вход 374×133 в вьюпорте, 5 карточек хаба |

Скриншоты AFTER: `after/entry_hub_{320,390,1280}.png`,
`after/entry_speech_{320,390,1280}.png`, `after/entry_persona_*.png`,
`green/*` (интегрированное дерево). DOM-выдержки: `dom/hub_after_390.json`
(`entryPresent: true`, первый ребёнок — `BUTTON.speech-hub-entry`),
`dom/hub_before_390.json`, `dom/persona_entry_{before,after}_390.json`.

## 6. Воспроизведение прогонов

```
# RED (база = прод/master):
.venv/Scripts/python.exe tests/ui_speech_mobile_entry_e2e.py \
  --webroot OPENCODE_WORKFLOW_SCRATCH/speech-mobile/web-master
# GREEN (кандидат):
.venv/Scripts/python.exe tests/ui_speech_mobile_entry_e2e.py --shots <dir>
# W6 deep e2e (нужна СВЕЖАЯ фикстура):
.venv/Scripts/python.exe OPENCODE_WORKFLOW_SCRATCH/speech-mobile/dump_api_fixture_scratch.py
W6_WEBROOT=<webroot> W6_FIXTURE=…/w6-fixture-current.json \
  .venv/Scripts/python.exe OPENCODE_WORKFLOW_SCRATCH/speech-mobile/w6_e2e_scratch.py
```

## 7. Не трогал / границы

* Бэкенд, `HUBS_V2`, TABS/навигация, стекло/линза/полигон/шапка — не тронуты
  (grep-подтверждение: мой CSS-блок без `backdrop-filter`/`data-glass`/
  `#lg-lens`; контрактный тест это пинует).
* Деплой/коммит не делались (запрещено брифом).
* W6-фикстура `plans/features/soul-1/evidence/w6/api-fixture.json` устарела
  (до W4 `starter`/`telemetry`/`policy`): прогон `tools/ui_soul1_w6_speech_e2e.py`
  «из коробки» сейчас RED (Vue-render падает на «Примеры», пустой экран).
  При релизе 2.58.86 это уже документировалось (`release-soul-25886/
  w6-e2e-diagnosis.txt`) с решением не трогать W6-эвиденс; фикстуру здесь
  НЕ менял — прогоны на регенерированной копии (scratch). Кандидат в
  housekeeping (там же был пункт «W6-фикстуру»).
* `round1024_image_module_test.js` на интегрированном дереве RED из-за
  CFG-02A (`mod_images.sources` += `limits_images`) — не мой лейн; на
  изолированном кандидате все 87/87 зелёные.
