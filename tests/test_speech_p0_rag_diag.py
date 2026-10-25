# -*- coding: utf-8 -*-
"""P0C-INT R2: пустой RAG-блок объясняется, а не считается поломкой.

TEST-LIFECYCLE: CONTRACT
owner=P0-SPEECH/hotfix
why=`probes_final4.md` §5: service-ветка вернула `rows=10` и пустой блок, но
    raw не содержал ни origin'ов, ни счётчиков отбора — причину нельзя было
    назвать. Здесь фиксируется диагностика: если все строки — собственные
    выводы бота, блок обязан быть пустым (P0-правило self-echo), и это
    помечается `rag_empty_reason=all_self_origin` + `rag_empty_is_correct`.
    Защита self-echo не ослабляется: обычные факты проходят.
replace_when=если формат `<RAG_Memory>`/self-echo контракт изменится.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "probes_full"))

import harness_probe_full as H  # noqa: E402


class _Hot:
    def get(self, key, default=None):
        return default


class _Memory:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    async def get_rag_facts(self, chat_id, query, **kwargs):
        self.calls.append({"chat_id": chat_id, "query": query,
                           "kwargs": dict(kwargs)})
        return list(self._rows)


def _row(idx: int, origin: str, fact: str) -> dict:
    return {"id": 20000 + idx, "origin": origin, "fact": fact,
            "rag_ts": 1792873000 + idx, "message_timestamp": 1792873000 + idx,
            "created_at": 1792873000 + idx, "target_user": None,
            "tg_message_id": 500 + idx, "item_id": "tg:%d" % (500 + idx),
            "forward_from": "", "expired": False, "expires_at": None,
            "chat_id": -1001, "status": "confirmed", "subject_ref_id": None,
            "speaker_author_id": 42115912, "assertion_kind": "opinion",
            "attribution_method": "speaker", "provenance_channel": "chat"}


def _run(rows, global_ctx=""):
    memory = _Memory(rows)
    saved = H.service_memory

    async def _stub(root, llm):
        return memory, {"memory_class": "FakeMemory", "db_read_only": True,
                        "vec_reflected": True, "vec_dim": 3072,
                        "vec_tables": ["graph_facts_vec"]}

    H.service_memory = _stub
    try:
        return asyncio.run(H.build_rag_block(
            ROOT, {}, "вопрос", global_ctx, _Hot(), llm=None,
            source=H.RAG_SERVICE))
    finally:
        H.service_memory = saved


def test_ten_self_origin_rows_give_empty_block_with_reason():
    """Прод-случай: все 10 строк — выводы бота ⇒ пустой блок ЗАКОНЕН."""
    rows = [_row(i, "bot_self_reply", "бот сказал #%d" % i) for i in range(10)]
    block, meta = _run(rows)
    assert block == ""
    assert meta["rag_source"] == H.RAG_SERVICE
    assert meta["rows"] == 10
    assert meta["after_self_filter"] == 0
    assert meta["rag_empty_reason"] == "all_self_origin"
    assert meta["rag_empty_is_correct"] is True
    assert all(r["self_referential"] for r in meta["rows_detail"])
    assert {r["origin"] for r in meta["rows_detail"]} == {"bot_self_reply"}


def test_mixed_rows_keep_real_facts_in_the_block():
    """Self-echo отфильтрован, обычные факты проходят (защита не ослаблена)."""
    rows = ([_row(i, "chat_history", "Макс вступился за Костю #%d" % i)
             for i in range(6)]
            + [_row(10 + i, "bot_direct_reply", "бот ответил #%d" % i)
               for i in range(4)])
    block, meta = _run(rows)
    assert block.startswith("<RAG_Memory>")
    assert meta["after_self_filter"] == 6
    assert meta["after_dedup"] == 6
    assert "rag_empty_reason" not in meta
    assert "бот ответил" not in block
    detail = meta["rows_detail"]
    assert sum(1 for r in detail if r["self_referential"]) == 4
    assert sum(1 for r in detail if r["kept_after_dedup"]) == 6


def test_rows_already_in_global_context_are_deduped():
    rows = [_row(i, "chat_history", "факт номер %d" % i) for i in range(3)]
    global_ctx = "\n".join("Аня: факт номер %d, и это видно в окне" % i
                           for i in range(3))
    block, meta = _run(rows, global_ctx)
    assert block == ""
    assert meta["after_self_filter"] == 3
    assert meta["after_dedup"] == 0
    assert meta["rag_empty_reason"] == "dedup_vs_global"
    assert meta["rag_empty_is_correct"] is False


def test_empty_retrieval_is_reported_as_no_facts():
    block, meta = _run([])
    assert block == ""
    assert meta["rows"] == 0
    assert meta["rag_empty_reason"] == "no_facts"
    assert meta["rag_empty_is_correct"] is True


def test_self_echo_protection_is_not_weakened():
    """Прямая проверка правила: origin бота никогда не попадает в факты."""
    from services import provenance
    assert provenance.is_self_referential_origin("bot_self_reply") is True
    assert provenance.is_self_referential_origin("bot_direct_reply") is True
    assert provenance.is_self_referential_origin("chat_history") is False
    rows = [_row(i, "bot_self_reply", "бот сказал #%d" % i) for i in range(3)]
    block, _ = _run(rows)
    assert "бот сказал" not in block
