import json
from pathlib import Path

before = json.loads(Path("parity-before.json").read_text(encoding="utf-8"))["parity"]["surfaces"]
after = json.loads(Path("parity-after.json").read_text(encoding="utf-8"))["parity"]["surfaces"]
result = {}
ok = True
for name in sorted(before):
    b, a = before[name], after.get(name, {})
    match = b.get("sha256") == a.get("sha256") and b.get("http") == a.get("http")
    ok = ok and match
    result[name] = {"http_before": b.get("http"), "http_after": a.get("http"),
                    "sha256_before": b.get("sha256"), "sha256_after": a.get("sha256"),
                    "match": match}
    if name == "prompt_versions":
        for key in b.get("items", {}):
            bi = b["items"][key]
            ai = a.get("items", {}).get(key, {})
            result[name]["items"] = result[name].get("items", {})
            result[name]["items"][key] = {
                "sha256_before": bi.get("sha256"),
                "sha256_after": ai.get("sha256"),
                "match": bi.get("sha256") == ai.get("sha256"),
            }
            ok = ok and bi.get("sha256") == ai.get("sha256")
out = {"release": "2.58.197", "all_match": ok, "surfaces": result}
Path("settings-parity-2.58.197.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v["match"] for k, v in result.items()}, ensure_ascii=False))
print("all_match=", ok)

