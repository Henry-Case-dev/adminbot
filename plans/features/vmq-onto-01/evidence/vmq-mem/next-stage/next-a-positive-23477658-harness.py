"""VMQ-NEXT-03/04 positive-case harness: REAL `_build_rag_block` ->
`_rag_unified_rows` on a derivative of the prod-DB copy.

Product is NOT patched. Instrumentation only:
  * spy on `_rag_retrieve` (calls the original) -> base/period call evidence
  * spy on `_rag_unified_rows` (calls the original) -> returned rows
  * spy on `build_rag_context` (calls the original) -> rendered items
  * `_cp_g` wrapped by a recording proxy that calls the ORIGINAL resolver
  * MODE=empty -> the configured LLM client double returns `{"selected": []}`
    (product's own typed parser decides validity; response is logged)
"""
import asyncio, hashlib, json, logging, os, re, sqlite3, sys, time, traceback

CODE_ROOT = os.environ["CODE_ROOT"]
SRC_DB = os.environ["SRC_DB"]
OUT = os.environ["OUT"]
DERIV = os.environ["DERIV"]
TAG = os.environ.get("TAG", "run")
MODE = os.environ.get("MODE", "real")   # real | empty
SEAM = os.environ.get("RERANK_SEAM", "llm")   # llm | method
ENV_FILE = os.environ.get("ENV_FILE") or os.path.join(CODE_ROOT, ".env")

sys.path.insert(0, CODE_ROOT)
from dotenv import load_dotenv as _ld
_ld(ENV_FILE)

from config.settings import settings
import services.direct_chat_service as dcs
import services.summary_memory as sm
import services.chat_params as cparams
from services.database import DatabaseService
from services.summary_memory import MemoryManager
from services.llm_client import LLMClient

CHAT = -1002661910336
UID = 138811255
LIMIT = 10
CAP = 2000
NUM_LINE = re.compile(r"^\s*(\d+)\.\s")
DATE_RE = re.compile(r"(\d{2})\.(20\d\d)")
YEAR_RE = re.compile(r"(20\d\d)")
FACT_RE = re.compile(r"fact:(\d+)")
MSG_RE = re.compile(r"msg:(\d+)")


class Hot:
    def __init__(self, over):
        self.over = dict(over)

    def get(self, key, default=None):
        return self.over.get(key, default)


HOT = Hot({
    "flags.graph_rag_enabled": True,
    "flags.chat_rag_rerank_enabled": True,
    "flags.relations_tone_enabled": False,
    "memory.nostalgia_layer_a_enabled": False,
    "limits.graph_rag_facts_limit": LIMIT,
    "limits.graph_rag_context_max_chars": CAP,
})
dcs.hot = HOT

CPG = []
_orig_cp_g = cparams.get_chat_param


async def _rec_cp_g(chat_id, key, default=None):
    val = await _orig_cp_g(chat_id, key, default)
    CPG.append({"chat": int(chat_id), "key": str(key), "default": default,
                "resolved": val, "type": type(val).__name__})
    return val


dcs._cp_g = _rec_cp_g


class RerankStub:
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
            self.raw.append(str(out)[:400])
            return out
        if self.mode == "empty":
            self.raw.append('{"selected": []}')
            return '{"selected": []}'
        self.raw.append('{"selected": []}')
        return '{"selected": []}'


class Msg:
    def __init__(self, text):
        self.text = text


def sha(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def year_of(row):
    return dcs._rag_row_year(row)


def years_of(rows):
    out = {}
    for row in rows:
        y = year_of(row)
        out[str(y)] = out.get(str(y), 0) + 1
    return out


def make_deriv():
    if os.path.exists(DERIV):
        return
    src = sqlite3.connect("file:%s?mode=ro" % SRC_DB.replace("\\", "/"), uri=True)
    dst = sqlite3.connect(DERIV)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()


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
    out = {}
    for part in str(line).split("|")[1:]:
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


async def run_block(db, mem, query, policy, mode):
    dcs.hot = HOT
    llm = mem.llm
    llm.mode = mode
    llm.calls = 0
    llm.raw = []
    CPG.clear()
    svc = dcs.DirectChatService(memory=mem, db=db, llm=None, aliases=None)
    captured, calls, holder = {}, [], {}
    seam_calls = {"n": 0}
    orig_seam = None
    if SEAM == "method":
        orig_seam = mem.rerank_rag_facts

        async def seam_double(q, facts):
            seam_calls["n"] += 1
            return []

        mem.rerank_rag_facts = seam_double
    orig_retrieve = dcs.DirectChatService.__dict__["_rag_retrieve"].__func__

    async def spy_retrieve(db_, memory, chat_id, query_, channels, limit,
                           policy_, **kw):
        t0 = time.monotonic()
        res = await orig_retrieve(db_, memory, chat_id, query_, channels,
                                  limit, policy_, **kw)
        try:
            rows = dcs.DirectChatService._rag_rows_from_result(res, limit)
        except Exception:
            rows = []
        calls.append({
            "channels": list(channels), "limit": int(limit), "policy": policy_,
            "period_fill": bool(kw.get("period_fill")),
            "lexical_stem": bool(kw.get("lexical_stem")),
            "include_archived": bool(kw.get("include_archived")),
            "exclude_years": sorted(kw.get("exclude_years") or ()),
            "pool_rows": len(rows), "pool_ids": [r.get("id") for r in rows],
            "pool_years": years_of(rows),
            "period_meta": (dict(getattr(res, "period_fill", None) or {})
                            if isinstance(getattr(res, "period_fill", None), dict)
                            else None),
            "ms": int((time.monotonic() - t0) * 1000)})
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
                captured.setdefault("logs", []).append(
                    "%s::%s" % (record.name, record.getMessage()))
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
            CHAT, Msg(query), "", memory_scope=policy, subject_name=None,
            subject_uid=None)
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
    period_keys = dcs._rag_period_keys(rows) if isinstance(rows, list) else set()
    judged_keys = dcs._rag_period_judged_keys(rows) if isinstance(rows, list) else set()
    protected_keys = period_keys - judged_keys
    period_rows = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not row.get("period_fill"):
                continue
            key = row.get("item_id") or (row.get("origin"), row.get("fact"))
            period_rows.append({
                "id": row.get("id"), "year": year_of(row),
                "proxy": dcs._rag_subject_proxy_of(row),
                "protected": key in protected_keys,
                "stems_shared": row.get("stems_shared"),
                "stems_shared_reason": row.get("stems_shared_reason"),
                "fact": str(row.get("fact"))[:160]})
    pool = getattr(svc, "_rag_period_pool", None) or {}
    pool_rows = []
    for row in (pool.get("rows") or ()):
        if not isinstance(row, dict):
            continue
        pool_rows.append({
            "id": row.get("id"), "year": year_of(row),
            "proxy": dcs._rag_subject_proxy_of(row),
            "stems_shared": row.get("stems_shared"),
            "stems_shared_reason": row.get("stems_shared_reason"),
            "recheck_shared": dcs._rag_subject_shared(
                dcs._rag_subject_stems(query), row.get("fact")),
            "fact": str(row.get("fact"))[:160]})
    info = parse_block(block)
    rag_line = ""
    for line in captured.get("logs", []):
        if "direct: rag block" in line:
            rag_line = line
    typed_empty = [l for l in captured.get("logs", [])
                   if "valid EMPTY" in l or "valid EMPTY" in str(l)]
    block_ids = set(info["ids"])
    out = {
        "query": query, "policy": policy, "mode": MODE, "qa_key": TAG,
        "seam": SEAM, "seam_calls": seam_calls["n"],
        "sha_block": sha(block), "block_len": len(block),
        "block_empty": not bool(str(block or "").strip()),
        "block": block,
        "block_ids": info["ids"], "block_rows": info["rows"],
        "block_years": info["years"],
        "retrieval_calls": calls,
        "rows_returned_n": len(rows) if isinstance(rows, list) else None,
        "rows_returned": ([{"id": r.get("id"), "year": year_of(r),
                            "period_fill": bool(r.get("period_fill")),
                            "proxy": dcs._rag_subject_proxy_of(r),
                            "stems_shared": r.get("stems_shared")}
                           for r in rows] if isinstance(rows, list) else None),
        "period_rows": period_rows,
        "period_protected_n": len(protected_keys),
        "period_protected_in_block": [str(r["id"]) for r in period_rows
                                      if r["protected"] and str(r["id"]) in block_ids],
        "period_pool_n": len(pool_rows), "period_pool_rows": pool_rows,
        "period_stats_service": dict(getattr(svc, "_rag_period_stats", None) or {}),
        "rag_log": rag_line, "rag_counts": parse_rag_log(rag_line),
        "typed_empty_log": typed_empty[:4],
        "rerank_calls": llm.calls, "rerank_raw": list(llm.raw)[:4],
        "cp_g_calls": list(CPG),
        "rendered_items": len(captured.get("items") or ()),
        "elapsed_ms": elapsed, "error": err,
    }
    return out


async def main():
    make_deriv()
    import subprocess
    meta = {"tag": TAG, "mode": MODE, "code_root": CODE_ROOT, "db": DERIV,
            "src_db": SRC_DB,
            "channels": list(dcs.DirectChatService._RAG_FACT_CHANNELS),
            "period_channels": list(dcs.DirectChatService._RAG_PERIOD_CHANNELS),
            "period_pool": dcs.DirectChatService._RAG_PERIOD_POOL,
            "min_stems": dcs.DirectChatService._RAG_PERIOD_MIN_STEMS,
            "slot_div": dcs.DirectChatService._RAG_PERIOD_SLOT_DIV,
            "limit": LIMIT, "cap": CAP,
            "seam": SEAM, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    for key, ref in (("git_head", "HEAD"),
                     ("blob_dcs", "HEAD:services/direct_chat_service.py"),
                     ("blob_mca", "HEAD:services/mca_retrieval_context.py"),
                     ("blob_sm", "HEAD:services/summary_memory.py")):
        try:
            meta[key] = subprocess.check_output(
                ["git", "-C", CODE_ROOT, "rev-parse", ref], text=True).strip()
        except Exception:
            meta[key] = "unknown"

    db = DatabaseService(DERIV)
    await db.initialize()
    client = LLMClient(base_url=settings.LLM_BASE_URL,
                       api_key=settings.LLM_API_KEY,
                       chat_model=settings.LLM_MODEL_NAME,
                       embed_model=settings.EMBEDDING_MODEL_NAME)
    mem = MemoryManager(db, client)
    out = {"meta": meta, "blocks": []}
    out["vec"] = {"available": bool(await mem.initialize()),
                  "dim": getattr(mem, "_vec_dim", None),
                  "off_reason": getattr(mem, "_vec_off_reason", None)}
    try:
        out["vec"]["period_guard"] = await mem._period_vector_guard()
        out["vec"]["identity_fp"] = mem._identity_fingerprint()
    except Exception:
        out["vec"]["period_guard"] = "ERR:%s" % traceback.format_exc()[-300:]
    out["config"] = {
        "rerank_flag_settings_default": settings.CHAT_RAG_RERANK_ENABLED,
        "typed_reranker": getattr(settings, "MCA_TYPED_RERANKER_ENABLED", None),
        "facts_limit_runtime": LIMIT,
        "context_max_chars_runtime": CAP,
        "llm_model": settings.LLM_MODEL_NAME,
        "embed_model": settings.EMBEDDING_MODEL_NAME,
        "llm_base_host": settings.LLM_BASE_URL}
    mem.llm = RerankStub(client, MODE, 3)

    queries = json.load(open(os.environ["QUERIES"], encoding="utf-8-sig"))
    for item in queries:
        for policy in item.get("policies", ["historical", "auto"]):
            r = await run_block(db, mem, item["question"], policy, MODE)
            r["item_key"] = item["key"]
            out["blocks"].append(r)
            print("Q %s %-10s empty=%s block_rows=%d years=%s protected=%s "
                  "period_rows=%d pool=%d period_kept=%s despite_empty=%s %s"
                  % (item["key"], policy, r["block_empty"], r["block_rows"],
                     r["block_years"], r["period_protected_in_block"],
                     len(r["period_rows"]), r["period_pool_n"],
                     r["rag_counts"].get("period_kept"),
                     r["rag_counts"].get("period_kept_despite_empty"),
                     ("ERR" if r["error"] else "")), flush=True)
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False, indent=1)
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("WROTE", OUT)
    await db.db.close()


if __name__ == "__main__":
    asyncio.run(main())


