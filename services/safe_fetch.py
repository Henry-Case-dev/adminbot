"""Раунд 10.27 (MCA Wave 1, `mca-02-safe-fetch-cookies`) — общий SafeFetcher.

Единый безопасный контур внешних загрузок (ADR-1027-5 D1–D7):

* только HTTP/HTTPS, нормализация URL, запрет встроенных credentials;
* SSRF-проверки IPv4/IPv6 (loopback/private/link-local/CGNAT/ULA/reserved/
  multicast/unspecified/broadcast), IPv4-mapped IPv6 и metadata-эндпоинты;
* проверка **каждого** redirect + **фактического** адреса подключения
  (anti-rebinding через ``network_stream.get_extra_info("server_addr")``);
* потоковые лимиты переданных **и** распакованных байтов, timeout, параллелизм;
* отдельный видео-профиль загрузки на диск (HTML-лимит к видео не применяется);
* ошибки ``SafeFetchError(code, stage, reason, retryable)`` + R17-маскирование;
* egress-guard (loopback HTTP CONNECT/absolute-URI прокси) для медиа-подпроцессов
  и обходящих клиентов;
* отдельный env-only allowlist доверенных API/локальных служб.

Границы (REUSE, второй fetch-контур запрещён): `services/llm_probe._safe_base`
(паттерн host через `urlsplit`), cookies/proxy (`config.settings`, env-only, не
логируются), download-контракт ADR-1016-1, события `services/mca_events`.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx

from config.settings import settings
from services import mca_gates
from services.log_ring import sanitize
from services.mca_events import emit_mca_event

logger = logging.getLogger(__name__)

# ── ошибки/стадии (D7) ───────────────────────────────────────────────────────
STAGES = frozenset({
    "normalize", "resolve", "connect", "redirect", "stream", "decompress",
})

#: коды, которые могут попасть в событие MCA-13 (`reason_code`).
REASON_CODES = frozenset({
    "scheme_not_allowed", "credentials_in_url", "invalid_url",
    "destination_blocked", "metadata_endpoint_blocked", "redirect_blocked",
    "too_many_redirects", "resolve_failed", "too_many_bytes",
    "decompressed_too_large", "safe_fetch_timeout", "egress_guard_unavailable",
    "client_error",
})

_DEFAULT_HTML_MAX = 5 * 1024 * 1024          # 5 MB — HTML-профиль
_DEFAULT_HTML_DECOMPRESSED = 8 * 1024 * 1024  # 8 MB — распакованный потолок
_DEFAULT_IMAGE_MAX = 25 * 1024 * 1024         # 25 MB — изображение
_DEFAULT_VIDEO_MAX = 2_000_000_000            # 2 GB — совместимо с baseline
_DEFAULT_HTML_TIMEOUT = 10.0
_DEFAULT_VIDEO_TIMEOUT = 240.0
_DEFAULT_MAX_REDIRECTS = 5
_READ_CHUNK = 65_536

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

#: секретные query-параметры, значения которых маскируются (R17).
_SECRET_QUERY_KEYS = frozenset({
    "key", "api_key", "apikey", "api-key", "x-api-key", "token",
    "access_token", "auth", "authorization", "sig", "signature", "secret",
    "password", "passwd", "pwd", "session", "sessionid", "cookie",
})
#: metadata-эндпоинты (по IP и по имени хоста).
_METADATA_IPS = frozenset({
    "169.254.169.254", "fd00:ec2::254", "100.100.100.200",
})
_METADATA_HOSTS = frozenset({
    "metadata.google.internal", "metadata.goog",
})

_DOT_SEGMENT_RE = re.compile(r"[\x00-\x1f\x7f\\]")


class SafeFetchError(Exception):
    """Ошибка безопасной загрузки: код/стадия/понятная причина/retryable.

    ``reason`` — уже R17-safe строка (URL с query маскируется)."""

    def __init__(self, code: str, stage: str, reason: str = "",
                 retryable: bool = False) -> None:
        self.code = code if code in REASON_CODES else "client_error"
        self.stage = stage if stage in STAGES else "stream"
        self.reason = str(reason)
        self.retryable = bool(retryable)
        super().__init__(f"code={self.code} | stage={self.stage} | "
                         f"reason={self.reason}")

    def to_event_fields(self) -> dict:
        return {"stage": self.stage, "reason_code": self.code,
                "error_json": {"type": "SafeFetchError", "code": self.code,
                               "stage": self.stage,
                               "retryable": self.retryable}}


# ── R17-маскирование ─────────────────────────────────────────────────────────

_QUERY_SECRET_RE = re.compile(
    r"(?i)(^|[?&])((?:key|api_key|apikey|api-key|x-api-key|token|access_token|"
    r"auth|authorization|sig|signature|secret|password|passwd|pwd|session|"
    r"sessionid|cookie)=)[^&\s]*")


def mask_query(query: str) -> str:
    """Маскировать значения секретных query-параметров (форма без re-encode)."""
    if not query:
        return ""
    # `parse_qsl` — валидация (битые пары не считаем секретом), вывод — regex,
    # чтобы сохранить исходную кодировку остальных параметров.
    try:
        parse_qsl(query, keep_blank_values=True)
    except Exception:      # pragma: no cover
        return "***"
    return _QUERY_SECRET_RE.sub(r"\1\2***", query)


def mask_url(url: str) -> str:
    """R17: URL без секретов — scheme://host[:port]/path?query(masked)."""
    try:
        parts = urlsplit(str(url))
    except Exception:
        return "[redacted-url]"
    if not parts.scheme and not parts.netloc:
        return "[redacted-url]"
    host = parts.hostname or ""
    if host and ":" in host:
        host = f"[{host}]"
    netloc = host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    masked = urlunsplit((parts.scheme, netloc, parts.path,
                         mask_query(parts.query), ""))
    return sanitize(masked)


def mask_text(text: str) -> str:
    """R17: маскировать секреты (в т.ч. секретные query) в произвольной строке."""
    return sanitize(_QUERY_SECRET_RE.sub(r"\1\2***", str(text or "")))


# ── нормализация URL (D2) ────────────────────────────────────────────────────

def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4 — удалить `.`/`..`-сегменты без обращения к ФС."""
    if not path:
        return "/"
    output: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if output:
                output.pop()
            continue
        output.append(segment)
    normalized = "/" + "/".join(output)
    if path.endswith("/") and not normalized.endswith("/"):
        normalized += "/"
    return normalized


def normalize_url(url: Any) -> str:
    """Нормализовать и валидировать URL (схема/credentials/host/порт/путь).

    Raise ``SafeFetchError`` (стадия ``normalize``) при отклонении."""
    if not isinstance(url, str) or not url.strip():
        raise SafeFetchError("invalid_url", "normalize", "empty url")
    raw = url.strip()
    if _DOT_SEGMENT_RE.search(raw):
        raise SafeFetchError("invalid_url", "normalize",
                             "control characters or backslash in url")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise SafeFetchError("invalid_url", "normalize",
                             f"unparseable url ({type(exc).__name__})") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise SafeFetchError("scheme_not_allowed", "normalize",
                             f"scheme {scheme or 'none'!r} not allowed")
    if parts.username is not None or parts.password is not None:
        raise SafeFetchError("credentials_in_url", "normalize",
                             "embedded credentials are not allowed")
    host = (parts.hostname or "").strip()
    if not host:
        raise SafeFetchError("invalid_url", "normalize", "missing host")
    if ":" in host:                      # IPv6-литерал
        try:
            ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise SafeFetchError("invalid_url", "normalize",
                                 "invalid IPv6 host") from exc
        host_ascii = host.lower()
    else:
        try:
            host_ascii = host.encode("idna").decode("ascii").lower()
        except (UnicodeError, ValueError) as exc:
            raise SafeFetchError("invalid_url", "normalize",
                                 "invalid internationalized host") from exc
        host_ascii = host_ascii.rstrip(".")
        if not host_ascii:
            raise SafeFetchError("invalid_url", "normalize", "missing host")
    try:
        port = parts.port
    except ValueError as exc:
        raise SafeFetchError("invalid_url", "normalize",
                             "invalid port") from exc
    default_port = 80 if scheme == "http" else 443
    if port == default_port:
        port = None
    path = _remove_dot_segments(parts.path)
    netloc = host_ascii if ":" not in host_ascii else f"[{host_ascii}]"
    if port:
        netloc = f"{netloc}:{port}"
    # фрагмент не передаётся на сервер — канонически отбрасываем.
    return urlunsplit((scheme, netloc, path, parts.query, ""))


# ── SSRF-политика назначения (D3) ────────────────────────────────────────────

def _ip_reason(addr: ipaddress._BaseAddress) -> str | None:
    """Причина блокировки для IP-адреса (или None, если адрес допустим)."""
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:                       # ::ffff:a.b.c.d
        return "ipv4_mapped"
    text = str(addr)
    if text in _METADATA_IPS:
        return "metadata_endpoint"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link_local"
    if addr.is_multicast:
        return "multicast"
    if addr.is_unspecified:
        return "unspecified"
    if addr.is_reserved:
        return "reserved"
    if addr.is_private:
        return "private"
    if addr.version == 4:
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return "cgnat"
        if addr == ipaddress.IPv4Address("255.255.255.255"):
            return "broadcast"
    else:
        if addr in ipaddress.ip_network("fc00::/7"):
            return "ula"
    return None


def destination_reason(host: str) -> str | None:
    """Причина блокировки для host-литерала/имени (R17: без значений секретов)."""
    if not host:
        return "invalid_host"
    if host.lower().rstrip(".") in _METADATA_HOSTS:
        return "metadata_endpoint"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None                              # имя — проверяется после resolve
    return _ip_reason(addr)


def _resolve_ip(host: str) -> list[str]:
    """Резолв A/AAAA (sync; вызывается из executor'а). Кэш на время класса."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    out: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in out:
            out.append(ip)
    return out


async def _aresolve(host: str) -> list[str]:
    return await asyncio.to_thread(_resolve_ip, host)


def _trusted_hosts() -> set[str]:
    raw = str(getattr(settings, "SAFE_FETCH_TRUSTED_HOSTS", "") or "")
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    if not hosts:
        hosts = {"localhost", "127.0.0.1", "::1"}
    return hosts


def _trusted_ports() -> set[int]:
    raw = str(getattr(settings, "SAFE_FETCH_TRUSTED_PORTS", "") or "")
    ports: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ports.add(int(part))
    return ports


def is_trusted(host: str, port: int | None) -> bool:
    """Хост/порт в отдельном env-allowlist доверенных API/локальных служб."""
    if (host or "").lower().rstrip(".") not in _trusted_hosts():
        return False
    ports = _trusted_ports()
    if not ports:
        return True
    return port in ports


def _first_blocked(ips: Iterable[str]) -> str | None:
    for ip in ips:
        reason = _ip_reason(ipaddress.ip_address(ip))
        if reason:
            return reason
    return None


@dataclass
class GuardedTarget:
    """Результат pre-flight проверки: нормализованный URL + валидные IP."""
    url: str
    host: str
    port: int
    scheme: str
    resolved: tuple[str, ...] = field(default_factory=tuple)


def guarded_target(url: Any, *, trusted: bool = False,
                   resolve: bool = True) -> GuardedTarget:
    """Нормализовать + проверить назначение (SSRF) ДО передачи клиенту.

    ``trusted=True`` разрешает приватные/loopback-цели, но **только** если
    хост/порт в env-allowlist (доверенные API/локальные службы). Пользовательские
    URL всегда ``trusted=False`` → внутренняя сеть блокируется.

    Raise ``SafeFetchError`` (стадии normalize/resolve)."""
    normalized = normalize_url(url)
    parts = urlsplit(normalized)
    scheme = parts.scheme
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "https" else 80)

    allow_internal = trusted and is_trusted(host, port)

    literal_reason = destination_reason(host)
    if literal_reason == "metadata_endpoint":
        raise SafeFetchError("metadata_endpoint_blocked", "resolve",
                             "destination blocked (metadata_endpoint)")
    if literal_reason and not allow_internal:
        raise SafeFetchError("destination_blocked", "resolve",
                             f"destination blocked ({literal_reason})")

    resolved: tuple[str, ...] = ()
    if literal_reason is not None and allow_internal:
        # M-MCA02-2: доверенная цель задана IP-литералом — resolve не
        # выполняется, но peer-проверка (anti-rebinding) должна иметь
        # валидированный адрес, иначе фактический server_addr даёт ложный
        # mismatch. Канонизируем сам литерал.
        try:
            resolved = (str(ipaddress.ip_address(host)),)
        except ValueError:      # pragma: no cover - нормализация уже отвергла
            resolved = ()
    elif resolve and literal_reason is None:
        try:
            resolved = tuple(_resolve_ip(host))
        except (socket.gaierror, UnicodeError, OSError) as exc:
            raise SafeFetchError("resolve_failed", "resolve",
                                 f"dns resolution failed ({type(exc).__name__})"
                                 ) from exc
        if not resolved:
            raise SafeFetchError("resolve_failed", "resolve",
                                 "dns resolution returned no addresses")
        reason = _first_blocked(resolved)
        if reason == "metadata_endpoint":
            raise SafeFetchError("metadata_endpoint_blocked", "resolve",
                                 "destination blocked (metadata_endpoint)")
        if reason and not allow_internal:
            raise SafeFetchError("destination_blocked", "resolve",
                                 f"destination blocked ({reason})")
    return GuardedTarget(normalized, host, port, scheme, resolved)


async def aguarded_target(url: Any, *, trusted: bool = False) -> GuardedTarget:
    """Async-обёртка ``guarded_target`` (резолв в executor'е)."""
    return await asyncio.to_thread(guarded_target, url, trusted=trusted)


# ── профили/лимиты (D5/D6) ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Profile:
    name: str
    max_transmitted: int
    max_decompressed: int
    timeout: float
    concurrency: int


def _profile(name: str, *, max_bytes: int | None = None,
             timeout: float | None = None) -> Profile:
    if name == "video":
        return Profile("video", max_bytes or _int_setting(
            "SAFE_FETCH_VIDEO_MAX_BYTES", _DEFAULT_VIDEO_MAX),
            _int_setting("SAFE_FETCH_VIDEO_MAX_DECOMPRESSED_BYTES",
                         _DEFAULT_VIDEO_MAX),
            timeout or _float_setting("SAFE_FETCH_VIDEO_TIMEOUT_SECONDS",
                                      _DEFAULT_VIDEO_TIMEOUT), 2)
    if name == "image":
        cap = max_bytes or _int_setting("SAFE_FETCH_IMAGE_MAX_BYTES",
                                        _DEFAULT_IMAGE_MAX)
        return Profile("image", cap, cap,
                       timeout or _DEFAULT_HTML_TIMEOUT, 4)
    # html (default)
    return Profile("html", max_bytes or _int_setting(
        "SAFE_FETCH_HTML_MAX_BYTES", _DEFAULT_HTML_MAX),
        _int_setting("SAFE_FETCH_HTML_MAX_DECOMPRESSED_BYTES",
                     _DEFAULT_HTML_DECOMPRESSED),
        timeout or _float_setting("SAFE_FETCH_HTML_TIMEOUT_SECONDS",
                                  _DEFAULT_HTML_TIMEOUT), 8)


def _int_setting(name: str, default: int) -> int:
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):      # pragma: no cover
        return default
    return value if value > 0 else default


def _float_setting(name: str, default: float) -> float:
    try:
        value = float(getattr(settings, name, default))
    except (TypeError, ValueError):      # pragma: no cover
        return default
    return value if value > 0 else default


_semaphores: dict[str, asyncio.Semaphore] = {}


def _semaphore(name: str, limit: int) -> asyncio.Semaphore:
    sem = _semaphores.get(name)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _semaphores[name] = sem
    return sem


# ── peer-проверка (anti-rebinding, D3) ───────────────────────────────────────

def peer_allowed(response: httpx.Response, validated: Iterable[str]
                 ) -> tuple[bool, str]:
    """Сверить фактический peer-адрес с валидированным набором.

    Возвращает ``(ok, status)``; ``status ∈ {ok, mismatch, unverifiable}``."""
    stream = (getattr(response, "extensions", None) or {}).get("network_stream")
    if stream is None:
        return True, "unverifiable"
    try:
        addr = stream.get_extra_info("server_addr")
    except Exception:      # pragma: no cover
        return True, "unverifiable"
    if not addr:
        return True, "unverifiable"
    ip = str(addr[0])
    return (ip in set(validated)), "ok" if ip in set(validated) else "mismatch"


# ── SafeFetcher (D1/D5/D6/D7) ────────────────────────────────────────────────

@dataclass
class SafeFetchResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str

    def text(self) -> str:
        encoding = None
        try:
            ctype = self.headers.get("content-type", "")
            m = re.search(r"charset=([\w\-]+)", ctype, re.I)
            if m:
                encoding = m.group(1)
        except Exception:      # pragma: no cover
            encoding = None
        try:
            return self.content.decode(encoding or "utf-8", errors="replace")
        except LookupError:    # pragma: no cover
            return self.content.decode("utf-8", errors="replace")


class SafeFetcher:
    """Общий безопасный fetch-контур (единственный; второй запрещён)."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(follow_redirects=False, timeout=None)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- внутренний цикл с ручными redirect'ами и peer-проверкой --
    async def _request(self, url: str, *, profile: Profile, method: str,
                       headers: dict, json_body: Any, content: Any,
                       client: httpx.AsyncClient | None,
                       trusted: bool) -> tuple[httpx.Response, str]:
        http = client or self._get_client()
        base_headers = {"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"}
        if headers:
            base_headers.update(headers)
        current = url
        for _ in range(_DEFAULT_MAX_REDIRECTS + 1):
            try:
                target = await aguarded_target(current, trusted=trusted)
            except SafeFetchError:
                raise
            request = http.build_request(
                method, target.url, headers=base_headers, json=json_body,
                content=content, timeout=profile.timeout)
            # B-MCA02-1/ADR-1027-5 D5: per-request профильный timeout
            # (connect/read/write/pool). httpx 0.28 `send` не принимает
            # `timeout=`, поэтому значение задаётся на `build_request`;
            # иначе клиент с `timeout=None` не ограничивал бы запрос вообще.
            try:
                response = await http.send(
                    request, stream=True, follow_redirects=False)
            except httpx.TimeoutException:
                raise
            except httpx.HTTPError as exc:
                raise SafeFetchError("client_error", "connect",
                                     f"transport error ({type(exc).__name__})",
                                     retryable=True) from exc
            ok, status = peer_allowed(response, target.resolved)
            if not ok:
                await response.aclose()
                raise SafeFetchError("destination_blocked", "connect",
                                     "actual peer address not validated")
            if status == "unverifiable":
                logger.warning(
                    "[safe_fetch] peer unverifiable (no network_stream) | "
                    "host=%s | stage=connect", target.host)
            if (response.status_code in (301, 302, 303, 307, 308)
                    and response.headers.get("location")):
                location = response.headers["location"]
                await response.aclose()
                current = urljoin(target.url, location)
                try:
                    await aguarded_target(current, trusted=trusted)
                except SafeFetchError as exc:
                    code = ("redirect_blocked"
                            if exc.code in ("destination_blocked",
                                            "metadata_endpoint_blocked")
                            else exc.code)
                    raise SafeFetchError(code, "redirect",
                                         f"redirect blocked ({exc.code})") from exc
                continue
            return response, target.url
        raise SafeFetchError("too_many_redirects", "redirect",
                             f"more than {_DEFAULT_MAX_REDIRECTS} redirects")

    async def fetch(self, url: str, *, profile: str = "html",
                    method: str = "GET", headers: dict | None = None,
                    json_body: Any = None, content: Any = None,
                    client: httpx.AsyncClient | None = None,
                    trusted: bool = False, max_bytes: int | None = None,
                    timeout: float | None = None) -> SafeFetchResponse:
        """Потоково прочитать ответ с лимитами (переданные+распакованные)."""
        prof = _profile(profile, max_bytes=max_bytes, timeout=timeout)
        sem = _semaphore(prof.name, prof.concurrency)
        host_ref = final_url_if(url)
        await self._emit("start", "INFO", host_ref)
        async with sem:
            started = time.monotonic()
            response = None
            final_url = final_url_if(url)
            try:
                # Общий deadline профиля поверх per-phase httpx-timeout:
                # гарантирует возврат даже на транспортах/стримах, где
                # per-phase таймаут не срабатывает (B-MCA02-1, SC-06).
                async with asyncio.timeout(prof.timeout):
                    response, final_url = await self._request(
                        url, profile=prof, method=method,
                        headers=headers or {}, json_body=json_body,
                        content=content, client=client, trusted=trusted)
                    body, decoded = await self._read_stream(response, prof)
            except SafeFetchError as exc:
                await self._emit_failure(final_url, exc, started)
                raise
            except (TimeoutError, httpx.TimeoutException) as exc:
                err = SafeFetchError("safe_fetch_timeout", "stream",
                                     "request timeout", retryable=True)
                await self._emit_failure(final_url, err, started)
                raise err from exc
            finally:
                if response is not None:
                    await response.aclose()
        await self._emit("success", "INFO", final_url,
                         duration_ms=int((time.monotonic() - started) * 1000))
        return SafeFetchResponse(response.status_code, response.headers,
                                 body, final_url)

    async def _read_stream(self, response: httpx.Response, prof: Profile
                           ) -> tuple[bytes, int]:
        buf = bytearray()
        decoded = 0
        try:
            async for chunk in response.aiter_bytes(_READ_CHUNK):
                decoded += len(chunk)
                if decoded > prof.max_decompressed:
                    raise SafeFetchError(
                        "decompressed_too_large", "decompress",
                        f"decompressed body exceeds {prof.max_decompressed}")
                if response.num_bytes_downloaded > prof.max_transmitted:
                    raise SafeFetchError(
                        "too_many_bytes", "stream",
                        f"transmitted body exceeds {prof.max_transmitted}")
                buf.extend(chunk)
        except httpx.TimeoutException:
            # Пробрасываем таймаут наверх: `fetch`/`stream_to_file` переводят
            # его в `safe_fetch_timeout` (стадия stream). Не маскируем под
            # обычный client_error.
            raise
        except httpx.HTTPError as exc:
            raise SafeFetchError("client_error", "stream",
                                 f"stream error ({type(exc).__name__})",
                                 retryable=True) from exc
        return bytes(buf), decoded

    async def fetch_text(self, url: str, *, client: httpx.AsyncClient | None = None,
                         profile: str = "html", headers: dict | None = None,
                         max_bytes: int | None = None,
                         timeout: float | None = None,
                         trusted: bool = False) -> str:
        resp = await self.fetch(url, profile=profile, client=client,
                                headers=headers, max_bytes=max_bytes,
                                timeout=timeout, trusted=trusted)
        return resp.text()

    async def fetch_json(self, url: str, *, method: str = "GET",
                         json_body: Any = None, headers: dict | None = None,
                         client: httpx.AsyncClient | None = None,
                         profile: str = "html", trusted: bool = True,
                         max_bytes: int | None = None) -> Any:
        import json as _json
        resp = await self.fetch(url, profile=profile, method=method,
                                json_body=json_body, headers=headers,
                                client=client, trusted=trusted,
                                max_bytes=max_bytes)
        return _json.loads(resp.text())

    async def stream_to_file(self, url: str, dest_path: str, *,
                             profile: str = "video",
                             headers: dict | None = None,
                             client: httpx.AsyncClient | None = None,
                             trusted: bool = False,
                             max_bytes: int | None = None,
                             timeout: float | None = None,
                             progress_cb=None) -> int:
        """Загрузить поток на диск отдельным профилем (HTML-лимит не применён)."""
        prof = _profile(profile, max_bytes=max_bytes, timeout=timeout)
        sem = _semaphore(prof.name, prof.concurrency)
        host_ref = final_url_if(url)
        await self._emit("start", "INFO", host_ref)
        async with sem:
            started = time.monotonic()
            response = None
            written = 0
            failed = True
            try:
                # B-MCA02-1 (SC-06): профильный deadline и для выгрузки на диск.
                async with asyncio.timeout(prof.timeout):
                    response, _ = await self._request(
                        url, profile=prof, method="GET", headers=headers or {},
                        json_body=None, content=None, client=client,
                        trusted=trusted)
                    with open(dest_path, "wb") as fh:
                        async for chunk in response.aiter_bytes(_READ_CHUNK):
                            written += len(chunk)
                            if written > prof.max_decompressed:
                                raise SafeFetchError(
                                    "too_many_bytes", "stream",
                                    f"file exceeds {prof.max_decompressed}")
                            if response.num_bytes_downloaded > prof.max_transmitted:
                                raise SafeFetchError(
                                    "too_many_bytes", "stream",
                                    f"transmitted exceeds {prof.max_transmitted}")
                            fh.write(chunk)
                            if progress_cb is not None:
                                try:
                                    progress_cb({"status": "downloading",
                                                 "downloaded_bytes": written})
                                except Exception:
                                    logger.debug(
                                        "[safe_fetch] progress_cb failed",
                                        exc_info=True)
                failed = False
                await self._emit("success", "INFO", host_ref,
                                 duration_ms=int((time.monotonic() - started)
                                                 * 1000))
                return written
            except SafeFetchError as exc:
                await self._emit_failure(host_ref, exc, started)
                raise
            except (TimeoutError, httpx.TimeoutException) as exc:
                err = SafeFetchError("safe_fetch_timeout", "stream",
                                     "download timeout", retryable=True)
                await self._emit_failure(host_ref, err, started)
                raise err from exc
            finally:
                if response is not None:
                    await response.aclose()
                if failed:
                    # L-MCA02-4: не оставлять частично записанный файл.
                    try:
                        os.unlink(dest_path)
                    except OSError:
                        pass

    @staticmethod
    async def _emit(outcome: str, level: str, host_ref: str,
                    **fields) -> None:
        """Событие MCA-13 (start/terminal outcome); fail-open."""
        try:
            emit_mca_event("safe_fetch", outcome=outcome, level=level,
                           component="safe_fetch", entity_id=host_ref,
                           **fields)
        except Exception:      # события не рвут fetch
            return

    @staticmethod
    async def _emit_failure(host_ref: str, exc: SafeFetchError,
                            started: float) -> None:
        """Событие MCA-13 (terminal outcome) для блокировок/ошибок."""
        await SafeFetcher._emit(
            "failed", "ERROR", host_ref,
            duration_ms=int((time.monotonic() - started) * 1000),
            **exc.to_event_fields())


def final_url_if(url: str) -> str:
    """R17-safe идентификатор цели (host без query) для событий/логов."""
    try:
        parts = urlsplit(str(url))
        return (parts.hostname or "")[:120]
    except Exception:      # pragma: no cover
        return ""


# ── pre-flight для подпроцессов/медиа (D4) ───────────────────────────────────

def guard_subprocess_target(url: str, *, trusted: bool = False) -> str:
    """Pre-flight контроль назначения перед передачей URL в yt-dlp/Cobalt/медиа."""
    return guarded_target(url, trusted=trusted).url


# ── egress-guard: in-process loopback HTTP CONNECT/absolute-URI прокси (D4) ──

class EgressGuard:
    """Минимальный loopback HTTP-прокси, применяющий destination-политику.

    Поддерживает ``CONNECT host:port`` (HTTPS-туннель) и absolute-URI
    (plain HTTP). Каждый таргет проходит ту же SSRF-политику. Опционально
    цепляется к существующему upstream-прокси (``SAFE_FETCH_UPSTREAM_PROXY``),
    чтобы не ломать гео/резидентный доступ.
    """

    _MAX_HEADER_BYTES = 32 * 1024

    def __init__(self) -> None:
        self._server: asyncio.AbstractServer | None = None
        self._port: int | None = None
        self._lock = asyncio.Lock()

    @property
    def url(self) -> str | None:
        return f"http://127.0.0.1:{self._port}" if self._port else None

    @property
    def available(self) -> bool:
        return self._port is not None

    async def start(self) -> str | None:
        async with self._lock:
            if self._port is not None:
                return self.url
            try:
                self._server = await asyncio.start_server(
                    self._handle, "127.0.0.1", 0)
            except OSError:
                logger.warning("[egress_guard] start failed", exc_info=True)
                return None
            self._port = self._server.sockets[0].getsockname()[1]
            logger.info("[egress_guard] listening | port=%d", self._port)
            return self.url

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            except Exception:      # pragma: no cover - shutdown не должен висеть
                pass
            self._server = None
            self._port = None

    async def _read_headers(self, reader: asyncio.StreamReader
                            ) -> tuple[str, list[str], bytes]:
        raw = bytearray()
        line = await reader.readline()
        if not line:
            raise ConnectionError("empty request")
        raw.extend(line)
        request_line = line.decode("latin-1").rstrip("\r\n")
        headers: list[str] = []
        while True:
            line = await reader.readline()
            raw.extend(line)
            if len(raw) > self._MAX_HEADER_BYTES:
                raise ConnectionError("headers too large")
            if line in (b"\r\n", b"\n", b""):
                break
            headers.append(line.decode("latin-1").rstrip("\r\n"))
        return request_line, headers, bytes(raw)

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        try:
            request_line, headers, _ = await self._read_headers(reader)
            parts = request_line.split(" ")
            if len(parts) < 3:
                await self._deny(writer, 400, "bad_request")
                return
            method, target, _version = parts[0], parts[1], parts[2]
            if method.upper() == "CONNECT":
                await self._handle_connect(target, reader, writer)
            else:
                await self._handle_absolute(method, target, headers,
                                            reader, writer)
        except Exception as exc:      # fail-closed для прокси
            logger.warning("[egress_guard] handler error | exc=%s",
                           type(exc).__name__)
        finally:
            try:
                writer.close()
            except Exception:      # pragma: no cover
                pass

    def _check(self, host: str, port: int) -> str | None:
        """Причина блокировки цели (или None). Политика как у SafeFetcher."""
        try:
            guarded_target(f"http://{_hostport(host, port)}/", trusted=False)
        except SafeFetchError as exc:
            return exc.code
        return None

    async def _handle_connect(self, target: str, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter) -> None:
        host, port = _split_hostport(target, default=443)
        reason = self._check(host, port)
        if reason:
            await self._deny(writer, 403, reason)
            return
        try:
            up_reader, up_writer = await _open_upstream(host, port)
        except OSError:
            await self._deny(writer, 502, "connect_failed")
            return
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()
        await _pipe(reader, writer, up_reader, up_writer)

    async def _handle_absolute(self, method: str, target: str,
                               headers: list[str],
                               reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter) -> None:
        try:
            parts = urlsplit(target)
        except ValueError:
            await self._deny(writer, 400, "bad_target")
            return
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        reason = self._check(host, port)
        if reason:
            await self._deny(writer, 403, reason)
            return
        path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
        out_headers = [h for h in headers
                       if not h.lower().startswith(("proxy-connection",
                                                    "connection"))]
        out = bytearray()
        out.extend(f"{method} {path} HTTP/1.1\r\n".encode("latin-1"))
        if not any(h.lower().startswith("host:") for h in out_headers):
            out.extend(f"Host: {_hostport(host, port)}\r\n".encode("latin-1"))
        for h in out_headers:
            out.extend(f"{h}\r\n".encode("latin-1"))
        out.extend(b"Connection: close\r\n\r\n")
        try:
            up_reader, up_writer = await _open_upstream(host, port)
        except OSError:
            await self._deny(writer, 502, "connect_failed")
            return
        up_writer.write(bytes(out))
        await up_writer.drain()
        await _pipe_directional(up_reader, writer)
        up_writer.close()

    @staticmethod
    async def _deny(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
        body = f"blocked: {reason}".encode("latin-1")
        writer.write(
            f"HTTP/1.1 {status} Blocked\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode("latin-1") + body)
        try:
            await writer.drain()
        except Exception:      # pragma: no cover
            pass


def _hostport(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _split_hostport(target: str, default: int) -> tuple[str, int]:
    host, _, port_s = target.rpartition(":")
    if not host:
        return target.strip("[]"), default
    try:
        return host.strip("[]"), int(port_s)
    except ValueError:
        return target.strip("[]"), default


async def _open_upstream(host: str, port: int
                         ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Открыть соединение с целью (напрямую или через upstream-прокси)."""
    upstream = str(getattr(settings, "SAFE_FETCH_UPSTREAM_PROXY", "") or "").strip()
    if upstream:
        up = urlsplit(upstream)
        up_host = up.hostname or ""
        up_port = up.port or 8080
        reader, writer = await asyncio.open_connection(up_host, up_port)
        auth = ""
        if up.username:
            import base64
            token = base64.b64encode(
                f"{up.username}:{up.password or ''}".encode()).decode()
            auth = f"Proxy-Authorization: Basic {token}\r\n"
        writer.write(
            f"CONNECT {_hostport(host, port)} HTTP/1.1\r\n"
            f"Host: {_hostport(host, port)}\r\n{auth}\r\n".encode("latin-1"))
        await writer.drain()
        status_line = await reader.readline()
        if b" 200 " not in status_line:
            writer.close()
            raise OSError(f"upstream proxy refused: "
                          f"{status_line.decode('latin-1').strip()[:40]}")
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        return reader, writer
    return await asyncio.open_connection(host, port)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                up_reader: asyncio.StreamReader,
                up_writer: asyncio.StreamWriter) -> None:
    async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter):
        try:
            while True:
                data = await src.read(_READ_CHUNK)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except Exception:      # pragma: no cover
            pass
        finally:
            # Закрыть приёмник на EOF — иначе keep-alive-туннель висит
            # до бесконечности (важно и для чистого shutdown guard'а).
            try:
                dst.close()
            except Exception:      # pragma: no cover
                pass

    await asyncio.gather(
        _pump(reader, up_writer), _pump(up_reader, writer),
        return_exceptions=True)
    for w in (up_writer, writer):
        try:
            w.close()
        except Exception:      # pragma: no cover
            pass


async def _pipe_directional(reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(_READ_CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:      # pragma: no cover
        pass


_guard: EgressGuard | None = None
_guard_loop: object | None = None


def get_egress_guard() -> EgressGuard:
    global _guard
    if _guard is None:
        _guard = EgressGuard()
    return _guard


async def ensure_egress_guard() -> str | None:
    """Запустить egress-guard (loopback) и вернуть proxy-URL (или None).

    Guard привязан к текущему event loop (пересоздаётся при смене loop —
    важно для тестов; в проде loop один)."""
    global _guard, _guard_loop
    if not mca_gates.egress_guard_enabled():
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:      # pragma: no cover - нет loop
        return None
    if _guard is None or _guard_loop is not loop:
        _guard = EgressGuard()
        _guard_loop = loop
    url = await _guard.start()
    if url is None:
        emit_mca_event("safe_fetch", outcome="failed", level="WARN",
                       component="egress_guard",
                       reason_code="egress_guard_unavailable")
    return url


def egress_proxy_url() -> str | None:
    """Proxy-URL guard'а, если он уже запущен (никогда не бросает)."""
    if not mca_gates.egress_guard_enabled():
        return None
    guard = _guard
    return guard.url if guard is not None and guard.available else None


def apply_egress_proxy(url: str | None = None) -> str | None:
    """Proxy для httpx/aiohttp-клиентов (guard или None при OFF/недоступности)."""
    return url or egress_proxy_url()


def apply_egress_to_ytdlp_opts(opts: dict) -> dict:
    """Добавить egress-guard в yt-dlp opts (если включён и не задан свой proxy).

    Существующий ``proxy`` (гео/резидентный) НЕ перезаписывается; в этом случае
    остаётся pre-flight контроль (честный residual risk)."""
    proxy = egress_proxy_url()
    if proxy and not (opts.get("proxy") or "").strip():
        opts["proxy"] = proxy
    return opts
