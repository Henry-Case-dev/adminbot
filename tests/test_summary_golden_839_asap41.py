"""ASAP 4.1 волна 3 — GOLDEN: 839 synthetic messages, WHOLE_WINDOW,
semantic map → FactPackage synthesis (31+ сообщений в теме — «too_many_facts»
невозможен по построению), Writer/Reviewer от окна, run жив до публикации
(T-4607–T-4610 acceptance, spec §2 + §9; §44-A / §48 Run 1-модель).

Все LLM-каналы — локальные моки; обложка OFF; никаких внешних вызовов.
"""
import json
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_generator import SummaryGenerator

pytestmark = pytest.mark.asap41

CHAT = -100839
RUN = "golden-839"


@pytest.fixture(autouse=True)
def _review_on(monkeypatch):
    """Review-контур включён (смежный флаг волны D conftest держит OFF для
    не-asap4 тестов; прод-дефолт ON)."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L2_REVIEW_ENABLED",
                        True, raising=False)
    yield


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_COVER_ARTICLE_ENABLED",
                        False, raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_COVER_FALLBACK_ENABLED",
                        False, raising=False)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _big_capacity(monkeypatch, effective=262144):
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="t", model=model, base_url=base_url,
            effective_context_window=int(effective), source="runtime",
            confidence="estimated", fallback_used=False)
    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)


def _rows839():
    rows = []
    for i in range(839):
        rows.append({
            "id": 5000 + i, "tg_message_id": 5000 + i,
            "timestamp": 1_700_000_000 + i * 37,
            "user_id": 10 + (i % 5), "author_name": f"Участник{i % 5}",
            "text": f"сообщение {i} о релизе релизной ветки и болях деплоя",
            "media_type": "text", "reply_to_id": None,
            "is_forward": 0, "forward_source": None})
    return rows


def _map_response(rows):
    """LLM L1 → map v1: одна тема с 420+ сообщениями (31+ «фактов»-класс
    невозможен), вторая с остатком; полный покрытие message_ids."""
    ids = [r["tg_message_id"] for r in rows]
    return json.dumps({
        "schema_version": 1,
        "topics": [
            {"topic_id": "topic_001", "title": "релизная ветка и деплой",
             "message_ids": ids[:420], "participants":
             [f"Участник{k}" for k in range(5)],
             "short_hint": "обсуждение релиза, конфликтов и выката"},
            {"topic_id": "topic_002", "title": "бытовое",
             "message_ids": ids[420:], "participants": ["Участник0"],
             "short_hint": "остальная переписка"},
        ],
        "events": [{"kind": "конфликт", "message_ids": ids[:3]}],
        "relationships": [],
        "unassigned_message_ids": [],
        "response_mode": "serious", "cover_prompt": ""},
        ensure_ascii=False)


def _writer_doc(payload_items):
    ids = [item["message_id"] for item in payload_items
           if isinstance(item.get("message_id"), int)]
    return json.dumps({
        "schema_version": 1, "title": "Релиз, конфликты и дежурный хаос.",
        "paragraphs": [
            {"text": "Участник0 рассказал про релизную ветку и боли деплоя.",
             "emphasis_spans": [],
             "evidence_message_ids": ids[:3]},
            {"text": "Дальше обсуждали бытовое: конфликты и мелкие вопросы.",
             "emphasis_spans": [], "evidence_message_ids": ids[-3:]},
        ]}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_golden_839_whole_window_run_alive(monkeypatch):
    """§48 Run 1-модель: 839 сообщений; WHOLE_WINDOW (L1 requests=1);
    coverage 100%; FactPackage synthesis (420+ сообщений в теме — потолок
    не invalid); Writer/Reviewer от окна; run жив до публикации."""
    _big_capacity(monkeypatch)
    rows = _rows839()

    async def _forced(system, slot):
        return ("tokens", 60000, "manual_cap")

    monkeypatch.setattr(sl1, "resolve_l1_effective_budget", _forced)
    payload_items = sl1.build_l1_payload(rows, CHAT)

    l1_map = _map_response(rows)
    writer_doc = _writer_doc(payload_items)
    approved = json.dumps({"status": "approved", "findings": []},
                          ensure_ascii=False)
    calls = []

    class LLM:
        async def generate(self, messages, **kw):
            head = messages[-1].get("content") or ""
            calls.append(head)
            if head.startswith("СООБЩЕНИЯ ЧАТА"):
                return l1_map
            if head.startswith("ИСТОЧНИК"):
                return writer_doc
            if "ПРОВЕРЬ СТАТЬЮ" in head:
                return approved
            if "ВНЕСИ ИСПРАВЛЕНИЯ" in head:
                return writer_doc
            return approved

    memory = MagicMock()
    memory.db = object()
    memory.get_window_messages = AsyncMock(return_value=rows)
    memory.compress_and_purge = AsyncMock()
    memory.search_long_term = AsyncMock(return_value=[])
    memory.vector_search = AsyncMock(return_value=[])
    memory.get_graph_facts = AsyncMock(return_value=[])
    memory.get_rag_context = AsyncMock(return_value="")
    memory.memorize_facts = AsyncMock()
    gen = SummaryGenerator(memory=memory, xml=MagicMock(), llm=LLM(),
                           bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)

    from services.summary_run_log import RunContext
    ctx = RunContext(run_id=RUN, chat_id=CHAT, mode="hybrid_l2", manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, RUN, ctx=ctx)

    # ── L1: ровно ОДИН запрос whole-window с полным окном ─────────────────
    assert calls[0].startswith("СООБЩЕНИЯ ЧАТА")
    assert len([c for c in calls if c.startswith("СООБЩЕНИЯ ЧАТА")]) == 1
    cov = sl1.last_run_coverage()
    assert cov and cov["source_messages_total"] == 839
    assert cov["coverage_percent"] == 100.0
    # ── Writer от окна: полный serialized window + map ────────────────────
    from services.prompt_style_blocks import resolve_prompt
    from services.summary_prompts import SUMMARY_L2_WRITER_SYSTEM_PROMPT
    canon = resolve_prompt("prompts.summary_l2_writer_system_prompt",
                           SUMMARY_L2_WRITER_SYSTEM_PROMPT)
    assert "ВСПОМОГАТЕЛЬНЫЙ ИНДЕКС" in canon   # «пакет фактов — индекс»
    writer_content = next(c for c in calls if c.startswith("ИСТОЧНИК"))
    assert "Всего сообщений: 839." in writer_content
    assert "SEMANTIC MAP" in writer_content
    assert "structure source yourself" not in writer_content
    # ── Reviewer получил Draft + SourceWindow + Map ───────────────────────
    review_content = next(c for c in calls
                          if "ПРОВЕРЬ СТАТЬЮ" in c)
    assert '"source_window"' in review_content
    assert '"semantic_map"' in review_content
    # ── run жив: публикация произошла; health ok (0 деградаций) ──────────
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.source_coverage == 100.0
    assert ctx.status in ("ok", None) or ctx.status == "ok"


async def _force_auto_budget(limit):
    async def _fake(system, slot):
        return ("tokens", limit, "manual_cap")
    return _fake
