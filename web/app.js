/* Epic 85 (84.7, T-620/T-621/T-632/T-639/T-640/T-644) — фронтенд TMA-админки.
 * Vue 3 Options API (global build), zero-build. Все запросы — через api()
 * с заголовком X-Telegram-Init-Data (84.6). 401 → сессия устарела;
 * 403 → запрет. Вкладки «Статус» и «Справка» видны ВСЕГДА.
 *
 * Эпик 04.09.2026 (3.5.1): конфиг-вкладки декларативны и повторяют серверный
 * контракт TAB_RULES (services/param_catalog.py): id вкладок — TAB_*,
 * заголовки — CONFIG_TAB_TITLES, sources — правила «категория → группы».
 * Каждая конфиг-вкладка рендерится ОДНИМ generic-шаблоном (index.html) по
 * groupedForTab() — 5 старых категорийных шаблонов схлопнуты.
 */
(function () {
  'use strict';

  // UPD3 (T-1936/R31): sentinel маски секрета. Маска — НЕ значение: она не
  // сохраняется (guard в saveBlock/saveKeyItem) и не считается изменением.
  var SECRET_MASK = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022';
  function isSecretMask(v) { return v === SECRET_MASK; }
  // UPD3-fix (Critical-1/R31/INV-3): клик в конец маски + ввод даёт КОМПОЗИТ
  // (`••••••••••••<ввод>`). Любая строка, СОДЕРЖАЩАЯ сентинел, считается
  // маской, а не новым секретом: иначе композит уйдёт в POST /api/config и
  // перезапишет реальный ключ (порча BYOK). Guard'ы обязаны использовать
  // ТОЛЬКО этот предикат (не строгое равенство `isSecretMask`).
  function hasSecretMask(v) {
    return String(v == null ? '' : v).indexOf(SECRET_MASK) !== -1;
  }
  // UPD3-fix (L-2): подсказка, когда в поле — маска/композит секрета.
  // Значение НЕ сохранено — сообщение объясняет, что делать (иначе «Уже
  // сохранено» вводит в заблуждение и ввод молча теряется).
  var SECRET_MASK_HINT = 'Поле содержит маску сохранённого секрета — выделите поле и введите значение заново';

  // F9 (10.25, ADR-1025-22 D1/D3): display-индикатор секрета — `••••••••last4`
  // (last4 есть) / «Ключ установлен» (configured без last4) / «Не настроен».
  // Вход: `{configured,last4}` ЛИБО непустое не-объектное значение ЛИБО пусто.
  // Сырой секрет сюда не попадает (R17); маска — НЕ значение input (§50).
  function secretDisplayOf(v) {
    var configured = false;
    var tail = '';
    if (v != null && v !== '') {
      if (typeof v === 'object') {
        configured = !!v.configured;
        tail = v.last4 || '';
      } else {
        configured = true;               // непустое не-объектное значение
      }
    }
    var mask = tail
      ? ('\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022' + tail)
      : (configured ? 'Ключ установлен' : 'Не настроен');
    return { configured: configured, last4: tail, maskText: mask };
  }

  // F11 (10.24, ADR-1024-12): ГЛОБАЛЬНЫЕ провайдерские секреты — сохраняются
  // безопасным путём и правятся ТОЛЬКО глобальным админом (паритет с
  // `PUT /api/config/keys/own scope=global`, который иначе отдаёт 403).
  // Зеркало backend-allowlist `services/chat_keys.GLOBAL_SECRET_KEYS`.
  var GLOBAL_SECRET_KEYS = ['keys.image_api_key'];
  function isGlobalSecretKey(k) { return GLOBAL_SECRET_KEYS.indexOf(k) >= 0; }

  // ═══ Вкладки (3.5.1; зеркало TAB_RULES/CONFIG_TAB_TITLES бэка) ═══
  // sources: [{category, groups|null|except:[...]}] — groups = белый список
  // групп категории, except = вся категория кроме перечисленного, null = вся.
  var TABS = [
    { id: 'llm_providers', icon: 'smart_toy', label: 'LLM Провайдеры',
      type: 'config', menu: 'ai',
      // A4/A8: витрина — блоки ПО МОДУЛЯМ (providerBlocks, HTML); sources —
      // зеркало TAB_RULES (A8: keys_youtube→М6, models_checkup/keys_betterstack→М9).
      sources: [
        { category: 'models', groups: [
            'models_main', 'models_fallback', 'models_embeddings',
            'models_llm_timeouts', 'models_llm_guard',
            'models_extra_providers', 'models_video_summary'] },
        { category: 'keys', groups: [
            'keys_llm', 'keys_groq', 'keys_openrouter', 'keys_search',
            'keys_media'] },
      ] },
    { id: 'prompts', icon: 'description', label: 'Промпты', type: 'config', menu: 'ai',
      sources: [
        { category: 'prompts', groups: null },
        // F7 (10.24, ADR-1024-3 D1): лимит анти-клише — зеркало TAB_RULES
        // (группа limits_anticliche на вкладке «Промпты»).
        { category: 'limits', groups: ['limits_anticliche'] },
      ] },
    // ── Раунд 10.6 (T-1165/T-1201): 11 модулей (config-источники для окна) ──
    { id: 'mod_summary', icon: 'description', label: 'Саммаризация',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_summary', 'flags_summary',
            'flags_summary_filter'] },
        { category: 'limits', groups: ['limits_summary',
            'limits_summary_filter'] },
        { category: 'reactions', groups: ['reactions_summary'] },
      ] },
    { id: 'mod_direct', icon: 'smart_toy', label: 'Прямые ответы',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_direct', 'flags_chat_behavior'] },
        { category: 'limits', groups: ['limits_chat', 'limits_chat_behavior',
            'limits_chat_budgets', 'limits_temperature'] },
        { category: 'reactions', groups: ['reactions_chat'] },
      ] },
    { id: 'mod_factcheck', icon: 'radar', label: 'Фактчек',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_factcheck'] },
        { category: 'limits', groups: ['limits_factcheck'] },
      ] },
    { id: 'mod_search', icon: 'grid_view', label: 'Поиск',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_search'] },
        { category: 'limits', groups: ['limits_search'] },
      ] },
    { id: 'mod_transcribe', icon: 'play_circle', label: 'Транскрипт голосовых и видео',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_transcribe'] },
        { category: 'limits', groups: ['limits_transcribe'] },
      ] },
    { id: 'mod_video_summary', icon: 'play_circle', label: 'Выжимка видео',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_video_summary'] },
        { category: 'limits', groups: ['limits_video_summary', 'limits_youtube',
            'limits_youtube_proxy'] },
        { category: 'keys', groups: ['keys_youtube'] },
      ] },
    { id: 'mod_media_download', icon: 'cloud', label: 'Скачивание медиа',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_media_download'] },
        { category: 'limits', groups: ['limits_media_download'] },
      ] },
    { id: 'mod_web', icon: 'auto_stories', label: 'Веб-страницы',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_web'] },
        { category: 'limits', groups: ['limits_web'] },
      ] },
    { id: 'mod_checkup', icon: 'monitoring', label: 'Диагностика',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_service', 'flags_throttle'] },
        { category: 'limits', groups: ['limits_checkup', 'limits_service'] },
        { category: 'models', groups: ['models_checkup'] },
        { category: 'keys', groups: ['keys_betterstack'] },
      ] },
    { id: 'mod_sleep', icon: 'bedtime', label: 'Сон',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'memory', groups: ['memory_dream'] },
      ] },
    { id: 'mod_nostalgia', icon: 'history', label: 'Ностальгия',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'memory', groups: ['memory_nostalgia'] },
      ] },
    // F3 (10.19, ADR-1019-3 D1): «Бюджеты» — оба контура (ключ чата + фон)
    // и лимит контекста; тумблер безлимита — в спец-блоке (index.html).
    // F21 (10.24, ADR-1024-22 D7): +master-группа flags_module_budgets
    // (зеркало Python-rule; новых вкладок нет).
    { id: 'mod_budgets', icon: 'receipt_long', label: 'Бюджеты',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_budgets'] },
        { category: 'limits', groups: ['limits_chat_key',
            'limits_chat_context', 'limits_worker'] },
      ] },
    // F5 (10.24, ADR-1024-9 D1): отдельный пункт «Генерация изображений» —
    // группа flags_module_images перенесена из mod_direct (провайдер
    // models_images/keys_images остаётся в llm_providers, «один дом»).
    { id: 'mod_images', icon: 'grid_view', label: 'Генерация изображений',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_images'] },
      ] },
    // Список-витрина 11 модулей (не config; карточки + модалки).
    { id: 'modules', icon: 'extension', label: 'Модули', type: 'modules',
      menu: 'modules' },
    // F1 (ADR-1025-1 D1): «Память» — отдельный nav-раздел (не «ИИ»).
    { id: 'memory_rag', icon: 'memory', label: 'Память', type: 'config',
      menu: 'memory',
      sources: [
        { category: 'limits', groups: ['limits_memory', 'limits_graph',
            'limits_rag'] },
        { category: 'flags', groups: ['flags_memory'] },
        { category: 'memory', groups: ['memory_infinite'] },
        { category: 'reactions', groups: ['reactions_memory'] },
      ] },
    // A3/T-1174: «Умный кэш» — отдельный подраздел AI.
    { id: 'smart_cache', icon: 'bolt', label: 'Умный кэш', type: 'config',
      menu: 'ai',
      sources: [
        { category: 'limits', groups: ['limits_smart_cache'] },
        { category: 'flags', groups: ['flags_smart_cache'] },
      ] },
    // Раунд 10.4 (B-11): «Имена людей» — KV-редактор алиасов + per-chat/ЛС.
    { id: 'people_names', icon: 'badge', label: 'Имена', type: 'config',
      menu: 'ai',
      sources: [
        { category: 'limits', groups: ['limits_user_aliases'] },
      ] },
    // Раунд 10.4 (F-1): «Участники и отношения» — кастом-вкладка (свой
    // шаблон, как chat_lore): блок участников активного чата + конфиг-часть
    // (limits_relations/flags_relations через generic-блок; A-канон).
    { id: 'relations', icon: 'group', label: 'Участники и отношения',
      type: 'relations', menu: 'memory',
      sources: [
        { category: 'limits', groups: ['limits_relations'] },
        { category: 'flags', groups: ['flags_relations'] },
      ] },
    // Раунд 10.6 (A2/T-1181): PERMsoc — только простые per-chat функции
    // (13 reactions + 3 flags + 5 limits); 10 миселённых ключей → М5/М6/М7.
    { id: 'permsoc', icon: 'admin_panel_settings', label: 'PERMsoc',
      type: 'config', menu: 'permsoc',
      sources: [
        { category: 'reactions', groups: [
            'reactions_admin', 'reactions_deadpage',
            'reactions_slavik', 'reactions_alan', 'reactions_kostik',
            'reactions_war', 'reactions_common', 'reactions_goodmorning',
            'reactions_mimic', 'reactions_olya',
            'reactions_word_reactions', 'reactions_permsoc'] },
        { category: 'flags', groups: [
            'flags_permsoc', 'flags_media', 'flags_permsoc_behavior'] },
        { category: 'limits', groups: [
            'limits_alan', 'limits_kostik', 'limits_media_permsoc',
            'limits_mimic', 'limits_deadpage'] },
      ] },
    { id: 'access', icon: 'supervisor_account', label: 'Доступы',
      type: 'access', categories: ['access'], menu: 'access' },
    // Раунд 7 (chat-lore-management-v2, spec §3.10/E2): «Лор чатов» — НЕ
    // config-вкладка: свой рендер (index.html) и своя ветка видимости
    // canViewTab (Q6: секция chat_lore / wildcard / непустой probe-список).
    // Раунд 10.4 (A-8, Risk A-2): sources — ТОЛЬКО для рендера config-части
    // (группы limits_lore/flags_lore) через groupedForTab; тип — 'chat_lore'.
    { id: 'chat_lore', icon: 'auto_stories', label: 'Лор чата', type: 'chat_lore',
      menu: 'memory',
      sources: [
        { category: 'limits', groups: ['limits_lore'] },
        { category: 'flags', groups: ['flags_lore'] },
      ] },
    // F1 (T-2394): Статус — единственная главная/стартовая (#/), доступна всем.
    { id: 'status', icon: 'monitoring', label: 'Статус', type: 'status', always: true,
      home: true, menu: 'home' },
    { id: 'info', icon: 'help', label: 'Справка', type: 'info',
      always: true, menu: 'home' },
    // Раунд 10 (F-12): точка интеграции Oversight (только global admin).
    // F1 (Human Gate §8.1): #/oversight сохранён, имя «Аналитика», дубля нет.
    { id: 'oversight', icon: 'radar', label: 'Аналитика', type: 'oversight',
      menu: 'home' },
  ];

  var LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
  var MAX_HISTORY_POINTS = 288;   // B1/T-1129: 24ч × 5 мин
  // 10.10 (п.2, ADR-1010-2): временная сетка графика истории ключей.
  var SAMPLE_BUCKET = 300;        // 5 мин — тот же бакет, что пишет ring
  var MIN_BUCKETS = 12;           // минимум 1 час даже при 1-2 сэмплах
  // D4: порядок секций матрицы прав = порядок config-вкладок (21; §4.3).
  var TAB_SECTION_ORDER = [
    'mod_summary', 'mod_direct', 'mod_factcheck', 'mod_search',
    'mod_transcribe', 'mod_video_summary', 'mod_media_download', 'mod_web',
    'mod_checkup', 'mod_sleep', 'mod_nostalgia', 'mod_budgets', 'mod_images',
    'llm_providers', 'prompts',
    'memory_rag', 'smart_cache', 'people_names', 'relations', 'chat_lore',
    'permsoc',
  ];
  // F6 (ADR-1018-6 D4): фактические navbar-разделы мини-аппа с настройками
  // (Модули/ИИ/PERMsoc) — порядок и подписи для группировки «Матрицы ролей»;
  // зеркало backend NAV_ORDER/NAV_TITLES (services/param_catalog.py).
  var NAV_GROUP_ORDER = ['modules', 'ai', 'memory', 'permsoc'];
  var NAV_GROUP_TITLES = { modules: 'Модули', ai: 'ИИ', memory: 'Память',
    permsoc: 'PERMsoc' };

  // ═══ Material Symbols Rounded — PUA-карта (T-1147/§15.4.4) ═══
  // Субсет без лигатур ⟹ рендер кодпоинтом (ICONS[name] → символ PUA),
  // НЕ текстовым именем. 37 иконок (10.8: +17 новых; паритет с ICON_NAMES,
  // источник — build/icon_codepoints.json, ADR-002).
  var ICONS = {
    admin_panel_settings: '\uef3d',
    auto_stories: '\ue666',
    badge: '\uea67',
    bedtime: '\ue1f9',
    bolt: '\uea0b',
    chevron_right: '\ue409',
    cloud: '\ue2bd',
    delete: '\ue872',
    description: '\ue873',
    dns: '\ue875',
    edit_note: '\ue745',
    expand_more: '\ue5cf',
    extension: '\ue87b',
    grid_view: '\ue9b0',
    group: '\ue7ef',
    help: '\ue887',
    history: '\ue28e',
    key: '\ue73c',
    manage_accounts: '\uf02e',
    memory: '\ue322',
    monitoring: '\uf190',
    play_arrow: '\ue037',
    play_circle: '\ue038',
    psychology: '\uea4a',
    radar: '\uf04e',
    receipt_long: '\uef6e',
    restart_alt: '\uf053',
    save: '\ue161',
    settings: '\ue8b8',
    shield: '\ue75b',
    smart_toy: '\uf06c',
    stop: '\ue047',
    supervisor_account: '\ue1df',
    swap_horiz: '\ue8d4',
    trending_up: '\ue8e5',
    visibility: '\ue417',
    visibility_off: '\ue8f5',
  };
  // tab.id → Material-имя (рендер через tabMat(); fallback — emoji TABS.icon).
  var TAB_ICON = {
    mod_summary: 'description', mod_direct: 'smart_toy',
    mod_factcheck: 'radar', mod_search: 'grid_view',
    mod_transcribe: 'play_circle', mod_video_summary: 'play_circle',
    mod_media_download: 'cloud', mod_web: 'auto_stories',
    mod_checkup: 'monitoring', mod_sleep: 'bedtime',
    mod_nostalgia: 'history', modules: 'extension',
    llm_providers: 'smart_toy', prompts: 'description',
    // F5 (10.24, ADR-1024-9 D5): переиспользуем существующий grid_view
    // (в font-subset) — без правки шрифтового сабсета.
    mod_images: 'grid_view',
    memory_rag: 'memory', smart_cache: 'bolt', people_names: 'badge',
    relations: 'group', permsoc: 'admin_panel_settings',
    access: 'supervisor_account', chat_lore: 'auto_stories',
    status: 'monitoring', info: 'help', oversight: 'radar',
  };

  // ═══ T-1100: navbar — ровно 6 пунктов эталона (§2.1) ═══
  // Навигация только через hash (openTab/navigateTo), не vue-router.
  var NAV_ITEMS = [
    { id: 'status', label: 'Статус', route: '#/', icon: 'monitoring' },
    { id: 'how', label: 'Справка', route: '#/how', icon: 'help' },
    { id: 'modules', label: 'Модули', route: '#/modules', icon: 'extension' },
    { id: 'ai', label: 'ИИ', route: '#/ai', icon: 'smart_toy' },
    { id: 'permsoc', label: 'PERMsoc', route: '#/permsoc',
      icon: 'admin_panel_settings' },
    { id: 'access', label: 'Доступы', route: '#/access',
      icon: 'supervisor_account' },
  ];

  // ═══ F1 (ADR-1025-1 D1/D3): IA v2 — 7 пунктов, 3 уровня ═══
  // legacy NAV_ITEMS выше НЕ трогаем: OFF-режим (IA_V2_ENABLED=false)
  // рендерит его байт-в-байт. group: public | admin | local.
  var NAV_ITEMS_V2 = [
    { id: 'status', label: 'Статус', route: '#/', icon: 'monitoring',
      group: 'public' },
    { id: 'how', label: 'Справка', route: '#/how', icon: 'help',
      group: 'public' },
    { id: 'modules', label: 'Модули', route: '#/modules', icon: 'extension',
      group: 'admin' },
    { id: 'ai', label: 'ИИ', route: '#/ai', icon: 'smart_toy',
      group: 'admin' },
    { id: 'memory', label: 'Память', route: '#/memory', icon: 'memory',
      group: 'admin' },
    { id: 'access', label: 'Доступы', route: '#/access',
      icon: 'supervisor_account', group: 'admin' },
    { id: 'permsoc', label: 'PERMsoc', route: '#/permsoc',
      icon: 'admin_panel_settings', group: 'local' },
  ];

  // Hub-экраны (T-1100, §2.2): карточки → дочерние маршруты. optional
  // `section` — якорь внутри экрана (для #/access/*).
  // Раунд 10.6 (A2): «Модули» — НЕ hub, а список-витрина 11 модулей.
  var HUBS = {
    '#/ai': {
      title: 'ИИ',
      subtitle: 'Провайдеры, промпты, память, кэш, имена и отношения',
      cards: [
        { icon: 'smart_toy', title: 'LLM Провайдеры',
          subtitle: 'Блоки по модулям: base_url, модель, ключ, тест',
          route: '#/ai/llm', tab: 'llm_providers' },
        { icon: 'description', title: 'Промпты',
          subtitle: 'Все системные промпты модулей',
          route: '#/ai/prompts', tab: 'prompts' },
        { icon: 'memory', title: 'Память',
          subtitle: 'Память, граф, хранение, RAG-доли',
          route: '#/ai/memory', tab: 'memory_rag' },
        { icon: 'bolt', title: 'Умный кэш',
          subtitle: 'Exact Match Cache: TTL и строки',
          route: '#/ai/smart-cache', tab: 'smart_cache' },
        { icon: 'badge', title: 'Имена',
          subtitle: 'Имена людей (алиасы, per-chat/ЛС)',
          route: '#/ai/names', tab: 'people_names' },
        { icon: 'group', title: 'Участники и отношения',
          subtitle: 'Участники чата и отношения',
          route: '#/ai/relations', tab: 'relations' },
        { icon: 'auto_stories', title: 'Лор чата',
          subtitle: 'Ручной и авто-лор, история',
          route: '#/ai/lore', tab: 'chat_lore' },
        // Раунд 10.14 (F3 persona-ui-tab-round1014): «Личность» — карточка
        // ведёт на special-screen #/ai/persona (НЕ config-вкладка; Δ каталога 0).
        { icon: 'psychology', title: 'Личность',
          subtitle: 'Имя, биография, характер, осознание ИИ',
          route: '#/ai/persona', tab: 'persona' },
      ],
    },
    '#/access': {
      title: 'Доступы',
      subtitle: 'Матрица ролей, локальные админы, роли',
      cards: [
        { icon: 'admin_panel_settings', title: 'Матрица ролей',
          subtitle: 'Права на параметры: чтение и запись',
          route: '#/access/roles', tab: 'access' },
        { icon: 'group', title: 'Локальные админы',
          subtitle: 'Администраторы активного чата',
          route: '#/access/local', tab: 'access' },
        { icon: 'supervisor_account', title: 'Роли',
          subtitle: 'Суперадмины, модераторы, пользователи',
          route: '#/access/admins', tab: 'access' },
      ],
    },
  };

  // ═══ F1 (ADR-1025-1 D1/D3): хабы IA v2 ═══
  // «ИИ» теряет память/лор/отношения (уехали в «Память»); #/access — тот же.
  var HUBS_V2 = {
    '#/ai': {
      title: 'ИИ',
      subtitle: 'Провайдеры, промпты, кэш, имена и личность',
      // F5 (ADR-1025-15 D2/§47): ровно 5 внутренних страниц в порядке ТЗ.
      // «LLM Провайдеры» → витринное «Модели и подключения» (route/tab НЕ
      // меняются: `#/ai/llm` / `llm_providers`).
      cards: [
        { icon: 'description', title: 'Библиотека промптов',
          subtitle: 'Все системные промпты модулей',
          route: '#/ai/prompts', tab: 'prompts' },
        { icon: 'smart_toy', title: 'Модели и подключения',
          subtitle: 'Блоки по модулям: base_url, модель, ключ, тест',
          route: '#/ai/llm', tab: 'llm_providers' },
        { icon: 'psychology', title: 'Личность и стиль',
          subtitle: 'Имя, биография, характер, осознание ИИ',
          route: '#/ai/persona', tab: 'persona' },
        { icon: 'badge', title: 'Имена и алиасы',
          subtitle: 'Имена людей (алиасы, per-chat/ЛС)',
          route: '#/ai/names', tab: 'people_names' },
        { icon: 'bolt', title: 'Умный кэш',
          subtitle: 'Exact Match Cache: TTL и строки',
          route: '#/ai/smart-cache', tab: 'smart_cache' },
      ],
    },
    '#/memory': {
      title: 'Память',
      subtitle: 'Настройки памяти, лор чатов, люди и связи',
      // F6 (ADR-1025-19 D6/§52–§56): раздел «Память». Сохранены ВСЕ сущест-
      // вующие рендеры: generic `memory_rag` (→ «Настройки памяти», 5 подгрупп
      // Поиск/Граф знаний/Хранение/Ночной синтез/Отношения), `chat_lore`
      // (→ «Лор чатов»), `relations` (→ «Люди и связи»: просмотр людей, НЕ
      // RAG-настройки). Отдельных экранов «Досье»/«Факты» в F6 нет — они
      // покрываются generic-настройками памяти и «Живой лентой досье» в
      // «Аналитике»; новые страницы/маршруты = R16/вне скоупа (см. evidence).
      cards: [
        { icon: 'settings', title: 'Настройки памяти',
          subtitle: 'Поиск, граф знаний, хранение, ночной синтез, отношения',
          route: '#/memory/rag', tab: 'memory_rag' },
        { icon: 'auto_stories', title: 'Лор чатов',
          subtitle: 'Ручной и авто-лор, автогенерация, история',
          route: '#/memory/lore', tab: 'chat_lore' },
        { icon: 'group', title: 'Люди и связи',
          subtitle: 'Участники и отношения (просмотр людей, не RAG-настройки)',
          route: '#/memory/relations', tab: 'relations' },
      ],
    },
    '#/access': HUBS['#/access'],
  };

  // ═══ Раунд 10.6 (A2/T-1165): «Модули» = ровно 11; toggle + окно ═══
  // toggleKey — pg-ключ master-флага (реальный гейт), tab — config-вкладка
  // с операционными группами модуля (generic-рендер в модалке).
  // F4 (10.25, ADR-1025-14 D5): `keywords` — описания/синонимы для поиска
  // (§44), живут в витрине JS (services/param_catalog.py НЕ трогается →
  // Δ каталога = 0). Старые названия оставлены синонимами (маркеры целы).
  // F4 (D3/D6): `runtimeGate` — природа мастер-флага по КОДУ (global →
  // hot.get без чата; per_chat → override→global→default); `parentGate` —
  // глобальный родитель (регистрация роутеров 0a–0i по flags.summary_enabled).
  var MODULES = [
    { id: 'mod_summary', title: 'Сводки чатов',
      subtitle: 'Пересказы разговоров и каналов', icon: 'description',
      toggleKey: 'flags.summary_enabled', tab: 'mod_summary',
      runtimeGate: 'global',
      keywords: ['саммари', 'саммаризация', 'сводка', 'сводки', 'суммаризация',
                 'summary', 'пересказ', 'пересказы'] },
    { id: 'mod_direct', title: 'Ответы в чате',
      subtitle: 'Ответы бота на обращения', icon: 'smart_toy',
      toggleKey: 'flags.direct_chat_botword_enabled', tab: 'mod_direct',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['ответы', 'ответы в чате', 'прямые ответы', 'direct',
                 'botword', 'реплай', 'reply', 'бот'] },
    { id: 'mod_factcheck', title: 'Фактчек',
      subtitle: 'Проверка фактов', icon: 'radar',
      toggleKey: 'flags.factcheck_enabled', tab: 'mod_factcheck',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['фактчек', 'фактчекинг', 'факты', 'проверка фактов',
                 'factcheck', 'check'] },
    { id: 'mod_search', title: 'Поиск',
      subtitle: 'Интернет-поиск', icon: 'grid_view',
      toggleKey: 'flags.search_enabled', tab: 'mod_search',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['поиск', 'найди', 'загугли', 'интернет', 'search', 'google',
                 'гугл'] },
    { id: 'mod_transcribe', title: 'Транскрипт голосовых и видео',
      subtitle: 'Распознавание речи', icon: 'play_circle',
      toggleKey: 'flags.enable_voice_transcription', tab: 'mod_transcribe',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['транскрипт', 'транскрибация', 'голосовые', 'распознавание',
                 'speech', 'stt', 'voice'] },
    { id: 'mod_video_summary', title: 'Выжимка видео',
      subtitle: 'Пересказ видео', icon: 'play_circle',
      toggleKey: 'flags.video_summary_enabled', tab: 'mod_video_summary',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['выжимка', 'видео', 'ютуб', 'youtube', 'video', 'пересказ'] },
    { id: 'mod_media_download', title: 'Скачивание медиа',
      subtitle: 'Скачивание видео по ссылке', icon: 'cloud',
      toggleKey: 'flags.download_enabled', tab: 'mod_media_download',
      runtimeGate: 'global',
      keywords: ['скачивание', 'медиа', 'download', 'видео', 'файлы'] },
    { id: 'mod_web', title: 'Веб-страницы',
      subtitle: 'Пересказ страниц', icon: 'auto_stories',
      toggleKey: 'flags.webpage_enabled', tab: 'mod_web',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['веб', 'веб-страницы', 'страницы', 'web', 'webpage', 'url'] },
    { id: 'mod_checkup', title: 'Диагностика',
      subtitle: 'Чекап, метрики и логи', icon: 'monitoring',
      toggleKey: 'flags.checkup_enabled', tab: 'mod_checkup',
      runtimeGate: 'global', parentGate: 'flags.summary_enabled',
      keywords: ['диагностика', 'чекап', 'метрики', 'логи', 'checkup',
                 'status'] },
    { id: 'mod_sleep', title: 'Сон',
      subtitle: 'Синтез убеждений', icon: 'bedtime',
      toggleKey: 'memory.dream_enabled', tab: 'mod_sleep',
      runtimeGate: 'per_chat',
      keywords: ['сон', 'сны', 'синтез', 'убеждения', 'dream', 'beliefs'] },
    { id: 'mod_nostalgia', title: 'Ностальгия',
      subtitle: '«Кстати…» по старым сообщениям', icon: 'history',
      toggleKey: 'memory.nostalgia_enabled', tab: 'mod_nostalgia',
      runtimeGate: 'per_chat',
      keywords: ['ностальгия', 'nostalgia', 'кстати', 'старые сообщения'] },
    // F3 (10.19, ADR-1019-3 D1): «Бюджеты» — карточка с параметрами раздела
    // (mod_budgets), внутри — тумблер «Безлимит по чату».
    // F21 (10.24, ADR-1024-22 D7): master-тумблер бюджетов (снят noToggle);
    // сохранение — штатным saveConfigItem (global/per-chat через X-Chat-Id).
    { id: 'mod_budgets', title: 'Бюджеты',
      subtitle: 'Лимиты интеллекта и фона, безлимит по чату',
      icon: 'receipt_long', toggleKey: 'flags.budgets_enabled',
      tab: 'mod_budgets', runtimeGate: 'per_chat',
      keywords: ['бюджеты', 'бюджет', 'лимиты', 'безлимит', 'budget',
                 'токены'] },
    // F5 (10.24, ADR-1024-9 D1/D4): отдельная карточка «Генерация
    // изображений» с главным тумблером (default ON); гейт видимости —
    // uiFlag('IMAGE_MODULE_CARD_ENABLED') в computed `visibleModules`.
    { id: 'mod_images', title: 'Генерация изображений',
      subtitle: 'Рисунки по просьбе', icon: 'grid_view',
      toggleKey: 'flags.image_generation_module_enabled', tab: 'mod_images',
      runtimeGate: 'per_chat',
      keywords: ['изображения', 'картинки', 'рисунки', 'генерация', 'image',
                 'generation'] },
  ];

  // ═══ F5 (ADR-1025-15 D1/D6): витринные метаданные workspace-маршрута ═══
  // `routeSlug` и `tabs` живут В JS-витрине (services/param_catalog.py НЕ
  // трогается → Δ каталога = 0). routeSlug = id без префикса `mod_`.
  // `tabs` — применимые вкладки страницы модуля (§46/§4.2 spec.md); вкладка
  // без содержимого не рендерится (`workspaceTabHasContent`).
  var WORKSPACE_TABS = {
    mod_summary: ['overview', 'settings', 'prep', 'clusterizer', 'writer',
      'models', 'limits', 'testing'],
    mod_direct: ['overview', 'settings', 'synthesizer', 'verbalizer', 'models',
      'limits', 'testing'],
    mod_factcheck: ['overview', 'settings', 'synthesizer', 'verbalizer',
      'models', 'limits', 'testing'],
    mod_search: ['overview', 'settings', 'prompts', 'models', 'limits',
      'testing'],
    mod_transcribe: ['overview', 'settings', 'models', 'limits', 'testing'],
    mod_video_summary: ['overview', 'settings', 'prompts', 'models', 'limits',
      'testing'],
    mod_media_download: ['overview', 'settings', 'limits'],
    mod_web: ['overview', 'settings', 'prompts', 'models', 'limits',
      'testing'],
    mod_checkup: ['overview', 'settings', 'prompts', 'models', 'limits',
      'testing'],
    mod_sleep: ['overview', 'settings', 'limits'],
    mod_nostalgia: ['overview', 'settings', 'limits'],
    mod_budgets: ['overview', 'settings', 'limits'],
    mod_images: ['overview', 'settings', 'models', 'testing'],
  };
  MODULES.forEach(function (m) {
    if (!m.routeSlug) m.routeSlug = String(m.id).replace(/^mod_/, '');
    if (!m.tabs) m.tabs = WORKSPACE_TABS[m.id] || ['overview', 'settings'];
  });
  // Тексты вкладок workspace (i18n-канон §46/§85).
  var WORKSPACE_TAB_LABELS = {
    overview: 'Обзор', settings: 'Основные настройки', prompts: 'Промпты',
    synthesizer: 'Синтезатор', verbalizer: 'Вербализатор', models: 'Модели',
    limits: 'Лимиты', testing: 'Тестирование', prep: 'Подготовка сообщений',
    clusterizer: 'Кластеризатор', writer: 'Писатель',
  };
  // Модуль → группа промптов каталога (F5 D3/§48: один объект на два маршрута).
  var MODULE_PROMPT_GROUPS = {
    mod_factcheck: 'prompts_factcheck',
    mod_search: 'prompts_search',
    mod_checkup: 'prompts_checkup',
    mod_direct: 'prompts_direct_chat',
    mod_summary: 'prompts_summary',
    mod_video_summary: 'prompts_youtube',
    mod_web: 'prompts_web',
    mod_sleep: 'prompts_memory',
  };

  // ═══ F5 (ADR-1025-15 D4/§49): 6 групп «Моделей и подключений» ═══
  // Группировка — ВИТРИНА (Δ каталога = 0): каждый блок-подключение
  // (`providerConnectionBlocks`) принадлежит ровно одной группе; advanced
  // блоки (`llm_guard`/`search_keys`/`media_share`) остаются «техническими».
  var PROVIDER_GROUPS = [
    { id: 'prov_text', title: 'Генерация текста', blocks: ['direct'] },
    { id: 'prov_stt', title: 'Распознавание речи', blocks: ['transcription'] },
    { id: 'prov_video', title: 'Видео', blocks: ['video_summary'] },
    { id: 'prov_embeddings', title: 'Эмбеддинги', blocks: ['embeddings'] },
    { id: 'prov_background', title: 'Фоновые задачи',
      blocks: ['intel_history', 'intel_background', 'intel_reflection'] },
    { id: 'prov_images', title: 'Генерация изображений',
      blocks: ['image_generation'] },
  ];
  // Модуль → блоки-подключения для его вкладки «Модели» (§46/§49).
  var MODULE_MODEL_BLOCKS = {
    mod_summary: ['direct'], mod_direct: ['direct'],
    mod_factcheck: ['direct'], mod_search: ['direct'], mod_web: ['direct'],
    mod_transcribe: ['transcription'], mod_video_summary: ['video_summary'],
    mod_checkup: [], mod_images: ['image_generation'],
    mod_sleep: [], mod_nostalgia: [], mod_budgets: [], mod_media_download: [],
  };

  // F6 round1025 (ADR-1025-19 D6 §52–§56): 5 подгрупп витрины «Память →
  // Настройки». Только presentation-level: классификация по ключу параметра,
  // `services/param_catalog.py` НЕ правится (Δ каталога = 0, §116).
  var MEMORY_SUBGROUPS = [
    { id: 'search', title: 'Поиск' },
    { id: 'graph', title: 'Граф знаний' },
    { id: 'storage', title: 'Хранение' },
    { id: 'dream', title: 'Ночной синтез' },
    { id: 'relations', title: 'Отношения' },
    { id: 'other', title: 'Прочее' },
  ];
  // A4/T-1207: «LLM Провайдеры» — блоки ПО МОДУЛЯМ (base_url+model+key).
  // role задаёт, какое поле тела POST /api/llm/test заполняет значение.
  // 10.9 (T-1303): «Название модели» — ПЕРВОЕ поле каждого блока; label'ы —
  // человеческие (spec §4.1/§4.2).
  var PROVIDER_BLOCKS = [
    // Раунд 10.12 (ADR-1012-1 §2.2): parent-блок + subBlocks (как embeddings).
    // main+fallback, groq+openrouter(STT), video primary+fallback — merged
    // в один визуальный блок; id'ы сохранены (их ждут тесты/пробер).
    { id: 'direct', title: 'Прямые ответы', modules: 'Прямые ответы',
      subBlocks: [
        { id: 'direct_main', title: 'Основная модель', modules: 'Прямые ответы',
          fields: [
            { key: 'models.llm_display_name', label: 'Название модели', role: '' },
            { key: 'models.llm_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.llm_model_name', label: 'Модель', role: 'model' },
            { key: 'keys.llm_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
        { id: 'direct_fallback', title: 'Запасная модель',
          modules: 'Прямые ответы (фолбэк)',
          fields: [
            { key: 'models.llm_fallback_display_name', label: 'Название модели', role: '' },
            { key: 'models.llm_fallback_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.llm_fallback_model', label: 'Модель', role: 'model' },
            { key: 'keys.llm_fallback_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    { id: 'transcription', title: 'Транскрибация', modules: 'Транскрибация',
      subBlocks: [
        { id: 'transcribe_groq', title: 'Модель транскрибации',
          modules: 'Транскрибация',
          fields: [
            { key: 'models.groq_display_name', label: 'Название модели', role: '' },
            { key: 'models.groq_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.groq_transcribe_model', label: 'Модель', role: 'model' },
            { key: 'keys.groq_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
        { id: 'transcribe_openrouter', title: 'Запасная модель транскрибации',
          modules: 'Транскрибация (фолбэк)',
          note: 'Адрес и ключ общие с блоком «Саммаризация видео» — один аккаунт OpenRouter',
          fields: [
            { key: 'models.openrouter_transcribe_display_name', label: 'Название модели', role: '' },
            { key: 'models.openrouter_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.openrouter_transcribe_model', label: 'Модель', role: 'model' },
            { key: 'keys.openrouter_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    { id: 'video_summary', title: 'Саммаризация видео',
      modules: 'Саммаризация видео',
      subBlocks: [
        { id: 'video_summary_openrouter', title: 'Саммаризация видео',
          modules: 'Саммаризация видео',
          note: 'Адрес и ключ общие с блоком «Запасная модель транскрибации» — один аккаунт OpenRouter',
          fields: [
            { key: 'models.openrouter_display_name', label: 'Название модели', role: '' },
            { key: 'models.openrouter_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.video_primary_model', label: 'Модель', role: 'model' },
            { key: 'keys.openrouter_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
        { id: 'video_fallback', title: 'Запасная модель саммаризации видео',
          modules: 'Саммаризация видео (фолбэк)',
          fields: [
            { key: 'models.openrouter_display_name', label: 'Название модели', role: '' },
            { key: 'models.openrouter_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.video_fallback_model', label: 'Модель', role: 'model' },
            { key: 'keys.openrouter_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    // 10.11 (spec §2.3, ADR-1011-2): один визуальный блок = ровно 3 подблока
    // (Основная модель / Фоллбэк 1 / Фоллбэк 2); у каждого Base URL + Модель +
    // Ключ + «Проверить». `dim` уходит в «Расширенные» (generic-группа).
    { id: 'embeddings', title: 'Эмбеддинги',
      modules: 'Поиск по памяти',
      subBlocks: [
        { id: 'embeddings_main', title: 'Основная модель',
          modules: 'Поиск по памяти',
          fields: [
            { key: 'models.embedding_display_name', label: 'Название модели', role: '' },
            // Раунд 10.12 (ADR-1012-1 D1): СОБСТВЕННЫЙ адрес/ключ эмбеддингов
            // (не models.llm_base_url / keys.llm_api_key).
            { key: 'models.embedding_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.embedding_model_name', label: 'Модель', role: 'model' },
            { key: 'keys.embedding_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
        { id: 'embeddings_fallback1', title: 'Фоллбэк 1',
          modules: 'Поиск по памяти (фолбэк 1)',
          fields: [
            { key: 'models.embedding_fallback_display_name', label: 'Название модели', role: '' },
            { key: 'models.embedding_fallback_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.embedding_fallback_model', label: 'Модель', role: 'model' },
            { key: 'keys.embedding_fallback_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
        { id: 'embeddings_fallback2', title: 'Фоллбэк 2',
          note: 'Адрес и модель общие с «Фоллбэк 1»',
          modules: 'Поиск по памяти (фолбэк 2)',
          fields: [
            { key: 'models.embedding_fallback2_display_name', label: 'Название модели', role: '' },
            { key: 'models.embedding_fallback_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.embedding_fallback_model', label: 'Модель', role: 'model' },
            { key: 'keys.embedding_fallback_api_key_2', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    // Раунд 10.13 (F4, ADR-1013-1 §2.3): два выделенных LLM для Интеллекта.
    // parent + subBlocks (формат 10.12); id подблоков стабильны (probe).
    // Пустые поля → основная модель (models.llm_* / keys.llm_api_key).
    { id: 'intel_history', title: 'LLM для исторической памяти (Вехи/Лор)',
      modules: 'Вехи и лор чата',
      subBlocks: [
        { id: 'intel_history_main', title: 'Подключение',
          modules: 'Вехи и лор чата',
          fields: [
            { key: 'models.intel_history_display_name', label: 'Название модели', role: '' },
            { key: 'models.intel_history_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.intel_history_model_name', label: 'Модель', role: 'model' },
            { key: 'keys.intel_history_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    { id: 'intel_background', title: 'LLM для фоновых проверок (Оценка важности)',
      modules: 'Оценка важности',
      subBlocks: [
        { id: 'intel_background_main', title: 'Подключение',
          modules: 'Оценка важности',
          fields: [
            { key: 'models.intel_bg_display_name', label: 'Название модели', role: '' },
            { key: 'models.intel_bg_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.intel_bg_model_name', label: 'Модель', role: 'model' },
            { key: 'keys.intel_bg_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    // Раунд 10.14 (F8, UPD п.3, ADR-1013-1 §2.3): третье выделенное
    // подключение — LLM для саморефлексии (Экстрактор сути). parent +
    // subBlocks (формат 10.12); id подблока стабилен (probe).
    // Пустые поля → основная модель (models.llm_* / keys.llm_api_key).
    { id: 'intel_reflection', title: 'LLM для саморефлексии (Экстрактор сути)',
      modules: 'Саморефлексия',
      subBlocks: [
        { id: 'intel_reflection_main', title: 'Подключение',
          modules: 'Саморефлексия',
          fields: [
            { key: 'models.intel_reflection_display_name', label: 'Название модели', role: '' },
            { key: 'models.intel_reflection_base_url', label: 'Адрес сервера', role: 'base_url' },
            { key: 'models.intel_reflection_model_name', label: 'Модель', role: 'model' },
            { key: 'keys.intel_reflection_api_key', label: 'Ключ', role: 'api_key', secret: true },
          ] },
      ] },
    // 10.23 (F5, ADR-1023-5 §D5): генерация изображений — адрес/модель/ключ +
    // чекбокс «Режим GET-запроса» (блокирует ввод ключа: GET идёт анонимно).
    // 10.24 (F12, ADR-1024-4 D3): кнопка «Проверить подключение» → POST
    // /api/images/test (тестовый промпт; тост успех/сырой текст ошибки).
    { id: 'image_generation', title: 'Генерация изображений',
      modules: 'Генерация изображений', testable: true,
      probeEndpoint: '/api/images/test',
      // L4 (review iter1): кнопка проверяет СОХРАНЁННЫЕ адрес/модель/ключ из
      // базы, а не значения полей формы — предупреждаем явно.
      note: '«Проверить подключение» использует сохранённые адрес, модель и '
        + 'ключ из базы — сначала сохраните карточку.',
      fields: [
        { key: 'models.image_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.image_model', label: 'Модель', role: 'model' },
        { key: 'models.image_get_mode', label: 'Режим GET-запроса',
          checkbox: true,
          hint: 'Режим GET-запроса (ключ не используется)' },
        { key: 'keys.image_api_key', label: 'Ключ', role: 'api_key',
          secret: true, globalSecret: true,
          dependsOn: 'models.image_get_mode' },
      ] },
    // 10.11 (spec §2.5, OPEN-Q6): зона «Расширенные настройки».
    { id: 'llm_guard', title: 'Таймауты и защита', modules: 'Общий',
      zone: 'advanced',
      // MAJOR-1: не сетевой провайдер — тест-кнопки нет; значения не
      // отправляются как `model` (role '').
      testable: false,
      fields: [
        { key: 'models.llm_timeout', label: 'Сколько ждать ответ', role: '' },
        { key: 'models.llm_max_retries', label: 'Повторов', role: '' },
        { key: 'models.llm_total_budget', label: 'Общий дедлайн', role: '' },
      ] },
    { id: 'search_keys', title: 'Поиск: ключи', modules: 'Поиск',
      zone: 'advanced',
      // MINOR-2: каждый ключ тестируется ОТДЕЛЬНО (search_keys:tavily/exa).
      perFieldTest: true,
      fields: [
        { key: 'keys.tavily_api_key', label: 'Ключ Tavily', role: 'api_key',
          secret: true, probeTarget: 'search_keys:tavily' },
        { key: 'keys.exa_api_key', label: 'Ключ Exa', role: 'api_key',
          secret: true, probeTarget: 'search_keys:exa' },
      ] },
    { id: 'media_share', title: 'Медиа-шара', modules: 'Саммаризация видео',
      zone: 'advanced',
      note: 'Секретный токен для авторизации бота при скачивании медиафайлов '
        + 'из закрытых источников',
      fields: [
        { key: 'keys.media_share_secret', label: 'Секрет ссылок',
          role: 'api_key', secret: true },
      ] },
  ];

  // ═══ Раунд 10.25 (F7, ADR-1025-20 D1/D2): PERMsoc — 6 функциональных
  // блоков ЛОКАЛЬНОГО пространства чата. Владение — key-level (группы каталога
  // смешивают блоки, Ф13); `groups` — только добор невзятых ключей. «Общее»/
  // «Мастер» больше НЕ owner-блок: мастер выведен в отдельный уровень §61.
  // Новые блоки «Общие реакции»/«Расписания» пишут собственный per-chat
  // блок-гейт (D3, `gate`) и НЕ зависят от мастер-плагина; персональные —
  // `toggleKey` + master. Ключ попадает ровно в один блок (partition-тест).
  var PERMSOC_OWNER_BLOCKS = [
    { id: 'slavik', title: 'Славик', icon: 'smart_toy',
      toggleKey: 'flags.slavik_enabled',
      keys: ['reactions.slavik_user_id',
             'reactions.dead_page_relay_channel_id',
             'reactions.dead_page_source_channel_id',
             'reactions.dead_page_source_channel_username',
             'reactions.dead_page_dir', 'reactions.slavic_random_dir',
             'reactions.gif_path',
             'limits.slavik_mimic_cooldown', 'limits.slavik_mimic_min_words',
             'limits.gif_interval', 'limits.slavic_photo_interval',
             'limits.dead_page_cooldown',
             'limits.dead_page_caption_max_chars',
             'limits.dead_page_max_forward_retries',
             // §62: deprecated, НЕ удалять — код читает legacy-fallback.
             'reactions.slavic_photo_path'],
      groups: ['reactions_slavik', 'reactions_deadpage', 'limits_deadpage'] },
    { id: 'kostik', title: 'Костик', icon: 'smart_toy',
      toggleKey: 'flags.kostik_enabled',
      keys: ['reactions.kostik_user_id', 'reactions.kostik_replies',
             'limits.kostik_reply_probability'],
      groups: ['reactions_kostik', 'limits_kostik'] },
    { id: 'olya', title: 'Оля', icon: 'play_circle',
      toggleKey: 'flags.olya_enabled',
      keys: ['reactions.olya_user_id', 'reactions.olya_saveasbot_channel_ids',
             'reactions.olya_saveasbot_user_ids', 'reactions.olya_media_base',
             'reactions.olya_caption_text', 'reactions.olya_media_type',
             'flags.olya_caption_enabled', 'flags.olya_repost_enabled',
             'flags.olya_always_send',
             'flags.olya_caption_mention_enabled',
             'limits.olya_cooldown'],
      groups: ['reactions_olya'] },
    { id: 'mimic', title: 'Мимикрия', icon: 'psychology',
      toggleKey: 'flags.mimic_enabled',
      keys: ['reactions.mimic_victim_user_ids',
             'reactions.alan_mimic_enabled', 'reactions.kucha_enabled',
             'flags.mimic_forwards_enabled', 'limits.mimic_cooldown',
             'limits.mimic_min_words'],
      groups: ['reactions_mimic', 'reactions_permsoc'] },
    // D3: собственный per-chat блок-гейт (feature_gates), не мастер.
    { id: 'reactions', title: 'Общие реакции', icon: 'forum',
      gate: 'permsoc_reactions',
      keys: ['reactions.alan_user_id', 'reactions.alan_username',
             'reactions.alan_greeting_dir', 'reactions.war_channel_ids',
             'reactions.war_channel_usernames', 'reactions.war_replies',
             'reactions.danger_words', 'reactions.vasya_enabled',
             'flags.alan_replies_enabled', 'flags.dead_page_post_on_join',
             'reactions.admin_user_id', 'reactions.common_media_base',
             'flags.common_media_enabled', 'flags.common_work_media_enabled'],
      groups: ['reactions_alan', 'reactions_war', 'reactions_common',
               'reactions_admin', 'reactions_word_reactions',
               'flags_permsoc_behavior', 'flags_media'] },
    { id: 'schedule', title: 'Расписания', icon: 'schedule',
      gate: 'permsoc_schedule',
      keys: ['reactions.goodmorning_time', 'reactions.goodmorning_media_dir',
             'reactions.goodmorning_target_chat_ids',
             'reactions.goodmorning_tz',
             'limits.alan_reply_interval', 'limits.alan_greeting_cooldown',
             'limits.alan_silence_greeting_hours', 'limits.danger_cooldown',
             'limits.selfdev_cooldown', 'limits.work_cooldown',
             'limits.common_cooldown'],
      groups: ['reactions_goodmorning', 'limits_alan',
               'limits_media_permsoc'] },
  ];
  // D5: русские названия/порядок подгрупп внутри блока (§62–§67) —
  // presentation-level (каталог не правим; Δ каталога=0). Каждая подгруппа —
  // {title, keys}: `keys` — те же ключи, что в `keys` owner-блока, разложенные
  // по §-подгруппам (Основное/Контент/Мимикрия/…). Объединение всех `keys`
  // подгрупп == `keys` блока (partition-тест). Рендер — `permsocRenderItems`.
  var PERMSOC_BLOCK_SUBGROUPS = {
    slavik: [
      { title: 'Основное', keys: ['reactions.slavik_user_id'] },
      { title: 'Контент', keys: [
        'reactions.dead_page_relay_channel_id',
        'reactions.dead_page_source_channel_id',
        'reactions.dead_page_source_channel_username',
        'reactions.dead_page_dir', 'reactions.slavic_random_dir',
        'reactions.gif_path'] },
      { title: 'Мимикрия', keys: [
        'limits.slavik_mimic_cooldown', 'limits.slavik_mimic_min_words'] },
      { title: 'Ограничения', keys: [
        'limits.gif_interval', 'limits.slavic_photo_interval',
        'limits.dead_page_cooldown', 'limits.dead_page_caption_max_chars',
        'limits.dead_page_max_forward_retries'] },
      { title: 'Дополнительно', keys: ['reactions.slavic_photo_path'] },
    ],
    kostik: [
      { title: 'Основное', keys: ['reactions.kostik_user_id'] },
      { title: 'Ответы', keys: ['reactions.kostik_replies'] },
      { title: 'Ограничения', keys: ['limits.kostik_reply_probability'] },
    ],
    olya: [
      { title: 'Основное', keys: ['reactions.olya_user_id'] },
      { title: 'Источники', keys: [
        'reactions.olya_saveasbot_channel_ids',
        'reactions.olya_saveasbot_user_ids'] },
      { title: 'Ответы', keys: [
        'reactions.olya_media_base', 'reactions.olya_caption_text',
        'reactions.olya_media_type', 'flags.olya_caption_enabled',
        'flags.olya_repost_enabled', 'flags.olya_always_send',
        'flags.olya_caption_mention_enabled'] },
      { title: 'Ограничения', keys: ['limits.olya_cooldown'] },
    ],
    mimic: [
      { title: 'Кого передразнивать', keys: ['reactions.mimic_victim_user_ids'] },
      { title: 'Реакции', keys: [
        'reactions.alan_mimic_enabled', 'reactions.kucha_enabled'] },
      { title: 'Пересланные', keys: ['flags.mimic_forwards_enabled'] },
      { title: 'Пауза', keys: ['limits.mimic_cooldown'] },
      { title: 'Длина', keys: ['limits.mimic_min_words'] },
    ],
    reactions: [
      { title: 'Приветствия', keys: [
        'reactions.alan_user_id', 'reactions.alan_username',
        'reactions.alan_greeting_dir'] },
      { title: 'Оповещения', keys: [
        'reactions.war_channel_ids', 'reactions.war_channel_usernames',
        'reactions.war_replies'] },
      { title: 'Триггеры', keys: [
        'reactions.danger_words', 'reactions.vasya_enabled',
        'flags.alan_replies_enabled', 'flags.dead_page_post_on_join',
        'reactions.admin_user_id'] },
      { title: 'Медиа', keys: [
        'reactions.common_media_base', 'flags.common_media_enabled',
        'flags.common_work_media_enabled'] },
    ],
    schedule: [
      { title: 'Рассылка', keys: [
        'reactions.goodmorning_time',
        'reactions.goodmorning_target_chat_ids',
        'reactions.goodmorning_tz'] },
      { title: 'Медиа', keys: ['reactions.goodmorning_media_dir'] },
      { title: 'Доп. ограничения', keys: [
        'limits.alan_reply_interval', 'limits.alan_greeting_cooldown',
        'limits.alan_silence_greeting_hours', 'limits.danger_cooldown',
        'limits.selfdev_cooldown', 'limits.work_cooldown',
        'limits.common_cooldown'] },
    ],
  };
  // M-F7-2 (§64): presentation-оверрайд виджета. В каталоге списки ID Оли —
  // `type=json, widget=''` (Δ каталога=0, не меняем): в UI рендерим
  // структурированный `list-editor` (строки/чипы), а не сырой textarea/CSV.
  var PERMSOC_LIST_WIDGET_KEYS = {
    'reactions.olya_saveasbot_channel_ids': true,
    'reactions.olya_saveasbot_user_ids': true,
  };
  // Ключи-тумблеры рендерятся ТОЛЬКО в <summary> owner-блоков; мастер
  // выведен в отдельный уровень §61 (не в тело блока).
  var PERMSOC_TOGGLE_KEYS = {
    'flags.permsoc_enabled': true, 'flags.slavik_enabled': true,
    'flags.kostik_enabled': true,
    'flags.olya_enabled': true, 'flags.mimic_enabled': true,
  };
  // D1-защита записи: набор PERMsoc-ключей (мастер + тумблеры блоков + все
  // ключи §62–§67). Попытка записи любого из них при scope=global
  // блокируется (persistItems/saveConfigItem) — §4/§60 «не глобальная
  // конфигурация». Строится из PERMSOC_OWNER_BLOCKS (единый источник).
  var PERMSOC_LOCAL_KEYS = (function () {
    var m = {};
    Object.keys(PERMSOC_TOGGLE_KEYS).forEach(function (k) { m[k] = true; });
    PERMSOC_OWNER_BLOCKS.forEach(function (o) {
      (o.keys || []).forEach(function (k) { m[k] = true; });
    });
    return m;
  })();

  // UI-полировка TMA (fix-раунд ревью): blob-аватары через прокси.
  // Прямой <img :src="'/api/avatar/...'"> НЕ работает: картинку грузит
  // браузер БЕЗ X-Telegram-Init-Data → 401. avatarUrl() ходит fetch'ем с
  // заголовком initData → blob → URL.createObjectURL; URL кладётся в
  // реактивное поле (chat.avatarUrl/u.avatarUrl/meAvatarUrl), img рисуется
  // только через v-if. Кэш {kind:id → objectURL} — ТОЛЬКО успешные загрузки
  // (негатив не кэшируем: ре-рендер/ре-авторизация смогут попробовать
  // снова); лимит ~200 URL, при переполнении revoke самого старого.
  var _avatarCache = new Map();
  var _AVATAR_CACHE_MAX = 200;

  // ═══ F4 (graph-physics-stabilization-round1018, ADR-1018-4) ═══
  // Физика графа: короткая стабилизация (150 итераций вместо 250) и
  // авто-отключение physics после первичной расстановки по событию
  // stabilizationIterationsDone/stabilized → ~60 FPS при 500–800 узлах (F3).
  // Каталог-Δ=0 — только код-константы (маркеры JS-тестов).
  var GRAPH_PHYSICS_ITERATIONS = 150;
  var GRAPH_PHYSICS_DISABLE_ON_STABILIZE = true;

  function arr(x) { return Array.isArray(x) ? x : []; }

  // ═══ Hash-routing (T-1099, OD1/OD3/§6.3): route — источник истины ═══
  // Маршрут — ТОЛЬКО hash, начинающийся с '#/' (launch-hash tgWebAppData
  // игнорируется, §6.1/§6.2). vue-router НЕ используется (zero-build).
  // Ниже — чистые функции (routeToTab/tabToRoute/routeParent/routeDepth),
  // покрываются маркер-тестом test_webapp_back_button.
  var ROUTE_TO_TAB = {
    '#/': 'status',
    // F11 (10.25, ADR-1025-23 D4): аддитивный маршрут полного исследования
    // графа связей (mobile §16). Владелец routing — F1; родитель — `#/`.
    '#/status/graph': 'status',
    '#/oversight': 'oversight',
    '#/how': 'info',
    '#/modules': 'modules',
    // F3 (10.19, ADR-1019-3 D1): раздел «Бюджеты» в «Модулях».
    '#/modules/budgets': 'mod_budgets',
    // F5 (10.24, ADR-1024-9 review iter1): вкладка «Генерация изображений»
    // получила канонический маршрут (симметрично «Бюджетам»); при OFF
    // kill-switch `applyRoute` откатывает её на витрину `#/modules`.
    '#/modules/images': 'mod_images',
    '#/permsoc': 'permsoc',
    '#/ai': 'llm_providers',
    '#/ai/llm': 'llm_providers',
    '#/ai/prompts': 'prompts',
    '#/ai/smart-cache': 'smart_cache',
    '#/ai/names': 'people_names',
    // F1 (ADR-1025-1 D3): legacy-маршруты остаются валидными (алиасы ниже),
    // канонический дом «Памяти» — #/memory/*.
    '#/ai/memory': 'memory_rag',
    '#/ai/relations': 'relations',
    '#/ai/lore': 'chat_lore',
    '#/memory': 'memory_rag',
    '#/memory/rag': 'memory_rag',
    '#/memory/lore': 'chat_lore',
    '#/memory/relations': 'relations',
    // F3 (10.14): special-screen «Личность» (не зеркалит TABS/TAB_RULES).
    '#/ai/persona': 'persona',
    '#/access': 'access',
    '#/access/roles': 'access',
    '#/access/local': 'access',
    '#/access/admins': 'access',
    // Удалённые роуты → алиасы (spec §3.2): не 404, ведут в новый дом.
    '#/ai/limits': 'llm_providers',
    '#/ai/sleep': 'modules',
    '#/ai/nostalgia': 'modules',
    '#/modules/features': 'modules',
    '#/modules/switches': 'modules',
    '#/modules/reactions': 'modules',
    '#/modules/custom': 'modules',
  };
  var TAB_TO_ROUTE = {
    status: '#/', info: '#/how', oversight: '#/oversight',
    modules: '#/modules', permsoc: '#/permsoc',
    mod_budgets: '#/modules/budgets',
    mod_images: '#/modules/images',
    llm_providers: '#/ai/llm', prompts: '#/ai/prompts',
    // F1 (ADR-1025-1 D3): «Память» живёт в своём разделе.
    memory_rag: '#/memory/rag', smart_cache: '#/ai/smart-cache',
    people_names: '#/ai/names', relations: '#/memory/relations',
    chat_lore: '#/memory/lore', access: '#/access',
    // F3 (10.14): persona — special-screen маршрут (нет записи в TABS).
    persona: '#/ai/persona',
  };
  var ROOT_ROUTES = ['#/', '#/how', '#/modules', '#/permsoc', '#/ai',
    '#/memory', '#/access'];
  // MINOR-1: удалённые роуты → канонический hash (spec §3.2). applyRoute
  // делает replaceState, чтобы адресная строка не несла legacy-путь.
  var ROUTE_ALIAS = {
    '#/ai/limits': '#/ai',
    '#/ai/sleep': '#/modules',
    '#/ai/nostalgia': '#/modules',
    // F1 (ADR-1025-1 D3): старые «дом-в-ИИ» маршруты памяти → «Память».
    '#/ai/memory': '#/memory',
    '#/ai/lore': '#/memory/lore',
    '#/ai/relations': '#/memory/relations',
    '#/modules/features': '#/modules',
    '#/modules/switches': '#/modules',
    '#/modules/reactions': '#/modules',
    '#/modules/custom': '#/modules',
  };
  var ROUTE_PARENT = {
    // F11 (10.25, ADR-1025-23 D4): полный граф — дочерний экран «Статуса».
    '#/status/graph': '#/',
    '#/oversight': '#/',
    '#/ai/llm': '#/ai', '#/ai/prompts': '#/ai',
    '#/ai/smart-cache': '#/ai', '#/ai/names': '#/ai',
    '#/ai/persona': '#/ai',   // F3 (10.14)
    // F1 (ADR-1025-1 D3/D6): подстраницы «Памяти» → родитель-хаб #/memory.
    '#/memory/rag': '#/memory', '#/memory/lore': '#/memory',
    '#/memory/relations': '#/memory',
    '#/access/roles': '#/access', '#/access/local': '#/access',
    '#/access/admins': '#/access',
    '#/modules/budgets': '#/modules',
    '#/modules/images': '#/modules',
  };

  // ═══ F5 (ADR-1025-15 D1/D6): динамический резолвер workspace-маршрутов ═══
  // Грамматика: `#/modules/<slug>[/<wt>[/<stage>/<promptKey>]]`. Резолвер
  // распознаёт ЛЮБОЙ `<slug>` ∈ MODULES[].routeSlug, НЕ перечисляя 13 записей
  // в статической карте. Существующие `#/modules/budgets|images` совместимы
  // (они уже в ROUTE_TO_TAB → обрабатываются раньше).
  function parseWorkspaceRoute(route) {
    var r = String(route || '').split('?')[0];
    if (r.indexOf('#/modules/') !== 0) return null;
    var parts = r.substring('#/modules/'.length).split('/').filter(Boolean);
    if (!parts.length) return null;
    return { slug: parts[0] || '', tab: parts[1] || '',
             stage: parts[2] || '', promptKey: parts[3] || '' };
  }
  function isWorkspaceRoute(route) {
    return parseWorkspaceRoute(route) !== null;
  }
  // D3/§48: «ИИ → Библиотека промптов → <slug>/<stage>» — вторая дверь в ту
  // же комнату (`#/ai/prompts/<slug>[/<stage>]`).
  function parsePromptLibraryRoute(route) {
    var r = String(route || '').split('?')[0];
    if (r.indexOf('#/ai/prompts/') !== 0) return null;
    var parts = r.substring('#/ai/prompts/'.length).split('/').filter(Boolean);
    if (!parts.length) return null;
    var stage = parts[1] || '';
    var promptKey = parts[2] || '';
    // `#/ai/prompts/<slug>/<stage>/<promptKey>` — фокус промпта (M-F5S-1).
    // Для модуля без промежуточного stage ключ config-item (`prompts.*`)
    // занимает слот stage: этапы (`synthesizer`/`verbalizer`) так выглядеть
    // не могут, поэтому префикс `prompts.` однозначен.
    if (stage && stage.indexOf('prompts.') === 0) {
      promptKey = stage; stage = '';
    }
    return { slug: parts[0] || '', stage: stage, promptKey: promptKey };
  }
  function _wsModuleById(slug) {
    if (!slug) return null;
    for (var i = 0; i < MODULES.length; i++) {
      var m = MODULES[i];
      var s = m.routeSlug || String(m.id || '').replace(/^mod_/, '');
      if (s === slug) return m;
    }
    return null;
  }
  // D3/§48: вкладка промптов модуля для второй двери (библиотеки). Приоритет
  // объявленных вкладок; `prompts` — логический дефолт (mod_summary и др.).
  function _workspacePromptTabOf(m) {
    var declared = (m && m.tabs) || [];
    var order = ['prompts', 'synthesizer', 'verbalizer'];
    for (var i = 0; i < order.length; i++) {
      if (declared.indexOf(order[i]) >= 0) return order[i];
    }
    return 'prompts';
  }
  // §4.3 п.2 (T-2700): вкладка применима по СТАТИЧЕСКОЙ витрине (не требует
  // данных конфига). `testing` показывается только если у модуля есть
  // тестируемые подключения (`MODULE_MODEL_BLOCKS`); пустая вкладка не рендерится.
  function _workspaceTabApplicable(m, tabId) {
    if (!m || !tabId) return false;
    if ((m.tabs || []).indexOf(tabId) < 0) return false;
    if (tabId === 'testing') {
      return (MODULE_MODEL_BLOCKS[m.id] || []).length > 0;
    }
    return true;
  }

  // F5 (ADR-1025-15 D4/§49, T-2714): карточка подключения.
  // Значения — ТОЛЬКО из существующей структуры `PROVIDER_BLOCKS`/`models_*`
  // через `blockFieldValue` (сохранённое значение, без подстановки дефолта —
  // §49 «не менять сохранённую модель при открытии»). Секреты (`keys.*`) в
  // карточку как значения не выводятся (F9/§46): поля-секреты пропускаются.
  // «Настроить» раскрывает существующую форму блока (reuse `saveBlock`),
  // «Проверить» — существующий `testBlock` (reuse эндпоинтов).
  function buildConnectionCard(ctx, b) {
    if (!b) return null;
    var subs = (b.subBlocks && b.subBlocks.length) ? b.subBlocks : [];
    var primary = subs.length ? subs[0] : b;
    var fallback = subs.length > 1 ? subs[1] : null;
    function modelOf(blk) {
      if (!blk) return '';
      var fields = blk.fields || [];
      for (var i = 0; i < fields.length; i++) {
        // role === 'model' — «Модель»; секреты роли `api_key` не читаем.
        if (fields[i].role === 'model') {
          var v = ctx.blockFieldValue ? ctx.blockFieldValue(fields[i]) : '';
          return (v == null) ? '' : String(v);
        }
      }
      return '';
    }
    var results = ctx.blockResults || {};
    var testing = ctx.blockTesting || {};
    var res = results[primary.id] || results[b.id] || null;
    var isTesting = !!(testing[primary.id] || testing[b.id]);
    var status;
    if (isTesting) {
      status = { ok: null, text: 'Проверка…' };
    } else if (res) {
      status = { ok: !!res.ok,
                 text: (res.ok ? 'Подключение OK' : 'Ошибка')
                       + (res.text ? ' · ' + res.text : '') };
    } else {
      status = { ok: null, text: 'Не проверено' };
    }
    return {
      id: b.id,
      block: b,
      title: b.title,
      display: ctx.blockDisplayName ? (ctx.blockDisplayName(b) || '') : '',
      purpose: b.modules || b.title || '',
      note: b.note || '',
      primary: modelOf(primary),
      primaryLabel: primary.title || 'Основная модель',
      fallback: modelOf(fallback),
      fallbackLabel: fallback ? (fallback.title || 'Резервная модель') : '',
      hasFallback: !!fallback,
      status: status,
      testTarget: primary,
      canTest: b.testable !== false,
    };
  }

  // Маршрут валиден ТОЛЬКО если hash начинается с '#/' (иначе launch-hash).
  function normalizeRoute(hash) {
    if (typeof hash !== 'string') return null;
    if (hash.indexOf('#/') !== 0) return null;
    var r = hash.split('?')[0];           // отбросить query после маршрута
    if (Object.prototype.hasOwnProperty.call(ROUTE_TO_TAB, r)) return r;
    // F5: динамические workspace/prompt-library маршруты (без статической карты).
    if (isWorkspaceRoute(r)) return r;
    if (parsePromptLibraryRoute(r)) return r;
    return null;
  }
  function routeToTab(route) {
    var r = normalizeRoute(route);
    if (r && !Object.prototype.hasOwnProperty.call(ROUTE_TO_TAB, r)) {
      var ws = parseWorkspaceRoute(r);
      if (ws) {
        var m = _wsModuleById(ws.slug);
        if (m && m.tab) return m.tab;   // RBAC + kill-switch работают как были
      }
      // D3/§48: вторая дверь `#/ai/prompts/<slug>[/<stage>]` открывает
      // Библиотеку промптов (tab `prompts`); фокус модуля выводит
      // производное `workspace` из того же hash.
      if (parsePromptLibraryRoute(r)) return 'prompts';
    }
    return ROUTE_TO_TAB[r || '#/'] || 'status';
  }
  function tabToRoute(tabId) {
    return TAB_TO_ROUTE[tabId] || '#/';
  }
  function routeParent(route) {
    var r = normalizeRoute(route);
    if (!r || ROOT_ROUTES.indexOf(r) >= 0) return null;
    var ws = parseWorkspaceRoute(r);
    if (ws) {
      if (!_wsModuleById(ws.slug)) return '#/modules';
      if (ws.promptKey) return '#/modules/' + ws.slug + '/' + ws.stage;
      if (ws.tab) return '#/modules/' + ws.slug;
      return '#/modules';
    }
    var pl = parsePromptLibraryRoute(r);
    if (pl) {
      if (pl.promptKey && pl.stage) {
        return '#/ai/prompts/' + pl.slug + '/' + pl.stage;
      }
      if (pl.promptKey) return '#/ai/prompts/' + pl.slug;
      return pl.stage ? ('#/ai/prompts/' + pl.slug) : '#/ai/prompts';
    }
    return ROUTE_PARENT[r] || '#/';
  }
  function routeDepth(route) {
    var r = normalizeRoute(route);
    if (!r || ROOT_ROUTES.indexOf(r) >= 0) return 0;
    var base = routeParent(route) ? 1 : 0;
    var ws = parseWorkspaceRoute(r);
    if (ws && _wsModuleById(ws.slug) && (ws.tab || ws.promptKey)) {
      return base + 1;                 // 0/1/2: каталог ← модуль ← вкладка
    }
    return base;
  }
  // D1: hub-роут доступен, если видна ХОТЯ БЫ ОДНА его карточка. НЕ гейтим
  // hub по одному «представительскому» tab (иначе роль с правами только на
  // prompts/limits получала редирект с #/ai).
  // F1: `hubs` — активная карта (HUBS_V2 при IA v2, иначе legacy HUBS).
  function hubVisible(route, canViewTab, hubs) {
    var hub = (hubs || HUBS)[route];
    if (!hub) return false;
    return hub.cards.some(function (c) {
      return !c.tab || canViewTab(c.tab);
    });
  }

  // OD13: deep-link OFF (start_param в маршрутизацию НЕ вовлекается).
  if (window.__TMA_BACK__ === undefined) window.__TMA_BACK__ = true;
  if (window.__TMA_DEEPLINK__ === undefined) window.__TMA_DEEPLINK__ = false;

  // BOOT (T-1099/§6.2 п.1): читаем и кэшируем initData ДО любой записи hash.
  function getInitData() {
    try {
      var d = (window.Telegram && Telegram.WebApp && Telegram.WebApp.initData) || '';
      if (d) {
        try { sessionStorage.setItem('adminbot.initData', d); } catch (e) { /* quota */ }
        return d;
      }
    } catch (e) { /* вне TG */ }
    try { return sessionStorage.getItem('adminbot.initData') || ''; } catch (e2) { return ''; }
  }

  // Стартовый маршрут: наш hash → sessionStorage → '#/'.
  function initialRoute() {
    var h = normalizeRoute(window.location.hash);
    if (h) return h;
    // F1 (T-2396): явный, но неизвестный hash '#/…' → Статус (без падения),
    // а не восстанавливаем saved-маршрут (иначе мусор не приводил бы к '#/').
    if (typeof window.location.hash === 'string' &&
        window.location.hash.indexOf('#/') === 0) return '#/';
    try {
      var saved = normalizeRoute(sessionStorage.getItem('adminbot.route'));
      if (saved) return saved;
    } catch (e) { /* quota */ }
    return '#/';
  }

  // 10.11 (Scanner LOW): ключ localStorage для аккордеонов. Без scope —
  // исторический `adminbot.expand:<tab>` (обратная совместимость); со scope —
  // отдельный стабильный ключ (внешняя зона vs inner-группы).
  function _expandKey(tabId, scope) {
    return 'adminbot.expand:' + tabId + (scope ? ':' + scope : '');
  }

  // Router-состояние — НЕ в data()/реактивности: нативный BackButton-объект
  // нельзя оборачивать в reactive-proxy, а _-поля инстанса Vue не проксирует.
  var _appVm = null;
  var _backApi = null;
  var _boundBackApi = null;   // R10.5-1: к какому объекту уже привязан onClick
  var _routeApplied = false;
  var _onHashChange = null;
  var _onResize = null;       // F1 (§6/§7): пересчёт shell-режима
  var _onVV = null;           // HOTFIX10: visualViewport → resize OGL-фона
  var _onKeydown = null;      // MODERATE-2: глобальный Esc (закрытие модалки)
  var _onVisibility = null;   // F5-Q3: пауза cognition-polling при hidden
  // F24 (ADR-1024-24 D1/C3): подписки на TMA-fullscreen-события. Ссылки на
  // колбэки храним модульно — `offEvent` в beforeUnmount должен получить
  // РОВНО ТУ ЖЕ функцию (иначе listener не снимается).
  var _fsSubscribed = false;  // guard: подписки установлены ровно один раз
  var _fsOnFullscreen = null;
  var _fsOnViewport = null;
  // HOTFIX10 (ADR-1025-18 D5, T-2857): пересчёт геометрии OGL-фона по
  // фактическому размеру контейнера. Безопасный no-op вне/без библиотеки.
  function _auroraResize() {
    try {
      if (window.__AuroraFlow && typeof window.__AuroraFlow.resize === 'function') {
        window.__AuroraFlow.resize();
      }
    } catch (e) { /* no-op */ }
  }
  // round 10.26 (ADR-1026-3 D1/D4): исходный Dark Aurora Flow сохранён модулем
  // `polygon-background.js` как `__AuroraFlowLegacy` (публичный `__AuroraFlow`
  // подменён совместимым фасадом Polygon). `_syncBgLayer` выбирает ровно один
  // активный рендерер по матрице §4.2: ON → Polygon, OFF → legacy Aurora.
  function _legacyAuroraFlow() {
    try {
      if (window.__AuroraFlowLegacy
          && typeof window.__AuroraFlowLegacy.start === 'function') {
        return window.__AuroraFlowLegacy;
      }
      var f = window.__AuroraFlow;
      if (f && !f.__polygonAdapter && typeof f.start === 'function') return f;
    } catch (e) { /* no-op */ }
    return null;
  }
  // Категории вкладки для RBAC-проверок: явный список (не-конфиг вкладки)
  // либо уникальные категории источников (конфиг вкладки).
  function tabCategories(tab) {
    if (!tab || !tab.sources) return arr(tab && tab.categories);
    var out = [];
    tab.sources.forEach(function (s) {
      if (out.indexOf(s.category) < 0) out.push(s.category);
    });
    return out;
  }

  // 3.5.2: id считается числовым, если целиком из цифр (иначе null).
  // Используется warnText KV-редактора («нечисловые ID сохранятся как
  // строки»). Сортировка пар — НЕ здесь: sync() сохраняет порядок объекта.
  function numericId(id) {
    var s = String(id).trim();
    if (!/^\d+$/.test(s)) return null;
    return parseInt(s, 10);
  }

  var app = Vue.createApp({
    data: function () {
      return {
        tabs: TABS,
        activeTab: 'status',
        openModuleId: null,       // A2/T-1167: открытая модалка параметров
        modules: MODULES,
        // ── F4 (10.25, ADR-1025-14 D1/D2): ModuleConfigurationStore ──
        // Канонический источник значений — существующий `configItems`
        // (loadConfig → GET /api/config). Store добавляет ТОЛЬКО «оверлей
        // операции»: оптимистичное значение в полёте (moduleOptimistic),
        // блокировку повтора (modulePending) и понятную ошибку по ключу
        // (moduleSaveError). Копий конфигурации на визуальный экземпляр нет.
        // Ключ — `scope_type/scope_id/module_id` (§38).
        moduleOptimistic: {},     // storeKey → { value, opId } (только в полёте)
        modulePending: {},        // storeKey → true (in-flight)
        moduleSaveError: {},      // storeKey → понятный текст ошибки
        // F4 (D4/§34–§36): избранное — UI-предпочтение (localStorage), НЕ
        // конфигурация бота; не включает/выключает модуль. Fail-open.
        moduleQuickpicks: null,   // string[] id модулей (init в created/loadMe)
        moduleQuickpicksOpen: false,   // «Все избранные» раскрыты
        // F4 (D5/§32/§44): поиск/фильтр каталога — представление.
        moduleSearch: '',
        moduleFilter: 'all',      // all|on|off|issues|picks
        // A4/T-1207: LLM-блоки по модулям + черновики/результаты теста.
        providerBlocks: PROVIDER_BLOCKS,
        blockDrafts: {},
        blockResults: {},
        blockTesting: {},
        blockSaving: {},
        // F5 (ADR-1025-15 D4/§49, T-2714): раскрытие формы настроек карточки
        // подключения («Настроить»). Значение — только UI-состояние раскрытия;
        // сохранение идёт существующим F0 write-path (`saveBlock`).
        connectionSettingsOpen: {},
        // F-11/F24 (ADR-1024-24 D2): РЕАКТИВНЫЙ стейт аккордеонов — единственный
        // источник рендера `:open` (computed advancedOpen/provAdvancedOpen/
        // chatLoreAdvancedOpen). localStorage `adminbot.expand:<tab>[:<scope>]` —
        // только персист; инициализация — initExpandState() в created().
        expand: {},
        // T-1099: hash-роутер — route (@see #6.3), backNative — есть ли
        // нативный Telegram.WebApp.BackButton (иначе in-app fallback ←).
        route: '#/',
        backNative: false,
        // F1 (§6/§7): shell-режим по ширине вьюпорта:
        // mobile <768 | compact 768–1199 | desktop ≥1200.
        shellMode: (typeof window !== 'undefined' && window.innerWidth)
          ? (window.innerWidth < 768 ? 'mobile'
            : (window.innerWidth < 1200 ? 'compact' : 'desktop'))
          : 'desktop',
        drawerOpen: false,   // 768–1199: временная навигация (не персистится)
        moreOpen: false,     // <768: шторка «Ещё» в нижней навигации
        helpQuery: '',       // T-2400: поиск по «Справке» (mobile)
        me: null,
        authError: null,
        authLocked: false,
        // Раунд 10 (F-7 T-854, F-7 T-906): контекст чата — активный `activeChatId`
        // (persist localStorage 'adminbot.active_chat_id'), api() добавляет
        // X-Chat-Id; NULL → ровно старое поведение (глобальный конфиг).
        activeChatId: null,
        accessChats: [],              // GET /api/access/chats (селектор F-11)
        accessMy: null,               // GET /api/access/me
        // S9 round1026 (ADR-1026-8 D1/D3, §113): dry-run «Тестирование» пайплайна
        // Сводок чатов. available=null → probe ещё не выполнен (секция скрыта).
        summaryTest: {
          available: null,
          chatId: null,
          hours: 24,
          running: false,
          testId: null,
          result: null,
          error: '',
          coverBusy: false,
          cover: null,
        },
        // A9/T-1206/10.8: «Доступы» — id открытого окна подраздела (route-driven).
        accessOpen: null,             // null | 'roles' | 'local' | 'admins'
        activeChatTitle: 'Весь бот',  // индикатор активного скоупа в шапке
        // T-1127/§15.1.1: явный вид скоупа + epoch — токен отбрасывания
        // устаревших in-flight ответов при смене scope (R10.4-2).
        scopeEpoch: 0,
        // T-1127 (§15.1.3): кастомный a11y-dropdown (listbox) с аватарами.
        scopeOpen: false,
        scopeSearch: '',
        scopeFocus: -1,
        // F6 round 10.21 (T-1993/L-4): коллизионное позиционирование панели
        // выбора контекста (иначе при коротком заголовке вкладки `right:0` +
        // min-width 260px выводил панель за левый край вьюпорта).
        scopePanelStyle: {},
        // Роль-пикер (F-7 T-855): модалка per-param прав (global admin).
        // Ре-дизайн 10.2, BUG-6 (spec §3.2.1): флаги «Чтение»/«Запись» —
        // чекбоксы user/moderator/local_admin; global admin — неявно.
        permPickerOpen: false,
        permPickerItem: null,
        permPicker: {
          viewRoles: { user: false, moderator: false, local_admin: false },
          editRoles: { user: false, moderator: false, local_admin: false },
        },
        permPickerSaving: false,
        // OD10/T-1130 (раунд 10.5): визуальная матрица ролей — ВСЕ параметры
        // по секциям мини-аппа, per-param read/write (global admin).
        matrixItems: {},
        matrixLoading: false,
        matrixError: '',
        matrixSearch: '',
        matrixSaving: {},
        // BYOK-UI (F-7 T-856): ключ чата — для локального админа
        ownKeyDraft: '',
        ownKeySaving: false,
        keyStatusOwn: null,           // GET /api/config/keys/status
        // «Доступы» (F-7 T-857): локальные админы активного чата
        chatLocalAdmins: [],
        chatLocalAdminsBusy: false,
        newLocalAdminId: '',
        newLocalAdminRole: 'local_admin',
        // Раунд 10 (F-10 E1/F-9 D1): «Модули» — gates + бюджет фона
        modulesBusy: false,
        gateInfo: null,          // GET /api/chat/{id}/gates
        gatesBusy: false,
        budgetInfo: null,        // GET /api/workers/budget
        budgetBusy: false,
        budgetsUnlimitedBusy: false,   // F3: тумблер «Безлимит по чату»
        permsocBusy: false,
        // Раунд 10 (F-12 C1/C2): Oversight-дашборд (global admin)
        oversightData: null,     // GET /api/oversight/summary
        oversightBusy: false,
        oversightSearch: '',
        oversightSort: 'chat_id',
        oversightDetail: null,   // модалка деталей чата
        oversightDetailBusy: false,
        oversightOpBusy: false,
        // ── Раунд 10.23 (F7, ADR-1023-7 §2.8): аналитика токенов в «Сводке» ──
        tokenAnalyticsLatest: null,     // GET /api/analytics/usage/latest
        tokenAnalyticsSummary: null,    // GET /api/analytics/usage/summary
        tokenAnalyticsExecution: null,  // S8: GET /api/analytics/execution/latest
        tokenAnalyticsPeriod: 'day',    // day|week|month
        tokenAnalyticsBusy: false,
        // F6 round1025 (ADR-1025-19 D2/D3): два несмешиваемых режима карты
        // вызовов. 'latest' — трассировка (/usage/latest); 'day|week|month' —
        // агрегат (/usage/summary). Ветки отрисовки взаимоисключающие (§26).
        execMode: 'latest',
        execSelected: null,             // выбранный узел (side-panel/bottom-sheet)
        execDetailOpen: false,
        // Фильтры §27 — только на «Аналитике» (превью Статуса их не получает).
        execFilterModule: '',
        execFilterModel: '',
        execFilterStage: '',
        execFilterStatus: '',
        execFilterQuery: '',            // §27: поиск по строке (label/model/module/tool)
        // F6 (D5/§21): компактное превью последнего вызова на Статусе.
        execPreviewBusy: false,
        // F6 (D6/§52–§56): presentation-подгруппа витрины «Память → Настройки»
        // (Δ каталога = 0: только перегруппировка в JS-витрине).
        memorySubgroup: '',
        // ── Раунд 10.20 (БЛОК 3.3/T-1897): «Живая лента досье» (тикер) ──
        dossierFeed: [],         // GET /api/oversight/dossier_feed
        dossierFeedBusy: false,
        dossierFeedError: '',
        dossierFeedTimer: null,
        // ── Раунд 10.20 (БЛОК 3.2/T-1896): Досье участника (модалка) ──
        dossierOpen: false,
        dossierBusy: false,
        dossierUserId: null,
        dossierName: '',
        dossierData: null,       // {extracted, manual_traits, facts, links}
        dossierDraft: '',        // ручная правка (textarea)
        dossierSaving: false,
        dossierSavedAt: 0,       // monotonic-метка успешного сохранения
        // ── F8 round 10.22 (ADR-1022-8): асинхронная пересборка досье ──
        dossierRebuildPeriod: '180',  // 30|90|180|all (default 180)
        dossierRebuildJob: null,      // job-view (сервер — источник истины)
        dossierRebuildBusy: false,    // старт/отмена в полёте
        dossierRebuildTimer: null,    // polling ~2с только пока job активен
        // S10.22-6: доступность фичи (kill-switch DOSSIER_REBUILD_UI_ENABLED).
        // OFF → latest отдаёт 404 → прячем блок вместо битой кнопки.
        dossierRebuildEnabled: true,
        // ── Раунд 10.20 (БЛОК 3.6/T-1900): sticky-save (baseline конфига) ──
        configSnapshot: {},      // key → JSON(value) на момент загрузки
        stickySaving: false,
        // S10.20-6: список полей, которые НЕ удалось сохранить sticky-панелью
        // (ошибка/409) — baseline НЕ сдвигается, панель подсвечивает провалы.
        stickyFailed: [],
        // F0 (10.25, ADR-1025-2 D1): реальный 409 с непустым conflicting[] —
        // отдельное состояние формы `conflict` (черновик НЕ сбрасывается).
        stickyConflict: [],
        // F0 (ревью): КЛЮЧИ полей с ошибкой сохранения — подсветка у полей
        // (per-field error map), в отличие от `stickyFailed` (заголовки).
        stickyFailedKeys: [],
        // F0 (10.25, ADR-1025-4 D1): типобезопасные id тостов и операций;
        // _opNotified — идемпотентность notify(operationId, …) (один тост на
        // операцию); _toastSeq — стабильный уникальный id тоста.
        _toastSeq: 0,
        _opSeq: 0,
        _opNotified: {},
        // UI-полировка TMA: meAvatarUrl — URL аватара текущего юзера (blob
        // через same-origin прокси avatarUrl; S10.16-8: без внешнего CDN) и
        // флаг полноэкранного режима TMA (кнопка ⛶ в шапке). Кэш blob-URL —
        // модульный _avatarCache (см. выше в файле) — реактивность не нужна.
        meAvatarUrl: '',
        isFullscreen: false,
        // config
        configItems: [],
        // F10 (10.24, ADR-1024-11 D2): версия загрузки конфига — растёт в
        // loadConfig(); входит в :key kv-editor, чтобы reload гарантированно
        // перемонтировал редактор (реактивность prop на замену массива).
        configVersion: 0,
        configGroups: [],          // 84.24: метаданные групп (с сервера)
        configSearch: '',          // 84.24: фильтр по title/description/key
        configLoading: false,
        configError: '',          // F-13 (AC-3, MED-021): баннер loadConfig
                                  // (403/503/сеть) — объясняет пустую вкладку
        configChatUpdatedAt: null, // F-7: optimistic-метка чата (X-Chat-Id)
        // Раунд 10.23 (F8, ADR-1023-8): вкладка «Промпты» — активный режим
        // Вербализатора (Tabs) и блок мониторинга динамического анти-клише.
        promptMode: 'casual',      // редактируемый режим: casual|serious|deep_research
        clicheMeta: null,          // GET /api/anticliche (метаданные + список)
        clicheAvailable: false,    // F4-API доступен (fail-open → блок скрыт)
        clicheLoading: false,
        clicheBusy: false,         // форс-обновление/сохранение в процессе
        clicheEditing: false,      // режим ручного редактирования
        clicheDraft: '',           // черновик списка (по строке на фразу)
        clicheLenWarned: false,    // review fix: одно предупреждение на сессию правки
        // F7 (10.24, ADR-1024-3 D1): черновик регулируемого лимита паттернов.
        clicheLimitDraft: '',
        saving: new Set(),
        keyDrafts: {},
        secretMask: SECRET_MASK,  // контракт/тесты; рантайм-guard'ы читают SECRET_MASK напрямую
        // 3.5.1: показать/скрыть маску ключа — F9/ADR-1025-22 D4: локально в
        // компоненте `secret-field` (`reveal`), per-key `keyReveal` не нужен.
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
        // chat_lore (round 7, spec §3.10/E2)
        chatLoreChats: [],             // доступные чаты (селектор слева)
        chatLoreLoading: false,        // загрузка списка чатов
        chatLoreProfile: null,         // профиль выбранного чата (ответ API)
        chatLoreSelectedId: null,
        chatLoreProfileLoading: false,
        chatLoreError: '',             // ошибка профиля (карточка справа)
        chatLoreSaving: false,         // short-операции (manual/settings/clear)
        chatLoreGenerating: false,     // «Сгенерировать сейчас» (LLM, минуты)
        chatLoreHistory: [],           // timeline истории (модалка, DESC)
        chatLoreHistoryOpen: false,
        chatLoreHistoryLoading: false,
        chatLore409: null,             // Q8: {code:'conflict', current_updated_at}
        // Раунд 9 (AGI Memory, spec §3.6.3, T-830/F3): «Участники и
        // отношения» в «Лор чатов» (relations-блок карточки чата).
        relationsEnabled: false,       // per-chat тумблер relations_enabled
        chatRelations: [],             // строки GET /chat_lore/{id}/relations
        relationsBusy: false,          // загрузка/сохранение отношений
        relationDraft: null,           // {user_id, stage_manual, note} в работе
        // Раунд 9 (AGI Memory, spec §3.6.3, T-831/F4): «Синтез (сон)» и
        // «Ностальгия» — мини-блоки вкладок «Сон»/«Ностальгия».
        dreamBusy: false,              // POST /api/memory/dream/run в процессе
        memoryRagBusy: false,          // прочие операции блоков памяти
        dreamBeliefs: [],              // последние beliefs (GET)
        dreamLog: [],                  // последние строки memory_dream_log
        nostalgiaLog: [],              // последние срабатывания (GET nostalgia)
        // ── F5 (cognition-dashboard-round1013, ТЗ §5/§7): «Осмысление» +
        //    виджет «Интеллект и Память». Данные — аддитивные read-API
        //    (cognition/status, graph, stats, timeline, beliefs?kind=).
        cognition: null,               // GET /api/memory/cognition/status
        cognitionBeliefs: [],          // лента «Убеждения» (kind=belief)
        cognitionParadigms: [],        // лента «Парадигмы» (kind=paradigm)
        // F4 (persona-traits-ribbon-round1014): третья лента «Эволюция
        // характера» — global `dynamic_traits` из GET /api/persona.
        cognitionTraits: [],
        // F8 (dead-extractor-paradigms-round1024, ADR-1024-5 D3): явные
        // статусы/причины пустоты лент для пояснительного Empty State.
        cognitionParadigmsStatus: null,   // ok|empty (deep-sleep)
        cognitionParadigmsReason: null,   // код причины (R17-safe)
        cognitionTraitsStatus: null,      // ok|empty|skip|error|never
        cognitionTraitsReason: null,      // код причины (R17-safe)
        cognitionSelfFactsCount: null,    // self-факты за окно (chat-scope)
        personaHealth: null,           // метрики Личности (GET /persona/health)
        cognitionStats: null,          // GET /api/memory/stats
        cognitionTimeline: [],         // GET /api/memory/timeline
        // F7 (memory-retention-health, D-6): метрики здоровья памяти
        // (GET /api/memory/health) — overdue/unconfirmed/сырьё/хранилище.
        memoryHealth: null,
        memoryHealthBusy: false,
        cognitionBusy: false,
        cognitionTimer: null,          // polling 15с (только вкладка «Статус»)
        _cognitionPollRestore: null,   // F2: таймер возврата polling к 15с
        cognitionNetwork: null,        // vis.Network (destroy-дисциплина)
        cognitionGraphData: null,      // {nodes, edges, truncated}
        _cognitionGraphSig: null,      // подпись данных (ISSUE-4: без пере-рендера)
        _cognitionGraphMode: null,     // F11 §16: 'simple' (mobile) | 'full'
        cognitionVisLoaded: false,     // lazy-load vis-network
        // F2 (graph-frontend-physics-search-round1015, ТЗ §1 frontend):
        // «Поиск по графу» — центрирование камеры на узле по имени.
        graphSearchQuery: '',          // строка поиска (v-model.trim)
        graphSearchStatus: '',         // статус: «Найден: …» / «Ничего не найдено»
        _graphSearchMatches: [],       // текущий список совпадений (по label)
        _graphSearchIdx: 0,            // индекс перебора (Enter циклически)
        _graphSearchLastQ: '',         // последний запрос (сброс перебора)
        memoryWidgetBusy: false,
        reducedMotion: false,          // prefers-reduced-motion (анимации off)
        // hotfix6 (ADR-1025-12 D1/D4): диагностика tier стекла (R17-safe) +
        // состояние §15 «Сердцебиение» (Canvas 2D, телеметрия отдельно от рендера).
        glassTierDiag: null,           // {supported, override, maxNodes, active, reducedMotion}
        hbState: 'unknown',            // HEALTHY | WARNING | CRITICAL | UNKNOWN
        hbEma: null,                   // EMA-сглаживание метрики нагрузки (0..1)
        hbReason: 'нет данных',        // причина состояния (для тултипа/подписи)
        hbDwellPending: null,          // ожидаемый tier эскалации (dwell, N сэмплов)
        hbDwellCount: 0,               // число подряд подтверждающих сэмплов
        hbTipOpen: false,              // тултип hover/tap (CPU/RAM/диск/статус/время/причина)
        hbCanvasRaf: null,             // id requestAnimationFrame (null — цикл остановлен)
        hbLastDraw: 0,
        // C2 (D5/D8/Q9): переезд чата и per-chat админы — глобальный admin
        remapNewChatId: '',            // новый chat_id для «Переезда чата»
        remapBusy: false,              // POST remap в процессе
        chatAdmins: [],                // telegram_id админов выбранного чата
        newChatAdminId: '',            // ввод telegram_id нового админа
        adminsBusy: false,             // список/мутация админов в процессе
        loreManual: '',                // черновик ручного лора (textarea)
        loreAuto: '',                  // авто-лор (read-only textarea)
        loreSettings: {                // настройки авто-генерации (форма)
          auto_enabled: true,
          auto_period_hours: 24,
          auto_window_hours: 24,
        },
        // status
        statusData: null,
        statusError: null,
        statusTimer: null,
        // B1/OD8 (T-1128/T-1129): компактный список доступности ключей +
        // временной график (GET /api/status/key-history, leak-safe).
        keyHistory: null,
        keyHistoryChart: null,
        keyHistoryChartHeight: 120,   // 10.10 (п.2): реактивная высота
        logs: [],
        logsCount: 0,
        logsLoading: false,
        // F6 (T-1461/T-1462, §3.2, F6-Q4): единый источник истины фильтра
        // логов; дефолт при каждом первичном открытии приложения —
        // комбинированный тег ERROR+WARNING (сессионно, без localStorage).
        logLevel: 'ERROR+WARNING',
        // S7 (ADR-1026-9 D4, §110): клиентский чип «Саммари» в СУЩЕСТВУЮЩЕМ
        // log viewer. Активация → logLevel='INFO' + фильтрация this.logs по
        // маркерам событий Саммари; нового endpoint/routes.py нет.
        logSummaryOnly: false,
        logLevelBeforeSummary: null,
        // 10.7 (3c): transient-подсветка строки, скопированной по клику.
        copiedIndex: null,
        copiedTimer: null,
        // ── F11 (10.25, ADR-1025-23): композиция витрины «Статус» ──
        // §20/D5: счётчики «Ошибки/Предупреждения» — лёгкие запросы
        // /api/status/logs?level=…&limit=1 (читаем `count`); viewer не тронут.
        logErrorCount: null,
        logWarnCount: null,
        // §13/D2: имя бота из persona (из УЖЕ загружаемого /api/persona в
        // loadCognition); пусто → нейтральное «Бот».
        botDisplayName: '',
        // §16/D4: расширение графа — витринный фильтр по group, подробности
        // выбранного узла, ближайшие связи, mobile-экран полного исследования.
        graphFilterGroup: '',
        graphDetail: null,
        graphNeighbors: [],
        graphFullOpen: false,   // fallback при IA_V2_ENABLED=false (шторка)
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
        // F6 (help-guide-integration-round1014): второй блок «Справки» —
        // Markdown-гайд по возможностям. Хранение — PG (content.intelligence_guide),
        // рендер только через sanitizeHtml (DOMPurify self-host).
        guideHtml: '',
        guideMeta: null,
        guideLoading: false,
        editingGuide: false,
        guidePreviewing: false,
        guideDraft: '',
        // ── F3 (persona-ui-tab-round1014): special-screen «Личность»
        //    (#/ai/persona). Только статические параметры (PG-API /api/persona),
        //    реактивно по активному чату (X-Chat-Id через api()). Никакой
        //    визуализации (traits — F4, отдельно).
        personaDraft: null,     // {name, biography, system_prompt_overrides, is_aware_ai}
        personaMeta: null,      // {scope, chat_id, is_global, persona_enabled, …}
        personaLoading: false,
        personaBusy: false,
        // toasts
        toasts: [],
      };
    },

    computed: {
      currentTabLabel: function () {
        var tab = this.currentTab;
        return tab ? tab.label : '';
      },
      // F24 (ADR-1024-24 D2/§4.1): реактивные аксессоры `:open`. computed читает
      // реактивную карту `this.expand` (localStorage в рендере НЕ читается).
      //   advancedOpen — inner-зоны вкладки (bare-ключ `adminbot.expand:<tab>`,
      //     F-11/10.4): «Промпты», group-аккордеоны, «Настройки отношений»;
      //   chatLoreAdvancedOpen — explicit-tab зона «Лор чатов» (тот же bare-ключ,
      //     но фиксирует исходный tabId 'chat_lore');
      //   provAdvancedOpen — внешняя зона «Провайдеров» (scope 'prov-advanced',
      //     отдельный стабильный ключ — Scanner LOW 10.11).
      advancedOpen: function () {
        return !!this.expand[_expandKey(this.activeTab)];
      },
      chatLoreAdvancedOpen: function () {
        return !!this.expand[_expandKey('chat_lore')];
      },
      provAdvancedOpen: function () {
        return !!this.expand[_expandKey('llm_providers', 'prov-advanced')];
      },
      // T-1099: глубина текущего маршрута (0 = корень → нативный ✕).
      routeDepth: function () {
        return routeDepth(this.route);
      },
      // T-1100: navbar-пункты, отфильтрованные по правам.
      // F1 (ADR-1025-1 D5/D10): kill-switch новой IA. OFF → legacy-набор
      // NAV_ITEMS/HUBS и .navbar-band байт-в-байт; ON → IA v2.
      iaV2: function () {
        return this.uiFlag('IA_V2_ENABLED');
      },
      navItems: function () {
        var self = this;
        var canView = function (id) { return self.canViewTab(id); };
        var items = this.iaV2 ? NAV_ITEMS_V2 : NAV_ITEMS;
        var hubs = this.iaV2 ? HUBS_V2 : HUBS;
        return items.filter(function (n) {
          if (n.id === 'status' || n.id === 'how') return true;
          if (n.id === 'permsoc') return self.canViewTab('permsoc');
          // A2/блокер-1: «Модули» — НЕ hub (список 11 модулей) → свой tab.
          if (n.id === 'modules') return canView('modules');
          // F1: «Память» — свой hub (видна хотя бы одна карточка).
          if (n.id === 'memory') return hubVisible('#/memory', canView, hubs);
          // D1: hub-пункты (ai/access) видимы, если видна хотя бы одна карточка.
          if (n.id === 'ai' || n.id === 'access') {
            return hubVisible(n.route, canView, hubs);
          }
          return false;
        });
      },
      activeNav: function () {
        var r = this.route || '#/';
        if (r === '#/' || r === '#/oversight' || r === '#/status/graph') {
          return 'status';
        }
        if (r === '#/how') return 'how';
        if (r.indexOf('#/modules') === 0) return 'modules';
        // Reviewer (M): `#/memory*` достижим и при OFF-откате (алиас/дееплинк),
        // но в legacy `NAV_ITEMS` раздела «Память» нет — подсвечиваем «ИИ».
        if (r.indexOf('#/memory') === 0) return this.iaV2 ? 'memory' : 'ai';
        if (r.indexOf('#/ai') === 0) return 'ai';
        if (r === '#/permsoc') return 'permsoc';
        if (r.indexOf('#/access') === 0) return 'access';
        return '';
      },
      // T-1100: карточки активного hub-экрана (или null, если не hub).
      hubCards: function () {
        var map = this.iaV2 ? HUBS_V2 : HUBS;
        var hub = map[this.route];
        if (!hub) return null;
        var self = this;
        var cards = hub.cards.filter(function (c) {
          return !c.tab || self.canViewTab(c.tab);
        });
        if (!cards.length) return null;
        return { title: hub.title, subtitle: hub.subtitle, cards: cards };
      },
      // F1 (§6/§7, UPD §8.4): пункты shell’ов.
      // Desktop sidebar: публичные + админ + локальный (группы разделены).
      sidebarItems: function () {
        return this.navItems;
      },
      // Mobile bottom-nav: не более 4. hotfix4 (T-2519/T-2520, ADR-1025-8 D3):
      // Статус+Справка — ВСЕГДА первые два для ЛЮБОЙ роли; далее ОДИН
      // приоритетный админ-раздел (Модули, иначе ИИ); «Ещё» — только при
      // наличии реально скрытых (непубличных) разделов.
      // H-1 (Scanner): «Ещё» обязателен при ЛЮБОМ непубличном разделе
      // (Память/Доступы/PERMsoc/Модули/ИИ) — иначе раздел недостижим на <768.
      bottomNavItems: function () {
        var items = this.navItems;
        var byId = {};
        items.forEach(function (n) { byId[n.id] = n; });
        var out = [];
        if (byId['status']) out.push(byId['status']);
        if (byId['how']) out.push(byId['how']);
        // Один приоритетный админ-раздел: Модули (иначе ИИ) — остальные
        // непубличные уходят в «Ещё».
        var pri = byId['modules'] || byId['ai'];
        if (pri) out.push(pri);
        var shown = {};
        out.forEach(function (n) { shown[n.id] = true; });
        var hiddenCount = items.filter(function (n) {
          return n.group !== 'public' && !shown[n.id];
        }).length;
        if (hiddenCount) {
          out.push({ id: 'more', label: 'Ещё', route: '', icon: 'expand_more',
            more: true });
        }
        return out;
      },
      // Меню «Ещё» (шторка, T-2520): только реально скрытые непубличные
      // разделы (Память/Доступы/PERMsoc + вытесненный ИИ); дубля «Справки»
      // нет. «Профиль» — существующий identity-блок (UPD §8.2), не экран.
      mobileMoreItems: function () {
        var items = this.navItems;
        var byId = {};
        items.forEach(function (n) { byId[n.id] = n; });
        var inlineId = byId['modules'] ? 'modules'
          : (byId['ai'] ? 'ai' : '');
        return items.filter(function (n) {
          return n.group !== 'public' && n.id !== inlineId;
        });
      },
      // Управляемая мобильная навигация (<768) или drawer (768–1199).
      isMobileShell: function () {
        return this.shellMode === 'mobile';
      },
      hasSidebar: function () {
        return this.shellMode === 'desktop';
      },
      // Drawer-навигация для планшета/компактного desktop (768–1199).
      isCompactShell: function () {
        return this.shellMode === 'compact';
      },
      // F1 (§4.2): группы sidebar — публичные / админ / локальный PERMsoc.
      sidebarGroups: function () {
        var pub = [], admin = [], local = [];
        this.navItems.forEach(function (n) {
          if (n.group === 'public') pub.push(n);
          else if (n.group === 'local') local.push(n);
          else admin.push(n);
        });
        return { pub: pub, admin: admin, local: local };
      },
      // UPD §8.4: «текущий раздел + путь назад» на вложенных страницах.
      breadcrumb: function () {
        var r = this.route || '#/';
        var parent = routeParent(r);
        if (!parent) return null;
        var home = { label: 'Статус', route: '#/' };
        if (parent === '#/') return { root: home, current: this._routeLabel(r) };
        return { root: home, mid: { label: this._routeLabel(parent),
          route: parent }, current: this._routeLabel(r) };
      },
      currentTab: function () {
        return this.tabs.find(function (t) { return t.id === this.activeTab; }, this) || null;
      },
      // A2/T-1167: активная модалка модуля (по openModuleId).
      activeModule: function () {
        var id = this.openModuleId;
        if (!id) return null;
        return this.modules.find(function (m) { return m.id === id; }) || null;
      },
      activeModuleTab: function () {
        var m = this.activeModule;
        if (!m) return null;
        return this.tabs.find(function (t) { return t.id === m.tab; }) || null;
      },
      // A2: «один дом» — окно модуля рендерит только операционные группы.
      activeModuleGroups: function () {
        var t = this.activeModuleTab;
        var groups = t ? this.groupedForTab(t) : [];
        // INFO: content_media (tab=None) специфицирован в окно Модуля 6.
        var m = this.activeModule;
        if (m && m.id === 'mod_video_summary') {
          var extra = this._syntheticGroup('content', 'content_media');
          if (extra) groups = groups.concat([extra]);
        }
        return groups;
      },
      // ═══ F5 (ADR-1025-15 D1/D3/D6): workspace модуля — производная hash ═══
      // Своей копии маршрута НЕТ: всё выводится из `this.route`.
      // Поддерживаются ОБЕ двери §48: `#/modules/<slug>[/<wt>[/<key>]]`
      // (door='modules') и `#/ai/prompts/<slug>[/<stage>]` (door='library') —
      // объект один и тот же config-item `prompts.*`, копий нет.
      workspace: function () {
        var route = this.route || '';
        var parsed = parseWorkspaceRoute(route);
        var door = 'modules';
        if (!parsed) {
          var lib = parsePromptLibraryRoute(route);
          if (!lib) return null;
          door = 'library';
          parsed = { slug: lib.slug, tab: '', stage: lib.stage,
                     promptKey: lib.promptKey || '' };
        }
        var m = (typeof this.moduleBySlug === 'function')
          ? this.moduleBySlug(parsed.slug) : _wsModuleById(parsed.slug);
        if (!m) return null;
        var declared = m.tabs || [];
        var tab;
        if (door === 'library') {
          // Библиотека открывает ту же комнату: stage → соответствующая
          // вкладка, иначе первая промптовая вкладка модуля.
          tab = (parsed.stage && declared.indexOf(parsed.stage) >= 0)
            ? parsed.stage : _workspacePromptTabOf(m);
        } else {
          tab = parsed.tab || 'overview';
          if (declared.indexOf(tab) < 0) tab = 'overview';
        }
        var stage = parsed.stage || '';
        var promptKey = parsed.promptKey || '';
        // §48: короткая форма `#/modules/<slug>/<wt>/<promptKey>` (без
        // отдельного stage) — 3-й сегмент = ключ промпта. Только для
        // door='modules': у библиотеки `<stage>` — это реальный этап.
        if (door === 'modules' && !promptKey && stage) {
          promptKey = stage; stage = '';
        }
        return { module: m, slug: parsed.slug, tab: tab,
                 stage: stage, promptKey: promptKey, door: door };
      },
      workspaceModule: function () {
        return this.workspace ? this.workspace.module : null;
      },
      workspaceTab: function () {
        return this.workspace ? this.workspace.tab : '';
      },
      // S9 (ADR-1026-8 D1/D8): секция «Тестирование пайплайна» видна только для
      // модуля «Сводки чатов» на вкладке `testing` и при подтверждённой
      // доступности API (env-флаг ON → probe 200; OFF → 404 → скрыта).
      summaryTestVisible: function () {
        var ws = this.workspace;
        return !!(ws && ws.module && ws.module.id === 'mod_summary'
          && ws.tab === 'testing' && this.summaryTest.available === true);
      },
      // §113: пресеты временного окна (часы).
      summaryTestWindows: function () {
        return [6, 12, 24, 72, 168];
      },
      // B-R1026S9-2: безопасный доступ к §112-метрикам — на error/running
      // payload без полной структуры секция метрик не рендерится (нет
      // `undefined.l1`). Сервер отдаёт полные структуры, это второй барьер.
      summaryTestMetrics: function () {
        var r = this.summaryTest.result;
        var m = (r && r.metrics) || null;
        if (!m || !m.tokens || !m.tokens.l1 || !m.cost || !m.budget) {
          return null;
        }
        return m;
      },
      // B-R1026S9-2: безопасный доступ к §113-артефактам (аналогично).
      summaryTestArtifacts: function () {
        var r = this.summaryTest.result;
        var a = (r && r.artifacts) || null;
        if (!a || !Array.isArray(a.source) || !Array.isArray(a.filtered)
            || !Array.isArray(a.clusters)) {
          return null;
        }
        return a;
      },
      // §112: «Процент отсева» (null/неизвестно → «Нет данных», без выдумок).
      summaryTestDropPercent: function () {
        var r = this.summaryTest.result;
        var m = (r && r.metrics) || null;
        if (!m || !m.tokens || !m.cost || !m.budget) return 'Нет данных';
        var v = m.drop_percent;
        if (v === null || v === undefined || v === '') return 'Нет данных';
        return v + '%';
      },
      // Применимые вкладки: объявленные ∩ имеющие содержимое (§46/§4.3).
      workspaceTabs: function () {
        var ws = this.workspace;
        if (!ws) return [];
        var self = this;
        return (ws.module.tabs || []).map(function (id) {
          return { id: id, label: WORKSPACE_TAB_LABELS[id] || id };
        }).filter(function (t) {
          return self.workspaceTabHasContent(ws.module, t.id);
        });
      },
      // §48: фокус промпта (объект один — config-item `prompts.*`).
      workspacePromptFocus: function () {
        var ws = this.workspace;
        if (!ws) return null;
        var items = this.workspacePromptItems(ws.module, ws.stage || '');
        if (!items.length) items = this.workspacePromptItems(ws.module);
        if (!items.length) return null;
        var key = ws.promptKey;
        if (key) {
          for (var i = 0; i < items.length; i++) {
            if (items[i].key === key) return items[i];
          }
          return null;   // ключ не найден → дерево открыто, фокус не назначен
        }
        return items[0];
      },
      // §48: плоский список промптов активной workspace-вкладки.
      workspacePromptList: function () {
        var ws = this.workspace;
        if (!ws) return [];
        if (ws.tab === 'prompts') return this.workspacePromptItems(ws.module);
        if (ws.tab === 'synthesizer') {
          return this.workspacePromptItems(ws.module, 'synthesizer');
        }
        if (ws.tab === 'verbalizer') {
          return this.workspacePromptItems(ws.module, 'verbalizer');
        }
        return [];
      },
      // §47/§48: рабочая точка входа в библиотеку промптов из раздела ИИ —
      // модули, чьи промпты там представлены (вторая дверь). Клик ведёт
      // на `#/ai/prompts/<slug>[/<stage>]` → тот же config-item, что и
      // страница модуля (копий нет).
      promptLibraryEntries: function () {
        var self = this;
        var out = [];
        (this.modules || []).forEach(function (m) {
          var gid = MODULE_PROMPT_GROUPS[m.id];
          if (!gid) return;
          var count = self.workspacePromptItems(m).length;
          if (!count) return;
          var stages = [];
          ['synthesizer', 'verbalizer'].forEach(function (st) {
            if (self.workspacePromptItems(m, st).length) stages.push(st);
          });
          out.push({ module: m, slug: self.routeSlugOf(m),
                     count: count, stages: stages });
        });
        return out;
      },
      // §9.3 spec: инвариант покрытия §117(1–4) — ДОКАЗАТЕЛЬНЫЙ.
      // `old` — статически объявленные группы источника вкладки модуля
      // (`TABS[m.tab].sources`); `seen` — группы, реально достижимые в
      // ПРИМЕНИМЫХ вкладках workspace (учитывается `m.tabs`). Расхождение =
      // провал (потеря группы/параметра при переработке UI). «Старое»
      // множество НЕ выводится из `groupedForTab` → проверка не тавтологична.
      workspaceCoverage: function () {
        var m = this.workspaceModule;
        if (!m) return { groups: [], missing: [] };
        var self = this;
        var seen = {};
        function add(g) { if (g && g.id) seen[g.id] = true; }
        // 1) группы, достижимые в применимых вкладках workspace (m.tabs учтён).
        ['settings', 'models', 'limits', 'prep'].forEach(function (wt) {
          if (!_workspaceTabApplicable(m, wt)) return;
          self._workspaceGroupsFor(m, wt).forEach(add);
        });
        // 2) промпты модуля: вкладка промптов workspace ИЛИ вторая дверь §48.
        var pg = MODULE_PROMPT_GROUPS[m.id];
        if (pg) seen[pg] = true;
        // 3) синтетическая группа Видео (эквивалент activeModuleGroups).
        if (m.id === 'mod_video_summary') {
          var extra = this._syntheticGroup('content', 'content_media');
          if (extra) add(extra);
        }
        // 4) эталон — статические источники вкладки модуля (`TABS[m.tab]`).
        var t = (this.tabs || []).find(function (x) { return x.id === m.tab; });
        var old = {};
        (t && t.sources ? t.sources : []).forEach(function (s) {
          if (s.groups && s.groups.length) {
            s.groups.forEach(function (gid) { old[gid] = true; });
            return;
          }
          // groups: null → вся категория (для prompts — группа модуля).
          if (s.category === 'prompts') {
            if (pg) old[pg] = true;
            return;
          }
          self.groupedForTab(t).forEach(function (g) {
            if (g && g.category === s.category && g.id) old[g.id] = true;
          });
        });
        var groups = Object.keys(seen);
        var missing = Object.keys(old).filter(function (gid) {
          return !seen[gid] && gid !== 'content_media';
        });
        return { groups: groups, missing: missing };
      },
      // §49: 6 групп «Моделей и подключений» (все блоки-подключения ровно раз).
      providerGrouped: function () {
        var blocks = this.providerConnectionBlocks || [];
        var byId = {};
        blocks.forEach(function (b) { byId[b.id] = b; });
        var groups = [];
        var seen = {};
        PROVIDER_GROUPS.forEach(function (g) {
          var list = [];
          (g.blocks || []).forEach(function (id) {
            if (byId[id] && !seen[id]) { list.push(byId[id]); seen[id] = true; }
          });
          groups.push({ id: g.id, title: g.title, blocks: list });
        });
        var rest = blocks.filter(function (b) { return !seen[b.id]; });
        if (rest.length) {
          groups.push({ id: 'technical', title: 'Технические подключения',
                        blocks: rest });
        }
        return groups;
      },
      // Модели workspace-модуля: его блоки-подключения (§49) в его группах.
      workspaceModelGroups: function () {
        var m = this.workspaceModule;
        if (!m) return [];
        var blockIds = MODULE_MODEL_BLOCKS[m.id] || [];
        var groups = this.providerGrouped || [];
        var out = [];
        groups.forEach(function (g) {
          var list = (g.blocks || []).filter(function (b) {
            return blockIds.indexOf(b.id) >= 0;
          });
          if (list.length) out.push({ id: g.id, title: g.title, blocks: list });
        });
        return out;
      },
      // F5 (D4/§49, T-2714): карточки подключений модуля — 6 групп, в каждой
      // карточка с полями «название/назначение/основная модель/резервная
      // модель/статус» + действия «Проверить»/«Настроить». Значения — из
      // существующей структуры (см. `buildConnectionCard`), без секретов.
      workspaceModelCards: function () {
        var self = this;
        return (this.workspaceModelGroups || []).map(function (g) {
          return {
            id: g.id, title: g.title,
            cards: (g.blocks || []).map(function (b) {
              return buildConnectionCard(self, b);
            }),
          };
        });
      },
      // §46: вкладка «Тестирование» — РЕАЛЬНЫЙ контент (T-2700): тестируемые
      // подключения модуля (подблоки разворачиваются), reuse `testBlock` без
      // записи. Пусто → вкладка не рендерится (`workspaceTabHasContent`).
      workspaceTestingBlocks: function () {
        var out = [];
        var groups = this.workspaceModelGroups || [];
        groups.forEach(function (g) {
          (g.blocks || []).forEach(function (b) {
            if (!b || b.testable === false) return;
            if (b.subBlocks && b.subBlocks.length) {
              b.subBlocks.forEach(function (sb) {
                if (sb && sb.testable !== false) out.push(sb);
              });
            } else {
              out.push(b);
            }
          });
        });
        return out;
      },
      // F5 (10.24, ADR-1024-9 D6): карточка «Генерация изображений» видна
      // только при uiFlag('IMAGE_MODULE_CARD_ENABLED') (default ON). OFF →
      // витрина без карточки; вкладка также недоступна (см. _flagTabHidden).
      visibleModules: function () {
        var self = this;
        return this.modules.filter(function (m) {
          if (m.id === 'mod_images') {
            return self.uiFlag('IMAGE_MODULE_CARD_ENABLED');
          }
          return true;
        });
      },
      // ═══ F4 (10.25, ADR-1025-14 D1/D5/D6): store-производные каталога ═══
      // §45: счётчики для ВЫБРАННОЙ области по набору visibleModules.
      // Инвариант «неизвестное ≠ выключено»: unknown/blocked/inert и
      // провал сохранения идут в «Есть проблемы», НЕ в «Выключено».
      // noToggle входит ТОЛЬКО в «Всего»; uiFlag-скрытые модули (по
      // visibleModules) не входят никуда.
      moduleCounters: function () {
        var self = this;
        var scope = this.storeScope();
        var total = 0, on = 0, off = 0, issues = 0;
        this.visibleModules.forEach(function (m) {
          total += 1;
          if (m.noToggle) return;
          var st = self.getModuleState(scope, m.id);
          if (st.runtime === 'on') on += 1;
          else if (st.runtime === 'off') off += 1;
          if (st.runtime === 'unknown' || st.runtime === 'blocked'
              || st.runtime === 'inert' || st.error
              || self._moduleSaveFailed(m)) {
            issues += 1;
          }
        });
        return { total: total, on: on, off: off, issues: issues };
      },
      // §34–§35: кандидаты панели быстрого управления (витрина, без
      // noToggle и uiFlag-скрытых).
      quickpickCandidates: function () {
        return this.visibleModules.filter(function (m) {
          return !!m.toggleKey && !m.noToggle;
        });
      },
      // §34: избранные модули в сохранённом порядке (после валидации).
      quickpickModules: function () {
        var byId = {};
        this.quickpickCandidates.forEach(function (m) { byId[m.id] = m; });
        return (this.moduleQuickpicks || []).map(function (id) {
          return byId[id];
        }).filter(Boolean);
      },
      // §35: лимит начального отображения (остальные — «Все избранные»).
      quickpickVisible: function () {
        var list = this.quickpickModules;
        return this.moduleQuickpicksOpen ? list : list.slice(0, 4);
      },
      quickpickHiddenCount: function () {
        return Math.max(0, this.quickpickModules.length - 4);
      },
      // §32/§44: фильтры каталога — представление (ноль мутаций).
      moduleFilterOptions: function () {
        return [
          { id: 'all', label: 'Все' },
          { id: 'on', label: 'Включённые' },
          { id: 'off', label: 'Выключенные' },
          { id: 'issues', label: 'Есть проблемы' },
          { id: 'picks', label: 'Избранные' },
        ];
      },
      // §32/§44: основной каталог после поиска+фильтра (генеральные
      // тумблеры сохраняются — фильтр их не сбрасывает).
      filteredModules: function () {
        var self = this;
        var scope = this.storeScope();
        var q = String(this.moduleSearch || '').trim().toLowerCase();
        var f = this.moduleFilter || 'all';
        return this.visibleModules.filter(function (m) {
          if (q && self._moduleSearchHaystack(m).indexOf(q) < 0) return false;
          if (f === 'all') return true;
          if (m.noToggle) return false;
          if (f === 'picks') return self.isQuickpick(m);
          var st = self.getModuleState(scope, m.id);
          if (f === 'on') return st.runtime === 'on';
          if (f === 'off') return st.runtime === 'off';
          if (f === 'issues') {
            return st.runtime === 'unknown' || st.runtime === 'blocked'
              || st.runtime === 'inert' || !!st.error
              || self._moduleSaveFailed(m);
          }
          return true;
        });
      },
      // 3.5.1: активная вкладка — конфиг (generic-рендер по sources)
      currentTabIsConfig: function () {
        var t = this.currentTab;
        return !!(t && t.type === 'config');
      },
      // 3.5.1: группы активной конфиг-вкладки (для generic-шаблона).
      // 10.9 → 10.25 (F7): PERMsoc — 6 owner-блоков (псевдо-группы `owner`);
      currentTabGroups: function () {
        var t = this.currentTab;
        if (!t || t.type !== 'config') return [];
        // F5 (§46): на странице модуля generic-группы фильтруются вкладкой.
        if (this.workspaceModule) {
          var m = this.workspaceModule;
          var wt = this.workspaceTab;
          // §48: промпты рендерит master-detail (не generic-сетка).
          if (wt === 'prompts' || wt === 'synthesizer' || wt === 'verbalizer') {
            return [];
          }
          if (wt === 'models') return this._workspaceGroupsFor(m, 'models');
          if (wt === 'limits') return this._workspaceGroupsFor(m, 'limits');
          if (wt === 'prep') return this._workspaceGroupsFor(m, 'prep');
          if (wt === 'settings') return this._workspaceGroupsFor(m, 'settings');
          return [];
        }
        if (t.id === 'permsoc') return this._permsocOwnerGroups();
        // F6 (ADR-1025-19 D6/§52–§56): «Память → Настройки» — 5 подгрупп
        // витрины (presentation-level; каталог не правится).
        if (t.id === 'memory_rag') return this._memoryGroups();
        return this.groupedForTab(t);
      },
      currentTabItemCount: function () {
        var t = this.currentTab;
        return (t && t.type === 'config') ? this.tabItemCount(t) : 0;
      },
      // F6 (ADR-1025-19 D6/§53–§56): реально присутствующие подгруппы
      // «Память → Настройки». Computed (не method) — реактивен к configItems
      // и корректно итерируется в шаблоне.
      memorySubgroupChips: function () {
        var self = this;
        var base = this.groupedForTab(this.currentTab);
        var present = {};
        (base || []).forEach(function (g) {
          (g.items || []).forEach(function (it) {
            present[self._memorySubgroupOf(it)] = true;
          });
        });
        return MEMORY_SUBGROUPS.filter(function (s) { return present[s.id]; });
      },
      // F8 (ADR-1023-8): Tabs режимов Вербализатора (вкладка «Промпты»).
      promptModeTabs: function () {
        return [
          { id: 'casual', label: 'Casual' },
          { id: 'serious', label: 'Serious' },
          { id: 'deep_research', label: 'Deep Research' },
        ];
      },
      // 10.11 (spec §2.2): две смысловые зоны «Провайдеров». ОБЯЗАНЫ быть
      // computed (не methods): шаблон обращается как к bare-ref
      // (`v-for="b in providerConnectionBlocks"`, `providerAdvancedBlocks.length`).
      // Методы рендерились бы как `[]` (function не iterable) — полная потеря
      // блоков 2.2–2.5 (Reviewer CRITICAL).
      providerConnectionBlocks: function () {
        return (this.providerBlocks || []).filter(function (b) {
          return b.zone !== 'advanced';
        });
      },
      providerAdvancedBlocks: function () {
        return (this.providerBlocks || []).filter(function (b) {
          return b.zone === 'advanced';
        });
      },
      // 10.9 (п.7.1): один блок «Доступность ключей» — 4 группы функций.
      // Порядок групп = порядок записей /api/status (сервер уже сгруппировал).
      llmGroups: function () {
        var cards = (this.statusData && this.statusData.llm) || [];
        var order = [], byId = {};
        cards.forEach(function (c) {
          var gid = c.group_id || 'other';
          if (!byId[gid]) {
            byId[gid] = { id: gid, title: c.group_title || 'Прочее',
                          cards: [] };
            order.push(gid);
          }
          byId[gid].cards.push(c);
        });
        return order.map(function (id) { return byId[id]; });
      },
      permissions: function () {
        return (this.me && this.me.permissions) ? this.me.permissions : {};
      },
      // chat_lore (3.10): глобальный admin = роль admin || wildcard; remap и
      // управление chat_admins (D5/D8/Q9) видны в UI только ему (C2)
      isGlobalAdmin: function () {
        return !!(this.me && (this.me.role_name === 'admin'
          || (this.me.permissions && this.me.permissions.wildcard)));
      },
      // F11 (10.24, ADR-1024-12; review iter2 M1): ЭФФЕКТИВНЫЙ глобальный
      // админ с сервера (`/api/me.is_global_admin` — единый источник
      // `services/roles.access_for`). Паритет с RBAC safe-эндпоинта: custom-
      // роль с `role_type=global_admin` без wildcard тоже правит глобальный
      // секрет. Fallback на legacy-эвристику `isGlobalAdmin`, если поле не
      // пришло (старый сервер/тест-стенд). НЕ заменяет `isGlobalAdmin`
      // (общий флаг других фич) — только гейт глобальных секретов.
      isGlobalAdminEffective: function () {
        if (this.me && typeof this.me.is_global_admin === 'boolean') {
          return this.me.is_global_admin;
        }
        return !!this.isGlobalAdmin;
      },
      // F6 round1025 (ADR-1025-19 D1/D2/§25): adapter-слой
      // `Backend metrics → Normalized execution graph → UI`. Вычисление узлов
      // вынесено из компонента в `window.ExecutionGraph`; здесь — только
      // view-проекция нормализованных узлов для существующего `.token-flow*`.
      // Связи — ТОЛЬКО подтверждённые (parent_id в БД нет → tool без ветки).
      tokenFlowTree: function () {
        var EG = this.execGraphApi();
        var empty = { nodes: [], edges: [], main: [], hasBranch: false,
                      empty: true, runId: null, totals: null,
                      startedAt: null, metrics: null };
        if (!EG) return empty;
        // S8 (ADR-1026-10 D3/D6): в режиме «последний вызов» приоритет —
        // реальный граф прогона Саммари (filter → L1 → L2 → format + §112),
        // если он не пуст; иначе — F6-трассировка (обратная совместимость).
        // Агрегат периода (fromSummary) сюда не подмешивается (§26).
        var ex = (this.execMode === 'latest') ? this.execGraph : null;
        var useExec = !!(ex && ex.nodes && ex.nodes.length);
        var graph = useExec ? ex : this.execTrace;
        var all = graph.nodes || [];
        if (!all.length) return empty;
        var source = useExec ? EG.filter(all, this._execFilters())
                             : this.execTraceNodes;
        var allowed = {};
        var nodes = source.map(function (n) {
          allowed[n.id] = true;
          // §24: для algorithm/format — только реальные метрики (без LLM-токенов).
          var note = '';
          var m = n.metrics || {};
          var bits = [];
          if (n.kind === 'algorithm') {
            if (m.source_count != null) bits.push('Обработано: ' + m.source_count);
            if (m.saved_count != null) bits.push('Сохранено: ' + m.saved_count);
            if (m.drop_percent != null) bits.push('Отсев: ' + m.drop_percent + '%');
          } else if (n.kind === 'format') {
            if (m.channel) bits.push('Канал: ' + m.channel);
            if (m.paragraphs != null) bits.push('Абзацев: ' + m.paragraphs);
          }
          if (n.durationMs != null) bits.push('Время: ' + Math.round(n.durationMs) + ' мс');
          note = bits.join(' · ');
          return {
            id: n.id, kind: n.kind, title: n.stageLabel, note: note,
            input: n.inputTokens, output: n.outputTokens,
            cost: n.cost, priceKnown: n.priceKnown,
            estimated: n.metadata.tokensEstimated,
            stageKey: n.stageKey, status: n.status, model: n.model,
            moduleId: n.moduleId, runId: n.runId, parentIds: n.parentIds,
            ref: n, children: [],
          };
        });
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        // `edges` — подтверждённая последовательность (спина). `children` —
        // ОТДЕЛЬНЫЙ контейнер веток: заполняется только реальными branch-
        // рёбрами (§25/§30); sequence-рёбра спины в ветку НЕ дублируются.
        // Сейчас branch-рёбер нет (tool без parent_id) → ветвления нет.
        var edges = [];
        (graph.edges || []).forEach(function (e) {
          if (!allowed[e.from] || !allowed[e.to]) return;
          edges.push({ from: e.from, to: e.to });
          if (e.branch && byId[e.from]) byId[e.from].children.push(byId[e.to]);
        });
        var hasBranch = nodes.some(function (n) { return n.children.length > 0; });
        return { nodes: nodes, edges: edges, main: nodes, hasBranch: hasBranch,
                 empty: nodes.length === 0, runId: graph.runId,
                 totals: graph.totals, startedAt: graph.startedAt,
                 metrics: useExec ? graph.metrics : null,
                 filtered: this.execFilterActive() };
      },
      // S8 (ADR-1026-10 D3/D6): нормализованный граф ОДНОГО прогона Саммари —
      // клиентская проекция backend-ответа тем же ExecutionGraph (не вторая
      // визуализация). Узлы только реальные; publish GATED.
      execGraph: function () {
        var EG = this.execGraphApi();
        return EG ? EG.fromExecution(this.tokenAnalyticsExecution) : {
          runId: null, startedAt: null, nodes: [], edges: [], main: [],
          hasBranch: false, empty: true, totals: null, metrics: null };
      },
      // §112 (REQ-S8-09): честные строки метрик Саммари («Нет данных» вместо
      // выдуманного $0; публикация — gated). Источник — execGraph.metrics.
      execMetricsRows: function () {
        var g = this.execGraph;
        if (!g || !g.metrics) return [];
        var m = g.metrics;
        var self = this;
        function int(v) {
          return (v === null || v === undefined) ? 'Нет данных' : String(v);
        }
        function pct(v) {
          return (v === null || v === undefined)
            ? 'Нет данных' : (Math.round(v * 10) / 10) + '%';
        }
        function costSlot(slot) {
          if (!slot || slot.price_known !== true) return 'Нет данных';
          return self.fmtCost(slot.cost_usd, true);
        }
        var l1 = (m.tokens || {}).l1;
        var l2 = (m.tokens || {}).l2;
        var totalKnown = ((m.tokens || {}).total || {}).price_known === true;
        return [
          { label: 'Исходные сообщения', value: int(m.source_count) },
          { label: 'После фильтра', value: int(m.filtered_count) },
          { label: 'Восстановленные', value: int(m.restored_count) },
          { label: 'Процент отсева', value: pct(m.drop_percent) },
          { label: 'Темы', value: int(m.threads_count) },
          { label: 'Токены L1', value: self.execTokenPair(l1) },
          { label: 'Токены L2', value: self.execTokenPair(l2) },
          { label: 'Стоимость L1', value: costSlot(l1) },
          { label: 'Стоимость L2', value: costSlot(l2) },
          { label: 'Общая стоимость',
            value: totalKnown ? self.fmtCost(m.cost ? m.cost.total : null, true)
                             : 'Нет данных' },
          { label: 'Время выполнения', value: self.execDuration(m.duration_ms) },
          { label: 'Статус обложки', value: self.execCoverLabel(m.cover_status) },
          { label: 'Статус публикации',
            value: self.execPublicationLabel(m.publication_status) },
        ];
      },
      execTokenPair: function (slot) {
        if (!slot) return 'Нет данных';
        return this.fmtExactTokens(slot.input_tokens) + ' / '
             + this.fmtExactTokens(slot.output_tokens);
      },
      execDuration: function (ms) {
        return (ms === null || ms === undefined)
          ? 'Нет данных' : Math.round(ms) + ' мс';
      },
      execCoverLabel: function (status) {
        if (status === 'ok') return 'готова';
        if (status === 'unavailable') return 'недоступна';
        if (status === 'none') return 'не генерировалась';
        return 'Нет данных';
      },
      // §112/D4: публикация GATED (S6) — честный факт, не выдуманное «опубликовано».
      execPublicationLabel: function (status) {
        if (status === 'gated') return 'недоступна (гейт S6)';
        return (status === null || status === undefined) ? 'Нет данных'
                                                         : String(status);
      },
      // РЕЖИМ 1 (§26): нормализованная трассировка последнего вызова.
      execTrace: function () {
        var EG = this.execGraphApi();
        return EG ? EG.fromTrace(this.tokenAnalyticsLatest) : {
          runId: null, startedAt: null, nodes: [], edges: [], main: [],
          hasBranch: false, empty: true, totals: null };
      },
      // РЕЖИМ 2 (§26): нормализованный агрегат периода — отдельный объект,
      // никогда не смешивается с трассировкой.
      execSummaryGraph: function () {
        var EG = this.execGraphApi();
        return EG ? EG.fromSummary(this.tokenAnalyticsSummary) : {
          period: null, byModule: [], series: [], aggregate: [], totals: null,
          empty: true };
      },
      execIsTrace: function () {
        return this.execMode === 'latest';
      },
      // Трассировка с учётом фильтров §27 (модуль/модель/этап/статус).
      execTraceNodes: function () {
        var EG = this.execGraphApi();
        if (!EG) return [];
        return EG.filter(this.execTrace.nodes, this._execFilters());
      },
      // Агрегатные узлы с учётом ТОЛЬКО фильтра «модуль» (M-F6S-1): остальные
      // поля (model/stage/status/query) у агрегата отсутствуют (null) и не
      // выдумываются. Дополнительно при входе в период фильтры сбрасываются
      // в setExecMode — здесь страховка от «утечки» трассировочных фильтров.
      execAggregate: function () {
        var EG = this.execGraphApi();
        if (!EG) return [];
        var moduleId = this.execFilterModule || '';
        var list = this.execSummaryGraph.aggregate || [];
        if (!moduleId) return list.slice();
        return EG.filter(list, { module: moduleId });
      },
      // Есть ли данные в активном режиме (для honest empty-state §28).
      execHasData: function () {
        return this.execIsTrace
          ? this.execTraceNodes.length > 0
          : (this.execAggregate.length > 0
             || this.execSummaryGraph.series.length > 0);
      },
      // Опции фильтров — только реально встречающиеся значения (без вымысла).
      execModuleOptions: function () {
        var set = {};
        this.execTrace.nodes.forEach(function (n) {
          if (n.moduleId) set[n.moduleId] = true;
        });
        return Object.keys(set);
      },
      execModelOptions: function () {
        var set = {};
        this.execTrace.nodes.forEach(function (n) {
          if (n.model) set[n.model] = true;
        });
        return Object.keys(set);
      },
      execStageOptions: function () {
        var seen = {}, out = [];
        this.execTrace.nodes.forEach(function (n) {
          if (n.stageKey && !seen[n.stageKey]) {
            seen[n.stageKey] = true;
            out.push({ key: n.stageKey, label: n.stageLabel });
          }
        });
        return out;
      },
      // §27: фильтр «статус». Значения — только реально встречающиеся в
      // трассировке (сейчас всегда 'unknown' — не выдумываем статусы).
      execStatusOptions: function () {
        var self = this;
        var seen = {}, out = [];
        this.execTrace.nodes.forEach(function (n) {
          if (n.status && !seen[n.status]) {
            seen[n.status] = true;
            out.push({ value: n.status, label: self.execStatusLabel(n.status) });
          }
        });
        return out;
      },
      // Детали выбранного узла (side-panel/bottom-sheet §27).
      execDetail: function () {
        var EG = this.execGraphApi();
        return EG ? EG.detail(this.execSelected) : null;
      },
      // Компактное превью последнего вызова для Статуса (§21, граница с F11:
      // F6 отдаёт источник + компактный компонент, композиция — F11).
      execPreview: function () {
        var EG = this.execGraphApi();
        var g = EG ? EG.fromTrace(this.tokenAnalyticsLatest) : null;
        if (!g || g.empty) return { empty: true, nodes: [], totals: null,
                                    runId: null, startedAt: null };
        return { empty: false, nodes: g.nodes.slice(0, 8),
                 totals: g.totals, runId: g.runId, startedAt: g.startedAt };
      },
      // Столбики графика расходов: высота пропорциональна cost_usd бакета.
      // Tooltip — существующий title (bucket·цена·вызовы) в шаблоне.
      tokenSeriesBars: function () {
        var s = this.tokenAnalyticsSummary;
        var series = (s && s.series) || [];
        var max = 0;
        series.forEach(function (b) { max = Math.max(max, b.cost_usd || 0); });
        return series.map(function (b) {
          var cost = b.cost_usd || 0;
          return {
            bucket: b.bucket,
            cost_usd: cost,
            calls: b.calls || 0,
            label: String(b.bucket || '').replace('T', ' ').slice(0, 16),
            height: max > 0 ? Math.max(2, Math.round(cost / max * 100)) : 0,
          };
        });
      },
      // 3.10: любая операция лора в процессе — блокировка кнопок-мутаций
      chatLoreBusy: function () {
        return this.chatLoreProfileLoading
          || this.chatLoreSaving || this.chatLoreGenerating;
      },
      // F3 (10.14): контролы «Личности» заблокированы при выключенном флаге
      // (серверный гейт записи сохраняется — только индикация).
      personaDisabled: function () {
        return !!(this.personaMeta && this.personaMeta.persona_enabled === false);
      },
      // F3: индикатор scope внутри карточки «Личность» (navbar сохраняет
      // ровно один глобальный {{ scopeLabel }}; здесь — свой badge).
      // L2-фикс: переиспользуем единый scopeLabel (без дубля логики).
      personaScopeBadge: function () {
        return this.scopeLabel;
      },
      // F4 (84.14.5): только доступные вкладки;
      // «Статус» и «Справка» — всегда (RBAC-исключения).
      // NB (F5 10.24): computed НЕ подключён к разметке (в UI нет полосы
      // вкладок), поэтому гейт kill-switch `IMAGE_MODULE_CARD_ENABLED` живёт
      // НЕ здесь, а в `visibleModules` (карточка) и `applyRoute`/`setTab`
      // (доступ к вкладке) — см. spec §3.2.5 / ADR-1024-9 D6.
      visibleTabs: function () {
        var self = this;
        return this.tabs.filter(function (tab) {
          return tab.always || self.canViewTab(tab.id);
        });
      },
      // 3.10: визуальная склейка «ручной + авто» для инфо-строки (превью)
      loreMemoryPreview: function () {
        var manual = (this.loreManual || '').trim();
        var auto = (this.loreAuto || '').trim();
        var parts = [];
        if (manual) parts.push(manual);
        if (manual && auto) parts.push('---');
        if (auto) parts.push(auto);
        if (!parts.length) return '';
        return this.truncateLore(parts.join('\n'), 300);
      },
      errorLogs: function () {
        return this.logs.filter(function (l) { return l.level === 'ERROR' || l.level === 'CRITICAL'; });
      },
      warnLogs: function () {
        return this.logs.filter(function (l) { return l.level === 'WARNING'; });
      },
      // S7 (ADR-1026-9 D4, §110): отображаемый список логов. Чип «Саммари»
      // активен → только события Саммари (this.logs уже загружены сервером);
      // иначе — прежнее поведение (level-фильтр/счётчики не затронуты).
      shownLogs: function () {
        if (!this.logSummaryOnly) return this.logs;
        var self = this;
        return this.logs.filter(function (log) {
          return self.isSummaryLog(log);
        });
      },
      // §15/C2 (ADR-1025-12 D4): «сердцебиение» — производное от состояния
      // (HEALTHY/WARNING/CRITICAL/UNKNOWN), которое обновляет телеметрия
      // (_applyHeartbeatSample). Рендер только отображает готовое состояние.
      // C2-OFF (UI_HEARTBEAT_CANVAS_ENABLED=false) → байт-в-байт legacy-семантика
      // (`heartbeatLegacy`): SVG-виджет с прежними порогами 0.5/0.8 и подписями.
      heartbeat: function () {
        // Явное OFF-условие `=== false` (а не falsy): контексты без canvas-флага
        // получают актуальную семантику; OFF-путь откатывает ИМЕННО флагом.
        if (this.heartbeatCanvasEnabled === false) return this.heartbeatLegacy;
        var st = this.hbState || 'unknown';
        var label = { healthy: 'норма', warning: 'внимание',
                      critical: 'критично', unknown: 'нет данных' }[st];
        var badge = st === 'critical' ? 'badge-err'
          : (st === 'warning' ? 'badge-warn'
            : (st === 'unknown' ? 'badge-muted' : 'badge-ok'));
        var period = st === 'critical' ? 0.8 : (st === 'warning' ? 1.4 : 2.4);
        var level = st === 'critical' ? 'high' : (st === 'warning' ? 'elev' : 'calm');
        return {
          state: st, level: level, period: period,
          label: label || 'нет данных',
          detail: this.hbReason || '', reason: this.hbReason || '',
          badge: badge,
        };
      },
      // §15/C2-OFF (T-2599, мягкий откат C2): прежнее вычисление «сердцебиения»
      // (HEAD 441e8f7) — ratio = loadavg[0]/cpu_count иначе max(CPU%,RAM%)/100;
      // пороги 0.5/0.8; метки «спокойный/повышен/пик N%»; классы
      // badge-ok/warn/err; период для `--ekg-period`. Байт-в-байт поведение при
      // UI_HEARTBEAT_CANVAS_ENABLED=false (OFF реально откатывает семантику).
      heartbeatLegacy: function () {
        var server = this.statusData ? this.statusData.server : null;
        var ratio = null;
        if (server) {
          var load = null;
          if (Array.isArray(server.loadavg) && server.loadavg.length) {
            load = Number(server.loadavg[0]);
          }
          if (load != null && !isNaN(load) && load > 0) {
            var cores = Number(server.cpu_count);
            if (!cores || cores < 1) cores = 1;
            ratio = load / cores;
          } else {
            var cpu = Number(server.cpu_percent);
            var mem = (server.memory && server.memory.percent != null)
              ? Number(server.memory.percent) : NaN;
            var vals = [];
            if (!isNaN(cpu)) vals.push(cpu);
            if (!isNaN(mem)) vals.push(mem);
            if (vals.length) ratio = Math.max.apply(null, vals) / 100;
          }
        }
        if (ratio == null || isNaN(ratio)) {
          return { level: 'calm', period: 2.4, label: 'спокойный',
                   detail: 'метрик нет — нейтраль', badge: 'badge-ok' };
        }
        ratio = Math.max(0, ratio);
        var pct = Math.round(ratio * 100);
        if (ratio > 0.8) {
          return { level: 'high', period: 0.8, label: 'пик ' + pct + '%',
                   detail: 'высокая нагрузка', badge: 'badge-err' };
        }
        if (ratio >= 0.5) {
          return { level: 'elev', period: 1.4, label: 'повышен ' + pct + '%',
                   detail: 'нагрузка растёт', badge: 'badge-warn' };
        }
        return { level: 'calm', period: 2.4, label: 'спокойный ' + pct + '%',
                 detail: 'нагрузка в норме', badge: 'badge-ok' };
      },
      // §15 (T-2602): поля тултипа hover/tap — CPU/RAM/диск/статус/время/причина.
      heartbeatTip: function () {
        var s = this.statusData || {};
        var server = s.server || {};
        var pct = function (v) {
          return (v != null && !isNaN(Number(v))) ? Math.round(Number(v)) + '%' : '—';
        };
        var gen = (s.uptime && s.uptime.generated_at) || null;
        var updated = '—';
        if (gen) {
          try { updated = new Date(gen).toLocaleTimeString(); } catch (e) { /* — */ }
        }
        return {
          cpu: pct(server.cpu_percent),
          mem: (server.memory && server.memory.percent != null)
            ? pct(server.memory.percent) : '—',
          disk: (server.disk && server.disk.percent != null)
            ? pct(server.disk.percent) : '—',
          bot: (s.bot && s.bot.state) || '—',
          updated: updated,
          reason: this.hbReason || '',
        };
      },
      heartbeatAria: function () {
        return 'Сердцебиение сервера: ' + this.heartbeat.label +
          (this.hbReason ? ' — ' + this.hbReason : '');
      },
      // §15/C2 (T-2599): Canvas 2D доступен и флаг ON. OFF → SVG (откат).
      heartbeatCanvasEnabled: function () {
        if (!this.uiFlag('UI_HEARTBEAT_CANVAS_ENABLED')) return false;
        try {
          return !!(document.createElement('canvas').getContext('2d'));
        } catch (e) { return false; }
      },
      // D (ADR-1025-12 D5): двухстрочная шапка только в IA v2 при флаге ON;
      // иначе — legacy-разметка байт-в-байт (OFF-откат).
      headerCompactV2: function () {
        return this.iaV2 && this.uiFlag('UI_HEADER_COMPACT_V2');
      },
      // HOTFIX7 (ADR-1025-13 D3/D4): два независимых отката shell-областей.
      // Default ON (штатное новое поведение); OFF → класс `.shell-*-legacy`
      // возвращает прежние токены/геометрию без редеплоя.
      shellGlassV2: function () {
        return this.uiFlag('UI_SHELL_GLASS_V2');
      },
      shellLayoutV2: function () {
        return this.uiFlag('UI_SHELL_LAYOUT_V2');
      },
      // HOTFIX8 (ADR-1025-16 D5): env-only мягкие откаты областей B/D.
      // Default ON (штатное новое поведение); OFF → прежние значения/фон.
      shellV3: function () {
        return this.uiFlag('UI_SHELL_V3');
      },
      auroraBgEnabled: function () {
        return this.uiFlag('UI_AURORA_BG_ENABLED');
      },
      // HOTFIX9 (ADR-1025-17 D1/D4/D5/D6): env-only мягкие откаты четырёх
      // новых областей. Default ON (штатное новое поведение); OFF → прежнее
      // (flex→legacy, графит→hotfix8, стекло→frost, aurora→legacy CSS).
      shellFlexV3: function () {
        return this.uiFlag('UI_SHELL_FLEX_V3');
      },
      shellGraphiteV3: function () {
        // HOTFIX9 L-H9S-2: legacy-рубильник `UI_SHELL_V3` (hotfix8) больше не
        // «мёртвый» — OFF любого из двух флагов возвращает hotfix8-токены
        // (класс `.shell-v3-off`); дубль намерения сохранён как алиас.
        return this.uiFlag('UI_SHELL_GRAPHITE_V3')
          && this.uiFlag('UI_SHELL_V3');
      },
      liquidGlassLib: function () {
        return this.uiFlag('UI_LIQUID_GLASS_LIB');
      },
      auroraFlowV2: function () {
        return this.uiFlag('UI_AURORA_FLOW_V2');
      },
      // round 10.26 (ADR-1026-3 D2/D4): env-only флаг активного полигонального
      // фона (Canvas 2D + Delaunator). Default ON; OFF → мягкий откат к
      // Dark Aurora Flow по `auroraFlowV2`. Δ каталога = 0.
      polygonBgEnabled: function () {
        return this.uiFlag('UI_POLYGON_BG_ENABLED');
      },
      // HOTFIX7 (ADR-1025-13 D2.6): premium-рендер ECG; OFF → прежний
      // canvas-рендер (синусоида + импульс). `UI_HEARTBEAT_CANVAS_ENABLED=OFF`
      // по-прежнему уводит на legacy SVG (порядок: SVG → canvas legacy → ECG).
      heartbeatPremium: function () {
        return this.uiFlag('UI_HEARTBEAT_PREMIUM');
      },
      // F5 (T-1586, round1015) + F3 (round1017): бейджи фаз — оконная
      // семантика (spec §3а/§4) сохранена. Вне фазы — не светится и
      // показывает ОСТАТОК до начала (`fmtCountdown`); в активной — `.glow`
      // и время окончания (`fmtClock(active_until)`). UPD3 убрал ветку
      // «выключен»: при enabled=false показывается остаток без свечения.
      // `now` — серверный `generated_at` (ADR-1017-3 §2.1), не локальные часы.
      dreamPhaseBadge: function () {
        var c = this.cognition;
        if (!c) {
          // S10.17-2 (F2 T-1721): нет данных → чистый «—», без «через —».
          return { text: '—', cls: 'badge-muted' };
        }
        var d = c.dream || {};
        var now = Number(c.generated_at) || Math.floor(Date.now() / 1000);
        if (d.active) {
          if (d.active_until) {
            return { text: '🌙 Сон до ' + this.fmtClock(d.active_until),
                     cls: 'badge-ok glow' };
          }
          return { text: '🌙 Сон идёт', cls: 'badge-ok glow' };
        }
        if (d.state === 'limit_exhausted') {
          return { text: '☀️ Лимит сна исчерпан', cls: 'badge-warn' };
        }
        return { text: '☀️ Сон через ' +
                 this.fmtCountdown(Number(d.next_wake_at) - now),
                 cls: 'badge-muted' };
      },
      deepPhaseBadge: function () {
        var c = this.cognition;
        if (!c) {
          // S10.17-2 (F2 T-1721): нет данных → чистый «—», без «через —».
          return { text: '—', cls: 'badge-muted' };
        }
        var d = c.deep_sleep || {};
        var now = Number(c.generated_at) || Math.floor(Date.now() / 1000);
        if (d.active) {
          if (d.active_until) {
            return { text: '🌌 Глубокий сон до ' +
                     this.fmtClock(d.active_until), cls: 'badge-info glow' };
          }
          return { text: '🌌 Глубокий сон идёт', cls: 'badge-info glow' };
        }
        return { text: '🌅 Глубокий сон через ' +
                 this.fmtCountdown(Number(d.next_run_at) - now),
                 cls: 'badge-muted' };
      },
      // F5 (T-1455): бюджет контекста из аддитивного /api/status.context
      // (in-memory accounting); красный — урезание или загрузка > 90%.
      // D-7 (10.19): `unlimited` (бюджет `-1`) → «Безлимит (∞)», без
      // ложных 100% (used/limit).
      memoryContext: function () {
        var c = (this.statusData && this.statusData.context) || {};
        var unlimited = !!c.unlimited;
        var cap = unlimited ? 0 : (Number(c.limit) || 0);
        var used = (c.used == null) ? null : Number(c.used);
        var ratio = (used != null && cap > 0) ? (used / cap) : 0;
        return { used: used, limit: cap || null, unlimited: unlimited,
                 truncated: !!c.truncated, ratio: ratio,
                 red: !!c.truncated || ratio > 0.9 };
      },
      // F11 (10.25, ADR-1025-23 D6): kill-switch композиции Статуса.
      // Default ON; OFF → одноколоночный безопасный режим (`.status-grid--legacy`)
      // — НЕ byte-identical legacy-DOM (осознанное решение, M-F11S-1).
      statusGridV2: function () {
        return this.uiFlag('UI_STATUS_GRID_V2');
      },
      // F11 (§14/D2): честные системные метрики — `null` (нет данных) ≠ 0.
      // `ready` — пришла ли секция `server`; поля нормализованы в number|null.
      statusSys: function () {
        var s = (this.statusData && this.statusData.server) || null;
        function num(v) {
          return (v == null || v === '' || isNaN(Number(v))) ? null : Number(v);
        }
        function part(m) {
          if (!m || typeof m !== 'object') return null;
          return { used: num(m.used), total: num(m.total),
                   percent: num(m.percent) };
        }
        return {
          ready: !!s,
          cpu: s ? num(s.cpu_percent) : null,
          mem: s ? part(s.memory) : null,
          disk: s ? part(s.disk) : null,
          loadavg: (s && Array.isArray(s.loadavg)) ? s.loadavg : null,
          process: (s && s.process) || null,
        };
      },
      // F11 (§13/D2): последняя активность бота из uptime.last_heartbeat;
      // нет данных → «—» (не выдумываем).
      botLastActivity: function () {
        var u = (this.statusData && this.statusData.uptime) || null;
        if (!u || !u.last_heartbeat) return '—';
        return this.fmtLogTs(u.last_heartbeat);
      },
      // F11 (§17/D3): виджет сна — ЕДИНЫЙ источник времени (cognition,
      // серверный `generated_at`); активность ТОЛЬКО с сервера; countdown
      // считается от серверного времени (новых таймеров нет).
      sleepWidget: function () {
        var c = this.cognition;
        if (!c) return { ready: false, dream: null, deep: null, budget: null };
        var self = this;
        var now = Number(c.generated_at) || Math.floor(Date.now() / 1000);
        function phase(p, nextKey) {
          var active = !!p.active;
          var until = p.active_until || null;
          var next = (p[nextKey] != null) ? p[nextKey] : null;
          var secs = (next != null) ? (Number(next) - now) : null;
          return {
            active: active,
            until: until,
            lastRun: p.last_run_at || null,
            state: p.state || null,
            countdownSecs: secs,
            text: active
              ? (until ? ('до ' + self.fmtClock(until)) : 'идёт')
              : (secs != null ? ('через ' + self.fmtCountdown(secs)) : '—'),
          };
        }
        var d = c.dream || {};
        var ds = c.deep_sleep || {};
        return {
          ready: true,
          dream: phase(d, 'next_wake_at'),
          deep: phase(ds, 'next_run_at'),
          budget: d.budget || null,
        };
      },
      // F11 (§16/D4): группы узлов графа для витринного фильтра (вес/алгоритм
      // и layout НЕ меняются — только клиентское выделение).
      graphGroupOptions: function () {
        var g = this.cognitionGraphData || {};
        var seen = {}, out = [];
        (g.nodes || []).forEach(function (n) {
          var grp = n.group || 'other';
          if (!seen[grp]) { seen[grp] = true; out.push(grp); }
        });
        return out;
      },
      // F11 (§19/D5): «Новые факты» — стабильный ключ (позиция скролла не
      // сбрасывается); время/тип показываются ТОЛЬКО если есть в ответе
      // (follow-up F11-FU-DOSSIER-TS — не выдумываем).
      factsFeed: function () {
        var items = this.dossierFeed || [];
        return items.map(function (it) {
          var t = (it.created_at != null) ? it.created_at
            : (it.ts != null ? it.ts : null);
          return {
            key: 'ff|' + it.chat_id + '|' + it.name + '|' + (it.excerpt || ''),
            name: it.user_name || it.name || '',
            text: it.excerpt || '',
            time: (t != null) ? t : null,
            kind: it.kind || it.type || null,
          };
        });
      },
      // F11 (§16/D4): mobile-экран полного исследования графа доступен по
      // аддитивному hash-маршруту `#/status/graph` (владелец — F1) либо по
      // fallback-шторке (IA_V2_ENABLED=false).
      graphFullVisible: function () {
        return this.route === '#/status/graph' || this.graphFullOpen === true;
      },
      // ── Раунд 10.20 (БЛОК 3.6/T-1900): sticky-save — dirty-поля модалки ──
      // Значения, изменённые относительно baseline (configSnapshot), для
      // которых есть право записи. Секреты — отдельно (dirtyKeyItems).
      dirtyItems: function () {
        var self = this;
        var snap = this.configSnapshot || {};
        var out = [];
        (this.configItems || []).forEach(function (it) {
          if (!it || it.key == null) return;
          if (it.secret || it.category === 'keys') return;
          if (!self.canEditConfig(it.key)) return;
          if (!Object.prototype.hasOwnProperty.call(snap, it.key)) return;
          if (snap[it.key] !== self._serializeValue(it.value)) out.push(it);
        });
        return out;
      },
      dirtyKeyItems: function () {
        var self = this;
        var drafts = this.keyDrafts || {};
        return (this.configItems || []).filter(function (it) {
          return it && it.key != null
            && (it.category === 'keys' || it.secret)
            && !!drafts[it.key]
            // UPD3/R31: маска и её композит (`маска+ввод`) ≠ изменение.
            && !hasSecretMask(drafts[it.key])
            && self.canEditConfig(it.key);
        });
      },
      stickyDirtyCount: function () {
        return (this.dirtyItems || []).length + (this.dirtyKeyItems || []).length;
      },
      // F9 (ADR-1025-22 D3): статус BYOK-ключа чата — из `keyStatusOwn`
      // (GET /api/config/keys/status; R17: только {configured,last4}).
      byokSecret: function () {
        var own = (this.keyStatusOwn && this.keyStatusOwn.own) || {};
        var v = own['keys.llm_api_key'] || null;
        return { configured: !!v, last4: (v && v.last4) || '' };
      },
      // F0 (10.25, ADR-1025-2 D1): ЕДИНОЕ вычисляемое состояние формы —
      // loading | saving | error | conflict | dirty | clean (не набор флагов).
      // Визуальный слой SaveBar читает его (F0/F9), не дублирует логику.
      saveState: function () {
        if (this.configLoading) return 'loading';
        if (this.stickySaving) return 'saving';
        if (this.saving && this.saving.size > 0) return 'saving';
        if (this.stickyConflict && this.stickyConflict.length) return 'conflict';
        if (this.stickyFailed && this.stickyFailed.length) return 'error';
        if (this.stickyDirtyCount > 0) return 'dirty';
        return 'clean';
      },
      // ── Раунд 10.20 (БЛОК 3.3/T-1897): модель «Живой ленты досье» ──
      // Дублирование для seamless-скролла (тот же приём, что у лент
      // «Осмысления»/_ribbonLoop) + подпись чата из oversight-кэша.
      // F4 (10.24, ADR-1024-8 D3/D4): переносим user_id/user_name/chat_id —
      // строка с user_id становится кликабельной (openFeedDossier).
      dossierFeedLoop: function () {
        var items = this.dossierFeed || [];
        if (!items.length) return [];
        var titles = {};
        var chats = (this.oversightData && this.oversightData.chats) || [];
        chats.forEach(function (c) { titles[c.chat_id] = c.title; });
        var marked = items.map(function (it, i) {
          return {
            key: 'df' + i + '-' + it.chat_id + '-' + it.name,
            name: it.name,
            user_name: it.user_name || it.name,
            user_id: (it.user_id == null ? null : it.user_id),
            chat_id: it.chat_id,
            excerpt: it.excerpt,
            chatLabel: titles[it.chat_id] || ('Чат ' + it.chat_id),
            dup: false,
          };
        });
        // F4 review iter1: клон помечаем `dup` — он нужен только для
        // бесшовного цикла, но НЕ должен попадать в таб-порядок/дерево
        // доступности (aria-hidden) и не должен быть интерактивным.
        return marked.concat(marked.map(function (it) {
          return Object.assign({}, it, { key: it.key + '-dup', dup: true });
        }));
      },
      // F4 (10.24, ADR-1024-8 D1): скорость вертикальной ленты —
      // max(72s, items × 6s): длиннее список → скорость строки НЕ растёт
      // (лента заметно медленнее прежней горизонтали 42s).
      dossierFeedSpeed: function () {
        var n = (this.dossierFeed || []).length;
        return Math.max(72, n * 6) + 's';
      },
      cognitionBeliefsLoop: function () {
        return this._ribbonLoop(this.cognitionBeliefs);
      },
      cognitionParadigmsLoop: function () {
        return this._ribbonLoop(this.cognitionParadigms);
      },
      // F4 (persona-traits-ribbon-round1014): лента «Эволюция характера» —
      // тот же механизм `_ribbonLoop`, без дублирования (spec §0/§2).
      cognitionTraitsLoop: function () {
        return this._ribbonLoop(this.cognitionTraits);
      },
      // F8 (dead-extractor-paradigms-round1024, ADR-1024-5 D3/UPD3 №4):
      // пояснительный Empty State — понятная причина пустоты ленты.
      cognitionParadigmsEmptyReason: function () {
        return this.emptyReasonLabel(
          this.cognitionParadigmsReason, this.cognitionParadigmsStatus);
      },
      cognitionTraitsEmptyReason: function () {
        return this.emptyReasonLabel(
          this.cognitionTraitsReason, this.cognitionTraitsStatus);
      },
      // F4 (UPD п.4): бейдж статуса экстрактора самосознания для панели
      // «Личность» в «Сводке». Fail-open: нет данных → «не запускался».
      personaExtractorBadge: function () {
        var h = this.personaHealth || {};
        var s = h.extractor_status || 'never';
        return {
          ok: { text: 'работает', cls: 'badge-ok' },
          empty: { text: 'пустой результат', cls: 'badge-muted' },
          error: { text: 'ошибка', cls: 'badge-err' },
          never: { text: 'не запускался', cls: 'badge-muted' },
        }[s] || { text: String(s), cls: 'badge-muted' };
      },
      canEditInfo: function () {
        return this.hasPerm('action.edit_info');
      },
      sanitizedInfoHtml: function () {
        return this.sanitizeHtml(this.infoHtml);
      },
      // F6: гайд → Markdown→HTML→санитайз. v-html получает ТОЛЬКО это.
      sanitizedGuideHtml: function () {
        return this.sanitizeHtml(this.renderGuideMarkdown(this.guideHtml));
      },
      sanitizedGuidePreviewHtml: function () {
        return this.sanitizeHtml(this.renderGuideMarkdown(this.guideDraft));
      },
      // F1 (T-2400): «Справка» — оглавление + якоря заголовков. HTML берём
      // уже санитайзенный; добавляем только id к h1..h3 (стиль не меняем).
      helpContent: function () {
        var info = this._anchorHtml(this.sanitizedInfoHtml, 'info');
        var guide = this._anchorHtml(this.sanitizedGuideHtml, 'guide');
        return {
          infoHtml: info.html,
          guideHtml: guide.html,
          toc: info.anchors.concat(guide.anchors),
        };
      },
      filteredHelpToc: function () {
        var q = (this.helpQuery || '').trim().toLowerCase();
        var toc = this.helpContent.toc;
        if (!q) return toc;
        return toc.filter(function (a) {
          return a.text.toLowerCase().indexOf(q) >= 0;
        });
      },
      confirmText: function () {
        var labels = {
          restart: 'Перезапустить бота? Текущий процесс будет остановлен (graceful shutdown) и поднят заново.',
          stop: 'Остановить бота? Бот останется выключенным до ручного/веб-запуска.',
          start: 'Запустить бота?',
        };
        return labels[this.confirmAction] || '';
      },
      // 10.7 (1a): scope-производные — именно computed, иначе шаблонные
      // привязки без вызова (`{{ scopeLabel }}`) печатают
      // `function () { [native code] }` (Vue биндит методы).
      // T-1127/§15.1.1: вид scope для UI (GLOBAL/ЧАТ/ЛС) — производная от
      // activeChatId/isDmCtx. X-Chat-Id: null=GLOBAL, <0=ЧАТ, >0=ЛС.
      scopeKind: function () {
        if (this.activeChatId == null) return 'global';
        return this.isDmCtx() ? 'dm' : 'chat';
      },
      scopeLabel: function () {
        if (this.scopeKind === 'global') return 'GLOBAL';
        return this.scopeKind === 'dm' ? 'ЛС' : 'ЧАТ';
      },
      // T-1127: пункты dropdown (GLOBAL + ЧАТы + ЛС), RBAC-список с сервера.
      scopeOptions: function () {
        var q = (this.scopeSearch || '').toLowerCase();
        var opts = [];
        if (this.isGlobalAdmin) {
          opts.push({ key: 'global', kind: 'global', chat_id: null,
                      title: 'Весь бот', subtitle: 'Глобальные настройки',
                      badge: 'GLOBAL', initial: 'В' });
        }
        var chats = [];
        var dms = [];
        this.accessChats.forEach(function (c) {
          var o = {
            key: String(c.chat_id),
            kind: c.is_dm ? 'dm' : 'chat',
            chat_id: c.chat_id,
            title: c.title || ('Чат ' + c.chat_id),
            subtitle: c.is_dm ? 'Личные сообщения' : (c.access || ''),
            badge: c.is_dm ? 'ЛС' : '',
            is_dm: !!c.is_dm,
            photo_file_id: c.photo_file_id,
            avatarUrl: c.avatarUrl || '',
            initial: (c.title || String(c.chat_id)).slice(0, 1),
          };
          if (c.is_dm) dms.push(o); else chats.push(o);
        });
        function filt(list) {
          if (!q) return list;
          return list.filter(function (o) {
            return o.title.toLowerCase().indexOf(q) >= 0;
          });
        }
        return opts.concat(filt(chats), filt(dms));
      },
      scopeTriggerTitle: function () {
        return this.activeChatId == null ? 'Весь бот' : this.activeChatTitle;
      },
      scopeTriggerInitial: function () {
        return (this.scopeTriggerTitle || '?').slice(0, 1);
      },
      scopeTriggerAvatar: function () {
        var self = this;
        if (this.activeChatId == null) return '';
        var c = this.accessChats.find(function (x) {
          return x.chat_id === self.activeChatId;
        });
        return (c && c.avatarUrl) || '';
      },
    },

    // F6 (T-1461, §3.2): изменение селектора уровня сразу перезагружает лог —
    // селектор == запрос == рендер (устранение рассинхрона). Смена вкладки
    // (setTab) лог не перезагружает → дефолт при открытии сохраняется.
    watch: {
      logLevel: function () {
        this.loadLogs();
      },
      // F11 (§16/D4): смена режима графа (mobile-упрощение ↔ отдельный экран
      // полного исследования) — пере-рендер vis.Network (режим входит в
      // сигнатуру рендера). Сеть читается только на «Статусе».
      graphFullVisible: function () {
        var self = this;
        this.$nextTick(function () {
          self.renderCognitionGraph();
          self._focusGraphFull();
        });
      },
      // F11 (§16/D4): смена shell-режима (пересечение 768px) — граф
      // переключается между упрощённым и полным.
      shellMode: function () {
        var self = this;
        this.$nextTick(function () { self.renderCognitionGraph(); });
      },
      // F8 (ADR-1023-8): при переходе на «Промпты» синхронизируем режим и
      // подтягиваем блок анти-клише (идемпотентно, fail-open).
      activeTab: function (id) {
        if (id === 'prompts') {
          this._syncPromptModeFromConfig();
          this.maybeLoadCliche();
        }
        // F2 (T-2540): после смены вкладки контент v-if достраивается позже —
        // пересчитываем уровень стекла после рендера (в дополнение к observer).
        var self = this;
        this.$nextTick(function () { self._lgSchedule(); });
        // HOTFIX9 D5 (T-2817): новые целевые узлы (Статус) могли появиться —
        // точечно монтируем стекло после рендера.
        this.$nextTick(function () { self._syncGlassLib(); });
        // hotfix6/C2 (T-2599, MEDIUM): rAF-цикл сердебиения живёт ТОЛЬКО на
        // «Статусе»; возврат — перерисовка кадра после монтирования канваса
        // (в т.ч. reduced-motion: статичный кадр, без пустого канваса).
        if (id === 'status') {
          this.$nextTick(function () { self.startHeartbeatCanvas(); });
        } else {
          this.stopHeartbeatCanvas();
        }
      },
      // S9 (ADR-1026-8 D1): при открытии вкладки «Тестирование» модуля «Сводки
      // чатов» — однократный probe доступности API (идемпотентно, fail-open).
      workspaceTab: function (tab) {
        if (tab === 'testing') this.maybeLoadSummaryTest();
      },
    },

    // T-1099/§6.2 п.1-4: initData — ДО hash. created() вычисляет стартовый
    // маршрут и синхронизирует activeTab (производная от route); loader
    // активной вкладки дёргается позже в mounted после auth.
    created: function () {
      getInitData();                       // кэш initData ДО записи hash
      this._syncShellMode();               // F1: shell-режим по ширине
      this.initExpandState();              // F24: реактивный стейт аккордеонов
      this.initQuickpicks();               // F4 D4: избранное модулей (fail-open)
      var r = initialRoute();
      this.route = r;
      var tabId = routeToTab(r);
      if (tabId) this.activeTab = tabId;
      var found = this.tabs.find(function (t) { return t.id === tabId; });
      // §6.2 п.4: не перезаписываем launch-hash «в лоб» — replaceState.
      if (!normalizeRoute(window.location.hash)) {
        try { history.replaceState(null, '', r); } catch (e) { /* file:// */ }
      }
    },

    mounted: function () {
      var self = this;
      // T-1099/§6.4.4: hashchange — ЕДИНСТВЕННЫЙ «применитель» роута;
      // BackButton.onClick регистрируется ровно ОДИН раз на BOOT (без
      // перерегистрации → без накопления stale-колбэков/петель).
      _appVm = this;
      _onHashChange = function () {
        // F1 (T-2396): неизвестный '#/…'-hash → канонический '#/' (replaceState),
        // launch-hash без '#/' игнорируем как раньше.
        var raw = window.location.hash;
        var norm = normalizeRoute(raw);
        if (!norm && typeof raw === 'string' && raw.indexOf('#/') === 0) {
          try { history.replaceState(null, '', '#/'); } catch (e) { /* file:// */ }
          norm = '#/';
        }
        _appVm.applyRoute(norm || '#/');
      };
      window.addEventListener('hashchange', _onHashChange);
      // F1 (§6/§7): пересчёт shell-режима при ресайзе (sidebar строго ≥1200).
      // F2 (T-2540): + пересчёт уровня A стекла (min-сторона ≥240).
      _onResize = function () {
        if (_appVm) {
          _appVm._syncShellMode();
          _appVm.reconcileLiquidGlass();
          if (typeof _appVm._hbResize === 'function') _appVm._hbResize();
        }
        // HOTFIX10 (ADR-1025-18 D5, T-2857): пересчёт геометрии OGL-фона по
        // фактическому размеру контейнера (buffer/viewport/uniforms).
        _auroraResize();
      };
      window.addEventListener('resize', _onResize);
      // HOTFIX10 (ADR-1025-18 D5): visualViewport (fullscreen/клавиатура/поворот)
      // может менять видимую область без window-resize — пересчитываем фон.
      // F9 (ADR-1025-22 D5): + keyboard-offset для SaveBar/последнего поля.
      if (window.visualViewport
          && typeof window.visualViewport.addEventListener === 'function') {
        _onVV = function () {
          if (_appVm && typeof _appVm._hbResize === 'function') _appVm._hbResize();
          _auroraResize();
          if (_appVm && typeof _appVm._syncKeyboardOffset === 'function') {
            _appVm._syncKeyboardOffset();
          }
        };
        window.visualViewport.addEventListener('resize', _onVV);
        // F9 (D5): клавиатура/скролл visualViewport без resize (iOS) — тоже.
        window.visualViewport.addEventListener('scroll', _onVV);
      }
      // MODERATE-2 + 10.8 (R10.8-1): глобальный Esc закрывает модалку модуля
      // И route-driven окна «Доступов» (фокус может быть вне модалки —
      // keydown на карточке недостаточно; закрытие окна = hash → #/access).
      _onKeydown = function (e) {
        if (e.key === 'Escape' && _appVm) {
          _appVm.escClose();
        }
      };
      window.addEventListener('keydown', _onKeydown);
      // F5-Q3: пауза polling «Осмысления» при сворачивании TMA (hidden).
      _onVisibility = function () {
        if (_appVm) _appVm.onVisibilityChange();
      };
      document.addEventListener('visibilitychange', _onVisibility);
      try {
        this.reducedMotion = !!(window.matchMedia &&
          window.matchMedia('(prefers-reduced-motion: reduce)').matches);
      } catch (e) { this.reducedMotion = false; }
      this.initFullscreen();               // F24: синхронизация с TMA-fullscreen
      this._syncBgLayer();                 // HOTFIX8: aurora↔legacy page-wash
      this.initBackButton();
      // F2 (T-2540): страховка «крупного элемента» для уровня A стекла.
      this.reconcileLiquidGlass();
      this._initLiquidGlassObserver();
      // hotfix6/C2 (ADR-1025-12 D4): Canvas-2D «сердцебиение» §15 + D3 —
      // измерение высоты шапки в `--header-h` (резерв контента).
      this.$nextTick(function () { self.startHeartbeatCanvas(); });
      this._initHeaderHeight();
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
        self._syncBgLayer();              // HOTFIX8: флаги shell v3/aurora получены
        // Контекст чата (activeChatId) — ДО loadConfig: первый рендер сразу
        // в per-chat слое (F-7 T-854); без контекста — старый глобальный вид.
        self.loadAccessCtx().then(function () {
          self.loadConfig();
          self.loadKeyStatus();
          if (self.canViewTab('access')) self.loadLocalAdmins();
        });
        if (self.isGlobalAdmin) {
          self.loadOversight();     // F-12: сводка (кэш сервера 60с)
        }
        if (self.canViewTab('access')) {
          self.loadAdmins();
          self.loadRoles();
        }
        // 3.10 (Q6): probe-список «Лор чатов» — без секции chat_lore вкладка
        // видна только при непустом списке (per-chat админ); пустой список
        // вкладку НЕ показывает. 403/503 в probe — молча (вкладка скрыта).
        if (!self.hasPerm('section.chat_lore')) {
          self.loadChats(true);
        }
        // ФИКС 2026-09-03: данные АКТИВНОЙ вкладки (по умолчанию 'status')
        // не грузились до первого переключения — loaders вызывались только
        // в setTab. Теперь после успешной авторизации вызываем per-tab
        // loader активной вкладки (loadStatus+loadLogs+polling для 'status').
        self.setTab(self.activeTab);
        self.applyRoute(self.route);   // T-1099: персист + syncBackButton
      });
      // Опц. рекомендация ревью: контекст Telegram может появиться ПОЗЖЕ
      // готовности WebView — подписываемся на событие ready (дебаунс —
      // флаг retriedOnce, чтобы не дублировать запросы).
      if (window.Telegram && Telegram.WebApp && Telegram.WebApp.onEvent) {
        Telegram.WebApp.onEvent('ready', function () {
          // R10.5-1: BackButton может стать доступен только к `ready` —
          // переинициализируем (onClick — ровно один раз) + sync видимости.
          self.initBackButton();
          // F24 (C3): контекст Telegram может появиться ПОЗЖЕ монтирования —
          // переинициализируем fullscreen (guard не даёт двойных подписок).
          self.initFullscreen();
          self.retryInitData();
        });
      }
    },

    methods: {
      // P0 (prod-incident F1, 21.09.2026): `stickyFieldFailed` ошибочно лежал
      // в `computed` → шаблоны (`index.html`) вызывают его как функцию
      // `stickyFieldFailed(item.key)`; computed-геттер отдавал boolean →
      // `TypeError: stickyFieldFailed is not a function` в render → пустой
      // generic config-раздел (`#/ai/llm`, `#/ai/names`, `#/ai/smart-cache`,
      // `#/memory/rag`, …). Перенесён в `methods` (тело не менялось).
      stickyFieldFailed: function (key) {
        return (this.stickyFailedKeys || []).indexOf(key) >= 0;
      },
      // F6 round 10.21 (T-1998): ранее объявлен в `computed` → вызывался как
      // функция и падал `this._syntheticGroup is not a function` при открытии
      // окна модуля «Выжимка видео» (Vue render-error, модалка не строилась).
      // Перенесён в `methods` — `activeModuleGroups` вызывает его с аргументами.
      _syntheticGroup: function (category, gid) {
        var q = (this.configSearch || '').trim().toLowerCase();
        var items = this.configItems.filter(function (it) {
          if (it.category !== category || it.group !== gid) return false;
          if (!q) return true;
          return (it.title || '').toLowerCase().indexOf(q) >= 0
            || (it.key || '').toLowerCase().indexOf(q) >= 0;
        });
        if (!items.length) return null;
        var meta = null;
        this.configGroups.forEach(function (g) { if (g.id === gid) meta = g; });
        return { uid: category + '/' + gid, id: gid, category: category,
                 meta: meta, items: items };
      },

      hasInitData: function () {
        // T-1099/§6.2 п.1: initData читается/кэшируется ДО hash; фолбэк —
        // sessionStorage (переживает перезаброс launch-hash при refresh).
        return !!getInitData();
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
          self.loadAccessCtx().then(function () {
            self.loadConfig();
            self.loadKeyStatus();
            if (self.canViewTab('access')) self.loadLocalAdmins();
          });
          if (self.canViewTab('access')) {
            self.loadAdmins();
            self.loadRoles();
          }
          // 3.10 (Q6): probe-список «Лор чатов» — без секции chat_lore
          // вкладка видна только при непустом списке (per-chat админ).
          if (!self.hasPerm('section.chat_lore')) {
            self.loadChats(true);
          }
          // ФИКС 2026-09-03: автозагрузка активной вкладки (как в mounted)
          self.setTab(self.activeTab);
        });
      },

      // ═══ API-обёртка (84.6: X-Telegram-Init-Data на каждый запрос) ═══
      // Раунд 10 (F-7 T-854): активный чат → заголовок X-Chat-Id (контекст
      // per-chat слоя chat_params; NULL → старый глобальный вид).
      api: async function (path, options) {
        // Без Telegram-контекста запросы бессмысленны (401 вхолостую) —
        // заглушка вместо спама в API (фин. доработка DevOps).
        if (this.authLocked || !this.hasInitData()) {
          throw new ApiError(401, 'no telegram context');
        }
        options = options || {};
        // Раунд 10.12 (ADR-1012-1 D2): `global:true` — запрос НЕ получает
        // X-Chat-Id (глобальные ключи per_chat=false сохраняются глобально).
        // Флаг не должен утекать в fetch-инициализатор.
        var init = Object.assign({}, options);
        delete init.global;
        init.headers = Object.assign({}, options.headers || {});
        if (!init.headers['Content-Type'] && init.body) {
          init.headers['Content-Type'] = 'application/json';
        }
        if (this.activeChatId != null && options.global !== true) {
          init.headers['X-Chat-Id'] = String(this.activeChatId);
        }
        var initData = getInitData();   // T-1099: тот же кэш, что на BOOT
        if (initData) {
          init.headers['X-Telegram-Init-Data'] = initData;
        }
        var resp = await fetch(path, init);
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

      // ═══ UI-полировка TMA: аватары (fix-раунд — blob-fetch) ═══
      // Прямой <img src="/api/avatar/..."> ловит 401 (браузер грузит
      // картинку без X-Telegram-Init-Data). Вместо этого avatarUrl():
      // fetch прокси с заголовком initData → blob → createObjectURL;
      // результат кладётся в реактивное поле объекта и img рисуется по
      // v-if. Ошибка (401/404/сеть) → null: img не показываем вовсе.
      avatarUrl: async function (kind, id) {
        if (kind == null || id == null) return null;
        var key = kind + ':' + id;
        var hit = _avatarCache.get(key);
        if (hit) return hit;
        var initData = '';
        try {
          initData = (window.Telegram && Telegram.WebApp
            && Telegram.WebApp.initData) || '';
        } catch (e) { initData = ''; }
        if (!initData) return null;      // вне Telegram-контекста — нет фото
        var resp = null;
        try {
          resp = await fetch('/api/avatar/' + kind + '/' + id, {
            headers: { 'X-Telegram-Init-Data': initData },
          });
        } catch (e) { return null; }
        if (!resp.ok) return null;       // 401/404/5xx — фото нет (не кэш)
        try {
          var blob = await resp.blob();
          var url = URL.createObjectURL(blob);
          _avatarCache.set(key, url);
          if (_avatarCache.size > _AVATAR_CACHE_MAX) {
            var oldestKey = _avatarCache.keys().next().value;
            if (oldestKey != null) {
              var oldUrl = _avatarCache.get(oldestKey);
              _avatarCache.delete(oldestKey);
              try { if (oldUrl) URL.revokeObjectURL(oldUrl); } catch (e2) {}
            }
          }
          return url;
        } catch (e) { return null; }
      },

      // Загрузка аватара в реактивное поле obj.avatarUrl (строки списков
      // чатов/участников). Вызывается из loadChats/loadRelations — img
      // показывается через v-if="…photo_file_id != null && ….avatarUrl".
      loadAvatar: async function (kind, id, obj) {
        var url = await this.avatarUrl(kind, id);
        if (obj) obj.avatarUrl = url;
        return url;
      },

      // Hotfix-R10 (аватары вне серверного топ-50): ленивый догруз — НЕ
      // батч-запрос всех аватаров разом (NFR F-8): стаггер 300мс между
      // вызовами. Отрицательный ответ (нет фото/404) — u.avatarSkipped,
      // повторные обходы листа не перезапрашивают; до результата/негатива
      // в листе фолбэк-инициал (avatarInitial) и img по v-if="u.avatarUrl".
      loadRelationAvatarsLazy: function (rows) {
        var self = this;
        var missing = (rows || []).filter(function (u) {
          return u && u.user_id != null && u.photo_file_id == null
            && !u.avatarUrl && !u.avatarSkipped;
        });
        missing.forEach(function (u, idx) {
          setTimeout(function () {
            if (u.avatarUrl || u.avatarSkipped) return;
            self.loadAvatar('user', u.user_id, u).then(function (url) {
              if (!url) u.avatarSkipped = true;
            });
          }, (idx + 1) * 300);
        });
      },

      // Шапка: аватар текущего юзера — ТОЛЬКО same-origin blob-прокси
      // /api/avatar (S10.16-8/F4). Внешний Telegram-CDN (me.photo_url из
      // initData) запрещён строгим CSP `img-src 'self' data: blob:` и
      // редиректит на cdn*.telesco.pe → лишний внешний запрос + CSP-violation.
      // Повторный вызов (после loadMe/ре-авторизации) сбрасывает поле —
      // аватар может появиться, даже если раньше не загрузился.
      refreshMeAvatar: function () {
        var self = this;
        var me = this.me;
        this.meAvatarUrl = '';
        if (!me || me.telegram_id == null) return;
        this.loadAvatar('user', me.telegram_id).then(function (url) {
          if (url && self.me) self.meAvatarUrl = url;
        });
      },

      // @error аватара в шапке: blob-URL прокси битым быть не должен, но
      // fail-closed — сбрасываем поле (img по v-if скрывается); следующий
      // refreshMeAvatar после loadMe попробует снова.
      onMeAvatarError: function () {
        this.meAvatarUrl = '';
      },

      // @error аватаров в списках: сброс поля → v-if убирает битый img;
      // при следующей загрузке списка loadAvatar поставит URL снова (если
      // фото появилось/серверный негатив-кэш 1ч протух). Не style.display:
      // тот не дал бы img показаться при ре-рендере.
      avatarError: function (obj) {
        if (obj) obj.avatarUrl = null;
      },

      // F9 (10.25, ADR-1025-22 D5): keyboard-offset для SaveBar/последнего поля.
      // visualViewport-геометрия: `innerHeight - (vv.height + vv.offsetTop)`
      // (экранная клавиатура). CSS-переменная `--kb-offset` применяется к
      // `.modal-actions`/`.sticky-save`/`.modal-card` (safe-area уже учтён
      // РОВНО ОДИН РАЗ в `.sticky-save` — здесь только клавиатура). Активное
      // поле в скролл-области приводим в видимость `block:'nearest'`.
      _syncKeyboardOffset: function () {
        var vv = window.visualViewport;
        var root = (typeof document !== 'undefined') ? document.documentElement : null;
        var offset = 0;
        if (vv && typeof vv.height === 'number') {
          var innerH = window.innerHeight || 0;
          offset = Math.max(0, Math.round(innerH - (vv.height + (vv.offsetTop || 0))));
        }
        if (root && root.style) {
          root.style.setProperty('--kb-offset', offset + 'px');
        }
        if (!offset || typeof document === 'undefined') return;
        var el = document.activeElement;
        if (!el || typeof el.closest !== 'function') return;
        var tag = (el.tagName || '').toLowerCase();
        if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') return;
        if (!el.closest('.modal-body, .scroll-area')) return;
        if (typeof el.scrollIntoView === 'function') {
          try { el.scrollIntoView({ block: 'nearest' }); } catch (e) { /* no-op */ }
        }
      },

      toast: function (text, kind) {
        // F0.4 (ADR-1025-4 D1/D3): стабильный id, дедуп (текст+kind) в окне,
        // очередь ≤3 с приоритетом err>warn>ok. Сигнатура обратно совместима.
        if (this._suppressToast) return;
        if (text == null) return;
        var self = this;
        var k = kind || 'ok';
        var existing = this.toasts || [];
        for (var i = 0; i < existing.length; i++) {
          if (existing[i].text === text && existing[i].kind === k) return;
        }
        var priority = { err: 3, warn: 2, ok: 1 };
        var id = 'ts' + (++this._toastSeq);
        var entry = { id: id, text: String(text), kind: k,
                      priority: priority[k] || 1, expanded: false };
        var next = existing.concat([entry]);
        var MAX_VISIBLE = 3;
        // L-4 (ревью): при переполнении вытесняем САМЫЙ СТАРЫЙ тост
        // наименьшего приоритета (а не только что добавленный — новый виден).
        while (next.length > MAX_VISIBLE) {
          var dropIdx = 0;
          for (var j = 1; j < next.length; j++) {
            if ((next[j].priority || 1) < (next[dropIdx].priority || 1)) {
              dropIdx = j;
            }
          }
          next.splice(dropIdx, 1);
        }
        next.sort(function (a, b) { return (b.priority || 1) - (a.priority || 1); });
        this.toasts = next;
        setTimeout(function () {
          self.toasts = (self.toasts || []).filter(function (t) {
            return t.id !== id;
          });
        }, 4200);
      },

      // ═══ Раунд 10 (F-7 T-854): контекст чата ═══
      // activeChatId: persist localStorage; NULL = «Весь бот» (глобальный).
      loadAccessCtx: async function () {
        try {
          var data = await this.api('/api/access/me');
          this.accessMy = data;
          var chats = await this.api('/api/access/chats');
          this.accessChats = Array.isArray(chats) ? chats : [];
          var saved = localStorage.getItem('adminbot.active_chat_id');
          var savedOk = saved != null
            && this.accessChats.some(function (c) {
              return String(c.chat_id) === String(saved);
            });
          if (savedOk) {
            this.activeChatId = parseInt(saved, 10);
          } else if (saved != null) {
            localStorage.removeItem('adminbot.active_chat_id');
            this.activeChatId = null;
          }
          // Локальный админ/mod-грант без глобального режима → первый доступный
          if (this.activeChatId == null && !data.is_global_admin
              && this.accessChats.length) {
            this.activeChatId = this.accessChats[0].chat_id;
          }
          this.syncActiveChatTitle();
        } catch (e) {
          // фолбэк: часть-1 не выкатана / 403 — глобальный режим (старое)
          this.accessChats = [];
          this.accessMy = null;
          if (this.activeChatId != null) {
            this.activeChatId = null;
          }
          this.syncActiveChatTitle();
        }
      },
      syncActiveChatTitle: function () {
        var self = this;
        if (this.activeChatId == null) {
          this.activeChatTitle = 'Весь бот';
          return;
        }
        var found = this.accessChats.find(function (c) {
          return c.chat_id === self.activeChatId;
        });
        this.activeChatTitle = (found && found.title)
          || ('Чат ' + this.activeChatId);
      },
      // F3 (§5.1/§5.2): есть ли несохранённые правки формы. Проверяем
      // защитно — тесты/минимальный контекст без полного стейта не должны
      // падать (иначе возвращаем false = «чисто»).
      hasUnsavedEdits: function () {
        try {
          if (typeof this.stickyDirtyCount === 'number'
              && this.stickyDirtyCount > 0) return true;
        } catch (e) { /* нет computed — считаем чисто */ }
        if (this.saving && typeof this.saving.size === 'number'
            && this.saving.size > 0) return true;
        if (this.dirtyItems && this.dirtyItems.length) return true;
        if (this.dirtyKeyItems && this.dirtyKeyItems.length) return true;
        // F3 (reviewer High): state, который setActiveChat() молча чистит,
        // тоже считается несохранёнными правками (иначе потеря ввода):
        //   * blockDrafts — поля provider-блоков, в т.ч. введённый API-ключ
        //     (в объект попадают ТОЛЬКО отредактированные поля → непусто=правка);
        //   * ownKeyDraft — введённый BYOK-ключ активного чата.
        if (this.blockDrafts && typeof this.blockDrafts === 'object') {
          for (var bk in this.blockDrafts) {
            if (Object.prototype.hasOwnProperty.call(this.blockDrafts, bk)) {
              return true;
            }
          }
        }
        if (typeof this.ownKeyDraft === 'string' && this.ownKeyDraft.trim()) {
          return true;
        }
        // personaDraft инициализируется серверными значениями → сравниваем
        // с baseline (personaMeta.values), а не с null.
        if (this.personaDraft) {
          var pv = (this.personaMeta && this.personaMeta.values) || null;
          if (!pv) return true;
          if ((this.personaDraft.name || '') !== (pv.name || '')
              || (this.personaDraft.biography || '') !== (pv.biography || '')
              || (this.personaDraft.system_prompt_overrides || '')
                 !== (pv.system_prompt_overrides || '')
              || !!this.personaDraft.is_aware_ai !== !!pv.is_aware_ai) {
            return true;
          }
        }
        // dossierDraft инициализируется серверным manual_traits → baseline.
        // Сравниваем и пустую строку (очистка поля ≠ отсутствие правки).
        if (this.dossierData
            && this.dossierDraft !== (this.dossierData.manual_traits || '')) {
          return true;
        }
        return false;
      },
      setActiveChat: function (chatId) {
        var id = (chatId == null || chatId === '') ? null : parseInt(chatId, 10);
        this.scopeOpen = false;
        if (id === this.activeChatId) return;
        // F3 (§5.1/§5.2): смена области при несохранённых правках — сначала
        // предупредить; отказ = область НЕ меняем (черновик не теряем).
        if (typeof this.hasUnsavedEdits === 'function' && this.hasUnsavedEdits()) {
          var proceed = true;
          try {
            proceed = (typeof window === 'undefined'
              || typeof window.confirm !== 'function')
              || window.confirm('Есть несохранённые изменения. '
                + 'Переключить область и потерять их?');
          } catch (e) { proceed = true; }
          if (!proceed) return;
        }
        this.activeChatId = id;
        if (id == null) {
          localStorage.removeItem('adminbot.active_chat_id');
        } else {
          localStorage.setItem('adminbot.active_chat_id', String(id));
        }
        this.syncActiveChatTitle();
        // T-1127/§15.1.7: смена scope — единый сброс chat-scoped состояния
        // (обобщение R10.4-2): epoch отбрасывает устаревшие in-flight
        // ответы, чистим relations/лор/гейты/локальных админов/модалки.
        this.scopeEpoch++;
        // F4 (L-F4-3): операции модулей привязаны к scope-ключу; при смене
        // области карты overlay/блокировок/ошибок не переносятся в новую
        // область (состояние читается из configItems новой области).
        this.moduleOptimistic = {};
        this.modulePending = {};
        this.moduleSaveError = {};
        this.chatLoreProfile = null;
        this.chatLoreSelectedId = null;
        this.chatLoreHistory = [];
        this.chatLore409 = null;
        this.gateInfo = null;
        this.chatAdmins = [];
        this.permPickerOpen = false;
        this.permPickerItem = null;
        // Ревью-фикс (R10.4-2, класс кросс-чата): смена активного чата
        // сбрасывает список участников (иначе на вкладке relations виден
        // старый список чата A, а запись уходит в чат B); при открытой
        // вкладке relations — сразу перезагрузка для нового чата.
        this.chatRelations = [];
        if (this.activeTab === 'relations' && this.canViewTab('relations')
            && this.activeChatId != null && !this.isDmCtx()
            && !this.relationsBusy) {
          this.loadRelations(this.activeChatId);
        } else {
          this.relationsEnabled = false;
        }
        // перерисовка конфиг-вкладок/профиля (activeChatChanged-событие)
        this.configError = '';   // F-13 (AC-3): свежий скоуп — баннер скрыт
        this.configItems = [];
        // F5 (10.14, T-1514): scope-bound метка/черновики не переезжают в чат.
        this.configChatUpdatedAt = null;
        this.keyDrafts = {}; this.ownKeyDraft = '';
        // 10.10 (п.3): смена scope — сброс черновиков/результатов блоков
        // (draft==null = «не трогать»; старый результат теста неактуален).
        this.blockDrafts = {};
        this.blockResults = {};
        // F3 (10.14): «Личность» — черновик НЕ переживает смену scope
        // (согласовано с F5); при активном экране сразу читаем свой скоуп.
        this.personaDraft = null;
        this.personaMeta = null;
        this.personaLoading = false;
        if (this.activeTab === 'persona' && this.canViewTab('persona')) {
          this.loadPersona();
        }
        this.loadConfig();
        this.loadKeyStatus();
        // 10.20 (БЛОК 5.4, S10.19-15): реактивность «Сводки» по chat_id —
        // «Бюджет контекста» (per-chat /api/status.context) и «Дневной фон»
        // (/api/workers/budget) перечитываются при смене чата. Один запрос
        // на виджет (без дублей); активная вкладка 'status' — уже видна.
        if (this.activeTab === 'status' && this.canViewTab('status')) {
          this.loadStatus();
          if (this.isGlobalAdmin) {
            this.loadOversight();
          }
        }
        // 10.20 (T-1897): «Живая лента досье» — при смене чата один запрос
        // (GLOBAL → все чаты; конкретный чат → только его участники).
        if (this.activeTab === 'oversight' && this.isGlobalAdmin) {
          this.stopDossierFeedPolling();
          this.startDossierFeedPolling();
        }
        if (this.accessMy && !this.accessMy.is_global_admin) {
          this.loadLocalAdmins();
        }
        // Hotfix-R10 («Модули»/PERMsoc): гейты/пермсок — per chat;
        // при смене «Весь бот» ↔ чат на этих вкладках перечитываем
        // (иначе стейл-флаги).
        if ((this.activeTab === 'modules' || this.activeTab === 'permsoc')
            && this.canViewTab(this.activeTab)) {
          this.loadGateInfo();
        }
        if (this.activeTab !== 'modules'
            && this.activeTab !== 'permsoc'
            && this.activeChatId != null) {
          // смена контекста сбрасывает стейл-гейты для «Модулей»/PERMsoc
          this.gateInfo = null;
        }
      },
      isChatContext: function () {
        return this.activeChatId != null;
      },
      // Раунд 10.4 (A-8, Risk A-2): запись TABS «Лор чатов» для рендера
      // config-части вкладки (groupedForTab по sources limits_lore/flags_lore).
      chatLoreTab: function () {
        var t = this.tabs.find(function (x) { return x.id === 'chat_lore'; });
        return t || null;
      },
      // Раунд 10.4 (F-1): запись TABS «Участники и отношения» для рендера
      // config-части (groupedForTab по sources limits_relations/flags_relations).
      relationsTab: function () {
        var t = this.tabs.find(function (x) { return x.id === 'relations'; });
        return t || null;
      },
      // F-14 (§6.2): активный скоуп — СВОИ ЛС (запись «Личные сообщения»
      // в селекторе; is_dm приходит с сервера в /api/access/chats).
      isDmCtx: function () {
        var self = this;
        if (this.activeChatId == null) return false;
        return this.accessChats.some(function (c) {
          return c.chat_id === self.activeChatId && c.is_dm;
        });
      },

      // ═══ Роль-пикер (F-7 T-855): per-param права (global admin) ═══
      // Ре-дизайн 10.2, BUG-6 (spec §3.2): флаги {viewRoles, editRoles}
      // чекбоксы user/moderator/local_admin; global admin — неявно ВСЕГДА.
      roleArr: function (roles) {
        var names = ['user', 'moderator', 'local_admin'];
        return names.filter(function (r) { return !!roles[r]; });
      },
      roleCheckboxAny: function (roles) {
        return !!(roles && (roles.user || roles.moderator || roles.local_admin));
      },
      openPermPicker: function (item) {
        this.permPickerItem = item;
        var picker = {
          viewRoles: { user: false, moderator: false, local_admin: false },
          editRoles: { user: false, moderator: false, local_admin: false },
        };
        arr(item.view_roles).forEach(function (r) {
          if (picker.viewRoles[r] !== undefined) picker.viewRoles[r] = true;
        });
        arr(item.edit_roles).forEach(function (r) {
          if (picker.editRoles[r] !== undefined) picker.editRoles[r] = true;
        });
        this.permPicker = picker;
        this.permPickerOpen = true;
      },
      closePermPicker: function () {
        this.permPickerOpen = false;
        this.permPickerItem = null;
      },
      savePermPicker: async function () {
        var item = this.permPickerItem;
        if (!item) return;
        this.permPickerSaving = true;
        try {
          var viewRoles = this.roleArr(this.permPicker.viewRoles);
          var editRoles = this.roleArr(this.permPicker.editRoles);
          await this.api('/api/access/param_permissions/' + encodeURIComponent(item.key), {
            method: 'PUT',
            body: JSON.stringify({ view_roles: viewRoles, edit_roles: editRoles }),
          });
          // ответ — нормализованная форма; сервер делает view_roles |= edit_roles
          item.view_roles = viewRoles;
          item.edit_roles = editRoles;
          this.toast('Права ключа сохранены: ' + item.title, 'ok');
          this.closePermPicker();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.permPickerSaving = false;
        }
      },
      resetPermPicker: async function () {
        var item = this.permPickerItem;
        if (!item) return;
        if (!window.confirm('Сбросить права «' + item.title
            + '» на дефолтные?')) return;
        this.permPickerSaving = true;
        try {
          await this.api('/api/access/param_permissions/' + encodeURIComponent(item.key),
            { method: 'DELETE' });
          this.toast('Права сброшены на дефолт: ' + item.title, 'ok');
          this.permPickerOpen = false;
          // матрица изменилась → перечитываем конфиг (свежие view/edit-роли);
          // _preserveScroll — чтобы сброс прав не прыгал в начало страницы.
          await this._preserveScroll(this.loadConfig);
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.permPickerSaving = false;
        }
      },
      itemHiddenDev: function (item) {
        // BUG-6/§3.2.1: «скрыт» = local_admin снят из «Чтения»
        return arr(item.view_roles).indexOf('local_admin') < 0;
      },

      // ═══ BYOK-UI (F-7 T-856): свой ключ чата ═══
      loadKeyStatus: async function () {
        if (this.activeChatId == null) {
          this.keyStatusOwn = null;
          return;
        }
        var epoch = this.scopeEpoch;   // R1: снимок scope
        try {
          var data = await this.api('/api/config/keys/status');
          if (!this._scopeGuard(epoch)) return;   // R1: устаревший ответ
          this.keyStatusOwn = data;
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          this.keyStatusOwn = null;
        }
      },
      saveOwnKey: async function () {
        var value = (this.ownKeyDraft || '').trim();
        if (!value) {
          this.toast('Введите новый ключ чата', 'warn');
          return;
        }
        this.ownKeySaving = true;
        try {
          await this.api('/api/config/keys/own', {
            method: 'PUT',
            body: JSON.stringify({ key_name: 'keys.llm_api_key', value: value }),
          });
          this.ownKeyDraft = '';
          this.toast('Ключ чата сохранён', 'ok');
          await this.loadKeyStatus();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.ownKeySaving = false;
        }
      },
      deleteOwnKey: async function () {
        if (!window.confirm('Удалить ключ чата? Чат вернётся к глобальному ключу (если разрешён).')) return;
        this.ownKeySaving = true;
        try {
          await this.api('/api/config/keys/own/keys.llm_api_key', { method: 'DELETE' });
          this.toast('Ключ чата удалён', 'ok');
          await this.loadKeyStatus();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.ownKeySaving = false;
        }
      },

      // F11 (10.24, ADR-1024-12 D4): БЕЗОПАСНЫЙ путь сохранения
      // провайдерского секрета — в общий POST /api/config секреты не попадают.
      // Контракт spec §3.2: `saveProviderSecret(key, value, {scope})`.
      //   * scope 'global' (default) + image-ключ + kill-switch ON →
      //     PUT safe-эндпоинт, scope:'global', БЕЗ X-Chat-Id (`global:true`),
      //     ответ — маска (R17);
      //   * scope 'chat' + `keys.llm_api_key` → per-chat BYOK (PUT без global);
      //   * прочие секреты ИЛИ kill-switch OFF → прежний глобальный POST
      //     (`per_chat=false`, без X-Chat-Id) — OFF-поведение фичи.
      saveProviderSecret: async function (key, value, opts) {
        opts = opts || {};
        var scope = opts.scope || 'global';
        if (key === 'keys.llm_api_key' && scope === 'chat') {
          return this.api('/api/config/keys/own', {
            method: 'PUT',
            body: JSON.stringify({ key_name: key, value: value,
                                   scope: 'chat' }),
          });
        }
        var flagOn = (typeof this.uiFlag === 'function')
          ? this.uiFlag('BYOK_IMAGE_KEY_ENABLED') : true;
        if (key === 'keys.image_api_key' && scope === 'global' && flagOn) {
          return this.api('/api/config/keys/own', {
            method: 'PUT',
            body: JSON.stringify({ key_name: key, value: value,
                                   scope: 'global' }),
            global: true,
          });
        }
        return this.api('/api/config', {
          method: 'POST',
          body: JSON.stringify({ items: [{ key: key, value: value }],
                                 updated_at: null }),
          global: true,
        });
      },
      // F11 (10.24, ADR-1024-12 D4): сохранение ГЛОБАЛЬНОГО image-ключа из
      // карточки-модалки (saveKeyItem): safe-эндпоинт + тот же успешный
      // жизненный цикл (очистка черновика, тост, reload, ре-сев масок).
      saveImageKeyItem: async function (item, value) {
        await this.saveProviderSecret(item.key, value);
        this.keyDrafts[item.key] = '';
        this.toast('Ключ обновлён: ' + item.title, 'ok');
        await this._preserveScroll(this.loadConfig);
        if (typeof this._seedSecretMasks === 'function') this._seedSecretMasks();
        return true;
      },

      // ═══ «Доступы» (F-7 T-857): локальные админы активного чата ═══
      loadLocalAdmins: async function () {
        if (this.activeChatId == null) {
          this.chatLocalAdmins = [];
          return;
        }
        this.chatLocalAdminsBusy = true;
        var epoch = this.scopeEpoch;   // D2: снимок scope
        try {
          var data = await this.api('/api/chat_lore/admins?chat_id=' + this.activeChatId);
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          var self = this;
          this.chatLocalAdmins = (Array.isArray(data) ? data : []).map(function (r) {
            return { telegram_id: r, role_name: 'local_admin' };
          });
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          this.chatLocalAdmins = [];
        } finally {
          if (this._scopeGuard(epoch)) this.chatLocalAdminsBusy = false;   // R3
        }
      },
      addLocalAdmin: async function () {
        var tid = parseInt(this.newLocalAdminId, 10);
        if (!tid) { this.toast('Введите Telegram ID', 'warn'); return; }
        try {
          await this.api('/api/access/chats/' + this.activeChatId + '/admins', {
            method: 'POST',
            body: JSON.stringify({ telegram_id: tid, role_name: this.newLocalAdminRole }),
          });
          this.toast('Локальный админ добавлен: ' + tid, 'ok');
          this.newLocalAdminId = '';
          await this.loadLocalAdmins();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },
      removeLocalAdmin: async function (tid) {
        if (!window.confirm('Удалить локального админа ' + tid + ' из чата?')) return;
        try {
          await this.api('/api/access/chats/' + this.activeChatId + '/admins/' + tid, { method: 'DELETE' });
          this.toast('Удалён: ' + tid, 'ok');
          await this.loadLocalAdmins();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },

      // ═══ Раунд 10 (F-10 E1/F-9 D1): «Модули» ═══
      // Gates чата (тяжёлые 3 + permsoc master) + Opt-In + бюджет фона.
      loadGateInfo: async function () {
        if (this.activeChatId == null) {
          this.gateInfo = null;
          return;
        }
        var epoch = this.scopeEpoch;   // D2: снимок scope
        this.gatesBusy = true;
        try {
          var gi = await this.api('/api/chat/' + this.activeChatId + '/gates');
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.gateInfo = gi;
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          this.gateInfo = null;
        } finally {
          if (this._scopeGuard(epoch)) this.gatesBusy = false;   // R3
        }
      },
      loadBudgetInfo: async function () {
        this.budgetBusy = true;
        try {
          this.budgetInfo = await this.api('/api/workers/budget');
        } catch (e) {
          this.budgetInfo = null;
        } finally {
          this.budgetBusy = false;
        }
      },
      // F7 (раунд 10.23, ADR-1023-7 §2.8): аналитика токенов — дерево
      // последнего вызова (Flow node) + графики день/неделя/месяц. Fail-open:
      // ошибка/недоступность → null (шаблон «—»). Меню не трогает.
      loadTokenAnalytics: async function () {
        this.tokenAnalyticsBusy = true;
        try {
          var period = this.tokenAnalyticsPeriod || 'day';
          // S8 (ADR-1026-10 D3): граф прогона Саммари — отдельный аддитивный
          // источник; его отказ не должен ронять аналитику F6 (fail-open).
          var res = await Promise.all([
            this.api('/api/analytics/usage/latest'),
            this.api('/api/analytics/usage/summary?period=' + period),
            this.api('/api/analytics/execution/latest')
              .catch(function () { return null; }),
          ]);
          this.tokenAnalyticsLatest = res[0];
          this.tokenAnalyticsSummary = res[1];
          this.tokenAnalyticsExecution = res[2];
        } catch (e) {
          this.tokenAnalyticsLatest = null;
          this.tokenAnalyticsSummary = null;
          this.tokenAnalyticsExecution = null;
        } finally {
          this.tokenAnalyticsBusy = false;
        }
      },
      setTokenAnalyticsPeriod: function (period) {
        this.tokenAnalyticsPeriod = period;
        this.loadTokenAnalytics();
      },
      // F3 (10.24, ADR-1024-13): UI-флаг из `GET /api/me.ui_flags`.
      // До загрузки /api/me — безопасный дефолт ON (новое поведение =
      // штатный дефолт). CSP-safe: значения приходят в JSON, без inline-script.
      uiFlag: function (name) {
        var flags = (this.me && this.me.ui_flags) || null;
        if (!flags || !Object.prototype.hasOwnProperty.call(flags, name)) {
          return true;
        }
        return !!flags[name];
      },
      // F5 (10.24, ADR-1024-9 review iter1): kill-switch вкладки. При
      // IMAGE_MODULE_CARD_ENABLED=OFF карточка скрыта (visibleModules), а
      // диплинк `#/mod_images` редиректится на витрину `#/modules`
      // (applyRoute). Главный тумблер при OFF в UI недостижим — возврат
      // ручки: env-флаг ON либо `git revert`.
      _flagTabHidden: function (tabId) {
        return tabId === 'mod_images'
          && !this.uiFlag('IMAGE_MODULE_CARD_ENABLED');
      },
      // Шаги дерева последнего вызова: [{label, tokens, cost_usd, …}].
      // F7 (review iter1): человекочитаемые метки шагов дерева
      // («Слой 1/2», «Инструмент: name», «Один вызов», «Изображение»).
      tokenFlowNodes: function () {
        var latest = this.tokenAnalyticsLatest;
        var steps = (latest && latest.steps) || [];
        var labels = {
          stage1: 'Слой 1', stage2: 'Слой 2', tool: 'Инструмент',
          single: 'Один вызов', image: 'Изображение',
        };
        return steps.map(function (s) {
          var base = labels[s.step] || (s.step || '?');
          var label = base + (s.tool_name ? (': ' + s.tool_name) : '');
          return {
            label: label,
            module: s.module || '',
            tokens: (s.input_tokens || 0) + (s.output_tokens || 0),
            cost_usd: s.cost_usd || 0,
            estimated: !!s.tokens_estimated,
            price_known: s.price_known !== false,
          };
        });
      },
      // Человекочитаемая подпись корня дерева: время последнего вызова.
      _tokenFlowTimestamp: function (ts) {
        if (!ts) return 'последний вызов';
        var s = String(ts).replace('T', ' ').slice(0, 16);
        return 'последний вызов · ' + s;
      },
      // Точное число токенов (без «k»-сокращения) — формат Flow node.
      fmtExactTokens: function (n) {
        var v = Number(n) || 0;
        return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
      },
      // F6 (ADR-1025-19 D5/§28): `$0` — ТОЛЬКО для подтверждённого нуля.
      // При `known === false` (price_known=false) или отсутствии числа —
      // «Нет данных» (устраняет прежний `$0`-по-умолчанию).
      fmtCost: function (v, known) {
        if (known === false) return 'Нет данных';
        if (v === null || v === undefined) return 'Нет данных';
        var n = Number(v);
        if (isNaN(n)) return 'Нет данных';
        if (n === 0) return '$0';
        if (n < 0.000001) return '$' + n.toExponential(2);
        return '$' + n.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
      },
      // Честная подпись стоимости узла/итога (D5): неизвестная цена -> «Нет
      // данных», подтверждённый ноль -> `$0`.
      execCostLabel: function (node) {
        if (!node) return 'Нет данных';
        return this.fmtCost(node.cost, node.priceKnown);
      },
      fmtTokensCell: function (v) {
        return (v === null || v === undefined) ? '—' : this.fmtExactTokens(v);
      },
      // Статус в данных не передаётся (ADR-1025-19 D1) — показываем честно.
      execStatusLabel: function (status) {
        return (status === 'unknown' || !status) ? 'нет данных' : String(status);
      },
      // F6 (D1): adapter из `window.ExecutionGraph` (загружается до app.js).
      execGraphApi: function () {
        if (typeof window !== 'undefined' && window.ExecutionGraph) {
          return window.ExecutionGraph;
        }
        return null;
      },
      _execFilters: function () {
        return { module: this.execFilterModule || '',
                 model: this.execFilterModel || '',
                 stage: this.execFilterStage || '',
                 status: this.execFilterStatus || '',
                 query: this.execFilterQuery || '' };
      },
      execFilterActive: function () {
        return !!(this.execFilterModule || this.execFilterModel
                  || this.execFilterStage || this.execFilterStatus
                  || this.execFilterQuery);
      },
      // Переключение режима §26: 'latest' (трассировка) | day|week|month.
      // Смена режима СБРАСЫВАЕТ фильтры §27 (M-F6S-1): агрегатные узлы не
      // несут model/stage/status, иначе фильтр трассировки «протёк» бы в
      // период и дал ложное «За период данных нет».
      setExecMode: function (mode) {
        if (mode !== this.execMode) this.resetExecFilters();
        this.execMode = mode;
        this.execSelected = null;
        this.execDetailOpen = false;
        if (mode !== 'latest') this.tokenAnalyticsPeriod = mode;
        this.loadTokenAnalytics();
      },
      setExecFilter: function (name, value) {
        if (name === 'module') this.execFilterModule = value;
        else if (name === 'model') this.execFilterModel = value;
        else if (name === 'stage') this.execFilterStage = value;
        else if (name === 'status') this.execFilterStatus = value;
        else if (name === 'query') this.execFilterQuery = value;
      },
      resetExecFilters: function () {
        this.execFilterModule = '';
        this.execFilterModel = '';
        this.execFilterStage = '';
        this.execFilterStatus = '';
        this.execFilterQuery = '';
      },
      // Выбор узла: desktop side-panel / mobile bottom-sheet (§27). Показываем
      // только реальные поля (отсутствующие -> «Нет данных»).
      selectExecNode: function (node) {
        this.execSelected = node;
        this.execDetailOpen = true;
      },
      closeExecDetail: function () {
        this.execDetailOpen = false;
        this.execSelected = null;
      },
      // F6 (D5/§21): компактное превью последнего вызова для Статуса. Отдельный
      // лёгкий путь (только `/usage/latest`), без фильтров §27 и без второго
      // рендера — тот же adapter.
      loadExecPreview: async function () {
        if (this.tokenAnalyticsLatest) return;   // уже загружено на «Аналитике»
        this.execPreviewBusy = true;
        try {
          this.tokenAnalyticsLatest = await this.api('/api/analytics/usage/latest');
        } catch (e) {
          this.tokenAnalyticsLatest = null;
        } finally {
          this.execPreviewBusy = false;
        }
      },
      loadModules: async function () {
        if (this.modulesBusy) return;
        this.modulesBusy = true;
        try {
          // 10.9 (п.6): «Бюджет фона» переехал в «Сводку» — «Модули»
          // больше бюджет не грузят (единый клиентский путь: loadOversight).
          await this.loadGateInfo();
        } finally {
          this.modulesBusy = false;
        }
      },
      // toggle тяжёлого гейта (PUT /api/chat/{id}/gates; 409-протокол)
      toggleGate: async function (feature, enabled) {
        if (this.activeChatId == null) return;
        this.gatesBusy = true;
        try {
          await this.api('/api/chat/' + this.activeChatId + '/gates', {
            method: 'PUT',
            body: JSON.stringify({ feature: feature, enabled: !!enabled }),
          });
          this.toast((enabled ? 'Включено: ' : 'Выключено: ') + feature, 'ok');
          await this.loadGateInfo();
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.toast('Конфликт версии (409) — обновлено', 'warn');
            this.loadGateInfo();
          } else {
            this.toast('Ошибка: ' + e.message, 'err');
          }
        } finally {
          this.gatesBusy = false;
        }
      },
      // master PERMsoc (только global admin; локальный — read-only)
      togglePermsoc: async function (enabled) {
        this.permsocBusy = true;
        try {
          await this.toggleGate('permsoc', enabled);
        } finally {
          this.permsocBusy = false;
        }
      },
      // BUG-3 (spec §10 A/C): мастер-флаг PERMsoc (перчат-гейт) для
      // карточек «Модули» + вкладки «PERMsoc».
      permsocMasterOn: function () {
        var g = this.gateInfo && this.gateInfo.gates;
        return !!(g && g.permsoc);
      },
      // BUG-3 / 10.9 (§1.3): сводка 5 модулей — derived (master) / под-флаг
      // (flags.slavik_enabled|olya|mimic) / OFF (master). Славик теперь
      // имеет собственный под-флаг (ADR-109-4).
      permsocModuleBadge: function (module) {
        if (!this.isChatContext() || !(this.gateInfo && this.gateInfo.gates)) {
          return null;
        }
        if (!this.gateInfo.gates.permsoc) return 'OFF (master)';
        var subFlags = {
          slavik: 'flags.slavik_enabled',
          kostik: 'flags.kostik_enabled',
          olya: 'flags.olya_enabled',
          mimic: 'flags.mimic_enabled',
        };
        var itemKey = subFlags[module];
        if (!itemKey) return 'derived (master)';   // alan
        var it = this.configItems.find(function (i) { return i.key === itemKey; });
        return it && it.value ? 'под-флаг ON' : 'под-флаг OFF';
      },
      // бюджет: прогресс-бары (usage/limit в долях; guard нулей).
      // F3 (10.19, I-1): `limit <= 0` (−1 = безлимит / 0 = запрет) → 0%
      // (раньше отрицательный limit давал отрицательную ширину бара).
      budgetRatio: function (pair) {
        if (!pair || !pair.limit || pair.limit <= 0) return 0;
        if (pair.unlimited) return 0;
        return Math.min(1, (pair.used || 0) / pair.limit);
      },
      // F3 (10.19, ADR-1019-8 D6): человекочитаемый текст метрики —
      // «Безлимит (∞)» / «Запрещено» / «used / limit».
      limitsPairText: function (pair) {
        if (!pair) return '—';
        if (pair.unlimited) return 'Безлимит (∞)';
        if (pair.forbidden) return 'Запрещено';
        return (pair.used || 0) + ' / ' + (pair.limit == null ? '?' : pair.limit);
      },
      // F3: статус хранения импорта («Импорт: Вечно» / «Импорт: N дней»).
      storageLabel: function (storage) {
        if (!storage) return '—';
        return 'Импорт: ' + (storage.import_forever
          ? 'Вечно' : (storage.label || (storage.import_retention_days + ' дней')));
      },
      // F3: ключи per-chat контуров, которые пишет тумблер безлимита.
      budgetsUnlimitedKeys: function () {
        return [
          'limits.chat_global_key_budget_requests',
          'limits.chat_global_key_budget_tokens',
          'limits.worker_daily_llm_calls_per_chat',
          'limits.worker_daily_llm_tokens_per_chat',
          'limits.chat_global_context_max_tokens',
          'limits.chat_thread_max_tokens',
          'limits.chat_context_budget_tokens',
        ];
      },
      _budgetItem: function (key) {
        return this.configItems.find(function (i) { return i.key === key; });
      },
      // Включён ли безлимит: все ключи — per-chat override == −1.
      budgetsUnlimitedActive: function () {
        if (!this.isChatContext()) return false;
        var self = this;
        return this.budgetsUnlimitedKeys().every(function (key) {
          var it = self._budgetItem(key);
          return it && it.chat_source === 'chat' && Number(it.value) === -1;
        });
      },
      // Тумблер «Безлимит по чату» (F3/D4): ON → все ключи = −1 (одним
      // POST /api/config, per-chat); OFF → ЯВНЫЕ значения глобального слоя
      // (POST /api/config, а не DELETE: DELETE терял meta.chat_settings_seed_version
      // и сид переприменял −1 на рестарте — ревью Батча C, D-3). Новых
      // REGISTRY-ключей не вводит.
      toggleBudgetsUnlimited: async function (on) {
        if (!this.isChatContext()) {
          this.toast('Сначала выберите чат', 'warn');
          return;
        }
        var self = this;
        var keys = this.budgetsUnlimitedKeys();
        this.budgetsUnlimitedBusy = true;
        try {
          if (on) {
            var items = keys.map(function (key) { return { key: key, value: -1 }; });
            await this.api('/api/config', {
              method: 'POST',
              body: JSON.stringify({
                items: items, updated_at: this.configChatUpdatedAt,
              }),
            });
            this.toast('Включён безлимит по этому чату', 'ok');
          } else {
            // Явные дефолты: null (env не задан, напр. контекст) → 0 =
            // «не задано» (резолв уходит на эффективный дефолт).
            var offItems = keys.map(function (key) {
              var it = self._budgetItem(key);
              var base = (it && it.global_value !== null
                          && it.global_value !== undefined) ? it.global_value : 0;
              return { key: key, value: base };
            });
            await this.api('/api/config', {
              method: 'POST',
              body: JSON.stringify({
                items: offItems, updated_at: this.configChatUpdatedAt,
              }),
            });
            this.toast('Безлимит снят — лимиты по глобальным значениям', 'ok');
          }
          await this._preserveScroll(this.loadConfig);
          await this.loadKeyStatus();
        } catch (e) {
          if (e.status === 409) {
            this.toast('Конфликт версии (409) — обновите конфигурацию', 'warn');
            this._preserveScroll(this.loadConfig);
          } else {
            this.toast('Ошибка: ' + e.message, 'err');
          }
        } finally {
          this.budgetsUnlimitedBusy = false;
        }
      },

      // ═══ Раунд 10 (F-12 C1/C2): Oversight (global admin) ═══
      loadOversight: async function () {
        this.oversightBusy = true;
        try {
          this.oversightData = await this.api('/api/oversight/summary');
          // F4 (UPD п.4): панель «Личность» — отдельный persona-API
          // (один дом данных; не дублируем в oversight/summary).
          this.loadPersonaHealth();
          // 10.9 (п.6, ADR-109-5): «Бюджет фона» живёт в «Сводке» — единый
          // клиентский путь (прогрессбары), без дубля global_budget.
          this.loadBudgetInfo();
          // F7 (раунд 10.23): аналитика токенов — Flow node + графики.
          this.loadTokenAnalytics();
        } catch (e) {
          this.oversightData = null;
          if (e.status !== 401 && e.status !== 403) {
            this.toast('Не удалось загрузить сводку: ' + e.message, 'err');
          }
        } finally {
          this.oversightBusy = false;
        }
      },
      // F4 (UPD п.4): метрики здоровья Личности для панели «Личность» в
      // «Сводке». Fail-open: ошибка/недоступность → null (шаблон «—»).
      loadPersonaHealth: async function () {
        try {
          this.personaHealth = await this.api('/api/persona/health');
        } catch (e) {
          this.personaHealth = null;
        }
      },
      // F7 (memory-retention-health, D-6): метрики здоровья памяти для
      // «Мониторинга Интеллекта» (просрочено/не подтверждено/сырьё/диск).
      // Fail-open: ошибка/недоступность → null (шаблон «—»).
      loadMemoryHealth: async function () {
        this.memoryHealthBusy = true;
        try {
          this.memoryHealth = await this.api('/api/memory/health');
        } catch (e) {
          this.memoryHealth = null;
        } finally {
          this.memoryHealthBusy = false;
        }
      },
      // Предупреждение о низком свободном месте (порог 2 ГБ).
      memoryStorageWarn: function () {
        var s = this.memoryHealth && this.memoryHealth.storage;
        if (!s || !s.disk_free_bytes) return false;
        return s.disk_free_bytes < 2147483648;
      },
      // Hotfix-R10 («Модули» без выбранного чата): Opt-In-сводка из
      // Oversight-данных удалена в 10.9 (карточка дублирующих гейтов убрана).
      oversightRows: function () {
        var self = this;
        var q = (this.oversightSearch || '').trim().toLowerCase();
        var rows = (this.oversightData && this.oversightData.chats) || [];
        if (q) {
          rows = rows.filter(function (c) {
            return String(c.chat_id).indexOf(q) >= 0
              || (c.title || '').toLowerCase().indexOf(q) >= 0
              || (c.key_status || '').toLowerCase().indexOf(q) >= 0;
          });
        }
        var sort = this.oversightSort;
        rows = rows.slice().sort(function (a, b) {
          var va = a[sort], vb = b[sort];
          if (typeof va === 'boolean') va = va ? 1 : 0;
          if (typeof vb === 'boolean') vb = vb ? 1 : 0;
          if (va == null) va = 0;
          if (vb == null) vb = 0;
          if (va === vb) return (a.chat_id || 0) - (b.chat_id || 0);
          return va > vb ? -1 : 1;    // активные/opt-in/Pеки выше — интуитивно
        });
        return rows;
      },
      keyStatusRu: function (status) {
        return { own: 'свой ключ', global: 'глобальный',
                 forbidden: 'запрещён', none: 'нет' }[status] || status;
      },
      openChatDetails: async function (chatId) {
        this.oversightDetailBusy = true;
        try {
          this.oversightDetail = await this.api('/api/oversight/chat/' + chatId);
        } catch (e) {
          this.oversightDetail = null;
          this.toast('Ошибка деталей: ' + e.message, 'err');
        } finally {
          this.oversightDetailBusy = false;
        }
      },
      closeChatDetails: function () {
        this.oversightDetail = null;
      },
      toggleKillswitch: async function (feature, target) {
        var chat = this.oversightDetail;
        if (!chat) return;
        if (!window.confirm('Фича «' + feature + '» ' + (target ? 'включится'
                            : 'выключится') + ' для чата — продолжить?')) return;
        this.oversightOpBusy = true;
        try {
          var res = await this.api(
            '/api/oversight/chat/' + chat.chat_id + '/killswitch', {
              method: 'POST',
              body: JSON.stringify({ feature: feature, enabled: !!target,
                                     expected_updated_at: null }),
            });
          this.toast((res.enabled ? 'Включено' : 'Выключено') + ': '
                     + feature, 'ok');
          await this.loadOversight();
          await this.openChatDetails(chat.chat_id);
        } catch (e) {
          if (e.status === 409) {
            this.toast('Конфликт версии (409) — обновите детали', 'warn');
          } else {
            this.toast('Ошибка: ' + e.message, 'err');
          }
        } finally {
          this.oversightOpBusy = false;
        }
      },
      toggleGlobalKey: async function (allow) {
        var chat = this.oversightDetail;
        if (!chat) return;
        if (!window.confirm(allow
            ? 'Разрешить глобальный ключ для чата?'
            : 'Если у чата нет своего ключа — бот перестанет использовать '
              + 'глобальные ключи (или отвечать). Продолжить?')) return;
        this.oversightOpBusy = true;
        try {
          await this.api('/api/oversight/chat/' + chat.chat_id + '/global_key', {
            method: 'POST',
            body: JSON.stringify({ allow: !!allow }),
          });
          this.toast(allow ? 'Глобальный ключ разрешён'
                     : 'Глобальный ключ запрещён', 'ok');
          await this.loadOversight();
          await this.openChatDetails(chat.chat_id);
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.oversightOpBusy = false;
        }
      },

      // ═══ Индикатор «переопределено чатом» (F-7 T-868) ═══
      itemOverriddenByChat: function (item) {
        return this.isChatContext() && item && item.chat_source === 'chat';
      },
      // F3 (§5): источник эффективного значения для карточки параметра.
      // В глобальной области не показываем (вся форма и так глобальная);
      // в области чата/ЛС — «глобальная настройка» (наследование) либо
      // «настройки чата» (локальное переопределение, PERMsoc).
      configSourceLabel: function (item) {
        if (!item || this.scopeKind === 'global') return '';
        return (item.chat_source === 'chat')
          ? 'Источник: настройки чата'
          : 'Источник: глобальная настройка';
      },
      configSourceTitle: function (item) {
        if (!item) return '';
        if (item.chat_source === 'chat') {
          return 'Локальное переопределение для этой области '
            + '(настройки чата/PERMsoc) — не заводское значение';
        }
        return 'Значение наследуется из глобальной конфигурации';
      },
      // F3 (§43): фактическое состояние. Сервер отдаёт эффективное `value`
      // (для per_chat-ключей override перекрывает глобальное — проверено по
      // web/api/routes.py get_config). Явно отмечаем расхождение «локально
      // включено при глобально выключенном» и не применяемые локально
      // глобальные параметры. Приоритет локального НЕ предполагается.
      configItemNotice: function (item) {
        if (!item || this.scopeKind === 'global') return '';
        // §43/ревью Medium: показываем ТОЛЬКО фактическое расхождение —
        // локальное включение при глобально выключенном (per_chat override
        // wins, см. web/api/routes.py::get_config). Не шумим на
        // per_chat=false (~101 параметр) — там источник уже говорит всё.
        if (item.chat_source === 'chat' && item.global_value === false
            && item.value === true) {
          return 'Локально включено, хотя глобально выключено';
        }
        return '';
      },
      resetChatOverride: async function (item) {
        // F-14 (§6.3) + F3 (ревью 2): сброс override — global admin (любой
        // чат), DM-владелец (свой ЛС) ИЛИ локальный админ чата. Паритет с
        // серверным гейтом `web/api/routes.py:871-876` (DELETE-override
        // разрешён is_global_admin/is_local_admin; DM — is_dm_owner).
        if (!(this.isGlobalAdmin || this.isDmCtx() || this.isLocalAdminCtx())) {
          this.toast('Нет права сбросить override', 'err');
          return;
        }
        if (!window.confirm('Сбросить «' + item.title + '» на глобальное значение для этого чата?')) return;
        this.saving.add(item.key);
        try {
          await this.api('/api/config/chat/' + encodeURIComponent(item.key), {
            method: 'DELETE',
          });
          this.toast('Сброшено на глобальное: ' + item.title, 'ok');
          await this._preserveScroll(this.loadConfig);
          await this.loadKeyStatus();
        } catch (e) {
          if (e.status === 409) {
            this.toast('Конфликт версии (409) — перезагрузите конфигурацию', 'warn');
            this._preserveScroll(this.loadConfig);
          } else {
            this.toast('Ошибка: ' + e.message, 'err');
          }
        } finally {
          this.saving.delete(item.key);
        }
      },

      // ═══ Hash-роутер (T-1099, §6.2/§6.4.4): applyRoute — применитель ═══
      // route — источник истины; activeTab — производная. RBAC-гейт перед
      // применением: запрещённый раздел → откат на '#/' через replaceState
      // (не создаёт лишней history), UI не ослабляет серверные проверки.
      applyRoute: function (rawHash) {
        var route = normalizeRoute(rawHash);
        if (!route) route = this.route || '#/';
        // MINOR-1: legacy-алиасы нормализуем в канонический hash (replaceState).
        var aliasTarget = ROUTE_ALIAS[route];
        if (aliasTarget) {
          try { history.replaceState(null, '', aliasTarget); } catch (e) { /* file:// */ }
          route = aliasTarget;
        }
        // F5 (D1): неизвестный slug → витрина «Модули» + toast (не белый
        // экран); неприменимая вкладка → дефолт «Обзор».
        var wsParsed = parseWorkspaceRoute(route);
        if (wsParsed) {
          var wsm = _wsModuleById(wsParsed.slug);
          if (!wsm) {
            this.toast('Модуль не найден', 'warn');
            route = '#/modules';
            try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
          } else if (wsParsed.tab
                     && !_workspaceTabApplicable(wsm, wsParsed.tab)) {
            route = '#/modules/' + wsParsed.slug;
            try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
          }
        }
        // D3/§48: вторая дверь `#/ai/prompts/<slug>[/<stage>]`. Неизвестный
        // модуль → чистая библиотека (без белого экрана); существующий slug
        // открывает тот же config-item, что и страница модуля.
        var plParsed = parsePromptLibraryRoute(route);
        if (plParsed) {
          var plm = _wsModuleById(plParsed.slug);
          if (!plm) {
            this.toast('Модуль не найден', 'warn');
            route = '#/ai/prompts';
            try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
          } else if (!MODULE_PROMPT_GROUPS[plm.id]) {
            // L-F5S-3: у модуля нет промптов — «пустая» библиотечная дверь
            // ведёт в чистую библиотеку (без шапки-перехода в никуда).
            route = '#/ai/prompts';
            try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
          }
        }
        if (route === this.route && _routeApplied) {
          this.syncBackButton();
          return;
        }
        var tabId = routeToTab(route);
        var hubs = this.iaV2 ? HUBS_V2 : HUBS;
        var isHub = Object.prototype.hasOwnProperty.call(hubs, route);
        if (this.me && isHub) {
          // D1: hub-роут гейтим по видимым карточкам, НЕ по representative tab.
          if (!hubVisible(route, this.canViewTab.bind(this), hubs)) {
            this.toast('Нет доступа к разделу', 'warn');
            route = '#/';
            tabId = routeToTab(route);
            try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
          }
        } else if (this.me && tabId && !this.canViewTab(tabId)) {
          // RBAC имеет ПРИОРИТЕТ над kill-switch: нет права на вкладку →
          // штатный отказ на `#/` независимо от флага.
          this.toast('Нет доступа к разделу', 'warn');
          route = '#/';
          tabId = routeToTab(route);
          try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
        } else if (this.me && tabId && this._flagTabHidden
                   && this._flagTabHidden(tabId)) {
          // F5 (10.24, ADR-1024-9 review iter2): kill-switch скрывает не
          // только карточку, но и вкладку — диплинк `#/modules/images` при
          // OFF редиректится на витрину «Модули»; витрина тоже под RBAC
          // (нет права на `modules` → `#/`).
          route = this.canViewTab('modules') ? '#/modules' : '#/';
          tabId = routeToTab(route);
          try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
        }
        this.route = route;
        _routeApplied = true;
        try { sessionStorage.setItem('adminbot.route', route); } catch (e) { /* quota */ }
        // 10.8/ADR-001: окно подраздела «Доступов» — производная от hash;
        // любой не-`#/access/*` маршрут обнуляет состояние (нет stale-окна).
        this.accessOpen = route.indexOf('#/access/') === 0
          ? route.substring('#/access/'.length) : null;
        var found = this.tabs.find(function (t) { return t.id === tabId; });
        if (tabId && tabId !== this.activeTab) this.setTab(tabId);
        // F5 (§46): страница модуля гарантирует конфиг и данные модуля.
        var wsm2 = this.workspace ? this.workspace.module : null;
        if (wsm2) {
          if (!this.configItems.length && typeof this.loadConfig === 'function') {
            this.loadConfig();
          }
          if (typeof this._ensureModuleData === 'function') {
            this._ensureModuleData(wsm2);
          }
        }
        this.syncBackButton();
      },
      // D2/§15.1.7 (R10.4-2): отбрасывание устаревших in-flight ответов при
      // смене scope — снимок epoch перед await, сверка после.
      _scopeGuard: function (epoch) {
        return epoch === this.scopeEpoch;
      },
      navigateTo: function (route) {
        var r = normalizeRoute(route);
        if (!r) return;
        if (r === this.route) { this.applyRoute(r); return; }
        // ровно ОДНА history-запись → hashchange → applyRoute
        window.location.hash = r;
      },
      // Навигация из меню: hash авторитетен (не setTab напрямую).
      openTab: function (id) {
        var r = tabToRoute(id);
        if (r) this.navigateTo(r);
        else this.setTab(id);
      },
      // T-1100: navbar → маршрут (hash).
      navTo: function (route) {
        this.navigateTo(route);
      },
      // F1 (T-2400): инъекция id-анкеров в h1..h3 санитайзенного HTML +
      // сбор оглавления. Без DOMParser (тесты/старый браузер) — no-op.
      _anchorHtml: function (html, prefix) {
        var anchors = [];
        if (!html || typeof DOMParser === 'undefined') {
          return { html: html, anchors: anchors };
        }
        try {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          var hs = doc.body.querySelectorAll('h1, h2, h3');
          for (var i = 0; i < hs.length; i++) {
            var text = (hs[i].textContent || '').trim();
            if (!text) continue;
            var id = prefix + '-h' + (i + 1);
            hs[i].setAttribute('id', id);
            anchors.push({ id: id, text: text, level: Number(hs[i].tagName.slice(1)),
              source: prefix });
          }
          return { html: doc.body.innerHTML, anchors: anchors };
        } catch (e) {
          return { html: html, anchors: anchors };
        }
      },
      scrollToAnchor: function (id) {
        try {
          var el = document.getElementById(id);
          if (el && typeof el.scrollIntoView === 'function') {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        } catch (e) { /* вне DOM */ }
      },
      // F1 (UPD §8.4): человекочитаемая подпись раздела для пути назад.
      // M-1 (Scanner): подстраницы/спец-экраны вне TABS (#/ai/persona,
      // #/access/roles, #/memory/*) — подпись из карточки хаба, не сырой hash.
      _routeLabel: function (route) {
        // F11 (10.25, ADR-1025-23 D4): заголовок экрана полного графа.
        if (route === '#/status/graph') return 'Граф связей';
        var items = this.iaV2 ? NAV_ITEMS_V2 : NAV_ITEMS;
        for (var i = 0; i < items.length; i++) {
          if (items[i].route === route) return items[i].label;
        }
        var map = this.iaV2 ? HUBS_V2 : HUBS;
        for (var rk in map) {
          if (!Object.prototype.hasOwnProperty.call(map, rk)) continue;
          var cards = map[rk].cards || [];
          for (var c = 0; c < cards.length; c++) {
            if (cards[c].route === route) return cards[c].title;
          }
        }
        var tabId = routeToTab(route);
        var t = TABS.find(function (x) { return x.id === tabId; });
        return (t && t.label) || String(route || '');
      },
      // F1 (§6/§7): shell-режим по ширине; постоянный sidebar строго ≥1200.
      _syncShellMode: function () {
        try {
          var w = window.innerWidth || 0;
          this.shellMode = w >= 1200 ? 'desktop' : (w >= 768 ? 'compact'
            : 'mobile');
        } catch (e) { /* вне браузера */ }
      },
      toggleDrawer: function () {
        this.drawerOpen = !this.drawerOpen;
        if (this.drawerOpen) this.moreOpen = false;
      },
      closeDrawer: function () {
        this.drawerOpen = false;
      },
      toggleMore: function () {
        this.moreOpen = !this.moreOpen;
        if (this.moreOpen) this.drawerOpen = false;
      },
      closeMore: function () {
        this.moreOpen = false;
      },
      // F1 (UPD §8.4/T-2399): путь назад на родителя (in-app + TMA BackButton).
      goParent: function () {
        var p = routeParent(this.route);
        this.navigateTo(p || '#/');
      },
      // Навигация из shell (sidebar/bottom-nav/шторка): закрыть оверлеи.
      shellNavTo: function (route) {
        this.closeDrawer();
        this.closeMore();
        this.navigateTo(route);
      },
      // A9/T-1206 + 10.8/ADR-001: «Доступы» — route-driven окна подразделов
      // (hash `#/access/<id>`; состояние окна — производная applyRoute).
      openAccessWindow: function (id) {
        if (!id) return;
        if (!this.canViewTab('access')) {
          this.toast('Нет доступа к разделу', 'warn');
          return;
        }
        this.navigateTo('#/access/' + id);
      },
      closeAccessWindow: function () {
        this.navigateTo('#/access');
      },
      // 10.8 (R10.8-1): Esc закрывает верхнюю модалку — окно модуля (если
      // открыто), иначе route-driven окно «Доступов». Вынесено из глобального
      // keydown ради юнит-тестируемости.
      escClose: function () {
        // F11 (L-F11S-3, §16/D4): полноэкранный граф — верхний слой;
        // Esc закрывает его первым (fallback-шторка или hash-маршрут).
        if (this.graphFullVisible) { this.closeGraphFull(); return; }
        // F6 (§27/L-F6S-4): side-panel/bottom-sheet деталей узла закрывается Esc.
        if (this.execDetailOpen) { this.closeExecDetail(); return; }
        // 10.20 (T-1896): модалка досье — верхняя (её и закрываем первой).
        if (this.dossierOpen) { this.closeDossier(); return; }
        if (this.openModuleId != null) { this.closeModule(); return; }
        if (this.accessOpen != null) { this.closeAccessWindow(); }
      },
      isAccessOpen: function (id) {
        return this.accessOpen === id;
      },
      // ═══ A2/T-1166/T-1167: модули — toggle + окно параметров ═══
      openModuleWindow: function (m) {
        if (!m) return;
        // Раунд 10.20 (БЛОК 3.1(б)/T-1895): root cause — карточка модуля
        // видна по широкому предикату вкладки «Модули» (reactions/flags/
        // chat_lore/local-admin), а отдельный гейт canViewTab(m.tab) требовал
        // секции конкретной config-вкладки (flags/limits/keys). У ролей без
        // этих секций кнопка «Параметры» (напр. «Выжимка видео») молча не
        // открывала модалку. Открываем всегда, если виден сам список модулей;
        // запись по-прежнему гейтится per-item canEditConfig → read-only.
        if (!this.canViewTab('modules')) {
          this.toast('Нет доступа к модулям', 'warn');
          return;
        }
        this.openModuleId = m.id;
        this._ensureModuleData(m);
        if (!this.configItems.length) this.loadConfig();
        // T-1900: baseline для sticky-save — момент открытия модалки
        // (guard — unit-стабы openModuleWindow).
        if (typeof this._snapshotConfig === 'function') this._snapshotConfig();
      },
      // MAJOR-2: операционные панели Сон/Ностальгия живут в модалке —
      // данные грузятся при открытии (не только по activeTab).
      _ensureModuleData: function (m) {
        if (!m || !this.isGlobalAdmin) return;
        if (m.id === 'mod_sleep') {
          if (!this.dreamBeliefs.length && !this.memoryRagBusy) {
            this.loadDreamBeliefs();
            this.loadDreamLog();
          }
        } else if (m.id === 'mod_nostalgia') {
          if (!this.nostalgiaLog.length && !this.memoryRagBusy) {
            this.loadNostalgiaLog();
          }
        }
      },
      closeModule: function () {
        this.openModuleId = null;
        // S10.18-22: модалка «Сон» живёт на вкладке modules — ускоренный
        // polling/ретраи, запущенные кнопкой «Сон сейчас», не должны жить
        // после закрытия модалки вне вкладки «Статус» (F5/R10.11-5).
        if (this.activeTab !== 'status') this.stopCognitionPolling();
      },

      // ═══ Раунд 10.20 (БЛОК 3.6/T-1900): sticky-save ═══════════════════
      // Одна закреплённая панель «Отмена» / «Сохранить изменения» вместо
      // индивидуальных кнопок под инпутами. Baseline — configSnapshot,
      // снимается при загрузке конфига и открытии модалки; тумблеры/select
      // остаются на мгновенном auto-save (существующий путь saveConfigItem).
      _serializeValue: function (v) {
        try { return JSON.stringify(v); } catch (e) { return String(v); }
      },
      _snapshotConfig: function () {
        var snap = {};
        (this.configItems || []).forEach(function (it) {
          if (it && it.key != null) snap[it.key] = JSON.stringify(it.value);
        });
        this.configSnapshot = snap;
        // F9 (10.25, ADR-1025-22 D1): маска больше НЕ засеивается в значение
        // input. Оставляем вызов — страховочная очистка legacy/композитных
        // черновиков (маска не является значением поля, §50/R17).
        if (typeof this._seedSecretMasks === 'function') this._seedSecretMasks();
      },
      // F9 (ADR-1025-22 D1, отменяет засев UPD3/R31): маска — display-
      // индикатор (`secretDisplay`), а НЕ значение `input`. Поле ввода
      // configured-секрета всегда пустое: не трогали → draft пуст → не
      // сохраняется; замена → реальный ввод. Здесь лишь убираем остатки
      // маски/композита из черновиков (defense-in-depth; в API они не уйдут
      // и благодаря guard'ам dirtyKeyItems/saveKeyItem/saveBlock).
      _seedSecretMasks: function () {
        var self = this;
        if (!this.keyDrafts || typeof this.keyDrafts !== 'object') {
          this.keyDrafts = {};
          return;
        }
        Object.keys(this.keyDrafts).forEach(function (k) {
          if (hasSecretMask(self.keyDrafts[k])) delete self.keyDrafts[k];
        });
      },
      cancelModalEdits: function () {
        var snap = this.configSnapshot || {};
        (this.configItems || []).forEach(function (it) {
          if (!it || it.key == null) return;
          if (!Object.prototype.hasOwnProperty.call(snap, it.key)) return;
          try { it.value = JSON.parse(snap[it.key]); } catch (e) { /* keep */ }
        });
        // UPD3: вместо keyDrafts={} — пере-сев масок (пустые поля не вернуть).
        this.keyDrafts = {};
        if (typeof this._seedSecretMasks === 'function') this._seedSecretMasks();
        this.stickyFailed = [];
        this.toast('Изменения отменены', 'ok');
      },
      saveModalEdits: async function () {
        if (this.stickySaving) return;
        var dirty = this.dirtyItems.slice();
        var keys = this.dirtyKeyItems.slice();
        if (!dirty.length && !keys.length) {
          this.toast('Нет изменений для сохранения', 'warn');
          return;
        }
        this.stickySaving = true;
        // S10.20-6: собираем провалы; baseline сдвигаем ТОЛЬКО если всё
        // сохранилось — иначе ошибка «благословлялась» бы как новая норма.
        // F0.4 (ADR-1025-4 D1): ОДНО итоговое уведомление на операцию —
        // значения пишет persistItems (silent), секреты — saveKeyItem(silent),
        // итог озвучивается ниже один раз.
        var failed = [];
        var failedKeys = [];
        var total = dirty.length + keys.length;
        try {
          if (typeof this.persistItems === 'function') {
            if (dirty.length) {
              var res = await this.persistItems(dirty, {
                operationId: 'sticky-' + (++this._opSeq), silent: true,
              });
              for (var i = 0; i < res.failed.length; i++) {
                var fi = this._findConfigItem(res.failed[i].key);
                failed.push((fi && fi.title) || res.failed[i].key);
                failedKeys.push(res.failed[i].key);
              }
              // Ревью (item 3): пропущенные по guard in-flight ключи — НЕ
              // молча: считаем неподтверждёнными (baseline не сдвигаем).
              var skipped = res.skipped || [];
              for (var sk = 0; sk < skipped.length; sk++) {
                var skItem = this._findConfigItem(skipped[sk]);
                failed.push((skItem && skItem.title) || skipped[sk]);
                failedKeys.push(skipped[sk]);
              }
            }
            for (var j = 0; j < keys.length; j++) {
              var okKey = await this.saveKeyItem(keys[j], true);
              if (okKey === false) {
                failed.push(keys[j].title || keys[j].key);
                failedKeys.push(keys[j].key);
              }
            }
          } else {
            // Легаси-контекст (юнит-тесты) без единого write-path: поштучно.
            for (var i2 = 0; i2 < dirty.length; i2++) {
              var ok = await this.saveConfigItem(dirty[i2]);
              if (ok === false) {
                failed.push(dirty[i2].title || dirty[i2].key);
                failedKeys.push(dirty[i2].key);
              }
            }
            for (var j2 = 0; j2 < keys.length; j2++) {
              var okKey2 = await this.saveKeyItem(keys[j2]);
              if (okKey2 === false) {
                failed.push(keys[j2].title || keys[j2].key);
                failedKeys.push(keys[j2].key);
              }
            }
          }
          if (failed.length) {
            this.stickyFailed = failed;
            this.stickyFailedKeys = failedKeys;
            this.toast('Сохранено ' + (total - failed.length) + ' из ' +
                       total + '; не сохранено: ' + failed.join(', '),
                       failed.length === total ? 'err' : 'warn');
          } else {
            this.stickyFailed = [];
            this.stickyFailedKeys = [];
            this._snapshotConfig();
            this.toast('Изменения сохранены (' + total + ')', 'ok');
          }
        } finally {
          this.stickySaving = false;
        }
      },

      // ═══ Раунд 10.20 (БЛОК 3.2/T-1896): Досье участника ═══════════════
      openDossier: async function (row) {
        if (!row || row.user_id == null || this.activeChatId == null) return;
        this.dossierOpen = true;
        this.dossierBusy = true;
        this.dossierUserId = row.user_id;
        this.dossierName = this.resolveRelationName(row) || '';
        this.dossierData = null;
        this.dossierDraft = '';
        // F8: пересборка — состояние per-user; прогресс подтягиваем с сервера.
        this.dossierRebuildJob = null;
        this.stopDossierRebuildPolling();
        try {
          await this.loadDossier(row.user_id, this.dossierName);
          await this.resumeDossierRebuild();
        } finally {
          this.dossierBusy = false;
        }
      },
      loadDossier: async function (userId, name) {
        var url = '/api/chat_lore/' + this.activeChatId + '/dossier/' + userId;
        if (name) url += '?name=' + encodeURIComponent(name);
        try {
          var data = await this.api(url);
          this.dossierData = data;
          this.dossierDraft = (data && data.manual_traits) || '';
        } catch (e) {
          this.dossierData = null;
          this.toast('Не удалось загрузить досье: ' + this.loreErrText(e), 'err');
        }
      },
      closeDossier: function () {
        this.dossierOpen = false;
        this.dossierBusy = false;
        this.dossierUserId = null;
        this.dossierName = '';
        this.dossierData = null;
        this.dossierDraft = '';
        // F8: polling не должен жить после закрытия модалки; сам job остаётся
        // на сервере и подтянется при reopen (persistence).
        this.stopDossierRebuildPolling();
      },
      saveDossier: async function () {
        if (this.dossierUserId == null || this.activeChatId == null) return;
        if (this.dossierSaving) return;
        this.dossierSaving = true;
        try {
          var url = '/api/chat_lore/' + this.activeChatId
            + '/dossier/' + this.dossierUserId;
          if (this.dossierName) {
            url += '?name=' + encodeURIComponent(this.dossierName);
          }
          var data = await this.api(url, {
            method: 'PUT',
            body: JSON.stringify({ traits: this.dossierDraft || '' }),
          });
          this.dossierData = data;
          this.dossierDraft = (data && data.manual_traits) || '';
          this.toast(this.dossierDraft
            ? 'Досье обновлено' : 'Правка сброшена — досье авто', 'ok');
        } catch (e) {
          this.toast('Не удалось сохранить досье: ' + this.loreErrText(e), 'err');
        } finally {
          this.dossierSaving = false;
        }
      },

      // ═══ F8 round 10.22 (ADR-1022-8): пересборка досье ═══════════════
      // Сервер — источник истины (job-store); фронт лишь рисует состояние и
      // опрашивает GET, пока job активен. Ошибки GET — fail-open (нейтрально).
      dossierRebuildIsActive: function (job) {
        // S10.22-5: `interrupted` — НЕ активен для целей блокировки старта
        // (оживёт только ручной откат). Активны лишь работающие статусы.
        return !!job && ['queued', 'running', 'cancelling']
          .indexOf(job.status) >= 0;
      },
      dossierRebuildCancelable: function (job) {
        // Отмена/откат доступны и для `interrupted` (после рестарта процесса),
        // хотя новый старт при этом разрешён.
        return !!job && (this.dossierRebuildIsActive(job)
          || job.status === 'interrupted');
      },
      dossierRebuildStageText: function (job) {
        var map = {
          snapshot: 'Снимок данных', cleanup: 'Очистка мусора',
          extract: 'Извлечение фактов', synthesize: 'Синтез портрета',
          write: 'Запись досье', finalize: 'Завершение',
          rollback: 'Откат изменений',
        };
        return (job && map[job.stage]) || 'Выполняется';
      },
      // F8 §2.6 п.5: терминальный 'failed' не тупик — если снапшот цел и
      // откат ещё не сделан, доступен повторный откат (кнопка «Повторить
      // откат» вместо «Пересобрать заново»). Зеркалит серверный критерий.
      dossierRollbackRetryable: function (job) {
        if (!job || job.status !== 'failed' || !job.snapshot_ref) return false;
        var rb = job.rollback || {};
        if (rb.done) return false;
        return job.error_code === 'rollback_failed'
          || (job.cleaned || 0) > 0 || (job.rebuilt || 0) > 0;
      },
      startDossierRebuild: async function () {
        if (this.dossierUserId == null || this.activeChatId == null) return;
        if (this.dossierRebuildBusy) return;
        if (this.dossierRebuildIsActive(this.dossierRebuildJob)) return;
        var period = this.dossierRebuildPeriod || '180';
        if (period === 'all' && !window.confirm(
            'Пересборка «Всё время» может занять много времени и токенов. '
            + 'Продолжить?')) {
          return;
        }
        this.dossierRebuildBusy = true;
        try {
          var url = '/api/chat_lore/' + this.activeChatId + '/dossier/'
            + this.dossierUserId + '/rebuild';
          if (this.dossierName) {
            url += '?name=' + encodeURIComponent(this.dossierName);
          }
          var data = await this.api(url, {
            method: 'POST',
            body: JSON.stringify({ period: period }),
          });
          this.dossierRebuildJob = data || null;
          this._rememberDossierRebuild(data && data.job_id);
          this.startDossierRebuildPolling();
          this.toast('Пересборка досье запущена', 'ok');
        } catch (e) {
          var code = (e && e.message && e.message.code) || null;
          if (e && e.status === 409 && code === 'chat_locked') {
            // Кросс-процессный lock: пересборку чата уже ведёт CLI-прогон.
            // Своего job'а нет — polling не запускаем.
            this.toast('Чат занят другим прогоном пересборки — повторите '
              + 'позже', 'warn');
          } else if (e && e.status === 409) {
            // already_running: подхватываем существующий job.
            await this.loadDossierRebuild();
            this.startDossierRebuildPolling();
            this.toast('Пересборка уже выполняется', 'warn');
          } else {
            this.toast('Не удалось запустить пересборку: '
              + this.loreErrText(e), 'err');
          }
        } finally {
          this.dossierRebuildBusy = false;
        }
      },
      loadDossierRebuild: async function () {
        if (this.dossierUserId == null || this.activeChatId == null) return;
        try {
          var data = await this.api('/api/chat_lore/' + this.activeChatId
            + '/dossier/' + this.dossierUserId + '/rebuild/latest');
          this.dossierRebuildEnabled = true;
          this.dossierRebuildJob = data || null;
          this._rememberDossierRebuild(data && data.job_id);
        } catch (e) {
          // S10.22-6: kill-switch OFF → `latest` отдаёт 404. Прячем весь блок,
          // а не показываем кнопку, ведущую в ошибку. Прочие сбои — fail-open.
          if (e && e.status === 404) {
            this.dossierRebuildEnabled = false;
          }
          this.dossierRebuildJob = null;
        }
      },
      resumeDossierRebuild: async function () {
        if (this.dossierUserId == null) return;
        await this.loadDossierRebuild();
        if (this.dossierRebuildIsActive(this.dossierRebuildJob)) {
          this.startDossierRebuildPolling();
        } else {
          this.stopDossierRebuildPolling();
        }
      },
      pollDossierRebuild: async function () {
        var job = this.dossierRebuildJob;
        if (!job || !job.job_id || this.dossierUserId == null) return;
        try {
          var data = await this.api('/api/chat_lore/' + this.activeChatId
            + '/dossier/' + this.dossierUserId + '/rebuild/' + job.job_id);
          if (!data) return;
          this.dossierRebuildJob = data;
          if (!this.dossierRebuildIsActive(data)) {
            this.stopDossierRebuildPolling();
            if (data.status === 'done') {
              await this.loadDossier(this.dossierUserId, this.dossierName);
              this.toast('Досье пересобрано', 'ok');
            } else if (data.status === 'cancelled') {
              await this.loadDossier(this.dossierUserId, this.dossierName);
              this.toast('Пересборка отменена — данные восстановлены', 'warn');
            } else if (data.status === 'failed') {
              this.toast('Пересборка не удалась', 'err');
            }
          }
        } catch (e) {
          // Одиночный сбой опроса — не роняем UI; следующий тик повторит.
        }
      },
      startDossierRebuildPolling: function () {
        var self = this;
        this.stopDossierRebuildPolling();
        if (!this.dossierRebuildIsActive(this.dossierRebuildJob)) return;
        this.dossierRebuildTimer = setInterval(function () {
          self.pollDossierRebuild();
        }, 2000);
      },
      stopDossierRebuildPolling: function () {
        if (this.dossierRebuildTimer) {
          clearInterval(this.dossierRebuildTimer);
          this.dossierRebuildTimer = null;
        }
      },
      cancelDossierRebuild: async function () {
        var job = this.dossierRebuildJob;
        if (!job || !job.job_id || this.dossierRebuildBusy) return;
        var retry = this.dossierRollbackRetryable(job);
        if (!window.confirm(retry
            ? 'Повторить откат досье/фактов участника из снимка?'
            : 'Отменить пересборку и откатить досье/факты участника?')) return;
        this.dossierRebuildBusy = true;
        try {
          await this.api('/api/chat_lore/' + this.activeChatId + '/dossier/'
            + this.dossierUserId + '/rebuild/' + job.job_id + '/cancel',
            { method: 'POST' });
          this.dossierRebuildJob = Object.assign({}, job,
            { status: 'cancelling' });
          this.startDossierRebuildPolling();
        } catch (e) {
          this.toast('Не удалось отменить: ' + this.loreErrText(e), 'err');
        } finally {
          this.dossierRebuildBusy = false;
        }
      },
      _rememberDossierRebuild: function (jobId) {
        // localStorage — лишь подсказка {chat,user,job}; истина — сервер.
        try {
          if (jobId) {
            localStorage.setItem('adminbot.dossier_rebuild', JSON.stringify({
              chat_id: this.activeChatId, user_id: this.dossierUserId,
              job_id: jobId,
            }));
          } else {
            localStorage.removeItem('adminbot.dossier_rebuild');
          }
        } catch (e) { /* приватный режим — не критично */ }
      },

      // ═══ Раунд 10.20 (БЛОК 3.3/T-1897): «Живая лента досье» ══════════
      // F4 (10.24, ADR-1024-8 D4): клик по строке ленты (UPD3 №9).
      // Лента по умолчанию GLOBAL (активного чата нет), а `openDossier` —
      // per-chat: сначала переключаем контекст (setActiveChat → reload
      // config/lore/oversight), затем открываем модалку. Строка без user_id
      // в сюда не попадает. Ошибка переключения → toast, модалка не открывается.
      openFeedDossier: async function (it) {
        if (!it || it.user_id == null) return;
        var chatId = (it.chat_id == null) ? null : String(it.chat_id);
        // Спека §3.2(2)/review iter1: чат факта обязателен — иначе открыли бы
        // чужое досье в текущем активном чате (риск R1). chat_id 0/пусто —
        // то же «неизвестный чат».
        if (chatId == null || chatId === '' || chatId === '0') {
          this.toast('Не удалось определить чат факта', 'err');
          return;
        }
        if (this.activeChatId == null || String(this.activeChatId) !== chatId) {
          try {
            this.setActiveChat(chatId);
          } catch (e) {
            this.toast('Не удалось переключить чат: '
              + (e && e.message ? e.message : e), 'err');
            return;
          }
        }
        if (this.activeChatId == null) {
          this.toast('Не удалось открыть досье: не выбран чат', 'err');
          return;
        }
        await this.openDossier({
          user_id: it.user_id,
          name: it.user_name || it.name || '',
        });
      },
      loadDossierFeed: async function () {
        if (this.dossierFeedBusy) return;
        this.dossierFeedBusy = true;
        try {
          var url = '/api/oversight/dossier_feed?limit=16';
          if (this.activeChatId != null) {
            url += '&chat_id=' + encodeURIComponent(this.activeChatId);
          }
          var data = await this.api(url);
          this.dossierFeed = (data && data.items) || [];
          this.dossierFeedError = '';
        } catch (e) {
          this.dossierFeed = [];
          this.dossierFeedError = this.loreErrText(e);
        } finally {
          this.dossierFeedBusy = false;
        }
      },
      // Реактивность без лишних запросов: один запрос на смену scope/чата;
      // polling-таймер перезапускается только по явному вызову.
      startDossierFeedPolling: function () {
        var self = this;
        this.stopDossierFeedPolling();
        this.loadDossierFeed();
        this.dossierFeedTimer = setInterval(function () {
          self.loadDossierFeed();
        }, 45000);   // 45с — лента живая, но не дёргает API
      },
      stopDossierFeedPolling: function () {
        if (this.dossierFeedTimer) {
          clearInterval(this.dossierFeedTimer);
          this.dossierFeedTimer = null;
        }
      },

      canEditModule: function (m) {
        return !!m && this.canEditConfig(m.toggleKey);
      },

      // ═══════ F4 (10.25, ADR-1025-14 D1/D2): ModuleConfigurationStore ═══════
      // Тонкий слой над существующим `configItems` (§39: без новых
      // библиотек). Канонический источник значений — configItems; store
      // добавляет только оверлей операции (ovely/pending/error).
      // §38: логический ключ — `scope_type/scope_id/module_id`.
      storeScope: function () {
        var kind = this.scopeKind;
        if (kind !== 'chat' && kind !== 'dm') kind = 'global';
        var id = (kind === 'global' || this.activeChatId == null)
          ? null : this.activeChatId;
        return { type: kind, id: id };
      },
      storeKey: function (scope, moduleId) {
        scope = scope || this.storeScope();
        var type = (scope && scope.type) ? scope.type : 'global';
        var idPart = (scope && scope.id != null) ? String(scope.id) : 'null';
        return type + '/' + idPart + '/' + moduleId;
      },
      _moduleById: function (moduleId) {
        var list = this.modules || [];
        for (var i = 0; i < list.length; i++) {
          if (list[i] && list[i].id === moduleId) return list[i];
        }
        return null;
      },
      // Данные `configItems` относятся ТОЛЬКО к активной области
      // (setActiveChat очищает+перезагружает их) → для чужой области
      // фактическое состояние недоступно (не выдумываем его).
      _isActiveScope: function (scope) {
        if (!scope) return false;
        var cur = this.storeScope();
        var a = (cur.id == null) ? 'null' : String(cur.id);
        var b = (scope.id == null) ? 'null' : String(scope.id);
        return cur.type === scope.type && a === b;
      },
      _moduleConfigItem: function (m) {
        if (!m || !m.toggleKey) return null;
        var items = this.configItems || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i] && items[i].key === m.toggleKey) return items[i];
        }
        return null;
      },
      // §39: производное состояние (overlay → configItems → «неизвестно»).
      getModuleState: function (scope, moduleId) {
        scope = scope || this.storeScope();
        var key = this.storeKey(scope, moduleId);
        var m = this._moduleById(moduleId);
        var active = this._isActiveScope(scope);
        var item = (active && m) ? this._moduleConfigItem(m) : null;
        var known = !!(item && item.value !== null && item.value !== undefined);
        var effective = known ? item.value : null;
        var globalValue = (item && item.global_value !== undefined)
          ? item.global_value : null;
        var hasOverride = !!(item && scope.type !== 'global'
          && item.chat_source === 'chat');
        var overlay = this.moduleOptimistic ? this.moduleOptimistic[key] : null;
        var pending = !!(this.modulePending && this.modulePending[key]);
        var error = (this.moduleSaveError && this.moduleSaveError[key]) || '';
        var display = (overlay && pending) ? !!overlay.value
                                           : (known ? effective : null);
        return {
          key: key, known: known, effective: effective, globalValue: globalValue,
          hasOverride: hasOverride, display: display,
          runtime: this._moduleRuntimeState(m, item, scope, known),
          pending: pending, error: error,
        };
      },
      // §43: фактическое рабочее состояние (не просто значение флага):
      //   on      — включён и реально работает;
      //   off     — выключен (без конфликта);
      //   blocked — включён, но глобальный/родительский гейт выключен;
      //   inert   — локальный override для gate='global' не влияет;
      //   unknown — нет элемента/значения (≠ выключено!).
      _moduleRuntimeState: function (m, item, scope, known) {
        if (!known || !item) return 'unknown';
        var eff = (item.value === true);
        var gate = (m && m.runtimeGate) || 'global';
        if (!eff) {
          if (item.chat_source === 'chat' && gate === 'global') return 'inert';
          return 'off';
        }
        if (m && m.parentGate && m.parentGate !== m.toggleKey
            && typeof this._findConfigItem === 'function') {
          var p = this._findConfigItem(m.parentGate);
          if (p && p.value === false) return 'blocked';
        }
        // F4-M1 (§43, ADR-1025-14 D3): включён локально, но gate='global'
        // и глобально выключен → локальный override НЕ действует: модуль
        // фактически не работает. Условие симметрично `moduleRuntimeNotice`
        // (только НЕглобальная область: в глобальной effective === global_value).
        if (gate === 'global' && scope && scope.type !== 'global'
            && item.global_value === false) return 'blocked';
        return 'on';
      },
      // §43: подпись фактического состояния для НЕглобальной области.
      // Отдельный helper — `configItemNotice` (F3) НЕ изменяется.
      moduleRuntimeNotice: function (m) {
        if (!m) return '';
        var scope = this.storeScope();
        var item = this._moduleConfigItem(m);
        if (!item) return '';
        var gate = m.runtimeGate || 'global';
        var gv = item.global_value;
        var eff = item.value;
        var hasOverride = item.chat_source === 'chat';
        // Родительский гейт (флаги 0a–0i) — глобальный выключатель: показываем
        // в ЛЮБОЙ области, если модуль включён, но фактически не работает.
        if (m.parentGate && m.parentGate !== m.toggleKey && eff === true
            && typeof this._findConfigItem === 'function') {
          var p = this._findConfigItem(m.parentGate);
          if (p && p.value === false) return 'Не работает: отключён глобально';
        }
        if (scope.type === 'global') return '';
        if (gv === false && eff === true) {
          if (gate === 'per_chat') {
            return 'Включено для этой области (глобально выключено)';
          }
          if (gate === 'unknown') {
            return 'Локальное значение сохранено; глобально модуль выключен';
          }
          return 'Не работает: отключён глобально (локальное значение сохранено)';
        }
        if (eff === false && hasOverride && gate === 'global') {
          return 'Отключение для этой области не влияет: '
            + 'модуль управляется глобально';
        }
        return '';
      },
      moduleStateText: function (m) {
        if (!m) return '';
        if (m.noToggle) return 'Управляется параметрами';
        var st = this.getModuleState(this.storeScope(), m.id);
        if (st.runtime === 'unknown' || st.display === null) {
          return 'Состояние неизвестно';
        }
        if (st.runtime === 'blocked') return 'Включён, но не работает';
        return st.display ? 'Включён' : 'Выключен';
      },
      moduleSourceText: function (m) {
        if (!m || !m.toggleKey) return '';
        var item = this._moduleConfigItem(m);
        return item ? this.configSourceLabel(item) : '';
      },
      modulePendingFor: function (m) {
        if (!m) return false;
        var key = this.storeKey(this.storeScope(), m.id);
        return !!(this.modulePending && this.modulePending[key]);
      },
      moduleSaveErrorFor: function (m) {
        if (!m) return '';
        var key = this.storeKey(this.storeScope(), m.id);
        return (this.moduleSaveError && this.moduleSaveError[key]) || '';
      },
      _moduleSaveFailed: function (m) {
        if (!m || !m.toggleKey) return false;
        var keys = this.stickyFailedKeys || [];
        return keys.indexOf(m.toggleKey) >= 0;
      },
      _moduleSearchHaystack: function (m) {
        if (!m) return '';
        var parts = [m.title, m.subtitle, m.toggleKey, m.id];
        if (m.keywords && m.keywords.length) {
          parts = parts.concat(m.keywords);
        }
        return parts.join(' ').toLowerCase();
      },
      // §39: адаптация существующих вызовов шаблона (внешнее поведение
      // сохранено; RBAC — в canEditModule/setModuleState).
      moduleEnabled: function (m) {
        if (!m) return false;
        return this.getModuleState(this.storeScope(), m.id).display === true;
      },
      toggleModule: async function (m, checked) {
        if (!m) return { ok: false, error: 'unknown-module' };
        return await this.setModuleState(this.storeScope(), m.id, checked);
      },
      // §40–§42: ОДНА мутация на действие через канонический write-path F0.
      setModuleState: async function (scope, moduleId, enabled) {
        var self = this;
        scope = scope || this.storeScope();
        var m = this._moduleById(moduleId);
        if (!m) return { ok: false, error: 'unknown-module' };
        // 1) RBAC
        if (typeof this.canEditModule === 'function' && !this.canEditModule(m)) {
          this.toast('Нет права изменить модуль', 'err');
          return { ok: false, error: 'forbidden' };
        }
        // 2) данные чужой области в памяти отсутствуют → мутации нет.
        if (!this._isActiveScope(scope)) {
          return { ok: false, error: 'inactive-scope' };
        }
        // 3) канонический элемент конфигурации (нет → не выдумываем запись)
        var item = this._moduleConfigItem(m);
        if (!item) {
          this.toast('Параметр недоступен: ' + m.toggleKey, 'warn');
          return { ok: false, error: 'missing-item' };
        }
        var key = this.storeKey(scope, moduleId);
        // 4) блокировка повтора (§41.2): повторный тап по ключу — no-op
        if (this.modulePending && this.modulePending[key]) {
          return { ok: false, skipped: true };
        }
        // fix scope + epoch ДО await (§42): «текущий чат на момент ответа»
        // нигде не читается.
        var epoch = this.scopeEpoch;
        var opId = 'mod-' + (++this._opSeq);
        var prevValue = item.value;
        if (!this.modulePending) this.modulePending = {};
        if (!this.moduleOptimistic) this.moduleOptimistic = {};
        if (!this.moduleSaveError) this.moduleSaveError = {};
        // 5) оптимистично — ТОЛЬКО overlay; configItems НЕ мутируем
        //    (структурная гарантия отката §41).
        this.moduleOptimistic[key] = { value: !!enabled, opId: opId };
        this.modulePending[key] = true;
        this.moduleSaveError[key] = '';
        var res;
        try {
          // 6) ровно ОДНА мутация: один элемент → одна группа → один POST
          res = await this.persistItems(
            [{ key: m.toggleKey, value: !!enabled, per_chat: item.per_chat }],
            { operationId: opId });
        } catch (e) {
          res = { saved: [], skipped: [],
                  failed: [{ key: m.toggleKey,
                             reason: (e && e.message) || 'error' }],
                  revalidated: false, state: 'error' };
        }
        res = res || {};
        var sameScope = (epoch === this.scopeEpoch);
        var saved = (res.saved || []).indexOf(m.toggleKey) >= 0;
        var skipped = (res.skipped || []).indexOf(m.toggleKey) >= 0;
        var failedObj = null;
        (res.failed || []).forEach(function (f) {
          if (f && f.key === m.toggleKey) failedObj = f;
        });
        var reload = async function () {
          if (!sameScope) return;   // чужая область: ничего не читаем/не меняем
          try {
            if (typeof self._preserveScroll === 'function') {
              await self._preserveScroll(self.loadConfig);
            } else if (typeof self.loadConfig === 'function') {
              await self.loadConfig();
            }
          } catch (e) { /* fail-open */ }
        };
        if (skipped) {
          // вторая линия in-flight-guard F0: запрос уже летит (не наш итог)
          delete this.moduleOptimistic[key];
          this.modulePending[key] = false;
          return { ok: false, skipped: true };
        }
        if (saved || res.revalidated) {
          await reload();           // значение подтверждено сервером
          delete this.moduleOptimistic[key];
          this.modulePending[key] = false;
          return { ok: true };
        }
        // 7) ошибка/409: overlay снимаем → UI возвращается к серверному
        // значению (configItems не мутировался). F0-ветка 409 возвращает
        // черновик в элемент — восстанавливаем подтверждённое значение.
        if (sameScope) {
          var cur = (typeof this._findConfigItem === 'function')
            ? this._findConfigItem(m.toggleKey) : null;
          if (cur && prevValue !== undefined) cur.value = prevValue;
          if (failedObj && failedObj.reason === 'conflict') await reload();
        }
        delete this.moduleOptimistic[key];
        this.modulePending[key] = false;
        this.moduleSaveError[key] = (failedObj && failedObj.reason === 'conflict')
          ? 'Конфликт версии — значение перечитано'
          : 'Не удалось сохранить';
        return { ok: false, error: (failedObj && failedObj.reason) || 'error' };
      },
      // §39: re-read канонического конфига. Данных чужой области в памяти
      // нет → для неактивной области no-op (новых API нет, R16).
      refreshModuleState: async function (scope, moduleId) {
        scope = scope || this.storeScope();
        if (!this._isActiveScope(scope)) return false;
        if (typeof this.loadConfig !== 'function') return false;
        if (typeof this._preserveScroll === 'function') {
          await this._preserveScroll(this.loadConfig);
        } else {
          await this.loadConfig();
        }
        return true;
      },
      // §39: подписка на состояние ключа. В Options API шаблоны реактивны
      // неявно; метод даёт явный контракт + функцию отписки.
      subscribeModuleState: function (scope, moduleId, cb) {
        if (typeof cb !== 'function' || typeof this.$watch !== 'function') {
          return function () {};
        }
        var self = this;
        var fixedScope = scope || this.storeScope();
        var stop = this.$watch(function () {
          return JSON.stringify(self.getModuleState(fixedScope, moduleId));
        }, function () { cb(self.getModuleState(fixedScope, moduleId)); });
        return function () { try { stop(); } catch (e) { /* noop */ } };
      },
      // ═══ F4 D4/§34–§36: избранное — UI-предпочтение (localStorage) ═══
      _quickpicksStorageKey: function () {
        var suffix = '';
        if (this.me && this.me.telegram_id != null) {
          suffix = ':' + this.me.telegram_id;
        }
        return 'adminbot.modules_quickpicks.v1' + suffix;
      },
      _lsGet: function (k) {
        try {
          var ls = (typeof window !== 'undefined' && window.localStorage)
            ? window.localStorage
            : ((typeof localStorage !== 'undefined') ? localStorage : null);
          return ls ? ls.getItem(k) : null;
        } catch (e) { return null; }
      },
      _lsSet: function (k, v) {
        try {
          var ls = (typeof window !== 'undefined' && window.localStorage)
            ? window.localStorage
            : ((typeof localStorage !== 'undefined') ? localStorage : null);
          if (!ls) return false;
          ls.setItem(k, v);
          return true;
        } catch (e) { return false; }
      },
      _defaultQuickpicks: function () {
        var base = ['mod_summary', 'mod_direct', 'mod_factcheck', 'mod_search'];
        var allowed = {};
        this.quickpickCandidates.forEach(function (m) { allowed[m.id] = true; });
        var out = [];
        base.forEach(function (id) { if (allowed[id]) out.push(id); });
        if (!out.length) {
          this.quickpickCandidates.slice(0, 4).forEach(function (m) {
            out.push(m.id);
          });
        }
        return out;
      },
      _sanitizeQuickpicks: function (ids) {
        var allowed = {};
        this.quickpickCandidates.forEach(function (m) { allowed[m.id] = true; });
        var out = [];
        (ids || []).forEach(function (id) {
          if (allowed[id] && out.indexOf(id) < 0) out.push(id);
        });
        return out;
      },
      _readQuickpicks: function () {
        var raw = this._lsGet(this._quickpicksStorageKey());
        if (!raw) return null;
        try {
          var parsed = JSON.parse(raw);
          return Array.isArray(parsed) ? parsed : null;
        } catch (e) { return null; }
      },
      _writeQuickpicks: function () {
        try {
          return this._lsSet(this._quickpicksStorageKey(),
            JSON.stringify(this.moduleQuickpicks || []));
        } catch (e) { return false; }
      },
      // fail-open: нет localStorage / битый JSON → стартовый набор §34.
      initQuickpicks: function () {
        var stored = this._readQuickpicks();
        if (!stored) {
          if (Array.isArray(this.moduleQuickpicks)
              && this.moduleQuickpicks.length) {
            return;   // уже инициализировано (повторный вызов после loadMe)
          }
          stored = this._defaultQuickpicks();
        }
        this.moduleQuickpicks = this._sanitizeQuickpicks(stored);
      },
      isQuickpick: function (m) {
        return !!m && (this.moduleQuickpicks || []).indexOf(m.id) >= 0;
      },
      // Закрепление/открепление НЕ включает/выключает модуль (§36).
      toggleQuickpick: function (m) {
        if (!m) return;
        var ids = (this.moduleQuickpicks || []).slice();
        var idx = ids.indexOf(m.id);
        if (idx >= 0) ids.splice(idx, 1);
        else ids.push(m.id);
        this.moduleQuickpicks = this._sanitizeQuickpicks(ids);
        this._writeQuickpicks();
      },
      // F5 (ADR-1025-15 D2/§46): шов F4 меняет РЕАЛИЗАЦИЮ — теперь это
      // навигация на страницу модуля `#/modules/<slug>` (§46). Точка входа
      // (кнопка «Настроить») не меняется. Если workspace-определение или
      // hash-навигация недоступны (file://, unit-стаб) — fallback на
      // регресс-путь `openModuleWindow` (модалка, §60.2/§79/§116).
      openModuleWorkspace: function (m) {
        if (!m) return;
        if (typeof this.canViewTab === 'function'
            && !this.canViewTab('modules')) {
          this.toast('Нет доступа к модулям', 'warn');
          return;
        }
        var slug = this.routeSlugOf ? this.routeSlugOf(m)
          : (m.routeSlug || String(m.id || '').replace(/^mod_/, ''));
        var navOk = (typeof this._workspaceNavAvailable === 'function')
          ? this._workspaceNavAvailable() : true;
        if (typeof this.navigateTo !== 'function' || !navOk) {
          return this.openModuleWindow(m);
        }
        this.navigateTo('#/modules/' + slug);
      },
      // file:// / unit-стаб без hashchange → модалка (мягкий регресс-путь).
      _workspaceNavAvailable: function () {
        try {
          if (typeof window === 'undefined') return false;
          if (window.location && window.location.protocol === 'file:') {
            return false;
          }
          return true;
        } catch (e) { return false; }
      },
      routeSlugOf: function (m) {
        if (!m) return '';
        return m.routeSlug || String(m.id || '').replace(/^mod_/, '');
      },
      // Поиск модуля по slug среди ТЕКУЩЕГО `this.modules` (production/MODULES).
      moduleBySlug: function (slug) {
        var list = this.modules || MODULES;
        if (!slug) return null;
        for (var i = 0; i < list.length; i++) {
          var m = list[i];
          var s = m.routeSlug || String(m.id || '').replace(/^mod_/, '');
          if (s === slug) return m;
        }
        return null;
      },
      // Навигация по вкладке workspace (hash — источник истины).
      openWorkspaceTab: function (tabId) {
        var ws = this.workspace;
        if (!ws) return;
        var next = '#/modules/' + ws.slug;
        if (tabId && tabId !== 'overview') next += '/' + tabId;
        this.navigateTo(next);
      },
      workspaceTabLabel: function (tabId) {
        return WORKSPACE_TAB_LABELS[tabId] || tabId || '';
      },
      // ── S9 round1026 (ADR-1026-8 D1/D3/D4, §113): dry-run «Тестирование» ──
      // Probe доступности: env-флаг OFF → API 404 → секция скрыта (D8).
      maybeLoadSummaryTest: function () {
        var ws = this.workspace;
        if (!ws || !ws.module || ws.module.id !== 'mod_summary'
            || ws.tab !== 'testing') {
          return;
        }
        if (this.summaryTest.available !== null || this.summaryTest._probing) {
          return;
        }
        this.summaryTest._probing = true;
        var self = this;
        this.api('/api/summary/test/availability')
          .then(function () { self.summaryTest.available = true; })
          .catch(function () { self.summaryTest.available = false; })
          .then(function () {
            self.summaryTest._probing = false;
            if (self.summaryTest.available && !self.summaryTest.chatId
                && self.accessChats.length) {
              self.summaryTest.chatId = self.accessChats[0].chat_id;
            }
          });
      },
      // «Проверить пайплайн»: async-запуск + опрос результата (D4).
      summaryTestRun: function () {
        var self = this;
        var st = this.summaryTest;
        if (st.running) return;
        if (!st.chatId) { this.toast('Выберите чат для проверки', 'err'); return; }
        st.running = true;
        st.error = '';
        st.result = null;
        st.testId = null;
        st.cover = null;
        this.api('/api/summary/test/run', {
          method: 'POST', global: true,
          body: JSON.stringify({ chat_id: st.chatId, window_hours: st.hours }),
        }).then(function (data) {
          st.testId = data.test_id;
          self.summaryTestPoll();
        }).catch(function (e) {
          st.running = false;
          st.error = (e && e.message) ? e.message : 'Не удалось запустить проверку';
        });
      },
      summaryTestPoll: function () {
        var self = this;
        var st = this.summaryTest;
        if (!st.testId) { st.running = false; return; }
        this.api('/api/summary/test/' + st.testId + '?limit=200', { global: true })
          .then(function (data) {
            if (data && data.status === 'running') {
              setTimeout(function () { self.summaryTestPoll(); }, 1500);
              return;
            }
            st.result = data;
            st.running = false;
          }).catch(function (e) {
            st.running = false;
            st.error = (e && e.message) ? e.message : 'Не удалось получить результат';
          });
      },
      // Отдельное подтверждение обложки (§113/D3) — с предупреждением о расходе.
      summaryTestConfirmCover: function () {
        var self = this;
        var st = this.summaryTest;
        if (!st.testId || st.coverBusy) return;
        if (!window.confirm('Сгенерировать обложку для тестового прогона? '
            + 'Это отдельный вызов генерации изображения (расход).')) {
          return;
        }
        st.coverBusy = true;
        this.api('/api/summary/test/' + st.testId + '/cover', {
          method: 'POST', global: true,
          body: JSON.stringify({ confirm: true }),
        }).then(function (data) {
          st.coverBusy = false;
          st.cover = data;
          if (data && data.cover_status !== 'generated') {
            self.toast('Обложка не сгенерирована: '
              + ((data && data.cover_status) || ''), 'err');
          }
        }).catch(function (e) {
          st.coverBusy = false;
          self.toast('Ошибка обложки: ' + ((e && e.message) || ''), 'err');
        });
      },
      // §48: выбор промпта в дереве (desktop — центр; mobile — полный экран).
      openWorkspacePrompt: function (item, stage) {
        var ws = this.workspace;
        if (!ws || !item) return;
        var seg = stage || ws.stage || item.stage || '';
        // §48 (M-F5S-1): из двери библиотеки остаёмся в библиотеке —
        // `#/ai/prompts/<slug>[/<stage>]/<key>`. Нельзя строить
        // `#/modules/<slug>/<wt>/<key>` для модуля без объявленной
        // промпт-вкладки (напр. mod_summary/mod_sleep): `applyRoute`
        // редиректит такую вкладку на «Обзор» и редактор не открывается.
        if (ws.door === 'library') {
          var lib = '#/ai/prompts/' + ws.slug;
          if (seg && seg !== 'prompts') lib += '/' + seg;
          lib += '/' + encodeURIComponent(item.key);
          this.navigateTo(lib);
          return;
        }
        var wt = ws.tab || 'prompts';
        var next = '#/modules/' + ws.slug + '/' + wt;
        if (seg && seg !== wt) next += '/' + seg;
        next += '/' + encodeURIComponent(item.key);
        this.navigateTo(next);
      },
      // §48/§85: вторая дверь — тот же объект через библиотеку промптов.
      openPromptLibrary: function (m, stage) {
        if (!m) return;
        var slug = this.routeSlugOf(m);
        var next = '#/ai/prompts/' + slug;
        if (stage) next += '/' + stage;
        this.navigateTo(next);
      },
      // Группа промптов каталога, принадлежащая модулю (D3).
      _workspacePromptGroup: function (m) {
        if (!m) return null;
        var gid = MODULE_PROMPT_GROUPS[m.id];
        if (!gid) return null;
        var pt = (this.tabs || []).find(function (t) { return t.id === 'prompts'; });
        if (!pt) return null;
        var groups = this.groupedForTab(pt);
        for (var i = 0; i < groups.length; i++) {
          if (groups[i].id === gid) return groups[i];
        }
        return null;
      },
      workspacePromptItems: function (m, stage) {
        var grp = this._workspacePromptGroup(m);
        if (!grp) return [];
        if (stage) return this.promptStageItems(grp, stage);
        return grp.items || [];
      },
      // Раскладка вкладки модуля по workspace-вкладкам (settings/models/limits).
      // S1 round1026 (ADR-1026-1 D6): группы префильтра Саммари — на вкладке
      // «Подготовка сообщений» (§87: Модули → Сводки чатов → Подготовка
      // сообщений). Витрина JS — Δ каталога = 0.
      workspaceGroupTab: function (m, grp) {
        if (!grp) return 'settings';
        if (grp.id === 'flags_summary_filter'
            || grp.id === 'limits_summary_filter') return 'prep';
        if (grp.category === 'models') return 'models';
        if (grp.category === 'limits') return 'limits';
        return 'settings';
      },
      _workspaceGroupsFor: function (m, tabId) {
        if (!m) return [];
        var t = (this.tabs || []).find(function (x) { return x.id === m.tab; });
        if (!t) return [];
        var self = this;
        return this.groupedForTab(t).filter(function (g) {
          return self.workspaceGroupTab(m, g) === tabId;
        });
      },
      // Вкладка рендерится, только если у неё есть содержимое (§4.3 п.2).
      // Стадии Саммари §85 — честный placeholder (не декоративная пустышка).
      // `testing` (T-2700) — только при наличии тестируемых подключений.
      workspaceTabHasContent: function (m, tabId) {
        if (!m) return false;
        if (!_workspaceTabApplicable(m, tabId)) return false;
        if (tabId === 'overview') return true;
        if (tabId === 'prep' || tabId === 'clusterizer'
            || tabId === 'writer') return true;
        if (tabId === 'synthesizer' || tabId === 'verbalizer') {
          return this.workspacePromptItems(m, tabId).length > 0;
        }
        if (tabId === 'prompts') return this.workspacePromptItems(m).length > 0;
        if (tabId === 'models') {
          return this.workspaceModelGroups.length > 0
            || this._workspaceGroupsFor(m, 'models').length > 0;
        }
        if (tabId === 'limits') return this._workspaceGroupsFor(m, 'limits').length > 0;
        if (tabId === 'testing') {
          var tb = this.workspaceTestingBlocks;
          return !!(tb && tb.length > 0);
        }
        return this._workspaceGroupsFor(m, 'settings').length > 0;
      },
      // §84: карточки L1/L2 прямого чата из СУЩЕСТВУЮЩИХ стадий/ключей.
      directStageCards: function () {
        var self = this;
        function stageCard(id, title, promptKey, modelKey) {
          var prompt = (self.configItems || []).find(function (i) {
            return i.key === promptKey;
          }) || null;
          var model = (self.configItems || []).find(function (i) {
            return i.key === modelKey;
          }) || null;
          return {
            id: id, title: title, prompt: prompt, model: model,
            provider: self.blockFieldValue
              ? self.blockFieldValue({ key: 'models.llm_base_url' }) : '',
            modelName: model ? String(model.value == null ? '' : model.value) : '',
            source: model ? self.configSourceLabel(model) : '',
            checkable: true,
          };
        }
        return [
          stageCard('l1', 'L1 · Синтезатор',
                    'prompts.direct_chat_synthesizer_system_prompt',
                    'models.llm_model_name'),
          stageCard('l2', 'L2 · Вербализатор',
                    'prompts.direct_chat_verbalizer_system_prompt',
                    'models.llm_model_name'),
        ];
      },
      // §84: «Проверить» для L1/L2 — reuse существующего блока `direct`.
      testDirectStage: async function (card) {
        if (!card) return;
        var block = (this.providerBlocks || []).find(function (b) {
          return b.id === 'direct';
        });
        if (block) {
          await this.testBlock(block.subBlocks && block.subBlocks[0]
            ? block.subBlocks[0] : block);
        }
      },
      // F5 (§49/T-2714): карточка подключения — производная от существующей
      // структуры `PROVIDER_BLOCKS`; секреты не читаются.
      connectionCard: function (b) {
        return buildConnectionCard(this, b);
      },
      // T-2714: «Настроить» — раскрытие/скрытие существующей формы блока.
      // Само раскрытие НИЧЕГО не пишет (§49): сохранение — только `saveBlock`.
      toggleConnectionSettings: function (b) {
        if (!b || !b.id) return;
        this.connectionSettingsOpen[b.id] = !this.connectionSettingsOpen[b.id];
      },
      // T-2714: «Проверить» карточки — существующий `testBlock` (reuse
      // `/api/llm/test` / `/api/images/test`); новых API нет (R16).
      testConnection: async function (b) {
        if (!b) return;
        var card = buildConnectionCard(this, b);
        var target = (card && card.testTarget) ? card.testTarget : b;
        await this.testBlock(target);
      },
      // A4/T-1207: значение блока — черновик, иначе сохранённая строка.
      // 10.10 (п.3): `draft === ''` (явная очистка) ВОЗВРАЩАЕТ '' (не
      // откатывается к configItems); отсутствие черновика — реальное
      // значение из configItems (fallback), секреты → ''.
      // F9 (ADR-1025-22 D1): секрет-поле ВСЕГДА пустое без черновика —
      // маска/«Ключ установлен» — display-индикатор (`secretDisplay`), а не
      // значение `input` (§50/R17). Сырое значение даже при праве админа НЕ
      // подставляем: ввод — только новый ключ.
      blockFieldValue: function (f) {
        var draft = this.blockDrafts[f.key];
        if (draft != null) return draft;
        var it = this.configItems.find(function (i) { return i.key === f.key; });
        if (!it) return '';
        var isSecret = !!(f.secret || it.secret || it.category === 'keys');
        if (isSecret) return '';
        if (it.value && typeof it.value === 'object') return '';
        if (typeof it.value === 'string') return it.value;
        if (it.type !== 'bool' && it.value != null) return it.value;
        return '';
      },
      // 10.23 (F5): bool-поле блока (чекбокс GET-режима) — из черновика или
      // сохранённого значения configItems.
      blockFieldBool: function (f) {
        var draft = this.blockDrafts[f.key];
        if (draft != null) return (draft === true || draft === 'true'
                                   || draft === '1');
        var it = this.configItems.find(function (i) { return i.key === f.key; });
        if (!it) return false;
        return it.value === true || it.value === 'true' || it.value === 1;
      },
      // 10.23 (F5): поле зависит от другого bool-поля (GET-режим блокирует
      // ввод API-ключа). Значение зависимости — черновик или configItems.
      blockDependsOn: function (f) {
        if (!f || !f.dependsOn) return false;
        var draft = this.blockDrafts[f.dependsOn];
        if (draft != null) return (draft === true || draft === 'true'
                                   || draft === '1');
        var it = this.configItems.find(function (i) {
          return i.key === f.dependsOn;
        });
        if (!it) return false;
        return it.value === true || it.value === 'true' || it.value === 1;
      },
      // F11 (10.24, ADR-1024-12 D5): переключение bool-поля блока
      // (например, «Режим GET-запроса»). При включении зависимые СЕКРЕТЫ
      // очищаются (черновик ''), при выключении — черновик снимается, и поле
      // снова показывает маску из БД. Очистка ТОЛЬКО UI: ключ из БД не
      // удаляется (никакого DELETE — R4).
      setBlockBool: function (b, f, checked) {
        this.blockDrafts[f.key] = checked;
        var self = this;
        (b && b.fields ? b.fields : []).forEach(function (dep) {
          if (!dep.secret || dep.dependsOn !== f.key) return;
          if (checked) self.blockDrafts[dep.key] = '';
          else delete self.blockDrafts[dep.key];
        });
      },
      // Раунд 10.12 (ADR-1012-1 §2.3): маленькая надпись у header каждого
      // подключения = значение первого поля с role === '' («Название модели»).
      // Пусто → прежний текст модуля (x.modules), не пусто/не хардкод.
      blockDisplayName: function (x) {
        if (!x) return '';
        var fields = x.fields || [];
        var nameField = null;
        var value = '';
        for (var i = 0; i < fields.length; i++) {
          // display-поле = «Название модели» (role '' + *_display_name).
          // У technical-блоков (advanced) display-поля нет → x.modules.
          if (fields[i].role === ''
              && String(fields[i].key || '').indexOf('display_name') >= 0) {
            nameField = fields[i];
            break;
          }
        }
        if (nameField) {
          var v = this.blockFieldValue(nameField);
          if (typeof v === 'string' && v.trim()) value = v.trim();
        }
        if (!value) value = x.modules || '';
        // Parent-блоки, где modules == title (direct/transcription/video),
        // не дублируют заголовок (Scanner LOW, раунд 10.12).
        if (value && value === x.title) return '';
        return value;
      },
      blockFieldPlaceholder: function (f) {
        var it = this.configItems.find(function (i) { return i.key === f.key; });
        // F9 (ADR-1025-22 D1): секрет-поле — всегда пустое; подсказка говорит,
        // что делать (заменить), а не показывает маску как значение.
        if (it && (f.secret || it.secret || it.category === 'keys')) {
          var configured = !!(it.value && typeof it.value === 'object'
                              && it.value.configured);
          return configured ? 'Новый ключ (заменить)…' : 'Ключ…';
        }
        return f.label;
      },
      // 10.11 (ADR-1011-1): R17-безопасный индикатор «ключ уже сохранён»
      // (configItems отдаёт только {configured,last4}, без сырого секрета).
      blockFieldConfigured: function (f) {
        var it = this.configItems.find(function (i) { return i.key === f.key; });
        return !!(it && typeof it.value === 'object' && it.value
                  && it.value.configured);
      },
      last4ByKey: function (key) {
        var it = this.configItems.find(function (i) { return i.key === key; });
        if (it && it.value && typeof it.value === 'object') {
          return it.value.last4 || '';
        }
        return '';
      },
      // F9 (ADR-1025-22 D1/D3): display-строка секрет-поля БЛОКА —
      // `••••••••last4` / «Ключ установлен» / «Не настроен». Не значение input.
      testBlock: async function (b) {
        if (!b || this.blockTesting[b.id]) return;
        this.blockTesting[b.id] = true;
        var self = this;
        try {
          // 10.24 (F12, ADR-1024-4 D3): «Проверить подключение» в карточке
          // изображений — бэкенд шлёт реальный тестовый промпт и возвращает
          // ProbeResult; тост показывает успех или СЫРОЙ безопасный текст
          // ошибки провайдера (R17: без ключа).
          if (b.probeEndpoint) {
            var probe = await this.api(b.probeEndpoint, {
              method: 'POST', body: JSON.stringify({ prompt: '' }),
            });
            var ok = !!(probe && probe.ok);
            var info = ok
              ? ('OK ' + (probe.status_code != null ? probe.status_code : '')
                 + ' · ' + (probe.latency_ms || 0) + ' мс'
                 + (probe.model ? (' · ' + probe.model) : ''))
              : ((probe && (probe.body_excerpt || probe.reason)) || 'ошибка');
            this.blockResults[b.id] = { ok: ok, text: info };
            this.toast(ok ? ('Подключение OK: ' + info)
                          : ('Ошибка подключения: ' + info),
                       ok ? 'ok' : 'err');
            return;
          }
          var body = { block: b.id, base_url: '', model: '', api_key: '' };
          b.fields.forEach(function (f) {
            var v = self.blockFieldValue(f);
            if (f.role === 'base_url') body.base_url = v || body.base_url;
            else if (f.role === 'model') body.model = v || body.model;
            // UPD3-fix/R31: маску и её композит в пробу не шлём (бэкенд
            // резолвит сохранённый ключ по block).
            else if (f.role === 'api_key' && v && !hasSecretMask(v)) body.api_key = v;
          });
          var res = await this.api('/api/llm/test', {
            method: 'POST', body: JSON.stringify(body),
          });
          this.blockResults[b.id] = {
            ok: !!res.ok,
            text: res.ok
              ? ('OK ' + (res.http_status || '') + ' · ' + (res.latency_ms || 0) + ' мс')
              : (res.error || 'ошибка'),
          };
        } catch (e) {
          // F12 (10.24): серверный detail различается (llm/test 5с, images/test
          // 10с) — показываем его как есть, без хардкода интервала.
          var msg = (e && e.message) || 'ошибка';
          this.blockResults[b.id] = { ok: false, text: msg };
        } finally {
          this.blockTesting[b.id] = false;
        }
      },
      // MINOR-2: тест КОНКРЕТНОГО ключа блока (search_keys:tavily/exa).
      testField: async function (b, f) {
        if (!b || !f || !f.probeTarget || this.blockTesting[f.probeTarget]) return;
        var target = f.probeTarget;
        this.blockTesting[target] = true;
        try {
          var res = await this.api('/api/llm/test', {
            method: 'POST',
            body: JSON.stringify({
              block: target, base_url: '', model: '',
              // UPD3/R31: маску/композит в пробу не шлём — бэкенд резолвит
              // сохранённый ключ.
              api_key: hasSecretMask(this.blockFieldValue(f))
                ? '' : this.blockFieldValue(f),
            }),
          });
          this.blockResults[target] = {
            ok: !!res.ok,
            text: res.ok
              ? ('OK ' + (res.http_status || '') + ' · ' + (res.latency_ms || 0) + ' мс')
              : (res.error || 'ошибка'),
          };
        } catch (e) {
          var msg = (e && e.status === 429) ? 'Слишком часто — подождите 5 секунд'
            : ((e && e.message) || 'ошибка');
          this.blockResults[target] = { ok: false, text: msg };
        } finally {
          this.blockTesting[target] = false;
        }
      },
      // MODERATE-1: сохранение полей блока через /api/config (без потери
      // черновика). Секреты пишутся только если введён новый ключ.
      // F11 (10.24, ADR-1024-12 D4): секреты ВЫНЕСЕНЫ из общего POST —
      // идут через saveProviderSecret (image → safe-эндпоинт global).
      saveBlock: async function (b) {
        if (!b || this.blockSaving[b.id]) return;
        var self = this;
        var items = [];
        var secrets = [];
        b.fields.forEach(function (f) {
          var it = self.configItems.find(function (i) { return i.key === f.key; });
          var draft = self.blockDrafts[f.key];
          if (f.secret) {
            // UPD3-fix/R31: маска-сентинел И её композит (`маска+ввод`) НЕ
            // отправляем — иначе перезапишем реальный секрет «остатком» ввода.
            // F11: собранный секрет уходит отдельным безопасным запросом.
            if (draft && !hasSecretMask(draft)) {
              secrets.push({ key: f.key, value: draft });
            }
            return;
          }
          // MINOR-3: `draft == null` = «не трогать»; `''` (пусто) = очистить.
          if (draft == null) return;
          var perChat = it ? it.per_chat : undefined;
          if (draft === '') { items.push({ key: f.key, value: '',
                                           per_chat: perChat }); return; }
          var v = draft;
          if (it && it.type === 'int') v = parseInt(v, 10);
          else if (it && it.type === 'float') v = parseFloat(v, 10);
          else if (it && it.type === 'bool') v = !!v;
          if (typeof v === 'number' && !isFinite(v)) {
            self.toast('Некорректное значение: ' + f.key, 'err');
            return;
          }
          items.push({ key: f.key, value: v, per_chat: perChat });
        });
        if (!items.length && !secrets.length) {
          this.toast('Нет изменений', 'warn');
          return;
        }
        this.blockSaving[b.id] = true;
        var persistResult = null;
        try {
          // F11: секреты — ТОЛЬКО безопасным путём (по одному), никогда в
          // теле общего запроса. Никакой `keys.*` в items не попадает.
          for (var si = 0; si < secrets.length; si++) {
            await this.saveProviderSecret(secrets[si].key, secrets[si].value,
                                          { scope: 'global' });
          }
          if (items.length) {
            if (typeof this.persistItems === 'function') {
              // F0.1 (ADR-1025-2 D2): единый write-path — persistItems сам
              // делает scope-split и guard in-flight; итог решаем ниже по
              // РЕАЛЬНОМУ результату (H-1: частичный провал/in-flight ≠ успех).
              persistResult = await this.persistItems(items, { silent: true });
            } else {
              // Легаси-контекст без единого write-path (юнит-тесты): прежний
              // прямой POST с scope-split по configItems.
              function isGlobalKey(k) {
                var spec = self.configItems.find(function (i) {
                  return i.key === k;
                });
                return !!(spec && spec.per_chat === false);
              }
              var globalItems = items.filter(function (i) {
                return isGlobalKey(i.key);
              });
              var chatItems = items.filter(function (i) {
                return !isGlobalKey(i.key);
              });
              if (globalItems.length && chatItems.length) {
                await this.api('/api/config', {
                  method: 'POST',
                  body: JSON.stringify({ items: chatItems,
                                         updated_at: this.configChatUpdatedAt }),
                });
                await this.api('/api/config', {
                  method: 'POST',
                  body: JSON.stringify({ items: globalItems }),
                  global: true,
                });
              } else {
                var allGlobal = globalItems.length > 0;
                await this.api('/api/config', {
                  method: 'POST',
                  body: JSON.stringify({
                    items: items,
                    updated_at: allGlobal ? null : this.configChatUpdatedAt,
                  }),
                  global: allGlobal,
                });
              }
            }
          }
          if (persistResult) {
            // H-1 (ревью): успех ТОЛЬКО если всё сохранено и ничего не
            // пропущено in-flight; иначе честный warn/err с перечнем.
            var failedKeys = (persistResult.failed || []).map(function (f) {
              return f.key;
            });
            var skippedKeys = persistResult.skipped || [];
            var allOk = (persistResult.state === 'saved'
                         && !failedKeys.length && !skippedKeys.length);
            if (allOk) {
              this.toast('Сохранено: ' + b.title, 'ok');
              await this._preserveScroll(this.loadConfig);
            } else {
              var badKeys = failedKeys.concat(skippedKeys);
              var names = badKeys.map(function (k) {
                var fi = (typeof self._findConfigItem === 'function')
                  ? self._findConfigItem(k) : null;
                return (fi && fi.title) || k;
              }).join(', ');
              var savedN = (persistResult.saved || []).length;
              this.toast('Сохранено ' + savedN + ' из ' + items.length
                         + '; не сохранено: ' + (names || '—'),
                         savedN ? 'warn' : 'err');
              await this._preserveScroll(this.loadConfig);
            }
          } else {
            this.toast('Сохранено: ' + b.title, 'ok');
            await this._preserveScroll(this.loadConfig);
          }
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.toast('Конфликт версии (409) — конфигурация обновлена', 'warn');
            this._preserveScroll(this.loadConfig);
          } else {
            this.toast('Ошибка сохранения: ' + (e.message || e), 'err');
          }
        } finally {
          this.blockSaving[b.id] = false;
        }
      },
      // T-1100: карточка hub → дочерний экран (+якорь секции для access).
      openHubCard: function (card) {
        var self = this;
        if (!card) return;
        // F6 (L-F6S-5): presentation-подгруппа «Память → Настройки» не должна
        // «залипать» между входами — при открытии карточки хаба сбрасываем её
        // (мёртвый шов memorySubgroup у карточек удалён).
        this.memorySubgroup = '';
        this.navigateTo(card.route);
        if (card.section) {
          this.$nextTick(function () { self.scrollToId(card.section); });
        }
      },
      scrollToId: function (id) {
        try {
          var el = document.getElementById(id);
          if (el && el.scrollIntoView) {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        } catch (e) { /* no DOM */ }
      },

      // ═══ T-1127 (§15.1.3): кастомный scope-dropdown (a11y listbox) ═══
      toggleScope: function () {
        this.scopeOpen = !this.scopeOpen;
        if (this.scopeOpen) {
          this.scopeSearch = '';
          this.scopeFocus = 0;
          this.ensureScopeAvatars();
          this.positionScopePanel();
        } else {
          this.scopeFocus = -1;
        }
      },

      // F6 round 10.21 (T-1993/L-4): не даём панели уехать за край вьюпорта.
      // По умолчанию `.scope-panel` — right:0 от триггера. Если при этом её
      // левый край уходит за экран (короткий заголовок вкладки) — якорим
      // панель к ЛЕВОМУ краю триггера и ограничиваем ширину; если упирается
      // в правый край (узкий вьюпорт) — оставляем right:0 с ограничением.
      positionScopePanel: function () {
        var self = this;
        // Сброс прошлой коррекции: меряем дефолтную позицию (right:0), а не
        // inline-стиль, оставшийся от предыдущего открытия.
        self.scopePanelStyle = {};
        this.$nextTick(function () {
          var panel = document.querySelector('.scope-panel');
          if (!panel || !self.scopeOpen) return;
          var wrap = panel.closest('.scope-wrap') || panel.parentElement;
          var vw = document.documentElement.clientWidth;
          var pad = 8;
          var pr = panel.getBoundingClientRect();
          var wr = wrap ? wrap.getBoundingClientRect() : pr;
          if (pr.left < pad) {
            self.scopePanelStyle = {
              left: '0', right: 'auto',
              maxWidth: Math.max(160, Math.round(vw - wr.left - pad)) + 'px',
            };
          } else if (pr.right > vw - pad) {
            self.scopePanelStyle = {
              left: 'auto', right: '0',
              maxWidth: Math.max(160, Math.round(wr.right - pad)) + 'px',
            };
          } else {
            self.scopePanelStyle = {};
          }
        });
      },
      closeScope: function () {
        this.scopeOpen = false;
        this.scopeFocus = -1;
      },
      // M2: стрелки/Enter по listbox (фокус-менеджмент).
      scopeMove: function (delta) {
        if (!this.scopeOpen) { this.toggleScope(); return; }
        var n = this.scopeOptions.length;
        if (!n) return;
        this.scopeFocus = (this.scopeFocus + delta + n) % n;
      },
      scopePickFocused: function () {
        if (this.scopeOpen && this.scopeFocus >= 0) {
          var o = this.scopeOptions[this.scopeFocus];
          if (o) this.pickScope(o);
        } else {
          this.toggleScope();
        }
      },
      pickScope: function (o) {
        this.scopeOpen = false;
        this.setActiveChat(o && o.chat_id != null ? String(o.chat_id) : '');
      },
      isScopeSelected: function (o) {
        if (!o) return false;
        if (o.kind === 'global') return this.activeChatId == null;
        return o.chat_id === this.activeChatId;
      },
      // Ленивая догрузка аватаров чатов (R10.4-4): только при открытии.
      ensureScopeAvatars: function () {
        var self = this;
        this.accessChats.forEach(function (c) {
          if (c.photo_file_id != null && !c.avatarUrl && !c.__avBusy) {
            c.__avBusy = true;
            self.loadAvatar('chat', c.chat_id, c);
          }
        });
      },
      // Определённый родитель (§6.4.4), БЕЗ history.back().
      goBack: function () {
        // A2/T-1167: при открытом окне модуля back СНАЧАЛА закрывает окно
        // (роут не меняется — важно для Android).
        if (this.openModuleId != null) { this.closeModule(); return; }
        var p = routeParent(this.route);
        if (p) this.navigateTo(p);
      },
      // Bot API 6.1+ guard: BackButton может отсутствовать вне TMA.
      // R10.5-1: вызывается и на BOOT, и на late-`ready` (контекст может
      // появиться позже). onClick привязывается РОВНО ОДИН раз на объект
      // (_boundBackApi), затем syncBackButton() переоценивает видимость.
      initBackButton: function () {
        var self = this;
        var wa = window.Telegram && window.Telegram.WebApp;
        var bb = wa && wa.BackButton;
        _backApi = (bb && typeof bb.show === 'function'
          && typeof bb.hide === 'function') ? bb : null;
        this.backNative = !!_backApi;
        if (_backApi && typeof _backApi.onClick === 'function'
            && _boundBackApi !== _backApi) {
          _backApi.onClick(function () { self.goBack(); });
          _boundBackApi = _backApi;
        }
        // late-ready: переоценить видимость (show() при depth>0).
        if (_backApi) this.syncBackButton();
      },
      // ЕДИНСТВЕННОЕ место смены видимости; show() заменяет нативный ✕ на ←.
      syncBackButton: function () {
        if (!_backApi) return;
        var want = window.__TMA_BACK__ !== false && routeDepth(this.route) > 0;
        if (want === !!_backApi.isVisible) return;
        try { want ? _backApi.show() : _backApi.hide(); } catch (e) { /* old SDK */ }
      },

      // ═══ Material Symbols (T-1147): рендер PUA-кодпоинтом ═══
      iconGlyph: function (name) {
        return ICONS[name] || '';
      },
      tabMat: function (id) {
        var name = TAB_ICON[id];
        return (name && ICONS[name]) ? ICONS[name] : '';
      },

      setTab: function (id) {
        var self = this;
        // F5 (10.24, ADR-1024-9 review iter1): kill-switch вкладки — при
        // IMAGE_MODULE_CARD_ENABLED=OFF уйти на `mod_images` нельзя ни одним
        // путём (карточка скрыта, диплинк `#/modules/images` откатывается);
        // попытка активации → витрина «Модули».
        if (id === 'mod_images' && this._flagTabHidden
            && this._flagTabHidden('mod_images')) {
          id = 'modules';
        }
        // R10.7-3: смена вкладки отменяет отложенный сброс подсветки
        // скопированной строки лога (иначе таймер 800 мс «протекает»).
        if (this.copiedTimer) clearTimeout(this.copiedTimer);
        this.copiedTimer = null;
        this.copiedIndex = null;
        var prevTab = this.activeTab;
        this.activeTab = id;
        // Ревью-фикс раунда (кросс-чатовая запись отношений): уход с
        // «Лора чатов» сбрасывает лор-профиль и список участников —
        // вкладка relations работает ТОЛЬКО от активного чата.
        if (prevTab === 'chat_lore' && id !== 'chat_lore') {
          this.chatLoreProfile = null;
          this.chatRelations = [];
        }
        // F-11: синхрон активной меню-секции удалён вместе с боковой панелью (A1).
        if (id === 'modules' && this.canViewTab('modules')
            && !this.gateInfo && !this.modulesBusy) {
          this.loadModules();
        }
        // BUG-3 (permsoc): мастер-карта читает те же гейты — подгружаем
        // при первом показе вкладки (per chat; без чата — hint-заметка).
        if ((id === 'modules' || id === 'permsoc')
            && this.canViewTab(id) && !this.gateInfo && !this.modulesBusy
            && this.activeChatId != null) {
          this.loadGateInfo();
        }
        // 84.24-ревью: поиск не переносится между вкладками
        if (this.configSearch) this.configSearch = '';
        // 3.5.1 (UX): скролл контента в начало при переключении вкладки.
        // HOTFIX9 D2 (T-2804, ADR-1025-17): в TMA/mobile/fullscreen скроллится
        // не document, а `main.scroll-area` (flex-колонка) — сбрасываем оба,
        // чтобы новый основной раздел открывался с начала страницы.
        this.$nextTick(function () {
          var sc = document.scrollingElement || document.documentElement;
          if (sc) sc.scrollTop = 0;
          if (typeof document.querySelector === 'function') {
            var area = document.querySelector('.app-shell .scroll-area');
            if (area) area.scrollTop = 0;
          }
        });
        if (id === 'status') {
          this.loadStatus();
          this.loadLogs();
          this.startStatusPolling();
          this.loadCognition();          // F5/§5: блок «Осмысление»
          this.startCognitionPolling();  // F5-Q3: polling 15с
        } else {
          this.stopStatusPolling();
          this.stopCognitionPolling();   // F5-Q3: вне «Статуса» — стоп
          this.destroyCognitionGraph();  // R10.11-5: нет stale-инстанса
        }
        if (id === 'oversight') {
          this.loadMemoryWidget();       // F5/§7: виджет «Сводка»
          this.loadPersonaHealth();      // F4/UPD п.4: метрики Личности
          // 10.20 (T-1897): «Живая лента досье» (guard — unit-стабы setTab).
          if (typeof this.startDossierFeedPolling === 'function') {
            this.startDossierFeedPolling();
          }
        } else if (typeof this.stopDossierFeedPolling === 'function') {
          this.stopDossierFeedPolling();    // вне «Сводки» — без polling
        }
        if (id === 'info') {
          if (!this.infoHtml && !this.infoLoading) this.loadInfo();
          // F6 (10.14): второй блок «Справки» — гайд грузится вместе с первым.
          if (!this.guideHtml && !this.guideLoading) this.loadGuide();
        }
        // F3 (10.14): «Личность» — special-screen, всегда перечитываем свой
        // скоуп при входе (черновик мог быть от прошлого чата).
        if (id === 'persona' && !this.personaLoading) {
          this.loadPersona();
        }
        if (id === 'access' && this.canViewTab('access')) {
          this.loadAdmins();
          this.loadRoles();
          if (this.isGlobalAdmin) this.loadMatrix();   // T-1130
        }
        // 3.10: «Лор чатов» — при первом показе грузим список чатов (для
        // ролей с секцией; per-chat админы уже прошли probe в mounted).
        if (id === 'chat_lore' && this.hasPerm('section.chat_lore')
            && !this.chatLoreChats.length && !this.chatLoreLoading) {
          this.loadChats();
        }
        // Ревью-фикс раунда: «Участники и отношения» — автозагрузка
        // участников активного чата при переходе (кнопка ⟳ остаётся;
        // листать вручную не нужно). В ЛС — заглушка (сервер 404).
        if (id === 'relations' && this.canViewTab('relations')
            && this.activeChatId != null && !this.isDmCtx()
            && !this.relationsBusy) {
          this.loadRelations(this.activeChatId);
        }
        // MAJOR-2: Сон/Ностальгия — панели в модалке модуля; их данные
        // грузятся в openModuleWindow/_ensureModuleData (не по activeTab).
        // 3.5.1: конфиг-вкладки (generic-рендер) — данные общие для всех;
        // первый показ любой из них грузит /api/config целиком.
        var tab = this.currentTab;
        if (tab && (tab.type === 'config' || tab.type === 'modules')
            && !this.configItems.length) {
          self.loadConfig();
        }
      },

      // ═══ TMA-кнопки шапки (UI-полировка) ═══
      // F-13 (AC-2): метод принудительного закрытия миниаппа удалён
      // вместе с крестиком ✕ выхода — закрытие в Telegram штатное
      // (свайп/системная кнопка); остаются ⛶ и мобильный ✕ сайдбара.
      // F24 (ADR-1024-24 D1, AMEND решения 10.10): ⛶ — user-action
      // (`requestFullscreen`/`exitFullscreen`). Флаг НЕ «угадывается»: если
      // SDK отдаёт фактический boolean `isFullscreen` — берём его, НО не
      // синхронно (свойство обновляется асинхронно после transition; review
      // iter1): основной путь — события fullscreenChanged/viewportChanged,
      // плюс отложенный re-read (microtask + rAF). Иначе (старый SDK/вне TG)
      // — legacy-инверсия локального флага.
      toggleFullscreen: function () {
        try {
          var wa = window.Telegram && Telegram.WebApp;
          if (!wa) return;
          // D5/T-2607: не полагаемся на единственное имя метода — Telegram SDK
          // отдаёт `requestFullscreen`/`exitFullscreen` (Bot API 8.0), но в
          // старых/нишевых клиентах встречаются камел-варианты. Fallback —
          // ближайший доступный (без «мёртвой» кнопки).
          if (this.isFullscreen) {
            if (typeof wa.exitFullscreen === 'function') wa.exitFullscreen();
            else if (typeof wa.expand === 'function') wa.expand();
          } else {
            if (typeof wa.requestFullscreen === 'function') wa.requestFullscreen();
            else if (typeof wa.requestFullScreen === 'function') wa.requestFullScreen();
            else if (typeof wa.expand === 'function') wa.expand();
          }
          if (typeof wa.isFullscreen !== 'boolean') {
            this.isFullscreen = !this.isFullscreen;   // legacy-фолбэк
            return;
          }
          var self = this;
          var reread = function () { self.setFullscreenFromTma(); };
          try { Promise.resolve().then(reread); } catch (e1) { /* нет Promise */ }
          try {
            if (window.requestAnimationFrame) window.requestAnimationFrame(reread);
          } catch (e2) { /* нет rAF */ }
        } catch (e) { /* вне TG/старый SDK — молча */ }
      },

      // F24 (ADR-1024-24 C3): источник истины — TMA. Инициализируем флаг из
      // `Telegram.WebApp.isFullscreen` и подписываемся на события (ровно раз —
      // guard `_fsSubscribed`). Вызывается из mounted() и из `ready`
      // (контекст Telegram может появиться позже). Вне TG/без методов — no-op.
      initFullscreen: function () {
        if (_fsSubscribed) { this.setFullscreenFromTma(); return; }
        try {
          var wa = window.Telegram && Telegram.WebApp;
          if (!wa) return;
          if (typeof wa.isFullscreen === 'boolean') {
            this.isFullscreen = wa.isFullscreen;
          }
          if (typeof wa.onEvent !== 'function') return;
          var self = this;
          _fsOnFullscreen = function () { self.setFullscreenFromTma(); };
          _fsOnViewport = function () { self.setFullscreenFromTma(); };
          wa.onEvent('fullscreenChanged', _fsOnFullscreen);
          wa.onEvent('viewportChanged', _fsOnViewport);
          _fsSubscribed = true;
        } catch (e) {
          // review iter1: исключение на втором onEvent не должно оставлять
          // «бесхозную» подписку — best-effort снимаем уже зарегистрированный
          // первый листенер и сбрасываем guard/ссылки, чтобы повторный
          // initFullscreen() поднял состояние с чистого листа.
          try {
            var w = window.Telegram && Telegram.WebApp;
            if (w && typeof w.offEvent === 'function' && _fsOnFullscreen) {
              w.offEvent('fullscreenChanged', _fsOnFullscreen);
            }
          } catch (e1) { /* no-op */ }
          _fsOnFullscreen = null;
          _fsOnViewport = null;
          _fsSubscribed = false;
        }
      },

      // F24 (C3): локальный флаг — производный от фактического TMA. Если SDK
      // не отдаёт boolean `isFullscreen` — НЕ угадываем (no-op).
      setFullscreenFromTma: function () {
        try {
          var wa = window.Telegram && Telegram.WebApp;
          if (wa && typeof wa.isFullscreen === 'boolean') {
            this.isFullscreen = wa.isFullscreen;
          }
        } catch (e) { /* no-op */ }
        // HOTFIX9 D7 (T-2832): после смены fullscreen даём Vue перерисовать
        // разметку и перерисовываем canvas по новому размеру (иначе в fullscreen
        // сердебиение могло «исчезнуть»). Дизайн/данные не затрагиваются.
        var self = this;
        var redraw = function () {
          if (typeof self._hbResize === 'function') self._hbResize();
          // HOTFIX10 (ADR-1025-18 D5, T-2857): после входа/выхода из fullscreen
          // пересчитываем фон по новому размеру контейнера (не оставляем старые
          // drawing buffer/viewport/uniforms).
          _auroraResize();
        };
        if (typeof this.$nextTick === 'function') {
          this.$nextTick(redraw);
        } else {
          redraw();
        }
        // Страховка: layout/viewport Telegram может «доехать» после transition.
        try {
          if (window.requestAnimationFrame) window.requestAnimationFrame(redraw);
        } catch (e3) { /* no-op */ }
      },

      // F24 (C3/C4): отписки в beforeUnmount — `offEvent` с ТЕМИ ЖЕ fn-ссылками
      // (паттерн `_onVisibility`). Повторный вызов безопасен.
      teardownFullscreen: function () {
        try {
          var wa = window.Telegram && Telegram.WebApp;
          if (wa && typeof wa.offEvent === 'function') {
            if (_fsOnFullscreen) wa.offEvent('fullscreenChanged', _fsOnFullscreen);
            if (_fsOnViewport) wa.offEvent('viewportChanged', _fsOnViewport);
          }
        } catch (e) { /* no-op */ }
        _fsOnFullscreen = null;
        _fsOnViewport = null;
        _fsSubscribed = false;
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
        // F3 (10.14): «Личность» — special-screen (НЕ config-вкладка TABS;
        // инвариант «TABS — зеркало TAB_RULES» не трогаем). Глобальный admin
        // видит всегда; chat-скоуп — при праве edit_persona/content (F2 §5).
        // R10.14-1: роль с edit_persona читает/правит и global (без
        // выбранного чата) — глобальный экран достижим (GET global 200).
        if (tabId === 'persona') {
          if (this.isGlobalAdmin) return true;
          if (this.hasPerm('edit_persona')) return true;
          if (this.activeChatId == null) return false;
          return this.hasPerm('section.content')
            || this.isLocalAdminCtx();
        }
        var tab = this.tabs.find(function (t) { return t.id === tabId; });
        if (!tab) return false;
        if (tab.always) return true;
        // F-14 (§6.2): DM-скоуп (свои ЛС) — конфиг-вкладки открыты
        // (Провайдеры read-only/BYOK, Промпты, Лимиты, Память-RAG,
        // Реакции-Триггеры); permsoc скрыт (групповые перс-модули).
        if (this.isDmCtx() && tab.type === 'config' && tab.id !== 'permsoc') {
          return true;
        }
        var p = this.permissions;
        if (p.wildcard) return true;
        // 3.10 (Q6): «Лор чатов» — секция chat_lore ИЛИ непустой
        // probe-список (per-chat админы без секции; пустой НЕ показываем).
        if (tab.type === 'chat_lore') {
          return this.hasPerm('section.chat_lore') || this.chatLoreChats.length > 0;
        }
        // Раунд 10.4 (F-2/F-3): «Участники и отношения» — видимость как у
        // chat_lore (секция chat_lore / probe; НОВЫХ RBAC-секций нет);
        // в DM-скоупе — видна (конфиг-часть правится, участники — заглушка
        // по 404 сервера, F-4).
        if (tab.type === 'relations') {
          if (this.isDmCtx()) return true;
          return this.hasPerm('section.chat_lore') || this.chatLoreChats.length > 0;
        }
        // Раунд 10 (F-11 Q1 / F-12): Oversight — только global admin;
        // «Модули» — реакции/флаги секции либо локальный админ чата.
        if (tab.type === 'oversight') {
          return this.isGlobalAdmin;
        }
        if (tab.type === 'modules') {
          return this.hasPerm('section.reactions')
            || this.hasPerm('section.flags')
            || this.hasPerm('section.chat_lore')
            || this.isGlobalAdmin || this.isLocalAdminCtx();
        }
        var sections = arr(p.sections), params = arr(p.params), keys = arr(p.keys);
        var cats = tabCategories(tab);
        for (var i = 0; i < cats.length; i++) {
          var cat = cats[i];
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

      // Раунд 10 (F-11 Q1): локальный админ/мод-грант активного чата
      isLocalAdminCtx: function () {
        return !!(this.accessMy && this.accessMy.is_local_admin);
      },

      // F-11 (4.2) / F24 (ADR-1024-24 D2/C1): раскрытие аккордеона — чтение
      // РЕАКТИВНОГО `this.expand` (единственный источник рендера `:open`).
      // Сигнатура сохранена для JS-юнитов 10.11; localStorage — только персист
      // (перенос в реактив закрывает дефект «advanced пропадает в fullscreen»).
      expandOpen: function (tabId, scope) {
        return !!this.expand[_expandKey(tabId, scope)];
      },

      // F24 (ADR-1024-24 D3/C2): синхронизация с фактом DOM, а НЕ инверсия.
      // `@toggle` срабатывает и при программной установке `open` из Vue — при
      // общих bare-ключах (несколько `details` на одной вкладке) инверсия дала
      // бы осцилляцию (открыли A → Vue открыл B → toggle B инвертировал ключ →
      // закрылись оба). `ev.target.open` идемпотентен. Без события (legacy/юниты
      // без $event) — прежняя инверсия. Пишем в реактивный стейт И в localStorage.
      toggleExpand: function (tabId, scope, ev) {
        var k = _expandKey(tabId, scope);
        var next;
        if (ev && ev.target && typeof ev.target.open === 'boolean') {
          next = ev.target.open;
        } else {
          next = !this.expand[k];
        }
        this.expand[k] = next;
        try { localStorage.setItem(k, next ? '1' : ''); } catch (e) { /* quota */ }
      },

      // F24 (ADR-1024-24 D2/C1): однократная инициализация реактивного стейта
      // аккордеонов из localStorage (скан по префиксу `adminbot.expand:`;
      // значение `'1'` → раскрыто). Вызывается в created() ДО первого рендера.
      // Приватный режим/недоступность localStorage → стейт пустой («свёрнуто»),
      // без исключений. Ключи `_expandKey` не меняются (обратная совместимость).
      initExpandState: function () {
        try {
          var n = localStorage.length || 0;
          for (var i = 0; i < n; i++) {
            var k = localStorage.key(i);
            if (!k || k.indexOf('adminbot.expand:') !== 0) continue;
            if (localStorage.getItem(k) === '1') this.expand[k] = true;
          }
        } catch (e) { /* приватный режим — «свёрнуто» */ }
      },
      itemAdvanced: function (item) {
        return item && item.progressive_level === 'advanced';
      },
      // Hotfix-R10 (пустые вкладки Промпты/Лимиты/LLM/Память/Реакции/Доступы):
      // шаблон звал basicItems/advancedItems — методов не было → TypeError в
      // рендере → Vue удалял всю конфиг-ветку (вкладки пустые). Методы —
      // зеркало itemAdvanced (Базовые = НЕ advanced, Расширенные = advanced).
      // Hotfix-R10: isAdminIdHidden фильтруется ЗДЕСЬ — v-if вместе с v-for
      // на одном элементе в Vue 3 не работал (item вне области v-if).
      basicItems: function (grp) {
        var self = this;
        if (!grp || !grp.items) return [];
        return grp.items.filter(function (i) {
          return !self.itemAdvanced(i) && !self.isAdminIdHidden(i);
        });
      },
      advancedItems: function (grp) {
        var self = this;
        if (!grp || !grp.items) return [];
        return grp.items.filter(function (i) {
          return self.itemAdvanced(i) && !self.isAdminIdHidden(i);
        });
      },

      // ═══ Раунд 10.23 (F8, ADR-1023-8): вкладка «Промпты» ═══════════════
      // Клиентская группировка элементов карточки модуля по полю `stage`
      // (synthesizer/verbalizer/mode/None) — секции «Синтезатор (Логика)» /
      // «Вербализатор (Характер)». GROUPS/TAB_RULES не затронуты.
      promptStageItems: function (grp, stage) {
        if (!grp || !grp.items) return [];
        return grp.items.filter(function (i) { return i.stage === stage; });
      },
      promptOtherItems: function (grp) {
        if (!grp || !grp.items) return [];
        return grp.items.filter(function (i) { return !i.stage; });
      },
      promptsHasSynthesizer: function (grp) {
        return this.promptStageItems(grp, 'synthesizer').length > 0;
      },
      promptsHasVerbalizer: function (grp) {
        return this.promptStageItems(grp, 'verbalizer').length > 0;
      },
      // F8 (review iter1): секции карточки модуля для вкладки «Промпты».
      // Пустые секции НЕ рендерятся (группы без staged-элементов —
      // prompts_memory/prompts_checkup — дают только «Прочие промпты»).
      // Внутри секции items разбиты на basic/advanced (дисклоузер).
      promptSections: function (grp) {
        var self = this;
        function split(items) {
          var basic = [], advanced = [];
          items.forEach(function (it) {
            if (self.itemAdvanced(it)) advanced.push(it); else basic.push(it);
          });
          return { basic: basic, advanced: advanced };
        }
        var sections = [];
        var synth = this.promptStageItems(grp, 'synthesizer');
        var verb = this.promptStageItems(grp, 'verbalizer');
        var other = this.promptOtherItems(grp);
        if (synth.length) {
          sections.push(Object.assign(
            { id: 'synthesizer', title: 'Синтезатор (Логика)', note: '' },
            split(synth)));
        }
        if (verb.length) {
          sections.push(Object.assign(
            { id: 'verbalizer', title: 'Вербализатор (Характер)',
              note: synth.length ? ''
                : 'Модуль одностадийный — только Вербализатор.' },
            split(verb)));
        }
        if (other.length) {
          sections.push(Object.assign(
            { id: 'other', title: 'Прочие промпты модуля', note: '' },
            split(other)));
        }
        return sections;
      },
      promptItemByKey: function (grp, key) {
        var items = (grp && grp.items) || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i].key === key) return items[i];
        }
        return null;
      },
      promptModeItem: function (mode) {
        var m = mode || this.promptMode;
        return (this.configItems || []).find(function (i) {
          return i.key === 'prompts.verbilizer_mode_' + m;
        }) || null;
      },
      promptDefaultModeItem: function () {
        return (this.configItems || []).find(function (i) {
          return i.key === 'prompts.verbilizer_default_mode';
        }) || null;
      },
      // Клик по табу / смена селекта: переключает редактируемый режимный
      // блок и задаёт режим по умолчанию (ключ prompts.verbilizer_default_mode,
      // автосейв). Review iter1 (High): сохраняем по факту СМЕНЫ режима
      // (promptMode !== mode), а не по `item.value !== mode` — иначе селект
      // (аргумент = текущее item.value) никогда не сохранялся.
      selectPromptMode: async function (mode) {
        if (!mode) return;
        mode = String(mode);
        var changed = this.promptMode !== mode;
        this.promptMode = mode;
        var item = this.promptDefaultModeItem();
        if (item && changed && this.canEditConfig(item.key)) {
          item.value = mode;
          await this.saveConfigItem(item);
        }
      },
      // F6 (10.24, ADR-1024-10, review iter1): таб в V2 ТОЛЬКО переключает
      // редактируемый режимный блок и НЕ пишет fallback-ключ (его пишет
      // единственный дропдаун в шапке). OFF-карточка 10.23 продолжает
      // использовать selectPromptMode (switch+save) — её поведение не меняем.
      switchPromptMode: function (mode) {
        if (!mode) return;
        this.promptMode = String(mode);
      },
      // Единственная точка записи ключа prompts.verbilizer_default_mode из V2:
      // вызывается только шапочным дропдауном по @change. v-model уже обновил
      // item.value; синхронизируем редактируемый режим и сохраняем ключ.
      savePromptFallbackMode: async function () {
        var item = this.promptDefaultModeItem();
        if (!item) return;
        var value = String(item.value == null ? '' : item.value);
        var allowed = this.promptModeTabs.map(function (t) { return t.id; });
        if (allowed.indexOf(value) >= 0) this.promptMode = value;
        // F0.1: await + guard in-flight внутри saveConfigItem — двойной тап
        // дропдауна НЕ порождает второй POST.
        if (this.canEditConfig(item.key)) await this.saveConfigItem(item);
      },
      // F6 (10.24, ADR-1024-10 D1): условие аккордеона на «Промптах».
      // V2 ON → всегда false (advanced-элементы идут в общий grid через
      // promptVisibleItems); OFF → как в 10.23 (basic + <details>).
      promptsShowAccordion: function (sec) {
        if (!sec) return false;
        var v2 = (typeof this.uiFlag === 'function')
          ? this.uiFlag('PROMPTS_UI_V2_ENABLED') : true;
        return !v2 && (sec.advanced || []).length > 0;
      },
      _syncPromptModeFromConfig: function () {
        var item = this.promptDefaultModeItem();
        // F6 (10.24, ADR-1024-10 D2): пусто/бито → код-дефолт `casual`
        // (резервный режим), не `serious`. Валидное значение приоритетно.
        var allowed = this.promptModeTabs.map(function (t) { return t.id; });
        var value = item ? String(item.value == null ? '' : item.value) : '';
        this.promptMode = allowed.indexOf(value) >= 0 ? value : 'casual';
      },
      // F6 (10.24, ADR-1024-10 D1): элементы секции для плоской раскладки.
      // V2 ON → basic + advanced в ОДНОМ grid (аккордеон не нужен: одиночный
      // textarea виден сразу). OFF → только basic (advanced остаётся под
      // <details> прежней раскладки 10.23).
      promptVisibleItems: function (sec) {
        if (!sec) return [];
        var v2 = (typeof this.uiFlag === 'function')
          ? this.uiFlag('PROMPTS_UI_V2_ENABLED') : true;
        if (!v2) return sec.basic || [];
        return (sec.basic || []).concat(sec.advanced || []);
      },
      // ── Блок мониторинга динамического анти-клише (API F4) ────────────
      // Fail-open: F4-API недоступен (403/404/503/сеть) → блок скрыт
      // (clicheAvailable=false), вкладка «Промпты» продолжает работать.
      loadCliche: async function () {
        if (!this.isGlobalAdmin) { this.clicheAvailable = false; return; }
        this.clicheLoading = true;
        try {
          var data = await this.api('/api/anticliche');
          this.clicheMeta = data || null;
          this.clicheAvailable = true;
          this.clicheLimitDraft = String(this.clicheLimitValue());
        } catch (e) {
          this.clicheAvailable = false;
          this.clicheMeta = null;
        } finally {
          this.clicheLoading = false;
        }
      },
      maybeLoadCliche: function () {
        // F8 (review iter1): обновляем список при КАЖДОМ входе на вкладку
        // (не только при первом) — дата/форс не «замерзают». Защита от
        // параллельных запросов — clicheLoading.
        if (this.isGlobalAdmin && this.activeTab === 'prompts'
            && !this.clicheLoading) {
          this.loadCliche();
        }
      },
      forceRefreshCliche: async function () {
        if (this.clicheBusy) return;
        this.clicheBusy = true;
        try {
          await this.api('/api/anticliche/refresh', { method: 'POST' });
          await this.loadCliche();
          this.toast('Список анти-клише обновлён', 'ok');
        } catch (e) {
          this.toast('Не удалось обновить список анти-клише', 'err');
        } finally {
          this.clicheBusy = false;
        }
      },
      toggleClicheEdit: function () {
        if (this.clicheEditing) { this.clicheEditing = false; return; }
        var pats = (this.clicheMeta && this.clicheMeta.patterns) || [];
        this.clicheDraft = pats.map(function (p) { return p.phrase; }).join('\n');
        this.clicheLenWarned = false;
        this.clicheEditing = true;
      },
      limitClicheDraft: function () {
        // Review fix: канон 120 на ФРАЗУ. Поле многострочное (фраза на
        // строку), поэтому HTML `maxlength` ограничил бы ВЕСЬ черновик —
        // режем по строкам; о первом усечении честно предупреждаем.
        var max = 120;
        var trimmed = false;
        var out = String(this.clicheDraft || '').split('\n').map(function (line) {
          if (line.length > max) { trimmed = true; return line.slice(0, max); }
          return line;
        });
        if (trimmed) {
          this.clicheDraft = out.join('\n');
          if (!this.clicheLenWarned) {
            this.clicheLenWarned = true;
            this.toast('Фраза-клише сокращена до ' + max + ' символов', 'warn');
          }
        }
      },
      saveCliche: async function () {
        if (this.clicheBusy) return;
        var maxLen = 120;   // T-2488 (ADR-1025-7 D2): канон длины фразы
        var phrases = String(this.clicheDraft || '').split('\n')
          .map(function (s) { return s.trim(); })
          .filter(function (s) { return s.length > 0; });
        var tooLong = phrases.filter(function (s) { return s.length > maxLen; });
        if (tooLong.length) {
          // Понятная ошибка, а НЕ тихий дроп усечённой фразы (T-2492).
          this.toast('Фраз длиннее ' + maxLen + ' символов: ' + tooLong.length +
                     '. Сократите их и сохраните заново.', 'err');
          return;
        }
        this.clicheBusy = true;
        try {
          var resp = await this.api('/api/anticliche', {
            method: 'PUT',
            body: JSON.stringify({ patterns: phrases.map(function (p) {
              return { phrase: p };
            }) }),
          });
          await this.loadCliche();
          this.clicheEditing = false;
          var total = phrases.length;
          var savedN = (resp && typeof resp.count === 'number')
            ? resp.count : total;
          var dropped = (resp && resp.dropped) || {};
          var clicheReasonLabels = {
            invalid: 'некорректные', hardcoded: 'хардкод-клише',
            duplicate: 'дубли', over_limit: 'сверх лимита',
          };
          var reasons = [];
          ['invalid', 'hardcoded', 'duplicate', 'over_limit'].forEach(
            function (k) {
              var arr = dropped[k] || [];
              if (arr.length) {
                reasons.push(clicheReasonLabels[k] + ': ' + arr.length);
              }
            });
          if (savedN >= total && reasons.length === 0) {
            this.toast('Список анти-клише сохранён', 'ok');
          } else {
            // 200 ≠ «всё сохранено»: честно показываем, что отброшено и почему.
            this.toast('Сохранено ' + savedN + ' из ' + total
                       + (reasons.length ? '; отброшено — '
                           + reasons.join(', ') : ''),
                       savedN > 0 ? 'warn' : 'err');
          }
        } catch (e) {
          this.toast('Не удалось сохранить список анти-клише', 'err');
        } finally {
          this.clicheBusy = false;
        }
      },
      clicheStatusLabel: function () {
        // F0.3 (ADR-1025-3 D3): честные статусы; «нет новых» ≠ ошибка модели.
        var map = { ok: 'актуален', parse_error: 'ошибка разбора',
                    fetch_error: 'ошибка загрузки',
                    llm_error: 'ошибка провайдера',
                    budget_skip: 'пропуск по бюджету',
                    empty: 'новых нет (успех)', no_new: 'новых нет (успех)',
                    disabled: 'отключён', never: 'ещё не обновлялся',
                    fresh: 'актуален (кэш свежий)' };
        var st = (this.clicheMeta && this.clicheMeta.last_status) || 'never';
        return map[st] || st;
      },
      // F0.3 (ADR-1025-3 D1): «за обновление ≤ K» — размер партии (per_run),
      // отдельно от вместимости (max_patterns).
      clichePerRun: function () {
        return (this.clicheMeta && this.clicheMeta.per_run) || 0;
      },
      formatClicheDate: function (iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return String(iso);
        try { return d.toLocaleString(); } catch (e) { return String(iso); }
      },
      // F7 (10.24, ADR-1024-3 D1): регулируемый лимит анти-клише. Поле —
      // числовой ввод в карточке монитора, значение — каталоговый ключ
      // limits.anticliche_max_patterns (int, default 200; clamp 1..1000).
      clicheLimitItem: function () {
        var items = this.configItems || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i].key === 'limits.anticliche_max_patterns') {
            return items[i];
          }
        }
        return null;
      },
      clicheLimitValue: function () {
        var it = this.clicheLimitItem();
        if (it && it.value !== null && it.value !== undefined
            && it.value !== '') {
          return it.value;
        }
        return (this.clicheMeta && this.clicheMeta.max_patterns) || 0;
      },
      canEditClicheLimit: function () {
        var it = this.clicheLimitItem();
        return it ? this.canEditConfig(it.key) : false;
      },
      saveClicheLimit: async function () {
        if (this.clicheBusy) return;
        var it = this.clicheLimitItem();
        if (!it) {
          this.toast('Лимит не загружен — откройте вкладку заново', 'warn');
          return;
        }
        var val = parseInt(this.clicheLimitDraft, 10);
        if (!isFinite(val) || val < 1 || val > 1000) {
          this.toast('Лимит анти-клише: целое число от 1 до 1000', 'err');
          this.clicheLimitDraft = String(this.clicheLimitValue());
          return;
        }
        this.clicheBusy = true;
        try {
          // Review iter1 (Medium): динамический кэш анти-клише — глобальная
          // сущность; воркер резолвит лимит через `hot.get` (только
          // глобальный слой). Принудительно сохраняем ключ глобально (без
          // X-Chat-Id), иначе в контексте чата правка ушла бы в per-chat
          // слой и была бы тихим no-op. `per_chat:false` → глобальный путь
          // внутри `saveConfigItem`.
          var payload = Object.assign({}, it, { per_chat: false, value: val });
          await this.saveConfigItem(payload);
        } finally {
          this.clicheBusy = false;
          await this.loadCliche();
        }
      },

      canEditConfig: function (key) {
        var p = this.permissions;
        if (p.wildcard) return true;
        var cat = String(key).split('.')[0];
        // F11 (10.24, ADR-1024-12): ГЛОБАЛЬНЫЙ провайдерский секрет (image)
        // правит ТОЛЬКО глобальный админ — паритет с safe-эндпоинтом
        // (`scope=global`), который иначе отдаёт 403. Секция `keys` НЕ даёт
        // права на этот ключ (иначе UI обещал бы возможность, которую
        // бэкенд отбирает).
        if (isGlobalSecretKey(key)) {
          // `isGlobalAdminEffective` — computed (ЗНАЧЕНИЕ, не метод).
          return !!this.isGlobalAdminEffective;
        }
        // F-14 (§6, ремедиация ревью): в DM-скоупе (свои ЛС) юзер правит
        // параметры как local_admin — permissions из /api/me (глобальная
        // роль user = {}) не отражают is_dm_owner. НО сервер (routes.py)
        // в chat/DM-скоупе отвергает per_chat=False (models.*, keys.*) → 422
        // («ключ нельзя переносить на уровень чата»). Зеркалим сервер:
        // такие ключи в DM — read-only (R10.5-2). keys.* — только BYOK.
        if (this.isDmCtx()) {
          var dmItem = (this.configItems || []).find(function (i) {
            return i.key === key;
          });
          if (dmItem && dmItem.per_chat === false) return false;
          if (cat === 'models' || cat === 'keys') return false;  // fallback
          return true;
        }
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
          // F4 D4: ключ избранного модулей — с суффиксом аккаунта, если есть.
          this.initQuickpicks();
          // UI-полировка TMA: свежий аватар (CDN photo_url / blob-прокси);
          // после ошибок поле сбрасывается — img может появиться вновь
          this.refreshMeAvatar();
        } catch (e) {
          if (e.status === 401) { /* authError уже выставлен */ }
          this.me = null;
        }
      },

      // 10.9 (п.3): сохранение параметра не сбрасывает прокрутку. Снимок
      // scrollTop до fn(), восстановление в $nextTick после (после
      // ре-рендера loadConfig). setTab-сброс НЕ трогаем.
      // 10.9 MEDIUM-4: в TMA-fullscreen скроллится НЕ document, а
      // main.scroll-area (.app-shell overflow:hidden) — сохраняем/восстанавливаем
      // оба контейнера.
      _preserveScroll: async function (fn, ctx) {
        var doc = (typeof document !== 'undefined') ? document : null;
        function scrollEl() {
          return doc ? (doc.scrollingElement || doc.documentElement) : null;
        }
        function areaEl() {
          if (!doc) return null;
          if (doc.querySelector) return doc.querySelector('.scroll-area');
          return null;
        }
        var el = scrollEl();
        var top = el ? el.scrollTop : 0;
        var area = areaEl();
        var areaTop = area ? area.scrollTop : 0;
        try {
          return await fn.call(ctx || this);
        } finally {
          this.$nextTick(function () {
            var e2 = scrollEl();
            if (e2) e2.scrollTop = top;
            var a2 = areaEl();
            if (a2) a2.scrollTop = areaTop;
          });
        }
      },

      // F7 (M-F7-2, §64): нормализация витрины конфига после загрузки.
      // 1) widget отсутствует у старого сервера — дефолт '';
      // 2) presentation-оверрайд: списки ID Оли (`type=json, widget=''` в
      //    каталоге, Δ каталога=0) → `list` (структурированный редактор, не
      //    сырой CSV/textarea);
      // 3) остальные json без виджета — строкифаем (textarea-текст как раньше);
      //    json с widget='keyvalue'/'list' НЕ строкифаим (остаётся объектом/
      //    массивом для компонента-редактора).
      _normalizeConfigItems: function (items) {
        (items || []).forEach(function (item) {
          if (!item.widget) item.widget = '';
          if (!item.widget && PERMSOC_LIST_WIDGET_KEYS[item.key]) {
            item.widget = 'list';
          }
          if (item.type === 'json' && !item.widget &&
              typeof item.value === 'object' && item.value !== null) {
            item.value = JSON.stringify(item.value, null, 2);
          }
        });
        return items;
      },

      loadConfig: async function () {
        var epoch = this.scopeEpoch;   // D2: снимок scope
        this.configLoading = true;
        try {
          var data = await this.api('/api/config');
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.configError = '';      // F-13 (AC-3): успех — баннер скрыт
          // F4 (L-F4-2): успешный reload активной области снимает «залипшую»
          // ошибку сохранения модуля (ключ принадлежит прочитанной области).
          this.moduleSaveError = {};
          this.configItems = data.items || [];
          // F10 (ADR-1024-11 D2): reload → новая версия; :key kv-editor
          // перемонтирует редактор (created/immediate-watch видит финальное
          // значение, а не «ещё не приехало»).
          this.configVersion++;
          this.configGroups = data.groups || [];
          this.configChatUpdatedAt = data.updated_at != null
            ? data.updated_at : null;   // optimistic-метка чата (409-протокол)
          // 10.10 (п.3): успешная загрузка = свежие значения из configItems;
          // старые черновики сбрасываем (draft==null = «не трогать»), иначе
          // черновик «переживал» бы reload и показывал стейл.
          this.blockDrafts = {};
          this._normalizeConfigItems(this.configItems);
          // 3.5.2: после перезагрузки KV-редакторы (компоненты) сами
          // пересоберут пары из item.value — внешних черновиков нет.
          // 10.20 (T-1900): baseline sticky-save = свежезагруженный конфиг.
          if (typeof this._snapshotConfig === 'function') this._snapshotConfig();
          // F8 (ADR-1023-8): синхронизируем активный режим Вербализатора с
          // ключом по умолчанию и (на вкладке «Промпты») подтягиваем блок
          // анти-клише (fail-open).
          this._syncPromptModeFromConfig();
          if (this.activeTab === 'prompts') this.maybeLoadCliche();
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          // ПРОД-ИНЦИДЕНТ (C): 401 различается — понятное сообщение вместо
          // общего «Не удалось загрузить конфигурацию».
          // F-13 (AC-3, MED-021): 403/503/сеть — configError-баннер
          // (вкладка «пустая» из-за отказа сервера — баннер объясняет);
          // 401-тост и остальные тосты — как были. configError очищается
          // успешным loadConfig и setActiveChat.
          if (e.status === 401) {
            this.toast('Сессия Telegram недействительна — открой админку через кнопку меню в боте', 'warn');
          } else if (e.status === 403) {
            // api() уже тостит «Доступ запрещён: …» — здесь баннер-совет
            this.configError = 'Нет доступа к параметрам этого чата — выберите другой чат или глобальный режим.';
          } else if (e.status === 503) {
            this.configError = 'PostgreSQL недоступен — попробуйте позже.';
            this.toast('Не удалось загрузить конфигурацию', 'err');
          } else {
            this.configError = 'Не удалось загрузить конфигурацию: '
              + ((e && e.message) ? e.message : 'сеть недоступна');
            this.toast('Не удалось загрузить конфигурацию', 'err');
          }
        } finally {
          if (this._scopeGuard(epoch)) this.configLoading = false;   // R3
        }
      },

      // 3.5.1: проходят ли item правила источника вкладки (зеркало
      // TAB_RULES: groups=белый список | except=вся категория кроме | null=вся).
      itemMatchesSource: function (item, source) {
        if (!source || source.category !== item.category) return false;
        if (source.groups) return source.groups.indexOf(item.group) >= 0;
        if (source.except) return source.except.indexOf(item.group) < 0;
        return true;                                  // null → вся категория
      },
      tabSourceForItem: function (tab, item) {
        var self = this;
        var srcs = (tab && tab.sources) || [];
        for (var i = 0; i < srcs.length; i++) {
          if (self.itemMatchesSource(item, srcs[i])) return srcs[i];
        }
        return null;
      },
      // Количество параметров вкладки БЕЗ поиска (для пустых состояний).
      tabItemCount: function (tab) {
        var self = this;
        return this.configItems.reduce(function (n, it) {
          return self.tabSourceForItem(tab, it) ? n + 1 : n;
        }, 0);
      },
      // Раунд 10.4 (E-2): ранг группы в витрине = индекс ПЕРВОГО правила
      // (category, groups), которому группа принадлежит; для except-правил —
      // первое правило категории (fallback). Для вкладок без повторения
      // категорий результат равен старой категориальной сортировке.
      flatGroupRank: function (tab, category, groupId) {
        if (!tab || !tab.sources) return 99;
        var catFirst = {};
        var ruleOf = {};
        tab.sources.forEach(function (s, i) {
          if (!(s.category in catFirst)) catFirst[s.category] = i;
          if (s.groups) {
            s.groups.forEach(function (g) {
              var k = s.category + '/' + g;
              if (!(k in ruleOf)) ruleOf[k] = i;
            });
          }
        });
        var k = category + '/' + groupId;
        if (k in ruleOf) return ruleOf[k];
        return catFirst[category] != null ? catFirst[category] : 99;
      },
      // F6 (ADR-1025-19 D6): презентационная подгруппа параметра «Памяти».
      // Классификация по ключу — без правки каталога (Δ каталога = 0).
      _memorySubgroupOf: function (item) {
        var u = String((item && item.key) || '').toUpperCase();
        if (u.indexOf('DIG_') >= 0) return 'search';
        if (u.indexOf('RELATIONS_') >= 0 || u.indexOf('IRONY_FILTER') >= 0) {
          return 'relations';
        }
        if (u.indexOf('DEEP_SLEEP') >= 0 || u.indexOf('BELIEF_') >= 0
            || u.indexOf('DREAM_') >= 0) {
          return 'dream';
        }
        if (u.indexOf('VEC_INT8') >= 0 || u.indexOf('MEMORY_BACKUP') >= 0
            || u.indexOf('FULL_MEMORY_RETENTION') >= 0
            || u.indexOf('ARCHIVE_MEMORY_RETENTION') >= 0
            || u.indexOf('GRAPH_USER_QUOTA') >= 0
            || u.indexOf('EMBED_CACHE') >= 0) {
          return 'storage';
        }
        if (u.indexOf('GRAPH_') >= 0) return 'graph';
        return 'other';
      },
      setMemorySubgroup: function (id) {
        this.memorySubgroup = id || '';
      },
      // F6 (D6): 5 подгрупп «Память → Настройки» вместо групп каталога.
      // Возвращает псевдо-группы в порядке MEMORY_SUBGROUPS; при активной
      // подгруппе — только она. Ни один параметр не теряется (§116).
      _memoryGroups: function () {
        var self = this;
        var base = this.groupedForTab(this.currentTab);
        var buckets = {};
        MEMORY_SUBGROUPS.forEach(function (s) {
          buckets[s.id] = {
            uid: 'memsub:' + s.id, id: s.id, category: '',
            subgroup: s.id, title: s.title,
            meta: { id: s.id, title: s.title, order: 0 }, items: [],
          };
        });
        (base || []).forEach(function (g) {
          (g.items || []).forEach(function (it) {
            var sid = self._memorySubgroupOf(it);
            buckets[sid].items.push(it);
          });
        });
        var want = this.memorySubgroup || '';
        return MEMORY_SUBGROUPS.map(function (s) { return buckets[s.id]; })
          .filter(function (g) {
            if (!g.items.length) return false;
            return !want || want === g.id;
          });
      },
      // Группы-«витрины» активной конфиг-вкладки: [{id, meta, category,
      // items[]}]. Порядок — по flatGroupRank (порядок правил; для
      // секционированных вкладок — секции), внутри — group.order;
      // параметры без group → «Прочее» в конце. Поиск-фильтр как раньше.
      // R10.6-1: ключи, уже редактируемые в provider-блоках (один дом).
      // 10.11 (§2.0): рекурсивно обходим subBlocks[].fields (embeddings).
      providerCoveredKeys: function () {
        var keys = {};
        function addFields(fields) {
          (fields || []).forEach(function (f) { keys[f.key] = true; });
        }
        (this.providerBlocks || []).forEach(function (b) {
          addFields(b.fields);
          (b.subBlocks || []).forEach(function (sb) {
            addFields(sb.fields);
          });
        });
        return keys;
      },
      groupedForTab: function (tab) {
        var self = this;
        if (!tab || !tab.sources) return [];
        // R10.6-1: на «LLM Провайдеры» generic-редакторы НЕ дублируют поля,
        // уже показанные в блоках (остальные поля групп остаются).
        var covered = (tab.id === 'llm_providers')
          ? this.providerCoveredKeys() : null;
        var q = (this.configSearch || '').trim().toLowerCase();
        var items = this.configItems.filter(function (it) {
          if (!self.tabSourceForItem(tab, it)) return false;
          if (covered && covered[it.key]) return false;
          if (!q) return true;
          return (it.title || '').toLowerCase().indexOf(q) >= 0
            || (it.description || '').toLowerCase().indexOf(q) >= 0
            || (it.key || '').toLowerCase().indexOf(q) >= 0;
        });
        var byId = {};
        this.configGroups.forEach(function (g) { byId[g.id] = g; });
        var grouped = items.reduce(function (acc, it) {
          var gid = it.group || '';
          var uid = it.category + '/' + gid;
          if (!acc[uid]) {
            acc[uid] = {
              uid: uid,            // уникальный ключ витрины для v-for
              id: gid,
              category: it.category,
              meta: gid ? (byId[gid] || null) : null,
              items: [],
            };
          }
          acc[uid].items.push(it);
          return acc;
        }, {});
        var result = Object.keys(grouped).map(function (k) { return grouped[k]; });
        result.sort(function (a, b) {
          if (a.id === '' && b.id === '') return 0;
          if (a.id === '') return 1;               // «Прочее» — в конец
          if (b.id === '') return -1;
          var ra = self.flatGroupRank(tab, a.category, a.id);
          var rb = self.flatGroupRank(tab, b.category, b.id);
          if (ra !== rb) return ra - rb;
          var oa = a.meta ? a.meta.order : 999;
          var ob = b.meta ? b.meta.order : 999;
          return oa - ob;
        });
        // параметры внутри группы уже отсортированы сервером
        // BUG-5 (дефенсив, spec §10 F-11): группа, где после
        // basic/advanced-разделения не осталось ни одного элемента,
        // в рендер не попадает (карточка «(0)» не рисуется).
        return result.filter(function (g) {
          return self.basicItems(g).length > 0 || self.advancedItems(g).length > 0;
        });
      },

      // Раунд 10.25 (F7, ADR-1025-20 D1/D2/D3): owner-блоки PERMsoc.
      // Без выбранного чата редактируемых блоков НЕТ (§60): PERMsoc —
      // локальное пространство. Элементы распределяются по владельцу
      // (key-level), ключи-тумблеры исключаются из тела; мастер — отдельно.
      _permsocOwnerGroups: function () {
        var self = this;
        if (typeof this.isChatContext === 'function' && !this.isChatContext()) {
          return [];   // §60: не правим глобал — блоки не рендерятся
        }
        var grouped = this.groupedForTab(this.currentTab);
        var claimed = {};
        PERMSOC_OWNER_BLOCKS.forEach(function (o) {
          (o.keys || []).forEach(function (k) { claimed[k] = true; });
        });
        // Ключ ровно в одном блоке: explicit `keys` (приоритет) → `groups`
        // (добор невзятых). Незнакомый ключ остаётся без блока (не свалка).
        function ownerOf(it) {
          for (var i = 0; i < PERMSOC_OWNER_BLOCKS.length; i++) {
            var o = PERMSOC_OWNER_BLOCKS[i];
            if ((o.keys || []).indexOf(it.key) >= 0) return o.id;
            if ((o.groups || []).indexOf(it.group) >= 0 && !claimed[it.key]) {
              return o.id;
            }
          }
          return null;
        }
        var result = PERMSOC_OWNER_BLOCKS.map(function (o) {
          return {
            uid: 'owner:' + o.id, id: o.id, category: '', owner: o,
            meta: { id: o.id, title: o.title,
                    description: self._ownerDescription(o) },
            items: [],
          };
        });
        var byId = {};
        result.forEach(function (r) { byId[r.id] = r; });
        grouped.forEach(function (g) {
          g.items.forEach(function (it) {
            if (PERMSOC_TOGGLE_KEYS[it.key]) return;   // только в <summary>
            var oid = ownerOf(it);
            if (oid && byId[oid]) byId[oid].items.push(it);
          });
        });
        // LOW-6: все owner-блоки рендерятся всегда (тумблер — в <summary>),
        // даже если тело пустое/скрыто правами. Не фильтруем по items.length.
        return result;
      },
      _ownerDescription: function (o) {
        return {
          slavik: 'Фото, гифки, посты из старого канала и передразнивания Славика.',
          kostik: 'ID, фразы-реплики и вероятность ответа.',
          olya: 'Реакции бота на видео Оли и подписи к ним.',
          mimic: 'Кого бот передразнивает и как часто.',
          reactions: 'Приветствия Лехи, военные оповещения, триггеры и общие медиа.',
          schedule: 'Утренняя рассылка и дополнительные ограничения по времени.',
        }[o.id] || '';
      },
      // D5: витринные подгруппы блока (§62–§67) — presentation-level.
      // [{title, keys}] — порядок отображения из ТЗ/спеки.
      permsocOwnerSubgroups: function (owner) {
        if (!owner) return [];
        return PERMSOC_BLOCK_SUBGROUPS[owner.id] || [];
      },
      // H-F7-1 (fix): плоский список витрины для owner-блока с РУССКИМИ
      // заголовками подгрупп (§62/§64/§66 и др.). Возвращает элементы
      // `basicItems(grp)` + псевдо-элементы-заголовки `{__subheader, key}`.
      // Для не-owner групп и при отсутствии подгрупп — прежний плоский
      // список (остальные вкладки не меняются). Элементы, не попавшие ни в
      // одну подгруппу, идут в конец без шапки (страховка; partition-тест
      // гарантирует, что таких нет).
      permsocRenderItems: function (grp) {
        var items = this.basicItems(grp);
        if (!grp || !grp.owner) return items;
        var groups = this.permsocOwnerSubgroups(grp.owner);
        if (!groups.length) return items;
        var byKey = {};
        items.forEach(function (i) { byKey[i.key] = i; });
        var out = [];
        var used = {};
        groups.forEach(function (sg) {
          var sgItems = [];
          (sg.keys || []).forEach(function (k) {
            if (byKey[k] && !used[k]) {
              sgItems.push(byKey[k]);
              used[k] = true;
            }
          });
          if (!sgItems.length) return;
          out.push({ __subheader: sg.title, key: 'subheader:' + sg.title });
          sgItems.forEach(function (it) { out.push(it); });
        });
        items.forEach(function (i) { if (!used[i.key]) out.push(i); });
        return out;
      },
      // M-F7-2 (§64): list-редактор для списков ID Оли использует подписи
      // «ID» (variant='ids'), а не «фразы»/«Костик молчит» (дефолт). Объект
      // для v-bind; дефолт Костика не меняется (тексты — в шаблоне).
      listEditorProps: function (item) {
        if (item && PERMSOC_LIST_WIDGET_KEYS[item.key]) {
          return { variant: 'ids' };
        }
        return {};
      },
      // §63 (D4): `limits.kostik_reply_probability` — сервер хранит float
      // 0.0–1.0, UI показывает проценты 0–100 %. Конвертация ТОЛЬКО на
      // границе виджета (клип [0,1] / [0,100]); серверную шкалу не меняем.
      permsocProbToPercent: function (v) {
        var n = Number(v);
        if (!isFinite(n)) return 0;
        if (n < 0) n = 0;
        if (n > 1) n = 1;
        return Math.round(n * 100);
      },
      permsocPercentToProb: function (p) {
        var n = Number(p);
        if (!isFinite(n)) return 0;
        if (n < 0) n = 0;
        if (n > 100) n = 100;
        return n / 100;
      },
      saveKostikProbability: async function (item, percent) {
        if (!item) return;
        item.value = this.permsocPercentToProb(percent);
        await this.saveConfigItem(item);
      },
      // Состояние owner-тумблера. Персональные — per-chat config-флаг;
      // новые блоки — per-chat блок-гейт (gates.permsoc_*); мастер — gates.
      permsocOwnerOn: function (owner) {
        if (!owner) return false;
        if (owner.gate) return this.permsocBlockGateOn(owner.gate);
        var it = this.configItems.find(function (i) {
          return i.key === owner.toggleKey;
        });
        return !!(it && it.value);
      },
      permsocBlockGateOn: function (feature) {
        var g = this.gateInfo && this.gateInfo.gates;
        return !!(g && g[feature]);
      },
      canToggleOwner: function (owner) {
        if (!owner) return false;
        if (owner.gate) {
          // D3/§61: блок-гейт — global-admin; при OFF kill-switch тумблер
          // честно read-only (серверный эффект отключён).
          if (!this.uiFlag('PERMSOC_BLOCK_GATES_ENABLED')) return false;
          return !!this.isGlobalAdmin;
        }
        return this.canEditConfig(owner.toggleKey);
      },
      // Мастер-тумблер §61 — только global admin (PUT /gates).
      canToggleMaster: function () {
        return !!this.isGlobalAdmin;
      },
      // Единственный путь записи owner-тумблера: блок-гейт → gates,
      // персональный — config; НЕ оба одновременно. OFF блока пишет ТОЛЬКО
      // собственный ключ (`toggleKey`/`gate`) — дочерние не сбрасываются.
      toggleOwner: async function (owner, checked) {
        if (!owner) return;
        if (owner.gate) {
          if (!this.canToggleOwner(owner)) return;
          await this.toggleGate(owner.gate, !!checked);
          return;
        }
        if (!this.canToggleOwner(owner)) return;
        var it = this.configItems.find(function (i) {
          return i.key === owner.toggleKey;
        });
        if (!it) {
          this.toast('Параметр недоступен: ' + owner.toggleKey, 'warn');
          return;
        }
        it.value = !!checked;
        await this.saveConfigItem(it);
      },

      // Раунд 10.4 (E-3): заголовок секции витрины — для ПЕРВОЙ группы
      // секции (шапка выводится один раз; группы секции подряд).
      sectionTitle: function (grp) {
        var tab = this.currentTab;
        if (!tab || !tab.sections || !grp) return null;
        var s = null;
        for (var i = 0; i < tab.sections.length; i++) {
          var sec = tab.sections[i];
          if ((sec.category === null || sec.category === grp.category)
              && sec.groups.indexOf(grp.id) >= 0) { s = sec; break; }
        }
        if (!s) return null;
        var groups = this.currentTabGroups || [];
        for (var j = 0; j < groups.length; j++) {
          var g = groups[j];
          if ((s.category === null || s.category === g.category)
              && s.groups.indexOf(g.id) >= 0) {
            return g === grp ? s.title : null;
          }
        }
        return null;
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
      // 3.5.1: маска секрета с кнопкой показать — перенесено в компонент
      // `secret-field` (F9/ADR-1025-22 D4: локальный `reveal`), per-key
      // `keyReveal`/`toggleKeyReveal` удалены как мёртвый код.

      inputType: function (item) {
        if (item.type === 'int' || item.type === 'float') return 'number';
        return 'text';
      },

      // F0 (10.25, ADR-1025-2 D1): поиск конфиг-элемента по ключу (для
      // заголовков уведомлений / сравнения черновика с сервером).
      _findConfigItem: function (key) {
        var items = this.configItems || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i] && items[i].key === key) return items[i];
        }
        return null;
      },

      // F0 (10.25, ADR-1025-4 D1): ОДНО итоговое уведомление на операцию.
      // Идемпотентен по operationId (повтор — игнор). ok/warn/err —
      // по частичному результату (никогда «success+error» без объяснения).
      notify: function (operationId, result, items) {
        if (operationId) {
          // L-3 (ревью): сначала нормализуем хранилище, потом читаем ключ.
          if (!this._opNotified || typeof this._opNotified !== 'object') {
            this._opNotified = {};
          }
          if (this._opNotified[operationId]) return;
          this._opNotified[operationId] = result || true;
          // F0.4 (ревью): ограничить рост — ленивая очистка по окну тоста,
          // чтобы таблица идемпотентности не росла на каждую операцию.
          var selfOp = this;
          setTimeout(function () {
            if (selfOp._opNotified) delete selfOp._opNotified[operationId];
          }, 8000);
        }
        var res = result || {};
        var saved = res.saved || [];
        var failed = res.failed || [];
        var skipped = res.skipped || [];
        var total = saved.length + failed.length;
        var self = this;
        var titleOf = function (key) {
          var it = self._findConfigItem(key);
          return (it && it.title) ? it.title : key;
        };
        // Только in-flight-пропуски (ничего не отправляли) — без тоста:
        // итог озвучит владелец летящей операции (не дублируем, не врём).
        if (!saved.length && !failed.length && skipped.length) return;
        if (!failed.length) {
          if (saved.length === 1) {
            this.toast('Сохранено: ' + titleOf(saved[0]), 'ok');
          } else if (saved.length > 1) {
            this.toast('Сохранено: ' + saved.length + ' из ' + total, 'ok');
          }
          return;
        }
        var names = failed.map(function (f) {
          return titleOf(f.key);
        }).join(', ');
        if (saved.length) {
          this.toast('Сохранено ' + saved.length + ' из ' + total +
                     '; не сохранено: ' + names, 'warn');
        } else {
          this.toast('Не сохранено: ' + names, 'err');
        }
      },

      // F0 (10.25, ADR-1025-2 D2): ЕДИНАЯ точка сохранения.
      // items, {reason, operationId, silent} → OperationResult
      // {saved:[key], failed:[{key,reason,conflicting}], revalidated, state}.
      // Guard in-flight по ключу (двойной тап = один запрос); scope-split
      // (chat/global — отдельные POST); токен обязателен для chat (RC-6);
      // 409-recovery — один re-read + сравнение, без авто-retry.
      persistItems: async function (items, opts) {
        opts = opts || {};
        var self = this;
        var operationId = opts.operationId || ('op-' + (++this._opSeq));
        // Защита от «минимального» контекста (юнит-тесты вызывают методы
        // напрямую): недостающие хелперы/Set не должны ронять запись.
        var saving = this.saving;
        if (!saving || typeof saving.has !== 'function') {
          saving = this.saving = new Set();
        }
        var serialize = (typeof this._serializeValue === 'function')
          ? this._serializeValue
          : function (v) { return JSON.stringify(v); };
        var inScope = (typeof this._scopeGuard === 'function')
          ? function (ep) { return self._scopeGuard(ep); }
          : function () { return true; };
        var list = (items || []).filter(Boolean);
        var drafts = {};
        var skipped = [];
        var guardBlocked = [];   // F7 D1: PERMsoc-ключи при scope=global
        var chatItems = [];
        var globalItems = [];
        for (var i = 0; i < list.length; i++) {
          var it = list[i];
          if (!it || it.key == null) continue;
          drafts[it.key] = serialize(it.value);
          // F7 (ADR-1025-20 D1/§60): PERMsoc — НЕ глобальная конфигурация.
          // Без выбранного чата (scope=global) либо с per_chat=false запись
          // PERMsoc-ключа ЗАПРЕЩЕНА (ban + уведомление, не молча).
          if (PERMSOC_LOCAL_KEYS[it.key]
              && (this.activeChatId == null || it.per_chat === false)) {
            guardBlocked.push(it.key);
            continue;
          }
          if (saving.has(it.key)) { skipped.push(it.key); continue; }  // in-flight
          saving.add(it.key);
          if (it.per_chat === false) globalItems.push(it);
          else chatItems.push(it);
        }
        // Все ключи уже в полёте (двойной тап/параллельный вызов): НЕ дублируем
        // запрос и НЕ объявляем ложный успех — итог озвучит владелец in-flight
        // операции. Пропущенные ключи возвращаем явно (не молча).
        if (!chatItems.length && !globalItems.length) {
          if (guardBlocked.length) {
            var gbFailed = guardBlocked.map(function (k) {
              return { key: k, reason: 'permsoc-global' };
            });
            var gbResult = { saved: [], failed: gbFailed, skipped: skipped,
                             revalidated: false, state: 'error',
                             operationId: operationId };
            this.stickyFailedKeys = guardBlocked.slice();
            if (!opts.silent && typeof this.notify === 'function') {
              this.notify(operationId, gbResult, list);
            }
            return gbResult;
          }
          return { saved: [], failed: [], skipped: skipped,
                   revalidated: false, state: 'saving',
                   operationId: operationId, inFlight: true };
        }
        // RC-6: chat-scope с null-токеном (сменили scope) — сначала loadConfig.
        if (chatItems.length && this.configChatUpdatedAt == null) {
          try { await this.loadConfig(); } catch (e) { /* fail-open */ }
        }
        var saved = [];
        var failed = [];
        var revalidated = false;
        var groups = [];
        if (chatItems.length) groups.push({ items: chatItems, isGlobal: false });
        if (globalItems.length) groups.push({ items: globalItems, isGlobal: true });
        for (var g = 0; g < groups.length; g++) {
          var grp = groups[g];
          var epoch = this.scopeEpoch;
          var body = {
            items: grp.items.map(function (x) {
              return { key: x.key, value: x.value };
            }),
            updated_at: grp.isGlobal ? null : this.configChatUpdatedAt,
          };
          try {
            var resp = await this.api('/api/config', {
              method: 'POST',
              body: JSON.stringify(body),
              global: grp.isGlobal,
            });
            if (!inScope(epoch)) continue;            // устаревший scope
            if (resp && resp.revalidated) revalidated = true;
            if (resp && resp.updated_at && !grp.isGlobal) {
              this.configChatUpdatedAt = resp.updated_at;
            }
            for (var s = 0; s < grp.items.length; s++) {
              saved.push(grp.items[s].key);
            }
          } catch (e) {
            var isConflict = (e.status === 409 && e.message
                              && e.message.code === 'conflict');
            var conflicting = isConflict
              ? (e.message.conflicting || []) : [];
            for (var f = 0; f < grp.items.length; f++) {
              failed.push({
                key: grp.items[f].key,
                reason: isConflict ? 'conflict' : (e.message || 'error'),
                conflicting: conflicting,
              });
            }
          } finally {
            for (var d = 0; d < grp.items.length; d++) {
              saving.delete(grp.items[d].key);
            }
          }
        }
        // §2.3 409-recovery: без авто-retry; один re-read + сравнение.
        var conflictFailed = failed.filter(function (f) {
          return f.reason === 'conflict';
        });
        if (conflictFailed.length) {
          try { await this.loadConfig(); } catch (e) { /* fail-open */ }
          var stillFailed = [];
          for (var r = 0; r < conflictFailed.length; r++) {
            var cf = conflictFailed[r];
            var serverItem = (typeof this._findConfigItem === 'function')
              ? this._findConfigItem(cf.key) : null;
            var serverVal = serverItem ? serialize(serverItem.value) : null;
            if (serverVal != null && serverVal === drafts[cf.key]) {
              saved.push(cf.key);                     // выполнено после проверки
              revalidated = true;
            } else {
              stillFailed.push(cf);
              // F0.1 (ревью): черновик пользователя НЕ уничтожаем — после
              // loadConfig() возвращаем его в элемент (серверное значение
              // остаётся прочитанным, но поле снова dirty и подсвечено conflict).
              if (serverItem
                  && Object.prototype.hasOwnProperty.call(drafts, cf.key)) {
                var rawDraft = drafts[cf.key];
                if (rawDraft !== undefined) {
                  try { serverItem.value = JSON.parse(rawDraft); }
                  catch (e) { /* не восстановить — оставляем серверное */ }
                }
              }
            }
          }
          failed = failed.filter(function (f) {
            return f.reason !== 'conflict';
          }).concat(stillFailed);
          this.stickyConflict = stillFailed.map(function (f) {
            return f.key;
          });
        } else {
          this.stickyConflict = [];
        }
        // F7 D1: заблокированные PERMsoc-ключи — явный провал (не молча).
        for (var gb2 = 0; gb2 < guardBlocked.length; gb2++) {
          failed.push({ key: guardBlocked[gb2], reason: 'permsoc-global' });
        }
        var state = failed.length ? (saved.length ? 'saved' : 'error')
                                  : 'saved';
        var result = {
          saved: saved, failed: failed, skipped: skipped,
          revalidated: revalidated, state: state, operationId: operationId,
        };
        // F0.4 (ревью): per-field карта провалов — подсветка у полей.
        this.stickyFailedKeys = failed.map(function (f) { return f.key; });
        if (!opts.silent && typeof this.notify === 'function') {
          this.notify(operationId, result, list);
        }
        return result;
      },

      saveConfigItem: async function (item) {
        // F0.1: guard in-flight по ключу (двойной тап = один запрос).
        // Возврат: true — сохранено; null — пропущено (уже в полёте);
        // false — реальный провал.
        if (!item || item.key == null) return false;
        // F7 (ADR-1025-20 D1/§60): PERMsoc-ключ нельзя записать как global.
        // Без выбранного чата или с per_chat=false — отказ с понятным текстом
        // (защита от любого обхода UI; §4 «PERMsoc не глобальная конфигурация»).
        if (PERMSOC_LOCAL_KEYS[item.key]
            && (this.activeChatId == null || item.per_chat === false)) {
          this.toast('PERMsoc: выбери чат — эти настройки не меняются глобально',
                     'warn');
          return false;
        }
        if (this.saving && this.saving.has && this.saving.has(item.key)) {
          return null;                 // in-flight: не наш успех и не провал
        }
        var value = item.value;
        if (item.type === 'json') {
          // 3.5.1: json без widget редактируется текстом JSON → парсим.
          if (typeof value === 'string') {
            try {
              value = JSON.parse(value);
            } catch (e) {
              this.toast('Невалидный JSON в ' + item.key, 'err');
              return false;
            }
          }
        } else if (item.type === 'int') {
          // Раунд 4 (T-718): числовые проверки — ТОЛЬКО для int/float
          // (раньше isNaN('текст') === true ломал str-поля).
          value = parseInt(value, 10);
          if (!isFinite(value)) {
            this.toast('Некорректное значение для ' + item.key, 'err');
            return false;
          }
        } else if (item.type === 'float') {
          value = parseFloat(value);
          if (!isFinite(value)) {
            this.toast('Некорректное значение для ' + item.key, 'err');
            return false;
          }
        } else if (item.type === 'bool') {
          value = !!value;               // чекбокс — как раньше (защитная ветка)
        } else if (value === null || value === undefined) {
          this.toast('Некорректное значение для ' + item.key, 'err');
          return false;
        }
        // Раунд 4 (T-719): str-поле категории prompts/content не может быть
        // пустым (сервер дублирует 422 — единая точка валидации, FR-E2).
        if (item.type === 'str' && typeof value === 'string'
            && (item.category === 'prompts' || item.category === 'content')
            && !value.trim()) {
          this.toast('Промпт не может быть пустым: ' + item.title, 'err');
          return false;
        }
        if (typeof this.persistItems === 'function') {
          // F0.1: единая точка сохранения (guard in-flight и scope-split —
          // внутри; здесь атомарный одиночный ключ).
          var res = await this.persistItems([{ key: item.key, value: value,
                                               per_chat: item.per_chat }]);
          if (res.saved.indexOf(item.key) >= 0) {
            await this._preserveScroll(this.loadConfig);
            return true;
          }
          if (res.skipped && res.skipped.indexOf(item.key) >= 0) {
            // Ключ уже сохраняется другой (in-flight) операцией — НЕ успех
            // и НЕ провал: null (baseline здесь не двигаем).
            return null;
          }
          // S10.20-6: неуспех → false (sticky-панель НЕ сдвигает baseline).
          return false;
        }
        // Легаси-контекст без единого write-path (юнит-тесты): прежний путь.
        var isGlobal = item.per_chat === false;
        try {
          await this.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({
              items: [{ key: item.key, value: value }],
              updated_at: isGlobal ? null : this.configChatUpdatedAt,
            }),
            global: isGlobal,
          });
          this.toast('Сохранено: ' + item.title, 'ok');
          await this._preserveScroll(this.loadConfig);
          return true;
        } catch (e) {
          this.toast('Ошибка сохранения: ' + (e.message || e), 'err');
          return false;
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
        var v = item && item.value;
        if (v && typeof v === 'object') return v.last4 || '';
        // F9 (ADR-1025-22 D3): значение-строку хвостом не раскрываем — нет
        // last4 → display даст «Ключ установлен».
        return '';
      },
      // F9 (10.25, ADR-1025-22 D1/D3): единый display-индикатор секрета.
      // `item` — configItem (со `value`), `{key}`-поле блока ИЛИ строковый ключ
      // (ищем в configItems). Возврат { configured, last4, maskText }.
      secretDisplay: function (item) {
        var v;
        if (typeof item === 'string') {
          var found = (this.configItems || []).find(function (i) {
            return i && i.key === item;
          });
          v = found ? found.value : null;
        } else if (item && typeof item === 'object'
                   && Object.prototype.hasOwnProperty.call(item, 'value')) {
          v = item.value;
        } else if (item && typeof item === 'object' && item.key != null) {
          var byKey = (this.configItems || []).find(function (i) {
            return i && i.key === item.key;
          });
          v = byKey ? byKey.value : null;
        } else {
          v = item;
        }
        return secretDisplayOf(v);
      },
      isSecretMask: function (v) { return isSecretMask(v); },
      // UPD3-fix: композит `маска+ввод` тоже должен распознаваться как маска.
      hasSecretMask: function (v) { return hasSecretMask(v); },
      saveKeyItem: async function (item, silent) {
        var value = (this.keyDrafts[item.key] || '').trim();
        var isGlobal = item.per_chat === false;
        if (hasSecretMask(value)) { if (!silent) this.toast(SECRET_MASK_HINT, 'warn'); return false; }
        if (!value) { if (!silent) this.toast('Введите новый ключ', 'warn'); return false; }
        this.saving.add(item.key);
        try {
          if (item.key === 'keys.image_api_key') { return await this.saveImageKeyItem(item, value); }
          await this.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({
              items: [{ key: item.key, value: value }],
              updated_at: isGlobal ? null : this.configChatUpdatedAt,
            }),
            global: isGlobal,
          });
          this.keyDrafts[item.key] = '';
          if (!silent) this.toast('Ключ обновлён: ' + item.title, 'ok');
          await this._preserveScroll(this.loadConfig);
          if (typeof this._seedSecretMasks === 'function') this._seedSecretMasks();
          return true;
        } catch (e) {
          if (!silent) this.toast('Ошибка: ' + e.message, 'err');
          return false;                          // S10.20-6
        } finally {
          this.saving.delete(item.key);
        }
      },
      // F9 (10.25, ADR-1025-22 D2): удаление ГЛОБАЛЬНОГО секрета — отдельное
      // подтверждаемое действие. Без НОВОГО endpoint (R16):
      //   * `isGlobalSecretKey(key) && BYOK_IMAGE_KEY_ENABLED` →
      //     существующий `DELETE /api/config/keys/own/{key}` (глобальная ветка
      //     safe-эндпоинта + аудит `record_global_secret_audit`);
      //   * иначе → F0 write-path empty-write: `persistItems([{key,value:'',…}])`
      //     → global POST /api/config. Пусто = «не настроен» (`_mask_secret`).
      // `DELETE /api/config/chat/{key}` НЕ используем (это сброс override).
      deleteKeyItem: async function (item) {
        var key = (typeof item === 'string') ? item : (item && item.key);
        if (!key) return false;
        var it = (typeof this._findConfigItem === 'function')
          ? this._findConfigItem(key) : null;
        var title = (item && item.title) || (it && it.title) || key;
        if (!window.confirm('Удалить секрет «' + title + '»? Ключ станет '
                            + '«не настроен», отменить нельзя.')) {
          return false;
        }
        try {
          var flagOn = (typeof this.uiFlag === 'function')
            ? this.uiFlag('BYOK_IMAGE_KEY_ENABLED') : true;
          if (isGlobalSecretKey(key) && flagOn) {
            // H-F9S-1: `global:true` — иначе `api()` подставит `X-Chat-Id`
            // (выбранный чат) → сервер уйдёт в chat-ветку → `delete_chat_key`
            // (whitelist = `{keys.llm_api_key}`) → ValueError/HTTP 422. Паритет
            // с `saveProviderSecret` (`global:true`) и ADR-1025-22 D2.
            await this.api('/api/config/keys/own/' + encodeURIComponent(key),
                           { method: 'DELETE', global: true });
          } else if (typeof this.persistItems === 'function') {
            var perChat = it ? it.per_chat : undefined;
            var opId = 'del-' + (++this._opSeq);
            var res = await this.persistItems(
              [{ key: key, value: '', per_chat: perChat }],
              { operationId: opId, silent: true });
            if (!res || res.state !== 'saved'
                || (res.failed || []).length || (res.skipped || []).length) {
              this.toast('Не удалось удалить: ' + title, 'err');
              return false;
            }
          } else {
            // Легаси-контекст без единого write-path (юнит-тесты).
            await this.api('/api/config', {
              method: 'POST',
              body: JSON.stringify({ items: [{ key: key, value: '' }],
                                     updated_at: null }),
              global: true,
            });
          }
          if (this.keyDrafts) delete this.keyDrafts[key];
          if (this.blockDrafts) delete this.blockDrafts[key];
          this.toast('Удалено: ' + title, 'ok');
          if (typeof this._preserveScroll === 'function' && this.loadConfig) {
            await this._preserveScroll(this.loadConfig);
          }
          return true;
        } catch (e) {
          this.toast('Ошибка удаления: ' + ((e && e.message) || e), 'err');
          return false;
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
        // 10.10 (п.5, ADR-1010-3): аватар+ник — blob через прокси
        // (photo_file_id != null; без прямых <img src>). Себе подставляем
        // имя из initData, если сервер не отдал. Негатив (нет blob/401/404)
        // помечаем avatarSkipped — повторная loadAdmins не долбит прокси.
        var self = this;
        (this.admins || []).forEach(function (a) {
          if (self.me && a.telegram_id === self.me.telegram_id
              && !a.display_name) {
            a.display_name = self.me.first_name || self.me.username || null;
          }
          if (a.photo_file_id != null && !a.avatarUrl && !a.avatarSkipped) {
            self.loadAvatar('user', a.telegram_id, a).then(function (url) {
              if (!url) a.avatarSkipped = true;
            });
          }
        });
      },
      // 10.10 (п.5): инициал админа — переиспользует общий avatarInitial
      // (единая графем-логика); без имени — первый символ ID (fallback).
      adminInitial: function (admin) {
        if (!admin) return '?';
        var initial = this.avatarInitial({
          user_id: admin.telegram_id,
          name: admin.display_name,
        });
        if (initial && initial !== '?') return initial;
        var idStr = admin.telegram_id != null ? String(admin.telegram_id) : '';
        return idStr ? idStr.charAt(0) : '?';
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
      // ═══ OD15/T-1142 (раунд 10.5): rename/delete ролей ═══
      // superuser — абсолютная защита (UI disabled + сервер 403/409).
      isSuperuserRole: function (role) {
        var name = role && role.role_name;
        if (name === 'admin' || name === 'global_admin' || name === 'superuser') {
          return true;
        }
        return !!(role && role.role_type === 'global_admin');
      },
      canEditRole: function (role) {
        // можно rename/delete только пользовательскую (не superuser, не builtin).
        return !this.isSuperuserRole(role)
          && !(role && role.role_type)
          && !!(role && role.is_custom);
      },
      roleRestrictionHint: function (role) {
        if (this.isSuperuserRole(role)) {
          return 'Роль суперпользователя защищена — нельзя переименовать/удалить';
        }
        if (role && role.role_type) {
          return 'Встроенную роль нельзя переименовать/удалить';
        }
        return 'Переименовать/удалить роль';
      },
      renameRole: async function (role) {
        if (!this.canEditRole(role)) return;
        var next = window.prompt('Новое имя роли «' + role.role_name + '»:',
                                 role.role_name);
        if (next == null) return;
        next = String(next).trim();
        if (!next || next === role.role_name) return;
        try {
          await this.api('/api/roles/' + encodeURIComponent(role.role_name)
                         + '/rename',
                         { method: 'POST',
                           body: JSON.stringify({ new_name: next }) });
          this.toast('Роль переименована: ' + role.role_name + ' → ' + next, 'ok');
          await this.loadRoles();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },
      deleteRole: async function (role) {
        if (!this.canEditRole(role)) return;
        if (!window.confirm('Удалить роль «' + role.role_name
                            + '»? Права роли будут удалены.')) return;
        try {
          await this.api('/api/roles/' + encodeURIComponent(role.role_name),
                         { method: 'DELETE' });
          this.toast('Роль удалена: ' + role.role_name, 'ok');
          await this.loadRoles();
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },

      // ═══ OD10/T-1130 (раунд 10.5): визуальная матрица ролей ═══
      // ВСЕ параметры каталога, сгруппированные по секциям мини-аппа
      // (category → group), per-param назначение read/write-ролей.
      loadMatrix: async function () {
        if (!this.isGlobalAdmin) return;
        this.matrixLoading = true;
        this.matrixError = '';
        try {
          var data = await this.api('/api/access/param_permissions');
          this.matrixItems = (data && data.items) || {};
        } catch (e) {
          this.matrixError = 'Не удалось загрузить матрицу: ' + e.message;
          this.matrixItems = {};
        } finally {
          this.matrixLoading = false;
        }
      },
      // D4: матрица группируется по СЕКЦИЯМ мини-аппа (config-вкладки), а не
      // по внутренним категориям каталога. Backend отдаёт `tab`/`tab_title`.
      matrixCategoryTitle: function (cat) {
        var titles = {
          prompts: 'Промпты', models: 'Модели и провайдеры',
          keys: 'API-ключи', limits: 'Лимиты и кулдауны',
          flags: 'Флаги модулей', reactions: 'Реакции и персоны',
          content: 'Контент', memory: 'Память',
        };
        return titles[cat] || cat;
      },
      // F6 (ADR-1018-6 D4): матрица группируется по ФАКТИЧЕСКИМ разделам
      // мини-аппа (nav → секция → группа → параметр). Backend отдаёт
      // аддитивные nav/nav_title/nav_order; TAB_SECTION_ORDER — порядок
      // секций внутри nav (fallback при отсутствии nav).
      matrixSections: function () {
        var items = this.matrixItems || {};
        var q = (this.matrixSearch || '').toLowerCase();
        var byNav = {};
        Object.keys(items).forEach(function (key) {
          var it = items[key];
          if (q && key.toLowerCase().indexOf(q) < 0
              && (it.title || '').toLowerCase().indexOf(q) < 0) return;
          var navId = it.nav || 'other';
          if (!byNav[navId]) {
            var navOrder = (typeof it.nav_order === 'number') ? it.nav_order
              : NAV_GROUP_ORDER.indexOf(navId);
            byNav[navId] = {
              id: navId,
              title: it.nav_title || NAV_GROUP_TITLES[navId] || 'Прочее',
              order: navOrder < 0 ? 999 : navOrder,
              sections: {},
            };
          }
          var nav = byNav[navId];
          var secId = it.tab || ('cat:' + (it.category || 'other'));
          if (!nav.sections[secId]) {
            nav.sections[secId] = {
              id: secId, title: it.tab_title || null,
              category: it.category || 'other', groups: {},
            };
          }
          var gid = it.group || 'other';
          if (!nav.sections[secId].groups[gid]) {
            nav.sections[secId].groups[gid] = {
              id: gid, title: it.group_title || gid,
              order: it.group_order || 999, items: [],
            };
          }
          nav.sections[secId].groups[gid].items.push({ key: key, item: it });
        });
        var self = this;
        return Object.keys(byNav).map(function (nid) {
          var nav = byNav[nid];
          nav.sections = Object.keys(nav.sections).map(function (sid) {
            var sec = nav.sections[sid];
            if (!sec.title) sec.title = self.matrixCategoryTitle(sec.category);
            sec.groups = Object.keys(sec.groups).map(function (g) {
              var grp = sec.groups[g];
              grp.items.sort(function (a, b) { return a.key < b.key ? -1 : 1; });
              return grp;
            }).sort(function (a, b) {
              return (a.order - b.order) || (a.id < b.id ? -1 : 1);
            });
            sec.order = TAB_SECTION_ORDER.indexOf(sec.id);
            sec.count = sec.groups.reduce(function (n, g) {
              return n + g.items.length;
            }, 0);
            return sec;
          }).sort(function (a, b) {
            var ao = a.order < 0 ? 999 : a.order;
            var bo = b.order < 0 ? 999 : b.order;
            return (ao - bo) || (a.id < b.id ? -1 : 1);
          });
          nav.count = nav.sections.reduce(function (n, s) {
            return n + s.count;
          }, 0);
          return nav;
        }).sort(function (a, b) {
          return (a.order - b.order) || (a.id < b.id ? -1 : 1);
        });
      },
      matrixChecked: function (item, field, role) {
        return arr(item && item[field]).indexOf(role) >= 0;
      },
      matrixRoleToggle: async function (key, field, role) {
        var item = this.matrixItems[key];
        if (!item) return;
        var domain = ['user', 'moderator', 'local_admin'];
        var view = arr(item.view_roles).slice();
        var edit = arr(item.edit_roles).slice();
        var target = (field === 'view_roles') ? view : edit;
        var i = target.indexOf(role);
        if (i >= 0) target.splice(i, 1); else target.push(role);
        var allowed = view.concat(edit);   // запись подразумевает чтение
        var body = {
          view_roles: domain.filter(function (r) { return allowed.indexOf(r) >= 0; }),
          edit_roles: domain.filter(function (r) { return edit.indexOf(r) >= 0; }),
        };
        this.matrixSaving[key] = true;
        try {
          var resp = await this.api(
            '/api/access/param_permissions/' + encodeURIComponent(key),
            { method: 'PUT', body: JSON.stringify(body) });
          this.matrixItems[key] = Object.assign({}, item, {
            view_roles: resp.view_roles || body.view_roles,
            edit_roles: resp.edit_roles || body.edit_roles,
            default: false,
          });
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        } finally {
          this.matrixSaving[key] = false;
        }
      },
      matrixReset: async function (key) {
        try {
          await this.api('/api/access/param_permissions/' + encodeURIComponent(key),
                         { method: 'DELETE' });
          this.toast('Сброшено на дефолт: ' + key, 'ok');
          await this.loadMatrix();
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
      // §15/C2 (ADR-1025-12 D4): ЧИСТАЯ машина состояний (юнит-тестируема).
      // sample: {cpu,mem,disk — доли 0..1|null, botOk, stale, missing, reason};
      // prev:   {state, ema, dwellPending, dwellCount}. Гистерезис вход≠выход
      // (0.70/0.65; 0.90/0.85) + EMA + dwell (N подряд подтверждающих сэмплов
      // на эскалацию); отсутствие/устаревание данных → UNKNOWN. Без выдуманных
      // метрик/BPM.
      _heartbeatTransition: function (sample, prev) {
        // Dwell: смена tier применяется только после N последовательных
        // подтверждающих сэмплов при УЖЕ установившемся состоянии (EMA была) —
        // одиночный выброс не меняет состояние. Де-эскалация, первый сэмпл
        // (EMA ещё не было), выход из UNKNOWN и отказ бота — сразу (восстановление
        // и критический отказ не маскируются).
        var DWELL_N = 2;
        var state = (prev && prev.state) || 'unknown';
        var ema = (prev && typeof prev.ema === 'number') ? prev.ema : null;
        var dwellPending = (prev && prev.dwellPending) || null;
        var dwellCount = (prev && prev.dwellCount) || 0;
        if (!sample || sample.missing || sample.stale) {
          return {
            state: 'unknown', ema: ema, dwellPending: null, dwellCount: 0,
            reason: (sample && sample.reason) ||
              ((sample && sample.stale) ? 'телеметрия устарела' : 'нет данных'),
          };
        }
        var vals = [];
        if (typeof sample.cpu === 'number') vals.push(sample.cpu);
        if (typeof sample.mem === 'number') vals.push(sample.mem);
        if (typeof sample.disk === 'number') vals.push(sample.disk);
        if (!vals.length) {
          return { state: 'unknown', ema: ema, dwellPending: null,
                   dwellCount: 0, reason: 'метрик нет' };
        }
        var m = Math.max.apply(null, vals);
        var hadEma = (ema != null);
        ema = hadEma ? (0.4 * m + 0.6 * ema) : m;
        var rank = { unknown: 0, healthy: 1, warning: 2, critical: 3 };
        var target;
        if (sample.botOk === false) {
          target = 'critical';
        } else if (state === 'critical') {
          target = (ema >= 0.85) ? 'critical' : (ema >= 0.65 ? 'warning' : 'healthy');
        } else if (state === 'warning') {
          target = (ema >= 0.90) ? 'critical' : (ema >= 0.65 ? 'warning' : 'healthy');
        } else {
          target = (ema >= 0.90) ? 'critical' : (ema >= 0.70 ? 'warning' : 'healthy');
        }
        var next = target;
        var pending = null;
        var count = 0;
        var escalate = rank[target] > rank[state];
        if (sample.botOk !== false && escalate && hadEma && state !== 'unknown') {
          count = (dwellPending === target) ? (dwellCount + 1) : 1;
          if (count >= DWELL_N) {
            next = target; pending = null; count = 0;
          } else {
            next = state; pending = target;
          }
        }
        var pct = Math.round(ema * 100);
        var reason;
        if (next === 'critical') {
          reason = (sample.botOk === false) ? 'бот не работает'
            : ('критическая нагрузка ' + pct + '%');
        } else if (next === 'warning') {
          reason = 'повышенная нагрузка ' + pct + '%';
        } else if (next === 'healthy') {
          reason = 'нагрузка в норме ' + pct + '%';
        } else {
          reason = 'нет данных';
        }
        if (pending) reason += ' — подтверждение';
        return { state: next, ema: ema, dwellPending: pending,
                 dwellCount: count, reason: reason };
      },
      // Снимок телеметрии §15 из УЖЕ полученного /api/status (без сети здесь).
      // «missing» (поля НЕТ → UNKNOWN с причиной) отделено от «bad» (поле есть,
      // но значение плохое → CRITICAL): `polling_error`/не-running → CRITICAL;
      // отсутствие `bot.state`/`generated_at` → UNKNOWN, а не «свежо»/не «0».
      heartbeatSample: function () {
        var s = this.statusData;
        if (!s) return { missing: true, reason: 'нет данных' };
        var bot = s.bot || null;
        if (!bot || !bot.state) {
          return { missing: true, reason: 'нет состояния бота' };
        }
        var server = s.server || null;
        if (!server) {
          return { missing: true, reason: 'нет данных телеметрии' };
        }
        var sample = { missing: false, stale: false };
        var gen = (s.uptime && s.uptime.generated_at) || null;
        if (!gen) {
          // §15: без отметки времени актуальность неизвестна → UNKNOWN.
          sample.stale = true;
          sample.reason = 'нет отметки времени';
        } else {
          var t = Date.parse(gen);
          // stale: снимок старше 2× интервала поллинга (30 с) → UNKNOWN (§15).
          if (!isNaN(t) && (Date.now() - t) > 120000) {
            sample.stale = true;
            sample.reason = 'телеметрия устарела';
          }
        }
        // bad (значение есть, но бот не в рабочем состоянии) → CRITICAL.
        if (bot.state === 'polling_error') sample.botOk = false;
        else sample.botOk = (bot.state === 'running' || bot.state === 'polling');
        var cpu = Number(server.cpu_percent);
        var mem = (server.memory && server.memory.percent != null)
          ? Number(server.memory.percent) : NaN;
        var disk = (server.disk && server.disk.percent != null)
          ? Number(server.disk.percent) : NaN;
        if ((isNaN(cpu) || cpu <= 0) && Array.isArray(server.loadavg) &&
            server.loadavg.length) {
          var cores = Number(server.cpu_count) || 1;
          var la = Number(server.loadavg[0]);
          if (!isNaN(la)) cpu = (la / cores) * 100;
        }
        var clamp = function (v) {
          return isNaN(v) ? null : Math.max(0, Math.min(1, v / 100));
        };
        sample.cpu = clamp(cpu);
        sample.mem = clamp(mem);
        sample.disk = clamp(disk);
        if (sample.cpu == null && sample.mem == null && sample.disk == null) {
          sample.missing = true;
        }
        return sample;
      },
      // Телеметрия → сглаженное состояние; рендер читает готовый снимок.
      _applyHeartbeatSample: function (sample) {
        var res = this._heartbeatTransition(sample, {
          state: this.hbState, ema: this.hbEma,
          dwellPending: this.hbDwellPending, dwellCount: this.hbDwellCount,
        });
        this.hbEma = res.ema;
        this.hbReason = res.reason;
        this.hbDwellPending = res.dwellPending || null;
        this.hbDwellCount = res.dwellCount || 0;
        if (res.state !== this.hbState) this.hbState = res.state;
        // Перерисовка/возобновление цикла при обновлении снимка: reduced-motion
        // — статичный кадр; иначе — (пере)запуск rAF (в т.ч. если канвас был
        // размонтирован из-за ошибки/смены вкладки и вернулся).
        if (this._prefersReducedMotion()) this._hbScheduleDraw();
        else this.startHeartbeatCanvas();
      },
      // §15/C2 (T-2602): тултип hover (desktop) / tap (mobile).
      toggleHeartbeatTip: function () { this.hbTipOpen = !this.hbTipOpen; },
      showHeartbeatTip: function () { this.hbTipOpen = true; },
      hideHeartbeatTip: function () { this.hbTipOpen = false; },
      // §15/C2 (T-2599/T-2604): Canvas 2D + rAF (WebGL запрещён). Вне
      // Canvas-окружения/при reduced-motion — статичный кадр без цикла.
      // T-2599 (MEDIUM): цикл живёт ТОЛЬКО на вкладке «Статус» — вне неё
      // останавливается (не крутим 60 fps в фоне). $nextTick — канвас монтируется
      // по v-if/смене вкладки; на reduced-motion рисуем статичный кадр после
      // монтирования (не остаётся пустого канваса при возврате).
      startHeartbeatCanvas: function () {
        if (!this.heartbeatCanvasEnabled) return;
        if (this.activeTab && this.activeTab !== 'status') return;
        if (typeof window === 'undefined' || !window.requestAnimationFrame) return;
        if (this.hbCanvasRaf) return;
        var self = this;
        var go = function () {
          if (self.hbCanvasRaf) return;
          if (self.activeTab && self.activeTab !== 'status') return;
          if (self._prefersReducedMotion()) { self._hbDraw(0); return; }
          self.hbCanvasRaf = window.requestAnimationFrame(function (ts) {
            self._hbFrame(ts);
          });
        };
        if (typeof this.$nextTick === 'function') this.$nextTick(go);
        else go();
      },
      stopHeartbeatCanvas: function () {
        if (this.hbCanvasRaf && typeof window !== 'undefined' &&
            window.cancelAnimationFrame) {
          window.cancelAnimationFrame(this.hbCanvasRaf);
        }
        this.hbCanvasRaf = null;
      },
      // Телеметрия обновилась без активного rAF (reduced-motion) → статика.
      _hbScheduleDraw: function () {
        if (!this.heartbeatCanvasEnabled) return;
        if (!this.hbCanvasRaf) this._hbDraw(this.hbLastDraw || 0);
      },
      // HOTFIX9 D7 (T-2831/T-2832, ADR-1025-17): при смене viewport/fullscreen
      // canvas мог схлопнуться/потерять размер — перерисовываем кадр по фактическим
      // clientWidth/clientHeight (дизайн/цвета/пороги/алгоритм НЕ меняются).
      _hbResize: function () {
        if (!this.heartbeatCanvasEnabled) return;
        if (this.activeTab && this.activeTab !== 'status') return;
        this._hbScheduleDraw();
        this.startHeartbeatCanvas();
      },
      _hbFrame: function (ts) {
        this.hbCanvasRaf = null;
        if (typeof document !== 'undefined' && document.hidden) return;
        // T-2599 (MEDIUM): канвас не смонтирован / вкладка не «Статус» —
        // кадр НЕ перепланируем (цикл останавливается, а не висит вхолостую).
        var cv = this.$refs && this.$refs.hbCanvas;
        if (!cv || (this.activeTab && this.activeTab !== 'status')) return;
        this._hbDraw(ts);
        if (!this._prefersReducedMotion() && typeof window !== 'undefined' &&
            window.requestAnimationFrame) {
          var self = this;
          this.hbCanvasRaf = window.requestAnimationFrame(function (t) {
            self._hbFrame(t);
          });
        }
      },
      // ═══ HOTFIX7 (ADR-1025-13 D2): premium-рендер сердцебиения ═══
      // Форма сигнала — реалистичный кардиокомплекс P/Q/R/S/T (сумма гауссиан),
      // НЕ синусоида. Развёртка sweep-wipe: луч идёт слева-вправо; позади —
      // яркая трасса, впереди — приглушённая изолиния; «плавающей точки» и
      // горизонтального переноса линии нет. Число комплексов/период — от
      // состояния (не от выдуманного BPM). Свечение ограничено, есть дыхание
      // яркости. Семантика `_heartbeatTransition`/`heartbeatSample` не меняется.
      _hbEcg: function (u) {
        var g = function (x, mu, sigma, a) {
          var d = (x - mu) / sigma;
          return a * Math.exp(-0.5 * d * d);
        };
        return g(u, 0.180, 0.030, 0.08)    // P
             + g(u, 0.340, 0.012, -0.10)   // Q
             + g(u, 0.365, 0.011, 1.00)    // R
             + g(u, 0.390, 0.013, -0.22)   // S
             + g(u, 0.550, 0.045, 0.20);   // T
      },
      _hbRgba: function (color, alpha) {
        var s = String(color || '').trim();
        var m = /^#([0-9a-fA-F]{6})$/.exec(s);
        if (m) {
          var h = m[1];
          return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' +
            parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) +
            ',' + alpha + ')';
        }
        var r = /^rgba?\(([^)]+)\)$/.exec(s);
        if (r) {
          var parts = r[1].split(',').map(function (p) { return p.trim(); });
          return 'rgba(' + parts[0] + ',' + parts[1] + ',' + parts[2] +
            ',' + alpha + ')';
        }
        return s;
      },
      // Цвет состояния — из СТАТУС-токенов §8 (--ok/--warn/--err/--text-3; тот же
      // источник, что у бейджа `.hb-<state>` — review F-3) через getComputedStyle
      // ОДНОКРАТНО на смену состояния (кэш) с фолбэками единого источника.
      // Интенсивность свечения — лестница по состоянию (CRITICAL заметно сильнее,
      // UNKNOWN без glow) — review F-4.
      _hbPalette: function (st) {
        if (this._hbPaletteState === st && this._hbPaletteCache) {
          return this._hbPaletteCache;
        }
        var fallback = {
          healthy: '#3DD68C', warning: '#F6C56F',
          critical: '#F07178', unknown: '#A2B0C6',
        };
        var token = { healthy: '--ok', warning: '--warn',
                      critical: '--err', unknown: '--text-3' };
        var glowAlpha = { healthy: 0.45, warning: 0.60, critical: 0.85,
                          unknown: 0 };
        var core = fallback[st] || fallback.unknown;
        try {
          if (typeof getComputedStyle === 'function' &&
              typeof document !== 'undefined' && document.documentElement) {
            var v = getComputedStyle(document.documentElement)
              .getPropertyValue(token[st] || token.unknown);
            if (v && v.trim()) core = v.trim();
          }
        } catch (e) { /* фолбэк §8 */ }
        var ga = glowAlpha[st];
        if (ga == null) ga = glowAlpha.unknown;
        var pal = { core: core, glow: this._hbRgba(core, ga),
                    glowAlpha: ga };
        this._hbPaletteState = st;
        this._hbPaletteCache = pal;
        return pal;
      },
      // Бледная сетка монитора (alpha ~0.06) — «язык» медицинского прибора.
      _hbDrawGrid: function (ctx, w, h, dpr) {
        if (!ctx || typeof ctx.beginPath !== 'function') return;
        ctx.save();
        ctx.globalAlpha = 0.06;
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = Math.max(0.5, 0.6 * dpr);
        var step = Math.max(8, 26 * dpr);
        for (var x = 0; x <= w; x += step) {
          ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
        }
        for (var y = 0; y <= h; y += step) {
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
        }
        ctx.globalAlpha = 0.10;
        ctx.beginPath(); ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2); ctx.stroke();
        ctx.restore();
      },
      // Premium ECG sweep-wipe. При reduced-motion — один статичный кадр
      // (полная трасса в цвете состояния, без луча/свечения/дыхания).
      _hbDrawPremium: function (ts, ctx, cv, dpr, st) {
        var w = cv.width, h = cv.height, mid = h * 0.5;
        var pal = this._hbPalette(st);
        var reduced = this._prefersReducedMotion();
        var amp = { healthy: 0.34, warning: 0.50, critical: 0.62, unknown: 0.14 };
        var beats = { healthy: 3, warning: 4, critical: 5, unknown: 2 };
        var period = { healthy: 4.2, warning: 3.1, critical: 2.2, unknown: 7.0 };
        var a = amp[st] || amp.unknown;
        var n = beats[st] || beats.unknown;
        var sweep = period[st] || period.unknown;
        var t = (ts || 0) / 1000;
        var self = this;
        var traceY = function (x) {
          var u = (x / (w || 1)) * n;
          var frac = u - Math.floor(u);
          return mid - self._hbEcg(frac) * (h * 0.42) * a;
        };
        var step = Math.max(1, 2 * dpr);
        ctx.clearRect(0, 0, w, h);
        this._hbDrawGrid(ctx, w, h, dpr);
        var beatFrac = reduced ? 0 : ((t / sweep) * n) % 1;
        var head = reduced ? w : ((t / sweep) % 1) * w;
        var breath = reduced ? 1 : (0.72 + 0.28 * Math.sin(t * 2 * Math.PI * 0.15));
        // F-4/review: множитель свечения по состоянию (CRITICAL ×1.5, UNKNOWN 0).
        var glowScale = { healthy: 0.9, warning: 1.1, critical: 1.5, unknown: 0 };
        var gs = glowScale[st];
        if (gs == null) gs = 0;
        var glow = (st === 'unknown') ? 0
          : Math.round(Math.max(6, Math.round(9 * dpr * (a + 0.4))) * gs);
        var x;
        // 1) приглушённая базовая изолиния на весь проход.
        ctx.save();
        ctx.globalAlpha = reduced ? 0.6 : (0.22 * breath);
        ctx.strokeStyle = pal.core;
        ctx.lineWidth = Math.max(1, 1.2 * dpr);
        ctx.beginPath();
        for (x = 0; x <= w; x += step) {
          var y0 = traceY(x);
          if (x === 0) ctx.moveTo(x, y0); else ctx.lineTo(x, y0);
        }
        ctx.stroke();
        ctx.restore();
        // 2) яркая трасса позади луча (sweep-wipe).
        ctx.save();
        ctx.globalAlpha = reduced ? 1 : breath;
        ctx.strokeStyle = pal.core;
        ctx.lineWidth = Math.max(1.6, 2.2 * dpr);
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        if (glow) { ctx.shadowBlur = glow; ctx.shadowColor = pal.glow; }
        ctx.beginPath();
        for (x = 0; x <= head; x += step) {
          var y1 = traceY(x);
          if (x === 0) ctx.moveTo(x, y1); else ctx.lineTo(x, y1);
        }
        ctx.stroke();
        ctx.restore();
        if (reduced) return;
        // 3) «голова» луча + вспышка-взрыв на R-пике (затухание ≈0.35 c).
        ctx.save();
        ctx.globalAlpha = 0.9 * breath;
        ctx.fillStyle = pal.core;
        if (glow) { ctx.shadowColor = pal.glow; ctx.shadowBlur = glow; }
        ctx.beginPath();
        ctx.arc(head, traceY(head), Math.max(1.5, 2 * dpr), 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        var dR = Math.abs(beatFrac - 0.365);
        if (dR < 0.05 && typeof ctx.createRadialGradient === 'function') {
          var burst = 1 - (dR / 0.05);
          var rad = (10 + 16 * burst) * dpr;
          var hy = traceY(head);
          var grd = ctx.createRadialGradient(head, hy, 0, head, hy, rad);
          grd.addColorStop(0, pal.glow);
          grd.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.save();
          ctx.globalAlpha = Math.min(0.9, pal.glowAlpha * 1.1) * burst * breath;
          ctx.fillStyle = grd;
          ctx.beginPath();
          ctx.arc(head, hy, rad, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
      },
      // Canvas-legacy (UI_HEARTBEAT_PREMIUM=false): прежний рендер — бегущая
      // синусоида + сдвигающийся отрезок-импульс (мягкий откат D2 без редеплоя).
      _hbDrawLegacy: function (ts, ctx, cv, dpr, st) {
        var colors = { healthy: '#3DD68C', warning: '#F6C56F',
                       critical: '#EF4444', unknown: '#A2B0C6' };
        var freq = { healthy: 1, warning: 2, critical: 3, unknown: 0.6 };
        var amp = { healthy: 0.35, warning: 0.6, critical: 0.9, unknown: 0.12 };
        var col = colors[st] || colors.unknown;
        var t = (ts || 0) / 1000;
        var w = cv.width, h = cv.height, mid = h / 2;
        ctx.clearRect(0, 0, w, h);
        ctx.strokeStyle = col;
        ctx.lineWidth = Math.max(1.5, 2 * dpr);
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        var step = 4 * dpr;
        for (var x = 0; x <= w; x += step) {
          var phase = (x / (w || 1)) * Math.PI * 2 * 3;
          var y = mid - Math.sin(phase + t * (freq[st] || 1)) *
                  (h * 0.5) * (amp[st] || 0.2);
          if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        // Импульс: частота зависит от состояния (характер, не только цвет).
        ctx.globalAlpha = 0.9;
        ctx.beginPath();
        var span = (st === 'unknown') ? 1e9
          : (st === 'critical' ? 600 : (st === 'warning' ? 1000 : 1500));
        var headX = (((t * 1000) % span) / span) * w;
        ctx.moveTo(headX, mid);
        ctx.lineTo(Math.min(w, headX + 6 * dpr), mid);
        ctx.stroke();
        ctx.globalAlpha = 1;
      },
      // Рисование только готового снимка состояния (сеть в кадре отсутствует).
      _hbDraw: function (ts) {
        var cv = this.$refs && this.$refs.hbCanvas;
        if (!cv || typeof cv.getContext !== 'function') return;
        var ctx = cv.getContext('2d');
        if (!ctx) return;
        var dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
        if (dpr > 2) dpr = 2;   // D2.5: DPR cap = 2 (перф-бюджет)
        var cssW = cv.clientWidth || 320, cssH = cv.clientHeight || 56;
        if (cv.width !== Math.round(cssW * dpr)) cv.width = Math.round(cssW * dpr);
        if (cv.height !== Math.round(cssH * dpr)) {
          cv.height = Math.round(cssH * dpr);
        }
        var st = this.hbState || 'unknown';
        if (this.heartbeatPremium === false) {
          this._hbDrawLegacy(ts, ctx, cv, dpr, st);
        } else {
          this._hbDrawPremium(ts, ctx, cv, dpr, st);
        }
        this.hbLastDraw = ts || 0;
      },
      loadStatus: async function () {
        var epoch = this.scopeEpoch;   // D2: снимок scope (permsoc-телеметрия per chat)
        try {
          var st = await this.api('/api/status');
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.statusData = st;
          this.statusError = null;
          // hotfix6/C2 (ADR-1025-12 D4): телеметрия §15 ОТДЕЛЕНА от рендера.
          // Обновляем снимок состояния из УЖЕ полученного /api/status (30 с,
          // app.js::startStatusPolling) — новый поллер не вводим, сеть в кадре
          // requestAnimationFrame отсутствует.
          this._applyHeartbeatSample(this.heartbeatSample());
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
          // §15: недоступность API → UNKNOWN (не «0»).
          this._applyHeartbeatSample({ missing: true });
        }
        // F6 (ADR-1025-19 D5/§21): компактное превью последнего вызова на
        // Статусе (global admin). Отдельный лёгкий путь — только /usage/latest;
        // источник и компонент у F6, композиция витрины §11–§20 — у F11.
        if (this.isGlobalAdmin) {
          this.loadExecPreview();
          // F11 (§19/D5): бюджеты/факты — на СУЩЕСТВУЮЩИХ путях (без новых
          // поллеров; переиспользуем ритм статус-поллинга 30с).
          this.loadBudgetInfo();
          this.loadDossierFeed();
        }
        // F11 (§20/D5): счётчики ошибок/предупреждений (viewer не тронут).
        this.loadLogCounts();
        // hotfix6/C2 (T-2599): EKG-SVG заменён на Canvas 2D + rAF (флаг
        // UI_HEARTBEAT_CANVAS_ENABLED; OFF → прежний SVG байт-в-байт).
        this.loadKeyHistory();   // B1/T-1129: список + график доступности
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
        if (!health || health.status === 'not_configured') return 'badge-muted';
        if (health.ok || health.status === 'ok') return 'badge-ok';
        if (health.status === 'error') return 'badge-err';
        if (health.status === 'timeout' || health.status === 'unreachable') {
          return 'badge-warn';
        }
        return 'badge-muted';
      },
      // 10.9 (п.7.1): человеческий статус реального health-probe.
      healthLabel: function (health) {
        if (!health) return '—';
        return {
          ok: 'OK', timeout: 'Таймаут', error: 'Ошибка',
          unreachable: 'Недоступен', not_configured: 'Не настроен',
        }[health.status] || health.status;
      },

      // ═══ B1/OD8 (T-1128/T-1129): доступность ключей ═══
      loadKeyHistory: async function () {
        try {
          this.keyHistory = await this.api('/api/status/key-history');
        } catch (e) {
          this.keyHistory = null;   // empty-state по инварианту §8
        }
        this.$nextTick(this.renderKeyHistoryChart);
      },
      // Последний сэмпл провайдера (для компактной строки списка).
      latestSample: function (prov) {
        var arr = (prov && prov.samples) || [];
        return arr.length ? arr[arr.length - 1] : null;
      },
      // Индикатор: 2xx → ok; 429/5xx/network → err; прочие 4xx/not_config → warn.
      availabilityClass: function (sample) {
        if (!sample) return 'none';
        var code = sample.http_status;
        if (sample.ok || (code != null && code >= 200 && code < 300)) return 'ok';
        if (code == null || code === 429 || code >= 500) return 'err';
        return 'warn';
      },
      availabilityCode: function (sample) {
        if (!sample || sample.http_status == null) return '—';
        return String(sample.http_status);
      },
      // 10.10 (п.2, ADR-1010-2): чистая модель графика — юнит-тестируемая.
      // Каждый провайдер — своя дорожка (ок = i+0.75 / err = i+0.25),
      // общая временная сетка (шаг 5 мин, минимум 1 час), пропущенные слоты
      // = null. Провайдеры есть, но сэмплов нет (или вход пуст) → null:
      // чарт не строится, пустое состояние не ломается.
      keyHistoryChartModel: function (providers) {
        var list = (providers || []).filter(function (p) { return p; });
        if (!list.length) return null;
        var anySample = list.some(function (p) {
          return (p.samples || []).length > 0;
        });
        if (!anySample) return null;
        // F2 round 10.25 (ADR-1025-9 D1/T-2536): палитра графиков → §8.
        var palette = ['#42D6C4', '#A78BFA', '#3DD68C', '#F6C56F',
                       '#F07178', '#77A8FF'];
        var endBucket = -Infinity;
        var firstBucket = Infinity;
        list.forEach(function (p) {
          (p.samples || []).forEach(function (s) {
            var ts = Number(s.ts);
            if (!isFinite(ts)) return;
            if (ts > endBucket) endBucket = ts;
            if (ts < firstBucket) firstBucket = ts;
          });
        });
        if (!isFinite(endBucket) || !isFinite(firstBucket)) return null;
        endBucket = Math.floor(endBucket / SAMPLE_BUCKET) * SAMPLE_BUCKET;
        firstBucket = Math.floor(firstBucket / SAMPLE_BUCKET) * SAMPLE_BUCKET;
        // HIGH-1: окно строим ОТ КОНЦА (endBucket — последний элемент):
        // сначала ограничиваем длину MAX_HISTORY_POINTS (minStart), затем
        // гарантируем минимум MIN_BUCKETS и не уходим раньше первого
        // фактического сэмпла. Никаких break/slice — иначе при разреженной
        // истории > 2*MAX_HISTORY_POINTS новейшие сэмплы терялись.
        var minStart = endBucket - (MAX_HISTORY_POINTS - 1) * SAMPLE_BUCKET;
        var startBucket = Math.max(firstBucket, minStart);
        startBucket = Math.min(startBucket,
                               endBucket - (MIN_BUCKETS - 1) * SAMPLE_BUCKET);
        startBucket = Math.max(0, startBucket);
        var grid = [];
        for (var t = startBucket; t <= endBucket; t += SAMPLE_BUCKET) {
          grid.push(t);
        }
        var labels = grid.map(function (ts) {
          var d = new Date(ts * 1000);
          var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
          return pad(d.getHours()) + ':' + pad(d.getMinutes());
        });
        var datasets = list.map(function (p, idx) {
          var samples = (p.samples || []).filter(function (s) {
            return isFinite(Number(s.ts));
          });
          var byBucket = {};
          samples.forEach(function (s) {
            var b = Math.floor(Number(s.ts) / SAMPLE_BUCKET) * SAMPLE_BUCKET;
            byBucket[b] = !!s.ok;
          });
          var lane = idx;
          // 10.11 (ADR-1011-3): точки {x(ms), y|lane} — честная линейная
          // время-ось; пропущенный бакет → {x, y:null} (spanGaps тянет шаг).
          var data = grid.map(function (ts) {
            var laneValue = null;
            if (Object.prototype.hasOwnProperty.call(byBucket, ts)) {
              laneValue = byBucket[ts] ? lane + 0.75 : lane + 0.25;
            }
            return { x: ts * 1000, y: laneValue };
          });
          return {
            label: p.module_title || p.provider || p.module_id,
            data: data,
            borderColor: palette[idx % palette.length],
            backgroundColor: palette[idx % palette.length],
            stepped: true,
            tension: 0,
            pointRadius: samples.length <= 1 ? 3 : 0,
            spanGaps: true,      // 10.11: статус «тянется» до следующей точки
          };
        });
        return {
          labels: labels,      // совместимость (рендер идёт по точкам {x,y})
          datasets: datasets,
          laneCount: list.length,
          xMin: grid[0] * 1000,
          xMax: grid[grid.length - 1] * 1000,
          height: Math.max(120, 44 + list.length * 22),
        };
      },
      renderKeyHistoryChart: function () {
        // Рвём предыдущий инстанс в ЛЮБОМ случае (даже при `keyHistory ==
        // null`): иначе Chart.js держит stale-инстанс/слушатели на canvas.
        if (this.keyHistoryChart) {
          this.keyHistoryChart.destroy();
          this.keyHistoryChart = null;
        }
        if (!this.keyHistory) {
          this.keyHistoryChartHeight = 120;
          return;
        }
        var model = this.keyHistoryChartModel(this.keyHistory.providers);
        this.keyHistoryChartHeight = model ? model.height : 120;
        if (!model) return;
        var canvas = this.$refs.keyHistoryCanvas;
        if (!canvas) return;
        var self = this;
        // Высота выставлена реактивно — строим чарт на следующем тике,
        // чтобы canvas получил итоговые размеры обёртки.
        this.$nextTick(function () {
          var el = self.$refs.keyHistoryCanvas;
          if (!el) return;
          var cfg = {
            type: 'line',
            data: { labels: model.labels, datasets: model.datasets },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              // 10.11 (ADR-1011-3): явные {x,y} — без авто-парсинга.
              parsing: false,
              scales: {
                y: { min: -0.2, max: model.laneCount + 0.2,
                     ticks: { display: false } },
                // Честная числовая время-ось (ms) без date-adapter;
                // подписи тиков — HH:MM.
                x: {
                  type: 'linear',
                  min: model.xMin,
                  max: model.xMax,
                  ticks: {
                    color: '#9CA3AF', maxTicksLimit: 6, font: { size: 10 },
                    callback: function (v) {
                      var d = new Date(v);
                      var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
                      return pad(d.getHours()) + ':' + pad(d.getMinutes());
                    },
                  },
                },
              },
              plugins: {
                legend: { display: true, position: 'bottom',
                          labels: { color: '#AAB6C8', boxWidth: 10,
                                    font: { size: 10 } } },
              },
            },
          };
          if (self.keyHistoryChart) { self.keyHistoryChart.destroy(); }
          self.keyHistoryChart = new Chart(el, cfg);
        });
      },

      loadLogs: async function () {
        // F6 (T-1461/§3.2): единый источник истины — селектор, запрос и
        // рендер используют ОДНО значение `logLevel` (дефолт при открытии
        // ERROR+WARNING). Иначе — рассинхрон «в селекторе INFO, в списке ALL».
        var lvl = this.logLevel || 'ERROR+WARNING';
        this.logLevel = lvl;
        this.logsLoading = true;
        try {
          var data = await this.api(
            '/api/status/logs?level=' + encodeURIComponent(lvl) + '&limit=200');
          this.logs = (data.logs || []).map(function (l) { l.expanded = false; return l; });
          this.logsCount = data.count || 0;
          // F-8 (T-871): автоскролл при новых записях. Hotfix-R10: сервер
          // отдаёт НОВЫЕ СВЕРХУ (entries[-limit:][::-1]) — скроллим в ВЕРХ
          // (panel.scrollHeight — старый скролл на ОЛД-записи внизу).
          var self = this;
          this.$nextTick(function () {
            var panel = self.$refs.logPanel;
            if (panel) panel.scrollTop = 0;
          });
        } catch (e) { this.logs = []; }
        finally { this.logsLoading = false; }
      },
      // F11 (§20/D5): счётчики «Ошибки» (только ERROR) и «Предупреждения»
      // (только WARNING) — из СУЩЕСТВУЮЩЕГО /api/status/logs. Поле `count`
      // там ограничено `limit`, поэтому читаем аддитивный `counts` (точные
      // числа по всему ring-буферу, H-F11S-1). Раскрытие/копирование/
      // столбцы/viewer НЕ меняются.
      loadLogCounts: async function () {
        try {
          var res = await this.api('/api/status/logs?level=ALL&limit=1');
          var counts = (res && res.counts) || null;
          this.logErrorCount = counts ? (counts.ERROR || 0) : null;
          this.logWarnCount = counts ? (counts.WARNING || 0) : null;
        } catch (e) {
          this.logErrorCount = null;
          this.logWarnCount = null;
        }
      },
      // F11 (§20/D5): клик по счётчику — плавный скролл к карточке логов.
      // I-F11S-1: `$refs.statusLogs` в разметке нет — мёртвая ветка удалена.
      scrollToLogs: function () {
        var self = this;
        this.$nextTick(function () {
          var el = (typeof document !== 'undefined')
            ? document.getElementById('status-logs') : null;
          if (!el || typeof el.scrollIntoView !== 'function') return;
          try {
            el.scrollIntoView({
              behavior: self.reducedMotion ? 'auto' : 'smooth',
              block: 'start',
            });
          } catch (e) {
            el.scrollIntoView();
          }
        });
      },
      // S7 (ADR-1026-9 D4, §110): маркеры событий Саммари (§108/§109) для
      // клиентского фильтра. `run_id=` — любая строка этапа несёт сквозной id.
      logSummaryMarkers: function () {
        return ['SUMMARY_', 'FILTER_', 'RESTORE_', 'L1_', 'L2_', 'FORMAT_',
                'COVER_', 'TEST_', 'run_id='];
      },
      isSummaryLog: function (log) {
        var msg = (log && log.message) || '';
        var markers = this.logSummaryMarkers();
        for (var i = 0; i < markers.length; i++) {
          if (msg.indexOf(markers[i]) !== -1) return true;
        }
        return false;
      },
      // S7 (§110/D4): понятная формулировка ошибки из кода события; детали
      // (run_id/время/модель/причина) остаются в раскрываемой строке.
      summaryErrorLabel: function (log) {
        var msg = (log && log.message) || '';
        var map = [
          ['L1_ERROR', 'Саммари: ошибка кластеризации'],
          ['L2_ERROR', 'Саммари: ошибка генерации статьи'],
          ['FORMAT_ERROR', 'Саммари: ошибка форматирования'],
          ['COVER_ERROR', 'Саммари: ошибка обложки'],
          ['FILTER_ERROR', 'Саммари: ошибка фильтра'],
          ['RESTORE_ERROR', 'Саммари: ошибка восстановления контекста'],
          ['SUMMARY_FAILED', 'Саммари: прогон не удался'],
        ];
        for (var i = 0; i < map.length; i++) {
          if (msg.indexOf(map[i][0]) !== -1) return map[i][1];
        }
        return '';
      },
      // S7 (§110/D4): переключатель чипа «Саммари». Включение поднимает
      // уровне-фильтр до INFO (INFO-события этапов видны), выключение
      // возвращает прежний уровень, только если его не сменили вручную
      // (L-R1026S7-2: ручной выбор не перетирается); раскрытие/копирование
      // не затрагиваются.
      toggleLogSummary: function () {
        this.logSummaryOnly = !this.logSummaryOnly;
        if (this.logSummaryOnly) {
          this.logLevelBeforeSummary = this.logLevel;
          if (this.logLevel !== 'INFO') {
            this.logLevel = 'INFO';           // watcher перезагрузит лог
            return;
          }
        } else if (this.logLevel === 'INFO' &&
                   this.logLevelBeforeSummary &&
                   this.logLevelBeforeSummary !== 'INFO') {
          this.logLevel = this.logLevelBeforeSummary;  // watcher перезагрузит
          return;
        }
        this.loadLogs();
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
      // 10.8 (3b): компактные ДАТА+ВРЕМЯ «DD.MM HH:MM:SS» — дата снова видна
      // на тач-устройствах, где :title (fmtLogTs) недоступен без hover.
      fmtLogTime: function (ts) {
        if (!ts) return '';
        var d = new Date(ts);
        if (isNaN(d.getTime())) {
          return String(ts).slice(0, 19).replace('T', ' ');
        }
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + ' '
          + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':'
          + pad(d.getSeconds());
      },
      // Раунд 9: формат unix-секунд (users_meta/graph_facts/logs в секундах)
      fmtTs: function (ts) {
        if (!ts) return '—';
        return this.fmtLogTs(new Date(ts * 1000));
      },
      // Раунд 9: русская подпись стадии отношений (спец. зеркало STAGE_RU)
      stageRu: function (stage) {
        var map = {
          stranger: 'нюфаг', acquaintance: 'знакомый',
          regular: 'свой', veteran: 'ветеран',
        };
        return map[stage] || stage || '—';
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
          // BUG-7 (invisible copy field): fallback-execCommand — временный
          // textarea с классом .clipboard-ghost (CSS: fixed left:-9999px,
          // opacity:0, contain:strict — невидим и НЕ ломает раскладку
          // Telegram WebView, но остаётся фокусируемым). 10.7 (3a): узел
          // удаляется в finally — в DOM не остаётся «призрака» у фильтр-строки.
          var ta = document.createElement('textarea');
          ta.className = 'clipboard-ghost';
          ta.setAttribute('readonly', '');
          document.body.appendChild(ta);
          window.__adminbotClipGhost = ta;
          ta.value = text;
          ta.focus({ preventScroll: true });
          ta.select();
          try {
            // execCommand('copy') возвращает boolean и НЕ бросает исключение —
            // проверяем результат (иначе ложный тост «Скопировано»).
            var ok = document.execCommand('copy');
            if (ok) this.toast('Скопировано', 'ok');
            else this.toast('Не удалось скопировать', 'err');
          } catch (e2) {
            this.toast('Не удалось скопировать', 'err');
          } finally {
            ta.remove();
            if (window.__adminbotClipGhost === ta) {
              window.__adminbotClipGhost = null;
            }
          }
        }
      },
      // 10.7 (3c): копирование строки лога по клику + подсветка на 800 мс.
      copyLogRow: function (log, i) {
        this.copiedIndex = i;
        if (this.copiedTimer) clearTimeout(this.copiedTimer);
        var self = this;
        this.copiedTimer = setTimeout(function () {
          self.copiedIndex = null;
          self.copiedTimer = null;
        }, 800);
        this.copyText(this.logText(log));
      },
      copyAllLogs: function () {
        // 10.7 (1a/3c): явная привязка (без потери this в callback).
        var self = this;
        this.copyText(this.logs.map(function (l) {
          return self.logText(l);
        }).join('\n\n'));
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

      // ═══ Справка (84.13) ═══
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
        var raw = html || '';
        if (window.DOMPurify
            && typeof window.DOMPurify.sanitize === 'function') {
          return window.DOMPurify.sanitize(raw);
        }
        // M1: fail-CLOSED — нет санитайзера → рендерим как ЭКРАНИРОВАННЫЙ
        // текст (не сырой HTML).
        console.warn('[adminbot] DOMPurify недоступен — текст без HTML');
        return String(raw)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
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
      // F2 10.16 (ADR-1016-3): force-reset справки к код-канону (RBAC
      // edit_info). Прежний текст бэкапится в prev_html на стороне бэкенда.
      resetInfoCanon: async function () {
        if (!window.confirm('Сбросить текст справки к канону из кода? '
            + 'Текущий текст сохранится в бэкапе.')) return;
        try {
          var data = await this.api('/api/info/reset-canon', { method: 'POST' });
          this.infoMeta = Object.assign({}, this.infoMeta, data, {
            canon_drift: false,
          });
          await this.loadInfo();
          this.editingInfo = false;
          this.toast('Справка сброшена к канону', 'ok');
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },

      // ═══ F6 (help-guide-integration-round1014): гайд по возможностям ═══
      // Markdown-редактор + предпросмотр; хранение — PG (/api/info/guide).
      loadGuide: async function () {
        this.guideLoading = true;
        try {
          var data = await this.api('/api/info/guide');
          this.guideHtml = data.markdown || '';
          this.guideMeta = data;
          this.guideDraft = data.markdown || '';
        } catch (e) {
          if (e.status !== 401) this.toast('Не удалось загрузить гайд', 'err');
        } finally {
          this.guideLoading = false;
        }
      },
      toggleGuideEditor: function () {
        this.editingGuide = !this.editingGuide;
        this.guidePreviewing = false;
        this.guideDraft = this.guideHtml || '';
      },
      // Мини-конвертер Markdown→HTML. Сначала ЭКРАНИРУЕТ HTML, затем
      // размечает. Результат ВСЕГДА проходит sanitizeHtml перед v-html.
      renderGuideMarkdown: function (md) {
        var esc = String(md == null ? '' : md)
          .replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        function inline(s) {
          s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener">$1</a>');
          s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
          s = s.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
          s = s.replace(/\*([^*]+)\*/g, '<i>$1</i>');
          return s;
        }
        var lines = esc.split(/\r?\n/);
        var out = [];
        var inList = false;
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          var h = line.match(/^(#{1,6})\s+(.*)$/);
          if (h) {
            if (inList) { out.push('</ul>'); inList = false; }
            var lvl = h[1].length;
            out.push('<h' + lvl + '>' + inline(h[2]) + '</h' + lvl + '>');
            continue;
          }
          var li = line.match(/^\s*[-*]\s+(.*)$/);
          if (li) {
            if (!inList) { out.push('<ul>'); inList = true; }
            out.push('<li>' + inline(li[1]) + '</li>');
            continue;
          }
          if (inList) { out.push('</ul>'); inList = false; }
          if (!line.trim()) continue;
          out.push('<p>' + inline(line) + '</p>');
        }
        if (inList) out.push('</ul>');
        return out.join('');
      },
      saveGuide: async function () {
        var md = this.guideDraft || '';
        if (!md.trim()) { this.toast('Текст пуст', 'warn'); return; }
        try {
          var data = await this.api('/api/info/guide', {
            method: 'POST',
            body: JSON.stringify({ markdown: md }),
          });
          this.guideHtml = md;
          this.guideMeta = data;
          this.editingGuide = false;
          this.guidePreviewing = false;
          this.toast('Сохранено', 'ok');
        } catch (e) {
          this.toast('Ошибка: ' + e.message, 'err');
        }
      },
      // Dedicated API /api/persona (F2): api() сам ставит X-Chat-Id по
      // активному scope (NULL → global). Пустое значение ≠ дефолт: сервер
      // отдаёт values as-is, UI показывает плейсхолдеры. scopeEpoch-гвард
      // отбрасывает устаревшие in-flight ответы при смене чата.
      personaSetField: function (field, value) {
        if (!this.personaDraft) return;
        this.personaDraft[field] = value;
      },
      loadPersona: async function () {
        var epoch = this.scopeEpoch;
        this.personaLoading = true;
        try {
          var data = await this.api('/api/persona');
          if (!this._scopeGuard(epoch)) return;   // D2: scope сменился
          this.personaMeta = data || null;
          var v = (data && data.values) || {};
          this.personaDraft = {
            name: v.name || '',
            biography: v.biography || '',
            system_prompt_overrides: v.system_prompt_overrides || '',
            is_aware_ai: !!v.is_aware_ai,
          };
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          this.personaMeta = null;
          this.personaDraft = null;
          if (e.status !== 401) {
            this.toast('Не удалось загрузить личность: '
              + this.loreErrText(e), 'err');
          }
        } finally {
          if (this._scopeGuard(epoch)) this.personaLoading = false;   // R3
        }
      },
      savePersona: async function () {
        if (!this.personaDraft || this.personaBusy || this.personaDisabled) return;
        var body = {
          name: this.personaDraft.name || '',
          biography: this.personaDraft.biography || '',
          system_prompt_overrides: this.personaDraft.system_prompt_overrides || '',
          is_aware_ai: !!this.personaDraft.is_aware_ai,
          // H1/F2 §5: optimistic-токен строки персоны (GET отдаёт updated_at).
          updated_at: (this.personaMeta && this.personaMeta.updated_at) || null,
        };
        this.personaBusy = true;
        try {
          var data = await this.api('/api/persona', {
            method: 'PUT',
            body: JSON.stringify(body),
          });
          // PUT отдаёт {scope, chat_id, values, is_global}; persona_enabled
          // приходит только из GET — мёржим, не теряем индикатор флага.
          this.personaMeta = Object.assign({}, this.personaMeta || {}, data || {});
          this.toast('Личность сохранена', 'ok');
        } catch (e) {
          if (e.status === 409) {
            this.toast('Конфликт версии (409) — перезагрузите', 'warn');
            await this.loadPersona();
          } else if (e.status === 403) {
            this.toast('Нет права edit_persona', 'err');
          } else if (e.status !== 401) {
            this.toast('Ошибка сохранения: ' + this.loreErrText(e), 'err');
          }
        } finally {
          this.personaBusy = false;
        }
      },
      resetPersona: async function () {
        // Сброс доступен только для chat-scope (DELETE per-chat override →
        // наследование глобальной личности). Global override не удаляем.
        if (this.activeChatId == null || this.personaBusy) return;
        if (!window.confirm('Сбросить личность этого чата к глобальной?')) return;
        this.personaBusy = true;
        try {
          await this.api('/api/persona', { method: 'DELETE' });
          this.toast('Сброшено к глобальному', 'ok');
          await this.loadPersona();
        } catch (e) {
          if (e.status === 404) {
            this.toast('Override не задан — уже унаследовано', 'warn');
            await this.loadPersona();
          } else if (e.status === 403) {
            this.toast('Нет права edit_persona', 'err');
          } else if (e.status !== 401) {
            this.toast('Ошибка сброса: ' + this.loreErrText(e), 'err');
          }
        } finally {
          this.personaBusy = false;
        }
      },

      // ═══ Лор чатов (round 7, spec §3.10/E2; Q6/Q8) ═══
      loreErrText: function (e) {
        var d = e && e.message;
        if (d && typeof d === 'object') {
          if (d.code) return 'код: ' + d.code;
          return String(d);
        }
        return d ? String(d) : ('HTTP ' + ((e && e.status) || '?'));
      },

      // Список доступных чатов (probe для юзеров без секции — раскрывает
      // вкладку per-chat админам; см. canViewTab/3.10).
      loadChats: async function (probe) {
        var self = this;
        this.chatLoreLoading = true;
        try {
          var data = await this.api('/api/chat_lore/chats');
          this.chatLoreChats = Array.isArray(data) ? data : [];
          // UI-полировка TMA: сервер отдаёт title best-effort (бот может
          // быть недоступен/чат без заголовка) — подставляем читаемый
          // дефолт, чтобы список чатов не пустовал заголовками
          this.chatLoreChats.forEach(function (c) {
            if (c && !c.title) c.title = 'Чат ' + c.chat_id;
          });
          // UI-полировка TMA (fix-раунд): аватары чатов — blob через прокси
          // (fetch с X-Telegram-Init-Data; прямой <img src=/api/avatar/*> —
          // 401). Только для строк с photo_file_id != null (сервер сказал,
          // что фото есть) — меньше пустых 404-запросов в прокси.
          this.chatLoreChats.forEach(function (c) {
            if (c && c.chat_id != null && c.photo_file_id != null) {
              self.loadAvatar('chat', c.chat_id, c);
            }
          });
          this.chatLoreError = '';
          // текущий чат «пропал» из списка (403/remap) — сбрасываем профиль;
          // иначе авто-выбор первого чата (удобно per-chat админу с одним)
          var found = this.chatLoreSelectedId != null
            && this.chatLoreChats.some(function (c) {
              return c.chat_id === self.chatLoreSelectedId;
            });
          if (!found) {
            this.chatLoreSelectedId = null;
            this.chatLoreProfile = null;
          }
          if (this.chatLoreSelectedId == null && this.chatLoreChats.length) {
            this.loadProfile(this.chatLoreChats[0].chat_id);
          }
        } catch (e) {
          if (e.status === 403) {
            // 403 в probe — молча: вкладка просто остаётся скрытой (Q6)
            this.chatLoreChats = [];
            this.chatLoreSelectedId = null;
            this.chatLoreProfile = null;
            if (!probe) this.toast('Нет доступа к чатам лора', 'warn');
          } else if (e.status !== 401 && !probe) {
            this.toast('Не удалось загрузить список чатов: '
              + this.loreErrText(e), 'err');
          }
        } finally {
          this.chatLoreLoading = false;
        }
      },

      loadProfile: async function (chatId) {
        if (chatId == null || chatId === '') return;
        var epoch = this.scopeEpoch;   // D2: снимок scope
        this.chatLoreProfileLoading = true;
        this.chatLoreError = '';
        try {
          var p = await this.api('/api/chat_lore/' + chatId);
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.applyLoreProfile(p);
          // C2: список админов грузим вместе с профилем (глобальный admin —
          // остальным секции remap/админов в шаблоне не видны)
          if (this.isGlobalAdmin) this.loadChatAdmins(p.chat_id);
          // F3 (раунд 9): участники и отношения — при каждом выборе чата
          this.loadRelations(p.chat_id);
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          // неудачная загрузка не оставляет «протухший» профиль на экране
          this.chatLoreProfile = null;
          this.chatAdmins = [];
          this.chatRelations = [];
          this.relationsEnabled = false;
          if (e.status === 404) {
            this.chatLoreError = 'Профиль чата ' + chatId + ' не найден (404).';
          } else if (e.status === 403) {
            this.chatLoreError = 'Нет доступа к профилю чата ' + chatId + ' (403).';
          } else if (e.status !== 401) {
            this.chatLoreError = 'Не удалось загрузить профиль чата: '
              + this.loreErrText(e);
          }
        } finally {
          if (this._scopeGuard(epoch)) this.chatLoreProfileLoading = false;   // R3
        }
      },

      // Применение профиля из API к форме. preserveDrafts=true — не трогать
      // черновики текстов (ручной лор могли редактировать в этот момент):
      // используется после saveSettings/clearAuto/авто-прогона.
      applyLoreProfile: function (p, preserveDrafts) {
        if (!p) return;
        this.chatLoreProfile = p;
        this.chatLoreSelectedId = p.chat_id;
        this.loreSettings = {
          auto_enabled: !!p.auto_enabled,
          auto_period_hours: p.auto_period_hours != null ? p.auto_period_hours : 24,
          auto_window_hours: p.auto_window_hours != null ? p.auto_window_hours : 24,
        };
        if (!preserveDrafts) {
          this.loreManual = p.manual_lore || '';
          this.loreAuto = p.auto_lore || '';
        }
      },

      saveManual: async function () {
        var p = this.chatLoreProfile;
        if (!p || this.chatLoreBusy) return;
        if ((this.loreManual || '').length > 4000) {
          this.toast('Ручной лор не длиннее 4000 символов', 'warn');
          return;
        }
        this.chatLoreSaving = true;
        try {
          var saved = await this.api('/api/chat_lore/' + p.chat_id, {
            method: 'PUT',
            body: JSON.stringify({
              manual_lore: this.loreManual || '',
              updated_at: p.updated_at,       // Q8: optimistic-метка в теле
            }),
          });
          this.applyLoreProfile(saved);
          this.toast('Ручной лор сохранён', 'ok');
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.chatLore409 = e.message;     // → модалка «Перезагрузить?»
            return;
          }
          this.toast('Ошибка сохранения: ' + this.loreErrText(e), 'err');
        } finally {
          this.chatLoreSaving = false;
        }
      },

      saveSettings: async function () {
        var p = this.chatLoreProfile;
        if (!p || this.chatLoreBusy) return;
        var period = parseInt(this.loreSettings.auto_period_hours, 10);
        var win = parseInt(this.loreSettings.auto_window_hours, 10);
        if (!isFinite(period) || period < 1 || period > 720
            || !isFinite(win) || win < 1 || win > 720) {
          this.toast('Период и окно — числа от 1 до 720 часов', 'warn');
          return;
        }
        this.chatLoreSaving = true;
        try {
          var saved = await this.api(
            '/api/chat_lore/' + p.chat_id + '/settings', {
              method: 'PUT',
              body: JSON.stringify({
                auto_enabled: !!this.loreSettings.auto_enabled,
                auto_period_hours: period,
                auto_window_hours: win,
                updated_at: p.updated_at,
              }),
            });
          this.applyLoreProfile(saved, true);
          this.toast('Настройки автогенерации сохранены', 'ok');
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.chatLore409 = e.message;
            return;
          }
          this.toast('Ошибка сохранения настроек: ' + this.loreErrText(e), 'err');
        } finally {
          this.chatLoreSaving = false;
        }
      },

      generateNow: async function () {
        var p = this.chatLoreProfile;
        if (!p || this.chatLoreBusy) return;
        if (!p.auto_enabled) {
          this.toast('Автогенерация выключена — включите её в настройках', 'warn');
          return;
        }
        this.chatLoreGenerating = true;
        try {
          var res = (await this.api(
            '/api/chat_lore/' + p.chat_id + '/generate',
            { method: 'POST', body: '{}' })) || {};
          if (res.status === 'ok') {
            this.toast(res.changed
              ? 'Авто-лор обновлён'
              : 'Авто-лор без изменений (UNCHANGED)', 'ok');
          } else if (res.reason === 'quiet_window') {
            this.toast('Мало осмысленных сообщений в окне — генерация пропущена', 'warn');
          } else {
            this.toast('Генерация пропущена: ' + (res.reason || '—'), 'warn');
          }
          // авто-прогон мог изменить auto_lore/last_auto_at — перечитываем
          // профиль; черновик ручного текста при этом не трогаем
          try {
            var fresh = await this.api('/api/chat_lore/' + p.chat_id);
            if (fresh) {
              this.applyLoreProfile(fresh, true);
              this.loreAuto = fresh.auto_lore || '';
            }
          } catch (e2) { /* некритично — подтянется при следующем выборе чата */ }
        } catch (e) {
          var code = e.status === 409 && e.message ? e.message.code : null;
          if (code === 'auto_disabled') {
            this.toast('Автогенерация выключена для чата', 'warn');
          } else if (code === 'locked') {
            this.toast('Прогон уже выполняется — попробуйте чуть позже', 'warn');
          } else if (code === 'conflict') {
            this.chatLore409 = e.message;
          } else {
            this.toast('Ошибка генерации: ' + this.loreErrText(e), 'err');
          }
        } finally {
          this.chatLoreGenerating = false;
        }
      },

      clearAuto: async function () {
        var p = this.chatLoreProfile;
        if (!p || this.chatLoreBusy) return;
        if (!window.confirm('Очистить авто-лор чата ' + p.chat_id
            + '? Прошлый текст останется в истории изменений.')) return;
        this.chatLoreSaving = true;
        try {
          var saved = await this.api(
            '/api/chat_lore/' + p.chat_id + '/clear_auto',
            { method: 'POST', body: '{}' });
          this.applyLoreProfile(saved, true);
          this.loreAuto = saved.auto_lore || '';
          this.toast('Авто-лор очищен', 'ok');
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.chatLore409 = e.message;
            return;
          }
          this.toast('Ошибка очистки: ' + this.loreErrText(e), 'err');
        } finally {
          this.chatLoreSaving = false;
        }
      },

      loadHistory: async function () {
        var p = this.chatLoreProfile;
        if (!p || this.chatLoreHistoryLoading) return;
        this.chatLoreHistoryOpen = true;
        this.chatLoreHistoryLoading = true;
        this.chatLoreHistory = [];
        try {
          var rows = await this.api(
            '/api/chat_lore/' + p.chat_id + '/history?limit=100');
          // diff-строки считаем один раз при загрузке (old/new → красное/зелёное)
          this.chatLoreHistory = (Array.isArray(rows) ? rows : []).map(
            function (r) {
              r.diff = this.diffLines(r.old_value, r.new_value);
              return r;
            }, this);
        } catch (e) {
          if (e.status !== 401 && e.status !== 403) {
            this.toast('Не удалось загрузить историю: ' + this.loreErrText(e), 'err');
          }
        } finally {
          this.chatLoreHistoryLoading = false;
        }
      },
      closeLoreHistory: function () {
        this.chatLoreHistoryOpen = false;
      },
      // Q8: 409-модалка «Профиль изменён — перезагрузить?» → повторный GET
      confirmLoreReload: function () {
        var target = this.chatLoreSelectedId
          || (this.chatLoreProfile && this.chatLoreProfile.chat_id);
        this.chatLore409 = null;
        if (target != null) this.loadProfile(target);
      },
      cancelLoreReload: function () {
        this.chatLore409 = null;
      },

      // ═══ Раунд 10 (F-8 T-872/T-873): отношения — имена/аватары ═══
      // Резолв имени участника (T-872, уточнение 10.2): Alias
      // (limits.summary_aliases) → nickname (servername) → username.
      // Имена — КАК ЕСТЬ (эмодзи/спецсимволы — без чистки сервера); @ с
      // username показывает ТОЛЬКО если имени нет (без «@»); user_id как
      // имя — НИКОГДА (ID и так мелким рядом в карточке). Аватар:
      // /api/avatar-прокси + фолбэк-инициал первой графемы имени.
      summaryAliasesMap: function () {
        var item = this.configItems.find(function (it) {
          return it.key === 'limits.summary_aliases';
        });
        var v = item && item.value;
        return (v && typeof v === 'object') ? v : {};
      },
      resolveRelationName: function (u) {
        if (!u || u.user_id == null) return '';
        var aliases = this.summaryAliasesMap();
        var alias = aliases[String(u.user_id)];
        if (alias) return String(alias);
        if (u.name) return String(u.name);
        // 10.2: username — БЕЗ «@» и только когда имени нет (сервер уже
        // снимает @; дубль с подписью не показываем)
        if (u.username) return String(u.username);
        // ID как имя — никогда: пусто (id уже мелким рядом в карточке)
        return '';
      },
      avatarInitial: function (u) {
        var name = this.resolveRelationName(u);
        // 10.2: Array.from — первая ГРАФЕМА (эмодзи/суррогатные пары не
        // ломаются, charAt(0) давал бы половинку суррогатной пары)
        var first = (typeof name === 'string' && name.length)
          ? Array.from(name)[0] : '';
        return (first || '?').toUpperCase();
      },
      // F-8 (T-873): имя чата из локального кэша списка + chat_id мелким
      chatProfileTitle: function () {
        var p = this.chatLoreProfile;
        if (!p) return '';
        var found = this.chatLoreChats.find(function (c) {
          return c.chat_id === p.chat_id;
        });
        return (found && found.title) || ('Чат ' + p.chat_id);
      },
      // F-8 (T-876): «Telegram ID админа» (reactions.admin_user_id) показывается
      // в «Доступах» — в config-вкладке PERMsoc скрыт (данные/ключ НЕ меняются).
      isAdminIdHidden: function (item) {
        return this.activeTab === 'permsoc'
          && item && item.key === 'reactions.admin_user_id';
      },
      adminIdItem: function () {
        return this.configItems.find(function (it) {
          return it.key === 'reactions.admin_user_id';
        }) || null;
      },

      // ═══ Раунд 9 (AGI Memory, spec §3.6.1/§3.6.3, T-830/F3): отношения ═══

      // GET /chat_lore/{id}/relations: SQLite-скоры/авто-стадии (users_meta)
      // + PG manual (relations JSONB); строим черновики строки для правки.
      loadRelations: async function (chatId) {
        if (chatId == null || chatId === '') return;
        var self = this;
        var epoch = this.scopeEpoch;   // D2: снимок scope
        this.relationsBusy = true;
        try {
          var data = await this.api('/api/chat_lore/' + chatId + '/relations');
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.relationsEnabled = !!(data && data.relations_enabled);
          var rows = Array.isArray(data && data.users) ? data.users : [];
          rows.forEach(function (u) {
            u.draft_stage = u.stage_manual || 'auto';
            u.draft_note = u.note || '';
          });
          this.chatRelations = rows;
          // UI-полировка TMA (fix-раунд): аватары участников — blob через
          // прокси avatarUrl('user', …); photo_file_id != null (сервер
          // обогатил топ-50) — сразу; остальным — ленивый догруз
          // (стаггер 300мс, см. loadRelationAvatarsLazy, Hotfix-R10).
          this.chatRelations.forEach(function (u) {
            if (u && u.user_id != null && u.photo_file_id != null) {
              self.loadAvatar('user', u.user_id, u);
            }
          });
          this.loadRelationAvatarsLazy(rows);
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          this.chatRelations = [];
          if (e.status === 404) {
            this.chatRelations = [];
          } else if (e.status !== 401 && e.status !== 403) {
            this.toast('Не удалось загрузить отношения: '
              + this.loreErrText(e), 'err');
          }
        } finally {
          if (this._scopeGuard(epoch)) this.relationsBusy = false;   // R3
        }
      },

      // PUT /chat_lore/{id}/relations {user_id, stage_manual, note} —
      // ручная стадия админа (manual ?? auto в инжекте); 409 optimistic.
      saveRelationManual: async function (row) {
        // Раунд 10.4 (F-5): chat_id — лор-профиль ИЛИ активный чат
        // (вкладка «Участники и отношения»); методы общие.
        var p = this.chatLoreProfile;
        // Ревью-фикс раунда: НА вкладке relations всегда АКТИВНЫЙ чат;
        // chatLoreProfile.chat_id — только на «Лоре чатов» (иначе кросс-чат:
        // профиль чата A остаётся после ухода с лора → правки чату B
        // уходили чату A).
        var onLoreTab = this.activeTab === 'chat_lore';
        var relChat = (onLoreTab && p && p.chat_id != null)
          ? p.chat_id : this.activeChatId;
        if (relChat == null || !row || this.relationsBusy) return;
        this.relationsBusy = true;
        this.relationDraft = {
          user_id: row.user_id,
          stage_manual: row.draft_stage,
          note: row.draft_note,
        };
        try {
          var saved = await this.api(
            '/api/chat_lore/' + relChat + '/relations', {
              method: 'PUT',
              body: JSON.stringify({
                user_id: row.user_id,
                stage_manual: this.relationDraft.stage_manual,
                note: this.relationDraft.note || null,
                updated_at: (p && p.updated_at) || null,  // optimistic-метка
              }),
            });
          if (p) this.applyLoreProfile(saved, true);   // свежие relations/метка
          await this.loadRelations(relChat);
          this.toast('Пометка участника сохранена', 'ok');
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.chatLore409 = e.message;       // → модалка «Перезагрузить?»
            return;
          }
          if (e.status === 422) {
            this.toast('Стадия вне списка допустимых (422)', 'warn');
          } else {
            this.toast('Ошибка сохранения пометки: ' + this.loreErrText(e),
              'err');
          }
        } finally {
          this.relationsBusy = false;
        }
      },

      // DELETE /chat_lore/{id}/relations {user_id, updated_at} — сброс на
      // авто (стирает и стадию, и заметку; spec §3.6.3 «сброс»).
      removeRelationManual: async function (row) {
        // Раунд 10.4 (F-5): chat_id — лор-профиль ИЛИ активный чат.
        var p = this.chatLoreProfile;
        // Ревью-фикс раунда: НА вкладке relations всегда АКТИВНЫЙ чат;
        // chatLoreProfile.chat_id — только на «Лоре чатов» (иначе кросс-чат:
        // профиль чата A остаётся после ухода с лора → правки чату B
        // уходили чату A).
        var onLoreTab = this.activeTab === 'chat_lore';
        var relChat = (onLoreTab && p && p.chat_id != null)
          ? p.chat_id : this.activeChatId;
        if (relChat == null || !row || this.relationsBusy) return;
        this.relationsBusy = true;
        try {
          var saved = await this.api(
            '/api/chat_lore/' + relChat + '/relations', {
              method: 'DELETE',
              body: JSON.stringify({
                user_id: row.user_id,
                updated_at: (p && p.updated_at) || null,
              }),
            });
          if (p) this.applyLoreProfile(saved, true);
          await this.loadRelations(relChat);
          this.toast('Участник возвращён на авто-стадию', 'ok');
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.chatLore409 = e.message;
            return;
          }
          this.toast('Ошибка сброса пометки: ' + this.loreErrText(e), 'err');
        } finally {
          this.relationsBusy = false;
        }
      },

      // PUT /chat_lore/{id}/relations_enabled {enabled, updated_at} —
      // per-chat тумблер «Влиять на тон бота» (D-3; БЕЗ истории).
      // Раунд 10.20 (БЛОК 3.1(в)/T-1895): root cause «мёртвого» тумблера —
      // `:checked` (НЕ v-model) + busy-блокировка: Vue на ре-рендере возвращал
      // visual в исходное состояние, пока шёл запрос, а при 409 стейт
      // откатывался — пользователь видел «щелчок без эффекта». Фикс:
      // оптимистичное обновление стейта ДО запроса + откат и явный 409-путь.
      onRelationsToggle: function (ev) {
        if (this.relationsBusy) {
          ev.target.checked = this.relationsEnabled;   // визуальная синхронизация
          return;
        }
        this.toggleRelationsEnabled(!!ev.target.checked);
      },
      toggleRelationsEnabled: async function (want) {
        // Раунд 10.4 (F-5): chat_id — лор-профиль ИЛИ активный чат.
        var p = this.chatLoreProfile;
        // Ревью-фикс раунда: НА вкладке relations всегда АКТИВНЫЙ чат;
        // chatLoreProfile.chat_id — только на «Лоре чатов» (иначе кросс-чат:
        // профиль чата A остаётся после ухода с лора → правки чату B
        // уходили чату A).
        var onLoreTab = this.activeTab === 'chat_lore';
        var relChat = (onLoreTab && p && p.chat_id != null)
          ? p.chat_id : this.activeChatId;
        if (relChat == null || this.relationsBusy) return;
        var previous = this.relationsEnabled;
        // Оптимистично: визуальный отклик мгновенный (без «мёртвого» щелчка).
        this.relationsEnabled = !!want;
        this.relationsBusy = true;
        try {
          var saved = await this.api(
            '/api/chat_lore/' + relChat + '/relations_enabled', {
              method: 'PUT',
              body: JSON.stringify({
                enabled: !!want,
                updated_at: (p && p.updated_at) || null,
              }),
            });
          if (p) this.applyLoreProfile(saved, true);
          this.relationsEnabled = !!saved.relations_enabled;
          this.toast(this.relationsEnabled
            ? 'Тон по стадиям включён для чата'
            : 'Тон по стадиям выключен', 'ok');
        } catch (e) {
          // 409 конкурентности — стейт не «залипает»: откат + окно конфликта.
          this.relationsEnabled = previous;
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.chatLore409 = e.message;       // reload подтянет и relations
            return;
          }
          this.toast('Ошибка переключения: ' + this.loreErrText(e), 'err');
        } finally {
          this.relationsBusy = false;
        }
      },

      // Алиасы имён spec §3.6.3 (saveRelation/resetRelation/saveRelationsToggle)
      saveRelation: function (row) { return this.saveRelationManual(row); },
      resetRelation: function (row) { return this.removeRelationManual(row); },
      saveRelationsToggle: function () { return this.toggleRelationsEnabled(); },

      // ═══ Раунд 9 (AGI Memory, spec §3.6.2/§3.6.3, T-831/F4): «Сон» ═══

      // GET /api/memory/dream/beliefs — последние убеждения (карточки).
      loadDreamBeliefs: async function () {
        this.memoryRagBusy = true;
        try {
          var data = await this.api('/api/memory/dream/beliefs?limit=20');
          this.dreamBeliefs = Array.isArray(data) ? data : [];
        } catch (e) {
          this.dreamBeliefs = [];
          if (e.status !== 401 && e.status !== 403 && e.status !== 503) {
            this.toast('Не удалось загрузить убеждения: ' + e.message, 'err');
          }
        } finally {
          this.memoryRagBusy = false;
        }
      },

      // POST /api/memory/dream/run — ручной «синтез сейчас» (202/409/503);
      // флаг dream_enabled не требуется (спец. ручной запуск, D-5).
      runDreamNow: async function () {
        if (this.dreamBusy) return;
        this.dreamBusy = true;
        var self = this;
        try {
          await this.api('/api/memory/dream/run', { method: 'POST',
            body: JSON.stringify({}) });
          // F2 (spec §4.6, T-1720, ADR-1018-2 D5): ручной запуск — бейдж
          // зажигаем оптимистично и НЕМЕДЛЕННО тянем cognition (WebSocket в
          // проекте нет; polling 15с дал бы стейл). Плюс ретраи 1/3/8с и
          // временное ускорение polling до 5с на время прогона.
          if (this.cognition && this.cognition.dream) {
            this.cognition.dream.active = true;
          }
          this.loadCognition();
          // S10.18-22/-26: сначала перезапуск polling (он чистит старые
          // ретраи внутри stop), затем — новые ретраи, иначе restart снял бы
          // только что созданные таймеры.
          this.restartCognitionPolling(5000, 120000);
          this._retryCognition([1000, 3000, 8000]);
          this.toast('Синтез запущен в фоне — результат появится в списке '
            + 'убеждений', 'ok');
          setTimeout(function () {   // прогресс LLM-прогона — минуты; обновим
            self.loadDreamBeliefs();
            self.loadDreamLog();
          }, 3000);
        } catch (e) {
          var code = (e.status === 409 && e.message) ? e.message.code : null;
          if (code === 'already_running') {
            this.toast('Синтез уже выполняется — подождите', 'warn');
          } else if (e.status === 503) {
            this.toast('Воркер сна недоступен (503)', 'warn');
          } else {
            this.toast('Ошибка запуска синтеза: ' + e.message, 'err');
          }
        } finally {
          this.dreamBusy = false;
        }
      },

      // DELETE /api/memory/dream/beliefs/{id} — мягкое удаление (D-7).
      dreamDelete: async function (belief) {
        if (!belief || !window.confirm('Удалить убеждение (мягко)? Оно '
            + 'перестанет попадать в контекст.')) return;
        this.memoryRagBusy = true;
        try {
          await this.api('/api/memory/dream/beliefs/' + belief.id,
            { method: 'DELETE' });
          this.toast('Убеждение удалено (мягко)', 'ok');
          await this.loadDreamBeliefs();
        } catch (e) {
          this.toast('Ошибка удаления: ' + e.message, 'err');
        } finally {
          this.memoryRagBusy = false;
        }
      },

      // POST /api/memory/dream/beliefs/{id}/protect — в protected_facts чата.
      dreamProtect: async function (belief) {
        if (!belief || this.memoryRagBusy) return;
        this.memoryRagBusy = true;
        try {
          var res = await this.api(
            '/api/memory/dream/beliefs/' + belief.id + '/protect',
            { method: 'POST', body: '{}' });
          this.toast(res && res.protected
            ? 'Убеждение защищено от синтеза'
            : 'Уже было в защищённых', 'ok');
          await this.loadDreamBeliefs();
        } catch (e) {
          this.toast('Ошибка защиты: ' + e.message, 'err');
        } finally {
          this.memoryRagBusy = false;
        }
      },

      // GET /api/memory/dream/log — «последние сны» (аудит).
      loadDreamLog: async function () {
        try {
          var data = await this.api('/api/memory/dream/log?limit=20');
          this.dreamLog = Array.isArray(data) ? data : [];
        } catch (e) {
          this.dreamLog = [];
          if (e.status !== 401 && e.status !== 403 && e.status !== 503) {
            this.toast('Не удалось загрузить лог снов: ' + e.message, 'err');
          }
        }
      },

      // GET /api/memory/nostalgia/log — «последние срабатывания».
      loadNostalgiaLog: async function () {
        try {
          var data = await this.api('/api/memory/nostalgia/log?limit=20');
          this.nostalgiaLog = Array.isArray(data) ? data : [];
        } catch (e) {
          this.nostalgiaLog = [];
          if (e.status !== 401 && e.status !== 403 && e.status !== 503) {
            this.toast('Не удалось загрузить ностальгию: ' + e.message, 'err');
          }
        }
      },

      // ═══ F5 (cognition-dashboard-round1013, ТЗ §5/§7): «Осмысление» ═══
      // Данные — аддитивные read-API (cognition/status, graph, stats,
      // timeline, beliefs?kind=); R17-safe, без хардкода.

      // F4 (persona-traits-ribbon-round1014): адаптер `dynamic_traits`
      // `{ts,text,source}` → `{id,fact,created_at}` для `_ribbonLoop`
      // (лента «Эволюция характера»). Fail-open: не-массив → [].
      _traitsAdapter: function (list) {
        var src = Array.isArray(list) ? list : [];
        var out = [];
        for (var i = 0; i < src.length; i++) {
          var it = src[i] || {};
          out.push({
            id: (it.id != null ? it.id : (it.ts || i)),
            fact: it.text || '',
            created_at: it.ts || 0,
          });
        }
        return out;
      },
      // Лента с opacity-классами по позиции (T-1450); дублируется дважды
      // для seamless вертикального скролла (CSS @keyframes translateY -50%).
      _ribbonLoop: function (items) {
        var src = (Array.isArray(items) ? items : []).slice(0, 12);
        var n = src.length;
        var out = [];
        for (var pass = 0; pass < 2; pass++) {
          for (var i = 0; i < n; i++) {
            var it = src[i] || {};
            out.push({
              key: pass + '-' + i + '-' + (it.id != null ? it.id : i),
              id: it.id, fact: it.fact || '',
              created_at: it.created_at || 0,
              op: this.ribbonItemClass(i, n),
            });
          }
        }
        return out;
      },
      // Класс opacity по нормированной дистанции от центра (0 — центр → 100,
      // 1 — край → 50); юнит-тестируемая чистая функция (spec §4.1).
      ribbonItemClass: function (index, total) {
        var n = Math.max(1, Number(total) || 1);
        var center = (n - 1) / 2;
        var half = center > 0 ? center : 1;
        var dist = Math.abs((Number(index) || 0) - center) / half;
        if (dist <= 0.34) return 'ribbon-op-100';
        if (dist <= 0.67) return 'ribbon-op-75';
        return 'ribbon-op-50';
      },
      // F3 (sleep-badge-countdown-round1017): остаток до старта фазы.
      // 8100 → «2ч 15м»; 900 → «15м»; 0/-30 → «0м»; null/NaN → «—».
      // Кламп ≥0, округление ВНИЗ до минут (ADR-1017-3 §2.2).
      fmtCountdown: function (seconds) {
        if (seconds == null) return '—';
        var s = Number(seconds);
        if (isNaN(s)) return '—';
        if (s < 0) s = 0;
        var total = Math.floor(s / 60);
        if (total < 1) return '0м';
        var h = Math.floor(total / 60);
        var m = total % 60;
        return h > 0 ? (h + 'ч ' + m + 'м') : (m + 'м');
      },
      // HH:MM локального времени (Timeline/бейдж «следующее пробуждение»).
      fmtClock: function (ts) {
        if (!ts) return '—';
        var d = new Date(Number(ts) * 1000);
        if (isNaN(d.getTime())) return '—';
        var hh = String(d.getHours()); if (hh.length < 2) hh = '0' + hh;
        var mm = String(d.getMinutes()); if (mm.length < 2) mm = '0' + mm;
        return hh + ':' + mm;
      },
      // F8 (ADR-1024-5 D3/UPD3 №4): R17-safe код причины → понятный текст
      // пояснительного Empty State. Неизвестный код → нейтральная фраза.
      emptyReasonLabel: function (reason, status) {
        var code = String(reason || status || '').toLowerCase();
        var map = {
          ok: 'данные есть',
          no_self_facts: 'за последние 30 дней нет self-фактов — бот ещё ' +
            'не сформировал наблюдений о собственном поведении',
          persona_disabled: 'модуль «Личность» выключен для этого чата',
          master_off: 'мастер-рубильник памяти выключен (нужно решение ' +
            'владельца)',
          budget_skip: 'дневной бюджет фоновых задач исчерпан',
          cooldown: 'ещё не прошёл интервал между прогонами',
          daily_limit: 'суточный лимит прогонов исчерпан',
          no_anchors: 'недостаточно исторических фактов (нужны минимум 2 ' +
            'опоры старше 90 дней)',
          no_context: 'нет свежего контекста для анализа',
          duplicate: 'все выводы уже записаны ранее (идемпотентность)',
          empty: 'источников пока недостаточно',
          error: 'ошибка пайплайна (причина видна в логах)',
          never: 'прогон ещё не выполнялся',
        };
        return map[code] || 'данных пока нет — они появятся по мере накопления';
      },
      // F4 (persona-traits-ribbon-round1014): 'ДД.ММ' для записей ленты
      // «Эволюция характера» (F4-Q1: «13.09: Стал более циничным...»).
      fmtDayMonth: function (ts) {
        if (!ts) return '—';
        var d = new Date(Number(ts) * 1000);
        if (isNaN(d.getTime())) return '—';
        var dd = String(d.getDate()); if (dd.length < 2) dd = '0' + dd;
        var mm = String(d.getMonth() + 1); if (mm.length < 2) mm = '0' + mm;
        return dd + '.' + mm;
      },
      // 45000 → «45k» (прогресс-бары лимитов, ТЗ §7).
      fmtTokens: function (n) {
        if (n == null) return '—';
        var v = Number(n) || 0;
        if (v >= 1000) return Math.round(v / 1000) + 'k';
        return String(v);
      },
      nostalgiaLabel: function () {
        var n = (this.cognition && this.cognition.nostalgia) || {};
        if (n.mode === 'silence') {
          return 'Тишина: ' + (n.silence_left_min || 0) + '/' +
            (n.silence_min_total || 0) + ' мин';
        }
        if (n.mode === 'cooldown') {
          return 'Кулдаун: ещё ' + (n.cooldown_left_h || 0) + ' ч';
        }
        return 'Готова к вбросу';
      },
      // '' | '?chat_id=N' (first) / '&chat_id=N' (иначе) — helper для URL.
      _cidQuery: function (first) {
        if (this.activeChatId == null) return '';
        return (first ? '?' : '&') + 'chat_id=' + this.activeChatId;
      },
      loadCognition: async function () {
        if (!this.isGlobalAdmin) return;
        this.cognitionBusy = true;
        try {
          var q = this._cidQuery(true);
          this.cognition = await this.api(
            '/api/memory/cognition/status' + q);
          this.cognitionStats = await this.api('/api/memory/stats' + q);
          this.cognitionTimeline = await this.api(
            '/api/memory/timeline' + (q ? q + '&limit=20' : '?limit=20'));
          // S10.13-5: ленты beliefs/paradigms тоже скоупятся выбранным чатом
          // (иначе остальные блоки чатовые, а ленты — глобальные).
          var cq = this._cidQuery(false);
          var beliefs = await this.api(
            '/api/memory/dream/beliefs?kind=belief&limit=30' + cq);
          this.cognitionBeliefs = Array.isArray(beliefs) ? beliefs : [];
          var paradigms = await this.api(
            '/api/memory/dream/beliefs?kind=paradigm&limit=30' + cq);
          this.cognitionParadigms = Array.isArray(paradigms) ? paradigms : [];
          // F8 (ADR-1024-5 D3): статус/причина парадигм для Empty State.
          // Fail-open: ошибка → причина неизвестна (лента покажет текст).
          try {
            var deep = await this.api('/api/memory/deep-sleep' + q);
            this.cognitionParadigmsStatus =
              (deep && deep.paradigms_status) || null;
            this.cognitionParadigmsReason =
              (deep && deep.paradigms_reason) || null;
          } catch (de) {
            this.cognitionParadigmsStatus = null;
            this.cognitionParadigmsReason = null;
          }
          // F4 (persona-traits-ribbon-round1014): третья лента — «Эволюция
          // характера» из global `dynamic_traits` (GET /api/persona).
          // Fail-open: ошибка → пустой пул (заглушка).
          try {
            var persona = await this.api('/api/persona' + q);
            this.cognitionTraits = this._traitsAdapter(
              persona && persona.dynamic_traits);
            // F11 (§13/D2): имя бота для Hero — из того же ответа persona
            // (новых запросов нет; пусто → нейтральное «Бот»).
            var pv = (persona && persona.values) || {};
            this.botDisplayName = (pv.name || '').trim();
            // F8 (ADR-1024-5 D3): причина/статус черт + self-факты.
            this.cognitionTraitsStatus =
              (persona && persona.traits_status) || null;
            this.cognitionTraitsReason =
              (persona && persona.traits_reason) || null;
            this.cognitionSelfFactsCount =
              (persona && persona.self_facts_count != null)
                ? persona.self_facts_count : null;
          } catch (pe) {
            this.cognitionTraits = [];
          }
          // F4/UPD п.4: метрики Личности (для «Сводки»), fail-open внутри.
          this.loadPersonaHealth();
          // F7 (D-6): метрики здоровья памяти (просрочено/не подтверждено/
          // сырьё/хранилище) — аддитивный блок «Мониторинга Интеллекта».
          this.loadMemoryHealth();
        } catch (e) {
          if (e.status !== 401 && e.status !== 403 && e.status !== 503) {
            this.toast('Осмысление: ' + e.message, 'err');
          }
        } finally {
          this.cognitionBusy = false;
        }
        this.loadCognitionGraph();
      },
      // Виджет «Интеллект и Память» в «Сводке» (T-1454..T-1456): компактный
      // набор — статус фаз + метрики + короткий Timeline.
      loadMemoryWidget: async function () {
        if (!this.isGlobalAdmin) return;
        this.memoryWidgetBusy = true;
        try {
          var q = this._cidQuery(true);
          this.cognition = await this.api(
            '/api/memory/cognition/status' + q);
          this.cognitionStats = await this.api('/api/memory/stats' + q);
          this.cognitionTimeline = await this.api(
            '/api/memory/timeline' + (q ? q + '&limit=8' : '?limit=8'));
        } catch (e) {
          if (e.status !== 401 && e.status !== 403 && e.status !== 503) {
            this.toast('Интеллект и Память: ' + e.message, 'err');
          }
        } finally {
          this.memoryWidgetBusy = false;
        }
      },
      // ── Граф (T-1452): lazy self-host vis-network (ADR-1013-2) ──────────
      ensureVisNetwork: function () {
        var self = this;
        if (window.vis && window.vis.Network) {
          this.cognitionVisLoaded = true;
          return Promise.resolve(true);
        }
        if (this._visPromise) return this._visPromise;
        this._visPromise = new Promise(function (resolve) {
          var s = document.createElement('script');
          s.src = '/static/vendor/vis-network/vis-network.min.js';
          s.async = true;
          s.onload = function () {
            self.cognitionVisLoaded = !!(window.vis && window.vis.Network);
            resolve(self.cognitionVisLoaded);
          };
          s.onerror = function () {
            self.cognitionVisLoaded = false;
            resolve(false);
          };
          document.head.appendChild(s);
        });
        return this._visPromise;
      },
      loadCognitionGraph: async function () {
        if (!this.isGlobalAdmin) return;
        try {
          this.cognitionGraphData = await this.api(
            '/api/memory/graph' + this._cidQuery(true));
        } catch (e) {
          this.cognitionGraphData = { nodes: [], edges: [], truncated: false };
        }
        var self = this;
        this.$nextTick(function () { self.renderCognitionGraph(); });
      },
      // ISSUE-4: подпись данных графа. 15с-polling не должен сбрасывать
      // drag/zoom/physics — пересоздаём vis.Network только при реальном
      // изменении узлов/рёбер (иначе Android WebView получает лишнюю нагрузку).
      _graphSignature: function (g) {
        var nodes = (g && g.nodes) || [];
        var edges = (g && g.edges) || [];
        return JSON.stringify([
          nodes.map(function (n) {
            return [n.id, n.label, n.group, n.degree || 0]; }),
          edges.map(function (e) {
            return [e.from, e.to, e.label || '', e.weight || 0]; }),
        ]);
      },
      renderCognitionGraph: async function () {
        var ok = await this.ensureVisNetwork();
        if (!ok || !this.isGlobalAdmin) return;
        // R10.11-5: пока грузился vis-network, могли уйти с «Статуса» —
        // не создаём stale-инстанс (destroy уже отработал при уходе).
        if (this.activeTab !== 'status') return;
        var el = this.$refs ? this.$refs.cognitionGraph : null;
        if (!el) return;
        var g = this.cognitionGraphData || { nodes: [], edges: [] };
        var sig = this._graphSignature(g);
        // F11 (§16/D4): mobile — упрощённый граф (без физики/перетаскивания,
        // фиксированный fit); на отдельном экране полного исследования —
        // полный режим. Смена режима → пере-рендер (instance пересоздаётся).
        var simpleGraph = this.isMobileShell && !this.graphFullVisible;
        var mode = simpleGraph ? 'simple' : 'full';
        // ISSUE-4: экземпляр жив и данные/режим не изменились → не трогаем сеть.
        if (this.cognitionNetwork && sig === this._cognitionGraphSig
            && mode === this._cognitionGraphMode) return;
        this.destroyCognitionGraph();
        var nodes = new window.vis.DataSet(g.nodes || []);
        var edges = new window.vis.DataSet(g.edges || []);
        var options = {
          nodes: { shape: 'dot', size: 14,
                   font: { size: 12, color: '#e5e7eb' } },
          edges: { arrows: 'to', smooth: true,
                   color: { color: 'rgba(148,163,184,.45)' },
                   font: { size: 10, color: '#94a3b8' } },
          // F11 (§16/D4): mobile-упрощение — без перетаскивания узлов;
          // desktop/полный экран — прежнее поведение.
          interaction: { hover: true, dragNodes: !simpleGraph, dragView: true,
                         zoomView: true },
          // F2 (T-1559): физика отталкивания barnesHut — кластеры
          // разлетаются, а не слипаются. reducedMotion → физика выключена.
          // F11: mobile-упрощение → физика сразу off (см. ниже, после создания).
          physics: this.reducedMotion
            ? false
            : {
                solver: 'barnesHut',
                barnesHut: {
                  gravitationalConstant: -8000, // расталкивание (негатив)
                  centralGravity: 0.3,          // удержание в кадре
                  springLength: 120,            // длина пружины рёбер
                  springConstant: 0.04,
                  damping: 0.09,                // гасит «болтанку»
                  avoidOverlap: 0.2,            // не даёт слипаться
                },
                stabilization: { enabled: true,
                                 iterations: GRAPH_PHYSICS_ITERATIONS,
                                 updateInterval: 25, fit: true },
                minVelocity: 0.75,
              },
          groups: { user: { color: '#a78bfa' }, topic: { color: '#38bdf8' },
                    event: { color: '#f59e0b' }, fact: { color: '#34d399' } },
        };
        this.cognitionNetwork = new window.vis.Network(
          el, { nodes: nodes, edges: edges }, options);
        this._cognitionGraphSig = sig;
        this._cognitionGraphMode = mode;
        // F11 (§16/D4): mobile-упрощение — физика сразу выключена
        // (фиксированный fit), перетаскивание — через `dragNodes`.
        if (simpleGraph) {
          try {
            this.cognitionNetwork.setOptions({ physics: { enabled: false } });
          } catch (e) { /* noop */ }
        }
        // F11 (§16/D4): подробности выбранного узла + ближайшие связи. `on`
        // (не `once`) — обработчики живут с инстансом и снимаются его destroy.
        if (this.cognitionNetwork
            && typeof this.cognitionNetwork.on === 'function') {
          var selfSel = this;
          this.cognitionNetwork.on('selectNode', function (params) {
            var id = params && params.nodes && params.nodes[0];
            if (id != null) selfSel.graphSelectNode(id);
          });
          this.cognitionNetwork.on('deselectNode', function () {
            selfSel.graphClearDetail();
          });
        }
        // F4 (ADR-1018-4 D2): выключаем physics ПОСЛЕ первичной расстановки.
        // `once` (не `on`) — обработчики не копятся при повторных рендерах.
        // B3-1: guard ТОЛЬКО по тождеству инстанса — после
        // destroyCognitionGraph() this.cognitionNetwork=null, поэтому старый
        // (уже уничтоженный) инстанс отсекается. Полей `destroyed`/
        // `isDestroyed` в self-host vis-network v9.1.9 НЕТ — проверять их
        // нельзя (мёртвый guard). Сетевые вызовы на уничтоженной сети ловит
        // try/catch. reducedMotion → физика изначально false, слушатели не нужны.
        if (!this.reducedMotion && GRAPH_PHYSICS_DISABLE_ON_STABILIZE) {
          var self = this;
          var net = this.cognitionNetwork;
          var _disablePhysics = function () {
            if (net && net === self.cognitionNetwork) {
              try {
                net.setOptions({ physics: { enabled: false } });
              } catch (e) { /* noop: сеть уже уничтожена */ }
            }
          };
          net.once('stabilizationIterationsDone', _disablePhysics);
          net.once('stabilized', _disablePhysics);
        }
      },
      // F2 (T-1560/1561, spec §5): поиск по графу — подстрока по label
      // (R16: id — ключ, поиск по label). Несколько совпадений — перебор
      // по повторному Enter. Пустой ввод → сброс + fit(). search-only:
      // polling/_graphSignature/пересоздание сети не затрагиваются.
      searchCognitionGraph: async function () {
        var q = String(this.graphSearchQuery || '').trim().toLowerCase();
        if (!this.cognitionNetwork) {
          // гонка lazy-load: дождаться рендера и повторить один раз
          await this.renderCognitionGraph();
          if (!this.cognitionNetwork) return;
        }
        if (!q) { this.clearCognitionGraphSearch(); return; }
        var nodes = (this.cognitionGraphData &&
                     this.cognitionGraphData.nodes) || [];
        // F11 (§16/D4): поиск по имени (label) И по алиасу. Алиасы берём из
        // УЖЕ загруженного `summaryAliasesMap()` (limits.summary_aliases);
        // новых endpoint'ов/полей нет. Если совпал только алиас, для которого
        // в графе нет узла — честное «в графе нет узла …» (без выдумывания).
        var aliases = this.summaryAliasesMap ? this.summaryAliasesMap() : {};
        var aliasIds = {};
        Object.keys(aliases).forEach(function (uid) {
          var val = aliases[uid];
          if (val && String(val).toLowerCase().indexOf(q) !== -1) {
            aliasIds[String(uid)] = true;
          }
        });
        var hits = nodes.filter(function (n) {
          if (String(n.label || '').toLowerCase().indexOf(q) !== -1) return true;
          return !!aliasIds[String(n.id)];
        });
        if (!hits.length) {
          this._graphSearchMatches = [];
          this._graphSearchIdx = 0;
          this.graphSearchStatus = 'Ничего не найдено';
          this.toast('В графе нет узла «' + q + '»', 'warn');
          return;
        }
        // циклический перебор при повторном поиске того же запроса
        if (q !== this._graphSearchLastQ) { this._graphSearchIdx = -1; }
        this._graphSearchLastQ = q;
        this._graphSearchMatches = hits;
        this._graphSearchIdx = (this._graphSearchIdx + 1) % hits.length;
        var node = hits[this._graphSearchIdx];
        var anim = this.reducedMotion
          ? false : { duration: 600, easingFunction: 'easeInOutQuad' };
        this.cognitionNetwork.focus(node.id,
          { scale: 1.1, animation: anim });
        this.cognitionNetwork.selectNodes([node.id]);
        this.graphSearchStatus = 'Найден: ' + node.label +
          (hits.length > 1
            ? ' (' + (this._graphSearchIdx + 1) + '/' + hits.length + ')'
            : '');
      },
      clearCognitionGraphSearch: function () {
        this.graphSearchQuery = '';
        this.graphSearchStatus = '';
        this._graphSearchMatches = [];
        this._graphSearchIdx = 0;
        this._graphSearchLastQ = '';
        if (this.cognitionNetwork) {
          this.cognitionNetwork.selectNodes([]);
          var anim = this.reducedMotion ? false : { duration: 500 };
          this.cognitionNetwork.fit(anim);
        }
      },
      // F11 (§16/D4): «ближайшие связи» узла — соседи по существующим рёбрам
      // (реальные данные; вес/семантика/алгоритм НЕ меняются).
      graphNeighborsOf: function (nodeId) {
        var g = this.cognitionGraphData || {};
        var byId = {};
        (g.nodes || []).forEach(function (n) { byId[String(n.id)] = n; });
        var seen = {}, out = [];
        (g.edges || []).forEach(function (e) {
          var other = null;
          if (String(e.from) === String(nodeId)) other = e.to;
          else if (String(e.to) === String(nodeId)) other = e.from;
          if (other == null) return;
          var k = String(other);
          if (seen[k]) return;
          seen[k] = true;
          var n = byId[k] || {};
          out.push({ id: other, label: n.label || k, group: n.group || 'other' });
        });
        return out;
      },
      // F11 (§16/D4): выбрали узел → подробности (реальные label/group/degree)
      // + ближайшие связи.
      graphSelectNode: function (nodeId) {
        var detail = null;
        if (nodeId != null) {
          var nodes = (this.cognitionGraphData
            && this.cognitionGraphData.nodes) || [];
          for (var i = 0; i < nodes.length; i++) {
            if (String(nodes[i].id) === String(nodeId)) {
              var n = nodes[i];
              detail = { id: n.id, label: n.label || String(n.id),
                         group: n.group || 'other',
                         degree: (n.degree != null ? n.degree : null) };
              break;
            }
          }
        }
        this.graphDetail = detail;
        this.graphNeighbors = (nodeId != null)
          ? this.graphNeighborsOf(nodeId) : [];
      },
      graphClearDetail: function () {
        this.graphDetail = null;
        this.graphNeighbors = [];
      },
      // F11 (§16/D4): фокус на узле/соседе — камера + выделение (сеть не
      // пересоздаётся; layout не трогается).
      focusGraphNode: function (nodeId) {
        if (!this.cognitionNetwork || nodeId == null) return;
        var anim = this.reducedMotion
          ? false : { duration: 500, easingFunction: 'easeInOutQuad' };
        try {
          this.cognitionNetwork.focus(nodeId, { scale: 1.1, animation: anim });
          this.cognitionNetwork.selectNodes([nodeId]);
        } catch (e) { /* noop: сеть уничтожена */ }
        this.graphSelectNode(nodeId);
      },
      // F11 (§16/D4): витринный клиентский фильтр по group — выделяем
      // совпадающие узлы и подгоняем камеру. Физика/вес/дефолтный layout
      // НЕ меняются.
      applyGraphFilter: function () {
        if (!this.cognitionNetwork) return;
        var grp = this.graphFilterGroup;
        if (!grp) { this.clearCognitionGraphSearch(); return; }
        var nodes = (this.cognitionGraphData
          && this.cognitionGraphData.nodes) || [];
        var ids = nodes.filter(function (n) {
          return (n.group || 'other') === grp;
        }).map(function (n) { return n.id; });
        if (!ids.length) {
          this.graphSearchStatus = 'В группе нет узлов';
          return;
        }
        try {
          this.cognitionNetwork.selectNodes(ids);
          this.cognitionNetwork.fit({
            nodes: ids,
            animation: this.reducedMotion ? false : { duration: 500 },
          });
        } catch (e) { /* noop */ }
        this.graphSearchStatus = 'Группа «' + grp + '»: ' + ids.length + ' узлов';
      },
      // F11 (§16/D4): сброс вида — фильтр/подробности/выделение + fit().
      graphResetView: function () {
        this.graphFilterGroup = '';
        this.graphClearDetail();
        this.clearCognitionGraphSearch();
      },
      // F11 (§16/D4): mobile — отдельный экран полного исследования. Основной
      // путь — аддитивный hash-маршрут `#/status/graph` (владелец — F1);
      // fallback при IA_V2_ENABLED=false — полноэкранная шторка.
      openGraphFull: function () {
        this.graphClearDetail();
        if (this.iaV2) {
          if (typeof this.navTo === 'function') this.navTo('#/status/graph');
          else this.route = '#/status/graph';
        } else {
          this.graphFullOpen = true;
        }
      },
      closeGraphFull: function () {
        if (this.graphFullOpen) { this.graphFullOpen = false; return; }
        if (typeof this.goBack === 'function') this.goBack();
      },
      // F11 (L-F11S-3, §16/D4): initial focus на полноэкранном диалоге графа —
      // Esc/навигация с клавиатуры работают без мыши (preventScroll ≠ прыжок).
      _focusGraphFull: function () {
        var el = this.$refs && this.$refs.graphFullPanel;
        if (!el || typeof el.focus !== 'function' || !this.graphFullVisible) return;
        try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
      },
      destroyCognitionGraph: function () {
        if (this.cognitionNetwork) {
          try { this.cognitionNetwork.destroy(); } catch (e) { /* noop */ }
          this.cognitionNetwork = null;
        }
        this._cognitionGraphSig = null;
        this._cognitionGraphMode = null;
        if (typeof this.graphClearDetail === 'function') this.graphClearDetail();
      },
      // ── Polling 15с с паузой при document.hidden (F5-Q3, R10.11-5) ─────
      // D2/R10.18: единый старт таймера БЕЗ раннего выхода по cognitionTimer
      // (нужен restore-пути после stop — иначе ускоренный 5с остаётся
      // навсегда). `ms` по умолчанию — базовые 15с.
      _startCognitionTimer: function (ms) {
        var self = this;
        if (typeof document !== 'undefined' && document.hidden) return;
        this.cognitionTimer = setInterval(function () {
          if (typeof document !== 'undefined' && document.hidden) return;
          self.loadCognition();
        }, ms || 15000);
      },
      startCognitionPolling: function () {
        if (!this.isGlobalAdmin || this.cognitionTimer) return;
        this._startCognitionTimer(15000);
      },
      stopCognitionPolling: function () {
        if (this.cognitionTimer) {
          clearInterval(this.cognitionTimer);
          this.cognitionTimer = null;
        }
        if (this._cognitionPollRestore) {
          clearTimeout(this._cognitionPollRestore);
          this._cognitionPollRestore = null;
        }
        // S10.18-26: ретраи ручного POST тоже снимаются при уходе с вкладки.
        if (Array.isArray(this._cognitionRetryTimers)
            && this._cognitionRetryTimers.length) {
          this._cognitionRetryTimers.forEach(function (t) { clearTimeout(t); });
          this._cognitionRetryTimers = [];
        }
      },
      // F2 (spec §4.6, T-1720): ретраи cognition после ручного POST — не
      // ждём polling 15с. Без WebSocket/живого tick-таймера (ADR-1017-3 §2.6).
      // S10.18-26: хэндлы сохраняются в state и снимаются в
      // stopCognitionPolling (иначе 3 запроса уходили вне вкладки).
      _retryCognition: function (delays) {
        var self = this;
        if (!Array.isArray(this._cognitionRetryTimers)) {
          this._cognitionRetryTimers = [];
        }
        (delays || []).forEach(function (ms) {
          var h = setTimeout(function () { self.loadCognition(); }, ms);
          self._cognitionRetryTimers.push(h);
        });
      },
      // D2/R10.18: вернуть БАЗОВЫЕ 15с после временного ускорения. Вызов
      // startCognitionPolling() здесь раннеретурнил (cognitionTimer ещё жив)
      // → 5с-таймер оставался навсегда.
      // S10.18-22: базовый 15с стартует ТОЛЬКО на вкладке «Статус»; вне неё
      // restore лишь останавливает таймеры (инвариант F5/R10.11-5 «вне
      // Статуса — стоп»).
      _restoreCognitionPolling: function () {
        this.stopCognitionPolling();
        if (this.activeTab !== 'status') return;
        this._startCognitionTimer(15000);
      },
      // F2 (spec §4.6, T-1720): временно ускорить polling (5с) на время
      // ручного прогона и вернуть базовые 15с через `restoreMs`.
      // R10.18 / R2-1: гейт `activeTab === 'status'` снят — кнопка «Запустить
      // синтез сейчас» живёт на вкладке «Модули», поэтому ускорение обязано
      // стартовать сразу после POST, независимо от вкладки (иначе вызов
      // оставался мёртвым). «Вечного 5с вне вкладки» нет: `setTab` при любом
      // уходе зовёт `stopCognitionPolling`, который снимает и interval, и
      // restore-таймер (см. `setTab` и `stopCognitionPolling`).
      restartCognitionPolling: function (intervalMs, restoreMs) {
        if (!this.isGlobalAdmin) return;
        var self = this;
        this.stopCognitionPolling();
        this._startCognitionTimer(intervalMs || 15000);
        if (restoreMs) {
          this._cognitionPollRestore = setTimeout(function () {
            self._cognitionPollRestore = null;
            self._restoreCognitionPolling();
          }, restoreMs);
        }
      },
      // F2/AMEND ADR-1025-12 D1 (T-2585): Liquid Glass уровень A — преломление
      // на ФОРГРАУНД-линзе (`filter: url(#lg-lens)`), НЕ на backdrop
      // url-фильтре (WebKit его не поддерживает). Выбор — чистая
      // feature-detect, без UA-gate (WKWebView/iOS-Edge учитываются честно).
      _liquidGlassSupported: function () {
        try {
          var win = (typeof window !== 'undefined' && window) || {};
          var css = win.CSS;
          if (!css || typeof css.supports !== 'function') return false;
          return css.supports('filter', 'url(#lg-lens)');
        } catch (e) { return false; }
      },
      // Ручной откат/диагностика (env-only через GET /api/me.ui_flags).
      _glassTierOverride: function () {
        var flags = (this.me && this.me.ui_flags) || {};
        var v = String(flags.UI_GLASS_TIER_OVERRIDE || 'auto').toLowerCase();
        return (v === 'a' || v === 'b' || v === 'c') ? v : 'auto';
      },
      // Перф-кап числа узлов tier A (env-only, default 6; min 1) — заменяет
      // старое правило min-стороны ≥240 (оно отсекало низкие панели).
      _lensMaxNodes: function () {
        var flags = (this.me && this.me.ui_flags) || {};
        var n = parseInt(flags.UI_LENS_MAX_NODES, 10);
        return (isFinite(n) && n > 0) ? n : 6;
      },
      _prefersReducedMotion: function () {
        if (this.reducedMotion) return true;
        try {
          return !!(window.matchMedia &&
            window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        } catch (e) { return !!this.reducedMotion; }
      },
      // T-2585: tier выбирается feature-detect + перф-кап (не UA, не min-240),
      // обратимо/транзитивно: `data-glass` (opt-in) НЕ переписывается, ведём
      // `data-glass-downgraded` + диагностические `data-glass-tier/-reason`.
      // Нет поддержки/бюджет/reduced-motion → честный B (не «пустое стекло»).
      reconcileLiquidGlass: function () {
        if (typeof document === 'undefined') return;
        // D-2/@Reviewer: ранний выход — скрытая вкладка.
        if (document.hidden) return;
        var nodes = document.querySelectorAll('[data-glass="a"]');
        if (!nodes.length) return;
        var supported = this._liquidGlassSupported();
        var override = this._glassTierOverride();
        var maxNodes = this._lensMaxNodes();
        var reduced = this._prefersReducedMotion();
        var active = 0;
        for (var i = 0; i < nodes.length; i++) {
          var el = nodes[i];
          var tier = 'b';
          var reason = 'fallback';
          if (!supported) reason = 'filter-unsupported';
          else if (override === 'c') reason = 'override-c';
          else if (override === 'b') reason = 'override-b';
          else if (reduced) reason = 'reduced-motion';
          else if (active >= maxNodes) reason = 'budget';
          else { tier = 'a'; reason = override === 'a' ? 'override-a' : 'auto'; }
          if (tier === 'a') {
            active++;
            el.removeAttribute('data-glass-downgraded');
          } else {
            el.setAttribute('data-glass-downgraded', '1');
          }
          el.setAttribute('data-glass-tier', tier);
          el.setAttribute('data-glass-reason', reason);
          // D-2: рост/смена размера allow-узла → пересчёт (b↔a), наблюдаем точечно.
          if (this._lgResizeObserver) {
            try { this._lgResizeObserver.observe(el); } catch (e) { /* no-op */ }
          }
        }
        // T-2583: R17-safe маркер выбранного tier (только числа/строки-флаги,
        // без контента и секретов) — используется диагностикой и live-гейтом.
        this.glassTierDiag = {
          supported: supported, override: override, maxNodes: maxNodes,
          active: active, reducedMotion: reduced,
        };
      },
      // Транзитивность (T-2540/@Reviewer): `[data-glass="a"]` достраивается
      // асинхронно (v-if/маршруты/данные). D-2/@Reviewer: троттлинг ≥250 мс,
      // ранний выход при document.hidden/отсутствии цели, scope `#app`,
      // ResizeObserver только на allow-узлы (не на весь body).
      _lgSchedule: function () {
        if (this._lgPending) return;
        var self = this;
        this._lgPending = true;
        var now = Date.now();
        var delay = 0;
        if (this._lgLastRun && (now - this._lgLastRun) < 250) {
          delay = 250 - (now - this._lgLastRun);
        }
        setTimeout(function () {
          self._lgPending = false;
          if (typeof document !== 'undefined' && document.hidden) return;
          self._lgLastRun = Date.now();
          self.reconcileLiquidGlass();
          // HOTFIX9 D5 (T-2817): поздние целевые узлы (селектор области и др.)
          // получают стекло по факту появления (идемпотентно).
          self._syncGlassLib();
        }, delay);
      },
      _initLiquidGlassObserver: function () {
        if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') {
          return;
        }
        if (this._lgObserver) return;
        var self = this;
        this._lgObserver = new MutationObserver(function () { self._lgSchedule(); });
        var root = document.getElementById('app') || document.body;
        if (root) {
          this._lgObserver.observe(root, {
            childList: true, subtree: true, attributeFilter: ['data-glass'],
          });
        }
        if (typeof ResizeObserver !== 'undefined') {
          this._lgResizeObserver = new ResizeObserver(function () {
            self._lgSchedule();
          });
        }
      },
      // D3/T-2609 (ADR-1025-12 D5): измеряем фактическую высоту sticky-шапки
      // (строка 1 + строка 2) и прокидываем в `--header-h` — резерв контента
      // и scroll-padding без «магических» ширинозависимых отступов.
      _initHeaderHeight: function () {
        if (typeof document === 'undefined') return;
        var apply = function () {
          try {
            var hdr = document.querySelector('header.header-sticky');
            if (!hdr) return;
            var h = Math.round(hdr.getBoundingClientRect().height);
            if (h > 0) {
              document.documentElement.style.setProperty('--header-h', h + 'px');
            }
          } catch (e) { /* no-op */ }
        };
        apply();
        if (typeof ResizeObserver !== 'undefined') {
          try {
            var hdr = document.querySelector('header.header-sticky');
            if (hdr && !this._headerObserver) {
              this._headerObserver = new ResizeObserver(apply);
              this._headerObserver.observe(hdr);
            }
          } catch (e) { /* no-op */ }
        }
      },
      // §10/T-2547: пауза дорогих фоновых эффектов при скрытии TMA.
      setBgPaused: function (paused) {
        try {
          document.documentElement.classList.toggle('lg-bg-paused', !!paused);
        } catch (e) { /* no-op: document недоступен */ }
        // HOTFIX9 D6: Dark Aurora Flow — стоп рендера при document.hidden.
        try {
          if (window.__AuroraFlow && window.__AuroraFlow.setPaused) {
            window.__AuroraFlow.setPaused(!!paused);
          }
        } catch (e2) { /* no-op */ }
      },
      // HOTFIX8 (ADR-1025-16 D3): UI_AURORA_BG_ENABLED=OFF → на <html> вешается
      // `bg-wash-legacy`, возвращающий прежний conic page-wash (§10/F2).
      // HOTFIX9 (ADR-1025-17 D6): UI_AURORA_FLOW_V2 (default ON) → один canvas
      // Dark Aurora Flow (`html.aurora-flow-v2`); legacy-слои выводятся из
      // активного пути. Default ON (aurora flow). Классы на documentElement —
      // вне Vue-разметки, синхронизируются вручную (CSP-safe).
      _syncBgLayer: function () {
        // round 10.26 (ADR-1026-3 D1/D4/D5): активный фон — полигональная сеть
        // на Canvas 2D (`__PolygonBackground`), если флаг ON и модуль загружен.
        // Иначе — прежний Dark Aurora Flow (hotfix9), но уже через сохранённый
        // `__AuroraFlowLegacy` (публичный `__AuroraFlow` — фасад Polygon).
        var polygon = !!this.polygonBgEnabled &&
          !!(window.__PolygonBackground &&
             typeof window.__PolygonBackground.start === 'function');
        var legacy = _legacyAuroraFlow();
        var flow = !!this.auroraFlowV2;
        var aurora = !!this.auroraBgEnabled;
        try {
          var de = document.documentElement;
          de.classList.toggle('polygon-bg', polygon);
          de.classList.toggle('aurora-flow-v2', !polygon && flow);
          de.classList.toggle('bg-wash-legacy', !polygon && !flow && !aurora);
        } catch (e) { /* no-op */ }
        try {
          if (polygon) {
            window.__PolygonBackground.start();   // единственный активный rAF
            if (legacy && typeof legacy.stop === 'function') legacy.stop();
          } else {
            if (window.__PolygonBackground &&
                typeof window.__PolygonBackground.stop === 'function') {
              window.__PolygonBackground.stop();  // снимает canvas из DOM
            }
            if (legacy) {
              if (flow) legacy.start(); else legacy.stop();
            }
          }
        } catch (e2) { /* no-op */ }
        if (typeof this._syncGlassLib === 'function') this._syncGlassLib();
      },
      // HOTFIX10 (ADR-1025-18 D1): vendored Liquid Glass применяется ТОЛЬКО к
      // изолированному декоративному `[data-glass-surface]` (см. glass.js).
      // Функциональные цели (селектор/⛶/карточка) стекло НЕ получают.
      // OFF (UI_LIQUID_GLASS_LIB, default) или отсутствие библиотеки → полный
      // cleanup без остаточных `.ps-glass*`.
      _syncGlassLib: function () {
        try {
          if (window.__LiquidGlass && typeof window.__LiquidGlass.sync === 'function') {
            window.__LiquidGlass.sync(!!this.liquidGlassLib);
          }
        } catch (e) { /* no-op */ }
      },
      onVisibilityChange: function () {
        // F2 (§10/T-2547): фон пауза — до ранних return'ов (activeTab/Dossier).
        this.setBgPaused(!!document.hidden);
        // hotfix6/C2 (T-2604): пауза/возобновление rAF-цикла сердебиения при
        // скрытии/возврате TMA (в существующем обработчике, без второго).
        if (document.hidden) this.stopHeartbeatCanvas();
        else this.startHeartbeatCanvas();
        // F2 (T-2540/D-2): вернулись из скрытия — пересчитать стекло (reconcile
        // пропускал работу при document.hidden).
        if (!document.hidden) this._lgSchedule();
        // F8: свернули/вернули мини-апп с открытой модалкой Досье —
        // приостанавливаем/возобновляем опрос пересборки (источник — сервер).
        if (this.dossierOpen) {
          if (document.hidden) {
            this.stopDossierRebuildPolling();
          } else {
            this.resumeDossierRebuild();
          }
        }
        if (this.activeTab !== 'status') return;
        if (document.hidden) {
          this.stopCognitionPolling();
        } else {
          this.loadCognition();
          this.startCognitionPolling();
        }
      },

      // Алиасы spec §3.6.3 (имена фронт-аудита G4)
      dreamBeliefsLoader: function () { return this.loadDreamBeliefs(); },
      nostalgiaLogLoader: function () { return this.loadNostalgiaLog(); },

      // ═══ Переезд чата и per-chat админы (C2: D5/D8/Q9, глобальный admin) ═══

      // POST /chat_lore/{id}/remap {new_chat_id} — merge-семантика: лор и
      // админы переезжают на новый chat_id, старый профиль удаляется.
      remapChat: async function () {
        var p = this.chatLoreProfile;
        if (!p || !this.isGlobalAdmin || this.remapBusy || this.adminsBusy) return;
        var newId = parseInt(this.remapNewChatId, 10);
        if (String(this.remapNewChatId).trim() === '' || !isFinite(newId)) {
          this.toast('Укажите новый chat_id (число)', 'warn');
          return;
        }
        if (newId === p.chat_id) {
          this.toast('Новый chat_id совпадает с текущим', 'warn');
          return;
        }
        if (!window.confirm('Перенести лор/админов на новый chat_id? Старый профиль будет удалён')) return;
        this.remapBusy = true;
        try {
          var res = await this.api('/api/chat_lore/' + p.chat_id + '/remap', {
            method: 'POST',
            body: JSON.stringify({ new_chat_id: newId }),
          });
          this.remapNewChatId = '';
          if (res && res.status === 'ok') {
            this.toast('Чат ' + p.chat_id + (res.merged
              ? ' объединён с ' + newId : ' переехал в ' + newId), 'ok');
          }
          this.chatAdmins = [];
          // старый chat_id исчез из списка — перечитываем и выбираем новый
          await this.loadChats();
          var found = this.chatLoreChats.some(function (c) {
            return c.chat_id === newId;
          });
          if (found) this.loadProfile(newId);
        } catch (e) {
          if (e.status === 422) {
            this.toast('Новый chat_id совпадает с текущим (422)', 'warn');
          } else {
            this.toast('Ошибка переезда: ' + this.loreErrText(e), 'err');
          }
        } finally {
          this.remapBusy = false;
        }
      },

      // GET /chat_lore/admins?chat_id=… — плоский список telegram_id (по
      // факту API: store.list_chat_admins → list[int], ORDER BY telegram_id).
      loadChatAdmins: async function (chatId) {
        if (chatId == null || chatId === '') return;
        var epoch = this.scopeEpoch;   // R1: снимок scope
        this.adminsBusy = true;
        try {
          var data = await this.api('/api/chat_lore/admins?chat_id=' + chatId);
          if (!this._scopeGuard(epoch)) return;   // R1: устаревший ответ
          this.chatAdmins = Array.isArray(data) ? data : [];
        } catch (e) {
          if (!this._scopeGuard(epoch)) return;   // R2: устаревшая ошибка
          this.chatAdmins = [];
          if (e.status !== 401 && e.status !== 403) {
            this.toast('Не удалось загрузить админов чата: '
              + this.loreErrText(e), 'err');
          }
        } finally {
          // R3: не сбрасываем busy устаревшего запроса (его владеет новый).
          if (this._scopeGuard(epoch)) this.adminsBusy = false;
        }
      },

      // POST /chat_lore/admins {chat_id, telegram_id} (только глобальный admin)
      addChatAdmin: async function () {
        var p = this.chatLoreProfile;
        if (!p || !this.isGlobalAdmin || this.adminsBusy || this.remapBusy) return;
        var tid = parseInt(this.newChatAdminId, 10);
        if (String(this.newChatAdminId).trim() === '' || !isFinite(tid)
            || tid <= 0) {
          this.toast('Укажите telegram_id (число)', 'warn');
          return;
        }
        this.adminsBusy = true;
        try {
          var res = await this.api('/api/chat_lore/admins', {
            method: 'POST',
            body: JSON.stringify({ chat_id: p.chat_id, telegram_id: tid }),
          });
          if (res && res.added === false) {
            this.toast('telegram_id ' + tid + ' уже админ чата', 'warn');
          } else {
            this.toast('Админ ' + tid + ' добавлен', 'ok');
            this.newChatAdminId = '';
          }
          await this.loadChatAdmins(p.chat_id);
        } catch (e) {
          this.toast('Ошибка добавления админа: ' + this.loreErrText(e), 'err');
        } finally {
          this.adminsBusy = false;
        }
      },

      // DELETE /chat_lore/admins?chat_id=…&telegram_id=… (глобальный admin)
      removeChatAdmin: async function (telegramId) {
        var p = this.chatLoreProfile;
        if (!p || !this.isGlobalAdmin || this.adminsBusy || this.remapBusy) return;
        if (!window.confirm('Удалить админа чата ' + telegramId + ' из ' + p.chat_id + '?')) return;
        this.adminsBusy = true;
        try {
          var res = await this.api(
            '/api/chat_lore/admins?chat_id=' + p.chat_id
            + '&telegram_id=' + telegramId,
            { method: 'DELETE' });
          this.toast(res && res.removed === false
            ? 'Админ уже удалён'
            : 'Админ ' + telegramId + ' удалён', 'ok');
          await this.loadChatAdmins(p.chat_id);
        } catch (e) {
          this.toast('Ошибка удаления админа: ' + this.loreErrText(e), 'err');
        } finally {
          this.adminsBusy = false;
        }
      },
      loreFieldLabel: function (field) {
        var map = {
          manual: 'ручной лор', auto: 'авто-лор',
          auto_enabled: 'автогенерация', auto_period_hours: 'период',
          auto_window_hours: 'окно', remap: 'переезд',
          chat_admin: 'админ чата',
        };
        return map[field] || field;
      },
      changedByLabel: function (row) {
        if (row && row.is_ai) return 'бот/ИИ';
        return 'telegram_id: '
          + (row && row.changed_by != null ? row.changed_by : '?');
      },
      truncateLore: function (text, cap) {
        var t = String(text == null ? '' : text);
        if (t.length <= cap) return t;
        return t.slice(0, cap).replace(/\s+$/, '') + '\n…[обрезано]';
      },
      // Простейший построчный diff old/new БЕЗ библиотек (3.10): строки,
      // которые есть только в old → del (красным), только в new → add.
      diffLines: function (oldText, newText) {
        var self = this;
        var splitCut = function (t) {
          var lines = self.truncateLore(t, 300).split('\n');
          if (lines.length === 1 && lines[0] === '') return [];
          return lines;
        };
        var oldLines = splitCut(oldText), newLines = splitCut(newText);
        var oldSet = {}, newSet = {};
        oldLines.forEach(function (l) { oldSet[l] = true; });
        newLines.forEach(function (l) { newSet[l] = true; });
        return {
          old: oldLines.map(function (l) {
            return { text: l, del: !newSet[l] };
          }),
          new: newLines.map(function (l) {
            return { text: l, add: !oldSet[l] };
          }),
        };
      },
      // Алиасы имён C-части (loadLoreChats/saveLoreManual/…) — поведение
      // то же; spec §3.10 использует краткие имена выше.
      loadLoreChats: function (probe) { return this.loadChats(probe); },
      selectLoreChat: function (chatId) { return this.loadProfile(chatId); },
      saveLoreManual: function () { return this.saveManual(); },
      saveLoreSettings: function () { return this.saveSettings(); },
      loreGenerate: function () { return this.generateNow(); },
      loreClearAuto: function () { return this.clearAuto(); },
      loreLoadHistory: function () { return this.loadHistory(); },
      openLoreHistory: function () { return this.loadHistory(); },
    },

    // 3.5.2: KV-редактор (kv-editor) получает доступ к корню — api/toast/
    // saving/loadConfig из компонента (provide/inject).
    provide: function () {
      return { root: this };
    },

    beforeUnmount: function () {
      this.stopStatusPolling();
      this.stopCognitionPolling();     // F5/R10.11-5: нет stale-таймера
      this.stopDossierFeedPolling();   // 10.20 (T-1897): нет stale-таймера
      this.stopDossierRebuildPolling(); // F8: нет stale-таймера пересборки
      this.destroyCognitionGraph();
      // F24 (ADR-1024-24 C4): снимаем подписки TMA-fullscreen при unmount.
      this.teardownFullscreen();
      // ISSUE-7: снимаем visibilitychange-листенер (F5-Q3) при unmount.
      if (_onVisibility) {
        document.removeEventListener('visibilitychange', _onVisibility);
        _onVisibility = null;
      }
      // F1 (§6/§7): снимаем resize-листенер shell-режима.
      if (_onResize) {
        window.removeEventListener('resize', _onResize);
        _onResize = null;
      }
      // HOTFIX10 (ADR-1025-18 D5): снимаем visualViewport-листенер фона.
      if (_onVV) {
        try {
          if (window.visualViewport
              && typeof window.visualViewport.removeEventListener === 'function') {
            window.visualViewport.removeEventListener('resize', _onVV);
          }
        } catch (e) { /* no-op */ }
        _onVV = null;
      }
      // F2 (T-2540/D-2): снимаем DOM/Resize-observer уровня A стекла.
      if (this._lgObserver) {
        this._lgObserver.disconnect();
        this._lgObserver = null;
      }
      if (this._lgResizeObserver) {
        this._lgResizeObserver.disconnect();
        this._lgResizeObserver = null;
      }
      // hotfix6/C2 (D4): останавливаем Canvas-2D rAF-цикл сердебиения.
      this.stopHeartbeatCanvas();
      // D3/T-2609: снимаем ResizeObserver высоты шапки.
      if (this._headerObserver) {
        try { this._headerObserver.disconnect(); } catch (e) { /* no-op */ }
        this._headerObserver = null;
      }
      if (this.controlTimer) clearInterval(this.controlTimer);
    },
  });

  // ═══ KV-редактор (3.5.2/FR-24-25): поля c widget='keyvalue' ═══
  // Пары «Telegram ID → имя» в локальном массиве; рендер — x-template
  // #kv-editor-tpl (index.html). Сборка объекта при сохранении, POST как
  // у saveKeyItem, перезагрузка loadConfig() после успеха.
  app.component('kv-editor', {
    name: 'kv-editor',
    inject: ['root'],
    props: {
      item: { type: Object, required: true },
      canEdit: { type: Boolean, default: false },
    },
    data: function () {
      return { pairs: [], maxPairs: 200 };
    },
    created: function () { this.sync(); },
    watch: {
      // F10 (10.24, ADR-1024-11 D2): prop `item` — shallowReactive-объект;
      // строковый путь 'item.value' не переживает замену `configItems`
      // (новый массив/объекты) и не видит вложенные мутации. deep+immediate
      // по самому `item` — надёжная инициализация и при монтировании, и при
      // любом изменении/замене значения. Гейт kill-switch.
      item: {
        handler: function () {
          if (this._renderEnabled()) this.sync();
        },
        deep: true,
        immediate: true,
      },
      // Kill-switch OFF → прежний (сломанный) watcher по пути — только для
      // аварийного сопоставления (default ON).
      'item.value': function () {
        if (!this._renderEnabled()) this.sync();
      },
    },
    computed: {
      // F10 (ADR-1024-11 D3): индикатор источника эффективного значения —
      // per-chat override («значение чата») либо глобальный слой.
      sourceLabel: function () {
        return (this.item && this.item.chat_source === 'chat')
          ? 'значение чата' : 'глобально';
      },
      // F10 (spec §3.2; review iter1 Low): индикатор использует и
      // `global_value` — подсказка поясняет, что значение пришло из
      // глобального слоя (в chat-скоупе API всегда отдаёт global_value-объект).
      sourceHint: function () {
        var it = this.item || {};
        if (it.chat_source === 'chat') {
          return 'Значение переопределено для этого чата';
        }
        if (it.global_value && typeof it.global_value === 'object') {
          return 'Значение из глобального слоя';
        }
        return 'Глобальное значение';
      },
      // id непустой в одной паре при пустом имени (или наоборот) — ошибка
      partialRows: function () {
        return this.pairs.filter(function (p) {
          return (String(p.id).trim() === '') !== (String(p.name).trim() === '');
        });
      },
      dupId: function () {
        var seen = {};
        for (var i = 0; i < this.pairs.length; i++) {
          var id = String(this.pairs[i].id).trim();
          if (!id) continue;
          if (seen[id]) return id;
          seen[id] = true;
        }
        return '';
      },
      // Критичная ошибка — Save disabled и подсветка
      issueText: function () {
        if (this.partialRows.length) return 'Заполните ID и имя в каждой строке';
        if (this.dupId) return 'Дублируется Telegram ID: ' + this.dupId;
        return '';
      },
      // Предупреждение (не блок): id не выглядят числами (могут быть и не
      // user_id — например, другие ключи словаря)
      warnText: function () {
        for (var i = 0; i < this.pairs.length; i++) {
          var id = String(this.pairs[i].id).trim();
          if (id && numericId(id) === null) {
            return 'Есть нечисловые ID — сохранятся как строки';
          }
        }
        return '';
      },
    },
    methods: {
      // F10 (ADR-1024-11 D5): kill-switch `ALIASES_KEYSVALUE_RENDER_ENABLED`
      // (env-only, default ON; доставка — /api/me.ui_flags). Безопасный
      // дефолт ON, если корень/флаг недоступны (как uiFlag).
      _renderEnabled: function () {
        if (this.root && typeof this.root.uiFlag === 'function') {
          return this.root.uiFlag('ALIASES_KEYSVALUE_RENDER_ENABLED');
        }
        return true;
      },
      // Инициализация/пересборка пар из объекта-значения item.value
      sync: function () {
        var raw = this.item && this.item.value;
        // F2 round1022: backend может отдать строку-JSON (двойное
        // кодирование jsonb) — распаковываем до объекта (до 2 уровней).
        // Не-JSON строка/массив/скаляр → безопасно пусто (fallback).
        var src = raw;
        var guard = 0;
        while (typeof src === 'string' && guard < 2) {
          try {
            src = JSON.parse(src);
          } catch (e) {
            src = null;
            break;
          }
          guard++;
        }
        var pairs;
        if (Array.isArray(src)) {
          // F10 (ADR-1024-11 D2): backend может отдать массив пар
          // [[key, value], …] — поддерживаем; прочие массивы → пусто.
          pairs = [];
          for (var i = 0; i < src.length; i++) {
            var row = src[i];
            if (Array.isArray(row) && row.length >= 2) {
              pairs.push({
                id: String(row[0]),
                name: String(row[1] == null ? '' : row[1]),
              });
            }
          }
        } else {
          if (!src || typeof src !== 'object') src = {};
          pairs = Object.keys(src).map(function (k) {
            return { id: String(k), name: String(src[k] == null ? '' : src[k]) };
          });
        }
        // 3.5.2/W2: порядок объекта-значения сохраняется (как в JSON/PG),
        // без сортировки; новые строки добавляются в конец (addRow).
        this.pairs = pairs;
      },
      addRow: function () {
        if (this.pairs.length >= this.maxPairs) {
          this.root.toast('Слишком много строк (максимум ' + this.maxPairs + ')', 'warn');
          return;
        }
        this.pairs.push({ id: '', name: '' });
      },
      removeRow: function (i) {
        this.pairs.splice(i, 1);
      },
      idBad: function (id) {
        var v = String(id).trim();
        return !!v && v === this.dupId;
      },
      // Частично заполненная пара: вернуть имя пустого поля ('id'/'name'),
      // иначе '' (для подсветки в шаблоне).
      emptyField: function (p) {
        var id = String(p.id).trim(), name = String(p.name).trim();
        if (!id && name) return 'id';
        if (id && !name) return 'name';
        return '';
      },
      save: async function () {
        if (this.issueText) {
          this.root.toast(this.issueText, 'err');
          return;
        }
        var obj = {};
        this.pairs.forEach(function (p) {
          var id = String(p.id).trim();
          var name = String(p.name).trim();
          if (!id && !name) return;        // пустая строка → игнорируется
          obj[id] = name;
        });
        var key = this.item.key;
        this.root.saving.add(key);
        try {
          await this.root.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({ items: [{ key: key, value: obj }] }),
          });
          this.root.toast('Сохранено: ' + (this.item.title || key), 'ok');
          await this.root._preserveScroll(this.root.loadConfig);
        } catch (e) {
          this.root.toast('Ошибка сохранения: ' + e.message, 'err');
        } finally {
          this.root.saving.delete(key);
        }
      },
    },
    template: '#kv-editor-tpl',
  });

  // ═══ Раунд 10.12 (ADR-1012-1 D4): список строк (widget='list') ═══
  // Каждая фраза — отдельное плотное поле; add/delete; save → saveConfigItem
  // (учитывает per-chat/global routing). Значение item.value — массив строк.
  app.component('list-editor', {
    name: 'list-editor',
    inject: ['root'],
    props: {
      item: { type: Object, required: true },
      canEdit: { type: Boolean, default: false },
      // F7 (M-F7-2, §64): variant='ids' — списки ID Оли (подписи «ID», не
      // «фразы»); '' — дефолт Костика (строки-фразы). Дефолтный текст живёт
      // в шаблоне `#list-editor-tpl` (не переписывается).
      variant: { type: String, default: '' },
    },
    data: function () {
      // rowIds — стабильные ключи строк для v-for :key (не index: удаление
      // середины не «сдвигает» DOM/фокус). _nextRowId — монотонный счётчик.
      return { rows: [], rowIds: [], maxRows: 100, _nextRowId: 1 };
    },
    created: function () { this.sync(); },
    watch: {
      'item.value': function () { this.sync(); },
    },
    methods: {
      // item.value: массив строк (json-параметр с widget='list') ЛИБО
      // JSON-строка (старые данные) → массив.
      sync: function () {
        var raw = this.item && this.item.value;
        var list = [];
        if (Array.isArray(raw)) list = raw.slice();
        else if (typeof raw === 'string' && raw.trim()) {
          try { list = JSON.parse(raw); } catch (e) { list = []; }
        }
        if (!Array.isArray(list)) list = [];
        this.rows = list.map(function (x) {
          return (x == null) ? '' : String(x);
        });
        if (this._nextRowId == null) this._nextRowId = 1;
        this.rowIds = this.rows.map(function () {
          return this._nextRowId++;
        }, this);
      },
      addRow: function () {
        if (this.rows.length >= this.maxRows) {
          this.root.toast('Слишком много фраз (максимум ' + this.maxRows + ')', 'warn');
          return;
        }
        this.rows.push('');
        if (this._nextRowId == null) this._nextRowId = 1;
        this.rowIds.push(this._nextRowId++);
      },
      removeRow: function (i) {
        this.rows.splice(i, 1);
        this.rowIds.splice(i, 1);
      },
      save: async function () {
        var self = this;
        // Защита от «минимального» контекста (юнит-тесты вызывают метод
        // напрямую): без toStoredValue — прежнее поведение (строка).
        var conv = (typeof self.toStoredValue === 'function')
          ? function (x) { return self.toStoredValue(x); }
          : function (x) { return x; };
        var cleaned = [];
        this.rows.forEach(function (r) {
          if (r == null) return;
          var v = String(r).trim();
          if (v) cleaned.push(conv(v));  // пустые строки отбрасываются
        });
        this.item.value = cleaned;           // json-массив без парсинга
        await this.root.saveConfigItem(this.item);
      },
      // H-F7-7 (§64): список строк — это ФРАЗЫ (Костик) ИЛИ ID (Оля). Списки
      // ID сервер сравнивает с int (`origin.chat.id`/`sender_user.id` в
      // `filters/olya_video.py`), поэтому для ключей из
      // `PERMSOC_LIST_WIDGET_KEYS` возвращаем числовой тип (чисто-числовые
      // строки → Number), нечисловые остаются строками; фразы Костика не
      // затронуты.
      _numericList: function () {
        return !!(this.item && PERMSOC_LIST_WIDGET_KEYS[this.item.key]);
      },
      toStoredValue: function (s) {
        if (this._numericList && this._numericList() && /^-?\d+$/.test(s)) {
          var n = Number(s);
          if (Number.isSafeInteger(n)) return n;
        }
        return s;
      },
    },
    template: '#list-editor-tpl',
  });

  // ═══ Раунд 10.20 (БЛОК 3.6/T-1900): sticky-save panel ══════════════════
  // Одна закреплённая панель «Отмена» / «Сохранить изменения» в модалках и
  // конфиг-вкладках. Dirty-поля считает root (configSnapshot vs configItems),
  // тумблеры/select — мгновенный auto-save (saveConfigItem) и в dirty не
  // попадают до следующей загрузки каталога.
  app.component('sticky-save', {
    name: 'sticky-save',
    inject: ['root'],
    props: {
      label: { type: String, default: 'Сохранить изменения' },
    },
    computed: {
      dirtyCount: function () { return this.root.stickyDirtyCount || 0; },
      // F0 (ревью, T-2416/T-2437): единое состояние формы из root.saveState,
      // а не набор независимых флагов. Корневой `saveState` — Vue computed
      // (на инстансе это ЗНАЧЕНИЕ-строка, не функция); поддерживаем и
      // функцию — на случай стаба/иного контракта (образец — stickyDirtyCount).
      saveState: function () {
        var s = this.root.saveState;
        if (typeof s === 'function') { s = s.call(this.root); }
        return s || (this.dirtyCount ? 'dirty' : 'clean');
      },
      stateLabel: function () {
        // F9 (ADR-1025-22 D6)/L-F9S-2: подписываем только состояния, которые
        // реально отдаёт root.saveState (loading|saving|conflict|error|dirty|
        // clean). `saved` здесь НЕ отображается: после подтверждения сервера
        // F0 переходит в `clean`, а «Сохранено» доставляет тост F0 (мёртвую
        // ветку не держим).
        var map = { clean: '', loading: 'Загрузка…', dirty: 'Есть изменения',
                    saving: 'Сохранение…',
                    error: 'Ошибка сохранения',
                    conflict: 'Конфликт версии' };
        return map[this.saveState] || '';
      },
      saving: function () {
        return this.saveState === 'saving' || !!this.root.stickySaving;
      },
      active: function () { return this.dirtyCount > 0; },
      // S10.20-6: поля, которые не сохранились (ошибка/409) — подсветка.
      failed: function () { return this.root.stickyFailed || []; },
    },
    methods: {
      cancel: function () { this.root.cancelModalEdits(); },
      save: function () { this.root.saveModalEdits(); },
    },
    template:
      '<div class="sticky-save" role="group" aria-label="Сохранение изменений"'
      + ' :data-save-state="saveState">'
      + '<span class="sticky-save__count">'
      + '{{ dirtyCount ? ("Изменено: " + dirtyCount) : "Нет изменений" }}'
      + '</span>'
      + '<span v-if="stateLabel" class="sticky-save__state">{{ stateLabel }}</span>'
      + '<span v-if="failed.length" class="sticky-save__failed">'
      + 'Не сохранено: {{ failed.join(", ") }}</span>'
      + '<button class="btn-ghost text-sm" type="button"'
      + ' :disabled="saving || !active" @click="cancel">Отмена</button>'
      + '<button class="btn-accent text-sm" type="button"'
      + ' :disabled="saving || !active" @click="save">'
      + '{{ saving ? "Сохранение…" : label }}</button>'
      + '</div>',
  });

  // ═══ F9 (10.25, ADR-1025-22 D1/D3/D4): единый компонент секрет-поля ═══════
  // Маска — DISPLAY-индикатор (не значение input, §50/R17): заголовок → тех.
  // ключ → описание → индикатор → пустой password-инпут + reveal →
  // «Заменить»/«Удалить». Zero-build (template: #secret-field-tpl), без
  // библиотек. Используется и для generic-ключей (`scope='global'`), и для
  // provider-блоков, и для BYOK (`scope='chat'`).
  app.component('secret-field', {
    name: 'secret-field',
    inject: ['root'],
    props: {
      title: { type: String, default: '' },
      techKey: { type: String, default: '' },
      description: { type: String, default: '' },
      configured: { type: Boolean, default: false },
      last4: { type: String, default: '' },
      draft: { type: String, default: '' },
      scope: { type: String, default: 'global' },
      disabled: { type: Boolean, default: false },
      placeholder: { type: String, default: 'Ключ…' },
      replaceLabel: { type: String, default: 'Заменить' },
    },
    data: function () {
      return { reveal: false };
    },
    computed: {
      // D1/D3: display-индикатор — `••••••••last4` / «Ключ установлен» /
      // «Не настроен». Значение поля НИКОГДА не равно маске.
      // L-F9S-1: единый источник форматирования — `secretDisplayOf`
      // (дубль строки маски устранён; display-строка, не значение input).
      maskText: function () {
        return secretDisplayOf({ configured: this.configured, last4: this.last4 })
          .maskText;
      },
      inputType: function () { return this.reveal ? 'text' : 'password'; },
      deleteLabel: function () {
        return this.scope === 'chat' ? 'Удалить ключ чата' : 'Удалить';
      },
    },
    methods: {
      onInput: function (e) {
        this.$emit('update:draft', e && e.target ? e.target.value : '');
      },
      // Замена = ввод нового значения + SaveBar; кнопка лишь фокусирует поле.
      replace: function () {
        var el = this.$refs.secretInput;
        if (el && typeof el.focus === 'function') el.focus();
        this.$emit('replace');
      },
      onDelete: function () { this.$emit('delete'); },
      toggleReveal: function () { this.reveal = !this.reveal; },
      iconGlyph: function (name) {
        if (this.root && typeof this.root.iconGlyph === 'function') {
          return this.root.iconGlyph(name);
        }
        return '';
      },
    },
    template: '#secret-field-tpl',
  });

  app.mount('#app');

  function ApiError(status, message) {
    this.status = status;
    this.message = message;
    this.name = 'ApiError';
  }
})();
