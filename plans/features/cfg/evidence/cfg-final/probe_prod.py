# -*- coding: utf-8 -*-
"""CFG-FINAL F1 prod probes v2 (read-only HTTPS): 2.58.104 @ 8ea6ed4e.

ADD-2.2: секция «Лимиты генерации» в отданных байтах + factory OFF default.
ADD-2.4: deployed_probe (healthz/assets) + bytes identity (raw) + SUBST delta
         + served markers (те же метрики, что rel97 served_markers.py).
ADD-2.5: glass invariant (git blob ID c2ad97d4... + served==git + #lg-lens +
         scale="32" + polygon не менялся с 99f5672c).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import time

import httpx

ROOT = r"C:\Code\Python\adminbot"
BASE = "https://admin-bot.duckdns.org"
DEPLOYED = "8ea6ed4e016cf8fbb23e1447cb02503c54131650"
ACCEPT_97 = "99f5672c"
VERSION = "2.58.104"


def git_bytes(commit, path):
    return subprocess.run(["git", "show", "%s:%s" % (commit, path)], cwd=ROOT,
                          capture_output=True).stdout


def git_blob_id(commit, path):
    out = subprocess.run(["git", "ls-tree", commit, "--", path], cwd=ROOT,
                         capture_output=True, text=True).stdout
    m = re.search(r"blob ([0-9a-f]{40})", out)
    return m.group(1) if m else None


def sha256(b):
    return hashlib.sha256(b).hexdigest()


out = {"now_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "base": BASE, "expected_deployed": DEPLOYED, "version": VERSION}

with httpx.Client(base_url=BASE, timeout=30.0,
                  headers={"User-Agent": "cfg-final-f1/1.0"}) as c:
    h = c.get("/healthz")
    out["healthz"] = {"http": h.status_code, "body": h.text[:200]}
    idx = c.get("/web/")
    html = idx.content
    app = c.get("/web/app.js")
    css_raw = c.get("/web/static/app.css")
    css_subst = c.get("/static/app.css")
    poly = c.get("/web/static/polygon-background.js")

out["assets"] = {
    "/web/": {"http": idx.status_code, "bytes": len(html),
              "sha256_12": sha256(html)[:12]},
    "/web/app.js": {"http": app.status_code, "bytes": len(app.content),
                    "sha256_12": sha256(app.content)[:12]},
    "/web/static/app.css (raw)": {"http": css_raw.status_code,
                                  "bytes": len(css_raw.content),
                                  "sha256_12": sha256(css_raw.content)[:12]},
    "/static/app.css (subst)": {"http": css_subst.status_code,
                                "bytes": len(css_subst.content),
                                "sha256_12": sha256(css_subst.content)[:12]},
    "/web/static/polygon-background.js": {
        "http": poly.status_code, "bytes": len(poly.content),
        "sha256_12": sha256(poly.content)[:12]},
}

# ── ADD-2.4: bytes identity (raw assets) vs deployed commit ──────────────────
ident = {}
for path, served in (("web/app.js", app.content),
                     ("web/static/app.css", css_raw.content),
                     ("web/static/polygon-background.js", poly.content)):
    gb = git_bytes(DEPLOYED, path)
    ident[path] = {"git_content_sha256_12": sha256(gb)[:12],
                   "served_sha256_12": sha256(served)[:12],
                   "byte_identical": gb == served}
out["bytes_identity_raw_vs_8ea6ed4e"] = ident

# SUBST delta для /static/app.css: ровно подстановка __APP_VERSION__
raw_lines = css_raw.content.decode("utf-8", "replace").splitlines()
sub_lines = css_subst.content.decode("utf-8", "replace").splitlines()
diff_rows = []
if len(raw_lines) == len(sub_lines):
    for a, b in zip(raw_lines, sub_lines):
        if a != b:
            diff_rows.append({"raw_has_placeholder": "__APP_VERSION__" in a,
                              "subst_has_version": VERSION in b,
                              "raw_12": sha256(a.encode())[:12]})
subst_ok = (len(diff_rows) >= 1
            and all(r["raw_has_placeholder"] and r["subst_has_version"]
                    for r in diff_rows))
out["subst_css_delta"] = {"line_counts_equal": len(raw_lines) == len(sub_lines),
                          "diff_lines": len(diff_rows),
                          "all_placeholder_substitution": subst_ok}

# ── ADD-2.4: served markers (метрики served_markers.py rel97) ────────────────
text = html.decode("utf-8", "replace")
jst = app.content.decode("utf-8", "replace")
ct_raw = css_raw.content.decode("utf-8", "replace")
ct_sub = css_subst.content.decode("utf-8", "replace")
out["served_markers"] = {
    "PAGE_VER_index": sum(1 for l in text.splitlines() if VERSION in l),
    "SUBST_CSS": sum(1 for l in ct_sub.splitlines() if VERSION in l),
    "STICKY_SAVE_SERVED": sum(1 for l in text.splitlines() if "sticky-save" in l),
    "CFG04_SAVE_INDICATOR": text.count("data-save-indicator"),
    "CFG04_TECH_KEY_LINES": sum(1 for l in text.splitlines() if "tech-key" in l),
    "CFG04_KB_OFFSET_CSS": sum(1 for l in ct_raw.splitlines()
                               if "--kb-offset" in l),
    "CFG04_SAFE_AREA": sum(1 for l in ct_raw.splitlines()
                           if "safe-area-inset-bottom" in l),
    "app_js_sticky_save": jst.count("sticky-save"),
}

# ── ADD-2.2: секция «Лимиты генерации» + factory OFF default ─────────────────
st_txt = git_bytes(DEPLOYED, "config/settings.py").decode("utf-8", "replace")
freq_def = re.search(
    r"IMAGE_FREQ_LIMIT_ENABLED: bool = _env_bool\(\s*\"IMAGE_FREQ_LIMIT_"
    r"ENABLED\",\s*(True|False)", st_txt)
out["add22_limits"] = {
    "app_js_section_limits_images_hits": jst.count("Лимиты генерации"),
    "app_js_user_images_isolation_note": "Пользовательские изображения" in jst,
    "app_js_covers_isolation_note": "обложки сводок" in jst,
    "factory_freq_default_line_found": bool(freq_def),
    "factory_freq_default_value": freq_def.group(1) if freq_def else None,
}

# ── ADD-2.5: glass invariant ─────────────────────────────────────────────────
blob_id = git_blob_id(DEPLOYED, "web/static/polygon-background.js")
poly_changed = subprocess.run(
    ["git", "diff", "--name-only", ACCEPT_97, DEPLOYED, "--",
     "web/static/polygon-background.js"], cwd=ROOT, capture_output=True,
    text=True).stdout.split()
lens_html = re.search(r"id=\"lg-lens\"", text)
out["add25_glass"] = {
    "git_blob_id": blob_id,
    "git_blob_id_matches_c2ad97d4": bool(blob_id
                                         and blob_id.startswith("c2ad97d4")),
    "served_equals_git_content": ident["web/static/polygon-background.js"][
        "byte_identical"],
    "polygon_unchanged_since_99f5672c": not poly_changed,
    "lg_lens_in_served_index": bool(lens_html),
    "scale_32_present": ('scale="32"' in text) or ('scale="32"' in jst),
}

# ── вердикты ─────────────────────────────────────────────────────────────────
out["verdict"] = {
    "healthz_258104": out["healthz"]["http"] == 200
    and VERSION in out["healthz"]["body"],
    "bytes_identity_raw_all": all(v["byte_identical"]
                                  for v in ident.values()),
    "subst_delta_only_version": subst_ok,
    "add22_section_and_off_default": (
        out["add22_limits"]["app_js_section_limits_images_hits"] >= 3
        and out["add22_limits"]["factory_freq_default_value"] == "False"),
    "add25_glass_invariant": all(out["add25_glass"].values()),
}
out["verdict"]["PASS"] = all(out["verdict"].values())

with io.open(ROOT + r"\OPENCODE_WORKFLOW_SCRATCH\cfg-final\probe-prod-104.json",
             "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
print(json.dumps({"verdict": out["verdict"], "assets": out["assets"],
                  "served_markers": out["served_markers"],
                  "add22": out["add22_limits"],
                  "add25": out["add25_glass"],
                  "subst": out["subst_css_delta"]}, ensure_ascii=False,
                 indent=1))
