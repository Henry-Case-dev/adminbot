"""F6 — Alan_Z Reply Engine.

Every ALAN_REPLY_INTERVAL (default: 10) messages from Alan (id 138811255),
the bot replies with a random phrase from the ALAN_REPLIES pool.

The pool covers topics Alan is passionate about: тренировки, лонгковид,
фьючерсы, нейросети, жим дьявола. Extensible — just add strings to the list.
"""
import logging
import random

from aiogram import Router, types

from filters.user_id import UserIdFilter
from config.settings import settings
from services.database import DatabaseService

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
