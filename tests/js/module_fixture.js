'use strict';
/* MOD-ACL-UX-01 M4A: общий загрузчик DTO каталога для node-юнитов.
 *
 * До M4A `web/app.js` содержал массив `MODULES`, и юниты читали карточки
 * прямо из `data.modules`. Каталог удалён (design D2) — карточки появляются
 * только после `loadConfig` (`GET /api/config.modules[]`). Здесь тот же
 * production-путь повторяется на закоммиченном снимке живого
 * `registry_for_frontend()` (drift ловит Python-тест
 * `tests/test_mod_acl_ux_01_m3_module_routes.py::test_js_fixture_matches_live_registry`);
 * второй копии списка модулей нет.
 */
const fs = require('fs');
const path = require('path');

const SPECS = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'fixtures', 'module_registry_visible.json'),
  'utf8'));

function applyModuleDto(captured) {
  const data = captured.data();
  const methods = captured.methods || {};
  if (typeof methods.f3ApplyModuleRegistry !== 'function') return data;
  // `workspaceModule` truthy гасит route-переприменение, которое юниту не
  // нужно: маршрутизацию проверяет конкретный тест своим `applyRoute`.
  methods.f3ApplyModuleRegistry.call({
    modules: data.modules,
    _f4Registry: {},
    workspaceModule: { id: 'stub' },
    _pendingModuleRoute: null,
    applyRoute: function () {},
    toast: function () {},
  }, SPECS);
  return data;
}

module.exports = { SPECS: SPECS, applyModuleDto: applyModuleDto };
