"""EVOL-017 — история версий промптов в админке.

HTTP-слой над уже принятым ``prompt_release_policy``: список, текст, diff,
активация, каталог. Права: без сессии 401, без права 403, чужой чат не
отдаёт текст. Откат и возврат вперёд не стирают журнал. Снятая и
несовместимая ревизии читаются, но не включаются.

TEST-LIFECYCLE: CONTRACT owner=EVOL-017
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import prompt_registry as prompt_reg
from services.permissions import Permissions
from services.prompt_release_policy import (
    ActivationRow,
    MemoryPromptJournal,
    RevisionRow,
)
from services.roles import AccessCtx
from tests.test_webapp_api import (
    ADMIN_ID,
    USER_ID,
    _FakeConn,
    _FakePg,
    _hdr,
)
from web.api import routes as routes_mod
from web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
BLOCK = "factcheck.base.single"
PG_KEY = "prompts.factcheck_system_prompt"
CHAT_A = -100111
CHAT_B = -100222
CHAT_ADMIN = 515151515


def _run(coro):
    return asyncio.run(coro)


def _rev(revision_id, body, *, origin="manual", scope="global",
         chat_id=None, retired=False, schema_compat="",
         factory_revision="", reason="", actor=""):
    return RevisionRow(
        revision_id=revision_id, block_id=BLOCK, scope=scope, origin=origin,
        content_sha12=revision_id[:12].ljust(12, "0"), body=body,
        pg_key=PG_KEY, chat_id=chat_id, factory_revision=factory_revision,
        schema_compat=schema_compat, actor=actor, reason=reason,
        retired=retired)


async def _seed(store: MemoryPromptJournal) -> None:
    await store.insert_revision(_rev(
        "rev-factory-a", "FACTORY A\n", origin="factory",
        factory_revision="fac-a"))
    await store.insert_revision(_rev(
        "rev-manual-m", "MANUAL M\n", origin="manual", actor="5885953495",
        reason="owner_edit"))
    await store.insert_revision(_rev(
        "rev-factory-b", "FACTORY B\n", origin="factory",
        factory_revision="fac-b"))
    await store.insert_revision(_rev(
        "rev-legacy", "OLD UNKNOWN\n", origin="legacy", reason="legacy_import"))
    await store.insert_revision(_rev(
        "rev-retired", "RETIRED TEXT\n", retired=True))
    await store.insert_revision(_rev(
        "rev-incompat", "INCOMPAT TEXT\n", schema_compat="gone-v0"))
    await store.insert_revision(_rev(
        "rev-chat-a", "CHAT111 ONLY\n", scope="chat", chat_id=CHAT_A))
    await store.insert_revision(_rev(
        "rev-chat-b", "CHAT222 ONLY\n", scope="chat", chat_id=CHAT_B))
    await store.insert_activation(ActivationRow(
        block_id=BLOCK, scope="global", kind="deploy_activate",
        outcome="applied", revision_id="rev-factory-b",
        factory_revision_applied="fac-b", actor="release"))


@pytest.fixture
def journal():
    store = MemoryPromptJournal()
    _run(_seed(store))
    return store


@pytest.fixture
def client(monkeypatch, journal):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    monkeypatch.setattr(routes_mod, "_prompt_journal", lambda cache: journal)
    conn = _FakeConn(
        settings_rows=[
            {"key": PG_KEY, "value": "FACTORY B\n", "category": "prompts",
             "updated_at": "2026-10-30T00:00:00+00:00"},
        ],
        role_rows=[
            {"role_name": "admin", "permissions": {"wildcard": True},
             "is_custom": False},
            {"role_name": "user", "permissions": {}, "is_custom": False},
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
        tc.journal = journal
        yield tc


def _ids(store: MemoryPromptJournal) -> set[str]:
    return set(store.revisions)


def test_missing_auth_is_401(client):
    assert client.get(f"/api/prompts/{PG_KEY}/versions").status_code == 401
    assert client.post(f"/api/prompts/{PG_KEY}/activate",
                       json={"revision_id": "rev-manual-m"}).status_code == 401


def test_user_without_rights_is_403(client):
    headers = _hdr(USER_ID)
    assert client.get(f"/api/prompts/{PG_KEY}/versions",
                      headers=headers).status_code == 403
    assert client.get("/api/prompts/revisions/rev-manual-m/source",
                      headers=headers).status_code == 403
    assert client.get("/api/prompts/revisions/diff",
                      params={"a": "rev-factory-a", "b": "rev-manual-m"},
                      headers=headers).status_code == 403
    assert client.post(f"/api/prompts/{PG_KEY}/activate",
                       json={"revision_id": "rev-manual-m"},
                       headers=headers).status_code == 403
    assert client.get("/api/prompts/catalog", headers=headers).status_code == 403
    # Отказ до сервиса: указатель и журнал не тронуты.
    assert len(client.journal.activations) == 1


def test_versions_have_no_bodies_or_secrets(client):
    resp = client.get(f"/api/prompts/{PG_KEY}/versions", headers=_hdr())
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    raw = json.dumps(payload)
    assert "FACTORY B" not in raw
    assert "CHAT222" not in raw
    assert "api_key" not in raw
    assert "password" not in raw
    assert payload["active"]["revision_id"] == "rev-factory-b"
    assert payload["factory_revision"]
    assert "activation_time_available" in payload
    assert payload["activation_time_available"] is False
    origins = {row["origin"] for row in payload["revisions"]}
    assert {"factory", "manual", "legacy"} <= origins
    legacy = next(row for row in payload["revisions"]
                  if row["origin"] == "legacy")
    assert legacy["actor"] == ""
    assert legacy["reason"] == "legacy_import"
    assert "body" not in legacy


def test_rollback_forward_keeps_history(client):
    before = _ids(client.journal)
    back = client.post(f"/api/prompts/{PG_KEY}/activate",
                       json={"revision_id": "rev-manual-m"},
                       headers=_hdr())
    assert back.status_code == 200, back.text
    body = back.json()
    assert body["applied"] is True
    assert body["activation_kind"] == "manual_rollback"
    assert body["active_unchanged"] is False
    listed = client.get(f"/api/prompts/{PG_KEY}/versions",
                        headers=_hdr()).json()
    assert listed["active"]["revision_id"] == "rev-manual-m"
    assert before <= _ids(client.journal)

    fwd = client.post(f"/api/prompts/{PG_KEY}/activate",
                      json={"revision_id": "rev-factory-b"},
                      headers=_hdr())
    assert fwd.status_code == 200, fwd.text
    assert fwd.json()["applied"] is True
    assert fwd.json()["activation_kind"] == "manual_forward"
    listed = client.get(f"/api/prompts/{PG_KEY}/versions",
                        headers=_hdr()).json()
    assert listed["active"]["revision_id"] == "rev-factory-b"
    assert before <= _ids(client.journal)
    assert client.cache.get(PG_KEY) == "FACTORY B\n"


def test_retired_and_incompatible_are_viewable_but_blocked(client):
    active_before = client.get(f"/api/prompts/{PG_KEY}/versions",
                               headers=_hdr()).json()["active"]["revision_id"]
    for rev_id, reason in (("rev-retired", "revision_retired"),
                           ("rev-incompat", "schema_incompatible")):
        source = client.get(f"/api/prompts/revisions/{rev_id}/source",
                            headers=_hdr())
        assert source.status_code == 200, source.text
        assert source.json()["body"]
        denied = client.post(f"/api/prompts/{PG_KEY}/activate",
                             json={"revision_id": rev_id}, headers=_hdr())
        assert denied.status_code == 200, denied.text
        payload = denied.json()
        assert payload["applied"] is False
        assert payload["reason"] == reason
        assert payload["active_unchanged"] is True
        assert reason in payload["reason_text"] or payload["reason_text"]
        assert "не изменилась" in payload["reason_text"]
    active_after = client.get(f"/api/prompts/{PG_KEY}/versions",
                              headers=_hdr()).json()["active"]["revision_id"]
    assert active_after == active_before
    diff = client.get("/api/prompts/revisions/diff",
                      params={"a": "rev-retired", "b": "rev-incompat"},
                      headers=_hdr())
    assert diff.status_code == 200
    assert diff.json()["known"] is True
    assert any(line.startswith("+") or line.startswith("-")
               for line in diff.json()["diff"])


def test_chat_isolation(client, monkeypatch):
    async def access_for(telegram_id, chat_id=None, cache=None):
        if telegram_id == ADMIN_ID:
            return AccessCtx(
                role_global="global_admin", role_chat=None,
                perms_global=Permissions.from_dict({"wildcard": True}),
                perms_chat=Permissions.from_dict({}),
                is_global_admin=True, is_local_admin=False, rank=4)
        if telegram_id == CHAT_ADMIN and chat_id == CHAT_A:
            return AccessCtx(
                role_global="user", role_chat="local_admin",
                perms_global=Permissions.from_dict({}),
                perms_chat=Permissions.from_dict({"sections": ["prompts"]}),
                is_global_admin=False, is_local_admin=True, rank=3)
        return AccessCtx(
            role_global="user", role_chat=None,
            perms_global=Permissions.from_dict({}),
            perms_chat=Permissions.from_dict({}),
            is_global_admin=False, is_local_admin=False, rank=1)

    monkeypatch.setattr(routes_mod.roles_srv, "access_for", access_for)
    own = client.get("/api/prompts/revisions/rev-chat-a/source",
                     headers=_hdr(CHAT_ADMIN))
    assert own.status_code == 200, own.text
    assert own.json()["body"] == "CHAT111 ONLY\n"
    assert "CHAT222" not in own.text
    foreign = client.get("/api/prompts/revisions/rev-chat-b/source",
                         headers=_hdr(CHAT_ADMIN))
    assert foreign.status_code == 403
    assert "CHAT222" not in foreign.text
    before = len(client.journal.activations)
    denied = client.post(
        f"/api/prompts/{PG_KEY}/activate",
        json={"revision_id": "rev-chat-b"},
        headers={**_hdr(CHAT_ADMIN), "X-Chat-Id": str(CHAT_B)})
    assert denied.status_code == 403
    assert len(client.journal.activations) == before


def test_save_creates_snapshot_and_keeps_old(client):
    before = _ids(client.journal)
    text = "НОВАЯ ПРАВКА ИЗ РЕДАКТОРА\n"
    resp = client.post("/api/config",
                       json={"items": [{"key": PG_KEY, "value": text}]},
                       headers=_hdr())
    assert resp.status_code == 200, resp.text
    snaps = resp.json().get("prompt_snapshots") or []
    assert snaps and snaps[0]["key"] == PG_KEY
    assert before <= _ids(client.journal)
    assert snaps[0]["revision_id"] not in before
    listed = client.get(f"/api/prompts/{PG_KEY}/versions",
                        headers=_hdr()).json()
    ids = {row["revision_id"] for row in listed["revisions"]}
    assert "rev-manual-m" in ids
    assert snaps[0]["revision_id"] in ids


def test_catalog_lists_internal_prompts_without_bodies(client):
    resp = client.get("/api/prompts/catalog", headers=_hdr())
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["count"] == len(prompt_reg.all_blocks())
    raw = json.dumps(payload)
    assert "body" not in raw
    assert "api_key" not in raw
    families = {fam["id"] for fam in payload["families"]}
    assert "internal" in families
    code = next(block for block in prompt_reg.all_blocks() if not block.pg_key)
    view = client.get(f"/api/prompts/{code.block_id}/versions", headers=_hdr())
    assert view.status_code == 200, view.text
    assert view.json()["can_activate"] is False
    blocked = client.post(f"/api/prompts/{code.block_id}/activate",
                          json={"revision_id": "nope"}, headers=_hdr())
    assert blocked.status_code == 422


def test_editor_page_contains_history_area():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    editor = html.split("data-prompt-editor", 1)[1].split("data-prompt-meta", 1)[0]
    assert "История версий" in editor
    assert "data-prompt-history" in editor
    assert "data-prompt-history-toggle" in editor
    assert "data-prompt-catalog" in html
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "импортировано при переходе" in js
    assert "Включить сохранённую версию" in js
    assert "window.confirm" in js
    assert "Активная версия не изменилась" in js
    css = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
    assert "max-width: 420px" in css
    assert ".prompt-history" in css
