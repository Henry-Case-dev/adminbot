'use strict';
/* MOD-ACL-UX-01 M4A — independent-review fixes (D1–D10).

Проверяет целевые швы по finding'ам:
  D1  hit-area tri-state не перекрывает соседнюю кнопку (вертикальный inset);
  D2  подпись CHAT в карточке читаемая: без nowrap/ellipsis, отдельная строка;
  D3  can_read=false → нет state-чипов/значений (только отказ с ролью);
  D4  409 → diff «ваше/на сервере» + «Применить свою»/«Загрузить серверное»,
      без авто-loadConfig; ровно один POST на явный повтор (param и gate);
  D6  GLOBAL OFF + CHAT ON → badge «Включено отдельно для этого чата»;
      GLOBAL ON + CHAT OFF → «Выключено в этом чате»; global OFF — общий режим;
  D7  no-master (time/embeddings) — без фиктивного GLOBAL switch;
  D8  403 каталога — «Нет доступа к разделу «Модули»», без «Очистить поиск»;
  D9  длинная причина ready=false доступна через title/aria-label;
  D10 role=tabpanel на общем контейнере вкладок (все вкладки, не только Обзор).

Запуск: node tests/js/mod_acl_ux_m4_review_fixes_test.js
*/
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const ROOT = path.join(__dirname, '..', '..');
const APP_JS = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const INDEX = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'web', 'static', 'app.css'), 'utf8');

let captured = null;
global.Vue = {
  createApp: function (opts) {
    captured = opts;
    return { component() {}, provide() {}, use() {}, mount() {} };
  },
};
const _storage = {
  _s: {},
  getItem(k) {
    return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null;
  },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
global.window = {
  location: { hash: '' }, addEventListener() {}, Telegram: null,
  confirm: function () { return true; }, localStorage: _storage,
};
global.document = {
  addEventListener() {}, getElementById() { return null; },
  createElement() { return { style: {}, setAttribute() {}, remove() {} }; },
  body: { appendChild() {}, removeChild() {} },
  querySelector() { return null; },
};
Object.defineProperty(global, 'navigator', {
  configurable: true, value: { clipboard: { writeText: async function () {} } },
});
global.sessionStorage = _storage;
global.localStorage = _storage;
global.history = { replaceState() {} };
global.Chart = function () {};
global.fetch = async function () { throw new Error('no fetch in test'); };

require(path.join(ROOT, 'web', 'app.js'));
const { applyModuleDto } = require('./module_fixture.js');
const data = applyModuleDto(captured);
const methods = captured.methods;
const computed = captured.computed;
const MODULES = data.modules;

let checks = 0;
function ok(cond, msg) {
  assert.ok(cond, msg);
  checks += 1;
}
function eq(a, b, msg) {
  assert.strictEqual(a, b, msg);
  checks += 1;
}
function byId(id) {
  return MODULES.filter(function (m) { return m.id === id; })[0];
}
function stateOf(patch) {
  return Object.assign({
    chat_state: 'inherit', desired: true, source: 'global',
    effective_runtime: true, ready: null, observed: null,
    observed_at: null, last_activity_at: null, emergency_block: false,
    reason_code: null, pending_restart: false, conflict: null,
    checked_at: '2026-11-17T00:00:00+00:00',
  }, patch || {});
}
function withState(m, patch, perms) {
  return Object.assign({}, m, {
    state: patch === null ? null : stateOf(patch),
    permissions: perms || { can_read: true, can_edit: true },
  });
}
function mkCtx(overrides) {
  const apiCalls = [];
  const loads = [];
  const toasts = [];
  const ctx = Object.assign({}, methods, {
    modules: MODULES,
    scopeKind: 'chat',
    activeChatId: -100,
    scopeEpoch: 7,
    configChatUpdatedAt: 'ts-1',
    moduleChatPending: {},
    moduleChatError: {},
    moduleConflict: {},
    moduleGlobalPending: {},
    moduleGlobalOptimistic: {},
    moduleGlobalError: {},
    me: { role_name: 'local_admin' },
    _opSeq: 0,
    apiCalls: apiCalls,
    loads: loads,
    _toasts: toasts,
    toast: function (m, k) { toasts.push([m, k]); },
    loadConfig: async function () { loads.push(1); },
    _preserveScroll: async function (fn) { return fn && fn.call(this); },
    api: async function (url, opts) {
      apiCalls.push({ url: url, opts: opts || {} });
      if (ctx.__apiImpl) return ctx.__apiImpl(url, opts);
      return {};
    },
  });
  Object.assign(ctx, overrides || {});
  return ctx;
}

(async function run() {
  try {
    // ── D1: hit-area только вертикальная ───────────────────────────────
    {
      const m = CSS.match(
        /\.module-card \.module-tristate-btn::after \{([^}]*)\}/);
      ok(m, 'D1: нет правила hit-area для tri-state в карточке');
      ok(/inset:\s*-?\d+px\s+0/.test(m[1]),
        'D1: hit-area tri-state должна быть inset: -Npx 0 (без горизонтали)');
      ok(!/inset:\s*-10px\s*;/.test(m[1]),
        'D1: горизонтальный inset -10px перекрывает соседнюю кнопку');
      ok(CSS.indexOf('.module-tristate-btn::after') >= 0,
        'D1: hit-area объявлена у tri-state');
    }

    // ── D2: читаемая подпись (двухстрочный контрол, без ellipsis) ──────
    {
      const row = CSS.match(/\.module-card \.module-control-row \{([^}]*)\}/);
      ok(row && /flex-direction:\s*column/.test(row[1]),
        'D2: строка контроля карточки — колонка (подпись над tri-state)');
      const label = CSS.match(
        /\.module-card \.module-control-row__label \{([^}]*)\}/);
      ok(label && /white-space:\s*normal/.test(label[1]),
        'D2: подпись CHAT переносится (white-space: normal)');
      ok(label && !/text-overflow:\s*ellipsis/.test(label[1]),
        'D2: подпись CHAT не обрезается ellipsis');
      ok(INDEX.indexOf(':data-module-chat-tristate="opt.id"') >= 0 &&
        INDEX.indexOf('{{ opt.label }}') >= 0,
        'D2: tri-state в шаблоне — реальные кнопки с полными подписями');
      ok(!/\.module-card \.module-control-row__label[^{]*\{[^}]*overflow:\s*hidden/
        .test(CSS), 'D2: подпись не прячется overflow:hidden');
    }

    // ── D3: can_read=false — только отказ, без значений ────────────────
    {
      const ctx = mkCtx();
      const denied = withState(byId('mod_budgets'), {},
        { can_read: false, can_edit: false });
      eq(methods.moduleStateChips.call(ctx, denied).length, 0,
        'D3: can_read=false → нет state-чипов');
      eq(methods.moduleStateText.call(ctx, denied), 'Нет права смотреть',
        'D3: карточка — отказ вместо состояния');
      ok(INDEX.indexOf('modulePermissions(m).can_read === false') >= 0 &&
        INDEX.indexOf('data-module-denied') >= 0,
        'D3: карточка не рендерит контроль/значения при отказе');
      ok(INDEX.indexOf('data-workspace-denied') >= 0 &&
        INDEX.indexOf('modulePermissions(workspaceModule).can_read === false') >= 0,
        'D3: страница модуля — отказ без чипов/контролов');
      eq(methods.moduleStateChips.call(ctx,
        withState(byId('mod_summary'), {}, { can_read: true, can_edit: true }))
        .length, 5, 'D3: при праве чтения чипы остаются');
    }

    // ── D6: честный badge GLOBAL↔CHAT ──────────────────────────────────
    {
      const ctx = mkCtx();
      const onGlobalOff = withState(byId('mod_summary'), {
        chat_state: 'on', desired: true, source: 'chat', global_value: false,
      });
      const b1 = methods.moduleEffectiveBadge.call(ctx, onGlobalOff);
      ok(b1 && b1.code === 'chat_on_global_off' &&
        b1.text === 'Включено отдельно для этого чата',
        'D6: GLOBAL OFF + CHAT ON → «Включено отдельно для этого чата»');
      const offGlobalOn = withState(byId('mod_summary'), {
        chat_state: 'off', desired: false, source: 'chat', global_value: true,
        effective_runtime: false,
      });
      const b2 = methods.moduleEffectiveBadge.call(ctx, offGlobalOn);
      ok(b2 && b2.text === 'Выключено в этом чате',
        'D6: GLOBAL ON + CHAT OFF → «Выключено в этом чате»');
      const gctx = mkCtx({ scopeKind: 'global', activeChatId: null });
      const b3 = methods.moduleEffectiveBadge.call(gctx,
        withState(byId('mod_web'), { desired: false, source: 'global',
          effective_runtime: false }));
      ok(b3 && b3.code === 'global_off_inherit' &&
        b3.text.indexOf('новые чаты наследуют') >= 0,
        'D6: global OFF — «Общий режим: выключен (новые чаты наследуют)»');
      eq(methods.moduleEffectiveBadge.call(ctx,
        withState(byId('mod_summary'), { source: 'global' })), null,
        'D6: обычное наследование — без лишнего badge');
      ok(INDEX.indexOf('data-module-effective') >= 0 &&
        INDEX.indexOf('data-workspace-effective') >= 0,
        'D6: badge рендерится в карточке и шапке');
    }

    // ── D7: no-master без фиктивного switch ───────────────────────────
    {
      const cardStart = INDEX.indexOf('class="module-card-body"');
      const cardEnd = INDEX.indexOf('class="module-card-footer"', cardStart);
      const CARD = INDEX.slice(cardStart, cardEnd);
      ok(/<template v-if="m.toggleKey">/.test(CARD),
        'D7: GLOBAL switch карточки — только при m.toggleKey');
      ok(CARD.indexOf('data-module-global-toggle') > CARD.indexOf('m.toggleKey'),
        'D7: switch не рендерится вне master-оси');
      ok(CARD.indexOf('data-module-no-master') >= 0,
        'D7: no-master получает явную подпись');
      ok(CARD.indexOf('data-module-scope-readonly') >= 0,
        'D7: чатовый no-master — без «управляется глобально» для time');
      ok(INDEX.indexOf('data-workspace-no-toggle') >= 0,
        'D7: шапка no-master — без switch');
      eq(methods.moduleChatScopeAvailable.call(
        mkCtx({ scopeKind: 'global', activeChatId: null })), false,
        'D7: в GLOBAL scope чатовый tri-state недоступен');
      eq(methods.moduleChatScopeAvailable.call(mkCtx()), true,
        'D7: в chat scope tri-state доступен');
      const time = byId('mod_time');
      eq(methods.moduleChatControlAvailable.call(mkCtx(), time), false,
        'D7: time — без чатового тумблера');
    }

    // ── D8: 403 каталога ≠ пустой поиск ───────────────────────────────
    {
      const forb = mkCtx({ configErrorStatus: 403, moduleSearch: 'x' });
      eq(computed.moduleCatalogForbidden.call(forb), true,
        'D8: 403 распознан');
      eq(computed.moduleFilterEmptyText.call(forb),
        'Нет доступа к разделу «Модули»',
        'D8: текст отказа раздела');
      ok(INDEX.indexOf('!moduleCatalogForbidden') >= 0,
        'D8: «Очистить поиск» скрыт при отказе');
      const empty = mkCtx({ configErrorStatus: 0, moduleSearch: 'zzz' });
      eq(computed.moduleFilterEmptyText.call(empty),
        'Ничего не найдено. Очистить поиск.',
        'D8: обычный пустой поиск сохранён');
      ok(APP_JS.indexOf('this.configErrorStatus = (e && e.status) || 0;') >= 0,
        'D8: статус ошибки сохраняется при загрузке');
    }

    // ── D9: длинная причина доступна (title/aria-label) ────────────────
    {
      const cardStateAt = INDEX.indexOf('data-module-state',
        INDEX.indexOf('!moduleConflictFor(m) && !m.noToggle'));
      const cardState = INDEX.slice(cardStateAt, cardStateAt + 400);
      ok(/ :title="moduleStateText\(m\)"/.test(cardState) &&
        / :aria-label="moduleStateText\(m\)"/.test(cardState),
        'D9: причина доступна через title и aria-label');
    }

    // ── D10: tabpanel на общем контейнере вкладок ──────────────────────
    {
      ok(INDEX.indexOf(
        ":role=\"workspaceModule && workspace.door === 'modules' ? 'tabpanel' : null\"")
        >= 0, 'D10: role=tabpanel на контейнере всех вкладок');
      eq(INDEX.indexOf('data-workspace-overview\n                   role="tabpanel"'), -1,
        'D10: дубль role=tabpanel у Обзора убран');
    }

    // ── D4: 409 → diff/выбор, без авто-перезагрузки ────────────────────
    {
      const m = withState(byId('mod_summary'), {});
      const ctx = mkCtx();
      ctx.__apiImpl = function (url, opts) {
        if ((opts || {}).method === 'POST') {
          const err = new Error('409');
          err.status = 409;
          err.message = { code: 'conflict', conflicting: ['flags.summary_enabled'] };
          throw err;
        }
        if (url === '/api/config') {
          return {
            updated_at: 'ts-server-9',
            modules: [{ id: 'summary', state: { chat_state: 'on',
              desired: true, global_value: true } }],
          };
        }
        return {};
      };
      const res = await methods.setModuleChatTriState.call(ctx, m, 'off');
      eq(res.error, 'conflict', 'D4: 409 распознан');
      eq(ctx.loads.length, 0, 'D4: НЕТ авто-loadConfig до выбора');
      const conflict = methods.moduleConflictFor.call(ctx, m);
      ok(conflict, 'D4: конфликт сохранён для diff/выбора');
      eq(conflict.localText, 'Выключить', 'D4: diff «ваше»');
      eq(conflict.serverText, 'Включить', 'D4: diff «на сервере»');
      eq(conflict.serverUpdatedAt, 'ts-server-9',
        'D4: серверный optimistic-token сохранён для повтора');
      eq(ctx.stickyConflict.length, 1, 'D4: stickyConflict непустой');
      ok(ctx._toasts.some(function (t) {
        return t[0] === 'Настройка изменилась в другом окне';
      }), 'D4: человеческий баннер');
      ok(INDEX.indexOf('data-module-conflict-open') >= 0,
        'D4/R2: компактный 409-индикатор ведёт в workspace');
      ok(INDEX.indexOf('data-module-conflict-apply') < 0,
        'R2: полный diff/выбор не рендерится в карточке (высота)');
      ok(INDEX.indexOf('data-workspace-conflict-apply') >= 0 &&
        INDEX.indexOf('data-workspace-conflict-server-load') >= 0,
        'D4: обе кнопки выбора в workspace');

      // «Применить свою» → ровно один явный POST с серверным токеном.
      ctx.apiCalls.length = 0;
      ctx.__apiImpl = function () { return {}; };
      const applied = await methods.applyModuleConflict.call(ctx, m);
      eq(applied.ok, true, 'D4: «Применить свою» выполнена');
      eq(ctx.apiCalls.length, 1, 'D4: ровно один POST на явный повтор');
      const body = JSON.parse(ctx.apiCalls[0].opts.body);
      eq(body.items[0].value, false, 'D4: повтор несёт намерение «Выключить»');
      eq(body.updated_at, 'ts-server-9',
        'D4: повтор использует серверный optimistic-token');
      eq(ctx.loads.length, 1, 'D4: применение перечитывает состояние один раз');
      eq(methods.moduleConflictFor.call(ctx, m), null,
        'D4: конфликт снят после успеха');

      // «Загрузить серверное» → без POST, один reload.
      const ctx2 = mkCtx();
      ctx2.__apiImpl = function (url, opts) {
        if ((opts || {}).method === 'POST') {
          const err = new Error('409');
          err.status = 409;
          err.message = { code: 'conflict' };
          throw err;
        }
        return { updated_at: 'ts-2', modules: [] };
      };
      await methods.setModuleChatTriState.call(ctx2, m, 'on');
      ctx2.apiCalls.length = 0;
      await methods.loadServerConflict.call(ctx2, m);
      eq(ctx2.apiCalls.length, 0, 'D4: «Загрузить серверное» без POST');
      eq(ctx2.loads.length, 1, 'D4: серверное — один reload');
      eq(methods.moduleConflictFor.call(ctx2, m), null,
        'D4: конфликт снят при загрузке серверного');

      // Gate-путь: stickyConflict = feature, diff/выбор тоже.
      const gateMod = withState(byId('mod_nostalgia'), {});
      const gctx = mkCtx();
      gctx.__apiImpl = function (url, opts) {
        if ((opts || {}).method === 'PUT') {
          const err = new Error('409');
          err.status = 409;
          err.message = { code: 'conflict' };
          throw err;
        }
        return { modules: [{ id: 'nostalgia',
          state: { chat_state: 'off' } }] };
      };
      await methods.setModuleChatTriState.call(gctx, gateMod, 'on');
      eq(gctx.stickyConflict[0], 'nostalgia',
        'D4: gate 409 → stickyConflict = feature (не пустая строка)');
      const gconf = methods.moduleConflictFor.call(gctx, gateMod);
      ok(gconf && gconf.serverText === 'Выключить',
        'D4: gate diff «на сервере» строится');
      eq(gctx.loads.length, 0, 'D4: gate 409 без авто-reload');
    }

    // ── R1: badge inline, не раздувает карточку ────────────────────────
    {
      const cardStart = INDEX.indexOf('class="module-card-body"');
      const cardEnd = INDEX.indexOf('class="module-card-footer"', cardStart);
      const CARD = INDEX.slice(cardStart, cardEnd);
      ok(CARD.indexOf('module-effective-inline') >= 0,
        'R1: badge эффективного состояния — inline в строке состояния');
      ok(CARD.indexOf('class="module-effective"') < 0,
        'R1: отдельного badge-блока в карточке нет');
      ok(/\.module-effective-inline \{[^}]*font-size:\s*10px/.test(CSS),
        'R1: inline badge компактный (10 px)');
      const ctx = mkCtx();
      const b = methods.moduleEffectiveBadge.call(ctx,
        withState(byId('mod_summary'), { source: 'chat', chat_state: 'on',
          desired: true, global_value: false }));
      ok(b && b.short && b.short.length <= 24,
        'R1: короткая подпись inline-badge (≤24 символов)');
      eq(b.text, 'Включено отдельно для этого чата',
        'R1: полная подпись сохранена для title/aria и шапки');
    }

    // ── R2: компактный 409 в карточке, diff/выбор — в workspace ────────
    {
      const cardStart = INDEX.indexOf('class="module-card-body"');
      const cardEnd = INDEX.indexOf('class="module-card-footer"', cardStart);
      const CARD = INDEX.slice(cardStart, cardEnd);
      ok(CARD.indexOf('data-module-conflict') >= 0 &&
        CARD.indexOf('data-module-conflict-open') >= 0,
        'R2: карточка показывает компактный конфликт + «Разрешить»');
      ok(CARD.indexOf('module-conflict__diff') < 0 &&
        CARD.indexOf('module-conflict__actions') < 0,
        'R2: diff/кнопки выбора не в карточке');
      ok(/\.module-conflict-compact \{[^}]*min-height:\s*44px/.test(CSS),
        'D2: 409-строка карточки — реальные 44 px (hit-area)');
      ok(CARD.indexOf('class="module-state module-state--conflict"') < 0,
        'D2: конфликт не в 16-px строке состояния');
      // Полный diff/выбор доступен в workspace.
      ok(INDEX.indexOf('data-workspace-conflict-local') >= 0 &&
        INDEX.indexOf('data-workspace-conflict-server') >= 0,
        'R2: diff «ваше/на сервере» доступен в workspace');
    }

    // ── R3: «Время» — один текст без дубля ─────────────────────────────
    {
      const cardStart = INDEX.indexOf('class="module-card-body"');
      const cardEnd = INDEX.indexOf('class="module-card-footer"', cardStart);
      const CARD = INDEX.slice(cardStart, cardEnd);
      ok(/v-else-if="!m\.noToggle"[^>]*class="module-state/.test(CARD) ||
        /class="module-state text-xs"\s*\n\s*data-module-state/.test(CARD),
        'R3: строка состояния не рендерится для no-master');
      ok(CARD.indexOf('!moduleConflictFor(m) && !m.noToggle') >= 0,
        'R3: no-master (time) — только подпись контроля');
    }

    // ── R4: workspace tri-state — реальные 44 px ───────────────────────
    {
      ok(/@media \(pointer: coarse\), \(max-width: 767px\) \{[^}]*\[data-workspace-chat-tristate\]\s*\{[^}]*min-height:\s*44px/
        .test(CSS), 'R4: workspace tri-state 44 px на coarse/mobile');
      ok(CSS.indexOf('.module-card .module-tristate-btn::after') >= 0,
        'R4: hit-area карточки остаётся scoped (без перекрытия workspace)');
      ok(/\.workspace-control\[data-workspace-chat-control\] \{[^}]*flex-wrap:\s*wrap/
        .test(CSS), 'D1: workspace chat-control переносит label/tri-state');
      ok(/@media \(pointer: coarse\), \(max-width: 767px\) \{[^}]*\[data-workspace-chat-control\] \{[^}]*flex-direction:\s*column/
        .test(CSS), 'D1: на мобиле label и tri-state — две строки');
      ok(CSS.indexOf('.workspace-control[data-workspace-chat-control] .module-tristate {') >= 0
        && CSS.indexOf('max-width: 100%') >= 0,
        'D1: tri-state ограничен шириной, а не обрезан');
    }

    console.log('M4-REVIEW-FIXES-OK — ' + checks + ' проверок');
  } catch (e) {
    console.error(e && e.stack ? e.stack : e);
    process.exit(1);
  }
})();
