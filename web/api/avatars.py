"""UI-полировка TMA — прокси аватаров Telegram + RAM-кэши обогащения.

GET /api/avatar/{kind}/{tid} (kind: chat|user; tid: int), под
Depends(get_tma_user) (как все /api-роуты, кроме /health):

  * chat:  bot.get_chat(tid).photo.big_file_id (у супергрупп фото есть,
           если установлено; иначе None → 404);
  * user:  bot.get_user_profile_photos(tid, limit=1) → file_id первого
           фото;
  * скачивание: bot.get_file(file_id) → download в память (BytesIO);
  * ответ: Response(content, media_type='image/jpeg',
    Cache-Control: public, max-age=86400);
  * RAM-TTL-кэш {(kind, tid): (ts, bytes|None)} — 1 час, максимум
    _MAX_CACHE_ENTRIES записей (в т.ч. негативный результат: юзер/чат без
    фото или ошибка Bot API → кэшируем None, чтобы фронт с onerror не
    долбил API). Ошибки → 404. Rate-limit не нужен (кэш).

Здесь же — RAM-кэши обогащения /api/chat_lore (title/photo чата,
username/фото участника): общие с аватарами, чтобы каждый chat/юзер
дёргал Bot API не чаще раза в час. Негативы (ошибка Bot API / нет фото)
кэшируются ТАК ЖЕ, как у аватаров (fix-раунд ревью).
"""
import io
import logging
import time
from typing import Annotated, Literal

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from services import web_runtime
from web.api.deps import get_tma_user

logger = logging.getLogger(__name__)

avatar_router = APIRouter()

_TTL_SECONDS = 3600             # 1 час: и аватары, и обогащение
_MAX_CACHE_ENTRIES = 500        # потолок записей RAM-кэша аватаров

_MISS = object()

# {(kind, tid): (ts, bytes|None)} — байты фото или None (негатив-кэш)
_avatar_cache: dict[tuple[str, int], tuple[float, bytes | None]] = {}
# {chat_id: (ts, {"title": str|None, "photo_file_id": str|None})}
_chat_info_cache: dict[int, tuple[float, dict]] = {}
# {(chat_id, user_id): (ts, username|None)} — username члена чата
_username_cache: dict[tuple[int, int], tuple[float, str | None]] = {}
# {user_id: (ts, photo_file_id|None)} — первое фото профиля
_user_photo_cache: dict[int, tuple[float, str | None]] = {}


# ── RAM-TTL-кэш (общий для всех словарей) ──────────────────────────────────

def _cache_get(cache: dict, key) -> object:
    """Значение записи или _MISS (нет/протухла; протухшую удаляем)."""
    hit = cache.get(key)
    if hit is None:
        return _MISS
    ts, value = hit
    if time.time() - ts >= _TTL_SECONDS:
        cache.pop(key, None)
        return _MISS
    return value


def _cache_put(cache: dict, key, value) -> None:
    """Запись с вытеснением: сначала протухшие, затем самая старая."""
    if len(cache) >= _MAX_CACHE_ENTRIES:
        now = time.time()
        for k in [k for k, (t, _v) in cache.items()
                  if now - t >= _TTL_SECONDS]:
            cache.pop(k, None)
    if len(cache) >= _MAX_CACHE_ENTRIES:
        oldest = min(cache, key=lambda k: cache[k][0])
        cache.pop(oldest, None)
    cache[key] = (time.time(), value)


# ── helpers Bot API ─────────────────────────────────────────────────────────

def _user_photo_file_id(photos) -> str | None:
    """file_id ПЕРВОГО фото профиля (берём наименьший размер — для аватара
    лишние мегабайты не нужны). photos: UserProfilePhotos (photos —
    list[list[PhotoSize]]) или сырой list; None → None."""
    raw = photos
    if raw is None:
        return None
    lst = raw.photos if hasattr(raw, "photos") else raw
    if not lst:
        return None
    first = lst[0]
    if isinstance(first, (list, tuple)):
        if not first:
            return None
        return first[0].file_id if hasattr(first[0], "file_id") else None
    return getattr(first, "file_id", None)


async def _avatar_file_id(bot, kind: str, tid: int) -> str | None:
    """file_id аватара чата/юзера; нет фото/ошибка → None (→ 404/негатив)."""
    if kind == "chat":
        chat = await bot.get_chat(tid)
        photo = getattr(chat, "photo", None)
        if photo is None:
            return None
        return getattr(photo, "big_file_id", None)
    photos = await bot.get_user_profile_photos(tid, limit=1)
    return _user_photo_file_id(photos)


async def fetch_avatar_bytes(kind: str, tid: int) -> bytes | None:
    """Байты аватара (кэш 1ч; None кэшируется как негатив тоже)."""
    key = (kind, tid)
    hit = _cache_get(_avatar_cache, key)
    if hit is not _MISS:
        return hit
    bot = web_runtime.get_web_bot()
    data = None
    if bot is not None:
        try:
            file_id = await _avatar_file_id(bot, kind, tid)
            if file_id:
                file = await bot.get_file(file_id)
                path = getattr(file, "file_path", None)
                if path:
                    buf = io.BytesIO()
                    await bot.download_file(path, destination=buf)
                    data = buf.getvalue() or None
        except Exception:
            logger.warning("[avatar] fetch failed | kind=%s tid=%s",
                           kind, tid, exc_info=True)
            data = None
    _cache_put(_avatar_cache, key, data)
    return data


# ── обогащение /api/chat_lore (chat_lore.py использует эти функции) ────────

async def chat_display_info(chat_id: int) -> dict:
    """{title, photo_file_id} для чата (best-effort, кэш 1ч): get_chat →
    title + photo.big_file_id — БЕЗ скачивания. Нет бота/ошибка → None-поля;
    негатив (ошибка Bot API, чат без фото) ТОЖЕ пишется в кэш — обогащение
    не долбит Bot API каждый запрос (fix-раунд ревью)."""
    hit = _cache_get(_chat_info_cache, chat_id)
    if hit is not _MISS:
        return dict(hit)
    info = {"title": None, "photo_file_id": None}
    bot = web_runtime.get_web_bot()
    if bot is None:
        return info
    try:
        chat = await bot.get_chat(chat_id)
        info["title"] = getattr(chat, "title", None)
        photo = getattr(chat, "photo", None)
        if photo is not None:
            info["photo_file_id"] = getattr(photo, "big_file_id", None)
    except Exception:
        logger.warning("[avatar] get_chat failed | chat_id=%s", chat_id,
                       exc_info=True)
    _cache_put(_chat_info_cache, chat_id, dict(info))
    return info


async def user_display_info(chat_id: int, user_id: int) -> dict:
    """{username, photo_file_id} участника чата (best-effort, кэши 1ч):
    username — bot.get_chat_member(chat_id, user_id).user.username (по
    (chat_id, user_id)), фото — getUserProfilePhotos limit=1 → file_id
    (по user_id). Нет бота/ошибка → None-поля (fail-open); негативы
    (ошибка/нет фото) тоже кэшируются — обогащение не долбит Bot API
    каждый запрос (fix-раунд ревью)."""
    bot = web_runtime.get_web_bot()
    username = None
    photo_file_id = None
    if bot is not None:
        ukey = (chat_id, user_id)
        hit = _cache_get(_username_cache, ukey)
        if hit is not _MISS:
            username = hit
        else:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                member_user = getattr(member, "user", None)
                username = (getattr(member_user, "username", None)
                            if member_user is not None else None)
            except Exception:
                logger.warning(
                    "[avatar] get_chat_member failed | chat=%s user=%s",
                    chat_id, user_id, exc_info=True)
            _cache_put(_username_cache, ukey, username)
        hit = _cache_get(_user_photo_cache, user_id)
        if hit is not _MISS:
            photo_file_id = hit
        else:
            try:
                photos = await bot.get_user_profile_photos(user_id, limit=1)
                photo_file_id = _user_photo_file_id(photos)
            except Exception:
                logger.warning(
                    "[avatar] profile photos failed | user=%s", user_id,
                    exc_info=True)
            _cache_put(_user_photo_cache, user_id, photo_file_id)
    return {"username": username, "photo_file_id": photo_file_id}


# ── роут: GET /api/avatar/{kind}/{tid} ──────────────────────────────────────

@avatar_router.get("/avatar/{kind}/{tid}")
async def avatar_proxy(
    kind: Literal["chat", "user"],
    tid: int,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Прокси аватара: image/jpeg + Cache-Control public,max-age=86400;
    нет фото/бота/ошибки → 404 (негатив кэшируется на 1ч)."""
    data = await fetch_avatar_bytes(kind, tid)
    if not data:
        raise HTTPException(status_code=404, detail="avatar not found")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
