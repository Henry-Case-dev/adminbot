"""P0 memory-relevance (owner 2026-11-25): роли, атрибуция и период в памяти.

Прицельные контрактные проверки причин production-дефектов (сценарии B/C):
  * автор материала vs упомянутый человек vs получатель нового текста;
  * период применяется к тому материалу, к которому относится;
  * prefix-OR — генератор кандидатов, а не вердикт релевантности;
  * тонкий результат не заполняется случайными воспоминаниями;
  * служебные метаданные поиска не стоят в поверхности пересказа.

Реальная SQLite-база и существующие чтения (`save_smart_message`,
`search_messages_fts`, `get_chat_history_messages`); vector-нога не
вызывается (`memory=None`), поэтому тесты не зависят от провайдера
эмбеддингов. На базовом коммите (e3467ccb7) эти проверки падают —
см. `plans/features/vmq-onto-01/evidence/p0-memory-relevance-2026-11-25.md`.
"""
from __future__ import annotations

import dataclasses

import pytest

from services import mca_retrieval_context as rc
from services.database import DatabaseService

CHAT = -9002001
NIKITA = 777          # автор исходного материала
RECIPIENT = 888       # получатель нового текста
OTHER = 999           # прочие участники

T2021 = 1623758400    # 2021-06-15
T2024 = 1718424000    # 2024-06-15
T2025 = 1749960000    # 2025-06-15

NIKITA_VOICE = "Днюха у меня была знатная, с меня магарыч и байки."
NIKITA_OLD = "Днюха прошла, рыба клюёт сама."
GIVEN_TO_NIKITA = "Днюха у Никиты сегодня, все к столу."
UNRELATED = "Кто-нибудь видел мой ключ от гаража?"


async def _db() -> DatabaseService:
    svc = DatabaseService(":memory:")
    await svc.initialize()
    return svc


async def _add_msg(db, user, text, ts, tg) -> None:
    await db.save_smart_message(
        user_id=user, chat_id=CHAT, text=text, reply_to_id=None,
        timestamp=ts, media_type="text", author_name="", message_id=tg)


async def _seed(db) -> None:
    await _add_msg(db, NIKITA, NIKITA_OLD, T2024, 4001)
    await _add_msg(db, NIKITA, NIKITA_VOICE, T2025, 4002)
    await _add_msg(db, OTHER, GIVEN_TO_NIKITA, T2025, 4003)
    await _add_msg(db, OTHER, UNRELATED, T2025, 4004)


class TestAuthorVsMention:
    """Сценарий C: «сообщения, написанные X» ≠ «сообщения ДЛЯ X»."""

    @pytest.mark.asyncio
    async def test_addressee_is_not_an_author_filter(self):
        """Адресат («поздравь Никиту») не режет чужие сообщения о нём."""
        db = await _db()
        await _seed(db)
        request = rc.build_memory_request(
            chat_id=CHAT, topic="днюха Никиты", addressee_uid=NIKITA,
            addressee_name="Никита", top_k=12)
        result = await rc.retrieve(db, memory=None, request=request)
        authors = {cand.author_id for cand in result.candidates}
        assert NIKITA in authors, "собственная речь субъекта обязана быть"
        assert OTHER in authors, (
            "сообщение другого человека О субъекте не отбрасывается: "
            "адресат — не авторский allowlist")

    @pytest.mark.asyncio
    async def test_explicit_author_constraint_selects_only_that_author(self):
        """Явный автор материала ограничивает выдачу только его речью."""
        db = await _db()
        await _seed(db)
        request = dataclasses.replace(
            rc.build_memory_request(
                chat_id=CHAT, topic="днюха и поздравления 2025 год",
                addressee_uid=RECIPIENT, addressee_name="Вася",
                author_uid=NIKITA, top_k=12),
            period_fill=True, memory_scope="historical")
        result = await rc.retrieve(db, memory=None, request=request)
        assert result.candidates, "речь заявленного автора должна находиться"
        assert {cand.author_id for cand in result.candidates} == {NIKITA}

    def test_fact_about_person_is_not_attributed_to_that_person(self):
        """Факт о человеке, сказанный другим, не получает его авторство."""
        row = {
            "id": 1, "fact": "Никита написал поздравление брату",
            "chat_id": CHAT, "target_user": str(NIKITA),
            "speaker_author_id": OTHER, "message_timestamp": T2025,
            "origin": "chat_history", "subject_ref_id": None,
        }
        cand = rc._fact_candidate(row, "lexical", 0,
                                  lambda **kw: "fact:1")
        assert cand.author_id == OTHER
        assert cand.subject_entity_id == NIKITA

    def test_fact_without_speaker_has_no_invented_author(self):
        """Нет speaker — автор честно неизвестен, а не «тот, о ком факт»."""
        row = {
            "id": 2, "fact": "Никита любит рыбалку", "chat_id": CHAT,
            "target_user": str(NIKITA), "speaker_author_id": None,
            "message_timestamp": T2025, "origin": "chat_history",
            "subject_ref_id": None,
        }
        cand = rc._fact_candidate(row, "lexical", 0,
                                  lambda **kw: "fact:2")
        assert cand.author_id is None, (
            "subject -> author fallback смешивал роли")
        assert cand.subject_entity_id == NIKITA


class TestRoleSeparation:
    """Автор исходника и получатель нового текста — разные люди."""

    def test_request_keeps_source_author_and_recipient_apart(self):
        request = rc.build_memory_request(
            chat_id=CHAT, topic="поздравление для другого участника",
            addressee_uid=RECIPIENT, addressee_name="Вася",
            author_uid=NIKITA, top_k=10)
        assert request.author_entity_ids == (NIKITA,)
        assert request.subject_entity_ids == (RECIPIENT,)
        # адресат не объявляется «говорящим»: роли не склеиваются
        assert request.speaker_entity_id is None

    @pytest.mark.asyncio
    async def test_material_is_authored_by_source_not_recipient(self):
        db = await _db()
        await _seed(db)
        request = dataclasses.replace(
            rc.build_memory_request(
                chat_id=CHAT, topic="днюха 2025", addressee_uid=RECIPIENT,
                addressee_name="Вася", author_uid=NIKITA, top_k=12),
            period_fill=True, memory_scope="historical")
        result = await rc.retrieve(db, memory=None, request=request)
        assert result.candidates
        assert all(cand.author_id == NIKITA for cand in result.candidates)


class TestPeriodScope:
    """Период применяется к материалу автора, а не к чужим упоминаниям."""

    @pytest.mark.asyncio
    async def test_year_window_applies_to_author_messages(self):
        db = await _db()
        await _seed(db)
        request = dataclasses.replace(
            rc.build_memory_request(
                chat_id=CHAT, topic="как он говорил в 2025 году",
                addressee_uid=RECIPIENT, addressee_name="Вася",
                author_uid=NIKITA, top_k=12),
            period_fill=True, memory_scope="historical")
        result = await rc.retrieve(db, memory=None, request=request)
        assert result.candidates, "речь автора за указанный год должна быть"
        years = {rc._candidate_year(cand) for cand in result.candidates}
        assert years == {2025}, (
            f"выдача обязана ограничиться целевым годом: {years}")
        assert all(cand.author_id == NIKITA for cand in result.candidates)

    def test_without_period_no_year_window_is_invented(self):
        """Без периода окно не выдумывается (горизонт не вводится)."""
        request = rc.build_memory_request(
            chat_id=CHAT, topic="днюха", author_uid=NIKITA, top_k=10)
        assert rc._message_period_window(request, None) is None
        assert request.time_from is None and request.time_to is None

    @pytest.mark.asyncio
    async def test_thin_result_is_not_filled_with_other_material(self):
        """Нет материала в ограничениях — честно пусто, без подстановки."""
        db = await _db()
        await _seed(db)
        request = dataclasses.replace(
            rc.build_memory_request(
                chat_id=CHAT, topic="днюха 2021 год", author_uid=NIKITA,
                top_k=12),
            period_fill=True, memory_scope="historical")
        result = await rc.retrieve(db, memory=None, request=request)
        assert result.candidates == ()
        assert result.status == rc.RETRIEVAL_EMPTY


class TestPrefixOrIsOnlyACandidateGenerator:
    """Объём широкого prefix-OR не решает порядок и состав."""

    @pytest.mark.asyncio
    async def test_service_prefix_match_ranks_below_content_match(self):
        db = await _db()
        # предметное совпадение (днюх*) — старше; служебный префикс («в» →
        # «Видел.») — свежее и в FTS-ранге выше (короткий документ).
        await _add_msg(db, NIKITA, NIKITA_VOICE, T2024, 5001)
        await _add_msg(db, OTHER, "Видел.", T2025, 5002)
        request = rc.RetrievalRequest(
            chat_id=CHAT, query="днюха в стиле", top_k=12)
        result = await rc.retrieve(db, memory=None, request=request)
        previews = [cand.preview for cand in result.candidates]
        assert any("Днюха" in text for text in previews)
        assert any("Видел" in text for text in previews), (
            "лексически иначе сформулированный материал не отбрасывается")
        assert previews.index(NIKITA_VOICE) < previews.index("Видел."), (
            "служебный prefix-only матч не опережает предметный")


class TestServiceMetadataSurface:
    """Счётчик/метод поиска — служебный блок, а не материал для пересказа."""

    @pytest.mark.asyncio
    async def test_counts_do_not_open_the_result(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.tool_router import ToolContext, ToolDeps, ToolRouter
        memory = MagicMock()
        memory.search_long_term = AsyncMock(return_value=[{
            "user_id": NIKITA, "author_name": "Никита",
            "text": NIKITA_VOICE, "timestamp": T2025}])
        memory.count_mentions = AsyncMock(return_value={
            "count": 9377, "first_seen": T2024, "last_seen": T2025})
        router = ToolRouter(ToolDeps(search=MagicMock(), memory=memory,
                                     aliases=None))
        ctx = ToolContext(CHAT, "днюха")
        out = await router.dispatch(
            "query_chat_memory", {"query": "днюха"}, ctx)
        first_line = out.split("\n", 1)[0]
        assert "9377" not in first_line, (
            "служебный счётчик не должен быть первой строкой результата")
        assert NIKITA_VOICE in out
        assert "<поиск_служебное>" in out
        service_block = out.split("<поиск_служебное>", 1)[1]
        assert "9377" in service_block
        assert out.index(NIKITA_VOICE) < out.index("<поиск_служебное>"), (
            "материал идёт до служебного блока")
