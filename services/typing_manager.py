"""Epic 60 Фаза C (Section 65.7, R60-16, T-475) — индикатор «печатает…».

Готовый ChatActionSender из aiogram 3.29.1 (вердикт T-459 тема 2): своя
фоновая задача НЕ пишется. `typing_active` — async context manager; обёртка
вокруг LLM-точки (от отправки контекста в ИИ до отправки ответа). БЕЗ
искусственной паузы.

Сброс НЕ нужен: (а) индикатор гаснет сам ≤5с после последнего sendChatAction
(выход из блока останавливает фоновую таску), (б) НЕМЕДЛЕННО при отправке
ботом любого сообщения. При зависшем LLM выход из блока — по
asyncio.TimeoutError (LLM_TOTAL_BUDGET в llm_client) — «вечно печатает»
невозможен. Ошибки send_chat_action внутри ChatActionSender — WARNING,
контекст продолжает работать.

Выключатель TYPING_INDICATOR_ENABLED (default true): false → nullcontext
(блок не создаётся — ровно старое поведение). TYPING_INTERVAL_SECONDS
(default 5.0 — под TG-таймаут 5с).
"""
from contextlib import nullcontext

from aiogram.utils.chat_action import ChatActionSender

from config.settings import settings
from services import hot_config as hot


def typing_active(bot, chat_id: int):
    """async context manager 'typing…' (65.7). ChatActionSender сам шлёт
    action каждые TYPING_INTERVAL_SECONDS до выхода из блока."""
    if bot is None or not hot.get("flags.typing_indicator_enabled", settings.TYPING_INDICATOR_ENABLED):
        return nullcontext()
    return ChatActionSender.typing(
        bot=bot,
        chat_id=chat_id,
        interval=hot.get("limits.typing_interval_seconds", settings.TYPING_INTERVAL_SECONDS),
    )
