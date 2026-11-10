"""UR-F шаг 2 — API-проекция durable-событий хода в инспектор ответа.

Проверяется наблюдаемый контракт `GET /api/direct/turn-diagnostics`
(`plans/features/unified-reply/evidence/ur-f-inspector-contract.md` §4–5) на
РЕАЛЬНЫХ строках `mca_events` в SQLite и РЕАЛЬНЫХ эмиттерах шага 1
(`turn_trace`, `direct_execution`, проектор стиля), а не на моках:

  * якорь цепочки — три `direct_turn_*`; детали (`direct_turn_selection`,
    `reply_search_evidence`, `tool_phase`, `style_policy`) приклеиваются по
    `trace_id` и НЕ создают новых ходов;
  * join строго по `chat_id + trace_id`: переплетённые ходы не смешиваются,
    строка другого чата игнорируется;
  * новый ход отдаёт `stages/source/clock/selection/search/style`; старая
    трасса — `null` + `stages.* = false` при `available: true`;
  * битый/усечённый `usage_json`/`source_ref_json` не даёт 500 и не выдумывает
    числа;
  * повтор положительного факта не дублируется;
  * `include_text=1`: текст из существующих хранилищ, только под правом на
    этот же чат (иначе 403), строка другого чата не отдаётся.

Запуск: pytest tests/test_ur_f_inspector_step2.py -q
"""
import asyncio
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import httpx
import pytest

from services import direct_chat_service
from services import direct_execution
from services import lore_runtime
from services import mca_events
from services import style_policy as _sp
from services import turn_trace
from services.config_cache import ConfigCache
from services.database import DatabaseService

CHAT_ID = -1009876543210
OTHER_CHAT = -1001111111111
ADMIN_ID = 5885953495
STRANGER_ID = 777001
TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"

SOURCE_TG_ID = 501           # сообщение хода
REPLY_PARENT_TG_ID = 500     # сообщение, на которое ответили
OWN_OUTPUT_TG_ID = 77        # своя реплика бота в истории

SOURCE_TEXT = "исходный вопрос владельца"
REPLY_PARENT_TEXT = "то, на что отвечали"
OWN_OUTPUT_TEXT = "своя прошлая реплика бота"
FOREIGN_TEXT = "текст из ДРУГОГО чата — не должен утечь"


# ── тест-клиент: реальный ASGI-запрос через приложение ──────────────────────


class _FakeConn:
    """Минимальный PG-двойник для ConfigCache (роли/admins)."""

    def __init__(self):
        self._rows = {
            "bot_admins": [{"telegram_id": ADMIN_ID, "role_name": "admin",
                            "added_by": None, "created_at": None}],
            "bot_roles": [
                {"role_name": "admin", "permissions": {"wildcard": True},
                 "is_custom": False},
                {"role_name": "user", "permissions": {}, "is_custom": False},
            ],
        }

    async def execute(self, sql, *args):
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        return None

    async def fetch(self, sql, *args):
        for table, rows in self._rows.items():
            if table in sql:
                return rows
        return []

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Tx()


class _FakePool:
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
        self._pool = _FakePool(conn)

    @property
    def pool(self):
        return self._pool

    async def connect(self):
        pass

    async def init(self, seed_settings: bool = True):
        pass

    async def close(self):
        pass


def make_init_data(user_id: int = ADMIN_ID) -> str:
    """Подпись initData существующим токеном (реальная TMA-аутентификация)."""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "u"}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


async def _make_client(monkeypatch):
    """Приложение целиком + httpx ASGI-транспорт (один event loop с БД)."""
    from web.api import deps as deps_mod
    from web.app import create_app

    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    cache = ConfigCache(pg=_FakePg(_FakeConn()), retry_attempts=1,
                        retry_delay=0)
    if not cache.is_initialized:
        await cache.init()
    monkeypatch.setattr("services.hot_config._cache", cache)
    app = create_app(cache)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                             base_url="http://test")


async def _make_db(tmp_path) -> DatabaseService:
    db = DatabaseService(str(tmp_path / "ur_f_step2.db"))
    await db.initialize()
    return db


@pytest.fixture(autouse=True)
def _clean_state():
    turn_trace.reset()
    mca_events.reset_pending()
    yield
    turn_trace.reset()
    mca_events.reset_pending()


# ── реальные эмиттеры шага 1 ────────────────────────────────────────────────


class _Decision:
    """Мини-носитель `EvidenceDecision` (claims/class/required) для coverage."""

    def __init__(self, *, required=True, evidence_class="externally_factual",
                 claims=("c1",)):
        self.required = required
        self.evidence_class = evidence_class
        self.claims = claims


def _emit_chain(trace_id, *, chat_id=CHAT_ID,
                clock_stages=("l1", "tool", "l2"),
                source_message_id=SOURCE_TG_ID,
                reply_to_message_id=REPLY_PARENT_TG_ID):
    """Три ЯКОРНЫХ события хода через публичный API `turn_trace`."""
    trace = turn_trace.begin(
        trace_id, chat_id=chat_id, trigger="botword", flow="direct",
        source_message_id=source_message_id, source_author_id=10,
        reply_to_message_id=reply_to_message_id, reply_to_author_id=9,
        source_message_ts=1_700_000_100, alias_source_author="@Вася",
        alias_reply_parent="Петя")
    turn_trace.note_clock(trace_id, line="[2026-11-06 15:00 МСК]",
                          source="chat", timezone="Europe/Moscow",
                          as_of_utc="2026-11-06T12:00:00+00:00",
                          config_version="cfg3", timezone_source="chat")
    for stage in clock_stages:
        turn_trace.note_clock_stage(trace_id, stage)
    turn_trace.note_l1(trace_id, action="reply", response_act="answer",
                       model="test-model")
    turn_trace.note_tools(
        trace_id, rounds=1,
        tool_results=[{"tool": "web_search", "status": "success",
                       "out_chars": 800, "evidence_refs": ("a", "b")}],
        decision=_Decision())
    turn_trace.emit_context(trace)
    turn_trace.note_l2_request(trace_id, provider="test-provider",
                              model="test-model", max_output_tokens=1000,
                              blocks=["l1:context", "l2:writer"])
    turn_trace.note_l2_completion(trace_id, raw_text="черновик ответа",
                                 final_text="черновик ответа",
                                 stats={"semantic_rewrite_count": 0})
    turn_trace.emit_writer(trace)
    turn_trace.note_delivery(trace_id, outcome="success", channel="reply",
                            tg_message_ids=[42])


def _search_links(prefix="a"):
    return ((f"web:{prefix}1", f"https://example.test/{prefix}1",
             f"Заголовок {prefix}1"),
            (f"web:{prefix}2", f"https://example.test/{prefix}2",
             f"Заголовок {prefix}2"))


def _emit_search(trace_id, *, chat_id=CHAT_ID, links=None, intent="required"):
    """`reply_search_evidence` (слой source_ref_json) реальным эмиттером."""
    links = _search_links() if links is None else links
    evidence = direct_execution.ToolEvidence(
        search_intent=intent, search_called=True,
        search_status=direct_execution.SEARCH_STATUS_OK,
        source_ids=tuple(link[0] for link in links),
        source_count=len(links), evidence_used=True,
        sources=tuple(
            direct_execution.SourceRecord(
                source_id=source_id, tool="web_search", url=url, title=title)
            for source_id, url, title in links))
    return direct_execution.emit_search_trace(
        evidence, chat_id=chat_id, correlation_id=trace_id)


def _emit_tool_phase(trace_id, *, chat_id=CHAT_ID):
    """`tool_phase` (payload стадии) реальным эмиттером."""
    evidence = direct_execution.ToolEvidence(
        search_intent="required", search_called=True,
        search_status=direct_execution.SEARCH_STATUS_OK, source_count=2,
        evidence_used=True)
    direct_execution._emit_tool_phase_event(
        route="direct", chat_id=chat_id, correlation_id=trace_id, llm=None,
        evidence=evidence, mode="search", action="reply", outcome="success",
        finish_reason="search", pack=None, demote_reason="",
        time_context="[2026-11-06 15:00 МСК]")


def _selection_payload(*, source_ids=("msg:1", "msg:2")):
    return {
        "counts": {"available_messages": 40, "included_messages": 12,
                   "window_messages": 25},
        "budget": {"slot": "l2_writer", "window": 128000,
                   "window_source": "chat", "output_reserve": 4096,
                   "available": 90000, "budget": 60000,
                   "policy_mode": "adaptive", "payload_tokens": 41000,
                   "fallback_window": None},
        "blocks": [
            {"kind": "global_tail", "role": "p1", "rendered": True,
             "source_ids": list(source_ids), "first_ts": 1_700_000_000,
             "last_ts": 1_700_000_100, "tokens": 900},
            {"kind": "rag", "role": "p2", "rendered": False,
             "skip_reason": "budget", "tokens": 0},
        ],
        "dropped": [{"reason_code": "over_budget", "kind": "rag", "count": 3}],
        "self_outputs": [{"source_id": f"bot_output_tg:{OWN_OUTPUT_TG_ID}",
                          "tg_message_id": OWN_OUTPUT_TG_ID,
                          "ts": 1_700_000_050}],
        "policy_version": "alloc_v3",
    }


def _emit_selection(trace_id, *, chat_id=CHAT_ID, payload=None):
    turn_trace.note_selection(trace_id, chat_id=chat_id,
                              payload=_selection_payload() if payload is None
                              else payload)


def _emit_style(trace_id, *, chat_id=CHAT_ID, rule_id="no_cliche"):
    """Проекция стиля снимка хода (реальный проектор `direct_chat_service`)."""
    outcome = _sp.StyleOutcome(
        text="черновик ответа", policy_revision="g3", policy_source="global",
        applied=True,
        results=[_sp.RuleOutcome(rule_id=rule_id, kind="form",
                                 status=_sp.STATUS_REPAIRED,
                                 reason="cliche_removed", source="global")])
    direct_chat_service._project_style_snapshot(
        outcome, chat_id=chat_id, correlation_id=trace_id)


def _emit_full_turn(trace_id, *, chat_id=CHAT_ID):
    _emit_chain(trace_id, chat_id=chat_id)
    _emit_selection(trace_id, chat_id=chat_id)
    _emit_search(trace_id, chat_id=chat_id)
    _emit_tool_phase(trace_id, chat_id=chat_id)
    _emit_style(trace_id, chat_id=chat_id)


async def _rows_of(db, trace_id, chat_id=CHAT_ID):
    rows = await mca_events.query_events(db, chat_id=chat_id, limit=400)
    return [row for row in rows if row.get("trace_id") == trace_id], rows


async def _get(client, query, *, user_id=ADMIN_ID):
    return await client.get("/api/direct/turn-diagnostics?" + query,
                            headers=_hdr(user_id))


# ── 1. Новый ход: все секции + корреляция по trace_id ──────────────────────


@pytest.mark.asyncio
async def test_new_trace_projects_all_sections(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_full_turn("corr-new")
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        resp = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-new")
        assert resp.status_code == 200, resp.text
        body = resp.json()

    assert body["available"] is True
    assert body["trace_id"] == "corr-new"
    # Секции-братья существуют и заполнены.
    assert body["stages"] == {"context": True, "writer": True,
                              "delivery": True, "selection": True,
                              "search": True, "tool_phase": True,
                              "style": True}
    assert body["source"]["message_id"] == SOURCE_TG_ID
    assert body["source"]["author_id"] == 10
    assert body["source"]["author_alias"] == "Вася"
    assert body["source"]["message_ts"] == 1_700_000_100
    assert body["source"]["reply_to_id"] == REPLY_PARENT_TG_ID
    assert body["source"]["reply_to_author_id"] == 9
    assert body["source"]["reply_to_alias"] == "Петя"
    assert body["clock"]["timezone"] == "Europe/Moscow"
    assert body["clock"]["stages"] == ["l1", "tool", "l2"]
    # context.clock — расширение того же объекта (обратная совместимость).
    assert body["context"]["clock"]["timezone"] == "Europe/Moscow"
    assert body["context"]["clock"]["stages"] == ["l1", "tool", "l2"]

    selection = body["selection"]
    assert selection["policy_version"] == "alloc_v3"
    assert selection["counts"]["included_messages"] == 12
    # `fallback_window: null` — «окна не было», а НЕ пропуск и не 0.
    assert "fallback_window" in selection["budget"]
    assert selection["budget"]["fallback_window"] is None
    assert selection["budget"]["output_reserve"] == 4096
    assert [b["kind"] for b in selection["blocks"]] == ["global_tail", "rag"]
    # `role` — приоритет вытеснения, а не авторская роль.
    assert selection["blocks"][0]["role"] == "p1"
    assert selection["blocks"][1]["rendered"] is False
    assert selection["blocks"][1]["skip_reason"] == "budget"
    assert selection["dropped"] == [{"reason_code": "over_budget",
                                     "kind": "rag", "count": 3}]
    assert selection["self_outputs"][0]["tg_message_id"] == OWN_OUTPUT_TG_ID

    search = body["search"]
    assert search["decision"] == "required"
    assert search["called"] is True
    assert search["status"] == direct_execution.SEARCH_STATUS_OK
    assert search["evidence_class"] == "externally_factual"
    assert search["required"] is True
    assert search["source_count"] == 2
    assert search["source_ids"] == ["web:a1", "web:a2"]
    assert search["links"][0]["source_url"] == "https://example.test/a1"
    assert search["links"][0]["source_title"] == "Заголовок a1"

    style = body["style"]
    assert style["revision"] == "g3"
    assert style["source"] == "global"
    assert style["applied"] is True
    assert [r["rule_id"] for r in style["rules"]] == ["no_cliche"]
    assert style["rules"][0]["status"] == _sp.STATUS_REPAIRED
    assert style["rules"][0]["reason"] == "cliche_removed"

    # Текст в трассе не появляется ни в каком виде (R17) — только по запросу.
    assert "text" not in body["source"]
    assert "исходный вопрос" not in resp.text


# ── 2. Старая трасса: null-секции, stages false, available true ─────────────


@pytest.mark.asyncio
async def test_old_trace_returns_null_sections(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    trace = turn_trace.begin("corr-old", chat_id=CHAT_ID, trigger="botword")
    turn_trace.emit_context(trace)
    turn_trace.emit_writer(trace)
    turn_trace.emit_delivery(trace)
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        resp = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-old")
        assert resp.status_code == 200, resp.text
        body = resp.json()

    assert body["available"] is True
    assert body["context"] is not None
    assert body["stages"] == {"context": True, "writer": True,
                              "delivery": True, "selection": False,
                              "search": False, "tool_phase": False,
                              "style": False}
    assert body["selection"] is None
    assert body["search"] is None
    assert body["style"] is None
    # Старая трасса не знает ни источника, ни стадий часов: null, не 0.
    assert body["source"] == {"message_id": None, "author_id": None,
                              "author_alias": None, "message_ts": None,
                              "reply_to_id": None, "reply_to_author_id": None,
                              "reply_to_alias": None}
    assert body["clock"]["stages"] is None


# ── 3. Битый/усечённый JSON: без 500 и без выдуманных чисел ─────────────────


@pytest.mark.asyncio
async def test_malformed_json_is_honest_not_500(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-broken")
    _emit_selection("corr-broken")
    _emit_search("corr-broken")
    await mca_events.flush_events(db)

    rows, _ = await _rows_of(db, "corr-broken")
    for row in rows:
        if row["event_name"] == "direct_turn_context":
            # Усечённая запись: ровно то, что даёт обрезка слоя `[:2000]`.
            await db.db.execute(
                "UPDATE mca_events SET usage_json = ? WHERE id = ?",
                ('{"flow": "direct", "l1": {"action": "rep', row["id"]))
        if row["event_name"] == "reply_search_evidence":
            await db.db.execute(
                "UPDATE mca_events SET source_ref_json = ? WHERE id = ?",
                ('{"search_intent": "required", "source_links": [{"id"',
                 row["id"]))
        if row["event_name"] == "direct_turn_selection":
            await db.db.execute(
                "UPDATE mca_events SET usage_json = ? WHERE id = ?",
                ("", row["id"]))
    await db.db.commit()

    async with await _make_client(monkeypatch) as client:
        resp = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-broken")
        assert resp.status_code == 200, resp.text
        body = resp.json()

    assert body["available"] is True
    # Контекст разобран как «нет данных»: ни выдуманного flow, ни нулей.
    assert body["context"]["flow"] == ""
    assert body["context"]["l1"] == {}
    assert body["source"]["message_id"] is None
    assert body["clock"]["stages"] is None
    # Секция выбора есть (событие есть), но поля — null, не 0.
    assert body["stages"]["selection"] is True
    assert body["selection"]["counts"] is None
    assert body["selection"]["budget"] is None
    assert body["selection"]["blocks"] is None
    assert body["selection"]["policy_version"] is None
    # Битый `source_ref_json` → ни счётчиков, ни ссылок.
    assert body["search"]["source_count"] is None
    assert body["search"]["source_ids"] is None
    assert body["search"]["links"] is None
    assert body["search"]["required"] is None


# ── 4. Переплетённые ходы и чужой чат ───────────────────────────────────────


@pytest.mark.asyncio
async def test_interleaved_turns_do_not_mix_details(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-A")
    _emit_chain("corr-B")
    _emit_selection("corr-A", payload=_selection_payload(
        source_ids=("msg:A1",)))
    _emit_selection("corr-B", payload=_selection_payload(
        source_ids=("msg:B1",)))
    _emit_search("corr-A", links=_search_links("a"))
    _emit_search("corr-B", links=_search_links("b"))
    # Деталь ТОГО ЖЕ trace_id, но ДРУГОГО чата — не приклеивается.
    _emit_selection("corr-A", chat_id=OTHER_CHAT,
                    payload=_selection_payload(source_ids=("msg:X1",)))
    _emit_search("corr-A", chat_id=OTHER_CHAT, links=_search_links("x"))
    # Деталь БЕЗ якорной цепочки не создаёт «ход» (иначе появился бы фантом).
    _emit_selection("corr-orphan", payload=_selection_payload(
        source_ids=("msg:O1",)))
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        body_a = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-A")
                  ).json()
        body_b = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-B")
                  ).json()
        orphan = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-orphan")
                  ).json()

    assert body_a["selection"]["blocks"][0]["source_ids"] == ["msg:A1"]
    assert body_b["selection"]["blocks"][0]["source_ids"] == ["msg:B1"]
    assert body_a["search"]["source_ids"] == ["web:a1", "web:a2"]
    assert body_b["search"]["source_ids"] == ["web:b1", "web:b2"]
    assert body_a["search"]["links"][0]["source_url"] == \
        "https://example.test/a1"
    # Чужой чат не породил ни смешивания, ни собственного хода; сирота
    # (деталь без якоря) тоже не стала ходом.
    assert len(body_a["turns"]) == 2
    assert orphan["available"] is False
    assert orphan["reason"] == "trace_not_found"


# ── 5. Повтор положительного факта не дублируется ──────────────────────────


@pytest.mark.asyncio
async def test_duplicate_positive_events_collapse(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-dup")
    # Один и тот же снимок выбора записан дважды (fallback/повторная проекция);
    # внутри блока тот же id цитаты приходит дважды — положительный факт один.
    duplicated = _selection_payload(source_ids=("msg:1", "msg:1", "msg:2"))
    _emit_selection("corr-dup", payload=duplicated)
    _emit_selection("corr-dup", payload=duplicated)
    # Тот же поиск дважды: одинаковые источники/ссылки.
    _emit_search("corr-dup")
    _emit_search("corr-dup")
    # То же правило стиля дважды.
    _emit_style("corr-dup")
    _emit_style("corr-dup")
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        body = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-dup")
                ).json()

    # Списки — без повторов, счётчик источников честный (не удвоен).
    assert body["selection"]["blocks"][0]["source_ids"] == ["msg:1", "msg:2"]
    assert body["search"]["source_ids"] == ["web:a1", "web:a2"]
    assert body["search"]["source_count"] == 2
    assert len(body["search"]["links"]) == 2
    assert [r["rule_id"] for r in body["style"]["rules"]] == ["no_cliche"]
    assert len(body["selection"]["self_outputs"]) == 1
    assert len(body["selection"]["dropped"]) == 1


# ── 6. include_text: право на чат, хранилище, чужой чат ────────────────────


@pytest.mark.asyncio
async def test_include_text_permission_and_chat_scope(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    # Одинаковый tg id в ДВУХ чатах: отдаться должен только свой.
    await db.save_smart_message(
        user_id=10, chat_id=CHAT_ID, text=SOURCE_TEXT,
        reply_to_id=REPLY_PARENT_TG_ID, timestamp=1_700_000_100,
        media_type="text", author_name="Вася", message_id=SOURCE_TG_ID)
    await db.save_smart_message(
        user_id=10, chat_id=OTHER_CHAT, text=FOREIGN_TEXT,
        reply_to_id=None, timestamp=1_700_000_100, media_type="text",
        author_name="Чужой", message_id=SOURCE_TG_ID)
    await db.save_smart_message(
        user_id=11, chat_id=CHAT_ID, text=REPLY_PARENT_TEXT, reply_to_id=None,
        timestamp=1_700_000_000, media_type="text", author_name="Петя",
        message_id=REPLY_PARENT_TG_ID)
    await db.record_bot_output(chat_id=CHAT_ID, tg_message_id=OWN_OUTPUT_TG_ID,
                               sent_at=1_700_000_050,
                               content_text=OWN_OUTPUT_TEXT)
    await db.record_bot_output(chat_id=OTHER_CHAT,
                               tg_message_id=OWN_OUTPUT_TG_ID,
                               sent_at=1_700_000_050,
                               content_text="чужая реплика")
    _emit_full_turn("corr-text")
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        # Без параметра текст не отдаётся вовсе (обратная совместимость).
        plain = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-text")
                 ).json()
        assert "text" not in plain["source"]

        allowed = await _get(
            client, f"chat_id={CHAT_ID}&trace_id=corr-text&include_text=1")
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()

        denied = await _get(
            client,
            f"chat_id={CHAT_ID}&trace_id=corr-text&include_text=1",
            user_id=STRANGER_ID)
        assert denied.status_code == 403

    assert body["source"]["text"] == SOURCE_TEXT
    assert body["source"]["truncated"] is False
    assert body["source"]["reply_parent"]["message_id"] == REPLY_PARENT_TG_ID
    assert body["source"]["reply_parent"]["text"] == REPLY_PARENT_TEXT
    assert body["selection"]["self_outputs"][0]["text"] == OWN_OUTPUT_TEXT
    # Строка другого чата не вернулась (ни как текст хода, ни как своя).
    assert FOREIGN_TEXT not in json.dumps(body, ensure_ascii=False)
    assert "чужая реплика" not in json.dumps(body, ensure_ascii=False)


@pytest.mark.asyncio
async def test_text_read_boundary_denies_without_chat_access(tmp_path):
    """Предикат стоит НА ГРАНИЦЕ чтения текста: без права на чат — 403 и ни
    одного чтения (вид ответа не меняется)."""
    from fastapi import HTTPException

    from services import roles
    from web.api import routes as routes_mod

    db = await _make_db(tmp_path)
    ctx = await roles.access_for(STRANGER_ID, CHAT_ID, cache=None)
    assert ctx.is_global_admin is False
    view = {"source": {"message_id": SOURCE_TG_ID,
                       "reply_to_id": REPLY_PARENT_TG_ID},
            "selection": {"self_outputs": [
                {"tg_message_id": OWN_OUTPUT_TG_ID, "source_id": None}]}}
    with pytest.raises(HTTPException) as exc:
        await routes_mod._turn_attach_text(db, CHAT_ID, view, ctx=ctx)
    assert exc.value.status_code == 403
    assert "text" not in view["source"]
    assert "text" not in view["selection"]["self_outputs"][0]


@pytest.mark.asyncio
async def test_include_text_truncates_long_text(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    long_text = "я" * 1000
    await db.save_smart_message(
        user_id=10, chat_id=CHAT_ID, text=long_text,
        reply_to_id=None, timestamp=1_700_000_100, media_type="text",
        author_name="Вася", message_id=SOURCE_TG_ID)
    _emit_chain("corr-long", reply_to_message_id=None)
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        body = (await _get(
            client,
            f"chat_id={CHAT_ID}&trace_id=corr-long&include_text=1")).json()

    assert len(body["source"]["text"]) == 600
    assert body["source"]["truncated"] is True
    # Родителя ответа нет — секция не выдумывается.
    assert "reply_parent" not in body["source"]
