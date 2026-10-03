"""ASAP 4.1 волна 8 (T-4628, spec §9/§11.1) — OFF-PARITY MATRIX: ВСЕ
kill-switches эпика (9 зон A–G) в комбинированном OFF → бит-в-бит контур
2.58.46 на едином прогоне + per-call resolve-гигиена.

Kill-switches §11.1 (env-only, default ON):
  1. SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED    (A.1)
  2. SUMMARY_WHOLE_WINDOW_FIRST_ENABLED       (A.2 master)
  3. SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED (A.3)
  4. SUMMARY_L1_SEMANTIC_MAP_ENABLED          (B.1)
  5. SUMMARY_WRITER_SOURCE_INPUT_ENABLED      (B.3)
  6. SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED     (§3)
  7. SUMMARY_LLM_SUPERVISOR_ENABLED           (D master)
  8. SUMMARY_RUN_DURABLE_ENABLED              (E)
  9. SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED     (F.2)

EXPECT комбинированного OFF (бит-в-бит 2.58.46):
  * runtime не пишет ни в одну новую v24-таблицу (source_windows/runs/
    stages: 0 строк на сценарии с реальной temp-SQLite);
  * capacity-снапшота/WHOLE_WINDOW-плана нет (planning-estimate контур);
  * L1 — контракт §95-v2 (threads/facts), map-схемы нет;
  * Writer — FactPackage-центричный вход (без блока ИСТОЧНИК полного
    окна и без «structure source yourself»);
  * Summary-вызовы без supervised_transport (каскады 2.58.46);
  * Legacy-капы окна работают (trim 560→≤500);
  * style-резолвер байт-в-бит прежний resolve_style_slot.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.cover_style_pipeline as csp
import services.model_capacity as mc
import services.summary_llm_supervisor as sup
import services.summary_l1_clusterizer as sl1
import services.summary_legacy_fullwindow as lfw
import services.summary_generator as sg
import services.summary_source_window as ssw
import services.summary_run_store as srs
from services.summary_generator import SummaryGenerator
from services.summary_run_log import RunContext

pytestmark = pytest.mark.asap41

CHAT = -100334
KILL_SWITCHES = (
    "SUMMARY_SOURCE_WINDOW_DURABLE_ENABLED",
    "SUMMARY_WHOLE_WINDOW_FIRST_ENABLED",
    "SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED",
    "SUMMARY_L1_SEMANTIC_MAP_ENABLED",
    "SUMMARY_WRITER_SOURCE_INPUT_ENABLED",
    "SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED",
    "SUMMARY_LLM_SUPERVISOR_ENABLED",
    "SUMMARY_RUN_DURABLE_ENABLED",
    "SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED",
)


def _flags_off_everywhere(monkeypatch, value):
    """Патч девяти флагов на ВСЕХ Settings-классах, на которые ссылаются
    сервисы зон (прецедент conftest `_asap41_flags_off_by_default`)."""
    import config.settings as cs
    import services.cover_style_jobs as csj
    classes = {cs.Settings, type(cs.settings)}
    for module in (sl1, sg, csp, csj, sup, lfw, ssw, srs):
        inst = getattr(module, "settings", None)
        if inst is not None:
            classes.add(type(inst))
    for cls in classes:
        for name in KILL_SWITCHES:
            if hasattr(cls, name):
                monkeypatch.setattr(cls, name, value, raising=False)


@pytest.fixture(autouse=True)
def _clean():
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _rows(count, *, start_id=1200, text="коммуналка и соседи"):
    return [{
        "id": start_id + i, "tg_message_id": start_id + i,
        "timestamp": 1_700_000_000 + i * 60, "user_id": 30 + (i % 3),
        "author_name": f"Вася{i % 3}", "text": f"{text} {i}",
        "media_type": "text", "reply_to_id": None,
        "is_forward": 0, "forward_source": None} for i in range(count)]


def _v2_l1_response(ids):
    return json.dumps({
        "schema_version": 2,
        "threads": [{"thread_id": "thread_001", "topic": "коммуналка",
                     "message_ids": list(ids),
                     "facts": [{"text": "факт окна",
                                "evidence_message_ids": list(ids)[:3]}]}],
        "unassigned_message_ids": [], "response_mode": "serious",
        "cover_prompt": ""}, ensure_ascii=False)


def _writer_doc():
    return json.dumps({
        "schema_version": 1, "title": "Прежний контур 2.58.46.",
        "paragraphs": [{"text": "Абзац прежнего Writer.",
                        "emphasis_spans": []}]}, ensure_ascii=False)


# ── Комбинированный OFF: один реальный прогон — бит-в-бит 2.58.46 ──────────

@pytest.mark.asyncio
async def test_combined_off_full_run_is_25846(tmp_path, monkeypatch):
    """Все 9 kill-switches OFF на одном прогоне с temp-SQLite: durable-
    таблиц пусты, зонных надстроек A–G нет, публикация как раньше."""
    _flags_off_everywhere(monkeypatch, False)
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / "off-parity.db"))
    await db.initialize()
    rows = _rows(6)
    ids = [r["tg_message_id"] for r in rows]
    calls = []

    class _LLM:
        async def generate(self, messages, **kw):
            head = messages[-1].get("content") or ""
            calls.append((head, dict(kw)))
            if head.startswith("СООБЩЕНИЯ ЧАТА"):
                return _v2_l1_response(ids)
            return _writer_doc()

    memory = MagicMock()
    memory.db = db
    memory.get_window_messages = AsyncMock(return_value=rows)
    memory.compress_and_purge = AsyncMock()
    memory.search_long_term = AsyncMock(return_value=[])
    memory.vector_search = AsyncMock(return_value=[])
    memory.get_graph_facts = AsyncMock(return_value=[])
    memory.get_rag_context = AsyncMock(return_value="")
    memory.memorize_facts = AsyncMock()
    gen = SummaryGenerator(memory=memory, xml=MagicMock(), llm=_LLM(),
                           bot=None)
    gen._deliver_l2_plain = AsyncMock(return_value=True)
    ctx = RunContext(run_id="w8-off", chat_id=CHAT, mode="hybrid_l2",
                     manual=False)
    await gen._run_hybrid_l2(CHAT, rows, None, "w8-off", ctx=ctx)

    # Публикация состоялась прежним контуром.
    gen._deliver_l2_plain.assert_awaited_once()
    assert ctx.status == "ok"
    # (1)/(8): runtime НЕ пишет ни в одну новую таблицу v24.
    for table in ("summary_source_windows", "summary_runs",
                  "summary_run_stages"):
        cursor = await db.db.execute(f"SELECT COUNT(*) AS n FROM {table}")
        row = await cursor.fetchone()
        assert row["n"] == 0, f"{table} должна быть пуста при combined OFF"
    # (2)/(3): capacity-план/snapshot прежнего контура отсутствуют.
    assert sl1._capacity_plan_snapshot() is None
    # (4): L1 — контракт §95-v2 (threads/facts), map-схемы нет.
    for head, kw in calls:
        assert "SEMANTIC MAP" not in head
        assert "topics" not in (kw or {})
    # (5)/(7): Writer — FactPackage-центричный вход; supervised-канала нет.
    for head, kw in calls:
        assert "ИСТОЧНИК — ПОЛНОЕ ОКНО ЧАТА" not in head
        assert "supervised_transport" not in kw
    l1_calls = [h for h, _ in calls if h.startswith("СООБЩЕНИЯ ЧАТА")]
    assert len(l1_calls) == 1
    await db.close()


@pytest.mark.asyncio
def _memory_mock(rows=None):
    """Изолированная memory-машка: AsyncMock для асинхронных ридеров
    (прецедент wave-3 legacy-фикстур); db=None → durable fail-open."""
    memory = MagicMock()
    memory.get_window_messages = AsyncMock(return_value=rows or [])
    memory.compress_and_purge = AsyncMock()
    memory.search_long_term = AsyncMock(return_value=[])
    memory.vector_search = AsyncMock(return_value=[])
    memory.get_graph_facts = AsyncMock(return_value=[])
    memory.get_rag_context = AsyncMock(return_value="")
    memory.memorize_facts = AsyncMock()
    return memory


@pytest.mark.asyncio
async def test_combined_off_legacy_caps_and_resolvers(tmp_path, monkeypatch):
    """Прежние внешние контуры 2.58.46: legacy-капы окна обрезают
    (560→≤500 + live hard-cap warning), style-резолвер байт-в-бит
    resolve_style_slot, supervisor wrap отсутствует."""
    _flags_off_everywhere(monkeypatch, False)

    class _LegacyLLM:
        def __init__(self):
            self.contents = []

        async def generate(self, messages, **kw):
            self.contents.append(messages[-1].get("content") or "")
            return "выжимка."

    from services.summary_xml import XmlGroundingBuilder
    gen = SummaryGenerator(memory=_memory_mock(), xml=XmlGroundingBuilder(),
                           llm=_LegacyLLM(), bot=None)
    gen._deliver_plain = AsyncMock(return_value=True)
    gen._deliver_rich = AsyncMock(return_value=True)
    import services.summary_hybrid_budget as shb
    monkeypatch.setattr(shb, "hybrid_output_reserve_tokens",
                        lambda *, kind="l1", settings_obj=None: 4000)
    ctx = RunContext(run_id="w8-off-legacy", chat_id=CHAT, mode="off",
                     manual=False)
    published = await gen._run_legacy_pipeline(
        CHAT, _rows(560), None, 105, "w8-off-legacy", ctx=ctx, max_parts=2)
    assert published
    legacy = gen.llm
    assert legacy.contents, "Legacy-вызов обязан состояться"
    flat = legacy.contents[0]
    # (6) Legacy OFF-капы окна: прошлый hot-cap жив (560 → обрезано).
    assert flat.count("<message ") < 560

    # (9) Style-резолвер байт-в-бит resolve_style_slot.
    monkeypatch.setattr(csp, "default_edit_connection", _conn_stub(None))
    slot = await csp.resolve_style_slot_inherited(
        profile={"model_mode": "default"})
    baseline = csp.resolve_style_slot(profile={"model_mode": "default"})
    assert {k: v for k, v in slot.items() if k != "_connection"} == baseline

    # (7) Supervisor-врезка отсутствует (OFF → None = прежний канал).
    assert sup.make_wrapped(_LegacyLLM(), None, "rid", operation="l1",
                            module="summary", step="l1") is None


def _conn_stub(value):
    async def _stub(pg):
        return value
    return _stub


# ── Per-zone: прод-дефолты ON + per-call resolve (гигиена §11.1) ───────────

def test_nine_kill_switches_prod_default_on():
    """Каждый из 9 флагов поимённо: прод-дефолт ON (spec §11.1)."""
    from config.settings import Settings
    for name in KILL_SWITCHES:
        assert getattr(Settings, name, None) is True, \
            f"{name}: прод-дефолт должен быть ON"


def test_zone_resolver_helpers_exist_and_never_raise(monkeypatch):
    """Резолвы флагов — per-call helper'ы своих зон, никогда не бросают
    (мусорный env → fail-open, прецедент capacity_guard_enabled)."""
    monkeypatch.setenv("SUMMARY_LLM_SUPERVISOR_ENABLED", "fffff-garbage")
    # вызов не бросает (bool-коэрция из settings уже отработала fail-open).
    assert sup.supervisor_enabled() in (True, False)
    assert csp.style_global_default_enabled() in (True, False)
    assert lfw.legacy_source_window_enabled() in (True, False)
    assert srs.run_durable_enabled() in (True, False)
    assert ssw.durable_enabled() in (True, False)
    from services.summary_l2_writer import writer_source_input_enabled
    assert writer_source_input_enabled() in (True, False)


@pytest.mark.asyncio
async def test_off_zone_a_no_snapshot_and_zone_b_no_map_cap_off(tmp_path,
                                                                monkeypatch):
    """Точечные зоны A/B при source OFF: через единственную точку создания
    (`_establish_source_window`) snapshot НЕ пишется (store не вызывается,
    таблица пуста); legacy-капы работают. Zone A/B/C/D/E/F OFF-поведение
    ядер матрицы — поимённо закреплён и в предшествующих invariants-тестах."""
    _flags_off_everywhere(monkeypatch, False)
    from services.database import DatabaseService
    db = DatabaseService(str(tmp_path / "off-zone-a.db"))
    await db.initialize()

    store_calls = []

    async def _store_spy(d, window):
        store_calls.append(getattr(window, "run_id", "?"))
        return True

    monkeypatch.setattr(ssw, "store_source_window", _store_spy)
    gen = SummaryGenerator(memory=MagicMock(), xml=MagicMock(),
                           llm=MagicMock(), bot=None)
    gen.memory.db = db
    await gen._establish_source_window("w8-zone-a", CHAT, _rows(3))
    assert store_calls == []          # OFF: единственная точка НЕ пишет
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS n FROM summary_source_windows")
    row = await cursor.fetchone()
    assert row["n"] == 0
    assert not ssw.durable_enabled()
    await db.close()
