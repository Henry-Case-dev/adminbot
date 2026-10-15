"""ASAP 8 F7 — «Истории чата» humanize: display_names в web/api/stories.py.

Контракт (architecture.md §7 F7; ТЗ §14/§28.17; audit-modules-infra §7):
  * feed/card — СЕРВЕРНЫЙ резолв display_names [{id, name, ambiguous}]
    канон-ID → имя: имена активных участников чата (`get_active_participants`,
    окно 30 дней / cap 200 — тот же источник, что
    `web/api/chat_lore.py::_participant_names` и oversight) + AliasResolver
    (`limits.summary_aliases`). JS-дубликата резолва нет.
  * честный fallback без выдуманных имён: неизвестный числовой участник →
    «Участник N»; не-числовой (историческое канон-имя из LLM-пути mca-05) —
    наружу как есть.
  * два участника с одинаковым display name НЕ склеиваются: обе записи
    остаются, обе помечены `ambiguous` (различие по `id` — под Developer
    details); raw IDs из ответа не удаляются (служебные поля: фильтр,
    merge/split), но главный UI их не показывает — структурные пины шаблона.
  * человеческое объяснение §14 в витрине (НЕ Telegram Stories, НЕ Summary),
    витрина «Всего / Новых за 24ч / Последняя сборка / Backfill».

R17: имена участников — не секреты; message-контент наружу не отдаётся.

TEST-LIFECYCLE: CONTRACT owner=asap8/F7
"""
import asyncio
import json
import time
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import mca_events
from services import mca_gates
from services import lore_runtime
from services import summary_aliases
from services.config_cache import ConfigCache
from services.database import (
    DatabaseService,
    EPISODE_UNKNOWN_OUTCOME,
)
from services.mca_episodes import (
    EpisodeRepository,
    EpisodeService,
)
from services.permissions import Permissions
from web.api import deps as deps_mod
from web.api import stories as stories_mod
from web.api.stories import stories_router

CHAT = -100500
CHAT2 = -100501
T_2022 = 1650000000
_NOW = 1790000000
TEST_TOKEN = "123456:TEST_F7_TOKEN"
ADMIN_ID = 111222

UID_ANYA = 111111
UID_BORIS = 222222
UID_UNKNOWN = 333333
UID_ANJA2 = 444444
UID_ANJA3 = 555555
UID_ALIAS = 666666


# ── инфраструктура (прецедент tests/test_mca12_stories_round1046.py) ─────────

async def _db(tmp_path, name="f7.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _seed_author(db, uid: int, chat_id: int, name: str) -> None:
    """author_name в smart_messages (источник get_active_participants);
    timestamp в 30-дневном окне от реального now()."""
    await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name) VALUES (?, ?, ?, NULL, ?, 'text', ?)",
        (uid, chat_id, "сообщение", int(time.time()) - 60, name))
    await db.db.commit()


async def _seed_story(repo: EpisodeRepository, *, chat_id: int,
                      parts_a: list, parts_b: list) -> str:
    """Два эпизода с confirmed-связью → одна история; участники истории —
    объединение участников эпизодов (mca-05 assemble)."""
    db = repo._db
    ep_ids = []
    for i, (title, parts) in enumerate((("Эпизод А", parts_a),
                                        ("Эпизод Б", parts_b))):
        eid = await repo.insert_episode(
            chat_id=chat_id, title=title, summary=f"суть {i + 1}",
            participants=parts,
            claims=[{"text": "утверждение", "refs": []}],
            event_start=T_2022 + i * 100, event_end=T_2022 + i * 100 + 50,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[],
            message_keys=[f"{chat_id}:tg:{100 + i}"],
            seg_key=f"s-{chat_id}-f7-{i}", extraction_version="x", now=_NOW)
        ep_ids.append(eid)
    await db.db.execute(
        "INSERT OR IGNORE INTO mca_story_continuations "
        "(from_episode_id, to_episode_id, status, created_at) "
        "VALUES (?, ?, 'confirmed', ?)", (ep_ids[0], ep_ids[1], _NOW))
    await db.db.commit()
    svc = EpisodeService(db, llm=None, now=_NOW)
    await svc.assemble_stories(chat_id, _NOW)
    await mca_events.flush_events(db)
    stories = await repo.list_stories(chat_id, limit=10)
    assert len(stories) == 1
    return stories[0]["story_id"]


def make_init_data(token: str, user_id: int) -> str:
    import hashlib
    import hmac
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A",
                            "username": "a"}, separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, v)
                           for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


def _fake_cache(*, admin: bool = True) -> ConfigCache:
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    cache._roles = {
        "admin": {"permissions": {"wildcard": True},
                  "is_custom": False, "role_type": "global_admin"},
    }
    cache._permissions = {
        "admin": Permissions.from_dict({"wildcard": True})}
    cache._admins = {ADMIN_ID: "admin"} if admin else {}
    cache._pg_available = True
    cache._initialized = True
    cache._pg = None
    return cache


def _client(db, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.state.cache = _fake_cache(admin=admin)
    app.include_router(stories_router, prefix="/api")
    return TestClient(app)


def _hdr(user=ADMIN_ID, chat: int | None = CHAT) -> dict:
    h = {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user)}
    if chat is not None:
        h["X-Chat-Id"] = str(chat)
    return h


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


@pytest.fixture(autouse=True)
def _clean_events():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


# ═══ Серверный резолв: лента ═════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_feed_display_names_resolved(tmp_path):
    """F7-контракт ленты: display_names [{id, name, ambiguous}], порядок =
    participants, имена из author_name чата; raw participants остаются
    (служебное поле/фильтр)."""
    db = await _db(tmp_path)
    try:
        await _seed_author(db, UID_ANYA, CHAT, "Аня")
        await _seed_author(db, UID_BORIS, CHAT, "Борис")
        repo = EpisodeRepository(db)
        sid = await _seed_story(repo, chat_id=CHAT,
                                parts_a=[str(UID_ANYA), str(UID_BORIS)],
                                parts_b=[str(UID_BORIS)])
        feed = await stories_mod.web_stories.stories_feed(db, CHAT)
        payload = stories_mod._annotate_feed(
            feed, *await stories_mod._names_ctx(db, CHAT))
        assert payload["state"] == "ok"
        discovered = [e for e in payload["events"]
                      if e["event"] == "story_discovered"]
        assert discovered and discovered[0]["story_id"] == sid
        ev = discovered[0]
        entries = ev["display_names"]
        assert [e["id"] for e in entries] == ev["participants"], \
            "порядок display_names = participants"
        by_id = {e["id"]: e for e in entries}
        assert by_id[str(UID_ANYA)]["name"] == "Аня"
        assert by_id[str(UID_BORIS)]["name"] == "Борис"
        assert all(e["ambiguous"] is False for e in entries)
        assert set(entries[0].keys()) == {"id", "name", "ambiguous"}
        # raw IDs не удалены (служебное поле: фильтр/Developer details)
        assert str(UID_ANYA) in ev["participants"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_display_names_fallback_unknown_and_ambiguous(tmp_path):
    """Честный fallback: неизвестный числовой участник → «Участник N»
    (не выдуманное имя); два участника с одинаковым именем НЕ склеиваются —
    обе записи остаются, обе ambiguous, id различны."""
    db = await _db(tmp_path)
    try:
        await _seed_author(db, UID_ANJA2, CHAT, "Аня")
        await _seed_author(db, UID_ANJA3, CHAT, "Аня")
        repo = EpisodeRepository(db)
        await _seed_story(repo, chat_id=CHAT,
                          parts_a=[str(UID_UNKNOWN)],
                          parts_b=[str(UID_UNKNOWN)])
        feed = await stories_mod.web_stories.stories_feed(db, CHAT)
        payload = stories_mod._annotate_feed(
            feed, *await stories_mod._names_ctx(db, CHAT))
        ev = next(e for e in payload["events"]
                  if e["event"] == "story_discovered")
        entries = ev["display_names"]
        assert entries == [{"id": str(UID_UNKNOWN),
                            "name": f"Участник {UID_UNKNOWN}",
                            "ambiguous": False}]
        # неоднозначность: одна история, два разных участника с одним именем
        await _seed_author(db, UID_ANJA2, CHAT2, "Аня")
        await _seed_author(db, UID_ANJA3, CHAT2, "Аня")
        await _seed_story(repo, chat_id=CHAT2,
                          parts_a=[str(UID_ANJA2), str(UID_ANJA3)],
                          parts_b=[str(UID_ANJA3)])
        feed2 = await stories_mod.web_stories.stories_feed(db, CHAT2)
        payload2 = stories_mod._annotate_feed(
            feed2, *await stories_mod._names_ctx(db, CHAT2))
        ev2 = next(e for e in payload2["events"]
                   if e["event"] == "story_discovered")
        entries2 = ev2["display_names"]
        assert len(entries2) == 2
        assert {e["id"] for e in entries2} == {str(UID_ANJA2), str(UID_ANJA3)}
        assert all(e["name"] == "Аня" for e in entries2)
        assert all(e["ambiguous"] is True for e in entries2), \
            "одинаковое имя разных участников — честная пометка"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_display_names_alias_resolution(tmp_path, monkeypatch):
    """AliasResolver (limits.summary_aliases) применяется на Stories-пути:
    алиас канон-ID побеждает даже без author_name в 30-дневном окне."""
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        await _seed_story(repo, chat_id=CHAT,
                          parts_a=[str(UID_ALIAS)],
                          parts_b=[str(UID_ALIAS)])

        async def _fake_resolver(chat_id):
            return summary_aliases.AliasResolver(
                json.dumps({str(UID_ALIAS): "Лёха"}))

        monkeypatch.setattr(stories_mod.summary_aliases,
                            "build_alias_resolver", _fake_resolver)
        feed = await stories_mod.web_stories.stories_feed(db, CHAT)
        payload = stories_mod._annotate_feed(
            feed, *await stories_mod._names_ctx(db, CHAT))
        ev = next(e for e in payload["events"]
                  if e["event"] == "story_discovered")
        assert ev["display_names"][0]["name"] == "Лёха"
        assert ev["display_names"][0]["id"] == str(UID_ALIAS)
    finally:
        await db.close()


# ═══ Серверный резолв: карточка ══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_card_display_names_contract(tmp_path):
    """Карточка: display_names на истории и КАЖДОМ эпизоде; не-числовой
    участник (канон-имя из LLM-пути) — наружу как есть."""
    db = await _db(tmp_path)
    try:
        await _seed_author(db, UID_ANYA, CHAT, "Аня")
        repo = EpisodeRepository(db)
        sid = await _seed_story(repo, chat_id=CHAT,
                                parts_a=["Лёва", str(UID_ANYA)],
                                parts_b=[str(UID_ANYA)])
        card = await stories_mod.web_stories.story_card(db, CHAT, sid)
        payload = stories_mod._annotate_card(
            card, *await stories_mod._names_ctx(db, CHAT))
        assert payload["state"] == "ok"
        story_entries = payload["story"]["display_names"]
        by_id = {e["id"]: e for e in story_entries}
        assert by_id["Лёва"]["name"] == "Лёва"
        assert by_id[str(UID_ANYA)]["name"] == "Аня"
        assert len(payload["episodes"]) == 2
        for ep in payload["episodes"]:
            entries = ep["display_names"]
            assert [e["id"] for e in entries] == ep["participants"]
            by_ep = {e["id"]: e for e in entries}
            assert by_ep[str(UID_ANYA)]["name"] == "Аня"
            if "Лёва" in by_ep:
                assert by_ep["Лёва"]["name"] == "Лёва"
        # не-числовой участник дошёл до карточки эпизода без подмены
        assert any("Лёва" in {e["id"] for e in ep["display_names"]}
                   for ep in payload["episodes"])
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_display_names_fail_open_names_unavailable(tmp_path, monkeypatch):
    """Fail-open: чтение имён упало → пустая карта, честный «Участник N»
    (резолв не роняет ответ — precедент oversight fail-open)."""
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        await _seed_story(repo, chat_id=CHAT,
                          parts_a=[str(UID_ANYA)],
                          parts_b=[str(UID_ANYA)])

        async def _boom(*a, **kw):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(db, "get_active_participants", _boom)
        names, resolver = await stories_mod._names_ctx(db, CHAT)
        assert names == {}
        entries = stories_mod._display_entries([str(UID_ANYA)], names, resolver)
        assert entries == [{"id": str(UID_ANYA),
                            "name": f"Участник {UID_ANYA}",
                            "ambiguous": False}]
    finally:
        await db.close()


# ═══ HTTP-контракт роутера ═══════════════════════════════════════════════════

@pytest.fixture
def api_db(tmp_path):
    db = _run(_db(tmp_path, "f7api.db"))
    yield db
    _run(db.close())


def _run(coro):
    """Синхронно выполнить async-функцию (sync-тесты/TestClient; прецедент
    test_mca12_stories_round1046._run)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patch_lore(monkeypatch, db):
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)


def test_api_feed_and_card_carry_display_names(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    repo = EpisodeRepository(api_db)
    _run(_seed_author(api_db, UID_ANYA, CHAT, "Аня"))
    sid = _run(_seed_story(
        repo, chat_id=CHAT,
        parts_a=[str(UID_ANYA), str(UID_UNKNOWN)],
        parts_b=[str(UID_ANYA)]))
    client = _client(api_db)
    body = client.get("/api/stories/feed", headers=_hdr()).json()
    assert body["state"] == "ok"
    ev = next(e for e in body["events"]
              if e["event"] == "story_discovered")
    names = {e["id"]: e["name"] for e in ev["display_names"]}
    assert names[str(UID_ANYA)] == "Аня"
    assert names[str(UID_UNKNOWN)] == f"Участник {UID_UNKNOWN}"
    card = client.get(f"/api/stories/{sid}", headers=_hdr()).json()
    assert card["state"] == "ok"
    assert {e["id"] for e in card["story"]["display_names"]} \
        == set(card["story"]["participants"])
    assert all("display_names" in ep for ep in card["episodes"])


def test_api_no_chat_and_disabled_not_annotated(api_db, monkeypatch):
    """Честные состояния не обогащаются: no_chat/disabled возвращаются как
    есть (без display_names-надписей поверх disabled)."""
    _patch_lore(monkeypatch, api_db)
    client = _client(api_db)
    body = client.get("/api/stories/feed", headers=_hdr(chat=None)).json()
    assert body["state"] == "no_chat" and body["events"] == []
    monkeypatch.setattr(mca_gates, "stories_vitrina_enabled",
                        lambda: False)
    body = client.get("/api/stories/feed", headers=_hdr()).json()
    assert body["enabled"] is False and body["state"] == "disabled"


# ═══ UI-контракт: человеческий главный UI, raw IDs — под Developer details ═══

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_ui_human_explanation_and_vitrina_labels():
    """§14: человеческое объяснение (не Telegram Stories, не Summary) и
    витрина «Всего / Новых за 24ч / Последняя сборка / Backfill»."""
    html = _read("web/index.html")
    assert 'data-stories-explain' in html
    assert "объединённые в эпизоды" in html
    assert "Это не Telegram Stories и не Summary" in html
    assert "Всего: {{ storiesSummary.counters.total }}" in html
    assert "Новых за 24ч: {{ storiesSummary.counters.new_window }}" in html
    assert "Последняя сборка:" in html
    assert "Backfill: {{ storiesBackfillLabel(storiesSummary.progress) }}" in html
    js = _read("web/app.js")
    for fn in ("storiesParticipantsLabel", "storiesSourceCount",
               "storiesUsageLabel", "storiesBuildLabel",
               "storiesBackfillLabel", "storiesEpisodeIds",
               "storiesClaimRefs"):
        assert fn + ":" in js, f"helper {fn} есть"


def test_ui_no_numeric_id_dump_in_main_ui():
    """§28.17: raw IDs/episode_id/ключи-источники НЕ показываются в главном
    UI — только под Developer details (collapsed).
    re-pin ASAP 8 v6.3 B08 (REQ-B08, Wave 3a): карточки переведены на
    display_title/primary_participants (+others_count) и раскрываемую
    хронологию; «Участники (ID):» из главного вида убраны вовсе (строже
    старого контракта), data-stories-dev/claims-refs инварианты сохранены."""
    html = _read("web/index.html")
    # лента: участники больше не raw join
    assert "участники: {{ ev.participants.join" not in html
    # участники — через display_names (ключевые + «ещё N»), не raw-список
    assert html.count("storiesParticipantsLabel(") >= 3, \
        "v6.3 B08: участники рендерятся storiesParticipantsLabel"
    assert "display_names" in html
    # raw-ID блок «Участники (ID):» — ровно один, внутри collapsed
    # Developer details (главный вид — display_names без ID)
    assert html.count("Участники (ID):") == 1, \
        "v6.3 B08: raw IDs — только в collapsed dev details"
    dev_idx = html.find("Участники (ID):")
    dev_block = html.rfind("data-stories-dev", 0, dev_idx)
    assert dev_block > 0, "raw IDs — внутри блока data-stories-dev"
    # split-чекбоксы без episode_id-префикса
    assert "ep.episode_id.slice(0, 8)" not in html
    # утверждения: raw-ключи источников ушли из главного вида в dev details
    assert "(источники: {{ c.refs.join" not in html
    assert "storiesClaimRefs(storiesManageCard)" in html
    # обе карточки имеют collapsed Developer details
    assert html.count("data-stories-dev") == 2
    for idx in (m.start() for m in
                __import__("re").finditer("data-stories-dev", html)):
        details_idx = html.rfind("<details", 0, idx)
        summary_idx = html.find("<summary", idx)
        assert details_idx > 0 and details_idx < idx < summary_idx, \
            "Developer details — <details> (collapsed по умолчанию)"
