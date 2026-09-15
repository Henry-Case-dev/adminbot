"""F6 (10.19, ADR-1019-5 D3) — диагностика рассинхрона ФС↔БД для
медиа-путей (honest-контракт).

Симптом чекапа (UPD2 п.6): приложение «не находит» `photos/file_456.jpg`:
в БД есть записи-ссылки на медиа, а файлов на диске локального Bot API нет
(переезд/чистка).

D-4 (Medium, ревью Батча E): честный контракт результата. Схема БД НЕ хранит
реальные пути файлов (Bot API `file_path` транзиентен и не персистится),
поэтому:
  * `db_media_rows` — число записей `smart_messages` с медиа
    (`media_type != 'text'`) — достоверно;
  * `text_media_paths` — относительные медиа-пути, ЭВРИСТИЧЕСКИ найденные в
    ТЕКСТЕ сообщений (best-effort regex `photos/file_*.jpg`; обычно мало);
  * `files_on_disk` — bounded-обход каталога локального Bot API
    `TELEGRAM_API_FILES_DIR/<bot_id:token>/`;
  * `missing_on_disk`/`orphan_files`/`sample_missing` — производные от
    `text_media_paths` (эвристики), поэтому `reliable: false` и
    `basis: 'text_scan'`: числа НЕ выдаются за точный рассинхрон БД↔ФС.

R17 (жёстко): наружу/в логи — только хвосты имён и числовые счётчики; строка
`<bot_id>:<token>` и абсолютные пути с токеном НИКОГДА не логируются/не
отдаются. Fail-open: любая ошибка → нулевые счётчики (эндпоинт не падает).
"""
import asyncio
import logging
import re
from pathlib import Path

from config.settings import settings
from services.media_download import local_files_subdir

logger = logging.getLogger(__name__)

# Относительные пути локального Bot API, которые могут встречаться в тексте
# сообщений/логах: photos/file_456.jpg, videos/file_1.mp4, voice/file_9.ogg …
_MEDIA_PATH_RE = re.compile(
    r"(?:photos|videos|documents|voice|music|animations|stickers|video_notes)"
    r"/[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}")
# Категории медиа-сообщений (media_type != 'text') — «ссылки на медиа в БД».
_MEDIA_TYPES = ("photo", "video", "voice", "audio", "document", "animation",
                "video_note", "sticker")

_MAX_DISK_ENTRIES = 20000          # bounded-обход каталога Bot API
_SAMPLE_TAILS = 10                 # сколько примеров хвостов отдавать наружу


def _tail(path: str) -> str:
    """R17-safe хвост: последние две сегмента «dir/file» (без корня/токена)."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p]
    return "/".join(parts[-2:]) if parts else ""


def _extract_text_paths(rows, limit: int) -> dict[str, str]:
    """{lower_path: tail-путь} из текстов сообщений (bounded limit)."""
    found: dict[str, str] = {}
    for row in rows:
        text = row_get(row, "text")
        if not text:
            continue
        for match in _MEDIA_PATH_RE.findall(str(text)):
            key = match.lower()
            if key not in found:
                found[key] = _tail(match)
            if len(found) >= limit:
                return found
    return found


def row_get(row, key, default=None):
    """Field accessor как в database.row_get (dict/aiosqlite.Row/tuple)."""
    if hasattr(row, "get"):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


async def _db_media_paths(db, chat_id: int | None, sample_limit: int):
    """(db_media_rows, {lower_path: tail}) — DB-счётчик + текстовые пути
    (fail-open — вызывающий). `db_media_rows` достоверен; пути — эвристика
    из текста (реальных file_path в схеме нет, D-4)."""
    type_ph = ",".join("?" for _ in _MEDIA_TYPES)
    where = f"media_type IN ({type_ph})"
    params: list = list(_MEDIA_TYPES)
    if chat_id is not None:
        where += " AND chat_id = ?"
        params.append(int(chat_id))
    cursor = await db.db.execute(
        f"SELECT COUNT(*) AS c FROM smart_messages WHERE {where}", params)
    row = await cursor.fetchone()
    db_rows = int(row_get(row, "c", 0) or 0)
    # Пути из текста — bounded выборка свежих непустых сообщений.
    text_where = "text IS NOT NULL AND text != ''"
    text_params: list = []
    if chat_id is not None:
        text_where += " AND chat_id = ?"
        text_params.append(int(chat_id))
    cursor = await db.db.execute(
        f"SELECT text FROM smart_messages WHERE {text_where} "
        "ORDER BY id DESC LIMIT ?", [*text_params, int(sample_limit)])
    rows = await cursor.fetchall()
    return db_rows, _extract_text_paths(rows, int(sample_limit))


def _local_root(bot) -> Path | None:
    """Корень локального Bot API-хранилища (R17 — не логируется)."""
    if bot is None:
        return None
    try:
        return Path(settings.TELEGRAM_API_FILES_DIR) / local_files_subdir(bot)
    except Exception:
        return None


def _scan_disk(root: Path | None, limit: int) -> set[str]:
    """Bounded обход файлов под root → {lower relative path}."""
    present: set[str] = set()
    if root is None:
        return present
    try:
        if not root.exists():
            return present
        for entry in root.rglob("*"):
            if len(present) >= limit:
                break
            try:
                if entry.is_file():
                    present.add(entry.relative_to(root).as_posix().lower())
            except (OSError, ValueError):
                continue
    except OSError:
        logger.warning("[media_integrity] disk scan failed — fail-open",
                       exc_info=False)
    return present


async def audit_media_files(db, bot=None, *, chat_id: int | None = None,
                            sample_limit: int = 200) -> dict:
    """F6 (ADR-1019-5 D3, D-4): диагностика БД↔ФС.

    Возвращает `{db_media_rows, text_media_paths, files_on_disk,
    missing_on_disk, orphan_files, sample_missing, reliable, basis}`.
    `reliable=False`/`basis='text_scan'` — пути берутся из ТЕКСТА сообщений
    (в схеме нет реальных file_path), поэтому missing/orphan — эвристики, а
    не точный рассинхрон. Тяжёлый обход диска — в отдельном потоке
    (`asyncio.to_thread`), чтобы не блокировать event loop (D-3). R17: только
    числа и хвосты имён; ошибка → нулевые счётчики (fail-open)."""
    out = {
        "db_media_rows": 0,
        "text_media_paths": 0,
        "files_on_disk": 0,
        "missing_on_disk": 0,
        "orphan_files": 0,
        "sample_missing": [],
        "reliable": False,
        "basis": "text_scan",
    }
    try:
        db_rows, db_paths = await _db_media_paths(db, chat_id, sample_limit)
        out["db_media_rows"] = db_rows
        out["text_media_paths"] = len(db_paths)
    except Exception:
        logger.warning("[media_integrity] audit db failed — fail-open",
                       exc_info=True)
        return out
    try:
        # D-3: синхронный rglob по каталогу (до _MAX_DISK_ENTRIES файлов) —
        # в отдельном потоке, event loop не блокируется.
        disk = await asyncio.to_thread(
            _scan_disk, _local_root(bot), _MAX_DISK_ENTRIES)
    except Exception:
        disk = set()
    out["files_on_disk"] = len(disk)
    db_lower = set(db_paths.keys())
    missing = [tail for key, tail in db_paths.items() if key not in disk]
    out["missing_on_disk"] = len(missing)
    out["sample_missing"] = sorted(set(missing))[:_SAMPLE_TAILS]
    out["orphan_files"] = sum(1 for f in disk if f not in db_lower)
    logger.info(
        "[media_integrity] audit | db_rows=%d text_paths=%d disk=%d "
        "missing=%d orphan=%d | reliable=false",
        out["db_media_rows"], out["text_media_paths"], out["files_on_disk"],
        out["missing_on_disk"], out["orphan_files"])
    return out
