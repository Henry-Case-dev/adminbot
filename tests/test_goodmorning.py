"""T-231: юниты goodmorning-рассылки (Epic 30, R30-3, D88/D89/D93).

Покрытие: пул капций (6 шт., каноны дословно, выбор из пула),
GoodmorningRelay (детект типов, gif-маркер с регистром .MP4, audio/voice
skip, пустая папка, plain-send БЕЗ reply), GoodmorningSchedulerService
(_parse_hhmm, пустые targets → False, cron-триггер, _tick, shutdown).
"""
import logging
import random
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger

from services.goodmorning_captions import GOODMORNING_CAPTIONS, pick_caption
from services.goodmorning_relay import (
    MEDIA_ANIMATION,
    MEDIA_AUDIO,
    MEDIA_PHOTO,
    MEDIA_VIDEO,
    MEDIA_VOICE,
    GoodmorningRelay,
)
from services.goodmorning_scheduler import (
    GoodmorningSchedulerService,
    _parse_hhmm,
)


# ── Captions ──


class TestGoodmorningCaptions:
    CANONS = (
        "❗️❗️❗️ПАДЪЕМ НИГЕРЫ, ПОРА ТРЯСТИСЬ И СУЕТИТЬСЯ",
        "❗️❗️❗️ ПЕРМЯКИ, ПОДНИМАЕМ ЖОПКИ, ПОРА ТОП ТОП ТОП НА ЗАВОДИК, НЕ ЗАБУДЬТЕ ПОСРАТЬ",
        "❗️❗️❗️ АХАХАХ ПЕРМЯКИ КРЯХТЯТ ПОДНИМАЮТСЯ С КРОВАТОК, ПОСМОТРИТЕ НА ЭТИХ ЛОШКОВ",
    )

    def test_pool_has_six_captions(self):
        assert len(GOODMORNING_CAPTIONS) == 6

    def test_first_three_are_user_canons_verbatim(self):
        assert GOODMORNING_CAPTIONS[:3] == self.CANONS

    def test_all_start_with_alarm_emoji(self):
        for caption in GOODMORNING_CAPTIONS:
            assert caption.startswith("❗️❗️❗️")

    def test_all_are_uppercase(self):
        for caption in GOODMORNING_CAPTIONS:
            assert caption.upper() == caption

    def test_new_three_have_no_mat(self):
        for caption in GOODMORNING_CAPTIONS[3:]:
            for bad in ("ЕБАН", "БЛЯ", "ХУЙ", "ПИЗД", "НАХУЙ", "ДОЛБО"):
                assert bad not in caption

    def test_pick_caption_returns_from_pool_and_covers_all(self):
        picked = {pick_caption() for _ in range(300)}
        assert picked == set(GOODMORNING_CAPTIONS)


# ── Relay ──


class TestGoodmorningRelay:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock()
        bot.send_video = AsyncMock()
        bot.send_animation = AsyncMock()
        return bot

    def test_detect_photo(self):
        relay = GoodmorningRelay(AsyncMock(), "media/common/goodmorning")
        assert relay._detect_media_type(Path("goodmorning_03.jpg")) == MEDIA_PHOTO

    def test_detect_video(self):
        relay = GoodmorningRelay(AsyncMock(), "media/common/goodmorning")
        assert relay._detect_media_type(Path("goodmorning_01.mp4")) == MEDIA_VIDEO

    def test_detect_animation_by_gif_marker(self):
        relay = GoodmorningRelay(AsyncMock(), "media/common/goodmorning")
        assert (
            relay._detect_media_type(Path("goodmorning_05_gif.MP4"))
            == MEDIA_ANIMATION
        )

    def test_detect_animation_uppercase_ext(self):
        """D93: регистр расширения .MP4 не мешает детекту."""
        relay = GoodmorningRelay(AsyncMock(), "media/common/goodmorning")
        assert relay._detect_media_type(Path("goodmorning_02.MP4")) == MEDIA_VIDEO

    def test_detect_audio_and_voice(self):
        relay = GoodmorningRelay(AsyncMock(), "media/common/goodmorning")
        assert relay._detect_media_type(Path("a.mp3")) == MEDIA_AUDIO
        assert relay._detect_media_type(Path("v.ogg")) == MEDIA_VOICE

    def test_detect_unsupported(self):
        relay = GoodmorningRelay(AsyncMock(), "media/common/goodmorning")
        assert relay._detect_media_type(Path("readme.txt")) is None

    def test_scan_skips_audio_voice_with_warning(self, tmp_path, caplog):
        relay = GoodmorningRelay(AsyncMock(), str(tmp_path / "gm"))
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "a.jpg").write_text("fake")
        (subdir / "b.mp3").write_text("fake")
        (subdir / "c.ogg").write_text("fake")
        (subdir / "d.txt").write_text("fake")

        with caplog.at_level(logging.WARNING):
            files = relay._scan_directory()

        assert len(files) == 1
        assert files[0][0].name == "a.jpg"
        assert "b.mp3" in caplog.text
        assert "c.ogg" in caplog.text

    def test_scan_missing_directory_warning_and_empty(self, tmp_path, caplog):
        relay = GoodmorningRelay(AsyncMock(), str(tmp_path / "nope"))
        with caplog.at_level(logging.WARNING):
            files = relay._scan_directory()
        assert files == []
        assert "not found" in caplog.text

    def test_scan_empty_directory_warning_and_empty(self, tmp_path, caplog):
        subdir = tmp_path / "empty"
        subdir.mkdir()
        relay = GoodmorningRelay(AsyncMock(), str(subdir))
        with caplog.at_level(logging.WARNING):
            files = relay._scan_directory()
        assert files == []
        assert "no sendable media" in caplog.text

    @pytest.mark.asyncio
    async def test_send_photo_plain_with_caption(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "p.jpg").write_text("fake")
        relay = GoodmorningRelay(mock_bot, str(subdir))

        with patch.object(random, "choice", side_effect=[(Path(subdir / "p.jpg"), MEDIA_PHOTO), GOODMORNING_CAPTIONS[0]]):
            result = await relay.send_goodmorning(chat_id=42)

        assert result is True
        mock_bot.send_photo.assert_called_once()
        kwargs = mock_bot.send_photo.call_args.kwargs
        assert kwargs["chat_id"] == 42
        assert kwargs["caption"] == GOODMORNING_CAPTIONS[0]
        # plain-send: НИКАКИХ reply_parameters/reply_to_message_id
        assert "reply_parameters" not in kwargs
        assert "reply_to_message_id" not in kwargs

    @pytest.mark.asyncio
    async def test_send_video_plain_with_caption(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "v.mp4").write_text("fake")
        relay = GoodmorningRelay(mock_bot, str(subdir))

        with patch.object(random, "choice", side_effect=[(Path(subdir / "v.mp4"), MEDIA_VIDEO), GOODMORNING_CAPTIONS[2]]):
            result = await relay.send_goodmorning(chat_id=43)

        assert result is True
        mock_bot.send_video.assert_called_once()
        kwargs = mock_bot.send_video.call_args.kwargs
        assert kwargs["caption"] == GOODMORNING_CAPTIONS[2]
        assert "reply_parameters" not in kwargs

    @pytest.mark.asyncio
    async def test_send_animation_plain(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "gif.mp4").write_text("fake")
        relay = GoodmorningRelay(mock_bot, str(subdir))

        with patch.object(random, "choice", side_effect=[(Path(subdir / "gif.mp4"), MEDIA_ANIMATION), GOODMORNING_CAPTIONS[3]]):
            result = await relay.send_goodmorning(chat_id=44)

        assert result is True
        mock_bot.send_animation.assert_called_once()
        assert "reply_parameters" not in mock_bot.send_animation.call_args.kwargs

    @pytest.mark.asyncio
    async def test_empty_dir_returns_false(self, mock_bot, tmp_path, caplog):
        relay = GoodmorningRelay(mock_bot, str(tmp_path / "none"))
        with caplog.at_level(logging.WARNING):
            result = await relay.send_goodmorning(chat_id=1)
        assert result is False
        mock_bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_error_returns_false(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "p.jpg").write_text("fake")
        relay = GoodmorningRelay(mock_bot, str(subdir))
        mock_bot.send_photo.side_effect = RuntimeError("telegram down")

        with patch.object(random, "choice", side_effect=[(Path(subdir / "p.jpg"), MEDIA_PHOTO), GOODMORNING_CAPTIONS[0]]):
            result = await relay.send_goodmorning(chat_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_caption_always_from_pool(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "p.jpg").write_text("fake")
        relay = GoodmorningRelay(mock_bot, str(subdir))

        for _ in range(25):
            result = await relay.send_goodmorning(chat_id=45)
            assert result is True
            kwargs = mock_bot.send_photo.call_args.kwargs
            assert kwargs["caption"] in GOODMORNING_CAPTIONS


# ── Scheduler ──


class TestParseHhmm:
    def test_valid_two_digit(self):
        assert _parse_hhmm("07:00") == (7, 0)

    def test_valid_one_digit_hour(self):
        assert _parse_hhmm("7:00") == (7, 0)

    def test_valid_edge(self):
        assert _parse_hhmm("23:59") == (23, 59)

    @pytest.mark.parametrize("bad", ["24:00", "07:60", "abc", "07", "7:0", "", "07:000"])
    def test_invalid_falls_back_with_warning(self, bad, caplog):
        with caplog.at_level(logging.WARNING):
            assert _parse_hhmm(bad) == (7, 0)
        assert "invalid GOODMORNING_TIME" in caplog.text


class TestGoodmorningSchedulerService:
    def make_service(self, targets=(111, 222)):
        relay = MagicMock()
        relay.send_goodmorning = AsyncMock(return_value=True)
        service = GoodmorningSchedulerService(
            relay=relay,
            time_str="07:30",
            tz="Asia/Yekaterinburg",
            target_chat_ids=targets,
        )
        return service, relay

    def test_empty_targets_start_returns_false(self, caplog):
        service, _ = self.make_service(targets=())
        with caplog.at_level(logging.WARNING):
            assert service.start() is False
        assert service._scheduler.running is False
        assert "TARGET_CHAT_IDS пуст" in caplog.text

    @pytest.mark.asyncio
    async def test_start_with_targets_adds_cron_job(self):
        service, _ = self.make_service()
        assert service.start() is True
        try:
            assert service._scheduler.running is True
            job = service._scheduler.get_job(GoodmorningSchedulerService.JOB_ID)
            assert isinstance(job.trigger, CronTrigger)
            fields = {f.name: f for f in job.trigger.fields}
            assert [str(e) for e in fields["hour"].expressions] == ["7"]
            assert [str(e) for e in fields["minute"].expressions] == ["30"]
            assert str(job.trigger.timezone) == "Asia/Yekaterinburg"
            assert job.max_instances == 1
            assert job.coalesce is True
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_memory_jobstore_only(self):
        service, _ = self.make_service()
        service.start()
        try:
            jobstore = service._scheduler._jobstores["default"]
            assert isinstance(jobstore, MemoryJobStore)
        finally:
            await service.shutdown()

    @pytest.mark.asyncio
    async def test_invalid_tz_falls_back(self, caplog):
        relay = MagicMock()
        relay.send_goodmorning = AsyncMock()
        with caplog.at_level(logging.WARNING):
            service = GoodmorningSchedulerService(
                relay=relay, time_str="07:00", tz="Mars/Olympus", target_chat_ids=(1,)
            )
        assert service._tz == "Asia/Yekaterinburg"
        assert "invalid GOODMORNING_TZ" in caplog.text

    @pytest.mark.asyncio
    async def test_tick_sends_to_all_targets(self):
        service, relay = self.make_service(targets=(1, 2, 3))
        await service._tick()
        assert relay.send_goodmorning.await_count == 3
        relay.send_goodmorning.assert_any_await(1)
        relay.send_goodmorning.assert_any_await(2)
        relay.send_goodmorning.assert_any_await(3)

    @pytest.mark.asyncio
    async def test_tick_one_failure_does_not_kill_others(self, caplog):
        relay = MagicMock()
        async def flaky(chat_id):
            if chat_id == 2:
                raise RuntimeError("chat exploded")
            return True

        relay.send_goodmorning = AsyncMock(side_effect=flaky)
        service = GoodmorningSchedulerService(
            relay=relay, time_str="07:00", tz="Asia/Yekaterinburg",
            target_chat_ids=(1, 2, 3),
        )
        with caplog.at_level(logging.WARNING):
            await service._tick()
        assert relay.send_goodmorning.await_count == 3

    @pytest.mark.asyncio
    async def test_shutdown_without_start_does_not_raise(self):
        service, _ = self.make_service()
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        service, _ = self.make_service()
        service.start()
        await service.shutdown()
        await service.shutdown()  # второй вызов не падает
