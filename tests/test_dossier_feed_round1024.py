"""F4 round 10.24 (dossier-live-feed-round1024, ADR-1024-8) — тесты ленты досье.

Покрытие (spec §3.3/§6):
  * API `/api/oversight/dossier_feed` аддитивно отдаёт `user_id`/`user_name`
    (обратный резолв `graph_facts.target_user` → участник, read-time, Δ DDL=0);
  * совпадение по канон-алиасу (AliasResolver) и по сырому имени;
  * нерезолвленное имя → `user_id is null`, строка остаётся в ответе;
  * ошибка резолва/БД → fail-open (HTTP 200, `user_id=null`);
  * контракт-совместимость: прежние ключи `chat_id/name/excerpt` на месте,
    лишние поля не утекают (R17); резолв не пишет в БД (read-only);
  * статика фронта: вертикальная лента/скорость/кликабельность/флаг.

Работаем на **настоящих** `sqlite3.Row` (как aiosqlite.Row) в боевом порядке
`get_active_participants` (`ORDER BY cnt DESC, user_id ASC`), чтобы регресс
`.get`-обращения и приоритета коллизий не спрятался за тихим `except`
(прецедент F18/ADR-1024-19; review iter1 F4).
"""
import logging
import sqlite3
import unicodedata
from pathlib import Path

import pytest

from web.api import oversight as ov

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")


def _active_rows(pairs: list) -> list:
    """`sqlite3.Row` в РЕАЛЬНОМ порядке `get_active_participants`
    (`services/database.py:3719-3725`): одна строка на участника,
    ``ORDER BY cnt DESC, user_id ASC``. `pairs = [(user_id, name, cnt)]`."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE m(user_id INTEGER, author_name TEXT)")
        for uid, name, cnt in pairs:
            for _ in range(int(cnt)):
                conn.execute("INSERT INTO m VALUES (?, ?)", (uid, name))
        return conn.execute(
            "SELECT user_id, MAX(author_name) AS author_name, COUNT(*) AS cnt "
            "FROM m WHERE user_id IS NOT NULL GROUP BY user_id "
            "ORDER BY cnt DESC, user_id ASC").fetchall()
    finally:
        conn.close()


class _FakeDB:
    """Минимальный read-only стаб: `dossier_feed` + `get_active_participants`."""

    def __init__(self, feed_rows=None, participants=None):
        self._feed = feed_rows or []
        self._participants = participants or {}
        self.raise_feed = False
        self.raise_participants = False
        self.writes = 0

    async def dossier_feed(self, limit=12, chat_id=None):
        if self.raise_feed:
            raise RuntimeError("feed boom")
        return list(self._feed)

    async def get_active_participants(self, chat_id, since_ts, cap):
        if self.raise_participants:
            raise RuntimeError("participants boom")
        return list(self._participants.get(chat_id, []))

    async def execute(self, *a, **k):   # запись запрещена — резолв read-only
        self.writes += 1
        raise AssertionError("резолв user_id не должен писать в БД (Δ DDL=0)")


class _Resolver:
    """Стаб AliasResolver: {str(user_id): alias}."""

    def __init__(self, mapping=None):
        self._m = mapping or {}

    def resolve(self, user_id, nickname=None, username=None):
        if str(user_id) in self._m:
            return self._m[str(user_id)]
        if nickname:
            return nickname
        return str(user_id)


def _use_db(monkeypatch, db):
    monkeypatch.setattr(ov.lore_runtime, "get_lore_db", lambda: db)


def _use_resolver(monkeypatch, mapping):
    async def _build(chat_id):
        return _Resolver(mapping)

    monkeypatch.setattr(ov.summary_aliases, "build_alias_resolver", _build)


def _dossier_item(chat_id, name, fact):
    return {"chat_id": chat_id, "name": name, "fact": fact}


# ── API-контракт: аддитивные user_id/user_name ──────────────────────────────
@pytest.mark.asyncio
async def test_api_resolves_user_id_by_name(monkeypatch):
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Толян", "любит мемы")],
        participants={-100: _active_rows([(5, "Толян", 1)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["user_id"] == 5
    assert item["user_name"] == "Толян"
    # Контракт-совместимость: прежние ключи на месте (R16).
    assert item["chat_id"] == -100
    assert item["name"] == "Толян"
    assert item["excerpt"] == "любит мемы"
    # Никаких лишних полей наружу (R17).
    assert set(item.keys()) == {"chat_id", "name", "excerpt",
                                "user_id", "user_name"}
    assert db.writes == 0


@pytest.mark.asyncio
async def test_api_resolves_user_id_by_alias_canon(monkeypatch):
    """Сырое имя участника отличается от `target_user` — матч по канон-алиасу."""
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Толян", "факт")],
        participants={-100: _active_rows([(7, "tolik_nick", 1)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {"7": "Толян"})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)

    assert body["items"][0]["user_id"] == 7
    assert body["items"][0]["user_name"] == "Толян"


@pytest.mark.asyncio
async def test_api_unresolved_name_stays_text(monkeypatch):
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Призрак", "факт")],
        participants={-100: _active_rows([(5, "Толян", 1)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)

    assert len(body["items"]) == 1, "нерезолвленная строка остаётся в ответе"
    assert body["items"][0]["user_id"] is None
    assert body["items"][0]["user_name"] == "Призрак"


@pytest.mark.asyncio
async def test_api_fail_open_on_resolve_error(monkeypatch):
    """Ошибка резолва → HTTP-контракт не ломается: 200, `user_id=null`."""
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Толян", "факт")],
        participants={-100: _active_rows([(5, "Толян", 1)])})
    db.raise_participants = True
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)

    assert len(body["items"]) == 1
    assert body["items"][0]["user_id"] is None
    assert body["items"][0]["excerpt"] == "факт"


@pytest.mark.asyncio
async def test_api_fail_open_when_db_missing(monkeypatch):
    monkeypatch.setattr(ov.lore_runtime, "get_lore_db", lambda: None)
    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)
    assert body == {"chat_id": None, "items": []}


@pytest.mark.asyncio
async def test_api_global_resolves_per_chat(monkeypatch):
    """GLOBAL: у каждого чата своя карта участников (кэш по chat_id)."""
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Аня", "ф1"),
                   _dossier_item(-200, "Борис", "ф2")],
        participants={-100: _active_rows([(1, "Аня", 1)]),
                      -200: _active_rows([(2, "Борис", 1)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)
    by_chat = {i["chat_id"]: i for i in body["items"]}

    assert by_chat[-100]["user_id"] == 1
    assert by_chat[-200]["user_id"] == 2


@pytest.mark.asyncio
async def test_api_collision_prefers_more_active(monkeypatch):
    """Коллизия имён: побеждает более АКТИВНЫЙ участник (`cnt` DESC)."""
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Аня", "факт")],
        # uid 9 активнее (cnt 5) → в боевом порядке первый, несмотря на uid.
        participants={-100: _active_rows([(3, "Аня", 1), (9, "Аня", 5)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)
    assert body["items"][0]["user_id"] == 9


@pytest.mark.asyncio
async def test_api_collision_tiebreak_smaller_uid(monkeypatch):
    """Коллизия имён при равной активности: tiebreak — меньший `user_id`
    (`ORDER BY cnt DESC, user_id ASC`, database.py:3719-3725)."""
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Аня", "факт")],
        participants={-100: _active_rows([(3, "Аня", 2), (9, "Аня", 2)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)
    assert body["items"][0]["user_id"] == 3


@pytest.mark.asyncio
async def test_api_nfkc_name_match(monkeypatch):
    """Разные Unicode-формы имени (NFD vs NFC) совпадают (NFKC-нормализация)."""
    nfd_name = unicodedata.normalize("NFD", "Йожик")  # «Й» → «И» + бревис
    assert nfd_name != "Йожик", "предпосылка: формы действительно различаются"
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, nfd_name, "факт")],
        participants={-100: _active_rows([(5, "Йожик", 1)])})
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    body = await ov.dossier_feed(None, None, chat_id=None, limit=12)
    assert body["items"][0]["user_id"] == 5


@pytest.mark.asyncio
async def test_api_logs_do_not_leak_raw_values(monkeypatch, caplog):
    """R17 (spec §6): серверные логи не содержат сырых значений ленты
    (ни excerpt-секрета, ни имени) даже при сбое резолва."""
    canary = "CANARY-SECRET-VALUE-1234567890"
    db = _FakeDB(
        feed_rows=[_dossier_item(-100, "Толян", canary)],
        participants={-100: _active_rows([(5, "Толян", 1)])})
    db.raise_participants = True
    _use_db(monkeypatch, db)
    _use_resolver(monkeypatch, {})

    with caplog.at_level(logging.WARNING, logger="web.api.oversight"):
        body = await ov.dossier_feed(None, None, chat_id=None, limit=12)

    assert body["items"][0]["user_id"] is None, "сбой резолва → fail-open"
    assert canary not in caplog.text, "R17: сырое значение утекло в лог"
    assert "Толян" not in caplog.text, "R17: имя участника утекло в лог"


# ── Статика фронта: вертикаль/скорость/клик/флаг ────────────────────────────
class TestDossierFeedStatic:
    def test_css_vertical_marker_and_reduced_motion(self):
        assert "dossier-ticker-scroll-y" in CSS
        assert "prefers-reduced-motion" in CSS
        assert "translateY" in CSS
        # mask 180deg (вертикаль), фикс. высота контейнера.
        assert "180deg, transparent, #000 12%" in CSS
        assert "--dossier-h: 180px" in CSS
        # Прежняя горизонталь 42s сохраняется (OFF-ветка) — не удаляем.
        assert "dossier-ticker-scroll 42s linear infinite" in CSS

    def test_css_seamless_uses_gap_var(self):
        # review iter1: бесшовность через --dossier-gap/2, без магической .25rem.
        assert "calc(-50% - (var(--dossier-gap) / 2))" in CSS

    def test_css_speed_var_used_by_track(self):
        assert "var(--dossier-speed" in CSS

    def test_index_gates_flag_and_keeps_off_branch(self):
        assert "uiFlag('DOSSIER_LIVE_FEED_ENABLED')" in INDEX
        assert "dossier-ticker--y" in INDEX
        assert "dossier-ticker__item--click" in INDEX
        assert "openFeedDossier(it)" in INDEX
        assert "@keydown.enter.prevent" in INDEX
        # review iter1: клише-клон исключён из a11y/таб-порядка.
        assert ":aria-hidden=\"it.dup ? 'true' : null\"" in INDEX
        assert "!it.dup && it.user_id != null" in INDEX
        # OFF-ветка — прежний горизонтальный тикер (role="marquee").
        assert 'role="marquee"' in INDEX

    def test_appjs_speed_and_click_path(self):
        assert "dossierFeedSpeed" in APP_JS
        assert "openFeedDossier" in APP_JS
        assert "dup: true" in APP_JS
        assert "user_name" in APP_JS and "user_id" in APP_JS

    def test_flag_delivered_additionally(self):
        assert "DOSSIER_LIVE_FEED_ENABLED" in SETTINGS
        assert "DOSSIER_LIVE_FEED_ENABLED" in ROUTES
