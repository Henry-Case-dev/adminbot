# spec.md — frontend-reorg-modules-reactions (ТЗ 1+2+3-лор раунда 10.4, фича A)

Задачи: T-974…T-989 (tasks.md). Стадия старта — PLANNED → ARCHITECTED (наст. файл).
База: HEAD `1410a68`. Порядок: после D/C/E, до B/F/H/G.

## 1. Контекст и проблема

(1) «Реакции и Триггеры» — свалочная вкладка: 15 групп reactions + flags_media; интервалы/кулдауны/мимикрия/dead page — про функциональные модули PERMsoc, а не про «триггеры». (2) «Модули и Фичи» — двусмысленно: меню-секция и вкладка с одинаковым названием; вкладка дублирует сводку PERMsoc; «Модули (вкл/выкл)» (flags_modules+flags_service) — на «Лимитах». (3) Настройки лора (limits_lore+flags_lore) — на «Лимитах», хотя относятся к «Лору чатов».

## 2. КЛЮЧЕВАЯ ДЕВИАНСИЯ D-A1 (расхождение с tasks.md — принимать как канон)

ТЗ владельца (п.1, оба абзаца): в «Функции PERMsoc» переезжают **Dead page, Славик, Леха, War-алерты, Common-медиа, Утренняя рассылка, Мимикрия, Оля, Словесные реакции** — «…reactions_* (persons, permsoc, deadpage, mimic, slavik, alan, olya, **war, goodmorning, common + word**)…». tasks.md T-975 оставляет в TAB_REACTIONS_TRIGGERS группы {admin, war, common, goodmorning, summary, chat, memory, word_reactions} — **противоречит ТЗ**.

**Решение (канон спеки):** следовать ТЗ владельца. `TAB_REACTIONS_TRIGGERS` = {reactions_admin, reactions_summary, reactions_chat, reactions_memory} (без флагов); `TAB_PERMSOC` = 11 групп reactions {persons, permsoc, deadpage, mimic, slavik, alan, olya, war, common, goodmorning, word_reactions} + flags {permsoc, media} + limits {persons, mimic, deadpage, media}. **AC-A2/T-975 трактуются в расширенной редакции (таблица целей ниже — единственная истина).** Обоснование: (1) первоисточник требований — ТЗ владельца; (2) «только триггеры/реакции»: war/common/goodmorning/word — функциональные модули-реакции (war-алерты, danger-контент, рассылка, словесные реакции персон — они часть PERMsoc-персонажей: kucha/vasya — реакции Славика/Васи, common — медиа Славика, war — сводка); (3) пример «логичные блоки: Медиа-реакции, Люди, Словесные, Таймеры/рассылки, Мимикрия, Dead page» — подтверждает; (4) перекладка задачи снимается девиансией на уровне spec (Builder следует spec); при несогласии владельца — откат одной строки TAB_RULES.

## 3. Целевое состояние (единая таблица — канон)

| Вкладка | Источники (категория, набор) | Итог |
|---------|------------------------------|------|
| `permsoc` («Функции PERMsoc») | reactions {persons, permsoc, deadpage, mimic, slavik, alan, olya, war, common, goodmorning, word_reactions} + flags {permsoc, media} + limits {persons, mimic, deadpage, media} | 11+2+4 = 17 групп |
| `reactions_triggers` («Реакции и Триггеры») | reactions {admin, summary, chat, memory} | 4 группы, без флагов |
| `limits` («Лимиты») | limits: except += {limits_persons, limits_mimic, limits_deadpage, limits_media, limits_lore}; flags: except += {flags_media, flags_permsoc, flags_modules, flags_service, flags_lore} | остаются: limits_cooldowns/summary/search/factcheck/checkup/youtube_web/chat/chat_behavior/chat_budgets/temperature/smart_cache/service/youtube_proxy/worker + flags_chat_behavior; limits_relations/limits_user_aliases — ОСТАЮТСЯ до фич F/B |
| `modules_switches` («Модули (вкл/выкл)», НОВАЯ) | flags {modules, service} | 2 группы |
| `chat_lore` («Лор чатов», не-config) | конфиг-часть: limits {limits_lore} + flags {flags_lore} | 2 группы + generic-блок в шаблоне |
| `modules_feats` («Модули», не-config) | — (карточки модулей; сводка PERMsoc удаляется) | — |
| `llm_providers`/`prompts`/`memory_rag` | без изменений | — |

**Порядок TABS (меню 'modules'):** `reactions_triggers` → `modules_switches` → `modules_feats` → `permsoc` (интервалы → переключатели → фичи-карточки → персонажи; существующий порядок reactions→modules_feats→permsoc сохраняет обусловленность первым табом секции reactions_triggers).

## 4. Ключевые решения

| ID | Решение | Обоснование |
|----|---------|-------------|
| **A-1** | TAB_RULES-правки (см. таблицу): (а) new записи `TAB_MODULES_SWITCHES = "modules_switches"` + правил; (б) `TAB_CHAT_LORE` получает ПРАВИЛО-источник `((LIMITS,{limits_lore}), (FLAGS,{flags_lore}))` — config-часть **не-config вкладки** (прецедент: TAB_PERMSOC-запись была config вкладка; здесь конфиг-часть внутри кастом-вкладки; проверить: `chat_lore` НЕ является config-вкладкой — правило только для TAB_RULES-аудита; `_TAB_BY_GROUP` отдаст 'chat_lore' для этих групп — НЕ ломает аудит «каждая группа ровно на одной вкладке»); (в) `TAB_LIMITS` except-списки расширяются (см. таблицу); (г) `TAB_REACTIONS_TRIGGERS` — 4 группы, категория flags удалена из правил. | Целевое состояние; _TAB_BY_GROUP без ValueError; группы не «в двух вкладках». |
| **A-2** | **TAB_PERMSOC — единая мастер-карта остаётся** (index.html:488-530: master per-chat/global, 5 модулей, сводка); к ней примкнут группы (персоны/лимиты/флаги PERMsoc/медиа). Логические «блоки» обеспечиваются ПОРЯДКОМ групп рендера в рамках вкладки (категории по порядку правил: reactions → flags → limits) + существующими title/description групп. **Слияние «Медиа и Оля»**: не создавать НОВУЮ группу (это изменило бы REGISTRY-числа!); фактически блок «Оля» виден рядом: reactions_olya (категория reactions) и flags_media (категория flags — 2-я по правилу). Переносить keys-подгруппы нельзя (REGISTRY). | REGISTRY 383/71/359 без изменений — «логичность» достигается порядком и заголовками, а не новой группой. |
| **A-3** | Порядок источников TAB_PERMSOC: `reactions → flags → limits` (существующий формат; порядок источников = порядок рендера). | Стабильность: master-флаги близко к персоне-группам. |
| **A-4** | **MENU_LABELS.modules → «Модули»** (app.js:80); **label modules_feats → «Модули»** (app.js:47). | ТЗ 2: «Модули и Фичи» → «Модули». |
| **A-5** | **Карточки модулей** (index.html, модульный блок modules_feats T-982): каждая карточка = имя (Например: «Славик», «Костя», «Леха (+приветствие)», «Оля», «Передразнивания», «Dead page», «War-алерты», «Common-медиа», «Утренняя рассылка», «Сон», «Ностальгия», «Авто-лор», «Саммари») + 1-2 строки описания + статус (существующий мастер/бейдж) + переход setTab (при наличии). Динамика: статичный HTML (тексты = константы index.html) — НЕ новый API. | ТЗ 2: «имена/описания модулей»; текстовые карточки — дешево, без API. |
| **A-6** | **Сводка «Функции PERMsoc» удаляется из modules_feats** (карточка + кнопка `setTab('permsoc')`; маркер «Открыть „Функции PERMsoc“ 🎭» — исчезает); вкладка permsoc и её мастер-карта — остаются (см. А-2). | ТЗ 2: «убрать сводку…НЕ удалять саму вкладку/функции»; F-198 — вкладка доступна в меню «Модули». |
| **A-7** | «Модули (вкл/выкл)» — отдельная config-вкладка `modules_switches` (flags {modules, service}); из «Лимитов» (flags except) эти группы уходят. НЕ конфликт с F-4 Баг-4: Баг-4 — после раунда (см. backlog конфликт-матрицу). | ТЗ 1: «Модули (вкл/выкл) → в раздел Модули»; каталог без дифов (группы существуют). |
| **A-8** | Лор-настройки: generic-блок «⚙️ Расширенные настройки» на вкладке `chat_lore` (после профиля лора/истории; рендер groupedForTab для групп limits_lore+flags_lore с per-chat override-кнопками и canEditConfig, сохранение — существующий POST /api/config; пер-чат — override-система как в generic). | ТЗ 1: «настройки лора → в Лор чатов под Расширенные»; канон: единый POST /api/config; 409/403 — существующие. |
| **A-9** | **canViewTab/RBAC**: вкладка `modules_switches` — config (категории flags — RBAC-секции flags; видимость по правилам context as-is); config-часть chat_lore — права каталога (param./flags., существующие; гейт блока — canEditConfig). `known_sections()` — **без расширения** (chat_lore секция существует). | R5/канон известных секций; новых RBAC-секций нет. |
| **A-10** | `CONFIG_TAB_TITLES` += `modules_switches` → «Модули (вкл/выкл)»; константы `TAB_MODULES_SWITCHES` в param_catalog рядом с TAB_PERMSOC:1358-1360. | Зеркала каталога↔фронта. |

## 5. Изменяемые файлы

| Файл | Что меняется |
|------|--------------|
| `services/param_catalog.py` | TAB_RULES (A-1), CONFIG_TAB_TITLES (A-10), константы (A-10); REGISTRY/GROUPS/Settings — НЕ меняются. |
| `web/app.js` | TABS-зеркало: permsoc/reactions_triggers/limits-источники; +modules_switches; labels (A-4); меню-теги. |
| `web/index.html` | (1) modules_feats: карточки модулей (A-5), удаление сводки PERMsoc (A-6); (2) chat_lore: generic-блок настроек лора (A-8); (3) если нужно — быстрые ссылки/«Функции PERMsoc» из «Модулей» → вкладка permsoc доступна в меню (Никаких новых кнопок setTab('permsoc')!). |
| Тесты | test_frontend_tab_mapping (composition + ALL_TABS + TAB_MODULES_SWITCHES + chat_lore-правило), test_webapp_nav_disclosure_ui (T-987…T-988-маркеры, негатив старой сводки), test_webapp_lore_ui (блок настроек лора — маркер), тест «каждая группа ровно на одной вкладке» — зелёный. |

## 6. Критерии приёмки

| AC | Критерий | Проверка |
|----|----------|----------|
| AC-A1 | импорт `param_catalog` без ValueError; `group_tab(gid)` для каждой из 17+4+2+2 групп — ровно ожидаемая вкладка | python-импорт/юнит |
| AC-A2 | `tab_group_ids('reactions_triggers') == {reactions_admin, reactions_summary, reactions_chat, reactions_memory}`; flags не входит | юнит |
| AC-A3 | `tab_group_ids('permsoc') == 11 реакционных + {flags_permsoc, flags_media} + 4 limits` | юнит |
| AC-A4 | на «Лимитах» нет: limits_mimic/deadpage/media/lore/persons; flags_modules/service/lore/media/permsoc; оставшееся — по таблице (limits_cooldowns, limits_summary, limits_search, limits_factcheck, limits_checkup, limits_youtube_web, limits_chat, limits_chat_behavior, limits_chat_budgets, limits_temperature, limits_smart_cache, limits_service, limits_youtube_proxy, limits_worker, limits_relations, limits_user_aliases + flags_chat_behavior, flags_relations) | юнит + маркер |
| AC-A5 | `tab_group_ids('modules_switches') == {flags_modules, flags_service}`; id/титул в каталоге+app.js | юнит + маркер |
| AC-A6 | `group_tab('limits_lore') == 'chat_lore'`; `group_tab('flags_lore') == 'chat_lore'`; `CONFIG_TAB_TITLES['chat_lore']` — «Лор чатов» без изменений | юнит |
| AC-A7 | REGISTRY 383 / 71 группа / Settings 359 — без изменений (test_param_catalog зелёный) | тест |
| AC-B1 | Зеркало TABS синхронно (маркеры exact); `node --check` clean | T-981 |
| AC-B2 | Карточки модулей содержат имя+описание (маркеры); мастер-тумблеры без регресса | T-982 |
| AC-B3 | `setTab('permsoc')` из modules_feats отсутствует (негатив); вкладка permsoc + мастер: остаются | T-983 |
| AC-B4 | `flags.*` (модули/сервис) видны на modules_switches; на `limits` их текстов нет (негатив-маркер) | T-984 |
| AC-C1 | Поля LORE_* и флаги лора доступны на chat_lore (маркер); сохранение — POST /api/config (409 — как в generic) | T-985 |
| AC-C2 | user-роль с секцией chat_lore: лор-профиль виден, конфиг-блок read-only/скрыт; local/global admin — редактирование. DM: chat_lore-вкладка скрыта? (по F-14: DM → 'chat_lore' 404 логика: вкладка в DM скрыта по canViewTab-ветке chat_lore — БЕЗ изменений; config-часть — недоступна в DM (профиль ЛС 404) — как сейчас для лора) | T-986 |
| AC | pytest 0 failed; node --check; git diff --check; live: новые вкладки рендерятся (T-989) | T-987…T-989 |

## 7. Негативные тесты (что НЕ сломать)

- **REGISTRY 383 / 71 / 359** (MED-017) — без изменений; новые группы/ключи ЗАПРЕЩЕНЫ (только переносы).
- **`_TAB_BY_GROUP`** — без ValueError (ни одна группа в двух вкладках: except-списки зеркальны со всеми фичами раунда: учтены будущие B (limits_user_aliases→people_names), F (limits_relations/flags_relations→relations) — НО на ЭТОМ шаге A эти группы остаются на «Лимитах» (их уход — B/F; порядок раунда это допускает; запрещено «превентивно» убирать их в A — двойные диффы).
- **SQLite v8**, **порядок роутеров bot.py**, **каноны промптов** — без дифов.
- **R16/R17** — имена/маскировка секретов не задеваются.
- **F-9/PERMsoc-изоляция** (runtime-плагин permsoc.py, PermsocGateFilter, master `flags.permsoc_enabled`, бэкфилы) — НЕ меняются (только UI/каталог).
- **F-10-гейты** (modules_feats карточки «Тяжёлые фичи»/«Бюджет фона» → данные gates/budget API) — не ломаются; карточка «Бюджет фона» остаётся на modules_feats.
- **test_param_catalog** — без изменений; **маркеры MED-022** — обновляются перечисленные; `test_webapp_lore_ui` (маркеры тумблеров лора) — зелёный.
- **DM**: modules_switches — config вкладка, видимость в DM по категории flags (существующая ветка); permsoc в DM скрыт (существующее правило — сохраняется); «Модули» (modules_feats) в DM — как сейчас (activeChatId==null логика; без изменений).
- **F-6**: SUPERSEDED — папка не трогается, регресс каскада в B/H.

## 8. Границы (вне скоупа)

- Логические «блоки» ВНУТРИ PERMsoc — только порядком рендера/заголовками групп (A-2); **новые группы не создаются** (ограничение REGISTRY).
- «Участники и отношения» — фича F (здесь только перенос limits_lore/flags_lore в chat_lore; limits_relations/flags_relations — F).
- «Имена людей» (limits_user_aliases) — фича B.
- Строки `flags.permsoc_enabled`/`flags.olya_enabled`/`flags.mimic_enabled` — на вкладке permsoc уже были; не перемещаются (flags_permsoc — источник и есть).
- Карточки модулей — статичные тексты; API-разведение «модулей» (реестр permsoc.py) — НЕ вводится на фронте (текущий реестр — permsoc.py).

## 9. Риски и блокеры

| Риск | Митигация |
|------|-----------|
| **Риск A-1**: D-A1-девиансия (T-975 трактуется шире) — возможное несогласие PM/Buildера. | Документирована §2; AC-таблица — единая истина; при откате — одна строка TAB_RULES + 2 группы обратно (малые диффы). |
| **Риск A-2**: конфиг-часть chat_lore (limits_lore/flags_lore) — per-chat override-кнопки на не-config вкладке (в шаблоне chat_lore нет configItems-логики): `groupedForTab` — работает по configItems (общий стейт), вкладка chat_lore имеет sources-правило? → для рендера передать «мнимый таб» (TABS-запись chat_lore в app.js — добавить `sources`-массив конфиг-части!) — **зеркало: chat_lore получает sources в app.js (для groupedForTab только)**, тип вкладки остаётся 'chat_lore'. | явное решение: TABS-запись chat_lore += `sources: [{category:'limits', groups:['limits_lore']},{category:'flags',groups:['flags_lore']}]` + кастом-рендер вызывает groupedForTab(chatLoreTab). |
| **Риск A-3**: «Модули (вкл/выкл)» — название «не модуль» в TABS-иконке/ид; дубль с label modules_feats «Модули». | ок: иконка «⚙️», label «Модули (вкл/выкл)» (T-978/AC-A5); путаница не критична. |
| **Блокер**: `_TAB_BY_GROUP` — ValueError если где-то забыт except: обязательный ранний pytest-прогон после T-974…T-977. | AC-A1/юнит-тесты (импорт) — первый прогон. |

## 10. Зависимости

- До: D/C/E. После: B (people_names), F (relations), H, G.
- B: limits_user_aliases уходит из «Лимитов» — except A уже не содержит (параметры A-таблицы: limits_user_aliases остаётся на пределах до B — да, B сделает).
- F: limits_relations/flags_relations — аналогично (до F остаются на пределах).
- F-4 Баг-4 — ПОСЛЕ раунда; F-1 — ДО B/G (атомарный POST — B учитывает); F-5 — ПОСЛЕ G/B (см. backlog).
