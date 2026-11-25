"""P0 memory-relevance r1 fixes: author_window на реальном объёме + проводка.

Закрывают блокеры ревью r1:
  F1 — `author_window` обязан возвращать речь автора за период на плотном
       архиве (автор пишет НЕ в первых строках окна), bounded-чтением по
       автору/году, а не ASC-срезом первых часов периода;
  F2 — автор и период должны доезжать до `retrieve` из production-путей:
       live-нога памяти (период) и plan-driven RAG-пересборка (автор+период),
       с доставкой оригиналов в блок отдельным слоем.

Реальная SQLite-база, существующие чтения; vector-нога не вызывается.
На типе `f9d3cc72b` соответствующие проверки падают (RED), см. evidence.
"""
from __future__ import annotations

import dataclasses
import datetime
import types

import pytest

from services import mca_retrieval_context as rc
from services.database import DatabaseService

CHAT = -9003001
AUTHOR = 138811255          # автор материала
OTHER_A = 555001
OTHER_B = 555002

T2025_START = 1735689600    # 2025-01-01 UTC
T2024_MID = 1718424000      # 2024-06-15
DECEMBER = int(datetime.datetime(
    2025, 12, 20, 12, 0, tzinfo=datetime.timezone.utc).timestamp())

#: Больше старого bounded-пула (fetch_k*20 = 240 при top_k=12) на каждый
#: «шумовой» автор, чтобы ASC-срез физически не доходил до целевого автора.
NOISE_PER_AUTHOR = 150


async def _db() -> DatabaseService:
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _add_msg(db, user, text, ts, tg) -> None:
    await db.save_smart_message(
        user_id=user, chat_id=CHAT, text=text, reply_to_id=None,
        timestamp=ts, media_type="text", author_name="", message_id=tg)


async def _seed_dense_year(db) -> None:
    """3 автора × сотни строк; целевой автор говорит только в конце года."""
    tg = 7000
    for index in range(NOISE_PER_AUTHOR):
        ts = T2025_START + index * 60
        await _add_msg(db, OTHER_A, f"январская болтовня {index}", ts, tg)
        tg += 1
        await _add_msg(db, OTHER_B, f"январские планы {index}", ts + 1, tg)
        tg += 1
    for index in range(6):
        await _add_msg(db, AUTHOR, f"моя декабрьская речь {index}",
                       DECEMBER + index, tg)
        tg += 1
    await db.db.commit()


def _author_request(**kwargs):
    base = dict(chat_id=CHAT, topic="манера речи 2025 год",
                addressee_uid=OTHER_B, addressee_name="Вася",
                author_uid=AUTHOR, top_k=12)
    base.update(kwargs)
    return dataclasses.replace(
        rc.build_memory_request(**base), period_fill=True,
        memory_scope="historical")


class TestAuthorWindowOnDenseArchive:
    """F1: bounded-чтение по автору/году, а не первые строки окна."""

    @pytest.mark.asyncio
    async def test_author_absent_from_first_rows_is_still_found(self):
        db = await _db()
        await _seed_dense_year(db)
        result = await rc.retrieve(db, memory=None,
                                   request=_author_request())
        own = [cand for cand in result.candidates
               if cand.entity_type == "message"
               and cand.author_id == AUTHOR]
        assert own, (
            "речь автора за указанный год обязана находиться, даже если он "
            "не писал в первые часы периода")
        assert {rc._candidate_year(cand) for cand in own} == {2025}
        assert all(str(cand.preview).startswith("моя декабрьская речь")
                   for cand in own)

    @pytest.mark.asyncio
    async def test_author_window_does_not_return_other_years(self):
        db = await _db()
        await _seed_dense_year(db)
        await _add_msg(db, AUTHOR, "старая речь 2024", T2024_MID, 9001)
        await db.db.commit()
        result = await rc.retrieve(db, memory=None,
                                   request=_author_request())
        years = {rc._candidate_year(cand) for cand in result.candidates
                 if cand.author_id == AUTHOR}
        assert years == {2025}, "год ограничения не должен расширяться"

    @pytest.mark.asyncio
    async def test_author_read_is_bounded(self):
        db = await _db()
        await _seed_dense_year(db)
        seen: list = []
        real = db.get_author_message_periods

        async def _spy(chat_id, user_id, limit, **kwargs):
            seen.append((int(user_id), int(limit), dict(kwargs)))
            return await real(chat_id, user_id, limit, **kwargs)

        db.get_author_message_periods = _spy
        await rc.retrieve(db, memory=None, request=_author_request())
        assert seen, "авторское чтение должно использоваться"
        for uid, limit, kwargs in seen:
            assert uid == AUTHOR
            assert 0 < limit <= 12 * 20, "чтение не растёт с корпусом"
            assert kwargs.get("years") == (2025,)


class TestPlanMaterialAuthor:
    """F2: автор из плана только при запросе существующего материала."""

    @staticmethod
    def _plan(caps=(), target=None, act="reply"):
        return types.SimpleNamespace(
            capabilities_needed=tuple(caps), target_user_id=target,
            response_act=act, memory_scope="auto")

    def test_author_resolved_when_plan_requests_material(self):
        from services import direct_chat_service as dcs
        plan = self._plan(caps=("chat_memory",), target=AUTHOR)
        assert dcs._plan_material_author(plan) == AUTHOR

    def test_recipient_is_not_promoted_to_author(self):
        from services import direct_chat_service as dcs
        plan = self._plan(caps=("web_search",), target=AUTHOR)
        assert dcs._plan_material_author(plan) is None, (
            "без запроса существующего материала названный человек — "
            "получатель, а не автор")

    def test_no_plan_no_author(self):
        from services import direct_chat_service as dcs
        assert dcs._plan_material_author(None) is None


class TestOriginalsReachPayload:
    """F2: план → автор+период в retrieve → оригиналы в блоке."""

    def _service(self, db, tmp_path):
        from tests.test_direct_chat import FakeMemory, _make_service
        from tests.test_ur_c_3_real_fts import BOT_UID
        return _make_service(memory=FakeMemory(window=[], rag=""), db=db,
                             bot_id=BOT_UID)

    @pytest.mark.asyncio
    async def test_block_renders_author_originals(self, tmp_path):
        from tests.test_direct_chat import _message
        from tests.test_ur_c_3_real_fts import _stub_episodes
        db = DatabaseService(str(tmp_path / "orig.db"))
        await db.initialize()
        try:
            await _seed_dense_year(db)
            svc = self._service(db, tmp_path)
            svc._build_old_episodes = _stub_episodes_fn
            block, _hint = await svc._build_rag_block(
                CHAT, _message(text="манера речи 2025 год"), "",
                memory_scope="historical", plan_act="research",
                author_uid=AUTHOR)
            assert "<Memory_Originals>" in block
            assert "моя декабрьская речь" in block
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_rescope_passes_author_and_period_to_retrieve(
            self, tmp_path, monkeypatch):
        from tests.test_direct_chat import _message
        from services import mca_retrieval_context as _rc
        db = DatabaseService(str(tmp_path / "rescope.db"))
        await db.initialize()
        try:
            await _seed_dense_year(db)
            svc = self._service(db, tmp_path)
            svc._build_old_episodes = _stub_episodes_fn
            seen: list = []

            async def _spy(db_, memory, request):
                seen.append(request)
                return await _real_retrieve(db_, memory, request)

            _real_retrieve = _rc.retrieve
            monkeypatch.setattr(_rc, "retrieve", _spy)
            plan = types.SimpleNamespace(
                capabilities_needed=("chat_memory",),
                target_user_id=AUTHOR, response_act="research",
                memory_scope="historical", target_message_id=None)
            rag_ctx = {
                "chat_id": CHAT, "message": _message(
                    text="манера речи 2025 год"),
                "global_ctx": "", "history_sample": None,
                "projection": None, "subject_name": "Вася",
                "subject_uid": OTHER_B,
            }
            # PRE-plan блок — РЕАЛЬНЫМ методом (нулевые факты), не заглушкой:
            # именно этот случай (голый `<Memory_Originals>`) планировщик
            # раньше не находил (review r2 F3).
            pre_block, _hint = await svc._build_rag_block(
                CHAT, rag_ctx["message"], "", memory_scope="auto",
                plan_act="", author_uid=None)
            rag_ctx["block"] = pre_block
            rag_ctx["index"] = 0
            blocks = [pre_block] if pre_block else []
            out = await svc._apply_plan_memory_scope(blocks, rag_ctx, plan)
            assert seen, "пересборка обязана идти тем же retrieve"
            assert any(tuple(req.author_entity_ids) == (AUTHOR,)
                       and req.period_fill for req in seen), (
                "автор материала и период обязаны доходить до retrieval")
            assert any("моя декабрьская речь" in str(block or "")
                       for block in out), (
                "оригиналы автора должны попасть в payload хода")
        finally:
            await db.close()


async def _stub_episodes_fn(*args, **kwargs):
    return "", {"count": 0, "messages": 0, "tokens": 0, "hits": 0,
                "spans": [], "rows": [], "supplement_lines": []}


class TestMessageYearWindow:
    """N4: годовое окно на сообщениях меняет поведение (не dead logic).

    60 совпадений 2024 года заполняют FTS-лимит (top_k*2 = 24) целиком, а
    единственное совпадение 2025 года стоит в корпусе последним. Без окна
    top-N состоит только из 2024, и explicit-year фильтр оставляет пусто;
    с окном (since/until года) читаются строки целевого года.
    """

    @pytest.mark.asyncio
    async def test_target_year_rows_survive_full_out_of_year_slice(self):
        db = await _db()
        base = int(datetime.datetime(
            2024, 3, 1, tzinfo=datetime.timezone.utc).timestamp())
        # Короткие совпадения другого года выигрывают bm25 (длина документа).
        for index in range(60):
            await _add_msg(db, OTHER_A, "поздравление", base + index,
                           8000 + index)
        # Единственное совпадение целевого года — длинный документ: по rank
        # оно проигрывает и в top-N без окна не попадает.
        filler = " ".join(f"слово{index}" for index in range(120))
        await _add_msg(db, OTHER_B, f"поздравление {filler}", DECEMBER, 8900)
        await db.db.commit()
        request = rc.RetrievalRequest(
            chat_id=CHAT, query="поздравление 2025 год", top_k=12,
            period_fill=True, memory_scope="historical")
        result = await rc.retrieve(db, memory=None, request=request)
        previews = [str(cand.preview) for cand in result.candidates]
        assert any(text.startswith("поздравление слово") for text in previews), (
            "целевой год обязан читаться, даже если весь top-N занят "
            "совпадениями другого года")
        assert all(rc._candidate_year(cand) == 2025
                   for cand in result.candidates)


class TestLiveMemoryLegPeriod:

    @pytest.mark.asyncio
    async def test_explicit_year_reaches_live_memory_leg(
            self, tmp_path, monkeypatch):
        from tests.test_direct_chat import FakeMemory, _message, _make_service
        from tests.test_ur_c_3_real_fts import (
            BOT_UID, _force_budget, _global_parts, _row, _stub_episodes)
        db = DatabaseService(str(tmp_path / "live.db"))
        await db.initialize()
        try:
            await _seed_dense_year(db)
            window = [_row(i, text=f"свежая болтовня {i}", uid=40 + i,
                           ts=DECEMBER + 100 + i, tg=950 + i)
                      for i in range(3)]
            svc = _make_service(memory=FakeMemory(window=window), db=db,
                                bot_id=BOT_UID)
            _stub_episodes(svc, monkeypatch)
            _force_budget(monkeypatch, svc, 60_000)
            seen: list = []
            real = rc.retrieve

            async def _spy(db_, memory, request):
                seen.append(request)
                return await real(db_, memory, request)

            monkeypatch.setattr(rc, "retrieve", _spy)
            msg = _message(text="покажи манеру речи за 2025 год",
                          message_id=5000)
            await svc._compose_user_content(
                chat_id=CHAT, message=msg, blocks=[], chain=[],
                window=window, roster=[], suffix_map={},
                global_parts=_global_parts(), target_name="Аня",
                target_user_id=OTHER_B, trigger_message_id=5000,
                out_excluded=[], live_selection=True)
            assert seen, "live-нога памяти должна вызывать retrieve"
            assert any(req.period_fill for req in seen), (
                "названный год обязан доехать до live-ноги памяти")
        finally:
            await db.close()
