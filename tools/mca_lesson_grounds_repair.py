"""Восстановление оснований уроков из сохранённых evidence-связей (12.11.2026).

Дефект: `ExperienceService.lesson.validate` заменял `mca_lessons.
independent_sources` более узким списком (для preference/humor-уроков —
пустым), поэтому у подтверждённого урока оставался `confirmation_count`
без единого основания. Функция восстановления читает ТОЛЬКО уже сохранённые
данные (`mca_evidence_links` → `mca_source_refs`) и дописывает найденные
основания в пустой список.

Границы (не менять без отдельного решения):
* ничего не выдумывает: нет связей — урок попадает в `refused`;
* статус урока не меняется, «VERIFIED» не ставится;
* нет колонок v46 (старая БД) — честный отказ без падения;
* идемпотентно: повторный прогон на тех же данных ничего не пишет;
* без миграций, без новых таблиц.

Использование (локальная копия БД, не рабочий файл прода):

    py -3 tools/mca_lesson_grounds_repair.py --db backup.db            # отчёт
    py -3 tools/mca_lesson_grounds_repair.py --db backup.db --apply    # запись
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _run(path: str, *, apply: bool, chat_id: int | None,
               limit: int) -> dict:
    from services.database import DatabaseService
    from services.mca_experience import get_service

    db = DatabaseService(path)
    await db.initialize()
    try:
        store = get_service(db).store
        if not apply:
            # Сухой прогон: считаем то же, но без записи.
            return await _dry_run(db, store, chat_id=chat_id, limit=limit)
        return await store.recover_lesson_grounds(chat_id=chat_id,
                                                  limit=limit)
    finally:
        await db.close()


async def _dry_run(db, store, *, chat_id, limit) -> dict:
    """Тот же отбор и те же правила, но без UPDATE."""
    report = {"scanned": 0, "repaired": [], "refused": [], "unchanged": 0,
              "dry_run": True}
    try:
        columns = {str(r["name"]) for r in await (await db.db.execute(
            "PRAGMA table_info(mca_lessons)")).fetchall()}
    except Exception:
        columns = set()
    if not {"independent_sources", "confirmation_count"} <= columns:
        report["refused"].append({"reason": "schema_without_v46_columns"})
        return report
    where = " AND scope_chat_id = ?" if chat_id is not None else ""
    params: tuple = (int(chat_id),) if chat_id is not None else ()
    cursor = await db.db.execute(
        "SELECT lesson_id, version, scope_chat_id, source_ref_id, "
        "independent_sources FROM mca_lessons WHERE "
        "(independent_sources IS NULL OR independent_sources IN ('', '[]'))"
        + where + " ORDER BY updated_at DESC LIMIT ?",
        (*params, max(1, int(limit))))
    rows = [dict(r) for r in await cursor.fetchall()]
    report["scanned"] = len(rows)
    if not rows:
        return report
    links = await store.lesson_grounds_from_links(
        [r.get("source_ref_id") for r in rows])
    from services.mca_experience import _ground_token
    for row in rows:
        recovered = []
        for ref in (links.get(int(row.get("source_ref_id") or 0), [])
                    if row.get("source_ref_id") is not None else []):
            token = _ground_token(ref, row.get("scope_chat_id"))
            if token and token not in recovered:
                recovered.append(token)
        entry = {"lesson_id": str(row.get("lesson_id") or ""),
                 "version": int(row.get("version") or 0)}
        if recovered:
            entry["would_restore"] = sorted(recovered)
            report["repaired"].append(entry)
        else:
            entry["reason"] = "no_stored_evidence_links"
            report["refused"].append(entry)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="путь к файлу SQLite")
    parser.add_argument("--apply", action="store_true",
                        help="записать восстановление (по умолчанию — отчёт)")
    parser.add_argument("--chat-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    report = asyncio.run(_run(args.db, apply=args.apply,
                              chat_id=args.chat_id, limit=args.limit))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
