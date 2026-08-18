"""Tests for services/youtube_transcript_engine.py (T-289, R37-3, Section 46.4/46.12).

youtube-transcript-api мокается через services.youtube_transcript_engine.YouTubeTranscriptApi
(модуль-левел импорт с ImportError-guard — прецедент DDGS в test_search_aggregator.py;
реальная библиотека в тестах НЕ импортируется).
"""
import pytest

from services import youtube_transcript_engine as engine_mod
from services.youtube_transcript_engine import (
    YouTubeTranscriptEngine,
    YouTubeTranscriptUnavailableException,
)


class _FakeTranscript:
    def __init__(self, language_code, generated, segments=None):
        self.language_code = language_code
        self.is_generated = generated
        self._segments = segments or [
            {"text": f"сегмент {language_code}", "start": 5.0, "duration": 3.0}
        ]

    def fetch(self):
        return self._segments


class _FakeTranscriptList:
    """Подмножество TranscriptList (0.6.x): find_* бросают Exception как
    NoTranscriptFound; итерируется по имеющимся транскриптам."""

    def __init__(self, transcripts=()):
        self._transcripts = list(transcripts)

    def find_manually_created_transcript(self, language_codes):
        for t in self._transcripts:
            if not t.is_generated and t.language_code in language_codes:
                return t
        raise RuntimeError("NoTranscriptFound")

    def find_generated_transcript(self, language_codes):
        for t in self._transcripts:
            if t.is_generated and t.language_code in language_codes:
                return t
        raise RuntimeError("NoTranscriptFound")

    def __iter__(self):
        return iter(self._transcripts)


class _FakeApi:
    """YouTubeTranscriptApi (0.6.x): list_transcripts → TranscriptList."""

    result = None

    @classmethod
    def list_transcripts(cls, video_id):
        return cls.result


def _segments(*pairs):
    return [{"text": text, "start": start, "duration": 1.0} for text, start in pairs]


class TestPickTranscriptPriority:
    """#7: manual ru → manual en → generated ru → generated en → прочий generated."""

    @pytest.mark.parametrize(
        "transcripts,expected_lang",
        [
            (
                [
                    _FakeTranscript("ru", False),
                    _FakeTranscript("en", False),
                    _FakeTranscript("ru", True),
                    _FakeTranscript("en", True),
                ],
                "ru",
            ),
            (
                [
                    _FakeTranscript("en", False),
                    _FakeTranscript("ru", True),
                    _FakeTranscript("en", True),
                ],
                "en",
            ),
            (
                [
                    _FakeTranscript("ru", True),
                    _FakeTranscript("en", True),
                ],
                "ru",
            ),
            (
                [
                    _FakeTranscript("en", True),
                ],
                "en",
            ),
            (
                [
                    _FakeTranscript("fr", True),   # прочий generated (5-й приоритет)
                ],
                "fr",
            ),
        ],
    )
    def test_priority(self, transcripts, expected_lang):
        chosen = YouTubeTranscriptEngine._pick_transcript(
            _FakeTranscriptList(transcripts), "video-1"
        )
        assert chosen.language_code == expected_lang

    def test_nothing_found_raises(self):
        with pytest.raises(YouTubeTranscriptUnavailableException):
            YouTubeTranscriptEngine._pick_transcript(_FakeTranscriptList([]), "video-1")

    def test_none_list_raises(self):
        with pytest.raises(YouTubeTranscriptUnavailableException):
            YouTubeTranscriptEngine._pick_transcript(None, "video-1")

    def test_only_manual_other_language_but_generated_any_works(self):
        """manual fr (не подходит по кодам) + generated de → прочий generated."""
        chosen = YouTubeTranscriptEngine._pick_transcript(
            _FakeTranscriptList(
                [_FakeTranscript("fr", False), _FakeTranscript("de", True)]
            ),
            "video-1",
        )
        assert chosen.language_code == "de"


class TestFetchErrors:
    """#8: ошибки библиотеки → единое YouTubeTranscriptUnavailableException."""

    @pytest.mark.parametrize(
        "exc",
        [
            RuntimeError("TranscriptsDisabled"),
            RuntimeError("NoTranscriptFound"),
            RuntimeError("VideoUnavailable"),
            RuntimeError("TooManyRequests"),
            RuntimeError("network error"),
        ],
    )
    def test_list_transcripts_error_wrapped(self, monkeypatch, exc):
        class _FailingApi(_FakeApi):
            @classmethod
            def list_transcripts(cls, video_id):
                raise exc

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _FailingApi)
        engine = YouTubeTranscriptEngine()
        with pytest.raises(YouTubeTranscriptUnavailableException):
            engine._fetch_segments("video-1")

    def test_transcript_fetch_error_wrapped(self, monkeypatch):
        class _FailingFetch(_FakeTranscript):
            def fetch(self):
                raise RuntimeError("fetch failed")

        class _Api(_FakeApi):
            result = _FakeTranscriptList([_FailingFetch("ru", False)])

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with pytest.raises(YouTubeTranscriptUnavailableException):
            YouTubeTranscriptEngine()._fetch_segments("video-1")

    def test_empty_transcript_list_raises(self, monkeypatch):
        class _Api(_FakeApi):
            result = _FakeTranscriptList([])

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with pytest.raises(YouTubeTranscriptUnavailableException):
            YouTubeTranscriptEngine()._fetch_segments("video-1")

    def test_none_transcript_list_raises(self, monkeypatch):
        class _Api(_FakeApi):
            result = None

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with pytest.raises(YouTubeTranscriptUnavailableException):
            YouTubeTranscriptEngine()._fetch_segments("video-1")


class TestFormat:
    """#9/#10: таймкоды floor + жёсткий срез по max_symbols."""

    def test_timestamps_floor(self):
        formatted = YouTubeTranscriptEngine._format(
            _segments(("первый", 5.0), ("второй", 12.25), ("третий", 61.0)), 4000
        )
        lines = formatted.split("\n")
        assert lines[0].startswith("[00:05] ")
        assert lines[1].startswith("[00:12] ")
        assert lines[2].startswith("[01:01] ")

    def test_format_join_and_text(self):
        formatted = YouTubeTranscriptEngine._format(
            _segments(("привет всем", 5.0), ("начнем", 12.0)), 4000
        )
        assert formatted == "[00:05] привет всем\n[00:12] начнем"

    def test_small_max_symbols_hard_slice(self):
        """#10: жёсткий срез — len(result) == max_symbols."""
        formatted = YouTubeTranscriptEngine._format(
            _segments(("длинный текст сегмента", 5.0), ("еще сегмент", 10.0)), 10
        )
        assert len(formatted) == 10

    def test_early_stop_skips_later_segments(self):
        """Ранний стоп: сегменты за лимитом не попадают в результат."""
        formatted = YouTubeTranscriptEngine._format(
            _segments(("первый", 5.0), ("второй очень длинный сегмент", 10.0)), 20
        )
        assert "[00:10]" not in formatted

    def test_empty_segments_empty_string(self):
        assert YouTubeTranscriptEngine._format([], 4000) == ""


class TestFetchTranscript:
    """#11: sync-вызов в executor, await корректен, контракт async."""

    @pytest.mark.asyncio
    async def test_fetch_transcript_awaits_and_formats(self, monkeypatch):
        class _Api(_FakeApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("ru", False, _segments(("привет", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        result = await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert result == "[00:05] привет"

    @pytest.mark.asyncio
    async def test_fetch_transcript_propagates_unavailable(self, monkeypatch):
        class _Api(_FakeApi):
            result = _FakeTranscriptList([])

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with pytest.raises(YouTubeTranscriptUnavailableException):
            await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)

    @pytest.mark.asyncio
    async def test_fetch_transcript_uses_max_symbols(self, monkeypatch):
        class _Api(_FakeApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("ru", False, _segments(("текст", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        result = await YouTubeTranscriptEngine().fetch_transcript("video-1", 5)
        assert len(result) == 5
