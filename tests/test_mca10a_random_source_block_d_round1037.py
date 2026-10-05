"""MCA-10a `mca-10a-random-source-anu` — focused-тесты блока D (T-4980).

Покрытие (MCA10-R4, spec D9/§10, A35):
  * состав блока «Источник случайности» (selected/effective, ANU-состояние,
    запас, последняя партия, счётчики draws, fallback, последние решения);
  * читающий контракт: открытие/повтор НЕ делают QRNG/LLM-вызовов (A35);
  * K1 OFF → honest `disabled/not_run` без данных (сервис не вызывается);
  * при фактическом PRNG quantum-статус НЕ выдаётся (quantum_active=false +
    точный блокер);
  * R17: key_fingerprint/сырой ключ в блок не попадают; журнал — whitelist;
  * права/chat scope: журнал draw — по чату; без чата — только global admin.
"""
import asyncio
import json

import pytest

from services import mca_gates
from services import mca_random_source as mrs
from services.database import DatabaseService
from services.status_service import StatusService


def _draw_record(draw_id: str, *, chat_id=None, source="pseudorandom",
                 created_at=1000, candidates=("a", "b"), purpose="p"):
    return {
        "draw_id": draw_id, "created_at": created_at, "chat_id": chat_id,
        "purpose": purpose, "source": source,
        "provider": "python-random" if source == "pseudorandom"
        else mrs.PROVIDER_ANU,
        "batch_id": None, "value": 1, "candidates_json": json.dumps(candidates),
        "pool_size": 2, "probability": None, "policy_version": "mca10a-v1",
        "selected_id": "b", "fallback_reason": None,
        "config_version": "2.58.57", "secret_extra": "must-not-leak",
    }


class _NeverFetch:
    """Любой внешний вызов = провал читающего контракта (A35)."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("внешний вызов из читающего блока запрещён")


@pytest.fixture
def svc(monkeypatch, tmp_path):
    async def _setup():
        db = DatabaseService(str(tmp_path / "mca10a_d.db"))
        await db.initialize()
        service = mrs.RandomSourceService(db, auto_refill=False)
        service.set_client(mrs.AnuClient(http_get=_NeverFetch(),
                                         min_interval=0.0))
        await service._store.journal_draw(_draw_record("d1", chat_id=1))
        await service._store.journal_draw(_draw_record("d2", chat_id=2))
        monkeypatch.setattr(mrs, "_service", service)
        return service

    service = asyncio.run(_setup())
    yield service
    mrs.reset_service()
    try:
        asyncio.run(service.db.close())
    except Exception:
        pass


async def _block(svc, *, chat_id=None, is_global_admin=False):
    return await StatusService().random_source_snapshot(
        chat_id=chat_id, is_global_admin=is_global_admin)


def test_block_composition_and_honest_quantum_flag(svc, monkeypatch):
    monkeypatch.setattr(
        svc, "resolve_effective",
        lambda chat_id=None: _async_result(("pseudorandom",
                                            "provider_unavailable")))
    block = asyncio.run(_block(svc, chat_id=1))
    assert block["enabled"] is True
    assert block["available"] is True
    assert block["selected_source"] == "quantum"
    assert block["effective_source"] == "pseudorandom"
    assert block["quantum_active"] is False        # quantum-статус не выдаётся
    assert block["blocker"] == "provider_unavailable"
    assert block["anu_state"] in (
        "provider_unconfigured", "unverified", "disabled", "degraded",
        "quota_exhausted", "active")
    assert block["reserve_remaining"] == 0
    assert block["buffer_max"] == 2048
    assert block["low_watermark"] == 256
    assert block["draws"] == {"quantum": 0, "pseudorandom": 2}
    assert block["policy_version"] == mrs.POLICY_VERSION
    assert block["recent_draws_scope"] == "chat"
    assert [d["draw_id"] for d in block["recent_draws"]] == ["d1"]
    draw = block["recent_draws"][0]
    assert draw["candidates"] == ["a", "b"]
    assert "secret_extra" not in draw
    # R17: отпечаток ключа/сырой ключ наружу не отдаются.
    blob = json.dumps(block, ensure_ascii=False, default=str)
    assert "key_fingerprint" not in blob
    assert "anu-draft" not in blob


def test_quantum_effective_shows_quantum(svc, monkeypatch):
    monkeypatch.setattr(
        svc, "resolve_effective",
        lambda chat_id=None: _async_result(("quantum", None)))
    block = asyncio.run(_block(svc, chat_id=1))
    assert block["quantum_active"] is True
    assert block["blocker"] is None


def test_k2_off_pseudorandom_with_disabled_blocker(svc, monkeypatch):
    # K2 OFF → ANU-запросов нет; блок честно показывает pseudorandom+disabled.
    monkeypatch.setattr(mca_gates, "random_quantum_enabled", lambda: False)
    block = asyncio.run(_block(svc, chat_id=1))
    assert block["quantum_active"] is False
    assert block["effective_source"] == "pseudorandom"
    assert block["blocker"] == "disabled"
    assert block["anu_state"] == "disabled"


def test_read_only_no_external_calls_on_open_and_repeat(svc, monkeypatch):
    fetch = _NeverFetch()
    svc.set_client(mrs.AnuClient(http_get=fetch, min_interval=0.0))

    async def _boom(*args, **kwargs):
        raise AssertionError("write/активация из читающего блока запрещены")

    monkeypatch.setattr(svc, "activate", _boom)
    monkeypatch.setattr(svc, "test_connection", _boom)
    monkeypatch.setattr(svc, "refill_if_needed", _boom)
    first = asyncio.run(_block(svc, chat_id=1))
    second = asyncio.run(_block(svc, chat_id=1))
    assert first == second
    assert fetch.calls == 0


def test_k1_off_honest_disabled_without_service(monkeypatch):
    monkeypatch.setattr(mca_gates, "random_source_enabled", lambda: False)

    def _boom(*args, **kwargs):
        raise AssertionError("K1 OFF: сервис не должен вызываться")

    monkeypatch.setattr(mrs, "get_service", _boom)
    block = asyncio.run(StatusService().random_source_snapshot(chat_id=1))
    assert block["enabled"] is False
    assert block["state"] == "disabled"
    assert block["quantum_active"] is False
    assert "recent_draws" not in block


def test_recent_draws_scope_rights(svc):
    # Чат: только свои draw. Без чата: non-admin — restricted/пусто,
    # global admin — глобальный журнал.
    chat_block = asyncio.run(_block(svc, chat_id=2))
    assert [d["draw_id"] for d in chat_block["recent_draws"]] == ["d2"]
    restricted = asyncio.run(_block(svc, chat_id=None, is_global_admin=False))
    assert restricted["recent_draws"] == []
    assert restricted["recent_draws_scope"] == "restricted"
    global_block = asyncio.run(_block(svc, chat_id=None, is_global_admin=True))
    assert {d["draw_id"] for d in global_block["recent_draws"]} == {"d1", "d2"}
    assert global_block["recent_draws_scope"] == "global"


def test_chat_scope_rbac_gate(svc):
    # RBAC роута: нет доступа к чату → журнал не отдаётся (restricted),
    # но состояние источника остаётся видимым (read-only статус).
    block = asyncio.run(StatusService().random_source_snapshot(
        chat_id=2, chat_scope_allowed=False))
    assert block["recent_draws"] == []
    assert block["recent_draws_scope"] == "restricted"
    assert block["enabled"] is True


def test_public_draw_whitelist_and_candidates_cap(svc):
    many = [f"c{i}" for i in range(50)]
    row = _draw_record("d9", chat_id=3, candidates=many)
    row["unknown_field"] = "x"
    public = StatusService._public_draw(row)
    assert len(public["candidates"]) == StatusService._RECENT_CANDIDATES_CAP
    assert "unknown_field" not in public
    assert set(public) == set(StatusService._DRAW_PUBLIC_FIELDS) | {
        "candidates"}


def test_build_snapshot_contains_random_block(svc, monkeypatch):
    async def _no_health(self, module_id, base_url, key, model="", kind="chat"):
        return {"ok": False, "status": "not_configured", "http_status": None,
                "latency_ms": None, "checked_at": None}

    async def _no_uptime(self, pg):
        return []

    monkeypatch.setattr(StatusService, "_check_health", _no_health)
    monkeypatch.setattr(StatusService, "fetch_uptime_rows", _no_uptime)
    snapshot = asyncio.run(StatusService().build_snapshot(cache=None))
    assert "random" in snapshot
    assert snapshot["random"]["enabled"] is True
    assert "key_fingerprint" not in json.dumps(snapshot["random"])


async def _async_result(value):
    return value
