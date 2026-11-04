"""T-231: юниты goodmorning-рассылки (Epic 30, R30-3, D88/D89/D93).

Покрытие: пул капций (6 шт., каноны дословно, выбор из пула),
GoodmorningRelay (детект типов, gif-маркер с регистром .MP4, audio/voice
skip, пустая папка, plain-send БЕЗ reply), GoodmorningSchedulerService
(_parse_hhmm, пустые targets → False, cron-триггер, _tick, shutdown).

GM-media-quantum (AMEND): выбор медиа и подписи делает единственный
RandomSource проекта (`mca_random_source.get_service().draw_index`) —
quantum либо его штатный pseudorandom-фолбэк. Тесты ниже проверяют:
обнаружение новых файлов без рестарта, отсутствие повторов внутри цикла,
управление выбором именно draw'ом, запись диагностики draw, честный
фолбэк при недоступном источнике и durable-состояние цикла.
"""
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger

from services.goodmorning_captions import GOODMORNING_CAPTIONS
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


class FakeRandomSource:
    """Детерминированный «quantum»-источник для тестов (DI, без ANU/БД).

    Возвращает заранее заданные индексы (`indices`), затем `default_index`.
    `error` — исключение вместо draw; `deferred_reason` — честный отложенный
    draw (источник выключен/нет запаса, фолбэк запрещён).
    """

    def __init__(self, indices=(), *, default_index=None, error=None,
                 deferred_reason=None, fallback_reason=None,
                 source="quantum"):
        self.indices = list(indices)
        self.default_index = default_index
        self.error = error
        self.deferred_reason = deferred_reason
        self.fallback_reason = fallback_reason
        self.source = source
        self.calls = []

    async def draw_index(self, n, *, chat_id=None, purpose="",
                         policy_version=None, candidates=None,
                         probability=None):
        call = {
            "n": n,
            "chat_id": chat_id,
            "purpose": purpose,
            "candidates": list(candidates or []),
            "policy_version": policy_version,
        }
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        if self.deferred_reason is not None:
            return SimpleNamespace(
                index=None, value=None, source=self.source,
                selected_source=self.source, provider=None, batch_id=None,
                draw_id=None, fallback_reason=self.fallback_reason,
                reason=self.deferred_reason, deferred=True)
        if self.indices:
            index = self.indices.pop(0)
        elif self.default_index is not None:
            index = self.default_index
        else:
            index = n - 1
        return SimpleNamespace(
            index=index, value=index, source=self.source,
            selected_source=self.source, provider="ANU Quantum Numbers",
            batch_id="batch-1", draw_id=f"draw-{len(self.calls)}",
            fallback_reason=self.fallback_reason, reason=None, deferred=False)


def _sent_media_name(bot) -> str:
    for name in ("send_photo", "send_video", "send_animation"):
        call = getattr(bot, name).call_args
        if call is not None:
            payload = (call.kwargs.get("photo") or call.kwargs.get("video")
                       or call.kwargs.get("animation"))
            return Path(getattr(payload, "path", str(payload))).name
    raise AssertionError("nothing was sent")


def _sent_caption(bot) -> str:
    for name in ("send_photo", "send_video", "send_animation"):
        call = getattr(bot, name).call_args
        if call is not None:
            return call.kwargs.get("caption")
    raise AssertionError("nothing was sent")


def _reset_bot(bot) -> None:
    for name in ("send_photo", "send_video", "send_animation"):
        getattr(bot, name).reset_mock()


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

    def test_pool_has_no_duplicates(self):
        """Повтор в пуле сломал бы «без повторов внутри цикла» (ключ = текст)."""
        assert len(set(GOODMORNING_CAPTIONS)) == len(GOODMORNING_CAPTIONS)


# ── Relay ──


class TestGoodmorningRelay:
    @pytest.fixture
    def mock_bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=1))
        bot.send_video = AsyncMock(return_value=SimpleNamespace(message_id=2))
        bot.send_animation = AsyncMock(return_value=SimpleNamespace(message_id=3))
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

    def test_scan_reports_ignored_subdirectories(self, tmp_path, caplog):
        """Подпапка не сканируется — это честно видно в логе, а не молча."""
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "a.jpg").write_text("fake")
        nested = subdir / "new"
        nested.mkdir()
        (nested / "b.jpg").write_text("fake")
        relay = GoodmorningRelay(AsyncMock(), str(subdir))

        with caplog.at_level(logging.INFO):
            files = relay._scan_directory()

        assert [f.name for f, _ in files] == ["a.jpg"]
        assert "подпапки не сканируются" in caplog.text
        assert "new" in caplog.text

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
        source = FakeRandomSource([0, 0])
        relay = GoodmorningRelay(mock_bot, str(subdir), random_source=source,
                                 state_path=tmp_path / "state.json")

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
        source = FakeRandomSource([0, 2])
        relay = GoodmorningRelay(mock_bot, str(subdir), random_source=source,
                                 state_path=tmp_path / "state.json")

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
        source = FakeRandomSource([0, 3])
        relay = GoodmorningRelay(mock_bot, str(subdir), random_source=source,
                                 state_path=tmp_path / "state.json")

        result = await relay.send_goodmorning(chat_id=44)

        assert result is True
        mock_bot.send_animation.assert_called_once()
        assert "reply_parameters" not in mock_bot.send_animation.call_args.kwargs

    @pytest.mark.asyncio
    async def test_empty_dir_returns_false(self, mock_bot, tmp_path, caplog):
        relay = GoodmorningRelay(mock_bot, str(tmp_path / "none"),
                                 state_path=tmp_path / "state.json")
        with caplog.at_level(logging.WARNING):
            result = await relay.send_goodmorning(chat_id=1)
        assert result is False
        mock_bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_error_returns_false(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "p.jpg").write_text("fake")
        mock_bot.send_photo.side_effect = RuntimeError("telegram down")
        source = FakeRandomSource([0, 0])
        relay = GoodmorningRelay(mock_bot, str(subdir), random_source=source,
                                 state_path=tmp_path / "state.json")

        result = await relay.send_goodmorning(chat_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_caption_always_from_pool(self, mock_bot, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "p.jpg").write_text("fake")
        relay = GoodmorningRelay(mock_bot, str(subdir),
                                 state_path=tmp_path / "state.json")

        for _ in range(25):
            result = await relay.send_goodmorning(chat_id=45)
            assert result is True
            kwargs = mock_bot.send_photo.call_args.kwargs
            assert kwargs["caption"] in GOODMORNING_CAPTIONS
            _reset_bot(mock_bot)


# ── Quantum selection (GM-media-quantum) ──

class TestGoodmorningQuantumSelection:
    @pytest.fixture
    def bot(self):
        bot = AsyncMock()
        bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=1))
        bot.send_video = AsyncMock(return_value=SimpleNamespace(message_id=2))
        bot.send_animation = AsyncMock(return_value=SimpleNamespace(message_id=3))
        return bot

    @pytest.fixture
    def media_dir(self, tmp_path):
        subdir = tmp_path / "gm"
        subdir.mkdir()
        (subdir / "a.jpg").write_text("a")
        (subdir / "b.mp4").write_text("b")
        return subdir

    def _relay(self, bot, media_dir, source, tmp_path):
        return GoodmorningRelay(bot, str(media_dir), random_source=source,
                                state_path=tmp_path / "state.json")

    @pytest.mark.asyncio
    async def test_new_media_file_is_discovered_without_restart(
            self, bot, media_dir, tmp_path, caplog):
        """Пул перечитывается на каждой отправке: новый файл виден сразу."""
        source = FakeRandomSource(default_index=None)  # всегда последний allowed
        relay = self._relay(bot, media_dir, source, tmp_path)

        with caplog.at_level(logging.INFO):
            assert await relay.send_goodmorning(chat_id=1) is True
        first = _sent_media_name(bot)
        assert first == "b.mp4"          # allowed=[a,b] → индекс n-1
        _reset_bot(bot)
        caplog.clear()

        (media_dir / "c.jpg").write_text("c")   # владелец кладёт НОВЫЙ файл

        with caplog.at_level(logging.INFO):
            assert await relay.send_goodmorning(chat_id=1) is True
        second = _sent_media_name(bot)

        assert second == "c.jpg", "новый файл обязан попасть в пул без рестарта"
        assert "found 3 files" in caplog.text

    @pytest.mark.asyncio
    async def test_media_and_caption_draws_are_separate_and_recorded(
            self, bot, media_dir, tmp_path, caplog):
        source = FakeRandomSource([1, 4])
        relay = self._relay(bot, media_dir, source, tmp_path)

        with caplog.at_level(logging.INFO):
            assert await relay.send_goodmorning(chat_id=7) is True

        purposes = [call["purpose"] for call in source.calls]
        assert purposes == ["goodmorning_media", "goodmorning_caption"]
        assert all(call["chat_id"] == 7 for call in source.calls)
        # draw управляет выбором: index=1 → второй файл, index=4 → 5-я подпись
        assert _sent_media_name(bot) == "b.mp4"
        assert _sent_caption(bot) == GOODMORNING_CAPTIONS[4]
        # диагностика: source/draw_id/индексы в логе (воспроизводимость)
        assert "media_source=quantum" in caplog.text
        assert "media_draw_id=draw-1" in caplog.text
        assert "caption_draw_id=draw-2" in caplog.text
        assert "media_index=1" in caplog.text
        assert "caption_index=4" in caplog.text

    @pytest.mark.asyncio
    async def test_no_repeats_within_cycle_then_pool_genuinely_exhausted(
            self, bot, media_dir, tmp_path, caplog):
        source = FakeRandomSource(default_index=0)   # всегда первый allowed
        relay = self._relay(bot, media_dir, source, tmp_path)

        sent = []
        captions = []
        with caplog.at_level(logging.INFO):
            for _ in range(4):
                assert await relay.send_goodmorning(chat_id=9) is True
                sent.append(_sent_media_name(bot))
                captions.append(_sent_caption(bot))
                _reset_bot(bot)
        state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        cycles = state["media"]["cycles"]

        # 1-й цикл: каждый файл ровно один раз (без повторов) …
        assert sent[:2] == ["a.jpg", "b.mp4"], sent
        # … пул исчерпан ЧЕСТНО → 3-й send начинает новый цикл в том же порядке
        assert sent == ["a.jpg", "b.mp4", "a.jpg", "b.mp4"], sent
        assert cycles == 1
        # подписи тоже без повторов внутри цикла
        assert captions[0] != captions[1]
        assert len(set(captions)) == 4

    @pytest.mark.asyncio
    async def test_pool_of_one_repeats_is_exhausted_not_a_bug(
            self, bot, tmp_path):
        media_dir = tmp_path / "single"
        media_dir.mkdir()
        (media_dir / "only.jpg").write_text("x")
        relay = self._relay(bot, media_dir, FakeRandomSource(), tmp_path)

        assert await relay.send_goodmorning(chat_id=1) is True
        _reset_bot(bot)
        assert await relay.send_goodmorning(chat_id=1) is True
        assert _sent_media_name(bot) == "only.jpg"

    @pytest.mark.asyncio
    async def test_provider_error_uses_documented_fallback_and_says_so(
            self, bot, media_dir, tmp_path, caplog):
        source = FakeRandomSource(error=RuntimeError("ANU down"))
        relay = self._relay(bot, media_dir, source, tmp_path)

        with caplog.at_level(logging.INFO):
            assert await relay.send_goodmorning(chat_id=5) is True

        assert _sent_media_name(bot) in {"a.jpg", "b.mp4"}
        # фолбэк честно помечен: quantum не приписывается
        assert "random source draw failed" in caplog.text
        assert "media_source=pseudorandom" in caplog.text
        assert "media_fallback=provider_unavailable" in caplog.text
        assert "caption_fallback=provider_unavailable" in caplog.text
        assert "media_source=quantum" not in caplog.text

    @pytest.mark.asyncio
    async def test_deferred_draw_uses_fallback(self, bot, media_dir, tmp_path,
                                               caplog):
        source = FakeRandomSource(deferred_reason="disabled")
        relay = self._relay(bot, media_dir, source, tmp_path)

        with caplog.at_level(logging.INFO):
            assert await relay.send_goodmorning(chat_id=5) is True

        assert "media_fallback=disabled" in caplog.text
        assert "media_source=pseudorandom" in caplog.text

    @pytest.mark.asyncio
    async def test_rotation_survives_restart(self, bot, media_dir, tmp_path):
        source_a = FakeRandomSource(default_index=0)
        relay_a = self._relay(bot, media_dir, source_a, tmp_path)
        assert await relay_a.send_goodmorning(chat_id=1) is True
        first = _sent_media_name(bot)
        _reset_bot(bot)

        # «рестарт»: новый инстанс читает то же состояние цикла
        source_b = FakeRandomSource(default_index=0)
        relay_b = self._relay(bot, media_dir, source_b, tmp_path)
        assert await relay_b.send_goodmorning(chat_id=1) is True
        second = _sent_media_name(bot)

        assert first != second, "рестарт не должен начинать цикл заново"

        state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
        assert len(state["media"]["used"]) == 2
        assert set(state["media"]["used"]) == {first, second}

    @pytest.mark.asyncio
    async def test_failed_send_does_not_consume_cycle(self, bot, media_dir,
                                                      tmp_path):
        bot.send_photo.side_effect = RuntimeError("telegram down")
        source = FakeRandomSource(default_index=0)
        relay = self._relay(bot, media_dir, source, tmp_path)

        assert await relay.send_goodmorning(chat_id=1) is False
        assert not (tmp_path / "state.json").exists()

        bot.send_photo.side_effect = None
        assert await relay.send_goodmorning(chat_id=1) is True
        assert _sent_media_name(bot) == "a.jpg"

    @pytest.mark.asyncio
    async def test_unreadable_state_falls_open(self, bot, media_dir, tmp_path):
        state_path = tmp_path / "state.json"
        state_path.write_text("{not json", encoding="utf-8")
        relay = GoodmorningRelay(bot, str(media_dir),
                                 random_source=FakeRandomSource(default_index=0),
                                 state_path=state_path)

        assert await relay.send_goodmorning(chat_id=1) is True
        assert _sent_media_name(bot) == "a.jpg"
        repaired = json.loads(state_path.read_text(encoding="utf-8"))
        assert repaired["media"]["used"] == ["a.jpg"]

    @pytest.mark.asyncio
    async def test_default_source_is_project_random_service(
            self, bot, media_dir, tmp_path):
        """Без DI relay берёт ЕДИНСТВЕННЫЙ контур — mca_random_source.get_service."""
        fake = FakeRandomSource(default_index=1)
        with patch("services.mca_random_source.get_service",
                   return_value=fake) as getter:
            relay = GoodmorningRelay(bot, str(media_dir),
                                     state_path=tmp_path / "state.json")
            assert await relay.send_goodmorning(chat_id=1) is True

        getter.assert_called()
        assert [c["purpose"] for c in fake.calls] == [
            "goodmorning_media", "goodmorning_caption"]
        # в журнал уходят кандидаты пула (воспроизводимость выбора)
        assert fake.calls[0]["candidates"] == ["a.jpg", "b.mp4"]

    @pytest.mark.asyncio
    async def test_draw_candidates_exclude_used_items_in_cycle(
            self, bot, media_dir, tmp_path):
        source = FakeRandomSource(default_index=0)
        relay = self._relay(bot, media_dir, source, tmp_path)

        assert await relay.send_goodmorning(chat_id=1) is True
        _reset_bot(bot)
        assert await relay.send_goodmorning(chat_id=1) is True
        _reset_bot(bot)

        assert source.calls[0]["candidates"] == ["a.jpg", "b.mp4"]
        assert source.calls[2]["candidates"] == ["b.mp4"]
        assert source.calls[2]["n"] == 1


# ── Интеграция с durable RandomSource (реальный сервис + sqlite) ──


class TestGoodmorningRandomSourceIntegration:
    """Реальный `RandomSourceService` (mca-10a) + реальная схема v27.

    Доказывает шов: quantum-партия → draw из остатка пула → журнал
    `mca_random_draws` с purpose/source/draw_id/кандидатами/временем.
    """

    @pytest.mark.asyncio
    async def test_quantum_draw_is_journaled_for_media_and_caption(
            self, tmp_path, monkeypatch):
        from services import mca_random_source as mrs
        from services.database import DatabaseService

        db = DatabaseService(str(tmp_path / "gm.db"))
        await db.initialize()
        try:
            await self._assert_journaled(db, tmp_path, monkeypatch)
        finally:
            await db.close()

    async def _assert_journaled(self, db, tmp_path, monkeypatch):
        from services import mca_random_source as mrs

        store = mrs.RandomStore(db)
        # ANU-партия: uint16 0 → индекс 0 (медиа), 40 → индекс 4 (подпись)
        await store.insert_batch(
            mrs.AnuBatch(values=[0, 40], data_type="uint16", length=2))

        async def fake_setting(key, chat_id, default):
            return {"memory.random_source": "quantum",
                    "memory.random_fallback_to_pseudorandom": True}.get(
                        key, default)

        monkeypatch.setattr(mrs, "_read_memory_setting", fake_setting)
        service = mrs.RandomSourceService(db, auto_refill=False)

        media_dir = tmp_path / "gm"
        media_dir.mkdir()
        (media_dir / "a.jpg").write_text("a")
        (media_dir / "b.mp4").write_text("b")

        bot = AsyncMock()
        bot.send_photo = AsyncMock(return_value=SimpleNamespace(message_id=1))
        relay = GoodmorningRelay(bot, str(media_dir), random_source=service,
                                 state_path=tmp_path / "state.json")

        assert await relay.send_goodmorning(chat_id=42) is True

        rows = await store.recent_draws(limit=10)
        by_purpose = {r["purpose"]: r for r in rows}
        assert set(by_purpose) == {"goodmorning_media", "goodmorning_caption"}

        media = by_purpose["goodmorning_media"]
        assert media["source"] == "quantum"
        assert media["provider"] == "ANU Quantum Numbers"
        assert media["draw_id"]
        assert media["created_at"] > 0
        assert media["chat_id"] == 42
        assert media["pool_size"] == 2
        assert json.loads(media["candidates_json"]) == ["a.jpg", "b.mp4"]
        assert media["selected_id"] == "0"
        assert media["policy_version"] == "gm-media-quantum-v1"

        caption = by_purpose["goodmorning_caption"]
        assert caption["source"] == "quantum"
        assert caption["selected_id"] == "4"
        assert json.loads(caption["candidates_json"]) == [
            "0", "1", "2", "3", "4", "5"]
        assert caption["draw_id"] != media["draw_id"]
        # quantum-партия реально израсходована (2 значения), запаса не осталось
        assert await store.reserve_remaining() == 0


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
