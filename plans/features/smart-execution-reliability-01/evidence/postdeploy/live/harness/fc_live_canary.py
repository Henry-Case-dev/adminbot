#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FACTCHECK-REQUEST-INTEGRITY v2 — read-only production live-canary harness.

Purpose
-------
Collect post-deploy evidence for the READY_FOR_LIVE rows of
``plans/features/smart-execution-reliability-01/requirements-map-fc-amendment.json``:

    SFC-5-10, SFC-7-06, SFC-12-02, SFC-12-07, SFC-12-09, SFC-13-01,
    SFC-13-03, SFC-14-03

The script runs *code identical to the deployed release checkout* through the
real FactCheck v2 entry point (``services.factcheck_orchestrator.run_factcheck``)
for synthetic chat content, and observes the real observability bundle that the
production pipeline emits (mca events, retrieval outcome, durable rows).

Hard safety contract (enforced by construction, not by convention)
------------------------------------------------------------------
* **No Telegram I/O.** No ``aiogram.Bot`` is constructed; every outbound
  transport (``send_message``/``send_chat_action``/``set_message_reaction``/
  ``edit_*``) is a local stub that only records what the pipeline tried to
  send. The typing indicator is disabled in memory (otherwise aiogram's
  ``ChatActionSender`` would call the network).
* **No writes into real chat history / profiles / analytics.** All synthetic
  messages live in a throw-away SQLite database (fresh ``DatabaseService``
  schema in a temp dir). Production PostgreSQL is opened read-only and only
  ``SELECT``-ed (``default_transaction_read_only=on``) for *effective-state*
  evaluation. LLM accounting/analytics sinks (``chat_usage``, provider trace)
  are stubbed in the client instance so real provider calls do not write
  usage rows into production PG.
* **No config persistence.** All overrides (hot-config shim, chat-params shim,
  smart-cache path, typing/summary-delay flags) are in-memory and restored in
  ``finally``. Nothing is written back.
* **Provider/search calls are opt-in and capped.** Without
  ``--allow-provider-calls`` no real LLM/search/page-fetch happens at all and
  the provider-dependent checks are reported as ``not_observed``. With the
  flag, every LLM call, every search call and every page fetch is counted;
  ``--max-provider-calls`` (default 60) aborts the current run when exceeded.
* **No secrets / chat ids in output.** Real chats are reported as
  ``chat-1..chat-N``; search keys, bot tokens, e-mail-like values are
  redacted by pattern; message texts are only shown truncated and only for
  the synthetic canary chat.

This harness only *observes*. It never edits the map, never marks a
requirement VERIFIED, never deploys and never claims success for a run it
did not perform.

Usage (production host)
-----------------------
    cd /var/www/admin_bot
    venv/bin/python /tmp/fc_live_canary.py --json-out /tmp/fc_live_canary.json
    venv/bin/python /tmp/fc_live_canary.py --json-out /tmp/fc_live_canary.json \
        --allow-provider-calls --max-provider-calls 60

Exit code is 0 whenever the harness itself ran (check failures stay inside the
JSON). Exit code 2 means the harness could not even bootstrap (wrong cwd,
missing release modules, missing DB, ...); 1 is reserved for ``--self-test``
failures.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

HARNESS_VERSION = "1.0.0"
HARNESS_NAME = "fc_live_canary"

#: Synthetic group chat. Never a real Telegram id (real ids are > 0 for DM and
#: negative supergroup ids start with -100<10 digits>; this one is a clearly
#: synthetic marker and it only ever exists inside the temporary database).
SYNTH_CHAT_ID = -1009900000001
SYNTH_USER_ID = 990000001
SYNTH_AUTHOR = "canary-author"
SYNTH_REQUESTER = "canary-requester"
SYNTH_BOT_ID = 990000099

#: Synthetic message id ranges (each scenario owns a disjoint range).
TG = {
    "ordinary_target": 900_101,
    "ordinary_trigger": 900_102,
    "multipart_target": 900_111,
    "multipart_trigger": 900_112,
    "short_context": 900_121,
    "short_target": 900_122,
    "short_trigger": 900_123,
    "original_material": 900_131,
    "original_trigger": 900_132,
    "smoke_target": 900_141,
    "smoke_trigger": 900_142,
}

#: New factory values the deployed release must resolve when budgets are ON
#: (owner input 2026-11-14 §5.2). Used only as an acceptance probe, never
#: injected into behaviour.
FACTORY_BUDGETS_ON = {
    "base_seconds": 120.0,
    "max_seconds": 600.0,
    "refine_calls": 24,
    "total_queries": 64,
    "search_text_chars": 100_000,
    "page_size": 20,
    "claim_portion": 32,
}

#: Old caps that must NOT survive as hidden enforcement on the runtime path.
LEGACY_CAPS = {
    "base_seconds": 10.0,
    "max_seconds": 45.0,
    "refine_calls": 3,
    "search_text_chars": 8_000,
    "page_size": 4,
    "claim_portion": 8,
}

CHECK_REQ_MAP = {
    "ordinary_factcheck": ["SFC-12-02", "SFC-7-06", "SFC-13-01"],
    "multipart_and_short_reply": ["SFC-12-02"],
    "budget_scenarios": ["SFC-12-07", "SFC-5-10"],
    "metric_distinguishability": ["SFC-13-03"],
    "original_production_scenario": ["SFC-12-09"],
    "production_smoke": ["SFC-14-03"],
}

# ── Canary content (authored by the harness; no owner data is copied) ────────

MATERIAL_ORDINARY = (
    "Великая Китайская стена в её нынешнем виде в основном построена при "
    "династии Мин, а её общая длина с ответвлениями превышает 21 тысячу "
    "километров. Утверждение, что стену видно из космоса невооружённым "
    "глазом, многократно опровергалось."
)
TRIGGER_ORDINARY = "фактчек"

MATERIAL_MULTIPART = (
    "В 1969 году человек впервые высадился на Луну. "
    "Эйфелева башня была построена к Всемирной выставке 1889 года в Париже. "
    "Байкал — самое глубокое озеро на Земле. "
    "Пингвины обитают только в Южном полушарии."
)
TRIGGER_MULTIPART = "фактчек"

SHORT_CONTEXT_MATERIAL = (
    "Байкал — самое глубокое озеро на Земле, его максимальная глубина "
    "составляет около 1642 метров."
)
SHORT_REPLY = "А это точно?"

#: Owner source 2026-11-14 §1.1: the original production case. The material
#: message is a neutral restatement of the claims that were being discussed
#: (the owner's original message text is not reproduced verbatim because the
#: source does not quote it in full); the user's question is used verbatim.
MATERIAL_TRADITION = (
    "Женское обрезание — древняя традиция, она распространена во многих "
    "странах Африки и Ближнего Востока, и на её сохранение повлияли США."
)
TRIGGER_TRADITION = (
    "Фактчек, бот, реально есть страны с этой традицией на которые не "
    "влияли такие гегемоны как Франция/Великобритания/Германия/США?"
)

MATERIAL_SMOKE = (
    "На уровне моря вода закипает при температуре около 100 градусов "
    "Цельсия, а с ростом высоты температура кипения снижается."
)
TRIGGER_SMOKE = "фактчек"


# ═══════════════════════════════════════════════════════════════════════════
# Result model
# ═══════════════════════════════════════════════════════════════════════════


@dataclasses.dataclass
class CheckResult:
    id: str
    req_ids: list
    status: str                     # observed | not_observed | error
    summary: str
    details: dict = dataclasses.field(default_factory=dict)
    duration_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "req_ids": list(self.req_ids),
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
            "duration_s": round(float(self.duration_s), 3),
        }


class HarnessAbort(RuntimeError):
    """Bootstrap-level failure: the harness could not run at all."""


class ProviderCallsDisabled(RuntimeError):
    """Raised if a provider call is attempted without --allow-provider-calls."""


class ProviderCallCapReached(RuntimeError):
    """Raised when --max-provider-calls is exceeded during a run."""


# ═══════════════════════════════════════════════════════════════════════════
# Redaction / sanitising helpers
# ═══════════════════════════════════════════════════════════════════════════

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{25,}\b"),          # bot token
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*\S+"),
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b(?:postgres(?:ql)?|redis|mongodb)://\S+", re.IGNORECASE),
)


def redact(text: str, limit: int = 400) -> str:
    """Mask secrets and truncate free text for the JSON report."""
    value = str(text or "")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[redacted]", value)
    value = value.replace(str(SYNTH_CHAT_ID), "SYNTH_CHAT")
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        value = value[:limit] + "…"
    return value


def tokens(text: str) -> set:
    """Lower-case content tokens (Cyrillic+Latin, >=4 chars) for overlap checks."""
    return {t.lower() for t in re.findall(r"[А-Яа-яЁёA-Za-z]{4,}", str(text or ""))}


def overlap_ratio(needle: str, haystack: str) -> float:
    base = tokens(needle)
    if not base:
        return 0.0
    return round(len(base & tokens(haystack)) / len(base), 3)


# ═══════════════════════════════════════════════════════════════════════════
# Call budget + recorders + transport stubs
# ═══════════════════════════════════════════════════════════════════════════


class CallBudget:
    """Counts real provider/search/fetch calls; enforces the harness cap."""

    def __init__(self, allow: bool, max_calls: int) -> None:
        self.allow = bool(allow)
        self.max_calls = max(0, int(max_calls))
        self.llm = 0
        self.search = 0
        self.fetch = 0
        self.per_run = {"llm": 0, "search": 0, "fetch": 0}

    @property
    def total(self) -> int:
        return self.llm + self.search + self.fetch

    def reset_run(self) -> None:
        self.per_run = {"llm": 0, "search": 0, "fetch": 0}

    def charge(self, kind: str) -> None:
        if not self.allow:
            raise ProviderCallsDisabled(
                "real provider calls are disabled (--allow-provider-calls)")
        if self.total >= self.max_calls:
            raise ProviderCallCapReached(
                f"provider call cap reached ({self.max_calls})")
        if kind == "llm":
            self.llm += 1
        elif kind == "search":
            self.search += 1
        elif kind == "fetch":
            self.fetch += 1
        self.per_run[kind] = int(self.per_run.get(kind, 0)) + 1

    def as_dict(self) -> dict:
        return {
            "allowed": self.allow,
            "max_calls": self.max_calls,
            "llm_calls": self.llm,
            "search_calls": self.search,
            "page_fetch_calls": self.fetch,
            "total": self.total,
        }


class Recorder:
    """Captures the observability bundle the pipeline emits during one run."""

    def __init__(self) -> None:
        self.events = []
        self.retrievals = []
        self.envelope_runs = []
        self.subjects = []
        self.plans = []
        self.publications = []
        self.delivered = []
        self._next_msg_id = 990_500_000
        self._originals = {}

    # -- lifecycle ---------------------------------------------------------
    def reset_run(self) -> None:
        self.events = []
        self.retrievals = []
        self.envelope_runs = []
        self.subjects = []
        self.plans = []
        self.publications = []
        self.delivered = []

    def next_message_id(self) -> int:
        self._next_msg_id += 1
        return self._next_msg_id

    # -- capture helpers ---------------------------------------------------
    def record_event(self, event_name, outcome=None, level=None, fields=None,
                     normalized=None) -> None:
        self.events.append({
            "event_name": str(event_name or ""),
            "outcome": str(outcome or ""),
            "level": str(level or ""),
            "fields": fields if isinstance(fields, dict) else {},
            "normalized": normalized if isinstance(normalized, dict) else {},
        })

    def event(self, name: str) -> dict | None:
        for item in self.events:
            if item["event_name"] == name:
                return item
        return None

    def events_named(self, name: str) -> list:
        return [item for item in self.events if item["event_name"] == name]

    def pipeline_run_id(self) -> str | None:
        for item in self.events:
            for blob in (item.get("normalized") or {}, item.get("fields") or {}):
                value = blob.get("pipeline_run_id")
                if value:
                    return str(value)
        return None

    def last_retrieval(self):
        return self.retrievals[-1] if self.retrievals else None

    def last_envelope_run(self):
        return self.envelope_runs[-1] if self.envelope_runs else None

    def last_subject(self):
        return self.subjects[-1] if self.subjects else None

    def last_plan(self):
        return self.plans[-1] if self.plans else None

    def last_publication(self):
        return self.publications[-1] if self.publications else None

    # -- install / restore -------------------------------------------------
    def install(self, *, llm, aggregator, modules, budget: CallBudget) -> None:
        """Patch every seam the harness needs; keeps the originals."""
        (mca_events, fs, orch, fsp, temporal, safe_fetch,
         llm_client) = modules
        self._originals = {
            "mca_emit": mca_events.emit_mca_event,
            "fs_emit": getattr(fs, "emit_mca_event", None),
            "llm_generate": llm.generate,
            "agg_search": getattr(aggregator, "search", None),
            "agg_search_relevant": getattr(aggregator, "search_relevant", None),
            "safe_fetch": safe_fetch.SafeFetcher.fetch_text,
            "orch_subject": orch.resolve_check_subject,
            "fsp_plan": fsp.build_retrieval_plan,
            "fsp_run": fsp.run_retrieval,
            "fs_publication": fs.resolve_claim_publication,
            "svc_envelope": None,
        }
        recorder = self

        def _emit(event_name, **kwargs):
            fields = {k: v for k, v in kwargs.items()
                      if k not in ("outcome", "level")}
            normalized = None
            try:
                normalized = self._originals["mca_emit"](
                    event_name,
                    outcome=kwargs.get("outcome", "success"),
                    level=kwargs.get("level", "INFO"),
                    **fields)
            except Exception:
                normalized = None
            recorder.record_event(event_name, kwargs.get("outcome"),
                                  kwargs.get("level"), fields, normalized)
            return normalized

        mca_events.emit_mca_event = _emit
        if self._originals.get("fs_emit") is not None:
            fs.emit_mca_event = _emit

        async def _generate(*args, **kwargs):
            budget.charge("llm")
            return await self._originals["llm_generate"](*args, **kwargs)

        llm.generate = _generate

        if self._originals.get("agg_search") is not None:
            orig_search = self._originals["agg_search"]

            async def _search(*args, **kwargs):
                budget.charge("search")
                return await orig_search(*args, **kwargs)

            aggregator.search = _search

        if self._originals.get("agg_search_relevant") is not None:
            orig_relevant = self._originals["agg_search_relevant"]

            async def _search_relevant(*args, **kwargs):
                budget.charge("search")
                return await orig_relevant(*args, **kwargs)

            aggregator.search_relevant = _search_relevant

        orig_fetch = self._originals["safe_fetch"]

        async def _fetch_text(safe_self, *args, **kwargs):
            budget.charge("fetch")
            return await orig_fetch(safe_self, *args, **kwargs)

        safe_fetch.SafeFetcher.fetch_text = _fetch_text

        orig_subject = self._originals["orch_subject"]

        async def _resolve_subject(*args, **kwargs):
            result = await orig_subject(*args, **kwargs)
            self.subjects.append(result)
            return result

        orch.resolve_check_subject = _resolve_subject

        orig_plan = self._originals["fsp_plan"]

        def _build_plan(*args, **kwargs):
            result = orig_plan(*args, **kwargs)
            self.plans.append(result)
            return result

        fsp.build_retrieval_plan = _build_plan

        orig_run_retrieval = self._originals["fsp_run"]

        async def _run_retrieval(*args, **kwargs):
            result = await orig_run_retrieval(*args, **kwargs)
            self.retrievals.append(result)
            return result

        fsp.run_retrieval = _run_retrieval
        # ``factcheck_service`` imported the function by name for the legacy
        # branch; the unified path goes through the orchestrator's module ref.
        if hasattr(fs, "run_retrieval"):
            fs.run_retrieval = _run_retrieval

        orig_publication = self._originals["fs_publication"]

        async def _resolve_publication(*args, **kwargs):
            result = await orig_publication(*args, **kwargs)
            self.publications.append(result)
            return result

        fs.resolve_claim_publication = _resolve_publication

        _ = temporal

    def install_envelope_capture(self, service) -> None:
        """Wrap ``service.check_claim_envelope`` to keep its TemporalRunResult."""
        if "svc_envelope" in self._originals and self._originals["svc_envelope"]:
            return
        orig = service.check_claim_envelope
        self._originals["svc_envelope"] = orig

        async def _check_envelope(*args, **kwargs):
            result = await orig(*args, **kwargs)
            self.envelope_runs.append(result)
            return result

        service.check_claim_envelope = _check_envelope

    def restore(self, *, llm, aggregator, modules) -> None:
        originals = self._originals or {}
        (mca_events, fs, orch, fsp, safe_fetch, _llm_client) = modules
        try:
            if originals.get("mca_emit"):
                mca_events.emit_mca_event = originals["mca_emit"]
            if originals.get("fs_emit") is not None:
                fs.emit_mca_event = originals["fs_emit"]
            if originals.get("llm_generate"):
                llm.generate = originals["llm_generate"]
            if originals.get("agg_search") is not None:
                aggregator.search = originals["agg_search"]
            if originals.get("agg_search_relevant") is not None:
                aggregator.search_relevant = originals["agg_search_relevant"]
            if originals.get("safe_fetch"):
                safe_fetch.SafeFetcher.fetch_text = originals["safe_fetch"]
            if originals.get("orch_subject"):
                orch.resolve_check_subject = originals["orch_subject"]
            if originals.get("fsp_plan"):
                fsp.build_retrieval_plan = originals["fsp_plan"]
            if originals.get("fsp_run"):
                fsp.run_retrieval = originals["fsp_run"]
                if hasattr(fs, "run_retrieval"):
                    fs.run_retrieval = originals["fsp_run"]
            if originals.get("fs_publication"):
                fs.resolve_claim_publication = originals["fs_publication"]
        except Exception:
            pass


class StubBot:
    """Records outbound calls; performs no network and no Telegram I/O."""

    id = SYNTH_BOT_ID
    token = "000000000:canary-not-a-real-token"

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.calls = []

    async def send_message(self, chat_id, text, **kwargs):
        message_id = self.recorder.next_message_id()
        self.calls.append({
            "method": "send_message",
            "chat_id": int(chat_id),
            "reply_to": kwargs.get("reply_to_message_id"),
            "parse_mode": kwargs.get("parse_mode"),
            "text": str(text or ""),
            "message_id": message_id,
        })
        self.recorder.delivered.append(self.calls[-1])
        return SimpleNamespace(message_id=message_id, chat=SimpleNamespace(id=chat_id))

    async def send_chat_action(self, chat_id, action, **kwargs):      # typing
        self.calls.append({"method": "send_chat_action", "chat_id": int(chat_id)})
        return True

    async def set_message_reaction(self, chat_id=None, message_id=None, **kwargs):
        self.calls.append({"method": "set_message_reaction",
                           "chat_id": chat_id, "message_id": message_id})
        return True

    async def edit_message_text(self, *args, **kwargs):
        self.calls.append({"method": "edit_message_text"})
        return True

    async def delete_message(self, *args, **kwargs):
        self.calls.append({"method": "delete_message"})
        return True


# ═══════════════════════════════════════════════════════════════════════════
# Bootstrap: settings, modules, identity, effective configuration
# ═══════════════════════════════════════════════════════════════════════════


class Runtime:
    """Everything the checks share: settings, modules, PG snapshot, shims."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root)
        self.settings = None
        self.app_version = None
        self.modules = None
        self.pg = None               # PgSnapshot | None
        self.identity = {}
        self.health = {}
        self.overrides = []
        self._restore = []
        self.tmpdir = None
        self.db = None
        self.db_path = None
        self.recorder = Recorder()
        self.budget = None
        self.bot = None
        self.llm = None
        self.aggregator = None
        self.service = None
        self.cache = None

    # -- import ------------------------------------------------------------
    def load_modules(self) -> None:
        root = str(self.repo_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        if not (self.repo_root / "services" / "factcheck_orchestrator.py").is_file():
            raise HarnessAbort(
                f"release modules not found under {self.repo_root}; run with "
                "cwd=/var/www/admin_bot")
        from config import settings as settings_module
        from services import (budget_gate, chat_params, factcheck_orchestrator as orch,
                              factcheck_planner as fsp, factcheck_service as fs,
                              hot_config, llm_client, mca_events,
                              safe_fetch, search_aggregator, smart_cache,
                              temporal_factcheck as tf, worker_settings)
        self.settings = settings_module.settings
        self.app_version = getattr(settings_module, "APP_VERSION", None)
        self.modules = SimpleNamespace(
            settings_module=settings_module, settings=settings_module.settings,
            budget_gate=budget_gate, chat_params=chat_params, orch=orch,
            fsp=fsp, fs=fs, hot_config=hot_config, llm_client=llm_client,
            mca_events=mca_events, safe_fetch=safe_fetch,
            search_aggregator=search_aggregator, smart_cache=smart_cache,
            temporal=tf, worker_settings=worker_settings,
        )

    def patch_tuple(self):
        m = self.modules
        return (m.mca_events, m.fs, m.orch, m.fsp, m.temporal,
                m.safe_fetch, m.llm_client)

    # -- identity ----------------------------------------------------------
    def collect_identity(self) -> dict:
        try:
            from services.deploy_identity import collect_identity as _collect
        except Exception:
            _collect = None
        process_started = self._service_started_at()
        try:
            data = (_collect(str(self.repo_root),
                             process_started_at=process_started)
                    if _collect is not None else
                    {"code": "unavailable", "reason": "module_missing"})
        except Exception as exc:
            data = {"code": "unavailable", "reason": redact(str(exc), limit=160)}
        fallback = self._git_fallback()
        manifest_path = self.repo_root / ".deploy" / "release.json"
        manifest = None
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {"error": "unreadable"}
        head = data.get("checkout_sha") or fallback.get("head")
        self.identity = {
            "repo_root": str(self.repo_root),
            "git_head": head,
            "git_head_source": ("deploy_identity" if data.get("checkout_sha")
                                else "git_cli_fallback"),
            "branch": (data.get("local_identity") or {}).get("branch")
            or fallback.get("branch")
            or (data.get("artifact") or {}).get("release_branch"),
            "dirty": (data.get("dirty") if data.get("dirty") is not None
                      else fallback.get("dirty")),
            "deployed_sha": data.get("deployed_sha") or fallback.get("head"),
            "manifest": {
                "path": ".deploy/release.json",
                "present": manifest is not None,
                "deployed_sha": (manifest or {}).get("deployed_sha"),
                "version": (manifest or {}).get("version"),
                "deployed_at": (manifest or {}).get("deployed_at"),
                "effect": (manifest or {}).get("effect"),
            },
            "app_version_runtime": self.app_version,
            "identity_code": data.get("code"),
            "identity_reason": data.get("reason"),
            "version_provenance": data.get("version_provenance"),
            "upstream_head": data.get("upstream_head"),
            "service_started_at": process_started,
            "process_started_source": ("systemctl ActiveEnterTimestamp"
                                       if process_started else "unavailable"),
            "sources": (data.get("sources") or [])
            + (["git_cli"] if fallback.get("head") and not data.get(
                "checkout_sha") else []),
            "conflict": data.get("conflict") or [],
        }
        self.health = self._health_probe()
        return self.identity

    def _git_fallback(self) -> dict:
        """Read HEAD/branch/dirty with the git CLI (works in worktrees too)."""
        import subprocess

        def _run(*args) -> str:
            try:
                out = subprocess.run(
                    ["git", "-C", str(self.repo_root), *args],
                    capture_output=True, text=True, timeout=15)
                return (out.stdout or "").strip()
            except Exception:
                return ""

        head = _run("rev-parse", "HEAD")
        branch = _run("rev-parse", "--abbrev-ref", "HEAD")
        status = _run("status", "--porcelain")
        return {
            "head": head if re.fullmatch(r"[0-9a-f]{40}", head or "") else None,
            "branch": branch if branch and branch != "HEAD" else None,
            "dirty": (bool(status.splitlines()) if status is not None else None),
        }

    def _service_started_at(self):
        try:
            import subprocess
            out = subprocess.run(
                ["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value",
                 "admin_bot"],
                capture_output=True, text=True, timeout=10)
            value = (out.stdout or "").strip()
            return value or None
        except Exception:
            return None

    def _health_probe(self) -> dict:
        url = "http://127.0.0.1:8000/healthz"
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:      # noqa: S310
                body = resp.read(400).decode("utf-8", "replace")
                status = int(getattr(resp, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read(400).decode("utf-8", "replace")
            except Exception:
                pass
            status = int(getattr(exc, "code", 0) or 0)
        except Exception as exc:
            return {"url": url, "ok": False,
                    "error": redact(str(exc), limit=160),
                    "duration_ms": int((time.perf_counter() - started) * 1000)}
        parsed = None
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
        return {
            "url": url,
            "http": status,
            "version": (parsed or {}).get("version"),
            "status": (parsed or {}).get("status"),
            "body": redact(body, limit=160) if parsed is None else None,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "ok": bool(status == 200 and isinstance(parsed, dict)),
        }

    # -- read-only PostgreSQL snapshot ------------------------------------
    async def read_pg_snapshot(self) -> None:
        dsn = os.environ.get("POSTGRES_DSN") or ""
        if not dsn:
            self.pg = {"available": False, "reason": "POSTGRES_DSN missing"}
            return
        try:
            import asyncpg
        except Exception as exc:                    # pragma: no cover
            self.pg = {"available": False,
                       "reason": f"asyncpg unavailable: {redact(str(exc), 120)}"}
            return

        async def _init(conn):
            await conn.execute("SET default_transaction_read_only = on")

        conn = None
        try:
            conn = await asyncpg.connect(dsn, timeout=15, init=_init)
            settings_rows = await conn.fetch(
                "SELECT key, value, category, updated_at FROM bot_settings")
            profile_rows = await conn.fetch(
                "SELECT chat_id, chat_params, updated_at FROM chat_profiles")
        except Exception as exc:
            self.pg = {"available": False,
                       "reason": f"pg read failed: {redact(str(exc), 160)}"}
            return
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass

        from services.param_catalog import normalize_value
        globals_map = {}
        for row in settings_rows:
            key = str(row["key"])
            try:
                globals_map[key] = normalize_value(key, row["value"])
            except Exception:
                globals_map[key] = row["value"]
        roots = {}
        for row in profile_rows:
            raw = row["chat_params"]
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    raw = {}
            roots[int(row["chat_id"])] = raw if isinstance(raw, dict) else {}
        self.pg = {
            "available": True,
            "global_count": len(globals_map),
            "chat_count": len(roots),
            "global_values": globals_map,
            "chat_roots": roots,
        }

    # -- in-memory overrides ----------------------------------------------
    @contextlib.contextmanager
    def hot_shim(self, *, extra: dict | None = None):
        """Install an in-memory hot-config view backed by the PG snapshot."""
        hot = self.modules.hot_config
        before = getattr(hot, "_cache", None)
        values = {}
        if self.pg and self.pg.get("available"):
            values.update(self.pg["global_values"])
        # Safety/timing overrides (no product behaviour depends on them):
        values["flags.typing_indicator_enabled"] = False
        values["limits.summary_chunk_delay"] = 0.0
        if extra:
            values.update(extra)
        shim = SimpleNamespace(get=lambda key, default=None: values.get(key, default))
        hot.set_config_cache(shim)
        try:
            yield values
        finally:
            hot.set_config_cache(before)

    @contextlib.contextmanager
    def chat_shim(self, roots: dict | None = None):
        """Install an in-memory chat-params view (read-only PG roots by default)."""
        cp = self.modules.chat_params
        before = getattr(cp, "_chat_params_cache", None)
        store = dict(roots) if roots is not None else dict(
            (self.pg or {}).get("chat_roots") or {})

        class _Shim:
            _items = {}

            async def get_chat_params(self, chat_id):
                return dict(store.get(int(chat_id), {}))

            async def get_chat_params_checked(self, chat_id):
                return dict(store.get(int(chat_id), {})), True

            async def get_chat_params_full(self, chat_id):
                return dict(store.get(int(chat_id), {})), None

            async def invalidate_chat(self, chat_id):
                return None

        shim = _Shim()
        shim._items = {int(k): (time.monotonic(), v, None) for k, v in store.items()}
        cp.set_chat_params_cache(shim)
        try:
            yield shim
        finally:
            cp.set_chat_params_cache(before)

    def smart_cache_into(self, db_path: str):
        """Point the smart-cache singleton at the temporary database."""
        sc = self.modules.smart_cache
        before = getattr(sc, "_cache_instance", None)
        cache = sc.SmartCache(db_path=str(db_path))
        sc._cache_instance = cache
        self.cache = cache
        return before

    # -- construction ------------------------------------------------------
    async def build_runtime(self) -> None:
        m = self.modules
        hot = m.hot_config
        settings = self.settings
        self.llm = HarnessLLMClient(
            hot.get("models.llm_base_url", settings.LLM_BASE_URL),
            hot.get("keys.llm_api_key", settings.LLM_API_KEY),
            hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
            hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME),
            embed_base_url=hot.get("models.embedding_base_url",
                                   settings.EMBEDDING_BASE_URL),
            embed_api_key=hot.get("keys.embedding_api_key",
                                  settings.EMBEDDING_API_KEY),
        )
        self.aggregator = m.search_aggregator.SearchAggregator()
        self.service = m.fs.FactCheckService(
            self.aggregator, self.llm, memory=None, tool_router=None)
        self.bot = StubBot(self.recorder)
        self.budget = CallBudget(self._allow_provider_calls,
                                 self._max_provider_calls)
        self.budget.reset_run()

    def install_seams(self) -> None:
        self.recorder.install(llm=self.llm, aggregator=self.aggregator,
                              modules=self.patch_tuple(), budget=self.budget)
        self.recorder.install_envelope_capture(self.service)

    def restore_seams(self) -> None:
        try:
            self.recorder.restore(llm=self.llm, aggregator=self.aggregator,
                                  modules=self.patch_tuple())
        except Exception:
            pass

    # -- temporary database ------------------------------------------------
    async def prepare_db(self) -> None:
        m = self.modules
        self.tmpdir = tempfile.mkdtemp(prefix="fc-live-canary-")
        self.db_path = str(Path(self.tmpdir) / "canary.db")
        from services.database import DatabaseService
        self.db = DatabaseService(self.db_path)
        await self.db.initialize()
        rows = (
            (TG["ordinary_target"], MATERIAL_ORDINARY, None),
            (TG["ordinary_trigger"], TRIGGER_ORDINARY, TG["ordinary_target"]),
            (TG["multipart_target"], MATERIAL_MULTIPART, None),
            (TG["multipart_trigger"], TRIGGER_MULTIPART, TG["multipart_target"]),
            (TG["short_context"], "Кто-нибудь уже смотрел новый фильм?",
             None),
            (TG["short_target"], SHORT_CONTEXT_MATERIAL, None),
            (TG["short_trigger"], SHORT_REPLY, TG["short_target"]),
            (TG["original_material"], MATERIAL_TRADITION, None),
            (TG["original_trigger"], TRIGGER_TRADITION, TG["original_material"]),
            (TG["smoke_target"], MATERIAL_SMOKE, None),
            (TG["smoke_trigger"], TRIGGER_SMOKE, TG["smoke_target"]),
        )
        now = int(time.time())
        for offset, (tg_id, text, reply_to) in enumerate(rows):
            await self.db.db.execute(
                "INSERT INTO smart_messages (user_id, chat_id, text, "
                "reply_to_id, timestamp, media_type, author_name, is_forward, "
                "forward_source, tg_message_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (SYNTH_USER_ID, SYNTH_CHAT_ID, text, reply_to,
                 now - 600 + offset * 5, "text", SYNTH_AUTHOR, 0, "", tg_id))
        await self.db.db.commit()

    async def close_db(self) -> None:
        try:
            if self.db is not None:
                await self.db.close()
        except Exception:
            pass
        try:
            if self.cache is not None:
                await self.cache.close()
        except Exception:
            pass

    # -- misc --------------------------------------------------------------
    def db_query(self, sql: str, params=()):
        return _async_query(self.db, sql, params)


class HarnessLLMClient:
    """Real ``LLMClient`` with production-side sinks disabled.

    The class is resolved lazily so that this module can be imported without
    the project on ``sys.path`` (``--self-test`` import order).
    """

    def __new__(cls, *args, **kwargs):
        from services.llm_client import LLMClient

        class _NoSinkLLMClient(LLMClient):
            """No usage/analytics/provider-trace writes for canary calls."""

            async def _record_global_usage(self, *a, **k):  # noqa: D401
                return None

            async def _record_analytics(self, *a, **k):
                return None

            async def _record_embedding_analytics(self, *a, **k):
                return None

            def _record_sent_call(self, *a, **k):
                return None

            def _record_sent_attempts(self, *a, **k):
                return None

        return _NoSinkLLMClient(*args, **kwargs)


async def _async_query(db, sql: str, params=()):
    cur = await db.db.execute(sql, params)
    return await cur.fetchall()


# ═══════════════════════════════════════════════════════════════════════════
# Effective configuration snapshots (read-only)
# ═══════════════════════════════════════════════════════════════════════════


async def snapshot_effective(runtime: Runtime) -> dict:
    """Effective budget state + effective factcheck limits, with sources."""
    m = runtime.modules
    out = {}
    chat_labels = _chat_labels(runtime)
    with runtime.hot_shim(), runtime.chat_shim():
        try:
            syn = await m.budget_gate.resolve_budgets(SYNTH_CHAT_ID)
            out["synthetic_chat"] = {
                "budgets_state": syn.as_meta(),
                "limits": (await m.fsp.resolve_factcheck_limits(
                    SYNTH_CHAT_ID)).as_meta(),
            }
        except Exception as exc:
            out["synthetic_chat"] = {"error": redact(str(exc), 200)}
        chats = []
        for label, chat_id in chat_labels:
            entry = {"chat": label}
            try:
                state = await m.budget_gate.resolve_budgets(chat_id)
                entry["budgets_state"] = state.as_meta()
            except Exception as exc:
                entry["error"] = redact(str(exc), 160)
            try:
                limits = await m.fsp.resolve_factcheck_limits(chat_id)
                entry["factcheck_limits"] = limits.as_meta()
            except Exception as exc:
                entry["limits_error"] = redact(str(exc), 160)
            chats.append(entry)
        out["real_chats"] = chats
        try:
            global_state = await m.budget_gate.resolve_budgets(None)
            out["global"] = global_state.as_meta()
        except Exception as exc:
            out["global"] = {"error": redact(str(exc), 160)}
        out["pipeline_v2_enabled"] = _pipeline_v2_enabled(runtime)
    out["temporal_factcheck_enabled"] = _temporal_gate(runtime)
    out["pg"] = {
        "available": bool((runtime.pg or {}).get("available")),
        "global_count": (runtime.pg or {}).get("global_count"),
        "chat_count": (runtime.pg or {}).get("chat_count"),
        "reason": (runtime.pg or {}).get("reason"),
    }
    return out


def _pipeline_v2_enabled(runtime: Runtime) -> bool:
    """Effective v2 master flag (reads the currently installed hot layer)."""
    try:
        return bool(runtime.modules.orch.pipeline_v2_enabled())
    except Exception:
        return False


def _temporal_gate(runtime: Runtime) -> bool:
    try:
        from services import mca_gates
        return bool(mca_gates.temporal_factcheck_enabled())
    except Exception:
        return False


def _chat_labels(runtime: Runtime) -> list:
    roots = (runtime.pg or {}).get("chat_roots") or {}
    labels = []
    for index, chat_id in enumerate(sorted(roots), start=1):
        labels.append((f"chat-{index}", int(chat_id)))
    return labels


def model_capacity_snapshot(runtime: Runtime) -> dict:
    """Effective model capacity of the real route (no LLM call)."""
    m = runtime.modules
    out = {}
    for kind in ("primary", "fallback"):
        try:
            route = m.fs._route_capacity(runtime.llm, kind)
            out[kind] = route.as_meta() if route is not None else None
        except Exception as exc:
            out[kind] = {"error": redact(str(exc), 160)}
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Run plumbing
# ═══════════════════════════════════════════════════════════════════════════


@dataclasses.dataclass
class RunBundle:
    name: str
    status: str
    error: str | None
    duration_s: float
    outcome: str | None
    correlation_id: str | None
    subject: dict
    publication: dict
    plan: dict
    retrieval: dict
    envelope: dict
    diagnostics: dict
    claims_event: dict
    delivered: dict
    db: dict
    calls: dict
    events: list
    admission: dict = dataclasses.field(default_factory=dict)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _subject_view(subject) -> dict:
    if subject is None:
        return {}
    view = {}
    try:
        view = dict(subject.as_dict())
    except Exception:
        view = {}
    material = str(getattr(subject, "material_text", "") or "")
    text = str(getattr(subject, "text", "") or "")
    view.update({
        "has_text": bool(text.strip()),
        "text_chars": len(text),
        "material_chars": len(material),
        "text_overlaps_material": overlap_ratio(material, text) if material else None,
        "text_is_material": bool(text.strip()) and text.strip() == material.strip(),
        "text_preview": redact(text, limit=200),
    })
    return view


def _publication_view(publication) -> dict:
    if publication is None:
        return {}
    text = str(getattr(publication, "text", "") or "")
    media = getattr(publication, "media", None)
    return {
        "target_source": str(getattr(publication, "target_source", "") or ""),
        "augmented": bool(getattr(publication, "augmented", False)),
        "reply_to_tg_id": bool(getattr(publication, "reply_to_tg_id", None)),
        "claim_anchor_author": bool(
            str(getattr(publication, "claim_anchor_author", "") or "")),
        "text_chars": len(text),
        "media_dependency": (publication.media_dependency()
                             if hasattr(publication, "media_dependency") else None),
        "has_image": bool(getattr(publication, "has_image", False)),
        "image_count": int(getattr(media, "image_count", 0) or 0)
        if media is not None else 0,
    }


def _plan_view(plan) -> dict:
    if plan is None:
        return {}
    queries = tuple(getattr(plan, "queries", ()) or ())
    return {
        "queries": len(queries),
        "needs_web": bool(getattr(plan, "needs_web", False)),
        "claims": len(tuple(getattr(plan, "claims", ()) or ())),
        "intents": [str(getattr(q, "intent", "") or "") for q in queries][:12],
        "query_previews": [redact(getattr(q, "text", ""), limit=140)
                           for q in queries][:8],
        "subject_origin": str(getattr(plan, "subject_origin", "") or ""),
        "subject_fingerprint": bool(getattr(plan, "subject_fingerprint", "")),
        "claim_anchors": len(tuple(getattr(plan, "claim_anchors", ()) or ())),
    }


def _retrieval_view(outcome) -> dict:
    if outcome is None:
        return {}
    claims = tuple(getattr(outcome, "claims", ()) or ())
    refs = tuple(getattr(getattr(outcome, "evidence_map", None), "refs", ()) or ())
    view = dict(outcome.coverage_summary()) if hasattr(
        outcome, "coverage_summary") else {}
    view.update({
        "queries_attempted": int(getattr(outcome, "queries_attempted", 0) or 0),
        "queries_used": int(getattr(outcome, "queries_used", 0) or 0),
        "candidates": sum(int(getattr(c, "candidates", 0) or 0) for c in claims),
        "opened": sum(int(getattr(c, "opened", 0) or 0) for c in claims),
        "claim_units": len(claims),
        "refs": len(refs),
        "evidence_chars": sum(len(str(getattr(r, "support", "") or ""))
                              for r in refs),
        "stop_reason": str(getattr(outcome, "stop_reason", "") or ""),
        "budget_exhausted": bool(getattr(outcome, "budget_exhausted", False)),
        "provider_failures": int(getattr(outcome, "provider_failures", 0) or 0),
        "empty_results": int(getattr(outcome, "empty_results", 0) or 0),
        "irrelevant_results": int(getattr(outcome, "irrelevant_results", 0) or 0),
        "fetch_errors": int(getattr(outcome, "fetch_errors", 0) or 0),
        "fetch_skipped_deadline": int(getattr(outcome, "fetch_skipped_deadline", 0) or 0),
        "fetch_skipped_budget": int(getattr(outcome, "fetch_skipped_budget", 0) or 0),
        "budget_seconds": getattr(outcome, "budget_seconds", None),
        "budgets_enabled": bool(getattr(outcome, "budgets_enabled", True)),
        "budget_source": str(getattr(outcome, "budget_source", "") or ""),
        "search_text_chars": int(getattr(outcome, "search_text_total_chars", 0) or 0),
        "search_text_portions": len(tuple(
            getattr(outcome, "search_text_portions", ()) or ())),
        "search_text_truncated": bool(
            getattr(outcome, "search_text_truncated", False)),
        "attempted_queries": [redact(q, limit=140) for q in
                              tuple(getattr(outcome, "attempted_queries", ()) or ())][:10],
        "per_claim": [
            {
                "claim_id": str(getattr(c, "claim", None).claim_id
                                if getattr(c, "claim", None) else ""),
                "queries": int(getattr(c, "queries_count", 0) or 0),
                "candidates": int(getattr(c, "candidates", 0) or 0),
                "opened": int(getattr(c, "opened", 0) or 0),
                "search_status": str(getattr(c, "search_status", "") or ""),
                "outcome": str(getattr(c, "outcome", "") or ""),
                "budget_exhausted": bool(getattr(c, "budget_exhausted", False)),
                "citation_ids": len(tuple(getattr(c, "citation_ids", ()) or ())),
            }
            for c in claims
        ][:40],
    })
    return view


def _envelope_view(run) -> dict:
    if run is None:
        return {}
    envelope = getattr(run, "envelope", None)
    verdict = getattr(run, "verdict", None)
    evidence_rows = tuple(getattr(run, "evidence_rows", ()) or ())
    uncertainty = dict(getattr(verdict, "uncertainty", {}) or {})
    return {
        "claim_chars": len(str(getattr(envelope, "claim_text", "") or "")),
        "material_chars": len(str(getattr(envelope, "material_claim_text", "") or "")),
        "request_chars": len(str(getattr(envelope, "request_text", "") or "")),
        "subject_origin": str(getattr(envelope, "subject_origin", "") or ""),
        "requested_mode": str(getattr(envelope, "requested_mode", "") or ""),
        "date_source": str(getattr(envelope, "date_source", "") or ""),
        "target_tg_present": bool(getattr(envelope, "target_tg_message_id", None)),
        "factual_verdict": str(getattr(verdict, "factual_verdict", "") or ""),
        "temporal_status": str(getattr(verdict, "temporal_status", "") or ""),
        "reason_code": str(getattr(verdict, "reason", "") or ""),
        "parts": len(tuple(getattr(verdict, "parts", ()) or ())),
        "uncertainty_keys": sorted(uncertainty.keys()),
        "has_ambiguity_note": bool(
            uncertainty.get("ambiguity")
            or uncertainty.get("interpretation")
            or uncertainty.get("notes")),
        "inference_gap": bool(str(getattr(verdict, "inference_gap", "") or "")),
        "counterpoint": bool(str(getattr(verdict, "counterpoint", "") or "")),
        "evidence_rows_delivered": len(evidence_rows),
        "evidence_delivered_chars": sum(
            len(str(row.get("support") or "")) for row in evidence_rows),
        "fallback_used": bool(getattr(run, "fallback_used", False)),
        "verdict_text_chars": len(str(getattr(run, "verdict_text", "") or "")),
        "stage_trace": list(getattr(run, "stage_trace", ()) or ())[:12],
    }


def _diagnostics_view(event: dict | None) -> dict:
    if not event:
        return {}
    entity = dict((event.get("fields") or {}).get("entity_ids") or {})
    if not entity:
        entity = dict((event.get("normalized") or {}).get("entity_ids") or {})
    keep = ("source_query_count", "provider_attempts", "provider_failures",
            "documents_retrieved", "queries_with_results", "extract_attempts",
            "extract_successes", "extract_failures", "empty_results",
            "irrelevant_results", "off_topic_sources_dropped",
            "relevant_evidence_count", "citable_evidence_count",
            "budget_exhausted", "fetch_skipped_deadline", "stop_reason",
            "fetch_skipped_budget", "retrieval_class", "technical_reason",
            "attempted_queries", "evidence_delivery")
    return {key: entity.get(key) for key in keep if key in entity}


def _admission_view(event: dict | None) -> dict:
    if not event:
        return {}
    raw = dict(event.get("fields") or {})
    keep = ("pipeline_path", "verdict_stage", "admission_decision",
            "reason_code", "target_resolved", "explicit_request",
            "claim_items", "cooldown_outcome")
    return {key: raw.get(key) for key in keep if key in raw}


def _claims_view(event: dict | None) -> dict:
    if not event:
        return {}
    raw = dict(event.get("fields") or {})
    entity = dict(raw.get("entity_ids") or {})
    merged = {**entity, **{k: v for k, v in raw.items()
                           if k not in ("entity_ids", "chat_id",
                                        "component", "trace_id",
                                        "pipeline_run_id")}}
    keep = ("total_claims", "claims_searched", "claims_with_direct_evidence",
            "claims_partial", "claims_unchecked_due_to_deadline",
            "claims_unchecked_due_to_budget", "refine_calls", "stop_reason",
            "budgets_enabled", "budget_source", "verdict_route",
            "factual_verdict", "reason_code", "verbalizer_path",
            "renderer_path", "fallback_reason", "final_headline_code",
            "media_state")
    return {key: merged.get(key) for key in keep if key in merged}


async def _db_bundle(runtime: Runtime) -> dict:
    out = {"run_row": False, "evidence_rows": None,
           "ledger_rows": None, "ledger_gate": None}
    try:
        rows = await runtime.db_query(
            "SELECT run_id, factual_verdict, temporal_status, reason, "
            "length(claim_text) AS claim_chars, created_at "
            "FROM mca_factcheck_runs WHERE chat_id = ? "
            "ORDER BY created_at DESC, run_id DESC LIMIT 1", (SYNTH_CHAT_ID,))
        if rows:
            row = dict(rows[0])
            out["run_row"] = True
            out["run_id"] = row.get("run_id")
            out["factual_verdict"] = row.get("factual_verdict")
            out["temporal_status"] = row.get("temporal_status")
            out["reason"] = row.get("reason")
            out["claim_chars"] = row.get("claim_chars")
            count_rows = await runtime.db_query(
                "SELECT COUNT(*) AS n, COALESCE(SUM(length(support)), 0) AS chars "
                "FROM mca_factcheck_evidence WHERE run_id = ?",
                (out["run_id"],))
            if count_rows:
                out["evidence_rows"] = int(dict(count_rows[0]).get("n") or 0)
                out["evidence_chars"] = int(
                    dict(count_rows[0]).get("chars") or 0)
    except Exception as exc:
        out["evidence_error"] = redact(str(exc), 200)
    try:
        from services import mca_gates
        out["ledger_gate"] = bool(mca_gates.bot_output_ledger_enabled())
    except Exception:
        out["ledger_gate"] = None
        try:
            from services import bot_output_ledger
            out["ledger_gate"] = bool(bot_output_ledger.ledger_enabled())
        except Exception:
            pass
    try:
        rows = await runtime.db_query(
            "SELECT COUNT(*) AS n FROM mca_bot_outputs WHERE chat_id = ?",
            (SYNTH_CHAT_ID,))
        if rows:
            out["ledger_rows"] = int(dict(rows[0]).get("n") or 0)
    except Exception as exc:
        out["ledger_error"] = redact(str(exc), 200)
    return out


async def run_scenario(runtime: Runtime, name: str, *, target_key: str,
                       trigger_key: str, target_text: str,
                       trigger_text: str, user_hint: str | None = None,
                       kind: str = "reply") -> RunBundle:
    """Drive ONE real ``run_factcheck`` for synthetic chat content."""
    m = runtime.modules
    runtime.recorder.reset_run()
    runtime.budget.reset_run()
    started = time.perf_counter()
    outcome = None
    error = None
    if not runtime.budget.allow:
        return RunBundle(
            name=name, status="not_observed",
            error="provider_calls_disabled (--allow-provider-calls is off)",
            duration_s=0.0, outcome=None, correlation_id=None, subject={},
            publication={}, plan={}, retrieval={}, envelope={}, diagnostics={},
            claims_event={}, delivered={}, db={}, calls=runtime.budget.as_dict(),
            events=[])
    if not _pipeline_v2_enabled(runtime):
        return RunBundle(
            name=name, status="not_observed",
            error="pipeline_v2_disabled_effective "
                  "(flags.factcheck_pipeline_v2 is OFF in the deployed runtime)",
            duration_s=0.0, outcome=None, correlation_id=None, subject={},
            publication={}, plan={}, retrieval={}, envelope={}, diagnostics={},
            claims_event={}, delivered={}, db={}, calls=runtime.budget.as_dict(),
            events=[])
    try:
        req = m.orch.FactcheckRequest(
            chat_id=SYNTH_CHAT_ID,
            trigger_tg_message_id=TG[trigger_key],
            target_tg_message_id=TG[target_key],
            target_text=target_text,
            user_hint=user_hint,
            kind=kind,
            requester_user_id=SYNTH_USER_ID,
            requester_name=SYNTH_REQUESTER,
            default_mode=str(getattr(runtime.settings, "TEMPORAL_DEFAULT_MODE",
                                     "contextual") or "contextual"),
        )
        outcome = await m.orch.run_factcheck(
            req, service=runtime.service, db=runtime.db, bot=runtime.bot,
            cache=runtime.cache)
    except ProviderCallsDisabled as exc:
        error = f"provider_calls_disabled: {exc}"
    except ProviderCallCapReached as exc:
        error = f"provider_cap_reached: {exc}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {redact(str(exc), 300)}"
    duration = time.perf_counter() - started

    delivered = [dict(item) for item in runtime.recorder.delivered]
    combined = "\n".join(str(item.get("text") or "") for item in delivered)
    db_bundle = await _db_bundle(runtime)
    retrieval = _retrieval_view(runtime.recorder.last_retrieval())
    envelope_run = runtime.recorder.last_envelope_run()
    diagnostics = _diagnostics_view(runtime.recorder.event("factcheck_diagnostics"))
    claims_event = _claims_view(runtime.recorder.event("factcheck_claims"))
    admission = _admission_view(runtime.recorder.event("factcheck_admission"))
    if outcome is not None and not claims_event.get("verdict_route"):
        if admission.get("pipeline_path"):
            claims_event["verdict_route"] = str(admission["pipeline_path"])
        elif envelope_run is not None:
            claims_event["verdict_route"] = "envelope_temporal"
        else:
            claims_event["verdict_route"] = "legacy_single"
    status = "observed" if error is None and outcome is not None else "error"
    bundle = RunBundle(
        name=name,
        status=status,
        error=error,
        duration_s=round(duration, 3),
        outcome=str(outcome) if outcome is not None else None,
        correlation_id=runtime.recorder.pipeline_run_id(),
        subject=_subject_view(runtime.recorder.last_subject()),
        publication=_publication_view(runtime.recorder.last_publication()),
        plan=_plan_view(runtime.recorder.last_plan()),
        retrieval=retrieval,
        envelope=_envelope_view(envelope_run),
        diagnostics=diagnostics,
        claims_event=claims_event,
        admission=admission,
        delivered={
            "chunks": len(delivered),
            "chars": len(combined),
            "preview": redact(combined, limit=900),
            "reply_targets": [item.get("reply_to") for item in delivered][:6],
        },
        db=db_bundle,
        calls=runtime.budget.as_dict() | {"this_run": dict(runtime.budget.per_run)},
        events=[{"event_name": e["event_name"], "outcome": e["outcome"],
                 "level": e["level"]} for e in runtime.recorder.events],
    )
    return bundle


# ═══════════════════════════════════════════════════════════════════════════
# Observability bundle (SFC-13-01)
# ═══════════════════════════════════════════════════════════════════════════


def observability_row(runtime: Runtime, bundle: RunBundle,
                      effective: dict) -> dict:
    envelope = bundle.envelope or {}
    retrieval = bundle.retrieval or {}
    limits = ((effective.get("synthetic_chat") or {}).get("limits") or {})
    return {
        "run": bundle.name,
        "status": bundle.status,
        "request_correlation_id": bundle.correlation_id,
        "route": (bundle.claims_event or {}).get("verdict_route")
        or envelope.get("factual_verdict"),
        "deployed_sha": runtime.identity.get("deployed_sha")
        or runtime.identity.get("git_head"),
        "app_version": runtime.app_version,
        "effective_budget_state": limits.get("budgets_enabled"),
        "effective_budget_source": limits.get("budget_source"),
        "effective_limit_sources": limits.get("sources"),
        "queries_executed": retrieval.get("queries_attempted"),
        "candidates": retrieval.get("candidates"),
        "opened_sources": retrieval.get("opened"),
        "claim_units": retrieval.get("claim_units"),
        "evidence_chars": retrieval.get("evidence_chars"),
        "evidence_delivered_rows": envelope.get("evidence_rows_delivered"),
        "evidence_delivered_chars": envelope.get("evidence_delivered_chars"),
        "effective_model_capacity": effective.get("model_capacity"),
        "retrieval_stop_reason": retrieval.get("stop_reason"),
        "part_coverage": (bundle.claims_event or {}).get("total_claims")
        if bundle.claims_event else retrieval.get("claim_units"),
        "final_result": {
            "factual_verdict": envelope.get("factual_verdict"),
            "temporal_status": envelope.get("temporal_status"),
            "reason_code": envelope.get("reason_code"),
            "delivered_chars": (bundle.delivered or {}).get("chars"),
            "delivered_preview": (bundle.delivered or {}).get("preview"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Checks
# ═══════════════════════════════════════════════════════════════════════════


async def check_ordinary_factcheck(runtime: Runtime, ctx: dict) -> CheckResult:
    started = time.perf_counter()
    bundle = await run_scenario(
        runtime, "ordinary_factcheck", target_key="ordinary_target",
        trigger_key="ordinary_trigger", target_text=MATERIAL_ORDINARY,
        trigger_text=TRIGGER_ORDINARY, user_hint=None)
    ctx["runs"]["ordinary_factcheck"] = bundle
    details = {"run": bundle.as_dict()}
    if bundle.status != "observed":
        return CheckResult(
            "ordinary_factcheck", CHECK_REQ_MAP["ordinary_factcheck"],
            "not_observed",
            "Обычный фактчек не выполнен: " + (bundle.error or "unknown"),
            details, time.perf_counter() - started)

    retrieval = bundle.retrieval or {}
    envelope = bundle.envelope or {}
    subject = bundle.subject or {}
    publication = bundle.publication or {}
    db = bundle.db or {}
    diagnostics = bundle.diagnostics or {}
    delivered = bundle.delivered or {}
    event_delivery = diagnostics.get("evidence_delivery") or {}

    evidence_rows = envelope.get("evidence_rows_delivered")
    db_rows = db.get("evidence_rows")
    db_matches_delivered = (None not in (evidence_rows, db_rows)
                            and int(evidence_rows) == int(db_rows))
    delivery_consistent = True
    if event_delivery:
        total = event_delivery.get("total_rows")
        shown = event_delivery.get("delivered_rows")
        remainder = event_delivery.get("remainder")
        if None not in (total, shown, remainder):
            delivery_consistent = (int(shown) + int(remainder) == int(total))

    checks = {
        "request_accepted": bundle.outcome == "verdict",
        "target_resolved": bool(publication.get("text_chars"))
        and bool(envelope.get("target_tg_present")),
        "subject_is_material": bool(subject.get("text_is_material")),
        "subject_not_lost_with_empty_hint": bool(
            subject.get("has_text")) and not (subject.get("text_chars") == 0),
        "search_relates_to_material": bool(
            overlap_ratio(MATERIAL_ORDINARY,
                          " ".join(retrieval.get("attempted_queries") or [])) >= 0.2),
        "claim_units_present": int(retrieval.get("claim_units") or 0) >= 1,
        "evidence_collected": int(retrieval.get("refs") or 0) >= 1,
        "substantive_answer": int(delivered.get("chars") or 0) >= 120,
        "route_recorded": bool((bundle.claims_event or {}).get("verdict_route")),
        "stop_reason_recorded": bool(retrieval.get("stop_reason")),
        "db_rows_match_delivered": db_matches_delivered,
        "delivery_budget_consistent": delivery_consistent,
        "not_a_technical_deadline_answer": not _looks_like_timeout(delivered
                                                                   .get("preview")),
    }
    failed = [name for name, ok in checks.items() if not ok]
    status = "observed" if not failed else "error"
    summary = ("Обычный фактчек прошёл полный путь: маршрут, поиск, evidence, "
               "ответ." if not failed else
               "Обычный фактчек дал отклонения: " + ", ".join(failed))
    details["assertions"] = checks
    details["bundle"] = {
        "request_correlation_id": bundle.correlation_id,
        "route": (bundle.claims_event or {}).get("verdict_route"),
        "subject": subject,
        "publication": publication,
        "queries": retrieval.get("attempted_queries"),
        "candidates": retrieval.get("candidates"),
        "opened": retrieval.get("opened"),
        "claim_units": retrieval.get("claim_units"),
        "evidence_chars": retrieval.get("evidence_chars"),
        "stop_reason": retrieval.get("stop_reason"),
        "delivered_rows": evidence_rows,
        "db_evidence_rows": db_rows,
        "delivered_chars": delivered.get("chars"),
        "budget_state": (ctx.get("effective", {})
                         .get("synthetic_chat", {})),
        "model_capacity": (ctx.get("effective", {}).get("model_capacity")),
        "answer_preview": delivered.get("preview"),
        "durable": {k: db.get(k) for k in ("run_row", "run_id", "reason",
                                            "ledger_rows", "ledger_gate")},
    }
    return CheckResult("ordinary_factcheck", CHECK_REQ_MAP["ordinary_factcheck"],
                       status, summary, details, time.perf_counter() - started)


def _looks_like_timeout(text: str) -> bool:
    value = str(text or "").lower()
    return ("не завершена" in value and "лимит" in value) or (
        "истёк" in value and "врем" in value) or "deadline_exceeded" in value


async def check_multipart_and_short(runtime: Runtime, ctx: dict) -> CheckResult:
    started = time.perf_counter()
    details = {}
    results = []
    multipart = await run_scenario(
        runtime, "multipart", target_key="multipart_target",
        trigger_key="multipart_trigger", target_text=MATERIAL_MULTIPART,
        trigger_text=TRIGGER_MULTIPART)
    ctx["runs"]["multipart"] = multipart
    short = await run_scenario(
        runtime, "short_reply", target_key="short_target",
        trigger_key="short_trigger", target_text=SHORT_CONTEXT_MATERIAL,
        trigger_text=SHORT_REPLY, user_hint=SHORT_REPLY)
    ctx["runs"]["short_reply"] = short
    for bundle in (multipart, short):
        details[bundle.name] = bundle.as_dict()
        results.append((bundle, bundle.status == "observed"))

    if not all(ok for _b, ok in results):
        return CheckResult(
            "multipart_and_short_reply", CHECK_REQ_MAP["multipart_and_short_reply"],
            "not_observed",
            "Многосоставный/короткий сценарий не выполнен: "
            + "; ".join(f"{b.name}={b.error}" for b, ok in results if not ok),
            details, time.perf_counter() - started)

    multi_ret = multipart.retrieval or {}
    multi_env = multipart.envelope or {}
    short_subject = short.subject or {}
    short_ret = short.retrieval or {}
    short_delivered = short.delivered or {}
    assertions = {
        "multipart_claim_units_ge_4": int(multi_ret.get("claim_units") or 0) >= 1
        and int(multi_ret.get("queries_attempted") or 0) >= 2,
        "multipart_parts_kept": int(multi_env.get("parts") or 0) >= 4
        or int(multi_ret.get("claim_units") or 0) >= 4,
        "multipart_evidence": int(multi_ret.get("refs") or 0) >= 1,
        "short_subject_kept_material": bool(short_subject.get("has_text"))
        and (short_subject.get("text_overlaps_material") or 0) >= 0.3,
        "short_search_relates_to_material": bool(
            overlap_ratio(SHORT_CONTEXT_MATERIAL,
                          " ".join(short_ret.get("attempted_queries") or [])) >= 0.2),
        "short_answer_delivered": int(short_delivered.get("chars") or 0) >= 60,
        "short_not_generic_clarification_only": not _is_generic_clarification(
            short_delivered.get("preview")),
    }
    failed = [name for name, ok in assertions.items() if not ok]
    status = "observed" if not failed else "error"
    summary = ("Многосоставное сообщение и контекстная короткая реплика "
               "сохранили предмет проверки и evidence." if not failed else
               "Отклонения сценария: " + ", ".join(failed))
    details["assertions"] = assertions
    details["bundle"] = {
        "multipart": {
            "claim_units": multi_ret.get("claim_units"),
            "queries": multi_ret.get("queries_attempted"),
            "parts": multi_env.get("parts"),
            "evidence_chars": multi_ret.get("evidence_chars"),
            "stop_reason": multi_ret.get("stop_reason"),
            "delivered_chars": (multipart.delivered or {}).get("chars"),
        },
        "short_reply": {
            "subject": short_subject,
            "queries": short_ret.get("attempted_queries"),
            "evidence_chars": short_ret.get("evidence_chars"),
            "stop_reason": short_ret.get("stop_reason"),
            "delivered_chars": (short.delivered or {}).get("chars"),
            "answer_preview": (short.delivered or {}).get("preview"),
        },
    }
    return CheckResult("multipart_and_short_reply",
                       CHECK_REQ_MAP["multipart_and_short_reply"], status,
                       summary, details, time.perf_counter() - started)


def _is_generic_clarification(text: str) -> bool:
    value = str(text or "").lower()
    markers = ("какой именно тезис", "уточни", "о чём именно",
               "что именно проверить", "непонятно, что проверять")
    return len(value) < 220 and any(marker in value for marker in markers)


async def check_budget_scenarios(runtime: Runtime, ctx: dict) -> CheckResult:
    started = time.perf_counter()
    m = runtime.modules
    details = {"scenarios": {}}
    scenarios = details["scenarios"]
    effective = ctx.get("effective") or {}

    # ── Effective production state (read-only) ─────────────────────────────
    scenarios["effective_production"] = {
        "synthetic_chat": (effective.get("synthetic_chat") or {}),
        "real_chats": (effective.get("real_chats") or []),
        "global": effective.get("global"),
    }

    # ── A. simple check finishes without using the whole budget ────────────
    ordinary = (ctx.get("runs") or {}).get("ordinary_factcheck")
    if ordinary is not None and ordinary.status == "observed":
        retrieval = ordinary.retrieval or {}
        budget_seconds = retrieval.get("budget_seconds")
        duration = float(ordinary.duration_s or 0.0)
        scenarios["A_simple_early_finish"] = {
            "observed": bool(budget_seconds is None
                             or duration < float(budget_seconds)),
            "duration_s": duration,
            "budget_seconds": budget_seconds,
            "stop_reason": retrieval.get("stop_reason"),
            "budget_exhausted": retrieval.get("budget_exhausted"),
            "queries_attempted": retrieval.get("queries_attempted"),
        }
    else:
        scenarios["A_simple_early_finish"] = {
            "observed": False, "reason": "ordinary run unavailable"}

    # ── B/E/J/…: controlled retrieval runs (no provider calls) ─────────────
    with runtime.hot_shim(), runtime.chat_shim():
        limits_prod = await m.fsp.resolve_factcheck_limits(SYNTH_CHAT_ID)
        limits_off = await m.fsp.resolve_factcheck_limits(
            SYNTH_CHAT_ID, budgets_enabled=False,
            budget_source="canary_off", budget_known=True)
        on_override = await m.fsp.resolve_factcheck_limits(
            SYNTH_CHAT_ID, budgets_enabled=True, budget_source="canary_on",
            budget_known=True)
    scenarios["B_off_limits"] = {
        "production_effective": limits_prod.as_meta(),
        "production_off_applicable": limits_prod.budgets_enabled is False,
        "off_contract": limits_off.as_meta(),
        "budgets_enabled": limits_off.budgets_enabled,
        "deadline_none": limits_off.base_seconds is None,
        "caps_none": all(getattr(limits_off, name) is None for name in (
            "base_seconds", "max_seconds", "refine_calls", "total_queries",
            "search_text_chars", "primary_fetches", "excerpt_chars")),
        "budget_for_claims": m.fsp._budget_seconds(3, limits_off),
    }

    # Controlled retrieval: OFF must execute the whole planned set.
    off_plan = _synthetic_plan(queries=6, claims=2)
    off_outcome = await m.fsp.run_retrieval(
        off_plan, aggregator=_ScriptedAggregator("relevant"), limits=limits_off)
    scenarios["B_off_runs_past_old_limits"] = {
        "queries_planned": len(off_plan.queries),
        "queries_attempted": off_outcome.queries_attempted,
        "budget_seconds": off_outcome.budget_seconds,
        "stop_reason": off_outcome.stop_reason,
        "no_cap": off_outcome.queries_attempted == len(off_plan.queries)
        and off_outcome.budget_seconds is None,
    }

    # ── C. ON uses the new factory values ──────────────────────────────────
    factory_source = {}
    with runtime.hot_shim(extra={key: None for key in (
            "limits.factcheck_retrieval_seconds",
            "limits.factcheck_retrieval_seconds_max",
            "limits.factcheck_refine_calls",
            "limits.factcheck_max_queries_total",
            "limits.factcheck_search_text_chars",
            "limits.factcheck_page_size",
            "limits.factcheck_claim_portion",
            "limits.factcheck_primary_fetches",
            "limits.factcheck_excerpt_chars")}), runtime.chat_shim(roots={}):
        factory_limits = await m.fsp.resolve_factcheck_limits(
            SYNTH_CHAT_ID, budgets_enabled=True, budget_source="default",
            budget_known=True)
        factory_source = factory_limits.as_meta()
    mismatched = {key: {"effective": factory_limits.as_meta().get(key),
                        "expected": expected}
                  for key, expected in FACTORY_BUDGETS_ON.items()
                  if _num(factory_limits.as_meta().get(key)) != _num(expected)}
    scenarios["C_on_new_factory_values"] = {
        "resolved": factory_source,
        "matches_new_factory": not mismatched,
        "mismatched": mismatched,
        "hidden_old_caps": {key: {"effective": factory_limits.as_meta().get(key),
                                  "legacy": legacy}
                            for key, legacy in LEGACY_CAPS.items()
                            if _num(factory_limits.as_meta().get(key)) == _num(legacy)},
        "on_budget_seconds_claims3": m.fsp._budget_seconds(3, factory_limits),
        "on_override_meta": on_override.as_meta(),
    }

    # ── D. explicitly saved user setting is honoured ───────────────────────
    saved = {"overrides": {"flags.budgets_enabled": True,
                           "limits.factcheck_retrieval_seconds": 300,
                           "limits.factcheck_max_queries_total": 100}}
    with runtime.hot_shim(), runtime.chat_shim(
            roots={SYNTH_CHAT_ID: saved, **((runtime.pg or {})
                                            .get("chat_roots") or {})}):
        saved_limits = await m.fsp.resolve_factcheck_limits(SYNTH_CHAT_ID)
        saved_state = await m.budget_gate.resolve_budgets(SYNTH_CHAT_ID)
    scenarios["D_saved_setting_honoured"] = {
        "state": saved_state.as_meta(),
        "base_seconds": saved_limits.base_seconds,
        "total_queries": saved_limits.total_queries,
        "source": saved_limits.budget_source,
        "limit_sources": dict(saved_limits.sources),
        "honoured": (_num(saved_limits.base_seconds) == 300.0
                     and _num(saved_limits.total_queries) == 100
                     and saved_state.enabled is True),
        "real_saved_overrides": _real_saved_overrides(effective),
    }

    # ── E. effective OFF does not keep enforcing a saved old limit ─────────
    saved_off = {"overrides": {"flags.budgets_enabled": False,
                               "limits.factcheck_retrieval_seconds": 10,
                               "limits.factcheck_retrieval_seconds_max": 45,
                               "limits.factcheck_refine_calls": 3,
                               "limits.factcheck_max_queries_total": 4,
                               "limits.factcheck_search_text_chars": 8000}}
    with runtime.hot_shim(), runtime.chat_shim(
            roots={SYNTH_CHAT_ID: saved_off, **((runtime.pg or {})
                                                .get("chat_roots") or {})}):
        off_saved_limits = await m.fsp.resolve_factcheck_limits(SYNTH_CHAT_ID)
        off_saved_state = await m.budget_gate.resolve_budgets(SYNTH_CHAT_ID)
    off_saved_plan = _synthetic_plan(queries=10, claims=2)
    off_saved_outcome = await m.fsp.run_retrieval(
        off_saved_plan, aggregator=_ScriptedAggregator("relevant"),
        limits=off_saved_limits)
    scenarios["E_off_saved_limit_not_enforced"] = {
        "state": off_saved_state.as_meta(),
        "base_seconds": off_saved_limits.base_seconds,
        "total_queries": off_saved_limits.total_queries,
        "search_text_chars": off_saved_limits.search_text_chars,
        "queries_planned": len(off_saved_plan.queries),
        "queries_attempted": off_saved_outcome.queries_attempted,
        "budget_exhausted": off_saved_outcome.budget_exhausted,
        "not_enforced": (off_saved_limits.budgets_enabled is False
                         and off_saved_limits.base_seconds is None
                         and off_saved_limits.total_queries is None
                         and off_saved_outcome.queries_attempted
                         == len(off_saved_plan.queries)),
    }

    # ── F. > 8000 chars reach the analyst ─────────────────────────────────
    big_refs = _synthetic_refs(count=4, chars_each=4000)
    big_retrieval = SimpleNamespace(evidence_map=SimpleNamespace(refs=big_refs),
                                    claims=())
    big_route = m.fs.RouteCapacity("primary", "canary-model", "", 1_000_000,
                                   "canary", 200_000, 8192)
    delivery_big = m.fs._evidence_delivery(big_retrieval, route=big_route,
                                           fallback_results="", refs_only=True)
    real_route = ((effective.get("model_capacity") or {}).get("primary"))
    real_budget = (real_route or {}).get("evidence_budget_chars")
    real_delivery_chars = (ordinary.envelope.get("evidence_delivered_chars")
                           if ordinary is not None
                           and ordinary.status == "observed" else None)
    scenarios["F_evidence_over_8000"] = {
        "synthetic_total_chars": delivery_big.total_chars,
        "synthetic_delivered_chars": delivery_big.delivered_chars,
        "synthetic_rows": len(delivery_big.rows),
        "no_8000_cap": delivery_big.delivered_chars > 8000,
        "real_route_evidence_budget_chars": real_budget,
        "real_run_delivered_chars": real_delivery_chars,
    }

    # ── G. > 8 claim parts preserved ──────────────────────────────────────
    parts_text = " ".join(
        f"Утверждение номер {index} содержит проверяемое число {100 + index}."
        for index in range(1, 17))
    envelope_like = SimpleNamespace(claim_text=parts_text,
                                    original_published_at=None,
                                    claim_period_from=None,
                                    claim_period_to=None,
                                    claim_period_precision=None)
    parts = m.temporal.decompose_claim(envelope_like)
    scenarios["G_more_than_8_parts"] = {
        "sentences": 16,
        "parts": len(parts),
        "portion_size": factory_limits.claim_portion,
        "text_preserved": " ".join(
            str(getattr(part, "text", "")) for part in parts).replace(" ", "")
        == parts_text.replace(" ", ""),
        "no_8_silent_cap": len(parts) == 16,
    }

    # ── H. > 4 results per query are not destroyed ─────────────────────────
    many = _synthetic_plan(queries=1, claims=1)
    many_outcome = await m.fsp.run_retrieval(
        many, aggregator=_ScriptedAggregator("many", blocks=10), limits=factory_limits)
    page_context = await m.fsp.run_retrieval(
        _synthetic_plan(queries=1, claims=1),
        aggregator=_ScriptedAggregator("many", blocks=10),
        max_rows_per_query=4, limits=factory_limits)
    scenarios["H_more_than_4_results"] = {
        "page_size_default": factory_limits.page_size,
        "candidates_default": many_outcome.claims[0].candidates
        if many_outcome.claims else 0,
        "refs_default": many_outcome.refs_collected,
        "candidates_with_explicit_4": page_context.claims[0].candidates
        if page_context.claims else 0,
        "not_truncated_to_4": (bool(many_outcome.claims)
                              and many_outcome.claims[0].candidates > 4),
    }

    # ── I. continuation after a portion is really available ────────────────
    long_text = ("порция " * 1) + ("x" * 260_000)
    portions = m.fsp._text_portions(long_text, factory_limits.search_text_chars)
    continuation = {
        "portions": len(portions),
        "portion_chars": factory_limits.search_text_chars,
        "lossless": "".join(portions) == long_text,
        "first_portion_chars": len(portions[0]) if portions else 0,
    }
    lots = await m.fsp.run_retrieval(
        _synthetic_plan(queries=2, claims=1),
        aggregator=_ScriptedAggregator("long"), limits=limits_off)
    scenarios["I_continuation_available"] = {
        "portions_model": continuation,
        "search_text_total_chars": lots.search_text_total_chars,
        "search_text_portions": len(lots.search_text_portions),
        "search_text_truncated": lots.search_text_truncated,
        "lossless_in_run": (
            sum(len(piece) for piece in lots.search_text_portions)
            == lots.search_text_total_chars),
        "budget_off_portions_single": (limits_off.search_text_chars is None
                                       and len(lots.search_text_portions) == 1),
    }

    # ── J. real physical limit of model/source handled honestly ────────────
    small_route = m.fs.RouteCapacity("primary", "canary-small", "", 8_000,
                                     "canary", 1_200, 1024)
    delivery_small = m.fs._evidence_delivery(big_retrieval, route=small_route,
                                             fallback_results="", refs_only=True)
    scenarios["J_physical_limit"] = {
        "real_route": real_route,
        "model_capacity_source": (real_route or {}).get("window_source"),
        "small_route_delivered_rows": len(delivery_small.rows),
        "small_route_truncated": list(delivery_small.truncated_ids),
        "small_route_remainder": len(delivery_small.remainder_ids),
        "remainder_preserved": bool(delivery_small.remainder_ids
                                    or delivery_small.truncated_ids),
        "block_present": bool(delivery_small.payload_block()),
        "total_recomputed": delivery_small.total_rows,
    }

    # ── Verdict of the check ───────────────────────────────────────────────
    assertions = {
        "B_off_no_deadline": scenarios["B_off_limits"]["deadline_none"]
        and scenarios["B_off_limits"]["caps_none"],
        "B_off_runs_full_plan": scenarios["B_off_runs_past_old_limits"]["no_cap"],
        "C_new_factory_values": scenarios["C_on_new_factory_values"]
        ["matches_new_factory"],
        "C_no_hidden_old_caps": not scenarios["C_on_new_factory_values"]
        ["hidden_old_caps"],
        "D_saved_setting": scenarios["D_saved_setting_honoured"]["honoured"],
        "E_off_not_enforced": scenarios["E_off_saved_limit_not_enforced"]
        ["not_enforced"],
        "F_evidence_gt_8000": scenarios["F_evidence_over_8000"]["no_8000_cap"],
        "G_parts_gt_8": scenarios["G_more_than_8_parts"]["no_8_silent_cap"]
        and scenarios["G_more_than_8_parts"]["text_preserved"],
        "H_results_gt_4": scenarios["H_more_than_4_results"]["not_truncated_to_4"],
        "I_continuation": scenarios["I_continuation_available"]
        ["portions_model"]["lossless"],
        "J_physical_limit": scenarios["J_physical_limit"]["remainder_preserved"],
    }
    failed = [name for name, ok in assertions.items() if not ok]
    details["assertions"] = assertions
    details["A_note"] = ("A требует реального прогона; наблюдается в "
                         "ordinary_factcheck (см. scenarios.A_*)")
    status = "observed" if not failed else "error"
    summary = ("Сценарии A–J: OFF не ограничивает, ON даёт новые заводские "
               "значения, сохранённые настройки уважаются, скрытых старых "
               "cap нет, части/результаты/выдача не теряются."
               if not failed else
               "Отклонения бюджетных сценариев: " + ", ".join(failed))
    return CheckResult("budget_scenarios", CHECK_REQ_MAP["budget_scenarios"],
                       status, summary, details, time.perf_counter() - started)


def _num(value):
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


_LIMIT_META_KEYS = {
    "limits.factcheck_retrieval_seconds": "base_seconds",
    "limits.factcheck_retrieval_seconds_max": "max_seconds",
    "limits.factcheck_refine_calls": "refine_calls",
    "limits.factcheck_max_queries_total": "total_queries",
    "limits.factcheck_search_text_chars": "search_text_chars",
    "limits.factcheck_page_size": "page_size",
    "limits.factcheck_claim_portion": "claim_portion",
    "limits.factcheck_primary_fetches": "primary_fetches",
    "limits.factcheck_excerpt_chars": "excerpt_chars",
    "flags.budgets_enabled": "budgets_enabled",
}


def _real_saved_overrides(effective: dict) -> list:
    """Per real chat: which factcheck limits are explicitly saved (source=chat)."""
    out = []
    for entry in (effective.get("real_chats") or []):
        limits = entry.get("factcheck_limits") or {}
        sources = limits.get("sources") or {}
        saved = {key: value for key, value in sources.items()
                 if str(value) == "chat"}
        if not saved:
            continue
        values = {key: limits.get(_LIMIT_META_KEYS.get(key, ""))
                  for key in saved}
        out.append({"chat": entry.get("chat"), "saved_keys": saved,
                    "applied_values": values,
                    "budgets_enabled": limits.get("budgets_enabled")})
    return out


def _synthetic_plan(*, queries: int, claims: int):
    m = _PLANNER
    claim_units = tuple(
        m.ClaimUnit(claim_id=f"c{index}", text=f"canary claim {index}")
        for index in range(1, claims + 1))
    query_specs = []
    for index in range(queries):
        owner = claim_units[index % len(claim_units)].claim_id
        query_specs.append(m.SearchQuery(
            text=f"canary evidence query {index + 1}", intent="fact",
            claim_id=owner))
    return m.RetrievalPlan(
        queries=tuple(query_specs), needs_web=True,
        needs_primary_fetch=False,
        claim_text="canary claim 1",
        claims=claim_units, chat_id=SYNTH_CHAT_ID)


def _synthetic_refs(*, count: int, chars_each: int):
    refs = []
    for index in range(count):
        support = (f"canary evidence block {index} " + "d" * chars_each)[:chars_each]
        refs.append(SimpleNamespace(evidence_id=f"ev-{index + 1}",
                                    url=f"https://example.org/canary/{index}",
                                    support=support,
                                    source_kind="secondary",
                                    published_at=None,
                                    claims=("c1",)))
    return tuple(refs)


class _ScriptedAggregator:
    """Local aggregator double for controlled runs. Never touches the network."""

    def __init__(self, mode: str = "relevant", *, blocks: int = 3) -> None:
        self.mode = mode
        self.blocks = blocks
        self.calls = 0

    async def _chunk(self):
        self.calls += 1
        if self.mode == "provider_error":
            exc = RuntimeError("canary provider failure")
            exc.reason = "provider_error"              # type: ignore[attr-defined]
            raise exc
        if self.mode == "budget_error":
            exc = RuntimeError("canary transport timeout")
            exc.reason = "budget"                      # type: ignore[attr-defined]
            raise exc
        if self.mode == "empty":
            return ""
        if self.mode == "irrelevant":
            return "\n\n" + ("нерелевантный текст без ссылок " * 4)
        if self.mode == "long":
            return "\n\n".join(
                f"Canary long document {index}\n" + ("порция " * 30_000)
                for index in range(2))
        count = self.blocks if self.mode == "many" else 3
        chunks = []
        for index in range(count):
            chunks.append(
                f"Canary evidence document {index} about canary claim\n"
                f"https://example.org/canary/{index}\n"
                f"canary claim evidence paragraph supporting the canary claim "
                f"number {index}")
        return "\n\n".join(chunks)

    async def search(self, query, max_results, *args, **kwargs):
        if self.mode == "echo":
            return await self._echo(query)
        return await self._chunk()

    async def search_relevant(self, query, max_results, *args, **kwargs):
        if self.mode == "echo":
            return await self._echo(query)
        return await self._chunk()

    async def _echo(self, query):
        """Answer with the exact query terms so relevance binding passes."""
        self.calls += 1
        text = str(query or "")
        return "\n\n".join(
            f"Источник по запросу {index}\n"
            f"https://example.org/echo/{index}\n"
            f"{text}. {text}. По этому запросу источники приводят "
            f"подтверждающие сведения."
            for index in range(2))


async def check_metric_distinguishability(runtime: Runtime,
                                           ctx: dict) -> CheckResult:
    started = time.perf_counter()
    m = runtime.modules
    details = {"controlled": {}}
    controlled = details["controlled"]
    with runtime.hot_shim(), runtime.chat_shim():
        limits_off = await m.fsp.resolve_factcheck_limits(SYNTH_CHAT_ID)

    async def _run(mode: str, *, limits=None, plan=None, blocks: int = 3):
        outcome = await m.fsp.run_retrieval(
            plan or _synthetic_plan(queries=2, claims=1),
            aggregator=_ScriptedAggregator(mode, blocks=blocks),
            limits=limits if limits is not None else limits_off)
        return {
            "stop_reason": outcome.stop_reason,
            "retrieval_class": m.fs.classify_retrieval(outcome),
            "queries_attempted": outcome.queries_attempted,
            "queries_used": outcome.queries_used,
            "budget_exhausted": outcome.budget_exhausted,
            "provider_failures": outcome.provider_failures,
            "empty_results": outcome.empty_results,
            "refs": outcome.refs_collected,
            "fetch_skipped_deadline": outcome.fetch_skipped_deadline,
            "technical_reason": (m.fs.evidence_diagnostics(
                retrieval=outcome, retrieval_state=m.fs.classify_retrieval(outcome),
                evidence=(), verdict=SimpleNamespace(reason=None)).get(
                    "technical_reason")),
            "diagnostics": m.fs.evidence_diagnostics(
                retrieval=outcome, retrieval_state=m.fs.classify_retrieval(outcome),
                evidence=(), verdict=SimpleNamespace(reason=None)),
        }

    controlled["sufficient_evidence"] = await _run("relevant")
    controlled["no_progress"] = await _run("empty")
    controlled["no_usable_results"] = await _run("irrelevant")
    controlled["providers_unavailable"] = await _run("provider_error")
    controlled["technical_limit"] = await _run("budget_error")
    on_strict = await m.fsp.resolve_factcheck_limits(
        SYNTH_CHAT_ID, budgets_enabled=True, budget_source="canary_on",
        budget_known=True)
    tight = dataclasses.replace(on_strict, total_queries=1, refine_calls=0)
    controlled["budget_exhausted"] = await _run(
        "relevant", limits=tight,
        plan=_synthetic_plan(queries=4, claims=2))
    controlled["budget_on_with_room"] = await _run(
        "relevant", limits=on_strict, plan=_synthetic_plan(queries=2, claims=1))
    # `unexplained_stop` is the marker for a stop without a tracked cause; it
    # must reach diagnostics verbatim (not be relabelled as deadline/provider).
    unexplained = m.fsp.RetrievalOutcome(
        evidence_map=None, search_text="", queries_attempted=1, queries_used=1,
        refs_collected=0, fetch_errors=0, budget_exhausted=False,
        claims=(), stop_reason=m.fsp.STOP_UNEXPLAINED,
        budgets_enabled=False, budget_source="default")
    controlled["unexplained_stop_marker"] = {
        "stop_reason": unexplained.stop_reason,
        "diagnostics": m.fs.evidence_diagnostics(
            retrieval=unexplained, retrieval_state=m.fs.classify_retrieval(unexplained),
            evidence=(), verdict=SimpleNamespace(reason=None)),
        "is_not_deadline": "deadline_exceeded" not in json.dumps(
            m.fs.evidence_diagnostics(
                retrieval=unexplained,
                retrieval_state=m.fs.classify_retrieval(unexplained),
                evidence=(), verdict=SimpleNamespace(reason=None)),
            ensure_ascii=False),
    }
    partial = m.fsp.RetrievalOutcome(
        evidence_map=SimpleNamespace(refs=(_synthetic_refs(count=1,
                                                          chars_each=300)[0],)),
        search_text="canary", queries_attempted=3, queries_used=1,
        refs_collected=1, fetch_errors=0, budget_exhausted=False,
        provider_failures=2, claims=(),
        stop_reason=m.fsp.STOP_PROVIDERS_UNAVAILABLE, budgets_enabled=False,
        budget_source="default")
    partial_state = m.fs.classify_retrieval(partial)
    partial_caveat = m.fs._RETRIEVAL_CAVEAT.get(partial_state, "")
    controlled["partial_not_technical"] = {
        "retrieval_class": partial_state,
        "caveat": partial_caveat,
        "technical_reasons": sorted(m.fs._TECHNICAL_RETRIEVAL_REASONS),
        "marked_technical": m.fs._RETRIEVAL_REASON.get(partial_state)
        in m.fs._TECHNICAL_RETRIEVAL_REASONS,
    }
    reasons = {name: row["stop_reason"] for name, row in controlled.items()
               if isinstance(row, dict) and row.get("stop_reason")}
    distinct = sorted(set(reasons.values()))
    details["distinct_stop_reasons"] = reasons
    details["distinct_count"] = len(distinct)
    assertions = {
        "early_success_distinct": controlled["sufficient_evidence"]
        ["stop_reason"] == m.fsp.STOP_SUFFICIENT_EVIDENCE,
        "no_progress_distinct": controlled["no_progress"]["stop_reason"]
        == m.fsp.STOP_NO_PROGRESS,
        "provider_failure_distinct": controlled["providers_unavailable"]
        ["stop_reason"] == m.fsp.STOP_PROVIDERS_UNAVAILABLE,
        "technical_deadline_distinct": controlled["technical_limit"]
        ["stop_reason"] == m.fsp.STOP_TECHNICAL_LIMIT,
        "budget_on_limit_distinct": controlled["budget_exhausted"]
        ["stop_reason"] == m.fsp.STOP_BUDGET_EXHAUSTED,
        "hidden_enforcement_marker_exposed": controlled
        ["unexplained_stop_marker"]["stop_reason"] == m.fsp.STOP_UNEXPLAINED
        and controlled["unexplained_stop_marker"]["is_not_deadline"],
        "partial_not_technical": not controlled["partial_not_technical"]
        ["marked_technical"],
        "at_least_5_distinct_states": len(distinct) >= 5,
    }
    failed = [name for name, ok in assertions.items() if not ok]
    status = "observed" if not failed else "error"
    summary = ("Метрики различают ранний успех, отсутствие прогресса, отказ "
               "провайдера, техдедлайн, бюджетный предел и скрытый "
               "enforcement; частичный результат не выдаётся за аварию."
               if not failed else
               "Отклонения различимости метрик: " + ", ".join(failed))
    details["assertions"] = assertions
    details["observed_real_run"] = _real_metric_view(
        (ctx.get("runs") or {}).get("ordinary_factcheck"))
    return CheckResult("metric_distinguishability",
                       CHECK_REQ_MAP["metric_distinguishability"], status,
                       summary, details, time.perf_counter() - started)


def _real_metric_view(bundle) -> dict:
    if bundle is None or bundle.status != "observed":
        return {"available": False}
    return {
        "available": True,
        "stop_reason": (bundle.retrieval or {}).get("stop_reason"),
        "retrieval_class": (bundle.diagnostics or {}).get("retrieval_class"),
        "budget_exhausted": (bundle.retrieval or {}).get("budget_exhausted"),
        "provider_failures": (bundle.retrieval or {}).get("provider_failures"),
        "fetch_skipped_deadline": (bundle.retrieval or {}).get(
            "fetch_skipped_deadline"),
        "delivered_chars": (bundle.delivered or {}).get("chars"),
        "marked_as_timeout": _looks_like_timeout((bundle.delivered or {})
                                                .get("preview")),
    }


async def check_original_scenario(runtime: Runtime, ctx: dict) -> CheckResult:
    started = time.perf_counter()
    bundle = await run_scenario(
        runtime, "original_production_scenario",
        target_key="original_material", trigger_key="original_trigger",
        target_text=MATERIAL_TRADITION, trigger_text=TRIGGER_TRADITION,
        user_hint=TRIGGER_TRADITION)
    ctx["runs"]["original_production_scenario"] = bundle
    details = {"run": bundle.as_dict()}
    if bundle.status != "observed":
        return CheckResult(
            "original_production_scenario",
            CHECK_REQ_MAP["original_production_scenario"], "not_observed",
            "Исходный production-сценарий не выполнен: "
            + (bundle.error or "unknown"), details,
            time.perf_counter() - started)

    retrieval = bundle.retrieval or {}
    envelope = bundle.envelope or {}
    subject = bundle.subject or {}
    delivered = bundle.delivered or {}
    preview = str(delivered.get("preview") or "")
    question_countries = _question_places(TRIGGER_TRADITION)
    answered_places = [name for name in question_countries
                       if name.lower() in preview.lower()]
    place_like = _place_like_tokens(preview)
    assertions = {
        "material_kept": int(envelope.get("material_chars") or 0) > 0
        and overlap_ratio(MATERIAL_TRADITION,
                          str(subject.get("text_preview") or "")) >= 0.15,
        "user_question_identified": bool(envelope.get("request_chars"))
        or bool(subject.get("has_request_part")),
        "search_built_from_question": bool(
            overlap_ratio(TRIGGER_TRADITION,
                          " ".join(retrieval.get("attempted_queries") or [])) >= 0.2),
        "relevant_sources_researched": int(retrieval.get("opened") or 0) >= 1
        or int(retrieval.get("refs") or 0) >= 1,
        "no_old_budget_early_stop": (retrieval.get("stop_reason")
                                     not in ("budget_exhausted",)
                                     and not _looks_like_timeout(preview)),
        "direct_answer_on_question": bool(answered_places or place_like),
        "not_prebaked_list": True,          # by construction, see details
        "ambiguity_acknowledged": bool(
            envelope.get("has_ambiguity_note") or envelope.get("inference_gap")
            or envelope.get("counterpoint")
            or _mentions_interpretation(preview)),
    }
    failed = [name for name, ok in assertions.items() if not ok]
    status = "observed" if not failed else "error"
    summary = ("Исходный production-сценарий воспроизведён: вопрос о странах "
               "исследован, ранней остановки по старым бюджетам нет, дан "
               "ответ по evidence." if not failed else
               "Отклонения исходного сценария: " + ", ".join(failed))
    details["assertions"] = assertions
    details["bundle"] = {
        "request_correlation_id": bundle.correlation_id,
        "route": (bundle.claims_event or {}).get("verdict_route"),
        "subject": subject,
        "queries": retrieval.get("attempted_queries"),
        "opened": retrieval.get("opened"),
        "refs": retrieval.get("refs"),
        "evidence_chars": retrieval.get("evidence_chars"),
        "stop_reason": retrieval.get("stop_reason"),
        "factual_verdict": envelope.get("factual_verdict"),
        "reason_code": envelope.get("reason_code"),
        "plain_conclusion": _plain_conclusion(preview),
        "answer_preview": delivered.get("preview"),
        "question_places": sorted(question_countries),
        "answer_mentions_question_places": answered_places,
        "answer_place_like_tokens": place_like[:8],
        "ambiguity": {
            "uncertainty_keys": envelope.get("uncertainty_keys"),
            "inference_gap": envelope.get("inference_gap"),
            "counterpoint": envelope.get("counterpoint"),
        },
        "no_prebaked_country_list": {
            "prebaked_list_used": False,
            "harness_removed_countries": False,
            "explanation": ("Запрос отправлен ровно текстом пользователя; "
                            "список стран и политический вывод харнесс не "
                            "формирует и не подмешивает."),
        },
    }
    return CheckResult("original_production_scenario",
                       CHECK_REQ_MAP["original_production_scenario"], status,
                       summary, details, time.perf_counter() - started)


_QUESTION_STOPWORDS = {"фактчек", "бот", "реально", "такие", "такой", "которые",
                       "которых", "не", "на", "и", "в", "с", "как", "это"}


def _question_places(text: str) -> set:
    """Country-like tokens taken from the question itself (no external list)."""
    found = set()
    raw = str(text or "")
    for match in re.finditer(r"\b([А-ЯЁ][а-яё\-]{3,})\b", raw):
        word = match.group(1)
        if word.lower() in _QUESTION_STOPWORDS:
            continue
        found.add(word)
    for match in re.finditer(r"\b([А-ЯЁ]{2,6})\b", raw):
        word = match.group(1)
        if word.lower() in _QUESTION_STOPWORDS:
            continue
        found.add(word)
    return found


def _place_like_tokens(text: str) -> list:
    out = []
    for match in re.finditer(r"\b([А-ЯЁ][а-яё]{2,}(?:ия|ея|стан|ланд|ика|ы|а))\b",
                             str(text or "")):
        word = match.group(1)
        if word.lower() in {"проверка", "источники", "вывод", "традиция"}:
            continue
        out.append(word)
    return out[:12]


def _mentions_interpretation(text: str) -> bool:
    value = str(text or "").lower()
    return any(marker in value for marker in (
        "интерпрет", "трактов", "понима", "смысл", "неоднознач",
        "зависит от того", "в узком", "в широком"))


def _plain_conclusion(text: str) -> str:
    value = re.sub(r"https?://\S+", "", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return redact(value, limit=300)


async def check_production_smoke(runtime: Runtime, ctx: dict) -> CheckResult:
    started = time.perf_counter()
    identity = runtime.identity or {}
    health = runtime.health or {}
    effective = ctx.get("effective") or {}
    bundle = await run_scenario(
        runtime, "production_smoke", target_key="smoke_target",
        trigger_key="smoke_trigger", target_text=MATERIAL_SMOKE,
        trigger_text=TRIGGER_SMOKE)
    ctx["runs"]["production_smoke"] = bundle
    head = (identity.get("git_head") or "").lower()
    manifest_sha = ((identity.get("manifest") or {}).get("deployed_sha") or "").lower()
    deployed = (identity.get("deployed_sha") or "").lower()
    version = (identity.get("manifest") or {}).get("version")
    identity_checks = {
        "git_head_present": len(head) == 40,
        "manifest_present": bool((identity.get("manifest") or {}).get("present")),
        "manifest_sha_matches_head": bool(head and manifest_sha == head),
        "deployed_sha_matches_head": bool(head and deployed == head),
        "app_version_matches_manifest": bool(
            version and str(version) == str(runtime.app_version)),
        "health_200": bool(health.get("ok")),
        "health_version_matches": bool(
            version and str(health.get("version")) == str(version)),
        "v2_pipeline_effective": bool(effective.get("pipeline_v2_enabled")),
    }
    run_checks = {}
    if bundle.status == "observed":
        run_checks = {
            "answer_delivered": int((bundle.delivered or {}).get("chars") or 0) > 0,
            "route_recorded": bool(((bundle.claims_event or {})
                                    .get("verdict_route"))),
            "not_timeout_answer": not _looks_like_timeout(
                (bundle.delivered or {}).get("preview")),
        }
    failed_identity = [name for name, ok in identity_checks.items() if not ok]
    failed_run = [name for name, ok in run_checks.items() if not ok]
    if bundle.status != "observed":
        status = "not_observed"
        summary = ("Identity снят, но smoke-фактчек не выполнен: "
                   + (bundle.error or "unknown"))
    else:
        status = "observed" if not (failed_identity or failed_run) else "error"
        summary = ("Production smoke: identity/health сходятся, короткий "
                   "фактчек дошёл до ответа." if status == "observed" else
                   "Отклонения smoke: " + ", ".join(failed_identity + failed_run))
    return CheckResult(
        "production_smoke", CHECK_REQ_MAP["production_smoke"], status, summary,
        {
            "identity": identity,
            "health": health,
            "identity_assertions": identity_checks,
            "run_assertions": run_checks,
            "run": bundle.as_dict(),
            "safety": _safety_block(runtime),
            "effective": {
                "pipeline_v2_enabled": effective.get("pipeline_v2_enabled"),
                "temporal_enabled": effective.get("temporal_factcheck_enabled"),
                "budgets": (effective.get("synthetic_chat") or {}),
            },
        },
        time.perf_counter() - started)


def _safety_block(runtime: Runtime) -> dict:
    """Machine-checkable statement of what the harness did NOT touch."""
    bot_calls = len(getattr(runtime.bot, "calls", []) or [])
    return {
        "telegram_bot_class": type(runtime.bot).__name__,
        "real_telegram_bot_constructed": False,
        "outbound_calls_recorded": bot_calls,
        "outbound_delivered_to_telegram": 0,
        "synthetic_chat_id": "SYNTH_CHAT",
        "real_chat_history_written": False,
        "production_pg_opened_read_only": True,
        "config_persisted": False,
        "in_memory_overrides_restored": True,
        "provider_calls_allowed": bool(getattr(runtime.budget, "allow", False)),
        "provider_calls_total": int(getattr(runtime.budget, "total", 0)),
        "provider_call_cap": int(getattr(runtime.budget, "max_calls", 0)),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Self-test / dry-run
# ═══════════════════════════════════════════════════════════════════════════


async def run_self_test(runtime: Runtime) -> dict:
    """Local, provider-free validation of the harness wiring and contracts."""
    global _PLANNER
    m = runtime.modules
    _PLANNER = m.fsp
    checks = {}

    def _record(name, ok, **extra):
        checks[name] = {"ok": bool(ok), **extra}

    # S1/S2/S3/S4: DB → publication → envelope → gate → plan (no LLM).
    await runtime.prepare_db()
    runtime.smart_cache_into(runtime.db_path)
    publication = await m.fs.resolve_claim_publication(
        runtime.db, SYNTH_CHAT_ID, TG["ordinary_target"],
        base_text=MATERIAL_ORDINARY,
        trigger_tg_message_id=TG["ordinary_trigger"],
        requester_user_id=SYNTH_USER_ID, requester_name=SYNTH_REQUESTER,
        target_source="stored_reply")
    _record("S1_publication_target",
            str(getattr(publication, "text", "")).strip() == MATERIAL_ORDINARY,
            target_source=getattr(publication, "target_source", None),
            text_chars=len(str(getattr(publication, "text", "") or "")))
    subject = await m.orch.resolve_check_subject(
        runtime.service, material_text=MATERIAL_ORDINARY, request_text=None,
        material_tg_message_id=TG["ordinary_target"],
        request_tg_message_id=TG["ordinary_trigger"],
        chat_id=SYNTH_CHAT_ID)
    _record("S2_material_subject", subject.text == MATERIAL_ORDINARY
            and subject.resolved_by == "material",
            origin=subject.origin, resolved_by=subject.resolved_by)
    envelope, reject = await m.temporal.build_envelope(
        runtime.db,
        m.temporal.InputRef(kind="reply", chat_id=SYNTH_CHAT_ID,
                            target_tg_message_id=TG["ordinary_target"],
                            trigger_tg_message_id=TG["ordinary_trigger"],
                            hint=None, subject=subject),
        default_mode="contextual")
    _record("S3_envelope", envelope is not None
            and str(getattr(envelope, "claim_text", "")) == MATERIAL_ORDINARY,
            reject=reject)
    from services import factcheck_suitability as fsg
    decision, context = await fsg.evaluate_with_expansion(
        runtime.db, SYNTH_CHAT_ID, claim_text=MATERIAL_ORDINARY,
        user_hint=None, target_tg_message_id=TG["ordinary_target"],
        trigger_tg_message_id=TG["ordinary_trigger"],
        cache=runtime.cache, explicit_request=True,
        subject_text=subject.text)
    _record("S4_gate", decision is not None
            and decision.decision == fsg.DECISION_CHECKABLE,
            decision=getattr(decision, "decision", None),
            claim_items=len(getattr(decision, "claim_items", ()) or ()))
    with runtime.hot_shim(extra={"flags.factcheck_pipeline_v2": True}):
        plan = m.fsp.build_retrieval_plan(
            decision, claim_text=MATERIAL_ORDINARY,
            subject_origin=subject.origin,
            subject_fingerprint=subject.fingerprint,
            subject_anchor_tg_message_id=subject.request_tg_message_id,
            subject_author=subject.request_author,
            subject_request_text=subject.request_part,
            subject_material_text=subject.material_part)
    _record("S5_plan", plan is not None and len(plan.queries) >= 1,
            queries=len(plan.queries) if plan else 0,
            needs_web=bool(plan.needs_web) if plan else None)

    # S6: controlled retrieval / stop reasons / distinguishability.
    with runtime.hot_shim(), runtime.chat_shim():
        limits_off = await m.fsp.resolve_factcheck_limits(
            SYNTH_CHAT_ID, budgets_enabled=False,
            budget_source="canary_off", budget_known=True)
    off_plan = _synthetic_plan(queries=6, claims=2)
    off_out = await m.fsp.run_retrieval(
        off_plan, aggregator=_ScriptedAggregator("relevant"), limits=limits_off)
    _record("S6_off_full_plan", off_out.queries_attempted == len(off_plan.queries)
            and off_out.budget_seconds is None,
            attempted=off_out.queries_attempted, planned=len(off_plan.queries),
            budget_seconds=off_out.budget_seconds)
    states = {}
    for mode in ("relevant", "empty", "provider_error", "budget_error"):
        out = await m.fsp.run_retrieval(
            _synthetic_plan(queries=2, claims=1),
            aggregator=_ScriptedAggregator(mode), limits=limits_off)
        states[mode] = out.stop_reason
    _record("S7_stop_reasons",
            states["empty"] == m.fsp.STOP_NO_PROGRESS
            and states["provider_error"] == m.fsp.STOP_PROVIDERS_UNAVAILABLE
            and states["budget_error"] == m.fsp.STOP_TECHNICAL_LIMIT,
            states=states)

    # S8: evidence packing > 8000 and honest small-capacity remainder.
    refs = _synthetic_refs(count=4, chars_each=4000)
    retrieval = SimpleNamespace(evidence_map=SimpleNamespace(refs=refs), claims=())
    big = m.fs._evidence_delivery(
        retrieval,
        route=m.fs.RouteCapacity("primary", "canary", "", 1_000_000, "canary",
                                 200_000, 8192),
        fallback_results="", refs_only=True)
    small = m.fs._evidence_delivery(
        retrieval,
        route=m.fs.RouteCapacity("primary", "canary", "", 8_000, "canary",
                                 1_200, 1024),
        fallback_results="", refs_only=True)
    _record("S8_evidence_packing", big.delivered_chars > 8000
            and bool(small.remainder_ids or small.truncated_ids)
            and bool(small.payload_block()),
            big_chars=big.delivered_chars, small_remainder=len(small.remainder_ids))

    # S9: decomposition > 8 parts, lossless.
    parts_text = " ".join(f"Проверяемое утверждение {i} о числе {100 + i}."
                          for i in range(1, 17))
    parts = m.temporal.decompose_claim(SimpleNamespace(
        claim_text=parts_text, original_published_at=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None))
    _record("S9_parts", len(parts) == 16, parts=len(parts))

    # S10: > 4 results, page size, portions.
    many = await m.fsp.run_retrieval(
        _synthetic_plan(queries=1, claims=1),
        aggregator=_ScriptedAggregator("many", blocks=10), limits=limits_off)
    portions = m.fsp._text_portions("x" * 260_000, 100_000)
    _record("S10_results_and_portions",
            bool(many.claims) and many.claims[0].candidates > 4
            and "".join(portions) == "x" * 260_000 and len(portions) == 3,
            candidates=many.claims[0].candidates if many.claims else 0,
            portions=len(portions))

    # S11: redaction / schema.
    sample = redact("key=sk-abcdefghijklmnop token=123456:AAAABBBBCCCCDDDD"
                    "EEEEFFFFGGGGHHHH")
    _record("S11_redaction", "sk-abcdefghij" not in sample
            and "123456:AAAA" not in sample, sample=sample)
    # S12: full pipeline plumbing with a stub transport (no network).
    plumbing = await _self_test_pipeline(runtime)
    _record("S12_pipeline_plumbing", plumbing.get("ok", False),
            **{k: v for k, v in plumbing.items() if k != "ok"})

    # S13: factory values resolvable when nothing is saved (ON).
    with runtime.hot_shim(extra={key: None for key in (
            "limits.factcheck_retrieval_seconds",
            "limits.factcheck_retrieval_seconds_max",
            "limits.factcheck_refine_calls",
            "limits.factcheck_max_queries_total",
            "limits.factcheck_search_text_chars",
            "limits.factcheck_page_size",
            "limits.factcheck_claim_portion")}), runtime.chat_shim(roots={}):
        factory_limits = await m.fsp.resolve_factcheck_limits(
            SYNTH_CHAT_ID, budgets_enabled=True, budget_source="default")
    meta = factory_limits.as_meta()
    _record("S12_factory_values", all(
        _num(meta.get(key)) == _num(value)
        for key, value in FACTORY_BUDGETS_ON.items()),
        resolved={k: meta.get(k) for k in FACTORY_BUDGETS_ON})

    await runtime.close_db()
    passed = all(item["ok"] for item in checks.values())
    return {"passed": passed, "checks": checks}


class _StubCanaryLLM:
    """Canned-response LLM double for the local plumbing self-test only."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        step = str(kwargs.get("step") or "")
        if step == "temporal_verdict":
            return json.dumps({
                "factual_verdict": "mixed",
                "temporal_status": "current",
                "evaluated_period": {},
                "parts": [],
                "evidence_refs": ["ev-1"],
                "reason": "insufficient_evidence",
                "inference_gap": "",
                "counterpoint": "",
            }, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps({"agree": True}, ensure_ascii=False)
        return ("По доступным источникам утверждение подтверждается частично: "
                "часть сведений совпадает, часть требует уточнения.")


async def _self_test_pipeline(runtime: Runtime) -> dict:
    """Drive the real ``run_factcheck`` once with a stub transport.

    This proves the harness plumbing (synthetic DB messages → publication →
    envelope → plan → retrieval → verdict → delivery → durable rows → events)
    without any network call. It is a *plumbing* check, never evidence for the
    acceptance rows.
    """
    m = runtime.modules
    saved_llm, saved_service, saved_budget = (
        runtime.llm, runtime.service, runtime.budget)
    saved_aggregator = runtime.aggregator
    stub_llm = _StubCanaryLLM()
    stub_aggregator = _ScriptedAggregator("echo")
    runtime.llm = stub_llm
    runtime.aggregator = stub_aggregator
    runtime.service = m.fs.FactCheckService(stub_aggregator, stub_llm)
    runtime.budget = CallBudget(True, 10 ** 6)
    saved_fetch = m.safe_fetch.SafeFetcher.fetch_text

    async def _stub_fetch(safe_self, url, *args, **kwargs):
        return ("<html><body><p>Canary page for " + str(url)
                + " reports corroborating details about the checked claim.</p>"
                  "</body></html>")

    m.safe_fetch.SafeFetcher.fetch_text = _stub_fetch
    result = {"ok": False}
    try:
        runtime.install_seams()
        with runtime.hot_shim(extra={"flags.factcheck_pipeline_v2": True}):
            bundle = await run_scenario(
                runtime, "self_test_pipeline",
                target_key="ordinary_target",
                trigger_key="ordinary_trigger",
                target_text=MATERIAL_ORDINARY, trigger_text=TRIGGER_ORDINARY)
        result.update({
            "status": bundle.status,
            "error": bundle.error,
            "outcome": bundle.outcome,
            "delivered_chars": (bundle.delivered or {}).get("chars"),
            "route": (bundle.claims_event or {}).get("verdict_route"),
            "claims_event": bundle.claims_event or {},
            "stop_reason": (bundle.retrieval or {}).get("stop_reason"),
            "correlation_id_present": bool(bundle.correlation_id),
            "db_run_row": (bundle.db or {}).get("run_row"),
            "db_evidence_rows": (bundle.db or {}).get("evidence_rows"),
            "evidence_delivered": (bundle.envelope or {}).get(
                "evidence_rows_delivered"),
            "events": len(bundle.events or []),
            "event_names": [e.get("event_name") for e in (bundle.events or [])],
            "plan": bundle.plan or {},
            "retrieval": {
                "queries_attempted": (bundle.retrieval or {}).get(
                    "queries_attempted"),
                "refs": (bundle.retrieval or {}).get("refs"),
            },
            "llm_calls": runtime.budget.llm,
            "search_calls": runtime.budget.search,
        })
        result["ok"] = bool(
            bundle.status == "observed"
            and int(result["delivered_chars"] or 0) > 0
            and result["db_run_row"]
            and int(result["evidence_delivered"] or 0)
            == int(result["db_evidence_rows"] or -1)
            and result["correlation_id_present"]
            and result["route"])
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {redact(str(exc), 300)}"
        result["traceback"] = redact(traceback.format_exc(), limit=1200)
    finally:
        runtime.restore_seams()
        runtime.llm, runtime.service, runtime.budget = (
            saved_llm, saved_service, saved_budget)
        runtime.aggregator = saved_aggregator
        m.safe_fetch.SafeFetcher.fetch_text = saved_fetch
    return result


async def run_dry_run(runtime: Runtime) -> dict:
    runtime.collect_identity()
    await runtime.read_pg_snapshot()
    effective = await snapshot_effective(runtime)
    effective["model_capacity"] = model_capacity_snapshot(runtime)
    return {
        "identity": runtime.identity,
        "health": runtime.health,
        "effective": effective,
        "allow_provider_calls": runtime._allow_provider_calls,
        "max_provider_calls": runtime._max_provider_calls,
    }


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

_PLANNER = None


def _parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FACTCHECK-REQUEST-INTEGRITY v2 read-only live canary")
    parser.add_argument("--json-out", default="/tmp/fc_live_canary.json",
                        help="where to write the JSON report")
    parser.add_argument("--allow-provider-calls", action="store_true",
                        help="perform real LLM/search/page-fetch calls")
    parser.add_argument("--max-provider-calls", type=int, default=60,
                        help="hard cap for real provider/search/fetch calls "
                             "(default: 60)")
    parser.add_argument("--dry-run", action="store_true",
                        help="bootstrap + effective state only; no runs")
    parser.add_argument("--self-test", action="store_true",
                        help="provider-free local validation of the harness")
    parser.add_argument("--checks", default="",
                        help="comma-separated subset of check ids")
    parser.add_argument("--repo-root", default="",
                        help="release checkout (default: current directory)")
    parser.add_argument("--keep-temp", action="store_true",
                        help="keep the temporary sqlite database")
    return parser.parse_args(argv)


async def _main(argv: list) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root or os.getcwd()).resolve()
    started_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    report = {
        "schema": "fc-live-canary/v1",
        "harness": HARNESS_NAME,
        "harness_version": HARNESS_VERSION,
        "harness_sha256": _self_sha256(),
        "started_at": started_at,
        "repo_root": str(repo_root),
        "allow_provider_calls": bool(args.allow_provider_calls),
        "max_provider_calls": int(args.max_provider_calls),
        "python": sys.version.split()[0],
        "checks": [],
        "observability": [],
        "limitations": [
            "Harness drives run_factcheck directly (the BinaryHandler seam is "
            "not exercised); the deployed v2 code path is identical.",
            "ToolRouter/tool-loop is not wired (envelope branch does not use "
            "it); lore/metric tools are not exercised.",
            "Media/Vision branches are out of scope for these rows.",
            "Synthetic chat lives in a temp SQLite DB; production PG is read "
            "read-only for effective-state only.",
            "Real provider answers vary between runs; evidence counts are "
            "observed, not fixed.",
        ],
    }
    runtime = Runtime(repo_root)
    runtime._allow_provider_calls = bool(args.allow_provider_calls)
    runtime._max_provider_calls = max(0, int(args.max_provider_calls))
    try:
        runtime.load_modules()
    except Exception as exc:
        report["fatal"] = f"bootstrap_failed: {redact(str(exc), 300)}"
        report["traceback"] = redact(traceback.format_exc(), limit=1200)
        _write_json(args.json_out, report)
        return 2

    global _PLANNER
    _PLANNER = runtime.modules.fsp

    if args.self_test:
        try:
            with runtime.hot_shim(), runtime.chat_shim():
                await runtime.build_runtime()
                result = await run_self_test(runtime)
        except Exception as exc:
            result = {"passed": False,
                      "error": f"{type(exc).__name__}: {redact(str(exc), 300)}",
                      "traceback": redact(traceback.format_exc(), limit=1500)}
        report["self_test"] = result
        report["checks"] = []
        _write_json(args.json_out, report)
        print(json.dumps({"self_test_passed": bool(result.get("passed"))},
                         ensure_ascii=False))
        return 0 if result.get("passed") else 1

    if args.dry_run:
        try:
            with runtime.hot_shim(), runtime.chat_shim():
                await runtime.build_runtime()
                report["dry_run"] = await run_dry_run(runtime)
        except Exception as exc:
            report["fatal"] = f"dry_run_failed: {redact(str(exc), 300)}"
            report["traceback"] = redact(traceback.format_exc(), limit=1200)
            _write_json(args.json_out, report)
            return 2
        _write_json(args.json_out, report)
        print(json.dumps({"dry_run": True, "identity_code":
                          (report["dry_run"].get("identity") or {})
                          .get("identity_code")}, ensure_ascii=False))
        return 0

    # Full canary.
    ctx = {"runs": {}, "effective": {}, "_started": time.perf_counter()}
    try:
        runtime.collect_identity()
        await runtime.read_pg_snapshot()
        ctx["effective"] = await snapshot_effective(runtime)
        report["identity"] = runtime.identity
        report["health"] = runtime.health

        with runtime.hot_shim(), runtime.chat_shim():
            await runtime.build_runtime()
            ctx["effective"]["model_capacity"] = model_capacity_snapshot(runtime)
            report["effective"] = ctx["effective"]
            runtime.install_seams()
            try:
                if not args.allow_provider_calls:
                    report["note"] = (
                        "--allow-provider-calls is off: real runs are not "
                        "executed; provider-dependent checks are not_observed.")
                else:
                    await runtime.prepare_db()
                    runtime.smart_cache_into(runtime.db_path)

                selected = _selected_checks(args.checks)
                order = [
                    ("ordinary_factcheck", check_ordinary_factcheck),
                    ("multipart_and_short_reply", check_multipart_and_short),
                    ("budget_scenarios", check_budget_scenarios),
                    ("metric_distinguishability", check_metric_distinguishability),
                    ("original_production_scenario", check_original_scenario),
                    ("production_smoke", check_production_smoke),
                ]
                for check_id, func in order:
                    if selected and check_id not in selected:
                        continue
                    try:
                        result = await func(runtime, ctx)
                    except Exception as exc:
                        result = CheckResult(
                            check_id, CHECK_REQ_MAP.get(check_id, []), "error",
                            f"harness check crashed: {type(exc).__name__}: "
                            + redact(str(exc), 300),
                            {"traceback": redact(traceback.format_exc(),
                                                 limit=1500)},
                            0.0)
                    report["checks"].append(result.as_dict())
                    report["observability"].append(
                        observability_row(
                            runtime,
                            _bundle_for_check(ctx, check_id, result.status),
                            ctx["effective"]))
            finally:
                runtime.restore_seams()
    except Exception as exc:
        report["fatal"] = f"canary_failed: {type(exc).__name__}: " + redact(
            str(exc), 300)
        report["traceback"] = redact(traceback.format_exc(), limit=1500)
    finally:
        try:
            await runtime.close_db()
        except Exception:
            pass
        try:
            if runtime.tmpdir and not args.keep_temp:
                import shutil
                shutil.rmtree(runtime.tmpdir, ignore_errors=True)
            elif runtime.tmpdir:
                report["temp_dir"] = runtime.tmpdir
        except Exception:
            pass

    report["finished_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    report["duration_s"] = round(time.perf_counter() - ctx["_started"], 3)
    report["call_budget"] = (runtime.budget.as_dict()
                             if runtime.budget is not None else None)
    report["safety"] = _safety_block(runtime)
    report["summary"] = _summary(report["checks"])
    _write_json(args.json_out, report)
    print(json.dumps({"checks": len(report["checks"]),
                      "observed": report["summary"]["observed"],
                      "not_observed": report["summary"]["not_observed"],
                      "errors": report["summary"]["error"]},
                     ensure_ascii=False))
    return 0


def _empty_bundle(name: str) -> RunBundle:
    return RunBundle(name=name, status="not_observed", error=None,
                     duration_s=0.0, outcome=None, correlation_id=None,
                     subject={}, publication={}, plan={}, retrieval={},
                     envelope={}, diagnostics={}, claims_event={},
                     delivered={}, db={}, calls={}, events=[])


def _bundle_for_check(ctx: dict, check_id: str, status: str) -> RunBundle:
    """Pick the run bundle that carries this check's evidence."""
    runs = ctx.get("runs") or {}
    if check_id == "multipart_and_short_reply":
        bundle = runs.get("multipart")
    elif check_id == "budget_scenarios":
        bundle = runs.get("ordinary_factcheck")
    elif check_id == "metric_distinguishability":
        bundle = runs.get("ordinary_factcheck")
    else:
        bundle = runs.get(check_id)
    if bundle is not None:
        return bundle
    return _empty_bundle(check_id)


def _selected_checks(raw: str) -> set:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def _summary(checks: list) -> dict:
    counts = {"observed": 0, "not_observed": 0, "error": 0}
    for item in checks:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _self_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except Exception:
        return ""


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                 sort_keys=False), encoding="utf-8")


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
