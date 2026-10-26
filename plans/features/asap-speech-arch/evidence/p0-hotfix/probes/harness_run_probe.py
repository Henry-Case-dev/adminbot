"""P0 probe runner: one provider/model/temperature for old and new payloads.

Reads the API key from the local .env, never prints or persists it.
Only synthetic L2 context is used; no Telegram, no production.
"""
from __future__ import annotations

import concurrent.futures as cf
import io
import json
import os
import time
import urllib.error
import urllib.request

SCRATCH = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\p0-probes"
ENV = r"C:\Code\Python\adminbot\.env"
OUTDIR = os.path.join(SCRATCH, "raw")
TEMPERATURE = 0.7
MAX_TOKENS = 2400


def read_env() -> dict:
    data = {}
    for line in io.open(ENV, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def call(base_url: str, key: str, model: str, messages: list) -> dict:
    body = json.dumps({"model": model, "messages": messages,
                       "temperature": TEMPERATURE,
                       "max_tokens": MAX_TOKENS}).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        return {"ok": False, "error": f"HTTP {exc.code}: {detail}",
                "latency_s": round(time.time() - t0, 2)}
    except Exception as exc:  # noqa: BLE001 - probe must record, not crash
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "latency_s": round(time.time() - t0, 2)}
    latency = round(time.time() - t0, 2)
    try:
        text = payload["choices"][0]["message"]["content"] or ""
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "no choices in response",
                "latency_s": latency,
                "raw_envelope": json.dumps(payload)[:2000]}
    usage = payload.get("usage") or {}
    return {"ok": True, "text": text, "latency_s": latency,
            "usage": {k: usage.get(k) for k in
                      ("prompt_tokens", "completion_tokens", "total_tokens")},
            "response_model": payload.get("model")}


def run_one(payload_doc: dict, base_url: str, key: str, model: str) -> dict:
    variant = payload_doc["variant"]
    case = payload_doc["case"]
    out = dict(payload_doc)
    out["api"] = call(base_url, key, model, payload_doc["messages"])
    out["temperature"] = TEMPERATURE
    out["max_tokens"] = MAX_TOKENS
    return out


def main() -> int:
    env = read_env()
    base_url = env["LLM_BASE_URL"]
    model = env["LLM_MODEL_NAME"]
    key = env["LLM_API_KEY"]
    os.makedirs(OUTDIR, exist_ok=True)

    jobs = []
    for variant in ("old", "new"):
        doc = json.load(io.open(os.path.join(SCRATCH, f"payload_{variant}.json"),
                                encoding="utf-8"))
        for cid, item in doc["payloads"].items():
            jobs.append((variant, cid, item))

    results = {}

    def work(job):
        variant, cid, item = job
        doc = {"variant": variant, "case": cid,
               "route": item["route"], "user": item["user"],
               "note": item["note"], "messages": item["messages"],
               "system_chars": item["system_chars"],
               "system_sha12": item["system_sha12"],
               "core_used_chars": item["core_used_chars"],
               "core_sha12": item["core_sha12"]}
        return (variant, cid), run_one(doc, base_url, key, model)

    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for key_, value in pool.map(work, jobs):
            results["/".join(key_)] = value
            print(key_, value["api"]["ok"], value["api"].get("latency_s"),
                  len(value["api"].get("text") or ""), flush=True)

    meta = {"provider_base_url": base_url, "model": model,
            "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    io.open(os.path.join(OUTDIR, "results.json"), "w", encoding="utf-8").write(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False,
                   indent=1))
    print("saved", os.path.join(OUTDIR, "results.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
