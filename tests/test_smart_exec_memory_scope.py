"""SMART-EXECUTION-RELIABILITY-01 — I6/I7: chat-scope KNN и correction frame.

Покрытие (owner input §I6/§I7, `requirements-map` SXR-I6-01, SXR-I6-02,
SXR-I7-01):

  * retrieval изолирован по разрешённому chat scope ДО effective top-K:
    чужие чаты физически не входят в KNN-выдачу и не занимают k до cap —
    float и int8 пути archive-поиска, RAG-кандидаты graph_facts и dedup;
    решение не опирается на рост `k_last`, не требует DDL/переиндексации и
    сохраняет существующие эмбеддинги/corpus;
  * correction frame передаёт ПОЛНЫЙ текст содержательного утверждения и
    цитаты (никакого символьного капа 800 и никакой замены другим cap);
  * `style_policy outcome=success` с удалением конечной точки — штатное
    успешное применение действующей речевой настройки, а не дефект: проход
    не меняет политику речи/кавычки/мат/пользовательские настройки.

TEST-LIFECYCLE: CONTRACT (SXR-I6-01/I6-02/I7-01)
R17: синтетические векторы/факты; реальные переписки не используются.
"""
from __future__ import annotations

import logging
import time

import pytest

from services import chat_params
from services import hot_config as hot
from services import mca_gates
from services import style_policy as sp
from services.database import DatabaseService
from services.summary_memory import _KNN_SCOPE_K_CAP
from tests.test_asap8_v6_d06_isolation import (
    VecLLM,
    _init_memory,
    _mix,
    _seed_archive,
    _seed_graph_vec,
    _unit,
)
from tests.test_direct_chat import FakeDB, FakeMemory, _make_service, _message

CHAT_A = -100
CHAT_B = -200


async def _db(tmp_path, name: str = "i6_scope.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ── chat-scope KNN (SXR-I6-01) ──────────────────────────────────────────────


class TestChatScopeKnn:
    @pytest.mark.asyncio
    async def test_archive_float_scope_beats_foreign_dominance(
            self, tmp_path, monkeypatch):
        """60 чужих фактов ближе своих не вытесняют свой чат: exact scope до
        top-K. На старом коде (глобальный KNN → фильтр после k) при cap=8
        выдача была бы пустой/partial."""
        monkeypatch.setattr(
            "services.summary_memory._KNN_SCOPE_K_CAP", 8)
        d = await _db(tmp_path)
        try:
            memory = await _init_memory(d, VecLLM(), monkeypatch, int8=False)
            own = [f"свой факт #{i}" for i in range(3)]
            await _seed_archive(
                d, memory,
                [(CHAT_A, text, _mix(0.98, 0.2)) for text in own]
                + [(CHAT_B, f"чужой факт #{i}", _unit(0)) for i in range(60)])
            facts, tele = await memory._search_archive_knn_scoped(
                CHAT_A, _unit(0), 3)
            assert set(facts) == set(own)
            assert tele["scope"] == "rowid"
            assert tele["filtered_other_chat"] == 0
            assert tele["partial"] is False
            assert tele["k_last"] <= _KNN_SCOPE_K_CAP
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_archive_int8_scope_beats_foreign_dominance(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "services.summary_memory._KNN_SCOPE_K_CAP", 8)
        d = await _db(tmp_path)
        try:
            memory = await _init_memory(d, VecLLM(), monkeypatch, int8=True)
            assert memory._vec_int8 is True
            own = [f"int8 свой факт #{i}" for i in range(3)]
            await _seed_archive(
                d, memory,
                [(CHAT_A, text, _mix(0.98, 0.2)) for text in own]
                + [(CHAT_B, f"int8 чужой #{i}", _unit(0)) for i in range(60)])
            facts, tele = await memory._search_archive_knn_scoped(
                CHAT_A, _unit(0), 3)
            assert set(facts) == set(own)
            assert tele["scope"] == "rowid"
            assert tele["filtered_other_chat"] == 0
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_graph_facts_candidates_are_chat_scoped(
            self, tmp_path, monkeypatch):
        """RAG-кандидаты graph_facts: чужие ближайшие не занимают fetch_k."""
        from config.settings import settings
        monkeypatch.setattr(
            "services.summary_memory._KNN_SCOPE_K_CAP", 8)
        d = await _db(tmp_path)
        try:
            memory = await _init_memory(d, VecLLM(), monkeypatch, int8=False)
            memory._vec_available = True
            now = int(time.time())
            own_ids = []
            for i in range(2):
                fid = await d.insert_graph_fact(
                    CHAT_A, f"свой факт графа #{i}", "search_fact",
                    now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
                own_ids.append(fid)
                await _seed_graph_vec(
                    memory, fid, CHAT_A, _mix(0.98, 0.2), now + 1000)
            for i in range(40):
                fid = await d.insert_graph_fact(
                    CHAT_B, f"чужой факт графа #{i}", "search_fact",
                    now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
                await _seed_graph_vec(memory, fid, CHAT_B, _unit(0), now + 1000)
            cands = await memory._vec_candidates(
                CHAT_A, _unit(0), 2, True, now, include_self=True)
            assert {fid for fid, _cos, _vec in cands} == set(own_ids)
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_dedup_foreign_crowd_cannot_hide_own_fact(
            self, tmp_path, monkeypatch):
        from config.settings import settings
        d = await _db(tmp_path)
        try:
            memory = await _init_memory(d, VecLLM(), monkeypatch, int8=False)
            now = int(time.time())
            own_id = await d.insert_graph_fact(
                CHAT_A, "озон поставляет быстрее чем wildberries", "search_fact",
                now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
            await _seed_graph_vec(memory, own_id, CHAT_A, _mix(0.96, 0.28),
                                  now + 1000)
            for i in range(250):
                fid = await d.insert_graph_fact(
                    CHAT_B, f"сосед доставляет быстрее чем amazon #{i}",
                    "search_fact", now + 1000,
                    weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
                await _seed_graph_vec(memory, fid, CHAT_B, _unit(0), now + 1000)
            rows = await memory._dedup_knn(CHAT_A, _unit(0))
            assert [row["fact_id"] for row in rows] == [own_id]
            assert all(row["chat_id"] == CHAT_A for row in rows)
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_dedup_own_ttl_refill_without_foreign_substitute(
            self, tmp_path, monkeypatch):
        """Добор остаётся честным для TTL своего чата: чужие не подставляются
        вместо просроченных своих, живые свои находятся стадийно."""
        from config.settings import settings
        d = await _db(tmp_path)
        try:
            memory = await _init_memory(d, VecLLM(), monkeypatch, int8=False)
            now = int(time.time())
            for i in range(5):
                fid = await d.insert_graph_fact(
                    CHAT_A, f"просроченный свой #{i}", "search_fact",
                    now - 10, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
                await _seed_graph_vec(memory, fid, CHAT_A, _unit(0), now - 10)
            live_ids = []
            for i in range(3):
                fid = await d.insert_graph_fact(
                    CHAT_A, f"живой свой #{i}", "search_fact",
                    now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
                live_ids.append(fid)
                await _seed_graph_vec(memory, fid, CHAT_A, _mix(0.9, 0.4),
                                      now + 1000)
            for i in range(250):
                fid = await d.insert_graph_fact(
                    CHAT_B, f"чужой живой #{i}", "search_fact",
                    now + 1000, weight=settings.GRAPH_FACT_WEIGHT_ARCHIVE)
                await _seed_graph_vec(memory, fid, CHAT_B, _unit(0), now + 1000)
            rows = await memory._dedup_knn(CHAT_A, _unit(0))
            found = {row["fact_id"] for row in rows}
            assert found == set(live_ids)
            assert all(row["chat_id"] == CHAT_A for row in rows)
            assert all(row["expires_at"] is not None
                       and row["expires_at"] > now for row in rows)
        finally:
            await d.close()


# ── correction frame: полный текст (SXR-I6-02) ─────────────────────────────


class _Cache:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


@pytest.fixture
def speech_on():
    saved = hot.get_config_cache()
    hot.set_config_cache(
        _Cache({"flags.context_speech_projection": True}))
    yield
    hot.set_config_cache(saved)


BOT_ID = 424242


def _bot_msg(tg_id, text):
    from unittest.mock import MagicMock
    reply = MagicMock()
    reply.message_id = tg_id
    reply.text = text
    reply.caption = None
    reply.from_user = MagicMock()
    reply.from_user.id = BOT_ID
    reply.from_user.first_name = "Adminbot"
    return reply


def _quote(text):
    from unittest.mock import MagicMock
    q = MagicMock()
    q.text = text
    return q


def _trigger(text, *, message_id=900, reply=None, quote=None):
    message = _message(text=text, message_id=message_id, chat_id=CHAT_A)
    message.chat.type = "supergroup"
    message.reply_to_message = reply
    message.quote = quote
    message.date = None
    return message


def _long_text(prefix: str, length: int = 2981) -> str:
    tail = " ХВОСТ-УТВЕРЖДЕНИЯ-НЕ-ДОЛЖЕН-ПОТЕРЯТЬСЯ"
    filler = "содержательное утверждение человека без искусственного среза "
    fill = max(0, length - len(tail) - len(prefix))
    body = (filler * ((fill // len(filler)) + 2))[:fill]
    return prefix + body + tail


async def _payload(*, window=(), db=None, message=None):
    svc = _make_service(memory=FakeMemory(window=list(window)),
                        db=db or FakeDB({}), bot_id=BOT_ID,
                        bot_username="probe_bot")
    from services.canonical_context import SpeechProjection
    projection = SpeechProjection(run_id="i6-run")
    blocks = await svc._build_user_content(
        CHAT_A, message or _trigger("ну?"), "Никита", target_user_id=11,
        projection=projection)
    return "\n".join(str(b) for b in blocks if b)


def _frame(payload: str) -> str:
    start = payload.find("<Correction_Frame")
    assert start >= 0, payload[:400]
    end = payload.find("</Correction_Frame>", start)
    return payload[start:end + len("</Correction_Frame>")]


class TestCorrectionFrameFullText:
    @pytest.mark.asyncio
    async def test_long_own_claim_is_not_truncated(self, speech_on, caplog):
        """2981-символьное утверждение (прод-лог `chars=2981 -> 800`) доходит
        целиком: хвост за 800-м символом присутствует в рамке."""
        claim = _long_text("Моё утверждение: ")
        assert len(claim) == 2981
        with caplog.at_level(logging.WARNING,
                             logger="services.direct_chat_service"):
            payload = await _payload(
                message=_trigger("это не так", reply=_bot_msg(5001, claim)))
        frame = _frame(payload)
        assert " ХВОСТ-УТВЕРЖДЕНИЯ-НЕ-ДОЛЖЕН-ПОТЕРЯТЬСЯ" in frame
        assert claim in frame
        assert len(frame) > 2900
        assert "correction frame claim truncated" not in caplog.text
        assert "correction frame quote truncated" not in caplog.text

    @pytest.mark.asyncio
    async def test_long_quote_is_not_truncated(self, speech_on):
        quote = _long_text("Цитата: ")
        payload = await _payload(
            message=_trigger("вот именно это", reply=_bot_msg(5002, "коротко"),
                             quote=_quote(quote)))
        frame = _frame(payload)
        assert " ХВОСТ-УТВЕРЖДЕНИЯ-НЕ-ДОЛЖЕН-ПОТЕРЯТЬСЯ" in frame
        assert quote in frame


# ── I7: style_policy success — штатное применение настройки ────────────────


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes: list = []

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value
        self.writes.append((key, value))

    def set_many(self, items):
        self.writes.append(("set_many", len(items)))


class _FakeChatCache:
    def __init__(self):
        self.writes: list = []

    async def get_chat_params(self, chat_id):
        return {"overrides": {}}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None


@pytest.fixture(autouse=True)
def _clean_policy_state():
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    yield
    sp.reset_repetition_state()
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)


class TestStylePolicySuccessIsNormal:
    @pytest.mark.asyncio
    async def test_trailing_period_removal_is_success_not_defect(
            self, monkeypatch):
        """Активная настройка «без точки в конце»: текст теряет ТОЛЬКО
        конечную точку; событие — success/repaired=1; политика/настройки не
        переписываются."""
        from tests.test_soul1_style_policy import doc_with
        monkeypatch.setenv("SPEECH_STYLE_POLICY_ENABLED", "1")
        doc = doc_with("no_trailing_period")
        fake_hot = _FakeHot({"flags.speech_style_policy_enabled": True,
                             sp.DOC_KEY: doc})
        fake_chat = _FakeChatCache()
        hot.set_config_cache(fake_hot)
        chat_params.set_chat_params_cache(fake_chat)
        assert mca_gates.speech_style_policy_enabled() is True

        source = "Ну да, логично."
        outcome = await sp.apply_style_policy(source, chat_id=CHAT_A)
        assert outcome.applied is True
        assert outcome.text == "Ну да, логично"
        assert source[:-1] == outcome.text          # только конечная точка
        assert outcome.repaired == 1
        fired = {row["kind"]: row for row in sp.fired_rules(outcome)}
        assert fired["trailing_period"]["status"] == sp.STATUS_REPAIRED

        status, payload = sp.style_event_payload(outcome)
        assert status == "success"
        assert payload["repaired"] == 1
        assert any(row["kind"] == "trailing_period"
                   for row in payload["rules"])
        # Никаких записей настроек/политики: успешный проход ничего не меняет.
        assert fake_hot.writes == []
        assert fake_chat.writes == []
        assert fake_hot.get(sp.DOC_KEY) == doc
