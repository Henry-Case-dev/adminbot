"""Tests for services/smartmodule_urls.py (T-289, R37-4, D125/D128, Section 46.3/46.12).

D125: только MVP-формы YouTube (watch?v= / shorts/ / youtu.be/, www. опционален);
m./music./live/embed — вне скоупа. D128: extract_web_url пропускает YouTube-URL,
приоритет YouTube при выборе video_id.
"""
import pytest

from services.smartmodule_urls import extract_web_url, extract_youtube_video_id

YT_ID = "dQw4w9WgXcQ"


class TestExtractYoutubeVideoId:
    @pytest.mark.parametrize(
        "text,expected",
        [
            (f"https://youtube.com/watch?v={YT_ID}", YT_ID),
            (f"https://youtube.com/watch?t=10&v={YT_ID}", YT_ID),
            (f"https://www.youtube.com/watch?v={YT_ID}", YT_ID),
            (f"https://youtube.com/shorts/{YT_ID}", YT_ID),
            (f"https://www.youtube.com/shorts/{YT_ID}", YT_ID),
            (f"https://youtu.be/{YT_ID}", YT_ID),
            (f"https://www.youtu.be/{YT_ID}", YT_ID),
            (f"глянь вот это {YT_ID} прямо сюда: https://youtu.be/{YT_ID} ок", YT_ID),
            (f"https://youtube.com/watch?list=PL1&index=2&v={YT_ID}", YT_ID),
        ],
    )
    def test_valid_forms(self, text, expected):
        assert extract_youtube_video_id(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",          # m. — вне скоупа
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",      # music. — вне скоупа
            "https://youtube.com/live/dQw4w9WgXcQ",               # live — вне скоупа
            "https://youtube.com/embed/dQw4w9WgXcQ",              # embed — вне скоупа
            "https://youtube.com/watch?v=short",                  # ID < 11 символов
            "https://youtube.com/watch?v=",                       # пустой ID
            "https://youtu.be/abc",                               # ID < 11 символов
            "https://vimeo.com/12345",                            # не YouTube
            "просто текст без ссылок",
            "",
        ],
    )
    def test_out_of_scope_returns_none(self, text):
        assert extract_youtube_video_id(text) is None


class TestExtractWebUrl:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("вот ссылка: https://x.com/a.", "https://x.com/a"),
            ("https://x.com/a,", "https://x.com/a"),
            ("https://x.com/a!", "https://x.com/a"),
            ("смотри https://x.com/a). тут", "https://x.com/a"),
            ("https://x.com/a\"", "https://x.com/a"),
            ("https://x.com/путь", "https://x.com/путь"),
        ],
    )
    def test_trailing_punctuation_stripped(self, text, expected):
        assert extract_web_url(text) == expected

    def test_plain_url_without_punct_untouched(self):
        assert extract_web_url("тут https://x.com/a?b=c&d=1 норм") == "https://x.com/a?b=c&d=1"

    def test_youtube_url_skipped_web_url_taken(self):
        """D128: YouTube-URL в веб-парсер НЕ уходит — берётся следующий веб-URL."""
        text = f"https://youtu.be/{YT_ID} и https://habr.com/ru/articles/1"
        assert extract_web_url(text) == "https://habr.com/ru/articles/1"

    def test_only_youtube_url_returns_none(self):
        assert extract_web_url(f"https://youtu.be/{YT_ID}") is None

    def test_youtube_www_forms_skipped(self):
        text = f"https://www.youtube.com/watch?v={YT_ID} затем https://x.com/a"
        assert extract_web_url(text) == "https://x.com/a"

    def test_no_url_returns_none(self):
        assert extract_web_url("просто текст без ссылок") is None
        assert extract_web_url("") is None


class TestPriority:
    def test_web_url_earlier_youtube_later_youtube_wins(self):
        """D128: приоритет YouTube-URL — video_id извлекается независимо от позиции."""
        text = f"https://x.com/a потом https://youtu.be/{YT_ID}"
        assert extract_youtube_video_id(text) == YT_ID

    def test_youtube_earlier_web_later_web_extractor_takes_web(self):
        text = f"https://youtu.be/{YT_ID} потом https://x.com/a"
        assert extract_web_url(text) == "https://x.com/a"

    def test_first_youtube_of_two(self):
        text = f"https://youtu.be/{YT_ID} и https://youtube.com/watch?v=aaaaaaaaaaa"
        assert extract_youtube_video_id(text) == YT_ID

    def test_first_web_of_two(self):
        text = "https://a.com/1 и https://b.com/2"
        assert extract_web_url(text) == "https://a.com/1"
