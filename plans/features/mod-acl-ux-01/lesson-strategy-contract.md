# Контракт уроков опыта (MOD-ACL-UX-01 amendment, 2026-11-09)

**Источник:** `plans/owner_inputs/2026-11-09-lesson-strategy-human-gate.md`
**Статус:** FROZEN — реализация без нового Human Gate
**Слот схемы:** v43 (следующий после prod v42; `CREATE … IF NOT EXISTS`)
**Линия реализации:** `integ/unify-release`
**Зависимость:** VMQ-ONTO-01 — cross-epic (QN-направление); не блокирует данный контракт.

---

## 1. Семантический контракт урока (расширение существующих таблиц v28)

### 1.1 Новые поля в `mca_lessons` (ALTER, v43)

```sql
ALTER TABLE mca_lessons ADD COLUMN confirmation_count  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE mca_lessons ADD COLUMN independent_sources TEXT;   -- JSON array of source_ref_id
ALTER TABLE mca_lessons ADD COLUMN origin_kind         TEXT;   -- 'semantic'|'detector'|'technical'|'explicit'
ALTER TABLE mca_lessons ADD COLUMN semantic_rule_key   TEXT;   -- R17-safe token (не сырой текст)
ALTER TABLE mca_lessons ADD COLUMN semantic_scope_key  TEXT;   -- 'chat:<id>'|'user:<id>'|'global'
ALTER TABLE mca_lessons ADD COLUMN temporal_rank       REAL NOT NULL DEFAULT 1.0;  -- адаптивный вес
ALTER TABLE mca_lessons ADD COLUMN superseded_at       INTEGER;  -- NULL пока актуален
```

Инварианты:
- `recommendation` содержит **только сервер-канонические формулировки** — токен из `CANONICAL_RECOMMENDATIONS`
  ИЛИ строку из `mca_lessons_semantic_templates` (§1.2). Сырые реплики пользователя — запрещены (R17).
- `semantic_rule_key` — R17-safe токен `^[A-Za-z0-9_.:\-]{1,64}$`; в нём нет UID/текста.
- `independent_sources` — JSON-массив `source_ref_id`; дубли одного source_ref не считаются независимыми.
- `confirmation_count` обновляется только при **независимом** подтверждении (разный `source_ref_id`).
- `temporal_rank` ∈ [0.0, 2.0]; снижается только адаптивно по противоречиям, **не** по возрасту.
- Старые версии урока сохраняются: `superseded_at` заполняется, `status='superseded'`, запись не удаляется.

### 1.2 Новая таблица `mca_lessons_semantic_templates` (CREATE IF NOT EXISTS, v43)

```sql
CREATE TABLE IF NOT EXISTS mca_lessons_semantic_templates (
    template_id   TEXT PRIMARY KEY,          -- R17-safe токен
    lesson_type   TEXT NOT NULL,             -- из LESSON_TYPES
    rule_key      TEXT NOT NULL,             -- semantic_rule_key
    template_text TEXT NOT NULL,             -- сервер-каноническая формулировка
    scope_pattern TEXT NOT NULL DEFAULT 'any', -- 'chat'|'user'|'global'|'any'
    origin_kinds  TEXT NOT NULL,             -- JSON array: ['semantic','explicit',…]
    created_at    INTEGER NOT NULL,
    UNIQUE(lesson_type, rule_key)
);
```

Назначение: расширяет `CANONICAL_RECOMMENDATIONS` за пределы замкнутого каталога. Builder
добавляет строки миграцией; существующий каталог переносится в таблицу при v43 с `origin_kinds='["detector","technical","explicit"]'`.

---

## 2. Политика порогов (configurable defaults)

### 2.1 Правило выбора порога по типу урока

| Тип / условие                     | `confirmation_count` для `validated` | Где хранится порог |
|---|---|---|
| Повторяющийся локальный паттерн   | **2** независимых наблюдения          | `experience.lesson_min_local_confirmations` |
| Явная просьба участника           | **1**                                 | `experience.lesson_min_explicit_confirmations` |
| Проверяемая техническая ошибка    | **1**                                 | `experience.lesson_min_technical_confirmations` |
| Глобальный scope                  | **3** (прежний дефолт — строже)       | `experience.lesson_min_global_confirmations` |
| Гипотеза LLM без явного сигнала   | **никогда автоматически** (`recheck_required=1`) | — |

Локальное усвоение всегда проще глобального: `lesson_min_local_confirmations ≤ lesson_min_global_confirmations`.
Это инвариант, проверяемый тестом `test_lesson_threshold_local_le_global`.

### 2.2 Новые ParamSpec (добавить в `param_catalog.py`, группа `memory_experience`)

```python
("EXPERIENCE_LESSON_MIN_LOCAL_CONFIRMATIONS",
 "Уроки: мин. подтверждений (локальный)", "int", "memory_experience",
 "Сколько независимых наблюдений нужно для повторяющегося локального паттерна. "
 "По умолчанию 2.", "advanced"),

("EXPERIENCE_LESSON_MIN_EXPLICIT_CONFIRMATIONS",
 "Уроки: мин. подтверждений (явный запрос)", "int", "memory_experience",
 "Минимум для явной просьбы участника или проверяемой технической ошибки. "
 "По умолчанию 1.", "advanced"),

("EXPERIENCE_LESSON_MIN_GLOBAL_CONFIRMATIONS",
 "Уроки: мин. подтверждений (глобальный)", "int", "memory_experience",
 "Минимум для уроков с scope=global. По умолчанию 3.", "advanced"),
```

pg_id-ключи: `experience.lesson_min_local_confirmations` / `…explicit…` / `…global…`.
Дефолты хранятся рядом с ParamSpec; hot-чтение через `chat_params.get_chat_param`; нет рестарта.

---

## 3. Безопасное ослабление каталога (без копирования пользовательского текста в промпты)

### 3.1 Четыре стадии — изолированные write-пути

```
detect (classifier/semantic LLM) → mca_experience_feedback (candidate ≠ fact)
                                  ↓
confirm (ExperienceReviewRunner, independent_sources count ≥ threshold)
                                  ↓
activate (status=validated→active, temporal_rank=1.0)
                                  ↓
apply (Writer context, только ID + template_text из §1.2; никакого сырого текста)
```

Гарантии:
- Стадия `detect` пишет только `feedback` + код причины; никакого урока.
- Стадия `confirm` использует `template_text` из `mca_lessons_semantic_templates`
  ИЛИ `CANONICAL_RECOMMENDATIONS`; `recommendation` поля всегда из этих двух источников — никогда из реплики.
- Стадия `apply`: Writer получает `(lesson_id, recommendation, scope, temporal_rank)`;
  текст реплики пользователя **не передаётся** в system/developer-content.
- Противоречие: новый сигнал снижает `temporal_rank` на противоречащий урок и
  помечает `recheck_required=1`; старая версия остаётся, не стирается.

### 3.2 Проверка противоречий (контракт)

При активации нового урока `ExperienceReviewRunner` проверяет:
- Есть ли в том же `(scope_chat_id, scope_user_id, lesson_type)` активный урок с пересекающимся `semantic_scope_key`.
- Если да: старый получает `temporal_rank *= 0.5`, `recheck_required=1`, `status` **не меняется** (история сохранена).
- Противоречие фиксируется в `mca_events` (event_type=`experience.lesson_contradiction`).

---

## 4. Гибридное расписание: свежий поток + архив

### 4.1 Текущий throughput-gap и исправление (немедленно, без VMQ)

| Параметр | До исправления | После |
|---|---|---|
| `SEMANTIC_PER_CHAT_MAX` | 10 строк/тик | **50** строк/тик |
| `SEMANTIC_CHATS_PER_PASS` | 4 чата | **6** чатов |
| Tick-период | 900 с | 900 с (без изменений) |
| Ёмкость/сутки | ~5.7k сообщений | ~28.8k сообщений |
| Archival cursor scope | нет | отдельный `archive_cursor:<chat_id>` в payload |

Значения делаются configurable через `experience.semantic_per_chat_max` и
`experience.semantic_chats_per_pass` (новые ParamSpec, группа `memory_experience`).

### 4.2 Архивный курсор (durable, per-chat, в payload job)

```python
# ключ в payload ExperienceReviewRunner
ARCHIVE_CURSOR_PREFIX = "archive_cursor:"   # + str(chat_id)
ARCHIVE_WATERMARK_KEY = "archive_watermark" # глобальная нижняя граница
```

- `archive_cursor:<chat_id>` содержит `{"rowid": int, "last_ts": int, "coverage_year": int|null}`.
- Прогресс курсора не сбрасывается при рестарте сервиса (durable в `task_jobs.payload`).
- `archive_watermark` = min по всем per-chat курсорам; выставляется в аналитику.
- Архивные батчи ограничены `experience.archive_per_run_max` (ParamSpec, дефолт 200 строк).
  Архивный шаг выполняется **после** свежего в том же RunLoop, только если budget остался.

### 4.3 Взвешенное исследование временных областей (до VMQ — существующий RandomSource)

Направление выбора архивного chat/year определяется по весу:

```
weight(chat, year) = staleness_days(chat, year) × informative_score(chat, year)
                     × (1 / max(1, recent_visits(chat, year, window=30d)))
```

- `staleness_days` = текущая дата − `last_archive_scan_ts`; настраиваемый дефолт 365.
- `informative_score` ∈ [0.1, 1.0] — нормированное число неисследованных `mca_experience_feedback` в области.
- `recent_visits` — счётчик в payload, сбрасывается каждые 30 дней (адаптивно, без жёстких календарных периодов).
- Выбор: `random.choices(candidates, weights=...)` через **единственный существующий** `RandomSource` (без второго генератора).
- После VMQ: `RandomSource` заменяется QN-навигацией через **тот же контракт** (plug-in точка); изменений в `ExperienceReviewRunner` не требуется кроме инициализации `RandomSource`.

### 4.4 Временная применимость и адаптивный ранг (инварианты)

- Свежий/повторно подтверждённый урок: `temporal_rank` увеличивается на `+0.1` за каждое
  повторное независимое подтверждение (cap 2.0).
- Возраст записи **сам по себе не снижает** `temporal_rank`.
- `temporal_rank` снижается только при: зафиксированном противоречии (×0.5), явной отмене участника (×0.0 → suspend), ручном reset владельца.
- При выборе уроков для Writer: сортировка по `temporal_rank DESC, last_validated_at DESC`; при равном ранге предпочитаются более свежие.

---

## 5. Аналитика (обязательные события и поля)

Все новые события — через единственный `emit_mca_event` (mca-13); никакого нового sink.

| Событие | Поля |
|---|---|
| `experience.fresh_stream_lag` | `chat_id, lag_rows, cursor_rowid, ts` |
| `experience.archive_coverage` | `chat_id, year, scanned_rows, total_rows, last_ts` |
| `experience.lesson_candidate` | `lesson_type, origin_kind, scope, confirmation_count` |
| `experience.lesson_activated` | `lesson_id, lesson_type, scope, temporal_rank` |
| `experience.lesson_rejected` | `reason_code, lesson_type, origin_kind` |
| `experience.lesson_contradiction` | `lesson_id_old, lesson_id_new, scope_key` |
| `experience.archive_direction_selected` | `chat_id, year, weight, selector='qn'|'random'` |
| `experience.stale_belief_flagged` | `lesson_id, temporal_rank, days_since_confirmed` |

Счётчики в job-payload (доступны через admin-API): `candidates_total`, `lessons_activated`,
`lessons_rejected_by_reason`, `archive_rows_scanned`, `fresh_rows_scanned`, `contradictions_found`.

---

## 6. Staged Builder plan

### Шаг 1 — Схема v43 + ParamSpec (сериализованно, один файл)
**Файлы:** `services/db_migrations.py` (ALTER v43), `services/param_catalog.py`
**Проверка Reviewer:** `test_v43_schema_idempotent`; миграция на копии реальной БД; новые поля NULL-safe для старого кода.

### Шаг 2 — Threshold policy в ExperienceReviewRunner
**Файлы:** `services/mca_experience.py` (константы, новые дефолты), `services/mca_experience_jobs.py` (`_choose_threshold`)
**Проверка Reviewer:** `test_lesson_threshold_local_le_global`; `test_threshold_explicit_1`; `test_threshold_local_2`; `test_llm_hypothesis_never_auto_validated`.

### Шаг 3 — Семантические шаблоны + ослабление каталога
**Файлы:** `services/mca_experience.py` (`mca_lessons_semantic_templates` read), `services/mca_experience_jobs.py` (`_resolve_recommendation`)
**Инвариант:** `recommendation` всегда из таблицы/`CANONICAL_RECOMMENDATIONS`; тест `test_no_raw_user_text_in_recommendation`.

### Шаг 4 — Throughput fix + архивный курсор
**Файлы:** `services/mca_experience_jobs.py` (`SEMANTIC_PER_CHAT_MAX=50`, `SEMANTIC_CHATS_PER_PASS=6`, `ARCHIVE_CURSOR_PREFIX`, `_run_archive_batch`)
**Проверка Reviewer:** `test_archive_cursor_durable`; lag-счётчик выставляется при превышении `experience.fresh_stream_lag_warn_threshold`.

### Шаг 5 — Взвешенное исследование + temporal_rank
**Файлы:** `services/mca_experience_jobs.py` (`_pick_archive_direction`, `_update_temporal_rank`)
**Проверка Reviewer:** `test_temporal_rank_age_no_decay`; `test_contradiction_halves_rank`; `test_archive_direction_weights`.

### Шаг 6 — Аналитика (события + payload-счётчики)
**Файлы:** `services/mca_experience_jobs.py` (emit-вызовы), admin-API endpoint (read-only)
**Проверка Reviewer:** каждое из 8 событий §5 тестируется на mock-emit; счётчики job-payload сохраняются между рестартами.

**Параллельная безопасность:** шаги 1–3 SERIALIZE (схема/каталог); шаги 4–6 READ_ONLY_PARALLEL по продуктовому коду, SERIALIZE по одному файлу `mca_experience_jobs.py`. Шаги не объединять в одном PR.

**Гейт:** `MCA_EXPERIENCE_LEARNING_ENABLED` (существующий; catalog key `flags.experience_learning_enabled`). Новые поля OFF-safe (NULL/0). Отдельный аварийный env-ключ не нужен.

**Откат:** ALTER-поля инертны для старого кода; флаг OFF → baseline. Schema rollback деструктивно не нужен.

---

## LESSONS CONTRACT FROZEN

**Defaults:**
- `experience.lesson_min_local_confirmations` = **2**
- `experience.lesson_min_explicit_confirmations` = **1**
- `experience.lesson_min_technical_confirmations` = **1**
- `experience.lesson_min_global_confirmations` = **3**
- `experience.semantic_per_chat_max` = **50**
- `experience.semantic_chats_per_pass` = **6**
- `experience.archive_per_run_max` = **200**
- `temporal_rank` initial = **1.0**, contradiction factor = **0.5**, cap = **2.0**, increment per reconfirmation = **+0.1**

QN-интеграция: cross-epic зависимость VMQ-ONTO-01, не блокирует реализацию. Plug-in точка — `RandomSource` в `_pick_archive_direction`; до VMQ используется стандартный `random.choices`.
