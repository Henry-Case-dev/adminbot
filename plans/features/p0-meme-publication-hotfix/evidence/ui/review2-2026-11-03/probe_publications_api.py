# -*- coding: utf-8 -*-
"""Review probe: /api/initiative/publications (+detail) on REAL sqlite journals + RBAC."""
import json, os, sqlite3, sys, time, types, pathlib
HERE = pathlib.Path(__file__).resolve().parent
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\evol-71536a366a11-a15826a0"
sys.path.insert(0, REPO)
os.chdir(REPO)

import aiosqlite, asyncio
from fastapi.testclient import TestClient
from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_REVIEW"
ADMIN_ID = 5885953495
USER_ID = 999999999
CHAT_A = -100500
CHAT_B = -100501
CHAT_C = -100502
NOW = int(time.time())

def init_data(user_id):
    import hashlib, hmac, urllib.parse
    fields = {"auth_date": str(int(time.time())), "query_id": "AAHkFg",
              "user": json.dumps({"id": user_id, "first_name": "A"}, separators=(",", ":"))}
    dc = "\n".join(k + "=" + v for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dc.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc

def hdr(user_id=ADMIN_ID, chat=None):
    h = {"X-Telegram-Init-Data": init_data(user_id)}
    if chat is not None:
        h["X-Chat-Id"] = str(chat)
    return h

MCA_DDL = ("CREATE TABLE IF NOT EXISTS mca_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
 " level TEXT NOT NULL, event_name TEXT NOT NULL, outcome TEXT NOT NULL, trace_id TEXT, operation_id TEXT,"
 " parent_operation_id TEXT, chat_id INTEGER, component TEXT, stage TEXT, reason_code TEXT, duration_ms INTEGER,"
 " attempt INTEGER, config_version TEXT, model TEXT, provider TEXT, entity_ids TEXT, usage_json TEXT,"
 " error_json TEXT, source_ref_json TEXT)")

OUT_DDL = ("CREATE TABLE IF NOT EXISTS mca_bot_outputs (output_id INTEGER PRIMARY KEY AUTOINCREMENT,"
 " bot_user_id INTEGER, chat_id INTEGER NOT NULL, tg_message_id INTEGER, revision_no INTEGER NOT NULL DEFAULT 1,"
 " sent_at INTEGER, parent_message_ref TEXT, output_kind TEXT NOT NULL, content_text TEXT, content_ref TEXT,"
 " content_hash TEXT, correlation_id TEXT, source_feature TEXT,"
 " delivery_status TEXT NOT NULL DEFAULT 'delivered', created_at INTEGER NOT NULL)")

RES_DDL = ("CREATE TABLE IF NOT EXISTS meme_initiative_reservation (job_id TEXT PRIMARY KEY,"
 " chat_id INTEGER NOT NULL, day_bucket TEXT NOT NULL, timezone_name TEXT NOT NULL,"
 " timezone_source TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',"
 " created_at INTEGER NOT NULL)")

ATT_DDL = ("CREATE TABLE IF NOT EXISTS meme_initiative_attempt (attempt_id TEXT PRIMARY KEY,"
 " chat_id INTEGER NOT NULL, job_id TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL, stage TEXT NOT NULL,"
 " outcome TEXT NOT NULL, reason_code TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',"
 " limit_source TEXT NOT NULL DEFAULT '', limit_value INTEGER, window_messages INTEGER)")

DB_PATH = str(HERE / "review_journals.sqlite")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
con = sqlite3.connect(DB_PATH)
for ddl in (MCA_DDL, OUT_DDL, RES_DDL, ATT_DDL):
    con.execute(ddl)
con.execute("INSERT INTO meme_initiative_reservation VALUES ('J1',?,?,?,?,?,?,?)",
            (CHAT_A, "2026-11-03", "UTC", "chat", "reserved", "", NOW))
attempts = [
    ("a1", CHAT_A, "J1", NOW - 700, "summary", "success", "", json.dumps({"chars": 120}), "auto", 600, 12),
    ("a2", CHAT_A, "J1", NOW - 650, "joke", "success", "", json.dumps({"chars": 40}), "auto", 600, 12),
    ("a3", CHAT_A, "J1", NOW - 600, "image_generation", "success", "", json.dumps({"bytes": 90000}), "auto", 600, 12),
    ("a4", CHAT_A, "J1", NOW - 500, "publish", "cancelled", "publication_stale",
     json.dumps({"publication": {"delivered": False}}), "auto", 600, 12),
    ("b1", CHAT_A, "J2", NOW - 3000, "publish", "published", "",
     json.dumps({"publish": {"output": {"tg_message_id": 777}}}), "chat", 800, 5),
    ("e1", CHAT_A, "J5", NOW - 2000, "publish", "skipped", "publication_conflict", json.dumps({"events": [{"name": "digest_ready", "at": 1, "run_id": "J5", "mode": "automatic", "source": "", "reason": "", "detail": ""}, {"name": "image_ready", "at": 2, "run_id": "J5", "mode": "automatic", "source": "", "reason": "", "detail": ""}, {"name": "publication_requested", "at": 3, "run_id": "J5", "mode": "automatic", "source": "", "reason": "", "detail": "claim_requested"}, {"name": "publication_deferred_conflict", "at": 4, "run_id": "J5", "mode": "automatic", "source": "deferred", "reason": "publication_conflict", "detail": "deferred|slot_busy"}]}), 'auto', 600, 12),
    ("f1", CHAT_A, "J6", NOW - 2500, "publish", "published", "sent", json.dumps({"events": [{"name": "image_ready", "at": 2, "run_id": "J6", "mode": "automatic", "source": "", "reason": "", "detail": ""}, {"name": "publication_deferred_conflict", "at": 4, "run_id": "J6", "mode": "automatic", "source": "deferred", "reason": "publication_conflict", "detail": "deferred|slot_busy"}, {"name": "publication_sent", "at": 9, "run_id": "J6", "mode": "automatic", "source": "", "reason": "sent", "delivered": True}], "publish": {"output": {"tg_message_id": 999}}}), 'auto', 600, 12),
    ("c1", CHAT_B, "J3", NOW - 400, "publish", "published", "",
     json.dumps({"publish": {"output": {"tg_message_id": 888}}}), "auto", 800, 5),
]
con.executemany("INSERT INTO meme_initiative_attempt VALUES (?,?,?,?,?,?,?,?,?,?,?)", attempts)
events = [
    (NOW - 1000, "info", "initiative_decided", "skipped", "T1", CHAT_A, "decision", "quiet_hours", None),
    (NOW - 900, "info", "publication_sent", "success", "T1", CHAT_A, "send", "", None),
    (NOW - 500, "warn", "publication_stale", "cancelled", "T2", CHAT_A, "send", "publication_stale", None),
    (NOW - 800, "info", "initiative_decided", "skipped", "T3", CHAT_B, "decision", "quiet_hours", None),
    (NOW - 3456000, "info", "initiative_decided", "skipped", "T0", CHAT_A, "decision", "old", None),
    (NOW - 200, "info", "initiative_decided", "success", "T4", CHAT_A, "decision", "", None),
    (NOW - 150, "warn", "publication_cancelled", "cancelled", "T4", CHAT_A, "send", "publication_stale", None),
    (NOW - 120, "info", "initiative_publication_conflict", "skipped", "T5", CHAT_A, "claim", "publication_conflict", None),
    (NOW - 1100, "info", "initiative_decided", "skipped", "T6", CHAT_A, "decision", "window_closed", None),
    (NOW - 1050, "info", "initiative_publication_conflict", "skipped", "T6", CHAT_A, "claim", "publication_conflict", None),
    (NOW - 1000, "info", "publication_sent", "success", "T6", CHAT_A, "send", "", None),
    (NOW - 1500, "info", "initiative_decided", "success", "U1", CHAT_A, "decision", "", None),
    (NOW - 1450, "info", "initiative_publication_yielded", "skipped", "U1", CHAT_A, "claim", "publication_conflict", None),
    (NOW - 1600, "info", "initiative_decided", "success", "U2", CHAT_A, "decision", "", None),
    (NOW - 1550, "info", "publication_hold", "deferred", "U2", CHAT_A, "claim", "publication_conflict", None),
    (NOW - 1700, "info", "initiative_decided", "success", "U3", CHAT_A, "decision", "", None),
    (NOW - 1650, "info", "publication_pending", "pending", "U3", CHAT_A, "claim", "", None),
    (NOW - 1750, "info", "delivery_unknown", "unknown", "U4", CHAT_A, "send", "delivery_unknown", None),
    (NOW - 130, "info", "initiative_decided", "skipped", "T5", CHAT_A, "decision", "window_closed", None),
]
con.executemany("INSERT INTO mca_events (ts, level, event_name, outcome, trace_id, chat_id, stage,"
                " reason_code, error_json) VALUES (?,?,?,?,?,?,?,?,?)", events)
con.execute("INSERT INTO mca_bot_outputs (chat_id, tg_message_id, sent_at, output_kind, correlation_id,"
            " delivery_status, created_at) VALUES (?,?,?,?,?,?,?)",
            (CHAT_A, 555, NOW - 880, "initiative_reply", "T1", "delivered", NOW - 880))
con.commit()
con.close()

class _AioConn:
    def __init__(self, conn):
        self._conn = conn
    async def execute(self, sql, params=()):
        return await self._conn.execute(sql, tuple(params))

class _Db:
    def __init__(self, path, conn):
        self.db_path = pathlib.Path(path)
        self.db = _AioConn(conn)

class _FakePgConn:
    async def execute(self, sql, *a):
        return "UPDATE 1"
    async def fetch(self, sql, *a):
        if "FROM bot_roles" in sql:
            return [{"role_name": "admin", "permissions": {"wildcard": True},
                     "is_custom": False, "role_type": "global_admin"}]
        if "FROM bot_admins" in sql:
            return [{"telegram_id": ADMIN_ID, "role_name": "admin", "added_by": None,
                     "created_at": "2026-09-07T00:00:00+00:00"}]
        return []
    async def fetchrow(self, sql, *a):
        return None

class _Pool:
    def __init__(self, c):
        self._c = c
    def acquire(self):
        c = self._c
        class _CM:
            async def __aenter__(self):
                return c
            async def __aexit__(self, *e):
                return False
        return _CM()
    async def close(self):
        pass

class _FakePg:
    def __init__(self, c):
        self._pool = _Pool(c)
    @property
    def pool(self):
        return self._pool
    async def connect(self):
        pass
    async def init(self, seed_settings=True):
        pass
    async def close(self):
        pass

FAILS = []
def check(cond, label, detail=""):
    print(("  OK   " if cond else "  FAIL ") + label + (("  << " + str(detail)) if (not cond and detail) else ""))
    if not cond:
        FAILS.append(label)

deps_mod.settings = types.SimpleNamespace(API_TOKEN=TEST_TOKEN)
cache = ConfigCache(pg=_FakePg(_FakePgConn()), retry_attempts=1, retry_delay=0)
asyncio.run(cache.init())
from services import chat_params as cp_srv
cp_srv.set_chat_params_cache(cp_srv.ChatParamsCache(cache.pg))
app = create_app(cache)
async def _open():
    c = await aiosqlite.connect(DB_PATH)
    return c
lore_conn = asyncio.run(_open())
lore_conn.row_factory = aiosqlite.Row
fake_db = _Db(DB_PATH, lore_conn)
from services import lore_runtime
lore_runtime.set_lore_components(db=fake_db)

with TestClient(app) as tc:
    print("== AUTH / RBAC ==")
    check(tc.get("/api/initiative/publications", headers={"X-Chat-Id": str(CHAT_A)}).status_code == 401,
          "401 без initData")
    r = tc.get("/api/initiative/publications/detail?attempt_id=meme:J1", headers={"X-Chat-Id": str(CHAT_A)})
    check(r.status_code == 401, "detail: 401 без initData", r.status_code)
    r = tc.get("/api/initiative/publications", headers=hdr())
    check(r.status_code == 422, "422 без X-Chat-Id", r.status_code)
    r = tc.get("/api/initiative/publications", headers=hdr(USER_ID, CHAT_A))
    check(r.status_code == 403, "403 не-админу (нет доступа к чату)", (r.status_code, r.text[:120]))
    r = tc.get("/api/initiative/publications/detail?attempt_id=meme:J1", headers=hdr(USER_ID, CHAT_A))
    check(r.status_code == 403, "403 не-админу на detail", (r.status_code, r.text[:120]))

    print("== LIST: реальные журналы ==")
    body = tc.get("/api/initiative/publications?days=7", headers=hdr(ADMIN_ID, CHAT_A)).json()
    ids = [x["attempt_id"] for x in body["rows"]]
    check(body["available"] is True and body["chat_id"] == CHAT_A, "available/chat_id", body.get("available"))
    check("meme:J1" in ids and "meme:J2" in ids, "обе мем-попытки из журнала", ids)
    check("meme:J3" not in ids, "чужая попытка (чат B) не протекла", ids)
    check(not any(i.endswith("text:T3") for i in ids), "события чужого чата не протекли", ids)
    check(not any(i.endswith("text:T0") for i in ids), "событие старше period не попало (days=7)", ids)
    j1 = next(x for x in body["rows"] if x["attempt_id"] == "meme:J1")
    j2 = next(x for x in body["rows"] if x["attempt_id"] == "meme:J2")
    t1 = next((x for x in body["rows"] if x["attempt_id"] == "text:T1"), None)
    check(j1["outcome"] == "cancelled", "J1: исход отменено", j1["outcome"])
    check(j1["reason_code"] == "publication_stale", "J1: точный reason code", j1["reason_code"])
    check(j1["delivered"] is False, "J1: не доставлено (delivered=false)", j1["delivered"])
    check(j1["chain_len"] == 4, "J1: цепочка 4 этапа", j1["chain_len"])
    check(j2["delivered"] is True and j2["message_id"] == 777, "J2: опубликовано, tg id из фактов",
          (j2["delivered"], j2["message_id"]))
    check(j2["limit_source"] == "chat" and j2["limit_value"] == 800, "J2: источник/значение лимита",
          (j2["limit_source"], j2["limit_value"]))
    check(t1 is not None, "текстовая попытка T1 найдена", ids)
    if t1:
        check(t1["delivered"] is True and t1["message_id"] == 555,
              "T1: факт доставки из mca_bot_outputs", (t1["delivered"], t1["message_id"]))
        print("  NOTE  T1: outcome=" + str(t1["outcome"]) + " delivered=" + str(t1["delivered"]))
    check("text:T2" in ids, "событие publication_stale без решения отдельной строкой", ids)
    t5 = next((x for x in body["rows"] if x["attempt_id"] == "text:T5"), None)
    print("  NOTE  T5 (decided + initiative_publication_conflict): " + (json.dumps(t5, ensure_ascii=False) if t5 else "ОТСУТСТВУЕТ"))
    b5 = tc.get("/api/initiative/publications?days=7&reason=publication_conflict", headers=hdr(ADMIN_ID, CHAT_A)).json()
    print("  NOTE  фильтр reason=publication_conflict -> " + str([x["attempt_id"] for x in b5["rows"]]))
    d5 = tc.get("/api/initiative/publications/detail?attempt_id=text:T5", headers=hdr(ADMIN_ID, CHAT_A)).json()
    print("  NOTE  detail T5 events -> " + str([e["event_name"] for e in d5["events"]]))
    t4 = next((x for x in body["rows"] if x["attempt_id"] == "text:T4"), None)
    print("  NOTE  T4 (решение success + publication_cancelled): " + json.dumps(t4, ensure_ascii=False) if t4 else "  NOTE  T4 отсутствует")
    check(t4 is not None and t4["outcome"] == "cancelled" and t4["reason_code"] == "publication_stale", "T4: строка показывает отмену публикации, а не «решение прошло»", (t4 or {}).get("outcome"))
    t1row = next((x for x in body["rows"] if x["attempt_id"] == "text:T1"), None)
    check(t1row is not None and t1row["outcome"] == "published" and t1row["delivered"] is True and t1row["message_id"] == 555, "F1-обратно: решение «пропуск», затем отправка = опубликовано", t1row)
    t6 = next((x for x in body["rows"] if x["attempt_id"] == "text:T6"), None)
    check(t6 is not None and t6["outcome"] == "published" and t6["delivered"] is True, "F2: конфликт, затем доставка = опубликовано (не ошибка)", t6)
    t5 = next((x for x in body["rows"] if x["attempt_id"] == "text:T5"), None)
    check(t5 is not None and t5["outcome"] == "deferred" and t5["reason_code"] == "publication_conflict", "F2: конфликт координации = отложено с точной причиной", t5)
    check(t5 is not None and t5["delivered"] is None, "F2: у отложенной попытки доставка «неизвестно», а не «нет»", (t5 or {}).get("delivered"))
    f5 = tc.get("/api/initiative/publications?days=7&reason=publication_conflict", headers=hdr(ADMIN_ID, CHAT_A)).json()
    f5ids = [x["attempt_id"] for x in f5["rows"]]
    check("text:T5" in f5ids and "text:T6" in f5ids, "F2: фильтр причины находит и отложенную, и доставленную после конфликта", f5ids)
    check(f5["counts"].get("deferred", 0) >= 1, "F2: счётчик отложенных в counts", f5["counts"])
    d5 = tc.get("/api/initiative/publications/detail?attempt_id=text:T5", headers=hdr(ADMIN_ID, CHAT_A)).json()
    d5names = [e["event_name"] for e in d5["events"]]
    check("initiative_publication_conflict" in d5names and "initiative_decided" in d5names, "F2: в детали вся цепочка событий", d5names)
    j1 = next((x for x in body["rows"] if x["attempt_id"] == "meme:J1"), None)
    check(j1 is not None and j1["outcome"] == "cancelled" and j1["reason_code"] == "publication_stale" and j1["delivered"] is False, "мем: отмена публикации читается отменой", j1)
    j5 = next((x for x in body["rows"] if x["attempt_id"] == "meme:J5"), None)
    check(j5 is not None and j5["outcome"] == "deferred" and j5["delivered"] is None, "мем: отложено конфликтом = не ошибка и не «не доставлено»", j5)
    check(j5 is not None and "publication_conflict" in (j5.get("reason_codes") or []), "мем: причина конфликта в наборе причин", (j5 or {}).get("reason_codes"))
    j6 = next((x for x in body["rows"] if x["attempt_id"] == "meme:J6"), None)
    check(j6 is not None and j6["outcome"] == "published" and j6["delivered"] is True and j6["message_id"] == 999, "мем: отложили, затем доставили = опубликовано", j6)
    dj1 = tc.get("/api/initiative/publications/detail?attempt_id=meme:J5", headers=hdr(ADMIN_ID, CHAT_A)).json()
    ev1 = [e["event_name"] for e in dj1.get("events") or []]
    check("publication_deferred_conflict" in ev1, "мем: в детали видна цепочка событий P0 (deferred)", ev1)
    print("  NOTE  detail J5 events: " + json.dumps(ev1, ensure_ascii=False))
    print("  NOTE  detail J5 event[0]: " + json.dumps((dj1.get("events") or [{}])[0], ensure_ascii=False))
    u1 = next((x for x in body["rows"] if x["attempt_id"] == "text:U1"), None)
    t2 = next((x for x in body["rows"] if x["attempt_id"] == "text:T2"), None)
    print("  NOTE  T2 (одиночное publication_stale): " + (json.dumps(t2, ensure_ascii=False) if t2 else "ОТСУТСТВУЕТ"))
    print("  NOTE  U1 (неизвестное имя initiative_publication_yielded): " + (json.dumps(u1, ensure_ascii=False) if u1 else "СТРОКА ОТСУТСТВУЕТ"))
    u2 = next((x for x in body["rows"] if x["attempt_id"] == "text:U2"), None)
    print("  NOTE  U2 (неизвестное имя publication_hold, outcome=deferred): " + (json.dumps(u2, ensure_ascii=False) if u2 else "СТРОКА ОТСУТСТВУЕТ"))
    u3 = next((x for x in body["rows"] if x["attempt_id"] == "text:U3"), None)
    print("  NOTE  U3 (неизвестное имя publication_pending, outcome=pending): " + (json.dumps(u3, ensure_ascii=False) if u3 else "СТРОКА ОТСУТСТВУЕТ"))
    u4 = next((x for x in body["rows"] if x["attempt_id"] == "text:U4"), None)
    print("  NOTE  U4 (delivery_unknown): " + (json.dumps(u4, ensure_ascii=False) if u4 else "СТРОКА ОТСУТСТВУЕТ"))
    check(body["counts"]["meme"] >= 2 and body["counts"]["text"] >= 2, "counts по типам", body["counts"])

    print("== FILTERS / PAGINATION ==")
    b = tc.get("/api/initiative/publications?days=7&kind=meme", headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(all(x["kind"] == "meme" for x in b["rows"]) and b["counts"]["text"] == 0,
          "фильтр kind=meme на сервере", b["counts"])
    b = tc.get("/api/initiative/publications?days=7&outcome=cancelled", headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(all(x["outcome"] == "cancelled" for x in b["rows"]) and len(b["rows"]) >= 1,
          "фильтр outcome=cancelled", b["counts"])
    b = tc.get("/api/initiative/publications?days=7&reason=publication_stale", headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(len(b["rows"]) >= 1 and all("publication_stale" in (x["reason_code"] or "") for x in b["rows"]),
          "фильтр reason=publication_stale", [x["reason_code"] for x in b["rows"]])
    b = tc.get("/api/initiative/publications?days=7&mode=manual", headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(b["rows"] == [], "фильтр mode=manual: пусто (ручных нет)", b["counts"])
    p1 = tc.get("/api/initiative/publications?days=7&limit=2", headers=hdr(ADMIN_ID, CHAT_A)).json()
    off = p1["next_offset"]
    p2 = tc.get("/api/initiative/publications?days=7&limit=2&offset=" + str(off), headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(len(p1["rows"]) == 2 and len(p2["rows"]) >= 1, "пагинация: вторая страница непустая",
          (len(p1["rows"]), len(p2["rows"])))
    check(off is not None and set(x["attempt_id"] for x in p1["rows"]).isdisjoint(
          set(x["attempt_id"] for x in p2["rows"])), "страницы не пересекаются", off)
    b = tc.get("/api/initiative/publications?days=7", headers=hdr(ADMIN_ID, CHAT_C)).json()
    check(b["rows"] == [] and b["counts"]["total"] == 0, "пустой журнал: 0 строк, без падения", b["counts"])

    print("== DETAIL ==")
    d = tc.get("/api/initiative/publications/detail?attempt_id=meme:J1", headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(len(d["chain"]) == 4, "J1: 4 этапа в трассе", len(d["chain"]))
    check([c["stage"] for c in d["chain"]][-1] == "publish", "J1: последний этап publish",
          [c["stage"] for c in d["chain"]])
    check(d["chain"][-1]["reason_code"] == "publication_stale", "J1: точный reason code в трассе",
          d["chain"][-1]["reason_code"])
    check(d["delivery"]["delivered"] is False, "J1: delivery.delivered=false", d["delivery"])
    d = tc.get("/api/initiative/publications/detail?attempt_id=text:T1", headers=hdr(ADMIN_ID, CHAT_A)).json()
    check(len(d["events"]) >= 2, "T1: цепочка событий (решение+отправка)",
          [e["event_name"] for e in d["events"]])
    check(bool(d["delivery"]) and d["delivery"]["message_id"] == 555, "T1: факт доставки", d["delivery"])
    r = tc.get("/api/initiative/publications/detail?attempt_id=nonsense", headers=hdr(ADMIN_ID, CHAT_A))
    check(r.status_code == 422, "422 на неизвестный attempt_id", r.status_code)
    r = tc.get("/api/initiative/publications/detail?attempt_id=meme:J1", headers=hdr(ADMIN_ID, CHAT_B))
    d = r.json()
    check(d["attempt"] is None and d["chain"] == [], "чужая попытка по другому X-Chat-Id не отдаётся",
          (r.status_code, d.get("attempt")))

print("== NO DB ==")
lore_runtime.set_lore_components(db=None)
with TestClient(app) as tc:
    r = tc.get("/api/initiative/publications?days=7", headers=hdr(ADMIN_ID, CHAT_A))
    b = r.json()
    check(r.status_code == 200 and b["available"] is False and "db_unavailable" in b["notes"],
          "нет БД: 200 available=false, а не 500", (r.status_code, b.get("notes")))

cp_srv.set_chat_params_cache(None)
lore_runtime.reset_lore_runtime()
asyncio.run(lore_conn.close())
print("")
print("RESULT: " + ("PASS" if not FAILS else "FAIL") + " (" + str(len(FAILS)) + " failures)")
sys.exit(1 if FAILS else 0)










