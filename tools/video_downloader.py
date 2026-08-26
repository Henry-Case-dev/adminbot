"""Epic 66 (D261/D263): pre-flight yt-dlp → выбор качества → Cobalt → файл.

Глобальный asyncio.Lock уровня сервиса: одновременно ОДНО скачивание на весь
процесс (Section 70.4). Лок занят → немедленный признак busy БЕЗ ожидания.
yt-dlp-метаданные (probe) вне лока. Cleanup файла — на стороне хендлера в
finally; сервис отдаёт Path и не владеет жизненным циклом после возврата.
"""
import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import aiohttp

from config.settings import build_ytdlp_base_opts

logger = logging.getLogger(__name__)

# Section 70.4: таймауты (yt-dlp синхронный — to_thread + wait_for).
_PROBE_TIMEOUT_SECONDS = 20.0
_COBALT_POST_TIMEOUT = aiohttp.ClientTimeout(total=25, connect=10, sock_read=15)
_STREAM_TIMEOUT = aiohttp.ClientTimeout(total=300)

# Допустимые высоты (DESC); пересечение с найденными у источника.
_ALLOWED_HEIGHTS: tuple[int, ...] = (2160, 1440, 1080, 720, 480, 360)
_FALLBACK_QUALITIES: tuple[str, ...] = ("1080p", "720p", "360p")

# Section 70.8 #6: лимит локального Bot API (2 GB).
VD_MAX_BYTES = 2_000_000_000

# Epic 74 (D282): жёсткий лимит чтения ТЕЛА ошибки cobalt — тело приходит
# по сети, его размер заранее неизвестен (нельзя resp.text() без потолка).
_ERROR_BODY_MAX_BYTES = 1024

# Section 77 (D283): пауза перед единственным ретраем empty-body
# (cobalt #1428: транзиентный бан IP googlevideo, ~минуты).
_EMPTY_BODY_RETRY_DELAY_SECONDS = 4.0

_FILENAME_SANITIZE_RE = re.compile(r"[^\w.\- ]+")


class DownloadError(Exception):
    """Общая ошибка скачивания (yt-dlp/Cobalt/стрим) — пул VD_ERROR_PHRASES."""


class DownloadBusyError(DownloadError):
    """Лок занят другим скачиванием — пул VD_BUSY_PHRASES."""


class DownloadTooBigError(DownloadError):
    """Файл жирнее лимита телеги — пул VD_TOO_BIG_PHRASES."""


class CobaltServiceDownError(DownloadError):
    """Cobalt недоступен (ConnectError) — пул VD_SERVICE_DOWN_PHRASES."""


@dataclass(frozen=True)
class ProbeResult:
    title: str
    qualities: tuple[str, ...]          # «360p»…«2160p», DESC


def unique_qualities(formats) -> tuple[str, ...]:
    """Уникальные видео-разрешения из yt-dlp formats (70.4 п.2).

    Форматы только с vcodec != 'none'; дедуп height; сортировка DESC;
    пересечение с _ALLOWED_HEIGHTS. Пусто → fallback [1080p, 720p, 360p].
    """
    heights: set[int] = set()
    for fmt in formats or []:
        if not isinstance(fmt, dict):
            continue
        vcodec = fmt.get("vcodec")
        height = fmt.get("height")
        if vcodec in (None, "none") or not isinstance(height, int):
            continue
        heights.add(height)
    found = [h for h in _ALLOWED_HEIGHTS if h in heights]
    if not found:
        return _FALLBACK_QUALITIES
    return tuple(f"{h}p" for h in found)


class VideoDownloader:
    """Epic 66 (D261): pre-flight yt-dlp → выбор качества → Cobalt → файл."""

    def __init__(self, cobalt_url: str, download_dir: str):
        self._cobalt_url = cobalt_url.rstrip("/")
        self._download_dir = Path(download_dir)
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        """True = идёт скачивание (одновременных операций НЕ бывает)."""
        return self._lock.locked()

    async def probe(self, url: str) -> ProbeResult:
        """Метаданные yt-dlp: title + список качеств. Вне глобального лока.
        Epic 72 (74.A/D270): прокси/cookies — единый build_ytdlp_base_opts()
        (фикс прод-бага «Sign in to confirm you're not a bot» на probe)."""
        from yt_dlp import YoutubeDL              # ленивый тяжёлый импорт (D261)

        base = build_ytdlp_base_opts()
        if base.get("proxy"):                     # R17: только факт, НЕ значение
            logger.info("[videodl] probe | proxy=set")

        def _extract() -> dict:
            ydl = YoutubeDL({**base, "quiet": True, "noplaylist": True})
            return ydl.extract_info(url, download=False)

        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(_extract), timeout=_PROBE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise DownloadError(f"probe timeout: {url}") from exc
        except Exception as exc:
            raise DownloadError(f"probe failed: {exc}") from exc
        if not isinstance(info, dict):
            raise DownloadError("probe returned no info")
        title = info.get("title") or url
        qualities = unique_qualities(info.get("formats"))
        logger.info("[videodl] probed | qualities=%s", qualities)   # title/url НЕ логируем целиком
        return ProbeResult(title=str(title), qualities=qualities)

    async def download(self, url: str, quality: str) -> Path:
        """Скачивание под ГЛОБАЛЬНЫМ локом. Занят → DownloadBusyError сразу."""
        if self._lock.locked():
            raise DownloadBusyError("another download is running")
        async with self._lock:
            self._download_dir.mkdir(parents=True, exist_ok=True)
            tunnel_url, filename = await self._request_tunnel(url, quality)
            return await self._stream_to_file(tunnel_url, filename)

    async def _request_tunnel(self, url: str, quality: str) -> tuple[str, str | None]:
        """POST на Cobalt: {url, videoQuality, downloadMode:'auto'} → tunnel URL.
        Epic 74 (D280): качество нормализуется к enum БЕЗ «p» («1080p»→«1080»,
        int → str, «max» как есть; мусор → DownloadError до похода в сеть).
        D281: обязателен Accept: application/json. D282: тело ответа при
        >=400 читается, error.code из JSON извлекается и логируется."""
        quality_norm = self._normalize_quality(quality)
        payload = {"url": url, "videoQuality": quality_norm,
                   "downloadMode": "auto"}
        try:
            async with aiohttp.ClientSession(timeout=_COBALT_POST_TIMEOUT) as session:
                async with session.post(
                        self._cobalt_url, json=payload,
                        headers={"Accept": "application/json"}) as resp:
                    if resp.status >= 400:
                        raise await self._http_error(resp)
                    data = await resp.json(content_type=None)
        except aiohttp.ClientConnectorError as exc:
            raise CobaltServiceDownError(f"cobalt unreachable: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise DownloadError("cobalt request timeout") from exc
        except aiohttp.ClientError as exc:
            raise DownloadError(f"cobalt transport error: {exc}") from exc
        if not isinstance(data, dict) or data.get("error"):
            reason = data.get("error", {"code": "unknown"}) if isinstance(data, dict) else "non-json"
            raise DownloadError(f"cobalt error: {reason}")
        status = data.get("status")
        tunnel = data.get("url")
        if status not in ("tunnel", "redirect") or not tunnel:
            # local-processing и прочие статусы не поддерживаем (70.4 п.3)
            raise DownloadError(f"unsupported cobalt status: {status!r}")
        filename = data.get("filename") if isinstance(data.get("filename"), str) else None
        return str(tunnel), filename

    @staticmethod
    def _normalize_quality(quality) -> str:
        """Epic 74 (D280): «1080p»/«1080»/1080 → «1080»; «max» как есть;
        мусор → DownloadError БЕЗ похода в сеть."""
        raw = str(quality)
        text = raw.strip()
        if text.lower() == "max":
            return "max"
        try:
            return str(int(text.strip("pP")))
        except ValueError:
            raise DownloadError(f"invalid quality: {raw!r}") from None

    @staticmethod
    async def _http_error(resp) -> DownloadError:
        """Epic 74 (D282): тело ответа при >=400 читается С ЖЁСТКИМ ЛИМИТОМ
        (_ERROR_BODY_MAX_BYTES — тело сетевое, размер неизвестен; срез
        сообщения [:500]), error.code из JSON извлекается, логируется и
        включается в текст ошибки. Если тело нечитаемо (обрыв соединения при
        чтении) — голый статус без тела, диагностика не теряется."""
        try:
            raw = await resp.content.read(_ERROR_BODY_MAX_BYTES)
            body_full = raw.decode("utf-8", errors="replace")
        except Exception as exc:  # обрыв чтения тела — статус всё равно важен
            logger.error("[videodl] cobalt http %s | body unreadable: %s",
                         resp.status, exc)
            return DownloadError(f"cobalt http {resp.status}")
        error_code = None
        try:
            parsed = json.loads(body_full)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
                error_code = parsed["error"].get("code")
        except ValueError:
            pass
        body = body_full[:500]
        logger.error("[videodl] cobalt http %s | code=%s | body=%s",
                     resp.status, error_code or "-", body)
        detail = error_code if error_code else body
        return DownloadError(f"cobalt http {resp.status}: {detail}")

    async def _stream_to_file(self, tunnel_url: str,
                              filename: str | None) -> Path:
        """Стрим tunnel-URL во временный файл DOWNLOAD_DIR → rename.
        Section 77 (D283): при статусе <400 и 0 записанных байтах — ровно
        ОДНА повторная попытка того же URL после паузы 4с; обе пустые →
        DownloadError("empty body from tunnel (after retry)"). http >=400
        и сетевые ошибки — без ретрая (семантика прежняя). Каждая попытка —
        свой ClientSession(timeout=_STREAM_TIMEOUT), таймаут на одну попытку.
        D284: при written==0 — WARNING-диагностика БЕЗ полного URL."""
        stamp = int(time.time())
        rand = secrets.token_hex(4)
        tmp_path = self._download_dir / f"vd_{stamp}_{rand}.mp4"
        try:
            written, meta = await self._stream_attempt(tunnel_url, tmp_path)
            if written == 0:
                self._log_empty_body(tunnel_url, attempt=1, meta=meta)
                await asyncio.sleep(_EMPTY_BODY_RETRY_DELAY_SECONDS)
                written, meta = await self._stream_attempt(tunnel_url,
                                                           tmp_path)
                if written == 0:
                    self._log_empty_body(tunnel_url, attempt=2, meta=meta)
                    raise DownloadError(
                        "empty body from tunnel (after retry)")
            final_path = self._finalize_name(tmp_path, filename)
            tmp_path.rename(final_path)
            logger.info("[videodl] downloaded | bytes=%d", written)
            return final_path
        finally:
            # rename не удался / исключение до rename → временный файл не копим
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    async def _stream_attempt(self, tunnel_url: str,
                              tmp_path: Path) -> tuple[int, dict]:
        """Одна попытка GET tunnel URL → стрим в tmp_path (truncate "wb").
        Возвращает (written, метаданные для D284-диагностики)."""
        try:
            async with aiohttp.ClientSession(timeout=_STREAM_TIMEOUT) as session:
                async with session.get(tunnel_url) as resp:
                    if resp.status >= 400:
                        raise DownloadError(f"tunnel http {resp.status}")
                    headers = resp.headers
                    written = 0
                    with open(tmp_path, "wb") as fh:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            written += len(chunk)
                            if written > VD_MAX_BYTES:
                                raise DownloadTooBigError(
                                    f"file exceeds {VD_MAX_BYTES} bytes")
                            fh.write(chunk)
                    return written, {
                        "http_status": resp.status,
                        "content_length": headers.get("Content-Length"),
                        "estimated_content_length":
                            headers.get("Estimated-Content-Length"),
                        "content_type": headers.get("Content-Type"),
                    }
        except aiohttp.ClientConnectorError as exc:
            raise CobaltServiceDownError(f"tunnel unreachable: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise DownloadError("stream timeout") from exc
        except aiohttp.ClientError as exc:
            raise DownloadError(f"stream transport error: {exc}") from exc

    @staticmethod
    def _log_empty_body(tunnel_url: str, attempt: int, meta: dict) -> None:
        """Section 77 (D284): диагностика written==0. Полный tunnel URL НЕ
        логируем (подпись в query) — только первые 8 символов query-param
        id (gv_id); CL/ECL отличают «обещал N, отдал 0» от «честно 0»."""
        gv_id = parse_qs(urlsplit(tunnel_url).query).get("id", [""])[0][:8]
        logger.warning(
            "[videodl] tunnel empty body | attempt=%d | http_status=%d | "
            "content_length=%s | estimated_content_length=%s | "
            "content_type=%s | bytes_written=0 | gv_id=%s",
            attempt, meta["http_status"], meta["content_length"],
            meta["estimated_content_length"], meta["content_type"], gv_id)

    @staticmethod
    def _finalize_name(tmp_path: Path, filename: str | None) -> Path:
        if not filename:
            return tmp_path
        safe = _FILENAME_SANITIZE_RE.sub("_", filename.strip())[:120]
        suffix = tmp_path.suffix or ".mp4"
        if not safe:
            return tmp_path
        if not safe.endswith(suffix):
            safe = f"{safe}{suffix}"
        return tmp_path.with_name(safe)
