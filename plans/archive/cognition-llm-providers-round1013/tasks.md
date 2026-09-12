# Фича F4 — `cognition-llm-providers-round1013` (выделенные LLM для Интеллекта)

> **Статус: ✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; реализовано Step 4 @Builder, 13.09.2026). Спека: `spec.md` + `adr-1013-1-provider-keys.md`.
> Каталог-Δ: REGISTRY 427 / Settings 399 / categorized 403 (GROUPS 90 / mapped 88 / TAB_RULES 19).
> Полный `pytest` — 5343 passed / 0 failed; `node --check web/app.js` clean; `JS-UNIT-OK`; `git diff --check` clean.
> **Раунд:** 10.13. **Нумерация:** T-1443…T-1447 (продолжает F3 T-1442).
> **Тип:** frontend (UI провайдеров) + аддитивный серверный read-path. **Приоритет:** P1.
> **Зависимости:** независима (может идти параллельно F1–F3); **согласовать имена PG-ключей** с F3
> (T-1439 — роутер воркеров).
> **ТЗ:** `plans/current_task.md`, раздел **3** (UI-часть «Выделенные LLM для Интеллекта (Настройки)»).
> **Эпик:** `Epic: Cognition-Sleep-Memory Refactor round1013`.

## 0. Цель

В настройках провайдеров (Vue) появляются два новых блока подключения: LLM для Исторической памяти
(Вехи/Лор) и LLM для Фоновых проверок (Оценка важности). Пустые поля → автоматический фоллбэк на основную
модель.

## 1. Требования (дословно из ТЗ §3 UI)

- [x] Два новых блока подключения в UI настроек провайдеров:
  1. **LLM для Исторической памяти (Вехи/Лор)**
  2. **LLM для Фоновых проверок (Оценка важности)**
- [x] Если поля пустые — фоллбэк на **Основную модель**.
- [x] (backend-часть роутера — в F3, T-1439; здесь — UI + параметры + probe-поддержка.)

## 2. Целевые модули (`file:line` на HEAD `ce25dc7`)

- `web/app.js` — `PROVIDER_BLOCKS` (`blockDisplayName`, merged parent+`subBlocks` модель 10.12),
  `providerCoveredKeys` (рекурсивный обход `subBlocks[].fields`), `saveBlock`/`testBlock`/`testField`.
- `web/index.html` — рендер блоков подключения (10.12: `subBlocks`, динамическая подпись display-name).
- `services/llm_probe.py` — `_BLOCK_SAVED_KEY`, `KNOWN_BLOCKS`, `_LLM_BLOCKS`/`_EMBEDDING_BLOCKS`.
- `services/param_catalog.py` — ParamSpec/GroupSpec, категории `models`/`keys` (санкционированный Δ).
- `config/settings.py` — code-default новых параметров; `.env.example` — плейсхолдеры.
- `services/llm_client.py`, `services/status_service.py` — read-path выбранной модели (hot.get).
- `bot.py` — только DI-kwargs (порядок роутеров не трогать).
- Тесты: `tests/test_webapp_round1013_ui.py` (новый), `tests/test_llm_probe.py`,
  `tests/test_param_catalog.py`, `tests/test_webapp_api.py`, `tests/js/routing_test.js`.

## 3. Инварианты (constraints — не нарушать)

- **Новые provider-блоки — только формат `parent` + `subBlocks` (10.12).** Обязательно добавлять их в
  `providerCoveredKeys` **и** в `_BLOCK_SAVED_KEY` (`services/llm_probe.py`) — иначе generic-дубли (R10.6-1)
  или «не настроен» при сохранённом ключе.
- **R17:** секреты — только `{configured, last4}`; на фронт сырой ключ не уходит; probe-резолв сохранённого
  ключа — только для пустого `api_key`.
- **R16:** id — ключ, не имя.
- **Ноль новых PG-DDL**; SQLite **v8**; порядок роутеров `bot.py` не трогать (DI-kwargs).
- **Каталог-инварианты 405/90/377/88, TAB_RULES 19** — новые ключи только санкционированным Δ с
  обновлением пин-тестов (`test_param_catalog`, `test_round106_ia_smoke.provider_blocks_single_home`).
- **Reuse R10.12-5:** parent-`modules` не должен дублировать `title` (иначе `blockDisplayName` даёт шум).
- **R10.11-1:** не воспроизводить общий `localStorage`-ключ nested-`<details>`.
- **Коммиты:** русские conventional commits.

## 4. Зависимости

- **Вверх:** нет.
- **Пересечение:** F3 (T-1439) исполняет серверный роутер по тем же ключам — **имена ключей фиксируются
  @Architect в F3 T-1434/здесь T-1443**; исполнять F4 после согласования ключей.
- **Вниз:** F5 (дашборд) может показывать статус/модели этих воркеров.

## 5. Definition of Done

- [x] В UI два новых блока подключения (parent+subBlocks) с полями Base URL / Модель / Название модели / Ключ.
- [x] Пустые поля → фоллбэк на основную модель; поведение документировано.
- [x] `providerCoveredKeys` покрывает новые ключи; `_BLOCK_SAVED_KEY` резолвит сохранённый ключ; generic-дублей нет.
- [x] Сохранение/тест новых блоков работает при активном чате (global-save, без 422).
- [x] Каталог-Δ осознан: пересчитаны REGISTRY/GROUPS/Settings/mapped, обновлены пин-тесты.
- [x] `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`; полный `pytest` — 0 failed.
- [x] `git diff --check` чист; ноль PG-DDL; `.env.example` — только плейсхолдеры.

## 6. Чек-лист задач

- [x] **T-1443 (@Architect, гейт):** spec/ADR: имена PG-ключей (`models.*_base_url`/`_model_name`/`_display_name`,
  `keys.*_api_key`), категория/группа, дефолты, семантика «пусто → основная модель», probe-идентификаторы
  блоков, санкционированный Δ каталога, связь с F3 T-1439.
- [x] **T-1444 (@Builder):** 2 новых provider-блока `parent`+`subBlocks` в `PROVIDER_BLOCKS`
  (историческая память; фоновые проверки) с полями Base URL/Модель/Название модели/Ключ.
- [x] **T-1445 (@Builder):** `providerCoveredKeys` (рекурсивно), `_BLOCK_SAVED_KEY`/`KNOWN_BLOCKS`/`_LLM_BLOCKS`
  в `services/llm_probe.py`; `saveBlock`/`testBlock`/`testField` корректны; `blockDisplayName` без дубля title.
- [x] **T-1446 (@Builder):** параметры в `services/param_catalog.py` + `config/settings.py` + `.env.example`;
  обновление счётчиков и пин-тестов; фоллбэк на основную модель при пустых полях.
- [x] **T-1447 (@Builder):** тесты: JS-юниты (блоки/покрытие ключей/фоллбэк), Python (`test_param_catalog`,
  `test_webapp_api`, `test_llm_probe`), статик-маркеры; `node --check`, полный `pytest`, `git diff --check`.

## 7. Открытые вопросы (@Architect → владелец)

- **F4-Q1:** одна выделенная LLM на категорию или раздельные ключи base_url/key для каждой?
- **F4-Q2:** пустое поле ключа → фоллбэк на основную модель (какой именно — `keys.llm_api_key`)?
- **F4-Q3:** показывать ли блоки в зоне «Подключения» или в «Расширенные» (10.11 две зоны)?
- **F4-Q4:** нужны ли отдельные probe-карточки в «Доступность ключей» (`status_service.llm_registry`)?

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (config/UI-only, аддитивные параметры; прецедент 10.9–10.12).
- **Rollback:** атомарный `git revert`; значения в PG правятся через админку без DDL.
- **Progressive delivery:** неприменимо (внутренний инструмент одного владельца).
