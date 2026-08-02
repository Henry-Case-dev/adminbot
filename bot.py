import asyncio
import logging
import os

import sentry_sdk
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.storage.memory import MemoryStorage
from logtail import LogtailHandler

from config.settings import settings

# Initialize Sentry error tracking (Better Stack)
sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=1.0,
    )
from services.database import DatabaseService
from services.scheduler import SchedulerService
from services.media_picker import MediaService
from services.dead_page_relay import DeadPageRelay
from services.common_relay import CommonRelay
from services.mimic_relay import MimicRelay
from services.message_counter import MessageCounterMiddleware

# Handlers
from handlers.kostik import kostik_router
from handlers.alan import alan_router, setup_alan
from handlers.slavik import slavik_router, setup_slavik
from handlers.vasya import vasya_router
from handlers.slava_presence import slava_presence_router, setup_presence
from handlers.alan_greeting import alan_greeting_router
from handlers.dead_page_trigger import dead_page_router, setup_dead_page
from handlers.war_alert import war_alert_router, setup_war_alert
from handlers.common import common_router, setup_common, setup_common_mimic
from handlers.admin_commands import admin_commands_router, setup_admin_commands

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
formatter = logging.Formatter(log_format)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logtail_token = os.getenv("LOGTAIL_SOURCE_TOKEN")
handlers = [console_handler]
if logtail_token:
    handlers.append(LogtailHandler(source_token=logtail_token))

logging.basicConfig(level=logging.INFO, handlers=handlers)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


async def on_startup():
    """Initialize DB, scheduler, and wire dependencies."""
    db = DatabaseService(settings.DB_PATH)
    await db.initialize()
    logger.info("Database initialized")

    # Create relay and scheduler
    relay = DeadPageRelay(bot, db, MediaService(media_base=settings.DEAD_PAGE_DIR))
    scheduler = SchedulerService(relay=relay, target_user_id=settings.SLAVIK_USER_ID)
    logger.info("DeadPageRelay and Scheduler created")

    # Inject dependencies
    setup_presence(db, scheduler)
    setup_dead_page(relay, db)
    setup_alan(db)
    setup_admin_commands(relay)
    setup_war_alert()
    setup_slavik(db)  # F6: Slavic photo counter (Epic 12)
    
    common_relay = CommonRelay(
        bot,
        cooldown_seconds=settings.COMMON_COOLDOWN_SECONDS,
        danger_cooldown_seconds=settings.DANGER_COOLDOWN_SECONDS,
    )
    setup_common(common_relay)
    logger.info("Common Service (Epic 15) initialized")

    mimic_relay = MimicRelay(
        min_words=settings.MIMIC_MIN_WORDS,
        cooldown_seconds=settings.MIMIC_COOLDOWN_SECONDS,
    )
    setup_common_mimic(mimic_relay)
    logger.info("Mimic Service (Epic 18) initialized")
    
    # Attach GIF counter middleware to slavik router
    slavik_router.message.middleware(MessageCounterMiddleware(db))

    # Start background scheduler
    asyncio.create_task(scheduler.run())
    logger.info("Scheduler started")

    # ═══════════════════════════════════════════════════════════
    # REGISTRATION ORDER (CRITICAL — DO NOT CHANGE)
    # ═══════════════════════════════════════════════════════════

    # 0. Admin test commands (Epic 10) — command-based, no conflict with other filters
    dp.include_router(admin_commands_router)

    # 1. ChatMemberUpdated handler (F1: Slava return detection)
    dp.include_router(slava_presence_router)

    # 1b. ChatMemberUpdated handler (F7: Alan greeting video)
    dp.include_router(alan_greeting_router)

    # 2. Kostik router — user ID 350803143
    dp.include_router(kostik_router)

    # 3. Alan router — user ID 138811255 (F6: reply engine, every 10 msgs)
    dp.include_router(alan_router)

    # 4. Dead Page trigger — reposts from @d_pages (NEW in V2)
    dp.include_router(dead_page_router)

    # 4b. War Words Alert (F5v2) — keyword + channel repost alerts (Epic 10)
    dp.include_router(war_alert_router)

    # 4c. Common Service (Epic 15): otboy "отбой" + danger keywords → random media with quote
    dp.include_router(common_router)

    # 5. Slava router — user ID 479167456 (F3, F4 + catch-all; F5 moved to 4b)
    dp.include_router(slavik_router)

    # 6. Vasya router — text filters, no user restriction
    dp.include_router(vasya_router)

    logger.info("All routers registered (v2.4.0)")

    # ── Epic 14: Relay channel media group tracker ──
    @dp.channel_post(F.chat.id == settings.DEAD_PAGE_RELAY_CHANNEL_ID)
    async def track_relay_post(message: types.Message):
        """Track media_group_id for relay channel posts to enable album-aware forwarding."""
        if message.media_group_id:
            await db.save_relay_album_map(message.message_id, message.media_group_id)
            logger.debug(
                f"[relay_tracker] Indexed msg_id={message.message_id} "
                f"media_group_id={message.media_group_id}"
            )
        # Track Rich Messages (Bot API 10.2+) — log for diagnostics
        try:
            rich = message.rich_message
            if rich is not None:
                logger.info(
                    f"[relay_tracker] Rich Message indexed: msg_id={message.message_id}"
                )
        except AttributeError:
            pass
    logger.info("Relay channel media group tracker registered (Epic 14)")


async def on_shutdown():
    """Cleanup resources on bot shutdown."""
    logger.info("Bot shutting down...")


async def main():
    await on_startup()
    logger.info("Bot started, listening for messages...")
    print("Бот запущен и слушает чат...")
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()


if __name__ == '__main__':
    asyncio.run(main())
