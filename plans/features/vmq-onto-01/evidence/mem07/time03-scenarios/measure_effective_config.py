# -*- coding: utf-8 -*-
"""Read-only measurement of the effective GraphRAG configuration.

Run this from the production environment (the service venv, production .env
loaded) or from a worktree that has the same env. It reads:

  * config.settings.settings (env/factory layer);
  * bot_settings rows for flags.graph_rag_enabled and
    limits.graph_rag_facts_limit via a SELECT-only PostgreSQL connection.

It never writes to PostgreSQL and never changes settings. The output JSON is
the provenance file accepted by mem07.py --effective-config.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

SCHEMA = "vmq-mem07-effective/1"
KEYS = ("flags.graph_rag_enabled", "limits.graph_rag_facts_limit")


def _code_root_candidates(explicit: str | None = None):
    if explicit:
        yield Path(explicit).resolve()
    here = Path(__file__).resolve()
    yield here.parent
    yield from here.parent.parents


def ensure_code_root(explicit: str | None = None) -> Path:
    """Put the product worktree root on sys.path before importing config.

    Python adds the *script directory* to sys.path, not the caller's cwd, so a
    documented invocation from the worktree root would otherwise fail with
    ``ModuleNotFoundError: config``. The root is found deterministically by
    walking up from this file until ``config/settings.py`` and ``services/``
    exist, or taken from ``--code-root`` and verified.
    """
    for candidate in _code_root_candidates(explicit):
        if (candidate / "config" / "settings.py").is_file() and \
                (candidate / "services").is_dir():
            root = str(candidate)
            if root not in sys.path:
                sys.path.insert(0, root)
            return candidate
    if explicit:
        raise RuntimeError("code_root_invalid:%s" % explicit)
    raise RuntimeError("code_root_not_found")



def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_value(value):
    if isinstance(value, (bool, int, float)):
        return value
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def tool_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


async def measure(settings_only: bool = False,
                  command: str | None = None,
                  code_root: str | None = None) -> dict:
    ensure_code_root(code_root)
    from config.settings import settings

    settings_instance = {
        "flags.graph_rag_enabled": bool(settings.GRAPH_RAG_ENABLED),
        "limits.graph_rag_facts_limit": int(settings.GRAPH_RAG_FACTS_LIMIT),
    }
    dsn = os.getenv("POSTGRES_DSN")
    db_values = {}
    pg_status = "skipped_settings_only" if settings_only else (
        "dsn_absent" if not dsn else "not_queried")
    hot_measured = False
    if not settings_only and dsn:
        try:
            import asyncpg
            conn = await asyncpg.connect(dsn, timeout=10)
            try:
                rows = await conn.fetch(
                    "SELECT key, value FROM bot_settings "
                    "WHERE key = ANY($1::text[])", list(KEYS))
                for row in rows:
                    db_values[str(row["key"])] = _json_value(row["value"])
                pg_status = "read_only_query_ok"
                hot_measured = True
            finally:
                await conn.close()
        except Exception as exc:
            pg_status = "read_only_query_error:%s" % type(exc).__name__
    effective = {}
    sources = {}
    for key in KEYS:
        if key in db_values and db_values[key] is not None:
            effective[key] = db_values[key]
            sources[key] = "db_hot_config"
        else:
            effective[key] = settings_instance[key]
            sources[key] = "settings_instance"
    effective["flags.graph_rag_enabled"] = _bool(
        effective["flags.graph_rag_enabled"], settings_instance["flags.graph_rag_enabled"])
    effective["limits.graph_rag_facts_limit"] = _int(
        effective["limits.graph_rag_facts_limit"],
        settings_instance["limits.graph_rag_facts_limit"])
    production_ready = bool(hot_measured or pg_status == "dsn_absent")
    return {
        "schema": SCHEMA,
        "tool": "measure_effective_config.py",
        "tool_sha256": tool_sha256(),
        "command": command or " ".join(sys.argv),
        "measured_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "read_only": True,
        "settings_only": bool(settings_only),
        "production_ready": production_ready,
        "postgres_query": "SELECT key, value FROM bot_settings WHERE key = ANY($1::text[])",
        "pg_status": pg_status,
        "hot_config_measured": bool(hot_measured),
        "settings_instance": settings_instance,
        "db_hot_config": db_values,
        "sources": sources,
        "effective": effective,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only effective GraphRAG config measurement")
    parser.add_argument("--out", required=True)
    parser.add_argument("--settings-only", action="store_true",
                        help="skip PostgreSQL; for local fixture tests only")
    parser.add_argument("--code-root", default="",
                        help="product worktree root containing config/ and services/")
    args = parser.parse_args(argv)
    try:
        ensure_code_root(args.code_root or None)
    except Exception as exc:
        print(json.dumps({"status": "not_executed",
                          "reason": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    payload = asyncio.run(measure(settings_only=args.settings_only,
                                  code_root=args.code_root or None))
    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": args.out,
                      "effective": payload["effective"],
                      "sources": payload["sources"],
                      "pg_status": payload["pg_status"],
                      "hot_config_measured": payload["hot_config_measured"],
                      "production_ready": payload["production_ready"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())