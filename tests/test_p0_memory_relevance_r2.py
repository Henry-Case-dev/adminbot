"""P0 memory-relevance review r2: F3 — originals-only блок и пересборка.

Блокер r2: при нулевых фактах `_build_rag_block` отдавал голый
`<Memory_Originals>` без обёртки `<RAG_Memory>`, а `_apply_plan_memory_scope`
ищет блок по префиксу `<RAG_Memory>` → ровно в целевом случае (пустые факты)
автор/период из плана не доходили до `retrieve`, и речь автора не попадала
в payload.

Проверки строят PRE-plan блок РЕАЛЬНЫМ `_build_rag_block` (не заглушкой) на
фикстуре без фактов и проверяют оба пути: замена помеченного блока и вставка
на слот `rag_ctx["index"]`, когда блока не было вовсе. На предыдущем типе
`351c298c7` тесты падают (RED).
"""
from __future__ import annotations

import datetime
import types

import pytest

from services.database import DatabaseService

CHAT = -9004001
AUTHOR = 147734047
OTHER = 555101

T2025_DEC = int(datetime.datetime(
    2025, 12, 20, 12, 0, tzinfo=datetime.timezone.utc).timestamp())

AUTHOR_LINE = "совершенно другие слова автора"
OTHER_LINE = "поздравления коллеге"


async def _db(tmp_path, name="r2.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_msg(db, user, text, ts, tg) -> None:
    await db.save_smart_message(
        user_id=user, chat_id=CHAT, text=text, reply_to_id=None,
        timestamp=ts, media_type="text", author_name="", message_id=tg)


async def _seed(db) -> None:
    # Целевой автор — своя речь в декабре 2025.
    for index in range(4):
        await _add_msg(db, AUTHOR, f"{AUTHOR_LINE} {index}",
                       T2025_DEC + index, 9200 + index)
    # Другой участник — «чужой» материал того же периода.
    for index in range(4):
        await _add_msg(db, OTHER, f"{OTHER_LINE} {index}",
                       T2025_DEC + 100 + index, 9300 + index)
    await db.db.commit()


def _service(db):
    from tests.test_direct_chat import FakeMemory, _make_service
    from tests.test_ur_c_3_real_fts import BOT_UID
    svc = _make_service(memory=FakeMemory(window=[], rag=""), db=db,
                        bot_id=BOT_UID)

    async def _episodes(*args, **kwargs):
        return "", {"count": 0, "messages": 0, "tokens": 0, "hits": 0,
                    "spans": [], "rows": [], "supplement_lines": []}

    svc._build_old_episodes = _episodes
    return svc


def _plan(*, caps=("chat_memory",), target=AUTHOR, act="historical_recall",
          scope="historical"):
    return types.SimpleNamespace(
        capabilities_needed=tuple(caps), target_user_id=target,
        response_act=act, memory_scope=scope, target_message_id=None)


def _message(text="поздравления 2025"):
    from tests.test_direct_chat import _message as _mk
    return _mk(text=text)


class TestOriginalsOnlyBlockIsARagBlock:
    """F3: любой выход `_build_rag_block` — помеченный `<RAG_Memory>`."""

    @pytest.mark.asyncio
    async def test_zero_facts_originals_carry_the_wrapper(self, tmp_path):
        db = await _db(tmp_path, "wrap.db")
        try:
            await _seed(db)
            svc = _service(db)
            block, _hint = await svc._build_rag_block(
                CHAT, _message(), "", memory_scope="historical",
                plan_act="research", author_uid=AUTHOR)
            assert "<Memory_Originals>" in block
            assert block.startswith("<RAG_Memory>"), (
                "блок только из оригиналов обязан быть помечен тем же "
                "тегом, что и фактовый: иначе планировщик его не найдёт")
            assert block.rstrip().endswith("</RAG_Memory>")
        finally:
            await db.close()


class TestPlanAuthorReachesRetrieveAtZeroFacts:
    """F3: автор+период доходят до retrieve и оригиналы — в payload."""

    @pytest.mark.asyncio
    async def test_real_preplan_block_is_replaced_by_author_speech(
            self, tmp_path, monkeypatch):
        from services import mca_retrieval_context as rc
        db = await _db(tmp_path, "replace.db")
        try:
            await _seed(db)
            svc = _service(db)
            # PRE-plan блок — РЕАЛЬНЫМ методом, без автора (как в production).
            pre_block, _hint = await svc._build_rag_block(
                CHAT, _message(), "", memory_scope="auto", plan_act="",
                author_uid=None)
            assert pre_block, "pre-plan блок должен существовать (лексика)"
            assert OTHER_LINE in pre_block

            seen: list = []
            real = rc.retrieve

            async def _spy(db_, memory, request):
                seen.append(request)
                return await real(db_, memory, request)

            monkeypatch.setattr(rc, "retrieve", _spy)
            rag_ctx = {
                "chat_id": CHAT, "message": _message(), "global_ctx": "",
                "history_sample": None, "projection": None,
                "subject_name": "Вася", "subject_uid": OTHER,
                "index": 0, "block": pre_block,
            }
            out = await svc._apply_plan_memory_scope(
                [pre_block, "<Target_User>Вася</Target_User>"], rag_ctx,
                _plan())
            assert seen, "пересборка обязана вызвать retrieve"
            assert any(tuple(req.author_entity_ids) == (AUTHOR,)
                       and req.period_fill for req in seen), (
                "автор материала и период обязаны доходить до retrieval")
            merged = "\n".join(str(block or "") for block in out)
            assert AUTHOR_LINE in merged, (
                "речь автора обязана попасть в payload")
            assert merged.startswith("<RAG_Memory>") or any(
                str(block).startswith("<RAG_Memory>") for block in out)
            assert OTHER_LINE not in merged, (
                "чужой лексический материал заменён речью автора")
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_absent_block_is_inserted_at_its_slot(
            self, tmp_path, monkeypatch):
        """Блока не было вовсе (фактов и оригиналов нет) — вставка на слот."""
        from services import mca_retrieval_context as rc
        db = await _db(tmp_path, "insert.db")
        try:
            await _seed(db)
            svc = _service(db)
            seen: list = []
            real = rc.retrieve

            async def _spy(db_, memory, request):
                seen.append(request)
                return await real(db_, memory, request)

            monkeypatch.setattr(rc, "retrieve", _spy)
            rag_ctx = {
                "chat_id": CHAT, "message": _message(), "global_ctx": "",
                "history_sample": None, "projection": None,
                "subject_name": "Вася", "subject_uid": OTHER,
                "index": 1, "block": "",
            }
            out = await svc._apply_plan_memory_scope(
                ["<Global_Context>\nфон\n</Global_Context>",
                 "<Current_Question>поздравления 2025</Current_Question>"],
                rag_ctx, _plan(act="research"))
            assert seen, "пересборка обязана вызвать retrieve"
            assert any(tuple(req.author_entity_ids) == (AUTHOR,)
                       and req.period_fill for req in seen)
            assert len(out) == 3, "блок вставлен на свой слот, не потерян"
            assert str(out[1]).startswith("<RAG_Memory>")
            assert AUTHOR_LINE in str(out[1])
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_recipient_plan_does_not_read_author(self, tmp_path,
                                                       monkeypatch):
        """Роль-правило r1 сохраняется: получатель не становится автором."""
        from services import mca_retrieval_context as rc
        db = await _db(tmp_path, "recipient.db")
        try:
            await _seed(db)
            svc = _service(db)
            seen: list = []
            real = rc.retrieve

            async def _spy(db_, memory, request):
                seen.append(request)
                return await real(db_, memory, request)

            monkeypatch.setattr(rc, "retrieve", _spy)
            rag_ctx = {
                "chat_id": CHAT, "message": _message(), "global_ctx": "",
                "history_sample": None, "projection": None,
                "subject_name": "Вася", "subject_uid": OTHER,
                "index": 0, "block": "",
            }
            await svc._apply_plan_memory_scope(
                ["<Target_User>Вася</Target_User>"], rag_ctx,
                _plan(caps=("web_search",)))
            assert seen
            assert all(not tuple(req.author_entity_ids) for req in seen), (
                "получатель не должен попадать в ось автора")
        finally:
            await db.close()
