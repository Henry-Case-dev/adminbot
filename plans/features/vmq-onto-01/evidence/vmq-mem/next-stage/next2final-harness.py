"""VMQ-MEM-NEXT stage measurement harness (read-only, on a COPY of the prod DB).

Path under test (REAL product functions, code = c087253d / 2.58.188):
    DirectChatService._rag_unified_rows -> _build_rag_block

Only harness-side substitutions, all recorded in the output:
  * rerank provider: MODE=real (real configured provider) | empty (provider
    returns a VALID empty verdict `{"selected": []}`) | keep_first (deterministic)
  * RERANK_SEAM=method : replace `memory.rerank_rag_facts` itself with a double
    returning [] (second, independent form of the same empty verdict)
Nothing in the product is patched; `_cp_g` (per-chat gate) is wrapped by a
recording proxy that calls the ORIGINAL resolver.
"""
import asyncio, hashlib, json, logging, os, re, sys, time, traceback

CODE_ROOT = os.environ["CODE_ROOT"]
DB_PATH = os.environ["DB_PATH"]
OUT = os.environ["OUT"]
TAG = os.environ.get("TAG", "run")
MODE = os.environ.get("MODE", "real")          # real | empty | keep_first | fail
SEAM = os.environ.get("RERANK_SEAM", "llm")    # llm | method

sys.path.insert(0, CODE_ROOT)
from dotenv import load_dotenv as _ld
_ld(os.environ.get("ENV_FILE") or ".env")

CHAT = -1002661910336
UID = 138811255
LIMIT = 10
CAP = 2000

import services.direct_chat_service as dcs
import services.summary_memory as sm
import services.chat_params as cparams
from services.database import DatabaseService
from services.summary_memory import MemoryManager
from services.llm_client import LLMClient
from config.settings import settings

_prov = dcs._prov


class Hot:
    def __init__(self, over):
        self.over = dict(over)

    def get(self, key, default=None):
        return self.over.get(key, default)


HOT = Hot({
    "flags.graph_rag_enabled": True,
    "flags.chat_rag_rerank_enabled": os.environ.get("RERANK_ON", "1") == "1",
    "flags.relations_tone_enabled": False,
    "memory.nostalgia_layer_a_enabled": False,
    "limits.graph_rag_facts_limit": LIMIT,
    "limits.graph_rag_context_max_chars": CAP,
})
dcs.hot = HOT

#: per-chat gate calls observed at the real resolver (production chain:
#: chat override -> global hot -> env/factory default)
CPG = []
_orig_cp_g = cparams.get_chat_param


async def _rec_cp_g(chat_id, key, default=None):
    val = await _orig_cp_g(chat_id, key, default)
    CPG.append({"chat": int(chat_id), "key": str(key),
                "default": default, "resolved": val,
                "type": type(val).__name__})
    return val


dcs._cp_g = _rec_cp_g

FTS_CALLS = []
_orig_bfq = sm.build_fts_query


def _bfq(keywords, mode="prefix_or"):
    result = _orig_bfq(keywords, mode)
    FTS_CALLS.append({"mode": mode, "keywords": [str(k) for k in keywords],
                      "match": result})
    return result


sm.build_fts_query = _bfq

NUM_LINE = re.compile(r"^\s*(\d+)\.\s")
DATE_RE = re.compile(r"(\d{2})\.(20\d\d)")
YEAR_RE = re.compile(r"(20\d\d)")
FACT_RE = re.compile(r"fact:(\d+)")
MSG_RE = re.compile(r"msg:(\d+)")


class RerankStub:
    """Rerank provider double; embeddings/other attrs delegate to the real client."""

    def __init__(self, real, mode="real", keep=3):
        self._real = real
        self.mode = mode
        self.keep = keep
        self.calls = 0
        self.raw = []
        self._chat_model = "harness-empty-verdict" if mode == "empty" else None
        self._base_url = "harness://local" if mode != "real" else None

    def __getattr__(self, item):
        return getattr(self._real, item)

    async def generate(self, messages, **kwargs):
        self.calls += 1
        if self.mode == "real":
            out = await self._real.generate(messages, **kwargs)
            self.raw.append(str(out)[:300])
            return out
        prompt = "\n".join(str(m.get("content") or "") for m in messages)
        if self.mode == "fail":
            raise RuntimeError("harness: rerank provider unavailable")
        if self.mode == "empty":
            self.raw.append('{"selected": []}')
            return '{"selected": []}'
        pairs = []
        for line in prompt.splitlines():
            m = NUM_LINE.match(line)
            if not m:
                continue
            dm = DATE_RE.search(line)
            pairs.append((int(m.group(1)), int(dm.group(2)) if dm else 0))
        picked = [i for i, _y in pairs[:self.keep]] if pairs else []
        out = json.dumps({"selected": picked})
        self.raw.append(out)
        return out


class Msg:
    def __init__(self, text):
        self.text = text


def sha(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _year(row):
    return dcs._rag_row_year(row)


def years_of(rows):
    out = {}
    for row in rows:
        y = _year(row)
        out[str(y)] = out.get(str(y), 0) + 1
    return out


def parse_block(block):
    lines = [ln for ln in str(block or "").splitlines()
             if ln.strip() and not ln.startswith("<RAG_Memory")
             and not ln.startswith("</RAG_Memory")]
    years, ids = {}, []
    for ln in lines:
        ys = YEAR_RE.findall(ln)
        key = ys[0] if ys else "none"
        years[key] = years.get(key, 0) + 1
        ids.extend(FACT_RE.findall(ln))
        ids.extend(MSG_RE.findall(ln))
    return {"rows": len(lines), "years": years, "ids": ids, "lines": lines}


def parse_rag_log(line):
    """`direct: rag block | facts=.. | period_kept=.. | ...` -> dict."""
    out = {}
    for part in str(line).split("|")[1:]:
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


async def run_block(db, mem, query, policy, rerank_mode="real", keep=3,
                    subject_name=None):
    FTS_CALLS.clear()
    llm = mem.llm
    llm.mode = rerank_mode
    llm.keep = keep
    llm.calls = 0
    llm.raw = []
    CPG.clear()
    seam_calls = {"n": 0}

    orig_seam = None
    if SEAM == "method":
        orig_seam = mem.rerank_rag_facts

        async def seam_double(q, facts):
            seam_calls["n"] += 1
            # SEAM_KEEP=1 -> deterministic identity verdict (no LLM): every
            # row the retrieval produced stays in the block, identical on both
            # sides. SEAM_KEEP=0 -> valid empty verdict (strings)
            if os.environ.get("SEAM_KEEP", "0") == "1":
                return list(facts)
            return []

        mem.rerank_rag_facts = seam_double

    svc = dcs.DirectChatService(memory=mem, db=db, llm=None, aliases=None)
    captured, calls, holder = {}, [], {}
    orig_retrieve = dcs.DirectChatService.__dict__["_rag_retrieve"].__func__

    async def spy_retrieve(db_, memory, chat_id, query_, channels, limit,
                           policy_, **kw):
        started_r = time.monotonic()
        res = await orig_retrieve(db_, memory, chat_id, query_, channels,
                                 limit, policy_, **kw)
        try:
            rows = dcs.DirectChatService._rag_rows_from_result(res, limit)
        except Exception:
            rows = []
        meta = getattr(res, "period_fill", None)
        calls.append({
            "channels": list(channels), "limit": int(limit),
            "policy": policy_,
            "period_fill": bool(kw.get("period_fill")),
            "lexical_stem": bool(kw.get("lexical_stem")),
            "include_archived": bool(kw.get("include_archived")),
            "exclude_years": list(kw.get("exclude_years") or ()),
            "pool_rows": len(rows),
            "usable": sum(1 for r in rows
                          if not _prov.is_self_referential_origin(
                              r.get("origin"))),
            "pool_ids": [r.get("id") for r in rows],
            "pool_years": years_of(rows),
            "period_meta": dict(meta) if isinstance(meta, dict) else None,
            "ms": int((time.monotonic() - started_r) * 1000),
        })
        return res

    dcs.DirectChatService._rag_retrieve = staticmethod(spy_retrieve)
    orig_rows = svc._rag_unified_rows

    async def spy_rows(*a, **k):
        r = await orig_rows(*a, **k)
        holder["rows"] = r
        return r

    svc._rag_unified_rows = spy_rows
    orig_build = dcs.build_rag_context

    def spy_build(items, **kw):
        captured["items"] = [tuple(i) for i in items]
        return orig_build(items, **kw)

    class H(logging.Handler):
        def emit(self, record):
            try:
                captured.setdefault("logs", []).append(record.getMessage())
            except Exception:
                pass

    handler = H()
    lg = logging.getLogger("services.direct_chat_service")
    lg2 = logging.getLogger("services.summary_memory")
    old_level, old_level2 = lg.level, lg2.level
    lg.setLevel(logging.INFO)
    lg2.setLevel(logging.INFO)
    lg.addHandler(handler)
    lg2.addHandler(handler)
    dcs.build_rag_context = spy_build
    started = time.monotonic()
    block, err = "", None
    try:
        block, _hint = await svc._build_rag_block(
            CHAT, Msg(query), "", memory_scope=policy,
            subject_name=subject_name,
            subject_uid=UID if subject_name else None)
    except Exception:
        err = traceback.format_exc()[-1500:]
    finally:
        dcs.build_rag_context = orig_build
        lg.removeHandler(handler)
        lg2.removeHandler(handler)
        lg.setLevel(old_level)
        lg2.setLevel(old_level2)
        dcs.DirectChatService._rag_retrieve = staticmethod(orig_retrieve)
        if orig_seam is not None:
            mem.rerank_rag_facts = orig_seam
    elapsed = int((time.monotonic() - started) * 1000)

    rows = holder.get("rows")
    period_rows, protected_keys = [], set()
    _keys_fn = getattr(dcs, "_rag_period_keys", None)
    _judged_fn = getattr(dcs, "_rag_period_judged_keys", None)
    _proxy_fn = getattr(dcs, "_rag_subject_proxy_of", None)
    if isinstance(rows, list):
        try:
            period_keys = _keys_fn(rows) if _keys_fn else set()
            judged_keys = _judged_fn(rows) if _judged_fn else set()
        except Exception:
            period_keys, judged_keys = set(), set()
        for row in rows:
            if not isinstance(row, dict) or not row.get("period_fill"):
                continue
            key = row.get("item_id") or (row.get("origin"), row.get("fact"))
            proxy = _proxy_fn(row) if _proxy_fn else row.get("subject_proxy")
            in_prot = key in (period_keys - judged_keys)
            if in_prot:
                protected_keys.add(key)
            period_rows.append({
                "id": row.get("id"), "year": _year(row),
                "proxy": proxy, "protected": bool(in_prot),
                "status": row.get("status"), "origin": row.get("origin"),
                "stems_shared": row.get("stems_shared"),
                "fact": str(row.get("fact"))[:150],
            })
    info = parse_block(block)
    rag_line = ""
    for line in captured.get("logs", []):
        if line.startswith("direct: rag block"):
            rag_line = line
    rag = parse_rag_log(rag_line)
    pool = getattr(svc, "_rag_period_pool", None) or {}
    pool_rows = []
    for row in (pool.get("rows") or ()):
        if isinstance(row, dict):
            pool_rows.append({"id": row.get("id"), "year": _year(row),
                              "proxy": (_proxy_fn(row) if _proxy_fn else row.get("subject_proxy")),
                              "fact": str(row.get("fact"))[:150]})
    block_ids = set(info["ids"])
    protected_after = [str(r["id"]) for r in period_rows
                       if r["protected"] and str(r["id"]) in block_ids]
    base_call = calls[0] if calls else {}
    info.update({
        "query": query, "policy": policy, "rerank_mode": rerank_mode,
        "seam": SEAM, "keep": keep, "subject": subject_name,
        "sha_block": sha(block), "block_len": len(block),
        "sha_ids": sha("|".join(info["ids"])),
        "block_empty": not bool(str(block or "").strip()),
        "retrieval_calls": calls,
        "usable": base_call.get("usable") if "usable" in base_call else None,
        "base_slice_rows": base_call.get("pool_rows"),
        "base_slice_years": base_call.get("pool_years"),
        "base_slice_ids": base_call.get("pool_ids"),
        "rows_returned": len(rows) if isinstance(rows, list) else None,
        "rows_returned_years": years_of(rows) if isinstance(rows, list) else None,
        "rows_returned_ids": ([r.get("id") for r in rows]
                              if isinstance(rows, list) else None),
        # NEXT-02 final: full row identity (id/year/channel/proxy/text) so the
        # paired scorer can judge relevance mechanically without re-querying.
        "rows_detail": ([{
            "id": r.get("id"), "year": _year(r),
            "origin": r.get("origin"),
            "period_fill": bool(r.get("period_fill")),
            "proxy": (_proxy_fn(r) if _proxy_fn else r.get("subject_proxy")),
            "stems_shared": r.get("stems_shared"),
            "text": str(r.get("fact") or r.get("text") or "")[:400],
        } for r in rows] if isinstance(rows, list) else None),
        "period_rows": period_rows, "period_rows_n": len(period_rows),
        "period_protected_n": len(protected_keys),
        "period_protected_in_block": protected_after,
        "period_pool_rows": pool_rows,
        "period_pool_n": len(pool_rows),
        "period_stats_service": dict(getattr(svc, "_rag_period_stats", None)
                                     or {}),
        "rag_log": rag_line,
        "rag_counts": rag,
        "rerank_calls": llm.calls,
        "rerank_raw": list(llm.raw)[:4],
        "seam_calls": seam_calls["n"],
        "cp_g_calls": list(CPG),
        "block": block,
        "elapsed_ms": elapsed,
        "logs": [l for l in captured.get("logs", [])
                 if "rerank" in l][:8],
        "error": err,
    })
    return info


async def main():
    out = {"meta": {"tag": TAG, "code_root": CODE_ROOT, "db": DB_PATH,
                    "mode": MODE, "seam": SEAM, "limit": LIMIT, "cap": CAP,
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())}}
    import subprocess
    for key, ref in (("git_head", "HEAD"),
                     ("app_version_blob", "HEAD:config/settings.py"),
                     ("blob_dcs", "HEAD:services/direct_chat_service.py"),
                     ("blob_sm", "HEAD:services/summary_memory.py"),
                     ("blob_mca", "HEAD:services/mca_retrieval_context.py")):
        try:
            out["meta"][key] = subprocess.check_output(
                ["git", "-C", CODE_ROOT, "rev-parse", ref],
                text=True).strip()
        except Exception:
            out["meta"][key] = "unknown"
    sample = json.load(open(os.environ["SAMPLE"], encoding="utf-8-sig"))
    if isinstance(sample, dict):
        out["sample_meta"] = sample.get("meta")
        sample = sample["queries"]

    db = DatabaseService(DB_PATH)
    await db.initialize()
    client = LLMClient(base_url=settings.LLM_BASE_URL,
                       api_key=settings.LLM_API_KEY,
                       chat_model=settings.LLM_MODEL_NAME,
                       embed_model=settings.EMBEDDING_MODEL_NAME)
    mem = MemoryManager(db, client)
    # Frozen query embeddings: the embedding client has a provider fallback
    # chain with a DIFFERENT model/base_url, so a primary outage silently
    # changes the vector space and the KNN ranking. When EMBED_JSON is set,
    # every frozen question is embedded with the very same vector on both
    # sides; anything outside the frozen set still uses the real client.
    frozen_path = os.environ.get("EMBED_JSON")
    if frozen_path and os.path.exists(frozen_path):
        frozen = json.load(open(frozen_path, encoding="utf-8"))
        vectors = frozen["vectors"]
        orig_embed = mem._embed
        hits = {"hit": 0, "miss": 0}

        async def _frozen_embed(texts, priority=None):
            texts = list(texts)
            if all(t in vectors for t in texts):
                hits["hit"] += len(texts)
                return [vectors[t] for t in texts]
            hits["miss"] += 1
            return await orig_embed(texts, priority=priority)

        mem._embed = _frozen_embed
        out["frozen_embeddings"] = {
            "file": os.path.basename(frozen_path),
            "sha256": hashlib.sha256(open(frozen_path, "rb").read()).hexdigest(),
            "model": frozen.get("model"), "n": frozen.get("n"),
            "dim": frozen.get("dim"), "hits": hits,
        }
    out["vec"] = {"available": bool(await mem.initialize()),
                  "dim": getattr(mem, "_vec_dim", None),
                  "off_reason": getattr(mem, "_vec_off_reason", None)}
    out["config"] = {
        "rerank_flag_settings_default": settings.CHAT_RAG_RERANK_ENABLED,
        "typed_reranker": getattr(settings, "MCA_TYPED_RERANKER_ENABLED", None),
        "graph_rag_enabled": settings.GRAPH_RAG_ENABLED,
        "facts_limit_runtime": LIMIT,
        "context_max_chars_runtime": CAP,
        "llm_model": settings.LLM_MODEL_NAME,
        "embed_model": settings.EMBEDDING_MODEL_NAME,
        "llm_base_host": settings.LLM_BASE_URL,
    }
    mem.llm = RerankStub(client, MODE, 3)
    # probe the period vector guard once, before the questions
    try:
        guard = await mem._period_vector_guard()
    except Exception:
        guard = "ERR:%s" % traceback.format_exc()[-200:]
    out["vec"]["period_guard"] = guard
    try:
        out["vec"]["identity_fp"] = mem._identity_fingerprint()
    except Exception:
        pass

    started_batch = time.monotonic()
    deadline = started_batch + float(os.environ.get("BATCH_CAP_S", "1500"))
    per_q = float(os.environ.get("Q_CAP_S", "180"))
    out["meta"]["batch_cap_s"] = deadline - started_batch
    out["meta"]["q_cap_s"] = per_q
    done, missing = [], []
    for item in sample:
        if time.monotonic() > deadline:
            missing.extend([x["key"] for x in sample
                            if x["key"] not in done])
            print("BATCH_CAP_REACHED; missing=", missing, flush=True)
            break
        anchor = item.get("anchor")
        row = None
        if anchor is not None:
            cur = await db.db.execute(
                "SELECT id, fact, origin, status, "
                "COALESCE(message_timestamp, created_at) ts FROM graph_facts "
                "WHERE id=?", (anchor,))
            row = await cur.fetchone()
            await cur.close()
        rec = dict(item)
        rec["anchor_row"] = (dict(row) if row else None)
        rec["runs"] = {}
        for policy in ("historical", "auto"):
            t0 = time.monotonic()
            try:
                r = await asyncio.wait_for(
                    run_block(db, mem, item["question"], policy, MODE, 3, None),
                    timeout=per_q)
            except asyncio.TimeoutError:
                rec["runs"][policy] = {"timeout": True, "q_cap_s": per_q}
                print("Q %s %s TIMEOUT after %ss" % (item["key"], policy,
                                                     per_q), flush=True)
                continue
            r["q_ms"] = int((time.monotonic() - t0) * 1000)
            anc = str(anchor) if anchor is not None else None
            r["anchor_in_block"] = bool(anc and anc in r["ids"])
            r["anchor_in_rows"] = bool(
                anc and anc in [str(x) for x in
                                (r.get("rows_returned_ids") or [])])
            r["anchor_in_base"] = bool(
                anc and anc in [str(x) for x in (r.get("base_slice_ids") or [])])
            extra = [c for c in r["retrieval_calls"] if c.get("period_fill")]
            r["anchor_in_period_pool"] = bool(
                anc and any(anc in [str(x) for x in c["pool_ids"]]
                            for c in extra))
            if anc:
                vids = []
                for c in extra:
                    pm = c.get("period_meta") or {}
                    if int(pm.get("vector_rows") or 0) > 0:
                        vids = [str(x) for x in c["pool_ids"]]
                r["period_pool_ids_with_vector_rows"] = vids
                r["anchor_in_period_pool_vector_leg"] = anc in vids
            r.pop("fts_calls", None)
            rec["runs"][policy] = r
        # compact stdout line per question/policy
        for policy, r in rec["runs"].items():
            if r.get("timeout"):
                continue
            print("Q %s %-10s anchor_in_block=%s period_rows=%d "
                  "protected=%s kept=%s despite_empty=%s leg=%s vrows=%s "
                  "miss=%s block_rows=%d rerank=%d %s"
                  % (item["key"], policy, r["anchor_in_block"],
                     r["period_rows_n"], r["period_protected_n"],
                     r["rag_counts"].get("period_kept"),
                     r["rag_counts"].get("period_kept_despite_empty"),
                     r["rag_counts"].get("period_vector_leg"),
                     r["period_stats_service"].get("vector_rows"),
                     r["rag_counts"].get("vector_pool_miss"),
                     r["ids"] and len(r["ids"]) or 0,
                     r["rerank_calls"],
                     ("ERR" if r["error"] else "")), flush=True)
        out.setdefault("items", []).append(rec)
        done.append(item["key"])
        # partial durable write after EVERY question (results survive a kill)
        out["meta"]["completed"] = list(done)
        out["meta"]["missing"] = [x["key"] for x in sample
                                 if x["key"] not in done]
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)

    out["meta"]["completed"] = list(done)
    out["meta"]["missing"] = [x["key"] for x in sample if x["key"] not in done]
    out["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime())
    out["meta"]["batch_s"] = round(time.monotonic() - started_batch, 1)

    out["meta"]["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime())
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("WROTE", OUT)
    await db.db.close()


if __name__ == "__main__":
    asyncio.run(main())

