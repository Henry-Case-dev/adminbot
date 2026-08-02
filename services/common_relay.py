"""CommonRelay — unified media service for otboy + danger sub-services.

Sends random media files from media/common/{subdir}/ directories.
Supports five media types, auto-detected from file extension and name:
  - photo:  .jpg, .jpeg, .png, .webp, .bmp
  - video:  .mp4, .mov, .webm WITHOUT "gif" in filename
  - animation: .mp4, .mov, .webm WITH "gif" in filename
  - audio:  .mp3
  - voice:  .ogg

Shared cooldown across all sub-services (otboy + danger).
Per-chat in-memory cooldown (dict[int, float]), no DB.
"""
import logging
import random
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, ReplyParameters

from config.settings import settings

logger = logging.getLogger(__name__)

MEDIA_PHOTO = "photo"
MEDIA_VIDEO = "video"
MEDIA_ANIMATION = "animation"
MEDIA_AUDIO = "audio"
MEDIA_VOICE = "voice"

_IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".webm"}
_AUDIO_EXTENSIONS: set[str] = {".mp3"}
_VOICE_EXTENSIONS: set[str] = {".ogg"}


class CommonRelay:
    """Sends random media files from common subdirectories.

    Supports three media types, auto-detected from file extension and name.
    Shared cooldown across all sub-services (otboy + danger).

    Attributes:
        _cooldowns: Per-chat cooldown timestamps (chat_id → time.monotonic()).
    """

    def __init__(
        self,
        bot: Bot,
        cooldown_seconds: float,
        danger_cooldown_seconds: float = 0,
        media_base: str | None = None,
    ) -> None:
        """Initialise CommonRelay.

        Args:
            bot: aiogram Bot instance for sending media.
            cooldown_seconds: Shared cooldown in seconds (0 = disabled).
            danger_cooldown_seconds: Danger-specific cooldown in seconds (0 = no extra restriction).
            media_base: Base directory for media files (default: settings.COMMON_MEDIA_BASE).
        """
        self._bot = bot
        self._cooldown_seconds = cooldown_seconds
        self._danger_cooldown_seconds = danger_cooldown_seconds
        self._media_base = media_base or settings.COMMON_MEDIA_BASE
        self._cooldowns: dict[int, float] = {}
        self._danger_cooldowns: dict[int, float] = {}

    def _detect_media_type(self, filepath: Path) -> str | None:
        """Determine media type from file extension and filename.

        Returns one of MEDIA_PHOTO, MEDIA_VIDEO, MEDIA_ANIMATION,
        MEDIA_AUDIO, MEDIA_VOICE, or None for unsupported file types.
        """
        ext = filepath.suffix.lower()
        if ext in _IMAGE_EXTENSIONS:
            return MEDIA_PHOTO
        if ext in _VIDEO_EXTENSIONS:
            fname = filepath.name.lower()
            if "_gif" in fname or fname.startswith("gif") or ".gif." in fname:
                return MEDIA_ANIMATION
            return MEDIA_VIDEO
        if ext in _AUDIO_EXTENSIONS:
            return MEDIA_AUDIO
        if ext in _VOICE_EXTENSIONS:
            return MEDIA_VOICE
        return None

    def _scan_directory(self, subdir: str) -> list[tuple[Path, str]]:
        """Scan media/common/{subdir}/ for supported media files.

        Args:
            subdir: Subdirectory name (e.g. "otboy", "danger").

        Returns:
            List of (path, media_type) tuples. Empty list if directory
            is missing or has no supported files (graceful degradation).
        """
        base = Path(self._media_base) / subdir
        if not base.exists():
            logger.warning(
                "CommonRelay: directory not found %s — skipping",
                base,
            )
            return []

        files: list[tuple[Path, str]] = []
        for entry in base.iterdir():
            try:
                if not entry.is_file():
                    continue
                media_type = self._detect_media_type(entry)
                if media_type is not None:
                    files.append((entry, media_type))
                else:
                    logger.debug(
                        "CommonRelay: skipping unsupported file %s in %s",
                        entry.name,
                        subdir,
                    )
            except OSError:
                logger.warning(
                    "CommonRelay: cannot access entry %s in %s — skipping",
                    entry,
                    subdir,
                )
                continue

        logger.info(
            "CommonRelay: scanned %s — found %d supported files: %s",
            base,
            len(files),
            [(f.name, mt) for f, mt in files],
        )

        if not files:
            logger.warning(
                "CommonRelay: no supported media files in %s",
                base,
            )
            return []

        return files

    async def _send_by_type(
        self,
        chat_id: int,
        message_id: int,
        matched_word: str,
        filepath: Path,
        media_type: str,
    ) -> None:
        """Dispatch to the correct bot.send_* method based on media_type.

        Args:
            chat_id: Target chat.
            message_id: Original message to reply to.
            matched_word: Word to quote in the reply.
            filepath: Path to the media file.
            media_type: One of MEDIA_PHOTO, MEDIA_VIDEO, MEDIA_ANIMATION,
                        MEDIA_AUDIO, MEDIA_VOICE.
        """
        reply_params = ReplyParameters(
            message_id=message_id,
            quote=matched_word,
        )
        input_file = FSInputFile(str(filepath))

        if media_type == MEDIA_PHOTO:
            await self._bot.send_photo(
                chat_id=chat_id,
                photo=input_file,
                reply_parameters=reply_params,
            )
        elif media_type == MEDIA_VIDEO:
            await self._bot.send_video(
                chat_id=chat_id,
                video=input_file,
                reply_parameters=reply_params,
            )
        elif media_type == MEDIA_ANIMATION:
            await self._bot.send_animation(
                chat_id=chat_id,
                animation=input_file,
                reply_parameters=reply_params,
            )
        elif media_type == MEDIA_AUDIO:
            await self._bot.send_audio(
                chat_id=chat_id,
                audio=input_file,
                reply_parameters=reply_params,
            )
        elif media_type == MEDIA_VOICE:
            await self._bot.send_voice(
                chat_id=chat_id,
                voice=input_file,
                reply_parameters=reply_params,
            )
        else:
            raise ValueError(f"Unknown media_type: {media_type}")

    async def send_common(
        self,
        chat_id: int,
        message_id: int,
        matched_word: str,
        subdir: str,
    ) -> None:
        """Send random media from media/common/{subdir}/ as a reply.

        Shared cooldown across all sub-services — if any sub-service
        recently sent in this chat, all are blocked.

        Args:
            chat_id: Target chat.
            message_id: Message to reply to.
            matched_word: Word to quote (original case preserved).
            subdir: Subdirectory under media/common/ (e.g. "otboy", "danger").
        """
        now = time.monotonic()

        if subdir == "danger" and self._danger_cooldown_seconds > 0:
            last_danger = self._danger_cooldowns.get(chat_id)
            if last_danger is not None:
                elapsed = now - last_danger
                if elapsed < self._danger_cooldown_seconds:
                    logger.info(
                        "CommonRelay: danger_cooldown_active | chat_id=%s | "
                        "elapsed=%.1fs | remaining=%.1fs",
                        chat_id,
                        elapsed,
                        self._danger_cooldown_seconds - elapsed,
                    )
                    return

        if self._cooldown_seconds > 0:
            last_sent = self._cooldowns.get(chat_id)
            if last_sent is not None:
                elapsed = now - last_sent
                if elapsed < self._cooldown_seconds:
                    logger.info(
                        "CommonRelay: cooldown_active | chat_id=%s | subdir=%s | "
                        "elapsed=%.1fs | remaining=%.1fs",
                        chat_id,
                        subdir,
                        elapsed,
                        self._cooldown_seconds - elapsed,
                    )
                    return

        try:
            files = self._scan_directory(subdir)
        except (PermissionError, OSError):
            logger.exception(
                "CommonRelay: scan error for subdir=%s | chat_id=%s",
                subdir,
                chat_id,
            )
            return

        if not files:
            return

        filepath, media_type = random.choice(files)
        logger.info(
            "CommonRelay: picked %s (%s) from %s | chat_id=%s",
            filepath.name,
            media_type,
            subdir,
            chat_id,
        )

        try:
            await self._send_by_type(
                chat_id=chat_id,
                message_id=message_id,
                matched_word=matched_word,
                filepath=filepath,
                media_type=media_type,
            )
            self._cooldowns[chat_id] = now
            if subdir == "danger":
                self._danger_cooldowns[chat_id] = now
            logger.info(
                "CommonRelay: sent | chat_id=%s | subdir=%s | "
                "file=%s | type=%s | matched_word=%r",
                chat_id,
                subdir,
                filepath.name,
                media_type,
                matched_word,
            )
        except Exception:
            logger.exception(
                "CommonRelay: send failed | chat_id=%s | subdir=%s | "
                "file=%s | type=%s",
                chat_id,
                subdir,
                filepath.name,
                media_type,
            )
