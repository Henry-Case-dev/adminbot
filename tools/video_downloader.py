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
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import aiohttp
import httpx

from config.settings import build_ytdlp_base_opts, settings

logger = logging.getLogger(__name__)

# Прямые медиа-ссылки (замечание чекапа): расширение в конце URL (с учётом
# query) → не yt-dlp/cobalt, а прямой стрим.
_DIRECT_MEDIA_RE = re.compile(
    r"\.(mp4|webm|mov|mkv|avi|gif)(?:[?#]|$)", re.IGNORECASE)
# Браузерный UA + рефереры для ретрая 403 (2ch.su и др.).
_DIRECT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36")
_DIRECT_REFERRERS = ("https://2ch.su/",)
_DIRECT_MAX_BYTES = 2_000_000_000

# Section 70.4: таймауты (yt-dlp синхронный — to_thread + wait_for).
_PROBE_TIMEOUT_SECONDS = 20.0
_COBALT_POST_TIMEOUT = aiohttp.ClientTimeout(total=25, connect=10, sock_read=15)
_STREAM_TIMEOUT = aiohttp.ClientTimeout(total=300)

# Epic 77 (D287): таймаут yt-dlp-ветки скачивания (больше cobalt-ских
# 300с×2, т.к. сюда входит merge ffmpeg; бюджет один на всю операцию).
_YTDLP_DOWNLOAD_TIMEOUT_SECONDS = 900.0

# Прод-инцидент 30.08.2026 «Invalid data found when processing input»:
# устаревший yt-dlp + форс-изменения YouTube (SABR/403, issue #17456) →
# битые CDN-фрагменты → ffmpeg-merge падает. Ретрай с резервным
# player_client — перебор по очереди до первого успеха.
_FALLBACK_PLAYER_CLIENTS = ("android", "web_safari", "tv", "ios", "mweb")
# Максимум ПОПЫТОК (загрузок) на одно видео: дефолт + до 2 резервных клиентов.
_MAX_YTDLP_ATTEMPTS = 3
# Минимальный свободный диск перед загрузкой (WARNING, не блокируем).
_MIN_FREE_DISK_BYTES = 500 * 1024 * 1024

# Признаки недоступности видео (детект до скачивания — понятная ошибка
# вместо «Invalid data…»). M1: ТОЛЬКО полные фразы бот-проверки — голый
# «sign in» даёт ложные срабатывания (например, «how to sign in to our
# site» в описании).
_AVAILABILITY_SIGN_IN_MARKERS = (
    "sign in to confirm you're not a bot",
    "confirm you're not a bot",
    "confirm you are not a bot")
_DRM_NOTE_MARKERS = ("drc", "premium", "cenc", "widevine")

# Epic 77 (D286): ТОЛЬКО эти хосты идут в yt-dlp-ветку; остальные платформы
# (vimeo, vk, …) — cobalt как раньше. Поддомены/подмена не матчатся.
_YOUTUBE_HOSTS = frozenset({
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "youtu.be", "music.youtube.com",
})

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

# Epic 77 (review-fix): инфикс промежуточных файлов yt-dlp при merge
# (vd_*.f137.mp4 / vd_*.f140.m4a — YoutubeDL.py prepend_extension).
_INTERMEDIATE_INFIX_RE = re.compile(r"\.f\d+\.[^.]+$")


def _is_postprocess_error(text: str) -> bool:
    """Маркер падения на постпроцессинге (ffmpeg merge) — для merge-фолбека."""
    lowered = str(text).lower()
    return ("postprocess" in lowered or "error opening input" in lowered
            or "invalid data found" in lowered or "ffmpeg" in lowered)


class DownloadError(Exception):
    """Общая ошибка скачивания (yt-dlp/Cobalt/стрим) — пул VD_ERROR_PHRASES."""


class DownloadBusyError(DownloadError):
    """Лок занят другим скачиванием — пул VD_BUSY_PHRASES."""


class DownloadTooBigError(DownloadError):
    """Файл жирнее лимита телеги — пул VD_TOO_BIG_PHRASES."""


class CobaltServiceDownError(DownloadError):
    """Cobalt недоступен (ConnectError) — пул VD_SERVICE_DOWN_PHRASES."""


class DownloadUnavailableError(DownloadError):
    """Видео недоступно: возрастное ограничение / требуется вход / DRM /
    live. Понятное русское сообщение пользователю (пул VD_UNAVAILABLE_PHRASES)."""


@dataclass(frozen=True)
class ProbeResult:
    title: str
    qualities: tuple[str, ...]          # «360p»…«2160p», DESC


def is_youtube_url(url: str) -> bool:
    """Epic 77 (D286): YouTube-URL → yt-dlp-ветка, остальные → cobalt.

    hostname (lowercase, без трейлинг точки) строго в _YOUTUBE_HOSTS;
    scheme только http/https; любой парс-фейл/None-hostname → False.
    """
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    hostname = (parts.hostname or "").lower().rstrip(".")
    return hostname in _YOUTUBE_HOSTS


def is_direct_media_url(url: str) -> bool:
    """Замечание чекапа: прямая медиа-ссылка (mp4/webm/mov/mkv/avi/gif)
    с расширением в КОНЦЕ URL (с учётом query/фрагмента) → стрим-даунлоад.
    Схема http/https; путь (до ?/#) заканчивается расширением."""
    try:
        parts = urlsplit(str(url))
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.path:
        return False
    return bool(_DIRECT_MEDIA_RE.search(parts.path))


def _direct_ext(url: str) -> str:
    """Расширение из пути URL (без query); дефолт mp4."""
    try:
        path = urlsplit(str(url)).path
    except ValueError:
        path = ""
    suffix = Path(path).suffix.lstrip(".").lower()
    return suffix if suffix in ("mp4", "webm", "mov", "mkv", "avi", "gif") \
        else "mp4"


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
        """Скачивание под ГЛОБАЛЬНЫМ локом. Занят → DownloadBusyError сразу.
        Epic 77 (D288): YouTube + гейт on → yt-dlp-ветка; иначе cobalt.
        Контракт (url, quality) -> Path НЕ меняется."""
        if self._lock.locked():
            raise DownloadBusyError("another download is running")
        async with self._lock:
            self._download_dir.mkdir(parents=True, exist_ok=True)
            # Прод-хотфикс: прямые медиа-ссылки (mp4/webm/…) — стрим-даунлоад
            if is_direct_media_url(url):
                return await self.download_direct(url)
            if settings.YTDLP_FOR_YOUTUBE and is_youtube_url(url):
                return await self.download_ytdlp(url, quality)
            tunnel_url, filename = await self._request_tunnel(url, quality)
            return await self._stream_to_file(tunnel_url, filename)

    async def download_direct(self, url: str) -> Path:
        """Прямой стрим медиа-файла (mp4/webm/…): httpx с браузерным UA;
        при 403 — повтор с Referer (2ch.su и пр.); байты > _DIRECT_MAX_BYTES →
        DownloadTooBigError. Возвращает путь к сохранённому файлу."""
        stamp = int(time.time())
        rand = secrets.token_hex(4)
        ext = _direct_ext(url)
        self._download_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._download_dir / f"vd_{stamp}_{rand}.{ext}"
        headers = {"User-Agent": _DIRECT_UA}
        attempts = [headers] + [
            {**headers, "Referer": ref} for ref in _DIRECT_REFERRERS]
        last_status: int | None = None
        for attempt_headers in attempts:
            try:
                async with httpx.AsyncClient(
                        timeout=httpx.Timeout(60.0, connect=15.0),
                        follow_redirects=True) as client:
                    async with client.stream(
                            "GET", url, headers=attempt_headers) as resp:
                        if resp.status_code == 403:
                            last_status = 403
                            logger.warning(
                                "[videodl] direct 403 → retry with referer "
                                "| url=%s", url)
                            continue
                        if resp.status_code >= 400:
                            out_path.unlink(missing_ok=True)
                            raise DownloadError(
                                f"direct download HTTP {resp.status_code}"
                                f" | url={url}")
                        size = 0
                        with open(out_path, "wb") as fh:
                            async for chunk in resp.aiter_bytes(65536):
                                size += len(chunk)
                                if size > _DIRECT_MAX_BYTES:
                                    fh.close()
                                    out_path.unlink(missing_ok=True)
                                    raise DownloadTooBigError(
                                        f"file exceeds {_DIRECT_MAX_BYTES}"
                                        f" bytes | url={url}")
                                fh.write(chunk)
                logger.info("[videodl] direct downloaded | url=%s | "
                            "bytes=%d | ext=%s", url, size, ext)
                return out_path
            except DownloadTooBigError:
                raise
            except httpx.HTTPError as exc:
                # B1: частично записанный файл (обрыв в середине стрима) —
                # не оставляем на диске.
                out_path.unlink(missing_ok=True)
                raise DownloadError(
                    f"direct download failed: {exc} | url={url}") from exc
        out_path.unlink(missing_ok=True)
        raise DownloadError(
            f"direct download 403 (все referer-попытки) | url={url}"
            if last_status == 403 else f"direct download failed | url={url}")

    @staticmethod
    def _format_selector(quality: str) -> str:
        """Селектор форматов с приоритетом прямых CDN-ссылок ([protocol^=https])
        над битыми HLS/m3u8 (wX4OiGISNlY — SABR-эксперимент ломает HDR10)."""
        quality_norm = quality
        if quality_norm == "max":
            return (
                "bv[ext=mp4][protocol^=https]+ba[ext=m4a]"
                "/bv[ext=mp4]+ba[ext=m4a]/bv+ba/b")
        h = int(quality_norm)
        return (
            f"bv[ext=mp4][height<={h}][protocol^=https]+ba[ext=m4a]"
            f"/bv[ext=mp4][height<={h}]+ba[ext=m4a]"
            f"/bv[height<={h}]+ba/b[height<={h}]")

    async def download_ytdlp(self, url: str, quality: str) -> Path:
        """Epic 77 (D287): YouTube через локальный yt-dlp (+POT-плагин).
        Вызывается ИЗ download() под глобальным локом. Возвращает
        ФАКТИЧЕСКИЙ post-merge путь (итоговый mp4).

        Review-fix Epic 77: итоговый путь берётся из
        info["requested_downloads"][-1]["filepath"] после
        extract_info(download=True). progress_hooks "finished" стреляют
        ТОЛЬКО на фазе скачивания и несут PRE-merge имена промежуточных
        файлов (vd_*.f<id>.mp4 / vd_*.f<id>.m4a) — merged-файл там НЕ
        появляется (merge = постпроцессор, см. YoutubeDL.py:3559-3577).

        Прод-хотфикс 30.08.2026: перед загрузкой — диск-чек (WARNING);
        при ошибке yt-dlp — перебор резервных player_client (android первым).
        Диагностика DevOps (wX4OiGISNlY): HDR10-m3u8-форматы (633/636) в SABR
        приходят ПОВРЕЖДЁННЫМИ → ffmpeg «Invalid data found». Селекторы с
        [protocol^=https] предпочитают прямые CDN-ссылки битым HLS.
        """
        from yt_dlp import YoutubeDL              # ленивый тяжёлый импорт (D261)

        quality_norm = self._normalize_quality(quality)
        if quality_norm == "max":
            h = None
        else:
            h = int(quality_norm)
        format_selector = self._format_selector(
            "max" if h is None else str(h))
        stamp = int(time.time())
        rand = secrets.token_hex(4)
        prefix = f"vd_{stamp}_{rand}"
        outtmpl = str(self._download_dir / f"{prefix}.%(ext)s")

        # Диск-чек (не блокируем — только WARNING для диагностики).
        self._download_dir.mkdir(parents=True, exist_ok=True)
        try:
            usage = shutil.disk_usage(self._download_dir)
            if usage.free < _MIN_FREE_DISK_BYTES:
                logger.warning(
                    "[videodl] low disk | free=%d MB | url=%s",
                    usage.free // (1024 * 1024), url)
        except OSError:
            logger.warning("[videodl] disk_usage failed | dir=%s",
                           self._download_dir, exc_info=True)

        def _hook(d: dict) -> None:
            if d.get("status") == "downloading" and \
                    d.get("downloaded_bytes", 0) > VD_MAX_BYTES:
                raise DownloadTooBigError(
                    f"file exceeds {VD_MAX_BYTES} bytes")

        def _build_opts(extractor_args: dict | None, merge: bool,
                        format_sel: str) -> dict:
            opts = {**build_ytdlp_base_opts(), "format": format_sel,
                    "outtmpl": outtmpl,
                    "noplaylist": True, "quiet": True, "noprogress": True,
                    "progress_hooks": [_hook]}
            if merge:
                opts["merge_output_format"] = "mp4"
            # B2: extractor_args МЕРЖАТСЯ с базовыми (потенциальный
            # pot_provider/pot_token_background из build_ytdlp_base_opts
            # сохраняются; player_client ретрая перезаписывает свой ключ).
            base_ea = opts.get("extractor_args") or {}
            youtube_ea = dict(base_ea.get("youtube") or {})
            if extractor_args:
                youtube_ea.update(extractor_args.get("youtube") or {})
            if youtube_ea:
                opts["extractor_args"] = {"youtube": youtube_ea}
            return opts

        def _run(extractor_args: dict | None, merge: bool,
                 format_sel: str) -> dict:
            with YoutubeDL(_build_opts(extractor_args, merge, format_sel)) \
                    as ydl:
                return ydl.extract_info(url, download=True)

        async def _attempt(extractor_args: dict | None, merge: bool,
                           format_sel: str, phase: str):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_run, extractor_args, merge, format_sel),
                    timeout=_YTDLP_DOWNLOAD_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                raise DownloadError(
                    f"yt-dlp timeout after "
                    f"{int(_YTDLP_DOWNLOAD_TIMEOUT_SECONDS)}s"
                    f" | url={url} | phase={phase}") from exc
            except DownloadTooBigError:
                raise                       # TOO_BIG-пул фраз в хендлере (D288)
            except Exception as exc:
                # Прод-хотфикс: бот-проверка/LOGIN_REQUIRED → понятная ошибка
                text = str(exc).lower()
                if any(m in text for m in _AVAILABILITY_SIGN_IN_MARKERS) \
                        or "login_required" in text:
                    raise DownloadUnavailableError(
                        "YouTube требует подтверждения (бот-проверка) — "
                        f"попробуйте позже или другой источник | url={url}") \
                        from exc
                raise DownloadError(
                    f"yt-dlp failed: {exc} | url={url} | phase={phase}") \
                    from exc

        def _raise_unavailable(info: dict) -> None:
            """Детект недоступности (c): age-рестрикт/Sign-in/DRM/live →
            понятная ошибка пользователю."""
            age_limit = info.get("age_limit") or 0
            availability = str(info.get("availability") or "")
            desc = str(info.get("description") or "")
            lower = (availability + "\n" + desc).lower()
            if age_limit > 0:
                raise DownloadUnavailableError(
                    f"видео недоступно: возрастное ограничение "
                    f"(age_limit={age_limit}) | url={url}")
            if any(m in lower for m in _AVAILABILITY_SIGN_IN_MARKERS):
                raise DownloadUnavailableError(
                    f"видео недоступно: требуется вход в аккаунт / "
                    f"подтверждение «не робот» | url={url}")
            if info.get("is_live"):
                raise DownloadUnavailableError(
                    f"видео недоступно: прямая трансляция | url={url}")
            drm = False
            for fmt in info.get("formats") or []:
                note = str((fmt or {}).get("format_note") or "").lower()
                if any(m in note for m in _DRM_NOTE_MARKERS):
                    drm = True
                    break
            if drm:
                raise DownloadUnavailableError(
                    f"видео недоступно: защищено DRM | url={url}")

        # M2 (утечка .f* при успешном merge-фолбеке): уборка промежуточных
        # файлов (vd_*.f<id>.*, *.part, *.ytdl) выполняется БЕЗУСЛОВНО —
        # и при успехе, и при ошибке; итоговый файл (keep) сохраняется.
        def _final_of(info_: dict | None) -> Path | None:
            """Итоговый файл из requested_downloads (если yt-dlp его дал)."""
            requested = info_.get("requested_downloads") if isinstance(
                info_, dict) else None
            if isinstance(requested, list) and requested and \
                    isinstance(requested[-1], dict) and \
                    requested[-1].get("filepath"):
                return Path(str(requested[-1]["filepath"]))
            return None

        def _purge_temp(keep: Path | None) -> None:
            """Удалить все {prefix}.* кроме keep (промежуточные .f<id>.*,
            .part, .ytdl и т.п.)."""
            for leftover in self._download_dir.glob(f"{prefix}.*"):
                if keep is not None and \
                        leftover.resolve() == keep.resolve():
                    continue
                leftover.unlink(missing_ok=True)

        ok = False
        merge_fallback_used = False
        info: dict | None = None
        last_err: DownloadError | None = None

        # Первая попытка: дефолт (клиент по умолчанию, merge, целевое качество).
        try:
            info = await _attempt(None, True, format_selector, "download")
            ok = True
        except DownloadError as exc:
            last_err = exc
            # Merge-фолбек (d): если падение на постпроцессинге (ffmpeg/
            # merge/Invalid data) — повтор БЕЗ merge, один файл.
            err_text = str(exc)
            if _is_postprocess_error(err_text):
                merge_fallback_used = True
                logger.warning(
                    "[videodl] merge-фолбек (без merge) | url=%s | err=%s",
                    url, err_text)
                try:
                    info = await _attempt(
                        None, False, "b[ext=mp4]/b/best", "no-merge")
                    ok = True
                except DownloadError as exc2:
                    last_err = exc2
            # Резервные клиенты (b): перебор по очереди, до _MAX_YTDLP_ATTEMPTS
            # загрузок всего (дефолт и merge-фолбек уже потрачены).
            attempts_left = max(0, _MAX_YTDLP_ATTEMPTS - 1
                                - (1 if ok else 0)
                                - (1 if merge_fallback_used else 0))
            for client in _FALLBACK_PLAYER_CLIENTS:
                if ok or attempts_left <= 0:
                    break
                logger.warning(
                    "[videodl] retry with player_client=%s | url=%s | "
                    "err=%s", client, url, last_err)
                try:
                    info = await _attempt(
                        {"youtube": {"player_client": [client]}},
                        True, format_selector, f"retry-{client}")
                    ok = True
                except DownloadError as exc2:
                    last_err = exc2
                    attempts_left -= 1
        finally:
            # M2: уборка БЕЗУСЛОВНА — и при успехе (merge-фолбек оставляет
            # .f137.mp4/.f140.m4a), и при ошибке; итоговый файл сохраняется.
            if not ok:
                _purge_temp(None)
            else:
                keep = _final_of(info)
                if keep is not None:
                    _purge_temp(keep)
        if not ok:
            raise last_err if last_err is not None else DownloadError(
                f"yt-dlp failed | url={url}")

        # Детект недоступности (c): возрастное ограничение / Sign-in / DRM /
        # live → понятная ошибка вместо «Invalid data…».
        if isinstance(info, dict):
            try:
                _raise_unavailable(info)
            except DownloadUnavailableError:
                _purge_temp(None)
                raise

        # Канонический post-merge путь: requested_downloads заполняется
        # ПОСЛЕ постпроцессоров (merge) → filepath = итоговый файл.
        requested = info.get("requested_downloads") if isinstance(
            info, dict) else None
        if isinstance(requested, list) and requested and \
                isinstance(requested[-1], dict) and \
                requested[-1].get("filepath"):
            final_path = Path(str(requested[-1]["filepath"]))
            _purge_temp(final_path)
            return final_path
        # Fallback: glob БЕЗ промежуточных (vd_*.f<id>.*, .part/.ytdl);
        # ровно один кандидат → он итоговый, иначе неоднозначность → ошибка.
        matches = sorted(
            p for p in self._download_dir.glob(f"{prefix}.*")
            if p.suffix not in (".part", ".ytdl")
            and not _INTERMEDIATE_INFIX_RE.search(p.name))
        if len(matches) == 1:
            _purge_temp(matches[0])
            return matches[0]
        # F1: edge-дыра M2 — при неоднозначности/отсутствии итогового файла
        # тоже чистим каталог (никаких .f*/.part на диске).
        _purge_temp(None)
        raise DownloadError("yt-dlp finished but output file not found")

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
