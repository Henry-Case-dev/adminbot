# -*- coding: utf-8 -*-
"""Bot-like provenance proof on the deployed 2.58.203.

Read-only: PG connection in a read-only transaction, deployed code, no writes,
no provider calls, no Telegram. The resolver runs in the SAME process state as
the bot after its normal startup wiring (``apply_release`` ->
``set_release_policy_active(True)``) with the runtime hot/chat caches primed
from the persisted layers, which is what the running service uses.

Outputs machine values only: lengths, sha, layer codes, hashed chat refs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
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

from services import chat_params  # noqa: E402
from services import checkup_service  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT  # noqa: E402

KEY = "prompts.checkup_system_prompt"
BLOCK = "checkup.base.system"
MANUAL_SHA12 = "31d175065461"


def sha256(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def sha12(text: str) -> str:
    return sha256(text)[:12]


def ref(value) -> str:
    return sha12(str(value))


def decoded(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


class FakeHot:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values[key] if key in self.values else default

    def get_config_cache(self):
        return self

    def get_updated_at(self, key):
        return ""


class FakeChatParams:
    def __init__(self, roots):
        self.roots = {int(k): dict(v or {}) for k, v in roots.items()}

    async def get_chat_params(self, chat_id):
        return dict(self.roots.get(int(chat_id), {}) or {})


async def probe(chat_id: int, label: str) -> dict:
    resolved = await pr.resolve_chat_speech_ex(KEY, CHECKUP_SYSTEM_PROMPT,
                                              chat_id=int(chat_id))
    text, source, meta = await checkup_service._resolve_checkup_base_prompt(
        int(chat_id))
    lowered = str(text).lower()
    return {
        "target": label,
        "chat_ref": ref(chat_id),
        "prompt_layer": source,
        "meta_prompt_layer": meta.get("prompt_layer"),
        "withheld": bool(resolved.withheld),
        "meta_withheld": bool(meta.get("prompt_withheld")),
        "provenance_reason": str(resolved.provenance_reason or ""),
        "meta_provenance_reason": str(meta.get("prompt_provenance_reason") or ""),
        "text_chars": len(text),
        "text_sha12": sha12(text),
        "text_sha256": sha256(text),
        "contains_betterstack": "betterstack" in lowered,
        "contains_401": "401" in str(text),
        "diagnostics": list(getattr(resolved, "diagnostics", []) or []),
        "withheld_class": getattr(resolved, "withheld_class", None),
    }


async def main() -> dict:
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        return {"error": "no_dsn"}
    con = await asyncpg.connect(
        dsn, server_settings={"default_transaction_read_only": "on"})
    try:
        rows = await con.fetch(
            "SELECT key, value::text AS val FROM bot_settings")
        settings = {}
        for r in rows:
            settings[r["key"]] = decoded(r["val"])
        raw_row = await con.fetchval(
            "SELECT value::text FROM bot_settings WHERE key = $1", KEY)
        body = decoded(raw_row)
        global_body = body if isinstance(body, str) else str(body)

        active_global = await con.fetchrow(
            "SELECT a.activation_id, a.revision_id, a.detail_code, a.outcome, "
            "       a.release_id, a.factory_revision_applied, "
            "       length(r.body) AS chars, r.content_sha12 "
            "FROM prompt_activations a "
            "JOIN prompt_revisions r ON r.revision_id = a.revision_id "
            "WHERE a.block_id = $1 AND a.scope = 'global' "
            "ORDER BY a.activation_id DESC LIMIT 1", BLOCK)

        manual = await con.fetchrow(
            "SELECT revision_id, origin, scope, chat_id, retired, "
            "       length(body) AS chars, body "
            "FROM prompt_revisions WHERE revision_id = 'rev:d31300ef35a0'")

        profs = await con.fetch(
            "SELECT chat_id, chat_params::text AS params FROM chat_profiles "
            "ORDER BY chat_id")
        roots = {}
        meta_rows = []
        for idx, row in enumerate(profs, start=1):
            data = decoded(row["params"]) or {}
            roots[int(row["chat_id"])] = data
            overrides = data.get("overrides") or {}
            value = overrides.get(KEY)
            meta_rows.append({
                "alias": f"CHAT_C{idx}", "ref": ref(row["chat_id"]),
                "overrides_count": len(overrides),
                "checkup_override": (None if value is None else {
                    "chars": len(str(value)), "sha12": sha12(str(value))}),
            })

        hot.set_config_cache(FakeHot(settings))
        chat_params.set_chat_params_cache(FakeChatParams(roots))
        pr.set_release_policy_active(True)          # normal startup wiring

        manual_chat = None
        for row in meta_rows:
            ov = row["checkup_override"]
            if ov and ov["sha12"] == MANUAL_SHA12:
                manual_chat = next(int(p["chat_id"]) for p in profs
                                   if ref(p["chat_id"]) == row["ref"])
                manual_alias = row["alias"]
                break
        if manual_chat is None:
            return {"error": "manual_chat_not_found", "chats": meta_rows}

        no_override_chat = None
        for row in meta_rows:
            if row["checkup_override"] is None:
                no_override_chat = next(int(p["chat_id"]) for p in profs
                                        if ref(p["chat_id"]) == row["ref"])
                no_override_alias = row["alias"]
                break

        out = {
            "deployed_app_version": (Path(APP, "config", "settings.py")
                                     .read_text(errors="replace")
                                     .split('APP_VERSION = "')[1].split('"')[0]),
            "factory_code": {"chars": len(CHECKUP_SYSTEM_PROMPT),
                             "sha256": sha256(CHECKUP_SYSTEM_PROMPT)},
            "global_layer": {
                "raw_value_chars": len(raw_row or ""),
                "body_chars": len(global_body),
                "body_sha12": sha12(global_body),
                "body_sha256": sha256(global_body),
                "contains_betterstack": "betterstack" in global_body.lower(),
                "contains_401": "401" in global_body,
                "active_revision": ({
                    "activation_id": int(active_global["activation_id"]),
                    "revision_id": active_global["revision_id"],
                    "detail_code": active_global["detail_code"],
                    "outcome": active_global["outcome"],
                    "release_id": active_global["release_id"],
                    "factory_revision_applied":
                        active_global["factory_revision_applied"],
                    "chars": int(active_global["chars"] or 0),
                    "sha12": active_global["content_sha12"],
                } if active_global else None),
            },
            "manual_revision": ({
                "revision_id": manual["revision_id"], "origin": manual["origin"],
                "scope": manual["scope"], "retired": bool(manual["retired"]),
                "chars": int(manual["chars"] or 0),
                "sha12": sha12(manual["body"]),
            } if manual else None),
            "chats": meta_rows,
            "manual_chat": {"alias": manual_alias, "ref": ref(manual_chat)},
            "no_override_chat": ({"alias": no_override_alias,
                                  "ref": ref(no_override_chat)}
                                 if no_override_chat is not None else None),
            "resolver": {
                "release_policy_active": True,
                "manual_chat": await probe(manual_chat, "manual_chat"),
                "no_override_chat": (await probe(no_override_chat,
                                                 "no_override_chat")
                                     if no_override_chat is not None else None),
            },
        }
        return out
    finally:
        await con.close()


if __name__ == "__main__":
    data = asyncio.run(main())
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prov203.json"
    Path(dest).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1))
