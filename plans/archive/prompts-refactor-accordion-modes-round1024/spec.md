# Spec: prompts-refactor-accordion-modes-round1024 (F6)

> Раунд 10.24 (UPD2 п.4 + UPD3 №2) · P1 · каталог + UI/web + fallback-контракт · Владелец: F6
> Ступень `param_catalog.py`: **F7 (Part 1, влит) → F5 → F6**
> Ступень `web/**`: **3-я** (F3 → F5 → **F6** → F11 → F4 → F10)
> **ADR:** ADR-1024-10 (AMEND ADR-1023-8)
> **⚠️ UPD3 №2:** дропдаун **НЕ удаляем** → «Резервный режим (Fallback)», дефолт
> **`casual`**, строгий предохранитель (не влияет на штатный выбор режима).

## 1. Цель

Убрать хаос на вкладке «Промпты»:
1. **Убить аккордеоны** («Расширенные системные [N]»): если внутри секции один
   `textarea` — он должен быть виден сразу.
2. **Дропдаун сохранить** как предохранитель: переименовать в **«Резервный режим
   (Fallback)»**, дефолт **`casual`**; применяется **только при сбое** (LLM зависла /
   нечитаемый ответ), а не для штатного выбора.
3. **Табы режимов** (`Casual`/`Serious`/`Deep Research`) перенести **внутрь карточек
   конкретных модулей** (Прямой чат, Поиск, Веб-страницы и др.) — прямо над полем
   Вербализатора.

## 2. Что уже есть (координаты)

| Что | Где |
|---|---|
| Вкладка «Промпты»: секции stage, аккордеон `<details class="advanced">` | `web/index.html:377-531` (аккордеон `:499-525`) |
| Отдельная группа режимов с табами + дропдаун | `web/index.html:432-467` (`grp.id === 'prompts_verbilizer'`) |
| `promptSections(grp)` (basic/advanced split) | `web/app.js:3794-3847` |
| `promptModeTabs`, `promptModeItem`, `promptDefaultModeItem`, `selectPromptMode`, `_syncPromptModeFromConfig` | `web/app.js:1185-1192, 3855-3889` |
| CSS `details.advanced` (используется и в `llm_providers`) | `web/static/app.css:991-1025` |
| Ключи режимов/дефолта (group `prompts_verbilizer`) | `services/param_catalog.py:458-473`; select-preset `:1868-1873` |
| `VERBILIZER_DEFAULT_MODE = "serious"` + `_resolve_default_mode` | `services/prompt_style_blocks.py:157-187, 231-249` |
| Одностадийные модули (verbalizer-only): Поиск/YouTube/Веб | `prompts_search`/`prompts_youtube`/`prompts_web` |
| Пин-тесты | `tests/test_ui_verbilizer_tabs_round1023.py` (`:122-192`), `tests/js/round1023_verbilizer_tabs_test.js` |

> Замечание: ключ `prompts.verbilizer_default_mode` **сохраняется** — Δ каталога F6 = **0**.

## 3. Требуемое поведение

### 3.1. Убрать аккордеоны (только на «Промптах»)

- В шаблоне карточек модулей (`index.html:469-528`) рендерить `sec.basic` и
  `sec.advanced` **в одном общем grid** без `<details>`/`<summary>`.
- `promptSections()` может возвращать плоский список `items` (или оставить
  `basic/advanced`, но шаблон рисует оба множества подряд). Пустые секции не рисуются.
- `details.advanced` **остаётся** для `llm_providers` (`index.html:532-542`) —
  не трогать его CSS/поведение.
- Порядок секций сохраняется: «Синтезатор (Логика)» → «Вербализатор (Характер)» →
  «Прочие промпты модуля».

### 3.2. «Резервный режим (Fallback)» (строгий предохранитель)

- **UI:** дропдаун остаётся, но подпись/заголовок = **«Резервный режим (Fallback)»**
  + пояснение: «Срабатывает только при сбое модели (зависла/нечитаемый ответ).
  Штатный выбор режима делает Синтезатор динамически».
- **Дефолт:** `casual`.
  - `services/prompt_style_blocks.py::VERBILIZER_DEFAULT_MODE = "casual"`.
  - `param_catalog.py` title_ru ключа → «Резервный режим (Fallback)»; `select_options`
    `("casual","serious","deep_research")` сохраняются.
  - `_syncPromptModeFromConfig()` при отсутствии/битом значении → **`casual`**
    (сейчас `serious`).
- **Контракт fallback (критично):**
  - Штатный путь: Stage-1 JSON отдаёт `response_mode ∈ {casual,serious,deep_research}`
    → `compose_verbalizer_system(base, response_mode)` использует **его**; ключ
    `prompts.verbilizer_default_mode` **не читается**.
  - Сбойный путь: `response_mode` отсутствует/пуст/невалиден → только тогда
    `candidate = _resolve_default_mode()` (значение ключа, дефолт `casual`).
  - Это ровно текущее поведение `prompt_style_blocks.py:242-244`; фиксируем его
    тестами как **инвариант**: валидный Stage-1 режим **никогда** не переопределяется
    fallback-ключом.
  - **Проводка (review iter1):** чтобы сбойный сигнал реально доходил до compose,
    `system2_handoff.normalize_response_mode()` для невалид/пусто возвращает `""`
    (а не коэрсит в `"serious"`); резолв ключа — в `compose_verbalizer_system`.
- `prompt_migrations`/канон: ключ и код-дефолт синхронизированы (атомарный коммит:
  код + эталон/миграция + тесты — ADR-1013-3).

### 3.3. Табы режимов внутри карточек модулей

- В карточке модуля, у которого есть элементы `stage === 'verbalizer'`
  (`prompts_direct_chat`, `prompts_factcheck`, `prompts_search`, `prompts_web`,
  `prompts_summary`, `prompts_youtube`), **над** полем(ями) Вербализатора рендерить:
  1) ряд табов `Casual | Serious | Deep Research` (существующий `promptModeTabs`);
  2) textarea редактирования выбранного режима (`prompts.verbilizer_mode_<mode>`);
- Клик по табу переключает **редактируемый режим** (`promptMode`) и сохраняет его как
  выбранный при необходимости (`selectPromptMode`). Семантика как в 10.23.
- Отдельную карточку группы `prompts_verbilizer` (`index.html:432-467`) **убрать из
  рендера** как самостоятельный набор табов; её ключи редактируются из карточек
  модулей. Сама группа в каталоге остаётся (Δ=0).
- **`«Резервный режим (Fallback)»` рендерится один раз** — компактной строкой в
  заголовке вкладки «Промпты» (не дублируется в каждой карточке), чтобы исключить
  противоречивое редактирование одного ключа из нескольких мест.
- Шаренный характер режимов сохраняется: правка `prompts.verbilizer_mode_*`
  влияет на все модули (режим — общий, а не per-module).
- Блок анти-клише (`data-block="anticliche-monitor"`) на вкладке не трогать.

### 3.4. Гейт

- `uiFlag('PROMPTS_UI_V2_ENABLED')`: ON → новая раскладка; OFF → прежние аккордеоны
  + отдельная карточка режимов (байт-в-байт 10.23).

## 4. Изменения по файлам

| Файл | Что |
|---|---|
| `web/index.html` | Убрать аккордеон (`:499-525`); табы+textarea режимов внутрь карточки модуля (над Вербализатором); дропдаун → «Резервный режим (Fallback)» один раз; гейт `uiFlag`. |
| `web/app.js` | `promptSections`/`promptMode*` под новую раскладку; `_syncPromptModeFromConfig` дефолт `casual`; `uiFlag`. |
| `services/prompt_style_blocks.py` | `VERBILIZER_DEFAULT_MODE = "casual"`; docstring fallback-контракта. |
| `services/param_catalog.py` | title_ru ключа → «Резервный режим (Fallback)» (Δ ключей = 0). |
| `config/settings.py` + `routes.me` | `PROMPTS_UI_V2_ENABLED` (enabler). |
| `tests/**` | §6. |

## 5. Контракты

- **Fallback-инвариант:** `compose_verbalizer_system(base, valid_mode)` не читает
  `prompts.verbilizer_default_mode`; ключ используется только при невалидном/пустом
  `response_mode`.
- **Каталог:** ключ `prompts.verbilizer_default_mode` существует, `widget=select`,
  `select_options=("casual","serious","deep_research")`; UI-подпись «Резервный режим
  (Fallback)»; код-дефолт `casual`.
- **UI:** одиночный `textarea` в секции → без аккордеона; табы режимов — внутри
  карточек с Вербализатором.
- **Fail-open:** нет данных/ошибка конфига → вкладка не ломается.

## 6. Тесты

- **Python (`tests/test_ui_verbilizer_tabs_round1023.py` — обновить + новый
  `test_prompts_round1024.py`):**
  - `VERBILIZER_DEFAULT_MODE == "casual"`; `get_by_pg_key(...).title_ru` содержит
    «Резервный режим (Fallback)»; `spec.select_options` не изменился;
  - `compose_verbalizer_system("BASE", "deep_research")` → deep-блок (заданный режим
    приоритетнее fallback-ключа);
  - `compose_verbalizer_system("BASE", "wat")` при кэше
    `{"prompts.verbilizer_default_mode": "casual"}` → casual-блок; при `"bogus"` →
    **casual** (код-дефолт), не serious;
  - прежний `test_default_mode_invalid_falls_back_serious` переписан на casual.
- **JS (`tests/js/round1024_prompts_ui_test.js`):**
  - `promptSections` не создаёт аккордеонов; одиночный item доступен сразу;
  - `_syncPromptModeFromConfig` при пустом/битом значении → `casual`;
  - табы режимов рендерятся в карточке с verbalizer;
  - `node --check web/app.js`.
- **Гейт:** `tests/js/vue_mount_test.js` зелёный; блок анти-клише не сломан.

## 7. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | Fallback незаметно перехватит штатный роутинг | High | контракт §5 + тесты «валидный режим приоритетнее» |
| R2 | Канон-атомарность (ADR-1013-3) | High | код + эталон/миграция + тесты одним коммитом |
| R3 | Перенос табов ломает `v-model`/сохранение | Medium | JS-тесты переключения/сохранения |
| R4 | Дублирование дропдауна в каждой карточке | Medium | рендер fallback-дропдауна **один раз** (§3.3) |
| R5 | Рассинхрон UI-подписи и тестов | Medium | обновить подпись и пин-тесты в том же коммите |

## 8. Критерии приёмки

- На «Промптах» нет бессмысленных свёрнутых списков при одиночном поле.
- Дропдаун присутствует как **«Резервный режим (Fallback)»**, дефолт **`casual`**.
- Fallback **не влияет** на штатный динамический выбор Синтезатора и срабатывает
  только на сбойном пути (доказано тестами).
- Табы режимов — внутри карточек соответствующих модулей, над полем Вербализатора.
- Δ каталога = 0; pytest/JS-гейт зелёные; анти-клише-монитор не сломан.

## 9. Флаг и откат

- `PROMPTS_UI_V2_ENABLED` (env-only `ClassVar`, **default ON**) через `ui_flags`;
  OFF → прежняя **раскладка** 10.23 (аккордеоны + отдельная карточка режимов).
  Код-дефолт `casual` безусловен и флагом OFF не откатывается.
- Откат: флаг OFF / `git revert` (именно `git revert` возвращает код-дефолт
  `casual → serious` и прежнюю проводку режимов). Δ DDL = 0.
