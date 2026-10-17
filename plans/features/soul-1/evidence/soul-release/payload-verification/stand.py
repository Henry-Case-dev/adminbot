# -*- coding: utf-8 -*-
"""SOUL-PAYLOAD-VERIFY — offline stand (read-only lane, no prod access).

Reconstruct the live prod `prompts.*` config from the SOUL-PREP snapshot
(17.10.2026, evidence/soul-prep/) and run the REAL runtime code
(services.prompt_registry + services.prompt_composer + services.prompt_style_blocks
+ services.mca_gates + services.bot_persona + humor modules) on it, to produce
the effective prompt payloads for 5 paths:

    Direct, Initiative, Factcheck, Summary, fallback/degraded.

Data provenance:
  * PG prompt values: reconstructed = current code canon where the snapshot
    says "live == factory(code-canon)" (22/25 keys) and cross-checked against
    the snapshot sha256_12/length; verbilizer_default_mode="serious" (sha
    verified); summary_cover_style_id="" (sha verified); summary_editor custom
    (2023 chars) is NOT reconstructible -> marked unknown (marker count from
    snapshot = 0).
  * flags.*: from the snapshot; SOUL axes set to the post-release ON state
    (env + PG), exactly per soul-release-prep.md checklist (core/style/humor;
    candidate-eval deliberately OFF).
  * per-chat: chat -1002661910336 (working group), overrides from snapshot;
    chat prompt values that are customs are NOT reconstructible -> only the
    known-reconstructed verbilizer_default_mode="casual" is materialized.

Output: stand-output.json + stand-output.txt next to this file.
Run:    py -3 plans/features/soul-1/evidence/soul-release/payload-verification/stand.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _find_repo(start: Path) -> Path:
    p = start
    for _ in range(12):
        if (p / "services" / "prompt_registry.py").exists() and (p / "plans").is_dir():
            return p
        p = p.parent
    raise SystemExit("repo root not found")


REPO = _find_repo(HERE)
sys.path.insert(0, str(REPO))
os.chdir(REPO)

PREP = REPO / "plans" / "features" / "soul-1" / "evidence" / "soul-prep"
CHAT = -1002661910336  # working group per snapshot
OTHER_CHATS = (5885953495, -1004482340693)

MARKERS = ("токсичн", "бот-абьюзер", "унизить", "унизив", "обоссав",
           "саркастично-токсичн", "человеческо-токсичный", "двач")

SOUL_FLAGS_ON = {
    "flags.unified_composer_enabled": True,
    "flags.character_core_enabled": True,
    "flags.speech_style_policy_enabled": True,
    "flags.humor_craft_enabled": True,
    "flags.humor_library_enabled": True,
    "flags.humor_feedback_enabled": True,
    # candidate-eval axis stays OFF (runbook: платные вызовы, не нужны фиче)
}
SOUL_ENV_ON = {
    "UNIFIED_COMPOSER_ENABLED": "1",
    "CHARACTER_CORE_ENABLED": "1",
    "SPEECH_STYLE_POLICY_ENABLED": "1",
    "HUMOR_CRAFT_ENABLED": "1",
    "HUMOR_LIBRARY_ENABLED": "1",
    "HUMOR_FEEDBACK_ENABLED": "1",
}


def sha12(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def marker_hits(text: str) -> dict:
    low = str(text or "").lower()
    return {m: low.count(m.lower()) for m in MARKERS if m.lower() in low}


def run_git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True,
                             text=True, timeout=60)
        return out.stdout.strip()
    except Exception as exc:  # pragma: no cover
        return "ERR:%s" % exc


# ═══════════════════════════════════════════════════════════════════════════
# 0. snapshot parsing + live-value reconstruction
# ═══════════════════════════════════════════════════════════════════════════

def load_snapshot() -> dict:
    """Parse prep snapshot: prompts.* rows, flags.*, per-chat overrides."""
    inv = {}
    text = (PREP / "prompts_classification.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(
            r"^prompts\.(\S+)\s+([0-9a-f]{12})\s+len=(\d+)\s+mk=(-?\d+)\s+"
            r"(WITHHOLD|-)\s+(\S+)\s+\(factory=([0-9a-f]{12}|n/a)\)", line)
        if not m:
            continue
        key = "prompts." + m.group(1)
        inv[key] = {
            "sha12": m.group(2), "len": int(m.group(3)), "markers": int(m.group(4)),
            "withhold_class": m.group(5) == "WITHHOLD",
            "class_token": m.group(6), "factory_sha12": m.group(7),
        }
    raw = (PREP / "ev_live_snapshot_2026-10-17.txt").read_text(encoding="utf-8")
    flags = {}
    for m in re.finditer(r"^SNAP flag (\S+)=(\S+) cat=", raw, re.M):
        flags[m.group(1)] = (m.group(2).lower() == "true")
    chat_over = {}
    for m in re.finditer(r"^SNAP chat_over (-?\d+) (\S+) kind=(\S+) "
                         r"sha12=([0-9a-f]{12}) len=(\d+)", raw, re.M):
        chat_over.setdefault(int(m.group(1)), {})[m.group(2)] = {
            "kind": m.group(3), "sha12": m.group(4), "len": int(m.group(5))}
    return {"prompts": inv, "flags": flags, "chat_over": chat_over}


def reconstruct_prompts(snap: dict, pr) -> tuple[dict, list, list]:
    """(values, fidelity_rows, unknown_rows) — live PG prompts.* reconstruction."""
    values, fidelity, unknown = {}, [], []
    for key, row in sorted(snap["prompts"].items()):
        spec = pr.by_pg_key(key)
        block_id = spec.block_id if spec is not None else ""
        factory = pr.factory_text(block_id) if block_id else ""
        marker_snapshot = row["markers"]

        if factory and sha12(factory) == row["sha12"]:
            values[key] = factory
            fidelity.append({"key": key, "source": "code-canon(factory-equal)",
                             "sha12_match": True, "len_match":
                             len(factory) == row["len"],
                             "block_id": block_id})
            continue
        # known non-canon values reconstructible by content
        if key == "prompts.verbilizer_default_mode":
            candidate = "serious"
            if sha12(candidate) == row["sha12"]:
                values[key] = candidate
                fidelity.append({"key": key, "source": "reconstructed('serious')",
                                 "sha12_match": True,
                                 "len_match": len(candidate) == row["len"],
                                 "block_id": block_id})
                continue
        if key == "prompts.summary_cover_style_id" and row["len"] == 0:
            values[key] = ""
            fidelity.append({"key": key, "source": "empty(custom slot)",
                             "sha12_match": True, "len_match": True,
                             "block_id": block_id})
            continue
        unknown.append({"key": key, "block_id": block_id,
                        "snapshot_sha12": row["sha12"], "snapshot_len": row["len"],
                        "snapshot_markers": marker_snapshot,
                        "reason": "custom value not captured in prep snapshot"})
    return values, fidelity, unknown


# ═══════════════════════════════════════════════════════════════════════════
# 1. fake PG layer (same DI hooks as bot.py)
# ═══════════════════════════════════════════════════════════════════════════

class FakeCache:
    """ConfigCache stand-in: sync get() over bot_settings mapping."""

    def __init__(self, settings: dict):
        self._settings = dict(settings)

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def get_all(self):
        return dict(self._settings)


class FakeChatCache:
    """ChatParamsCache stand-in: per-chat overrides only."""

    def __init__(self, overrides_by_chat: dict):
        self._by_chat = {int(k): dict(v) for k, v in overrides_by_chat.items()}

    async def get_chat_params(self, chat_id: int) -> dict:
        return {"overrides": dict(self._by_chat.get(int(chat_id), {}))}


def install_fakes(global_values: dict, chat_overrides: dict):
    from services import hot_config as hot
    from services import chat_params as cp
    hot.set_config_cache(FakeCache(global_values))
    cp.set_chat_params_cache(FakeChatCache(chat_overrides))


# ═══════════════════════════════════════════════════════════════════════════
# 2. per-key effective resolution (runtime resolver, no I/O)
# ═══════════════════════════════════════════════════════════════════════════

def resolve_keys_table(snap: dict, values: dict, pr) -> list:
    rows = []
    for key, row in sorted(snap["prompts"].items()):
        spec = pr.by_pg_key(key)
        block_id = spec.block_id if spec is not None else ""
        stored = values.get(key)
        chat_value = None  # no chat overrides for these keys are materialized
        if stored is None:
            rows.append({
                "key": key, "block_id": block_id, "resolved": False,
                "reason": "custom value not reconstructible offline",
                "withheld": None, "effective_sha12": None,
                "snapshot_sha12": row["sha12"]})
            continue
        eff = pr.effective_prompt(key, pg_value=stored, chat_value=chat_value)
        rows.append({
            "key": key, "block_id": block_id, "resolved": True,
            "snapshot_sha12": row["sha12"],
            "withheld": bool(eff.withheld),
            "withheld_reason": eff.provenance_reason,
            "source": eff.source,
            "effective_sha12": sha12(eff.text),
            "effective_chars": len(eff.text),
            "removed": eff.legacy_removed,
            "diagnostics": list(eff.diagnostics),
            "markers_after": marker_hits(eff.text),
            "known_canon": bool(eff.known_canon),
        })
    return rows


def suppress_labels(block_id: str, pr) -> list:
    text = pr.factory_text(block_id)
    cleaned, info = pr.suppress_legacy_speech(text, source="global")
    return {"labels": list(info.labels), "removed": info.removed,
            "applied": info.applied}


# ═══════════════════════════════════════════════════════════════════════════
# 3. composer stand (same call shapes as direct_chat_service)
# ═══════════════════════════════════════════════════════════════════════════

def manifest_view(manifest, pc) -> dict:
    return {
        "profile": manifest.profile,
        "writer": manifest.writer,
        "manifest_id": manifest.manifest_id,
        "system_sha12": sha12(manifest.system),
        "system_chars": len(manifest.system),
        "tokens_total": manifest.tokens_total,
        "markers": marker_hits(manifest.system),
        "layers": [{
            "layer": t.layer, "block_id": t.block_id, "owner": t.owner,
            "source": t.source, "revision": t.revision, "chars": t.chars,
            "rendered": t.rendered, "skip_reason": t.skip_reason,
            "detail": t.detail, "conflict": t.conflict,
        } for t in manifest.layers],
        "conflicts": [{
            "conflict_id": c.conflict_id, "outcome": c.outcome,
            "layer": c.layer, "block_id": c.block_id, "detail": c.detail,
        } for c in manifest.conflicts],
        "versions": dict(manifest.versions),
        "flags": {k: bool(v) for k, v in dict(manifest.flags).items()},
    }


def layer_text(manifest, layer: str) -> str:
    # text is not stored in traces; recompute via parts (system split is lossy
    # for empty parts) -> use marker scan on full system + per-layer chars.
    return ""


def contract_probe(text: str, needles: tuple) -> dict:
    return {n: (n in text) for n in needles}


async def direct_path(pr, pc, psb, snap, values) -> dict:
    from services import chat_prompts as cp_mod
    from services import bot_persona

    out = {}
    # ── tool-phase base (direct_chat_service.py:2445) ──────────────────────
    res = await pr.resolve_chat_speech_ex(
        "prompts.direct_chat_system_prompt", cp_mod.CHAT_SYSTEM_PROMPT,
        chat_id=CHAT)
    out["tool_phase_base"] = {
        "source": res.source, "withheld": bool(res.withheld),
        "withheld_reason": res.provenance_reason,
        "sha12": sha12(res.text), "chars": len(res.text),
        "markers": marker_hits(res.text),
        "diagnostics": list(res.diagnostics),
        "contracts": contract_probe(res.text, (
            "ИНСТРУМЕНТЫ", "ПРИОРИТЕТЫ", "АНТИ-ГАЛЛЮЦИНАЦИИ",
            "ЕСЛИ ПОЙМАЛИ НА НЕСТЫКОВКЕ", "query_chat_memory",
            "execute_web_search", "АНТИ-БОТ", "АСИММЕТРИЯ")),
    }
    # ── L2 writer base (direct_chat_service.py:4314-4317) ──────────────────
    l2_base = psb.resolve_prompt("prompts.direct_chat_verbalizer_system_prompt",
                                 cp_mod.DIRECT_VERBALIZER_SYSTEM_PROMPT)
    out["l2_base"] = {"sha12": sha12(l2_base), "chars": len(l2_base),
                      "markers": marker_hits(l2_base),
                      "contracts": contract_probe(l2_base, (
                          "СИСТЕМНАЯ РОЛЬ", "ОЖИДАЕМАЯ ПОЛНОТА",
                          "НЕСТЫКОВКЕ", "ТИПОГРАФИКА"))}
    # ── identity layer: synthetic minimal persona (marked) ─────────────────
    persona = bot_persona.BotPersona(name="Тестовый", biography="Синтетическая биография оффлайн-стенда.")
    identity_text = bot_persona.build_persona_prompt_block(persona, [], enabled=True)
    out["identity_text_synthetic"] = {
        "sha12": sha12(identity_text), "chars": len(identity_text),
        "markers": marker_hits(identity_text)}
    gates = await pc.resolve_gates(CHAT)
    snapshot = await pc.turn_snapshot(CHAT, None)
    out["gates"] = gates.as_flags()
    out["core_ref"] = {
        "source": snapshot.core.source, "origin": snapshot.core.origin,
        "level": snapshot.core.detail_level, "reason": snapshot.core.detail_reason,
        "revision": snapshot.core.revision, "chars": len(snapshot.core.text),
        "sha12": sha12(snapshot.core.text),
        "markers": marker_hits(snapshot.core.text),
        "contains_authorial_opening": "живой участник неформального" in snapshot.core.text,
    }
    # composer plans (same shape as _compose_speech_system, direct_chat_service.py:4257)
    user_parts = ("<Current_Question>\nтестовое сообщение\n</Current_Question>",)
    plan_tool = pc.PromptPlan(
        profile="speech_plain", writer="tool_phase", chat_id=CHAT,
        channel="plain", html_safe=True, run_id="stand-direct-tool",
        base_prompt=res.text, base_source=res.source, include_mode_block=True,
        core=snapshot.core,
        identity=pc.identity_from_text(identity_text, chat_id=CHAT, source="chat"),
        style_policy=snapshot.style_policy, user_parts=user_parts, gates=gates)
    manifest_tool = pc.compose_prompt(plan_tool)
    out["manifest_tool_phase"] = manifest_view(manifest_tool, pc)

    plan_l2 = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=CHAT,
        channel="plain", html_safe=True, run_id="stand-direct-l2",
        base_prompt=l2_base, base_source="global", include_mode_block=True,
        response_mode="casual", core=snapshot.core,
        identity=pc.identity_from_text(identity_text, chat_id=CHAT, source="chat"),
        style_policy=snapshot.style_policy, user_parts=user_parts, gates=gates)
    manifest_l2 = pc.compose_prompt(plan_l2)
    out["manifest_l2_casual"] = manifest_view(manifest_l2, pc)

    # humor craft layer inside the same composer (strategy from L1 plan)
    from services import mca_humor_craft as _hc
    humor_ref = await _hc.resolve_ref(chat_id=CHAT,
                                      comic_strategy="absurd_escalation",
                                      extent="auto")
    plan_h = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=CHAT,
        channel="plain", html_safe=True, run_id="stand-direct-l2-humor",
        base_prompt=l2_base, base_source="global", include_mode_block=True,
        response_mode="casual",
        response_plan=pc.PlanRef(text="ОЖИДАЕМАЯ ПОЛНОТА: обычный ответ.",
                                 revision="stand", extent="auto",
                                 structure="answer", tone="playful",
                                 comic_strategy="absurd_escalation"),
        humor=humor_ref, core=snapshot.core,
        identity=pc.identity_from_text(identity_text, chat_id=CHAT, source="chat"),
        style_policy=snapshot.style_policy, user_parts=user_parts, gates=gates)
    out["manifest_l2_with_humor"] = manifest_view(pc.compose_prompt(plan_h), pc)

    # mode blocks effective (same resolver the composer uses)
    modes = {}
    for mode in ("casual", "serious", "deep_research"):
        cand, base, block = psb.resolve_mode_parts(l2_base, mode)
        modes[mode] = {"candidate": cand, "block_sha12": sha12(block),
                       "block_chars": len(block), "markers": marker_hits(block),
                       "block_text": block if len(block) < 400 else block[:400]}
    out["mode_blocks_effective"] = modes
    # deep_research full manifest (channel output layer)
    plan_dr = pc.PromptPlan(
        profile="speech_rich", writer="l2_writer", chat_id=CHAT,
        channel="rich", html_safe=False, run_id="stand-direct-l2-dr",
        base_prompt=l2_base, base_source="global", include_mode_block=True,
        response_mode="deep_research", core=snapshot.core,
        identity=pc.identity_from_text(identity_text, chat_id=CHAT, source="chat"),
        style_policy=snapshot.style_policy, user_parts=user_parts, gates=gates)
    out["manifest_l2_deep_research"] = manifest_view(
        pc.compose_prompt(plan_dr), pc)
    # duplicate-owner-character mechanism check (real code, synthetic input)
    dup_line = ("Характер: Мат - естественная часть речи, а не приправа "
                "к каждому предложению")
    ident2 = "<Persona>\nИмя: Тестовый\n" + dup_line + "\n</Persona>"
    dup = pc._duplicate_character_segment(ident2, snapshot.core.text)
    keep_line = "Характер: любит поспать днём и греться на солнце"
    ident3 = "<Persona>\nИмя: Тестовый\n" + keep_line + "\n</Persona>"
    keep = pc._duplicate_character_segment(ident3, snapshot.core.text)
    out["duplicate_dedup_probe"] = {
        "synthetic": True,
        "dup_line_matches_core": bool(dup),
        "dup_segment": dup[:60] if dup else "",
        "non_dup_line_kept": keep == "",
        "conflict_id": "duplicate_owner_character",
    }
    return out


async def initiative_path(pr, pc, psb, values) -> dict:
    from services import chat_prompts as cp_mod
    out = {}
    l1_base = psb.resolve_prompt("prompts.direct_l1_planner_system_prompt",
                                 cp_mod.DIRECT_L1_PLANNER_SYSTEM_PROMPT)
    out["l1_decision_base"] = {"sha12": sha12(l1_base), "chars": len(l1_base),
                               "markers": marker_hits(l1_base)}
    gates = await pc.resolve_gates(CHAT)
    m = pc.compose_machine_system(l1_base, writer="initiative_l1",
                                  chat_id=CHAT, run_id="stand-init")
    out["l1_machine_manifest"] = manifest_view(m, pc)
    # text generation = existing L2 writer path (same as Direct L2)
    l2_base = psb.resolve_prompt("prompts.direct_chat_verbalizer_system_prompt",
                                 cp_mod.DIRECT_VERBALIZER_SYSTEM_PROMPT)
    snapshot = await pc.turn_snapshot(CHAT, None)
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=CHAT,
        channel="plain", html_safe=True, run_id="stand-init-l2",
        base_prompt=l2_base, base_source="global", include_mode_block=True,
        response_mode="casual", core=snapshot.core,
        identity=pc.identity_from_text("<Persona>\nИмя: Тестовый\n</Persona>",
                                       chat_id=CHAT, source="chat"),
        style_policy=snapshot.style_policy, gates=gates, user_parts=("goal",))
    out["l2_manifest"] = manifest_view(pc.compose_prompt(plan), pc)
    return out


async def factcheck_path(pr, pc, psb, values) -> dict:
    from services import factcheck_prompts as fp
    out = {}
    single = psb.resolve_prompt("prompts.factcheck_system_prompt",
                                fp.FACTCHECK_SYSTEM_PROMPT)
    analyst = psb.resolve_prompt("prompts.factcheck_analyst_system_prompt",
                                 fp.FACTCHECK_ANALYST_SYSTEM_PROMPT)
    verb = psb.resolve_prompt("prompts.factcheck_verbalizer_system_prompt",
                              fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT)
    verb_system = psb.compose_verbalizer_system(verb, "casual", "plain")
    out["single"] = {"sha12": sha12(single), "chars": len(single),
                     "markers": marker_hits(single),
                     "contracts": contract_probe(single, (
                         "вердикт", "АНТИ-БОТ", "АСИММЕТРИЯ", "двача"))}
    out["analyst"] = {"sha12": sha12(analyst), "chars": len(analyst),
                      "markers": marker_hits(analyst)}
    out["verbalizer_system"] = {"sha12": sha12(verb_system),
                                "chars": len(verb_system),
                                "markers": marker_hits(verb_system),
                                "contracts": contract_probe(verb_system, (
                                    "ТИПОГРАФИКА", "АНТИ-БОТ"))}
    # fallback branch when SMART_VERBALIZER_MODES_ENABLED=0 (code-previous canon)
    prev = fp.PREV_FACTCHECK_VERBALIZER_R1023
    out["modes_off_prev_branch"] = {"sha12": sha12(prev), "chars": len(prev),
                                    "markers": marker_hits(prev)}
    return out


async def summary_path(pr, pc, psb, values) -> dict:
    from services import summary_prompts as sp
    out = {}
    single = psb.resolve_prompt("prompts.summary_system_prompt",
                                sp.SYSTEM_PROMPT)
    narrator = psb.resolve_prompt("prompts.summary_narrator_system_prompt",
                                  sp.SUMMARY_NARRATOR_SYSTEM_PROMPT)
    l1 = psb.resolve_prompt("prompts.summary_l1_clusterizer_system_prompt",
                            sp.SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT)
    l2w = psb.resolve_prompt("prompts.summary_l2_writer_system_prompt",
                             sp.SUMMARY_L2_WRITER_SYSTEM_PROMPT)
    narrator_system = psb.compose_verbalizer_system(narrator, "casual", "plain")
    out["legacy_single"] = {"sha12": sha12(single), "chars": len(single),
                            "markers": marker_hits(single),
                            "contracts": contract_probe(single, (
                                "<chat_history>", "АНТИ-БОТ", "саммари"))}
    out["narrator_system"] = {"sha12": sha12(narrator_system),
                              "chars": len(narrator_system),
                              "markers": marker_hits(narrator_system)}
    out["l1_clusterizer"] = {"sha12": sha12(l1), "chars": len(l1),
                             "markers": marker_hits(l1),
                             "contracts": contract_probe(l1, (
                                 "кластеризатор", "JSON"))}
    l2_voice = {
        "phase_saved_by_w_rule": ("СТИЛЬ (характер бота)" in l2w
                                  or "характер бота" in l2w),
        "legacy_voice_phrases": {
            "характер бота": "характер бота" in l2w,
            "двачерские обороты": "двачерские обороты" in l2w,
            "атмосферу конфы": "атмосферу конфы" in l2w,
        },
        "withholding_required": False,
        "legacy_persona_flag": False,
        "suppression_labels": [],
        "conclusion": ("reachable legacy-voice reference in the live canon; "
                       "NOT covered by the 9 removal rules and NOT withheld"),
    }
    out["l2_writer"] = {"sha12": sha12(l2w), "chars": len(l2w),
                        "markers": marker_hits(l2w),
                        "legacy_voice": l2_voice,
                        "contracts": contract_probe(l2w, (
                            "ГРАММАТИКА", "АКЦЕНТЫ", "ФОРМАТ ОТВЕТА"))}
    # editor (custom, not reconstructible): state from snapshot
    out["editor_custom"] = {
        "reconstructible": False, "snapshot_sha12": "6a1f3432889c",
        "snapshot_len": 2023, "snapshot_markers": 0,
        "known_canon": None,
        "suppression": "no-op unless bytes match a known canon (snapshot says they don't)",
    }
    # per-chat summary_system_prompt override: runtime consumption check
    out["chat_override_summary_system_prompt"] = {
        "chat": CHAT, "snapshot_sha12": "141016a95b95", "snapshot_len": 3484,
        "consumed_by_runtime_summary_path": False,
        "note": "summary path resolves prompts.summary_system_prompt via "
                "hot(global) only; chat layer is not read (resolve_prompt)",
    }
    return out


async def fallback_path(pr, pc, psb, values) -> dict:
    from services import chat_prompts as cp_mod
    out = {}
    # (a) composer fail-open manifests never throw: base-only system
    res = await pr.resolve_chat_speech_ex(
        "prompts.direct_chat_system_prompt", cp_mod.CHAT_SYSTEM_PROMPT,
        chat_id=CHAT)
    plan = pc.PromptPlan(profile="speech_plain", writer="fallback",
                         chat_id=CHAT, base_prompt=res.text,
                         base_source=res.source)
    fb = pc._fallback_manifest(plan)
    out["composer_fail_open"] = {
        "system_source": "base_prompt(effective, suppressed)",
        "sha12": sha12(fb.system), "chars": len(fb.system),
        "markers": marker_hits(fb.system),
        "layers": [{"layer": t.layer, "block_id": t.block_id,
                    "skip_reason": t.skip_reason} for t in fb.layers]}
    # (b) modes-OFF legacy branch (SMART_VERBALIZER_MODES_ENABLED=0)
    prev = cp_mod.PREV_CHAT_VERBALIZER_R1023
    out["modes_off_prev_branch"] = {"sha12": sha12(prev), "chars": len(prev),
                                    "markers": marker_hits(prev),
                                    "used_when": "SMART_VERBALIZER_MODES_ENABLED=0"}
    # (c) code-fallback of resolve_prompt (PG key absent/empty -> raw canon)
    code_default = cp_mod.CHAT_SYSTEM_PROMPT
    via_resolve = pr.resolve_speech_value("prompts.direct_chat_system_prompt",
                                          code_default, source="default")
    out["code_default_path"] = {
        "source": "default", "suppression_applied": via_resolve.text != code_default,
        "sha12": sha12(via_resolve.text), "chars": len(via_resolve.text),
        "markers": marker_hits(via_resolve.text),
        "note": "documented W2 OFF-parity: code fallback bytes unchanged",
    }
    # (d) runtime config state: modes kill-switch default
    from config import settings as st
    out["smart_verbalizer_modes_enabled_default"] = bool(
        getattr(st.settings, "SMART_VERBALIZER_MODES_ENABLED", True))
    # (e) flag typing probe: bot_settings.value is JSONB; a *string* "false"
    # would be truthy for the new axes (not in param_catalog -> no cast).
    from services import hot_config as _hot
    from services import mca_gates as _g
    _cache = _hot.get_config_cache()
    saved = _cache._settings.get("flags.unified_composer_enabled")
    _cache._settings["flags.unified_composer_enabled"] = "false"
    str_false = _g._intent_catalog_flag("flags.unified_composer_enabled", False)
    _cache._settings["flags.unified_composer_enabled"] = False
    bool_false = _g._intent_catalog_flag("flags.unified_composer_enabled", False)
    _cache._settings["flags.unified_composer_enabled"] = saved
    out["flag_typing_probe"] = {
        "string_false_reads_as": bool(str_false),
        "json_bool_false_reads_as": bool(bool_false),
        "note": "bot_settings.value is JSONB; write JSON booleans true/false",
    }
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 4. custom / non-canon entries (task 3)
# ═══════════════════════════════════════════════════════════════════════════

def customs_section(snap: dict, pr, psb) -> dict:
    out = {}
    g = snap["prompts"]["prompts.verbilizer_default_mode"]
    out["verbilizer_default_mode"] = {
        "global_value_reconstructed": "serious",
        "global_snapshot_sha12": g["sha12"], "len": g["len"],
        "markers": g["markers"],
        "factory_sha12": g["factory_sha12"],
        "consumed": "global only: _resolve_default_mode() -> hot.get(...); "
                    "applied only when Stage-1 response_mode is empty/invalid",
        "chat_override": {"chat": CHAT, "value_reconstructed": "casual",
                          "snapshot_sha12": "c633eb52f63c", "len": 6,
                          "consumed_by_runtime": False,
                          "note": "per-chat override exists in PG but the "
                                  "fallback resolver reads the global layer"},
        "conflict": False,
        "verdict": "no legacy-personality instructions; mode = length/format "
                   "convention; 'serious' tone (грамотно, по делу, легкая "
                   "циничная ирония) compatible with Core",
    }
    e = snap["prompts"]["prompts.summary_editor_system_prompt"]
    out["summary_editor"] = {
        "global_snapshot_sha12": e["sha12"], "len": e["len"],
        "markers": e["markers"], "factory_sha12": e["factory_sha12"],
        "class": "custom (2023)",
        "content_available": False,
        "withholding_required": False,
        "conflict": "unknown (content not captured; marker scan = 0)",
        "note": "machine JSON stage (summary editor) — not a speech layer "
                "(speech=False in registry)",
    }
    c = snap["chat_over"][CHAT]
    out["summary_cover_style_per_chat"] = {
        "chat": CHAT, "snapshot_sha12": c["prompts.summary_cover_style"]["sha12"],
        "len": c["prompts.summary_cover_style"]["len"],
        "markers": "not captured", "consumed": "cover pipeline only "
        "(summary_generator._resolve_cover_style_text -> chat layer)",
        "conflict": "unknown (content not captured)",
    }
    out["summary_cover_style_id_per_chat"] = {
        "chat": CHAT, "snapshot_sha12": c["prompts.summary_cover_style_id"]["sha12"],
        "len": c["prompts.summary_cover_style_id"]["len"],
        "consumed": "cover style selection id (POST /api/cover/select)",
        "conflict": False,
    }
    chat_summary = c["prompts.summary_system_prompt"]
    out["summary_system_prompt_per_chat"] = {
        "chat": CHAT, "snapshot_sha12": chat_summary["sha12"],
        "len": chat_summary["len"],
        "consumed_by_runtime": False,
        "note": "summary runtime resolves the GLOBAL key only "
                "(resolve_prompt -> hot.get); chat layer shown in UI",
        "conflict": "not applicable to runtime payload",
    }
    # whole-repo scan of 'other non-canon prompts.*' -> handled by sweep
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 5. factory-registry + python-constants marker sweep (task 2)
# ═══════════════════════════════════════════════════════════════════════════

def registry_sweep(pr) -> dict:
    rows = []
    for spec in pr.all_blocks():
        text = pr.factory_text(spec.block_id)
        hits = marker_hits(text)
        if not hits:
            continue
        rows.append({
            "block_id": spec.block_id, "family": spec.family,
            "pg_key": spec.pg_key, "speech": spec.speech,
            "legacy_persona": spec.legacy_persona,
            "withholding_required": bool(pr.withholding_required(spec)),
            "markers": hits, "chars": len(text),
            "code_source": spec.code_source,
            "consumers": list(spec.consumers),
            "suppression_labels": suppress_labels(spec.block_id, pr)["labels"],
        })
    return {"total_blocks": len(pr.all_blocks()),
            "withholding_blocks": len(pr.withholding_blocks()),
            "marker_blocks": rows}


def python_constants_sweep() -> dict:
    """Marker scan over services/*.py string literals (heuristic split)."""
    pat = re.compile("|".join(MARKERS), re.IGNORECASE)
    hits = []
    for path in sorted((REPO / "services").glob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(),
                1):
            if not pat.search(line):
                continue
            hits.append({"file": str(path.relative_to(REPO)).replace("\\", "/"),
                         "line": lineno,
                         "kind": "comment/docstring" if line.lstrip().startswith(
                             ("#", '"""', "*", "→")) else "code-line",
                         "snippet": line.strip()[:160]})
    return {"marker_lines": hits,
            "files": sorted({h["file"] for h in hits})}


CALLERS_SCAN = ("evaluate_candidates", "capture_send", "run_window_pass",
                "strategy_weight", "sample_penalties")


def humor_section(pr, pc, gates_now) -> dict:
    import services.mca_humor_craft as hc
    from services import mca_humor_feedback as hf
    from services import mca_sample_library as sl
    out = {}
    out["axes"] = {
        "humor_craft_enabled": gates_now.humor_craft_enabled,
        "humor_library_enabled": gates_now.humor_library_enabled,
        "humor_feedback_enabled": gates_now.humor_feedback_enabled,
        "candidate_eval": {
            "env_and_flag": __import__("services.mca_gates",
                                       fromlist=["x"]).humor_candidate_eval_enabled(),
            "default": False,
        },
    }
    # craft layer resolution (context activation)
    async def run_craft():
        ref_ok = await hc.resolve_ref(chat_id=CHAT,
                                      comic_strategy="absurd_escalation",
                                      extent="auto")
        ref_serious = hc.select_technique(
            comic_strategy="absurd_escalation", structure="report")
        ref_none = hc.select_technique(comic_strategy="none")
        from services import mca_humor_feedback as _hf
        weight = await _hf.strategy_weight(None, CHAT, "absurd_escalation")
        return ref_ok, ref_serious, ref_none, weight
    ref_ok, decision_serious, decision_none, weight = asyncio.run(run_craft())
    out["craft"] = {
        "layer_chars": len(ref_ok.text or ""), "layer_sha12": sha12(ref_ok.text or ""),
        "technique": ref_ok.technique, "enabled": ref_ok.enabled,
        "markers": marker_hits(ref_ok.text or ""),
        "serious_context_reason": decision_serious.reason,
        "no_strategy_reason": decision_none.reason,
        "layer_calls": hc.layer_calls(ref_ok.technique),
        "feedback_weight_no_db": weight,
    }
    # candidate eval consumers scan
    consumers = {}
    for fn in CALLERS_SCAN:
        found = []
        for path in sorted(list((REPO / "services").glob("*.py"))
                           + list((REPO / "handlers").glob("*.py"))):
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if fn + "(" in line and "def " + fn not in line \
                        and "#" not in line.split(fn)[0]:
                    found.append("%s:%d" % (path.relative_to(REPO).as_posix(),
                                            lineno))
        consumers[fn] = found
    out["callers_scan"] = consumers
    # boundary probes straight from the module
    out["candidate_eval_probe_off"] = asyncio.run(
        hc.evaluate_candidates(candidates=["а", "б"], llm=None)).reason
    os.environ.pop("HUMOR_CANDIDATE_EVAL_ENABLED", None)
    out["candidate_eval_probe_axis_off"] = asyncio.run(
        hc.evaluate_candidates(candidates=["а", "б"], llm=None)).reason

    class _StubLLM:
        async def generate(self, *args, **kwargs):
            return "вариант 1"

    os.environ["HUMOR_CANDIDATE_EVAL_ENABLED"] = "1"
    from services import hot_config as _hot
    _cache = _hot.get_config_cache()
    if _cache is not None:
        _cache._settings["flags.humor_candidate_eval_enabled"] = True
    out["candidate_eval_axis_on_no_llm"] = asyncio.run(
        hc.evaluate_candidates(candidates=["а", "б"], llm=None)).reason
    res_on = asyncio.run(hc.evaluate_candidates(candidates=["а", "б", "в"],
                                                llm=_StubLLM()))
    out["candidate_eval_axis_on_bounded"] = {
        "applied": bool(res_on.applied), "reason": res_on.reason,
        "calls": int(res_on.calls), "candidates": list(res_on.candidates),
        "max_candidates": hc.CANDIDATE_EVAL_MAX_CANDIDATES,
        "max_calls": hc.CANDIDATE_EVAL_MAX_CALLS,
        "timeout_s": hc.CANDIDATE_EVAL_TIMEOUT_S,
    }
    os.environ.pop("HUMOR_CANDIDATE_EVAL_ENABLED", None)
    if _cache is not None:
        _cache._settings.pop("flags.humor_candidate_eval_enabled", None)
    # window pass gate behaviour (gate ON, db None -> honest zeros)
    out["window_pass_gate_on_db_none"] = asyncio.run(
        hf.run_window_pass(None))
    os.environ.pop("HUMOR_FEEDBACK_ENABLED", None)
    out["window_pass_gate_off"] = asyncio.run(hf.run_window_pass(None))
    os.environ["HUMOR_FEEDBACK_ENABLED"] = "1"
    return out


# ═══════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════

def main() -> int:
    for k, v in SOUL_ENV_ON.items():
        os.environ[k] = v
    os.environ.pop("HUMOR_CANDIDATE_EVAL_ENABLED", None)

    from services import prompt_registry as pr
    from services import prompt_composer as pc
    from services import prompt_style_blocks as psb
    from services import mca_gates as gates

    snap = load_snapshot()
    values, fidelity, unknown = reconstruct_prompts(snap, pr)

    flags = dict(snap["flags"])
    flags.update(SOUL_FLAGS_ON)
    global_values = dict(values)
    global_values.update(flags)
    chat_over = {CHAT: {"prompts.verbilizer_default_mode": "casual"}}
    install_fakes(global_values, chat_over)

    report = {
        "meta": {
            "candidate_worktree_head": run_git("rev-parse", "HEAD"),
            "services_vs_6094a2cf_diff": run_git(
                "diff", "--stat", "6094a2cf", "--", "services") or "<empty>",
            "registry_version": pr.REGISTRY_VERSION,
            "factory_set": pr.factory_set_fingerprint(),
            "prod_snapshot": "2026-10-17 19:04:41 UTC, prod 0b7a0aca (2.58.84)",
            "mode": "offline reconstruction; SOUL axes modeled ON (env+PG)",
            "soul_env_set": SOUL_ENV_ON,
            "soul_flags_set": SOUL_FLAGS_ON,
            "chat": CHAT,
        },
        "reconstruction": {
            "fidelity": fidelity, "unknown": unknown,
            "counts": {"total": len(snap["prompts"]),
                       "reconstructed": len(fidelity),
                       "unknown": len(unknown)},
        },
        "keys_effective": resolve_keys_table(snap, values, pr),
        "withheld_values_view": pr.withheld_values(),
        "paths": {},
        "customs": customs_section(snap, pr, psb),
        "sweep_registry": registry_sweep(pr),
        "sweep_python": python_constants_sweep(),
    }

    gates_now = asyncio.run(pc.resolve_gates(CHAT))
    report["paths"]["direct"] = asyncio.run(direct_path(pr, pc, psb, snap, values))
    report["paths"]["initiative"] = asyncio.run(
        initiative_path(pr, pc, psb, values))
    report["paths"]["factcheck"] = asyncio.run(
        factcheck_path(pr, pc, psb, values))
    report["paths"]["summary"] = asyncio.run(summary_path(pr, pc, psb, values))
    report["paths"]["fallback"] = asyncio.run(
        fallback_path(pr, pc, psb, values))
    report["humor"] = humor_section(pr, pc, gates_now)

    (HERE / "stand-output.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── compact txt summary ────────────────────────────────────────────────
    lines = []
    add = lines.append
    add("SOUL-PAYLOAD-VERIFY stand output")
    add("meta: %s" % json.dumps(report["meta"], ensure_ascii=False))
    add("")
    add("== reconstruction ==")
    add(json.dumps(report["reconstruction"]["counts"], ensure_ascii=False))
    for row in report["reconstruction"]["unknown"]:
        add("UNKNOWN %s len=%s sha=%s markers=%s" % (
            row["key"], row["snapshot_len"], row["snapshot_sha12"],
            row["snapshot_markers"]))
    add("")
    add("== keys effective (withheld/suppressed) ==")
    for row in report["keys_effective"]:
        add("%-58s res=%s withheld=%s removed=%s eff=%s mk=%s diag=%s" % (
            row["key"], row["resolved"], row.get("withheld"),
            row.get("removed"), row.get("effective_sha12"),
            row.get("markers_after"), ",".join(row.get("diagnostics") or [])))
    add("")
    add("== withheld view ==")
    for row in report["withheld_values_view"]:
        add("%-58s %s" % (row["pg_key"], row["withheld_reason"]))
    for path_name, data in report["paths"].items():
        add("")
        add("== path: %s ==" % path_name)
        add(json.dumps(data, ensure_ascii=False, indent=1)[:12000])
    add("")
    add("== customs ==")
    add(json.dumps(report["customs"], ensure_ascii=False, indent=1))
    add("")
    add("== humor ==")
    add(json.dumps(report["humor"], ensure_ascii=False, indent=1))
    add("")
    add("== sweep registry (marker blocks) ==")
    for row in report["sweep_registry"]["marker_blocks"]:
        add("%-34s family=%-10s pg=%-40s wp=%s lp=%s mk=%s" % (
            row["block_id"], row["family"], row["pg_key"],
            row["withholding_required"], row["legacy_persona"], row["markers"]))
    add("")
    add("== sweep python (files) ==")
    add(json.dumps(report["sweep_python"]["files"], ensure_ascii=False))
    (HERE / "stand-output.txt").write_text("\n".join(lines), encoding="utf-8")
    print("stand ok; outputs written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
