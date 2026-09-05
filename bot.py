import asyncio
import contextlib
import logging
import os
import signal

import sentry_sdk
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.storage.memory import MemoryStorage
import uvicorn

from config.settings import settings
from services import hot_config as hot
from services.betterstack_handler import BetterStackHandler
from services.config_cache import ConfigCache
from services.control_service import ControlService
from services.hot_config import set_config_cache
from services.log_ring import log_ring as _log_ring_singleton
from services.status_service import status
from services.uptime_heartbeat import UptimeHeartbeatService
from web.app import create_app

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
from handlers.dead_page_delete import dead_page_delete_router, setup_dead_page_delete
from handlers.war_alert import war_alert_router, setup_war_alert
from handlers.common import common_router, setup_common, setup_common_mimic
from handlers.olya import olya_router, setup_olya
from handlers.admin_commands import admin_commands_router, setup_admin_commands
from handlers.menu import menu_router
from services.olya_relay import OlyaRelay
from handlers.summary import summary_observer_router, summary_router, setup_summary
from services.llm_client import LLMClient
from services.summary_aliases import AliasResolver
from services.summary_generator import SummaryGenerator
from services.summary_memory import MemoryManager
from services.summary_scheduler import SummarySchedulerService
from services.memory_backup import MemoryBackupService
from services.memory_maintenance import MemoryMaintenanceService
from services.summary_xml import XmlGroundingBuilder
from services.goodmorning_relay import GoodmorningRelay
from services.goodmorning_scheduler import GoodmorningSchedulerService
from services.bot_commands import setup_bot_commands
from handlers.factcheck import factcheck_router, setup_factcheck
from handlers.search import search_router, setup_search
from services.search_aggregator import SearchAggregator
from services.factcheck_service import FactCheckService
from services.search_service import SearchService
from handlers.youtube import (
    setup_youtube,
    setup_youtube_video_media,
    youtube_router,
)
from handlers.web import web_router, setup_web
from services.web_content_extractor import WebContentExtractor
from services.youtube_transcript_engine import YouTubeTranscriptEngine
from services.youtube_summarizer_service import YoutubeSummarizerService
from services.video_cascade_client import OpenRouterVideoClient
from services.web_summarizer_service import WebSummarizerService
from handlers.checkup import checkup_router, setup_checkup
from services.checkup_service import CheckupService
from services.system_logs_fetcher import CheckupLogsFetcher
from handlers.direct_chat import direct_chat_router, setup_direct_chat
from services.direct_chat_service import DirectChatService
from services.persistent_throttling import PersistentThrottle
from services.smart_cache import close_smart_cache, get_smart_cache
# ── Epic 66 (D262): локальный Bot API для скачивания >50MB ──
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from handlers.info import info_router, setup_info
from services.info_service import InfoService
from handlers.debug_config import debug_config_router
from tools.video_downloader import VideoDownloader
from handlers.video_download import video_download_router, setup_video_download
# ── Epic 67: VoiceTranscriber (Section 71) ──
from SmartModule.service import VoiceTranscriber
from handlers.voice_transcription import (
    voice_transcription_router,
    setup_voice_transcription,
)
# ── Раунд 7: Chat Lore v2 (PG-профили чатов) — B5: DI/startup/shutdown ──
from services.chat_lore_store import ChatLoreStore
from services.lore_cache import ChatLoreCache
from services.lore_notify import LoreNotify
from services.lore_runtime import (
    get_lore_cache,
    get_lore_notify,
    get_lore_store,
    set_lore_components,
)
from services.lore_worker import LoreWorker
from handlers.chat_lifecycle import chat_lifecycle_router, setup_chat_lifecycle

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
formatter = logging.Formatter(log_format)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# ── Раунд 4 (T-706, spec 3.1.6, FR-B5): собственный BetterStackHandler вместо
# logtail-python 0.4.0 (тихие потери: Queue-Full → dropcount без лога, ошибки
# только print в flusher). Чтение токена: строго LOGTAIL_SOURCE_TOKEN — один
# токен общий для BetterStack Errors и Logs. Формат фрейма — logtail-совместимый
# (3.1.2). Содержимое токена не проверяется (совпадение с SENTRY_DSN — норма).
betterstack_token = os.getenv("LOGTAIL_SOURCE_TOKEN")
handlers = [console_handler]
if betterstack_token:
    handlers.append(BetterStackHandler(source_token=betterstack_token,
                                       level=logging.INFO))

logging.basicConfig(level=logging.INFO, handlers=handlers)

# ── Раунд 4 (T-707, spec FR-B4): aiogram.event логирует КАЖДЫЙ апдейт на INFO
# («Update id=… is/not handled», aiogram 3.31 dispatcher.py:174-185) → спам в
# панели BetterStack. WARNING/ERROR-событий в этом логгере нет — ничего
# полезного не теряется. Уровень root INFO сохраняется.
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Epic 85 (84.11.1, T-628): in-memory ring-buffer логов для /api/status/logs.
# На root-logger рядом с basicConfig; маскировка секретов в emit (R17).
# ВАЖНО (фикс 2026-09-03): подключаем МОДУЛЬНЫЙ синглтон services.log_ring.log_ring
# (routes/status_service читают get_log_ring() — тот же объект); ранее здесь
# создавался НОВЫЙ LogRingHandler(), а API читал пустой синглтон → «логи пустые».
_log_ring_singleton.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_log_ring_singleton)
log_ring_handler = _log_ring_singleton

# ── Раунд 4 (3.1.6/3.1.8, T-706): стартовая диагностика BetterStack. Маркер
# пишется ПОСЛЕ подключения log_ring (выше) — виден и в journald, и в
# /api/status/logs («слушает ли хендлер», аналог T-700). Первым событием маркер
# уходит и в панель BetterStack (live-проверка). Токен НЕ логируется — только
# token_len (R17/NFR-3). Счётчики/журнал ошибок — в самом хендлере.
if betterstack_token:
    logger.info("[betterstack] attached | token_len=%d | handler=own-v1",
                len(betterstack_token))
else:
    logger.warning("[betterstack] skipped (no LOGTAIL_SOURCE_TOKEN)")

if hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
    bot = Bot(
        token=settings.API_TOKEN,
        session=AiohttpSession(
            api=TelegramAPIServer.from_base(settings.LOCAL_BOT_API_URL, is_local=True),
        ),
    )
else:
    bot = Bot(token=settings.API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# SmartModule (Epic 24) — module-level refs for on_shutdown
_summary_service = None
_llm_client = None
# Goodmorning (Epic 30) — module-level ref for on_shutdown
_goodmorning_scheduler = None
# SmartModule FactCheck + SmartSearch (Epic 33) — module-level ref for on_shutdown
_search_aggregator = None
# SmartModule YouTube + Web (Epic 37) — module-level ref for on_shutdown
_web_extractor = None
# SmartModule Checkup (Epic 42) — module-level ref for on_shutdown
_checkup_fetcher = None
# Memory backup (Epic 60, Section 64.3, T-464) — module-level ref for on_shutdown
_memory_backup_service = None
# Memory maintenance (Epic 60, Section 66.2/66.11, T-480/T-489) — merge+review
_memory_maintenance_service = None
# Uptime heartbeat (Epic 85, 84.11.3, T-630) — module-level ref for on_shutdown
_uptime_heartbeat = None
# Раунд 3 (T-688): ОБЩИЙ VideoDownloader — создаётся в summary-блоке (0e
# ссылочные ветки НЕ гейтятся flags.download_enabled), переиспользуется
# роутером 4e «скачай» (один глобальный лок скачивания на процесс).
_shared_video_downloader = None
# Раунд 7 (chat-lore-management-v2) — refs for on_shutdown: NOTIFY-слушатель
# и авто-воркер лора чатов (PG-профили; B5).
_lore_notify = None
_lore_worker = None


async def on_startup():
    """Initialize DB, scheduler, and wire dependencies."""
    db = DatabaseService(settings.DB_PATH)
    await db.initialize()
    logger.info("Database initialized")

    # ── Раунд 5 (3.2.3/4.6.3, T-733): идемпотентный инжект лора чата
    # (экспорт-конференция 2661910336 → runtime chat_id -1002661910336;
    # protected_facts chat-level + graph_facts user_memory + FTS).
    # Миграция v6 уже применена в db.initialize() — инжект после неё безопасен.
    # БЕЗУСЛОВЕН (вне summary-гейта): лор ставится при любом флаге. Fail-open:
    # ошибка → WARNING, старт бота НЕ роняем (вторая гарантия после DevOps T-743).
    from services.chat_lore import ensure_chat_lore
    try:
        result = await ensure_chat_lore(db)
        logger.info("[chat_lore] startup ensure | %s", result)
    except Exception:  # fail-open: старт не роняем
        logger.warning("[chat_lore] startup ensure failed", exc_info=True)

    # ── Раунд 7 (chat-lore-management-v2, T-773/T-774, B3/B4): PG-лор чатов.
    # Store/Cache/NOTIFY-слушатель — ДО summary-блока (инжект direct_chat
    # получает ChatLoreCache из runtime). Fail-open (NFR-2): PG недоступен →
    # WARNING, бот жив на settings-дефолтах; компоненты не установлены →
    # ровно старое поведение (SQLite-легаси-лор).
    global _lore_notify
    pg = hot.get_config_cache()
    pg = pg.pg if pg is not None else None
    if pg is not None and getattr(pg, "dsn", None):
        try:
            lore_store = ChatLoreStore(pg)
            lore_cache = ChatLoreCache(lore_store)
            _lore_notify = LoreNotify(lore_cache, dsn=pg.dsn)
            asyncio.create_task(_lore_notify.start())
            # runtime доступен с этого момента: API-роуты web/api/chat_lore.py
            # и инжект direct_chat (в summary-блоке ниже) читают компоненты
            # из services.lore_runtime (B5).
            set_lore_components(store=lore_store, cache=lore_cache,
                                notify=_lore_notify)
            logger.info(
                "[lore] store/cache/notify initialized (LISTEN lore_updated)")
        except Exception:
            logger.warning(
                "[lore] store/cache/notify init failed — fail-open (старое "
                "поведение инжекта)", exc_info=True)
    else:
        logger.warning(
            "[lore] PostgreSQL недоступен — PG-лор выключен (fail-open, "
            "SQLite-легаси активен)")

    # Раунд 3 (3.1, T-687): ленивая TTL-чистка каталога временных публикаций
    # при старте (NFR-2: каталог не копится). Файлы сами протухнут по mtime,
    # но после долгого простоя остатки убираем сразу.
    from services import media_share
    try:
        await asyncio.to_thread(media_share.cleanup_expired)
    except Exception:
        logger.warning("[media_share] startup cleanup failed", exc_info=True)

    # Create relay and scheduler
    relay = DeadPageRelay(bot, db, MediaService(media_base=hot.get("reactions.dead_page_dir", settings.DEAD_PAGE_DIR)))
    scheduler = SchedulerService(relay=relay, target_user_id=hot.get("reactions.slavik_user_id", settings.SLAVIK_USER_ID))
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
        cooldown_seconds=hot.get("limits.common_cooldown", settings.COMMON_COOLDOWN),
        danger_cooldown_seconds=hot.get("limits.danger_cooldown", settings.DANGER_COOLDOWN),
        selfdev_cooldown_seconds=hot.get("limits.selfdev_cooldown", settings.SELFDEV_COOLDOWN),
        work_cooldown_seconds=hot.get("limits.work_cooldown", settings.WORK_COOLDOWN),
    )
    setup_common(common_relay)
    logger.info("Common Service (Epic 15) initialized")

    mimic_relay = MimicRelay(
        min_words=hot.get("limits.mimic_min_words", settings.MIMIC_MIN_WORDS),
        cooldown_seconds=hot.get("limits.mimic_cooldown", settings.MIMIC_COOLDOWN),
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
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        _llm_client = LLMClient(
            hot.get("models.llm_base_url", settings.LLM_BASE_URL),
            hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
            hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME),
        )
        aliases = AliasResolver(hot.get("limits.summary_aliases", settings.SUMMARY_ALIASES))
        # Epic 60 (66.9, T-487): aliases → MemoryManager (привязка фактов к
        # людям по алиасам: канон-имена в фактах/узлах → карточки /persona).
        memory = MemoryManager(db, _llm_client, aliases=aliases)
        vec_ok = await memory.initialize()
        logger.info(
            "SmartModule: sqlite-vec %s",
            "available" if vec_ok else "UNAVAILABLE — FTS5 fallback (R3)",
        )
        xml_builder = XmlGroundingBuilder()
        generator = SummaryGenerator(memory, xml_builder, _llm_client, bot, aliases)
        setup_summary(generator, db, aliases, bot.id)
        _summary_service = SummarySchedulerService(generator, db)
        _summary_service.start()  # BEFORE dp.start_polling (RESEARCH §c)
        logger.info("SmartModule Summary (Epic 24) initialized (TZ=%s)", hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE))

        # ── SmartModule: FactCheck + SmartSearch (Epic 33) ──
        global _search_aggregator
        _search_aggregator = SearchAggregator()                 # ленивый httpx-клиент
        _search_aggregator.log_config()                         # D104: WARNING-и пустых ключей
        setup_factcheck(FactCheckService(_search_aggregator, _llm_client, memory=memory), db)
        setup_search(SearchService(_search_aggregator, _llm_client, memory=memory), db)
        logger.info("SmartModule FactCheck + SmartSearch (Epic 33) initialized")

        # ── SmartModule: YouTube + Web (Epic 37) ──
        global _web_extractor
        youtube_engine = YouTubeTranscriptEngine()
        _web_extractor = WebContentExtractor()
        _web_extractor.log_config()                         # WARNING пустых ключей (D104)
        # Bugfix 04.09.2026 (Часть 1): ЕДИНЫЙ инстанс VoiceTranscriber —
        # общий asyncio.Semaphore (D295) для голосовых/кружочков (0i) и
        # нативных TG-видео (медиа-ветка 0e). Инстанс создаётся ВНУТРИ
        # summary-блока независимо от enable_voice_transcription (ключи пусты →
        # стратегии skip); поведение voice-роутера не меняется. Порядок
        # регистрации роутеров ниже НЕ трогаем.
        voice_service = VoiceTranscriber(
            max_concurrency=hot.get("models.groq_max_concurrency",
                                    settings.GROQ_MAX_CONCURRENCY))
        # Раунд 3 (T-688): общий VideoDownloader для ссылочных веток 0e
        # (прямые ссылки/платформы) и роутера 4e «скачай» — лёгкий, клиенты
        # ленивые (D261); лок скачивания один на процесс (гонок нет).
        global _shared_video_downloader
        _shared_video_downloader = VideoDownloader(
            settings.COBALT_API_URL, settings.DOWNLOAD_DIR)
        setup_youtube_video_media(voice_service, db, aliases, memory, bot.id,
                                  downloader=_shared_video_downloader)
        # Раунд 3 (3.7/C2, T-697): backfill expires_at существующих
        # bot_direct_reply-фактов без TTL (идемпотентно; NULL-строк больше
        # нет после первого старта). Fail-open.
        try:
            await memory.backfill_direct_reply_ttl()
        except Exception:
            logger.warning("[graphrag] bot_direct_reply backfill skipped",
                           exc_info=True)
        # Эпик 04.09.2026 (3.2): видео-каскад L1/L2 (мультимодальный OpenRouter
        # video_url). Ключ пуст → video_client.available=False → ровно старое
        # поведение (субтитры), WARNING в каскаде.
        setup_youtube(YoutubeSummarizerService(
            youtube_engine, _llm_client, memory=memory,
            video_client=OpenRouterVideoClient()), db)
        setup_web(WebSummarizerService(_web_extractor, _llm_client, memory=memory), db)
        logger.info("SmartModule YouTube + Web (Epic 37) initialized")

        # ── SmartModule: Checkup (Epic 42) ──
        global _checkup_fetcher
        _checkup_fetcher = CheckupLogsFetcher(
            sql_host=hot.get("models.checkup_betterstack_sql_host", settings.CHECKUP_BETTERSTACK_SQL_HOST),
            sql_user=hot.get("keys.checkup_betterstack_sql_user", settings.CHECKUP_BETTERSTACK_SQL_USER),
            sql_password=hot.get("keys.checkup_betterstack_sql_password", settings.CHECKUP_BETTERSTACK_SQL_PASSWORD),
            sql_table=hot.get("models.checkup_betterstack_sql_table", settings.CHECKUP_BETTERSTACK_SQL_TABLE),
            sql_query=hot.get("models.checkup_betterstack_sql_query", settings.CHECKUP_BETTERSTACK_SQL_QUERY),
            journalctl_cmd=settings.CHECKUP_JOURNALCTL_CMD,
        )
        logger.info(
            "Checkup SQL API configured=%s (R17: только факт)",
            bool(hot.get("keys.checkup_betterstack_sql_user", settings.CHECKUP_BETTERSTACK_SQL_USER) and hot.get("keys.checkup_betterstack_sql_password", settings.CHECKUP_BETTERSTACK_SQL_PASSWORD)),
        )
        setup_checkup(
            CheckupService(_llm_client, db=db, memory=memory),
            _checkup_fetcher, db)
        logger.info("SmartModule Checkup (Epic 42) initialized")

        # ── SmartModule: DirectChat (Epic 50, Section 58.4) ──
        bot_user = await bot.get_me()
        # Epic 60 (63.1): рубильник THROTTLE_PERSISTENT_ENABLED → persistent
        # token bucket (throttle_state); false → дефолт DirectChatService
        # строит старый in-memory DirectChatThrottle.
        throttle = None
        if hot.get("flags.throttle_persistent_enabled", settings.THROTTLE_PERSISTENT_ENABLED):
            throttle = PersistentThrottle(
                hot.get("limits.chat_burst_limit", settings.CHAT_BURST_LIMIT), hot.get("limits.chat_cooldown_seconds", settings.CHAT_COOLDOWN_SECONDS),
                "direct_chat", db)
        # Эпик 04.09.2026 (3.3, FR-17): инструменты только в direct_chat —
        # поиск через SearchAggregator, память через MemoryManager.
        from services.tool_router import ToolDeps, ToolRouter
        _tool_router = ToolRouter(ToolDeps(
            search=_search_aggregator, memory=memory, aliases=aliases))
        setup_direct_chat(
            DirectChatService(
                memory, db, _llm_client, aliases,
                throttle=throttle,
                bot_id=bot.id,
                bot_username=(getattr(bot_user, "username", None) or "").lower(),
                # Epic 60 (67.4, T-499): дедуп одинаковых текстов подряд
                # (smart_cache, slug direct_dedup; рубильник CHAT_DEDUP_ENABLED).
                cache=get_smart_cache(),
                tool_router=_tool_router,
                # Раунд 7 (T-781/F1): ChatLoreCache — инжект PG-лора в
                # контекст; None (PG down/ранний старт) → старое поведение.
                chat_lore_cache=get_lore_cache(),
            ),
            bot.id,
            (getattr(bot_user, "username", None) or "").lower(),
        )
        logger.info("SmartModule DirectChat (Epic 50) initialized")

        # ── VoiceTranscriber (Epic 67, Section 71.6) — сервис зависит от
        # memory/aliases; пустые ключи → стратегии пропустит контроллер ──
        # Epic 79.5 (D295): max_concurrency из настроек для защиты Groq Free Tier.
        # Bugfix 04.09.2026 (Часть 1): инстанс ЕДИНЫЙ с медиа-веткой youtube
        # (создан выше, в блоке YouTube) — здесь только регистрация роутера 0i.
        if hot.get("flags.enable_voice_transcription", settings.ENABLE_VOICE_TRANSCRIPTION):
            setup_voice_transcription(voice_service, db, aliases, memory, bot.id)
            logger.info(
                "VoiceTranscriber enabled (max_dur=%ss, groq=%s openrouter=%s, "
                "max_concurrency=%d)",
                hot.get("limits.voice_max_duration_seconds", settings.VOICE_MAX_DURATION_SECONDS),
                bool(hot.get("keys.groq_api_key", settings.GROQ_API_KEY)), bool(hot.get("keys.openrouter_api_key", settings.OPENROUTER_API_KEY)),
                hot.get("models.groq_max_concurrency", settings.GROQ_MAX_CONCURRENCY),
            )
        else:
            logger.info(
                "VoiceTranscriber disabled (ENABLE_VOICE_TRANSCRIPTION=False)")

        # ── Memory backup (Epic 60, Section 64.3, T-464) ──
        # VACUUM INTO-бэкап + текстовый экспорт фактов, daily. Рубильник
        # MEMORY_BACKUP_ENABLED; НЕ на остановленном боте (онлайн).
        global _memory_backup_service
        if hot.get("flags.memory_backup_enabled", settings.MEMORY_BACKUP_ENABLED):
            _memory_backup_service = MemoryBackupService(db)
            _memory_backup_service.start()
            logger.info("MemoryBackup (Epic 60) initialized (daily %s %s)",
                        hot.get("limits.memory_backup_hour", settings.MEMORY_BACKUP_HOUR), hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE))
        else:
            logger.info("MemoryBackup disabled (MEMORY_BACKUP_ENABLED=False)")

        # ── Memory maintenance (Epic 60, Section 66.2/66.11, T-480/T-489) ──
        # Слияние эпизодов + периодический пересмотр фактов (MemoryJobStore).
        global _memory_maintenance_service
        _memory_maintenance_service = MemoryMaintenanceService(db, memory, _llm_client)
        _memory_maintenance_service.start()
        logger.info("MemoryMaintenance (Epic 60, Фаза D) initialized")
    else:
        logger.info("SmartModule Summary disabled (SUMMARY_ENABLED=False)")

    # ── Раунд 7 (chat-lore-management-v2, T-776/T-775, C2/B5): воркер
    # авто-лора + runtime/handlers-DI. Вне summary-гейта: LLMClient при
    # выключенном summary создаётся свой (ленивый, ключи не проверяет);
    # start() сам решает по flags.lore_worker_enabled (джоб не
    # регистрируется). Fail-open: PG/компонентов нет → WARNING.
    global _lore_worker
    lore_store = get_lore_store()
    if lore_store is not None:
        try:
            lore_llm = _llm_client or LLMClient(
                hot.get("models.llm_base_url", settings.LLM_BASE_URL),
                hot.get("keys.llm_api_key", settings.LLM_API_KEY),
                hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
                hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME),
            )
            _lore_worker = LoreWorker(
                lore_store, cache=get_lore_cache(), db=db,
                llm=lore_llm, bot_id=bot.id, pg=lore_store.pg)
            await _lore_worker.start()
            set_lore_components(
                store=lore_store, cache=get_lore_cache(),
                notify=get_lore_notify(), worker=_lore_worker)
            setup_chat_lifecycle(lore_store, bot_id=bot.id)
            logger.info("LoreWorker (раунд 7) initialized")
        except Exception:
            logger.warning(
                "[lore] worker init failed — fail-open (PG-лор выключен)",
                exc_info=True)

    # ── Goodmorning (Epic 30) — без роутера (D91): чистый планировщик-сервис ──
    global _goodmorning_scheduler
    goodmorning_relay = GoodmorningRelay(bot=bot, media_dir=hot.get("reactions.goodmorning_media_dir", settings.GOODMORNING_MEDIA_DIR))
    _goodmorning_scheduler = GoodmorningSchedulerService(
        relay=goodmorning_relay,
        time_str=hot.get("reactions.goodmorning_time", settings.GOODMORNING_TIME),
        tz=hot.get("reactions.goodmorning_tz", settings.GOODMORNING_TZ),
        target_chat_ids=hot.get("reactions.goodmorning_target_chat_ids", settings.GOODMORNING_TARGET_CHAT_IDS),
    )
    _goodmorning_scheduler.start()  # ДО dp.start_polling; пустые targets → WARNING, no-op

    # ── /info + /edit_info (Epic 43, D162) — БЕЗУСЛОВНО (LLM не нужен) ──
    info_service = InfoService(settings.INFO_TEXT_FILE)
    info_service.load()
    setup_info(info_service, db)                 # Epic 60 (63.1): персистентный кулдаун
    logger.info("InfoService (Epic 43) initialized | file=%s", settings.INFO_TEXT_FILE)

    # ── Epic 31 (R31-2): меню команд (setMyCommands) — ДО dp.start_polling ──
    await setup_bot_commands(bot)

    # ═══════════════════════════════════════════════════════════
    # REGISTRATION ORDER (CRITICAL — DO NOT CHANGE)
    # ═══════════════════════════════════════════════════════════

    # 0a. SmartModule observer (Epic 24) — catch-all, saves ALL messages, returns UNHANDLED
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(summary_observer_router)

    # 0b. SmartModule /summary (Epic 24) — BEFORE admin_commands and catch-all 5/6
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(summary_router)

    # 0c. SmartModule FactCheck (Epic 33) — reply с «фактчек»; консьюмит, НЕ-триггеры → UNHANDLED
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(factcheck_router)

    # 0d. SmartModule SmartSearch (Epic 33) — «найди/поищи/загугли»; консьюмит, НЕ-триггеры → UNHANDLED
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(search_router)

    # 0e. SmartModule YouTube (Epic 37) — YT-URL + триггер; консьюмит, НЕ-триггеры → UNHANDLED
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(youtube_router)

    # 0f. SmartModule Web (Epic 37) — веб-URL + триггер; консьюмит, НЕ-триггеры → UNHANDLED
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(web_router)

    # 0g. SmartModule Checkup (Epic 42) — триггер-фразы; консьюмит, НЕ-триггеры → UNHANDLED
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(checkup_router)

    # 0h. SmartModule DirectChat (Epic 50, Section 58.4) — Reply-на-бота/упоминание;
    # позиция ПОСЛЕ 0g checkup, ДО admin_commands. Observer-стиль.
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED):
        dp.include_router(direct_chat_router)

    # 0i. Transcription (Epic 67, Section 71.3) — ПОСЛЕ observer 0a; UNHANDLED-стиль
    if hot.get("flags.summary_enabled", settings.SUMMARY_ENABLED) and hot.get("flags.enable_voice_transcription", settings.ENABLE_VOICE_TRANSCRIPTION):
        dp.include_router(voice_transcription_router)

    # 0. Admin test commands (Epic 10) — command-based, no conflict with other filters
    dp.include_router(admin_commands_router)
    dp.include_router(menu_router)

    # 0a. /debug_config (84.18, T-656) — скрытая диагностика RAM-кэша; DM-only,
    # допуск is_debug_admin (wildcard/action.debug.config/ADMIN_USER_ID-фолбек)
    dp.include_router(debug_config_router)

    # 0h. /info + /edit_info (Epic 43) — БЕЗУСЛОВНО (D162), command-based
    dp.include_router(info_router)

    # 1. ChatMemberUpdated handler (F1: Slava return detection)
    dp.include_router(slava_presence_router)

    # 1b. ChatMemberUpdated handler (F7: Alan greeting video)
    dp.include_router(alan_greeting_router)

    # 1c. ChatMemberUpdated handler (раунд 7, T-777/T-778): lifecycle чатов —
    # my_chat_member ТОЛЬКО по событиям самого бота (узкий фильтр в
    # handlers/chat_lifecycle.py; чужие → UNHANDLED) + migrate_to_chat_id.
    # Инклуд-добавка рядом с slava_presence; порядок существующих не менять.
    dp.include_router(chat_lifecycle_router)

    # 2. Kostik router — user ID 350803143
    dp.include_router(kostik_router)

    # 3. Alan router — user ID 138811255 (F6: reply engine, every 10 msgs)
    dp.include_router(alan_router)

    # 4. Dead Page trigger — reposts from @d_pages (NEW in V2)
    dp.include_router(dead_page_router)

    # 4a. Dead Page delete detection (Epic 52 / T-417, Section 61.6.4) — reply/quote
    # на УДАЛЁННЫЙ репост Славика (InaccessibleMessage). Позиция ДО war_alert/common/slavik.
    setup_dead_page_delete(db, bot.id)
    dp.include_router(dead_page_delete_router)

    # 4b. War Words Alert (F5v2) — keyword + channel repost alerts (Epic 10)
    dp.include_router(war_alert_router)

    # 4c. Common Service (Epic 15): otboy "отбой" + danger keywords → random media with quote
    dp.include_router(common_router)

    # 4d. Olya Service (Epic 19) — video from @ole4444444ka → random media (plain send)
    if hot.get("flags.olya_enabled", settings.OLYA_ENABLED):
        olya_relay = OlyaRelay(
            bot=bot,
            cooldown_seconds=hot.get("limits.olya_cooldown", settings.OLYA_COOLDOWN),
            media_base=hot.get("reactions.olya_media_base", settings.OLYA_MEDIA_BASE),
        )
        setup_olya(olya_relay)
        dp.include_router(olya_router)
        logger.info("Olya service enabled (cooldown=%.1fs)", hot.get("limits.olya_cooldown", settings.OLYA_COOLDOWN))
    else:
        logger.info("Olya service disabled (OLYA_ENABLED=False)")

    # 4e. Video Download (Epic 66, Section 70.7) — триггер «скачай <url>»;
    # консьюмит при триггере, НЕ-триггеры → UNHANDLED
    if hot.get("flags.download_enabled", settings.DOWNLOAD_ENABLED):
        # Раунд 3 (T-688): ОБЩИЙ инстанс со ссылочными ветками 0e (создан в
        # summary-блоке) — один глобальный лок скачивания на процесс.
        downloader = _shared_video_downloader or VideoDownloader(
            settings.COBALT_API_URL, settings.DOWNLOAD_DIR)
        setup_video_download(downloader, db)
        dp.include_router(video_download_router)
        logger.info("VideoDownloader enabled (cobalt=%s)", settings.COBALT_API_URL)
    else:
        logger.info("VideoDownloader disabled (DOWNLOAD_ENABLED=False)")

    # 5. Slava router — user ID 479167456 (F3, F4 + catch-all; F5 moved to 4b)
    dp.include_router(slavik_router)

    # 6. Vasya router — text filters, no user restriction
    dp.include_router(vasya_router)

    logger.info("All routers registered (v2.4.0)")

    # ── Epic 14: Relay channel media group tracker ──
    @dp.channel_post(F.chat.id == hot.get("reactions.dead_page_relay_channel_id", settings.DEAD_PAGE_RELAY_CHANNEL_ID))
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
    if _lore_worker:
        await _lore_worker.stop()
    if _lore_notify:
        await _lore_notify.stop()
    if _uptime_heartbeat:
        await _uptime_heartbeat.shutdown()
    if _goodmorning_scheduler:
        await _goodmorning_scheduler.shutdown()
    if _summary_service:
        await _summary_service.shutdown()
    if _memory_backup_service:
        await _memory_backup_service.shutdown()
    if _memory_maintenance_service:
        await _memory_maintenance_service.shutdown()
    if _llm_client:
        await _llm_client.close()
    if _search_aggregator:
        await _search_aggregator.close()
    if _web_extractor:
        await _web_extractor.close()
    if _checkup_fetcher:
        await _checkup_fetcher.close()
    await close_smart_cache()


async def main():
    # ── Epic 85 (84.15.4): флаг-файл stop. Обнаружен → удаляем (F12: обычный
    # ручной старт чистит следы прошлого stop) → мгновенный exit 0 — страховка
    # от рестарт-петли Restart=always (exit 0 = успех, systemd НЕ ретраит).
    if ControlService.flag_file_exists():
        logger.warning("[control] flag-file %s обнаружен — удалён, "
                       "мгновенный exit 0", ControlService.FLAG_FILE_NAME)
        ControlService().remove_flag_file()
        return

    # ── Epic 85 (84.11.2): started_at — первая строка main().
    status.mark_started()

    # ── Epic 85 (84.4): ConfigCache ДО on_startup — горячие точки (T-619)
    # видят кэш; PG down → WARNING, бот работает на settings-дефолтах (R6).
    cache = ConfigCache()
    await cache.init()
    set_config_cache(cache)

    # ── Раунд 5 (T-740, spec 3.3.4): авто-миграция канонов промптов в PG
    # (9 ключей; канон → новый канон; кастом юзера НЕ трогаем; PG down /
    # ключ отсутствует → skip с логом [prompt_migration]). Заменяет
    # migrate_direct_chat_prompt_if_legacy (удалена из chat_prompts.py).
    from services.prompt_migrations import migrate_prompt_canons
    await migrate_prompt_canons(cache)

    # ── Раунд 3 (3.7/C2, T-697): легаси-NULL TTL bot_direct_reply в PG → 30
    # (сид поставит 30, если ключа нет; 0/число — явный выбор, не трогаем).
    from services.summary_memory import migrate_direct_reply_ttl_default
    await migrate_direct_reply_ttl_default(cache)

    await on_startup()
    logger.info("Bot started, listening for messages...")
    print("Бот запущен и слушает чат...")

    # ── Epic 85 (84.11.3, T-630): heartbeat аптайма (60с) + автоочистка.
    global _uptime_heartbeat
    _uptime_heartbeat = UptimeHeartbeatService(pg=cache.pg)
    _uptime_heartbeat.start()

    # ── Epic 85 (84.4, T-615): ОДИН event loop — uvicorn.server.serve() +
    # polling-таска. uvicorn.run() и потоки ЗАПРЕЩЕНЫ (R2).
    stop_event = asyncio.Event()
    server_holder: list[uvicorn.Server | None] = [None]

    def request_shutdown() -> None:
        """F1 (84.15.4): dev restart/stop = graceful exit — должен ОСТАНАВЛИВАТЬ
        и polling, и uvicorn: stop_event (watcher) + server.should_exit
        (иначе serve() живёт вечно и колбэк никого не останавливает)."""
        stop_event.set()
        if server_holder[0] is not None:
            server_holder[0].should_exit = True

    control = ControlService(request_shutdown=request_shutdown)
    app = create_app(cache, control=control)
    web_port = int(os.getenv("WEB_PORT", "8000"))
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=web_port,
        loop="auto",            # R3: asyncio на Windows-деве, uvloop на проде
        log_level="warning",
        log_config=None,        # hotfix 30.08.2026: НЕ запускать дефолтный
        # dictConfig uvicorn — его _clearExistingHandlers → logging.shutdown()
        # закрывает LogtailHandler и дедлочит с logtail-флашером (прод-инцидент
        # Epic 85: процесс «active», но polling/webapp/heartbeat не стартуют).
    ))
    server_holder[0] = server
    polling = asyncio.create_task(dp.start_polling(bot))
    status.set_polling_state("polling")

    def _watch_polling(task: asyncio.Task) -> None:
        """84.11.2: state polling_error — задача polling done() с exception."""
        if task.cancelled():
            status.set_polling_state("stopped")   # штатная остановка (SIGTERM)
            return
        exc = task.exception()
        status.set_polling_state("polling_error" if exc is not None
                                 else "stopped")
        if exc is not None:
            logger.error("polling task crashed", exc_info=exc)

    polling.add_done_callback(_watch_polling)

    # ── Graceful shutdown (84.15.5/T-642): SIGTERM/SIGINT → корректная
    # остановка ≤10с (polling.cancel + on_shutdown + PG-пул).
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, ValueError):
            pass                     # Windows: SIGTERM недоступен — только SIGINT
    watcher = asyncio.create_task(stop_event.wait())

    try:
        await server.serve()
    finally:
        stop_event.set()
        polling.cancel()
        watcher.cancel()
        try:
            await polling
        except asyncio.CancelledError:
            pass
        except Exception:
            # polling уже упал ДО остановки — не роняем main (state
            # polling_error выставлен в _watch_polling, R6: бот отдаёт статус)
            logger.error("polling finished with error during shutdown",
                         exc_info=True)
        with contextlib.suppress(asyncio.CancelledError):
            await watcher
        server.should_exit = True
        await on_shutdown()
        await cache.close()
        # ── Раунд 4 (3.1.6/3.1.4, FR-B3): мягкое закрытие логов — САМЫЙ конец
        # процесса (после on_shutdown/cache.close, в финальном finally):
        # logging.shutdown() делает close() всех хендлеров → BetterStackHandler
        # досылает остаток буфера (≤2000 событий; SIGKILL/TimeoutStopSec —
        # документированная потеря буфера, как было с logtail).
        logger.info("[betterstack] shutdown flush")
        try:
            logging.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    asyncio.run(main())
