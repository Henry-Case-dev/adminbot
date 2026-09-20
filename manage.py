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
import datetime
import json
import logging
import math
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from config.settings import settings

# ── Охват импорта (spec §2.3/§3.2) ─────────────────────────────────────────
# 4 экспорта — история ОДНОГО переезжавшего чата; таргет памяти — runtime-
# супергруппа -1002661910336 (фаза 1 подтвердила). Имя файла «желтая до
# 10.2024.json» содержит кириллицу — передаётся явно (glob-сюрпризов нет).
HISTORY_DIR = Path("migrate_history")
# LEGACY (D-2.8, ревью итерации 4): исторический id целевого чата фазы 1 —
# НЕ бизнес-логика и НЕ настройка; конкретный runtime-id задаётся явным
# `--target-chat`/`--chat` (или данными `config/chat_settings_seed.json`).
# Оставлен только как дефолт CLI-удобства с явным legacy-маркером.
LEGACY_TARGET_CHAT_ID = -1002661910336
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

# Задача 2 (2026-09-05): единая консольная фраза ручного останова (Ctrl+C).
# Прогресс Graph-этапа пишется по факту обработанных пачек → повторный
# запуск продолжает с чекпоинта (history_processed=0/1).
_KI_NOTICE = ("⏸ Остановлено вручную (Ctrl+C). Прогресс сохранён: "
              "повторный запуск продолжит с места остановки.")
_KI_EXIT_CODE = 130                 # 128 + SIGINT


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
        EmbedClient, EmbedError, GraphWorker, HistoryLLMClient,
        HistoryLLMError, humanize_embed_error, humanize_history_llm_error,
        run_vec_backfill,
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
    if not args.dry_run:
        # Задача 2: подсказка паузы в начале прогона (Ctrl+C — безопасно).
        print(f"Пауза в любой момент: Ctrl+C (прогресс сохраняется)")

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
        # Задача 2: единая фраза останова + exit-код 130 (без трейсбека).
        print(f"\n{_KI_NOTICE}", file=sys.stderr)
        try:
            progress.close()
        except Exception:
            pass
        return _KI_EXIT_CODE
    except (EmbedError, HistoryLLMError) as exc:
        # Задача 3: причину человекочитаемо — РАЗДЕЛЬНО: HistoryLLMError —
        # про парсинг фактов/локальную LLM (humanize_history_llm_error),
        # EmbedError — про эмбеддинги (humanize_embed_error; тип/код
        # сохранены в тексте). Стоп-ошибка (5 подряд) несёт готовый
        # человеческий текст в exc.reason.
        if isinstance(exc, HistoryLLMError):
            reason = getattr(exc, "reason", None) \
                or humanize_history_llm_error(exc)
        else:
            reason = getattr(exc, "reason", None) \
                or humanize_embed_error(exc)
        print(f"ошибка Graph-этапа: {reason} | тип={type(exc).__name__} | "
              f"детали: {exc}", file=sys.stderr)
        try:
            progress.close()
        except Exception:
            pass
        return 1
    except Exception as exc:
        print(f"ошибка Graph-этапа: {type(exc).__name__}: {exc}",
              file=sys.stderr)
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
    imp.add_argument("--target-chat", type=int, default=LEGACY_TARGET_CHAT_ID,
                     help="--mode fts: чат-таргет памяти (legacy-дефолт: "
                          f"{LEGACY_TARGET_CHAT_ID}; лучше задать явно)")
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
    imp.add_argument("--chat", type=int, default=LEGACY_TARGET_CHAT_ID,
                     help=f"--mode graph: чат-источник сырья (legacy-дефолт: "
                          f"{LEGACY_TARGET_CHAT_ID}; лучше задать явно)")
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
                     help="--mode graph: битые пачки (LLM-ошибка/битый "
                          "JSON после ретраев) пропускать с WARNING и НЕ "
                          "помечать (повторятся след. запуском); пачки "
                          "и так НЕ фатальны — без флага стоп только после "
                          "5 ошибок ПОДРЯД, с флагом — продолжаем всегда")
    imp.add_argument("--vec-backfill", action="store_true",
                     help="--mode graph: подрежим догонки векторов — фактам "
                          "origin='history_import' без vec-строки (после "
                          "--embed-mode skip)")
    # ── F3 (10.19, ADR-1019-8 D4): сид настроек чатов (опционально) ─────────────
    overrides = sub.add_parser(
        "apply-chat-overrides",
        help="применить декларативные настройки чатов из config/chat_settings_seed.json",
        description="Идемпотентный сид эксклюзивных per-chat настроек "
                    "(retention 0=вечно, бюджеты/контекст −1) из "
                    "config/chat_settings_seed.json. Повторный прогон — no-op.")
    overrides.add_argument("--force", action="store_true",
                     help="перезаписать бюджеты/контекст даже при ручной "
                          "правке (enforce-ключи применяются всегда)")
    overrides.add_argument("--seed", default=None,
                     help="путь сида (дефолт: config/chat_settings_seed.json)")
    # ── F22 (10.24, ADR-1024-23 D5): read-only аудит overrides/истории ──────
    audit = sub.add_parser(
        "audit-chat-overrides",
        help="READ-ONLY аудит per-chat overrides и истории правок (F22)",
        description="READ-ONLY (только SELECT): фактический набор overrides "
                    "чата и сверка с эталоном сида (ok|absent|different), "
                    "таймлайн chat_lore_history field='chat_params' с "
                    "детектором вайпа, chat_keys — только {configured,last4}, "
                    "счётчики chat_usage/worker_budget/bot_settings и резолв "
                    "flags.chat_context_budgets_enabled. Секреты не выводятся "
                    "(R17/R18); JSONL — в gitignored var/audit/.")
    audit.add_argument("--chat-id", type=int, required=True,
                       help="chat_id для аудита (обязателен)")
    audit.add_argument("--seed", default=None,
                       help="путь сида-эталона (дефолт: "
                            "config/chat_settings_seed.json)")
    audit.add_argument("--history-limit", type=int, default=200,
                       help="потолок строк таймлайна chat_params (дефолт 200)")
    audit.add_argument("--jsonl", default=None,
                       help="путь JSONL-выгрузки (дефолт: var/audit/"
                            "chat_overrides_<chat_id>_<utc>.jsonl)")
    audit.add_argument("--strict", action="store_true",
                       help="non-zero exit при дрейфе "
                            "(absent/different/wipe_suspected)")
    # ── F7 (10.19, ADR-1019-6 D2, D-2 ревью Батча E): retention импорта ──
    ret = sub.add_parser(
        "retention",
        aliases=("retention-dry-run",),
        help="retention импорта: dry-run (дефолт) | --apply (реальный purge)",
        description="F7: архивирует и удаляет ИМПОРТИРОВАННУЮ историю "
                    "(smart_messages, import_key + history_processed=1) "
                    "старше per-chat срока; чаты с retention 0 (вечно) не затрагиваются. "
                    "БЕЗ `--apply` — только подсчёт (dry-run, безопасно). "
                    "С `--apply` — обязательный архив в файл, затем purge; "
                    "сверка архива/кандидатов, иначе удаление отменяется. "
                    "Авто-крон гейтится env IMPORT_RETENTION_ENABLED "
                    "(default OFF) + IMPORT_RETENTION_DRY_RUN (default ON) + "
                    "IMPORT_RETENTION_BACKUP_CONFIRMED (default OFF).")
    ret.add_argument("--dry-run", action="store_true",
                     help="только подсчёт (по умолчанию и так dry-run; флаг "
                          "делает намерение явным и защищает от --apply)")
    ret.add_argument("--apply", action="store_true",
                     help="ВЫПОЛНИТЬ удаление после архива (по умолчанию — "
                          "dry-run: только счётчики, данные не удаляются)")
    ret.add_argument("--db", default=None,
                     help=f"путь SQLite-БД (дефолт: {settings.DB_PATH})")
    ret.add_argument("--batch", type=int, default=2000,
                     help="строк на пачку при архиве/purge (дефолт 2000)")
    ret.add_argument("--archive-dir", default=None,
                     help="каталог файла-архива (дефолт: MEMORY_BACKUP_DIR)")
    # ── F4/F5 (10.21, ADR-1021-4 / ADR-1021-5): CLI памяти ─────────────────
    # Дефолт — БОЕВОЙ прогон (`apply`); обязательный dry-run и двойные
    # env-подтверждения ОТМЕНЕНЫ (UPD). `--dry-run` — опциональная диагностика.
    # ⛔ Сырая история (smart_messages/импорт) не мутируется ни при каких
    # обстоятельствах (guard allowlist в services/memory_rebuild.py).
    mem = sub.add_parser(
        "memory",
        help="память: rebuild-dossiers | sanitize-beliefs | consolidate | audit",
        description="Деструктивный контур памяти: пересборка досье "
                    "(двухслойный пайплайн F1), санитария убеждений/фактов, "
                    "консолидация убеждений в парадигмы и READ-ONLY аудит. "
                    "Только сгенерированные производные; сырая история "
                    "неприкосновенна; авто-бэкап + JSONL-архив до DELETE; "
                    "без авто-кронов.")
    mem_sub = mem.add_subparsers(dest="memory_command",
                                 metavar="<подкоманда>")
    mem_sub.required = True

    def _add_memory_common(sp, *, with_scope: bool) -> None:
        sp.add_argument("--db", default=None,
                        help=f"путь SQLite-БД (дефолт: {settings.DB_PATH})")
        sp.add_argument("--limit", type=int, default=500,
                        help="потолок строк bounded-выборки (дефолт 500)")
        sp.add_argument("--batch", type=int, default=2000,
                        help="строк на пачку архива/удаления (дефолт 2000)")
        sp.add_argument("--backup-dir", default=None,
                        help="каталог авто-бэкапа/JSONL-архива "
                             "(дефолт: MEMORY_BACKUP_DIR)")
        sp.add_argument("--dry-run", action="store_true",
                        help="опциональная диагностика: ничего не пишет и не "
                             "удаляет (дефолт — боевой прогон)")
        if with_scope:
            sp.add_argument("--chat", type=int, action="append", default=None,
                            help="чат явно (можно несколько раз); целевой "
                                 f"чат {LEGACY_TARGET_CHAT_ID} требует "
                                 "--allow-target-chat")
            sp.add_argument("--all", action="store_true",
                            help="все чаты БЕЗ целевого (он исключён)")
            sp.add_argument("--allow-target-chat", action="store_true",
                            help="разрешить явный целевой чат в --chat")

    rb = mem_sub.add_parser(
        "rebuild-dossiers",
        help="сброс старых chat_meme + пересборка досье (пайплайн F1)",
        description="Боевая пересборка досье: сброс сгенерированных мемов "
                    "(chat_meme) и повторный прогон двухслойного пайплайна F1. "
                    "Сырая история и ручные persona_dossier_overrides "
                    "не трогаются (последние — только с --include-overrides).")
    _add_memory_common(rb, with_scope=True)
    rb.add_argument("--include-overrides", action="store_true",
                    help="ТАКЖЕ сбросить ручные persona_dossier_overrides "
                         "(по умолчанию НЕ трогаются)")
    # F1 round1022 (UPD3, Д-1/Д-3): операторский shortcut целевого чата;
    # равнозначен `--chat <target> --allow-target-chat`. `--all` целевой
    # по-прежнему исключает. Окно боевого прогона — 180 дней (4320 ч).
    rb.add_argument("--target-chat", action="store_true",
                    help=f"shortcut: целевой чат {LEGACY_TARGET_CHAT_ID} "
                         "(= --chat <id> --allow-target-chat)")
    rb.add_argument("--window-hours", type=int, default=4320,
                    help="окно пересборки, часов (дефолт 4320 = 180 дней); "
                         "0 = без ограничения по времени (в пределах --limit)")

    sb = mem_sub.add_parser(
        "sanitize-beliefs",
        help="санитария: факты без связей, убеждения, галлюцинации",
        description="Чистка ТОЛЬКО сгенерированных производных: факты без "
                    "инцидентных edges, невалидные убеждения (валидатор "
                    "count-agnostic), галлюцинации (source_ids/target вне "
                    "БД/ростера). Сырая история не читается и не мутуируется.")
    _add_memory_common(sb, with_scope=True)

    con = mem_sub.add_parser(
        "consolidate",
        help="консолидация убеждений в парадигмы (идемпотентно)",
        description="Memory Consolidation (F4): bounded-выборка убеждений "
                    "(belief_meta.type='belief'), ранжирование по опорам, "
                    "запись парадигм с дедупом. Повторный прогон — 0 записей. "
                    "CLI-only, авто-крона нет.")
    _add_memory_common(con, with_scope=False)
    con.add_argument("--chat", type=int, action="append", default=None,
                     help="чат(ы); без него — все чаты (целевой защищён)")
    con.add_argument("--all", action="store_true",
                     help="все чаты БЕЗ целевого (он исключён)")
    con.add_argument("--allow-target-chat", action="store_true",
                     help="разрешить явный целевой чат в --chat")
    con.add_argument("--min-sources", type=int, default=2,
                     help="мин. число опор (source_ids) для парадигмы (2)")

    aud = mem_sub.add_parser(
        "audit",
        help="READ-ONLY аудит причин пустого мета-слоя (F4/T-1972)",
        description="READ-ONLY: фактические флаги, счётчики memory_dream_log "
                    "по kind, число парадигм/убеждений, точка обрыва и ветвь "
                    "spec §3.3. Ничего не меняет.")
    aud.add_argument("--db", default=None,
                     help=f"путь SQLite-БД (дефолт: {settings.DB_PATH})")

    # ── F9 (10.24, ADR-1024-2): retention диска ─────────────────────
    disk = sub.add_parser(
        "disk",
        help="retention диска: audit (read-only) | cleanup (dry-run/--apply)",
        description="Аудит и очистка диска по политике владельца (UPD3 №5): "
                    "бэкапы БД — ровно 1; не-history JSONL — 6 мес; логи — "
                    "7 дней. Архивы истории сообщений (imported_history_"
                    "*.jsonl) НЕПРИКОСНОВЕННЫ. Удаление — только с --apply "
                    "(по умолчанию dry-run), с verify свежего бэкапа.")
    disk_sub = disk.add_subparsers(dest="disk_command", metavar="<подкоманда>")
    disk_sub.required = True
    d_aud = disk_sub.add_parser(
        "audit", help="READ-ONLY: категории/размеры/топ-файлы",
        description="Read-only снимок каталогов: категории (db_backup, "
                    "facts_export, jsonl_retention, immutable, other), "
                    "immutable_bytes, total_bytes, топ-10 по размеру. Ничего "
                    "не удаляет и не меняет.")
    d_aud.add_argument("--dir", action="append", default=None,
                       help="каталог для аудита (можно несколько; дефолт: "
                            f"{settings.MEMORY_BACKUP_DIR})")
    d_clean = disk_sub.add_parser(
        "cleanup", help="очистка: dry-run по умолчанию, --apply для удаления",
        description="Строит план (DB-бэкапы за пределами 1, facts за "
                    "пределами 1, не-history JSONL старше 180 дней) и — "
                    "только с --apply — удаляет, предварительно верифицировав "
                    "наличие валидного свежего бэкапа БД (fail-closed).")
    d_clean.add_argument("--apply", action="store_true",
                         help="выполнить удаление (без флага — dry-run)")
    d_clean.add_argument("--dir", action="append", default=None,
                         help="каталог очистки (можно несколько; дефолт: "
                              f"{settings.MEMORY_BACKUP_DIR})")

    # ── F10 (10.24, ADR-1024-11 D1): READ-ONLY диагностика алиасов ─────
    diag = sub.add_parser(
        "diag",
        help="READ-ONLY диагностика (aliases: global vs per-chat override)",
        description="Только SELECT: форма и число ключей global-значения "
                    "`limits.summary_aliases` (bot_settings), наличие/форма "
                    "per-chat override (chat_profiles.chat_params.overrides) "
                    "и форма ответа GET /api/config (value/global_value/"
                    "widget/chat_source). Значения НЕ выводятся (R17 — только "
                    "форма и число ключей); restore из бэкапа запрещён.")
    diag_sub = diag.add_subparsers(dest="diag_command", metavar="<подкоманда>")
    diag_sub.required = True
    d_alias = diag_sub.add_parser(
        "aliases", help="READ-ONLY: global/override/API-форма алиасов",
        description="Фиксирует «есть данные / нет данных» и форму для "
                    "`limits.summary_aliases` без единой записи в БД.")
    d_alias.add_argument("--chat-id", type=int, action="append", default=None,
                         help="целевой chat_id для проверки per-chat override "
                              "(можно несколько раз)")
    return parser


def _retention_dry_run(args) -> bool:
    """UPD4 п.3: dry-run, если явно запрошен `--dry-run`/alias `retention-dry-run`
    или не передан `--apply`. `--apply --dry-run` → dry-run (безопасный приоритет)."""
    return (not getattr(args, "apply", False)
            or bool(getattr(args, "dry_run", False))
            or getattr(args, "command", "") == "retention-dry-run")


def _make_db_snapshot(db_path) -> Path:
    """CLI retention (T-1910a, ADR-1020-5 п.6): временный СНАПШОТ SQLite для
    работы при ЖИВОМ боте. Backup API читает согласованный снимок (включая
    несохранённые в WAL данные) в отдельный файл — живой процесс не
    блокируется, «database is locked» не возникает.

    Вызывающий обязан удалить снапшот через `_drop_snapshot`."""
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    fd, name = tempfile.mkstemp(prefix="retention_snap_", suffix=".db")
    os.close(fd)
    dest = Path(name)
    source = sqlite3.connect(str(src), timeout=30)
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dest


def _drop_snapshot(path: Path | None) -> None:
    """Удалить временный снапшот и его WAL/SHM-файлы (best-effort)."""
    if path is None:
        return
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink(missing_ok=True)
        except OSError:
            pass


def _cmd_retention(args) -> int:
    """F7 (D-2/UPD4 п.3): `python manage.py retention [--dry-run|--apply]`.

    10.20 (T-1910a, ADR-1020-5 п.6): dry-run работает по ВРЕМЕННОМУ СНАПШОТУ
    БД (backup API) — утилита не падает при живом боте и не блокирует его;
    `--apply` открывает живую БД БЕЗ DDL/миграций (`initialize_existing`,
    WAL/busy_timeout). R17: в выводе нет путей/значений секретов."""
    from services.database import DatabaseService
    from services.memory_maintenance import run_import_retention

    dry_run = _retention_dry_run(args)
    db_path = Path(getattr(args, "db", None) or settings.DB_PATH)
    snapshot: Path | None = None

    async def _run(source_path: Path, *, existing: bool) -> dict:
        db = DatabaseService(str(source_path))
        if existing:
            await db.initialize_existing()
        else:
            await db.initialize()
        try:
            return await run_import_retention(
                db, dry_run=dry_run,
                archive_dir=getattr(args, "archive_dir", None),
                batch=int(getattr(args, "batch", 2000) or 2000))
        finally:
            try:
                await db.close()
            except Exception:
                pass

    if dry_run:
        try:
            snapshot = _make_db_snapshot(db_path)
        except Exception as exc:
            logging.warning("[retention] snapshot failed — fail safe | "
                            "reason=%s", type(exc).__name__)
            print("retention: mode=dry-run reason=snapshot_failed")
            return 1
        try:
            report = asyncio.run(_run(snapshot, existing=False))
        finally:
            _drop_snapshot(snapshot)
    else:
        report = asyncio.run(_run(db_path, existing=True))

    print(f"retention: mode={'dry-run' if dry_run else 'APPLY'} "
          f"reason={report.get('reason')} chats={report.get('chats')} "
          f"candidates={report.get('candidates')} "
          f"archived={report.get('archived')} deleted={report.get('deleted')} "
          f"batches={report.get('batches')} "
          f"archive={'yes' if report.get('archive') else 'no'}")
    return 0


def _cmd_disk(args) -> int:
    """F9 (10.24, ADR-1024-2): `python manage.py disk audit|cleanup`.

    R17/R18: вывод содержит только имена файлов, размеры и счётчики — без
    содержимого, полных секретов и ключей. `cleanup` по умолчанию dry-run;
    удаление — только с `--apply` (fail-closed verify свежего бэкапа БД)."""
    from services import disk_retention as dr

    dirs = getattr(args, "dir", None) or dr.default_dirs()
    command = args.disk_command

    if command == "audit":
        report = dr.audit(dirs)
        print("disk audit (READ-ONLY)")
        for entry in report["dirs"]:
            print(f"  dir: {entry}")
        for category, bucket in sorted(report["categories"].items()):
            print(f"  {category}: count={bucket['count']} "
                  f"bytes={bucket['bytes']} ({dr.human_bytes(bucket['bytes'])})")
        print(f"  immutable_bytes={report['immutable_bytes']} "
              f"({dr.human_bytes(report['immutable_bytes'])})")
        print(f"  total_bytes={report['total_bytes']} "
              f"({dr.human_bytes(report['total_bytes'])})")
        print(f"  log_retention_days={report['log_retention_days']} "
              "(journald: docs/runbook-disk-retention.md)")
        for item in report["top_files"]:
            print(f"  top: {item['name']} bytes={item['bytes']} "
                  f"category={item['category']}")
        forecast = dr.forecast_monthly(dirs)
        print(f"  forecast: bytes_per_day={forecast['bytes_per_day']} "
              f"projected_30d={forecast['projected_30d']} "
              f"({dr.human_bytes(forecast['projected_30d'])}) "
              f"files={forecast['files']} "
              f"immutable_bytes={forecast['immutable_bytes']} "
              f"span_days={forecast['span_days']}")
        print(f"  forecast_method: {forecast['method']}")
        return 0

    plan = dr.plan_cleanup(dirs)
    total = sum(int(item.get("bytes") or 0) for item in plan)
    if not getattr(args, "apply", False):
        print(f"disk cleanup: DRY-RUN candidates={len(plan)} "
              f"bytes={total} ({dr.human_bytes(total)})")
        for item in plan:
            print(f"  would-delete: {Path(item['path']).name} "
                  f"category={item['category']} reason={item['reason']} "
                  f"bytes={item['bytes']}")
        print("  (удаление не выполнялось; добавьте --apply)")
        return 0

    result = dr.apply_cleanup(plan, verify=True, dirs=dirs)
    if result.get("aborted_reason"):
        print(f"disk cleanup: ABORTED reason={result['aborted_reason']} "
              "(нет валидного свежего бэкапа БД — fail-closed)")
        return 1
    print(f"disk cleanup: APPLY deleted={result['deleted']} "
          f"bytes_freed={result['bytes_freed']} "
          f"({dr.human_bytes(result['bytes_freed'])}) "
          f"skipped={result['skipped']} errors={result['errors']}")
    for category, bucket in sorted(result["categories"].items()):
        print(f"  {category}: count={bucket['count']} bytes={bucket['bytes']}")
    return 0


def _seed_usable(seed_path) -> bool:
    """Сид прочитан и содержит хотя бы один чат (fail-loud для CLI).

    `load_chat_settings_seed` fail-open возвращает `{}` при отсутствующем/
    битом файле — это НЕ «нечего делать», а неисправность ремонта."""
    from services.chat_settings_seed import load_chat_settings_seed
    try:
        seed = load_chat_settings_seed(seed_path)
    except Exception:
        return False
    return bool(isinstance(seed, dict) and (seed.get("chats") or []))


def _cmd_apply_chat_overrides(args) -> int:
    """F3 (10.19) + F22 (10.24, ADR-1024-23 D4): `python manage.py
    apply-chat-overrides [--force]` — идемпотентный сид.

    F22: (1) `await pg.connect()` **до** `pg.init(seed_settings=False)`;
    (2) fail-loud при недоступной PG, битом/пустом сиде и реальных ошибках —
    выход с ненулевым кодом. Иначе CLI печатал `applied=0 skipped=0 errors=0`
    и притворялся успешным (тихий no-op, ремонт данных не выполнялся)."""
    from services.pg_db import PgDatabase
    from services.chat_settings_seed import apply_chat_settings_seed

    seed_path = getattr(args, "seed", None)
    if not _seed_usable(seed_path):
        print("apply-chat-overrides: сид chat_settings_seed.json нечитаем или "
              "пуст — ремонт не выполнен", file=sys.stderr)
        return 1

    async def _run() -> dict | None:
        pg = PgDatabase()
        try:
            await pg.connect()
        except Exception as exc:
            print(f"apply-chat-overrides: не удалось подключиться к "
                  f"PostgreSQL ({type(exc).__name__}) — ремонт не выполнен",
                  file=sys.stderr)
            return None
        if pg.pool is None:
            print("apply-chat-overrides: PostgreSQL недоступен (POSTGRES_DSN "
                  "пуст или пул не создан) — ремонт не выполнен",
                  file=sys.stderr)
            return None
        try:
            # Спека §3.2.1/§5.1 + ADR D4: connect ДО init (init при отсутствии
            # пула молча скипал DDL — первопричина тихого no-op).
            await pg.init(seed_settings=False)
        except Exception as exc:
            print(f"apply-chat-overrides: не удалось применить схему "
                  f"({type(exc).__name__}) — ремонт не выполнен",
                  file=sys.stderr)
            await _safe_close(pg)
            return None
        try:
            return await apply_chat_settings_seed(pg, force=bool(getattr(
                args, "force", False)))
        finally:
            await _safe_close(pg)

    report = asyncio.run(_run())
    if report is None:
        return 1
    print(f"apply-chat-overrides: applied={len(report['applied'])} "
          f"skipped={len(report['skipped'])} errors={len(report['errors'])}")
    for chat_id, keys in report["applied"]:
        print(f"  chat {chat_id}: {', '.join(keys)}")
    if report["errors"]:
        print(f"apply-chat-overrides: ошибки применения на "
              f"{len(report['errors'])} чат(ах) — ремонт НЕ полный",
              file=sys.stderr)
        return 1
    return 0


# ═══ F22 (раунд 10.24, ADR-1024-23 D5/D7): read-only аудит overrides ═════════
# Только SELECT (без set_chat_params/NOTIFY/history). R17/R18: в stdout/JSONL
# попадают лишь имена ключей, числа-значения лимитов (0/-1) и
# `{configured,last4}`; сырые `key_value`/секреты/полные JSON-дампы `old_value`
# и `new_value` НЕ выводятся. JSONL — в gitignored `var/audit/`.

_AUDIT_PROFILE_SQL = (
    "SELECT chat_id, updated_at, chat_params FROM chat_profiles "
    "WHERE chat_id = $1")
_AUDIT_HISTORY_SQL = (
    "SELECT id, created_at, changed_by, old_value, new_value "
    "FROM chat_lore_history WHERE chat_id = $1 AND field = 'chat_params' "
    "ORDER BY created_at DESC, id DESC LIMIT $2")
_AUDIT_KEYS_SQL = (
    "SELECT key_name, key_value FROM chat_keys WHERE chat_id = $1")
_AUDIT_USAGE_SQL = (
    "SELECT metric, used, day FROM chat_usage WHERE chat_id = $1 "
    "ORDER BY day DESC LIMIT 30")
_AUDIT_WORKER_SQL = (
    "SELECT day, scope, metric, used FROM worker_budget WHERE scope = $1 "
    "ORDER BY day DESC LIMIT 30")
_AUDIT_SETTINGS_SQL = (
    "SELECT key, value FROM bot_settings WHERE key = ANY($1::text[])")

# Ось «усечение контекста direct-контура» (F22 фиксирует границу с master-
# тумблером бюджетов F21 `flags.budgets_enabled`; F22 флаги НЕ пишет).
_CONTEXT_BUDGET_FLAG = "flags.chat_context_budgets_enabled"


def _iso_any(value):
    """JSON-safe строка из datetime/строки/None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_dict(row) -> dict:
    """asyncpg.Record | dict | None → dict (без падений)."""
    if row is None:
        return {}
    try:
        return dict(row)
    except Exception:
        return {}


def _load_params(value) -> dict:
    """JSONB chat_params → dict (мусор/строка → {})."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def _safe_close(pg) -> None:
    try:
        await pg.close()
    except Exception:
        pass


def _load_seed_ref(chat_id: int, seed_path) -> tuple[dict, int, bool]:
    """`(эталон overrides чата, version сида, seed_ok)`.

    `seed_ok=False` — сид нечитаем/битый/пуст (fail-loud: аудит без эталона
    недостоверен). Generic-обход: chat_id берётся из данных сида."""
    from services.chat_settings_seed import load_chat_settings_seed
    seed = load_chat_settings_seed(seed_path)
    seed_ok = bool(isinstance(seed, dict) and (seed.get("chats") or []))
    try:
        version = int(seed.get("version", 0) or 0)
    except (TypeError, ValueError):
        version = 0
    reference: dict = {}
    for entry in seed.get("chats") or []:
        try:
            if int(entry["chat_id"]) == int(chat_id):
                reference = dict(entry.get("overrides") or {})
                break
        except (KeyError, TypeError, ValueError):
            continue
    return reference, version, seed_ok


def _values_equal(key: str, current, expected) -> bool:
    """Сравнение значения с эталоном с учётом типа каталога (мусор → False)."""
    if current == expected:
        return True
    try:
        from services.param_catalog import normalize_value
        return normalize_value(key, current) == normalize_value(key, expected)
    except Exception:
        return False


def _classify_overrides(overrides: dict, reference: dict) -> list[dict]:
    """Классификация seed-ключей: `ok | absent | different` (R17-safe).

    Выводится только **эталонное** seed-значение (`seed_value`, числа 0/-1) —
    фактическое значение override (может быть произвольной строкой) в вывод
    не попадает (R17/R18)."""
    out = []
    for key, expected in reference.items():
        if key not in overrides:
            status = "absent"
        elif _values_equal(key, overrides[key], expected):
            status = "ok"
        else:
            status = "different"
        out.append({"key": key, "status": status, "seed_value": expected})
    return out


def _parse_overrides_blob(text) -> tuple[set, object]:
    """`(набор ключей overrides, seed_version|None)` из TEXT old/new_value.

    Значение — свободный TEXT; не-JSON/мусор → пустой набор (не падаем)."""
    if text is None:
        return set(), None
    if isinstance(text, (bytes, bytearray)):
        try:
            text = text.decode("utf-8", "replace")
        except Exception:
            return set(), None
    if not isinstance(text, str):
        return set(), None
    try:
        parsed = json.loads(text)
    except Exception:
        return set(), None
    if not isinstance(parsed, dict):
        return set(), None
    overrides = parsed.get("overrides")
    keys = set(overrides) if isinstance(overrides, dict) else set()
    version = None
    meta = parsed.get("meta")
    if isinstance(meta, dict):
        raw = meta.get("chat_settings_seed_version")
        if raw is not None:
            try:
                version = int(raw)
            except (TypeError, ValueError):
                version = None
    return keys, version


def _timeline_entry(row: dict, seed_keys: set) -> dict:
    """R17-safe строка таймлайна `chat_params`: только наборы ключей/числа.

    `wipe_suspected` — уменьшение числа seed-ключей в `overrides` (детектор
    вайпа: merge-баг стирал namespace целиком)."""
    old_keys, old_ver = _parse_overrides_blob(row.get("old_value"))
    new_keys, new_ver = _parse_overrides_blob(row.get("new_value"))
    seed_old = len(seed_keys & old_keys)
    seed_new = len(seed_keys & new_keys)
    return {
        "id": row.get("id"),
        "created_at": _iso_any(row.get("created_at")),
        "changed_by": row.get("changed_by"),
        "added": sorted(new_keys - old_keys),
        "dropped": sorted(old_keys - new_keys),
        "seed_version_old": old_ver,
        "seed_version_new": new_ver,
        "seed_keys_old": seed_old,
        "seed_keys_new": seed_new,
        "wipe_suspected": seed_new < seed_old,
    }


def _resolve_context_flag(overrides: dict, global_values: dict) -> dict:
    """Резолв `flags.chat_context_budgets_enabled`: chat → global → default.

    F22 review iter1: `worker_settings.resolve_setting_with_source` в CLI не
    работает — chat-слой читается из процесс-глобала `ChatParamsCache`, который
    выставляется только `bot.py`. Здесь резолвим из уже вычитанных данных PG
    (source `'chat'`/`'global'`/`'default'`)."""
    from config.settings import settings
    from services.param_catalog import get_by_pg_key, normalize_value
    spec = get_by_pg_key(_CONTEXT_BUDGET_FLAG)
    default = None
    if spec is not None and getattr(spec, "settings_field", None):
        default = getattr(settings, spec.settings_field, None)
    if default is None:
        default = getattr(settings, "CHAT_CONTEXT_BUDGETS_ENABLED", None)
    if _CONTEXT_BUDGET_FLAG in overrides:
        return {"value": normalize_value(_CONTEXT_BUDGET_FLAG,
                                         overrides[_CONTEXT_BUDGET_FLAG]),
                "source": "chat"}
    if _CONTEXT_BUDGET_FLAG in global_values:
        return {"value": global_values[_CONTEXT_BUDGET_FLAG],
                "source": "global"}
    return {"value": default, "source": "default"}


async def _collect_chat_overrides_audit(pg, *, chat_id: int, seed_path=None,
                                        history_limit: int = 200) -> dict:
    """Read-only сбор аудита (§3.3). Все запросы — только `SELECT`.

    Возвращает R17-safe сводку; `wipe_detected` — найден ли вайп в истории."""
    reference, seed_version, seed_ok = _load_seed_ref(chat_id, seed_path)
    seed_keys = set(reference)
    report: dict = {
        "chat_id": int(chat_id),
        "seed_ok": seed_ok,
        "seed_version_expected": seed_version,
        "reference_keys": sorted(seed_keys),
        "profile": False,
        "updated_at": None,
        "classification": [],
        "seed_meta_version": None,
        "allow_global_present": False,
        "timeline": [],
        "wipe_detected": False,
        "chat_keys": [],
        "chat_usage": [],
        "worker_budget": [],
        "global_limits": {},
        "context_flag": {"value": None, "source": None},
        "warnings": [],
    }
    pool = getattr(pg, "pool", None)
    if pool is None:
        raise RuntimeError("PostgreSQL недоступен (пул отсутствует)")
    async with pool.acquire() as conn:
        profile_row = _as_dict(await conn.fetchrow(
            _AUDIT_PROFILE_SQL, int(chat_id)))
        chat_params = _load_params(profile_row.get("chat_params"))
        overrides = dict(chat_params.get("overrides") or {})
        meta = dict(chat_params.get("meta") or {})
        keys_ns = dict(chat_params.get("keys") or {})
        report["profile"] = bool(profile_row)
        report["updated_at"] = _iso_any(profile_row.get("updated_at"))
        report["classification"] = _classify_overrides(overrides, reference)
        raw_ver = meta.get("chat_settings_seed_version")
        if raw_ver is not None:
            try:
                report["seed_meta_version"] = int(raw_ver)
            except (TypeError, ValueError):
                report["seed_meta_version"] = None
        report["allow_global_present"] = "allow_global" in keys_ns

        hist_rows = await conn.fetch(_AUDIT_HISTORY_SQL, int(chat_id),
                                     int(history_limit))
        for item in hist_rows or []:
            report["timeline"].append(
                _timeline_entry(_as_dict(item), seed_keys))
        report["wipe_detected"] = any(
            entry["wipe_suspected"] for entry in report["timeline"])

        # chat_keys — ТОЛЬКО маска {configured,last4} (сырое значение не выводим).
        try:
            from services.chat_keys import mask_key_info
            rows = await conn.fetch(_AUDIT_KEYS_SQL, int(chat_id))
            for item in rows or []:
                raw = _as_dict(item)
                mask = mask_key_info(raw.get("key_name"), raw.get("key_value"))
                report["chat_keys"].append({
                    "key_name": mask["key_name"],
                    "configured": mask["configured"],
                    "last4": mask["last4"]})
        except Exception:
            report["warnings"].append("chat_keys")

        # Счётчики — только числа.
        try:
            rows = await conn.fetch(_AUDIT_USAGE_SQL, int(chat_id))
            for item in rows or []:
                raw = _as_dict(item)
                report["chat_usage"].append({
                    "metric": raw.get("metric"),
                    "used": int(raw.get("used") or 0),
                    "day": _iso_any(raw.get("day"))})
        except Exception:
            report["warnings"].append("chat_usage")
        try:
            rows = await conn.fetch(_AUDIT_WORKER_SQL,
                                    f"chat:{int(chat_id)}")
            for item in rows or []:
                raw = _as_dict(item)
                report["worker_budget"].append({
                    "day": _iso_any(raw.get("day")),
                    "scope": raw.get("scope"),
                    "metric": raw.get("metric"),
                    "used": int(raw.get("used") or 0)})
        except Exception:
            report["warnings"].append("worker_budget")
        # Глобальный слой: 8 limit-ключей + флаг контекста — только числа.
        setting_keys = sorted(set(seed_keys) | {_CONTEXT_BUDGET_FLAG})
        global_values: dict = {}
        try:
            from services.param_catalog import normalize_value
            rows = await conn.fetch(_AUDIT_SETTINGS_SQL, setting_keys)
            for item in rows or []:
                raw = _as_dict(item)
                key = raw.get("key")
                global_values[key] = normalize_value(key, raw.get("value"))
        except Exception:
            report["warnings"].append("bot_settings")
        report["global_limits"] = {
            key: value for key, value in global_values.items()
            if key in seed_keys}

    # Ось контекста (граница с master-тумблером F21) — резолв из данных PG
    # (без bot-only глобала `ChatParamsCache`, недоступного в CLI).
    report["context_flag"] = _resolve_context_flag(overrides, global_values)
    return report


def _audit_drift(report: dict) -> bool:
    """Дрейф = не все seed-ключи `ok`, вайп в истории, нечитаемый эталон или
    неполный аудит (отказ отдельной секции). Под `--strict` → non-zero."""
    if not report.get("seed_ok", True):
        return True
    if report.get("wipe_detected"):
        return True
    if report.get("warnings"):
        return True
    return any(item.get("status") != "ok"
               for item in report.get("classification") or [])


def _write_audit_jsonl(path: Path, report: dict) -> None:
    """Записать R17-safe JSONL (по строке на запись; без сырых JSON-дампов)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[dict] = []
    summary = {k: v for k, v in report.items()
               if k not in ("timeline", "chat_keys", "chat_usage",
                            "worker_budget", "global_limits", "context_flag")}
    summary["type"] = "summary"
    lines.append(summary)
    for entry in report.get("timeline") or []:
        lines.append({"type": "timeline", **entry})
    for mask in report.get("chat_keys") or []:
        lines.append({"type": "chat_key", **mask})
    for usage in report.get("chat_usage") or []:
        lines.append({"type": "chat_usage", **usage})
    for wb in report.get("worker_budget") or []:
        lines.append({"type": "worker_budget", **wb})
    for key, value in (report.get("global_limits") or {}).items():
        lines.append({"type": "global_limit", "key": key, "value": value})
    lines.append({"type": "context_flag", **(report.get("context_flag") or {})})
    with open(path, "w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def _cmd_audit_chat_overrides(args) -> int:
    """F22 (ADR-1024-23 D5): `python manage.py audit-chat-overrides` — READ-ONLY.

    Только `SELECT`; ничего не пишет в БД. `--strict` — non-zero при дрейфе."""
    from services.pg_db import PgDatabase

    chat_id = int(args.chat_id)
    seed_path = getattr(args, "seed", None)

    async def _run() -> dict | None:
        pg = PgDatabase()
        try:
            await pg.connect()
        except Exception as exc:
            print(f"audit-chat-overrides: не удалось подключиться к "
                  f"PostgreSQL ({type(exc).__name__}) — аудит не выполнен",
                  file=sys.stderr)
            return None
        if pg.pool is None:
            print("audit-chat-overrides: PostgreSQL недоступен (POSTGRES_DSN "
                  "пуст или пул не создан) — аудит не выполнен",
                  file=sys.stderr)
            await _safe_close(pg)
            return None
        try:
            return await _collect_chat_overrides_audit(
                pg, chat_id=chat_id, seed_path=seed_path,
                history_limit=int(getattr(args, "history_limit", 200) or 200))
        finally:
            await _safe_close(pg)

    try:
        report = asyncio.run(_run())
    except Exception as exc:
        print(f"audit-chat-overrides: ошибка аудита ({type(exc).__name__}) — "
              f"данные не изменялись", file=sys.stderr)
        return 1
    if not report:
        return 1
    seed_unusable = not report.get("seed_ok", True)

    counts = {"ok": 0, "absent": 0, "different": 0}
    for item in report["classification"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(f"audit-chat-overrides: chat={report['chat_id']} "
          f"profile={'yes' if report['profile'] else 'no'} "
          f"seed_version={report['seed_meta_version']} "
          f"reference_keys={len(report['reference_keys'])} "
          f"ok={counts['ok']} absent={counts['absent']} "
          f"different={counts['different']} "
          f"allow_global_present={report['allow_global_present']} "
          f"updated_at={report['updated_at']}")
    for item in report["classification"]:
        # R17: печатаем только эталонное seed-значение (не текущий override)
        seed_val = item.get("seed_value")
        suffix = "" if seed_val is None else f" seed={seed_val}"
        print(f"  [{item['status']}] {item['key']}{suffix}")
    print(f"  timeline: rows={len(report['timeline'])} "
          f"wipe_suspected={'yes' if report['wipe_detected'] else 'no'}")
    for entry in report["timeline"]:
        print(f"    id={entry['id']} at={entry['created_at']} "
              f"by={entry['changed_by']} added={len(entry['added'])} "
              f"dropped={len(entry['dropped'])} "
              f"seed_keys={entry['seed_keys_old']}->{entry['seed_keys_new']} "
              f"wipe={'yes' if entry['wipe_suspected'] else 'no'}")
    for mask in report["chat_keys"]:
        print(f"  chat_key {mask['key_name']}: configured="
              f"{mask['configured']} last4={mask['last4']}")
    flag = report["context_flag"]
    print(f"  {_CONTEXT_BUDGET_FLAG}: value={flag['value']} "
          f"source={flag['source']}")
    if report["warnings"]:
        print(f"  warnings: {','.join(report['warnings'])}")

    jsonl_arg = getattr(args, "jsonl", None)
    if jsonl_arg:
        jsonl_path = Path(jsonl_arg)
    else:
        stamp = datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        jsonl_path = (Path("var") / "audit"
                      / f"chat_overrides_{report['chat_id']}_{stamp}.jsonl")
    try:
        _write_audit_jsonl(jsonl_path, report)
        print(f"  jsonl: {jsonl_path}")
    except OSError as exc:
        print(f"audit-chat-overrides: не удалось записать JSONL "
              f"({type(exc).__name__}) — БД не изменена", file=sys.stderr)
        return 1
    if seed_unusable:
        print("audit-chat-overrides: сид-эталон нечитаем/пуст — аудит "
              "недостоверен (это НЕ «всё ок»)", file=sys.stderr)
        return 1
    return 1 if (_audit_drift(report)
                 and bool(getattr(args, "strict", False))) else 0


def _memory_scope(args, available: list, *, required: bool) -> list:
    """F5/§3: охват чатов CLI `memory`.

    `--all` НИКОГДА не включает целевой чат; для него нужен явный `--chat` +
    `--allow-target-chat`. `required=True` (rebuild/sanitize) — без охвата
    отказ (защита от «случайно всё»); `required=False` (consolidate) — все
    чаты без целевого."""
    target = LEGACY_TARGET_CHAT_ID
    explicit = [int(c) for c in (getattr(args, "chat", None) or [])]
    allow = bool(getattr(args, "allow_target_chat", False))
    # F1 round1022: явный shortcut `--target-chat` равнозначен
    # `--chat <target> --allow-target-chat`; он НЕ делает целевой чат
    # доступным через `--all`.
    if bool(getattr(args, "target_chat", False)):
        return [target]
    if explicit:
        if target in explicit and not allow:
            raise SystemExit(
                f"целевой чат {target} защищён: нужен явный --chat {target} "
                f"+ --allow-target-chat")
        return explicit
    if getattr(args, "all", False):
        return [int(c) for c in available if int(c) != target]
    if required:
        raise SystemExit(
            "укажите охват: --chat <id> (можно несколько раз) или --all")
    return [int(c) for c in available if int(c) != target]


def _build_rebuild_pipeline(db, args):
    """F5/§4.1: боевой pipeline пересборки досье — двухслойный пайплайн F1
    поверх окна `smart_messages` (SQLite-ЧТЕНИЕ, инвариант §3.1.1)."""
    from services.llm_client import LLMClient
    from services.lore_worker import LoreWorker

    llm = LLMClient(
        settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL_NAME,
        settings.EMBEDDING_MODEL_NAME,
        embed_base_url=settings.EMBEDDING_BASE_URL,
        embed_api_key=settings.EMBEDDING_API_KEY)
    worker = LoreWorker(None, cache=None, db=db, llm=llm)
    default_window_hours = int(getattr(args, "window_hours", 4320) or 0)
    limit = int(getattr(args, "limit", 0) or 0)

    async def _pipeline(chat_id: int, window_hours: int | None = None) -> int:
        # F1 round1022: rebuild_dossiers передаёт effective_window (R1b);
        # fallback — значение CLI (0 = без ограничения по времени).
        eff = (default_window_hours if window_hours is None
               else int(window_hours))
        return await worker.rebuild_dossier_for_chat(
            chat_id, window_hours=int(eff or 0), limit=limit or None)
    return _pipeline


async def _open_memory_db(db_path: Path, *, readonly: bool = False):
    """F5: живая БД без DDL (`initialize_existing`), свежая — `initialize`.

    S10.21-6: `readonly=True` (команда `audit`) открывает существующий файл
    строго в режиме `mode=ro` — без DDL/миграций/WAL; отсутствие файла —
    явная ошибка, схема НЕ создаётся."""
    from services.database import DatabaseService

    if readonly:
        db = DatabaseService(str(db_path))
        await db.initialize_readonly()
        return db
    if db_path.exists():
        db = DatabaseService(str(db_path))
        try:
            await db.initialize_existing()
            return db
        except Exception:
            try:
                await db.close()
            except Exception:
                pass
    db = DatabaseService(str(db_path))
    await db.initialize()
    return db


def _print_memory_report(command: str, report: dict) -> None:
    """R17-safe вывод CLI: counts/классы/коды, без текстов и путей."""
    if command == "audit":
        print(f"memory audit: break_point={report.get('break_point')} "
              f"branch={report.get('branch')} "
              f"flags={report.get('flags')}")
        print(f"  paradigms_total={report.get('paradigms_total')} "
              f"by_chat={report.get('paradigms_by_chat')}")
        print(f"  dream_log={report.get('dream_log')} "
              f"last_run={report.get('last_run')}")
        print(f"  beliefs={report.get('beliefs_by_status')}")
        return
    mode = "dry-run" if report.get("dry_run") else "APPLY"
    if command == "consolidate":
        print(f"memory consolidate: mode={mode} chats={report.get('chats')} "
              f"scanned={report.get('scanned')} "
              f"candidates={report.get('candidates')} "
              f"written={report.get('written')} "
              f"max_paradigms={report.get('max_paradigms')} "
              f"skipped={report.get('skipped')} "
              f"archived={report.get('archived')} "
              f"reasons={report.get('reasons')} "
              f"backup={'yes' if report.get('backup') else 'no'}")
        return
    if command == "rebuild-dossiers":
        # F1 round1022 (UPD3): R17-safe отчёт — только числа/коды.
        print(f"memory rebuild-dossiers: mode={mode} "
              f"chats={report.get('chats')} scanned={report.get('scanned')} "
              f"reset={report.get('reset')} "
              f"reset_portraits={report.get('reset_portraits')} "
              f"confirmed_candidates={report.get('confirmed_candidates')} "
              f"cleaned_facts={report.get('cleaned_facts')} "
              f"protected_belief_sources="
              f"{report.get('protected_belief_sources')} "
              f"rebuilt={report.get('rebuilt')} "
              f"skipped={report.get('skipped')} "
              f"window_hours_used={report.get('window_hours_used')} "
              f"source_age_days={report.get('source_age_days')} "
              f"max_msgs={report.get('max_msgs')} "
              f"reasons={report.get('reasons')} "
              f"backup={'yes' if report.get('backup') else 'no'}")
        return
    print(f"memory sanitize-beliefs: mode={mode} chats={report.get('chats')} "
          f"scanned={report.get('scanned')} "
          f"candidates={report.get('candidates')} "
          f"archived={report.get('archived')} deleted={report.get('deleted')} "
          f"roster_size={report.get('roster_size')} "
          f"classes={report.get('classes')} reasons={report.get('reasons')} "
          f"backup={'yes' if report.get('backup') else 'no'}")


def _memory_exit_code(command: str, report: dict) -> int:
    """F1 round1022: ненулевой exit, если что-то сброшено, но не пересобрано
    (`rebuild_empty`, R1b/ADR-1022-1 §5). Молчаливый «успех» запрещён."""
    if command == "rebuild-dossiers":
        reasons = report.get("reasons") or {}
        if reasons.get("rebuild_empty"):
            return 1
    return 0


def _acquire_memory_locks(chats, *, jobs_dir=None):
    """R6/spec §2.7 (F8): CLI F1 берёт тот же кросс-процессный per-chat
    file-lock, что и UI-джоба (`services/dossier_rebuild_jobs`). Иначе
    одновременный CLI-прогон и UI-пересборка одного чата конкурировали бы.

    Возвращает `(handles, busy_chat)`: при занятом локе `handles` пуст, а
    `busy_chat` — id первого занятого чата (R17: без путей/имён)."""
    from services import dossier_rebuild_jobs as drj

    directory = jobs_dir if jobs_dir is not None else drj.jobs_dir()
    handles = []
    for chat_id in chats:
        lock = drj.acquire_chat_lock(directory, int(chat_id))
        if lock is None:
            _release_memory_locks(handles)
            return [], int(chat_id)
        handles.append(lock)
    return handles, None


def _release_memory_locks(locks) -> None:
    """Best-effort освобождение CLI-lock'ов (идемпотентно)."""
    for lock in locks or []:
        try:
            lock.release()
        except Exception:
            pass


def _cmd_memory(args) -> int:
    """F4/F5 (ADR-1021-4/5): `python manage.py memory <подкоманда>`.

    Дефолт — боевой прогон; `--dry-run` — опциональная диагностика.
    Схема БД не меняется; авто-кронов/HTTP-триггеров нет.

    F8/R6: `rebuild-dossiers`/`sanitize-beliefs` берут per-chat file-lock
    `services/dossier_rebuild_jobs` — тот же, что UI-джоба; занят → exit 1
    с кодом `chat_locked`."""
    from services import memory_maintenance as mm
    from services import memory_rebuild as mr

    command = args.memory_command
    db_path = Path(getattr(args, "db", None) or settings.DB_PATH)
    outcome = {"locked_chat": None}

    async def _run_memory_engine(db, chats) -> dict:
        if command == "rebuild-dossiers":
            pipeline = None
            if not args.dry_run:
                pipeline = _build_rebuild_pipeline(db, args)
            return await mr.rebuild_dossiers(
                db, chat_ids=chats, dry_run=bool(args.dry_run),
                include_overrides=bool(args.include_overrides),
                limit=int(args.limit), pipeline=pipeline,
                db_path=str(db_path), backup_dir=args.backup_dir,
                window_hours=int(args.window_hours),
                batch=int(args.batch))
        return await mr.sanitize_beliefs(
            db, chat_ids=chats, dry_run=bool(args.dry_run),
            limit=int(args.limit), db_path=str(db_path),
            backup_dir=args.backup_dir, batch=int(args.batch))

    async def _run() -> dict:
        # S10.21-6: `audit` — строго read-only (без DDL/WAL/создания файла).
        db = await _open_memory_db(db_path, readonly=(command == "audit"))
        try:
            if command == "audit":
                return await mm.collect_paradigm_audit(db)
            available = await db.get_graph_chat_ids()
            if command == "consolidate":
                chats = _memory_scope(args, available, required=False)
                return await mm.consolidate(
                    db, chat_ids=chats, dry_run=bool(args.dry_run),
                    limit=int(args.limit), min_sources=int(args.min_sources),
                    db_path=str(db_path), backup_dir=args.backup_dir)
            chats = _memory_scope(args, available, required=True)
            if command in ("rebuild-dossiers", "sanitize-beliefs"):
                locks, busy_chat = _acquire_memory_locks(chats)
                if busy_chat is not None:
                    outcome["locked_chat"] = busy_chat
                    return None
                try:
                    return await _run_memory_engine(db, chats)
                finally:
                    _release_memory_locks(locks)
            return await _run_memory_engine(db, chats)
        finally:
            try:
                await db.close()
            except Exception:
                pass

    try:
        report = asyncio.run(_run())
    except (FileNotFoundError, RuntimeError):
        # S10.21-6: audit НЕ создаёт схему — при отсутствии файла/таблиц
        # сообщаем явно (R17: без пути) и выходим с ошибкой.
        if command == "audit":
            print("memory audit: error=db_unavailable — файл БД не найден "
                  "или схема отсутствует (ничего не создано)")
            return 1
        raise
    if outcome["locked_chat"] is not None:
        # R17-safe: только код и chat_id; путей/имён нет.
        print(f"memory {command}: error=chat_locked chat="
              f"{outcome['locked_chat']} — пересборку этого чата уже "
              f"выполняет CLI/UI, повторите позже")
        return 1
    _print_memory_report(command, report)
    return _memory_exit_code(command, report)


# ── F10 (10.24, ADR-1024-11 D1): READ-ONLY диагностика алиасов ──────────────
_ALIASES_PG_KEY = "limits.summary_aliases"
_ALIASES_SETTING_SQL = "SELECT key, value FROM bot_settings WHERE key = $1"
_ALIASES_PROFILE_SQL = (
    "SELECT chat_id, chat_params FROM chat_profiles WHERE chat_id = $1")


def _aliases_shape(value) -> dict:
    """R17-safe форма значения: тип/число ключей/двойное кодирование.

    Значения НЕ возвращаются — только форма (spec §3.1)."""
    from web.api.routes import _ensure_keyvalue_object
    encoded_as_string = isinstance(value, str)
    double_encoded = False
    if encoded_as_string:
        try:
            json.loads(value)
            double_encoded = True
        except ValueError:
            double_encoded = False
    effective = _ensure_keyvalue_object(value, pg_key=_ALIASES_PG_KEY)
    return {
        "raw_type": type(value).__name__,
        "encoded_as_string": encoded_as_string,
        "double_encoded": double_encoded,
        "effective_keys": len(effective),
    }


async def _collect_aliases_diag(pg, *, chat_ids=None) -> dict:
    """Read-only сбор фактов (только SELECT).

    global (bot_settings) + per-chat override (chat_profiles.chat_params) +
    API-эффект (widget/value/global_value/chat_source). Без значений (R17)."""
    from services.param_catalog import get_by_pg_key
    from web.api.routes import _ensure_keyvalue_object

    report: dict = {
        "key": _ALIASES_PG_KEY,
        "global": None,
        "global_present": False,
        "widget": "",
        "chats": [],
        "warnings": [],
    }
    pool = getattr(pg, "pool", None)
    if pool is None:
        raise RuntimeError("PostgreSQL недоступен (пул отсутствует)")

    spec = get_by_pg_key(_ALIASES_PG_KEY)
    report["widget"] = spec.widget if spec is not None else ""
    is_per_chat = bool(spec.per_chat) if spec is not None else False

    async with pool.acquire() as conn:
        row = _as_dict(await conn.fetchrow(_ALIASES_SETTING_SQL,
                                           _ALIASES_PG_KEY))
        global_value = row.get("value") if row else None
        report["global_present"] = bool(row)
        report["global"] = _aliases_shape(global_value)
        effective_global = _ensure_keyvalue_object(
            global_value, pg_key=_ALIASES_PG_KEY)

        for chat_id in (chat_ids or []):
            profile = _as_dict(await conn.fetchrow(_ALIASES_PROFILE_SQL,
                                                   int(chat_id)))
            root = _load_params(profile.get("chat_params"))
            overrides = dict(root.get("overrides") or {})
            override_present = _ALIASES_PG_KEY in overrides
            override_value = overrides.get(_ALIASES_PG_KEY)
            # Эффективное значение API: override (если per-chat) иначе global.
            if override_present and is_per_chat:
                effective = _ensure_keyvalue_object(
                    override_value, pg_key=_ALIASES_PG_KEY)
                chat_source = "chat"
                global_out = effective_global
            else:
                effective = effective_global
                chat_source = ""
                global_out = effective_global if override_present else None
            report["chats"].append({
                "chat_id": int(chat_id),
                "profile_present": bool(profile),
                "override_present": override_present,
                "override": (_aliases_shape(override_value)
                             if override_present else None),
                "api_value_keys": len(effective),
                "api_global_value_keys": (len(global_out)
                                          if isinstance(global_out, dict)
                                          else None),
                "api_chat_source": chat_source,
            })
    return report


def _cmd_diag(args) -> int:
    """F10 (ADR-1024-11 D1): `python manage.py diag aliases` — READ-ONLY.

    Только SELECT; ничего не пишет в БД. Значения не выводятся (R17)."""
    if getattr(args, "diag_command", None) != "aliases":
        print("diag: неизвестная подкоманда", file=sys.stderr)
        return 2
    from services.pg_db import PgDatabase

    chat_ids = list(getattr(args, "chat_id", None) or [])

    async def _run():
        pg = PgDatabase()
        try:
            await pg.connect()
        except Exception as exc:
            print(f"diag aliases: не удалось подключиться к PostgreSQL "
                  f"({type(exc).__name__}) — диагностика не выполнена",
                  file=sys.stderr)
            return None
        if pg.pool is None:
            print("diag aliases: PostgreSQL недоступен (POSTGRES_DSN пуст "
                  "или пул не создан) — диагностика не выполнена",
                  file=sys.stderr)
            await _safe_close(pg)
            return None
        try:
            return await _collect_aliases_diag(pg, chat_ids=chat_ids)
        finally:
            await _safe_close(pg)

    try:
        report = asyncio.run(_run())
    except Exception as exc:
        print(f"diag aliases: ошибка диагностики ({type(exc).__name__}) — "
              f"данные не изменялись", file=sys.stderr)
        return 1
    if not report:
        return 1

    g = report["global"] or {}
    print(f"diag aliases: key={report['key']} widget={report['widget']} "
          f"global_present={'yes' if report['global_present'] else 'no'} "
          f"global_type={g.get('raw_type')} "
          f"global_keys={g.get('effective_keys')} "
          f"double_encoded={'yes' if g.get('double_encoded') else 'no'}")
    for chat in report["chats"]:
        ov = chat["override"] or {}
        print(f"  chat={chat['chat_id']} "
              f"profile={'yes' if chat['profile_present'] else 'no'} "
              f"override={'yes' if chat['override_present'] else 'no'} "
              f"override_type={ov.get('raw_type')} "
              f"override_keys={ov.get('effective_keys')} "
              f"api_value_keys={chat['api_value_keys']} "
              f"api_global_value_keys={chat['api_global_value_keys']} "
              f"api_chat_source='{chat['api_chat_source']}'")
    print("  вывод data: только форма/число ключей (R17), значения не "
          "печатаются; restore из бэкапа запрещён")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass            # не-файловый поток (pytest-каптура и т.п.)
    try:
        args = build_parser().parse_args(argv)
        if args.command == "apply-chat-overrides":
            return _cmd_apply_chat_overrides(args)
        if args.command == "audit-chat-overrides":
            return _cmd_audit_chat_overrides(args)
        if args.command == "memory":
            return _cmd_memory(args)
        if args.command == "disk":
            return _cmd_disk(args)
        if args.command == "diag":
            return _cmd_diag(args)
        if args.command in ("retention", "retention-dry-run"):
            return _cmd_retention(args)
        if args.command != "import_history":
            return 2
        if args.mode == "graph":
            return _cmd_import_history_graph(args)
        return _cmd_import_history_fts(args)
    except KeyboardInterrupt:
        # Задача 2: ручной останов — понятная фраза + exit 130, БЕЗ трейсбека
        # (прогресс пачек/чекпоинты сохранены — повторный запуск продолжит).
        print(f"\n{_KI_NOTICE}", file=sys.stderr)
        return _KI_EXIT_CODE


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    sys.exit(main())
