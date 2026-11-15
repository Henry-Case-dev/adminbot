# -*- coding: utf-8 -*-
"""Read-only production snapshot for the 2.58.203 deploy (pre/post compare).

Runs on the production host with the DEPLOYED code. No writes, no provider
calls, no Telegram. Prints a JSON document with machine values only: lengths,
digests, hashes, codes; chat ids appear only through a hashed reference.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP = "/var/www/admin_bot"
sys.path.insert(0, APP)

for line in Path(APP, ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import asyncpg  # noqa: E402

BLOCK = "checkup.base.system"
KEY = "prompts.checkup_system_prompt"
SPECIFIC = [
    "flags.budgets_enabled",
    "flags.factcheck_pipeline_v2",
    "models.llm_model_name",
    "models.llm_base_url",
    KEY,
    "prompts.factcheck_subject_system_prompt",
]


def sha256(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def sha12(text: str) -> str:
    return sha256(text)[:12]


def ref(value) -> str:
    return sha12(str(value))


def digest(pairs) -> str:
    h = hashlib.sha256()
    for k, v in sorted(pairs):
        h.update(str(k).encode("utf-8"))
        h.update(b"\x00")
        h.update(str(v).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def app_version() -> str:
    src = Path(APP, "config", "settings.py").read_text(encoding="utf-8", errors="replace")
    for line in src.splitlines():
        if line.startswith("APP_VERSION"):
            return line.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    return ""


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", APP, *args], capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception as exc:                       # pragma: no cover
        return f"ERR:{exc.__class__.__name__}"


def health(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return {"code": resp.status, "body": resp.read(400).decode("utf-8", "replace")}
    except Exception as exc:
        return {"code": None, "error": exc.__class__.__name__}


def load_json(raw):
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


async def main() -> dict:
    dsn = os.environ.get("POSTGRES_DSN")
    out: dict = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "app_version": app_version(),
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "dirty_tracked": len([x for x in git("status", "--porcelain",
                                             "--untracked-files=no").splitlines() if x.strip()]),
        "health_local": health("http://127.0.0.1:8000/healthz"),
        "health_public": health("https://admin-bot.duckdns.org/healthz"),
    }

    # ── SQLite schema ──────────────────────────────────────────────────────
    try:
        con = sqlite3.connect(f"file:{APP}/local_database.db?mode=ro", uri=True,
                              timeout=30)
        con.execute("PRAGMA query_only=1")
        out["sqlite"] = {
            "user_version": con.execute("PRAGMA user_version").fetchone()[0],
            "tables": con.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
        }
        try:
            out["sqlite"]["schema_migrations_rows"] = con.execute(
                "SELECT count(*) FROM schema_migrations").fetchone()[0]
            out["sqlite"]["schema_migrations_max"] = con.execute(
                "SELECT max(version) FROM schema_migrations").fetchone()[0]
        except Exception as exc:
            out["sqlite"]["schema_migrations_error"] = exc.__class__.__name__
        con.close()
    except Exception as exc:
        out["sqlite"] = {"error": exc.__class__.__name__}

    if not dsn:
        out["error"] = "no_dsn"
        return out

    con = await asyncpg.connect(
        dsn, server_settings={"default_transaction_read_only": "on"})
    try:
        # ── bot_settings ───────────────────────────────────────────────────
        rows = await con.fetch(
            "SELECT key, value::text AS val, updated_at::text AS upd "
            "FROM bot_settings ORDER BY key")
        out["settings"] = {
            "count": len(rows),
            "digest": digest((r["key"], r["val"]) for r in rows),
            "digest_excluding_checkup": digest(
                (r["key"], r["val"]) for r in rows if r["key"] != KEY),
            "specific": {},
        }
        by_key = {r["key"]: r for r in rows}
        for key in SPECIFIC:
            row = by_key.get(key)
            if row is None:
                out["settings"]["specific"][key] = {"present": False}
                continue
            item = {"present": True, "chars": len(str(row["val"])),
                    "sha256": sha256(str(row["val"])), "updated_at": row["upd"]}
            if key.startswith("prompts."):
                item["contains_betterstack"] = "betterstack" in str(row["val"]).lower()
                item["contains_401"] = "401" in str(row["val"])
            out["settings"]["specific"][key] = item

        # ── chat_profiles ─────────────────────────────────────────────────
        profs = await con.fetch(
            "SELECT chat_id, chat_params::text AS params FROM chat_profiles "
            "ORDER BY chat_id")
        chats = []
        for idx, row in enumerate(profs, start=1):
            data = load_json(row["params"]) or {}
            overrides = data.get("overrides") or {}
            value = overrides.get(KEY)
            chats.append({
                "alias": f"CHAT_C{idx}",
                "ref": ref(row["chat_id"]),
                "overrides_count": len(overrides),
                "checkup_override": ({"present": False} if value is None else
                                     {"present": True, "chars": len(str(value)),
                                      "sha256": sha256(str(value))}),
            })
        out["profiles"] = {
            "count": len(profs),
            "digest": digest((r["chat_id"], r["params"]) for r in profs),
            "chats": chats,
        }

        # ── prompt journal (checkup.base.system) ──────────────────────────
        revs = await con.fetch(
            "SELECT revision_id, origin, scope, chat_id, retired, "
            "       factory_revision, reason, "
            "       length(body) AS chars, content_sha12, created_at::text AS created "
            "FROM prompt_revisions WHERE block_id = $1 "
            "ORDER BY created_at DESC LIMIT 8", BLOCK)
        acts = await con.fetch(
            "SELECT activation_id, revision_id, scope, chat_id, kind, outcome, "
            "       detail_code, release_id, factory_revision_applied, "
            "       created_at::text AS created "
            "FROM prompt_activations WHERE block_id = $1 "
            "ORDER BY activation_id DESC LIMIT 10", BLOCK)
        man = await con.fetchrow(
            "SELECT revision_id, origin, scope, retired, factory_revision, reason, "
            "       length(body) AS chars, "
            "       body, created_at::text AS created "
            "FROM prompt_revisions WHERE revision_id = 'rev:d31300ef35a0'")
        out["prompts"] = {
            "block": BLOCK,
            "global_row": {
                "chars": len(str(by_key[KEY]["val"])) if KEY in by_key else 0,
                "sha256": sha256(str(by_key[KEY]["val"])) if KEY in by_key else "",
            },
            "revisions": [{
                "revision_id": r["revision_id"][:22], "origin": r["origin"],
                "scope": r["scope"], "chat_ref": ref(r["chat_id"]) if r["chat_id"] else "",
                "retired": bool(r["retired"]), "factory_revision": r["factory_revision"],
                "reason": r["reason"],
                "chars": int(r["chars"] or 0), "sha12": r["content_sha12"],
                "created": r["created"],
            } for r in revs],
            "activations": [{
                "activation_id": int(a["activation_id"]),
                "revision_id": (a["revision_id"] or "")[:22],
                "scope": a["scope"],
                "chat_ref": ref(a["chat_id"]) if a["chat_id"] else "",
                "kind": a["kind"], "outcome": a["outcome"],
                "detail_code": a["detail_code"], "release_id": a["release_id"],
                "factory_revision_applied": a["factory_revision_applied"],
                "created": a["created"],
            } for a in acts],
            "manual_revision": ({
                "revision_id": man["revision_id"], "origin": man["origin"],
                "scope": man["scope"], "retired": bool(man["retired"]),
                "factory_revision": man["factory_revision"],
                "reason": man["reason"],
                "chars": int(man["chars"] or 0),
                "sha256": sha256(man["body"]), "created": man["created"],
            } if man else {"present": False}),
        }

        # ── effective budgets / chain limits (documented precedence) ──────
        # chat override → global bot_settings row → factory default(settings).
        # Measured from the stored layers (no process cache priming) and the
        # env-backed chain limits through the deployed resolver.
        from config.settings import settings as app_settings
        from services import tool_loop

        factory_default = bool(getattr(app_settings, "BUDGETS_ENABLED", True))
        try:
            global_raw = str(by_key["flags.budgets_enabled"]["val"]).strip().strip('"')
            global_value = global_raw.lower() in ("true", "1", "yes", "on")
            global_source = "global"
        except Exception:
            global_value, global_source = factory_default, "default"

        def chat_budget(idx, data):
            overrides = (data or {}).get("overrides") or {}
            raw = overrides.get("flags.budgets_enabled")
            if raw is None:
                return {"alias": f"CHAT_C{idx}", "value": global_value,
                        "source": global_source, "chat_override": False}
            value = str(raw).strip().strip('"').lower() in ("true", "1", "yes", "on")
            return {"alias": f"CHAT_C{idx}", "value": value, "source": "chat",
                    "chat_override": True}

        chat_budget_rows = []
        for idx, row in enumerate(profs, start=1):
            chat_budget_rows.append(chat_budget(idx, load_json(row["params"]) or {}))

        glim = tool_loop.resolve_chain_limits(budgets_enabled=global_value)
        out["budgets"] = {
            "global_value": global_value,
            "global_source": global_source,
            "factory_default": factory_default,
            "chat_override_present": any(c["chat_override"] for c in chat_budget_rows),
            "chats": chat_budget_rows,
            "global_limits": glim.as_meta(),
            "per_chat_limits": [dict(tool_loop.resolve_chain_limits(
                budgets_enabled=c["value"]).as_meta(), alias=c["alias"])
                for c in chat_budget_rows],
        }

        # ── capacity ─────────────────────────────────────────────────────
        from services import model_capacity

        model = str(by_key["models.llm_model_name"]["val"]).strip('"') if "models.llm_model_name" in by_key else ""
        base_url = str(by_key["models.llm_base_url"]["val"]).strip('"') if "models.llm_base_url" in by_key else ""
        try:
            cap = await model_capacity.resolve_capacity(base_url or "(default)", model)
            out["capacity"] = {
                "model": cap.model,
                "base_url_host": base_url.split("//")[-1].split("/")[0] if base_url else "",
                "window": cap.effective_context_window,
                "max_output": cap.max_output_tokens,
                "declared": cap.declared_context_window,
                "runtime": cap.runtime_context_window,
                "source": cap.source, "confidence": cap.confidence,
                "fallback_used": cap.fallback_used,
                "override_value": cap.override_value,
                "proven_limit": cap.proven_limit,
            }
        except Exception as exc:
            out["capacity"] = {"error": exc.__class__.__name__}
        out["factory_code"] = {}
        try:
            from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT
            out["factory_code"] = {"chars": len(CHECKUP_SYSTEM_PROMPT),
                                   "sha256": sha256(CHECKUP_SYSTEM_PROMPT)}
        except Exception as exc:
            out["factory_code"] = {"error": exc.__class__.__name__}
    finally:
        await con.close()
    return out


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/snapshot.json"
    data = asyncio.run(main())
    Path(dest).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1))
