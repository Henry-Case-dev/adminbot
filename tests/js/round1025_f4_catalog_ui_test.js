'use strict';
/* F4 round1025 — структура каталога/панели (§32–§35, ADR-1025-14 D6/D7):
 *   (a) порядок страницы «Модули»: заголовок+счётчики → панель избранного →
 *       поиск+фильтры → основной каталог;
 *   (b) сетка каталога ≤3/2/1 (изолированные правила .module-catalog),
 *       панель ≤4/2/2–1 (CSS Grid + minmax + container queries);
 *   (c) тач-цель тумблера ≥44×44 CSS px;
 *   (d) «карточка ≠ тумблер» (клик по телу не переключает);
 *   (e) «Настроить» → openModuleWorkspace → openModuleWindow (§D6);
 *   (f) нет карусели и второго каталога.
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
  const posHead = MOD.indexOf('hub-title">Модули');
  const posToolbar = MOD.indexOf('module-toolbar');
  const posCatalog = MOD.indexOf('module-catalog');
  // ASAP 4.2 (D5.3): панель «Быстрое управление» удалена полностью —
  // единственный список модулей — каталог.
  // L-F11S-1 (EVOL-027 v0.8, W10): тяжёлая агрегатная KPI-строка
  // («всего/включено/выключено/проблемы») удалена из каталога
  // (plans/current_task.md L389); число результатов живёт в подписи списка.
  for (const [name, pos] of [['заголовок', posHead],
    ['поиск/фильтры', posToolbar], ['каталог', posCatalog]]) {
    assert.ok(pos >= 0, 'a: нет блока «' + name + '»');
  }
  assert.ok(posHead < posToolbar && posToolbar < posCatalog,
    'a: порядок блоков §32 нарушен');
  assert.strictEqual(MOD.indexOf('module-counters'), -1,
    'a: KPI-строка модулей должна отсутствовать (EVOL-027 v0.8)');
  assert.strictEqual(MOD.indexOf('module-counter'), -1,
    'a: плитки KPI модулей должны отсутствовать');
  assert.ok(MOD.indexOf('data-module-caption') >= 0,
    'a: нет подписи числа результатов в списке');
  assert.strictEqual(MOD.indexOf('module-quick-wrap'), -1,
    'a: Quick Access панель должна быть удалена');
  assert.strictEqual(MOD.indexOf('Быстрое управление'), -1,
    'a: «Быстрое управление» отсутствует');
  // §5 v2.1 (решение владельца 26905a89): РОВНО ОДИН переключатель в
  // карточке; его область берётся из верхнего селектора GLOBAL/чат
  // (`data-module-scope`), второго (global+chat) тумблера нет.
  const scopeToggles = (MOD.match(/data-module-scope-toggle/g) || []).length;
  assert.strictEqual(scopeToggles, 1,
    'a: в карточке РОВНО один тумблер модуля (data-module-scope-toggle)');
  assert.strictEqual(MOD.indexOf('data-module-global-toggle'), -1,
    'a: отдельного «глобального» тумблера в карточке нет');
  assert.ok(/:data-module-scope="moduleScopeIsGlobal\(\) \? 'global' : 'chat'"/.test(MOD),
    'a: область тумблера — из верхнего селектора (global/chat)');
  assert.ok(MOD.indexOf('setModuleScopeState(m, $event.target.checked)') >= 0,
    'a: тумблер вызывает серверную операцию сразу (в своей области)');
  // Наследование — компактное ДЕЙСТВИЕ, не второй тумблер.
  assert.strictEqual((MOD.match(/data-module-override-reset/g) || []).length, 1,
    'a: возврат к наследованию — одно действие (data-module-override-reset)');
  assert.ok(MOD.indexOf('Наследовать глобальное') >= 0,
    'a: подпись действия наследования');
  assert.ok(MOD.indexOf('data-module-scope-readonly') >= 0,
    'a: честный read-only статус вместо фиктивного второго тумблера');
}

// ── (b) Поиск и фильтры §44/§32 ─────────────────────────────────────────
{
  assert.ok(MOD.indexOf('placeholder="Найти модуль…"') >= 0, 'b: нет поля поиска');
  assert.ok(MOD.indexOf('v-model="moduleSearch"') >= 0, 'b: поиск не привязан');
  assert.ok(MOD.indexOf('moduleFilterOptions') >= 0, 'b: нет фильтров');
  assert.ok(MOD.indexOf('moduleFilter === f.id') >= 0, 'b: фильтр не активен');
  for (const label of ['Все', 'Включённые', 'Выключенные',
    'Есть проблемы']) {
    assert.ok(APP_JS.indexOf("label: '" + label + "'") >= 0,
      'b: нет фильтра «' + label + '»');
  }
  // §7 (v2.1): концепция избранного/закрепления удалена полностью — фильтра
  // «Избранные» в списке опций нет (и «Закреплено» его не заменяет).
  assert.strictEqual(APP_JS.indexOf("label: 'Избранные'"), -1,
    'b: фильтра «Избранные» нет (избранное удалено)');
  assert.strictEqual(APP_JS.indexOf("label: 'Закреплено'"), -1,
    'b: «Закреплено» не подменяет избранное');
  assert.ok(MOD.indexOf('v-for="m in filteredModules"') >= 0,
    'b: каталог не использует filteredModules');
  assert.ok(MOD.indexOf('Ничего не найдено') >= 0, 'b: нет empty-state');
}

// ── (c) Каталог ≤3/2/1 (изолированные правила) ──────────────────────────
{
  assert.ok(/\.module-catalog\s*\{[^}]*container-type:\s*inline-size/.test(CSS),
    'c: .module-catalog без container-type');
  assert.ok(/@container\s*\(max-width:\s*1023px\)\s*\{[^}]*\.module-catalog \.module-list\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/.test(CSS),
    'c: нет тира 2 колонки');
  assert.ok(/@container\s*\(max-width:\s*479px\)\s*\{[^}]*\.module-catalog \.module-list\s*\{[^}]*minmax\(0,\s*1fr\)/.test(CSS),
    'c: нет тира 1 колонка');
  // базовый (top-level) triple-rule каталога по-прежнему существует
  assert.ok(/\.prov-grid,\s*\.module-list,\s*\.hub-grid\s*\{/.test(CSS),
    'c: сломан общий triple-rule (F1/F2 маркер)');
}

// ── (d) Быстрое управление удалено (ASAP 4.2 D5.3) ──────────────────────
{
  // DOM-панели нет; карусели тоже нет (инвариант сохранён).
  assert.strictEqual(MOD.indexOf('module-quick-wrap'), -1,
    'd: панель быстрого управления не должна присутствовать');
  assert.strictEqual(MOD.indexOf('quickpickVisible'), -1,
    'd: элементы панели не должны присутствовать');
  assert.strictEqual(MOD.indexOf('module-quick-item'), -1,
    'd: карточка панели не должна присутствовать');
  assert.ok(MOD.indexOf('filteredModules') >= 0,
    'd: модули по-прежнему рендерятся каталогом');
  // карусели нет
  assert.ok(CSS.indexOf('module-carousel') < 0, 'd: карусель запрещена');
  assert.ok(MOD.indexOf('module-carousel') < 0, 'd: карусель запрещена (html)');
}

// ── (e) Тач-цель ≥44×44 + «карточка ≠ тумблер» ──────────────────────────
{
  const m = CSS.match(/\.module-toggle\s*\{([^}]*)\}/);
  assert.ok(m, 'e: нет правила .module-toggle');
  assert.ok(/min-width:\s*44px/.test(m[1]), 'e: тач-цель min-width < 44');
  assert.ok(/min-height:\s*44px/.test(m[1]), 'e: тач-цель min-height < 44');
  // карточка не имеет обработчика клика-переключения
  const cardTag = MOD.match(/<article class="module-card[^>]*>/);
  assert.ok(cardTag, 'e: нет карточки модуля');
  assert.ok(cardTag[0].indexOf('@click') < 0, 'e: карточка работает как тумблер');
  assert.ok(MOD.indexOf('role="listitem"') >= 0, 'e: нет роли listitem');
  // aria-label на ЕДИНСТВЕННОМ тумблере: область (Глобально/В этом чате) +
  // значение + название модуля — один подписанный контрол (§5 v2.1).
  assert.strictEqual((MOD.match(/:aria-label="moduleScopeToggleAria\(m\)"/g)
    || []).length, 1,
    'e: у единственного тумблера один aria-label (moduleScopeToggleAria)');
  assert.ok(/moduleScopeToggleAria: function[\s\S]{0,600}'Глобально'[\s\S]{0,300}'В этом чате'/.test(
    APP_JS.replace(/\n/g, ' ')),
    'e: aria-label различает область (Глобально / В этом чате)');
  assert.strictEqual(MOD.indexOf('moduleGlobalToggleLabel'), -1,
    'e: подписи отдельного «глобального» тумблера больше нет');
  assert.ok(MOD.indexOf('module-card-head') >= 0, 'e: нет верхней строки карточки');
  assert.ok(MOD.indexOf('module-state') >= 0, 'e: нет фактического состояния');
}

// ── (f) «Настроить» → openModuleWorkspace (шов F5, §D6) ─────────────────
{
  assert.ok(MOD.indexOf('openModuleWorkspace(m)') >= 0,
    'f: кнопка не вызывает openModuleWorkspace');
  assert.ok(MOD.indexOf('>Настроить</button>') >= 0, 'f: кнопка не «Настроить»');
  assert.ok(MOD.indexOf('openModuleWindow(m)') < 0,
    'f: новый маршрут/прямой вызов openModuleWindow в шаблоне запрещён');
  assert.ok(APP_JS.indexOf('openModuleWorkspace: function (m)') >= 0,
    'f: нет шва openModuleWorkspace');
  assert.ok(APP_JS.indexOf('openModuleWindow: function (m)') >= 0,
    'f: регресс-путь openModuleWindow потерян');
  assert.ok(APP_JS.indexOf('return this.openModuleWindow(m)') >= 0,
    'f: шов не делегирует в модалку');
  assert.ok(MOD.indexOf('module-params-btn') >= 0,
    'f: класс module-params-btn (аудит) потерян');
}

// ── (g) Один каталог, один store для трёх представлений ─────────────────
{
  const listCount = (INDEX.match(/class="module-list\b/g) || []).length;
  assert.strictEqual(listCount, 1, 'g: должен быть ровно один .module-list');
  // §5 v2.1: единственный тумблер карточки идёт через ОДИН store —
  // setModuleScopeState (область фиксирует верхний селектор), который
  // делегирует в канонические write-path (global / этого чата).
  const scopeCalls = (MOD.match(/setModuleScopeState\(/g) || []).length;
  assert.strictEqual(scopeCalls, 1, 'g: в карточке ровно один write-вызов тумблера');
  assert.strictEqual(MOD.indexOf('setModuleGlobalState('), -1,
    'g: шаблон не вызывает глобальную операцию напрямую (только через scope)');
  assert.strictEqual(MOD.indexOf('toggleModule('), -1,
    'g: шаблон не вызывает чатовую операцию напрямую (только через scope)');
  assert.ok(/setModuleScopeState: async function/.test(APP_JS),
    'g: операция области не реализована методом store');
  const sblock = APP_JS.slice(APP_JS.indexOf('setModuleScopeState: async function'),
                              APP_JS.indexOf('moduleOverrideResetAvailable: function'));
  assert.ok(sblock.indexOf('this.moduleScopeIsGlobal()') >= 0 &&
            sblock.indexOf('setModuleGlobalState(m, enabled)') >= 0 &&
            sblock.indexOf('setModuleState(this.storeScope(), m.id, enabled)') >= 0,
    'g: область решает, какой канонический write-path вызвать');
  assert.strictEqual(APP_JS.indexOf('data-module-scope-toggle'), -1,
    'g: атрибут тумблера живёт только в index.html');
}

console.log('MODULE-CATALOG-OK');
