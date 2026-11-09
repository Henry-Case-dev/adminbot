# MOD-ACL-UX-01 M3 — «Векторная память»: маршрут раздела и честный отказ

Кандидат: ветка `integ/unify-release`, коммит — см. `git log -1 -- <этот файл>`.
Слайс: `web/app.js`, `web/index.html` (сервисы не тронуты).

## Что было сломано (подтверждено кодом и прогоном)

1. Реестр модулей (`services/module_registry.py`) отдаёт карточке `embeddings`
   `tab/config_tab = mod_embeddings`, а маршрут `#/modules/embeddings`
   резолвится в этот же id. В статическом `TABS` такой вкладки нет
   (инфраструктурный модуль без собственного мастера), поэтому
   `canViewTab('mod_embeddings')` возвращал `false` ЛЮБОЙ роли — включая
   глобального админа. Гейт `applyRoute` показывал «Нет доступа к разделу» и
   уводил на `#/`.
2. `isGlobalAdmin` во фронте опирался на legacy-эвристику
   (`role_name === 'admin'`/wildcard) и игнорировал серверный
   `me.is_global_admin`. Кастомная роль с `role_type=global_admin` без
   legacy-имени считалась обычным пользователем → «Аналитика», «Модули»,
   карточка Embeddings закрывались при уже разрешённом сервере.
3. Панель `GET /api/memory/embeddings` при 403 показывала «Панель недоступна» —
   отказ прав выглядел как техническая поломка.

## Таблица маршрутов реестра (до → после, роль = авторизованный глобальный админ)

| модуль | вкладка карточки | до | после |
|---|---|---|---|
| initiative | mod_initiative | открывается | открывается |
| factcheck | mod_factcheck | открывается | открывается |
| vision | mod_vision | открывается | открывается |
| nostalgia | mod_nostalgia | открывается | открывается |
| sleep | mod_sleep | открывается | открывается |
| stories | memory_rag | открывается | открывается |
| experience | memory_rag | открывается | открывается |
| random | mod_sleep | открывается | открывается |
| character | permsoc | открывается | открывается |
| **embeddings** | **mod_embeddings** | **«Нет доступа к разделу» (любая роль)** | **страница модуля открывается** |
| factcheck_temporal | — (hidden) | в выдаче фронта отсутствует | без изменений |

Остальные маршруты не менялись: их вкладки есть в `TABS`, гейт по секциям
прежний.

## Направление отказа

Страница модуля без своей config-вкладки = раздел «Модули»
(`canViewTab('modules')`). Нет прав на «Модули» → по-прежнему
«Нет доступа к разделу» и `#/`; неизвестный `mod_*` (нет такого модуля) →
отказ даже админу; `applyRoute` для неизвестного slug → витрина «Модули».

## Проверки

- `node tests/js/mod_acl_ux_m3_module_routes_test.js` — 119 проверок
  (все 10 видимых модулей реестра, оба направления, три состояния панели).
  RED до фикса: тот же тест на `HEAD:web/app.js` падает на
  `admin: страница модуля «embeddings» (mod_embeddings) доступна`.
- `py -3 -m pytest tests/test_mod_acl_ux_01_m3_module_routes.py` — 3 passed
  (включая drift-guard снимка реестра).
- Полный `tests/js`: 104 pass / 8 fail — все 8 падают и на `HEAD` без моих
  правок (проверено отдельным worktree на HEAD).
- Python routing/permission: 191 passed (`test_mod_acl_ux_01_m3_*`,
  `test_mod_acl_ux_01_m1_acl_false_403`, `test_access`, `test_dm_access`,
  `test_webapp_deps`, `test_round106_ia_smoke`, `test_webapp_nav_disclosure_ui`,
  `test_webapp_round1014_ui`) + 97 passed (agi/evol/scope-наборы).

## Экраны (Playwright, 1280×900, статичный web/ + заглушки /api)

- `m3-vector-memory-admin-1280.png` — `#/modules/embeddings` у глобального
  админа: шапка «Векторная память (Embeddings/GraphRAG)», вкладка «Обзор».
- `m3-vector-memory-user-denied-1280.png` — тот же адрес у обычного
  пользователя: тост «Нет доступа к разделу», адрес `#/`.
- `m3-panel-empty-1280.png` — панель в «Аналитика → Память и интеллект»:
  «Индексы ещё не построены.» (`data-embeddings-state="empty"`).
- `m3-panel-denied-1280.png` — сервер вернул 403 при админе по `/api/me`:
  «Нет доступа к панели векторной памяти…» (`data-embeddings-state="denied"`).

Ограничение заглушки: `/api/config` отдаёт пустой список items, поэтому блок
«На этой вкладке нет доступных параметров» на скриншоте модуля — следствие
заглушки, а не продукта.
