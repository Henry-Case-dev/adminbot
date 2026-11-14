"""Compare the pre/post deploy snapshots and emit verify203.json (verifier v2).

v1 false failures were verifier bugs, not product findings:
  * prompt rows are stored as JSON text, so the raw text length/sha of
    ``prompts.checkup_system_prompt`` is not the body length/sha;
  * two chats legitimately carry an explicit ``flags.budgets_enabled=false``
    chat override (as on 2.58.202), so "no override at all" was the wrong
    assertion.
The correction reads the body identity from the prompt journal (revision rows
recorded by the release) and from the deployed bot-like provenance probe.
"""
from __future__ import annotations

import json
from pathlib import Path

run = Path(__file__).resolve().parent
pre = json.loads((run / "snapshot_pre_203.json").read_text(encoding="utf-8"))
post = json.loads((run / "snapshot_post_203.json").read_text(encoding="utf-8"))
prov = json.loads((run / "prov203.json").read_text(encoding="utf-8"))

checks: list[dict] = []


def check(name: str, ok: bool, detail) -> None:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})


check("app_version_258203", post["app_version"] == "2.58.203", post["app_version"])
check("head_candidate", post["head"] == "c97c06e45cdbbf45b4c9df500e11cdb1d0486ae5", post["head"])
check("branch_release", post["branch"] == "release/smart-corrective-01", post["branch"])
check("checkout_clean", post["dirty_tracked"] == 0, post["dirty_tracked"])
check("health_local_200_258203",
      post["health_local"].get("code") == 200 and "2.58.203" in post["health_local"].get("body", ""),
      post["health_local"])
check("health_public_200_258203",
      post["health_public"].get("code") == 200 and "2.58.203" in post["health_public"].get("body", ""),
      post["health_public"])

check("schema_user_version_47",
      pre["sqlite"].get("user_version") == post["sqlite"].get("user_version") == 47,
      {"pre": pre["sqlite"], "post": post["sqlite"]})
check("schema_tables_130", post["sqlite"].get("tables") == 130, post["sqlite"].get("tables"))
check("schema_migrations_36_47",
      post["sqlite"].get("schema_migrations_rows") == 36
      and post["sqlite"].get("schema_migrations_max") == 47,
      {"rows": post["sqlite"].get("schema_migrations_rows"),
       "max": post["sqlite"].get("schema_migrations_max")})

sp, so = pre["settings"], post["settings"]
check("settings_count_stable", sp["count"] == so["count"], {"pre": sp["count"], "post": so["count"]})
check("settings_digest_excluding_checkup_unchanged",
      sp["digest_excluding_checkup"] == so["digest_excluding_checkup"],
      {"pre": sp["digest_excluding_checkup"], "post": so["digest_excluding_checkup"]})
changed = sorted(k for k in sp["specific"] if sp["specific"][k] != so["specific"][k])
check("settings_only_checkup_row_changed", changed == ["prompts.checkup_system_prompt"], changed)

for key in ("flags.budgets_enabled", "flags.factcheck_pipeline_v2",
            "models.llm_model_name", "models.llm_base_url",
            "prompts.factcheck_subject_system_prompt"):
    check(f"setting_unchanged:{key}", sp["specific"][key] == so["specific"][key],
          {"pre": sp["specific"][key], "post": so["specific"][key]})

# released global prompt: journal revision chain + decoded body from the probe
pre_revs = {r["revision_id"]: r for r in pre["prompts"]["revisions"]}
post_revs = {r["revision_id"]: r for r in post["prompts"]["revisions"]}
gl = prov["global_layer"]
check("global_prompt_was_3030_b0c70f97",
      pre_revs.get("rev:3be4841bca08", {}).get("scope") == "global"
      and pre_revs["rev:3be4841bca08"]["chars"] == 3030
      and pre_revs["rev:3be4841bca08"]["sha12"] == "b0c70f974e0e",
      pre_revs.get("rev:3be4841bca08"))
check("global_prompt_now_factory_3462_3140bb36",
      gl["body_chars"] == 3462 and gl["body_sha256"].startswith("3140bb364044")
      and gl["contains_betterstack"] is False and gl["contains_401"] is False,
      {k: gl[k] for k in ("body_chars", "body_sha12", "contains_betterstack",
                          "contains_401")})
check("global_prompt_row_matches_active_global_revision",
      gl["active_revision"]["revision_id"] == "rev:a2a369bba312"
      and gl["active_revision"]["chars"] == 3462
      and gl["active_revision"]["sha12"] == "3140bb364044"
      and gl["active_revision"]["detail_code"] == "factory_activate"
      and gl["active_revision"]["outcome"] == "applied"
      and gl["active_revision"]["factory_revision_applied"] == "fac:93c42f967ef8",
      gl["active_revision"])
check("new_factory_revision_in_journal",
      post_revs.get("rev:a2a369bba312", {}).get("chars") == 3462
      and post_revs["rev:a2a369bba312"]["sha12"] == "3140bb364044"
      and post_revs["rev:a2a369bba312"]["scope"] == "global",
      post_revs.get("rev:a2a369bba312"))
check("factory_code_3462_3140bb36",
      post["factory_code"].get("chars") == 3462
      and post["factory_code"].get("sha256", "").startswith("3140bb364044"),
      post["factory_code"])

check("profiles_count_stable", pre["profiles"]["count"] == post["profiles"]["count"],
      post["profiles"]["count"])
check("profiles_digest_unchanged",
      pre["profiles"]["digest"] == post["profiles"]["digest"],
      {"pre": pre["profiles"]["digest"], "post": post["profiles"]["digest"]})
ovr = {c["alias"]: c for c in post["profiles"]["chats"]}
manual_alias = [a for a, c in ovr.items()
                if c["checkup_override"].get("present")
                and c["checkup_override"].get("sha256", "").startswith("31d175065461")]
check("manual_chat_override_present_12469_31d17506", len(manual_alias) == 1,
      {a: {"present": ovr[a]["checkup_override"].get("present"),
           "chars": ovr[a]["checkup_override"].get("chars"),
           "sha12": ovr[a]["checkup_override"].get("sha256", "")[:12]}
       for a in ovr})

pm, po = pre["prompts"], post["prompts"]
man = po["manual_revision"]
check("manual_revision_unchanged",
      man.get("revision_id") == "rev:d31300ef35a0" and man.get("origin") == "manual"
      and man.get("retired") is False and man.get("chars") == 12469
      and man.get("sha256", "").startswith("31d175065461")
      and man == pm["manual_revision"], man)

new_acts = [a for a in po["activations"]
            if a["activation_id"] > max(x["activation_id"] for x in pm["activations"])]
details = sorted({(a["scope"], a["detail_code"], a["outcome"]) for a in new_acts})
check("new_activation_factory_activate_global",
      ("global", "factory_activate", "applied") in details, details)
check("new_activation_factory_superseded_manual_chat",
      ("chat", "factory_superseded_manual", "skipped_same") in details, details)
check("new_activations_apply_new_factory_revision",
      {a.get("factory_revision_applied") for a in new_acts} == {"fac:93c42f967ef8"},
      sorted({a.get("factory_revision_applied") for a in new_acts}))

b = post["budgets"]
check("budgets_off_everywhere",
      b["global_value"] is False and all(c["value"] is False for c in b["chats"]),
      {"global": b["global_value"], "chats": b["chats"],
       "sources": [c["source"] for c in b["chats"]]})
check("budgets_off_unchanged_vs_pre",
      pre["budgets"]["global_value"] == b["global_value"]
      and [(c["alias"], c["value"]) for c in pre["budgets"]["chats"]]
      == [(c["alias"], c["value"]) for c in b["chats"]],
      {"pre": pre["budgets"]["chats"], "post": b["chats"]})
lim = b["global_limits"]
check("mca_caps_zero",
      lim["max_total_calls"] == 0 and lim["max_metered_calls"] == 0
      and lim["max_same_call"] == 0 and lim["fuse_seconds"] == 0.0, lim)
check("capacity_intact",
      post["capacity"].get("window") == 1048576
      and post["capacity"].get("max_output") == 32768
      and post["capacity"].get("source") == "provider_catalog"
      and post["capacity"].get("confidence") == "verified",
      post["capacity"])

failed = [c["check"] for c in checks if not c["ok"]]
out = {"ok": not failed, "failed": failed, "checks": checks, "verifier": "v2",
       "pre_ts": pre["ts"], "post_ts": post["ts"]}
(run / "verify203.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
print(json.dumps({"ok": out["ok"], "failed": failed, "n_checks": len(checks),
                  "n_failed": len(failed)}, ensure_ascii=False, indent=1))
for c in checks:
    if not c["ok"]:
        print("FAILED:", c["check"], json.dumps(c["detail"], ensure_ascii=False)[:500])
