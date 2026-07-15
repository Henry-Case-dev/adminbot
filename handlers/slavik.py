from aiogram import Router, types
from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from config.settings import settings

slavik_router = Router()


# Handler 1: F4 — KUCHA words → "ДАЛБАЕБ"
@slavik_router.message(KuchaWordFilter())
async def kucha_handler(message: types.Message):
    await message.reply("ДАЛБАЕБ")


# Handler 2: Catch-all → "пошёл нахуй" (original behavior)
# Note: F5 (war words) moved to war_alert_router at position 4b (Epic 10)
@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
async def slavik_catchall_handler(message: types.Message):
    await message.reply("пошёл нахуй")
