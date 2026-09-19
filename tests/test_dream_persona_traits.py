"""Раунд 10.14 (F2 persona-storage-core) — тесты «эволюции характера».

Покрытие (spec §3.4): парсер PERSONA_EVOLUTION_PROMPT-ответа, вызов
`DeepSleepWorker._run_persona_traits_once` (ok/empty/error), дедуп/cap
делегируются `bot_persona.append_traits`, fail-open.
"""
import pytest

from services import bot_persona
from services.dream_prompts import (
    PERSONA_EVOLUTION_PROMPT,
    build_persona_user,
    parse_persona_traits,
)
from services.dream_worker import DreamWorker

CHAT_ID = -1001234567890


class _FakeDB:
    def __init__(self, self_facts=None, beliefs=None, tokens_by_kind=None):
        self.self_facts = list(self_facts or [])
        self.beliefs = list(beliefs or [])
        self.tokens_by_kind = dict(tokens_by_kind or {})
        self.calls = []
        self.events = []

    async def get_dream_candidates(self, chat_id, now_ts, *, origins,
                                   since_id=0, since_ts=None, limit=1000):
        self.calls.append(("candidates", tuple(origins)))
        return list(self.self_facts)

    async def list_recent_beliefs(self, chat_id=None, limit=50, status=None,
                                  belief_type=None):
        return list(self.beliefs)

    async def sum_dream_log_tokens(self, since_ts, kind=None):
        return int(self.tokens_by_kind.get(kind, 0))

    async def log_dream_event(self, chat_id, run_at, *, kind, tokens=0,
                              status=None, **kwargs):
        self.events.append((kind, int(tokens), status))
        return len(self.events)


class _FakeLLM:
    def __init__(self, raw="[]", error=None):
        self.raw = raw
        self.error = error
        self.calls = []

    async def generate_worker(self, role, messages, temperature=None):
        self.calls.append((role, messages))
        if self.error:
            raise self.error
        return self.raw


def _worker(db, llm):
    return DreamWorker(db=db, memory=None, llm=llm)


class TestParsePersonaTraits:
    def test_plain_array(self):
        assert parse_persona_traits('["a", "b"]') == ["a", "b"]

    def test_object_wrapper(self):
        assert parse_persona_traits('{"traits": ["x"]}') == ["x"]

    def test_fenced_and_nested_dict(self):
        raw = '```json\n[{"text": "стал циничнее"}]\n```'
        assert parse_persona_traits(raw) == ["стал циничнее"]

    def test_empty(self):
        assert parse_persona_traits("") == []
        assert parse_persona_traits("[]") == []

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_persona_traits("не JSON совсем")

    def test_build_user_includes_sources(self):
        text = build_persona_user(
            [{"fact": "[Бот] решил: шутить"}], [{"fact": "любит грибы"}])
        assert "шутить" in text and "грибы" in text
        assert PERSONA_EVOLUTION_PROMPT  # канон-константа существует


class TestRunPersonaTraits:
    @pytest.mark.asyncio
    async def test_ok_writes_traits(self, monkeypatch):
        written = {}

        async def _append(traits, *, chat_id, source):
            written["traits"] = list(traits)
            written["chat_id"] = chat_id
            written["source"] = source
            return len(traits)

        statuses = []

        async def _status(value):
            statuses.append(value)

        monkeypatch.setattr(bot_persona, "append_traits", _append)
        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB(self_facts=[{"fact": "[Бот] решил: шутить про грибы"}])
        llm = _FakeLLM('["стал чаще шутить"]')
        out = await _worker(db, llm)._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "ok", "traits": 1}
        assert written["traits"] == ["стал чаще шутить"]
        assert written["chat_id"] == CHAT_ID
        assert written["source"] == "deep_sleep"
        assert statuses == ["ok"]
        assert llm.calls and llm.calls[0][0] == "background"

    @pytest.mark.asyncio
    async def test_empty_sources_no_llm(self, monkeypatch):
        statuses = []

        async def _status(value):
            statuses.append(value)

        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB()
        llm = _FakeLLM()
        out = await _worker(db, llm)._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "empty", "traits": 0}
        assert llm.calls == []
        # F8/ADR-1024-5 D3: явная причина 'no_self_facts' вместо 'empty'.
        assert statuses == ["no_self_facts"]

    @pytest.mark.asyncio
    async def test_parse_error_sets_error(self, monkeypatch):
        statuses = []

        async def _status(value):
            statuses.append(value)

        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB(self_facts=[{"fact": "[Бот] решил: пошутить"}],
                     beliefs=[{"fact": "любит грибы"}])
        llm = _FakeLLM("вышел из чата")
        out = await _worker(db, llm)._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "error", "traits": 0}
        assert statuses == ["error"]

    @pytest.mark.asyncio
    async def test_llm_error_fail_open(self, monkeypatch):
        statuses = []

        async def _status(value):
            statuses.append(value)

        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB(self_facts=[{"fact": "[Бот] решил: x"}])
        llm = _FakeLLM(error=RuntimeError("down"))
        out = await _worker(db, llm)._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "error", "traits": 0}
        assert statuses == ["error"]

    @pytest.mark.asyncio
    async def test_beliefs_only_no_llm(self, monkeypatch):
        """Без self-фактов личность не оценивается по одному лору чата."""
        statuses = []

        async def _status(value):
            statuses.append(value)

        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB(beliefs=[{"fact": "любит грибы"}])
        llm = _FakeLLM('["стал циничнее"]')
        out = await _worker(db, llm)._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "empty", "traits": 0}
        assert llm.calls == []
        # F8/ADR-1024-5 D3: явная причина 'no_self_facts' вместо 'empty'.
        assert statuses == ["no_self_facts"]


class TestRunPersonaTraitsBudget:
    """R10.14-2: traits-LLM проходит бюджет/ledger (F2 §3.4 п.5)."""

    @pytest.mark.asyncio
    async def test_budget_skip_no_llm(self, monkeypatch):
        """Превышение капа → traits-LLM не вызывается (fail-safe skip)."""
        statuses = []

        async def _status(value):
            statuses.append(value)

        async def _no_budget(chat_id, prompt_text, *, extra_tokens=0,
                             manual=False):
            return False

        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB(self_facts=[{"fact": "[Бот] решил: x"}])
        llm = _FakeLLM('["стал циничнее"]')
        worker = _worker(db, llm)
        monkeypatch.setattr(worker, "_deep_budget_ok", _no_budget)
        out = await worker._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "budget", "traits": 0}
        assert llm.calls == []
        assert statuses == ["budget_skip"]
        assert db.events == [("deep_traits", 0, "budget_skip")]

    @pytest.mark.asyncio
    async def test_tokens_logged_as_deep_traits(self, monkeypatch):
        """Токены traits логируются в memory_dream_log(kind='deep_traits')."""
        async def _append(traits, *, chat_id, source):
            return len(traits)

        async def _status(value):
            pass

        async def _ok(chat_id, prompt_text, *, extra_tokens=0, manual=False):
            return True

        monkeypatch.setattr(bot_persona, "append_traits", _append)
        monkeypatch.setattr(bot_persona, "record_trait_status", _status)
        db = _FakeDB(self_facts=[{"fact": "[Бот] решил: шутить"}])
        llm = _FakeLLM('["стал чаще шутить"]')
        worker = _worker(db, llm)
        monkeypatch.setattr(worker, "_deep_budget_ok", _ok)
        out = await worker._run_persona_traits_once(CHAT_ID)
        assert out == {"status": "ok", "traits": 1}
        assert len(db.events) == 1
        kind, tokens, status = db.events[0]
        assert kind == "deep_traits" and tokens > 0 and status == "done"

    @pytest.mark.asyncio
    async def test_deep_budget_includes_traits_tokens(self, monkeypatch):
        """Суточный кап видит уже потраченные deep_traits-токены."""
        db = _FakeDB(tokens_by_kind={"deep_traits": 10 ** 9})
        worker = _worker(db, _FakeLLM())

        async def _consume(*args, **kwargs):
            raise AssertionError("consume не должен вызываться при капе")

        from services import worker_budget
        monkeypatch.setattr(worker_budget, "consume", _consume)
        assert await worker._deep_budget_ok(CHAT_ID, "prompt") is False
