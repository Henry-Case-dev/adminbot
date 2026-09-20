# Spec: dossier-live-feed-round1024 (F4)

> Раунд 10.24 (UPD2 п.2 + UPD3 №9) · P1 · UI/web + API · Владелец: F4
> Ступень `web/**`: **5-я** (F3→F5→F6→F11→**F4**→F10)
> **ADR:** ADR-1024-8 (AMEND 10.20 T-1897 / ADR-1022-8)
> **Сквозной слой:** `plans/features/round1024-web-architecture.md`

## 1. Цель

1. Лента «Живая лента досье»: горизонтальный marquee 42s → **вертикальный
   (снизу вверх), заметно медленнее**, читаемый.
2. **Каждая строка кликабельна** → переключение контекста на чат факта и открытие
   модалки «Досье» участника (решение UPD3 №9).

## 2. Что уже есть (координаты)

| Что | Где |
|---|---|
| Горизонтальная анимация 42s, mask 90deg, пауза по hover | `web/static/app.css:952-980`, `:1027-1031` |
| Разметка ленты (`role="marquee"`) | `web/index.html:1351-1374` |
| Модель `dossierFeedLoop` (дублирование для seamless-скролла) | `web/app.js:1413-1430` |
| API `GET /api/oversight/dossier_feed?chat_id&limit` → `{chat_id, items:[{chat_id,name,excerpt}]}` | `web/api/oversight.py:175-207` |
| Источник `db.dossier_feed` → `{chat_id, name, fact}` (`target_user AS name`) | `services/database.py:4551-4580` |
| `openDossier(row)` требует `row.user_id` **и** `this.activeChatId` | `web/app.js:2868-2885` |
| Канон имени участника (AliasResolver) + `{user_id: name}` участников | `web/api/chat_lore.py:579,666-682,822-839` |
| `setActiveChat(chatId)` (меняет scope → reload) | `web/app.js:1916-1950` |
| Фоновый поллинг ленты | `web/app.js` `loadDossierFeed`/`startDossierFeedPolling` |

**Проблема:** в `graph_facts` нет `user_id` (только `target_user` — имя), поэтому
API не отдаёт идентификатор, а модалка без него не открывается.

## 3. Требуемое поведение

### 3.1. Вертикальная лента (CSS)

- Контейнер `dossier-ticker` получает **фиксированную высоту** (например
  `--dossier-h: 180px`; ≤ `40vh` на мобиле) и `overflow:hidden`.
- Дорожка — `flex-direction: column`, `translateY`-анимация **снизу вверх**:
  `from { transform: translateY(0) } to { transform: translateY(calc(-100% - gap)) }`
  (тот же приём дублирования контента, что был для горизонтали, «повёрнутый»).
- Скорость — **существенно медленнее**: базовая длительность ≥ **72s** и
  масштабируется от числа элементов: `duration = max(72s, items × 6s)` (медленнее
  при больших списках, чтобы скорость строки не росла).
- `mask-image: linear-gradient(180deg, transparent, #000 12%, #000 88%, transparent)`.
- `prefers-reduced-motion: reduce` → `animation: none`, контейнер становится
  обычным прокручиваемым списком, mask снимается (как сейчас `:1027-1031`).
- Hover/focus — пауза (сохранить).
- Число элементов — ограничено (`limit ≤ 24`) и лёгкий CSS; без тяжёлых теней.

### 3.2. Клик → Досье (контракт строки)

- Строка рендерится как `role="button"`, `tabindex="0"`, обработчики `@click` и
  `@keydown.enter`/`space` (a11y). Внутри — прежние `name/chatLabel/excerpt` + `◆`.
- Клик вызывает `openFeedDossier(it)`:
  1. если `it.user_id == null` → строку **не делаем** кликабельной (рендер как текст),
     курсор обычный (нет ложного affordance);
  2. если `activeChatId == null` **или** `String(activeChatId) !== String(it.chat_id)`:
     сначала `setActiveChat(String(it.chat_id))` (батч-переключение scope: config/lore/
     oversight перезагрузятся), затем `openDossier({user_id, name})`;
  3. иначе → сразу `openDossier({user_id, name})`.
  4. ошибка переключения → `toast` с понятным текстом, модалка не открывается.
- `openDossier` **не** менять по контракту (он per-chat) — переключение делает вызывающий.

### 3.3. Backend: добавить `user_id` (резолв, без DDL)

- Значение `name` в `graph_facts.target_user` — **каноническое имя** (alias/nickname).
  Обратный резолв `name → user_id` строится **read-time** для каждого `chat_id`
  из результата ленты (обычно 1–N чатов, N ≤ limit):
  - источник `{user_id: author_name}` — `db.get_active_participants(chat_id, now−30д, 200)`
    (уже используется в `web/api/chat_lore.py::_participant_names`);
  - поверх — `summary_aliases.build_alias_resolver(chat_id)`: для каждого `uid`
    получить канонический alias и добавить в обратную карту `alias → uid`;
  - инвертировать карту; при коллизии имён — приоритет более «свежего»/активного
    участника (детерминированно: меньший `user_id` как tiebreaker).
- В ответ API аддитивно (R16): `items[].user_id: int | null`,
  `items[].user_name: str` (канон-имя, может совпадать с `name`).
- **Fail-open:** ошибка резолва (нет БД/исключение) → `user_id=null`, лента всё
  равно отдаётся текстом (без 500).
- Работу резолва кэшировать в пределах запроса (не звать на каждую строку).
- **R17/приватность:** эндпоинт уже под `requires_global_admin`; новых
  персональных полей, кроме `user_id` (используется в UI повсеместно), не добавляем.
- Δ DDL = 0 — колонка `user_id` в `graph_facts` **не создаётся** (сохраняем
  `imported-history-immutable`/`manual-overrides-immutable` и нулевой DDL).

### 3.4. Реактивность

- Лента по-прежнему: GLOBAL (нет `chat_id`) → все чаты; активный чат → только он.
- При смене скоупа — прежний одиночный запрос (`startDossierFeedPolling` не менять).
- `dossierFeedLoop` пересчитать под вертикаль (тот же дубль-массив, замена `key`-суффикса).

## 4. Изменения по файлам

| Файл | Что |
|---|---|
| `web/static/app.css` | Переписать `.dossier-ticker*` под вертикаль; `--dossier-h`, `--dossier-speed`; mask 180deg; `prefers-reduced-motion` fallback; `.dossier-ticker__item` → строка-кнопка стили (hover/focus). |
| `web/index.html` | Шаблон ленты `:1364-1373`: вертикальная дорожка, строки `role="button"` + `@click`/`@keydown`, гейт `uiFlag('DOSSIER_LIVE_FEED_ENABLED')` (OFF → прежняя горизонталь). |
| `web/app.js` | `openFeedDossier(it)`; `dossierFeedLoop` под вертикаль; передача `user_id`/`chat_id` в модели; `uiFlag`. |
| `web/api/oversight.py` | Резолв `user_id`/`user_name`, аддитивные поля в items (§3.3). |
| `services/database.py` | (при необходимости) helper обратного резолва имени — **read-only**, без DDL. |
| `config/settings.py` + `routes.me` | флаг `DOSSIER_LIVE_FEED_ENABLED` (enabler). |
| `tests/**` | см. §6. |

## 5. Контракты

- **API (аддитивно, R16):** `items[] = {chat_id:int, name:str, excerpt:str,
  user_id:int|null, user_name:str}`. Прежние поля не удаляются/не переименовываются.
- **Frontend:** `openFeedDossier({chat_id, user_id, name, user_name})`;
  `openDossier({user_id, name})` — без изменений.
- **GLOBAL-режим:** переключение контекста обязательно до открытия досье.
- **Fail-open:** резолв/лента/переключение — ошибки не ломают вкладку.

## 6. Тесты

- **Python (`tests/test_webapp_oversight_api.py` + новый `test_dossier_feed_round1024.py`):**
  - API отдаёт `user_id` для строк, чьё `target_user` матчится с участниками чата;
  - нерезолвленное имя → `user_id is null`, строка остаётся в ответе;
  - ошибка резолва → `user_id=null` и HTTP 200 (fail-open);
  - контракт-совместимость: прежние ключи `chat_id/name/excerpt` на месте;
  - «нет plaintext-секретов» (R17) — значение секретов не появляется.
- **JS (`tests/js/round1024_dossier_feed_test.js`, node):**
  - `dossierFeedLoop` дублирует элементы и пересчитывает ключи;
  - `openFeedDossier`: `user_id=null` → нет вызова `openDossier`;
  - `activeChatId` пуст → сначала `setActiveChat(chat_id)`, затем `openDossier`
    с верным `user_id`;
  - `node --check web/app.js`.
- **CSS-маркер:** `test_webapp_oversight_ui` / smoke — присутствует
  `dossier-ticker-scroll-y` (или аналог), `prefers-reduced-motion`.
- **Гейт:** `tests/js/vue_mount_test.js` зелёный.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | GLOBAL-лента ↔ per-chat досье (нет активного чата) | High | §3.2: сначала `setActiveChat`, иначе no-op + toast |
| R2 | Вертикальная анимация тормозит TMA | Medium | фикс. высота, `limit ≤ 24`, лёгкий CSS, `will-change: transform` |
| R3 | `user_id` раскрывает внутренние ID | Medium | только в global-admin эндпоинте; поле и так используется в UI |
| R4 | Резолв дорогой (N чатов × запрос) | Medium | кэш в пределах запроса, `get_active_participants` с лимитом 200 |
| R5 | regress `prefers-reduced-motion` | Low | сохранить медиа-блок |

## 8. Критерии приёмки

- Лента движется **вертикально снизу вверх** и заметно медленнее горизонтали.
- Клик по строке с извлечённым участником открывает «Досье»; в GLOBAL-режиме
  контекст чата переключается корректно; строки без `user_id` некликабельны.
- API отдаёт `user_id` аддитивно и не раскрывает лишнего; fail-open соблюдён.
- Δ DDL = 0; JS-гейт и pytest зелёные.

## 9. Флаг и откат

- `DOSSIER_LIVE_FEED_ENABLED` (env-only `ClassVar`, **default ON**) через `ui_flags`;
  OFF → горизонтальный тикер 42s, строки некликабельны.
- Откат: флаг OFF / `git revert`. Миграций нет, схемы не менялись.
