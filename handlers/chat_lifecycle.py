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

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER

logger = logging.getLogger(__name__)

chat_lifecycle_router = Router(name="chat_lifecycle")

_store = None          # ChatLoreStore (DI из bot.py)
_bot_id = None         # bot.id (DI из bot.py; None → сравнение отключено)


def setup_chat_lifecycle(store, bot_id: int | None = None):
    """Called from bot.py to inject dependencies (прецедент setup_presence)."""
    global _store, _bot_id
    _store = store
    _bot_id = bot_id


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
        if _store is None:
            return UNHANDLED
        await _store.add_link(old_chat_id, new_chat_id)
        result = await _store.migrate_profile(
            old_chat_id=old_chat_id, new_chat_id=new_chat_id,
            changed_by=None)
        logger.info(
            "[chat_lifecycle] migrate_profile | old=%s | new=%s | %s",
            old_chat_id, new_chat_id, result)
    except Exception:
        logger.warning(
            "[chat_lifecycle] migrate failed — fail-open | old=%s new=%s",
            old_chat_id, new_chat_id, exc_info=True)
    return None
