import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config.settings import settings
from services.database import DatabaseService
from services.scheduler import SchedulerService
from services.message_counter import MessageCounterMiddleware

# Handlers
from handlers.kostik import kostik_router
from handlers.alan import alan_router, setup_alan
from handlers.slavik import slavik_router
from handlers.vasya import vasya_router
from handlers.slava_presence import slava_presence_router, setup_presence

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


async def on_startup():
    """Initialize DB, scheduler, and wire dependencies."""
    db = DatabaseService(settings.DB_PATH)
    await db.initialize()
    logger.info("Database initialized")

    scheduler = SchedulerService(bot, db, target_user_id=settings.SLAVIK_USER_ID)
    logger.info("Scheduler created")

    # Inject dependencies into slava_presence module
    setup_presence(db, scheduler)
    
    # Inject DB into alan reply engine
    setup_alan(db)
    
    # Attach GIF counter middleware to slavik router
    slavik_router.message.middleware(MessageCounterMiddleware(db))

    # Start background scheduler
    asyncio.create_task(scheduler.run())
    logger.info("Scheduler started")

    # ═══════════════════════════════════════════════════════════
    # REGISTRATION ORDER (CRITICAL — DO NOT CHANGE)
    # ═══════════════════════════════════════════════════════════

    # 1. ChatMemberUpdated handler (F1: Slava return detection)
    dp.include_router(slava_presence_router)

    # 2. Kostik router — user ID 350803143
    dp.include_router(kostik_router)

    # 3. Alan router — user ID 138811255 (F6: reply engine, every 10 msgs)
    dp.include_router(alan_router)

    # 4. Slava router — user ID 479167456 (F3, F4, F5 + catch-all)
    dp.include_router(slavik_router)

    # 5. Vasya router — text filters, no user restriction
    dp.include_router(vasya_router)

    logger.info("All routers registered")


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
