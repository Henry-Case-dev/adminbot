# -*- coding: utf-8 -*-
"""VMQ-MEM-07 - independent read-only evidence harness (Reviewer-owned).

This is evidence tooling, not product code. It does not edit services/,
handlers/, web/, config/, product tests, maps or statuses.

Pipeline per question:
  DirectChatService._rag_unified_rows
    -> _build_rag_block
    -> _build_old_episodes
    -> payload_builder.build_messages
  plus the same read-only DB used by mca_retrieval_context.retrieve().

LLM and embedding clients are failing stubs; the snapshot is opened with
SQLite mode=ro and its sha256 is compared before/after. All outputs contain
only ids, years, timestamps, counts, origins/statuses, hashes and codes; no
message/fact text and no personal display names.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import hashlib
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

CANDIDATE = "0fce97a14338521a24d94f560e896ebcb19f9492"
CHAT = -1002661910336
OWNER_QUERY = "напиши юмористический рассказ об основных шизах конфы"
SECRET_MARKERS = ("SECRET_FACT_TEXT_MEM07", "SECRET_MSG_TEXT_MEM07")
REF_RE = re.compile(r"(?:fact|tg|msg|row):\d+")
SCHEMA = "vmq-mem07-independent/1"

MATRIX_CLASSES = {
    "H": "humor_story",
    "R": "plain_retelling",
    "P": "participant_characterization",
    "C": "conflict_reconstruction",
    "E": "relations_views_change",
}

#: Privacy-excluded Builder participant ids (context only, never used as proof).
BUILDER_PIDS = (485008070, 138811255, 1313107079)

#: E1 candidate topics, first with >=2 supported years and one pre-2026 wins.
E1_TOPICS = (
    ("работе и зарплатам", ("работ", "зарплат", "деньг")),
    ("органной музыке", ("орган", "музык", "концерт")),
    ("шаурме", ("шаурм",)),
    ("витаминам", ("витамин",)),
    ("вайпу сервера", ("вайп", "сервер")),
    ("концертам", ("концерт", "билет")),
)

SPECS = (
    dict(id="H1", cls="H", template=OWNER_QUERY, ref="shiz",
         mode="derived", terms=("шиз",), predicate=("шиз",),
         tags=("owner_query",)),
    dict(id="H2", cls="H", template="расскажи смешную историю про ремонт ванной",
         ref="bath", mode="year", year=2022, terms=("ремонт", "ванн"),
         predicate=("ремонт", "ванн")),
    dict(id="R1", cls="R", template="перескажи, что происходило в чате в 2024 году",
         ref="retell2024", mode="year", year=2024, terms=(),
         predicate=("__year__", 2024)),
    dict(id="R2", cls="R", template="напомни, о чём говорили про собаку",
         ref="dog", mode="year", year=2024, terms=("собак",),
         predicate=("собак",)),
    dict(id="R3", cls="R", template="что известно про основные шизы конфы?",
         ref="shiz", mode="derived", terms=("шиз",), predicate=("шиз",),
         parity_of="H1"),
    dict(id="R4", cls="R", template="что было с ремонтом ванной?",
         ref="bath", mode="year", year=2022, terms=("ремонт", "ванн"),
         predicate=("ремонт", "ванн"), parity_of="H2"),
    dict(id="P1", cls="P", template="что за человек {P1}? что о нём известно за всё время?",
         ref="person:P1", mode="participant", slot="P1",
         predicate=("__subject__", "P1")),
    dict(id="P2", cls="P", template="какие истории и взгляды связаны с {P2}?",
         ref="person:P2", mode="participant", slot="P2",
         predicate=("__subject__", "P2")),
    dict(id="C1", cls="C", template="из-за чего был конфликт на конфе?",
         ref="conflict_conf", mode="conflict", year=2023,
         terms=("ссор", "ругал", "конфликт", "спор"),
         and_terms=("конф",), predicate=("ссор", "ругал", "конфликт", "спор")),
    dict(id="C2", cls="C", template="восстанови, из-за чего ругались в 2024 году",
         ref="conflict2024", mode="year", year=2024,
         terms=("ссор", "ругал", "конфликт", "спор"),
         predicate=("ссор", "ругал", "конфликт", "спор")),
    dict(id="E1", cls="E", template="как менялось отношение чата к {E1_topic}?",
         ref="topic:E1", mode="topic", slot="E1_topic",
         predicate=("__topic__", "E1")),
    dict(id="E2", cls="E", template="кто с кем дружил и ссорился за всё время?",
         ref="relations", mode="relations",
         terms=("друж", "отношен", "ссор", "ругал", "спор", "люб"),
         predicate=("друж", "отношен", "ссор", "ругал", "спор", "люб")),
    dict(id="N1", cls="N", template="что сейчас с ремонтом ванной?",
         ref="bath_current", mode="current", terms=("ремонт", "ванн"),
         predicate=("ремонт", "ванн"), control="current"),
    dict(id="N2", cls="N", template="как сейчас обстоят дела с собакой?",
         ref="dog_current", mode="current", terms=("собак",),
         predicate=("собак",), control="current"),
    dict(id="X1", cls="X", template="что сейчас с {X1_topic}?",
         ref="counterexample", mode="counterexample", slot="X1_topic",
         predicate=("__counterexample__",), control="counterexample"),
)

POLICIES = ("auto", "auto_plan")
POLICY_HISTORICAL_FOR = ("H1", "R3", "P1")


def sha256_text(value) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def year_of(value):
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).year


def hist(values) -> dict:
    out = {}
    for value in values:
        if value is None:
            continue
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: str(kv[0])))


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def utc_bounds(year: int) -> tuple:
    start = int(_dt.datetime(int(year), 1, 1, tzinfo=_dt.timezone.utc).timestamp())
    end = int(_dt.datetime(int(year) + 1, 1, 1, tzinfo=_dt.timezone.utc).timestamp())
    return start, end


def compact(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def fs_terms(terms, mode="or") -> str:
    parts = ['"%s"*' % str(t) for t in terms if str(t)]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    op = " AND " if mode == "and" else " OR "
    return "(" + op.join(parts) + ")"


def safe_write(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


class NetworkBlock:
    def __init__(self):
        self._orig_connect = None
        self._orig_create = None
        self.blocked = 0

    def __enter__(self):
        self._orig_connect = socket.socket.connect
        self._orig_create = socket.create_connection
        outer = self

        def _loopback(address):
            try:
                host = str(address[0])
            except (TypeError, IndexError):
                return False
            return host in ("127.0.0.1", "::1", "localhost")

        def connect(sock, address, *args, **kwargs):
            if (sock.family in (socket.AF_INET, socket.AF_INET6)
                    and not _loopback(address)):
                outer.blocked += 1
                raise RuntimeError("network_blocked")
            return outer._orig_connect(sock, address, *args, **kwargs)

        def create_connection(address, *args, **kwargs):
            if not _loopback(address):
                outer.blocked += 1
                raise RuntimeError("network_blocked")
            return outer._orig_create(address, *args, **kwargs)

        socket.socket.connect = connect
        socket.create_connection = create_connection
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._orig_connect
        socket.create_connection = self._orig_create
        return False

def snapshot_meta(path: str, chat_id: int) -> dict:
    meta = {"exists": bool(path and os.path.exists(path)), "path_name": None,
            "bytes": None, "sha256": None, "quick_check": None,
            "user_version": None, "tables": {}, "archive": {}}
    if not meta["exists"]:
        return meta
    meta["path_name"] = os.path.basename(path)
    meta["bytes"] = os.path.getsize(path)
    meta["sha256"] = sha256_file(path)
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        meta["quick_check"] = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        meta["user_version"] = int(conn.execute("PRAGMA user_version").fetchone()[0])
        for table in ("smart_messages", "smart_messages_fts", "graph_facts",
                      "graph_facts_fts", "nodes", "edges", "lore_stories",
                      "mca_source_refs", "mca_community_builds"):
            try:
                n = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                meta["tables"][table] = int(n)
            except sqlite3.Error:
                meta["tables"][table] = None
        try:
            row = conn.execute(
                "SELECT MIN(timestamp) AS lo, MAX(timestamp) AS hi, "
                "COUNT(*) AS n FROM smart_messages WHERE chat_id=?",
                (chat_id,)).fetchone()
            lo, hi, n = row["lo"], row["hi"], row["n"]
            by_year = {}
            for r in conn.execute(
                    "SELECT CAST(strftime('%Y', timestamp, 'unixepoch') AS INTEGER) "
                    "AS yr, COUNT(*) AS n FROM smart_messages WHERE chat_id=? "
                    "GROUP BY yr ORDER BY yr", (chat_id,)):
                by_year[str(r["yr"])] = int(r["n"])
            meta["archive"] = {
                "min_ts": int(lo) if lo is not None else None,
                "max_ts": int(hi) if hi is not None else None,
                "messages": int(n or 0),
                "by_year": by_year,
                "current_year": year_of(hi),
            }
        except sqlite3.Error as exc:
            meta["archive"] = {"error": type(exc).__name__}
    finally:
        conn.close()
    return meta


class ReferenceBuilder:
    """Build a deterministic, archive-derived reference for one ref key."""

    def __init__(self, db, chat_id: int, seed: str, current_year: int,
                 as_of: int, participants: dict, e1: dict,
                 counterexample: dict):
        self.db = db
        self.chat_id = chat_id
        self.seed = seed
        self.current_year = int(current_year)
        self.as_of = int(as_of)
        self.participants = participants or {}
        self.e1 = e1 or {}
        self.counterexample = counterexample or {}
        self.cache = {}
        self._cols = {}
        self.notes = []

    async def _rows(self, sql: str, params=()):
        cur = await self.db.db.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]

    async def _cols_of(self, table: str):
        if table in self._cols:
            return self._cols[table]
        try:
            rows = await self._rows("PRAGMA table_info(%s)" % table)
            cols = {str(r.get("name")) for r in rows}
        except Exception:
            cols = set()
        self._cols[table] = cols
        return cols

    def _fact_filter(self, alias: str = "f") -> str:
        return ("%s.status='confirmed' AND %s.kind='fact' AND "
                "%s.origin NOT IN ('bot_direct_reply','bot_self_reply') AND "
                "(%s.expires_at IS NULL OR %s.expires_at > ?)"
                % (alias, alias, alias, alias, alias))

    async def support_years(self, terms, mode="or", person=None,
                            and_terms=()) -> dict:
        out = {}
        col = await self._cols_of("graph_facts")
        if not terms:
            rows = await self._rows(
                "SELECT CAST(strftime('%%Y', COALESCE(f.message_timestamp, "
                "f.created_at), 'unixepoch') AS INTEGER) AS yr, COUNT(*) AS n "
                "FROM graph_facts f WHERE f.chat_id=? AND %s "
                "GROUP BY yr ORDER BY yr" % self._fact_filter(),
                (self.chat_id, self.as_of))
            for r in rows:
                if r.get("yr") is not None:
                    out.setdefault(str(r["yr"]), {})["facts"] = int(r["n"])
            rows = await self._rows(
                "SELECT CAST(strftime('%Y', timestamp, 'unixepoch') AS INTEGER) "
                "AS yr, COUNT(*) AS n FROM smart_messages WHERE chat_id=? "
                "GROUP BY yr ORDER BY yr", (self.chat_id,))
            for r in rows:
                if r.get("yr") is not None:
                    out.setdefault(str(r["yr"]), {})["messages"] = int(r["n"])
            if person:
                out = {}
                name, uid = person
                rows = await self._rows(
                    "SELECT CAST(strftime('%%Y', COALESCE(f.message_timestamp, "
                    "f.created_at), 'unixepoch') AS INTEGER) AS yr, COUNT(*) AS n "
                    "FROM graph_facts f WHERE f.chat_id=? AND %s AND "
                    "(f.target_user LIKE ? OR f.speaker_author_id=?) "
                    "GROUP BY yr ORDER BY yr" % self._fact_filter(),
                    (self.chat_id, self.as_of, "%" + name + "%", uid))
                for r in rows:
                    if r.get("yr") is not None:
                        out.setdefault(str(r["yr"]), {})["facts"] = max(
                            int(r["n"]), out.setdefault(str(r["yr"]), {}).get("facts", 0))
                rows = await self._rows(
                    "SELECT CAST(strftime('%Y', timestamp, 'unixepoch') AS INTEGER) "
                    "AS yr, COUNT(*) AS n FROM smart_messages WHERE chat_id=? "
                    "AND user_id=? GROUP BY yr ORDER BY yr", (self.chat_id, uid))
                for r in rows:
                    if r.get("yr") is not None:
                        out.setdefault(str(r["yr"]), {})["messages"] = max(
                            int(r["n"]), out.setdefault(str(r["yr"]), {}).get("messages", 0))
            return out
        match = self._match(terms, and_terms)
        if "status" in col:
            rows = await self._rows(
                "SELECT CAST(strftime('%%Y', COALESCE(f.message_timestamp, "
                "f.created_at), 'unixepoch') AS INTEGER) AS yr, COUNT(*) AS n "
                "FROM graph_facts_fts JOIN graph_facts f "
                "ON f.id=graph_facts_fts.rowid "
                "WHERE graph_facts_fts MATCH ? AND f.chat_id=? AND %s "
                "GROUP BY yr ORDER BY yr" % self._fact_filter(),
                (match, self.chat_id, self.as_of))
        else:
            rows = await self._rows(
                "SELECT CAST(strftime('%Y', COALESCE(f.message_timestamp, "
                "f.created_at), 'unixepoch') AS INTEGER) AS yr, COUNT(*) AS n "
                "FROM graph_facts_fts JOIN graph_facts f "
                "ON f.id=graph_facts_fts.rowid "
                "WHERE graph_facts_fts MATCH ? AND f.chat_id=? "
                "GROUP BY yr ORDER BY yr", (match, self.chat_id))
        for r in rows:
            if r.get("yr") is not None:
                out.setdefault(str(r["yr"]), {})["facts"] = int(r["n"])
        rows = await self._rows(
            "SELECT CAST(strftime('%Y', m.timestamp, 'unixepoch') AS INTEGER) "
            "AS yr, COUNT(*) AS n FROM smart_messages_fts "
            "JOIN smart_messages m ON m.id=smart_messages_fts.rowid "
            "WHERE smart_messages_fts MATCH ? AND m.chat_id=? "
            "GROUP BY yr ORDER BY yr", (match, self.chat_id))
        for r in rows:
            if r.get("yr") is not None:
                out.setdefault(str(r["yr"]), {})["messages"] = int(r["n"])
        if person:
            name, uid = person
            rows = await self._rows(
                "SELECT CAST(strftime('%%Y', COALESCE(f.message_timestamp, "
                "f.created_at), 'unixepoch') AS INTEGER) AS yr, COUNT(*) AS n "
                "FROM graph_facts f WHERE f.chat_id=? AND %s AND "
                "(f.target_user LIKE ? OR f.speaker_author_id=?) "
                "GROUP BY yr ORDER BY yr" % self._fact_filter(),
                (self.chat_id, self.as_of, "%" + name + "%", uid))
            for r in rows:
                if r.get("yr") is not None:
                    out.setdefault(str(r["yr"]), {})["facts"] = max(
                        int(r["n"]), out.setdefault(str(r["yr"]), {}).get("facts", 0))
            rows = await self._rows(
                "SELECT CAST(strftime('%Y', timestamp, 'unixepoch') AS INTEGER) "
                "AS yr, COUNT(*) AS n FROM smart_messages WHERE chat_id=? "
                "AND user_id=? GROUP BY yr ORDER BY yr", (self.chat_id, uid))
            for r in rows:
                if r.get("yr") is not None:
                    out.setdefault(str(r["yr"]), {})["messages"] = max(
                        int(r["n"]), out.setdefault(str(r["yr"]), {}).get("messages", 0))
        return out
    def _match(self, terms, and_terms=()) -> str:
        left = fs_terms(terms, "or")
        right = fs_terms(and_terms, "or")
        if left and right:
            return "(%s) AND (%s)" % (left, right)
        return left or right

    async def _fact_anchors(self, terms, year, and_terms=(), person=None):
        lo, hi = utc_bounds(year)
        match = self._match(terms, and_terms)
        col = await self._cols_of("graph_facts")
        sql = ("SELECT f.id, COALESCE(f.message_timestamp, f.created_at) AS ts, "
               "f.tg_message_id, f.status, f.kind, f.origin, f.target_user, "
               "f.speaker_author_id FROM graph_facts f ")
        params = []
        if match:
            sql = ("SELECT f.id, COALESCE(f.message_timestamp, f.created_at) AS ts, "
                   "f.tg_message_id, f.status, f.kind, f.origin, f.target_user, "
                   "f.speaker_author_id FROM graph_facts_fts "
                   "JOIN graph_facts f ON f.id=graph_facts_fts.rowid ")
            where = ["graph_facts_fts MATCH ?", "f.chat_id=?"]
            params.extend([match, self.chat_id])
        else:
            where = ["f.chat_id=?"]
            params.append(self.chat_id)
        where.extend(["COALESCE(f.message_timestamp, f.created_at)>=?",
                      "COALESCE(f.message_timestamp, f.created_at)<?"])
        params.extend([lo, hi])
        if "status" in col:
            where.append("f.status='confirmed'")
        if "kind" in col:
            where.append("f.kind='fact'")
        where.append("f.origin NOT IN ('bot_direct_reply','bot_self_reply')")
        if "expires_at" in col:
            where.append("(f.expires_at IS NULL OR f.expires_at>?)")
            params.append(self.as_of)
        if person:
            name, uid = person
            where.append("(f.target_user LIKE ? OR f.speaker_author_id=?)")
            params.extend(["%" + name + "%", uid])
        sql += "WHERE " + " AND ".join(where) + " ORDER BY f.id LIMIT 200"
        rows = await self._rows(sql, tuple(params))
        anchors = []
        for row in rows:
            fact_id = as_int(row.get("id"))
            if fact_id is None:
                continue
            tg = as_int(row.get("tg_message_id"))
            refs = ["fact:%d" % fact_id]
            if tg:
                refs.append("tg:%d" % tg)
            anchors.append({
                "kind": "fact", "id": fact_id, "year": year_of(row.get("ts")),
                "ref": "fact:%d" % fact_id, "refs": refs, "tg": tg,
                "status": str(row.get("status") or ""),
                "origin": str(row.get("origin") or ""),
                "derived_no_tg": not bool(tg),
            })
        return anchors

    async def _message_anchors(self, terms, year, and_terms=(), person=None):
        lo, hi = utc_bounds(year)
        match = self._match(terms, and_terms)
        sql = ("SELECT m.id, m.timestamp, m.tg_message_id, m.user_id "
               "FROM smart_messages m ")
        params = []
        if match:
            sql = ("SELECT m.id, m.timestamp, m.tg_message_id, m.user_id "
                   "FROM smart_messages_fts JOIN smart_messages m "
                   "ON m.id=smart_messages_fts.rowid ")
            where = ["smart_messages_fts MATCH ?", "m.chat_id=?"]
            params.extend([match, self.chat_id])
        else:
            where = ["m.chat_id=?"]
            params.append(self.chat_id)
        where.extend(["m.timestamp>=?", "m.timestamp<?"])
        params.extend([lo, hi])
        if person:
            name, uid = person
            where.append("(m.user_id=? OR m.text LIKE ?)")
            params.extend([uid, "%" + name + "%"])
        sql += "WHERE " + " AND ".join(where) + " ORDER BY m.id LIMIT 200"
        rows = await self._rows(sql, tuple(params))
        anchors = []
        for row in rows:
            msg_id = as_int(row.get("id"))
            if msg_id is None:
                continue
            tg = as_int(row.get("tg_message_id"))
            refs = ["row:%d" % msg_id, "msg:%d" % msg_id]
            if tg:
                refs.append("tg:%d" % tg)
            anchors.append({
                "kind": "message", "id": msg_id,
                "year": year_of(row.get("timestamp")),
                "ref": "row:%d" % msg_id, "refs": refs, "tg": tg,
                "user_id": as_int(row.get("user_id")),
                "by_author": bool(person and as_int(row.get("user_id")) == person[1]),
            })
        if person:
            name, uid = person
            rows = await self._rows(
                "SELECT id, timestamp, tg_message_id, user_id FROM smart_messages "
                "WHERE chat_id=? AND user_id=? AND timestamp>=? AND timestamp<? "
                "ORDER BY id LIMIT 200", (self.chat_id, uid, lo, hi))
            for row in rows:
                msg_id = as_int(row.get("id"))
                if msg_id is None:
                    continue
                tg = as_int(row.get("tg_message_id"))
                refs = ["row:%d" % msg_id, "msg:%d" % msg_id]
                if tg:
                    refs.append("tg:%d" % tg)
                anchors.append({
                    "kind": "message", "id": msg_id,
                    "year": year_of(row.get("timestamp")),
                    "ref": "row:%d" % msg_id, "refs": refs, "tg": tg,
                    "user_id": as_int(row.get("user_id")), "by_author": True,
                })
        return anchors

    def _select(self, anchors, kind: str):
        seen = set()
        unique = []
        for anchor in anchors:
            key = (anchor.get("kind"), anchor.get("id"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(anchor)
        unique.sort(key=lambda a: sha256_text(
            "%s:%s:%s" % (self.seed, kind, a.get("id"))))
        return unique[:16]

    async def build(self, spec: dict) -> dict:
        key = spec["ref"]
        if key in self.cache:
            return self.cache[key]
        out = {"key": key, "mode": spec.get("mode"), "expected_years": [],
               "anchors": [], "counts": {"facts": 0, "messages": 0, "by_year": {}},
               "support": {}, "reference_sha256": None, "not_executed": None,
               "as_of": self.as_of, "subject": None}
        person = None
        if spec.get("mode") == "participant":
            slot = spec.get("slot")
            person = self.participants.get(slot)
            if not person:
                out["not_executed"] = "participant_support_insufficient"
                self.cache[key] = out
                return out
            out["subject"] = {
                "pseudo": slot,
                "uid_sha256": sha256_text(person[1]),
                "name_sha256": sha256_text(person[0]),
            }
        mode = spec.get("mode")
        terms = spec.get("terms") or ()
        and_terms = spec.get("and_terms") or ()
        if mode == "topic" and self.e1.get("topic"):
            terms = tuple(self.e1["topic"][1])
        support = await self.support_years(terms, "or", person, and_terms)
        if mode == "year":
            year = int(spec.get("year"))
            years = [year]
            out["support"] = {str(year): support.get(str(year), {})}
        elif mode == "conflict":
            year = int(spec.get("year") or 2023)
            if not support.get(str(year)):
                pre = [int(y) for y in support
                       if int(y) < 2026 and
                       (support[y].get("facts", 0) >= 1
                        or support[y].get("messages", 0) >= 3)]
                if pre:
                    year = min(pre)
            years = [year]
            out["support"] = {str(year): support.get(str(year), {})}
        elif mode == "participant":
            years = [int(y) for y in support
                     if (support[y].get("facts", 0) >= 3
                         or support[y].get("messages", 0) >= 20)]
            years = sorted(years)
            if len(years) < 2 or not any(y < 2026 for y in years):
                out["not_executed"] = "participant_support_insufficient"
                out["support"] = support
                self.cache[key] = out
                return out
            out["support"] = support
        elif mode == "derived":
            years = [int(y) for y in support
                     if (support[y].get("facts", 0) >= 3
                         or support[y].get("messages", 0) >= 10)]
            years = sorted(years)
            if not years or not any(y < 2026 for y in years):
                out["not_executed"] = "reference_support_low"
                out["support"] = support
                self.cache[key] = out
                return out
            out["support"] = support
        elif mode == "relations":
            years = [int(y) for y in support
                     if (support[y].get("facts", 0) >= 3
                         or support[y].get("messages", 0) >= 30)]
            years = sorted(years)
            if len(years) < 2:
                out["not_executed"] = "reference_support_low"
                out["support"] = support
                self.cache[key] = out
                return out
            out["support"] = support
        elif mode == "topic":
            topic = self.e1.get("topic")
            if not topic:
                out["not_executed"] = "topic_support_insufficient"
                self.cache[key] = out
                return out
            years = self.e1.get("years") or []
            out["subject"] = {"topic": topic[0], "terms": list(topic[1])}
            out["support"] = support
        elif mode == "current":
            years = [self.current_year]
            out["support"] = {str(self.current_year):
                              support.get(str(self.current_year), {})}
        elif mode == "counterexample":
            ce = self.counterexample or {}
            if not ce:
                out["not_executed"] = "counterexample_pair_unavailable"
                self.cache[key] = out
                return out
            years = sorted({int(y) for y in ce.get("years") or []})
            out["support"] = support
            out["subject"] = {"topic": ce.get("topic")}
            if ce.get("old_id") and ce.get("new_id"):
                pair = []
                for fid in (ce.get("old_id"), ce.get("new_id")):
                    anchor = await self._fact_by_id(int(fid))
                    if anchor:
                        pair.append(anchor)
                out["anchors"] = pair
                out["counts"]["facts"] = len(pair)
                out["counts"]["messages"] = 0
                out["counts"]["by_year"] = hist([a["year"] for a in pair])
                out["expected_years"] = sorted(
                    {int(y) for y in years})[:5]
                out["reference_sha256"] = sha256_text(compact([
                    {"kind": a["kind"], "id": a["id"], "year": a["year"],
                     "ref": a["ref"]} for a in pair]))
                if not pair:
                    out["not_executed"] = "reference_empty"
                self.cache[key] = out
                return out
            if not (ce.get("old_id") and ce.get("new_id")):
                terms = ("вайп", "сервер")
        else:
            out["not_executed"] = "unknown_reference_mode"
            self.cache[key] = out
            return out
        years = sorted({int(y) for y in years})[:5]
        out["expected_years"] = years
        anchors = []
        missing = []
        for year in years:
            facts = await self._fact_anchors(terms, year, and_terms, person)
            messages = await self._message_anchors(terms, year, and_terms, person)
            facts = self._select(facts, "fact")
            messages = self._select(messages, "message")
            if not facts and not messages:
                missing.append(year)
            anchors.extend(facts)
            anchors.extend(messages)
            out["counts"]["by_year"][str(year)] = {
                "facts": len(facts), "messages": len(messages)}
        out["anchors"] = anchors
        out["counts"]["facts"] = sum(1 for a in anchors if a["kind"] == "fact")
        out["counts"]["messages"] = sum(1 for a in anchors if a["kind"] == "message")
        out["reference_sha256"] = sha256_text(compact([
            {"kind": a["kind"], "id": a["id"], "year": a["year"], "ref": a["ref"]}
            for a in anchors]))
        if not anchors:
            out["not_executed"] = "reference_empty"
        elif missing:
            out["not_executed"] = "reference_empty:%s" % ",".join(map(str, missing))
        self.cache[key] = out
        return out
    async def _fact_by_id(self, fact_id: int):
        rows = await self._rows(
            "SELECT f.id, COALESCE(f.message_timestamp, f.created_at) AS ts, "
            "f.tg_message_id, f.status, f.kind, f.origin FROM graph_facts f "
            "WHERE f.id=? AND f.chat_id=?", (int(fact_id), self.chat_id))
        if not rows:
            return None
        row = rows[0]
        tg = as_int(row.get("tg_message_id"))
        refs = ["fact:%d" % int(row["id"])]
        if tg:
            refs.append("tg:%d" % tg)
        return {"kind": "fact", "id": int(row["id"]),
                "year": year_of(row.get("ts")),
                "ref": "fact:%d" % int(row["id"]), "refs": refs, "tg": tg,
                "status": str(row.get("status") or ""),
                "origin": str(row.get("origin") or ""),
                "derived_no_tg": not bool(tg)}


async def select_participants(db, chat_id: int, seed: str) -> dict:
    cur = await db.db.execute(
        "SELECT user_id, author_name, COUNT(*) AS n, "
        "COUNT(DISTINCT CAST(strftime('%Y', timestamp, 'unixepoch') AS INTEGER)) "
        "AS yrs FROM smart_messages WHERE chat_id=? AND user_id>0 "
        "AND COALESCE(author_name,'')<>'' AND timestamp>=? AND timestamp<? "
        "GROUP BY user_id, author_name HAVING n>=50 AND yrs>=3 "
        "ORDER BY n DESC LIMIT 200",
        (chat_id, utc_bounds(2022)[0], utc_bounds(2025)[1]))
    rows = [dict(r) for r in await cur.fetchall()]
    names = {}
    for row in rows:
        uid = as_int(row.get("user_id"))
        if uid is None or uid in BUILDER_PIDS:
            continue
        if row.get("author_name"):
            names.setdefault(uid, []).append(
                (int(row.get("n") or 0), str(row.get("author_name"))))
    out = {}
    candidates = []
    for uid, pairs in names.items():
        name = sorted(pairs, reverse=True)[0][1]
        cur = await db.db.execute(
            "SELECT COUNT(*) AS n FROM graph_facts WHERE chat_id=? "
            "AND status='confirmed' AND kind='fact' AND "
            "(target_user LIKE ? OR speaker_author_id=?)",
            (chat_id, "%" + name + "%", uid))
        fact_row = await cur.fetchone()
        fact_n = int(fact_row["n"] if fact_row is not None else 0)
        if fact_n < 5:
            continue
        candidates.append({"uid": uid, "name": name, "messages": sum(
            p[0] for p in pairs), "facts": fact_n})
    candidates.sort(key=lambda c: sha256_text(
        "%s:participant:%s" % (seed, c["uid"])))
    for idx, cand in enumerate(candidates[:2]):
        out["P%d" % (idx + 1)] = (cand["name"], cand["uid"])
    return out


async def select_e1(builder: ReferenceBuilder, seed: str) -> dict:
    for label, terms in E1_TOPICS:
        support = await builder.support_years(terms, "or")
        years = sorted(int(y) for y in support
                       if support[y].get("facts", 0) >= 3
                       or support[y].get("messages", 0) >= 20)
        if len(years) >= 2 and any(y < 2026 for y in years):
            return {"topic": (label, tuple(terms)), "years": years[:5],
                    "support": support}
    return {}


async def select_counterexample(builder: ReferenceBuilder) -> dict:
    try:
        rows = await builder._rows(
            "SELECT id, fact, COALESCE(message_timestamp, created_at) AS ts "
            "FROM graph_facts WHERE chat_id=? AND status='confirmed' "
            "AND kind='fact' AND (fact LIKE '%уже не%' OR fact LIKE '%больше не%' "
            "OR fact LIKE '%перестал%' OR fact LIKE '%сейчас%' "
            "OR fact LIKE '%передумал%' OR fact LIKE '%изменил%') "
            "ORDER BY id DESC LIMIT 80", (builder.chat_id,))
    except Exception:
        rows = []
    stop = {"который", "которая", "которые", "чтобы", "потому", "теперь",
            "сейчас", "просто", "вообще", "очень", "можно", "нужно", "будет",
            "было", "были", "есть", "этого", "этому", "такой", "такая"}
    for row in rows:
        text = str(row.get("fact") or "")
        tokens = [t for t in re.findall(r"[А-Яа-яЁёA-Za-z]{5,}", text)
                  if t.lower() not in stop]
        if not tokens:
            continue
        topic = tokens[0]
        old = await builder._rows(
            "SELECT id, COALESCE(message_timestamp, created_at) AS ts "
            "FROM graph_facts WHERE chat_id=? AND status='confirmed' "
            "AND kind='fact' AND id<>? AND fact LIKE ? AND "
            "COALESCE(message_timestamp, created_at) < ? "
            "ORDER BY id LIMIT 20",
            (builder.chat_id, int(row["id"]), "%" + topic[:5] + "%",
             int(row["ts"]) - 180 * 86400))
        if not old:
            continue
        return {"mode": "runtime_changed_position", "topic": topic,
                "old_id": int(old[0]["id"]), "new_id": int(row["id"]),
                "years": [year_of(old[0]["ts"]), year_of(row["ts"])]}
    fallback_years = []
    support = await builder.support_years(("вайп", "сервер"), "or")
    for y in sorted(int(k) for k in support):
        if y < builder.current_year and (support[str(y)].get("facts", 0) >= 1
                                         or support[str(y)].get("messages", 0) >= 3):
            fallback_years.append(y)
    if fallback_years:
        return {"mode": "fallback_event_completed", "topic": "вайп сервера",
                "years": [fallback_years[0], builder.current_year]}
    return {}

class StubLLM:
    def __init__(self):
        self.embed_calls = 0
        self.generate_calls = 0

    async def embed(self, texts):
        self.embed_calls += 1
        raise RuntimeError("EMBED_API_FAILED provider_unavailable")

    async def generate(self, messages, **kwargs):
        self.generate_calls += 1
        raise RuntimeError("LLM unavailable")


class StubAliases:
    def resolve(self, user_id, nickname=None, username=None, memory_name=None):
        return str(nickname or username or memory_name or user_id or "")

    def canon_name(self, name):
        return str(name or "").strip()


class CacheStub:
    def get(self, key, default=None):
        return default

    def get_all(self):
        return {}


def parse_ref(ref: str):
    head, _, tail = str(ref or "").partition(":")
    return head, as_int(tail)


async def resolve_message_ref(db, chat_id: int, ref: str):
    head, rid = parse_ref(ref)
    if rid is None:
        return None
    if head == "row":
        sql = ("SELECT id, timestamp, text, tg_message_id, user_id FROM "
               "smart_messages WHERE id=? AND chat_id=?")
        params = (rid, chat_id)
    elif head == "msg":
        sql = ("SELECT id, timestamp, text, tg_message_id, user_id FROM "
               "smart_messages WHERE chat_id=? AND (id=? OR tg_message_id=?)")
        params = (chat_id, rid, rid)
    elif head == "tg":
        sql = ("SELECT id, timestamp, text, tg_message_id, user_id FROM "
               "smart_messages WHERE chat_id=? AND (tg_message_id=? OR id=?)")
        params = (chat_id, rid, rid)
    else:
        return None
    cur = await db.db.execute(sql, params)
    row = await cur.fetchone()
    return dict(row) if row is not None else None


async def resolve_fact_ref(db, chat_id: int, ref: str):
    head, rid = parse_ref(ref)
    if head != "fact" or rid is None:
        return None
    cur = await db.db.execute(
        "SELECT id, status, kind, tg_message_id, COALESCE(message_timestamp, "
        "created_at) AS ts FROM graph_facts WHERE id=? AND chat_id=?",
        (rid, chat_id))
    row = await cur.fetchone()
    return dict(row) if row is not None else None


async def resolve_ref(db, chat_id: int, ref: str) -> dict:
    head, rid = parse_ref(ref)
    out = {"ref": ref, "kind": head, "id": rid, "resolved": False,
           "weak": False, "reason": ""}
    if rid is None:
        out["reason"] = "unparseable"
        return out
    if head == "fact":
        row = await resolve_fact_ref(db, chat_id, ref)
        if row is None:
            out["reason"] = "fact_missing"
            return out
        out["resolved"] = True
        if str(row.get("status") or "") != "confirmed":
            out["weak"] = True
            out["reason"] = "fact_status_" + str(row.get("status") or "")
        elif not row.get("tg_message_id"):
            out["weak"] = True
            out["reason"] = "fact_without_tg"
        return out
    if head in ("row", "msg", "tg"):
        row = await resolve_message_ref(db, chat_id, ref)
        if row is None:
            out["reason"] = "message_missing"
            return out
        out["resolved"] = True
        return out
    out["reason"] = "unsupported_prefix"
    return out


def _item_year(row) -> int:
    return year_of(row.get("rag_ts") or row.get("message_timestamp"))


async def _message_texts(db, chat_id: int, refs) -> dict:
    out = {}
    for ref in sorted(set(refs))[:120]:
        row = await resolve_message_ref(db, chat_id, ref)
        if row is not None:
            out[ref] = row
    return out


async def probe_question(svc, db, chat_id: int, spec: dict, query: str,
                         policy: str, tail) -> dict:
    from html import escape as html_escape
    from services.payload_builder import build_messages
    entry = {"id": spec["id"], "class": spec["cls"], "policy": policy,
             "query_template": spec["template"], "query_sha256": sha256_text(query),
             "errors": []}
    scope = "historical" if policy == "historical" else "auto"
    plan_act = "historical_recall" if policy == "auto_plan" else ""
    stub = SimpleNamespace(text=query, chat_id=chat_id, message_id=0)
    rows = []
    try:
        rows = await asyncio.wait_for(svc._rag_unified_rows(
            chat_id, query, stub, memory_scope=scope, plan_act=plan_act), 300)
    except Exception as exc:
        entry["errors"].append("rows:%s" % type(exc).__name__)
    rows = list(rows or ())
    period = dict(getattr(svc, "_rag_period_stats", None) or {})
    trace = {}
    rag_block = ""
    try:
        rag_block, _hint = await asyncio.wait_for(svc._build_rag_block(
            chat_id, stub, "", memory_scope=scope, out_memory=trace,
            plan_act=plan_act), 300)
    except Exception as exc:
        entry["errors"].append("rag:%s" % type(exc).__name__)
    ep_block = ""
    ep_stats = {}
    try:
        ep_block, ep_stats = await asyncio.wait_for(
            svc._build_old_episodes(chat_id, query, tail, {}, None, None), 300)
    except Exception as exc:
        entry["errors"].append("episodes:%s" % type(exc).__name__)
    question_block = "<Current_Question>%s</Current_Question>" % html_escape(query)
    user_blocks = [b for b in (rag_block, ep_block, question_block) if b]
    payload = build_messages("[harness-system-placeholder]", user_blocks,
                             time_line="")
    payload_text = payload[1]["content"] if len(payload) > 1 else ""
    bundle_refs = []
    bundle_relations = 0
    bundle_status = "not_requested"
    try:
        bundle_stub = SimpleNamespace(text=query, chat_id=chat_id, message_id=None)
        bundle = await asyncio.wait_for(svc._build_evidence_bundle(
            chat_id, bundle_stub, query, "", None, user_blocks,
            excluded=None, chosen_intent=None, retrieval_result=None), 120)
        if bundle is None:
            bundle_status = "gate_off"
        else:
            bundle_status = "ok"
            bundle_relations = len(getattr(bundle, "relations", ()) or ())
            for item in getattr(bundle, "evidence", ()) or ():
                ref = str(getattr(item, "entity_id", "") or "")
                if REF_RE.fullmatch(ref):
                    bundle_refs.append(ref)
    except Exception as exc:
        bundle_status = "error:%s" % type(exc).__name__
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fact_id = as_int(row.get("id"))
        ref = str(row.get("item_id") or "")
        if not REF_RE.fullmatch(ref) and fact_id is not None:
            ref = "fact:%d" % fact_id
        refs = [ref] if REF_RE.fullmatch(ref) else []
        tg = as_int(row.get("tg_message_id"))
        if tg:
            refs.append("tg:%d" % tg)
        items.append({
            "kind": "fact", "id": fact_id, "ref": ref, "refs": refs,
            "year": _item_year(row), "text": str(row.get("fact") or ""),
            "origin": str(row.get("origin") or ""),
            "status": str(row.get("status") or ""),
            "period_fill": bool(row.get("period_fill")),
            "subject_proxy": row.get("subject_proxy"),
            "user_id": as_int(row.get("user_id")),
            "speaker_author_id": as_int(row.get("speaker_author_id")),
            "target_user": str(row.get("target_user") or ""),
            "subject_ref_id": row.get("subject_ref_id"),
        })
    span_refs = []
    for span in (ep_stats or {}).get("spans") or ():
        for ref in span.get("source_ids") or ():
            span_refs.append(str(ref))
    span_texts = await _message_texts(db, chat_id, span_refs)
    for ref in sorted(set(span_refs)):
        row = span_texts.get(ref)
        if row is None:
            continue
        msg_id = as_int(row.get("id"))
        tg = as_int(row.get("tg_message_id"))
        refs = ["row:%d" % msg_id, "msg:%d" % msg_id]
        if tg:
            refs.append("tg:%d" % tg)
        items.append({
            "kind": "message", "id": msg_id, "ref": "row:%d" % msg_id,
            "refs": refs, "year": year_of(row.get("timestamp")),
            "text": str(row.get("text") or ""), "origin": "episode",
            "status": "confirmed", "period_fill": False, "subject_proxy": None,
            "user_id": as_int(row.get("user_id")), "speaker_author_id": None,
            "target_user": "", "subject_ref_id": None,
        })
    payload_refs = []
    for ref in REF_RE.findall(payload_text):
        if ref not in payload_refs:
            payload_refs.append(ref)
    for ref in bundle_refs:
        if ref not in payload_refs:
            payload_refs.append(ref)
    author_hashes = hist([
        sha256_text(str(i.get("speaker_author_id") or i.get("user_id")))
        for i in items if (i.get("speaker_author_id") or i.get("user_id"))])
    subject_refs = sum(1 for i in items if i.get("subject_ref_id"))
    block_tags = sorted(set(re.findall(r"<([A-Za-z_]+)>", payload_text)))
    rag_lines = []
    for line in str(rag_block or "").splitlines():
        refs = REF_RE.findall(line)
        if refs:
            rag_lines.append({"refs": refs, "archive": "архив" in line,
                              "date": bool(re.search(r"20\d\d", line))})
    entry.update({
        "rows": len(rows),
        "row_years": hist([_item_year(r) for r in rows if isinstance(r, dict)]),
        "items": len(items),
        "years": hist([i["year"] for i in items]),
        "period": {
            "policy": str(period.get("policy") or ""),
            "replace_allowed": int(period.get("replace_allowed") or 0),
            "period_skipped": str(period.get("period_skipped") or ""),
            "intent": period.get("period_intent") or {},
            "intent_source": str(period.get("intent_source") or ""),
            "pool": int(period.get("selection_rows") or 0),
            "kept": int(period.get("selection_kept") or 0),
            "dropped_subject": int(period.get("rejected_subject") or 0),
            "dropped_budget": int(period.get("dropped_budget") or 0),
            "dropped_status": int(period.get("dropped_status") or 0),
            "vector_leg": str(period.get("vector_leg") or ""),
            "vector_rows": int(period.get("vector_rows") or 0),
        },
        "writer": {
            "rag_rendered": bool(rag_block), "rag_chars": len(rag_block or ""),
            "rag_years": dict(trace.get("years") or {}),
            "rag_source_ids": len(trace.get("source_ids") or ()),
            "episode_rendered": bool(ep_block), "episode_chars": len(ep_block or ""),
            "episode_years": dict((ep_stats or {}).get("years") or {}),
            "episode_messages": int((ep_stats or {}).get("messages") or 0),
            "payload_chars": len(payload_text),
            "payload_sha256": sha256_text(payload_text),
            "payload_refs": len(payload_refs),
            "block_tags": block_tags,
        },
        "payload_refs": payload_refs,
        "bundle_status": bundle_status,
        "bundle_ref_count": len(bundle_refs),
        "bundle_relations": bundle_relations,
        "authors": author_hashes,
        "subject_refs": subject_refs,
        "rag_lines": rag_lines,
        "_items": items,
        "_payload": payload_text,
    })
    return entry

def _predicate_match(spec: dict, item: dict, ref: dict, participants: dict) -> bool:
    pred = spec.get("predicate") or ()
    text = str(item.get("text") or "").lower()
    if pred and pred[0] == "__year__":
        return item.get("year") == pred[1]
    if pred and pred[0] == "__subject__":
        person = participants.get(pred[1])
        if not person:
            return False
        name, uid = person
        if item.get("user_id") == uid or item.get("speaker_author_id") == uid:
            return True
        if name and name.lower() in text:
            return True
        target = str(item.get("target_user") or "").lower()
        return bool(name and name.lower() in target)
    if pred and pred[0] == "__topic__":
        terms = (ref.get("subject") or {}).get("terms") or ()
        return any(str(t).lower() in text for t in terms)
    if pred and pred[0] == "__counterexample__":
        topic = str((ref.get("subject") or {}).get("topic") or "").lower()
        return bool(text) and (not topic or topic[:5] in text)
    return any(str(t).lower() in text for t in pred)


async def _item_is_resolved(db, chat_id: int, item: dict, cache: dict) -> bool:
    for ref in item.get("refs") or ():
        if ref not in cache:
            cache[ref] = await resolve_ref(db, chat_id, ref)
        if cache[ref].get("resolved"):
            return True
    return False


async def compute_metrics(entry: dict, ref: dict, spec: dict,
                          participants: dict, current_year: int,
                          db, chat_id: int) -> dict:
    items = list(entry.get("_items") or ())
    anchors = list(ref.get("anchors") or ())
    expected = [int(y) for y in (ref.get("expected_years") or [])]
    years = {i.get("year") for i in items if i.get("year") is not None}
    p_num = len(set(expected) & years)
    p_den = len(expected)
    matched_items = []
    year_ok = 0
    anchor_hits = 0
    for anchor in anchors:
        refs = set(anchor.get("refs") or ())
        if any(refs & set(i.get("refs") or ()) for i in items):
            anchor_hits += 1
    for item in items:
        hit = [a for a in anchors
               if set(a.get("refs") or ()) & set(item.get("refs") or ())]
        if hit:
            matched_items.append(item)
            if any(item.get("year") == a.get("year") for a in hit):
                year_ok += 1
    resolution = {}
    judged = len(items)
    no_text = 0
    relevant = 0
    for item in items:
        if not str(item.get("text") or "").strip():
            no_text += 1
            continue
        resolved = await _item_is_resolved(db, chat_id, item, resolution)
        if resolved and _predicate_match(spec, item, ref, participants):
            relevant += 1
    claims = list(entry.get("payload_refs") or ())
    unres = 0
    weak = 0
    link_cache = {}
    for claim in claims:
        if claim not in link_cache:
            link_cache[claim] = await resolve_ref(db, chat_id, claim)
        info = link_cache[claim]
        if not info.get("resolved"):
            unres += 1
        elif info.get("weak"):
            weak += 1
    out = {
        "coverage": {
            "period": {"num": p_num, "den": p_den,
                       "value": (p_num / p_den) if p_den else None,
                       "applicable": bool(p_den)},
            "anchor": {"num": anchor_hits, "den": len(anchors),
                       "value": (anchor_hits / len(anchors)) if anchors else None,
                       "applicable": bool(anchors)},
        },
        "chrono": {"num": year_ok, "den": len(matched_items),
                   "value": (year_ok / len(matched_items)) if matched_items else None,
                   "applicable": bool(matched_items)},
        "relevance": {"num": relevant, "den": judged,
                      "value": (relevant / judged) if judged else None,
                      "applicable": bool(judged), "no_text": no_text},
        "fabricated": {"num": unres, "den": len(claims),
                       "value": (unres / len(claims)) if claims else None,
                       "applicable": bool(claims), "weak": weak},
        "years": sorted(y for y in years if y is not None),
        "anchor_hits": anchor_hits,
        "old_anchor_hits": sum(
            1 for a in anchors if a.get("year") in (2023, 2024) and any(
                set(a.get("refs") or ()) & set(i.get("refs") or ()) for i in items)),
        "old_anchor_den": sum(
            1 for a in anchors if a.get("year") in (2023, 2024)),
    }
    if spec.get("control") == "current":
        old_items = [i for i in items if i.get("year") and i["year"] < current_year]
        unlabeled = 0
        archive = 0
        dated = 0
        for item in old_items:
            refs = set(item.get("refs") or ())
            lines = [ln for ln in entry.get("rag_lines") or ()
                     if refs & set(ln.get("refs") or ())]
            if not lines:
                continue
            if any(ln.get("archive") for ln in lines):
                archive += 1
            elif any(ln.get("date") for ln in lines):
                dated += 1
            else:
                unlabeled += 1
        out["negative"] = {
            "old_rows": len(old_items), "archive_marked": archive,
            "date_labeled": dated, "unlabeled_old": unlabeled,
            "current_rows": sum(1 for i in items if i.get("year") == current_year),
            "pass": unlabeled == 0,
            "reason": "no_old_rows" if not old_items else "",
        }
    if spec.get("control") == "counterexample":
        old_anchor = next((a for a in anchors
                           if a.get("id") == (entry.get("counterexample") or {}).get("old_id")), None)
        new_anchor = next((a for a in anchors
                           if a.get("id") == (entry.get("counterexample") or {}).get("new_id")), None)
        old_present = bool(old_anchor and any(
            set(old_anchor.get("refs") or ()) & set(i.get("refs") or ()) for i in items))
        new_present = bool(new_anchor and any(
            set(new_anchor.get("refs") or ()) & set(i.get("refs") or ()) for i in items))
        old_labeled = False
        if old_anchor:
            refs = set(old_anchor.get("refs") or ())
            lines = [ln for ln in entry.get("rag_lines") or ()
                     if refs & set(ln.get("refs") or ())]
            old_labeled = bool(lines) and all(
                ln.get("archive") or ln.get("date") for ln in lines)
        out["counterexample"] = {
            "old_present": old_present, "new_present": new_present,
            "old_labeled": old_labeled,
            "pass": (not old_present or old_labeled),
            "mode": (entry.get("counterexample") or {}).get("mode"),
        }
    return out


def _metric_part(metrics: dict, key: str) -> dict:
    cur = metrics or {}
    for part in key.split("."):
        cur = (cur or {}).get(part, {}) if isinstance(cur, dict) else {}
    return cur if isinstance(cur, dict) else {}


def _pool(rows, key: str) -> dict:
    num = sum(int(_metric_part(r.get("metrics"), key).get("num") or 0)
              for r in rows)
    den = sum(int(_metric_part(r.get("metrics"), key).get("den") or 0)
              for r in rows)
    return {"num": num, "den": den, "value": (num / den) if den else None,
            "applicable": bool(den)}


def class_metrics(questions: list) -> dict:
    matrix = [q for q in questions if q.get("class") in MATRIX_CLASSES]
    out = {}
    for prefix, name in MATRIX_CLASSES.items():
        rows = [q for q in matrix if q.get("class") == prefix]
        out[name] = {
            "questions": [q["id"] for q in rows],
            "coverage_anchor": _pool(rows, "coverage.anchor"),
            "coverage_period": _pool(rows, "coverage.period"),
            "chrono": _pool(rows, "chrono"),
            "relevance": _pool(rows, "relevance"),
            "fabricated": _pool(rows, "fabricated"),
        }
    return out

def _value(entry: dict, path: str):
    cur = entry.get("metrics") or {}
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def compute_parity(questions: list) -> list:
    by_id = {q["id"]: q for q in questions}
    pairs = (("H1", "R3"), ("H2", "R4"))
    out = []
    for humor_id, plain_id in pairs:
        h = by_id.get(humor_id)
        p = by_id.get(plain_id)
        item = {"pair": [humor_id, plain_id], "result": "unverified",
                "ordinary_no_worse": None, "reasons": []}
        if not h or not p:
            item["reasons"].append("missing_question")
            out.append(item)
            continue
        checks = (
            ("coverage.anchor", ">="), ("coverage.period", ">="),
            ("chrono", ">="), ("relevance", ">="), ("fabricated", "<="),
        )
        ok = True
        applicable = 0
        for path, direction in checks:
            hv = _value(h, path + ".value")
            pv = _value(p, path + ".value")
            item[path] = {"humor": hv, "plain": pv}
            if hv is None or pv is None:
                item["reasons"].append("not_applicable:%s" % path)
                continue
            applicable += 1
            if direction == ">=":
                good = pv + 1e-9 >= hv
            else:
                good = pv <= hv + 1e-9
            if not good:
                ok = False
                item["reasons"].append("plain_worse:%s" % path)
        if applicable == 0:
            item["result"] = "unverified"
        else:
            item["ordinary_no_worse"] = ok
            item["result"] = "pass" if ok else "fail"
        out.append(item)
    return out


def build_assertions(payload: dict, questions: list, parity: list,
                     controls: dict, fixture: bool = False) -> list:
    out = []

    def add(aid, expected, actual, status):
        out.append({"id": aid, "expected": expected, "actual": actual,
                    "status": status})

    snap = payload.get("snapshot") or {}
    archive = snap.get("archive") or {}
    ro_ok = (snap.get("sha256") == payload.get("snapshot_sha256_after"))
    min_msgs = 1 if fixture else 1500000
    snap_ok = (snap.get("quick_check") == "ok"
               and snap.get("user_version") == 48
               and int(archive.get("messages") or 0) >= min_msgs)
    add("MEM07-SNAPSHOT", "quick_check=ok, user_version=48, archive>=%d, sha stable" % min_msgs,
        {"quick_check": snap.get("quick_check"),
         "user_version": snap.get("user_version"),
         "messages": archive.get("messages"), "readonly": ro_ok},
        "pass" if snap_ok and ro_ok else "fail")
    matrix = [q for q in questions if q.get("class") in MATRIX_CLASSES]
    per_class = {c: sum(1 for q in matrix if q.get("class") == c)
                 for c in MATRIX_CLASSES}
    owner_ok = any(q["id"] == "H1"
                   and q.get("query_template") == OWNER_QUERY for q in questions)
    q_ok = (len(matrix) >= 12 and all(v >= 2 for v in per_class.values())
            and owner_ok and len(controls) == 3)
    add("MEM07-QUESTIONS", "12 matrix questions, >=2 per class, exact owner query, 3 controls",
        {"matrix": len(matrix), "per_class": per_class, "owner_query": owner_ok,
         "controls": sorted(controls)}, "pass" if q_ok else "fail")
    ref_bad = [q["id"] for q in matrix
               if (q.get("reference") or {}).get("not_executed")]
    add("MEM07-REFERENCES", "every matrix question has archive-derived anchors",
        {"without_reference": ref_bad}, "pass" if not ref_bad else "not_executed")
    trace_bad = [q["id"] for q in matrix
                 if (q.get("policies") or {}).get("auto", {}).get("errors")
                 or not (q.get("policies") or {}).get("auto", {}).get("writer", {}).get("payload_chars")]
    add("MEM07-TRACE", "auto policy product retrieve + Writer payload for every matrix question",
        {"without_trace": trace_bad}, "pass" if not trace_bad else "fail")
    metric_bad = []
    for q in matrix:
        metrics = q.get("metrics") or {}
        for key in ("coverage", "chrono", "relevance", "fabricated"):
            part = metrics.get(key) or {}
            if key in ("coverage",):
                if not part.get("anchor", {}).get("den") and not part.get("period", {}).get("den"):
                    metric_bad.append("%s:%s" % (q["id"], key))
            elif not part.get("den") and part.get("applicable", True):
                metric_bad.append("%s:%s" % (q["id"], key))
    add("MEM07-METRICS", "four metrics with explicit denominators for every matrix question",
        {"missing_denominators": metric_bad}, "pass" if not metric_bad else "fail")
    add("MEM07-PARITY", "parity pairs computed from numbers (result stored separately)",
        {"pairs": parity}, "pass")
    control_bad = []
    for qid in ("N1", "N2"):
        neg = ((controls.get(qid) or {}).get("metrics") or {}).get("negative") or {}
        if "pass" not in neg:
            control_bad.append(qid)
    x = controls.get("X1") or {}
    x_status = (x.get("metrics") or {}).get("counterexample", {}).get("pass")
    add("MEM07-CONTROLS", "N1/N2 negative computed, X1 executed or explicitly not_executed",
        {"missing": control_bad, "X1_pass": x_status,
         "X1_reference": (x.get("reference") or {}).get("not_executed")},
        "pass" if not control_bad and x_status is not None else "not_executed")
    forbidden = []
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k)
                if k in ("text", "fact", "query_resolved", "message_text") and isinstance(v, str):
                    forbidden.append(path + "/" + key)
                walk(v, path + "/" + key)
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                walk(v, path + "/" + str(idx))
    walk(payload)
    serialized = json.dumps(payload, ensure_ascii=False)
    secrets = [m for m in SECRET_MARKERS if m in serialized]
    add("MEM07-NO-TEXT", "no message/fact text, resolved personal query or fixture secret in output",
        {"forbidden_fields": forbidden[:20], "secret_hits": secrets},
        "pass" if not forbidden and not secrets else "fail")
    add("MEM07-READONLY", "snapshot sha256 unchanged", {"before": snap.get("sha256"),
        "after": payload.get("snapshot_sha256_after")}, "pass" if ro_ok else "fail")
    add("MEM07-NO-NETWORK", "LLM/embed stubs raised; socket egress blocked",
        {"network_blocked": payload.get("environment", {}).get("network_blocked"),
         "stub_embed_calls": payload.get("environment", {}).get("stub_embed_calls"),
         "stub_generate_calls": payload.get("environment", {}).get("stub_generate_calls")},
        "pass" if payload.get("environment", {}).get("network_blocked") else "fail")
    return out

def compact_ref(ref: dict) -> dict:
    return {
        "key": ref.get("key"), "mode": ref.get("mode"),
        "expected_years": ref.get("expected_years") or [],
        "counts": ref.get("counts") or {},
        "reference_sha256": ref.get("reference_sha256"),
        "not_executed": ref.get("not_executed"),
        "subject": ref.get("subject"),
        "anchors": [{
            "kind": a.get("kind"), "id": a.get("id"), "year": a.get("year"),
            "ref": a.get("ref"),
            "tg": a.get("tg"), "status": a.get("status"),
            "origin": a.get("origin"),
            "derived_no_tg": a.get("derived_no_tg"),
            "by_author": a.get("by_author"),
        } for a in (ref.get("anchors") or ())],
    }


def strip_entry(entry: dict) -> dict:
    out = dict(entry)
    for key in ("_items", "_payload", "rag_lines", "counterexample",
                "reference", "expected_years", "reference_key", "id",
                "class", "query_template", "query_sha256"):
        out.pop(key, None)
    return out


async def run(args, meta: dict) -> dict:
    from services import hot_config as hot
    from services import mca_gates
    from services.database import DatabaseService
    from services.direct_chat_service import DirectChatService
    from services.summary_memory import MemoryManager

    hot.set_config_cache(CacheStub())
    db = DatabaseService(args.db)
    await db.initialize_readonly()
    stub_llm = StubLLM()
    vec = {"vec_ok": False, "vec_dim": None,
           "sqlite_vec_off_reason": None, "sqlite_vec_loaded": False,
           "vec_error": None}
    try:
        memory = MemoryManager(db, stub_llm, aliases=None)

        async def _noop():
            return 0

        memory.backfill_archive_vectors = _noop
        memory.backfill_graph_fact_vectors = _noop
        try:
            vec_ok = bool(await asyncio.wait_for(memory.initialize(), 120))
        except Exception as exc:
            vec_ok = False
            vec["vec_error"] = type(exc).__name__
        vec["vec_ok"] = vec_ok
        vec["vec_dim"] = getattr(memory, "_vec_dim", None)
        vec["sqlite_vec_off_reason"] = getattr(memory, "_vec_off_reason", None)
        vec["sqlite_vec_loaded"] = bool(
            vec_ok or vec["sqlite_vec_off_reason"] == "embed")
        svc = DirectChatService(memory, db, stub_llm, StubAliases())
        tail = await db.get_recent_messages(args.chat_id, 40)
        archive = meta.get("archive") or {}
        current_year = int(archive.get("current_year") or 2026)
        as_of = int(archive.get("max_ts") or int(time.time()))
        seed = sha256_text("%s:%s:%s" % (
            CANDIDATE, args.chat_id, meta.get("sha256") or ""))
        participants = await select_participants(db, args.chat_id, seed)
        builder = ReferenceBuilder(db, args.chat_id, seed, current_year,
                                   as_of, participants, {}, {})
        e1 = await select_e1(builder, seed)
        builder.e1 = e1
        ce = await select_counterexample(builder)
        builder.counterexample = ce
        refs = {}
        for spec in SPECS:
            if spec["ref"] not in refs:
                refs[spec["ref"]] = await builder.build(spec)
        questions = []
        for spec in SPECS:
            q = spec["template"]
            slot = spec.get("slot")
            if slot in ("P1", "P2"):
                person = participants.get(slot)
                q = q.replace("{%s}" % slot, person[0]) if person else None
            elif slot == "E1_topic":
                q = q.replace("{E1_topic}", e1["topic"][0]) if e1 else None
            elif slot == "X1_topic":
                q = q.replace("{X1_topic}", ce.get("topic") or "") if ce else None
            ref = refs.get(spec["ref"]) or {}
            question = {
                "id": spec["id"], "class": spec["cls"],
                "query_template": spec["template"],
                "reference_key": spec["ref"],
                "expected_years": ref.get("expected_years") or [],
                "reference": compact_ref(ref),
                "policies": {},
                "not_executed": None if q else "query_slot_unresolved",
            }
            if not q or ref.get("not_executed"):
                question["not_executed"] = (ref.get("not_executed")
                                            or "query_slot_unresolved")
                question["metrics"] = {}
                questions.append(question)
                continue
            question["query_sha256"] = sha256_text(q)
            for policy in POLICIES:
                entry = await probe_question(svc, db, args.chat_id, spec, q,
                                             policy, tail)
                entry["reference_key"] = spec["ref"]
                entry["expected_years"] = ref.get("expected_years") or []
                entry["reference"] = compact_ref(ref)
                if spec.get("control") == "counterexample":
                    entry["counterexample"] = ce
                entry["metrics"] = await compute_metrics(
                    entry, ref, spec, participants, current_year, db,
                    args.chat_id)
                question["policies"][policy] = strip_entry(entry)
            if spec["id"] in POLICY_HISTORICAL_FOR:
                entry = await probe_question(svc, db, args.chat_id, spec, q,
                                             "historical", tail)
                entry["reference_key"] = spec["ref"]
                entry["expected_years"] = ref.get("expected_years") or []
                entry["reference"] = compact_ref(ref)
                entry["metrics"] = await compute_metrics(
                    entry, ref, spec, participants, current_year, db,
                    args.chat_id)
                question["policies"]["historical"] = strip_entry(entry)
            question["metrics"] = (question["policies"].get("auto") or {}).get(
                "metrics") or {}
            questions.append(question)
        controls = {q["id"]: q for q in questions
                    if q.get("class") in ("N", "X")}
        matrix = [q for q in questions if q.get("class") in MATRIX_CLASSES]
        classes = class_metrics(questions)
        parity = compute_parity(questions)
        time03 = {}
        for qid in ("H1", "H2", "R2", "C1", "P1", "P2", "E1", "E2"):
            q = next((x for x in matrix if x["id"] == qid), None)
            if not q:
                continue
            row = {}
            for policy in POLICIES:
                m = ((q.get("policies") or {}).get(policy) or {}).get("metrics") or {}
                row[policy] = {
                    "years": m.get("years") or [],
                    "old_anchor_hits": m.get("old_anchor_hits"),
                    "old_anchor_den": m.get("old_anchor_den"),
                    "pass": bool(m.get("old_anchor_hits")
                                 and any(y in (2023, 2024)
                                         for y in (m.get("years") or []))),
                }
            time03[qid] = row
        time07 = []
        for q in matrix:
            auto = ((q.get("policies") or {}).get("auto") or {}).get("metrics") or {}
            plan = ((q.get("policies") or {}).get("auto_plan") or {}).get("metrics") or {}
            time07.append({
                "id": q["id"], "class": q["class"],
                "auto_years": auto.get("years") or [],
                "plan_years": plan.get("years") or [],
                "auto_coverage_anchor": (auto.get("coverage") or {}).get("anchor"),
                "plan_coverage_anchor": (plan.get("coverage") or {}).get("anchor"),
                "auto_relevance": auto.get("relevance"),
                "plan_relevance": plan.get("relevance"),
                "auto_fabricated": auto.get("fabricated"),
                "plan_fabricated": plan.get("fabricated"),
            })
        time08 = {
            "yearless": {k: time03.get(k) for k in time03},
            "N1": ((controls.get("N1") or {}).get("metrics") or {}).get("negative"),
            "N2": ((controls.get("N2") or {}).get("metrics") or {}).get("negative"),
            "X1": ((controls.get("X1") or {}).get("metrics") or {}).get("counterexample"),
            "X1_reference": (controls.get("X1") or {}).get("reference"),
        }
        gates = {"retrieval_context": None, "evidence_bundle": None,
                 "typed_reranker": None, "episodes": None,
                 "canonical_attribution": None, "event_contract": None}
        for key, fn in (("retrieval_context", mca_gates.retrieval_context_enabled),
                        ("evidence_bundle", mca_gates.evidence_bundle_enabled),
                        ("typed_reranker", mca_gates.typed_reranker_enabled),
                        ("episodes", mca_gates.episodes_enabled),
                        ("canonical_attribution", mca_gates.canonical_attribution_enabled),
                        ("event_contract", mca_gates.event_contract_enabled)):
            try:
                gates[key] = bool(fn())
            except Exception:
                gates[key] = None
        from config import settings as _settings
        configuration = {
            "gates": gates,
            "graph_rag_enabled": bool(getattr(_settings, "GRAPH_RAG_ENABLED", False)),
            "graph_rag_facts_limit": int(getattr(_settings, "GRAPH_RAG_FACTS_LIMIT", 0) or 0),
            "vector": vec,
        }
        return {
            "chat_id": args.chat_id, "seed": seed, "questions": questions,
            "classes": classes, "parity": parity, "time03": time03,
            "time07": time07, "time08": time08, "controls": controls,
            "configuration": configuration,
            "participants": {k: {"uid_sha256": sha256_text(v[1]),
                                 "name_sha256": sha256_text(v[0])}
                             for k, v in participants.items()},
            "e1": {"topic": (e1.get("topic") or (None,))[0],
                   "years": e1.get("years") or []} if e1 else None,
            "counterexample": {"mode": ce.get("mode"), "years": ce.get("years") or []}
                             if ce else None,
            "stub_embed_calls": stub_llm.embed_calls,
            "stub_generate_calls": stub_llm.generate_calls,
        }
    finally:
        try:
            await db.close()
        except Exception:
            pass

def _pct(part) -> str:
    if not isinstance(part, dict) or part.get("value") is None:
        return "n/a"
    return "%.3f (%s/%s)" % (part["value"], part.get("num"), part.get("den"))


def summary_md(payload: dict) -> str:
    lines = []
    lines.append("# VMQ-MEM-07 - independent five-class evidence")
    lines.append("")
    lines.append("- Generated (local): %s" % time.strftime("%Y-%m-%d %H:%M:%S %z"))
    lines.append("- Mode: %s" % payload.get("mode"))
    lines.append("- Command: %s" % payload.get("command"))
    lines.append("- Candidate: %s" % payload.get("candidate_sha"))
    lines.append("- Code root HEAD: %s" % payload.get("code_root_head"))
    lines.append("- Product diff vs candidate: %s" % payload.get("product_diff_clean"))
    snap = payload.get("snapshot") or {}
    archive = snap.get("archive") or {}
    lines.append("- Snapshot sha256: %s" % snap.get("sha256"))
    lines.append("- Snapshot quick_check: %s; user_version: %s; messages: %s" % (
        snap.get("quick_check"), snap.get("user_version"), archive.get("messages")))
    lines.append("- Chat: %s; current_year: %s; years: %s" % (
        payload.get("chat_id"), archive.get("current_year"), archive.get("by_year")))
    env = payload.get("environment") or {}
    lines.append("- Python: %s; sqlite: %s; sqlite-vec: %s; vector: %s" % (
        env.get("python"), env.get("sqlite"), env.get("sqlite_vec"),
        (payload.get("configuration") or {}).get("vector")))
    lines.append("- Stubs: embed_calls=%s generate_calls=%s; socket_blocked=%s" % (
        env.get("stub_embed_calls"), env.get("stub_generate_calls"),
        env.get("network_blocked")))
    lines.append("")
    lines.append("## Questions (auto policy)")
    lines.append("")
    lines.append("| ID | class | template | expected years | delivered years | coverage anchor | coverage period | chrono | relevance | fabricated |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for q in payload.get("questions") or ():
        auto = (q.get("policies") or {}).get("auto") or {}
        m = q.get("metrics") or {}
        cov = m.get("coverage") or {}
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            q.get("id"), q.get("class"), q.get("query_template"),
            q.get("expected_years"), (auto.get("years") or {}),
            _pct(cov.get("anchor")), _pct(cov.get("period")),
            _pct(m.get("chrono")), _pct(m.get("relevance")),
            _pct(m.get("fabricated"))))
    lines.append("")
    lines.append("## Classes (pooled)")
    lines.append("")
    lines.append("| class | questions | coverage anchor | coverage period | chrono | relevance | fabricated |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, cls in (payload.get("classes") or {}).items():
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            name, ",".join(cls.get("questions") or ()),
            _pct(cls.get("coverage_anchor")), _pct(cls.get("coverage_period")),
            _pct(cls.get("chrono")), _pct(cls.get("relevance")),
            _pct(cls.get("fabricated"))))
    lines.append("")
    lines.append("## Parity (MEM-04)")
    lines.append("")
    for pair in payload.get("parity") or ():
        lines.append("- %s: **%s**; reasons=%s" % (
            pair.get("pair"), pair.get("result"), pair.get("reasons")))
    lines.append("")
    lines.append("## Controls (TIME-03/07/08)")
    lines.append("")
    controls = payload.get("controls") or {}
    for qid in ("N1", "N2"):
        neg = ((controls.get(qid) or {}).get("metrics") or {}).get("negative") or {}
        lines.append("- %s: pass=%s; old_rows=%s; unlabeled_old=%s; current_rows=%s" % (
            qid, neg.get("pass"), neg.get("old_rows"), neg.get("unlabeled_old"),
            neg.get("current_rows")))
    x = ((controls.get("X1") or {}).get("metrics") or {}).get("counterexample") or {}
    lines.append("- X1: pass=%s; mode=%s; old_present=%s; new_present=%s; old_labeled=%s" % (
        x.get("pass"), x.get("mode"), x.get("old_present"), x.get("new_present"),
        x.get("old_labeled")))
    lines.append("")
    lines.append("## TIME-07 within-candidate A/B")
    lines.append("")
    lines.append("| ID | auto years | plan years | auto coverage | plan coverage | auto relevance | plan relevance |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in payload.get("time07") or ():
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            row.get("id"), row.get("auto_years"), row.get("plan_years"),
            _pct(row.get("auto_coverage_anchor")), _pct(row.get("plan_coverage_anchor")),
            _pct(row.get("auto_relevance")), _pct(row.get("plan_relevance"))))
    lines.append("")
    lines.append("## Assertions")
    lines.append("")
    lines.append("| ID | Status | Expected | Actual (counts/hashes only) |")
    lines.append("|---|---|---|---|")
    for a in payload.get("assertions") or ():
        lines.append("| %s | **%s** | %s | `%s` |" % (
            a.get("id"), a.get("status"), a.get("expected"),
            json.dumps(a.get("actual"), ensure_ascii=False)[:600]))
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for item in payload.get("limitations") or ():
        lines.append("- %s" % item)
    lines.append("")
    lines.append("## Note")
    lines.append("")
    lines.append("This harness is evidence tooling. It does not change product code, maps or statuses;")
    lines.append("it does not claim VERIFIED or product quality by itself. Text of messages/facts and")
    lines.append("personal display names are not written; only ids, years, counts, hashes and codes.")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_outputs(out_dir: str, payload: dict, prefix: str) -> dict:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    json_path = os.path.join(out_dir, prefix + ".json")
    md_path = os.path.join(out_dir, prefix + "-summary.md")
    hash_path = os.path.join(out_dir, prefix + "-hashes.txt")
    payload["command"] = " ".join(sys.argv)
    safe_write(json_path, json.dumps(payload, ensure_ascii=False, indent=1))
    safe_write(md_path, summary_md(payload))
    harness_dir = Path(__file__).parent
    files = {}
    for name in ("mem07.py", "make_fixture.py", "test_mem07_smoke.py"):
        p = harness_dir / name
        if p.exists():
            files[name] = sha256_file(str(p))
    outputs = {"json": sha256_file(json_path), "summary": sha256_file(md_path)}
    lines = ["snapshot_sha256_before: %s" % (payload.get("snapshot") or {}).get("sha256"),
             "snapshot_sha256_after: %s" % payload.get("snapshot_sha256_after"),
             "candidate_sha: %s" % payload.get("candidate_sha"),
             "code_root_head: %s" % payload.get("code_root_head")]
    for name, value in sorted(files.items()):
        lines.append("harness_%s: %s" % (name, value))
    for name, value in outputs.items():
        lines.append("output_%s: %s" % (name, value))
    safe_write(hash_path, "\n".join(lines) + "\n")
    return {"files": files, "outputs": outputs, "paths": {
        "json": json_path, "summary": md_path, "hashes": hash_path}}

def git_out(cwd: str, *args):
    try:
        import subprocess
        proc = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        return int(proc.returncode), (proc.stdout or "").strip()
    except Exception:
        return 99, ""


def environment_info() -> dict:
    import platform
    out = {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
           "platform": platform.platform(), "sqlite_vec": None}
    try:
        import importlib.metadata
        out["sqlite_vec"] = importlib.metadata.version("sqlite-vec")
    except Exception:
        pass
    return out


def base_payload(args, meta: dict, code_root: str, head: str,
                 clean, mode: str) -> dict:
    return {
        "schema": SCHEMA, "mode": mode, "generated_at": int(time.time()),
        "candidate_sha": CANDIDATE, "code_root": code_root,
        "code_root_head": head, "product_diff_clean": clean,
        "chat_id": args.chat_id, "snapshot": meta,
        "snapshot_sha256_after": meta.get("sha256"),
        "environment": environment_info(), "configuration": {},
        "seed": None, "questions": [], "classes": {}, "parity": [],
        "time03": {}, "time07": [], "time08": {}, "controls": {},
        "differences": {
            "builder_artifacts_used_as_proof": False,
            "builder_matrix_context": "plans/features/vmq-onto-01/evidence/vmq-mem/formulation-class-matrix.json (2026-11-15, 2.58.203)",
            "mapping": {
                "H1": "A1_creative_owner (same mandatory owner query; different reference)",
                "H2": "no direct Builder class (new humor topic)",
                "R1": "B_retell (different wording/year)",
                "R2": "no direct Builder class (new yearless topic)",
                "R3": "A1P_plain_twin (different wording; same reference as H1)",
                "R4": "no direct Builder class (ordinary twin of H2)",
                "P1": "C_person_profile (different runtime participant)",
                "P2": "C_person_profile (second runtime participant)",
                "C1": "D_conflict_2023 (yearless formulation)",
                "C2": "no direct Builder class (2024 conflict)",
                "E1": "E_relations_years (topic-specific)",
                "E2": "E_relations_years (friendship/quarrel wording)",
                "N1": "T3_current (different question)",
                "N2": "T3_current (different question)",
                "X1": "no direct Builder class (changed-position counterexample)",
            },
            "note": "Builder values are context only, not proof; numeric differences are recorded after the real run.",
        },
        "assertions": [],
        "limitations": [
            "Read-only snapshot; not the live process.",
            "LLM/embedding clients are failing stubs; no generated answer text.",
            "Vector leg is compat_not_proven when the embed stub fails; lexical path is measured, not semantic retrieval.",
            "Product block builders (_build_rag_block, _build_old_episodes) and canonical build_messages are used; the full L1 turn composer and system prompt are out of scope.",
            "One chat, one run per configuration; no statistical generalization.",
            "TIME-07 is within-candidate A/B (auto vs auto_plan), not a cross-release baseline.",
            "Fabricated-link metric covers payload/bundle refs, not generated prose.",
        ],
    }


def publish_not_executed(args, meta: dict, reason: str, code_root: str = "",
                         head: str = "", mode: str = "snapshot") -> int:
    payload = base_payload(args, meta, code_root, head, False, mode)
    payload["technical_reason"] = reason
    payload["assertions"] = [{
        "id": "MEM07-RUN", "expected": "executed read-only on candidate snapshot",
        "actual": {"reason": reason}, "status": "not_executed"}]
    info = write_outputs(args.out, payload,
                         "fixture" if mode == "fixture" else "mem07-independent")
    print(json.dumps({"status": "not_executed", "reason": reason,
                      "out": info["paths"]}, ensure_ascii=False))
    return 2 if reason.startswith("snapshot_") else 4

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="VMQ-MEM-07 independent read-only harness")
    parser.add_argument("--db", help="fresh SQLite snapshot (read-only)")
    parser.add_argument("--chat-id", type=int, default=CHAT)
    parser.add_argument("--out", default="", help="output directory")
    parser.add_argument("--code-root", default="", help="worktree with product code")
    parser.add_argument("--fixture", action="store_true",
                        help="build a synthetic fixture and run on it (never production evidence)")
    parser.add_argument("--dry-run", action="store_true", help="print resolved config only")
    parser.add_argument("--no-network-block", action="store_true",
                        help="do not install the socket egress guard")
    parser.add_argument("--builder-matrix", default="",
                        help="path to Builder matrix (context only; never proof)")
    args = parser.parse_args(argv)
    mode = "fixture" if args.fixture else "snapshot"
    code_root = args.code_root or os.getcwd()
    for extra in (os.getcwd(), code_root):
        if extra and extra not in sys.path:
            sys.path.insert(0, extra)
    if not args.out:
        args.out = tempfile.mkdtemp(prefix="mem07-out-")
    if args.dry_run:
        print(json.dumps({
            "candidate": CANDIDATE, "chat_id": args.chat_id, "mode": mode,
            "db": args.db, "out": args.out, "code_root": code_root,
            "expected_schema": 48, "builder_matrix_context": args.builder_matrix,
        }, ensure_ascii=False, indent=1))
        return 0
    if args.fixture:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        from make_fixture import build_fixture
        fixture_dir = tempfile.mkdtemp(prefix="mem07-fixture-")
        args.db = os.path.join(fixture_dir, "fixture.db")
        asyncio.run(build_fixture(args.db, chat_id=args.chat_id))
    if not args.db or not os.path.exists(args.db):
        meta = {"exists": False, "sha256": None, "quick_check": None,
                "user_version": None, "tables": {}, "archive": {},
                "path_name": os.path.basename(args.db or "")}
        return publish_not_executed(args, meta, "snapshot_missing", code_root,
                                    "", mode)
    meta = snapshot_meta(args.db, args.chat_id)
    if meta.get("quick_check") != "ok":
        return publish_not_executed(
            args, meta, "snapshot_quick_check_%s" % meta.get("quick_check"),
            code_root, "", mode)
    if int(meta.get("user_version") or 0) != 48:
        return publish_not_executed(
            args, meta, "snapshot_user_version_%s" % meta.get("user_version"),
            code_root, "", mode)
    rc, head = git_out(code_root, "rev-parse", "HEAD")
    rc2, diff = git_out(code_root, "diff", "--stat", CANDIDATE, "--",
                        "services", "handlers", "web/api", "web/static", "config")
    rc3, status = git_out(code_root, "status", "--porcelain", "--",
                          "services", "handlers", "web/api", "web/static", "config")
    clean = (rc == 0 and rc2 == 0 and not diff and rc3 == 0 and not status)
    if not clean and mode != "fixture":
        return publish_not_executed(args, meta, "product_diff_vs_candidate",
                                    code_root, head, mode)
    block = None
    try:
        if args.no_network_block:
            result = asyncio.run(run(args, meta))
            network = {"enabled": False, "blocked_attempts": None}
        else:
            with NetworkBlock() as block:
                result = asyncio.run(run(args, meta))
            network = {"enabled": True, "blocked_attempts": block.blocked}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        payload = base_payload(args, meta, code_root, head, clean, mode)
        payload["technical_reason"] = "technical_failure:%s" % type(exc).__name__
        payload["assertions"] = [{
            "id": "MEM07-RUN", "expected": "technical run completed",
            "actual": {"error": type(exc).__name__}, "status": "fail"}]
        info = write_outputs(args.out, payload,
                             "fixture" if mode == "fixture" else "mem07-independent")
        print(json.dumps({"status": "technical_failure",
                          "error": type(exc).__name__, "out": info["paths"]},
                         ensure_ascii=False))
        return 4
    after = sha256_file(args.db)
    payload = base_payload(args, meta, code_root, head, clean, mode)
    payload.update(result)
    payload["snapshot_sha256_after"] = after
    payload["environment"].update({
        "stub_embed_calls": result.get("stub_embed_calls"),
        "stub_generate_calls": result.get("stub_generate_calls"),
        "network_blocked": network.get("enabled"),
        "blocked_attempts": network.get("blocked_attempts"),
    })
    payload["configuration"] = result.get("configuration") or {}
    payload["assertions"] = build_assertions(
        payload, payload.get("questions") or [], payload.get("parity") or [],
        payload.get("controls") or {}, fixture=(mode == "fixture"))
    statuses = [a.get("status") for a in payload.get("assertions") or ()]
    if after != meta.get("sha256"):
        rc = 3
    elif "fail" in statuses:
        rc = 1
    elif "not_executed" in statuses:
        rc = 2
    else:
        rc = 0
    info = write_outputs(args.out, payload,
                         "fixture" if mode == "fixture" else "mem07-independent")
    print(json.dumps({"status": ["ok", "fail", "not_executed", "readonly_violation"][rc]
                      if rc < 4 else "technical_failure",
                      "exit": rc, "out": info["paths"],
                      "assertions": {a["id"]: a["status"] for a in payload["assertions"]}},
                     ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
