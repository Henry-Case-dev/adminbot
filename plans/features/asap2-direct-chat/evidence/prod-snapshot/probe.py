# -*- coding: utf-8 -*-
"""ASAP2-PROD-SNAP: read-only snapshot of deployed prompt config (no secrets).

Runs on the prod server inside /var/www/admin_bot with the project venv.
SELECT-only PG access; SQLite opened mode=ro when needed. Prints a compact
digest; full detail is also written next to this script by the runner wrapper.
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = "/var/www/admin_bot"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

K_L1 = "prompts.direct_l1_planner_system_prompt"
K_L2 = "prompts.direct_chat_verbalizer_system_prompt"
CHATS = (-1002661910336, -1004482340693)


def sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def brief(t: str) -> dict:
    return {
        "sha256": sha(t),
        "sha12": sha(t)[:12],
        "len": len(t),
        "head80": t[:80].replace("\n", " "),
        "tail60": t[-60:].replace("\n", " "),
    }


def sh(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT,
                                       timeout=20).decode("utf-8", "replace").strip()
    except Exception as exc:                      # pragma: no cover
        return "ERR:%s" % exc


def dsn():
    env = open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace").read()
    for name in ("POSTGRES_DSN", "PG_DSN", "DATABASE_URL", "POSTGRES_URL"):
        m = re.search(r'^%s=["\']?([^"\'\n]+)' % name, env, re.M)
        if m:
            return m.group(1).strip(), name
    return None, None


async def pg_part(rep):
    import asyncpg
    d, dsn_name = dsn()
    if not d:
        rep["pg"] = {"available": False, "reason": "dsn_absent"}
        return
    rep["dsn_env"] = dsn_name
    conn = await asyncio.wait_for(asyncpg.connect(d, timeout=8), 12)
    try:
        rows = await conn.fetch(
            "SELECT key, value::text AS v, updated_at FROM bot_settings "
            "WHERE key = ANY($1::text[])", [K_L1, K_L2])
        active = {}
        for r in rows:
            raw = r["v"]
            try:
                val = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                val = raw
            active[r["key"]] = {"value": val if isinstance(val, str) else str(val),
                                "updated_at": str(r["updated_at"]),
                                "raw_is_json_string": isinstance(val, str)}
        rep["active_pg"] = {k: (brief(v["value"]) | {"updated_at": v["updated_at"]})
                            for k, v in active.items()}

        prof = await conn.fetch(
            "SELECT chat_id, chat_params FROM chat_profiles "
            "WHERE chat_id = ANY($1::bigint[])", list(CHATS))
        ov = {}
        for r in prof:
            doc = r["chat_params"]
            if isinstance(doc, str):
                try:
                    doc = json.loads(doc)
                except Exception:
                    doc = {}
            doc = doc or {}
            overrides = doc.get("overrides") or {}
            picked = {k: len(v) if isinstance(v, str) else v
                      for k, v in overrides.items() if k in (K_L1, K_L2)}
            ov[int(r["chat_id"])] = {
                "has_doc": bool(doc),
                "override_keys_total": len(overrides),
                "picked": picked,
                "any_prompt_override": sorted(
                    [k for k in overrides if k.startswith("prompts.")])[:8],
            }
        rep["chat_overrides"] = {str(k): v for k, v in ov.items()}
        rep["chat_profiles_rows"] = [int(r["chat_id"]) for r in prof]

        steps = await conn.fetch(
            "SELECT module, step, count(*) AS n FROM llm_usage_events "
            "WHERE ts > now() - interval '7 days' GROUP BY 1,2 "
            "ORDER BY n DESC LIMIT 12")
        rep["usage_steps_7d"] = [
            {"module": s["module"], "step": s["step"], "n": int(s["n"])}
            for s in steps]

        meta = await conn.fetch(
            "SELECT plan_meta::text AS pm FROM llm_usage_events "
            "WHERE ts > now() - interval '7 days' AND plan_meta IS NOT NULL")
        keys = {}
        acts = {}
        for r in meta:
            try:
                pm = json.loads(r["pm"]) if isinstance(r["pm"], str) else r["pm"]
            except Exception:
                continue
            if not isinstance(pm, dict):
                continue
            for k in pm:
                keys[k] = keys.get(k, 0) + 1
            act = str(pm.get("response_act") or "")
            if act:
                acts[act] = acts.get(act, 0) + 1
        rep["plan_meta_7d"] = {
            "rows_with_plan_meta": len(meta),
            "keys": keys,
            "has_needs_clarification": any("clarification" in k for k in keys),
            "response_act_counts": acts,
        }
    finally:
        await conn.close()
    rep["pg"] = {"available": True}


def prompt_part(rep):
    from services.chat_prompts import (DIRECT_L1_PLANNER_SYSTEM_PROMPT as F_L1,
                                       DIRECT_VERBALIZER_SYSTEM_PROMPT as F_L2)
    from services import prompt_registry as pr
    from services.direct_l1 import L1Plan, build_l2_plan_block

    canons = {}
    for key, const, block_id in ((K_L1, F_L1, "direct.base.l1_planner"),
                                 (K_L2, F_L2, "direct.base.l2_writer")):
        try:
            reg = pr.factory_text(block_id)
        except Exception as exc:
            reg = "ERR:%s" % exc
        canons[key] = {
            "module_const": brief(const),
            "registry_factory": brief(reg) if isinstance(reg, str) and not reg.startswith("ERR:") else reg,
            "const_eq_registry": (const == reg) if isinstance(reg, str) else None,
        }
    rep["factory"] = canons

    effective = {}
    eff_texts = {}
    raw = rep.get("_raw") or {}
    for key, const in ((K_L1, F_L1), (K_L2, F_L2)):
        val = raw.get(key)
        if not isinstance(val, str) or not val.strip():
            effective[key] = {"active_present": False,
                              "effective": brief(const),
                              "source": "default",
                              "factory_eq_effective": True,
                              "withheld": False}
            eff_texts[key] = const
            continue
        res = pr.resolve_speech_value(key, val, source="global")
        eff_texts[key] = res.text
        effective[key] = {
            "active_present": True,
            "effective": brief(res.text),
            "source": res.source,
            "withheld": bool(getattr(res, "withheld", False)),
            "withheld_sha12": getattr(res, "withheld_sha256_12", ""),
            "provenance_reason": getattr(res, "provenance_reason", ""),
            "diagnostics": list(getattr(res, "diagnostics", ()) or ()),
            "factory_eq_active_raw": val == const,
            "factory_eq_effective": res.text == const,
            "active_eq_effective": res.text == val,
        }
    rep["effective"] = effective

    eff_l1 = eff_texts.get(K_L1, "")
    eff_l2 = eff_texts.get(K_L2, "")
    rep["canon_checks"] = {
        "l1_clar_contract_count": eff_l1.count("УТОЧНЕНИЯ И ПРОДОЛЖЕНИЕ ДИАЛОГА"),
        "l1_legacy_imperative_present": "Ничего кроме вопроса не пиши" in eff_l1,
        "l1_claim_envelope_directive_present": "Если без уточнения ответ может быть не о том" in eff_l1,
        "l1_clarify_ask_marker_present": "clarify=ask" in eff_l1,
        "l1_clarify_assume_marker_present": "clarify=assume" in eff_l1,
        "l2_single_question_rule_count": eff_l2.count(
            "Вместо ответа задавай один конкретный уточняющий вопрос"),
        "l2_section_43_phrase_present": "Для выполнения этого запроса действительно не хватает" in eff_l2,
        "l2_legacy_no_more_than_question": "Ничего кроме вопроса не пиши" in eff_l2,
    }

    def case(name, plan, clarification):
        blk = build_l2_plan_block(plan, clarification=clarification)
        return {
            "name": name,
            "has_act_line": "смысловой акт ответа: clarification" in blk,
            "has_target_line": "недостающий обязательный предмет:" in blk,
            "has_43_directive": "Для выполнения этого запроса действительно не хватает" in blk,
            "chars": len(blk),
            "body": blk,
        }

    rep["payload_cases"] = [
        case("P1_false_no_target", L1Plan(action="reply", response_act="answer",
                                          needs_clarification=False), False),
        case("P2_act_clar_but_flag_false", L1Plan(action="reply",
                                                  response_act="clarification",
                                                  needs_clarification=False), False),
        case("P3_true_with_target", L1Plan(action="reply", response_act="clarification",
                                           needs_clarification=True,
                                           clarification_target="media_target"), True),
        case("P4_true_empty_target", L1Plan(action="reply", response_act="clarification",
                                            needs_clarification=True,
                                            clarification_target=""), True),
    ]


async def main():
    rep = {}
    # deploy facts
    ver = sh("grep -m1 -E '^APP_VERSION' %s/config/settings.py" % ROOT)
    rep["deploy"] = {
        "git_head": sh("git rev-parse HEAD"),
        "git_branch": sh("git rev-parse --abbrev-ref HEAD"),
        "git_head_time": sh("git log -1 --format=%cI"),
        "git_head_subject": sh("git log -1 --format=%s"),
        "version_line": ver,
        "rollback_ref": sh("git rev-parse release/fix-2.58.111 2>/dev/null || echo MISSING"),
        "rollback_obj_ok": sh("git cat-file -e fbf9013d89b03e38473ce6824a460fdbb736fff8 "
                              "&& echo OK || echo MISSING"),
        "healthz": sh("curl -s --max-time 6 http://127.0.0.1:8000/healthz"),
        "systemctl_active": sh("systemctl is-active admin_bot"),
        "systemctl_show": sh("systemctl show admin_bot -p NRestarts -p MainPID "
                             "-p ExecMainStatus"),
        "backup": sh("ls -l %s/backups/pre_deploy_258113_1792734640.db 2>/dev/null || echo MISSING" % ROOT),
        "disk_free": sh("df -h / | tail -1"),
    }
    await pg_part(rep)
    # raw active values for effective computation (kept locally, not printed)
    raw = {}
    try:
        import asyncpg
        d, _n = dsn()
        conn = await asyncio.wait_for(asyncpg.connect(d, timeout=8), 12)
        try:
            for r in await conn.fetch(
                    "SELECT key, value::text AS v FROM bot_settings "
                    "WHERE key = ANY($1::text[])", [K_L1, K_L2]):
                v = r["v"]
                try:
                    v = json.loads(v) if isinstance(v, str) else v
                except Exception:
                    pass
                raw[r["key"]] = str(v)
        finally:
            await conn.close()
    except Exception as exc:
        rep["raw_error"] = str(exc)
    rep["_raw"] = raw
    prompt_part(rep)
    # keep only digests, drop raw text before printing
    raw_eff = {}
    for k, v in (rep.get("effective") or {}).items():
        v = dict(v)
        v.pop("_text", None)
        raw_eff[k] = v
    rep["effective"] = raw_eff
    rep.pop("_raw", None)
    print("JSON_BEGIN")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("JSON_END")


asyncio.run(main())
