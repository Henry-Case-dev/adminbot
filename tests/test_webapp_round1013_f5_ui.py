"""F5 `cognition-dashboard-round1013` — дашборд «Осмысление» + виджет
«Интеллект и Память» (ТЗ §5/§7, spec §3-§4).

Покрытие:
  * backend: форма `cognition/status`, `graph` (cap/truncated/R16),
    `stats`, `timeline` (merge+DESC), `beliefs?kind=`, аддитивное
    `/api/status.context`;
  * DB read-хелперы (`graph_snapshot`/`graph_stats`/`last_run_at`/
    `sum_dream_tokens`) на in-memory SQLite;
  * R17: ответы не содержат ключей/эмбеддингов/base_url;
  * UI-маркеры app.js/index.html + self-host vis-network (без CDN).
"""
import datetime
import json
import time
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(".")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite DatabaseService (async-фикстура — без утечек loop)."""
    from services.database import DatabaseService
    d = DatabaseService(":memory:")
    await d.initialize()
    yield d
    await d.close()


async def _seed_graph(db, chat_id=1, nodes=5, edges=None):
    """5 узлов user + рёбра цепочкой (degree ≥ 1 у всех)."""
    ids = []
    for i in range(nodes):
        ids.append(await db.upsert_node(chat_id, f"node{i}", "user"))
    if edges is None:
        for i in range(nodes - 1):
            await db.upsert_edge(ids[i], ids[i + 1], "связь")
    else:
        for src, dst, rel in edges:
            await db.upsert_edge(ids[src], ids[dst], rel)
    return ids


# ── backend: /api/memory/* helpers ─────────────────────────────────────────

class TestBeliefsKindFilter:
    def test_belief_out_type_marker(self):
        from web.api import memory_agi as ma
        base = {
            "id": 1, "chat_id": 2, "fact": "x", "weight": 0.5,
            "importance": 1, "source_ids": "[]", "belief_meta": None,
            "status": "confirmed", "supersedes": None, "created_at": 3,
        }
        normal = ma._belief_out(dict(base))
        assert normal["type"] == "belief"
        assert normal["is_paradigm"] is False
        para = ma._belief_out({**base, "belief_meta":
                               '{"type":"paradigm","base_weight":0.6}'})
        assert para["type"] == "paradigm"
        assert para["is_paradigm"] is True
        assert para["base_weight"] == 0.6

    @pytest.mark.asyncio
    async def test_kind_filters(self, db, monkeypatch):
        from web.api import memory_agi as ma
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "kind, status, weight, belief_meta) VALUES "
            "(1, 'обычное', 'chat_history', 1, 'belief', 'confirmed', 0.5, "
            " '{}'),"
            "(1, 'парадигма', 'chat_history', 2, 'belief', 'confirmed', 0.6, "
            " '{\"type\":\"paradigm\"}')")
        await db.db.commit()
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        all_rows = await ma.dream_beliefs(
            request=None, user=None, chat_id=None, limit=50, status="all",
            kind="all")
        assert len(all_rows) == 2
        beliefs = await ma.dream_beliefs(
            request=None, user=None, chat_id=None, limit=50, status="all",
            kind="belief")
        assert [r["fact"] for r in beliefs] == ["обычное"]
        paradigms = await ma.dream_beliefs(
            request=None, user=None, chat_id=None, limit=50, status="all",
            kind="paradigm")
        assert [r["fact"] for r in paradigms] == ["парадигма"]
        assert paradigms[0]["type"] == "paradigm"


class TestCognitionStatus:
    @pytest.mark.asyncio
    async def test_shape_and_budget(self, db, monkeypatch):
        from web.api import memory_agi as ma
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(ma.hot, "get",
                            lambda key, default=None: default)
        data = await ma.cognition_status(request=None, user=None,
                                         chat_id=None)
        assert set(data) >= {"dream", "deep_sleep", "lore", "nostalgia"}
        d = data["dream"]
        assert d["state"] in ("sleep", "synthesizing", "limit_exhausted")
        assert isinstance(d["next_wake_at"], int)
        assert d["budget"]["distilled_limit"] >= 0
        assert "last_inject_at" in data["lore"]
        assert data["nostalgia"]["mode"] in ("silence", "cooldown", "ready")

    @pytest.mark.asyncio
    async def test_running_beats_state(self, db, monkeypatch):
        from web.api import memory_agi as ma

        class _W:
            dream_running = True
            deep_running = True

        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(ma.hot, "get",
                            lambda key, default=None: default)
        monkeypatch.setattr(ma.lore_runtime, "get_dream_worker",
                            lambda: _W())
        data = await ma.cognition_status(request=None, user=None,
                                         chat_id=None)
        assert data["dream"]["state"] == "synthesizing"
        assert data["dream"]["running"] is True
        assert data["deep_sleep"]["running"] is True

    @pytest.mark.asyncio
    async def test_nostalgia_status_with_chat_id_bot_excluded(self, db,
                                                              monkeypatch):
        """BLOCKER-2: последнее ЮЗЕРСКОЕ сообщение (бот исключается по
        реальному bot_id) + порядок аргументов `_nostalgia_state`."""
        from web.api import memory_agi as ma

        class _NW:
            bot_id = 999

        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(ma.lore_runtime, "get_nostalgia_worker",
                            lambda: _NW())
        monkeypatch.setattr(ma.hot, "get",
                            lambda key, default=None: {
                                "memory.nostalgia_min_silence_minutes": 45,
                                "memory.nostalgia_cooldown_hours": 12,
                            }.get(key, default))
        now = int(time.time())
        # последнее юзерское — 60 мин назад (тишина 45 мин уже выдержана)
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
            "author_name) VALUES (?, ?, ?, ?, ?)",
            (111, 7, "юзер", now - 3600, "Саша"))
        # сообщение БОТА — 1 мин назад (обязано исключаться из «тишины»)
        await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
            "author_name) VALUES (?, ?, ?, ?, ?)",
            (999, 7, "бот", now - 60, "бот"))
        # ностальгия отправлена 2 часа назад → кулдаун 12ч → остаток 10ч
        await db.db.execute(
            "INSERT INTO nostalgia_log (chat_id, ts, kind, status) "
            "VALUES (?, ?, 'golden', 'sent')", (7, now - 7200))
        await db.db.commit()
        data = await ma.cognition_status(request=None, user=None, chat_id=7)
        nost = data["nostalgia"]
        # swap аргументов дал бы 11ч, а включение бота — режим silence
        assert nost["mode"] == "cooldown"
        assert nost["cooldown_left_h"] == 10

    def test_nostalgia_state_modes(self):
        from web.api import memory_agi as ma
        now = 1_000_000.0
        # тишина: последнее сообщение 10 мин назад, порог 45 → 35 слева
        s = ma._nostalgia_state(now - 600, None, now, 45, 12)
        assert s["mode"] == "silence"
        assert 34 <= s["silence_left_min"] <= 35
        assert s["silence_min_total"] == 45
        # кулдаун: sent 2 часа назад, порог 12 → 10 слева
        c = ma._nostalgia_state(None, int(now) - 7200, now, 45, 12)
        assert c["mode"] == "cooldown"
        assert c["cooldown_left_h"] == 10
        # готово
        r = ma._nostalgia_state(int(now) - 999999, int(now) - 999999,
                                now, 45, 12)
        assert r["mode"] == "ready"

    def test_next_hour_and_day_start(self):
        from web.api import memory_agi as ma
        tz = "UTC"
        base = datetime.datetime(2026, 9, 13, 5, 30,
                                 tzinfo=datetime.timezone.utc)
        nxt = ma._next_hour_epoch(4, tz, base.timestamp())
        # 04:00 уже прошло → следующий день
        assert datetime.datetime.fromtimestamp(
            nxt, datetime.timezone.utc).hour == 4
        after = datetime.datetime.fromtimestamp(
            nxt, datetime.timezone.utc).day
        assert after == 14
        start = ma._local_day_start(base.timestamp(), tz)
        sd = datetime.datetime.fromtimestamp(start, datetime.timezone.utc)
        assert (sd.hour, sd.minute) == (0, 0)


class TestGraphAndStats:
    @pytest.mark.asyncio
    async def test_graph_cap_truncated_r16(self, db, monkeypatch):
        from web.api import memory_agi as ma
        await _seed_graph(db, chat_id=1, nodes=5)
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        monkeypatch.setattr(ma, "GRAPH_MAX_NODES", 3)
        monkeypatch.setattr(ma, "GRAPH_MAX_EDGES", 2)
        snap = await ma.memory_graph(request=None, user=None, chat_id=1)
        assert len(snap["nodes"]) == 3
        assert snap["truncated"] is True
        assert snap["limits"] == {"nodes": 3, "edges": 2}
        # R16: id-ключи, label/group присутствуют (без сырых текстов)
        assert all({"id", "label", "group"} <= set(n) for n in snap["nodes"])
        # рёбра ссылаются на оставшиеся узлы
        ids = {n["id"] for n in snap["nodes"]}
        assert all(e["from"] in ids and e["to"] in ids
                   for e in snap["edges"])

    @pytest.mark.asyncio
    async def test_graph_degree_order(self, db, monkeypatch):
        from web.api import memory_agi as ma
        ids = await _seed_graph(db, chat_id=1, nodes=4,
                                edges=[(0, 1, "a"), (0, 2, "b"),
                                       (0, 3, "c"), (1, 2, "d")])
        snap = await db.graph_snapshot(chat_id=1)
        # узел 0 — degree 3, первый
        assert snap["nodes"][0]["id"] == ids[0]
        assert snap["nodes"][0]["degree"] == 3
        assert snap["truncated"] is False

    @pytest.mark.asyncio
    async def test_stats_counters(self, db):
        await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "kind, status, weight, belief_meta) VALUES "
            "(1, 'f1', 'chat_history', 1, 'fact', 'confirmed', 0.5, '{}'),"
            "(1, 'f2', 'chat_history', 2, 'fact', 'confirmed', 0.5, '{}'),"
            "(1, 'b1', 'chat_history', 3, 'belief', 'confirmed', 0.5, '{}'),"
            "(1, 'b2', 'chat_history', 4, 'belief', 'archived_belief', 0.2, "
            " '{}'),"
            "(1, 'p1', 'chat_history', 5, 'belief', 'confirmed', 0.6, "
            " '{\"type\":\"paradigm\"}'),"
            "(1, 'm1', 'chat_history', 6, 'fact', 'chat_meme', 0.5, '{}'),"
            "(1, 'u1', 'chat_history', 7, 'fact', 'unconfirmed', 0.5, '{}')")
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, "
            "created_at) VALUES (1, NULL, 'защищён', 1)")
        await db.db.commit()
        await _seed_graph(db, chat_id=1, nodes=3,
                          edges=[(0, 1, "друг"), (1, 2, "коллега")])
        stats = await db.graph_stats(chat_id=1)
        assert stats["facts"] == 2          # f1 + f2 (без мема и unconfirmed)
        assert stats["beliefs"] == 2        # b1+b2 (без парадигмы p1)
        assert stats["archived_beliefs"] == 1
        assert stats["paradigms"] == 1
        assert stats["protected_facts"] == 1
        assert stats["memes"] == 1
        assert stats["graph_nodes"] == 3
        assert stats["graph_edges"] == 2
        assert stats["relation_types"] == 2

    @pytest.mark.asyncio
    async def test_stats_api_fail_open(self, monkeypatch):
        from web.api import memory_agi as ma

        class _Boom:
            async def graph_stats(self, chat_id=None):
                raise RuntimeError("db down")

        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: _Boom())
        stats = await ma.memory_stats(request=None, user=None, chat_id=None)
        assert stats == {"facts": 0, "beliefs": 0, "archived_beliefs": 0,
                         "protected_facts": 0, "paradigms": 0, "memes": 0,
                         "graph_nodes": 0, "graph_edges": 0,
                         "relation_types": 0}


class TestTimeline:
    @pytest.mark.asyncio
    async def test_merge_sorted_desc(self, db, monkeypatch):
        from web.api import memory_agi as ma
        await db.db.execute(
            "INSERT INTO memory_dream_log (chat_id, run_at, kind, tokens, "
            "status) VALUES (1, 100, 'distilled', 10, 'ok'),"
            "(1, 300, 'deep_run', 20, 'ok')")
        await db.db.execute(
            "INSERT INTO nostalgia_log (chat_id, ts, kind, status, "
            "created_at) VALUES (1, 200, 'golden', 'sent', 200),"
            "(1, 250, 'golden', 'skipped', 250)")
        await db.db.commit()
        monkeypatch.setattr(ma, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(ma, "_db_or_503", lambda: db)
        # изолируем от in-memory lore-accounting других тестов
        from services import direct_chat_service as dcs
        monkeypatch.setitem(dcs._PROCESS_ACCOUNTING, "lore_last_inject_at",
                            None)
        events = await ma.memory_timeline(request=None, user=None,
                                          chat_id=1, limit=20)
        events = [e for e in events if e["source"] in ("dream", "nostalgia")]
        ts = [e["ts"] for e in events]
        assert ts == sorted(ts, reverse=True)
        assert [e["ts"] for e in events] == [300, 200, 100]
        icons = {e["ts"]: e["icon"] for e in events}
        assert icons[300] == "🌌"
        assert icons[200] == "📻"
        assert icons[100] == "🌙"


class TestContextAccounting:
    def test_record_and_snapshot(self):
        from services import direct_chat_service as dcs
        dcs.record_context_usage(1500, 4000, True)
        acct = dcs.get_process_accounting()
        assert acct["context_used"] == 1500
        assert acct["context_limit"] == 4000
        assert acct["context_truncated"] is True
        before = acct["lore_last_inject_at"]
        dcs.record_lore_inject(1234)
        assert dcs.get_process_accounting()["lore_last_inject_at"] == 1234
        dcs._PROCESS_ACCOUNTING["lore_last_inject_at"] = before  # restore

    def test_status_field_additive(self):
        src = _read("services/status_service.py")
        assert '"context": context_field' in src
        assert "get_process_accounting" in src
        assert "CHAT_CONTEXT_BUDGET_TOKENS" in src


# ── R17: никаких секретов/base_url в ответах графа/Timeline ─────────────────

class TestR17Safe:
    FORBIDDEN = ("api_key", "base_url", "embedding", "authorization",
                 "secret", "last4")

    def test_belief_out_no_secrets(self):
        from web.api import memory_agi as ma
        out = ma._belief_out({
            "id": 1, "chat_id": 1, "fact": "x", "weight": 0.5,
            "importance": 0, "source_ids": "[]",
            "belief_meta": '{"type":"paradigm"}', "status": "confirmed",
            "supersedes": None, "created_at": 0,
        })
        blob = json.dumps(out).lower()
        assert not any(bad in blob for bad in self.FORBIDDEN)

    @pytest.mark.asyncio
    async def test_graph_snapshot_no_secrets(self, db):
        await _seed_graph(db, chat_id=1, nodes=3)
        snap = await db.graph_snapshot(chat_id=1)
        blob = json.dumps(snap).lower()
        assert "api_key" not in blob and "base_url" not in blob
        assert "embedding" not in blob


# ── UI-маркеры (app.js / index.html) ───────────────────────────────────────

class TestUiMarkers:
    def test_app_js_methods(self):
        js = _read("web/app.js")
        for marker in (
            "dreamPhaseBadge: function", "deepPhaseBadge: function",
            "memoryContext: function", "ribbonItemClass: function",
            "_ribbonLoop: function", "fmtClock: function",
            "nostalgiaLabel: function", "loadCognition: async function",
            "loadCognitionStats: async function",
            "loadMemoryWidget: async function",
            "renderCognitionGraph: async function",
            "destroyCognitionGraph: function",
            "ensureVisNetwork: function",
            "startCognitionPolling: function",
            "stopCognitionPolling: function",
            "onVisibilityChange: function",
        ):
            assert marker in js, marker

    def test_app_js_badges_and_polling(self):
        js = _read("web/app.js")
        assert "🌙 Сон активен" in js
        assert "🌌 Глубокий сон активен" in js
        assert "🌙 Лимит исчерпан" in js
        assert "15000" in js                      # polling 15с (F5-Q3)
        assert "document.hidden" in js            # пауза при hidden
        assert "new window.vis.Network" in js
        assert "window.vis.DataSet" in js
        assert "'/static/vendor/vis-network/vis-network.min.js'" in js
        assert "prefers-reduced-motion" in js
        # F6 не сломан: EKG-computed на месте.
        assert "heartbeat: function" in js
        assert "renderUptimeChart" not in js

    def test_app_js_destroy_and_cleanup(self):
        js = _read("web/app.js")
        assert "this.cognitionNetwork.destroy()" in js
        before = js[js.index("beforeUnmount: function"):]
        assert "stopCognitionPolling()" in before
        assert "destroyCognitionGraph()" in before

    def test_app_js_beliefs_lists_scope_to_chat(self):
        """S10.13-5: ленты beliefs/paradigms скоупятся выбранным чатом
        (как cognition/status, stats, timeline, graph)."""
        js = _read("web/app.js")
        block = js[js.index("loadCognition: async function"):
                  js.index("loadMemoryWidget: async function")]
        assert "this._cidQuery(false)" in block
        assert ("'/api/memory/dream/beliefs?kind=belief&limit=30' + cq"
                in block)
        assert ("'/api/memory/dream/beliefs?kind=paradigm&limit=30' + cq"
                in block)

    def test_index_html_markers(self):
        html = _read("web/index.html")
        assert "Мониторинг Интеллекта" in html
        assert "cognition-ribbons" in html
        assert "ribbon-op-50" in html
        assert "cognitionGraph" in html
        assert "Интеллект и Память" in html
        assert "Статистика графа памяти" in html
        assert "timeline-list" in html
        assert "memoryContext" in html
        assert "nostalgiaLabel()" in html

    def test_vis_network_self_host_no_cdn(self):
        vendor = ROOT / "web" / "static" / "vendor" / "vis-network" / \
            "vis-network.min.js"
        assert vendor.exists()
        head = vendor.read_text(encoding="utf-8", errors="ignore")[:400]
        assert "vis-network" in head and "9.1.9" in head
        html = _read("web/index.html")
        # vis-network НЕ подключается статически и НЕ с CDN (lazy self-host).
        assert "unpkg.com/vis-network" not in html
        assert "cdn.jsdelivr.net/npm/vis-network" not in html
        assert '<script src="/static/vendor/vis-network' not in html

    def test_backend_endpoints_present(self):
        src = _read("web/api/memory_agi.py")
        assert 'memory_router.get("/memory/cognition/status")' in src
        assert 'memory_router.get("/memory/graph")' in src
        assert 'memory_router.get("/memory/stats")' in src
        assert 'memory_router.get("/memory/timeline")' in src
        assert "GRAPH_MAX_NODES = 120" in src
        assert "GRAPH_MAX_EDGES = 240" in src
        # beliefs kind-фильтр
        assert 'pattern="^(belief|paradigm|all)$"' in src

    def test_database_helpers_present(self):
        src = _read("services/database.py")
        assert "async def graph_snapshot" in src
        assert "async def graph_stats" in src
        assert "async def last_run_at" in src
        assert "async def sum_dream_tokens" in src

    def test_dream_worker_running_props(self):
        src = _read("services/dream_worker.py")
        assert "def dream_running" in src
        assert "def deep_running" in src
