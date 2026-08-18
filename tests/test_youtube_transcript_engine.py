"""Tests for services/youtube_transcript_engine.py (T-289, R37-3, Section 46.4/46.12;
Epic 39, R39-5, Section 48.6).

youtube-transcript-api мокается через services.youtube_transcript_engine.YouTubeTranscriptApi
(модуль-левел импорт с ImportError-guard — прецедент DDGS в test_search_aggregator.py;
реальная библиотека в тестах НЕ импортируется). Epic 39: yt-dlp мокается через
engine_mod.yt_dlp (types.SimpleNamespace(YoutubeDL=_FakeYDL)) — реальная сеть НЕ ходит.
"""
import json
import logging
import types

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
    """#11: sync-вызов в executor, await корректен, контракт async.
    Epic 39 (48.6 #1): autouse yt_dlp=None — каскад сразу в фолбек transcript-api
    (иначе тесты пошли бы в РЕАЛЬНУЮ сеть yt-dlp)."""

    @pytest.fixture(autouse=True)
    def _no_ytdlp(self, monkeypatch):
        monkeypatch.setattr(engine_mod, "yt_dlp", None)

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


class _FakeYDL:
    """YoutubeDL-fake (48.6): __init__ захватывает opts, extract_info возвращает
    extract_result или рейзит extract_error."""

    last_opts = None
    extract_result = None
    extract_error = None

    def __init__(self, opts):
        _FakeYDL.last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if _FakeYDL.extract_error is not None:
            raise _FakeYDL.extract_error
        return _FakeYDL.extract_result


class _CapturingApi(_FakeApi):
    """list_transcripts с захватом kwargs (proxies/cookies, 48.6 #7/#8)."""

    last_kwargs = None

    @classmethod
    def list_transcripts(cls, video_id, **kwargs):
        _CapturingApi.last_kwargs = kwargs
        return cls.result


def _json3_file(tmp_path, events, name="subs.json3"):
    path = tmp_path / name
    path.write_text(json.dumps({"events": events}), encoding="utf-8")
    return str(path)


def _ytdlp_info(manual=None, auto=None, requested=None):
    return {
        "subtitles": manual or {},
        "automatic_captions": auto or {},
        "requested_subtitles": requested or {},
    }


def _mock_settings(monkeypatch, proxy="", cookies=""):
    monkeypatch.setattr(
        engine_mod,
        "settings",
        types.SimpleNamespace(
            YOUTUBE_TRANSCRIPT_PROXY_URL=proxy,
            YOUTUBE_COOKIES_FILE=cookies,
        ),
    )


class TestYtdlpPrimary:
    """Epic 39 (48.6 #2-11): yt-dlp primary → transcript-api fallback; прокси/
    cookies; приоритеты треков. yt_dlp/YouTubeTranscriptApi подменяются целиком,
    settings — SimpleNamespace: реальная сеть НИКОГДА не дёргается."""

    @pytest.fixture(autouse=True)
    def _mocks(self, monkeypatch):
        _FakeYDL.last_opts = None
        _FakeYDL.extract_result = None
        _FakeYDL.extract_error = None
        _CapturingApi.last_kwargs = None
        monkeypatch.setattr(
            engine_mod, "yt_dlp", types.SimpleNamespace(YoutubeDL=_FakeYDL)
        )
        _mock_settings(monkeypatch)

    @pytest.mark.asyncio
    async def test_ytdlp_success_formats_and_skips_empty_rollup(self, tmp_path, caplog):
        """#2: fake extract_info → json3 с пустым rollup-событием → _format."""
        filepath = _json3_file(
            tmp_path,
            [
                {"tStartMs": 0, "dDurationMs": 382080, "segs": [{"utf8": ""}]},
                {
                    "tStartMs": 3760,
                    "dDurationMs": 2000,
                    "segs": [{"utf8": "Привет, "}, {"utf8": "мир!"}],
                },
                {
                    "tStartMs": 6000,
                    "dDurationMs": 1500,
                    "segs": [{"utf8": "Второй сегмент"}],
                },
            ],
        )
        sub = {"ext": "json3", "filepath": filepath}
        _FakeYDL.extract_result = _ytdlp_info(
            manual={"ru": sub}, auto={"ru": sub}, requested={"ru": sub}
        )
        with caplog.at_level(logging.INFO):
            result = await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert result == "[00:03] Привет, мир!\n[00:06] Второй сегмент"
        assert any("source=yt-dlp" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_ytdlp_download_error_falls_back_to_transcript_api(
        self, caplog, monkeypatch
    ):
        """#3: extract_info raise → WARNING → фолбек transcript-api успех."""
        _FakeYDL.extract_error = RuntimeError("ERROR: unable to download video data")

        class _Api(_FakeApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("ru", False, _segments(("привет", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with caplog.at_level(logging.INFO):
            result = await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert result == "[00:05] привет"
        assert any(
            "yt-dlp failed → transcript-api fallback" in r.message
            and r.levelno == logging.WARNING
            for r in caplog.records
        )
        assert any("source=transcript-api" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_both_engines_fail_raises_unavailable(self, monkeypatch):
        """#4: оба движка падают → YouTubeTranscriptUnavailableException."""
        _FakeYDL.extract_error = RuntimeError("network down")

        class _Api(_FakeApi):
            result = None

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with pytest.raises(
            YouTubeTranscriptUnavailableException, match="both engines failed"
        ):
            await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)

    @pytest.mark.asyncio
    async def test_ytdlp_not_installed_warns_and_falls_back(self, monkeypatch, caplog):
        """#5: yt_dlp=None (ImportError-прецедент) → WARNING в __init__ + фолбек."""
        monkeypatch.setattr(engine_mod, "yt_dlp", None)

        class _Api(_FakeApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("en", True, _segments(("hello", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        with caplog.at_level(logging.WARNING):
            result = await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert result == "[00:05] hello"
        assert any("yt-dlp is not installed" in r.message for r in caplog.records)
        assert any(
            "transcript-api fallback" in r.message for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_proxy_and_cookies_passed_to_ytdlp_opts(self, tmp_path, monkeypatch):
        """#6: непустые настройки → opts['proxy']/opts['cookiefile']."""
        filepath = _json3_file(
            tmp_path,
            [{"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "текст"}]}],
        )
        sub = {"ext": "json3", "filepath": filepath}
        _FakeYDL.extract_result = _ytdlp_info(
            manual={"ru": sub}, auto={}, requested={"ru": sub}
        )
        _mock_settings(monkeypatch, proxy="http://pr:8080", cookies="/tmp/c.txt")
        await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert _FakeYDL.last_opts["proxy"] == "http://pr:8080"
        assert _FakeYDL.last_opts["cookiefile"] == "/tmp/c.txt"

    @pytest.mark.asyncio
    async def test_proxy_and_cookies_passed_to_transcript_api(self, monkeypatch):
        """#7: yt-dlp raise + непустые настройки → list_transcripts с kwargs."""
        _FakeYDL.extract_error = RuntimeError("boom")

        class _Api(_CapturingApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("ru", False, _segments(("привет", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        _mock_settings(monkeypatch, proxy="http://pr:8080", cookies="/tmp/c.txt")
        await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert _CapturingApi.last_kwargs == {
            "proxies": {"http": "http://pr:8080", "https": "http://pr:8080"},
            "cookies": "/tmp/c.txt",
        }

    @pytest.mark.asyncio
    async def test_empty_settings_no_ytdlp_proxy_keys(self, tmp_path):
        """#8: пустые настройки → opts БЕЗ proxy/cookiefile."""
        filepath = _json3_file(
            tmp_path,
            [{"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "текст"}]}],
        )
        sub = {"ext": "json3", "filepath": filepath}
        _FakeYDL.extract_result = _ytdlp_info(
            manual={"ru": sub}, auto={}, requested={"ru": sub}
        )
        await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert "proxy" not in _FakeYDL.last_opts
        assert "cookiefile" not in _FakeYDL.last_opts

    @pytest.mark.asyncio
    async def test_empty_settings_no_transcript_api_kwargs(self, monkeypatch):
        """#8: пустые настройки → list_transcripts БЕЗ kwargs (регрессия: моки 46.4 живы)."""
        _FakeYDL.extract_error = RuntimeError("boom")

        class _Api(_CapturingApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("ru", False, _segments(("привет", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert _CapturingApi.last_kwargs == {}

    @pytest.mark.parametrize(
        "manual_langs,auto_langs,requested_langs,expected_lang",
        [
            (("ru", "en"), (), ("ru", "en"), "ru"),
            (("en",), ("ru",), ("ru", "en"), "ru"),
            ((), ("en",), ("en",), "en"),
        ],
    )
    def test_track_priority(
        self, tmp_path, manual_langs, auto_langs, requested_langs, expected_lang
    ):
        """#9: приоритеты _extract_ytdlp_segments (requested manual-preferred
        внутри языка): manual ru+en → ru; manual en + auto ru → ru; auto en → en."""
        subs = {}
        for lang in ("ru", "en"):
            subs[lang] = {
                "ext": "json3",
                "filepath": _json3_file(
                    tmp_path,
                    [
                        {
                            "tStartMs": 1000,
                            "dDurationMs": 1000,
                            "segs": [{"utf8": f"текст-{lang}"}],
                        }
                    ],
                    name=f"sub_{lang}.json3",
                ),
            }
        info = {
            "subtitles": {lang: subs[lang] for lang in manual_langs},
            "automatic_captions": {lang: subs[lang] for lang in auto_langs},
            "requested_subtitles": {lang: subs[lang] for lang in requested_langs},
        }
        segments = YouTubeTranscriptEngine()._extract_ytdlp_segments(info, "video-1")
        assert [s["text"] for s in segments] == [f"текст-{expected_lang}"]

    def test_no_ru_en_requested_raises(self, tmp_path):
        """#10: ни ru, ни en в requested → raise (делегация приоритета 5)."""
        sub = {
            "ext": "json3",
            "filepath": _json3_file(
                tmp_path,
                [{"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "bonjour"}]}],
                name="sub_fr.json3",
            ),
        }
        info = _ytdlp_info(manual={"fr": sub}, auto={}, requested={"fr": sub})
        with pytest.raises(YouTubeTranscriptUnavailableException):
            YouTubeTranscriptEngine()._extract_ytdlp_segments(info, "video-1")

    @pytest.mark.asyncio
    async def test_priority5_delegates_to_fallback(self, tmp_path, monkeypatch):
        """#10: приоритет 5 (прочий generated) → фолбек transcript-api умеет его."""
        sub = {
            "ext": "json3",
            "filepath": _json3_file(
                tmp_path,
                [{"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": "bonjour"}]}],
                name="sub_fr.json3",
            ),
        }
        _FakeYDL.extract_result = _ytdlp_info(
            manual={"fr": sub}, auto={}, requested={"fr": sub}
        )

        class _Api(_FakeApi):
            result = _FakeTranscriptList(
                [_FakeTranscript("fr", True, _segments(("bonjour", 5.0)))]
            )

        monkeypatch.setattr(engine_mod, "YouTubeTranscriptApi", _Api)
        result = await YouTubeTranscriptEngine().fetch_transcript("video-1", 4000)
        assert result == "[00:05] bonjour"

    def test_missing_filepath_raises(self):
        """#11: нет filepath → raise → фолбек."""
        with pytest.raises(
            YouTubeTranscriptUnavailableException, match="subtitle file missing"
        ):
            YouTubeTranscriptEngine()._read_ytdlp_subtitle(
                {"ext": "json3", "filepath": None}, "video-1"
            )

    def test_unknown_ext_raises(self, tmp_path):
        """#11: неизвестный ext → raise → фолбек."""
        path = tmp_path / "subs.ass"
        path.write_text("whatever", encoding="utf-8")
        with pytest.raises(
            YouTubeTranscriptUnavailableException, match="unsupported subtitle format"
        ):
            YouTubeTranscriptEngine()._read_ytdlp_subtitle(
                {"ext": "ass", "filepath": str(path)}, "video-1"
            )

    def test_empty_segments_raise(self, tmp_path):
        """#11: только пустые rollup-события → raise «empty transcript» → фолбек."""
        filepath = _json3_file(
            tmp_path,
            [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": ""}]}],
        )
        with pytest.raises(
            YouTubeTranscriptUnavailableException, match="empty transcript"
        ):
            YouTubeTranscriptEngine()._read_ytdlp_subtitle(
                {"ext": "json3", "filepath": filepath}, "video-1"
            )


class TestNormalizers:
    """Epic 39 (48.6 #12-16): JSON3/VTT/SRT/TTML + _ts_to_seconds →
    {text, start, duration} (start — float-секунды, совместимо с _format)."""

    def test_json3_ms_to_seconds_and_rollup_skip(self):
        """#12: tStartMs=3760 → start 3.76; пустой rollup пропущен; пробелы схлопнуты."""
        content = json.dumps(
            {
                "events": [
                    {"tStartMs": 0, "dDurationMs": 382080, "segs": [{"utf8": ""}]},
                    {
                        "tStartMs": 3760,
                        "dDurationMs": 2000,
                        "segs": [{"utf8": "  Привет,  "}, {"utf8": "мир!\n"}],
                    },
                ]
            }
        )
        segments = YouTubeTranscriptEngine._normalize_json3(content)
        assert segments == [
            {"text": "Привет, мир!", "start": 3.76, "duration": 2.0},
        ]

    def test_vtt_tags_multiline_timing(self):
        """#13: align-хвост игнорируется, <c>-теги стрипнуты, multiline склеен."""
        content = (
            "WEBVTT\n"
            "Kind: captions\n"
            "\n"
            "00:00:03.420 --> 00:07:13.940 align:start position:0%\n"
            "Привет <c.yellow>мир</c.yellow>\n"
            "вторая строка\n"
            "\n"
            "00:07:14.000 --> 00:07:20.500 align:start\n"
            "Пока"
        )
        segments = YouTubeTranscriptEngine._normalize_vtt_srt(content)
        assert [s["text"] for s in segments] == ["Привет мир вторая строка", "Пока"]
        assert segments[0]["start"] == 3.42
        assert segments[0]["duration"] == pytest.approx(430.52)
        assert segments[1]["start"] == 434.0
        assert segments[1]["duration"] == 6.5

    def test_srt_comma_timestamps(self):
        """#14: SRT с запятыми в таймкодах."""
        content = "00:00:03,420 --> 00:00:07,940\nТекст <i>курсивом</i>\nвторая"
        segments = YouTubeTranscriptEngine._normalize_vtt_srt(content)
        assert segments == [
            {"text": "Текст курсивом вторая", "start": 3.42, "duration": pytest.approx(4.52)},
        ]

    def test_ttml_tags_stripped(self):
        """#15: TTML <p begin/end>, теги стрипнуты, текст склеен."""
        content = (
            '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
            '<p begin="00:00:03.420" end="00:00:07.940">Привет, <br/> мир</p>'
            "</div></body></tt>"
        )
        segments = YouTubeTranscriptEngine._normalize_ttml(content)
        assert segments == [
            {"text": "Привет, мир", "start": 3.42, "duration": pytest.approx(4.52)},
        ]

    @pytest.mark.parametrize(
        "ts,expected",
        [
            ("01:02:03.500", 3723.5),
            ("01:02", 62.0),
            ("12.3", 12.3),
            ("00:01:02,5", 62.5),
        ],
    )
    def test_ts_to_seconds(self, ts, expected):
        """#16: «HH:MM:SS.mmm» / «MM:SS.mmm» / «SS.mmm», ',' = '.'."""
        assert YouTubeTranscriptEngine._ts_to_seconds(ts) == expected
