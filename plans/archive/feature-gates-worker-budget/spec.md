# Спецификация: Feature Gates + Worker-бюджет (F-10)

**Эпик:** раунд 10 (07.09.2026), части 2.3 (Feature Gates / жёсткий Opt-In) + 2.4 (глобальный суточный бюджет фоновых воркеров) «Multi-chat scaling» (research §4 пункты 1-2, §5.1-5.2). **Задачи:** T-890…T-902 (база HEAD `fac1b9f`).
**Статус:** спецификация @Architect (T-890) — закрывает Q1–Q6 раздела A `tasks.md`. Взаимность: F-7 (`chat_params` §4.2, RBAC §2.3), F-9 («пермсос»-гейт §3), F-11 (TMA-навигация), F-12 (бюджеты/гейты в сводке).

---

## 1. Скоуп и инварианты

1. **Тяжёлый Opt-In**: новые чаты получают `gates_opt_in=false` + явные OFF-гейты тяжёлых фич; включение — только явное (глобальный админ или локальный админ чата).
2. **Глобальный бюджет фона**: единый суточный ledger в PG `worker_budget`, потребляют ровно 3 воркера (Dream/Nostalgia/Lore), интерактив и суммари-крон **не трогаем** (приоритет P0-интерактива — research §4.1).
3. **Существующее поведение живых чатов сохраняется**: бэкфил-скрипт для текущих PG-профилей пишет гейты по сегодняшним глобальным флагам (→ ON) и `gates_opt_in=true`.
4. **Fail-open**: PG down → `consume()` возвращает True (воркеры не останавливаются), гейты — по глобальным флагам; WARNING-лог с дедупом.
5. **SQLite-схема не меняется** — миграции только аддитивные `CREATE IF NOT EXISTS` в PG-ДДЛ; `memory_dream_log`/`nostalgia_log`/`dream_state` — их аудит-поля остаются, ledger — отдельная надстройка (без миграции старых строк).
6. Порядок роутеров `bot.py`/DI-зона on_startup (memory_maintenance/lore_worker) — **не переставлять**; WorkerBudget создаётся рядом с существующими сервисами, передаётся в воркеры конструктором.

---

## 2. Q1 — Модель Opt-In: колонка + единый JSONB-гейт-слой

**Решение (двухслойная модель, «колонка + gates namespace»):**
- `chat_profiles.gates_opt_in BOOLEAN NOT NULL DEFAULT FALSE` — **аддитивная колонка** (ADD COLUMN IF NOT EXISTS). Смысл: «чат явно участвует в Opt-In программе» (выставляется автоматически при первом включении любой тяжёлой фичи, либо локальному админу через API; читается svодкой F-12).
- **Значения per-feature — в `chat_params["gates"]`** (уже определён в F-7 §4.2) — НЕ отдельная JSONB-колонка `feature_gates` (два источника правды). Ключи: `dream`, `nostalgia`, `lore_auto`, `permsoc` (последний — F-9).
- Единственная точка записи: `services/feature_gates.py::set_feature_gate(chat_id, feature, enabled, *, changed_by, expected_updated_at=None)` → F-7 `set_chat_params` (транзакция + история `field='gates'` + NOTIFY; 409 optimistic).

**Резолв гейта (единый, используется F-9/F-12):**
```
gates_enabled(chat, feature):
    1. chat_params.gates[feature]   → если есть явно (bool)
    2. hot.get("flags.<feature>_enabled", settings-дефолт)
       [существующие флаги flags.dream_enabled / flags.nostalgia_enabled /
        flags.lore_auto_enabled — остаются ГЛОБАЛЬНЫМИ дефолтами, значения в проде не тронуты]
    3. иначе False (класс «feature не существует») — безопасно
```
PRIMER: отсутствие явного chat-гейта при включённом глобальном флаге = ON; поэтому «OFF для новых чатов» достигается явной записью `gates[dream|nostalgia|lore_auto]=false` при `ensure_profile` (C1) — так живые чаты (без явных гейтов) сохраняют сегодняшнее поведение.

---

## 3. Q2 — «Тяжёлые фичи» — точный список

**Ровно три: `dream`, `nostalgia`, `lore_auto`.** Relations (`relations_enabled` — собственный тумблер профиля) и `dig_into_lore` (тул) — НЕ в списке (опыт раунда 9: не гейтились, управляются собственными тумблерами). `permsoc` — лёгкий master (F-9), не тяжёлый, но гейт-запись в том же namespace (кто_can_toggle: только глобальный админ).

| feature | канонический флаг | воркер | default (новый чат) |
|---|---|---|---|
| `dream` | `flags.dream_enabled` | DreamWorker | OFF (явный гейт) |
| `nostalgia` | `flags.nostalgia_enabled` | NostalgiaWorker | OFF (явный гейт) |
| `lore_auto` | `flags.lore_auto_enabled` | LoreWorker | OFF (явный гейт) |
| `permsoc` | `flags.permsoc_enabled` | PermsocGate (F-9) | OFF (гейт F-9) |

---

## 4. Q3 — Включение/активация

- **Кто включает**: глобальный админ (где угодно) **или** локальный админ чата (chat_admins-грант, F-7) — для трёх тяжёлых; `permsoc` — только глобальный админ.
- **Что делает включение**: `set_feature_gate(..., True)` → если фича тяжёлая и `gates_opt_in=false` → в той же транзакции `gates_opt_in=true` (**auto_opt_in**); история `field='gates'` + лог.
- **Поведение при Opt-In OFF**: прямые ответы бота в чате работают (direct_chat НЕ гейтится — UX-вариант из PM-базы); воркеры: `generate_for_chat`/тик-обработчики скипают чат (`WARNING skip: gate <feature> | chat=%s`), никаких LLM-вызовов, никаких сообщений в чат.
- Новый чат при входе (`handlers/chat_lifecycle.py::ensure_profile`): `gates_opt_in=false` + явные гейты трёх тяжёлых = false. Существующие чаты — бэкфил (ниже).
- **Бэкфил-скрипт** `scripts/backfill_feature_gates.py` (по образцу seed/бэкфил-прецедентов; идемпотентный; stdout):
  ```
  поле gates[dream|nostalgia|lore_auto] = текущий глобальный (<hot.get> флага, в проде = true)
  gates_opt_in = true, если хоть один из 3 = ON; иначе false
  запись — ТОЛЬКО если gate отсутствует (существующие не затираем)
  чат без профиля — скип
  ```
  Запуск: @DevOps при деплое (после миграции DDL, до живых тиков).

---

## 5. Q4 — Бюджет-ледеджер и приоритеты

### 5.1 ДДЛ (в `DDL_STATEMENTS`, идемпотентно)

```sql
CREATE TABLE IF NOT EXISTS worker_budget (
    day        DATE NOT NULL,
    scope      TEXT NOT NULL,      -- 'global' | 'chat:<id>'
    metric     TEXT NOT NULL,      -- 'llm_calls' | 'llm_tokens'
    used       BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (day, scope, metric)
);
```

- Единственный источник правды — **PG** (SQLite-воркеры пишут через имеющийся в runtime `PgDatabase` — прецедент chat_lore-записи; НЕ дублировать в SQLite).
- **День**: локальная таймзона сервера `Asia/Yekaterinburg` — константа `WORKER_BUDGET_TZ` (settings+REGISTRY-замечание; используется как в `memory_maintenance`/`GOODMORNING_TZ`); `day := date(now() AT TIME ZONE tz)`.
- **Первый вызов дня**: строки не создаются заранее — `upsert` атомарно создаёт с нуля (INSERT … ON CONFLICT DO UPDATE `used = used + $1`).

### 5.2 `services/worker_budget.py` (НОВЫЙ)

```python
async def consume(scope, metric, amount=1) -> bool
    # одна SQL-операция: INSERT ... ON CONFLICT (day, scope, metric)
    # DO UPDATE SET used = worker_budget.used + $amount, updated_at = now()
    # RETURNING used; False если used > limit(metric) (или PG down → True+WARNING throttled)
async def get_usage(scope=None) -> list[dict]     # день, scope, metric, used (+limit resolved)
async def get_day_summary() -> dict                # для GET /api/workers/budget и F-12
def priority_of(worker_id) -> int                 # nostalgia=0 (высший), lore=1, dream=2 (низший)
def workers_dropped(order) -> list[str]           # деградация по списку при исчерпании
```

- Лимиты — REGISTRY (горячие, `hot.get` на каждый вызов → кэш):
  `limits.worker_daily_llm_calls_global` (200), `limits.worker_daily_llm_tokens_global` (500000),
  `limits.worker_daily_llm_calls_per_chat` (35), `limits.worker_daily_llm_tokens_per_chat` (100000),
  `limits.worker_priority_order` (`"nostalgia,lore,dream"` — строка порядка деградации), `limits.worker_budget_jitter` (мин., 5).
- **Деградация**: при исчерпании **global**-лимита тик-прогон воркера скипается («остановка после отката»): сначала падает `dream`, потом `lore`, последней `nostalgia` (порядок priority_order). Per-chat лимит — скип конкретного чата. Токены — оценка на входе (chars/4) + факт ответа (вкл. токены ответа; приблизительность — README-пометка), calls — 1 на вызов LLM.
- **Jitter**: тики воркеров (IntervalTrigger) размазываются случайным сдвигом `random(0, limits.worker_budget_jitter)`... точнее: существующий `AsyncIOScheduler` (memory_maintenance, интервалы 30-60 мин) + jitter (параметр планировщика) — по прецеденту, НЕ менять интервалы; jitter-вычесление в DI-зоне bot.py.
- Флаг «фон выключить при перегреве»: не требуется — приоритетная схема и есть механизм.

---

## 6. Q5 — Интеграция в воркеры (consum-точки)

| Воркер | Тип consume | Где (вставка) | При skip |
|---|---|---|---|
| DreamWorker (дистилляция) | `global ('llm_calls', 1)` + `('llm_tokens', est)` + per-chat тот же счёт с scope `chat:<id>` | перед `llm_client`-вызовом дистилляции; перед обращением к чату — `gates_enabled(chat,'dream')` | `memory_dream_log` status='budget_skip' (прецедент) |
| NostalgiaWorker (слой B — генерация) | то же | перед LLM-вызовом генерации; префильтр тихой фазы — `gates_enabled(chat,'nostalgia')` | `nostalgia_log` status='budget_skip' |
| LoreWorker (merge-вызов) | то же | перед merge-LLM в `generate_for_chat`; префильтр — `gates_enabled(chat,'lore_auto')` | WARNING-лог, история не пишется |

- `memory_dream_log.tokens` (SQLite-бюджет kind/tokens) — **остаётся как есть** (внутренний аудит воркера), ledger — надстройка, старые строки не мигрируем.
- День-граница/часовой пояс — §5.1.

---

## 7. API + TMA (D3/E1/E2)

| Метод | Права | Описание |
|---|---|---|
| `GET /api/chat/{chat_id}/gates` | global admin; local admin/moderator чата — чтение; чужой чат → 403 | `{chat_id, opt_in, gates: {dream,nostalgia,lore_auto,permsoc}, who_can_toggle: {dream: 'global|local', permsoc: 'global'}, updated_at}` |
| `PUT /api/chat/{chat_id}/gates` | global admin (любые), local admin своего чата (только тяжёлые) | `{feature, enabled}` → `set_feature_gate`; 422 невалидная фича, 403 чужой/локальный-на-permsoc, 409 optimistic; ответ `{feature, enabled, opt_in}` |
| `GET /api/workers/budget` | global admin (раздел) или local admin — с фильтром `global+свой чат` | `{day, timezone, global: {calls:{used,limit}, tokens:{...}}, chats: [{chat_id, ...}], priorities: [...]}` |

- Модуль `web/api/gates.py` + `web/api/budget.py` (НОВЫЕ, include в `web/app.py` после `api_router` / рядом с chat_lore_router — добавка, прецедент).
- **TMA «Модули и Фичи»** (до F-11 — карточка во вкладке «Реакции и Триггеры»/ авто-лор-карточка в «Лоре»): три чипа Сон/Ностальгия/Авто-лор (ON/OFF бейджи, toggle по правам §7), строка «Opt-In: включено/выключено» (с пояснением), блок «Бюджет фона» — прогресс-бары день/глобал + per-chat (usage/limit) из `GET /api/workers/budget`; лимиты НЕ редактируются из TMA (только config-раздел limits); view для владельца + refresh-кнопка (без polling).

---

## 8. Тест-инварианты (F1)

1. Lifecycle: новый профиль — opt_in=false + 3 явных OFF-гейта; повторный вход — no-op; существующий профиль не изменяется.
2. `gates_enabled` matrix (явный > глобальный > False); `auto_opt_in` при первом включении тяжёлой.
3. Воркеры: 3 skip-пути (моки — gate off → LLM-вызовы не происходят), budget: consume-порог (лимит 10 → 11-й False), новый день — авто-сброс (эмуляция), per-chat/global независимы, деградация по priority_order, jitter в диапазоне, fail-open (PG down → consume=True, не упал).
4. API: 401/403/404/422/409 матрица (global/local/mod/user; локальный на чужой чат 403); GET /api/workers/budget — global+mylocal для local.
5. Обновление существующих тестов dream/nostalgia/lore (моки под gates).
6. Полный pytest → 0 failed; `git diff --check`; RUNTIME WARNING (SQLite-схема/инструменты истории нетронуты; `worker_budget` — PG).

---

## 9. Инвентарь (Q6) для @Builder

- Точки: `handlers/chat_lifecycle.py` (ensure_profile — где писать гейты: существующий store-метод `upsert_profile_on_join`), `services/lore_worker.py`, `services/dream_worker.py`, `services/nostalgia_worker.py`, `bot.py` (DI: on_startup зона memory_maintenance/lore_worker — добавка, порядок НЕ менять), `services/param_catalog.py` (новые limits-записи + `flags.*` — частично есть), `web/app.js`/`web/index.html` (карточки/прогресс-бары), `services/config_cache.py` (не трогаем).
- REGISTRY-дополнение: `limits.worker_daily_*` (5) + `WORKER_BUDGET_TZ`-константа (settings) + `flags.*` где отсутствуют.
- Существующие флаги-гейты в воркерах (`flags.dream_enabled`, `flags.nostalgia_enabled` в хот-гете) — **не удалять**: становятся глобальным слоем chain.

## 10. Риски для @Builder

1. **Двойной счёт токенов** (Dream использует свои estimates): подтвердить в тестах, что consume-сумматор не рушит прежние `memory_dream_log` аудиты.
2. **Скип ЛоrWorker.aстда не забыть** NOTIFY-независимость: skip НЕ должен инвалидировать кэш профилей (история не пишется).
3. **chat_profiles.chat_lore_history field='gates'** — CHECK-расширение в DDL F-7 §4.1 (согласовано; код gates API обязан писать историю этим значением).
4. **Jitter + IntervalTrigger** — прецедентная проверка: jitter шире интервала → частота падает в полти (!) — каппуровать `jitter ≤ interval/3`.
