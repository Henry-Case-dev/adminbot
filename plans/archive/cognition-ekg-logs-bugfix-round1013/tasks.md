# Фича F6 — `cognition-ekg-logs-bugfix-round1013` (EKG-«Сердцебиение» + багфикс «Логи»)

> **Статус: ✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; реализовано Step 4 @Builder, 13.09.2026). Спека: `spec.md`.
> pytest 5351 passed / 0 failed; `node --check web/app.js` clean; `JS-UNIT-OK`;
> `git diff --check` clean. Каталог-Δ F6 = 0.
> **Раунд:** 10.13. **Нумерация:** T-1459…T-1464 (продолжает F5 T-1458).
> **Тип:** frontend (+ изменение контракта `/api/status/logs`). **Приоритет:** P2.
> **Зависимости:** независима (может идти параллельно F1–F5). Пересечение с F5 по странице «Статус»
> (разные зоны: аптайм vs ленты/граф) — согласовать порядок правок `web/index.html`/`web/app.js`.
> **ТЗ:** `plans/current_task.md`, разделы **8** («Анимация Сердцебиение Сервера») и **9**
> («Багфикс компонента Логи»).
> **Эпик:** `Epic: Cognition-Sleep-Memory Refactor round1013`.

## 0. Цель

Убрать бесполезный линейный график аптайма и заменить его живым SVG-EKG, привязанным к здоровью сервера.
Починить рассинхрон селектора и списка логов, добавить комбинированный тег `ERROR+WARNING` и сделать его
фильтром по умолчанию при открытии.

## 1. Требования (дословно из ТЗ §8 + §9)

- [x] Удалить старый линейный график аптайма в «Статусе».
- [x] Заменить на компактный SVG-компонент «Сердцебиение» (EKG) с CSS-анимацией; привязать параметры
      анимации к реальному здоровью сервера (`Load`/`CPU/RAM`): норма → спокойный зелёный,
      пик → учащённый оранжевый/красный.
- [x] Исправить баг: при открытии страницы в селекторе выбран `INFO`, а рендерятся `ALL` (все логи).
- [x] Добавить в селектор новый комбинированный тег **`ERROR+WARNING`**.
- [x] При первичном открытии мини-аппа фильтр логов по умолчанию — всегда **`ERROR+WARNING`**.

## 2. Целевые модули (`file:line` на HEAD `ce25dc7`)

- `web/app.js` — `logLevel: 'INFO'` `:860`, `loadLogs()` `:3786` (`/api/status/logs?level=`),
  `renderUptimeChart()` `:3575` (`uptimeCanvas`, chart `:3610-3611`), `uptimeChart` state `:851`.
- `web/index.html` — аптайм-карточка `:2714-2719` (`<canvas v-else ref="uptimeCanvas" height="90">`),
  лог-селектор `:2766-2768` (`['ALL','DEBUG','INFO','WARNING','ERROR','CRITICAL']`), badges `:2774-2775`.
- `web/api/routes.py` — `GET /status/logs` `:1124-1136` (`level: str = Query(default="INFO")`, docstring
  «DEBUG|INFO|WARNING|ERROR|CRITICAL|ALL»).
- `services/log_ring.py` — `get_entries()` `:139-152` (порог «не ниже уровня», `ALL` = без фильтра).
- `services/uptime_heartbeat.py` — `_heartbeat()` `:67` (пульс/метрики, при необходимости — источник для EKG).
- `services/status_service.py` — `_server_metrics()` `:354` (cpu/loadavg/memory), uptime-бакеты `:386`.
- Тесты: `tests/test_webapp_round1013_ui.py` (новый), `tests/test_webapp_*log*`, `tests/test_log_ring*`,
  `tests/js/routing_test.js`.

## 3. Инварианты (constraints — не нарушать)

- **Контракт `GET /api/status/logs` изменится** (новый комбинированный тег `ERROR+WARNING`) — обязательна
  правка маркерных тестов и docstring; существующие теги (`DEBUG/INFO/WARNING/ERROR/CRITICAL/ALL`) не ломать.
- **R17:** логи уже маскируются в ring-buffer; не ослаблять; секреты не логировать/не эхо.
- **Ноль новых PG-DDL**; SQLite **v8**; порядок роутеров `bot.py` не трогать.
- **Каталог-инварианты 405/90/377/88, TAB_RULES 19** — новые параметры (если появятся пороги EKG) только
  санкционированным Δ + пин-тесты.
- Не ломать существующий Chart.js key-history (F5/10.11); EKG — **свой** SVG/CSS, без нового тяжёлого графика.
- `prefers-reduced-motion` и доступность (WCAG AA) — сохранить/учесть для анимации.
- **R10.12-2/-3/-4** (stale docstring probe, `KOSTIK_ENABLED` вне `.env.example`, index-key list-editor) —
  не блокеры; при касании затронуть нельзя/можно закрыть точечно (не обязательно в этой фиче).
- **Коммиты:** русские conventional commits.

## 4. Зависимости

- **Вверх:** нет.
- **Пересечение:** F5 (дашборд) — тот же файл/страница «Статус»; **исполнять F5 и F6 последовательно**
  (или согласовать правки), чтобы не конфликтовать в `web/index.html`/`web/app.js`.
- **Вниз:** нет.

## 5. Definition of Done

- [x] Старый линейный график аптайма удалён.
- [x] SVG-EKG с CSS-анимацией привязан к Load/CPU/RAM: спокойный зелёный ↔ учащённый оранжевый/красный.
- [x] Рассинхрон селектора/списка устранён (единый источник истины `logLevel`).
- [x] Новый тег `ERROR+WARNING` в селекторе и на сервере; при открытии по умолчанию выбран он.
- [x] Сервер корректно фильтрует комбинированный тег; маркерные тесты контракта обновлены.
- [x] `node --check web/app.js` clean; `JS-UNIT-OK`; полный `pytest` — 0 failed; `git diff --check` чист.
- [x] R17 не ослаблен; анимация уважает `prefers-reduced-motion`.

## 6. Чек-лист задач

- [x] **T-1459 (@Architect, гейт):** spec/ADR: семантика комбинированного тега `ERROR+WARNING` (включает
  ERROR и WARNING, без ниже), маппинг на `log_ring.get_entries`, обратная совместимость API, поведение
  дефолта при открытии; параметры EKG (пороги Load/CPU/RAM → скорость/цвет), выбор SVG+CSS vs JS.
- [x] **T-1460 (@Builder, EKG):** удалить линейный график аптайма (`renderUptimeChart`/`uptimeCanvas`/state);
  добавить компактный SVG-компонент «Сердцебиение» с CSS-анимацией; привязать скорость/цвет к Load/CPU/RAM
  (спокойный зелёный ↔ учащённый оранжевый/красный); учесть `prefers-reduced-motion`.
- [x] **T-1461 (@Builder, баг логов):** устранить рассинхрон селектора (`INFO`) и фактического рендера
  (`ALL`); единый источник истины; загрузка логов при первичном открытии использует выбранный уровень.
- [x] **T-1462 (@Builder, новый тег):** добавить `ERROR+WARNING` в селектор и в `services/log_ring.get_entries`/
  `web/api/routes.py` (`level`); дефолт при первичном открытии = `ERROR+WARNING`; docstring/контракт обновлены.
- [x] **T-1463 (@Builder, тесты):** маркерные тесты контракта `/api/status/logs` (комбо-тег, дефолт),
  `test_log_ring` (фильтр ERROR+WARNING = ERROR∪WARNING), UI-статика (нет `uptimeCanvas`/есть EKG-маркеры,
  `logLevel` default), JS-юниты (model/filter); обновление существующих маркеров.
- [x] **T-1464 (@Builder):** `node --check web/app.js`, `node tests/js/routing_test.js` → `JS-UNIT-OK`,
  полный `pytest` (0 failed, дельта), `git diff --check` clean.

## 7. Открытые вопросы (@Architect → владелец)

- **F6-Q1:** `ERROR+WARNING` — клиентский фильтр (два запроса/локальная фильтрация) или серверный новый тег?
- **F6-Q2:** какие именно метрики задают «пульс» (Loadavg на Windows = None → CPU/RAM fallback)?
- **F6-Q3:** удалять ли данные/поля `uptime` из `/api/status` (оставить для истории ключей) — контракт?
- **F6-Q4:** «при первичном открытии» — только первый заход в сессию или каждый заход на вкладку «Статус»?
- **F6-Q5:** пороги «пика» (проценты CPU/RAM/Load) — в каталог (Δ) или константа settings?

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (render-only + расширение существующего контракта логов).
- **Rollout stages:** неприменимо (внутренний инструмент одного владельца).
- **Rollback:** атомарный `git revert`.
