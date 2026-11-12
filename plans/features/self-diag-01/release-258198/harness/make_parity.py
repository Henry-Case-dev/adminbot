import json
from pathlib import Path

run = Path(r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\self-diag-01-0ccfa8fbf52b\probe-5da2b593e3")
before = json.loads((run / "parity-before.json").read_text(encoding="utf-8"))["parity"]
after = json.loads((run / "parity-after.json").read_text(encoding="utf-8"))["parity"]
items = json.loads((run / "parity-items-diff.json").read_text(encoding="utf-8"))

SAVED = ("meme_settings_saved_-1004482340693", "meme_settings_saved_-1002661910336")
out = {
    "release": "2.58.198",
    "before": {"taken_at_utc": before["taken_at_utc"], "prod_version": "2.58.197"},
    "after": {"taken_at_utc": after["taken_at_utc"], "prod_version": "2.58.198"},
    "surfaces_equal": {},
    "saved_prompt_settings_unchanged": {},
    "config_items": items,
    "notes": [
        "surface sha256: config_global/config_chat changed only because the catalog gained"
        " exactly one approved key flags.self_diag_repo_origin (see config_items: added 1,"
        " changed 0, removed 0); chat surfaces also carry the volatile modules/3/gate/observed_at",
        "meme-settings raw payload churns in analytics.attempts/* (live operational data);"
        " the SAVED blocks hash is byte-identical for both chats",
        "prompts catalog + 4 prompt version sets + overrides-map are byte-identical",
        "chat_params: latest per-item updated_at stays 2026-11-11T12:33:23Z; no saved value rewritten",
    ],
}
for name, b in before["surfaces"].items():
    a = after["surfaces"].get(name) or {}
    out["surfaces_equal"][name] = {
        "http_before": b.get("http"), "http_after": a.get("http"),
        "sha256_before": b.get("sha256"), "sha256_after": a.get("sha256"),
        "equal": b.get("sha256") == a.get("sha256"),
    }
for name in SAVED:
    out["saved_prompt_settings_unchanged"][name] = out["surfaces_equal"][name]["equal"]

(run / "settings-parity-2.58.198.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if k != "config_items"}, ensure_ascii=False, indent=1)[:2500])
