"""mca-06-sleep-paradigms — блоки D+E (round 10.34) targeted-тесты.

Покрытие по контрактам (spec.md §5–§8.6, ADR-1028-9 D7/D8/D10/AM-5,
threat-failure THR-3/THR-4; tasks T-4713…T-4722):
  * T-4713 независимость оснований по уникальным первичным событиям
    `(chat_id, tg_message_id)`; счётчик в belief_meta.
  * T-4714 мост-валидатор (5 проверок), порог `min_anchors=2` на НЕЗАВИСИМЫХ
    событиях; иначе `insufficient_evidence`; константы round1021 не сдвинуты.
  * T-4715 10-статусная матрица + маппинг старых кодов (словарь один).
  * T-4716 противоречие → сужение/спорность + EvidenceLink `contradicts`.
  * T-4717 типизированные anchor_items (message/graph_fact), honest unknown,
    недубльность.
  * T-4718 read-only раскрытие цепочки до сообщений + delta на реальном API.
  * T-4719 идемпотентность + `supersedes` EvidenceLink, старая версия читаема.
  * T-4720 bounded очередь пересмотра, cap/paused/resume, kill-switch OFF.
  * T-4721 bot_self_reply исключён из independence-подсчёта.
  * T-4722 `applicability_scope`/`valid_from`/`valid_to` в belief_meta, без DDL.
"""
import asyncio
import time

import pytest

from services import mca_dream_evidence as ev
from services import mca_gates
from services import provenance
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100
NOW = int(time.time())
DAY = 86400


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


# ── фейки ───────────────────────────────────────────────────────────────────

def _cand(fact, *, days_old=200, tg=None, fid=None, origin="chat_history",
          self_referential=False, **extra):
    d = {
        "id": fid if fid is not None else abs(hash(fact)) % 100000,
        "chat_id": CHAT_ID,
        "fact": fact,
        "origin": origin,
        "rag_ts": NOW - days_old * DAY,
        "message_timestamp": NOW - days_old * DAY,
        "created_at": NOW - days_old * DAY,
        "tg_message_id": tg,
        "target_user": None,
        "self_referential": self_referential,
    }
    d.update(extra)
    return d


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)

    async def generate_worker(self, role, messages, temperature=None):
        if self._answers:
            return self._answers.pop(0)
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


class _Sel:
    def __init__(self, candidates, *, missing_timestamp=0, fts_fallback=False,
                 reason=None):
        self.candidates = list(candidates)
        self.missing_timestamp = missing_timestamp
        self.fts_fallback = fts_fallback
        self.reason = reason


def _packet(texts, *, target="Толян", created_at=None):
    created_at = created_at if created_at is not None else NOW - 3600
    return {
        "beliefs": [{"fact": texts[0], "id": 1, "target_user": target,
                     "created_at": created_at}],
        "recent": [{"fact": t, "importance": 5} for t in texts[1:]],
        "source_ids": [1],
    }


class _Mem:
    _vec_available = False

    async def retrieve_fact_candidates(self, *a, **k):
        return []

    async def get_rag_facts(self, *a, **k):
        return []


def _worker(db, sel, llm, monkeypatch, *, packet=None):
    import services.dream_worker as dw
    import services.mca_dream_history as hist
    monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                        lambda: False)
    monkeypatch.setattr(dw.mca_gates, "dream_gate_resolver_enabled",
                        lambda: False)

    async def _fake_select(*a, **k):
        return sel

    monkeypatch.setattr(hist, "select_historical_candidates", _fake_select)
    w = DreamWorker(db, memory=_Mem(), llm=llm)
    pkt = packet if packet is not None else _packet(["Толян литрбол"])

    async def _build(chat_id, now, since_ts):
        return pkt

    async def _traits(chat_id, now, *, manual=False):
        return 0

    async def _budget(*a, **k):
        return True

    monkeypatch.setattr(w, "_build_deep_packet", _build)
    monkeypatch.setattr(w, "_run_persona_traits_step", _traits)
    monkeypatch.setattr(w, "_deep_budget_ok", _budget)
    return w


# ── T-4713/T-4721: независимость ────────────────────────────────────────────

class TestIndependence:
    def test_two_retellings_one_message_is_one(self):
        a = _cand("пересказ один", tg=7)
        b = _cand("пересказ два", tg=7)
        assert ev.count_independent_events([a, b]) == 1

    def test_two_distinct_events_is_two(self):
        a = _cand("событие один", tg=7)
        b = _cand("событие два", tg=8)
        assert ev.count_independent_events([a, b]) == 2

    def test_two_graph_facts_distinct_ids(self):
        a = _cand("факт один", tg=None, fid=11)
        b = _cand("факт два", tg=None, fid=12)
        assert ev.count_independent_events([a, b]) == 2

    def test_bot_self_excluded_from_independence(self):
        a = _cand("бот сказал", tg=7, origin="bot_self_reply",
                  self_referential=True)
        b = _cand("человек сказал", tg=8)
        assert ev.is_bot_self(a) is True
        assert ev.count_independent_events([a, b]) == 1
        assert ev.excluded_bot_self([a, b]) == 1

    def test_dedup_anchors_removes_same_event(self):
        a = _cand("первый", tg=5)
        b = _cand("второй", tg=5)
        assert len(ev.dedup_anchors([a, b])) == 1


# ── T-4715: 10-статусная матрица ────────────────────────────────────────────

class TestStatusMatrix:
    def test_exactly_ten_canonical_statuses(self):
        assert len(ev.DREAM_STATUSES) == 10
        assert set(ev.DREAM_STATUSES) == {
            "disabled", "error", "no_context", "no_anchors",
            "insufficient_evidence", "unchanged", "duplicate", "budget",
            "cooldown", "written"}

    def test_legacy_mapping(self):
        assert ev.map_status("ok") == "written"
        assert ev.map_status("budget_skip") == "budget"
        assert ev.map_status("daily_limit") == "budget"
        assert ev.map_status("no_memory") == "disabled"
        assert ev.map_status("cooldown") == "cooldown"   # idempotent

    def test_internal_reasons_not_statuses(self):
        for code in ("no_memory", "rag_failed", "llm_error", "parse_error",
                     "paradigm_write"):
            assert code in ev.INTERNAL_REASON_CODES
            assert code not in ev.DREAM_STATUSES

    def test_matrix_single_source(self):
        m = ev.status_matrix()
        assert len(m["statuses"]) == 10
        assert m["legacy_map"]["ok"] == "written"


# ── T-4714/T-4716: мост-валидатор ───────────────────────────────────────────

class TestBridgeValidator:
    def _pkt(self):
        return _packet(["Толян литрбол каждый вечер"])

    def test_random_old_fact_no_subject(self):
        anchors = [_cand("погода в нью-йорке была холодной", tg=1)]
        bv = ev.validate_bridge("вывод про толяна", self._pkt(), anchors,
                                now=NOW)
        assert bv.ok is False
        assert bv.reason == "no_subject"
        assert bv.checks["subject"] is False

    def test_bridge_with_event_passes(self):
        anchors = [
            _cand("Толян пил литрбол каждую пятницу", tg=1),
            _cand("Толян рассказывал про литрбол друзьям", tg=2),
        ]
        bv = ev.validate_bridge("Толян изменил привычки литрбол", self._pkt(),
                                anchors, now=NOW)
        assert bv.ok is True
        assert bv.independent_events == 0
        assert bv.checks["time_order"] is True

    def test_time_order_enforced(self):
        # «раньше» не раньше «сейчас»: anchor свежее нового периода.
        anchors = [_cand("Толян литрбол вчера", days_old=-1, tg=1)]
        bv = ev.validate_bridge("Толян литрбол", self._pkt(), anchors,
                                now=NOW)
        assert bv.checks["time_order"] is False
        assert bv.reason == "time_order"

    def test_unresolved_source_is_honest_unknown(self):
        anchors = [{"fact": "Толян литрбол", "message_timestamp": NOW - 200 * DAY}]
        bv = ev.validate_bridge("Толян литрбол", self._pkt(), anchors,
                                now=NOW)
        assert bv.checks["source_resolved"] is False
        assert bv.reason == "unresolved_source"

    def test_contradiction_narrows_not_rejects(self):
        anchors = [
            _cand("Толян больше не пьёт литрбол", tg=1),
            _cand("Толян литрбол бросил привычку", tg=2),
        ]
        bv = ev.validate_bridge("Толян изменил привычки литрбол", self._pkt(),
                                anchors, now=NOW)
        assert bv.ok is True
        assert bv.narrowed is True
        assert bv.contradictions
        assert bv.applicability["narrowed"] is True
        assert bv.applicability["valid_from"] is not None

    def test_round1021_constants_unchanged(self):
        from config.settings import settings
        assert settings.DEEP_SLEEP_TOP_K == 20
        assert settings.DEEP_SLEEP_MAX_PARADIGMS == 3
        assert settings.DEEP_SLEEP_TOKENS_PER_DAY == 40000
        # порог 2 — на независимых событиях, не снижается.
        from services import dream_worker as dw
        assert dw._DEEP_SLEEP_MIN_HISTORICAL == 2

    @pytest.mark.asyncio
    async def test_link_contradicts_creates_evidence_link(self, db):
        fid = await db.insert_graph_fact(CHAT_ID, "спорный вывод",
                                         "derived_belief", None, kind="belief")
        anchor = _cand("Толян больше не пьёт литрбол", tg=321)
        ok = await ev.link_contradicts(db, chat_id=CHAT_ID, fact_id=fid,
                                       anchor_item=anchor)
        assert ok is True
        mapping = await db.resolve_source_ref_ids(
            CHAT_ID, [("graph_fact", str(fid))])
        links = await provenance.get_evidence_links(
            db, mapping[("graph_fact", str(fid))])
        assert any(l["link_type"] == "contradicts" for l in links)


# ── T-4717: типизация/валидатор ссылок ──────────────────────────────────────

class TestLinkTyping:
    def test_anchor_source_ref_message_and_fact(self):
        m = ev.anchor_source_ref(CHAT_ID, _cand("x", tg=42))
        assert m.entity_type == "message" and m.tg_message_id == 42
        f = ev.anchor_source_ref(CHAT_ID, _cand("x", tg=None, fid=9))
        assert f.entity_type == "graph_fact" and f.entity_id == "9"

    def test_validate_links_duplicate(self):
        a = _cand("первый", tg=5)
        b = _cand("второй", tg=5)
        lv = ev.validate_links([a, b])
        assert lv.duplicates and not lv.ok

    def test_validate_links_unresolved_when_not_registered(self):
        a = _cand("факт", tg=5)
        lv = ev.validate_links([a], existing_pairs=set())
        assert lv.unresolved and not lv.ok

    @pytest.mark.asyncio
    async def test_record_anchor_items_typed_both_groups(self, db):
        fid = await db.insert_graph_fact(CHAT_ID, "парадигма", "derived_belief",
                                         None, kind="belief")
        anchors = [_cand("историческое сообщение", tg=777),
                   _cand("старый факт", tg=None, fid=555)]
        res = await ev.record_anchor_items_provenance(
            db, fact_id=fid, chat_id=CHAT_ID, anchor_items=anchors)
        assert res["recorded"] == 2
        mapping = await db.resolve_source_ref_ids(
            CHAT_ID, [("graph_fact", str(fid))])
        links = await provenance.get_evidence_links(
            db, mapping[("graph_fact", str(fid))])
        types = {await _entity_type(db, l["source_ref_id"]) for l in links}
        assert types == {"message", "graph_fact"}


async def _entity_type(db, ref_id):
    row = await provenance.get_source_ref(db, ref_id)
    return row["entity_type"]


# ── T-4719: версии / идемпотентность ────────────────────────────────────────

class TestVersions:
    def test_dedup_key_stable(self):
        from services.dream_worker import _deep_dedup_key
        a = [_cand("Толян литрбол", tg=1)]
        b = [_cand("Толян литрбол", tg=1)]
        assert _deep_dedup_key("текст", a) == _deep_dedup_key("текст", b)

    def test_find_supersede_candidate_topic_overlap(self):
        import json
        rows = [{"id": 10, "fact": "Толян литрбол каждый вечер",
                 "belief_meta": json.dumps({"type": "paradigm"})}]
        got = ev.find_supersede_candidate(rows, "Толян литрбол изменился")
        assert got == 10

    @pytest.mark.asyncio
    async def test_link_supersedes_and_old_readable(self, db):
        old = await db.insert_graph_fact(CHAT_ID, "старая версия",
                                         "derived_belief", None, kind="belief")
        new = await db.insert_graph_fact(CHAT_ID, "новая версия",
                                         "derived_belief", None, kind="belief")
        ok = await ev.link_supersedes(db, chat_id=CHAT_ID, new_fact_id=new,
                                      old_fact_id=old, claim_key="k")
        assert ok is True
        mapping = await db.resolve_source_ref_ids(
            CHAT_ID, [("graph_fact", str(new))])
        links = await provenance.get_evidence_links(
            db, mapping[("graph_fact", str(new))])
        assert any(l["link_type"] == "supersedes" for l in links)
        # старая версия читаема (не затёрта).
        assert await db.get_graph_fact(old) is not None


# ── T-4720: очередь пересмотра ──────────────────────────────────────────────

class TestRevisionQueue:
    def setup_method(self):
        ev.reset_revision_queue()

    def test_cap_bounded(self):
        q = ev.RevisionQueue(cap=3)
        assert q.enqueue([1, 2, 3, 4, 5]) == 3
        assert q.size == 3

    def test_priority_and_drain(self):
        q = ev.RevisionQueue(cap=5)
        q.enqueue(["low"], priority=0)
        q.enqueue(["high"], priority=10)
        assert q.drain(limit=1) == ["high"]

    def test_paused_resume(self):
        q = ev.RevisionQueue(cap=5)
        q.pause()
        assert q.enqueue([1]) == 0
        q.resume()
        assert q.enqueue([1]) == 1

    def test_kill_switch_off_no_enqueue(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_revision_queue_enabled",
                            lambda: False)
        assert ev.enqueue_dependent_revisions([1, 2]) == 0

    def test_kill_switch_on_enqueue(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_revision_queue_cap",
                            lambda: 2)
        assert ev.enqueue_dependent_revisions([1, 2, 3]) == 2


# ── T-4722: область/время применимости ──────────────────────────────────────

class TestApplicability:
    def test_merge_applicability_additive(self):
        meta = {"type": "paradigm", "dedup_key": "x"}
        merged = ev.merge_applicability(
            meta, applicability=ev.build_applicability(
                scope="Толян", valid_from=NOW - 100, valid_to=NOW,
                narrowed=True))
        assert merged["applicability_scope"] == "Толян"
        assert merged["valid_from"] == NOW - 100
        assert merged["valid_to"] == NOW
        assert merged["type"] == "paradigm"      # существующее не потеряно

    def test_nullable_when_not_narrowed(self):
        app = ev.build_applicability()
        assert app["applicability_scope"] is None
        assert app["valid_from"] is None and app["valid_to"] is None
        assert "narrowed" not in app

    @pytest.mark.asyncio
    async def test_no_ddl_count_paradigms_still_works(self, db):
        await db.insert_graph_fact(CHAT_ID, "п1", "derived_belief", None,
                                   kind="belief")
        n = await db.count_paradigms(CHAT_ID)
        assert isinstance(n, int)


# ── T-4713/T-4714: интеграция worker ────────────────────────────────────────

PARADIGM_ANSWER = (
    '{"paradigms":[{"text":"Толян изменил привычки литрбол",'
    '"anchors":[1,2]}]}')


class TestWorkerIntegration:
    @pytest.mark.asyncio
    async def test_insufficient_evidence_two_retellings(self, db, monkeypatch):
        # 2 якоря одного сообщения → independence=1 < 2 → insufficient_evidence.
        a = _cand("Толян пил литрбол", tg=7)
        b = _cand("Толян пил литрбол пересказ", tg=7)
        w = _worker(db, _Sel([a, b]), _FakeLLM(), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "insufficient_evidence"
        assert out["paradigms"] == 0

    @pytest.mark.asyncio
    async def test_random_old_fact_no_subject_insufficient(self, db,
                                                           monkeypatch):
        a = _cand("погода в нью-йорке холодная", tg=1)
        b = _cand("курс доллара вырос", tg=2)
        w = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "insufficient_evidence"

    @pytest.mark.asyncio
    async def test_bridge_pass_writes_and_meta_independent(self, db,
                                                           monkeypatch):
        a = _cand("Толян пил литрбол каждую пятницу", tg=1)
        b = _cand("Толян рассказывал про литрбол друзьям", tg=2)
        w = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written" and out["paradigms"] == 1
        rows = await db.list_recent_beliefs(chat_id=CHAT_ID, limit=10,
                                            belief_type="paradigm")
        assert rows
        meta = w._belief_meta(rows[0])
        assert meta.get("independent_events") == 2
        assert meta.get("bot_self_excluded") == 0
        assert "dedup_key" in meta

    @pytest.mark.asyncio
    async def test_repeat_run_idempotent_no_new_records(self, db,
                                                        monkeypatch):
        a = _cand("Толян пил литрбол каждую пятницу", tg=1)
        b = _cand("Толян рассказывал про литрбол друзьям", tg=2)
        w1 = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out1 = await w1._run_deep_once(CHAT_ID, manual=True)
        assert out1["status"] == "written"
        first_total = await db.count_paradigms(CHAT_ID)
        w2 = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out2 = await w2._run_deep_once(CHAT_ID, manual=True)
        assert out2["status"] == "duplicate"
        assert await db.count_paradigms(CHAT_ID) == first_total

    @pytest.mark.asyncio
    async def test_narrowed_applicability_in_belief_meta(self, db,
                                                        monkeypatch):
        a = _cand("Толян больше не пьёт литрбол", tg=1)
        b = _cand("Толян бросил литрбол привычку", tg=2)
        w = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        rows = await db.list_recent_beliefs(chat_id=CHAT_ID, limit=10,
                                            belief_type="paradigm")
        meta = w._belief_meta(rows[0])
        assert meta.get("applicability_scope")
        assert meta.get("valid_from") is not None
        assert meta.get("valid_to") is not None

    @pytest.mark.asyncio
    async def test_evidence_typing_off_legacy_min_anchors(self, db,
                                                         monkeypatch):
        # OFF → прежнее поведение: 2 якоря (пусть один пересказ) проходят
        # порог по числу, без independence-гейта.
        a = _cand("Толян пил литрбол", tg=7)
        b = _cand("Толян пил литрбол пересказ", tg=7)
        monkeypatch.setattr(mca_gates, "dream_evidence_typing_enabled",
                            lambda: False)
        w = _worker(db, _Sel([a, b]), _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "ok"


# ── T-4718: раскрытие цепочки (реальный API/БД) ─────────────────────────────

class TestChainDisclosure:
    @pytest.mark.asyncio
    async def test_chain_resolves_to_message_and_delta(self, db):
        anchors = [_cand("историческое сообщение про литрбол", tg=555),
                   _cand("старый факт про толяна", tg=None, fid=777)]
        fid = await db.insert_graph_fact(CHAT_ID, "новая парадигма",
                                         "derived_belief", None, kind="belief")
        await ev.record_anchor_items_provenance(
            db, fact_id=fid, chat_id=CHAT_ID, anchor_items=anchors)
        chain = await ev.expand_chain(db, chat_id=CHAT_ID, fact_id=fid)
        assert chain["fact_id"] == fid
        assert chain["delta"]["new"] == "новая парадигма"
        assert chain["messages"], "цепочка должна раскрываться до сообщения"
        assert chain["messages"][0]["tg_message_id"] == 555
        kinds = {a["entity_type"] for a in chain["anchors"]}
        assert "message" in kinds and "graph_fact" in kinds

    @pytest.mark.asyncio
    async def test_chain_delta_old_version(self, db):
        old = await db.insert_graph_fact(CHAT_ID, "старый вывод",
                                         "derived_belief", None, kind="belief")
        new = await db.insert_graph_fact(CHAT_ID, "новый вывод",
                                         "derived_belief", None, kind="belief",
                                         supersedes=old)
        chain = await ev.expand_chain(db, chat_id=CHAT_ID, fact_id=new)
        assert chain["delta"]["old"] == "старый вывод"
        assert chain["delta"]["supersedes_fact_id"] == old
