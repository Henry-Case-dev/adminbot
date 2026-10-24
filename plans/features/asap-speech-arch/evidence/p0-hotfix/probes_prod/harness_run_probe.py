"""Run one LLM call per payload (same provider/model/temperature) and save raw."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time

import urllib.request

REPO = r"C:\Code\Python\adminbot"


def env_val(key: str) -> str:
    for line in open(os.path.join(REPO, ".env"), encoding="utf-8", errors="replace"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("missing " + key)


def sha12(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = json.load(open(args.payload, encoding="utf-8"))
    base = env_val("LLM_BASE_URL").rstrip("/")
    key = env_val("LLM_API_KEY")
    model = env_val("LLM_MODEL_NAME")
    body = {
        "model": model,
        "messages": data["messages"],
        "temperature": 0.7,
        "max_tokens": 2400,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key},
        method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except Exception as exc:                      # noqa: BLE001
        raw = json.dumps({"error": "%s: %s" % (type(exc).__name__, str(exc)[:300])})
        status = -1
    elapsed = round(time.time() - t0, 2)
    try:
        parsed = json.loads(raw)
        text = (parsed.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        usage = parsed.get("usage")
        err = parsed.get("error")
    except Exception:
        text, usage, err = "", None, "unparsable"
    out = {
        "variant": data["variant"], "case": data["case"],
        "route": data["route"],
        "model": model, "temperature": 0.7, "max_tokens": 2400,
        "system_chars": data["system_chars"], "system_sha12": data["system_sha12"],
        "user_chars": data["user_chars"], "user_sha12": data["user_sha12"],
        "http_status": status, "elapsed_s": elapsed,
        "usage": usage, "error": err,
        "response_chars": len(text),
        "response_sha12": sha12(text) if text else "",
        "response": text,
        "raw_envelope_sha12": sha12(raw),
    }
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ("variant", "case", "http_status",
                                          "elapsed_s", "response_chars",
                                          "response_sha12", "system_chars",
                                          "usage")}, ensure_ascii=False))
    if text:
        print("--- head ---")
        print(text[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
