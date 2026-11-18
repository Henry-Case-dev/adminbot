"""VMQ-TIME-09 — backend/API «покрытие памяти по годам» для ОДНОГО прогона.

Проверяется наблюдаемый контракт (brief
`plans/features/vmq-onto-01/evidence/time09-ui-brief-2026-11-19.md` §2/§5.2)
на РЕАЛЬНЫХ событиях `mca_events` и РЕАЛЬНЫХ producer'ах:

  * `RetrievalRequest.trace_id` аддитивен; без него событие байт-паритетно
    (ключа `trace_id` в событии нет);
  * `mca07_retrieval` durable-событие несёт `trace_id` того же хода, что
    `direct_turn_selection` (связка Writer-блоков и retrieval по одному id);
  * `_rag_retrieve`/`_build_old_episodes` передают trace в `RetrievalRequest`;
    `_build_rag_block` кладёт его в событие period-selection;
  * `GET /api/direct/turn-diagnostics` сохраняет `selection.blocks[].years`
    и `selection.memory_period` (схема, без лишних ключей);
  * `retrieval[]` — bounded, отсортирован по ts, БЕЗ `period_selection`;
  * измеренный `{}` отличается от отсутствия данных
    (`years_present`/`excluded_present`); нули не выдумываются;
  * R17: в ответе только коды/числа, свободный текст события не проходит;
  * 403 без доступа к чату; 200 — global admin;
  * `stages.retrieval` присутствует; старые ключи не переименованы;
  * truncated selection не подставляет `{}` вместо отсутствующих лет.

Запуск: pytest tests/test_vmq_time09_turn_coverage.py -q
"""
import hashlib
import hmac
import json
import time
import types
import urllib.parse

import httpx
import pytest

from services import direct_chat_service as dcs
from services import hot_config as hot
from services import lore_runtime
from services import mca_events
from services import mca_retrieval_context as rc
from services import memory_diagnostics
from services import turn_trace
from services.config_cache import ConfigCache
from services.database import DatabaseService

CHAT_ID = -1009876543210
OTHER_CHAT = -1001111111111
ADMIN_ID = 5885953495
STRANGER_ID = 777001
TEST_TOKEN = "123456:TEST_TOKEN_FOR_API_TESTS"
MARKER = "СЕКРЕТ_ТЕКСТ_ФАКТА_НЕ_ДОЛЖЕН_УТЕЧЬ"


# ── тест-клиент (реальный ASGI) ─────────────────────────────────────────────


class _FakeConn:
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
    db = DatabaseService(str(tmp_path / "time09.db"))
    await db.initialize()
    return db


@pytest.fixture(autouse=True)
def _clean_state():
    turn_trace.reset()
    mca_events.reset_pending()
    yield
    turn_trace.reset()
    mca_events.reset_pending()


# ── реальные producer'ы/эмиттеры ───────────────────────────────────────────


def _emit_chain(trace_id, *, chat_id=CHAT_ID):
    trace = turn_trace.begin(
        trace_id, chat_id=chat_id, trigger="botword", flow="direct",
        source_message_id=501, source_author_id=10)
    turn_trace.note_l1(trace_id, action="reply", response_act="answer",
                       model="test-model")
    turn_trace.emit_context(trace)
    turn_trace.note_l2_request(trace_id, provider="test-provider",
                               model="test-model", max_output_tokens=1000,
                               blocks=["l1:context", "l2:writer"])
    turn_trace.note_l2_completion(trace_id, raw_text="draft", final_text="draft",
                                  stats={"semantic_rewrite_count": 0})
    turn_trace.emit_writer(trace)
    turn_trace.note_delivery(trace_id, outcome="success", channel="reply",
                             tg_message_ids=[42])


def _selection_payload(*, truncated=False, with_rag=True,
                       memory_period=None):
    blocks = [
        {"kind": "global_tail", "role": "p1", "rendered": True,
         "source_ids": ["msg:1"], "tokens": 300,
         "years": {"2026": 3}},
    ]
    if with_rag:
        blocks.append(
            {"kind": "rag", "role": "p2", "rendered": True,
             "source_ids": ["fact:1", "fact:2"], "tokens": 800,
             "years": {"2023": 2, "2026": 7}})
        blocks.append(
            {"kind": "episode", "role": "p2", "rendered": True,
             "source_ids": ["episode:1"], "tokens": 200,
             "years": {"2023": 1}})
    payload = {
        "counts": {"available_messages": 40, "included_messages": 12,
                   "window_messages": 25},
        "blocks": blocks,
        "dropped": [{"reason_code": "over_budget", "kind": "rag",
                     "count": 3}],
        "policy_version": "alloc_v3",
        "memory_period": memory_period if memory_period is not None else {
            "policy": "auto",
            "replace_allowed": 1,
            "period_skipped": "auto_no_replace",
            "intent": {"kind": "historical", "source": "memory_scope",
                       "years": [2023]},
            "intent_source": "memory_scope",
            "pool": 12, "kept": 3, "historical_quota": 2,
            "multi_year_quota": 1, "dropped_subject": 1,
            "dropped_budget": 2, "dropped_status": 1,
            "dropped_out_of_target_year": 0, "dropped_unknown_year": 0,
            "pool_status": {"confirmed": 2, "archived": 1},
            "pool_expired": 0, "age_policy": "expiry",
            "vector_leg": "knn", "vector_rows": 12,
        },
    }
    if truncated:
        payload["truncated"] = True
    return payload


def _emit_selection(trace_id, *, chat_id=CHAT_ID, payload=None):
    turn_trace.note_selection(
        trace_id, chat_id=chat_id,
        payload=_selection_payload() if payload is None else payload)


async def _insert_event(db, *, trace_id, chat_id=CHAT_ID, ts=None,
                        event_name="mca07_retrieval", outcome="silent",
                        reason_code=None, usage=None):
    """Строка слоя `mca_events` с явным ts (только для проверки сортировки/
    защитного фильтра; продовый producer таких строк не пишет)."""
    await db.db.execute(
        "INSERT INTO mca_events (ts, level, event_name, outcome, trace_id,"
        " chat_id, component, stage, reason_code, usage_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (int(ts if ts is not None else time.time()), "INFO", event_name,
         outcome, trace_id, int(chat_id), "retrieval_context", "retrieval",
         reason_code,
         json.dumps(usage, ensure_ascii=False) if usage is not None else None))
    await db.db.commit()


async def _get(client, query, *, user_id=ADMIN_ID):
    return await client.get("/api/direct/turn-diagnostics?" + query,
                            headers=_hdr(user_id))


# ── 1. RetrievalRequest.trace_id аддитивен ─────────────────────────────────


def test_retrieval_request_trace_id_is_optional_and_additive():
    import dataclasses
    req = rc.RetrievalRequest(chat_id=CHAT_ID, query="q")
    assert req.trace_id is None, "trace_id не обязателен (паритет)"
    assert dataclasses.replace(req, trace_id="t1").trace_id == "t1"
    # Существующие поля не тронуты.
    assert req.purpose == "reply" and req.chat_id == CHAT_ID


@pytest.mark.asyncio
async def test_retrieval_event_carries_trace_id_and_parity_without_it(
        tmp_path):
    db = await _make_db(tmp_path)
    # Реальная точка emit'а: каналы пусты → silent-событие.
    request = rc.RetrievalRequest(chat_id=CHAT_ID, query="", channels=(),
                                  trace_id="trace-run-1")
    result = await rc.retrieve(db, None, request)
    assert result.reason_code == "retrieval_empty"
    parity = rc.RetrievalRequest(chat_id=OTHER_CHAT, query="", channels=())
    await rc.retrieve(db, None, parity)
    await mca_events.flush_events(db)

    traced = await mca_events.query_events(db, trace_id="trace-run-1",
                                           limit=10)
    assert [row["event_name"] for row in traced] == ["mca07_retrieval"]
    assert traced[0]["trace_id"] == "trace-run-1"
    plain = await mca_events.query_events(db, chat_id=OTHER_CHAT, limit=10)
    assert [row["event_name"] for row in plain] == ["mca07_retrieval"]
    assert not plain[0].get("trace_id"), (
        "без trace_id поле не добавляется — прежнее событие")


@pytest.mark.asyncio
async def test_rag_retrieve_passes_trace_id_to_request(monkeypatch):
    captured = {}

    async def fake_retrieve(db, memory, request):
        captured["request"] = request
        return types.SimpleNamespace(fact_rows=(), period_fill=None)

    monkeypatch.setattr(rc, "retrieve", fake_retrieve)
    await dcs.DirectChatService._rag_retrieve(
        None, None, CHAT_ID, "q", ("vector",), 5, "auto", trace_id="t-1")
    assert captured["request"].trace_id == "t-1"
    await dcs.DirectChatService._rag_retrieve(
        None, None, CHAT_ID, "q", ("vector",), 5, "auto")
    assert captured["request"].trace_id is None, "паритет без trace"


@pytest.mark.asyncio
async def test_build_old_episodes_passes_trace_id(monkeypatch):
    captured = {}

    async def fake_retrieve(db, memory, request):
        captured["request"] = request
        return types.SimpleNamespace(candidates=(), period_fill=None)

    monkeypatch.setattr(rc, "retrieve", fake_retrieve)
    service = dcs.DirectChatService.__new__(dcs.DirectChatService)
    service.db = None
    service.memory = None
    block, stats = await service._build_old_episodes(
        CHAT_ID, "что было в 2023?", [], {}, trace_id="t-ep")
    assert block == ""
    assert captured["request"].trace_id == "t-ep"
    assert captured["request"].mode == "history"


@pytest.mark.asyncio
async def test_build_rag_block_period_event_carries_trace(
        monkeypatch, tmp_path):
    class _FakeHot:
        def get(self, key, default=None):
            return {"flags.chat_rag_rerank_enabled": False,
                    "memory.nostalgia_layer_a_enabled": False}.get(
                        key, hot.get(key, default))

    monkeypatch.setattr(hot, "_cache", _FakeHot())
    ts = 1672574400            # 2023-01-01 UTC
    row = {
        "id": 1, "item_id": "fact:1", "fact": "старый факт про переезд",
        "origin": "chat_history", "rag_ts": ts, "created_at": ts,
        "target_user": "aleksey", "weight": 0.5, "status": "confirmed",
        "last_confirmed_at": ts, "message_timestamp": ts, "kind": "fact",
        "importance": 5, "forward_from": "", "expires_at": None,
        "chat_id": CHAT_ID, "belief_meta": None,
        "tg_message_id": 1001,
    }
    service = dcs.DirectChatService(memory=object(), db=None, llm=None,
                                    aliases=None)

    async def fake_unified(*_args, **_kwargs):
        service._rag_period_stats = {
            "policy": "auto", "replace_allowed": 1, "period_skipped": "",
            "period_intent": {"kind": "historical", "years": [],
                              "source": "memory_scope"},
            "intent_source": "memory_scope", "selection_rows": 1,
            "selection_kept": 1,
        }
        return [row]

    monkeypatch.setattr(service, "_rag_unified_rows", fake_unified)
    calls = []
    monkeypatch.setattr(rc, "emit_stage_event",
                        lambda *a, **k: calls.append((a, k)))

    class _Msg:
        text = "что было в 2023 году?"

    block, _hint = await service._build_rag_block(
        CHAT_ID, _Msg(), "", trace_id="t-rag")
    assert "старый факт" in block
    period = [call for call in calls
              if call[0][:2] == ("retrieval", "selection")
              and call[1].get("reason_code") == "period_selection"]
    assert period, f"period-selection событие не отправлено: {calls}"
    assert period[0][1].get("trace_id") == "t-rag", (
        "событие отбора обязано принадлежать тому же ходу")


# ── 2. API: years/memory_period/retrieval[] ────────────────────────────────


@pytest.mark.asyncio
async def test_api_preserves_writer_years_and_memory_period(tmp_path,
                                                           monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-years")
    _emit_selection("corr-years")
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        resp = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-years")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    selection = body["selection"]
    blocks = {item["kind"]: item for item in selection["blocks"]}
    assert blocks["rag"]["rendered"] is True
    assert blocks["rag"]["years"] == {"2023": 2, "2026": 7}
    assert blocks["rag"]["years_present"] is True
    assert blocks["episode"]["years"] == {"2023": 1}
    period = selection["memory_period"]
    assert period["policy"] == "auto"
    assert period["period_skipped"] == "auto_no_replace"
    assert period["intent"]["kind"] == "historical"
    assert period["intent"]["years"] == [2023]
    assert period["pool"] == 12 and period["kept"] == 3
    assert period["dropped_status"] == 1 and period["dropped_budget"] == 2
    assert period["pool_status"] == {"confirmed": 2, "archived": 1}
    # `stages.retrieval` существует всегда (старая трасса — False).
    assert body["stages"]["retrieval"] is False


@pytest.mark.asyncio
async def test_api_retrieval_is_bounded_sorted_and_excludes_period_selection(
        tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-runs")
    _emit_selection("corr-runs", payload=_selection_payload(truncated=False))
    # 8 основных вызовов + защитный period_selection (в проде не durable).
    for index in range(8):
        await _insert_event(
            db, trace_id="corr-runs", ts=1_700_000_100 + index,
            reason_code="retrieval_empty",
            usage={"policy": "auto",
                   "years": {"2023": index} if index else {},
                   "excluded": {"budget": index} if index else {}})
    await _insert_event(
        db, trace_id="corr-runs", ts=1_700_000_200,
        reason_code="period_selection",
        usage={"years": {"2025": 99},
               "excluded": {"budget": 99}})
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        body = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-runs")
                ).json()
    runs = body["retrieval"]
    assert body["stages"]["retrieval"] is True
    assert isinstance(runs, list) and len(runs) == 6, (
        "bounded: не больше 6 вызовов на ход")
    assert [row["ts"] for row in runs] == sorted(row["ts"] for row in runs), (
        "вызовы отсортированы по времени")
    assert all(row["reason_code"] != "period_selection" for row in runs), (
        "period_selection не создаёт вторую строку: его годы уже в "
        "selection.memory_period")
    assert runs[0]["years"] == {} and runs[0]["years_present"] is True
    assert runs[0]["excluded"] == {} and runs[0]["excluded_present"] is True
    # Закрытый набор исключений — пять ключей (отсутствующие = 0).
    assert set(runs[1]["excluded"]) == set(
        memory_diagnostics._RETRIEVAL_EXCLUSION_KEYS)
    assert runs[1]["excluded"]["budget"] == 1
    assert runs[1]["excluded"]["status"] == 0
    assert runs[1]["policy"] == "auto"
    assert runs[1]["period"] is False


@pytest.mark.asyncio
async def test_api_retrieval_distinguishes_measured_empty_from_missing(
        tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-state")
    # Событие без usage_json — «не зафиксировано», а не измеренный ноль.
    await _insert_event(db, trace_id="corr-state", ts=1_700_000_300,
                        reason_code="retrieval_empty", usage=None)
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        body = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-state")
                ).json()
    run = body["retrieval"][0]
    assert run["years"] is None and run["years_present"] is False
    assert run["excluded"] is None and run["excluded_present"] is False
    assert run["period"] is False, "period — признак period_fill, не догадка"


@pytest.mark.asyncio
async def test_api_r17_projection_rejects_free_text(tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-r17")
    _emit_selection("corr-r17")
    await _insert_event(
        db, trace_id="corr-r17", ts=1_700_000_400,
        reason_code="episodes_used",
        usage={"policy": "auto", "years": {"2023": 2},
               "excluded": {"relevance": 1},
               "period_fill": {"vector_leg": "knn"},
               "fact_text": MARKER, "note": MARKER})
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        resp = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-r17")
    assert resp.status_code == 200, resp.text
    dump = resp.text
    assert MARKER not in dump, "R17: свободный текст события не проходит"
    run = resp.json()["retrieval"][0]
    assert set(run) <= {"ts", "outcome", "reason_code", "policy", "period",
                        "years", "years_present", "excluded",
                        "excluded_present"}
    assert run["period"] is True


@pytest.mark.asyncio
async def test_api_truncated_selection_does_not_substitute_years(
        tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-trunc")
    # RAG-блок мог не попасть в слой из-за лимита payload: его лет нет,
    # подставлять `{}` (измеренный ноль) нельзя.
    _emit_selection("corr-trunc", payload=_selection_payload(
        truncated=True, with_rag=False, memory_period={}))
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        body = (await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-trunc")
                ).json()
    selection = body["selection"]
    assert selection["truncated"] is True
    kinds = [item["kind"] for item in (selection["blocks"] or [])]
    assert "rag" not in kinds
    for item in (selection["blocks"] or []):
        if item["kind"] == "global_tail":
            assert item["years"] == {"2026": 3}
    assert selection.get("memory_period") is None, (
        "пустой memory_period — нет данных, а не нули")


@pytest.mark.asyncio
async def test_api_403_for_foreign_chat_and_200_for_admin(
        tmp_path, monkeypatch):
    db = await _make_db(tmp_path)
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)
    _emit_chain("corr-rbac")
    await mca_events.flush_events(db)

    async with await _make_client(monkeypatch) as client:
        forbidden = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-rbac",
                               user_id=STRANGER_ID)
        allowed = await _get(client, f"chat_id={CHAT_ID}&trace_id=corr-rbac")
    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["available"] is True


def test_exclusion_keys_are_single_source():
    allowed = set(memory_diagnostics._RETRIEVAL_EXCLUSION_KEYS)
    assert allowed == {"policy_operative", "status", "expired",
                       "relevance", "budget"}
    # Значения — закрытый набор; UI подписывает ровно эти пять.
    from web.api import routes
    assert tuple(routes._RETRIEVAL_EXCLUSION_KEYS) == tuple(
        memory_diagnostics._RETRIEVAL_EXCLUSION_KEYS)
