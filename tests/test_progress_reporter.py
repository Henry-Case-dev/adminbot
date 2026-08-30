"""Epic 84 (84.23, D303): прогресс-бар скачивания — формат строки,
троттлинг правок, same-text guard, финиш/фейл/close, мост потоков,
реестр. Сеть не трогаем — мок-бот."""
import asyncio
import time
from concurrent.futures import Future
from unittest.mock import MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from services.progress_reporter import (
    ProgressReporter,
    format_progress,
    get_active,
    register,
    unregister,
)

CHAT_ID = -1001234567890


class _Bot:
    """Фейк-бот: история отправок/правок/удалений + message_id=42."""

    def __init__(self):
        self.sent: list[str] = []
        self.edits: list[tuple[float, str]] = []
        self.deleted: list[int] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return MagicMock(message_id=42)

    async def edit_message_text(self, chat_id, message_id, text):
        self.edits.append((time.monotonic(), text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


# ── 1. format_progress (84.23.2) ─────────────────────────────────────

class TestFormatProgress:
    def test_with_total_bar_percent_speed_eta_title(self):
        text = format_progress({
            "status": "downloading",
            "downloaded_bytes": 12_345_678,
            "total_bytes": 22_500_000,
            "speed": 2_100_000,
            "eta": 5,
        }, "Название видео")
        assert "55%" in text                    # 12.35/22.5 = 54.9 → 55
        assert "12.3/22.5 МБ" in text
        assert "2.1 МБ/с" in text
        assert "ETA 5с" in text
        assert "Название видео" in text

    def test_bar_has_ten_segments(self):
        text = format_progress({
            "status": "downloading",
            "downloaded_bytes": 50_000_000,
            "total_bytes": 100_000_000,
        })
        bar = text.split(" ", 1)[0]
        assert bar.count("█") == 5
        assert bar.count("░") == 5
        assert "50%" in text

    def test_no_total_indeterminate_mode(self):
        text = format_progress({
            "status": "downloading",
            "downloaded_bytes": 12_345_678,
            "speed": 1_000_000,
            "eta": None,
        })
        assert "⬇️ Скачано 12.3 МБ" in text
        assert "1.0 МБ/с" in text
        assert "%" not in text

    def test_title_truncated_to_40(self):
        long_title = "x" * 100
        text = format_progress({
            "status": "downloading",
            "downloaded_bytes": 10,
            "total_bytes": 100,
        }, long_title)
        assert ("x" * 39 + "…") in text

    def test_finished_and_error_statuses(self):
        assert format_progress({"status": "finished"}) == \
            "⏳ Обработка (ffmpeg merge)…"
        assert "Ошибка: boom" in format_progress(
            {"status": "error", "error": "boom"})


# ── 2. ProgressReporter: троттлинг/гарды ─────────────────────────────

class TestProgressReporter:
    @pytest.mark.asyncio
    async def test_start_sends_message_and_remembers_id(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID, trigger_message_id=100)
        await rp.start("⏳ Скачивание…")
        assert bot.sent == ["⏳ Скачивание…"]
        assert rp._message_id == 42
        assert rp._started is True

    @pytest.mark.asyncio
    async def test_throttle_min_two_seconds(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        await rp.update("10%")
        await rp.update("10%")          # same-text guard
        await rp.update("20%")          # троттлинг (не прошло 2с)
        assert len(bot.edits) == 1
        assert bot.edits[0][1] == "10%"

    @pytest.mark.asyncio
    async def test_same_text_skipped_even_after_throttle_expired(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        rp._last_edit = time.monotonic() - 10
        await rp.update("same")
        await rp.update("same")
        assert len(bot.edits) == 1

    @pytest.mark.asyncio
    async def test_update_after_interval_passes(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        rp._last_edit = time.monotonic() - 3.0
        await rp.update("new text")
        assert len(bot.edits) == 1
        assert bot.edits[0][1] == "new text"

    @pytest.mark.asyncio
    async def test_finish_bypasses_throttle(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        await rp.update("10%")
        await rp.finish("✅ Файл готов, отправляю…")
        assert len(bot.edits) == 2
        assert bot.edits[-1][1] == "✅ Файл готов, отправляю…"

    @pytest.mark.asyncio
    async def test_fail_sets_error_text_and_keeps_message(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        await rp.fail("не получилось")
        assert bot.edits[-1][1] == "не получилось"
        assert bot.deleted == []        # сообщение с ошибкой НЕ удаляем

    @pytest.mark.asyncio
    async def test_finish_fail_return_bool(self):
        """F1: True — текст применён; False — старт не удался."""
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        assert await rp.fail("x") is False         # старта не было
        assert await rp.finish("✅ Файл готов") is False
        await rp.start("⏳ Скачивание…")
        assert await rp.finish("✅ Файл готов") is True
        assert await rp.fail("ошибка") is True

    @pytest.mark.asyncio
    async def test_finish_false_when_message_gone(self):
        """F1: правка невозможна (сообщение пропало) → False + disabled."""
        class _GoneBot(_Bot):
            async def edit_message_text(self, chat_id, message_id, text):
                raise TelegramBadRequest(
                    MagicMock(), "message to delete not found")

        bot = _GoneBot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        assert await rp.finish("✅ Файл готов") is False
        assert rp._disabled is True

    @pytest.mark.asyncio
    async def test_close_deletes_once(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        await rp.close()
        await rp.close()
        assert bot.deleted == [42]

    @pytest.mark.asyncio
    async def test_close_without_start_noop(self):
        bot = _Bot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.close()
        assert bot.deleted == []

    @pytest.mark.asyncio
    async def test_edit_failure_disables_reporter(self):
        class _BrokenBot(_Bot):
            async def edit_message_text(self, chat_id, message_id, text):
                raise RuntimeError("chat not found")

        bot = _BrokenBot()
        rp = ProgressReporter(bot, CHAT_ID)
        await rp.start("⏳ Скачивание…")
        await rp.update("10%")
        assert rp._disabled is True
        # репортер жив, задача не падает
        assert bot.edits == []


# ── 3. on_progress: хук → текст → мост ───────────────────────────────

class TestOnProgress:
    def test_formats_from_hook_dict(self, monkeypatch):
        bridged = []
        bot = MagicMock()

        def _fake_rcs(coro, loop):
            bridged.append(coro)
            coro.close()
            return Future()

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_rcs)
        rp = ProgressReporter(bot, CHAT_ID, loop=MagicMock())
        rp.on_progress({
            "status": "downloading",
            "downloaded_bytes": 1024,
            "total_bytes": 2048,
            "speed": 512,
            "eta": 2,
            "info_dict": {"title": "clip"},
        })
        assert len(bridged) == 1

    def test_bad_hook_dict_does_not_raise(self, monkeypatch):
        bot = MagicMock()
        rp = ProgressReporter(bot, CHAT_ID, loop=None)
        rp.on_progress({"status": "downloading"})       # без полей — ок
        rp.on_progress("not a dict")                    # не падает
        rp.on_progress(None)


# ── 4. мост потоков ─────────────────────────────────────────────────

class TestThreadBridge:
    def test_from_other_thread_uses_run_coroutine_threadsafe(self, monkeypatch):
        calls = []

        def _fake_rcs(coro, loop):
            calls.append(loop)
            coro.close()                # не запускаем — только факт моста
            return Future()

        monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", _fake_rcs)
        loop = MagicMock()
        bot = MagicMock()
        rp = ProgressReporter(bot, CHAT_ID, loop=loop)
        rp._started = True
        rp._message_id = 1
        rp.update_sync("10%")
        assert calls == [loop]

    def test_loop_none_skips_bridge(self):
        bot = MagicMock()
        rp = ProgressReporter(bot, CHAT_ID, loop=None)
        rp._started = True
        rp._message_id = 1
        rp.update_sync("10%")           # не падает
        assert rp._last_text is None


# ── 5. реестр (84.23.6) ──────────────────────────────────────────────

class TestRegistry:
    def test_register_get_unregister(self):
        rp = ProgressReporter(MagicMock(), CHAT_ID, loop=None)
        assert get_active(CHAT_ID) is None
        register(CHAT_ID, rp)
        assert get_active(CHAT_ID) is rp
        unregister(CHAT_ID)
        assert get_active(CHAT_ID) is None
