# Задачи: frontend-reorg-modules-reactions (ТЗ 1+2 раунда 10.4)

Раунд 10.4, фича A (T-974…T-989). Стадия старта — PLANNED; spec.md @Architect.
ТЗ владельца (п.1 и п.2): (1) «Реакции и Триггеры» → разгрузить: интервалы/
кулдауны/Мимикрия/Dead page переезжают в «Функции PERMsoc»; (2) «Модули и Фичи»
→ «Модули»: имена/описания модулей, убрать дублирующую сводку «Функции PERMsoc»
(вкладка остаётся), «Модули (вкл/выкл)» → в раздел «Модули», настройки лора
(limits_lore + flags_lore) → в «Лор чатов» под «Расширенные» (кат. расширенных).

Отправная точка (рекон `recon: tma-structure-10.4`, HEAD 1410a68):
- TAB_RULES `services/param_catalog.py:1374-1406`; жёсткое правило «группа → ровно
  1 вкладка» `_TAB_BY_GROUP` :1424-1431 (ValueError на дубликате!).
- Зеркало TABS `web/app.js:18-72` (sources-исключения/белые списки обязаны
  повторять TAB_RULES — B-1-лайк-риск); MENU_LABELS :76-83 (modules='Модули и Фичи').
- `modules_feats` — НЕ config-вкладка: index.html:889+ (карточки «Тяжёлые фичи»/
  «Функции PERMsoc»/«Бюджет фона»); PERMsoc-сводка с кнопкой `setTab('permsoc')`
  (маркер «Открыть «Функции PERMsoc» 🎭»).
- Группы: reactions{persons,permsoc,admin,deadpage,slavik,alan,war,common,
  goodmorning,mimic,olya,summary,chat,memory,word_reactions} (15), flags_media (7),
  limits{persons,mimic,deadpage,media} — кандидаты переноса.
- limits_lore (8 ключей) + flags_lore (3) — сейчас на «Лимитах» (TAB_LIMITS).
- Эталон каталога: REGISTRY 383 / 71 группа / Settings 359 (**НОВЫХ ключей нет** —
  только переносы; эталон test_param_catalog не меняется).

ЦЕЛЕВОЕ СОСТОЯНИЕ (дефолт, для уточнения @Architect в spec.md):
1. TAB_PERMSOC sources → reactions {persons, permsoc, deadpage, mimic, slavik,
   alan, olya} + flags {permsoc, media} + limits {persons, mimic, deadpage, media}.
2. TAB_REACTIONS_TRIGGERS sources → reactions {admin, war, common, goodmorning,
   summary, chat, memory, word_reactions} (без flags-источника).
3. TAB_LIMITS: из except добавить {limits_mimic, limits_deadpage, limits_media,
   limits_lore, limits_relations? → нет: limits_relations → фича F (f); здесь —
   limits_lore; flags: modules, service, lore} → т.е. except-списки расширяются.
4. MENU_LABELS.modules + label modules_feats → «Модули»; карточка-сводка
   «Функции PERMsoc» удаляется из modules_feats (вкладка permsoc и её master
   остаются в меню «Модули»); карточки модулей получают имя + описание.
5. Новая config-вкладка «Модули (вкл/выкл)» (id `modules_switches`, menu
   'modules'): flags {modules, service}.
6. limits_lore + flags_lore: config-часть вкладки chat_lore (запись TAB_RULES
   для TAB_CHAT_LORE + generic-блок «Расширенные настройки» в шаблоне chat_lore;
   группа не может остаться на «Лимитах» — иначе двойной рендер/ValueError).

## A. Каталог: TAB_RULES / группы (param_catalog.py) [@Architect/@Builder]

- [ ] T-974 — TAB_RULES: перераспределение реакций/лимитов/флагов по целевому
  состоянию (см. выше); ВСЕ except-списки и белые списки зеркально обновить
  (следить: группа не может быть «в двух вкладках» — _TAB_BY_GROUP).
  **AC-A1:** `python -c "from services import param_catalog as p"""
  — импорт без ValueError; `group_tab()` для каждого из реакций/лимит-групп
  возвращает ровно ожидаемую вкладку (см. перечисление в шапке).
- [ ] T-975 — TAB_REACTIONS_TRIGGERS: новый except-список category reactions
  (убрать {deadpage, mimic, slavik, alan, olya} из оставшихся {admin, war,
  common, goodmorning, summary, chat, memory, word_reactions}); из TAB_RULES
  удалить категорию flags в источнике реакции (flags_media переезжает в
  permsoc). **AC-A2:** `tab_group_ids(TAB_REACTIONS_TRIGGERS)` == {admin, war,
  common, goodmorning, summary, chat, memory, word_reactions}; flags_media
  НЕ входит.
- [ ] T-976 — TAB_PERMSOC: sources = реакции {persons, permsoc, deadpage, mimic,
  slavik, alan, olya} + flags {permsoc, media} + limits {persons, mimic,
  deadpage, media}. **AC-A3:** `tab_group_ids(TAB_PERMSOC)` == указанный набор;
  CONFIG_TAB_TITLES не меняется («Функции PERMsoc»).
- [ ] T-977 — TAB_LIMITS: except по категории limits += {limits_mimic,
  limits_deadpage, limits_media, limits_lore} (persons/memory/graph уже там);
  except по категории flags += {flags_modules, flags_service, flags_lore}
  (memory/media/permsoc/relations уже/позже). **AC-A4:** на «Лимитах» не
  остаётся ни одного из переносимых; `limits.cooldowns`/`limits.summary`/
  `limits.chat*`/`limits.temperature`/`limits.smart_cache`/`limits.service`/
  `limits.youtube_proxy`/`limits.worker` остаются.
- [ ] T-978 — НОВАЯ config-вкладка TAB_MODULES_SWITCHES = "modules_switches"
  (CONFIG_TAB_TITLES: «Модули (вкл/выкл)»), sources: flags {modules, service};
  TAB_RULES-запись + зеркало TABS (menu 'modules'). **AC-A5:** id/заголовок
  присутствуют в каталоге и app.js; `tab_group_ids` == {flags_modules,
  flags_service}.
- [ ] T-979 — limits_lore + flags_lore → config-часть «Лор чатов»: запись
  (TAB_CHAT_LORE, ((LIMITS, {limits_lore}), (FLAGS, {flags_lore}))) в TAB_RULES;
  группы исключаются из TAB_LIMITS (T-977). **AC-A6:** `group_tab("limits_lore")`
  == "chat_lore" и `group_tab("flags_lore")` == "chat_lore"; импорт каталога без
  ошибок; CONFIG_TAB_TITLES[TAB_CHAT_LORE] остаётся «Лор чатов».
- [ ] T-980 — регресс-эталон каталога: **AC-A7:** REGISTRY 383 записей /
  71 группа / Settings 359 — БЕЗ изменений (MED-017, эталон
  test_param_catalog.py); новый параметр в каталог НЕ добавляется (переносы
  группами, pg-ключи не тронуты).

## B. Фронт: TABS / MENU / modules_feats [@Builder]

- [ ] T-981 — TABS-зеркало (app.js:18-72): обновить sources/except всех
  изменённых вкладок (T-975…T-979) + вкладка modules_switches; MENU_LABELS.modules
  → «Модули»; label modules_feats → «Модули». **AC-B1:** синхронность зеркала с
  TAB_RULES — тест-маркеры (exact-строки except/groups) обновлены; `node --check
  web/app.js` clean.
- [ ] T-982 — modules_feats: карточки модулей с ИМЕНАМИ и ОПИСАНИЯМИ (Славик,
  Костя/Костик, Леха/Алан (+приветствие), Оля, Передразнивания, Dead page,
  War-алерты, Common, Сон, Ностальгия, Авто-лор, Саммари, Утренняя рассылка…);
  у каждой: имя, 1–2 строки описания, статус (вкл/выкл через существующие
  мастер-переключатели/бейджи), при наличии — переход к настройкам (setTab).
  **AC-B2:** каждая карточка содержит `name` и `description` (текст из
  index.html; маркеры-тесты); мастер-тумблеры без регресса.
- [ ] T-983 — удалить из modules_feats сводную карточку «Функции PERMsoc» +
  кнопку «Открыть „Функции PERMsoc“ 🎭» (вкладка permsoc доступна из меню;
  мастер/под-флаги на самой вкладке остаются). **AC-B3:** маркер setTab('permsoc')
  из modules_feats-блока отсутствует; отрицательный grep-тест
  test_webapp_nav_disclosure_ui (test_permsoc_tab_and_summary_card) обновлён
  под новое состояние (вкладка/мастер остаются, сводки нет).
- [ ] T-984 — вкладка modules_feats: контент «Модули (вкл/выкл)» — группа
  рендерится через generic-config (вкладка modules_switches) — карточка-ссылка
  или редирект-подсказка в «Модулях» при необходимости.
  **AC-B4:** ключи flags.* (модули/сервис) видимы на вкладке modules_switches и
  НЕ дублируются на «Лимитах» (их тексты отсутствуют в HTML вкладки limits —
  маркер).

## C. Вкладка «Лор чатов»: расширенные настройки [@Builder]

- [ ] T-985 — в шаблоне chat_lore (index.html:1248+) добавить generic-блок
  «⚙️ Расширенные настройки» (<details class="advanced">, рендер групп
  limits_lore + flags_lore через текущий groupedForTab-механизм; per-chat
  override-кнопки/восстановление — как в generic-рендере).
  **AC-C1:** поля LORE_* (MIN_MESSAGES/MAX_WORDS/INJECT_MAX_CHARS/TICK_MINUTES/
  GENERATE_COOLDOWN/…) и флаги лора доступны на вкладке «Лор чатов» (маркер);
  сохранение идёт через существующий POST /api/config (конфликты 409 — как в
  generic-рендере); значения per-chat (весь чат) — через override-систему.
- [ ] T-986 — canViewTab/роль для config-части chat_lore: параметрам лора
  доступ через `param.`/`flags.`-права (как на других config-вкладках);
  вкладка остаётся видимой по текущему правилу (секция chat_lore / probe) —
  гейт на конфиг-блок — существующий canEditConfig. **AC-C2:** user-роль с
  секцией chat_lore видит лор-профиль, но конфиг-блок read-only/скрыт по
  правам; global/local admin — редактирование работает.

## D. Маркер-тесты и регресс [@Builder]

- [ ] T-987 — test_frontend_tab_mapping.py: обновить composition-тесты
  (reactions_triggers, permsoc, limits-исключения, лимits/strict)
  + реестр ALL_TABS/импорты (+ TAB_MODULES_SWITCHES, TAB_CHAT_LORE-запись);
  тесты «каждая группа ровно на одной вкладке/N-группах» — на месте и зелёные.
  **AC-D1:** тест-файл проходит; продублированы маркеры зеркала app.js.
- [ ] T-988 — test_webapp_nav_disclosure_ui.py: тест-permsoc-сводки обновлён
  (T-983), modules_render_blocks — под новые карточки, menu/labels — под
  «Модули»; негативы — отсутствие старых строк. **AC-D2:** файл проходит;
  маркер «Открыть «Функции PERMsoc» 🎭» удалён/заменён; «Модули и Фичи» → «Модули».
- [ ] T-989 — полный регресс и статический контроль: **AC-D3:** `python -m pytest`
  полный прогон (baseline 4831 + новые) — 0 failed; `node --check web/app.js`
  clean; `git diff --check` чист; live-маркер: миниапп открывается, вкладки
  «Модули»/«Модули (вкл/выкл)»/«Лор чатов» рендерятся без TypeError.

**Критерии приёмки ТЗ (сводные):**
- ТЗ 1: в «Функциях PERMsoc» есть интервалы/кулдауны/Мимикрия/Dead page
  (группы permsoc-набора A-состояния); на «Реакциях и Триггерах» их нет.
- ТЗ 2: меню и вкладка называются «Модули»; карточки модулей с именами и
  описаниями; сводка PERMsoc удалена из «Модулей»; «Модули (вкл/выкл)» в
  разделе «Модули»; настройки лора — в «Лор чатов» под «Расширенными».
- Ноль изменений REGISTRY/групп/Settings (383/71/359); SQLite v8; порядок
  роутеров bot.py — без дифов; каноны промптов — без дифов; R16/имена as-is.
