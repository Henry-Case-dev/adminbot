# Spec: tma-relume-redesign — редизайн TMA-админки по референсу Relume

> ## 🆕 v3-указатель (10.09.2026, Step 2 @Architect, E3) — ЧИТАТЬ `design-project.md` v3
>
> `design-project.md` обновлён до **v3** по решениям владельца **OD7–OD10** (поздний вечер
> 10.09.2026): **D6/D7 — ✅ RESOLVED** (Чат-Профиль = глобальный **scope-switcher**;
> B1 — в скоупе; B2 — OUT; B3 — в скоупе и расширен). Подробные спеки — `design-project.md`
> **§15** (15.1 scope-switcher, 15.2 key-availability, 15.3 role-matrix, 15.4 font-delivery,
> 15.5 deep-link, 15.6 вопросы владельцу). Этот `spec.md` остаётся **исследовательским
> приложением** (разбор референса/кода). **Реализация — за hard-gate.**

> ## ⚠️ v2 (10.09.2026, Step 2 @Architect) — этот файл ЧАСТИЧНО SUPERSEDED
>
> **Главный deliverable раунда 10.5 = `design-project.md` (эта же папка).**
> Он построен по решениям владельца **OD1–OD6** и является АВТОРИТЕТНЫМ для реализации.
> Этот `spec.md` сохранён как **исследовательский приложение** (§1–§2 — разбор референса,
> §2 — фактическое состояние кода) и как история проектных решений.
>
> **СООТВЕТСТВИЕ OD1–OD6 (что отменено, что закреплено):**
>
> | Решение владельца | Что было в v1 (@Architect) | Статус v2 |
> |---|---|---|
> | **OD1** — навигация = вариант **B, полный ребейлд** (mirror reference IA) | рекомендовался вариант **C** (hybrid) | **OD1 отменяет**: реализуем **B** (navbar+hub+hash), см. `design-project.md` §2/§6 |
> | **OD2** — скоуп **ВСЁ СРАЗУ** (big-bang) | рекомендовалось **поэтапно** | **OD2 отменяет**: один заход, но внутренний порядок tokens→shell→hub→15screens→QA (`design-project.md` §7) |
> | **OD3** — технология **та же** (Vue3 global, zero-build) | та же | ✅ совпадает, закреплено |
> | **OD4** — палитра эталона как база + **АНИМИРОВАННЫЕ градиенты**, reduced-motion, WCAG AA | рекомендовался **P3** (статичная схема) | **OD4 заменяет**: градиент-токены + `@property` + reduced-motion (`design-project.md` §4) |
> | **OD5** — **Material Icons** primary; emoji временно | рекомендовалось emoji now, Material follow-up | **OD5 заменяет**: Material Symbols Rounded, спека размеров/осей/поставки (`design-project.md` §5) |
> | **OD6** — **структура эталона = эталон композиции** (15 страниц) | — (новое) | ✅ закреплено: `design-project.md` §2/§7 |
>
> **Hash-routing:** при OD1(B)+OD3 он **ОБЯЗАТЕЛЕН** (следствие, не опция) — см.
> `design-project.md` §6 и `tasks.md` §0.1. `D8` = только back/deep-link.
>
> **Открытые вопросы (обновлено v3):** **D6 — ✅ RESOLVED (OD7)**;
> **D7 — ✅ RESOLVED (OD8/OD9/OD10)**; **D8 — ✅ back RESOLVED**; открыты **D9 (deep-link)**
> и **D11 (файл шрифта)**. Актуальные спеки — `design-project.md` **§15** (старые §11.1/§11.2 —
> SUPERSEDED).
>
> **Реализация НЕ начинается** до апрува `design-project.md` владельцем (GATE,
> `design-project.md` §14).

---

> **Статус v1 (исторический):** 🟡 DESIGN (Step 2, @Architect). Реализация НЕ стартует до апрува
> решений §7 (T-1076).
> **Вход:** ТЗ владельца 10.09.2026 + `reference-analysis.md` + `tasks.md`
> (эта папка) + глобальные `plans/project.md`, `plans/ARCHITECTURE.md` (§22–25).
> **Референс:** `relumesite_example/` — статический экспорт Relume (15 страниц).
> **Подтверждение:** полный разбор референса выполнен по фактическим исходникам
> (HTML/CSS/JS), см. §1–§2; готовность к полной переделке мини-аппа — подтверждена
> при условии решений §7.
> **v2-сноска:** §5.1 (варианты A/B/C) и §5.5 (P1/P2/P3) — история решения; итог — OD1(B)
> и OD4 (анимированные градиенты) из `design-project.md`.

---

## 0. Вывод-резюме (для владельца)

1. **Референс — это статический визуальный мокап, а не функциональное ТЗ.**
   Проверено инструментально: во ВСЕХ 15 `index.htm` — **0 `<input>`, 0 `<form>`,
   0 `<table>`, 0 `<select>`** (счётчики см. §1). «Тумблеры», «бюджеты», «матрица
   ролей», «KPI-плитки» референса — это стилизованные статические блоки
   (`<div>`/CSS-grid), а не рабочие контролы. Значит, задача — **визуальный +
   информационно-архитектурный редизайн** существующего функционала, а не перенос
   логики.
2. **Структура референса полностью восстановлена:** 15 страниц, плоский фиксированный
   navbar из 6 пунктов, 3 hub-страницы с карточками подразделов, по-страничный
   инвентарь секций/карточек — §1–§2.
3. **Существующий мини-апп уже покрывает ~90% функционала референса** (см. §4):
   18 вкладок в 5 меню-секциях (`web/app.js`, `web/index.html`). Основные расхождения —
   (а) **навигационная модель** (SPA-сайдбар vs navbar + hub-карточки + отдельные
   экраны), (б) **визуальный слой** (сейчас — фиолетовый градиент + glass, в референсе —
   токен-система Inter + Material Symbols, тил/тьма `#14CBB6`/`#161616`), (в) несколько
   «экранных» сущностей, которые в аппе размазаны (Матрица ролей, Локальные админы,
   Кастомные модули).
4. **Бэкенд почти не требует изменений** (§6): все данные для 15 экранов уже есть в
   `web/api/routes.py`, `web/api/access.py`, `web/api/chat_lore.py`, `web/api/gates.py`,
   `web/api/oversight.py`, `web/api/memory_agi.py` + `services/status_service.py`.
   Изменения нужны только для 3 необязательных фич (исторический график доступности
   ключей, CRUD кастомных модулей, read-only матрица ролей для не-глобалов).
5. **Блокер только один:** выбор варианта подхода и палитры владельцем (§7, T-1076).
   После апрува — секция E `tasks.md` наполняется задачами, @Builder стартует.

---

## 1. Глубокий анализ референса

### 1.1. Что именно изучено (цитируются фактические файлы)

| Артефакт | Что извлечено |
|---|---|
| `relumesite_example/index.htm` … 15×`index.htm` | секции, заголовки, tagline, навигация |
| `relumesite_example/index.238f2711.css` (115 КБ) | токены `:root`, схемы `.scheme-1..4`, типографика, радиусы, тени, брейкпоинты |
| `relumesite_example/ai/index.669b0eec.css`, `.../page-1/index.097018d2.css` и др. | per-section CSS |
| `relumesite_example/index.8433654a.js` (18 КБ) | рантайм Relume (не функциональная логика бота) |
| `relumesite_example/op-sdk/bootstrap.js` | Relume-аналитика (`analytics-events.relume.io`), не Telegram |
| `relumesite_example/webcopy-origin.txt` | манифест скачивания (список URL), не контент |

> **Важно:** `reference-analysis.md` (артефакт @PM) сравнивался с первоисточником;
> расхождения зафиксированы в §1.6. Разбор глубже, чем в `reference-analysis.md`.

### 1.2. Полный инвентарь страниц и навигационная иерархия

Навигация — **плоский фиксированный top-navbar** (лого слева, меню справа),
`scrollBehaviour:"Fixed"`, `menuAlignment:"Right"`. Вложенности/dropdown'ов в
навигации НЕТ (проверено: 6× `navLabel`, 0 `dropdown`/`navChildren`). Вместо вложенности —
**hub-страницы** с сеткой карточек подразделов.

Top-level navbar (одинаков на всех 15 страницах):

| # | Label | URL | Роль |
|---|-------|-----|------|
| 1 | Статус | `/` | Dashboard |
| 2 | Как это работает | `/page` | Инфо |
| 3 | Модули | `/page-1` | Hub модулей |
| 4 | Настройки AI | `/ai` | Hub настроек AI |
| 5 | Функции PERMsoc | `/permsoc` | Модули PERMsoc |
| 6 | Доступы и Роли | `/page-20` | Hub доступов |

Иерархия (navbar → hub → подстраница):

```
/                     Статус сервера и бота         [7 секций]
/page                 Как это работает
/page-1               Модули (hub)                 [12 карточек]
  /page-1/page-2        Кастомные модули
/ai                   Настройки AI (hub)           [8 карточек]
  /ai/llm               LLM Провайдеры
  /ai/page-13           Промпты
  /ai/page-14           Лимиты
  /ai/page-15           Память
  /ai/page-16           Сон и Ностальгия
/permsoc              Функции PERMsoc              [7 карточек]
/page-20              Доступы и Роли (hub)         [3 карточки]
  /page-20/page-21      Матрица ролей
  /page-20/page-22      Локальные админы чата
/page-23              Управление администраторами
```

> Секционные id страниц (`data-sid`): на подстраницах `ai/*`, `page-20/page-21..23`,
> `page-1/page-2` — единый шаблон `[1 (navbar), g (hero-card), m (hub/контент), <uuid>]`.
> Hub-страницы (`ai`, `page-1`, `page-20`, `permsoc`) и главная — с расширенным `main`
> (3–5 секций).

### 1.3. По-страничный инвентарь секций и параметров

Формат: **H1/H2 → карточки (H4) → описание**. Все элементы — статические; «контролы»
(reference) указаны как *декларируемые*, но физически не реализованы.

**`/` — Статус сервера и бота** (7 секций)
- Hero (scheme-4): tagline «Панель управления», H1, описание, secondary-кнопка
  «Как это работает».
- «Управление ботом» (scheme-3, grid-3): карточки **Рестарт / Стоп / Старт**
  (icon `restart_alt`/`stop_circle`/`play_circle`).
- «Метрики здоровья» (grid-3, divider): KPI-плитки **Аптайм 99.9% · Состояние Онлайн ·
  Ошибки со старта 0 · CPU 42% · RAM 68% · Диск 54%**.
- «Графики» (grid-card-2): 2 плейсхолдера — **График аптайма**, **Доступность ключей API**.
- «Панель логов» (scheme-4, tagline «Фильтр: ERROR + WARNING»): 5 строк с бейджами
  ERROR/WARNING/INFO и временем; «строки можно копировать».
- Footer (scheme-4, групповое меню разделов).

**`/ai` — Настройки AI (hub)**
- H2 «Разделы настроек»: карточки **LLM Провайдеры** (`cloud`, «Ключи и модели»),
  **Промпты** (`description`), **Лимиты** (`speed`), **Память** (`memory`),
  **Сон и Ностальгия** (`bedtime`), **Имена** (`badge`), **Участники и отношения**
  (`group`), **Лор чата** (`auto_stories`).

**`/ai/llm` — LLM Провайдеры** — «Провайдеры»: **Основной провайдер**
(«OpenAI / Anthropic / Groq»), **Ключи API** («Ключи и их доступность»), **Фолбэк**
(«Запасной провайдер при сбое»).

**`/ai/page-13` — Промпты** — «Системные промпты»: **Основной промпт**
(«Личность и поведение»), **Промпты модулей** («Отдельные промпты для функций»),
**Лор и тон** («Лор чата и стиль общения»).

**`/ai/page-14` — Лимиты** — «Лимиты и кулдауны»: **Лимиты токенов**, **Кулдауны**,
**Бюджеты** («Лимит расходов и температура»).

**`/ai/page-15` — Память** — «Память и граф знаний»: **Память**, **Граф знаний**,
**Хранение** (README упоминает «Пам» — опечатка экспорта).

**`/ai/page-16` — Сон и Ностальгия** — «Режим сна и ностальгия»: **Режим сна**,
**Ностальгия**, **Расписание**.

**`/permsoc` — Функции PERMsoc** — «Модули PERMsoc» (7 карточек): **Имитация
общения** (Славик), **Реплики** (Леха), **Реплики** (Костик), **Модуль Оли** (Оля),
**Режим тревоги** (War-алерты), **Мёртвая страница** (Dead page), **Утренняя
рассылка** (Рассылка), **Мимикрия** (Имитация стиля). Описание: «захардкоженные
функции для чата… по умолчанию включены для -1002661910336».

**`/page-1` — Модули (hub)** — «Модули бота» (12 карточек): **Саммаризация,
Прямые ответы, Фактчек, Поиск, Транскрипт голосовых, Выжимка видео, Скачивание
медиа, Веб-страницы, Диагностика, Умный кэш, Кастомные модули**.

**`/page-1/page-2` — Кастомные модули** — «Параметры и лимиты»: **Включён**
(`toggle_on`), **Бюджет** (`account_balance_wallet`), **Триггеры** (`extension`).

**`/page-20` — Доступы и Роли (hub)** — «Разделы доступа»: **Администраторы**
(`admin_panel_settings`), **Матрица ролей** (`grid_view`), **Локальные админы**
(`supervisor_account`).

**`/page-20/page-21` — Матрица ролей** — «Роли и права»: категории
**Провайдеры LLM** («Суперадмин: чтение/запись · Локальный админ: чтение/запись»),
**Ключи API** («…остальные: скрыто»), **Промпты** («…Модератор: скрыто»),
**Лимиты**, **Память** («Локальный админ: чтение»), **Имена».

**`/page-20/page-22` — Локальные админы чата** — tagline-селектор
«Чат: -1002661910336 ▾», список **Оля / Славик / Костик** (Имя + «ID … · роль»),
кнопка **«Добавить админа»**.

**`/page-23` — Управление администраторами** — «Администраторы»: **Суперадмины**
(«Полный доступ»), **Модераторы** («Всё кроме промптов и ключей»), **Пользователи**
(«Только чтение»), кнопка **«Добавить роль»**.

**`/page` — Как это работает** — H1 + 3 абзаца (описание функций бота, настроек,
ролей) + примечание «редактируется суперюзером, остальным — чтение».

### 1.4. Дизайн-токены (точные значения из `index.238f2711.css`)

**Шрифты/иконки**
- `--font-family-heading` / `--font-family-body` = **Inter** (400/500/600;
  подключён через `css2?family=Inter:wght@400|500|600`).
- Иконки: **Material Symbols Outlined/Rounded/Sharp** (`--icon-font-family`,
  `--icons-style-default: rounded`, `--icon-weight: 400`).

**Типографика** (rem, `line-height`, letter-spacing)
| Токен | Значение |
|---|---|
| `--heading-h1-size` / `-line-height` | `3.5rem` / `1.2` |
| `--heading-h2-size` | `3rem` |
| `--heading-h3-size` | `2.5rem` |
| `--heading-h4-size` / `-lh` | `2rem` / `1.3` |
| `--heading-h5-size` | `1.5rem` |
| `--heading-h6-size` | `1.25rem` |
| `--heading-weight` / `-letter-spacing` | `600` / `-.03em` |
| `--text-large-size` | `1.25rem` |
| `--text-medium-size` | `1.125rem` |
| `--text-regular-size` / `-lh` | `1rem` / `1.5` |
| `--text-small-size` | `.875rem` |
| `--text-tiny-size` | `.75rem` |
| `--body-max-width` | `35rem` |
| `--heading-max-width` | `48rem` |

**Палитра — 4 схемы** (`.scheme-1..4`, значения из `:root` override)
| Схема | Background | Background-secondary | Heading/Text | Accent | Применение в референсе |
|---|---|---|---|---|---|
| scheme-1 | `#12B7A4` (teal) | `#14CBB6` | `#F5F5F5` | `#291F40` | карточки/вложенные секции |
| scheme-2 | `#161616` | `#262626` | `#ffffff` | `#A78DE4` | тёмная (button-fill `#14CBB6`) |
| scheme-3 | `#A91443` (магента) | `#C25879` | `#F5F5F5` | `#F5F5F5` | контент-секции |
| scheme-4 | `#664EA0` (пурпур) | `#8D6BDC` | `#ffffff` | `#D9CDF3` | navbar + hero + footer |

Базовая шкала нейтралей: `50 #F5F5F5 · 100 #E7E7E7 · 200 #D4D4D4 · 300 #BABABA ·
400 #9E9E9E · 500 #808080 · 600 #616161 · 700 #424242 · 800 #262626 · 900 #121212`
(сайт-override: `900 #161616`, `950 #070707`).
Системные: green `#16B364` (+50…950), red `#FF4848` (+50…950),
yellow `#EAAA08` (+50…950). Прозрачности: `--color-white-a5..a90`, `--color-dark-a5..a90`.

> **Акцент `#14CBB6`** встречается 7 раз в основном CSS и является
> `--scheme1-background-secondary` и `--button-fill` у scheme-2 (тёмной). Утверждение
> @PM «scheme-4, accent #14CBB6» неточно: scheme-4 — это пурпур `#664EA0`/`#8D6BDC`,
> а `#14CBB6` — «фирменный» тил на тёмной/teal-схемах. См. §7 (решение по палитре).

**Радиусы / границы / тени**
- `--radius-small: 2px`, `--radius-medium/large: 4px`; компонентные:
  `--borderRadius-sm: 4px`, `-md: 8px`, `-lg: 12px`, `-full: 9999px`.
- `--border-width: 1px`, `--divider-width: 1px`.
- Кнопки: `--button-radius: var(--radius-small)`; padding `1.25rem × .75rem`
  (small: `1rem × .5rem`); `--button-weight: 500`.
- Тени: `sm 0 1px 2px rgba(0,0,0,.05)` · `md 0 4px 6px -1px rgba(0,0,0,.07)…` ·
  `lg 0 10px 25px -3px rgba(0,0,0,.08)…` · `xl 0 20px 50px -12px rgba(0,0,0,.12)`.

**Spacing-шкала**: `--spacing-0 .0 → --spacing-4-5 1.125rem → --spacing-5 1.25rem →
--spacing-6 1.5rem → --spacing-8 2rem → --spacing-10 2.5rem → --spacing-12 3rem →
--spacing-16 4rem → --spacing-20 5rem → --spacing-28 7rem`.
Секции: `--section-padding-large 7rem`, `-medium 5rem`, `-small 3.5rem`;
`--page-padding 2.5rem`; `--gap-section-content 5rem`.

**Анимации**: `--duration-fast .15s / -normal .3s / -slow .5s / -slower .8s`;
`--easing-easeOut cubic-bezier(0,0,.2,1)` и др.; поддержан `prefers-reduced-motion`
(есть в CSS референса).

**Инпуты/контролы (только как стиль)**: `--input-radius: var(--radius-small)`,
`--input-border: var(--scheme-border)`, `--input-padding-horizontal: .75rem`,
`--input-fill`, `--input-check-glyph` (SVG-галка), `--input-select-glyph` (SVG-шеврон).
`--navbar-height: 4.5rem`, `--zIndex-dropdown 100 / sticky 200 / modal 300 / tooltip 400`.

### 1.5. Компонентные паттерны и адаптив

- **Fixed navbar** (лого слева, меню справа, 6 пунктов) + **hub-grid карточек**
  (`grid-column-3`/`grid-column-card-2`) + секционный header (`tagline` + H2 + описание).
- **KPI-плитка** (`stat-highlight`): крупное значение H2 + подпись H6.
- **Карточка-строка/блок**: `icon-wrapper` (Material Symbol в `icon-medium
  icon-color`) + H4 + описание.
- **Панель логов**: строки с бейджем уровня, временем, текстом; копирование.
- **Графики**: 2 плейсхолдера-изображения (`data:image/svg+xml`).
- **Матрица ролей**: текстовые строки «роль: чтение/запись/скрыто» (НЕ `<table>`).
- **Селектор чата** на `/page-20/page-22`: tagline «Чат: -1002661910336 ▾».
- **Адаптив**: Relume-стандарт — `@media (max-width:991px)` (планшет),
  `@media (max-width:479px)` (телефон-портрет). Сетки 3→1, карточки в столбец.

### 1.6. Telegram WebApp-интеграция в референсе

**Отсутствует.** `telegram-web-app.js`/`window.Telegram`/`themeParams`/`initData`
в референсе НЕ используются (единственный внешний скрипт — Relume-аналитика
`op-sdk/bootstrap.js`). Это чистый статический сайт. Вывод: адаптация под Telegram
themeParams — **наша** инженерная задача, а не требование референса (§7).

### 1.7. Корректировки к `reference-analysis.md` (@PM)

| Утверждение @PM | Факт |
|---|---|
| «Референс многостраничный (15 роутов)» | подтверждено |
| «navbar = scheme-4; accent `#14CBB6`» | scheme-4 = `#664EA0`, accent `#D9CDF3`; `#14CBB6` — teal (scheme-1 secondary / scheme-2 button) |
| «Toggle-степперы, бейджи, маскировка ключей» как паттерны | физически 0 `<input>`/`<select>`; это статические `<div>`-мокапы |
| «Настройки AI (хаб) = 5 секций» | в референсе хаб **8 карточек** (вкл. Имена, Участники и отношения, Лор чата) |
| «Кастомные модули — часть modules_feats/reactions_triggers» | отдельная страница `/page-1/page-2` с бюджетом/триггерами; в аппе такой сущности нет |

---

## 2. Текущее состояние мини-аппа (фактическое, по коду)

Стек: **Vue 3 global build (CDN), zero-build**, Tailwind CDN + инлайн-CSS,
`web/index.html` (2400 строк) + `web/app.js` (3135 строк); `node --check web/app.js`.
Тема: фиолетово-синий градиент, glass-карточки (`--accent-grad #8b5cf6→#3b82f6`).

**Навигация** (`web/app.js:18–156`):
- `MENU_ORDER = ['home','chat_profile','modules','ai','access']` —
  Главная / Чат-Профиль / Модули / Настройки AI / Доступы и Роли.
- `TABS` — **18 вкладок**:
  - `home`: `status`(always), `info`(always), `oversight`;
  - `chat_profile`: `chat_lore`, `people_names`, `relations`;
  - `modules`: `reactions_triggers`, `modules_switches`, `modules_feats`, `permsoc`;
  - `ai`: `llm_providers`, `prompts`, `limits`, `memory_rag`, `memory_dream`, `memory_nostalgia`;
  - `access`: `access`.
- Рендер: левый sidebar (mobile — drawer, z-index 45), хедер со **единым** селектором
  чата (`X-Chat-Id`), контент — generic-шаблон `groupedForTab()` для config-вкладок
  (`web/index.html:561–789`) + кастом-шаблоны `relations`/`chat_lore`/`status`/`info`/
  `oversight`/`access`/`modules_feats`.

**Каталог параметров** (`services/param_catalog.py`): `TAB_RULES` + `CONFIG_TAB_TITLES`
+ `_TAB_BY_GROUP`; REGISTRY **383 записи / 74 группы / 359 Settings-полей** (эталон
`test_param_catalog`, MED-017). Вкладки — **зеркало** `TAB_RULES` (`test_frontend_tab_mapping.py`).
Любое изменение IA обязано сохранить это соответствие.

**Что уже реализовано на вкладке `status`** (`web/index.html:1886–2017`): карточка
Бот (аптайм/состояние/режим/версия/ошибки + Рестарт/Стоп/Старт с debounce), карточка
Сервер (CPU/RAM/Диск прогресс-бары, load, PID/RSS/threads), карточки LLM (key configured/
last4, latency, health), **график аптайма** (canvas, 24ч/5-мин бакеты), **панель логов**
(уровни ALL..CRITICAL, копирование строки по клику, раскрытие стека, бейджи ERROR/WARN).

**API-слой** (фактическая директория `web/api/`, проверено `ls`):
`routes.py`, `access.py`, `chat_lore.py`, `gates.py`, `oversight.py`, `memory_agi.py`,
`avatars.py`, `deps.py`, `__init__.py`.
> ⚠️ `plans/reports/global_map.md` и `audit_backlog.md` перечисляют несуществующие
> модули (`admins.py`, `config.py`, `roles.py`, `params.py`, `permissions.py`, `keys.py`,
> `usage.py`, `status.py`, `logs.py`, `direct_chat.py`, `relations.py`, `workers.py`,
> `system.py`). **Не доверять этим именам — эндпоинты консолидированы в `routes.py`.**
> Это прямое исполнение требования «do NOT assume endpoints exist — verify».

Полный перечень фактических эндпоинтов (по `@*_router.get/post/put/delete`):

| Группа | Эндпоинты |
|---|---|
| System/me | `GET /api/health`, `GET /api/me` |
| Config | `GET/POST /api/config`, `GET /api/config/params-meta`, `GET/PUT/DELETE /api/config/keys/own`, `GET /api/config/keys/status`, `DELETE /api/config/chat/{key}` |
| Admins/Roles | `GET/POST /api/admins`, `POST /api/admins/remove`, `GET/POST /api/roles`, `GET /api/roles/tree` |
| Info | `GET/POST /api/info` |
| Status/Control | `GET /api/status`, `GET /api/status/logs`, `POST /api/control/restart|stop|start`, `GET /api/debug/config` |
| Access | `GET /api/access/me`, `GET /api/access/chats`, `POST/DELETE /api/access/chats/{id}/admins[/{tg}]`, `GET/PUT/DELETE /api/access/param_permissions[/{key}]`, `POST /api/access/chats/{id}/param_permissions/{key}` |
| Chat Lore | `GET/POST/DELETE /api/chat_lore/admins`, `GET /api/chat_lore/chats`, `GET/PUT /api/chat_lore/{chat_id}`, `PUT …/settings`, `POST …/generate|clear_auto|remap`, `GET …/history`, `GET/PUT/DELETE …/relations[/{user_id}]`, `PUT …/relations_enabled` |
| Gates/Budget | `GET/PUT /api/chat/{chat_id}/gates`, `GET /api/workers/budget` |
| Oversight | `GET /api/oversight/summary`, `GET /api/oversight/chat/{chat_id}`, `POST …/killswitch`, `POST …/global_key` |
| Memory AGI | `POST /api/memory/dream/run`, `POST /api/memory/dream`, `GET /api/memory/dream/beliefs`, `GET /api/memory/dream`, `DELETE …/beliefs/{id}`, `POST …/beliefs/{id}/protect`, `GET /api/memory/dream/log`, `GET /api/memory/nostalgia/log` |
| Avatars | `GET /api/avatar/{kind}/{tid}` |

---

## 3. Информационная архитектура: референс vs апп

### 3.1. Соответствие верхнего уровня

| Референс (navbar) | Текущий апп | Комментарий |
|---|---|---|
| Статус | `home` → `status` | совпадает |
| Как это работает | `home` → `info` | совпадает |
| Модули | `modules` | апп детальнее (4 вкладки) |
| Настройки AI | `ai` | в референсе хаб включает и чат-профиль-настройки |
| Функции PERMsoc | `modules` → `permsoc` | в аппе внутри «Модули» |
| Доступы и Роли | `access` + `chat_profile` | разнесено |
| — (нет в референсе) | `home` → `oversight`; `chat_profile` | апп шире референса |

**Ключевое IA-расхождение:** референс складывает «Имена / Участники и отношения /
Лор чата» в хаб «Настройки AI», а «Функции PERMsoc» — в отдельный navbar-пункт.
Апп имеет отдельную секцию «Чат-Профиль» и держит PERMsoc внутри «Модули».

### 3.2. Целевая IA (рекомендация, при варианте C — §7)

```
Главная            ✔ Статус (Dashboard) · ✔ Как это работает · ✔ Oversight
Настройки AI       Hub-карточки:
                     ✔ LLM Провайдеры   ✔ Промпты   ✔ Лимиты   ✔ Память
                     ✔ Сон и Ностальгия
                     ✔ Имена (people_names) · ✔ Участники и отношения (relations)
                     ✔ Лор чата (chat_lore)
Модули             Hub-карточки:
                     ✔ Реакции и Триггеры · ✔ Модули (вкл/выкл)
                     ✔ Модули (карточки/кастомные) · ✔ Функции PERMsoc
Доступы и Роли     Hub-карточки:
                     ✔ Матрица ролей · ✔ Локальные админы · ✔ Администраторы
```
(«✔» = компонент/вкладка уже существует; меняется только точка входа и визуал.)

Открытый IA-вопрос: оставить ли отдельную секцию «Чат-Профиль» (текущий канон,
меньше тестовых рисков) или свернуть её в «Настройки AI» как в референсе
(больше соответствия, но правка `MENU_ORDER`/`MENU_LABELS` + маркер-тестов). См. §7.

---

## 4. Gap-анализ (двусторонний)

### 4.1. Референс → апп (маппинг и статус)

| Экран референса | Текущий tab / группа параметров | Статус |
|---|---|---|
| Dashboard «Статус сервера и бота» | `status` | **Существует** (полный) |
| — аналитика аптайма %, KPI-плитки | `status.uptime.buckets` | **Partial** (можно вывести % фронтом, плиток нет) |
| — график доступности ключей | `status.llm[].health` | **Missing** (нет истории) → §6 B1 |
| Управление ботом (Рестарт/Стоп/Старт) | `status` + `/api/control/*` | **Существует** |
| Панель логов | `status` + `/api/status/logs` | **Существует** |
| AI hub «Разделы настроек» | `ai` секция | **Partial** (нет единого hub-экрана) |
| LLM Провайдеры | `llm_providers` (4 секции) | **Существует** |
| Промпты | `prompts` | **Существует** |
| Лимиты | `limits` | **Существует** |
| Память / Граф знаний / Хранение | `memory_rag` (+ `relations`) | **Существует/Partial** |
| Сон и Ностальгия | `memory_dream`, `memory_nostalgia` | **Существует** (в референсе одна страница) |
| Имена | `people_names` | **Существует** |
| Участники и отношения | `relations` | **Существует** |
| Лор чата | `chat_lore` | **Существует** |
| Модули (12 карточек) | `modules_feats` (6 карточек-хинтов) | **Partial** |
| Кастомные модули | — (нет сущности) | **Missing** → §6 B2 |
| Функции PERMsoc (7) | `permsoc` (17 групп) | **Существует** |
| Доступы и Роли (hub) | `access` | **Partial** (нет hub-экрана) |
| Матрица ролей | role-editor modal (`/api/roles/tree`) + per-key `param_permissions` picker | **Partial** (нет автономного read-view) |
| Локальные админы чата | блок в `chat_lore` + `access`; `/api/chat_lore/admins`, `/api/access/chats/{id}/admins` | **Существует** (разнесено по 2 вкладкам) |
| Управление администраторами | `access`: `/api/admins`, `/api/roles` | **Существует** |
| Как это работает | `info` | **Существует** |

### 4.2. Апп → референс (не потерять при редизайне!)

| Фича аппа | Где | Риск при редизайне |
|---|---|---|
| Oversight (сводка чатов) | `home` → `oversight` | нет аналога в референсе — НЕ удалять |
| DM-скоуп (ЛС) + BYOK | F-13/F-14 | референс не знает ЛС |
| Gates opt-in / worker budget | `modules_feats`, `/api/workers/budget` | нет в референсе |
| Per-chat overrides + optimistic 409 | config-вкладки | нет в референсе |
| Relations-таблица (аватары, стадии, note) | `relations` | нет в референсе |
| Role-tree конструктор + per-key perm picker | `access` | референс упрощает до текста |
| Control debounce, log copy/expand | `status` | сохранить |
| `prefers-reduced-motion`, safe-area insets, z-index-каскад | CSS | сохранить |
| Маркер-тесты: `test_frontend_tab_mapping`, `test_webapp_nav_disclosure_ui`, `test_webapp_rbac_ui`, `test_webapp_dm_ui`, `test_webapp_avatars_ui` | `tests/` | обновлять при новой IA (прецедент MED-022) |

### 4.3. Что чинить по итогам Scanner-аудитов (интеграция в дизайн)

| ID | Находка | Как учитывается в спеке |
|---|---|---|
| R10.4-2 | Смена чата не сбрасывала relations | **В рабочем дереве уже исправлено** (`web/app.js:748–759`); спека закрепляет как инвариант: смена `activeChatId` сбрасывает/перезагружает состояние всех chat-scoped экранов |
| R10.4-5 | «Перезагрузить» в 409-модалке на relations — no-op | требование §5.7: модалка 409 обязана перезагружать текущий экран |
| R10.4-4 | Фото тянутся для 100 участников вместо топ-50 | NFR §5.8: relations-экран — ленивый догруз аватаров (`loadRelationAvatarsLazy`) |
| R10.4-1 | Лог graphrag-обрезки показывает глобальный лимит | backend minor (не UI) — зафиксировано, вне скоупа редизайна |
| MED-021 | Error-boundary только частично (configError) | §5.6: унифицированные error/empty-states + «⟳ Повторить» на ВСЕХ экранах |
| MED-022 | Мало интеграционных/маркер-тестов | §6 T-1086/1087: обновление маркеров + полный pytest |
| LOW-012 | Нет CSP | §5.9: если добавляем внешние шрифты — CSP/`font-src` учесть |
| R10.3-1 | DM `models.*` редактируемы → 422 | сохранить read-only-семантику DM в новом UI |

---

## 5. Дизайн/архитектура редизайна

### 5.1. Модель навигации — 3 варианта (⏸ решение §7)

| | A. Reskin | B. Full-rebuild | C. Hybrid (рекомендация) |
|---|---|---|---|
| Суть | сохранить SPA+sidebar, перекрасить | 15 отдельных роутов, новый фреймворк/сборка | SPA без сборки + hash-роутинг + hub-экраны |
| Риск регресса | низкий | высокий | средний |
| Соответствие референсу | ~50% | ~100% | ~90% |
| Backend | 0 | 0 | 0 |
| Тесты | минимальные правки | много правок | средние правки маркеров |
| Deep-link/back в TMA | нет | да | да |
| Движок | Vue3 global | ??? | Vue3 global |

**Рекомендация @Architect:** вариант **C**. Обоснование: (1) референс — статический
мокап, портировать функционально нечего; (2) zero-build SPA — действующий канон
(`web/app.js`, `node --check`), фреймворк/сборка добавят инфраструктурный риск;
(3) hash-роутинг (~100 строк, без зависимостей) даёт наиболее ценный UX-прирост —
deep-link и кнопку «назад» внутри TMA; (4) hub-экраны для AI/Модулей/Доступов
повторяют референс, но строятся поверх существующих `TABS`.

Вариант **A** допустим как урезанный скоуп (только токены + рестайл), если владелец
хочет минимальный объём. Вариант **B** @Architect **не рекомендует**.

### 5.2. Архитектура варианта C (детально, если апрувнут)

- Один документ `web/index.html`; «роуты» — `location.hash` вида `#/ai/llm`,
  `#/access/roles`; `hashchange` → `setTab()` + при необходимости hub-экран.
  Дефолт `#/` → `status`. Совместимость: существующий `activeTab` сохраняется как
  источник истины; hash — только отражение/навигация (не ломает `canViewTab`).
- Shell: верхний **navbar** (desktop, ≥992px) + **drawer** (mobile, ≤991px), логотип
  слева, chat-selector/user-chip справа. Альтернативно (A) — сохранить текущий sidebar,
  но обязательно привести к токенам. Компонент переиспользует `telegram-web-app.js`
  (`headerColor`/`backgroundColor`/`BackButton`).
- **Hub-экран** = «раздел»: grid карточек; карточка = icon + title + subtitle + chevron;
  клик → соответствующий tab (или вложенный hub).
- Существующие config-вкладки (`groupedForTab`/`buildConfigSections`) не меняют
  контракт: те же `TABS`/`TAB_RULES`, тот же generic-рендер, только визуал.
- Кастомные вкладки (`status`, `info`, `relations`, `chat_lore`, `modules_feats`,
  `oversight`, `access`) переразмечаются в компоненты токен-системы без смены данных.

### 5.3. Компонентный инвентарь (целевой)

| Компонент | Назначение | Аналог сейчас |
|---|---|---|
| `AppShell` | navbar/drawer + контент | `aside.sidebar` + `header` |
| `Navbar` / `NavDrawer` | верхняя навигация / мобильный drawer | sidebar-группы |
| `BrandLogo` | лого+название+«Панель управления» | `AdminBot`+подпись |
| `ChatSelector` | единый выбор чата | `<select class="chat-select">` |
| `UserChip` | аватар+имя+роль+fullscreen | хедер-блок |
| `PageHeader` | tagline + H1/H2 + описание + secondary-кнопка | hero-карточки |
| `HubGrid` / `HubCard` | карточки подразделов | нет (плоские вкладки) |
| `StatTile` | KPI (значение+подпись) | нет (текст в `status`) |
| `Meter` | прогресс CPU/RAM/Диск | `.progress` |
| `SectionCard` | карточка-секция с заголовком | `.card` |
| `AccordionSection` | базовая/расширенная группа параметров | `<details>` + `sectionTitle` |
| `ParamRow` | label+описание+widget+save | generic-рендер |
| `Toggle` | bool | Tailwind switch |
| `SelectField` / `NumberField` / `TextField` / `Textarea` / `SecretField` | виджеты | `.field` |
| `Badge` | ON/OFF/configured/wildcard/ERROR… | `.badge` |
| `LogPanel` | логи с фильтром/копированием/раскрытием | `log-panel` |
| `Sparkline/Chart` | аптайм (canvas); key-availability — §6 B1 | canvas |
| `ModuleCard` | карточка модуля (icon/имя/описание/статус/ссылка) | `modules_feats` |
| `AdminList` / `RoleList` | списки админов/ролей + добавление | `access` |
| `RoleTreeEditor` | чекбокс-дерево прав роли | roleEditor-modal |
| `PermPicker` | view/edit роли для ключа | permPicker-modal |
| `RelationsTable` | участники/стадии/score/note | relations-шаблон |
| `ChatAdminList` | локальные админы | chat_admins-блок |
| `Modal` / `ConfirmModal` / `ConflictModal(409)` | модалки | `modal-backdrop` |
| `Toast`, `EmptyState`, `ErrorState(+retry)`, `Spinner` | состояния | частично есть |

### 5.4. Дизайн-токены для внедрения

Ввести CSS-слой custom properties в `web/index.html` (сегодня токен-слоя нет;
цвета — inline/Tailwind config `accent #8b5cf6`). Минимальный набор:

```
/* typescale */ --font-body/heading: Inter …; --text-xs..xl;
              --heading-h1..h6 (3.5/3/2.5/2/1.5/1.25rem, w600, ls -.03em);
/* radius */   --radius-sm 4px, --radius-md 8px, --radius-lg 12px, --radius-full 9999px;
/* spacing */  --space-0-5..--space-28; --page-padding; --section-padding-*;
/* shadows */  --shadow-sm/md/lg/xl;
/* motion */   --dur-fast .15s / -normal .3s / -slow .5s; --ease-out;
/* palette */  схема по решению §7 (P1/P2/P3);
/* status */   --ok #16B364, --warn #EAAA08, --err #FF4848 (+ фоны a10/a20);
```
Требование: **удалить** хардкод `#8b5cf6/#3b82f6/#2b2b40` и Tailwind-цвета
`card/accent/accent2`; всё — через токены.

### 5.5. Палитра/тема — 3 стратегии (⏸ решение §7)

- **P1 — 1:1 копия** схем референса (teal/magenta/purple/dark) — максимум сходства,
  плохой fit для Telegram, риск контраста.
- **P2 — Telegram themeParams** (`--tg-theme-*`) — нативно, но теряется айдентика.
- **P3 (рекомендация) — «Relume token system, Telegram-aware»**: токен-архитектура
  референса, но **одна** сдержанная схема: база — тёмная scheme-2 (`#161616`/
  `#262626`), акцент — тил `#14CBB6` (signature), служебные — green/red/yellow;
  опционально подхват `themeParams` только для `header`/`background`/`text`;
  `prefers-color-scheme` и `prefers-reduced-motion` учтены.

### 5.6. Состояния, доступность, отказоустойчивость

- Унифицировать empty/error/spinner (закрыть MED-021): баннер + «⟳ Повторить» +
  «✕», очистка при успехе/смене контекста; 401 → экран «сессия устарела».
- Сохранить z-index-каскад: sidebar 45 < modal 50 < toast 60 (backdrop 35).
- safe-area insets (`env(safe-area-inset-top/bottom)`), `prefers-reduced-motion`.
- Контраст WCAG AA для текста/бейджей (особенно на тил-акценте).

### 5.7. Инварианты (нельзя нарушать)

1. `TABS` ↔ `TAB_RULES` (`services/param_catalog.py`) синхронны; REGISTRY 383/74
   группы/359 Settings — без изменений (MED-017).
2. RBAC: `canViewTab`/`canEditConfig`/DM-ветки и серверные гейты — источник истины;
   UI не ослабляет проверки.
3. Смена `activeChatId` сбрасывает/перезагружает состояние всех chat-scoped экранов
   (R10.4-2 класс).
4. R17: ключи только в маске `{configured,last4}`; секреты не в DOM/логах.
5. Zero-build, `node --check web/app.js`; ноль новых PG-DDL; SQLite остаётся v8.
6. 409-модалка конфликта обязана реально перезагружать текущий экран (R10.4-5).
7. Relations-аватары — ленивый догруз (R10.4-4).

---

## 6. Влияние на бэкенд/API (верифицировано по коду)

### 6.1. Чисто фронтенд (новых эндпоинтов НЕ нужно)

Все 15 экранов, кроме перечисленного в §6.2: hub-карточки, токен-слой, navbar/sidebar,
hash-роутинг, KPI-плитки (аптайм % выводится из `GET /api/status.uptime.buckets`),
дашборд, config-вкладки (`GET/POST /api/config`, `GET /api/config/params-meta`),
keys/BYOK, prompts/limits/memory/dream/nostalgia/names/relations/lore, modules/permsoc,
access (admins/roles/roles-tree/param_permissions), local chat admins, info, oversight,
gates, worker budget.

### 6.2. Потенциально новые бэкенд-фичи (НЕ предполагать — только по решению)

> **⛔ SUPERSEDED v3 (OD8/OD9/OD10):** **B1 — В СКОУПЕ** (переработано, `design-project.md`
> §15.2); **B2 — OUT** (read-only сохраняется, §3.3); **B3 — В СКОУПЕ и расширен** (§15.3).
> Таблица ниже — исторический черновик рекомендаций v1/v2.

| ID | Фича | Что нужно | Оценка | Рекомендация @Architect |
|---|---|---|---|---|
| B1 | «График доступности ключей API» (история) | writer-сэмплер + storage + GET | высокая | **Defer** (в референсе — статический плейсхолдер; цена/ценность плохие) |
| B2 | «Кастомные модули» CRUD (Включён/Бюджет/Триггеры) | новая сущность + эндпоинты | высокая | **Defer**; представить как read-only карточку-навигацию в `modules_switches`/`permsoc`/`/api/workers/budget` |
| B3 | Read-only «Матрица ролей» для не-глобалов | либо role-scoped ответ, либо переиспользовать `GET /api/roles/tree?role_name=` | низкая | **Опционально** — при желании владельца |

> **Не трогать:** `services/param_catalog.py` REGISTRY, `config/settings.py` (359 полей),
> SQLite-схему (v8), PG-DDL, каноны промптов, порядок роутеров `bot.py`.

---

## 7. Риски, открытые вопросы, точки решения (⏸ требуют владельца)

| # | Решение | Варианты | Рекомендация | Блокирует |
|---|---|---|---|---|
| D1 | **Модель навигации** (T-1076) | A reskin / B full-rebuild / C hybrid | **C** | секцию E целиком |
| D2 | **Скоуп** | все экраны сразу / поэтапно (Статус→AI→…) | **поэтапно** (§8) | темп |
| D3 | **Технология** | vanilla Vue3 zero-build / фреймворк+сборка | **остаться на Vue3 global** | объём/инфра |
| D4 | **Палитра** | P1 1:1 / P2 themeParams / P3 гибрид | **P3** (`#14CBB6` на `#161616`) | весь визуал |
| D5 | **Иконки** | emoji (как сейчас) / Material Symbols (как референс) | **emoji now**, Material Symbols — follow-up | визуал/вес |
| D6 | **Чат-Профиль** | оставить отдельное меню / свернуть в «Настройки AI» (как референс) | на усмотрение владельца | `MENU_ORDER`/тесты |
| D7 | **B1/B2/B3** | делать / отложить | **отложить (B1/B2)**, B3 опц. | объём backend |
| D8 | **Единая точка входа** | hash-роутинг / без него | **с hash** (при C) | UX/nav |

**Риски:**
- R1. Регресс кросс-чатового состояния при реструктуризации (класс R10.4-2) — снижается §5.7 п.3.
- R2. Расхождение `TABS` ↔ `TAB_RULES` → падение `test_frontend_tab_mapping` и «пропажа» параметров — §5.7 п.1, обязательная сверка на каждом шаге.
- R3. Утяжеление TMA (внешние шрифты/иконки, CDN) → медленный старт WebView — D5, локальный subset/fallback.
- R4. Контраст/тёмная тема Telegram — D4, проверка WCAG AA.
- R5. Ломка маркер-тестов UI — план T-1087 (MED-022).
- R6. Неочевидная разница светлой/тёмной схемы Telegram — заранее решить P2/P3-фолбэк.

**Открытые вопросы** (дублируют `tasks.md` §«Открытые вопросы», уточнены):
1. D1–D8 выше.
2. Нужен ли реальный исторический график ключей (B1) или плейсхолдер как в референсе?
3. Нужны ли «Кастомные модули» как сущность (B2) или карточка-переход?
4. Должны ли не-глобальные роли видеть «свою» матрицу (B3)?
5. `media/` — политика подтверждена (не трогать, в `.gitignore` не добавлять).

---

## 8. План фаз (для секции E, после апрува D1)

| Фаза | Содержание | Задачи `tasks.md` |
|---|---|---|
| 0 | Решения D1–D8, финализация spec | T-1076/T-1077 |
| 1 | Токен-слой + shell (navbar/drawer, hash-роутинг) | T-1078/T-1079 |
| 2 | Dashboard (метрики/плитки/график/логи/контроль) | T-1080 |
| 3 | AI hub + 5 подстраниц (+ Имена/Отношения/Лор) | T-1081 |
| 4 | Модули + Кастомные (read-only) | T-1082 |
| 5 | Функции PERMsoc | T-1083 |
| 6 | Доступы: hub + Матрица + Локальные админы + Администраторы | T-1084 |
| 7 | Info + полировка (motion/empty/a11y) | T-1085 |
| 8 | QA: node --check, сверка TABS↔TAB_RULES, маркеры, pytest, live-верификация | T-1086…T-1089 |

Строгое требование к каждой фазе: `node --check web/app.js`; `TABS` ↔ `TAB_RULES`
не разошлись; REGISTRY/GROUPS/Settings без изменений; полный pytest без регрессий
(база **4860 passed / 0 failed**); `git diff --check` чист.

---

## 9. Критерии приёмки (Acceptance Criteria)

- **AC-1 (Токены).** В `web/index.html` введён токен-слой (`--scheme-*`, spacing,
  radius, shadow, typography, motion, status-цвета), соответствующий значениям §1.4;
  хардкод `#8b5cf6/#3b82f6/#2b2b40` и Tailwind `card/accent/accent2` удалён; шрифт Inter.
- **AC-2 (Навигация).** Доступны все 5 секций и hub-экраны AI/Модули/Доступы; каждая
  существующая вкладка достижима; `canViewTab`/DM-гейты сохранены; при D1=C — hash
  deep-link + back/forward; дефолт `#/` → `status`.
- **AC-3 (Паритет функционала).** Каждая текущая вкладка/группа параметров
  функциональна; `TABS` ↔ `TAB_RULES` синхронны; REGISTRY **383 / 74 группы /
  359 Settings** без изменений (`test_param_catalog` зелёный).
- **AC-4 (Dashboard).** Бот/Сервер/LLM/аптайм-график/логи/контроль на месте; KPI-плитки;
  адаптив ≤991px и ≤479px (сетки схлопываются в столбец).
- **AC-5 (Регресс).** `node --check web/app.js` clean; полный pytest без регрессий
  (0 failed); обновлены маркер-тесты `test_frontend_tab_mapping.py`,
  `test_webapp_nav_disclosure_ui.py`, `test_webapp_rbac_ui`/`test_webapp_dm_ui`/
  `test_webapp_avatars_ui`; `git diff --check` чист.
- **AC-6 (TMA).** `themeParams`/`prefers-color-scheme`/`prefers-reduced-motion` учтены;
  safe-area insets; z-index-каскад сохранён; контраст ≥ WCAG AA.
- **AC-7 (Безопасность/скоуп).** Ноль новых PG-DDL; SQLite остаётся v8; R17-маскировка
  ключей; DM-изоляция и BYOK-контракты неизменны; `media/` не тронут.
- **AC-8 (Состояния).** Empty/error/spinner унифицированы; «⟳ Повторить»/«✕» на всех
  экранах (закрытие MED-021); 409-модалка реально перезагружает текущий экран (R10.4-5).
- **AC-9 (Живая верификация).** Владелец подтвердил визуальную сверку с референсом в
  Telegram (десктоп + Android) — T-1089.

---

## 10. Подтверждение готовности

Полное понимание референса достигнуто по фактическим исходникам (HTML/CSS/JS), а не по
заголовкам: инвентарь 15 страниц, иерархия навигации, по-страничные секции/карточки,
точные дизайн-токены, компонентные паттерны, адаптив и вывод об отсутствии
Telegram-интеграции в референсе. **@Architect готов к полной переделке мини-аппа**
при наличии апрува решений §7 (D1–D8). Пока D1 не выбран — реализация (секция E
`tasks.md`) заблокирована; `spec.md` под выбранный вариант финализируется в T-1077.

---

## 11. Источники (процитированные пути)

- Референс: `relumesite_example/index.htm`, `ai/index.htm`, `ai/llm/index.htm`,
  `ai/page-13..16/index.htm`, `permsoc/index.htm`, `page-1/index.htm`,
  `page-1/page-2/index.htm`, `page/index.htm`, `page-20/index.htm`,
  `page-20/page-21|22/index.htm`, `page-23/index.htm`,
  `index.238f2711.css`, `ai/index.669b0eec.css`, `op-sdk/bootstrap.js`.
- Планы: `plans/project.md`, `plans/ARCHITECTURE.md` (§22–25),
  `plans/features/tma-relume-redesign/reference-analysis.md`,
  `plans/features/tma-relume-redesign/tasks.md`.
- Отчёты Scanner: `plans/reports/full_audit_results.md` (Round 10.3/10.4),
  `plans/reports/global_map.md`, `plans/reports/audit_backlog.md`,
  `plans/reports/round10.4_review_fixes.md`.
- Код: `web/index.html`, `web/app.js`, `web/api/routes.py`, `web/api/access.py`,
  `web/api/chat_lore.py`, `web/api/gates.py`, `web/api/oversight.py`,
  `web/api/memory_agi.py`, `web/api/avatars.py`, `web/app.py`,
  `services/param_catalog.py`, `services/status_service.py`.
