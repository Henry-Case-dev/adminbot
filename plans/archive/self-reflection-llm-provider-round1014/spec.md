# Spec F8 — `self-reflection-llm-provider-round1014` (3-й провайдер: LLM для саморефлексии / Экстрактор сути)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1541…T-1548. **ТЗ:** `plans/current_task.md` **UPD п.3**.
> **Зависимости:** нет (self-contained; потребляется **F1** — экстрактор сути).
> **Паттерн:** parent+subBlocks round 10.12 / **ADR-1013-1** (выделенные LLM Интеллекта `intel_history`/`intel_bg`).
> **Baseline:** HEAD `2edc65b`, каталог 427/90/399/403, pytest 5392/0.

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **Роль** | `LLMClient.generate_worker('reflection')`; slug `intel_reflection`; `_WORKER_ROLE_PREFIX['reflection']='intel_reflection'`. |
| **PG-ключи** | `models.intel_reflection_base_url`, `models.intel_reflection_model_name`, `models.intel_reflection_display_name`, `keys.intel_reflection_api_key`. |
| **Дефолты/фоллбэк** | Все поля пусты → используется основная модель (`models.llm_*` / `keys.llm_api_key`); dedicated-ошибка/пустой ответ → `generate()` (fail-open). Ровно как `intel_history`/`intel_bg`. |
| **UI** | Новый parent-блок «LLM для саморефлексии (Экстрактор сути)» в витрине «LLM Провайдеры» (модуль «Саморефлексия»), формат parent+subBlocks; `testable` по умолчанию (probe). |
| **Probe** | `intel_reflection_main` в `llm_probe`: `_LLM_BLOCKS`, `_BLOCK_SAVED_KEY`, `_INTEL_BLOCK_SLUG`; фоллбэк base/model на основную модель (S10.13-10). |
| **RBAC** | models.* / keys.* — глобальные (per_chat=False); R17-маска `{configured,last4}`. |
| **Каталог-Δ** | +4 ключа: REGISTRY 427→**435**, Settings 399→**406**, categorized 403→**411**; GROUPS/mapped/TAB_RULES без изменений. |

---

## §1. Цель и scope

Владелец требует **третье отдельное подключение провайдера** для «LLM для саморефлексии (Экстрактор сути)»
(UPD п.3). Экстрактор сути собственных ответов бота (F1) вызывает выделенную модель; пустые поля → основная модель.

**In scope:** PG-ключи (models/keys), дефолты settings, роль `reflection` в `generate_worker`, probe, UI-блок, каталог-Δ, тесты.

**Out of scope:** изменение промпта/логики F1 (только роль); `status.llm` «Доступность ключей» (сейчас `intel_*` не выводятся — не расширяем); иные провайдеры.

---

## §2. Данные и каталог

### 2.1. `config/settings.py` (рядом с `INTEL_HISTORY_*`/`INTEL_BG_*`, `:435-442`)
```python
INTEL_REFLECTION_BASE_URL: str = _env_str("INTEL_REFLECTION_BASE_URL", "")
INTEL_REFLECTION_MODEL_NAME: str = _env_str("INTEL_REFLECTION_MODEL_NAME", "")
INTEL_REFLECTION_DISPLAY_NAME: str = _env_str("INTEL_REFLECTION_DISPLAY_NAME", "")
INTEL_REFLECTION_API_KEY: str = _env_str("INTEL_REFLECTION_API_KEY", "")
```

### 2.2. `services/param_catalog.py`
```python
# _MODELS (group models_extra_providers — рядом с INTEL_BG_*)
("INTEL_REFLECTION_BASE_URL", "Адрес нейросети саморефлексии", "str", "models_extra_providers",
 "Адрес сервера нейросети для экстрактора сути (саморефлексия). Пусто — используется основная нейросеть."),
("INTEL_REFLECTION_MODEL_NAME", "Модель саморефлексии", "str", "models_extra_providers",
 "Название модели для экстрактора сути. Пусто — берётся основная модель."),
("INTEL_REFLECTION_DISPLAY_NAME", "Название модели саморефлексии", "str", "models_extra_providers",
 "Как называть эту нейросеть в админке. Пусто — покажется адрес сервера."),

# _KEYS (group keys_llm — рядом с INTEL_HISTORY_API_KEY/INTEL_BG_API_KEY)
("INTEL_REFLECTION_API_KEY", "Ключ нейросети саморефлексии", "str", True, "keys_llm",
 "Ключ отдельной нейросети для экстрактора сути. Пусто — используется ключ основной нейросети."),
```
- Типы/группы/категории — как у соседних `intel_*`; `per_chat=False` (категории models/keys).
- `.env.example` — 4 плейсхолдера (пустые).

### 2.3. Роль воркера (`services/llm_client.py:895-899`)
```python
_WORKER_ROLE_PREFIX = {
    "history": "intel_history",
    "background": "intel_bg",
    "bg": "intel_bg",
    "reflection": "intel_reflection",   # F8/UPD п.3
}
```
- `_worker_profile` уже читает `models.{slug}_base_url`, `models.{slug}_model_name`, `keys.{slug}_api_key`;
  `dedicated` = любой непустой; пустые поля → основная модель; ошибка dedicated → фоллбэк `generate()`. **Код не меняется, кроме словаря.**

### 2.4. Probe (`services/llm_probe.py`)
- `_LLM_BLOCKS` (`:36-44`): + `"intel_reflection_main"`.
- `_BLOCK_SAVED_KEY` (`:58-74`): + `"intel_reflection_main": "keys.intel_reflection_api_key"`.
- `_INTEL_BLOCK_SLUG` (`:116-118`): + `"intel_reflection_main": "intel_reflection"`.
- `_intel_probe_fallback` (S10.13-10) автоматически подставит base/model основной модели.

### 2.5. Frontend (`web/app.js` `PROVIDER_BLOCKS`, рядом с `intel_background` `:470-481`)
```js
{ id: 'intel_reflection', title: 'LLM для саморефлексии (Экстрактор сути)',
  modules: 'Саморефлексия',
  subBlocks: [
    { id: 'intel_reflection_main', title: 'Подключение',
      modules: 'Саморефлексия',
      fields: [
        { key: 'models.intel_reflection_display_name', label: 'Название модели', role: '' },
        { key: 'models.intel_reflection_base_url', label: 'Адрес сервера', role: 'base_url' },
        { key: 'models.intel_reflection_model_name', label: 'Модель', role: 'model' },
        { key: 'keys.intel_reflection_api_key', label: 'Ключ', role: 'api_key', secret: true },
      ] },
  ] },
```
- `testable` не отключаем (сетевой провайдер → probe `intel_reflection_main`).
- Пустые поля не тестируются как отдельные probeTarget (общий `testBlock`).

## §3. Каталог-Δ (сводка раунда)

| Метрика | Baseline | F1 | F2 | F6 | F8 | Итог |
|---|---|---|---|---|---|---|
| REGISTRY | 427 | +2 | +1 | +1 | **+4** | **435** |
| Settings | 399 | +2 | +1 | 0 | **+4** | **406** |
| categorized | 403 | +2 | +1 | +1 | **+4** | **411** |
| GROUPS | 90 | 0 | 0 | 0 | 0 | 90 |
| mapped (`_TAB_BY_GROUP`) | 88 | 0 | 0 | 0 | 0 | 88 |
| TAB_RULES / CONFIG_TAB_TITLES | 19 | 0 | 0 | 0 | 0 | 19 |

## §4. Feature flag / progressive delivery

- Отдельного флага не требуется: при пустых полях блок — no-op (основная модель). Rollback = `git revert`.
- Включение dedicated-модели — заполнение полей в админке (без рестарта); R17: ключ только `{configured,last4}`.

## §5. Тест-план

1. `generate_worker('reflection')`: пустые поля → ровно `generate()`; задан base/model/key → dedicated-запрос; dedicated-ошибка → фоллбэк на основную; unknown role → `ValueError`.
2. `_worker_profile('reflection')` читает `models.intel_reflection_*`/`keys.intel_reflection_api_key` (hot-override).
3. Probe: `intel_reflection_main` в `KNOWN_BLOCKS`; пустые base/model → фоллбэк на основную (не ложный error); маска ключа.
4. Каталог: 4 новых ключа, группы/категории; пин-тесты Δ (REGISTRY 435 / Settings 406 / categorized 411; GROUPS/mapped/TAB_RULES 19).
5. `.env.example` содержит 4 ключа; секретов нет.
6. UI-маркеры: блок «LLM для саморефлексии (Экстрактор сути)», 4 поля, `intel_reflection_main`.
7. `node --check web/app.js`, полный pytest 0 failed, `git diff --check`.

## §6. Критерии приёмки (DoD)

- [ ] Третье подключение доступно в «LLM Провайдеры»; поля `intel_reflection_*` сохраняются/переживают рестарт.
- [ ] `generate_worker('reflection')` использует dedicated-модель; пусто → основная; ошибка → фоллбэк.
- [ ] Probe работает без ложных ошибок при частично заполненных полях.
- [ ] Δ каталога = +4 ключа; GROUPS/mapped/TAB_RULES не изменились.
- [ ] R17 соблюдён; полный `pytest` 0 failed; `node --check` clean.
