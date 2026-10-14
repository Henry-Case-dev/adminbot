# Аудит раунда 10.24 — F21 `budget-global-toggle-round1024` (шаг 5)

- **Ревьюер:** @Reviewer
- **Итерация 1:** коммит `4659173` (база `4659173^`) → `Changes Requested`.
- **Итерация 2 (актуальный статус):** коммит `d8e09a6` (база `d8e09a6^` = `cbc4f98`, F22 влит поверх F21 и **не приписывается** F21).
- **Спека/ADR/задачи:** `spec.md`, `ADR-1024-22.md`, `tasks.md` (T-2360…T-2368)
- **ТЗ:** `plans/current_task.md`, строка 404 (критический баг бюджетов; «добавить глобальный тумблер… и проверить чтобы эта настройка действительно работала»). Секреты не цитируются (R17/R18).

**Статус (итерация 2): Approved**

Все 4 findings итерации 1 закрыты. High устранён в коде и покрыт тестами; Medium (докконтракт) и оба Low закрыты. Полный `pytest -q` → **7560 passed, 0 failed**; JS-гейты (`round1024_budget_toggle_test.js` → `BUDGET-TOGGLE-OK`, `vue_mount_test.js`, `round1020_ui_test.js`) — зелёные; `node --check web/app.js` — OK; Δ каталога **459/98/96/20/418/434**, Δ DDL = 0; границы OFF, R16/17/18, `physical-two-call`, F20/F22 — не нарушены. Подробности — в разделе «Итерация 2» в конце документа.

---

## Findings

### [Severity: High — ЗАКРЫТ в итерации 2] `global_degradation_allows` не уважал master OFF — фон оставался под бюджетом

> Статус: **closed** (коммит `d8e09a6`). Master-гейт добавлен; см. «Итерация 2».

Итог итерации 1: тумблер собран аккуратно — единый резолвер `chat → global → default(True)` с fail-open ON, OFF-короткое замыкание в direct-снимке и в `consume` после UPSERT, master-AND в контекст-гейте, границы OFF (`allow_global`/BYOK/модель/`physical-two-call`) соблюдены, Δ каталога ровно по спеке, `web/api/routes.py` и `services/llm_client.py` не тронуты. **Но контракт «OFF = фон не ограничивает» не был выполнен**: enforcement-путь фона (`worker_budget.global_degradation_allows`) остался без master-гейта. Ниже — исходные findings итерации 1 (историческая запись), затем закрытие.

---

## Findings

### [Severity: High] `global_degradation_allows` не уважает master OFF — фон по-прежнему ограничивается бюджетом

- **Файл:** `services/worker_budget.py:167-181` (функция `global_degradation_allows`).
- **Точки вызова:** `services/dream_worker.py:105` и `:1777`, `services/lore_worker.py:99`, `services/nostalgia_worker.py:492`.
- **Проблема:** OFF-гейт добавлен только в `consume` (`worker_budget.py:226`). Воркеры же решают «идти ли в тик» ДО `consume` через `global_degradation_allows(worker_id)`, который читает `get_usage` (→ `_metric_limit`, флаг не спрашивает) и при `used_calls >= limit_calls` возвращает `False` → воркер скипает тик с логом «global budget exhausted — degradation». При master OFF `consume` всегда `True`, поэтому расход растёт и этот предохранитель сработает как обычно — фон встанет.
- **Почему это важно:** спека §4.1 (строка «global OFF … фон-контур: лимиты НЕ применяются»), §9 («OFF → direct и фон **не ограничивают**») и ADR-1024-22 D4 («OFF = прекращение enforcement») прямо обещают выключение фон-контура целиком. Требование владельца (`current_task.md:404`) — «отключает/включает бюджеты **целиком**». Фактически OFF выключает direct-контур и `consume`, но оставляет глобальную деградацию воркеров. Это скрытый, недокументированный в §4.3.2/ADR путь enforcement — тихий частичный отказ заявленной функции.
- **Дополнительно:** кейса «OFF + исчерпанный global-лимит → воркер допущен» нет ни в `tests/test_budget_global_toggle_round1024.py` (там только `consume`/`_metric_limit`), ни где-либо ещё — покрытие отсутствует.
- **Обязательный фикс (ровно один из двух, предпочтителен первый):**
  1. Добавить master-короткое замыкание в `global_degradation_allows` **до** чтения usage (это глобальный скоп, поэтому `chat_id=None`):
     ```python
     if not await budget_gate.budgets_enabled(None):
         return True
     ```
     и тест «master OFF + global cap 0/исчерпан → `global_degradation_allows("dream") is True`» в `tests/test_budget_global_toggle_round1024.py`.
  2. Либо явно зафиксировать в `ADR-1024-22` (D4/§3 Negative) и `spec.md` §4.3.2/§4.1, что деградация воркеров — НЕ бюджет и master OFF её не снимает; при этом §9 и формулировку «OFF → фон не ограничивают» привести в соответствие. Без правки кода/доков фича не соответствует спеке.

### [Severity: Medium] Документная дыра: ADR/spec перечисляют не все enforcement-точки фона

- **Файл:** `plans/features/budget-global-toggle-round1024/spec.md:125-130` (§4.3.2) и `ADR-1024-22.md:52-58` (D4).
- **Проблема:** §4.3.2/ADR D4 описывают OFF только для `consume` и `_metric_limit`, но в модуле `worker_budget` есть второй потребитель лимитов — `global_degradation_allows` (`worker_budget.py:167-181`), который вызывается воркерами ДО `consume`. Именно из-за этой дыры в контракте реализация «почти совпала» со спекой.
- **Почему это важно:** неполный контракт = неполный enforcement OFF; в следующем раунде любой новый вызов `global_degradation_allows`/`allowed_workers` снова протащат бюджет мимо master-флага.
- **Обязательный фикс:** в §4.3.2 и ADR D4 явно перечислить **все** enforcement-точки фона (`consume`, `_metric_limit`, `global_degradation_allows`/`allowed_workers`) и указать, какая из них гейтится master-флагом. Закрывается вместе с High-фиксом.

### [Severity: Low] JS-тест заявляет в комментарии проверку `TAB_RULES = 20`, но её не выполняет

- **Файл:** `tests/js/round1024_budget_toggle_test.js:3-9, 95-101`.
- **Проблема:** шапка обещает «новых вкладок нет (TAB_RULES = 20, состав tabs не изменился)», однако блок 3 проверяет лишь уникальность `id`, наличие `mod_budgets` и (через Python-тест) факт — но **количества** вкладок не ассертит. `data.tabs.length === 20` отсутствует.
- **Почему важно:** `tma-menu-freeze` — инвариант приёмки; без счётчика тест не поймает случайное +1 вкладки. Комментарий, обещающий больше, чем проверяет код, — это ложная гарантия.
- **Обязательный фикс:** добавить `assert.strictEqual(data.tabs.length, 20, 'tma-menu-freeze: вкладок 20');` либо убрать `TAB_RULES = 20` из комментария.

### [Severity: Low] Докстринг `budget_gate` обещает лог `key/chat/source`, логируется только `chat`

- **Файл:** `services/budget_gate.py:11-13, 40-43`.
- **Проблема:** шапка модуля заявляет «логируется только `key`/`chat`/`source`», а в `except` пишется лишь `chat=%s`. `source` (и сам `key`) не логируются — диагностика fail-open беднее заявленной.
- **Почему важно:** при расследовании «почему тумблер не применился» нужен именно `source` (`chat|global|default`). Некритично, но расхождение кода и документации модуля.
- **Обязательный фикс:** либо логировать `source` (через `resolve_setting_with_source`), либо поправить докстринг до фактического поведения. R17 не нарушается ни в одном варианте.

---

## Контракт: чекбоксы spec §4 / tasks.md

### Тумблер и UI (spec §2, §6; ADR D7)
- [x] Ключ `flags.budgets_enabled` (`param_catalog.py:968-972`, `BUDGETS_ENABLED`, group `flags_module_budgets`, bool, default True).
- [x] Группа `flags_module_budgets` (`param_catalog.py:335-338`, order 21).
- [x] Карточка `mod_budgets`: `noToggle` снят, добавлен `toggleKey: 'flags.budgets_enabled'` (`web/app.js:394-396`); фактических `noToggle:` в `MODULES` — 0.
- [x] Новых вкладок/карточек нет: `mod_budgets` в `TABS` получил source `flags_module_budgets` (`web/app.js:132-135`); `MODULES` — 12 карточек, `TAB_RULES`/`TAB_NAV`/`CONFIG_TAB_TITLES` — 20.
- [x] Сохранение — штатным `saveConfigItem` (`global:item.per_chat===false`, для flags per_chat=true → per-chat + `X-Chat-Id`; без чата — global), F20-ветки не вводились.
- [x] Прав на ключ достаточно: `default_matrix` для category flags → `edit_roles=[local_admin]`, владелец/global admin редактирует (`services/access.py:209-226,288-308`).

### Резолвер (spec §4.2; ADR D3)
- [x] Единая точка `services/budget_gate.py::budgets_enabled(chat_id)`.
- [x] Приоритет `chat → global → default(True)` через `resolve_setting_cached`.
- [x] Fail-open ON при ошибке резолва (`budget_gate.py:39-44`); тест `test_fail_open_on_error`.
- [x] `chat_id=None` (скоп `'global'`) видит только глобальный слой; `_scope_chat_id` корректно парсит `chat:<id>`/`global`.
- [x] Секретов не читает/не логирует (R17).

### OFF = enforcement off, учёт ведётся (spec §4.1, §4.4; ADR D4)
- [x] `worker_budget.consume`: UPSERT **до** гейта, при OFF `return True` (`worker_budget.py:214-227`); счётчик растёт — тест `test_off_allows_and_records`.
- [x] `chat_usage.budget_snapshot`: при OFF `exceeded=False`, `exceeded_metric=None`, добавлен аддитивный `budgets_enabled` (R16), `used_*`/`limit_*`/`forbidden` фактичны (`chat_usage.py:176-264`).
- [x] `llm_client` не тронут: ветка `if snapshot["exceeded"]` получает `False` транзитивно (`llm_client.py:404-421`); тест `test_off_returns_global_key_not_budget`.
- [x] `direct_chat_service._build_user_content`: `budgets_enabled = master AND context-флаг` (`:1147-1152,1168`); тесты `test_master_*`.
- [x] `flags.chat_context_budgets_enabled` перекрывается master OFF — тест `test_master_off_overrides_context_on`.
- [x] `/api/config`-путь (F20) и `web/api/routes.py` не изменены.
- [ ] **Фон целиком:** `global_degradation_allows` НЕ гейтится master-флагом — **нарушено** (см. High).

### Границы OFF (spec §1, §8-R1; ADR D6)
- [x] `keys.allow_global=false` сохраняется → `NoApiKeyForChat('forbidden')` — тест `test_off_does_not_bypass_allow_global_forbidden`.
- [x] BYOK/выбор провайдера/модели не затронуты (диффа нет).
- [x] `physical-two-call`: LLM-конвейер не переписан, `llm_client` не менялся.
- [x] `tma-menu-freeze`: новых пунктов/вкладок/карточек нет (счётчики подтверждены рантаймом).

### Δ каталога (spec §3; ADR D8) — рантайм-сверка
- [x] `REGISTRY` 458→**459**, `GROUPS` 97→**98**, `_TAB_BY_GROUP` 95→**96**, Settings 417→**418**, categorized 433→**434**, flags-групп 20→**21**.
- [x] `TAB_RULES` 20→**20**, `CONFIG_TAB_TITLES`/`TAB_NAV` **20** (новых вкладок нет).
- [x] `toggleKey:` в `MODULES` 11→**12**, карточек **12**.
- [x] Δ DDL = 0 (новый ключ — строка `bot_settings` авто-сидом из REGISTRY; таблицы/миграции не менялись).
- [x] Все 17 пин-файлов обновлены в **одном** коммите (§7.1), комментарии содержат историю дельт.

### Тесты (spec §7; tasks T-2365)
- [x] (a) дефолт ON — `test_default_on*/test_on_*`.
- [x] (b) OFF глобально → не ограничивает, учёт цел, sandbox `budget` не появляется.
- [x] (c) OFF per-chat vs global, per-chat приоритетнее — `test_per_chat_overrides_global`, `test_per_chat_off_only_for_that_chat`, `test_off_per_chat_scope`.
- [x] (d) статистика при OFF (UPSERT + `report_call`) — `test_off_allows_and_records`, `test_report_call_writes_off`.
- [x] (e) fail-open ON — `test_fail_open_on_error`.
- [x] (f) фон: `consume` при `0`/OFF и «`_metric_limit` не вызывается при OFF» — корректно.
- [x] (g) master-приоритет над context-флагом — все три комбинации.
- [x] (h) каталог — ключ/группа/вкладка/счётчики.
- [x] (i) `allow_global=false` не обходится OFF.
- [x] Тесты не тавтологичны: `test_off_skips_metric_limit` (raise при вызове), `test_off_allows_and_records` (проверка фактического UPSERT), `test_master_*` (захват `enabled`).
- [ ] **OFF фона на уровне деградации воркеров** — покрытие отсутствует (см. High/Medium).

### Инварианты/приёмка
- [x] Полный pytest — **7539 passed, 0 failed** (заявленное 7539 подтверждено).
- [x] `node --check web/app.js` — OK; JS-тесты зелёные.
- [x] `git diff --check` — чисто.
- [x] R16 (аддитивность), R17/R18 (секреты), `physical-two-call`, `tma-menu-freeze` — соблюдены.
- [ ] §9 «OFF → direct и фон не ограничивают» — **не выполнено** из-за `global_degradation_allows`.

---

## Если Changes Requested — точный список

1. `services/worker_budget.py::global_degradation_allows` — добавить master-гейт `if not await budget_gate.budgets_enabled(None): return True` **до** чтения usage (fail-open: ошибка резолва → ON), чтобы OFF действительно выключал фон целиком.
2. `tests/test_budget_global_toggle_round1024.py` — добавить кейс: master OFF + исчерпанный/`0` global worker-лимит → `global_degradation_allows("dream") is True` (и master ON + cap → `False`, чтобы не сломать деградацию).
3. `spec.md` §4.3.2/§4.1 и `ADR-1024-22` D4 — перечислить **все** enforcement-точки фона (`consume`, `_metric_limit`, `global_degradation_allows`/`allowed_workers`) и их связь с master-флагом; либо (если решение владельца — оставить деградацию) явно вывести деградацию из-под OFF и привести §9 в соответствие.
4. `tests/js/round1024_budget_toggle_test.js` — либо ассертить `data.tabs.length === 20` (инвариант `tma-menu-freeze`), либо убрать недостоверное утверждение `TAB_RULES = 20` из комментария.
5. `services/budget_gate.py` — привести докстринг к факту (залогировать `source` или убрать обещание `key/source`).

После п.1–2 повторно прогнать полный pytest (ожидается 7539 + 1 новый = 7540+) и JS-тесты.

_Примечание: Context7 для данного ревью неприменим — новых сторонних зависимостей/API-библиотек коммит не вводит (изменения только в собственном коде и тестах), а инструмент по своему назначению предназначен для документации библиотек, а не для код-ревью. CVE-проверка не требуется (Δ зависимостей = 0)._

---

# Итерация 2 — коммит `d8e09a6` (база `d8e09a6^` = `cbc4f98`)

**Статус: Approved.** Все 4 findings итерации 1 закрыты по существу; новых дефектов не внесено.

## Артефакты и границы ревью

- `git show d8e09a6 --stat`: 4 файла, +79/−4 — `services/budget_gate.py` (+4/−1), `services/worker_budget.py` (+9/−1), `tests/js/round1024_budget_toggle_test.js` (+7/−1), `tests/test_budget_global_toggle_round1024.py` (+61). **Δ DDL = 0.**
- Верхушка `d8e09a6` — ребёнок `cbc4f98` (F22). F22 влит **поверх** F21 и относится к ремонту seed-overrides/manage-CLI — изменениям F21 не приписываются; конфликтов не создаёт (полный прогон зелёный).
- `spec.md`/`ADR-1024-22.md` в этом репозитории **не трекаются git** (вся папка фичи `?? untracked`), поэтому их правки не попадают в `--stat` коммита — проверены чтением файлов на диске.

## Закрытие findings итерации 1

### [High] `global_degradation_allows` — ЗАКРЫТ

- **Файл:** `services/worker_budget.py:167-176` — добавлено короткое замыкание ДО чтения usage:
  ```python
  if not await budget_gate.budgets_enabled(None):
      return True
  ```
  Скоп — `chat_id=None` (глобальный слой), что корректно: предохранитель деградации глобальный.
- **Fail-open сохранён:** ошибка резолва внутри `budget_gate.budgets_enabled` → `True` → условие `not True` = `False` → деградация работает как прежде (enforcement как раньше, spec §4.2/§4.1).
- **`allowed_workers`** отдельного гейта не требует — в проде вызывается только из `global_degradation_allows` (grep: `services/worker_budget.py:180` и тесты); при master OFF до него не доходит. Проверено.
- **Покрытие (4 новых теста, не тавтологичны):**
  - `test_off_frees_background_even_when_exhausted` — OFF + `used=100/limit=60` → `True` для dream/lore/nostalgia. На коде без гейта тест падал бы (`False`) → доказателен.
  - `test_off_zero_limit_still_allows` — OFF + `0`-sentinel → `True`.
  - `test_on_degrades_when_exhausted` — ON + исчерпание → `False`; плюс проверка границы матрицы `allowed_workers(("dream","lore","nostalgia"),60,60) == {dream:False, lore:True, nostalgia:True}` — прежнее поведение не сломано.
  - `test_off_does_not_read_usage` — OFF → `get_usage` не вызывается (raise при вызове).

### [Medium] Докконтракт — ЗАКРЫТ

- **`spec.md:92-94`** — добавлено определение: «фон-контур» = весь `worker_budget`-enforcement (`consume`, `_metric_limit`, `global_degradation_allows`/`allowed_workers`); «при master OFF воркеры не скипают тики по budget exhausted».
- **`spec.md:135-140`** — новый п.3 §4.3.3 с точным гейтом `budgets_enabled(None)` до чтения usage и обоснованием, почему `allowed_workers` отдельного гейта не требует.
- **`ADR-1024-22.md:52-61`** — D4 расширен таблицей всех enforcement-точек фона и поведением при OFF.
- Правки соответствуют фактическому коду `d8e09a6` (сверено построчно).

### [Low] JS-тест `TAB_RULES` — ЗАКРЫТ

- **`tests/js/round1024_budget_toggle_test.js:101-104`** — добавлен реальный ассерт `assert.strictEqual(data.tabs.length, 25, 'tma-menu-freeze: вкладок 25')`; комментарии исправлены (число заморожено 25, включая 5 неконфиг-вкладок; Python-инвариант `TAB_RULES = 20` — пинами pytest).
- **Факт подтверждён рантаймом:** число `id` в JS `TABS` = **25**; `len(pc.TAB_RULES)` = **20** (неконфиг-вкладки в `TAB_RULES` не входят). Ассерт корректен.

### [Low] Докстринг `budget_gate` — ЗАКРЫТ

- **`services/budget_gate.py:10-15`** — докстринг приведён к факту: успешный резолв оставляет debug-лог `[settings] key/chat/source` внутри `resolve_setting_cached`; при ошибке — WARNING с `chat`; значения/секреты не логируются. Соответствует реализации (R17 сохранён).

## Инварианты и прогоны (итерация 2)

- [x] Полный `pytest -q` → **7560 passed, 0 failed** (заявленное 7560 подтверждено).
- [x] `node --check web/app.js` → OK; `round1024_budget_toggle_test.js` → `BUDGET-TOGGLE-OK`; `vue_mount_test.js` → `VUE-MOUNT-OK`; `round1020_ui_test.js` → `JS-UNIT-OK`.
- [x] Δ каталога (рантайм): `REGISTRY` **459**, `GROUPS` **98**, `_TAB_BY_GROUP` **96**, `TAB_RULES` **20**, Settings **418**, categorized **434** — ровно по spec §3/D8.
- [x] Δ DDL = 0 (миграции/таблицы не менялись).
- [x] R16 (аддитивность), R17/R18 (секреты), `physical-two-call` (`llm_client.py` не менялся), `tma-menu-freeze` (карточек 12, вкладок 25 заморожено, `TAB_RULES` 20) — соблюдены.
- [x] F20 (`test_budget_overrides_merge_round1024`) и F22 — зелёные в полном прогоне; `web/api/routes.py` не изменялся.
- [x] §9 «OFF → direct и фон не ограничивают» — **выполнено**: `budget_snapshot` (direct), `consume` (учёт+cap) и `global_degradation_allows` (деградация) все уважают master-флаг.

**Итог: Approved.** Блокирующих дефектов нет. Коммит `d8e09a6` можно двигать дальше (T-2368 @DevOps — live-проверка тумблера на целевом чате).

__ **Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.__
