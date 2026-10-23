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

    async def _resolve(chat_id, mode, db=None, stats=None):
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

    async def _resolve(chat_id, mode, db=None, stats=None):
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


# ── Ревизия review-limits.md F1–F3, #11/#14 ──────────────────────────────────


class _PersonaDB:
    """Фейк чтения карточки: 30 фактов + 5 защищённых + 15 мемов."""

    def __init__(self, facts: int = 30, memes: int = 15) -> None:
        self._facts = facts
        self._memes = memes

    async def get_persona_card(self, chat_id, canon, limit, now):
        # Реальный SQL факты НЕ лимитирует (LIMIT только у связей).
        return {"facts": [f"факт {i}" for i in range(self._facts)],
                "links": []}

    async def get_protected_facts(self, chat_id, canon,
                                  include_chat_level=True):
        return [f"защищённый {i}" for i in range(5)]

    async def list_chat_memes(self, chat_id, canon, limit=10):
        return [{"fact": f"мем {i}"} for i in range(self._memes)]

    async def get_generated_dossier(self, chat_id, canon):
        return None


def _persona_service(db):
    import types

    from services import direct_chat_service as dcs

    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    svc.aliases = types.SimpleNamespace(canon_name=lambda name: "вася")
    svc.db = db
    svc._chat_lore_state = _lore_off
    return svc


async def _lore_off(chat_id):
    return (False, None)


@pytest.mark.asyncio
async def test_persona_card_counts_items_before_ten_item_cap(
        monkeypatch, caplog):
    """F1: totals считаются ДО срезки ≤10, иначе WARN не срабатывает."""
    from services import direct_chat_service as dcs

    monkeypatch.setattr(
        dcs.hot, "get",
        lambda key, default=None: True if key == "flags.irony_filter_enabled"
        else default)
    svc = _persona_service(_PersonaDB())

    with caplog.at_level(logging.WARNING,
                         logger="services.direct_chat_service"):
        card = await svc.build_persona_card(1, "Вася")

    assert "persona dossier capped" in caplog.text
    # 30 фактов + 5 защищённых = 35 владельческих строк, вошло 10
    assert "facts_kept=10/35" in caplog.text
    assert "memes_kept=10/15" in caplog.text
    # заголовок больше не выдаёт усечённое число за полное
    assert "знаю о тебе: 35 фактов" in card
    assert "защищённый 4" in card and "факт 4" in card
    assert "факт 5" not in card      # cap 10 держится (5 защищённых + 5 фактов)
    # R17: текстов фактов в логе нет
    assert "защищённый" not in caplog.text


@pytest.mark.asyncio
async def test_persona_card_flat_branch_logs_item_cap(monkeypatch, caplog):
    """#12 в плоской ветке (irony OFF) тот же cap 10 — тоже не молчит."""
    from services import direct_chat_service as dcs

    monkeypatch.setattr(dcs.hot, "get", lambda key, default=None: default)
    svc = _persona_service(_PersonaDB(memes=0))

    with caplog.at_level(logging.WARNING,
                         logger="services.direct_chat_service"):
        card = await svc.build_persona_card(1, "Вася")

    assert "persona dossier capped" in caplog.text
    assert "mode=flat" in caplog.text
    assert "facts_kept=10/35" in caplog.text
    assert "знаю о тебе: 35 фактов" in card


@pytest.mark.asyncio
async def test_expression_resolver_counts_approved_rows_before_item_cap(
        monkeypatch, caplog):
    """F2: 20 одобренных строк → total=20, kept=4 (реальный сev резолвера)."""
    from services import mca_expression as ex
    from services import mca_gates
    from services import mca_sample_library as lib

    rows = _rows(20)

    async def _list_samples(db=None, **kwargs):
        return list(rows)

    async def _table_ready(db):
        return True

    monkeypatch.setattr(lib, "list_samples", _list_samples)
    monkeypatch.setattr(lib, "table_ready", _table_ready)
    monkeypatch.setattr(lib, "_db_ready", lambda db: True)
    monkeypatch.setattr(mca_gates, "expression_examples_enabled",
                        lambda: True)

    stats: dict = {}
    picked, reason = await lib.resolve_expression_examples_ex(
        777, "off", db=object(), stats=stats)

    assert reason == ""
    assert len(picked) == lib.EXPRESSION_RESOLVE_MAX_ITEMS == 4
    assert stats == {"eligible": 20, "selected": 4, "dropped": 16}

    with caplog.at_level(logging.WARNING, logger="services.mca_expression"):
        refs = await ex.build_expression_examples_refs(777, "off", db=object())

    assert len(refs) == 1 and refs[0].enabled is True
    assert "kept=4/20" in caplog.text and "by=items" in caplog.text
    # состав слоя тоже правдив: total — до лимита резолвера
    assert refs[0].text.total_items == 20
    assert refs[0].text.included_items == 4
    assert refs[0].text.dropped == 16


def test_current_question_dropped_when_markers_fill_cap(caplog, monkeypatch):
    """#11: маркеры заняли весь cap → текст не вошёл, но это видно."""
    import types

    from services import direct_chat_service as dcs

    monkeypatch.setattr(dcs, "media_context_enabled", lambda: True)
    monkeypatch.setattr(dcs.hot, "get",
                        lambda key, default=None: 40 if "current_question" in key
                        else default)
    svc = dcs.DirectChatService.__new__(dcs.DirectChatService)
    message = types.SimpleNamespace(text="я" * 30, caption=None, chat_id=5,
                                    message_id=1, reply_to_message=None)

    with caplog.at_level(logging.WARNING,
                         logger="services.direct_chat_service"):
        block = svc._render_current_question(message,
                                             extra_markers=["м" * 50])

    assert "current question dropped" in caplog.text
    assert "chars=30" in caplog.text and "markers=1" in caplog.text
    assert "м" * 50 in block          # маркер выжил
    assert "я" * 30 not in block      # текст не влез
    assert "яяяя" not in caplog.text  # R17: текста сообщения в логе нет


@pytest.mark.asyncio
async def test_extract_tail_truncation_is_logged(monkeypatch, caplog):
    """#19: хвостовой срез экстрактора (8000) больше не молчит."""
    from services import summary_memory as sm

    memory = sm.MemoryManager.__new__(sm.MemoryManager)
    seen: dict = {}

    async def _extract(tail):
        seen["len"] = len(tail)
        return "[]"

    memory._extract_facts = _extract
    text = "я" * (sm._FACT_EXTRACT_MAX_CHARS + 500)

    with caplog.at_level(logging.WARNING, logger="services.summary_memory"):
        result = await memory._memorize_facts_inner(5, text, "chat_history")

    assert result["status"] == "no_new_facts"
    assert seen["len"] == sm._FACT_EXTRACT_MAX_CHARS
    assert "extract input truncated" in caplog.text
    assert f"chars={len(text)} -> {sm._FACT_EXTRACT_MAX_CHARS}" in caplog.text
    assert "я" * 20 not in caplog.text


def test_sample_field_clip_is_logged(caplog):
    """#14: обрезка полей примера — WARN (defense-in-depth для API-потолка)."""
    from services import mca_sample_library as lib

    with caplog.at_level(logging.WARNING,
                         logger="services.mca_sample_library"):
        fields = lib.normalize_fields({"input_text": "и" * 2100,
                                       "reply_text": "о" * 4100})

    assert len(fields["input_text"]) == 2000
    assert len(fields["reply_text"]) == 4000
    assert "field clipped" in caplog.text
    assert "field=input_text | chars=2100 -> 2000" in caplog.text
    assert "field=reply_text | chars=4100 -> 4000" in caplog.text
    assert "и" * 30 not in caplog.text
