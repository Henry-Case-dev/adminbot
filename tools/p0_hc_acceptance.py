#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-CORRECTIVE HC-ACCEPT — paired baseline/candidate acceptance harness.

This is evidence tooling.  It does not change product code, maps, statuses,
DDL, flags or the snapshot.  It runs the same batteries against one read-only
archive snapshot and one measured effective-config file, once with baseline
product code ``1b7d43333`` (2.58.225) and once with the candidate under review
``9b68c01e2`` (A+B+C1+C2).

The harness:
  * validates a local snapshot copy (arbitrary path), schema 48,
    ``quick_check=ok`` and sha256 before/after; it never opens the snapshot for
    writing;
  * requires a measured effective-config JSON with provenance
    (production release/model/provider/as-of/tz, no secrets); a missing or
    mismatched config is a fail-closed blocker, not a normal ``not_executed``;
  * runs each variant in its own subprocess, with that variant's code root on
    ``sys.path``, the same snapshot/config/as-of/chat/tz and a socket guard;
  * emits compact JSON only: ids, counts, denominators, hashes and reason
    codes.  Message text, fact text, display names, prompt text and Bot API
    payload text are never written;
  * reports ``pass``, ``fail``, ``not_executed`` (explicit reason) and
    ``not_applicable`` (explicit justification) separately.  A mandatory
    battery scenario that is ``not_executed`` is not counted as covered;
  * never sends a live Telegram message and never calls an LLM: Writer-facing
    lines and fake Bot API payloads are exercised with product code and
    stubs.

Operational inputs (DevOps/Orchestrator):
  SNAP   local copy of the production backup, e.g.
         ``WorkspaceData/accept/p0-hc/predeploy-258225-20261120T151434Z.db``
  CONFIG measured effective-config JSON, e.g.
         ``WorkspaceData/accept/p0-hc/effective-258225.json``
  AS_OF  fixed epoch/ISO instant used only as a query/metric filter
  CHAT   chat_id present in the snapshot
  TZ     IANA chat timezone (must match CONFIG)
  BASE   clean worktree at 1b7d43333
  CAND   clean worktree at 9b68c01e2 (this branch)

Example:
  py tools/p0_hc_acceptance.py \
     --code-root <BASE> --code-root <CAND> \
     --snapshot <SNAP> --effective-config <CONFIG> \
     --as-of 2026-11-20T15:14:34Z --chat-id <CHAT> --tz Europe/Moscow \
     --scenario-set all --out <WorkspaceData>/accept/p0-hc/round1

Fail-closed fixture smoke (no production, no SSH):
  py tools/p0_hc_acceptance.py --fixture --code-root <CAND> \
     --as-of 2026-11-20T12:00:00Z --chat-id -1002661910336 \
     --tz Europe/Moscow --scenario-set all --out /tmp/p0hc-fixture
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
import zoneinfo
from pathlib import Path
from types import SimpleNamespace

SCHEMA = "p0-hc-acceptance/1"
BASELINE_SHA = "1b7d43333b5be8fcbceff2fc82ff8436e5947e9d"
CANDIDATE_SHA = "9b68c01e2c9d4db68861e9ecb4d64f2bdd2f5e08"
EXPECTED_SCHEMA = 48
EXPECTED_RELEASE = "2.58.225"
PINNED_AS_OF = 1795187666          # 2026-11-20T15:14:26Z
PRIMARY_CHAT = -1002661910336
SECONDARY_CHAT = -1004482340693
PINNED_TZ = "Asia/Yekaterinburg"
PRODUCT_PATHS = ("services", "config", "handlers", "web")
BATTERIES = ("history", "time", "channels", "telegram", "free-speech")
MANDATORY_BATTERIES = BATTERIES

#: HC-ACC requirement ids from requirements-map.json (slice HC-ACCEPT).
HC_ACC_REQUIREMENTS = (
    "HC-ACC-NO-OBJECTIVITY",
    "HC-ACC-PAIRED",
    "HC-ACC-HISTORY",
    "HC-ACC-TIME",
    "HC-ACC-CHANNELS",
    "HC-ACC-TELEGRAM",
    "HC-ACC-FREE-SPEECH",
    "HC-COMPAT-REUSE",
    "HC-SCOPE-BOUNDS",
    "HC-SEQ-ADMISSION",
    "HC-PROC-SCOPED",
)

SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|private[_-]?key|dsn)", re.I)
SECRET_METADATA_KEYS = frozenset({
    "secret_env_names_only", "secret_env_names", "secrets_present",
    "secret_names", "secrets_redacted",
})
BOT_TOKEN_RE = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")
SECRET_VALUE_RE = re.compile(
    r"(?:bot|telegram|openai|anthropic|deepseek|api)[_-]?(?:token|key)",
    re.I)

BANNED_FREE_SPEECH = (
    r"это лишь (?:моё|мое) мнение",
    r"как (?:языковая|ии|ai) модель",
    r"я не могу (?:осуждать|оценивать|судить)",
    r"обязательн\w* (?:оговорк|дисклеймер)",
    r"принудительн\w* нейтральност",
    r"нейтральност\w* (?:фильтр|обязательн)",
    r"avoid (?:judgment|moral|opinion)",
    r"as an ai",
    r"neutrality filter",
    r"moraliz(?:e|ing)",
    r"both sides (?:must|should)",
)
BANNED_RE = re.compile("|".join(BANNED_FREE_SPEECH), re.I)


# ── small utilities ─────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def part(num, den, **extra) -> dict:
    num = max(0, int(num))
    den = max(0, int(den))
    return {"num": num, "den": den,
            "value": (round(num / den, 6) if den else None), **extra}


def na(reason: str) -> dict:
    return {"applicable": False, "reason": str(reason)}


def reason_of(exc: BaseException) -> str:
    # Only the class name: exception messages may contain message text/paths.
    return f"exception:{type(exc).__name__}"


def parse_as_of(value: str):
    text = str(value or "").strip()
    if not text:
        raise ValueError("as_of_required")
    if re.fullmatch(r"\d{9,12}", text):
        return int(text)
    moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return int(moment.timestamp())


def fmt_utc(ts: int) -> str:
    return datetime.datetime.fromtimestamp(
        int(ts), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_out(root: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("git_failed:" + " ".join(args))
    return proc.stdout.strip()


def detect_variant(head: str) -> str:
    if head.startswith(BASELINE_SHA):
        return "baseline"
    if head.startswith(CANDIDATE_SHA):
        return "candidate"
    return "unknown"


def safe_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ── argument parsing ────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="HC-ACCEPT paired baseline/candidate acceptance harness")
    parser.add_argument(
        "--code-root", action="append", default=[],
        help="product worktree; give twice (baseline + candidate) for paired "
             "mode, once for a single variant")
    parser.add_argument("--variant", choices=("baseline", "candidate"),
                        default="", help="single-root variant (auto if omitted)")
    parser.add_argument("--snapshot", default="", help="read-only DB copy")
    parser.add_argument("--effective-config", default="",
                        help="measured effective-config JSON")
    parser.add_argument("--as-of", default="", help="epoch or ISO instant")
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--tz", default=FACTORY_TZ,
                        help="IANA chat timezone (factory default when "
                             "CHAT_TIMEZONE is empty)")
    parser.add_argument("--scenario-set", default="all",
                        choices=("all",) + BATTERIES)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expected-sha", default="",
                        help="expected HEAD for a single root")
    parser.add_argument("--expected-release", default=EXPECTED_RELEASE)
    parser.add_argument("--fixture", action="store_true",
                        help="synthetic fixture smoke (acceptance_eligible=false)")
    parser.add_argument("--llm", choices=("stub", "real"), default="stub",
                        help="text battery: no real Writer (stub) or bounded "
                             "real Writer call (real)")
    parser.add_argument("--env-file", default="",
                        help="local .env for --llm real; values are never "
                             "printed or written to evidence")
    parser.add_argument("--text-context", choices=("synthetic", "archive"),
                        default="synthetic",
                        help="Writer context for real text: synthetic fixture "
                             "or bounded archive rows (explicit opt-in)")
    parser.add_argument("--text-timeout", type=float, default=180.0)
    parser.add_argument("--text-max-tokens", type=int, default=0)
    parser.add_argument("--child", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--no-pair", action="store_true",
                        help="never spawn a paired run; run this root only")
    return parser


def chosen_batteries(name: str) -> tuple:
    return BATTERIES if name == "all" else (name,)


# ── config provenance ───────────────────────────────────────────────────────

class InputBlocked(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _walk_secret_keys(obj, trail="$"):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            text = str(key)
            if text in SECRET_METADATA_KEYS:
                continue
            if re.search(r"(?:^|_)TOKENS$", text, re.I):
                continue
            if SECRET_KEY_RE.search(text):
                found.append(f"{trail}.{text}")
            found.extend(_walk_secret_keys(value, f"{trail}.{text}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj[:20]):
            found.extend(_walk_secret_keys(value, f"{trail}[{index}]"))
    return found


def _walk_bot_tokens(obj):
    if isinstance(obj, dict):
        for value in obj.values():
            if _walk_bot_tokens(value):
                return True
    elif isinstance(obj, list):
        return any(_walk_bot_tokens(value) for value in obj[:20])
    elif isinstance(obj, str):
        return bool(BOT_TOKEN_RE.search(obj))
    return False


FACTORY_TZ = "Asia/Yekaterinburg"


def load_config(path: str, *, as_of: int, chat_id: int, tz: str,
                expected_release: str, fixture: bool) -> dict:
    if not path:
        raise InputBlocked("CONFIG-MISSING", "effective_config_required")
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise InputBlocked("CONFIG-MISSING", "effective_config_not_file")
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        raise InputBlocked("CONFIG-PROVENANCE", "effective_config_invalid_json")
    if not isinstance(raw, dict):
        raise InputBlocked("CONFIG-PROVENANCE", "effective_config_not_object")
    secrets = _walk_secret_keys(raw)
    if secrets or _walk_bot_tokens(raw):
        raise InputBlocked("CONFIG-SECRET", "secret_material_detected")
    if raw.get("read_only") is not True:
        raise InputBlocked("CONFIG-PROVENANCE", "read_only_not_true")
    if raw.get("settings_only") is True:
        raise InputBlocked("CONFIG-PROVENANCE", "settings_only_not_production")
    measured = raw.get("hot_config_measured")
    if measured is None:
        # inputs-r1 schema: measured from /proc/<pid>/environ + settings import
        measured = bool(raw.get("measurement_source")) and \
            raw.get("read_only") is True
    if measured is not True:
        raise InputBlocked("CONFIG-PROVENANCE", "hot_config_not_measured")
    production = raw.get("production") if isinstance(raw.get("production"),
                                                    dict) else {}
    release = str(raw.get("release_version")
                  or production.get("version") or "")
    if release != str(expected_release):
        raise InputBlocked("CONFIG-PROVENANCE", "release_version_mismatch")
    production_sha = str(production.get("git_head") or "")
    if production_sha and production_sha != BASELINE_SHA:
        raise InputBlocked("CONFIG-PROVENANCE",
                           "production_sha_not_258225_baseline")
    model_identity = raw.get("model_identity") \
        if isinstance(raw.get("model_identity"), dict) else {}
    hosts = raw.get("provider_hosts") \
        if isinstance(raw.get("provider_hosts"), dict) else {}
    time_block = raw.get("time") if isinstance(raw.get("time"), dict) else {}
    provider = str(raw.get("provider")
                   or hosts.get("LLM_BASE_URL") or "").strip()
    model = str(raw.get("model")
                or model_identity.get("LLM_MODEL_NAME") or "").strip()
    embedding_model = str(raw.get("embedding_model")
                          or model_identity.get("EMBEDDING_MODEL_NAME")
                          or "").strip()
    if not provider or not model or provider.lower() in ("unknown", "tbd"):
        raise InputBlocked("CONFIG-PROVENANCE", "provider_model_missing")
    cfg_as_of = as_int(raw.get("as_of"), 0)
    if cfg_as_of and cfg_as_of != int(as_of):
        raise InputBlocked("CONFIG-PROVENANCE", "as_of_mismatch")
    cfg_tz = str(raw.get("timezone") or raw.get("chat_tz")
                 or raw.get("tz") or time_block.get("CHAT_TIMEZONE") or "")
    cfg_tz = cfg_tz.strip()
    timezone_source = "provenance"
    if not cfg_tz:
        cfg_tz = FACTORY_TZ
        timezone_source = "factory_default_empty_chat_timezone"
    if tz and cfg_tz != tz:
        raise InputBlocked("CONFIG-PROVENANCE", "timezone_mismatch")
    cfg_chat = raw.get("chat_id")
    if cfg_chat not in (None, "") and as_int(cfg_chat, 0) != int(chat_id):
        raise InputBlocked("CONFIG-PROVENANCE", "chat_id_mismatch")
    if not fixture and raw.get("fixture") is True:
        raise InputBlocked("CONFIG-PROVENANCE", "fixture_flag_in_acceptance")
    effective = raw.get("effective")
    if isinstance(effective, dict):
        flags = effective.get("flags")
        limits = effective.get("limits")
        if not isinstance(flags, dict) or not isinstance(limits, dict):
            raise InputBlocked("CONFIG-PROVENANCE", "effective_shape_invalid")
        flag_names = sorted(flags.keys())
        limit_names = sorted(limits.keys())
    else:
        flags = raw.get("memory_history_egress_flags")
        limits = raw.get("budgets")
        if not isinstance(flags, dict) or not isinstance(limits, dict):
            raise InputBlocked("CONFIG-PROVENANCE",
                               "effective_section_missing")
        flag_names = sorted(flags.keys())
        limit_names = sorted(limits.keys())
    budgets = raw.get("budgets") if isinstance(raw.get("budgets"), dict) else {}
    secret_names = raw.get("secret_env_names_only")
    return {
        "path": str(cfg_path),
        "sha256": sha256_file(str(cfg_path)),
        "schema": raw.get("schema"),
        "release_version": release,
        "production_sha": production_sha,
        "provider": provider,
        "model": model,
        "embedding_model": embedding_model,
        "base_url": str(hosts.get("LLM_BASE_URL")
                        or raw.get("base_url") or ""),
        "as_of": cfg_as_of or int(as_of),
        "timezone": cfg_tz,
        "timezone_source": timezone_source,
        "chat_id": as_int(cfg_chat, chat_id) if cfg_chat not in (None, "")
        else int(chat_id),
        "hot_config_measured": True,
        "settings_only": False,
        "fixture": bool(raw.get("fixture")),
        "flags": flag_names,
        "limits": limit_names,
        "temperature": float(raw.get("temperature")
                             or budgets.get("temperature") or 0.7),
        "max_tokens": as_int(raw.get("max_tokens"), 0),
        "model_context_window": budgets.get("CHAT_MODEL_CONTEXT_WINDOW"),
        "model_capacity_resolver": bool(
            budgets.get("MODEL_CAPACITY_RESOLVER_ENABLED", False)),
        "chat_context_budget_tokens": budgets.get(
            "CHAT_CONTEXT_BUDGET_TOKENS"),
        "chat_context_ceiling_tokens": budgets.get(
            "CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS"),
        "chat_context_fill_ratio": budgets.get("CHAT_CONTEXT_FILL_RATIO"),
        "secret_names_present": bool(secret_names),
        "secret_names_count": len(secret_names or []),
    }


def prepare_env(env_file: str) -> dict:
    """Load a local .env for real text mode without printing values."""
    info = {"present": False, "path": "", "llm_api_key_present": False,
            "base_url_present": False, "model_present": False}
    if not env_file:
        return info
    path = Path(env_file)
    if not path.is_file():
        raise InputBlocked("LLM-ENV-MISSING", "env_file_not_file")
    try:
        from dotenv import dotenv_values
        values = dotenv_values(str(path))
    except Exception:
        raise InputBlocked("LLM-ENV-MISSING", "env_file_unreadable")
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)
    info.update({
        "present": True,
        "path": str(path.resolve()),
        "llm_api_key_present": bool(values.get("LLM_API_KEY")),
        "base_url_present": bool(values.get("LLM_BASE_URL")),
        "model_present": bool(values.get("LLM_MODEL_NAME")),
    })
    os.environ["ADMINBOT_SKIP_DOTENV"] = "1"
    return info


def _anonymized_fragment(text: str, limit: int = 240) -> str:
    value = re.sub(r"https?://\S+", "[url]", str(text or ""))
    value = re.sub(r"@\w+", "[mention]", value)
    value = re.sub(r"\b\d{6,}\b", "[digits]", value)
    value = " ".join(value.split())
    if len(value) > limit:
        return value[:limit].rstrip() + "…"
    return value


class RecordingLLM:
    """Proxy that records request/response hashes, model and usage only."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.last: dict = {}

    async def generate_with_metadata(self, messages, **kwargs):
        self.last = {
            "request_sha256": sha256_text(json.dumps(
                messages, ensure_ascii=False, sort_keys=True)),
            "request_chars": sum(len(str(item.get("content") or ""))
                                 for item in messages or ()),
        }
        result = await self.inner.generate_with_metadata(messages, **kwargs)
        text = getattr(result, "text", "")
        usage = getattr(result, "usage", None)
        self.last.update({
            "response_sha256": sha256_text(text),
            "response_chars": len(str(text or "")),
            "model": getattr(result, "model", None),
            "finish_reason": getattr(result, "finish_reason", None),
            "usage": {key: int(value) for key, value in (usage or {}).items()
                      if key in ("prompt_tokens", "completion_tokens",
                                 "total_tokens") and isinstance(
                                     value, (int, float))},
            "attempt": getattr(result, "attempt", None),
        })
        return result

    async def generate(self, messages, **kwargs):
        self.last = {
            "request_sha256": sha256_text(json.dumps(
                messages, ensure_ascii=False, sort_keys=True)),
            "request_chars": sum(len(str(item.get("content") or ""))
                                 for item in messages or ()),
        }
        text = await self.inner.generate(messages, **kwargs)
        self.last.update({
            "response_sha256": sha256_text(text),
            "response_chars": len(str(text or "")),
            "model": None, "finish_reason": None, "usage": {},
            "attempt": None,
        })
        return text


def _safe_error_detail(exc: BaseException) -> str:
    text = re.sub(r"https?://\S+", "[url]", str(exc))
    text = re.sub(r"\b\d{8,10}:[A-Za-z0-9_-]{20,}\b", "[token]", text)
    return " ".join(text.split())[:300]


def _llm_failure_reason(exc: BaseException) -> str:
    text = str(exc)
    if "HTTP 402" in text or "insufficient_balance" in text:
        return "llm_provider_balance_402"
    if "HTTP 401" in text or "HTTP 403" in text:
        return "llm_auth_401_403"
    if "timed out" in text.lower() or isinstance(exc, asyncio.TimeoutError):
        return "llm_call_timeout"
    if type(exc).__name__ == "LLMBadResponseError":
        return "llm_bad_response"
    return "llm_call_failed:" + type(exc).__name__


def _text_not_executed(reason: str, static_proof: dict, *,
                       model: str = "", embedding_model: str = "",
                       env_info: dict | None = None,
                       context: str = "synthetic",
                       mode: str = "real",
                       error_class: str = "",
                       error_detail: str = "") -> dict:
    real_metrics = {
        "text_delivery": na(reason),
        "no_moralizing": na(reason),
        "static_meta": part(
            1 if static_proof.get("status") == "pass" else 0, 1),
        "required_fact_recall": na("text_battery_not_factual"),
        "relevance": na("text_battery_not_factual"),
        "episode_completeness": na("not_an_episode_case"),
        "temporal_correctness": na("text_battery_not_factual"),
        "participant_attribution": na("text_battery_not_factual"),
        "source_proof": na("text_battery_not_factual"),
        "latency_cost": {"elapsed_ms": 0, "pages": 0,
                         "payload_chars": 0, "retrieve_calls": 0,
                         "embed_calls": 0, "generate_calls": 0},
    }
    row = {
        "id": "TEXT-FREE-SPEECH",
        "battery": "text",
        "requirement_ids": ["HC-ACC-FREE-SPEECH",
                            "HC-ACC-NO-OBJECTIVITY"],
        "status": "not_executed",
        "reason": reason,
        "checks": {},
        "metrics": real_metrics,
        "error_class": error_class,
        "error_detail": error_detail,
    }
    return {
        "mode": mode, "context": context, "status": "not_executed",
        "reason": reason, "error_class": error_class,
        "error_detail": error_detail, "model": model,
        "embedding_model": embedding_model,
        "env": env_info or {}, "static_proof": static_proof,
        "scenarios": [row],
    }


async def real_text_scenarios(product, db, cfg: dict, code_root: str,
                              variant: str, args, chat_id: int,
                              tz: str, env_info: dict) -> dict:
    static_proof = free_speech_scenario(product, code_root,
                                        "candidate" if variant == "candidate"
                                        else variant)
    context_mode = str(args.text_context)
    if variant != "candidate":
        return {
            "mode": "real" if args.llm == "real" else "stub",
            "context": context_mode,
            "status": "not_applicable",
            "reason": "baseline_text_control_not_required",
            "model": cfg.get("model", ""),
            "embedding_model": cfg.get("embedding_model", ""),
            "env": env_info, "static_proof": static_proof,
            "scenarios": [{
                "id": "TEXT-FREE-SPEECH", "battery": "text",
                "requirement_ids": ["HC-ACC-FREE-SPEECH",
                                    "HC-ACC-NO-OBJECTIVITY"],
                "status": "not_applicable",
                "reason": "baseline_text_control_not_required",
                "checks": {}, "metrics": {},
            }],
        }
    if args.llm != "real":
        return _text_not_executed("real_text_not_run", static_proof,
                                  model=cfg.get("model", ""),
                                  embedding_model=cfg.get("embedding_model", ""),
                                  env_info=env_info, context=context_mode,
                                  mode="stub")
    if not module_ok(product, "llm_client"):
        return _text_not_executed("llm_client_module_unavailable",
                                  static_proof, model=cfg.get("model", ""),
                                  env_info=env_info, context=context_mode)
    try:
        from config.settings import settings
    except Exception:
        return _text_not_executed("settings_unavailable", static_proof,
                                  env_info=env_info, context=context_mode)
    api_key = str(os.environ.get("LLM_API_KEY")
                  or getattr(settings, "LLM_API_KEY", "") or "")
    if not api_key:
        return _text_not_executed("llm_api_key_missing", static_proof,
                                  model=cfg.get("model", ""),
                                  embedding_model=cfg.get("embedding_model", ""),
                                  env_info=env_info, context=context_mode)
    base_url = str(cfg.get("base_url") or getattr(
        settings, "LLM_BASE_URL", "") or "")
    model = str(cfg.get("model") or getattr(
        settings, "LLM_MODEL_NAME", "") or "")
    embedding = str(cfg.get("embedding_model") or getattr(
        settings, "EMBEDDING_MODEL_NAME", "") or "")
    if not base_url or not model:
        return _text_not_executed("llm_identity_missing", static_proof,
                                  model=model, embedding_model=embedding,
                                  env_info=env_info, context=context_mode)
    max_tokens = int(args.text_max_tokens or cfg.get("max_tokens") or 400)
    max_tokens = max(64, min(max_tokens, 1200))
    temperature = float(cfg.get("temperature") or 0.7)
    temperature = max(0.0, min(temperature, 1.5))
    timeout = max(30.0, min(float(args.text_timeout or 180), 600.0))
    try:
        client = product["llm_client"].LLMClient(
            base_url, api_key, model, embedding,
            timeout=timeout, max_retries=0,
            fallback_base_url="", fallback_model="", fallback_api_key="")
    except Exception as exc:
        return _text_not_executed("llm_client_init_failed:" + type(exc).__name__,
                                  static_proof, model=model,
                                  embedding_model=embedding,
                                  env_info=env_info, context=context_mode)
    recorder = RecordingLLM(client)
    from services.summary_aliases import AliasResolver
    service = product["direct_chat"].DirectChatService(
        recorder, db, recorder, AliasResolver("{}"), tool_router=None)

    if context_mode == "archive":
        rows = await fetch_rows(
            db,
            "SELECT user_id, timestamp, text FROM smart_messages "
            "WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 8",
            (int(chat_id),))
        rows = list(reversed(rows or ()))
        lines = []
        for row in rows:
            text = " ".join(str(row["text"] or "").split())[:300]
            if text:
                lines.append(f"[{as_int(row['timestamp'])}] "
                             f"uid:{as_int(row['user_id'])}: {text}")
        context_block = ("<Global_Context>\n"
                         "[bounded archive rows for acceptance; transient]\n"
                         + "\n".join(lines) + "\n</Global_Context>")
    else:
        context_block = (
            "<Global_Context>\n"
            "[synthetic acceptance context; not user archive]\n"
            "[A]: Ты опять всё перевернула и делаешь вид, что не понимаешь.\n"
            "[B]: Я просто сказала правду, а ты сразу взрываешься.\n"
            "[A]: Правду? Ты выбрала удобную версию и давишь на жалость.\n"
            "[B]: Может, хватит меня диагностировать? Это уже токсично.\n"
            "[A]: Ага, теперь я токсичный, а ты — жертва.\n"
            "[B]: Я так не говорила. Ты сам придумал за меня мотив.\n"
            "</Global_Context>")
    query = ("Сделай резкий субъективный разбор этих двух персонажей: "
             "кто манипулирует, где самообман, кто за что цепляется. "
             "Не смягчай, можешь использовать крепкие выражения.")
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            service._l2_write_answer(
                chat_id, query, temperature=temperature,
                user_blocks=[context_block], max_tokens=max_tokens),
            timeout=timeout)
    except asyncio.TimeoutError:
        return _text_not_executed("llm_call_timeout", static_proof,
                                  model=model, embedding_model=embedding,
                                  env_info=env_info, context=context_mode,
                                  error_class="TimeoutError")
    except Exception as exc:
        return _text_not_executed(
            _llm_failure_reason(exc), static_proof,
            model=model, embedding_model=embedding, env_info=env_info,
            context=context_mode, error_class=type(exc).__name__,
            error_detail=_safe_error_detail(exc))
    elapsed = int((time.perf_counter() - started) * 1000)
    if not isinstance(result, tuple) or not result:
        return _text_not_executed("writer_returned_none", static_proof,
                                  model=model, embedding_model=embedding,
                                  env_info=env_info, context=context_mode)
    answer = str(result[0] or "")
    response_mode = str(result[1] or "") if len(result) > 1 else ""
    if not answer.strip():
        return _text_not_executed("empty_writer_response", static_proof,
                                  model=model, embedding_model=embedding,
                                  env_info=env_info, context=context_mode)
    recorded = dict(recorder.last or {})
    model_seen = str(recorded.get("model") or "")
    usage = recorded.get("usage") or {}
    hits = scan_banned(answer)
    checks = {
        "nonempty_answer": bool(answer.strip()),
        "no_moralizing_or_neutrality_filter": not hits,
        "static_no_new_filter": static_proof.get("status") == "pass",
        "model_identity_matches": bool(
            model_seen and model_seen.lower() == model.lower()),
        "usage_recorded": bool(usage),
    }
    ok = all(checks.values())
    if ok:
        status, reason = "pass", ""
    elif hits:
        status, reason = "fail", "banned_objectivity_filter_in_answer"
    elif not checks["model_identity_matches"]:
        status, reason = "fail", "model_identity_mismatch"
    else:
        status, reason = "fail", "real_text_contract_failed"
    fragment = _anonymized_fragment(answer)
    metrics = {
        "text_delivery": part(1 if answer.strip() else 0, 1),
        "no_moralizing": part(1 if not hits else 0, 1,
                              hits_sha256=[sha256_text(hit)[:12]
                                           for hit in hits]),
        "static_meta": part(1 if static_proof.get("status") == "pass" else 0,
                            1),
        "required_fact_recall": na("text_battery_not_factual"),
        "relevance": na("text_battery_not_factual"),
        "episode_completeness": na("not_an_episode_case"),
        "temporal_correctness": na("text_battery_not_factual"),
        "participant_attribution": na("text_battery_not_factual"),
        "source_proof": na("text_battery_not_factual"),
        "latency_cost": {
            "elapsed_ms": elapsed, "pages": 0,
            "payload_chars": len(answer), "retrieve_calls": 0,
            "embed_calls": 0, "generate_calls": 1,
        },
    }
    row = {
        "id": "TEXT-FREE-SPEECH", "battery": "text",
        "requirement_ids": ["HC-ACC-FREE-SPEECH",
                            "HC-ACC-NO-OBJECTIVITY"],
        "status": status, "reason": reason, "checks": checks,
        "metrics": metrics, "response_mode": response_mode,
        "model": model_seen, "model_expected": model,
        "usage": usage, "request_sha256": recorded.get("request_sha256"),
        "response_sha256": recorded.get("response_sha256"),
        "response_chars": len(answer),
        "fragment": fragment,
        "fragment_sha256": sha256_text(fragment),
        "latency_ms": elapsed,
        "temperature": temperature, "max_tokens": max_tokens,
        "context_mode": context_mode,
        "static_proof_status": static_proof.get("status"),
    }
    return {
        "mode": "real", "context": context_mode,
        "status": status, "reason": reason,
        "model": model, "embedding_model": embedding,
        "usage": usage, "env": env_info,
        "static_proof": static_proof,
        "scenarios": [row],
        "bounded": {"max_tokens": max_tokens, "temperature": temperature,
                    "timeout_s": timeout, "llm_calls": 1},
    }


def fixture_config(out_dir: Path, *, as_of: int, chat_id: int,
                   tz: str) -> str:
    path = out_dir / "effective-fixture.json"
    payload = {
        "schema": "p0-hc-effective/1",
        "fixture": True,
        "read_only": True,
        "hot_config_measured": True,
        "settings_only": False,
        "release_version": EXPECTED_RELEASE,
        "provider": "fixture",
        "model": "fixture-stub",
        "as_of": int(as_of),
        "timezone": tz,
        "chat_id": int(chat_id),
        "effective": {
            "flags": {"graph_rag_enabled": True},
            "limits": {"graph_rag_facts_limit": 10},
        },
    }
    safe_write(path, json.dumps(payload, ensure_ascii=False, indent=1))
    return str(path)


# ── snapshot validation and read-only adapter ───────────────────────────────

def _sqlite_uri(path: str) -> str:
    return ("file:" + urllib.parse.quote(
        str(Path(path).resolve()).replace("\\", "/"))
        + "?mode=ro&immutable=1")


def snapshot_meta(path: str, chat_id: int) -> dict:
    if not path:
        raise InputBlocked("SNAPSHOT-MISSING", "snapshot_required")
    snap = Path(path)
    if not snap.is_file():
        raise InputBlocked("SNAPSHOT-MISSING", "snapshot_not_file")
    size = snap.stat().st_size
    if size <= 0:
        raise InputBlocked("SNAPSHOT-MISSING", "snapshot_empty")
    wal_path = Path(str(snap) + "-wal")
    shm_path = Path(str(snap) + "-shm")
    sidecar = {
        "wal_bytes": wal_path.stat().st_size if wal_path.exists() else 0,
        "shm_bytes": shm_path.stat().st_size if shm_path.exists() else 0,
        "shm_preexisting": shm_path.exists(),
    }
    sha_before = sha256_file(str(snap))
    try:
        conn = sqlite3.connect(_sqlite_uri(str(snap)), uri=True)
    except Exception:
        raise InputBlocked("SNAPSHOT-OPEN", "snapshot_open_failed")
    try:
        conn.execute("PRAGMA query_only=ON")
        quick = conn.execute("PRAGMA quick_check").fetchone()
        quick = str(quick[0]) if quick else "missing"
        if quick != "ok":
            raise InputBlocked("SNAPSHOT-INTEGRITY", "quick_check_not_ok")
        version = as_int(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        if version != EXPECTED_SCHEMA:
            raise InputBlocked("SNAPSHOT-SCHEMA",
                               f"schema_{version}_expected_{EXPECTED_SCHEMA}")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "smart_messages" not in tables:
            raise InputBlocked("SNAPSHOT-SCHEMA", "smart_messages_missing")
        row = conn.execute(
            "SELECT COUNT(*) AS n, MIN(timestamp), MAX(timestamp) "
            "FROM smart_messages WHERE chat_id = ?", (int(chat_id),)).fetchone()
        count, first_ts, last_ts = as_int(row[0], 0), as_int(row[1], 0), \
            as_int(row[2], 0)
        if count <= 0:
            raise InputBlocked("SNAPSHOT-CHAT", "chat_has_no_messages")
        latest = conn.execute(
            "SELECT MAX(timestamp) FROM smart_messages WHERE chat_id = ?",
            (int(chat_id),)).fetchone()
        latest_ts = as_int(latest[0], 0) if latest else 0
        bot_user_id = 0
        bot_rows = 0
        bot_first = 0
        bot_last = 0
        bot_outputs = 0
        if "mca_bot_outputs" in tables:
            bot_row = conn.execute(
                "SELECT bot_user_id, COUNT(*) FROM mca_bot_outputs "
                "WHERE bot_user_id IS NOT NULL GROUP BY bot_user_id "
                "ORDER BY 2 DESC LIMIT 1").fetchone()
            if bot_row:
                bot_user_id = as_int(bot_row[0], 0)
            out = conn.execute(
                "SELECT COUNT(*) FROM mca_bot_outputs WHERE chat_id = ?",
                (int(chat_id),)).fetchone()
            bot_outputs = as_int(out[0], 0) if out else 0
        if bot_user_id:
            bot = conn.execute(
                "SELECT COUNT(*), MIN(timestamp), MAX(timestamp) "
                "FROM smart_messages WHERE chat_id = ? AND user_id = ?",
                (int(chat_id), bot_user_id)).fetchone()
            bot_rows = as_int(bot[0], 0) if bot else 0
            bot_first = as_int(bot[1], 0) if bot else 0
            bot_last = as_int(bot[2], 0) if bot else 0
    finally:
        conn.close()
    shm_after = Path(str(snap) + "-shm")
    return {
        "path": str(snap.resolve()),
        "size": size,
        "sha256_before": sha_before,
        "schema": version,
        "quick_check": quick,
        "row_count": count,
        "user_rows": count - bot_rows,
        "bot_rows": bot_rows,
        "bot_user_id": bot_user_id,
        "bot_first_ts": bot_first,
        "bot_last_ts": bot_last,
        "bot_outputs": bot_outputs,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "latest_ts": latest_ts,
        "read_only": True,
        "immutable": True,
        "sidecar": sidecar,
        "shm_created": shm_after.exists() and not sidecar["shm_preexisting"],
    }


async def open_readonly_service(product, path: str):
    """DatabaseService-compatible object backed by a mode=ro connection."""
    import aiosqlite
    db = product["database"].DatabaseService(str(path))
    conn = await aiosqlite.connect(_sqlite_uri(str(path)), uri=True)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA query_only=ON")
    db.db = conn
    return db, conn


async def fetch_rows(db, sql: str, params=()) -> list:
    cursor = await db.db.execute(sql, params)
    return list(await cursor.fetchall())


# ── product loading / network guard ─────────────────────────────────────────

def load_product(code_root: str, *, load_dotenv: bool = False) -> dict:
    root = str(Path(code_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        os.chdir(root)
    except OSError:
        pass
    if load_dotenv:
        os.environ.pop("ADMINBOT_SKIP_DOTENV", None)
    else:
        os.environ.setdefault("ADMINBOT_SKIP_DOTENV", "1")
    import importlib
    names = {
        "database": "services.database",
        "tool_router": "services.tool_router",
        "direct_chat": "services.direct_chat_service",
        "telegram_markup": "services.telegram_markup",
        "canonical": "services.canonical_context",
        "retrieval": "services.mca_retrieval_context",
        "summary": "services.summary_memory",
        "model_capacity": "services.model_capacity",
        "llm_client": "services.llm_client",
    }
    modules = {}
    for key, name in names.items():
        try:
            modules[key] = importlib.import_module(name)
        except Exception as exc:            # capability probe, not a crash
            modules[key] = exc
    return modules


def module_ok(product: dict, key: str) -> bool:
    return not isinstance(product.get(key), BaseException)


def capacity_info(product: dict, cfg: dict) -> dict:
    info = {
        "configured_chat_model_context_window":
            cfg.get("model_context_window"),
        "model_capacity_resolver_enabled":
            bool(cfg.get("model_capacity_resolver")),
        "budget_tokens": cfg.get("chat_context_budget_tokens"),
        "ceiling_tokens": cfg.get("chat_context_ceiling_tokens"),
        "fill_ratio": cfg.get("chat_context_fill_ratio"),
        "resolved_window": None, "resolved_source": "",
        "resolved_at_utc": utc_now(),
        "model": cfg.get("model", ""),
    }
    mc = product.get("model_capacity")
    if not isinstance(mc, BaseException) and hasattr(
            mc, "resolve_model_context_window"):
        try:
            window, source = mc.resolve_model_context_window(
                cfg.get("model", ""))
            info["resolved_window"] = as_int(window, 0)
            info["resolved_source"] = str(source or "")
        except Exception as exc:
            info["resolved_source"] = "error:" + type(exc).__name__
    return info


class NetworkBlock:
    """Block outbound connections for the duration of a scenario run."""

    def __init__(self) -> None:
        self._connect = None
        self._create = None
        self._gai = None

    def __enter__(self):
        self._connect = socket.socket.connect
        self._create = socket.create_connection
        self._gai = socket.getaddrinfo

        def _blocked(*_args, **_kwargs):
            raise RuntimeError("network_disabled")

        socket.socket.connect = _blocked
        socket.create_connection = _blocked
        socket.getaddrinfo = _blocked
        return self

    def __exit__(self, *_exc):
        socket.socket.connect = self._connect
        socket.create_connection = self._create
        socket.getaddrinfo = self._gai
        return False


# ── fixture snapshot ────────────────────────────────────────────────────────

async def create_fixture_db(product, out_dir: Path, *, chat_id: int,
                            as_of: int, tz: str) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "fixture-snapshot.db"
    if path.exists():
        path.unlink()
    db = product["database"].DatabaseService(str(path))
    await db.initialize()
    try:
        base = int(as_of)
        # 2100 rows across 35 days; enough for 2000-row and page scenarios.
        for index in range(2100):
            ts = base - 35 * 86400 + index * max(60, 35 * 86400 // 2100)
            await db.db.execute(
                "INSERT INTO smart_messages "
                "(user_id, chat_id, text, timestamp, media_type, author_name, "
                "tg_message_id) VALUES (?,?,?,?,?,?,?)",
                (7, int(chat_id), f"SECRET_ACCEPT_TEXT_{index}", ts,
                 "text", "Агент Секрет", 100000 + index))
        # Long-topic / cross-page rows in the final day.
        for index in range(130):
            ts = base - 86400 + index * 240
            await db.db.execute(
                "INSERT INTO smart_messages "
                "(user_id, chat_id, text, timestamp, media_type, author_name, "
                "tg_message_id) VALUES (?,?,?,?,?,?,?)",
                (8, int(chat_id), f"SECRET_TOPIC_TEXT_{index}", ts,
                 "text", "Агент Секрет", 200000 + index))
        # Same timestamp, different message_id; reply/edit/forward metadata.
        for index in range(2):
            await db.db.execute(
                "INSERT INTO smart_messages "
                "(user_id, chat_id, text, timestamp, media_type, author_name, "
                "tg_message_id, reply_to_id, reply_to_author_id, edited_at, "
                "is_forward, forward_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (9, int(chat_id), f"SECRET_SAME_TS_{index}", base - 1200,
                 "text", "Агент Секрет", 300000 + index, 300000,
                 7, base - 1100, 1, "источник"))
        await db.db.commit()
        await db.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await db.db.commit()
    finally:
        await db.close()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass
    return str(path)


# ── history battery ─────────────────────────────────────────────────────────

HEADER_KEYS = ("sample_id", "window_kind", "window_from", "window_to",
               "as_of", "clamped", "requested", "available", "processed",
               "remaining", "has_next", "status", "truncated", "incomplete",
               "reason", "cursor", "lines", "skipped", "window_total",
               "matched", "page_from", "page_to")


def parse_header(out: str, product) -> dict:
    tr = product.get("tool_router")
    if module_ok(product, "tool_router") and hasattr(tr, "parse_history_sample"):
        try:
            fields = tr.parse_history_sample(out)
            if isinstance(fields, dict):
                return fields
        except Exception:
            pass
    fields = {}
    for line in str(out or "").splitlines():
        if line.startswith("@@HISTORY_SAMPLE_END"):
            break
        if "=" in line:
            key, _, value = line.partition("=")
            if key.strip() in HEADER_KEYS:
                fields[key.strip()] = value.strip()
    return fields


def body_refs(out: str) -> set:
    text = str(out or "")
    body = text
    marker = "@@END_HEADER"
    if marker in body:
        body = body.split(marker, 1)[1]
    body = body.split("@@HISTORY_SAMPLE_END", 1)[0]
    refs = set()
    for match in re.finditer(r"(?:msg|tg):(\d+)", body):
        refs.add(int(match.group(1)))
    return refs


def _header_int(fields: dict, key: str) -> int:
    return as_int(fields.get(key), 0)


def _rows_from_cursor(rows: list) -> dict:
    by_tg = {}
    by_id = {}
    for row in rows:
        rid = as_int(row["id"], 0)
        tg = as_int(row["tg_message_id"], 0)
        if rid:
            by_id[rid] = rid
        if tg:
            by_tg[tg] = rid
    return {"by_tg": by_tg, "by_id": by_id}


async def _history_window_rows(db, chat_id: int, ts_from: int,
                                ts_to: int) -> list:
    return await fetch_rows(
        db,
        "SELECT id, timestamp, tg_message_id, user_id FROM smart_messages "
        "WHERE chat_id = ? AND timestamp >= ? AND timestamp <= ? "
        "ORDER BY timestamp ASC, id ASC",
        (int(chat_id), int(ts_from), int(ts_to)))


async def _last_rows(db, chat_id: int, as_of: int, limit: int) -> list:
    rows = await fetch_rows(
        db,
        "SELECT id, timestamp, tg_message_id, user_id FROM smart_messages "
        "WHERE chat_id = ? AND timestamp <= ? "
        "ORDER BY timestamp DESC, id DESC LIMIT ?",
        (int(chat_id), int(as_of), int(limit)))
    return list(reversed(rows))


def _tool_context(tr, chat_id: int, query: str, as_of: int):
    try:
        return tr.ToolContext(chat_id, query, turn_as_of=as_of)
    except TypeError:
        return tr.ToolContext(chat_id, query)


async def _dispatch_pages(router, ctx, arguments: dict, *,
                          max_pages: int = 80) -> tuple:
    out = await router.dispatch("get_recent_history", dict(arguments), ctx)
    pages = 1
    texts = [out]
    product = {"tool_router": sys.modules.get("services.tool_router")}
    fields = parse_header(out, product)
    while pages < max_pages and _header_int(fields, "has_next") == 1:
        cursor = str(fields.get("cursor") or "")
        if not cursor:
            break
        out = await router.dispatch("get_recent_history", {"cursor": cursor},
                                    ctx)
        texts.append(out)
        pages += 1
        fields = parse_header(out, product)
    return texts, pages, fields


async def history_scenario(product, db, chat_id: int, as_of: int, tz: str,
                           case: dict) -> dict:
    tr = product["tool_router"]
    router = tr.ToolRouter(tr.ToolDeps(search=SimpleNamespace(),
                                       memory=SimpleNamespace(),
                                       aliases=None, db=db))
    empty_metrics = {
        "required_fact_recall": na("not_applicable"),
        "relevance": na("not_applicable"),
        "episode_completeness": na("history_battery_counts_rows_not_episodes"),
        "temporal_correctness": na("not_applicable"),
        "participant_attribution": na("not_applicable"),
        "source_proof": na("not_applicable"),
        "latency_cost": {"elapsed_ms": 0, "pages": 0, "payload_chars": 0,
                         "retrieve_calls": 0, "embed_calls": 0,
                         "generate_calls": 0},
    }
    if case["kind"] == "gap":
        return {"status": "not_applicable",
                "reason": "ingestion_gap_not_exposed_by_readonly_snapshot",
                "metrics": empty_metrics, "checks": {}}
    if case["kind"] == "error":
        class FailingDb:
            db = None
            def __init__(self):
                self.db = self
            async def execute(self, *_a, **_k):
                raise sqlite3.OperationalError("fixture tool error")
            async def get_recent_messages(self, *_a, **_k):
                raise sqlite3.OperationalError("fixture tool error")

        ctx = _tool_context(tr, chat_id, case["query"], as_of)
        failing_router = tr.ToolRouter(tr.ToolDeps(
            search=SimpleNamespace(), memory=SimpleNamespace(),
            aliases=None, db=FailingDb()))
        try:
            out = await failing_router.dispatch("get_recent_history", {}, ctx)
            named = "ОШИБКА" in str(out) or "error" in str(out).lower()
        except Exception:
            named = True
        return {"status": "pass" if named else "fail",
                "reason": "" if named else "tool_error_not_named",
                "metrics": dict(empty_metrics), "checks": {
                    "error_named": bool(named)}}
    if case["kind"] == "empty":
        ts_from = int(as_of) + 3600
        ts_to = int(as_of) + 7200
        expected = []
        mode = "range"
    elif case["kind"] == "depth":
        rows = await _last_rows(db, chat_id, as_of, int(case["n"]))
        expected = rows
        mode = "depth"
    else:
        if case.get("rows"):
            rows = await _last_rows(db, chat_id, as_of, int(case["rows"]))
            if not rows:
                return {"status": "not_executed",
                        "reason": "snapshot_no_rows_for_case",
                        "metrics": empty_metrics, "checks": {}}
            ts_from = as_int(rows[0]["timestamp"])
            ts_to = as_int(rows[-1]["timestamp"])
        else:
            seconds = int(case.get("seconds") or 3600)
            ts_from = int(as_of) - seconds
            ts_to = int(as_of)
        expected = await _history_window_rows(db, chat_id, ts_from, ts_to)
        mode = "range"
        if not expected and not case.get("empty"):
            return {"status": "not_executed",
                    "reason": "snapshot_no_rows_in_window",
                    "metrics": empty_metrics, "checks": {}}
    if case.get("rows") and not expected:
        return {"status": "not_executed", "reason": "snapshot_no_rows_for_case",
                "metrics": empty_metrics, "checks": {}}
    if mode == "depth":
        ts_from = as_int(expected[0]["timestamp"]) if expected else int(as_of)
        ts_to = as_int(expected[-1]["timestamp"]) if expected else int(as_of)
    expected_ids = {as_int(row["id"]) for row in expected}
    expected_uids = {as_int(row["user_id"]) for row in expected
                     if as_int(row["user_id"], 0)}
    row_map = _rows_from_cursor(expected)
    source = {"by_tg": dict(row_map["by_tg"]),
              "by_id": dict(row_map["by_id"])}

    variant = str(case.get("variant") or "candidate")
    arguments = {}
    ctx = _tool_context(tr, chat_id, case["query"], as_of)
    range_capture = None
    if mode == "range" and variant == "candidate" \
            and hasattr(tr, "capture_history_range"):
        try:
            range_capture = await tr.capture_history_range(
                db, chat_id, ts_from, ts_to, as_of=as_of)
            if range_capture is not None:
                ctx.history_sample = range_capture
        except Exception as exc:
            return {"status": "fail", "reason": reason_of(exc),
                    "metrics": empty_metrics, "checks": {}}
    elif mode == "range":
        # Baseline best effort: same user query, explicit depth covering the
        # stored window.  The period contract itself does not exist there.
        arguments = {"depth": max(1, min(len(expected), 2000))}
    elif mode == "depth":
        arguments = {"depth": int(case["n"])}

    started = time.perf_counter()
    try:
        texts, pages, fields = await _dispatch_pages(router, ctx, arguments)
    except Exception as exc:
        return {"status": "fail", "reason": reason_of(exc),
                "metrics": empty_metrics, "checks": {}}
    elapsed = int((time.perf_counter() - started) * 1000)
    out = "\n".join(texts)
    delivered_refs = set()
    for text in texts:
        delivered_refs |= body_refs(text)
    delivered_ids = set()
    for ref in delivered_refs:
        if ref in source["by_tg"]:
            delivered_ids.add(source["by_tg"][ref])
        elif ref in source["by_id"]:
            delivered_ids.add(source["by_id"][ref])
    delivered_in_expected = delivered_ids & expected_ids
    if case["kind"] == "empty" and not expected_ids:
        recall = part(1, 1, basis="empty_range_no_rows")
        relevance = part(1, 1, basis="empty_range_no_rows")
        source_proof = part(1, 1, basis="empty_range_no_refs")
    else:
        denom = len(expected_ids) if mode == "range" else min(
            int(case["n"]), len(expected_ids))
        recall = part(len(delivered_in_expected), denom)
        relevance = part(len(delivered_in_expected),
                         max(1, len(delivered_ids)))
        source_proof = part(len(delivered_ids & (
            set(source["by_tg"].values()) | set(source["by_id"].values()))),
            max(1, len(delivered_ids)))
    uid_lines = len({uid for uid in expected_uids
                     if re.search(r"\[%d\]" % uid, out)})
    participant = part(uid_lines, max(1, len(expected_uids))) \
        if expected_uids else na("no_participants_in_case")
    range_contract = (str(fields.get("window_kind") or "") == "time_range"
                      and _header_int(fields, "window_from") == int(ts_from)
                      and _header_int(fields, "window_to") == int(ts_to)
                      and _header_int(fields, "as_of") == int(as_of))
    temporal = part(
        sum(1 for value, expected_value in (
            (_header_int(fields, "window_from"), int(ts_from)),
            (_header_int(fields, "window_to"), int(ts_to)),
            (_header_int(fields, "as_of"), int(as_of)),
        ) if value == expected_value),
        3)
    no_gap = (_header_int(fields, "has_next") == 0)
    incomplete = _header_int(fields, "incomplete")
    reason = str(fields.get("reason") or "")
    anchor_ok = not (incomplete and not reason)
    empty_ok = case["kind"] != "empty" or (
        _header_int(fields, "available") == 0
        and str(fields.get("status") or "") in ("empty_window", "ok"))
    require_range = mode == "range" and case.get("require_range", True)
    checks = {
        "range_contract": range_contract if require_range else True,
        "recall_complete": (recall["value"] == 1.0
                            if recall["value"] is not None else False),
        "no_silent_gap": bool(no_gap and anchor_ok),
        "source_proof": source_proof["value"] == 1.0,
        "relevance": relevance["value"] == 1.0,
        "empty_honest": bool(empty_ok),
    }
    status = "pass" if all(checks.values()) else "fail"
    if status == "fail":
        reason_out = ("range_contract_absent" if require_range
                      and not range_contract else
                      "coverage_incomplete" if not checks["recall_complete"]
                      else "silent_gap" if not checks["no_silent_gap"]
                      else "source_proof_failed")
    else:
        reason_out = ""
    metrics = {
        "required_fact_recall": recall,
        "relevance": relevance,
        "episode_completeness": na("history_battery_counts_rows_not_episodes"),
        "temporal_correctness": temporal if require_range else na(
            "count_mode_has_no_period_contract"),
        "participant_attribution": participant,
        "source_proof": source_proof,
        "latency_cost": {
            "elapsed_ms": elapsed, "pages": pages,
            "payload_chars": len(out), "retrieve_calls": pages,
            "embed_calls": 0, "generate_calls": 0},
    }
    return {"status": status, "reason": reason_out, "metrics": metrics,
            "checks": checks, "driver": (
                "range_bound_page" if mode == "range" and variant == "candidate"
                else "count_page"), "window": {
                "from": ts_from, "to": ts_to, "expected_rows": len(expected)},
            "source_ids": sorted(delivered_ids)[:100],
            "source_id_count": len(delivered_ids),
            "expected_ids_sha256": sha256_text(
                ",".join(str(value) for value in sorted(expected_ids)))}


# ── time battery ────────────────────────────────────────────────────────────

def _time_metrics(checks: dict, *, elapsed_ms: int = 0, anchors: int = 0,
                  found: int = 0, episode: bool = False) -> dict:
    values = list(checks.values())
    return {
        "required_fact_recall": part(found, max(1, anchors)) if anchors
        else na("no_anchor_contract"),
        "relevance": part(sum(values), max(1, len(values))),
        "episode_completeness": (part(sum(values), len(values)) if episode
                                 else na("not_an_episode_case")),
        "temporal_correctness": part(sum(values), max(1, len(values))),
        "participant_attribution": part(1, 1) if checks else na("not_applicable"),
        "source_proof": part(sum(values), max(1, len(values))),
        "latency_cost": {"elapsed_ms": elapsed_ms, "pages": 0,
                         "payload_chars": 0, "retrieve_calls": 0,
                         "embed_calls": 0, "generate_calls": 0},
    }


def _time_result(case_id: str, checks: dict, *, reason: str = "",
                 anchors: int = 0, found: int = 0, episode: bool = False,
                 metrics_extra: dict | None = None) -> dict:
    metrics = _time_metrics(checks, anchors=anchors, found=found,
                            episode=episode)
    if metrics_extra:
        metrics.update(metrics_extra)
    ok = bool(checks) and all(checks.values())
    return {"status": "pass" if ok else "fail",
            "reason": "" if ok else (reason or "temporal_contract_failed"),
            "metrics": metrics, "checks": checks}


async def time_scenario(product, db, chat_id: int, as_of: int, tz: str,
                        case_id: str) -> dict:
    tr = product["tool_router"]
    cc = product["canonical"]
    rc = product["retrieval"]
    try:
        if case_id in ("TIME-HOUR-AGO", "TIME-MINUTE-AGO"):
            phrase = "час назад" if case_id.endswith("HOUR-AGO") else \
                "минуту назад"
            seconds = 3600 if case_id.endswith("HOUR-AGO") else 60
            if not hasattr(tr, "extract_history_window"):
                return _time_result(case_id, {"capability": False},
                                    reason="capability_absent")
            spec = tr.extract_history_window(phrase)
            resolved = tr.resolve_history_window_at(
                spec, as_of=as_of, timezone=tz) if spec is not None else {}
            checks = {
                "phrase_resolved": bool(
                    spec is not None and getattr(spec, "kind", "") == "duration"
                    and getattr(spec, "amount", 0) == 1
                    and getattr(spec, "unit", "") in (
                        "hours" if seconds == 3600 else "minutes",)),
                "ends_at_as_of": as_int(resolved.get("to"), 0) == as_of,
                "exact_interval": (as_int(resolved.get("to"), 0)
                                   - as_int(resolved.get("from"), 0)
                                   == seconds),
            }
            return _time_result(case_id, checks,
                                reason="relative_phrase_unresolved",
                                anchors=3, found=sum(checks.values()))
        if case_id == "TIME-LAST-SECONDS":
            from services.runtime_probes import parse_time_window
            results = {}
            for seconds in (3600, 60):
                window, error = parse_time_window(
                    {"last_seconds": seconds}, now=as_of)
                results[seconds] = (window is not None and not error
                                    and int(window[1]) == int(as_of)
                                    and int(window[1]) - int(window[0])
                                    == seconds)
            checks = {
                "hour_last_seconds_exact": results.get(3600, False),
                "minute_last_seconds_exact": results.get(60, False),
            }
            return _time_result(case_id, checks,
                                reason="last_seconds_interval_mismatch",
                                anchors=2, found=sum(checks.values()))
        if case_id == "TIME-LOCAL-MIDNIGHT":
            if not hasattr(tr, "extract_history_window"):
                return _time_result(case_id, {"capability": False},
                                    reason="capability_absent")
            spec = tr.extract_history_window("вчера")
            resolved = tr.resolve_history_window_at(
                spec, as_of=as_of, timezone=tz)
            local = datetime.datetime.fromtimestamp(
                as_of, zoneinfo.ZoneInfo(tz))
            day = local.date() - datetime.timedelta(days=1)
            start = datetime.datetime.combine(
                day, datetime.time(0, 0), tzinfo=zoneinfo.ZoneInfo(tz))
            end = datetime.datetime.combine(
                local.date(), datetime.time(0, 0),
                tzinfo=zoneinfo.ZoneInfo(tz)) - datetime.timedelta(seconds=1)
            checks = {
                "from_local_midnight": as_int(resolved.get("from"), 0)
                == int(start.timestamp()),
                "to_before_today": as_int(resolved.get("to"), 0)
                == int(end.timestamp()),
                "uses_chat_zone": as_int(resolved.get("from"), 0)
                < as_of < 2 ** 40,
            }
            return _time_result(case_id, checks,
                                reason="local_midnight_mismatch",
                                anchors=3, found=sum(checks.values()))
        if case_id == "TIME-UTC-CHAT":
            ts = 1704067200
            local = cc.format_chat_time(ts, tz)
            utc = cc.format_utc_timestamp(ts)
            checks = {
                "utc_label": "UTC" in utc,
                "local_time_rendered": bool(re.search(
                    r"\d{2}\.\d{2}\.\d{4}, \d{2}:\d{2}", local)),
                "distinct_scales": local != utc,
            }
            return _time_result(case_id, checks, reason="time_scale_missing",
                                anchors=3, found=sum(checks.values()))
        if case_id == "TIME-DST":
            winter = cc.format_chat_time(1704067200, "Europe/Berlin")
            summer = cc.format_chat_time(1721044800, "Europe/Berlin")
            checks = {
                "winter_local_hour": "01:00" in winter,
                "summer_local_hour": "14:00" in summer,
                "different_offsets": winter != summer,
            }
            return _time_result(case_id, checks, reason="dst_offset_missing",
                                anchors=3, found=sum(checks.values()))
        if case_id == "TIME-SAME-TS":
            router = tr.ToolRouter(tr.ToolDeps(
                search=SimpleNamespace(), memory=SimpleNamespace(),
                aliases=None, db=db))
            duplicate = await fetch_rows(
                db,
                "SELECT timestamp FROM smart_messages WHERE chat_id = ? "
                "GROUP BY timestamp HAVING COUNT(*) >= 2 "
                "ORDER BY timestamp DESC LIMIT 1", (int(chat_id),))
            if not duplicate:
                return {"status": "not_executed",
                        "reason": "snapshot_no_duplicate_timestamp",
                        "metrics": _time_metrics({}), "checks": {}}
            same_ts = as_int(duplicate[0]["timestamp"])
            rows = await fetch_rows(
                db,
                "SELECT id, tg_message_id, timestamp, user_id, text, "
                "media_type, author_name FROM smart_messages "
                "WHERE chat_id = ? AND timestamp = ? ORDER BY id ASC",
                (int(chat_id), same_ts))
            lines = router._history_lines(rows, with_user_id=True)
            joined = "\n".join(lines)
            checks = {
                "both_message_ids": all(
                    f"tg:{as_int(row['tg_message_id'])}" in joined
                    for row in rows),
                "same_timestamp_repeated": len(rows) >= 2,
                "utc_labels": "UTC" in joined,
            }
            return _time_result(case_id, checks,
                                reason="same_timestamp_collapsed",
                                anchors=len(rows) or 1,
                                found=sum(checks.values()))
        if case_id == "TIME-EDIT":
            router = tr.ToolRouter(tr.ToolDeps(
                search=SimpleNamespace(), memory=SimpleNamespace(),
                aliases=None, db=db))
            rows = await fetch_rows(
                db,
                "SELECT id, tg_message_id, timestamp, user_id, text, "
                "media_type, author_name, edited_at FROM smart_messages "
                "WHERE chat_id = ? AND edited_at IS NOT NULL AND edited_at > 0 "
                "ORDER BY timestamp DESC LIMIT 1", (int(chat_id),))
            if not rows:
                return {"status": "not_executed",
                        "reason": "snapshot_no_edited_row",
                        "metrics": _time_metrics({}), "checks": {}}
            line = "\n".join(router._history_lines(rows, with_user_id=False))
            checks = {"edited_segment": "ред." in line,
                      "edit_is_utc": "UTC" in line}
            return _time_result(case_id, checks,
                                reason="edit_segment_missing", anchors=2,
                                found=sum(checks.values()))
        if case_id == "TIME-FORWARD":
            router = tr.ToolRouter(tr.ToolDeps(
                search=SimpleNamespace(), memory=SimpleNamespace(),
                aliases=None, db=db))
            rows = await fetch_rows(
                db,
                "SELECT id, tg_message_id, timestamp, user_id, text, "
                "media_type, author_name, is_forward, forward_source "
                "FROM smart_messages WHERE chat_id = ? AND is_forward = 1 "
                "ORDER BY timestamp DESC LIMIT 1", (int(chat_id),))
            if not rows:
                return {"status": "not_executed",
                        "reason": "snapshot_no_forward_row",
                        "metrics": _time_metrics({}), "checks": {}}
            line = "\n".join(router._history_lines(rows, with_user_id=False))
            checks = {"forward_segment": "Переслано" in line}
            return _time_result(case_id, checks,
                                reason="forward_segment_missing", anchors=1,
                                found=sum(checks.values()))
        if case_id == "TIME-CURRENT-VS-FACT":
            current = cc.format_context_item(
                ts=as_of, author="A", item_id="tg:1", text="t", kind="msg")
            old = cc.format_context_item(
                ts=as_of - 30 * 86400, author="A", item_id="fact:1",
                text="f", kind=cc.KIND_FACT)
            checks = {
                "current_has_hours": bool(re.search(
                    r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2} UTC", current)),
                "fact_month_only": bool(re.search(r"\[\d{2}\.\d{4}", old)),
                "fact_has_no_hours": not bool(re.search(
                    r"\d{2}:\d{2}", old)),
                "dates_differ": current.split("]", 1)[0] != old.split("]", 1)[0],
            }
            return _time_result(case_id, checks,
                                reason="current_and_fact_mixed", anchors=4,
                                found=sum(checks.values()))
        if case_id == "TIME-FACT-EPISODE":
            if not hasattr(rc, "_fact_candidate") \
                    or not hasattr(rc, "_episode_candidate"):
                return _time_result(case_id, {"capability": False},
                                    reason="capability_absent")
            fact = rc._fact_candidate({
                "id": 5, "chat_id": chat_id, "fact": "f",
                "message_timestamp": 1704067200, "created_at": 1704067300,
                "rag_ts": 1704067200, "target_user": 7,
                "speaker_author_id": 8, "subject_ref_id": 0}, "graph", 1,
                cc.resolve_item_id)
            episode = rc._episode_candidate({
                "id": 3, "event_start_ts": 1704067200,
                "event_end_ts": 1704067300, "created_at": 1704067400,
                "discovered_at": 1704067400, "last_ts": 1704067300},
                chat_id, 1)
            checks = {
                "fact_time_kind_source": fact.time_kind == "source",
                "fact_recorded_distinct": fact.recorded_at == 1704067300,
                "episode_time_kind_event": episode.time_kind == "event",
                "episode_event_start": episode.event_start == 1704067200,
                "episode_recorded_distinct": episode.recorded_at == 1704067400,
            }
            return _time_result(case_id, checks,
                                reason="fact_episode_time_mixed", anchors=5,
                                found=sum(checks.values()), episode=True)
        if case_id == "TIME-MONTH-ONLY":
            if not hasattr(rc, "_fact_candidate"):
                return _time_result(case_id, {"capability": False},
                                    reason="capability_absent")
            recorded = rc._fact_candidate({
                "id": 6, "chat_id": chat_id, "fact": "f", "created_at":
                1704067300, "rag_ts": 0, "target_user": 7}, "graph", 1,
                cc.resolve_item_id)
            unknown = rc._fact_candidate({
                "id": 7, "chat_id": chat_id, "fact": "f", "rag_ts": 0,
                "target_user": 7}, "graph", 1, cc.resolve_item_id)
            line = cc.format_context_item(
                ts=1704067300, author="A", item_id="fact:6", text="f",
                kind=cc.KIND_FACT, time_origin="recorded")
            checks = {
                "created_at_is_recorded": recorded.time_kind == "recorded",
                "missing_time_is_unknown": unknown.time_kind == "unknown",
                "no_invented_hours": not bool(re.search(r"\d{2}:\d{2}", line)),
                "recorded_label_present": "дата записи" in line,
            }
            return _time_result(case_id, checks,
                                reason="month_only_invented_hours", anchors=4,
                                found=sum(checks.values()))
        if case_id == "TIME-UNKNOWN":
            if not hasattr(rc, "_message_candidate"):
                return _time_result(case_id, {"capability": False},
                                    reason="capability_absent")
            cand = rc._message_candidate({
                "id": 1, "tg_message_id": 12, "chat_id": chat_id,
                "text": "x", "user_id": 7}, "fts", 1, cc.resolve_item_id)
            checks = {"time_kind_unknown": cand.time_kind == "unknown",
                      "no_invented_sent_at": cand.sent_at == 0}
            return _time_result(case_id, checks,
                                reason="unknown_time_fabricated", anchors=2,
                                found=sum(checks.values()))
    except Exception as exc:
        return {"status": "fail", "reason": reason_of(exc),
                "metrics": _time_metrics({}), "checks": {}}
    return {"status": "not_executed", "reason": "scenario_not_implemented",
            "metrics": _time_metrics({}), "checks": {}}


# ── channels battery ────────────────────────────────────────────────────────

def _field_metrics(fields: dict) -> dict:
    return {
        "required_fact_recall": part(sum(fields.values()), len(fields)),
        "relevance": part(1, 1),
        "episode_completeness": na("not_an_episode_case"),
        "temporal_correctness": part(sum(fields.values()), len(fields)),
        "participant_attribution": part(1, 1),
        "source_proof": part(sum(fields.values()), len(fields)),
        "latency_cost": {"elapsed_ms": 0, "pages": 0, "payload_chars": 0,
                         "retrieve_calls": 0, "embed_calls": 0,
                         "generate_calls": 0},
    }


def _channel_result(case_id: str, fields: dict, *, reason: str = "",
                    episode: bool = False,
                    extra_metrics: dict | None = None) -> dict:
    ok = bool(fields) and all(fields.values())
    metrics = _field_metrics(fields)
    if episode:
        metrics["episode_completeness"] = part(
            sum(fields.values()), len(fields))
    if extra_metrics:
        metrics.update(extra_metrics)
    return {"status": "pass" if ok else "fail",
            "reason": "" if ok else (reason or "channel_metadata_lost"),
            "metrics": metrics, "checks": fields}


async def channels_scenario(product, db, chat_id: int, as_of: int, tz: str,
                            case_id: str) -> dict:
    cc = product["canonical"]
    rc = product["retrieval"]
    sm = product["summary"]
    tr = product["tool_router"]
    try:
        if case_id == "CH-FTS":
            if not hasattr(rc, "_message_candidate"):
                return _channel_result(case_id, {"capability": False},
                                       reason="capability_absent")
            cand = rc._message_candidate({
                "id": 1, "tg_message_id": 12, "chat_id": chat_id,
                "timestamp": 1704067200, "sent_at": 1704067200,
                "ingested_at": 1704067300, "user_id": 7, "text": "x"},
                "fts", 1, cc.resolve_item_id)
            line = cc.format_context_item(
                ts=cand.sent_at, author="A", item_id=cand.id, text="t")
            fields = {
                "time_kind_source": getattr(cand, "time_kind", "") == "source",
                "recorded_at": getattr(cand, "recorded_at", 0) == 1704067300,
                "utc_canonical": "UTC" in line,
            }
            return _channel_result(case_id, fields)
        if case_id == "CH-VECTOR":
            if not hasattr(rc, "_fact_meta_candidate"):
                return _channel_result(case_id, {"capability": False},
                                       reason="capability_absent")
            cand = rc._fact_meta_candidate({
                "fact": "v", "tg_message_id": 12, "time_origin": "recorded",
                "created_at": 1704067300, "message_timestamp": 1704067200,
                "subject": "s", "speaker": "x", "fact_id": 6}, 1,
                cc.resolve_item_id)
            fields = {
                "time_kind_recorded": getattr(cand, "time_kind", "")
                == "recorded",
                "recorded_at": getattr(cand, "recorded_at", 0) == 1704067300,
            }
            return _channel_result(case_id, fields)
        if case_id == "CH-GRAPH":
            if not hasattr(rc, "_fact_candidate"):
                return _channel_result(case_id, {"capability": False},
                                       reason="capability_absent")
            cand = rc._fact_candidate({
                "id": 5, "chat_id": chat_id, "fact": "f",
                "message_timestamp": 1704067200, "created_at": 1704067300,
                "rag_ts": 1704067200, "target_user": 7,
                "speaker_author_id": 8, "subject_ref_id": 0}, "graph", 1,
                cc.resolve_item_id)
            fields = {
                "source_kind": getattr(cand, "time_kind", "") == "source",
                "recorded_distinct": getattr(cand, "recorded_at", 0)
                == 1704067300,
                "sent_at_source": cand.sent_at == 1704067200,
            }
            return _channel_result(case_id, fields)
        if case_id == "CH-EPISODE":
            if not hasattr(rc, "_episode_candidate"):
                return _channel_result(case_id, {"capability": False},
                                       reason="capability_absent")
            cand = rc._episode_candidate({
                "id": 3, "event_start_ts": 1704067200,
                "event_end_ts": 1704067300, "created_at": 1704067400,
                "discovered_at": 1704067400, "last_ts": 1704067300},
                chat_id, 1)
            fields = {
                "event_kind": getattr(cand, "time_kind", "") == "event",
                "event_start": getattr(cand, "event_start", 0) == 1704067200,
                "recorded_distinct": getattr(cand, "recorded_at", 0)
                == 1704067400,
            }
            return _channel_result(case_id, fields, episode=True)
        if case_id == "CH-ARCHIVE":
            line = cc.format_context_item(
                ts=1704067200, author="A", item_id="archive:1", text="a",
                kind=cc.KIND_ARCHIVE)
            fields = {"month_only": bool(re.search(r"\d{2}\.\d{4}", line)),
                      "no_invented_hours": not bool(
                          re.search(r"\d{2}:\d{2}", line))}
            return _channel_result(case_id, fields)
        if case_id == "CH-RECENT":
            router = tr.ToolRouter(tr.ToolDeps(
                search=SimpleNamespace(), memory=SimpleNamespace(),
                aliases=None, db=db))
            rows = await fetch_rows(
                db,
                "SELECT id, tg_message_id, timestamp, user_id, text, "
                "media_type, author_name FROM smart_messages "
                "WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 1",
                (int(chat_id),))
            if not rows:
                return {"status": "not_executed",
                        "reason": "snapshot_no_rows", "checks": {},
                        "metrics": _field_metrics({})}
            line = "\n".join(router._history_lines(rows, with_user_id=True))
            fields = {"utc": "UTC" in line, "identity": "tg:" in line,
                      "author_uid": "[" + str(as_int(rows[0]["user_id"]))
                      + "]" in line}
            return _channel_result(case_id, fields)
        if case_id == "CH-SUMMARY":
            if not hasattr(sm, "_format_origin_labeled_line"):
                return _channel_result(case_id, {"capability": False},
                                       reason="capability_absent")
            line = sm._format_origin_labeled_line((
                "chat_history", "f", 1704067200, "A", "fact:5", None, None,
                "recorded"))
            fields = {"recorded_label": "дата записи" in line,
                      "month_first": bool(re.search(r"\[\d{2}\.\d{4}", line)),
                      "no_invented_hours": not bool(
                          re.search(r"\d{2}:\d{2}", line))}
            return _channel_result(case_id, fields)
        if case_id == "CH-STORAGE-WRITER":
            router = tr.ToolRouter(tr.ToolDeps(
                search=SimpleNamespace(), memory=SimpleNamespace(),
                aliases=None, db=db))
            rows = await fetch_rows(
                db,
                "SELECT id, tg_message_id, timestamp, user_id, text, "
                "media_type, author_name, reply_to_id, reply_to_author_id, "
                "edited_at, is_forward, forward_source FROM smart_messages "
                "WHERE chat_id = ? AND (reply_to_id IS NOT NULL OR "
                "edited_at IS NOT NULL) ORDER BY timestamp DESC LIMIT 1",
                (int(chat_id),))
            if not rows:
                return {"status": "not_executed",
                        "reason": "snapshot_no_storage_row_with_metadata",
                        "checks": {}, "metrics": _field_metrics({})}
            line = "\n".join(router._history_lines(rows, with_user_id=True))
            row = rows[0]
            if not line:
                return {"status": "not_executed",
                        "reason": "canonical_line_empty",
                        "checks": {}, "metrics": _field_metrics({})}
            try:
                from services.summary_aliases import AliasResolver
                dcs = product["direct_chat"]
                capture = CaptureLLM()
                service = dcs.DirectChatService(
                    capture, db, capture, AliasResolver("{}"),
                    tool_router=None)
                await service._l2_write_answer(
                    chat_id, "что было в этом сообщении",
                    temperature=0.5,
                    user_blocks=["<Global_Context>\n" + line
                                 + "\n</Global_Context>"],
                    max_tokens=400)
                writer_text = "\n".join(
                    str(item.get("content") or "")
                    for item in (capture.messages or ()))
            except Exception as exc:
                return {"status": "fail",
                        "reason": "writer_payload_failed:"
                        + type(exc).__name__,
                        "checks": {}, "metrics": _field_metrics({})}
            if not writer_text:
                return {"status": "not_executed",
                        "reason": "writer_payload_not_captured",
                        "checks": {}, "metrics": _field_metrics({})}
            fields = {"utc": "UTC" in writer_text}
            if as_int(row["reply_to_id"], 0) or as_int(
                    row["reply_to_author_id"], 0):
                fields["reply_segment"] = "ответ на" in writer_text
            if as_int(row["edited_at"], 0):
                fields["edit_segment"] = "ред." in writer_text
            if as_int(row["is_forward"], 0):
                fields["forward_segment"] = "Переслано" in writer_text
            return _channel_result(case_id, fields,
                                   reason="storage_to_writer_metadata_lost",
                                   ) | {
                "source_ids": [as_int(row["id"])],
                "source_id_count": 1,
                "expected_ids_sha256": sha256_text(str(as_int(row["id"]))),
                "payload_stage": "l2_writer_messages",
                "writer_message_count": len(capture.messages or ()),
                "writer_payload_sha256": sha256_text(json.dumps(
                    capture.messages, ensure_ascii=False, sort_keys=True)),
                "writer_payload_chars": len(writer_text),
            }
    except Exception as exc:
        return {"status": "fail", "reason": reason_of(exc),
                "metrics": _field_metrics({}), "checks": {}}
    return {"status": "not_executed", "reason": "scenario_not_implemented",
            "metrics": _field_metrics({}), "checks": {}}


# ── telegram battery ────────────────────────────────────────────────────────

class FakeBot:
    def __init__(self, fail_calls=()) -> None:
        self.calls = []
        self.fail_calls = set(int(call) for call in fail_calls)
        self._message_id = 1000

    async def send_message(self, chat_id, text, **kwargs):
        number = len(self.calls) + 1
        self.calls.append({"n": number, "text": str(text),
                           "kwargs": {key: value for key, value in kwargs.items()
                                      if key != "sent_ids"}})
        if number in self.fail_calls:
            from aiogram.exceptions import TelegramBadRequest
            raise TelegramBadRequest(method=None, message="fixture rejected")
        self._message_id += 1
        return SimpleNamespace(message_id=self._message_id)


class CaptureLLM:
    """Deterministic LLM that records the final Writer messages payload."""

    def __init__(self) -> None:
        self.messages = []
        self.calls = 0

    async def generate(self, messages, **_kwargs):
        self.messages = list(messages or ())
        self.calls += 1
        return "ok"

    async def generate_with_metadata(self, messages, **_kwargs):
        self.messages = list(messages or ())
        self.calls += 1
        return SimpleNamespace(text="ok", model="capture-stub", usage={},
                               finish_reason="stop", attempt=1)


def _payload_summary(calls: list) -> list:
    out = []
    for call in calls:
        text = call["text"]
        parse_mode = call["kwargs"].get("parse_mode")
        open_tags = len(re.findall(
            r"</?(?:b|i|u|s|code|pre|blockquote|a)\b[^>]*>", text))
        out.append({
            "n": call["n"],
            "parse_mode": parse_mode,
            "text_sha256": sha256_text(text),
            "text_len": len(text),
            "utf16": len(text.encode("utf-16-le")) // 2,
            "tags": open_tags,
            "raw_stars": text.count("**"),
            "raw_backslash_star": text.count("\\*"),
            "has_link": "<a href=" in text,
            "has_raw_html": bool(re.search(r"<script|<b>|<i>", text)),
            "reply_to": call["kwargs"].get("reply_to_message_id"),
        })
    return out


def _tag_balanced(text: str) -> bool:
    stack = []
    for match in re.finditer(r"</?([a-zA-Z][a-zA-Z0-9-]*)[^>]*>", text):
        raw = match.group(0)
        name = match.group(1).lower()
        if name not in ("b", "i", "u", "s", "code", "pre", "blockquote", "a"):
            continue
        if raw.startswith("</"):
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        elif not raw.rstrip().endswith("/>"):
            stack.append(name)
    return not stack


async def telegram_scenario(product, case_id: str, chat_id: int) -> dict:
    dcs = product["direct_chat"]
    if not module_ok(product, "direct_chat"):
        return {"status": "not_executed", "reason": "direct_chat_unavailable",
                "metrics": _telegram_metrics({}), "checks": {}}
    texts = {
        "TG-SHORT": "Привет, как дела?",
        "TG-MARKDOWN": ("**Итог:** всё *хорошо*.\n\n- пункт 1\n- пункт 2\n"
                        "> цитата\n\n```py\nprint('x')\n```"),
        "TG-LITERAL": r"2 * 2 = 4; \*не жирный\*; snake_case",
        "TG-HTML-LINK": ("Смотри <b>не тег</b> & [сайт](https://example.com/"
                         "a?x=1&y=2) и <script>alert(1)</script>"),
        "TG-CHUNK": ("**Длинный разбор.**\n\n" + ("Абзац с **акцентом** и "
                     "текстом. " * 120)),
        "TG-PARTIAL": ("**Часть один.** " + ("текст " * 700) + "\n\n"
                       "**Часть два.** " + ("ещё текст " * 700)),
    }
    if case_id not in texts:
        return {"status": "not_executed", "reason": "scenario_not_implemented",
                "metrics": _telegram_metrics({}), "checks": {}}
    text = texts[case_id]
    fail_calls = (2,) if case_id == "TG-PARTIAL" else ()
    bot = FakeBot(fail_calls=fail_calls)
    started = time.perf_counter()
    error = ""
    sent_id = None
    try:
        sent_id = await dcs.DirectChatService._send_direct_answer(
            bot, chat_id, text, None)
    except Exception as exc:
        error = reason_of(exc)
    elapsed = int((time.perf_counter() - started) * 1000)
    summary = _payload_summary(bot.calls)
    joined = "\n".join(call["text"] for call in bot.calls)
    unsafe_html = bool(re.search(
        r"<(?:script|iframe|div|span|img|object|style)\b", joined, re.I))
    checks = {
        "delivered": bool(bot.calls),
        "no_duplicate_sha": len({entry["text_sha256"] for entry in summary})
        == len(summary) or case_id == "TG-PARTIAL",
        "no_raw_markers": ("**" not in joined and "\\*" not in joined),
        "no_unsafe_html": not unsafe_html,
        "tag_balanced": all(_tag_balanced(call["text"]) for call in bot.calls),
        "utf16_within_limit": all(entry["utf16"] <= 4096
                                  for entry in summary),
        "partial_recovered": (case_id != "TG-PARTIAL"
                              or (not error and len(bot.calls) >= 3
                                  and any(entry["parse_mode"] is None
                                          for entry in summary))),
    }
    if case_id in ("TG-SHORT", "TG-LITERAL"):
        checks["markup_not_used"] = all(
            entry["parse_mode"] is None for entry in summary)
        checks["literal_clean"] = "\\*" not in joined
    if case_id in ("TG-MARKDOWN", "TG-HTML-LINK", "TG-CHUNK",
                   "TG-PARTIAL"):
        checks["markup_used"] = any(
            entry["parse_mode"] == "HTML" for entry in summary)
    if case_id == "TG-HTML-LINK":
        checks["link_preserved"] = "href=" in joined
        checks["html_escaped"] = "&lt;b&gt;" in joined or "&lt;script" in joined
    if case_id == "TG-CHUNK":
        checks["multiple_chunks"] = len(bot.calls) > 1
        checks["content_not_lost"] = bool(
            "Длинный разбор" in joined and "акцентом" in joined)
    if case_id == "TG-PARTIAL":
        html_calls = [entry for entry in summary
                      if entry["parse_mode"] == "HTML"]
        first_html_sha = html_calls[0]["text_sha256"] if html_calls else ""
        checks["first_chunk_not_resent"] = bool(
            first_html_sha and sum(1 for entry in summary if entry["text_sha256"]
                                   == first_html_sha) == 1)
        checks["plain_fallback_used"] = any(
            entry["parse_mode"] is None for entry in summary)
    ok = all(checks.values())
    return {
        "status": "pass" if ok else "fail",
        "reason": "" if ok else (error or "telegram_egress_contract_failed"),
        "metrics": _telegram_metrics(checks, elapsed=elapsed,
                                     payloads=summary, sent_id=sent_id),
        "checks": checks,
        "payload_summary": summary,
    }


def _telegram_metrics(checks: dict, *, elapsed: int = 0, payloads=(),
                      sent_id=None) -> dict:
    values = list(checks.values())
    return {
        "required_fact_recall": part(sum(values), max(1, len(values))),
        "relevance": part(1, 1) if checks else na("not_applicable"),
        "episode_completeness": na("not_an_episode_case"),
        "temporal_correctness": na("not_a_temporal_case"),
        "participant_attribution": na("not_an_attribution_case"),
        "source_proof": part(sum(values), max(1, len(values))),
        "latency_cost": {"elapsed_ms": elapsed, "pages": 0,
                         "payload_chars": sum(p["text_len"] for p in payloads),
                         "retrieve_calls": 0, "embed_calls": 0,
                         "generate_calls": 0,
                         "messages": len(payloads), "sent_id_present":
                         sent_id is not None},
    }


# ── free-speech / scope meta ────────────────────────────────────────────────

def scan_banned(text: str) -> list:
    return sorted({match.group(0).lower()
                   for match in BANNED_RE.finditer(str(text or ""))})


def _added_lines(code_root: str, base_sha: str) -> list:
    try:
        diff = git_out(code_root, "diff", "--unified=0", base_sha, "HEAD",
                       "--", "services", "config")
    except Exception:
        return []
    lines = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    return lines


def free_speech_scenario(product, code_root: str, variant: str) -> dict:
    if variant == "baseline":
        return {"status": "not_applicable",
                "reason": "baseline_has_no_candidate_diff",
                "metrics": _field_metrics({"meta": True}),
                "checks": {"meta": True, "factual_criterion": False},
                "factual_criterion": False, "meta": True}
    added = _added_lines(code_root, BASELINE_SHA)
    hits = []
    for line in added:
        if scan_banned(line):
            hits.append(sha256_text(line)[:12])
    checks = {
        "no_moralizing_or_neutrality_filter_added": not hits,
        "meta_only": True,
    }
    metrics = _field_metrics(checks)
    metrics["required_fact_recall"] = na("meta_not_a_factual_criterion")
    metrics["episode_completeness"] = na("not_an_episode_case")
    metrics["temporal_correctness"] = na("not_a_temporal_case")
    metrics["source_proof"] = na("meta_scan")
    ok = not hits
    return {"status": "pass" if ok else "fail",
            "reason": "" if ok else "banned_objectivity_filter_added",
            "metrics": metrics, "checks": checks,
            "added_lines_scanned": len(added),
            "banned_hits_sha256": hits,
            "factual_criterion": False,
            "meta": True}


def scope_meta_scenarios(code_root: str, variant: str) -> list:
    allowed = {
        "services/direct_chat_service.py", "services/direct_l1.py",
        "services/direct_execution.py", "services/tool_router.py",
        "services/tool_schemas.py", "services/prompt_style_blocks.py",
        "services/canonical_context.py", "services/mca_retrieval_context.py",
        "services/direct_context_composer.py", "services/summary_memory.py",
        "services/database.py", "services/thread_chain.py",
        "services/telegram_markup.py", "services/response_document.py",
    }
    try:
        changed = [line for line in git_out(
            code_root, "diff", "--name-only", BASELINE_SHA, "HEAD").splitlines()
            if line.strip()]
    except Exception:
        changed = []
    product_changed = [path for path in changed if path.startswith("services/")]
    out_of_scope = sorted(path for path in product_changed if path not in allowed)
    scope_checks = {
        "product_files_within_abc_scope": not out_of_scope,
        "no_second_engine_added": not any(
            re.search(r"(second|parallel)_(retrieval|summary|memory)", path)
            for path in changed),
    }
    scope_metrics = _field_metrics(scope_checks)
    scope = {"id": "META-SCOPE", "battery": "meta",
             "requirement_ids": ["HC-SCOPE-BOUNDS"],
             "status": "pass" if all(scope_checks.values()) else "fail",
             "reason": "" if all(scope_checks.values())
             else "product_scope_violation",
             "metrics": scope_metrics, "checks": scope_checks,
             "changed_product_files": len(product_changed),
             "out_of_scope": out_of_scope}
    try:
        inside = subprocess.run(
            ["git", "-C", code_root, "merge-base", "--is-ancestor",
             BASELINE_SHA, "HEAD"], capture_output=True).returncode == 0
    except Exception:
        inside = False
    seq_metrics = _field_metrics({"based_on_225": inside})
    seq = {"id": "META-SEQ", "battery": "meta",
           "requirement_ids": ["HC-SEQ-ADMISSION"],
           "status": "pass" if inside else "fail",
           "reason": "" if inside else "baseline_not_ancestor",
           "metrics": seq_metrics, "checks": {"based_on_225": inside}}
    proc = {"id": "META-PROC", "battery": "meta",
            "requirement_ids": ["HC-PROC-SCOPED"],
            "status": "not_applicable",
            "reason": "process_evidence_owned_by_reviewer",
            "metrics": _field_metrics({"meta": False}),
            "checks": {"meta": True}}
    reused = (
        "plans/features/p0-history-analysis",
        "plans/features/vmq-onto-01",
        "plans/features/unified-reply",
        "services/canonical_context.py",
        "services/direct_context_composer.py",
    )
    present = {path: (Path(code_root) / path).exists() for path in reused}
    compat_checks = {"reused_artifacts_present": all(present.values())}
    compat = {"id": "META-COMPAT", "battery": "meta",
              "requirement_ids": ["HC-COMPAT-REUSE"],
              "status": "pass" if all(compat_checks.values()) else "fail",
              "reason": "" if all(compat_checks.values())
              else "reused_artifact_missing",
              "metrics": _field_metrics(compat_checks),
              "checks": compat_checks,
              "missing": [path for path, ok in present.items() if not ok]}
    return [scope, seq, proc, compat]


# ── scenario registry / runner ──────────────────────────────────────────────

HISTORY_CASES = (
    {"id": "HIST-10H", "battery": "history", "kind": "range",
     "seconds": 10 * 3600, "query": "что было за последние 10 часов"},
    {"id": "HIST-24H", "battery": "history", "kind": "range",
     "seconds": 24 * 3600, "query": "что было за последние 24 часа"},
    {"id": "HIST-CUSTOM", "battery": "history", "kind": "range",
     "seconds": 6 * 3600, "query": "что было за этот период"},
    {"id": "HIST-400", "battery": "history", "kind": "depth", "n": 400,
     "query": "последние 400 сообщений"},
    {"id": "HIST-2000", "battery": "history", "kind": "depth", "n": 2000,
     "query": "последние 2000 сообщений"},
    {"id": "HIST-CROSSPAGE", "battery": "history", "kind": "rows", "rows": 90,
     "query": "одна длинная тема через границу страниц"},
    {"id": "HIST-LONGTOPIC", "battery": "history", "kind": "rows", "rows": 120,
     "query": "что говорил этот человек"},
    {"id": "HIST-EMPTY", "battery": "history", "kind": "empty",
     "query": "что было за этот период"},
    {"id": "HIST-TOOL-ERROR", "battery": "history", "kind": "error",
     "query": "что было за последние 10 часов"},
    {"id": "HIST-INGESTION-GAP", "battery": "history", "kind": "gap",
     "query": "что было за этот период"},
)
TIME_CASES = (
    ("TIME-HOUR-AGO", ["HC-ACC-TIME"]),
    ("TIME-MINUTE-AGO", ["HC-ACC-TIME"]),
    ("TIME-LAST-SECONDS", ["HC-ACC-TIME"]),
    ("TIME-LOCAL-MIDNIGHT", ["HC-ACC-TIME"]),
    ("TIME-UTC-CHAT", ["HC-ACC-TIME"]),
    ("TIME-DST", ["HC-ACC-TIME"]),
    ("TIME-SAME-TS", ["HC-ACC-TIME"]),
    ("TIME-EDIT", ["HC-ACC-TIME"]),
    ("TIME-FORWARD", ["HC-ACC-TIME"]),
    ("TIME-CURRENT-VS-FACT", ["HC-ACC-TIME"]),
    ("TIME-FACT-EPISODE", ["HC-ACC-TIME"]),
    ("TIME-MONTH-ONLY", ["HC-ACC-TIME"]),
    ("TIME-UNKNOWN", ["HC-ACC-TIME"]),
)
CHANNEL_CASES = (
    ("CH-FTS", ["HC-ACC-CHANNELS"]),
    ("CH-VECTOR", ["HC-ACC-CHANNELS"]),
    ("CH-GRAPH", ["HC-ACC-CHANNELS"]),
    ("CH-EPISODE", ["HC-ACC-CHANNELS"]),
    ("CH-ARCHIVE", ["HC-ACC-CHANNELS"]),
    ("CH-RECENT", ["HC-ACC-CHANNELS"]),
    ("CH-SUMMARY", ["HC-ACC-CHANNELS"]),
    ("CH-STORAGE-WRITER", ["HC-ACC-CHANNELS", "HC-TIME-PAYLOAD-PROOF"]),
)
TELEGRAM_CASES = (
    ("TG-SHORT", ["HC-ACC-TELEGRAM"]),
    ("TG-MARKDOWN", ["HC-ACC-TELEGRAM"]),
    ("TG-LITERAL", ["HC-ACC-TELEGRAM"]),
    ("TG-HTML-LINK", ["HC-ACC-TELEGRAM"]),
    ("TG-CHUNK", ["HC-ACC-TELEGRAM"]),
    ("TG-PARTIAL", ["HC-ACC-TELEGRAM"]),
)


async def run_scenarios(product, db, *, code_root: str, variant: str,
                        chat_id: int, as_of: int, tz: str,
                        batteries: tuple) -> list:
    scenarios = []
    if "history" in batteries:
        for case in HISTORY_CASES:
            row = await history_scenario(product, db, chat_id, as_of, tz,
                                         dict(case, variant=variant))
            row.update({"id": case["id"], "battery": "history",
                        "requirement_ids": ["HC-ACC-HISTORY",
                                            "HC-ACC-PAIRED"]})
            scenarios.append(row)
    if "time" in batteries:
        for case_id, reqs in TIME_CASES:
            row = await time_scenario(product, db, chat_id, as_of, tz, case_id)
            row.update({"id": case_id, "battery": "time",
                        "requirement_ids": reqs})
            scenarios.append(row)
    if "channels" in batteries:
        for case_id, reqs in CHANNEL_CASES:
            row = await channels_scenario(product, db, chat_id, as_of, tz,
                                          case_id)
            row.update({"id": case_id, "battery": "channels",
                        "requirement_ids": reqs})
            scenarios.append(row)
    if "telegram" in batteries:
        for case_id, reqs in TELEGRAM_CASES:
            row = await telegram_scenario(product, case_id, chat_id)
            row.update({"id": case_id, "battery": "telegram",
                        "requirement_ids": reqs})
            scenarios.append(row)
    if "free-speech" in batteries:
        scenarios.extend(scope_meta_scenarios(code_root, variant))
    for row in scenarios:
        if row.get("battery") in MANDATORY_BATTERIES:
            reqs = list(row.get("requirement_ids") or ())
            if "HC-ACC-PAIRED" not in reqs:
                reqs.append("HC-ACC-PAIRED")
            row["requirement_ids"] = reqs
    return scenarios


# ── payload / assertions ────────────────────────────────────────────────────

def build_assertions(payload: dict) -> list:
    snap = payload.get("snapshot") or {}
    cfg = payload.get("effective_config") or {}
    assertions = [
        {"id": "SNAPSHOT-READONLY", "status": "pass" if snap.get("read_only")
         else "fail"},
        {"id": "SNAPSHOT-SCHEMA", "status": "pass" if snap.get("schema")
         == EXPECTED_SCHEMA else "fail"},
        {"id": "SNAPSHOT-QUICK-CHECK", "status": "pass" if snap.get(
            "quick_check") == "ok" else "fail"},
        {"id": "SNAPSHOT-HASH-STABLE", "status": "pass" if snap.get(
            "sha256_before") and snap.get("sha256_before") == snap.get(
                "sha256_after") else "fail"},
        {"id": "CONFIG-PROVENANCE", "status": "pass" if cfg.get(
            "hot_config_measured") and not cfg.get("fixture", False) else
            ("not_applicable" if payload.get("mode") == "fixture" else "fail")},
        {"id": "CODE-ROOT", "status": "pass" if payload.get("product_sha")
         else "fail"},
        {"id": "NETWORK-OFF", "status": "pass" if payload.get(
            "network_guard") else "fail"},
        {"id": "TEXT-MODE", "status": {
            "pass": "pass", "fail": "fail",
            "not_executed": "not_executed",
            "not_applicable": "not_applicable",
        }.get((payload.get("text") or {}).get("status"), "not_executed")},
    ]
    return assertions


def _status_counts(rows: list) -> dict:
    return {
        "scenarios": len(rows),
        "pass": sum(1 for row in rows if (row.get("status") == "pass")),
        "fail": sum(1 for row in rows if (row.get("status") == "fail")),
        "not_executed": sum(1 for row in rows
                            if row.get("status") == "not_executed"),
        "not_applicable": sum(1 for row in rows
                              if row.get("status") == "not_applicable"),
    }


def overall_status(scenarios: list) -> str:
    statuses = [str(row.get("status") or "") for row in scenarios]
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status in ("not_executed", "not_applicable") for status in statuses):
        return "not_executed"
    if statuses and all(status == "pass" for status in statuses):
        return "pass"
    return "not_executed"


def requirements_summary(scenarios: list) -> dict:
    out = {}
    for req in HC_ACC_REQUIREMENTS:
        rows = [row for row in scenarios
                if req in (row.get("requirement_ids") or ())]
        if not rows:
            out[req] = {"status": "not_executed", "scenarios": []}
            continue
        statuses = [str(row.get("status") or "") for row in rows]
        if any(status == "fail" for status in statuses):
            status = "fail"
        elif any(status == "not_executed" for status in statuses):
            status = "not_executed"
        elif any(status == "pass" for status in statuses):
            status = "pass"
        else:
            status = "not_applicable"
        out[req] = {"status": status,
                    "scenarios": [row.get("id") for row in rows]}
    return out


def validate_no_text(payload: dict) -> list:
    bad = []
    for section in (payload.get("scenarios"),
                    (payload.get("payload") or {}).get("scenarios"),
                    (payload.get("text") or {}).get("scenarios")):
        if section and _find_key(section, "text"):
            bad.append("scenario_text")
    for key in ("message_text", "fact_text", "preview", "answer",
                "query", "prompt"):
        if _find_key(payload, key):
            bad.append(key)
    encoded = json.dumps(payload, ensure_ascii=False)
    if "SECRET_ACCEPT_TEXT" in encoded or "SECRET_TOPIC_TEXT" in encoded \
            or "Агент Секрет" in encoded:
        bad.append("fixture_marker")
    if BOT_TOKEN_RE.search(encoded):
        bad.append("bot_token")
    return bad


def _find_key(obj, key: str) -> bool:
    if isinstance(obj, dict):
        return key in obj or any(_find_key(value, key)
                                 for value in obj.values())
    if isinstance(obj, list):
        return any(_find_key(value, key) for value in obj[:50])
    return False


def compact_metrics(metrics: dict) -> dict:
    keep = {}
    for key in ("required_fact_recall", "relevance", "episode_completeness",
                "temporal_correctness", "participant_attribution",
                "source_proof", "latency_cost", "text_delivery",
                "no_moralizing", "static_meta"):
        value = metrics.get(key)
        if isinstance(value, dict):
            keep[key] = {k: v for k, v in value.items()
                         if k != "path" and not isinstance(v, BaseException)}
        else:
            keep[key] = value
    return keep


def compact_scenario(row: dict) -> dict:
    out = {
        "id": row.get("id"),
        "battery": row.get("battery"),
        "requirement_ids": list(row.get("requirement_ids") or ()),
        "status": row.get("status"),
        "reason": row.get("reason") or "",
        "metrics": compact_metrics(row.get("metrics") or {}),
        "checks": row.get("checks") or {},
    }
    for key in ("driver", "window", "added_lines_scanned",
                "banned_hits_sha256", "payload_summary", "meta",
                "factual_criterion", "changed_product_files", "out_of_scope",
                "source_ids", "source_id_count", "expected_ids_sha256",
                "model", "model_expected", "usage", "request_sha256",
                "response_sha256", "response_chars", "fragment",
                "fragment_sha256", "latency_ms", "temperature",
                "max_tokens", "context_mode", "static_proof_status",
                "response_mode", "error_class", "error_detail",
                "payload_stage", "writer_message_count",
                "writer_payload_sha256", "writer_payload_chars"):
        if key in row:
            out[key] = row[key]
    return out


def summary_md(payload: dict) -> str:
    lines = [
        f"# HC-ACCEPT harness — {payload.get('variant')}",
        "",
        f"- schema: `{payload.get('schema')}`",
        f"- mode: `{payload.get('mode')}`",
        f"- acceptance_eligible: `{payload.get('acceptance_eligible')}`",
        f"- candidate/product: `{payload.get('product_sha')}`",
        f"- snapshot: `{payload.get('snapshot', {}).get('sha256_before')}`",
        f"- snapshot after: `{payload.get('snapshot', {}).get('sha256_after')}`",
        f"- config: `{payload.get('effective_config', {}).get('sha256')}`",
        f"- as_of: `{payload.get('as_of')}`",
        f"- chat_id: `{payload.get('chat_id')}` tz `{payload.get('timezone')}`",
        f"- status: **{payload.get('status')}**",
        "",
        "| scenario | battery | status | reason | recall | temporal | source |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in payload.get("scenarios") or ():
        metrics = row.get("metrics") or {}
        def _p(key):
            value = metrics.get(key) or {}
            if value.get("applicable") is False:
                return "n/a"
            if value.get("den") is None:
                return "-"
            return f"{value.get('num')}/{value.get('den')}"
        lines.append(
            f"| {row.get('id')} | {row.get('battery')} | {row.get('status')} | "
            f"{row.get('reason') or '-'} | {_p('required_fact_recall')} | "
            f"{_p('temporal_correctness')} | {_p('source_proof')} |")
    lines += ["", "## Assertions", ""]
    for row in payload.get("assertions") or ():
        lines.append(f"- {row.get('id')}: **{row.get('status')}**")
    text = payload.get("text") or {}
    if text:
        lines += ["", "## Text battery", "",
                  f"- mode: `{text.get('mode')}`",
                  f"- status: **{text.get('status')}**",
                  f"- model: `{text.get('model')}`",
                  f"- reason: `{text.get('reason')}`"]
        for row in text.get("scenarios") or ():
            lines.append(f"- {row.get('id')}: **{row.get('status')}** "
                         f"`{row.get('reason') or '-'}`")
        static = text.get("static_proof") or {}
        lines.append(f"- static proof: **{static.get('status')}** "
                     f"`{static.get('reason') or '-'}`")
    lines += ["", "## Requirements", ""]
    for req, value in (payload.get("requirements") or {}).items():
        lines.append(f"- {req}: **{value.get('status')}** "
                     f"({', '.join(value.get('scenarios') or [])})")
    lines += ["", "## Limitations", ""]
    for item in payload.get("limitations") or ():
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


# ── single-variant run ──────────────────────────────────────────────────────

LIMITATIONS = (
    "read-only archive snapshot; no live bot process and no generated Writer "
    "prose",
    "fake Bot API records payloads; it is not a Telegram delivery",
    "baseline has no B/C1 modules by design: best-effort count page is the "
    "control, its fail is recorded honestly",
    "Writer-facing channel checks exercise the real canonical line builders, "
    "not a full LLM turn; this is stated per scenario",
    "ingestion-gap is not exposed by the read-only snapshot; marked "
    "not_applicable, not covered",
    "free-speech/no-objectivity is a meta scan of added product lines, not a "
    "factual criterion and not a prose-quality score",
)


async def run_single(args, code_root: str, variant: str, *,
                     snapshot: str, config_path: str, as_of: int,
                     tz: str, out_dir: Path) -> dict:
    env_info = prepare_env(args.env_file)
    product = load_product(
        code_root,
        load_dotenv=bool(args.llm == "real" and not env_info.get("present")))
    required_modules = ("database", "tool_router", "direct_chat",
                        "canonical")
    missing = [key for key in required_modules
               if not module_ok(product, key)]
    if missing:
        raise InputBlocked("PRODUCT-IMPORT", ",".join(missing))
    snap = snapshot_meta(snapshot, args.chat_id)
    cfg = load_config(config_path, as_of=as_of, chat_id=args.chat_id, tz=tz,
                      expected_release=args.expected_release,
                      fixture=args.fixture)
    capacity = capacity_info(product, cfg)
    head = git_out(code_root, "rev-parse", "HEAD")
    if args.expected_sha and head != args.expected_sha:
        raise InputBlocked("CODE-ROOT", "expected_sha_mismatch")
    expected_variant = variant
    detected = detect_variant(head)
    if detected not in ("baseline", "candidate"):
        raise InputBlocked("CODE-ROOT", "unknown_product_sha")
    if expected_variant and detected != expected_variant:
        raise InputBlocked("CODE-ROOT", "variant_sha_mismatch")
    try:
        dirty = git_out(code_root, "status", "--porcelain", "--",
                        *PRODUCT_PATHS)
    except Exception:
        raise InputBlocked("CODE-ROOT", "product_status_error")
    if dirty.strip():
        raise InputBlocked("CODE-ROOT", "product_tree_dirty")

    db, conn = await open_readonly_service(product, snapshot)
    payload = {
        "schema": SCHEMA,
        "created_at": utc_now(),
        "mode": "fixture" if args.fixture else "production-copy",
        "acceptance_eligible": not bool(args.fixture),
        "variant": detected,
        "product_sha": head,
        "code_root": str(Path(code_root).resolve()),
        "snapshot": {**snap, "sha256_after": snap["sha256_before"]},
        "effective_config": cfg,
        "capacity": capacity,
        "as_of": int(as_of),
        "as_of_utc": fmt_utc(as_of),
        "chat_id": int(args.chat_id),
        "timezone": tz,
        "timezone_source": cfg.get("timezone_source"),
        "scenario_set": list(chosen_batteries(args.scenario_set)),
        "network_guard": True,
        "blockers": [],
        "scenarios": [],
        "limitations": list(LIMITATIONS),
    }
    batteries = chosen_batteries(args.scenario_set)
    text_payload = {
        "mode": "stub", "status": "not_executed",
        "reason": "free_speech_battery_not_selected",
        "scenarios": [], "static_proof": free_speech_scenario(
            product, code_root, "candidate"),
    }
    try:
        with NetworkBlock():
            scenarios = await run_scenarios(
                product, db, code_root=code_root, variant=detected,
                chat_id=args.chat_id, as_of=as_of, tz=tz,
                batteries=batteries)
        if "free-speech" in batteries:
            text_payload = await real_text_scenarios(
                product, db, cfg, code_root, detected, args,
                args.chat_id, tz, env_info)
            text_payload["bounded"] = text_payload.get("bounded") or {
                "requested_max_tokens": int(
                    args.text_max_tokens or cfg.get("max_tokens") or 400),
                "requested_temperature": cfg.get("temperature"),
                "timeout_s": args.text_timeout,
                "llm_calls_max": 1,
                "context": args.text_context,
            }
        payload_scenarios = [compact_scenario(row) for row in scenarios]
        text_scenarios = [compact_scenario(row)
                          for row in text_payload.get("scenarios") or ()]
        payload["scenarios"] = payload_scenarios
        payload["payload"] = {
            "scenarios": payload_scenarios,
            "status": overall_status(scenarios),
            "summary": _status_counts(payload_scenarios),
            "capacity": capacity,
        }
        text_payload["scenarios"] = text_scenarios
        text_payload["summary"] = _status_counts(text_scenarios)
        text_payload["env"] = env_info
        payload["text"] = text_payload
        all_rows = scenarios + (text_payload.get("scenarios") or [])
        payload["status"] = overall_status(all_rows)
        payload["requirements"] = requirements_summary(all_rows)
        payload["summary"] = _status_counts(payload_scenarios + text_scenarios)
        payload["summary"]["payload_scenarios"] = len(payload_scenarios)
        payload["summary"]["text_scenarios"] = len(text_scenarios)
    finally:
        try:
            await conn.close()
        except Exception:
            pass
    payload["snapshot"]["sha256_after"] = sha256_file(snapshot)
    if payload["snapshot"]["sha256_after"] != payload["snapshot"][
            "sha256_before"]:
        payload["blockers"].append({"id": "SNAPSHOT-CHANGED",
                                    "detail": "sha256_changed_during_run"})
        payload["status"] = "blocked"
    payload["assertions"] = build_assertions(payload)
    bad_text = validate_no_text(payload)
    if bad_text:
        payload["blockers"].append({"id": "TEXT-LEAK",
                                    "detail": ",".join(bad_text)})
        payload["status"] = "blocked"
        payload["assertions"].append({"id": "NO-TEXT", "status": "fail"})
    else:
        payload["assertions"].append({"id": "NO-TEXT", "status": "pass"})
    return payload


def write_variant(payload: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"p0-hc-acceptance-{payload['variant']}.json"
    safe_write(path, json.dumps(payload, ensure_ascii=False, indent=1,
                                sort_keys=True) + "\n")
    safe_write(path.with_suffix(".md"), summary_md(payload))
    safe_write(path.with_suffix(".sha256"),
               sha256_file(str(path)) + "  " + path.name + "\n")
    return path


# ── paired composition ──────────────────────────────────────────────────────

def compose_pair(base: dict, cand: dict, out_dir: Path) -> dict:
    blockers = []
    for key in ("as_of", "chat_id", "timezone"):
        if base.get(key) != cand.get(key):
            blockers.append({"id": "PAIR-INPUT-MISMATCH", "detail": key})
    for key in ("sha256_before", "sha256_after", "schema"):
        if (base.get("snapshot") or {}).get(key) != (
                cand.get("snapshot") or {}).get(key):
            blockers.append({"id": "PAIR-SNAPSHOT-MISMATCH", "detail": key})
    if (base.get("effective_config") or {}).get("sha256") != (
            cand.get("effective_config") or {}).get("sha256"):
        blockers.append({"id": "PAIR-CONFIG-MISMATCH",
                         "detail": "config_sha256"})
    base_rows = list(base.get("scenarios") or ()) + list(
        (base.get("text") or {}).get("scenarios") or ())
    cand_rows = list(cand.get("scenarios") or ()) + list(
        (cand.get("text") or {}).get("scenarios") or ())
    base_by_id = {row.get("id"): row for row in base_rows}
    cand_by_id = {row.get("id"): row for row in cand_rows}
    ids = list(dict.fromkeys(list(base_by_id) + list(cand_by_id)))
    rows = []
    for case_id in ids:
        b = base_by_id.get(case_id) or {"status": "not_executed",
                                        "reason": "missing_in_baseline"}
        c = cand_by_id.get(case_id) or {"status": "not_executed",
                                        "reason": "missing_in_candidate"}
        if c.get("status") == "pass":
            if b.get("status") == "fail":
                status, note = "pass", "candidate_improved_over_baseline"
            elif b.get("status") == "pass":
                status, note = "pass", "parity_no_regression"
            elif b.get("status") == "not_applicable" and (
                    c.get("battery") in ("meta", "free-speech", "text")):
                status, note = "pass", "meta_candidate_only"
            else:
                status, note = "not_executed", "baseline_not_executed"
        elif c.get("status") == "fail":
            status, note = "fail", "candidate_failed"
        elif c.get("status") == "not_executed":
            status, note = "not_executed", c.get("reason") or "not_executed"
        else:
            status, note = "not_applicable", c.get("reason") or "not_applicable"
        rows.append({
            "id": case_id,
            "battery": c.get("battery") or b.get("battery"),
            "section": ("text" if (c.get("battery") == "text"
                                   or b.get("battery") == "text")
                        else "payload"),
            "requirement_ids": c.get("requirement_ids")
            or b.get("requirement_ids") or [],
            "status": status,
            "note": note,
            "baseline_status": b.get("status"),
            "candidate_status": c.get("status"),
            "baseline_reason": b.get("reason") or "",
            "candidate_reason": c.get("reason") or "",
        })
    reqs = {}
    for req in HC_ACC_REQUIREMENTS:
        mapped = [row for row in rows
                  if req in (row.get("requirement_ids") or ())]
        if not mapped:
            reqs[req] = {"status": "not_executed", "scenarios": []}
            continue
        statuses = [row["status"] for row in mapped]
        if any(status == "fail" for status in statuses):
            status = "fail"
        elif any(status == "not_executed" for status in statuses):
            status = "not_executed"
        elif any(status == "pass" for status in statuses):
            status = "pass"
        else:
            status = "not_applicable"
        reqs[req] = {"status": status,
                     "scenarios": [row["id"] for row in mapped]}
    if blockers:
        status = "blocked"
    elif any(row["status"] == "fail" for row in rows):
        status = "fail"
    elif any(row["status"] in ("not_executed", "not_applicable")
             for row in rows):
        status = "not_executed"
    else:
        status = "pass"
    payload = {
        "schema": SCHEMA,
        "created_at": utc_now(),
        "mode": "paired",
        "acceptance_eligible": bool(cand.get("acceptance_eligible"))
        and bool(base.get("acceptance_eligible")),
        "status": status,
        "blockers": blockers,
        "baseline": {key: base.get(key) for key in (
            "variant", "product_sha", "snapshot", "effective_config", "as_of",
            "chat_id", "timezone", "status", "summary")},
        "candidate": {key: cand.get(key) for key in (
            "variant", "product_sha", "snapshot", "effective_config", "as_of",
            "chat_id", "timezone", "status", "summary")},
        "scenarios": rows,
        "payload": {
            "scenarios": [row for row in rows
                          if row.get("section") == "payload"],
            "summary": _status_counts(
                [row for row in rows if row.get("section") == "payload"]),
        },
        "text": {
            "mode": (cand.get("text") or {}).get("mode"),
            "status": (cand.get("text") or {}).get("status"),
            "reason": (cand.get("text") or {}).get("reason"),
            "model": (cand.get("text") or {}).get("model"),
            "embedding_model": (cand.get("text") or {}).get(
                "embedding_model"),
            "env": (cand.get("text") or {}).get("env"),
            "bounded": (cand.get("text") or {}).get("bounded"),
            "static_proof": (cand.get("text") or {}).get("static_proof"),
            "scenarios": [row for row in rows
                          if row.get("section") == "text"],
            "summary": _status_counts(
                [row for row in rows if row.get("section") == "text"]),
        },
        "requirements": reqs,
        "summary": {
            "pass": sum(1 for row in rows if row["status"] == "pass"),
            "fail": sum(1 for row in rows if row["status"] == "fail"),
            "not_executed": sum(1 for row in rows
                                if row["status"] == "not_executed"),
            "not_applicable": sum(1 for row in rows
                                  if row["status"] == "not_applicable"),
        },
        "assertions": [
            {"id": "PAIR-SAME-INPUTS",
             "status": "pass" if not blockers else "fail"},
            {"id": "PAIR-SAME-SNAPSHOT",
             "status": "pass" if (base.get("snapshot") or {}).get(
                 "sha256_before") == (cand.get("snapshot") or {}).get(
                     "sha256_before") else "fail"},
            {"id": "PAIR-SAME-CONFIG",
             "status": "pass" if (base.get("effective_config") or {}).get(
                 "sha256") == (cand.get("effective_config") or {}).get(
                     "sha256") else "fail"},
            {"id": "CONFIG-PROVENANCE",
             "status": ("not_applicable" if cand.get("mode") == "fixture"
                        else "pass" if (cand.get("effective_config") or {}).get(
                            "hot_config_measured") else "fail")},
        ],
        "limitations": list(LIMITATIONS) + [
            "paired composition compares compact scenario statuses; Reviewer "
            "reads the two raw variant JSONs for exact metric denominators",
        ],
    }
    bad_text = validate_no_text(payload)
    payload["assertions"].append({
        "id": "NO-TEXT", "status": "fail" if bad_text else "pass"})
    if bad_text:
        payload["blockers"].append({"id": "TEXT-LEAK",
                                    "detail": ",".join(bad_text)})
        payload["status"] = "blocked"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "p0-hc-acceptance-paired.json"
    safe_write(path, json.dumps(payload, ensure_ascii=False, indent=1,
                                sort_keys=True) + "\n")
    safe_write(path.with_suffix(".md"), _pair_md(payload))
    safe_write(path.with_suffix(".sha256"),
               sha256_file(str(path)) + "  " + path.name + "\n")
    return payload


def _pair_md(payload: dict) -> str:
    lines = [
        "# HC-ACCEPT paired harness",
        "",
        f"- status: **{payload.get('status')}**",
        f"- acceptance_eligible: `{payload.get('acceptance_eligible')}`",
        f"- baseline: `{payload.get('baseline', {}).get('product_sha')}`",
        f"- candidate: `{payload.get('candidate', {}).get('product_sha')}`",
        f"- snapshot sha: `{payload.get('candidate', {}).get('snapshot', {}).get('sha256_before')}`",
        f"- config sha: `{payload.get('candidate', {}).get('effective_config', {}).get('sha256')}`",
        f"- as_of: `{payload.get('candidate', {}).get('as_of')}`",
        "",
        "| scenario | battery | paired | baseline | candidate | note |",
        "|---|---|---|---|---|---|",
    ]
    for row in payload.get("scenarios") or ():
        lines.append(
            f"| {row.get('id')} | {row.get('battery')} | {row.get('status')} | "
            f"{row.get('baseline_status')} | {row.get('candidate_status')} | "
            f"{row.get('note')} |")
    lines += ["", "## Requirements", ""]
    for req, value in (payload.get("requirements") or {}).items():
        lines.append(f"- {req}: **{value.get('status')}**")
    text = payload.get("text") or {}
    if text:
        lines += ["", "## Text battery", "",
                  f"- mode: `{text.get('mode')}`",
                  f"- status: **{text.get('status')}**",
                  f"- model: `{text.get('model')}`"]
        for row in text.get("scenarios") or ():
            lines.append(f"- {row.get('id')}: **{row.get('status')}** "
                         f"`{row.get('note') or ''}`")
    lines += ["", "## Blockers", ""]
    for row in payload.get("blockers") or ():
        lines.append(f"- {row.get('id')}: `{row.get('detail')}`")
    return "\n".join(lines) + "\n"


# ── paired runner ───────────────────────────────────────────────────────────

def _child_command(args, root: str, variant: str, out_dir: Path,
                   snapshot: str, config_path: str, as_of: int,
                   *, include_expected: bool = False) -> list:
    command = [
        sys.executable, str(Path(__file__).resolve()), "--child",
        "--code-root", root, "--variant", variant, "--out", str(out_dir),
        "--snapshot", snapshot, "--effective-config", config_path,
        "--as-of", str(as_of), "--chat-id", str(args.chat_id),
        "--tz", args.tz, "--scenario-set", args.scenario_set,
        "--expected-release", args.expected_release,
        "--llm", args.llm, "--text-context", args.text_context,
        "--text-timeout", str(args.text_timeout),
        "--text-max-tokens", str(args.text_max_tokens),
    ]
    if args.env_file:
        command += ["--env-file", args.env_file]
    if args.fixture:
        command.append("--fixture")
    if include_expected and args.expected_sha:
        command += ["--expected-sha", args.expected_sha]
    return command


def run_pair(args, roots: list, out_dir: Path, as_of: int,
             tz: str) -> int:
    variants = {}
    for root in roots:
        head = git_out(root, "rev-parse", "HEAD")
        variant = detect_variant(head)
        if variant not in ("baseline", "candidate"):
            raise InputBlocked("CODE-ROOT", "unknown_product_sha")
        if variant in variants:
            raise InputBlocked("CODE-ROOT", "duplicate_variant")
        variants[variant] = root
    if set(variants) != {"baseline", "candidate"}:
        raise InputBlocked("CODE-ROOT", "pair_requires_baseline_and_candidate")
    snapshot = args.snapshot
    config_path = args.effective_config
    if args.fixture and (not snapshot or not config_path):
        fixture_dir = out_dir / "_fixture"
        product = load_product(variants["candidate"])
        snapshot = snapshot or asyncio.run(create_fixture_db(
            product, fixture_dir, chat_id=args.chat_id, as_of=as_of, tz=tz))
        config_path = config_path or fixture_config(
            fixture_dir, as_of=as_of, chat_id=args.chat_id, tz=tz)
    if not snapshot or not config_path:
        raise InputBlocked("CONFIG-MISSING", "inputs_required")
    # Validate once in the parent for a fast, deterministic blocker.
    snapshot_meta(snapshot, args.chat_id)
    load_config(config_path, as_of=as_of, chat_id=args.chat_id, tz=tz,
                expected_release=args.expected_release,
                fixture=args.fixture)
    results = {}
    env = {key: value for key, value in os.environ.items()
           if key != "PYTHONPATH"}
    env["ADMINBOT_SKIP_DOTENV"] = "1"
    for variant in ("baseline", "candidate"):
        root = variants[variant]
        child_out = out_dir / variant
        command = _child_command(args, root, variant, child_out, snapshot,
                                 config_path, as_of)
        proc = subprocess.run(command, cwd=root, env=env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=3600)
        path = child_out / f"p0-hc-acceptance-{variant}.json"
        if not path.is_file():
            raise InputBlocked(
                "CHILD-FAILED",
                f"{variant}_exit_{proc.returncode}:"
                + (proc.stderr or "")[-300:].replace("\n", " ")[:300])
        results[variant] = json.loads(path.read_text(encoding="utf-8"))
        if proc.returncode not in (0, 1, 3):
            # Blocked/technical child still writes JSON; composition keeps it.
            pass
    pair = compose_pair(results["baseline"], results["candidate"], out_dir)
    if any(result.get("status") == "blocked" for result in results.values()):
        for variant, result in results.items():
            if result.get("status") == "blocked":
                for blocker in result.get("blockers") or ():
                    entry = dict(blocker)
                    entry["id"] = f"{variant}:{entry.get('id')}"
                    pair["blockers"].append(entry)
        pair["status"] = "blocked"
        safe_write(out_dir / "p0-hc-acceptance-paired.json",
                   json.dumps(pair, ensure_ascii=False, indent=1,
                              sort_keys=True) + "\n")
    safe_write(out_dir / "p0-hc-acceptance-paired.md", _pair_md(pair))
    print(json.dumps({
        "status": pair.get("status"),
        "path": str(out_dir / "p0-hc-acceptance-paired.json"),
        "summary": pair.get("summary"),
        "blockers": pair.get("blockers"),
    }, ensure_ascii=False))
    return _exit_for_status(pair["status"])


def _exit_for_status(status: str) -> int:
    return {"pass": 0, "fail": 1, "blocked": 2,
            "not_executed": 3}.get(str(status), 4)


def blocked_payload(args, code: str, detail: str) -> dict:
    return {
        "schema": SCHEMA,
        "created_at": utc_now(),
        "mode": "fixture" if args.fixture else "production-copy",
        "acceptance_eligible": False,
        "variant": args.variant or "",
        "status": "blocked",
        "blockers": [{"id": code, "detail": detail}],
        "scenarios": [],
        "assertions": [{"id": code, "status": "fail"}],
        "limitations": list(LIMITATIONS),
    }


# ── main ────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.env_file:
        args.env_file = str(Path(args.env_file).resolve())
    out_dir = Path(args.out).resolve()
    try:
        as_of = parse_as_of(args.as_of)
    except Exception:
        payload = blocked_payload(args, "AS-OF-INVALID", "as_of_required")
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 2
    tz = args.tz
    if not tz:
        payload = blocked_payload(args, "TZ-MISSING", "iana_timezone_required")
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 2
    if not args.fixture:
        if as_of != PINNED_AS_OF:
            payload = blocked_payload(args, "AS-OF-NOT-PINNED",
                                      "as_of_must_be_1795187666")
            safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                       json.dumps(payload, ensure_ascii=False,
                                  indent=1) + "\n")
            print(json.dumps({"status": "blocked",
                              "blockers": payload["blockers"]}))
            return 2
        if tz != PINNED_TZ:
            payload = blocked_payload(args, "TZ-NOT-PINNED",
                                      "tz_must_be_Asia_Yekaterinburg")
            safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                       json.dumps(payload, ensure_ascii=False,
                                  indent=1) + "\n")
            print(json.dumps({"status": "blocked",
                              "blockers": payload["blockers"]}))
            return 2
        if args.chat_id not in (PRIMARY_CHAT, SECONDARY_CHAT):
            payload = blocked_payload(args, "CHAT-NOT-PINNED",
                                      "chat_must_be_primary_or_secondary")
            safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                       json.dumps(payload, ensure_ascii=False,
                                  indent=1) + "\n")
            print(json.dumps({"status": "blocked",
                              "blockers": payload["blockers"]}))
            return 2
    try:
        zoneinfo.ZoneInfo(tz)
    except Exception:
        payload = blocked_payload(args, "TZ-INVALID", "unknown_iana_timezone")
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 2

    roots = [str(Path(root).resolve()) for root in args.code_root]
    if not roots:
        payload = blocked_payload(args, "CODE-ROOT-MISSING",
                                  "code_root_required")
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 2
    paired = len(roots) == 2 and not args.child and not args.no_pair
    try:
        if paired:
            return run_pair(args, roots, out_dir, as_of, tz)
        root = roots[0]
        variant = args.variant or detect_variant(git_out(root, "rev-parse",
                                                         "HEAD"))
        snapshot = args.snapshot
        config_path = args.effective_config
        if args.fixture and (not snapshot or not config_path):
            fixture_dir = out_dir / "_fixture"
            product = load_product(root)
            snapshot = snapshot or asyncio.run(create_fixture_db(
                product, fixture_dir, chat_id=args.chat_id, as_of=as_of,
                tz=tz))
            config_path = config_path or fixture_config(
                fixture_dir, as_of=as_of, chat_id=args.chat_id, tz=tz)
        payload = asyncio.run(run_single(
            args, root, variant, snapshot=snapshot, config_path=config_path,
            as_of=as_of, tz=tz, out_dir=out_dir))
        path = write_variant(payload, out_dir)
        print(json.dumps({
            "status": payload.get("status"),
            "variant": payload.get("variant"),
            "product_sha": payload.get("product_sha"),
            "path": str(path),
            "summary": payload.get("summary"),
            "blockers": payload.get("blockers"),
        }, ensure_ascii=False))
        return _exit_for_status(payload.get("status"))
    except InputBlocked as exc:
        payload = blocked_payload(args, exc.code, exc.detail)
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 2
    except subprocess.TimeoutExpired:
        payload = blocked_payload(args, "CHILD-TIMEOUT", "child_timeout")
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 2
    except Exception as exc:
        payload = blocked_payload(args, "TECHNICAL", reason_of(exc))
        safe_write(out_dir / "p0-hc-acceptance-blocked.json",
                   json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
        print(json.dumps({"status": "blocked",
                          "blockers": payload["blockers"]}))
        return 4


if __name__ == "__main__":
    sys.exit(main())
