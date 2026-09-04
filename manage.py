#!/usr/bin/env python3
"""Фаза 2 (T-748..T-764) — argparse-диспетчер CLI импорта истории чатов.

Подкоманда `import_history`:
  * --mode fts  — потоковый разбор JSON-экспортов Telegram Desktop
                  (migrate_history/*.json) → smart_messages + smart_messages_fts
                  под таргет-чат (серверный этап, RAM-safe через ijson);
  * --mode graph — GraphRAG-воркер истории (T-761..T-763): локальная Ollama
                  (qwen3.5:9b, think off) пачками по 25 извлекает значимые
                  факты из импортированного сырья → graph_facts
                  (origin history_import, weight 0.3, message_timestamp)
                  + FTS + vec (float+int8, --embed-mode api);
                  `--vec-backfill` — догонка векторов пропущенным фактам.

Только stdout-логи/прогресс (tqdm — на stderr); бот не запускается
(side-эффектов bot.py нет). Секреты не печатаются (R17).

Примеры:
  python manage.py import_history --mode fts --all --dry-run
  python manage.py import_history --mode fts --all --resume
  python manage.py import_history --mode fts --only-live-chat --db snapshot.db
  python manage.py import_history --mode fts --files "2026.json" "10.08.2025.json"
  python manage.py import_history --mode graph --db snapshot.db
  python manage.py import_history --mode graph --db snapshot.db --dry-run
  python manage.py import_history --mode graph --db snapshot.db \\
      --limit 100 --fact-density 0.15 --min-fact-chars 12
  python manage.py import_history --mode graph --db snapshot.db --vec-backfill
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

# Дефолты Graph-воркера (--mode graph; локальная Ollama юзера).
GRAPH_DEFAULT_ENDPOINT = "http://localhost:11434/v1"
GRAPH_DEFAULT_MODEL = "qwen3.5:9b"
GRAPH_DEFAULT_BATCH_SIZE = 25
GRAPH_DEFAULT_DENSITY = 0.15   # решение оркестратора после B5-аудита
GRAPH_DEFAULT_MIN_CHARS = 12
GRAPH_DEFAULT_EMBED_CONCURRENCY = 8

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


def _fmt_eta(seconds: float) -> str:
    """ETA/длительность «Xч Yм» / «Yм Zс» / «Zс»."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}ч {minutes}м"
    if minutes:
        return f"{minutes}м {secs}с"
    return f"{secs}с"


def _print_graph_report(stats: dict, *, dry_run: bool,
                        backfill: bool = False) -> None:
    print("\n── Итог Graph-этапа ─────────────────────────────────")
    if backfill:
        vec = stats.get("vec", {})
        print(f"vec-backfill: {stats.get('checked', 0)} фактов проверено | "
              f"векторов добавлено {stats.get('vec_rows', 0)} | "
              f"без vec {stats.get('no_vec', 0)} | "
              f"done={stats.get('done')}")
        if not vec.get("active", False):
            print(f"vec отключён: {vec.get('reason') or '?'}")
    else:
        vec = stats.get("vec", {})
        if dry_run:
            print(f"dry-run: кандидатов {stats.get('pending', 0)} | "
                  f"в пачки (density K={stats.get('k_step')}) "
                  f"{stats.get('selected', 0)} | пачек "
                  f"{stats.get('batches', 0)} | "
                  f"ожидаемых фактов ≈ {stats.get('est_facts', 0)}")
            print("LLM/embed-вызовы НЕ выполнялись (--dry-run); БД не менялась.")
            return
        print(f"пачек обработано: {stats.get('batches')} | "
              f"сообщений в пачках: {stats.get('selected_msgs')} | "
              f"фактов ВСТАВЛЕНО: {stats.get('facts_inserted')} | "
              f"дублей-IGNORE: {stats.get('facts_ignored_dupes')} | "
              f"без vec: {stats.get('no_vec')} | "
              f"ошибок LLM: {stats.get('llm_errors')}")
        if stats.get("batches"):
            duration = float(stats.get("duration") or 0)
            msg_rate = (stats["selected_msgs"] / duration
                        if duration else 0.0)
            print(f"фактов на пачку (средн.): "
                  f"{stats['facts_inserted'] / stats['batches']:.2f} | "
                  f"скорость: {msg_rate:.1f} мсг/с | "
                  f"длительность: {_fmt_eta(duration)}")
            remaining = max(0, (stats.get("total_selected", 0)
                                or 0) - stats.get("selected_msgs", 0))
            if remaining and msg_rate:
                print(f"ETA: {_fmt_eta(remaining / msg_rate)} "
                      f"(осталось ~{remaining} сообщений)")
        print(f"сообщений к обработке на старте: "
              f"{stats.get('total_selected', 0)} | done={stats.get('done')}")
        if not vec.get("active", False):
            print(f"vec не задействован: {vec.get('reason') or '?'} "
                  f"(факты живы текстом/FTS; догонка — --vec-backfill)")
        elif stats.get("no_vec"):
            print(f"{stats.get('no_vec')} фактов без вектора (embed-фейлы) — "
                  f"догонка --vec-backfill")


async def _dry_run_graph(db_path: str, args) -> dict:
    """--dry-run: подсчёт кандидатов/пачек БЕЗ записи и БЕЗ LLM (AC-8)."""
    from tools.history_import.llm_worker import GraphWorker
    worker = GraphWorker(db_path, llm=None, chat_id=args.chat,
                         batch_size=args.batch_size or GRAPH_DEFAULT_BATCH_SIZE,
                         fact_density=args.fact_density,
                         min_fact_chars=args.min_fact_chars)
    try:
        await worker.open()
        pending = await worker.pending_count()
        selected = await worker.pending_selected_count()
        batches = int(math.ceil(selected / max(1, worker.batch_size)))
        return {
            "pending": pending, "selected": selected,
            "batches": batches,
            "est_facts": batches * worker.max_facts_per_batch,
            "k_step": worker.k_step,
        }
    finally:
        await worker.close()


def _cmd_import_history_graph(args) -> int:
    from tqdm import tqdm

    from tools.history_import.llm_worker import (
        EmbedClient, GraphWorker, HistoryLLMClient, run_vec_backfill,
    )

    db_path = args.db or settings.DB_PATH
    graph_batch = args.batch_size or GRAPH_DEFAULT_BATCH_SIZE
    if args.vec_backfill:
        print("Graph: --vec-backfill (догонка векторов фактам history_import "
              "без vec-строки)")
        if args.dry_run:
            print("--dry-run с --vec-backfill не поддерживается: догонка "
                  "требует embed-API (для подсчёта откройте БД SQL-запросом: "
                  "SELECT COUNT(*) FROM graph_facts WHERE origin='history_import'"
                  " AND id NOT IN (SELECT fact_id FROM graph_facts_vec)); "
                  "БД не тронута", file=sys.stderr)
            return 1
        progress = tqdm(unit="facts", desc="vec-backfill",
                        file=sys.stderr, mininterval=1.0,
                        dynamic_ncols=True)

        async def _run_backfill() -> dict:
            embed = EmbedClient(concurrency=args.embed_concurrency)
            try:
                return await run_vec_backfill(
                    db_path, embed_client=embed, chat_id=args.chat,
                    progress=progress)
            finally:
                await embed.aclose()

        stats = asyncio.run(_run_backfill())
        try:
            progress.close()
        except Exception:
            pass
        _print_graph_report(stats, dry_run=False, backfill=True)
        return 0

    print(f"Graph-этап (T-761..T-763): chat_id={args.chat} | "
          f"endpoint={args.endpoint} | transport={args.transport} | "
          f"model={args.model} | density={args.fact_density} (K="
          f"{max(1, min(1000, int(round(1 / max(args.fact_density, 0.01)))))})"
          f" | batch={graph_batch} | min-fact-chars="
          f"{args.min_fact_chars} | embed-mode={args.embed_mode}")
    if args.dry_run:
        print("режим: --dry-run (без записи, без LLM — подсчёт)")
    elif args.reset:
        print("режим: --reset (все импортированные строки чата будут "
              "переобработаны; дубли фактов отсекутся UNIQUE-индексом)")
    else:
        print("режим: resume автоматический (history_processed=0); "
              "прерывание Ctrl+C безопасно — повторный запуск продолжит")
    if args.skip_errors:
        print("режим: --skip-errors (битые пачки пропускаются, НЕ помечаются)")

    if args.dry_run:
        stats = asyncio.run(_dry_run_graph(db_path, args))
        _print_graph_report(stats, dry_run=True)
        return 0
    progress = tqdm(unit="msgs", desc="graph", file=sys.stderr,
                    mininterval=1.0, dynamic_ncols=True)

    async def _run() -> dict:
        llm = HistoryLLMClient(
            model=args.model, endpoint=args.endpoint,
            transport=args.transport, think_off_mode=args.think_off_mode)
        embed = None
        if args.embed_mode == "api":
            embed = EmbedClient(concurrency=args.embed_concurrency)
        worker = GraphWorker(db_path, llm=llm, embed_client=embed,
                             chat_id=args.chat,
                             batch_size=graph_batch,
                             fact_density=args.fact_density,
                             min_fact_chars=args.min_fact_chars,
                             embed_mode=args.embed_mode,
                             skip_errors=args.skip_errors,
                             progress=progress)
        try:
            return await worker.run(limit_batches=args.limit,
                                    reset=args.reset)
        finally:
            await llm.aclose()
            if embed is not None:
                await embed.aclose()

    try:
        stats = asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nпрервано (Ctrl+C): обработанные пачки помечены "
              "processed=1 — повторный запуск продолжит с места", 
              file=sys.stderr)
        try:
            progress.close()
        except Exception:
            pass
        return 1
    except Exception as exc:
        print(f"ошибка Graph-этапа: {exc}", file=sys.stderr)
        try:
            progress.close()
        except Exception:
            pass
        return 1
    try:
        progress.close()
    except Exception:
        pass
    _print_graph_report(stats, dry_run=False)
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
               "  python manage.py import_history --mode fts --only-live-chat\n"
               "  python manage.py import_history --mode graph --db snapshot.db\n"
               "  python manage.py import_history --mode graph --db snapshot.db\n"
               "      --limit 100 --fact-density 0.15\n"
               "  python manage.py import_history --mode graph --db snapshot.db\n"
               "      --vec-backfill")
    sub = parser.add_subparsers(dest="command", metavar="<команда>")
    sub.required = True

    imp = sub.add_parser(
        "import_history",
        help="импорт истории чатов: --mode fts (сервер) | graph (локально)",
        description="Импорт JSON-экспортов Telegram Desktop (migrate_history/) "
                    "в память бота. --mode fts: smart_messages + "
                    "smart_messages_fts (идемпотентен, import_key + "
                    "INSERT OR IGNORE; RAM-safe ijson). --mode graph: "
                    "GraphRAG-воркер на локальной Ollama (пачки по 25 → "
                    "graph_facts origin history_import + FTS + vec).")
    imp.add_argument("--mode", choices=("fts", "graph"), default="fts",
                     help="fts — сырьё в smart_messages+FTS (сервер); "
                          "graph — GraphRAG-воркер истории (локальная Ollama)")
    imp.add_argument("--files", nargs="+", metavar="FILE",
                     help="JSON-экспорты (--mode fts; порядок = приоритет "
                          "дедупа: свежий первым); кириллические имена — явно")
    imp.add_argument("--all", action="store_true",
                     help="--mode fts: все экспорты из migrate_history/ "
                          "(канонический порядок «свежий первым»)")
    imp.add_argument("--only-live-chat", action="store_true",
                     help="--mode fts: только 2 файла live-чата (экспорт-id "
                          f"{LIVE_CHAT_EXPORT_ID}; детект по шапке файла)")
    imp.add_argument("--db", default=None,
                     help=f"путь SQLite-БД (дефолт: {settings.DB_PATH}); для "
                          f"graph — СНАПШОТ прод-БД, не живая БД бота)")
    imp.add_argument("--target-chat", type=int, default=DEFAULT_TARGET_CHAT,
                     help="--mode fts: чат-таргет памяти (дефолт: "
                          f"{DEFAULT_TARGET_CHAT})")
    imp.add_argument("--batch-size", type=int, default=None,
                     help="fts: строк на транзакцию (дефолт 500); "
                          "graph: сообщений в пачке (дефолт 25)")
    imp.add_argument("--resume", action="store_true",
                     help="fts: продолжить (дубли отсекаются INSERT OR "
                          "IGNORE); graph: продолжение и так автоматическое "
                          "(history_processed) — флаг принимается для "
                          "единообразия")
    imp.add_argument("--reset", action="store_true",
                     help="fts: чистый старт (сброс чекпоинтов); graph: "
                          "переобработка всех импортированных строк чата")
    imp.add_argument("--dry-run", action="store_true",
                     help="без записи: fts — разбор+статы; graph — подсчёт "
                          "кандидатов/пачек (LLM НЕ вызывается)")
    imp.add_argument("--no-vacuum", action="store_true",
                     help="--mode fts: пропустить wal_checkpoint+VACUUM")
    # ── Graph-воркер (--mode graph; часть B, T-761..T-763) ─────────
    imp.add_argument("--chat", type=int, default=DEFAULT_TARGET_CHAT,
                     help=f"--mode graph: чат-источник сырья (дефолт: "
                          f"{DEFAULT_TARGET_CHAT})")
    imp.add_argument("--endpoint", default=GRAPH_DEFAULT_ENDPOINT,
                     help=f"--mode graph: эндпоинт Ollama (дефолт: "
                          f"{GRAPH_DEFAULT_ENDPOINT})")
    imp.add_argument("--transport", choices=("auto", "openai", "ollama"),
                     default="auto",
                     help="--mode graph: auto — openai, если endpoint "
                          "заканчивается /v1, иначе нативный ollama "
                          "(/api/chat)")
    imp.add_argument("--think-off-mode",
                     choices=("auto", "reasoning_effort", "ollama_chat"),
                     default="auto",
                     help="--mode graph: способ выключения думания qwen3.5: "
                          "auto — оба поля (think:false + reasoning_effort:"
                          "none, belt-and-suspenders); reasoning_effort — "
                          "только OpenAI-поле; ollama_chat — только "
                          "нативное think:false")
    imp.add_argument("--model", default=GRAPH_DEFAULT_MODEL,
                     help=f"--mode graph: модель Ollama (дефолт: "
                          f"{GRAPH_DEFAULT_MODEL}; резерв без думания — "
                          f"qwen3:14b)")
    imp.add_argument("--limit", type=int, default=0,
                     help="--mode graph: остановиться после N пачек "
                          "(0 = все непомеченные; пробный прогон/ETA-замер)")
    imp.add_argument("--fact-density", type=float,
                     default=GRAPH_DEFAULT_DENSITY,
                     help=f"--mode graph: плотность фактов — берётся ~каждое "
                          f"K-е сообщение, K=round(1/density) (дефолт: "
                          f"{GRAPH_DEFAULT_DENSITY} по решению оркестратора "
                          f"после B5-аудита)")
    imp.add_argument("--min-fact-chars", type=int,
                     default=GRAPH_DEFAULT_MIN_CHARS,
                     help=f"--mode graph: мин. длина ТЕКСТА сообщения для "
                          f"участия в пачке — отсев мелочи (дефолт: "
                          f"{GRAPH_DEFAULT_MIN_CHARS})")
    imp.add_argument("--embed-mode", choices=("api", "skip"), default="api",
                     help="--mode graph: api — vec float+int8 через "
                          "API-эмбеддинги (.env ноутбука: LLM_BASE_URL/"
                          "EMBEDDING_*); skip — факты текстом+FTS, "
                          "векторы потом --vec-backfill")
    imp.add_argument("--embed-concurrency", type=int,
                     default=GRAPH_DEFAULT_EMBED_CONCURRENCY,
                     help=f"--mode graph: параллельных embed-запросов "
                          f"(дефолт: {GRAPH_DEFAULT_EMBED_CONCURRENCY})")
    imp.add_argument("--skip-errors", action="store_true",
                     help="--mode graph: битые пачки (LLM-ошибка после "
                          "ретраев) пропускать с WARNING и НЕ помечать "
                          "(повторятся след. запуском); без флага — стоп "
                          "с ошибкой")
    imp.add_argument("--vec-backfill", action="store_true",
                     help="--mode graph: подрежим догонки векторов — фактам "
                          "origin='history_import' без vec-строки (после "
                          "--embed-mode skip)")
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
    if args.mode == "graph":
        return _cmd_import_history_graph(args)
    return _cmd_import_history_fts(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
