# Spec F3 — `budget-settings-section` (Раздел «Бюджеты» в «Модулях»: оба контура + тумблер безлимита; «Сводка» показывает актуальные лимиты)

> **Раунд:** 10.19, **итерация 2** (Step 2 @Architect, 15.09.2026). **Тип:** backend + frontend/каталог (`services/param_catalog.py`, `services/oversight.py`, `services/chat_settings_seed.py` (новый), `services/retention_policy.py` (новый), `config/chat_settings_seed.json` (новый), `web/api/*`, `web/index.html`, `web/app.js`). **Приоритет:** **P0/P1**.
> **ADR:** `adr-1019-3-budgets-section.md` + **`adr-1019-8-per-chat-limits-and-seed.md`** (мультичатовость, sentinel-таблица, сид настроек чатов, guard, Сводка).
> **Задачи:** T-1799…T-1808 + итерация 2: T-1856…T-1860. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/90/406/411/88/19**.
> **Источник:** `plans/current_task.md` UPD2 п.1 (строка 132) + чекап (строка 162) + **UPD3 п.2-5** (строки 184-214).
> **Статус F3:** ✅ **IMPLEMENTED** (Step 4 @Builder, 16.09.2026). Каталог: **437/92/407/412/90/20**; полный `pytest` **6227 passed / 0 failed**; `node --check`/`routing_test.js`/`vue_mount_test.js`/`git diff --check` — clean. Закрыты T-1799…T-1807 + T-1856…T-1860; гейт T-1808 — @Reviewer/@PM. Дефолты (100/500 000; фон 60/300 000) доехали до прода идемпотентной миграцией `migrate_global_budget_defaults` (S10.19-8); сид настроек чатов — `services/chat_settings_seed.py` + `config/chat_settings_seed.json`.
> **UPD4 (итерация 3, 16.09.2026):** концепция «VIP» убрана из **кода** полностью — сид переименован в нейтральный универсальный (`services/chat_settings_seed.py` + `config/chat_settings_seed.json`, CLI `apply-chat-overrides`, `source='seed_enforced'`); выдачей безлимитов/вечного хранения управляют **только данные**, код-путь generic (`for entry in seed["chats"]`). Детали — ADR-1019-8 §D10, spec F7 §10.
> **HOTFIX (Post-Deploy Gate, 16.09.2026):** `set_chat_params(..., changed_by="chat_settings_seed")` передавал **строку** в `chat_lore_history.changed_by BIGINT` (`services/pg_db.py:95`) → asyncpg `DataError`; исключение глоталось fail-open (`bot.py`), на проде сид **никогда не применялся** (SQL-гейт: 8 × `None`). Фикс: `changed_by=None` (канон «NULL = бот/AI», согласован с `scripts/backfill_*.py`; аудит-строка сохраняется). Прежний тест мокал `set_chat_params` и не исполнял реальный SQL — добавлен `TestSeedIntegrationNoMock` (реальные `set_chat_params`/`ensure_scope_profile` + строгий PG-фейк, валидирующий BIGINT), а также тест «ошибка записи → WARNING», идемпотентность повторного прогона.
> **Зависимости:** **F2** (механизм безлимита — обязателен) → **F3** → F4. **Конфликт файлов:** `web/index.html`/`app.js` (F5 — вливать ступенями F3→F5), `services/param_catalog.py` (F4/F7).
>
> **🔴 UPD3 (итерация 2) — корректировки F3 (обязательны):**
> 1. **3 явных per-chat поля** в UI настроек чата: «Хранение импорта (дней)» (`0 = вечно`), «Лимит токенов/вызовов» (`−1 = безлимит`, `0 = запрет`), «Лимит контекста» (`−1 = безлимит`, `0 = не задано`).
> 2. **целевой чат `-1002661910336`** получает эксклюзивные значения **сидом** (данные, не хардкод): retention `0`, бюджеты `−1`, контекст `−1`/максимум.
> 3. **«Сводка»**: бейдж **«Безлимит (∞)»** вместо `1 500 000 / 1 500 000`; статус **«Импорт: Вечно»** / «Импорт: 180 дней».
> 4. Каталог-Δ пересчитан (см. §4.3): **+1 REGISTRY-ключ, +2 группы, +1 вкладка**.

## 1. Контекст и цель

Владелец: «Настройки по бюджетам в миниапп я вообще их не вижу, почему их нет? Нужен отдельный раздел в Модулях… проследи, что в Сводке бары показывают актуальную информацию по лимитам». Сейчас:
- лимиты **direct-ключа** (`limits.chat_global_key_budget_*`) лежат в группе `limits_chat` («Прямой чат: контекст») вместе с десятками ключей контекста — найти их невозможно;
- лимиты **фона** (`limits.worker_daily_*`) лежат в группе `limits_worker` (вкладка «Диагностика»);
- «Сводка» строит `budget` **только** из `worker_budget.get_usage(f"chat:{id}")` → direct-контур **не показан**, лимиты выглядят «не превышенными» в момент sandbox-срабатывания.

**Цель:** отдельный понятный раздел **«Бюджеты»** с обоими контурами и тумблером безлимита; честные бары «Сводки»; человекочитаемое объяснение «фон vs интеллект».

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `services/param_catalog.py:1232-1240` — `CHAT_GLOBAL_KEY_BUDGET_TOKENS/REQUESTS`, группа `limits_chat` → вкладка `TAB_MOD_DIRECT` (`:1836-1843`); описания «…0 — общий ключ чату запрещён».
- `services/param_catalog.py:1244-1267` — `WORKER_DAILY_LLM_*`, группа `limits_worker` → `TAB_MOD_CHECKUP`.
- `services/param_catalog.py:220-225,251` — `GroupSpec` `limits_chat`, `limits_chat_budgets`, `limits_worker` (не путать **бюджеты контекста** `limits_chat_budgets` и **бюджеты ключа**).
- `services/oversight.py:193-215` — `budget` из `worker_budget.get_usage`; при отсутствии строк `budget=None`.
- `services/oversight.py:226` — `global_budget` (только worker).
- `services/worker_budget.py:210-217` — `_metric_limit` (per-chat 35 / tokens 100k; global 200/500k); `:220-244` — `get_usage` (аддитивно возвращает `limit`).
- `services/chat_usage.py:128-136` — `key_status` (used/limit calls/tokens) — источник для direct-баров.
- `services/param_catalog.py:1828-1960` — `TAB_RULES`; `CONFIG_TAB_TITLES` (19), `TAB_NAV` (19, ADR-1018-6 D1/D2).
- Инвариант каталога: `REGISTRY 436 / GROUPS 90 / Settings 406 / categorized 411 / mapped 88 / TAB_RULES = CONFIG_TAB_TITLES 19`.

## 3. Требуемое поведение

1. В «Модулях» — отдельный раздел **«Бюджеты»** (новая config-вкладка `mod_budgets`), показывающий **оба контура** рядом:
   - «Бюджет ключа чата (интеллект)» — `limits.chat_global_key_budget_requests/tokens` (группа `limits_chat_key`);
   - «Лимит контекста (чат)» — `limits.chat_global_context_max_tokens`, `limits.chat_thread_max_tokens`, `limits.chat_context_budget_tokens` (группа `limits_chat_context`);
   - «Бюджет фоновых воркеров» — `limits.worker_daily_llm_*` (группа `limits_worker`, переезжает из «Диагностики»).
2. **Тумблер «Безлимит по чату»** — пишет per-chat `−1` в существующие ключи обоих контуров (механизм F2), подтверждение + откат. Новой REGISTRY-записи **нет**.
3. **Три явных per-chat поля** (UPD3 п.2) с человекочитаемыми описаниями — все `per_chat=True` (категория `limits`):
   - **«Хранение импорта (дней)»** → `limits.import_history_retention_days`: `0` = **вечно/безлимит** (иной sentinel, чем у бюджетов!), `>0` = хранить N дней, `<0` = невалидно → глобальный дефолт (WARNING);
   - **«Лимит токенов/вызовов»** → `limits.chat_global_key_budget_requests/tokens` (+ фон `…_per_chat`): `−1` = **безлимит**, `0` = **запрет** (канон F-7 — подтверждён осознанно), `>0` = cap;
   - **«Лимит контекста»** → `limits.chat_global_context_max_tokens`/`…_thread_…`/`…_context_budget_…`: `−1` = **безлимит** (до потолка безопасности), `0` = **не задано** → глобальный дефолт, `>0` = cap.
4. **целевой чат `-1002661910336` — данными** через сид (`services/chat_settings_seed.py` + `config/chat_settings_seed.json`, ADR-1019-8 §D4): retention `0`, бюджеты ключа/чата `−1`, фон `−1`, контекст `−1` (максимум). Id — **только** в сиде/тестах; сид **не добавляет новых хардкодов** chat_id в бизнес-логику (легаси-константы `services/chat_lore.py`, `manage.py:44`, `tools/history_import/llm_worker.py` существовали до F3 и не являются настройками сида).
5. **«Сводка»**: бары показывают **фактические** лимиты обоих контуров + контекст + хранение; при `unlimited` — **«Безлимит (∞)»**, при `forbidden` — «Запрещено»; статус **«Импорт: Вечно»** / «Импорт: N дней». Аддитивно (R16), §4.2.
6. Человекочитаемые описания у каждого лимита: что ограничивает, что при исчерпании, что значат `0`/`−1` (по семействам — §4.5).
7. Объяснение «фон vs интеллект» простыми словами — текст помощи в разделе (§4.5).
8. **Изоляция (UPD3 п.2):** значения лимитов резолвятся строго per-chat (`resolve_setting_cached`); кэш `chat_params` — по `chat_id`; никакой кросс-чат-утечки (см. §4.6 + F7 §4.6 — аудит памяти).
9. Пин-тесты каталога обновлены согласованно с Δ (§4.3).

## 4. Технический дизайн

### 4.1. UI-структура раздела (новая вкладка)

```
Модули → «Бюджеты»  (tab_id = "mod_budgets")
┌ Бюджет ключа чата — «интеллект» ─────────────────────────────┐
│ ● Лимит вызовов в сутки        [ 100 ]     [ ] Безлимит (∞)   │
│ ● Лимит токенов в сутки        [ 500 000]  [ ] Безлимит (∞)   │
│ Использовано сегодня: 25 / 100 вызовов · 699 / 500k токенов  │
│ ⚠ 0 = полный запрет; −1 = безлимит. Это лимит на общий ключ, │
│   когда у чата нет своего. Исчерпан → бот ответит заглушкой. │
└──────────────────────────────────────────────────────────────┘
┌ Лимит контекста — «сколько памяти видит бот в ответе» ────────┐
│ ● <Global_Context>, токенов     [ 5000 ]  [ ] Безлимит (∞)   │
│ ● <Conversation_Thread>, токенов [ 3000 ]  [ ] Безлимит (∞)  │
│ ● Общий бюджет контекста, токенов [16000] [ ] Безлимит (∞)   │
│ ⚠ 0 = «не задано» → глобальный дефолт; −1 = безлимит (ограничен│
│   окном модели и потолком безопасности).                     │
└──────────────────────────────────────────────────────────────┘
┌ Бюджет фоновых воркеров — «фон» ─────────────────────────────┐
│ ● Вызовов в сутки (чат)   [ 60 ]   ● Токенов (чат) [300 000] │
│ ● Вызовов всего (все чаты)[200]    ● Токенов всего [500 000] │
│ ⚠ 0 = запрет фона для чата; −1 = безлимит. Сон/Ностальгия/Лор│
└──────────────────────────────────────────────────────────────┘
┌ Хранение импорта (дней)  [ 180 ]   (0 = вечно) ──────────────┐
│ ⚠ 0 = хранить вечно (удаление запрещено); >0 = срок хранения;│
│   перед удалением — архив + бэкап (F7).                       │
└──────────────────────────────────────────────────────────────┘
[ Безлимит по этому чату ]  — тумблер, per-chat (F2)
```
- Рендер — существующий generic-механизм каталога (группы → `kv`-поля), без нового компонента. Тумблер — тонкая обёртка над per-chat ключами direct/фон/контекст: ON пишет `−1`, OFF возвращает числа (дефолт/прежнее). Тумблер **не** вводит новую REGISTRY-запись.
- UI-индикация `unlimited`/`forbidden` — из ответа API (не из локальной эвристики): `POST /api/config` возвращает эффективное состояние; «Сводка» — из `limits` (§4.2).

### 4.2. «Сводка» — оба контура + контекст + хранение (аддитивно, R16)

**Точный контракт** `services/oversight.py::build_summary` (карточка чата). Существующий ключ `budget` (worker) **сохраняется без изменений**; добавляется **новый** ключ `limits`:

```python
# ChatSummary (dataclass) + dict-карточка build_summary
"budget": {...},          # СУЩЕСТВУЮЩЕЕ (worker-контур) — не трогать (R16)
"limits": {               # НОВОЕ
    "key_budget": {                                   # direct (chat_usage)
        "calls":  {"used": int, "limit": int, "unlimited": bool,
                   "forbidden": bool, "source": "chat|global|default"},
        "tokens": {"used": int, "limit": int, "unlimited": bool,
                   "forbidden": bool, "source": "chat|global|default"},
    },
    "worker_budget": {                                # фон (зеркало budget)
        "calls":  {"used": int, "limit": int, "unlimited": bool,
                   "forbidden": bool, "source": "chat|global|default"},
        "tokens": {...},
    },
    "context": {
        "global_tokens":       {"limit": int, "unlimited": bool,
                                "source": "chat|global|default"},
        "thread_tokens":       {...},
        "total_budget_tokens": {...},
    },
    "storage": {
        "import_retention_days": int,                 # 0 = вечно
        "import_forever": bool,                       # == (days == 0)
        "source": "chat|global|default",
        "label": "Вечно" | "180 дней",                # человекочитаемо
    },
}
```
- **Источник direct-метрик** — `chat_usage.key_status(...)` (расширенный `unlimited`/`source`, F2 §4.2); worker — `worker_budget.get_usage(scope=f"chat:{id}")` (расширенный `unlimited`, F3 §4.4); контекст/хранение — `worker_settings.resolve_setting_with_source` (ADR-1018-7; нулевая стоимость — кэш).
- **Совместимость:** старые ключи `calls`/`tokens` (`budget`) остаются — фронт не ломается; `limits` — добавка.
- **UI-тексты (точные):**
  - `unlimited: true` → **«Безлимит (∞)»** (бейдж `badge-ok`) вместо `{{used}} / {{limit}}`;
  - `forbidden: true` → **«Запрещено»** (бейдж `badge-err`);
  - иначе — `{{used}} / {{limit}}`;
  - storage: `import_forever` → **«Импорт: Вечно»** (`badge-ok`), иначе **«Импорт: {{label}}»**.
- **Где показывать:** карточка чата «Сводки» (`web/index.html` ~`1166`) и/или виджет «Интеллект и Память` (`~1024-1093`) — по одному компактному блоку; новых эндпоинтов нет (`/api/oversight/summary` уже отдаёт карточку).
- **Fail-open:** ошибка чтения любого источника → соответствующий под-объект отсутствует/нулевой, никогда не 500 (R16-аддитивность + fail-open).

### 4.3. Каталог-Δ — точный (итерация 2; санкция владельца принята в UPD3)

**Итог «было → станет»:**

| Изменение | Было | Станет |
|---|---|---|
| `GroupSpec` **`limits_chat_key`** (category `limits`, «Бюджет ключа чата», order 29) | — | **+1 группа** |
| `GroupSpec` **`limits_chat_context`** (category `limits`, «Лимит контекста (чат)», order 30) | — | **+1 группа** |
| `CHAT_GLOBAL_KEY_BUDGET_REQUESTS/TOKENS`: group `limits_chat` → **`limits_chat_key`** | `limits_chat` | `limits_chat_key` |
| `CHAT_GLOBAL_CONTEXT_MAX_TOKENS`, `CHAT_THREAD_MAX_TOKENS`: group `limits_chat` → **`limits_chat_context`** | `limits_chat` | `limits_chat_context` |
| `CHAT_CONTEXT_BUDGET_TOKENS`: group `limits_chat_budgets` → **`limits_chat_context`** (в группе остаются только доли `CHAT_BUDGET_*_RATIO`) | `limits_chat_budgets` | `limits_chat_context` |
| **Новый ключ** `IMPORT_HISTORY_RETENTION_DAYS` (int, group `limits_memory`, env `IMPORT_HISTORY_RETENTION_DAYS`) | — | **+1 REGISTRY / +1 Settings / +1 categorized** |
| `TAB_MOD_BUDGETS = "mod_budgets"` + `CONFIG_TAB_TITLES[...]="Бюджеты"` | 19 вкладок | **+1 вкладка (20)** |
| `TAB_RULES[TAB_MOD_BUDGETS] = ((LIMITS, {"limits_chat_key", "limits_chat_context", "limits_worker"}),)` | — | **+1 секция** |
| `TAB_NAV[TAB_MOD_BUDGETS] = NAV_MODULES` | — | **+1** |
| `limits_worker`: вкладка `TAB_MOD_CHECKUP` → **`TAB_MOD_BUDGETS`** | «Диагностика» | «Бюджеты» |
| `web/app.js` `TABS`: `mod_budgets` (label «Бюджеты», menu `modules`); `mod_direct` — убрать переехавшие группы; `mod_checkup` — убрать `limits_worker` | 19 TABS | **20 TABS (parity)** |

**Итоговый каталог после итерации 2:** `REGISTRY 437 / GROUPS 92 / Settings 407 / categorized 412 / mapped 90 / TAB_RULES = CONFIG_TAB_TITLES 20 / TAB_NAV 20`.
(Прирост: `REGISTRY +1`, `Settings +1`, `categorized +1` — новый retention-ключ; `GROUPS +2` — 2 новые группы; `mapped +2` (обе группы назначены вкладке; ещё 2 content-группы остаются без вкладки, как и раньше); `TAB_RULES/CONFIG_TAB_TITLES/TAB_NAV +1`.)
**Синхронно обновляются:** `tests/test_param_catalog.py` (436→437; 90→92; `limits_chat_key`/`limits_chat_context` существуют; `limits_worker` не потерян; counts категории `limits` 187→188), `tests/test_frontend_tab_mapping.py` (`19→20`; `_TAB_BY_GROUP 88→90`; `ALL_TABS` +1; `tab_group_ids(mod_budgets)`; `mod_direct`/`mod_checkup` состав), `tests/js/routing_test.js` + JS-parity (`CONFIG_TAB_TITLES ↔ TABS[].label`).

### 4.4. `worker_budget` — per-chat + sentinel (часть F3, зависит от F2)

Чтобы тумблер отключал **оба** контура:
- `worker_budget._metric_limit(scope, metric)` для `scope='chat:<id>'` → резолв per-chat (`resolve_setting_cached`) по `limits.worker_daily_llm_calls_per_chat`/`_tokens_per_chat`; `scope='global'` — без изменений (глобальные лимиты остаются предохранителем всего процесса);
- sentinel (ADR-1019-8 §D2): `limit < 0` → **безлимит**; `limit == 0` → **запрет** фонового расхода для чата; `limit > 0` → cap. Новая форма `get_usage`/`get_day_summary` аддитивно отдают `unlimited`/`forbidden`/`source` (`chat|global|default`);
- дефолты per-chat: `WORKER_DAILY_LLM_CALLS_PER_CHAT` 35 → **60**, `WORKER_DAILY_LLM_TOKENS_PER_CHAT` 100 000 → **300 000** (UPD3: умеренные, не 120/500k). Глобальные 200/500k — **не меняются**.

### 4.5. Объяснение владельцу простыми словами (текст раздела; отдельный блок «Как это работает»)

> **Зачем вообще два бюджета.** Бот тратит деньги на две разные вещи. **«Интеллект»** — это когда ты пишешь боту, и он отвечает: каждое твоё сообщение = вызов нейросети на общем ключе. **«Фон»** — это то, что бот делает сам, пока ты молчишь: сон (складывает факты в убеждения), ностальгия, лор. Их считают раздельно, потому что чинить надо раздельно: если кончился фон — бот просто перестаёт «думать» между сообщениями; если кончился интеллект — бот перестаёт отвечать тебе (отсюда заглушка «нет ключа»).
>
> **Почему глобальные значения именно такие — и почему теперь безлимит по чату.** Раньше стояло 25 ответов и 100 000 «токенов» (токен ≈ кусочек слова) в сутки на общий ключ. Это оказалось мало: 25 ответов бот выбирал уже к обеду. Но делать **всем чатам** безлимит нельзя — тогда один сбойный чат может «сжечь» ключ. Поэтому: глобальные потолки остаются **предохранителем** (**100 ответов / 500 000 токенов**; фон — **60 вызовов / 300 000 токенов** — это примерно ответ каждые 10 минут весь активный день), а нужному чату ты выдаёшь **личный безлимит** тумблером «Безлимит по этому чату». Так система остаётся мультичатовой и безопасной.
>
> **Что значит `0`, `−1` и «Безлимит».** Для **бюджетов**: `0` — это **запрет** («этому чату тратить нельзя вообще»), `−1` — **безлимит** (не считать и не запрещать). Для **хранения импорта** наоборот: `0` — **вечно** (удалять переписку нельзя), а `−1` не имеет смысла. Для **контекста**: `0` — «оставь как настроено глобально», `−1` — «не резать» (в пределах возможностей модели). Тумблер «Безлимит по этому чату» ставит `−1` куда нужно и ничего не ломает другим чатам.
>
> **Что происходит при исчерпании.** Интеллект: бот честно говорит «не могу — лимит», а не молчит. Фон: воркеры отключаются по очереди (сначала Сон), остальные работают; ты видишь это в «Сводке».
>
> **Хранение истории.** «Импорт: Вечно» — старая переписка, по которой бот ищет, остаётся навсегда (для этого чата удаление запрещено). «Импорт: 180 дней» — по истечении срока сырьё архивируется в файл и только потом удаляется из базы (иначе база растёт до миллионов строк).

### 4.6. Изоляция per-chat (UPD3 п.2) — инвариант для F3

- Резолв значений — только `resolve_setting_cached(key, chat_id=chat_id)` (chat → global → default); кэш `ChatParamsCache` ключуется `chat_id` (TTL 120с + NOTIFY-инвалидация `chat_params_updated`).
- Запись тумблера/полей — только через `set_chat_params(chat_id, {"overrides": {...}})`: **merge**, не перезапись чужих ключей; один optimistic-токен на профиль (409 при конфликте).
- Сводка строит `limits` **для конкретного** `chat_id`; `worker_budget.get_usage(scope=f"chat:{id}")` уже scope-изолирован; `chat_usage` — PK `(chat_id, day, metric)`.
- Никаких общих (не-keyed) кэшей значений лимитов. Тесты: два чата с разными override → значения не пересекаются; отключение безлимита у целевого чата не меняет другой чат.
- **Аудит памяти (импорт/RAG/кэши/эмбеддинги)** — в F7 §4.6 (общий инвариант ADR-1019-8 §D5); F3 фиксирует только лимитный слой.

## 5. Изменения схемы / каталога / env

- **Схема БД:** нет новых таблиц/колонок. сид настроек чатов — DML в `chat_profiles.chat_params` (JSONB `overrides`), не DDL.
- **Каталог:** Δ = **GROUPS +2, mapped +2, REGISTRY +1, Settings +1, categorized +1, TAB_RULES/CONFIG_TAB_TITLES +1, TAB_NAV +1** (детали — §4.3). **Санкция получена (UPD3 п.5).**
- **env:** `CHAT_GLOBAL_KEY_BUDGET_*` дефолты 100/500 000 (F2); `WORKER_DAILY_LLM_CALLS_PER_CHAT` 35 → **60**, `WORKER_DAILY_LLM_TOKENS_PER_CHAT` 100 000 → **300 000**; `IMPORT_HISTORY_RETENTION_DAYS` = **180** (новый, F7); `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` = **32000** (новый, env-only инфра, F4). Глобальные фон-лимиты 200/500k не меняем.
- **Файлы-данные:** `config/chat_settings_seed.json` (новый, без секретов) — политика целевого чата.

## 6. Влияние на тесты

- `tests/test_param_catalog.py`: новые числа `437/92/407/412/90/20`; `limits_chat_key` (2 ключа) и `limits_chat_context` (3 ключа) существуют; `limits_worker` не потерян; в `limits_chat_budgets` остались только доли; `TAB_RULES[TAB_MOD_BUDGETS]` покрывает оба контура; каждая группа покрыта ровно одной вкладкой; retention-ключ в `limits_memory`.
- `tests/test_frontend_tab_mapping.py` + `tests/js/routing_test.js`: parity `CONFIG_TAB_TITLES` ↔ `TABS[].label` для 20 секций; `TAB_NAV` исчерпывающ; `tab_group_ids(TAB_MOD_BUDGETS) == {limits_chat_key, limits_chat_context, limits_worker}`.
- Новый `tests/test_budget_settings_round1019.py`: `build_summary` содержит `limits` (key/worker/context/storage); аддитивность (старый `budget` сохранён); `unlimited`/`forbidden`/`source` в метриках; `storage.import_forever` ↔ `days==0`; тумблер пишет/снимает override (mock `chat_params`); `worker_budget` sentinel/per-chat; **изоляция:** два чата с разными override не пересекаются.
- Новый `tests/test_chat_settings_seed_round1019.py`: `apply_chat_settings_seed` пишет `−1`/`0` только целевому `chat_id`; повторный прогон — no-op (нет истории/NOTIFY); `enforce`-retention перезаписывается всегда, бюджеты уважают ручную правку; отсутствие id в `services/*` кроме `chat_settings_seed`/`config/chat_settings_seed.json` (grep-тест).
- `tests/test_oversight.py` (если есть): worker-поля `budget` сохранены (обратная совместимость).
- JS-гейты: `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check`. Полный `pytest` 0 failed.

## 7. Rollout / feature-flag / откат

- **Feature flag не вводится** (видимость/настройка существующих значений). Rollback — `git revert` (+ возврат каталога).
- **Progressive delivery:** тумблер/подписи сначала на тестовом чате (`-1002661910336`), затем прод.
- **Порядок:** F2 (механизм) → F3 (UI+Сводка). С F5 (`index.html`/`app.js`) вливать ступенями **F3 → F5**, чтобы не смешивать диff.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Каталог-инвариант 436/90/406/411/88/19 | Δ фиксирован в ADR-1019-3 и требует санкции (c) |
| R2 | Смешение «бюджет ключа» и «бюджет контекста» (`limits_chat_budgets`) | Разные группы/подписи в разделе; явное пояснение |
| R3 | Сводка показывала worker как «бюджет чата» → ложная картина | Два контура явно (`chat`/`worker`), согласовано с F2 |
| R4 | Тумблер без механизма F2 | Жёсткая зависимость **F2 → F3** |
| R5 | Пересечение ФРОНТА с F5 | Ступенчатое вливание F3 → F5 |
| R6 | Повышенные дефолты = рост стоимости | Явное объяснение владельцу; лимиты остаются управляемыми; глобальный предохранитель фон-контура не тронут |

## 9. Открытые вопросы (human-gate — санкция владельца)

1. **(c) Δ каталога — ПРИНЯТО (UPD3 п.5):** новая группа `limits_chat_key` + новая группа `limits_chat_context` + ключ `import_history_retention_days` + новая вкладка `mod_budgets` (итог `437/92/407/412/90/20`). Запасной Δ=0 (собрать раздел только из `limits_worker`) — **отклонён** как неполный.
2. **(c) Дефолты — ПРИНЯТО:** direct **100/500 000**, фон per-chat **60/300 000**; глобальный предохранитель 200/500k не меняем. Безлимит — **только per-chat** (UPD3 п.5).
3. **(c) Формулировки описаний и пояснений** (§4.5) — утверждены вместе с Δ.
4. **сид настроек чатов** (§4.5/ADR-1019-8 §D4) — значение `-1002661910336` в `config/chat_settings_seed.json`; сид **не вводит новых хардкодов** id в бизнес-логику (легаси: `chat_lore.py`, `manage.py:44`, `tools/history_import/llm_worker.py`). @Reviewer: grep-тест «новых хардкодов нет».
5. **Правило синхронности:** пин-тесты и JS-parity обновляются одним коммитом с каталогом (прецедент ADR-1018-6 D3).
