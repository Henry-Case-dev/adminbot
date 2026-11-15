# -*- coding: utf-8 -*-
"""Read-only snapshot of the acceptance-critical effective configuration.

Reads the SAME keys the measurement depends on:
  * global overrides from bot_settings (Postgres, SELECT only);
  * the per-chat overrides for the measured chat (chat_profiles.chat_params);
  * the Settings defaults from the deployed tree.

No secrets are requested. Output: cfg.json {defaults, global, chat, effective}.
`effective` = chat override -> global override -> settings default, which is
the precedence the product uses (chat_params.get_chat_param -> hot.get ->
Settings).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

APP = "/var/www/admin_bot"
OUT = os.environ.get("VMQ_CFG", "/root/vmq2/measure/cfg.json")
CHAT = -1002661910336

os.chdir(APP)
sys.path.insert(0, APP)

KEYS = [
    "flags.graph_rag_enabled",
    "flags.chat_rag_rerank_enabled",
    "flags.memory_communities_enabled",
    "flags.memory_identity_enabled",
    "flags.memory_attribution_enabled",
    "limits.graph_rag_facts_limit",
    "limits.graph_rag_context_max_chars",
    "limits.chat_rag_dedup_overlap_ratio",
    "limits.chat_episode_max_count",
    "limits.chat_episode_max_messages",
    "limits.chat_episode_gap_seconds",
    "limits.dig_max_snippets",
    "limits.dig_max_symbols",
    # VMQ-MEM/TIME Slice A parity run: embedding route identity. Only
    # non-secret routing keys; API keys are never requested or written.
    "models.embedding_base_url",
    "models.embedding_dim",
    "models.embedding_model_name",
    "keys.embedding_quota_group_labels",
]

SETTINGS_ATTR = {
    "flags.graph_rag_enabled": "GRAPH_RAG_ENABLED",
    "flags.chat_rag_rerank_enabled": "CHAT_RAG_RERANK_ENABLED",
    "limits.graph_rag_facts_limit": "GRAPH_RAG_FACTS_LIMIT",
    "limits.graph_rag_context_max_chars": "GRAPH_RAG_CONTEXT_MAX_CHARS",
    "limits.chat_episode_max_count": "CHAT_EPISODE_MAX_COUNT",
    "limits.chat_episode_max_messages": "CHAT_EPISODE_MAX_MESSAGES",
    "limits.chat_episode_gap_seconds": "CHAT_EPISODE_GAP_SECONDS",
    "limits.dig_max_snippets": "DIG_MAX_SNIPPETS",
    "limits.dig_max_symbols": "DIG_MAX_SYMBOLS",
    "models.embedding_base_url": "EMBEDDING_BASE_URL",
    "models.embedding_dim": "EMBEDDING_DIM",
    "models.embedding_model_name": "EMBEDDING_MODEL_NAME",
}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(APP) / ".env", override=False)
    except Exception:                  # noqa: BLE001
        pass


def main() -> int:
    _load_env()
    from config.settings import settings

    defaults = {}
    for key, attr in SETTINGS_ATTR.items():
        defaults[key] = getattr(settings, attr, None)

    env_flags = {
        name: os.getenv(name)
        for name in ("MCA_RETRIEVAL_CONTEXT_ENABLED",
                     "MCA_EVIDENCE_BUNDLE_ENABLED", "MCA_EPISODES_ENABLED")
    }
    model_identity = {
        "llm_model_name": getattr(settings, "LLM_MODEL_NAME", None),
        "embedding_model_name": getattr(settings, "EMBEDDING_MODEL_NAME", None),
        "llm_base_url_host": _host(getattr(settings, "LLM_BASE_URL", "")),
        "embedding_base_url_host": _host(
            getattr(settings, "EMBEDDING_BASE_URL", "")),
    }
    out = {"defaults": defaults, "env_flags": env_flags,
           "model_identity": model_identity, "global": {}, "chat": {},
           "effective": dict(defaults), "pg": "unknown"}

    dsn = os.getenv("POSTGRES_DSN") or getattr(settings, "POSTGRES_DSN", "")
    if not dsn:
        out["pg"] = "no_dsn"
        _write(out)
        return 0
    try:
        import asyncpg

        async def go() -> None:
            con = await asyncpg.connect(dsn=dsn, timeout=12)
            try:
                rows = await con.fetch(
                    "SELECT key, value FROM bot_settings "
                    "WHERE key = ANY($1::text[])", KEYS)
                out["global"] = {r["key"]: r["value"] for r in rows}
                prof = await con.fetchrow(
                    "SELECT chat_params FROM chat_profiles WHERE chat_id=$1",
                    CHAT)
                cp = prof["chat_params"] if prof else None
                if isinstance(cp, str):
                    try:
                        cp = json.loads(cp)
                    except Exception:      # noqa: BLE001
                        cp = None
                out["chat"] = (cp or {}).get("overrides") or {}
                out["chat_gates"] = (cp or {}).get("gates") or {}
            finally:
                await con.close()

        asyncio.run(go())
        out["pg"] = "ok"
    except Exception as exc:           # noqa: BLE001
        out["pg"] = "failed:%s" % type(exc).__name__
    for key in KEYS:
        if key in (out["chat"] or {}):
            out["effective"][key] = out["chat"][key]
        elif key in (out["global"] or {}):
            out["effective"][key] = out["global"][key]
    _write(out)
    return 0


def _host(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(str(url or "")).hostname or ""
    except Exception:                  # noqa: BLE001
        return ""


def _write(out: dict) -> None:
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("CFG_OK pg=%s effective=%s" % (out["pg"],
                                         json.dumps(out["effective"],
                                                    ensure_ascii=False)))


if __name__ == "__main__":
    sys.exit(main())
