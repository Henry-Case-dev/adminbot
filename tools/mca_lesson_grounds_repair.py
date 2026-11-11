"""Восстановление оснований уроков из сохранённых evidence-связей (12.11.2026).

Дефект: `ExperienceService.lesson.validate` заменял `mca_lessons.
independent_sources` более узким списком (для preference/humor-уроков —
пустым), поэтому у ПОДТВЕРЖДЁННОГО урока оставался `confirmation_count` без
единого основания. Функция восстановления читает ТОЛЬКО уже сохранённые
данные (`mca_evidence_links` → `mca_source_refs`).

Границы области (уточнено сухим прогоном на проде 2.58.190, 13.11.2026):

* правится ТОЛЬКО `confirmation_count > 0` при пустых основаниях — это и есть
  дефект;
* урок с `confirmation_count = 0` — законное «оснований пока нет»: он в
  `skipped_unconfirmed`, не трогается и не считается исправленным;
* если восстановленных оснований больше счётчика — `refused:
  grounds_exceed_counter` (другой дефект; список длиннее счётчика не пишем);
* нет связей → `refused: no_stored_evidence_links`;
* статус урока не меняется, «VERIFIED» не ставится, миграций и новых таблиц
  нет;
* идемпотентно: повторный прогон на тех же данных ничего не пишет.

По умолчанию — СУХОЙ прогон (ничего не пишет). Запись только с `--apply`:

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
        # Один и тот же код для отчёта и записи: правила не могут разойтись.
        return await store.recover_lesson_grounds(chat_id=chat_id,
                                                  limit=limit,
                                                  dry_run=not apply)
    finally:
        await db.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Восстановление оснований уроков (по умолчанию — сухой "
                    "прогон без записи).")
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
