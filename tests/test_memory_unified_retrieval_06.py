"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-06 — единый retrieval ответного пути.

Источник: `plans/features/memory-cognitive-02/contracts.md` §4.4 (расширение
`retrieve()`, а не второй поиск), §7.1 (запрос, три режима, uid ≠ nodes.id),
§7.2 (человеческий `summary_text`), §7.3 (factcheck ≠ память), §7.4 (никаких
квот по классам), §7.5 (`get_user_context`, `relationships` не деградирует).

Покрываемые требования:
* MEM-06.1/06.3 — exact/FTS/vector/reply/episode/entity собираются ОДНИМ
  `retrieve()`; второго поискового пути нет (AST-гвардия + счётчик вызовов);
* MEM-06.2 — схема запроса: chat_ids (ACL), purpose, intent, subject ids;
* MEM-06.4 — типизированный ранг (доверие источника, свежесть, identity);
* MEM-06.5 — отсутствие фиксированных квот по классам;
* MEM-06.6 — режимы `specific`/`episodic`/`thematic`;
* MEM-06.7 — гейты неоднозначности и уместности («память не уместна»);
* MEM-06.8 — `summary_text` с датой/автором без внутренних id;
* MEM-06.9 — factcheck не переписывает статус памяти;
* MEM-06.10 — все шесть purposes, `relationships` с основанием ребра;
* квота-архив (`archived_fact`) невидим обычной выдаче и виден только
  явному историческому пути.
"""
from __future__ import annotations

import ast
import datetime
import hashlib
import inspect
import json
import re
import time

import pytest

from services import mca_retrieval_context as rc
from services.database import DatabaseService
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.tool_schemas import MEMORY_LOOKUP_TOOL_NAME

_INTERNAL_RE = re.compile(
    r"(node_id|edge_id|source_ref_id|chat_id|cosine|channel=|ent:|fact:|"
    r"tg:|msg:|episode:|comm:)")


# ── фейки каналов (без второго поиска: только контрактные методы) ─────────


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def fetchall(self):
        return list(self._rows)

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeFacadeShell:
    """Минимальный `db.db` для фасада эпизодов mca-05 (legacy-совместимость).

    Фасад активен по умолчанию; его чтение нового store на двойнике пусто,
    поэтому эпизоды приходят существующим legacy-контрактом."""

    def __init__(self, legacy_rows):
        self._legacy = list(legacy_rows)

    async def execute(self, sql, params=()):
        text = str(sql)
        if "FROM lore_stories" in text:
            return _FakeCursor(self._legacy)
        if "sqlite_master" in text:
            return _FakeCursor([])
        return _FakeCursor([])


class _FakeDB:
    def __init__(self, *, messages=(), facts=(), episodes=(), nodes=(),
                 generation=None):
        self._messages = list(messages)
        self._facts = list(facts)
        self._episodes = list(episodes)
        self._nodes = list(nodes)
        self._generation = generation
        self.archival = []
        self.db = _FakeFacadeShell(self._episodes)

    async def search_messages_fts(self, chat_id, match, limit):
        return self._messages

    async def search_graph_facts_fts(self, chat_id, match, limit, now_ts,
                                     include_direct_reply=False,
                                     include_archived=False, **_kw):
        self.archival.append(bool(include_archived))
        return self._facts

    async def list_lore_stories(self, chat_id, limit=200):
        return self._episodes

    async def get_nodes_by_ids(self, chat_id, node_ids):
        ids = {int(n) for n in node_ids}
        return [row for row in self._nodes if int(row["id"]) in ids]

    async def get_active_embedding_generation(self, index_name):
        return self._generation


class _FakeMemory:
    def __init__(self, vec=()):
        self._vec = list(vec)
        self.archival = []

    async def retrieve_fact_candidates(self, chat_id, query, *, limit,
                                       include_archived=False, **_kw):
        self.archival.append(bool(include_archived))
        return self._vec


def _msg(i, text, ts, uid=7, tg=None):
    return {"id": i, "chat_id": -100, "text": text, "timestamp": ts,
            "user_id": uid, "tg_message_id": tg}


# ── MEM-06.1/06.3 + квота-архив: один retrieval, архив невидим ─────────────


@pytest.mark.asyncio
async def test_quota_archived_fact_invisible_until_historical_request(tmp_path):
    """`archived_fact` (вытеснено квотой) не попадает в обычную выдачу, но
    находится явным историческим запросом (`include_archived=True`)."""
    db = DatabaseService(str(tmp_path / "arch06.db"))
    await db.initialize()
    try:
        live = await db.insert_graph_fact(
            -100, "живой факт про дроны", "chat_history", None,
            target_user="Лёха")
        archived = await db.insert_graph_fact(
            -100, "архивный факт про дроны", "chat_history", None,
            target_user="Лёха")
        assert await db.archive_graph_fact_for_quota(
            archived, -100, "Лёха") is True

        ordinary = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=-100, query="дроны", top_k=10))
        ids = {c.id for c in ordinary.candidates}
        assert f"fact:{live}" in ids
        assert f"fact:{archived}" not in ids

        historical = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=-100, query="дроны", top_k=10, include_archived=True))
        assert f"fact:{archived}" in {c.id for c in historical.candidates}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reply_and_context_paths_never_request_archives(monkeypatch):
    """Изоляция архива (структурная гвардия, фикс ревью): обычные пути —
    reply, шесть context-purpose, инициатива и статистика — вызывают
    `retrieve` с `include_archived=False`; явный исторический путь
    (`dig_into_lore`) передаёт True в канал graph_facts. Гвардия падает, если
    True «протечёт» в обычный путь через переменную, а не литерал — читается
    фактическое значение запроса/канала, а не текст исходника."""
    import services.direct_chat_service as dcs
    from services import chat_statistics
    from services import mca_exploration as exploration

    requests: list = []
    real = rc.retrieve

    async def _spy(db, memory, request):
        requests.append(request)
        return await real(db, memory, request)

    monkeypatch.setattr(rc, "retrieve", _spy)

    def _assert_ordinary(label: str):
        assert requests, f"{label}: retrieval не вызван"
        assert all(r.include_archived is False for r in requests), (
            f"{label}: архив попал в обычный путь → "
            f"{[r.include_archived for r in requests]}")

    # (1) reply (direct-RAG)
    monkeypatch.setattr(dcs, "hot", _Hot())
    monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
    svc = _reply_service(_ReplyDB(_reply_rows()),
                         _ReplyMemory(_reply_rows()))
    block, _hint = await svc._build_rag_block(-100, _Msg("про дроны"), "")
    assert "любит дроны" in block
    _assert_ordinary("reply")

    # (2) шесть context-purpose
    router = _router(db=_LookupDB())
    for purpose in ("general", "identity", "appearance", "speech_style",
                    "biography", "relationships"):
        requests.clear()
        await router.dispatch(MEMORY_LOOKUP_TOOL_NAME,
                              {"person": "Лёха", "purpose": purpose},
                              ToolContext(-100, "q", user_id=5))
        _assert_ordinary(f"context:{purpose}")

    # (3) инициатива / (4) статистика: обычный поиск, без архива
    requests.clear()
    await exploration.select_memory_recall_candidates(
        _ReplyDB([]), None, chat_id=-100, query="дроны", top_k=4)
    _assert_ordinary("initiative")
    requests.clear()
    await chat_statistics.collect_candidates(
        _ReplyDB([]), None, chat_id=-100, query="дроны", top_k=4)
    _assert_ordinary("chat_statistics")

    # (5) явный исторический путь: dig_into_lore передаёт True в канал
    archived_calls: list = []

    class _DigDB(_ReplyDB):
        async def search_graph_facts_fts(self, chat_id, match, limit, now_ts,
                                         include_direct_reply=False,
                                         include_archived=False,
                                         include_self=False, **_kw):
            archived_calls.append(bool(include_archived))
            return []

    class _DigMemory:
        db = _DigDB([])

        async def search_long_term(self, chat_id, terms, limit):
            return []

    dig_router = ToolRouter(ToolDeps(search=None, memory=_DigMemory(),
                                     aliases=_Aliases({"5": "Лёха"}),
                                     db=_DigDB([])))
    raw = await dig_router._dig_into_lore(
        {"query": "дроны", "mode": "facts"},
        ToolContext(-100, "дроны", user_id=5))
    assert raw                                       # путь исполнен
    assert archived_calls and all(archived_calls)    # исторический = True
    # негативный контроль: гвардия видит РЕАЛЬНОЕ значение поля запроса
    assert rc.RetrievalRequest(chat_id=-100, query="q",
                               include_archived=True).include_archived is True


@pytest.mark.asyncio
async def test_entity_channel_and_uid_vs_node_id_separation():
    """§7.1: `subject_node_ids` (`nodes.id`) питает entity-канал и НЕ
    смешивается с `subject_entity_ids` (Telegram uid)."""
    db = _FakeDB(nodes=[{"id": 5, "entity_name": "Дроны",
                         "entity_type": "topic", "canonical_node_id": 42}])
    result = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", subject_node_ids=(5,), top_k=5))
    entity = [c for c in result.candidates if c.channel == "entity"]
    assert entity and "entity" in result.channels_used
    # канонический id C-1 (redirect member→canonical), не member
    assert entity[0].id == "ent:-100:42"
    assert entity[0].subject_node_id == 42

    # uid, случайно равный nodes.id, не даёт exact-subject prior
    node_only = rc.RetrievalCandidate(
        id="fact:1", entity_type="graph_fact", entity_id="1", score=60.0,
        channel="vector", subject_node_id=5, provenance_backed=True)
    other = rc.RetrievalCandidate(
        id="fact:2", entity_type="graph_fact", entity_id="2", score=61.0,
        channel="vector", subject_entity_id=5, provenance_backed=True)
    ordered = rc.apply_identity_prior([node_only, other],
                                      subject_entity_ids=(5,))
    # node id 5 не считается совпадением uid → предпочтение у uid-совпадения
    assert ordered[0].id == "fact:2"
    ordered_nodes = rc.apply_identity_prior([node_only, other],
                                            subject_node_ids=(5,))
    assert ordered_nodes[0].id == "fact:1"


# ── MEM-06.4: типизированное ранжирование ─────────────────────────────────


def test_typed_rank_trust_and_freshness_beat_stale_cosine():
    """Старый сомнительный факт не выигрывает у свежего точного assertion
    только за счёт «похожести»; канальный вес остаётся доминирующим."""
    now = int(time.time())
    stale_legacy = rc.RetrievalCandidate(
        id="fact:old", entity_type="graph_fact", entity_id="old", score=79.0,
        channel="lexical", sent_at=now - 4000 * 86400,
        provenance_backed=False)
    fresh_fact = rc.RetrievalCandidate(
        id="fact:new", entity_type="graph_fact", entity_id="new", score=60.0,
        channel="vector", sent_at=now, provenance_backed=True)
    request = rc.RetrievalRequest(chat_id=-100, query="дроны")
    old_score = rc.typed_rank_score(stale_legacy, request, "auto", now=now)
    new_score = rc.typed_rank_score(fresh_fact, request, "auto", now=now)
    assert new_score > old_score
    # более сильный канал всё равно не перебивается бонусами свежести
    exact = rc.RetrievalCandidate(
        id="tg:9", entity_type="message", entity_id="9", score=100.0,
        channel="exact", sent_at=now - 300 * 86400)
    assert rc.typed_rank_score(exact, request, "auto", now=now) > new_score


def test_identity_prior_prefers_requested_subject():
    """Sub-контракт MEM-06.4: тождество говорящего/субъекта сильнее proximity."""
    wrong = rc.RetrievalCandidate(
        id="fact:wrong", entity_type="graph_fact", entity_id="w", score=100.0,
        channel="vector", subject_entity_id=999, provenance_backed=True)
    right = rc.RetrievalCandidate(
        id="fact:right", entity_type="graph_fact", entity_id="r", score=60.0,
        channel="lexical", subject_entity_id=2, provenance_backed=True)
    out = rc.apply_identity_prior([wrong, right], subject_entity_ids=(2,))
    assert out[0].id == "fact:right"


# ── MEM-06.6: три режима ──────────────────────────────────────────────────


def _mode_data():
    now = int(time.time())
    return (
        _FakeDB(
            messages=[_msg(1, "дроны летали вчера", now - 100, tg=55)],
            episodes=[{"id": 5, "topic": "про дроны", "story": "давно",
                       "last_ts": 1000}],
            nodes=[{"id": 77, "entity_name": "Дроны",
                    "entity_type": "topic", "canonical_node_id": None}],
            generation={"fingerprint": "FP"}),
        _FakeMemory(vec=[{"id": 3, "fact": "дроны и оптика", "rag_ts": 3000,
                          "tg_message_id": None, "item_id": "fact:3",
                          "subject_ref_id": 9}]),
    )


@pytest.mark.asyncio
async def test_three_modes_are_distinct_and_deterministic():
    db, memory = _mode_data()

    specific = await rc.retrieve(db, memory, rc.RetrievalRequest(
        chat_id=-100, query="дроны", mode="specific",
        subject_node_ids=(77,), top_k=10))
    assert specific.mode == "specific"
    # эпизоды не подмешиваются в точечный поиск без reply-связи
    assert "episode" not in specific.channels_used
    assert "entity" in specific.channels_used

    episodic = await rc.retrieve(db, memory, rc.RetrievalRequest(
        chat_id=-100, query="что было про дроны", mode="episodic", top_k=10))
    assert episodic.mode == "episodic"
    assert episodic.candidates[0].channel == "episode"
    assert episodic.reason_code == "episodes_used"

    thematic = await rc.retrieve(db, memory, rc.RetrievalRequest(
        chat_id=-100, query="дроны", mode="thematic", top_k=10))
    assert thematic.mode == "thematic"
    assert len(thematic.candidates) >= 1

    # повтор даёт тот же порядок (детерминизм, 0 LLM)
    again = await rc.retrieve(db, memory, rc.RetrievalRequest(
        chat_id=-100, query="дроны", mode="specific",
        subject_node_ids=(77,), top_k=10))
    assert [c.id for c in again.candidates] == [c.id for c in
                                                specific.candidates]


def test_mode_selection_is_deterministic_and_llm_free():
    """Режим выбирается существующей planner-логикой с явным fallback:
    детерминированно на фиксированном наборе входов (0 LLM-вызовов)."""
    fixed = [
        ("кто такой Лёха", "who", {}),
        ("что было вчера", "history", {}),
        ("обзор тем", "broad-theme", {}),
        ("просто так", "follow-up", {}),
        ("расскажи историю", "auto", {}),
        ("расскажи историю", "auto", {"range_active": True}),
        ("Папаха", "fact", {}),
        ("почему так вышло", "relationship", {}),
        ("что сейчас", "current", {}),
        ("что произошло на прошлой неделе", "what-happened", {}),
        ("найди цитату", "auto", {}),
        ("дроны", "auto", {}),
        ("история про оптику", "auto", {}),
        ("когда Кирилл сменил ник", "history", {}),
        ("кто спорил с Папахой", "relationship", {}),
        ("убеждение о работе", "broad-theme", {}),
        ("GregTech и параллели", "auto", {}),
        ("вспомни, как всё начиналось", "auto", {}),
        ("что было раньше", "auto", {}),
        ("последние новости", "current", {}),
    ]
    first = [rc.resolve_intent_mode(rc.RetrievalRequest(
        chat_id=-100, query=query, intent=intent), **kwargs)
        for query, intent, kwargs in fixed]
    second = [rc.resolve_intent_mode(rc.RetrievalRequest(
        chat_id=-100, query=query, intent=intent), **kwargs)
        for query, intent, kwargs in fixed]
    assert first == second                      # детерминизм
    assert len(first) == 20
    # явный режим имеет приоритет и валидируется (неизвестный → auto)
    assert rc.resolve_intent_mode(rc.RetrievalRequest(
        chat_id=-100, query="q", mode="thematic")) == "thematic"
    assert rc.resolve_intent_mode(rc.RetrievalRequest(
        chat_id=-100, query="q", mode="bogus")) == "auto"
    assert "specific" in first and "episodic" in first and "thematic" in first


# ── MEM-06.7: гейты неоднозначности и уместности ──────────────────────────


@pytest.mark.asyncio
async def test_ambiguity_gate_shows_variants_without_auto_pick():
    db = _FakeDB(messages=[_msg(1, "Папаха сказал про дроны", 1000, tg=55)])
    result = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="Папаха",
        ambiguous_subjects=("Папаха (ник)", "Папаха (персонаж)"), top_k=5))
    assert result.candidates                     # варианты видны
    assert result.ambiguity and len(result.ambiguity) == 2
    assert result.relevance is not None
    assert result.relevance.use_memory is False
    assert result.relevance.reason_code == "ambiguous_subject"


@pytest.mark.asyncio
async def test_relevance_gate_drops_wrong_person_and_allows_no_memory():
    """«Не перепутан человек»: факт про другого субъекта без совпадения по
    тексту отбрасывается; решение «не использовать память» возможно."""
    db = _FakeDB(facts=[{"id": 9, "fact": "совсем другая тема", "rag_ts": 2000,
                         "tg_message_id": None, "chat_id": -100,
                         "target_user": "999", "subject_ref_id": 4}])
    result = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", subject_entity_ids=(2,), top_k=5))
    assert result.candidates == ()
    assert result.relevance is not None
    assert result.relevance.use_memory is False


# ── MEM-06.5: никаких квот по классам (INV-12) ────────────────────────────


def test_no_fixed_snippet_quotas_in_retrieval_or_writer_payload():
    import services.direct_chat_service as dcs

    source = inspect.getsource(rc)
    assert "max_items" not in source
    assert "_MEMORY_LOOKUP_PURPOSE_DEFAULTS" not in inspect.getsource(dcs)
    # квоты инструмента остаются капом get_user_context, не retrieval
    from services import tool_router as tr
    assert tr._MEMORY_LOOKUP_PURPOSE_DEFAULTS == {
        "identity": 5, "appearance": 10, "speech_style": 5,
        "biography": 10, "relationships": 10, "general": 8}


# ── MEM-06.8: человеческий summary_text ───────────────────────────────────


def test_evidence_summary_text_has_date_author_and_no_internal_ids():
    ts = int(datetime.datetime(
        2026, 10, 12, 9, 0, tzinfo=datetime.timezone.utc).timestamp())
    lines = rc.render_evidence_summary([
        {"kind": "fact", "text": "любит дроны (fact:7, node_id=3, "
                                 "cosine=0.91, channel=vector)",
         "author": "Лёха", "ts": ts},
        {"kind": "fact", "text": "предположение про отпуск",
         "author": "Лёха", "ts": ts, "certainty": "assumption"},
        {"kind": "fact", "text": "пересланная новость", "author": "Петя",
         "ts": ts, "forward_from": "РБК (tg:99)"},
        {"kind": "episode", "text": "спор про оптику",
         "episode_bounds": "начало 10.10 / конец 12.10"},
        {"kind": "fact", "text": "   ", "author": "Пусто"},
    ], tz_name="Europe/Moscow")
    text = "\n".join(lines)
    assert "Лёха сказал(а) 12.10.2026: любит дроны" in text
    assert "предположение / гипотеза" in text
    assert "пересланное сообщение, первоисточник" in text
    assert text.startswith("эпизод (начало 10.10 / конец 12.10):") or \
        "эпизод (начало 10.10 / конец 12.10): спор про оптику" in text
    assert len(lines) == 4                     # пустой текст не выводится
    assert not _INTERNAL_RE.search(text)
    # пояс чата учитывается (Москва = UTC+3 → та же дата, но не UTC-число)
    assert "1760263200" not in text


def test_evidence_bundle_summary_field_is_additive():
    bundle = rc.EvidenceBundle(trigger="tg:1")
    assert bundle.summary_text == ()
    bundle2 = rc.EvidenceBundle(trigger="tg:1", summary_text=("А: текст",))
    assert bundle2.summary_text == ("А: текст",)
    assert bundle2.schema_version == bundle.schema_version


@pytest.mark.asyncio
async def test_bundle_summary_in_writer_seam_and_prompt_hash_unchanged(
        monkeypatch):
    """summary_text наполняется из уже отобранных ссылок и уходит в слой
    памяти Writer; active prompts не меняются (INV-09)."""
    import services.direct_chat_service as dcs
    from services import prompt_registry

    fingerprint_before = prompt_registry.factory_set_fingerprint()
    chat_prompt_hash_before = hashlib.sha256(
        dcs.CHAT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()

    class _FactDB:
        db = _FakeFacadeShell([])

        async def get_smart_message_by_tg_id(self, chat_id, tg_id):
            return None

        async def get_graph_fact_records(self, fact_ids):
            return [{"id": fact_ids[0], "fact": "любит дроны",
                     "target_user": "Лёха", "created_at": 1700000000,
                     "message_timestamp": 1700000000,
                     "forward_from": "", "status": "confirmed",
                     "subject_ref_id": 5}]

    async def _tz(_chat_id):
        return "Europe/Moscow"

    monkeypatch.setattr(rc, "chat_timezone_name", _tz)
    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    svc.db = _FactDB()
    svc.bot_id = 1

    async def _summary_revision(chat_id):
        return ""

    svc._summary_revision = _summary_revision
    blocks = [("rag", "<RAG_Memory>\n[10.2023 | Автор: Лёха | fact:9]: "
                      "деталь\n</RAG_Memory>"),
              ("current", "<Current_Question>что с дронами?</Current_Question>")]
    msg = type("M", (), {"message_id": 100})()
    bundle = await svc._build_evidence_bundle(
        -100, msg, "что с дронами?", "Лёха", 5, blocks)
    assert bundle is not None
    assert any("любит дроны" in line for line in bundle.summary_text)
    assert any("01.01.2024" in line or "Лёха сказал(а)" in line
               for line in bundle.summary_text)
    assert not _INTERNAL_RE.search("\n".join(bundle.summary_text))

    scoped = dcs._bundle_scoped_slice(bundle)
    assert "Память (с датами и источниками)" in scoped
    assert "любит дроны" in scoped
    # summary — данные пользовательского слоя, а не активный промпт
    assert "любит дроны" not in dcs.CHAT_SYSTEM_PROMPT
    assert prompt_registry.factory_set_fingerprint() == fingerprint_before
    assert hashlib.sha256(
        dcs.CHAT_SYSTEM_PROMPT.encode("utf-8")).hexdigest() \
        == chat_prompt_hash_before


# ── MEM-06.9: factcheck ≠ память ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_factcheck_does_not_mutate_memory_status(tmp_path):
    """Память утверждает «сказано», а не «истинно»: вердикт factcheck
    (`refuted`) не переписывает `graph_facts.status`."""
    import services.factcheck_service as fcs

    db = DatabaseService(str(tmp_path / "fc06.db"))
    await db.initialize()
    try:
        fact_id = await db.insert_graph_fact(
            -100, "земля плоская", "chat_history", None,
            target_user="Лёха")
        before = await db.get_graph_fact(fact_id)
        assert before["status"] == "confirmed"

        ordinary = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=-100, query="плоская", top_k=5))
        cand = next(c for c in ordinary.candidates
                    if c.entity_id == str(fact_id))
        # выдача несёт источник/утверждение, а не «внешнюю истинность»
        assert cand.verification != "true"
        assert cand.entity_type == "graph_fact"
        # factcheck владеет только своим вердиктом-словарём
        assert "refuted" in fcs.CLAIM_STATUS_HUMAN

        after = await db.get_graph_fact(fact_id)
        assert after["status"] == before["status"]
    finally:
        await db.close()
    source = inspect.getsource(fcs)
    for forbidden in ("UPDATE graph_facts", "insert_graph_fact",
                      "archive_graph_fact_for_quota"):
        assert forbidden not in source


# ── MEM-06.2/06.10: get_user_context (6 purposes) через единый retrieval ───


class _LookupDB:
    """Двойник, у которого есть каналы поиска (чтобы путь unified был живым)."""

    def __init__(self):
        self.card_calls = 0
        self.fts_calls = []
        self.subject_calls = []

    async def get_user_context_facts(self, chat_id, target_user, limit, now_ts,
                                     user_id=None):
        # §7.5: субъект-канал единого retrieval — то же чтение, что у прежнего
        # `get_user_context` (устойчивый ref по uid, legacy по имени).
        self.subject_calls.append((chat_id, target_user, user_id))
        return [{"id": 1, "fact": "Лёха носит бороду", "origin": "chat_history",
                 "created_at": 1700000000, "target_user": target_user,
                 "weight": 0.8, "status": "confirmed",
                 "last_confirmed_at": 1700000000, "tg_message_id": None,
                 "message_timestamp": 1700000000, "kind": "fact"}][:limit]

    async def get_persona_card(self, chat_id, name, limit, now_ts):
        self.card_calls += 1
        return {"facts": [], "links": [
            {"source_name": "Лёха", "relation_type": "друг",
             "target_name": "Петя", "edge_id": 11, "fact_id": None,
             "origin": "legacy_unknown", "weight": 2},
            {"source_name": "Лёха", "relation_type": "коллега",
             "target_name": "Аня", "edge_id": 12, "fact_id": 77,
             "origin": "chat_history", "weight": 3}]}

    async def get_generated_dossier(self, chat_id, target_user):
        return {"portrait": "портрет Лёхи", "updated_at": 1700000000,
                "patterns": ["короткие фразы"], "themes": ["дроны"]}

    async def get_recent_messages(self, chat_id, limit):
        return [_msg(i, f"сообщение Лёхи {i}", 1700000000 + i, uid=5, tg=i)
                for i in range(1, 8)]

    async def search_messages_fts(self, chat_id, match, limit):
        return [_msg(21, "Лёха говорил про дроны", int(time.time()),
                     uid=5, tg=88)]

    async def search_graph_facts_fts(self, chat_id, match, limit, now_ts,
                                     include_direct_reply=False,
                                     include_archived=False, **_kw):
        self.fts_calls.append((chat_id, match, include_archived))
        return [_fact_row(1, "Лёха носит бороду и любит дронов")][:limit]

    async def get_graph_fact_records(self, fact_ids, status=None):
        wanted = {int(i) for i in fact_ids}
        return [row for row in [_fact_row(1, "Лёха носит бороду и любит дронов")]
                if row["id"] in wanted]

    async def list_lore_stories(self, chat_id, limit=200):
        return []

    async def get_active_embedding_generation(self, index_name):
        return None


def _fact_row(fid: int, fact: str) -> dict:
    """Строка graph_facts в форме `get_graph_fact_records`."""
    return {"id": fid, "fact": fact, "origin": "chat_history",
            "created_at": 1700000000, "target_user": "Лёха",
            "weight": 0.8, "status": "confirmed",
            "last_confirmed_at": 1700000000, "message_timestamp": 1700000000,
            "tg_message_id": None, "forward_from": "", "expires_at": None,
            "chat_id": -100, "subject_ref_id": 9,
            "speaker_author_id": None, "assertion_kind": None,
            "attribution_method": None, "provenance_channel": None}


class _LookupMemory:
    def __init__(self):
        self.calls = []

    async def retrieve_fact_candidates(self, chat_id, query, *, limit,
                                       include_archived=False, **_kw):
        self.calls.append(("retrieve_fact_candidates", include_archived))
        return [{"id": 3, "fact": "Лёха любит дроны",
                 "origin": "chat_history", "rag_ts": 1700000000,
                 "target_user": "Лёха", "chat_id": -100,
                 "item_id": "fact:3", "subject_ref_id": 9}]

    async def get_rag_facts(self, *a, **kw):        # legacy-путь (не вызывается)
        self.calls.append(("get_rag_facts",))
        return []

    async def search_long_term(self, *a, **kw):
        self.calls.append(("search_long_term",))
        return []


class _Aliases:
    def __init__(self, mapping):
        self._aliases = {str(k): str(v) for k, v in mapping.items()}

    def canon_name(self, name):
        text = str(name or "").strip()
        return text

    def resolve(self, user_id, nickname=None, username=None):
        return self._aliases.get(str(user_id), str(nickname or user_id))


def _router(db=None, memory=None):
    return ToolRouter(ToolDeps(search=None,
                               memory=memory if memory is not None else
                               _LookupMemory(),
                               aliases=_Aliases({"5": "Лёха"}), db=db))


def _payload(raw: str) -> dict:
    return json.loads(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", [
    "identity", "appearance", "speech_style", "biography",
    "relationships", "general"])
async def test_all_six_purposes_work(purpose):
    router = _router(db=_LookupDB())
    out = _payload(await router.dispatch(
        MEMORY_LOOKUP_TOOL_NAME, {"person": "Лёха", "purpose": purpose},
        ToolContext(-100, "q", user_id=5)))
    assert out["status"] == "ok", out
    assert out["purpose"] == purpose
    assert out["facts"], f"purpose={purpose} вернул пусто"
    assert out.get("error") != "invalid_purpose"


@pytest.mark.asyncio
async def test_relationships_not_degraded_and_basis_present():
    db = _LookupDB()
    router = _router(db=db)
    out = _payload(await router.dispatch(
        MEMORY_LOOKUP_TOOL_NAME, {"person": "Лёха", "purpose": "relationships"},
        ToolContext(-100, "q", user_id=5)))
    assert out["purpose"] == "relationships"
    assert out["status"] == "ok"
    assert db.card_calls == 1
    assert len(out["facts"]) == 2
    unsupported = out["facts"][0]
    supported = out["facts"][1]
    # ребро без основания честно помечено и НЕ деградирует до general
    assert unsupported["has_unsupported_sources"] is True
    assert "источник не указан" in unsupported["source_basis"]
    assert supported["has_unsupported_sources"] is False
    assert supported["legacy_ids"] == ["12", "77"]
    assert out["sources"][0]["kind"] == "edge"
    assert out["sources"][1]["ref"] == "12"


@pytest.mark.asyncio
async def test_general_purpose_uses_single_unified_retrieval(monkeypatch):
    """Регрессия MEM-06.1: чтения идут через ОДИН `retrieve`, не через
    собственный поиск в ветке."""
    calls: list = []
    real = rc.retrieve

    async def _count(db, memory, request):
        calls.append(request.purpose)
        return await real(db, memory, request)

    monkeypatch.setattr(rc, "retrieve", _count)
    memory = _LookupMemory()
    router = _router(db=_LookupDB(), memory=memory)
    out = _payload(await router.dispatch(
        MEMORY_LOOKUP_TOOL_NAME, {"person": "Лёха", "purpose": "general"},
        ToolContext(-100, "q", user_id=5)))
    assert out["facts"]
    assert calls == ["dossier"]                  # ровно один вход
    # обычная (не архивная) выдача: reply/context путь архив не просит
    assert all(flag is False for _, flag in memory.calls)


def test_no_second_search_path_introduced():
    """Второго поискового движка нет: в модуле контракта ровно один
    `retrieve`, нет своих `search_*`-функций; ветка `relationships` не
    содержит SQL-поиска."""
    tree = ast.parse(inspect.getsource(rc))
    funcs = [node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert funcs.count("retrieve") == 1
    assert not [name for name in funcs if name.startswith("search_")]

    relationships = inspect.getsource(ToolRouter._memory_lookup_relationships)
    assert "search_graph_facts_fts(" not in relationships
    assert "search_messages_fts(" not in relationships
    unified = inspect.getsource(ToolRouter._memory_lookup_unified)
    assert "_rc.retrieve(" in unified


# ── §4.4: purpose/limit/chat_ids ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_ui_search_limit_validated_and_applied():
    db = _FakeDB(messages=[_msg(i, f"дроны {i}", 1000 + i, tg=i)
                           for i in range(1, 6)])
    bad = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", purpose="ui_search", limit=21))
    assert bad.status == rc.RETRIEVAL_ERROR
    assert bad.reason_code == "invalid_limit"

    ok = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", purpose="ui_search", limit=2))
    assert ok.status == rc.RETRIEVAL_OK
    assert ok.purpose == "ui_search"
    assert len(ok.candidates) <= 2

    # limit/cursor — только для ui_search
    wrong = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", purpose="reply", limit=3))
    assert wrong.status == rc.RETRIEVAL_ERROR
    assert wrong.reason_code == "limit_not_allowed"

    unknown = await rc.retrieve(db, None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", purpose="bogus"))
    assert unknown.reason_code == "invalid_purpose"


@pytest.mark.asyncio
async def test_chat_ids_acl_scope_is_respected():
    seen: list = []

    class _ChatsDB(_FakeDB):
        async def search_messages_fts(self, chat_id, match, limit):
            seen.append(chat_id)
            return [_msg(1, "дроны", 1000, tg=chat_id)]

    result = await rc.retrieve(_ChatsDB(), None, rc.RetrievalRequest(
        chat_id=-100, query="дроны", chat_ids=(-100, -200), top_k=5))
    assert result.chat_ids == (-100, -200)
    assert set(seen) == {-100, -200}
    # None = ровно chat_id (прежнее поведение)
    assert rc.effective_chat_ids(rc.RetrievalRequest(
        chat_id=-300, query="q")) == (-300,)


# ═══════════════════════════════════════════════════════════════════════════
# Фикс ревью: reply-путь direct-RAG идёт через ЕДИНЫЙ `retrieve` (§7.5)
# ═══════════════════════════════════════════════════════════════════════════


def _reply_rows():
    """Строки graph_facts в форме `get_rag_facts(with_meta=True)`."""
    now = 1700000000
    return [
        {"id": 1, "origin": "chat_history", "fact": "любит дроны",
         "rag_ts": now, "created_at": now, "message_timestamp": now,
         "target_user": "Лёха", "tg_message_id": None, "forward_from": "",
         "item_id": "fact:1", "score": 2.0, "expired": False,
         "expires_at": None, "chat_id": -100, "status": "confirmed",
         "subject_ref_id": 1, "speaker_author_id": 1},
        {"id": 2, "origin": "chat_history", "fact": "собирает квадрокоптеры",
         "rag_ts": now + 10, "created_at": now + 10,
         "message_timestamp": now + 10, "target_user": "Лёха",
         "tg_message_id": None, "forward_from": "", "item_id": "fact:2",
         "score": 1.0, "expired": False, "expires_at": None, "chat_id": -100,
         "status": "confirmed", "subject_ref_id": 1,
         "speaker_author_id": 1},
    ]


class _ReplyDB:
    """Двойник БД direct-пути: каналы единого retrieval (без второго поиска)."""

    def __init__(self, rows, messages=()):
        self.rows = [dict(r) for r in rows]
        self.messages = list(messages)
        self.fts_calls = []

    async def search_messages_fts(self, chat_id, match, limit):
        return list(self.messages)

    async def search_graph_facts_fts(self, chat_id, match, limit, now_ts,
                                     include_direct_reply=False,
                                     include_archived=False,
                                     include_self=False, **_kw):
        self.fts_calls.append((chat_id, match, bool(include_archived)))
        return [dict(r) for r in self.rows][:limit]

    async def get_active_embedding_generation(self, index_name):
        return None


class _ReplyMemory:
    """Двойник MemoryManager: единый канал кандидатов + прежнее чтение."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.legacy_calls = 0
        self.unified_calls = 0

    async def retrieve_fact_candidates(self, chat_id, query, *, limit=None,
                                       include_direct_reply=False,
                                       include_self=False,
                                       include_archived=False):
        self.unified_calls += 1
        rows = [dict(r) for r in self.rows]
        return rows[:limit] if limit else rows

    async def get_rag_facts(self, chat_id, query, *, with_meta=False, **_kw):
        self.legacy_calls += 1
        return [dict(r) for r in self.rows]

    async def fetch_golden_facts(self, *a, **kw):
        return []


class _Hot:
    """hot-флаги direct-пути: RAG включён, реранк/ностальгия выключены."""

    _VALUES = {
        "flags.graph_rag_enabled": True,
        "flags.chat_rag_rerank_enabled": False,
        "memory.nostalgia_layer_a_enabled": False,
    }

    def get(self, key, default=None):
        return self._VALUES.get(key, default)


async def _no_chat_param(chat_id, key, default=None):
    return default


def _reply_service(db, memory):
    import services.direct_chat_service as dcs

    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    svc.db = db
    svc.memory = memory
    svc.bot_id = 1
    return svc


class _Msg:
    def __init__(self, text, message_id=100):
        self.text = text
        self.message_id = message_id


def _rag_inner(block: str) -> str:
    return block[len("<RAG_Memory>\n"):-len("\n</RAG_Memory>")]


@pytest.mark.asyncio
async def test_reply_rag_uses_one_unified_retrieve(monkeypatch):
    """BLOCKER 2 (фикс ревью): direct-путь RAG читает факты ОДНИМ `retrieve`
    (purpose=reply), а не собственным поиском; прежнее чтение не вызывается."""
    import services.direct_chat_service as dcs

    monkeypatch.setattr(dcs, "hot", _Hot())
    monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
    calls: list = []
    real = rc.retrieve

    async def _spy(db, memory, request):
        calls.append(request)
        return await real(db, memory, request)

    monkeypatch.setattr(rc, "retrieve", _spy)
    memory = _ReplyMemory(_reply_rows())
    svc = _reply_service(_ReplyDB(_reply_rows()), memory)
    block, hint = await svc._build_rag_block(-100, _Msg("про дроны"), "")
    assert block.startswith("<RAG_Memory>\n")
    assert "любит дроны" in block and "собирает квадрокоптеры" in block
    assert hint == ""
    assert len(calls) == 1, "ровно один вход единого retrieval"
    request = calls[0]
    assert request.purpose == "reply"
    # Только канал `vector`: прежняя выдача direct-RAG — KNN/MMR того же
    # чтения; exact/lexical (вес выше) меняли бы состав top-k.
    assert request.channels == ("vector",)
    assert request.preserve_channel_order is True
    assert request.include_self is True
    assert request.include_direct_reply is True
    assert request.include_archived is False
    assert memory.legacy_calls == 0        # второго чтения RAG-фактов нет
    assert memory.unified_calls == 1


@pytest.mark.asyncio
async def test_reply_rag_legacy_and_unified_selection_parity(monkeypatch):
    """Паритет отбора: на одном и том же наборе фактов unified-путь и прежнее
    чтение дают ОДИН И ТОТ ЖЕ блок (состав и порядок), т.е. принятая выдача
    direct-RAG не меняется — меняется только источник отбора."""
    import services.direct_chat_service as dcs

    monkeypatch.setattr(dcs, "hot", _Hot())
    monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
    rows = _reply_rows()

    unified_memory = _ReplyMemory(rows)
    unified, _ = await _reply_service(
        _ReplyDB(rows), unified_memory)._build_rag_block(
            -100, _Msg("про дроны"), "")

    class _NoChannelsDB:
        """Двойник без каналов единого retrieval → прежнее чтение."""

    class _LegacyOnlyMemory:
        """Реализация памяти без канала единого retrieval (compat-двойник)."""

        def __init__(self, rows):
            self.rows = [dict(r) for r in rows]
            self.legacy_calls = 0

        async def get_rag_facts(self, chat_id, query, *, with_meta=False,
                                **_kw):
            self.legacy_calls += 1
            return [dict(r) for r in self.rows]

        async def fetch_golden_facts(self, *a, **kw):
            return []

    legacy_memory = _LegacyOnlyMemory(rows)
    legacy, _ = await _reply_service(
        _NoChannelsDB(), legacy_memory)._build_rag_block(
            -100, _Msg("про дроны"), "")

    assert unified == legacy
    lines = _rag_inner(unified).split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("[чат] [") and "любит дроны" in lines[0]
    assert lines[1].startswith("[чат] [") and "собирает квадрокоптеры" in lines[1]
    assert "fact:1" in lines[0] and "fact:2" in lines[1]      # ASC-хронология
    assert unified_memory.legacy_calls == 0
    assert legacy_memory.legacy_calls == 1


# ═══════════════════════════════════════════════════════════════════════════
# Фикс ревью: ВСЕ шесть purpose — через один и тот же `retrieve` (§7.5)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose,channels,participants,relations,order", [
    ("general", None, (), False, False),
    # профиль субъекта — канал `subject` (отбор по субъекту, не по тексту)
    ("identity", ("subject",), (), False, True),
    ("appearance", ("subject",), (), False, True),
    ("biography", ("subject",), (), False, True),
    ("speech_style", ("recent",), (5,), False, True),
    ("relationships", (), (), True, True),
])
async def test_each_purpose_calls_shared_retrieve_once(
        purpose, channels, participants, relations, order, monkeypatch):
    """MEM-06.10: каждое назначение входит в ЕДИНЫЙ `retrieve` ровно один раз
    и передаёт свою документированную политику каналов (§4.4), а не идёт в
    БД/память напрямую."""
    calls: list = []
    real = rc.retrieve

    async def _spy(db, memory, request):
        calls.append(request)
        return await real(db, memory, request)

    monkeypatch.setattr(rc, "retrieve", _spy)
    router = _router(db=_LookupDB())
    out = _payload(await router.dispatch(
        MEMORY_LOOKUP_TOOL_NAME, {"person": "Лёха", "purpose": purpose},
        ToolContext(-100, "q", user_id=5)))
    assert out["status"] == "ok", out
    assert out["purpose"] == purpose
    assert out["facts"], f"purpose={purpose} вернул пусто"
    assert len(calls) == 1, f"purpose={purpose}: входов {len(calls)}"
    request = calls[0]
    assert request.purpose == "dossier"          # назначение lookup-ветки
    assert request.channels == channels
    assert request.participants == participants
    assert request.include_relations is relations
    assert request.preserve_channel_order is order
    assert request.include_archived is False
    # §7.5: субъект объявлен именем+uid — отбор фактов о человеке не зависит
    # от совпадения текста факта с именем.
    assert request.subject_names == ("Лёха",)
    assert request.subject_entity_ids == (5,)


@pytest.mark.asyncio
async def test_relationships_projection_keeps_basis_through_retrieve(
        monkeypatch):
    """Санкционированная проекция связей: рёбра приходят из `retrieve`
    (`include_relations`), envelope сохраняет facts/sources/legacy_ids/
    has_unsupported_sources — и собственного SQL у ветки нет."""
    calls: list = []
    real = rc.retrieve

    async def _spy(db, memory, request):
        calls.append(request)
        return await real(db, memory, request)

    monkeypatch.setattr(rc, "retrieve", _spy)
    db = _LookupDB()
    out = _payload(await _router(db=db).dispatch(
        MEMORY_LOOKUP_TOOL_NAME,
        {"person": "Лёха", "purpose": "relationships"},
        ToolContext(-100, "q", user_id=5)))
    assert len(calls) == 1 and calls[0].include_relations is True
    assert db.card_calls == 1
    assert [f["text"] for f in out["facts"]] == ["Лёха (друг) Петя",
                                                 "Лёха (коллега) Аня"]
    assert out["facts"][0]["has_unsupported_sources"] is True
    assert out["facts"][1]["has_unsupported_sources"] is False
    assert out["facts"][1]["legacy_ids"] == ["12", "77"]
    assert [s["kind"] for s in out["sources"]] == ["edge", "edge"]


def test_relation_projection_is_bounded_and_marks_basis():
    """Проекция связей (§7.5): порядок сохраняется, размер ограничен, ребро
    без основания честно помечено."""
    links = [{"source_name": "A", "relation_type": "r", "target_name": "B",
              "edge_id": 1, "fact_id": None, "origin": "legacy_unknown"}]
    links += [{"source_name": f"N{i}", "relation_type": "r",
               "target_name": f"M{i}", "edge_id": 10 + i, "fact_id": 100 + i,
               "origin": "chat_history"} for i in range(30)]
    projected = rc.project_relations(links, 5)
    assert len(projected) == 5
    assert projected[0]["has_unsupported_sources"] is True
    assert projected[1]["legacy_ids"] == ["10", "100"]


# ═══════════════════════════════════════════════════════════════════════════
# Фикс ревью: bounded batch-чтение ссылок evidence summary (§7.2)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_evidence_summary_read_is_bounded_to_ref_cap(monkeypatch):
    """Batch-чтение фактов ограничивается ДО обращения к БД: даже при 30
    `fact:`-ссылках в блоке читается не больше `_BUNDLE_BLOCK_MAX_REFS`."""
    import services.direct_chat_service as dcs

    class _FactDB:
        db = _FakeFacadeShell([])

        def __init__(self):
            self.reads = []

        async def get_smart_message_by_tg_id(self, chat_id, tg_id):
            return None

        async def get_graph_fact_records(self, fact_ids, status=None):
            self.reads.append(tuple(fact_ids))
            return [{"id": fid, "fact": f"факт {fid}", "target_user": "Лёха",
                     "created_at": 1700000000, "message_timestamp": None,
                     "forward_from": "", "status": "confirmed",
                     "subject_ref_id": 5} for fid in fact_ids]

    db = _FactDB()
    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    svc.db = db
    svc.bot_id = 1

    async def _summary_revision(chat_id):
        return ""

    svc._summary_revision = _summary_revision

    async def _tz(_chat_id):
        return "Europe/Moscow"

    monkeypatch.setattr(rc, "chat_timezone_name", _tz)
    refs = " ".join(f"fact:{i}" for i in range(1, 31))
    blocks = [("rag", f"<RAG_Memory>\n{refs}\n</RAG_Memory>"),
              ("current",
               "<Current_Question>что с дронами?</Current_Question>")]
    bundle = await svc._build_evidence_bundle(
        -100, _Msg("что с дронами?"), "что с дронами?", "Лёха", 5, blocks)
    assert bundle is not None
    assert db.reads, "batch-чтение фактов не выполнено"
    assert max(len(ids) for ids in db.reads) <= dcs._BUNDLE_BLOCK_MAX_REFS
    assert len(bundle.summary_text) <= 20


# ═══════════════════════════════════════════════════════════════════════════
# Регрессия ре-ревью 40ae401a: профиль субъекта отбирается ПО СУБЪЕКТУ
# (`subject_ref_id`/`target_user`), а не по совпадению текста с запросом.
# Факты о человеке не обязаны содержать его имя в тексте.
# ═══════════════════════════════════════════════════════════════════════════

#: 4 факта о человеке; имя встречается ТОЛЬКО в первом тексте.
_PERSON_FACTS = ("Лёха носит бороду", "любит дронов",
                 "работает программистом", "живёт в Москве")


class _NoMemory:
    """Память без RAG: профиль читается subject-каналом единого retrieval."""

    def __init__(self):
        self.calls = []

    async def retrieve_fact_candidates(self, chat_id, query, **kw):
        self.calls.append("retrieve_fact_candidates")
        return []

    async def get_rag_facts(self, *a, **kw):
        self.calls.append("get_rag_facts")
        return []

    async def search_long_term(self, *a, **kw):
        self.calls.append("search_long_term")
        return []

    async def get_rag_context(self, *a, **kw):
        self.calls.append("get_rag_context")
        return ""


async def _seed_person(db, texts=_PERSON_FACTS, *, name="Лёха",
                       chat_id=-100) -> dict:
    """Реальная запись фактов субъекта (без подмешивания имени в текст)."""
    ids = {}
    for text in texts:
        ids[text] = await db.insert_graph_fact(
            chat_id, text, "chat_history", None, target_user=name)
    return ids


async def _purpose_payload(router, purpose, *, max_items=None) -> dict:
    args = {"person": "Лёха", "purpose": purpose}
    if max_items is not None:
        args["max_items"] = max_items
    return _payload(await router.dispatch(
        MEMORY_LOOKUP_TOOL_NAME, args, ToolContext(-100, "q", user_id=5)))


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["identity", "biography"])
async def test_profile_purpose_returns_all_subject_facts(tmp_path, purpose):
    """Приёмочный тест регрессии: 4 факта о человеке, имя только в одном
    тексте → identity и biography обязаны вернуть ВСЕ 4 (отбор по субъекту,
    а не по FTS-совпадению с запросом). Двойник с именем в тексте этот
    дефект скрывал."""
    db = DatabaseService(str(tmp_path / f"subj_{purpose}.db"))
    await db.initialize()
    try:
        ids = await _seed_person(db)
        router = _router(db=db, memory=_NoMemory())
        out = await _purpose_payload(router, purpose, max_items=10)
        texts = [f["text"] for f in out["facts"]]
        missing = [text for text in _PERSON_FACTS if text not in texts]
        assert not missing, (
            f"{purpose}: потеряны факты субъекта без имени в тексте {missing} "
            f"(вернулось {texts})")
        assert len(ids) == len(_PERSON_FACTS)
        # envelope прежний: факты/источники/confidence на месте
        assert len(out["sources"]) >= len(_PERSON_FACTS)
        assert out["confidence"]["label"] == "confirmed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_appearance_selects_subject_facts_without_name_in_text(
        tmp_path):
    """appearance: лексиконный фильтр поверх ФАКТОВ СУБЪЕКТА — факт внешности
    без имени в тексте не теряется."""
    db = DatabaseService(str(tmp_path / "subj_appearance.db"))
    await db.initialize()
    try:
        await _seed_person(db, ("Лёха носит бороду", "высокий рост",
                                "любит дронов", "живёт в Москве"))
        router = _router(db=db, memory=_NoMemory())
        out = await _purpose_payload(router, "appearance", max_items=10)
        texts = [f["text"] for f in out["facts"]]
        assert "высокий рост" in texts           # без имени в тексте
        assert "Лёха носит бороду" in texts
        assert "любит дронов" not in texts       # не внешность
        assert out["no_data"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_general_returns_all_subject_facts(tmp_path):
    """general: субъект-факты входят в выдачу независимо от имени в тексте."""
    db = DatabaseService(str(tmp_path / "subj_general.db"))
    await db.initialize()
    try:
        await _seed_person(db)
        router = _router(db=db, memory=_NoMemory())
        out = await _purpose_payload(router, "general", max_items=10)
        texts = [f["text"] for f in out["facts"]]
        missing = [text for text in _PERSON_FACTS if text not in texts]
        assert not missing, f"general: потеряны факты субъекта {missing}"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_archived_subject_fact_does_not_leak_into_profile(tmp_path):
    """Архивный (`archived_fact`, вытеснено квотой) факт субъекта остаётся
    невидимым обычному профилю — субъект-канал не открывает архив."""
    db = DatabaseService(str(tmp_path / "subj_arch.db"))
    await db.initialize()
    try:
        ids = await _seed_person(db, ("Лёха носит бороду", "любит дронов",
                                      "работает программистом"))
        assert await db.archive_graph_fact_for_quota(
            ids["любит дронов"], -100, "Лёха") is True
        router = _router(db=db, memory=_NoMemory())
        out = await _purpose_payload(router, "identity", max_items=10)
        texts = [f["text"] for f in out["facts"]]
        assert "Лёха носит бороду" in texts
        assert "работает программистом" in texts
        assert "любит дронов" not in texts
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_retrieve_subject_channel_contract(tmp_path):
    """Контракт субъект-канала единого retrieval: отбор по субъекту, порядок
    `weight DESC` (порядок самого чтения), честная атрибуция субъекта и
    `fact_rows` — без второго чтения у потребителя."""
    db = DatabaseService(str(tmp_path / "subj_channel.db"))
    await db.initialize()
    try:
        ids = {}
        for text, weight in (("любит дронов", 0.4),
                             ("работает программистом", 0.9),
                             ("живёт в Москве", 0.6),
                             ("Лёха носит бороду", 0.2)):
            ids[text] = await db.insert_graph_fact(
                -100, text, "chat_history", None, target_user="Лёха",
                weight=weight)
        result = await rc.retrieve(db, None, rc.RetrievalRequest(
            chat_id=-100, query="Лёха", purpose="dossier", top_k=10,
            channels=("subject",), subject_names=("Лёха",),
            subject_entity_ids=(5,), preserve_channel_order=True))
        assert result.channels_used == ("subject",)
        assert {c.entity_id for c in result.candidates} == {
            str(fid) for fid in ids.values()}
        # порядок — собственный порядок чтения: weight DESC
        assert [c.entity_id for c in result.candidates] == [
            str(ids["работает программистом"]), str(ids["живёт в Москве"]),
            str(ids["любит дронов"]), str(ids["Лёха носит бороду"])]
        assert len(result.fact_rows) == 4
        assert result.relevance is not None
        assert result.relevance.matched_subject is True
    finally:
        await db.close()


# ── Паритет direct-RAG: порядок/состав канала, а не типизированный ранг ────


def _meta_row(fid: int, fact: str, ts: int) -> dict:
    """Строка в форме `retrieve_fact_candidates` (KNN/MMR-порядок памяти)."""
    return {"id": fid, "item_id": f"fact:{fid}", "origin": "chat_history",
            "fact": fact, "rag_ts": ts, "message_timestamp": ts,
            "created_at": ts, "target_user": "Лёха", "tg_message_id": None,
            "forward_from": "", "score": 1.0, "expired": False,
            "expires_at": None, "chat_id": -100, "status": "confirmed",
            "subject_ref_id": 1, "speaker_author_id": 1}


class _HotLimit(_Hot):
    """hot-флаги direct-пути с явным лимитом фактов RAG."""

    def __init__(self, limit: int):
        self._limit = int(limit)

    def get(self, key, default=None):
        if key == "limits.graph_rag_facts_limit":
            return self._limit
        return _Hot.get(self, key, default)


@pytest.mark.asyncio
async def test_reply_rag_keeps_channel_order_and_composition(monkeypatch):
    """Паритет состава/порядка direct-RAG: принятая выдача — это KNN/MMR-
    порядок памяти. Набор, где FTS-канал нашёл бы третий факт, а типизированный
    ранг поставил бы самый свежий факт первым, НЕ должен менять ни состав
    (top-limit по релевантности), ни порядок отбора."""
    import services.direct_chat_service as dcs

    now = int(time.time())
    rows = [_meta_row(1, "любит дроны", now - 500000),
            _meta_row(2, "собирает квадрокоптеры", now - 10),
            _meta_row(3, "дроны повсюду", now - 300000)]
    monkeypatch.setattr(dcs, "hot", _HotLimit(2))
    monkeypatch.setattr(dcs, "_cp_g", _no_chat_param)
    memory = _ReplyMemory(rows)
    svc = _reply_service(_ReplyDB([rows[2]]), memory)

    selected = await svc._rag_unified_rows(-100, "про дроны", _Msg("про дроны"))
    assert [row["id"] for row in selected] == [1, 2], (
        "порядок KNN/MMR канала должен сохраняться, а FTS-совпадение — "
        f"не вытеснять релевантный топ: {[r['id'] for r in selected]}")

    block, _hint = await svc._build_rag_block(-100, _Msg("про дроны"), "")
    lines = _rag_inner(block).split("\n")
    assert len(lines) == 2, block
    assert "fact:3" not in block, "FTS-факт вне top-limit не должен попадать"
    assert "любит дроны" in block and "собирает квадрокоптеры" in block
