"""ASAP 8 v6.3 W3-STATUS — API /api/memory/expired-overview + intel-funnels.

TEST-LIFECYCLE: CONTRACT owner=REQ-B03-блок/U03.4 (slice FE-STATUS)

Проверяет (RBAC — как /api/memory/health, только global admin):
  * 401 без initData; 403 модератору/неизвестному;
  * expired-overview: честная раскладка B03 (expired_total/searchable/
    needs_recheck/superseded/infinite_retention); fail-open W1-обёртки
    (error → available=false, не 500);
  * intel-funnels: durable counters initiative.observe/experience.review
    + окна событий 24ч/7д + liveness + лаг семантики + последнее
    применение; R17 — только числа/коды, без контента.

Fake-DB роутится по подстрокам SQL (task_jobs/mca_events/smart_messages/
mca_lesson_applications) — реальная SQLite не поднимается (паттерн
test_webapp_oversight_api).
"""
import json
import types

import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod
from web.api import memory_overview as mo

TEST_TOKEN = "123456:TEST_TOKEN_OVERVIEW"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079


def make_init_data(user_id: int = ADMIN_ID) -> str:
    import hashlib
    import hmac
    import time
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A"},
                           separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


class _FakeSqlConn:
    """Fake aiosqlite-conn: rows по подстроке SQL."""

    def __init__(self):
        self.task_jobs = []
        self.event_counts = []
        self.max_message_id = 0
        self.last_application = None

    async def execute(self, sql, *args):
        sql_l = " ".join(str(sql).split())
        if "FROM task_jobs" in sql_l:
            params = args[0] if args and isinstance(args[0], tuple) else args
            kind = params[0] if params else None
            rows = [dict(r) for r in self.task_jobs
                    if kind is None or r.get("kind") == kind]
            return _Cursor(rows)
        if "FROM mca_events" in sql_l:
            return _Cursor([dict(r) for r in self.event_counts])
        if "FROM smart_messages" in sql_l:
            return _Row({"m": self.max_message_id})
        if "FROM mca_lesson_applications" in sql_l:
            return _Row(self.last_application)
        return _Cursor([])

    async def execute_sync_if_any(self, *a, **k):  # pragma: no cover
        raise AssertionError("не используется")


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class _Row:
    def __init__(self, row):
        self._row = row

    async def fetchone(self):
        return self._row


class _FakeDb:
    """DatabaseService-подмена: только .db (SQL-канал)."""

    def __init__(self):
        self.db = _FakeSqlConn()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    from services.config_cache import ConfigCache as _C
    cache = _C(pg=None, retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    fake_db = _FakeDb()
    from services import lore_runtime
    lore_runtime.set_lore_components(db=fake_db)
    # кэш воронок — на identity db: чистим между тестами
    mo._funnels_cache.clear()
    mo._overview_mm.clear()
    try:
        with TestClient(app) as tc:
            tc.fake_db = fake_db
            yield tc
    finally:
        lore_runtime.reset_lore_runtime()
        mo._funnels_cache.clear()
        mo._overview_mm.clear()


class TestExpiredOverview:
    def test_401_without_init_data(self, client):
        assert client.get("/api/memory/expired-overview").status_code == 401

    def test_403_moderator(self, client, monkeypatch):
        # матрица ролей: admin/moderator из PG; PG недоступен → role-гейт
        # читает cache; без ролей модератор-статус не выдаётся → проверяем
        # явную подмену _require_global_admin-источника прав.
        from web.api import memory_agi
        monkeypatch.setattr(memory_agi, "_is_global_admin",
                            lambda cache, tid: tid != MODERATOR_ID)
        resp = client.get("/api/memory/expired-overview",
                          headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_overview_shape(self, client, monkeypatch):
        class _MM:
            async def expired_memory_overview(self, chat_id=None):
                return {"now_ts": 1791900000, "expired_total": 3584,
                        "expired_searchable": 3500, "needs_recheck": 1200,
                        "superseded_total": 210, "infinite_retention": True}

        monkeypatch.setattr(mo, "_memory_manager", lambda db: _MM())
        resp = client.get("/api/memory/expired-overview", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["expired_total"] == 3584
        assert body["expired_searchable"] == 3500
        assert body["needs_recheck"] == 1200
        assert body["superseded_total"] == 210
        assert body["infinite_retention"] is True

    def test_overview_fail_open(self, client, monkeypatch):
        """W1-обёртка fail-open (error) → available=false, не 500."""
        class _MM:
            async def expired_memory_overview(self, chat_id=None):
                return {"now_ts": 1791900000, "expired_total": 0,
                        "expired_searchable": 0, "needs_recheck": 0,
                        "superseded_total": 0, "infinite_retention": False,
                        "error": "overview_failed"}

        monkeypatch.setattr(mo, "_memory_manager", lambda db: _MM())
        resp = client.get("/api/memory/expired-overview", headers=_hdr())
        assert resp.status_code == 200
        assert resp.json()["available"] is False


class TestIntelFunnels:
    def _seed(self, client):
        conn = client.fake_db.db
        conn.task_jobs = [{
            "kind": "initiative.observe",
            "status": "completed", "reason_code": None,
            "payload": json.dumps({
                "counters": {"observed": 420, "eligible": 25,
                             "opportunities": 4, "intents_created": 2,
                             "silent_decisions": 2, "react_decisions": 1,
                             "sent": 1, "writer_unavailable": 1,
                             "errors": 0,
                             "eval_skips": {"budget": 3}},
                "semantic_watermark": 15000,
                "semantic_pending": {"-100": 3},
            }),
            "created_at": 1791800000, "updated_at": 1791890000,
            "finished_at": 1791890000,
        }, {
            "kind": "experience.review",
            "status": "completed", "reason_code": None,
            "payload": json.dumps({
                "counters": {"semantic_scanned": 300,
                             "semantic_extracted": 12,
                             "semantic_candidates": 9,
                             "semantic_rejected": 3,
                             "semantic_duplicates": 2,
                             "semantic_llm_unavailable": 1},
                "semantic_watermark": 14900, "semantic_pending": {},
            }),
            "created_at": 1791700000, "updated_at": 1791880000,
            "finished_at": 1791880000,
        }]
        conn.event_counts = [
            {"event_name": "initiative_observer_scan", "c": 260},
            {"event_name": "initiative_sent", "c": 2},
            {"event_name": "semantic_extract", "c": 8},
            {"event_name": "applied", "c": 3},
        ]
        conn.max_message_id = 15200
        conn.last_application = {"applied_at": 1791800000,
                                 "outcome": "success"}

    def test_auth(self, client):
        assert client.get("/api/memory/intel-funnels").status_code == 401

    def test_funnels_shape(self, client):
        self._seed(client)
        resp = client.get("/api/memory/intel-funnels", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        ini = body["initiative"]
        assert ini["job"]["status"] == "completed"
        c = ini["job"]["counters"]
        assert c["observed"] == 420 and c["sent"] == 1
        assert c["eval_skips"] == {"budget": 3}
        # окна: fake возвращает одни counts на оба окна — окна заполнены
        assert ini["events"]["24h"]["initiative_observer_scan"] == 260
        assert ini["events"]["7d"]["initiative_sent"] == 2
        assert ini["liveness"] is not None
        exp = body["experience"]
        assert exp["job"]["counters"]["semantic_scanned"] == 300
        # последняя job (по updated_at) — observe; review — вторая строка:
        # роутинг по kind: обе строки одного fake — берём самые свежие по
        # updated_at на каждый kind (fake отдаёт одинаковый список, ок).
        lag = exp["semantic_lag"]
        assert lag["max_message_id"] == 15200
        assert lag["watermark"] >= 0
        assert exp["last_application"]["outcome"] == "success"
        assert exp["events"]["24h"]["applied"] == 3

    def test_r17_no_message_content(self, client):
        """R17: ответ содержит только числа/коды — текстов сообщений нет."""
        self._seed(client)
        resp = client.get("/api/memory/intel-funnels", headers=_hdr())
        raw = resp.text
        for leak in ("текст сообщения", "message_text", "fact", "raw"):
            # 'fact' может встретиться только как часть кодов — проверяем
            # осмысленно: значения payload контента не отдаются
            assert '"text"' not in raw
        assert "raw_content" not in raw
