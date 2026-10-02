"""T-4506 (post-asap4-corrective-pass): сервер-sайд retention/cleanup политика диска.

Автономный CLI (только stdlib, без импорта приложения): очистка ТОЛЬКО по
явному whitelist-классам из disk-audit §9 (`plans/features/
post-asap4-corrective-pass/disk-audit.md`), файл-за-файлом, с логом.

Отличие от `services/disk_retention.py` (F9/ADR-1024-2): тот — runtime-механизм
ротации внутри каталога бэкапов приложения (`MEMORY_BACKUP_DIR`); этот скрипт —
сервер-сайд политикка для путей ВНЕ приложения (`/home/nik/backups*`, /tmp,
headroom-логи, playwright-артефакты). Каталог `backups/` приложения и daily-роутация
в нём этим скриптом НЕ трогаются (у рантайма свой keep=1).

Гарантии безопасности:
  * Кандидаты собираются ТОЛЬКО внутри хардкод-корней whitelist-правил; CLI не
    позволяет добавить ни один путь. Ничего вне корней скрипт не открывает.
  * HARDCODE denylist сильнее whitelist: рабочая БД+WAL/shm, именованные
    копии/якоря БД (суточный `local_database_2*.db`, `pre_migration_*.db`,
    `*pre_v*`), `.env*`, архивы истории (`*history*`), cookies, media/uploads,
    память/GraphRAG-данные, venv/.git, браузерный профиль — не удаляются НИКОГДА,
    даже если лежат в whitelist-каталоге.
  * `migrate_history/` — conditional: по умолчанию исключён, удаляется только с
    явным `--with-owner-confirm` (и всё равно старше 7 дней, свежие экспорты нет).
  * Dry-run по умолчанию: печатает план с размерами. Реальное удаление — только
    `--apply`, по-файлу; примитив удаления НЕ доверяет входному плану и повторно
    проверяет каждый путь (whitelist-контейнмент + denylist + паттерн правила).
  * Никаких `rm -rf` по широким путям и никакого `shutil.rmtree`: только
    `unlink` отдельных файлов из вычисленного списка; каталоги не удаляются.
  * Kill-switch: `ADMINBOT_DISK_RETENTION_ENABLED=0` — полный no-op (default ON).
  * Idempotent: повторный прогон после apply — пустой план.
  * R17: в логи/отчёт идут только имена файлов, размеры, счётчики и классы.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ── Kill-switch (env-only, default ON; OFF = полный no-op) ──────────────────

ENABLED_ENV = "ADMINBOT_DISK_RETENTION_ENABLED"

# ── HARDCODE denylist — сильнее любого whitelist-правила ────────────────────

# Точные имена: рабочая БД и её WAL/shm (где бы они ни встретились).
DENIED_EXACT_NAMES = frozenset({
    "local_database.db",
    "local_database.db-wal",
    "local_database.db-shm",
})

# Глобы по имени: именованные копии/якоря БД и секреты.
#   local_database_2*.db — суточный авто-бэкап и любые именованные копии
#   (в т.ч. свежайший — защита «свежайший daily» делается с запасом: ВСЕ
#   именованные копии вне whitelist-корней этого скрипта и не удаляются).
#   pre_migration_*.db — ВСЕ pre-migration якоря (включая якорь этого pass'а
#   pre_migration_20261002_101544.db и любые будущие) — решение по ним принимает
#   владелец (T-4509), не автоматика.
DENIED_NAME_GLOBS = (
    "local_database_2*.db",
    "pre_migration_*.db",
    ".env*",
)

# Подстроки в имени (lowercase): версионные rollback-якоря, сырая история,
# cookies/секреты.
DENIED_NAME_MARKERS = (
    "pre_v",    # pre_v21 и будущие pre_vNN — anchors, неприкосновенны
    "history",  # импортированная/сырая история сообщений — бессрочно (UPD3 №5)
    "cookie",   # cookies.txt и подобные (секреты)
)

# Сегменты пути: медиа/загрузки, память/GraphRAG, рантайм, браузерный профиль.
DENIED_DIR_SEGMENTS = frozenset({
    "media", "uploads",
    "graphrag", "chroma", "lancedb", "embeddings", "memory",
    "venv", ".git",
    "chrome-profile", "bot-chrome-profile",
})

# Conditional-сегмент: исключён по умолчанию, только с --with-owner-confirm
# (и всё равно только файлы старше окна правила — см. правило migrate_history).
OWNER_CONFIRM_SEGMENTS = frozenset({"migrate_history"})

# ── Правила whitelist (декларативные, хардкод; CLI пути не расширяет) ───────


@dataclass(frozen=True)
class RetentionRule:
    """Класс очистки: явные корни + узкие паттерны имён файлов + политика.

    Политика (комбинация, все фильтры одновременно):
      * min_age_days — возраст строго БОЛЬШЕ порога (равный порогу остаётся);
      * keep_newest — сохранить N новейших по mtime; ранжирующий пул включает
        ВСЕ файлы правил (в т.ч. denylist — они занимают слоты, но сами
        защищены), плюс read-only `rank_roots` (там ничего не удаляется —
        только учёт свежести, чтобы «1–2 последних» считались по всем
        известным местам якорей, как в disk-audit §7.1);
      * keep_current_month — файлы текущего календарного месяца не удаляются;
      * max_total_bytes — мягкий кап суммы удерживаемых классом байтов
        (после всех прочих фильтров старшие перевеса уходят в кандидаты).
    """

    key: str
    roots: tuple[str, ...]              # явные корни удаления (без масок)
    patterns: tuple[str, ...]           # узкие fnmatch-паттерны имени файла
    recursive: bool = True
    min_age_days: float | None = None
    keep_newest: int | None = None
    keep_current_month: bool = False
    rank_roots: tuple[str, ...] = ()    # read-only: только ранжирование keep_newest
    rank_patterns: tuple[str, ...] = ()
    max_total_bytes: int | None = None
    requires_owner_confirm: bool = False
    description: str = ""


def default_rules() -> tuple[RetentionRule, ...]:
    """Whitelist-классы из disk-audit §9 (T-4505) + предписания T-4506.

    Ретеншн якорей — «1–2 последних + якоря текущего месяца» (audit §7.1):
    keep_newest=2 по пулу ВСЕХ известных мест якорей (home-каталоги + корень
    приложения read-only) + keep_current_month. pre_v21 и
    pre_migration_20261002_101544.db защищены отдельно и навсегда (denylist),
    поэтому правило физически способно тронуть только безымянные старые
    копии вроде pre_mca_v19 — ровно как в disposition аудита.
    """
    return (
        RetentionRule(
            key="db_anchor_backups",
            roots=("/home/nik/backups", "/home/nik/backups_adminbot"),
            rank_roots=("/var/www/admin_bot",),
            rank_patterns=("*.db",),
            patterns=("*.db",),
            recursive=False,
            keep_newest=2,
            keep_current_month=True,
            description="Старые ad-hoc якоря БД в home-каталогах "
                        "(1-2 последних + текущий месяц; pre_v*/pre_migration*/daily "
                        "защищены denylist'ом всегда)"),
        RetentionRule(
            key="app_adhoc_db_baks",
            roots=("/var/www/admin_bot",),
            patterns=("local_database.db.bak.*",),
            recursive=False,
            min_age_days=14.0,
            description="Ad-hoc копии БД в корне приложения старше 14 дней "
                        "(рабочая БД/WAL не совпадают с паттерном)"),
        RetentionRule(
            key="playwright_artifacts",
            roots=("/var/www/admin_bot/.playwright-mcp",),
            patterns=("*",),
            recursive=True,
            min_age_days=7.0,
            description="Playwright/.playwright-mcp артефакты старше 7 дней"),
        RetentionRule(
            key="pytest_tmp",
            roots=("/tmp/pytest-of-nik",),
            patterns=("*",),
            recursive=True,
            min_age_days=3.0,
            description="pytest-артефакты в /tmp старше 3 дней"),
        RetentionRule(
            key="pytest_tmp_files",
            roots=("/tmp",),
            patterns=("adminbot_test_*",),
            recursive=False,
            min_age_days=3.0,
            description="Темп-файлы тестов adminbot_test_* в /tmp старше 3 дней"),
        RetentionRule(
            key="rotated_logs",
            roots=("/opt/headroom/home/.headroom/logs",),
            patterns=("*.log.[0-9]*", "*.log.[0-9]*.gz"),
            recursive=False,
            min_age_days=14.0,
            description="Ротированные логи (proxy.log.N) старше 14 дней; "
                        "активный proxy.log паттерну не соответствует"),
        RetentionRule(
            key="migrate_history",
            roots=("/var/www/admin_bot/migrate_history",),
            patterns=("*",),
            recursive=True,
            min_age_days=7.0,
            requires_owner_confirm=True,
            description="Сырые экспорты истории миграции (данные уже в БД): "
                        "ТОЛЬКО после off-site архива и явного owner-confirm"),
    )


# ── Вспомогательные ─────────────────────────────────────────────────────────


def human_bytes(size: float) -> str:
    value = float(size or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024.0


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def _size(path: str) -> int:
    try:
        return int(os.stat(path).st_size)
    except OSError:
        return 0


def _iter_files(root: str, patterns: tuple[str, ...], recursive: bool):
    """Файлы корня, соответствующие узким паттернам имени. Только чтение.

    os.walk без followlinks: симлинк-каталоги не раскрываются; файловые
    симлинки не кандидаты (L-4504-5, паритет с non-recursive веткой
    follow_symlinks=False) — в плане нет PLAN-строк, которые apply потом
    блокирует. Сами файлы проверяются на denylist/контейнмент отдельно
    (plan и apply)."""
    base = Path(root)
    if not base.is_dir():
        return
    if not recursive:
        try:
            entries = list(os.scandir(root))
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file(follow_symlinks=False) and _matches(
                        entry.name, patterns):
                    yield os.path.join(root, entry.name)
            except OSError:
                continue
        return
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            if _matches(name, patterns):
                path = os.path.join(dirpath, name)
                if os.path.islink(path):
                    continue
                yield path


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, pat.lower()) for pat in patterns)


# ── Denylist (wins over whitelist) ──────────────────────────────────────────


def deny_reason(path: str, *, owner_confirm: bool = False) -> str:
    """Причина запрета удаления файла ('' — файл не запрещён). Over-block ок:
    ложное запрещение безопасно, ложное разрешение — нет."""
    name = os.path.basename(path)
    low = name.lower()
    if name in DENIED_EXACT_NAMES or low in {n.lower() for n in DENIED_EXACT_NAMES}:
        return "protected_db_or_wal"
    for pat in DENIED_NAME_GLOBS:
        if fnmatch.fnmatch(low, pat.lower()):
            return f"denied_glob:{pat}"
    for marker in DENIED_NAME_MARKERS:
        if marker in low:
            return f"denied_marker:{marker}"
    parts = os.path.normpath(path).replace("\\", "/").split("/")
    for seg in parts:
        seg_low = seg.lower()
        if seg_low in {s.lower() for s in DENIED_DIR_SEGMENTS}:
            return f"denied_segment:{seg_low}"
        if seg in OWNER_CONFIRM_SEGMENTS and not owner_confirm:
            return "owner_confirm_required:migrate_history"
    return ""


def _within(path: str, root: str) -> bool:
    """true, если realpath(path) лежит строго внутри realpath(root)."""
    try:
        rp = os.path.realpath(path)
        rr = os.path.realpath(root)
        return bool(rp) and bool(rr) and os.path.commonpath([rp, rr]) == rr
    except (ValueError, OSError):
        return False


def _contained_roots(path: str, roots) -> list[str]:
    return [r for r in roots if _within(path, r)]


# ── Сборка плана (чистая, без побочных эффектов) ────────────────────────────


def _month_start(now: float) -> float:
    dt = datetime.fromtimestamp(now)
    return datetime(dt.year, dt.month, 1).timestamp()


def _rank_newest(rule: RetentionRule) -> tuple[set[str], list[dict]]:
    """Пути keep_newest новейших файлов + защищённые файлы, замеченные в
    read-only rank_roots (для отчёта). Пул = файлы правил (вкл. denylist) +
    rank_roots. Файлы rank_roots НИКОГДА не удаляются — ранжирование только
    учитывает их свежесть; denylist-файлы там фиксируются как protected."""
    keep = rule.keep_newest
    if not keep or keep < 1:
        return set(), []
    pool: list[tuple[float, str]] = []
    protected: list[dict] = []
    for root in rule.roots:
        for p in _iter_files(root, rule.patterns, rule.recursive):
            pool.append((_mtime(p), p))
    for root, pats in zip(rule.rank_roots,
                          rule.rank_patterns or ("*",) * len(rule.rank_roots)):
        for p in _iter_files(root, (pats,), False):
            pool.append((_mtime(p), p))
            reason = deny_reason(p)
            if reason:
                protected.append({"rule": rule.key, "path": p,
                                  "reason": reason})
    pool.sort(key=lambda item: (-item[0], item[1]))
    return {p for _mt, p in pool[:keep]}, protected


def retention_enabled(environ=None) -> bool:
    env = environ if environ is not None else os.environ
    return env.get(ENABLED_ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def build_plan(rules=None, *, now: float | None = None,
               owner_confirm: bool = False,
               enabled: bool | None = None) -> dict:
    """Кандидаты на удаление без побочных эффектов + защищённые с причинами.

    Idempotent: файл либо попадает в план по явному правилу, либо нет;
    повторный вызов на неизменном FS даёт тот же план."""
    rules = default_rules() if rules is None else rules
    now = time.time() if now is None else now
    if enabled is None:
        enabled = retention_enabled()
    out: dict = {"enabled": enabled, "plan": [], "protected": [],
                 "scanned": 0, "rules": {}}
    if not enabled:
        return out
    month_start = _month_start(now)
    for rule in rules:
        rule_report = {"scanned": 0, "candidates": 0, "protected": 0}
        out["rules"][rule.key] = rule_report
        if rule.requires_owner_confirm and not owner_confirm:
            out["protected"].append({
                "rule": rule.key, "path": rule.roots[0] if rule.roots else "",
                "reason": "owner_confirm_required:rule"})
            continue
        newest, rank_protected = _rank_newest(rule)
        out["protected"].extend(rank_protected)
        candidates: list[dict] = []
        for root in rule.roots:
            for path in _iter_files(root, rule.patterns, rule.recursive):
                rule_report["scanned"] += 1
                out["scanned"] += 1
                reason = deny_reason(path, owner_confirm=owner_confirm)
                if reason:
                    rule_report["protected"] += 1
                    out["protected"].append(
                        {"rule": rule.key, "path": path, "reason": reason})
                    continue
                if path in newest:
                    continue
                mtime = _mtime(path)
                if rule.keep_current_month and mtime >= month_start:
                    continue
                if rule.min_age_days is not None:
                    age_days = (now - mtime) / 86400.0
                    if age_days <= rule.min_age_days:
                        continue
                    age_out = round(age_days, 2)
                else:
                    age_out = None
                candidates.append({
                    "rule": rule.key, "path": path, "bytes": _size(path),
                    "age_days": age_out})
        if rule.max_total_bytes is not None and candidates:
            cap = int(rule.max_total_bytes)
            candidates.sort(key=lambda c: (-_mtime(c["path"]), c["path"]))
            acc = 0
            over: list[dict] = []
            for cand in candidates:
                if acc + cand["bytes"] <= cap:
                    acc += cand["bytes"]
                else:
                    over.append(cand)
            candidates = over
        rule_report["candidates"] = len(candidates)
        out["plan"].extend(candidates)
    out["plan"].sort(key=lambda c: (c["rule"], c["path"]))
    out["total_bytes"] = sum(c["bytes"] for c in out["plan"])
    return out


# ── df-снимок ───────────────────────────────────────────────────────────────


def df_snapshot(roots) -> dict:
    """До/после: свободно/занято по ФС каждого существующего корня."""
    snap: dict = {}
    seen: set[str] = set()
    for root in roots:
        try:
            real = os.path.realpath(root)
        except OSError:
            continue
        if real in seen or not os.path.isdir(real):
            continue
        seen.add(real)
        try:
            usage = shutil.disk_usage(real)
        except OSError:
            continue
        snap[real] = {"total": usage.total, "used": usage.used,
                      "free": usage.free}
    return snap


# ── Применение плана (fail-closed, по-файлу) ────────────────────────────────


def _rules_by_key(rules) -> dict:
    return {r.key: r for r in rules}


def apply_plan(plan, *, rules=None, owner_confirm: bool = False,
               log=print) -> dict:
    """Удалить план по-файлу, повторно проверив КАЖДЫЙ путь.

    Примитив не доверяет входному плану: для каждого элемента заново
    (1) whitelist-контейнмент внутри корней СВОЕГО правила, (2) denylist,
    (3) соответствие паттерну правила. Только unlink файлов; каталоги,
    симлинки-эскейпы и всё вне корней блокируются с причиной."""
    rules = default_rules() if rules is None else rules
    by_key = _rules_by_key(rules)
    report = {"deleted": 0, "bytes_freed": 0, "skipped": 0, "blocked": 0,
              "errors": 0, "per_file": []}
    for item in plan or []:
        path = str(item.get("path", ""))
        rule = by_key.get(str(item.get("rule", "")))
        if rule is None:
            report["blocked"] += 1
            log(f"BLOCKED no-rule {path}")
            continue
        if not _contained_roots(path, rule.roots):
            report["blocked"] += 1
            log(f"BLOCKED outside-whitelist {path}")
            continue
        reason = deny_reason(path, owner_confirm=owner_confirm)
        if reason:
            report["blocked"] += 1
            log(f"BLOCKED {reason} {path}")
            continue
        if not _matches(os.path.basename(path), rule.patterns):
            report["blocked"] += 1
            log(f"BLOCKED pattern-mismatch {path}")
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            if not os.path.exists(path):
                report["skipped"] += 1
                continue
            report["blocked"] += 1
            log(f"BLOCKED not-regular-file {path}")
            continue
        try:
            size = _size(path)
            os.unlink(path)
        except FileNotFoundError:
            report["skipped"] += 1
            continue
        except OSError:
            report["errors"] += 1
            log(f"ERROR unlink-failed {path}")
            continue
        report["deleted"] += 1
        report["bytes_freed"] += size
        report["per_file"].append({"path": path, "bytes": size,
                                   "rule": rule.key})
        log(f"DELETE {rule.key} {human_bytes(size)} {path}")
    return report


# ── Опциональный apt-кэш (безопасная каноническая команда) ──────────────────

APT_CLEAN_CMD = ("apt-get", "clean")
APT_LISTS_MANUAL = ("rm -rf /var/lib/apt/lists/*  # ТОЛЬКО вручную @DevOps "
                    "(скрипт широкие rm -rf не исполняет; "
                    "списки регенерируются при первом apt update)")


def run_apt_clean(runner=None) -> dict:
    """`apt-get clean` (argv-список, без shell). Ошибки не фатальны."""
    runner = runner if runner is not None else subprocess.run
    try:
        proc = runner(list(APT_CLEAN_CMD), capture_output=True, text=True,
                      timeout=120, shell=False, check=False)
        return {"cmd": " ".join(APT_CLEAN_CMD), "returncode": proc.returncode}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"cmd": " ".join(APT_CLEAN_CMD), "returncode": None,
                "error": type(exc).__name__}


# ── Отчёт ───────────────────────────────────────────────────────────────────


def render_report(plan: dict, *, apply_report: dict | None = None,
                  df_before: dict | None = None,
                  df_after: dict | None = None,
                  apt_result: dict | None = None) -> str:
    lines: list[str] = []
    mode = "APPLY" if apply_report is not None else "DRY-RUN"
    lines.append(f"=== adminbot disk retention — {mode} "
                 f"(T-4506) ===")
    lines.append(f"enabled={plan['enabled']} scanned={plan['scanned']} "
                 f"candidates={len(plan['plan'])} "
                 f"protected={len(plan['protected'])}")
    lines.append("")
    lines.append("-- Классы (whitelist) --")
    rules_report = plan.get("rules", {})
    for key, info in rules_report.items():
        lines.append(f"  {key}: scanned={info['scanned']} "
                     f"candidates={info['candidates']} "
                     f"protected={info['protected']}")
    lines.append("")
    lines.append("-- План удаления (по-файлу) --")
    if plan["plan"]:
        for cand in plan["plan"]:
            age = cand.get("age_days")
            age_s = f" age={age}d" if age is not None else ""
            lines.append(f"  PLAN {cand['rule']} "
                         f"{human_bytes(cand['bytes'])}{age_s} {cand['path']}")
        lines.append(f"  TOTAL {human_bytes(plan.get('total_bytes', 0))}")
    else:
        lines.append("  (пусто — чистить нечего, идемпотентный no-op)")
    if plan["protected"]:
        lines.append("")
        lines.append("-- Защищено denylist'ом (не тронуто) --")
        for item in plan["protected"][:20]:
            lines.append(f"  KEEP {item['reason']} {item['path']}")
        if len(plan["protected"]) > 20:
            lines.append(f"  ... и ещё {len(plan['protected']) - 20}")
    if df_before:
        lines.append("")
        lines.append("-- df до --")
        for real, u in df_before.items():
            lines.append(f"  {real}: total={human_bytes(u['total'])} "
                         f"used={human_bytes(u['used'])} "
                         f"free={human_bytes(u['free'])}")
    if apply_report is not None:
        lines.append("")
        lines.append("-- Результат apply --")
        lines.append(f"deleted={apply_report['deleted']} "
                     f"freed={human_bytes(apply_report['bytes_freed'])} "
                     f"skipped={apply_report['skipped']} "
                     f"blocked={apply_report['blocked']} "
                     f"errors={apply_report['errors']}")
        if apt_result is not None:
            rc = apt_result.get("returncode")
            extra = apt_result.get("error", "")
            lines.append(f"apt: {apt_result['cmd']} returncode={rc} {extra}".rstrip())
        lines.append(f"apt-списки (вручную): {APT_LISTS_MANUAL}")
    if df_after:
        lines.append("")
        lines.append("-- df после --")
        for real, u in df_after.items():
            lines.append(f"  {real}: total={human_bytes(u['total'])} "
                         f"used={human_bytes(u['used'])} "
                         f"free={human_bytes(u['free'])}")
        if df_before:
            for real, u in df_after.items():
                before = df_before.get(real)
                if before:
                    delta = u["free"] - before["free"]
                    lines.append(f"  освобождено на {real}: "
                                 f"{human_bytes(max(0, delta))}")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Retention/cleanup диска по whitelist-классам "
                    "(T-4506; dry-run по умолчанию, удаление только --apply)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="реально удалить план (по умолчанию dry-run)")
    mode.add_argument("--dry-run", action="store_true",
                      help="явный dry-run (поведение по умолчанию)")
    parser.add_argument("--with-owner-confirm", action="store_true",
                        help="разблокировать migrate_history "
                             "(явное подтверждение владельца)")
    parser.add_argument("--with-apt", action="store_true",
                        help="при --apply дополнительно выполнить безопасный "
                             "'apt-get clean'")
    parser.add_argument("--json", action="store_true",
                        help="машиночитаемый вывод (план/отчёт/df) в stdout")
    args = parser.parse_args(argv)

    if not retention_enabled():
        print(f"[disk_retention] disabled via {ENABLED_ENV}=0 — no-op")
        return 0

    rules = default_rules()
    plan = build_plan(rules, owner_confirm=args.with_owner_confirm)
    all_roots: list[str] = []
    for rule in rules:
        all_roots.extend(rule.roots)
        all_roots.extend(rule.rank_roots)
    df_before = df_snapshot(all_roots)

    apply_report = None
    df_after = None
    apt_result = None
    if args.apply:
        apply_report = apply_plan(plan["plan"], rules=rules,
                                  owner_confirm=args.with_owner_confirm)
        if args.with_apt:
            apt_result = run_apt_clean()
        df_after = df_snapshot(all_roots)

    if args.json:
        payload = {
            "mode": "apply" if args.apply else "dry-run",
            "enabled": plan["enabled"],
            "scanned": plan["scanned"],
            "plan": plan["plan"],
            "total_bytes": plan.get("total_bytes", 0),
            "protected_count": len(plan["protected"]),
            "df_before": df_before,
            "df_after": df_after,
            "apply": apply_report,
            "apt": apt_result,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_report(plan, apply_report=apply_report,
                            df_before=df_before, df_after=df_after,
                            apt_result=apt_result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
