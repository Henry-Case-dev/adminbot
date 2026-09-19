# spec.md — F4 `dynamic-anticliche-cache-round1023`

> **Раунд 10.23** · Приоритет **P1** · Шаг 2 @Architect (часть 2/3) · Тип: backend (worker/PG-DDL/detector) + API
> **ADR:** `ADR-1023-4.md` (Accepted). **Задачи:** `tasks.md` (T-2126…T-2135).
> **ТЗ:** `plans/current_task.md`, «Dynamic Anti-Cliche Cache (Динамический фильтр)» (untracked; секреты не цитируем — R17/R18).
> **Сквозной архитектурный документ:** `plans/features/round1023-architecture.md` (§1 F4, §3.4 DDL, §5 ступени, §8).
> **Baseline:** HEAD `731a845`; pytest **6962/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; прод `a8a6437`.
> **Зависит от:** F3 (validator-loop и режимы Вербализатора). **Ступень канона:** позиция F4 в контуре F1→F2→F3→**F4**→F6 (в этой фиче канон **не меняется** — см. §5).

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Захардкоженный список клише (коды `as_ai`, `classic_genre`, `summing_up`, `in_conclusion`, `hope_helped`, `you_asked_before`, `mirror_no_you`, `bullet_list`) | `services/negative_constraints.py:49` `FORBIDDEN_CLICHE_PATTERNS` |
| Публичный детектор (чистая функция, синхронный, без I/O) | `services/negative_constraints.py:100` `find_forbidden_cliches(text, enabled_rules=None)` |
| Validator-loop (брак + ≤2 ретрая, fail-open) | `services/negative_constraints.py:132` `verbalize_validated(...)` |
| Системный промпт ретрая | `services/prompt_style_blocks.py:62` `CLICHE_RETRY_SYSTEM_PROMPT` |
| Scrubber режет **только** `<thought>`/`fact:\d+`/`msg:\d+` (клише — нет) | `services/outgoing_guard.py:47` `sanitize_outgoing` |
| Открытый техдолг | **S10.22-4b** (Info) — `as_ai` ложно срабатывает при запятой: «Он, как искусственный интеллект…» → `['as_ai']` |
| Планировщик фоновых джобов (APScheduler, MemoryJobStore, max_instances=1, coalesce) | `services/memory_maintenance.py:57`, `services/lore_worker.py:266`, `services/nostalgia_worker.py` |
| Идемпотентный PG-DDL | `services/pg_db.py:33` `DDL_STATEMENTS` (выполняются в `init()` циклом), сиды `_seed_*` |
| Идемпотентные DML-миграции данных | `services/config_migrations.py` (`migrate_*`, вызов из `bot.py main()`) |
| Кэш конфига в процессе (без PG на каждый вызов) | `services/hot_config.py` (`hot.get`, `set_config_cache`) |

### 0.1. Ключевое противоречие ТЗ (решается ADR-1023-4)

ТЗ (строка 46) буквально требует: *«Динамически подставляйте `{dynamic_cliche_list}` в системный промпт Вербализатора. Если сгенерирован текст с этими словами — Regex Scrubber бракует ответ…»*.

Это **прямо нарушает** два инварианта раунда (`round1023-architecture.md` §4):
1. **validator-loop без regex-реза клише** — клише только бракуются и регенерируются, клише кодом **не** вырезаются (вето владельца 10.22).
2. **«список клише живёт в коде»** + grep-тест отсутствия тропов в промпт-константах — вставка динамического списка в промпт ломает оба.

**Решение (ADR-1023-4):** динамический список питает **ДЕТЕКТОР** (`find_forbidden_cliches` → `verbalize_validated`), а **не** подменяет канон-список в промпте и **не** становится scrubber'ом. Захардкоженный `FORBIDDEN_CLICHE_PATTERNS` остаётся нетронутым. Это ровно то, что уже зафиксировано в `round1023-architecture.md` §1 и `tasks.md` («динамический кэш должен питать детектор … а не подменять канон-список в промпте»).

---

## 1. Цель

Раз в неделю фоновый воркер забирает источник (статья «Wikipedia:Signs of AI writing» или словарь клише с GitHub), просит LLM извлечь ~20 популярных ИИ-паттернов и кладёт нормализованный JSON-список (стабильные коды + литеральные фразы + источник + дата) в PG-кэш. Динамические правила **дополняют** детектор `find_forbidden_cliches`, который используется в `verbalize_validated` (браковка ответа + ≤2 ретрая Вербализатору). Никакого regex-реза клише; никаких динамических фраз в промптах. Заодно закрывается S10.22-4b.

---

## 2. Требуемое поведение

### 2.1. Источник и воркер

- Источник по умолчанию: `https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing` (Wikipedia REST/action API) **или** словарь клише с GitHub. URL/канал — данные в PG-кэше (`source`), дефолт — код-константа (Δ каталога = 0).
- Периодичность: **раз в неделю** (`IntervalTrigger(days=7)`, jitter, `max_instances=1`, `coalesce=True`, `misfire_grace_time` — как у `lore_worker`/`memory_maintenance`). Воркер — реактивный фон, отдельного LLM-вызова в пользовательском пути нет.
- Воркер: скачивает источник → LLM-промпт «извлеки ~20 популярных паттернов ИИ-письма» → **строгий JSON** `{"patterns":[{"phrase":"...","origin":"..."}]}` → нормализация/дедуп/лимит → запись в кэш.
- Устойчивость: сбой источника/LLM/записи → **предыдущий кэш сохраняется**, ошибка логируется R17-safe (класс/код, без сырого текста и без фраз клише).

### 2.2. Хранение (PG, идемпотентный DDL)

Новая таблица **`anticliche_cache`** (singleton-строка):

| Колонка | Тип | Смысл |
|---|---|---|
| `id` | `SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1)` | singleton |
| `patterns` | `JSONB NOT NULL DEFAULT '[]'::jsonb` | список `[{"code","phrase","origin","added_at"}]` |
| `source` | `TEXT NOT NULL DEFAULT ''` | идентификатор источника (`wikipedia`/`github`/`manual`) |
| `source_url` | `TEXT NOT NULL DEFAULT ''` | URL источника (без секретов) |
| `version` | `INTEGER NOT NULL DEFAULT 0` | растёт при успешной записи/ручной правке |
| `fetched_at` | `TIMESTAMPTZ` | время забора источника |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | время записи строки |
| `last_status` | `TEXT NOT NULL DEFAULT 'never'` | `never|ok|fetch_error|llm_error|parse_error` (R17-safe) |

Индекс: `CREATE INDEX IF NOT EXISTS idx_anticliche_cache_updated ON anticliche_cache (updated_at DESC)` (для метаданных; таблица singleton — индекс дешёвый). Опционально seed-строка `INSERT ... (id) VALUES (1) ON CONFLICT DO NOTHING`.

> **Развилка SQLite/PG закрыта:** кэш — **PG** (см. §4). SQLite остаётся **v12** (Δ SQLite DDL = 0).

### 2.3. Нормализация и лимиты (защита от мусора и инъекций)

- Фраза динамического правила — **только литеральная строка** (НЕ regex). На детекторе она компилируется через `re.escape`. Произвольные regex/скобки не принимаются.
- Нормализация фразы: `lower`, `ё→е`, схлопывание пробелов; длина 2…120 символов; отбрасывание пустых/служебных.
- Лимит: **≤ 20** правил (конфигурируемо код-константой `ANTICLICHE_MAX_PATTERNS = 20`; Δ каталога = 0).
- Дедуп:
  - между динамическими — по нормализованной фразе;
  - с захардкоженными — фраза, которая уже ловится `find_forbidden_cliches(phrase, DEFAULT_ENABLED_RULES)`, **пропускается** как избыточная.
- Стабильный код: `"dyn_" + sha1(normalized_phrase).hexdigest()[:8]` (детерминирован, не зависит от порядка/запуска).
- **Fail-open:** недоступен PG/битый JSON → динамические правила отсутствуют, работает только захардкоженный детектор (байт-в-байт прежнее поведение).

### 2.4. Подача в детектор (контракт)

`services/negative_constraints.py` — **аддитивное** расширение:

```python
@dataclass(frozen=True)
class DynamicClicheRule:
    code: str
    phrase: str

def find_forbidden_cliches(
    text: str,
    enabled_rules: frozenset[str] | set[str] | None = None,
    dynamic_rules: Iterable[DynamicClicheRule] | None = None,   # НОВОЕ, опционально
) -> list[str]: ...

async def verbalize_validated(
    generate_call, base_messages, *,
    max_retries=2, scrubber=sanitize_outgoing,
    enabled_rules=None,
    dynamic_rules: Iterable[DynamicClicheRule] | None = None,   # НОВОЕ, проброс
) -> tuple[str, dict]: ...
```

- `dynamic_rules=None` → поведение **байт-в-байт** прежнее.
- Компиляция `re.escape(phrase)` (+ `\b` по краям, если фраза начинается/кончается на словесный символ), поиск по **нормализованному** тексту (та же `_normalize`, что и сейчас). Кэш скомпилированных шаблонов по `phrase` (модульный dict, bounded).
- Возвращаются только **коды** (`dyn_xxxxxxxx`) — R17: matched-подстроки наружу не отдаются.
- Scrubber по-прежнему **не** режет клише (`outgoing_guard.ExtraPatterns` не пополняется).

### 2.5. Резолв правил в оркестраторах (без PG на каждый ответ)

- Новый модуль `services/anticliche_cache.py`:
  - `async def fetch_cache(pg) -> dict` — чтение singleton-строки (fail-open → `{}`);
  - `def get_rules() -> tuple[DynamicClicheRule, ...]` — **in-process memoized** список (резолв из runtime-кэша/PG один раз, инвалидация после форс-обновления/ручной правки);
  - `def invalidate() -> None`, `def set_runtime_pg(pg)` (DI из `bot.py`, прецедент `worker_budget.set_worker_budget_pg`).
- Оркестраторы Stage-2 (фактчек/прямой чат/саммари) при вызове `verbalize_validated(...)` передают `dynamic_rules=anticliche_cache.get_rules()`. При выключенном флаге/пустом кэше — `None`.
- **Инвариант:** детектор остаётся синхронной чистой функцией; I/O загрузки кэша — только в оркестраторе/кэш-модуле.

### 2.6. Фикс S10.22-4b

Ложное срабатывание `as_ai` при запятой: «Он, **как** искусственный интеллект, не устаёт». Причина — lookbehind `(?<!\bон\s)` не видит «он, » (между субъектом и «как» стоит «, »). Фикс: добавить к третьеличному правилу симметричные comma-варианты (regex фиксированной ширины — Python `re` не поддерживает variable-length lookbehind):

```
(?<!\bон,\s)(?<!\bона,\s)(?<!\bоно,\s)(?<!\bэто,\s)
(?<!\bлюди,\s)(?<!\bчеловек,\s)(?<!\bсебя,\s)
```

Регресс-тесты: «Он, как искусственный интеллект, не устаёт» → `[]`; «Люди, как искусственный интеллект, ошибаются» → `[]`; первое лицо «Я, как ИИ, …» → `['as_ai']` (сохраняется); «она, как языковая модель» → `[]`.

### 2.7. API мониторинга (админ, R16-аддитивно)

Новый router или аддитивные хэндлеры в `web/api/routes.py` (RBAC — глобальный админ, как `/api/workers/budget`):

- `GET /api/anticliche` → `{updated_at, fetched_at, source, source_url, version, last_status, count, max_patterns, patterns:[{code, phrase, origin}]}`. Фразы отдаются админу (UI F8), в логи не пишутся.
- `POST /api/anticliche/refresh` → форс-обновление (ручной запуск воркера), возвращает `{status, count, version, source}`; коды/статусы, без сырья.
- `PUT /api/anticliche` → ручная правка списка (`{"patterns":[{"phrase","origin"}]}`), нормализация/дедуп/лимит на сервере, `source='manual'`, `version+1`, `invalidate()`.
- Ручная правка **не трогает** захардкоженный список и не пишет в промпты.

---

## 3. Изменения по файлам

| Файл | Тип изменения |
|---|---|
| `services/negative_constraints.py` | **эксклюзив F4**: `DynamicClicheRule`, опциональный `dynamic_rules`, фикс S10.22-4b (comma-lookbehind). Scrubber-семантика не меняется |
| `services/anticliche_worker.py` | **новый** (эксклюзив F4): забор источника, LLM-извлечение, строгий parse, дедуп/нормализация, запись, APScheduler-джоб |
| `services/anticliche_cache.py` | **новый** (эксклюзив F4): чтение/резолв/runtime-кэш/инвалидация |
| `services/pg_db.py` | аддитивно: `CREATE TABLE IF NOT EXISTS anticliche_cache` + индекс + seed-строка (в `DDL_STATEMENTS`) |
| `services/config_migrations.py` | (опц.) идемпотентная seed-миграция дефолтного источника; вызов из `bot.py` |
| `services/scheduler.py` / `bot.py` | регистрация недельного джоба (APScheduler, паттерн `lore_worker`), DI `set_runtime_pg`; порядок роутеров `bot.py` не сдвигается |
| `web/api/routes.py` (+ router) | 3 админ-эндпоинта мониторинга (R16-аддитивно) |
| `services/outgoing_guard.py` | **НЕ** меняется (scrubber клише не трогает) |
| `services/prompt_style_blocks.py` / промпт-константы | **НЕ** меняется (канон F4 — no-op) |

---

## 4. Контракты/схемы БД, Δ DDL

- **PG-таблица:** `anticliche_cache` (см. §2.2). Δ **SQLite = 0**; Δ каталога = **0**.
- `bot_settings`/промпты не затрагиваются.
- Идемпотентность: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, seed `ON CONFLICT DO NOTHING`, повторный старт — no-op.
- Откат DDL: `DROP TABLE IF EXISTS anticliche_cache` безопасен (кэш, данные не пользовательские).

---

## 5. Канон / промпты (важно)

- **F4 не меняет промпт-константы.** Позиция F4 в канон-контуре (`F1→F2→F3→**F4**→F6`) в этой фиче — **no-op**: `PROMPT_MIGRATIONS`/`ROLLBACK_MIGRATIONS`/`PREV_*` **не добавляются**, `plans/docs/canon/**` не меняется.
- Промпт извлечения паттернов живёт как **код-константа** в `services/anticliche_worker.py` и не перечисляет сами клише (иначе grep-тест тропов поймает сам запрет).
- Динамические фразы из PG **никогда** не попадают в промпт-константы и не подставляются в `system`/`user` сообщения — только в детектор.
- Тест-гарант: промпт-константы (`prompt_style_blocks.py` + Stage-2 каноны) байт-в-байт; динамические фразы не встречаются в коде вне `anticsiche_worker.py`/тестов/БД.

---

## 6. План тестирования

1. **Разбор LLM-ответа:** валидный JSON → список; markdown-fences; усечённый/невалидный JSON → `[]` + статус `parse_error` (fail-open, кэш не портится).
2. **Нормализация/дедуп/лимит:** дубликаты схлопываются; >20 обрезается; фраза, ловящаяся хардкодом, пропускается; пустые/слишком длинные/не-литеральные — отбрасываются.
3. **Стабильные коды:** детерминированный `dyn_<hash>`; стабильность между прогонами.
4. **Подача в детектор:** `dynamic_rules` → соответствующие коды в `find_forbidden_cliches`; `dynamic_rules=None` → прежний результат байт-в-байт.
5. **Scrubber не режет клише:** `sanitize_outgoing` для текста с динамической фразой возвращает текст без изменений.
6. **Ретраи:** динамическое правило срабатывает → брак + ≤2 ретрая → после исчерпания лучший вариант (fail-open).
7. **S10.22-4b:** кейсы «Он, как искусственный интеллект…»/«Люди, как ИИ…» → `[]`; первое лицо сохраняется.
8. **Fail-open:** нет кэша / PG down / битый JSON / ошибка LLM → работает хардкодный детектор, воркер не падает.
9. **Идемпотентность DDL:** повторный `init()`/миграция — no-op.
10. **R17:** логи не содержат фраз/сырого текста источника/секретов; возвращаются коды/числа.
11. **R18/секреты:** в коммитах нет plaintext-ключей; отчёт без значений.
12. **Регресс:** канон-промпты и grep-тест тропов не нарушены; полный pytest **0 failed**; `node --check web/app.js` (если F8-UI ещё не влит — гейт на F4 не обязателен).

---

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | High | Динамический кэш нарушает «список в коде»/grep-тест | Хардкод не трогаем; динамика — только в детектор; промпт-константы байт-в-байт (ADR-1023-4, T-2129/T-2134) |
| R2 | High | Кэш превращается в scrubber | Клише только бракуются/ретраятся; `outgoing_guard` не меняется (T-2129/T-2133) |
| R3 | Medium | Нестабильный источник/ошибки LLM роняют воркер | fail-open, предыдущий кэш сохраняется, `last_status` (T-2128/T-2133) |
| R4 | Medium | Разрастание/мусор, regex-инъекция/ReDoS | Литеральные фразы, `re.escape`, лимит ≤20, дедуп, ручная правка (T-2127/T-2128/T-2132) |
| R5 | R17/R18 | Сырьё/секреты в логах/отчётах | R17-safe логи (коды/числа), отчёт без значений (T-2133/T-2135) |

---

## 8. Feature flag / раскатка / откат

- `DYNAMIC_ANTICLICHE_ENABLED` — env-only `ClassVar` (**default ON**, Δ каталога = 0). `bot.py`/config.
  - `OFF` → `get_rules()` возвращает `()`, воркер не регистрируется → только захардкоженный детектор (байт-в-байт 10.22).
- Поэтапная раскатка internal→10%→50%→100% **не требуется** (прецедент 10.21/10.22).
- Откат: флаг OFF / `git revert` + `DROP TABLE IF EXISTS anticliche_cache` (безопасно). Канон-миграции откатывать не нужно (канон не менялся).

---

## 9. Критерии приёмки

- Воркер по расписанию обновляет кэш; список извлекается LLM и хранится в PG (дата/источник/версия).
- Динамический список влияет на детектор/validator-loop; клише **не** вырезаются scrubber'ом.
- Ручное редактирование и форс-обновление работают (API).
- S10.22-4b закрыт регресс-тестом. Канон-промпты и grep-тест не нарушены. Полный pytest — **0 failed**.

---

## 10. Зависимости / ступени / handoff

- **Зависит от F3** (validator-loop и режимы Вербализатора).
- Ступень канона: F4 — no-op (см. §5); следующая ступень (F6) читает неизменённый канон.
- Эксклюзивы: `services/negative_constraints.py`, `services/anticliche_worker.py`, `services/anticliche_cache.py`.
- F8 потребляет API мониторинга (§2.7) для блока `dynamic_cliche_list` (UI F8, не F4).

## 11. Открытые вопросы → Human Gate

1. **Хранилище кэша:** выбран PG-таблица `anticliche_cache` (vs `bot_settings`-ключ из предварительной формулировки Part 1 §0). Подтвердить (влияет на Δ DDL: SQLite всё равно Δ0).
2. **Лимит паттернов:** 20 — подтвердить (влияет на «мусорность» детектора).
3. **Источник по умолчанию:** Wikipedia-статья vs GitHub-словарь — подтвердить приоритет (по умолчанию Wikipedia).
