"""VMQ-NEXT-03 controlled positive case — runnable entrypoint.

Real product path (no injection into `_rag_unified_rows`):
    DirectChatService._build_rag_block
        -> DirectChatService._rag_unified_rows
            -> DirectChatService._rag_retrieve
                -> mca_retrieval_context.retrieve

Only harness-side substitutions, all printed in the output:
  * rerank provider double: MODE=empty returns a VALID empty verdict
    `{"selected": []}` through the product's own typed parser; MODE=real uses
    the configured provider;
  * RERANK_SEAM=method replaces `memory.rerank_rag_facts` itself with a double
    returning [] (second, independent form of the same verdict);
  * read-only spies on `_rag_retrieve` / `_rag_unified_rows` / `build_rag_context`
    (each calls the ORIGINAL) and a recording proxy around `_cp_g`.
  * `dcs.hot` is pinned to the measured prod values (`flags.graph_rag_enabled`,
    `flags.chat_rag_rerank_enabled`, limits 10/2000): the SQLite copy has no
    `bot_settings`/`chat_profiles` (they live in PostgreSQL). The pinned dict is
    printed as `meta.harness_hot`.
Nothing in the product is patched, no rows are injected.

The source DB is opened read-only; the run uses a fresh `sqlite3.backup`
derivative (the vector leg marks usage) which is removed on exit unless
`--keep-deriv` is given.

Example (candidate worktree + prod-DB copy):

    py -u positive_probe.py \
        --code-root C:/.../worktrees/.../self-diag-01-...-3a18d4fe \
        --db C:/.../probe-d86a98460c/prod-copy.db \
        --env-file C:/Code/Python/adminbot/.env \
        --work-dir C:/.../runs/.../positive-a \
        --out C:/.../runs/.../positive-a/out.json

Default `--queries` is the companion file `positive_probe-queries.json`
(controlled question "Что сейчас с работой?", row 2242/2023, product
`stems_shared=2`, one-row block under a valid empty verdict).
"""
import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import tempfile
import time
import traceback

CHAT = -1002661910336
CPG = []
YEAR_RE = re.compile(r"(20\d\d)")
FACT_RE = re.compile(r"fact:(\d+)")
MSG_RE = re.compile(r"msg:(\d+)")
DEFAULT_SHA = ("5310e91e282813f6342c950eb3ee182dc93e9ad6fdf54fdd91d3287e394082b2")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Hot:
    """Prod values pinned by the harness (same as the 12.11 measurement)."""

    def __init__(self, over):
        self.over = dict(over)

    def get(self, key, default=None):
        return self.over.get(key, default)


class Msg:
    def __init__(self, text):
        self.text = text


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


def make_derivative(src_db, deriv):
    src = sqlite3.connect("file:%s?mode=ro" % src_db.replace("\\", "/"), uri=True)
    dst = sqlite3.connect(deriv)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()


def check_expect(rec, exp):
    """Compare the observed block with the expected values from the query file."""
    reasons = []
    ok = True
    period = [r for r in (rec.get("period_rows") or [])
              if str(r.get("id")) == str(exp.get("row_id"))]
    if exp.get("row_id") is not None:
        if not period:
            ok = False
            reasons.append("row %s is not a returned period row" % exp["row_id"])
        elif str(exp["row_id"]) not in [str(x) for x in rec.get("block_ids") or []]:
            ok = False
            reasons.append("row %s is not in the rendered block" % exp["row_id"])
    if period and exp.get("stems_shared") is not None:
        if period[0].get("stems_shared") != exp["stems_shared"]:
            ok = False
            reasons.append("stems_shared=%s != %s"
                           % (period[0].get("stems_shared"),
                              exp["stems_shared"]))
    if period and exp.get("year") is not None:
        if period[0].get("year") != exp["year"]:
            ok = False
            reasons.append("year=%s != %s" % (period[0].get("year"),
                                              exp["year"]))
    if period and exp.get("proxy"):
        if period[0].get("proxy") != exp["proxy"]:
            ok = False
            reasons.append("proxy=%s != %s" % (period[0].get("proxy"),
                                               exp["proxy"]))
    if exp.get("block_rows") is not None:
        if rec.get("block_rows") != exp["block_rows"]:
            ok = False
            reasons.append("block_rows=%s != %s"
                           % (rec.get("block_rows"), exp["block_rows"]))
    for key in ("period_kept", "period_kept_despite_empty"):
        if exp.get(key) is not None:
            got = (rec.get("rag_counts") or {}).get(key)
            if str(got) != str(exp[key]):
                ok = False
                reasons.append("%s=%s != %s" % (key, got, exp[key]))
    if exp.get("block_line_contains"):
        if exp["block_line_contains"] not in str(rec.get("block") or ""):
            ok = False
            reasons.append("block does not contain %r"
                           % exp["block_line_contains"])
    return {"pass": ok, "reasons": reasons}


async def run_query(args, db, mem, dcs, item):
    """Run one question/policy through the real `_build_rag_block`."""
    query = item["question"]
    llm = mem.llm
    llm.mode = args.mode
    llm.calls = 0
    llm.raw = []
    calls, captured, holder = [], {}, {}
    CPG.clear()
    seam_calls = {"n": 0}
    orig_seam = None
    if args.seam == "method":
        orig_seam = mem.rerank_rag_facts

        async def seam_double(q, facts):
            seam_calls["n"] += 1
            return []

        mem.rerank_rag_facts = seam_double
    svc = dcs.DirectChatService(memory=mem, db=db, llm=None, aliases=None)
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
            "channels": list(channels), "limit": int(limit),
            "policy": policy_,
            "period_fill": bool(kw.get("period_fill")),
            "lexical_stem": bool(kw.get("lexical_stem")),
            "include_archived": bool(kw.get("include_archived")),
            "exclude_years": sorted(kw.get("exclude_years") or ()),
            "pool_rows": len(rows),
            "pool_ids": [r.get("id") for r in rows],
            "pool_years": years_of(rows, dcs),
            "period_meta": (dict(getattr(res, "period_fill", None) or {})
                            if isinstance(getattr(res, "period_fill", None),
                                          dict) else None),
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
            CHAT, Msg(query), "", memory_scope=args.policy,
            subject_name=None, subject_uid=None)
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
    period_keys = (dcs._rag_period_keys(rows)
                   if isinstance(rows, list) else set())
    judged_keys = (dcs._rag_period_judged_keys(rows)
                   if isinstance(rows, list) else set())
    protected_keys = period_keys - judged_keys
    period_rows = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not row.get("period_fill"):
                continue
            key = row.get("item_id") or (row.get("origin"), row.get("fact"))
            period_rows.append({
                "id": row.get("id"), "year": year_of(row, dcs),
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
            "id": row.get("id"), "year": year_of(row, dcs),
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
    typed_empty = [l for l in captured.get("logs", []) if "valid EMPTY" in l]
    rec = {
        "item_key": item.get("key"), "query": query, "policy": args.policy,
        "mode": args.mode, "seam": args.seam,
        "block": block, "block_empty": not bool(str(block or "").strip()),
        "block_ids": info["ids"], "block_rows": info["rows"],
        "block_years": info["years"],
        "retrieval_calls": calls,
        "rows_returned_n": len(rows) if isinstance(rows, list) else None,
        "rows_returned": ([{"id": r.get("id"), "year": year_of(r, dcs),
                            "period_fill": bool(r.get("period_fill")),
                            "proxy": dcs._rag_subject_proxy_of(r),
                            "stems_shared": r.get("stems_shared")}
                           for r in rows] if isinstance(rows, list) else None),
        "period_rows": period_rows,
        "period_protected_n": len(protected_keys),
        "period_protected_in_block": [str(r["id"]) for r in period_rows
                                      if r["protected"]
                                      and str(r["id"]) in set(info["ids"])],
        "period_pool_n": len(pool_rows), "period_pool_rows": pool_rows,
        "period_stats_service": dict(getattr(svc, "_rag_period_stats", None) or {}),
        "rag_log": rag_line, "rag_counts": parse_rag_log(rag_line),
        "typed_empty_log": typed_empty[:4],
        "rerank_calls": llm.calls, "rerank_raw": list(llm.raw)[:4],
        "seam_calls": seam_calls["n"], "cp_g_calls": list(CPG),
        "sha_block": hashlib.sha256(str(block).encode("utf-8")).hexdigest(),
        "elapsed_ms": elapsed, "error": err}
    rec["expect"] = check_expect(rec, item.get("expect") or {})
    return rec


def year_of(row, dcs):
    return dcs._rag_row_year(row)


def years_of(rows, dcs):
    out = {}
    for row in rows:
        y = year_of(row, dcs)
        out[str(y)] = out.get(str(y), 0) + 1
    return out


def parse_args(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        description="VMQ-NEXT-03 controlled positive case through the real "
                    "_build_rag_block path (read-only DB copy).")
    ap.add_argument("--code-root", default=os.environ.get("CODE_ROOT") or ".",
                    help="candidate worktree (default: $CODE_ROOT or cwd)")
    ap.add_argument("--db", required=True,
                    help="prod-DB COPY (opened read-only; a derivative is made)")
    ap.add_argument("--expect-sha", default=DEFAULT_SHA,
                    help="expected sha256 of --db ('' disables; default %s)"
                         % DEFAULT_SHA[:12])
    ap.add_argument("--env-file", default=os.environ.get("ENV_FILE"),
                    help="dotenv file with provider keys (default $ENV_FILE)")
    ap.add_argument("--queries", default=os.path.join(
        here, "positive_probe-queries.json"))
    ap.add_argument("--work-dir", default=None,
                    help="dir for the derivative + default --out "
                         "(default: a fresh temp dir, removed on exit)")
    ap.add_argument("--out", default=None, help="output JSON path")
    ap.add_argument("--deriv-name", default="derived-%d.db" % os.getpid())
    ap.add_argument("--mode", choices=("empty", "real"), default="empty")
    ap.add_argument("--seam", choices=("llm", "method"), default="llm")
    ap.add_argument("--policies", default=None,
                    help="comma list overriding query policies "
                         "(default: per-query)")
    ap.add_argument("--block-timeout", type=float, default=120.0,
                    help="per-block timeout, seconds (default 120)")
    ap.add_argument("--batch-timeout", type=float, default=300.0,
                    help="whole-run timeout, seconds (default 300)")
    ap.add_argument("--keep-deriv", action="store_true",
                    help="keep the DB derivative and the temp work dir")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    args.code_root = os.path.abspath(args.code_root)
    args.db = os.path.abspath(args.db)
    if not os.path.isfile(args.db):
        sys.exit("ERROR: --db not found: %s" % args.db)
    if not os.path.isdir(args.code_root):
        sys.exit("ERROR: --code-root not found: %s" % args.code_root)

    work_dir = args.work_dir
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="vmq-positive-")
    os.makedirs(work_dir, exist_ok=True)
    out_path = args.out or os.path.join(work_dir, "positive_probe-out.json")
    deriv = os.path.join(work_dir, args.deriv_name)

    src_sha = sha256_file(args.db)
    if args.expect_sha and src_sha != args.expect_sha.lower():
        sys.exit("ERROR: --db sha256 %s != %s (use --expect-sha '' to skip)"
                 % (src_sha, args.expect_sha))
    print("source_db %s sha256 %s bytes %d"
          % (args.db, src_sha, os.path.getsize(args.db)), flush=True)

    make_derivative(args.db, deriv)
    print("derivative %s bytes %d" % (deriv, os.path.getsize(deriv)),
          flush=True)

    sys.path.insert(0, args.code_root)
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)

    import services.direct_chat_service as dcs
    import services.chat_params as cparams
    from services.database import DatabaseService
    from services.summary_memory import MemoryManager
    from services.llm_client import LLMClient
    from config.settings import settings

    class RerankStub:
        def __init__(self, real, mode):
            self._real = real
            self.mode = mode
            self.calls = 0
            self.raw = []
            self._chat_model = ("harness-empty-verdict"
                                if mode == "empty" else None)
            self._base_url = "harness://local" if mode != "real" else None

        def __getattr__(self, item):
            return getattr(self._real, item)

        async def generate(self, messages, **kwargs):
            self.calls += 1
            if self.mode == "real":
                out = await self._real.generate(messages, **kwargs)
                self.raw.append(str(out)[:400])
                return out
            self.raw.append('{"selected": []}')
            return '{"selected": []}'

    dcs.hot = Hot({
        "flags.graph_rag_enabled": True,
        "flags.chat_rag_rerank_enabled": True,
        "flags.relations_tone_enabled": False,
        "memory.nostalgia_layer_a_enabled": False,
        "limits.graph_rag_facts_limit": 10,
        "limits.graph_rag_context_max_chars": 2000,
    })
    cpg = CPG
    orig_cp_g = cparams.get_chat_param

    async def rec_cp_g(chat_id, key, default=None):
        val = await orig_cp_g(chat_id, key, default)
        cpg.append({"chat": int(chat_id), "key": str(key),
                    "default": default, "resolved": val,
                    "type": type(val).__name__})
        return val

    dcs._cp_g = rec_cp_g

    async def run_all():
        db = DatabaseService(deriv)
        await db.initialize()
        client = LLMClient(base_url=settings.LLM_BASE_URL,
                           api_key=settings.LLM_API_KEY,
                           chat_model=settings.LLM_MODEL_NAME,
                           embed_model=settings.EMBEDDING_MODEL_NAME)
        mem = MemoryManager(db, client)
        meta = {
            "entrypoint": os.path.abspath(__file__),
            "code_root": args.code_root,
            "query_file": os.path.abspath(args.queries),
            "source_db": {"path": args.db, "sha256": src_sha,
                          "bytes": os.path.getsize(args.db)},
            "derivative": deriv, "mode": args.mode, "seam": args.seam,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "block_timeout_s": args.block_timeout,
            "batch_timeout_s": args.batch_timeout,
            "harness_hot": dict(dcs.hot.over),
        }
        try:
            import subprocess
            meta["git_head"] = subprocess.check_output(
                ["git", "-C", args.code_root, "rev-parse", "HEAD"],
                text=True).strip()
            for key, ref in (("blob_dcs", "HEAD:services/direct_chat_service.py"),
                             ("blob_mca", "HEAD:services/mca_retrieval_context.py"),
                             ("blob_sm", "HEAD:services/summary_memory.py")):
                try:
                    meta[key] = subprocess.check_output(
                        ["git", "-C", args.code_root, "rev-parse", ref],
                        text=True).strip()
                except Exception:
                    meta[key] = "unknown"
        except Exception:
            meta["git_head"] = "unknown"
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
            "typed_reranker": getattr(settings, "MCA_TYPED_RERANKER_ENABLED",
                                      None),
            "llm_model": settings.LLM_MODEL_NAME,
            "embed_model": settings.EMBEDDING_MODEL_NAME,
            "llm_base_host": settings.LLM_BASE_URL}
        mem.llm = RerankStub(client, args.mode)
        queries = json.load(open(args.queries, encoding="utf-8-sig"))
        if isinstance(queries, dict):
            queries = [queries]
        deadline = time.monotonic() + args.batch_timeout
        try:
            for item in queries:
                policies = ([p.strip() for p in args.policies.split(",")
                             if p.strip()] if args.policies
                            else item.get("policies", ["historical", "auto"]))
                for policy in policies:
                    if time.monotonic() > deadline:
                        out["blocks"].append({"item_key": item.get("key"),
                                              "policy": policy,
                                              "batch_timeout": True})
                        continue
                    args.policy = policy
                    try:
                        rec = await asyncio.wait_for(
                            run_query(args, db, mem, dcs, item),
                            timeout=args.block_timeout)
                    except asyncio.TimeoutError:
                        rec = {"item_key": item.get("key"), "policy": policy,
                               "timeout": True,
                               "block_timeout_s": args.block_timeout}
                    out["blocks"].append(rec)
                    print("Q %s %-10s empty=%s rows=%s years=%s "
                          "protected=%s period_kept=%s despite_empty=%s "
                          "expect=%s%s"
                          % (item.get("key"), policy, rec.get("block_empty"),
                             rec.get("block_rows"), rec.get("block_years"),
                             rec.get("period_protected_in_block"),
                             (rec.get("rag_counts") or {}).get("period_kept"),
                             (rec.get("rag_counts") or {}).get(
                                 "period_kept_despite_empty"),
                             (rec.get("expect") or {}).get("pass"),
                             (" ERR" if rec.get("error") else "")), flush=True)
                    with open(out_path, "w", encoding="utf-8") as fh:
                        json.dump(out, fh, ensure_ascii=False, indent=1)
        finally:
            try:
                await db.db.close()
            except Exception:
                pass
        meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        print("WROTE %s" % out_path)
        return out

    try:
        out = asyncio.run(run_all())
    finally:
        if not args.keep_deriv:
            for suffix in ("", "-wal", "-shm"):
                p = deriv + suffix
                if os.path.exists(p):
                    os.remove(p)
    print("work_dir %s (output kept)" % work_dir, flush=True)
    passed = [b for b in out.get("blocks", []) if (b.get("expect") or {}).get("pass")]
    failed = [b for b in out.get("blocks", []) if not (b.get("expect") or {}).get("pass")]
    print("EXPECT pass=%d fail=%d" % (len(passed), len(failed)), flush=True)
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
