"""EVOL-SRC-READER — проверенное чтение исходного кода (discovery → locator →
verified fetch → bounded follow-up → evidence contract).

Источник: `plans/current_task.md` §1 (строки 1176–1236), архитектурный контракт
`plans/features/evol/arch/source-reader-contract.md`.

Что здесь есть и чего здесь НЕТ:

* **один** инструмент `read_source_code` с тремя операциями
  (``discover|locate|read``) — второго LLM-инструмента/пайплайна не создаётся;
* транспорт — строго существующий ``services.safe_fetch.SafeFetcher`` (SSRF,
  редиректы, лимиты байтов/времени, R17-маскирование). Второго HTTP-клиента,
  второго набора секретов и второго transport-контура здесь нет;
* провайдер сейчас ровно один — GitHub. Остальные хостинги честно
  ``unsupported``/``provider_unconfigured`` (никаких заявлений о поддержке);
* ``verified=true`` выдаётся ТОЛЬКО по реальным байтам файла, привязанным к
  конкретному commit (инвариант V1): HTTP 200 для точной идентичности
  ``(repo, commit, path)``, непустые декодированные байты, ``line_range``
  вычислен из этих байт, ``snippet`` — их точная подстрока, ``verified_url``
  содержит commit, ``source_kind == "file"``;
* никакого исполнения скачанного кода: в модуле нет ``exec/eval/importlib/
  subprocess`` (тест-инвариант), код только декодируется и режется по строкам;
* телеметрия — существующий стадийный эмиттер
  ``mca_retrieval_context.emit_stage_event``, коды — только существующие
  значения ``mca_events.REASON_CODES`` (0 новых кодов);
* никаких жёстких словарей имён проектов/пакетов/веток: разбор ссылок идёт по
  ФОРМЕ URL, локатор — по дереву репозитория и по синтаксическим формам строки,
  ранжирование discovery — по полям ответа API.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

from config.settings import settings
from services.safe_fetch import SafeFetchError

logger = logging.getLogger(__name__)

# ── статусы payload (закрытый набор контракта §1.1) ─────────────────────────
STATUS_OK = "ok"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NOT_FOUND = "not_found"
STATUS_UNSUPPORTED = "unsupported"
STATUS_ERROR = "error"
STATUSES = frozenset({STATUS_OK, STATUS_AMBIGUOUS, STATUS_NOT_FOUND,
                      STATUS_UNSUPPORTED, STATUS_ERROR})

# ── стадии (§1.2.5: стадии различимы в диагностике) ─────────────────────────
STAGE_DISCOVER = "discover"
STAGE_LOCATOR = "locator"
STAGE_FETCH = "fetch"
STAGE_FOLLOWUP = "followup"
STAGES = frozenset({STAGE_DISCOVER, STAGE_LOCATOR, STAGE_FETCH, STAGE_FOLLOWUP})

# ── операции инструмента (§1.2: одна возможность, три операции) ──────────────
OPERATION_DISCOVER = "discover"
OPERATION_LOCATE = "locate"
OPERATION_READ = "read"
OPERATIONS = (OPERATION_DISCOVER, OPERATION_LOCATE, OPERATION_READ)

# ── виды источника (§3: только `file` может стать `verified`) ────────────────
KIND_FILE = "file"
KIND_DIRECTORY = "directory"
KIND_REPO = "repo"
KIND_README = "readme"
KIND_ISSUE = "issue"
KIND_PULL = "pull"
KIND_RELEASE = "release"
KIND_OTHER = "other"

# ── провайдер/эндпоинты (id вызова, НЕ URL с токенами) ──────────────────────
PROVIDER_GITHUB = "github"
PROVIDER_NAME = PROVIDER_GITHUB
ENDPOINT_SEARCH = "search.repositories"
ENDPOINT_REPO = "repos"
ENDPOINT_COMMITS = "commits"
ENDPOINT_TREE = "tree"
ENDPOINT_CONTENTS = "contents"
ENDPOINT_BLOBS = "blobs"
ENDPOINT_RAW = "raw"

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
HTML_BASE = "https://github.com"

#: Поддержанные хостинги — проверка по hostname нормализованного URL
#: (защита от `github.com.evil.tld`), а не по строке.
SUPPORTED_HOSTS = frozenset({"github.com", "raw.githubusercontent.com",
                             "api.github.com"})

# ── коды отказов (§5; 0 новых значений REASON_CODES) ────────────────────────
ERR_SOURCE_MISSING = "source_missing"
ERR_RATE_LIMIT = "rate_limit"
ERR_AUTH_FAILED = "auth_failed"
ERR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERR_TIMEOUT = "safe_fetch_timeout"
ERR_PARSE = "parse_error"
ERR_NO_RESULTS = "no_relevant_results"
ERR_PROVIDER_UNCONFIGURED = "provider_unconfigured"
ERR_DISABLED = "disabled"
ERR_INVALID_URL = "invalid_url"
ERR_UNSUPPORTED_KIND = "unsupported"
#: Пустой файл — это НЕ «файла нет»: отдельная машинная причина.
ERR_EMPTY_CONTENT = "empty_content"

#: payload-код → существующий `mca_events.REASON_CODES` (§5):
#: `no_relevant_results` — payload-код, в словаре ему соответствует
#: `retrieval_empty` (тот же канон, что `evidence_policy`).
_REASON_FOR_CODE = {
    ERR_SOURCE_MISSING: "source_missing",
    ERR_RATE_LIMIT: "rate_limit",
    ERR_AUTH_FAILED: "auth_failed",
    ERR_PROVIDER_UNAVAILABLE: "provider_unavailable",
    ERR_TIMEOUT: "safe_fetch_timeout",
    ERR_PARSE: "parse_error",
    ERR_NO_RESULTS: "retrieval_empty",
    ERR_PROVIDER_UNCONFIGURED: "provider_unconfigured",
    ERR_DISABLED: "disabled",
    ERR_INVALID_URL: "invalid_url",
    # «Форма ответа, которую нельзя использовать как код» (каталог, symlink,
    # submodule, не-UTF-8/бинарь) — существующий код класса parser/битого
    # ответа. Значения `capability_not_ready` в `mca_events.REASON_CODES` НЕТ,
    # поэтому оно здесь не используется (0 новых кодов).
    ERR_UNSUPPORTED_KIND: "parse_error",
}

# ── предохранители (потолки — контракт §4) ──────────────────────────────────
_MAX_FILES_CEILING = 6
_MAX_DEPTH_CEILING = 2
_MAX_REQUESTS_CEILING = 16
_DEFAULT_MAX_FILES = 3
_DEFAULT_MAX_DEPTH = 1
_DEFAULT_MAX_REQUESTS = 8
_DEFAULT_MAX_FILE_BYTES = 2_000_000

#: Сколько кандидатов «самый длинный ref первым» проверять при разборе
#: `/blob/…`-ссылки (контракт §2: ≤4 проверки `contents?ref=`).
_MAX_REF_CANDIDATES = 4
#: Сколько кандидатов-репозиториев показывать при неоднозначности (§3: ≤3).
_MAX_CANDIDATES = 3
#: Сколько путей-кандидатов отбирает локатор (§3: ≤3).
_MAX_LOCATOR_PATHS = 3


# ── env-only конфигурация (прецедент `ARTICLE_TOOL_ENABLED`) ────────────────

def source_read_enabled() -> bool:
    """Kill-switch ``SOURCE_READ_ENABLED`` (env-only, default ON)."""
    try:
        return bool(getattr(settings, "SOURCE_READ_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _bounded_int(name: str, default: int, ceiling: int) -> int:
    """env-целое с потолком: мусор/0/минус → дефолт, больше потолка → потолок."""
    try:
        value = int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
    if value <= 0:
        return default
    return min(value, ceiling)


def max_files() -> int:
    return _bounded_int("SOURCE_READ_MAX_FILES", _DEFAULT_MAX_FILES,
                        _MAX_FILES_CEILING)


def max_depth() -> int:
    return _bounded_int("SOURCE_READ_MAX_DEPTH", _DEFAULT_MAX_DEPTH,
                        _MAX_DEPTH_CEILING)


def max_requests() -> int:
    return _bounded_int("SOURCE_READ_MAX_REQUESTS", _DEFAULT_MAX_REQUESTS,
                        _MAX_REQUESTS_CEILING)


def max_file_bytes() -> int:
    return _bounded_int("SOURCE_READ_MAX_FILE_BYTES", _DEFAULT_MAX_FILE_BYTES,
                        64 * 1024 * 1024)


def github_token() -> str:
    """Опциональная авторизация: только env, значение никогда не логируется."""
    try:
        return str(getattr(settings, "SOURCE_READ_GITHUB_TOKEN", "") or "").strip()
    except Exception:      # pragma: no cover - защитная ветка
        return ""


# ── отказ провайдера (структурный, без свободного текста наружу) ─────────────

class SourceFetchError(Exception):
    """Отказ source-endpoint: код/стадия/http/retryable/detail (R17-safe).

    ``detail`` — закрытый машинный тег (``host_not_supported``, ``symlink``…),
    никогда не URL и не текст ответа."""

    def __init__(self, code: str, stage: str = STAGE_FETCH, *,
                 http: int = 0, retryable: bool = False,
                 detail: str = "") -> None:
        self.code = str(code or ERR_PROVIDER_UNAVAILABLE)
        self.stage = stage if stage in STAGES else STAGE_FETCH
        self.http = int(http or 0)
        self.retryable = bool(retryable)
        self.detail = str(detail or "")[:60]
        super().__init__(f"code={self.code} | stage={self.stage} | "
                         f"http={self.http} | detail={self.detail}")

    @property
    def reason_code(self) -> str:
        return _REASON_FOR_CODE.get(self.code, self.code)

    def to_payload(self) -> dict:
        return {"code": self.code, "stage": self.stage, "http": self.http,
                "retryable": self.retryable, "detail": self.detail}


# ── структуры данных провайдера ─────────────────────────────────────────────

@dataclass(frozen=True)
class RepoInfo:
    """Репозиторий как его отдаёт провайдер (никаких выдуманных полей)."""

    owner: str
    name: str
    default_branch: str = ""
    language: str = ""
    stars: int = 0
    description: str = ""
    pushed_at: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html_url(self) -> str:
        return f"{HTML_BASE}/{self.full_name}"

    def as_candidate(self) -> dict:
        return {"repo": self.full_name, "stars": int(self.stars or 0),
                "language": self.language, "description": self.description,
                "url": self.html_url}


@dataclass(frozen=True)
class TreeEntry:
    path: str
    kind: str = "blob"          # blob|tree|commit (как отдаёт API)
    sha: str = ""
    size: int = 0


@dataclass
class TreeListing:
    entries: list[TreeEntry] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class SourceFile:
    """Байты файла + провенанс (``endpoint`` — id вызова, не URL)."""

    path: str
    data: bytes
    sha: str = ""
    size: int = 0
    endpoint: str = ENDPOINT_CONTENTS


# ── разбор ссылок (по ФОРМЕ URL, без словарей имён) ─────────────────────────

_LINE_FRAGMENT_RE = re.compile(r"^L(\d+)(?:-L?(\d+))?$", re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_README_RE = re.compile(r"^readme(?:$|[._-])", re.IGNORECASE)
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class ParsedSourceUrl:
    """Разобранная ссылка: форма URL → (host, repo, вид, ref/path кандидаты)."""

    host: str
    supported: bool = True
    owner: str = ""
    repo: str = ""
    kind: str = KIND_OTHER
    ref: str = ""
    path: str = ""
    commit: str = ""
    line_start: int | None = None
    line_end: int | None = None
    #: (ref, path) — «самый длинный ref первым» (§2: слэши в названии ветки).
    ref_path_candidates: tuple[tuple[str, str], ...] = ()

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}" if self.owner and self.repo else ""


def _fragment_range(fragment: str) -> tuple[int | None, int | None]:
    match = _LINE_FRAGMENT_RE.match(str(fragment or "").strip())
    if not match:
        return (None, None)
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if start < 1 or end < start:
        return (None, None)
    return (start, end)


def _ref_path_candidates(segments: list[str]) -> tuple[tuple[str, str], ...]:
    """Разбить хвост `/blob/<ref…>/<path>` на кандидатов (ref, path).

    Порядок — от самого КОРОТКОГО ref к длинному, максимум ``_MAX_REF_CANDIDATES``
    проверок. Почему не «самый длинный первым»: буквальное требование ТЗ —
    «правильно разрешать ветки, в названиях которых есть ``/``» (строка 1198),
    и оно выполняется при любом порядке («первый 200 = истина»); при порядке
    «длинный первым» обычная ссылка `blob/<branch>/<глубокий путь>` тратила бы
    до 4 запросов впустую на часовой квоте GitHub (60/час, риск R2), а ветка
    со слэшем при коротком порядке стоит ровно одну лишнюю пробу."""
    out: list[tuple[str, str]] = []
    for split in range(1, len(segments)):
        ref = "/".join(segments[:split])
        path = "/".join(segments[split:])
        if not ref or not path:
            continue
        out.append((ref, path))
        if len(out) >= _MAX_REF_CANDIDATES:
            break
    return tuple(out)


def _kind_for_path(path: str) -> str:
    """Вид источника по форме пути: README — документация, не исходник."""
    name = path.rsplit("/", 1)[-1] if path else ""
    return KIND_README if _README_RE.match(name or "") else KIND_FILE


def parse_source_url(url: Any) -> ParsedSourceUrl | None:
    """Разобрать ссылку на источник. Не бросает; None — это не URL вообще."""
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if (parts.scheme or "").lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    line_start, line_end = _fragment_range(parts.fragment)
    segments = [unquote(seg) for seg in parts.path.split("/") if seg]
    if host not in SUPPORTED_HOSTS:
        return ParsedSourceUrl(host=host, supported=False)
    if host == "api.github.com":
        # /repos/{o}/{r}/contents/{path}?ref=… (ref в query — слэши безопасны)
        if (len(segments) >= 4 and segments[0] == "repos"
                and segments[3] in ("contents", "blobs")):
            owner, repo = segments[1], segments[2]
            tail = segments[4:] if len(segments) > 4 else []
            path = "/".join(tail)
            ref = ""
            for pair in str(parts.query or "").split("&"):
                key, _, value = pair.partition("=")
                if key == "ref" and value:
                    ref = unquote(value)
            return ParsedSourceUrl(
                host="github.com", owner=owner, repo=repo,
                kind=_kind_for_path(path) if path else KIND_REPO,
                ref=ref, path=path,
                commit=ref if _HEX_RE.match(ref) else "",
                line_start=line_start, line_end=line_end,
                ref_path_candidates=((ref, path),) if ref and path else ())
        return ParsedSourceUrl(host="github.com", kind=KIND_OTHER)
    if host == "raw.githubusercontent.com":
        if len(segments) < 4:
            return ParsedSourceUrl(host=host, owner=(segments[0] if segments
                                                     else ""),
                                   repo=(segments[1] if len(segments) > 1
                                         else ""),
                                   kind=KIND_OTHER)
        owner, repo = segments[0], segments[1]
        candidates = _ref_path_candidates(segments[2:])
        ref, path = candidates[0] if candidates else ("", "")
        return ParsedSourceUrl(
            host="github.com", owner=owner, repo=repo,
            kind=_kind_for_path(path), ref=ref, path=path,
            commit=ref if _HEX_RE.match(ref) else "",
            line_start=line_start, line_end=line_end,
            ref_path_candidates=candidates)
    # github.com
    if len(segments) < 2:
        return ParsedSourceUrl(host=host, kind=KIND_OTHER)
    owner, repo, rest = segments[0], segments[1], segments[2:]
    if not rest:
        return ParsedSourceUrl(host=host, owner=owner, repo=repo,
                               kind=KIND_REPO, line_start=line_start,
                               line_end=line_end)
    head = rest[0].lower()
    if head in ("blob", "raw"):
        candidates = _ref_path_candidates(rest[1:])
        ref, path = candidates[0] if candidates else ("", "")
        return ParsedSourceUrl(
            host=host, owner=owner, repo=repo, kind=_kind_for_path(path),
            ref=ref, path=path,
            commit=ref if _HEX_RE.match(ref) else "",
            line_start=line_start, line_end=line_end,
            ref_path_candidates=candidates)
    if head == "tree":
        candidates = _ref_path_candidates(rest[1:]) if len(rest) > 1 else ()
        ref = candidates[0][0] if candidates else ""
        return ParsedSourceUrl(
            host=host, owner=owner, repo=repo, kind=KIND_DIRECTORY,
            ref=ref, path=("/".join(candidates[0][1].split("/")[:-1])
                           if candidates and candidates[0][1] else ""),
            commit=ref if _HEX_RE.match(ref) else "",
            line_start=line_start, line_end=line_end,
            ref_path_candidates=candidates)
    if head in ("issues", "pull", "releases", "wiki", "discussions"):
        kind = {"issues": KIND_ISSUE, "pull": KIND_PULL,
                "releases": KIND_RELEASE}.get(head, KIND_OTHER)
        return ParsedSourceUrl(host=host, owner=owner, repo=repo, kind=kind,
                               line_start=line_start, line_end=line_end)
    return ParsedSourceUrl(host=host, owner=owner, repo=repo, kind=KIND_OTHER,
                           line_start=line_start, line_end=line_end)


def parse_repo_spec(spec: Any) -> tuple[str, str] | None:
    """``"owner/name"`` (или ссылка на репозиторий) → (owner, name)."""
    text = str(spec or "").strip().strip("/")
    if not text:
        return None
    if "://" in text or text.lower().startswith(("github.com/", "www.")):
        parsed = parse_source_url(text if "://" in text
                                  else f"https://{text}")
        if parsed is not None and parsed.owner and parsed.repo:
            name = parsed.repo[:-4] if parsed.repo.endswith(".git") \
                else parsed.repo
            return (parsed.owner, name)
        return None
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[-2]
    name = parts[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return (owner, name) if owner and name else None


# ── провайдер (Protocol) и единственная реализация — GitHub ──────────────────

class SourceProvider(Protocol):
    """Граница провайдера (контракт §2): только эти методы, все async."""

    name: str

    async def search_repos(self, query: str, *,
                           limit: int = 5) -> list[RepoInfo]: ...

    async def resolve_repo(self, owner: str, repo: str
                           ) -> RepoInfo | None: ...

    async def resolve_commit(self, repo: str, ref: str) -> str | None: ...

    async def list_tree(self, repo: str, commit: str) -> TreeListing | None: ...

    async def read_file(self, repo: str, commit: str, path: str,
                        *, blob_sha: str = "") -> SourceFile | None: ...


def _classify_http_status(status: int, headers) -> str:
    """HTTP-статус → закрытый код отказа (§5). ``""`` — успех."""
    code = int(status or 0)
    if code in (404, 410):
        return ERR_SOURCE_MISSING
    if code in (401, 403, 429):
        remaining = ""
        retry_after = ""
        try:
            remaining = str(headers.get("x-ratelimit-remaining", "") or "")
            retry_after = str(headers.get("retry-after", "") or "")
        except Exception:      # pragma: no cover - защитная ветка
            remaining = retry_after = ""
        if code == 429 or remaining.strip() == "0" or retry_after.strip():
            return ERR_RATE_LIMIT
        return ERR_AUTH_FAILED
    if code >= 500:
        return ERR_PROVIDER_UNAVAILABLE
    if code >= 400:
        return ERR_PROVIDER_UNAVAILABLE
    return ""


class GitHubProvider:
    """GitHub через существующий ``SafeFetcher`` (второго транспорта нет).

    Эндпоинты: ``search.repositories`` / ``repos`` / ``commits`` / ``tree`` /
    ``contents`` / ``blobs`` / ``raw``. ``/search/code`` намеренно не
    используется (требует аутентификации и отдаёт только default-ветку)."""

    name = PROVIDER_GITHUB

    def __init__(self, fetcher=None, *, token: str = "",
                 max_bytes: int | None = None) -> None:
        self._fetcher = fetcher
        self._token = str(token or "").strip()
        self._max_bytes = int(max_bytes or max_file_bytes())
        #: сколько сетевых вызовов реально сделано (наблюдаемость/reuse=0)
        self.network_calls = 0
        #: последний использованный endpoint (id вызова, не URL)
        self.last_endpoint = ""

    @property
    def uses_auth(self) -> bool:
        """Авторизация использована (возможен приватный доступ → scope=chat)."""
        return bool(self._token)

    @property
    def fetcher(self):
        if self._fetcher is None:
            from services.safe_fetch import SafeFetcher
            self._fetcher = SafeFetcher()
        return self._fetcher

    def _headers(self) -> dict:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            # Значение токена не попадает ни в логи, ни в события, ни в payload.
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _count(self, endpoint: str) -> None:
        self.network_calls += 1
        self.last_endpoint = endpoint

    async def _fetch(self, url: str, *, endpoint: str, want_bytes: bool = False):
        """Один вызов существующего SafeFetcher + классификация отказа."""
        self._count(endpoint)
        try:
            response = await self.fetcher.fetch(
                url, profile="html", headers=self._headers(), trusted=False,
                max_bytes=self._max_bytes,
                timeout=float(getattr(settings, "SAFE_FETCH_HTML_TIMEOUT_SECONDS",
                                      10.0) or 10.0))
        except SafeFetchError as exc:
            # SSRF/редирект/схема/размер/таймаут — код существующего контура.
            raise SourceFetchError(exc.code, STAGE_FETCH,
                                   retryable=bool(exc.retryable),
                                   detail=str(exc.stage or "")[:40]) from exc
        except Exception as exc:      # pragma: no cover - транспорт не бросает
            raise SourceFetchError(ERR_PROVIDER_UNAVAILABLE, STAGE_FETCH,
                                   retryable=True,
                                   detail=type(exc).__name__) from exc
        code = _classify_http_status(response.status_code, response.headers)
        if code:
            raise SourceFetchError(
                code, STAGE_FETCH, http=int(response.status_code),
                retryable=code in (ERR_RATE_LIMIT, ERR_PROVIDER_UNAVAILABLE))
        if want_bytes:
            return response.content
        return response

    async def _get_json(self, url: str, *, endpoint: str):
        response = await self._fetch(url, endpoint=endpoint)
        body = response.content or b""
        if not body.strip():
            raise SourceFetchError(ERR_PARSE, STAGE_FETCH,
                                   http=int(response.status_code),
                                   detail="empty_body")
        try:
            return json.loads(body.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, ValueError) as exc:
            # HTML вместо кода / битый JSON — честный parse_error, не «нет файла».
            raise SourceFetchError(ERR_PARSE, STAGE_FETCH,
                                   http=int(response.status_code),
                                   detail="invalid_json") from exc

    # -- SourceProvider -------------------------------------------------
    async def search_repos(self, query: str, *,
                           limit: int = 5) -> list[RepoInfo]:
        from urllib.parse import quote_plus
        text = str(query or "").strip()
        if not text:
            return []
        url = (f"{API_BASE}/search/repositories?q={quote_plus(text)}"
               f"&per_page={max(1, min(int(limit or 5), 10))}")
        payload = await self._get_json(url, endpoint=ENDPOINT_SEARCH)
        items = payload.get("items") if isinstance(payload, dict) else None
        out: list[RepoInfo] = []
        for item in items or []:
            info = _repo_from_api(item)
            if info is not None:
                out.append(info)
        return out

    async def resolve_repo(self, owner: str, repo: str) -> RepoInfo | None:
        if not owner or not repo:
            return None
        try:
            payload = await self._get_json(
                f"{API_BASE}/repos/{owner}/{repo}", endpoint=ENDPOINT_REPO)
        except SourceFetchError as exc:
            if exc.code == ERR_SOURCE_MISSING:
                return None
            raise
        return _repo_from_api(payload)

    async def resolve_commit(self, repo: str, ref: str) -> str | None:
        """ref → 40-hex commit. ``ref`` уходит в **query** (слэши безопасны)."""
        if not repo:
            return None
        from urllib.parse import quote
        suffix = f"?sha={quote(str(ref or ''), safe='')}&per_page=1"
        try:
            payload = await self._get_json(
                f"{API_BASE}/repos/{repo}/commits{suffix}",
                endpoint=ENDPOINT_COMMITS)
        except SourceFetchError as exc:
            if exc.code == ERR_SOURCE_MISSING:
                return None
            raise
        commit = ""
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                commit = str(first.get("sha") or "")
        elif isinstance(payload, dict):
            commit = str(payload.get("sha") or "")
        commit = commit.strip().lower()
        return commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None

    async def list_tree(self, repo: str, commit: str) -> TreeListing | None:
        """Дерево по commit (path-параметр = 40-hex, слэшей нет)."""
        if not repo or not commit:
            return None
        payload = await self._get_json(
            f"{API_BASE}/repos/{repo}/git/trees/{commit}?recursive=1",
            endpoint=ENDPOINT_TREE)
        if not isinstance(payload, dict):
            return None
        entries: list[TreeEntry] = []
        for item in payload.get("tree") or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path:
                continue
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            entries.append(TreeEntry(path=path,
                                     kind=str(item.get("type") or "blob"),
                                     sha=str(item.get("sha") or ""),
                                     size=size))
        return TreeListing(entries=entries,
                           truncated=bool(payload.get("truncated")))

    async def read_file(self, repo: str, commit: str, path: str,
                        *, blob_sha: str = "") -> SourceFile | None:
        """Байты файла для точной идентичности ``(repo, commit, path)``.

        Порядок (контракт §8): ``blobs`` (если sha уже известен из дерева) →
        ``contents?ref=<commit>`` → ``raw``. Каждый шаг — свой
        ``provenance.endpoint``; 404 на шаге — переход к следующему."""
        if not repo or not commit or not path:
            return None
        from urllib.parse import quote
        encoded = quote(path, safe="/")
        last_error: SourceFetchError | None = None
        if blob_sha:
            file = await self._read_blob(repo, blob_sha, path)
            if file is not None:
                return file
        try:
            contents = await self._read_contents(repo, commit, encoded, path)
        except SourceFetchError as exc:
            if exc.code != ERR_SOURCE_MISSING:
                last_error = exc
            contents = None
        if contents is not None:
            if contents.data:
                return contents
            # содержимое не вложено (файл > 1 MB) — берём blobs по sha.
            if contents.size and contents.sha:
                file = await self._read_blob(repo, contents.sha, path)
                if file is not None:
                    return file
            # size == 0 и байтов нет: файл действительно пуст. Возвращаем его
            # как есть — вызывающий отдаст честный `unsupported/empty_content`,
            # а не «файла нет».
            return contents
        raw_file = None
        try:
            raw_file = await self._read_raw(repo, commit, encoded, path)
        except SourceFetchError as exc:
            if exc.code != ERR_SOURCE_MISSING:
                last_error = exc
        if raw_file is not None:
            return raw_file
        if last_error is not None:
            # Причина отказа содержимого не маскируется «файла нет»: сначала
            # была содержательная ошибка (например path_mismatch), и честно
            # возвращается именно она.
            raise last_error
        return None

    async def _read_blob(self, repo: str, sha: str,
                         path: str) -> SourceFile | None:
        try:
            payload = await self._get_json(
                f"{API_BASE}/repos/{repo}/git/blobs/{sha}",
                endpoint=ENDPOINT_BLOBS)
        except SourceFetchError as exc:
            if exc.code == ERR_SOURCE_MISSING:
                return None
            raise
        if not isinstance(payload, dict):
            raise SourceFetchError(ERR_PARSE, STAGE_FETCH, detail="blob_shape")
        data = _decode_base64(payload.get("content"))
        return SourceFile(path=path, data=data, sha=str(payload.get("sha") or sha),
                          size=int(payload.get("size") or len(data) or 0),
                          endpoint=ENDPOINT_BLOBS)

    async def _read_contents(self, repo: str, commit: str, encoded: str,
                             path: str) -> SourceFile | None:
        payload = await self._get_json(
            f"{API_BASE}/repos/{repo}/contents/{encoded}?ref={commit}",
            endpoint=ENDPOINT_CONTENTS)
        if isinstance(payload, list):
            raise SourceFetchError(ERR_UNSUPPORTED_KIND, STAGE_FETCH,
                                   detail="path_is_directory")
        if not isinstance(payload, dict):
            raise SourceFetchError(ERR_PARSE, STAGE_FETCH,
                                   detail="contents_shape")
        kind = str(payload.get("type") or "file")
        if kind in ("symlink", "submodule"):
            # Наружу не разворачиваем: symlink/submodule — честный unsupported.
            raise SourceFetchError(ERR_UNSUPPORTED_KIND, STAGE_FETCH,
                                   detail=kind)
        api_path = str(payload.get("path") or "").strip("/")
        if api_path and api_path != str(path or "").strip("/"):
            # Ответ описывает ДРУГОЙ путь: точная идентичность (repo, commit,
            # path) не подтверждена → это не наше чтение (V1.1), не verified.
            raise SourceFetchError(ERR_PARSE, STAGE_FETCH,
                                   detail="path_mismatch")
        data = _decode_base64(payload.get("content"))
        try:
            size = int(payload.get("size") or len(data) or 0)
        except (TypeError, ValueError):
            size = len(data)
        return SourceFile(path=path, data=data,
                          sha=str(payload.get("sha") or ""), size=size,
                          endpoint=ENDPOINT_CONTENTS)

    async def _read_raw(self, repo: str, commit: str, encoded: str,
                        path: str) -> SourceFile | None:
        try:
            body = await self._fetch(
                f"{RAW_BASE}/{repo}/{commit}/{encoded}",
                endpoint=ENDPOINT_RAW, want_bytes=True)
        except SourceFetchError as exc:
            if exc.code == ERR_SOURCE_MISSING:
                return None
            raise
        return SourceFile(path=path, data=bytes(body or b""),
                          sha="", size=len(body or b""),
                          endpoint=ENDPOINT_RAW)


def _repo_from_api(payload) -> RepoInfo | None:
    """Ответ API → RepoInfo (только реальные поля ответа)."""
    if not isinstance(payload, dict):
        return None
    full = str(payload.get("full_name") or "").strip()
    owner = str(payload.get("owner", {}).get("login")
                if isinstance(payload.get("owner"), dict) else "") or ""
    name = str(payload.get("name") or "")
    if not full and owner and name:
        full = f"{owner}/{name}"
    if "/" not in full:
        return None
    owner, _, name = full.partition("/")
    if not owner or not name:
        return None
    try:
        stars = int(payload.get("stargazers_count") or 0)
    except (TypeError, ValueError):
        stars = 0
    return RepoInfo(owner=owner, name=name,
                    default_branch=str(payload.get("default_branch") or ""),
                    language=str(payload.get("language") or ""),
                    stars=stars,
                    description=str(payload.get("description") or "")[:200],
                    pushed_at=str(payload.get("pushed_at") or ""))


def _decode_base64(raw) -> bytes:
    """GitHub contents/blobs: base64 с переносами строк."""
    text = str(raw or "")
    if not text:
        return b""
    compact = "".join(text.split())
    try:
        return base64.b64decode(compact, validate=False)
    except (ValueError, TypeError) as exc:      # pragma: no cover - защита
        raise SourceFetchError(ERR_PARSE, STAGE_FETCH,
                               detail="invalid_base64") from exc


# ── текстовые помощники: строки, окно, проверки (без исполнения кода) ────────

_LANGUAGE_BY_EXT = {
    ".java": "java", ".kt": "kotlin", ".py": "python", ".js": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".c": "c", ".h": "c", ".hpp": "cpp", ".cc": "cpp", ".cpp": "cpp",
    ".scala": "scala", ".swift": "swift", ".m": "objective-c", ".lua": "lua",
}

#: Расширения, которые считаются исходниками (по форме расширения, не по
#: именам проектов/файлов примера).
_SOURCE_EXTS = frozenset(_LANGUAGE_BY_EXT)


def language_for_path(path: str) -> str:
    name = str(path or "").rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return _LANGUAGE_BY_EXT.get(name[dot:].lower(), "") if dot >= 0 else ""


@dataclass(frozen=True)
class DecodedSource:
    """Результат строгого декодирования байт источника.

    ``ok=False`` — это НЕ «файла нет»: байты получены, но это не текст
    исходника (не-UTF-8 или служебные/бинарные байты). Причина — закрытый
    машинный тег, наружу отдаётся как ``reason``/``detail``."""

    text: str = ""
    ok: bool = False
    reason: str = ""


#: Доля служебных символов, выше которой содержимое считается бинарным.
#: Считаются только управляющие символы, НЕ являющиеся текстовыми
#: (`\t`, `\n`, `\r` — легальные байты исходника, включая CRLF).
_MAX_CONTROL_RATIO = 0.02
_TEXT_CONTROLS = frozenset({"\t", "\n", "\r", "\f", "\v"})


def decode_source_bytes(data: bytes) -> DecodedSource:
    """Строгое декодирование источника: UTF-8 без откатов и без «бинарного ok».

    Правило (V1.2): ``verified`` возможен только для текста, декодированного
    строго как UTF-8 и не состоящего из служебных/бинарных байтов. Latin-1 и
    прочие «всеядные» декодеры не используются: они превращают PNG/архив в
    «код» с NUL-ами. Не-UTF-8 и бинарь → честный ``ok=False`` с причиной."""
    if not data:
        return DecodedSource(reason="empty_content")
    # NUL в сырых байтах — однозначный бинарь: отдельная причина честнее
    # «invalid_encoding» (PNG/архив/исполняемый файл).
    if b"\x00" in data:
        return DecodedSource(reason="binary_content")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return DecodedSource(reason="invalid_encoding")
    controls = 0
    for char in text:
        if char in _TEXT_CONTROLS:
            continue
        code = ord(char)
        if code < 0x20 or code == 0x7F:
            controls += 1
    if controls and controls / max(1, len(text)) > _MAX_CONTROL_RATIO:
        return DecodedSource(reason="binary_content")
    return DecodedSource(text=text, ok=True)


def decode_file_text(data: bytes) -> str:
    """Текст источника или ``""`` (тонкая обёртка над строгим правилом)."""
    return decode_source_bytes(data).text


def split_lines(text: str) -> list[str]:
    """Строки файла: разделитель — только ``\\n``, ``\\r`` сохраняется.

    ``str.splitlines()`` здесь непригоден: он съедает ``\\r``, и любой
    CRLF-исходник переставал быть «точным фрагментом» реальных байт (ложный
    ``verified=false``). Завершающий перевод строки не создаёт лишнюю строку."""
    if not text:
        return []
    parts = text.split("\n")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    return parts


def line_spans(text: str) -> list[tuple[int, int]]:
    """Смещения (start, end) каждой строки в исходном тексте (без ``\\n``).

    ``end`` включает ``\\r`` для CRLF-файла: срез по смещениям даёт ровно те
    байты, что были в файле."""
    spans: list[tuple[int, int]] = []
    offset = 0
    for line in split_lines(text):
        spans.append((offset, offset + len(line)))
        offset += len(line) + 1
    return spans


def strip_line_ending(line: str) -> str:
    """Строка без хвостового ``\\r`` — только для синтаксического разбора."""
    return line[:-1] if line.endswith("\r") else line



def locate_symbol_line(lines: list[str], symbol: str) -> int:
    """1-based номер первой строки, где символ встречается целым словом."""
    token = str(symbol or "").strip()
    if not token:
        return 0
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(token)
                         + r"(?![A-Za-z0-9_])")
    for index, line in enumerate(lines, start=1):
        if pattern.search(strip_line_ending(line)):
            return index
    return 0


def symbol_occurrences(lines: list[str], symbol: str) -> list[int]:
    token = str(symbol or "").strip()
    if not token:
        return []
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(token)
                         + r"(?![A-Za-z0-9_])")
    return [index for index, line in enumerate(lines, start=1)
            if pattern.search(strip_line_ending(line))]


#: Формы строки, при которых символ «только выставляет параметр» (§4, §1.2.4):
#: объявление поля, присваивание, параметр конструктора/метода. Проверка —
#: по СИНТАКСИЧЕСКОЙ форме строки, без словаря имён.
_PARAMETER_ONLY_RES = (
    re.compile(r"^\s*(?:(?:public|private|protected|static|final|readonly|"
               r"volatile|transient|internal|const|lateinit|override)\s+)*"
               r"[A-Za-z_][\w<>\[\],. ?]*\s+{sym}\s*(?:=|;|,|\))"),
    re.compile(r"^\s*{sym}\s*(?:=|:=|\+=|-=|\*=|/=)\s*"),
    re.compile(r"^\s*(?:this\.)?{sym}\s*;\s*$"),
    re.compile(r"[\w>\]]\s+{sym}\s*[,)]\s*$"),
    re.compile(r"^\s*@?\w+\s*\(\s*[^)]*{sym}[^)]*\)\s*;?\s*$"),
)


def is_parameter_only(lines: list[str], symbol: str) -> bool:
    """Все вхождения — объявление/присваивание/параметр (детерминированно)."""
    hits = symbol_occurrences(lines, symbol)
    if not hits:
        return False
    token = re.escape(str(symbol).strip())
    patterns = [re.compile(p.pattern.format(sym=token)) for p in _PARAMETER_ONLY_RES]
    for index in hits:
        line = strip_line_ending(lines[index - 1])
        if not any(pattern.search(line) for pattern in patterns):
            return False
    return True


_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
_TYPE_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9_]{2,})(?![A-Za-z0-9_])")


def sibling_identifiers(snippet: str, exclude: str = "") -> list[str]:
    """Идентификаторы, реально использованные в теле (вызовы/типы).

    Это разбор ФОРМЫ строки (call/type), а не словарь имён: результат — лишь
    кандидаты для ограниченного follow-up, не утверждения о поведении."""
    found: dict[str, int] = {}
    for match in _CALL_RE.finditer(str(snippet or "")):
        name = match.group(1)
        found[name] = found.get(name, 0) + 1
    for match in _TYPE_RE.finditer(str(snippet or "")):
        name = match.group(1)
        found[name] = found.get(name, 0) + 1
    skip = str(exclude or "").strip()
    # Синтаксические ключевые слова языков — не идентификаторы-цели.
    keywords = frozenset({
        "if", "for", "while", "switch", "catch", "return", "function",
        "class", "new", "else", "try", "throw", "super", "this", "case",
        "synchronized", "assert", "print", "String", "Integer", "Boolean",
        "Double", "Float", "Long", "Object", "Math", "List", "Map", "Set",
        "Optional", "System", "Exception", "RuntimeException", "Override",
    })
    return [name for name, _count in sorted(found.items(),
                                            key=lambda item: (-item[1], item[0]))
            if name not in keywords and name != skip]


def line_window(total_lines: int, *, symbol_line: int = 0,
                line_start: int | None = None,
                line_end: int | None = None) -> tuple[int, int]:
    """Границы окна чтения (1-based, включительно) ДО лимита символов.

    Единственный содержательный ограничитель размера — динамическое окно
    evidence (символы): собственного потолка строк здесь нет, иначе нужная
    часть файла после лимита была бы недостижима. Явный `line_start/line_end`
    и найденный символ задают НАЧАЛО окна, конец — конец файла (дальше режет
    бюджет символов)."""
    if total_lines <= 0:
        return (0, 0)
    if line_start and line_end:
        start = max(1, min(int(line_start), total_lines))
        end = max(start, min(int(line_end), total_lines))
        return (start, end)
    if line_start:
        return (max(1, min(int(line_start), total_lines)), total_lines)
    if symbol_line:
        return (max(1, int(symbol_line) - 25), total_lines)
    return (1, total_lines)


@dataclass
class SnippetWindow:
    """Доставленный фрагмент + наблюдаемая обрезка (§1.1/§4)."""

    text: str = ""
    line_range: tuple[int, int] = (0, 0)
    truncated: bool = False
    why: str = ""
    used_chars: int = 0
    retrievable_remainder_lines: int = 0
    total_lines: int = 0


def build_snippet(text: str, *, budget_chars: int,
                  symbol_line: int = 0, line_start: int | None = None,
                  line_end: int | None = None) -> SnippetWindow:
    """Собрать фрагмент как ТОЧНЫЙ срез исходного текста (V1.3).

    ``text`` — декодированный текст файла целиком; фрагмент вырезается по
    смещениям строк, поэтому переводы строк (в том числе ``\\r\\n``) остаются
    теми же, что в файле. Номера строк передаются отдельно (`line_range`),
    единственная копия кода в payload остаётся дословной."""
    lines = split_lines(text)
    total = len(lines)
    if total <= 0:
        return SnippetWindow(total_lines=0)
    spans = line_spans(text)
    start, end = line_window(total, symbol_line=symbol_line,
                             line_start=line_start, line_end=line_end)
    if start <= 0 or end < start:
        return SnippetWindow(total_lines=total)
    limit = int(budget_chars or 0)
    chosen_end = start - 1
    for index in range(start, end + 1):
        # Длина среза от начала первой строки до конца текущей — с реальным
        # разделителем; бюджет считается по тем же байтам, что доставляются.
        candidate = spans[index - 1][1] - spans[start - 1][0]
        if limit > 0 and candidate > limit and chosen_end >= start:
            break
        chosen_end = index
    if chosen_end < start:
        chosen_end = start
    fragment = text[spans[start - 1][0]:spans[chosen_end - 1][1]]
    remainder = total - chosen_end if chosen_end < total else 0
    truncated = chosen_end < total
    return SnippetWindow(text=fragment, line_range=(start, chosen_end),
                         truncated=truncated,
                         why="over_window" if truncated else "",
                         used_chars=len(fragment),
                         retrievable_remainder_lines=remainder,
                         total_lines=total)


# ── телеметрия (существующий стадийный эмиттер, 0 новых кодов) ──────────────

def _emit_stage(stage: str, outcome: str, *, reason_code: str = "",
                duration_ms: int = 0, extra: dict | None = None,
                level: str | None = None) -> None:
    """Событие стадии `mca07_source_<stage>`; R17-safe (числа/коды, без URL)."""
    try:
        from services.mca_retrieval_context import emit_stage_event
        fields: dict = {}
        if reason_code:
            fields["reason_code"] = str(reason_code)
        if duration_ms:
            fields["duration_ms"] = int(duration_ms)
        if extra:
            fields["error_json"] = {k: v for k, v in extra.items()
                                    if isinstance(v, (str, int, float, bool))}
        emit_stage_event("source_" + str(stage), outcome, level=level, **fields)
    except Exception:      # pragma: no cover - наблюдаемость не рвёт поток
        pass


# ── оркестратор: discover → locate → fetch → follow-up ──────────────────────

class SourceReader:
    """Оркестратор чтения исходников. Никогда не бросает наружу.

    ``fetcher`` — опциональный ``SafeFetcher`` (тесты передают клиент с
    ``MockTransport``); без него создаётся штатный. ``search`` — существующий
    поисковый каскад (``ToolDeps.search``) для discovery по описанию; None →
    discovery идёт только через API репозиториев."""

    def __init__(self, *, fetcher=None, provider=None, search=None) -> None:
        self._fetcher = fetcher
        self._provider = provider
        self._search = search

    # -- провайдер/счётчики ---------------------------------------------
    @property
    def provider(self) -> SourceProvider:
        if self._provider is None:
            self._provider = GitHubProvider(self._fetcher, token=github_token())
        return self._provider

    def _network_calls(self) -> int:
        return int(getattr(self.provider, "network_calls", 0) or 0)

    def _exhausted(self) -> bool:
        """Жёсткий предохранитель от ретрай-петли (§4, SOURCE_READ_MAX_REQUESTS)."""
        return self._network_calls() >= max_requests()

    @property
    def uses_auth(self) -> bool:
        return bool(getattr(self.provider, "uses_auth", False))

    # -- публичный вход --------------------------------------------------
    async def run(self, *, operation: str = OPERATION_READ, url: Any = "",
                  repo: Any = "", query: Any = "", ref: Any = "", path: Any = "",
                  symbol: Any = "", line_start=None, line_end=None,
                  follow=None, language: Any = "", budget_chars: int = 0,
                  context_query: Any = "") -> dict:
        """Один вызов инструмента → payload Evidence Contract (§1.1).

        Все аргументы, кроме ``operation``, опциональны и могут быть выведены
        из контекста хода (``url`` ← resolved_url, ``query`` ← query хода).
        Функция НИКОГДА не бросает: любой сбой → ``status:"error"``."""
        started = time.monotonic()
        state = _RunState(operation=str(operation or OPERATION_READ).lower(),
                          budget_chars=int(budget_chars or 0))
        try:
            payload = await self._run(state, url=url, repo=repo, query=query,
                                      ref=ref, path=path, symbol=symbol,
                                      line_start=line_start, line_end=line_end,
                                      follow=follow, language=language,
                                      context_query=context_query)
        except SourceFetchError as exc:
            payload = self._error_payload(state, exc)
        except Exception as exc:      # НИКОГДА не бросает (контракт dispatch)
            logger.warning("[source_reader] unexpected failure | error=%s",
                           type(exc).__name__)
            payload = self._error_payload(
                state, SourceFetchError(ERR_PROVIDER_UNAVAILABLE,
                                        state.stage or STAGE_FETCH,
                                        retryable=True,
                                        detail=type(exc).__name__))
        calls = self._network_calls()
        payload["latency_ms"] = int((time.monotonic() - started) * 1000)
        payload["network_calls"] = calls
        payload.setdefault("provenance", {})["network_calls"] = calls
        return payload

    # -- основная логика -------------------------------------------------
    async def _run(self, state: "_RunState", *, url, repo, query, ref, path,
                   symbol, line_start, line_end, follow, language,
                   context_query) -> dict:
        if not source_read_enabled():
            raise SourceFetchError(ERR_DISABLED, STAGE_DISCOVER,
                                   detail="kill_switch")
        operation = state.operation
        if operation not in OPERATIONS:
            operation = OPERATION_READ
            state.operation = operation
        parsed = parse_source_url(url) if str(url or "").strip() else None
        if parsed is not None and not parsed.supported:
            # Другой хостинг: заявлений о поддержке нет (§2) — честный отказ.
            payload = self._payload(
                state, STATUS_UNSUPPORTED,
                error=ERR_PROVIDER_UNCONFIGURED,
                reason=ERR_PROVIDER_UNCONFIGURED,
                error_detail=SourceFetchError(
                    ERR_PROVIDER_UNCONFIGURED, STAGE_DISCOVER,
                    detail="host_not_supported").to_payload())
            _emit_stage(STAGE_DISCOVER, "failed",
                        reason_code=_REASON_FOR_CODE[ERR_PROVIDER_UNCONFIGURED],
                        extra={"network_calls": self._network_calls()})
            return payload
        state.line_start = line_start if line_start else (
            parsed.line_start if parsed is not None else None)
        state.line_end = line_end if line_end else (
            parsed.line_end if parsed is not None else None)
        state.stage = STAGE_DISCOVER
        info, stop = await self._discover(
            state, parsed=parsed, repo=repo, query=query,
            language=language, context_query=context_query)
        if stop is not None:
            return stop
        state.repo = info.full_name
        # Приватный доступ (авторизация использована) → reuse только внутри чата
        # (§3.3: публичный документ можно, приватный контекст — нет).
        state.repo_scope = "chat" if self.uses_auth else "public"
        ref_hint = str(ref or "").strip() or (parsed.ref if parsed else "")
        path_hint = str(path or "").strip() or (parsed.path if parsed else "")
        state.requested_ref = ref_hint
        if operation == OPERATION_DISCOVER:
            payload = self._payload(
                state, STATUS_OK, repo=info.full_name,
                source_kind=(KIND_REPO if not path_hint
                             else _kind_for_path(path_hint)),
                ref=ref_hint)
            payload["candidates"] = [info.as_candidate()]
            payload["stage"] = STAGE_DISCOVER
            payload["read_level"] = "discovered"
            return payload
        if operation == OPERATION_LOCATE:
            direct = path_hint or (parsed is not None and parsed.kind in
                                   (KIND_FILE, KIND_README))
            if direct:
                return await self._fetch_one(
                    state, info, parsed=parsed, ref_hint=ref_hint,
                    path_hint=path_hint, symbol=str(symbol or ""),
                    stage=STAGE_LOCATOR)
            return await self._locate_in_tree(
                state, info, parsed=parsed, ref_hint=ref_hint,
                path_hint=path_hint, symbol=str(symbol or ""),
                query=str(query or context_query or ""))
        # Путь не задан и ссылка не файловая → локатор по дереву, затем чтение:
        # «просто найди реализацию» (§1.1 сценарий 3) обязан пройти путь
        # discovery → locator → verified fetch, а не угадать файл по имени.
        if not path_hint and (parsed is None or parsed.kind not in
                              (KIND_FILE, KIND_README)):
            located = await self._locate_in_tree(
                state, info, parsed=parsed, ref_hint=ref_hint,
                path_hint=path_hint, symbol=str(symbol or ""),
                query=str(query or context_query or ""))
            if located.get("status") != STATUS_OK:
                return located
            want_chain = True if follow is None else bool(follow)
            if not want_chain:
                return located
            return await self._followup(state, info=info, payload=located,
                                        commit=str(located.get("commit") or ""),
                                        symbol=str(symbol or ""))
        payload = await self._fetch_one(state, info, parsed=parsed,
                                        ref_hint=ref_hint, path_hint=path_hint,
                                        symbol=str(symbol or ""),
                                        stage=STAGE_FETCH)
        if payload.get("status") != STATUS_OK:
            return payload
        want_follow = True if follow is None else bool(follow)
        if not want_follow:
            return payload
        return await self._followup(state, info=info, payload=payload,
                                    commit=str(payload.get("commit") or ""),
                                    symbol=str(symbol or ""))
    # -- discovery -------------------------------------------------------
    async def _discover(self, state: "_RunState", *, parsed, repo, query,
                        language, context_query):
        """Определить репозиторий: ссылка → 0 поисковых вызовов, иначе API."""
        owner = parsed.owner if parsed is not None else ""
        name = parsed.repo if parsed is not None else ""
        if not owner or not name:
            spec = parse_repo_spec(repo)
            if spec is not None:
                owner, name = spec
        if owner and name:
            info = await self.provider.resolve_repo(owner, name)
            if info is None:
                raise SourceFetchError(ERR_SOURCE_MISSING, STAGE_DISCOVER,
                                       http=404, detail="repo_not_found")
            _emit_stage(STAGE_DISCOVER, "success",
                        extra={"network_calls": self._network_calls(),
                               "repo_present": True})
            return (info, None)
        text = str(query or context_query or "").strip()
        if not text:
            raise SourceFetchError(ERR_INVALID_URL, STAGE_DISCOVER,
                                   detail="no_url_no_repo_no_query")
        candidates = await self._discover_candidates(state, text, language)
        if not candidates:
            _emit_stage(STAGE_DISCOVER, "failed",
                        reason_code=_REASON_FOR_CODE[ERR_NO_RESULTS],
                        extra={"network_calls": self._network_calls()})
            raise SourceFetchError(ERR_NO_RESULTS, STAGE_DISCOVER,
                                   detail="search_empty")
        top = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        if runner_up is not None and _ambiguous(top, runner_up):
            _emit_stage(STAGE_DISCOVER, "success",
                        reason_code="ambiguous_identity",
                        extra={"network_calls": self._network_calls(),
                               "verified": False})
            return (None, self._ambiguous_payload(state, top, runner_up,
                                                  candidates))
        _emit_stage(STAGE_DISCOVER, "success",
                    extra={"network_calls": self._network_calls(),
                           "repo_present": True, "verified": False})
        return (top["repo"], None)

    def _ambiguous_payload(self, state: "_RunState", top: dict,
                           runner_up: dict, candidates: list) -> dict:
        """Неоднозначность — НЕ выбор за пользователя: один вопрос (§3)."""
        payload = self._payload(
            state, STATUS_AMBIGUOUS,
            reason="ambiguous_identity",
            question=(f"Уточни, какой репозиторий нужен: "
                      f"{top['repo'].full_name} или "
                      f"{runner_up['repo'].full_name}?"))
        payload["candidates"] = [item["repo"].as_candidate()
                                 for item in candidates[:_MAX_CANDIDATES]]
        payload["stage"] = STAGE_DISCOVER
        payload["read_level"] = "discovered"
        payload["needs_choice"] = True
        return payload

    async def _discover_candidates(self, state: "_RunState", text: str,
                                   language) -> list[dict]:
        """Кандидаты: API-поиск + существующий каскад поиска (без словарей)."""
        tokens = _term_tokens(text)
        wanted_lang = str(language or "").strip().lower()
        seen: dict[str, dict] = {}
        try:
            for info in await self.provider.search_repos(text, limit=5):
                seen[info.full_name.lower()] = {
                    "repo": info,
                    "score": _score_repo(info, tokens, wanted_lang,
                                         explicit=False)}
        except SourceFetchError as exc:
            if exc.code in (ERR_RATE_LIMIT, ERR_AUTH_FAILED):
                raise
            logger.info("[source_reader] discovery search failed | code=%s",
                        exc.code)
        for info in await self._cascade_candidates(text):
            key = info.full_name.lower()
            candidate = seen.get(key)
            score = _score_repo(info, tokens, wanted_lang, explicit=False)
            if candidate is None:
                seen[key] = {"repo": info, "score": score + 5}
            else:
                candidate["score"] = max(candidate["score"], score + 5)
        ordered = sorted(seen.values(),
                         key=lambda item: (-item["score"],
                                           item["repo"].full_name))
        return ordered[:_MAX_CANDIDATES]

    async def _cascade_candidates(self, text: str) -> list[RepoInfo]:
        """Существующий поисковый каскад: из выдачи берутся ТОЛЬКО URL-формы.

        Имена проектов/пакеты не сопоставляются словарём: из текста выдачи
        извлекаются github-адреса по форме URL (`smartmodule_urls`)."""
        search = self._search
        if search is None:
            return []
        try:
            text_out = await search.search(text, max_symbols=4000)
        except Exception:      # pragma: no cover - каскад не бросает наружу
            return []
        try:
            from services.smartmodule_urls import extract_urls
            urls = extract_urls(str(text_out or ""))
        except Exception:      # pragma: no cover - защитная ветка
            return []
        out: list[RepoInfo] = []
        wanted: set[str] = set()
        for url in urls:
            parsed = parse_source_url(url)
            if parsed is None or not parsed.supported:
                continue
            if not parsed.owner or not parsed.repo:
                continue
            key = f"{parsed.owner}/{parsed.repo}".lower()
            if key in wanted:
                continue
            wanted.add(key)
            if len(out) >= 2 or self._exhausted():
                break
            info = await self.provider.resolve_repo(parsed.owner, parsed.repo)
            if info is not None:
                out.append(info)
        return out

    # -- идентичность (repo, commit, path) -------------------------------
    async def _resolve_identity(self, state: "_RunState", info, *, parsed,
                                ref_hint: str, path_hint: str):
        """→ (ref, commit, path, prefetched SourceFile|None) или None.

        Кандидаты «самый длинный ref первым» проверяются ТОЛЬКО реальным
        чтением байт: первый успех = истина, остальные не выполняются (§2)."""
        repo = info.full_name
        if not path_hint and (parsed is None or not parsed.ref_path_candidates):
            commit = await self._commit_for(state, info, ref_hint)
            return (ref_hint, commit, "", None)
        pairs: list[tuple[str, str]] = []
        if ref_hint and path_hint:
            pairs.append((ref_hint, path_hint))
        for pair in (parsed.ref_path_candidates if parsed is not None else ()):
            if pair not in pairs:
                pairs.append(pair)
        if path_hint and not pairs:
            pairs.append((ref_hint, path_hint))
        seen: set[tuple[str, str]] = set()
        unsupported: SourceFetchError | None = None
        pending_empty: tuple | None = None
        for ref_candidate, path_candidate in pairs[:_MAX_REF_CANDIDATES]:
            if not path_candidate or (ref_candidate, path_candidate) in seen:
                continue
            seen.add((ref_candidate, path_candidate))
            if self._exhausted():
                state.not_checked_reason = "budget"
                return None
            try:
                commit = await self._commit_for(state, info, ref_candidate)
            except SourceFetchError as exc:
                if exc.code in (ERR_SOURCE_MISSING,):
                    continue
                raise
            if not commit:
                continue
            if self._exhausted():
                state.not_checked_reason = "budget"
                return None
            try:
                source_file = await self.provider.read_file(
                    repo, commit, path_candidate)
            except SourceFetchError as exc:
                if exc.code == ERR_UNSUPPORTED_KIND:
                    # Каталог/symlink/submodule: это не «файла нет». Запоминаем
                    # честную причину и пробуем следующий кандидат.
                    unsupported = exc
                    continue
                if exc.code == ERR_SOURCE_MISSING:
                    continue
                raise
            if source_file is None:
                continue
            if not source_file.data:
                empty = True
                pending_empty = (ref_candidate, commit, path_candidate,
                                 source_file)
                continue
            return (ref_candidate, commit, path_candidate, source_file)
        if unsupported is not None:
            raise unsupported
        if pending_empty is not None:
            # Файл существует, но пуст: возвращаем идентичность и пустые байты,
            # чтобы вызвавший отдал честный `unsupported/empty_content`.
            return pending_empty
        return None

    async def _commit_for(self, state: "_RunState", info, ref: str) -> str:
        """ref/branch/tag/commit → 40-hex commit (провенанс чтения)."""
        raw_ref = str(ref or "").strip()
        if re.fullmatch(r"[0-9a-fA-F]{40}", raw_ref or ""):
            return raw_ref.lower()
        wanted = raw_ref or info.default_branch or ""
        if not wanted:
            raise SourceFetchError(ERR_SOURCE_MISSING, STAGE_FETCH,
                                   detail="no_ref")
        if self._exhausted():
            state.not_checked_reason = "budget"
            raise SourceFetchError(ERR_PROVIDER_UNAVAILABLE, STAGE_FETCH,
                                   retryable=True, detail="request_budget")
        commit = await self.provider.resolve_commit(info.full_name, wanted)
        if not commit:
            raise SourceFetchError(ERR_SOURCE_MISSING, STAGE_FETCH, http=404,
                                   detail="ref_not_found")
        return commit

    # -- одно чтение файла ----------------------------------------------
    async def _fetch_one(self, state: "_RunState", info, *, parsed,
                         ref_hint: str, path_hint: str, symbol: str,
                         stage: str) -> dict:
        state.stage = stage
        try:
            identity = await self._resolve_identity(
                state, info, parsed=parsed, ref_hint=ref_hint,
                path_hint=path_hint)
        except SourceFetchError as exc:
            if exc.code == ERR_UNSUPPORTED_KIND:
                # Каталог/symlink/submodule вместо файла — честный «это не
                # читаемый файл», а не «файла нет».
                return self._not_source_payload(
                    state, info=info, commit="", path=path_hint,
                    source_file=None,
                    reason=exc.detail or "unsupported_kind", stage=stage)
            raise
        if identity is None:
            _emit_stage(stage, "failed",
                        reason_code=_REASON_FOR_CODE[ERR_SOURCE_MISSING],
                        extra={"network_calls": self._network_calls()})
            raise SourceFetchError(ERR_SOURCE_MISSING, stage, http=404,
                                   detail="path_or_ref_not_found")
        ref_used, commit, path_used, prefetched = identity
        # Показываем ref, к которому чтение РЕАЛЬНО привязано: при разборе
        # `/blob/<ref…>/<path>` «сырая» догадка (например `feature` для ветки
        # `feature/x`) вводила бы в заблуждение и ломала бы reuse-идентичность.
        state.requested_ref = ref_used or ref_hint
        if not path_used:
            raise SourceFetchError(ERR_SOURCE_MISSING, stage,
                                   detail="path_required")
        source_file = prefetched
        if source_file is None:
            source_file = await self.provider.read_file(info.full_name, commit,
                                                        path_used)
        if source_file is None:
            _emit_stage(stage, "failed",
                        reason_code=_REASON_FOR_CODE[ERR_SOURCE_MISSING],
                        extra={"network_calls": self._network_calls()})
            raise SourceFetchError(ERR_SOURCE_MISSING, stage, http=404,
                                   detail="unreadable_file")
        if not source_file.data:
            # Пустой файл существует: это не «нет файла», а «нечего читать».
            return self._not_source_payload(
                state, info=info, commit=commit, path=path_used,
                source_file=source_file, reason="empty_content", stage=stage)
        state.files_read += 1
        decoded = decode_source_bytes(source_file.data)
        lines = split_lines(decoded.text)
        symbol_line = locate_symbol_line(lines, symbol) if symbol else 0
        if decoded.ok and symbol and not symbol_line:
            # Символ не подтверждён байтами: честный not_found, а не «вероятно».
            _emit_stage(stage, "success",
                        reason_code=_REASON_FOR_CODE[ERR_SOURCE_MISSING],
                        extra={"network_calls": self._network_calls(),
                               "verified": False, "line_count": len(lines)})
            return self._payload(state, STATUS_NOT_FOUND,
                                 repo=info.full_name, commit=commit,
                                 path=path_used,
                                 reason="symbol_not_found")
        return self._read_payload(state, info=info, commit=commit,
                                  path=path_used, source_file=source_file,
                                  decoded=decoded, symbol=symbol,
                                  symbol_line=symbol_line, stage=stage,
                                  ref_kind=_ref_kind(state.requested_ref))

    # -- locator по дереву ----------------------------------------------
    async def _locate_in_tree(self, state: "_RunState", info, *, parsed,
                              ref_hint: str, path_hint: str, symbol: str,
                              query: str) -> dict:
        commit = await self._commit_for(state, info, ref_hint)
        state.stage = STAGE_LOCATOR
        listing = await self.provider.list_tree(info.full_name, commit)
        if listing is None:
            return self._payload(state, STATUS_NOT_FOUND,
                                 repo=info.full_name, commit=commit,
                                 reason="tree_unavailable")
        if listing.truncated:
            state.not_checked_reason = "tree_truncated"
        ranked = rank_paths(listing, query=query, symbol=symbol,
                            path=path_hint, language=info.language)
        if parsed is not None and parsed.kind == KIND_DIRECTORY and parsed.path:
            prefix = parsed.path.rstrip("/") + "/"
            ranked = [entry for entry in ranked
                      if entry.path.startswith(prefix)] or ranked
        state.files_considered = len(ranked)
        if not ranked:
            _emit_stage(STAGE_LOCATOR, "failed",
                        reason_code=_REASON_FOR_CODE[ERR_SOURCE_MISSING],
                        extra={"network_calls": self._network_calls()})
            return self._payload(state, STATUS_NOT_FOUND,
                                 repo=info.full_name, commit=commit,
                                 reason="no_path_match")
        for entry in ranked[:_MAX_LOCATOR_PATHS]:
            if self._exhausted():
                state.not_checked_reason = "budget"
                break
            try:
                source_file = await self.provider.read_file(
                    info.full_name, commit, entry.path, blob_sha=entry.sha)
            except SourceFetchError as exc:
                if exc.code in (ERR_SOURCE_MISSING, ERR_UNSUPPORTED_KIND):
                    continue
                raise
            if source_file is None or not source_file.data:
                continue
            state.files_read += 1
            decoded = decode_source_bytes(source_file.data)
            lines = split_lines(decoded.text)
            symbol_line = locate_symbol_line(lines, symbol) if symbol else 0
            if decoded.ok and symbol and not symbol_line:
                continue
            return self._read_payload(state, info=info, commit=commit,
                                      path=entry.path, source_file=source_file,
                                      decoded=decoded, symbol=symbol,
                                      symbol_line=symbol_line,
                                      stage=STAGE_LOCATOR,
                                      ref_kind=_ref_kind(state.requested_ref))
        _emit_stage(STAGE_LOCATOR, "success",
                    extra={"network_calls": self._network_calls(),
                           "files_read": state.files_read, "verified": False})
        payload = self._payload(state, STATUS_NOT_FOUND, repo=info.full_name,
                                commit=commit, reason="symbol_not_found")
        payload["candidate_paths"] = [entry.path
                                     for entry in ranked[:_MAX_LOCATOR_PATHS * 2]]
        return payload

    # -- bounded follow-up (§4) ------------------------------------------
    async def _followup(self, state: "_RunState", *, info, payload: dict,
                        commit: str, symbol: str) -> dict:
        """Ограниченный обход смежных файлов + честный `not_checked`."""
        state.stage = STAGE_FOLLOWUP
        primary_path = str(payload.get("path") or "")
        snippet = str(payload.get("snippet") or "")
        parameter_only = bool(payload.get("parameter_only"))
        identifiers = sibling_identifiers(snippet, exclude=symbol)
        files: list[dict] = [{
            "path": primary_path,
            "verified": bool(payload.get("verified")),
            "line_range": list(payload.get("line_range") or []),
            "verified_url": str(payload.get("verified_url") or ""),
            "snippet_chars": int(payload.get("snippet_chars") or 0),
            "role": "primary",
            "symbol_found": bool(payload.get("symbol_found")),
        }]
        depth_left = max_depth()
        reason = state.not_checked_reason
        untried: list[str] = []

        def _finish(incomplete: bool) -> dict:
            payload["files"] = files
            payload["followup_incomplete"] = bool(incomplete)
            payload["not_checked"].update({
                "files_considered": max(state.files_considered, len(files)),
                "files_read": state.files_read,
                "depth_left": depth_left,
                "reason": reason or "",
            })
            if untried:
                payload["not_checked"]["untried_paths"] = untried[:5]
            return payload

        # Без идентификаторов в теле и без «параметр-только» обходить нечего:
        # это не «не смогли прочитать», а «смежных целей не найдено».
        if not identifiers or depth_left <= 0:
            _emit_stage(STAGE_FOLLOWUP, "skipped",
                        extra={"files_read": state.files_read,
                               "network_calls": self._network_calls()})
            if parameter_only:
                reason = reason or "depth_limit"
            return _finish(bool(parameter_only))
        if self._exhausted():
            reason = "budget"
            _emit_stage(STAGE_FOLLOWUP, "failed",
                        reason_code=_REASON_FOR_CODE[ERR_RATE_LIMIT],
                        extra={"network_calls": self._network_calls()})
            return _finish(True)
        # Сбой дерева на этапе follow-up НЕ отменяет уже подтверждённое чтение
        # основного файла: цепочка просто помечается неполной (честный
        # not_checked), а не превращается в ошибку инструмента.
        try:
            listing = await self.provider.list_tree(info.full_name, commit)
        except SourceFetchError:
            listing = None
        if listing is None:
            reason = reason or "tree_unavailable"
            return _finish(True)
        if listing.truncated:
            reason = "tree_truncated"
        ranked = rank_sibling_paths(listing, identifiers, exclude=primary_path,
                                    language=info.language)
        per_file_budget = max(600, int(state.budget_chars or 0)
                              // max(1, max_files()))
        for entry in ranked:
            if depth_left <= 0:
                reason = reason or "depth_limit"
                untried.append(entry.path)
                continue
            if state.files_read >= max_files():
                reason = reason or "budget"
                untried.append(entry.path)
                continue
            if self._exhausted():
                reason = "budget"
                untried.append(entry.path)
                continue
            try:
                source_file = await self.provider.read_file(
                    info.full_name, commit, entry.path, blob_sha=entry.sha)
            except SourceFetchError as exc:
                if exc.code in (ERR_SOURCE_MISSING, ERR_UNSUPPORTED_KIND):
                    continue
                raise
            if source_file is None or not source_file.data:
                continue
            state.files_read += 1
            decoded = decode_source_bytes(source_file.data)
            if not decoded.ok:
                # Бинарь/не-UTF-8 среди смежных файлов — не «код»: файл не
                # добавляется в цепочку (честно, без verified).
                continue
            text = decoded.text
            child_lines = split_lines(text)
            child_symbol = _first_present(identifiers, child_lines)
            symbol_line = locate_symbol_line(child_lines, child_symbol) \
                if child_symbol else 0
            window = build_snippet(text, budget_chars=per_file_budget,
                                   symbol_line=symbol_line)
            child_verified = bool(
                window.text and window.text in text
                and _kind_for_path(entry.path) == KIND_FILE)
            files.append({
                "path": entry.path,
                "verified": child_verified,
                "line_range": [int(window.line_range[0]),
                               int(window.line_range[1])],
                "verified_url": (_verified_url(info.full_name, commit,
                                               entry.path, window.line_range)
                                 if child_verified else ""),
                "snippet": window.text,
                "snippet_chars": len(window.text),
                "symbol": child_symbol,
                "role": "followup",
            })
            depth_left = max(0, depth_left - 1)
        incomplete = bool(untried) or (parameter_only and len(files) <= 1)
        if parameter_only and len(files) <= 1 and not reason:
            # Обход был ОБЯЗАН (§1.2.4), но смежных кандидатов не нашлось:
            # честного «прочитал механизм» не будет.
            reason = "budget" if untried else "not_found"
            incomplete = True
        _emit_stage(STAGE_FOLLOWUP, "success",
                    extra={"files_read": state.files_read,
                           "network_calls": self._network_calls(),
                           "verified": True})
        return _finish(incomplete)

    # -- сборка payload --------------------------------------------------
    def _read_payload(self, state: "_RunState", *, info, commit: str,
                      path: str, source_file: SourceFile,
                      decoded: "DecodedSource", symbol: str, symbol_line: int,
                      stage: str, ref_kind: str) -> dict:
        """Payload чтения: `verified` — ТОЛЬКО по инварианту V1.

        Заголовок/README/иной вид источника (`source_kind != "file"`)
        доставляет текст честно (`verified=false`), но НЕ подтверждается.
        Содержимое, которое не является текстом исходника (не-UTF-8,
        NUL/служебные байты), не доставляется и не подтверждается: это
        ``unsupported`` с машинной причиной, а не «файла нет»."""
        kind = _kind_for_path(path)
        if not decoded.ok:
            return self._not_source_payload(
                state, info=info, commit=commit, path=path,
                source_file=source_file, reason=decoded.reason, stage=stage)
        text = decoded.text
        lines = split_lines(text)
        window = build_snippet(text, budget_chars=int(state.budget_chars or 0),
                               symbol_line=symbol_line,
                               line_start=state.line_start,
                               line_end=state.line_end)
        # V1.3: `snippet` — ТОЧНАЯ подстрока декодированного текста.
        exact = bool(window.text) and window.text in text
        parameter_only = bool(symbol) and is_parameter_only(lines, symbol)
        verified = bool(exact and kind == KIND_FILE and bool(lines))
        state.last_lines = lines
        payload = self._payload(
            state, STATUS_OK,
            verified=verified,
            repo=info.full_name,
            commit=commit,
            path=path,
            source_kind=kind,
            verified_url=(_verified_url(info.full_name, commit, path,
                                        window.line_range)
                          if verified else ""),
            line_range=[int(window.line_range[0]), int(window.line_range[1])],
            snippet=window.text,
            snippet_chars=int(window.used_chars),
            file_total_lines=len(lines),
            language=language_for_path(path) or info.language,
            symbol=symbol,
            symbol_found=bool(symbol and symbol_line),
            parameter_only=parameter_only,
            truncation={
                "truncated": bool(window.truncated),
                "why": window.why,
                "effective_limit": int(state.budget_chars or 0),
                "limit_source": "evidence_window",
                "retrievable_remainder_lines":
                    int(window.retrievable_remainder_lines),
            },
            read_level=_read_level(window, len(lines)))
        payload["provenance"].update({
            "provider": PROVIDER_GITHUB,
            "endpoint": source_file.endpoint or ENDPOINT_CONTENTS,
            "fetched_at": int(time.time()),
            "bytes": len(source_file.data),
            "sha256": hashlib.sha256(source_file.data).hexdigest(),
            "read_level": payload["read_level"],
        })
        payload["source_id"] = _source_id(info.full_name, commit, path)
        _emit_stage(stage, "success",
                    extra={"verified": verified,
                           "files_read": state.files_read,
                           "network_calls": self._network_calls(),
                           "http": 200, "ref_kind": ref_kind,
                           "line_count": len(lines),
                           "path_depth": path.count("/"),
                           "language": payload["language"],
                           "repo_present": True})
        return payload

    def _not_source_payload(self, state: "_RunState", *, info, commit: str,
                            path: str, source_file: SourceFile, reason: str,
                            stage: str) -> dict:
        """Байты получены, но это не текст исходника → честный `unsupported`.

        Отличается от `source_missing` (файла/ветки нет) и от `ok`: бинарь,
        не-UTF-8 содержимое, пустой файл, каталог, symlink/submodule
        называются своими причинами; `verified` всегда False."""
        payload = self._payload(
            state, STATUS_UNSUPPORTED,
            repo=info.full_name, commit=commit, path=path,
            source_kind=(KIND_DIRECTORY if reason == "path_is_directory"
                         else _kind_for_path(path)),
            reason=reason,
            read_level="fetched")
        payload["provenance"].update({
            "provider": PROVIDER_GITHUB,
            "endpoint": source_file.endpoint if source_file is not None
            else "",
            "fetched_at": int(time.time()),
            "bytes": len(source_file.data) if source_file is not None else 0,
            "sha256": (hashlib.sha256(source_file.data).hexdigest()
                       if source_file is not None else ""),
            "read_level": "fetched",
        })
        payload["source_id"] = _source_id(info.full_name, commit, path)
        _emit_stage(stage, "skipped",
                    reason_code=_REASON_FOR_CODE[ERR_UNSUPPORTED_KIND],
                    extra={"network_calls": self._network_calls(),
                           "files_read": state.files_read,
                           "verified": False})
        return payload

    def _payload(self, state: "_RunState", status: str, **overrides) -> dict:
        """Базовая форма Evidence Contract §1.1 (все ключи всегда присутствуют)."""
        payload: dict = {
            "status": status,
            "stage": state.stage,
            "verified": False,
            "host": "github.com",
            "repo": state.repo,
            "ref": state.requested_ref,
            "commit": "",
            "path": "",
            "source_kind": KIND_OTHER,
            "verified_url": "",
            "line_range": [],
            "snippet": "",
            "snippet_chars": 0,
            "file_total_lines": 0,
            "language": "",
            "symbol": "",
            "symbol_found": False,
            "parameter_only": False,
            "truncation": {
                "truncated": False, "why": "",
                "effective_limit": int(state.budget_chars or 0),
                "limit_source": "evidence_window",
                "retrievable_remainder_lines": 0,
            },
            "not_checked": {
                "files_considered": state.files_considered,
                "files_read": state.files_read,
                "depth_left": max_depth(),
                "reason": state.not_checked_reason,
            },
            "followup_incomplete": False,
            "files": [],
            "read_level": "discovered",
            "reused": False,
            "source_id": "",
            "network_calls": self._network_calls(),
            "latency_ms": 0,
            "provenance": {
                "provider": PROVIDER_GITHUB,
                "endpoint": "",
                "fetched_at": 0,
                "bytes": 0,
                "sha256": "",
                "read_level": "discovered",
                "network_calls": self._network_calls(),
            },
        }
        payload.update({key: value for key, value in overrides.items()
                        if value is not None})
        return payload

    def _error_payload(self, state: "_RunState",
                       exc: SourceFetchError) -> dict:
        """`status:"error"` (конвейер: ToolResult `error`, §1.1).

        `error` — машинный КОД (строкой), как у существующих инструментов:
        `tool_result._payload_error_code` читает именно его, поэтому правок в
        конвейере не требуется. Полная запись Evidence Contract (code/stage/
        http/retryable/detail) лежит рядом в `error_detail`."""
        payload = self._payload(state, STATUS_ERROR,
                                error=exc.code, reason=exc.code,
                                error_detail=exc.to_payload())
        if state.not_checked_reason:
            payload["not_checked"]["reason"] = state.not_checked_reason
        _emit_stage(exc.stage, "failed", reason_code=exc.reason_code,
                    extra={"http": exc.http,
                           "network_calls": self._network_calls(),
                           "retryable": exc.retryable})
        return payload


@dataclass
class _RunState:
    """Состояние одного вызова: счётчики наблюдаемости и причина остановки."""

    operation: str = OPERATION_READ
    budget_chars: int = 0
    stage: str = STAGE_DISCOVER
    repo: str = ""
    repo_scope: str = "public"
    requested_ref: str = ""
    line_start: int | None = None
    line_end: int | None = None
    files_considered: int = 0
    files_read: int = 0
    not_checked_reason: str = ""
    last_lines: list[str] = field(default_factory=list)


# ── ранжирование (только реальные сигналы, без словарей имён) ──────────────

def _term_tokens(text: str) -> list[str]:
    """Токены запроса (существующий канон контентных терминов)."""
    try:
        from services.search_aggregator import content_terms
        terms = sorted(content_terms(str(text or "")))
        if terms:
            return terms
    except Exception:      # pragma: no cover - защитная ветка
        pass
    return [token.lower() for token in _IDENTIFIER_RE.findall(str(text or ""))]


def _score_repo(info: RepoInfo, tokens: list[str], wanted_lang: str,
                *, explicit: bool) -> float:
    """Балл кандидата — только сигналы ответа API и самого запроса (§3)."""
    score = 100.0 if explicit else 0.0
    haystack = f"{info.full_name} {info.description}".lower()
    overlap = sum(1 for token in tokens if token and token in haystack)
    score += min(25.0, overlap * 5.0)
    if wanted_lang and info.language.lower() == wanted_lang:
        score += 10.0
    try:
        import math
        score += min(15.0, math.log10(max(1, int(info.stars or 0))) * 5.0)
    except Exception:      # pragma: no cover - защитная ветка
        pass
    return round(score, 3)


def _ambiguous(top: dict, runner_up: dict) -> bool:
    """Неоднозначность: разные репозитории и разрыв меньше 25% балла."""
    if top["repo"].full_name.lower() == runner_up["repo"].full_name.lower():
        return False
    best = float(top["score"] or 0.0)
    second = float(runner_up["score"] or 0.0)
    if best <= 0:
        return False
    return (best - second) / best < 0.25


def rank_paths(listing: TreeListing, *, query: str, symbol: str, path: str,
               language: str) -> list[TreeEntry]:
    """Локатор: пути дерева по стему/сегментам/расширению (§3, без словарей)."""
    tokens = set(_term_tokens(f"{query} {symbol}"))
    stem = str(symbol or "").strip().lower()
    wanted_path = str(path or "").strip().lower()
    wanted_lang = str(language or "").strip().lower()
    ranked: list[tuple[float, TreeEntry]] = []
    for entry in listing.entries:
        if entry.kind not in ("blob", ""):
            continue
        lowered = entry.path.lower()
        name = lowered.rsplit("/", 1)[-1]
        name_stem = name.rsplit(".", 1)[0]
        ext = name[name.rfind("."):] if "." in name else ""
        if ext not in _SOURCE_EXTS:
            continue
        score = 0.0
        if wanted_path and lowered == wanted_path:
            score += 100.0
        if stem:
            if name_stem == stem:
                score += 60.0
            elif stem in name_stem:
                score += 40.0
        if tokens:
            score += 6.0 * sum(1 for token in tokens if token in lowered)
        if ext and wanted_lang and _LANGUAGE_BY_EXT.get(ext, "") == wanted_lang:
            score += 10.0
        if any(part in lowered.split("/")[:-1]
               for part in ("test", "tests", "docs", "doc", "example",
                            "examples", "samples")):
            score -= 25.0
        if _README_RE.match(name):
            score -= 40.0
        if score <= 0:
            continue
        ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1].path))
    return [entry for _score, entry in ranked]


def rank_sibling_paths(listing: TreeListing, identifiers: list[str], *,
                       exclude: str, language: str) -> list[TreeEntry]:
    """Смежные файлы: стем пути совпадает с идентификатором из тела (§4)."""
    wanted = {str(item).strip().lower() for item in identifiers
              if str(item or "").strip()}
    skip = str(exclude or "").strip()
    wanted_lang = str(language or "").strip().lower()
    ranked: list[tuple[float, TreeEntry]] = []
    for entry in listing.entries:
        if entry.kind not in ("blob", ""):
            continue
        if skip and entry.path == skip:
            continue
        name = entry.path.rsplit("/", 1)[-1]
        lowered = name.lower()
        ext = lowered[lowered.rfind("."):] if "." in lowered else ""
        if ext not in _SOURCE_EXTS:
            continue
        stem = lowered.rsplit(".", 1)[0]
        if stem not in wanted:
            continue
        score = 50.0
        if wanted_lang and _LANGUAGE_BY_EXT.get(ext, "") == wanted_lang:
            score += 10.0
        score -= 3.0 * entry.path.count("/")
        ranked.append((score, entry))
    ranked.sort(key=lambda item: (-item[0], item[1].path))
    return [entry for _score, entry in ranked]


def _first_present(identifiers, lines: list[str]) -> str:
    for candidate in identifiers:
        if locate_symbol_line(lines, candidate):
            return candidate
    return ""


def _ref_kind(ref: str) -> str:
    """Вид ref для наблюдаемости: commit (40 hex) | branch/tag."""
    text = str(ref or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", text):
        return "commit"
    return "branch"


def _read_level(window: SnippetWindow, total_lines: int) -> str:
    """Уровень чтения (словарь `source_reuse`): фрагмент → `selected`."""
    if not window.text:
        return "discovered"
    if window.line_range[0] <= 1 and window.line_range[1] >= total_lines:
        return "parsed"
    return "selected"


def _verified_url(repo: str, commit: str, path: str, line_range) -> str:
    """Commit-pinned ссылка (никогда не изменяемая ветка) — V1.4."""
    if not repo or not commit or not path:
        return ""
    base = f"{HTML_BASE}/{repo}/blob/{commit}/{path}"
    try:
        start, end = int(line_range[0]), int(line_range[1])
    except (TypeError, ValueError, IndexError):
        return base
    return f"{base}#L{start}-L{end}" if start > 0 and end >= start else base


def _source_id(repo: str, commit: str, path: str) -> str:
    raw = f"{repo}|{commit}|{path}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


__all__ = [
    "STATUSES", "STAGES", "OPERATIONS", "SUPPORTED_HOSTS",
    "STATUS_OK", "STATUS_AMBIGUOUS", "STATUS_NOT_FOUND", "STATUS_UNSUPPORTED",
    "STATUS_ERROR", "PROVIDER_GITHUB", "SourceFetchError", "RepoInfo",
    "TreeEntry", "TreeListing", "SourceFile", "ParsedSourceUrl",
    "SourceProvider", "GitHubProvider", "SourceReader", "parse_source_url",
    "parse_repo_spec", "rank_paths", "rank_sibling_paths", "build_snippet",
    "sibling_identifiers", "is_parameter_only", "locate_symbol_line",
    "language_for_path", "decode_file_text", "split_lines",
    "source_read_enabled", "max_files", "max_depth", "max_requests",
    "max_file_bytes", "github_token", "decode_source_bytes", "DecodedSource",
    "line_spans", "strip_line_ending", "ERR_EMPTY_CONTENT",
]
