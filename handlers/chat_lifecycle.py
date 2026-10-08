"""Раунд 7 (chat-lore-management-v2, T-777/T-778, D1/D2) — lifecycle чатов.

Два chat_member-хендлера ТОЛЬКО по событиям самого бота (узкий фильтр:
ChatMemberUpdatedFilter + проверка new/old_chat_member.user.id == bot.id;
обязателен — Group Privacy; прецедент фильтрации handlers/slava_presence.py:
чужие события → UNHANDLED, чтобы не сломать существующие роутеры):

  * бот стал участником/админом (IS_NOT_MEMBER >> IS_MEMBER — группа
    IS_MEMBER покрывает member/administrator/creator/restricted(+)) →
    `ensure_profile(chat_id)` + `set_active(chat_id, True)`
    (существующие тексты/настройки не трогаются; FR-6);
  * бот удалён/вышел (IS_MEMBER >> IS_NOT_MEMBER) → `set_active(chat_id,
    False)` (тексты и настройки сохраняются).

Message-хендлер `migrate_to_chat_id` (aiogram 3; service-сообщение о переезде
чата: старый id = message.chat.id, новый = message.migrate_to_chat_id):
`store.add_link(old, new)` + `store.migrate_profile(old, new)` (Q9-merge,
WARNING при отсутствии профиля old — no-op). Ленивый резолв старых id —
внутри store (resolve_chat_id), хендлер ничего не кэширует (FR-7).

DI — модульный `setup_chat_lifecycle(store, bot_id=None)` (прецедент
`setup_presence`); регистрация в bot.py — добавочный инклуд рядом с
slava_presence_router (порядок существующих не менять). Fail-open: любые
ошибки store → WARNING, апдейт consumed (бот не падает).
"""
import logging
import time

from aiogram import BaseMiddleware, F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER

logger = logging.getLogger(__name__)

chat_lifecycle_router = Router(name="chat_lifecycle")


def _emit_lifecycle(event_name: str, outcome: str, *, level: str = "INFO",
                    **fields):
    """MCA-17 (`chat.lifecycle`): fail-open эмиссия (REUSE mca-13).

    Прецедент graphrag_rebuild._emit; R17: только id/коды — заголовки
    чатов/имена не переносятся."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="chat_lifecycle", **fields)
    except Exception:      # контракт не рвёт lifecycle-хендлер
        pass

_store = None          # ChatLoreStore (DI из bot.py)
_bot_id = None         # bot.id (DI из bot.py; None → сравнение отключено)
_db = None             # SQLite DatabaseService (DI из bot.py; MCA-03 D6)


def setup_chat_lifecycle(store, bot_id: int | None = None, db=None):
    """Called from bot.py to inject dependencies (прецедент setup_presence).

    `db` (SQLite) — аддитивно для MCA-03 (регистрация `chat_id_migrations` при
    подтверждённом `migrate_to_chat_id`); без него handler работает как прежде."""
    global _store, _bot_id, _db
    _store = store
    _bot_id = bot_id
    _db = db


def _is_bot_user(user) -> bool:
    """Событие про самого бота (узкий фильтр Group Privacy)."""
    if _bot_id is None:
        return False
    try:
        return user.id == _bot_id
    except AttributeError:
        return False


@chat_lifecycle_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
async def on_bot_joined(event: types.ChatMemberUpdated):
    """FR-6: бот стал участником/админом → профиль is_active=true."""
    return await _handle_bot_joined(event)


@chat_lifecycle_router.my_chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
async def on_bot_joined_my(event: types.ChatMemberUpdated):
    """ASAP 7 (F5, P7-C-1): то же самое по my_chat_member-observer.

    Собственное вступление бота Telegram доставляет как update
    `my_chat_member` (всегда, вне allowed_updates), а не `chat_member`
    (тот требует бот-админа и приходил бы только про чужих). Без этого
    хендлера my_chat_member-observer пуст → профиль нового чата не
    создаётся, чат невидим в /api/access/chats."""
    return await _handle_bot_joined(event)


async def _handle_bot_joined(event: types.ChatMemberUpdated):
    """Общая логика join для chat_member/my_chat_member (ASAP 7 F5)."""
    user = event.new_chat_member.user
    if not _is_bot_user(user):
        return UNHANDLED                 # чужие события — другим роутерам
    chat_id = event.chat.id
    logger.info("[chat_lifecycle] bot joined | chat_id=%s | status=%s",
                chat_id, event.new_chat_member.status)
    try:
        existed = False
        if _store is not None:
            existed = await _store.get_profile(chat_id) is not None
            await _store.upsert_profile_on_join(chat_id)
            await _store.set_active(chat_id, True)
        # ── Раунд 10 (F-9 T-884 / F-10 T-893): жёсткий Opt-In для НОВЫХ
        # чатов (профиля НЕ было). gates-пространство пусто/отсутствует →
        # явные дефолты: permsoc=false (F-9) + тяжёлые dream/nostalgia/
        # lore_auto=false (F-10); gates_opt_in — дефолт колонки (=false).
        # Существующие профили НЕ трогаем (их поведение — бэкфил-скрипты
        # Q3 деплоя); повторный вход (гейты уже записаны) — no-op.
        if not existed:
            await ensure_gates_defaults(chat_id)
    except Exception:
        logger.warning(
            "[chat_lifecycle] join upsert failed — fail-open | chat_id=%s",
            chat_id, exc_info=True)
    return None


async def ensure_gates_defaults(chat_id: int) -> None:
    """Единый патч gates при вступлении бота (F-9 + F-10 в ОДНОМ вызове
    set_chat_params — риск-гонка §8-правило: не делать два UPDATE)."""
    try:
        from services import chat_params
        pg = None
        cache = _global_cache()
        if cache is not None:
            pg = getattr(cache, "pg", None)
        if pg is None:
            return
        root = await chat_params.get_all_chat_params(chat_id)
        gates = root.get("gates") or {}
        if gates:
            return                     # уже записаны (в т.ч. частично)
        await chat_params.set_chat_params(
            chat_id,
            {"gates": {"permsoc": False, "dream": False,
                       "nostalgia": False, "lore_auto": False},
             "meta": {"updated_by": None, "note": "gates defaults (join)"}},
            changed_by=None, pg=pg, history_field="gates")
        logger.info(
            "[chat_lifecycle] gates defaults written | chat_id=%s "
            "(permsoc=dream=nostalgia=lore_auto=false)", chat_id)
    except Exception:
        logger.warning(
            "[chat_lifecycle] gates defaults failed — fail-open | chat_id=%s",
            chat_id, exc_info=True)


def _global_cache():
    try:
        from services import hot_config as hot
        return hot.get_config_cache()
    except Exception:
        return None


@chat_lifecycle_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_MEMBER >> IS_NOT_MEMBER
    )
)
async def on_bot_left(event: types.ChatMemberUpdated):
    """FR-6: бот удалён/вышел → профиль is_active=false."""
    return await _handle_bot_left(event)


@chat_lifecycle_router.my_chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_MEMBER >> IS_NOT_MEMBER
    )
)
async def on_bot_left_my(event: types.ChatMemberUpdated):
    """ASAP 7 (F5, P7-C-1): leave по my_chat_member-observer (см.
    on_bot_joined_my — собственный membership приходит только там)."""
    return await _handle_bot_left(event)


async def _handle_bot_left(event: types.ChatMemberUpdated):
    """Общая логика leave для chat_member/my_chat_member (ASAP 7 F5)."""
    user = event.old_chat_member.user
    if not _is_bot_user(user):
        return UNHANDLED                 # чужие события — другим роутерам
    chat_id = event.chat.id
    logger.info("[chat_lifecycle] bot left | chat_id=%s | status=%s",
                chat_id, event.old_chat_member.status)
    try:
        if _store is not None:
            await _store.set_active(chat_id, False)
    except Exception:
        logger.warning(
            "[chat_lifecycle] leave update failed — fail-open | chat_id=%s",
            chat_id, exc_info=True)
    return None


@chat_lifecycle_router.message(F.migrate_to_chat_id)
async def on_chat_migrated(message: types.Message):
    """FR-7: переезд чата — chat_links + migrate_profile (Q9-merge).
    Узкий service-хендлер; регистрируется ДО широких message-роутеров."""
    old_chat_id = message.chat.id
    new_chat_id = message.migrate_to_chat_id
    logger.info(
        "[chat_lifecycle] chat migrated | old=%s | new=%s",
        old_chat_id, new_chat_id)
    try:
        # MCA-03 (D6/REQ-MCA03-06): явный mapping chat_id по подтверждённым
        # метаданным Telegram (`migrate_to_chat_id` сервисного сообщения).
        # Отдельно от PG chat_links (SQLite canonical identity для MCA-03).
        if _db is not None:
            try:
                from services import message_identity as _mi
                await _mi.register_chat_id_migration(
                    _db, old_chat_id=old_chat_id, new_chat_id=new_chat_id,
                    evidence="telegram:migrate_to_chat_id")
                # MCA-17 (`chat.lifecycle`): терминал записи chat_id_migrations.
                _emit_lifecycle(
                    "chat_id_migration", "success", chat_id=new_chat_id,
                    entity_ids={"old_chat_id": old_chat_id})
            except Exception:
                _emit_lifecycle(
                    "chat_id_migration", "failed", level="WARN",
                    chat_id=new_chat_id,
                    entity_ids={"old_chat_id": old_chat_id})
                logger.warning(
                    "[chat_lifecycle] chat_id_migration record failed — "
                    "fail-open | old=%s new=%s", old_chat_id, new_chat_id,
                    exc_info=True)
        if _store is None:
            return UNHANDLED
        await _store.add_link(old_chat_id, new_chat_id)
        result = await _store.migrate_profile(
            old_chat_id=old_chat_id, new_chat_id=new_chat_id,
            changed_by=None)
        logger.info(
            "[chat_lifecycle] migrate_profile | old=%s | new=%s | %s",
            old_chat_id, new_chat_id, result)
        # ── ASAP 7 (F5, C9): профиль нового id при отсутствии — upsert +
        # set_active(True) (бот физически присутствует в supergroup —
        # сервисное сообщение доставлено ему). migrate_profile переносит/
        # мерджит существующую строку, но при отсутствии профиля old —
        # no-op → новый чат остался бы невидим в селекторе.
        try:
            if await _store.get_profile(new_chat_id) is None:
                await _store.upsert_profile_on_join(new_chat_id)
                await _store.set_active(new_chat_id, True)
                await ensure_gates_defaults(new_chat_id)
                logger.info(
                    "[chat_lifecycle] migrated chat profile created "
                    "| new=%s", new_chat_id)
            _profile_seen.discard(old_chat_id)
            _profile_seen.add(new_chat_id)
        except Exception:
            logger.warning(
                "[chat_lifecycle] migrated profile ensure failed — "
                "fail-open | old=%s new=%s", old_chat_id, new_chat_id,
                exc_info=True)
    except Exception:
        logger.warning(
            "[chat_lifecycle] migrate failed — fail-open | old=%s new=%s",
            old_chat_id, new_chat_id, exc_info=True)
    return None


# ── ASAP 7 (F5, P7-C-2): fallback-регистрация профиля группы ────────────
# Join-событие могло быть пропущено (даунтайм/эджи Bot API). Первое
# сообщение из group-чата без профиля → ensure_profile + set_active(True)
# (прецедент store.ensure_profile :373-386). Только chat_id<0; только при
# отсутствии профиля — позитивный кэш _profile_seen + backoff-память
# _fallback_last_try (не звать PG на каждое сообщение). Fail-open; гейт
# CHAT_PROFILE_FALLBACK_ENABLED (env, default ON, config/settings.py).

_FALLBACK_BACKOFF_SECONDS = 300.0
_profile_seen: set[int] = set()        # chat_id: профиль заведомо есть
_fallback_last_try: dict[int, float] = {}   # backoff неудачных/новых


class ChatProfileFallbackMiddleware(BaseMiddleware):
    """dp.update.outer_middleware — единая точка входа message-роутинга
    ДО диспетчеризации. Thin: handler-цепочку не меняет, ошибки ensure
    наружу не пробрасывает (hot-path не рвём)."""

    async def __call__(self, handler, event, data):
        try:
            await maybe_ensure_group_profile(event)
        except Exception:                 # страховка: fail-open всегда
            logger.debug(
                "[chat_lifecycle] fallback middleware skipped",
                exc_info=True)
        return await handler(event, data)


chat_profile_fallback_middleware = ChatProfileFallbackMiddleware()


def _extract_group_chat_id(update) -> int | None:
    """chat_id первого message-like поля Update; None если нет/не группа."""
    try:
        for attr in ("message", "edited_message", "channel_post",
                     "edited_channel_post"):
            msg = getattr(update, attr, None)
            if msg is not None:
                chat_id = getattr(getattr(msg, "chat", None), "id", None)
                if chat_id is not None and chat_id < 0:
                    return chat_id
                return None
    except Exception:
        return None
    return None


def reset_fallback_memory() -> None:
    """Тест-хук: очистка backoff-памяти между сценариями."""
    _profile_seen.clear()
    _fallback_last_try.clear()


async def maybe_ensure_group_profile(update) -> None:
    """Fallback-материализация профиля группового чата (P7-C-2).
    Никогда не бросает; идемпотентен (upsert + set_active(True))."""
    try:
        from config.settings import settings
        enabled = bool(settings.CHAT_PROFILE_FALLBACK_ENABLED)
    except Exception:
        enabled = True                    # гейт недоступен → fail-open ON
    if not enabled or _store is None:
        return
    chat_id = _extract_group_chat_id(update)
    if chat_id is None or chat_id in _profile_seen:
        return
    now = time.monotonic()
    last = _fallback_last_try.get(chat_id)
    if last is not None and (now - last) < _FALLBACK_BACKOFF_SECONDS:
        return
    _fallback_last_try[chat_id] = now
    try:
        if await _store.get_profile(chat_id) is not None:
            _profile_seen.add(chat_id)
            return
        await _store.ensure_profile(chat_id)
        await _store.set_active(chat_id, True)
        # Новый профиль → тот же hard opt-in gates-дефолт, что и при join
        # (:101-102); идемпотентно (гейт-дефолты только для пустых).
        await ensure_gates_defaults(chat_id)
        _profile_seen.add(chat_id)
        logger.info(
            "[chat_lifecycle] fallback profile registered | chat_id=%s",
            chat_id)
        _emit_lifecycle("chat_profile_fallback", "success", chat_id=chat_id)
    except Exception:
        logger.warning(
            "[chat_lifecycle] fallback ensure failed — fail-open "
            "| chat_id=%s", chat_id, exc_info=True)
        _emit_lifecycle("chat_profile_fallback", "failed", level="WARN",
                        chat_id=chat_id)
