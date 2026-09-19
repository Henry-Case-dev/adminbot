# Задачи: image-generation-tool-round1023

> **Раунд 10.23** · Приоритет **P1** · Шаг 1 @PM (+ Step 2 @Architect: `spec.md` + **ADR-1023-5**) · Тип: backend (tool/service/DDL) + канон? + UI (`web/**`)
> **ТЗ:** `plans/current_task.md`, «Генерация изображений и Rich Text Саммари → 1. Генерация изображений (Direct Chat)». Untracked, секреты не цитировать/не коммитить (R17/R18).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** F2 (ступень `param_catalog`).

## Цель
Инструмент `generate_image` для Синтезатора прямого чата: срабатывает на явные ключевики («Бот, нарисуй …», «Бот, создай изображение …», «Бот, создай мем …») и на свободные просьбы через tool-calling. При падении Вербализатор выдаёт циничную отмазку. Провайдер по умолчанию — Pollinations.ai (seed-миграция), настраивается в UI.

## Контекст / что уже есть
- Tool Calling: `services/tool_schemas.py` (8 инструментов, EN-descriptions), `services/tool_loop.py` (`TOOL_MAX_ROUNDS=4` `:38`), `services/tool_router.py`, `services/direct_chat_service.py:726` (`active_tools(...)`).
- Провайдеры/ключи в каталоге: группы `models_*`/`keys_*` (`services/param_catalog.py:158-187`), вкладка «Провайдеры» (`TAB_RULES` `:1909`).
- Бюджет платных вызовов: `services/worker_budget.py:196` `consume(...)`.
- DDL/сиды: `services/pg_db.py` (идемпотентные `CREATE TABLE IF NOT EXISTS` + `ALTER … ADD COLUMN IF NOT EXISTS`).
- **Нет** существующего кода генерации изображений и Pollinations-интеграции.

## КРИТИЧЕСКОЕ ПРАВИЛО ТЗ
Перед интеграцией сторонних API — **обязательно** изучить актуальную документацию через веб-поиск (Exa/DuckDuckGo), не гадать.

## Секреты
Ключ Pollinations задан в ТЗ (`plans/current_task.md`, untracked). В коммитимые файлы/миграции **plaintext-ключ не попадает**: сид читает ключ из `.env`/PG-настройки. В планах/отчётах — только ссылка «ключ из ТЗ current_task.md».

## Задачи
- [x] **T-2136** [@Architect] ADR-1023-5: схема инструмента `generate_image`, конфиг провайдера (URL/модель/ключ/GET-режим), хранение секрета (`.env`/PG, не git), интеграция tool_loop/`active_tools`, путь через `worker_budget`, фолбэк-отмазка, откат. Создать `spec.md` + `ADR-1023-5.md`.
- [x] **T-2137** [@Builder] **Веб-ресёрч (обязательно):** актуальная документация Pollinations API (endpoint, `response_format: "url"`, параметры модели `flux`), проверить актуальность; зафиксировать координаты в spec/ADR (без секретов).
- [x] **T-2138** [@Builder] Инструмент `generate_image` в `services/tool_schemas.py` (EN-description, строгая типизация) + регистрация в `active_tools` под тумблер модуля; обработка в tool-loop (`TOOL_MAX_ROUNDS=4`).
- [x] **T-2139** [@Builder] Сервис `services/image_generation.py`: вызов провайдера (`response_format: "url"` жёстко), поддержка GET-режима, таймауты, fail-open → циничная отмазка; лог без секретов (R17).
- [x] **T-2140** [@Builder] Платный вызов проходит через `services/worker_budget.py::consume` (метрика/лимит — по spec); при исчерпании — деградация/отмазка.
- [x] **T-2141** [@Builder] Каталог: группы `models_images`/`keys_images` (`URL`, `Модель`, `API Ключ`, чекбокс «Режим GET-запроса») + модуль-тумблер (`flags_module_images`) в `services/param_catalog.py`; Δ каталога зафиксировать.
- [x] **T-2142** [@Builder] Seed-миграция дефолтного провайдера Pollinations (Base URL `https://gen.pollinations.ai/v1`, модель `flux`). **Ключ — только из env/PG (значение «ключ из ТЗ current_task.md»); в миграции/репозитории plaintext отсутствует**; миграция идемпотентна (`ON CONFLICT DO NOTHING`).
- [x] **T-2143** [@Builder] UI: блок image-генерации в «Провайдеры» (URL/Модель/API Ключ/чекбокс GET) + тумблер в «Модули» (`web/index.html`, `web/app.js`, generic-рендер; структура меню не меняется — tma-menu-freeze).
- [x] **T-2144** [@Builder] Тесты: схема/регистрация инструмента, гейт тумблера, GET-режим, путь worker_budget, идемпотентность сида, отсутствие plaintext-ключа в репозитории, отмазка при падении.
- [x] **T-2145** [@Builder] Регресс: существующие инструменты/каталог не сломаны; `test_param_catalog` обновлён осознанно; полный pytest 0 failed.
- [ ] **T-2146** [@DevOps] Деплой: добавить env-переменную ключа на сервере (без вывода значения), прогнать сид, живая приёмка генерации; отчёт (R17/R18).

## Критерии приёмки
- Инструмент вызывается по ключевикам и через tool-calling; результат — изображение (URL).
- Провайдер/модель/ключ/GET-режим настраиваются в UI; тумблер модуля работает.
- Дефолтный провайдер Pollinations записан сид-миграцией; **секрет нигде в git не хранится plaintext**.
- При падении API — циничная отмазка, бот не падает. Полный pytest — 0 failed.

## Риски
- **R1 (Critical):** утечка секрета Pollinations в git/логи → только env/PG, тест «нет plaintext в репо», отчёт без значения (T-2142/T-2144/T-2146).
- **R2 (High):** неверная/устаревшая интеграция Pollinations → обязательный веб-ресёрч + фиксация в spec (T-2137).
- **R3 (High):** необработанный платный вызов / расход вне бюджета → `worker_budget.consume` + деградация (T-2140).
- **R4 (Medium):** тулы ломают порядок/канон R9 → новый инструмент добавляется осознанно, тесты состава (T-2138/T-2145).
- **R5 (Medium):** UI-изменение меняет структуру меню → tma-menu-freeze, generic-рендер (T-2143).

## Зависимости / ступени вливания
- **Зависит от F2** (порядок правок `param_catalog`) → после F2; может идти **параллельно** канон-цепочке F3/F4 (другие файлы).
- Эксклюзив: `services/tool_schemas.py`, `services/image_generation.py`, `services/worker_budget.py` (чтение), группы каталога `*_images`.
- `web/index.html`/`web/app.js` — **ступень F5 → F7 → F8** (блок провайдеров раньше dashboard/табов).
- Требует `spec.md` + `ADR-1023-5` (Step 2 @Architect).

## Feature flag / раскатка
- `IMAGE_GENERATION_ENABLED` — env-only `ClassVar` (**default ON**) + каталоговый тумблер модуля. Раскатка internal→10%→50%→100% не требуется; откат — kill-switch OFF / `git revert` (сид обратимо: дефолтный провайдер удаляется без потери пользовательских настроек).
