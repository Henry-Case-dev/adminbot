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

    # Scheduler
    MORNING_HOUR: int = _env_int("MORNING_HOUR", 10)
    EVENING_HOUR: int = _env_int("EVENING_HOUR", 20)
    POLL_INTERVAL: int = _env_int("POLL_INTERVAL", 60)

    # GIF counter
    GIF_INTERVAL: int = _env_int("GIF_INTERVAL", 5)
    GIF_PATH: str = os.getenv("GIF_PATH", "media/slavic_chlen.mp4")

    # Dead page
    DEAD_PAGE_DIR: str = os.getenv("DEAD_PAGE_DIR", "media/dead_page")


settings = Settings()
