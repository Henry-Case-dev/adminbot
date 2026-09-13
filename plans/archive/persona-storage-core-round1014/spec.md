# Spec F2 — `persona-storage-core-round1014` (Архитектура Личности: PG-хранилище + ядро)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, **итерация 2**, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1487…T-1497. **ТЗ:** `plans/current_task.md` §2 + **UPD п.1,2,4**.
> **Зависимости:** **F1** (`persona_state` DDL + self-канон). **Вниз:** F3 (UI), F4 (лента+метрики), F6 (гайд). **Baseline:** HEAD `2edc65b`, SQLite v8, каталог 427/90/399/403.
> **ADR:** `adr-1014-1-persona-storage.md` (PG `personas`/`persona_traits`, scope-резолв, API, миграция/сид).
> **Ревизия:** отменяет редакцию 1 (DDL-free `content.persona_*` + `chat_params.overrides`).

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **A. Storage** | **PG-таблицы `personas` + `persona_traits`** (DDL разрешён, UPD п.1). Персона НЕ хранится в `bot_settings`/`chat_params.overrides`. |
| **F2-Q1** scope/`is_global` | First-class колонки `is_global`+`chat_id`; CHECK `(is_global AND chat_id IS NULL) OR (NOT is_global AND chat_id IS NOT NULL)`; partial unique на глобальную и на `chat_id`. |
| **Резолв** | per-chat → global → empty. Поле per-chat не наследует global построчно (сброс = `DELETE` строки). |
| **E. `dynamic_traits`** | **Отдельная таблица `persona_traits`** (не JSONB): метрики `COUNT/MAX`, лента `ORDER BY`, ротация `DELETE`, провенанс `chat_id/source`. |
| **F2-Q4** приоритет | persona-блок **дописывается в конец** системного промпта direct (`system_prompt + "\n\n" + block`). F8-досье пользователя — отдельный user-блок, не задет. |
| **F2-Q5** fallback | Персона пуста/ошибка → блок не строится, промпт **байт-в-байт** прежний. |
| **F. is_aware_ai=false** | Отдельный код-блок `_NO_AI_DISCLOSURE_BLOCK` дописывается после `</Persona>`. |
| **D. naming** | Новая сущность = **личность БОТА** → модуль `services/bot_persona.py`. Существующие `build_persona_card`/`get_persona_card`/«досье» (`direct_chat_service.py:1511`, `database.py:3390`) = карточка ПОЛЬЗОВАТЕЛЯ — **не трогать**. |
| **name-триггер** | Sync-чтение глобального имени из in-memory кэша `bot_persona.get_cached_global_name()` (обновляется на старте и при PUT). Per-chat имя-триггер — вне scope (путь sync). |
| **Feature flag** | `flags.persona_enabled` (bool, `flags_memory`, дефолт **True** — UPD п.2). |

---

## §1. Цель и scope

Бот получает настраиваемую личность: статические поля (имя, биография, характер, «осознаёт себя ИИ») и динамические
черты (`dynamic_traits`), обновляемые «Глубоким сном». Личность scope-базирована: глобально + per-chat override.

**In scope:** PG-схема `personas`/`persona_traits` (+ DDL/сид), scope-резолв, `services/bot_persona.py`, склейка persona-блока
в системный промпт direct, `is_aware_ai`-запрет, генерация/хранение `persona_traits` в DeepSleepWorker,
имя-триггер (global, cache), health-метрики, флаг.

**Out of scope:** UI (F3), лента/метрики-виджет (F4), гайд (F6); изменение F8-досье пользователя; SD-миграция памяти.

---

## §2. Схема данных

### 2.1. PG DDL (полный текст — ADR-1014-1 §2.1)

- `personas(id BIGSERIAL PK, chat_id BIGINT FK→chat_profiles ON DELETE CASCADE, is_global BOOL, name, biography,
  system_prompt_overrides, is_aware_ai, created_at, updated_at)` + 2 partial-unique индекса + CHECK скоупа.
- `persona_traits(id BIGSERIAL PK, chat_id BIGINT NULL, trait TEXT, source TEXT, created_at TIMESTAMPTZ)` +
  индексы `(created_at DESC)`, `(chat_id, created_at DESC)`.
- `persona_state` — владелец F1 (ADR-1014-2 §D9); F2 добавляет колонки трейтов аддитивно (порядок в `DDL_STATEMENTS`: CREATE `persona_state` — из F1, ДО этих ALTER):
  ```sql
  ALTER TABLE persona_state ADD COLUMN IF NOT EXISTS last_trait_at TIMESTAMPTZ;
  ALTER TABLE persona_state ADD COLUMN IF NOT EXISTS last_trait_status TEXT NOT NULL DEFAULT 'never';
  ```

### 2.2. Сид (идемпотентно; `PgDatabase.init` / `_seed_persona`)

- глобальная персона: `INSERT ... SELECT NULL, true WHERE NOT EXISTS (SELECT 1 FROM personas WHERE is_global);`
  (поля пусты; ручные правки не перезатираются).
- `persona_state` singleton — сид из F1.

### 2.3. Каталог-Δ F2 (санкционированный, ровно 1 ключ)

| pg_key | группа | тип | settings_field | дефолт | per_chat |
|---|---|---|---|---|---|
| `flags.persona_enabled` | `flags_memory` | bool | `PERSONA_ENABLED` | **`True`** | true |

Статические поля персоны в каталог **НЕ входят** (источник — PG-таблица; UI — dedicated API + special-tab, см. F3).

### 2.4. Код-дефолты `config/settings.py`

```python
PERSONA_ENABLED: bool = _env_bool("PERSONA_ENABLED", True)
PERSONA_TRAITS_MAX: int = _env_int("PERSONA_TRAITS_MAX", 50)          # cap FIFO
PERSONA_TRAIT_MAX_CHARS: int = _env_int("PERSONA_TRAIT_MAX_CHARS", 200)
```
(не каталог — инфраструктурные константы, «осознанное исключение» F5.)

---

## §3. Алгоритмы

### 3.1. `services/bot_persona.py` (новый модуль)

```python
@dataclass(frozen=True)
class BotPersona:
    name: str; biography: str; overrides: str; is_aware_ai: bool
    scope_chat_id: int | None      # None = global
    is_global: bool

async def resolve_bot_persona(chat_id: int | None) -> BotPersona:
    """per-chat строка → global строка → BotPersona.empty(); fail-open (PG down → empty)."""

def build_persona_prompt_block(persona: BotPersona) -> str:
    """'' если flags.persona_enabled OFF/пусто; иначе блок (§3.2)."""

# hard prohibition (is_aware_ai=false)
_NO_AI_DISCLOSURE_BLOCK = ("Ты НЕ раскрываешь и не признаёшь, что ты бот, ИИ, программа или модель. "
                           "На вопросы «ты бот/ИИ/нейросеть?» — отвечай в образе своей биографии, "
                           "не подтверждай и не опровергай техническую природу.")

async def save_persona(chat_id: int | None, patch: dict) -> None: ...   # UPSERT (§ADR §2.3)
async def delete_persona(chat_id: int) -> None: ...                     # DELETE override
async def append_traits(traits: list[str], *, chat_id: int | None, source="deep_sleep") -> int: ...
async def get_traits(limit: int = 50, chat_id: int | None = None) -> list[dict]: ...
async def get_persona_health() -> dict: ...                             # traits_count/last_trait_at/extractor_status
def get_cached_global_name() -> str: ...                                # sync, для триггера
def set_global_name_cache(name: str) -> None: ...
async def load_global_cache() -> None: ...                              # при старте приложения
```

### 3.2. Склейка в системный промпт

Точка: `direct_chat_service.handle` (`:575-578`), после `system_prompt = await _cpg(...)`:

```python
if hot.get("flags.persona_enabled", settings.PERSONA_ENABLED):
    persona = await resolve_bot_persona(chat_id)
    block = build_persona_prompt_block(persona)
    if block:
        system_prompt = system_prompt + "\n\n" + block
```

Формат блока (порядок/байты фиксируются байт-тестом):
```
<Persona>
Имя: {name}
Биография: {biography}
Характер: {overrides}
Черты, которые ты приобрёл: • {trait1} • {trait2} ...
</Persona>
```
- Пустые секции не рендерятся; если нечего показать — `block == ""`.
- `is_aware_ai=false` → после `</Persona>` `_NO_AI_DISCLOSURE_BLOCK`.
- `is_aware_ai=true` (дефолт) → запрет не добавляется.

### 3.3. `name` как триггер обращения

- `handlers/direct_chat.py::_is_direct_trigger` (`:127-155`) — sync: `name = bot_persona.get_cached_global_name()`;
  при непустом — regex по границам слова; гейт `flags.persona_enabled`.
- Кэш обновляется: (а) `load_global_cache()` при старте (после ConfigCache.init); (б) `set_global_name_cache` в `PUT /api/persona` (global).
- Per-chat имя-триггер не поддерживается (sync-путь не может ждать PG) — зафиксировать в ARCH.

### 3.4. `persona_traits`: генерация в «Глубоком сне»

Точка: `services/dream_worker.py::_run_deep_once` (`:1140+`), новый `_run_persona_traits_once(chat_id)` после успешной записи парадигм, при `flags.persona_enabled AND flags.deep_sleep_enabled`.

1. Источники: свежие self-факты (`origin='bot_self_reply'`) + beliefs/paradigms чата (наблюдаемое поведение, не «галлюцинации»).
2. Промпт `PERSONA_EVOLUTION_PROMPT` (код-константа `services/dream_prompts.py`, не PG): «Как изменился характер бота за период? Верни строго JSON-массив коротких наблюдений».
3. Вызов `LLMClient.generate_worker("background")` (deep-sleep-роль); fail-open при ошибке.
4. Парсинг JSON-массива строк → нормализация (cap 200) → дедуп (`lower(btrim)`) + FIFO-cap `PERSONA_TRAITS_MAX` → `append_traits`.
5. Токены — существующий `worker_budget`; отдельный cap не вводится (гейт — флаг).
6. `persona_state.last_trait_at/status` (`ok|empty|error`).

### 3.5. Чтение/запись

- **Чтение** (промпт/API/лента): `resolve_bot_persona` + `get_traits`.
- **Запись** (F3): `PUT /api/persona` → per-chat UPSERT (после `ensure_scope_profile`), global UPSERT; `reset:true`/`DELETE` → удаление override; optimistic-токен `updated_at` (409).
- `dynamic_traits` — read-only через API (пишет только worker).

---

## §4. Файлы и точки изменения (`file:line` на HEAD `2edc65b`)

| Файл | Точка | Изменение |
|---|---|---|
| `services/pg_db.py` | `DDL_STATEMENTS` | +`personas`, +`persona_traits`, +`ALTER persona_state` (traits), +сид глобальной персоны |
| `services/bot_persona.py` | новый | §3.1 |
| `services/direct_chat_service.py` | `handle` `:575-578` | склейка persona-блока |
| `handlers/direct_chat.py` | `_is_direct_trigger` `:127-155` | имя-триггер (global cache) |
| `services/dream_worker.py` | `_run_deep_once` `:1140` | вызов `_run_persona_traits_once`; новый метод |
| `services/dream_prompts.py` | новый | `PERSONA_EVOLUTION_PROMPT` + парсер (образец `parse_bridge_answer`) |
| `config/settings.py` | `:797+` | +`PERSONA_ENABLED`, `PERSONA_TRAITS_MAX`, `PERSONA_TRAIT_MAX_CHARS` |
| `services/param_catalog.py` | `_FLAGS` | +`FLAGS.persona_enabled` (`flags_memory`, default True) |
| `web/api/routes.py` | рядом с `/config` | `GET/PUT/DELETE /api/persona`, `GET /api/persona/health` (F4) |
| `.env.example` | `flags`-секция | +`PERSONA_ENABLED=true` |
| тесты | `tests/test_bot_persona.py`, `tests/test_persona_prompt.py`, `tests/test_dream_persona_traits.py`; расширить `test_param_catalog`, `test_direct_chat*` | §7 |

## §5. API/контракты (для F3/F4)

`GET /api/persona` (auth TMA; scope `X-Chat-Id`):
```json
{ "scope": "global" | "chat", "chat_id": -1002661910336 | null,
  "values": {"name": "...", "biography": "...", "system_prompt_overrides": "...", "is_aware_ai": true},
  "is_global": true, "persona_enabled": true,
  "dynamic_traits": [{"ts": 1757750400, "text": "...", "source": "deep_sleep"}] }
```

`PUT /api/persona` (RBAC: global — action `edit_persona` + global admin; chat — action `edit_persona` или секция `content`):
```json
{ "name": "Костик", "biography": "", "system_prompt_overrides": "...", "is_aware_ai": false, "reset": false }
```
- partial; chat-scope UPSERT; `reset:true` → `DELETE` строки чата; global UPSERT.
- Валидация: строки ≤ 8192; `is_aware_ai` bool. Ошибки: 403/409/422/503.

`GET /api/persona/health` (global admin) — §F4: `{traits_count, last_trait_at, extractor_status, extractor_last_at}`.

## §6. Конфиг/дефолты — §2.4.

## §7. Тест-план

1. **PG DDL/сид:** `PgDatabase.init()` дважды идемпотентно; ровно одна глобальная и одна per-chat строка (partial unique);
   сид не перезатирает ручные правки; `ensure_scope_profile` перед chat-UPSERT.
2. **Резолв:** per-chat → global → empty; сброс override возвращает global; PG down → empty (fail-open).
3. **Промпт-блок:** OFF/пусто → `""` (байт-в-байт); ON+поля → точный блок; пустые секции опущены; `is_aware_ai=false` → запрет.
4. **Имя-триггер:** кэш глобального имени поднимает direct; гейт `flags.persona_enabled`; пусто → без изменений.
5. **Трейты:** генерация (ok/empty/error), дедуп, cap 50/FIFO, длина 200, `ORDER BY created_at DESC`, `source`.
6. **Метрики:** `get_persona_health` = `COUNT(persona_traits)`, `MAX(created_at)`, статус из `persona_state`.
7. Отсутствие регресса F8-досье (`build_persona_card` не тронут); grep: нет `content.persona_*` в `bot_settings`.
8. Каталог-Δ: `flags.persona_enabled` (+1); сводный Δ раунда (REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / TAB_RULES 19).
9. `node --check`, полный pytest 0 failed, `git diff --check`.

## §8. Feature flag / progressive delivery

- `flags.persona_enabled` — **default True** (UPD п.2). OFF → промпт/триггер/воркер без изменений.
- Rollback = OFF + `git revert`; данные (PG-строки) безвредны; откат схемы — `DROP TABLE persona_traits, personas`.

## §9. Критерии приёмки (DoD)

- [ ] Persona хранится в PG (`personas`, `persona_traits`); scope `is_global`/`chat_id` first-class; ни одного ключа персоны в `bot_settings`.
- [ ] Scope-read/write работает (global/per-chat, reset, FK-cascade, optimistic 409).
- [ ] Блок подхватывается в промпт; `is_aware_ai=false` → жёсткий запрет; пусто → байт-в-байт.
- [ ] `persona_traits` наполняется «Глубоким сном»; записи с датой/провенансом; cap/dedup.
- [ ] Нет конфликта с F8-досье; naming задокументирован.
- [ ] `GET/PUT/DELETE /api/persona` scope-aware; контракт зафиксирован для F3/F4.
- [ ] Полный `pytest` 0 failed (база 5392); `node --check` clean; Δ каталога задокументирован.
