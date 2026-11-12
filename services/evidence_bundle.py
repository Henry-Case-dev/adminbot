"""SELF-DIAG-01 D3 — единый сериализуемый диагностический evidence-bundle.

Логический контракт ТЗ §10 (не вторая БД и не второй telemetry-стор):

* один ``DiagnosticEvidenceBundle`` на один диагностический запрос;
* источники несут ``observed_at`` (время ИЗМЕРЕНИЯ), ``source_id``/owner,
  ``scope``, закрытый ``status``, ``coverage``, ``latency_ms``, ``reason_code``;
* ``declared`` ≠ ``configured`` ≠ ``probe_succeeded`` ≠ ``healthy`` —
  четыре отдельных поля, ни одно не выводится из другого;
* утверждения только ``observed``/``correlated``/``hypothesis``/``unknown``/
  ``not_checked``; процентов уверенности нет;
* ``redaction_count`` по техническому классу, ``permission_decision`` без
  секретных значений, ``latency_ms`` и ``reason_code`` присутствуют;
* ссылки на сохранённые сущности переиспользуют существующий
  ``services.provenance.SourceRef`` (store/entity_type/entity_id/resolution),
  а не изобретают несовместимый дубль;
* проекция в ``mca_events`` использует ТОЛЬКО существующие поля события
  (``build_event`` отбрасывает всё остальное), без нового DDL.

Модуль чистый: без сети, без LLM, без записи в БД.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import re
from typing import Any, Iterable, Sequence

# ── Закрытые наборы (ТЗ §10) ───────────────────────────────────────────────

BUNDLE_SCHEMA = "self-diag-01/d3-bundle-v1"

STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"
STATUS_PERMISSION_DENIED = "permission_denied"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_STALE = "stale"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_CHECKED = "not_checked"

STATUSES: tuple[str, ...] = (
    STATUS_OK, STATUS_DEGRADED, STATUS_UNAVAILABLE, STATUS_PERMISSION_DENIED,
    STATUS_NOT_CONFIGURED, STATUS_STALE, STATUS_UNSUPPORTED, STATUS_UNKNOWN,
    STATUS_NOT_CHECKED,
)

#: Детерминированный приоритет агрегации (раньше = важнее). Нужен, чтобы
#: несколько источников давали один честный итог, а не «оптимистичный ok».
STATUS_SEVERITY: dict[str, int] = {
    STATUS_PERMISSION_DENIED: 0,
    STATUS_UNAVAILABLE: 1,
    STATUS_DEGRADED: 2,
    STATUS_STALE: 3,
    STATUS_UNKNOWN: 4,
    STATUS_NOT_CONFIGURED: 5,
    STATUS_UNSUPPORTED: 6,
    STATUS_NOT_CHECKED: 7,
    STATUS_OK: 8,
}

CLAIM_OBSERVED = "observed"
CLAIM_CORRELATED = "correlated"
CLAIM_HYPOTHESIS = "hypothesis"
CLAIM_UNKNOWN = "unknown"
CLAIM_NOT_CHECKED = "not_checked"
CLAIM_KINDS: tuple[str, ...] = (
    CLAIM_OBSERVED, CLAIM_CORRELATED, CLAIM_HYPOTHESIS, CLAIM_UNKNOWN,
    CLAIM_NOT_CHECKED,
)

COVERAGE_COMPLETE = "complete"
COVERAGE_PARTIAL = "partial"
COVERAGE_EMPTY = "empty"
COVERAGE_VALUES: tuple[str, ...] = (
    COVERAGE_COMPLETE, COVERAGE_PARTIAL, COVERAGE_EMPTY,
)

#: Контрактные поля bundle (EVD-05..EVD-12). Тест сверяет наличие всех.
BUNDLE_FIELDS: tuple[str, ...] = (
    "schema", "request_id", "chat_scope", "scope", "runtime", "sources",
    "claims", "redaction", "not_checked", "access", "status", "coverage",
    "observed_at", "latency_ms", "reason_code", "runtime_sha", "git_head_sha",
    "source_verified", "commits_since_deploy", "git_metadata_attempted",
    "code_lookup_attempted", "request",
)


# ── Время/JSON ─────────────────────────────────────────────────────────────

def utc_now_iso(ts: float | None = None) -> str:
    """ISO-8601 UTC. ``ts`` — уже снятый момент измерения (не «сейчас»)."""
    moment = (datetime.datetime.now(datetime.timezone.utc)
              if ts is None
              else datetime.datetime.fromtimestamp(ts, datetime.timezone.utc))
    return moment.isoformat()


def _json_safe(value: Any) -> Any:
    """Только JSON-типы; bytes/set/объекты не протекают из probes."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    return str(value)


# ── Source evidence ────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class SourceEvidence:
    """Один измеренный источник. Четыре состояния доступности — раздельно."""

    kind: str
    status: str
    observed_at: str
    source_id: str
    owner: str
    scope: str
    latency_ms: int | None = None
    coverage: dict | None = None
    reason_code: str | None = None
    declared: bool = True
    configured: bool = True
    probe_succeeded: bool = False
    healthy: bool | None = None
    verified: bool | None = None
    facts: dict | None = None
    not_checked: tuple[str, ...] = ()
    redaction: dict | None = None
    source_ref: dict | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"invalid source status: {self.status!r}")
        if not str(self.kind or "").strip():
            raise ValueError("source kind is empty")
        if not str(self.source_id or "").strip():
            raise ValueError("source_id is empty")
        if self.reason_code is not None and not isinstance(self.reason_code,
                                                           str):
            raise ValueError("reason_code must be str|None")

    def to_dict(self) -> dict:
        payload = {
            "kind": self.kind,
            "status": self.status,
            "observed_at": self.observed_at,
            "source_id": self.source_id,
            "owner": self.owner,
            "scope": self.scope,
            "latency_ms": self.latency_ms,
            "coverage": self.coverage or coverage(COVERAGE_PARTIAL),
            "reason_code": self.reason_code,
            "declared": bool(self.declared),
            "configured": bool(self.configured),
            "probe_succeeded": bool(self.probe_succeeded),
            "healthy": self.healthy,
            "not_checked": list(self.not_checked),
        }
        if self.verified is not None:
            payload["verified"] = bool(self.verified)
        if self.facts is not None:
            payload["facts"] = _json_safe(self.facts)
        if self.redaction is not None:
            payload["redaction"] = _json_safe(self.redaction)
        if self.source_ref is not None:
            payload["source_ref"] = _json_safe(self.source_ref)
        return payload


# ── Фабрики ────────────────────────────────────────────────────────────────

def coverage(parts: Iterable[str] = (), *, complete: bool = False,
             truncated: bool = False, why: str = "") -> dict:
    """Наблюдаемое покрытие: что реально проверено и где обрезка/почему."""
    items = [str(p) for p in (parts or ()) if str(p or "").strip()]
    state = (COVERAGE_COMPLETE if complete and not truncated
             else COVERAGE_PARTIAL if items or truncated
             else COVERAGE_EMPTY)
    payload = {"state": state, "parts": items, "truncated": bool(truncated)}
    if why:
        payload["why"] = str(why)
    return payload


def claim(kind: str, statement: str, evidence_refs: Sequence[str] = (),
          limitations: Sequence[str] = ()) -> dict:
    """Типизированное утверждение; никаких процентов уверенности."""
    if kind not in CLAIM_KINDS:
        raise ValueError(f"invalid claim kind: {kind!r}")
    text = str(statement or "").strip()
    if not text:
        raise ValueError("claim statement is empty")
    payload = {
        "kind": kind,
        "statement": text,
        "evidence_refs": [str(r) for r in evidence_refs if str(r or "")],
    }
    limits = [str(x) for x in limitations if str(x or "")]
    if limits:
        payload["limitations"] = limits
    return payload


def redaction(count: int = 0, classes: Iterable[str] = (), *,
              reason: str = "no_secret_values") -> dict:
    """Счётчик редакции по техническому классу (без самих значений)."""
    try:
        redacted = max(0, int(count or 0))
    except (TypeError, ValueError):
        redacted = 0
    kinds = sorted({str(c) for c in (classes or ()) if str(c or "")})
    return {
        "performed": redacted > 0,
        "redacted_fields": redacted,
        "classes": kinds,
        "reason": str(reason or ""),
    }


def source_ref(*, store: str, entity_type: str, entity_id: str,
               chat_id: int | None = None, revision: str | None = None,
               tg_message_id: int | None = None,
               resolution: str = "resolved") -> dict:
    """Существующий SourceRef (provenance) для источников с хранимой сущностью.

    OS/runtime probes не имеют записанной сущности — для них source_ref не
    выдумывается (используются source_id/owner выше). Невалидный ref — ошибка
    вызывающего кода, а не тихая подмена другим контрактом.
    """
    from services import provenance as _provenance
    ref = _provenance.SourceRef(
        store=store, entity_type=entity_type, entity_id=str(entity_id),
        chat_id=chat_id, revision=revision, tg_message_id=tg_message_id,
        resolution=resolution)
    return ref.validate().as_dict()


def aggregate_status(statuses: Iterable[str]) -> str:
    """Итог по источникам: худший статус, ``ok`` только если все ``ok``.

    ``degraded`` означает «часть диагностики исправна»; ``unavailable`` —
    только когда ничего пригодного не осталось. Отказ политики важнее всего.
    """
    items = [s for s in (statuses or ()) if s]
    if not items:
        return STATUS_NOT_CHECKED
    unknown = [s for s in items if s not in STATUS_SEVERITY]
    if unknown:
        return STATUS_UNKNOWN
    if any(s == STATUS_PERMISSION_DENIED for s in items):
        return STATUS_PERMISSION_DENIED
    if all(s == STATUS_OK for s in items):
        return STATUS_OK
    if all(s == STATUS_NOT_CHECKED for s in items):
        return STATUS_NOT_CHECKED
    usable = (STATUS_OK, STATUS_DEGRADED, STATUS_STALE)
    if any(s in usable for s in items):
        return STATUS_DEGRADED
    if any(s == STATUS_UNAVAILABLE for s in items):
        return STATUS_UNAVAILABLE
    return min(items, key=lambda s: STATUS_SEVERITY[s])


# ── Stack summary (EVD-13) ─────────────────────────────────────────────────

_FRAME_RE = re.compile(
    r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
_SKIP_PREFIXES = ("During handling of the above exception",
                  "The above exception was the direct cause",
                  "Traceback (most recent call last)")
_EXC_TYPES = re.compile(
    r'^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Interrupt|Exit|Warning))'
    r'(?::\s*(?P<msg>.*))?$')


def _sanitize_text(text: str) -> str:
    """Существующий sanitizer логов (R17), без секретных значений наружу."""
    try:
        from services.log_ring import sanitize as _log_sanitize
        return _log_sanitize(str(text or ""))
    except Exception:       # pragma: no cover - защитная ветка
        return str(text or "")


def sanitize_text(text: str) -> str:
    """Публичная форма существующего sanitizer'а (один на проект).

    Нужна потребителям структурных фактов (например, корреляции traceback),
    чтобы не заводить вторую копию маскировки секретов.
    """
    return _sanitize_text(text)


def traceback_frames(text: str) -> dict:
    """Публичная структурная выжимка traceback: кадры + exception.

    Тот же разбор (``_parse_traceback``), что использует ``stack_summary``;
    текст кадров уже прошёл существующий sanitizer. Возвращает
    ``{"frames": [...], "exception": {...}|None, "partial": bool}`` и не
    бросает на произвольном тексте.
    """
    try:
        return _parse_traceback(str(text or ""))
    except Exception:       # pragma: no cover - защитная ветка
        return {"frames": [], "exception": None, "partial": True}


def stack_summary(text: str,
                  *,
                  budget_chars: int = 2000,
                  cursor: str = "",
                  max_frames: int = 120) -> dict:
    """Структурная выжимка traceback вместо «обрезки первых N символов».

    Кадры разбираются и отдаются по бюджету с continuation-курсором
    ``frame:<offset>``; exception-headline и source_id сохраняются. Полная
    длина текста и число кадров видимы в coverage, поэтому «тупая» обрезка
    не маскирует потерю причинно важных кадров.
    """
    raw = str(text or "")
    budget = max(200, int(budget_chars or 2000))
    parsed = _parse_traceback(raw)
    frames = parsed["frames"]
    total = len(frames)
    start = 0
    token = str(cursor or "").strip()
    if token:
        if not token.startswith("frame:"):
            return {
                "kind": "stack_summary", "status": STATUS_UNKNOWN,
                "reason_code": "unknown_cursor", "frames": [],
                "frame_count": total, "truncated": False,
                "next_cursor": "", "coverage": coverage(("traceback",),
                                                         why="bad_cursor"),
            }
        try:
            start = max(0, int(token.split(":", 1)[1]))
        except (TypeError, ValueError):
            return {
                "kind": "stack_summary", "status": STATUS_UNKNOWN,
                "reason_code": "unknown_cursor", "frames": [],
                "frame_count": total, "truncated": False,
                "next_cursor": "", "coverage": coverage(("traceback",),
                                                         why="bad_cursor"),
            }
    hard_limit = max(1, int(max_frames or 120))
    window = frames[start:start + hard_limit]
    shown: list[dict] = []
    used = 0
    for item in window:
        cost = 96 + len(item.get("file", "")) + len(item.get("function", ""))
        if shown and used + cost > budget:
            break
        shown.append(item)
        used += cost
        if used >= budget:
            break
    end = start + len(shown)
    next_cursor = f"frame:{end}" if end < total else ""
    complete = (start == 0 and end == total)
    result = {
        "kind": "stack_summary",
        "status": STATUS_OK if total else STATUS_NOT_CHECKED,
        "frames": shown,
        "frame_count": total,
        "truncated": bool(next_cursor) or len(window) < len(frames),
        "next_cursor": next_cursor,
        "coverage": coverage(
            ("traceback",),
            complete=complete,
            truncated=bool(next_cursor),
            why=(f"frame_limit_{hard_limit}" if len(window) < len(frames)
                 else "budget"),
        ),
        "raw_chars": len(raw),
        "shown_frames": len(shown),
    }
    if parsed.get("exception"):
        result["exception"] = parsed["exception"]
    if parsed.get("partial"):
        result["coverage"]["why"] = "unparsed_tail"
    if not total:
        result["reason_code"] = "no_traceback_frames"
    return result


def _parse_traceback(raw: str) -> dict:
    """Кадры + последняя exception-строка; текст только санитизируется."""
    frames: list[dict] = []
    partial = False
    lines = raw.splitlines()
    last_exc: dict | None = None
    for index, line in enumerate(lines):
        match = _FRAME_RE.match(line)
        if match:
            file_name = _sanitize_text(match.group("file").strip())
            function = _sanitize_text(match.group("func").strip())
            try:
                line_no = int(match.group("line"))
            except (TypeError, ValueError):
                line_no = 0
            source_line = ""
            if index + 1 < len(lines):
                candidate = lines[index + 1]
                if candidate.strip() and not candidate.lstrip().startswith(
                        ("File \"", "^")):
                    source_line = _sanitize_text(candidate.strip())[:200]
            frame = {
                "index": len(frames),
                "file": file_name,
                "line": line_no,
                "function": function,
            }
            if source_line:
                frame["source_line"] = source_line
            frames.append(frame)
            continue
        stripped = line.strip()
        if not stripped or line[:1].isspace():
            continue
        if stripped.startswith(_SKIP_PREFIXES):
            continue
        exc = _EXC_TYPES.match(stripped)
        if exc:
            message = exc.group("msg") or ""
            last_exc = {
                "type": _sanitize_text(exc.group("type"))[:120],
                "headline": _sanitize_text(stripped)[:300],
                "message_chars": len(message),
            }
        elif frames:
            # Непустой хвост после кадров без распознанного типа — честно
            # отмечаем неполный разбор, но не выдумываем тип исключения.
            partial = True
    return {"frames": frames, "exception": last_exc, "partial": partial}


# ── Bundle ─────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class DiagnosticEvidenceBundle:
    """Один сериализуемый bundle; без второй БД и без секретных значений."""

    request_id: str
    chat_scope: str
    scope: str
    sources: tuple[SourceEvidence, ...]
    claims: tuple[dict, ...]
    access: dict
    observed_at: str
    latency_ms: int
    runtime: dict
    not_checked: tuple[str, ...] = ()
    redaction: dict = dataclasses.field(
        default_factory=lambda: redaction(0, (), reason="not_performed"))
    reason_code: str | None = None
    runtime_sha: str | None = None
    git_head_sha: str | None = None
    source_verified: bool | None = None
    commits_since_deploy: int | None = None
    git_metadata_attempted: bool = False
    code_lookup_attempted: bool = False
    request: dict = dataclasses.field(default_factory=dict)

    @property
    def status(self) -> str:
        return aggregate_status(src.status for src in self.sources)

    @property
    def coverage(self) -> dict:
        parts: list[str] = []
        truncated = False
        complete = True
        for src in self.sources:
            cov = src.coverage or {}
            parts.extend(cov.get("parts") or [src.kind])
            truncated = truncated or bool(cov.get("truncated"))
            complete = complete and cov.get("state") == COVERAGE_COMPLETE
        return coverage(parts, complete=complete, truncated=truncated,
                        why="source_coverage")

    def to_dict(self) -> dict:
        payload = {
            "schema": BUNDLE_SCHEMA,
            "request_id": self.request_id,
            "chat_scope": self.chat_scope,
            "scope": self.scope,
            "runtime": _json_safe(self.runtime),
            "sources": [src.to_dict() for src in self.sources],
            "claims": [_json_safe(c) for c in self.claims],
            "redaction": _json_safe(self.redaction),
            "not_checked": list(self.not_checked),
            "access": _json_safe(self.access),
            "status": self.status,
            "coverage": self.coverage,
            "observed_at": self.observed_at,
            "latency_ms": int(self.latency_ms),
            "reason_code": self.reason_code,
            "runtime_sha": self.runtime_sha,
            "git_head_sha": self.git_head_sha,
            "source_verified": self.source_verified,
            "commits_since_deploy": self.commits_since_deploy,
            "git_metadata_attempted": bool(self.git_metadata_attempted),
            "code_lookup_attempted": bool(self.code_lookup_attempted),
            "request": _json_safe(self.request),
        }
        return payload

    def mca_event_fields(self) -> dict:
        """Поля, которые реально принимает существующий контракт mca_events."""
        return {
            "chat_id": self.access.get("chat_id"),
            "component": "self_diag",
            "stage": str(self.request.get("probe") or "inspect_runtime")[:120],
            "status": self.status,
            "duration_ms": int(self.latency_ms),
        }


def build_bundle(*, request_id: str, chat_scope: str, scope: str,
                 sources: Iterable[SourceEvidence], claims: Iterable[dict],
                 access: dict, observed_at: str, latency_ms: int,
                 runtime: dict, not_checked: Iterable[str] = (),
                 redaction_report: dict | None = None,
                 reason_code: str | None = None,
                 runtime_sha: str | None = None,
                 git_head_sha: str | None = None,
                 source_verified: bool | None = None,
                 commits_since_deploy: int | None = None,
                 git_metadata_attempted: bool = False,
                 code_lookup_attempted: bool = False,
                 request: dict | None = None) -> DiagnosticEvidenceBundle:
    """Собрать bundle с проверкой закрытых наборов и дедупликацией claims."""
    srcs = tuple(sources)
    seen_claims: set[tuple] = set()
    clean_claims: list[dict] = []
    for item in claims:
        kind = str(item.get("kind") or "")
        if kind not in CLAIM_KINDS:
            raise ValueError(f"invalid claim kind: {kind!r}")
        key = (kind, item.get("statement"), tuple(item.get("evidence_refs")
                                                  or ()))
        if key in seen_claims:
            continue
        seen_claims.add(key)
        clean_claims.append(item)
    return DiagnosticEvidenceBundle(
        request_id=str(request_id),
        chat_scope=str(chat_scope or "current_chat"),
        scope=str(scope or "current_chat"),
        sources=srcs,
        claims=tuple(clean_claims),
        access=_json_safe(access or {}),
        observed_at=str(observed_at),
        latency_ms=int(latency_ms or 0),
        runtime=_json_safe(runtime or {}),
        not_checked=tuple(sorted({str(x) for x in (not_checked or ())
                                  if str(x or "")})),
        redaction=_json_safe(redaction_report or redaction(
            0, (), reason="not_performed")),
        reason_code=reason_code,
        runtime_sha=runtime_sha,
        git_head_sha=git_head_sha,
        source_verified=source_verified,
        commits_since_deploy=commits_since_deploy,
        git_metadata_attempted=bool(git_metadata_attempted),
        code_lookup_attempted=bool(code_lookup_attempted),
        request=_json_safe(request or {}),
    )


def render_page(bundle: DiagnosticEvidenceBundle, *, max_chars: int,
                offset: int = 0) -> tuple[dict, int]:
    """Страница tool-результата по бюджету; (payload, next_offset).

    ``next_offset == len(sources)`` — всё показано. Ни один источник не
    теряется молча: ``page.omitted_source_ids`` + ``truncated`` видны модели.
    Бюджет включает claims: они фильтруются по показанным источникам и
    ограничиваются, чтобы одна область не вытесняла остальные.
    """
    payload = bundle.to_dict()
    all_sources = list(payload["sources"])
    all_claims = list(payload.get("claims") or [])
    total = len(all_sources)
    start = max(0, min(int(offset or 0), total))
    limit = max(600, int(max_chars or 4000))
    base = dict(payload)
    base["sources"] = []
    base["claims"] = []
    if start > 0:
        base["redaction"] = redaction(0, (), reason="page_2")
    shown: list[dict] = []
    end = start
    reserve = min(1500, max(300, limit // 4))
    for index in range(start, total):
        candidate = dict(base)
        candidate["sources"] = shown + [all_sources[index]]
        if len(json.dumps(candidate, ensure_ascii=False)) > limit - reserve:
            if shown:
                break
            # Один источник больше бюджета — отдаём метаданные без facts,
            # иначе страница не сдвинется вперёд.
            compact = dict(all_sources[index])
            compact.pop("facts", None)
            compact["facts_omitted"] = True
            shown.append(compact)
            end = index + 1
            break
        shown.append(all_sources[index])
        end = index + 1
    page = dict(base)
    page["sources"] = shown
    shown_ids = {str(src.get("source_id")) for src in shown}
    claims: list[dict] = []
    seen: set[tuple] = set()
    for item in all_claims:
        refs = [str(r) for r in item.get("evidence_refs") or ()]
        if refs and not (set(refs) & shown_ids):
            continue
        key = (item.get("kind"), item.get("statement"))
        if key in seen:
            continue
        seen.add(key)
        claims.append(item)
        if len(claims) >= 10:
            break
    page["claims"] = claims
    page["claims_truncated"] = len(claims) < len(all_claims)
    # Финальная гарантия бюджета: сначала снимаем claims, затем — хвост
    # источников; показанный источник без facts сохраняется как метаданные.
    if len(json.dumps(page, ensure_ascii=False)) > limit and claims:
        page["claims"] = []
        page["claims_truncated"] = True
    while len(json.dumps(page, ensure_ascii=False)) > limit and len(
            page["sources"]) > 1:
        page["sources"].pop()
        end -= 1
    if len(json.dumps(page, ensure_ascii=False)) > limit and page["sources"]:
        compact = dict(page["sources"][0])
        compact.pop("facts", None)
        compact["facts_omitted"] = True
        page["sources"] = [compact]
        end = start + 1
    omitted = [s.get("source_id") for s in all_sources[end:]]
    page["page"] = {"offset": start, "next_offset": end,
                    "total_sources": total}
    if omitted:
        page["truncated"] = True
        page["page"]["omitted_source_ids"] = omitted
    cov = dict(page.get("coverage") or {})
    cov["output"] = {"state": (COVERAGE_COMPLETE if not omitted
                               else COVERAGE_PARTIAL),
                     "shown_sources": len(page["sources"]),
                     "total_sources": total,
                     "why": ("" if not omitted else "output_budget")}
    page["coverage"] = cov
    if len(json.dumps(page, ensure_ascii=False)) > limit:
        # Крайний случай: сам базовый конверт больше бюджета. Отдаём
        # валидный минимальный JSON, а не обрезанную строку.
        page = {
            "schema": page.get("schema"),
            "status": page.get("status"),
            "reason_code": "output_budget_exceeded",
            "observed_at": page.get("observed_at"),
            "probe": page.get("probe"),
            "sources": [],
            "claims": [],
            "not_checked": ["output_budget_exceeded"],
            "truncated": True,
            "page": {"offset": start, "next_offset": end,
                     "total_sources": total,
                     "omitted_source_ids": omitted},
            "coverage": cov,
        }
    return page, end


def render_json(bundle: DiagnosticEvidenceBundle, *, max_chars: int = 6000,
                offset: int = 0) -> tuple[str, int]:
    page, next_offset = render_page(bundle, max_chars=max_chars,
                                    offset=offset)
    return json.dumps(page, ensure_ascii=False, sort_keys=False), next_offset


def render_facts_text(bundle: DiagnosticEvidenceBundle, *,
                      max_chars: int = 3000) -> str:
    """Компактный текстовый блок тех же фактов для LLM-входа чекапа.

    Это НЕ второй источник: строки строятся из того же bundle, что отдаётся
    tool-результатом. Ограничение — engineering-бюджет, не keyword-гейт.
    """
    lines = [f"DIAGNOSTIC_EVIDENCE status={bundle.status} "
             f"observed_at={bundle.observed_at}"]
    for src in bundle.sources:
        lines.append(
            f"- {src.kind} [{src.status}] declared={int(src.declared)} "
            f"configured={int(src.configured)} "
            f"probe_succeeded={int(src.probe_succeeded)} "
            f"healthy={'unknown' if src.healthy is None else int(src.healthy)} "
            f"source={src.source_id}")
        facts = src.facts or {}
        for key, value in facts.items():
            if isinstance(value, (dict, list, tuple)):
                continue
            lines.append(f"    {key}={value}")
        if src.reason_code:
            lines.append(f"    reason_code={src.reason_code}")
    if bundle.not_checked:
        lines.append("not_checked=" + ",".join(bundle.not_checked))
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[facts_budget_exceeded]"
    return text
