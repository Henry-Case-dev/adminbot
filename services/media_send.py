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
from aiogram.types import FSInputFile, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)

# ── Единое меню качества (T-1679, раунд 10.17 F2; ревью-итер.1 M3) ──────────
# Fast-Track (`handlers/video_download.py`, callback `vd:`) и tool-путь
# (`services/tool_router.py`, callback `tdq:`) ДЕЛЯТ один построитель меню:
# раскладка/подписи/заголовок задаются здесь, поведение двух путей не дрейфует.
QUALITY_ROW_SIZE = 3
_QUALITY_PROMPT = "выбери качество:"


def build_quality_keyboard(qualities,
                           callback_prefix: str) -> InlineKeyboardMarkup:
    """Клавиатура «{h}p» рядами по `QUALITY_ROW_SIZE`.

    Кнопка: `text` = строка качества из probe (напр. `"1080p"`),
    `callback_data` = `f"{callback_prefix}{height}"` (напр. `vd:1080`/`tdq:1080`).
    """
    builder = InlineKeyboardBuilder()
    for quality in qualities:
        text = str(quality)
        builder.button(text=text, callback_data=f"{callback_prefix}{text[:-1]}")
    builder.adjust(QUALITY_ROW_SIZE)
    return builder.as_markup()


def quality_menu_text(title) -> str:
    """Заголовок меню: необязательный title (≤200) + «выбери качество:»."""
    header = f"{str(title)[:200]}\n\n" if title else ""
    return f"{header}{_QUALITY_PROMPT}"


async def send_quality_menu(bot, chat_id: int, *, reply_to, title, qualities,
                            callback_prefix: str) -> None:
    """Отправить меню качества реплаем на триггер (R17: без URL/текстов)."""
    await bot.send_message(
        chat_id,
        quality_menu_text(title),
        reply_markup=build_quality_keyboard(qualities, callback_prefix),
        reply_to_message_id=reply_to,
        disable_web_page_preview=True,
    )


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
