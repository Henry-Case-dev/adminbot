"""Epic 65 — обогащение контекста (factcheck/search) + реранкинг + фокус саммари.

Тест-план:
1. format_chat_context: сборка блока, потолок символов, пустое окно → "".
2. FactCheckService.build_user_content: порядок claim → chat_context →
   user_hint → search_results; chat_context=None → блока нет.
3. search_service._rerank_usable: fail-open граница (тонкий/длинный вывод).
4. summary_generator._apply_focus: prepend + escape; None → без изменений.
"""
import pytest

from services.chat_context import format_chat_context
from services.factcheck_service import FactCheckService
from services.search_service import _rerank_usable
from services.summary_generator import _apply_focus


def _row(name="Вася", uid=1, text="привет"):
    # dict поддерживает row["key"] как sqlite3.Row
    return dict(author_name=name, user_id=uid, text=text, timestamp=1)


class TestFormatChatContext:
    def test_basic_block(self):
        rows = [_row(text="первое"), _row(name="Петя", text="второе")]
        out = format_chat_context(rows)
        assert out.startswith("<chat_context ")
        assert "НЕ доказательства" in out
        assert "[Вася]: первое" in out
        assert "[Петя]: второе" in out
        assert out.endswith("</chat_context>")

    def test_empty_rows_no_text(self):
        assert format_chat_context([]) == ""
        assert format_chat_context([_row(text=""), _row(text=None)]) == ""

    def test_char_cap(self):
        rows = [_row(text="x" * 600) for _ in range(10)]
        out = format_chat_context(rows, max_chars=1000)
        # строка "[Вася]: xxx…" = 608 симв.: 1-я влезает (608<=1000),
        # 2-я уже нет (608+608>1000)
        assert len(out) < 1200
        assert out.count("[Вася]") == 1

    def test_missing_author_uses_id(self):
        out = format_chat_context([_row(name=None, uid=42)])
        assert "[id42]:" in out


class TestFactcheckUserContentOrder:
    def test_order_claim_ctx_hint_results(self):
        out = FactCheckService.build_user_content(
            "клейм", "подсказка", None, "выдача",
            chat_context="<chat_context note=\"x\">[В]: й</chat_context>")
        i_claim = out.index("<claim>")
        i_end_claim = out.index("</claim>")
        i_ctx = out.index("<chat_context")
        i_hint = out.index("<user_hint>")
        i_res = out.index("<search_results>")
        assert i_claim < i_end_claim < i_ctx < i_hint < i_res

    def test_no_context_block_when_none(self):
        out = FactCheckService.build_user_content("клейм", None, None, "выдача")
        assert "<chat_context" not in out
        assert out.index("<claim>") < out.index("<search_results>")

    def test_forward_attr_preserved(self):
        out = FactCheckService.build_user_content(
            "клейм", None, "Channel X", "выдача",
            chat_context="<chat_context note=\"x\">y</chat_context>")
        assert 'is_forward="true"' in out
        assert out.index('is_forward') < out.index("<chat_context")


class TestRerankUsable:
    def test_thin_output_rejected(self):
        assert _rerank_usable("о" * 5000, "слишком коротко") is False
        assert _rerank_usable("о" * 5000, "") is False

    def test_not_smaller_kept_original(self):
        original = "о" * 400
        assert _rerank_usable(original, "р" * 450) is False   # не короче — смысла нет

    def test_good_output_accepted(self):
        assert _rerank_usable("о" * 4000, "р" * 800) is True


class TestApplyFocus:
    def test_prepend_and_escape(self):
        base = "<window>…</window>"
        out = _apply_focus(base, "выборы <2026>")
        assert out.startswith("<focus ")
        assert "главная тема" in out
        assert "&lt;2026&gt;" in out                  # escape сработал
        assert out.endswith(base)

    def test_none_noop(self):
        base = "<window>…</window>"
        assert _apply_focus(base, None) is base
        assert _apply_focus(base, "   ") is base

    def test_long_focus_truncated_to_200(self):
        out = _apply_focus("<w/>", "т" * 500)
        body = out.split(">", 1)[1].split("</focus>")[0]
        assert len(body.strip()) <= 200
