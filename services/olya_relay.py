"""OlyaRelay — plain media sender for Olya service (NO reply, NO quote)."""

import logging
import random
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)


class OlyaRelay:
    """Sends random media from a flat directory, without reply or quoting."""

    MEDIA_PHOTO = "photo"
    MEDIA_VIDEO = "video"
    MEDIA_ANIMATION = "animation"
    MEDIA_AUDIO = "audio"
    MEDIA_VOICE = "voice"

    EXTENSION_MAP = {
        ".jpg": MEDIA_PHOTO,
        ".jpeg": MEDIA_PHOTO,
        ".png": MEDIA_PHOTO,
        ".webp": MEDIA_PHOTO,
        ".bmp": MEDIA_PHOTO,
        ".mp4": MEDIA_VIDEO,
        ".mov": MEDIA_VIDEO,
        ".webm": MEDIA_VIDEO,
        ".mp3": MEDIA_AUDIO,
        ".ogg": MEDIA_VOICE,
    }

    def __init__(self, bot: Bot, cooldown_seconds: float, media_base: str) -> None:
        self._bot = bot
        self._cooldown_seconds = cooldown_seconds
        self._media_base = Path(media_base)
        self._last_sent: dict[int, float] = {}

    def _scan_directory(self) -> list[Path]:
        """Scan the media directory for all supported files (flat, non-recursive)."""
        if not self._media_base.is_dir():
            return []
        files: list[Path] = []
        for f in self._media_base.iterdir():
            try:
                if f.is_file() and f.suffix.lower() in self.EXTENSION_MAP:
                    files.append(f)
            except OSError:
                logger.warning("OlyaRelay: cannot access entry | entry=%s", f, exc_info=True)
        return files

    def _detect_media_type(self, filepath: Path) -> str:
        """Detect media type from file extension and GIF marker in name (word-boundary match)."""
        ext = filepath.suffix.lower()
        base_type = self.EXTENSION_MAP.get(ext, self.MEDIA_VIDEO)

        fname = filepath.name.lower()
        if "_gif" in fname or fname.startswith("gif") or ".gif." in fname:
            if base_type == self.MEDIA_VIDEO:
                return self.MEDIA_ANIMATION

        return base_type

    async def _send_file(self, chat_id: int, filepath: Path, media_type: str) -> bool:
        """Send a file WITHOUT reply or quoting (plain send)."""
        try:
            input_file = FSInputFile(str(filepath))
            if media_type == self.MEDIA_PHOTO:
                await self._bot.send_photo(chat_id, photo=input_file)
            elif media_type == self.MEDIA_VIDEO:
                await self._bot.send_video(chat_id, video=input_file)
            elif media_type == self.MEDIA_ANIMATION:
                await self._bot.send_animation(chat_id, animation=input_file)
            elif media_type == self.MEDIA_AUDIO:
                await self._bot.send_audio(chat_id, audio=input_file)
            elif media_type == self.MEDIA_VOICE:
                await self._bot.send_voice(chat_id, voice=input_file)
            else:
                return False
            return True
        except Exception:
            logger.exception("OlyaRelay: _send_file failed | type=%s | file=%s | chat=%s",
                             media_type, filepath, chat_id)
            return False

    async def send_olya(self, chat_id: int) -> bool:
        """Main entry: pick random file and send it with cooldown check."""
        now = time.monotonic()
        if chat_id in self._last_sent:
            elapsed = now - self._last_sent[chat_id]
            if elapsed < self._cooldown_seconds:
                return False

        files = self._scan_directory()
        if not files:
            return False

        chosen = random.choice(files)
        media_type = self._detect_media_type(chosen)

        success = await self._send_file(chat_id, chosen, media_type)
        if success:
            self._last_sent[chat_id] = now
        return success
