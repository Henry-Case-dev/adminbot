"""mca-06 T-4712: обследование сохранности `message_timestamp` в реальной БД.

READ-ONLY, bounded data-операция (ADR-1028-9 D4, spec §4.3): считает долю
фактов с/без валидного `message_timestamp` и ограниченно восстанавливает
пропущенные по оригиналам (`smart_archive_facts.timestamp` — то же основание
по `(chat_id, fact)`). Смысловые значения вне восстановительного контракта
НЕ меняются; запись в БД не производится.

Запуск:
  .venv/Scripts/python.exe tools/mca06_timestamp_audit.py [DB_PATH]
Отчёт: plans/reports/mca06_t4712_timestamp_audit.md
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
REPORT = os.path.join("plans", "reports", "mca06_t4712_timestamp_audit.md")
BOUND = 5000


def _pick_db(argv) -> str:
    if len(argv) > 1:
        return argv[1]
    for cand in ("local_database.db",):
        if os.path.exists(cand):
            try:
                c = sqlite3.connect("file:%s?mode=ro" % cand, uri=True)
                has = c.execute(
                    "select name from sqlite_master where type='table' "
                    "and name='graph_facts'").fetchone()
                if has:
                    return cand
            except Exception:
                pass
            finally:
                try:
                    c.close()
                except Exception:
                    pass
    hist = [f for f in os.listdir(".") if f.startswith("local_database_")
            and f.endswith("_history.db")]
    if hist:
        return sorted(hist)[-1]
    return "local_database.db"


def audit(db_path: str) -> dict:
    c = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    out = {"db": db_path, "total": 0, "with_ts": 0, "missing": 0,
           "recovered": 0, "samples": [], "smart_messages": None}
    try:
        out["total"] = int(c.execute(
            "select count(*) from graph_facts").fetchone()[0])
        out["with_ts"] = int(c.execute(
            "select count(*) from graph_facts "
            "where message_timestamp is not null "
            "and message_timestamp > 0").fetchone()[0])
        out["missing"] = out["total"] - out["with_ts"]
        # bounded recovery по оригиналам (READ-ONLY, LIMIT).
        rows = c.execute(
            "select id, chat_id, fact from graph_facts "
            "where message_timestamp is null or message_timestamp <= 0 "
            "limit ?", (BOUND,)).fetchall()
        for fid, chat_id, fact in rows:
            try:
                r = c.execute(
                    "select timestamp from smart_archive_facts "
                    "where chat_id = ? and fact = ? and timestamp > 0 "
                    "limit 1", (chat_id, fact)).fetchone()
            except Exception:
                r = None
            if r and r[0]:
                out["recovered"] += 1
            if len(out["samples"]) < 5:
                out["samples"].append(
                    {"id": fid, "recovered": bool(r and r[0])})
        try:
            out["smart_messages"] = {
                "total": int(c.execute(
                    "select count(*) from smart_messages").fetchone()[0]),
                "with_ts": int(c.execute(
                    "select count(*) from smart_messages "
                    "where timestamp is not null and timestamp > 0"
                ).fetchone()[0]),
                "with_tg": int(c.execute(
                    "select count(*) from smart_messages "
                    "where tg_message_id is not null").fetchone()[0]),
            }
        except Exception:
            pass
    finally:
        c.close()
    return out


def render(r: dict) -> str:
    pct = (100.0 * r["with_ts"] / r["total"]) if r["total"] else 0.0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# mca-06 T-4712 — обследование `message_timestamp` (реальная БД)",
        "",
        "> READ-ONLY, bounded (ADR-1028-9 D4, spec §4.3). Без записи в БД.",
        "> Сгенерировано: %s" % now,
        "",
        "## ДБ",
        "- `%s`" % r["db"],
        "",
        "## Сохранность `message_timestamp` (graph_facts)",
        "- Всего фактов: **%d**" % r["total"],
        "- С валидным `message_timestamp`: **%d** (%.2f%%)" % (
            r["with_ts"], pct),
        "- Без валидного `message_timestamp`: **%d**" % r["missing"],
        "",
        "## Bounded восстановление по оригиналам",
        "- Кандидатов к восстановлению (LIMIT %d): **%d**" % (
            BOUND, min(r["missing"], BOUND)),
        "- Восстановлено по `smart_archive_facts.timestamp` "
        "(`chat_id`+`fact`): **%d**" % r["recovered"],
        "- Сэмпл: %s" % ", ".join(
            "#%s%s" % (s["id"], "✓" if s["recovered"] else "✗")
            for s in r["samples"]),
        "",
    ]
    sm = r.get("smart_messages")
    if sm:
        lines += [
            "## Справочно: smart_messages",
            "- Всего сообщений: %d; с `timestamp`: %d; с `tg_message_id`: %d"
            % (sm["total"], sm["with_ts"], sm["with_tg"]),
            "",
        ]
    lines += [
        "## Контракт",
        "- Восстановление не меняет смысловые значения (только дата события).",
        "- Возраст исторического порога считается ТОЛЬКО по валидному",
        "  `message_timestamp`; unknown ≠ «старая» (T-4711).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    db_path = _pick_db(sys.argv)
    r = audit(db_path)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(render(r))
    print("REPORT:", REPORT)
    print("total=%d with_ts=%d missing=%d recovered=%d" % (
        r["total"], r["with_ts"], r["missing"], r["recovered"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
