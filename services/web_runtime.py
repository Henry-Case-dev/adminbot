"""UI-полировка TMA — runtime-держатель Bot для web-API.

Единый инстанс aiogram Bot создаётся модульно в bot.py (bot = Bot(...)
на уровне модуля) и внедряется сюда ПЕРЕД стартом FastAPI: bot.py main()
вызывает `set_web_bot(bot)` рядом с `app = create_app(cache, ...)`.
Чтение — модульным геттером get_web_bot(): аватар-прокси
(web/api/avatars.py) и обогащение /api/chat_lore/* (title/username/фото
чатов и участников) ходят в Bot API ТОЛЬКО через него.

None — бот не установлен (тесты/стендалон-режим/сам web-server без
polling): вызывающие fail-open — 404 (аватар) / None-поля (обогащение).
"""
import logging

logger = logging.getLogger(__name__)

_bot = None
_summary_generator = None


def set_web_bot(bot) -> None:
    """Внедрение Bot (bot.py main() перед create_app / тесты)."""
    global _bot
    _bot = bot


def set_summary_generator(generator) -> None:
    """S9 (ADR-1026-8 D1): внедрение SummaryGenerator для dry-run тест-контура.

    Зеркало ``set_web_bot``: bot.py вызывает после создания генератора; web-API
    берёт его через ``get_summary_generator`` (тест-прогон читает окно read-only
    и вызывает run_l1/run_l2 — без публикации/записи).
    """
    global _summary_generator
    _summary_generator = generator


def reset_web_runtime() -> None:
    """Полный сброс (shutdown/тесты)."""
    global _bot, _summary_generator
    _bot = None
    _summary_generator = None


def get_web_bot():
    """Bot для web-API (аватары/обогащение); None — не установлен."""
    return _bot


def get_summary_generator():
    """SummaryGenerator для dry-run тест-контура; None — не установлен."""
    return _summary_generator
