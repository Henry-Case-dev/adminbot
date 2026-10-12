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

ASAP 8 F9 (§16 ТЗ, architecture §9) — прокси-классификация + единый профиль:

1. Retry-матрица (классификация по КОРНЕВОЙ причине, unwrap __cause__;
   «retry» = каскадный ретрай с backoff _RETRY_BACKOFFS, ≤ _MAX_CASCADE_RETRIES
   = 4 ретрая = 5 попыток; специфичный парс — ДО generic-классов):

   | сигнал (по корневой причине)                                      | failure_class     | retry |
   |-------------------------------------------------------------------|-------------------|-------|
   | HTTP 407 / «Proxy Authentication Required» (вкл. yt-dlp           | proxy_auth_failed | НЕТ   |
   |   DownloadError «HTTP Error 407» — парсится ДО generic            |                   |       |
   |   «http error»-чека; ProxyError с маркером 407)                   |                   |       |
   | HTTP 403                                                          | forbidden         | НЕТ   |
   | HTTP 429 / TooManyRequests                                        | rate_limited      | ДА   |
   | timeout / «timed out» / TimeoutError                              | timeout           | ДА   |
   | «connection reset» / «reset by peer»                              | reset             | ДА   |
   | ProxyError / TransportError (НЕ 407), прокси недоступен           | proxy_unavailable | ДА   |
   | HTTP 500/502/503/504                                              | server_error      | ДА   |
   | прочие известные транзиентные паттерны (bot-check, empty          | transient         | ДА   |
   |   transcript, extract_info=None, JSONDecodeError,                 |                   |       |
   |   ParseError(no element), FailedToCreateConsentCookie)            |                   |       |
   | прочее / неизвестное                                              | permanent         | НЕТ   |

   Дефолт — PERMANENT (строго). proxy_auth_failed перманентен ДЛЯ ЗАПРОСА:
   407 на ЛЮБОМ движке останавливает каскад (transient-фейл второго движка
   не делает 407 ретраебельным) и логируется РОВНО ОДИН WARN на запрос.

2. Единый effective proxy profile (Y4): effective_proxy_profile() — ОДИН
   резолвер для yt-dlp opts["proxy"] И transcript-api proxy_config.
   Приоритет: (1) YOUTUBE_CREDENTIALED_LEVEL_ENABLED=False → прокси нет
   (оба пути); (2) resident-поля username/password + domain+port (hot → env)
   → http://[user:pass@]domain:port — оба пути; (3) URL hot
   keys.youtube_transcript_proxy_url → env YOUTUBE_TRANSCRIPT_PROXY_URL —
   оба пути (до F9 URL получал только yt-dlp — рассинхрон движков);
   (4) ничего → egress-guard (MCA-02) применяется движками по-старому.
   R17: proxy_url (может нести user:pass) НИКОГДА не логируется и не
   возвращается наружу — только endpoint_masked (host:port замаскирован).

3. Proxy health (Y4/Y5, §16 «MiniApp connection test»): run_proxy_health_check()
   — auth-проба через прокси + реальный yt-dlp путь + transcript-api путь;
   в ответе только замаскированный endpoint, коды классов и HTTP-статусы —
   секреты (логин/пароль/полный URL прокси) НИКОГДА.
"""
import asyncio
from services import hot_config as hot
import datetime
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from typing import Awaitable, Callable

from config.settings import build_ytdlp_base_opts, settings
from services import safe_fetch

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
# D155 + F9: транзиентные HTTP-статусы (403 УДАЛЁН — forbidden, БЕЗ retry;
# 407 здесь и не был — парсится ДО generic-класса, см. матрицу в докстринге).
_RETRY_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
# F9: классы, допускающие каскадный ретрай (см. таблицу в докстринге модуля).
_TRANSIENT_FAILURE_CLASSES = frozenset({
    "transient", "rate_limited", "timeout", "reset", "proxy_unavailable",
    "server_error",
})
_PROXY_AUTH_MARKER = "proxy authentication required"   # F9: маркер 407-ответа прокси
_RESET_MARKERS = ("connection reset", "reset by peer")  # F9: transient-reset

# ── F9: proxy health (§16 connection test; Y4/Y5) ───────────────────────────
_PROXY_HEALTH_PROBE_VIDEO = "dQw4w9WgXcQ"   # публичное видео с субтитрами (проба путей)
_PROXY_HEALTH_HTTP_TIMEOUT = 15.0           # граница auth-пробы (сек)
_PROXY_HEALTH_LAST: dict | None = None      # последний результат (per-process)
_PROXY_HEALTH_LOCK = threading.Lock()       # singleflight живой проверки


def _safe_exc_text(exc: BaseException | None) -> str:
    """R17/Y5: текст исключения для ЛОГОВ/сообщений через sanitize
    (log_ring._URI_CREDS_RE маскирует user:pass в URL прокси). Никогда
    не бросает; None → «-»."""
    if exc is None:
        return "-"
    try:
        from services.log_ring import sanitize as _sanitize_log
        return _sanitize_log(str(exc))[:500]
    except Exception:      # pragma: no cover — лог не должен ронять каскад
        return "<exc>"


def mask_proxy_endpoint(url: str | None) -> str | None:
    """F9/Y5: host:port из proxy-URL с ЗАМАСКИРОВАННЫМ хостом (первый+последний
    фрагменты). Секреты (user:pass) и полный хост никогда не попадают в UI/логи.
    Никогда не бросает; неразбираемый URL → None (честное «нет данных»)."""
    if not url:
        return None
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").strip()
        if not host:
            return None
        if len(host) > 6:
            masked = f"{host[:2]}\u2026{host[-2:]}"
        else:
            masked = f"{host[:1]}\u2026"
        port = parts.port
        return f"{masked}:{port}" if port else masked
    except Exception:      # pragma: no cover — маскировка не должна ронять
        return None


def effective_proxy_profile() -> dict:
    """F9/Y4: ЕДИНЫЙ effective proxy profile для ОБОИХ путей (yt-dlp opts и
    transcript-api proxy_config) — один резолвер, один приоритет (см. таблицу
    в докстринге модуля). Возвращает:

      configured       — явный YouTube-прокси настроен (resident-поля ИЛИ URL);
      source           — "webshare" | "url" | "none";
      proxy_url        — СЕКРЕТ (может нести user:pass): только для конфигов
                         движков; НИКОГДА не логировать/не отдавать наружу;
      endpoint_masked  — host:port с замаскированным хостом (для UI/логов);
      auth_configured  — заданы username+password (паритет resproxy в __init__).
    """
    if not getattr(settings, "YOUTUBE_CREDENTIALED_LEVEL_ENABLED", True):
        return {"configured": False, "source": "none", "proxy_url": None,
                "endpoint_masked": None, "auth_configured": False}
    username = (hot.get("keys.youtube_transcript_proxy_username", settings.YOUTUBE_TRANSCRIPT_PROXY_USERNAME) or "").strip()
    password = (hot.get("keys.youtube_transcript_proxy_password", settings.YOUTUBE_TRANSCRIPT_PROXY_PASSWORD) or "").strip()
    domain = (hot.get("limits.youtube_transcript_proxy_domain", settings.YOUTUBE_TRANSCRIPT_PROXY_DOMAIN) or "").strip()
    port = (hot.get("limits.youtube_transcript_proxy_port", settings.YOUTUBE_TRANSCRIPT_PROXY_PORT) or "").strip()
    has_auth = bool(username and password)
    if domain and port:                     # приоритет 2: resident-поля
        proxy_url = f"http://{domain}:{port}"
        if has_auth:
            proxy_url = f"http://{username}:{password}@{domain}:{port}"
        return {"configured": True, "source": "webshare", "proxy_url": proxy_url,
                "endpoint_masked": mask_proxy_endpoint(proxy_url),
                "auth_configured": has_auth}
    url = (hot.get("keys.youtube_transcript_proxy_url", settings.YOUTUBE_TRANSCRIPT_PROXY_URL) or "").strip()
    if url:                                 # приоритет 3: URL (hot → env) — оба пути
        return {"configured": True, "source": "url", "proxy_url": url,
                "endpoint_masked": mask_proxy_endpoint(url),
                "auth_configured": has_auth}
    return {"configured": False, "source": "none", "proxy_url": None,
            "endpoint_masked": None, "auth_configured": has_auth}


class YouTubeTranscriptUnavailableException(Exception):
    """Транскрипт недоступен (ОБА движка упали): нет субтитров / приватность /
    видео удалено / 429 / сетевой сбой. → пул 5.6 (YOUTUBE_ERROR_PHRASES).

    Раунд 10.24 (F16, ADR-1024-17 §Решение п.5): необязательный `reason`
    (позиционный `message` сохранён) — машинная причина, по которой хендлер
    выбирает пул фраз. Значения: ``"age_restricted"`` | ``"proxy_auth_failed"``
    (F9/Y1) | ``"transient"`` | ``"unavailable"`` (default —
    ``"unavailable"``). Хендлер unknown-reason безопасно деградирует в общий
    пул фраз."""

    def __init__(self, message: str, *, reason: str = "unavailable") -> None:
        super().__init__(message)
        self.reason = reason


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
        """D151/D152/D156 + F9: попытка = ВЕСЬ каскад (yt-dlp → transcript-api).
        Фейл попытки классифицируется гранулярно (_failure_class, матрица в
        докстринге модуля): transient-классы → on_retry(attempt,
        _MAX_CASCADE_RETRIES) → sleep(backoff) → повтор (максимум
        _MAX_CASCADE_RETRIES ретраев); proxy_auth_failed (407) перманентен
        ДЛЯ ЗАПРОСА — каскад останавливается с РОВНО ОДНИМ WARN (Y1);
        перманентный фейл → немедленный raise (0 ретраев). on_retry=None —
        ретраи без уведомлений. R17/Y5: тексты исключений логируются только
        через sanitize (могут нести proxy URL с user:pass)."""
        # MCA-02 (ADR-1027-5 D4): поднять loopback egress-guard (медиа-подпроцесс
        # и transcript-api ходят через него; OFF → legacy).
        try:
            await safe_fetch.ensure_egress_guard()
        except Exception:      # fail-open: guard не должен рвать транскрипцию
            logger.warning("[youtube engine] egress guard unavailable",
                           exc_info=True)
        ytdlp_exc: BaseException | None = None
        api_exc: BaseException | None = None
        proxy_auth_warned = False                # F9: WARN 1/request (Y1)
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
                    video_id, _safe_exc_text(exc),
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
                    video_id, _safe_exc_text(exc),
                    self._exc_status(exc), self._exc_body_bytes(exc),
                )
            ytdlp_class = self._failure_class(ytdlp_exc)
            api_class = self._failure_class(api_exc)
            # F9/Y1 (§28.20/§28.21): 407 (proxy_auth_failed) перманентен ДЛЯ
            # ЗАПРОСА — transient-фейл второго движка не делает его
            # ретраебельным (прежде OR-правило давало retry storm 1/2/4/8с).
            if "proxy_auth_failed" in (ytdlp_class, api_class):
                if not proxy_auth_warned:      # РОВНО ОДИН WARN на запрос (§26)
                    logger.warning(
                        "[youtube engine] proxy auth failed (407) — permanent "
                        "for this request, no retry | video_id=%r | "
                        "ytdlp=%s | transcript_api=%s",
                        video_id, ytdlp_class, api_class,
                    )
                    proxy_auth_warned = True
                break
            transient = (
                ytdlp_class in _TRANSIENT_FAILURE_CLASSES
                or api_class in _TRANSIENT_FAILURE_CLASSES
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
            f"(yt-dlp: {_safe_exc_text(ytdlp_exc)} "
            f"[status={self._exc_status(ytdlp_exc)}, "
            f"body_bytes={self._exc_body_bytes(ytdlp_exc)}]; "
            f"transcript-api: {_safe_exc_text(api_exc)} "
            f"[status={self._exc_status(api_exc)}, "
            f"body_bytes={self._exc_body_bytes(api_exc)}])",
            reason=self._classify_reason(ytdlp_exc, api_exc),
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
        # F9/Y4: ЕДИНЫЙ effective proxy profile — hot-оверрайды (прежде
        # игравшие только в логе presence) и resident-поля применяются и к
        # yt-dlp; env-URL из base перезаписывается профилем (один резолвер на
        # оба движка). R17: proxy_url НИКОГДА не логируется.
        profile = effective_proxy_profile()
        if profile["configured"] and profile["proxy_url"]:
            opts["proxy"] = profile["proxy_url"]
        # Прод-хотфикс: base может нести extractor_args (pot_provider) —
        # МЕРЖИМ в наш player_client (иначе player_client=web перекроется).
        base_ea = opts.get("extractor_args") or {}
        youtube_ea = dict(base_ea.get("youtube") or {})
        youtube_ea["player_client"] = ["web"]
        opts["extractor_args"] = {"youtube": youtube_ea}
        # MCA-02 (ADR-1027-5 D4): маршрутизировать yt-dlp через loopback
        # egress-guard (destination-политика на каждый CONNECT/redirect).
        safe_fetch.apply_egress_to_ytdlp_opts(opts)
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
        """F9/Y4: proxy_config из ЕДИНОГО effective_proxy_profile() —
        resident-поля (username/password/domain+port) ИЛИ URL (hot → env;
        до F9 URL получал только yt-dlp — рассинхрон движков). Ничего →
        egress-guard (MCA-02), иначе None. Credentialed-уровень OFF → None
        (как прежде, ДО guard). R17: значения НЕ логируются."""
        if not getattr(settings, "YOUTUBE_CREDENTIALED_LEVEL_ENABLED", True):
            return None
        profile = effective_proxy_profile()
        if profile["proxy_url"] and GenericProxyConfig is not None:
            try:
                return GenericProxyConfig(
                    http_url=profile["proxy_url"], https_url=profile["proxy_url"],
                )
            except Exception as exc:
                # N5 (R17): НЕ logger.exception — raw traceback может нести
                # proxy_url с user:pass; только sanitize-строка, без exc_info.
                from services.log_ring import sanitize as _sanitize_log
                logger.error(
                    "[youtube engine] failed to create GenericProxyConfig "
                    "| exc=%s", _sanitize_log(str(exc))[:200])
                return None

        # MCA-02 (ADR-1027-5 D4): без явного YouTube-прокси маршрутизируем
        # transcript-api через loopback egress-guard (destination-политика).
        guard = safe_fetch.egress_proxy_url()
        if guard and GenericProxyConfig is not None:
            try:
                return GenericProxyConfig(http_url=guard, https_url=guard)
            except Exception:      # pragma: no cover - защитная ветка
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
                    f"list failed (TRANSIENT) | video_id={video_id!r} ({exc})",
                    reason="transient",
                ) from exc
            if exc_name == "AgeRestricted":
                raise YouTubeTranscriptUnavailableException(
                    f"list failed (PERMANENT) | video_id={video_id!r} ({exc})",
                    reason="age_restricted",
                ) from exc
            raise YouTubeTranscriptUnavailableException(
                f"list failed | video_id={video_id!r} ({exc})",
                reason="unavailable",
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
    def _http_status_of(root: BaseException) -> int | None:
        r"""F9: HTTP-статус корневой причины: ``.status`` (int) → регэксп
        «HTTP Error (\d{3})». Не-целый .status игнорируется (fail-closed в
        регэксп-путь). Специфичный парс ДО generic-классов (матрица F9)."""
        status = getattr(root, "status", None)
        if isinstance(status, bool):         # bool — подкласс int; не статус
            status = None
        if isinstance(status, int):
            return status
        m = re.search(r"HTTP Error (\d{3})", str(root))
        return int(m.group(1)) if m else None

    @classmethod
    def _is_proxy_auth_failed(cls, exc: BaseException | None) -> bool:
        """F9/Y1: 407 / «Proxy Authentication Required» по корневой причине.
        Специфичный парс ДО generic http-error/ProxyError-классов; кроет
        urllib/requests ProxyError, yt-dlp DownloadError «HTTP Error 407» и
        обёртки transcript-api (__cause__)."""
        if exc is None:
            return False
        root = cls._root_cause(exc)
        if cls._http_status_of(root) == 407:
            return True
        return _PROXY_AUTH_MARKER in str(root).lower()

    @classmethod
    def _failure_class(cls, exc: BaseException | None) -> str:
        """F9: гранулярная классификация (матрица — в докстринге модуля).
        Порядок: специфичный парс (407/403) → известные классы → дефолт
        PERMANENT (строго). Возвращает failure_class, ретраебельность =
        ``класс in _TRANSIENT_FAILURE_CLASSES``."""
        if exc is None:
            return "none"
        root = cls._root_cause(exc)
        text = str(root)
        text_l = text.lower()
        name = type(root).__name__
        if "is not installed" in text:                       # ImportError-гарды
            return "permanent"
        # ── F9: специфичный парс ДО generic-классов ─────────────────────
        if cls._is_proxy_auth_failed(root):                  # 407 (Y1)
            return "proxy_auth_failed"
        if cls._http_status_of(root) == 403:                 # forbidden, без retry
            return "forbidden"
        if "extract_info returned none" in text_l:           # D154
            return "transient"
        if ("no readable subtitle files" in text
                or "no ru/en subtitles" in text):            # ignoreerrors-артефакт
            return "permanent"
        if ("video unavailable" in text_l
                or "video is not available" in text_l
                or name == "VideoUnavailable"):
            return "permanent"
        if "sign in to confirm you're not a bot" in text_l:
            return "transient"
        if name == "TooManyRequests":
            return "rate_limited"
        if name in ("FailedToCreateConsentCookie", "JSONDecodeError"):
            return "transient"
        if name == "ParseError":
            return "transient" if "no element found" in text_l else "permanent"
        if name == "YouTubeRequestFailed":
            if "timed out" in text_l:
                return "timeout"
            # http error: 407/403 уже перехвачены специфичным парсом выше —
            # здесь остаётся прежняя транзиентная семантика прочих http-фейлов.
            return "transient" if "http error" in text_l else "permanent"
        if "empty transcript" in text_l:
            return "transient"
        if name == "HTTPError":                              # ДО TransportError!
            status = cls._http_status_of(root)
            if status is None:
                return "permanent"
            if status == 429:
                return "rate_limited"
            if status in _RETRY_HTTP_STATUSES:               # 5xx (F9: без 403)
                return "server_error"
            return "permanent"
        if name in ("TransportError", "ProxyError"):
            return "proxy_unavailable"                       # не-407 → transient bounded
        if name == "DownloadError":
            if "http error" not in text_l:
                return "permanent"
            # Специфичный парс статуса ДО generic-решения (F9: «HTTP Error 407»
            # сюда больше не доходит — перехвачен выше как proxy_auth_failed).
            status = cls._http_status_of(root)
            if status == 429:
                return "rate_limited"
            if status in _RETRY_HTTP_STATUSES:
                return "server_error"
            return "permanent"
        if name in ("TranscriptsDisabled", "NoTranscriptAvailable",
                    "NoTranscriptFound", "InvalidVideoId"):
            return "permanent"
        if any(marker in text_l for marker in _RESET_MARKERS):
            return "reset"
        if "timed out" in text_l or isinstance(root, TimeoutError):
            return "timeout"
        return "permanent"                                   # дефолт: PERMANENT

    @classmethod
    def _is_transient(cls, exc: BaseException | None) -> bool:
        """D155 + F9: ретраебельность = ``_failure_class(exc) in
        _TRANSIENT_FAILURE_CLASSES``. Retry-матрица зафиксирована таблицей
        в докстринге модуля (единственный источник правды)."""
        return cls._failure_class(exc) in _TRANSIENT_FAILURE_CLASSES

    @staticmethod
    def _is_age_restricted(exc: BaseException | None) -> bool:
        """Раунд 10.24 (F16): age-restricted по корневой причине
        (класс AgeRestricted или текст «age-restricted»/«age restricted»).
        Приоритет выше transient (в логе прода age-restricted-фейл одного
        движка соседствовал с transient-фейлом другого)."""
        if exc is None:
            return False
        root = YouTubeTranscriptEngine._root_cause(exc)
        name = type(root).__name__
        text_l = str(root).lower()
        return (name == "AgeRestricted"
                or "age-restricted" in text_l
                or "age restricted" in text_l)

    @classmethod
    def _reason_of(cls, exc: BaseException | None) -> str | None:
        """Причина одного движка: явный `reason` обёртки (age/proxy_auth/
        transient), иначе структурная классификация. `None` — движок не падал.
        F9: proxy_auth_failed СТАРШЕ explicit "transient" (407 перманентен
        для запроса, даже если второй движок дал транзиентный фейл)."""
        if exc is None:
            return None
        explicit = getattr(exc, "reason", None)
        if explicit == "age_restricted" or cls._is_age_restricted(exc):
            return "age_restricted"
        if explicit == "proxy_auth_failed" or cls._is_proxy_auth_failed(exc):
            return "proxy_auth_failed"
        if explicit == "transient" or cls._is_transient(exc):
            return "transient"
        return "unavailable"

    @classmethod
    def _classify_reason(cls, ytdlp_exc: BaseException | None,
                         api_exc: BaseException | None) -> str:
        """Раунд 10.24 (F16, spec 4.3) + F9: приоритет age_restricted →
        proxy_auth_failed → transient → unavailable по обоим движкам.
        Значение уходит в `reason` итогового исключения (хендлер выбирает
        пул фраз; unknown-reason деградирует в общий пул безопасно)."""
        reasons = {cls._reason_of(ytdlp_exc), cls._reason_of(api_exc)}
        if "age_restricted" in reasons:
            return "age_restricted"
        if "proxy_auth_failed" in reasons:
            return "proxy_auth_failed"
        if "transient" in reasons:
            return "transient"
        return "unavailable"

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


# ── F9: proxy health — connection test (§16, Y4/Y5) ─────────────────────────

def _proxy_health_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _engine_failure_view(exc: BaseException) -> dict:
    """F9/Y5: безопасная проекция фейла движка для health-ответа: только
    failure_class, HTTP-статус и КЛАСС исключения (никогда str(exc) — он
    может нести proxy URL с user:pass)."""
    root = YouTubeTranscriptEngine._root_cause(exc)
    status = YouTubeTranscriptEngine._exc_status(exc)
    return {
        "status": "fail",
        "code": YouTubeTranscriptEngine._failure_class(exc),
        "http_status": status if status != "-" else None,
        "exc_type": type(root).__name__,
    }


def _proxy_auth_probe(proxy_url: str) -> dict:
    """F9/Y4: auth-проба прокси — GET https://www.youtube.com/generate_204
    ЧЕРЕЗ прокси (CONNECT). Интерпретация:
      * 407 от прокси / маркер «Proxy Authentication Required» → fail;
      * туннель установлен, ЛЮБОЙ ответ цели (вкл. 4xx/5xx от YouTube) → ok
        (auth принимает прокси, а не YouTube);
      * соединение не состоялось (refused/timeout/DNS) → unreachable.
    R17: тело ответа не читается, текст исключения наружу не идёт."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": proxy_url, "https": proxy_url}))
        req = urllib.request.Request(
            "https://www.youtube.com/generate_204",
            headers={"User-Agent": "adminbot-proxy-health/1.0"},
        )
        with opener.open(req, timeout=_PROXY_HEALTH_HTTP_TIMEOUT) as resp:
            return {"status": "ok", "http_status": int(resp.status),
                    "reason": None}
    except urllib.error.HTTPError as exc:
        if exc.code == 407:
            return {"status": "fail", "http_status": 407,
                    "reason": "proxy_auth_failed"}
        # Прокси пропустил к цели — auth ОК (код от самой YouTube).
        return {"status": "ok", "http_status": int(exc.code), "reason": None}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        cause_text = str(getattr(exc, "reason", None) or exc).lower()
        if _PROXY_AUTH_MARKER in cause_text or "407" in cause_text:
            return {"status": "fail", "http_status": None,
                    "reason": "proxy_auth_failed"}
        return {"status": "unreachable", "http_status": None,
                "reason": "proxy_unreachable"}


def proxy_health_snapshot() -> dict | None:
    """Последний результат run_proxy_health_check (без запуска новой пробы)."""
    return _PROXY_HEALTH_LAST


def run_proxy_health_check(*, video_id: str = _PROXY_HEALTH_PROBE_VIDEO) -> dict:
    """F9/Y4: connection test YouTube-прокси (owner-triggered, global-admin).

    Шаги (все через ЕДИНЫЙ effective_proxy_profile):
      1. auth — HTTP-проба через прокси (OK/FAIL/unreachable);
      2. ytdlp_path — РЕАЛЬНЫЙ движок-путь _fetch_ytdlp(video_id);
      3. transcript_api_path — list() через _transcript_proxy_config().

    Прокси не настроен → все шаги skipped (reason=no_proxy), честный снимок.
    Ответ содержит ТОЛЬКО endpoint_masked + коды классов/HTTP-статусы —
    секреты (логин/пароль/полный URL прокси) НИКОГДА (Y5). Результат
    кэшируется в _PROXY_HEALTH_LAST (GET /api/youtube/proxy/health)."""
    global _PROXY_HEALTH_LAST
    started = time.monotonic()
    profile = effective_proxy_profile()
    skipped = {"status": "skipped", "http_status": None, "reason": "no_proxy",
               "code": None}
    result: dict = {
        "configured": bool(profile["configured"] and profile["proxy_url"]),
        "source": profile["source"],
        "credentialed_enabled": bool(
            getattr(settings, "YOUTUBE_CREDENTIALED_LEVEL_ENABLED", True)),
        "endpoint": profile["endpoint_masked"],     # уже замаскирован (Y5)
        "auth_configured": bool(profile["auth_configured"]),
        "auth": dict(skipped),
        "ytdlp_path": dict(skipped),
        "transcript_api_path": dict(skipped),
        "checked_at": _proxy_health_now_iso(),
    }
    result["checked_at_ts"] = time.time()   # epoch-сек для UI fmtTs
    if result["configured"]:
        logger.info(
            "[youtube engine] proxy health check started | endpoint=%s | "
            "source=%s", profile["endpoint_masked"], profile["source"])
        result["auth"] = _proxy_auth_probe(profile["proxy_url"])
        engine = YouTubeTranscriptEngine()
        try:
            engine._fetch_ytdlp(video_id)
            result["ytdlp_path"] = {"status": "ok", "code": None,
                                    "http_status": None, "reason": None}
        except Exception as exc:                    # noqa: BLE001 — классифицируем
            result["ytdlp_path"] = _engine_failure_view(exc)
        try:
            proxy_cfg = engine._transcript_proxy_config()
            if YouTubeTranscriptApi is None:
                raise RuntimeError("youtube-transcript-api is not installed")
            api = (YouTubeTranscriptApi(proxy_config=proxy_cfg)
                   if proxy_cfg else YouTubeTranscriptApi())
            api.list(video_id)
            result["transcript_api_path"] = {"status": "ok", "code": None,
                                             "http_status": None,
                                             "reason": None}
        except Exception as exc:                    # noqa: BLE001 — классифицируем
            result["transcript_api_path"] = _engine_failure_view(exc)
        logger.info(
            "[youtube engine] proxy health check done | auth=%s | "
            "ytdlp=%s | transcript_api=%s",
            result["auth"]["status"], result["ytdlp_path"]["status"],
            result["transcript_api_path"]["status"])
    result["took_ms"] = int((time.monotonic() - started) * 1000)
    _PROXY_HEALTH_LAST = result
    return result


def run_proxy_health_check_locked(**kwargs) -> dict:
    """Singleflight: параллельный вызов НЕ плодит параллельных проб —
    возвращает последний результат с in_progress=true (честный ответ)."""
    if not _PROXY_HEALTH_LOCK.acquire(blocking=False):
        snap = dict(_PROXY_HEALTH_LAST) if _PROXY_HEALTH_LAST \
            else {"status": "never_run"}
        snap["in_progress"] = True
        return snap
    try:
        return run_proxy_health_check(**kwargs)
    finally:
        _PROXY_HEALTH_LOCK.release()
