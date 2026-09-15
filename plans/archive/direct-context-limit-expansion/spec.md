# Spec F4 — `direct-context-limit-expansion` (Развязка двух систем обрезки контекста, расширение `<Global_Context>`/`<Conversation_Thread>`, починка `token_counter`)

> **Раунд:** 10.19, **итерация 2** (Step 2 @Architect, 15.09.2026). **Тип:** backend + каталог/UI (`services/direct_chat_service.py`, `services/token_counter.py`, `config/settings.py`, `services/param_catalog.py`). **Приоритет:** **P1** (память бота «схлопнута» — качество ответов).
> **ADR:** `adr-1019-4-context-limits-decoupling.md` + **`../budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`** (sentinel-таблица, сид настроек чатов, изоляция).
> **Задачи:** T-1809…T-1817 + итерация 2: T-1861/T-1862. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/90/406/411/88/19**.
> **Источник:** `plans/current_task.md` UPD2 (строки 162,164,174) + **UPD3 п.2/п.3** (строки 189-207).
> **Зависимости:** F3 (паттерн настроек/группа `limits_chat_context`) → **F4**. **Конфликт файлов:** `services/param_catalog.py` (F3/F7), `config/settings.py` (F7).
>
> **🔴 UPD3 (итерация 2) — корректировки F4:**
> 1. **Контекст — явное per-chat поле** («Лимит контекста»): `−1` = **безлимит** (ограничен потолком безопасности), `0` = **не задано** → глобальный дефолт, `>0` = cap.
> 2. Значения по умолчанию — **глобальный предохранитель** (5000/3000/16000), безлимит — **только per-chat** (сид настроек чатов).
> 3. Новый env-only **потолок безопасности** `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (Δ каталога = 0): `−1` резолвится в него, а не в бесконечность.

## 1. Контекст и цель

Владелец: «с семи тысяч токенов память обрезают до 869 — это недопустимо; объясни, почему так жёстко режется; лимит должен быть значительно расширен и нужна понятная настройка». Плюс чекап: `token_counter` «ноет, что токенный лимит не задан, и падает на chars-fallback в 2000 символов».

**Причина «869»:** `_build_global_context` вызывает `resolve_chat_limit(..., token_default=1000)` (`direct_chat_service.py:1993-2002`). Так как `CHAT_GLOBAL_CONTEXT_MAX_TOKENS = None`, а env-переменная `CHAT_GLOBAL_CONTEXT_MAX_CHARS` не задана, функция возвращает `("tokens", 1000)` → `budget = safe_budget(1000) = 1000 / 1.15 = 869`. То есть **источник обрезки — не размер чата и не настройка владельца, а дефолт `1000` в коде**, превращённый «запасом безопасности» в 869.

**Цель:** расширить лимиты до осмысленных, развязать две независимые системы обрезки, дать понятную настройку, убрать chars-fallback из штатного пути.

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `services/direct_chat_service.py:1993-2002` — `kind, limit = resolve_chat_limit(per-chat tokens, **1000**, "CHAT_GLOBAL_CONTEXT_MAX_CHARS", chars, "CHAT_GLOBAL_CONTEXT")`.
- `services/direct_chat_service.py:2012-2015` — `budget = safe_budget(limit)` при `kind=='tokens'` → `safe_budget(1000)=869`; при превышении — `WARNING "direct: global context truncated | tokens=N -> 869"`.
- `services/token_counter.py:119-121` — `safe_budget(max) = max / TOKEN_SAFETY_MULTIPLIER(1.15)`.
- `services/token_counter.py:124-140` — `resolve_chat_limit`: токен задан → tokens; иначе если chars-env задан → **chars-fallback + WARNING**; иначе `("tokens", token_default)`.
- `config/settings.py:755-757` — `CHAT_GLOBAL_CONTEXT_MAX_TOKENS: int|None = None`, `CHAT_THREAD_MAX_TOKENS: int|None = None` (**None → chars-ветка**).
- `config/settings.py:650,663` — `CHAT_GLOBAL_CONTEXT_LIMIT=100`, `CHAT_GLOBAL_CONTEXT_MAX_CHARS=4000`, `CHAT_THREAD_MAX_CHARS=2000`.
- `config/settings.py:865-869` — **другой контур**: `CHAT_CONTEXT_BUDGET_TOKENS=4000` (+ доли `CHAT_BUDGET_*_RATIO`).
- `services/direct_chat_service.py:1125-1258` — `_apply_context_budget`: режет **общий** контекст по долям; global-доля = `effective × CHAT_BUDGET_GLOBAL_RATIO (0.30)` = ~1200 при 4000, далее порядок урезания может резать global **ещё раз** (двойная обрезка).
- `services/param_catalog.py:1017-1019` — описания: «Потолок глобального контекста, **слов**» / «Потолок ветки, слов» — **неверная единица** (это токены).

## 3. Требуемое поведение

1. `<Global_Context>` и `<Conversation_Thread>` получают **явные токенные потолки** (не `None`); обрезка 869 не воспроизводится.
2. Две системы лимитов **явно развязаны**: per-block caps (сколько максимум может занять блок) vs total budget (сколько всего); **двойная обрезка одного блока устранена** инвариантом конфигурации.
3. `token_counter`: осмысленный дефолт `CHAT_THREAD_MAX_TOKENS`; chars-fallback — **аварийный путь** с явным логом, а не штатный; «ной»-WARNING убран из штатного режима.
4. Понятная per-chat настройка в миниаппе с человекочитаемым описанием (единицы — **кусочки текста**; round-10.9 jargon-гейт запрещает слово «токены» в пользовательских текстах, хотя технически это токены); поле живёт в группе `limits_chat_context` (вкладка «Бюджеты», F3).
5. **Sentinel-семантика контекста (UPD3/ADR-1019-8 §D2):** `−1` = безлимит (резолвится в `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`, env-only, default 32000 — Δ каталога 0); `0` = не задано → глобальный дефолт; `>0` = cap. `−1` у **общего** бюджета = «не применять агрегатное усечение `_apply_context_budget`» (per-block caps продолжают действовать).
6. **Глобальные дефолты — предохранитель** (5000/3000/16000); безлимит контекста — **только per-chat** (сид настроек чатов: `-1002661910336` → `−1`).
7. Замер реального размера контекста до/после (evidence), perf-бюджет запроса соблюдён.
8. Каталог-Δ — в рамках F3/ADR-1019-3 (2 новые группы; новых REGISTRY-ключей F4 не добавляет).

## 4. Технический дизайн

### 4.1. Владелец каждого лимита (явная модель)

| Контур | Ключ | Смысл | Владелец обрезки |
|---|---|---|---|
| Per-block | `limits.chat_global_context_max_tokens` | максимум токенов блока `<Global_Context>` | `_build_global_context` |
| Per-block | `limits.chat_thread_max_tokens` | максимум токенов блока `<Conversation_Thread>` | сборка ветки |
| Total | `limits.chat_context_budget_tokens` (+ доли) | сумма по всем блокам | `_apply_context_budget` |

**Правило:** `_build_global_context` **никогда** не режет уже собранный блок из-за общего бюджета; `_apply_context_budget` **не** режет блок ниже его per-block потолка, если общий бюджет позволяет. **Реализация (D-1):** `global`/`thread` не проходят безусловный проход по долям — только цикл урезания при `total > budget`; остальные блоки (`map`/`rag`/`branch`/`anchors`) ограничиваются долями, как раньше. Инвариант: `CHAT_BUDGET_GLOBAL_RATIO × (budget − fixed_tokens) ≥ safe_budget(global_cap)` и то же для `thread` (`fixed` = target/relations/protected/lore/current/sandwich).

### 4.2. Целевые значения (рекомендация)

| Ключ | Было | Рекомендуется | Эффектив (÷1.15) |
|---|---|---|---|
| `CHAT_GLOBAL_CONTEXT_MAX_TOKENS` | `None` → код-дефолт **1000** | **5000** | ≈4347 (было 869) |
| `CHAT_THREAD_MAX_TOKENS` | `None` | **3000** | ≈2608 |
| `CHAT_CONTEXT_BUDGET_TOKENS` | **4000** | **16000** | — (global-доля 4800 ≥ 4347 ✓, thread 3200 ≥ 2608 ✓) |

Обоснование: при 4000 общий бюджет физически меньше одного потолка `<Global_Context>` 4347 → двойная обрезка неизбежна; 16000 выравнивает два контура. Доли `CHAT_BUDGET_*_RATIO` не меняются.
**Изменения:** `config/settings.py:755-757` (`None` → числа), `config/settings.py:869` (`16000`), описания каталога (`param_catalog.py:1017-1019`) — единицы «токены».

### 4.3. Инвариант-проверка конфигурации (устраняет «непонятную» двойную обрезку)

В `DirectChatService` — проверка и один WARNING-лог (R17-safe, только числа);
вызывается с оценкой `fixed_tokens` (сумма неприкосновенных блоков), т.к.
обрезка идёт по долям от `effective = budget − fixed`:
```python
effective = max(1, budget - fixed_tokens)
g_share = int(effective * CHAT_BUDGET_GLOBAL_RATIO)   # 0.30
t_share = int(effective * CHAT_BUDGET_THREAD_RATIO)   # 0.20
if g_share < safe_budget(global_cap) or t_share < safe_budget(thread_cap):
    logger.warning(
        "[direct] context config inconsistent | budget=%d fixed=%d -> "
        "effective=%d | global_share=%d < global_budget=%d …", …)
```
Не блокирует работу (fail-open), делает причину усечения видимой в журнале (владелец жалуется именно на «непонятно, почему режется»). Прежняя формула `budget < Σcaps` **пропускала** случай `fixed≈2822, budget=16000` (доля 3953 < cap 4347) — заменена на проверку долей (D-1).

### 4.4. `services/token_counter.py` — убрать костыль из штатного пути

- `resolve_chat_limit` — оставить сигнатуру (обратная совместимость вызовов/тестов), но:
  - при `token_value is None` и заданном `chars_env` — вернуть `("chars", chars_value)` **только если** per-chat значение явно задано; иначе (значения нет нигде) — `("tokens", token_default)`;
  - WARNING «токенный лимит не задан … chars-fallback=…» → `logger.debug` (штатная конфигурация больше не «ноет»). WARNING остаётся **только** если chars-ветка реально усекла текст.
- `CHAT_THREAD_MAX_TOKENS`: `None` → **3000**; `CHAT_GLOBAL_CONTEXT_MAX_TOKENS`: `None` → **5000** (см. §4.2). После этого chars-fallback не является основным путём.
- `safe_budget` и множитель `TOKEN_SAFETY_MULTIPLIER` — без изменений.
- Обрезка по chars (`truncate_to_tokens_keep_head` chars-ветка) сохраняется как аварийная страховка.

### 4.5. Человекочитаемое описание настройки (в разделе каталога)

> **«Сколько памяти бот видит в одном ответе».** Контекст — это то, что бот «помнит» в момент ответа: недавние сообщения, конспект, ветка диалога, найденные факты. Он ограничен, чтобы ответ не стоил как крыло самолёта и не тормозил. **`<Global_Context>`** — фон чата (свежий хвост + конспект); **`<Conversation_Thread>`** — ветка ответов на текущее сообщение; **общий бюджет** — суммарный потолок на всё вместе. Если общий бюджет меньше, чем потолки отдельных блоков, блоки начнут резаться дважды — поэтому общий бюджет должен быть не меньше их суммы (это проверяется автоматически). Увеличивая значения, ты даёшь боту больше памяти, но платишь больше за вызов.

**Единицы в UI:** «слова (кусочки текста)» — round-10.9 jargon-гейт
(`test_webapp_round109_ui.py::test_no_forbidden_jargon`) запрещает слово
«токены» в `title_ru`/`description` каталога. Технически значение — токены
(`resolve_chat_limit`/`count_tokens`), это зафиксировано в docstring/комментарии
каталога. Значения по умолчанию: `<Global_Context>` 5000, `<Thread>` 3000,
общий бюджет 16000.

### 4.6. Sentinel и per-chat резолв (итерация 2)

- Резолв — `resolve_setting_cached("limits.chat_global_context_max_tokens", chat_id=…)` и т.д. (chat → global → default; кэш TTL 120с).
- `services/budget_limits.py::context_state(v) -> 'unset'|'unlimited'|'cap'`:
  - `0` → `'unset'` → использовать глобальный дефолт (никогда не «пустой блок»);
  - `<0` → `'unlimited'` → эффективный потолок = `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (env-only, default **32000**), флаг `unlimited=True` в статусе;
  - `>0` → `'cap'`.
- `config/settings.py`: `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS: int = _env_int_min("CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS", 32000, 1000)` — **infra/env-only** (не в каталоге → Δ=0).
- Общий бюджет `−1` → `_apply_context_budget` не выполняется; каждый блок всё равно ограничен своим per-block потолком (для целевого чата он = ceiling).
- **Изоляция:** значения читаются per-chat; глобальные дефолты общие (это предохранитель, не утечка). Никаких не-keyed кэшей.

## 5. Изменения схемы / каталога / env

- **Схема БД:** нет.
- **Каталог:** новых REGISTRY-ключей **нет**; ключи переезжают в группу `limits_chat_context` (F3/ADR-1019-3) и получают описания с sentinel-семантикой (`0`/`−1`). Δ ключей = 0.
- **env:** `config/settings.py:755-757` (5000/3000), `:869` (16000), **новый** `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000` (env-only, Δ каталога 0); `.env.example` — комментарии.
- **Важно:** PG-значения засеяны `ON CONFLICT DO NOTHING` → фактические числа прод меняются через F3-UI/@DevOps/сид, а не сами по себе.
- **Сид настроек чатов:** `-1002661910336` → контекст `−1` (максимум) через `config/chat_settings_seed.json` (ADR-1019-8 §D4).

## 6. Влияние на тесты

- `tests/test_token_counter.py` (если есть) / новый `tests/test_context_limits_round1019.py`:
  - `resolve_chat_limit(None, 5000, …)` → `("tokens", 5000)` (не chars);
  - chars-ветка срабатывает только при явном per-chat значении; WARNING не эмитится в штатном режиме;
  - `safe_budget(5000) == 4347`;
  - инвариант-проверка: доля (`ratio × (budget − fixed)`) < `safe_budget(cap)` → warning-лог, работа продолжается (в т.ч. при `fixed≈3000, budget=16000`);
  - `resolve_context_tokens(None, отрицательный)` → кламп до 1 (D-8).
- `tests/test_direct_chat.py` / `test_direct_chat_context.py`: `<Global_Context>` не обрезается до 869 при большом окне; двойная обрезка отсутствует (блок ≤ cap); `budget=16000` не режет global ниже 4347, если суммарно влезает.
- `tests/test_param_catalog.py`: формулировки единиц — «кусочки текста» (round-10.9 jargon-гейт); Δ=0 (или синхронно с F3).
- Замер (T-1815): evidence «токены до/после» + время сборки контекста.
- Полный `pytest` 0 failed; `node --check`; `git diff --check` clean.

## 7. Rollout / feature-flag / откат

- **Feature flag не вводится** (лимиты уже настраиваемые; расширение — новые дефолты + данные). Если ADR сочтёт риск стоимости значимым — возможен отдельный per-chat override, но по умолчанию всё включается безусловно.
- **Progressive delivery:** сначала тестовый чат (`-1002661910336`), замер стоимости/латентности → затем прод.
- **Rollback:** `git revert` + возврат прежних значений (settings/PG).
- **Порядок:** F3 → F4 (общий каталог).

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Рост контекста → стоимость/латентность | T-1815 замер; значения конфигурируемы; инвариант-проверка |
| R2 | Две системы неявно связаны — «развязка» меняет поведение | Явная модель §4.1 + инвариант §4.3 + тесты |
| R3 | `chars-fallback` — страховка | Сохранить как аварийный путь, убрать шум WARNING |
| R4 | Δ каталога без санкции | Формулировки входят в F3-санкцию; записи не добавляются |
| R5 | «слов» вместо токенов вводит в заблуждение | T-1813: единицы «токены» |
| R6 | Пересечение с F2/F3 | F3 → F4; согласованное вливание |

## 9. Открытые вопросы (human-gate — рекомендации)

1. **(e) Целевые значения — ПРИНЯТО как глобальный предохранитель:** `<Global_Context>` **5000** (эфф. ≈4347), `<Conversation_Thread>` **3000** (эфф. ≈2608), общий бюджет **16000**. Безлимит (`−1`) — **только per-chat** (сид настроек чатов), см. ADR-1019-8 §D2/D4.
2. **Судьба chars-fallback:** рекомендация — **оставить аварийным** (не удалять), убрать WARNING из штатного режима.
3. **Тумблер «расширенный контекст»:** не вводится (значения настраиваемые; флаг = dead-code). Безлимит — per-chat sentinel `−1`.
4. **Где показывать настройку:** в F3-разделе «Бюджеты» (группа `limits_chat_context`).

## 10. Реализация (итерация 2, Батч D — @Builder, 16.09.2026)

Закрыт **High S10.19-13** (семантика контекстного семейства в потребителях) и
**Medium S10.19-14** (пустой день фон-контура → ложное «Запрещено»).

| Контур | Ключ | `< 0` (`-1`) | `0`/`None` | `> 0` | Дефолт |
|---|---|---|---|---|---|
| Per-block | `limits.chat_global_context_max_tokens` | потолок безлимита 32000 | глоб. дефолт 5000 | cap | 5000 |
| Per-block | `limits.chat_thread_max_tokens` | потолок 32000 | глоб. дефолт 3000 | cap | 3000 |
| Total | `limits.chat_context_budget_tokens` | агрегатное усечение НЕ применяется | глоб. дефолт 16000 | cap | 16000 |

Реализация: `token_counter.resolve_context_tokens` (чистый резолв) →
`resolve_chat_limit` (все call-sites: `_build_global_context`,
`_thread_limit`/`_render_thread`, `summary_generator`); `_apply_context_budget`
→ `-1` = skip aggregate; `config/settings.py` (5000/3000/16000);
`config_migrations.migrate_context_limit_defaults` (идемпотентно,
1000/500/4000 → 5000/3000/16000); `oversight.CONTEXT_LIMIT_KEYS` (5000/3000);
каталог (sentinel-описания, единицы — «кусочки текста»).

**Доказательство (S10.19-13):** `resolve_chat_limit(-1, 1000, …)` →
`("tokens", 32000)`, `safe_budget(32000)=27826` (было `safe_budget(-1)=1`);
`tests/test_context_limits_round1019.py::TestGlobalContextNotStarved` —
контекст целевого чата из 20 сообщений сохраняется целиком (`>100` токенов, не «1»).

## 11. Простыми словами: почему было 869 и что стало

Раньше фон (`<Global_Context>`) собирался с жёстким лимитом **1000** прямо в
коде (а не из настройки владельца), а «запас безопасности» ×1.15 оставлял
**869**. При этом настройка сида «безлимит» (`-1`) в потребителях не
распознавалась: она делилась на 1.15 и превращалась в **1 токен** — бот видел
от фона одну-единственную «крошку». Плюс общий бюджет 4000 был меньше одного
потолка фона, поэтому блок урезался дважды.

Теперь: дефолты подняты до **5000/3000/16000**, а `-1` честно означает
«безлимит» (применяется потолок безопасности 32000), `0` — «не задано»
(берётся глобальный дефолт). Целевой чат получает полный фон, а причина
любого усечения видна в логе (`context config inconsistent` при
`budget < global_cap + thread_cap`).
