"""GoodmorningRelay — утренняя рассылка медиа (Epic 30, R30-3, D88/D93).

Plain-send БЕЗ reply/quote (прецедент OlyaRelay): бот просто будит чат,
цитировать спящих нечем — они ещё не написали ничего умного.

Типы (D93): photo/video/animation — С caption; audio/voice — skip с
WARNING (caption им недоступен, а молча будить — грубо); unsupported —
debug-skip. Пустая/отсутствующая папка → WARNING + False.
Регистр расширения не мешает: `goodmorning_05_gif.MP4` → animation
по gif-маркеру (suffix.lower() + word-boundary детект, как в CommonRelay).
"""
import logging
import random
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from services.goodmorning_captions import pick_caption

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


class GoodmorningRelay:
    """Epic 30: утренняя рассылка — случайное медиа + caption, plain-send."""

    def __init__(self, bot: Bot, media_dir: str) -> None:
        self._bot = bot
        self._media_dir = media_dir

    def _detect_media_type(self, filepath: Path) -> str | None:
        """Тип файла по расширению + gif-маркер в имени.

        КОПИЯ логики CommonRelay (прецедент дублирования: OlyaRelay,
        ARCHITECTURE 4.3; вынос в media_utils — будущий рефакторинг,
        вне скоупа). suffix.lower() + word-boundary gif-детект (D93).
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

    def _scan_directory(self) -> list[tuple[Path, str]]:
        """Скан GOODMORNING_MEDIA_DIR.

        Только photo/video/animation (D93): audio/voice → WARNING + SKIP;
        unsupported → debug-skip; пустая/отсутствующая папка → WARNING + [].
        """
        base = Path(self._media_dir)
        if not base.exists() or not base.is_dir():
            logger.warning(
                "Goodmorning: media directory not found %s — рассылка без завтрака",
                base,
            )
            return []

        files: list[tuple[Path, str]] = []
        for entry in base.iterdir():
            try:
                if not entry.is_file():
                    continue
                media_type = self._detect_media_type(entry)
                if media_type in (MEDIA_PHOTO, MEDIA_VIDEO, MEDIA_ANIMATION):
                    files.append((entry, media_type))
                elif media_type in (MEDIA_AUDIO, MEDIA_VOICE):
                    # D93: caption недоступен — будить музыкой молча нельзя
                    logger.warning(
                        "Goodmorning: %s skipped — caption недоступен (D93)",
                        entry.name,
                    )
                else:
                    logger.debug(
                        "Goodmorning: skipping unsupported file %s", entry.name
                    )
            except OSError:
                logger.warning(
                    "Goodmorning: cannot access entry %s — skipping", entry
                )
                continue

        if not files:
            logger.warning(
                "Goodmorning: no sendable media in %s — утро отменяется", base
            )
            return []

        logger.info(
            "Goodmorning: scanned %s — found %d files: %s",
            base,
            len(files),
            [(f.name, mt) for f, mt in files],
        )
        return files

    async def send_goodmorning(self, chat_id: int) -> bool:
        """Случайный файл + случайная капция, plain-send БЕЗ ReplyParameters.

        Returns:
            True — отправлено; False — нечего отправлять или ошибка
            (лог + False, job не падает).
        """
        files = self._scan_directory()
        if not files:
            return False

        filepath, media_type = random.choice(files)
        caption = pick_caption()
        input_file = FSInputFile(str(filepath))

        try:
            if media_type == MEDIA_PHOTO:
                await self._bot.send_photo(
                    chat_id=chat_id, photo=input_file, caption=caption
                )
            elif media_type == MEDIA_VIDEO:
                await self._bot.send_video(
                    chat_id=chat_id, video=input_file, caption=caption
                )
            elif media_type == MEDIA_ANIMATION:
                await self._bot.send_animation(
                    chat_id=chat_id, animation=input_file, caption=caption
                )
            else:
                raise ValueError(f"Unknown media_type: {media_type}")
        except Exception:
            logger.exception(
                "Goodmorning: send failed | chat_id=%s | file=%s | type=%s",
                chat_id,
                filepath.name,
                media_type,
            )
            return False

        logger.info(
            "Goodmorning: sent | chat_id=%s | file=%s | type=%s | caption=%r",
            chat_id,
            filepath.name,
            media_type,
            caption,
        )
        return True
