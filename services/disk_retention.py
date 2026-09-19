"""F9 round 10.24 (ADR-1024-2): единый источник истины retention диска.

Политика владельца (UPD3 №5, жёсткая):
  * Бэкапы БД (`local_database_*.db` + `memory_rebuild_*.db`) — хранить
    **ровно 1** новейший (суммарно по обоим префиксам). 3+ запрещено.
  * JSONL — окно **180 дней**, НО файлы с дампами/архивами **истории
    сообщений** (`imported_history_*.jsonl` и любые history-подобные)
    **неприкосновенны**: не удаляются никогда и не попадают в план очистки.
  * Прочие не-history JSONL (снимки досье `memory_generated_*.jsonl`,
    телеметрия, мусор) — удалять старше окна.
  * Логи — **7 дней** (journald `SystemMaxUse`/`MaxRetentionSec`, применяет
    @DevOps; здесь только числовой параметр/прогноз).

Роль модуля — закрыть корневую причину +6.4 ГБ (ADR-1024-2 Context п.1):
safety-бэкапы `memory_rebuild_*.db` (≈802 МБ) не покрывались ротацией,
которая смотрела только `local_database_*`. Теперь `prune_db_backups`
вызывается и из ежедневного бэкапа (`memory_backup._rotate`), и из
`memory_rebuild.create_safety_backup` — единый путь ротации.

Гарантии безопасности:
  * IMMUTABLE-файлы никогда не попадают в `plan_cleanup` (deny-list по имени
    + content-sniff по ключам JSON — сырая история опознаётся и не удаляется).
  * `apply_cleanup(verify=True)` — fail-closed: без валидного свежего
    `*.db`-бэкапа (size > 0, не в удаляемом наборе) удаление отменяется.
  * CLI по умолчанию dry-run; удаление — только с `--apply`.
  * R16/R17/R18: в логи/отчёт идут только имена файлов, размеры, категории и
    счётчики — без содержимого, путей-секретов и ключей.
"""
from __future__ import annotations

import datetime
import fnmatch
import json
import logging
import os
import time
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

# ── таксономия (ADR-1024-2 D2, spec §5) ─────────────────────────────────────

IMMUTABLE_PATTERNS = ("imported_history_*.jsonl",)
DB_BACKUP_PATTERNS = ("local_database_*.db", "memory_rebuild_*.db")
FACTS_PATTERNS = ("facts_*.txt",)
JSONL_ROTATE_PATTERNS = ("memory_generated_*.jsonl",)

# Жёсткий deny-list по имени: любые архивы/дампы истории сообщений.
# Владелец: файловые архивы сырых переписок — бессрочное хранение.
HISTORY_DENY_NAME_MARKERS = (
    "imported_history", "raw_history", "chat_history", "history_export",
    "messages_export", "chat_export",
)
# Content-sniff (T-2259): даже если имя не попал под deny-list, опознаём
# сырую историю по ключам JSON-строк. Ничего не логируем (R17).
_SNIFF_BYTES = 65536
_SNIFF_LINES = 25
_ROW_HISTORY_KEYS = frozenset(
    {"text", "user_id", "reply_to_id", "reply_to_message_id", "import_key",
     "author_name", "forward_source"})

# Свежесть бэкапа для verify (fail-closed): daily-бэкап идёт раз в сутки,
# safety — по требованию; слишком старый «бэкап» не считается страховкой.
FRESH_BACKUP_DAYS = 7


class RetentionDisabled(RuntimeError):
    """Retention выключен kill-switch'ем (`DISK_RETENTION_ENABLED=false`)."""


# ── вспомогательное ─────────────────────────────────────────────────────────

def default_dirs() -> list[str]:
    """Каталоги по умолчанию для CLI-аудита (MEMORY_BACKUP_DIR)."""
    return [str(settings.MEMORY_BACKUP_DIR)]


def _retention_enabled() -> bool:
    return bool(getattr(settings, "DISK_RETENTION_ENABLED", True))


def _db_keep() -> int:
    """Фиксированный guard: ровно 1 бэкап БД (политика владельца UPD3 №5).

    `DB_BACKUP_KEEP` читается для совместимости, но жёстко ограничен 1 —
    значения 3+ запрещены (БД слишком тяжёлая)."""
    try:
        raw = int(getattr(settings, "DB_BACKUP_KEEP", 1) or 1)
    except (TypeError, ValueError):
        raw = 1
    return 1 if raw >= 1 else 1


def _jsonl_retention_days() -> int:
    try:
        days = int(getattr(settings, "JSONL_NONHISTORY_RETENTION_DAYS", 180) or 180)
    except (TypeError, ValueError):
        days = 180
    return days if days >= 1 else 180


def _history_immutable() -> bool:
    """История неприкосновенна ВСЕГДА (hard, ADR-1024-2 D2/spec §6)."""
    if not bool(getattr(settings, "HISTORY_JSONL_IMMUTABLE", True)):
        logger.warning("[disk_retention] HISTORY_JSONL_IMMUTABLE=false "
                       "проигнорирован: история сообщений неприкосновенна")
    return True


def _matches_any(name: str, patterns) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _history_name(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in HISTORY_DENY_NAME_MARKERS)


def _looks_like_history(path: Path) -> bool:
    """Content-sniff JSONL (bounded, R17-safe): опознать сырую историю.

    Признаки: root-объект Telegram-экспорта с ключом `messages` ИЛИ строка с
    `text` и хотя бы одним «мессенджер»-ключом. Содержимое НЕ логируется."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            read = 0
            for _ in range(_SNIFF_LINES):
                line = fh.readline(_SNIFF_BYTES)
                if not line:
                    break
                read += len(line)
                if read > _SNIFF_BYTES:
                    break
                line = line.strip()
                if not line or line[0] not in "{[":
                    continue
                try:
                    obj = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(obj, dict):
                    if "messages" in obj:
                        return True
                    if "text" in obj and (_ROW_HISTORY_KEYS - {"text"}) & set(obj):
                        return True
    except OSError:
        return False
    return False


def _size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except OSError:
        return 0


# ── классификация ───────────────────────────────────────────────────────────

def classify(path) -> str:
    """Категория файла: immutable|db_backup|facts_export|jsonl_retention|other.

    IMMUTABLE имеет наивысший приоритет: история сообщений (по имени или
    содержимому) НИКОГДА не станет кандидатом на удаление."""
    p = Path(path)
    name = p.name
    if _matches_any(name, IMMUTABLE_PATTERNS) or _history_name(name):
        return "immutable"
    if name.endswith(".jsonl") and _looks_like_history(p):
        return "immutable"
    if _matches_any(name, DB_BACKUP_PATTERNS):
        return "db_backup"
    if _matches_any(name, FACTS_PATTERNS):
        return "facts_export"
    if name.endswith(".jsonl"):
        return "jsonl_retention"
    return "other"


# ── сбор файлов ─────────────────────────────────────────────────────────────

def _collect(base: Path, patterns) -> list[Path]:
    out: dict[str, Path] = {}
    for pat in patterns:
        for path in base.glob(pat):
            if path.is_file():
                out[str(path)] = path
    return list(out.values())


def _iter_files(dirs) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for entry in dirs or ():
        base = Path(entry)
        if not base.exists() or not base.is_dir():
            continue
        key = str(base.resolve())
        if key in seen:
            continue
        seen.add(key)
        for path in base.rglob("*"):
            if path.is_file():
                files.append(path)
    return files


def _all_db_backups(dirs) -> list[Path]:
    out: dict[str, Path] = {}
    for entry in dirs or ():
        base = Path(entry)
        if base.is_dir():
            for path in _collect(base, DB_BACKUP_PATTERNS):
                out[str(path)] = path
    return list(out.values())


def _all_facts_exports(dirs) -> list[Path]:
    out: dict[str, Path] = {}
    for entry in dirs or ():
        base = Path(entry)
        if base.is_dir():
            for path in _collect(base, FACTS_PATTERNS):
                out[str(path)] = path
    return list(out.values())


def _newest_last(files) -> list[Path]:
    return sorted(files, key=lambda p: (_mtime_ns(p), p.name))


# ── ротация бэкапов БД (единый источник; T-2258) ────────────────────────────

def prune_db_backups(directory, *, keep: int = 1) -> list[str]:
    """Удалить все `*.db`-бэкапы кроме `keep` новейших (ОБА префикса).

    Возвращает список удалённых путей. Best-effort: ошибка unlink → WARNING,
    прогон не падает. `keep` жёстко ≥ 1 (нельзя снести все бэкапы)."""
    if not _retention_enabled():
        logger.info("[disk_retention] prune_db_backups skipped (disabled)")
        return []
    base = Path(directory)
    if not base.is_dir():
        return []
    keep = max(1, int(keep or 1))
    removed: list[str] = []
    for old in _newest_last(_collect(base, DB_BACKUP_PATTERNS))[:-keep]:
        try:
            old.unlink()
            removed.append(str(old))
            logger.info("[disk_retention] db backup rotated out | name=%s",
                        old.name)
        except OSError:
            logger.warning("[disk_retention] db backup unlink failed | "
                           "name=%s", old.name)
    return removed


def prune_facts_exports(directory, *, keep: int = 1) -> list[str]:
    """Держать `keep` новейших `facts_*.txt` (пара к бэкапу БД, ADR D2)."""
    if not _retention_enabled():
        return []
    base = Path(directory)
    if not base.is_dir():
        return []
    keep = max(1, int(keep or 1))
    removed: list[str] = []
    for old in _newest_last(_collect(base, FACTS_PATTERNS))[:-keep]:
        try:
            old.unlink()
            removed.append(str(old))
            logger.info("[disk_retention] facts export rotated out | name=%s",
                        old.name)
        except OSError:
            logger.warning("[disk_retention] facts export unlink failed | "
                           "name=%s", old.name)
    return removed


# ── аудит (read-only) ───────────────────────────────────────────────────────

def audit(dirs) -> dict:
    """Read-only снимок: категории {count, bytes}, immutable/total, top-10."""
    files = _iter_files(dirs)
    categories: dict[str, dict] = {}
    sized: list[tuple[int, Path, str]] = []
    immutable_bytes = 0
    total_bytes = 0
    for path in files:
        size = _size(path)
        category = classify(path)
        bucket = categories.setdefault(category, {"count": 0, "bytes": 0})
        bucket["count"] += 1
        bucket["bytes"] += size
        total_bytes += size
        if category == "immutable":
            immutable_bytes += size
        sized.append((size, path, category))
    sized.sort(key=lambda item: (-item[0], item[1].name))
    top_files = [
        {"name": path.name, "bytes": size, "category": category}
        for size, path, category in sized[:10]
    ]
    return {
        "dirs": [str(d) for d in (dirs or ())],
        "categories": categories,
        "immutable_bytes": immutable_bytes,
        "total_bytes": total_bytes,
        "top_files": top_files,
    }


# ── план очистки (чистая функция; T-2259) ───────────────────────────────────

def _plan_item(path: Path, category: str, reason: str) -> dict:
    return {"path": str(path), "category": category, "reason": reason,
            "bytes": _size(path)}


def plan_cleanup(dirs) -> list[dict]:
    """Кандидаты на удаление без побочных эффектов. IMMUTABLE исключены.

    Кандидаты: DB-бэкапы за пределами `keep=1`; `facts_*.txt` за пределами
    1; не-history JSONL старше окна (180 дней)."""
    if not _retention_enabled():
        return []
    plan: list[dict] = []
    db_keep = _db_keep()
    for old in _newest_last(_all_db_backups(dirs))[:-db_keep]:
        plan.append(_plan_item(old, "db_backup", "db_keep_newest_1"))
    for old in _newest_last(_all_facts_exports(dirs))[:-1]:
        plan.append(_plan_item(old, "facts_export", "facts_keep_newest_1"))
    days = _jsonl_retention_days()
    now = time.time()
    for path in _iter_files(dirs):
        if not path.name.endswith(".jsonl"):
            continue
        if classify(path) != "jsonl_retention":
            continue
        age_days = (now - (_mtime_ns(path) / 1_000_000_000)) / 86400.0
        if age_days > days:
            plan.append(_plan_item(path, "jsonl_retention",
                                   f"jsonl_older_than_{days}d"))
    return plan


# ── применение очистки (fail-closed; T-2258/D3) ─────────────────────────────

def _valid_fresh_backups(dirs, *, exclude: set[str]) -> list[Path]:
    now = time.time()
    valid: list[Path] = []
    for path in _all_db_backups(dirs):
        if str(path) in exclude:
            continue
        if _size(path) <= 0:
            continue
        age_days = (now - (_mtime_ns(path) / 1_000_000_000)) / 86400.0
        if age_days <= FRESH_BACKUP_DAYS:
            valid.append(path)
    return valid


def apply_cleanup(plan, *, verify: bool = True, dirs=None) -> dict:
    """Выполнить план: verify (fail-closed) → unlink → отчёт.

    `verify=True`: до удаления обязан существовать валидный свежий
    `*.db`-бэкап, НЕ входящий в план; иначе — abort без единого удаления.
    `dirs` — каталоги для проверки бэкапа (дефолт: родители элементов плана).
    Идемпотентно: отсутствующий файл считается уже удалённым (не ошибка)."""
    out = {"deleted": 0, "bytes_freed": 0, "aborted_reason": "",
           "skipped": 0, "errors": 0, "categories": {}}
    items = list(plan or [])
    if not items:
        return out
    if verify:
        delete_paths = {str(item.get("path")) for item in items
                        if item.get("category") == "db_backup"}
        scan_dirs = list(dirs) if dirs else sorted(
            {str(Path(item["path"]).parent) for item in items})
        if not _valid_fresh_backups(scan_dirs, exclude=delete_paths):
            logger.warning("[disk_retention] cleanup aborted — no valid fresh "
                           "db backup (fail-closed)")
            out["aborted_reason"] = "no_valid_backup"
            return out
    for item in items:
        path = Path(str(item.get("path")))
        category = str(item.get("category") or "other")
        try:
            size = _size(path)
            path.unlink()
            out["deleted"] += 1
            out["bytes_freed"] += size
            bucket = out["categories"].setdefault(category, {"count": 0, "bytes": 0})
            bucket["count"] += 1
            bucket["bytes"] += size
        except FileNotFoundError:
            out["skipped"] += 1
        except OSError:
            out["errors"] += 1
            logger.warning("[disk_retention] cleanup unlink failed | name=%s",
                           path.name)
    logger.info("[disk_retention] cleanup done | deleted=%d freed=%d skipped=%d",
                out["deleted"], out["bytes_freed"], out["skipped"])
    return out


# ── прогноз (T-2263) ────────────────────────────────────────────────────────

def forecast_monthly(dirs, *, window_days: int = 30, now: float | None = None) -> dict:
    """Прогноз расхода: суммарный размер свежих файлов / фактическое окно.

    `bytes_per_day` — средний прирост за наблюдаемое окно; `projected_30d` —
    линейная экстраполяция на 30 дней. Детерминирован на фикстурах."""
    now_ts = float(now if now is not None else time.time())
    window_days = max(1, int(window_days or 30))
    cutoff = now_ts - window_days * 86400.0
    recent = 0
    oldest = None
    for path in _iter_files(dirs):
        mtime = _mtime_ns(path) / 1_000_000_000
        if mtime < cutoff:
            continue
        recent += _size(path)
        oldest = mtime if oldest is None else min(oldest, mtime)
    if not recent or oldest is None:
        return {"bytes_per_day": 0, "projected_30d": 0,
                "recent_bytes": 0, "span_days": 0.0, "window_days": window_days}
    span_days = min(float(window_days),
                    max(1.0, (now_ts - oldest) / 86400.0))
    per_day = recent / span_days
    return {
        "bytes_per_day": int(per_day),
        "projected_30d": int(per_day * 30),
        "recent_bytes": recent,
        "span_days": round(span_days, 3),
        "window_days": window_days,
    }


def human_bytes(size: int) -> str:
    """Человекочитаемый размер (для CLI-вывода; без секретов)."""
    value = float(size or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"


def day_stamp(ts: float | None = None) -> str:
    return datetime.datetime.fromtimestamp(
        ts if ts is not None else time.time()).strftime("%Y-%m-%d %H:%M:%S")
