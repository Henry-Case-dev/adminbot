# -*- coding: utf-8 -*-
"""P1 «Инициатива» — журнал публикаций на РЕАЛЬНЫХ журналах (не стабах).

Проверяется то, что нельзя увидеть в браузере: слияние событий и журнала
квоты в ОДНУ логическую попытку и приоритет реального исхода отправки над
оптимистичным решением.

Контракт (ревью `ui-review.md`, находки F1/F2 от 2026-11-03):

  1. **F1** — последнее РЕАЛЬНОЕ публикационное событие главнее решения:
     решение «успех» + более поздняя отмена (`publication_cancelled`,
     `publication_stale`) читается как «отменено / publication_stale», а
     решение «пропуск» + более поздний `publication_sent` + запись в ledger —
     как «опубликовано» (без противоречия `skipped` + `delivered=true`).
  2. **F2** — события координации из P0 (`initiative_publication_conflict`,
     `initiative_publication_claim`, `publication_deferred_conflict`) видны в
     списке, находятся фильтром причины и присутствуют в цепочке деталей;
     отложенный конфликтом мем читается как «отложено», а не как ошибка, а
     доставленный после ожидания — как публикация.
  3. Пустая/чужая область, пагинация и RBAC не меняются.

Запуск: py -3 -m pytest tests/test_initiative_publications_api.py -q

TEST-LIFECYCLE: CONTRACT owner=HOTFIX-MEME-PUBLICATION-AND-INITIATIVE-UI §2.3
(«Публикации»: одна строка на логическую попытку, реальный исход и причина).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
import types
import urllib.parse

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from services.config_cache import ConfigCache
from web.app import create_app
from web.api import deps as deps_mod

TEST_TOKEN = "123456:TEST_TOKEN_INIT_PUB"
ADMIN_ID = 5885953495
USER_ID = 999999999
CHAT_A = -100500
CHAT_B = -100501
CHAT_EMPTY = -100502
NOW = int(time.time())


# ── окружение web-приложения (тот же приём, что в соседних API-тестах) ──────
def _init_data(user_id: int) -> str:
    fields = {"auth_date": str(int(time.time())), "query_id": "AAHkFg",
              "user": json.dumps({"id": user_id, "first_name": "A"},
                                 separators=(",", ":"))}
    dc = "\n".join(k + "=" + v for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dc.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _hdr(user_id: int = ADMIN_ID, chat=None) -> dict:
    headers = {"X-Telegram-Init-Data": _init_data(user_id)}
    if chat is not None:
        headers["X-Chat-Id"] = str(chat)
    return headers


class _AioConn:
    def __init__(self, conn):
        self._conn = conn

    async def execute(self, sql, params=()):
        return await self._conn.execute(sql, tuple(params))


class _Db:
    def __init__(self, path, conn):
        import pathlib
        self.db_path = pathlib.Path(path)
        self.db = _AioConn(conn)


class _FakePgConn:
    async def execute(self, sql, *args):
        return "UPDATE 1"

    async def fetch(self, sql, *args):
        if "FROM bot_roles" in sql:
            return [{"role_name": "admin", "permissions": {"wildcard": True},
                     "is_custom": False, "role_type": "global_admin"}]
        if "FROM bot_admins" in sql:
            return [{"telegram_id": ADMIN_ID, "role_name": "admin",
                     "added_by": None,
                     "created_at": "2026-09-07T00:00:00+00:00"}]
        return []

    async def fetchrow(self, sql, *args):
        return None


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _CM()

    async def close(self):
        pass


class _FakePg:
    def __init__(self, conn):
        self._pool = _Pool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings=True):
        pass

    async def close(self):
        pass


# ── журналы ────────────────────────────────────────────────────────────────
MCA_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " ts INTEGER NOT NULL, level TEXT NOT NULL, event_name TEXT NOT NULL,"
    " outcome TEXT NOT NULL, trace_id TEXT, operation_id TEXT,"
    " parent_operation_id TEXT, chat_id INTEGER, component TEXT, stage TEXT,"
    " reason_code TEXT, duration_ms INTEGER, attempt INTEGER,"
    " config_version TEXT, model TEXT, provider TEXT, entity_ids TEXT,"
    " usage_json TEXT, error_json TEXT, source_ref_json TEXT)")

OUT_DDL = (
    "CREATE TABLE IF NOT EXISTS mca_bot_outputs (output_id INTEGER PRIMARY KEY"
    " AUTOINCREMENT, bot_user_id INTEGER, chat_id INTEGER NOT NULL,"
    " tg_message_id INTEGER, revision_no INTEGER NOT NULL DEFAULT 1,"
    " sent_at INTEGER, parent_message_ref TEXT, output_kind TEXT NOT NULL,"
    " content_text TEXT, content_ref TEXT, content_hash TEXT,"
    " correlation_id TEXT, source_feature TEXT,"
    " delivery_status TEXT NOT NULL DEFAULT 'delivered',"
    " created_at INTEGER NOT NULL)")

RES_DDL = (
    "CREATE TABLE IF NOT EXISTS meme_initiative_reservation (job_id TEXT PRIMARY"
    " KEY, chat_id INTEGER NOT NULL, day_bucket TEXT NOT NULL,"
    " timezone_name TEXT NOT NULL, timezone_source TEXT NOT NULL,"
    " status TEXT NOT NULL, error_code TEXT NOT NULL DEFAULT '',"
    " created_at INTEGER NOT NULL)")

ATT_DDL = (
    "CREATE TABLE IF NOT EXISTS meme_initiative_attempt (attempt_id TEXT PRIMARY"
    " KEY, chat_id INTEGER NOT NULL, job_id TEXT NOT NULL DEFAULT '',"
    " ts INTEGER NOT NULL, stage TEXT NOT NULL, outcome TEXT NOT NULL,"
    " reason_code TEXT NOT NULL DEFAULT '',"
    " detail TEXT NOT NULL DEFAULT '',"
    " limit_source TEXT NOT NULL DEFAULT '', limit_value INTEGER,"
    " window_messages INTEGER)")


def _facts(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _deferred_events(*, cancelled: bool = True) -> list[dict]:
    """§1.3-цепочка P0: генерация прошла, публикацию отложил конфликт."""
    chain = [
        {"name": "digest_ready", "at": NOW - 700, "run_id": "J1",
         "mode": "automatic", "source": "", "reason": "", "detail": ""},
        {"name": "joke_ready", "at": NOW - 690, "run_id": "J1",
         "mode": "automatic", "source": "", "reason": "", "detail": ""},
        {"name": "image_ready", "at": NOW - 680, "run_id": "J1",
         "mode": "automatic", "source": "", "reason": "", "detail": ""},
        {"name": "publication_requested", "at": NOW - 670, "run_id": "J1",
         "mode": "automatic", "source": "", "reason": "",
         "detail": "claim_requested"},
        {"name": "publication_deferred_conflict", "at": NOW - 660,
         "run_id": "J1", "mode": "automatic", "source": "deferred",
         "reason": "publication_conflict", "detail": "deferred|slot_busy"},
    ]
    if cancelled:
        chain.append({
            "name": "publication_cancelled", "at": NOW - 650, "run_id": "J1",
            "mode": "automatic", "source": "deferred",
            "reason": "publication_expired", "detail": "expired",
            "delivered": False})
    return chain


def _build_journals(path: str) -> None:
    con = sqlite3.connect(path)
    for ddl in (MCA_DDL, OUT_DDL, RES_DDL, ATT_DDL):
        con.execute(ddl)
    con.execute("INSERT INTO meme_initiative_reservation VALUES"
                " ('J1',?,?,?,?,?,?,?)",
                (CHAT_A, "2026-11-03", "UTC", "chat", "reserved", "", NOW))
    attempts = [
        # J1: генерация прошла, публикацию отложил конфликт → «отложено».
        ("a1", CHAT_A, "J1", NOW - 700, "summary", "passed", "",
         _facts({"chars": 120}), "auto", 600, 12),
        ("a2", CHAT_A, "J1", NOW - 690, "joke", "passed", "",
         _facts({"chars": 40, "limit": 395}), "auto", 600, 12),
        ("a3", CHAT_A, "J1", NOW - 680, "image_generation", "passed", "",
         _facts({"chars": 90000}), "auto", 600, 12),
        ("a4", CHAT_A, "J1", NOW - 660, "publish", "skipped",
         "publication_conflict",
         _facts({"events": _deferred_events()}), "auto", 600, 12),
        # J2: обычная доставка.
        ("b1", CHAT_A, "J2", NOW - 3000, "publish", "published", "sent",
         _facts({"publish": {"output": {"tg_message_id": 777}}}), "chat", 800,
         5),
        # J4: отложили, а затем ДОСТАВИЛИ — не отменённая попытка.
        ("d1", CHAT_A, "J4", NOW - 5000, "publish", "skipped",
         "publication_conflict",
         _facts({"events": _deferred_events(cancelled=False)}), "auto", 600, 12),
        ("d2", CHAT_A, "J4", NOW - 400, "publish", "published", "sent",
         _facts({"events": _deferred_events(cancelled=False),
                 "publish": {"output": {"tg_message_id": 999}}}), "auto", 600,
         12),
    ]
    con.executemany("INSERT INTO meme_initiative_attempt VALUES"
                    " (?,?,?,?,?,?,?,?,?,?,?)", attempts)
    events = [
        # T1: решение «пропуск», но отправили — исход = опубликовано.
        (NOW - 1000, "info", "initiative_decided", "skipped", "T1", CHAT_A,
         "decision", "quiet_hours", None),
        (NOW - 900, "info", "publication_sent", "success", "T1", CHAT_A,
         "send", "", None),
        # T2: самостоятельное событие отмены (P0-стиль).
        (NOW - 500, "warn", "publication_stale", "cancelled", "T2", CHAT_A,
         "send", "publication_stale", None),
        # T3: другой чат — в журнал чата A не попадает.
        (NOW - 800, "info", "initiative_decided", "skipped", "T3", CHAT_B,
         "decision", "quiet_hours", None),
        # T0: вне окна периода.
        (NOW - 3456000, "info", "initiative_decided", "skipped", "T0", CHAT_A,
         "decision", "old", None),
        # T4 (F1): решение «успех», затем ОТМЕНА отправки — побеждает отмена.
        (NOW - 200, "info", "initiative_decided", "success", "T4", CHAT_A,
         "decision", "", None),
        (NOW - 150, "warn", "publication_cancelled", "cancelled", "T4", CHAT_A,
         "send", "publication_stale", None),
        # T5 (F2): конфликт координации — виден в списке и под фильтром.
        (NOW - 130, "info", "initiative_decided", "skipped", "T5", CHAT_A,
         "decision", "window_closed", None),
        (NOW - 120, "info", "initiative_publication_conflict", "skipped", "T5",
         CHAT_A, "claim", "publication_conflict", None),
        # ── U1–U4: коды, которых читатель не знал при написании ───────────
        # Ни одно из этих событий не имеет права УДАЛИТЬ строку попытки.
        (NOW - 1500, "info", "initiative_decided", "success", "U1", CHAT_A,
         "decision", "", None),
        (NOW - 1450, "info", "initiative_publication_yielded", "skipped", "U1",
         CHAT_A, "claim", "publication_conflict", None),
        (NOW - 1600, "info", "initiative_decided", "success", "U2", CHAT_A,
         "decision", "", None),
        (NOW - 1550, "info", "publication_hold", "deferred", "U2", CHAT_A,
         "claim", "publication_conflict", None),
        (NOW - 1700, "info", "initiative_decided", "success", "U3", CHAT_A,
         "decision", "", None),
        (NOW - 1650, "info", "publication_pending", "pending", "U3", CHAT_A,
         "claim", "", None),
        (NOW - 1750, "info", "delivery_unknown", "unknown", "U4", CHAT_A,
         "send", "delivery_unknown", None),
    ]
    con.executemany(
        "INSERT INTO mca_events (ts, level, event_name, outcome, trace_id,"
        " chat_id, stage, reason_code, error_json) VALUES (?,?,?,?,?,?,?,?,?)",
        events)
    con.execute(
        "INSERT INTO mca_bot_outputs (chat_id, tg_message_id, sent_at,"
        " output_kind, correlation_id, delivery_status, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (CHAT_A, 555, NOW - 880, "initiative_reply", "T1", "delivered",
         NOW - 880))
    con.commit()
    con.close()


def _client_for(tmp_path, build):
    """Общий стенд: БД журналов + web-приложение + lore-runtime."""
    db_path = str(tmp_path / "journals.sqlite")
    build(db_path)
    deps_mod.settings = types.SimpleNamespace(API_TOKEN=TEST_TOKEN)
    cache = ConfigCache(pg=_FakePg(_FakePgConn()), retry_attempts=1,
                        retry_delay=0)
    asyncio.run(cache.init())
    from services import chat_params as cp_srv
    cp_srv.set_chat_params_cache(cp_srv.ChatParamsCache(cache.pg))
    from services import lore_runtime

    app = create_app(cache)

    async def _open():
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        return conn

    conn = asyncio.run(_open())
    lore_runtime.set_lore_components(db=_Db(db_path, conn))
    try:
        with TestClient(app) as client:
            yield client
    finally:
        cp_srv.set_chat_params_cache(None)
        lore_runtime.reset_lore_runtime()
        asyncio.run(conn.close())


@pytest.fixture()
def api(tmp_path):
    yield from _client_for(tmp_path, _build_journals)


#: Строки, которых нет в базовом стенде: ручной ранний отказ (mode в detail) и
#: две исторические строки БЕЗ `job_id` (реальные данные до P0 corrective).
LEGACY_ATTEMPTS = (
    # manual=True, отказ на гейте: строки этапов нет, есть терминальная.
    ("m-manual", CHAT_A, "MANUAL-1", NOW - 50, "skipped", "skipped",
     "publication_conflict", _facts({"mode": "manual",
                                     "detail": "acquire_denied"}),
     "auto", 600, 12),
    # Две старые строки без родителя: НЕ склеиваются между собой.
    ("old-0", CHAT_A, "", NOW - 7000, "summary", "passed", "",
     _facts({"chars": 10}), "auto", 600, 12),
    ("old-1", CHAT_A, "", NOW - 6900, "publish", "skipped", "cooldown_active",
     _facts({"detail": "historical"}), "auto", 600, 12),
)


def _build_legacy_journals(path: str) -> None:
    _build_journals(path)
    con = sqlite3.connect(path)
    con.executemany("INSERT INTO meme_initiative_attempt VALUES"
                    " (?,?,?,?,?,?,?,?,?,?,?)", LEGACY_ATTEMPTS)
    con.commit()
    con.close()


@pytest.fixture()
def api_legacy(tmp_path):
    yield from _client_for(tmp_path, _build_legacy_journals)


def _rows(client, chat=CHAT_A, **query):
    q = {"days": 7, **query}
    resp = client.get("/api/initiative/publications", headers=_hdr(ADMIN_ID, chat),
                      params=q)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _row(body, attempt_id):
    return next((r for r in body["rows"] if r["attempt_id"] == attempt_id), None)


# ── F1: последнее реальное публикационное событие главнее решения ──────────
def test_decision_success_then_cancelled_reads_as_cancelled(api):
    body = _rows(api)
    row = _row(body, "text:T4")
    assert row is not None, [r["attempt_id"] for r in body["rows"]]
    assert row["outcome"] == "cancelled", row
    assert row["reason_code"] == "publication_stale", row
    assert row["delivered"] is False, row
    assert row["chain_len"] == 2, row


def test_decision_skip_then_sent_reads_as_published(api):
    body = _rows(api)
    row = _row(body, "text:T1")
    assert row is not None
    assert row["outcome"] == "published", row
    assert row["delivered"] is True and row["message_id"] == 555, row
    assert row["reason_code"] in ("", "sent"), row


def test_standalone_publication_event_is_a_row(api):
    body = _rows(api)
    row = _row(body, "text:T2")
    assert row is not None
    assert row["outcome"] == "cancelled" and row["delivered"] is False, row


# ── F2: конфликты координации видны, фильтруются и есть в цепочке ──────────
def test_coordination_conflict_visible_and_filterable(api):
    body = _rows(api)
    row = _row(body, "text:T5")
    assert row is not None, [r["attempt_id"] for r in body["rows"]]
    assert row["outcome"] == "deferred", row
    assert row["reason_code"] == "publication_conflict", row
    assert "publication_conflict" in (row["reason_codes"] or []), row

    filtered = _rows(api, reason="publication_conflict")
    ids = [r["attempt_id"] for r in filtered["rows"]]
    assert "text:T5" in ids, ids
    assert filtered["counts"]["deferred"] >= 1, filtered["counts"]


def test_conflict_detail_chain_contains_both_events(api):
    resp = api.get("/api/initiative/publications/detail?attempt_id=text:T5",
                   headers=_hdr(ADMIN_ID, CHAT_A))
    assert resp.status_code == 200, resp.text
    names = [e["event_name"] for e in resp.json()["events"]]
    assert "initiative_decided" in names, names
    assert "initiative_publication_conflict" in names, names


def test_meme_deferred_conflict_is_not_a_failure(api):
    body = _rows(api)
    row = _row(body, "meme:J1")
    assert row is not None
    assert row["outcome"] == "deferred", row
    assert row["delivered"] is None, row
    assert "publication_conflict" in (row["reason_codes"] or []), row
    filtered = _rows(api, reason="publication_conflict")
    assert "meme:J1" in [r["attempt_id"] for r in filtered["rows"]]


def test_meme_delivered_after_deferral_reads_as_published(api):
    body = _rows(api)
    row = _row(body, "meme:J4")
    assert row is not None
    assert row["outcome"] == "published", row
    assert row["delivered"] is True and row["message_id"] == 999, row
    # Фильтр по причине конфликта находит и доставленную попытку: конфликт
    # реально был, поэтому он честно доступен в журнале.
    filtered = _rows(api, reason="publication_conflict")
    assert "meme:J4" in [r["attempt_id"] for r in filtered["rows"]]


# ── Коды, неизвестные читателю, не удаляют строку и видны честно ──────────
def test_unknown_publication_event_with_coordination_reason_is_deferred(api):
    """U1: `initiative_publication_yielded` + skipped + publication_conflict.

    Имя незнакомо, `outcome` незнаком — но причина координации: отправка
    отложена, строка обязана остаться.
    """
    body = _rows(api)
    row = _row(body, "text:U1")
    assert row is not None, [r["attempt_id"] for r in body["rows"]]
    assert row["outcome"] == "deferred", row
    assert row["reason_code"] == "publication_conflict", row
    assert row["delivered"] is None, row
    filtered = _rows(api, reason="publication_conflict")
    assert "text:U1" in [r["attempt_id"] for r in filtered["rows"]]


def test_unknown_publication_event_with_deferred_outcome(api):
    """U2: `publication_hold` + deferred — отложено, а не ошибка."""
    row = _row(_rows(api), "text:U2")
    assert row is not None
    assert row["outcome"] == "deferred", row
    assert row["delivered"] is None, row


def test_unknown_publication_event_is_surfaced_as_other(api):
    """U3: `publication_pending` + pending — строка есть, имя видно сырым."""
    row = _row(_rows(api), "text:U3")
    assert row is not None, "незнакомое событие удалило попытку из журнала"
    assert row["outcome"] == "other", row
    assert row["delivered"] is None, row
    names = [e.get("name") for e in (row.get("other_events") or [])]
    assert "publication_pending" in names, row
    assert "publication_pending" in (row.get("reason_codes") or []), row
    outcomes = [e.get("outcome") for e in (row.get("other_events") or [])]
    assert "pending" in outcomes, row
    # Фильтр по сырому имени тоже находит строку (код не потерян).
    filtered = _rows(api, reason="publication_pending")
    assert "text:U3" in [r["attempt_id"] for r in filtered["rows"]]


def test_delivery_unknown_is_selected_and_filterable(api):
    """U4: `delivery_unknown` — отдельный честный исход, а не «строки нет»."""
    body = _rows(api)
    row = _row(body, "text:U4")
    assert row is not None, "delivery_unknown не попал в выборку"
    assert row["outcome"] == "delivery_unknown", row
    assert row["delivered"] is None, row
    filtered = _rows(api, outcome="delivery_unknown")
    assert "text:U4" in [r["attempt_id"] for r in filtered["rows"]]
    detail = api.get(
        "/api/initiative/publications/detail?attempt_id=text:U4",
        headers=_hdr(ADMIN_ID, CHAT_A)).json()
    assert "delivery_unknown" in [e["event_name"] for e in detail["events"]]


def test_no_known_or_unknown_event_deletes_an_attempt(api):
    """Инвариант: любое событие попытки оставляет её в журнале."""
    body = _rows(api, days=7, limit=100)
    ids = {r["attempt_id"] for r in body["rows"]}
    for attempt in ("text:U1", "text:U2", "text:U3", "text:U4",
                    "text:T4", "text:T5", "meme:J1"):
        assert attempt in ids, (attempt, sorted(ids))


def test_meme_detail_exposes_pipeline_event_chain(api):
    resp = api.get("/api/initiative/publications/detail?attempt_id=meme:J1",
                   headers=_hdr(ADMIN_ID, CHAT_A))
    payload = resp.json()
    assert resp.status_code == 200, resp.text
    names = [e["event_name"] for e in payload["events"]]
    assert "image_ready" in names, names
    assert "publication_deferred_conflict" in names, names
    deferred = next(e for e in payload["events"]
                    if e["event_name"] == "publication_deferred_conflict")
    assert deferred["reason_code"] == "publication_conflict", deferred
    assert deferred["detail"].startswith("deferred"), deferred


# ── Остальные контракты журнала не сломаны ─────────────────────────────────
def test_period_chat_scope_and_empty_chat(api):
    body = _rows(api)
    ids = [r["attempt_id"] for r in body["rows"]]
    assert not any(i.endswith("text:T0") for i in ids), ids
    assert not any(i.endswith("text:T3") for i in ids), ids
    empty = _rows(api, chat=CHAT_EMPTY)
    assert empty["rows"] == [] and empty["counts"]["total"] == 0, empty


def test_pagination_is_stable(api):
    first = _rows(api, limit=2)
    assert first["next_offset"] == 2, first["next_offset"]
    second = _rows(api, limit=2, offset=2)
    ids1 = {r["attempt_id"] for r in first["rows"]}
    ids2 = {r["attempt_id"] for r in second["rows"]}
    assert ids1 and ids2 and ids1.isdisjoint(ids2), (ids1, ids2)


def test_rbac_and_chat_header(api):
    assert api.get("/api/initiative/publications",
                   headers={"X-Chat-Id": str(CHAT_A)}).status_code == 401
    assert api.get("/api/initiative/publications",
                   headers=_hdr()).status_code == 422
    assert api.get("/api/initiative/publications",
                   headers=_hdr(USER_ID, CHAT_A)).status_code == 403


# ═════════════════════════════════════════════════════════════════════════════
# P0-INIT-MEME-UX-DIAG §1/§4 — пять осей в ОДНОМ ответе на ОДИН чат
# ═════════════════════════════════════════════════════════════════════════════
# TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-11-P0-INIT-MEME-UX-DIAG
# (§4: payload.chat_id равен запрошенному; данные другого чата не подмешиваются).


def _diagnostics(api, chat):
    resp = api.get("/api/initiative/mechanism-diagnostics",
                   headers=_hdr(ADMIN_ID, chat))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_mechanism_diagnostics_carries_all_five_axes(api):
    from services import initiative_diagnostics as diag

    body = _diagnostics(api, CHAT_A)
    assert body["schema_version"] == diag.DIAG_SCHEMA_VERSION
    assert body["chat_id"] == CHAT_A
    for name in ("text_initiative", "meme"):
        block = body[name]
        for axis in diag.AXIS_FIELDS:
            assert axis in block, (name, axis)
        assert set(block["configuration"]) == set(diag.CONFIGURATION_FIELDS)
        assert set(block["readiness"]) == set(diag.READINESS_FIELDS)
        assert set(block["last_attempt"]) == set(diag.LAST_ATTEMPT_FIELDS)
        assert set(block["last_delivery"]) == set(diag.LAST_DELIVERY_FIELDS)
        assert {"name", "state", "source"} <= set(
            block["health"]["dependencies"][0])
        assert block["health"]["state"] in ("ok", "degraded", "error",
                                            "unknown")


def test_mechanism_diagnostics_is_scoped_to_the_requested_chat(api):
    """Один чат — один payload: строки другого чата не подмешиваются."""
    chat_a = _diagnostics(api, CHAT_A)
    chat_b = _diagnostics(api, CHAT_B)
    assert chat_a["chat_id"] == CHAT_A
    assert chat_b["chat_id"] == CHAT_B

    # Мем-журнал: самая свежая попытка чата A — J4 (d2, ts=NOW-400).
    assert chat_a["meme"]["last_attempt"]["run_id"] == "J4"
    # У чата B строк мем-журнала нет: попытки не выдумываются, чужой J4 не
    # подмешивается.
    assert chat_b["meme"]["last_attempt"]["run_id"] == ""
    assert chat_b["meme"]["last_attempt"]["incomplete_historical"] is True

    # Текст: события чата A (самое свежее — T5) не попадают в чат B (там T3).
    assert chat_a["text_initiative"]["last_attempt"]["run_id"] == "T5"
    assert chat_b["text_initiative"]["last_attempt"]["run_id"] == "T3"

    # Подтверждённая доставка — только своя: у A есть output с id 555, у B нет.
    assert chat_a["text_initiative"]["last_delivery"]["status"] == "confirmed"
    assert chat_a["text_initiative"]["last_delivery"]["message_id"] == 555
    assert chat_a["text_initiative"]["last_delivery"]["destination"] == CHAT_A
    assert chat_b["text_initiative"]["last_delivery"]["status"] == "never"


def test_mechanism_diagnostics_without_chat_header_is_rejected(api):
    assert api.get("/api/initiative/mechanism-diagnostics",
                   headers=_hdr(ADMIN_ID)).status_code == 422
    assert api.get("/api/initiative/mechanism-diagnostics",
                   headers=_hdr(USER_ID, CHAT_A)).status_code == 403


# ═════════════════════════════════════════════════════════════════════════════
# Ревью 400021cc, блокер 4 — режим и исторические строки в СПИСКЕ попыток
# ═════════════════════════════════════════════════════════════════════════════

def test_manual_early_refusal_is_manual_in_the_publications_list(api_legacy):
    """`mode=manual` из detail JSON доезжает до списка (а не «auto»)."""
    body = _rows(api_legacy, limit=100)
    row = _row(body, "meme:MANUAL-1")
    assert row is not None, [r["attempt_id"] for r in body["rows"]]
    assert row["mode"] == "manual", row
    assert row["incomplete_historical"] is False
    # Ручной режим фильтруется серверно тем же полем.
    manual = _rows(api_legacy, mode="manual", limit=100)
    assert "meme:MANUAL-1" in [r["attempt_id"] for r in manual["rows"]]


def test_legacy_rows_without_job_id_are_marked_historical(api_legacy):
    """Две старые строки без `job_id` — две исторические, а не «нормальные»."""
    body = _rows(api_legacy, limit=100)
    rows = {r["attempt_id"]: r for r in body["rows"]}
    first = rows.get("meme:row:old-0")
    second = rows.get("meme:row:old-1")
    assert first is not None and second is not None, sorted(rows)
    for row in (first, second):
        assert row["incomplete_historical"] is True, row
        assert row["job_id"] == "", row
    # Они НЕ склеены в одну попытку и не выдают себя за попытку с родителем.
    assert first["attempt_id"] != second["attempt_id"]
    # Деталь исторической строки открывается по её же идентификатору.
    detail = api_legacy.get(
        "/api/initiative/publications/detail?attempt_id=meme:row:old-1",
        headers=_hdr(ADMIN_ID, CHAT_A))
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["attempt"]["incomplete_historical"] is True
    assert payload["chain"], payload


def test_regular_attempts_are_not_marked_historical(api):
    """Обычная попытка с `job_id` не помечается исторической."""
    body = _rows(api, limit=100)
    row = _row(body, "meme:J4")
    assert row is not None
    assert row["incomplete_historical"] is False
    assert row["job_id"] == "J4"


def test_missing_db_is_honest(tmp_path):
    deps_mod.settings = types.SimpleNamespace(API_TOKEN=TEST_TOKEN)
    cache = ConfigCache(pg=_FakePg(_FakePgConn()), retry_attempts=1,
                        retry_delay=0)
    asyncio.run(cache.init())
    from services import chat_params as cp_srv
    from services import lore_runtime
    cp_srv.set_chat_params_cache(cp_srv.ChatParamsCache(cache.pg))
    app = create_app(cache)
    lore_runtime.set_lore_components(db=None)
    try:
        with TestClient(app) as client:
            resp = client.get("/api/initiative/publications",
                              headers=_hdr(ADMIN_ID, CHAT_A))
            body = resp.json()
            assert resp.status_code == 200, resp.text
            assert body["available"] is False and "db_unavailable" in body["notes"]
    finally:
        cp_srv.set_chat_params_cache(None)
        lore_runtime.reset_lore_runtime()
