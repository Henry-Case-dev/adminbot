# Spec: budget-global-toggle-round1024 (F21)

> Раунд 10.24 (UPD5) · **P0/Critical** · каталог + backend-гейты + UI (master-рубильник бюджетов)
> **Владелец фичи:** F21. **ADR:** `ADR-1024-22` (AMEND ADR-1019-3 / ADR-1019-8 / ADR-1019-2).
> **Baseline:** HEAD `a406440` (прод `4314ea4`). Каталог сверен рантайм-прогоном.
> **Ступень общих файлов:** `services/param_catalog.py` — F5 → F6 → F7 → **F21**;
> `web/app.js` — web-очередь → **F21**; `services/llm_client.py` — F1 → **F21**;
> `services/chat_usage.py` / `services/worker_budget.py` — **F21**.
> **Связанные фичи:** F20 (предпосылка — merge per-chat не затирает значения, влит `070f31c`),
> F22 (разграничение/разбор с `flags.chat_context_budgets_enabled`), F23 (пин-тесты каталога/TAB_RULES).
> **Gate G (санкции владельца):** (1) новый ключ `flags.budgets_enabled` + группа каталога — **РАЗРЕШЕНО**;
> (2) OFF = бюджеты не считают и не ограничивают, **статистика ведётся**; (3) master-тумблер **приоритетен**,
> перекрывает `flags.chat_context_budgets_enabled`; (4) область — global + per-chat, per-chat override приоритетнее;
> (5) дефолт **ON**.

## 1. Цель

Дать владельцу **один master-рубильник бюджетов** на существующей карточке «Бюджеты» (`mod_budgets`)
в разделе «Модули»: включение/выключение бюджетов **целиком** — глобально ИЛИ для выбранного чата.
Сейчас карточка помечена `noToggle: true` (`web/app.js:393-395`) и не имеет master-флага; OFF-гейтов нет.

**Границы (что tумблер НЕ делает):**
- OFF **не** отменяет `keys.allow_global=false` (это право BYOK/доступа, а не бюджет);
- OFF **не** трогает BYOK-ключи, выбор провайдера/модели, `physical-two-call`;
- OFF **не** удаляет и **не** перестаёт писать счётчики usage (статистика ведётся всегда);
- OFF **не** снимает per-block потолки контекста как отдельный слой — он добавляет master-AND поверх
  контекстного гейта (owner #3: перекрывает `flags.chat_context_budgets_enabled`, см. §4.3).

## 2. Что уже есть (координаты, подтверждены рантаймом)

| Что | Где | Факт |
|---|---|---|
| Карточка «Бюджеты» без тумблера | `web/app.js:393-395` | `{ id:'mod_budgets', …, noToggle: true, tab:'mod_budgets' }` |
| Секция карточки (лимиты) | `web/app.js:130-135` | `sources:[{category:'limits', groups:['limits_chat_key','limits_chat_context','limits_worker']}]` |
| Механика тумблеров | `web/app.js:356-395` (`MODULES`), `:3153-3174` (`canEditModule`/`moduleEnabled`/`toggleModule`), `:4409-4478` (`saveConfigItem`) | card-toggle работает только при наличии `toggleKey` и отсутствии `noToggle` |
| Рендер тумблера в меню «Модули» | `web/index.html:934-938` | `v-if="m.noToggle"` → бейдж «лимиты», иначе `<input type=checkbox>` |
| Вкладка `mod_budgets` (Python) | `services/param_catalog.py:1976, 1999, 2042, 2117-2120` | title «Бюджеты», nav `modules`, rule = только `limits_chat_key/limits_chat_context/limits_worker` |
| Группа-образец модуля | `services/param_catalog.py:290-334` | `flags_module_*`, порядок в категории 1..20; `flags_module_images` = 20 |
| Ключ-образец флага | `services/param_catalog.py:959-960` | `IMAGE_GENERATION_MODULE_ENABLED` → `flags.image_generation_module_enabled`, default True |
| Резолвер-образец per-chat | `services/image_generation.py:131-148` | `resolve_module_enabled` (override → hot → default, fail-open) |
| Единый резолв настроек | `services/worker_settings.py:123-150` | `resolve_setting(_cached)`: `chat → global → default`, fail-open |
| Снимок бюджета direct | `services/chat_usage.py:194-258` | `budget_snapshot` → `_exceeds` → `exceeded/exceeded_metric` |
| Обёртка | `services/chat_usage.py:252-258` | `budget_exceeded` = `snapshot["exceeded"]` |
| Фон-бюджет | `services/worker_budget.py:201-227` (`consume`), `:260-278` (`_metric_limit`) | UPSERT пишется **до** проверки лимита; `False` = стоп |
| Sandbox-триггер | `services/llm_client.py:404-420` | `if snapshot["exceeded"]: … raise NoApiKeyForChat('budget')` |
| Фраза-заглушка | `services/sandbox_reply.py:8-11` → `direct_chat_service.py:767-781` | `content.no_key_reply` |
| Соседний (другой!) гейт | `services/direct_chat_service.py:1141-1145`, `:1595-1598` | `flags.chat_context_budgets_enabled` — усечение контекста, НЕ master |
| Сид целевого чата | `scripts/backfill_104_chat_flags.py` | ставит `flags.chat_context_budgets_enabled=false` целевому чату |
| Авто-сид нового ключа | `services/pg_db.py:406-409, 560-582` | `INSERT … ON CONFLICT DO NOTHING` из REGISTRY (Δ DDL = 0) |
| F20 write-path | `web/api/routes.py:479-529` (merge от `root["overrides"]`) | **НЕ ломать** |

**Рантайм-сверка (baseline, до F21, после F7):**
`REGISTRY=458`, `GROUPS=97`, `_TAB_BY_GROUP=95`, `TAB_RULES=20`, `CONFIG_TAB_TITLES=20`,
`TAB_NAV=20`, Settings-полей `417`, categorized `433`, flags-групп `20`, JS-витрина `12`,
`toggleKey:` в `MODULES` = `11` (`flags.budgets_enabled` отсутствует, `mod_images`/F5 ещё не влит).

## 3. Δ каталога (точно, санкция owner #1)

| Метрика | Было | Стало | Δ |
|---|---:|---:|---:|
| `REGISTRY` | 458 | **459** | +1 (`BUDGETS_ENABLED`) |
| `GROUPS` | 97 | **98** | +1 (`flags_module_budgets`) |
| `_TAB_BY_GROUP` (mapped) | 95 | **96** | +1 |
| Settings-полей | 417 | **418** | +1 |
| categorized | 433 | **434** | +1 |
| `TAB_RULES` | 20 | **20** | 0 (вкладка не создаётся) |
| `CONFIG_TAB_TITLES` / `TAB_NAV` | 20 | **20** | 0 |
| JS-витрина `MODULES` | 12 | **12** | 0 (карточка уже есть) |
| `toggleKey:` в `MODULES` | 11 | **12** | +1 |
| flags-группы | 20 | **21** | +1 |

> **Ступенчатая поправка:** если к моменту F21 уже влит **F5** (`mod_images`, `+1` config-вкладка,
> `+1` карточка, `+1` toggleKey → `TAB_RULES=21`, витрина `13`, `toggleKey=12`), то итог F21 = **21 вкладка,
> 13 карточек, `toggleKey=13`**. Δ самого F21 неизменен: `+1 REGISTRY/GROUPS/mapped/Settings/categorized`,
> `+0` вкладок/карточек. @Builder обязан взять актуальный baseline из рантайма (`len(pc.REGISTRY)` и т.п.)
> и подставить фактические числа — **все пины обновляются в том же коммите** (§7).

## 4. Требуемое поведение

### 4.1. Матрица ON/OFF × global/chat

| `flags.budgets_enabled` (резолв для scope) | direct-контур (`chat_usage`/`llm_client`) | фон-контур (`worker_budget`) | контекст (`_apply_context_budget`) | usage-статистика |
|---|---|---|---|---|
| **global ON** (дефолт) + chat без override | как прежде: лимиты и `0`=запрет применяются | как прежде | `flags.chat_context_budgets_enabled` решает | пишется |
| **global OFF**, chat без override | лимиты НЕ применяются; sandbox `reason=budget` не появляется | лимиты НЕ применяются | усечение выключено | **пишется** |
| global ON, **chat override ON** | применяются (chat приоритетнее) | применяются | решает context-флаг (master ON) | пишется |
| global ON, **chat override OFF** | не применяются для этого чата | не применяются | усечение выключено для чата | **пишется** |
| **global OFF, chat override ON** | применяются (per-chat override приоритетнее) | применяются | решает context-флаг (master ON для чата) | пишется |
| **global OFF, chat override OFF** | не применяются | не применяются | усечение выключено | **пишется** |
| резолв недоступен (PG/кэш/мусор) | **fail-open → ON** (как прежде) | ON | ON | пишется |

> «фон-контур» в таблице — это **весь** `worker_budget`-enforcement: `consume`, `_metric_limit` и
> предохранитель деградации `global_degradation_allows`/`allowed_workers` (см. §4.3.2–§4.3.3).
> При master OFF воркеры не скипают тики по «global budget exhausted».

### 4.2. Контракт резолва (единая точка)

Вводится **единственный** резолвер в новом модуле `services/budget_gate.py`:

```python
KEY_BUDGETS_ENABLED = "flags.budgets_enabled"   # pg_key

async def budgets_enabled(chat_id: int | None = None) -> bool:
    """Master-рубильник бюджетов.
    Приоритет: chat override → global (hot) → default settings.BUDGETS_ENABLED (True).
    Fail-open: любая ошибка резолва → True (поведение как прежде).
    chat_id=None → только global/default (фон-скоп 'global')."""
```

- Реализация — через `worker_settings.resolve_setting_cached(KEY, chat_id=chat_id, default=settings.BUDGETS_ENABLED)`
  (`chat → global → default`, кэши `ChatParamsCache`/`ConfigCache`, без PG-раундтрипа в горячем цикле),
  обёрнутая в `try/except → True`. **Секретов не читает** (R17).
- `True` = бюджеты включены, `False` = master OFF.
- Модуль **чистый по зависимостям**: импортирует `config.settings` и `services.worker_settings`; его импортируют
  `chat_usage`, `worker_budget`, `direct_chat_service` (циклов нет).

### 4.3. Short-circuit (где именно OFF обрывает проверку)

1. **`services/chat_usage.py::budget_snapshot` (единственная точка direct-контура).**
   В начале: `master_on = await budget_gate.budgets_enabled(chat_id)`.
   Лимиты и usage читаются **как обычно** (диагностика/статистика сохраняются), но при `master_on is False`
   `exceeded=False`, `exceeded_metric=None` (проверка `_exceeds`/`forbidden` **не** даёт стоп).
   В возвращаемый dict добавляется **аддитивный** ключ `"budgets_enabled": bool` (R16; существующие ключи не
   переименовываются/не удаляются). `forbidden`/`unlimited`/`source`/`used_*`/`limit_*` остаются фактическими
   для UI/Сводки, но enforcement выключен.
   → `budget_exceeded` и `llm_client._resolve_api_key_and_source` получают `exceeded=False` **транзитивно**:
   явная правка `llm_client.py` **не требуется** (ветка `if snapshot["exceeded"]` не срабатывает).
   Двойной резолв флага в `llm_client` **не** добавляем (риск лишнего I/O и рассинхрона).
2. **`services/worker_budget.py::consume`.**
   UPSERT счётчика выполняется **первым** (статистика всегда пишется). Сразу после успешного UPSERT:
   `if not await budget_gate.budgets_enabled(_scope_chat_id(scope)): return True`.
   Иначе — прежняя логика (`budget_limits.is_forbidden`/`is_unlimited`/cap). `scope='global'` → `chat_id=None`
   (глобальный слой), `scope='chat:<id>'` → per-chat override.
   `_metric_limit` при OFF **не вызывается** (нет резолва лимита — стоп невозможен).
3. **`services/worker_budget.py::global_degradation_allows` (предохранитель деградации фона).**
   Воркеры (`dream_worker`, `lore_worker`, `nostalgia_worker`, deep-sleep) решают «идти ли в тик» **до**
   `consume` через эту функцию. В начале — `if not await budget_gate.budgets_enabled(None): return True`
   (глобальный скоп → `chat_id=None`) **до** чтения usage, иначе OFF оставлял бы фон под деградацией.
   `allowed_workers` — чистый (sync) помощник, в проде вызывается только из `global_degradation_allows` и
   отдельного гейта не требует: при master OFF до него дело не доходит.
4. **`services/direct_chat_service.py::_build_context`.**
   `budgets_enabled = (await budget_gate.budgets_enabled(chat_id)) and bool(<резолв flags.chat_context_budgets_enabled>)`;
   вычисленное значение передаётся в `_apply_context_budget(blocks, budgets_enabled, budget_tokens)` как сейчас
   (`:1141-1161`). При master OFF контекст-усечение выключено, даже если `flags.chat_context_budgets_enabled=true`
   (owner #3). При master ON поведение ровно как прежде (context-флаг решает).
   Единственный production-call-site `_apply_context_budget` уже передаёт `enabled` — fallback `enabled=None`
   (тесты/легаси) **не трогаем** (там остаётся только context-флаг; master по умолчанию ON).
5. **`services/llm_client.py:404-420`** — код не меняется: `snapshot["exceeded"]` уже с учётом OFF.
   `NoApiKeyForChat('forbidden')` при `keys.allow_global=false` сохраняется (это НЕ бюджет, см. §1/§8-R1).

### 4.4. Статистика при OFF (инвариант)

- `worker_budget.consume` пишет `bot_usage_daily` (UPSERT) **до** гейта → счётчики растут и при OFF.
- `chat_usage.report_call` (вызовы+токены) — отдельный write-path, гейтом OFF **не** затрагивается:
  `llm_client._record_global_usage` (`:446-463`) продолжает писать.
- `budget_snapshot` при OFF по-прежнему возвращает фактические `used_calls/used_tokens` — дашборд/Сводка не «слепнут».

## 5. Изменения по файлам

| Файл | Что делать |
|---|---|
| **`services/budget_gate.py`** (новый) | §4.2: `KEY_BUDGETS_ENABLED`, `async budgets_enabled(chat_id)`, fail-open ON, R17-safe WARNING. |
| **`services/param_catalog.py`** | (1) `GroupSpec("flags_module_budgets", "flags", "Модуль: Бюджеты", "<desc>", 21)` в блоке flags; (2) в `_FLAGS` запись `("BUDGETS_ENABLED", "Главный тумблер бюджетов", "flags_module_budgets", "<desc>")`; (3) в `TAB_MOD_BUDGETS` rule добавить `(CATEGORY_FLAGS, frozenset({"flags_module_budgets"}))`. **Новых вкладок нет.** |
| **`config/settings.py`** | `BUDGETS_ENABLED: bool = _env_bool("BUDGETS_ENABLED", True)` рядом с `CHAT_CONTEXT_BUDGETS_ENABLED` (`:1063`). |
| **`.env.example`** | `BUDGETS_ENABLED=True` после `CHAT_CONTEXT_BUDGETS_ENABLED=True` (`:587`) — консистентность, без секретов. |
| **`web/app.js`** | (1) `mod_budgets` (`:393-395`): убрать `noToggle: true`, добавить `toggleKey: 'flags.budgets_enabled'`; (2) в `TABS` `mod_budgets` (`:130-135`) добавить source `{ category:'flags', groups:['flags_module_budgets'] }` (зеркало Python-rule для секции). `MODULES`/`TABS`/`EXPECTED_TABS` состав и порядок не менять. |
| **`services/chat_usage.py`** | §4.3.1: OFF short-circuit + аддитивный `budgets_enabled` в snapshot. |
| **`services/worker_budget.py`** | §4.3.2: OFF short-circuit после UPSERT. |
| **`services/direct_chat_service.py`** | §4.3.3: master-AND в `_build_context` (`:1139-1145`). |
| **`services/llm_client.py`** | Изменений нет (транзитивно). Не добавлять двойной резолв. |
| **`web/api/routes.py`** | **Не трогать** (F20 write-path). Новый ключ идёт обычным `POST /api/config` (+`X-Chat-Id`). |
| **тесты** | §7 (пины + новые тесты). |

## 6. UI

- В меню **«Модули»** карточка «Бюджеты» получает **рабочий switch** (снимаем `noToggle`): рендер
  `web/index.html:936-938` (`moduleEnabled`/`toggleModule`/`canEditModule`).
- Тумблер автоматически **global/per-chat**: `saveConfigItem` шлёт `global: item.per_chat === false`; для
  `flags.*` `per_chat=true`, поэтому при выбранном чате идёт per-chat override (+`X-Chat-Id`), без чата — global
  (`web/app.js:4451-4461`). Никаких новых веток сохранения не вводить (F20-путь обязателен).
- Флаг входит в `sources` вкладки `mod_budgets` → в окне «Бюджеты» появляется generic-чекбокс в группе
  «Модуль: Бюджеты».
- `tma-menu-freeze`: **новых пунктов/вкладок/карточек нет** — только тумблер на существующей карточке.
- Иконки/шрифт/навигация не меняются.

## 7. План тестов

### 7.1. Обновление пинов (в **одном** коммите)
Все `458→459`, `97→98`, `95→96`, `417→418`, `433→434` (с учётом baseline §3):

1. `tests/test_budget_settings_round1019.py` (L37-45) + `test_budgets_tab_composition` (L58-60): +`flags_module_budgets`.
2. `tests/test_frontend_tab_mapping.py` (L138-140) + `test_mod_budgets_composition` (L195-199).
3. `tests/test_help_guide_round1014.py` (L205-212).
4. `tests/test_param_catalog.py` (L91, L305).
5. `tests/test_round106_ia_smoke.py` (L39-43) + `test_modules_exactly_11` `toggleKey: == 11 → 12` (L115).
6. `tests/test_self_reflection_provider_round1014.py` (L73-80).
7. `tests/test_settings_persistence_round1014.py` (L44-51).
8. `tests/test_ui_verbilizer_tabs_round1023.py` (L81-84).
9. `tests/test_webapp_api.py` (L1391: `len(items)==len(categorized)==434`).
10. `tests/test_webapp_parity_smoke.py` (L57-61).
11. `tests/test_webapp_round1010_ui.py` (L187-191).
12. `tests/test_webapp_round1011_ui.py` (L147-151).
13. `tests/test_webapp_round1012_ui.py` (L192-199).
14. `tests/test_webapp_round1013_ui.py` (L35-42).
15. `tests/test_webapp_round1014_ui.py` (L38-45).
16. `tests/test_webapp_round1020_ui.py` (L237-238).
17. `tests/test_webapp_round109_ui.py` (L217-221).

> `test_orders_unique_within_category` требует уникальный `(flags, 21)` — свободен.
> `test_tabs_ids_and_order_unchanged`/`test_navbar_unchanged` (`len(mods)==12`) — **не меняются** (новых вкладок/карточек нет).

### 7.2. Новые тесты (`tests/test_budget_global_toggle_round1024.py`)
- **(a) Дефолт ON:** `resolve_setting`/`budget_gate.budgets_enabled` при пустых слоях → `True`; `budget_snapshot`
  при cap+usage сверх лимита → `exceeded=True` (поведение байт-в-байт как прежде).
- **(b) OFF глобально:** `flags.budgets_enabled=false` в глобальном слое → `budget_snapshot.exceeded is False`,
  `budgets_enabled is False`, `used_*` сохранены; `budget_exceeded` → `False`;
  `llm_client._resolve_api_key_and_source` возвращает `('global' key, 'global')`, **не** `NoApiKeyForChat('budget')`
  (тест-паттерн `test_budget_unlimited_round1019`).
- **(c) OFF per-chat vs global:** global ON + chat override false → OFF для чата, ON для другого чата;
  global OFF + chat override true → ON для чата (per-chat приоритетнее).
- **(d) Статистика при OFF:** `worker_budget.consume` при OFF → `True` **и** выполнен UPSERT (fake pool ловит
  `UPSERT_SQL`); `chat_usage.report_call` пишет `register_usage` и при OFF.
- **(e) Fail-open:** резолвер бросает/слой недоступен → `budgets_enabled is True` (enforcement как прежде).
- **(f) Фон:** `_metric_limit` при `0` (forbidden) даёт `consume=False` при master ON; при master OFF → `True`.
- **(g) Master приоритет над context-budgets:** master OFF + `flags.chat_context_budgets_enabled=true` →
  `_build_context` передаёт `budgets_enabled=False` (контекст не режется); master ON + context false → `False`;
  master ON + context true → `True`.
- **(h) Каталог:** `get("BUDGETS_ENABLED").pg_key == "flags.budgets_enabled"`, group `flags_module_budgets`,
  default `True`; `group_tab("flags_module_budgets") == TAB_MOD_BUDGETS`; `tab_group_ids(TAB_MOD_BUDGETS)`
  содержит группу; счётчики §3.
- **(i) `allow_global=false` не обходится OFF:** право BYOK-запрета сохраняется (OFF не расширяет доступ).

### 7.3. JS
- `tests/js/round1024_budget_toggle_test.js` (новый): в `MODULES` карточка `mod_budgets` содержит
  `toggleKey: 'flags.budgets_enabled'` и **не** содержит `noToggle`; `modules.length === 12`;
  в `TABS` source `flags_module_budgets` присутствует.
- `node --check web/app.js`; `tests/js/vue_mount_test.js` зелёный; `tests/js/round1020_ui_test.js` (12 карточек) — без изменений.

## 8. Риски

| # | Риск | Ур. | Митигация |
|---|---|---|---|
| R1 | OFF отключает слишком широко (обходит BYOK/доступ) | **Critical** | §1 + §4.3.4: OFF снимает только бюджетные cap/`0`-sentinel/контекст; `allow_global=false`, ключи, провайдеры — не трогаются. Тест (i). |
| R2 | Массовый пин-каталог (17+ файлов) ломает прогон | High | Обновить все пины **одним коммитом** (§7.1); рантайм-сверка фактических чисел перед пушем. |
| R3 | Путаница master ↔ `flags.chat_context_budgets_enabled` | High | master-AND в `_build_context`; аддитивный `budgets_enabled`; тест (g); ADR §AMEND. |
| R4 | per-chat vs global приоритет | Medium | Единый `resolve_setting_cached`; тест (c). |
| R5 | Конфликт `param_catalog.py`/`web/app.js` с очередью раунда | Medium | Ступень F5→F6→F7→F21; согласовать порядок перед началом. |
| R6 | `tma-menu-freeze` | Low | Новых пунктов нет; тесты состава меню не меняются. |
| R7 | Двойной резолв флага в горячем пути | Low | Один резолвер; `llm_client` — транзитивно; кэши `worker_settings`. |
| R8 | Секреты в логах/отчётах | Low | R17: лог только `key/chat/source`, значений нет. |
| R9 | F20-путь сохранения сломан | High | `web/api/routes.py` не трогаем; прогон `test_budget_overrides_merge_round1024`. |

## 9. Критерии приёмки

- В «Модулях» у карточки «Бюджеты» есть рабочий master-тумблер; состояние сохраняется глобально и per-chat.
- OFF → direct и фон **не ограничивают**, фраза `content.no_key_reply` по причине бюджета не появляется.
- OFF → usage-счётчики **продолжают расти** (тест (d)).
- Дефолт **ON**; ошибка резолва → **fail-open ON**.
- master OFF перекрывает `flags.chat_context_budgets_enabled` (тест (g)); иерархия зафиксирована в ADR.
- Δ DDL = 0; Δ каталога = §3 (ровно +1 ключ / +1 группа / +1 mapped / +0 вкладок / +0 карточек).
- Полный pytest — **0 failed**; `node --check web/app.js` — OK; `git diff --check` чист.
- `tma-menu-freeze`, `physical-two-call`, R16/R17/R18 соблюдены.

## 10. Откат / Feature Flag / Progressive Delivery

- **Флаг = сам тумблер:** `flags.budgets_enabled` (каталоговый, default ON) — он же kill-switch.
- **Прогрессивная раскатка:** global ON by default → включение OFF сначала на тестовом чате (per-chat override),
  затем глобально по решению владельца. Live-проверка на целевом чате `-1002661910336`.
- **Откат:** вернуть ON (глобально/per-chat) → поведение как прежде; либо `git revert` (Δ DDL=0, данные не мигрировались).
- После первого рестарта `PgDatabase` авто-сидит `flags.budgets_enabled=true` (ON CONFLICT DO NOTHING) — откат данных не нужен.

## 11. Инварианты

- **Δ DDL = 0.** Новый ключ — строка `bot_settings` через существующий идемпотентный сид; новых таблиц/колонок/миграций нет.
- **R16:** только аддитивные поля (`budgets_enabled` в snapshot; новый ключ в API).
- **R17/R18:** секреты не читаются/не логируются/не цитируются.
- **`physical-two-call`:** LLM-конвейер не переписывается (гейт стоит до/вокруг бюджета, не меняет вызовы).
- **`tma-menu-freeze`:** состав/порядок пунктов меню не меняется; новых вкладок и карточек нет.
- **F20-путь per-chat записи** (`web/api/routes.py`) не изменяется.
