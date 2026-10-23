# -*- coding: utf-8 -*-
"""ASAP3 §2 (S10): скрытые технические лимиты не выдают потерю за пустоту.

TEST-LIFECYCLE: CONTRACT/REGRESSION owner=ASAP3-LIMITS-INVENTORY §2/S10

Проверяется то, что реально теряло настройки владельца молча:

1. Набор примеров регистра речи: одобренные владельцем строки, не влезшие в
   технический бюджет §3.2 (≤4 строки / 140 токенов / 700 симв.), раньше
   давали `reason=""`/пустой блок → композер писал `expression_examples_absent`,
   то есть потеря выглядела как «набора нет». Теперь:
   - полная потеря → честная причина `budget_excluded` (закрытый набор
     `SKIP_REASONS`, виден в манифесте/Inspector), не `absent`;
   - частичная потеря → R17-safe WARN с числами (`kept=X/Y`), текст реплик не
     логируется.
2. Досье (память) в карточке человека: `format_dossier_block` режет факты и
   мемы по символьному бюджету. Раньше вызывающий код не мог узнать об
   усечении; теперь фактический состав отдаётся в `stats` и усечение
   фиксируется WARN, а не молчанием.
"""
from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def _expression_gate_on(monkeypatch):
    monkeypatch.delenv("EXPRESSION_EXAMPLES_ENABLED", raising=False)


def _rows(count: int, *, size: int = 20) -> list[dict]:
    return [
        {"id": i + 1, "context_note": "быт",
         "input_text": "и" * size, "reply_text": "о" * size,
         "owner_approved": 1, "status": "active",
         "technique": "expression_register", "tags": ["mode:off"],
         "expression_mode": "off", "scope": "global", "chat_id": None,
         "library_version": "v1", "sensitivity_flags": []}
        for i in range(count)
    ]


def test_expression_examples_counts_are_truthful_when_all_fit():
    from services import mca_expression as ex

    block = ex.render_expression_examples_block("off", _rows(2))
    assert block.startswith('<Expression_Examples mode="off">')
    assert block.total_items == 2 and block.included_items == 2
    assert block.dropped == 0 and block.limited_by == ""


def test_expression_examples_item_cap_is_counted_not_silent():
    from services import mca_expression as ex

    block = ex.render_expression_examples_block("off", _rows(6))
    assert block.total_items == 6
    assert block.included_items == ex.EXPRESSION_EXAMPLES_MAX_ITEMS == 4
    assert block.dropped == 2
    assert block.limited_by == "items"
    # блок остаётся корректно закрытым и в бюджете §3.2
    assert block.endswith("</Expression_Examples>")
    assert ex._estimate_tokens(block) <= ex.EXPRESSION_EXAMPLES_MAX_TOKENS


@pytest.mark.asyncio
async def test_expression_examples_budget_loss_is_budget_excluded_not_absent(
        monkeypatch, caplog):
    """Одобренные строки не влезли в бюджет → честная причина, а не «absent»."""
    from services import mca_expression as ex
    from services import mca_sample_library as lib
    from services import prompt_composer as pc

    huge = _rows(1, size=900)      # одна строка сама больше 700 символов

    async def _resolve(chat_id, mode, db=None):
        return tuple(huge), ""

    monkeypatch.setattr(lib, "resolve_expression_examples_ex", _resolve)

    with caplog.at_level(logging.WARNING, logger="services.mca_expression"):
        refs = await ex.build_expression_examples_refs(777, "off")

    assert len(refs) == 1
    assert refs[0].enabled is False
    assert refs[0].text == ""
    assert refs[0].skip_reason == "budget_excluded"
    assert refs[0].skip_reason in pc.SKIP_REASONS
    assert "budget=0" in caplog.text

    # в манифесте потеря видна как техническая причина, не как пустой набор
    manifest = pc.compose_prompt(pc.PromptPlan(
        profile=pc.PROFILE_SPEECH_PLAIN,
        base_prompt="база", expression_examples=refs))
    trace = [t for t in manifest.layers
             if t.block_id == "expression_examples"][0]
    assert trace.rendered is False
    assert trace.skip_reason == "budget_excluded"


@pytest.mark.asyncio
async def test_expression_examples_partial_drop_logs_counts_not_text(
        monkeypatch, caplog):
    from services import mca_expression as ex
    from services import mca_sample_library as lib

    rows = _rows(6)

    async def _resolve(chat_id, mode, db=None):
        return tuple(rows), ""

    monkeypatch.setattr(lib, "resolve_expression_examples_ex", _resolve)

    with caplog.at_level(logging.WARNING, logger="services.mca_expression"):
        refs = await ex.build_expression_examples_refs(777, "off")

    assert len(refs) == 1 and refs[0].enabled is True
    # 4 из 6 вошли; факт частичной потери виден числами
    assert "kept=4/6" in caplog.text and "by=items" in caplog.text
    # R17: текст реплик владельца в лог не попадает
    assert "оооо" not in caplog.text and "ииии" not in caplog.text


def test_current_question_truncation_is_logged(caplog, monkeypatch):
    """Обрезка текущего вопроса (cap 800) не молчит: WARN с числами."""
    import types

    from services import direct_chat_service as dcs

    monkeypatch.setattr(dcs, "media_context_enabled", lambda: False)
    monkeypatch.setattr(dcs.hot, "get",
                        lambda key, default=None: 40 if "current_question" in key
                        else default)
    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    message = types.SimpleNamespace(text="я" * 120, caption=None, chat_id=5,
                                    message_id=1, reply_to_message=None)

    with caplog.at_level(logging.WARNING, logger="services.direct_chat_service"):
        block = svc._render_current_question(message)

    assert "truncated" in caplog.text and "chars=120 -> 40" in caplog.text
    assert "я" * 40 in block and "я" * 41 not in block
    # R17: текста сообщения в логе нет
    assert "я" * 41 not in caplog.text


def test_dossier_cap_reports_dropped_items_instead_of_silence():
    from services.dossier_prompts import format_dossier_block

    facts = ["факт номер %d с текстом" % i for i in range(30)]
    memes = ["мем %d" % i for i in range(10)]
    stats: dict = {}
    text = format_dossier_block(facts, memes, 400, stats=stats)

    assert stats["facts_total"] == 30 and stats["memes_total"] == 10
    assert stats["truncated"] is True
    assert len(text) <= 400
    # мемы урезаются первыми (spec §6) — факты держатся дольше
    assert stats["memes_kept"] < stats["memes_total"]
    assert stats["facts_kept"] >= 1


def test_dossier_without_cap_reports_no_truncation():
    from services.dossier_prompts import format_dossier_block

    stats: dict = {}
    text = format_dossier_block(["один", "два"], ["мем"], 0, stats=stats)
    assert text and "[Факты]" in text
    assert stats["truncated"] is False
    assert stats["facts_kept"] == 2 and stats["memes_kept"] == 1
