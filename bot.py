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
from handlers.olya import olya_router, setup_olya
from handlers.admin_commands import admin_commands_router, setup_admin_commands
from services.olya_relay import OlyaRelay
from handlers.summary import summary_observer_router, summary_router, setup_summary
from services.llm_client import LLMClient
from services.summary_aliases import AliasResolver
from services.summary_generator import SummaryGenerator
from services.summary_memory import MemoryManager
from services.summary_scheduler import SummarySchedulerService
from services.summary_xml import XmlGroundingBuilder
from services.goodmorning_relay import GoodmorningRelay
from services.goodmorning_scheduler import GoodmorningSchedulerService
from services.bot_commands import setup_bot_commands
from handlers.factcheck import factcheck_router, setup_factcheck
from handlers.search import search_router, setup_search
from services.search_aggregator import SearchAggregator
from services.factcheck_service import FactCheckService
from services.search_service import SearchService

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

# SmartModule (Epic 24) — module-level refs for on_shutdown
_summary_service = None
_llm_client = None
# Goodmorning (Epic 30) — module-level ref for on_shutdown
_goodmorning_scheduler = None
# SmartModule FactCheck + SmartSearch (Epic 33) — module-level ref for on_shutdown
_search_aggregator = None


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
        cooldown_seconds=settings.COMMON_COOLDOWN,
        danger_cooldown_seconds=settings.DANGER_COOLDOWN,
        selfdev_cooldown_seconds=settings.SELFDEV_COOLDOWN,
        work_cooldown_seconds=settings.WORK_COOLDOWN,
    )
    setup_common(common_relay)
    logger.info("Common Service (Epic 15) initialized")

    mimic_relay = MimicRelay(
        min_words=settings.MIMIC_MIN_WORDS,
        cooldown_seconds=settings.MIMIC_COOLDOWN,
    )
    setup_common_mimic(mimic_relay)
    logger.info("Mimic Service (Epic 18) initialized")
    
    # Attach GIF counter middleware to slavik router
    slavik_router.message.middleware(MessageCounterMiddleware(db))

    # Start background scheduler
    asyncio.create_task(scheduler.run())
    logger.info("Scheduler started")

    # ── SmartModule: Summary (Epic 24) ──────────────────────
    global _summary_service, _llm_client
    if settings.SUMMARY_ENABLED:
        _llm_client = LLMClient(
            settings.LLM_BASE_URL,
            settings.LLM_API_KEY,
            settings.LLM_MODEL_NAME,
            settings.EMBEDDING_MODEL_NAME,
        )
        memory = MemoryManager(db, _llm_client)
        vec_ok = await memory.initialize()
        logger.info(
            "SmartModule: sqlite-vec %s",
            "available" if vec_ok else "UNAVAILABLE — FTS5 fallback (R3)",
        )
        aliases = AliasResolver(settings.SUMMARY_ALIASES)
        xml_builder = XmlGroundingBuilder()
        generator = SummaryGenerator(memory, xml_builder, _llm_client, bot, aliases)
        setup_summary(generator, db, aliases, bot.id)
        _summary_service = SummarySchedulerService(generator, db)
        _summary_service.start()  # BEFORE dp.start_polling (RESEARCH §c)
        logger.info("SmartModule Summary (Epic 24) initialized (TZ=%s)", settings.SUMMARY_TIMEZONE)

        # ── SmartModule: FactCheck + SmartSearch (Epic 33) ──
        global _search_aggregator
        _search_aggregator = SearchAggregator()                 # ленивый httpx-клиент
        _search_aggregator.log_config()                         # D104: WARNING-и пустых ключей
        setup_factcheck(FactCheckService(_search_aggregator, _llm_client))
        setup_search(SearchService(_search_aggregator, _llm_client))
        logger.info("SmartModule FactCheck + SmartSearch (Epic 33) initialized")
    else:
        logger.info("SmartModule Summary disabled (SUMMARY_ENABLED=False)")

    # ── Goodmorning (Epic 30) — без роутера (D91): чистый планировщик-сервис ──
    global _goodmorning_scheduler
    goodmorning_relay = GoodmorningRelay(bot=bot, media_dir=settings.GOODMORNING_MEDIA_DIR)
    _goodmorning_scheduler = GoodmorningSchedulerService(
        relay=goodmorning_relay,
        time_str=settings.GOODMORNING_TIME,
        tz=settings.GOODMORNING_TZ,
        target_chat_ids=settings.GOODMORNING_TARGET_CHAT_IDS,
    )
    _goodmorning_scheduler.start()  # ДО dp.start_polling; пустые targets → WARNING, no-op

    # ── Epic 31 (R31-2): меню команд (setMyCommands) — ДО dp.start_polling ──
    await setup_bot_commands(bot)

    # ═══════════════════════════════════════════════════════════
    # REGISTRATION ORDER (CRITICAL — DO NOT CHANGE)
    # ═══════════════════════════════════════════════════════════

    # 0a. SmartModule observer (Epic 24) — catch-all, saves ALL messages, returns UNHANDLED
    if settings.SUMMARY_ENABLED:
        dp.include_router(summary_observer_router)

    # 0b. SmartModule /summary (Epic 24) — BEFORE admin_commands and catch-all 5/6
    if settings.SUMMARY_ENABLED:
        dp.include_router(summary_router)

    # 0c. SmartModule FactCheck (Epic 33) — reply с «фактчек»; консьюмит, НЕ-триггеры → UNHANDLED
    if settings.SUMMARY_ENABLED:
        dp.include_router(factcheck_router)

    # 0d. SmartModule SmartSearch (Epic 33) — «найди/поищи/загугли»; консьюмит, НЕ-триггеры → UNHANDLED
    if settings.SUMMARY_ENABLED:
        dp.include_router(search_router)

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

    # 4d. Olya Service (Epic 19) — video from @ole4444444ka → random media (plain send)
    if settings.OLYA_ENABLED:
        olya_relay = OlyaRelay(
            bot=bot,
            cooldown_seconds=settings.OLYA_COOLDOWN,
            media_base=settings.OLYA_MEDIA_BASE,
        )
        setup_olya(olya_relay)
        dp.include_router(olya_router)
        logger.info("Olya service enabled (cooldown=%.1fs)", settings.OLYA_COOLDOWN)
    else:
        logger.info("Olya service disabled (OLYA_ENABLED=False)")

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
    if _goodmorning_scheduler:
        await _goodmorning_scheduler.shutdown()
    if _summary_service:
        await _summary_service.shutdown()
    if _llm_client:
        await _llm_client.close()
    if _search_aggregator:
        await _search_aggregator.close()


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
