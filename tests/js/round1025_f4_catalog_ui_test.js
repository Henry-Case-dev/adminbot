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
  const posCounters = MOD.indexOf('module-counters');
  const posQuick = MOD.indexOf('module-quick-wrap');
  const posToolbar = MOD.indexOf('module-toolbar');
  const posCatalog = MOD.indexOf('module-catalog');
  for (const [name, pos] of [['заголовок', posHead], ['счётчики', posCounters],
    ['панель', posQuick], ['поиск/фильтры', posToolbar], ['каталог', posCatalog]]) {
    assert.ok(pos >= 0, 'a: нет блока «' + name + '»');
  }
  assert.ok(posHead < posCounters && posCounters < posQuick
    && posQuick < posToolbar && posToolbar < posCatalog,
    'a: порядок блоков §32 нарушен');
  for (const m of ['moduleCounters.total', 'moduleCounters.on',
    'moduleCounters.off', 'moduleCounters.issues']) {
    assert.ok(MOD.indexOf(m) >= 0, 'a: нет индикатора ' + m);
  }
}

// ── (b) Поиск и фильтры §44/§32 ─────────────────────────────────────────
{
  assert.ok(MOD.indexOf('placeholder="Найти модуль…"') >= 0, 'b: нет поля поиска');
  assert.ok(MOD.indexOf('v-model="moduleSearch"') >= 0, 'b: поиск не привязан');
  assert.ok(MOD.indexOf('moduleFilterOptions') >= 0, 'b: нет фильтров');
  assert.ok(MOD.indexOf('moduleFilter === f.id') >= 0, 'b: фильтр не активен');
  for (const label of ['Все', 'Включённые', 'Выключенные',
    'Есть проблемы', 'Избранные']) {
    assert.ok(APP_JS.indexOf("label: '" + label + "'") >= 0,
      'b: нет фильтра «' + label + '»');
  }
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

// ── (d) Панель ≤4/2/2–1 + «Все избранные» ───────────────────────────────
{
  assert.ok(/\.module-quick\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/.test(CSS),
    'd: панель не 4 колонки (base)');
  assert.ok(/@container\s*\(max-width:\s*1023px\)\s*\{[^}]*\.module-quick\s*\{[^}]*repeat\(2,\s*minmax\(0,\s*1fr\)\)/.test(CSS),
    'd: панель tablet не 2 колонки');
  assert.ok(MOD.indexOf('Все избранные') >= 0, 'd: нет «Все избранные»');
  assert.ok(MOD.indexOf('v-for="m in quickpickVisible"') >= 0, 'd: нет элементов панели');
  assert.ok(MOD.indexOf('module-quick-item') >= 0, 'd: нет карточки панели');
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
  // aria-label на тумблере сохранён
  assert.ok(MOD.indexOf(":aria-label=\"'Включить модуль ' + m.title\"") >= 0,
    'e: нет aria-label тумблера');
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
  // панель/карточка/модалка используют одни moduleEnabled/toggleModule
  const en = (MOD.match(/moduleEnabled\(/g) || []).length;
  const tg = (MOD.match(/toggleModule\(/g) || []).length;
  assert.ok(en >= 3, 'g: тумблеры не через единый store (' + en + ')');
  assert.ok(tg >= 3, 'g: переключение не через единый store (' + tg + ')');
}

console.log('MODULE-CATALOG-OK');
