# spec.md — F9 `disk-space-audit-retention-round1024` (аудит, очистка, retention, отчёт)

> Раунд 10.24, Часть 1 (backend-core) · Приоритет **P0** · ADR: **ADR-1024-2**
> ТЗ: `plans/current_task.md` UPD2 п.7 (стр. 201–207), UPD3 п.5 (стр. 254–255). SSH-креды/ключи не цитировать (R17/R18).
> Baseline: HEAD `00eab85`; прод `4314ea4`; диск 10 → 16.4 ГБ (+6.4 ГБ).

## 1. Цель

Найти причину роста диска, удалить избыточное (бэкапы/кэши/логи), настроить строгие retention-политики и дать справку владельцу: **причина роста + что удалено + прогноз на месяц**. Политика владельца: **1 бэкап БД**, JSONL 6 мес, **архивы истории сообщений неприкосновенны**, прочие JSONL резать, логи 7 дней.

## 2. Что уже есть (координаты)

- Daily-бэкап + facts export + ротация: `services/memory_backup.py:32-40` (`_backup_keep_default`), `:94-114` (`backup_and_export`), `:116-149`, `:151-178`, `:180-200` (`_rotate` — **только** `local_database_*`/`facts_*`).
- Safety-бэкап (≈802 МБ): `services/memory_rebuild.py:68` (`_DEFAULT_BACKUP_PREFIX="memory_rebuild_"`), `:149-175` (`create_safety_backup`), `:178-191` (`_safety_backup`).
- JSONL-архив досье (не-history): `services/memory_rebuild.py:194-248` (`memory_generated_*.jsonl`).
- Архивы сырой истории: `services/memory_maintenance.py:367-435` (`imported_history_*.jsonl`, «файл содержит текст переписки») — **IMMUTABLE**.
- Логи: journald (stdout); ротации приложения нет.
- Retention-ключ: `limits.memory_backup_keep` (каталог, код-дефолт 1).
- Лог-хуки: F2 `services/external_log.py` (ADR-1024-1).

## 3. Требуемое поведение

1. Единый модуль `services/disk_retention.py` — таксономия и единый `prune_db_backups` для **обоих** префиксов бэкапов.
2. DB-бэкапов хранится **ровно 1** (новейший); `DB_BACKUP_KEEP` — фиксированный guard = 1.
3. `imported_history_*.jsonl` — **никогда не удалять** (S10.19-24 → Won't Fix).
4. `memory_generated_*.jsonl` и прочие не-history `*.jsonl` — удалять старше 180 дней.
5. Логи — 7 дней (journald `SystemMaxUse`/`MaxRetentionSec`, применяет @DevOps).
6. CLI `manage.py disk audit` (read-only) и `manage.py disk cleanup --apply` (по умолчанию dry-run).
7. Отчёт: причина роста +6 ГБ (атрибуция), что удалено/освобождено, прогноз на месяц.

## 4. Изменения по файлам

| Файл | Изменение |
|---|---|
| `services/disk_retention.py` | **новый**: `classify`, `audit`, `plan_cleanup`, `apply_cleanup`, `prune_db_backups(directory, keep=1)`, `forecast_monthly`; env-флаги |
| `services/memory_backup.py` | `_rotate` делегирует `prune_db_backups` (единый источник); keep-guard = 1 |
| `services/memory_rebuild.py` | `create_safety_backup` → после создания `prune_db_backups`; `memory_generated_*.jsonl` учитываются ротацией |
| `services/memory_maintenance.py` | явная пометка `imported_history_*.jsonl` как IMMUTABLE (не кандидат на удаление) |
| `manage.py` | команда `disk audit|cleanup [--apply] [--dir <path>]` |
| `config/settings.py` | env-only `ClassVar`: см. §6 |
| `plans/metrics.md` | отчёт «причина/удалено/прогноз» по завершении F9 (T-2263) |

## 5. Контракты

```python
# services/disk_retention.py
IMMUTABLE_PATTERNS = ("imported_history_*.jsonl",)
DB_BACKUP_PATTERNS = ("local_database_*.db", "memory_rebuild_*.db")
FACTS_PATTERNS = ("facts_*.txt",)
JSONL_ROTATE_PATTERNS = ("memory_generated_*.jsonl",)   # + прочие не-history

def classify(path) -> str            # immutable|db_backup|facts_export|jsonl_retention|other
def prune_db_backups(directory, *, keep: int = 1) -> list[str]   # возвращает удалённые
def audit(dirs) -> dict              # {category: {count, bytes}, immutable_bytes, total_bytes, top_files}
def plan_cleanup(dirs) -> list[dict] # [{path, category, reason, bytes}] — чистая функция
def apply_cleanup(plan, *, verify=True) -> dict  # {deleted, bytes_freed, aborted_reason}
def forecast_monthly(dirs) -> dict   # {bytes_per_day, projected_30d}
```

**Правила:**
- `apply_cleanup` не удаляет без verify (существует валидный свежий `*.db`-бэкап ненулевого размера).
- IMMUTABLE-файлы никогда не попадают в `plan_cleanup`.
- CLI default `dry_run=True`; удаление — только `--apply`.
- Вывод/логи — только пути/размеры/категории (без секретов).

## 6. Флаги

| Флаг | Default | Смысл |
|---|---|---|
| `DISK_RETENTION_ENABLED` | True | kill-switch retention |
| `DB_BACKUP_KEEP` | 1 (fixed guard) | строго 1 бэкап БД |
| `JSONL_NONHISTORY_RETENTION_DAYS` | 180 | окно не-history JSONL |
| `LOG_RETENTION_DAYS` | 7 | окно логов |
| `HISTORY_JSONL_IMMUTABLE` | True (hard) | история неприкосновенна |

## 7. Тесты

- (a) `prune_db_backups` покрывает **оба** префикса и оставляет ровно 1 новейший.
- (b) `imported_history_*.jsonl` НЕ удаляется никогда (immutability-тест).
- (c) `memory_generated_*.jsonl` старше 180 дней удаляется, свежие — нет.
- (d) `apply_cleanup(verify=True)` без валидного бэкапа → abort (fail-closed).
- (e) CLI dry-run не удаляет; `--apply` удаляет и возвращает отчёт.
- (f) `forecast_monthly` считает по mtime/размерам (детерминированный тест на фикстурах).
- (g) Логи/отчёт не содержат секретов (egress-сканер).

## 8. Риски

- **R1 (Critical):** удаление единственного валидного бэкапа → verify перед удалением (D3).
- **R2 (High):** retention затронет нужный JSONL-архив → `imported_history_*` в IMMUTABLE; прочее — окно 180 дней.
- **R3 (Medium):** journald-лимиты обрежут важные логи → 7 дней + лимит длины тела (F2).
- **R4 (Medium):** очистка кэшей (embeddings/anticliche) вызовет пересчёт → допустимо, зафиксировать в отчёте.
- **R5 (R17/R18):** SSH-креды/ключи не цитировать/не логировать.

## 9. Критерии приёмки

- Освобождено место; свежий валидный бэкап БД существует; пересборка досье не ломается.
- Retention автоматически ограничивает бэкапы, JSONL (кроме истории) и логи.
- Отчёт владельцу: причина роста, перечень удалённого, прогноз на месяц.
- Ни один секрет не попал в отчёт/логи.

## 10. Откат / Δ

- Retention — конфиг обратно / флаг OFF; удалённое восстановимо только из внешних бэкапов (поэтому verify).
- Δ DDL = 0; Δ каталога = 0. `S10.19-24` закрывается как **Won't Fix** (политика владельца).

## 11. Артефакты-ссылки

- ADR: `ADR-1024-2.md`; карта: `round1024-architecture.md` §3.2, §4, §5.
- Обязательство: `plans/metrics.md` (отчёт по F9).
