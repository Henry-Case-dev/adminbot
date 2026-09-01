/* Epic 85 (84.7, T-620/T-621/T-632/T-639/T-640/T-644) — фронтенд TMA-админки.
 * Vue 3 Options API (global build), zero-build. Все запросы — через api()
 * с заголовком X-Telegram-Init-Data (84.6). 401 → сессия устарела;
 * 403 → запрет. Вкладки «📊 Статус» и «ℹ️ Как это работает» видны ВСЕГДА.
 */
(function () {
  'use strict';

  var TABS = [
    { id: 'prompts', icon: '🧠', label: 'Промпты', categories: ['prompts'] },
    { id: 'models', icon: '⚙️', label: 'Модели и Провайдеры', categories: ['models'] },
    { id: 'keys', icon: '🔑', label: 'API Ключи', categories: ['keys'] },
    { id: 'limits', icon: '🚦', label: 'Лимиты и Модули', categories: ['limits', 'flags'] },
    { id: 'access', icon: '👥', label: 'Управление доступом', categories: ['access'] },
    { id: 'status', icon: '📊', label: 'Статус', always: true },
    { id: 'info', icon: 'ℹ️', label: 'Как это работает', always: true },
  ];

  var LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];

  function arr(x) { return Array.isArray(x) ? x : []; }

  Vue.createApp({
    data: function () {
      return {
        tabs: TABS,
        activeTab: 'status',
        sidebarOpen: false,
        me: null,
        authError: null,
        authLocked: false,
        // config
        configItems: [],
        configGroups: [],          // 84.24: метаданные групп (с сервера)
        configSearch: '',          // 84.24: фильтр по title/description/key
        configLoading: false,
        saving: new Set(),
        keyDrafts: {},
        // access
        admins: [],
        adminsLoading: false,
        rolesList: [],
        rolesLoading: false,
        newAdminId: '',
        newAdminRole: 'user',
        newRoleName: '',
        roleEditor: {
          open: false,
          loading: false,
          saving: false,
          roleName: '',
          isCustom: false,
          wildcard: false,
          sections: [],
          actions: [],
        },
        // status
        statusData: null,
        statusError: null,
        statusTimer: null,
        uptimeChart: null,
        logs: [],
        logsCount: 0,
        logsLoading: false,
        logLevel: 'INFO',
        // control
        controlLocked: false,
        controlLockSeconds: 0,
        controlTimer: null,
        controlBanner: null,
        confirmAction: null,
        // info
        infoHtml: '',
        infoMeta: null,
        infoLoading: false,
        editingInfo: false,
        infoPreviewing: false,
        infoDraft: '',
        // toasts
        toasts: [],
      };
    },

    computed: {
      currentTabLabel: function () {
        var tab = this.tabs.find(function (t) { return t.id === this.activeTab; }, this);
        return tab ? tab.label : '';
      },
      permissions: function () {
        return (this.me && this.me.permissions) ? this.me.permissions : {};
      },
      // F4 (84.14.5): сайдбар показывает ТОЛЬКО доступные вкладки;
      // «Статус» и «Как это работает» — всегда (RBAC-исключения).
      visibleTabs: function () {
        var self = this;
        return this.tabs.filter(function (tab) {
          return tab.always || self.canViewTab(tab.id);
        });
      },
      errorLogs: function () {
        return this.logs.filter(function (l) { return l.level === 'ERROR' || l.level === 'CRITICAL'; });
      },
      warnLogs: function () {
        return this.logs.filter(function (l) { return l.level === 'WARNING'; });
      },
      canEditInfo: function () {
        return this.hasPerm('action.edit_info');
      },
      sanitizedInfoHtml: function () {
        return this.sanitizeHtml(this.infoHtml);
      },
      confirmText: function () {
        var labels = {
          restart: 'Перезапустить бота? Текущий процесс будет остановлен (graceful shutdown) и поднят заново.',
          stop: 'Остановить бота? Бот останется выключенным до ручного/веб-запуска.',
          start: 'Запустить бота?',
        };
        return labels[this.confirmAction] || '';
      },
    },

    mounted: function () {
      var self = this;
      // Фин. доработка (DevOps): без Telegram-контекста — блокирующая
      // заглушка вместо бессмысленных 401 (ngrok-интерстициал ломал контекст).
      if (!this.hasInitData()) {
        this.authError = 'Миниапп открыт без Telegram-контекста — ' +
          'откройте админку через кнопку меню в боте';
        this.authLocked = true;
        return;
      }
      this.loadMe().then(function () {
        if (!self.me) return;             // 401/пусто — блокировка выше
        self.loadConfig();
        if (self.canViewTab('access')) {
          self.loadAdmins();
          self.loadRoles();
        }
        // ФИКС 2026-09-03: данные АКТИВНОЙ вкладки (по умолчанию 'status')
        // не грузились до первого переключения — loaders вызывались только
        // в setTab. Теперь после успешной авторизации вызываем per-tab
        // loader активной вкладки (loadStatus+loadLogs+polling для 'status').
        self.setTab(self.activeTab);
      });
      // Опц. рекомендация ревью: контекст Telegram может появиться ПОЗЖЕ
      // готовности WebView — подписываемся на событие ready (дебаунс —
      // флаг retriedOnce, чтобы не дублировать запросы).
      if (window.Telegram && Telegram.WebApp && Telegram.WebApp.onEvent) {
        Telegram.WebApp.onEvent('ready', function () {
          self.retryInitData();
        });
      }
    },

    methods: {
      hasInitData: function () {
        try {
          return !!(window.Telegram && Telegram.WebApp && Telegram.WebApp.initData);
        } catch (e) {
          return false;
        }
      },

      retryInitData: function () {
        var self = this;
        if (!this.hasInitData()) {
          // контекст так и не появился — снова блокирующая заглушка
          this.authLocked = true;
          this.authError = 'Миниапп открыт без Telegram-контекста — ' +
            'откройте админку через кнопку меню в боте';
          return;
        }
        this.authLocked = false;
        this.authError = null;
        this.loadMe().then(function () {
          var me = self.me;
          if (!me) {
            // /api/me не вернул юзера (401/пусто) — контекст есть, но не
            // авторизован; не спамить API — блокируем с баннером.
            self.authLocked = true;
            self.authError = 'Не удалось авторизоваться (initData). ' +
              'Откройте админку заново из Telegram.';
            return;
          }
          self.loadConfig();
          if (self.canViewTab('access')) {
            self.loadAdmins();
            self.loadRoles();
          }
          // ФИКС 2026-09-03: автозагрузка активной вкладки (как в mounted)
          self.setTab(self.activeTab);
        });
      },

      // ═══ API-обёртка (84.6: X-Telegram-Init-Data на каждый запрос) ═══
      api: async function (path, options) {
        // Без Telegram-контекста запросы бессмысленны (401 вхолостую) —
        // заглушка вместо спама в API (фин. доработка DevOps).
        if (this.authLocked || !this.hasInitData()) {
          throw new ApiError(401, 'no telegram context');
        }
        options = options || {};
        options.headers = Object.assign({}, options.headers || {});
        if (!options.headers['Content-Type'] && options.body) {
          options.headers['Content-Type'] = 'application/json';
        }
        var initData = '';
        try {
          initData = (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData) || '';
        } catch (e) { initData = ''; }
        if (initData) {
          options.headers['X-Telegram-Init-Data'] = initData;
        }
        var resp = await fetch(path, options);
        if (resp.status === 401) {
          this.authError = 'Не удалось авторизоваться (initData). Откройте админку заново из Telegram.';
          throw new ApiError(401, 'unauthorized');
        }
        var data = null;
        try { data = await resp.json(); } catch (e) { data = null; }
        if (!resp.ok) {
          var detail = (data && data.detail) ? data.detail : ('HTTP ' + resp.status);
          if (resp.status === 403) {
            this.toast('Доступ запрещён: ' + detail, 'err');
          }
          throw new ApiError(resp.status, detail);
        }
        return data;
      },

      toast: function (text, kind) {
        var self = this;
        var id = Date.now() + Math.random();
        this.toasts.push({ id: id, text: text, kind: kind || 'ok' });
        setTimeout(function () {
          self.toasts = self.toasts.filter(function (t) { return t.id !== id; });
        }, 4200);
      },

      setTab: function (id) {
        var self = this;
        this.activeTab = id;
        this.sidebarOpen = false;
        // 84.24-ревью: поиск не переносится между вкладками
        if (this.configSearch) this.configSearch = '';
        if (id === 'status') {
          this.loadStatus();
          this.loadLogs();
          this.startStatusPolling();
        } else {
          this.stopStatusPolling();
        }
        if (id === 'info' && !this.infoHtml && !this.infoLoading) {
          this.loadInfo();
        }
        if (id === 'access' && this.canViewTab('access')) {
          this.loadAdmins();
          this.loadRoles();
        }
        if (['prompts', 'models', 'keys', 'limits'].indexOf(id) >= 0 && !this.configItems.length) {
          self.loadConfig();
        }
      },

      // ═══ Права (84.14.2 — зеркало requires_permission) ═══
      hasPerm: function (required) {
        var p = this.permissions;
        if (!required) return false;
        if (p.wildcard) return true;
        var sections = arr(p.sections), params = arr(p.params),
            keys = arr(p.keys), actions = arr(p.actions);
        if (required.indexOf('section.') === 0) {
          return sections.indexOf(required.slice(8)) >= 0;
        }
        if (required.indexOf('param.') === 0) {
          var fullP = required.slice(6);
          return params.indexOf(fullP) >= 0 || sections.indexOf(fullP.split('.')[0]) >= 0;
        }
        if (required.indexOf('key.') === 0) {
          var fullK = required.slice(4);
          return keys.indexOf(fullK) >= 0 || sections.indexOf(fullK.split('.')[0]) >= 0;
        }
        if (required.indexOf('action.') === 0) {
          return actions.indexOf(required.slice(7)) >= 0;
        }
        if (required.indexOf('.') >= 0) {
          return params.indexOf(required) >= 0 || keys.indexOf(required) >= 0
            || sections.indexOf(required.split('.')[0]) >= 0;
        }
        return actions.indexOf(required) >= 0 || sections.indexOf(required) >= 0;
      },

      canViewTab: function (tabId) {
        var tab = this.tabs.find(function (t) { return t.id === tabId; });
        if (!tab) return false;
        if (tab.always) return true;
        var p = this.permissions;
        if (p.wildcard) return true;
        var sections = arr(p.sections), params = arr(p.params), keys = arr(p.keys);
        for (var i = 0; i < tab.categories.length; i++) {
          var cat = tab.categories[i];
          if (cat === 'access') {
            if (sections.indexOf('access') >= 0) return true;
            continue;
          }
          if (sections.indexOf(cat) >= 0) return true;
          if (params.some(function (k) { return k.indexOf(cat + '.') === 0; })) return true;
          if (cat === 'keys' && keys.length) return true;
        }
        return false;
      },

      canEditConfig: function (key) {
        var p = this.permissions;
        if (p.wildcard) return true;
        var cat = String(key).split('.')[0];
        if (cat === 'keys') {
          return arr(p.keys).indexOf(key) >= 0 || arr(p.sections).indexOf('keys') >= 0;
        }
        return arr(p.params).indexOf(key) >= 0 || arr(p.sections).indexOf(cat) >= 0;
      },

      // ═══ Загрузка данных ═══
      loadMe: async function () {
        try {
          this.me = await this.api('/api/me');
          this.authError = null;
        } catch (e) {
          if (e.status === 401) { /* authError уже выставлен */ }
          this.me = null;
        }
      },

      loadConfig: async function () {
        this.configLoading = true;
        try {
          var data = await this.api('/api/config');
          this.configItems = data.items || [];
          this.configGroups = data.groups || [];
          this.configItems.forEach(function (item) {
            if (item.type === 'json' && typeof item.value === 'object' && item.value !== null) {
              item.value = JSON.stringify(item.value, null, 2);
            }
          });
        } catch (e) {
          // ПРОД-ИНЦИДЕНТ (C): 401 различается — понятное сообщение вместо
          // общего «Не удалось загрузить конфигурацию».
          if (e.status === 401) {
            this.toast('Сессия Telegram недействительна — открой админку через кнопку меню в боте', 'warn');
          } else if (e.status !== 403) {
            this.toast('Не удалось загрузить конфигурацию', 'err');
          }
        } finally {
          this.configLoading = false;
        }
      },

      configByCategory: function (cat) {
        return this.configItems.filter(function (item) { return item.category === cat; });
      },

      // 84.24: группы для вкладки: [{meta, items[]}]; порядок — из
      // серверных groups[] (order), параметры без group → «Прочее» в конце.
      // Поиск-фильтр по title/description/key скрывает пустые группы.
      groupedByCategory: function (cat) {
        var self = this;
        var items = this.configByCategory(cat);
        var q = (this.configSearch || '').trim().toLowerCase();
        if (q) {
          items = items.filter(function (it) {
            return (it.title || '').toLowerCase().indexOf(q) >= 0
              || (it.description || '').toLowerCase().indexOf(q) >= 0
              || (it.key || '').toLowerCase().indexOf(q) >= 0;
          });
        }
        var order = {};
        var byId = {};
        this.configGroups.forEach(function (g) {
          order[g.id] = g.order;
          byId[g.id] = g;
        });
        var grouped = items.reduce(function (acc, it) {
          var gid = it.group || '';
          if (!acc[gid]) {
            acc[gid] = {
              id: gid,
              meta: gid ? (byId[gid] || null) : null,
              items: [],
            };
          }
          acc[gid].items.push(it);
          return acc;
        }, {});
        var result = Object.keys(grouped).map(function (gid) {
          return grouped[gid];
        });
        result.sort(function (a, b) {
          if (a.id === '' && b.id === '') return 0;
          if (a.id === '') return 1;               // «Прочее» — в конец
          if (b.id === '') return -1;
          var oa = a.meta ? a.meta.order : 999;
          var ob = b.meta ? b.meta.order : 999;
          return oa - ob;
        });
        // параметры внутри группы уже отсортированы сервером
        return result;
      },

      groupTitle: function (grp) {
        return (grp.meta && grp.meta.title) || 'Прочее';
      },
      groupDescription: function (grp) {
        return (grp.meta && grp.meta.description) || '';
      },
      clearConfigSearch: function () {
        this.configSearch = '';
      },

      inputType: function (item) {
        if (item.type === 'int' || item.type === 'float') return 'number';
        return 'text';
      },

      saveConfigItem: async function (item) {
        var value = item.value;
        if (item.type === 'int') value = parseInt(value, 10);
        else if (item.type === 'float') value = parseFloat(value);
        if (value === null || value === '' || isNaN(value)) {
          this.toast('Некорректное значение для ' + item.key, 'err');
          return;
        }
        this.saving.add(item.key);
        try {
          await this.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({ items: [{ key: item.key, value: value }] }),
          });
          this.toast('Сохранено: ' + item.title, 'ok');
        } catch (e) {
          this.toast('Ошибка сохранения: ' + e.message, 'err');
        } finally {
          this.saving.delete(item.key);
        }
      },

      // ФИКС 2026-09-03: статус ключа единой функцией — сервер отдаёт
      // {configured, last4} (без права на значение) ЛИБО саму строку
      // (право на значение/админ) — обе формы считаются «настроен»,
      // пустая строка/None → «не настроен».
      isKeyConfigured: function (item) {
        var v = item.value;
        if (v == null || v === '') return false;
        if (typeof v === 'object') return !!v.configured;
        return true;                       // непустая строка-значение
      },
      last4: function (item) {
        var v = item.value;
        if (v && typeof v === 'object') return v.last4 || '';
        if (v && typeof v === 'string') return '••••';   // значение видно, хвост не показываем
        return '';
      },
      saveKeyItem: async function (item) {
        var value = (this.keyDrafts[item.key] || '').trim();
        if (!value) {
          this.toast('Введите новый ключ', 'warn');
          return;
        }
        this.saving.add(item.key);
        try {
          await this.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({ items: [{ key: item.key, value: value }] }),
          });
          this.keyDrafts[item.key] = '';
          this.toast('Ключ обновлён: ' + item.title, 'ok');
          await this.loadConfig();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.saving.delete(item.key);
        }
      },

      // ═══ Управление доступом ═══
      loadAdmins: async function () {
        this.adminsLoading = true;
        try {
          var data = await this.api('/api/admins');
          this.admins = data.admins || [];
        } catch (e) { this.admins = []; }
        finally { this.adminsLoading = false; }
      },
      loadRoles: async function () {
        this.rolesLoading = true;
        try {
          var data = await this.api('/api/roles');
          this.rolesList = data.roles || [];
          if (!this.newAdminRole || !this.rolesList.some(function (r) { return r.role_name === this.newAdminRole; }, this)) {
            var userRole = this.rolesList.find(function (r) { return r.role_name === 'user'; });
            this.newAdminRole = userRole ? 'user' : (this.rolesList[0] || {}).role_name;
          }
        } catch (e) { this.rolesList = []; }
        finally { this.rolesLoading = false; }
      },
      addAdmin: async function () {
        var tgId = parseInt(this.newAdminId, 10);
        if (!tgId) { this.toast('Введите Telegram ID', 'warn'); return; }
        if (!this.newAdminRole) { this.toast('Выберите роль', 'warn'); return; }
        try {
          await this.api('/api/admins', {
            method: 'POST',
            body: JSON.stringify({ telegram_id: tgId, role_name: this.newAdminRole }),
          });
          this.toast('Назначено: ' + tgId + ' → ' + this.newAdminRole, 'ok');
          this.newAdminId = '';
          await this.loadAdmins();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },
      removeAdmin: async function (tgId) {
        if (!window.confirm('Удалить Telegram ID ' + tgId + '?')) return;
        try {
          await this.api('/api/admins/remove', {
            method: 'POST',
            body: JSON.stringify({ telegram_id: tgId }),
          });
          this.toast('Удалён: ' + tgId, 'ok');
          await this.loadAdmins();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },

      // ═══ Конструктор ролей (84.14.4) ═══
      openRoleEditor: async function (role) {
        this.roleEditor.open = true;
        this.roleEditor.loading = true;
        this.roleEditor.roleName = role.role_name;
        this.roleEditor.isCustom = role.is_custom;
        this.roleEditor.wildcard = !!(role.permissions && role.permissions.wildcard);
        try {
          var tree = await this.api('/api/roles/tree?role_name=' + encodeURIComponent(role.role_name));
          this.applyTree(tree);
        } catch (e) {
          this.toast('Ошибка загрузки дерева прав: ' + e.message, 'err');
          this.roleEditor.open = false;
        } finally {
          this.roleEditor.loading = false;
        }
      },
      createRole: async function () {
        var name = (this.newRoleName || '').trim();
        if (!name) { this.toast('Введите имя роли', 'warn'); return; }
        try {
          await this.api('/api/roles', {
            method: 'POST',
            body: JSON.stringify({ role_name: name, permissions: {}, is_custom: true }),
          });
          this.toast('Роль создана: ' + name, 'ok');
          this.newRoleName = '';
          await this.loadRoles();
          var created = this.rolesList.find(function (r) { return r.role_name === name; });
          if (created) await this.openRoleEditor(created);
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },
      applyTree: function (tree) {
        var sections = (tree.sections || []).map(function (s) {
          return {
            id: s.id, title: s.title, checked: !!s.checked, indeterminate: false,
            params: (s.params || []).map(function (p) {
              return { kind: 'param', key: p.key, title: p.title, checked: !!p.checked, section: s.id, secret: !!p.secret };
            }),
            keys: (s.keys || []).map(function (k) {
              return { kind: 'key', key: k.key, title: k.title, checked: !!k.checked, section: s.id };
            }),
          };
        });
        var actions = (tree.actions || []).map(function (a) {
          return { kind: 'action', id: a.id, title: a.title, checked: !!a.checked };
        });
        sections.forEach(function (s) {
          var children = s.params.concat(s.keys);
          var checkedCount = children.filter(function (c) { return c.checked; }).length;
          s.indeterminate = checkedCount > 0 && checkedCount < children.length;
          s.checked = children.length > 0 && checkedCount === children.length;
        });
        this.roleEditor.sections = sections;
        this.roleEditor.actions = actions;
      },
      closeRoleEditor: function () {
        this.roleEditor.open = false;
        this.roleEditor.sections = [];
        this.roleEditor.actions = [];
      },
      sectionChildren: function (section) {
        return section.params.concat(section.keys);
      },
      refreshSectionState: function (section) {
        var children = this.sectionChildren(section);
        var checkedCount = children.filter(function (c) { return c.checked; }).length;
        section.indeterminate = checkedCount > 0 && checkedCount < children.length;
        section.checked = children.length > 0 && checkedCount === children.length;
      },
      toggleSection: function (section) {
        var target = !section.checked;
        this.sectionChildren(section).forEach(function (c) { c.checked = target; });
        section.checked = target;
        section.indeterminate = false;
      },
      toggleNode: function (node) {
        node.checked = !node.checked;
        if (node.section) {
          var section = this.roleEditor.sections.find(function (s) { return s.id === node.section; });
          if (section) this.refreshSectionState(section);
        }
      },
      setIndeterminate: function (el, value) {
        if (el) el.indeterminate = !!value;
      },
      saveRole: async function () {
        var self = this;
        var permissions = { sections: [], params: [], keys: [], actions: [] };
        this.roleEditor.sections.forEach(function (section) {
          var children = self.sectionChildren(section);
          var allChecked = children.length > 0 && children.every(function (c) { return c.checked; });
          if (allChecked) {
            permissions.sections.push(section.id);
          } else {
            section.params.forEach(function (p) { if (p.checked) permissions.params.push(p.key); });
            section.keys.forEach(function (k) { if (k.checked) permissions.keys.push(k.key); });
          }
        });
        this.roleEditor.actions.forEach(function (a) {
          if (a.checked) permissions.actions.push(a.id);
        });
        this.roleEditor.saving = true;
        try {
          var saved = await this.api('/api/roles', {
            method: 'POST',
            body: JSON.stringify({
              role_name: this.roleEditor.roleName,
              permissions: permissions,
            }),
          });
          this.toast('Роль сохранена: ' + saved.role_name, 'ok');
          this.roleEditor.wildcard = !!(saved.permissions && saved.permissions.wildcard);
          await this.loadRoles();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');   // 409 (последняя wildcard) / 422
        } finally {
          this.roleEditor.saving = false;
        }
      },

      // ═══ Статус ═══
      loadStatus: async function () {
        try {
          this.statusData = await this.api('/api/status');
          this.statusError = null;
        } catch (e) {
          // 84.21.1: ошибка на ЛЮБОЙ не-OK (401/403/500/502/…), чтобы не
          // было вечных спиннеров; 401 — понятное сообщение, 403 — заглушка.
          if (e.status === 401) {
            this.statusError = 'Сессия устарела — откройте админку заново из Telegram.';
          } else if (e.status === 403) {
            this.statusError = 'Доступ запрещён (403) — недостаточно прав для Статуса.';
          } else {
            this.statusError = 'Не удалось получить статус сервера (' +
              (e.status ? 'HTTP ' + e.status : 'ошибка сети') + ').';
          }
        }
        this.$nextTick(this.renderUptimeChart);
      },
      startStatusPolling: function () {
        var self = this;
        if (this.statusTimer) return;
        this.statusTimer = setInterval(function () { self.loadStatus(); }, 30000);
      },
      stopStatusPolling: function () {
        if (this.statusTimer) {
          clearInterval(this.statusTimer);
          this.statusTimer = null;
        }
      },
      humanizeUptime: function (seconds) {
        if (seconds == null) return '—';
        var s = Math.max(0, Math.floor(seconds));
        var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
            m = Math.floor((s % 3600) / 60);
        if (d) return d + 'д ' + h + 'ч';
        if (h) return h + 'ч ' + m + 'м';
        return m + 'м ' + (s % 60) + 'с';
      },
      stateBadge: function (state) {
        if (state === 'polling') return 'badge-ok';
        if (state === 'polling_error') return 'badge-err';
        return 'badge-info';
      },
      fmtBytes: function (bytes) {
        if (bytes == null) return '—';
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' ГБ';
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(0) + ' МБ';
        return (bytes / 1024).toFixed(0) + ' КБ';
      },
      healthBadge: function (health) {
        if (!health) return 'badge-muted';
        if (health.ok) return 'badge-ok';
        if (health.status === 'unreachable') return 'badge-warn';
        return 'badge-muted';
      },
      renderUptimeChart: function () {
        var self = this;
        var canvas = this.$refs.uptimeCanvas;
        if (!canvas || !this.statusData || !this.statusData.uptime.buckets.length) return;
        var buckets = this.statusData.uptime.buckets;
        var labels = buckets.map(function (b) {
          var d = new Date(b.ts);
          var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
          return pad(d.getHours()) + ':' + pad(d.getMinutes());
        });
        var data = buckets.map(function (b) { return b.status === 'down' ? 0 : 1; });
        var cfg = {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'up',
              data: data,
              borderColor: '#8b5cf6',
              backgroundColor: 'rgba(139,92,246,0.15)',
              fill: true,
              tension: 0.25,
              pointRadius: 0,
              spanGaps: false,      // разрыв = downtime (84.11.5)
            }],
          },
          options: {
            responsive: true,
            scales: {
              y: { min: 0, max: 1.2, ticks: { display: false } },
              x: { ticks: { color: '#9ca3af', maxTicksLimit: 12, font: { size: 10 } } },
            },
            plugins: { legend: { display: false } },
          },
        };
        if (this.uptimeChart) { this.uptimeChart.destroy(); }
        this.uptimeChart = new Chart(canvas, cfg);
      },

      loadLogs: async function () {
        this.logsLoading = true;
        try {
          var data = await this.api(
            '/api/status/logs?level=' + encodeURIComponent(this.logLevel) + '&limit=200');
          this.logs = (data.logs || []).map(function (l) { l.expanded = false; return l; });
          this.logsCount = data.count || 0;
        } catch (e) { this.logs = []; }
        finally { this.logsLoading = false; }
      },
      levelBadge: function (level) {
        if (level === 'ERROR' || level === 'CRITICAL') return 'badge-err';
        if (level === 'WARNING') return 'badge-warn';
        if (level === 'DEBUG') return 'badge-muted';
        return 'badge-info';
      },
      fmtLogTs: function (ts) {
        if (!ts) return '';
        var d = new Date(ts);
        if (isNaN(d.getTime())) return String(ts).slice(0, 19).replace('T', ' ');
        return d.toLocaleString('ru-RU', { hour12: false });
      },
      logText: function (log) {
        return [log.ts, log.level, log.logger, log.message,
                log.exc_text ? '\n' + log.exc_text : ''].join(' | ');
      },
      copyText: async function (text) {
        try {
          await navigator.clipboard.writeText(text);
          this.toast('Скопировано', 'ok');
        } catch (e) {
          var ta = document.createElement('textarea');
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          try { document.execCommand('copy'); this.toast('Скопировано', 'ok'); }
          catch (e2) { this.toast('Не удалось скопировать', 'err'); }
          document.body.removeChild(ta);
        }
      },
      copyAllLogs: function () {
        this.copyText(this.logs.map(this.logText).join('\n\n'));
      },

      // ═══ Control (84.15.4) ═══
      requestControl: function (action) {
        this.confirmAction = action;
      },
      confirmControl: async function () {
        var action = this.confirmAction;
        this.confirmAction = null;
        try {
          var data = await this.api('/api/control/' + action, { method: 'POST' });
          this.controlBanner = {
            kind: 'ok',
            text: 'Команда принята: ' + action + ' (режим ' + data.mode + ', выполнение через ~'
              + data.scheduled_in_seconds + 'с). ' +
              (action !== 'start' ? 'Бот перезапустится/остановится — соединение может прерваться.' : ''),
          };
          this.lockControl(35);
        } catch (e) {
          if (e.status === 429) {
            this.controlBanner = { kind: 'err', text: 'Слишком часто: ' + e.message };
            this.lockControl(30);
          } else if (e.status === 409) {
            this.toast(e.message, 'warn');
          } else {
            this.controlBanner = { kind: 'err', text: 'Команда не выполнена: ' + e.message };
          }
        }
      },
      lockControl: function (seconds) {
        var self = this;
        this.controlLocked = true;
        this.controlLockSeconds = seconds;
        if (this.controlTimer) clearInterval(this.controlTimer);
        this.controlTimer = setInterval(function () {
          self.controlLockSeconds -= 1;
          if (self.controlLockSeconds <= 0) {
            clearInterval(self.controlTimer);
            self.controlTimer = null;
            self.controlLocked = false;
          }
        }, 1000);
      },

      // ═══ Как это работает (84.13) ═══
      loadInfo: async function () {
        this.infoLoading = true;
        try {
          var data = await this.api('/api/info');
          this.infoHtml = data.html || '';
          this.infoMeta = data;
          this.infoDraft = data.html || '';
        } catch (e) {
          if (e.status !== 401) this.toast('Не удалось загрузить справку', 'err');
        } finally {
          this.infoLoading = false;
        }
      },
      toggleInfoEditor: function () {
        this.editingInfo = !this.editingInfo;
        this.infoPreviewing = false;
        this.infoDraft = this.infoHtml || '';
      },
      sanitizeHtml: function (html) {
        if (window.DOMPurify) {
          return DOMPurify.sanitize(html || '');
        }
        console.warn('[adminbot] DOMPurify недоступен — рендер без санитизации');
        return html || '';
      },
      saveInfo: async function () {
        var html = this.infoDraft || '';
        if (!html.trim()) { this.toast('Текст пуст', 'warn'); return; }
        try {
          var data = await this.api('/api/info', {
            method: 'POST',
            body: JSON.stringify({ html: html }),
          });
          this.infoHtml = html;
          this.infoMeta = data;
          this.editingInfo = false;
          this.toast('Сохранено', 'ok');
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },
    },

    beforeUnmount: function () {
      this.stopStatusPolling();
      if (this.controlTimer) clearInterval(this.controlTimer);
    },
  }).mount('#app');

  function ApiError(status, message) {
    this.status = status;
    this.message = message;
    this.name = 'ApiError';
  }
})();
