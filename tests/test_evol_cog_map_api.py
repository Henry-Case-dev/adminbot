"""EVOL-COG-MAP (W7-S1) — GET /api/memory/cognitive-map.

TEST-LIFECYCLE: CONTRACT owner=EVOL-COG-MAP (W7-S1)
Контракт: `plans/features/evol/arch/cog-map-contract.md` §2/§5/§6.

Проверяется (реальная in-memory SQLite, без сети/Telegram/LLM):
  * изоляция чатов: узлы чужого чата в payload отсутствуют, а не «скрыты»;
    одинаковые имена в разных чатах НЕ сливаются (чат-квалифицированные id);
  * глобальная область (chat_id=None) — явный агрегат администратора;
  * caps/truncation: класс ≤150, `shown_of`/`truncated` заполнены всегда,
    порядок обрезки — importance → recency → id;
  * `empty` и `degraded` различаются (источник недоступен ≠ данных нет);
  * типизированная модель: стабильные id, раздельные времена, provenance,
    `isolated` без выдуманных рёбер, обоснование ребра (`fact_id`);
  * RBAC — как у остального Memory-API (401/403/200, только global admin);
  * пин-тест: `/api/memory/graph` и `/api/memory/stats` не изменились.

HTTP-тесты используют TestClient со стабом БД (RBAC/форма ответа), данные
проверяются на `build_cognitive_map(db, ...)` и на самом эндпоинте с
подменёнными auth/DI (прецедент `test_webapp_round1015_graph.py`) — это
устраняет перенос aiosqlite-соединения между event-loop'ами.
"""
import json
import re
import types

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient

from web.api import cognitive_map as cm

CHAT_A = -1001
CHAT_B = -2002
CHAT_C = -3003
CHAT_D = -3004
TEST_TOKEN = "123456:TEST_TOKEN_COGMAP"
ADMIN_ID = 5885953495
MODERATOR_ID = 1313107079


# ── фикстуры ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    from services.database import DatabaseService
    service = DatabaseService(":memory:")
    await service.initialize()
    yield service
    await service.close()


async def _node(db, chat_id, name, etype="user"):
    return await db.upsert_node(chat_id, name, etype)


async def _edge(db, source, target, relation="обсуждали", weight=1,
                fact_id=None):
    await db.upsert_edge(source, target, relation, weight_increment=weight,
                         fact_id=fact_id)


async def _fact(db, chat_id, text, *, importance=5, kind="fact",
                created_at=None, message_timestamp=None,
                supersedes=None, source_ids=None, belief_meta=None,
                tg_message_id=None, status="confirmed", origin=None):
    """Факт/убеждение. ``created_at`` выставляется UPDATE-ом: реальный
    `insert_graph_fact` ставит время сам (int(time.time())), а тесту нужен
    управляемый порядок «importance → recency → id».
    """
    fact_id = await db.insert_graph_fact(
        chat_id, text,
        origin or ("derived_belief" if kind == "belief" else "chat_history"),
        None,
        importance=importance,
        kind=kind,
        message_timestamp=message_timestamp,
        tg_message_id=tg_message_id,
        supersedes=supersedes,
        source_ids=(json.dumps(source_ids) if source_ids is not None else None),
        belief_meta=(json.dumps(belief_meta) if belief_meta else None),
        status=status,
    )
    if created_at is not None:
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ?, last_confirmed_at = ? "
            "WHERE id = ?", (created_at, created_at, fact_id))
        await db.db.commit()
    return fact_id


async def _observation(db, chat_id, text, *, observed_at=1750000100,
                       dimension="humor"):
    await db.db.execute(
        "INSERT INTO mca_trait_observations (agent_id, chat_id, dimension, "
        "raw_text, source_refs, subject_status, observed_at, created_at) "
        "VALUES ('bot', ?, ?, ?, ?, 'self', ?, ?)",
        (chat_id, dimension, text, json.dumps([{"chat_id": chat_id}]),
         observed_at, observed_at))
    await db.db.commit()


async def _dream(db, chat_id, run_at, kind, status="ok"):
    await db.db.execute(
        "INSERT INTO memory_dream_log (chat_id, run_at, kind, tokens, "
        "status) VALUES (?, ?, ?, 10, ?)", (chat_id, run_at, kind, status))
    await db.db.commit()


async def _seed_two_chats(db):
    """Чат A: полный набор (рёбра, факты, вера, парадигма, наблюдение, сон).

    Чат B: те же ИМЕНА сущностей (проверка «не сливать чаты») + один факт.
    """
    hub_a = await _node(db, CHAT_A, "Хаб")
    topic_a = await _node(db, CHAT_A, "Тема", "topic")
    lonely_a = await _node(db, CHAT_A, "Одиночка", "topic")
    assert lonely_a  # сирота не попадает в снапшот — рёбер нет
    await _edge(db, hub_a, topic_a, "обсуждали", weight=3)

    hub_b = await _node(db, CHAT_B, "Хаб")
    topic_b = await _node(db, CHAT_B, "Тема", "topic")
    await _edge(db, hub_b, topic_b, "обсуждали")

    old_fact = await _fact(db, CHAT_A, "Старый факт про кофе",
                           importance=3, created_at=1740000000,
                           message_timestamp=1740000000)
    new_fact = await _fact(db, CHAT_A, "Любит утренний кофе",
                           importance=7, created_at=1750000000,
                           message_timestamp=1750000000, tg_message_id=555,
                           supersedes=old_fact)
    belief = await _fact(db, CHAT_A, "Кофе — ритуал", importance=6,
                         kind="belief", created_at=1750000200,
                         source_ids=[new_fact, old_fact, 999999])
    paradigm = await _fact(db, CHAT_A, "Бережёт утро", importance=9,
                           kind="belief", created_at=1750000300,
                           belief_meta={"type": "paradigm"})
    other = await _fact(db, CHAT_A, "Изолированный факт", importance=1,
                        created_at=1750000400)
    fact_b = await _fact(db, CHAT_B, "Факт другого чата", importance=4,
                         created_at=1750000500)

    # Ребро с provenance: факт, породивший связь (edges.fact_id).
    await db.db.execute(
        "UPDATE edges SET fact_id = ? WHERE chat_id = ? AND source_id = ?",
        (new_fact, CHAT_A, hub_a))
    await db.db.commit()

    await _observation(db, CHAT_A, "Любит сарказм")
    await _dream(db, CHAT_A, 1750000600, "distilled")
    return {
        "hub_a": hub_a, "topic_a": topic_a, "hub_b": hub_b, "topic_b": topic_b,
        "old_fact": old_fact, "new_fact": new_fact, "belief": belief,
        "paradigm": paradigm, "other": other, "fact_b": fact_b,
    }


# ── HTTP-стаб ───────────────────────────────────────────────────────────────

class _StubDb:
    """БД-стаб для RBAC/формы: методов нет → все источники `not_loaded`."""

    async def graph_snapshot(self, **kwargs):
        raise RuntimeError("stub: graph недоступен")

    class _Conn:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("stub: SQL недоступен")

    db = _Conn()


def make_init_data(user_id: int = ADMIN_ID) -> str:
    import hashlib
    import hmac
    import time
    import urllib.parse
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHkFg",
        "user": json.dumps({"id": user_id, "first_name": "A"},
                           separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + f"&hash={calc}"


def _hdr(user_id: int = ADMIN_ID) -> dict:
    return {"X-Telegram-Init-Data": make_init_data(user_id)}


@pytest.fixture
def client(monkeypatch):
    from web.app import create_app
    from web.api import deps as deps_mod
    from services.config_cache import ConfigCache
    from services import lore_runtime

    monkeypatch.setattr(deps_mod, "settings",
                        types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
    cache = ConfigCache(pg=None, retry_attempts=1, retry_delay=0)
    app = create_app(cache)
    lore_runtime.set_lore_components(db=_StubDb())
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        lore_runtime.reset_lore_runtime()


# ── payload: изоляция и модель ──────────────────────────────────────────────

class TestChatIsolation:
    @pytest.mark.asyncio
    async def test_other_chat_nodes_absent(self, db):
        await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, CHAT_A)

        chat_ids = {node["chat_id"] for node in payload["nodes"]}
        assert chat_ids == {CHAT_A}, "в payload попал чужой чат"
        assert all(f":{CHAT_A}:" in node["id"] for node in payload["nodes"])
        assert not any(str(CHAT_B) in node["id"] for node in payload["nodes"])
        # чужой факт отсутствует, а не «скрыт»
        assert payload["scope"] == {"mode": "chat", "chat_id": CHAT_A}

    @pytest.mark.asyncio
    async def test_same_names_do_not_merge_in_global(self, db):
        seeded = await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, None)

        assert payload["scope"] == {"mode": "global", "chat_id": None}
        hubs = [n for n in payload["nodes"]
                if n["kind"] == "entity" and n["title"] == "Хаб"]
        assert len(hubs) == 2, "одинаковые имена разных чатов слились"
        assert {n["chat_id"] for n in hubs} == {CHAT_A, CHAT_B}
        assert len({n["id"] for n in hubs}) == 2, "id должны быть разными"

        facts = {n["id"] for n in payload["nodes"] if n["kind"] == "fact"}
        # id — типизированный ключ, а не индекс массива: chat + id строки БД
        assert all(re.fullmatch(r"fact:-?\d+:\d+", fid) for fid in facts)
        assert f"fact:{CHAT_A}:{seeded['new_fact']}" in facts
        assert f"fact:{CHAT_B}:{seeded['fact_b']}" in facts
        assert f"fact:{CHAT_A}:{seeded['fact_b']}" not in facts


class TestModelShape:
    @pytest.mark.asyncio
    async def test_payload_contract_keys(self, db):
        await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, CHAT_A)

        assert payload["version"] == cm.PAYLOAD_VERSION
        assert isinstance(payload["generated_at"], int)
        assert payload["state"] in {"ok", "partial", "empty", "degraded"}
        assert payload["degraded"] == {"active": False, "not_loaded": []}
        assert payload["caps"]["nodes"] == cm.GRAPH_MAX_NODES == 800
        assert payload["caps"]["edges"] == cm.GRAPH_MAX_EDGES == 2400
        assert payload["caps"]["per_class"] == cm.GRAPH_SEED_NODES == 150
        assert set(payload["truncated"]) >= {"nodes", "edges", "by_class"}
        shown = payload["shown_of"]
        assert shown["nodes"] == len(payload["nodes"])
        assert shown["edges"] == len(payload["edges"])
        assert set(shown["by_kind"]) == {"fact", "belief", "paradigm",
                                         "observation", "evolution_event",
                                         "entity"}
        # payload сериализуем в JSON без потерь (никаких datetime/объектов)
        assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload

    @pytest.mark.asyncio
    async def test_node_fields_are_honest(self, db):
        seeded = await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, CHAT_A, now=1762000000)
        assert payload["generated_at"] == 1762000000

        by_id = {node["id"]: node for node in payload["nodes"]}
        fact_id = f"fact:{CHAT_A}:{seeded['new_fact']}"
        node = by_id[fact_id]
        assert node["kind"] == "fact"
        assert node["text"] == "Любит утренний кофе"
        assert node["status"] == "confirmed"
        # времена разделены: произошло ≠ сохранено ≠ подтверждено
        assert node["time"]["occurred_at"] == 1750000000
        assert node["time"]["saved_at"] == 1750000000
        assert node["time"]["observed_at"] is None
        assert node["time"]["updated_at"] is None
        assert node["provenance"]["message_id"] == 555
        assert node["provenance"]["chat_id"] == CHAT_A
        assert node["provenance"]["version_of"] == seeded["old_fact"]
        assert node["metrics"]["importance"] == 7
        # confidence/strength/freshness не рассчитываются
        for missing in ("confidence", "strength", "freshness"):
            assert missing not in node["metrics"]
            assert missing not in node

        paradigm_node = by_id[f"paradigm:{CHAT_A}:{seeded['paradigm']}"]
        assert paradigm_node["provenance"]["belief_meta_type"] == "paradigm"
        assert by_id[f"belief:{CHAT_A}:{seeded['belief']}"]["kind"] == "belief"

        # entity-узлы не выдумывают времена
        entity = next(n for n in payload["nodes"] if n["kind"] == "entity")
        assert entity["time"] == {"occurred_at": None, "observed_at": None,
                                 "saved_at": None, "confirmed_at": None,
                                 "updated_at": None}

    @pytest.mark.asyncio
    async def test_edges_have_provenance_and_no_invented_links(self, db):
        seeded = await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, CHAT_A)
        node_ids = {node["id"] for node in payload["nodes"]}
        assert payload["edges"], "записанные связи потерялись"

        for edge in payload["edges"]:
            assert edge["from"] in node_ids and edge["to"] in node_ids
            assert isinstance(edge["relation"], str) and edge["relation"]
            assert edge["provenance"], "ребро без provenance"

        recorded = [e for e in payload["edges"] if not e["derived"]]
        assert len(recorded) == 1, "в чате A ровно одна записанная связь"
        assert recorded[0]["justification_recorded"] is True
        assert recorded[0]["provenance"]["fact_id"] == seeded["new_fact"]

        revisions = [e for e in payload["edges"]
                     if e["relation"] == "revised_by"]
        assert len(revisions) == 1
        assert revisions[0]["from"] == f"fact:{CHAT_A}:{seeded['old_fact']}"
        assert revisions[0]["to"] == f"fact:{CHAT_A}:{seeded['new_fact']}"
        # обоснование версии записано самой записью supersedes
        assert revisions[0]["provenance"]["basis"] == "supersedes"

        derived = [e for e in payload["edges"]
                   if e["relation"] == "derived_from"]
        assert any(e["from"].startswith(f"belief:{CHAT_A}:") for e in derived), \
            "belief → source fact по реальным source_ids не построен"
        assert payload["shown_of"]["unresolved_refs"] >= 1, \
            "source_ids на несуществующий факт не отмечен"

        # изолированные узлы остаются изолированными (без выдуманных рёбер)
        by_id = {node["id"]: node for node in payload["nodes"]}
        assert by_id[f"fact:{CHAT_A}:{seeded['other']}"]["isolated"] is True
        assert by_id[f"paradigm:{CHAT_A}:{seeded['paradigm']}"]["isolated"] is True
        assert by_id[f"fact:{CHAT_A}:{seeded['new_fact']}"]["isolated"] is False

    @pytest.mark.asyncio
    async def test_evolution_events_only_real_records(self, db):
        await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, CHAT_A)
        events = [n for n in payload["nodes"]
                  if n["kind"] == "evolution_event"]
        records = {e["provenance"]["record"] for e in events}
        assert "memory_dream_log" in records
        assert "graph_facts.supersedes" in records
        titles = " ".join(e["title"] for e in events)
        assert "Цикл памяти" in titles
        assert payload["shown_of"]["by_kind"]["observation"]["shown"] == 1


# ── caps / truncation ──────────────────────────────────────────────────────

class TestCaps:
    @pytest.mark.asyncio
    async def test_fact_class_truncated_by_importance(self, db):
        ids = []
        for i in range(160):
            ids.append(await _fact(db, CHAT_A, f"Факт номер {i}",
                                   importance=(i % 10) + 1,
                                   created_at=1750000000 + i))
        payload = await cm.build_cognitive_map(db, CHAT_A)

        facts = [n for n in payload["nodes"] if n["kind"] == "fact"]
        assert len(facts) == cm.GRAPH_SEED_NODES == 150
        assert payload["shown_of"]["by_kind"]["fact"] == {
            "shown": 150, "total": 160, "truncated": True}
        assert payload["truncated"]["nodes"] is True
        assert payload["truncated"]["by_class"]["fact"] is True
        assert payload["state"] == "partial"
        # порядок обрезки: importance DESC, затем recency DESC — самые важные
        # и свежие остались, самый старый факт выпал.
        importances = [n["metrics"]["importance"] for n in facts]
        assert importances == sorted(importances, reverse=True), \
            "порядок обрезки нарушен (класс → importance → recency → id)"
        kept = {n["id"] for n in facts}
        assert f"fact:{CHAT_A}:{ids[0]}" not in kept
        assert f"fact:{CHAT_A}:{ids[-1]}" in kept

    @pytest.mark.asyncio
    async def test_node_and_edge_caps_respected(self, db):
        await _seed_two_chats(db)
        payload = await cm.build_cognitive_map(db, None)
        assert len(payload["nodes"]) <= payload["caps"]["nodes"]
        assert len(payload["edges"]) <= payload["caps"]["edges"]
        # каждый когнитивный класс не больше 150
        counts = {}
        for node in payload["nodes"]:
            counts[node["kind"]] = counts.get(node["kind"], 0) + 1
        for kind in ("fact", "belief", "paradigm", "observation",
                     "evolution_event"):
            assert counts.get(kind, 0) <= cm.GRAPH_SEED_NODES

    @pytest.mark.asyncio
    async def test_entity_neighbourhood_is_reported_partial(self, db):
        """B1: снапшот отдаёт окрестность 150 сидов из 300 сущностей цепочки —
        ответ обязан быть `partial` с честным `by_kind.entity`, а не `ok`."""
        nodes = []
        for i in range(300):
            nodes.append(await _node(db, CHAT_C, f"Узел {i}", "topic"))
        for i in range(len(nodes) - 1):
            await _edge(db, nodes[i], nodes[i + 1], "связь")

        payload = await cm.build_cognitive_map(db, CHAT_C)
        entity = payload["shown_of"]["by_kind"]["entity"]
        assert entity["total"] == 300
        assert 0 < entity["shown"] < entity["total"], \
            "снапшот вернул всю цепочку — фикстура не воспроизводит дефект"
        assert entity["truncated"] is True
        assert payload["truncated"]["nodes"] is True
        assert payload["truncated"]["by_class"]["entity"] is True
        assert payload["shown_of"]["totals"]["nodes"] >= 300
        # рёбра — то же правило: показано меньше, чем записано
        assert payload["shown_of"]["totals"]["edges"] > payload["shown_of"]["edges"]
        assert payload["truncated"]["edges"] is True
        assert payload["state"] == "partial", \
            "неполная карта не имеет права называться ok"

    @pytest.mark.asyncio
    async def test_fully_loaded_small_chat_is_ok(self, db):
        """Обратная сторона правила: маленький полностью загруженный чат —
        по-прежнему `ok` (иначе «partial» перестал бы что-либо значить)."""
        hub = await _node(db, CHAT_D, "Хаб")
        topic = await _node(db, CHAT_D, "Тема", "topic")
        await _edge(db, hub, topic, "обсуждали")
        fact = await _fact(db, CHAT_D, "Единственный факт", importance=5)
        assert fact

        payload = await cm.build_cognitive_map(db, CHAT_D)
        assert payload["state"] == "ok"
        assert payload["truncated"]["nodes"] is False
        assert payload["truncated"]["edges"] is False
        assert payload["shown_of"]["by_kind"]["entity"] == {
            "shown": 2, "total": 2, "truncated": False}
        assert payload["shown_of"]["totals"]["nodes"] == len(payload["nodes"])
        assert payload["shown_of"]["totals"]["edges"] == len(payload["edges"])

    @pytest.mark.asyncio
    async def test_orphan_entity_is_reported_honestly(self, db):
        """Узел без рёбер снапшот отбрасывает — это тоже неполнота, и она
        обязана попадать в `truncated`, а не выдаваться за полную карту."""
        await _seed_two_chats(db)   # в чате A есть сущность «Одиночка» без рёбер
        payload = await cm.build_cognitive_map(db, CHAT_A)

        entity = payload["shown_of"]["by_kind"]["entity"]
        assert entity["shown"] == 2 and entity["total"] == 3
        assert entity["truncated"] is True
        assert payload["truncated"]["by_class"]["entity"] is True
        assert payload["state"] == "partial"


# ── empty vs degraded ─────────────────────────────────────────────────────

class TestStates:
    @pytest.mark.asyncio
    async def test_global_decay_run_is_not_chat_zero(self, db):
        """`memory_dream_log.chat_id = 0` — системный прогон decay, не «чат 0»."""
        hub = await _node(db, CHAT_A, "Хаб")
        topic = await _node(db, CHAT_A, "Тема", "topic")
        await _edge(db, hub, topic, "обсуждали")
        await _dream(db, 0, 1750000700, "decay_run")

        chat_payload = await cm.build_cognitive_map(db, CHAT_A)
        assert not [n for n in chat_payload["nodes"]
                    if n["kind"] == "evolution_event"], \
            "системный прогон попал в карту конкретного чата"

        global_payload = await cm.build_cognitive_map(db, None)
        events = [n for n in global_payload["nodes"]
                  if n["kind"] == "evolution_event"]
        assert len(events) == 1
        node = events[0]
        assert node["id"].startswith("evt:global:dream:")
        assert "evt:0:" not in node["id"], "служебная запись выдана за «чат 0»"
        assert node["scope"] == "global"
        assert node["chat_id"] is None
        assert node["provenance"]["chat_id"] is None

    @pytest.mark.asyncio
    async def test_empty_is_not_degraded(self, db):
        payload = await cm.build_cognitive_map(db, CHAT_A)
        assert payload["state"] == "empty"
        assert payload["nodes"] == [] and payload["edges"] == []
        assert payload["degraded"] == {"active": False, "not_loaded": []}
        assert set(payload["sources"].values()) == {"loaded"}
        assert payload["shown_of"]["totals"]["nodes"] == 0

    @pytest.mark.asyncio
    async def test_degraded_source_is_named(self, db, monkeypatch):
        await _seed_two_chats(db)

        async def _boom(**kwargs):
            raise RuntimeError("graph недоступен")

        monkeypatch.setattr(db, "graph_snapshot", _boom)
        payload = await cm.build_cognitive_map(db, CHAT_A)
        assert payload["state"] == "degraded"
        assert payload["degraded"]["active"] is True
        assert "graph" in payload["degraded"]["not_loaded"]
        assert payload["sources"]["graph"] == "not_loaded"
        # остальные источники прочитаны — данные фактов не потеряны
        assert payload["sources"]["facts"] == "loaded"
        assert any(n["kind"] == "fact" for n in payload["nodes"])

    @pytest.mark.asyncio
    async def test_sql_failure_degrades_class_only(self, db, monkeypatch):
        await _seed_two_chats(db)
        original = db.db.execute

        async def _flaky(sql, *args, **kwargs):
            if "graph_facts" in " ".join(str(sql).split()):
                raise RuntimeError("facts read failed")
            return await original(sql, *args, **kwargs)

        monkeypatch.setattr(db.db, "execute", _flaky)
        payload = await cm.build_cognitive_map(db, CHAT_A)
        assert payload["state"] == "degraded"
        assert "facts" in payload["degraded"]["not_loaded"]
        assert payload["shown_of"]["by_kind"]["fact"]["shown"] == 0
        assert payload["edges"] or payload["nodes"], "упавший класс не убил карту"


# ── эндпоинт: RBAC, wiring, пин-тесты ─────────────────────────────────────

class TestEndpoint:
    def test_401_without_init_data(self, client):
        assert client.get("/api/memory/cognitive-map").status_code == 401

    def test_403_for_non_admin(self, client, monkeypatch):
        from web.api import memory_agi
        monkeypatch.setattr(memory_agi, "_is_global_admin",
                            lambda cache, tid: tid != MODERATOR_ID)
        resp = client.get("/api/memory/cognitive-map", headers=_hdr(MODERATOR_ID))
        assert resp.status_code == 403

    def test_admin_gets_payload_even_if_sources_fail(self, client):
        resp = client.get("/api/memory/cognitive-map", headers=_hdr())
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == cm.PAYLOAD_VERSION
        assert body["state"] == "degraded"
        assert body["degraded"]["active"] is True
        assert "graph" in body["degraded"]["not_loaded"]
        assert body["nodes"] == [] and body["edges"] == []

    @pytest.mark.asyncio
    async def test_endpoint_passes_chat_scope(self, db, monkeypatch):
        await _seed_two_chats(db)
        monkeypatch.setattr(cm, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(cm, "_db_or_503", lambda: db)
        body = await cm.memory_cognitive_map(request=None, user=None,
                                             chat_id=CHAT_A)
        assert body["scope"] == {"mode": "chat", "chat_id": CHAT_A}
        assert {n["chat_id"] for n in body["nodes"]} == {CHAT_A}

    @pytest.mark.asyncio
    async def test_endpoint_requires_global_admin(self, db, monkeypatch):
        from web.api import memory_agi
        monkeypatch.setattr(memory_agi, "_is_global_admin",
                            lambda cache, tid: False)
        monkeypatch.setattr(cm, "_db_or_503", lambda: db)
        fake_request = types.SimpleNamespace(
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(cache=object())))
        with pytest.raises(HTTPException) as excinfo:
            await cm.memory_cognitive_map(
                request=fake_request,
                user=types.SimpleNamespace(id=MODERATOR_ID),
                chat_id=None)
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_legacy_graph_and_stats_endpoints_unchanged(self, db,
                                                              monkeypatch):
        """Пин-тест: старые /memory/graph и /memory/stats не изменились."""
        from web.api import memory_agi

        monkeypatch.setattr(memory_agi, "_require_global_admin",
                            lambda *a, **k: None)
        monkeypatch.setattr(memory_agi, "_db_or_503", lambda: db)
        seeded = await _seed_two_chats(db)
        graph = await memory_agi.memory_graph(request=None, user=None,
                                              chat_id=CHAT_A)
        assert set(graph) == {"nodes", "edges", "truncated", "limits"}
        assert graph["limits"] == {"nodes": 800, "edges": 2400}
        assert all(set(n) == {"id", "label", "group", "degree"}
                   for n in graph["nodes"])
        assert all(set(e) == {"from", "to", "label", "weight"}
                   for e in graph["edges"])

        stats = await memory_agi.memory_stats(request=None, user=None,
                                              chat_id=CHAT_A)
        assert set(stats) == {"facts", "beliefs", "archived_beliefs",
                              "protected_facts", "paradigms", "memes",
                              "graph_nodes", "graph_edges", "relation_types",
                              "bot_self_replies"}
        assert stats["facts"] == 3, "счётчик фактов изменился"
        assert stats["paradigms"] == 1
        assert stats["beliefs"] == 1
        assert seeded["fact_b"]  # данные чата B не влияют на счётчики чата A


# ── маркеры реализации (статические инварианты слайса) ────────────────────

class TestMarkers:
    def test_router_registered_once(self):
        from pathlib import Path
        source = Path("web/app.py").read_text(encoding="utf-8")
        assert source.count("include_router(cognitive_map_router") == 1
        assert "from web.api.cognitive_map import cognitive_map_router" in source

    def test_no_new_store_and_no_llm(self):
        from pathlib import Path
        source = Path("web/api/cognitive_map.py").read_text(encoding="utf-8")
        for forbidden in ("CREATE TABLE", "INSERT INTO", "UPDATE ",
                          "DELETE FROM", "embedding", "llm", "openai"):
            assert forbidden not in source, f"в API не должно быть {forbidden}"
        assert "graph_snapshot" in source, "топология — из существующего снапшота"
        assert "GRAPH_MAX_NODES" in source and "GRAPH_MAX_EDGES" in source
