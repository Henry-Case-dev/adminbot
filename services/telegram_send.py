"""F6 (T-2065, ADR-1022-6 §2.2) — обёртки отправки в Telegram (egress).

Любой модель-сгенерированный текст перед ``send``/``edit`` проходит
``services.outgoing_guard.sanitize_outgoing`` (режет технические теги).
Обёртки — единый chokepoint egress; ``SEND_POINTS`` — реестр точек,
переведённых на обёртки (тест покрытия сверяет реестр со сканом кода).
Caption-точки (``send_caption``/``edit_caption``) — вне контура egress:
подписи к медиа формируются без модели и в реестр/скан не входят.

Рубильник ``TELEGRAM_SEND_GUARD_ENABLED`` (env-only, default ON): OFF →
обёртки ведут себя как прямой вызов (байт-в-байт 10.21).
"""
from __future__ import annotations

import html as _html
import logging
import re
from typing import Any

from config.settings import settings
from services.outgoing_guard import sanitize_outgoing

logger = logging.getLogger(__name__)

# Раунд 10.23 (F6, ADR-1023-6): id вложения-обложки Article. Используется в
# `InputRichMessageMedia(id=…)` и ссылке `<img src="tg://photo?id=…">`.
SUMMARY_COVER_MEDIA_ID = "summary_cover"

# Структурные маркеры rich-контента (Сценарий Б: Markdown/HTML/таблицы).
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S", re.MULTILINE)
_MD_FENCE_RE = re.compile(r"^\s*```", re.MULTILINE)
_HTML_BLOCK_RE = re.compile(
    r"<(?:table|thead|tbody|tr|td|th|h[1-6]|ul|ol|li|div|blockquote|pre)\b",
    re.IGNORECASE,
)

# Реестр send-точек, переведённых на обёртки: модуль → имена функций.
# Тест покрытия (`tests/test_outgoing_guard_round1022.py`) сверяет реестр с
# реальными вызовами `send_message`/`edit_text` в исходниках.
SEND_POINTS: dict[str, tuple[str, ...]] = {
    "services/smartmodule_utils.py": ("_send_once",),
    "services/summary_generator.py": (
        "_send_streaming", "_send_chunked", "_send_one_chunk", "_send_ux",
        "send_rich_message",
    ),
}

# Точки, которые НЕ проходят guard осознанно: статические/UX/медиа-строки без
# модель-сгенерированного текста (allowlist с обоснованием).
SEND_ALLOWLIST: dict[str, str] = {
    "handlers/slava_presence.py": "статичное приветствие участника",
    "handlers/video_download.py": "UX-фразы прогресса и ошибок видео",
    "handlers/summary.py": "UX-фраза busy/ошибки",
    "services/dead_page_relay.py": "реле-текст готового поста (источник: канал)",
    "services/media_send.py": "медиа-отправка без LLM-текста",
    "services/mimic_relay.py": "релей фиксированных фраз мимикрии",
    "services/nostalgia_worker.py": "детерминированная справка ностальгии",
    "services/progress_reporter.py": "UX-прогресс Long Task",
    # Раунд 10.22 (ревью, Low): расширенный скан `_SEND_RE`
    # (`*.reply(`/`*.answer(`) — сервисные/UX-ответы вне Stage-2 System 2.
    "handlers/admin_commands.py": "админ-команды: служебные/реле-ответы",
    "handlers/dead_page_delete.py": "UX-подтверждение удаления dead-page",
    "handlers/debug_config.py": "диагностический вывод конфига (admin-only)",
    "handlers/menu.py": "текст главного WebApp-меню",
    # S10.22-3: обоснование уточнено — здесь не только UX-фразы, но и результат
    # ASR (`_process`): это НЕ текст Stage-2 LLM. Транскрипт экранируется
    # `html.escape` перед отправкой (`parse_mode=HTML`), поэтому raw-теги
    # `<thought>` недостижимы как разметка; латинские ID-маркеры `fact:`/`msg:`
    # в русскоязычном ASR не порождаются.
    "handlers/voice_transcription.py": (
        "UX-фразы + ASR-транскрипт (не Stage-2 LLM; html.escape)"),
    "services/summary_throttling.py": "UX-фраза busy саммари",
    "handlers/alan.py": "персона-триггер: фиксированный реле-текст",
    "handlers/kostik.py": "персона-триггер: фиксированный реле-текст",
    "handlers/slavik.py": "персона-триггер: фиксированный реле-текст",
    "handlers/vasya.py": "персона-триггер: фиксированный реле-текст",
    "handlers/war_alert.py": "персона-триггер: фиксированный реле-текст",
    # Раунд 10.23 (F5, ADR-1023-5 §D6): сгенерированное изображение —
    # байты без LLM-текста (подписи нет), в Telegram не уходит keyed-URL.
    "services/image_generation.py": "сгенерированное изображение, байты без LLM-текста",
    # Раунд 10.23 (F6, ADR-1023-6 §Decision 6): rich-точка `bot.send_rich_message`
    # в Справке — текст админ-канон/PG (не Stage-2 LLM-текст), правится только
    # `/edit_info`; rich-текст саммари идёт через обёртку `send_rich_message`.
    "handlers/info.py": "текст справки — админ-канон/PG, не Stage-2 LLM",
}


def _guard_enabled() -> bool:
    return bool(getattr(settings, "TELEGRAM_SEND_GUARD_ENABLED", True))


def _maybe_sanitize(text: str) -> str:
    if not _guard_enabled():
        return text
    return sanitize_outgoing(text)


async def send_text(bot, chat_id: int, text: str, **kwargs: Any):
    """``sanitize_outgoing`` → ``bot.send_message``."""
    return await bot.send_message(chat_id, _maybe_sanitize(text), **kwargs)


async def edit_text_safe(message, text: str, **kwargs: Any):
    """``sanitize_outgoing`` → ``message.edit_text``."""
    return await message.edit_text(_maybe_sanitize(text), **kwargs)


async def send_photo(bot, chat_id: int, photo, **kwargs: Any):
    """Раунд 10.23 (F5, ADR-1023-5 §D6) — отправка изображения-файла.

    Тонкая обёртка egress для сгенерированного изображения: подписи нет
    (LLM-текст в ``sendPhoto`` не уходит), поэтому guard не применяется —
    точка зарегистрирована в ``SEND_ALLOWLIST`` с обоснованием. ``photo`` —
    ``BufferedInputFile`` (байты из памяти): keyed-URL провайдера в Telegram
    не передаётся.
    """
    return await bot.send_photo(chat_id, photo, **kwargs)


# ── Раунд 10.23 (F6, ADR-1023-6 §Decision 4): Article (sendRichMessage) ─────

def looks_rich(text: str) -> bool:
    """Есть ли структурная rich-разметка (Markdown/HTML/таблицы).

    Публичный детектор: используется и оркестратором саммари для решения о
    даунгрейде rich→plain при фолбэке (review iter1, Medium-2)."""
    return _looks_rich(text)


def _looks_rich(text: str) -> bool:
    """Внутренний детектор структурной rich-разметки."""
    source = str(text or "")
    if not source:
        return False
    if (_HTML_BLOCK_RE.search(source) or _MD_HEADING_RE.search(source)
            or _MD_FENCE_RE.search(source)):
        return True
    try:                                  # единый детектор таблиц (F3)
        from services.negative_constraints import detect_plain_tables
        return detect_plain_tables(source)
    except Exception:                     # pragma: no cover - defensive
        return False


def _paragraphs_html(text: str) -> str:
    """Plain → ``<p>``-абзацы (``html.escape`` ПОСЛЕ sanitize)."""
    blocks = [block.strip() for block in str(text or "").split("\n\n")
              if block.strip()]
    return "".join("<p>{}</p>".format(_html.escape(block)) for block in blocks)


def build_cover_article_html(text: str, *,
                             cover_id: str = SUMMARY_COVER_MEDIA_ID) -> str:
    """Собрать HTML Article: обложка-ссылка + plain-абзацы.

    Порядок обязателен (инвариант 3): ``sanitize_outgoing`` ДО ``html.escape``,
    иначе технические теги станут сущностями и не вырежутся. Обложка
    ссылается как ``<img src="tg://photo?id=…">`` (резолвится через
    ``InputRichMessage.media``).
    """
    clean = _maybe_sanitize(text)
    body = _paragraphs_html(clean)
    if cover_id:
        return '<img src="tg://photo?id={}">'.format(cover_id) + body
    return body


def build_cover_media(photo_source, *,
                      cover_id: str = SUMMARY_COVER_MEDIA_ID):
    """Вложение Article из локального файла/байтов (F5 ``generate_image`` → путь).

    В Telegram уходят БАЙТЫ (``BufferedInputFile``), а не URL провайдера —
    keyed-URL не покидает сервер (R17)."""
    from aiogram.types import (
        BufferedInputFile,
        InputMediaPhoto,
        InputRichMessageMedia,
    )
    if isinstance(photo_source, (bytes, bytearray)):
        data = bytes(photo_source)
    else:
        with open(photo_source, "rb") as handle:
            data = handle.read()
    return InputRichMessageMedia(
        id=cover_id,
        media=InputMediaPhoto(
            media=BufferedInputFile(data, filename="summary_cover.jpg")))


async def send_rich_message(bot, chat_id: int, text: str, *, media=None,
                            cover_id: str | None = None,
                            content_format: str = "auto", **kwargs: Any):
    """Egress-обёртка rich-канала (``sendRichMessage``, Bot API 10.1+).

    ``content_format="auto"`` (default) — прежнее поведение байт-в-байт:
    plain-источник проходит ``sanitize_outgoing`` ДО сборки HTML (инвариант 3),
    plain-текст → ``InputRichMessage(html=…, media=…)`` с ``<p>``-абзацами и
    обложкой; rich-контент (Markdown/HTML/таблицы) → ``InputRichMessage(
    markdown=…)``. ``content_format="html"`` (S5/ADR-1026-7 D2) — источник есть
    УЖЕ готовый Rich HTML серверного форматтера (``summary_article_formatter``):
    отправляется как ``html`` без авто-детектора ``_looks_rich`` (который принял
    бы ``<h1`` за markdown). Заполняется РОВНО одно из ``html``/``markdown``.
    """
    from aiogram.types import InputRichMessage
    clean = _maybe_sanitize(text)
    media_list = list(media) if media else None
    if content_format == "html":
        rich = InputRichMessage(html=clean, media=media_list)
    elif _looks_rich(clean):
        # review iter1 (High-1): в markdown-режиме обложка — Markdown-ссылка
        # на вложение (`![alt](tg://photo?id=…)`), а НЕ сырой HTML `<img>`:
        # HTML-форма документирована только для `html`-режима.
        body = clean
        if cover_id:
            body = '![summary cover](tg://photo?id={})\n\n{}'.format(
                cover_id, body)
        rich = InputRichMessage(markdown=body, media=media_list)
    else:
        html = build_cover_article_html(clean, cover_id=cover_id or "")
        rich = InputRichMessage(html=html, media=media_list)
    return await bot.send_rich_message(chat_id, rich, **kwargs)
