"""ASAP 4.1 волна 8 (T-4627, spec §9/§46) — LADDER FIXTURES: консолидация
пяти §46-фикстур в единую матрицу fail-soft (DoD 8, 25–27).

Матрица (каждая строка — честная тройка: публикуется / coverage / health):
  M1  L1 total failure → Writer от Full SourceWindow; опубликовано;
      coverage 100%; L1_RESULT честно failed (не маскируется);
  M2  L2 unusable (writer/review не дали usable результат) → controlled
      fallback policy R4-D-029: usable-исход не теряется — LEVEL-3 Legacy
      публикует; health честно degraded (не «success»);
  M3  Style failure (style edit падает у единственного generator-шва
      _maybe_apply_cover_style → REASON_STYLE_FAILED) → базовая обложка
      публикуется; текст жив; health ok (cover-деградация не трогает text);
  M4  Base cover failure (image API падает) → Rich без image / plain;
      публикация текста состоялась; cover_status честно unavailable;
  M5  Rich publish failure (send_rich падает) → Plain rendering того же
      ResponseDocument (тот же текст, полная статья).

Все LLM-каналы/сеть — локальные моки; никаких внешних вызовов. Durable
runs OFF в фикстурах (publication gate → None; идемпотентность — fixture
зона E/T-4617), чтобы матрица была детерминированной.
"""
import json
import logging
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.cover_style_jobs as csj
import services.summary_l1_clusterizer as sl1
import services.summary_generator as sg
from services.cover_style_jobs import REASON_STYLE_FAILED
from services.summary_generator import SummaryGenerator
from services.summary_l2_writer import L2Result
from services.summary_run_log import RunContext

pytestmark = pytest.mark.asap41

CHAT = -100777
TITLE = "Лестница не роняет текст."


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Прод-дефолты зон B/C + детерминированная изоляция матрицы
    (патч по всем Settings-классам — reload-безопасно, прецедент
    conftest `_asap4_flags_off_by_default`)."""
    import config.settings as cs

    def _patch_all(name, value):
        for cls in {type(cs.settings), type(sl1.settings), type(sg.settings)}:
            if hasattr(cls, name):
                monkeypatch.setattr(cls, name, value, raising=False)

    _patch_all("SUMMARY_L2_REVIEW_ENABLED", True)
    _patch_all("SUMMARY_RUN_DURABLE_ENABLED", False)
    _patch_all("SUMMARY_COVER_FALLBACK_ENABLED", True)
    mc_clean()
    yield
    mc_clean()


def mc_clean():
    import services.model_capacity as mcap
    mcap.invalidate_capacity_cache()
    mcap._WINDOW_CACHE.clear()
    mcap._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Без реальных sleep (прецедент tests/test_summary_generator)."""
    import asyncio as real_asyncio
    fake = MagicMock()
    fake.sleep = AsyncMock(return_value=None)
    fake.Lock = real_asyncio.Lock
    monkeypatch.setattr("services.summary_generator.asyncio", fake)
    yield fake


def _big_capacity(monkeypatch, effective=262144):
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="t", model=model, base_url=base_url,
            effective_context_window=int(effective), source="runtime",
            confidence="estimated", fallback_used=False)
    import services.model_capacity as mcap
    monkeypatch.setattr(mcap, "resolve_capacity", fake_resolve)


def _rows(count, *, start_id=4100):
    return [{
        "id": start_id + i, "tg_message_id": start_id + i,
        "timestamp": 1_700_000_000 + i * 60, "user_id": 20 + (i % 4),
        "author_name": f"Участник{i % 4}", "text": f"пост номер {i}",
        "media_type": "text", "reply_to_id": None,
        "is_forward": 0, "forward_source": None} for i in range(count)]


def _map_json(ids):
    return json.dumps({
        "schema_version": 1,
        "topics": [{"topic_id": "topic_001", "title": "фасад и аренда",
                    "message_ids": list(ids),
                    "participants": ["Участник0"],
                    "short_hint": "переписка"}],
        "events": [], "unassigned_message_ids": [],
        "response_mode": "serious", "cover_prompt": "котик на фоне здания",
    }, ensure_ascii=False)


def _writer_doc(payload_items):
    ids = [item["message_id"] for item in payload_items
           if isinstance(item.get("message_id"), int)]
    return json.dumps({
        "schema_version": 1, "title": TITLE,
        "paragraphs": [
            {"text": "Участник0 рассказал про фасад и аренду.",
             "emphasis": None, "evidence_message_ids": ids[:2]},
            {"text": "Финальный абзац про соседей и Communicate.",
             "emphasis": None, "evidence_message_ids": ids[-2:]},
        ]}, ensure_ascii=False)


def _class_llm(rows):
    """Head-routing канон-мок (L1 map → Writer → Review approve)."""
    payload_items = sl1.build_l1_payload(rows, CHAT)
    writer_doc = _writer_doc(payload_items)
    ids = [r["tg_message_id"] for r in rows]

    class _LLM:
        def __init__(self):
            self.calls = []

        async def generate(self, messages, **kw):
            head = messages[-1].get("content") or ""
            self.calls.append(head)
            if head.startswith("СООБЩЕНИЯ ЧАТА"):
                return _map_json(ids)
            if head.startswith("ИСТОЧНИК"):
                return writer_doc
            if "ПРОВЕРЬ СТАТЬЮ" in head:
                return json.dumps({"status": "approved", "findings": []},
                                  ensure_ascii=False)
            return json.dumps({"status": "approved", "findings": []},
                              ensure_ascii=False)

    return _LLM(), payload_items, writer_doc


def _make_gen(rows, llm, monkeypatch, *, rich=False, plain_ok=True):
    """SummaryGenerator с моками доставки/каналов (прецедент wave-B)."""
    memory = MagicMock()
    memory.get_window_messages = AsyncMock(return_value=rows)
    memory.compress_and_purge = AsyncMock()
    memory.search_long_term = AsyncMock(return_value=[])
    memory.vector_search = AsyncMock(return_value=[])
    memory.get_graph_facts = AsyncMock(return_value=[])
    memory.get_rag_context = AsyncMock(return_value="")
    memory.memorize_facts = AsyncMock()
    gen = SummaryGenerator(memory=memory, xml=MagicMock(), llm=llm, bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    sends = {"plain": [], "rich": []}
    gen._plain_captures = sends
    monkeypatch.setattr(sg, "send_text",
                        AsyncMock(side_effect=lambda *a, **kw:
                                  (sends["plain"].append(a[2])
                                   or SimpleNamespace(message_id=1))))
    async def _send_rich(*a, **kw):
        if sends.get("fail_rich"):
            raise RuntimeError("send rich down")
        sends["rich"].append((a, dict(kw)))
        return SimpleNamespace(message_id=2)

    monkeypatch.setattr(sg, "send_rich_message", _send_rich)
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
    for cls in {type(sg.settings), type(sl1.settings)}:
        if hasattr(cls, "SUMMARY_COVER_ARTICLE_ENABLED"):
            monkeypatch.setattr(cls, "SUMMARY_COVER_ARTICLE_ENABLED",
                                rich, raising=False)
    monkeypatch.setattr(sg, "normalize_cover_prompt",
                        lambda v: ("нарисованный кот-обложка" if rich
                                   else v))
    gen._resolve_cover_style_text = AsyncMock(return_value="cinematic")
    return gen


def _png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n-fixture-bytes-")
    return str(path)


def _events(monkeypatch):
    from services import pipeline_events as pe
    captured = []

    def fake_emit(event_name, **kwargs):
        captured.append((event_name, dict(kwargs)))

    monkeypatch.setattr(pe, "_emit", fake_emit)
    return captured


def _ctx():
    return RunContext(run_id="w8-matrix", chat_id=CHAT, mode="hybrid_l2",
                      manual=False)


# ── M1 (§46): L1 total failure → Writer от окна; опубликовано ──────────────

@pytest.mark.asyncio
async def test_m1_l1_total_failure_published_coverage_health(monkeypatch):
    """Тройка матрицы: публикуется ✓; coverage (Writer-вход) 100%;
    health honest — L1_RESULT usable=False рядом с source 100%."""
    _big_capacity(monkeypatch)
    rows = _rows(4)
    doc = json.dumps({"schema_version": 1, "title": TITLE,
                      "paragraphs": [{"text": "т.", "emphasis_spans": []}]},
                     ensure_ascii=False)
    writer_doc = doc
    holder = {"calls": []}

    class _LLM:
        async def generate(self, messages, **kw):
            head = messages[-1].get("content") or ""
            holder["calls"].append(head)
            if head.startswith("СООБЩЕНИЯ ЧАТА"):
                return "мусор без json"          # ПОВТОРНО — L1 не жил
            if head.startswith("ИСТОЧНИК"):
                return writer_doc
            return json.dumps({"status": "approved", "findings": []},
                              ensure_ascii=False)

    gen = _make_gen(rows, _LLM(), monkeypatch)
    gen._run_legacy_pipeline = AsyncMock(return_value=False)
    events = _events(monkeypatch)
    ctx = _ctx()
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-m1", ctx=ctx)
    # публикуется
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.status == "ok"
    gen._run_legacy_pipeline.assert_not_awaited()
    # coverage: Writer получил всё окно (100% входа).
    assert ctx.source_coverage == 100.0
    writer_content = next(c for c in holder["calls"]
                          if c.startswith("ИСТОЧНИК"))
    assert "structure source yourself" in writer_content
    assert all(str(r["tg_message_id"]) in writer_content for r in rows)
    # health: L1 результат честно failed (не подменён успехом).
    l1_stages = [kw for name, kw in events if name == "SUMMARY_L1_STAGE"]
    assert any(kw.get("status") == "failed"
               or kw.get("outcome") == "failed" for kw in l1_stages)


# ── M2 (§46): L2 unusable → controlled fallback policy; Legacy спасает ─────

@pytest.mark.asyncio
async def test_m2_l2_unusable_usable_draft_not_lost_health_degraded(
        monkeypatch):
    """Тройка матрицы: публикуется ✓ (LEVEL-3 Legacy, R4-D-029);
    coverage: Writer-вход 100% до падения L2; health честно degraded
    (публикация Legacy не стирает деградацию — §50.53)."""
    _big_capacity(monkeypatch)
    rows = _rows(4)
    llm, payload_items, _ = _class_llm(rows)
    gen = _make_gen(rows, llm, monkeypatch)
    unusable = L2Result(status="error", document=None,
                        invalid_reason="m2_fixture_unusable", usage=None,
                        metrics={"l2_review_calls": 0}, duration_ms=0.0)
    gen._run_writer_source_stage = AsyncMock(return_value=unusable)
    gen._run_legacy_pipeline = AsyncMock(return_value=True)
    ctx = _ctx()
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-m2", ctx=ctx)
    # публикуется: usable исход не потерян — Legacy доставил текст.
    gen._run_legacy_pipeline.assert_awaited_once()
    assert ctx.fallback == "legacy"
    assert ctx.status == "ok"
    # coverage: до падения L2 Writer-вход был полным окном.
    assert ctx.source_coverage == 100.0
    # health: деградация видна (не «успех»).
    assert ctx.pipeline_health == "degraded"


# ── M3 (§46): style failure → базовая обложка публикуется ──────────────────

@pytest.mark.asyncio
async def test_m3_style_failure_base_cover_published(monkeypatch, tmp_path,
                                                     caplog):
    """Тройка матрицы: публикуется ✓ (rich с БАЗОВОЙ обложкой); coverage
    100%; health ok — style-упасть не трогает text pipeline (§34)."""
    _big_capacity(monkeypatch)
    rows = _rows(4)
    llm, _pi, _wd = _class_llm(rows)
    image_path = _png(tmp_path / "base_cover.png")
    monkeypatch.setattr(sg, "generate_image_verbose",
                        AsyncMock(return_value=(image_path, "ok")))
    monkeypatch.setattr(sg, "build_cover_media",
                        lambda path: "MEDIA:" + str(path))
    gen = _make_gen(rows, llm, monkeypatch, rich=True)
    # Шов генератора: style edit падает → REASON_STYLE_FAILED → base cover
    # (precendement wave-B: prod-механика в cover_style_jobs; точная причина
    # проходим через тот же contract REASON_STYLE_FAILED).
    gen._maybe_apply_cover_style = AsyncMock(
        return_value={"reason": REASON_STYLE_FAILED, "styled_path": None,
                      "applied": False, "outcome": csj.RESULT_BASE})
    caplog.set_level(logging.WARNING)
    ctx = _ctx()
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-m3", ctx=ctx)
    # публикуется: rich отправлен с медиа (базовая обложка, не styled).
    assert len(gen._plain_captures["rich"]) == 1
    media = gen._plain_captures["rich"][0][1]["media"]
    assert media == ["MEDIA:" + image_path]
    assert not gen._plain_captures["plain"], "текст не дублируется plain'ом"
    assert ctx.publish_status == "ok"
    # coverage 100%: Writer-вход всего окна.
    assert ctx.source_coverage == 100.0
    # health ok: cover/style деградация не трогает текст (§34).
    assert ctx.cover_status == "ok"
    assert not getattr(ctx, "pipeline_health", None) or \
        ctx.pipeline_health == "ok"


# ── M4 (§46): base cover failure → Rich без image / plain ──────────────────

@pytest.mark.asyncio
async def test_m4_base_cover_failure_text_still_published(monkeypatch):
    """Тройка матрицы: публикуется ✓ (rich без обложки — media=[]); coverage
    100%; cover_status честно unavailable; health ok (текст не страдает)."""
    _big_capacity(monkeypatch)
    rows = _rows(4)
    llm, _pi, _wd = _class_llm(rows)
    monkeypatch.setattr(sg, "generate_image_verbose",
                        AsyncMock(side_effect=RuntimeError("image api down")))
    gen = _make_gen(rows, llm, monkeypatch, rich=True)
    gen._maybe_apply_cover_style = AsyncMock(return_value=None)
    ctx = _ctx()
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-m4", ctx=ctx)
    # публикуется: rich отправлен БЕЗ медиа (или plain-фолбэк) — текст жив.
    if gen._plain_captures["rich"]:
        args, kwargs = gen._plain_captures["rich"][0]
        assert not kwargs.get("media"), \
            "media должно отсутствовать (без обложки)"
    else:
        assert gen._plain_captures["plain"], "текст обязан быть доставлен"
    assert ctx.status == "ok"
    # coverage 100%.
    assert ctx.source_coverage == 100.0
    # cover-статус честный: обложки нет.
    assert ctx.cover_status == "unavailable"
    assert not getattr(ctx, "pipeline_health", None) or \
        ctx.pipeline_health == "ok"


# ── M5 (§46): Rich failure → Plain same ResponseDocument ───────────────────

@pytest.mark.asyncio
async def test_m5_rich_publish_failure_plain_same_document(monkeypatch):
    """Тройка матрицы: публикуется ✓ (plain-канал); plain-текст содержит
    ТОТ ЖЕ документ (title + все абзацы — same ResponseDocument, никакой
    урезанный rewrite); coverage 100%; publish channel честный."""
    _big_capacity(monkeypatch)
    rows = _rows(4)
    llm, payload_items, writer_doc = _class_llm(rows)
    image_path_holder = ["no-image"]
    monkeypatch.setattr(sg, "generate_image_verbose",
                        AsyncMock(return_value=("unused.png", "ok")))
    monkeypatch.setattr(sg, "build_cover_media",
                        lambda path: "MEDIA:" + str(path))
    gen = _make_gen(rows, llm, monkeypatch, rich=True)
    sends = gen._plain_captures
    sends["fail_rich"] = True          # rich-отправка падает → plain same doc
    ctx = _ctx()
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-m5", ctx=ctx)
    # Rich-отправка упала (fail-флаг) → фолбэк plain.
    assert sends.get("fail_rich") is True
    plain = "\n".join(sends["plain"])
    assert TITLE in plain
    assert "Участник0 рассказал про фасад и аренду." in plain
    assert "Финальный абзац про соседей и Communicate." in plain
    assert ctx.publish_status == "ok"
    assert ctx.publish_channel == "text"
    # coverage 100%.
    assert ctx.source_coverage == 100.0
    assert not getattr(ctx, "pipeline_health", None) or \
        ctx.pipeline_health == "ok"
