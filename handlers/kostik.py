"""F7 — Kostik Reply Engine.

Replies to Kostik's messages (id 350803143) with configurable probability
and a random phrase from the KOSTIK_REPLIES pool. Extensible — just add
strings to the list.

Probability: KOSTIK_REPLY_PROBABILITY in settings (0.0–1.0, default 1.0).
- 1.0 = reply to every message (legacy behavior)
- 0.5 = reply to ~50% of messages
- 0.0 = never reply
"""
import logging
import random

from aiogram import Router, types

from filters.user_id import UserIdFilter
from config.settings import settings

logger = logging.getLogger(__name__)

kostik_router = Router()

# ── Reply Pool ────────────────────────────────────────────
# Extensible: add new strings to extend the pool.
# Each reply is a colorful insult directed at Kostik.
KOSTIK_REPLIES = [
    "пошёл нахуй кринжатура ебаная",
    "кринжанул опять, кринжатура",
    "завали ебало, кринж",
    "ты чё несёшь, кринжатина",
    "ну ты и кринжатура, Kostik",
    "закрой рот, кринжовый",
    "опять ты со своим кринжом",
    "кринжуешь, Костик, кринжуешь",
]


@kostik_router.message(UserIdFilter(settings.KOSTIK_USER_ID))
async def kostik_handler(message: types.Message) -> None:
    """Reply to Kostik with configurable probability using random phrase."""
    prob = settings.KOSTIK_REPLY_PROBABILITY

    if prob <= 0.0:
        return

    if prob >= 1.0 or random.random() < prob:
        reply_text = random.choice(KOSTIK_REPLIES)
        logger.debug("Kostik reply (prob=%.2f): %s", prob, reply_text)
        await message.reply(reply_text)
