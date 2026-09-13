"""Раунд 10.14 (F1 anti-echo-self-reply, ADR-1014-2 D4/D9) — LLM-экстрактор.

Покрытие: нормализация/cap сути; prompt-константа; dedicated-роль reflection →
фоллбэк на основную модель при её отсутствии/ошибке; fail-safe (обе модели
упали → ''); статусы persona_state (ok/empty/error) best-effort.
"""
import pytest

from services import self_reflection
from services.self_reflection import (
    SELF_REFLECTION_PROMPT,
    _normalize_essence,
    extract_self_essence,
    record_extractor_status,
)


class _FakeLLM:
    """Мок LLMClient: настраиваемые ответы/исключения worker/generate."""

    def __init__(self, *, worker=None, worker_exc=None, gen=None, gen_exc=None):
        self.worker = worker
        self.worker_exc = worker_exc
        self.gen = gen
        self.gen_exc = gen_exc
        self.calls = []

    async def generate_worker(self, role, messages, *, temperature=None,
                              chat_id=None):
        self.calls.append(("worker", role))
        if self.worker_exc is not None:
            raise self.worker_exc
        return self.worker

    async def generate(self, messages, temperature=None, chat_id=None):
        self.calls.append(("generate",))
        if self.gen_exc is not None:
            raise self.gen_exc
        return self.gen or ""


class TestPrompt:
    def test_prompt_mentions_format_and_cap(self):
        assert "[Бот]" in SELF_REFLECTION_PROMPT
        assert "решил" in SELF_REFLECTION_PROMPT
        assert "300" in SELF_REFLECTION_PROMPT


class TestNormalize:
    def test_valid_format_kept(self):
        assert _normalize_essence("[Бот] решил: пить чай") == \
            "[Бот] решил: пить чай"

    def test_whitespace_collapsed(self):
        assert _normalize_essence("  [Бот]   решил:\n\n  чай  ") == \
            "[Бот] решил: чай"

    def test_empty_and_none(self):
        assert _normalize_essence("") == ""
        assert _normalize_essence("   \n  ") == ""
        assert _normalize_essence(None) == ""

    def test_capped_to_300(self):
        raw = "x" * 500
        out = _normalize_essence(raw)
        assert len(out) == 300


class TestExtractSelfEssence:
    @pytest.mark.asyncio
    async def test_dedicated_role_used(self):
        statuses = []

        async def on_status(s):
            statuses.append(s)

        llm = _FakeLLM(worker="[Бот] посоветовал: гулять")
        out = await extract_self_essence(llm, "длинный ответ", chat_id=-1,
                                         on_status=on_status)
        assert out == "[Бот] посоветовал: гулять"
        assert llm.calls == [("worker", "reflection")]
        assert statuses == ["ok"]

    @pytest.mark.asyncio
    async def test_worker_missing_falls_back_to_generate(self):
        statuses = []

        async def on_status(s):
            statuses.append(s)

        llm = _FakeLLM(gen="[Бот] заявил: тест")
        llm.generate_worker = None                    # роль не зарегистрирована
        out = await extract_self_essence(llm, "ответ", on_status=on_status)
        assert out == "[Бот] заявил: тест"
        assert llm.calls == [("generate",)]
        assert statuses == ["ok"]

    @pytest.mark.asyncio
    async def test_worker_error_falls_back_to_generate(self):
        llm = _FakeLLM(worker_exc=ValueError("unknown worker role"),
                       gen="[Бот] решил: фоллбэк")
        out = await extract_self_essence(llm, "ответ")
        assert out == "[Бот] решил: фоллбэк"
        assert llm.calls == [("worker", "reflection"), ("generate",)]

    @pytest.mark.asyncio
    async def test_both_fail_returns_empty_error_status(self):
        statuses = []

        async def on_status(s):
            statuses.append(s)

        llm = _FakeLLM(worker_exc=ValueError("boom"),
                       gen_exc=RuntimeError("boom2"))
        out = await extract_self_essence(llm, "ответ", on_status=on_status)
        assert out == ""
        assert statuses == ["error"]

    @pytest.mark.asyncio
    async def test_empty_answer_skips_llm(self):
        statuses = []

        async def on_status(s):
            statuses.append(s)

        llm = _FakeLLM(worker="[Бот] решил: что-то")
        out = await extract_self_essence(llm, "   \n ", on_status=on_status)
        assert out == ""
        assert llm.calls == []
        assert statuses == ["empty"]

    @pytest.mark.asyncio
    async def test_worker_empty_marks_empty(self):
        statuses = []

        async def on_status(s):
            statuses.append(s)

        llm = _FakeLLM(worker="")
        out = await extract_self_essence(llm, "ответ", on_status=on_status)
        assert out == ""
        assert statuses == ["empty"]


class _FakeConn:
    def __init__(self, store):
        self.store = store

    async def execute(self, sql, *args):
        self.store.append((sql, args))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self):
        self.calls = []

    def acquire(self):
        return _FakeConn(self.calls)


class TestRecordExtractorStatus:
    @pytest.mark.asyncio
    async def test_upserts_persona_state(self, monkeypatch):
        pool = _FakePool()
        monkeypatch.setattr(self_reflection, "_persona_pool", lambda: pool)
        await record_extractor_status("ok")
        assert len(pool.calls) == 1
        sql, args = pool.calls[0]
        assert "persona_state" in sql and "ON CONFLICT (id)" in sql
        assert args == ("ok", None)

    @pytest.mark.asyncio
    async def test_error_capped_and_passed(self, monkeypatch):
        pool = _FakePool()
        monkeypatch.setattr(self_reflection, "_persona_pool", lambda: pool)
        await record_extractor_status("error", "x" * 1000)
        _, args = pool.calls[0]
        assert args[0] == "error"
        assert len(args[1]) == 500

    @pytest.mark.asyncio
    async def test_no_pool_is_noop(self, monkeypatch):
        monkeypatch.setattr(self_reflection, "_persona_pool", lambda: None)
        await record_extractor_status("ok")            # не бросает

    @pytest.mark.asyncio
    async def test_never_raises_on_db_error(self, monkeypatch):
        class _BoomPool:
            def acquire(self):
                raise RuntimeError("db down")

        monkeypatch.setattr(self_reflection, "_persona_pool", lambda: _BoomPool())
        await record_extractor_status("error", "x")     # не бросает
