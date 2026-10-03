"""ASAP 4.1 волна 8 (T-4625, spec §9/§44; §48 Run 1-модель) — GOLDEN
сценарии whole-window: единая консолидированная матрица golden-прогонов.

Сценарии (каждый — EXPECT-список §44/§0-директива no-false-acceptance):
  G1  839-window fits → WHOLE_WINDOW, РОВНО 1 L1-запрос, coverage 100%,
      run жив до публикации (health ok);
  G2  provider/model switch → capacity cache invalidated → авто re-plan
      strategy (WHOLE_WINDOW → CAPACITY_OVERFLOW), coverage 100%
      (same window/семантика — §28);
  G3  L1 fail → Writer получает Full SourceWindow («semantic map
      unavailable — structure source yourself»), публикация НЕ теряется,
      переход на урезанный Legacy ЗАПРЕЩЁН (§48 Run 1: 23700–23701),
      L1_RESULT честно failed рядом с source-coverage 100% (R6-G-001);
  G4  Legacy от SourceWindow (snapshot source_ref) → полный XML одного
      запроса, coverage 100%, 50k-стоп dead-path;
  G5  CAPACITY_OVERFLOW с невосстановимым сегментом → deterministic
      minimal map; никогда не превращать success в 0/N (full coverage).

Все LLM-каналы — локальные моки (head-routing); обложка OFF; никаких
внешних вызовов. Консолидация поверх волн 2–7 (golden/asap41-файлы
остаются независимыми).
"""
import json
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
import services.summary_legacy_fullwindow as lfw
from services.summary_generator import SummaryGenerator

pytestmark = pytest.mark.asap41

CHAT = -100839
CHAT2 = -100940


@pytest.fixture(autouse=True)
def _review_on(monkeypatch):
    """Review-контур прод-дефолт ON (смежный флаг волн D conftest держит
    OFF для не-asap4 маркеров)."""
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L2_REVIEW_ENABLED",
                        True, raising=False)
    yield


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Чистая capacity-механика + обложка OFF (plain delivery наблюдаем).
    Патч выставляется на ВСЕ Settings-классы (reload-безопасно —
    прецедент conftest `_asap4_flags_off_by_default`)."""
    import config.settings as cs
    import services.summary_generator as sg

    def _patch_all(name, value):
        targets = [type(cs.settings), type(sl1.settings), type(sg.settings)]
        extra = getattr(cs, "Settings", None)
        if extra is not None:
            targets.append(extra)
        for cls in {c for c in targets if c is not None}:
            if hasattr(cls, name):
                monkeypatch.setattr(cls, name, value, raising=False)

    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    _patch_all("SUMMARY_COVER_ARTICLE_ENABLED", False)
    _patch_all("SUMMARY_COVER_FALLBACK_ENABLED", False)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _slot(monkeypatch, base_url, model):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", base_url,
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", model,
                        raising=False)


def _big_capacity(monkeypatch, effective=262144):
    async def fake_resolve(base_url, model, slot=None):
        return types.SimpleNamespace(
            provider="t", model=model, base_url=base_url,
            effective_context_window=int(effective), source="runtime",
            confidence="estimated", fallback_used=False)
    monkeypatch.setattr(mc, "resolve_capacity", fake_resolve)


def _rows(count, *, start_id=5000, text="сообщение о релизе и деплое"):
    return [{
        "id": start_id + i, "tg_message_id": start_id + i,
        "timestamp": 1_700_000_000 + i * 37, "user_id": 10 + (i % 5),
        "author_name": f"Участник{i % 5}", "text": f"{text} {i}",
        "media_type": "text", "reply_to_id": None,
        "is_forward": 0, "forward_source": None} for i in range(count)]


def _rows839():
    return _rows(839)


def _map_json(topic_id_lists, *, title="релиз и конфликты"):
    topics = []
    for n, group in enumerate(topic_id_lists):
        topics.append({"topic_id": f"topic_{n + 1:03d}", "title": title,
                       "message_ids": list(group),
                       "participants": ["Участник0"],
                       "short_hint": "обсуждение"})
    return json.dumps({
        "schema_version": 1,
        "topics": topics,
        "events": [], "unassigned_message_ids": [],
        "response_mode": "serious", "cover_prompt": "",
    }, ensure_ascii=False)


def _writer_doc(payload_items, *, title="Релиз и конфликты."):
    ids = [item["message_id"] for item in payload_items
           if isinstance(item.get("message_id"), int)]
    return json.dumps({
        "schema_version": 1, "title": title,
        "paragraphs": [{
            "text": "Участник0 рассказал про релиз и конфликты.",
            "emphasis_spans": [], "evidence_message_ids": ids[:3]}],
    }, ensure_ascii=False)


def _review_approved():
    return json.dumps({"status": "approved", "findings": []},
                      ensure_ascii=False)


class _HeadLLM:
    """Head-routing канон-мок: L1-запрос (map), Writer (ИСТОЧНИК), Review,
    Revision — детерминированные ответы по маркеру первого сообщения."""

    def __init__(self, *, l1_responses, writer_doc, title="Релиз и конфликты."):
        self.l1_responses = list(l1_responses)
        self.writer_doc = writer_doc
        self.calls = []

    async def generate(self, messages, **kw):
        head = messages[-1].get("content") or ""
        self.calls.append(head)
        if head.startswith("СООБЩЕНИЯ ЧАТА"):
            if self.l1_responses:
                return self.l1_responses.pop(0)
            raise AssertionError("L1: ответов не осталось")
        if head.startswith("ИСТОЧНИК"):
            return self.writer_doc
        if "ПРОВЕРЬ СТАТЬЮ" in head:
            return _review_approved()
        return _review_approved()


def _memory_mock(rows):
    memory = MagicMock()
    memory.db = object()
    memory.get_window_messages = AsyncMock(return_value=rows)
    memory.compress_and_purge = AsyncMock()
    memory.search_long_term = AsyncMock(return_value=[])
    memory.vector_search = AsyncMock(return_value=[])
    memory.get_graph_facts = AsyncMock(return_value=[])
    memory.get_rag_context = AsyncMock(return_value="")
    memory.memorize_facts = AsyncMock()
    return memory


def _make_gen(llm, rows, *, run_id):
    from services.summary_xml import XmlGroundingBuilder
    gen = SummaryGenerator(memory=_memory_mock(rows),
                           xml=XmlGroundingBuilder(),
                           llm=llm, bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    gen._deliver_l2_rich = AsyncMock(return_value=True)  # cover-ветка off/mocked
    return gen


def _events(monkeypatch):
    """Захват SUMMARY_* событий (единый transport pipeline_events._emit)."""
    from services import pipeline_events as pe
    captured = []

    def fake_emit(event_name, **kwargs):
        captured.append((event_name, dict(kwargs)))

    monkeypatch.setattr(pe, "_emit", fake_emit)
    return captured


# ── G1 (§44-A): 839-window fits → WHOLE_WINDOW, 1 запрос, coverage 100% ────

@pytest.mark.asyncio
async def test_g1_839_window_fits_whole_window_single_request(monkeypatch):
    """EXPECT §44-A: WHOLE_WINDOW; L1 requests = 1; coverage 100%;
    публикация состоялась; run жив до конца (health ok)."""
    _big_capacity(monkeypatch)
    rows = _rows839()

    async def _forced(system, slot):
        return ("tokens", 60000, "manual_cap")

    monkeypatch.setattr(sl1, "resolve_l1_effective_budget", _forced)
    from services.summary_l1_clusterizer import build_l1_payload
    payload_items = build_l1_payload(rows, CHAT)
    llm = _HeadLLM(
        l1_responses=[_map_json([[r["tg_message_id"] for r in rows]])],
        writer_doc=_writer_doc(payload_items))
    gen = _make_gen(llm, rows, run_id="w8-g1")
    from services.summary_run_log import RunContext
    ctx = RunContext(run_id="w8-g1", chat_id=CHAT, mode="hybrid_l2",
                     manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-g1", ctx=ctx)

    # WHOLE_WINDOW: ровно 1 L1-запрос с ПОЛНЫМ окном (никаких messages[:N]).
    l1_calls = [c for c in llm.calls if c.startswith("СООБЩЕНИЯ ЧАТА")]
    assert len(l1_calls) == 1
    plan = sl1._capacity_plan_snapshot()
    assert plan and plan["mode"] == "WHOLE_WINDOW"
    assert plan["segments"] is None
    # coverage 100%.
    assert sl1.last_run_coverage()["coverage_percent"] == 100.0
    assert ctx.source_coverage == 100.0
    assert ctx.source_total == 839
    # run жив до публикации: plain delivery состоялась, статус ok.
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.status == "ok"
    assert not getattr(ctx, "pipeline_health", None) or \
        ctx.pipeline_health == "ok"


# ── G2 (§44-C): provider/model switch → cache invalidated → auto re-plan ──

@pytest.mark.asyncio
async def test_g2_provider_switch_replans_strategy(monkeypatch):
    """EXPECT §44-C: смена модели → новый ключ кеша (нет переиспользования
    старой capacity) → авто-смена strategy без потери coverage/семантики
    окна (§28)."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    # Плотное окно: влезает в 131k (WHOLE_WINDOW), не влезает в 32k
    # (CAPACITY_OVERFLOW) — детерминированный EXPECT §44-C.
    rows = _rows(240, text="сообщение о релизной ветке и болях деплоя " * 16)
    llm = _mock_llm_call()
    big = await sl1.run_l1(rows=rows, chat_id=CHAT2,
                           llm_call=llm, correlation_id="w8-g2-a")
    assert big.usable
    assert sl1._capacity_plan_snapshot()["mode"] == "WHOLE_WINDOW"
    before_key = mc._cache_key("https://nano-gpt.com/v1", "deepseek-chat")
    calls_before = llm.calls["count"]

    # Chat config: DeepSeek large → local 32k (конфиг-фикстура каталога,
    # не override поверх живого каталога — AM-2).
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-32k")

    async def _catalog(url, *, headers=None):
        if "127.0.0.1:8080/props" in url:
            return {"default_generation_settings": {"n_ctx": 32768}}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    small = await sl1.run_l1(rows=rows, chat_id=CHAT2, llm_call=llm,
                             correlation_id="w8-g2-b")
    assert small.usable
    # Cache invalidated по смене (provider+base_url+model+fingerprint):
    assert before_key != mc._cache_key("http://127.0.0.1:8080/v1",
                                       "tiny-local-32k")
    # Auto strategy re-plan: больше не WHOLE_WINDOW для того же окна.
    assert sl1._capacity_plan_snapshot()["mode"] == "CAPACITY_OVERFLOW"
    assert sl1._capacity_plan_snapshot()["segments"] == \
        llm.calls["count"] - calls_before
    # Семантика задачи инвариантна: та же coverage 100%, без потери.
    assert sl1.last_run_coverage()["coverage_percent"] == 100.0
    assert sl1.last_run_coverage()["source_messages_total"] == len(rows)


def _mock_llm_call():
    calls = {"count": 0, "payloads": []}

    async def _call(messages):
        calls["count"] += 1
        user = next((m.get("content") or "" for m in messages
                     if m.get("role") == "user"), "")
        calls["payloads"].append(user)
        ids = []
        for line in user.splitlines():
            line = line.strip()
            if not line.startswith('{"'):
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item.get("message_id"), int):
                ids.append(item["message_id"])
        assert ids, "mock: без §92-элементов"
        topics = [{"topic_id": "topic_001", "title": "релиз",
                   "message_ids": ids, "participants": [], "short_hint": ""}]
        return json.dumps({"schema_version": 1, "topics": topics, "events": [],
                           "unassigned_message_ids": []}, ensure_ascii=False)

    _call.calls = calls
    return _call


# ── G3 (§46): L1 fail → Writer от окна, запрет урезанного Legacy ───────────

@pytest.mark.asyncio
async def test_g3_l1_fail_writer_from_window_no_legacy(monkeypatch):
    """EXPECT §46-L1-failure: Writer получает Full SourceWindow с
    instruction «semantic map unavailable — structure source yourself»;
    публикация состоялась; Legacy НЕ вызван; L1_RESULT честно failed рядом
    с source-coverage 100% (никогда «L1 ok» при failed — R6-G-001)."""
    _big_capacity(monkeypatch)
    rows = _rows(6, start_id=7000)
    doc = {"schema_version": 1, "title": "Писатель от окна.",
           "paragraphs": [{"text": "текст.", "emphasis_spans": [],
                           "evidence_message_ids": [7000]}]}
    writer_doc = json.dumps(doc, ensure_ascii=False)
    llm = _HeadLLM(l1_responses=["не-json-мусор", "тоже не json"],
                   writer_doc=writer_doc)
    gen = _make_gen(llm, rows, run_id="w8-g3")
    gen._legacy_run = AsyncMock()
    gen._run_legacy_pipeline = AsyncMock(return_value=False)
    events = _events(monkeypatch)
    from services.summary_run_log import RunContext
    ctx = RunContext(run_id="w8-g3", chat_id=CHAT, mode="hybrid_l2",
                     manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-g3", ctx=ctx)

    # Writer от окна: полный serialized SourceWindow + honest instruction.
    writer_content = next(c for c in llm.calls if c.startswith("ИСТОЧНИК"))
    assert "structure source yourself" in writer_content
    assert all(str(row_id) in writer_content
               for row_id in (r["tg_message_id"] for r in rows))
    # §48 Run 1: переход на урезанный Legacy из-за L1 ЗАПРЕЩЁН.
    gen._run_legacy_pipeline.assert_not_awaited()
    # Публикация состоялась (L1 failed ≠ Summary failed).
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.status == "ok"
    # Честные оси: source coverage 100% (Writer получил всё окно), при
    # этом L1 результат — failed (не маскируется успехом).
    assert ctx.source_coverage == 100.0
    l1_stages = [kw for name, kw in events
                 if name == "SUMMARY_L1_STAGE"]
    assert any(kw.get("status") == "failed"
               or kw.get("outcome") == "failed" for kw in l1_stages)


# ── G4 (§31): Legacy от SourceWindow — coverage 100%, dead-path 50k ────────

@pytest.mark.asyncio
async def test_g4_legacy_from_window_coverage_full(monkeypatch, caplog):
    """EXPECT §31: Legacy-вход = durable snapshot (source_ref) → один запрос
    с ПОЛНЫМ XML окна (никаких срезов/капов-стопов), coverage 100%,
    опубликовано."""
    snapshot_rows = _rows(560, start_id=8000)
    loaded = []

    async def fake_load(db, run_id):
        loaded.append(run_id)
        return snapshot_rows

    monkeypatch.setattr(lfw, "load_legacy_rows", fake_load)
    _big_capacity(monkeypatch, effective=400000)
    observed = []

    class _LegacyLLM:
        async def generate(self, messages, **kw):
            observed.append(messages[-1].get("content") or "")
            return "выжимка снимка."

    import services.summary_hybrid_budget as shb
    monkeypatch.setattr(shb, "hybrid_output_reserve_tokens",
                        lambda *, kind="l1", settings_obj=None: 4000)
    gen = _make_gen(_LegacyLLM(), snapshot_rows, run_id="w8-g4")
    gen._deliver_plain = AsyncMock(return_value=True)
    gen._deliver_rich = AsyncMock(return_value=True)
    from services.summary_run_log import RunContext
    ctx = RunContext(run_id="w8-g4", chat_id=CHAT, mode="off", manual=False)
    with caplog.at_level("WARNING"):
        published = await gen._run_legacy_pipeline(
            CHAT, snapshot_rows, None, None, "w8-g4", ctx=ctx, max_parts=2)
    assert published
    assert loaded == ["w8-g4"]                  # читаем snapshot по run_id
    # ПОЛНЫЙ XML одного запроса: все 560 сообщений, нулевой hard-cap стоп;
    # coverage = вход одним запросом (все 560 id в первом вызове) — flat
    # fits-ветка не понижает ctx.source_coverage (деградаций нет).
    content = observed[0]
    assert content.count("<message ") >= 560
    assert all(str(row["tg_message_id"]) in content for row in snapshot_rows)
    assert "hard cap" not in caplog.text
    assert not getattr(ctx, "pipeline_health", None) or \
        ctx.pipeline_health == "ok"


# ── G5 (§14): невосстановимый сегмент → minimal map, никогда 0/N ──────────

@pytest.mark.asyncio
async def test_g5_unrecoverable_segment_minimal_map_full_coverage(monkeypatch):
    """EXPECT §14: в overflow-режиме сегменты все падают после restore →
    deterministic minimal maps затягивают ВЕСЬ сегментный материал —
    coverage 100% по построению (не превращать в 0/N), честный
    map_degraded; Writer работает от окна и публикует."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    _big_capacity(monkeypatch, effective=262144)

    async def _force_budget(system, slot):
        return ("tokens", 260, "manual_cap")

    monkeypatch.setattr(sl1, "resolve_l1_effective_budget", _force_budget)
    rows = _rows(24, start_id=9000)
    invalid = json.dumps({"broken": True})
    payloads = sl1.build_l1_payload(rows, CHAT)
    doc = {"schema_version": 1, "title": "Минимальная карта спасла run.",
           "paragraphs": [{"text": "текст из окна.", "emphasis_spans": [],
                           "evidence_message_ids": [9001]}]}
    llm = _HeadLLM(l1_responses=[invalid] * 64,
                   writer_doc=json.dumps(doc, ensure_ascii=False))
    gen = _make_gen(llm, rows, run_id="w8-g5")
    from services.summary_run_log import RunContext
    ctx = RunContext(run_id="w8-g5", chat_id=CHAT, mode="hybrid_l2",
                     manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-g5", ctx=ctx)

    # Overflow разбил окно на сегменты (L1-запросов == сегментам).
    plan = sl1._capacity_plan_snapshot()
    assert plan["mode"] == "CAPACITY_OVERFLOW"
    assert plan["segments"] >= 2
    # Никогда не превращать в 0/N: coverage 100% (minimal maps по ledger).
    cov = sl1.last_run_coverage()
    assert cov["coverage_percent"] == 100.0
    assert cov["source_messages_total"] == 24
    assert ctx.source_coverage == 100.0
    # Writer получил SEMANTIC MAP (minimal-заготовки) И полное окно →
    # публикация состоялась.
    writer_content = next(c for c in llm.calls if c.startswith("ИСТОЧНИК"))
    assert "SEMANTIC MAP" in writer_content
    assert "Сегмент" in writer_content          # детерминированные заготовки
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.status == "ok"


# ── T-4628-original (§47): attribution против SourceWindow — 8 сценариев ────

_SCENARIOS = {
    "similar_names": [
        {"tg_message_id": 1001, "text": "я оформил подписку",
         "uid": 1, "name": "Митя_Инженер"},
        {"tg_message_id": 1002, "text": "и я тоже, ключ от соседа",
         "uid": 2, "name": "Митя_Кассир"},
    ],
    "reply_chain": [
        {"tg_message_id": 1010, "text": "кто там был на планёрке?",
         "uid": 3, "name": "Аня"},
        {"tg_message_id": 1011, "text": "только менеджер",
         "uid": 4, "name": "Борис", "reply_to_id": 1010},
        {"tg_message_id": 1012, "text": "спасибо",
         "uid": 3, "name": "Аня", "reply_to_id": 1011},
    ],
    "forwarded": [
        {"tg_message_id": 1020, "text": "смотрите анонс",
         "uid": 5, "name": "Галя", "is_forward": 1,
         "forward_source": "Канал X"},
    ],
    "quote": [
        {"tg_message_id": 1030, "text": "я сказал: «успеем к пятнице»",
         "uid": 6, "name": "Дмитрий"},
        {"tg_message_id": 1031,
         "text": "Дмитрий обещал успех к пятнице, цитата прямо в треде",
         "uid": 7, "name": "Ева", "reply_to_id": 1030},
    ],
    "joke_vs_fact": [
        {"tg_message_id": 1040, "text": "шутка: я продал сервер за булку",
         "uid": 8, "name": "Жора"},
        {"tg_message_id": 1041,
         "text": "факт: сервер списали 01.09",
         "uid": 9, "name": "Зина"},
    ],
    "numbers": [
        {"tg_message_id": 1050, "text": "итого 1 234 567 ₽ за квартал",
         "uid": 10, "name": "Иван"},
    ],
    "dates": [
        {"tg_message_id": 1060,
         "text": "подтверждаю дату 31.12.2026 (1100 мск)",
         "uid": 11, "name": "Катя"},
    ],
    "conflicting_replicas": [
        {"tg_message_id": 1070, "text": "первая редакция: текст в треде",
         "uid": 12, "name": "Лёша"},
        {"tg_message_id": 1071, "text": "вторая редакция: текст в канале",
         "uid": 13, "name": "Маша"},
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
async def test_attribution_writer_and_reviewer_use_original_source(
        scenario, monkeypatch):
    """§47-матрица (8 fixture-сценариев): Writer И Reviewer получают
    ОРИГИНАЛЬНЫЙ SourceWindow целиком — материал сценария виден детермини-
    рованно (distinct участники/reply/forward/цитата/шутка vs факт/числа/
    даты/конфликтующие реплики); без срезов/трункации. Атрибуция — решение
    модели против оригинала (прод-приёмка §48 Run 1), механизм неделим."""
    _big_capacity(monkeypatch)
    built = []
    seq = 2000
    for spec in _SCENARIOS[scenario]:
        seq += 1
        built.append({
            "id": seq, "tg_message_id": spec["tg_message_id"],
            "timestamp": 1_710_000_000 + seq * 60,
            "user_id": spec.get("uid", 1),
            "author_name": spec.get("name", "Участник"),
            "text": spec["text"], "media_type": "text",
            "reply_to_id": spec.get("reply_to_id"),
            "is_forward": spec.get("is_forward", 0),
            "forward_source": spec.get("forward_source")})
    rows = built
    payload_items = sl1.build_l1_payload(rows, CHAT)
    doc = {"schema_version": 1, "title": "Атрибуция от оригинала.",
           "paragraphs": [{"text": "абзац.", "emphasis_spans": [],
                           "evidence_message_ids": [rows[0]
                                                    ["tg_message_id"]]}]}
    llm = _HeadLLM(
        l1_responses=[_map_json([
            [r["tg_message_id"] for r in rows]])],
        writer_doc=json.dumps(doc, ensure_ascii=False))
    gen = _make_gen(llm, rows, run_id=f"w8-attr-{scenario}")
    # Reviewer-контур включён (смежный Wave-D флаг); события честные.
    from services.summary_run_log import RunContext
    ctx = RunContext(run_id=f"w8-attr-{scenario}", chat_id=CHAT,
                     mode="hybrid_l2", manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, f"w8-attr-{scenario}", ctx=ctx)
    writer_content = next(c for c in llm.calls if c.startswith("ИСТОЧНИК"))
    review_content = next(c for c in llm.calls
                          if "ПРОВЕРЬ СТАТЬЮ" in c)
    # Полный plaintext-хеш окна: каждый сценарий-текст присутствует ВЕРБАТИМ
    # у Writer (sec §92) и у Reviewer (source_window JSON) — без срезов.
    for spec in _SCENARIOS[scenario]:
        text = spec["text"]
        assert text in writer_content, f"writer: {scenario}"
        assert text in review_content, f"reviewer: {scenario}"
    # Сценарная атрибуционная база сериализована без потери полей.
    first = built[0]
    assert str(first["tg_message_id"]) in writer_content
    assert _SCENARIOS[scenario][0]["name"] in writer_content, \
        f"author: {scenario}"
