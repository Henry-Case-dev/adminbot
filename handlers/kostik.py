"""F7 — Kostik Reply Engine.

Replies to Kostik's messages (id 350803143) with configurable probability
and a random phrase from the configurable pool
(`reactions.kostik_replies`, widget=list в PERMsoc → блок «Костик»).
Канон-дефолт — `config.settings.DEFAULT_KOSTIK_REPLIES` (4 фразы владельца
+ 10 в том же духе). Пустой список → безопасное молчание.

Probability: limits.kostik_reply_probability (0.0–1.0, default 1.0).
- 1.0 = reply to every message (legacy behavior)
- 0.5 = reply to ~50% of messages
- 0.0 = never reply
"""
import json
import logging
import random

from aiogram import Router, types

from filters.user_id import UserIdFilter
from config.settings import settings
from services import hot_config as hot
# Раунд 10 (F-9 B2): «Костя» — модуль плагина PERMsoc (гейт первой).
from services.permsoc import PermsocGateFilter

logger = logging.getLogger(__name__)

kostik_router = Router()

# Backward-compat thin-alias (тесты/импорты). Канон — settings.KOSTIK_REPLIES
# (раунд 10.12, ADR-1012-1 D4: литерал вынесен в каталог).
KOSTIK_REPLIES = tuple(settings.KOSTIK_REPLIES)


def _resolve_replies(raw) -> list[str]:
    """Нормализация настройки `reactions.kostik_replies`.

    Принимает list/tuple (PG-массив), JSON-строку или мусор. Возвращает
    список непустых `str` со strip. Пустой/битый вход → [] (Костик молчит,
    сбоя нет)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append(text)
    return out


@kostik_router.message(PermsocGateFilter("kostik"),
                       UserIdFilter(hot.get("reactions.kostik_user_id", settings.KOSTIK_USER_ID)))
async def kostik_handler(message: types.Message) -> None:
    """Reply to Kostik with configurable probability using random phrase.
    T-619: вероятность — горячая точка (фолбек settings).
    Раунд 10.12: фразы — `hot.get("reactions.kostik_replies", default)`."""
    prob = hot.get("limits.kostik_reply_probability",
                   settings.KOSTIK_REPLY_PROBABILITY)

    if prob <= 0.0:
        return

    if prob >= 1.0 or random.random() < prob:
        phrases = _resolve_replies(
            hot.get("reactions.kostik_replies", settings.KOSTIK_REPLIES))
        if not phrases:
            return                       # пустой список — безопасное молчание
        reply_text = random.choice(phrases)
        logger.debug("Kostik reply (prob=%.2f): %s", prob, reply_text)
        await message.reply(reply_text)
