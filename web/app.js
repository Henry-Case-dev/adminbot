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
      ],
      sections: [
        { title: 'Основные модели', category: 'models',
          groups: ['models_main'] },
        { title: 'Ключи', category: 'keys',
          groups: ['keys_llm', 'keys_groq', 'keys_openrouter'] },
        { title: 'Фолбэк', category: 'models', groups: ['models_fallback'] },
        { title: 'Расширенные', category: null, groups: [
            'models_embeddings', 'models_llm_timeouts', 'models_llm_guard',
            'models_extra_providers', 'models_video_summary',
            'keys_search', 'keys_media'] },
      ] },
    { id: 'prompts', icon: 'description', label: 'Промпты', type: 'config', menu: 'ai',
      sources: [
        { category: 'prompts', groups: null },
      ] },
    // ── Раунд 10.6 (T-1165/T-1201): 11 модулей (config-источники для окна) ──
    { id: 'mod_summary', icon: 'description', label: 'Саммаризация',
      type: 'config', menu: 'modules',
      sources: [
        { category: 'flags', groups: ['flags_module_summary', 'flags_summary'] },
        { category: 'limits', groups: ['limits_summary'] },
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
        { category: 'limits', groups: ['limits_checkup', 'limits_service',
            'limits_worker'] },
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
    // Список-витрина 11 модулей (не config; карточки + модалки).
    { id: 'modules', icon: 'extension', label: 'Модули', type: 'modules',
      menu: 'modules' },
    { id: 'memory_rag', icon: 'memory', label: 'Память', type: 'config',
      menu: 'ai',
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
      type: 'relations', menu: 'ai',
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
      menu: 'ai',
      sources: [
        { category: 'limits', groups: ['limits_lore'] },
        { category: 'flags', groups: ['flags_lore'] },
      ] },
    { id: 'status', icon: 'monitoring', label: 'Статус', type: 'status', always: true,
      menu: 'home' },
    { id: 'info', icon: 'help', label: 'Справка', type: 'info',
      always: true, menu: 'home' },
    // Раунд 10 (F-12): точка интеграции Oversight (только global admin).
    { id: 'oversight', icon: 'radar', label: 'Сводка', type: 'oversight',
      menu: 'home' },
  ];

  var LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
  var MAX_HISTORY_POINTS = 288;   // B1/T-1129: 24ч × 5 мин
  // 10.10 (п.2, ADR-1010-2): временная сетка графика истории ключей.
  var SAMPLE_BUCKET = 300;        // 5 мин — тот же бакет, что пишет ring
  var MIN_BUCKETS = 12;           // минимум 1 час даже при 1-2 сэмплах
  // D4: порядок секций матрицы прав = порядок config-вкладок (19; §4.3).
  var TAB_SECTION_ORDER = [
    'mod_summary', 'mod_direct', 'mod_factcheck', 'mod_search',
    'mod_transcribe', 'mod_video_summary', 'mod_media_download', 'mod_web',
    'mod_checkup', 'mod_sleep', 'mod_nostalgia', 'llm_providers', 'prompts',
    'memory_rag', 'smart_cache', 'people_names', 'relations', 'chat_lore',
    'permsoc',
  ];

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

  // ═══ Раунд 10.6 (A2/T-1165): «Модули» = ровно 11; toggle + окно ═══
  // toggleKey — pg-ключ master-флага (реальный гейт), tab — config-вкладка
  // с операционными группами модуля (generic-рендер в модалке).
  var MODULES = [
    { id: 'mod_summary', title: 'Саммаризация',
      subtitle: 'Пересказы разговоров и каналов', icon: 'description',
      toggleKey: 'flags.summary_enabled', tab: 'mod_summary' },
    { id: 'mod_direct', title: 'Прямые ответы',
      subtitle: 'Ответы бота на обращения', icon: 'smart_toy',
      toggleKey: 'flags.direct_chat_botword_enabled', tab: 'mod_direct' },
    { id: 'mod_factcheck', title: 'Фактчек',
      subtitle: 'Проверка фактов', icon: 'radar',
      toggleKey: 'flags.factcheck_enabled', tab: 'mod_factcheck' },
    { id: 'mod_search', title: 'Поиск',
      subtitle: 'Интернет-поиск', icon: 'grid_view',
      toggleKey: 'flags.search_enabled', tab: 'mod_search' },
    { id: 'mod_transcribe', title: 'Транскрипт голосовых и видео',
      subtitle: 'Распознавание речи', icon: 'play_circle',
      toggleKey: 'flags.enable_voice_transcription', tab: 'mod_transcribe' },
    { id: 'mod_video_summary', title: 'Выжимка видео',
      subtitle: 'Пересказ видео', icon: 'play_circle',
      toggleKey: 'flags.video_summary_enabled', tab: 'mod_video_summary' },
    { id: 'mod_media_download', title: 'Скачивание медиа',
      subtitle: 'Скачивание видео по ссылке', icon: 'cloud',
      toggleKey: 'flags.download_enabled', tab: 'mod_media_download' },
    { id: 'mod_web', title: 'Веб-страницы',
      subtitle: 'Пересказ страниц', icon: 'auto_stories',
      toggleKey: 'flags.webpage_enabled', tab: 'mod_web' },
    { id: 'mod_checkup', title: 'Диагностика',
      subtitle: 'Чекап, метрики и логи', icon: 'monitoring',
      toggleKey: 'flags.checkup_enabled', tab: 'mod_checkup' },
    { id: 'mod_sleep', title: 'Сон',
      subtitle: 'Синтез убеждений', icon: 'bedtime',
      toggleKey: 'memory.dream_enabled', tab: 'mod_sleep' },
    { id: 'mod_nostalgia', title: 'Ностальгия',
      subtitle: '«Кстати…» по старым сообщениям', icon: 'history',
      toggleKey: 'memory.nostalgia_enabled', tab: 'mod_nostalgia' },
  ];

  // A4/T-1207: «LLM Провайдеры» — блоки ПО МОДУЛЯМ (base_url+model+key).
  // role задаёт, какое поле тела POST /api/llm/test заполняет значение.
  // 10.9 (T-1303): «Название модели» — ПЕРВОЕ поле каждого блока; label'ы —
  // человеческие (spec §4.1/§4.2).
  var PROVIDER_BLOCKS = [
    { id: 'direct_main', title: 'Основная модель', modules: 'Прямые ответы',
      fields: [
        { key: 'models.llm_display_name', label: 'Название модели', role: '' },
        { key: 'models.llm_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.llm_model_name', label: 'Модель', role: 'model' },
        { key: 'keys.llm_api_key', label: 'Ключ', role: 'api_key', secret: true },
      ] },
    { id: 'direct_fallback', title: 'Фолбэк-модель',
      modules: 'Прямые ответы (фолбэк)',
      fields: [
        { key: 'models.llm_fallback_display_name', label: 'Название модели', role: '' },
        { key: 'models.llm_fallback_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.llm_fallback_model', label: 'Модель', role: 'model' },
        { key: 'keys.llm_fallback_api_key', label: 'Ключ', role: 'api_key', secret: true },
      ] },
    { id: 'transcribe_groq', title: 'Groq (расшифровка)', modules: 'Транскрибация',
      fields: [
        { key: 'models.groq_display_name', label: 'Название модели', role: '' },
        { key: 'models.groq_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.groq_transcribe_model', label: 'Модель', role: 'model' },
        { key: 'keys.groq_api_key', label: 'Ключ', role: 'api_key', secret: true },
      ] },
    { id: 'transcribe_openrouter', title: 'OpenRouter (запасной)',
      modules: 'Транскрибация (фолбэк)',
      fields: [
        { key: 'models.openrouter_display_name', label: 'Название модели', role: '' },
        { key: 'models.openrouter_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.openrouter_transcribe_model', label: 'Модель', role: 'model' },
        { key: 'keys.openrouter_api_key', label: 'Ключ', role: 'api_key', secret: true },
      ] },
    { id: 'video_summary_openrouter', title: 'Видео-модель (OpenRouter)',
      modules: 'Саммаризация видео',
      fields: [
        { key: 'models.openrouter_display_name', label: 'Название модели', role: '' },
        { key: 'models.openrouter_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.video_primary_model', label: 'Модель', role: 'model' },
        { key: 'keys.openrouter_api_key', label: 'Ключ', role: 'api_key', secret: true },
      ] },
    { id: 'embeddings', title: 'Эмбеддинги',
      modules: 'Поиск по памяти',
      // MAJOR-1: нет base_url/api-key в блоке → сетевой тест невозможен;
      // кнопка «Проверить» не рендерится (редактор — generic-группы ниже).
      testable: false,
      fields: [
        { key: 'models.embedding_display_name', label: 'Название модели', role: '' },
        { key: 'models.embedding_model_name', label: 'Модель', role: 'model' },
        { key: 'models.embedding_dim', label: 'Размер отпечатка', role: 'dim' },
      ] },
    { id: 'llm_guard', title: 'Таймауты и защита', modules: 'Общий',
      // MAJOR-1: не сетевой провайдер — тест-кнопки нет; значения не
      // отправляются как `model` (role '').
      testable: false,
      fields: [
        { key: 'models.llm_timeout', label: 'Сколько ждать ответ', role: '' },
        { key: 'models.llm_max_retries', label: 'Повторов', role: '' },
        { key: 'models.llm_total_budget', label: 'Общий дедлайн', role: '' },
      ] },
    { id: 'search_keys', title: 'Поиск: ключи', modules: 'Поиск',
      // MINOR-2: каждый ключ тестируется ОТДЕЛЬНО (search_keys:tavily/exa).
      perFieldTest: true,
      fields: [
        { key: 'keys.tavily_api_key', label: 'Ключ Tavily', role: 'api_key',
          secret: true, probeTarget: 'search_keys:tavily' },
        { key: 'keys.exa_api_key', label: 'Ключ Exa', role: 'api_key',
          secret: true, probeTarget: 'search_keys:exa' },
      ] },
    { id: 'media_share', title: 'Медиа-шара', modules: 'Саммаризация видео',
      fields: [
        { key: 'keys.media_share_secret', label: 'Секрет ссылок',
          role: 'api_key', secret: true },
      ] },
  ];

  // ═══ Раунд 10.9 (spec §1.2): PERMsoc owner-блоки ═══
  // Вкладка «PERMsoc» рендерится 4 collapsible <details class="owner-block">;
  // в каждом ровно ОДИН тумблер — в <summary> (generic-bool исключён телом).
  // Принадлежность: key ∈ owner.keys ИЛИ (group ∈ owner.groups и key не
  // заявлен ни одним персональным owner'ом). «Общее» получает остаток.
  var PERMSOC_OWNER_BLOCKS = [
    { id: 'slavik', title: 'Славик', icon: 'smart_toy',
      toggleKey: 'flags.slavik_enabled',
      keys: ['reactions.slavik_user_id', 'limits.slavik_mimic_min_words',
             'limits.slavik_mimic_cooldown', 'limits.gif_interval',
             'limits.slavic_photo_interval'],
      groups: ['reactions_slavik', 'reactions_deadpage', 'limits_deadpage'] },
    { id: 'olya', title: 'Оля', icon: 'play_circle',
      toggleKey: 'flags.olya_enabled',
      keys: ['reactions.olya_user_id', 'flags.olya_caption_enabled',
             'flags.olya_repost_enabled', 'flags.olya_always_send',
             'flags.olya_caption_mention_enabled', 'limits.olya_cooldown'],
      groups: ['reactions_olya'] },
    { id: 'mimic', title: 'Мимикрия', icon: 'psychology',
      toggleKey: 'flags.mimic_enabled',
      keys: ['reactions.mimic_victim_user_ids', 'limits.mimic_min_words',
             'limits.mimic_cooldown', 'flags.mimic_forwards_enabled',
             'reactions.alan_mimic_enabled', 'reactions.kucha_enabled'],
      groups: [] },
    { id: 'common', title: 'Общее / Мастер', icon: 'admin_panel_settings',
      toggleKey: 'flags.permsoc_enabled', keys: [], groups: [] },
  ];
  // Ключи-тумблеры рендерятся ТОЛЬКО в <summary> owner-блоков.
  var PERMSOC_TOGGLE_KEYS = {
    'flags.permsoc_enabled': true, 'flags.slavik_enabled': true,
    'flags.olya_enabled': true, 'flags.mimic_enabled': true,
  };

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

  function arr(x) { return Array.isArray(x) ? x : []; }

  // ═══ Hash-routing (T-1099, OD1/OD3/§6.3): route — источник истины ═══
  // Маршрут — ТОЛЬКО hash, начинающийся с '#/' (launch-hash tgWebAppData
  // игнорируется, §6.1/§6.2). vue-router НЕ используется (zero-build).
  // Ниже — чистые функции (routeToTab/tabToRoute/routeParent/routeDepth),
  // покрываются маркер-тестом test_webapp_back_button.
  var ROUTE_TO_TAB = {
    '#/': 'status',
    '#/oversight': 'oversight',
    '#/how': 'info',
    '#/modules': 'modules',
    '#/permsoc': 'permsoc',
    '#/ai': 'llm_providers',
    '#/ai/llm': 'llm_providers',
    '#/ai/prompts': 'prompts',
    '#/ai/memory': 'memory_rag',
    '#/ai/smart-cache': 'smart_cache',
    '#/ai/names': 'people_names',
    '#/ai/relations': 'relations',
    '#/ai/lore': 'chat_lore',
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
    llm_providers: '#/ai/llm', prompts: '#/ai/prompts',
    memory_rag: '#/ai/memory', smart_cache: '#/ai/smart-cache',
    people_names: '#/ai/names', relations: '#/ai/relations',
    chat_lore: '#/ai/lore', access: '#/access',
  };
  var ROOT_ROUTES = ['#/', '#/how', '#/modules', '#/permsoc', '#/ai', '#/access'];
  // MINOR-1: удалённые роуты → канонический hash (spec §3.2). applyRoute
  // делает replaceState, чтобы адресная строка не несла legacy-путь.
  var ROUTE_ALIAS = {
    '#/ai/limits': '#/ai',
    '#/ai/sleep': '#/modules',
    '#/ai/nostalgia': '#/modules',
    '#/modules/features': '#/modules',
    '#/modules/switches': '#/modules',
    '#/modules/reactions': '#/modules',
    '#/modules/custom': '#/modules',
  };
  var ROUTE_PARENT = {
    '#/oversight': '#/',
    '#/ai/llm': '#/ai', '#/ai/prompts': '#/ai', '#/ai/memory': '#/ai',
    '#/ai/smart-cache': '#/ai', '#/ai/names': '#/ai',
    '#/ai/relations': '#/ai', '#/ai/lore': '#/ai',
    '#/access/roles': '#/access', '#/access/local': '#/access',
    '#/access/admins': '#/access',
  };

  // Маршрут валиден ТОЛЬКО если hash начинается с '#/' (иначе launch-hash).
  function normalizeRoute(hash) {
    if (typeof hash !== 'string') return null;
    if (hash.indexOf('#/') !== 0) return null;
    var r = hash.split('?')[0];           // отбросить query после маршрута
    return Object.prototype.hasOwnProperty.call(ROUTE_TO_TAB, r) ? r : null;
  }
  function routeToTab(route) {
    return ROUTE_TO_TAB[normalizeRoute(route) || '#/'] || 'status';
  }
  function tabToRoute(tabId) {
    return TAB_TO_ROUTE[tabId] || '#/';
  }
  function routeParent(route) {
    var r = normalizeRoute(route);
    if (!r || ROOT_ROUTES.indexOf(r) >= 0) return null;
    return ROUTE_PARENT[r] || '#/';
  }
  function routeDepth(route) {
    return routeParent(route) ? 1 : 0;
  }
  // D1: hub-роут доступен, если видна ХОТЯ БЫ ОДНА его карточка. НЕ гейтим
  // hub по одному «представительскому» tab (иначе роль с правами только на
  // prompts/limits получала редирект с #/ai).
  function hubVisible(route, canViewTab) {
    var hub = HUBS[route];
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
    try {
      var saved = normalizeRoute(sessionStorage.getItem('adminbot.route'));
      if (saved) return saved;
    } catch (e) { /* quota */ }
    return '#/';
  }

  // Router-состояние — НЕ в data()/реактивности: нативный BackButton-объект
  // нельзя оборачивать в reactive-proxy, а _-поля инстанса Vue не проксирует.
  var _appVm = null;
  var _backApi = null;
  var _boundBackApi = null;   // R10.5-1: к какому объекту уже привязан onClick
  var _routeApplied = false;
  var _onHashChange = null;
  var _onKeydown = null;      // MODERATE-2: глобальный Esc (закрытие модалки)
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
        // A4/T-1207: LLM-блоки по модулям + черновики/результаты теста.
        providerBlocks: PROVIDER_BLOCKS,
        blockDrafts: {},
        blockResults: {},
        blockTesting: {},
        blockSaving: {},
        expand: {},              // F-11: localStorage adminbot.expand:<tab>
        // T-1099: hash-роутер — route (@see #6.3), backNative — есть ли
        // нативный Telegram.WebApp.BackButton (иначе in-app fallback ←).
        route: '#/',
        backNative: false,
        me: null,
        authError: null,
        authLocked: false,
        // Раунд 10 (F-7 T-854, F-7 T-906): контекст чата — активный `activeChatId`
        // (persist localStorage 'adminbot.active_chat_id'), api() добавляет
        // X-Chat-Id; NULL → ровно старое поведение (глобальный конфиг).
        activeChatId: null,
        accessChats: [],              // GET /api/access/chats (селектор F-11)
        accessMy: null,               // GET /api/access/me
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
        permsocBusy: false,
        // Раунд 10 (F-12 C1/C2): Oversight-дашборд (global admin)
        oversightData: null,     // GET /api/oversight/summary
        oversightBusy: false,
        oversightSearch: '',
        oversightSort: 'chat_id',
        oversightDetail: null,   // модалка деталей чата
        oversightDetailBusy: false,
        oversightOpBusy: false,
        // UI-полировка TMA: meAvatarUrl — URL аватара текущего юзера (CDN
        // photo_url из initData либо blob через прокси avatarUrl) и флаг
        // полноэкранного режима TMA (кнопка ⛶ в шапке). Кэш blob-URL —
        // модульный _avatarCache (см. выше в файле) — реактивность не нужна.
        meAvatarUrl: '',
        isFullscreen: false,
        // config
        configItems: [],
        configGroups: [],          // 84.24: метаданные групп (с сервера)
        configSearch: '',          // 84.24: фильтр по title/description/key
        configLoading: false,
        configError: '',          // F-13 (AC-3, MED-021): баннер loadConfig
                                  // (403/503/сеть) — объясняет пустую вкладку
        configChatUpdatedAt: null, // F-7: optimistic-метка чата (X-Chat-Id)
        saving: new Set(),
        keyDrafts: {},
        keyReveal: {},           // 3.5.1: показать/скрыть маску ключа (по item.key)
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
        uptimeChart: null,
        // B1/OD8 (T-1128/T-1129): компактный список доступности ключей +
        // временной график (GET /api/status/key-history, leak-safe).
        keyHistory: null,
        keyHistoryChart: null,
        keyHistoryChartHeight: 120,   // 10.10 (п.2): реактивная высота
        logs: [],
        logsCount: 0,
        logsLoading: false,
        logLevel: 'INFO',
        // 10.7 (3c): transient-подсветка строки, скопированной по клику.
        copiedIndex: null,
        copiedTimer: null,
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
        var tab = this.currentTab;
        return tab ? tab.label : '';
      },
      // T-1099: глубина текущего маршрута (0 = корень → нативный ✕).
      routeDepth: function () {
        return routeDepth(this.route);
      },
      // T-1100: navbar-пункты, отфильтрованные по правам.
      navItems: function () {
        var self = this;
        var canView = function (id) { return self.canViewTab(id); };
        return NAV_ITEMS.filter(function (n) {
          if (n.id === 'status' || n.id === 'how') return true;
          if (n.id === 'permsoc') return self.canViewTab('permsoc');
          // A2/блокер-1: «Модули» — НЕ hub (список 11 модулей) → свой tab.
          if (n.id === 'modules') return canView('modules');
          // D1: hub-пункты (ai/access) видимы, если видна хотя бы одна карточка.
          if (n.id === 'ai' || n.id === 'access') {
            return hubVisible(n.route, canView);
          }
          return false;
        });
      },
      activeNav: function () {
        var r = this.route || '#/';
        if (r === '#/' || r === '#/oversight') return 'status';
        if (r === '#/how') return 'how';
        if (r.indexOf('#/modules') === 0) return 'modules';
        if (r.indexOf('#/ai') === 0) return 'ai';
        if (r === '#/permsoc') return 'permsoc';
        if (r.indexOf('#/access') === 0) return 'access';
        return '';
      },
      // T-1100: карточки активного hub-экрана (или null, если не hub).
      hubCards: function () {
        var hub = HUBS[this.route];
        if (!hub) return null;
        var self = this;
        var cards = hub.cards.filter(function (c) {
          return !c.tab || self.canViewTab(c.tab);
        });
        if (!cards.length) return null;
        return { title: hub.title, subtitle: hub.subtitle, cards: cards };
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
      // 3.5.1: активная вкладка — конфиг (generic-рендер по sources)
      currentTabIsConfig: function () {
        var t = this.currentTab;
        return !!(t && t.type === 'config');
      },
      // 3.5.1: группы активной конфиг-вкладки (для generic-шаблона).
      // 10.9: PERMsoc — 4 owner-блока (псевдо-группы с `owner`).
      currentTabGroups: function () {
        var t = this.currentTab;
        if (!t || t.type !== 'config') return [];
        if (t.id === 'permsoc') return this._permsocOwnerGroups();
        return this.groupedForTab(t);
      },
      currentTabItemCount: function () {
        var t = this.currentTab;
        return (t && t.type === 'config') ? this.tabItemCount(t) : 0;
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
      // 3.10: любая операция лора в процессе — блокировка кнопок-мутаций
      chatLoreBusy: function () {
        return this.chatLoreProfileLoading
          || this.chatLoreSaving || this.chatLoreGenerating;
      },
      // F4 (84.14.5): только доступные вкладки;
      // «Статус» и «Справка» — всегда (RBAC-исключения).
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

    // T-1099/§6.2 п.1-4: initData — ДО hash. created() вычисляет стартовый
    // маршрут и синхронизирует activeTab (производная от route); loader
    // активной вкладки дёргается позже в mounted после auth.
    created: function () {
      getInitData();                       // кэш initData ДО записи hash
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
        _appVm.applyRoute(normalizeRoute(window.location.hash) || '#/');
      };
      window.addEventListener('hashchange', _onHashChange);
      // MODERATE-2 + 10.8 (R10.8-1): глобальный Esc закрывает модалку модуля
      // И route-driven окна «Доступов» (фокус может быть вне модалки —
      // keydown на карточке недостаточно; закрытие окна = hash → #/access).
      _onKeydown = function (e) {
        if (e.key === 'Escape' && _appVm) {
          _appVm.escClose();
        }
      };
      window.addEventListener('keydown', _onKeydown);
      this.initBackButton();
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
          self.retryInitData();
        });
      }
    },

    methods: {
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
        options.headers = Object.assign({}, options.headers || {});
        if (!options.headers['Content-Type'] && options.body) {
          options.headers['Content-Type'] = 'application/json';
        }
        if (this.activeChatId != null) {
          options.headers['X-Chat-Id'] = String(this.activeChatId);
        }
        var initData = getInitData();   // T-1099: тот же кэш, что на BOOT
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

      // Шапка: аватар текущего юзера. CDN me.photo_url (initData) — сразу;
      // если photo_url нет — blob через прокси avatarUrl('user', …).
      // Повторный вызов (после loadMe/ре-авторизации) сбрасывает поле —
      // аватар может появиться, даже если раньше не загрузился.
      refreshMeAvatar: function () {
        var self = this;
        var me = this.me;
        this.meAvatarUrl = '';
        if (!me || me.telegram_id == null) return;
        if (me.photo_url) {
          this.meAvatarUrl = me.photo_url;   // CDN; onerror → фолбек ниже
          return;
        }
        this.loadAvatar('user', me.telegram_id).then(function (url) {
          if (url && self.me) self.meAvatarUrl = url;
        });
      },

      // @error аватара в шапке: CDN photo_url умер → фолбек на прокси
      // Bot API (blob); blob тоже не удался → meAvatarUrl='' прячет img
      // (следующий refreshMeAvatar после loadMe попробует снова).
      onMeAvatarError: function () {
        var self = this;
        var me = this.me;
        var viaCdn = !!(me && me.photo_url
          && this.meAvatarUrl === me.photo_url);
        this.meAvatarUrl = '';
        if (!me || !viaCdn) return;
        this.loadAvatar('user', me.telegram_id).then(function (url) {
          if (url && self.me) self.meAvatarUrl = url;
        });
      },

      // @error аватаров в списках: сброс поля → v-if убирает битый img;
      // при следующей загрузке списка loadAvatar поставит URL снова (если
      // фото появилось/серверный негатив-кэш 1ч протух). Не style.display:
      // тот не дал бы img показаться при ре-рендере.
      avatarError: function (obj) {
        if (obj) obj.avatarUrl = null;
      },

      toast: function (text, kind) {
        var self = this;
        var id = Date.now() + Math.random();
        this.toasts.push({ id: id, text: text, kind: kind || 'ok' });
        setTimeout(function () {
          self.toasts = self.toasts.filter(function (t) { return t.id !== id; });
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
      setActiveChat: function (chatId) {
        var id = (chatId == null || chatId === '') ? null : parseInt(chatId, 10);
        this.scopeOpen = false;
        if (id === this.activeChatId) return;
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
        // 10.10 (п.3): смена scope — сброс черновиков/результатов блоков
        // (draft==null = «не трогать»; старый результат теста неактуален).
        this.blockDrafts = {};
        this.blockResults = {};
        this.loadConfig();
        this.loadKeyStatus();
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
          olya: 'flags.olya_enabled',
          mimic: 'flags.mimic_enabled',
        };
        var itemKey = subFlags[module];
        if (!itemKey) return 'derived (master)';   // kostik / alan
        var it = this.configItems.find(function (i) { return i.key === itemKey; });
        return it && it.value ? 'под-флаг ON' : 'под-флаг OFF';
      },
      // бюджет: прогресс-бары (usage/limit в долях; guard нулей)
      budgetRatio: function (pair) {
        if (!pair || !pair.limit) return 0;
        return Math.min(1, (pair.used || 0) / pair.limit);
      },

      // ═══ Раунд 10 (F-12 C1/C2): Oversight (global admin) ═══
      loadOversight: async function () {
        this.oversightBusy = true;
        try {
          this.oversightData = await this.api('/api/oversight/summary');
          // 10.9 (п.6, ADR-109-5): «Бюджет фона» живёт в «Сводке» — единый
          // клиентский путь (прогрессбары), без дубля global_budget.
          this.loadBudgetInfo();
        } catch (e) {
          this.oversightData = null;
          if (e.status !== 401 && e.status !== 403) {
            this.toast('Не удалось загрузить сводку: ' + e.message, 'err');
          }
        } finally {
          this.oversightBusy = false;
        }
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
      resetChatOverride: async function (item) {
        // F-14 (§6.3): сброс своего override — global admin (любой чат)
        // или DM-владелец (только свой ЛС; серверный гейт тот же).
        if (!(this.isGlobalAdmin || this.isDmCtx())) {
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
        if (route === this.route && _routeApplied) {
          this.syncBackButton();
          return;
        }
        var tabId = routeToTab(route);
        var isHub = Object.prototype.hasOwnProperty.call(HUBS, route);
        if (this.me && isHub) {
          // D1: hub-роут гейтим по видимым карточкам, НЕ по representative tab.
          if (!hubVisible(route, this.canViewTab.bind(this))) {
            this.toast('Нет доступа к разделу', 'warn');
            route = '#/';
            tabId = routeToTab(route);
            try { history.replaceState(null, '', route); } catch (e) { /* file:// */ }
          }
        } else if (this.me && tabId && !this.canViewTab(tabId)) {
          this.toast('Нет доступа к разделу', 'warn');
          route = '#/';
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
        if (this.openModuleId != null) { this.closeModule(); return; }
        if (this.accessOpen != null) { this.closeAccessWindow(); }
      },
      isAccessOpen: function (id) {
        return this.accessOpen === id;
      },
      // ═══ A2/T-1166/T-1167: модули — toggle + окно параметров ═══
      openModuleWindow: function (m) {
        if (!m) return;
        if (!this.canViewTab(m.tab)) {
          this.toast('Нет доступа к модулю', 'warn');
          return;
        }
        this.openModuleId = m.id;
        this._ensureModuleData(m);
        if (!this.configItems.length) this.loadConfig();
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
      },
      canEditModule: function (m) {
        return !!m && this.canEditConfig(m.toggleKey);
      },
      moduleEnabled: function (m) {
        if (!m) return false;
        var it = this.configItems.find(function (i) {
          return i.key === m.toggleKey;
        });
        return !!(it && it.value);
      },
      toggleModule: async function (m, checked) {
        if (!m || !this.canEditConfig(m.toggleKey)) return;
        var it = this.configItems.find(function (i) {
          return i.key === m.toggleKey;
        });
        if (!it) {
          this.toast('Параметр недоступен: ' + m.toggleKey, 'warn');
          return;
        }
        it.value = !!checked;
        await this.saveConfigItem(it);
      },
      // A4/T-1207: значение блока — черновик, иначе сохранённая строка.
      // 10.10 (п.3): `draft === ''` (явная очистка) ВОЗВРАЩАЕТ '' (не
      // откатывается к configItems); отсутствие черновика — реальное
      // значение из configItems (fallback), секреты → '' (маска).
      blockFieldValue: function (f) {
        var draft = this.blockDrafts[f.key];
        if (draft != null) return draft;
        var it = this.configItems.find(function (i) { return i.key === f.key; });
        if (it && typeof it.value === 'string') return it.value;
        if (it && it.type !== 'bool' && typeof it.value !== 'object') return it.value;
        return '';
      },
      blockFieldPlaceholder: function (f) {
        var it = this.configItems.find(function (i) { return i.key === f.key; });
        if (it && typeof it.value === 'object' && it.value) {
          return it.value.configured ? ('configured ••••' + (it.value.last4 || '')) : 'не настроен';
        }
        return f.label;
      },
      testBlock: async function (b) {
        if (!b || this.blockTesting[b.id]) return;
        this.blockTesting[b.id] = true;
        var self = this;
        var body = { block: b.id, base_url: '', model: '', api_key: '' };
        b.fields.forEach(function (f) {
          var v = self.blockFieldValue(f);
          if (f.role === 'base_url') body.base_url = v || body.base_url;
          else if (f.role === 'model') body.model = v || body.model;
          else if (f.role === 'api_key' && v) body.api_key = v;
        });
        try {
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
          var msg = (e && e.status === 429) ? 'Слишком часто — подождите 5 секунд'
            : ((e && e.message) || 'ошибка');
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
              api_key: this.blockFieldValue(f),
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
      saveBlock: async function (b) {
        if (!b || this.blockSaving[b.id]) return;
        var self = this;
        var items = [];
        b.fields.forEach(function (f) {
          var it = self.configItems.find(function (i) { return i.key === f.key; });
          var draft = self.blockDrafts[f.key];
          if (f.secret) {
            if (draft) items.push({ key: f.key, value: draft });
            return;
          }
          // MINOR-3: `draft == null` = «не трогать»; `''` (пусто) = очистить.
          if (draft == null) return;
          if (draft === '') { items.push({ key: f.key, value: '' }); return; }
          var v = draft;
          if (it && it.type === 'int') v = parseInt(v, 10);
          else if (it && it.type === 'float') v = parseFloat(v, 10);
          else if (it && it.type === 'bool') v = !!v;
          if (typeof v === 'number' && !isFinite(v)) {
            self.toast('Некорректное значение: ' + f.key, 'err');
            return;
          }
          items.push({ key: f.key, value: v });
        });
        if (!items.length) { this.toast('Нет изменений', 'warn'); return; }
        this.blockSaving[b.id] = true;
        try {
          await this.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({ items: items,
                                   updated_at: this.configChatUpdatedAt }),
          });
          this.toast('Сохранено: ' + b.title, 'ok');
          await this._preserveScroll(this.loadConfig);
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.toast('Конфликт версии (409) — конфигурация обновлена', 'warn');
            this._preserveScroll(this.loadConfig);
          } else {
            this.toast('Ошибка сохранения: ' + e.message, 'err');
          }
        } finally {
          this.blockSaving[b.id] = false;
        }
      },
      // T-1100: карточка hub → дочерний экран (+якорь секции для access).
      openHubCard: function (card) {
        var self = this;
        if (!card) return;
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
        } else {
          this.scopeFocus = -1;
        }
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
        // 3.5.1 (UX): скролл контента в начало при переключении вкладки
        this.$nextTick(function () {
          var sc = document.scrollingElement || document.documentElement;
          if (sc) sc.scrollTop = 0;
        });
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
      toggleFullscreen: function () {
        // Полноэкранный режим TMA (⛶): request/exitFullscreen обёрнуты в
        // try/catch (SDK без поддержки/вне TG — бездействие). Флаг —
        // локальный оптимистичный тоггл (события fullscreenChanged не ждём).
        try {
          var wa = window.Telegram && Telegram.WebApp;
          if (!wa) return;
          if (this.isFullscreen) {
            if (wa.exitFullscreen) wa.exitFullscreen();
          } else {
            if (wa.requestFullscreen) wa.requestFullscreen();
          }
          this.isFullscreen = !this.isFullscreen;
        } catch (e) { /* вне TG/старый SDK — молча */ }
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

      // F-11 (4.2): аккордеон «Расширенные» — localStorage adminbot.expand:<tab>
      expandOpen: function (tabId) {
        try {
          return localStorage.getItem('adminbot.expand:' + tabId) === '1';
        } catch (e) { return false; }
      },
      toggleExpand: function (tabId) {
        try {
          var cur = localStorage.getItem('adminbot.expand:' + tabId) === '1';
          localStorage.setItem('adminbot.expand:' + tabId, cur ? '' : '1');
        } catch (e) {}
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

      canEditConfig: function (key) {
        var p = this.permissions;
        if (p.wildcard) return true;
        var cat = String(key).split('.')[0];
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

      loadConfig: async function () {
        var epoch = this.scopeEpoch;   // D2: снимок scope
        this.configLoading = true;
        try {
          var data = await this.api('/api/config');
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.configError = '';      // F-13 (AC-3): успех — баннер скрыт
          this.configItems = data.items || [];
          this.configGroups = data.groups || [];
          this.configChatUpdatedAt = data.updated_at != null
            ? data.updated_at : null;   // optimistic-метка чата (409-протокол)
          // 10.10 (п.3): успешная загрузка = свежие значения из configItems;
          // старые черновики сбрасываем (draft==null = «не трогать»), иначе
          // черновик «переживал» бы reload и показывал стейл.
          this.blockDrafts = {};
          this.configItems.forEach(function (item) {
            // 3.5.1/FR-28: widget отсутствует у старого сервера — дефолт '';
            // json с widget='keyvalue' НЕ строкифайм (остаётся объектом для
            // KV-редактора), остальные json — textarea-текст как раньше.
            if (!item.widget) item.widget = '';
            if (item.type === 'json' && !item.widget &&
                typeof item.value === 'object' && item.value !== null) {
              item.value = JSON.stringify(item.value, null, 2);
            }
          });
          // 3.5.2: после перезагрузки KV-редакторы (компоненты) сами
          // пересоберут пары из item.value — внешних черновиков нет.
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
      // Группы-«витрины» активной конфиг-вкладки: [{id, meta, category,
      // items[]}]. Порядок — по flatGroupRank (порядок правил; для
      // секционированных вкладок — секции), внутри — group.order;
      // параметры без group → «Прочее» в конце. Поиск-фильтр как раньше.
      // R10.6-1: ключи, уже редактируемые в provider-блоках (один дом).
      providerCoveredKeys: function () {
        var keys = {};
        (this.providerBlocks || []).forEach(function (b) {
          (b.fields || []).forEach(function (f) { keys[f.key] = true; });
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

      // Раунд 10.9 (spec §1.2): owner-блоки PERMsoc. Превращаем обычные
      // группы (groupedForTab) в 4 «псевдо-группы» с `owner`; элементы
      // распределяются по владельцу, ключи-тумблеры исключаются из тела.
      _permsocOwnerGroups: function () {
        var self = this;
        var grouped = this.groupedForTab(this.currentTab);
        var claimed = {};
        PERMSOC_OWNER_BLOCKS.forEach(function (o) {
          if (o.id === 'common') return;
          (o.keys || []).forEach(function (k) { claimed[k] = true; });
        });
        function ownerOf(it) {
          for (var i = 0; i < PERMSOC_OWNER_BLOCKS.length; i++) {
            var o = PERMSOC_OWNER_BLOCKS[i];
            if (o.id === 'common') continue;
            if ((o.keys || []).indexOf(it.key) >= 0) return o.id;
            if ((o.groups || []).indexOf(it.group) >= 0 && !claimed[it.key]) {
              return o.id;
            }
          }
          return 'common';
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
            byId[ownerOf(it)].items.push(it);
          });
        });
        // LOW-6: ВСЕ 4 owner-блока рендерятся всегда (тумблер — в <summary>),
        // даже если тело пустое/скрыто правами. Не фильтруем по items.length.
        return result;
      },
      _ownerDescription: function (o) {
        return {
          slavik: 'Фото, гифки, посты из старого канала и передразнивания Славика.',
          olya: 'Реакции бота на видео Оли и подписи к ним.',
          mimic: 'Кого бот передразнивает и как часто.',
          common:
            'Мастер-выключатель и всё, что не привязано к одной персоне.',
        }[o.id] || '';
      },
      // Текущее состояние owner-тумблера: мастер-блок в чате читается из
      // gates.permsoc, остальные — из config-значения (bool).
      permsocOwnerOn: function (owner) {
        if (!owner) return false;
        if (owner.id === 'common' && this.isChatContext()) {
          return this.permsocMasterOn();
        }
        var it = this.configItems.find(function (i) {
          return i.key === owner.toggleKey;
        });
        return !!(it && it.value);
      },
      canToggleOwner: function (owner) {
        if (!owner) return false;
        if (owner.id === 'common' && this.isChatContext()) {
          return !!this.isGlobalAdmin;
        }
        return this.canEditConfig(owner.toggleKey);
      },
      // Единственный путь записи owner-тумблера: чат-мастер → gates, иначе
      // config — НЕ оба одновременно (spec §1.6).
      toggleOwner: async function (owner, checked) {
        if (!owner) return;
        if (owner.id === 'common' && this.isChatContext()) {
          await this.togglePermsoc(!!checked);
          return;
        }
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
      // 3.5.1: маска секрета с кнопкой показать (per-key, keyReveal)
      toggleKeyReveal: function (key) {
        this.keyReveal[key] = !this.keyReveal[key];
      },

      inputType: function (item) {
        if (item.type === 'int' || item.type === 'float') return 'number';
        return 'text';
      },

      saveConfigItem: async function (item) {
        var value = item.value;
        if (item.type === 'json') {
          // 3.5.1: json без widget редактируется текстом JSON → парсим.
          if (typeof value === 'string') {
            try {
              value = JSON.parse(value);
            } catch (e) {
              this.toast('Невалидный JSON в ' + item.key, 'err');
              return;
            }
          }
        } else if (item.type === 'int') {
          // Раунд 4 (T-718): числовые проверки — ТОЛЬКО для int/float
          // (раньше isNaN('текст') === true ломал str-поля).
          value = parseInt(value, 10);
          if (!isFinite(value)) {
            this.toast('Некорректное значение для ' + item.key, 'err');
            return;
          }
        } else if (item.type === 'float') {
          value = parseFloat(value);
          if (!isFinite(value)) {
            this.toast('Некорректное значение для ' + item.key, 'err');
            return;
          }
        } else if (item.type === 'bool') {
          value = !!value;               // чекбокс — как раньше (защитная ветка)
        } else if (value === null || value === undefined) {
          this.toast('Некорректное значение для ' + item.key, 'err');
          return;
        }
        // Раунд 4 (T-719): str-поле категории prompts/content не может быть
        // пустым (сервер дублирует 422 — единая точка валидации, FR-E2).
        if (item.type === 'str' && typeof value === 'string'
            && (item.category === 'prompts' || item.category === 'content')
            && !value.trim()) {
          this.toast('Промпт не может быть пустым: ' + item.title, 'err');
          return;
        }
        this.saving.add(item.key);
        try {
          await this.api('/api/config', {
            method: 'POST',
            body: JSON.stringify({ items: [{ key: item.key, value: value }],
                                   updated_at: this.configChatUpdatedAt }),
          });
          this.toast('Сохранено: ' + item.title, 'ok');
          await this._preserveScroll(this.loadConfig);
        } catch (e) {
          if (e.status === 409 && e.message && e.message.code === 'conflict') {
            this.toast('Конфликт версии (409) — конфигурация обновлена', 'warn');
            this._preserveScroll(this.loadConfig);
          } else {
            this.toast('Ошибка сохранения: ' + e.message, 'err');
          }
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
          await this._preserveScroll(this.loadConfig);
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
      // [{id, title, groups:[{id, title, order, items:[{key,item}]}]}] —
      // секция = мини-апп-вкладка (tab) или fallback-категория.
      matrixSections: function () {
        var items = this.matrixItems || {};
        var q = (this.matrixSearch || '').toLowerCase();
        var bySec = {};
        Object.keys(items).forEach(function (key) {
          var it = items[key];
          if (q && key.toLowerCase().indexOf(q) < 0
              && (it.title || '').toLowerCase().indexOf(q) < 0) return;
          var secId = it.tab || ('cat:' + (it.category || 'other'));
          if (!bySec[secId]) {
            bySec[secId] = {
              id: secId, title: it.tab_title || null,
              category: it.category || 'other', groups: {},
            };
          }
          var gid = it.group || 'other';
          if (!bySec[secId].groups[gid]) {
            bySec[secId].groups[gid] = {
              id: gid, title: it.group_title || gid,
              order: it.group_order || 999, items: [],
            };
          }
          bySec[secId].groups[gid].items.push({ key: key, item: it });
        });
        var self = this;
        return Object.keys(bySec).map(function (sid) {
          var sec = bySec[sid];
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
      loadStatus: async function () {
        var epoch = this.scopeEpoch;   // D2: снимок scope (permsoc-телеметрия per chat)
        try {
          var st = await this.api('/api/status');
          if (!this._scopeGuard(epoch)) return;   // scope сменился — ответ старый
          this.statusData = st;
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
              borderColor: '#14CBB6',            // токен --teal-500 (OD4)
              backgroundColor: 'rgba(20,203,182,0.15)',
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
        var palette = ['#14CBB6', '#8D6BDC', '#16B364', '#EAAA08',
                       '#FF4848', '#A78DE4'];
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
          var data = grid.map(function (ts) {
            if (!Object.prototype.hasOwnProperty.call(byBucket, ts)) return null;
            return byBucket[ts] ? lane + 0.75 : lane + 0.25;
          });
          return {
            label: p.module_title || p.provider || p.module_id,
            data: data,
            borderColor: palette[idx % palette.length],
            backgroundColor: palette[idx % palette.length],
            stepped: true,
            tension: 0,
            pointRadius: samples.length <= 1 ? 3 : 0,
            spanGaps: false,     // разрыв = нет данных
          };
        });
        return {
          labels: labels,
          datasets: datasets,
          laneCount: list.length,
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
              scales: {
                y: { min: -0.2, max: model.laneCount + 0.2,
                     ticks: { display: false } },
                x: { ticks: { color: '#9CA3AF', maxTicksLimit: 10,
                              font: { size: 10 } } },
              },
              plugins: {
                legend: { display: true, position: 'bottom',
                          labels: { color: '#BABABA', boxWidth: 10,
                                    font: { size: 10 } } },
              },
            },
          };
          if (self.keyHistoryChart) { self.keyHistoryChart.destroy(); }
          self.keyHistoryChart = new Chart(el, cfg);
        });
      },

      loadLogs: async function () {
        this.logsLoading = true;
        try {
          var data = await this.api(
            '/api/status/logs?level=' + encodeURIComponent(this.logLevel) + '&limit=200');
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
      onRelationsToggle: function (ev) {
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
      'item.value': function () { this.sync(); },
    },
    computed: {
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
      // Инициализация/пересборка пар из объекта-значения item.value
      sync: function () {
        var raw = this.item && this.item.value;
        var src = {};
        if (raw && typeof raw === 'object' && !Array.isArray(raw)) src = raw;
        var pairs = Object.keys(src).map(function (k) {
          return { id: String(k), name: String(src[k] == null ? '' : src[k]) };
        });
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

  app.mount('#app');

  function ApiError(status, message) {
    this.status = status;
    this.message = message;
    this.name = 'ApiError';
  }
})();
