"""Local repro: same persisted chat edition, two process policy states.

Uses the deployed train code (0beed63d) with an in-memory config/chat-params
double. No prod data. Proves the mechanism that produced the canary values.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys

ROOT = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-6fc68e04"
sys.path.insert(0, ROOT)

from services import chat_params  # noqa: E402
from services import checkup_service  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import prompt_registry as pr  # noqa: E402
from services.checkup_prompts import CHECKUP_SYSTEM_PROMPT  # noqa: E402

KEY = "prompts.checkup_system_prompt"
BLOCK = "checkup.base.system"
CHAT_ID = 424242

# 12 469 chars: same size as the owner edition, synthetic content.
MANUAL = ("ВЛАДЕЛЬЧЕСКАЯ РЕДАКЦИЯ ЧЕКAПА. " * 500)[:12469]
assert len(MANUAL) == 12469, len(MANUAL)


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values[key] if key in self.values else default

    def get_config_cache(self):
        return self


class FakeChatParams:
    def __init__(self, chat_id, overrides):
        self.roots = {int(chat_id): {"overrides": dict(overrides)}}

    async def get_chat_params(self, chat_id):
        return dict(self.roots.get(int(chat_id), {}) or {})


async def main() -> dict:
    factory = pr.factory_text(BLOCK)
    hot.set_config_cache(FakeHot({}))          # no global layer value
    chat_params.set_chat_params_cache(
        FakeChatParams(CHAT_ID, {KEY: MANUAL}))

    out = {
        "deployed_factory_chars": len(factory),
        "manual_chars": len(MANUAL),
        "manual_sha12": sha12(MANUAL),
        "withholding_required": pr.withholding_required(pr.block(BLOCK)),
    }

    # (A) out-of-process reader: startup wiring never ran (canary probe).
    pr.set_release_policy_active(False)
    resolved = await pr.resolve_chat_speech_ex(KEY, CHECKUP_SYSTEM_PROMPT,
                                               chat_id=CHAT_ID)
    text, source, meta = await checkup_service._resolve_checkup_base_prompt(
        CHAT_ID)
    out["A_no_startup_wiring"] = {
        "release_policy_active": pr.release_policy_active(),
        "source": resolved.source,
        "withheld": bool(resolved.withheld),
        "provenance_reason": resolved.provenance_reason,
        "text_chars": len(resolved.text),
        "text_sha12": sha12(resolved.text),
        "service_meta": meta,
        "service_source": source,
        "service_text_chars": len(text),
    }

    # (B) bot process: startup `apply_release` completed (prod journal line).
    pr.set_release_policy_active(True)
    resolved_b = await pr.resolve_chat_speech_ex(
        KEY, CHECKUP_SYSTEM_PROMPT, chat_id=CHAT_ID)
    text_b, source_b, meta_b = await checkup_service._resolve_checkup_base_prompt(
        CHAT_ID)
    out["B_after_startup_wiring"] = {
        "release_policy_active": pr.release_policy_active(),
        "source": resolved_b.source,
        "withheld": bool(resolved_b.withheld),
        "provenance_reason": resolved_b.provenance_reason,
        "diagnostics": list(resolved_b.diagnostics),
        "text_chars": len(resolved_b.text),
        "text_sha12": sha12(resolved_b.text),
        "service_meta": meta_b,
        "service_source": source_b,
        "service_text_chars": len(text_b),
    }
    pr.set_release_policy_active(False)
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=1))
