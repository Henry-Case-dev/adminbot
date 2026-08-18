"""Epic 37 — URL-экстракция и классификация (D125/D128, Section 46.3)."""
import re

# D125: ТОЛЬКО три MVP-формы (watch?v= / shorts/ / youtu.be/), префикс www.
# опционален. m./music./live/embed — НЕ матчатся (вне скоупа).
# watch: допускает произвольные параметры ДО v= (…&v=ID), ID — 11 символов [0-9A-Za-z_-].
_YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:youtube\.com/(?:watch\?(?:[^\s&]+&)*v=|shorts/)|youtu\.be/)"
    r"([0-9A-Za-z_-]{11})"
)

# Generic web: любой http(s)-URL; стрип хвостовой пунктуации (сообщения чата:
# «вот ссылка: https://x.com/a.» — точка не должна попасть в URL).
_WEB_URL_RE = re.compile(r"https?://[^\s]+")
_TRAILING_PUNCT = ".,!?;:)]}\"'"


def extract_youtube_video_id(text: str) -> str | None:
    """Первый YouTube-URL → video_id (D125-формы). None — нет/невалидный."""
    match = _YOUTUBE_URL_RE.search(text)
    return match.group(1) if match else None


def extract_web_url(text: str) -> str | None:
    """Первый http(s)-URL, НЕ являющийся YouTube-URL, с чисткой хвостовой
    пунктуации. None — нет (или есть только YouTube)."""
    for match in _WEB_URL_RE.finditer(text):
        candidate = match.group(0)
        if _YOUTUBE_URL_RE.search(candidate):
            continue          # D128: YouTube-URL — в веб-парсер не уходит
        return candidate.rstrip(_TRAILING_PUNCT) or None
    return None
