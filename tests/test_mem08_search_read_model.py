"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-08 — срезы S1+S2: read-модель поиска и
семантических сообществ (backend, без UI).

Контракт: `plans/features/memory-cognitive-02/contracts.md` §4.3–§4.9, §6 C-6,
§9.5 и артефакт S1 `plans/features/memory-cognitive-02/search-read-model.md`.

Проверяется:

* три честных состояния сообществ: таблиц нет / нет активной сборки / есть
  активная сборка — с разными `state`/`reason_code` и без фейковых данных;
* сообщества читаются ТОЛЬКО из `mca_community_builds.status='active'`
  (`superseded`/`building` не попадают никогда), нейтральная подпись честно
  помечена `label_kind="neutral"` и не выдаётся за семантическую категорию;
* существующие поля payload карты не изменились (golden-фикстура
  `tests/fixtures/mem08/cognitive_map_payload_v1.json`: разрешены ровно
  аддитивные `communities` и `sources["communities"]`);
* поиск — тонкий адаптер: вызывается ЕДИНСТВЕННЫЙ
  `mca_retrieval_context.retrieve`, своего SQL-поиска/FTS в адаптере нет;
* исходы различаются: `no_rights` ≠ `no_matches` ≠ `error` ≠ `cursor_stale`;
* курсор: `has_more` ⇔ `next_cursor`, устаревшая ревизия → `cursor_stale`
  с `reason_code='cursor_revision_mismatch'` и без items.

TEST-LIFECYCLE: CONTRACT owner=MEMORY-08 (S1/S2, contracts §4.3–§4.9/§6)
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
import pytest_asyncio

from services import mca_retrieval_context as rc
from services import memory_communities as mcom
from services import memory_contracts as mc
from services import memory_search as ms
from services.database import DatabaseService
from web.api import cognitive_map as cm

CHAT = -1009009
OTHER_CHAT = -1009010
BUILD_ACTIVE = "cb-active"
BUILD_PREV = "cb-prev"

FIXTURE = Path("tests/fixtures/mem08/cognitive_map_payload_v1.json")


# ── фикстуры ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    service = DatabaseService(":memory:")
    await service.initialize()
    yield service
    await service.close()


async def _node(db, chat_id, name, etype="user"):
    return await db.upsert_node(chat_id, name, etype)


async def _add_build(db, *, build_id, status, members, started_at,
                     chat_id=CHAT, prev_build_id=None):
    """Настоящие строки реестра сборок/членства (без выдуманных колонок)."""
    await db.db.execute(
        "INSERT INTO mca_community_builds (build_id, chat_id, algorithm, "
        "algorithm_version, params_json, graph_revision, node_count, "
        "edge_count, prev_build_id, change_summary_json, status, started_at, "
        "finished_at) VALUES (?, ?, 'weighted_modularity_local_moving', '1', "
        "'{}', 'rev', ?, 0, ?, '{}', ?, ?, ?)",
        (build_id, chat_id, len(members), prev_build_id, status, started_at,
         started_at))
    for community_id, nodes in members.items():
        for node_id, weight in nodes:
            await db.db.execute(
                "INSERT INTO mca_community_members (chat_id, build_id, "
                "community_id, node_id, member_weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, build_id, community_id, node_id, weight, started_at))
    await db.db.commit()


async def _seed_active_communities(db):
    """Активная сборка: сообщество из двух связанных узлов + одиночная пара.

    Имена дают СЕМАНТИЧЕСКУЮ подпись только у первого сообщества (есть
    подтверждённая связь); второе остаётся нейтральным `Сообщество N`.
    """
    hub = await _node(db, CHAT, "Кирилл")
    topic = await _node(db, CHAT, "Папаха", "topic")
    other_a = await _node(db, CHAT, "Сосна", "topic")
    other_b = await _node(db, CHAT, "Берег", "topic")
    await db.upsert_edge(hub, topic, "обсуждали", weight_increment=3)
    await db.upsert_edge(other_a, other_b, "рядом", weight_increment=1)
    # Подтверждённое происхождение связи: факт со subject_ref_id+speaker.
    fact_id = await db.insert_graph_fact(
        CHAT, "Кирилл носит папаху", "chat_history", None,
        target_user=None, subject_ref_id=hub, speaker_author_id=42)
    await db.db.execute(
        "UPDATE edges SET fact_id = ? WHERE chat_id = ? AND source_id = ?",
        (fact_id, CHAT, hub))
    await db.db.commit()
    await _add_build(
        db, build_id=BUILD_ACTIVE, status=mcom.STATUS_ACTIVE,
        members={"c1": [(hub, 3.0), (topic, 3.0)],
                 "c2": [(other_a, 1.0), (other_b, 1.0)]},
        started_at=1750000000)
    return {"hub": hub, "topic": topic, "other_a": other_a, "other_b": other_b}


# ── 1. три состояния сообществ ──────────────────────────────────────────────

class TestCommunityStates:
    @pytest.mark.asyncio
    async def test_tables_absent_is_not_empty_success(self, db):
        await _node(db, CHAT, "Хаб")
        await db.db.execute("DROP TABLE mca_community_members")
        await db.db.execute("DROP TABLE mca_community_builds")
        await db.db.commit()

        block = await ms.read_active_communities(db, CHAT)
        assert block["state"] == ms.COMMUNITY_STATE_UNAVAILABLE
        assert block["reason_code"] == ms.COMMUNITY_REASON_TABLES_ABSENT
        assert block["items"] == [] and block["build"] is None

    @pytest.mark.asyncio
    async def test_no_active_build_is_distinct_state(self, db):
        await _node(db, CHAT, "Хаб")
        await _add_build(db, build_id=BUILD_PREV, status=mcom.STATUS_SUPERSEDED,
                         members={"old": [(1, 1.0), (2, 1.0)]},
                         started_at=1740000000)

        block = await ms.read_active_communities(db, CHAT)
        assert block["state"] == ms.COMMUNITY_STATE_NO_ACTIVE_BUILD
        assert block["reason_code"] == ms.COMMUNITY_REASON_NO_ACTIVE_BUILD
        assert block["items"] == []
        assert block["build"] is None, "superseded не выдаётся за активную"

    @pytest.mark.asyncio
    async def test_active_build_payload_fields(self, db):
        ids = await _seed_active_communities(db)

        block = await ms.read_active_communities(db, CHAT)
        assert block["state"] == ms.COMMUNITY_STATE_OK
        assert block["reason_code"] is None
        assert block["build"]["build_id"] == BUILD_ACTIVE
        assert block["build"]["status"] == mcom.STATUS_ACTIVE
        assert block["build"]["algorithm"] == mcom.COMMUNITY_ALGORITHM
        assert block["total"] == 2 and block["shown"] == 2

        by_id = {item["community_id"]: item for item in block["items"]}
        assert set(by_id) == {"c1", "c2"}
        assert by_id["c1"]["member_count"] == 2
        assert by_id["c1"]["label_kind"] == "named"
        assert "Кирилл" in by_id["c1"]["label"]
        assert by_id["c1"]["label"].startswith("Сообщество: ")
        assert block["build"]["build_id"] in by_id["c1"]["label_basis"]
        # Метрики из настоящих связей, а не выдуманные.
        assert by_id["c1"]["metrics"]["confirmed_links"] == 1
        assert by_id["c1"]["metrics"]["legacy_links"] == 0

        # Нейтральная подпись: честный шаблон и явный label_kind.
        assert by_id["c2"]["label_kind"] == "neutral"
        assert by_id["c2"]["label"].startswith(
            mcom.NEUTRAL_LABEL_TEMPLATE.split("{")[0])
        assert by_id["c2"]["dominant_names"] == []

    @pytest.mark.asyncio
    async def test_non_active_build_rows_never_appear(self, db):
        await _seed_active_communities(db)
        # Старая сборка с ДРУГИМ составом: её членство не должно попасть.
        ghost = await _node(db, CHAT, "Призрак")
        await _add_build(db, build_id="cb-ghost", status=mcom.STATUS_BUILDING,
                         members={"ghost": [(ghost, 9.0)]},
                         started_at=1745000000)

        block = await ms.read_active_communities(db, CHAT)
        ids = {item["community_id"] for item in block["items"]}
        assert ids == {"c1", "c2"}
        assert "ghost" not in ids
        assert all(item["member_count"] == 2 for item in block["items"])

    @pytest.mark.asyncio
    async def test_only_active_build_used_when_superseded_follows(self, db):
        await _seed_active_communities(db)
        newer = await _node(db, CHAT, "Новая пара", "topic")
        newer2 = await _node(db, CHAT, "Ещё пара", "topic")
        await _add_build(db, build_id="cb-new", status=mcom.STATUS_SUPERSEDED,
                         members={"c9": [(newer, 1.0), (newer2, 1.0)]},
                         started_at=1760000000)

        block = await ms.read_active_communities(db, CHAT)
        assert block["build"]["build_id"] == BUILD_ACTIVE
        assert {i["community_id"] for i in block["items"]} == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_global_scope_reports_honest_state(self, db):
        await _seed_active_communities(db)
        block = await ms.read_active_communities(db, None)
        assert block["state"] == ms.COMMUNITY_STATE_NO_ACTIVE_BUILD
        assert block["reason_code"] == ms.COMMUNITY_REASON_SCOPE_GLOBAL
        assert block["items"] == []

    @pytest.mark.asyncio
    async def test_map_payload_exposes_communities_block(self, db):
        await _seed_active_communities(db)
        payload = await cm.build_cognitive_map(db, CHAT)
        assert payload["communities"]["state"] == ms.COMMUNITY_STATE_OK
        assert payload["sources"]["communities"] == "loaded"
        assert payload["communities"]["build"]["build_id"] == BUILD_ACTIVE

    @pytest.mark.asyncio
    async def test_map_payload_marks_unavailable_tables(self, db):
        await _node(db, CHAT, "Хаб")
        await db.db.execute("DROP TABLE mca_community_members")
        await db.db.execute("DROP TABLE mca_community_builds")
        await db.db.commit()
        payload = await cm.build_cognitive_map(db, CHAT)
        assert payload["communities"]["state"] == ms.COMMUNITY_STATE_UNAVAILABLE
        assert payload["communities"]["reason_code"] == \
            ms.COMMUNITY_REASON_TABLES_ABSENT


# ── 2. существующие поля карты не изменились (golden-фикстура) ──────────────

CHAT_FIXTURE = -1001
CHAT_FIXTURE_B = -2002


async def _seed_legacy_map(db):
    """Ровно тот сценарий, на котором снята фикстура (до S2)."""
    hub_a = await _node(db, CHAT_FIXTURE, "Хаб")
    topic_a = await _node(db, CHAT_FIXTURE, "Тема", "topic")
    await _node(db, CHAT_FIXTURE, "Одиночка", "topic")
    await db.upsert_edge(hub_a, topic_a, "обсуждали", weight_increment=3)
    hub_b = await _node(db, CHAT_FIXTURE_B, "Хаб")
    topic_b = await _node(db, CHAT_FIXTURE_B, "Тема", "topic")
    await db.upsert_edge(hub_b, topic_b, "обсуждали")

    async def _fact(text, **kwargs):
        fact_id = await db.insert_graph_fact(
            CHAT_FIXTURE, text, "chat_history", None,
            importance=kwargs.get("importance", 5),
            kind=kwargs.get("kind", "fact"),
            message_timestamp=kwargs.get("message_timestamp"),
            supersedes=kwargs.get("supersedes"),
            source_ids=(json.dumps(kwargs["source_ids"])
                        if kwargs.get("source_ids") is not None else None),
            belief_meta=(json.dumps(kwargs["belief_meta"])
                         if kwargs.get("belief_meta") else None))
        created_at = kwargs.get("created_at")
        if created_at is not None:
            await db.db.execute(
                "UPDATE graph_facts SET created_at = ?, last_confirmed_at = ? "
                "WHERE id = ?", (created_at, created_at, fact_id))
            await db.db.commit()
        return fact_id

    old_fact = await _fact("Старый факт про кофе", importance=3,
                           created_at=1740000000,
                           message_timestamp=1740000000)
    new_fact = await _fact("Любит утренний кофе", importance=7,
                           created_at=1750000000,
                           message_timestamp=1750000000,
                           supersedes=old_fact)
    await _fact("Кофе — ритуал", importance=6, kind="belief",
                created_at=1750000200, source_ids=[new_fact, old_fact])
    await _fact("Бережёт утро", importance=9, kind="belief",
                created_at=1750000300, belief_meta={"type": "paradigm"})
    await _fact("Изолированный факт", importance=1, created_at=1750000400)
    await db.db.execute(
        "UPDATE edges SET fact_id = ? WHERE chat_id = ? AND source_id = ?",
        (new_fact, CHAT_FIXTURE, hub_a))
    await db.db.execute(
        "INSERT INTO mca_trait_observations (agent_id, chat_id, dimension, "
        "raw_text, source_refs, subject_status, observed_at, created_at) "
        "VALUES ('bot', ?, 'humor', 'Любит сарказм', '[]', 'self', ?, ?)",
        (CHAT_FIXTURE, 1750000100, 1750000100))
    await db.db.execute(
        "INSERT INTO memory_dream_log (chat_id, run_at, kind, tokens, status) "
        "VALUES (?, ?, 'distilled', 10, 'ok')", (CHAT_FIXTURE, 1750000600))
    await db.db.commit()


def _code_strings(tree) -> list[str]:
    """Строковые константы КОДА (docstrings исключены: в них бывают слова)."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str) and id(node) not in docstrings]


def _normalized_payload(payload: dict) -> dict:
    """Убирает volatile-значения, аддитивные поля S2 и порядок рёбер.

    Порядок внутри `edges` зависит от порядка `source_ids` в строке факта, а
    не от контракта; набор и содержимое проверяются полностью.
    """
    data = json.loads(json.dumps(payload, ensure_ascii=False))
    data.pop("communities", None)
    data.get("sources", {}).pop("communities", None)
    data["generated_at"] = 0
    for edge in data.get("edges") or ():
        provenance = edge.get("provenance") or {}
        if "updated_at" in provenance:
            provenance["updated_at"] = 0
    data["nodes"] = sorted(data.get("nodes") or (), key=lambda n: n["id"])
    data["edges"] = sorted(data.get("edges") or (), key=lambda e: e["id"])
    return data


class TestMapPayloadUnchanged:
    @pytest.mark.asyncio
    async def test_existing_fields_match_golden_fixture(self, db):
        await _seed_legacy_map(db)
        payload = await cm.build_cognitive_map(db, CHAT_FIXTURE, now=1760000000)
        expected = json.loads(FIXTURE.read_text(encoding="utf-8"))

        assert _normalized_payload(payload) == _normalized_payload(expected)
        # Ровно одно аддитивное дополнение верхнего уровня (S2).
        assert set(payload) - set(expected) == {"communities"}
        assert set(payload["sources"]) - set(expected["sources"]) == {
            "communities"}


# ── 3. поиск: единый retrieve, без второго поискового пути ──────────────────

def _candidate(**kwargs):
    base = dict(id="ent:-1:1", entity_type="entity", entity_id="1",
                chat_id=CHAT, score=10.0, channel="entity", preview="Кирилл",
                provenance_backed=True)
    base.update(kwargs)
    return rc.RetrievalCandidate(**base)


def _result(candidates=(), *, status=rc.RETRIEVAL_OK, reason=None,
            ambiguity=(), channels=("entity",)):
    return rc.RetrievalResult(
        status=status, candidates=tuple(candidates),
        channels_used=tuple(channels), reason_code=reason,
        mode="auto", purpose="ui_search", chat_ids=(CHAT,),
        ambiguity=tuple(ambiguity))


class TestSearchUsesSingleRetrieve:
    @pytest.mark.asyncio
    async def test_adapter_calls_shared_retrieve_once(self, db, monkeypatch):
        calls: list = []

        async def fake_retrieve(db_arg, memory, request):
            calls.append(request)
            return _result([_candidate()])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="Кирилл",
                                          chat_id=CHAT)
        assert len(calls) == 1, "адаптер обязан идти через единый retrieve"
        assert calls[0].purpose == mc.MemoryPurpose.UI_SEARCH.value
        assert calls[0].limit == ms.SEARCH_POOL_LIMIT
        assert response.status is mc.SearchStatus.OK
        assert response.items[0].canonical_id == "ent:-1:1"

    def test_adapter_has_no_own_search_sql(self):
        source = Path("services/memory_search.py").read_text(encoding="utf-8")
        assert "mca_retrieval_context" in source and ".retrieve(" in source

        tree = ast.parse(source)
        strings = _code_strings(tree)
        for text in strings:
            assert not re.search(r"\bMATCH\b", text), (
                f"FTS-поиск в адаптере запрещён: {text[:60]!r}")
            for forbidden in ("search_messages_fts", "fts5", "cosine",
                              "embed("):
                assert forbidden not in text, f"второй поиск: {forbidden}"

        allowed_tables = {
            "sqlite_master", "nodes", "edges", "graph_facts",
            mcom.COMMUNITY_BUILDS_TABLE, mcom.COMMUNITY_MEMBERS_TABLE,
            "mca_entity_canonical", "mca_associations",
        }
        selects = []
        for text in strings:
            flat = " ".join(text.split())
            if not flat.upper().startswith("SELECT"):
                continue
            selects.append(flat)
            tables = set(re.findall(r"(?:FROM|JOIN)\s+([A-Za-z_][\w]*)", flat))
            assert tables <= allowed_tables, (
                f"адаптер читает не read-модель: {tables - allowed_tables}")
            assert "vec" not in flat.lower(), "векторный поиск — только retrieve"
        assert selects, "read-модель должна читать существующие таблицы"

    def test_endpoint_delegates_to_adapter(self):
        source = Path("web/api/cognitive_map.py").read_text(encoding="utf-8")
        assert "memory_search.search_memory(" in source
        assert "memory_search.read_active_communities(" in source
        # Второго поискового входа в API нет.
        assert "search_messages_fts" not in source
        assert not re.search(r"\bMATCH\b", source)


# ── 4. исходы: no_rights ≠ no_matches ≠ error ≠ cursor_stale ────────────────

class TestSearchOutcomes:
    @pytest.mark.asyncio
    async def test_no_rights_is_not_no_matches(self, db):
        response = await ms.search_memory(
            db, None, query="Кирилл", chat_id=CHAT,
            allowed_chat_ids=(OTHER_CHAT,))
        assert response.status is mc.SearchStatus.FORBIDDEN
        assert response.query_state is mc.QueryState.NO_RIGHTS
        assert response.reason_code == "no_rights"
        assert response.items == ()

    @pytest.mark.asyncio
    async def test_empty_result_is_no_matches(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([], status=rc.RETRIEVAL_EMPTY,
                           reason="retrieval_empty")

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="ничего",
                                          chat_id=CHAT)
        assert response.status is mc.SearchStatus.EMPTY
        assert response.query_state is mc.QueryState.NO_MATCHES
        assert response.reason_code == "retrieval_empty"

    @pytest.mark.asyncio
    async def test_retrieval_error_is_error_not_empty(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([], status=rc.RETRIEVAL_ERROR,
                           reason="retrieval_error")

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="сбой", chat_id=CHAT)
        assert response.status is mc.SearchStatus.ERROR
        assert response.query_state is mc.QueryState.ERROR
        assert response.reason_code == "retrieval_error"

    @pytest.mark.asyncio
    async def test_untyped_text_matches_are_honest_no_matches(self, db,
                                                              monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate(id="tg:5", entity_type="message",
                                       entity_id="5", channel="lexical",
                                       provenance_backed=False)])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="кофе",
                                          chat_id=CHAT)
        assert response.status is mc.SearchStatus.EMPTY
        assert response.query_state is mc.QueryState.NO_MATCHES
        assert response.reason_code == "untyped_text_matches_only"
        assert response.items == ()
        assert response.debug["untyped_matches"] == 1

    @pytest.mark.asyncio
    async def test_legacy_only_state(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate(id="fact:7", entity_type="graph_fact",
                                       entity_id="7", channel="lexical",
                                       preview="старый факт",
                                       provenance_backed=False)])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="старое",
                                          chat_id=CHAT)
        assert response.status is mc.SearchStatus.LEGACY_ONLY
        assert response.query_state is mc.QueryState.WEAK_LEGACY_ONLY

    @pytest.mark.asyncio
    async def test_invalid_inputs_are_request_errors(self, db):
        for kwargs, code in (
                ({"query": "   "}, "query_empty"),
                ({"query": "x" * 201}, "query_too_long"),
                ({"query": "ок"}, "invalid_limit"),
        ):
            payload = {"query": kwargs.pop("query"), "chat_id": CHAT}
            payload.update(kwargs)
            if code == "invalid_limit":
                payload["limit"] = 21
            with pytest.raises(ms.SearchRequestError) as excinfo:
                await ms.search_memory(db, None, **payload)
            assert excinfo.value.reason_code == code

    @pytest.mark.asyncio
    async def test_malformed_cursor_is_request_error(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate()])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        with pytest.raises(ms.SearchRequestError) as excinfo:
            await ms.search_memory(db, None, query="Кирилл", chat_id=CHAT,
                                   cursor="не-курсор")
        assert excinfo.value.reason_code == "invalid_cursor"


# ── 5. курсор и устаревание ревизии (§4.9) ──────────────────────────────────

class TestCursor:
    @pytest.mark.asyncio
    async def test_pagination_has_more_and_next_cursor_consistent(self, db,
                                                                  monkeypatch):
        pool = [_candidate(id=f"ent:{CHAT}:{n}", entity_id=str(n),
                           preview=f"Узел {n}") for n in range(1, 4)]

        async def fake_retrieve(db_arg, memory, request):
            return _result(pool)

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        first = await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                       limit=2)
        assert [i.canonical_id for i in first.items] == [
            f"ent:{CHAT}:1", f"ent:{CHAT}:2"]
        assert first.has_more is True and first.next_cursor

        second = await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                        limit=2, cursor=first.next_cursor)
        assert [i.canonical_id for i in second.items] == [f"ent:{CHAT}:3"]
        assert second.has_more is False and second.next_cursor is None

    @pytest.mark.asyncio
    async def test_revision_change_yields_cursor_stale(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate(id=f"ent:{CHAT}:{n}", entity_id=str(n),
                                       preview=f"Узел {n}")
                            for n in range(1, 4)])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        first = await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                       limit=2)
        # Ревизия графа изменилась между страницами (новая сущность).
        await _node(db, CHAT, "Новый узел")

        stale = await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                       limit=2, cursor=first.next_cursor)
        assert stale.status is mc.SearchStatus.CURSOR_STALE
        assert stale.reason_code == "cursor_revision_mismatch"
        assert stale.items == () and stale.next_cursor is None
        assert stale.query_state is not mc.QueryState.NO_MATCHES

    @pytest.mark.asyncio
    async def test_cursor_of_another_query_is_rejected(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate(id=f"ent:{CHAT}:{n}", entity_id=str(n))
                            for n in range(1, 4)])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        first = await ms.search_memory(db, None, query="узел", chat_id=CHAT,
                                       limit=2)
        with pytest.raises(ms.SearchRequestError) as excinfo:
            await ms.search_memory(db, None, query="другой запрос",
                                   chat_id=CHAT, limit=2,
                                   cursor=first.next_cursor)
        assert excinfo.value.reason_code == "invalid_cursor"


# ── 6. сообщество в выдаче — только из активной сборки ─────────────────────

class TestCommunitySearchItems:
    @pytest.mark.asyncio
    async def test_community_title_comes_from_active_build_label(self, db,
                                                                 monkeypatch):
        await _seed_active_communities(db)

        async def fake_retrieve(db_arg, memory, request):
            return _result([
                _candidate(id="comm:c1:1", entity_type="community",
                           entity_id="c1", channel="community"),
                _candidate(id="comm:missing:9", entity_type="community",
                           entity_id="missing", channel="community"),
            ])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="папаха",
                                          chat_id=CHAT)
        titles = {item.canonical_id: item.title for item in response.items}
        assert titles["comm:c1"].startswith("Сообщество: ")
        assert "Кирилл" in titles["comm:c1"]
        # Неизвестный/чужой community_id не подписывается выдуманной меткой.
        assert titles["comm:missing"] == "Без названия"
        assert response.debug["community"]["build_id"] == BUILD_ACTIVE

    @pytest.mark.asyncio
    async def test_associations_present_forces_neutral_label(self, db):
        """Пары cooccurrence влияют на подпись сборки → read-модель честно
        не подтверждает семантическую подпись (иначе выдала бы категорию,
        которой сборка не давала)."""
        await _seed_active_communities(db)
        before = await ms.read_active_communities(db, CHAT)
        assert {i["community_id"]: i["label_kind"]
                for i in before["items"]}["c1"] == "named"

        await db.db.execute(
            "INSERT INTO mca_associations (association_id, chat_id, link_type, "
            "a_event_id, b_event_id, status, created_at, updated_at) "
            "VALUES ('a1', ?, 'analogy', 'e1', 'e2', 'accepted', 1, 1)",
            (CHAT,))
        await db.db.commit()

        after = await ms.read_active_communities(db, CHAT)
        c1 = {i["community_id"]: i for i in after["items"]}["c1"]
        assert c1["label_kind"] == "neutral"
        assert "mca_associations" in c1["label_basis"]
        # Метрики по edges остаются реальными, подпись — нет.
        assert c1["metrics"]["confirmed_links"] == 1

    @pytest.mark.asyncio
    async def test_real_retrieve_path_returns_typed_items(self, db):
        """Без подмены retrieve: настоящий единый поиск даёт типизированные
        элементы (никаких сырых сообщений в выдаче)."""
        await db.insert_graph_fact(CHAT, "Лёха обсуждал дроны и оптику",
                                   "chat_history", None, target_user="Лёха")
        response = await ms.search_memory(db, None, query="дроны",
                                          chat_id=CHAT, limit=5)
        assert response.status in (mc.SearchStatus.OK,
                                   mc.SearchStatus.LEGACY_ONLY), response.status
        assert len(response.items) >= 1, "единый поиск не нашёл живой факт"
        fact = response.items[0]
        assert fact.ref_kind is mc.RefKind.FACT
        assert fact.canonical_id.startswith("fact:")
        assert fact.title and "дрон" in fact.title.lower()
        for item in response.items:
            assert item.ref_kind in (mc.RefKind.ENTITY, mc.RefKind.FACT,
                                     mc.RefKind.EPISODE, mc.RefKind.COMMUNITY)
            assert not item.canonical_id.startswith("tg:")
            assert not item.canonical_id.startswith("msg:")

    @pytest.mark.asyncio
    async def test_community_items_absent_without_active_build(self, db,
                                                               monkeypatch):
        await _node(db, CHAT, "Хаб")
        await _add_build(db, build_id=BUILD_PREV, status=mcom.STATUS_SUPERSEDED,
                         members={"old": [(1, 1.0), (2, 1.0)]},
                         started_at=1740000000)

        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate(id="comm:old:1",
                                       entity_type="community",
                                       entity_id="old",
                                       channel="community")])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="папаха",
                                          chat_id=CHAT)
        assert response.items[0].title == "Без названия"
        assert response.debug["community"]["state"] == \
            ms.COMMUNITY_STATE_NO_ACTIVE_BUILD

    @pytest.mark.asyncio
    async def test_ambiguity_is_variants_not_popular_choice(self, db,
                                                            monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result(
                [_candidate()],
                status=rc.RETRIEVAL_OK,
                ambiguity=(
                    {"canonical_id": f"ent:{CHAT}:1", "title": "Кирилл",
                     "discriminator": "участник чата"},
                    {"canonical_id": f"ent:{CHAT}:2", "title": "Кирилл",
                     "discriminator": "другой участник"},
                ))

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        response = await ms.search_memory(db, None, query="Кирилл",
                                          chat_id=CHAT)
        assert response.status is mc.SearchStatus.AMBIGUOUS
        ambiguity = response.items[0].ambiguity
        assert ambiguity is not None and len(ambiguity.variants) == 2
        assert {v.discriminator for v in ambiguity.variants} == {
            "участник чата", "другой участник"}


# ── 7. ACL/RBAC эндпоинта ──────────────────────────────────────────────────

class TestSearchEndpointAccess:
    def test_search_route_registered(self):
        paths = {(route.path, tuple(sorted(route.methods)))
                 for route in cm.cognitive_map_router.routes}
        assert ("/memory/search", ("GET",)) in paths
        assert ("/memory/cognitive-map", ("GET",)) in paths

    @pytest.mark.asyncio
    async def test_non_admin_is_403_before_any_search(self, db, monkeypatch):
        from fastapi import HTTPException
        from web.api import memory_agi

        monkeypatch.setattr(memory_agi, "_is_global_admin",
                            lambda cache, tid: False)
        monkeypatch.setattr(cm, "_db_or_503", lambda: db)
        request = __import__("types").SimpleNamespace(
            app=__import__("types").SimpleNamespace(
                state=__import__("types").SimpleNamespace(cache=object())))
        with pytest.raises(HTTPException) as excinfo:
            await cm.memory_search_endpoint(
                request=request,
                user=__import__("types").SimpleNamespace(id=42),
                q="Кирилл", chat_id=CHAT, limit=None, cursor=None)
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_endpoint_returns_contract_payload(self, db, monkeypatch):
        async def fake_retrieve(db_arg, memory, request):
            return _result([_candidate()])

        monkeypatch.setattr(rc, "retrieve", fake_retrieve)
        monkeypatch.setattr(cm, "_require_global_admin", lambda *a, **k: None)
        monkeypatch.setattr(cm, "_db_or_503", lambda: db)
        body = await cm.memory_search_endpoint(
            request=None, user=None, q="Кирилл", chat_id=CHAT, limit=5,
            cursor=None)
        assert body["status"] == "ok" and body["query_state"] == "candidates"
        assert set(body) == {"status", "reason_code", "query_state", "items",
                            "next_cursor", "has_more", "generation", "scope",
                            "revision", "debug"}
        assert body["scope"] == {"chat_id": CHAT, "mode": "chat",
                                 "partial": False}
