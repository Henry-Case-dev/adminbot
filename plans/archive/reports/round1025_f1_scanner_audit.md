# Scanner-аудит F1 `ia-shell-navigation-round1025` — 21.09.2026 (Step 6)

> Диапазон: `65e39fb..b1c87b0` (коммиты `1ebbd7b`, `ff34115`, `b1c87b0`). Ветка `master`, HEAD `b1c87b0` (SCANNER_F1_MARK).
> @Reviewer = Approved — проверял независимо, ревью не переиспользовал.
> Область: `services/param_catalog.py`, `web/app.js`, `web/index.html`, `web/static/app.css`,
> `web/static/telegram-init.js`, `web/api/routes.py`, тесты F1, `tools/ui_round1025_matrix.py`.

## Сводка

| Severity | Кол-во |
|---|---|
| Critical | **0** |
| High | **1** (H-1 — блокирует) |
| Medium | **2** |
| Low | **4** |

Вердикт: **к Шагу 7 — нет**, пока не закрыт H-1 (потери раздела на mobile для ограниченных ролей).

## Фактические цифры (замерено сейчас, не со слов отчёта)

| Гейт | Результат |
|---|---|
| `python -m pytest -q` (.venv) | **7996 passed / 0 failed**, 1 warning, 108.41 s |
| `node tests/js/*.js` (все 21 файла) | **21/21 PASS** |
| `node --check web/app.js` | exit 0 |
| `git diff 65e39fb..b1c87b0 --check` | exit 0 |
| `git status -s` | чисто; `stash@{0}` = `wip(f1): IA v2 round1025 …` — **цел** |
| Δ DDL / миграции | **0** (в диффе нет migrations, новых таблиц нет) |
| Δ каталога (services/) | только `param_catalog.py` NAV-метаданные: `REGISTRY 459 / GROUPS 98 / _TAB_BY_GROUP 96 / TAB_RULES 21` |
| zip в git / секреты | zip не трекается, `.env` не в индексе, новых секретов в диффе нет |
| F0/hotfix/Эпик 2 | F0-тесты и `tests/js/round1025_save_state_test.js` не изменены; Epic-2-контуры не тронуты |

## High

### [H-1] `web/app.js:1355-1378` (`bottomNavItems`/`mobileMoreItems`) — раздел недостижим на mobile
**Сценарий.** Признак «админского» bottom-nav вычисляется как
`canViewTab('modules') || canViewTab('llm_providers')` (`:1357`). Кнопка «Ещё» добавляется только
в этой ветке. Для роли, у которой есть право только на «Память» (`chat_lore`), только на «Доступы»
(`section.access`) или только на PERMsoc, признак = `false` → bottom-nav = `[Статус, Справка]`,
«Ещё» не рендерится, а разрешённый раздел лежит в `mobileMoreItems` (`how, memory/access/permsoc`) —
достать его из UI невозможно. В legacy-navbar тот же пользователь видел пункт «ИИ»/«Доступы»/«PERMsoc».
Воспроизвёл прямым прогоном computed (node):
```
access-only  | nav: status,how,access  | bottom: status,how | more: how,access
permsoc-only | nav: status,how,permsoc | bottom: status,how | more: how,permsoc
chat_lore    | nav: status,how,memory  | bottom: status,how | more: how,memory
```
На `/` карточек быстрого перехода на access/permsoc/memory нет (только `#/oversight`, `index.html:2664`)
— обходного пути в UI на <768 тоже нет. Deep-link по hash ещё работает (applyRoute не гейтит по nav),
но это не рядовой пользовательский путь.
**Фикс.** Строить bottom-nav от `navItems`, а не от двух tab-id: если публичных пунктов больше двух
или есть любой непубличный, добавлять «Ещё». Например:
```js
var extra = this.navItems.some(function (n) {
  return n.group !== 'public';   // memory/access/permsoc/modules/ai
});
if (!extra) return this.navItems.filter(...status/how...);
// иначе status + (modules/ai если видимы) + more
```
(В `NAV_ITEMS_V2` группа уже есть — использовать `group`, не перечислять id.)

## Medium

### [M-1] `web/app.js:3340-3349` (`_routeLabel`) + `:1401-1409` (`breadcrumb`) — сырой hash в хлебных крошках
`#/ai/persona` — валидный маршрут (`ROUTE_TO_TAB`), но `persona` отсутствует в `TABS`, а fallback
`_routeLabel` возвращает `String(route)`. Итог: на экране «Личность и стиль» breadcrumb показывает
`Статус / ИИ / #/ai/persona`. Замерено: `_routeLabel('#/ai/persona') === "#/ai/persona"`.
**Фикс.** Добавить подпись special-screen (`persona: 'Личность и стиль'`) или fallback на `title`
карточки хаба / humanize (`Доступы / #/ai/` → убрать `#/`). Тот же fallback применять к любому
будущему special-screen (регресс шире одной вкладки).

### [M-2] Kill-switch OFF не откатывает часть F1-UI
При `IA_V2_ENABLED=false` отключаются только навигация/шелл, но остаются: новый layout «Справки»
с оглавлением/поиском (`index.html:3089` — без `v-if="iaV2"`), mobile-редактор матрицы Доступов
(`index.html:1927`, CSS `.matrix-table` без scope `.ia-v2`), переименование «Сводка»→«Аналитика»
(`index.html:1353,2669`). По spec D5 (§6.4) OFF заявлен как nav-only, т.е. формально это осознанный
объём, но тогда «OFF = прежнее поведение» (критерий аудита/DoD 11) не выполняется буквально.
«Мёртвых» участков нет — всё кликабельно.
**Фикс.** Либо зафиксировать объём OFF одной строкой в ADR (layout/rename не откатываются), либо
обернуть эти блоки `v-if`/классом `.ia-v2`, если откат должен быть полным.

## Low

- **[L-1] `web/static/app.css:1352`** — `.bottom-nav-link` объявляет `min-width: 0` и сразу
  `min-width: 44px`; первый перезаписан. Для ellipsis-логики лейблов важнее `min-width: 0`
  (на 320px 4×44=176px влезает, но при длинных подписях вместо обрезки будет распирание).
  Фикс: убрать дубль, оставить `min-width: 44px; max-width: 100%`.
- **[L-2] `web/static/app.css:1388`** — `.more-sheet` позиционирован `bottom: 52px + safe-area`,
  а `.bottom-nav` (44px min-height + иконка 22px + лейбл + padding) фактически ≈46–56px; при
  safe-area>0 и крупном системном шрифте возможен наезд шторки на нижнюю панель на несколько px.
  Нужен замер (Playwright) или CSS-переменная высоты панели.
- **[L-3] Test-quality.** `tests/test_ia_shell_round1025.py:57-112` — grep-маркеры (есть ли строка
  `class="bottom-nav"`, `min-height: 44px`), не поведение; `tools/ui_round1025_matrix.py:79-80`
  поднимает только `global_admin` + `wildcard`, поэтому H-1 его прогоном не ловится. Поведенческие
  JS-тесты есть (`round1025_ia_routing_test.js`), но кейса ограниченных ролей в них нет. Фикс: кейс
  `bottomNavItems` для ролей `access-only`/`chat_lore-only` + опциональный прогон matrix с неполной ролью.
- **[L-4] `tests/fixtures/round1025/catalog_baseline.json`** — provenance post-change (зафиксировано
  в `_provenance`). Проверка «вкладка-владелец группы не менялась» опирается на снимок, снятый ПОСЛЕ
  правки, т.е. не является независимым оракулом; дрейф ловится только literal-счётчиками
  (459/98/96/21). По spec §8.4 допустимо, но для будущих «заморозок» baseline лучше снимать с pre-change ref.
- **[L-5] `web/index.html:45,54,3210,3218`** — `.sidebar-sep` рендерятся безусловно: у пользователя
  без админ/локальных прав остаются два «пустых» разделителя в sidebar/drawer. Фикс: `v-if="sidebarGroups.admin.length"`.

## Что чисто (проверено)

- **Роутинг/alias:** `#/ai/{memory,lore,relations}` → `#/memory{,,/lore,/relations}` (замерено через
  `applyRoute`); `#/memory/*` ↔ `TAB_TO_ROUTE` согласованы; при OFF `#/memory*` достижим (deep-link) и
  `activeNav` даёт `'ai'` (нет «мёртвого» пункта); мусорный `#/garbage` и пустой hash → `#/`;
  launch-hash TMA (`#tgWebAppData=…`) не переводится в `#/` (проверено по `normalizeRoute`/`initialRoute`);
  `ROUTE_PARENT` подстраниц памяти → `#/memory`, BackButton depth корректен.
- **Безопасность/XSS:** все новые шаблоны (breadcrumb/help-toc/names/me) используют `{{ }}`;
  `helpContent` работает на уже санитайзенном HTML, id-анкеры генерируются (`prefix-hN`), не из текста;
  новых `v-html` с серверными строками нет; нет inline-скриптов/`on*`-атрибутов; `telegram-init.js`
  пишет CSS-переменные через `style.setProperty` (CSP-safe).
- **Права:** «Статус»/«Справка» видны всем в обеих ветках; админ-пункты гейтятся `hubVisible`/
  `canViewTab`; PERMsoc остаётся локальным (`group:'local'`), не утёк в глобальные.
- **Адаптив:** shell-CSS использует `max(env(safe-area-inset-…), var(--tg-…))` — «только env()» в
  F1-зоне нет; `inert` ставится при закрытом drawer/sheet и снимается при открытом; touch-таргеты
  `.sidebar-link/.more-item/.bottom-nav-link` ≥44px; контент не уезжает под bottom-nav (padding с safe-area).
- **Kill-switch:** рубильник env-only `ClassVar`, наружу только `bool`; дефолт ON; legacy `NAV_ITEMS`/`HUBS`
  и `.navbar-band` сохранены литерально → OFF-набор пунктов 6/6 совпадает с прежним.
- **Инварианты:** Δ DDL=0, Δ каталога=0, F0/hotfix-тесты не тронуты, Эпик 2 не тронут, секретов/zip нет,
  `stash@{0}` цел, рабочий каталог чист.

## Замечание по методике
H-1 найден прогоном computed-функций на синтетических контекстах ролей (тот же приём, что в
`tests/js/round1025_ia_routing_test.js`). Рекомендую перенести оба кейса (H-1 и M-1) в JS-тесты F1,
чтобы регресс ловился автоматически.

---

## Повторный аудит после фикса `78e612a` (21.09.2026)

**Итог: Critical 0 / High 0.** Вердикт: **к Шагу 7 — да.**
Проверял независимо (отчёту не доверял) — диффом `b1c87b0..78e612a` и прогонами.

### Подтверждение H-1
`web/app.js:1355-1371` — «Ещё» строится от `navItems` по группе: `hasExtra = items.some(n => n.group !== 'public')`.
Проверил на ролях (замер computed):
```
access-only  bottom=[status,more]  more=[how,access]
permsoc-only bottom=[status,more]  more=[how,permsoc]
chat_lore    bottom=[status,more]  more=[how,memory]
no-rights    bottom=[status,how]   more=[how]        (как и требовалось)
admin        bottom=[status,modules,ai,more]  more=[how,memory,access,permsoc]
```
Шторка «Ещё» содержит нужный пункт → раздел достижим на <768 для всех трёх ролей. Пустой шторки не бывает
(`how` всегда публичен). Число пунктов bottom-nav ≤4.
**Тест действительно ловит регресс:** на старом `b1c87b0` тот же прогон даёт `bottom=["status","how"]` (без «more»),
на `78e612a` — `["status","more"]`. Новые кейсы в `tests/js/round1025_ia_routing_test.js` — поведенческие
(вызов computed с ролевыми лямбдами), не grep.

### Подтверждение M-1
`web/app.js:3339-3360` — `_routeLabel` ищет сначала nav-пункты, затем карточку хаба по `route`. Замер:
`#/ai/persona` → «Личность и стиль», `#/memory/rag` → «Память и RAG», `#/access/roles` → «Матрица ролей»,
`#/ai/llm` → «LLM Провайдеры». Breadcrumb `#/ai/persona` = `Статус / ИИ / Личность и стиль` (сырого hash нет).

### Подтверждение M-2
Объём OFF зафиксирован: ADR-1025-1 D5 и spec §6.4 — откат только навигации/шелла; layout «Справки»,
мобильный редактор «Доступов» и label «Аналитика» не откатываются (осознанный scope). «Мёртвых» состояний
в OFF не нашёл: `#/memory*`-deep-link работает, `activeNav` даёт `ai`.

### Low
L-1 закрыт (`app.css:1352` — убран дубль `min-width`); L-5 закрыт (`v-if="sidebarGroups.admin/local.length"`
для `.sidebar-sep` в sidebar и drawer). L-2 (offset `.more-sheet`), L-3 (ролевой прогон Playwright-матрицы),
L-4 (pre-change baseline) — помечены техдолгом в `tasks.md`; корректно, не блокеры.

### Фактические цифры повторного прогона
| Гейт | Результат |
|---|---|
| `python -m pytest -q` | **7996 passed / 0 failed** (112.26 s, 1 устаревший warning) |
| `node tests/js/*.js` | **21/21 PASS** |
| `node --check web/app.js` | exit 0 |
| `git diff --check` | exit 0 |
| `python tools/ui_round1025_matrix.py` | **0 нарушений** (10 вьюпортов; sidebar ≥1200, bottom-nav=4 <768, `scrollWidth==innerWidth`) |

### Инварианты
Δ DDL = 0 (миграций в диффе нет), Δ каталога = 0 (в `services/` только NAV-метаданные `param_catalog.py`;
пин-тесты 459/98/96/21 зелёные), F0-тесты и `round1025_save_state_test.js` не тронуты, Эпик 2 не тронут,
секретов в `78e612a` нет, zip/env в индексе нет, `stash@{0}` (F1-WIP) цел. Фикс-коммит меняет только F1-файлы
(`app.js`/`index.html`/`app.css`/JS-тест) + ADR/spec/tasks.

### Остаётся техдолгом (не блокирует Шаг 7)
L-2/L-3/L-4 из первого отчёта; Playwright-матрица по-прежнему гоняется только под `global_admin`.
