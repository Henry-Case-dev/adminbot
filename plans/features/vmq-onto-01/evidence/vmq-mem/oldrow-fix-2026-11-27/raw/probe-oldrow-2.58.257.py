"""P-OLDROW RED/GREEN probe on the deployed 2.58.257 snapshot (READ-ONLY).

Контракт: `plans/features/vmq-onto-01/evidence/vmq-mem/selector-rootcause-
2026-11-27.md` §5. Вход — тот же снимок, тот же чат и тот же entrypoint, что
в `measure-2026-11-27`:

  retrieve(period_fill=True, channels=(lexical, vector, author_window),
           top_k=32, memory_scope=historical|auto,
           subject_entity_ids=(uid,), subject_names=(name,),
           period_intent=<historical|subject_scope>)
  → select_period_rows(... slots=2, subject_uids=(uid,), subject_names=(name,))
  → reserve_period_append(budget=2)

Снимок открывается read-only: `file:...?mode=ro&immutable=1` + `PRAGMA
query_only=ON`; записи, провайдерских вызовов и рестартов нет. Векторная нога
не исполняется (memory=None) — та же честная граница, что у замера.
"""
import asyncio
import collections
import datetime
import hashlib
import json
import os
import sqlite3
import sys
import time

BASE = os.environ.get("OLDROW_CODE_ROOT") or os.getcwd()
SNAP = os.environ.get("OLDROW_SNAP") or ""
OUT = os.environ.get("OLDROW_OUT") or ""
CHAT = -1002661910336
PEOPLE = [(485008070, "P1"), (138811255, "P2_top_author"),
          (1313107079, "P3_history_2023_2024")]
TOP_K = 32
PERIOD_SLOT_DIV = 5
REF_YEARS = (2022, 2023, 2024, 2025, 2026)
Q_A1 = ("напиши юмористический рассказ об основных шизах конфы")
Q_A1P = "перескажи, что в чате писали про шизов и конфу"
Q_PERSON = "что ты знаешь про %s?"
Q_CURRENT = "что сейчас происходит?"
CURRENT_ENDING = "сейчас"


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def year_of(value):
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc).year
    except (OSError, OverflowError, ValueError):
        return None


def row_year(row):
    if not isinstance(row, dict):
        return None
    return year_of(row.get("message_timestamp") or row.get("created_at")
                   or row.get("rag_ts"))


def cand_year(cand):
    return year_of(getattr(cand, "sent_at", 0) or 0)


def hist(values):
    return {str(k): v for k, v in
            sorted(collections.Counter(
                v for v in values if v is not None).items())}


def coverage(years):
    return round(len(set(REF_YEARS) & set(years)) / len(REF_YEARS), 2)


def ro_uri(path):
    return "file:" + path.replace("\\", "/") + "?mode=ro&immutable=1"


def sha256_file(path, chunk=8 * 1024 * 1024):
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return digest.hexdigest(), size


async def main():
    if not SNAP or not os.path.exists(SNAP):
        print(json.dumps({"error": "snapshot_missing", "path": SNAP}))
        return
    os.chdir(BASE)
    sys.path.insert(0, BASE)

    import aiosqlite
    from services.database import DatabaseService
    from services import mca_retrieval_context as rc

    result = {
        "artifact_kind": "vmq_oldrow_red_green_readonly",
        "measured_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "code_root": BASE,
        "snapshot_path": SNAP,
        "chat_id": CHAT,
        "errors": [],
    }
    result["snapshot_sha256"], result["snapshot_bytes"] = sha256_file(SNAP)

    async def open_ds():
        service = DatabaseService(SNAP)
        service.db = await aiosqlite.connect(ro_uri(SNAP), uri=True)
        service.db.row_factory = aiosqlite.Row
        await service.db.execute("PRAGMA query_only=ON")

        async def noop(*_args, **_kwargs):
            return None

        service.touch_graph_facts = noop
        return service

    def request(**kwargs):
        base = dict(chat_id=CHAT, mode="specific", purpose="reply",
                    top_k=TOP_K, reply_depth=0, preserve_channel_order=True,
                    include_self=True, include_direct_reply=True,
                    include_archived=True, period_fill=True, lexical_stem=True,
                    exclude_years=())
        base.update(kwargs)
        return rc.RetrievalRequest(**base)

    def resolve_intent(query, *, memory_scope, subject_present=False,
                       current_state=False):
        """Новый структурный вход R3; на базе его нет — прежняя подпись."""
        try:
            return rc.resolve_period_intent(
                query, memory_scope=memory_scope,
                subject_present=subject_present, current_state=current_state)
        except TypeError:
            return rc.resolve_period_intent(query, memory_scope=memory_scope)

    def select_rows(rows, *, query, intent, policy, slots,
                    subject_uids=(), subject_names=()):
        """R1-пометка и субъектный фильтр; на базе — прежняя подпись."""
        try:
            return rc.select_period_rows(
                rows, query=query, intent=intent, policy=policy, slots=slots,
                subject_uids=subject_uids, subject_names=subject_names)
        except TypeError:
            return rc.select_period_rows(
                rows, query=query, intent=intent, policy=policy, slots=slots)

    db = await open_ds()
    sync = sqlite3.connect(ro_uri(SNAP), uri=True)
    sync.row_factory = sqlite3.Row
    sync.execute("PRAGMA query_only=ON")

    def person_name(uid):
        row = sync.execute(
            "SELECT author_name FROM smart_messages WHERE user_id=? AND "
            "chat_id=? AND COALESCE(author_name,'')<>'' "
            "GROUP BY author_name ORDER BY COUNT(*) DESC LIMIT 1",
            (uid, CHAT)).fetchone()
        return str(row["author_name"]) if row else ""

    def old_material(uid, name):
        """Материал старших лет существует (read-only SQL, как в замере)."""
        row = sync.execute(
            "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id=? AND "
            "user_id=? AND text<>'' AND timestamp < ?",
            (CHAT, uid, int(datetime.datetime(
                2026, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
             )).fetchone()
        return int(row["n"] if row else 0)

    async def measure_person(uid, alias):
        name = person_name(uid)
        query = Q_PERSON % name if name else ""
        out = {"alias": alias, "uid": uid, "name_present": bool(name),
               "old_messages_before_2026": old_material(uid, name),
               "query_masked": Q_PERSON % ("<subject:" + alias + ">")}
        for scope in ("auto", "historical"):
            intent = resolve_intent(
                query, memory_scope=scope, subject_present=True)
            req = request(query=query, top_k=TOP_K, memory_scope=scope,
                          channels=("lexical", "vector", "author_window"),
                          subject_entity_ids=(uid,), subject_names=(name,),
                          period_intent=intent)
            try:
                res = await asyncio.wait_for(
                    rc.retrieve(db, None, req), 600)
            except Exception as exc:            # pragma: no cover
                out[scope] = {"error": type(exc).__name__,
                              "text": str(exc)[:200]}
                continue
            fill = dict(res.period_fill or {})
            messages = [cand for cand in (res.candidates or ())
                        if getattr(cand, "entity_type", "") == "message"]
            own_old = [cand for cand in messages
                       if getattr(cand, "author_id", None) == uid
                       and (cand_year(cand) or 9999) <= 2025]
            facts = [dict(row) for row in (res.fact_rows or ())]
            slots = max(1, TOP_K // PERIOD_SLOT_DIV)
            accepted, selection = select_rows(
                facts, query=query, intent=intent, policy=scope, slots=slots,
                subject_uids=(uid,), subject_names=(name,))
            accepted_years = [row_year(row) for row in accepted]
            delivered = rc.reserve_period_append(accepted, budget=slots)
            delivered_years = [row_year(row) for row in delivered]
            out[scope] = {
                "intent": intent.as_dict(),
                "replace_allowed": int(bool(
                    rc.period_replace_allowed(intent, scope))),
                "period_fill": {
                    "author_window": fill.get("author_window"),
                    "author_window_rows": fill.get("author_window_rows"),
                    "author_window_years": fill.get("author_window_years"),
                    "vector_leg": fill.get("vector_leg"),
                },
                "channels_used": sorted(set(res.channels_used or ())),
                "message_candidates": len(messages),
                "old_author_messages_delivered": len(own_old),
                "old_author_message_years": hist(
                    [cand_year(cand) for cand in own_old]),
                "old_author_message_bound": {
                    "le_limit_div_5": len(own_old) <= TOP_K // PERIOD_SLOT_DIV,
                    "le_12": len(own_old) <= 12,
                },
                "fact_rows": len(facts),
                "fact_row_years": hist([row_year(row) for row in facts]),
                "old_fact_rows": sum(
                    1 for row in facts if (row_year(row) or 9999) <= 2025),
                "selector": {
                    "pool": int(selection.get("rows") or 0),
                    "kept": int(selection.get("kept") or 0),
                    "accepted_years": accepted_years,
                    "soft_fallback": int(
                        selection.get("soft_fallback") or 0),
                    "dropped_subject": int(
                        selection.get("dropped_subject") or 0),
                    "dropped_out_of_target_year": int(
                        selection.get("dropped_out_of_target_year") or 0),
                    "pool_expired": int(selection.get("pool_expired") or 0),
                    "reserved_old": int(selection.get("reserved_old") or 0),
                    "reserved_displaced": int(
                        selection.get("reserved_displaced") or 0),
                    "historical_quota": int(
                        selection.get("historical_quota") or 0),
                    "multi_year_quota": int(
                        selection.get("multi_year_quota") or 0),
                },
                "reserve_period_append": {
                    "budget": slots,
                    "delivered_years": delivered_years,
                    "old_period_in_budget": bool(
                        any((value or 9999) <= 2025
                            for value in delivered_years)),
                    "length_le_budget": len(delivered) <= slots,
                },
            }
            log("PERSON", alias, scope, accepted_years, len(own_old))
        # Контроль «что сейчас»: тот же субъект, текущее состояние.
        for scope in ("auto", "operative"):
            intent = resolve_intent(
                Q_CURRENT, memory_scope=scope, subject_present=True,
                current_state=True)
            req = request(query=Q_CURRENT, top_k=TOP_K, memory_scope=scope,
                          channels=("lexical", "vector", "author_window"),
                          subject_entity_ids=(uid,), subject_names=(name,),
                          period_intent=intent)
            try:
                res = await asyncio.wait_for(rc.retrieve(db, None, req), 600)
            except Exception as exc:            # pragma: no cover
                out["current_" + scope] = {"error": type(exc).__name__}
                continue
            fill = dict(res.period_fill or {})
            facts = [dict(row) for row in (res.fact_rows or ())]
            _accepted, selection = select_rows(
                facts, query=Q_CURRENT, intent=intent, policy=scope, slots=2,
                subject_uids=(uid,), subject_names=(name,))
            out["current_" + scope] = {
                "intent": intent.as_dict(),
                "author_window": fill.get("author_window"),
                "author_window_rows": fill.get("author_window_rows"),
                "channels_used": sorted(set(res.channels_used or ())),
                "reserved_old": int(selection.get("reserved_old") or 0),
                "fact_row_years": hist([row_year(row) for row in facts]),
            }
        return out

    async def measure_query(key, query, scope):
        intent = rc.resolve_period_intent(query, memory_scope=scope)
        req = request(query=query, top_k=TOP_K, memory_scope=scope,
                      channels=("lexical", "vector"),
                      period_intent=intent)
        res = await asyncio.wait_for(rc.retrieve(db, None, req), 900)
        facts = [dict(row) for row in (res.fact_rows or ())]
        accepted, selection = rc.select_period_rows(
            facts, query=query, intent=intent, policy=scope, slots=2)
        delivered = rc.reserve_period_append(accepted, budget=2)
        return {
            "intent": intent.as_dict(),
            "pool": len(facts),
            "pool_years": hist([row_year(row) for row in facts]),
            "selector": {
                "kept": int(selection.get("kept") or 0),
                "accepted_years": [row_year(row) for row in accepted],
                "soft_fallback": int(selection.get("soft_fallback") or 0),
                "dropped_subject": int(selection.get("dropped_subject") or 0),
                "pool_expired": int(selection.get("pool_expired") or 0),
                "reserved_old": int(selection.get("reserved_old") or 0),
                "reserved_displaced": int(
                    selection.get("reserved_displaced") or 0),
                "historical_quota": int(
                    selection.get("historical_quota") or 0),
                "multi_year_quota": int(
                    selection.get("multi_year_quota") or 0),
            },
            "delivered_years": [row_year(row) for row in delivered],
            "coverage_period": coverage([row_year(row) for row in delivered]),
        }

    try:
        result["people"] = {}
        for uid, alias in PEOPLE:
            result["people"][alias] = await measure_person(uid, alias)
            log("PERSON_DONE", alias)
        result["A1_historical"] = await measure_query(
            "A1", Q_A1, "historical")
        log("A1_DONE")
        result["A1P_historical"] = await measure_query(
            "A1P", Q_A1P, "historical")
        log("A1P_DONE")
        import inspect
        result["versions"] = {
            "module_file": str(getattr(rc, "__file__", "")),
            "resolve_period_intent": str(inspect.signature(
                rc.resolve_period_intent)),
            "select_period_rows": str(inspect.signature(
                rc.select_period_rows)),
            "reserve_period_append": str(inspect.signature(
                rc.reserve_period_append)),
        }
    finally:
        sync.close()
        try:
            await db.db.close()
        except Exception:                       # pragma: no cover
            pass
    result["snapshot_sha256_after"], _size = sha256_file(SNAP)
    payload = json.dumps(result, ensure_ascii=False, default=str, indent=1)
    if OUT:
        with open(OUT, "w", encoding="utf-8") as handle:
            handle.write(payload)
    print("===JSON_BEGIN===")
    print(payload)
    print("===JSON_END===")


if __name__ == "__main__":
    asyncio.run(main())
