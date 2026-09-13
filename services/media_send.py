"""Раунд 10.15 (F8, T-1614/ADR-1015-3 §6) — общая отправка медиа-файла.

Тонкий враппер над существующим `handlers/video_download._send_file`
(FSInputFile + supports_streaming=True, реплай, фолбэк на документ) без
импорта хендлера в сервисный слой (риск layering §12). Используется
инструментом `download_media` (tool_router): бэкенд сам шлёт MP4 в Telegram,
а в LLM возвращается фиктивный `tool_response` (модель не «печатает» видео).

Файл НЕ удаляется здесь — очистку делает вызывающий (finally).
"""
import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)


async def send_media(bot, chat_id: int, path: Path,
                     reply_to: int | None = None,
                     caption: str | None = None) -> None:
    """Отправить файл в чат (видео со streaming; фолбэк — документ).

    R17: в логи — только chat_id/имя файла, без URL/подписи.
    """
    file = FSInputFile(str(Path(path).absolute()))
    try:
        if reply_to:
            await bot.send_video(chat_id, file, supports_streaming=True,
                                 caption=caption,
                                 reply_to_message_id=reply_to)
        else:
            await bot.send_video(chat_id, file, supports_streaming=True,
                                 caption=caption)
    except TelegramBadRequest:
        # таргет реплая исчез / тип не видео — шлём документом
        try:
            if reply_to:
                await bot.send_document(
                    chat_id, FSInputFile(str(Path(path).absolute())),
                    reply_to_message_id=reply_to, caption=caption)
            else:
                await bot.send_document(
                    chat_id, FSInputFile(str(Path(path).absolute())),
                    caption=caption)
        except TelegramBadRequest:
            await bot.send_document(chat_id,
                                    FSInputFile(str(Path(path).absolute())))
    logger.info("[media_send] sent | chat=%s", chat_id)
