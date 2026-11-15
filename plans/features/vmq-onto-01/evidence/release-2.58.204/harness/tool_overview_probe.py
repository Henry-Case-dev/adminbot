# -*- coding: utf-8 -*-
"""Postdeploy person-overview TOOL probe (read-only) for 2.58.204.

Exercises the deployed tree's `get_user_context` tool path (biography/general/
identity) on a COPY of the production database:

  * exactly one `mca_retrieval_context.retrieve` per dispatch;
  * include_overview only on the person-overview purposes;
  * bounded overview slots (coverage / independent_periods / counterexamples /
    limitations) in the tool envelope;
  * identity negative: no overview keys, no overview request;
  * no extra search/router/LLM call: memory/embedding/generate spies stay
    empty apart from the single retrieval internals;
  * correction/version trace: overview episode_versions are compared with a
    fresh SQL recomputation of `episode_source_fingerprint` over the actual
    `smart_messages.current_revision` values of the copy.

No live writes, no restart, no Telegram, no provider chat call. The output
contains ids/periods/counts/codes only; the subject name is never written.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import sqlite3
import sys
import time
import traceback

VARIANT = os.environ.get("VMQ_VARIANT", "deployed")
CLONE = os.environ.get("VMQ_CLONE", "/var/www/admin_bot")
DBPATH = os.environ.get("VMQ_DB", "/root/vmq204/measure/e2e.db")
OUT = os.environ.get("VMQ_OUT", "/root/vmq204/measure/e2e_tool.json")
ENT = os.environ.get("VMQ_ENT", "/root/vmqC/measure/entities.json")
CFG = os.environ.get("VMQ_CFG", "/root/vmq204/measure/cfg204.json")
APP = "/var/www/admin_bot"
CHAT = -1002661910336

sys.path.insert(0, CLONE)
os.chdir(APP)
logging.basicConfig(level=logging.ERROR,
                    format="%(levelname)s %(name)s: %(message)s")

import services  # noqa: E402
from config.settings import settings  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import mca_episodes  # noqa: E402
from services import mca_gates  # noqa: E402
from services import mca_retrieval_context as mca  # noqa: E402
from services.database import DatabaseService  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402
from services.summary_memory import MemoryManager  # noqa: E402
from services.tool_router import ToolContext, ToolDeps, ToolRouter  # noqa: E402
from services.tool_schemas import MEMORY_LOOKUP_TOOL_NAME  # noqa: E402

WATCH = ("services/mca_retrieval_context.py",
         "services/tool_router.py",
         "services/direct_chat_service.py",
         "services/semantic_contracts.py",
         "services/database.py")


def sha12(text) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_key(key: str):
    text = str(key or "")
    if ":tg:" in text:
        _c, _s, raw = text.rpartition(":tg:")
        return ("tg_message_id", _int(raw))
    if ":db:" in text:
        _c, _s, raw = text.rpartition(":db:")
        return ("id", _int(raw))
    return (None, None)


def _sql(path, sql_text, params=()):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=20)
        try:
            return con.execute(sql_text, params).fetchall()
        finally:
            con.close()
    except Exception as exc:                    # noqa: BLE001
        return "err:%s" % type(exc).__name__


def overview_core(overview) -> dict | None:
    if overview is None:
        return None
    try:
        data = overview.as_dict()
    except Exception:                            # noqa: BLE001
        return {"error": "as_dict_failed"}
    coverage = data.get("coverage") or {}
    present = [{"period": block.get("period"),
                "episodes": block.get("episodes"),
                "refs": len(block.get("episode_refs") or ())}
               for block in coverage.get("present_periods") or ()
               if isinstance(block, dict)]
    support = [{"period": row.get("period"),
                "independent": row.get("independent"),
                "repeated": row.get("repeated")}
               for row in data.get("period_support") or ()
               if isinstance(row, dict)]
    versions = []
    for row in data.get("episode_versions") or ():
        if isinstance(row, dict):
            versions.append({
                "episode_ref": str(row.get("episode_ref") or "")[:32],
                "source_fingerprint": str(row.get("source_fingerprint") or ""),
                "content_status": row.get("content_status"),
                "stale": bool(row.get("stale")),
                "source_integrity": row.get("source_integrity"),
            })
    hints = []
    for row in data.get("semantic_hints") or ():
        if isinstance(row, dict):
            hints.append({"kind": row.get("kind"),
                          "status": row.get("status")
                          or row.get("verification") or row.get("type_status"),
                          "basis": row.get("basis"),
                          "conflict": row.get("conflict_status"),
                          "degraded": list(row.get("degraded") or ())[:6],
                          "candidates": int(row.get("candidates") or 0)})
    counter = [{"left_refs": len(pair.get("left_refs") or ()),
                "right_refs": len(pair.get("right_refs") or ()),
                "left_chars": len(str(pair.get("left_text") or "")),
                "right_chars": len(str(pair.get("right_text") or ""))}
               for pair in data.get("counterexamples") or ()
               if isinstance(pair, dict)]
    return {
        "state": data.get("state"),
        "subject_present": bool(data.get("subject_id")),
        "derived_version": data.get("derived_version"),
        "coverage": {
            "period_grain": coverage.get("period_grain"),
            "present_periods": present,
            "missing_periods": coverage.get("missing_periods"),
            "unknown_time_refs": len(
                coverage.get("unknown_time_episode_refs") or ()),
            "complete": coverage.get("complete"),
            "complete_reason": coverage.get("complete_reason"),
            "timezone": coverage.get("timezone"),
        },
        "independent_periods": list(data.get("independent_periods") or ()),
        "period_support": support,
        "episode_refs": [str(v)[:32] for v in
                         (data.get("episode_refs") or ())[:20]],
        "episode_refs_count": len(data.get("episode_refs") or ()),
        "episode_versions": versions,
        "support_source_refs_count": len(data.get("support_source_refs") or ()),
        "independent_support_count": data.get("independent_support_count"),
        "repeated_claims": data.get("repeated_claims"),
        "counterexamples": counter,
        "counterexamples_count": len(counter),
        "limitations": list(data.get("limitations") or ()),
        "semantic_hints": hints,
    }


def version_check(conn_path, refs, versions) -> dict:
    """Recompute source fingerprints from the copy's real revisions."""
    by_ref = {row["episode_ref"]: row for row in versions}
    wanted = [str(ref) for ref in refs][:40]
    if not wanted:
        return {"status": "no_episode_refs"}
    rows = _sql(
        conn_path,
        "SELECT episode_id, message_keys_json, COALESCE(recheck_pending,0) "
        "FROM mca_episodes WHERE chat_id=? AND episode_id IN (%s)"
        % ",".join("?" for _ in wanted), (CHAT, *wanted))
    if isinstance(rows, str):
        return {"status": rows}
    keys_by_ref = {}
    recheck = {}
    for episode_id, raw, pending in rows:
        try:
            keys = [str(k) for k in json.loads(raw or "[]")]
        except Exception:                        # noqa: BLE001
            keys = []
        keys_by_ref[str(episode_id)] = keys
        recheck[str(episode_id)] = bool(int(pending or 0))
    all_values = {}
    wanted_tg, wanted_db = [], []
    for keys in keys_by_ref.values():
        for key in keys:
            column, value = _parse_key(key)
            if column == "tg_message_id" and value is not None:
                wanted_tg.append(value)
            elif column == "id" and value is not None:
                wanted_db.append(value)
    for column, values in (("tg_message_id", wanted_tg), ("id", wanted_db)):
        values = list(dict.fromkeys(values))
        if not values:
            continue
        got = _sql(
            conn_path,
            "SELECT %s, current_revision FROM smart_messages "
            "WHERE chat_id=? AND %s IN (%s)"
            % (column, column, ",".join("?" for _ in values)),
            (CHAT, *values))
        if isinstance(got, str):
            return {"status": got}
        for token, revision in got:
            all_values[int(token)] = int(revision or 1)
    checked = []
    for ref in wanted:
        keys = keys_by_ref.get(ref)
        if keys is None:
            checked.append({"episode_ref": ref[:32], "present": False})
            continue
        revisions = {}
        present = 0
        corrected = 0
        for key in keys:
            column, value = _parse_key(key)
            revision = all_values.get(int(value)) if value is not None else None
            if revision is None:
                continue
            present += 1
            revisions[key] = revision
            if revision > 1:
                corrected += 1
        fingerprint = mca_episodes.episode_source_fingerprint(
            keys, revisions=revisions)
        view = by_ref.get(ref) or {}
        checked.append({
            "episode_ref": ref[:32],
            "present": True,
            "keys": len(keys),
            "keys_resolved": present,
            "keys_corrected_revision_gt1": corrected,
            "recheck_pending": recheck.get(ref),
            "sql_fingerprint": fingerprint,
            "view_fingerprint": view.get("source_fingerprint"),
            "fingerprint_match": fingerprint == view.get("source_fingerprint"),
            "view_source_integrity": view.get("source_integrity"),
            "view_stale": view.get("stale"),
        })
    overall = _sql(conn_path,
                   "SELECT COUNT(*), COALESCE(SUM(current_revision>1),0) "
                   "FROM smart_messages WHERE chat_id=?", (CHAT,))
    return {
        "status": "checked",
        "episodes": checked,
        "all_fingerprints_match": all(row.get("fingerprint_match")
                                      for row in checked if row.get("present")),
        "episodes_with_corrected_source": sum(
            1 for row in checked if row.get("keys_corrected_revision_gt1")),
        "copy_revision_stats": ({"messages": int(overall[0][0]),
                                 "messages_revision_gt1": int(overall[0][1])}
                                if not isinstance(overall, str) and overall
                                else overall),
    }


class _Cache:
    def __init__(self, data):
        self._data = dict(data or {})
        self.pg = None

    def get(self, key, default=None):
        return self._data.get(key, default)

    def get_all(self):
        return dict(self._data)


class Spy:
    def __init__(self):
        self.calls = []
        self._orig = None

    def __enter__(self):
        self._orig = mca.retrieve
        spy = self

        async def wrapper(db, memory, request):
            started = time.monotonic()
            out = await spy._orig(db, memory, request)
            spy.calls.append({
                "seconds": round(time.monotonic() - started, 2),
                "include_overview": bool(getattr(request,
                                                  "include_overview", False)),
                "purpose": getattr(request, "purpose", None),
                "memory_scope": getattr(request, "memory_scope", None),
                "channels": list(getattr(request, "channels", ()) or ()),
                "subject_ids": list(
                    getattr(request, "subject_entity_ids", ()) or ()),
                "result_object_id": id(out),
                "status": getattr(out, "status", None),
                "reason_code": getattr(out, "reason_code", None),
                "candidates": len(getattr(out, "candidates", ()) or ()),
                "fact_rows": len(getattr(out, "fact_rows", ()) or ()),
                "overview": overview_core(getattr(out, "overview", None)),
            })
            return out

        mca.retrieve = wrapper
        return self

    def __exit__(self, *exc):
        mca.retrieve = self._orig
        return False


class CountSpy:
    def __init__(self, obj, names):
        self.obj = obj
        self.names = names
        self.calls = {}
        self._orig = {}

    def __enter__(self):
        for name in self.names:
            orig = getattr(self.obj, name, None)
            if orig is None:
                continue
            self.calls[name] = 0
            self._orig[name] = orig
            setattr(self.obj, name, self._wrap(name, orig))
        return self

    def _wrap(self, name, orig):
        spy = self

        async def wrapper(*args, **kwargs):
            spy.calls[name] = spy.calls.get(name, 0) + 1
            return await orig(*args, **kwargs)

        return wrapper

    def __exit__(self, *exc):
        for name, orig in self._orig.items():
            setattr(self.obj, name, orig)
        return False


async def _aliases():
    try:
        from services.summary_aliases import build_alias_resolver
        got = await build_alias_resolver(CHAT)
        if got is not None and hasattr(got, "resolve"):
            return got, "real"
    except Exception:                            # noqa: BLE001
        pass

    class _Stub:
        def canon_name(self, name):
            return str(name or "").strip()

        def resolve(self, user_id, nickname=None, username=None,
                    memory_name=None):
            return str(nickname or username or memory_name or user_id or "")

    return _Stub(), "stub"


def _envelope_view(payload: str) -> dict:
    try:
        data = json.loads(payload)
    except Exception:                            # noqa: BLE001
        return {"json": False, "prefix": str(payload)[:120]}
    out = {"json": True, "keys": sorted(data.keys())}
    for key in ("status", "purpose", "empty_reason", "no_data"):
        if key in data:
            out[key] = data.get(key)
    for key in ("facts", "sources", "coverage", "independent_periods",
                "limitations", "counterexamples"):
        value = data.get(key)
        if isinstance(value, list):
            out[key] = len(value)
    if isinstance(data.get("coverage"), list):
        out["coverage_lines"] = [str(v) for v in data["coverage"]][:12]
    if isinstance(data.get("independent_periods"), list):
        out["independent_periods_values"] = [
            str(v) for v in data["independent_periods"]][:12]
    if isinstance(data.get("limitations"), list):
        out["limitations_codes"] = [str(v) for v in data["limitations"]][:12]
    if isinstance(data.get("counterexamples"), list):
        out["counterexamples_chars"] = [
            len(str(v)) for v in data["counterexamples"]][:8]
    extra = data.get("subject_material")
    if isinstance(extra, dict):
        out["subject_material"] = {k: extra.get(k) for k in
                                   ("years", "sources", "distinct_years")}
    temp = data.get("temporal_projection")
    if isinstance(temp, dict):
        out["temporal_projection"] = {
            k: temp.get(k) for k in
            ("edges_total", "year_bearing", "years", "reason", "invented")}
    return out


async def main() -> int:
    entities = json.load(open(ENT, encoding="utf-8"))
    cfg = json.load(open(CFG, encoding="utf-8"))
    hot.set_config_cache(_Cache(cfg.get("effective") or {}))
    person = entities["person"]
    name = str(person.get("name") or "")
    uid = _int(person.get("uid"))

    identity = {
        "artifact_kind": "postdeploy_readonly_e2e",
        "variant": VARIANT,
        "clone": CLONE,
        "services_file": services.__file__,
        "python": sys.version.split()[0],
        "db": DBPATH,
        "chat_ref": sha12(CHAT),
        "git_head": os.environ.get("VMQ_HEAD"),
        "git_tree": os.environ.get("VMQ_TREE"),
        "files": {},
        "gates": {
            "evidence_bundle": bool(mca_gates.evidence_bundle_enabled()),
            "episodes": bool(mca_gates.episodes_enabled()),
            "tool_overview": hasattr(mca, "overview_bundle_slots"),
        },
        "config": {
            "effective": cfg.get("effective"),
            "defaults": cfg.get("defaults"),
            "pg": cfg.get("pg"),
            "env_flags": cfg.get("env_flags"),
            "model_identity": cfg.get("model_identity"),
            "chat_override_keys": sorted(
                (cfg.get("chat") or {}).keys())[:40],
            "chat_override_count": len(cfg.get("chat") or {}),
        },
    }
    for rel in WATCH:
        path = os.path.join(CLONE, rel)
        try:
            with open(path, "rb") as fh:
                identity["files"][rel] = hashlib.sha256(
                    fh.read()).hexdigest()[:16]
        except OSError:
            identity["files"][rel] = "absent"
    assert os.path.realpath(services.__file__).startswith(
        os.path.realpath(CLONE)), "IMPORT NOT FROM THE DEPLOYED TREE"
    print("IDENT " + json.dumps(identity, ensure_ascii=False), flush=True)

    db = DatabaseService(DBPATH)
    await db.initialize()
    llm = LLMClient(
        hot.get("models.llm_base_url", settings.LLM_BASE_URL),
        hot.get("keys.llm_api_key", settings.LLM_API_KEY),
        hot.get("models.llm_model_name", settings.LLM_MODEL_NAME),
        hot.get("models.embedding_model_name", settings.EMBEDDING_MODEL_NAME),
        embed_base_url=hot.get("models.embedding_base_url",
                               settings.EMBEDDING_BASE_URL),
        embed_api_key=hot.get("keys.embedding_api_key",
                              settings.EMBEDDING_API_KEY))
    memory = MemoryManager(db, llm, aliases=None)
    vec = {"ok": None, "reason": None}
    try:
        vec["ok"] = bool(await memory.initialize())
    except Exception as exc:                     # noqa: BLE001
        vec["ok"] = False
        vec["reason"] = type(exc).__name__
    vec["available"] = getattr(memory, "_vec_available", None)
    vec["off_reason"] = getattr(memory, "_vec_off_reason", None)
    print("VEC " + json.dumps(vec), flush=True)

    aliases, alias_mode = await _aliases()
    router = ToolRouter(ToolDeps(search=None, memory=memory, aliases=aliases,
                                 db=db))
    out = {
        "artifact_kind": "postdeploy_readonly_e2e",
        "contract": "M-04 person-overview tool path + O-04 route/versions",
        "identity": identity,
        "alias_mode": alias_mode,
        "vec": vec,
        "person_query_sha12": sha12("profile:" + name),
        "calls": {},
        "version_check": {},
        "errors": [],
    }
    profile_ctx = ToolContext(CHAT, "profile question", user_id=uid)
    for purpose in ("biography", "general", "identity"):
        try:
            with Spy() as spy, CountSpy(
                    memory, ["retrieve_fact_candidates"]) as mem_spy, \
                    CountSpy(llm, ["embed", "embed_once", "generate"]) as llm_spy:
                payload = await asyncio.wait_for(
                    router.dispatch(MEMORY_LOOKUP_TOOL_NAME,
                                    {"person": name, "purpose": purpose},
                                    profile_ctx), 240)
            entry = {
                "purpose": purpose,
                "retrieve_calls": len(spy.calls),
                "retrieve_include_overview": [
                    call["include_overview"] for call in spy.calls],
                "retrieve": [{k: v for k, v in call.items()
                              if k not in ("overview",)} for call in spy.calls],
                "overview": (spy.calls[0]["overview"] if spy.calls else None),
                "memory_calls": dict(mem_spy.calls),
                "llm_calls": dict(llm_spy.calls),
                "envelope": _envelope_view(payload),
                "seconds": round(sum(c["seconds"] for c in spy.calls), 2),
            }
            out["calls"][purpose] = entry
            overview = (spy.calls[0].get("overview") if spy.calls else None)
            if overview and overview.get("episode_refs"):
                out["version_check"][purpose] = version_check(
                    DBPATH, overview["episode_refs"],
                    overview.get("episode_versions") or [])
        except Exception as exc:                 # noqa: BLE001
            out["errors"].append({"purpose": purpose,
                                  "error": type(exc).__name__,
                                  "text": str(exc)[:300],
                                  "tb": traceback.format_exc()[-500:]})
        print("CALL_DONE %s" % purpose, flush=True)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("WROTE " + OUT + " bytes=%s" % os.path.getsize(OUT), flush=True)
    await db.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception:                            # noqa: BLE001
        traceback.print_exc()
        sys.exit(3)
