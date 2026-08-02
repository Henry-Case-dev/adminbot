"""Эмпирическая проверка РЕАЛЬНОГО кода репозитория: имитируем цепочку роутеров
war_alert_router -> common_router -> slavik_router -> vasya_router, как в bot.py,
и проверяем, действительно ли danger_handler срабатывает для сообщения "ракета".
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, r"C:\Code\Python\adminbot")

from aiogram import Router
from aiogram.types import Message

from handlers.war_alert import war_alert_router, setup_war_alert
from handlers.common import common_router, setup_common
from handlers.slavik import slavik_router, setup_slavik
from handlers.vasya import vasya_router
from config.settings import settings

setup_war_alert()

sent_calls = []


class FakeRelay:
    async def send_common(self, chat_id, message_id, matched_word, subdir):
        sent_calls.append(("common", subdir, matched_word, chat_id, message_id))


setup_common(FakeRelay())


class FakeDB:
    async def slavic_photo_count_tick(self, chat_id, interval):
        return False


setup_slavik(FakeDB())

# Собираем roots как в bot.py
root = Router(name="root")
root.include_router(war_alert_router)
root.include_router(common_router)
root.include_router(slavik_router)
root.include_router(vasya_router)


def make_message(text, user_id, chat_id=100, message_id=1):
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.caption = None
    msg.forward_origin = None
    msg.media_group_id = None
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = chat_id
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.reply = AsyncMock()
    msg.bot = MagicMock()
    return msg


async def main():
    print("SLAVIK_USER_ID =", settings.SLAVIK_USER_ID)

    # Case 1: обычное сообщение "ракета" от НЕ-Славы
    sent_calls.clear()
    msg1 = make_message("ракета летит", user_id=999999, message_id=1)
    result1 = await root.propagate_event("message", msg1)
    print("Case1 (non-slavik, 'ракета летит'): result=", result1, "sent_calls=", sent_calls, "reply_called=", msg1.reply.called)

    # Case 2: сообщение "ракета" ОТ Славы
    sent_calls.clear()
    msg2 = make_message("ракета летит", user_id=settings.SLAVIK_USER_ID, message_id=2)
    result2 = await root.propagate_event("message", msg2)
    print("Case2 (slavik, 'ракета летит'): result=", result2, "sent_calls=", sent_calls, "reply_called=", msg2.reply.called, "reply_args=", msg2.reply.call_args)

    # Case 3: сообщение "отбой" от НЕ-Славы
    sent_calls.clear()
    msg3 = make_message("отбой", user_id=999999, message_id=3)
    result3 = await root.propagate_event("message", msg3)
    print("Case3 (non-slavik, 'отбой'): result=", result3, "sent_calls=", sent_calls)

    # Case 4: сообщение с ОБОИМИ словами "отбой" и "ракета" от НЕ-Славы
    sent_calls.clear()
    msg4 = make_message("отбой, ракета летит", user_id=999999, message_id=4)
    result4 = await root.propagate_event("message", msg4)
    print("Case4 (non-slavik, 'отбой ракета'): result=", result4, "sent_calls=", sent_calls)

    # Case 5: приватный чат (ЛС), просто chat.type
    sent_calls.clear()
    msg5 = make_message("бпла", user_id=999999, message_id=5)
    msg5.chat.type = "private"
    result5 = await root.propagate_event("message", msg5)
    print("Case5 (private DM, 'бпла'): result=", result5, "sent_calls=", sent_calls)


asyncio.run(main())
