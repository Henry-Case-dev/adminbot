from aiogram.filters import BaseFilter
from aiogram.types import Message, MessageOriginChannel


class TargetChannelFilter(BaseFilter):
    """
    Filter that matches only forwarded messages from target military channels.

    Solves: F.forward_origin matched ALL forwarded messages and blocked
    propagation to common_router. Non-target forwarded → filter returns
    False → handler not called → propagation continues.
    """

    def __init__(
        self,
        target_channel_ids: set[int] | None = None,
        target_channel_usernames: set[str] | None = None,
    ):
        self.target_channel_ids = target_channel_ids or set()
        self.target_channel_usernames = target_channel_usernames or set()

    async def __call__(self, message: Message) -> bool:
        origin = message.forward_origin
        if not isinstance(origin, MessageOriginChannel):
            return False

        if origin.chat.id in self.target_channel_ids:
            return True

        if origin.chat.username and origin.chat.username.lower() in self.target_channel_usernames:
            return True

        return False
