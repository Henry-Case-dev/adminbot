# Задачи: frontend-relations-participants (ТЗ 7 раунда 10.4)

Раунд 10.4, фича F (T-1033…T-1044). Стадия старта — PLANNED; spec.md @Architect.
ТЗ владельца (п.7, оба под-пункта):
1. Вынести «Участники и отношения» ИЗ «Лор чатов» — в отдельный раздел;
2. Настройки отношений (flags_relations + limits_relations — сейчас на
   «Лимитах» / вкладке limits) — сложить в этот же раздел.

Отправная точка (рекон tma-structure-10.4, HEAD 1410a68):
- «Участники и отношения» — блок внутри chat_lore-шаблона:
  index.html:1450-1556 (тумблер relations_enabled, карточки участников,
  resolveRelationName/avatarInitial, stage_auto/manual, note, скор, last_seen);
  данные — GET /api/chat_lore/{id}/relations (web/api/chat_lore.py:534-618),
  правки — PUT/DELETE relations + PUT relations_enabled (:660-766).
- Настройки отношений: flags_relations (RELATIONS_TONE_ENABLED) +
  limits_relations (12 ключей: стадии/полки/decay/пересчёт/капы) — сейчас на
  «Лимитах»: TAB_LIMITS except НЕ включает их (limits: persons/memory/graph/
  .../relations входит; flags: flags_relations входит).
- Каскад имён/алиасы: фича B (per-chat алиасы) — исполнить B ДО F (в каскаде
  участников на этой вкладке будет использоваться per-chat резолв алиасов).
- Эталон REGISTRY 383/71/359 — без изменений (переносы групп, не ключей).

ЦЕЛЕВОЕ СОСТОЯНИЕ (дефолт; уточнения @Architect):
- Новая вкладка `relations` («Участники и отношения», menu 'chat_profile'),
  type — свой (по образцу chat_lore: свой шаблон + data-API), видимость —
  canViewTab (секция chat_lore / probe-список — как у chat_lore; либо новый
  гейт — решение @Architect, но БЕЗ новых RBAC-секций: known_sections не
  расширяем (R5 конвенция — секции chat_lore покрывают)).
- Контент: (1) тумблер relations_enabled + карточки участников (перенос
  БЕЗ изменения функциональности: stage/note/409/стадии); (2) секция
  «Настройки отношений» — config-часть (generic-рендер групп flags_relations +
  limits_relations + преалементные поля) с per-chat override; (3) перекрёстная
  ссылка/карточка «Имена людей» (алиасы — фича B) — опционально.
- «Лор чатов»: остаётся лор-профиль/авто-лор/история/remap/чат-админы +
  «Расширенные» (limits_lore/flags_lore — фича A); блок участников УБИРАЕТСЯ.
- TAB_RULES: TAB_LIMITS except += {limits_relations} (flags: {"flags_relations"});
  новая запись (TAB_RELATIONS, ((LIMITS, {limits_relations}), (FLAGS,
  {flags_relations}))) — как в фиче A для лора (config-часть не-config вкладки).

## A. Каталог [@Architect/@Builder]

- [ ] T-1033 — TAB_RULES: (TAB_RELATIONS, ((LIMITS, {limits_relations}),
  (FLAGS, {flags_relations}))); TAB_LIMITS except: limits += {limits_relations},
  flags += {flags_relations}; CONFIG_TAB_TITLES[TAB_RELATIONS]=«Участники и
  отношения». **AC-R1:** `_TAB_BY_GROUP` без ValueError; `group_tab(...relations)`
  == 'relations'; с «Лимитов» группы ушли (маркер).
- [ ] T-1034 — эТАЛОН: REGISTRY 383 / 71 / Settings 359 — БЕЗ изменений;
  новых групп/ключей нет; **AC-R2:** test_param_catalog (383/71/359) — зелёный.

## B. Фронт: отдельная вкладка [@Builder]

- [ ] T-1035 — новая вкладка TABS (id 'relations', icon «👥», label «Участники и
  отношения», menu 'chat_profile', type 'relations'): шаблон в index.html +
  canViewTab (секция chat_lore / probe-список), data-загрузка (аналог
  loadRelations — перенос существующих методов loadChatRelations и их вызовов
  (app.js:2378-2510) на активный чат вкладки). **AC-R3:** вкладка видна
  (правила как у chat_lore: секция chat_lore либо непустой probe); список
  загружается; методы не дублируются/не удаляются старые chat_lore-локальные
  без регресса.
- [ ] T-1036 — перенос разметки участников из chat_lore: карточки (avatar,
  resolveRelationName/avatarInitial, stage_auto/manual, note, скор/msg30,
  last_seen), тумблер relations_enabled, модалки stage/note, 409-релиз.
  **AC-R4:** функциональность участников перенесена БЕЗ изменения (стадии,
  опт‑409, note, валидации этапов ручной стадии); из chat_lore-шаблона блок
  участников удалён; маркеры-тесты (avatars/dm/rbac UI) обновлены.
- [ ] T-1037 — секция «Настройки отношений» в шаблоне relations: generic-блок
  (как фича A для лора): группа flags_relations + limits_relations (поля
  стадий/decay/полки/капы) + per-chat override-кнопки/canEditConfig.
  **AC-R5:** поля настроек видны и сохраняются (POST /api/config; 409 —
  как в generic); для per-chat — override; DM-скоуп — валидация (отношения в
  ЛС: блок скрыт/read-only по правилу из B — DM юзер не админ своих ЛС для
  участников; решение @Architect: если участников в ЛС нет — скрыть блок).
- [ ] T-1038 — ссылки/переходы: из «Модули и Фичи» / «Лор чатов» —
  актуализировать упоминания; «Лор чатов»-карточка с указателем на новый
  раздел (опционально, маркер). **AC-R6:** SET-TAB переходы на relations —
  актуальные; старые упоминания блока участников в лоре удалены.

## C. Маркеры и регресс [@Builder]

- [ ] T-1039 — test_frontend_tab_mapping.py: кроме стандартного —
  composition relations (limits/flags наборы); ALL_TABS + импорты; состав
  TAB_LIMITS (исключения relations) — актуализированы.
- [ ] T-1040 — test_webapp_nav_disclosure_ui.py / test_webapp_avatars_ui.py /
  test_webapp_dm_ui.py / test_webapp_rbac_ui.py: маркеры вкладки relations,
  отсутствие участников в chat_lore-маркерах (move), сохранение маркеров
  аватаров/стадий; обновление маркеров-строк см. MED-022.
- [ ] T-1041 — тест серверный: GET/PUT/DELETE /api/chat_lore/{id}/relations
  остаются как есть; баг-риск: убрать relations_enabled из PUT /settings —
  НЕ делаем (остаётся; только UI). 404/403/409 — без изменений.
- [ ] T-1042 — регресс: полный pytest 0 failed; node --check; git diff --check.
- [ ] T-1043 — live-маркер: открывается «Участники и отношения»: список
  участников (имена/стадии/аватары), тумблер; настройки отношений
  сохраняются; «Лор чатов» — без блока участников, лор/история/remap на месте.

**Критерии приёмки ТЗ 7 (сводные):**
- «Участники и отношения» — ОТДЕЛЬНЫЙ раздел (вкладка в Чат-Профиле);
- настройки отношений (flags+limits) — в этом же разделе (не на «Лимитах»);
- функциональность участников/стадий/норм/409 R16 — БЕЗ регресса;
- «Лор чатов» — только лор (+расширенные из фичи A); known_sections без
  изменений; REGISTRY 383/71/359 — без изменений.
