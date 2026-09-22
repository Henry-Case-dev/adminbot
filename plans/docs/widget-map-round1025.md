# F8 — Карта виджетов `widget-map-round1025.md` (ADR-1025-21 D3)

> **Фича:** F8 `parameter-registry-widget-map-round1025` (read-only enabler). **ТЗ:** §2, §11–§21, §117 п.3.
> **Маркер:** `widget-map-round1025`. **Источники:** маршруты `web/api/*` (см. `plans/reports/round1025_f8_results.md`, блок A) и потребители в `web/app.js`.
> **Правило REQ-F8-08:** «есть в API, но исчез из UI ≠ сохранено». Колонка `ui_visibility ∈ {visible,hidden,api-only}`; `api-only` = данные доступны серверу, но UI-места нет → **не** считается сохранённым в интерфейсе.
> **R17:** секреты — только `{configured,last4}`; открытые значения в карту не попадают.

## Легенда

- `data_source` — реальный эндпоинт(ы)/адаптер, откуда виджет берёт данные (проверено по `web/api/*`).
- `new_location` — целевое место в IA §4 (Статус / Справка / Модули / ИИ / Память / Доступы / PERMsoc / Аналитика).
- `preserved_actions` — действия пользователя, которые обязаны сохраниться.
- `ui_visibility` — `visible` | `hidden` | `api-only`.

## Статус — витрина (§11–§20)

| old_widget | data_source | new_location | preserved_actions | ui_visibility |
|---|---|---|---|---|
| Hero состояния бота | `GET /api/status`, `GET /api/me` | Статус → Hero | статус/аптайм/последняя активность; компактное предупреждение об ошибке | visible |
| Системные метрики (CPU/RAM/диск/аптайм) | `GET /api/status` (system/metrics) | Статус → системные метрики | число+progress bar; «серверные метрики — ко всему серверу» | visible |
| Живое сердцебиение | `GET /api/status` (телеметрия; Canvas 2D, polling) | Статус → heartbeat | состояния HEALTHY/WARNING/CRITICAL/UNKNOWN; hover/нажатие с деталями | visible |
| Граф связей | `GET /api/memory/graph` | Статус → граф связей (+ отдельный экран исследования) | поиск по имени/алиасу, фокус, ближайшие связи, фильтры, детали, сброс | visible |
| Виджет сна (обычный/глубокий) | `GET /api/memory/deep-sleep`, `GET /api/memory/dream/log` | Статус → сон и активность | бейджи «Сон через…»/«Глубокий сон через…»; активное состояние с сервера | visible |
| Мониторинг интеллекта: убеждения | `GET /api/memory/dream/beliefs?kind=belief` | Статус → мониторинг интеллекта | живая лента, время/текст, раскрытие, protected | visible |
| Мониторинг интеллекта: парадигмы | `GET /api/memory/dream/beliefs?kind=paradigm` | Статус → мониторинг интеллекта | реальные данные/история; «нет результатов» без выдумок | visible |
| Мониторинг интеллекта: эволюция характера | `GET /api/persona`, `GET /api/persona/health` | Статус → мониторинг интеллекта | черты/история/состояние экстрактора | visible |
| Живая лента досье | `GET /api/oversight/dossier_feed?limit=16` | Статус → лента досье | вертикальная прокрутка без сброса позиции; имя/текст/время/тип | visible (env-гейт `DOSSIER_LIVE_FEED_ENABLED`) |
| Бюджеты и лимиты интеллекта | `GET /api/workers/budget`, `GET /api/status` (context budget) | Статус → бюджеты + Модули → Бюджеты | «Без лимита» без заполненного бара; «Нет данных» вместо $0 | visible |
| Превью карты LLM-вызовов | `GET /api/analytics/usage/latest` (адаптер `web/static/execution_graph.js`) | Статус → превью вызова; полная карта — Аналитика | компактное превью последнего вызова (не одна строка с числом) | visible |
| События | `GET /api/oversight/summary`, `GET /api/memory/timeline` | Статус → события | лента событий за период | visible |
| Логи | `GET /api/status/logs` | Статус → логи | уровни ERROR+WARN/ERROR/WARN/INFO, раскрытие, копирование строки | visible |
| Быстрый переход «Ошибки/Предупреждения» | `GET /api/status/logs` | Статус → счётчики сверху | прокрутка к логам по нажатию | visible |
| История ключей (key-history) | `GET /api/status/key-history` | Статус → график | leak-safe временной график доступности | visible |
| Media-health | `GET /api/status/media-health` | Статус → индикатор медиа | статус доступности медиа | visible |
| Токен-метрики NodeFlow | `GET /api/analytics/usage/latest` | Статус → превью | подсветка этапов последнего вызова | visible (env-гейт `TOKEN_FLOW_NODEFLOW_ENABLED`) |

## Аналитика (§21) — открывается из Статуса

| old_widget | data_source | new_location | preserved_actions | ui_visibility |
|---|---|---|---|---|
| Расходы/токены и распределение | `GET /api/analytics/usage/summary`, `GET /api/analytics/usage/latest` | Статус → Аналитика | период (день/неделя/месяц), распределение по моделям/модулям | visible |
| Карта LLM-вызовов (режимы «последний вызов» / «период») | `GET /api/analytics/usage/latest` + адаптер | Статус → Аналитика | выбор узла → детали; фильтры модуль/модель/этап/период/статус | visible |
| Дерево вызовов / история | `GET /api/analytics/usage/summary` | Статус → Аналитика | история вызовов за период | visible |
| Цены моделей | `GET /api/analytics/prices`, `PUT /api/analytics/prices` | ИИ → Аналитика цен (просмотр/правка) | просмотр/правка цен | visible |
| Сводка Oversight по чатам | `GET /api/oversight/summary`, `GET /api/oversight/chat/{chat_id}` | Статус → Аналитика (только global admin) | killswitch/global_key per chat | visible |
| Токен-аналитика (страница) | `GET /api/analytics/usage/latest`, `GET /api/analytics/usage/summary?period=` | Статус → Аналитика | выбор периода | visible |

## Память / Справка / ИИ / Доступы

| old_widget | data_source | new_location | preserved_actions | ui_visibility |
|---|---|---|---|---|
| Граф знаний (память) | `GET /api/memory/graph`, `GET /api/memory/stats` | Память → граф | фильтры/детали узлов | visible |
| Здоровье памяти | `GET /api/memory/health` | Память / Статус | overdue/unconfirmed/сырьё/хранилище | visible |
| Лор чата | `GET /api/chat_lore/{chat_id}`, `GET /api/chat_lore/chats` | Память → Лор чата | правка/генерация/remap/история | visible |
| Участники и отношения | `GET /api/chat_lore/{chat_id}/relations` | Память → Участники и отношения | правка отношений, включение отношений | visible |
| Досье участника | `GET /api/chat_lore/{chat_id}/dossier/{user_id}` | Память → досье | просмотр/правка досье | visible |
| Справка/гайд | `GET /api/info/guide`, `GET /api/info`, `GET /api/info/guide/backup` | Справка | просмотр/бэкап/сброс гайда | visible (публично) |
| Личность и стиль | `GET /api/persona`, `PUT /api/persona`, `DELETE /api/persona` | ИИ → Личность (+ Статус) | просмотр/правка/сброс, health | visible |
| Умный кэш / анти-клише | `GET /api/anticliche`, `POST /api/anticliche/refresh`, `PUT /api/anticliche` | ИИ → Промпты → анти-клише | список/обновление/правка | visible |
| Матрица прав | `GET /api/roles/tree`, `GET /api/access/param_permissions` | Доступы | выда/снятие прав параметров, дерево ролей | visible |
| Админы | `GET /api/admins`, `POST /api/admins`, `POST /api/admins/remove` | Доступы | список/назначение/снятие | visible |
| Роли | `GET /api/roles`, `POST /api/roles`, `DELETE /api/roles/{role_name}`, `POST /api/roles/{role_name}/rename` | Доступы | CRUD/переименование/права | visible |
| BYOK-ключи (маски) | `GET /api/config/keys/own`, `GET /api/config/keys/status` | ИИ → LLM Провайдеры | `{configured,last4}`; замена `PUT /api/config/keys/own` | visible |
| Модульные гейты (переключатели) | `GET /api/chat/{chat_id}/gates`, `PUT /api/chat/{chat_id}/gates` | Модули | вкл/выкл per-chat | visible |
| Аватары | `GET /api/avatar/{kind}/{tid}` | Статус / Память | отображение аватара | visible |
| Категории событий/логов (аналитика) | `GET /api/analytics/usage/*` | Аналитика | фильтры | visible |

## api-only — есть в API, но исчез из UI (≠ сохранено) / заведомо вне UI

| old_widget | data_source | new_location | preserved_actions | ui_visibility |
|---|---|---|---|---|
| Снимок in-memory состояния (debug) | `GET /api/debug/config` | — | read-only диагностика (admin/debug); UI-места нет → **не сохранено в UI**, API-контракт сохранён | api-only |
| Здоровье сервиса | `GET /api/health` | — | внешний мониторинг (ngrok/uptime); UI-места нет | api-only |
| Системные kill-switch-и UI (env-only) | `GET /api/me` (`ui_flags`) | Статус | доставка флагов shell во фронт (bool), без UI-тумблера | api-only |
| per-chat killswitch | `POST /api/oversight/chat/{chat_id}/killswitch` | Статус → Аналитика | экстренное отключение чата (global admin) | visible |
| Управление процессом бота | `POST /api/control/restart`/`stop`/`start` | Статус | рестарт/стоп/старт (роль/глоб. админ) | visible |
| Тесты соединений LLM/изображений | `POST /api/llm/test`, `POST /api/images/test` | ИИ → LLM Провайдеры | тест подключения | visible |

## Инварианты карты (проверяются маркер-тестами F8)

1. **0 потерянных виджетов:** каждый виджет §11–§21 присутствует строкой (полнота сверяется с реестром/картой экранов и `tests/`).
2. **api-only ≠ сохранено:** данные, существующие только в API (`/api/debug/config`, `/api/health`, `ui_flags`), явно помечены `api-only` и не выдаются за сохранённые в интерфейсе.
3. **R17:** секреты нигде не раскрыты; BYOK-виджет демонстрирует только маску `{configured,last4}`.
4. **Источники данных не дублируются и не выдуманы** — только реальные маршруты `web/api/*` и адаптеры `web/static/*`.
