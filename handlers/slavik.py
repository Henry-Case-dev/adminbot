from aiogram import Router, types
from filters.user_id import UserIdFilter
from filters.kucha_word import KuchaWordFilter
from filters.war_word import WarWordFilter
from config.settings import settings

slavik_router = Router()


# Handler 1: F4 — KUCHA words → "ДАЛБАЕБ"
@slavik_router.message(KuchaWordFilter())
async def kucha_handler(message: types.Message):
    await message.reply("ДАЛБАЕБ")


# Handler 2: F5 — War words → "трясло ебаное"
@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID), WarWordFilter())
async def war_word_handler(message: types.Message):
    await message.reply("трясло ебаное")


# Handler 3: Catch-all → "пошёл нахуй" (original behavior)
@slavik_router.message(UserIdFilter(settings.SLAVIK_USER_ID))
async def slavik_catchall_handler(message: types.Message):
    await message.reply("пошёл нахуй")
