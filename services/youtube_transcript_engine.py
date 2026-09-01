# services/youtube_transcript_engine.py (ПРАВКА, Epic 41, R41-1/R41-2/R41-3, Section 50.3; Epic 80/81, Section 81/82, D301/D312/D313)
"""Epic 37/39/41 — YouTube Transcript Engine (R37-3, 46.4; R39-1/2, 48; R41-1/2/3, 50).

Epic 41: каскад с ретраями (4 ретрая = 5 попыток, D151), ru-first через
ignoreerrors (D154), классификация транзиентных фейлов (D155), on_retry-колбэк
(D156), статус/размер тела в логах фолбека (D157). Контракт
fetch_transcript(video_id, max_symbols) -> str расширяется ОПЦИОНАЛЬНЫМ
kwarg on_retry=None (позиционная совместимость сохранена).

Epic 80/81 (Section 81/82): (a) D301 — player_client/extractor_args только в
_transcript_ytdlp_opts() (build_ytdlp_base_opts остаётся без POT/player_client
— не-YouTube пути чисты); (b) D312 — миграция youtube-transcript-api 0.6.x →
1.2.x: инстанс `YouTubeTranscriptApi(proxy_config=...)` + `.list(video_id)` +
`transcript.fetch().to_raw_data()`; cookies в fallback НЕ пробрасываются; (c)
D313 — resident-прокси Webshare через `_transcript_proxy_config()`
(WebshareProxyConfig/GenericProxyConfig/None); RequestBlocked/IpBlocked →
TRANSIENT, AgeRestricted/VideoUnplayable → PERMANENT.
"""
import asyncio
from services import hot_config as hot
import json
import logging
import os
import re
import shutil
import tempfile
from typing import Awaitable, Callable

from config.settings import build_ytdlp_base_opts, settings

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    YouTubeTranscriptApi = None

try:  # youtube-transcript-api >=1.2.0 (Epic 81, D312)
    from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
except ImportError:  # pragma: no cover — 0.6.x не несёт модуль proxies
    GenericProxyConfig = None
    WebshareProxyConfig = None

try:
    import yt_dlp
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    yt_dlp = None

logger = logging.getLogger(__name__)

_YTDLP_SOCKET_TIMEOUT = 20        # D139 (48.3): граница КАЖДОГО сетевого вызова yt-dlp
_YTDLP_SUBTITLE_LANGS = ("ru", "en")
_MAX_CASCADE_RETRIES = 4          # D151: 4 ретрая = 5 попыток каскада (1 стартовая + 4)
_RETRY_BACKOFFS = (1.0, 2.0, 4.0, 8.0)   # D152: экспонента, cap 8с; len == _MAX_CASCADE_RETRIES
_RETRY_HTTP_STATUSES = frozenset({403, 429, 500, 502, 503, 504})  # D155: транзиентные


class YouTubeTranscriptUnavailableException(Exception):
    """Транскрипт недоступен (ОБА движка упали): нет субтитров / приватность /
    видео удалено / 429 / сетевой сбой. → пул 5.6 (YOUTUBE_ERROR_PHRASES)."""


class YouTubeTranscriptEngine:
    """yt-dlp primary → transcript-api fallback. Формат [MM:SS] text, truncate."""

    def __init__(self) -> None:
        """D144: факт конфигурации логируется ОДИН раз при создании (bot.py
        on_startup), значения — НИКОГДА (R17)."""
        proxy = (hot.get("keys.youtube_transcript_proxy_url", settings.YOUTUBE_TRANSCRIPT_PROXY_URL) or "").strip()
        cookies = (hot.get("keys.youtube_cookies_file", settings.YOUTUBE_COOKIES_FILE) or "").strip()
        resproxy = bool(
            (hot.get("keys.youtube_transcript_proxy_username", settings.YOUTUBE_TRANSCRIPT_PROXY_USERNAME) or "").strip()
            and (hot.get("keys.youtube_transcript_proxy_password", settings.YOUTUBE_TRANSCRIPT_PROXY_PASSWORD) or "").strip()
        )
        logger.info(
            "[youtube engine] config | proxy=%s | cookies=%s | resproxy=%s",
            "set" if proxy else "empty",
            "set" if cookies else "empty",
            "set" if resproxy else "empty",
        )
        if not resproxy:
            logger.warning(
                "[youtube engine] transcript-api resident proxy disabled "
                "(resproxy=empty)"
            )
        if yt_dlp is None:  # pragma: no cover
            logger.warning(
                "[youtube engine] yt-dlp is not installed — every request "
                "will go to transcript-api"
            )

    async def fetch_transcript(
        self,
        video_id: str,
        max_symbols: int,
        on_retry: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> str:
        """D151/D152/D156: попытка = ВЕСЬ каскад (yt-dlp → transcript-api).
        Транзиентный фейл попытки (хотя бы один движок транзиентен, D155) →
        on_retry(attempt, _MAX_CASCADE_RETRIES) → sleep(backoff) → повтор;
        максимум _MAX_CASCADE_RETRIES ретраев. Перманентный фейл ОБОИХ →
        немедленный raise (0 ретраев). on_retry=None — ретраи без уведомлений."""
        ytdlp_exc: BaseException | None = None
        api_exc: BaseException | None = None
        for attempt in range(1, _MAX_CASCADE_RETRIES + 2):        # 1..5
            try:
                segments = await asyncio.to_thread(self._fetch_ytdlp, video_id)
                logger.info(
                    "[youtube engine] transcript ok | source=yt-dlp | "
                    "video_id=%r | segments=%d | attempt=%d",
                    video_id, len(segments), attempt,
                )
                return self._format(segments, max_symbols)
            except Exception as exc:
                ytdlp_exc = exc
                logger.warning(
                    "[youtube engine] yt-dlp failed → transcript-api fallback | "
                    "video_id=%r | error=%s | status=%s | body_bytes=%s",
                    video_id, exc,
                    self._exc_status(exc), self._exc_body_bytes(exc),
                )
            try:
                segments = await asyncio.to_thread(self._fetch_segments, video_id)
                logger.info(
                    "[youtube engine] transcript ok | source=transcript-api | "
                    "video_id=%r | segments=%d | attempt=%d",
                    video_id, len(segments), attempt,
                )
                return self._format(segments, max_symbols)
            except Exception as exc:
                api_exc = exc
                logger.warning(
                    "[youtube engine] transcript-api failed | video_id=%r | "
                    "error=%s | status=%s | body_bytes=%s",
                    video_id, exc,
                    self._exc_status(exc), self._exc_body_bytes(exc),
                )
            transient = (
                self._is_transient(ytdlp_exc) or self._is_transient(api_exc)
            )
            if not transient or attempt > _MAX_CASCADE_RETRIES:
                break
            await self._notify_retry(on_retry, attempt, video_id)
            logger.warning(
                "[youtube engine] cascade attempt %d failed (transient) → "
                "retry in %.0fs | video_id=%r",
                attempt, _RETRY_BACKOFFS[attempt - 1], video_id,
            )
            await asyncio.sleep(_RETRY_BACKOFFS[attempt - 1])
        raise YouTubeTranscriptUnavailableException(
            f"both engines failed after {attempt} attempt(s) | video_id={video_id!r} "
            f"(yt-dlp: {ytdlp_exc} [status={self._exc_status(ytdlp_exc)}, "
            f"body_bytes={self._exc_body_bytes(ytdlp_exc)}]; "
            f"transcript-api: {api_exc} [status={self._exc_status(api_exc)}, "
            f"body_bytes={self._exc_body_bytes(api_exc)}])"
        )

    async def _notify_retry(
        self,
        on_retry: Callable[[int, int], Awaitable[None]] | None,
        attempt: int,
        video_id: str,
    ) -> None:
        """D156: вызов (attempt, _MAX_CASCADE_RETRIES) ПЕРЕД sleep — ровно
        (1,4),(2,4),(3,4),(4,4). Колбэк НЕ должен ронять каскад: любое
        исключение глушится logger.exception (в т.ч. исчезнувший reply-таргет
        в хендлере)."""
        if on_retry is None:
            return
        try:
            await on_retry(attempt, _MAX_CASCADE_RETRIES)
        except Exception:
            logger.exception(
                "[youtube engine] on_retry callback failed (ignored) | video_id=%r",
                video_id,
            )

    # ── Основной движок: yt-dlp (R39-1, D139/D141) ────────────────

    def _fetch_ytdlp(self, video_id: str) -> list[dict]:
        """Sync-блок (executor). D154: ignoreerrors=True — фейл языка НЕ роняет
        extract_info (warning + переход к следующему языку); упавший язык
        остаётся в requested_subtitles БЕЗ filepath; extract_info может вернуть
        None вместо raise → info None = транзиентный фейл yt-dlp-уровня."""
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
            if info is None:                     # D154: ignoreerrors-семантика
                raise YouTubeTranscriptUnavailableException(
                    f"yt-dlp: extract_info returned None | video_id={video_id!r}"
                )
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
            "ignoreerrors": True,      # R41-1/D154: 429 на 'en' не валит ru
        }
        # D301 (Epic 84): player_client = "web" — требует PO Token (POT)
        # через bgutil-ytdlp-pot-provider (docker :4416). web_safari/tv_downgraded
        # НЕ поддерживают POT → bot-check «Sign in to confirm»/«The page needs
        # to be reloaded». "web" + POT + resident proxy работает без cookies.
        # bgutil-ytdlp-pot-provider остаётся plugin auto-load.
        # D301 (Epic 84): player_client = "web" — требует PO Token (POT)
        # через bgutil-ytdlp-pot-provider (docker :4416). web_safari/tv_downgraded
        # НЕ поддерживают POT → bot-check «Sign in to confirm»/«The page needs
        # to be reloaded». "web" + POT + resident proxy работает без cookies.
        # bgutil-ytdlp-pot-provider остаётся plugin auto-load.
        # Важно: "web" client НЕ возвращает downloadable formats (SABR forcing),
        # поэтому extract_info() с process=True падает с "Requested format is
        # not available". Используем process=False + ручной парсинг subtitles.
        opts["extractor_args"] = {
            "youtube": {"player_client": ["web"]}
        }
        # Epic 72 (74.A/D270): прокси/cookies (+POT-провайдер, если задан
        # YTDLP_POT_PROVIDER) — единый хелпер config.settings
        opts.update(build_ytdlp_base_opts())
        # Прод-хотфикс: base может нести extractor_args (pot_provider) —
        # МЕРЖИМ в наш player_client (иначе player_client=web перекроется).
        base_ea = opts.get("extractor_args") or {}
        youtube_ea = dict(base_ea.get("youtube") or {})
        youtube_ea["player_client"] = ["web"]
        opts["extractor_args"] = {"youtube": youtube_ea}
        return opts

    def _extract_ytdlp_segments(self, info: dict, video_id: str) -> list[dict]:
        """R41-1/D154 (ru-first): итерация ("ru","en") ПО requested_subtitles
        (порядок subtitleslangs сохраняется, ru первым; manual-preferred внутри
        языка — process_subtitles, 48.1). Язык БЕЗ filepath пропускается
        (артефакт ignoreerrors — 429 на 'en' при скачанном ru больше не валит
        запрос); исключение чтения файла языка → continue на следующий язык.
        Raise: «no readable subtitle files» — если filepath НЕТ ни у одного
        языка (ПЕРМАНЕНТ, D155 — идём в фолбек без ретраев); иначе — последнее
        исключение чтения (напр. «empty transcript» → транзиент)."""
        requested = info.get("requested_subtitles") or {}
        last_exc: BaseException | None = None
        any_filepath = False
        for lang in _YTDLP_SUBTITLE_LANGS:
            sub = requested.get(lang)
            if not sub:
                continue
            if not (sub.get("filepath") and os.path.exists(sub["filepath"])):
                continue                    # ignoreerrors-артефакт: язык упал
            any_filepath = True
            try:
                return self._read_ytdlp_subtitle(sub, video_id)
            except Exception as exc:
                last_exc = exc
                continue                    # следующий язык (en) может быть читаем
        if not any_filepath:
            raise YouTubeTranscriptUnavailableException(
                f"yt-dlp: no readable subtitle files | video_id={video_id!r}"
            )
        raise last_exc

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

    def _transcript_proxy_config(self):
        """Epic 84 (D320): proxy_config для YouTubeTranscriptApi 1.2.x.
        GenericProxyConfig с URL-embedded auth (http://user:pass@host:port).
        Приоритет: (1) username+password+domain+port → generic с auth,
        (2) domain+port → generic без auth, (3) webshare locations → None.
        Пусто → None (без прокси). R17: значения НЕ логируются."""
        username = (hot.get("keys.youtube_transcript_proxy_username", settings.YOUTUBE_TRANSCRIPT_PROXY_USERNAME) or "").strip()
        password = (hot.get("keys.youtube_transcript_proxy_password", settings.YOUTUBE_TRANSCRIPT_PROXY_PASSWORD) or "").strip()
        domain = (hot.get("keys.youtube_transcript_proxy_domain", settings.YOUTUBE_TRANSCRIPT_PROXY_DOMAIN) or "").strip()
        port = (hot.get("keys.youtube_transcript_proxy_port", settings.YOUTUBE_TRANSCRIPT_PROXY_PORT) or "").strip()

        if domain and port:
            proxy_url = f"http://{domain}:{port}"
            if username and password:
                proxy_url = f"http://{username}:{password}@{domain}:{port}"
            try:
                return GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)
            except Exception as exc:
                # N5 (R17): НЕ logger.exception — raw traceback может нести
                # proxy_url с user:pass; только sanitize-строка, без exc_info.
                from services.log_ring import sanitize as _sanitize_log
                logger.error(
                    "[youtube engine] failed to create GenericProxyConfig "
                    "| exc=%s", _sanitize_log(str(exc))[:200])
                return None

        return None  # без прокси

    def _fetch_segments(self, video_id: str) -> list[dict]:
        """Epic 84 (D319): YouTubeTranscriptApi 1.2.x — instance с proxy_config,
        .list(video_id), .find_transcript(), .fetch().to_raw_data().
        _pick_transcript() без изменений (TranscriptList 1.2.x сохраняет
        find_generated_transcript/find_manually_created_transcript)."""
        if YouTubeTranscriptApi is None:  # pragma: no cover
            raise YouTubeTranscriptUnavailableException(
                "youtube-transcript-api is not installed"
            )
        try:
            proxy_cfg = self._transcript_proxy_config()
            api = YouTubeTranscriptApi(proxy_config=proxy_cfg) if proxy_cfg \
                else YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
        except Exception as exc:
            # D319: RequestBlocked/IpBlocked → TRANSIENT, AgeRestricted → PERMANENT
            exc_name = type(exc).__name__
            if exc_name in ("RequestBlocked", "IpBlocked"):
                raise YouTubeTranscriptUnavailableException(
                    f"list failed (TRANSIENT) | video_id={video_id!r} ({exc})"
                ) from exc
            if exc_name == "AgeRestricted":
                raise YouTubeTranscriptUnavailableException(
                    f"list failed (PERMANENT) | video_id={video_id!r} ({exc})"
                ) from exc
            raise YouTubeTranscriptUnavailableException(
                f"list failed | video_id={video_id!r} ({exc})"
            ) from exc
        transcript = self._pick_transcript(transcript_list, video_id)
        try:
            fetched = transcript.fetch()
            return fetched.to_raw_data()
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

    # ── Классификация и диагностика (R41-2/R41-3, D155/D157) ──

    @staticmethod
    def _root_cause(exc: BaseException) -> BaseException:
        while exc.__cause__ is not None:
            exc = exc.__cause__
        return exc

    @staticmethod
    def _is_transient(exc: BaseException | None) -> bool:
        """D155: таблица 50.2, по корневой причине (unwrap __cause__ — обёртки
        YouTubeTranscriptUnavailableException из _fetch_segments сохраняют
        исходник в __cause__). Дефолт — PERMANENT (строго)."""
        if exc is None:
            return False
        root = YouTubeTranscriptEngine._root_cause(exc)
        text = str(root)
        text_l = text.lower()
        name = type(root).__name__
        if "is not installed" in text:                       # ImportError-гарды
            return False
        if "extract_info returned none" in text_l:           # D154
            return True
        if ("no readable subtitle files" in text
                or "no ru/en subtitles" in text):            # ignoreerrors-артефакт
            return False
        if ("video unavailable" in text_l
                or "video is not available" in text_l
                or name == "VideoUnavailable"):
            return False
        if "sign in to confirm you're not a bot" in text_l:
            return True
        if name in ("TooManyRequests", "FailedToCreateConsentCookie",
                    "JSONDecodeError"):
            return True
        if name == "ParseError":
            return "no element found" in text_l
        if name == "YouTubeRequestFailed":
            return ("http error" in text_l) or ("timed out" in text_l)
        if "empty transcript" in text_l:
            return True
        if name == "HTTPError":                              # ДО TransportError!
            status = getattr(root, "status", None)
            if status is None:
                m = re.search(r"HTTP Error (\d{3})", text)
                status = int(m.group(1)) if m else None
            return status in _RETRY_HTTP_STATUSES if status is not None else False
        if name in ("TransportError", "ProxyError"):
            return True
        if name == "DownloadError":
            return "http error" in text_l
        if name in ("TranscriptsDisabled", "NoTranscriptAvailable",
                    "NoTranscriptFound", "InvalidVideoId"):
            return False
        if "timed out" in text_l or isinstance(root, TimeoutError):
            return True
        return False                                         # дефолт: PERMANENT

    @staticmethod
    def _exc_status(exc: BaseException | None) -> str:
        r"""D157: HTTP-статус из корневой причины: HTTPError.status → регэксп
        «HTTP Error (\d{3})» (DownloadError/YouTubeRequestFailed-тексты) → «-»."""
        if exc is None:
            return "-"
        root = YouTubeTranscriptEngine._root_cause(exc)
        status = getattr(root, "status", None)
        if status is not None:
            return str(status)
        m = re.search(r"HTTP Error (\d{3})", str(root))
        return m.group(1) if m else "-"

    @staticmethod
    def _exc_body_bytes(exc: BaseException | None) -> str:
        """D157: размер тела из корневой причины: exc.response — bytes/bytearray
        → len; http.client.HTTPResponse — атрибут length; иначе «-»."""
        if exc is None:
            return "-"
        root = YouTubeTranscriptEngine._root_cause(exc)
        resp = getattr(root, "response", None)
        if isinstance(resp, (bytes, bytearray)):
            return str(len(resp))
        if hasattr(resp, "length") and resp.length is not None:
            return str(resp.length)
        return "-"
