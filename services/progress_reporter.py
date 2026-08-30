"""84.23 (D303): прогресс-бар скачивания видео.

Одно сообщение-прогресс на чат: отправка при первом вызове, правки с
троттлингом ≥2с и same-text guard (правки в Telegram идут в общие
чат-лимиты — частые правки = 429 + flood-ban). Хук yt-dlp исполняется в
рабочем потоке (asyncio.to_thread) — мост в loop через
asyncio.run_coroutine_threadsafe (Хабр-решение, plan 84.23.0).

Ошибки правки/удаления/отправки НИКОГДА не роняют скачивание:
прогресс-бар — вспомогательный слой, всё в try/except.
"""
import asyncio
import logging
import threading
import time
from typing import Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

# Порог правок: не чаще 1/2с (84.23.3; hot.get("video_download.progress_interval")
# НЕ внедряем — фикс-константа, канон).
_PROGRESS_INTERVAL = 2.0
_BAR_SEGMENTS = 10
_TITLE_MAX = 40
_BLOCK_FULL = "█"
_BLOCK_EMPTY = "░"


def _fmt_bytes(n: float) -> str:
    """Десятичные единицы (1000), как в ТЗ прогресс-бара: 12_345_678 → 12.3 МБ,
    2_100_000 → 2.1 МБ/с."""
    if n >= 1000 ** 2:
        return f"{n / 1000 ** 2:.1f} МБ"
    if n >= 1000:
        return f"{n / 1000:.0f} КБ"
    return f"{n:.0f} Б"


def _fmt_pair(downloaded: float, total: float) -> str:
    """«12.3/22.5 МБ» — общая единица, если обе ≥ 1 МБ; иначе раздельно."""
    if downloaded >= 1000 ** 2 and total >= 1000 ** 2:
        return (f"{downloaded / 1000 ** 2:.1f}"
                f"/{total / 1000 ** 2:.1f} МБ")
    return f"{_fmt_bytes(downloaded)}/{_fmt_bytes(total)}"


def format_progress(d: dict, title: str | None = None) -> str:
    """84.23.2: однострочный рендер прогресса.

    downloading + известный total:
        █████░░░░░ 54% | 12.3/22.5 МБ | 2.1 МБ/с | ETA 5с | <title 40>
    downloading без total (индетерминированный):
        ⬇️ Скачано 12.3 МБ | 2.1 МБ/с
    finished (после скачивания идёт merge ffmpeg):
        ⏳ Обработка (ffmpeg merge)…
    error: ❌ Ошибка: <текст>
    """
    status = d.get("status")
    if status == "finished":
        return "⏳ Обработка (ffmpeg merge)…"
    if status == "error":
        return f"❌ Ошибка: {str(d.get('error') or 'неизвестно')[:80]}"
    downloaded = d.get("downloaded_bytes") or 0
    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
    speed = d.get("speed")
    eta = d.get("eta")
    head: list[str] = []
    if total:
        pct = min(100.0, downloaded / total * 100.0)
        filled = round(pct / 100.0 * _BAR_SEGMENTS)
        bar = _BLOCK_FULL * filled + _BLOCK_EMPTY * (_BAR_SEGMENTS - filled)
        head.append(f"{bar} {pct:.0f}%")
        head.append(_fmt_pair(downloaded, total))
    else:
        head.append(f"⬇️ Скачано {_fmt_bytes(downloaded)}")
    if speed:
        head.append(f"{_fmt_bytes(speed)}/с")
    if eta is not None:
        head.append(f"ETA {int(eta)}с")
    line = " | ".join(head)
    if title:
        t = str(title).strip()
        if len(t) > _TITLE_MAX:
            t = t[:_TITLE_MAX - 1] + "…"
        line += f" | {t}"
    return line


class ProgressReporter:
    """Прогресс-бар (84.23.3): одно сообщение, троттлинг, same-text guard,
    мост потоков run_coroutine_threadsafe для вызовов из to_thread.

    Публичный async API: start/update/finish/fail/close (на loop).
    Синхронные обёртки update_sync/on_progress — безопасны из ЛЮБОГО потока
    (в т.ч. из хука yt-dlp в рабочем потоке).
    """

    def __init__(self, bot: Bot, chat_id: int, trigger_message_id: int | None = None,
                 loop: asyncio.AbstractEventLoop | None = None):
        self._bot = bot
        self._chat_id = chat_id
        self._trigger_message_id = trigger_message_id
        self._loop = loop or self._resolve_loop()
        self._message_id: int | None = None
        self._started = False
        self._closed = False
        self._disabled = False          # сообщение удалено/правки падают
        self._lock = asyncio.Lock()
        self._last_edit = 0.0           # time.monotonic последней правки
        self._last_text: str | None = None

    @staticmethod
    def _resolve_loop():
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    # ── мост потоков ─────────────────────────────────────────────────

    def _bridge(self, coro_factory: Callable[[], Callable]) -> None:
        """Запустить корутину на self._loop из любого потока (fire-and-forget).
        Прогресс не блокирует поток воркера; закрытый loop — тихо пропускаем."""
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        except RuntimeError:
            logger.debug("[videodl] progress bridge failed", exc_info=True)

    def update_sync(self, text: str) -> None:
        """Синхронная правка из ЛЮБОГО потока (троттлинг внутри)."""
        self._bridge(lambda: self.update(text))

    def on_progress(self, d: dict) -> None:
        """Колбэк для VideoDownloader.progress_cb (вызывается из хука yt-dlp
        в рабочем потоке ИЛИ из async-контекста direct-ветки)."""
        try:
            title = None
            info = d.get("info_dict")
            if isinstance(info, dict):
                title = info.get("title")
            text = format_progress(d, title)
            if text:
                self.update_sync(text)
        except Exception:
            # 84.23.9: рендер/мост не должны ронять скачивание
            logger.debug("[videodl] on_progress failed", exc_info=True)

    # ── async API (loop) ─────────────────────────────────────────────

    async def start(self, text: str) -> None:
        """Отправить «⏳ Скачивание…» (reply на триггер) и запомнить message_id."""
        if self._started or self._closed:
            return
        try:
            msg = await self._bot.send_message(
                self._chat_id, text,
                reply_to_message_id=self._trigger_message_id)
            try:
                self._message_id = int(msg.message_id)
            except (TypeError, ValueError, AttributeError):
                self._message_id = None
            self._started = self._message_id is not None
        except Exception:
            logger.debug("[videodl] progress start failed", exc_info=True)

    async def update(self, text: str) -> None:
        """editMessageText с троттлингом ≥2с и same-text guard."""
        if self._closed or self._disabled or not self._started:
            return
        if self._message_id is None:
            return
        async with self._lock:
            if time.monotonic() - self._last_edit < _PROGRESS_INTERVAL:
                return
            if text == self._last_text:
                return
            await self._edit_now(text)

    async def finish(self, text: str) -> bool:
        """Финальная правка (без троттлинга): «✅ Файл готов, отправляю…».
        True — текст реально применён (или сообщение уже закрыто);
        False — старт не удался / сообщение пропало (правка невозможна)."""
        if self._closed:
            return True                 # сообщение закрыто — показывать нечего
        if self._disabled or not self._started:
            return False
        if self._message_id is None:
            return False
        if text == self._last_text:
            return True                 # уже применён ранее
        async with self._lock:
            return await self._edit_now(text)

    async def fail(self, text: str) -> bool:
        """Правка с текстом ошибки (без троттлинга; сообщение НЕ удаляем —
        юзер должен видеть, что пошло не так). Возврат как у finish() —
        хендлер шлёт _safe_error_reply ТОЛЬКО при False."""
        return await self.finish(text)

    async def close(self) -> None:
        """Удалить прогресс-сообщение (missing_ok); идемпотентно."""
        if self._closed:
            return
        self._closed = True
        mid = self._message_id
        self._message_id = None
        if mid is None:
            return
        try:
            await self._bot.delete_message(self._chat_id, mid)
        except Exception:
            logger.debug("[videodl] progress delete failed", exc_info=True)

    # ── внутреннее ──────────────────────────────────────────────────

    async def _edit_now(self, text: str) -> bool:
        """Правка БЕЗ троттлинга. Все ошибки — внутрь, репортер жив.
        True — текст применён; False — сообщение пропало/правка невозможна."""
        try:
            await self._bot.edit_message_text(
                self._chat_id, self._message_id, text)
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                # гонка правок — текст уже применён, считаем применённым
                self._last_text = text
                return True
            self._disabled = True
            logger.debug("[videodl] progress edit failed: %s", exc)
            return False
        except Exception as exc:
            self._disabled = True
            logger.debug("[videodl] progress edit failed: %s", exc)
            return False
        self._last_edit = time.monotonic()
        self._last_text = text
        return True


# ── реестр (84.23.6): {chat_id: ProgressReporter} под lock ────────────
# Сейчас глобальный lock (70.4) = одно скачивание на процесс; реестр —
# на будущее (очередь/несколько задач) и для контроля «занят» в хендлере.

_active: dict[int, ProgressReporter] = {}
_active_lock = threading.Lock()


def register(chat_id: int, reporter: ProgressReporter) -> None:
    with _active_lock:
        _active[chat_id] = reporter


def unregister(chat_id: int) -> None:
    with _active_lock:
        _active.pop(chat_id, None)


def get_active(chat_id: int) -> ProgressReporter | None:
    with _active_lock:
        return _active.get(chat_id)
