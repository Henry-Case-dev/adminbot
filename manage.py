#!/usr/bin/env python3
"""Фаза 2 (T-748..T-754) — argparse-диспетчер CLI импорта истории чатов.

Подкоманда `import_history` (--mode fts): потоковый разбор JSON-экспортов
Telegram Desktop (migrate_history/*.json) → smart_messages +
smart_messages_fts под таргет-чат (серверный этап, RAM-safe через ijson;
дедуп import_key + INSERT OR IGNORE, чекпоинты --resume).

Только stdout-логи/прогресс (tqdm — на stderr); бот не запускается
(side-эффектов bot.py нет). Секреты не печатаются (R17).

Примеры:
  python manage.py import_history --mode fts --all --dry-run
  python manage.py import_history --mode fts --all --resume
  python manage.py import_history --mode fts --only-live-chat --db snapshot.db
  python manage.py import_history --mode fts --files "2026.json" "10.08.2025.json"
"""
import argparse
import asyncio
import logging
import math
import sys
import time
from pathlib import Path

from config.settings import settings

# ── Охват импорта (spec §2.3/§3.2) ─────────────────────────────────────────
# 4 экспорта — история ОДНОГО переезжавшего чата; таргет памяти — runtime-
# супергруппа -1002661910336 (фаза 1 подтвердила). Имя файла «желтая до
# 10.2024.json» содержит кириллицу — передаётся явно (glob-сюрпризов нет).
HISTORY_DIR = Path("migrate_history")
DEFAULT_TARGET_CHAT = -1002661910336
LIVE_CHAT_EXPORT_ID = 2661910336          # экспорт-id live-чата (2 файла)

# Канонический порядок дедупа «свежий первым» (FR-2): 2026.json побеждает
# 10.08.2025.json на пересечении 31.03–10.08.2025 (INSERT OR IGNORE).
_FRESH_FIRST_PRIORITY = ("2026", "10.08.2025", "10.2024")


def _scope_priority(name: str) -> tuple:
    """Ключ сортировки файлов: свежие экспорты раньше (приоритет дедупа)."""
    for index, marker in enumerate(_FRESH_FIRST_PRIORITY):
        if marker in name:
            return (index, name)
    return (len(_FRESH_FIRST_PRIORITY), name)


def _history_files() -> list[str]:
    if not HISTORY_DIR.is_dir():
        raise SystemExit(
            f"папка {HISTORY_DIR} не найдена — положите JSON-экспорты сюда "
            f"(запуск из корня проекта)")
    files = sorted(
        (p.name for p in HISTORY_DIR.iterdir() if p.suffix.lower() == ".json"),
        key=_scope_priority,
    )
    if not files:
        raise SystemExit(f"в {HISTORY_DIR} нет *.json экспортов")
    return [str(HISTORY_DIR / name) for name in files]


def _resolve_scope(args) -> list[str]:
    """Охват: явный --files (порядок задаёт приоритет дедупа) | --all |
    --only-live-chat (детект по шапке файла: экспорт-id 2661910336)."""
    given = [flag for flag in ("files", "all", "only_live_chat")
             if getattr(args, flag, None)]
    if len(given) > 1:
        raise SystemExit("выберите ОДИН охват: --files ИЛИ --all ИЛИ "
                         "--only-live-chat")
    if args.files:
        missing = [p for p in args.files if not Path(p).is_file()]
        if missing:
            raise SystemExit(f"файл не найден: {missing[0]}")
        return args.files
    all_files = _history_files()
    if args.all:
        return all_files
    if args.only_live_chat:
        live = []
        for path in all_files:
            from tools.history_import.parser import detect_export_id
            export_id = detect_export_id(path)
            if export_id == LIVE_CHAT_EXPORT_ID:
                live.append(path)
            else:
                print(f"пропуск (не live-чат, export-id={export_id}): "
                      f"{Path(path).name}", file=sys.stderr)
        if not live:
            raise SystemExit(
                f"live-файлы (export-id {LIVE_CHAT_EXPORT_ID}) в "
                f"{HISTORY_DIR} не найдены")
        return live
    raise SystemExit(
        "выберите охват: --files <пути…> (порядок = приоритет «свежий "
        "первым») | --all (все экспорты migrate_history/) | --only-live-chat")


def _ensure_db(db_path: str) -> None:
    """Миграции v1..v7 через DatabaseService.initialize() + fail-fast:
    без колонки smart_messages.import_key (v7) FTS-этап не запускается."""
    from services.database import DatabaseService
    import aiosqlite

    async def _run() -> None:
        svc = DatabaseService(db_path)
        try:
            await svc.initialize()
        finally:
            await svc.close()
        conn = await aiosqlite.connect(db_path)
        try:
            cursor = await conn.execute(
                "PRAGMA table_info(smart_messages)")
            cols = {row[1] for row in await cursor.fetchall()}
            if "import_key" not in cols:
                raise SystemExit(
                    f"БД {db_path} без миграции v7 (нет smart_messages."
                    f"import_key) — влейте код с миграцией v7 и перезапустите "
                    f"бота один раз перед импортом")
        finally:
            await conn.close()

    asyncio.run(_run())


def _print_file_line(fr) -> None:
    stats = (f"прочитано {fr.read} | принято {fr.accepted} | "
             f"вставлено {fr.inserted} | дублей {fr.duplicates} | "
             f"с текстом {fr.with_text} | служебных {fr.skipped_service} | "
             f"пустых {fr.skipped_empty} | ошибок {fr.errors} | "
             f"{fr.rate():.0f} мсг/с | {fr.duration:.1f}с")
    print(f"  {Path(fr.path).name}: {stats}")


def _print_report(summary: dict, db_path: str | None = None) -> None:
    print("\n── Итог импорта истории ────────────────────────────────")
    for fr in summary["files"]:
        _print_file_line(fr)
    total = (
        f"прочитано {summary['read']} | принято {summary['accepted']}"
    )
    if not summary["dry_run"]:
        total += (f" | ВСТАВЛЕНО {summary['inserted']} | "
                  f"дублей {summary['duplicates']}")
    total += (f" | с текстом {summary['with_text']} | "
              f"служебных {summary['skipped_service']} | "
              f"пустых {summary['skipped_empty']} | "
              f"ошибок {summary['errors']}")
    print(f"итог: {total}")
    print(f"длительность: {summary['duration']:.1f}с")
    if not summary["dry_run"]:
        print(f"VACUUM: {'выполнен' if summary['vacuumed'] else 'пропущен'}")
        if db_path:
            _print_db_counts(db_path)


def _print_db_counts(db_path: str) -> None:
    import aiosqlite

    async def _counts() -> None:
        conn = await aiosqlite.connect(db_path)
        try:
            cursor = await conn.execute(
                "SELECT chat_id, COUNT(*) AS c FROM smart_messages "
                "GROUP BY chat_id ORDER BY c DESC")
            rows = await cursor.fetchall()
            print("строк smart_messages по чатам:")
            for chat_id, count in rows:
                print(f"  chat_id={chat_id}: {count}")
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM smart_messages_fts")
            print(f"строк smart_messages_fts: {(await cursor.fetchone())[0]}")
            cursor = await conn.execute(
                "SELECT COUNT(*) AS c FROM smart_messages "
                "WHERE import_key IS NOT NULL")
            print(f"строк с import_key: {(await cursor.fetchone())[0]}")
        finally:
            await conn.close()

    asyncio.run(_counts())


def _cmd_import_history_fts(args) -> int:
    from tqdm import tqdm

    from tools.history_import.loader import import_history_fts

    files = _resolve_scope(args)
    db_path = args.db or settings.DB_PATH
    if not args.dry_run:
        _ensure_db(db_path)
    print(f"FTS-импорт: {len(files)} файлов → chat_id={args.target_chat}")
    for path in files:
        print(f"  {path}")
    if args.reset:
        print("режим: --reset (чистый старт, чекпоинты сброшены)")
    elif args.resume:
        print("режим: --resume (перечитывание файлов; дубли отсекаются "
              "INSERT OR IGNORE)")
    if args.dry_run:
        print("режим: --dry-run (БЕЗ записи — аудит/статы)")
    if args.no_vacuum:
        print("режим: --no-vacuum (финальный VACUUM пропущен)")
    started = time.monotonic()

    def run() -> dict:
        return asyncio.run(import_history_fts(
            db_path, files, args.target_chat,
            batch_size=args.batch_size or 500,
            reset=args.reset, dry_run=args.dry_run,
            no_vacuum=args.no_vacuum,
            progress=tqdm(unit="msgs", desc="импорт", file=sys.stderr,
                          mininterval=1.0, dynamic_ncols=True)))

    summary = run()
    summary["duration"] = time.monotonic() - started
    _print_report(summary, db_path=None if args.dry_run else db_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="Служебный CLI бота: импорт истории чатов из "
                    "JSON-экспортов Telegram (фаза 2). Только stdout-логи, "
                    "бот не запускается.",
        epilog="Примеры:\n"
               "  python manage.py import_history --mode fts --all --dry-run\n"
               "  python manage.py import_history --mode fts --all --resume\n"
               "  python manage.py import_history --mode fts --only-live-chat")
    sub = parser.add_subparsers(dest="command", metavar="<команда>")
    sub.required = True

    imp = sub.add_parser(
        "import_history",
        help="импорт истории чатов (--mode fts)",
        description="Импорт JSON-экспортов Telegram Desktop (migrate_history/) "
                    "в память бота: smart_messages + smart_messages_fts "
                    "(идемпотентен, import_key + INSERT OR IGNORE; RAM-safe "
                    "ijson).")
    imp.add_argument("--mode", choices=("fts",), default="fts",
                     help="fts — сырьё в smart_messages+FTS (сервер)")
    imp.add_argument("--files", nargs="+", metavar="FILE",
                     help="JSON-экспорты (порядок = приоритет дедупа: свежий "
                          "первым); кириллические имена — явно")
    imp.add_argument("--all", action="store_true",
                     help="все экспорты из migrate_history/ "
                          "(канонический порядок «свежий первым»)")
    imp.add_argument("--only-live-chat", action="store_true",
                     help="только 2 файла live-чата (экспорт-id "
                          f"{LIVE_CHAT_EXPORT_ID}; детект по шапке файла)")
    imp.add_argument("--db", default=None,
                     help=f"путь SQLite-БД (дефолт: {settings.DB_PATH})")
    imp.add_argument("--target-chat", type=int, default=DEFAULT_TARGET_CHAT,
                     help="чат-таргет памяти (дефолт: "
                          f"{DEFAULT_TARGET_CHAT})")
    imp.add_argument("--batch-size", type=int, default=None,
                     help="строк на транзакцию (дефолт 500)")
    imp.add_argument("--resume", action="store_true",
                     help="продолжить (дубли отсекаются INSERT OR IGNORE)")
    imp.add_argument("--reset", action="store_true",
                     help="чистый старт (сброс чекпоинтов)")
    imp.add_argument("--dry-run", action="store_true",
                     help="без записи: разбор+статы")
    imp.add_argument("--no-vacuum", action="store_true",
                     help="пропустить wal_checkpoint+VACUUM")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass            # не-файловый поток (pytest-каптура и т.п.)
    args = build_parser().parse_args(argv)
    if args.command != "import_history":
        return 2
    return _cmd_import_history_fts(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
