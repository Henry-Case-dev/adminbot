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

import logging
from typing import Any

from config.settings import settings
from services.outgoing_guard import sanitize_outgoing

logger = logging.getLogger(__name__)

# Реестр send-точек, переведённых на обёртки: модуль → имена функций.
# Тест покрытия (`tests/test_outgoing_guard_round1022.py`) сверяет реестр с
# реальными вызовами `send_message`/`edit_text` в исходниках.
SEND_POINTS: dict[str, tuple[str, ...]] = {
    "services/smartmodule_utils.py": ("_send_once",),
    "services/summary_generator.py": (
        "_send_streaming", "_send_chunked", "_send_one_chunk", "_send_ux",
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
