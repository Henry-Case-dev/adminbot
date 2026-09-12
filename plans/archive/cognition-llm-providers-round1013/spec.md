# Spec F4 — `cognition-llm-providers-round1013` (выделенные LLM для Интеллекта)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; спека Step 2 @Architect, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §3 (UI). Tasks: T-1443…T-1447. UI + аддитивный read-path. P1.
> ADR: `adr-1013-1-provider-keys.md` (единые ключи F3↔F4 — обязателен к исполнению).

## 0. Цель

В настройках провайдеров (Vue) — два новых блока подключения: LLM для
Исторической памяти (Вехи/Лор) и LLM для Фоновых проверок (Оценка важности).
Пустые поля → фоллбэк на основную модель. Серверный роутер — в F3 (T-1439).

## 1. Объём

### In scope
- 2 provider-блока `parent`+`subBlocks` с полями Base URL / Модель / Название / Ключ.
- Регистрация блоков в `providerCoveredKeys`, `_BLOCK_SAVED_KEY`, `_LLM_BLOCKS`.
- 8 новых PG-ключей (ADR-1013-1) + settings-дефолты + `.env.example` плейсхолдеры.
- `saveBlock`/`testBlock`/`testField` для новых блоков (global-save при активном чате, без 422).

### Out of scope
- Серверный роутер (F3 T-1439) — здесь только ключи/UI/probe.
- Отдельные probe-карточки в «Доступность ключей» (F4-Q4: не обязательно; см. §12).

## 2. Схема данных / ключи

Ровно 8 ключей по ADR-1013-1 (4×`history`, 4×`bg`). Хранилище — PG `bot_settings`
существующим DML-путём (сид `ON CONFLICT DO NOTHING`); ноль DDL; SQLite v8.

## 3. Изменения UI/контрактов

### 3.1. `web/app.js` — `PROVIDER_BLOCKS`
Добавить два parent-блока (см. ADR-1013-1 §2.3). Требования:
- parent `modules` ≠ `title` (иначе R10.12-5 дубль — уже реализовано в
  `blockDisplayName:2158`, но задать осмысленный `modules`).
- subBlock id: `intel_history_main`, `intel_background_main` (стабильные — ждёт probe).
- `role`: display `''` (для `blockDisplayName`), `base_url`, `model`, `api_key`.

### 3.2. `providerCoveredKeys` (`app.js:2815`)
Ничего менять не нужно — рекурсивный обход `subBlocks[].fields` уже покрывает.
Добавить тест, что новые ключи покрыты (generic-дублей нет).

### 3.3. `services/llm_probe.py`
- `_LLM_BLOCKS` += `intel_history_main`, `intel_background_main`.
- `_BLOCK_SAVED_KEY` += соответствующие `keys.intel_*_api_key`.
- `probe_block` — chat-probe (`kind="chat"`), байт-путь без изменений.

### 3.4. `api()`/`saveBlock` global-save (10.12)
Новые ключи — `per_chat` для моделей: `models.*` per_chat=true (по умолчанию
категория models), `keys.*` — secrets, per_chat=false → global-save.
`saveBlock` для mixed parent (models per_chat=true + key per_chat=false) уже
умеет 2 последовательных запроса (10.12 ADR-1012-1 D2). Ничего нового.

### 3.5. `services/llm_client.py` / `status_service.py`
Read-path: F4 **добавляет только чтение** ключей для отображения (каталог/hot).
Фактический выбор модели для воркеров — в F3 (`generate_worker`). Опционально
`status_service.llm_registry` — карточки `intel_history`/`intel_bg` (F4-Q4,
не обязательно; при добавлении — маска `{configured,last4}`, R17).

## 4. Алгоритм (UI-поток, без изменений механики)

```
saveBlock(parent-block):
  для каждого subBlock: собрать drafts (display/base/model/api_key)
  models per_chat=true → chat-scope POST (X-Chat-Id, configChatUpdatedAt)
  keys per_chat=false  → global POST (global:true, updated_at:null)
  реальные значения → blockFieldValue; секрет пустой → не перетирать (MINOR-3)
testBlock(subBlock) → POST /api/llm/test с base_url/model + api_key (пусто → probe резолвит сохранённый)
```

## 5. Файлы и точки изменения

| Файл | Что |
|---|---|
| `web/app.js` | `PROVIDER_BLOCKS` :358 (+2 блока) |
| `web/index.html` | рендер merged-блоков — без изменений (generic subBlocks) |
| `services/llm_probe.py` | `_LLM_BLOCKS` :33, `_BLOCK_SAVED_KEY` :54 |
| `services/param_catalog.py` | `_MODELS`/`_KEYS` += 8 записей (группы `models_extra_providers`/`keys_llm`) |
| `config/settings.py` | 8 полей `INTEL_*` = `""` (после `LLM_FALLBACK_*`) |
| `.env.example` | 8 закомментированных плейсхолдеров |
| `tests/test_webapp_round1013_ui.py` (новый), `test_llm_probe.py`, `test_param_catalog.py`, `test_webapp_api.py`, `tests/js/routing_test.js` | тесты/пин-счётчики |

## 6. Каталог-Δ

| Ключ | Кат. | Группа | Тип/дефолт | Settings | secret | per_chat |
|---|---|---|---|---|---|---|
| `models.intel_history_base_url` | models | `models_extra_providers` | str / `""` | `INTEL_HISTORY_BASE_URL` | – | true |
| `models.intel_history_model_name` | models | `models_extra_providers` | str / `""` | `INTEL_HISTORY_MODEL_NAME` | – | true |
| `models.intel_history_display_name` | models | `models_extra_providers` | str / `""` | `INTEL_HISTORY_DISPLAY_NAME` | – | true |
| `keys.intel_history_api_key` | keys | `keys_llm` | str / `""` | `INTEL_HISTORY_API_KEY` | ✔ | false |
| `models.intel_bg_base_url` | models | `models_extra_providers` | str / `""` | `INTEL_BG_BASE_URL` | – | true |
| `models.intel_bg_model_name` | models | `models_extra_providers` | str / `""` | `INTEL_BG_MODEL_NAME` | – | true |
| `models.intel_bg_display_name` | models | `models_extra_providers` | str / `""` | `INTEL_BG_DISPLAY_NAME` | – | true |
| `keys.intel_bg_api_key` | keys | `keys_llm` | str / `""` | `INTEL_BG_API_KEY` | ✔ | false |

Итог F4: **REGISTRY +8**, **Settings +8**, GROUPS 90, mapped 88, TAB_RULES 19.
(Кумулятивно после F1/F2/F3/F4: REGISTRY 405→427, Settings 377→399, categorized 381→403.)

## 7. Feature flags / progressive delivery

- Feature flag не требуется (config/UI-only, аддитивные параметры; прецедент 10.9–10.12).
- Rollback — атомарный `git revert`; значения в PG правятся из админки без DDL.

## 8. План миграций промптов

Не применимо (промптов нет).

## 9. Тест-план

1. JS: `PROVIDER_BLOCKS` содержит `intel_history`/`intel_background` с subBlocks и
   полями ролей; `blockDisplayName` не даёт дубль title; `providerCoveredKeys`
   покрывает все 8 ключей.
2. JS: `saveBlock` для mixed per_chat → 2 запроса (global без `X-Chat-Id`);
   `testBlock` шлёт base_url/model, пустой api_key → probe-резолв.
3. Python: `test_param_catalog` Settings 399, группы без изменений;
   `_BLOCK_SAVED_KEY`/`_LLM_BLOCKS`/`KNOWN_BLOCKS` содержат новые id.
4. `test_webapp_api`: `POST /api/llm/test` для `intel_history_main` резолвит
   сохранённый ключ при `api_key:""` (R17: без эха).
5. `test_round106_ia_smoke.provider_blocks_single_home` — под merged-модель без потерь.
6. `node --check web/app.js` clean; `node tests/js/routing_test.js` → `JS-UNIT-OK`.

## 10. Риски

| Риск | Митигация |
|---|---|
| Забыть `_BLOCK_SAVED_KEY` → «не настроен» при сохранённом ключе | Тест probe-резолва |
| Generic-дубли (R10.6-1) | `providerCoveredKeys` рекурсивен; тест покрытия |
| R10.12-5 дубль title/modules | `modules` ≠ `title` для parent |
| R10.11-1 общий localStorage-ключ details | не трогаем nested details; новые блоки — в зоне «Подключения» (F4-Q3) |

## 11. Критерии приёмки

- [ ] Два новых блока (parent+subBlocks) с полями Base URL / Модель / Название / Ключ.
- [ ] Пустые поля → основная модель (поведение задокументировано в ADR-1013-1).
- [ ] `providerCoveredKeys` + `_BLOCK_SAVED_KEY` покрывают; generic-дублей нет.
- [ ] Сохранение/тест новых блоков при активном чате (global-save, без 422).
- [ ] Каталог-Δ осознан (Settings 399, REGISTRY 427); пин-тесты обновлены.
- [ ] `node --check` clean, `JS-UNIT-OK`, `pytest` 0 failed, `git diff --check`.
- [ ] Ноль PG-DDL; `.env.example` — плейсхолдеры; R17 (секреты только `{configured,last4}`).

## 12. Разрешение open questions (F4)

- **F4-Q1** — раздельные ключи base_url/model/display/key на каждую роль (всего 8), не один общий.
- **F4-Q2** — фоллбэк на `keys.llm_api_key` / `models.llm_base_url` / `models.llm_model_name` (основная модель).
- **F4-Q3** — блоки в зоне «Подключения» (сверху), не в «Расширенных».
- **F4-Q4** — отдельные probe-карточки в «Доступность ключей» **не обязательны** для v1 (опционально, если добавит F5); README/ADR фиксируют.
