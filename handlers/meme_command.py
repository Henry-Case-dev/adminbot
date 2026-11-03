"""MEME-PIPELINE-REFactor-01 §4 — админская диагностическая команда ``/meme``.

Ручной запуск СУЩЕСТВУЮЩЕГО мем-пайплайна
(``services.meme_initiative.consider_chat(..., manual=True)``): второй ветки
генерации нет (§6 ТЗ), меняется только слой вызова, прав и доставки.

Замороженный порядок обработчика (``arch/integration-decisions.md`` §10.1):

1. RBAC — существующий механизм ``services.roles.access_for`` плюс прямой
   ``settings.ADMIN_USER_ID`` (§4). Не-админу — полная тишина: ни ответа, ни
   удаления его сообщения, ни генерации.
2. Разбор команды (``Command("meme")``; аргументы не используются).
3. Удаление сообщения команды — ПЕРВОЕ сетевое действие обработчика, до
   любого этапа пайплайна: след исчезает сразу, даже если пайплайн идёт
   десятки секунд или падает (дополнение владельца 03.11.2026).
4. Маркер приоритета ``manual_priority_until`` ОДНИМ стейтментом — ДО
   генерации (INIT-COORD §6): с этого момента автоматический путь не может
   перейти в ``sending``, приоритет заявлен атомарно, а не «после отправки».
5. Пайплайн: ``consider_chat(db, chat_id, manual=True, ...)``.
6. Доставка: успех — только изображение (путь ``sender`` не меняется), сбой —
   ровно одно короткое сообщение без кодов, промпта, выжимки и прикола.

Автоудаление best-effort: ровно ОДИН ``message.delete()`` с ограниченным
ожиданием; любой исход (403, >48 ч, сеть, уже удалено, таймаут) переживаем,
сбой остаётся только в логе (WARNING без traceback), пайплайн от него не
зависит, добивающих фоновых задач нет. Ответ уходит НОВЫМ сообщением в тот же
чат без reply-цели, поэтому доставка не зависит от исхода удаления.

Команда нигде не рекламируется: в меню ``/`` и справку не добавляется
(``services/bot_commands.py`` не трогаем).
"""
import asyncio
import logging

from aiogram import Router, types
from aiogram.filters import Command

from config.settings import settings

logger = logging.getLogger(__name__)

meme_command_router = Router()

#: Предел ожидания удаления сообщения команды (arch §10.1): зависший сетевой
#: вызов не отодвигает старт пайплайна.
DELETE_TIMEOUT_SECONDS = 5.0

#: Код причины → одно короткое бытовое сообщение. Коды, промпт, выжимка и
#: прикол в чат не попадают (arch §4): только причина, понятная человеку.
_FAILURE_TEXT = {
    "image_module_off": "Генерация картинок выключена.",
    "image_provider_not_configured": "Провайдер картинок не настроен.",
    "image_provider_unhealthy": "Провайдер картинок сейчас недоступен.",
    "summary_failed": "Не получилось собрать выжимку из переписки.",
    "joke_generation_failed": "Не получилось придумать прикол.",
    "joke_empty": "Не получилось придумать прикол.",
    "no_joke_budget": "Шаблон картинки не оставил места для прикола.",
    "template_empty": "Шаблон промпта картинки не задан.",
    "image_generation_failed": "Провайдер картинок не отдал изображение.",
    "low_activity": "В чате слишком мало сообщений для мема.",
    "schema_absent": "Журнал мемов ещё не инициализирован.",
    "length_limit_unknown": "Не удалось определить лимит длины промпта.",
    "publish_blocked": "Отправка мема не удалась.",
    # INIT-COORD: координация с автоматическими публикациями.
    "publication_in_flight": ("В этом чате уже идёт отправка — "
                              "попробуйте через минуту."),
    "publication_conflict": ("Публикация не сделана: в чате одновременно "
                             "идёт другой инициативный пост."),
    "publication_expired": ("Бронь публикации истекла — попробуйте ещё раз."),
    # P0 03.11.2026: готовый мем больше НЕ отменяется из-за нового сообщения
    # в чате — этот текст остаётся только для исторического кода журнала.
    "publication_stale": ("Готовый мем не отправлен: результат потерял "
                          "актуальность."),
    "source_material_gone": ("Исходные сообщения этого мема удалены из чата — "
                             "отправлять нечего."),
}
#: Ничего конкретного сказать нельзя — общая короткая фраза без внутренностей.
_GENERIC_FAILURE = "Мем не получился. Попробуйте позже."

_db = None
_llm = None
_bot = None
_pipeline_seams: dict = {}


def setup_meme_command(db, llm, bot, *, pipeline_seams: dict | None = None) -> None:
    """DI из ``bot.py``: БД, LLM-клиент, бот.

    ``pipeline_seams`` — швы ``consider_chat`` для тестов (продакшн передаёт
    пусто, значения по умолчанию берёт сам пайплайн).
    """
    global _db, _llm, _bot, _pipeline_seams
    _db = db
    _llm = llm
    _bot = bot
    _pipeline_seams = dict(pipeline_seams or {})


async def is_meme_admin(user_id, chat_id) -> bool:
    """RBAC команды: ``is_global_admin`` / ``is_local_admin`` / ADMIN_USER_ID.

    Права НЕ обходятся: это тот же ``roles.access_for``, что у остальных
    админских точек. Ошибка проверки доступа = отказ (не 500 в чат).
    """
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        return False
    if not uid:
        return False
    admin_id = int(getattr(settings, "ADMIN_USER_ID", 0) or 0)
    if admin_id and uid == admin_id:
        return True
    try:
        from services import roles
        ctx = await roles.access_for(
            uid, int(chat_id) if chat_id is not None else None)
    except Exception:
        logger.warning("[/meme] access check failed | user=%s chat=%s",
                       uid, chat_id)
        return False
    return bool(getattr(ctx, "is_global_admin", False)
                or getattr(ctx, "is_local_admin", False))


async def delete_command_message(message) -> bool:
    """Одно best-effort удаление сообщения команды.

    Исключение не выходит наружу, повторных попыток и добивающих задач нет:
    сбой виден в логе ОДНИМ WARNING с типом исключения и без traceback.
    """
    chat_id = int(getattr(message.chat, "id", 0) or 0)
    message_id = int(getattr(message, "message_id", 0) or 0)
    try:
        await asyncio.wait_for(message.delete(), DELETE_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.warning("[/meme] command delete failed (%s) | chat=%s msg=%s",
                       type(exc).__name__, chat_id, message_id)
        return False
    logger.info("[/meme] command deleted | chat=%s msg=%s", chat_id, message_id)
    return True


def _sender(bot):
    """Доставка — тот же binding, что у авто-инициативы (§6): только фото.

    Переиспользуется существующий путь вместо копии: правило «успех = только
    изображение, без caption и без follow-up» остаётся в одном месте.
    """
    from services.initiative_observer import InitiativeObserverRunner
    return InitiativeObserverRunner(None, bot=bot)._meme_sender()


async def claim_manual_priority(chat_id: int) -> int:
    """Маркер приоритета ручного запуска ДО генерации (INIT-COORD §6).

    Один стейтмент по таблице брони: автоматический путь в этом чате не сможет
    перейти ``claimed → sending``, пока маркер жив (``MANUAL_PRIORITY_SECONDS``).
    Нет БД/таблицы → 0: приоритет не заявлен, и это видно в логе, а не
    превращается в тихую блокировку ручной команды.
    """
    if _db is None:
        return 0
    try:
        from services import publication_coordination as pub
        coordinator = pub.PublicationCoordinator(_db)
        return await coordinator.claim_manual_priority(int(chat_id))
    except Exception:
        logger.warning("[/meme] manual priority marker failed | chat=%s",
                       chat_id, exc_info=True)
        return 0


async def run_manual_pipeline(chat_id: int, bot, *, request_ref: str = ""):
    """Один ручной проход существующего пайплайна (``manual=True``).

    ``manual=True`` обходит суточную квоту, кулдаун, минимум сообщений,
    случайный триггер, тихие часы, in-flight и гейт публикации; НЕ обходит
    RBAC, готовность image-модуля/провайдера, наличие журнала, разрешимость
    бюджета и контракт доставки (arch §4).

    ``request_ref`` — id сообщения ``/meme``: попадает в снапшот источника и
    в события попытки (run/correlation). Сам мем уходит НОВЫМ сообщением:
    сообщение команды удаляется до генерации (arch §10.1), поэтому reply-цели
    у доставки нет — это ограничение существующего транспорта, а не отказ от
    доставки готового мема.

    ``prompt_override`` не передаётся: шаблон берётся из слоёв настроек, иначе
    ``L`` считался бы без потолка модели (ревью P1, п.5).
    """
    from services import meme_initiative as meme
    params: dict = {
        "manual": True,
        "llm": _llm,
        "sender": _sender(bot),
        "ledger": meme.open_ledger(_db) if _db is not None else None,
        "request_ref": str(request_ref or ""),
    }
    params.update(_pipeline_seams)
    return await meme.consider_chat(_db, int(chat_id), **params)


async def _report_failure(bot, chat_id: int, reason: str = "") -> None:
    """Ровно одно короткое сообщение об ошибке новым сообщением, без reply."""
    text = _FAILURE_TEXT.get(str(reason or ""), _GENERIC_FAILURE)
    if bot is None:
        logger.warning("[/meme] no bot to report failure | chat=%s", chat_id)
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        logger.warning("[/meme] failure notice not delivered (%s) | chat=%s",
                       type(exc).__name__, chat_id)


@meme_command_router.message(Command("meme"))
async def cmd_meme(message: types.Message) -> None:
    """``/meme`` — ручная диагностика мем-пайплайна (только админ)."""
    chat_id = int(getattr(getattr(message, "chat", None), "id", 0) or 0)
    if not chat_id:
        return
    user = getattr(message, "from_user", None)
    user_id = int(getattr(user, "id", 0) or 0)
    if not await is_meme_admin(user_id, chat_id):
        # Полная тишина: чужое сообщение не трогаем и не подтверждаем, что
        # такая команда вообще существует.
        logger.debug("[/meme] non-admin rejected | user=%s chat=%s",
                     user_id, chat_id)
        return

    # Первое сетевое действие: след команды исчезает до любого этапа.
    await delete_command_message(message)

    # Приоритет заявлен ДО генерации: автоматический путь уже не сможет
    # перейти в `sending`, пока маркер жив (INIT-COORD §6).
    await claim_manual_priority(chat_id)

    bot = _bot if _bot is not None else getattr(message, "bot", None)
    request_ref = str(getattr(message, "message_id", 0) or "")
    try:
        result = await run_manual_pipeline(chat_id, bot, request_ref=request_ref)
    except Exception as exc:
        # Пайплайн обязан деградировать сам; сюда приходит только сбой моста
        # (журнал/БД) — в чат уходит одно короткое сообщение, без внутренностей.
        logger.warning("[/meme] manual run raised (%s) | chat=%s",
                       type(exc).__name__, chat_id)
        await _report_failure(bot, chat_id)
        return

    if result is not None and bool(getattr(result, "published", False)):
        return  # успех = только изображение, отправленное sender'ом пайплайна

    reason = str(getattr(result, "reason", "") or "")
    logger.info("[/meme] not published | chat=%s | stage=%s | reason=%s",
                chat_id, str(getattr(result, "stage", "") or ""), reason)
    await _report_failure(bot, chat_id, reason)
