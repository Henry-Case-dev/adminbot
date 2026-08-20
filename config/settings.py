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
    # LLM provider — OpenAI-compatible API (apinet.cloud hub by default).
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


settings = Settings()
