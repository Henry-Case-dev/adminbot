"""Epic 37 — YouTube Transcript Engine (R37-3, Section 46.4)."""
import asyncio
import logging

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    YouTubeTranscriptApi = None

logger = logging.getLogger(__name__)


class YouTubeTranscriptUnavailableException(Exception):
    """Транскрипт недоступен: нет субтитров / приватность / видео удалено /
    429 / сетевой сбой библиотеки. → пул 5.6 (YOUTUBE_ERROR_PHRASES)."""


class YouTubeTranscriptEngine:
    """Субтитры ru → en → автогенерированные, формат [MM:SS] text, truncate."""

    async def fetch_transcript(self, video_id: str, max_symbols: int) -> str:
        """1) segments = await asyncio.to_thread(self._fetch_segments, video_id)
        2) return self._format(segments, max_symbols)
        Raises YouTubeTranscriptUnavailableException (оборачивает ВСЕ ошибки
        библиотеки: TranscriptsDisabled/NoTranscriptFound/VideoUnavailable/
        TooManyRequests/сетевые)."""
        segments = await asyncio.to_thread(self._fetch_segments, video_id)
        return self._format(segments, max_symbols)

    def _fetch_segments(self, video_id: str) -> list[dict]:
        """Sync-блок (исполняется в executor). list_transcripts(video_id):
        приоритет (D-решение, дословно ТЗ «ru -> en -> автогенерированные»):
        1) manual ru → 2) manual en → 3) generated ru → 4) generated en →
        5) любой другой generated; пусто/нет списка → raise.
        Возвращает list[dict] c ключами text/start/duration (fetch() ветки 0.6.x)."""
        if YouTubeTranscriptApi is None:  # pragma: no cover
            raise YouTubeTranscriptUnavailableException(
                "youtube-transcript-api is not installed"
            )
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        except Exception as exc:
            raise YouTubeTranscriptUnavailableException(
                f"list_transcripts failed | video_id={video_id!r} ({exc})"
            ) from exc
        transcript = self._pick_transcript(transcript_list, video_id)
        try:
            return transcript.fetch()
        except Exception as exc:
            raise YouTubeTranscriptUnavailableException(
                f"transcript fetch failed | video_id={video_id!r} ({exc})"
            ) from exc

    @staticmethod
    def _pick_transcript(transcript_list, video_id: str):
        """Приоритет: manual ru → manual en → generated ru → generated en →
        любой другой generated; нет → YouTubeTranscriptUnavailableException."""
        if transcript_list is None:
            raise YouTubeTranscriptUnavailableException(
                f"no transcript list | video_id={video_id!r}"
            )
        for generated, language_codes in (
            (False, ["ru"]),
            (False, ["en"]),
            (True, ["ru"]),
            (True, ["en"]),
        ):
            try:
                if generated:
                    return transcript_list.find_generated_transcript(language_codes)
                return transcript_list.find_manually_created_transcript(language_codes)
            except Exception:
                continue
        try:
            return next(
                t for t in transcript_list if getattr(t, "is_generated", False)
            )
        except (StopIteration, TypeError):
            pass
        raise YouTubeTranscriptUnavailableException(
            f"no suitable transcript | video_id={video_id!r}"
        )

    @staticmethod
    def _format(segments: list[dict], max_symbols: int) -> str:
        """Склейка таймкодов и текста: строка "[MM:SS] text" на сегмент, "\n" join.
        Таймкод: f"{int(start)//60:02d}:{int(start)%60:02d}" (floor, как в плеерах).
        Длинные видео: накопление с ранним стопом при превышении max_symbols +
        финальный жёсткий text[:max_symbols] (прецедент SearchAggregator._truncate)."""
        lines: list[str] = []
        total = 0
        for segment in segments:
            start = float(segment.get("start") or 0)
            text = str(segment.get("text") or "")
            line = f"[{int(start) // 60:02d}:{int(start) % 60:02d}] {text}"
            if lines and total + len(line) + 1 > max_symbols:
                break                       # ранний стоп (длинные видео)
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)[:max_symbols]   # финальный жёсткий срез
