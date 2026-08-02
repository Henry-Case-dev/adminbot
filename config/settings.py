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
    DEAD_PAGE_COOLDOWN_SECONDS: int = _env_int("DEAD_PAGE_COOLDOWN_SECONDS", 10)

    # Keep join trigger?
    DEAD_PAGE_POST_ON_JOIN: bool = os.getenv("DEAD_PAGE_POST_ON_JOIN", "True").lower() in ("true", "1", "yes")

    # Max retries for random post picking
    DEAD_PAGE_MAX_FORWARD_RETRIES: int = _env_int("DEAD_PAGE_MAX_FORWARD_RETRIES", 5)

    # GIF counter
    GIF_INTERVAL: int = _env_int("GIF_INTERVAL", 5)
    GIF_PATH: str = os.getenv("GIF_PATH", "media/slavic_chlen.mp4")

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
    COMMON_COOLDOWN_SECONDS: float = _env_float("COMMON_COOLDOWN_SECONDS", 0)

    # Base directory for common media (contains otboy/ and danger/ subdirs).
    COMMON_MEDIA_BASE: str = os.getenv("COMMON_MEDIA_BASE", "media/common")

    # Danger-specific cooldown (Epic 18). Additional restriction on top of shared.
    # Danger sends are blocked if EITHER shared OR danger cooldown is active.
    # 0 = no additional danger restriction (default: 60.0 = 1 minute).
    DANGER_COOLDOWN_SECONDS: float = _env_float("DANGER_COOLDOWN_SECONDS", 60.0)

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
    MIMIC_COOLDOWN_SECONDS: float = _env_float("MIMIC_COOLDOWN_SECONDS", 60.0)

    # ── Slavik Mimic (§3.2 — replacement for "пошёл нахуй") ──
    # Minimum word count in Slava's message to use mimic instead of default reply.
    # Set to -1 to disable Slavik mimic entirely.
    SLAVIK_MIMIC_MIN_WORDS: int = _env_int("SLAVIK_MIMIC_MIN_WORDS", 5)

    # Cooldown in seconds between Slavik mimic replies (per chat).
    SLAVIK_MIMIC_COOLDOWN_SECONDS: float = _env_float("SLAVIK_MIMIC_COOLDOWN_SECONDS", 60.0)

    # ── Olya service (Epic 19) ──────────────────────────────────────────
    OLYA_ENABLED: bool = _env_bool("OLYA_ENABLED", True)
    OLYA_USER_ID: int = _env_int("OLYA_USER_ID", 834424825)
    OLYA_COOLDOWN_SECONDS: float = _env_float("OLYA_COOLDOWN_SECONDS", 60.0)
    OLYA_MEDIA_BASE: str = _env_str("OLYA_MEDIA_BASE", "media/olya/cringe")
    OLYA_SAVEASBOT_CHANNEL_IDS: tuple[int, ...] = _env_int_tuple("OLYA_SAVEASBOT_CHANNEL_IDS", (523131145,))
    OLYA_CAPTION_ENABLED: bool = _env_bool("OLYA_CAPTION_ENABLED", True)
    OLYA_CAPTION_TEXT: str = _env_str("OLYA_CAPTION_TEXT", "Спасибо, что пользуетесь - @SaveAsBot'ом")
    OLYA_REPOST_ENABLED: bool = _env_bool("OLYA_REPOST_ENABLED", True)
    OLYA_MEDIA_TYPE: str = _env_str("OLYA_MEDIA_TYPE", "video")
    OLYA_ALWAYS_SEND: bool = _env_bool("OLYA_ALWAYS_SEND", True)


settings = Settings()
