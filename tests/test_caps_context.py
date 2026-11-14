"""SXR-C3-02 / SXR-C2-01 — границы context/payload caps (Direct + фактчек).

Каждый тест проверяет НАБЛЮДАЕМОЕ поведение, а не внутреннюю константу:
полный текст вопроса/цитаты доезжает до payload; evidence выше старых
потолков доставляется; при реальной ёмкости используется существующая
упаковка с честной пометкой, без фиктивного «полного прочтения».
"""
from __future__ import annotations

import types

import pytest

from services import direct_chat_service as dcs
from services import direct_execution as dx
from services import direct_l1 as l1
from services import factcheck_context as fcx
from services.token_counter import count_tokens


def _message(text: str = "", *, message_id: int = 1):
    return types.SimpleNamespace(
        text=text, caption=None, chat_id=-100, message_id=message_id,
        date=None, from_user=None, chat=types.SimpleNamespace(type="group"),
        reply_to_message=None)


# ── Current_Question / correction: полный claim ─────────────────────────────

class TestCurrentQuestionFullText:
    def test_long_claim_over_800_and_2981_reaches_block(self, monkeypatch):
        monkeypatch.setattr(dcs, "media_context_enabled", lambda: False)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        text = "УТВЕРЖДЕНИЕ " + ("очень длинная часть " * 200)  # >3000
        assert len(text) > 2981
        block = svc._render_current_question(_message(text))
        assert text.strip() in block
        assert "…" not in block

    def test_media_markers_do_not_replace_text(self, monkeypatch):
        monkeypatch.setattr(dcs, "media_context_enabled", lambda: True)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        text = "вопрос " + ("х" * 1500)
        block = svc._render_current_question(
            _message(text), extra_markers=["[медиа: photo tg:7]"])
        assert text.strip() in block
        assert "[медиа: photo tg:7]" in block

    def test_correction_frame_keeps_full_claim_and_quote(self):
        claim = "прежнее утверждение " * 150      # ~3000
        quote = "выделенный фрагмент " * 150      # ~3000
        block = dcs._render_correction_frame(
            link=dcs.CORRECTION_LINK_REPLY,
            subject=dcs.CORRECTION_SUBJECT_OWN,
            trigger_label="M2", trigger_name="Вася",
            claim_label="M1", claim_text=claim, quote_text=quote)
        assert claim.strip() in block
        assert quote.strip() in block


# ── L1 получает тот же полный вопрос/реплику, что Writer ────────────────────

class TestL1WriterParity:
    def test_l1_bot_reply_not_clipped_to_400(self):
        text = "прошлый ответ бота " * 200       # ~3400 > 400
        context = l1.build_l1_context(
            query="возражение", bot_replies=(text,), budget_tokens=100_000)
        assert text.strip() in context

    def test_l1_context_budget_is_real_window_not_800(self):
        text = "вопрос " + ("у" * 2500)
        context = l1.build_l1_context(
            query=text, current_question=text, budget_tokens=100_000)
        assert text.strip() in context


# ── Фактчек: нет тотального капа 40, фид по ёмкости ─────────────────────────

class TestFactcheckContextCaps:
    def test_total_cap_40_removed(self):
        from handlers import factcheck as hfc
        assert hfc._clamp_window(1000, 1000) == (1000, 1000)
        assert hfc._clamp_window(25, 25) == (25, 25)

    def test_render_feed_uses_capacity_not_fixed_20k(self):
        head = "шапка чата"
        body = "предмет проверки " * 250          # ~4250
        ctx = fcx.ConversationContext(
            chat_id=-100, target_tg_message_id=7, trigger_tg_message_id=8,
            messages=(
                fcx.ContextMessage(
                    message_id=1, tg_message_id=7, chat_id=-100,
                    author="Вася", timestamp=1, reply_to_tg_id=None,
                    is_forward=False, forward_source=None, text=body,
                    verbatim=True),
            ),
            window={"before": 6, "after": 6})
        feed = ctx.render_feed(char_budget=200_000)
        assert body.strip() in feed
        # предмет проверки не обрезан до 600 символов
        assert len(feed) > 4000

    def test_anchor_survives_even_if_larger_than_capacity(self):
        body = "предмет проверки " * 250
        ctx = fcx.ConversationContext(
            chat_id=-100, target_tg_message_id=7, trigger_tg_message_id=8,
            messages=(
                fcx.ContextMessage(
                    message_id=1, tg_message_id=7, chat_id=-100,
                    author="Вася", timestamp=1, reply_to_tg_id=None,
                    is_forward=False, forward_source=None, text=body,
                    verbatim=True),
            ),
            window={"before": 6, "after": 6})
        feed = ctx.render_feed(char_budget=200)
        assert body.strip() in feed          # предмет не потерян
        assert "<chat_context" in feed


# ── Evidence pack: реальное окно вместо 40%/4000 ────────────────────────────

def _raw_with(content: str):
    return types.SimpleNamespace(evidence_sources=[
        dx.EvidenceSource(tool="fetch_article", status="ok",
                          content=content, total_chars=len(content))])


class TestEvidencePackCaps:
    def test_unknown_capacity_delivers_all_evidence(self):
        content = "ИСТОЧНИК " * 1500            # ~13500 > legacy 4000
        pack = dx.build_evidence_pack(_raw_with(content), capacity_chars=0)
        assert content.strip() in pack.text
        assert pack.complete is True

    def test_no_40pct_ceiling_in_budget_formula(self):
        cap = dx.l2_evidence_budget_chars(32768, other_chars=0)
        assert cap is not None
        # старый потолок 40% окна ≈ 13 107 токенов * 4 ≈ 52 428 символов
        assert cap > 100_000

    def test_large_evidence_reaches_payload_at_real_capacity(self):
        content = "ФАКТ " * 20_000               # ~100 000 символов
        cap = dx.l2_evidence_budget_chars(32768, other_chars=0)
        pack = dx.build_evidence_pack(_raw_with(content), capacity_chars=cap)
        assert content.strip() in pack.text
        assert pack.complete is True


# ── Fallback: реальный остаток окна, честная пометка ────────────────────────

class TestFallbackCaps:
    def test_fallback_keeps_full_evidence_when_fits(self):
        evidence = "E" * 2000
        adapter = dx.build_l2_fallback_adapter(
            system="S", parts=["вопрос"], evidence=evidence, query="q",
            fallback_budget_tokens=5000)
        out = adapter({"messages": []})
        assert evidence.strip() in out["messages"][1]["content"]
        assert "обрезано" not in out["messages"][1]["content"]

    def test_fallback_evidence_cut_to_real_remaining_not_fixed_1600(self):
        evidence = "E" * 8000
        adapter = dx.build_l2_fallback_adapter(
            system="S" * 900, parts=[], evidence=evidence, query="q",
            fallback_budget_tokens=500)
        out = adapter({"messages": []})
        user = out["messages"][1]["content"]
        # 1600-символьный фиктивный срез удалён: виден реальный остаток окна
        assert "показано" in user and "токенов" in user
        assert evidence not in user

    def test_protected_reserve_does_not_double_truncate(self, monkeypatch):
        monkeypatch.setattr(
            dcs.mca_gates, "adaptive_context_budget_enabled", lambda: True)
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        block = ("<Global_Context>\nсрок 2026-11-14\n"
                 + "\n".join(f"строка контекста номер {i} " * 3
                             for i in range(60))
                 + "\n</Global_Context>")
        limit = 120
        full = svc._truncate_block_raw(block, limit, "global")
        assert count_tokens(full) > 0
        # защищённая дата в сохранённом хвосте → резерв 48 не отнимается
        assert svc._truncate_block(block, limit, "global") == full


# ── Budgets OFF: секционные бюджеты не уничтожают контекст ──────────────────

class TestBudgetsOffContext:
    def test_legacy_budget_off_returns_every_block(self):
        svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
        blocks = [("global", "история " * 500),
                  ("rag", "память " * 500),
                  ("current", "полный вопрос пользователя")]
        out = svc._apply_context_budget(blocks, enabled=False,
                                        budget_tokens=10)
        assert len(out) == 3
        assert "история " * 500 in out[0]
        assert "память " * 500 in out[1]

    def test_composer_allocation_no_pressure_keeps_all(self):
        from services import direct_context_composer as comp
        pieces = [comp.ContextPiece(key="current", kind="current",
                                    text="полный вопрос", priority=comp.P0,
                                    evictable=False, position=16),
                  comp.ContextPiece(key="rag", kind="rag",
                                    text="релевантная память " * 100,
                                    priority=comp.P1, evictable=True,
                                    position=5)]
        result = comp.allocate_budget(pieces, budget=100_000)
        assert not result.excluded
        assert not result.compressed_or_dropped
        assert result.pieces[1].text == "релевантная память " * 100
