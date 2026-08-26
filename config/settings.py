import logging
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key, str(default))
    return int(val)


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key, str(default))
    return float(val)


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int_tuple(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    val = os.getenv(name)
    if val is None:
        return default
    parts = val.split(",")
    result: list[int] = []
    for p in parts:
        p = p.strip()
        if p:
            result.append(int(p))
    return tuple(result)


def _parse_duration(value: str) -> float:
    """Parse a duration string like '1s', '1m', '1h', '1d' to seconds.

    Also accepts bare integers as seconds for backward compatibility.
    '0' or '0s' returns 0.0 (disabled).
    """
    value = str(value).strip().lower()
    if not value:
        return 0.0

    if value.isdigit():
        return float(value)

    if value.endswith("s"):
        return float(value[:-1])
    elif value.endswith("m"):
        return float(value[:-1]) * 60
    elif value.endswith("h"):
        return float(value[:-1]) * 3600
    elif value.endswith("d"):
        return float(value[:-1]) * 86400
    else:
        try:
            return float(value)
        except ValueError:
            raise ValueError(
                f"Invalid duration format: '{value}'. "
                f"Use format like '1s', '1m', '1h', '1d', or a plain number of seconds."
            )


def _env_duration(key: str, default: str) -> float:
    """Read a duration env var and parse it. Falls back to default on parse error."""
    raw = os.getenv(key, default)
    try:
        return _parse_duration(raw)
    except ValueError:
        import logging
        logging.getLogger(__name__).warning(
            f"Invalid duration for {key}='{raw}', using default '{default}' = {_parse_duration(default)}s"
        )
        return _parse_duration(default)


def _env_int_min(key: str, default: int, min_value: int) -> int:
    """Int из env; кривой формат или значение < min_value → WARNING + default (D104)."""
    raw = os.getenv(key, str(default))
    try:
        val = int(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            f"Invalid int for {key}='{raw}', using default {default} (D104)"
        )
        return default
    if val < min_value:
        logging.getLogger(__name__).warning(
            f"{key}={val} < {min_value}, using default {default} (D104)"
        )
        return default
    return val


def _env_int_optional(key: str, default: int | None) -> int | None:
    """Int из env; пустая строка/отсутствие → default (None); кривой формат →
    WARNING + default (58.3)."""
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            f"Invalid int for {key}='{raw}', using default {default} (58.3)"
        )
        return default


def _env_float_min(key: str, default: float, min_value: float) -> float:
    """Float из env; кривой формат или значение < min_value → WARNING + default (D104)."""
    raw = os.getenv(key, str(default))
    try:
        val = float(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            f"Invalid float for {key}='{raw}', using default {default} (D104)"
        )
        return default
    if val < min_value:
        logging.getLogger(__name__).warning(
            f"{key}={val} < {min_value}, using default {default} (D104)"
        )
        return default
    return val


@dataclass(frozen=True)
class Settings:
    API_TOKEN: str = os.getenv("API_TOKEN", "")
    DB_PATH: str = os.getenv("DB_PATH", "local_database.db")
    MEDIA_BASE: str = os.getenv("MEDIA_BASE", "media")

    # User IDs (now configurable via env)
    SLAVIK_USER_ID: int = _env_int("SLAVIK_USER_ID", 479167456)
    KOSTIK_USER_ID: int = _env_int("KOSTIK_USER_ID", 350803143)
    ALAN_USER_ID: int = _env_int("ALAN_USER_ID", 138811255)

    # Alan reply interval — every N messages, bot replies with random phrase
    ALAN_REPLY_INTERVAL: int = _env_int("ALAN_REPLY_INTERVAL", 10)

    # Epic 52 (T-408): выключатель reply-блока Алана. false → reply молчит,
    # счётчик продолжает инкрементиться, F7v2 silence greeting работает БЕЗУСЛОВНО.
    ALAN_REPLIES_ENABLED: bool = _env_bool("ALAN_REPLIES_ENABLED", True)

    # Kostik reply probability — 0.0 (never) to 1.0 (always, legacy default)
    KOSTIK_REPLY_PROBABILITY: float = _env_float("KOSTIK_REPLY_PROBABILITY", 1.0)

    # Dead Page V2 — Repost-triggered
    DEAD_PAGE_SOURCE_CHANNEL_USERNAME: str = os.getenv("DEAD_PAGE_SOURCE_CHANNEL_USERNAME", "d_pages")
    DEAD_PAGE_SOURCE_CHANNEL_ID: int = _env_int("DEAD_PAGE_SOURCE_CHANNEL_ID", 0)

    # Relay channel (private bot channel for forwarding)
    DEAD_PAGE_RELAY_CHANNEL_ID: int = _env_int("DEAD_PAGE_RELAY_CHANNEL_ID", 4228645624)

    # Max caption characters for fallback sendPhoto (channel limit 4096)
    DEAD_PAGE_CAPTION_MAX_CHARS: int = _env_int("DEAD_PAGE_CAPTION_MAX_CHARS", 1024)

    # Anti-spam: minimum seconds between dead pages in same chat
    DEAD_PAGE_COOLDOWN: float = _env_duration("DEAD_PAGE_COOLDOWN", "10s")

    # Keep join trigger? (Epic 22 / D53: default off — join → only «ДОЛБОЕБ ВЕРНУЛСЯ»)
    DEAD_PAGE_POST_ON_JOIN: bool = _env_bool("DEAD_PAGE_POST_ON_JOIN", False)

    # Max retries for random post picking
    DEAD_PAGE_MAX_FORWARD_RETRIES: int = _env_int("DEAD_PAGE_MAX_FORWARD_RETRIES", 5)

    # GIF counter
    GIF_INTERVAL: int = _env_int("GIF_INTERVAL", 5)
    GIF_PATH: str = os.getenv("GIF_PATH", "media/slavik/slavic_chlen.mp4")

    # Dead page media directory
    DEAD_PAGE_DIR: str = os.getenv("DEAD_PAGE_DIR", "media/dead_page")

    # Alan greeting video (F7)
    ALAN_USERNAME: str = os.getenv("ALAN_USERNAME", "@Alan_Z")
    ALAN_GREETING_DIR: str = os.getenv("ALAN_GREETING_DIR", "media/leha_greeting")
    ALAN_GREETING_COOLDOWN: int = _env_int("ALAN_GREETING_COOLDOWN", 10)

    # Alan silence greeting — send greeting video when Alan was silent >= N hours (0.0 = disabled)
    ALAN_SILENCE_GREETING_HOURS: float = _env_float("ALAN_SILENCE_GREETING_HOURS", 6.0)

    # Admin test commands (Epic 10)
    ADMIN_USER_ID: int = _env_int("ADMIN_USER_ID", 5885953495)

    # ── War Words Alert (F5v2 / Epic 10) ──
    # Comma-separated channel IDs for repost detection
    # Default: "1654872411" (ЧП Пермь / Радар по всей России | БПЛА)
    WAR_CHANNEL_IDS: str = os.getenv("WAR_CHANNEL_IDS", "1654872411")

    # Comma-separated channel usernames (without @) for repost detection
    WAR_CHANNEL_USERNAMES: str = os.getenv("WAR_CHANNEL_USERNAMES", "")

    # Comma-separated reply phrases (random choice). Empty = use built-in defaults.
    WAR_REPLIES: str = os.getenv("WAR_REPLIES", "")

    # ── Slavic Photo (Epic 12) ──
    # Every N "пошёл нахуй" replies → send random media from SLAVIC_RANDOM_DIR
    SLAVIC_PHOTO_INTERVAL: int = _env_int("SLAVIC_PHOTO_INTERVAL", 10)
    SLAVIC_RANDOM_DIR: str = os.getenv("SLAVIC_RANDOM_DIR", "media/slavik/slavik_random")
    # Deprecated — kept for backward compatibility as fallback
    SLAVIC_PHOTO_PATH: str = os.getenv("SLAVIC_PHOTO_PATH", "media/slavic_na_litso.jpg")

    # ── Common Service (Epic 15) ──
    # Cooldown between media sends in the same chat (shared across otboy + danger).
    # 0 = no cooldown (every trigger sends media).
    COMMON_COOLDOWN: float = _env_duration("COMMON_COOLDOWN", "0")

    # Base directory for common media (contains otboy/ and danger/ subdirs).
    COMMON_MEDIA_BASE: str = os.getenv("COMMON_MEDIA_BASE", "media/common")

    # Danger-specific cooldown (Epic 18). Additional restriction on top of shared.
    # Danger sends are blocked if EITHER shared OR danger cooldown is active.
    # 0 = no additional danger restriction (default: 60.0 = 1 minute).
    DANGER_COOLDOWN: float = _env_duration("DANGER_COOLDOWN", "60s")

    # ── Common Service: selfdev/work (Epic 30) ──
    # Пер-сабдир анти-спам (time-format): блокирует только свой сабдир,
    # поверх общего COMMON_COOLDOWN.
    SELFDEV_COOLDOWN: float = _env_duration("SELFDEV_COOLDOWN", "5m")
    WORK_COOLDOWN: float = _env_duration("WORK_COOLDOWN", "5m")

    # ── Epic 52 (T-409, D213): выключатели common-медиа ──
    # Точечный: work-подсервис (media/common/work). false → work_handler
    # возвращает UNHANDLED, триггеры WorkWordFilter остаются зарегистрированными.
    # Прод: false (требование пользователя, T-416).
    COMMON_WORK_MEDIA_ENABLED: bool = _env_bool("COMMON_WORK_MEDIA_ENABLED", True)
    # Глобальный рубильник ВСЕХ common-медиа (otboy/danger/selfdev/work)
    # в единой точке CommonRelay.send_common. На проде НЕ выставляется.
    COMMON_MEDIA_ENABLED: bool = _env_bool("COMMON_MEDIA_ENABLED", True)

    # ── Goodmorning (Epic 30) ──
    GOODMORNING_TIME: str = os.getenv("GOODMORNING_TIME", "07:00")           # HH:MM
    GOODMORNING_TZ: str = os.getenv("GOODMORNING_TZ", "Asia/Yekaterinburg")
    # Пусто = рассылка выключена (планировщик не стартует, WARNING в лог).
    GOODMORNING_TARGET_CHAT_IDS: tuple[int, ...] = _env_int_tuple("GOODMORNING_TARGET_CHAT_IDS", ())
    GOODMORNING_MEDIA_DIR: str = os.getenv("GOODMORNING_MEDIA_DIR", "media/common/goodmorning")

    # Comma-separated danger keywords (case-insensitive, Cyrillic word boundaries).
    # Leave empty to use built-in defaults (135+ words from filters/word_lists.py).
    DANGER_WORDS: str = os.getenv("DANGER_WORDS", "")

    # ── Mimic Feature (common service, §3.1) ──
    # Comma-separated list of user IDs whose messages will be mimicked.
    # Empty or "0" = feature disabled.
    MIMIC_VICTIM_USER_IDS: str = os.getenv("MIMIC_VICTIM_USER_IDS", "138811255")

    # Minimum word count to trigger mimic (strict > N words).
    MIMIC_MIN_WORDS: int = _env_int("MIMIC_MIN_WORDS", 5)

    # Cooldown in seconds between mimic replies per (chat, user).
    MIMIC_COOLDOWN: float = _env_duration("MIMIC_COOLDOWN", "1h")

    # Мимикрировать только обычные сообщения; репосты пропускать (Epic 22 / D52).
    # True = передразнивать и репосты тоже.
    MIMIC_FORWARDS_ENABLED: bool = _env_bool("MIMIC_FORWARDS_ENABLED", False)

    # ── Slavik Mimic (§3.2 — replacement for "пошёл нахуй") ──
    # Minimum word count in Slava's message to use mimic instead of default reply.
    # Set to -1 to disable Slavik mimic entirely.
    SLAVIK_MIMIC_MIN_WORDS: int = _env_int("SLAVIK_MIMIC_MIN_WORDS", 5)

    # Cooldown in seconds between Slavik mimic replies (per chat).
    SLAVIK_MIMIC_COOLDOWN: float = _env_duration("SLAVIK_MIMIC_COOLDOWN", "60s")

    # ── Olya service (Epic 19) ──────────────────────────────────────────
    OLYA_ENABLED: bool = _env_bool("OLYA_ENABLED", True)
    OLYA_USER_ID: int = _env_int("OLYA_USER_ID", 834424825)
    OLYA_COOLDOWN: float = _env_duration("OLYA_COOLDOWN", "60s")
    OLYA_MEDIA_BASE: str = _env_str("OLYA_MEDIA_BASE", "media/olya/cringe")
    # Канальные ID SaveAsBot (репосты MessageOriginChannel). Пусто = каналы не матчим.
    # (523131145 — ID юзера, а не канала: дефолт сменён с (523131145,) на () в Epic 32)
    OLYA_SAVEASBOT_CHANNEL_IDS: tuple[int, ...] = _env_int_tuple("OLYA_SAVEASBOT_CHANNEL_IDS", ())
    OLYA_CAPTION_ENABLED: bool = _env_bool("OLYA_CAPTION_ENABLED", True)
    OLYA_CAPTION_TEXT: str = _env_str("OLYA_CAPTION_TEXT", "Спасибо, что пользуетесь - @SaveAsBot'ом")
    OLYA_REPOST_ENABLED: bool = _env_bool("OLYA_REPOST_ENABLED", True)
    OLYA_MEDIA_TYPE: str = _env_str("OLYA_MEDIA_TYPE", "video")
    OLYA_ALWAYS_SEND: bool = _env_bool("OLYA_ALWAYS_SEND", False)

    # ── Olya service (Epic 32: D100/D101) ──
    # ID юзера/бота SaveAsBot (репосты MessageOriginUser)
    OLYA_SAVEASBOT_USER_IDS: tuple[int, ...] = _env_int_tuple("OLYA_SAVEASBOT_USER_IDS", (523131145,))
    # Доп. триггер: упоминание @SaveAsBot в caption (регистронезависимо)
    OLYA_CAPTION_MENTION_ENABLED: bool = _env_bool("OLYA_CAPTION_MENTION_ENABLED", True)

    # ── SmartModule: Summary (Epic 24) ────────────────────────────
    # LLM provider — OpenAI-compatible API (apinet.cloud by default).
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")                            # R5/D64
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://apinet.cloud/v1")
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "deepseek-v4-flash")
    EMBEDDING_MODEL_NAME: str = os.getenv("EMBEDDING_MODEL_NAME", "gemini-embedding-001")
    LLM_TIMEOUT: float = _env_float("LLM_TIMEOUT", 30.0)   # Epic 47 (56.4): 60.0 → 30.0 (per-request)
    # LLM_MAX_RETRIES сохраняется (default 2): число повторов, попыток = retries + 1 = 3.
    LLM_MAX_RETRIES: int = _env_int("LLM_MAX_RETRIES", 2)
    EMBEDDING_DIM: int = _env_int("EMBEDDING_DIM", 3072)   # Epic 46 (D177): gemini-embedding-001 = 3072
    # ── LLM resilience (Epic 47, Section 56, D191) ──
    LLM_RETRY_BACKOFF_BASE: float = _env_float_min("LLM_RETRY_BACKOFF_BASE", 1.0, 0.0)
    LLM_RETRY_BACKOFF_CAP: float = _env_float_min("LLM_RETRY_BACKOFF_CAP", 8.0, 0.0)
    LLM_RETRY_JITTER_MAX: float = _env_float_min("LLM_RETRY_JITTER_MAX", 2.0, 0.0)
    # Жёсткий дедлайн ВСЕЙ _post (все попытки + сны), asyncio.timeout (56.4).
    LLM_TOTAL_BUDGET: float = _env_float_min("LLM_TOTAL_BUDGET", 60.0, 1.0)
    # ── LLM Circuit Breaker + Fallback (Epic 53, Section 62.6) ──
    # CB: скоуп ТОЛЬКО direct_chat (обёртка в direct_chat_service; llm_client
    # о CB не знает). Порог транзиентных фейлов подряд (5xx/транспорт/таймаут)
    # до OPEN; <1 → дефолт 3 (WARNING).
    LLM_CB_ENABLED: bool = _env_bool("LLM_CB_ENABLED", True)
    LLM_CB_FAILURE_THRESHOLD: int = _env_int_min("LLM_CB_FAILURE_THRESHOLD", 3, 1)
    # Кулдаун OPEN→HALF_OPEN в СЕКУНДАХ (float; прецедент SEARCH_COOLDOWN_SECONDS
    # — НЕ duration). <0 → дефолт 300.0 (WARNING).
    LLM_CB_COOLDOWN_SECONDS: float = _env_float_min("LLM_CB_COOLDOWN_SECONDS", 300.0, 0.0)
    # Фоллбэк-провайдер (опциональный): активен ТОЛЬКО если заданы ВСЕ ТРИ
    # (пусто = выключен — ровно старое поведение). R17: ключ — только в .env,
    # значение НИКОГДА не логируется (только факт configured).
    LLM_FALLBACK_BASE_URL: str = _env_str("LLM_FALLBACK_BASE_URL", "")
    LLM_FALLBACK_MODEL: str = _env_str("LLM_FALLBACK_MODEL", "")
    LLM_FALLBACK_API_KEY: str = _env_str("LLM_FALLBACK_API_KEY", "")
    # ── GraphRAG memorize (Epic 47, Section 56.5) ──
    GRAPH_MEMORIZE_MAX_BATCH_RETRIES: int = _env_int_min("GRAPH_MEMORIZE_MAX_BATCH_RETRIES", 2, 0)
    GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF: float = _env_float_min("GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF", 2.0, 0.0)
    # ── SummaryGenerator (Epic 47, Section 56.6) ──
    SUMMARY_RETRY_ONCE_PAUSE: float = _env_float_min("SUMMARY_RETRY_ONCE_PAUSE", 5.0, 0.0)
    # Feature switch: False = routers not registered, бот работает как раньше.
    SUMMARY_ENABLED: bool = _env_bool("SUMMARY_ENABLED", True)
    # L1: окно генерации (часы).
    SUMMARY_WINDOW_HOURS: float = _env_float("SUMMARY_WINDOW_HOURS", 6.0)
    # L2: хранение сырых сообщений (дни), дальше — сжатие в L3.
    FULL_MEMORY_RETENTION_DAYS: int = _env_int("FULL_MEMORY_RETENTION_DAYS", 30)
    # L3: срок жизни архивных фактов (дни).
    ARCHIVE_MEMORY_RETENTION_DAYS: int = _env_int("ARCHIVE_MEMORY_RETENTION_DAYS", 90)
    # Лимит Telegram: число частей ответа (чанкинг 4096).
    MAX_SUMMARY_PARTS: int = _env_int("MAX_SUMMARY_PARTS", 1)
    SUMMARY_TIMEZONE: str = os.getenv("SUMMARY_TIMEZONE", "Asia/Yekaterinburg")
    # Пусто = /summary разрешена всем (R9/D62).
    ALLOWED_SUMMARY_IDS: tuple[int, ...] = _env_int_tuple("ALLOWED_SUMMARY_IDS", ())
    # Epic 31 (D94): true = /summary только для ADMIN_USER_ID (ALLOWED_SUMMARY_IDS
    # игнорируется); false = всем/по списку (старое поведение).
    SUMMARY_ADMIN_ONLY: bool = _env_bool("SUMMARY_ADMIN_ONLY", False)
    # JSON-словарь алиасов {"<user_id>": "<alias>"} (R7/D61).
    SUMMARY_ALIASES: str = os.getenv("SUMMARY_ALIASES", "")
    SUMMARY_THROTTLE_SECONDS: float = _env_float("SUMMARY_THROTTLE_SECONDS", 60.0)
    SUMMARY_CHUNK_DELAY: float = _env_float("SUMMARY_CHUNK_DELAY", 2.0)
    # Пусто = все чаты, в которых есть сообщения.
    SUMMARY_TARGET_CHAT_IDS: tuple[int, ...] = _env_int_tuple("SUMMARY_TARGET_CHAT_IDS", ())
    SUMMARY_MAX_WINDOW_MESSAGES: int = _env_int("SUMMARY_MAX_WINDOW_MESSAGES", 500)
    SUMMARY_MAX_MESSAGE_CHARS: int = _env_int("SUMMARY_MAX_MESSAGE_CHARS", 2000)
    SUMMARY_MAX_CONTEXT_CHARS: int = _env_int("SUMMARY_MAX_CONTEXT_CHARS", 120000)
    SUMMARY_RAG_L2_LIMIT: int = _env_int("SUMMARY_RAG_L2_LIMIT", 10)
    SUMMARY_RAG_L3_LIMIT: int = _env_int("SUMMARY_RAG_L3_LIMIT", 10)
    SUMMARY_COMPRESS_BATCH: int = _env_int("SUMMARY_COMPRESS_BATCH", 100)

    # ── GraphRAG (Epic 26) ─────────────────────────────────────────
    # False = extraction-вызов при архивации не делается (ровно старое поведение)
    GRAPH_RAG_ENABLED: bool = _env_bool("GRAPH_RAG_ENABLED", True)
    # Инкремент веса ребра при повторном упоминании связи (D70)
    GRAPH_EDGE_WEIGHT_INCREMENT: int = _env_int("GRAPH_EDGE_WEIGHT_INCREMENT", 1)
    # Сколько рёбер-справок подмешивать в /summary (35.5)
    GRAPH_TOP_EDGES_LIMIT: int = _env_int("GRAPH_TOP_EDGES_LIMIT", 5)
    # Максимум триплетов, сохраняемых за один extraction-вызов (35.4)
    GRAPH_EXTRACT_MAX_TRIPLETS: int = _env_int("GRAPH_EXTRACT_MAX_TRIPLETS", 50)

    # ── GraphRAG v2 (Epic 46) ─────────────────────────────────────
    # TTL фактов (search_fact/youtube_content/web_content), дней; отдельно от
    # FULL_MEMORY_RETENTION_DAYS=30 / ARCHIVE_MEMORY_RETENTION_DAYS=90 (D175).
    # chat_history-факты — expires_at NULL (вечно).
    GRAPH_FACT_TTL_DAYS: int = _env_int("GRAPH_FACT_TTL_DAYS", 14)
    # Гибридный RAG (55.6): top-K фактов в контекст.
    GRAPH_RAG_FACTS_LIMIT: int = _env_int("GRAPH_RAG_FACTS_LIMIT", 10)
    # Жёсткий потолок символов XML-контекста RAG (truncate с WARNING).
    GRAPH_RAG_CONTEXT_MAX_CHARS: int = _env_int("GRAPH_RAG_CONTEXT_MAX_CHARS", 2000)

    # ── SmartModule: FactCheck + SmartSearch (Epic 33, D104) ─────
    # Ключи поисковиков. Пусто = уровень каскада отключён (WARNING при старте).
    # Секреты — ТОЛЬКО в .env (R17): не в коде, не в .env.example.
    TAVILY_API_KEY: str = _env_str("TAVILY_API_KEY", "")
    EXA_API_KEY: str = _env_str("EXA_API_KEY", "")
    # Длина LLM-ответа, символы; <100 → дефолт 4000 (WARNING).
    SEARCH_MAX_SYMBOLS: int = _env_int_min("SEARCH_MAX_SYMBOLS", 4000, 100)
    FACTCHECK_MAX_SYMBOLS: int = _env_int_min("FACTCHECK_MAX_SYMBOLS", 4000, 100)
    # Кулдауны per (chat, user) в СЕКУНДАХ (float; прецедент SUMMARY_THROTTLE_SECONDS —
    # НЕ time-format). <0 → дефолт 300.0 (WARNING). 0 = кулдаун выключен.
    SEARCH_COOLDOWN_SECONDS: float = _env_float_min("SEARCH_COOLDOWN_SECONDS", 300.0, 0.0)
    FACTCHECK_COOLDOWN_SECONDS: float = _env_float_min("FACTCHECK_COOLDOWN_SECONDS", 300.0, 0.0)

    # ── SmartModule: YouTube + Web (Epic 37) ──────────────────
    # Длина LLM-ответа И лимит контекста (транскрипт/страница), символы;
    # <100 → дефолт 4000 (WARNING). Прецедент SEARCH_MAX_SYMBOLS (двойное назначение).
    YOUTUBE_MAX_SYMBOLS: int = _env_int_min("YOUTUBE_MAX_SYMBOLS", 4000, 100)
    WEBPAGE_MAX_SYMBOLS: int = _env_int_min("WEBPAGE_MAX_SYMBOLS", 4000, 100)
    # Кулдауны per (chat, user) в СЕКУНДАХ (float; прецедент SEARCH_COOLDOWN_SECONDS —
    # НЕ time-format). <0 → дефолт 300.0 (WARNING). 0 = кулдаун выключен.
    # Раздельные трекеры → троттлинг YouTube и Web НЕЗАВИСИМ (46.9).
    YOUTUBE_COOLDOWN_SECONDS: float = _env_float_min("YOUTUBE_COOLDOWN_SECONDS", 300.0, 0.0)
    WEBPAGE_COOLDOWN_SECONDS: float = _env_float_min("WEBPAGE_COOLDOWN_SECONDS", 300.0, 0.0)

    # ── SmartModule: YouTube engine failover (Epic 39, D142/D144) ──
    # Прокси для ОБОИХ движков (yt-dlp опция proxy; transcript-api proxies
    # {"http": u, "https": u}). Пусто = без прокси. R17: значение НЕ логируется.
    YOUTUBE_TRANSCRIPT_PROXY_URL: str = _env_str("YOUTUBE_TRANSCRIPT_PROXY_URL", "")
    # Путь к Netscape-файлу cookies (yt-dlp cookiefile; transcript-api cookies=).
    # Пусто = без cookies. R17: значение НЕ логируется.
    YOUTUBE_COOKIES_FILE: str = _env_str("YOUTUBE_COOKIES_FILE", "")

    # ── SmartModule: Checkup (Epic 42) ────────────────────────────
    # Кулдаун per-chat в СЕКУНДАХ (float; прецедент SEARCH_COOLDOWN_SECONDS —
    # НЕ time-format). <0 → дефолт 300.0 (WARNING). 0 = выключен.
    CHECKUP_COOLDOWN_SECONDS: float = _env_float_min("CHECKUP_COOLDOWN_SECONDS", 300.0, 0.0)
    # Лимит ОТВЕТА LLM, символы; <100 → дефолт 3000 (WARNING).
    CHECKUP_MAX_SYMBOLS: int = _env_int_min("CHECKUP_MAX_SYMBOLS", 3000, 100)
    # ── Checkup 400 (Epic 49, Section 57.5) ──
    # Потолок user-входа (<system_logs>) в символах после scrub C0; <1000 → 12000 (WARNING).
    CHECKUP_MAX_INPUT_SYMBOLS: int = _env_int_min("CHECKUP_MAX_INPUT_SYMBOLS", 12000, 1000)
    # ── SmartModule: Checkup Betterstack SQL API (Epic 45, D172/D173) ──
    # ClickHouse HTTP-коннекшн (R45-1): POST SQL-тела, Basic auth,
    # FORMAT JSONEachRow (в тексте SQL). Пустые USER/PASSWORD ИЛИ пустой
    # TABLE при пустом QUERY → ступень пропущена (WARNING) → journalctl.
    # Хост — полный URL (порт неявный); не секрет, значение в .env необязательно.
    CHECKUP_BETTERSTACK_SQL_HOST: str = _env_str(
        "CHECKUP_BETTERSTACK_SQL_HOST", "https://eu-fsn-3-connect.betterstackdata.com"
    )
    CHECKUP_BETTERSTACK_SQL_USER: str = _env_str("CHECKUP_BETTERSTACK_SQL_USER", "")
    # R17: значение НИКОГДА не логируется (только факт configured/not configured).
    CHECKUP_BETTERSTACK_SQL_PASSWORD: str = _env_str("CHECKUP_BETTERSTACK_SQL_PASSWORD", "")
    # Префикс сорса логов (t<id>_<source> из карточки коннекшна «Query with»).
    CHECKUP_BETTERSTACK_SQL_TABLE: str = _env_str("CHECKUP_BETTERSTACK_SQL_TABLE", "")
    # Полный SQL-оверрайд (если задан — используется ВМЕСТО шаблона 54.3).
    CHECKUP_BETTERSTACK_SQL_QUERY: str = _env_str("CHECKUP_BETTERSTACK_SQL_QUERY", "")
    CHECKUP_JOURNALCTL_CMD: str = _env_str("CHECKUP_JOURNALCTL_CMD", "journalctl -u admin_bot -n 300 --no-pager")

    # ── /info + /edit_info (Epic 43) ────────────────────────────
    # Кулдаун /info per-chat в СЕКУНДАХ (float; прецедент SEARCH_COOLDOWN_SECONDS).
    # <0 → дефолт 300.0 (WARNING). 0 = выключен.
    INFO_COOLDOWN_SECONDS: float = _env_float_min("INFO_COOLDOWN_SECONDS", 300.0, 0.0)
    # Путь к справке: CWD-относительный или абсолютный; UTF-8 (52.1 #2)
    INFO_TEXT_FILE: str = _env_str("INFO_TEXT_FILE", "info_text.md")

    # ── DirectChat (Epic 50, Section 58) ───────────────────────
    # Epic 52 (T-411, R52-4): keyword-триггер «бот»/«ботохуета»/«ботина»/
    # «ботяра»/«ботик»/«ботохуйня» с word-boundary. false = keyword-ветка молчит
    # (reply на бота и mention работают как раньше).
    DIRECT_CHAT_BOTWORD_ENABLED: bool = _env_bool("DIRECT_CHAT_BOTWORD_ENABLED", True)
    # Epic 60 Фаза E (67.2, T-492, правило п.49): keyword-regex «бот»-семьи —
    # КОНФИГ, не код. Дефолт байт-в-байт равен старому литералу
    # handlers/direct_chat.py (тесты 61.5 зелёные без правок); невалидный
    # regex → WARNING + дефолт при импорте хендлера (бот не падает).
    CHAT_BOTWORD_PATTERN: str = _env_str(
        "CHAT_BOTWORD_PATTERN",
        r"(?i)(?<![0-9a-zа-яё_./])бот(?:ина|яра|ик|охуета|охуйня)?(?![0-9a-zа-яё_])")
    # Последние сообщений чата для фона <Global_Context> (58.6).
    CHAT_GLOBAL_CONTEXT_LIMIT: int = _env_int("CHAT_GLOBAL_CONTEXT_LIMIT", 100)
    # Token Bucket: обращений подряд до кулдауна; <1 → дефолт 3 (WARNING).
    CHAT_BURST_LIMIT: int = _env_int_min("CHAT_BURST_LIMIT", 3, 1)
    # Полное восстановление зарядов после последнего допущенного обращения, сек.
    CHAT_COOLDOWN_SECONDS: float = _env_float_min("CHAT_COOLDOWN_SECONDS", 300.0, 0.0)
    # TTL памяти bot_direct_reply-фактов, дней; пусто/0 = expires_at NULL (вечное).
    CHAT_DIRECT_REPLY_TTL_DAYS: int | None = _env_int_optional("CHAT_DIRECT_REPLY_TTL_DAYS", None)
    # Потолок символов <Global_Context>; <500 → дефолт 4000 (WARNING).
    CHAT_GLOBAL_CONTEXT_MAX_CHARS: int = _env_int_min("CHAT_GLOBAL_CONTEXT_MAX_CHARS", 4000, 500)
    # Глубина рекурсии <Conversation_Thread> (reply-цепочка); <1 → дефолт 6.
    CHAT_THREAD_MAX_DEPTH: int = _env_int_min("CHAT_THREAD_MAX_DEPTH", 6, 1)
    # Потолок символов <Conversation_Thread>; <500 → дефолт 2000 (WARNING).
    CHAT_THREAD_MAX_CHARS: int = _env_int_min("CHAT_THREAD_MAX_CHARS", 2000, 500)

    # ── Smart Cache (Epic 51, Section 59.2) ────────────────────
    # Аварийный рубильник Exact Match Cache. По умолчанию ВЫКЛЮЧЕН (mandate D212):
    # включается явно в прод-.env при деплое (T-407).
    SMART_CACHE_ENABLED: bool = _env_bool("SMART_CACHE_ENABLED", False)
    # TTL кэш-строк, сек; <60 → дефолт 1800 (WARNING).
    SMART_CACHE_TTL_SECONDS: int = _env_int_min("SMART_CACHE_TTL_SECONDS", 1800, 60)
    # Потолок строк таблицы smart_cache; <100 → дефолт 1000 (WARNING).
    SMART_CACHE_MAX_ROWS: int = _env_int_min("SMART_CACHE_MAX_ROWS", 1000, 100)

    # ── Epic 60 Фаза A (Section 63.5, R60-1/R60-2) ─────────────
    # Персистентный троттлинг (throttle_state/bot_replies, 63.1). false →
    # ровно старые in-memory инстансы (аварийный рубильник, прецедент
    # SMART_CACHE_ENABLED). Прод .env: не ставим (63.5).
    THROTTLE_PERSISTENT_ENABLED: bool = _env_bool("THROTTLE_PERSISTENT_ENABLED", True)
    # Таймаут ожидания per-chat замка генерации direct_chat (63.2), СЕКУНДЫ
    # (float; прецедент SEARCH_COOLDOWN_SECONDS — не duration). <0 → дефолт
    # 60.0 (WARNING). Таймаут → CHAT_LOCK_BUSY_PHRASES.
    CHAT_LOCK_WAIT_SECONDS: float = _env_float_min("CHAT_LOCK_WAIT_SECONDS", 60.0, 0.0)
    # Потолок словаря per-chat замков (ленивая чистка незалоченных); <16 →
    # дефолт 256 (WARNING).
    CHAT_LOCK_MAX_ENTRIES: int = _env_int_min("CHAT_LOCK_MAX_ENTRIES", 256, 16)

    # ── Epic 60 Фаза B (Section 64.8, R60-3…R60-9) ─────────────
    # Дедуп фактов при записи (64.1): cosine ≥ HIGH → noop (+подтверждение),
    # [LOW, HIGH) → supersede (старый инвалидируется, новый unconfirmed),
    # < LOW → add. Канон порогов — T-459 тема 6. false → ровно старое поведение.
    GRAPH_DEDUP_ENABLED: bool = _env_bool("GRAPH_DEDUP_ENABLED", True)
    GRAPH_DEDUP_SIMILARITY_HIGH: float = _env_float("GRAPH_DEDUP_SIMILARITY_HIGH", 0.95)
    GRAPH_DEDUP_SIMILARITY_LOW: float = _env_float("GRAPH_DEDUP_SIMILARITY_LOW", 0.85)
    # Бонус веса при noop-подтверждении (64.1.2): weight+bonus, cap 1.0, floor 0.1.
    GRAPH_DEDUP_WEIGHT_BONUS: float = _env_float("GRAPH_DEDUP_WEIGHT_BONUS", 0.1)
    # Антиотравление (64.2): unconfirmed-факты старше N дней выбросит ленивый
    # фоновый пересмотр (66.11); в фазе B — только фильтр выдачи status='confirmed'.
    GRAPH_UNCONFIRMED_RETENTION_DAYS: int = _env_int("GRAPH_UNCONFIRMED_RETENTION_DAYS", 14)
    # Бэкап БД раз в день + текстовый экспорт фактов (64.3). false → джоб не стартует.
    MEMORY_BACKUP_ENABLED: bool = _env_bool("MEMORY_BACKUP_ENABLED", True)
    MEMORY_BACKUP_DIR: str = _env_str("MEMORY_BACKUP_DIR", "backups")
    MEMORY_BACKUP_KEEP: int = _env_int_min("MEMORY_BACKUP_KEEP", 7, 1)
    MEMORY_BACKUP_HOUR: str = _env_str("MEMORY_BACKUP_HOUR", "05:00")
    # Кэш эмбеддингов (64.4): SHA-256-ключ, TTL дней, LRU-cap строк, ленивый
    # last_used_at (≥60с, без write-per-read). false → ровно старое поведение.
    EMBED_CACHE_ENABLED: bool = _env_bool("EMBED_CACHE_ENABLED", True)
    EMBED_CACHE_TTL_DAYS: int = _env_int_min("EMBED_CACHE_TTL_DAYS", 30, 1)
    # Epic 64: 50000 строк × ~6.5 КБ (float16 BLOB) ≈ стационар ~130 МБ;
    # было 50000 × ~46 КБ (JSON) ≈ 2.3 ГБ — источник взрывного роста БД.
    EMBED_CACHE_MAX_ROWS: int = _env_int_min("EMBED_CACHE_MAX_ROWS", 20000, 100)

    # ── Epic 64: ретраи фоллбэка + обслуживание БД ────────────────
    # Фоллбэк-чат: до N повторов транзиентных отказов (429/5xx/транспорт);
    # общий бюджет одной фоллбэк-цепочки (было жёстко 30с — мало при 15с/запрос).
    LLM_FALLBACK_MAX_RETRIES: int = _env_int_min("LLM_FALLBACK_MAX_RETRIES", 2, 0)
    LLM_FALLBACK_TIMEOUT_SECONDS: float = _env_float_min(
        "LLM_FALLBACK_TIMEOUT_SECONDS", 120.0, 1.0)
    # Периодический SQLite WAL-checkpoint(TRUNCATE) — удержание -wal
    # (наблюдался рост до 18 МБ без чекпоинта).
    DB_WAL_CHECKPOINT_ENABLED: bool = _env_bool("DB_WAL_CHECKPOINT_ENABLED", True)
    DB_WAL_CHECKPOINT_HOURS: int = _env_int_min("DB_WAL_CHECKPOINT_HOURS", 6, 1)

    # ── Epic 65: обогащение контекста + реранкинг поиска ──────────
    # Окно последних сообщений чата вокруг цели (NAACL'22: +10 п.т.; SIGIR'26:
    # большой контекст вредит → окно маленькое, блок маркирован НЕ-доказательства).
    FACTCHECK_CONTEXT_MESSAGES: int = _env_int_min("FACTCHECK_CONTEXT_MESSAGES", 6, 0)
    SEARCH_CONTEXT_MESSAGES: int = _env_int_min("SEARCH_CONTEXT_MESSAGES", 6, 0)
    # LLM-реранкинг выдачи (Anthropic Contextual Retrieval: rerank до −67% промахов).
    SEARCH_RERANK_ENABLED: bool = _env_bool("SEARCH_RERANK_ENABLED", True)
    # Метрики здоровья памяти в чекап (64.5): data-секция <memory_health> в
    # user-контенте; CHECKUP_SYSTEM_PROMPT (R42-6) НЕ меняется.
    CHECKUP_MEMORY_METRICS_ENABLED: bool = _env_bool("CHECKUP_MEMORY_METRICS_ENABLED", True)
    # Бегущий конспект (64.6): триггер при CHAT_CONTEXT_FILL_RATIO ×
    # SUMMARY_MAX_WINDOW_MESSAGES; хвост CHAT_RUNNING_SUMMARY_TAIL дословно;
    # TTL RUNNING_SUMMARY_TTL_MINUTES (быстрее окна 6ч — не консервирует контекст).
    CHAT_RUNNING_SUMMARY_ENABLED: bool = _env_bool("CHAT_RUNNING_SUMMARY_ENABLED", True)
    CHAT_CONTEXT_FILL_RATIO: float = _env_float("CHAT_CONTEXT_FILL_RATIO", 0.8)
    CHAT_RUNNING_SUMMARY_TAIL: int = _env_int_min("CHAT_RUNNING_SUMMARY_TAIL", 30, 1)
    RUNNING_SUMMARY_TTL_MINUTES: int = _env_int_min("RUNNING_SUMMARY_TTL_MINUTES", 60, 1)
    # Токены tiktoken (64.7): упреждающий тримминг ТОЛЬКО 3 лимитов сборки
    # direct_chat/summary; фактические лимиты — usage из API-ответа. Пустой
    # токенный при заданном chars → chars-fallback (WARNING). См.
    # services/token_counter.py (resolve_chat_limit).
    TOKENIZER_ENCODING: str = _env_str("TOKENIZER_ENCODING", "o200k_base")
    TOKEN_SAFETY_MULTIPLIER: float = _env_float_min("TOKEN_SAFETY_MULTIPLIER", 1.15, 1.0)
    CHAT_GLOBAL_CONTEXT_MAX_TOKENS: int | None = _env_int_optional("CHAT_GLOBAL_CONTEXT_MAX_TOKENS", None)
    CHAT_THREAD_MAX_TOKENS: int | None = _env_int_optional("CHAT_THREAD_MAX_TOKENS", None)
    SUMMARY_MAX_CONTEXT_TOKENS: int | None = _env_int_optional("SUMMARY_MAX_CONTEXT_TOKENS", None)

    # ── Epic 60 Фаза C (Section 65.11, R60-10…R60-19) ─────────
    # Стачка кулдаунов direct_chat (65.3): N кулдаунов подряд → молчание без
    # фразы. false → стачка не считается (ровно старое поведение).
    CHAT_SILENCE_ENABLED: bool = _env_bool("CHAT_SILENCE_ENABLED", True)
    # Кулдаунов подряд до молчания; <1 → дефолт 5 (WARNING).
    CHAT_SILENCE_AFTER_COOLDOWNS: int = _env_int_min("CHAT_SILENCE_AFTER_COOLDOWNS", 5, 1)
    # Стилевые якоря (65.4): секция <style_anchors> с последними ответами
    # бота из bot_replies. false → секция не строится.
    CHAT_STYLE_ANCHORS_ENABLED: bool = _env_bool("CHAT_STYLE_ANCHORS_ENABLED", True)
    # Сколько последних ответов; <1 → дефолт 3 (WARNING).
    CHAT_STYLE_ANCHORS_COUNT: int = _env_int_min("CHAT_STYLE_ANCHORS_COUNT", 3, 1)
    # Обрезка одного якоря, символов; <1 → дефолт 400 (WARNING).
    CHAT_STYLE_ANCHOR_MAX_CHARS: int = _env_int_min("CHAT_STYLE_ANCHOR_MAX_CHARS", 400, 1)
    # Настроение собеседника (65.9): эвристика по словам → user-блок <mood>
    # ПОСЛЕ <Target_User>. Системный промпт R50-4 НЕ меняется. Списки слов —
    # comma-separated env (правило п.49).
    CHAT_MOOD_ENABLED: bool = _env_bool("CHAT_MOOD_ENABLED", True)
    CHAT_MOOD_NEGATIVE_WORDS: str = _env_str(
        "CHAT_MOOD_NEGATIVE_WORDS",
        "бля,нахуй,заебал,сука,бесит,пидор,гандон,тупой",
    )
    CHAT_MOOD_POSITIVE_WORDS: str = _env_str(
        "CHAT_MOOD_POSITIVE_WORDS",
        "спс,спасибо,класс,топ,кайф,красава,супер",
    )
    # Стриминг саммари (65.6): placeholder «…» → edit-чанки с троттлингом.
    # false — ровно старая отправка (тест-режим, D238). Темп: приват/группа.
    SUMMARY_STREAMING_ENABLED: bool = _env_bool("SUMMARY_STREAMING_ENABLED", False)
    SUMMARY_STREAM_EDIT_INTERVAL_PRIVATE: float = _env_float_min(
        "SUMMARY_STREAM_EDIT_INTERVAL_PRIVATE", 1.0, 0.0)
    SUMMARY_STREAM_EDIT_INTERVAL_GROUP: float = _env_float_min(
        "SUMMARY_STREAM_EDIT_INTERVAL_GROUP", 3.0, 0.0)
    # Индикатор «печатает…» (65.7): ChatActionSender.typing вокруг LLM-точек,
    # без искусственной паузы; гаснет сам (≤5с / при отправке сообщения).
    TYPING_INDICATOR_ENABLED: bool = _env_bool("TYPING_INDICATOR_ENABLED", True)
    TYPING_INTERVAL_SECONDS: float = _env_float("TYPING_INTERVAL_SECONDS", 5.0)
    # Temperature-пресеты (65.8): точный/сбалансированный/болтливый →
    # precise/balanced/chatty. Передаётся только direct_chat (другие
    # пайплайны — дефолт провайдера, ключ в payload НЕ добавляется).
    CHAT_TEMPERATURE_PRECISE: float = _env_float("CHAT_TEMPERATURE_PRECISE", 0.0)
    CHAT_TEMPERATURE_BALANCED: float = _env_float("CHAT_TEMPERATURE_BALANCED", 0.7)
    CHAT_TEMPERATURE_CHATTY: float = _env_float("CHAT_TEMPERATURE_CHATTY", 1.0)
    CHAT_TEMPERATURE_PRESET_DEFAULT: str = _env_str("CHAT_TEMPERATURE_PRESET_DEFAULT", "balanced")

    # ── Epic 60 Фаза D (Section 66.13, R60-20…R60-31) ─────────
    # Веса значимости (66.1): стартовый вес по origin (chat_history — 0.5
    # фиксированный канон); подтверждение — GRAPH_DEDUP_WEIGHT_BONUS (64.1);
    # вес влияет на TTL: expires_at = now + TTL × (0.5 + weight).
    GRAPH_FACT_WEIGHT_DIRECT: float = _env_float("GRAPH_FACT_WEIGHT_DIRECT", 0.7)
    GRAPH_FACT_WEIGHT_ARCHIVE: float = _env_float("GRAPH_FACT_WEIGHT_ARCHIVE", 0.4)
    # Слияние повторяющихся эпизодов (66.2): фоновая задача раз в N дней;
    # пачка кластеров за прогон; потолок фактов в кластере. False = джоб молчит.
    GRAPH_EPISODE_MERGE_ENABLED: bool = _env_bool("GRAPH_EPISODE_MERGE_ENABLED", True)
    GRAPH_EPISODE_MERGE_INTERVAL_DAYS: int = _env_int_min(
        "GRAPH_EPISODE_MERGE_INTERVAL_DAYS", 7, 1)
    GRAPH_EPISODE_MERGE_BATCH: int = _env_int_min("GRAPH_EPISODE_MERGE_BATCH", 20, 1)
    GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER: int = _env_int_min(
        "GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER", 5, 2)
    # Time-decay (66.3): w_eff = weight × 0.5^(Δдней/half_life) от
    # last_confirmed_at; ТОЛЬКО множитель ранга при чтении (не удаление);
    # floor — факт не выпадает из ранга полностью.
    GRAPH_TIME_DECAY_ENABLED: bool = _env_bool("GRAPH_TIME_DECAY_ENABLED", True)
    GRAPH_TIME_DECAY_HALF_LIFE_DAYS: float = _env_float_min(
        "GRAPH_TIME_DECAY_HALF_LIFE_DAYS", 60.0, 1.0)
    GRAPH_TIME_DECAY_FLOOR: float = _env_float_min("GRAPH_TIME_DECAY_FLOOR", 0.1, 0.0)
    # Квота памяти на человека (66.4): лимит прямых фактов (target_user NOT
    # NULL); сверх квоты вытесняется самый лёгкий и старый (weight/(age+1)).
    # 0 = лимит выключен. False = квота не считается.
    GRAPH_USER_QUOTA_ENABLED: bool = _env_bool("GRAPH_USER_QUOTA_ENABLED", True)
    GRAPH_FACTS_PER_USER_QUOTA: int = _env_int_min("GRAPH_FACTS_PER_USER_QUOTA", 50, 0)
    # TTL+LRU touch (66.5): RAG-hit факта продлевает expires_at на N дней,
    # cap — created_at + 2 × базовый TTL (вечное протухание невозможно).
    GRAPH_FACT_TOUCH_ENABLED: bool = _env_bool("GRAPH_FACT_TOUCH_ENABLED", True)
    GRAPH_FACT_TOUCH_EXTEND_DAYS: int = _env_int_min("GRAPH_FACT_TOUCH_EXTEND_DAYS", 7, 1)
    # Сжатие векторов (66.6): int8-колонка для грубого KNN + float-канон с
    # реранком (двухпроходный поиск); backfill = rebuild из кэша эмбеддингов.
    # False → float-only схема (ровно старое поведение).
    VEC_INT8_ENABLED: bool = _env_bool("VEC_INT8_ENABLED", True)
    # MMR-разнообразие (66.8): кандидаты GRAPH_MMR_FETCH_K → greedy MMR
    # λ=GRAPH_MMR_LAMBDA → GRAPH_RAG_FACTS_LIMIT. Только vec-путь; FTS — rank.
    GRAPH_MMR_ENABLED: bool = _env_bool("GRAPH_MMR_ENABLED", True)
    GRAPH_MMR_LAMBDA: float = _env_float("GRAPH_MMR_LAMBDA", 0.6)
    GRAPH_MMR_FETCH_K: int = _env_int_min("GRAPH_MMR_FETCH_K", 20, 1)
    # Периодический пересмотр (66.11): склейка дублей, выброс истёкших/
    # unconfirmed, усечение лога сжатий. False = джоб молчит.
    GRAPH_REVIEW_ENABLED: bool = _env_bool("GRAPH_REVIEW_ENABLED", True)
    GRAPH_REVIEW_INTERVAL_DAYS: int = _env_int_min("GRAPH_REVIEW_INTERVAL_DAYS", 3, 1)
    GRAPH_COMPRESSION_LOG_RETENTION_DAYS: int = _env_int_min(
        "GRAPH_COMPRESSION_LOG_RETENTION_DAYS", 90, 1)
    # Бюджеты контекста direct_chat (66.12): доли от CHAT_CONTEXT_BUDGET_TOKENS
    # (system ~5% не управляется; ответ/запас — рекомендации). False → старые
    # MAX_CHARS/токен-потолки секций (64.7).
    CHAT_CONTEXT_BUDGETS_ENABLED: bool = _env_bool("CHAT_CONTEXT_BUDGETS_ENABLED", True)
    CHAT_CONTEXT_BUDGET_TOKENS: int = _env_int_min("CHAT_CONTEXT_BUDGET_TOKENS", 4000, 100)
    CHAT_BUDGET_MAP_RATIO: float = _env_float("CHAT_BUDGET_MAP_RATIO", 0.05)
    CHAT_BUDGET_GLOBAL_RATIO: float = _env_float("CHAT_BUDGET_GLOBAL_RATIO", 0.30)
    CHAT_BUDGET_THREAD_RATIO: float = _env_float("CHAT_BUDGET_THREAD_RATIO", 0.20)
    CHAT_BUDGET_RAG_RATIO: float = _env_float("CHAT_BUDGET_RAG_RATIO", 0.15)
    CHAT_BUDGET_TARGET_RATIO: float = _env_float("CHAT_BUDGET_TARGET_RATIO", 0.05)
    CHAT_BUDGET_ANCHORS_RATIO: float = _env_float("CHAT_BUDGET_ANCHORS_RATIO", 0.05)
    CHAT_BUDGET_RESPONSE_RATIO: float = _env_float("CHAT_BUDGET_RESPONSE_RATIO", 0.20)
    CHAT_BUDGET_RESERVE_RATIO: float = _env_float("CHAT_BUDGET_RESERVE_RATIO", 0.10)

    # ── Epic 60 Фаза E (Section 67.4, R60-35, T-499 — последним) ──
    # Дедуп одинаковых текстов подряд direct_chat (п.8): ключ
    # «чат+человек+текст» в smart_cache (slug direct_dedup); повтор в течение
    # TTL → повтор сохранённого ответа (или молчание, если в прошлый раз
    # ответа не было). false → ровно старое поведение. Троттлинг остаётся
    # ПЕРВЫМ барьером (D237); SMART_CACHE_ENABLED дедуп НЕ выключает
    # (разные фичи, рубильник только свой).
    CHAT_DEDUP_ENABLED: bool = _env_bool("CHAT_DEDUP_ENABLED", True)
    # TTL дедуп-записи, сек; <1 → дефолт 300 (WARNING).
    CHAT_DEDUP_TTL_SECONDS: int = _env_int_min("CHAT_DEDUP_TTL_SECONDS", 300, 1)

    # ── Epic 66: Cobalt Downloader (Section 70) ──
    # Рубильник фичи «скачай <url>». False = ровно v2.45.0 (облачная сессия,
    # роутер не зарегистрирован). Прод: false, пока Docker не поднят (T-523).
    DOWNLOAD_ENABLED: bool = _env_bool("DOWNLOAD_ENABLED", False)
    # Кулдаун per-(chat,user), time-format s/m/h/d (D264; дефолт 5m с
    # v2.47.2 — Section 75/D278).
    DOWNLOAD_COOLDOWN: float = _env_duration("DOWNLOAD_COOLDOWN", "5m")
    # Self-hosted cobalt (docker-compose, Section 70.2).
    COBALT_API_URL: str = _env_str("COBALT_API_URL", "http://localhost:9000/")
    # Локальный telegram-bot-api (docker-compose). Только при DOWNLOAD_ENABLED=True.
    LOCAL_BOT_API_URL: str = _env_str("LOCAL_BOT_API_URL", "http://localhost:8081")
    # Epic 78 (T-578/D291): хост-путь data-dir локального telegram-bot-api
    # (compose volume ./docker/telegram-bot-api:/var/lib/telegram-bot-api).
    TELEGRAM_API_FILES_DIR: str = _env_str(
        "TELEGRAM_API_FILES_DIR", "docker/telegram-bot-api")
    # Папка скачанных файлов на хосте (чистится автоматически после отправки).
    DOWNLOAD_DIR: str = _env_str("DOWNLOAD_DIR", "media/downloads")
    # Epic 77 (T-574): true = YouTube качаем локальным yt-dlp (+PO Token
    # провайдер :4416); false = возврат на cobalt для всего.
    YTDLP_FOR_YOUTUBE: bool = _env_bool("YTDLP_FOR_YOUTUBE", True)

    # ── Epic 67: VoiceTranscriber (Section 71) ──
    # Рубильник транскрипции voice/video_note. False = роутер не регистрируется.
    ENABLE_VOICE_TRANSCRIPTION: bool = _env_bool("ENABLE_VOICE_TRANSCRIPTION", True)
    # Лимит длительности, сек; больше → TOO_LONG-фраза без скачивания файла.
    VOICE_MAX_DURATION_SECONDS: int = _env_int("VOICE_MAX_DURATION_SECONDS", 600)
    # Каскад Groq → OpenRouter. Секреты ТОЛЬКО в прод .env (R17): значение не
    # логируется; пустой ключ = стратегия пропускается контроллером.
    GROQ_API_KEY: str = _env_str("GROQ_API_KEY", "")
    GROQ_TIMEOUT: float = _env_float("GROQ_TIMEOUT", 10.0)
    OPENROUTER_API_KEY: str = _env_str("OPENROUTER_API_KEY", "")
    OPENROUTER_TIMEOUT: float = _env_float("OPENROUTER_TIMEOUT", 15.0)

    # ── 65.8/65.5: словарь пресетов (канон D247). Определяется ПОСЛЕ
    # класса (dataclass не терпит mutable-полей по умолчанию). ───

    def _normalize_tone_key(self, preset_key: str | None) -> str:
        key = str(preset_key or "").strip().lower()
        if not key:
            key = str(self.CHAT_TEMPERATURE_PRESET_DEFAULT or "balanced").strip().lower()
        return key

    def tone_temperature(self, preset_key: str | None) -> float:
        """65.8: temperature для пресета юзера (пусто → дефолт-пресет)."""
        mapping = {
            "precise": self.CHAT_TEMPERATURE_PRECISE,
            "balanced": self.CHAT_TEMPERATURE_BALANCED,
            "chatty": self.CHAT_TEMPERATURE_CHATTY,
        }
        return mapping.get(self._normalize_tone_key(preset_key),
                           self.CHAT_TEMPERATURE_BALANCED)

    def tone_display_name(self, preset_key: str | None) -> str:
        """65.5: пресет → русское имя для фраз (/tone, /persona)."""
        return Settings._TONE_WORD_BY_KEY.get(
            self._normalize_tone_key(preset_key), "сбалансированный")

    @classmethod
    def tone_preset_key(cls, word: str) -> str | None:
        """65.5: русское слово тона → ключ пресета; None — неизвестный."""
        return Settings._TONE_KEY_BY_WORD.get(str(word or "").strip().lower())


Settings._TONE_KEY_BY_WORD = {
    "точный": "precise",
    "сбалансированный": "balanced",
    "болтливый": "chatty",
}
Settings._TONE_WORD_BY_KEY = {v: k for k, v in Settings._TONE_KEY_BY_WORD.items()}


settings = Settings()


def build_ytdlp_base_opts() -> dict:
    """Epic 72 (Section 74.A): общие yt-dlp опции прокси/cookies — ЕДИНЫЙ
    источник для services/youtube_transcript_engine.py и tools/video_downloader.py.
    Пустые настройки → ключи отсутствуют (поведение «без прокси», D142).
    R17: значения НЕ логируются."""
    opts: dict = {}
    proxy = (settings.YOUTUBE_TRANSCRIPT_PROXY_URL or "").strip()
    if proxy:
        opts["proxy"] = proxy
    cookies = (settings.YOUTUBE_COOKIES_FILE or "").strip()
    if cookies:
        opts["cookiefile"] = cookies
    return opts
