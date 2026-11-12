"""SELF-DIAG-01 D3 — общий read-only collector диагностических фактов.

Один сборщик для explicit-чекапа и общего Tool Calling (ТЗ §2.1 п.1):
``inspect_runtime`` и ``get_bot_health`` получают факты из одного
``DiagnosticCollector``, а не из второй инсталляции probes.

Что делает collector:

* валидирует area/probe/scope/time_window/cursor и аргументы зарегистрированной
  операции (LLM не задаёт unit/путь/SQL/чужой chat);
* исполняет один typed probe или сценарий ``investigate_incident`` (сценарий
  существующего координатора, без LLM-стадии и без нового агента);
* собирает ``DiagnosticEvidenceBundle`` с раздельными declared/configured/
  probe_succeeded/healthy, честными статусами и coverage;
* кэширует короткоживущий validated snapshot по
  ``runtime_sha + probe args + scope + permission class`` и дедуплицирует
  одновременные одинаковые запросы; отменённый запрос не кэшируется;
* ничего не пишет в БД и не вызывает LLM.

Сценарий расследования — это набор probes, а не второй оркестратор: факты
получает существующий Writer (через обычный tool-loop).
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
import weakref
from typing import Any, Iterable

from config.settings import settings
from services import deploy_identity
from services import evidence_bundle as bundle
from services import runtime_probes as probes
from services import hot_config as hot
from services import log_ring
from services import output_projection

logger = logging.getLogger(__name__)

#: Ключ подписи cursor: process-local, как у history-cursor (tool_router).
_CURSOR_KEY = secrets.token_bytes(32)


def _cursor_ttl() -> float:
    try:
        from services.tool_loop import TOOL_CHAIN_TIMEOUT_SECONDS
        value = float(getattr(settings, "MCA_TOOL_CHAIN_TIMEOUT_SECONDS",
                              TOOL_CHAIN_TIMEOUT_SECONDS))
        return value if value > 0 else TOOL_CHAIN_TIMEOUT_SECONDS
    except Exception:
        return 360.0


def encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    token = base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")
    token = token.rstrip("=")
    signature = hmac.new(_CURSOR_KEY, raw.encode("ascii"),
                         hashlib.sha256).hexdigest()[:16]
    return f"d3.{token}.{signature}"


def decode_cursor(token: str) -> tuple[dict | None, str]:
    text = str(token or "").strip()
    if not text:
        return None, ""
    parts = text.split(".")
    if len(parts) != 3 or parts[0] != "d3" or not parts[1] or not parts[2]:
        return None, "unknown_cursor"
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(padded).decode("ascii")
    except Exception:
        return None, "unknown_cursor"
    expected = hmac.new(_CURSOR_KEY, raw.encode("ascii"),
                        hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expected, parts[2]):
        return None, "unknown_cursor"
    try:
        payload = json.loads(raw)
    except Exception:
        return None, "unknown_cursor"
    if not isinstance(payload, dict):
        return None, "unknown_cursor"
    try:
        expired = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return None, "unknown_cursor"
    if expired < int(time.time()):
        return None, "stale_cursor"
    return payload, ""


@dataclasses.dataclass(frozen=True)
class CollectionRequest:
    """Разобранный запрос инструмента (без секретов и без чужих id)."""

    probe: str = ""
    area: str = ""
    scope: str = "current_chat"
    time_window: Any = None
    cursor: str = ""
    arguments: dict = dataclasses.field(default_factory=dict)
    chat_id: int | None = None
    permission: dict | None = None
    request_id: str = ""

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps({
            "probe": self.probe,
            "area": self.area,
            "scope": self.scope,
            "time_window": self.time_window,
            "arguments": self.arguments,
            "chat_id": self.chat_id,
            "permission_class": (self.permission or {}).get("data_class"),
            "permission_role": (self.permission or {}).get("role"),
        }, sort_keys=True, ensure_ascii=False, default=str).encode(
            "utf-8")).hexdigest()[:32]


class DiagnosticCollector:
    """Один короткоживущий validated snapshot на совместимые проверки."""

    def __init__(self, *, deps: probes.ProbeDeps | None = None,
                 limits: probes.ProbeLimits | None = None) -> None:
        self.limits = limits or probes.ProbeLimits.from_env()
        self.deps = deps or probes.ProbeDeps()
        if self.deps.redactor is None:
            self.deps.redactor = self._redact
        self._cache: dict[str, tuple[float, dict]] = {}
        self._locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = \
            weakref.WeakValueDictionary()
        self._identity: tuple[float, dict] | None = None

    # ── sanitize ──────────────────────────────────────────────────────────

    @staticmethod
    def _redact(text: str) -> tuple[str, dict]:
        raw = str(text or "")
        try:
            cache = hot.get_config_cache()
            snapshot = output_projection.known_secret_values(cache=cache)
            result = output_projection.sanitize(
                raw, kind="tool_result", secrets=snapshot)
            report = bundle.redaction(
                result.report.redacted, result.report.kinds,
                reason=result.report.reason)
            if not result.allowed:
                # Fail-closed: текст не отдаём, но факт редакции виден.
                return "", report
            return result.text, report
        except Exception:
            cleaned = log_ring.sanitize(raw)
            if cleaned == raw:
                return cleaned, bundle.redaction(0, (),
                                                 reason="no_secret_values")
            return cleaned, bundle.redaction(1, ("pattern",),
                                             reason="pattern_only")

    # ── identity snapshot (кэш по TTL) ────────────────────────────────────

    def _identity_record(self, now: float) -> dict:
        cached = self._identity
        if cached is not None:
            return cached[1]
        return {}

    def _collect_identity_sync(self) -> dict:
        root = probes.default_repo_root(self.deps)
        started = getattr(self.deps.status, "started_at", None)
        collector = self.deps.identity_collector
        try:
            if collector is not None:
                record = collector(root, process_started_at=started)
            else:
                record = deploy_identity.collect_identity(
                    root, process_started_at=started)
            return record if isinstance(record, dict) else {}
        except Exception:
            return {}

    async def _warm_identity(self, now: float) -> dict:
        cached = self._identity
        ttl = float(self.limits.identity_ttl_seconds)
        if cached is not None and ttl > 0 and (now - cached[0]) <= ttl:
            return cached[1]
        record = await asyncio.to_thread(self._collect_identity_sync)
        self._identity = (now, record)
        return record

    # ── cache/dedup ───────────────────────────────────────────────────────

    def _cache_key(self, request: CollectionRequest, now: float) -> str:
        record = self._identity_record(now)
        runtime_sha = str(record.get("deployed_sha") or "")
        config_token = self._config_token()
        return "|".join((
            request.fingerprint(), runtime_sha, config_token,
        ))

    @staticmethod
    def _config_token() -> str:
        try:
            cache = hot.get_config_cache()
            loaded = str(cache.loaded_at()) if cache is not None else ""
        except Exception:
            loaded = ""
        keys = ("flags.checkup_enabled", "limits.checkup_max_symbols",
                "limits.checkup_max_input_symbols",
                "flags.checkup_memory_metrics_enabled",
                "flags.factcheck_enabled", "temporal.tool_enabled",
                "flags.image_generation_module_enabled",
                "flags.lore_compiler_enabled", "flags.graph_rag_enabled",
                "memory.dream_enabled")
        values = []
        for key in keys:
            try:
                values.append(str(hot.get(key, None)))
            except Exception:
                values.append("")
        return hashlib.sha256(("|".join([loaded] + values)).encode(
            "utf-8")).hexdigest()[:16]

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def clear_cache(self) -> None:
        self._cache.clear()
        self._identity = None

    # ── публичный вход ────────────────────────────────────────────────────

    async def collect(self, request: CollectionRequest
                      ) -> tuple[bundle.DiagnosticEvidenceBundle, dict]:
        """(bundle, page) — page уже сериализуем в tool-результат."""
        started = self.deps.monotonic()
        now = float(self.deps.clock())
        request_id = request.request_id or uuid.uuid4().hex
        await self._warm_identity(now)
        page_offset = 0
        cursor_offset = 0
        cursor_payload, cursor_error = decode_cursor(request.cursor)
        if cursor_error:
            return self._error(
                reason=cursor_error,
                status=(bundle.STATUS_STALE if cursor_error == "stale_cursor"
                        else bundle.STATUS_UNSUPPORTED),
                request=request, request_id=request_id, now=now,
                started=started)
        spec = self._resolve_spec(request)
        if isinstance(spec, tuple):        # (reason, status)
            return self._error(reason=spec[0], status=spec[1],
                               request=request, request_id=request_id,
                               now=now, started=started)
        if cursor_payload:
            if str(cursor_payload.get("p")) != spec.probe_id:
                return self._error(reason="unknown_cursor",
                                   status=bundle.STATUS_UNSUPPORTED,
                                   request=request, request_id=request_id,
                                   now=now, started=started)
            kind = str(cursor_payload.get("k") or "")
            try:
                offset = int(cursor_payload.get("o") or 0)
            except (TypeError, ValueError):
                offset = 0
            if kind == "page":
                page_offset = max(0, offset)
            elif kind == "offset":
                cursor_offset = max(0, offset)
            else:
                return self._error(reason="unknown_cursor",
                                   status=bundle.STATUS_UNSUPPORTED,
                                   request=request, request_id=request_id,
                                   now=now, started=started)
        scope_error = self._validate_scope(spec, request)
        if scope_error:
            return self._error(reason=scope_error,
                               status=bundle.STATUS_PERMISSION_DENIED,
                               request=request, request_id=request_id,
                               now=now, started=started)
        if spec.expensive and not self.limits.expensive_enabled:
            return self._error(reason="expensive_probe_disabled",
                               status=bundle.STATUS_NOT_CONFIGURED,
                               request=request, request_id=request_id,
                               now=now, started=started)
        clean_args, arg_error = probes.validate_arguments(spec, request.arguments)
        if arg_error:
            return self._error(
                reason=arg_error,
                status=(bundle.STATUS_PERMISSION_DENIED
                        if arg_error == "argument_not_allowed"
                        else bundle.STATUS_UNSUPPORTED),
                request=request, request_id=request_id, now=now,
                started=started)
        window, window_error = probes.parse_time_window(
            request.time_window, limits=self.limits, now=now,
            default_seconds=spec.default_window_seconds)
        if window_error:
            return self._error(reason=window_error,
                               status=bundle.STATUS_UNSUPPORTED,
                               request=request, request_id=request_id,
                               now=now, started=started)
        ctx = probes.ProbeContext(
            deps=self.deps, limits=self.limits, chat_id=request.chat_id,
            scope=str(request.scope), request_id=request_id,
            arguments=clean_args, time_window=window,
            cursor_offset=cursor_offset, now=now)

        use_cache = not request.cursor
        cache_key = self._cache_key(request, now) if use_cache else ""
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None and cached[0] >= now:
                return self._page(cached[1], spec=spec, request=request,
                                  request_id=request_id, page_offset=page_offset,
                                  started=started, from_cache=True)
            async with self._lock_for(cache_key):
                cached = self._cache.get(cache_key)
                if cached is not None and cached[0] >= now:
                    return self._page(cached[1], spec=spec, request=request,
                                      request_id=request_id,
                                      page_offset=page_offset,
                                      started=started, from_cache=True)
                result = await self._execute(spec, ctx, request, request_id)
                self._store(cache_key, result, now)
        else:
            result = await self._execute(spec, ctx, request, request_id)
        return self._page(result, spec=spec, request=request,
                          request_id=request_id, page_offset=page_offset,
                          started=started, from_cache=False)

    def _store(self, key: str, result: dict, now: float) -> None:
        ttl = float(self.limits.snapshot_ttl_seconds)
        if ttl <= 0:
            return
        # Строго короткоживущий snapshot; старые ключи вычищаются, чтобы
        # process-local кэш не рос бесконечно.
        if len(self._cache) > 64:
            self._cache = {k: v for k, v in self._cache.items() if v[0] >= now}
        self._cache[key] = (now + ttl, result)

    # ── разрешение/валидация ─────────────────────────────────────────────

    def _resolve_spec(self, request: CollectionRequest):
        name = str(request.probe or "").strip()
        if name and "." not in name and request.area:
            name = f"{request.area}.{name}"
        if not name:
            return ("probe_required", bundle.STATUS_UNSUPPORTED)
        spec = probes.get_probe(name)
        if spec is None:
            return ("unknown_probe", bundle.STATUS_UNSUPPORTED)
        if request.area and spec.area != request.area:
            return ("area_probe_mismatch", bundle.STATUS_UNSUPPORTED)
        return spec

    @staticmethod
    def _validate_scope(spec: probes.ProbeSpec,
                        request: CollectionRequest) -> str:
        scope = str(request.scope or "")
        if scope not in probes.REQUEST_SCOPES:
            return "invalid_scope"
        if spec.read_scope == probes.READ_SCOPE_CURRENT_CHAT \
                and scope != "current_chat":
            return "scope_mismatch"
        if spec.read_scope == probes.READ_SCOPE_INSTANCE \
                and scope == "host":
            # host-scope запрос не расширяет instance-probe до чужих данных,
            # но и не притворяется host-wide: отказ честнее.
            return "scope_mismatch"
        return ""

    # ── исполнение ────────────────────────────────────────────────────────

    async def _execute(self, spec: probes.ProbeSpec,
                       ctx: probes.ProbeContext,
                       request: CollectionRequest,
                       request_id: str) -> dict:
        if spec.scenario:
            observations = await self._run_scenario(spec, ctx)
        else:
            observations = [await self._run_probe(spec, ctx)]
        identity = self._identity_atomic(ctx.now)
        return self._build(spec=spec, ctx=ctx, request=request,
                           request_id=request_id,
                           observations=observations, identity=identity)

    async def _run_scenario(self, spec: probes.ProbeSpec,
                            ctx: probes.ProbeContext) -> list[dict]:
        children: list[probes.ProbeSpec] = []
        for child_id in spec.children:
            child = probes.get_probe(child_id)
            if child is None:
                # Регистрация могла не состояться — это не падение сценария,
                # а честно отсутствующий источник.
                continue
            children.append(child)
        results = await asyncio.gather(
            *(self._run_probe(child, ctx) for child in children),
            return_exceptions=True)
        observations = []
        missing = [c for c in spec.children if probes.get_probe(c) is None]
        for child, result in zip(children, results):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                observations.append(self._failed_observation(
                    child, reason="probe_internal_error"))
            else:
                observations.append(result)
        for child_id in missing:
            observations.append(self._missing_observation(child_id, ctx))
        return observations

    async def _run_probe(self, spec: probes.ProbeSpec,
                         ctx: probes.ProbeContext) -> dict:
        missing = probes._missing_dependencies(spec, self.deps)  # noqa: SLF001
        if missing:
            return self._missing_observation(
                spec.probe_id, ctx,
                reason="missing_dependency:" + ",".join(missing))
        if spec.read_scope == probes.READ_SCOPE_CURRENT_CHAT \
                and ctx.chat_id is None:
            return self._missing_observation(
                spec.probe_id, ctx, status=bundle.STATUS_UNAVAILABLE,
                reason="no_chat_scope")
        started = self.deps.monotonic()
        timeout = (float(self.limits.expensive_timeout_seconds)
                   if spec.expensive
                   else float(self.limits.probe_timeout_seconds))
        try:
            value = spec.handler(ctx)
            if asyncio.iscoroutine(value):
                value = await asyncio.wait_for(value, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            return self._failed_observation(spec, reason="probe_timeout",
                                            latency_ms=self._elapsed(started))
        except Exception as exc:
            logger.warning("[self_diag] probe failed | probe=%s | error=%s",
                           spec.probe_id, type(exc).__name__)
            return self._failed_observation(spec, reason="probe_internal_error",
                                            latency_ms=self._elapsed(started))
        latency = self._elapsed(started)
        if not isinstance(value, probes.ProbeObservation):
            return self._failed_observation(spec, reason="invalid_probe_result",
                                            latency_ms=latency)
        return {
            "spec": spec,
            "observation": value,
            "latency_ms": latency,
            "declared": True,
            "configured": True,
        }

    def _elapsed(self, started: float) -> int:
        return max(0, int((self.deps.monotonic() - started) * 1000))

    def _failed_observation(self, spec: probes.ProbeSpec, *, reason: str,
                            latency_ms: int = 0) -> dict:
        observation = probes.ProbeObservation(
            status=bundle.STATUS_UNAVAILABLE,
            facts={}, source_id=f"probe:{spec.probe_id}",
            owner=spec.source_owner,
            coverage=bundle.coverage((spec.probe_id,), complete=False,
                                     why=reason),
            reason_code=reason, not_checked=(spec.probe_id,))
        return {"spec": spec, "observation": observation,
                "latency_ms": latency_ms, "declared": True,
                "configured": True}

    def _missing_observation(self, probe_id: str, ctx: probes.ProbeContext,
                             *, status: str = bundle.STATUS_NOT_CONFIGURED,
                             reason: str = "not_configured") -> dict:
        spec = probes.get_probe(probe_id)
        observation = probes.ProbeObservation(
            status=status, facts={}, source_id=f"probe:{probe_id}",
            owner=spec.source_owner if spec else "runtime",
            coverage=bundle.coverage((probe_id,), complete=False, why=reason),
            reason_code=reason, not_checked=(probe_id,))
        return {"spec": spec, "observation": observation, "latency_ms": 0,
                "declared": bool(spec), "configured": False}

    # ── сборка bundle ─────────────────────────────────────────────────────

    def _identity_atomic(self, now: float) -> dict:
        return self._identity_record(now)

    @staticmethod
    def _compact_facts(value: Any, *, depth: int = 0) -> Any:
        """Bounded facts: длинные строки/списки режутся по engineering-бюджету.

        Это не «обрезка причинного traceback»: stack_summary уже структурный
        (frames + continuation), а здесь ограничивается только объём прочих
        технических полей, чтобы одна область не вытесняла остальные.
        """
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:400]
        if depth >= 4:
            return str(value)[:200]
        if isinstance(value, dict):
            return {str(key)[:80]: DiagnosticCollector._compact_facts(
                item, depth=depth + 1)
                for key, item in list(value.items())[:40]}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [DiagnosticCollector._compact_facts(item, depth=depth + 1)
                    for item in list(value)[:40]]
        return str(value)[:200]

    def _build(self, *, spec: probes.ProbeSpec, ctx: probes.ProbeContext,
               request: CollectionRequest, request_id: str,
               observations: list[dict], identity: dict) -> dict:
        sources: list[bundle.SourceEvidence] = []
        claims: list[dict] = []
        not_checked: list[str] = []
        redacted_total = 0
        redaction_classes: set[str] = set()
        reason_code = None
        for item in observations:
            observation = item["observation"]
            item_spec = item.get("spec")
            source = bundle.SourceEvidence(
                kind=(item_spec.area if item_spec is not None
                      else observation.source_id.split(":", 1)[0]),
                status=observation.status,
                observed_at=bundle.utc_now_iso(ctx.now),
                source_id=observation.source_id,
                owner=observation.owner,
                scope=(item_spec.read_scope if item_spec is not None
                       else spec.read_scope),
                latency_ms=int(item.get("latency_ms") or 0),
                coverage=observation.coverage,
                reason_code=observation.reason_code,
                declared=bool(item.get("declared", True)),
                configured=bool(item.get("configured", True)),
                probe_succeeded=observation.status in (
                    bundle.STATUS_OK, bundle.STATUS_DEGRADED,
                    bundle.STATUS_STALE),
                healthy=observation.healthy,
                verified=observation.verified,
                facts=self._compact_facts(observation.facts),
                not_checked=observation.not_checked,
                redaction=observation.redaction,
                source_ref=observation.source_ref,
            )
            sources.append(source)
            claims.append(bundle.claim(
                bundle.CLAIM_OBSERVED,
                f"{source.source_id}: status={source.status} "
                f"declared={int(source.declared)} "
                f"configured={int(source.configured)} "
                f"probe_succeeded={int(source.probe_succeeded)}",
                [source.source_id]))
            if source.status != bundle.STATUS_OK and reason_code is None:
                reason_code = (source.reason_code
                               or f"source_status:{source.status}")
            not_checked.extend(source.not_checked)
            report = observation.redaction or {}
            redacted_total += int(report.get("redacted_fields") or 0)
            redaction_classes.update(report.get("classes") or ())
            correlated = (observation.facts or {}).get(
                "correlated_failures") or []
            if correlated:
                claims.append(bundle.claim(
                    bundle.CLAIM_CORRELATED,
                    f"{source.source_id}: correlation "
                    f"{(observation.facts or {}).get('correlation_id')} → "
                    f"{len(correlated)} failing stage(s)",
                    [source.source_id]))
            if source.status in (bundle.STATUS_UNAVAILABLE,
                                 bundle.STATUS_NOT_CONFIGURED,
                                 bundle.STATUS_UNSUPPORTED,
                                 bundle.STATUS_NOT_CHECKED):
                claims.append(bundle.claim(
                    bundle.CLAIM_NOT_CHECKED,
                    f"{source.source_id}: {source.status}"
                    f"{'/' + source.reason_code if source.reason_code else ''}",
                    [source.source_id]))
        if spec.scenario:
            claims.append(bundle.claim(
                bundle.CLAIM_OBSERVED,
                f"scenario {spec.probe_id}: {len(sources)} source(s) "
                "collected by existing tool coordinator",
                [s.source_id for s in sources]))
        record = identity or {}
        code = str(record.get("code") or "")
        verification = {
            "verified_deployed": True,
            "local_unverified": False,
            "unavailable": False,
            "permission_denied": False,
        }.get(code)
        access = self._access(request, spec.read_scope, spec)
        observed_at = bundle.utc_now_iso(ctx.now)
        result_bundle = bundle.build_bundle(
            request_id=request_id,
            chat_scope=("current_chat" if ctx.chat_id is not None
                        else "instance"),
            scope=str(request.scope),
            sources=sources,
            claims=claims,
            access=access,
            observed_at=observed_at,
            latency_ms=0,
            runtime={
                "service_identity": ("verified" if code == "verified_deployed"
                                     else "unknown"),
                "deployed_sha": record.get("deployed_sha"),
                "deploy_code": code or None,
                "repo_origin": record.get("repo_origin"),
                "runtime_kind": probes.runtime_identity().get("kind"),
            },
            not_checked=not_checked,
            redaction_report=bundle.redaction(
                redacted_total, redaction_classes,
                reason=("secret_fragments_removed" if redacted_total
                        else "no_secret_values")),
            reason_code=reason_code,
            runtime_sha=record.get("deployed_sha"),
            git_head_sha=record.get("checkout_sha"),
            source_verified=verification,
            commits_since_deploy=None,
            git_metadata_attempted=bool(record),
            code_lookup_attempted=False,
            request={"probe": spec.probe_id, "area": spec.area,
                     "arguments": ctx.arguments,
                     "time_window": list(ctx.time_window)
                     if ctx.time_window else None},
        )
        observation_next = None
        if len(observations) == 1:
            observation_next = observations[0]["observation"].next_offset
        return {"bundle": result_bundle,
                "observed_at": observed_at,
                "probe_next_offset": observation_next,
                "from_cache": False}

    @staticmethod
    def _access(request: CollectionRequest,
                read_scope: str,
                spec: probes.ProbeSpec | None = None) -> dict:
        decision = request.permission or {}
        evaluated = bool(decision.get("evaluated", bool(decision)))
        return {
            "resource_scope": str(request.scope),
            "chat_id": request.chat_id,
            "read_scope": read_scope,
            "data_class": decision.get("data_class") or "PUBLIC_TECH",
            "projection": ("chat_scoped"
                           if read_scope == probes.READ_SCOPE_CURRENT_CHAT
                           else "public_tech"),
            "permission_decision": {
                "evaluated": evaluated,
                "effect": decision.get("effect"),
                "reason_code": (decision.get("reason_code")
                                or ("gate_not_invoked" if not evaluated
                                    else None)),
                "capability": decision.get("capability"),
                "action": decision.get("action"),
                "role": decision.get("role"),
                "matrix_role": decision.get("matrix_role"),
                "source": decision.get("source"),
            },
        }

    def _page(self, result: dict, *, spec: probes.ProbeSpec,
              request: CollectionRequest, request_id: str,
              page_offset: int, started: float, from_cache: bool) -> \
            tuple[bundle.DiagnosticEvidenceBundle, dict]:
        result_bundle = result["bundle"]
        # latency_ms — длительность сбора, не время генерации ответа.
        final_bundle = dataclasses.replace(
            result_bundle, latency_ms=self._elapsed(started))
        page, next_offset = bundle.render_page(
            final_bundle, max_chars=int(self.limits.max_output_chars),
            offset=page_offset)
        page["schema"] = bundle.BUNDLE_SCHEMA
        page["from_cache"] = bool(from_cache)
        page["probe"] = spec.probe_id
        if next_offset < len(final_bundle.sources):
            page["next_cursor"] = encode_cursor({
                "v": 1, "p": spec.probe_id, "k": "page", "o": next_offset,
                "c": request.chat_id, "exp": int(time.time() + _cursor_ttl()),
            })
        probe_next = result.get("probe_next_offset")
        if probe_next is not None:
            page["probe_next_cursor"] = encode_cursor({
                "v": 1, "p": spec.probe_id, "k": "offset",
                "o": int(probe_next), "c": request.chat_id,
                "exp": int(time.time() + _cursor_ttl()),
            })
        return final_bundle, page

    # ── ошибки запроса ────────────────────────────────────────────────────

    def _error(self, *, reason: str, status: str,
               request: CollectionRequest, request_id: str, now: float,
               started: float) -> tuple[bundle.DiagnosticEvidenceBundle, dict]:
        source = bundle.SourceEvidence(
            kind="request", status=status,
            observed_at=bundle.utc_now_iso(now),
            source_id=f"request:{reason}", owner="collector",
            scope=str(request.scope or "current_chat"),
            coverage=bundle.coverage(("request",), complete=False,
                                     why=reason),
            reason_code=reason, declared=False, configured=False,
            probe_succeeded=False, healthy=None,
            facts={"probe": request.probe, "area": request.area})
        record = self._identity_record(now)
        code = str(record.get("code") or "")
        result_bundle = bundle.build_bundle(
            request_id=request_id,
            chat_scope=("current_chat" if request.chat_id is not None
                        else "instance"),
            scope=str(request.scope or "current_chat"),
            sources=[source],
            claims=[bundle.claim(
                bundle.CLAIM_NOT_CHECKED,
                f"request rejected: {reason}", [source.source_id])],
            access=self._access(request, probes.READ_SCOPE_INSTANCE),
            observed_at=bundle.utc_now_iso(now),
            latency_ms=self._elapsed(started),
            runtime={"service_identity": "unknown"},
            not_checked=(reason,),
            reason_code=reason,
            runtime_sha=record.get("deployed_sha"),
            git_head_sha=record.get("checkout_sha"),
            source_verified=None,
            git_metadata_attempted=bool(record),
            request={"probe": request.probe, "area": request.area})
        page, _ = bundle.render_page(
            result_bundle, max_chars=int(self.limits.max_output_chars))
        page["schema"] = bundle.BUNDLE_SCHEMA
        page["probe"] = request.probe
        page["from_cache"] = False
        return result_bundle, page

    # ── explicit-чекап: те же факты для второго входа ─────────────────────

    async def collect_for_checkup(self, *, logs_text: str,
                                  used_fallback: bool,
                                  chat_id: int | None = None,
                                  permission: dict | None = None,
                                  request_id: str = "") -> tuple[
                                      bundle.DiagnosticEvidenceBundle, str]:
        """Один collector для explicit-чекапа и tool-loop (ТЗ §2.1 п.1).

        Логи уже прочитаны хендлером (второй раз journal не читается), но
        остальные probes — тот же реестр и тот же bundle, что у
        ``inspect_runtime``. Возвращает (bundle, компактный facts-блок).
        """
        started = self.deps.monotonic()
        now = float(self.deps.clock())
        request_id = request_id or uuid.uuid4().hex
        await self._warm_identity(now)
        checks = (
            "deploy.identity", "process.self", "resources.cpu",
            "resources.memory", "disks.usage", "scheduler.jobs",
            "memory.health", "dependencies.providers", "incidents.active",
            "config.effective", "logs.errors", "telegram.delivery",
            "media.stt",
        )
        specs = [probes.get_probe(name) for name in checks]
        active = [spec for spec in specs if spec is not None]
        ctx = probes.ProbeContext(
            deps=self.deps, limits=self.limits, chat_id=chat_id,
            scope="current_chat", request_id=request_id,
            arguments={}, time_window=(max(0, int(now) - 3600), int(now)),
            now=now)
        results = await asyncio.gather(
            *(self._run_probe(spec, ctx) for spec in active),
            return_exceptions=True)
        observations: list[dict] = []
        for spec, result in zip(active, results):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                observations.append(self._failed_observation(
                    spec, reason="probe_internal_error"))
            else:
                observations.append(result)
        lines = [line for line in str(logs_text or "").splitlines()
                 if line.strip()]
        observations.append({
            "spec": None,
            "observation": probes.ProbeObservation(
                status=bundle.STATUS_OK,
                facts={"backend": "provided_by_checkup_handler",
                       "window_lines": len(lines),
                       "used_fallback": bool(used_fallback)},
                source_id="logs:checkup_input", owner="journal",
                coverage=bundle.coverage(("local_logs",),
                                         complete=not used_fallback,
                                         truncated=bool(used_fallback),
                                         why=("fallback_source"
                                              if used_fallback else "")),
                reason_code=None, not_checked=("journal_contents",)),
            "latency_ms": 0, "declared": True, "configured": True,
        })
        spec = probes.ProbeSpec(
            "logs.checkup", "logs", "checkup facts", "",
            probes.READ_SCOPE_CURRENT_CHAT, scenario=True,
            children=tuple(checks))
        request = CollectionRequest(
            probe=spec.probe_id, area="logs", scope="current_chat",
            chat_id=chat_id, permission=permission, request_id=request_id)
        result = self._build(spec=spec, ctx=ctx, request=request,
                             request_id=request_id,
                             observations=observations,
                             identity=self._identity_record(now))
        facts_text = bundle.render_facts_text(
            result["bundle"], max_chars=int(self.limits.max_facts_chars))
        return result["bundle"], facts_text
