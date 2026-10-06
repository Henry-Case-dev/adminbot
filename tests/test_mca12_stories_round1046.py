"""MCA-12 `mca-12-miniapp-stories` (round 10.46, ADR-1028-21) — Builder-покрытие.

Контрактные тесты (spec §8.1, T-5170):
  * санкции §7.3/§7.5: KS 83→85 (env-only ClassVar, default ON, независимые
    оси), routes +5 в NEW `web/api/stories.py`; `web/api/routes.py` НЕ менялся
    (byte-freeze ROUTES_SHA256_F11 — hash совпадает с пином, re-pin
    верифицирован, L-F11S-1);
  * M-MCA05-2 (D16/T-5161): no-op rebuild не создаёт версию/`story_rebuilt`;
    recheck-ревизия claims/участников/дат → новая версия и карточка
    обновляется;
  * A11: событие 2022, найденное сегодня — обе даты в ленте;
  * A13: ручная правка переживает пересборку (override не затёрт), версии
    доступны; stale-мутация отклонена с текущей версией (без затирания);
    merge/split создают redirect и новую версию;
  * A25/TH-1/TH-2: cross-chat карточка → 404 без раскрытия; неавторизованная
    мутация → 403; без чата → честный no_chat; K1 OFF → честный disabled;
    K2 OFF → 409 disabled;
  * A54: курсор/дедуп ленты — догрузка без дублей/потерь;
  * TH-7: серверная валидация пагинации/фильтров (422 вне whitelist),
    LIKE-метасимволы экранированы;
  * A26 (структурная часть): вставка витрины единственная, нового маршрута
    `#/stories` нет, регистрация роутера в web/app.py, JS-тест зелёный;
  * §16.3 (T-5168): defaults JS-рендера настроек = канону Settings.

R17: в тестах числа/коды/ID, секретов нет.
"""
import asyncio
import json
import re
import time
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services import mca_events
from services import mca_gates
from services import lore_runtime
from services import web_stories
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
from web.api.stories import stories_router

CHAT = -100500
CHAT2 = -100501
T_2022 = 1650000000
_NOW = 1790000000
TEST_TOKEN = "123456:TEST_MCA12_TOKEN"
ADMIN_ID = 111222
USER_ID = 999888


# ── инфраструктура ───────────────────────────────────────────────────────────

async def _db(tmp_path, name="mca12.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _seed_linked_episodes(repo, *, chat_id=CHAT, claims_text="утверждение",
                                participant="2", start=T_2022):
    """Два эпизода с confirmed-связью → одна компонента-история."""
    ep_ids = []
    for i, name in enumerate(("a", "b")):
        eid = await repo.insert_episode(
            chat_id=chat_id, title=f"Эп{name}", summary=f"часть {name}",
            participants=[participant],
            claims=[{"text": claims_text, "refs": []}],
            event_start=start + i * 100, event_end=start + i * 100 + 50,
            outcome=EPISODE_UNKNOWN_OUTCOME, outcome_known=False,
            open_questions=[], message_keys=[f"{chat_id}:tg:{100 + i}"],
            seg_key=f"s-{chat_id}-{name}", extraction_version="x",
            now=_NOW)
        ep_ids.append(eid)
    # confirmed-continuation (без связей эпизоды — отдельные компоненты)
    db = repo._db
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
    return ep_ids, stories[0]["story_id"]


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


def _fake_cache(*, admin: bool) -> ConfigCache:
    cache = ConfigCache.__new__(ConfigCache)
    cache._settings = {}
    if admin:
        cache._roles = {
            "admin": {"permissions": {"wildcard": True},
                      "is_custom": False, "role_type": "global_admin"},
        }
        cache._permissions = {
            "admin": Permissions.from_dict({"wildcard": True})}
        cache._admins = {ADMIN_ID: "admin"}
    else:
        cache._roles = {
            "user": {"permissions": {"sections": ["memory"]},
                     "is_custom": False, "role_type": "user"},
        }
        cache._permissions = {
            "user": Permissions.from_dict({"sections": ["memory"]})}
        cache._admins = {}
    cache._pg_available = True
    cache._initialized = True
    cache._pg = None
    return cache


def _client(db, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.state.cache = _fake_cache(admin=admin)
    app.include_router(stories_router, prefix="/api")
    return TestClient(app)


def _hdr(user=ADMIN_ID):
    return {"X-Telegram-Init-Data": make_init_data(TEST_TOKEN, user)}


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))


@pytest.fixture(autouse=True)
def _clean_events():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()


# ═══ Санкции: KS +2 (83→85), env-only, default ON ════════════════════════════

def test_kill_switches_85_and_defaults():
    names = {"MCA_STORIES_VITRINA_ENABLED", "MCA_STORIES_MANAGE_ENABLED"}
    assert names <= set(mca_gates.KILL_SWITCHES)
    # отсчёт от пост-mca-20 (83) → 85
    assert len(mca_gates.KILL_SWITCHES) == 85
    for name in names:
        default, off_parity = mca_gates.KILL_SWITCHES[name]
        assert default is True
        assert isinstance(off_parity, str) and off_parity
    assert mca_gates.stories_vitrina_enabled() is True
    assert mca_gates.stories_manage_enabled() is True


def test_kill_switches_env_only_classvar_independent():
    import dataclasses
    from config.settings import Settings
    # env-only ClassVar: в dataclass-поля Settings НЕ входят (Δ каталога = 0)
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert not ({"MCA_STORIES_VITRINA_ENABLED",
                 "MCA_STORIES_MANAGE_ENABLED"} & fields)
    # default ON у свежего Settings и per-call резолв
    s = Settings()
    assert s.MCA_STORIES_VITRINA_ENABLED is True
    assert s.MCA_STORIES_MANAGE_ENABLED is True
    # оси независимы: K1 OFF не выключает K2 (и наоборот), mca-07-прецедент
    class _S:
        MCA_STORIES_VITRINA_ENABLED = False
        MCA_STORIES_MANAGE_ENABLED = True
    orig = mca_gates.settings
    try:
        mca_gates.settings = _S
        assert mca_gates.stories_vitrina_enabled() is False
        assert mca_gates.stories_manage_enabled() is True
        _S.MCA_STORIES_VITRINA_ENABLED = True
        _S.MCA_STORIES_MANAGE_ENABLED = False
        assert mca_gates.stories_vitrina_enabled() is True
        assert mca_gates.stories_manage_enabled() is False
    finally:
        mca_gates.settings = orig


def test_routes_pin_unchanged_and_router_registered():
    # routes.py НЕ менялся (D2): byte-freeze ROUTES_SHA256_F11 держится;
    # re-pin сводится к осознанной верификации hash (L-F11S-1)
    import hashlib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sha = hashlib.sha256(
        (root / "web/api/routes.py").read_bytes()).hexdigest()
    from tests.test_round1025_f8_registry import ROUTES_SHA256_F11
    assert sha == ROUTES_SHA256_F11
    # роутер +5 маршрутов зарегистрирован в web/app.py (прецедент зон)
    app_py = (root / "web/app.py").read_text(encoding="utf-8")
    assert "include_router(stories_router" in app_py
    stories_py = (root / "web/api/stories.py").read_text(encoding="utf-8")
    for route in ("/stories/summary", "/stories/feed", "/stories",
                  "/stories/{story_id}", "/stories/{story_id}/action"):
        assert f'"{route}")' in stories_py, route


# ═══ M-MCA05-2 (T-5161/D16): unchanged-детектор ══════════════════════════════

@pytest.mark.asyncio
async def test_mmca05_2_noop_rebuild_creates_no_version_or_event(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        _eps, sid = await _seed_linked_episodes(repo)
        svc = EpisodeService(db, llm=None, now=_NOW + 1)
        versions_before = len(await repo.list_story_versions(sid))
        mca_events.reset_pending()
        await svc.assemble_stories(CHAT, _NOW + 1)
        await mca_events.flush_events(db)
        versions_after = len(await repo.list_story_versions(sid))
        assert versions_after == versions_before, \
            "повторная сборка без изменений не создаёт версию"
        rows = await repo._fetch_all(
            "SELECT COUNT(*) AS c FROM mca_events WHERE "
            "event_name = 'story_rebuilt'")
        assert rows[0]["c"] == 0, "no-op rebuild не эмитит story_rebuilt"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_mmca05_2_claims_revision_updates_card(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        ep_ids, sid = await _seed_linked_episodes(repo)
        svc = EpisodeService(db, llm=None, now=_NOW + 1)
        # recheck-ревизия утверждений эпизода
        await db.db.execute(
            "UPDATE mca_episodes SET claims_json = ? WHERE episode_id = ?",
            (json.dumps([{"text": "ревизия утверждения", "refs": []}]),
             ep_ids[0]))
        await db.db.commit()
        await svc.assemble_stories(CHAT, _NOW + 2)
        await mca_events.flush_events(db)
        versions = await repo.list_story_versions(sid)
        assert len(versions) == 2, "ревизия claims → новая версия"
        payload = json.loads(versions[-1]["payload_json"])
        texts = [c["text"] for c in payload["claims"]]
        assert "ревизия утверждения" in texts, \
            "карточка обновилась ревизией утверждений"
        assert "утверждение" in texts, "утверждения второго эпизода на месте"
        row = await repo.get_story(sid)
        assert "ревизия утверждения" in row["claims_json"]
        rows = await repo._fetch_all(
            "SELECT COUNT(*) AS c FROM mca_events WHERE "
            "event_name = 'story_rebuilt'")
        assert rows[0]["c"] >= 1, "карточка обновилась + событие контракта"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_mmca05_2_participants_and_dates_revision(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        ep_ids, sid = await _seed_linked_episodes(repo)
        svc = EpisodeService(db, llm=None, now=_NOW + 1)
        # участники эпизода изменились
        await db.db.execute(
            "UPDATE mca_episodes SET participants_json = ? "
            "WHERE episode_id = ?",
            (json.dumps(["2", "777"]), ep_ids[1]))
        await db.db.commit()
        await svc.assemble_stories(CHAT, _NOW + 2)
        assert len(await repo.list_story_versions(sid)) == 2
        # даты эпизода изменились
        await db.db.execute(
            "UPDATE mca_episodes SET event_end_ts = ? WHERE episode_id = ?",
            (T_2022 + 999, ep_ids[1]))
        await db.db.commit()
        await svc.assemble_stories(CHAT, _NOW + 3)
        assert len(await repo.list_story_versions(sid)) == 3, \
            "изменение дат события → новая версия"
    finally:
        await db.close()


# ═══ Read-side: summary/feed (A11/A54)/таблица (T-5156) ══════════════════════

@pytest.mark.asyncio
async def test_summary_honest_states_and_progress(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        # пустой чат: честное empty (не нули в «ok»)
        s = await web_stories.stories_summary(db, CHAT2, now=_NOW)
        assert s["state"] == "empty" and s["counters"]["total"] == 0
        assert s["progress"]["episodes_build"]["state"] == "not_run"
        assert s["progress"]["episodes_backfill"]["state"] == "not_run"
        _eps, sid = await _seed_linked_episodes(repo)
        s = await web_stories.stories_summary(db, CHAT, now=_NOW + 5)
        assert s["state"] == "ok"
        assert s["counters"]["total"] == 1
        assert s["counters"]["new_window"] >= 1, "story_discovered за окно"
        assert s["counters"]["pending_verification"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_feed_both_dates_a11_and_cursor_a54(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        _eps, sid = await _seed_linked_episodes(repo)
        feed = await web_stories.stories_feed(db, CHAT)
        assert feed["state"] == "ok" and feed["events"]
        discovered = [e for e in feed["events"]
                      if e["event"] == "story_discovered"]
        assert discovered, "story_discovered в ленте"
        ev = discovered[0]
        # A11: событие 2022 — обе даты (событие vs обнаружение)
        assert ev["event_start"] == T_2022
        assert ev["discovered_at"] == _NOW
        assert ev["discovered_at"] - ev["event_start"] > 36 * 3600
        assert ev["story_id"] == sid
        assert ev["title"], "название обогащено"
        # A54 (серверная часть контракта): инкремент строго id > cursor
        cursor = feed["cursor"]
        again = await web_stories.stories_feed(db, CHAT, cursor=cursor)
        assert again["events"] == [], "без дублей при повторном опросе"
        # новое событие после курсора → догрузка без потерь (ручная правка
        # через контракт действия — post-commit эмитит story_rebuilt)
        await web_stories.story_action(db, CHAT, sid, action="update",
                                       expected_version=1, title="Ручное имя",
                                       now=_NOW + 9)
        await mca_events.flush_events(db)
        gap = await web_stories.stories_feed(db, CHAT, cursor=cursor)
        assert [e["event"] for e in gap["events"]] == ["story_rebuilt"]
        ids = [e["id"] for e in gap["events"]]
        assert all(i > cursor for i in ids)
        # дедуп: merge страниц клиентом не дублирует (см. JS-тест)
        merged = web_stories.STORY_EVENT_NAMES
        assert "story_rebuilt" in merged and "story_discovered" in merged
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_table_keyset_filters_and_like_escaping(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        _eps, sid = await _seed_linked_episodes(repo)
        page = await web_stories.stories_table(db, CHAT, limit=20)
        assert page["state"] == "ok" and len(page["items"]) == 1
        assert page["has_more"] is False and page["next_cursor"] is None
        row = page["items"][0]
        assert row["num_episodes"] == 2
        assert row["expected_version"] == 1
        # фильтры
        assert len((await web_stories.stories_table(
            db, CHAT, limit=20, q="часть"))["items"]) == 1
        assert len((await web_stories.stories_table(
            db, CHAT, limit=20, title="Эп"))["items"]) == 1
        assert len((await web_stories.stories_table(
            db, CHAT, limit=20, participant="2"))["items"]) == 1
        assert (await web_stories.stories_table(
            db, CHAT, limit=20, participant="999"))["items"] == []
        assert (await web_stories.stories_table(
            db, CHAT, limit=20, event_from=T_2022 + 500))["items"] == []
        assert len((await web_stories.stories_table(
            db, CHAT, limit=20, event_from=T_2022,
            event_to=T_2022 + 200))["items"]) == 1
        assert (await web_stories.stories_table(
            db, CHAT, limit=20, state="closed"))["items"] == []
        assert len((await web_stories.stories_table(
            db, CHAT, limit=20, min_episodes=2, max_episodes=2))["items"]) == 1
        # TH-7: LIKE-метасимволы экранированы (литерал «%» не матчит всё)
        assert (await web_stories.stories_table(
            db, CHAT, limit=20, q="%"))["items"] == []
        # keyset: курсор «до» самой истории → пустая страница; has_more False
        page2 = await web_stories.stories_table(
            db, CHAT, limit=1, before_updated_at=_NOW,
            before_story_id="000")
        assert page2["items"] == []
        page3 = await web_stories.stories_table(
            db, CHAT, limit=1)
        assert page3["has_more"] is False
    finally:
        await db.close()


# ═══ Карточка (A25 cross-chat; T-5165 оригинал) ══════════════════════════════

@pytest.mark.asyncio
async def test_card_content_and_cross_chat_isolation(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        _eps, sid = await _seed_linked_episodes(repo)
        card = await web_stories.story_card(db, CHAT, sid)
        assert card["state"] == "ok"
        story = card["story"]
        assert story["story_id"] == sid
        assert story["claims"] and story["claims"][0]["text"]
        assert len(card["episodes"]) == 2
        assert len(card["versions"]) == 1
        assert card["versions"][0]["created_by"]
        # T-5165: ссылка только из валидированных метаданных (группа)
        assert card["original"]["state"] == "available"
        assert card["original"]["links"]
        url = card["original"]["links"][0]["url"]
        assert url.startswith("https://t.me/c/")
        # A25/TH-1: чужой чат → отказ без раскрытия существования
        assert await web_stories.story_card(db, CHAT2, sid) is None
        assert await web_stories.story_card(db, CHAT, "нет такой") is None
        # ЛС-чат: ключи чужого chat_id в ссылку не превращаются
        from services.web_stories import build_original
        archive = build_original(12345, [f"12345:db:9"])
        assert archive["state"] == "archive_only" and not archive["links"]
        assert build_original(12345, [])["state"] == "unavailable"
    finally:
        await db.close()


# ═══ Действия (A13/CAS; T-5164) ══════════════════════════════════════════════

@pytest.mark.asyncio
async def test_actions_update_cas_stale_and_rebuild(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        _eps, sid = await _seed_linked_episodes(repo)
        # ручная правка (CAS) — версия + override
        res = await web_stories.story_action(
            db, CHAT, sid, action="update", expected_version=1,
            title="Ручное имя", now=_NOW + 10)
        assert res["ok"] is True and res["expected_version"] == 2
        # A13: ручная правка переживает пересборку
        await EpisodeService(db, llm=None, now=_NOW + 11) \
            .assemble_stories(CHAT, _NOW + 11)
        await mca_events.flush_events(db)
        row = await repo.get_story(sid)
        assert row["override_title"] == "Ручное имя"
        versions = await repo.list_story_versions(sid)
        assert any(v["created_by"] == "manual" for v in versions)
        # stale update отклонён с текущей версией (не затирает чужие правки)
        with pytest.raises(web_stories.ActionError) as exc:
            await web_stories.story_action(
                db, CHAT, sid, action="update", expected_version=1,
                title="хак", now=_NOW + 12)
        assert exc.value.kind == "stale"
        assert exc.value.payload["current_version"] == 2
        # пустая правка / неизвестное действие — честный invalid
        with pytest.raises(web_stories.ActionError) as exc:
            await web_stories.story_action(db, CHAT, sid, action="update",
                                           expected_version=2)
        assert exc.value.kind == "invalid"
        with pytest.raises(web_stories.ActionError) as exc:
            await web_stories.story_action(db, CHAT, sid, action="explode")
        assert exc.value.kind == "invalid"
        # no-op rebuild — версия не растёт (пересборка без изменений)
        before = len(await repo.list_story_versions(sid))
        res = await web_stories.story_action(db, CHAT, sid,
                                             action="rebuild",
                                             now=_NOW + 13)
        assert res["ok"] is True
        assert len(await repo.list_story_versions(sid)) == before
        # exclude/restore
        res = await web_stories.story_action(db, CHAT, sid,
                                             action="exclude",
                                             now=_NOW + 14)
        assert res["ok"] is True
        assert (await repo.get_story(sid))["excluded_from_retrieval"] == 1
        res = await web_stories.story_action(db, CHAT, sid,
                                             action="restore",
                                             now=_NOW + 15)
        assert (await repo.get_story(sid))["excluded_from_retrieval"] == 0
        # неизвестная история
        with pytest.raises(web_stories.ActionError) as exc:
            await web_stories.story_action(db, CHAT, "нет", action="rebuild")
        assert exc.value.kind == "not_found"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_actions_merge_split_redirect_and_versions(tmp_path):
    db = await _db(tmp_path)
    try:
        repo = EpisodeRepository(db)
        ep_ids, sid = await _seed_linked_episodes(repo)
        # split: отделяем первый эпизод
        res = await web_stories.story_action(
            db, CHAT, sid, action="split", episode_ids=[ep_ids[0]],
            now=_NOW + 20)
        assert res["ok"] is True and res["story_id"]
        new_sid = res["story_id"]
        assert await repo.story_episode_ids(new_sid) == [ep_ids[0]]
        assert len(await repo.list_story_versions(new_sid)) == 1
        # частичный split — redirect НЕ создаётся (обе живы)
        assert await repo.redirect_target("story", sid) is None
        # merge обратно: redirect + версия target
        res = await web_stories.story_action(
            db, CHAT, new_sid, action="merge", target_id=sid,
            now=_NOW + 21)
        assert res["ok"] is True
        assert await repo.redirect_target("story", new_sid) == sid
        assert len(await repo.story_episode_ids(sid)) == 2
        # merge в себя — честный отказ
        with pytest.raises(web_stories.ActionError) as exc:
            await web_stories.story_action(db, CHAT, sid, action="merge",
                                           target_id=sid, now=_NOW + 22)
        assert exc.value.kind == "invalid"
        # повторный split: после частичного сплита источник остался с одним
        # эпизодом — «отделять нечего» → no-op (conflict)
        res = await web_stories.story_action(
            db, CHAT, sid, action="split", episode_ids=[ep_ids[1]],
            now=_NOW + 23)
        assert res["ok"] is True
        assert await repo.story_episode_ids(sid) == [ep_ids[0]]
        with pytest.raises(web_stories.ActionError) as exc:
            await web_stories.story_action(db, CHAT, sid, action="split",
                                           episode_ids=[ep_ids[0]],
                                           now=_NOW + 24)
        assert exc.value.kind == "conflict"
    finally:
        await db.close()


# ═══ Routes: RBAC/chat-scope/гейты/валидация (A25/TH-2/TH-7) ═════════════════

def _run(coro):
    """Синхронно выполнить async-функцию (sync-тесты/TestClient; прецедент
    test_cover_styles_contract_asap32._run)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def api_db(tmp_path):
    """SQLite-БД фичи + подмена lore_runtime.get_lore_db на неё."""
    db = _run(_db(tmp_path, "mca12api.db"))
    yield db
    _run(db.close())


def _patch_lore(monkeypatch, db):
    monkeypatch.setattr(lore_runtime, "get_lore_db", lambda: db)


def test_api_unauthenticated_rejected(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    client = _client(api_db)
    # без initData → 401 на любом read (A25: неавторизованный — отказ)
    assert client.get("/api/stories/summary").status_code == 401
    assert client.get("/api/stories/feed").status_code == 401
    assert client.get("/api/stories").status_code == 401
    resp = client.post("/api/stories/x/action", json={"action": "rebuild"})
    assert resp.status_code == 401


def test_api_summary_no_chat_and_foreign_chat(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    client = _client(api_db)
    # без чата — честный no_chat (не нули)
    r = client.get("/api/stories/summary", headers=_hdr())
    assert r.status_code == 200
    assert r.json()["state"] == "no_chat"
    r = client.get("/api/stories/summary", headers=_hdr(ADMIN_ID),
                   )
    assert r.json()["enabled"] is True
    # мусорный X-Chat-Id → 422
    bad = dict(_hdr(), **{"X-Chat-Id": "abc"})
    assert client.get("/api/stories/summary", headers=bad).status_code == 422
    # не-админ (роль user) — нет доступа к чату → 403 (chat scope)
    user_client = _client(api_db, admin=False)
    forbidden = dict(_hdr(USER_ID), **{"X-Chat-Id": str(CHAT)})
    assert user_client.get("/api/stories/summary",
                           headers=forbidden).status_code == 403
    assert user_client.get("/api/stories/feed",
                           headers=forbidden).status_code == 403
    assert user_client.get("/api/stories",
                           headers=forbidden).status_code == 403


def test_api_k1_off_honest_disabled(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    monkeypatch.setattr(mca_gates, "stories_vitrina_enabled",
                        lambda: False)
    client = _client(api_db)
    r = client.get("/api/stories/summary",
                   headers=dict(_hdr(), **{"X-Chat-Id": str(CHAT)}))
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False and body["state"] == "disabled"
    r = client.get("/api/stories/feed",
                   headers=dict(_hdr(), **{"X-Chat-Id": str(CHAT)}))
    assert r.json()["enabled"] is False
    r = client.get("/api/stories",
                   headers=dict(_hdr(), **{"X-Chat-Id": str(CHAT)}))
    assert r.json()["enabled"] is False
    # карточка — честный disabled (не 404-заглушка)
    r = client.get("/api/stories/some-id", headers=_hdr())
    assert r.status_code == 200 and r.json()["state"] == "disabled"


def test_api_mutation_gates_and_permissions(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    client = _client(api_db)
    headers = dict(_hdr(), **{"X-Chat-Id": str(CHAT)})
    # K2 OFF → 409 disabled (честный, D15); проверка ДО прав
    monkeypatch.setattr(mca_gates, "stories_manage_enabled",
                        lambda: False)
    r = client.post("/api/stories/x/action", headers=headers,
                    json={"action": "rebuild"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "disabled"
    monkeypatch.setattr(mca_gates, "stories_manage_enabled",
                        lambda: True)
    # не-админ → 403 (TH-2: server-side проверка прав каждого действия)
    user_client = _client(api_db, admin=False)
    r = user_client.post("/api/stories/x/action",
                         headers=dict(_hdr(USER_ID), **{"X-Chat-Id": str(CHAT)}),
                         json={"action": "rebuild"})
    assert r.status_code == 403
    # админ без чата → 422 (нужен контекст чата)
    r = client.post("/api/stories/x/action", headers=_hdr(),
                    json={"action": "rebuild"})
    assert r.status_code == 422
    # неизвестное действие → 422
    r = client.post("/api/stories/x/action", headers=headers,
                    json={"action": "explode"})
    assert r.status_code == 422
    # несуществующая история → 404
    r = client.post("/api/stories/нет-такой/action", headers=headers,
                    json={"action": "rebuild"})
    assert r.status_code == 404


def test_api_server_side_validation_th7(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    client = _client(api_db)
    headers = dict(_hdr(), **{"X-Chat-Id": str(CHAT)})
    # лимит вне whitelist → 422 (серверная валидация, client-side trust
    # запрещён)
    assert client.get("/api/stories?limit=0",
                      headers=headers).status_code == 422
    assert client.get("/api/stories?limit=1000",
                      headers=headers).status_code == 422
    assert client.get("/api/stories?state=bogus",
                      headers=headers).status_code == 422
    assert client.get("/api/stories?verification=bogus",
                      headers=headers).status_code == 422
    assert client.get("/api/stories?min_episodes=-1",
                      headers=headers).status_code == 422
    assert client.get("/api/stories/feed?limit=500",
                      headers=headers).status_code == 422
    assert client.get("/api/stories/feed?cursor=-5",
                      headers=headers).status_code == 422
    # валидные значения проходят
    ok = client.get("/api/stories?limit=5&state=open&verification=unknown",
                    headers=headers)
    assert ok.status_code == 200
    assert ok.json()["manage_enabled"] is True


def test_api_happy_path_update_via_http(api_db, monkeypatch):
    _patch_lore(monkeypatch, api_db)
    client = _client(api_db)
    headers = dict(_hdr(), **{"X-Chat-Id": str(CHAT)})

    async def _seed():
        repo = EpisodeRepository(api_db)
        return (await _seed_linked_episodes(repo))[1]

    sid = _run(_seed())
    # карточка через HTTP
    r = client.get(f"/api/stories/{sid}", headers=headers)
    assert r.status_code == 200
    card = r.json()
    assert card["story"]["story_id"] == sid
    version = card["story"]["expected_version"]
    # правка через HTTP (CAS)
    r = client.post(f"/api/stories/{sid}/action", headers=headers,
                    json={"action": "update", "expected_version": version,
                          "title": "Через HTTP"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # stale через HTTP → 409 c текущей версией (A13)
    r = client.post(f"/api/stories/{sid}/action", headers=headers,
                    json={"action": "update", "expected_version": version,
                          "title": "Опоздал"})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "stale"
    assert r.json()["detail"]["current_version"] == version + 1
    # feed/summary через HTTP под правами
    r = client.get("/api/stories/feed?cursor=0&limit=10", headers=headers)
    assert r.status_code == 200 and r.json()["state"] == "ok"
    r = client.get("/api/stories/summary", headers=headers)
    assert r.status_code == 200 and r.json()["state"] == "ok"


# ═══ A26 структурная часть + §16.3 defaults (T-5168) + JS ════════════════════

def test_a26_structure_single_insert_no_new_route():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "web/index.html").read_text(encoding="utf-8")
    # единственная вставка витрины в F11-сетку
    assert html.count('data-stories>') == 1
    assert html.count('data-stories-feed') == 1
    # верхнеуровневого маршрута историй нет (GEN-R12)
    assert "#/stories" not in html
    # таблица — внутри существующей memory_rag-вкладки
    rag = html.index("currentTab.id === 'memory_rag'")
    manage = html.index("data-stories-manage")
    assert rag < manage
    # вставка витрины: после «Бюджетов интеллекта», до «Доступности ключей»
    assert html.index("status-budgets") < html.index('data-stories>')
    assert html.index('data-stories>') < html.index("Доступность ключей")
    # блок инициативы — в карточке мониторинга интеллекта
    assert "data-intents" in html
    assert "data-stories-settings" in html
    assert "data-adjacent" in html
    # без html-вставок в новых зонах (TH-3)
    zone = html[html.index('data-stories>'):html.index("Доступность ключей")]
    assert not re.search(r"v-html|innerHTML|<script", zone)


def test_a26_ui_flags_not_extended():
    # routes.py не менялся → ui_flags /api/me не расширялись (гейты учатся
    # с ответов API) — фиксируем отсутствие MCA_STORIES_* в routes.py
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    routes = (root / "web/api/routes.py").read_text(encoding="utf-8")
    assert "MCA_STORIES" not in routes


def test_settings_meta_defaults_match_settings():
    """§16.3: default в JS-рендере = КОД-дефолту Settings (литерал в
    settings.py; env-override .env не «drift» — effective показывает его)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "web/app.js").read_text(encoding="utf-8")
    pairs = dict(re.findall(
        r"key: '([^']+)',\s*title: '[^']*',\s*def: '([^']*)'", js))
    settings_src = (root / "config/settings.py").read_text(encoding="utf-8")

    def code_default(field: str) -> str:
        # литерал дефолта в Settings-декларации (env-независимая каноника)
        m = re.search(rf'{field}:[^=]*=\s*_env_\w+\(\s*"{field}",\s*([^,)]+)',
                      settings_src)
        assert m, f"дефолт {field} не найден в settings.py"
        raw = m.group(1).strip()
        raw = {"True": "True", "False": "False"}.get(raw, raw)
        return raw.strip('"')

    expected_fields = {
        "memory.random_exploration_probability":
            "RANDOM_EXPLORATION_PROBABILITY",
        "memory.random_sleep_exploration_probability":
            "RANDOM_SLEEP_EXPLORATION_PROBABILITY",
        "memory.random_source": "RANDOM_SOURCE",
        "memory.random_fallback_to_pseudorandom":
            "RANDOM_FALLBACK_TO_PSEUDORANDOM",
        "limits.worker_daily_llm_calls_per_chat":
            "WORKER_DAILY_LLM_CALLS_PER_CHAT",
        "limits.worker_daily_llm_calls_global":
            "WORKER_DAILY_LLM_CALLS_GLOBAL",
        "flags.budgets_enabled": "BUDGETS_ENABLED",
        "limits.chat_context_budget_tokens": "CHAT_CONTEXT_BUDGET_TOKENS",
    }
    from services.param_catalog import REGISTRY
    catalog_keys = {s.pg_key for s in REGISTRY.values()}
    for pg_key, field in expected_fields.items():
        want = code_default(field)
        assert pairs.get(pg_key) == want, \
            f"{pg_key}: JS def {pairs.get(pg_key)!r} != код-дефолт {want!r}"
        assert pg_key in catalog_keys, \
            f"{pg_key} существует в каталоге (Δ каталога = 0)"


def test_js_ui_suite():
    import os
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-тест пропущен")
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    res = subprocess.run(
        [node, str(root / "tests/js/round1046_mca12_stories_ui_test.js")],
        capture_output=True, text=True, timeout=60, cwd=str(root))
    assert res.returncode == 0, (
        "JS-тест MCA-12 упал:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "MCA12-STORIES-UI-OK" in res.stdout
