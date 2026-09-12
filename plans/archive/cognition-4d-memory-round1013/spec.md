# Spec F1 — `cognition-4d-memory-round1013` (4D-память: хронологический RAG)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; реализовано Step 4 @Builder, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §1. Tasks: T-1417…T-1423. Тип: backend. Приоритет: P0.
> Зависимости: нет (фундамент; F2/F3/F8 опираются на эту спекy).
> ADR: `adr-1013-3-prompt-canon-policy.md` (Prompts — PREV, не PG).

## 0. Цель

Каждый факт, извлекаемый из БД и подаваемый в контекст LLM, несёт временной
префикс `[ММ.ГГГГ | Автор: <имя>] `; факты старше порога помечаются
`(Внимание: возможно устарело)`; «Сон» группирует факты по времени и делает
вывод о динамике. Бот перестаёт воспринимать старые факты как текущие.

## 1. Объём

### In scope
- Единый хелпер префикса факта `_fact_prefix(ts, author)` — замена `_date_prefix`.
- Расширение RAG-кортежа `(origin, fact, rag_ts)` → `(origin, fact, rag_ts, author)`
  во всех точках извлечения (KNN + FTS пути `_search_graph_facts`).
- Пометка устаревания по порогу.
- `dig_into_lore` — та же выдача (через общий хелпер).
- Группировка по времени + требование динамики в каноне `DREAM_DISTILL_PROMPT`
  (+`build_dream_user` — хронологический порядок внутри кластера).
- Новый лимит каталога `limits.rag_stale_after_days` (санкционированный Δ).

### Out of scope
- Новые таблицы/DDL, изменение `kind`/`origin` CHECK.
- PG-редактируемость канона сна (см. ADR-1013-3).
- Изменение формата `[uid]`-рендера direct-контекста (R16-канон).

## 2. Схема данных

Схема НЕ меняется. Используемые существующие поля `graph_facts`:
`fact`, `origin`, `created_at`, `message_timestamp`, `target_user`, `status`,
`kind`, `weight`, `last_confirmed_at`.

- **Дата факта (F1-Q2 — РЕШЕНО):** `rag_ts = COALESCE(message_timestamp, created_at)`
  — как уже сделано в `_knn_graph_facts` (`summary_memory.py:2192-2193`) и
  `search_graph_facts_fts` (`database.py:2127+`, алиас `rag_ts`). Не `created_at`
  в одиночку: импортированная история показывает дату сообщения-источника.
- **Автор (F1-Q1 — РЕШЕНО):** `author = graph_facts.target_user`. Если пусто/
  `NULL` → сегмент автора опускается: префикс `[ММ.ГГГГ] `. Пустое
  `«Автор: »` не рендерится. Не выдумывать имя (R16).

## 3. API/контракты

Контрактов HTTP нет. Внутренние контракты:

### 3.1. Новый хелпер (`services/summary_memory.py`)
```python
def _fact_prefix(rag_ts, author=None) -> str:
    """'[ММ.ГГГГ | Автор: X] ' / '[ММ.ГГГГ] ' / ''.
    None/0/битый ts → '' (никогда не бросает; RAG не роняет мусорным ts).
    author strip; пусто/None → сегмент автора опущен."""
```
Формат месяца: `strftime("%m.%Y")` (UTC), напр. `[04.2024 | Автор: Толян] `.

### 3.2. Пометка устаревания
```python
def _stale_suffix(rag_ts, *, now: int | None = None) -> str:
    """' (Внимание: возможно устарело)' если age > порога, иначе ''."""
```
Порог: `hot.get("limits.rag_stale_after_days", settings.RAG_STALE_AFTER_DAYS)`
(дефолт **180**). Строго `>` порога (ровно 180 дней — НЕ устарело).
`now = int(time.time())`; битый/нулевой ts → без пометки. Пометка добавляется
**после текста факта** (внутри `escape_xml_text`-строки).

### 3.3. Рендер-хелпер
`_format_origin_labeled_line(item)` → строка
`"[{label}] {_fact_prefix}{text}{_stale_suffix}"`, где `item` —
3- или 4-кортеж (`origin, fact, rag_ts[, author]`); author читается при
`len(item) >= 4`. Легаси-3-кортежи дают `[ММ.ГГГГ] ` (без автора).

### 3.4. `build_rag_context`
- Ветка `origin_labels=True`: без изменений структуры, но через новый хелпер.
- Легаси-ветка (search/factcheck): `date = _fact_prefix(item[2], author)` +
  `_stale_suffix(...)`; `_RAG_PREFIXES` остаются. Байт-тесты search/factcheck
  обновляются **осознанно** (смена формата даты — требование ТЗ).

### 3.5. Точки извлечения (расширение до 4-кортежей)
- `_knn_graph_facts` — вернуть `(row["origin"], row["fact"], rag_ts, row["target_user"])`.
- `_search_graph_facts` (FTS-ветка) — `(row["origin"], row["fact"], row["rag_ts"], row["target_user"])`.
- `dedup_rag_vs_global` — не меняется (читает `item[1]`).
- `rerank_rag_facts` — использует `_format_origin_labeled_line` (автор учтён).
- Потребитель direct-пути (`direct_chat_service._build_rag_memory`, ~`:1617-1658`)
  прозрачно получает 4-кортежи; `build_rag_context(kept, origin_labels=True)`.

### 3.6. `dig_into_lore` (`services/tool_router.py`)
Все сниппеты старой базы рендерятся через `_format_origin_labeled_line`
(единая выдача). Если сейчас там свой формат — заменить на хелпер; author брать
из `target_user` соответствующей строки.

## 4. Алгоритм/псевдокод

```
now = int(time.time())
for fact in facts:
    ts    = fact.message_timestamp or fact.created_at
    author= fact.target_user
    line  = f"[{label}] {_fact_prefix(ts, author)}{escape(text)}{_stale_suffix(ts, now=now)}"
```

Валидация возраста:
```
def _stale_suffix(ts, now=None):
    if not ts: return ""
    try: ts = int(ts)
    except (TypeError,ValueError): return ""
    now = now or int(time.time())
    days = (now - ts) / 86400.0
    lim  = int(hot.get("limits.rag_stale_after_days", settings.RAG_STALE_AFTER_DAYS) or 180)
    return " (Внимание: возможно устарело)" if days > lim else ""
```

## 5. Файлы и точки изменения

| Файл | Что |
|---|---|
| `services/summary_memory.py` | `_date_prefix` :669 → `_fact_prefix`; `_format_origin_labeled_line` :681; `build_rag_context` :693; `_search_graph_facts` :2098/2144; `_knn_graph_facts` :2146/2192 |
| `services/tool_router.py` | `dig_into_lore` — единый рендер |
| `services/dream_prompts.py` | `DREAM_DISTILL_PROMPT` :20; `build_dream_user` :39 |
| `config/settings.py` | `RAG_STALE_AFTER_DAYS: int = _env_int("RAG_STALE_AFTER_DAYS", 180)` |
| `services/param_catalog.py` | `_LIMITS` += `limits.rag_stale_after_days` (group `limits_memory`) |
| `.env.example` | закомментированный плейсхолдер `RAG_STALE_AFTER_DAYS` |
| `tests/test_summary_memory*.py`, `tests/test_dream*.py`, `tests/test_tool_router*.py`, новый `tests/test_webapp_round1013_ui.py` | тесты |

Вызовы `_date_prefix` вне RAG проверить (`grep`); если таковые есть — оставить
совместимую обёртку `_date_prefix = _fact_prefix` (без автора).

## 6. Канон сна (F1-Q4 — РЕШЕНО)

Правка `DREAM_DISTILL_PROMPT` обязательна (ТЗ §1, п.3), через дисциплину
ADR-1013-3 (PREV + байт-тесты, **без** `PROMPT_MIGRATIONS`):
- Добавить в ПРАВИЛА: «5. Учитывай даты фактов. Если правило/ситуация менялись
  во времени, сформулируй ДИНАМИКУ: что было раньше и что стало теперь.»
- `build_dream_user`: рендерить факты кластера в **хронологическом** порядке
  (по `_fact_date` ASC, затем `id` ASC), сохранив лимит `max_facts` и нумерацию
  evidence (нумерация — по позиции в новом порядке).

## 7. Каталог-Δ (санкционированный)

| Ключ | Категория | Группа | Тип/дефолт | Settings-поле | per_chat |
|---|---|---|---|---|---|
| `limits.rag_stale_after_days` | limits | `limits_memory` | int / 180 | `RAG_STALE_AFTER_DAYS` | true |

Итог F1: **REGISTRY +1 (405→406)**, Settings +1 (377→378), GROUPS 90, mapped 88,
TAB_RULES 19 — без изменений. Обновить пин-тесты `test_param_catalog.py`
(Settings 378), `test_webapp_api.py`/`test_webapp_round1011_ui.py` (REGISTRY 406,
categorized 382 при текущем счёте; сверить с фактическим после всех фич).

## 8. Feature flags / progressive delivery

- Feature flag **не вводится** (render/read-path, аддитивно). Гейт — существующий
  `flags.graph_rag_enabled`. Rollback — `git revert`.

## 9. План миграций промптов

`DREAM_DISTILL_PROMPT`: `PREV_DREAM_DISTILL_PROMPT` (байт-в-байт текущий) +
новый текст + байт-тест `test_dream_prompts.py`. `PROMPT_MIGRATIONS` — **без
изменений** (канон не PG-сид; ADR-1013-3).

## 10. Тест-план

1. `_fact_prefix`: формат `[ММ.ГГГГ | Автор: X] `; без автора → `[ММ.ГГГГ] `;
   None/0/«abc» → `""`; мусорный ts не бросает.
2. `_stale_suffix`: 179 дней → нет; ровно 180 → нет; 181 → пометка; порог из
   `hot.get` переопределяет дефолт.
3. `_format_origin_labeled_line`: 4-кортеж с автором; 3-кортеж без автора;
   `escape_xml_text` сохранён.
4. `build_rag_context`: legacy-ветка (search/factcheck) — новый префикс; пустой
   список → `""`.
5. `_knn_graph_facts`/`_search_graph_facts`: возвращают 4-кортежи; `target_user`
   NULL → author None.
6. `dedup_rag_vs_global` — регресс (поведение не меняется).
7. `dig_into_lore` — сниппеты с префиксом/пометкой.
8. Dream: `build_dream_user` — хронологический порядок; канон содержит правило
   динамики; байт-тест `PREV != new`, reference == new.
9. Каталог: Settings 378, `limits.rag_stale_after_days` читается `hot.get`.

## 11. Риски

| Риск | Митигация |
|---|---|
| Смена формата даты ломает байт-тесты search/factcheck | Обновить осознанно; зафиксировать в PR-описании |
| 4-кортежи ломают потребителей, ждущих len==3 | Все места индексируют `[0..2]`; добавить защиту `len(item)>=4`; регресс-тесты |
| Устаревшая пометка на «вечных» фактах (created_at=now, ts=0) | ts=0 → без пометки; «вечные» имеют created_at |
| `target_user` не заполнен у chat_history | Автор опускается (F1-Q1) — осознанно |

## 12. Критерии приёмки

- [x] Все точки подачи фактов (RAG, `dig_into_lore`, дистилляция) используют
      `_fact_prefix`; старый `[%Y-%m-%d]` путь удалён/обёрнут.
- [x] Факты старше порога несут `(Внимание: возможно устарело)`; граница ровно
      180 — без пометки.
- [x] `DREAM_DISTILL_PROMPT` группирует по времени и требует динамику; PREV-слепок
      + байт-тест на месте.
- [x] Порог/формат — через `hot.get`, без хардкода в хендлерах.
- [x] `pytest` 0 failed (5235 passed), `node --check web/app.js` clean,
      `git diff --check` чист; каталог-Δ (406/378/382) сверена.
- [x] Ноль PG-DDL; SQLite v8; порядок роутеров `bot.py` не тронут.

## 13. Разрешение open questions (F1)

- **F1-Q1** — нет автора → `[ММ.ГГГГ] ` (сегмент опущен). Источник автора — `target_user`.
- **F1-Q2** — возраст по `COALESCE(message_timestamp, created_at)` (`rag_ts`).
- **F1-Q3** — новый каталог-параметр `limits.rag_stale_after_days` (Δ +1), не константа.
- **F1-Q4** — правка канона обязательна; PREV+байт-тесты; `PROMPT_MIGRATIONS` не трогаем (ADR-1013-3).
