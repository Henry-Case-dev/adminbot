# Фича F8 — `self-reflection-llm-provider-round1014` (3-й провайдер: LLM для саморефлексии / Экстрактор сути)

> **Статус: ✅ COMPLETED** (Step 4 @Builder, 13.09.2026). `spec.md` реализован;
> pytest 5527/0, `node --check web/app.js` clean, `node tests/js/routing_test.js` OK.
> **Раунд:** 10.14. **Нумерация:** T-1541…T-1548 (продолжает T-1540 — финал F7).
> **Тип:** backend + frontend. **Приоритет:** P1 (нужен F1 для dedicated-роли; без него — фоллбэк).
> **Зависимости:** нет (потребляется **F1**).
> **ТЗ:** `plans/current_task.md` **UPD п.3**. **Эпик:** Self-Awareness / Persona round1014.
> **Паттерн:** ADR-1013-1 (`intel_history`/`intel_bg`). **Baseline:** HEAD `2edc65b`, pytest 5392/0.

## 0. Цель

Добавить в UI настройки провайдеров **третье отдельное подключение** «LLM для саморефлексии (Экстрактор сути)»:
PG-ключи `models.intel_reflection_*` + `keys.intel_reflection_api_key`, backend-роль `reflection` в
`LLMClient.generate_worker`, фоллбэк на основную модель (DeepSeek) при пустых полях.

## 1. Требования (UPD п.3)

- [x] Третье отдельное подключение провайдера в UI.
- [x] Логика фоллбэка: пусто → основная модель.
- [x] Backend-роль `reflection` для экстрактора сути (F1).

## 2. Целевые модули (`file:line` на HEAD `2edc65b`)

- `config/settings.py` `:435-442` — +4 поля `INTEL_REFLECTION_*`.
- `services/param_catalog.py` — `_MODELS`/`_KEYS` (+4 записи, группы `models_extra_providers`/`keys_llm`).
- `services/llm_client.py` `:895-899` — `_WORKER_ROLE_PREFIX['reflection']='intel_reflection'`.
- `services/llm_probe.py` `:36-44`, `:58-74`, `:116-118` — `intel_reflection_main`.
- `web/app.js` `PROVIDER_BLOCKS` `:470-481` — parent-блок + subBlock.
- `.env.example` — 4 плейсхолдера.
- Тесты: расширить `tests/test_deep_sleep.py` (образец intel), `tests/test_param_catalog.py`, UI-маркеры.

## 3. Инварианты

- ✅ PG-DDL разрешён; F8 новых таблиц не вводит (только bot_settings-ключи).
- ⛔ Порядок роутеров `bot.py`, `media/`/`.env` (кроме `.env.example`), R17/R16.
- **Единый паттерн ADR-1013-1:** поля display/base/model/key; пустые → основная; dedicated-ошибка → фоллбэк.
- **Каталог-Δ F8:** +4 (REGISTRY 435 / Settings 406 / categorized 411); GROUPS/mapped/TAB_RULES без изменений.
- **Ревью-гейты:** полный `pytest` 0 регрессий, `node --check web/app.js`, пин-тесты каталога, R17-скан, русские commits.

## 4. Зависимости

- **Вверх:** нет. **Вниз:** **F1** (использует роль `reflection`; при отсутствии — фоллбэк на основную модель).

## 5. Definition of Done

- [x] Блок «LLM для саморефлексии (Экстрактор сути)» в «LLM Провайдеры» (parent+subBlocks, 4 поля).
- [x] `generate_worker('reflection')` — dedicated при непустых полях; иначе основная; ошибка → фоллбэк.
- [x] Probe `intel_reflection_main` без ложных ошибок.
- [x] Δ каталога +4; R17 соблюдён.
- [x] Полный `pytest` 0 failed; `node --check` clean; `git diff --check` чист.

## 6. Чек-лист задач

- [ ] **T-1541 (@Architect, гейт):** spec: состав ключей `intel_reflection_*`, роль `reflection`, паттерн ADR-1013-1,
  probe, Δ каталога, фоллбэк.
- [x] **T-1542 (@Builder, backend):** `config/settings.py` (+4 поля), `param_catalog.py` (+4 записи),
  `.env.example`; пин-тесты каталога.
- [x] **T-1543 (@Builder, llm_client):** `_WORKER_ROLE_PREFIX['reflection']='intel_reflection'`; тест фоллбэка.
- [x] **T-1544 (@Builder, probe):** `intel_reflection_main` в `_LLM_BLOCKS`/`_BLOCK_SAVED_KEY`/`_INTEL_BLOCK_SLUG`;
  тест частично заполненных полей.
- [x] **T-1545 (@Builder, frontend):** provider-блок в `PROVIDER_BLOCKS` (parent+subBlocks, `modules:'Саморефлексия'`).
- [x] **T-1546 (@Builder, tests):** `generate_worker('reflection')` (dedicated/no-op/fallback/unknown), probe, UI-маркеры,
  Δ каталога.
- [x] **T-1547 (@Builder):** `node --check web/app.js`, полный `pytest` (0 failed), `git diff --check`.
- [ ] **T-1548 (@PM/@Reviewer, гейт):** сверка DoD, R17-скан, live-чеклист (сохранение полей на Android).

## 7. Открытые вопросы (закрыты владельцем)

- **F8-Q1:** формат — parent+subBlocks (ADR-1013-1). **F8-Q2:** фоллбэк — основная модель. **F8-Q3:** роль — `reflection`.

## 8. Feature flag / progressive delivery

- Флаг не требуется (пустые поля = no-op). Rollback = `git revert`. Включение — заполнение полей в админке.
