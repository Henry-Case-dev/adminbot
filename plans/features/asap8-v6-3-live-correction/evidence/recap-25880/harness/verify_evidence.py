"""RECAP-25880 — verify the evidence set (whole-viewport proof + fix checks)."""
import json
import os

OUT = r"C:\Code\Python\adminbot\plans\features\asap8-v6-3-live-correction\evidence\recap-25880"
EXPECT_VP = {(320, 700), (360, 780), (390, 844), (430, 932),
             (768, 1024), (1024, 768), (1440, 900), (667, 375)}

pf = json.load(open(os.path.join(OUT, "fingerprint.json"), encoding="utf-8"))
st = json.load(open(os.path.join(OUT, "capture_states.json"), encoding="utf-8"))
idx = json.load(open(os.path.join(OUT, "png_index.json"), encoding="utf-8"))

checks = {}
# 1. fingerprint vs deployed
checks["fingerprint.head_match"] = pf["head_match"]
checks["fingerprint.all_files_match"] = pf["all_match"]
checks["fingerprint.code_paths_clean"] = pf["code_paths_dirty"] is None

# 2. served CSS (deployed fix 1)
css = st["served_css"]
checks["css.served_right_formula_x3"] = css["right_formula_count"] == 3
checks["css.served_sha256_equals_worktree_file"] = css["file_sha256_match"]
checks["css.top_formula_present"] = css["top_formula_count"] >= 1
checks["css.left_formula_present"] = css["left_formula_count"] >= 1

# 3. whole-viewport proof: PNG IHDR == requested viewport for matrix+cover
matrix_bad = []
for key, m in st["states"].items():
    surface, tag = key.split("/")
    if surface in ("status", "analytics_overview", "analytics_processes",
                   "modules", "editor_prompts", "cover_editor"):
        w, h = (int(x) for x in tag.split("x"))
        fn = st["prefix"] + ("%s_%s.png" % (surface, tag))
        dims = idx["files"].get(fn)
        if not dims or (dims["width"], dims["height"]) != (w, h):
            matrix_bad.append({"file": fn, "want": [w, h],
                               "got": dims and [dims["width"], dims["height"]]})
checks["png.matrix_is_whole_viewport"] = not matrix_bad
checks["png.matrix_offenders"] = matrix_bad

# 4. matrix completeness: 6 surfaces x 8 viewports
missing = []
for surface in ("status", "analytics_overview", "analytics_processes",
                "modules", "editor_prompts", "cover_editor"):
    for (w, h) in sorted(EXPECT_VP):
        fn = st["prefix"] + ("%s_%dx%d.png" % (surface, w, h))
        if fn not in idx["files"]:
            missing.append(fn)
checks["png.matrix_48_files_present"] = not missing
checks["png.matrix_missing"] = missing

# 5. deployed fix 2 — L1 Planner entry in the Direct prompt library
l1_bad = [k for k, v in st["states"].items()
          if k.startswith("editor_prompts/") and not v["l1PromptPresent"]]
checks["l1.entry_present_all_8_viewports"] = not l1_bad
checks["l1.entry_missing_states"] = l1_bad
focus = [v for k, v in st["states"].items()
         if k.startswith("editor_prompts_l1_focus/")]
checks["l1.focus_editor_opened"] = bool(focus) and all(
    v["promptTextarea"] and v["promptTextarea"]["key"] ==
    "prompts.direct_l1_planner_system_prompt" for v in focus)
checks["l1.focus_textarea_lens"] = [v["promptTextarea"] for v in focus]

# 5b. whole-viewport proof for the extra states too (filename tag == IHDR)
#     suite_w2_fullscreen/* are DSF=2 captures -> width/height or 2x accepted.
import re
dim_bad = []
for fn, meta in idx["files"].items():
    dsf2 = fn.replace("\\", "/").startswith("suite_w2_fullscreen/")
    m = re.search(r"_(\d{3,4})x(\d{3,4})\.png$", fn)
    m1b = re.search(r"_(\d{3,4})_(\d{3,4})\.png$", fn)  # suite style 667_375
    if m or m1b:
        mm = m or m1b
        w, h = int(mm.group(1)), int(mm.group(2))
        ok = (meta["width"], meta["height"]) == (w, h) or (
            dsf2 and (meta["width"], meta["height"]) == (2 * w, 2 * h))
        if not ok:
            dim_bad.append({"file": fn, "want": [w, h],
                            "got": [meta["width"], meta["height"]]})
    else:
        m2 = re.search(r"_(\d{3,4})\.png$", fn)   # suite S* shots: width only
        if m2:
            w = int(m2.group(1))
            ok = meta["width"] == w or (dsf2 and meta["width"] == 2 * w)
            if not ok:
                dim_bad.append({"file": fn, "want_w": w,
                                "got_w": meta["width"]})
checks["png.all_named_dimensions_match_ihdr"] = not dim_bad
checks["png.dim_offenders"] = dim_bad

# 6. U07.2 safe-area geometry (deployed fix 1, live computed style)
inset_bad = [k for k, v in st["states"].items()
             if k.startswith("rowa_") and not v.get("inset_ok")]
checks["rowa.inset_geometry_ok"] = not inset_bad
checks["rowa.inset_bad"] = inset_bad

# 7. console errors
checks["console_errors_empty"] = not st["console_errors"]
checks["console_errors"] = st["console_errors"][:5]

hard = [k for k, v in checks.items() if isinstance(v, bool) and not v]
summary = {"all_hard_pass": not hard, "failed": hard,
           "states": len(st["states"]), "pngs_indexed": idx["count"],
           "hOverflow_states": {k: v["hOverflow"] for k, v in st["states"].items()
                                if v.get("hOverflow")},
           "checks": checks}
with open(os.path.join(OUT, "verify_summary.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
print(json.dumps(summary, ensure_ascii=False, indent=1))
return_ = 0 if summary["all_hard_pass"] else 1
raise SystemExit(return_)
