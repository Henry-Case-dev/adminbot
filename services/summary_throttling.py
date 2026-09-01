"""Epic 24/25 — ThrottlingMiddleware for /summary (R10, Sections 33.11 + 34.4).

Router-scoped outer middleware on summary_router only. In-memory TTL storage,
key = (chat_id, user_id). On spam: handler НЕ вызывается, вместо тишины —
случайная фраза-отборка из _THROTTLE_PHRASES с реальным оставшимся временем
(Epic 31, R31-3/D96/D97/D98).

Epic 25 (B3): mentions are validated against the bot username, symmetric to
aiogram's Command filter — a command addressed to ANOTHER bot does NOT consume
the throttle slot. Own mention (/summary@НашБот) throttles like plain /summary.
"""
import logging
import math
import random
import time

from aiogram import BaseMiddleware
from aiogram.types import Message

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# R31-3 (D96): 7 фраз, плейсхолдер {remaining}. 2 канона пользователя ДОСЛОВНО
# (первыми) + 5 новых PM (стиль-гард как D82: маленькие буквы, без эмодзи).
# Расширение пула = новая строка в кортеже.
_THROTTLE_PHRASES: tuple[str, ...] = (
    "хули ты дрочишь, подожди {remaining}",              # канон 1 (D96)
    "угомонись нахуй, не можешь {remaining} подождать?", # канон 2 (D96)
    "куда ты ломишься, {remaining} ещё не прошло",
    "остынь, дрыщ, саммари варится ещё {remaining}",
    "ты че, в сотый раз жмёшь? потерпи {remaining}",
    "хватит тыкать, через {remaining} вернёшься — не отсохнет",
    "твоё саммари в печи, дай ему {remaining} допечься",
)


def _pluralize(n: int, forms: tuple[str, str, str]) -> str:
    """Русская плюрализация: forms = (одна, две, много). 21 → «секунда», 11 → «секунд»."""
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return forms[0]
    if n10 in (2, 3, 4) and n100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


def format_remaining_seconds(seconds: float) -> str:
    """D97: ceil вверх; <60с → «N секунда/секунды/секунд»; ≥60с → «N минута/минуты/минут».

    Примеры: 60.0 → «1 минута», 25.0 → «25 секунд», 0.4 → «1 секунда».
    """
    total = max(1, math.ceil(seconds))          # guard: в ветке троттлинга remaining > 0 всегда
    if total < 60:
        return f"{total} {_pluralize(total, ('секунда', 'секунды', 'секунд'))}"
    minutes = math.ceil(total / 60)             # целые минуты, ceil (90с → «2 минуты»)
    return f"{minutes} {_pluralize(minutes, ('минута', 'минуты', 'минут'))}"


def _parse_command(text: str) -> tuple[str, str | None]:
    """Split the first token into (base, mention): '/summary@Bot' → ('/summary', 'bot')."""
    token = text.split()[0]
    base, _, mention = token.partition("@")
    return base, (mention.lower() if mention else None)


class ThrottlingMiddleware(BaseMiddleware):
    """Drops repeated /summary commands within the throttle window (reply-фраза вместо тишины, Epic 31)."""

    def __init__(self, throttle_seconds: float | None = None) -> None:
        # N1: middleware создаётся в setup_summary() (on_startup, ПОСЛЕ
        # set_config_cache) — hot.get читает живое значение из кэша (не
        # бейкдится при импорте). None → фолбек на settings.
        if throttle_seconds is None:
            throttle_seconds = hot.get("limits.summary_throttle_seconds",
                                       settings.SUMMARY_THROTTLE_SECONDS)
        self._throttle_seconds = throttle_seconds
        self._last: dict[tuple[int, int], float] = {}

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and (event.text or "").strip():
            base, mention = _parse_command(event.text)
            # B3: точное сравнение — /summaryfoo не матчится (полная симметрия с Command)
            if base == "/summary":
                if mention:
                    bot = data.get("bot")
                    me = await bot.me() if bot is not None else None
                    if (
                        me is not None
                        and getattr(me, "username", None)
                        and mention != str(me.username).lower()
                    ):
                        # чужая команда — слот НЕ потребляем, событие идёт дальше
                        # (Command-фильтр сам корректно отклонит чужую mention)
                        return await handler(event, data)
                key = (event.chat.id, event.from_user.id if event.from_user else 0)
                now = time.monotonic()
                last = self._last.get(key)
                if last is not None and (now - last) < self._throttle_seconds:
                    remaining = self._throttle_seconds - (now - last)
                    logger.info(                                  # аккуратность лога НЕ меняем (D97)
                        "[/summary] throttled | chat=%s user=%s remaining=%.0fs",
                        *key, remaining,
                    )
                    phrase = random.choice(_THROTTLE_PHRASES).format(
                        remaining=format_remaining_seconds(remaining)
                    )
                    try:
                        await event.reply(phrase)                 # reply на сообщение юзера
                    except Exception:
                        logger.warning(                           # best-effort: не ронять propagation
                            "[/summary] throttled reply failed | chat=%s user=%s",
                            *key, exc_info=True,
                        )
                    return                                        # хендлер НЕ вызывается (семантика троттлинга)
                self._last[key] = now
        return await handler(event, data)
