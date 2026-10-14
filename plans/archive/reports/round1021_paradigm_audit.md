# T-1972 — READ-ONLY аудит: почему мета-слой (Парадигмы / Deep Sleep) пуст

- **Фича:** F4 `paradigm-thresholds-consolidation-round1021` (ADR-1021-4).
- **Дата:** 18.09.2026, раунд 10.21. **Автор:** @Builder (Step 4).
- **Метод:** только чтение — код-дефолты `config/settings.py`, `PRAGMA table_info`
  и `COUNT(*)` по доступным БД в режиме `mode=ro`; мутаций нет.
- **Артефакт-копия (spec §3.1):** `plans/reports/round1021_paradigm_audit.md`.

## 1. Фактические значения флагов (env + код-дефолты)

| Флаг | Факт | Источник |
|---|---|---|
| `DREAM_ENABLED` | **False** | код-дефолт; ключа в `.env` нет |
| `DEEP_SLEEP_ENABLED` | **False** | код-дефолт; ключа в `.env` нет |
| `BELIEF_DECAY_ENABLED` | **False** | код-дефолт; ключа в `.env` нет |

Пороги (только для справки — они здесь **ни при чём**):
`DREAM_REPEAT_THRESHOLD=2`, `DREAM_IMPORTANCE_SUM_THRESHOLD=8`,
`DEEP_SLEEP_TOP_K=20`, `DEEP_SLEEP_MAX_PARADIGMS=3`,
`DEEP_SLEEP_TOKENS_PER_DAY=40000`, `DEEP_SLEEP_TRIGGER='after_sleep'`.

## 2. Состояние памяти в доступных БД

| БД | `memory_dream_log` | `dream_state` | `graph_facts` | `smart_messages` | парадигмы |
|---|---|---|---|---|---|
| `local_database.db` (~12 КБ) | нет (только `smart_cache`) | нет | нет | нет | 0 |
| `local_database_2026-09-04_history.db` (~755 МБ) | **нет** | **нет** | 10 447 | 1 928 453 | 0 |

Снапшот истории **старше** контуров F2/F3: в его `graph_facts` вообще нет колонок
`kind`/`belief_meta` — маркер парадигмы физически не мог быть записан. Строк
`memory_dream_log` нет ни в одной БД → **0 успешных обычных «снов» и 0
deep-прогонов**.

## 3. Точка обрыва (цепочка гейтов)

```
DREAM_ENABLED=False (default)
   └─ обычный «сон» DreamWorker не дистиллирует ⇒ memory_dream_log(kind='run') = 0
        └─ хук after_sleep (_maybe_deep_after_sleep) не срабатывает: нет stats с distilled>0
             └─ DEEP_SLEEP_ENABLED=False (default) — независимо глушит deep-прогон
                  └─ память_dream_log(kind='deep_run') = 0
                       └─ belief_meta.type='paradigm' = 0 ⇒ мета-слой пуст
```

**Вывод:** `break_point = flags_off`, **ветвь A** (spec §3.3). Пороги
`DREAM_*`/`DEEP_SLEEP_*` и кап `MAX_PARADIGMS` — **не причина**; их снижение/
поднятие без включения флагов эффекта не даст.

## 4. Решение по порогам (T-1974)

- Ветвь A: **пороги не меняем** (менять нечего — обрыв на рубильниках).
- Принудительное снижение (UPD Д11=да) разрешено и **реализовано** как
  идемпотентная обратимая PG/DML-миграция `migrate_deep_sleep_thresholds`
  (`services/config_migrations.py`, прецедент `migrate_dream_thresholds`), но
  по умолчанию **выключено** (`DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED=False`,
  env-only ClassVar, Δ каталога = 0) — активируется оператором только при
  ветке B/C по факту прод-аудита.
- Санкционированное действие ветки A (ops): включить `memory.dream_enabled` и
  `flags.deep_sleep_enabled` (per-chat/global), после чего — при необходимости
  — ручная консолидация `python manage.py memory consolidate`.

## 5. Проверка выходных данных

- Счётчики `paradigms_total`, `paradigms_last_run`, `dream_runs_7d`,
  `deep_sleep_skipped_reasons` добавлены в `services/memory_health.py`
  (T-1978), fail-open, R17-safe (числа/коды причин).
- READ-ONLY: во время аудита ни одна БД не изменялась (соединения `mode=ro`,
  DDL/DML не выполнялись).

## 6. Документирование gate-миграции порогов (fix-round 10.21)

- **Флаг** `DEEP_SLEEP_THRESHOLD_MIGRATION_ENABLED` (env-only ClassVar,
  default **false**) продублирован в `.env.example` (секция «Глубокий сон»)
  с пояснением: PG-миграция `migrate_deep_sleep_thresholds` вручную снижает
  cooldown глубокого сна `memory.deep_sleep_min_interval_hours` **20 → 6**.
- **20** — исходный код-дефолт (ветка A); **6** — целевое значение, которое
  применит миграция при активации оператором (ветка B/C). По умолчанию
  миграция выключена, каталог не меняется (Δ = 0).
- Обратимость: снижение — идемпотентный DML-шаг; откат — возврат значения
  20 (миграция не трогает кастомные значения, отличные от 20).
