"""ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 §2 (P0-2) — «История версий» промптов.

Регрессия реального продового HTTP 500 (01.11.2026) и контракт честной
истории:

  1. список ревизий на PG-семантике (``list_revisions`` НЕ отдаёт тела,
     длина приходит отдельным полем) не роняет запрос — продовый 500 был
     ``AttributeError: 'coroutine' object has no attribute 'body'`` в
     ``_revision_chars`` (недостающий ``await``), который не ловился, потому
     что тестовый ``MemoryPromptJournal`` отдавал тело в списке;
  2. сбой чтения журнала НЕ маскируется пустым списком: сервис поднимает
     ``JournalUnavailable``, HTTP-слой отдаёт 503 с человеческой причиной;
  3. события включения имеют дату (``prompt_activations.created_at``),
     строка ревизии несёт свой scope/chat — активация аудируема;
  4. откат/возврат вперёд не удаляют прошлые версии;
  5. рестарт без новой заводской метки не переписывает ручную правку
     ``prompts.summary_cover_style``;
  6. сохранение другого промпта не пишет в ``prompts.summary_cover_style``.

TEST-LIFECYCLE: CONTRACT owner=ASAP-SUMMARY-COVER-INTEGRITY-01 (P0-2)
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from services import prompt_factory as pf
from services import prompt_registry as prompt_reg
from services import prompt_release_policy as prp
from tests.test_evol016_prompt_activation import (
    PG_DSN_ENV,
    FakeCache,
    _PG_POLICY_SCHEMA,
    _pg_dsn,
    _pg_dsn_targets_project_db,
)
from tests.test_webapp_api import ADMIN_ID, _FakeConn, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

BLOCK = "factcheck.base.single"
PG_KEY = "prompts.factcheck_system_prompt"
COVER_BLOCK = "summary.cover.style"
COVER_KEY = "prompts.summary_cover_style"
COVER_FACTORY = prompt_reg.factory_text(COVER_BLOCK)
COVER_MANUAL = ("comic-book style, bold ink outlines, halftone dots, "
                "dramatic diagonal composition")


def _run(coro):
    return asyncio.run(coro)


class PgShapedJournal(prp.MemoryPromptJournal):
    """Журнал с ПОВЕДЕНИЕМ настоящего PG-стора.

    ``PgPromptJournal.list_revisions`` не возвращает тела (``body=""``) и
    отдаёт длину отдельным полем (``length(body) AS char_count``). Именно на
    этом расхождении продовый API падал с HTTP 500, а memory-стор оставался
    зелёным — поэтому здесь повторяется форма PG-строк.
    """

    async def list_revisions(self, block_id, chat_id=None, *,
                             include_retired=True, scope="global"):
        rows = await super().list_revisions(
            block_id, chat_id, include_retired=include_retired, scope=scope)
        for row in rows:
            row.chars = len(row.body or "")
            row.body = ""
        return rows


class BrokenJournal(prp.MemoryPromptJournal):
    """Стор, у которого чтение журнала падает (PG недоступен/схема)."""

    async def ensure_journal(self) -> bool:
        raise RuntimeError("pg connection lost")


def _rev(revision_id, body, *, origin="manual", scope="global", chat_id=None,
         retired=False, schema_compat="", factory_revision="", reason="",
         actor=""):
    return prp.RevisionRow(
        revision_id=revision_id, block_id=BLOCK, scope=scope, origin=origin,
        content_sha12=prompt_reg.sha12(body), body=body, pg_key=PG_KEY,
        chat_id=chat_id, factory_revision=factory_revision,
        schema_compat=schema_compat, actor=actor, reason=reason,
        retired=retired)


def _seed(store) -> None:
    _run(store.insert_revision(_rev(
        "rev-factory-a", "FACTORY A\n", origin="factory",
        factory_revision="fac-a")))
    _run(store.insert_revision(_rev(
        "rev-legacy", "OLD UNKNOWN TEXT\n", origin="legacy",
        reason="legacy_import")))
    _run(store.insert_revision(_rev(
        "rev-manual-m", "MANUAL M\n", actor=str(ADMIN_ID), reason="owner_edit")))
    _run(store.insert_activation(prp.ActivationRow(
        block_id=BLOCK, scope="global", kind="manual_edit",
        outcome="applied", revision_id="rev-manual-m", actor=str(ADMIN_ID),
        detail_code="owner_edit")))


@pytest.fixture(autouse=True)
def _reset_policy_state():
    yield
    prompt_reg.set_release_policy_active(False)
    prompt_reg.set_retired_blocks(())
    pf._HISTORY_FROZEN = False
    prompt_reg.reset_cache()


@pytest.fixture
def journal():
    store = PgShapedJournal()
    _seed(store)
    return store


def _client(monkeypatch, store, settings_rows=None):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache: store)
    conn = _FakeConn(
        settings_rows=list(settings_rows or [
            {"key": PG_KEY, "value": "MANUAL M\n", "category": "prompts",
             "updated_at": "2026-10-30T00:00:00+00:00"},
            {"key": COVER_KEY, "value": COVER_MANUAL, "category": "prompts",
             "updated_at": "2026-10-30T00:00:00+00:00"},
        ]),
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
        ],
        admin_rows=[
            {"telegram_id": ADMIN_ID, "role_name": "admin",
             "added_by": None, "created_at": "2026-10-30T00:00:00+00:00"},
        ],
    )
    from services.config_cache import ConfigCache
    cache = ConfigCache(pg=_FakePg(conn), retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    with TestClient(app) as tc:
        tc.cache = cache
        tc.journal = store
        tc.conn = conn
        yield tc


@pytest.fixture
def client(monkeypatch, journal):
    yield from _client(monkeypatch, journal)


# ── 1. Продовый HTTP 500: PG-форма списка ревизий ───────────────────────────

def test_versions_ok_on_pg_shaped_journal(client):
    """HTTP 500 «История версий» не воспроизводится на PG-форме строк."""
    resp = client.get(f"/api/prompts/{PG_KEY}/versions", headers=_hdr())
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    revisions = payload["revisions"]
    assert [r["revision_id"] for r in revisions] == [
        "rev-factory-a", "rev-legacy", "rev-manual-m"]
    by_id = {r["revision_id"]: r for r in revisions}
    # Длина текста пришла из стора (body в списке нет) — не 0 и не падение.
    assert by_id["rev-factory-a"]["chars"] == len("FACTORY A\n")
    assert by_id["rev-legacy"]["chars"] == len("OLD UNKNOWN TEXT\n")
    assert by_id["rev-manual-m"]["chars"] == len("MANUAL M\n")
    # Тела по-прежнему не отдаются списком.
    raw = json.dumps(payload)
    assert "MANUAL M" not in raw
    assert by_id["rev-legacy"]["scope"] == "global"
    assert by_id["rev-legacy"]["chat_id"] is None
    assert payload["active"]["revision_id"] == "rev-manual-m"
    assert payload["journal_available"] is True


def test_list_versions_service_on_pg_shape_keeps_origin_scope(journal):
    """Сервисный уровень: legacy/manual/factory + дата/scope/автор видны."""
    view = _run(prp.list_versions(BLOCK, store=journal, actor="owner"))
    rows = {r["revision_id"]: r for r in view["revisions"]}
    assert rows["rev-manual-m"]["origin"] == "manual"
    assert rows["rev-factory-a"]["origin"] == "factory"
    assert rows["rev-legacy"]["origin"] == "legacy"
    assert rows["rev-legacy"]["actor"] == ""
    assert rows["rev-manual-m"]["actor"] == str(ADMIN_ID)
    assert all(r["created_at"] for r in view["revisions"])
    assert view["activations"][0]["created_at"]


# ── 2. Честный отказ вместо пустого списка ──────────────────────────────────

def test_versions_503_when_journal_is_missing(monkeypatch):
    """Нет журнала/PG → 503, а не `200: []`."""
    for tc in _client(monkeypatch, None):
        resp = tc.get(f"/api/prompts/{PG_KEY}/versions", headers=_hdr())
        assert resp.status_code == 503, resp.text
        assert "журнал версий недоступен" in resp.json()["detail"]
        assert "revisions" not in resp.json()


def test_versions_503_on_journal_read_error(monkeypatch):
    """Сбой чтения журнала не превращается в «история пуста»."""
    broken = BrokenJournal()
    _seed(broken)
    for tc in _client(monkeypatch, broken):
        resp = tc.get(f"/api/prompts/{PG_KEY}/versions", headers=_hdr())
        assert resp.status_code == 503, resp.text
        assert "revisions" not in resp.json()


def test_list_versions_raises_journal_unavailable(journal):
    broken = BrokenJournal()
    _seed(broken)
    with pytest.raises(prp.JournalUnavailable):
        _run(prp.list_versions(BLOCK, store=broken, actor="owner"))


# ── 3. Аудит активаций: дата события и адресат версии ───────────────────────

def test_activation_events_carry_time(client):
    payload = client.get(f"/api/prompts/{PG_KEY}/versions",
                         headers=_hdr()).json()
    events = payload["activations"]
    assert events and events[0]["kind"] == "manual_edit"
    assert events[0]["created_at"]
    assert payload["activation_time_available"] is True
    # Время события не выдумано: это ISO-подобная метка, не «сейчас — 0».
    assert events[0]["created_at"][:2] == "20"


# ── 4. Откат/возврат вперёд не стирают прошлые версии ──────────────────────

def test_rollback_and_forward_keep_previous_versions(client):
    before = set(client.journal.revisions)
    back = client.post(f"/api/prompts/{PG_KEY}/activate",
                       json={"revision_id": "rev-factory-a"}, headers=_hdr())
    assert back.status_code == 200, back.text
    assert back.json()["applied"] is True
    assert back.json()["activation_kind"] == "manual_rollback"
    listed = client.get(f"/api/prompts/{PG_KEY}/versions",
                        headers=_hdr()).json()
    assert listed["active"]["revision_id"] == "rev-factory-a"
    assert {r["revision_id"] for r in listed["revisions"]} == before

    fwd = client.post(f"/api/prompts/{PG_KEY}/activate",
                      json={"revision_id": "rev-manual-m"}, headers=_hdr())
    assert fwd.status_code == 200, fwd.text
    assert fwd.json()["activation_kind"] == "manual_forward"
    listed = client.get(f"/api/prompts/{PG_KEY}/versions",
                        headers=_hdr()).json()
    assert listed["active"]["revision_id"] == "rev-manual-m"
    assert {r["revision_id"] for r in listed["revisions"]} == before
    kinds = [e["kind"] for e in listed["activations"]]
    assert "manual_rollback" in kinds and "manual_forward" in kinds


# ── 5. Рестарт без новой заводской метки: cover-prompt не перезаписан ──────

def test_restart_keeps_manual_cover_style():
    """``prompts.summary_cover_style``: cutover → ручная правка → рестарт."""
    cache = FakeCache({COVER_KEY: COVER_FACTORY})
    store = prp.MemoryPromptJournal()
    cutover = _run(prp.apply_release(
        cache, release_id=prp.CUTOVER_RELEASE_ID, store=store,
        blocks=[COVER_BLOCK]))
    assert cutover["applied"] is True
    assert cache.get(COVER_KEY) == COVER_FACTORY

    edited = _run(prp.write_versioned_value(
        COVER_BLOCK, COVER_MANUAL, cache=cache, store=store,
        actor=str(ADMIN_ID), reason="owner_edit"))
    assert edited["applied"] is True
    assert cache.get(COVER_KEY) == COVER_MANUAL
    revisions_before = set(store.revisions)

    # Тот же заводской релиз при следующем старте (restart/redeploy).
    restart = _run(prp.apply_release(
        cache, release_id=prp.CUTOVER_RELEASE_ID, store=store,
        blocks=[COVER_BLOCK]))
    assert restart["changed"] == 0, "рестарт что-то активировал"
    assert [r.outcome for r in restart["results"]] == ["skipped_same"]
    assert [r.detail_code for r in restart["results"]] == [
        "restart_same_revision"]
    assert cache.get(COVER_KEY) == COVER_MANUAL, "рестарт переписал ручную правку"
    assert set(store.revisions) == revisions_before, "рестарт добавил ревизию"

    view = _run(prp.list_versions(COVER_BLOCK, store=store, actor="owner"))
    assert view["active"]["revision_id"] == edited["revision_id"]
    origins = {r["origin"] for r in view["revisions"]}
    assert {"factory", "manual"} <= origins


# ── 6. Правка другого промпта не пишет в cover style ───────────────────────

def test_editing_other_prompt_does_not_write_cover_style(client):
    cover_before = {rid for rid, row in client.journal.revisions.items()
                    if row.block_id == COVER_BLOCK}
    new_text = "НОВАЯ ПРАВКА ДРУГОГО ПРОМПТА\n"
    resp = client.post("/api/config",
                       json={"items": [{"key": PG_KEY, "value": new_text}]},
                       headers=_hdr())
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == [PG_KEY]
    assert [s["key"] for s in resp.json()["prompt_snapshots"]] == [PG_KEY]

    # Ни один upsert не адресован cover-ключу.
    written_keys = [args[0] for sql, args in client.conn.queries
                    if "bot_settings" in sql and args]
    assert COVER_KEY not in written_keys
    # И в журнале не появилось ревизий cover-блока.
    cover_after = {rid for rid, row in client.journal.revisions.items()
                   if row.block_id == COVER_BLOCK}
    assert cover_after == cover_before
    assert client.cache.get(COVER_KEY) == COVER_MANUAL


# ── 7. Живой PostgreSQL: SQL-часть (length(body)) и форма PG-строк ─────────

@pytest.mark.asyncio
@pytest.mark.skipif(not _pg_dsn(),
                    reason=f"{PG_DSN_ENV} не задан — живой PostgreSQL "
                           "недоступен (skip, не подмена двойником)")
@pytest.mark.skipif(
    bool(_pg_dsn()) and _pg_dsn_targets_project_db(_pg_dsn()),
    reason=f"{PG_DSN_ENV} указывает на прод-базу `adminbot` — тест пишет в "
           "отдельную схему, прод не трогаем; укажите тестовую БД")
async def test_history_on_live_postgres_has_chars_and_dates():
    """Реальный PostgreSQL: ``length(body) AS char_count`` и дата активации.

    Двойники не проверяют SQL, поэтому единственный список ревизий, который
    отдаёт длину без тела, проверяется здесь (гейт ``ADMINBOT_TEST_PG_DSN``).
    """
    asyncpg = pytest.importorskip("asyncpg")
    import uuid

    dsn = _pg_dsn()
    schema = f"asap_p0_history_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(dsn)
    ddl_conn = None
    pool = None
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}"')
        # DDL журнала и активного слоя — в своей схеме (search_path), иначе
        # CREATE INDEX без префикса ушёл бы в public.
        ddl_conn = await asyncpg.connect(
            dsn, server_settings={"search_path": schema})
        for ddl in _PG_POLICY_SCHEMA + tuple(prp.JOURNAL_DDL):
            await ddl_conn.execute(ddl)
        await ddl_conn.close()
        ddl_conn = None
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=2,
            server_settings={"search_path": schema})
        store = prp.PgPromptJournal(pool)
        await store.ensure_journal()
        bodies = {
            "rev-live-legacy": ("импортированный старый текст\n", "legacy"),
            "rev-live-manual": ("ручная правка владельца\n", "manual"),
        }
        for rev_id, (body, origin) in bodies.items():
            await store.insert_revision(prp.RevisionRow(
                revision_id=rev_id, block_id=BLOCK, scope="global",
                origin=origin, content_sha12=prompt_reg.sha12(body),
                body=body, pg_key=PG_KEY, reason="legacy_import"
                if origin == "legacy" else "owner_edit"))
        await store.insert_activation(prp.ActivationRow(
            block_id=BLOCK, scope="global", kind="manual_edit",
            outcome="applied", revision_id="rev-live-manual",
            actor=str(ADMIN_ID), detail_code="owner_edit"))

        view = await prp.list_versions(BLOCK, store=store, actor="owner")
        by_id = {r["revision_id"]: r for r in view["revisions"]}
        assert by_id["rev-live-legacy"]["chars"] == len(bodies[
            "rev-live-legacy"][0])
        assert by_id["rev-live-manual"]["chars"] == len(bodies[
            "rev-live-manual"][0])
        assert all(r["created_at"] for r in view["revisions"])
        assert view["active"]["revision_id"] == "rev-live-manual"
        events = view["activations"]
        assert events and events[0]["created_at"], "нет времени активации"
    finally:
        if ddl_conn is not None:
            await ddl_conn.close()
        if pool is not None:
            await pool.close()
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await admin.close()
