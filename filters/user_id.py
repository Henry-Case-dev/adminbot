from aiogram.filters import BaseFilter
from aiogram.types import Message


class UserIdFilter(BaseFilter):
    """Passes only messages from specified user IDs. Works with ANY message type."""
    
    def __init__(self, *user_ids: int):
        self.user_ids = set(user_ids)
    
    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in self.user_ids
