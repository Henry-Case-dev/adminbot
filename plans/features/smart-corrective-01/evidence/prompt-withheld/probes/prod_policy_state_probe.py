"""Read-only prod probe: deployed 2.58.202 resolver on real persisted state.

Runs on the production host with the DEPLOYED code and a READ-ONLY PG
connection. No writes, no Telegram, no provider calls.

It measures the SAME deployed service method the final canary probed
(``CheckupService._resolve_checkup_base_prompt``) in two process states:

  A) no startup wiring (what an ad-hoc separate process sees), and
  B) startup wiring completed (``prompt_release_policy.apply_release`` ->
     ``set_release_policy_active(True)``), which the bot journal proves for
     the running service (see [prompt_release] релиз применён).

Output contains machine values only: lengths, sha12, codes, a redacted chat
reference. No prompt bodies, no chat ids, no DSN.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/var/www/admin_bot")

for line in Path("/var/www/admin_bot/.env").read_text().splitlines():
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
CANARY_STORED_SHA12 = "31d175065461"


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def ref(value) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


class FakeHot:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values[key] if key in self.values else default

    def get_config_cache(self):
        return self


class FakeChatParams:
    def __init__(self, chat_id, root):
        self.roots = {int(chat_id): dict(root or {})}

    async def get_chat_params(self, chat_id):
        return dict(self.roots.get(int(chat_id), {}) or {})


async def snapshot(chat_id: int) -> dict:
    pr.set_release_policy_active(False)
    a_res = await pr.resolve_chat_speech_ex(KEY, CHECKUP_SYSTEM_PROMPT,
                                            chat_id=chat_id)
    a_text, a_source, a_meta = await checkup_service._resolve_checkup_base_prompt(
        chat_id)
    a_global, a_global_source, a_global_meta = (
        await checkup_service._resolve_checkup_base_prompt(None))

    pr.set_release_policy_active(True)
    b_res = await pr.resolve_chat_speech_ex(KEY, CHECKUP_SYSTEM_PROMPT,
                                            chat_id=chat_id)
    b_text, b_source, b_meta = await checkup_service._resolve_checkup_base_prompt(
        chat_id)
    b_global, b_global_source, b_global_meta = (
        await checkup_service._resolve_checkup_base_prompt(None))
    pr.set_release_policy_active(False)

    def pack(res, meta, source, text):
        return {
            "source": source,
            "withheld": bool(res.withheld),
            "provenance_reason": res.provenance_reason,
            "diagnostics": list(res.diagnostics),
            "withheld_class": res.withheld_class,
            "text_chars": len(text),
            "text_sha12": sha12(text),
            "text_hash16": hashlib.sha256(
                str(text).encode("utf-8")).hexdigest()[:16],
            "meta": meta,
        }

    return {
        "A_no_startup_wiring": pack(a_res, a_meta, a_source, a_text),
        "B_after_startup_wiring": pack(b_res, b_meta, b_source, b_text),
        "global_layer": {
            "A_no_startup_wiring": {
                "source": a_global_source,
                "chars": len(a_global),
                "sha12": sha12(a_global),
                "meta": a_global_meta,
            },
            "B_after_startup_wiring": {
                "source": b_global_source,
                "chars": len(b_global),
                "sha12": sha12(b_global),
                "meta": b_global_meta,
            },
        },
    }


async def main() -> dict:
    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        return {"error": "no_dsn"}
    con = await asyncpg.connect(
        dsn, server_settings={"default_transaction_read_only": "on"})
    try:
        global_row = await con.fetchrow(
            "SELECT value FROM bot_settings WHERE key = $1", KEY)
        profiles = await con.fetch(
            "SELECT chat_id, chat_params FROM chat_profiles "
            "WHERE chat_params -> 'overrides' ? $1", KEY)
        target = None
        for row in profiles:
            raw = row["chat_params"]
            data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            value = str((data.get("overrides") or {}).get(KEY) or "")
            if sha12(value) == CANARY_STORED_SHA12:
                target = (int(row["chat_id"]), data, value)
                break
        if target is None:
            return {"error": "target_chat_not_found",
                    "profiles_with_key": len(profiles)}

        chat_id, root, stored = target
        revisions = await con.fetch(
            "SELECT revision_id, origin, scope, retired, "
            "length(body) AS body_chars, content_sha12 "
            "FROM prompt_revisions WHERE block_id = $1 AND scope = 'chat' "
            "AND chat_id = $2 ORDER BY created_at DESC LIMIT 5",
            BLOCK, chat_id)
        activations = await con.fetch(
            "SELECT activation_id, revision_id, kind, outcome, detail_code, "
            "created_at::text AS created_at FROM prompt_activations "
            "WHERE block_id = $1 AND scope = 'chat' AND chat_id = $2 "
            "ORDER BY activation_id DESC LIMIT 3", BLOCK, chat_id)

        hot.set_config_cache(FakeHot(
            {KEY: str(global_row["value"])} if global_row else {}))
        chat_params.set_chat_params_cache(FakeChatParams(chat_id, root))

        factory = pr.factory_text(BLOCK)
        out = {
            "deployed": {"app_version": os.environ.get("APP_VERSION", ""),
                         "factory_chars": len(factory),
                         "factory_sha12": sha12(factory)},
            "stored": {"chars": len(stored), "sha12": sha12(stored)},
            "global_row_present": bool(global_row),
            "global_value_chars": (len(str(global_row["value"]))
                                   if global_row else 0),
            "global_value_sha12": (sha12(str(global_row["value"]))
                                   if global_row else ""),
            "chat_ref": ref(chat_id),
            "revisions": [
                {"revision_id": r["revision_id"][:20], "origin": r["origin"],
                 "retired": bool(r["retired"]),
                 "body_chars": int(r["body_chars"] or 0),
                 "content_sha12": r["content_sha12"]}
                for r in revisions],
            "activations": [
                {"activation_id": int(a["activation_id"]),
                 "revision_id": a["revision_id"][:20],
                 "kind": a["kind"], "outcome": a["outcome"],
                 "detail_code": a["detail_code"],
                 "created_at": a["created_at"]}
                for a in activations],
            "resolver": await snapshot(chat_id),
        }
        return out
    finally:
        await con.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=1))
