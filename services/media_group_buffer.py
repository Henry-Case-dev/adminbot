"""Epic 36 — MediaGroupCaptionBuffer (R36-1, D121/D122, Section 45.1).

Сервисный слой БЕЗ импортов из handlers (нет циклов: и handlers/summary.py,
и handlers/factcheck.py импортируют из него). Прецедент структуры:
services/smartmodule_throttling.py (общее состояние, используемое хендлерами);
прецедент механики: handlers/dead_page_trigger.py _seen_media_groups
(OrderedDict LRU + TTL).

Заполнение: record_media_group_message из summary_observer (0a) — caption
приходит в Telegram ТОЛЬКО на ПЕРВОМ элементе media group. Чтение:
get_media_group_caption / get_media_group_ids из
services/factcheck_service.py (resolve_claim_publication) — reply «фактчек»
на 2-е/3-е фото альбома получает caption 1-го фото и набор id элементов,
чтобы отличить неполный durable-альбом от полного.

P0-FACTCHECK media (owner 25.10.2026 §3.3; review fix): буфер — только
same-turn fast-path. Источник истины реконструкции альбома — durable
`smart_messages.media_group_id` (observer пишет каждый элемент); после
рестарта/TTL альбом всё равно собирается из БД. Набор id элементов нужен
ТОЛЬКО для честной оценки полноты («в группе было N элементов, прочитано M»).
"""
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from aiogram import types

logger = logging.getLogger(__name__)

TTL_SECONDS = 60.0      # D122: reply юзера может прийти заметно позже пачки
                        # (dead_page — 5с, но там окно доставки пачки; здесь человеческий ответ)
MAX_ENTRIES = 100       # прецедент _MAX_DEDUP_ENTRIES; 100 × ~1KB ≈ <150KB памяти


@dataclass
class _MediaGroupRecord:
    caption: str
    first_message_id: int
    ts: float           # time.monotonic()
    # Review fix (25.10.2026): id всех элементов пачки — чтобы отличить
    # неполный durable-альбом (потерянная строка) от полного. Bounded:
    # Telegram media group ≤ 10 элементов.
    message_ids: set = field(default_factory=set)


_buffer: OrderedDict[str, _MediaGroupRecord] = OrderedDict()


def _cleanup_expired(now: float | None = None) -> None:
    """Выбросить записи старше TTL_SECONDS (прецедент _cleanup_expired_media_groups)."""
    if now is None:
        now = time.monotonic()
    expired = [k for k, rec in _buffer.items() if now - rec.ts > TTL_SECONDS]
    for k in expired:
        del _buffer[k]
        logger.debug("Media group buffer: expired entry evicted | group=%s", k)


def record_media_group_message(message: types.Message) -> None:
    """Заполнение буфера. Вызывается из summary_observer (0a) для КАЖДОГО сообщения.

    Правила:
    - media_group_id нет → return (не альбом);
    - caption = (message.caption or message.text or "").strip();
    - запись ЕСТЬ → move_to_end(mgid) + ts = now (TTL от последнего элемента),
      id элемента добавляется в набор; caption НЕ перезаписывается пустым;
    - записи НЕТ и caption непустой → вставка {caption, first_message_id, ids};
    - записи НЕТ и caption пуст → запись с пустым caption и набором id (альбом
      без подписи: caption не отдаётся, но полнота группы известна);
    - _cleanup_expired() на write-пути; len > MAX_ENTRIES → popitem(last=False) (LRU).
    """
    mgid = getattr(message, "media_group_id", None)
    if not mgid:
        return
    caption = (message.caption or message.text or "").strip()
    message_id = getattr(message, "message_id", None)
    _cleanup_expired()
    now = time.monotonic()
    record = _buffer.get(mgid)
    if record is not None:
        _buffer.move_to_end(mgid)
        record.ts = now                       # TTL от последнего элемента пачки
        if isinstance(message_id, int) and not isinstance(message_id, bool):
            record.message_ids.add(message_id)
        logger.debug(
            "Media group buffer: touch | group=%s entries=%d", mgid, len(_buffer)
        )
        return
    ids = {message_id} if isinstance(message_id, int) \
        and not isinstance(message_id, bool) else set()
    _buffer[mgid] = _MediaGroupRecord(
        caption=caption,
        first_message_id=message_id if isinstance(message_id, int) else 0,
        ts=now,
        message_ids=ids,
    )
    if len(_buffer) > MAX_ENTRIES:
        evicted, _ = _buffer.popitem(last=False)
        logger.debug("Media group buffer: LRU evicted | group=%s", evicted)
    logger.info(
        "Media group buffer: insert | group=%s first_msg=%s caption_len=%d entries=%d",
        mgid, message_id, len(caption), len(_buffer),
    )


def _live_record(media_group_id: str) -> _MediaGroupRecord | None:
    """Запись группы без истёкших (ленивая эвикция); None — нет/TTL."""
    record = _buffer.get(media_group_id)
    if record is None:
        return None
    if time.monotonic() - record.ts > TTL_SECONDS:
        del _buffer[media_group_id]
        logger.debug(
            "Media group buffer: expired on read | group=%s", media_group_id
        )
        return None
    return record


def get_media_group_caption(media_group_id: str) -> str | None:
    """Чтение (из handlers/factcheck.py). None = нет записи / TTL истёк
    (ленивая эвикция: del + DEBUG-expiry)."""
    if not media_group_id:
        return None
    record = _live_record(media_group_id)
    if record is None:
        return None
    return record.caption or None


def get_media_group_ids(media_group_id: str) -> tuple[int, ...] | None:
    """Id элементов группы, виденных в этом же ходе (ASC); None — нет/TTL.

    Review fix: позволяет отличить «в группе было N элементов, durable-строк
    M<N» от полного альбома. После рестарта буфер пуст → None (полнота
    оценивается по durable-строке/непрерывности id, см. resolver)."""
    if not media_group_id:
        return None
    record = _live_record(media_group_id)
    if record is None or not record.message_ids:
        return None
    return tuple(sorted(record.message_ids))
