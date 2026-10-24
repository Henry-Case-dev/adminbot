"""PEMsoc: одна реакция на сообщение/альбом/оригинал поста.

Проблема (25.10.2026): несколько независимых обработчиков (war_alert,
slavik, kucha, GIF/photo counter) отвечали на одно и то же сообщение;
альбом из N фото давал N ответов, повторный репост того же поста — ещё
ответы. Здесь единый in-memory claim, который выставляется ДО отправки.

Ключи:
* ``msg``    — (chat_id, message_id), TTL 30 c: защита от повторных update;
* ``album``  — (chat_id, media_group_id), TTL 15 c: один ответ на альбом;
* ``origin`` — (chat_id, user_id, origin_chat_id, origin_message_id), TTL 120 c:
  один ответ на повторный репост/удаление того же поста.

Claim синхронный (без await), поэтому конкурентные апдейты альбома в одном
event loop не могут оба пройти проверку. Никаких БД/сети/LLM.
"""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

_MSG_TTL = 30.0
_ALBUM_TTL = 15.0
_ORIGIN_TTL = 120.0
_MAX_ENTRIES = 2000

_claims: "OrderedDict[tuple, float]" = OrderedDict()


def _chat_id(message: Any) -> int | None:
    chat = getattr(message, "chat", None)
    return getattr(chat, "id", None)


def _user_id(message: Any) -> int:
    user = getattr(message, "from_user", None)
    return int(getattr(user, "id", 0) or 0)


def _origin_key(message: Any) -> tuple | None:
    """Ключ оригинала для репоста из канала (MessageOriginChannel)."""
    origin = getattr(message, "forward_origin", None)
    origin_chat = getattr(origin, "chat", None)
    origin_msg_id = getattr(origin, "message_id", None)
    chat_id = _chat_id(message)
    if origin_chat is None or origin_msg_id is None or chat_id is None:
        return None
    return ("origin", chat_id, _user_id(message),
            getattr(origin_chat, "id", None), origin_msg_id)


def _keys(message: Any) -> list[tuple]:
    chat_id = _chat_id(message)
    msg_id = getattr(message, "message_id", None)
    keys: list[tuple] = []
    if chat_id is not None and msg_id is not None:
        keys.append(("msg", chat_id, msg_id))
    media_group_id = getattr(message, "media_group_id", None)
    if chat_id is not None and media_group_id:
        keys.append(("album", chat_id, media_group_id))
    origin = _origin_key(message)
    if origin is not None:
        keys.append(origin)
    return keys


def _ttl(key: tuple) -> float:
    return {"msg": _MSG_TTL, "album": _ALBUM_TTL,
            "origin": _ORIGIN_TTL}.get(str(key[0]), _MSG_TTL)


def _prune(now: float) -> None:
    for key, expires_at in list(_claims.items()):
        if expires_at <= now:
            _claims.pop(key, None)
    while len(_claims) > _MAX_ENTRIES:
        _claims.popitem(last=False)


def claim_reaction(message: Any, *, source: str = "") -> bool:
    """True — реакция разрешена и застолблена; False — уже была реакция.

    ``source`` только для логов/диагностики, на ключи не влияет.
    """
    keys = _keys(message)
    if not keys:
        return True
    now = time.monotonic()
    _prune(now)
    for key in keys:
        if _claims.get(key, 0.0) > now:
            return False
    for key in keys:
        _claims[key] = now + _ttl(key)
        _claims.move_to_end(key)
    return True


def reset_claims() -> None:
    """Сброс состояния (тесты/диагностика; в runtime не вызывается)."""
    _claims.clear()
