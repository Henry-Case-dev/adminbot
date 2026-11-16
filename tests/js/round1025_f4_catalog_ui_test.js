'use strict';
/* MOD-ACL-UX-01 M4A — структура каталога модулей (design §3.2/§4.1/§7.4).
 *
 * Обновление round1025_f4_catalog_ui_test.js по frozen design (не ослабление):
 *   (a) порядок страницы «Модули»: поиск+фильтры → каталог; H1 «Модули»
 *       НЕ дублируется в контенте (единственный носитель — topbar, §3.3);
 *       плиток-KPI нет — caption `21 модуль · N требуют внимания`;
 *   (b) поиск/фильтры §44: подписи `Все/Включены/Выключены/Требуют внимания`,
 *       пустота по причине (поиск vs фильтр), «Очистить поиск»;
 *   (c) сетка 4/3/2/1 (тиры 1150/900/520, minmax 280), потолок 1100 снят;
 *   (d) карусели/панели быстрого доступа нет;
 *   (e) карточка: клик по телу → workspace, контрол не навигирует
 *       (@click.stop); GLOBAL-тумблер в global scope и CHAT tri-state в чате
 *       (И-1); тач-цель ≥44×44; role=listitem; aria-label у контрола;
 *   (f) «Открыть» → openModuleWorkspace (openModuleWindow только fallback);
 *   (g) ОДИН каталог: нет JS-массива MODULES (DTO — единственный источник,
 *       И-3); карточки сгруппированы по moduleGroups; один write-вызов
 *       на область.
 *
 * Запуск: node tests/js/round1025_f4_catalog_ui_test.js
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');

// Ветка каталога (шаблон Vue) — от 'activeTab === modules' до её закрытия.
const branchStart = INDEX.indexOf("activeTab === 'modules'");
assert.ok(branchStart > 0, 'нет ветки Модулей');
const branchEnd = INDEX.indexOf("activeTab === 'oversight'", branchStart);
const MOD = INDEX.slice(branchStart, branchEnd);

// ── (a) Порядок страницы ────────────────────────────────────────────────
{
  const posToolbar = MOD.indexOf('data-module-toolbar');
  const posCatalog = MOD.indexOf('class="module-catalog');
  assert.ok(posToolbar >= 0, 'a: нет тулбара каталога');
  assert.ok(posCatalog >= 0, 'a: нет каталога');
  assert.ok(posToolbar < posCatalog, 'a: тулбар обязан идти до каталога');
  // design §3.3 п.1: H1 «Модули» в контенте не дублируется.
  assert.strictEqual(MOD.indexOf('hub-title">Модули'), -1,
    'a: H1 «Модули» в контенте не дублируется (носитель — topbar)');
  assert.strictEqual(MOD.indexOf('hub-sub'), -1,
    'a: вводная простыня удалена (контент начинается с поиска)');
  // KPI-плитки запрещены; число — в caption.
  assert.strictEqual(MOD.indexOf('module-counters'), -1,
    'a: KPI-строка модулей отсутствует');
  assert.strictEqual(MOD.indexOf('module-counter'), -1,
    'a: плитки KPI отсутствуют');
  assert.ok(MOD.indexOf('data-module-caption') >= 0 &&
            MOD.indexOf('moduleCatalogCaption') >= 0,
    'a: caption «21 модуль · N требуют внимания» — из DTO');
  assert.strictEqual(MOD.indexOf('module-quick-wrap'), -1,
    'a: панели быстрого доступа нет');
  assert.strictEqual(MOD.indexOf('Быстрое управление'), -1,
    'a: «Быстрое управление» отсутствует');
}

// ── (b) Поиск и фильтры §44/§7.4 ────────────────────────────────────────
{
  assert.ok(MOD.indexOf('placeholder="Найти модуль…"') >= 0, 'b: нет поиска');
  assert.ok(MOD.indexOf('v-model="moduleSearch"') >= 0, 'b: поиск не привязан');
  assert.ok(MOD.indexOf('moduleFilterOptions') >= 0, 'b: нет фильтров');
  assert.ok(MOD.indexOf('moduleFilter === f.id') >= 0, 'b: фильтр не активен');
  for (const label of ['Все', 'Включены', 'Выключены', 'Требуют внимания']) {
    assert.ok(APP_JS.indexOf("label: '" + label + "'") >= 0,
      'b: нет фильтра «' + label + '»');
  }
  assert.strictEqual(APP_JS.indexOf("label: 'Есть проблемы'"), -1,
    'b: жаргон «Есть проблемы» заменён на «Требуют внимания»');
  // Фильтр — представление, критерий — оси DTO.
  assert.ok(/if \(f === 'on'\) return self\.moduleDesired\(m\) === true;/
    .test(APP_JS), 'b: «Включены» по оси desired');
  assert.ok(/if \(f === 'off'\) return self\.moduleDesired\(m\) === false;/
    .test(APP_JS), 'b: «Выключены» по оси desired');
  assert.ok(/if \(f === 'issues'\) return self\.moduleNeedsAttention\(m\);/
    .test(APP_JS), 'b: «Требуют внимания» по доказанным осям');
  // Пустота различает поиск и фильтр (И-8).
  assert.ok(MOD.indexOf('moduleFilterEmptyText') >= 0,
    'b: пустота выбирает причину (поиск/фильтр)');
  assert.ok(APP_JS.indexOf('Ничего не найдено. Очистить поиск.') >= 0,
    'b: пустой поиск — «Очистить поиск»');
  assert.ok(MOD.indexOf('data-module-clear-search') >= 0 &&
            APP_JS.indexOf('clearModuleSearch: function') >= 0,
    'b: действие «Очистить поиск» есть');
  assert.ok(MOD.indexOf('v-for="m in g.items"') >= 0,
    'b: карточки рендерятся из moduleGroups');
  assert.ok(MOD.indexOf('v-for="g in moduleGroups"') >= 0,
    'b: группы каталога рендерятся (5 групп)');
}

// ── (c) Сетка 4/3/2/1 (design §4.1/§8) ──────────────────────────────────
{
  assert.ok(/\.module-catalog\s*\{[^}]*container-type:\s*inline-size/.test(CSS),
    'c: .module-catalog без container-type');
  assert.ok(/\.module-list \{[\s\S]{0,200}minmax\(min\(100%, 280px\), 1fr\)/
    .test(CSS), 'c: базовый трек 280px');
  assert.strictEqual(/\.module-catalog \.module-list \{[\s\S]{0,160}max-width: 1100px/
    .test(CSS), false, 'c: потолок 1100px каталога снят');
  for (const tier of ['1400', '1100', '700']) {
    assert.ok(CSS.indexOf('@media (min-width: ' + tier + 'px)') >= 0,
      'c: нет тира ' + tier);
  }
  assert.ok(/repeat\(4, minmax\(0, 1fr\)\)/.test(CSS) &&
            /repeat\(3, minmax\(0, 1fr\)\)/.test(CSS) &&
            /repeat\(2, minmax\(0, 1fr\)\)/.test(CSS),
    'c: тиры 4/3/2/1 объявлены');
  // базовый (top-level) triple-rule каталога по-прежнему существует
  assert.ok(/\.prov-grid,\s*\.module-list,\s*\.hub-grid\s*\{/.test(CSS),
    'c: сломан общий triple-rule (F1/F2 маркер)');
  // 1440/1280/768/390 — 4/3/2/1 обеспечивается тирами выше.
  assert.ok(/\.module-group-title \{[\s\S]{0,240}text-transform:\s*uppercase/
    .test(CSS), 'c: групповой заголовок 12px uppercase');
}

// ── (d) Быстрое управление/карусель удалены ─────────────────────────────
{
  assert.strictEqual(MOD.indexOf('module-quick-item'), -1,
    'd: карточка панели не должна присутствовать');
  assert.ok(CSS.indexOf('module-carousel') < 0, 'd: карусель запрещена');
  assert.ok(MOD.indexOf('module-carousel') < 0, 'd: карусель запрещена (html)');
}

// ── (e) Карточка: клик/контрол/тач-цель/a11y ───────────────────────────
{
  const m = CSS.match(/\.module-toggle\s*\{([^}]*)\}/);
  assert.ok(m, 'e: нет правила .module-toggle');
  assert.ok(/min-width:\s*44px/.test(m[1]), 'e: тач-цель min-width < 44');
  assert.ok(/min-height:\s*44px/.test(m[1]), 'e: тач-цель min-height < 44');
  // Клик по телу открывает workspace; контрол не навигирует.
  assert.ok(/class="module-card-body" @click="openModuleWorkspace\(m\)"/
    .test(MOD), 'e: клик по телу карточки открывает workspace');
  const controlRow = MOD.match(/<div class="module-control-row"[^>]*>/);
  assert.ok(controlRow, 'e: нет строки управления');
  assert.ok(/@click\.stop/.test(controlRow[0]),
    'e: контрол карточки не навигирует (@click.stop)');
  assert.ok(MOD.indexOf('role="listitem"') >= 0, 'e: нет роли listitem');
  assert.ok(MOD.indexOf('role="list"') >= 0, 'e: нет роли list');
  // И-1: GLOBAL-тумблер в global scope, CHAT tri-state в чате.
  assert.strictEqual((MOD.match(/data-module-global-toggle/g) || []).length, 1,
    'e: GLOBAL-тумблер ровно один');
  assert.ok(MOD.indexOf(':data-module-chat-tristate="opt.id"') >= 0,
    'e: CHAT tri-state (Наследовать/Включить/Выключить)');
  assert.ok(APP_JS.indexOf("id: 'inherit', label: 'Наследовать'") >= 0,
    'e: подписи tri-state — человеческие');
  assert.strictEqual((MOD.match(/:aria-label="moduleGlobalToggleAria\(m\)"/g)
    || []).length, 1,
    'e: aria-label GLOBAL-тумблера (область+значение+название)');
  assert.strictEqual((MOD.match(/:aria-label="moduleChatLabel\(m\)"/g) || [])
    .length, 1,
    'e: aria-label CHAT-группы — глагольная подпись');
  assert.ok(MOD.indexOf('data-module-state') >= 0,
    'e: одна строка статуса карточки');
  assert.ok(INDEX.indexOf('data-workspace-chips') >= 0 &&
            APP_JS.indexOf('moduleStateChips: function') >= 0,
    'e: чипы осей на странице модуля (вне ветки каталога)');
}

// ── (f) «Открыть» → openModuleWorkspace (шов F5, §D6) ───────────────────
{
  assert.ok(MOD.indexOf('data-module-open') >= 0, 'f: нет кнопки входа');
  assert.ok(MOD.indexOf('>Открыть</button>') >= 0, 'f: кнопка не «Открыть»');
  assert.ok(MOD.indexOf('openModuleWorkspace(m)') >= 0,
    'f: кнопка не вызывает openModuleWorkspace');
  assert.ok(MOD.indexOf('openModuleWindow(m)') < 0,
    'f: прямой вызов openModuleWindow в шаблоне запрещён');
  assert.ok(APP_JS.indexOf('openModuleWorkspace: function (m)') >= 0,
    'f: нет шва openModuleWorkspace');
  assert.ok(APP_JS.indexOf('return this.openModuleWindow(m)') >= 0,
    'f: fallback в модалку сохранён');
  assert.ok(MOD.indexOf('module-params-btn') >= 0,
    'f: класс module-params-btn (аудит) потерян');
}

// ── (g) Один каталог (DTO), один write-вызов на область ─────────────────
{
  assert.strictEqual((INDEX.match(/class="module-catalog col-span-full"/g) || [])
    .length, 1, 'g: должен быть ровно один .module-catalog');
  // И-3: JS-копии каталога нет — ни массива, ни статического литерала.
  assert.strictEqual(APP_JS.indexOf('var MODULES = ['), -1,
    'g: JS-массив MODULES удалён (единственный источник — DTO)');
  assert.ok(APP_JS.indexOf('var WS_MODULES = [];') >= 0,
    'g: рантайм-кэш DTO (WS_MODULES), не каталог');
  assert.ok(/f3ApplyModuleRegistry: function \(modules\)/.test(APP_JS),
    'g: применить DTO — f3ApplyModuleRegistry');
  assert.ok(APP_JS.indexOf('catalogGroup: spec.catalog_group') >= 0 &&
            APP_JS.indexOf('catalogOrder: spec.catalog_order') >= 0,
    'g: группа/порядок карточки берутся из DTO');
  // Одна мутация на область: global → setModuleGlobalState,
  // chat → setModuleChatTriState; смешения нет.
  assert.strictEqual((MOD.match(/setModuleGlobalState\(/g) || []).length, 1,
    'g: ровно один GLOBAL write-вызов в шаблоне');
  assert.strictEqual((MOD.match(/setModuleChatTriState\(/g) || []).length, 1,
    'g: ровно один CHAT write-вызов в шаблоне');
  assert.strictEqual(MOD.indexOf('setModuleScopeState('), -1,
    'g: старый «единый» scope-тумблер из карточки удалён (И-1)');
}

// ── (h) M4A: 409/оси/права в шаблонах (И-2/И-5) ─────────────────────────
{
  assert.ok(APP_JS.indexOf("'Настройка изменилась в другом окне'") >= 0,
    'h: 409-баннер с человеческой причиной');
  assert.ok(APP_JS.indexOf('stickyConflict') >= 0,
    'h: 409 → stickyConflict (без автоповтора)');
  assert.ok(APP_JS.indexOf("moduleChatError[key] = 'Не удалось сохранить: ' + reason")
    >= 0, 'h: ошибка сохранения — с причиной');
  assert.ok(APP_JS.indexOf('Состояние неизвестно') >= 0,
    'h: unknown ≠ OFF (строка состояния)');
  assert.ok(INDEX.indexOf('Сохраняем…') >= 0, 'h: «Сохраняем…» до ответа');
  assert.ok(APP_JS.indexOf("'Настройка сохранена'") >= 0,
    'h: успех — только после ответа');
}

console.log('MODULE-CATALOG-OK');
