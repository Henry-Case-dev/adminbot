"""Epic 31 (R31-2/D95) — регистрация меню команд через Bot API setMyCommands.

BotFather НЕ нужен: setMyCommands полностью заменяет список команд бота для
заданного scope (40.1). Меню «/» — подсказка/UX; на ВОЗМОЖНОСТЬ вызова команды
не влияет — доступ решает allow-check в cmd_summary (D94), а не scope.
"""
import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault

logger = logging.getLogger(__name__)

# D95: только /summary (v1). setMyCommands ЗАМЕНЯЕТ весь список — админ-команды
# /deadpage, /alangreet в меню сознательно НЕ выносим (скрытые тестовые).
_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(
        command="summary",
        description="Пересказ последнего дня в личных сообщениях, если включены",
    ),
    BotCommand(
        command="info",
        description="Справка о боте",      # Epic 43 (R43-1)
    ),
    BotCommand(
        command="menu",
        description="Меню бота — открыть мини-апп",   # Задание B (2026-09-03)
    ),
)


async def setup_bot_commands(bot: Bot) -> bool:
    """Register bot command menu. Best-effort: сбой API не роняет старт.

    Идемпотентно: setMyCommands перезаписывает список — повторный вызов на
    каждом старте безвреден. Returns True при успехе (маркер для T-241-D).
    """
    try:
        # language_code НЕ задаём (D95): иначе меню скрыто от юзеров с не-русской
        # локалью Telegram, а ТЗ — «доступна любому юзеру».
        await bot.set_my_commands(
            commands=list(_COMMANDS),
            scope=BotCommandScopeDefault(),   # default: все чаты, все юзеры
        )
        logger.info(
            "Bot commands registered (set_my_commands ok): %s",
            [c.command for c in _COMMANDS],
        )
        return True
    except Exception:
        logger.exception("Failed to register bot commands (set_my_commands)")
        return False
