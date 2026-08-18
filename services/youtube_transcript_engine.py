# services/youtube_transcript_engine.py (ПРАВКА, Epic 39, R39-1/R39-2, Section 48.3)
"""Epic 37/39 — YouTube Transcript Engine (R37-3, Section 46.4; R39-1/2, Section 48).

Epic 39: yt-dlp (основной) → youtube-transcript-api (фолбек, D140). Контракт
fetch_transcript(video_id, max_symbols) -> str и YouTubeTranscriptUnavailableException
БЕЗ изменений. Прокси/cookies — из settings (R17: значения НЕ логируются, D144).
"""
import asyncio
import json
import logging
import os
import re
import shutil
import tempfile

from config.settings import settings

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    YouTubeTranscriptApi = None

try:
    import yt_dlp
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    yt_dlp = None

logger = logging.getLogger(__name__)

_YTDLP_SOCKET_TIMEOUT = 20        # D139: граница КАЖДОГО сетевого вызова yt-dlp
_YTDLP_SUBTITLE_LANGS = ("ru", "en")


class YouTubeTranscriptUnavailableException(Exception):
    """Транскрипт недоступен (ОБА движка упали): нет субтитров / приватность /
    видео удалено / 429 / сетевой сбой. → пул 5.6 (YOUTUBE_ERROR_PHRASES)."""


class YouTubeTranscriptEngine:
    """yt-dlp primary → transcript-api fallback. Формат [MM:SS] text, truncate."""

    def __init__(self) -> None:
        """D144: факт конфигурации логируется ОДИН раз при создании (bot.py
        on_startup), значения — НИКОГДА (R17)."""
        proxy = (settings.YOUTUBE_TRANSCRIPT_PROXY_URL or "").strip()
        cookies = (settings.YOUTUBE_COOKIES_FILE or "").strip()
        logger.info(
            "[youtube engine] config | proxy=%s | cookies=%s",
            "set" if proxy else "empty", "set" if cookies else "empty",
        )
        if yt_dlp is None:  # pragma: no cover
            logger.warning(
                "[youtube engine] yt-dlp is not installed — every request "
                "will go to transcript-api"
            )

    async def fetch_transcript(self, video_id: str, max_symbols: int) -> str:
        """yt-dlp (основной) → при неудаче youtube-transcript-api (фолбек) →
        YouTubeTranscriptUnavailableException. Контракт БЕЗ изменений (46.4);
        sync-вызовы — в asyncio.to_thread (прецедент DDGS / 46.4)."""
        try:
            segments = await asyncio.to_thread(self._fetch_ytdlp, video_id)
            logger.info(
                "[youtube engine] transcript ok | source=yt-dlp | "
                "video_id=%r | segments=%d", video_id, len(segments),
            )
            return self._format(segments, max_symbols)
        except Exception as exc:
            logger.warning(
                "[youtube engine] yt-dlp failed → transcript-api fallback | "
                "video_id=%r | error=%s", video_id, exc,
            )
        try:
            segments = await asyncio.to_thread(self._fetch_segments, video_id)
            logger.info(
                "[youtube engine] transcript ok | source=transcript-api | "
                "video_id=%r | segments=%d", video_id, len(segments),
            )
            return self._format(segments, max_symbols)
        except Exception as exc:
            raise YouTubeTranscriptUnavailableException(
                f"both engines failed | video_id={video_id!r} ({exc})"
            ) from exc

    # ── Основной движок: yt-dlp (R39-1, D139/D141) ────────────────

    def _fetch_ytdlp(self, video_id: str) -> list[dict]:
        """Sync-блок (executor). extract_info(download=True) + skip_download →
        yt-dlp сам скачивает файлы субтитров во временную папку (подписанные
        timedtext-URL + impersonation-хедеры — НЕ self-fetch, 48.1), парсим файл
        выбранного трека, папку удаляем в finally. Любая ошибка (DownloadError
        на 429 субтитров, VideoUnavailable, сеть) — наверх → фолбек."""
        if yt_dlp is None:  # pragma: no cover
            raise RuntimeError("yt-dlp is not installed")
        tmpdir = tempfile.mkdtemp(prefix="ytdlp_subs_")
        try:
            opts = self._ytdlp_opts()
            opts["outtmpl"] = os.path.join(tmpdir, "%(id)s.%(ext)s")
            opts["paths"] = {"home": tmpdir}
            url = f"https://www.youtube.com/watch?v={video_id}"
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            return self._extract_ytdlp_segments(info, video_id)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _ytdlp_opts(self) -> dict:
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": list(_YTDLP_SUBTITLE_LANGS),
            "subtitlesformat": "json3",
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,          # обязательно: quiet без noprogress
            "noplaylist": True,          # не глушит [download]-строки (48.1)
            "socket_timeout": _YTDLP_SOCKET_TIMEOUT,
            "overwrites": True,
        }
        proxy = (settings.YOUTUBE_TRANSCRIPT_PROXY_URL or "").strip()
        if proxy:
            opts["proxy"] = proxy
        cookies = (settings.YOUTUBE_COOKIES_FILE or "").strip()
        if cookies:
            opts["cookiefile"] = cookies
        return opts

    def _extract_ytdlp_segments(self, info: dict, video_id: str) -> list[dict]:
        """Выбор трека — зеркало _pick_transcript (D141): manual ru → manual en →
        generated ru → generated en. requested_subtitles[lang] уже manual-preferred
        внутри языка (process_subtitles, 48.1), поэтому итерация по ("ru","en")
        даёт ровно 4 первые приоритета. Приоритет 5 (прочий generated) НЕ качаем
        (subtitleslangs ограничен ru/en) — кейс делегируется фолбеку
        transcript-api, где _pick_transcript умеет его с Epic 37."""
        manual = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}
        requested = info.get("requested_subtitles") or {}
        for lang in _YTDLP_SUBTITLE_LANGS:
            if lang in requested and (lang in manual or lang in auto):
                return self._read_ytdlp_subtitle(requested[lang], video_id)
        raise YouTubeTranscriptUnavailableException(
            f"yt-dlp: no ru/en subtitles | video_id={video_id!r}"
        )

    def _read_ytdlp_subtitle(self, sub_info: dict, video_id: str) -> list[dict]:
        filepath = sub_info.get("filepath")
        if not filepath or not os.path.exists(filepath):
            raise YouTubeTranscriptUnavailableException(
                f"yt-dlp: subtitle file missing | video_id={video_id!r}"
            )
        ext = (sub_info.get("ext") or "").lower()
        with open(filepath, encoding="utf-8") as fh:
            content = fh.read()
        if ext == "json3":
            segments = self._normalize_json3(content)
        elif ext in ("vtt", "srt"):
            segments = self._normalize_vtt_srt(content)
        elif ext == "ttml":
            segments = self._normalize_ttml(content)
        else:
            raise YouTubeTranscriptUnavailableException(
                f"yt-dlp: unsupported subtitle format {ext!r} | video_id={video_id!r}"
            )
        if not segments:
            raise YouTubeTranscriptUnavailableException(
                f"yt-dlp: empty transcript | video_id={video_id!r}"
            )
        return segments

    # ── Нормализация форматов (D141, 48.1) ─────────────────────

    @staticmethod
    def _ts_to_seconds(ts: str) -> float:
        """«HH:MM:SS.mmm» | «MM:SS.mmm» | «SS.mmm» → float-секунды; ',' = '.'."""
        parts = [float(p) for p in ts.replace(",", ".").split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0]

    @staticmethod
    def _normalize_json3(content: str) -> list[dict]:
        """events[] → {text, start, duration}; ms → секунды; пустые rollup-события
        (48.1: tStartMs=0, dDurationMs=382080, text='') пропускаются."""
        segments = []
        for event in json.loads(content).get("events", []):
            text = "".join(seg.get("utf8", "") for seg in event.get("segs") or [])
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            segments.append({
                "text": text,
                "start": float(event.get("tStartMs") or 0) / 1000.0,
                "duration": float(event.get("dDurationMs") or 0) / 1000.0,
            })
        return segments

    @staticmethod
    def _normalize_vtt_srt(content: str) -> list[dict]:
        """Cue-блоки по пустым строкам; заголовок «HH:MM:SS.mmm --> …»
        (хвост настроек после «-->» игнорируется); inline-теги стрипятся;
        многострочный текст склеивается пробелами; duration = end - start (>=0)."""
        segments = []
        for block in re.split(r"\n\s*\n", content.strip()):
            header, *lines = block.strip().split("\n")
            m = re.match(r"^([\d:.]+[.,]?\d*)\s*-->\s*([\d:.]+[.,]?\d*)", header)
            if not m:
                continue
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", " ".join(lines))).strip()
            if not text:
                continue
            start = YouTubeTranscriptEngine._ts_to_seconds(m.group(1))
            end = YouTubeTranscriptEngine._ts_to_seconds(m.group(2))
            segments.append({
                "text": text, "start": start, "duration": max(end - start, 0.0),
            })
        return segments

    @staticmethod
    def _normalize_ttml(content: str) -> list[dict]:
        segments = []
        for m in re.finditer(
            r'<p\b[^>]*\bbegin="([^"]+)"[^>]*end="([^"]+)"[^>]*>(.*?)</p>',
            content, re.S,
        ):
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(3))).strip()
            if not text:
                continue
            start = YouTubeTranscriptEngine._ts_to_seconds(m.group(1))
            end = YouTubeTranscriptEngine._ts_to_seconds(m.group(2))
            segments.append({
                "text": text, "start": start, "duration": max(end - start, 0.0),
            })
        return segments

    # ── Фолбек: youtube-transcript-api (R39-2, D140) ────────────

    def _transcript_api_kwargs(self) -> dict:
        """Прокси (requests-формат {"http": u, "https": u}) и cookies (путь к
        Netscape-файлу). Пусто → ПУСТОЙ dict: вызов list_transcripts(video_id)
        идентичен 46.4 — существующие моки/тесты живы без правок."""
        kwargs = {}
        proxy = (settings.YOUTUBE_TRANSCRIPT_PROXY_URL or "").strip()
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        cookies = (settings.YOUTUBE_COOKIES_FILE or "").strip()
        if cookies:
            kwargs["cookies"] = cookies
        return kwargs

    def _fetch_segments(self, video_id: str) -> list[dict]:
        """Как 46.4 + прокидывание proxies/cookies в list_transcripts
        (сессия с ними доходит до fetch() — проверено по исходникам 0.6.3)."""
        if YouTubeTranscriptApi is None:  # pragma: no cover
            raise YouTubeTranscriptUnavailableException(
                "youtube-transcript-api is not installed"
            )
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(
                video_id, **self._transcript_api_kwargs()
            )
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

    # _pick_transcript / _format — БЕЗ изменений (46.4)
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
