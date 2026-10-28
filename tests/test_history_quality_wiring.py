"""P0-HA QUALITY wiring (волна 4b → DirectChatService) — подключение
инструкционных блоков качества к реальным швам direct-хода.

Покрытие:
* (a) системный промпт извлечения сегментов содержит ПОЛНЫЙ
  HISTORY_EXTRACTION_QUALITY_BLOCK — и на константе, и на реальном
  промпте, пойманном на шве self.llm.generate (step=history_segment);
* (b) ход с выборкой (history_assembly_block передан) → собранный system
  L2 Writer содержит ПОЛНЫЙ HISTORY_COVERAGE_ASSEMBLY_BLOCK (в хвосте,
  после scrub);
* (c) ход без выборки (параметр пуст/отсутствует) — байт-паритет прежней
  сборки: system равен прежней формуле компоновки, блока нет;
* (d) оба блока проходят без усечения и переформулировки (точные байты
  констант, ровно одно вхождение, существующие инструкции не тронуты).

Без сети, без внешнего PG (кэши сброшены фикстурой); SQLite in-memory.
TEST-LIFECYCLE: CONTRACT owner=P0-HA QUALITY wiring
"""
import os
from unittest.mock import MagicMock

import pytest

from services import chat_params
from services import hot_config as hot
from services import prompt_composer as pc
from services.chat_prompts import DIRECT_VERBALIZER_SYSTEM_PROMPT
from services.database import DatabaseService
from services.direct_chat_service import (
    _HISTORY_SEGMENT_SYSTEM_PROMPT,
    DirectChatService,
)
from services.direct_execution import ChainResult, EvidenceSource
from services.prompt_style_blocks import (
    HISTORY_COVERAGE_ASSEMBLY_BLOCK,
    HISTORY_EXTRACTION_QUALITY_BLOCK,
    compose_verbalizer_system,
)
from services.summary_aliases import AliasResolver
from services.tool_router import (
    ToolContext,
    ToolDeps,
    ToolRouter,
    capture_history_sample,
)

CHAT_ID = -1001234567890

CHARACTER_BLOCK = (
    "<Persona>\nИмя: Бот. Характер: язвительный, прямой.\n</Persona>\n\n"
    "<Character_Rules>\nНе раскрывать, что ты ИИ.\n</Character_Rules>")
STYLE_DIRECTIVES = ("<Style_Requests>\nПиши без канцелярита.\n"
                    "</Style_Requests>")


@pytest.fixture(autouse=True)
def _pg_down():
    """Код-каноны и композер OFF: те же условия, что у офлайн-стендов
    (локальный PG недоступен, env-тумблер снят)."""
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    prev = os.environ.pop("UNIFIED_COMPOSER_ENABLED", None)
    yield
    hot.set_config_cache(None)
    chat_params.set_chat_params_cache(None)
    pc.reset_state()
    if prev is not None:
        os.environ["UNIFIED_COMPOSER_ENABLED"] = prev


# ── стенд сегментного шва (зеркало test_history_segments.py) ────────────────

class SegmentLLM:
    """Фейковый LLM: журналирует (промпт, kwargs), отвечает пустым JSON."""

    def __init__(self):
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None, **kw):
        self.calls.append((messages[0]["content"],
                           {"step": kw.get("step")}))
        return '{"events":[],"status":"ok"}'


async def _make_db(count) -> DatabaseService:
    """Реальная DatabaseService на SQLite in-memory; ts = tg_id = i."""
    db = DatabaseService(":memory:")
    await db.initialize()
    body = ("строка про конфиг деплоя и логи сборки, " * 6)
    for i in range(1, count + 1):
        await db.db.execute(
            "INSERT INTO smart_messages "
            "(user_id, chat_id, text, timestamp, media_type, author_name, "
            "reply_to_id, tg_message_id) "
            "VALUES (1, ?, ?, ?, 'text', 'автор', NULL, ?)",
            (CHAT_ID, f"{body} м{i}", i, i))
    await db.db.commit()
    return db


def _service(db, llm) -> DirectChatService:
    router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                 aliases=None, db=db))
    return DirectChatService(MagicMock(), db, llm, AliasResolver("{}"),
                             tool_router=router)


async def _make_turn(db, depth):
    """Захват выборки + первая страница инструмента → (ctx, raw)."""
    ctx = ToolContext(CHAT_ID, f"проанализируй последние {depth} сообщений")
    bound = await capture_history_sample(db, CHAT_ID, depth)
    assert bound is not None
    ctx.history_sample = bound
    page = await ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(),
                                     aliases=None, db=db)).dispatch(
        "get_recent_history", {"depth": depth}, ctx)
    raw = ChainResult(page, evidence_sources=[
        EvidenceSource(tool="get_recent_history", status="ok",
                       content=page, total_chars=len(page))],
        chain_meta={})
    return ctx, raw


class TestSegmentPromptWiring:
    """(a)+(d): блок качества извлечения в системном промпте сегментов."""

    def test_constant_appends_block_without_truncation(self):
        """Константа: существующий текст байт-в-байт, блок в хвосте целиком."""
        assert _HISTORY_SEGMENT_SYSTEM_PROMPT.endswith(
            HISTORY_EXTRACTION_QUALITY_BLOCK)
        assert _HISTORY_SEGMENT_SYSTEM_PROMPT.count(
            HISTORY_EXTRACTION_QUALITY_BLOCK) == 1
        base = _HISTORY_SEGMENT_SYSTEM_PROMPT[
            : -len("\n\n" + HISTORY_EXTRACTION_QUALITY_BLOCK)]
        # прежний хвост инструкции не тронут (никакой переформулировки)
        assert base.endswith("пояснений.")
        assert "Ты — извлекатель фактов" in base
        assert "Верни СТРОГО" in base

    @pytest.mark.asyncio
    async def test_segment_llm_prompt_carries_full_block(self):
        """Реальный промпт на шве generate = константа + тело сегмента:
        блок присутствует ровно один раз, без усечения."""
        db = await _make_db(20)
        llm = SegmentLLM()
        service = _service(db, llm)
        ctx, raw = await _make_turn(db, 20)
        # слот 500 < страницы ~2КБ → путь сегментации (не короткий путь)
        block = await service.collect_history_segments(
            ctx, raw, slot_chars=500, chat_id=CHAT_ID)
        assert block is not None
        seg_prompts = [p for p, kw in llm.calls
                       if kw.get("step") == "history_segment"]
        assert seg_prompts, "сегментные вызовы LLM не найдены"
        for prompt in seg_prompts:
            assert prompt.startswith(
                _HISTORY_SEGMENT_SYSTEM_PROMPT + "\n\n")
            assert prompt.count(HISTORY_EXTRACTION_QUALITY_BLOCK) == 1
            assert HISTORY_EXTRACTION_QUALITY_BLOCK in prompt


# ── стенд L2 Writer (зеркало офлайн-стендов композера) ──────────────────────

class StubLLM:
    def __init__(self) -> None:
        self.captured: list[dict] = []

    async def generate(self, messages, **kwargs):
        self.captured.append({
            "step": kwargs.get("step"),
            "messages": [dict(m) for m in messages],
        })
        return "ЗАГЛУШКА ОТВЕТА"

    def _pg(self):
        return None


class StubMemory:
    async def get_window_messages(self, chat_id):
        return []


def build_service():
    from services.direct_chat_service import DirectChatService as D

    class Stub:
        _render_current_question = D._render_current_question
        _l1_reply_block = staticmethod(D._l1_reply_block)
        _l1_speech_hints = D._l1_speech_hints
        _build_speech_understanding = D._build_speech_understanding
        _attach_l1_plan_meta = D._attach_l1_plan_meta
        _compose_speech_system = D._compose_speech_system

        async def _history_partial(self, chat_id, window):
            return False

        def __init__(self, llm):
            self.llm = llm
            self.memory = StubMemory()
            self.db = None
            self.bot_id = 999
            self.aliases = None

    return Stub, D


class TestL2AssemblyWiring:
    """(b)+(c)+(d): assembly-блок в system L2 Writer только с выборкой."""

    @pytest.mark.asyncio
    async def test_turn_with_sample_gets_full_assembly_block(self):
        Stub, D = build_service()
        llm = StubLLM()
        result = await D._l2_write_answer(
            Stub(llm), CHAT_ID, "проанализируй историю чата", temperature=0.7,
            character_block=CHARACTER_BLOCK,
            style_directives=STYLE_DIRECTIVES,
            history_assembly_block=HISTORY_COVERAGE_ASSEMBLY_BLOCK)
        assert result is not None
        system = llm.captured[-1]["messages"][0]["content"]
        assert llm.captured[-1]["step"] == "l2_writer"
        # (d) блок проходит ЦЕЛИКОМ, ровно один раз, в хвосте system
        assert HISTORY_COVERAGE_ASSEMBLY_BLOCK in system
        assert system.count(HISTORY_COVERAGE_ASSEMBLY_BLOCK) == 1
        assert system.endswith(HISTORY_COVERAGE_ASSEMBLY_BLOCK)
        # существующие инструкции не вытеснены: база на месте перед блоком
        base = system[: -len("\n\n" + HISTORY_COVERAGE_ASSEMBLY_BLOCK)]
        assert base == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "serious", "plain",
            html_safe=True, character_block=CHARACTER_BLOCK,
            style_directives=STYLE_DIRECTIVES, extent_block="")

    @pytest.mark.asyncio
    async def test_turn_without_sample_byte_parity(self):
        """Без выборки (параметр пуст или отсутствует) system байт-в-байт
        равен прежней сборке: блока нет, хвост не изменён."""
        Stub, D = build_service()
        llm = StubLLM()
        await D._l2_write_answer(
            Stub(llm), CHAT_ID, "привет", temperature=0.7,
            character_block=CHARACTER_BLOCK,
            style_directives=STYLE_DIRECTIVES)
        system_default = llm.captured[-1]["messages"][0]["content"]
        assert HISTORY_COVERAGE_ASSEMBLY_BLOCK not in system_default
        # прежняя формула сборки (композер OFF, plan=None → scrub нет)
        assert system_default == compose_verbalizer_system(
            DIRECT_VERBALIZER_SYSTEM_PROMPT, "serious", "plain",
            html_safe=True, character_block=CHARACTER_BLOCK,
            style_directives=STYLE_DIRECTIVES, extent_block="")
        # явная пустая строка == отсутствие параметра (байт-в-байт)
        llm2 = StubLLM()
        await D._l2_write_answer(
            Stub(llm2), CHAT_ID, "привет", temperature=0.7,
            character_block=CHARACTER_BLOCK,
            style_directives=STYLE_DIRECTIVES, history_assembly_block="")
        assert llm2.captured[-1]["messages"][0]["content"] == system_default
