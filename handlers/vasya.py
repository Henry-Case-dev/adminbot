from aiogram import Router, types
from filters.vasya_name import VasyaFilter
from filters.admin_word import StrictAdminFilter

vasya_router = Router()


@vasya_router.message(VasyaFilter())
async def reply_to_vasya(message: types.Message):
    """If someone writes VASYA → reply ADMIN"""
    await message.reply("АДМИН")


@vasya_router.message(StrictAdminFilter())
async def reply_to_admin(message: types.Message):
    """If someone writes ADMIN → reply VASYA"""
    await message.reply("ВАСЯ")
