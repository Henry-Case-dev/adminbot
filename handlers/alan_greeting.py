"""
F7 — Alan Greeting Video.

When Alan (id 138811255) joins the chat, the bot picks a random video
from media/leha_greeting/ and sends it via send_video with caption "@Alan_Z".
"""
import glob
import logging
import os
import random
import time

from aiogram import F, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.filters import ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import FSInputFile

from config.settings import settings

logger = logging.getLogger(__name__)

alan_greeting_router = Router()

_last_greeting: dict[int, float] = {}

_VIDEO_EXTENSIONS = {".mp4", ".MP4", ".avi", ".AVI", ".mov", ".MOV", ".webm", ".WEBM"}


def _pick_random_greeting() -> str | None:
    greeting_dir = settings.ALAN_GREETING_DIR
    logger.debug("Scanning greeting directory: %s", greeting_dir)

    if not os.path.isdir(greeting_dir):
        logger.warning("Greeting directory does not exist: %s", greeting_dir)
        return None

    all_files = glob.glob(os.path.join(greeting_dir, "*"))
    logger.debug("Found %d total files in %s", len(all_files), greeting_dir)

    videos = [f for f in all_files 
              if os.path.isfile(f) and os.path.splitext(f)[1] in _VIDEO_EXTENSIONS]
    logger.debug("Found %d video files: %s", len(videos), videos)

    if not videos:
        logger.warning("No video files found in %s (supported: %s)", greeting_dir, _VIDEO_EXTENSIONS)
        return None

    chosen = random.choice(videos)
    logger.info("Randomly selected greeting video: %s", chosen)
    return chosen


async def _send_greeting(bot, chat_id: int) -> bool:
    logger.info("Preparing greeting video for chat %d", chat_id)

    video_path = _pick_random_greeting()
    if video_path is None:
        logger.warning("No greeting videos available for chat %d", chat_id)
        return False

    try:
        logger.debug("Sending video %s to chat %d with caption '%s'", video_path, chat_id, settings.ALAN_USERNAME)
        await bot.send_video(
            chat_id=chat_id,
            video=FSInputFile(video_path),
            caption=settings.ALAN_USERNAME,
        )
        logger.info("Greeting video sent successfully to chat %d", chat_id)
        return True
    except Exception as e:
        logger.error("Failed to send greeting video to chat %d: %s", chat_id, e, exc_info=True)
        return False


@alan_greeting_router.chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    ),
    lambda event: event.new_chat_member.user.id == settings.ALAN_USER_ID,
)
async def on_alan_join(event: types.ChatMemberUpdated):
    """F7: Detect when Alan joins the chat and send greeting video."""
    user = event.new_chat_member.user
    chat_id = event.chat.id

    logger.info("ChatMemberUpdated: user %d joined chat %d", user.id, chat_id)

    if user.id != settings.ALAN_USER_ID:
        logger.info("User %d is not Alan (%d), skipping greeting", user.id, settings.ALAN_USER_ID)
        return UNHANDLED

    logger.info("Alan (id=%d) joined chat %d — detected via ChatMemberUpdated", user.id, chat_id)

    now = time.time()
    if chat_id in _last_greeting:
        elapsed = now - _last_greeting[chat_id]
        if elapsed < settings.ALAN_GREETING_COOLDOWN:
            logger.info("Greeting for chat %d suppressed (cooldown: %.1fs remaining)", 
                       chat_id, settings.ALAN_GREETING_COOLDOWN - elapsed)
            return

    success = await _send_greeting(event.bot, chat_id)
    if success:
        _last_greeting[chat_id] = time.time()


@alan_greeting_router.message(F.new_chat_members)
async def on_alan_new_member(message: types.Message):
    """Fallback: detect Alan join via new_chat_members field."""
    if not message.new_chat_members:
        return UNHANDLED

    chat_id = message.chat.id

    if any(u.id == settings.ALAN_USER_ID for u in message.new_chat_members):
        logger.info("Alan (id=%d) joined chat %d — detected via new_chat_members fallback",
                   settings.ALAN_USER_ID, chat_id)

        now = time.time()
        if chat_id in _last_greeting:
            elapsed = now - _last_greeting[chat_id]
            if elapsed < settings.ALAN_GREETING_COOLDOWN:
                logger.info("Greeting for chat %d suppressed via new_chat_members (cooldown: %.1fs remaining)",
                           chat_id, settings.ALAN_GREETING_COOLDOWN - elapsed)
                return UNHANDLED

        success = await _send_greeting(message.bot, chat_id)
        if success:
            _last_greeting[chat_id] = time.time()

    return UNHANDLED
