"""F6 — Alan_Z Reply Engine.

Every ALAN_REPLY_INTERVAL (default: 10) messages from Alan (id 138811255),
the bot replies with a random phrase from the ALAN_REPLIES pool.

The pool covers topics Alan is passionate about: тренировки, лонгковид,
фьючерсы, нейросети, жим дьявола. Extensible — just add strings to the list.
"""
import logging
import random
import time

from aiogram import Router, types

from filters.user_id import UserIdFilter
from config.settings import settings
from services.database import DatabaseService
from handlers.alan_greeting import _send_greeting, _last_greeting

logger = logging.getLogger(__name__)

alan_router = Router()
alan_db: DatabaseService | None = None

# ── Reply Pool ────────────────────────────────────────────
# Extensible: add new strings to extend the pool.
# Each reply shows extreme interest in Alan's favorite topics.
ALAN_REPLIES = [
    # Original 6 (provided by user)
    "так интересно, продолжай",
    "ух ты! а что еще расскажешь интересного? Давай что-нибудь про нейросети или тренировки!",
    "это лечит лонгковид?",
    "ВЪЕБИ ГОВНА СУКА",
    "как там колени?",
    "сколько процентов хп?",

    # ── Тренировки ──
    "а жим дьявола сегодня был? расскажи как прошло, я всё пропустил!",
    "сколько подходов на жим дьявола делаешь? я вот до сих пор плечи болят",
    "треня была? чё сегодня качали? рассказывай!",
    "слушай, а ты не пробовал присед с лонгковидом совмещать? говорят, дыхалка прокачивается",

    # ── Лонгковид ──
    "а лонгковид реально существует или это заговор бигфармы?",
    "у меня кажется лонгковид начался — поднимаюсь на пятый этаж и всё, труба",
    "как ты с лонгковидом справляешься? есть рабочие методы?",

    # ── Фьючерсы ──
    "чё по фьючерсам сегодня? шорт или лонг?",
    "фьючерсы в плюс закрыл? расскажи, мне тоже интересно!",
    "я тут график битка смотрел — треугольник вырисовывается. Чё думаешь, куда пойдёт?",
    "а на фьючерсах сейчас вообще можно заработать или всех выносят?",

    # ── Нейросети ──
    "а нейросети уже научились жим дьявола делать?",
    "слышал про новую нейронку? она там вообще огонь, расскажи что знаешь!",
    "а ты какую нейросетку юзаешь для анализа рынка? deepseek или chatgpt?",
    "нейросети когда-нибудь заменят трейдеров? или это хайп?",

    # ── Жим дьявола ──
    "жим дьявола — это вообще законно? выглядит как открытие портала в ад",
    "после жима дьявола лонгковид не возвращается?",
    "а техника жима дьявола сложнее чем обычный жим? расскажи!",

    # ── Смешанные ──
    "нейросети могут предсказать движение фьючерсов? или это всё ещё рандом?",
    "как ты успеваешь и тренироваться и за рынком следить? поделись тайм-менеджментом!",
    "если нейросеть напишет стратегию для фьючерсов, а я по ней жим дьявола сделаю — я выиграю?",
    "расскажи чё-нибудь интересное! можно про тренировки, можно про рынок — я весь во внимании",
]


def setup_alan(db: DatabaseService) -> None:
    """Inject database dependency. Called from bot.py on_startup()."""
    global alan_db
    alan_db = db


@alan_router.message(UserIdFilter(settings.ALAN_USER_ID))
async def alan_handler(message: types.Message) -> None:
    """Count Alan's messages and reply with random phrase every N messages."""
    if alan_db is None:
        return

    interval = settings.ALAN_REPLY_INTERVAL
    if interval <= 0:
        logger.warning("ALAN_REPLY_INTERVAL is %d — replies disabled", interval)
        return

    count = await alan_db.increment_and_get_count(
        message.chat.id, message.from_user.id
    )

    if count % interval == 0:
        reply_text = random.choice(ALAN_REPLIES)
        logger.debug("Alan reply #%d in chat %d: %s", count, message.chat.id, reply_text)
        await message.reply(reply_text)

    # ── F7v2: Silence Greeting (Epic 11) ──
    silence_hours = settings.ALAN_SILENCE_GREETING_HOURS
    if silence_hours <= 0:
        logger.debug(
            "F7v2: ALAN_SILENCE_GREETING_HOURS=%.1f — silence greeting disabled",
            silence_hours,
        )
    else:
        try:
            now = time.time()
            last_ts = await alan_db.get_alan_last_message_ts(message.chat.id)
            chat_id = message.chat.id

            if last_ts is not None:
                elapsed = now - last_ts
                threshold = silence_hours * 3600
                if elapsed >= threshold:
                    # Check shared anti-spam cooldown with F7 join greeting
                    cooldown_ok = True
                    if chat_id in _last_greeting:
                        since_last = now - _last_greeting[chat_id]
                        if since_last < settings.ALAN_GREETING_COOLDOWN:
                            cooldown_ok = False
                            logger.info(
                                "F7v2: silence greeting for chat %d suppressed by shared cooldown "
                                "(%.1fs since last greeting, cooldown=%ds)",
                                chat_id, since_last, settings.ALAN_GREETING_COOLDOWN,
                            )

                    if cooldown_ok:
                        logger.info(
                            "F7v2: silence greeting triggered | chat=%d | elapsed=%.1fh | threshold=%.1fh",
                            chat_id, elapsed / 3600, silence_hours,
                        )
                        success = await _send_greeting(message.bot, chat_id)
                        if success:
                            _last_greeting[chat_id] = now
                            logger.info(
                                "F7v2: silence greeting sent | chat=%d | elapsed=%.1fh",
                                chat_id, elapsed / 3600,
                            )
                        else:
                            logger.warning(
                                "F7v2: silence greeting send failed | chat=%d", chat_id,
                            )
                else:
                    logger.info(
                        "F7v2: silence threshold not reached | chat=%d | elapsed=%.1fh | threshold=%.1fh "
                        "— timer reset without greeting",
                        chat_id, elapsed / 3600, silence_hours,
                    )
            else:
                logger.info(
                    "F7v2: first message from Alan in chat %d — baseline recorded, no greeting",
                    chat_id,
                )

            await alan_db.set_alan_last_message_ts(chat_id, now)
            logger.debug(
                "F7v2: updated last message timestamp for chat %d to %.0f",
                chat_id, now,
            )

        except Exception:
            logger.exception(
                "F7v2: error in silence greeting logic | chat=%d",
                message.chat.id,
            )
