# Задачи: budget-global-toggle-round1024

> **Раунд 10.24 (UPD5-critical)** · Приоритет **P0** · Шаг 1 @PM · Тип: каталог + backend-гейты + UI (master-рубильник бюджетов)
> **ТЗ:** `plans/current_task.md`, **строка 404**: «Добавить глобальный тумблер для меню бюджетов в разделе Модули, который отключает/включает бюджеты целиком глобально/для выбранного чата и проверить чтобы эта настройка действительно работала». Секреты не цитировать (R17/R18).
> **Baseline:** HEAD `00eab85`; прод `4314ea4`. Разведка @Memory: координаты UPD5.
> **Конфликт/AMEND:** **AMEND ADR-1019-3** (`mod_budgets` без master-тумблера, `noToggle: true`) + **AMEND ADR-1019-8** (семантика лимитов, `0`=запрет/`<0`=безлимит) + **AMEND ADR-1019-2 D4** (`budget_snapshot`/BYOK-резолв) — ожидаемо **ADR-1024-22**.
> **Границы:** F20 (фикс merge — предпосылка, чтобы тумблер и значения не затирались); F22 (разграничение с `flags.chat_context_budgets_enabled`); F23 (пин-тесты каталога/TAB_RULES).

## Цель
Дать владельцу **один глобальный master-тумблер бюджетов** в разделе «Модули» (карточка «Бюджеты»): выключение бюджетов **целиком** — глобально или для выбранного чата. Сейчас карточка помечена `noToggle: true` (`web/app.js:393-395`) и не имеет master-флага; механика тумблеров — `MODULES` + `toggleKey` (`web/app.js:356-395`, `:3163-3174`).

Требование владельца: тумблер должен **реально** работать (гейты OFF обязаны обходить бюджеты так, чтобы бот не уходил в заглушку `content.no_key_reply`).

## Что уже есть (координаты, подтверждены)
- **UI:** `web/app.js:393-395` — `mod_budgets` c `noToggle: true`; секция `:130-135` (`type:'config'`, `sources:[{category:'limits', groups:['limits_chat_key','limits_chat_context','limits_worker']}]`); механика тумблеров `:356-395` (`MODULES`) и `:3163-3174` (`toggleModule`/`saveConfigItem`).
- **Гейты, которые должны уважать OFF:**
  - `services/chat_usage.py:194-258` — `budget_snapshot` (единый снимок; `exceeded/forbidden/unlimited/source`).
  - `services/worker_budget.py:201-227` (`consume`) и `:260-278` (`_metric_limit`) — фоновый контур.
  - `services/llm_client.py:385-420` — `_resolve_api_key_and_source` → `NoApiKeyForChat('budget')`.
- **Куда уходит фраза-заглушка (при OFF не должна):** `services/sandbox_reply.py:8-11` (`DEFAULT_NO_KEY_REPLY`, ключ `content.no_key_reply`) → ответ `services/direct_chat_service.py:767-781`.
- **Резолв флага per-chat:** `services/worker_settings.py:123-150` (`resolve_setting`/`resolve_setting_cached`, источник `chat|global|default`, fail-open).
- **Существующий близкий гейт (не путать!):** `flags.chat_context_budgets_enabled` (`services/direct_chat_service.py:1142-1145`; сид-скрипт `scripts/backfill_104_chat_flags.py` ставит `false` целевому чату) — это **усечение бюджета контекста промпта**, а не master-рубильник лимитов. Разграничение — T-2366.

## Задачи
- [x] **T-2360** [@Architect] spec.md + ADR (**ожидаемо ADR-1024-22**, AMEND ADR-1019-3/1019-8/1019-2-D4): семантика **OFF** (не считать и не ограничивать; счётчики продолжают писаться; **дефолт fail-open** — при недоступности резолва бюджеты НЕ отключаются, поведение как прежде); область (**глобально И per-chat**, per-chat override приоритетнее глобального); дефолт **ON**; приоритет master ↔ существующий `flags.chat_context_budgets_enabled`; **Δ каталога** (новый ключ + группа) — вынести в Human Gate; откат/флаг.
- [x] **T-2361** [@Builder] `services/param_catalog.py`: новый ключ **`flags.budgets_enabled`** (`CATEGORY_FLAGS`, bool, group) + **новая `GroupSpec`** для группы бюджетов-рубильника; обновить `REGISTRY`/`GROUPS`/`_TAB_BY_GROUP` пин-тесты в том же коммите. **Стоп-условие: не начинать без санкции владельца на Δ каталога (Human Gate №1).**
- [x] **T-2362** [@Builder] Гейт OFF в трёх точках: `services/chat_usage.py::budget_snapshot` (не считать превышение/запрет; счётчики писать), `services/worker_budget.py::consume`/`_metric_limit` (не ограничивать), `services/llm_client.py::_resolve_api_key_and_source` (не бросать `NoApiKeyForChat('budget')` при OFF). Fail-open: ошибка резолва флага → трактуем как ON (как прежде).
- [x] **T-2363** [@Builder] Резолв флага per-chat/global через `worker_settings.resolve_setting(_cached)` (source `chat|global|default`, дефолт **ON**); per-chat override приоритетнее глобального; учёт в `details`/диагностике (`resolve_path`, R17-safe, без секретов).
- [x] **T-2364** [@Builder] UI: в `web/app.js` убрать `noToggle: true` у `mod_budgets` и добавить `toggleKey: 'flags.budgets_enabled'` (`:393-395`); убедиться, что механика `toggleModule`/`saveConfigItem` (#3163-3174) сохраняет глобальный/чат-скоуп корректно; при необходимости отразить тумблер в секции/окне «Бюджеты» (`:130-135`) — без Δ сверх санкционированного каталогом.
- [x] **T-2365** [@Builder] Тесты: (a) дефолт **ON** (поведение байт-в-байт как прежде); (b) **OFF** → бюджеты не ограничивают, бот **не** уходит в `content.no_key_reply`; (c) OFF **per-chat** vs OFF **глобально** (приоритет per-chat override); (d) при OFF счётчики usage продолжают расти; (e) fail-open: недоступен резолв → ON; (f) `worker_budget.consume` при OFF не блокирует; (g) пин-тесты каталога/TAB_RULES обновлены.
- [x] **T-2366** [@Builder] **Разграничение с `flags.chat_context_budgets_enabled`** (`direct_chat_service.py:1142-1145`, `scripts/backfill_104_chat_flags.py`): зафиксировать иерархию (master OFF перекрывает; master ON не отменяет усечение контекста); тест на совместное состояние; не сломать существующий backfill.
- [ ] **T-2367** [@Reviewer] Ревью: OFF реально работает во всех трёх гейтах; нет регресса BYOK/sandbox; дефолт ON; разграничение двух флагов документировано; нет утечек секретов (R17).
- [ ] **T-2368** [@DevOps] Деплой + live: выключить/включить тумблер (глобально и для целевого чата) → проверить, что бюджеты применяются/не применяются и бот отвечает. Отчёт (без секретов).

## Критерии приёмки
- В «Модулях» у карточки «Бюджеты» есть рабочий master-тумблер; состояние сохраняется для глобально/выбранного чата.
- OFF → бюджеты **не ограничивают** ни direct-контур, ни фоновый; фраза-заглушка `content.no_key_reply` по причине бюджета не появляется.
- Дефолт ON; ошибка резолва флага → fail-open (как раньше).
- Разграничение master-тумблера и `flags.chat_context_budgets_enabled` зафиксировано и покрыто тестом.
- Полный pytest — 0 failed; `node --check web/app.js` — OK.

## Риски
- **R1 (Critical):** OFF отключает бюджеты слишком широко (обход BYOK/безопасности) → уточнение границ в ADR + тест (b/c).
- **R2 (High):** Δ каталога без санкции ломает `test_param_catalog`/freeze-меню → **Human Gate №1** + T-2361/T-2365(g).
- **R3 (High):** путаница master-тумблера с `flags.chat_context_budgets_enabled` → T-2366 + тест.
- **R4 (Medium):** per-chat vs global приоритет неверно реализован → тест (c).
- **R5 (Medium):** конфликт `web/app.js` с web-очередью раунда; `param_catalog.py` — ступень с F5/F6/F7 → согласовать очередь.
- **R6 (Low):** секреты в отчётах (R17/R18).

## Зависимости / ступени / раскатка
- Зависит от: **F20** (иначе настройка тумблера/значений будет затираться merge-багом).
- Ступень общих файлов: `web/api/routes.py` — F11 → F20; `services/param_catalog.py` — F5 → F6 → F7 → **F21**; `web/app.js` — web-очередь раунда → **F21**; `services/llm_client.py` — F1 → **F21**; `services/chat_usage.py`/`services/worker_budget.py` — **F21**.
- **Feature flag:** **`flags.budgets_enabled`** (каталоговый, default ON; он же и есть продуктовый тумблер).
- **Раскатка (прогрессивная):** возможна — `internal → 10% → 50% → 100%` через существующий механизм per-chat/global override; на прод-чате включение после live-проверки. Кill-switch — флаг OFF. Откат — флаг ON/`git revert`.
- **Δ DDL = 0.** **Δ каталога ≠ 0** — вынести в **Human Gate**.
