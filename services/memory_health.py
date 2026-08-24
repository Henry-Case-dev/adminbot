"""Epic 60 (Section 64.5, T-466): метрики здоровья памяти — data-блок для
чекапа.

Только дешёвые SELECT/os-статс, БЕЗ LLM и БЕЗ токсичности (токсичность
добавит LLM по R42-6 — CHECKUP_SYSTEM_PROMPT не меняется). Все значения —
строками. Персональных данных нет (R17, карточки людей 66.9 сюда НЕ
попадают). Любая ошибка → WARNING → "" (чекап работает как раньше).
"""
import logging
import os
import shutil
import time

logger = logging.getLogger(__name__)


def _gib(value) -> str:
    return "?" if value is None else f"{value / (1024 ** 3):.1f} GiB"


def _mib(value) -> str:
    return "?" if value is None else f"{value / (1024 ** 2):.1f} MiB"


def _rss_bytes() -> int | None:
    """VmRSS из /proc/self/status (Linux-прод); нет файла → None (строка
    опускается — Windows-dev)."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024   # kB → байты
    except Exception:
        pass
    return None


async def _count(db, sql: str, params: tuple = ()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return row[0] if row else 0


async def collect_metrics(db, memory) -> str:
    """Готовый текстовый блок фикс-формата (64.5) или "" при ошибке."""
    try:
        now = int(time.time())
        lines = []

        total_facts = await _count(db, "SELECT COUNT(*) FROM graph_facts")
        cursor = await db.db.execute(
            "SELECT origin, COUNT(*) AS c FROM graph_facts GROUP BY origin "
            "ORDER BY origin")
        origins = {r["origin"]: r["c"] for r in await cursor.fetchall()}
        origin_part = ", ".join(f"{origin} {count}"
                                for origin, count in origins.items())
        lines.append(f"graph_facts: {total_facts}"
                     + (f" ({origin_part})" if origin_part else ""))

        expired = await _count(
            db, "SELECT COUNT(*) FROM graph_facts "
                "WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        unconfirmed = await _count(
            db, "SELECT COUNT(*) FROM graph_facts WHERE status = 'unconfirmed'")
        lines.append(f"graph_facts: просрочено {expired}, "
                     f"не подтверждено {unconfirmed}")

        lines.append(f"smart_archive_facts: "
                     f"{await _count(db, 'SELECT COUNT(*) FROM smart_archive_facts')}")
        lines.append(f"smart_messages: "
                     f"{await _count(db, 'SELECT COUNT(*) FROM smart_messages')}")
        nodes = await _count(db, "SELECT COUNT(*) FROM nodes")
        edges = await _count(db, "SELECT COUNT(*) FROM edges")
        lines.append(f"nodes: {nodes}, edges: {edges}")
        lines.append(f"embedding_cache: "
                     f"{await _count(db, 'SELECT COUNT(*) FROM embedding_cache')} строк")
        lines.append(f"throttle_state: "
                     f"{await _count(db, 'SELECT COUNT(*) FROM throttle_state')} строк")
        lines.append(f"smart_cache: "
                     f"{await _count(db, 'SELECT COUNT(*) FROM smart_cache')} строк")

        if memory is not None and getattr(memory, "vec_available", False):
            dim = getattr(memory, "_vec_dim", None)
            vec_rows: dict[str, int] = {}
            for table, label in (("smart_archive", "archive"),
                                 ("graph_facts_vec", "graph")):
                try:
                    vec_rows[label] = await _count(
                        db, f"SELECT COUNT(*) FROM {table}")
                except Exception:
                    vec_rows[label] = 0
            lines.append(f"vec: float32 dim={dim}, строк "
                         f"{vec_rows['graph'] + vec_rows['archive']} "
                         f"(graph {vec_rows['graph']}, archive {vec_rows['archive']})")
        else:
            lines.append("vec: недоступен")

        day_facts = await _count(
            db, "SELECT COUNT(*) FROM graph_facts WHERE created_at > ?",
            (now - 86400,))
        compressions = await _count(
            db, "SELECT COUNT(*) FROM graph_fact_compressions")
        lines.append(f"записано фактов за сутки: {day_facts}, "
                     f"дублей отсеяно: {compressions}")

        try:
            usage = shutil.disk_usage("/")
            lines.append(f"диск: свободно {_gib(usage.free)} "
                         f"из {_gib(usage.total)}")
        except Exception:
            pass

        db_size = wal_size = None
        try:
            db_path = getattr(db, "db_path", None)
            if db_path is not None and str(db_path) != ":memory:" \
                    and os.path.isfile(db_path):
                db_size = os.path.getsize(db_path)
                wal_path = str(db_path) + "-wal"
                wal_size = (os.path.getsize(wal_path)
                            if os.path.isfile(wal_path) else 0)
        except Exception:
            pass
        if db_size is not None:
            lines.append(f"бд: {_mib(db_size)}, wal: {_mib(wal_size)}")

        rss = _rss_bytes()
        if rss is not None:
            lines.append(f"память процесса: rss {_mib(rss)}")

        return "\n".join(lines)
    except Exception:
        logger.warning("memory_health: collect failed", exc_info=True)
        return ""
