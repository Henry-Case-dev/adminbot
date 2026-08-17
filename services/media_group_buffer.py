"""Epic 36 — MediaGroupCaptionBuffer (R36-1, D121/D122, Section 45.1).

Сервисный слой БЕЗ импортов из handlers (нет циклов: и handlers/summary.py,
и handlers/factcheck.py импортируют из него). Прецедент структуры:
services/smartmodule_throttling.py (общее состояние, используемое хендлерами);
прецедент механики: handlers/dead_page_trigger.py _seen_media_groups
(OrderedDict LRU + TTL).

Заполнение: record_media_group_message из summary_observer (0a) — caption
приходит в Telegram ТОЛЬКО на ПЕРВОМ элементе media group. Чтение:
get_media_group_caption из handlers/factcheck.py (_extract_target_text) —
reply «фактчек» на 2-е/3-е фото альбома получает caption 1-го фото.
In-memory: после рестарта буфер пуст → fallback 5.3 (принято, D121).
"""
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

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
    - запись ЕСТЬ → move_to_end(mgid) + ts = now (TTL от последнего элемента пачки);
      caption НЕ перезаписывается пустым (caption только на 1-м элементе);
    - записи НЕТ и caption непустой → вставка {caption, first_message_id, ts};
    - записи НЕТ и caption пуст → ничего (альбом без caption в буфере не храним);
    - _cleanup_expired() на write-пути; len > MAX_ENTRIES → popitem(last=False) (LRU).
    """
    mgid = getattr(message, "media_group_id", None)
    if not mgid:
        return
    caption = (message.caption or message.text or "").strip()
    _cleanup_expired()
    now = time.monotonic()
    record = _buffer.get(mgid)
    if record is not None:
        _buffer.move_to_end(mgid)
        record.ts = now                       # TTL от последнего элемента пачки
        logger.debug(
            "Media group buffer: touch | group=%s entries=%d", mgid, len(_buffer)
        )
        return
    if not caption:
        return                               # альбом без caption не храним
    _buffer[mgid] = _MediaGroupRecord(
        caption=caption,
        first_message_id=message.message_id,
        ts=now,
    )
    if len(_buffer) > MAX_ENTRIES:
        evicted, _ = _buffer.popitem(last=False)
        logger.debug("Media group buffer: LRU evicted | group=%s", evicted)
    logger.info(
        "Media group buffer: insert | group=%s first_msg=%s caption_len=%d entries=%d",
        mgid, message.message_id, len(caption), len(_buffer),
    )


def get_media_group_caption(media_group_id: str) -> str | None:
    """Чтение (из handlers/factcheck.py). None = нет записи / TTL истёк
    (ленивая эвикция: del + DEBUG-expiry)."""
    record = _buffer.get(media_group_id)
    if record is None:
        return None
    if time.monotonic() - record.ts > TTL_SECONDS:
        del _buffer[media_group_id]
        logger.debug(
            "Media group buffer: expired on read | group=%s", media_group_id
        )
        return None
    return record.caption
