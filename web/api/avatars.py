"""UI-полировка TMA — прокси аватаров Telegram + RAM-кэши обогащения.

GET /api/avatar/{kind}/{tid} (kind: chat|user; tid: int), под
Depends(get_tma_user) (как все /api-роуты, кроме /health):

  * chat:  bot.get_chat(tid).photo.big_file_id (у супергрупп фото есть,
           если установлено; иначе None → 404);
  * user:  bot.get_user_profile_photos(tid, limit=1) → file_id первого
           фото;
  * скачивание: bot.get_file(file_id) → download в память (BytesIO);
  * ответ: Response(content, media_type='image/jpeg',
    Cache-Control: private, max-age=86400 + Vary: X-Telegram-Init-Data);
  * RAM-TTL-кэш {(kind, tid): (ts, bytes|None)} — 1 час, максимум
    _MAX_CACHE_ENTRIES записей (в т.ч. негативный результат: юзер/чат без
    фото или ошибка Bot API → кэшируем None, чтобы фронт с onerror не
    долбил API). Ошибки → 404. Rate-limit не нужен (кэш).
    Транзиентные сбои (TelegramRetryAfter/TelegramNetworkError) НЕ
    кэшируются (F5 §3, BUG-4) — на ВСЕХ сайтах.

Здесь же — RAM-кэши обогащения /api/chat_lore (title/photo чата,
username/фото участника): общие с аватарами, чтобы каждый chat/юзер
дёргал Bot API не чаще раза в час. Негативы (ошибка Bot API / нет фото)
кэшируются ТАК ЖЕ, как у аватаров (fix-раунд ревью).

Права на САМУ картинку (avatar-scope): аутентификации мало — без гейта
любой валидный TMA-юзер (мини-апп открывается из /menu любому, кто написал
боту) тянул бы фото любого Telegram-id и аватар любого чата бота. Правило
(существующие хелперы, без нового ACL): self — всегда; чат — доступен
запросившему (канон `access.can_access_chat`, как на всех chat-scoped
маршрутах); юзер — глобальный админ ЛИБО участник/админ чата, доступного
запросившему (авторитетный список участников — users_meta + гранты
chat_admins). Отказ — 403 permission_denied ДО Bot API (кэш байтов не
трогаем). Кэш ответа — `private` (персональный гейт: shared-кэш не должен
отдавать чужую картинку) + `Vary: X-Telegram-Init-Data`; TTL прежний.
"""
import io
import logging
import time
from typing import Annotated, Literal

from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, \
    TelegramBadRequest
from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from config.settings import settings
from services import access as access_srv
from services import hot_config as hot
from services import lore_runtime
from services import roles as roles_srv
from services import web_runtime
from services.media_download import read_host_file_bytes, read_local_file_bytes
from web.api.deps import get_cache, get_tma_user

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
# {user_id: (ts, display_name|None)} — имя/ник глобального пользователя
# (10.10, ADR-1010-3): bot.get_chat(user_id), chat_id не требуется.
_user_name_cache: dict[int, tuple[float, str | None]] = {}


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
    """Байты аватара: кэш 1ч — только ПОЛОЖИТЕЛЬНЫЙ результат и
    ДЕФИНИТИВНЫЕ негативы (нет фото: пустой список/пустой file_id).
    Транзиентные Bot API-ошибки (rate-limit TelegramRetryAfter / сетевые
    TelegramNetworkError) НЕ кэшируются: возврат None без записи негатива —
    следующий запрос (ленивый догруз, ре-рендер) попробует снова (BUG-4)."""
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
                # F6 (ADR-1019-5 D2): локальный Bot API отдаёт ОТНОСИТЕЛЬНЫЙ
                # file_path — сначала пробуем общий локальный fallback
                # (TELEGRAM_API_FILES_DIR/<bot_id:token>/<path>, 3 ретрая);
                # при None — прежний bot.download_file (облако/локальный).
                if hot.get("flags.download_enabled",
                           settings.DOWNLOAD_ENABLED):
                    data = await read_local_file_bytes(bot, file_id)
                if data is None:
                    file = await bot.get_file(file_id)
                    path = getattr(file, "file_path", None)
                    if path:
                        # P0 (prod-incident): локальный Bot API отдаёт
                        # контейнерный абсолютный путь; aiogram `download_file`
                        # падал FileNotFoundError. Сначала читаем host-файл по
                        # нормализованному пути (container→host).
                        data = await read_host_file_bytes(bot, path)
                        if data is None:
                            buf = io.BytesIO()
                            await bot.download_file(path, destination=buf)
                            data = buf.getvalue() or None
        except (TelegramRetryAfter, TelegramNetworkError) as exc:
            # транзиентный сбой (лимиты/сеть): негатив НЕ пишем — иначе
            # фронт с onerror стаггерил бы пустые аватары на час
            logger.warning(
                "[avatar] transient Bot API error — NOT cached | kind=%s "
                "tid=%s err=%s", kind, tid, safe_exc_text(exc))
            return None
        except TelegramBadRequest as exc:
            # ожидаемо (нет фото/прав/чата) → debug без трейса; негатив кэш.
            _log_bot_api_failure("fetch", kind=kind, tid=tid, exc=exc,
                                 expected=True)
            data = None
        except Exception:
            # неожидаемо (баг/неведомый класс) → warning с трейсом (R17-safe).
            _log_bot_api_failure("fetch", kind=kind, tid=tid, exc=None,
                                 expected=False)
            data = None
    _cache_put(_avatar_cache, key, data)
    return data


def safe_exc_text(exc: Exception) -> str:
    """Краткое описание ошибки Bot API (без секретов/трейса)."""
    text = getattr(exc, "message", None) or str(exc)
    return (text or exc.__class__.__name__)[:200]


def _log_bot_api_failure(site: str, *, kind: str, tid: int,
                         exc: Exception | None, expected: bool) -> None:
    """Единая политика логов Bot API-сбоев (F5, round 10.17).

    * ``expected=True`` — ``TelegramBadRequest`` (нет фото/прав/чата) →
      ``debug`` без трейсбека; вызывающий код пишет негатив в кэш;
    * ``expected=False`` — прочее/неведомый класс → ``warning`` с
      ``exc_info=True`` (R17-safe: Bot API-исключения секретов не несут,
      URL/токены в лог не попадают).
    """
    if expected:
        logger.debug("[avatar] %s expected failure | kind=%s tid=%s err=%s",
                     site, kind, tid, safe_exc_text(exc))
    else:
        logger.warning("[avatar] %s failed | kind=%s tid=%s",
                       site, kind, tid, exc_info=True)


# ── обогащение /api/chat_lore (chat_lore.py использует эти функции) ────────

async def chat_display_info(chat_id: int) -> dict:
    """{title, photo_file_id} для чата (best-effort, кэш 1ч): get_chat →
    title + photo.big_file_id — БЕЗ скачивания. Нет бота/ошибка → None-поля;
    негатив (ошибка Bot API, чат без фото) ТОЖЕ пишется в кэш — обогащение
    не долбит Bot API каждый запрос (fix-раунд ревью).

    Транзиент (rate-limit/сеть) → WARNING без трейса и БЕЗ записи в кэш
    (spec F5 §3, BUG-4): следующий рендер попробует снова."""
    hit = _cache_get(_chat_info_cache, chat_id)
    if hit is not _MISS:
        return dict(hit)
    info = {"title": None, "photo_file_id": None}
    bot = web_runtime.get_web_bot()
    if bot is None:
        return info
    transient = False
    try:
        chat = await bot.get_chat(chat_id)
        info["title"] = getattr(chat, "title", None)
        photo = getattr(chat, "photo", None)
        if photo is not None:
            info["photo_file_id"] = getattr(photo, "big_file_id", None)
    except (TelegramRetryAfter, TelegramNetworkError) as exc:
        transient = True
        logger.warning("[avatar] chat transient — NOT cached | chat=%s err=%s",
                       chat_id, safe_exc_text(exc))
    except TelegramBadRequest as exc:
        _log_bot_api_failure("chat", kind="chat", tid=chat_id, exc=exc,
                             expected=True)
    except Exception:
        _log_bot_api_failure("chat", kind="chat", tid=chat_id, exc=None,
                             expected=False)
    if not transient:
        _cache_put(_chat_info_cache, chat_id, dict(info))
    return info


async def user_display_info(chat_id: int, user_id: int) -> dict:
    """{username, photo_file_id} участника чата (best-effort, кэши 1ч):
    username — bot.get_chat_member(chat_id, user_id).user.username (по
    (chat_id, user_id)), фото — getUserProfilePhotos limit=1 → file_id
    (по user_id). Нет бота/ошибка → None-поля (fail-open); негативы
    (ошибка/нет фото) тоже кэшируются — обогащение не долбит Bot API
    каждый запрос (fix-раунд ревью).

    Транзиент (rate-limit/сеть) на любом из двух вызовов → WARNING без
    трейса и БЕЗ записи соответствующего негатива в кэш (spec F5 §3,
    BUG-4) — как в `fetch_avatar_bytes`/`global_user_display_info`."""
    bot = web_runtime.get_web_bot()
    username = None
    photo_file_id = None
    if bot is not None:
        ukey = (chat_id, user_id)
        hit = _cache_get(_username_cache, ukey)
        if hit is not _MISS:
            username = hit
        else:
            username_transient = False
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                member_user = getattr(member, "user", None)
                username = (getattr(member_user, "username", None)
                            if member_user is not None else None)
            except (TelegramRetryAfter, TelegramNetworkError) as exc:
                username_transient = True
                logger.warning(
                    "[avatar] chat member transient — NOT cached | chat=%s "
                    "user=%s err=%s", chat_id, user_id, safe_exc_text(exc))
            except TelegramBadRequest as exc:
                _log_bot_api_failure("chat_member", kind="member",
                                     tid=user_id, exc=exc, expected=True)
            except Exception:
                _log_bot_api_failure("chat_member", kind="member",
                                     tid=user_id, exc=None, expected=False)
            if not username_transient:
                _cache_put(_username_cache, ukey, username)
        hit = _cache_get(_user_photo_cache, user_id)
        if hit is not _MISS:
            photo_file_id = hit
        else:
            photo_transient = False
            try:
                photos = await bot.get_user_profile_photos(user_id, limit=1)
                photo_file_id = _user_photo_file_id(photos)
            except (TelegramRetryAfter, TelegramNetworkError) as exc:
                photo_transient = True
                logger.warning(
                    "[avatar] profile photos transient — NOT cached | "
                    "user=%s err=%s", user_id, safe_exc_text(exc))
            except TelegramBadRequest as exc:
                _log_bot_api_failure("profile_photos", kind="photos",
                                     tid=user_id, exc=exc, expected=True)
            except Exception:
                _log_bot_api_failure("profile_photos", kind="photos",
                                     tid=user_id, exc=None, expected=False)
            if not photo_transient:
                _cache_put(_user_photo_cache, user_id, photo_file_id)
    return {"username": username, "photo_file_id": photo_file_id}


async def global_user_display_info(user_id: int) -> dict:
    """{display_name, photo_file_id} глобального пользователя (10.10,
    ADR-1010-3; best-effort, RAM-TTL 1ч, fail-open None).

    Имя: bot.get_chat(user_id) → first_name/last_name (Full Name
    предпочтительно) → username (без «@»). Фото: существующий
    `_user_photo_cache` + get_user_profile_photos(limit=1). chat_id НЕ
    нужен (в отличие от user_display_info(chat_id, uid)). Нет бота/бота
    «не знает» юзера → None (фронт покажет фолбэк-ID). LOW-4: транзиентные
    Bot API-ошибки (TelegramRetryAfter/TelegramNetworkError) НЕ кэшируются
    (паттерн BUG-4 у fetch_avatar_bytes) — следующий запрос попробует
    снова; кэшируются только дефинитивные негативы (нет имени/фото)."""
    info = {"display_name": None, "photo_file_id": None}
    bot = web_runtime.get_web_bot()
    if bot is None:
        return info

    hit = _cache_get(_user_name_cache, user_id)
    if hit is not _MISS:
        info["display_name"] = hit
    else:
        name = None
        name_transient = False
        try:
            chat = await bot.get_chat(user_id)
            first = getattr(chat, "first_name", None)
            last = getattr(chat, "last_name", None)
            full = " ".join(p for p in (first, last) if p).strip()
            if full:
                name = full
            else:
                username = getattr(chat, "username", None)
                if username:
                    name = str(username).lstrip("@") or None
        except (TelegramRetryAfter, TelegramNetworkError) as exc:
            name_transient = True
            logger.warning(
                "[avatar] get_chat(user) transient — NOT cached | user=%s "
                "err=%s", user_id, safe_exc_text(exc))
        except TelegramBadRequest as exc:
            _log_bot_api_failure("get_chat(user)", kind="name",
                                 tid=user_id, exc=exc, expected=True)
        except Exception:
            _log_bot_api_failure("get_chat(user)", kind="name",
                                 tid=user_id, exc=None, expected=False)
        if not name_transient:
            _cache_put(_user_name_cache, user_id, name)
        info["display_name"] = name

    hit = _cache_get(_user_photo_cache, user_id)
    if hit is not _MISS:
        info["photo_file_id"] = hit
    else:
        photo_file_id = None
        photo_transient = False
        try:
            photos = await bot.get_user_profile_photos(user_id, limit=1)
            photo_file_id = _user_photo_file_id(photos)
        except (TelegramRetryAfter, TelegramNetworkError) as exc:
            photo_transient = True
            logger.warning(
                "[avatar] profile photos transient — NOT cached | user=%s "
                "err=%s", user_id, safe_exc_text(exc))
        except TelegramBadRequest as exc:
            _log_bot_api_failure("profile_photos(user)", kind="photos",
                                 tid=user_id, exc=exc, expected=True)
        except Exception:
            _log_bot_api_failure("profile_photos(user)", kind="photos",
                                 tid=user_id, exc=None, expected=False)
        if not photo_transient:
            _cache_put(_user_photo_cache, user_id, photo_file_id)
        info["photo_file_id"] = photo_file_id
    return info


# ── авторизация картинки: кто вправе видеть этот аватар ─────────────────────
# Privacy-фикс (avatar-scope): аутентификации TMA недостаточно — id в пути
# приходит от клиента. Правило и хелперы — существующие (никакого нового ACL/
# кэша/настройки): доступ к чату = `access.can_access_chat` (канон routes.py/
# stories.py), «свой чат/свой профиль» — те же данные, что видит UI
# (users_meta — авторитетный список участников, chat_admins — гранты).

async def _chat_visible(cache, telegram_id: int, chat_id: int) -> bool:
    """Доступ юзера к чату (Q3-семантика) через канон can_access_chat.
    Сбой резолва ctx → False (fail-closed: лучше без аватара, чем чужой)."""
    try:
        ctx = await roles_srv.access_for(telegram_id, chat_id, cache=cache)
    except Exception:
        logger.warning("[avatar] access ctx failed — deny | user=%s chat=%s",
                       telegram_id, chat_id, exc_info=True)
        return False
    return access_srv.can_access_chat(ctx, chat_id)


async def _shares_chat_with(cache, telegram_id: int, target_id: int) -> bool:
    """target — участник (users_meta) или админ (chat_admins) хотя бы одного
    чата, доступного telegram_id. Чаты берём из существующего списка профилей
    лора (источник UI, F-14: DM-строки там отсутствуют). Нет лора/сбой
    источника → False (fail-closed)."""
    store = lore_runtime.get_lore_store()
    if store is None:
        return False
    try:
        profiles = await store.list_profiles()
    except Exception:
        logger.warning("[avatar] profiles unavailable — deny | user=%s",
                       telegram_id, exc_info=True)
        return False
    db = lore_runtime.get_lore_db()
    for profile in profiles:
        chat_id = int(profile.chat_id)
        known = False
        if db is not None:
            try:
                known = bool(await db.get_users_meta(chat_id, [target_id]))
            except Exception:
                known = False
        if not known:
            try:
                known = bool(await store.is_chat_admin(target_id, chat_id))
            except Exception:
                known = False
        if not known:
            continue
        if await _chat_visible(cache, telegram_id, chat_id):
            return True
    return False


async def _avatar_allowed(request: Request, user: WebAppUser, kind: str,
                          tid: int) -> bool:
    """Правило видимости аватара: self — всегда; глобальный админ — всё;
    kind=chat — только доступный чат; kind=user — только тот, с кем есть
    общий (доступный запросившему) чат."""
    if kind == "user" and tid == user.id:
        return True
    cache = get_cache(request)
    try:
        ctx = await roles_srv.access_for(user.id, cache=cache)
    except Exception:
        logger.warning("[avatar] access ctx failed — deny | user=%s",
                       user.id, exc_info=True)
        return False
    if ctx.is_global_admin:
        return True
    if kind == "chat":
        return await _chat_visible(cache, user.id, tid)
    return await _shares_chat_with(cache, user.id, tid)


# ── роут: GET /api/avatar/{kind}/{tid} ──────────────────────────────────────

@avatar_router.get("/avatar/{kind}/{tid}")
async def avatar_proxy(
    kind: Literal["chat", "user"],
    tid: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Прокси аватара: image/jpeg + Cache-Control private,max-age=86400
    (+ Vary по заголовку аутентификации); нет фото/бота/ошибки → 404
    (негатив кэшируется на 1ч); чужой аватар (нет доступа к чату/общего
    чата) → 403 permission_denied ДО Bot API."""
    if not await _avatar_allowed(request, user, kind, tid):
        request.state.tma_deny_reason = "permission_denied"
        logger.info("[avatar] denied | kind=%s tid=%s by=%s",
                    kind, tid, user.id)
        raise HTTPException(status_code=403, detail="permission denied")
    data = await fetch_avatar_bytes(kind, tid)
    if not data:
        raise HTTPException(status_code=404, detail="avatar not found")
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            # Картинка персональная (гейт доступа выше): shared-кэш
            # (proxy/CDN/общий профиль браузера) не должен отдавать её
            # другому пользователю в обход 403. private — кэш только у
            # запросившего клиента; TTL прежний (сутки).
            "Cache-Control": "private, max-age=86400",
            # Ответ зависит от личности запросившего; механизм
            # аутентификации /api — заголовок X-Telegram-Init-Data
            # (фронт: avatarUrl передаёт его же) → ключ кэша посредников.
            "Vary": "X-Telegram-Init-Data",
        },
    )
