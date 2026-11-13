"""Freeze query embeddings for the NEXT-02 final paired measurement.

The product's embedding client has a provider fallback chain with a DIFFERENT
model/base_url, so a primary-provider outage silently changes the vector space
and therefore the KNN ranking. A first baseline run was contaminated exactly
this way (O19 base slice differed from two identical repeats of the same side).

This script embeds every frozen question with the PRIMARY provider only
(fallback disabled), retries transient failures, and verifies that a second
identical request returns the identical vector. The resulting JSON is injected
into the harness so both sides use byte-identical query vectors.
"""
import asyncio
import hashlib
import json
import os
import sys

ROOT = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees" \
       r"\c742e4de9e92c489\vmq-onto-01-3689dd92710d-aaecec2a"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from dotenv import load_dotenv          # noqa: E402
load_dotenv(r"C:\Code\Python\adminbot\.env")

from config.settings import settings     # noqa: E402
from services.llm_client import LLMClient  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "next2final-embeddings.json")
SAMPLE = os.path.join(HERE, "next2final-sample.json")

TEXTS = []
with open(SAMPLE, encoding="utf-8") as fh:
    for query in json.load(fh)["queries"]:
        TEXTS.append(query["question"])


async def embed_with_retry(client, text, attempts=6):
    last = None
    for attempt in range(attempts):
        try:
            return (await client.embed([text]))[0]
        except Exception as exc:                     # noqa: BLE001
            last = exc
            await asyncio.sleep(2.0 * (attempt + 1))
    raise RuntimeError("embed failed for %r: %s" % (text[:40], last))


async def main():
    client = LLMClient(base_url=settings.LLM_BASE_URL,
                       api_key=settings.LLM_API_KEY,
                       chat_model=settings.LLM_MODEL_NAME,
                       embed_model=settings.EMBEDDING_MODEL_NAME)
    client._embed_fallback_active = False       # primary only
    out, unstable = {}, []
    for text in TEXTS:
        first = await embed_with_retry(client, text)
        second = await embed_with_retry(client, text)
        if first != second:
            unstable.append(text)
        out[text] = first
    payload = {
        "model": settings.EMBEDDING_MODEL_NAME,
        "dim": len(next(iter(out.values()))),
        "base_url_host": settings.EMBEDDING_BASE_URL,
        "n": len(out),
        "unstable_texts": unstable,
        "vectors": out,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    blob = open(OUT, "rb").read()
    print("n=%d dim=%d unstable=%d" % (len(out), payload["dim"],
                                       len(unstable)))
    print("sha256=%s bytes=%d" % (hashlib.sha256(blob).hexdigest(), len(blob)))
    print("host=", payload["base_url_host"], "model=", payload["model"])


asyncio.run(main())
