# ADR-1013-1 — Единые PG-ключи выделенных LLM для Интеллекта (F3↔F4)

> Статус: **ACCEPTED**. Дата: 13.09.2026. Автор: @Architect (Step 2).
> Касается: F3 (T-1439 роутер воркеров) и F4 (T-1443 UI-блоки/T-1446 параметры).
> База: HEAD `ce25dc7`.

## 1. Контекст

ТЗ §3 требует два выделенных подключения LLM: «для Исторической памяти
(Вехи/Лор)» и «для Фоновых проверок (Оценка важности)», с фоллбэком на основную
модель при пустых полях. F4 рисует UI-блоки, F3 исполняет роутер. Имена ключей
используют оба — их надо зафиксировать один раз.

Существующие прецеденты (сверено):
- `LLM_FALLBACK_BASE_URL`/`_MODEL`/`_API_KEY` — настройки с дефолтом `""`;
- `models.embedding_base_url` + `keys.embedding_api_key` — отдельная пара base/key (10.12);
- `_BLOCK_SAVED_KEY`/`KNOWN_BLOCKS`/`_LLM_BLOCKS` в `services/llm_probe.py`;
- модель провайдер-блоков 10.12 — `parent` + `subBlocks[].fields` с `role`
  (`''` display, `base_url`, `model`, `api_key`).

## 2. Решение

### 2.1. Имена PG-ключей (роли `history` / `background`)

| Роль | PG-ключ | Кат. | Группа | Settings-поле | Тип/дефолт |
|---|---|---|---|---|---|
| history | `models.intel_history_base_url` | models | `models_extra_providers` | `INTEL_HISTORY_BASE_URL` | str / `""` |
| history | `models.intel_history_model_name` | models | `models_extra_providers` | `INTEL_HISTORY_MODEL_NAME` | str / `""` |
| history | `models.intel_history_display_name` | models | `models_extra_providers` | `INTEL_HISTORY_DISPLAY_NAME` | str / `""` |
| history | `keys.intel_history_api_key` | keys | `keys_llm` | `INTEL_HISTORY_API_KEY` | secret / `""` |
| background | `models.intel_bg_base_url` | models | `models_extra_providers` | `INTEL_BG_BASE_URL` | str / `""` |
| background | `models.intel_bg_model_name` | models | `models_extra_providers` | `INTEL_BG_MODEL_NAME` | str / `""` |
| background | `models.intel_bg_display_name` | models | `models_extra_providers` | `INTEL_BG_DISPLAY_NAME` | str / `""` |
| background | `keys.intel_bg_api_key` | keys | `keys_llm` | `INTEL_BG_API_KEY` | secret / `""` |

Правило именования: `models.intel_<role>_<field>`, `keys.intel_<role>_api_key`,
`role ∈ {history, bg}`. `settings_field` — UPPER_SNAKE с префиксом `INTEL_<ROLE>_`.

### 2.2. Семантика «пусто → основная модель»

Читаются через `hot.get(pg_key, settings_default)`. Если base_url ИЛИ model
ИЛИ api_key пусты — используется соответствующее значение основной модели:
`models.llm_base_url` / `models.llm_model_name` / `keys.llm_api_key`
(code-defaults `settings.LLM_BASE_URL`/`LLM_MODEL_NAME`/`LLM_API_KEY`).
Роутер считается «dedicated» только если задан хотя бы один из трёх
(`base_url`/`model`/`api_key`); иначе — прямой вызов основной модели
(`LLMClient.generate`), байт-в-байт как в 10.12 (нулевой регресс).

### 2.3. UI provider-блоки (формат 10.12 — parent + subBlocks)

```
{ id: 'intel_history', title: 'LLM для исторической памяти (Вехи/Лор)',
  modules: 'Вехи и лор чата',            # ≠ title (R10.12-5 — не дублировать)
  subBlocks: [
    { id: 'intel_history_main', title: 'Подключение',
      modules: 'Вехи и лор чата',
      fields: [
        { key:'models.intel_history_display_name', label:'Название модели', role:'' },
        { key:'models.intel_history_base_url',     label:'Адрес сервера', role:'base_url' },
        { key:'models.intel_history_model_name',   label:'Модель',        role:'model' },
        { key:'keys.intel_history_api_key',        label:'Ключ',          role:'api_key', secret:true },
      ] } ] }
{ id: 'intel_background', title: 'LLM для фоновых проверок (Оценка важности)',
  modules: 'Оценка важности', subBlocks: [ { id:'intel_background_main', ... } ] }
```

### 2.4. Probe-идентификаторы (`services/llm_probe.py`)
- `_LLM_BLOCKS` += `intel_history_main`, `intel_background_main` (chat-probe).
- `_BLOCK_SAVED_KEY` += `intel_history_main → keys.intel_history_api_key`,
  `intel_background_main → keys.intel_bg_api_key`.
- `KNOWN_BLOCKS` — покрывается автоматически через `_LLM_BLOCKS`.
- `providerCoveredKeys` (рекурсивный обход `subBlocks[].fields`) — покрывает
  новые ключи автоматически ⇒ generic-дублей нет (R10.6-1).

### 2.5. Каталог-Δ (санкционированный)
F4: **REGISTRY +8**, **Settings +8** (все ключи — first-class с settings-дефолтом `""`),
GROUPS 90, mapped 88, TAB_RULES 19 — без изменений. Точные итоговые счётчики —
в `spec.md` F4 §7.

## 3. Обоснование

- **Единый формат `intel_<role>_*`** — очевидно расширяемый (добавление роли = 4 ключа),
  читаемые probe-идентификаторы `intel_<role>_main`.
- **`settings_field` для всех 8** (а не PG-only) — гарантированный code-default `""`
  (паритет с `LLM_FALLBACK_*`), простой сид/тест `test_param_catalog`, нет риска
  пустого `code_source`.
- **`base_url` обязателен в UI** — при переезде провайдеров выделенные модели
  ходят на свой адрес (паритет с OD-16/`models.embedding_base_url`).
- **Секреты** — `secret=True`, маска `{configured,last4}` (R17), probe резолвит
  сохранённый ключ только при пустом `api_key` (ADR-1011-1).

## 4. Последствия

- F4 и F3 исполняются по одним ключам; порядок: F4 (ключи/UI) может идти
  параллельно F1–F3, но T-1439 (роутер) должен читать именно эти ключи.
- Пин-тесты `test_param_catalog`/`test_webapp_api`/`test_round106_ia_smoke`
  обновляются (Settings +8, REGISTRY +8, provider_blocks под merged-модель).
- Диагностика: `status_service.llm_registry` — добавить (опц., F5-Q4) карточки
  `intel_history`/`intel_bg`; **не блокер** F4.

## 5. Альтернативы

- **A1. Один общий выделенный блок на оба воркера** — отклонено: ТЗ §3 требует
  два независимых блока; разный профиль (history — тяжёлая модель, background — дешёвая).
- **A2. Ключи `models.intel_base_url` + `models.intel_bg_*` без `_model_name`** —
  отклонено: непонятно, чем переопределяется модель; нужен явный `model_name`.
- **A3. PG-only (без settings_field)** — отклонено: нет code-default/сида,
  риск пустого `code_source` в `_MODELS_PG_ONLY`; +8 Settings приемлемо.
- **A4. Переиспользовать `models.llm_fallback_*`** — отклонено: семантика фолбэка
  иная (failover основной), а не маршрутизация воркеров.
