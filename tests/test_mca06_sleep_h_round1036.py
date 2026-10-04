"""mca-06-sleep-paradigms — блок H (round 10.36) targeted-тесты.

Покрытие по контрактам (spec.md §8.6/§8.7, ADR-1028-9 AM-2/AM-3,
threat-failure THR-8/THR-9; tasks T-4729/T-4730):
  * T-4729 — отрицательная граница ядра характера: DreamWorker (обе traits-ветки
    + ветка парадигм) не имеет write-пути к ядру владельца; пишет только
    derived-слой (`origin='derived_belief'`, `bot_persona.append_traits`).
  * T-4730 — `DreamRandomSource.pick` — единственный путь выбора материала;
    детерминированный равномерный (seed=(pipeline_run_id, chat_id)); selection
    в отчёте; случайность выбирает только материал, вердикт — по доказательствам;
    kill-switch OFF → обычный ранжированный пайплайн.
"""
import asyncio
import inspect
import json
import time

import pytest

import services.dream_worker as dw
import services.mca_dream_history as hist
from config.settings import Settings
from services import bot_persona
from services import chat_params
from services import mca_dream_evidence as mca_evidence
from services import mca_dream_random
from services import mca_gates
from services.database import DatabaseService
from services.dream_worker import DreamWorker

CHAT_ID = -100
NOW = int(time.time())
DAY = 86400


# ── фикстуры/хелперы ────────────────────────────────────────────────────────

@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


class _Mem:
    _vec_available = False

    async def retrieve_fact_candidates(self, *a, **k):
        return []

    async def get_rag_facts(self, *a, **k):
        return []


class _ProfileMem:
    """Память для прямого вызова исторического профиля."""

    _vec_available = False

    def __init__(self, rows):
        self._rows = list(rows)

    async def retrieve_fact_candidates(self, chat_id, query, limit=20):
        return list(self._rows)[: int(limit)]


class _Sel:
    def __init__(self, candidates, *, missing_timestamp=0, fts_fallback=False,
                 reason=None, selection_meta=None):
        self.candidates = list(candidates)
        self.missing_timestamp = missing_timestamp
        self.fts_fallback = fts_fallback
        self.reason = reason
        self.selection_meta = selection_meta


def _cand(fact, *, tg=None, days_old=200, fid=None):
    return {"id": fid if fid is not None else abs(hash(fact)) % 100000,
            "chat_id": CHAT_ID, "fact": fact, "origin": "chat_history",
            "rag_ts": NOW - days_old * DAY,
            "message_timestamp": NOW - days_old * DAY,
            "created_at": NOW - days_old * DAY, "tg_message_id": tg,
            "target_user": "Толян"}


def _packet(texts):
    return {"beliefs": [{"fact": texts[0], "id": 1, "target_user": "Толян",
                         "created_at": NOW - 3600}],
            "recent": [{"fact": t, "importance": 5} for t in texts[1:]],
            "source_ids": [1]}


PARADIGM_ANSWER = (
    '{"paradigms":[{"text":"Толян изменил привычки литрбол",'
    '"anchors":[1,2]}]}')


BRIDGE_ANCHORS = [
    _cand("Толян пил литрбол каждую пятницу", tg=1),
    _cand("Толян рассказывал про литрбол друзьям", tg=2),
]


class _FakeLLM:
    def __init__(self, *answers):
        self._answers = list(answers)

    async def generate_worker(self, role, messages, temperature=None):
        if self._answers:
            return self._answers.pop(0)
        return '{"paradigms":[]}'

    async def generate(self, messages, temperature=None, chat_id=None):
        return '{"beliefs":[]}'


def _worker(db, sel, llm, monkeypatch, *, packet=None, select_kwargs=None):
    monkeypatch.setattr(mca_gates, "dream_gate_resolver_enabled",
                        lambda: False)
    monkeypatch.setattr(dw.mca_gates, "dream_gate_resolver_enabled",
                        lambda: False)

    async def _fake_select(*a, **k):
        if select_kwargs is not None:
            select_kwargs.update(k)
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


# ── T-4729: граница ядра характера (AM-3, THR-8) ────────────────────────────

class TestCharacterCoreBoundary:
    def test_boundary_contract_declares_mca18_zone(self):
        boundary = mca_evidence.character_core_boundary()
        assert boundary["core_zone"] == "mca-18"
        assert "save_persona" in boundary["forbidden_core_api"]
        assert "append_traits" in boundary["allowed_derived_api"]
        assert mca_evidence.character_core_write_blocked("save_persona")
        assert not mca_evidence.character_core_write_blocked("append_traits")

    def test_dream_worker_has_no_core_write_path(self):
        w = DreamWorker(db=None, memory=None, llm=None)
        for api in mca_evidence.CHARACTER_CORE_WRITE_API:
            assert not hasattr(w, api), f"DreamWorker не должен иметь {api}"
        # структурно: sleep-контур не ссылается на write-API ядра mca-18.
        src = inspect.getsource(dw)
        for api in mca_evidence.CHARACTER_CORE_WRITE_API:
            assert api not in src, f"dream_worker.py не должен звать {api}"

    @pytest.mark.asyncio
    async def test_both_traits_branches_write_derived_not_core(
            self, db, monkeypatch):
        core_writes: list = []
        derived: list = []

        async def _core_write(*a, **k):
            core_writes.append(a[:1])
            raise AssertionError("write ядра характера из сна недопустим")

        for name in sorted(mca_evidence.CHARACTER_CORE_WRITE_API):
            if hasattr(bot_persona, name):
                monkeypatch.setattr(bot_persona, name, _core_write)

        async def _append(traits, *, chat_id, source="deep_sleep"):
            derived.append(("append_traits", list(traits)))
            return len(traits)

        async def _status(value):
            derived.append(("record_trait_status", value))

        monkeypatch.setattr(bot_persona, "append_traits", _append)
        monkeypatch.setattr(bot_persona, "record_trait_status", _status)

        async def _gate(chat_id, key, default=None):
            return True

        monkeypatch.setattr(chat_params, "get_chat_param", _gate)

        async def _cands(chat_id, now_ts, *, origins, **k):
            if tuple(origins) == ("bot_self_reply",):
                return [{"fact": "[Бот] решил шутить про грибы"}]
            return []

        async def _beliefs(*a, **k):
            return []

        monkeypatch.setattr(db, "get_dream_candidates", _cands)
        monkeypatch.setattr(db, "list_recent_beliefs", _beliefs)

        class _RoleLLM:
            async def generate_worker(self, role, messages, temperature=None):
                if role == "background":
                    return '["стал циничнее"]'
                return PARADIGM_ANSWER

        for fix in (True, False):
            monkeypatch.setattr(Settings, "DEEP_SLEEP_EXTRACT_FIX_ENABLED",
                                fix, raising=False)
            monkeypatch.setattr(mca_gates, "dream_random_explore_enabled",
                                lambda: False)
            core_writes.clear()
            derived.clear()
            cid = CHAT_ID if fix else CHAT_ID - 1
            w = DreamWorker(db, memory=_Mem(), llm=_RoleLLM())
            packet = _packet(["Толян литрбол"])

            async def _build(chat_id, now, since_ts):
                return packet

            monkeypatch.setattr(w, "_build_deep_packet", _build)

            async def _budget(*a, **k):
                return True

            monkeypatch.setattr(w, "_deep_budget_ok", _budget)

            async def _fake_select(*a, **k):
                return _Sel(list(BRIDGE_ANCHORS))

            monkeypatch.setattr(hist, "select_historical_candidates",
                                _fake_select)
            out = await w._run_deep_once(cid, manual=True)
            assert out["status"] == "written", (fix, out)
            assert core_writes == [], f"fix={fix}: write ядра недопустим"
            assert any(name == "append_traits" for name, _ in derived), \
                f"fix={fix}: derived-слой traits должен писаться"


# ── T-4730: DreamRandomSource (AM-2, THR-9) ─────────────────────────────────

class TestDreamRandomSource:
    def test_deterministic_uniform_same_seed_same_selection(self):
        pool = [_cand(f"f{i}", tg=i) for i in range(6)]
        src = mca_dream_random.default_source(42)
        a_items, a_meta = src.pick(pool, chat_id=CHAT_ID,
                                   purpose=mca_dream_random.PURPOSE_LESS_STUDIED,
                                   k=3)
        b_items, b_meta = src.pick(pool, chat_id=CHAT_ID,
                                   purpose=mca_dream_random.PURPOSE_LESS_STUDIED,
                                   k=3)
        assert [x["id"] for x in a_items] == [x["id"] for x in b_items]
        assert a_meta == b_meta
        assert a_meta["seed"] == [42, CHAT_ID]
        assert a_meta["pool"] == 6 and a_meta["k"] == 3
        assert len(set(a_meta["picked"])) == 3
        assert all(0 <= i < 6 for i in a_meta["picked"])

    def test_different_run_id_can_change_selection(self):
        pool = [_cand(f"f{i}", tg=i) for i in range(8)]
        seen = set()
        for run_id in range(6):
            items, _ = mca_dream_random.default_source(run_id).pick(
                pool, chat_id=CHAT_ID,
                purpose=mca_dream_random.PURPOSE_LESS_STUDIED, k=2)
            seen.add(tuple(x["id"] for x in items))
        assert len(seen) > 1, "разные seed должны давать разные выборки"

    def test_selection_meta_is_r17_safe(self):
        pool = [_cand("секретный текст события", tg=7)]
        items, meta = mca_dream_random.default_source(1).pick(
            pool, chat_id=CHAT_ID,
            purpose=mca_dream_random.PURPOSE_LESS_STUDIED, k=1)
        assert items and items[0]["fact"] == "секретный текст события"
        dumped = json.dumps(meta, ensure_ascii=False)
        assert "секретный" not in dumped
        assert meta["source"] == "deterministic_uniform"

    def test_interface_is_duck_typed(self):
        assert mca_dream_random.is_dream_random_source(
            mca_dream_random.default_source(1))
        assert not mca_dream_random.is_dream_random_source(object())

    @pytest.mark.asyncio
    async def test_select_uses_source_only_when_provided(self):
        pool = [_cand(f"c{i}", tg=i) for i in range(4)]
        mem = _ProfileMem(pool)
        # без источника — прежний ранжированный путь, selection_meta пуст
        plain = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "query", top_k=2, now=NOW, min_age_days=90)
        assert plain.selection_meta is None
        assert len(plain.candidates) == 2
        # с источником — выбор ТОЛЬКО через pick + meta
        src = mca_dream_random.default_source(99)
        rand = await hist.select_historical_candidates(
            mem, None, CHAT_ID, "query", top_k=2, now=NOW, min_age_days=90,
            random_source=src)
        assert rand.selection_meta is not None
        assert rand.selection_meta["seed"] == [99, CHAT_ID]
        assert rand.selection_meta["pool"] == 4
        assert len(rand.candidates) == 2
        picked_ids = {c["id"] for c in rand.candidates}
        assert picked_ids <= {c["id"] for c in pool}


class TestRandomExploreWiring:
    @pytest.mark.asyncio
    async def test_explore_on_passes_source_and_records_selection(
            self, db, monkeypatch):
        captured: dict = {}
        meta = {"source": "deterministic_uniform", "purpose": "less_studied",
                "seed": [7, CHAT_ID], "k": 2, "pool": 4, "picked": [0, 2]}
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS), selection_meta=meta),
                    _FakeLLM(PARADIGM_ANSWER), monkeypatch,
                    select_kwargs=captured)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        assert captured.get("random_source") is not None
        # выбор материала записан в отчёт §7.2 (R17-safe)
        cursor = await db.db.execute(
            "SELECT report_json FROM mca_pipeline_runs WHERE chat_id = ? "
            "ORDER BY started_at DESC LIMIT 1", (CHAT_ID,))
        rep = json.loads((await cursor.fetchone())["report_json"])
        assert rep["anchors"]["selection"]["seed"] == [7, CHAT_ID]
        assert rep["anchors"]["selection"]["k"] == 2
        assert "пил литрбол" not in json.dumps(rep, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_explore_off_no_source_ranked_parity(self, db, monkeypatch):
        monkeypatch.setattr(mca_gates, "dream_random_explore_enabled",
                            lambda: False)
        captured: dict = {}
        w = _worker(db, _Sel(list(BRIDGE_ANCHORS)), _FakeLLM(PARADIGM_ANSWER),
                    monkeypatch, select_kwargs=captured)
        out = await w._run_deep_once(CHAT_ID, manual=True)
        assert out["status"] == "written"
        assert captured.get("random_source") is None, \
            "OFF → выбор не вызывается (обычный пайплайн)"

    @pytest.mark.asyncio
    async def test_verdict_from_evidence_not_from_random_material(
            self, db, monkeypatch):
        # Разный случайный материал + одинаковый вердикт валидатора →
        # одинаковый статус; без доказательств → insufficient_evidence.
        import services.mca_dream_evidence as ev

        good = ev.BridgeValidation(ok=True)
        bad = ev.BridgeValidation(ok=False, reason="insufficient_evidence")

        monkeypatch.setattr(ev, "validate_bridge", lambda *a, **k: good)
        sel_a = _Sel([_cand("Толян пил литрбол A", tg=11),
                      _cand("Толян про литрбол B", tg=12)])
        sel_b = _Sel([_cand("Толян пил литрбол C", tg=21),
                      _cand("Толян про литрбол D", tg=22)])
        w_a = _worker(db, sel_a, _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out_a = await w_a._run_deep_once(CHAT_ID, manual=True)
        w_b = _worker(db, sel_b, _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out_b = await w_b._run_deep_once(CHAT_ID, manual=True)
        assert out_a["status"] == "written"
        assert out_b["status"] == "written"

        monkeypatch.setattr(ev, "validate_bridge", lambda *a, **k: bad)
        w_c = _worker(db, sel_a, _FakeLLM(PARADIGM_ANSWER), monkeypatch)
        out_c = await w_c._run_deep_once(CHAT_ID, manual=True)
        assert out_c["status"] == "insufficient_evidence"
        assert out_c["status"] != "written"
