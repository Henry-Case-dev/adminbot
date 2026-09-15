# Spec F7 — `memory-retention-health` (Retention `smart_messages`/логов, включение Сна/декая/воскрешений, честные метрики здоровья)

> **Раунд:** 10.19, **итерация 2** (Step 2 @Architect, 15.09.2026). **Тип:** backend/ops (`services/summary_memory.py`, `services/database.py`, `services/dream_worker.py`, `services/memory_maintenance.py`, `services/retention_policy.py` (новый), `web/api/memory_agi.py`, `config/settings.py`, `services/param_catalog.py`). **Приоритет:** **P1** (БД 724 МБ / диск 8 из 23 ГБ; память копит «склероз»).
> **ADR:** `adr-1019-6-memory-retention-health.md` + **`../budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`** (sentinel-таблица, сид настроек чатов, guard, изоляция).
> **Задачи:** T-1835…T-1844 + итерация 2: T-1863/T-1864. **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/90/406/411/88/19**; SQLite v10.
> **Источник:** `plans/current_task.md` UPD2 п.6 (строка 166) + чекап (строки 164,166) + **UPD3 п.2-3** (строки 184-207).
> **Зависимости:** F3/F4 (каталог/UI-паттерн) → **F7**; смежность F8 (`summary_memory.py`). **Конфликт файлов:** `services/param_catalog.py` (F3/F4), `config/settings.py` (F4).
>
> **🔴 UPD3 (итерация 2) — корректировки F7 (обязательны):**
> 1. **Retention — per-chat поле** «Хранение импорта (дней)»: `0` = **вечно** (иной sentinel, чем у бюджетов!), `<0` = невалидно → глобальный дефолт, `>0` = N дней.
> 2. **Целевой чат `-1002661910336`: retention = 0 (вечно)** сидом; purge импорта для него **жёстко запрещён** guard'ом (даже если кто-то выставит retention).
> 3. **Изоляция памяти (UPD3 п.2):** аудит строгой привязки импорта/памяти к `chat_id`; найден латентный дефект (`import_key` не chat-scoped при глобальном UNIQUE-индексе) — включён в §4.6 + задача.
> 4. Каталог-Δ сводится с F3/ADR-1019-8 (см. §5).

## 1. Контекст и цель

Из чекапа: **11864 факта, 667 просрочено, 40 не подтверждено**; **глубокий сон 0 прогонов, воскрешений 0, охлаждение 0**; `smart_messages` почти **2 млн строк**, БД **724 МБ**, свободно **8 из 23 ГБ**. Владелец: «система просто копит склероз… база и логи устроят драку за место».

**Цель:** объяснить и устранить причины «0 прогонов»; ввести retention для разросшейся таблицы; сделать метрики здоровья честными.

**Ключевое наблюдение (root cause по объёму):** штатные retention-пути **исключают** импортированную историю: `_compress_purge_extract_only` берёт `get_smart_raw(..., exclude_imported=True)` (`summary_memory.py:2907-2909`), а `compress_and_purge` работает с live-сырьём. Строки истории (`import_key IS NOT NULL`, 1.27M+ из архивов) графом пополняются Graph-воркером, но **никогда не удаляются** → это и есть основной драйвер ~2M строк и 724 МБ.

## 2. Текущее поведение (сверено с кодом HEAD `fd6acc7`)

- `web/api/memory_agi.py:357-382` — `memory_health_summary`: `beliefs_active/archived`, `resurrections_total`, `decay_runs_total`, `last_decay_at`; **нет** overdue/unconfirmed/размеров.
- `services/database.py:2272-2284` — `count_beliefs_by_status`; `:3972-4041` — `graph_stats` (facts/beliefs/nodes/edges).
- `services/dream_worker.py:1086-1105` — `_maybe_decay`: гейт `hot.get("flags.belief_decay_enabled", settings.BELIEF_DECAY_ENABLED)` (**default False**) → 0 прогонов.
- `services/dream_worker.py:1107-1163` — `_decay_step`; `:1192-1246` — `_try_reanimate` (условия: `_vec_available`, непустой архив, cosine ≥ `limits.belief_resonance_threshold`).
- `config/settings.py:1090` — `DREAM_ENABLED=False`; `:1137` — `DEEP_SLEEP_ENABLED=False` (per-chat резолв — ADR-1018-7).
- `config/settings.py:472,474` — `FULL_MEMORY_RETENTION_DAYS=30`, `ARCHIVE_MEMORY_RETENTION_DAYS=90`; `:558` — `INFINITE_RETENTION=False`.
- `services/summary_memory.py:2793-2858` — `compress_and_purge` (live-сырьё: сжатие → smart_archive → `delete_smart_messages_by_ids`); `:2860-2932` — `_compress_purge_extract_only` (**exclude_imported=True**); `services/database.py:1506-1520` — `delete_smart_messages_older_than`.
- `services/database.py:800-870` — v7-миграция: `import_key`, `history_processed`, индексы `idx_smart_messages_import_key` / `idx_smart_messages_history_pending`.
- `services/memory_maintenance.py:286-313` — `review` (дубли/истёкшие/unconfirmed по графу).
- `GRAPH_UNCONFIRMED_RETENTION_DAYS=14`, `GRAPH_COMPRESSION_LOG_RETENTION_DAYS=90`.

## 3. Требуемое поведение

1. **Retention импортированной истории** `smart_messages` (per-chat, UPD3 п.2): строки с `import_key IS NOT NULL` и `history_processed = 1` (граф уже пополнён) старше настраиваемого срока — архивируются и удаляются; идемпотентно, транзакционно, **с бэкапом до purge**. Sentinel: `0` = **вечно** (purge **жёстко запрещён**), `>0` = N дней, `<0` = невалидно → глобальный дефолт (WARNING).
2. **Retention логов**: `memory_dream_log`/`graph_fact_compressions`/архивные тексты — по существующим/новым срокам (настраиваемо).
3. **Глубокий сон / декай / воскрешения**: включены и настроены (per-chat/глобально по решению владельца) — не хардкодом; причина каждого пропуска логируется.
4. **Метрики здоровья** аддитивно (R16): `facts_overdue` (667), `facts_unconfirmed` (40), `beliefs_active/archived`, `smart_messages_total`, `db_size_bytes`, `disk_free_bytes`, `deep_sleep_runs_total`, `resurrect/decay` (есть).
5. Настройки retention/сна — с человекочитаемыми описаниями (F3-паттерн).
6. Замеры БД/диска до/после; отсутствие деградации производительности.
7. Без потери значимых данных: архив перед purge + бэкап (@DevOps) + dry-run.

## 4. Технический дизайн

### 4.1. Retention импортированной истории (ядро фичи) — per-chat + guard

- Новый ключ `limits.import_history_retention_days` (int, группа `limits_memory`, дефолт **180**, `0` = **вечно**, `<0` = невалидно → глобальный дефолт) — **Δ каталога +1** (§5; санкция UPD3 принята). Поле видно в настройках чата (F3, группа `limits_memory`) как **«Хранение импорта (дней)»**.
- **Policy-слой `services/retention_policy.py` (новый):**
```python
def retention_state(days) -> str:      # 'eternal' (0) | 'cap' (>0) | 'invalid' (<0)
async def resolve_import_retention_days(chat_id) -> tuple[int, str]:
    """(days, source) — chat → global → default; нормализация <0 → default+WARNING."""
async def imported_history_purge_allowed(chat_id) -> tuple[bool, int, str]:
    """(allowed, days, source); allowed = (days != 0)."""
```
- **DB-слой (структурный guard):**
```python
async def purge_imported_history(self, *, chat_cutoffs: dict[int, int],
                                 batch: int = 2000,
                                 dry_run: bool = False,
                                 chat_max_ids: dict[int, int] | None = None) -> dict:
    """Удаляет smart_messages WHERE chat_id IN chat_cutoffs
    AND import_key IS NOT NULL AND history_processed = 1
    AND timestamp < chat_cutoffs[chat_id] [AND id <= chat_max_ids[chat_id]],
    батчами + FTS-строки. keyword-only, БЕЗ дефолта: «удалить всем по
    глобальному сроку» невозможно. `chat_max_ids` — D-7 (граница архива).
    Возвращает {candidates, deleted, batches} (candidates — фактический
    подсчёт, не deleted). dry_run → только подсчёт."""
```
- **Guard (UPD3 п.3 + D-1 ревью Батча E):** `imported_history_purge_allowed` вызывается ДО построения маппинга; `days == 0` (данными сида) → чат **никогда не попадает** в `chat_cutoffs`. **Два независимых барьера:** (а) **fail-closed по недоступности chat-слоя** — `worker_settings.resolve_setting_with_source` отдаёт `source='error'` при нечитаемом `ChatParamsPool`/ошибке PG; `_resolve_days` при `source=='error'` → `(0,'error')` → `allowed=False`, а `run_import_retention` **отказывается от прогона ЦЕЛИКОМ** (`reason='chat_layer_unavailable'`), т.е. `chat_cutoffs` НЕ строится из fail-open `'default'`; (б) **hard-deny по данным сида** — `chat_settings_seed.enforced_eternal_chat_ids()` (ключ retention в `enforce` из `config/chat_settings_seed.json`) запрещает purge для чата даже при кривом резолве/недоступном сиде-рантайме (`source='seed_enforced'`). Seed `enforce`-политика (ADR-1019-8 §D4/D5) возвращает `0` на каждом старте. Тест фиксирует: единственный call-site (`memory_maintenance.run_import_retention`); целевой чат отсутствует в маппинге; реальный резолвер при недоступном chat-слое не удаляет целевой чат; прямой вызов с целевым чатом в `chat_cutoffs` — запрещён в тест-наборе (контракт метода).
- **Архивация перед purge:** `services/summary_memory.py` — экспорт выборки в `backups/imported_history_<ts>.jsonl.zst` (или `.jsonl`) с последующим удалением; при сбое архивации — **не удалять** (fail-safe). Для dry-run — только счётчики. **D-7 (ревью Батча E):** purge идёт строго по зафиксированному множеству (`id <= max_ids[chat]` из архива); при расхождении `candidates != archived` (строки стали `history_processed=1` между снапшотом и удалением) prune **прерывается** с WARNING без удаления (`reason='archive_mismatch'`). `candidates` — фактический подсчёт, НЕ подменяется `deleted`.
- Точка вызова — **существующий крон** `compress_and_purge` (4×/день) через новый шаг `memory_maintenance.run_import_retention()` (без нового APScheduler-джоба).
- **Dry-run сначала** (T-1836): счётчики кандидатов по чатам, затем фактическое удаление после бэкапа @DevOps.
- Идемпотентность: повторный прогон удаляет то же множество (условие по `timestamp < cutoff` + маркеры).

### 4.2. Включение Сна/декая/воскрешений (диагностика + настройка)

- `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` — резолвятся per-chat (`worker_settings`, ADR-1018-7). **Владелец сказал «включайте»**, но подтвердил баг рассинхрона. F7:
  1. **Диагностика:** лог причины пропуска каждого гейта (`reason=dream_disabled|deep_disabled|window_skip|decay_disabled|…`, R17-safe, `source=chat|global|default`).
  2. **Включение данными:** per-chat override для целевого чата (UI/`chat_params`), не хардкод.
  3. **`flags.belief_decay_enabled`** (глобальный master декай-шага) — включить (рекомендация) с консервативными порогами (`limits.belief_inactivity_days`, `limits.belief_decay_per_month`, `limits.belief_archive_threshold` не агрессивнее текущих).
- `_try_reanimate`: диагностировать, почему 0 (нет векторов/архива/порог) — лог причины; настройка порога `limits.belief_resonance_threshold` (существующий ключ).
- Включение **без фича-флага** (по решению владельца, прецедент 10.18): базовая логика активна; откат — данные/`git revert`.

### 4.3. Метрики здоровья (аддитивно)

- Новые DB-методы:
```python
async def count_overdue_facts(self, chat_id: int | None = None) -> int:
    """graph_facts WHERE expires_at IS NOT NULL AND expires_at < now
    AND status NOT IN ('expired','archived_belief')"""
async def count_unconfirmed_facts(self, chat_id: int | None = None) -> int:
    """graph_facts WHERE status = 'unconfirmed'"""
async def count_smart_messages(self, chat_id: int | None = None) -> int: ...
```
- `web/api/memory_agi.py::memory_health_summary` — аддитивные поля (R16):
```python
{
  ...существующие...,
  "facts_overdue": int, "facts_unconfirmed": int,
  "smart_messages_total": int,
  "deep_sleep_runs_total": int,
  "storage": {"db_size_bytes": int, "db_size_mb": float, "disk_free_bytes": int},
}
```
(`db_size_bytes`/`disk_free_bytes` — из SQLite-файла/`shutil.disk_usage`; R17-safe — только числа.)
- Фронт «Сводки»/«Мониторинг интеллекта» показывает эти метрики; при `storage.disk_free_bytes` ниже порога — предупреждающая подпись.

### 4.4. Человекочитаемое объяснение (для владельца; в UI/справке)

> «Память разделена на «сырьё» (переписка, по которой бот ищет) и «факты» (то, что он понял). Сырьё должно очищаться по сроку — иначе база растёт до миллионов строк. **Импорт старой переписки** жил вечно: 2 млн строк — это в основном она. Вводим срок хранения (по умолчанию 180 дней), но сначала сохраняем копию в файл и только потом удаляем из базы. **Глубокий сон/охлаждение/воскрешения показывали 0, потому что были выключены рубильники** — теперь они включены и причины каждого пропуска видны в логах. **667 просрочено / 40 не подтверждено** — это «старые» факты: просроченные уходят при пересмотре, неподтверждённые сбрасываются через 14 дней.»

### 4.6. Аудит изоляции памяти (UPD3 п.2) — «память строго привязана к `chat_id`»

**Инвариант:** любая строка памяти (импортированная история, факты, эмбеддинги, логи, чекпоинты) принадлежит ровно одному `chat_id`; выборка/RAG/кэш одного чата не могут вернуть/подавить данные другого. Проверено по коду HEAD `fd6acc7`:

| # | Место | Статус | Действие |
|---|---|---|---|
| I-1 | `tools/history_import/loader.py:174` — `msg["chat_id"] = target_chat` (перезапись chat_id из экспорта) | ✅ ок (импорт привязан к целевому чату) | тест-инвариант |
| I-2 | **`import_key` = `sha256(ts\|user_id\|text)[:32]` (`parser.py:122-131`) при ГЛОБАЛЬНОМ `UNIQUE idx_smart_messages_import_key` (`database.py:866-867`)** | ❌ **латентный дефект:** ключ не включает `chat_id`; при импорте одного и того же контента в два чата `INSERT OR IGNORE` **молча подавит** строку второго чата (кросс-чат-потеря) | **фикс:** SQLite-миграция **v11** — заменить глобальный UNIQUE на `UNIQUE(chat_id, import_key) WHERE import_key IS NOT NULL` (`idx_smart_messages_chat_import_key`); формулу `import_key` **не менять** (сохранить идемпотентность существующих 1.27M строк) |
| I-3 | `smart_messages_fts` (MATCH) — все продакшн-запросы добавляют `m.chat_id = ?` (`database.py:1591-1593,1608`) | ✅ ок | тест «FTS-выборка чата не возвращает чужие строки» |
| I-4 | `_dedup_knn` — фильтр `row["chat_id"] == chat_id` в Python (`summary_memory.py:2024-2036`) | ⚠️ утечки нет; возможна **потеря recall** (глобальный top-k вытесняет свои строки) | документировать; при росте чатов — chat-scoped vec-индекс (backlog, не блокер) |
| I-5 | `graph_facts_fts`/vec — `f.chat_id = ?` (`database.py:2602,2646,3196,3253`) | ✅ ок | тест |
| I-6 | `import_checkpoints (path PRIMARY KEY)` (`checkpoints.py:13-20`) — ключ только путь файла | ❌ **операционный дефект:** импорт того же файла во второй чат видит чекпоинт первого как «done» (искажение прогресса) | **фикс:** ключ `(path, chat_id)` (составной PK) — в той же SQLite-миграции **v11** (legacy-строки → `chat_id=0`) |
| I-7 | `chat_params`/`chat_usage`/`worker_budget` — ключ/scope по `chat_id` | ✅ ок | тест-инвариант |
| I-8 | Кэши: `ChatParamsCache` по `chat_id`; `_title_cache`/`_activity_cache` по `chat_id`; `EMBED_CACHE` по тексту (не контекст) | ✅ ок | тест |
| I-9 | Логи (R17): `dream_log`/`compression_log` — `chat_id` в строке | ✅ ок | тест |

**Вывод:** продакшн (один активный чат) не подвержен утечке сейчас; **при переходе к мультичатовости** дефекты I-2 и I-6 обязаны быть закрыты до второго активного чата (задача T-1864). Потенциальной **утечки** данных (чат A видит текст чата B) не найдено; найдены **потери/подавление** по глобальному ключу.

## 5. Изменения схемы / каталога / env

- **Схема БД (SQLite):** retention-DML — миграции **не требуются** (колонки `import_key`, `history_processed`, `expires_at`, `status` и индексы есть, v7). **Единственный DDL фичи (изоляция, I-2/I-6):** миграция **v10 → v11** — замена `idx_smart_messages_import_key` (глобальный UNIQUE) на `idx_smart_messages_chat_import_key UNIQUE(chat_id, import_key) WHERE import_key IS NOT NULL` (идемпотентно/reversible; `DROP INDEX IF EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS`; на существующих данных применимо — глобальный UNIQUE сильнее пер-чат). `import_checkpoints` — в ТОЙ ЖЕ миграции v11: rebuild с составным PK `(path, chat_id)`; legacy-строки получают `chat_id=0` (unscoped).
- **Каталог-Δ (сводится с F3/ADR-1019-8, санкция UPD3 принята):** +1 ключ `limits.import_history_retention_days` (группа `limits_memory`) → `REGISTRY 436→437 / Settings 406→407 / categorized 411→412`; `GROUPS 90→92` (2 новые группы F3), `TAB_RULES 19→20`, `mapped 88→90`. Итог: **437/92/407/412/90/20**.
- **env:** `IMPORT_HISTORY_RETENTION_DAYS` (новый, default 180) — сид каталога, `.env.example` плейсхолдер.
- **env-гейт деструктивного purge (D-2, ревью Батча E, env-only без каталога):** `IMPORT_RETENTION_ENABLED` (**default OFF**), `IMPORT_RETENTION_DRY_RUN` (**default ON**), `IMPORT_RETENTION_BACKUP_CONFIRMED` (**default OFF**, UPD4 п.3) — `ClassVar` (в каталог/Settings НЕ входят, Δ не растёт). Авто-крон `compress_and_purge` вызывает шаг только при ENABLED=true; **реальное удаление авто-кроном требует ЯВНО всех трёх:** `ENABLED=true` И `DRY_RUN=false` И `BACKUP_CONFIRMED=true`. Без подтверждённого бэкапа — только dry-run + WARNING (`memory_maintenance.auto_purge_dry_run`, единая точка правды). Ручной путь — `manage.py retention` (dry-run по умолчанию) / `retention --dry-run` / `retention --apply`.
- **Порядок роутеров `bot.py`** не меняется: `migrate_dream_thresholds` → `migrate_global_budget_defaults` → `migrate_context_limit_defaults` → `chat_settings_seed.apply_chat_settings_seed` (сид — после миграций; сид пишет per-chat, миграции — глобально, пересечений нет).
- Пороги сна/декая — существующие ключи (меняются значения, не состав).

## 6. Влияние на тесты

- Новый `tests/test_memory_retention_round1019.py`:
  - `purge_imported_history` — dry_run считает без удаления; реальный прогон удаляет только `import_key NOT NULL AND history_processed=1 AND timestamp < cutoff` **для чатов из `chat_cutoffs`**; live-строки не тронуты; FTS-строки удалены; повторный прогон — no-op; батчевость/лимит;
  - **guard:** `imported_history_purge_allowed(chat)` при `0` → `(False, 0, …)`; целевой чат **никогда** не попадает в `chat_cutoffs`; `purge_imported_history()` без маппинга → TypeError (структурный guard);
  - sentinel-семейство: `retention_state(0)=='eternal'`, `retention_state(180)=='cap'`, `retention_state(-1)=='invalid'`;
  - fail-safe: сбой архивации → строки не удалены; идемпотентность;
  - **изоляция (I-2/I-6):** один и тот же контент, импортированный в два чата, даёт **две** строки (после v11); повторный импорт в тот же чат — дубль (идемпотентно); чекпоинты не «завершают» файл для второго чата;
  - **D-1 (ревью Батча E):** на РЕАЛЬНОМ резолвере (без monkeypatch policy) при недоступном chat-слое (`ChatParamsPool` нет) строка целевого чата НЕ попадает в `chat_cutoffs`, `reason='chat_layer_unavailable'`, удаления нет; hard-deny целевого чата из `enforce`-данных сида даже при «разрешающем» fail-open резолве;
  - **D-7:** `chat_max_ids` ограничивает purge заархивированным множеством (id выше архива сохранён); расхождение `candidates != archived` → `reason='archive_mismatch'` без удаления; `candidates` не подменяется `deleted`;
  - **миграция v11** — повторный прогон идемпотентен (нет `import_checkpoints_old`, данные/версия сохранены).
- `tests/test_database.py` / `test_history_migration_v7.py`: миграция **v11** — индекс `idx_smart_messages_chat_import_key`, старый индекс удалён; `user_version == 11`; существующие строки сохранены.
- `tests/test_memory_agi*.py`: аддитивные поля health; R16 (существующие ключи сохранены); fail-open (ошибка БД → нули, не 500).
- `tests/test_dream_worker.py`: лог причины пропуска гейта; per-chat резолв `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` (смежно ADR-1018-7); `flags.belief_decay_enabled` → `decay_run`-маркер появляется.
- `tests/test_param_catalog.py`: Δ согласован (437/92/407/412/90/20).
- Полный `pytest` 0 failed; `git diff --check`; R17 (без текстов фактов/путей).

## 7. Rollout / feature-flag / откат

- **Гейты существуют** (`flags.belief_decay_enabled`, `DEEP_SLEEP_ENABLED` per-chat) — для сна/декая отдельных rollout-флагов не вводим.
- **Progressive delivery retention (D-2):** авто-крон по умолчанию **выключен** (`IMPORT_RETENTION_ENABLED=false`); при включении первый прогон — **гарантированно dry-run** (`IMPORT_RETENTION_DRY_RUN=true`). Далее: **dry-run (только подсчёт по чатам, `manage.py retention`) → бэкап БД (@DevOps) → DDL v11 (индекс/чекпоинты) → фактический purge батчами (`manage.py retention --apply`) → наблюдение размера/латентности**. Целевой чат (`0=вечно`/`enforce`) в purge не участвует; недоступный chat-слой → прогон отменяется.
- **Включение сна/декая:** сначала целевой тестовый чат → затем остальные (по данным).
- **Rollback:** выключить гейты/вернуть срок `0`; `git revert`; при ошибочном purge — восстановление из бэкапа/архива (процедура @DevOps); индекс v11 обратим (`DROP`/`CREATE`).

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Purge удалит нужные данные | Архив перед purge; dry-run; бэкап @DevOps; настраиваемый срок |
| R2 | Включение Сна/декая меняет поведение/расход | Настройка + бюджеты (F2/F3); постепенное включение; лог причины |
| R3 | Декай заархивирует «живые» убеждения | Консервативные пороги; тесты; лог `decayed/archived/reinforced` |
| R4 | Δ каталога без санкции | Human-gate (c); реализация retention возможна и при Δ=0 (использовать существующий `FULL_MEMORY_RETENTION_DAYS` для импорта — **не рекомендуется**, смешивает семантики) |
| R5 | Retention-джоб конкурирует с воркерами за БД | Батчи/`jitter`; вызов в существующем кроне; замер T-1843 |
| R6 | Метрики трактуются неверно | Пояснение в UI/доке (§4.4) |
| R7 | Смежный рассинхрон настроек (S10.18-12) | Читать через `worker_settings`; не регрессировать |

## 9. Открытые вопросы (human-gate — рекомендации)

1. **(e) Срок хранения импортированной истории — ПРИНЯТО:** **180 дней** (с архивом перед purge); `0` = **вечно**. **Целевой чат `-1002661910336` → `0`** (вечно) сидом; purge для него **жёстко запрещён** guard'ом (UPD3 п.3).
2. **(c) Δ каталога +1 — ПРИНЯТО (UPD3 п.5).** Иначе использовать `limits.full_memory_retention_days` для импорта **отклонено** (смешение живых и импортированных данных).
3. **(e) `flags.belief_decay_enabled`:** рекомендация — **включить** (глобально, консервативные пороги). Альтернатива — только per-chat.
4. **(e) Глубокий сон:** рекомендация — **включить per-chat** для целевого чата (не глобально), проверить каскад Сон→Глубокий→Личность.
5. **Бэкап перед purge** — обязательный шаг @DevOps; без него purge не запускать.
6. **(итерация 2) Изоляция (I-2/I-6):** SQLite **v11** + `import_checkpoints.chat_id` — закрыть до второго активного чата (T-1864); при одном чате — не блокер прод.

## 10. Deploy — двухэтапный гейт данных (UPD4 п.4) — SQL-чеклист @DevOps

> **Принцип (UPD4):** настройки целевого чата выдаются **только данными** (сид/миграция), а не логикой кода; код-путь полностью generic. Гейт разбит на два независимых шага, чтобы ошибка в одном не снесла историю.

**Этап 1 — @Reviewer (код, без боевой БД).**
- Проверить наличие и корректность скрипта-сида `config/chat_settings_seed.json` + `services/chat_settings_seed.py`: запись нацелена на целевой `chat_id`; `enforce` содержит `limits.import_history_retention_days`; `overrides` пишут `retention = 0`, бюджеты/фон/контекст `= -1`. Боевую БД **не проверять**.

**Этап 2 — @DevOps Post-Deploy Gate (боевая БД, ПОСЛЕ миграции и СТРОГО ДО рестарта/крона).**
Применить миграции/сид, затем выполнить SQL-запрос и **сверить значения**; при расхождении — **abort + откат деплоя** (рестарт бота/крона НЕ выполнять):

```sql
-- PostgreSQL: chat_profiles.chat_params (JSONB) целевого чата
SELECT
  (chat_params -> 'overrides' ->> 'limits.import_history_retention_days')::int     AS import_retention_days,
  (chat_params -> 'overrides' ->> 'limits.chat_global_key_budget_requests')::int   AS key_budget_requests,
  (chat_params -> 'overrides' ->> 'limits.chat_global_key_budget_tokens')::int     AS key_budget_tokens,
  (chat_params -> 'overrides' ->> 'limits.worker_daily_llm_calls_per_chat')::int   AS worker_calls,
  (chat_params -> 'overrides' ->> 'limits.worker_daily_llm_tokens_per_chat')::int  AS worker_tokens,
  (chat_params -> 'overrides' ->> 'limits.chat_global_context_max_tokens')::int    AS ctx_global,
  (chat_params -> 'overrides' ->> 'limits.chat_thread_max_tokens')::int            AS ctx_thread,
  (chat_params -> 'overrides' ->> 'limits.chat_context_budget_tokens')::int        AS ctx_budget
FROM chat_profiles
WHERE chat_id = -1002661910336;
```

**Ожидаемые значения (ровно эти; иначе — abort):**

| Поле (overrides) | Ожидаемо |
|---|---|
| `limits.import_history_retention_days` | **0** (вечно; purge запрещён) |
| `limits.chat_global_key_budget_requests` | **-1** (безлимит) |
| `limits.chat_global_key_budget_tokens` | **-1** |
| `limits.worker_daily_llm_calls_per_chat` | **-1** |
| `limits.worker_daily_llm_tokens_per_chat` | **-1** |
| `limits.chat_global_context_max_tokens` | **-1** (безлимит до потолка) |
| `limits.chat_thread_max_tokens` | **-1** |
| `limits.chat_context_budget_tokens` | **-1** |

- Дополнительно (SQLite, боевой файл БД): `PRAGMA user_version` → **11** (миграция изоляции применилась).
- **Порядок деплоя:** dry-run (`manage.py retention --dry-run`) → бэкап БД (@DevOps, подтверждается `IMPORT_RETENTION_BACKUP_CONFIRMED=true`) → DDL v11 → **Post-Deploy Gate (SQL выше) → только затем рестарт** → фактический purge (`retention --apply`) по решению владельца.
- **Провенанс:** `config/chat_settings_seed.json` — декларативные данные оператора; id допустим **только** здесь и в тестах, в `services/*` его нет (grep-тест).
