"""EVOL-021 (Wave 4 UI) — смысловые эпизоды: HTTP-слой и витрина.

TEST-LIFECYCLE: CONTRACT owner=EVOL-021

Сервисный контракт (реальные таблицы эпизодов) — в
`tests/test_evol021_episode_semantics.py`. Здесь проверяется то, что видит
админка и что нельзя сломать на HTTP-слое:
  * лента/группа восстановления/карточка живут в КОНКРЕТНОМ чате: без чата —
    честное «выберите чат», чужой чат — 403 (сервис не вызывается), эпизод
    чужого чата — 404 без раскрытия существования;
  * карточка отдаётся РОВНО по id (не «общий каталог»);
  * витрина: компактная лента, свёрнутая группа «Требуют восстановления»,
    «Технические детали» по требованию, «Открыть в памяти» — адресная ссылка
    `#/memory?episode=<id>`, старая таблица сохранена под «Расширенный поиск»,
    пустое состояние с датой последней сборки.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import episode_diagnostics as ed
from tests.test_webapp_api import ADMIN_ID, USER_ID, _FakeConn, _FakePg, _hdr
from web.api import routes as routes_mod
from web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
CHAT_A = -100111
CHAT_B = -100222
LOCAL_ADMIN_ID = 424242424


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        "web.api.deps.settings",
        type("S", (), {"API_TOKEN": "123456:TEST_TOKEN_FOR_API_TESTS"})())
    conn = _FakeConn(
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
        yield tc


def _feed_payload(chat_id=CHAT_A) -> dict:
    return {
        "scope": f"chat:{chat_id}", "chat_id": chat_id,
        "generated_at": 1_800_000_000, "state": "ok",
        "items": [{
            "episode_id": "ep-1", "chat_id": chat_id,
            "title": "Спор про деплой",
            "title_source": "pipeline",
            "what_happened": "Обсуждали порядок выкладки и отката",
            "what_happened_source": "summary",
            "event_period": {"start": 1_799_990_000, "end": 1_799_992_000,
                             "known": True},
            "discovered_at": 1_799_993_000, "processed_at": 1_799_993_500,
            "discovery_kind": "new_event_today", "discovery_label": "новое",
            "participants": {"primary": ["1", "2"], "others_count": 1,
                             "count": 3},
            "linked_messages": {"count": 3, "known": True, "capped": False,
                                "label": "исходных сообщений: 3"},
            "claims_count": 1, "completeness": "ready",
            "completeness_label": "полный",
            "verification": {"status": "verified", "state": "open",
                             "source": "story", "label": "История проверена"},
            "story": {"linked": True, "story_id": "st-1", "count": 1,
                      "title": "Спор про деплой",
                      "excluded_from_retrieval": False},
            "retrievable": True, "needs_recovery": False, "recovery": None,
        }],
        "total_ready": 1, "total_episodes": 2,
        "requires_recovery": {
            "count": 1,
            "by_reason": [{"reason": "no_source_messages",
                           "reason_label": "исходные сообщения не сохранены",
                           "count": 1}],
            "note": "Незавершённые эпизоды не выдаются за готовые истории",
        },
        "last_build": {"last_build_at": 1_799_994_000,
                       "last_build_state": "success",
                       "backfill_state": "idle", "backfill_active": False},
    }


def _card_payload(episode_id="ep-1", chat_id=CHAT_A) -> dict:
    item = dict(_feed_payload(chat_id)["items"][0])
    item["episode_id"] = episode_id
    item["generated_at"] = 1_800_000_000
    return item


def test_missing_auth_is_401(client):
    assert client.get("/api/episodes/feed").status_code == 401


def test_no_chat_is_honest(client):
    body = client.get("/api/episodes/feed", headers=_hdr()).json()
    assert body["state"] == "no_chat"
    assert body["items"] == []
    recovery = client.get("/api/episodes/recovery", headers=_hdr()).json()
    assert recovery["state"] == "no_chat"
    assert recovery["count"] == 0
    # Карточка без чата — 422 (не «общий каталог»).
    assert client.get("/api/episodes/ep-1", headers=_hdr()).status_code == 422


def test_foreign_chat_is_403_and_service_not_called(client, monkeypatch):
    called = []

    async def _feed(db, chat_id, *, limit=50):
        called.append(("feed", chat_id))
        return _feed_payload(chat_id)

    async def _recovery(db, chat_id, *, limit=50):
        called.append(("recovery", chat_id))
        return {"count": 0, "items": [], "by_reason": []}

    async def _card(db, chat_id, episode_id):
        called.append(("card", chat_id, episode_id))
        return _card_payload(episode_id, chat_id)

    monkeypatch.setattr(ed, "episode_feed", _feed)
    monkeypatch.setattr(ed, "recovery_group", _recovery)
    monkeypatch.setattr(ed, "episode_card", _card)
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())

    async def access_for(telegram_id, chat_id=None, cache=None):
        from services.permissions import Permissions
        from services.roles import AccessCtx
        if telegram_id == ADMIN_ID:
            return AccessCtx(
                role_global="global_admin", role_chat=None,
                perms_global=Permissions.from_dict({"wildcard": True}),
                perms_chat=Permissions.from_dict({}),
                is_global_admin=True, is_local_admin=False, rank=4)
        return AccessCtx(
            role_global="user", role_chat=None,
            perms_global=Permissions.from_dict({}),
            perms_chat=Permissions.from_dict({}),
            is_global_admin=False, is_local_admin=False, rank=1)

    monkeypatch.setattr(routes_mod.roles_srv, "access_for", access_for)
    headers = {**_hdr(USER_ID), "X-Chat-Id": str(CHAT_B)}
    assert client.get("/api/episodes/feed", headers=headers).status_code == 403
    assert client.get("/api/episodes/recovery",
                      headers=headers).status_code == 403
    assert client.get("/api/episodes/ep-1", headers=headers).status_code == 403
    assert called == []          # сервис не тронут


def test_own_chat_returns_feed_and_recovery(client, monkeypatch):
    seen = {}

    async def _feed(db, chat_id, *, limit=50):
        seen["feed"] = (chat_id, limit)
        return _feed_payload(chat_id)

    async def _recovery(db, chat_id, *, limit=50):
        seen["recovery"] = (chat_id, limit)
        return {"state": "ok", "group": "requires_recovery",
                "group_label": "Требуют восстановления", "count": 1,
                "items": [{"episode_id": "ep-2", "chat_id": chat_id,
                           "reason": "no_source_messages",
                           "reason_label": "исходные сообщения не сохранены",
                           "status": "unrecoverable",
                           "event_period": {"start": None, "end": None},
                           "linked_messages": {"count": 0}}],
                "by_reason": [{"reason": "no_source_messages",
                               "reason_label": "исходные сообщения не сохранены",
                               "status": "unrecoverable", "count": 1}],
                "truncated": False, "note": "архив не удаляется"}

    monkeypatch.setattr(ed, "episode_feed", _feed)
    monkeypatch.setattr(ed, "recovery_group", _recovery)
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())

    headers = {**_hdr(), "X-Chat-Id": str(CHAT_A)}
    body = client.get("/api/episodes/feed?limit=20", headers=headers).json()
    assert seen["feed"] == (CHAT_A, 20)
    assert body["items"][0]["episode_id"] == "ep-1"
    assert body["items"][0]["completeness"] == "ready"
    assert body["requires_recovery"]["count"] == 1
    assert body["last_build"]["last_build_at"] == 1_799_994_000

    recovery = client.get("/api/episodes/recovery", headers=headers).json()
    assert seen["recovery"] == (CHAT_A, 50)
    assert recovery["by_reason"][0]["reason"] == "no_source_messages"
    assert recovery["items"][0]["status"] == "unrecoverable"


def test_card_is_addressed_and_foreign_is_404(client, monkeypatch):
    async def _card(db, chat_id, episode_id):
        if episode_id != "ep-1":
            return None
        return _card_payload(episode_id, chat_id)

    monkeypatch.setattr(ed, "episode_card", _card)
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: object())
    headers = {**_hdr(), "X-Chat-Id": str(CHAT_A)}
    own = client.get("/api/episodes/ep-1", headers=headers)
    assert own.status_code == 200, own.text
    assert own.json()["episode_id"] == "ep-1"
    assert own.json()["what_happened"].startswith("Обсуждали порядок")
    assert client.get("/api/episodes/ep-2", headers=headers).status_code == 404


def test_unavailable_db_is_honest(client, monkeypatch):
    from services import lore_runtime
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: None)
    headers = {**_hdr(), "X-Chat-Id": str(CHAT_A)}
    body = client.get("/api/episodes/feed", headers=headers).json()
    assert body["state"] == "unavailable"
    assert client.get("/api/episodes/ep-1", headers=headers).status_code == 503


def test_ui_feed_recovery_and_addressed_link():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    block = html.split("data-episode-feed", 1)[1]
    block = block.split("data-stories-advanced", 1)[0]
    assert "data-episode-feed-items" in block
    assert "data-episode-id" in block
    assert "data-episode-feed-empty" in block
    assert "Последняя сборка" in block
    assert "data-episode-recovery-group" in block
    assert "data-episode-recovery-toggle" in block
    assert "Требуют восстановления" in block
    assert "data-episode-card" in block
    assert "data-episode-tech-toggle" in block
    assert "data-episode-open-in-memory" in block
    assert "Технические детали" in block
    # Старая техническая таблица сохранена под «Расширенный поиск».
    assert "data-stories-advanced" in html
    assert "Расширенный поиск" in html
    assert "data-stories-table" in html
    assert "data-stories-filters" in html


def test_ui_deep_link_targets_exact_episode():
    js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "openEpisodeInMemory: function" in js
    assert "'#/memory?episode=' + encodeURIComponent(episodeId)" in js
    assert "episodesApplyDeepLink: function" in js
    assert "/[?&]episode=([^&]+)/" in js
    # Карточка запрашивается по id, а не «каталогом».
    assert "'/api/episodes/'" in js
    assert "encodeURIComponent(episodeId)" in js
    # Группа восстановления по умолчанию свёрнута.
    assert "episodeRecoveryOpen: false" in js
    # Лента грузится при входе в «Память».
    assert "this.loadEpisodeFeed();" in js
