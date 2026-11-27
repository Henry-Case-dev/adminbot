"""P-OLDROW F1 corrective — RED/GREEN на реальном снимке (READ-ONLY).

Проверяет ровно то, что требовало ревью r1 (F1, OLDROW-R3-BASE-01): прямой
путь `subject_scope` (`replace_allowed=0`) НЕ выбрасывает хвост базового
среза; периодный вклад занимает дополнительную ёмкость `limit + limit//5`.

Запускается на трёх версиях кода с одним и тем же снимком:
  * base  `9516c9125`  — исходная выкатка;
  * prev  `e1c70d58f`  — предыдущий кандидат (F1-дефект);
  * fixed — текущий кандидат этого corrective.
Снимок открывается read-only (`mode=ro&immutable=1`, `PRAGMA query_only=ON`);
векторной ноги нет (`embed_unavailable`), поэтому базовый срез в этом
измерении читается ЛЕКСИЧЕСКОЙ ногой того же чата (override классового
`_RAG_FACT_CHANNELS` в измерительном скрипте; продуктовый код не меняется) —
иначе базовый срез был бы пуст и инвариант «база не меняется» нечем проверить.
"""
import asyncio
import collections
import datetime
import hashlib
import json
import os
import sys
import types

BASE = os.environ.get("OLDROW_CODE_ROOT") or os.getcwd()
SNAP = os.environ.get("OLDROW_SNAP") or ""
OUT = os.environ.get("OLDROW_OUT") or ""
CHAT = -1002661910336
PEOPLE = [(485008070, "P1"), (138811255, "P2_top_author"),
          (1313107079, "P3_history_2023_2024")]
TOP_K = 10
POOL = 32
Q_PERSON = "что ты знаешь про %s?"
Q_CURRENT = "что сейчас происходит про %s?"
Q_A1 = "напиши юмористический рассказ об основных шизах конфы"


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


def hist(values):
    return {str(k): v for k, v in
            sorted(collections.Counter(
                v for v in values if v is not None).items())}


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
    from services import direct_chat_service as dcs

    result = {
        "artifact_kind": "vmq_oldrow_f1_readonly",
        "measured_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "code_root": BASE,
        "chat_id": CHAT,
        "limit": TOP_K,
        "period_slots": max(1, TOP_K // 5),
    }
    result["snapshot_sha256"], result["snapshot_bytes"] = sha256_file(SNAP)
    import inspect
    result["signatures"] = {
        "resolve_period_intent": str(inspect.signature(
            rc.resolve_period_intent)),
        "select_period_rows": str(inspect.signature(
            rc.select_period_rows)),
    }

    async def open_ds():
        service = DatabaseService(SNAP)
        service.db = await aiosqlite.connect(ro_uri(SNAP), uri=True)
        service.db.row_factory = aiosqlite.Row
        await service.db.execute("PRAGMA query_only=ON")

        async def noop(*_a, **_k):
            return None

        service.touch_graph_facts = noop
        return service

    db = await open_ds()

    def person_name(uid):
        import sqlite3
        with sqlite3.connect(ro_uri(SNAP), uri=True) as sync:
            sync.row_factory = sqlite3.Row
            sync.execute("PRAGMA query_only=ON")
            row = sync.execute(
                "SELECT author_name FROM smart_messages WHERE user_id=? AND "
                "chat_id=? AND COALESCE(author_name,'')<>'' "
                "GROUP BY author_name ORDER BY COUNT(*) DESC LIMIT 1",
                (uid, CHAT)).fetchone()
            return str(row["author_name"]) if row else ""

    class _Consumer(dcs.DirectChatService):
        # Единственное отличие — базовый срез читается также лексически
        # (вектор недоступен на снимке). Продуктовый код не менялся.
        _RAG_FACT_CHANNELS = ("vector", "lexical")

    class _Hot:
        def __init__(self, values):
            self._values = dict(values)

        def get(self, key, default=None):
            return self._values.get(key, default)

    from services import hot_config as hot

    async def measure_consumer(uid, alias, query, scope, subject_ok=True,
                               fact_limit=None):
        name = person_name(uid) if subject_ok else ""
        service = _Consumer(memory=types.SimpleNamespace(), db=db, llm=None,
                            aliases=None)
        captured: dict = {}
        real = service._rag_retrieve
        calls: list = []
        saved_hot = getattr(hot, "_cache", None)
        if fact_limit is not None:
            hot._cache = _Hot({"limits.graph_rag_facts_limit": int(fact_limit)})

        async def spy(db_, memory, chat_id, query_, channels, limit, policy,
                      **kwargs):
            res = await real(db_, memory, chat_id, query_, channels, limit,
                             policy, **kwargs)
            calls.append({"period_fill": bool(kwargs.get("period_fill")),
                          "channels": tuple(channels)})
            if not kwargs.get("period_fill"):
                captured["base"] = [dict(row) for row in
                                    (res.fact_rows or ())]
            return res

        service._rag_retrieve = spy
        message = types.SimpleNamespace(text=query, chat_id=CHAT,
                                         message_id=0)
        try:
            rows = await asyncio.wait_for(service._rag_unified_rows(
                CHAT, query, message, memory_scope=scope,
                subject_name=(name if subject_ok else None),
                subject_uid=(uid if subject_ok else None)), 900)
        finally:
            if fact_limit is not None:
                hot._cache = saved_hot
        stats = dict(getattr(service, "_rag_period_stats", {}) or {})
        base_rows = captured.get("base") or []
        delivered = [dict(row) for row in (rows or ())]
        base_ids = [row.get("id") for row in base_rows]
        delivered_ids = [row.get("id") for row in delivered]
        return {
            "alias": alias,
            "query_masked": query.replace(name, "<subject>") if name else query,
            "scope": scope,
            "fact_limit": fact_limit,
            "calls": calls,
            "base_rows": len(base_rows),
            "base_slice_full": bool(
                fact_limit is not None
                and len(base_rows) >= int(fact_limit)),
            "base_ids_head": base_ids[:5],
            "base_ids_tail": base_ids[-3:],
            "delivered_rows": len(delivered),
            "delivered_ids": delivered_ids,
            "delivered_years": hist([row_year(row) for row in delivered]),
            "base_rows_preserved": sum(
                1 for value in base_ids if value in set(delivered_ids)),
            "base_missing": [value for value in base_ids
                             if value not in set(delivered_ids)],
            "base_prefix_preserved": (
                delivered_ids[:len(base_ids)] == base_ids),
            "old_rows_added": sum(
                1 for row in delivered
                if row.get("period_fill")
                and (row_year(row) or 9999)
                <= datetime.datetime.now(datetime.timezone.utc).year - 1),
            "stats": {key: stats.get(key) for key in (
                "policy", "replace_allowed", "breadth_allowed",
                "breadth_reason", "breadth_used", "period_skipped",
                "reserved_old", "base_rows_dropped",
                "subject_scope_no_replace", "author_window")},
        }

    try:
        result["consumer"] = {}
        for uid, alias in PEOPLE:
            key = "P1_auto" if alias == "P1" else alias + "_auto"
            result["consumer"][key] = await measure_consumer(
                uid, alias, Q_PERSON % person_name(uid), "auto")
            if alias == "P1":
                result["consumer"]["P1_current"] = await measure_consumer(
                    uid, alias, Q_CURRENT % person_name(uid), "auto")
            log("CONSUMER", key)
        result["consumer"]["P1_operative"] = await measure_consumer(
            PEOPLE[0][0], "P1", Q_CURRENT % person_name(PEOPLE[0][0]),
            "operative")
        result["consumer"]["A1_historical"] = await measure_consumer(
            0, "A1", Q_A1, "historical", subject_ok=False)
        # F1-класс на реальных данных: «полный базовый срез». На снимке
        # лексическая нога отдаёт 5 фактов, поэтому лимит фактов приводится к
        # фактическому числу базовых строк — это тот же класс, что 10/10 в
        # фикстуре ревью, и единственный способ воспроизвести вытеснение.
        p1_uid, p1_name = PEOPLE[0][0], person_name(PEOPLE[0][0])
        result["consumer"]["P1_auto_fullbase"] = await measure_consumer(
            p1_uid, "P1", Q_PERSON % p1_name, "auto",
            fact_limit=int(result["consumer"]["P1_auto"].get("base_rows")
                           or 5))
        result["consumer"]["P1_current_fullbase"] = await measure_consumer(
            p1_uid, "P1", Q_CURRENT % p1_name, "auto",
            fact_limit=5)
        log("CONSUMER_DONE")
        # Компактная копия тех же людей через периодный entrypoint (как в
        # основном evidence) — нужна только для контроля «что сейчас».
        result["controls"] = {}
        for uid, alias in PEOPLE:
            name = person_name(uid)
            for scope in ("auto", "operative"):
                try:
                    intent = rc.resolve_period_intent(
                        Q_CURRENT % name, memory_scope=scope,
                        subject_present=True, current_state=True)
                    subject_args = {"subject_present": True,
                                    "current_state": True}
                except TypeError:
                    intent = rc.resolve_period_intent(
                        Q_CURRENT % name, memory_scope=scope)
                    subject_args = {}
                req = rc.RetrievalRequest(
                    chat_id=CHAT, query=Q_CURRENT % name, mode="specific",
                    purpose="reply", top_k=POOL, reply_depth=0,
                    preserve_channel_order=True, include_self=True,
                    include_direct_reply=True, include_archived=True,
                    period_fill=True, lexical_stem=True, exclude_years=(),
                    memory_scope=scope,
                    channels=("lexical", "vector", "author_window"),
                    subject_entity_ids=(uid,), subject_names=(name,),
                    period_intent=intent)
                res = await asyncio.wait_for(rc.retrieve(db, None, req), 900)
                fill = dict(res.period_fill or {})
                result["controls"]["%s_%s" % (alias, scope)] = {
                    "intent": intent.as_dict(),
                    "author_window": fill.get("author_window"),
                    "channels_used": sorted(set(res.channels_used or ())),
                    "fact_years": hist([row_year(dict(row))
                                        for row in (res.fact_rows or ())]),
                }
    finally:
        try:
            await db.db.close()
        except Exception:                       # pragma: no cover
            pass
    result["snapshot_sha256_after"], _size = sha256_file(SNAP)
    payload = json.dumps(result, ensure_ascii=False, default=str, indent=1)
    if OUT:
        with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    print("===JSON_BEGIN===")
    print(payload)
    print("===JSON_END===")


if __name__ == "__main__":
    asyncio.run(main())
